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
#                        "atrasado" a las 8:00 de la mañana siguiente, nadie pudo atenderlo. Desde el calendario de
#                        negocio (2026-10-12) el tiempo hábil también excluye feriados y días especiales cerrados
#                        (`calendario_negocio.minutos_habiles`); sin excepciones cargadas da lo mismo que antes
#                        (lunes a sábado 8:00-19:00 si el negocio no configuró nada).
#   · "urgente"        — ventana de 24 h ABIERTA, edad de RELOJ >= `atencion_urgente_horas` (8 h) Y ya está
#                        "atrasada" por horas de horario.
#   · "ultima_llamada" — la ventana de 24 h de WhatsApp sigue abierta y le quedan menos de
#                        `atencion_ultima_llamada_horas` (6 h). Gana sobre los otros dos. Es un reloj REAL de Meta:
#                        el calendario de negocio nunca lo pausa.
#   · "ventana_cerrada" — (R4, 2026-10-07) la ventana de 24 h ya cerró: no hay texto libre posible (solo
#                        llamar o enviar plantilla). NUNCA es "atrasada" ni "urgente": lo urgente es lo que aún
#                        se puede atender por el chat; lo demás es un caso olvidado, no una emergencia.
#
# MODO HÁBIL (2026-10-12): si el negocio fijó `calendario_habil_desde` (AAAA-MM-DD, día de Lima) y hoy ya es esa fecha
# o posterior, los dos niveles de demora se miden SOLO en horas hábiles: atrasada = `atencion_atrasada_horas_habiles`
# (2 h) y urgente = `atencion_urgente_horas_habiles` (4 h; antes 8 h de reloj, que provocaba el efecto avalancha cada
# mañana tras un cierre). Sin esa clave se usan los valores de siempre.
# Es independiente de `dashboard._VENTANA_POR_VENCER` (4 h), que se conserva para lo que ya lo usa.

import logging
from datetime import datetime, timedelta

from sqlalchemy import select

