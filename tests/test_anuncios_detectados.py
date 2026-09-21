# tests/test_anuncios_detectados.py — vista "Anuncios detectados": los anuncios de
# Meta que trajeron leads (evidencia de Attribution V2), a qué campaña
# pertenecen hoy y la asignación posterior cuando la campaña no existía.

import json

import pytest
from fastapi import HTTPException

from agent import dashboard, memory as mem
from agent.campanas import detectar_y_asignar_campana


class _RequestFalso:
    def __init__(self, payload: dict):
        self._payload = payload

    async def json(self):
        return self._payload


def _cuerpo(respuesta) -> dict:
    return json.loads(respuesta.body)


async def _negocio(codigo: str):
    negocio = await mem.crear_negocio(f"Negocio {codigo}", codigo)
    canal = await mem.crear_canal_whatsapp(
        nombre=f"Canal {codigo}", phone_number_id=f"4080000{codigo[-2:]}", negocio_id=negocio["id"],
    )
    return negocio, canal


async def _lead_de_anuncio(negocio, canal, telefono: str, source_id: str, headline: str = "Terma a gas"):
    await mem.actualizar_lead(telefono, negocio_id=negocio["id"], numero_whatsapp_id="x")
    await mem.resolver_conversation_activa(telefono, negocio["id"], canal["id"])
    await mem.registrar_attribution_event(
        telefono, "meta_ads_no_resuelto",
        referral={"source_id": source_id, "headline": headline, "body": "Cuerpo del anuncio", "source_url": "https://fb.me/x"},
    )


async def _totales(negocio_id: str) -> dict:
    return {f["campana"]: f["total"] for f in await mem.contar_opportunities_por_campana(negocio_id)}


async def test_lista_agrupa_por_anuncio_y_muestra_la_campana_actual():
    negocio, canal = await _negocio("g-anu-01")
    julio = await mem.crear_campana("Meta Terma Julio", "referral_meta", "terma", negocio_id=negocio["id"])
    await _lead_de_anuncio(negocio, canal, "51901100001", "AD1")
    await _lead_de_anuncio(negocio, canal, "51901100002", "AD1")
    await _lead_de_anuncio(negocio, canal, "51901100003", "AD2", headline="Secadora")
    await mem.asignar_campana_origen("51901100001", julio["nombre"])

    anuncios = {a["source_id"]: a for a in await mem.listar_anuncios_detectados(negocio["id"])}

    assert anuncios["AD1"]["leads"] == 2 and anuncios["AD1"]["conversaciones"] == 2
    assert anuncios["AD1"]["sin_campana"] == 1
    assert anuncios["AD1"]["campanas"] == [{"campana": "Meta Terma Julio", "conversaciones": 1}]
    assert anuncios["AD1"]["headline"] == "Terma a gas" and anuncios["AD1"]["url"] == "https://fb.me/x"
    assert anuncios["AD2"]["sin_campana"] == 1 and anuncios["AD2"]["campanas"] == []


async def test_asignar_reemplaza_la_campana_y_actualiza_la_analitica():
    negocio, canal = await _negocio("g-anu-02")
    julio = await mem.crear_campana("Meta Terma Julio", "referral_meta", "terma", negocio_id=negocio["id"])
    setiembre = await mem.crear_campana("Meta Terma Setiembre", "referral_meta", "ad1", negocio_id=negocio["id"])
    await _lead_de_anuncio(negocio, canal, "51901100011", "AD1")
    await _lead_de_anuncio(negocio, canal, "51901100012", "AD1")
    await _lead_de_anuncio(negocio, canal, "51901100013", "AD2")
    await mem.asignar_campana_origen("51901100011", julio["nombre"])

    resumen = await mem.asignar_anuncio_a_campana(negocio["id"], "AD1", setiembre["id"], autor="jesus")

    assert resumen == {"conversaciones": 2, "leads": 2}
    totales = await _totales(negocio["id"])
    assert totales["Meta Terma Setiembre"] == 2 and totales["Meta Terma Julio"] == 0
    assert (await mem.obtener_lead("51901100011", negocio_id=negocio["id"]))["campana_origen"] == "Meta Terma Setiembre"
    ad2 = next(a for a in await mem.listar_anuncios_detectados(negocio["id"]) if a["source_id"] == "AD2")
    assert ad2["sin_campana"] == 1


async def test_asignar_no_toca_otro_negocio_ni_acepta_campanas_ajenas():
    negocio_a, canal_a = await _negocio("g-anu-03")
    negocio_b, canal_b = await _negocio("g-anu-04")
    campana_a = await mem.crear_campana("Campaña A", "referral_meta", "ad1", negocio_id=negocio_a["id"])
    campana_b = await mem.crear_campana("Campaña B", "referral_meta", "zzz", negocio_id=negocio_b["id"])
    await _lead_de_anuncio(negocio_a, canal_a, "51901100021", "AD1")
    await _lead_de_anuncio(negocio_b, canal_b, "51901100022", "AD1")

    await mem.asignar_anuncio_a_campana(negocio_a["id"], "AD1", campana_a["id"])

    assert (await _totales(negocio_a["id"]))["Campaña A"] == 1
    assert (await _totales(negocio_b["id"]))["Campaña B"] == 0
    with pytest.raises(LookupError):
        await mem.asignar_anuncio_a_campana(negocio_a["id"], "AD1", campana_b["id"])
    with pytest.raises(LookupError):
        await mem.asignar_anuncio_a_campana(negocio_a["id"], "NO-EXISTE", campana_a["id"])


