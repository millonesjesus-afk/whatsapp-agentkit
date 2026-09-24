# tests/test_mensajes_entrantes_tipos.py — 2026-09-24: el chat del panel mostraba
# "[reaction]" y no dejaba ver stickers, videos/GIF, ubicaciones ni contactos.
# Aquí se fija cómo se interpreta cada tipo que manda Meta y qué hace el webhook
# con ellos (sobre todo: una reacción NUNCA dispara a Gabi). Datos sintéticos.

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


async def _parsear(mensaje: dict) -> MensajeEntrante:
    return (await ProveedorMeta().parsear_webhook(_RequestMeta({"id": "wamid.T", "from": "51900000001", **mensaje})))[0]


# ── Cómo se interpreta cada tipo ────────────────────────────────────────────

async def test_reaccion_con_emoji_queda_como_texto_legible():
    m = await _parsear({"type": "reaction", "reaction": {"message_id": "wamid.X", "emoji": "👍"}})
    assert m.tipo == "reaction" and m.texto == "Reaccionó con 👍"


async def test_reaccion_sin_emoji_es_quitar_la_reaccion_y_no_deja_texto():
    m = await _parsear({"type": "reaction", "reaction": {"message_id": "wamid.X"}})
    assert m.tipo == "reaction" and m.texto == ""


async def test_ubicacion_se_vuelve_texto_con_enlace_a_maps():
    m = await _parsear({"type": "location", "location": {
        "latitude": -12.05, "longitude": -77.04, "name": "Mi casa", "address": "Av. Lima 123",
    }})
    assert m.tipo == "text"  # se trata como un mensaje normal: Gabi lo ve y responde
    assert "Ubicación compartida: Mi casa, Av. Lima 123" in m.texto
    assert "https://maps.google.com/?q=-12.05,-77.04" in m.texto


async def test_ubicacion_sin_datos_no_rompe():
    m = await _parsear({"type": "location", "location": {}})
    assert m.tipo == "text" and m.texto == "📍 Ubicación compartida"


async def test_contacto_compartido_lista_nombre_y_telefono():
    m = await _parsear({"type": "contacts", "contacts": [
        {"name": {"formatted_name": "Ana Pérez"}, "phones": [{"phone": "+51 900 111 222"}]},
        {"name": {"formatted_name": "Luis"}, "phones": []},
    ]})
    assert m.tipo == "text"
    assert m.texto == "👤 Contacto compartido: Ana Pérez (+51 900 111 222); Luis"


async def test_sticker_y_video_llegan_como_adjunto_descargable():
    sticker = await _parsear({"type": "sticker", "sticker": {"id": "MEDIA1", "mime_type": "image/webp", "animated": False}})
    assert sticker.tipo == "sticker" and sticker.media["media_id"] == "MEDIA1" and sticker.media["mime_type"] == "image/webp"
    video = await _parsear({"type": "video", "video": {"id": "MEDIA2", "mime_type": "video/mp4", "caption": "mira"}})
    assert video.tipo == "video" and video.media["caption"] == "mira"


# ── Qué extensiones se aceptan al guardar ───────────────────────────────────

def test_sticker_solo_se_guarda_si_es_webp():
    assert app_main._extension_permitida_para_media("sticker", "image/webp", "") == ".webp"
    assert app_main._extension_permitida_para_media("sticker", "image/jpeg", "") is None


def test_video_solo_se_guarda_si_es_mp4():
    assert app_main._extension_permitida_para_media("video", "video/mp4", "") == ".mp4"
    assert app_main._extension_permitida_para_media("video", "video/quicktime", "") is None


def test_un_documento_mp4_sigue_sin_estar_permitido():
    """Ver videos en el panel no abre la lista de extensiones que el panel deja ENVIAR."""
    assert app_main._extension_permitida_para_media("document", "video/mp4", "clip.mp4") is None
    assert ".mp4" not in app_main.EXTENSIONES_ARCHIVO_PERMITIDAS


# ── Qué hace el webhook ─────────────────────────────────────────────────────

def _request() -> Request:
    cuerpo = b'{"object": "whatsapp_business_account"}'
    entregado = False

    async def recibir():
        nonlocal entregado
        if entregado:
            return {"type": "http.disconnect"}
        entregado = True
        return {"type": "http.request", "body": cuerpo, "more_body": False}

    return Request({"type": "http", "method": "POST", "path": "/webhook", "headers": [], "query_string": b"",
                    "client": ("203.0.113.9", 1234)}, recibir)


