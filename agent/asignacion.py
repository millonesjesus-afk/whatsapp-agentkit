# agent/asignacion.py — Asignación automática de leads a asesores
# Generado por AgentKit

"""
Elige automáticamente un asesor disponible para un lead recién derivado,
según su nivel de experiencia (junior/intermedio/senior) frente al valor
estimado del producto de interés, balanceando por carga de leads activos.
El supervisor/admin siempre puede reasignar manualmente después.
"""

import logging
from datetime import datetime, timedelta
from agent.tools import buscar_productos, obtener_estado_horario_atencion
from agent.memory import (
    listar_asesores, contar_leads_activos, listar_leads_esperando_asesor, asignar_asesor_a_lead,
    obtener_configuracion, ejecutar_ciclo_de_espera, rotar_asignacion_por_inactividad,
    enviar_a_cola_de_supervision, listar_negocios, obtener_lead, obtener_timestamp_ultimo_mensaje_usuario,
)

logger = logging.getLogger("agentkit")

NIVELES = ["junior", "intermedio", "senior"]
# Valores por defecto — configurables desde "Gestionar asesores" en el panel
# (tabla configuracion, claves umbral_senior/umbral_intermedio). Estos solo
# se usan si nunca se guardó nada desde el panel.
UMBRAL_SENIOR_DEFAULT = 1500   # S/ — leads de este valor o más requieren asesor senior
UMBRAL_INTERMEDIO_DEFAULT = 500  # S/ — leads de este valor o más requieren al menos intermedio


async def _umbrales(negocio_id: str | None = None) -> tuple[float, float]:
    """Lee los umbrales configurados desde el panel para ESTE negocio (o los
    valores por defecto si ese negocio nunca los ajustó). `negocio_id=None`
    conserva el comportamiento anterior (fila global) para cualquier
    llamador que no lo pase — mismo criterio de compatibilidad que el resto
    de `Configuracion` (ver `obtener_configuracion`, Gate 5.2). Sin
    override propio, NUNCA hereda el valor global de otro negocio ni de la
    fila global — cae directo al default de este módulo."""
    umbral_senior = await obtener_configuracion("umbral_senior", str(UMBRAL_SENIOR_DEFAULT), negocio_id=negocio_id)
    umbral_intermedio = await obtener_configuracion("umbral_intermedio", str(UMBRAL_INTERMEDIO_DEFAULT), negocio_id=negocio_id)
    try:
        return float(umbral_senior), float(umbral_intermedio)
    except ValueError:
        return float(UMBRAL_SENIOR_DEFAULT), float(UMBRAL_INTERMEDIO_DEFAULT)


async def _nivel_requerido(interes: str, negocio_id: str | None) -> str:
    """Estima el nivel de experiencia necesario según el precio del producto
    de interés. `negocio_id` (Gate 4.4): buscar_productos falla cerrado
    (lista vacía) si es None, así que un Negocio no resuelto cae al nivel
    "intermedio" por defecto, igual que un interés vacío."""
    if not interes:
        return "intermedio"
    productos = await buscar_productos(interes, negocio_id, limite=1)
    if not productos:
        return "intermedio"
    try:
        precio = float(productos[0].get("PRECIO", ""))
    except (TypeError, ValueError):
        return "intermedio"
    umbral_senior, umbral_intermedio = await _umbrales(negocio_id)
    if precio >= umbral_senior:
        return "senior"
    if precio >= umbral_intermedio:
        return "intermedio"
    return "junior"


async def negocio_abierto_ahora(negocio_id: str | None) -> bool:
    """¿El negocio atiende AHORA (hora de Lima, según su `HorarioAtencion`, con el fallback de siempre
    lunes a sábado 8:00-19:00)? Misma función que usa Gabi para saber si hay asesores humanos."""
    return bool((await obtener_estado_horario_atencion(negocio_id))["dentro_de_horario"])


