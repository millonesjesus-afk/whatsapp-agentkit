# tests/test_media_respeta_asignacion.py — un adjunto (audio/imagen/documento)
# o un tipo no soportado NUNCA debe hacer que Gabi vuelva a responder en una
# conversación con asesor ya asignado (Gate 2026-09-23: 2 casos reales en la
# misma conversación — la rama de media/no-soportado no chequeaba asignación,
# a diferencia de la rama de texto).

import os

os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")
os.environ.setdefault("WHATSAPP_PROVIDER", "meta")

from sqlalchemy import select
from starlette.requests import Request

from agent import main as app_main
from agent import memory as mem
from agent.providers.base import MensajeEntrante


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
    def __init__(self, mensaje: MensajeEntrante, canal: dict):
        self._mensaje, self._canal = mensaje, canal
        self.enviados: list[str] = []

    async def verificar_firma(self, request, cuerpo):
        return True

    async def parsear_webhook(self, request):
        return [self._mensaje]

    async def resolver_canal(self, numero_whatsapp_id, negocio_id=None):
        return self._canal

    async def marcar_leido_y_escribiendo(self, mensaje_id, canal=None):
        return True

    async def enviar_mensaje(self, telefono, mensaje, canal=None, mensaje_id_citado=None):
        self.enviados.append(mensaje)
        return True, "wamid.OK"


async def _armar(monkeypatch, codigo: str, telefono: str, tipo: str) -> tuple[dict, _ProveedorFalso]:
    negocio = await mem.crear_negocio(f"Negocio {codigo}", codigo)
    canal_db = await mem.crear_canal_whatsapp(
        nombre=f"Canal {codigo}", phone_number_id=f"4093000{codigo[-2:]}", negocio_id=negocio["id"],
    )
    canal = {
        "id": canal_db["id"], "negocio_id": negocio["id"], "unidad_id": None,
        "phone_number_id": canal_db["phone_number_id"], "modo": "produccion",
    }
    mensaje = MensajeEntrante(
        telefono=telefono, texto="", mensaje_id=f"wamid.{codigo}", es_propio=False, tipo=tipo,
        numero_whatsapp_id=canal["phone_number_id"],
    )
    proveedor = _ProveedorFalso(mensaje, canal)
    monkeypatch.setattr(app_main, "proveedor", proveedor)
    return negocio, proveedor


async def _mensajes_assistant(negocio_id: str, telefono: str) -> list:
    async with mem.async_session() as session:
        resultado = await session.execute(
            select(mem.Mensaje).where(
                mem.Mensaje.negocio_id == negocio_id, mem.Mensaje.telefono == telefono,
                mem.Mensaje.role == "assistant",
            )
        )
        return resultado.scalars().all()


async def test_audio_no_reactiva_a_gabi_con_asesor_ya_asignado(monkeypatch):
    telefono = "51903100001"
    negocio, proveedor = await _armar(monkeypatch, "g-med-01", telefono, "audio")
    await mem.actualizar_lead(telefono, negocio_id=negocio["id"], numero_whatsapp_id="x")
    await mem.resolver_conversation_activa(telefono, negocio["id"], (await mem.listar_canales_whatsapp(negocio["id"]))[0]["id"])
    await mem.asignar_asesor_a_lead(telefono, "asesor1")

    await app_main.webhook_handler(_request())

    assert await _mensajes_assistant(negocio["id"], telefono) == []
    assert proveedor.enviados == []
    lead = await mem.obtener_lead(telefono, negocio_id=negocio["id"])
    assert lead["asesor_asignado"] == "asesor1"  # sigue asignado, nadie lo tocó


async def test_imagen_no_reactiva_a_gabi_con_pausado_manual(monkeypatch):
    telefono = "51903100002"
    negocio, proveedor = await _armar(monkeypatch, "g-med-02", telefono, "image")
    await mem.actualizar_lead(telefono, negocio_id=negocio["id"], numero_whatsapp_id="x")
    await mem.resolver_conversation_activa(telefono, negocio["id"], (await mem.listar_canales_whatsapp(negocio["id"]))[0]["id"])
    await mem.pausar_gabi_manual(telefono)

    await app_main.webhook_handler(_request())

    assert await _mensajes_assistant(negocio["id"], telefono) == []
    assert proveedor.enviados == []


async def test_tipo_no_soportado_no_reactiva_a_gabi_con_asesor_asignado(monkeypatch):
    telefono = "51903100003"
    negocio, proveedor = await _armar(monkeypatch, "g-med-03", telefono, "sticker")
    await mem.actualizar_lead(telefono, negocio_id=negocio["id"], numero_whatsapp_id="x")
    await mem.resolver_conversation_activa(telefono, negocio["id"], (await mem.listar_canales_whatsapp(negocio["id"]))[0]["id"])
    await mem.asignar_asesor_a_lead(telefono, "asesor1")

    await app_main.webhook_handler(_request())

    assert await _mensajes_assistant(negocio["id"], telefono) == []
    assert proveedor.enviados == []


async def test_audio_sigue_respondiendo_normal_sin_asesor_asignado(monkeypatch):
    """Control — el fix no debe cambiar el comportamiento de siempre cuando
    NO hay nadie asignado: Gabi sigue avisando que no puede escuchar audios."""
    telefono = "51903100004"
    negocio, proveedor = await _armar(monkeypatch, "g-med-04", telefono, "audio")

    await app_main.webhook_handler(_request())

    assert len(await _mensajes_assistant(negocio["id"], telefono)) == 1
    assert len(proveedor.enviados) == 1
