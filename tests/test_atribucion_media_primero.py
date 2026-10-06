# tests/test_atribucion_media_primero.py — el `referral` de un anuncio de
# Click-to-WhatsApp se registra también cuando el PRIMER mensaje del cliente es
# un adjunto (foto, audio, documento…). Antes la rama de media salía antes de
# `detectar_y_asignar_campana`, único consumidor del referral: no quedaba el
# AttributionEvent ni la campaña, la ventana gratis de anuncios no se detectaba
# y la analítica subestimaba. Mismo patrón (proveedor falso + webhook completo)
# que tests/test_media_respeta_asignacion.py.

import os

os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")
os.environ.setdefault("WHATSAPP_PROVIDER", "meta")

import pytest
from sqlalchemy import select
from starlette.requests import Request

from agent import campanas
from agent import main as app_main
from agent import memory as mem
from agent import politica_envios
from agent.providers.base import MensajeEntrante

REFERRAL = {
    "source_id": "120299988877",
    "headline": "Terma a gas desde S/419.90",
    "body": "Financiada y sin inicial",
    "ctwa_clid": "clid-AAA",
}


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


async def _armar(
    monkeypatch, codigo: str, telefono: str, tipo: str, referral: dict | None = REFERRAL,
    con_campana: bool = True, texto: str = "", media: dict | None = None,
) -> tuple[dict, _ProveedorFalso]:
    negocio = await mem.crear_negocio(f"Negocio {codigo}", codigo)
    canal_db = await mem.crear_canal_whatsapp(
        nombre=f"Canal {codigo}", phone_number_id=f"4094000{codigo[-2:]}", negocio_id=negocio["id"],
    )
    if con_campana:
        await mem.crear_campana(
            nombre=f"Anuncio terma {codigo}", tipo_deteccion="referral_meta", patron="terma a gas desde s/419.90",
            negocio_id=negocio["id"],
        )
    canal = {
        "id": canal_db["id"], "negocio_id": negocio["id"], "unidad_id": None,
        "phone_number_id": canal_db["phone_number_id"], "modo": "produccion",
    }
    mensaje = MensajeEntrante(
        telefono=telefono, texto=texto, mensaje_id=f"wamid.{codigo}", es_propio=False, tipo=tipo,
        numero_whatsapp_id=canal["phone_number_id"], referral=referral, media=media,
    )
    proveedor = _ProveedorFalso(mensaje, canal)
    monkeypatch.setattr(app_main, "proveedor", proveedor)
    return negocio, proveedor


async def _preparar_lead_con_campana(negocio: dict, telefono: str, campana: str) -> None:
    """Lead que ya existía con campaña de origen (first-touch ya tomado)."""
    canal_id = (await mem.listar_canales_whatsapp(negocio["id"]))[0]["id"]
    await mem.actualizar_lead(telefono, negocio_id=negocio["id"], numero_whatsapp_id="x")
    await mem.resolver_conversation_activa(telefono, negocio["id"], canal_id)
    await mem.asignar_campana_origen(telefono, campana)


async def _mensajes_de(negocio_id: str, telefono: str, role: str) -> list:
    async with mem.async_session() as session:
        resultado = await session.execute(
            select(mem.Mensaje).where(
                mem.Mensaje.negocio_id == negocio_id, mem.Mensaje.telefono == telefono,
                mem.Mensaje.role == role,
            ).order_by(mem.Mensaje.id)
        )
        return resultado.scalars().all()


@pytest.mark.parametrize("tipo,codigo,telefono", [
    ("image", "atr-m-01", "51904100001"),
    ("audio", "atr-m-02", "51904100002"),
])
async def test_adjunto_con_referral_crea_evento_y_asigna_campana(monkeypatch, tipo, codigo, telefono):
    negocio, _proveedor = await _armar(monkeypatch, codigo, telefono, tipo)

    await app_main.webhook_handler(_request())

    eventos = await mem.listar_attribution_events(telefono, negocio_id=negocio["id"])
    assert len(eventos) == 1
    assert eventos[0]["tipo_origen"] == "meta_ads"
    assert eventos[0]["campana_nombre"] == f"Anuncio terma {codigo}"
    assert eventos[0]["source_id"] == REFERRAL["source_id"]
    assert eventos[0]["first_touch"] is True
    lead = await mem.obtener_lead(telefono, negocio_id=negocio["id"])
    assert lead["campana_origen"] == f"Anuncio terma {codigo}"
    # y el mensaje del cliente se guardó como siempre
    assert [m.content for m in await _mensajes_de(negocio["id"], telefono, "user")] == [f"[{tipo}]"]


