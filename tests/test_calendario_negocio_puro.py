# tests/test_calendario_negocio_puro.py — Calendario de negocio, Fase 1 (2026-10-12): el módulo PURO
# `agent/calendario_negocio.py` y la constante `agent/calendario_peru.py`. Sin base de datos.
#
# Calendario de referencia de 2026 que usan los ejemplos: jueves 8-oct (Combate de Angamos), viernes 9, sábado 10,
# domingo 11, lunes 12. Datos sintéticos únicamente.

from datetime import date, datetime, timedelta

import pytest

from agent import calendario_negocio as cn
from agent import calendario_peru

LUN_SAB = {d: ("08:00", "19:00") for d in range(6)} | {6: None}


def lima(mes: int, dia: int, hora: int = 0, minuto: int = 0, anio: int = 2026) -> datetime:
    """Instante UTC naive de una hora de Lima."""
    return datetime(anio, mes, dia, hora, minuto) + timedelta(hours=5)


def feriado(mes: int, dia: int, nombre: str = "Combate de Angamos", **kw) -> cn.DiaEspecial:
    return cn.DiaEspecial(date(2026, mes, dia), kw.pop("tipo", cn.TIPO_FERIADO), nombre, **kw)


def cal(*excepciones: cn.DiaEspecial, semana=None) -> cn.Calendario:
    return cn.calendario_desde_rangos(semana or LUN_SAB, list(excepciones))


# ── Día normal ──────────────────────────────────────────────────────────────

def test_dia_normal_abierto_en_horario_y_cerrado_fuera():
    c = cal()
    assert cn.esta_abierto(lima(10, 7, 8), c) and cn.esta_abierto(lima(10, 7, 18, 59), c)
    assert not cn.esta_abierto(lima(10, 7, 19), c) and not cn.esta_abierto(lima(10, 7, 7, 59), c)
    e = cn.estado(lima(10, 7, 21), c)
    assert e["abierto"] is False and e["motivo"] == cn.MOTIVO_FUERA_DE_HORARIO and e["nombre"] is None
    assert e["proxima_apertura"] == lima(10, 8, 8)
    assert cn.estado(lima(10, 7, 10), c)["motivo"] is None


def test_domingo_es_dia_sin_atencion_y_la_proxima_apertura_es_el_lunes():
    e = cn.estado(lima(10, 11, 12), cal())
    assert e["abierto"] is False and e["motivo"] == cn.MOTIVO_DIA_SIN_ATENCION
    assert e["proxima_apertura"] == lima(10, 12, 8)


def test_la_proxima_apertura_es_siempre_futura():
    c = cal()
    assert cn.proxima_apertura(lima(10, 7, 10), c) == lima(10, 8, 8)       # abierto ahora: la del día siguiente
    assert cn.proxima_apertura(lima(10, 7, 8), c) == lima(10, 8, 8)        # justo a la hora de apertura: ya no es futura
    assert cn.proxima_apertura(lima(10, 7, 7, 59), c) == lima(10, 7, 8)


# ── Feriados ────────────────────────────────────────────────────────────────

def test_feriado_cierra_el_dia_y_dice_motivo_y_nombre():
    c = cal(feriado(10, 8))
    e = cn.estado(lima(10, 8, 10), c)
    assert e["abierto"] is False and e["motivo"] == cn.MOTIVO_FERIADO and e["nombre"] == "Combate de Angamos"
    assert e["proxima_apertura"] == lima(10, 9, 8)
    assert cn.tramos_del_dia(date(2026, 10, 8), c) == []
    assert cn.cerrado_todo_el_dia(date(2026, 10, 8), c)
    assert cn.estado(lima(10, 9, 10), c)["abierto"] is True                 # el día siguiente es normal


def test_feriado_en_domingo_no_cambia_nada_pero_conserva_su_motivo():
    c = cal(feriado(11, 1, "Día de Todos los Santos"), semana=LUN_SAB)
    e = cn.estado(lima(11, 1, 12), c)
    assert e["abierto"] is False and e["motivo"] == cn.MOTIVO_FERIADO
    assert cn.minutos_habiles(lima(10, 31, 0), lima(11, 2, 0), c) == cn.minutos_habiles(lima(10, 31, 0), lima(11, 2, 0), cal())


