# tests/test_llamadas_puntaje.py — "Para llamar" (2026-10-09, agent/llamadas.py): las piezas PURAS del diseño D3.
# Tabla de casos del puntaje (E3), datos nulos que a veces devuelve el modelo económico que extrae los datos del lead,
# rechazo del cliente (E4), teléfono llamable, segmentos, holdout determinista, franjas de reintento y que las reglas de
# texto no se desalineen de las del análisis de conversión que sostiene el diseño.

from datetime import datetime, timedelta

import pytest

from agent import llamadas as ll


# ── Puntaje ──────────────────────────────────────────────────────────────────────────────────────

def _puntaje(**kw):
    base = dict(
        mensajes_cliente=0, pidio_datos_o_financiamiento=False, dio_precio=False, producto_conocido=False,
        nombre_conocido=False, paso_flujo=None,
    )
    base.update(kw)
    return ll.calcular_puntaje(**base)[0]


@pytest.mark.parametrize("kw, esperado", [
    ({}, 0),
    ({"mensajes_cliente": 1}, 0),                                  # con un solo mensaje no suma
    ({"mensajes_cliente": 2}, 3),
    ({"mensajes_cliente": 9}, 3),                                  # no es proporcional
    ({"pidio_datos_o_financiamiento": True}, 3),
    ({"dio_precio": True}, 2),
    ({"producto_conocido": True}, 2),
    ({"nombre_conocido": True}, 1),
    ({"paso_flujo": "comparando_producto"}, 1),
    ({"paso_flujo": "evaluando_financiamiento"}, 1),
    ({"paso_flujo": "explorando"}, 0),
    ({"paso_flujo": "derivado_asesor"}, 0),
    ({"paso_flujo": "  Comparando_Producto "}, 1),                  # tolera mayúsculas y espacios
    ({"mensajes_cliente": 2, "dio_precio": True, "producto_conocido": True}, 7),
    (dict(mensajes_cliente=2, pidio_datos_o_financiamiento=True, dio_precio=True, producto_conocido=True, nombre_conocido=True, paso_flujo="comparando_producto"), 12),
])
def test_tabla_del_puntaje(kw, esperado):
    assert _puntaje(**kw) == esperado


def test_el_desglose_suma_el_puntaje_y_lista_las_seis_senales():
    puntaje, puntos = ll.calcular_puntaje(
        mensajes_cliente=3, pidio_datos_o_financiamiento=True, dio_precio=False, producto_conocido=True, nombre_conocido=False,
        paso_flujo="explorando",
    )
    assert puntaje == sum(puntos.values()) == 8
    assert set(puntos) == {"mensajes_cliente", "datos_o_financiamiento", "precio", "producto", "nombre", "paso"}


@pytest.mark.parametrize("puntaje, minimo, esperado", [
    (12, 4, "A"), (6, 4, "A"), (5, 4, "B"), (4, 4, "B"), (3, 4, None), (0, 4, None),
    (5, 5, "B"), (6, 7, None), (7, 7, "A"), (6, 6, "A"), (4, 3, "B"), (3, 3, "B"),
])
def test_segmentos(puntaje, minimo, esperado):
    assert ll.segmento_de(puntaje, minimo) == esperado


# ── Datos nulos del modelo económico ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize("valor", [
    None, "", "   ", "null", "NULL", "None", "none", "nan", "N/A", "n/a", "na", "-", "--", "?", "desconocido", "Desconocido",
    "no especificado", "sin_dato", "ninguno", "unknown", 0, 5, ["terma"], {"a": 1}, True,
])
def test_un_dato_nulo_o_raro_no_cuenta_como_conocido(valor):
    assert ll.dato_conocido(valor) is False


@pytest.mark.parametrize("valor", ["terma", "Rheem", " Ana ", "cocina a gas", "combo"])
def test_un_dato_real_cuenta_como_conocido(valor):
    assert ll.dato_conocido(valor) is True


# ── Teléfono llamable ────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("telefono, ok", [
    ("51987654321", True), ("51900000001", True),
    ("987654321", False),          # sin código de país
    ("14155550123", False),        # 11 dígitos pero de otro país
    ("5198765432", False), ("519876543210", False),
    ("A1B2C3D4E5F", False),        # BSUID de Meta
    ("+51987654321", False), ("", False), (None, False),
])
def test_solo_se_llama_a_numeros_peruanos_reales(telefono, ok):
    assert ll.es_telefono_peruano(telefono) is ok


# ── Rechazo del cliente ──────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("texto", [
    "No me interesa, gracias", "ya no me interesa", "No, gracias", "no gracias", "NO ME LLAMEN por favor", "no me llamen",
    "este número está equivocado", "Número equivocado", "me equivoqué de número", "ya compré uno", "Ya lo compré", "no soy cliente de calidda",
    "dejen de escribirme", "deja de llamar", "no quiero que me llamen", "no quiero llamadas",
])
def test_frases_de_rechazo(texto):
    assert ll.hay_rechazo([texto]) is True


@pytest.mark.parametrize("texto", [
    "Hola, quiero una terma", "me interesa la de 80 litros", "¿cuánto cuesta?", "puedes llamarme mañana", "gracias por la info, lo reviso",
    "mi DNI es 12345678", "",
])
def test_frases_que_no_son_rechazo(texto):
    assert ll.hay_rechazo([texto]) is False