async def test_adjunto_con_referral_sin_campana_que_coincida_queda_no_resuelto(monkeypatch):
    telefono = "51904100003"
    negocio, _proveedor = await _armar(monkeypatch, "atr-m-03", telefono, "image", con_campana=False)

    await app_main.webhook_handler(_request())

    eventos = await mem.listar_attribution_events(telefono, negocio_id=negocio["id"])
    assert [e["tipo_origen"] for e in eventos] == ["meta_ads_no_resuelto"]
    assert not (await mem.obtener_lead(telefono, negocio_id=negocio["id"])).get("campana_origen")


async def test_documento_con_referral_y_lead_con_campana_registra_evento_sin_cambiar_campana(monkeypatch):
    telefono = "51904100004"
    negocio, _proveedor = await _armar(
        monkeypatch, "atr-m-04", telefono, "document", media={"caption": "mi recibo"},
    )
    await _preparar_lead_con_campana(negocio, telefono, "Campaña original SMS")

    await app_main.webhook_handler(_request())

    eventos = await mem.listar_attribution_events(telefono, negocio_id=negocio["id"])
    assert len(eventos) == 1
    assert eventos[0]["tipo_origen"] == "meta_ads"
    assert eventos[0]["campana_nombre"] == "Anuncio terma atr-m-04"
    assert eventos[0]["first_touch"] is False
    lead = await mem.obtener_lead(telefono, negocio_id=negocio["id"])
    assert lead["campana_origen"] == "Campaña original SMS"  # first-touch intacto


async def test_texto_con_referral_y_lead_con_campana_tambien_deja_evidencia(monkeypatch):
    """El hueco del texto: `if not lead.campana_origen` ignoraba el referral de
    un segundo clic en otro anuncio."""
    telefono = "51904100005"
    negocio, _proveedor = await _armar(monkeypatch, "atr-m-05", telefono, "text", texto="Hola")
    await _preparar_lead_con_campana(negocio, telefono, "Campaña original SMS")
    await mem.asignar_asesor_a_lead(telefono, "asesor1")  # sin IA de por medio

    await app_main.webhook_handler(_request())

    eventos = await mem.listar_attribution_events(telefono, negocio_id=negocio["id"])
    assert [(e["tipo_origen"], e["first_touch"]) for e in eventos] == [("meta_ads", False)]
    assert (await mem.obtener_lead(telefono, negocio_id=negocio["id"]))["campana_origen"] == "Campaña original SMS"


@pytest.mark.parametrize("tipo,codigo,telefono", [
    ("image", "atr-m-06", "51904100006"),
    ("audio", "atr-m-07", "51904100007"),
])
async def test_adjunto_sin_referral_no_crea_nada(monkeypatch, tipo, codigo, telefono):
    negocio, _proveedor = await _armar(monkeypatch, codigo, telefono, tipo, referral=None)

    await app_main.webhook_handler(_request())

    assert await mem.listar_attribution_events(telefono, negocio_id=negocio["id"]) == []
    assert not (await mem.obtener_lead(telefono, negocio_id=negocio["id"])).get("campana_origen")


async def test_reintento_del_mismo_mensaje_no_duplica_el_evento(monkeypatch):
    telefono = "51904100008"
    negocio, proveedor = await _armar(monkeypatch, "atr-m-08", telefono, "image")

    await app_main.webhook_handler(_request())
    # Reintento de Meta del MISMO mensaje, con la marca de procesado liberada
    # (caso real: falló algo tras registrar la atribución y se liberó la marca).
    async with mem.async_session() as session:
        for marca in (await session.execute(select(mem.MensajeProcesado))).scalars().all():
            await session.delete(marca)
        await session.commit()
    await app_main.webhook_handler(_request())

    assert len(await mem.listar_attribution_events(telefono, negocio_id=negocio["id"])) == 1


async def test_mismo_referral_registrado_dos_veces_seguidas_no_duplica_el_evento(monkeypatch):
    """Idempotencia a nivel de atribución (cuando el mensaje se guardó pero el
    reintento llegó con otro wamid o sin la marca de procesado)."""
    telefono = "51904100016"
    negocio, _proveedor = await _armar(monkeypatch, "atr-m-16", telefono, "image")
    canal_id = (await mem.listar_canales_whatsapp(negocio["id"]))[0]["id"]
    await mem.actualizar_lead(telefono, negocio_id=negocio["id"], numero_whatsapp_id="x")
    await mem.resolver_conversation_activa(telefono, negocio["id"], canal_id)

    await campanas.registrar_referral_entrante(telefono, "", REFERRAL, negocio["id"])
    await campanas.registrar_referral_entrante(telefono, "", REFERRAL, negocio["id"])

    assert len(await mem.listar_attribution_events(telefono, negocio_id=negocio["id"])) == 1


