# tests/test_analitica_atribucion_sin_campana.py — complemento de la tabla de
# Campañas en Analítica: conversaciones SIN campana_origen_id, separadas entre
# anuncios de Meta detectados-pero-no-asignados y leads genuinamente orgánicos.

import json
from datetime import datetime

import pytest
from fastapi import HTTPException

from agent import dashboard, memory as mem

_INICIO, _FIN = datetime(2000, 1, 1), datetime(2100, 1, 1)


def _cuerpo(respuesta) -> dict:
    return json.loads(respuesta.body)


async def _lead_con_anuncio(negocio, canal, telefono: str, source_id: str, source_url: str, headline: str | None = "H"):
    """Conversación con evidencia de anuncio de Meta que NINGUNA campaña
    resolvió — nunca se llama a `asignar_campana_origen`, mismo camino que
    `campanas.detectar_y_asignar_campana` toma cuando el referral no matchea
    ninguna campaña configurada. `headline=None` simula el caso real en que
    Meta no manda ese campo (la clave ni aparece en el referral)."""
    await mem.actualizar_lead(telefono, negocio_id=negocio["id"], numero_whatsapp_id="x")
    conversation, opportunity = await mem.resolver_conversation_activa(telefono, negocio["id"], canal["id"])
    referral = {"source_id": source_id, "body": "cuerpo", "source_url": source_url}
    if headline is not None:
        referral["headline"] = headline
    await mem.registrar_attribution_event(telefono, "meta_ads_no_resuelto", referral=referral)
    return conversation, opportunity


async def _lead_organico(negocio, canal, telefono: str):
    """Conversación sin ningún rastro de Meta Ads y sin campaña — WhatsApp
    directo de toda la vida."""
    await mem.actualizar_lead(telefono, negocio_id=negocio["id"], numero_whatsapp_id="x")
    return await mem.resolver_conversation_activa(telefono, negocio["id"], canal["id"])


async def _lead_con_campana(negocio, canal, telefono: str, campana: str):
    """Conversación YA asignada a una campaña real — control negativo: no
    debe aparecer en `atribucion_sin_campana`."""
    await mem.actualizar_lead(telefono, negocio_id=negocio["id"], numero_whatsapp_id="x")
    conversation, opportunity = await mem.resolver_conversation_activa(telefono, negocio["id"], canal["id"])
    await mem.asignar_campana_origen(telefono, campana)
    return conversation, opportunity


async def _escenario(codigo: str):
    negocio = await mem.crear_negocio(f"Negocio {codigo}", codigo)
    canal = await mem.crear_canal_whatsapp(
        nombre=f"Canal {codigo}", phone_number_id=f"4091000{codigo[-2:]}", negocio_id=negocio["id"],
    )
    await mem.crear_campana("Meta Terma", "referral_meta", "terma", negocio_id=negocio["id"])

    # AD-1: dos conversaciones, una Facebook y una Instagram — se agrupan
    # bajo el mismo source_id.
    await _lead_con_anuncio(negocio, canal, "51903000001", "AD-1", "https://fb.me/x", headline="Terma en oferta")
    _, opp_ad1_ig = await _lead_con_anuncio(negocio, canal, "51903000002", "AD-1", "https://www.instagram.com/p/y/")
    # AD-2: un anuncio distinto, sin headline (para probar el fallback).
    await _lead_con_anuncio(negocio, canal, "51903000003", "AD-2", "https://fb.me/z", headline=None)
    # Orgánico puro.
    await _lead_organico(negocio, canal, "51903000004")
    # Control: ya tiene campaña real — no debe aparecer acá.
    await _lead_con_campana(negocio, canal, "51903000005", "Meta Terma")

    assert await mem.cerrar_opportunity_con_venta(
        opp_ad1_ig.id, opp_ad1_ig.version,
        [{"producto": "Terma", "precio": "100", "marca": "M", "proveedor": "P"}],
        {"resultado": "vendido"},
    )
    return negocio


async def _sin_campana(negocio_id: str, **filtros) -> dict:
    inicio = filtros.pop("desde", None) or _INICIO
    fin = filtros.pop("hasta", None) or _FIN
    return await mem.listar_atribucion_sin_campana_periodo(negocio_id, desde=inicio, hasta=fin, **filtros)


