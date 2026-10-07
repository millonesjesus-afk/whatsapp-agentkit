# agent/atencion_atrasada.py — Atención atrasada en Inicio + candidatos de la plantilla de zona muerta (2026-10-07, Q2)
#
# Un lead derivado a una persona que no contesta sigue siendo, en Inicio, "un cliente esperando más". Acá se le
# pone una señal de gravedad por ANTIGÜEDAD, calculada al vuelo (sin migración) sobre lo que ya devuelve
# `memory.listar_clientes_esperando`.
#
# Edad = tiempo desde `esperando_desde`: el PRIMER mensaje real del cliente que sigue sin respuesta saliente (de
# Gabi o de una persona) — ver `memory._inicio_de_espera_por_conversacion`.
#
# Niveles (de menor a mayor gravedad; cada ítem tiene a lo sumo uno). Umbrales por defecto, configurables por
# negocio con las claves de `configuracion` indicadas:
#   · "atrasada"       — el negocio estuvo ABIERTO al menos `atencion_atrasada_horas` (2 h) desde esperando_desde.
#                        Se mide en horas de horario de atención, no de reloj: un mensaje de las 20:00 no está
#                        "atrasado" a las 8:00 de la mañana siguiente, nadie pudo atenderlo. El horario sale de
#                        `HorarioAtencion` (el mismo de `tools._rangos_de_atencion_por_dia`: lunes a sábado
#                        8:00-19:00 si el negocio no configuró nada).
#   · "urgente"        — edad de RELOJ >= `atencion_urgente_horas` (8 h) Y ya está "atrasada" por horas de
#                        horario (o su ventana de 24 h ya cerró: sin texto libre posible, solo plantilla).
#   · "ultima_llamada" — la ventana de 24 h de WhatsApp sigue abierta y le quedan menos de
#                        `atencion_ultima_llamada_horas` (6 h). Gana sobre los otros dos.
# Es independiente de `dashboard._VENTANA_POR_VENCER` (4 h), que se conserva para lo que ya lo usa.

import logging
from datetime import datetime, time, timedelta

from sqlalchemy import select

from agent.memory import (
    RESULTADOS_CERRADOS, EventoLead, async_session, listar_clientes_esperando, obtener_configuracion,
)
from agent.tools import _rangos_de_atencion_por_dia

logger = logging.getLogger("agentkit")

CLAVE_ATRASADA_HORAS = "atencion_atrasada_horas"
CLAVE_URGENTE_HORAS = "atencion_urgente_horas"
CLAVE_ULTIMA_LLAMADA_HORAS = "atencion_ultima_llamada_horas"
UMBRALES_POR_DEFECTO = {"atrasada": 2.0, "urgente": 8.0, "ultima_llamada": 6.0}
_CLAVES = {
    "atrasada": CLAVE_ATRASADA_HORAS, "urgente": CLAVE_URGENTE_HORAS, "ultima_llamada": CLAVE_ULTIMA_LLAMADA_HORAS,
}

NIVELES = ("atrasada", "urgente", "ultima_llamada")
GRAVEDAD = {None: 0, "atrasada": 1, "urgente": 2, "ultima_llamada": 3}

# Perú no tiene horario de verano: Lima es UTC-5 todo el año (mismo criterio que dashboard._OFFSET_LIMA).
_OFFSET_LIMA = timedelta(hours=5)

# Plantilla automática de la zona muerta (script `scripts/plantilla_zona_muerta.py`).
CLAVE_AUTO_ZONA_MUERTA = "plantilla_auto_zona_muerta"      # "1" = encendida; ausente/otro = apagada
CLAVE_AUTO_HORAS_ANTES = "plantilla_auto_horas_antes"      # ventana abierta con menos de estas horas
CLAVE_AUTO_HORAS_DESPUES = "plantilla_auto_horas_despues"  # ventana cerrada hace menos de estas horas
AUTO_HORAS_ANTES_POR_DEFECTO = 6.0
AUTO_HORAS_DESPUES_POR_DEFECTO = 12.0
TIPO_EVENTO_PLANTILLA_AUTO = "plantilla_auto_enviada"      # <= 30 caracteres


def _numero_positivo(valor, por_defecto: float) -> float:
    try:
        n = float(str(valor).replace(",", "."))
    except (TypeError, ValueError):
        return por_defecto
    return n if n > 0 else por_defecto


