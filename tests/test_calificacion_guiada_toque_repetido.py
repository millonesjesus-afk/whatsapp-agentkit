# tests/test_calificacion_guiada_toque_repetido.py — Los botones de WhatsApp siguen tocables para siempre. Un toque en una pregunta que
# el cliente YA respondió no reescribe sus respuestas ni cambia el camino del flujo: lo atiende Gabi como texto y se retoma la pregunta
# que sigue pendiente.
import os

os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")
os.environ.setdefault("WHATSAPP_PROVIDER", "meta")
os.environ["DEBOUNCE_RESPUESTA_SEGUNDOS"] = "0"

from agent import memory as mem
from tests.test_calificacion_guiada import _cuerpo, _escenario, _hablar, _tel, _tocar


async def test_un_toque_contradictorio_en_una_pregunta_ya_respondida_no_cambia_el_camino(monkeypatch):
    negocio, canal, canal_dict, proveedor, gabi = await _escenario(monkeypatch, "activo")
    tel = _tel(40)
    await _hablar(proveedor, canal, tel, "Estoy interesado en financiar una Terma")
    await _tocar(proveedor, canal, tel, "cal:gas:si", "Sí, ya tengo")
    assert "terma" in _cuerpo(proveedor)                                                  # gas = sí → sigue la pregunta de equipo
    llamadas = gabi.llamadas

    await _tocar(proveedor, canal, tel, "cal:gas:no", "No tengo aún")                      # toca el botón viejo, con OTRA respuesta
    estado = await mem.obtener_estado_calificacion(tel)
    assert estado["respuestas"] == {"gas": "si"}                                           # su respuesta original no se reescribe
    assert "singas" not in estado["preguntas"]                                             # y no entró al camino «sin gas»
    assert gabi.llamadas == llamadas + 1                                                   # lo atendió Gabi como mensaje de texto
    eventos = [e for e in await mem.listar_eventos_lead(tel) if e["tipo"] == "calificacion_respuesta"]
    assert len(eventos) == 1                                                               # sin respuestas duplicadas en el Timeline
    assert estado["conteo"].get("equipo", 0) <= 2                                          # la pendiente se retoma, sin repetirse sin fin


async def test_el_toque_normal_sigue_avanzando(monkeypatch):
    negocio, canal, canal_dict, proveedor, gabi = await _escenario(monkeypatch, "activo")
    tel = _tel(41)
    await _hablar(proveedor, canal, tel, "Estoy interesado en financiar una Terma")
    await _tocar(proveedor, canal, tel, "cal:gas:si", "Sí, ya tengo")
    await _tocar(proveedor, canal, tel, "cal:equipo:ambos", "Punto de gas y ductería")
    assert _cuerpo(proveedor) == "¿El suministro de gas de esa casa está a tu nombre?"
