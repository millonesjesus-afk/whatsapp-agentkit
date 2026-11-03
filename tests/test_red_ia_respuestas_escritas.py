# tests/test_red_ia_respuestas_escritas.py — Red de seguridad con IA para las respuestas escritas del flujo guiado (2026-11-02).
#
# Caso real (chat 645b7ded): la clienta contestó «Solo yo soy la unica» y «Solo vivo yo sola» a la pregunta de tamaño; las reglas no la
# entendieron, la pregunta se repitió 3 veces y la clienta se molestó. Ahora: las reglas entienden «solo yo / vivo sola» (gratis) y,
# para lo que ninguna regla prevé, un Haiku elige una opción de la pregunta; si duda, falla o no hay saldo, todo sigue como antes.
import json
import os

os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")
os.environ.setdefault("WHATSAPP_PROVIDER", "meta")
os.environ["DEBOUNCE_RESPUESTA_SEGUNDOS"] = "0"

import pytest

from agent import calificacion_guiada as cg, memory as mem
from tests.test_bloque_b_rafagas_y_respuestas_escritas import _respuestas_en_timeline
from tests.test_calificacion_guiada import _cuerpo, _escenario, _hablar, _tel, _tocar


class _IA:
    """Doble de `_llamar_ia_interprete`: devuelve lo configurado (texto o dict→JSON) o lanza el error."""

    def __init__(self, respuesta=None, error=None):
        self.respuesta, self.error, self.llamadas = respuesta, error, []

    async def __call__(self, cuerpo, titulos, texto):
        self.llamadas.append((cuerpo, titulos, texto))
        if self.error:
            raise self.error
        return self.respuesta if isinstance(self.respuesta, str) else json.dumps(self.respuesta)


# ── Reglas gratis: «solo yo», «vivo sola» ────────────────────────────────────

@pytest.mark.parametrize("texto", ["Solo yo soy la unica", "Solo vivo yo sola", "vivo sola", "yo sola", "solo yo", "soy yo solo"])
@pytest.mark.parametrize("tipo", ["secadora", "lavado"])
def test_una_persona_sola_es_hasta_4_personas(texto, tipo):
    assert cg.interpretar_texto("tamano", texto, tipo) == "pequena"


@pytest.mark.parametrize("texto,esperado", [("solo yo y mis 6 hijos", None), ("vivo sola con mi hija y 2 nietos", None), ("somos 6", "grande")])
def test_solo_yo_no_pisa_un_numero(texto, esperado):
    assert cg.interpretar_texto("tamano", texto, "secadora") == esperado


def test_solo_yo_no_aplica_a_los_banos_de_la_terma():
    assert cg.interpretar_texto("tamano", "solo yo", "terma") is None


# ── La función de IA ─────────────────────────────────────────────────────────

async def test_la_ia_elige_la_opcion_y_se_valida(monkeypatch):
    ia = _IA({"opcion": 1, "confianza": 0.95})
    monkeypatch.setattr(cg, "_llamar_ia_interprete", ia)
    assert await cg.interpretar_texto_con_ia("tamano", "somos mi mama y yo nada mas", "secadora") == "pequena"
    cuerpo, titulos, texto = ia.llamadas[0]
    assert len(titulos) >= 2 and texto == "somos mi mama y yo nada mas"


@pytest.mark.parametrize("respuesta", [
    {"opcion": 0, "confianza": 0.99},           # no sabe → no elige
    {"opcion": 1, "confianza": 0.5},            # confianza baja
    {"opcion": 9, "confianza": 0.99},           # opción que no existe
    "no es json", "", {"confianza": 0.9},
])
async def test_la_ia_con_duda_o_salida_rota_no_elige(monkeypatch, respuesta):
    monkeypatch.setattr(cg, "_llamar_ia_interprete", _IA(respuesta))
    assert await cg.interpretar_texto_con_ia("tamano", "quien sabe", "secadora") is None