async def obtener_umbrales(negocio_id: str | None) -> dict[str, float]:
    """Horas de cada nivel para este negocio (los defaults si la clave falta o no es un número > 0)."""
    umbrales = {}
    for nivel, clave in _CLAVES.items():
        valor = await obtener_configuracion(clave, str(UMBRALES_POR_DEFECTO[nivel]), negocio_id=negocio_id)
        umbrales[nivel] = _numero_positivo(valor, UMBRALES_POR_DEFECTO[nivel])
    return umbrales


# ── Horario de atención (funciones puras sobre `rangos`: {dia 0=lunes: (apertura, cierre) | None}) ────────────

def _tramo_del_dia(rangos: dict, fecha) -> tuple[datetime, datetime] | None:
    rango = rangos.get(fecha.weekday())
    if not rango:
        return None
    return (
        datetime.combine(fecha, time.fromisoformat(rango[0])),
        datetime.combine(fecha, time.fromisoformat(rango[1])),
    )


def horas_de_atencion_abierta(rangos: dict, desde: datetime, hasta: datetime) -> float:
    """Horas, entre dos instantes UTC naive, en que el negocio estuvo abierto (hora de Lima)."""
    if hasta <= desde:
        return 0.0
    desde_lima, hasta_lima = desde - _OFFSET_LIMA, hasta - _OFFSET_LIMA
    total, dia = 0.0, desde_lima.date()
    while dia <= hasta_lima.date():
        tramo = _tramo_del_dia(rangos, dia)
        if tramo:
            inicio, fin = max(tramo[0], desde_lima), min(tramo[1], hasta_lima)
            if fin > inicio:
                total += (fin - inicio).total_seconds() / 3600
        dia += timedelta(days=1)
    return total


def esta_abierto(rangos: dict, ahora: datetime) -> bool:
    """True si `ahora` (UTC naive) cae dentro del horario de atención."""
    ahora_lima = ahora - _OFFSET_LIMA
    tramo = _tramo_del_dia(rangos, ahora_lima.date())
    return bool(tramo and tramo[0] <= ahora_lima < tramo[1])


def proxima_apertura(rangos: dict, ahora: datetime) -> datetime | None:
    """Próxima vez que el negocio abre, FUTURA, como UTC naive. None si nunca atiende."""
    ahora_lima = ahora - _OFFSET_LIMA
    for adelante in range(8):
        tramo = _tramo_del_dia(rangos, ahora_lima.date() + timedelta(days=adelante))
        if tramo and tramo[0] > ahora_lima:
            return tramo[0] + _OFFSET_LIMA
    return None


# ── Nivel de atención ───────────────────────────────────────────────────────────────────────────────────

def calcular_atencion(
    esperando_desde: datetime, ventana_vence_en: datetime, ventana_abierta: bool, ahora: datetime,
    rangos: dict, umbrales: dict[str, float] | None = None,
) -> dict:
    """`{"nivel": None | "atrasada" | "urgente" | "ultima_llamada", "edad_horas", "ventana_restante_horas"}`.
    `edad_horas` es de reloj (desde el primer mensaje sin respuesta); `ventana_restante_horas` es None si la
    ventana ya cerró. Las fechas son UTC naive."""
    umbrales = {**UMBRALES_POR_DEFECTO, **(umbrales or {})}
    edad = max(0.0, (ahora - esperando_desde).total_seconds() / 3600)
    restante = (ventana_vence_en - ahora).total_seconds() / 3600 if ventana_abierta else None
    if restante is not None and restante <= 0:
        restante = None
    atrasada = horas_de_atencion_abierta(rangos, esperando_desde, ahora) >= umbrales["atrasada"]
    if restante is not None and restante < umbrales["ultima_llamada"]:
        nivel = "ultima_llamada"
    elif edad >= umbrales["urgente"] and (atrasada or restante is None):
        nivel = "urgente"
    elif atrasada:
        nivel = "atrasada"
    else:
        nivel = None
    return {
        "nivel": nivel, "edad_horas": round(edad, 1),
        "ventana_restante_horas": round(restante, 1) if restante is not None else None,
    }


