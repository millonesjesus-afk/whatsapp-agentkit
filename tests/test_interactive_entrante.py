# tests/test_interactive_entrante.py — 2026-10-05: un toque en un botón o en una
# fila de lista de un mensaje interactivo llega a Meta como `type: "interactive"`;
# antes caía en el `else` del parser (texto vacío, tipo "interactive") y el
# cliente recibía "no puedo abrir ese tipo de mensaje". Ahora se trata como si
# hubiera escrito el título del botón/fila (igual que el tipo `button` de las
# plantillas). Payloads con la forma real de Meta, datos sintéticos.

import os

os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")
os.environ.setdefault("WHATSAPP_PROVIDER", "meta")

from sqlalchemy import select
from starlette.requests import Request

from agent import main as app_main
from agent import memory as mem
from agent.providers.base import MensajeEntrante
from agent.providers.meta import ProveedorMeta


class _RequestMeta:
    def __init__(self, mensaje: dict):
        self._cuerpo = {"entry": [{"changes": [{"value": {"metadata": {"phone_number_id": "123"}, "messages": [mensaje]}}]}]}

    async def json(self):
        return self._cuerpo


def _payload_interactivo(interactivo: dict, **extra) -> dict:
    return {
        "from": "51900000001", "id": "wamid.INT1", "timestamp": "1760000000", "type": "interactive",
        "interactive": interactivo, "context": {"from": "51911111111", "id": "wamid.ORIGINAL"}, **extra,
    }


async def _parsear(mensaje: dict) -> MensajeEntrante:
    return (await ProveedorMeta().parsear_webhook(_RequestMeta(mensaje)))[0]


# ── Parser ──────────────────────────────────────────────────────────────────

async def test_button_reply_se_vuelve_texto_con_el_titulo_y_guarda_los_ids():
    m = await _parsear(_payload_interactivo({"type": "button_reply", "button_reply": {"id": "btn_si", "title": "Sí, cuéntame más"}}))
    assert m.tipo == "text"
    assert m.texto == "Sí, cuéntame más"
    assert m.interactivo_id == "btn_si"
    assert m.contexto_id == "wamid.ORIGINAL"
    assert m.mensaje_id == "wamid.INT1" and m.telefono == "51900000001" and m.numero_whatsapp_id == "123"
    assert m.media is None and m.es_propio is False


async def test_list_reply_se_vuelve_texto_con_el_titulo_de_la_fila():
    m = await _parsear(_payload_interactivo({
        "type": "list_reply", "list_reply": {"id": "fila_terma", "title": "Terma a gas", "description": "5.5 L"},
    }))
    assert m.tipo == "text" and m.texto == "Terma a gas"
    assert m.interactivo_id == "fila_terma" and m.contexto_id == "wamid.ORIGINAL"


async def test_button_reply_sin_title_no_rompe_y_queda_con_texto_vacio():
    m = await _parsear(_payload_interactivo({"type": "button_reply", "button_reply": {"id": "btn_si"}}))
    assert m.tipo == "text" and m.texto == "" and m.interactivo_id == "btn_si"


async def test_interactivo_sin_el_objeto_de_respuesta_no_rompe():
    m = await _parsear(_payload_interactivo({"type": "button_reply"}))
    assert m.tipo == "text" and m.texto == "" and m.interactivo_id == ""
    m2 = await _parsear({"from": "51900000001", "id": "wamid.INT2", "type": "interactive"})
    assert m2.tipo == "interactive" and m2.texto == "" and m2.contexto_id == ""


async def test_sin_context_el_contexto_id_queda_vacio():
    mensaje = _payload_interactivo({"type": "button_reply", "button_reply": {"id": "b", "title": "Hola"}})
    del mensaje["context"]
    m = await _parsear(mensaje)
    assert m.texto == "Hola" and m.contexto_id == ""


async def test_nfm_reply_de_flows_y_subtipos_desconocidos_siguen_como_antes():
    flow = await _parsear(_payload_interactivo({
        "type": "nfm_reply", "nfm_reply": {"name": "flow", "body": "Sent", "response_json": "{}"},
    }))
    assert flow.tipo == "interactive" and flow.texto == "" and flow.interactivo_id == ""
    raro = await _parsear(_payload_interactivo({"type": "algo_nuevo", "algo_nuevo": {"id": "x", "title": "Y"}}))
    assert raro.tipo == "interactive" and raro.texto == ""


async def test_un_texto_normal_no_cambia_y_trae_los_campos_nuevos_vacios():
    m = await _parsear({"from": "51900000001", "id": "wamid.T", "type": "text", "text": {"body": "hola"}})
    assert (m.tipo, m.texto, m.interactivo_id, m.contexto_id) == ("text", "hola", "", "")


async def test_texto_que_responde_a_un_mensaje_conserva_el_contexto():
    m = await _parsear({
        "from": "51900000001", "id": "wamid.T2", "type": "text", "text": {"body": "sí"},
        "context": {"from": "51911111111", "id": "wamid.CITADO"},
    })
    assert m.texto == "sí" and m.contexto_id == "wamid.CITADO"