async def test_si_la_ia_falla_o_no_hay_saldo_no_lanza_y_devuelve_none(monkeypatch):
    monkeypatch.setattr(cg, "_llamar_ia_interprete", _IA(error=RuntimeError("credit balance is too low")))
    assert await cg.interpretar_texto_con_ia("tamano", "somos pocos", "secadora") is None


@pytest.mark.parametrize("paso,texto", [
    ("dato", "mi dni es 45781236"),             # el DNI y el número de cliente nunca van a la IA
    ("tamano", "¿cuántos kilos trae?"),         # una pregunta la atiende Gabi
    ("tamano", ""), ("tamano", "palabra " * 30),
])
async def test_no_se_llama_a_la_ia_para_el_dato_las_preguntas_ni_textos_largos(monkeypatch, paso, texto):
    ia = _IA({"opcion": 1, "confianza": 0.99})
    monkeypatch.setattr(cg, "_llamar_ia_interprete", ia)
    assert await cg.interpretar_texto_con_ia(paso, texto, "secadora") is None
    assert ia.llamadas == []


# ── De punta a punta ─────────────────────────────────────────────────────────

async def _hasta_el_tamano_de_secadora(monkeypatch, n: int):
    negocio, canal, canal_dict, proveedor, gabi = await _escenario(monkeypatch, "activo")
    tel = _tel(n)
    await _hablar(proveedor, canal, tel, "Estoy interesado en financiar una Secadora")
    await _tocar(proveedor, canal, tel, "cal:gas:si", "Sí, ya tengo")
    await _tocar(proveedor, canal, tel, "cal:equipo:punto", "Sí, tengo el punto")
    await _tocar(proveedor, canal, tel, "cal:titular:si", "Sí, soy el titular")
    return tel, canal, proveedor, gabi


async def test_la_ia_entiende_lo_que_ninguna_regla_preve_y_el_flujo_avanza(monkeypatch):
    tel, canal, proveedor, gabi = await _hasta_el_tamano_de_secadora(monkeypatch, 80)
    ia = _IA({"opcion": 1, "confianza": 0.95})
    monkeypatch.setattr(cg, "_llamar_ia_interprete", ia)
    await _hablar(proveedor, canal, tel, "somos mi mami y yo nada mas")
    estado = await mem.obtener_estado_calificacion(tel)
    assert estado["respuestas"]["tamano"] == "pequena" and estado["conteo"]["tamano"] == 1      # no se repitió la pregunta
    assert gabi.llamadas == 0 and "un dato del titular" in _cuerpo(proveedor)
    ultimo = (await _respuestas_en_timeline(tel))[0]
    assert ultimo["payload"]["origen"] == "texto_ia" and ultimo["payload"]["valor"] == "pequena"


async def test_si_la_ia_no_esta_segura_todo_sigue_como_antes(monkeypatch):
    tel, canal, proveedor, gabi = await _hasta_el_tamano_de_secadora(monkeypatch, 81)
    monkeypatch.setattr(cg, "_llamar_ia_interprete", _IA({"opcion": 0, "confianza": 0.9}))
    await _hablar(proveedor, canal, tel, "depende de la epoca")
    estado = await mem.obtener_estado_calificacion(tel)
    assert "tamano" not in estado["respuestas"] and gabi.llamadas == 1                          # contesta Gabi y se retoma la pregunta


async def test_con_el_interruptor_apagado_no_se_llama_a_la_ia(monkeypatch):
    tel, canal, proveedor, gabi = await _hasta_el_tamano_de_secadora(monkeypatch, 82)
    ia = _IA({"opcion": 1, "confianza": 0.99})
    monkeypatch.setattr(cg, "_llamar_ia_interprete", ia)

    async def _apagado(clave, defecto=None, negocio_id=None):
        return "0" if clave == cg.CLAVE_IA_TEXTO else defecto

    monkeypatch.setattr(mem, "obtener_configuracion", _apagado)
    await _hablar(proveedor, canal, tel, "somos mi mami y yo nada mas")
    assert ia.llamadas == [] and "tamano" not in (await mem.obtener_estado_calificacion(tel))["respuestas"]