@pytest.mark.parametrize("tipo,motivo", [
    (cn.TIPO_NO_LABORABLE, cn.MOTIVO_NO_LABORABLE), (cn.TIPO_PUENTE, cn.MOTIVO_PUENTE),
    (cn.TIPO_CIERRE_PROPIO, cn.MOTIVO_CIERRE_PROPIO), (cn.TIPO_ATENCION_ESPECIAL, cn.MOTIVO_DIA_SIN_ATENCION),
])
def test_cada_tipo_cerrado_da_su_motivo(tipo, motivo):
    c = cal(feriado(10, 8, "X", tipo=tipo, atiende=False))
    assert cn.estado(lima(10, 8, 10), c)["motivo"] == motivo


def test_no_laborable_que_atiende_no_cambia_el_horario_normal():
    c = cal(feriado(10, 8, "Día no laborable voluntario", tipo=cn.TIPO_NO_LABORABLE, atiende=True))
    assert cn.estado(lima(10, 8, 10), c)["abierto"] is True
    assert cn.minutos_habiles(lima(10, 8, 0), lima(10, 9, 0), c) == 11 * 60


def test_feriado_con_horario_especial_usa_ese_horario():
    c = cal(feriado(10, 8, atiende=True, hora_apertura="09:00", hora_cierre="13:00"))
    assert cn.esta_abierto(lima(10, 8, 9), c) and not cn.esta_abierto(lima(10, 8, 8, 30), c)
    assert cn.esta_abierto(lima(10, 8, 12, 59), c) and not cn.esta_abierto(lima(10, 8, 13), c)
    e = cn.estado(lima(10, 8, 15), c)
    assert e["abierto"] is False and e["motivo"] == cn.MOTIVO_FUERA_DE_HORARIO and e["nombre"] == "Combate de Angamos"
    assert cn.minutos_habiles(lima(10, 8, 0), lima(10, 9, 0), c) == 4 * 60
    assert cn.proxima_apertura(lima(10, 8, 15), c) == lima(10, 9, 8)


def test_atencion_especial_puede_abrir_un_domingo():
    c = cal(feriado(10, 11, "Campaña de domingo", tipo=cn.TIPO_ATENCION_ESPECIAL, atiende=True, hora_apertura="10:00", hora_cierre="14:00"))
    assert cn.esta_abierto(lima(10, 11, 11), c) and not cn.esta_abierto(lima(10, 11, 15), c)
    assert cn.proxima_apertura(lima(10, 10, 20), c) == lima(10, 11, 10)


def test_puente_que_une_con_el_fin_de_semana():
    # negocio de lunes a viernes: jueves 8 feriado + viernes 9 puente + sábado/domingo → vuelve el lunes 12 a las 8:00
    lun_vie = {d: ("08:00", "19:00") for d in range(5)} | {5: None, 6: None}
    c = cal(feriado(10, 8), feriado(10, 9, "Puente", tipo=cn.TIPO_PUENTE, atiende=False), semana=lun_vie)
    assert cn.proxima_apertura(lima(10, 7, 20), c) == lima(10, 12, 8)
    assert cn.proxima_apertura(lima(10, 7, 12), c) == lima(10, 12, 8)      # incluso abierto el miércoles
    # miércoles 17:00 → lunes 9:00: solo 2 h del miércoles y 1 h del lunes
    assert cn.minutos_habiles(lima(10, 7, 17), lima(10, 12, 9), c) == 3 * 60
    assert cn.estado(lima(10, 9, 12), c)["motivo"] == cn.MOTIVO_PUENTE
    assert cn.estado(lima(10, 10, 12), c)["motivo"] == cn.MOTIVO_DIA_SIN_ATENCION
    # con sábado hábil, el puente solo adelanta la apertura al sábado
    assert cn.proxima_apertura(lima(10, 7, 20), cal(feriado(10, 8), feriado(10, 9, "Puente", tipo=cn.TIPO_PUENTE))) == lima(10, 10, 8)


