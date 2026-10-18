# tests/test_reingreso_otro_anuncio.py — un cliente con el caso cerrado (sin respuesta / no interesado / no califica)
# que vuelve a escribir desde un anuncio DISTINTO abre una conversación nueva (cierre definitivo automático del caso
# anterior justo antes de DR-4). Tres modos por negocio: apagado, sombra (solo mide) y activo.

import os

os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")
os.environ.setdefault("WHATSAPP_PROVIDER", "meta")

import json

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from starlette.requests import Request

from agent import dashboard
from agent import main as app_main
from agent import memory as mem
from agent.providers.base import MensajeEntrante


async def _negocio(codigo: str):
    negocio = await mem.crear_negocio(f"Negocio {codigo}", codigo)
    canal = await mem.crear_canal_whatsapp(
        nombre=f"Canal {codigo}", phone_number_id=f"4095000{codigo[-2:]}", negocio_id=negocio["id"],
    )
    return negocio, canal


async def _caso_con_anuncio(negocio, canal, telefono, source_id="AD-A", resultado=None, asesor=None):
    """Conversación activa que entró por `source_id`, con `resultado` en el lead."""
    await mem.actualizar_lead(telefono, negocio_id=negocio["id"], numero_whatsapp_id="x")
    await mem.resolver_conversation_activa(telefono, negocio["id"], canal["id"])
    await mem.registrar_attribution_event(
        telefono, "meta_ads_no_resuelto", referral={"source_id": source_id, "headline": "h", "body": "b"},
    )
    if resultado:
        await mem.actualizar_lead(telefono, negocio_id=negocio["id"], resultado=resultado)
    if asesor:
        await mem.asignar_asesor_a_lead(telefono, asesor)


REF_B = {"source_id": "AD-B", "headline": "otro", "body": "otro"}


@pytest.mark.parametrize("resultado", ["sin_respuesta", "no_interesado", "no_califica"])
async def test_decide_otro_anuncio_cuando_el_caso_ya_tiene_cierre_comercial(resultado):
    negocio, canal = await _negocio("rea-01")
    await _caso_con_anuncio(negocio, canal, "51902200101", resultado=resultado)

    decision = await mem.evaluar_reingreso_por_anuncio("51902200101", negocio["id"], REF_B)

    assert decision["tipo"] == "otro_anuncio" and decision["anuncios_previos"] == ["AD-A"]
    assert decision["resultado"] == resultado


async def test_el_mismo_anuncio_solo_se_mide():
    negocio, canal = await _negocio("rea-02")
    await _caso_con_anuncio(negocio, canal, "51902200102", resultado="sin_respuesta")
    decision = await mem.evaluar_reingreso_por_anuncio("51902200102", negocio["id"], {"source_id": "AD-A"})
    assert decision["tipo"] == "mismo_anuncio"


@pytest.mark.parametrize("resultado", [None, "agendado", "postventa", "vendido", "consulta_atc", "otro", "cartera_fnb"])
async def test_no_decide_con_casos_abiertos_ventas_ni_atc(resultado):
    negocio, canal = await _negocio("rea-03")
    await _caso_con_anuncio(negocio, canal, "51902200103", resultado=resultado)
    assert await mem.evaluar_reingreso_por_anuncio("51902200103", negocio["id"], REF_B) is None


async def test_no_decide_sin_anuncio_sin_contacto_ni_con_cierre_definitivo():
    negocio, canal = await _negocio("rea-04")
    await _caso_con_anuncio(negocio, canal, "51902200104", resultado="no_interesado")
    assert await mem.evaluar_reingreso_por_anuncio("51902200104", negocio["id"], None) is None
    assert await mem.evaluar_reingreso_por_anuncio("51902200104", negocio["id"], {"source_id": ""}) is None
    assert await mem.evaluar_reingreso_por_anuncio("51999999999", negocio["id"], REF_B) is None
    await mem.cerrar_lead_definitivamente("51902200104", negocio["id"], autor=None)
    assert await mem.evaluar_reingreso_por_anuncio("51902200104", negocio["id"], REF_B) is None  # DR-4 ya lo maneja


async def test_conversacion_que_no_entro_por_anuncio_tambien_cuenta():
    negocio, canal = await _negocio("rea-05")
    await mem.actualizar_lead("51902200105", negocio_id=negocio["id"], numero_whatsapp_id="x")
    await mem.resolver_conversation_activa("51902200105", negocio["id"], canal["id"])
    await mem.actualizar_lead("51902200105", negocio_id=negocio["id"], resultado="sin_respuesta")  # entró por SMS/directo
    decision = await mem.evaluar_reingreso_por_anuncio("51902200105", negocio["id"], REF_B)
    assert decision["tipo"] == "otro_anuncio" and decision["anuncios_previos"] == []