async def elegir_asesor_automatico(
    interes: str, negocio_id: str | None, excluir: str | None = None, respetar_horario: bool = True,
) -> str | None:
    """Retorna el username del asesor más adecuado y disponible, o None si no hay ninguno.

    `respetar_horario` (2026-10-07, Fase 1 de la política de asignación): con el negocio CERRADO
    ahora devuelve None aunque haya asesores con el interruptor `disponible` encendido. Pasaba que
    un lead derivado el domingo de madrugada se asignaba a alguien que dormía, Gabi se pausaba al
    instante y nadie lo veía hasta que su ventana de 24 h de WhatsApp ya había cerrado. El lead queda
    derivado, SIN asesor y con Gabi activa, y `asignar_cola_pendiente_al_abrir` (Cron) lo reparte
    cuando el negocio abre. Solo se desactiva (`False`) en el modo sin IA (`respaldo_sin_ia`), que
    tiene su propia regla de asignación fuera de horario. Las asignaciones MANUALES (panel) no pasan
    por esta función.

    `negocio_id` (Gate 5.4, T2): esta función llama a listar_asesores(), que
    ahora exige negocio_id. Se llama desde el flujo de mensajes del webhook
    (ver main.py), donde el Canal —y por lo tanto el Negocio— puede no
    haberse podido resolver todavía; con negocio_id=None se falla cerrado
    (no hay ningún asesor elegible) en vez de listar asesores de cualquier
    Negocio.

    `excluir` (Punto 2, 2026-09-29): usado por `rotar_leads_inactivos` para
    pedir "el mejor asesor DISTINTO del que ya no respondió" — sin esto, la
    rotación por inactividad podría "rotar" un lead al mismo asesor que
    acaba de fallar en responder, si es el único (o el de menor carga)."""
    if negocio_id is None:
        return None
    if respetar_horario and not await negocio_abierto_ahora(negocio_id):
        logger.info("Asignación automática omitida: el negocio está cerrado ahora — el lead queda en la cola hasta que abra")
        return None
    asesores = await listar_asesores(negocio_id)
    disponibles = [a for a in asesores if a.get("disponible") and a["username"] != excluir]
    if not disponibles:
        return None

    nivel_req = await _nivel_requerido(interes, negocio_id)
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


