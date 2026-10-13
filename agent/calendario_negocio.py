# agent/calendario_negocio.py — Calendario de negocio: horario semanal + días especiales (2026-10-12, Fase 1)
#
# MÓDULO PURO: no importa memory ni tools ni toca la base. Recibe un `Calendario` ya armado y responde con
# fechas. Es la ÚNICA implementación de "¿el negocio atiende ahora?", "¿cuánto tiempo hábil pasó entre dos
# instantes?" y "¿cuándo vuelve a abrir?". Antes había cuatro copias (tools, atencion_atrasada, memory,
# asignacion) y ninguna conocía los feriados.
#
# Reglas:
#   · Zona fija de Lima = UTC-5 todo el año (Perú no tiene horario de verano). Los instantes que entran y salen
#     de las funciones públicas son UTC "naive" (la convención del repo); un día es SIEMPRE un día de Lima, así
#     que un mensaje de las 21:00 de Lima (02:00 UTC del día siguiente) pertenece al día de Lima.
#   · `semana`: {0=lunes … 6=domingo: [(apertura "HH:MM", cierre "HH:MM"), …]}. Lista vacía = día cerrado. Varios
#     rangos por día están soportados (pausa de almuerzo, etc.).
#   · `excepciones`: {fecha de Lima: DiaEspecial}. Una excepción MANDA sobre la semana:
#       atiende=False                      → cerrado todo el día (feriado, no laborable, puente, cierre propio)
#       atiende=True + hora_apertura/cierre → ese horario especial (reducido o extendido; también abre un domingo)
#       atiende=True sin horas              → el horario normal de ese día de la semana
#   · Un rango abre en `apertura` y cierra en `cierre` (semiabierto: a las 19:00 en punto ya está cerrado).
#   · Sin ninguna excepción el resultado es IDÉNTICO al del horario semanal de siempre.
#
# Qué NO se pausa jamás (y por eso no vive acá): la ventana de 24 h de WhatsApp y su cuenta regresiva (es un reloj de
# Meta) ni los relojes del CLIENTE (reenganche de 2 h, cierres de 15 h, 5 y 7 días).

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta

# Perú no tiene horario de verano: Lima es UTC-5 todo el año.
OFFSET_LIMA = timedelta(hours=5)

DIAS_ES = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
MESES_ES = [
    "enero", "febrero", "marzo", "abril", "mayo", "junio",
    "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
]

TIPO_FERIADO = "feriado"
TIPO_NO_LABORABLE = "no_laborable"
TIPO_PUENTE = "puente"
TIPO_ATENCION_ESPECIAL = "atencion_especial"
TIPO_CIERRE_PROPIO = "cierre_propio"
TIPOS_DIA_ESPECIAL = (TIPO_FERIADO, TIPO_NO_LABORABLE, TIPO_PUENTE, TIPO_ATENCION_ESPECIAL, TIPO_CIERRE_PROPIO)

MOTIVO_FUERA_DE_HORARIO = "fuera_de_horario"
MOTIVO_FERIADO = "feriado"
MOTIVO_NO_LABORABLE = "no_laborable"
MOTIVO_PUENTE = "puente"
MOTIVO_DIA_SIN_ATENCION = "dia_sin_atencion"
MOTIVO_CIERRE_PROPIO = "cierre_propio"
MOTIVOS = (
    MOTIVO_FUERA_DE_HORARIO, MOTIVO_FERIADO, MOTIVO_NO_LABORABLE, MOTIVO_PUENTE,
    MOTIVO_DIA_SIN_ATENCION, MOTIVO_CIERRE_PROPIO,
)
_MOTIVO_POR_TIPO = {
    TIPO_FERIADO: MOTIVO_FERIADO, TIPO_NO_LABORABLE: MOTIVO_NO_LABORABLE, TIPO_PUENTE: MOTIVO_PUENTE,
    TIPO_CIERRE_PROPIO: MOTIVO_CIERRE_PROPIO, TIPO_ATENCION_ESPECIAL: MOTIVO_DIA_SIN_ATENCION,
}

# Horario de siempre cuando un negocio no tiene fila de `HorarioAtencion` para un día: lunes a sábado 8:00-19:00.
RANGO_POR_DEFECTO = ("08:00", "19:00")
DIAS_POR_DEFECTO = range(0, 6)