async def test_los_tres_modos():
    negocio, canal = await _negocio("rea-06")
    await _caso_con_anuncio(negocio, canal, "51902200106", resultado="no_interesado")
    assert await mem.obtener_modo_reingreso_anuncio(negocio["id"]) == "sombra"  # nace en sombra

    await mem.guardar_modo_reingreso_anuncio(negocio["id"], "apagado")
    assert await mem.procesar_reingreso_por_anuncio("51902200106", negocio["id"], REF_B) is None
    assert (await mem.resumen_reingreso_anuncio(negocio["id"]))["total"] == 0

    await mem.guardar_modo_reingreso_anuncio(negocio["id"], "sombra")
    await mem.procesar_reingreso_por_anuncio("51902200106", negocio["id"], REF_B)
    await mem.procesar_reingreso_por_anuncio("51902200106", negocio["id"], REF_B)  # una sola vez por conversación y anuncio
    resumen = await mem.resumen_reingreso_anuncio(negocio["id"])
    assert resumen["total"] == 1 and resumen["por_tipo"] == {"sombra_otro_anuncio": 1}
    assert resumen["ultimos"][0]["telefono"] == "…0106"
    lead = await mem.obtener_lead("51902200106", negocio_id=negocio["id"])
    assert lead["cerrado_definitivamente_en"] is None  # la sombra no toca nada

    await mem.guardar_modo_reingreso_anuncio(negocio["id"], "activo")
    decision = await mem.procesar_reingreso_por_anuncio("51902200106", negocio["id"], REF_B)
    assert decision["aplicado"] is True
    lead = await mem.obtener_lead("51902200106", negocio_id=negocio["id"])
    assert lead["cerrado_definitivamente_en"] is not None

    with pytest.raises(ValueError):
        await mem.guardar_modo_reingreso_anuncio(negocio["id"], "inventado")


async def test_en_modo_activo_el_mismo_anuncio_no_actua():
    negocio, canal = await _negocio("rea-07")
    await _caso_con_anuncio(negocio, canal, "51902200107", resultado="sin_respuesta")
    await mem.guardar_modo_reingreso_anuncio(negocio["id"], "activo")
    decision = await mem.procesar_reingreso_por_anuncio("51902200107", negocio["id"], {"source_id": "AD-A"})
    assert decision["tipo"] == "mismo_anuncio" and "aplicado" not in decision
    assert (await mem.obtener_lead("51902200107", negocio_id=negocio["id"]))["cerrado_definitivamente_en"] is None


async def test_endpoints_modo_y_resumen():
    negocio, _ = await _negocio("rea-08")
    admin = {"negocio_id": negocio["id"], "rol": "admin", "username": "jesus"}

    class _Req:
        def __init__(self, d):
            self._d = d

        async def json(self):
            return self._d

    assert json.loads((await dashboard.anuncios_reingreso_json(usuario=admin)).body)["modo"] == "sombra"
    ok = json.loads((await dashboard.anuncios_reingreso_modo_json(_Req({"modo": "activo"}), usuario=admin, _csrf=None)).body)
    assert ok == {"ok": True, "modo": "activo"}
    assert json.loads((await dashboard.anuncios_reingreso_json(usuario=admin)).body)["modo"] == "activo"
    with pytest.raises(HTTPException) as e:
        await dashboard.anuncios_reingreso_modo_json(_Req({"modo": "x"}), usuario=admin, _csrf=None)
    assert e.value.status_code == 400


# ── Caso completo por el webhook ─────────────────────────────────────────────

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
    def __init__(self, mensaje, canal):
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


async def _webhook_con_adjunto_y_anuncio_b(monkeypatch, negocio, canal_db, telefono):
    canal = {
        "id": canal_db["id"], "negocio_id": negocio["id"], "unidad_id": None,
        "phone_number_id": canal_db["phone_number_id"], "modo": "produccion",
    }
    mensaje = MensajeEntrante(
        telefono=telefono, texto="", mensaje_id=f"wamid.{telefono}", es_propio=False, tipo="image",
        numero_whatsapp_id=canal["phone_number_id"], referral=REF_B, media=None,
    )
    monkeypatch.setattr(app_main, "proveedor", _ProveedorFalso(mensaje, canal))
    await app_main.webhook_handler(_request())


