# tests/test_gabi_envio_fallido.py — cuando Meta rechaza un mensaje de Gabi, el
# panel debe verlo como "fallido" (2026-09-21: dos clientes reales quedaron sin
# respuesta y el panel mostraba las respuestas de Gabi como enviadas).

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
    def __init__(self, mensaje: MensajeEntrante, canal: dict, acepta_envio: bool):
        self._mensaje, self._canal, self._acepta = mensaje, canal, acepta_envio

    async def verificar_firma(self, request, cuerpo):
        return True

    async def parsear_webhook(self, request):
        return [self._mensaje]

    async def resolver_canal(self, numero_whatsapp_id, negocio_id=None):
        return self._canal

    async def marcar_leido_y_escribiendo(self, mensaje_id, canal=None):
        return True

    async def enviar_mensaje(self, telefono, mensaje, canal=None, mensaje_id_citado=None):
        return (True, "wamid.OK") if self._acepta else (False, None)


async def _armar(monkeypatch, codigo: str, telefono: str, tipo: str, acepta_envio: bool):
    negocio = await mem.crear_negocio(f"Negocio {codigo}", codigo)
    canal_db = await mem.crear_canal_whatsapp(
        nombre=f"Canal {codigo}", phone_number_id=f"4050000{codigo[-2:]}", negocio_id=negocio["id"],
    )
    canal = {
        "id": canal_db["id"], "negocio_id": negocio["id"], "unidad_id": None,
        "phone_number_id": canal_db["phone_number_id"], "modo": "produccion",
    }
    mensaje = MensajeEntrante(
        telefono=telefono, texto="Hola, quiero una terma" if tipo == "text" else "",
        mensaje_id=f"wamid.{codigo}", es_propio=False, tipo=tipo,
        numero_whatsapp_id=canal["phone_number_id"],
    )
    monkeypatch.setattr(app_main, "proveedor", _ProveedorFalso(mensaje, canal, acepta_envio))

    async def respuesta_de_gabi(*args, **kwargs):
        return "¡Hola! ¿Cuántas personas viven en tu hogar?", False, None, None

    async def sin_datos(*args, **kwargs):
        return {}

    monkeypatch.setattr(app_main.servicio_inteligencia, "generar_respuesta", respuesta_de_gabi)
    monkeypatch.setattr(app_main.servicio_inteligencia, "extraer_datos_lead", sin_datos)
    return negocio


async def _respuesta_de_gabi_guardada(negocio_id: str, telefono: str):
    async with mem.async_session() as session:
        resultado = await session.execute(
            select(mem.Mensaje).where(
                mem.Mensaje.negocio_id == negocio_id, mem.Mensaje.telefono == telefono,
                mem.Mensaje.role == "assistant",
            )
        )
        return resultado.scalars().one()


async def test_respuesta_de_texto_rechazada_por_meta_queda_fallida(monkeypatch):
    negocio = await _armar(monkeypatch, "g-fal-01", "51900800001", "text", acepta_envio=False)

    await app_main.webhook_handler(_request())

    guardado = await _respuesta_de_gabi_guardada(negocio["id"], "51900800001")
    assert guardado.estado_envio == "fallido" and guardado.mensaje_id_meta is None


async def test_aviso_de_tipo_no_soportado_rechazado_por_meta_queda_fallido(monkeypatch):
    negocio = await _armar(monkeypatch, "g-fal-02", "51900800002", "sticker", acepta_envio=False)

    await app_main.webhook_handler(_request())

    guardado = await _respuesta_de_gabi_guardada(negocio["id"], "51900800002")
    assert guardado.estado_envio == "fallido"


async def test_respuesta_aceptada_por_meta_no_se_marca_fallida(monkeypatch):
    negocio = await _armar(monkeypatch, "g-fal-03", "51900800003", "text", acepta_envio=True)

    await app_main.webhook_handler(_request())

    guardado = await _respuesta_de_gabi_guardada(negocio["id"], "51900800003")
    assert guardado.estado_envio is None and guardado.mensaje_id_meta == "wamid.OK"


async def test_migracion_marca_fallidas_solo_las_respuestas_de_gabi_a_telefono_vacio():
    import importlib.util
    from pathlib import Path

    from sqlalchemy import text

    negocio = await mem.crear_negocio("Negocio g-fal-04", "g-fal-04")
    nid = negocio["id"]
    vacio_gabi = await mem.guardar_mensaje("", "assistant", "respuesta de Gabi", nid)
    vacio_cliente = await mem.guardar_mensaje("", "user", "mensaje del cliente", nid)
    real_gabi = await mem.guardar_mensaje("51900800004", "assistant", "respuesta a número real", nid)

    ruta = Path(__file__).resolve().parent.parent / "migrations/versions/b8e4c2a6d913_marcar_fallidas_respuestas_a_telefono_vacio.py"
    spec = importlib.util.spec_from_file_location("mig_marcar_fallidas", ruta)
    migracion = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migracion)
    async with mem.async_session() as session:
        await session.execute(text(migracion.SQL_MARCAR_FALLIDAS))
        await session.commit()

    async with mem.async_session() as session:
        estados = {
            m.id: m.estado_envio
            for m in (await session.execute(select(mem.Mensaje))).scalars().all()
        }
    assert estados[vacio_gabi["id"]] == "fallido"
    assert estados[vacio_cliente["id"]] is None
    assert estados[real_gabi["id"]] is None
