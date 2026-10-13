# agent/calendario_peru.py — Feriados nacionales de Perú, versionados en el código (2026-10-12, Fase 1)
#
# Constante PURA (sin base de datos). La siembra en la base (`memory.sembrar_calendario`, el script
# `scripts/sembrar_calendario.py` y el botón "Cargar feriados de Perú {año}" del panel) lee de acá.
#
# Alcance: SOLO feriados nacionales de Perú de cumplimiento obligatorio para el sector privado. Los días «no
# laborables» (que para el sector privado son voluntarios) y los «puentes» NO se precargan: los decide y los carga
# el administrador a mano cuando el Gobierno los decreta, y por defecto no cierran el negocio salvo que él lo marque.
#
# VERIFICACIÓN (leer antes de confiar):
#   · 2026 — verificado por el agente de diseño H1 (2026-10-12). Jueves y Viernes Santo calculados desde la Pascua
#     del 5-abr-2026.
#   · 2027 — SIN fuente oficial verificada: calculado (Pascua del 28-mar-2027 → Jueves/Viernes Santo 25 y 26-mar; el
#     resto son fechas fijas). 2027 NO VERIFICADO: revisar cada año contra el diario oficial El Peruano y contra los
#     decretos que agreguen días (el Gobierno puede declarar feriados o no laborables extra con poca anticipación).
#
# `fuente_url` apunta al diario oficial (sitio principal): es la fuente donde se publican las normas; no se inventa un
# enlace a una nota concreta.

from datetime import date

FUENTE_EL_PERUANO = "https://www.elperuano.pe"

NOTA_2027_NO_VERIFICADO = "2027 no verificado: fechas calculadas, revisar cada año contra El Peruano."

# (mes, día, nombre) de los feriados de fecha fija, comunes a todos los años.
_FIJOS_ENERO = ((1, 1, "Año Nuevo"),)
_FIJOS_MAYO_EN_ADELANTE = (
    (5, 1, "Día del Trabajo"),
    (6, 7, "Batalla de Arica y Día de la Bandera"),
    (6, 29, "San Pedro y San Pablo"),
    (7, 23, "Día de la Fuerza Aérea del Perú"),
    (7, 28, "Fiestas Patrias"),
    (7, 29, "Fiestas Patrias"),
    (8, 6, "Batalla de Junín"),
    (8, 30, "Santa Rosa de Lima"),
    (10, 8, "Combate de Angamos"),
    (11, 1, "Día de Todos los Santos"),
    (12, 8, "Inmaculada Concepción"),
    (12, 9, "Batalla de Ayacucho"),
    (12, 25, "Navidad"),
)

# Jueves y Viernes Santo (dependen de la Pascua).
_SEMANA_SANTA = {
    2026: (date(2026, 4, 2), date(2026, 4, 3)),
    2027: (date(2027, 3, 25), date(2027, 3, 26)),
}

# Años con lista disponible y si están verificados contra fuente oficial.
VERIFICADO_POR_ANIO = {2026: True, 2027: False}
ANIOS_DISPONIBLES = tuple(sorted(VERIFICADO_POR_ANIO))


def _armar(anio: int) -> list[dict]:
    jueves, viernes = _SEMANA_SANTA[anio]
    filas = [(date(anio, m, d), nombre) for m, d, nombre in _FIJOS_ENERO]
    filas += [(jueves, "Jueves Santo"), (viernes, "Viernes Santo")]
    filas += [(date(anio, m, d), nombre) for m, d, nombre in _FIJOS_MAYO_EN_ADELANTE]
    return [
        {
            "fecha": fecha, "nombre": nombre, "fuente_url": FUENTE_EL_PERUANO,
            "verificado": VERIFICADO_POR_ANIO[anio],
        }
        for fecha, nombre in sorted(filas)
    ]


FERIADOS_PERU: dict[int, list[dict]] = {anio: _armar(anio) for anio in ANIOS_DISPONIBLES}


def feriados_de(anio: int) -> list[dict]:
    """Los feriados nacionales de `anio`: `[{fecha: date, nombre, fuente_url, verificado: bool}]` ordenados por fecha.
    Lanza ValueError si no hay lista para ese año (hay que agregarla a este archivo, revisada contra El Peruano)."""
    if anio not in FERIADOS_PERU:
        raise ValueError(
            f"No hay feriados precargados para {anio}. Años disponibles: {', '.join(str(a) for a in ANIOS_DISPONIBLES)}."
        )
    return [dict(f) for f in FERIADOS_PERU[anio]]


def nota_del_anio(anio: int) -> str | None:
    """Aviso para mostrar junto al año si su lista no está verificada; None si está verificada."""
    if VERIFICADO_POR_ANIO.get(anio):
        return None
    return NOTA_2027_NO_VERIFICADO if anio == 2027 else f"{anio} no verificado: revisar contra El Peruano."


def buscar_feriado(fecha: date) -> dict | None:
    """El feriado precargado de esa fecha (para saber si una fila sembrada está verificada), o None."""
    for f in FERIADOS_PERU.get(fecha.year, []):
        if f["fecha"] == fecha:
            return dict(f)
    return None