class _ProveedorFalso:
    def __init__(self, mensaje, canal, descarga=None):
        self._mensaje, self._canal, self._descarga = mensaje, canal, descarga
        self.enviados: list[str] = []

    async def verificar_firma(self, request, cuerpo):
        return True

    async def parsear_webhook(self, request):
        return [self._mensaje]

    async def resolver_canal(self, numero_whatsapp_id, negocio_id=None):
        return self._canal

    async def marcar_leido_y_escribiendo(self, mensaje_id, canal=None):
        return True

    async def descargar_media(self, media_id, canal=None):
        return self._descarga

    async def enviar_mensaje(self, telefono, mensaje, canal=None, mensaje_id_citado=None):
        self.enviados.append(mensaje)
        return True, "wamid.OK"


async def _armar(monkeypatch, codigo: str, telefono: str, **campos_mensaje):
    negocio = await mem.crear_negocio(f"Negocio {codigo}", codigo)
    canal_db = await mem.crear_canal_whatsapp(
        nombre=f"Canal {codigo}", phone_number_id=f"4094000{codigo[-2:]}", negocio_id=negocio["id"],
    )
    canal = {"id": canal_db["id"], "negocio_id": negocio["id"], "unidad_id": None,
             "phone_number_id": canal_db["phone_number_id"], "modo": "produccion"}
    mensaje = MensajeEntrante(
        telefono=telefono, mensaje_id=f"wamid.{codigo}", es_propio=False,
        numero_whatsapp_id=canal["phone_number_id"], **{"texto": "", **campos_mensaje},
    )
    proveedor = _ProveedorFalso(mensaje, canal)
    monkeypatch.setattr(app_main, "proveedor", proveedor)
    return negocio, canal, proveedor


async def _mensajes(negocio_id: str, telefono: str, role: str) -> list:
    async with mem.async_session() as session:
        resultado = await session.execute(
            select(mem.Mensaje).where(
                mem.Mensaje.negocio_id == negocio_id, mem.Mensaje.telefono == telefono, mem.Mensaje.role == role,
            ).order_by(mem.Mensaje.id)
        )
        return resultado.scalars().all()


async def test_una_reaccion_se_guarda_y_gabi_no_responde_nada(monkeypatch):
    telefono = "51904200001"
    negocio, _, proveedor = await _armar(
        monkeypatch, "rx-01", telefono, tipo="reaction", texto="Reaccionó con 👍",
    )

    await app_main.webhook_handler(_request())

    assert [m.content for m in await _mensajes(negocio["id"], telefono, "user")] == ["Reaccionó con 👍"]
    assert await _mensajes(negocio["id"], telefono, "assistant") == []
    assert proveedor.enviados == []  # antes: "no puedo procesar este tipo de mensaje"


async def test_quitar_una_reaccion_no_guarda_ni_responde_nada(monkeypatch):
    telefono = "51904200002"
    negocio, _, proveedor = await _armar(monkeypatch, "rx-02", telefono, tipo="reaction", texto="")

    await app_main.webhook_handler(_request())

    assert await _mensajes(negocio["id"], telefono, "user") == []
    assert proveedor.enviados == []


async def test_un_sticker_se_guarda_como_adjunto_con_su_tipo(monkeypatch, tmp_path):
    telefono = "51904200003"
    negocio, canal, proveedor = await _armar(
        monkeypatch, "rx-03", telefono, tipo="sticker", media={"media_id": "M1", "mime_type": "image/webp", "filename": "", "caption": ""},
    )
    proveedor._descarga = (b"RIFF0000WEBPVP8 ", "image/webp")
    monkeypatch.setattr(app_main, "_guardar_archivo_en_disco", lambda nombre, contenido: str(tmp_path / "sticker.webp"))
    await mem.actualizar_lead(telefono, negocio_id=negocio["id"], numero_whatsapp_id="x")
    await mem.resolver_conversation_activa(telefono, negocio["id"], canal["id"])
    await mem.asignar_asesor_a_lead(telefono, "asesor1")  # con asesor no hay respuesta automática

    await app_main.webhook_handler(_request())

    [guardado] = await _mensajes(negocio["id"], telefono, "user")
    assert guardado.content == "[sticker]" and guardado.archivo_id is not None
    archivo = await mem.obtener_archivo_adjunto(guardado.archivo_id)
    assert archivo["content_type"] == "image/webp"