HORIZONTE_DIAS_POR_DEFECTO = 21


@dataclass(frozen=True)
class DiaEspecial:
    """Una excepción de fecha. `fecha` es un día de Lima. `hora_apertura`/`hora_cierre` ("HH:MM") solo tienen
    efecto con `atiende=True` (horario especial o reducido)."""
    fecha: date
    tipo: str
    nombre: str
    atiende: bool = False
    hora_apertura: str | None = None
    hora_cierre: str | None = None


@dataclass(frozen=True)
class Calendario:
    semana: dict
    excepciones: dict = field(default_factory=dict)


# ── Construcción ────────────────────────────────────────────────────────────────────────────────────────

def _a_hora(valor) -> time:
    return valor if isinstance(valor, time) else time.fromisoformat(str(valor))


def _normalizar_tramos(tramos) -> list[tuple[time, time]]:
    """Acepta None, un solo (apertura, cierre) o una lista de ellos; devuelve la lista ordenada de `time`."""
    if not tramos:
        return []
    if isinstance(tramos, tuple) and len(tramos) == 2 and not isinstance(tramos[0], (tuple, list)):
        tramos = [tramos]
    resultado = [(_a_hora(a), _a_hora(c)) for a, c in tramos]
    return sorted(t for t in resultado if t[0] < t[1])


def crear_calendario(semana: dict | None = None, excepciones=None) -> Calendario:
    """`semana` puede traer el día como lista de rangos, un solo rango o None/[] (cerrado); los días que falten
    quedan cerrados. `excepciones`: dict {fecha: DiaEspecial} o una lista de DiaEspecial."""
    semana = semana or {}
    if isinstance(excepciones, (list, tuple)):
        excepciones = {e.fecha: e for e in excepciones}
    return Calendario(
        semana={dia: _normalizar_tramos(semana.get(dia)) for dia in range(7)},
        excepciones=dict(excepciones or {}),
    )


def calendario_por_defecto(excepciones=None) -> Calendario:
    """Lunes a sábado 8:00-19:00 (el horario de siempre) más las excepciones dadas."""
    return crear_calendario({d: [RANGO_POR_DEFECTO] for d in DIAS_POR_DEFECTO}, excepciones)


def calendario_desde_rangos(rangos: dict, excepciones=None) -> Calendario:
    """Desde el formato `{dia: (apertura, cierre) | None}` que usan `tools._rangos_de_atencion_por_dia` y las
    pruebas del horario de atención."""
    return crear_calendario({d: ([r] if r else []) for d, r in (rangos or {}).items()}, excepciones)


def calendario_desde_filas(filas_horario: list[dict] | None, excepciones=None) -> Calendario:
    """Desde las filas de `HorarioAtencion` (`listar_horarios_atencion`). Un día SIN fila usa el horario de
    siempre (lunes a sábado 8:00-19:00); un día con fila deshabilitada o sin horas está cerrado."""
    por_dia = {f["dia_semana"]: f for f in (filas_horario or [])}
    semana: dict = {}
    for dia in range(7):
        fila = por_dia.get(dia)
        if fila is not None:
            abierto = bool(fila.get("habilitado")) and fila.get("hora_apertura") and fila.get("hora_cierre")
            semana[dia] = [(fila["hora_apertura"], fila["hora_cierre"])] if abierto else []
        else:
            semana[dia] = [RANGO_POR_DEFECTO] if dia in DIAS_POR_DEFECTO else []
    return crear_calendario(semana, excepciones)


def rangos_de_semana(cal: Calendario) -> dict[int, tuple[str, str] | None]:
    """El horario SEMANAL como `{dia: (apertura, cierre) | None}` ("HH:MM"); con varios rangos en un día, del primer
    inicio al último cierre. Es el formato histórico de `_rangos_de_atencion_por_dia`."""
    rangos: dict = {}
    for dia in range(7):
        tramos = cal.semana.get(dia) or []
        rangos[dia] = (tramos[0][0].strftime("%H:%M"), tramos[-1][1].strftime("%H:%M")) if tramos else None
    return rangos