# ── Flujo completo: el toque se trata como texto ────────────────────────────

def _request() -> Request:
    cuerpo = b'{"object": "whatsapp_business_account"}'
    entregado = False

    async def recibir():
        nonlocal entregado
        if entregado:
            return {"type": "http.disconnect"}
        entregado = True
        return {"type": "http.request", "body": cuerpo, "more_body": False}

    return Request({
        "type": "http", "method": "POST", "path": "/webhook", "headers": [], "query_string": b"",
        "client": ("203.0.113.9", 1234),
    }, recibir)


class _ProveedorFalso:
    """Parsea con el parser REAL de Meta el payload crudo que se le indique."""

    def __init__(self, canal: dict):
        self._canal = canal
        self._crudo: dict | None = None
        self.enviados: list[str] = []

    def payload(self, crudo: dict) -> None:
        self._crudo = crudo

    async def verificar_firma(self, request, cuerpo):
        return True

    async def parsear_webhook(self, request):
        crudo = {**self._crudo, "from": self._crudo.get("from", "51906000001")}
        return await ProveedorMeta().parsear_webhook(_RequestMeta(crudo))

    async def resolver_canal(self, numero_whatsapp_id, negocio_id=None):
        return self._canal

    async def marcar_leido_y_escribiendo(self, mensaje_id, canal=None):
        return True

    async def enviar_mensaje(self, telefono, mensaje, canal=None, mensaje_id_citado=None):
        self.enviados.append(mensaje)
        return True, "wamid.OK"


async def _armar(monkeypatch, codigo: str):
    negocio = await mem.crear_negocio(f"Negocio {codigo}", codigo)
    canal_db = await mem.crear_canal_whatsapp(nombre=f"Canal {codigo}", phone_number_id="123", negocio_id=negocio["id"])
    canal = {
        "id": canal_db["id"], "negocio_id": negocio["id"], "unidad_id": None,
        "phone_number_id": canal_db["phone_number_id"], "modo": "produccion",
    }
    proveedor = _ProveedorFalso(canal)
    monkeypatch.setattr(app_main, "proveedor", proveedor)
    monkeypatch.setenv("DEBOUNCE_RESPUESTA_SEGUNDOS", "0.05")

    llamadas: list[str] = []

    async def respuesta_de_gabi(mensaje, historial, lead, modo="produccion", negocio_id=None):
        llamadas.append(mensaje)
        return "¡Claro! Te cuento más", False, None, None

    async def sin_datos(*args, **kwargs):
        return {}

    monkeypatch.setattr(app_main.servicio_inteligencia, "generar_respuesta", respuesta_de_gabi)
    monkeypatch.setattr(app_main.servicio_inteligencia, "extraer_datos_lead", sin_datos)
    return negocio, proveedor, llamadas


async def _mensajes(negocio_id: str, role: str) -> list:
    async with mem.async_session() as session:
        r = await session.execute(
            select(mem.Mensaje).where(mem.Mensaje.negocio_id == negocio_id, mem.Mensaje.role == role).order_by(mem.Mensaje.id)
        )
        return r.scalars().all()


async def test_el_toque_de_un_boton_llega_a_gabi_como_si_el_cliente_lo_hubiera_escrito(monkeypatch):
    negocio, proveedor, llamadas = await _armar(monkeypatch, "g-int-01")
    proveedor.payload(_payload_interactivo({"type": "button_reply", "button_reply": {"id": "btn_si", "title": "Sí, cuéntame más"}}))

    await app_main.webhook_handler(_request())
    await app_main.gestor_debounce_respuestas.esperar_pendientes()

    assert llamadas == ["Sí, cuéntame más"]
    assert [m.content for m in await _mensajes(negocio["id"], "user")] == ["Sí, cuéntame más"]
    assert proveedor.enviados == ["¡Claro! Te cuento más"]
    assert not any("no puedo" in e.lower() for e in proveedor.enviados)  # ya no hay aviso de "tipo no soportado"


async def test_el_toque_de_una_fila_de_lista_tambien_es_texto(monkeypatch):
    negocio, proveedor, llamadas = await _armar(monkeypatch, "g-int-02")
    proveedor.payload(_payload_interactivo({"type": "list_reply", "list_reply": {"id": "f1", "title": "Terma a gas"}}))

    await app_main.webhook_handler(_request())
    await app_main.gestor_debounce_respuestas.esperar_pendientes()

    assert llamadas == ["Terma a gas"]
    assert [m.content for m in await _mensajes(negocio["id"], "user")] == ["Terma a gas"]


async def test_un_button_reply_sin_title_no_rompe_el_webhook_ni_dispara_a_gabi(monkeypatch):
    negocio, proveedor, llamadas = await _armar(monkeypatch, "g-int-03")
    proveedor.payload(_payload_interactivo({"type": "button_reply", "button_reply": {"id": "btn_si"}}))

    resultado = await app_main.webhook_handler(_request())
    await app_main.gestor_debounce_respuestas.esperar_pendientes()

    assert resultado == {"status": "ok"}
    assert llamadas == [] and proveedor.enviados == []
    assert await _mensajes(negocio["id"], "user") == []