def test_el_rechazo_mira_cualquiera_de_los_textos():
    assert ll.hay_rechazo(["hola", "no me interesa", "ok"]) is True
    assert ll.hay_rechazo([]) is False


# ── Reglas de texto: iguales a las del análisis de conversión ────────────────────────────────────

@pytest.mark.parametrize("texto", [
    "El precio es S/ 1,200", "cuesta S/. 500", "son 800 soles", "Soles disponibles", "Hola, ¿cómo estás?",
    "Necesito tu DNI", "Envíame tu documento de identidad", "hay financiamiento en cuotas", "pagas en tu recibo de gas",
    "Te cuento de la terma", "¿Cómo te llamas?", "",
])
def test_las_reglas_de_precio_dni_y_financiamiento_coinciden_con_el_analisis(texto):
    from scripts.analisis_conversion import rasgos_texto
    analisis, mias = rasgos_texto(texto), ll.rasgos_gabi(texto)
    assert (mias["precio"], mias["dni"], mias["financ"]) == (analisis["precio"], analisis["dni"], analisis["financ"])


def test_el_suministro_cuenta_como_dato_pedido():
    assert ll.rasgos_gabi("¿Me indicas tu número de suministro?")["dni"] is True
    assert ll.rasgos_gabi("Dime tu número de cliente")["dni"] is True


# ── Holdout y exploración ────────────────────────────────────────────────────────────────────────

def test_el_holdout_es_determinista_y_respeta_los_extremos():
    ids = [f"conv-{i}" for i in range(400)]
    assert all(ll.grupo_de(i, 0) == "llamar" for i in ids)
    assert all(ll.grupo_de(i, 100) == "control" for i in ids)
    assert [ll.grupo_de(i, 30) for i in ids] == [ll.grupo_de(i, 30) for i in ids]
    control = sum(1 for i in ids if ll.grupo_de(i, 30) == "control")
    assert 90 <= control <= 150      # ~30 % de 400


def test_la_exploracion_usa_otra_sal_que_el_holdout():
    ids = [f"conv-{i}" for i in range(400)]
    assert not any(ll.entra_a_exploracion(i, 0) for i in ids)
    assert all(ll.entra_a_exploracion(i, 100) for i in ids)
    en_expl = [i for i in ids if ll.entra_a_exploracion(i, 10)]
    assert 20 <= len(en_expl) <= 60
    assert set(en_expl) != {i for i in ids if ll.grupo_de(i, 10) == "control"}   # no son el mismo grupo de conversaciones


# ── Franjas de reintento ─────────────────────────────────────────────────────────────────────────

RANGOS = {d: ("08:00", "19:00") for d in range(6)} | {6: None}     # lunes a sábado 8-19 (Lima)


def _utc(lima: str) -> datetime:
    return datetime.fromisoformat(lima) + timedelta(hours=5)


def test_tras_un_no_contesto_de_la_manana_se_reintenta_en_la_tarde_del_mismo_dia():
    ahora = _utc("2026-10-07 10:00")          # miércoles
    proximo = ll.proxima_franja(RANGOS, ahora, ahora)
    assert proximo == _utc("2026-10-07 13:30")  # la tarde empieza a la mitad del horario (8:00-19:00 → 13:30)


def test_tras_un_no_contesto_de_la_tarde_se_reintenta_a_la_manana_siguiente():
    ahora = _utc("2026-10-07 15:00")
    assert ll.proxima_franja(RANGOS, ahora, ahora) == _utc("2026-10-08 08:00")


def test_respeta_la_separacion_minima_de_tres_horas():
    ahora = _utc("2026-10-07 13:00")          # la tarde empieza 13:30, pero faltan menos de 3 h para el mínimo de 16:00
    proximo = ll.proxima_franja(RANGOS, ahora, _utc("2026-10-07 09:00"))
    assert proximo == _utc("2026-10-07 16:00") and proximo - ahora >= timedelta(hours=3)


def test_salta_los_dias_cerrados():
    ahora = _utc("2026-10-10 15:00")          # sábado por la tarde → el lunes por la mañana (domingo cerrado)
    assert ll.proxima_franja(RANGOS, ahora, ahora) == _utc("2026-10-12 08:00")


def test_un_negocio_que_nunca_abre_no_tiene_proxima_franja():
    assert ll.proxima_franja({d: None for d in range(7)}, datetime.utcnow(), None) is None


# ── Oferta ───────────────────────────────────────────────────────────────────────────────────────

def test_el_texto_por_defecto_de_la_oferta_es_valido_y_se_rellena():
    assert ll.texto_de_oferta_valido(ll.OFERTA_TEXTO_POR_DEFECTO) is None
    texto = ll.armar_oferta(None, "Ana López", "terma de 80 litros")
    assert texto.startswith("Hola Ana, soy Gabi.") and "consulta de terma de 80 litros" in texto
    assert "Si prefieres que no te llamemos, avísame y no lo hacemos." in texto


def test_sin_nombre_ni_producto_no_quedan_huecos():
    texto = ll.armar_oferta(None, "null", None)
    assert texto.startswith("Hola, soy Gabi.") and "tu consulta." in texto and "{" not in texto


@pytest.mark.parametrize("texto", ["", "   ", "Hola, te cuento de nuestras termas", "Un asesor te llama hoy, ¿a qué hora?", "x" * 601])
def test_una_oferta_sin_salida_o_sin_llamada_o_muy_larga_no_es_valida(texto):
    assert ll.texto_de_oferta_valido(texto) is not None