def test_cierre_largo_de_mas_de_8_dias_se_resuelve():
    # 12 días seguidos cerrados (del lunes 12 al viernes 23, más el domingo)
    cerrados = [feriado(10, d, "Cierre por inventario", tipo=cn.TIPO_CIERRE_PROPIO) for d in range(12, 24)]
    c = cal(*cerrados)
    assert cn.proxima_apertura(lima(10, 11, 20), c) == lima(10, 24, 8)
    assert (cn.proxima_apertura(lima(10, 11, 20), c) - lima(10, 11, 20)) > timedelta(days=8)
    # el viejo `range(8)` habría devuelto None desde un día cualquiera del cierre
    assert cn.proxima_apertura(lima(10, 14, 12), c) == lima(10, 24, 8)
    assert cn.estado(lima(10, 14, 12), c)["proxima_apertura"] == lima(10, 24, 8)


def test_proxima_apertura_none_si_no_hay_apertura_en_el_horizonte():
    cerrado_siempre = cn.calendario_desde_rangos({d: None for d in range(7)})
    assert cn.proxima_apertura(lima(10, 7, 12), cerrado_siempre) is None
    assert cn.estado(lima(10, 7, 12), cerrado_siempre)["proxima_apertura"] is None
    # cierre propio de 30 días: más allá de las 3 semanas por defecto → None; con un horizonte mayor sí aparece
    c = cal(*[cn.DiaEspecial(date(2026, 10, 8) + timedelta(days=i), cn.TIPO_CIERRE_PROPIO, "X") for i in range(30)])
    assert cn.proxima_apertura(lima(10, 7, 20), c) is None
    assert cn.proxima_apertura(lima(10, 7, 20), c, horizonte_dias=40) == lima(11, 7, 8)


# ── Varios rangos por día y cruce de medianoche UTC ─────────────────────────

def test_varios_rangos_por_dia():
    semana = {d: [("08:00", "12:00"), ("14:00", "18:00")] for d in range(5)}
    c = cn.crear_calendario(semana)
    assert cn.esta_abierto(lima(10, 7, 11), c) and not cn.esta_abierto(lima(10, 7, 13), c) and cn.esta_abierto(lima(10, 7, 15), c)
    assert cn.proxima_apertura(lima(10, 7, 13), c) == lima(10, 7, 14)
    assert cn.proxima_apertura(lima(10, 7, 19), c) == lima(10, 8, 8)
    assert cn.minutos_habiles(lima(10, 7, 0), lima(10, 8, 0), c) == 8 * 60
    assert cn.minutos_habiles(lima(10, 7, 11), lima(10, 7, 15), c) == 2 * 60       # 11-12 y 14-15
    assert cn.rangos_de_semana(c)[0] == ("08:00", "18:00") and cn.rangos_de_semana(c)[6] is None


def test_cruce_de_medianoche_utc_se_resuelve_en_hora_de_lima():
    c = cal(feriado(10, 12, "Feriado del lunes"))
    # 21:00 de Lima del lunes 12 = 02:00 UTC del martes 13: sigue siendo LUNES para el negocio (feriado)
    instante = datetime(2026, 10, 13, 2, 0)
    assert cn.fecha_lima(instante) == date(2026, 10, 12)
    assert cn.estado(instante, c)["motivo"] == cn.MOTIVO_FERIADO
    assert cn.proxima_apertura(instante, c) == lima(10, 13, 8)
    # 18:00-20:00 de Lima del miércoles cruza la medianoche UTC (23:00 → 01:00): solo cuenta la hora hasta las 19:00
    assert cn.minutos_habiles(lima(10, 7, 18), lima(10, 7, 20), cal()) == 60
    assert cn.esta_abierto(datetime(2026, 10, 7, 23, 59), cal())           # 18:59 de Lima
    assert not cn.esta_abierto(datetime(2026, 10, 8, 0, 0), cal())         # 19:00 de Lima


# ── minutos_habiles ─────────────────────────────────────────────────────────

def test_minutos_habiles_entre_dias_distintos():
    c = cal()
    assert cn.minutos_habiles(lima(10, 9, 17), lima(10, 10, 10), c) == 4 * 60            # vie 17-19 + sáb 8-10
    assert cn.minutos_habiles(lima(10, 10, 18), lima(10, 12, 9), c) == 2 * 60            # sáb 18-19, domingo 0, lun 8-9
    assert cn.minutos_habiles(lima(10, 10, 20), lima(10, 11, 23), c) == 0
    assert cn.minutos_habiles(lima(10, 9, 10), lima(10, 9, 9), c) == 0