async def test_endpoint_crea_campana_por_id_de_anuncio_y_asigna():
    negocio, canal = await _negocio("g-anu-05")
    await _lead_de_anuncio(negocio, canal, "51901100031", "AD9")
    usuario = {"negocio_id": negocio["id"], "rol": "admin", "username": "jesus"}

    respuesta = await dashboard.asignar_anuncio_json(
        _RequestFalso({"source_id": "AD9", "nueva_campana": {"nombre": "Meta Terma Setiembre"}}),
        usuario=usuario, _csrf=None,
    )

    cuerpo = _cuerpo(respuesta)
    assert cuerpo["ok"] is True and cuerpo["asignados"] == {"conversaciones": 1, "leads": 1}
    campana = await mem.obtener_campana(cuerpo["campana_id"])
    assert campana["tipo_deteccion"] == "referral_meta" and campana["patron"] == "ad9"
    assert (await _totales(negocio["id"]))["Meta Terma Setiembre"] == 1


async def test_endpoint_valida_la_entrada():
    negocio, canal = await _negocio("g-anu-06")
    existente = await mem.crear_campana("Ya existe", "referral_meta", "x", negocio_id=negocio["id"])
    await _lead_de_anuncio(negocio, canal, "51901100041", "AD1")
    usuario = {"negocio_id": negocio["id"], "rol": "admin"}

    casos = [
        ({"source_id": "AD1"}, 400),
        ({"source_id": "AD1", "campana_id": existente["id"], "nueva_campana": {"nombre": "Otra"}}, 400),
        ({"source_id": "AD1", "nueva_campana": {"nombre": "ya existe"}}, 400),
        ({"source_id": "NO-EXISTE", "campana_id": existente["id"]}, 404),
        ({"campana_id": existente["id"]}, 400),
    ]
    for payload, esperado in casos:
        with pytest.raises(HTTPException) as e:
            await dashboard.asignar_anuncio_json(_RequestFalso(payload), usuario=usuario, _csrf=None)
        assert e.value.status_code == esperado, payload


async def test_deteccion_prefiere_la_campana_mas_especifica():
    negocio, canal = await _negocio("g-anu-07")
    await mem.crear_campana("Meta Terma Julio", "referral_meta", "terma", negocio_id=negocio["id"])
    await mem.crear_campana("Meta Terma Setiembre", "referral_meta", "120245001", negocio_id=negocio["id"])
    await mem.actualizar_lead("51901100051", negocio_id=negocio["id"], numero_whatsapp_id="x")
    await mem.resolver_conversation_activa("51901100051", negocio["id"], canal["id"])

    campana = await detectar_y_asignar_campana(
        "51901100051", "Hola", {"source_id": "120245001", "headline": "Terma a gas", "body": ""}, negocio["id"],
    )

    assert campana["nombre"] == "Meta Terma Setiembre"


async def test_el_endpoint_de_lista_devuelve_fechas_y_permiso():
    negocio, canal = await _negocio("g-anu-08")
    await _lead_de_anuncio(negocio, canal, "51901100061", "AD1")

    supervisor = _cuerpo(await dashboard.anuncios_json(usuario={"negocio_id": negocio["id"], "rol": "supervisor"}))
    admin = _cuerpo(await dashboard.anuncios_json(usuario={"negocio_id": negocio["id"], "rol": "admin"}))

    assert supervisor["puede_gestionar"] is False and admin["puede_gestionar"] is True
    assert isinstance(admin["anuncios"][0]["ultimo"], str) and admin["anuncios"][0]["source_id"] == "AD1"


async def _lead_con_url(negocio, canal, telefono: str, source_id: str, source_url):
    await mem.actualizar_lead(telefono, negocio_id=negocio["id"], numero_whatsapp_id="x")
    await mem.resolver_conversation_activa(telefono, negocio["id"], canal["id"])
    referral = {"source_id": source_id, "headline": "H", "body": "B"}
    if source_url is not None:
        referral["source_url"] = source_url
    await mem.registrar_attribution_event(telefono, "meta_ads_no_resuelto", referral=referral)


async def test_la_lista_cuenta_los_leads_por_red_social():
    negocio, canal = await _negocio("g-anu-09")
    await _lead_con_url(negocio, canal, "51901100071", "MIX", "https://fb.me/abc123")
    await _lead_con_url(negocio, canal, "51901100072", "MIX", "https://www.instagram.com/p/xyz/")
    await _lead_con_url(negocio, canal, "51901100073", "MIX", "https://l.instagram.com/?u=1")
    await _lead_con_url(negocio, canal, "51901100074", "MIX", "https://www.facebook.com/ads/x")
    await _lead_con_url(negocio, canal, "51901100075", "MIX", None)
    await _lead_con_url(negocio, canal, "51901100076", "MIX", "https://otro-sitio.com/a")
    await _lead_con_url(negocio, canal, "51901100077", "SOLO-IG", "https://www.instagram.com/p/solo/")

    anuncios = {a["source_id"]: a for a in await mem.listar_anuncios_detectados(negocio["id"])}

    assert anuncios["MIX"]["redes"] == {"facebook": 2, "instagram": 2, "otra": 2}
    assert anuncios["SOLO-IG"]["redes"] == {"facebook": 0, "instagram": 1, "otra": 0}


def test_dominios_parecidos_no_se_confunden_con_instagram_o_facebook():
    assert mem._red_de_referral({"source_url": "https://notinstagram.com/p/1"}) == "otra"
    assert mem._red_de_referral({"source_url": "https://instagram.com.evil.io/p/1"}) == "otra"
    assert mem._red_de_referral({"source_url": "no es una url"}) == "otra"
    assert mem._red_de_referral(None) == "otra"