# ── Tiempo ──────────────────────────────────────────────────────────────────────────────────────────────

def a_lima(instante_utc: datetime) -> datetime:
    """UTC naive → hora de Lima naive."""
    return instante_utc - OFFSET_LIMA


def a_utc(instante_lima: datetime) -> datetime:
    """Hora de Lima naive → UTC naive."""
    return instante_lima + OFFSET_LIMA


def fecha_lima(instante_utc: datetime) -> date:
    return a_lima(instante_utc).date()


def hora_legible(hora) -> str:
    """"08:00" → "8:00 a. m."; "19:00" → "7:00 p. m." — como se escribe en Perú."""
    h = _a_hora(hora)
    sufijo = "a. m." if h.hour < 12 else "p. m."
    return f"{h.hour % 12 or 12}:{h.minute:02d} {sufijo}"


# ── Consultas por día ───────────────────────────────────────────────────────────────────────────────────

def tramos_del_dia(fecha: date, cal: Calendario) -> list[tuple[time, time]]:
    """Los rangos de atención de un día de Lima: la excepción manda sobre la semana; lista vacía = cerrado."""
    ex = cal.excepciones.get(fecha)
    if ex is not None:
        if not ex.atiende:
            return []
        if ex.hora_apertura and ex.hora_cierre:
            return _normalizar_tramos([(ex.hora_apertura, ex.hora_cierre)])
    return list(cal.semana.get(fecha.weekday()) or [])


def _tramos_datetime(fecha: date, cal: Calendario) -> list[tuple[datetime, datetime]]:
    return [(datetime.combine(fecha, a), datetime.combine(fecha, c)) for a, c in tramos_del_dia(fecha, cal)]


def excepcion_del_dia(fecha: date, cal: Calendario) -> DiaEspecial | None:
    return cal.excepciones.get(fecha)


def cerrado_todo_el_dia(fecha: date, cal: Calendario) -> bool:
    return not tramos_del_dia(fecha, cal)


# ── Estado, próxima apertura, tiempo hábil ──────────────────────────────────────────────────────────────

def esta_abierto(ahora_utc: datetime, cal: Calendario) -> bool:
    ahora_lima = a_lima(ahora_utc)
    return any(a <= ahora_lima < c for a, c in _tramos_datetime(ahora_lima.date(), cal))


def proxima_apertura(ahora_utc: datetime, cal: Calendario, horizonte_dias: int = HORIZONTE_DIAS_POR_DEFECTO) -> datetime | None:
    """Próxima vez que el negocio abre, SIEMPRE FUTURA (con el negocio abierto ahora es la del siguiente rango),
    como UTC naive. None solo si no hay ninguna apertura en los `horizonte_dias` siguientes: un cierre largo
    (hasta 3 semanas por defecto) se resuelve igual."""
    ahora_lima = a_lima(ahora_utc)
    for adelante in range(horizonte_dias + 1):
        for apertura, _cierre in _tramos_datetime(ahora_lima.date() + timedelta(days=adelante), cal):
            if apertura > ahora_lima:
                return a_utc(apertura)
    return None


def estado(ahora_utc: datetime, cal: Calendario, horizonte_dias: int = HORIZONTE_DIAS_POR_DEFECTO) -> dict:
    """`{"abierto": bool, "motivo": None | fuera_de_horario | feriado | no_laborable | puente | dia_sin_atencion |
    cierre_propio, "nombre": str | None, "proxima_apertura": UTC naive | None}`.

    `motivo` es None con el negocio abierto. Cerrado: feriado/no_laborable/puente/cierre_propio si una excepción de
    atiende=False cierra el día; `dia_sin_atencion` si es un día de descanso de la semana (p. ej. el domingo) o una
    excepción de atención especial sin atención; `fuera_de_horario` en cualquier otro caso (antes de abrir, después
    de cerrar, entre dos rangos, o un día con horario reducido). `nombre` es el de la excepción de hoy, si hay."""
    ahora_lima = a_lima(ahora_utc)
    fecha = ahora_lima.date()
    ex = cal.excepciones.get(fecha)
    abierto = esta_abierto(ahora_utc, cal)
    motivo = None
    if not abierto:
        if ex is not None and not ex.atiende:
            motivo = _MOTIVO_POR_TIPO.get(ex.tipo, MOTIVO_DIA_SIN_ATENCION)
        elif ex is None and not cal.semana.get(fecha.weekday()):
            motivo = MOTIVO_DIA_SIN_ATENCION
        else:
            motivo = MOTIVO_FUERA_DE_HORARIO
    return {
        "abierto": abierto, "motivo": motivo, "nombre": ex.nombre if ex is not None else None,
        "proxima_apertura": proxima_apertura(ahora_utc, cal, horizonte_dias),
    }


