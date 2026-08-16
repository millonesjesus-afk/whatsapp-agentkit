# agent/asignacion.py — Asignación automática de leads a asesores
# Generado por AgentKit

"""
Elige automáticamente un asesor disponible para un lead recién derivado,
según su nivel de experiencia (junior/intermedio/senior) frente al valor
estimado del producto de interés, balanceando por carga de leads activos.
El supervisor/admin siempre puede reasignar manualmente después.
"""

import logging
from agent.tools import buscar_productos
from agent.memory import (
    listar_asesores, contar_leads_activos, listar_leads_esperando_asesor, asignar_asesor_a_lead,
    obtener_configuracion,
)

logger = logging.getLogger("agentkit")

NIVELES = ["junior", "intermedio", "senior"]
# Valores por defecto — configurables desde "Gestionar asesores" en el panel
# (tabla configuracion, claves umbral_senior/umbral_intermedio). Estos solo
# se usan si nunca se guardó nada desde el panel.
UMBRAL_SENIOR_DEFAULT = 1500   # S/ — leads de este valor o más requieren asesor senior
UMBRAL_INTERMEDIO_DEFAULT = 500  # S/ — leads de este valor o más requieren al menos intermedio


async def _umbrales() -> tuple[float, float]:
    """Lee los umbrales configurados desde el panel (o los valores por
    defecto si nunca se ajustaron)."""
    umbral_senior = await obtener_configuracion("umbral_senior", str(UMBRAL_SENIOR_DEFAULT))
    umbral_intermedio = await obtener_configuracion("umbral_intermedio", str(UMBRAL_INTERMEDIO_DEFAULT))
    try:
        return float(umbral_senior), float(umbral_intermedio)
    except ValueError:
        return float(UMBRAL_SENIOR_DEFAULT), float(UMBRAL_INTERMEDIO_DEFAULT)


async def _nivel_requerido(interes: str) -> str:
    """Estima el nivel de experiencia necesario según el precio del producto de interés."""
    if not interes:
        return "intermedio"
    productos = await buscar_productos(interes, limite=1)
    if not productos:
        return "intermedio"
    try:
        precio = float(productos[0].get("PRECIO", ""))
    except (TypeError, ValueError):
        return "intermedio"
    umbral_senior, umbral_intermedio = await _umbrales()
    if precio >= umbral_senior:
        return "senior"
    if precio >= umbral_intermedio:
        return "intermedio"
    return "junior"


async def elegir_asesor_automatico(interes: str) -> str | None:
    """Retorna el username del asesor más adecuado y disponible, o None si no hay ninguno."""
    asesores = await listar_asesores()
    disponibles = [a for a in asesores if a.get("disponible")]
    if not disponibles:
        return None

    nivel_req = await _nivel_requerido(interes)
    idx_req = NIVELES.index(nivel_req)

    def nivel_idx(asesor: dict) -> int:
        return NIVELES.index(asesor["nivel"]) if asesor.get("nivel") in NIVELES else NIVELES.index("intermedio")

    candidatos = [a for a in disponibles if nivel_idx(a) >= idx_req]
    if not candidatos:
        # Mejor asignar a alguien disponible (aunque no tenga el nivel ideal)
        # que dejar el lead sin atender.
        candidatos = disponibles

    cargas = []
    for asesor in candidatos:
        carga = await contar_leads_activos(asesor["username"])
        cargas.append((carga, asesor["username"]))
    cargas.sort(key=lambda item: item[0])

    elegido = cargas[0][1]
    logger.info(f"Asignación automática: {elegido} (nivel requerido: {nivel_req})")
    return elegido


async def asignar_lead_pendiente_a_asesor(username: str, nivel_asesor: str | None) -> str | None:
    """
    Cuando un asesor se pone disponible, revisa si hay leads que se quedaron
    esperando (derivados a un asesor, pero sin nadie disponible en su
    momento) y le asigna SOLO EL MÁS ANTIGUO que su nivel pueda atender —
    para que un lead no quede huérfano para siempre, sin dumpear toda la
    cola acumulada sobre el primer asesor que se conecta. Si se conectan
    varios asesores seguidos, la cola se reparte entre ellos de a uno, en
    vez de que el primero se lleve todo.

    Si ninguno de los pendientes calza con su nivel, igual le asigna el más
    antiguo (mejor atenderlo con el nivel que sea, que dejarlo esperando
    indefinidamente). Retorna el teléfono asignado, o None si no había nada
    pendiente.
    """
    pendientes = await listar_leads_esperando_asesor()
    if not pendientes:
        return None

    idx_asesor = NIVELES.index(nivel_asesor) if nivel_asesor in NIVELES else NIVELES.index("intermedio")

    for lead in pendientes:
        nivel_req = await _nivel_requerido(lead.get("interes") or "")
        if idx_asesor >= NIVELES.index(nivel_req):
            await asignar_asesor_a_lead(lead["telefono"], username)
            logger.info(f"Lead {lead['telefono']} (en espera) asignado a {username} al ponerse disponible")
            return lead["telefono"]

    # Ninguno calzaba con su nivel — mejor atender al más antiguo que dejarlo esperando.
    lead = pendientes[0]
    await asignar_asesor_a_lead(lead["telefono"], username)
    logger.info(f"Lead {lead['telefono']} (en espera, sin match de nivel) asignado a {username} al ponerse disponible")
    return lead["telefono"]