def test_minutos_habiles_una_semana_completa():
    # lunes 5 a lunes 12: lun-sáb = 6 días de 11 h
    assert cn.minutos_habiles(lima(10, 5, 0), lima(10, 12, 0), cal()) == 6 * 11 * 60


def test_un_feriado_resta_su_dia_a_los_minutos_habiles():
    assert cn.minutos_habiles(lima(10, 5, 0), lima(10, 12, 0), cal(feriado(10, 8))) == 5 * 11 * 60


# ── Pausa y textos ──────────────────────────────────────────────────────────

def test_pausa_vigente_solo_con_un_dia_cerrado_por_excepcion():
    c = cal(feriado(10, 8))
    p = cn.pausa_vigente(lima(10, 8, 15), c)
    assert p == {"motivo": cn.MOTIVO_FERIADO, "nombre": "Combate de Angamos", "reanuda_en": lima(10, 9, 8)}
    assert cn.pausa_vigente(lima(10, 7, 15), c) is None
    assert cn.pausa_vigente(lima(10, 11, 15), c) is None                  # un domingo normal no es pausa
    assert cn.pausa_vigente(lima(10, 7, 21), c) is None                   # la noche de un día hábil tampoco
    con_horario = cal(feriado(10, 8, atiende=True, hora_apertura="09:00", hora_cierre="13:00"))
    assert cn.pausa_vigente(lima(10, 8, 15), con_horario) is None


def test_describir_proxima_apertura():
    ahora = lima(10, 7, 20)
    assert cn.describir_proxima_apertura(lima(10, 7, 8), lima(10, 7, 6)) == "hoy a las 8:00 a. m."
    assert cn.describir_proxima_apertura(lima(10, 8, 8), ahora) == "mañana a las 8:00 a. m."
    assert cn.describir_proxima_apertura(lima(10, 9, 8), ahora) == "el viernes 9 a las 8:00 a. m."
    assert cn.describir_proxima_apertura(lima(10, 12, 8), ahora) == "el lunes 12 a las 8:00 a. m."
    assert cn.describir_proxima_apertura(lima(10, 19, 8), ahora) == "el lunes 19 de octubre a las 8:00 a. m."
    assert cn.describir_proxima_apertura(lima(10, 9, 14, 30), ahora) == "el viernes 9 a las 2:30 p. m."
    assert cn.describir_proxima_apertura(None, ahora) == ""


def test_describir_motivo():
    assert cn.describir_motivo(cn.MOTIVO_FERIADO, "Combate de Angamos") == "hoy es feriado: Combate de Angamos"
    assert cn.describir_motivo(cn.MOTIVO_NO_LABORABLE, "Elecciones") == "hoy es día no laborable: Elecciones"
    assert cn.describir_motivo(cn.MOTIVO_FUERA_DE_HORARIO) == "" and cn.describir_motivo(None) == ""


# ── Construcción ────────────────────────────────────────────────────────────

def test_calendario_desde_filas_usa_el_horario_de_siempre_para_los_dias_sin_fila():
    c = cn.calendario_desde_filas([])
    assert cn.rangos_de_semana(c) == LUN_SAB
    c = cn.calendario_desde_filas([
        {"dia_semana": 0, "habilitado": True, "hora_apertura": "09:00", "hora_cierre": "13:00"},
        {"dia_semana": 1, "habilitado": False, "hora_apertura": None, "hora_cierre": None},
    ])
    r = cn.rangos_de_semana(c)
    assert r[0] == ("09:00", "13:00") and r[1] is None and r[2] == ("08:00", "19:00") and r[6] is None