async def asignar_lead_pendiente_a_asesor(username: str, nivel_asesor: str | None, negocio_id: str) -> str | None:
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

    `negocio_id` (Gate 5.4, T2) obligatorio — a diferencia de
    elegir_asesor_automatico, quien llama a esta función siempre lo hace
    desde una sesión HTTP real del panel (el propio asesor togglea su
    disponibilidad), así que hay un Negocio legítimo garantizado.
    """
    # Los que pasaron a la cola de supervisión (ningún asesor los atendió) NO
    # se reparten solos: los trata un supervisor. Si no, el primer asesor en
    # ponerse "disponible" —quizá el mismo que no respondió— los recibiría.
    pendientes = [
        l for l in await listar_leads_esperando_asesor(negocio_id)
        if not l.get("escalado_supervision_en")
    ]
    if not pendientes:
        return None

    idx_asesor = NIVELES.index(nivel_asesor) if nivel_asesor in NIVELES else NIVELES.index("intermedio")

    for lead in pendientes:
        nivel_req = await _nivel_requerido(lead.get("interes") or "", negocio_id)
        if idx_asesor >= NIVELES.index(nivel_req):
            await asignar_asesor_a_lead(lead["telefono"], username, automatico=True)
            logger.info(f"Lead {lead['telefono']} (en espera) asignado a {username} al ponerse disponible")
            return lead["telefono"]

    # Ninguno calzaba con su nivel — mejor atender al más antiguo que dejarlo esperando.
    lead = pendientes[0]
    await asignar_asesor_a_lead(lead["telefono"], username, automatico=True)
    logger.info(f"Lead {lead['telefono']} (en espera, sin match de nivel) asignado a {username} al ponerse disponible")
    return lead["telefono"]


async def rotar_leads_inactivos(intervalo_minutos: int = 5, umbral_rotacion_minutos: int = 30) -> list[str]:
    """Punto 2 (2026-09-29) — el orquestador real del Cron nuevo (reemplaza
    a `liberar_asignaciones_inactivas`, 24h de reloj sin distinguir turno).
    `agent/memory.py::listar_leads_para_rotar_o_liberar` lleva la cuenta de
    minutos de TURNO (negocio abierto + asesor `disponible`) y ya resuelve
    directo los que corresponde LIBERAR (no necesita elegir a nadie) — acá
    solo se resuelven los que corresponde ROTAR, porque elegir al segundo
    asesor (nivel/carga, `elegir_asesor_automatico`) vive en este módulo,
    no en memory.py (memory.py no puede importar de acá: este módulo ya
    importa de memory.py, el ciclo rompería el arranque).

    Si no hay ningún otro asesor disponible para rotar (excluyendo al que
    ya no respondió), no tiene sentido esperar otros 30 min sin nadie a
    quien pasárselo — se libera directo, mismo motivo="timeout_inactividad"
    de siempre.

    Retorna los teléfonos efectivamente rotados, para que el script que
    llama esto pueda loguearlo."""
    return (await ejecutar_ciclo_de_rotacion(intervalo_minutos, umbral_rotacion_minutos))["rotados"]


async def ejecutar_ciclo_de_rotacion(intervalo_minutos: int = 5, umbral_rotacion_minutos: int = 30) -> dict:
    """Una corrida completa del Cron: devuelve `{"rotados": [...], "escalados":
    [...]}` con los teléfonos rotados a un segundo asesor y los que pasaron a la
    cola de supervisión (dos rotaciones sin respuesta, o sin otro asesor
    disponible). 2026-10-04: el script solo informaba los rotados y decía
    "ningún lead cruzó el umbral" aunque hubiera escalado/liberado otros."""
    ciclo = await ejecutar_ciclo_de_espera(intervalo_minutos, umbral_rotacion_minutos)
    rotados: list[str] = []
    escalados: list[str] = list(ciclo["escalados"])
    for c in ciclo["a_rotar"]:
        asesor_nuevo = await elegir_asesor_automatico(c["interes"] or "", c["negocio_id"], excluir=c["asesor_actual"])
        if asesor_nuevo is None:
            logger.info(f"Lead {c['telefono']} sin otro asesor disponible para rotar — pasa a la cola de supervisión")
            if await enviar_a_cola_de_supervision(c["telefono"], motivo="timeout_inactividad"):
                escalados.append(c["telefono"])
            continue
        await rotar_asignacion_por_inactividad(c["telefono"], c["asesor_actual"], asesor_nuevo, c["minutos_espera"])
        logger.info(f"Lead {c['telefono']} rotado de {c['asesor_actual']} a {asesor_nuevo} tras {c['minutos_espera']} min de turno sin respuesta")
        rotados.append(c["telefono"])

    return {"rotados": rotados, "escalados": escalados}


# ── Cola de pendientes al abrir el negocio (2026-10-07, Fase 1) ──────────────────────────────────
#
# Un lead derivado con el negocio cerrado queda SIN asesor y con Gabi activa (ver
# `elegir_asesor_automatico`). Este paso del Cron de cada 5 minutos lo reparte apenas el negocio
# abre y haya asesores `disponible`: el reloj de rotación solo corre en horario, así que asignar
# antes solo escondería el caso.

VENTANA_META_24H = timedelta(hours=24)

# Tope de asignaciones por corrida (una corrida = 5 min), configurable por negocio con la clave
# `cola_apertura_max_por_corrida`. 10 cubre de una vez el atraso típico de un fin de semana (la semana
# medida tenía 8 leads derivados fuera de horario) y, si el atraso fuera mayor, el resto sale en las
# corridas siguientes sin que un solo asesor reciba decenas de casos de golpe: cada asignación aumenta
# su carga activa, así que el reparto por carga también reparte el lote entre los asesores disponibles.
COLA_APERTURA_MAX_POR_CORRIDA_DEFAULT = 10


async def _limite_por_corrida(negocio_id: str) -> int:
    valor = await obtener_configuracion(
        "cola_apertura_max_por_corrida", str(COLA_APERTURA_MAX_POR_CORRIDA_DEFAULT), negocio_id=negocio_id,
    )
    try:
        return max(1, int(valor))
    except (TypeError, ValueError):
        return COLA_APERTURA_MAX_POR_CORRIDA_DEFAULT


def _clave_de_urgencia(ultimo_cliente: datetime | None, ahora: datetime) -> tuple:
    """Orden de la cola: primero los que MÁS PRONTO cierran su ventana de 24 h de WhatsApp (último
    mensaje del cliente + 24 h, de menor a mayor); luego los de ventana ya cerrada, del cliente que
    escribió más recientemente al más antiguo (los más fáciles de retomar con una plantilla); al final
    los que no tienen ningún mensaje del cliente registrado."""
    if ultimo_cliente is None:
        return (2, 0.0)
    cierre = ultimo_cliente + VENTANA_META_24H
    if cierre > ahora:
        return (0, cierre.timestamp())
    return (1, -ultimo_cliente.timestamp())


async def listar_cola_pendiente_por_urgencia(negocio_id: str, ahora: datetime | None = None) -> list[dict]:
    """Leads derivados sin asesor que se pueden repartir, ordenados por urgencia de ventana. Parte de
    `listar_leads_esperando_asesor` (sin resultado cerrado, con conversación activa, no cerrados
    definitivamente, no atendidos ya por una persona) y descarta además los escalados a supervisión y
    los que Gabi tiene pausados a mano: esos los trata una persona, no el reparto automático."""
    ahora = ahora or datetime.utcnow()
    pendientes = [
        l for l in await listar_leads_esperando_asesor(negocio_id)
        if not l.get("escalado_supervision_en") and not l.get("pausado_manual")
    ]
    con_clave = []
    for lead in pendientes:
        ultimo = await obtener_timestamp_ultimo_mensaje_usuario(lead["telefono"])
        con_clave.append((_clave_de_urgencia(ultimo, ahora), lead))
    con_clave.sort(key=lambda par: par[0])
    return [lead for _clave, lead in con_clave]


async def asignar_cola_pendiente_al_abrir(max_por_corrida: int | None = None) -> dict:
    """Paso del Cron `liberar_leads_inactivos`: por cada negocio ABIERTO ahora, asigna los leads
    derivados que quedaron sin asesor (ver `listar_cola_pendiente_por_urgencia`) con la misma lógica
    de `elegir_asesor_automatico` (solo asesores `disponible`, nivel y carga). Idempotente: un lead
    asignado sale de la cola, y justo antes de asignar cada uno se vuelve a leer por si otra corrida
    o una persona ya lo tomó. Si no hay ningún asesor disponible, no asigna nada (nadie pierde el lugar).

    `max_por_corrida` fuerza el tope (tests); si no, se lee `cola_apertura_max_por_corrida` del negocio.
    Devuelve {"asignados": [(telefono, asesor), ...], "pendientes": n} — `pendientes` son los que
    siguen esperando tras esta corrida (por tope o por falta de asesores) en los negocios abiertos."""
    asignados: list[tuple[str, str]] = []
    pendientes_restantes = 0
    for negocio in await listar_negocios(solo_activos=True):
        negocio_id = negocio["id"]
        if not await negocio_abierto_ahora(negocio_id):
            continue
        cola = await listar_cola_pendiente_por_urgencia(negocio_id)
        if not cola:
            continue
        limite = max_por_corrida if max_por_corrida is not None else await _limite_por_corrida(negocio_id)
        hechos = 0
        for lead in cola:
            if hechos >= limite:
                break
            fresco = await obtener_lead(lead["telefono"], negocio_id=negocio_id)
            if (
                fresco is None or fresco.get("asesor_asignado") or fresco.get("pausado_manual")
                or fresco.get("escalado_supervision_en") or fresco.get("paso_flujo") != "derivado_asesor"
            ):
                continue
            asesor = await elegir_asesor_automatico(fresco.get("interes") or "", negocio_id)
            if asesor is None:
                break  # sin asesores disponibles (o el negocio cerró entre medio): para los demás también
            await asignar_asesor_a_lead(lead["telefono"], asesor, automatico=True)
            logger.info(f"Cola al abrir: lead {lead['telefono']} asignado a {asesor}")
            asignados.append((lead["telefono"], asesor))
            hechos += 1
        pendientes_restantes += max(0, len(cola) - hechos)
    return {"asignados": asignados, "pendientes": pendientes_restantes}