async def anotar_atencion(negocio_id: str, items: list[dict], ahora: datetime | None = None) -> list[dict]:
    """Agrega `atencion` a cada ítem de `listar_clientes_esperando` (los modifica y los devuelve). Nunca
    lanza: ante una falla los ítems quedan con `atencion` sin nivel (Inicio sigue funcionando sin la señal)."""
    ahora = ahora or datetime.utcnow()
    try:
        rangos = await _rangos_de_atencion_por_dia(negocio_id)
        umbrales = await obtener_umbrales(negocio_id)
    except Exception:
        logger.exception("Atención atrasada: no se pudo leer el horario ni los umbrales — sin señal")
        rangos, umbrales = {}, dict(UMBRALES_POR_DEFECTO)
    for it in items:
        try:
            it["atencion"] = calcular_atencion(
                it.get("esperando_desde") or it["ultimo_mensaje_cliente_en"], it["ventana_vence_en"],
                it["ventana_abierta"], ahora, rangos, umbrales,
            )
        except Exception:
            logger.exception("Atención atrasada: falló el cálculo para un ítem")
            it["atencion"] = {"nivel": None, "edad_horas": 0.0, "ventana_restante_horas": None}
    return items


def gravedad(item: dict) -> int:
    return GRAVEDAD.get((item.get("atencion") or {}).get("nivel"), 0)


def totales_de_atencion(items: list[dict], para_campana: list[dict] | None = None) -> dict:
    """Totales ADITIVOS de `zona_accion.totales`. Los tres por nivel son excluyentes (cada ítem tiene uno)
    y `atencion_total` los suma. `atencion_campana`/`atencion_campana_urgentes` acotan al mismo conjunto que
    el badge de la campana (`esperando_campana`); "urgentes" = urgente + última llamada."""
    def _contar(lista: list[dict], *niveles: str) -> int:
        return sum(1 for it in lista if (it.get("atencion") or {}).get("nivel") in niveles)

    campana = items if para_campana is None else para_campana
    return {
        "atencion_atrasada": _contar(items, "atrasada"),
        "atencion_urgente": _contar(items, "urgente"),
        "atencion_ultima_llamada": _contar(items, "ultima_llamada"),
        "atencion_total": _contar(items, *NIVELES),
        "atencion_campana": _contar(campana, *NIVELES),
        "atencion_campana_urgentes": _contar(campana, "urgente", "ultima_llamada"),
    }


# ── Zona muerta ─────────────────────────────────────────────────────────────────────────────────────────

async def candidatos_zona_muerta(
    negocio_id: str, ahora: datetime | None = None, horas_antes: float = AUTO_HORAS_ANTES_POR_DEFECTO,
    horas_despues: float = AUTO_HORAS_DESPUES_POR_DEFECTO,
) -> list[dict]:
    """Clientes esperando (derivados a una persona, sin respuesta saliente desde su último mensaje) cuya
    ventana de 24 h se cierra antes de que alguien pueda atenderlos:
      · el negocio está CERRADO ahora (si está abierto aún hay quien conteste) y su próxima apertura es
        posterior al cierre de la ventana;
      · la ventana vence en menos de `horas_antes`, o cerró hace menos de `horas_despues` (pasado ese
        plazo ya no es una emergencia: lo retoma una persona con la plantilla manual);
      · el resultado no está cerrado (vendido, sin interés, etc.). `listar_clientes_esperando` ya descarta
        los cerrados definitivamente.
    No mira la idempotencia ni la configuración: eso es del script."""
    ahora = ahora or datetime.utcnow()
    rangos = await _rangos_de_atencion_por_dia(negocio_id)
    if esta_abierto(rangos, ahora):
        return []
    apertura = proxima_apertura(rangos, ahora)
    if apertura is None:
        return []
    candidatos = []
    for c in await listar_clientes_esperando(negocio_id, ahora=ahora):
        if c.get("resultado") in RESULTADOS_CERRADOS:
            continue
        vence = c["ventana_vence_en"]
        if c["ventana_abierta"]:
            if vence - ahora >= timedelta(hours=horas_antes):
                continue
        elif ahora - vence >= timedelta(hours=horas_despues):
            continue
        if apertura <= vence:   # alguien abre antes de que la ventana cierre
            continue
        candidatos.append(c)
    return candidatos


async def ya_se_envio_plantilla_automatica(conversation_id: str, desde: datetime) -> bool:
    """True si ya hay un evento `plantilla_auto_enviada` en esta conversación desde `desde` (el inicio de la
    espera actual): una sola plantilla automática por espera. Si el cliente contesta y más adelante vuelve a
    quedar sin respuesta, es otra espera y puede recibir otra."""
    async with async_session() as session:
        fila = (await session.execute(
            select(EventoLead.id).where(
                EventoLead.conversation_id == conversation_id, EventoLead.tipo == TIPO_EVENTO_PLANTILLA_AUTO,
                EventoLead.creado >= desde,
            ).limit(1)
        )).first()
    return fila is not None