def test_sin_excepciones_es_identico_al_calculo_historico():
    """Regresión: contra una copia del cálculo ANTERIOR (cuatro copias del horario semanal) en una grilla de instantes."""
    def tramo(fecha):
        r = LUN_SAB.get(fecha.weekday())
        if not r:
            return None
        return datetime.combine(fecha, datetime.strptime(r[0], "%H:%M").time()), datetime.combine(fecha, datetime.strptime(r[1], "%H:%M").time())

    def abierto_ref(ahora):
        l = ahora - timedelta(hours=5)
        t = tramo(l.date())
        return bool(t and t[0] <= l < t[1])

    def horas_ref(desde, hasta):
        if hasta <= desde:
            return 0.0
        d, h = desde - timedelta(hours=5), hasta - timedelta(hours=5)
        total, dia = 0.0, d.date()
        while dia <= h.date():
            t = tramo(dia)
            if t and min(t[1], h) > max(t[0], d):
                total += (min(t[1], h) - max(t[0], d)).total_seconds() / 3600
            dia += timedelta(days=1)
        return total

    def proxima_ref(ahora):
        l = ahora - timedelta(hours=5)
        for adelante in range(8):
            t = tramo(l.date() + timedelta(days=adelante))
            if t and t[0] > l:
                return t[0] + timedelta(hours=5)
        return None

    c = cal()
    base = lima(10, 1, 0)
    instantes = [base + timedelta(minutes=37 * i) for i in range(0, 24 * 60 * 14 // 37)]
    for i in instantes:
        assert cn.esta_abierto(i, c) == abierto_ref(i)
        assert cn.proxima_apertura(i, c) == proxima_ref(i)
    for a, b in zip(instantes[::7], instantes[11::7]):
        assert cn.minutos_habiles(a, b, c) / 60 == pytest.approx(horas_ref(a, b))
        assert cn.minutos_habiles(b, a, c) == 0


# ── Feriados de Perú (constante) ────────────────────────────────────────────

def test_feriados_2026_son_los_verificados():
    f = calendario_peru.feriados_de(2026)
    assert [x["fecha"] for x in f] == [
        date(2026, 1, 1), date(2026, 4, 2), date(2026, 4, 3), date(2026, 5, 1), date(2026, 6, 7), date(2026, 6, 29),
        date(2026, 7, 23), date(2026, 7, 28), date(2026, 7, 29), date(2026, 8, 6), date(2026, 8, 30), date(2026, 10, 8),
        date(2026, 11, 1), date(2026, 12, 8), date(2026, 12, 9), date(2026, 12, 25),
    ]
    assert all(x["verificado"] for x in f) and calendario_peru.nota_del_anio(2026) is None
    assert next(x for x in f if x["fecha"] == date(2026, 10, 8))["nombre"] == "Combate de Angamos"


def test_feriados_2027_se_marcan_no_verificados():
    f = calendario_peru.feriados_de(2027)
    assert len(f) == 16 and all(not x["verificado"] for x in f)
    assert date(2027, 3, 25) in {x["fecha"] for x in f} and date(2027, 3, 26) in {x["fecha"] for x in f}
    assert "no verificado" in calendario_peru.nota_del_anio(2027)
    assert all(x["fuente_url"].startswith("https://www.elperuano.pe") for x in f)


def _pascua(anio: int) -> date:
    """Algoritmo de Gauss/Meeus para la Pascua gregoriana."""
    a, b, c = anio % 19, anio // 100, anio % 100
    d, e = b // 4, b % 4
    g = (8 * b + 13) // 25
    h = (19 * a + b - d - g + 15) % 30
    j, k = c // 4, c % 4
    m = (a + 11 * h) // 319
    r = (2 * e + 2 * j - k - h + m + 32) % 7
    mes = (h - m + r + 90) // 25
    dia = (h - m + r + mes + 19) % 32
    return date(anio, mes, dia)


@pytest.mark.parametrize("anio", [2026, 2027])
def test_semana_santa_coincide_con_la_pascua_calculada(anio):
    pascua = _pascua(anio)
    fechas = {x["fecha"] for x in calendario_peru.feriados_de(anio)}
    assert pascua - timedelta(days=3) in fechas and pascua - timedelta(days=2) in fechas
    assert pascua == {2026: date(2026, 4, 5), 2027: date(2027, 3, 28)}[anio]


def test_anio_sin_lista_pide_agregarla():
    with pytest.raises(ValueError):
        calendario_peru.feriados_de(2031)
    assert calendario_peru.buscar_feriado(date(2026, 12, 25))["nombre"] == "Navidad"
    assert calendario_peru.buscar_feriado(date(2026, 12, 26)) is None