async def _conversaciones(negocio_id, telefono):
    async with mem.async_session() as session:
        contact = await mem._obtener_contact(session, negocio_id, telefono)
        filas = (await session.execute(
            select(mem.Conversation).where(mem.Conversation.contact_id == contact.id).order_by(mem.Conversation.creado)
        )).scalars().all()
        return [(c.id, c.estado, c.campana_origen_id, c.asesor_asignado_id) for c in filas]


async def test_webhook_activo_abre_conversacion_nueva_con_la_campana_del_anuncio_nuevo(monkeypatch):
    negocio, canal = await _negocio("rea-09")
    telefono = "51902200109"
    campana_a = await mem.crear_campana_de_anuncio("Campaña A", "AD-A", negocio["id"])
    campana_b = await mem.crear_campana_de_anuncio("Campaña B", "AD-B", negocio["id"])
    await _caso_con_anuncio(negocio, canal, telefono, "AD-A", resultado="no_interesado", asesor="asesor1")
    await mem.asignar_campana_origen(telefono, "Campaña A")
    await mem.guardar_modo_reingreso_anuncio(negocio["id"], "activo")
    antes = await _conversaciones(negocio["id"], telefono)

    await _webhook_con_adjunto_y_anuncio_b(monkeypatch, negocio, canal, telefono)

    despues = await _conversaciones(negocio["id"], telefono)
    assert len(antes) == 1 and len(despues) == 2
    assert despues[0][1] == "cerrada" and despues[1][1] == "activa"
    assert despues[0][2] == campana_a["id"] and despues[1][2] == campana_b["id"]  # cada conversación, su campaña
    assert despues[1][3] is None  # la asesora anterior se libera: el caso nuevo se reparte como lead nuevo
    lead = await mem.obtener_lead(telefono, negocio_id=negocio["id"])
    assert lead["campana_origen"] == "Campaña A" and lead["resultado"] is None  # primer contacto intacto, resultado limpio
    assert not lead["asesor_asignado"]
    resumen = await mem.resumen_reingreso_anuncio(negocio["id"])
    assert resumen["por_tipo"] == {"aplicado_otro_anuncio": 1}


async def test_webhook_en_sombra_no_cambia_nada_pero_deja_rastro(monkeypatch):
    negocio, canal = await _negocio("rea-10")
    telefono = "51902200110"
    await mem.crear_campana_de_anuncio("Campaña B", "AD-B", negocio["id"])
    await _caso_con_anuncio(negocio, canal, telefono, "AD-A", resultado="sin_respuesta", asesor="asesor1")

    await _webhook_con_adjunto_y_anuncio_b(monkeypatch, negocio, canal, telefono)

    assert len(await _conversaciones(negocio["id"], telefono)) == 1  # sigue la misma conversación
    resumen = await mem.resumen_reingreso_anuncio(negocio["id"])
    assert resumen["por_tipo"] == {"sombra_otro_anuncio": 1} and resumen["con_asesor"] == 1


async def test_webhook_activo_con_caso_abierto_no_parte_la_conversacion(monkeypatch):
    negocio, canal = await _negocio("rea-11")
    telefono = "51902200111"
    await _caso_con_anuncio(negocio, canal, telefono, "AD-A", resultado=None)  # sigue abierto
    await mem.guardar_modo_reingreso_anuncio(negocio["id"], "activo")

    await _webhook_con_adjunto_y_anuncio_b(monkeypatch, negocio, canal, telefono)

    assert len(await _conversaciones(negocio["id"], telefono)) == 1
    assert (await mem.resumen_reingreso_anuncio(negocio["id"]))["total"] == 0


async def test_una_falla_del_reingreso_nunca_frena_el_mensaje(monkeypatch):
    negocio, canal = await _negocio("rea-12")
    telefono = "51902200112"
    await _caso_con_anuncio(negocio, canal, telefono, "AD-A", resultado="no_interesado")

    async def explota(*a, **k):
        raise RuntimeError("falla simulada")

    monkeypatch.setattr(app_main, "procesar_reingreso_por_anuncio", explota)
    await _webhook_con_adjunto_y_anuncio_b(monkeypatch, negocio, canal, telefono)

    async with mem.async_session() as session:
        mensajes = (await session.execute(
            select(mem.Mensaje).where(mem.Mensaje.negocio_id == negocio["id"], mem.Mensaje.telefono == telefono, mem.Mensaje.role == "user")
        )).scalars().all()
    assert len(mensajes) == 1  # el mensaje se guardó igual