async def test_agrupa_anuncios_sin_asignar_por_source_id():
    negocio = await _escenario("g-org-01")

    resultado = await _sin_campana(negocio["id"])
    por_source_id = {a["source_id"]: a for a in resultado["anuncios"]}

    assert set(por_source_id) == {"AD-1", "AD-2"}
    assert por_source_id["AD-1"]["headline"] == "Terma en oferta"
    assert por_source_id["AD-1"]["total"] == 2 and por_source_id["AD-1"]["vendidos"] == 1
    assert por_source_id["AD-1"]["redes"] == {"facebook": 1, "instagram": 1, "otra": 0}
    assert por_source_id["AD-2"]["headline"] is None
    assert por_source_id["AD-2"]["total"] == 1 and por_source_id["AD-2"]["redes"] == {"facebook": 1, "instagram": 0, "otra": 0}


async def test_organico_solo_cuenta_lo_que_no_tiene_ningun_rastro_de_anuncio():
    negocio = await _escenario("g-org-02")

    resultado = await _sin_campana(negocio["id"])

    assert resultado["organico"] == {"total": 1, "vendidos": 0, "redes": {"facebook": 0, "instagram": 0, "otra": 1}}


async def test_conversacion_ya_asignada_a_campana_no_aparece_aca():
    negocio = await _escenario("g-org-03")

    resultado = await _sin_campana(negocio["id"])

    total_conversaciones_sin_campana = sum(a["total"] for a in resultado["anuncios"]) + resultado["organico"]["total"]
    assert total_conversaciones_sin_campana == 4  # AD-1 (2) + AD-2 (1) + orgánico (1); la 5ta ya tiene campaña


async def test_filtro_de_red_acota_cada_grupo_por_su_propia_red():
    negocio = await _escenario("g-org-04")

    instagram = await _sin_campana(negocio["id"], red="instagram")
    facebook = await _sin_campana(negocio["id"], red="facebook")
    otra = await _sin_campana(negocio["id"], red="otra")

    por_source_id_ig = {a["source_id"]: a for a in instagram["anuncios"]}
    assert por_source_id_ig["AD-1"]["total"] == 1 and por_source_id_ig["AD-1"]["redes"]["instagram"] == 1
    assert "AD-2" not in por_source_id_ig  # AD-2 es 100% Facebook
    assert instagram["organico"]["total"] == 0  # lo orgánico siempre es "otra"

    por_source_id_fb = {a["source_id"]: a for a in facebook["anuncios"]}
    assert por_source_id_fb["AD-1"]["total"] == 1 and por_source_id_fb["AD-2"]["total"] == 1
    assert facebook["organico"]["total"] == 0

    assert otra["anuncios"] == [] and otra["organico"]["total"] == 1


async def test_universo_completo_no_se_solapa_con_las_campanas_reales():
    """Invariante: campañas reales + anuncios sin asignar + orgánico cubren
    el 100% de las conversaciones del período, sin doble conteo."""
    negocio = await _escenario("g-org-05")

    campanas = await mem.contar_opportunities_por_campana(negocio["id"], desde=_INICIO, hasta=_FIN)
    sin_campana = await mem.listar_atribucion_sin_campana_periodo(negocio["id"], desde=_INICIO, hasta=_FIN)

    total_campanas = sum(c["total"] for c in campanas)
    total_sin_campana = sum(a["total"] for a in sin_campana["anuncios"]) + sin_campana["organico"]["total"]
    assert total_campanas == 1  # el lead ya asignado a "Meta Terma"
    assert total_sin_campana == 4
    assert total_campanas + total_sin_campana == 5  # las 5 conversaciones del escenario


async def test_endpoint_analitica_incluye_atribucion_sin_campana():
    negocio = await _escenario("g-org-06")
    admin = {"negocio_id": negocio["id"], "rol": "admin", "username": "admin1"}

    cuerpo = _cuerpo(await dashboard.analitica_json(usuario=admin))

    assert "atribucion_sin_campana" in cuerpo
    assert {a["source_id"] for a in cuerpo["atribucion_sin_campana"]["anuncios"]} == {"AD-1", "AD-2"}
    assert cuerpo["atribucion_sin_campana"]["organico"]["total"] == 1

    with pytest.raises(HTTPException):
        await dashboard.analitica_json(usuario=admin, red="tiktok")