from agent import calendario_negocio as cal_negocio
from agent.memory import (
    RESULTADOS_CERRADOS, EventoLead, async_session, listar_clientes_esperando, obtener_calendario_habil_desde,
    obtener_configuracion,
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
# Modo hábil (calendario de negocio, 2026-10-12): umbrales medidos en HORAS HÁBILES.
CLAVE_ATRASADA_HORAS_HABILES = "atencion_atrasada_horas_habiles"
CLAVE_URGENTE_HORAS_HABILES = "atencion_urgente_horas_habiles"
UMBRALES_HABILES_POR_DEFECTO = {"atrasada": 2.0, "urgente": 4.0, "ultima_llamada": 6.0}
_CLAVES_HABILES = {
    "atrasada": CLAVE_ATRASADA_HORAS_HABILES, "urgente": CLAVE_URGENTE_HORAS_HABILES, "ultima_llamada": CLAVE_ULTIMA_LLAMADA_HORAS,
}

NIVELES = ("atrasada", "urgente", "ultima_llamada")          # solo con la ventana ABIERTA
NIVEL_VENTANA_CERRADA = "ventana_cerrada"
GRAVEDAD = {None: 0, NIVEL_VENTANA_CERRADA: 0, "atrasada": 1, "urgente": 2, "ultima_llamada": 3}

# Perú no tiene horario de verano: Lima es UTC-5 todo el año (mismo criterio que dashboard._OFFSET_LIMA).
_OFFSET_LIMA = cal_negocio.OFFSET_LIMA

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


async def obtener_umbrales(negocio_id: str | None, modo_habil: bool = False) -> dict[str, float]:
    """Horas de cada nivel para este negocio (los defaults si la clave falta o no es un número > 0). Con
    `modo_habil` se leen los umbrales en HORAS HÁBILES (`atencion_atrasada_horas_habiles` 2 h y
    `atencion_urgente_horas_habiles` 4 h); la última llamada es la misma en ambos modos."""
    claves, defaults = (_CLAVES_HABILES, UMBRALES_HABILES_POR_DEFECTO) if modo_habil else (_CLAVES, UMBRALES_POR_DEFECTO)
    umbrales = {}
    for nivel, clave in claves.items():
        valor = await obtener_configuracion(clave, str(defaults[nivel]), negocio_id=negocio_id)
        umbrales[nivel] = _numero_positivo(valor, defaults[nivel])
    return umbrales


async def modo_habil_vigente(negocio_id: str | None, ahora: datetime) -> bool:
    """True si el negocio fijó `calendario_habil_desde` y ya llegó esa fecha (día de Lima). Sin la clave, o con una
    fecha futura, rigen los umbrales de siempre."""
    desde = await obtener_calendario_habil_desde(negocio_id)
    return desde is not None and cal_negocio.fecha_lima(ahora) >= desde


# ── Horario de atención (funciones sobre `rangos`: {dia 0=lunes: (apertura, cierre) | None}) ─────────────────
# Delgadas a propósito: el cálculo vive en `agent/calendario_negocio.py`. Si `rangos` viene de
# `tools._rangos_de_atencion_por_dia` trae el calendario completo (feriados incluidos); si es un dict suelto (pruebas,
# llamadores viejos) se toma como horario semanal sin excepciones.

def _calendario(rangos) -> cal_negocio.Calendario:
    if isinstance(rangos, cal_negocio.Calendario):
        return rangos
    adjunto = getattr(rangos, "calendario", None)
    return adjunto if adjunto is not None else cal_negocio.calendario_desde_rangos(rangos)


def minutos_de_atencion_abierta(rangos, desde: datetime, hasta: datetime) -> float:
    """Minutos, entre dos instantes UTC naive, en que el negocio estuvo abierto (hora de Lima, con feriados)."""
    return cal_negocio.minutos_habiles(desde, hasta, _calendario(rangos))


def horas_de_atencion_abierta(rangos, desde: datetime, hasta: datetime) -> float:
    """Horas, entre dos instantes UTC naive, en que el negocio estuvo abierto (hora de Lima)."""
    return minutos_de_atencion_abierta(rangos, desde, hasta) / 60


def esta_abierto(rangos, ahora: datetime) -> bool:
    """True si `ahora` (UTC naive) cae dentro del horario de atención."""
    return cal_negocio.esta_abierto(ahora, _calendario(rangos))


def proxima_apertura(rangos, ahora: datetime) -> datetime | None:
    """Próxima vez que el negocio abre, FUTURA, como UTC naive. None si no abre en las próximas 3 semanas."""
    return cal_negocio.proxima_apertura(ahora, _calendario(rangos))


def _tramo_del_dia(rangos, fecha) -> tuple[datetime, datetime] | None:
    """(apertura, cierre) del día de Lima `fecha` como datetime naive de Lima, o None si ese día está cerrado
    (feriados y días especiales incluidos). Con varios rangos en el día: del primer inicio al último cierre. Lo usa
    `llamadas.py` para partir el día en franjas."""
    tramos = cal_negocio.tramos_del_dia(fecha, _calendario(rangos))
    if not tramos:
        return None
    return datetime.combine(fecha, tramos[0][0]), datetime.combine(fecha, tramos[-1][1])


# ── Nivel de atención ───────────────────────────────────────────────────────────────────────────────────

def calcular_atencion(
    esperando_desde: datetime, ventana_vence_en: datetime, ventana_abierta: bool, ahora: datetime,
    rangos: dict, umbrales: dict[str, float] | None = None, modo_habil: bool = False, en_pausa: bool = False,
) -> dict:
    """`{"nivel": None | "atrasada" | "urgente" | "ultima_llamada" | "ventana_cerrada", "edad_horas",
    "ventana_restante_horas"}`. `edad_horas` es de reloj (desde el primer mensaje sin respuesta);
    `ventana_restante_horas` es None si la ventana ya cerró. Las fechas son UTC naive.
    R4 (2026-10-07): con la ventana de 24 h cerrada el nivel es SIEMPRE `ventana_cerrada` (nunca
    atrasada/urgente/ultima_llamada); esos tres solo existen con la ventana abierta.

    Calendario de negocio (2026-10-12): el tiempo hábil sale de `calendario_negocio.minutos_habiles` (excluye noches,
    domingos, feriados y días especiales cerrados). `modo_habil=False` (sin `calendario_habil_desde`) conserva las reglas
    de siempre: atrasada = `umbrales["atrasada"]` horas hábiles y urgente = reloj >= `umbrales["urgente"]` Y atrasada.
    `modo_habil=True`: atrasada y urgente son horas HÁBILES (`umbrales` por defecto 2 h y 4 h). La última llamada es
    siempre de reloj (la ventana de Meta no se pausa). `en_pausa=True` agrega `"en_pausa": True` al resultado (hoy el
    negocio está cerrado por un feriado o día especial); sin pausa la clave no existe."""
    umbrales = {**(UMBRALES_HABILES_POR_DEFECTO if modo_habil else UMBRALES_POR_DEFECTO), **(umbrales or {})}
    edad = max(0.0, (ahora - esperando_desde).total_seconds() / 3600)
    restante = (ventana_vence_en - ahora).total_seconds() / 3600 if ventana_abierta else None
    if restante is not None and restante <= 0:
        restante = None
    if restante is None:
        resultado = {"nivel": NIVEL_VENTANA_CERRADA, "edad_horas": round(edad, 1), "ventana_restante_horas": None}
    else:
        habiles = minutos_de_atencion_abierta(rangos, esperando_desde, ahora) / 60
        atrasada = habiles >= umbrales["atrasada"]
        if restante < umbrales["ultima_llamada"]:
            nivel = "ultima_llamada"
        elif modo_habil and habiles >= umbrales["urgente"]:
            nivel = "urgente"
        elif not modo_habil and edad >= umbrales["urgente"] and atrasada:
            nivel = "urgente"
        elif atrasada:
            nivel = "atrasada"
        else:
            nivel = None
        resultado = {
            "nivel": nivel, "edad_horas": round(edad, 1),
            "ventana_restante_horas": round(restante, 1) if restante is not None else None,
        }
    if en_pausa:
        resultado["en_pausa"] = True
    return resultado


async def pausa_de_atencion(negocio_id: str | None, ahora: datetime | None = None) -> dict | None:
    """Hay pausa cuando HOY el negocio está cerrado todo el día por una excepción del calendario (feriado, día no
    laborable, puente, cierre propio). Devuelve `{"motivo", "nombre", "reanuda_en": ISO UTC con Z | None,
    "reanuda_texto": "el viernes 9 a las 8:00 a. m."}` o None. Nunca lanza: ante una falla, sin pausa."""
    from agent.memory import iso_utc
    ahora = ahora or datetime.utcnow()
    try:
        rangos = await _rangos_de_atencion_por_dia(negocio_id)
        pausa = cal_negocio.pausa_vigente(ahora, _calendario(rangos))
    except Exception:
        logger.exception("Atención atrasada: no se pudo calcular la pausa del calendario — sin pausa")
        return None
    if pausa is None:
        return None
    return {
        "motivo": pausa["motivo"], "nombre": pausa["nombre"],
        "reanuda_en": iso_utc(pausa["reanuda_en"]) if pausa["reanuda_en"] else None,
        "reanuda_texto": cal_negocio.describir_proxima_apertura(pausa["reanuda_en"], ahora),
    }


async def anotar_atencion(negocio_id: str, items: list[dict], ahora: datetime | None = None) -> list[dict]:
    """Agrega `atencion` a cada ítem de `listar_clientes_esperando` (los modifica y los devuelve). Nunca
    lanza: ante una falla los ítems quedan con `atencion` sin nivel (Inicio sigue funcionando sin la señal)."""
    ahora = ahora or datetime.utcnow()
    modo_habil, en_pausa = False, False
    try:
        rangos = await _rangos_de_atencion_por_dia(negocio_id)
        modo_habil = await modo_habil_vigente(negocio_id, ahora)
        umbrales = await obtener_umbrales(negocio_id, modo_habil)
        en_pausa = cal_negocio.pausa_vigente(ahora, _calendario(rangos)) is not None
    except Exception:
        logger.exception("Atención atrasada: no se pudo leer el horario ni los umbrales — sin señal")
        rangos, umbrales, modo_habil = {}, dict(UMBRALES_POR_DEFECTO), False
    for it in items:
        try:
            it["atencion"] = calcular_atencion(
                it.get("esperando_desde") or it["ultimo_mensaje_cliente_en"], it["ventana_vence_en"],
                it["ventana_abierta"], ahora, rangos, umbrales, modo_habil=modo_habil, en_pausa=en_pausa,
            )
        except Exception:
            logger.exception("Atención atrasada: falló el cálculo para un ítem")
            it["atencion"] = {
                "nivel": None if it.get("ventana_abierta") else NIVEL_VENTANA_CERRADA,
                "edad_horas": 0.0, "ventana_restante_horas": None,
            }
    return items


def gravedad(item: dict) -> int:
    return GRAVEDAD.get((item.get("atencion") or {}).get("nivel"), 0)


def totales_de_atencion(items: list[dict], para_campana: list[dict] | None = None, pausa: dict | None = None) -> dict:
    """Totales ADITIVOS de `zona_accion.totales`. Los tres por nivel son excluyentes (cada ítem tiene uno)
    y `atencion_total` los suma (todos con la ventana ABIERTA). `atencion_ventana_cerrada` (R4, 2026-10-07)
    cuenta aparte los casos con la ventana de 24 h cerrada. `atencion_campana`/`atencion_campana_urgentes`
    acotan al mismo conjunto que el badge de la campana (`esperando_campana`) y cuentan SOLO ventana abierta;
    "urgentes" = urgente + última llamada.

    Calendario de negocio (2026-10-12): con `pausa` vigente (hoy es feriado o día especial cerrado) la campana NO suma
    «casos sin atender»: `atencion_campana` y `atencion_campana_urgentes` cuentan solo las «últimas llamadas» (la
    ventana de 24 h de Meta es un reloj real y no se pausa) y `atencion_en_pausa` dice cuántos clientes de la campana
    esperan hasta que el negocio reabra (0 sin pausa)."""
    def _contar(lista: list[dict], *niveles: str) -> int:
        return sum(1 for it in lista if (it.get("atencion") or {}).get("nivel") in niveles)

    campana = items if para_campana is None else para_campana
    if pausa is not None:
        atencion_campana = atencion_campana_urgentes = _contar(campana, "ultima_llamada")
    else:
        atencion_campana, atencion_campana_urgentes = _contar(campana, *NIVELES), _contar(campana, "urgente", "ultima_llamada")
    return {
        "atencion_atrasada": _contar(items, "atrasada"),
        "atencion_urgente": _contar(items, "urgente"),
        "atencion_ultima_llamada": _contar(items, "ultima_llamada"),
        "atencion_total": _contar(items, *NIVELES),
        "atencion_ventana_cerrada": _contar(items, NIVEL_VENTANA_CERRADA),
        "atencion_campana": atencion_campana,
        "atencion_campana_urgentes": atencion_campana_urgentes,
        "atencion_en_pausa": len(campana) if pausa is not None else 0,
    }


# ── Zona muerta ─────────────────────────────────────────────────────────────────────────────────────────

# Víspera de un cierre por calendario: las horas previas al último cierre antes de un día cerrado por una excepción
# (feriado, no laborable, puente, cierre propio) en que ya se marcan candidatos, sin esperar a estar cerrados.
VISPERA_HORAS_ANTES_DEL_CIERRE = 2.0


def _en_vispera_de_cierre(ahora: datetime, cal: cal_negocio.Calendario) -> bool:
    """True si el negocio está ABIERTO ahora, el cierre de hoy está a menos de `VISPERA_HORAS_ANTES_DEL_CIERRE` y el día
    siguiente queda cerrado todo el día por una EXCEPCIÓN del calendario (no por ser domingo)."""
    ahora_lima = cal_negocio.a_lima(ahora)
    hoy = ahora_lima.date()
    manana = hoy + timedelta(days=1)
    ex = cal.excepciones.get(manana)
    if ex is None or ex.atiende or not cal_negocio.cerrado_todo_el_dia(manana, cal):
        return False
    tramos = cal_negocio.tramos_del_dia(hoy, cal)
    if not tramos:
        return False
    cierre = datetime.combine(hoy, tramos[-1][1])
    return timedelta(0) < cierre - ahora_lima <= timedelta(hours=VISPERA_HORAS_ANTES_DEL_CIERRE)


async def candidatos_zona_muerta(
    negocio_id: str, ahora: datetime | None = None, horas_antes: float = AUTO_HORAS_ANTES_POR_DEFECTO,
    horas_despues: float = AUTO_HORAS_DESPUES_POR_DEFECTO,
) -> list[dict]:
    """Clientes esperando (derivados a una persona, sin respuesta saliente desde su último mensaje) cuya
    ventana de 24 h se cierra antes de que alguien pueda atenderlos:
      · el negocio está CERRADO ahora (si está abierto aún hay quien conteste) y su próxima apertura es
        posterior al cierre de la ventana. «Cerrado» incluye feriados y días especiales y la próxima apertura
        sale del calendario (un cierre largo de más de una semana también se resuelve);
      · EXCEPCIÓN — la víspera de un cierre por calendario: con el negocio todavía abierto pero a menos de 2 h
        de su último cierre antes de un feriado/día especial, también se marcan (cada candidato trae
        `momento: "vispera"`; los demás `momento: "cerrado"`), para poder avisarles antes de que cierre la ventana;
      · la ventana vence en menos de `horas_antes`, o cerró hace menos de `horas_despues` (pasado ese
        plazo ya no es una emergencia: lo retoma una persona con la plantilla manual);
      · el resultado no está cerrado (vendido, sin interés, etc.). `listar_clientes_esperando` ya descarta
        los cerrados definitivamente.
    No mira la idempotencia ni la configuración: eso es del script. Lee el calendario fresco (es un Cron)."""
    ahora = ahora or datetime.utcnow()
    rangos = await _rangos_de_atencion_por_dia(negocio_id, fresco=True)
    cal = _calendario(rangos)
    vispera = False
    if cal_negocio.esta_abierto(ahora, cal):
        vispera = _en_vispera_de_cierre(ahora, cal)
        if not vispera:
            return []
    apertura = cal_negocio.proxima_apertura(ahora, cal)
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
        c["momento"] = "vispera" if vispera else "cerrado"
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
