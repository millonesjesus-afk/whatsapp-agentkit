# tests/test_analitica_por_red.py — la tabla de campañas de Analítica desglosa
# cada campaña por red (Facebook / Instagram / otra) y se puede filtrar por red.

import json

import pytest
from fastapi import HTTPException

from agent import dashboard, memory as mem


def _cuerpo(respuesta) -> dict:
    return json.loads(respuesta.body)


async def _lead(negocio, canal, telefono: str, campana: str, source_url: str | None):
    await mem.actualizar_lead(telefono, negocio_id=negocio["id"], numero_whatsapp_id="x")
    conversation, opportunity = await mem.resolver_conversation_activa(telefono, negocio["id"], canal["id"])
    if source_url is not None:
        referral = {"source_id": "AD-" + telefono[-2:], "headline": "H", "body": "B", "source_url": source_url}
        await mem.registrar_attribution_event(telefono, "meta_ads", referral=referral, campana_nombre=campana)
    await mem.asignar_campana_origen(telefono, campana)
    return opportunity


async def _escenario(codigo: str):
    negocio = await mem.crear_negocio(f"Negocio {codigo}", codigo)
    canal = await mem.crear_canal_whatsapp(
        nombre=f"Canal {codigo}", phone_number_id=f"4090000{codigo[-2:]}", negocio_id=negocio["id"],
    )
    await mem.crear_campana("Meta Terma", "referral_meta", "terma", negocio_id=negocio["id"])
    await mem.crear_campana("SMS Terma", "texto_saludo", "terma rheem", negocio_id=negocio["id"])
    fb1 = await _lead(negocio, canal, "51902000001", "Meta Terma", "https://fb.me/a")
    await _lead(negocio, canal, "51902000002", "Meta Terma", "https://fb.me/b")
    ig = await _lead(negocio, canal, "51902000003", "Meta Terma", "https://www.instagram.com/p/c/")
    await _lead(negocio, canal, "51902000004", "SMS Terma", None)
    for opp in (fb1, ig):
        assert await mem.cerrar_opportunity_con_venta(
            opp.id, opp.version, [{"producto": "Terma", "precio": "100", "marca": "M", "proveedor": "P"}],
            {"resultado": "vendido"},
        )
    return negocio


async def _por_nombre(negocio_id: str, **filtros) -> dict:
    return {f["campana"]: f for f in await mem.contar_opportunities_por_campana(negocio_id, **filtros)}


async def test_cada_campana_trae_su_desglose_por_red():
    negocio = await _escenario("g-red-01")

    filas = await _por_nombre(negocio["id"])

    assert filas["Meta Terma"]["redes"] == {"facebook": 2, "instagram": 1, "otra": 0}
    assert filas["SMS Terma"]["redes"] == {"facebook": 0, "instagram": 0, "otra": 1}
    assert filas["Meta Terma"]["total"] == 3 and filas["Meta Terma"]["vendidos"] == 2


async def test_el_filtro_de_red_acota_totales_y_ventas():
    negocio = await _escenario("g-red-02")

    instagram = await _por_nombre(negocio["id"], red="instagram")
    facebook = await _por_nombre(negocio["id"], red="facebook")
    otra = await _por_nombre(negocio["id"], red="otra")

    assert (instagram["Meta Terma"]["total"], instagram["Meta Terma"]["vendidos"]) == (1, 1)
    assert instagram["SMS Terma"]["total"] == 0
    assert instagram["Meta Terma"]["redes"] == {"facebook": 0, "instagram": 1, "otra": 0}
    assert (facebook["Meta Terma"]["total"], facebook["Meta Terma"]["vendidos"]) == (2, 1)
    assert (otra["SMS Terma"]["total"], otra["Meta Terma"]["total"]) == (1, 0)


async def test_una_red_sin_conversaciones_deja_todo_en_cero():
    negocio = await mem.crear_negocio("Negocio g-red-03", "g-red-03")
    await mem.crear_campana("Sola", "referral_meta", "x", negocio_id=negocio["id"])

    filas = await _por_nombre(negocio["id"], red="instagram")

    assert filas["Sola"]["total"] == 0 and filas["Sola"]["redes"] == {"facebook": 0, "instagram": 0, "otra": 0}


async def test_el_endpoint_filtra_solo_la_tabla_de_campanas_y_valida_la_red():
    negocio = await _escenario("g-red-04")
    admin = {"negocio_id": negocio["id"], "rol": "admin", "username": "admin1"}

    todas = _cuerpo(await dashboard.analitica_json(usuario=admin))
    instagram = _cuerpo(await dashboard.analitica_json(usuario=admin, red="instagram"))

    por_nombre = lambda c: {x["campana"]: x for x in c["campanas"]}
    assert por_nombre(todas)["Meta Terma"]["total"] == 3
    assert por_nombre(instagram)["Meta Terma"]["total"] == 1
    assert instagram["embudo"] == todas["embudo"] and instagram["flujo_periodo"] == todas["flujo_periodo"]
    with pytest.raises(HTTPException) as e:
        await dashboard.analitica_json(usuario=admin, red="tiktok")
    assert e.value.status_code == 400
