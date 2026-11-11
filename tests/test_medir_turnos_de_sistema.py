"""Clasificación de mensajes del cliente para medir qué turnos podrían ser texto fijo (scripts/medir_turnos_de_sistema.py) — datos sintéticos."""
import pytest

from scripts import medir_turnos_de_sistema as m


@pytest.mark.parametrize("texto", ["Ok", "ok gracias", "Muchas gracias!", "Perfecto 👍", "Listo, gracias", "de acuerdo", "Ok, muchas gracias por la información", "Gracias, igualmente"])
def test_cortesias(texto):
    assert m.clasificar(texto) == "cortesia"


@pytest.mark.parametrize("texto", [
    "No estoy interesado en la secadora. Gracias.", "ya no me interesa", "no gracias", "Entonces, Srta. No estoy interesado en la secadora. Gracias.",
])
def test_no_interesado(texto):
    assert m.clasificar(texto) == "no_interesado"


@pytest.mark.parametrize("texto", [
    "Entonces puedes quitar mi número de su base de datos, para que no me escriban por favor", "no me escriban más", "dejen de molestar", "borren mis datos",
])
def test_retiro_de_datos_gana_sobre_los_demas(texto):
    assert m.clasificar(texto) == "retiro_datos"


@pytest.mark.parametrize("texto", ["Hola", "Buenas tardes", "buenos días"])
def test_saludos(texto):
    assert m.clasificar(texto) == "saludo"


@pytest.mark.parametrize("texto", [
    "¿Cuánto cuesta la secadora de 22 kg?", "ok pero cuánto sale", "gracias, y tienen en cuotas?", "si", "no", "quiero una terma a gas de 55 litros", "Consulta, esta máquina también lava?",
])
def test_lo_demas_queda_en_otro(texto):
    assert m.clasificar(texto) == "otro"


def test_vacio():
    assert m.clasificar("") == "vacio" and m.clasificar(None) == "vacio"


def test_resumen_cuenta_y_estima_ahorro_solo_de_los_tipos_cerrados():
    def ev(texto, delicado=False):
        return {"ultimo_cliente": texto, "payload": {"delicado": delicado}}

    eventos = [ev("ok"), ev("gracias"), ev("no me interesa"), ev("¿cuánto cuesta?", delicado=True), ev("quiero una terma")]
    r = m.resumir(eventos)
    assert r["respuestas"] == 5
    assert r["tipos"]["cortesia"]["n"] == 2 and r["tipos"]["cortesia"]["pct"] == 40.0
    assert r["tipos"]["no_interesado"]["n"] == 1
    assert r["tipos"]["otro"]["n"] == 2 and r["tipos"]["otro"]["ahorro_mensual_usd"] == 0.0
    assert r["tipos"]["cortesia"]["ahorro_mensual_usd"] > 0
    assert r["tipos"]["otro"]["de_ellos_no_delicados"] == 1