async def test_referral_dedupe_no_confunde_un_clic_nuevo(monkeypatch):
    """Otro clic (otro ctwa_clid) en el mismo anuncio sí es evidencia nueva."""
    telefono = "51904100009"
    negocio, proveedor = await _armar(monkeypatch, "atr-m-09", telefono, "image")
    await app_main.webhook_handler(_request())

    proveedor._mensaje = MensajeEntrante(
        telefono=telefono, texto="", mensaje_id="wamid.atr-m-09-b", es_propio=False, tipo="image",
        numero_whatsapp_id=proveedor._canal["phone_number_id"], referral={**REFERRAL, "ctwa_clid": "clid-BBB"},
    )
    await app_main.webhook_handler(_request())

    eventos = await mem.listar_attribution_events(telefono, negocio_id=negocio["id"])
    assert sorted((e["first_touch"], e["ctwa_clid"]) for e in eventos) == [(False, "clid-BBB"), (True, "clid-AAA")]


async def test_error_en_la_atribucion_no_rompe_el_guardado_ni_la_respuesta(monkeypatch):
    telefono = "51904100010"
    negocio, proveedor = await _armar(monkeypatch, "atr-m-10", telefono, "image")

    async def _falla(*args, **kwargs):
        raise RuntimeError("falla simulada de atribución")

    monkeypatch.setattr(campanas, "registrar_attribution_event", _falla)

    await app_main.webhook_handler(_request())

    assert [m.content for m in await _mensajes_de(negocio["id"], telefono, "user")] == ["[image]"]
    assert len(proveedor.enviados) == 1  # el aviso de "no puedo ver fotos" salió igual
    assert await mem.listar_attribution_events(telefono, negocio_id=negocio["id"]) == []


@pytest.mark.parametrize("tipo,codigo,telefono", [
    ("image", "atr-m-11", "51904100011"),
    ("audio", "atr-m-12", "51904100012"),
    ("document", "atr-m-13", "51904100013"),
])
async def test_con_asesor_asignado_el_adjunto_con_referral_no_reactiva_a_gabi(monkeypatch, tipo, codigo, telefono):
    negocio, proveedor = await _armar(monkeypatch, codigo, telefono, tipo)
    await mem.actualizar_lead(telefono, negocio_id=negocio["id"], numero_whatsapp_id="x")
    await mem.resolver_conversation_activa(telefono, negocio["id"], (await mem.listar_canales_whatsapp(negocio["id"]))[0]["id"])
    await mem.asignar_asesor_a_lead(telefono, "asesor1")

    await app_main.webhook_handler(_request())

    assert proveedor.enviados == []
    assert await _mensajes_de(negocio["id"], telefono, "assistant") == []
    assert (await mem.obtener_lead(telefono, negocio_id=negocio["id"]))["asesor_asignado"] == "asesor1"
    # la atribución sí quedó registrada
    assert len(await mem.listar_attribution_events(telefono, negocio_id=negocio["id"])) == 1


async def test_ventana_de_anuncio_abierta_tras_adjunto_con_referral(monkeypatch):
    """Con el evento registrado, la política de envíos reconoce el intervalo
    gratuito del anuncio (nadie le ha respondido todavía: asesor asignado)."""
    telefono = "51904100014"
    negocio, _proveedor = await _armar(monkeypatch, "atr-m-14", telefono, "image")
    await mem.actualizar_lead(telefono, negocio_id=negocio["id"], numero_whatsapp_id="x")
    await mem.resolver_conversation_activa(telefono, negocio["id"], (await mem.listar_canales_whatsapp(negocio["id"]))[0]["id"])
    await mem.asignar_asesor_a_lead(telefono, "asesor1")

    assert await politica_envios._ventana_de_anuncio_abierta(negocio["id"], telefono) is False
    await app_main.webhook_handler(_request())
    assert await politica_envios._ventana_de_anuncio_abierta(negocio["id"], telefono) is True


async def test_reaccion_con_referral_no_registra_atribucion(monkeypatch):
    """Las reacciones y demás tipos sin cambio: salen antes y no tocan la atribución."""
    telefono = "51904100015"
    negocio, proveedor = await _armar(monkeypatch, "atr-m-15", telefono, "reaction", texto="Reaccionó con 👍")

    await app_main.webhook_handler(_request())

    assert await mem.listar_attribution_events(telefono, negocio_id=negocio["id"]) == []
    assert proveedor.enviados == []
