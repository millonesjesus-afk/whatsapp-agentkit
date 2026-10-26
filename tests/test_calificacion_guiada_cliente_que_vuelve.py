# tests/test_calificacion_guiada_cliente_que_vuelve.py — Un cliente que ya tuvo una conversación y la vio cerrarse, y vuelve con una
# conversación NUEVA, es un primer mensaje de nuevo: el flujo guiado debe arrancar (caso real del 25-oct: el flujo contaba los
# mensajes de TODO el teléfono y creía que ya lo habían atendido, así que Gabi respondió con IA y sin botones).
import os

os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")
os.environ.setdefault("WHATSAPP_PROVIDER", "meta")
os.environ["DEBOUNCE_RESPUESTA_SEGUNDOS"] = "0"

from agent import brain, calificacion_guiada as cg, memory as mem
from tests.test_cierre_cortesia import _caso_cerrado, _correr, _msg, _preparar_webhook


async def _volver(monkeypatch, codigo: str, telefono: str, texto: str):
    negocio, canal, canal_dict, _conv = await _caso_cerrado(codigo, telefono, cierre="cron")
    await mem.guardar_configuracion(cg.CLAVE_MODO, "activo", negocio_id=negocio["id"])
    proveedor, gabi = _preparar_webhook(monkeypatch, canal_dict, canal, [])
    proveedor.interactivos = []

    async def enviar_interactivo(telefono, interactivo, canal=None):
        proveedor.interactivos.append(interactivo)
        return True, f"wamid.INT{len(proveedor.interactivos)}"
    proveedor.enviar_interactivo = enviar_interactivo
    await _correr(proveedor, [_msg(telefono, canal, texto, f"wamid.vuelve-{codigo}")])
    return negocio, proveedor, gabi


async def test_cliente_que_vuelve_con_el_texto_del_anuncio_recibe_el_primer_mensaje_fijo(monkeypatch):
    negocio, proveedor, gabi = await _volver(monkeypatch, "g-cv-01", "51960010001", "Estoy interesado en financiar una Terma")
    assert gabi.llamadas == 0 and len(proveedor.interactivos) == 1
    cuerpo = proveedor.interactivos[0]["body"]["text"]
    assert cuerpo.startswith("Hola 👋 Soy Gabi") and cuerpo.endswith("¿Tu casa ya tiene gas natural de Cálidda?")


async def test_cliente_que_vuelve_con_una_pregunta_recibe_la_ia_y_despues_la_pregunta_de_gas(monkeypatch):
    negocio, proveedor, gabi = await _volver(monkeypatch, "g-cv-02", "51960010002", "¿Cuánto demora la instalación de una terma?")
    assert gabi.llamadas == 1 and len(proveedor.interactivos) == 1
    assert proveedor.interactivos[0]["body"]["text"] == "¿Tu casa ya tiene gas natural de Cálidda?"


async def test_el_contexto_de_claude_cuenta_solo_la_conversacion_activa(monkeypatch):
    negocio, proveedor, gabi = await _volver(monkeypatch, "g-cv-03", "51960010003", "¿Cuánto demora la instalación de una terma?")
    lead = await mem.obtener_lead("51960010003", negocio_id=negocio["id"])
    # el historial del TELÉFONO trae 4+ mensajes de antes; la conversación nueva solo tiene el de ahora
    historial_del_telefono = [{"role": "user", "content": "x"}, {"role": "assistant", "content": "y"}] * 5
    dichos = await brain._textos_del_cliente_en_la_conversacion("51960010003", negocio["id"], historial_del_telefono, "¿Cuánto demora la instalación de una terma?")
    assert dichos == []
    bloques = await brain._armar_bloques_contexto("hola", historial_del_telefono, lead, negocio["id"])
    assert not any("Respuestas del cliente a preguntas con botones" in b for b in bloques)