def pausa_vigente(ahora_utc: datetime, cal: Calendario, horizonte_dias: int = HORIZONTE_DIAS_POR_DEFECTO) -> dict | None:
    """Hay "pausa" cuando HOY (día de Lima) está cerrado por una EXCEPCIÓN del calendario (feriado, no laborable,
    puente, cierre propio): `{"motivo", "nombre", "reanuda_en": UTC naive | None}`. Un domingo normal o la noche de un
    día hábil NO son pausa (eso ya era así: nunca se contó como atraso)."""
    ex = cal.excepciones.get(fecha_lima(ahora_utc))
    if ex is None or ex.atiende:
        return None
    return {
        "motivo": _MOTIVO_POR_TIPO.get(ex.tipo, MOTIVO_DIA_SIN_ATENCION), "nombre": ex.nombre,
        "reanuda_en": proxima_apertura(ahora_utc, cal, horizonte_dias),
    }


def minutos_habiles(inicio_utc: datetime, fin_utc: datetime, cal: Calendario) -> float:
    """Minutos, entre dos instantes UTC naive, en que el negocio estuvo ABIERTO (excepciones incluidas: un feriado
    no suma). 0 si `fin <= inicio`."""
    if fin_utc <= inicio_utc:
        return 0.0
    inicio, fin = a_lima(inicio_utc), a_lima(fin_utc)
    total, dia = 0.0, inicio.date()
    while dia <= fin.date():
        for apertura, cierre in _tramos_datetime(dia, cal):
            desde, hasta = max(apertura, inicio), min(cierre, fin)
            if hasta > desde:
                total += (hasta - desde).total_seconds() / 60
        dia += timedelta(days=1)
    return total


# ── Textos para el cliente ──────────────────────────────────────────────────────────────────────────────

def describir_proxima_apertura(apertura_utc: datetime | None, ahora_utc: datetime) -> str:
    """"hoy a las 8:00 a. m.", "mañana a las 8:00 a. m.", "el viernes 9 a las 8:00 a. m." (de 2 a 6 días) o
    "el lunes 9 de noviembre a las 8:00 a. m." (una semana o más). Vacío si no hay próxima apertura."""
    if apertura_utc is None:
        return ""
    apertura, ahora = a_lima(apertura_utc), a_lima(ahora_utc)
    hora = hora_legible(apertura.time())
    diferencia = (apertura.date() - ahora.date()).days
    if diferencia <= 0:
        return f"hoy a las {hora}"
    if diferencia == 1:
        return f"mañana a las {hora}"
    dia = f"el {DIAS_ES[apertura.weekday()]} {apertura.day}"
    if diferencia >= 7:
        dia += f" de {MESES_ES[apertura.month - 1]}"
    return f"{dia} a las {hora}"


def describir_motivo(motivo: str | None, nombre: str | None = None) -> str:
    """El motivo del cierre en una frase corta, en minúsculas: "hoy es feriado: Combate de Angamos". Vacío para
    `fuera_de_horario` y para el negocio abierto (no hay nada especial que decir)."""
    sufijo = f": {nombre}" if nombre else ""
    if motivo == MOTIVO_FERIADO:
        return f"hoy es feriado{sufijo}"
    if motivo == MOTIVO_NO_LABORABLE:
        return f"hoy es día no laborable{sufijo}"
    if motivo == MOTIVO_PUENTE:
        return f"hoy es día de puente{sufijo}"
    if motivo == MOTIVO_CIERRE_PROPIO:
        return f"hoy no hay atención{sufijo}"
    if motivo == MOTIVO_DIA_SIN_ATENCION:
        return "hoy no es día de atención"
    return ""
