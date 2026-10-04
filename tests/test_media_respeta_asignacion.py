# tests/test_media_respeta_asignacion.py — un adjunto (audio/imagen/documento)
# o un tipo no soportado NUNCA debe hacer que Gabi vuelva a responder en una
# conversación con asesor ya asignado (Gate 2026-09-23: 2 casos reales en la
# misma conversación — la rama de media/no-soportado no chequeaba asignación,
# a diferencia de la rama de texto).

import os

os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")
os.environ.setdefault("WHATSAPP_PROVIDER", "meta")

import pytest
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


async def _mensajes_de(negocio_id: str, telefono: str, role: str) -> list:
    async with mem.async_session() as session:
        resultado = await session.execute(
            select(mem.Mensaje).where(
                mem.Mensaje.negocio_id == negocio_id, mem.Mensaje.telefono == telefono,
                mem.Mensaje.role == role,
            ).order_by(mem.Mensaje.id)
        )
        return resultado.scalars().all()


async def _mensajes_assistant(negocio_id: str, telefono: str) -> list:
    return await _mensajes_de(negocio_id, telefono, "assistant")


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


FRASE_POR_TIPO = [
    ("audio", "escuchar audios"),
    ("image", "fotos, videos ni stickers"),
    ("video", "fotos, videos ni stickers"),  # los GIF de WhatsApp llegan como video
    ("sticker", "fotos, videos ni stickers"),
    ("document", "ese tipo de mensaje"),
    ("unknown", "ese tipo de mensaje"),
]


@pytest.mark.parametrize("tipo,frase", FRASE_POR_TIPO)
async def test_sin_asesor_gabi_avisa_con_la_frase_del_tipo_y_pide_escribir(monkeypatch, tipo, frase):
    """Sin asesor asignado, lo que Gabi no puede leer recibe el aviso de siempre
    ("no puedo ... ¿me lo escribes por texto?"), ahora con la frase que
    corresponde al tipo: antes TODO decía "no puedo escuchar audios", incluso
    una foto. El mensaje del cliente igual se guarda para el panel."""
    telefono = "51903100004"
    negocio, proveedor = await _armar(monkeypatch, f"g-med-4{tipo[:2]}", telefono, tipo)

    await app_main.webhook_handler(_request())

    assert len(proveedor.enviados) == 1
    assert frase in proveedor.enviados[0] and "por texto" in proveedor.enviados[0]
    assert [m.content for m in await _mensajes_de(negocio["id"], telefono, "user")] == [f"[{tipo}]"]
    assert [m.content for m in await _mensajes_assistant(negocio["id"], telefono)] == proveedor.enviados


@pytest.mark.parametrize("tipo,_frase", FRASE_POR_TIPO)
async def test_con_asesor_asignado_ningun_tipo_recibe_respuesta_automatica(monkeypatch, tipo, _frase):
    """La regla que manda: con un asesor asignado NO se responde nada automático
    a ningún formato. El mensaje se guarda y el lead queda como "Nuevo"."""
    telefono = "51903100005"
    negocio, proveedor = await _armar(monkeypatch, f"g-med-5{tipo[:2]}", telefono, tipo)
    await mem.actualizar_lead(telefono, negocio_id=negocio["id"], numero_whatsapp_id="x")
    await mem.resolver_conversation_activa(telefono, negocio["id"], (await mem.listar_canales_whatsapp(negocio["id"]))[0]["id"])
    await mem.asignar_asesor_a_lead(telefono, "asesor1")

    await app_main.webhook_handler(_request())

    assert proveedor.enviados == [] and await _mensajes_assistant(negocio["id"], telefono) == []
    assert [m.content for m in await _mensajes_de(negocio["id"], telefono, "user")] == [f"[{tipo}]"]
    lead = await mem.obtener_lead(telefono, negocio_id=negocio["id"])
    assert lead["visto_asesor"] is False


async def test_una_reaccion_nunca_recibe_respuesta_ni_con_ni_sin_asesor(monkeypatch):
    for codigo, telefono, con_asesor in (("g-med-61", "51903100006", False), ("g-med-62", "51903100007", True)):
        negocio, proveedor = await _armar(monkeypatch, codigo, telefono, "reaction")
        proveedor._mensaje.texto = "Reaccionó con 👍"
        if con_asesor:
            await mem.actualizar_lead(telefono, negocio_id=negocio["id"], numero_whatsapp_id="x")
            await mem.resolver_conversation_activa(telefono, negocio["id"], (await mem.listar_canales_whatsapp(negocio["id"]))[0]["id"])
            await mem.asignar_asesor_a_lead(telefono, "asesor1")

        await app_main.webhook_handler(_request())

        assert proveedor.enviados == [] and await _mensajes_assistant(negocio["id"], telefono) == []
        assert [m.content for m in await _mensajes_de(negocio["id"], telefono, "user")] == ["Reaccionó con 👍"]


async def test_dos_adjuntos_seguidos_reciben_un_solo_aviso_y_ambos_quedan_guardados(monkeypatch):
    """Capa central de envíos (2026-10-04): tres fotos seguidas hacían tres avisos
    idénticos, tres mensajes de servicio. Ahora el aviso sale una vez por cliente
    cada 10 min; los adjuntos se guardan todos y no se inventa un mensaje de Gabi
    que no salió."""
    telefono = "51903100006"
    negocio, proveedor = await _armar(monkeypatch, "g-med-agr", telefono, "image")

    await app_main.webhook_handler(_request())
    proveedor._mensaje = MensajeEntrante(     # segunda foto: otro wamid (el mismo se descarta por duplicado)
        telefono=telefono, texto="", mensaje_id="wamid.g-med-agr-2", es_propio=False, tipo="image",
        numero_whatsapp_id=proveedor._canal["phone_number_id"],
    )
    await app_main.webhook_handler(_request())

    assert len(proveedor.enviados) == 1
    assert len(await _mensajes_de(negocio["id"], telefono, "user")) == 2
    assert len(await _mensajes_assistant(negocio["id"], telefono)) == 1
