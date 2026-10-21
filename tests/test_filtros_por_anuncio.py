# tests/test_filtros_por_anuncio.py — filtros globales de Analítica por empresa, formato y producto del anuncio: acotan TODOS
# los paneles (flujo, embudo, ventas, productos, campañas, asesores, rendimiento por anuncio) al mismo conjunto de clientes.

import json
from datetime import datetime, timedelta

import pytest
from fastapi import HTTPException

from agent import dashboard, memory as mem


async def _negocio(codigo: str):
    negocio = await mem.crear_negocio(f"Negocio {codigo}", codigo)
    canal = await mem.crear_canal_whatsapp(
        nombre=f"Canal {codigo}", phone_number_id=f"4098000{codigo[-2:]}", negocio_id=negocio["id"],
    )
    return negocio, canal


async def _cliente(negocio, canal, telefono, anuncio, titulo, texto, media, asesor=None):
    await mem.actualizar_lead(telefono, negocio_id=negocio["id"], numero_whatsapp_id="x")
    await mem.resolver_conversation_activa(telefono, negocio["id"], canal["id"])
    await mem.registrar_attribution_event(telefono, "meta_ads_no_resuelto", referral={
        "source_id": anuncio, "headline": titulo, "body": texto, "media_type": media, "source_url": f"https://fb.me/{anuncio}",
    })
    if asesor:
        await mem.asignar_asesor_a_lead(telefono, asesor)


async def _vender(negocio, canal, telefono, producto, precio):
    _, opp = await mem.resolver_conversation_activa(telefono, negocio["id"], canal["id"])
    assert await mem.cerrar_opportunity_con_venta(
        opp.id, opp.version, [{"producto": producto, "precio": precio, "marca": "M", "proveedor": "P"}],
        {"resultado": "vendido"},
    )


async def _escenario(codigo: str):
    """Estratek: video de secadora (3 clientes, 2 ventas). Cálidda: imagen de terma (2 clientes, 1 venta). Sin empresa: imagen
    de cocina (1 cliente, sin venta). Más un cliente orgánico (sin anuncio) con una venta."""
    negocio, canal = await _negocio(codigo)
    for i, (tel, asesor) in enumerate((("01", "ana"), ("02", "ana"), ("03", "beto"))):
        await _cliente(negocio, canal, f"5190550{codigo[-2:]}{tel}", "AD-V", "Reel secadora", "tu secadora", "video", asesor)
    for tel in ("04", "05"):
        await _cliente(negocio, canal, f"5190550{codigo[-2:]}{tel}", "AD-I", "Pieza terma", "tu terma", "image", "beto")
    await _cliente(negocio, canal, f"5190550{codigo[-2:]}06", "AD-C", "Pieza cocina", "tu cocina", "image", "ana")
    await mem.actualizar_lead(f"5190550{codigo[-2:]}07", negocio_id=negocio["id"], numero_whatsapp_id="x")
    await mem.resolver_conversation_activa(f"5190550{codigo[-2:]}07", negocio["id"], canal["id"])
    await _vender(negocio, canal, f"5190550{codigo[-2:]}01", "Secadora", "100")
    await _vender(negocio, canal, f"5190550{codigo[-2:]}02", "Secadora", "150")
    await _vender(negocio, canal, f"5190550{codigo[-2:]}04", "Terma", "200")
    await _vender(negocio, canal, f"5190550{codigo[-2:]}07", "Ducteria", "50")  # orgánico
    grupos = (await mem.rendimiento_por_anuncio(negocio["id"], datetime(2000, 1, 1), datetime.utcnow() + timedelta(days=1)))["grupos"]
    por_titulo = {g["titulo"]: g["clave"] for g in grupos}
    await mem.guardar_empresa_grupo(negocio["id"], por_titulo["Reel secadora"], "Estratek")
    await mem.guardar_empresa_grupo(negocio["id"], por_titulo["Pieza terma"], "Cálidda")
    return negocio


def _periodo():
    return datetime.utcnow() - timedelta(days=1), datetime.utcnow() + timedelta(days=1)


async def _panel(negocio, ids):
    inicio, fin = _periodo()
    nid = negocio["id"]
    return {
        "flujo": await mem.contar_flujo_periodo(nid, inicio, fin, ids_conversacion=ids),
        "embudo": await mem.calcular_embudo_comercial(nid, inicio, fin, ids_conversacion=ids),
        "valor": await mem.resumen_ventas_periodo(nid, inicio, fin, ids_conversacion=ids),
        "productos": await mem.productos_vendidos_periodo(nid, inicio, fin, ids_conversacion=ids),
        "equipo": await mem.contar_oportunidades_por_asesor(nid, ["ana", "beto"], inicio, fin, incluir_sin_asesor=True, ids_conversacion=ids),
        "sin_campana": await mem.listar_atribucion_sin_campana_periodo(nid, inicio, fin, ids_conversacion=ids),
        "anuncios": await mem.rendimiento_por_anuncio(nid, inicio, fin, ids_conversacion=ids),
        "detalle": await mem.ventas_detalle_periodo(nid, inicio, fin, ids_conversacion=ids),
    }


async def test_sin_filtro_no_se_acota_nada():
    negocio = await _escenario("flt-01")
    assert await mem.ids_conversacion_de_segmento(negocio["id"]) is None
    p = await _panel(negocio, None)
    assert p["flujo"]["conversaciones"] == 7 and p["flujo"]["ventas"] == 4


async def test_filtro_por_empresa_acota_todos_los_paneles_al_mismo_conjunto():
    negocio = await _escenario("flt-02")
    ids = await mem.ids_conversacion_de_segmento(negocio["id"], empresa="Estratek")
    assert len(ids) == 3
    p = await _panel(negocio, ids)

    assert (p["flujo"]["leads"], p["flujo"]["conversaciones"], p["flujo"]["oportunidades"], p["flujo"]["ventas"]) == (3, 3, 3, 2)
    assert p["embudo"]["ventas"] == 2 and p["valor"]["monto"] == "250.00"
    assert [(x["producto"], x["unidades"]) for x in p["productos"]] == [("Secadora", 2)]
    assert (p["equipo"]["ana"]["ventas"], p["equipo"]["beto"]["ventas"], p["equipo"][""]["ventas"]) == (2, 0, 0)
    assert sum(f["oportunidades"] for f in p["equipo"].values()) == p["flujo"]["oportunidades"] == 3
    assert sum(a["vendidos"] for a in p["sin_campana"]["anuncios"]) == 2 and p["sin_campana"]["organico"]["total"] == 0
    assert [g["titulo"] for g in p["anuncios"]["grupos"]] == ["Reel secadora"] and p["anuncios"]["resumen"]["ventas_periodo"] == 2
    assert p["detalle"]["resumen"]["total"] == 2 and p["detalle"]["resumen"]["valor_total"] == "250.00"


async def test_filtro_por_formato_producto_y_sin_empresa():
    negocio = await _escenario("flt-03")
    nid = negocio["id"]
    imagen = await mem.ids_conversacion_de_segmento(nid, formato="imagen")
    terma = await mem.ids_conversacion_de_segmento(nid, producto="terma")
    sin_empresa = await mem.ids_conversacion_de_segmento(nid, empresa=mem.SIN_EMPRESA_FILTRO)
    combinado = await mem.ids_conversacion_de_segmento(nid, empresa="cálidda", formato="imagen", producto="terma")  # sin distinguir mayúsculas

    assert (len(imagen), len(terma), len(sin_empresa), len(combinado)) == (3, 2, 1, 2)
    p = await _panel(negocio, imagen)
    assert p["flujo"]["ventas"] == 1 and p["flujo"]["conversaciones"] == 3
    # un segmento sin ningún cliente deja la pantalla en cero, no en el total
    vacio = await mem.ids_conversacion_de_segmento(nid, empresa="Nadie")
    assert vacio == set()
    p0 = await _panel(negocio, vacio)
    assert p0["flujo"]["conversaciones"] == 0 and p0["flujo"]["ventas"] == 0 and p0["anuncios"]["grupos"] == []


async def test_el_filtro_orgánico_no_incluye_lo_que_no_vino_de_un_anuncio():
    negocio = await _escenario("flt-04")
    ids = await mem.ids_conversacion_de_segmento(negocio["id"], formato="video")
    p = await _panel(negocio, ids)
    assert p["sin_campana"]["organico"]["vendidos"] == 0  # la venta orgánica queda fuera de cualquier filtro de anuncio


async def test_lista_de_empresas_y_endpoints_validan_los_filtros():
    negocio = await _escenario("flt-05")
    assert await mem.listar_empresas_anuncio(negocio["id"]) == ["Cálidda", "Estratek"]
    admin = {"negocio_id": negocio["id"], "rol": "admin", "username": "jesus"}

    de_estratek = json.loads((await dashboard.analitica_anuncios_json(usuario=admin, empresa="Estratek")).body)
    ventas_estratek = json.loads((await dashboard.analitica_ventas_json(usuario=admin, empresa="Estratek")).body)
    assert [g["titulo"] for g in de_estratek["grupos"]] == ["Reel secadora"]
    assert ventas_estratek["resumen"]["total"] == 2
    with pytest.raises(HTTPException) as e:
        await dashboard.analitica_anuncios_json(usuario=admin, formato="gif")
    assert e.value.status_code == 400
    with pytest.raises(HTTPException) as e:
        await dashboard.analitica_ventas_json(usuario=admin, producto="auto")
    assert e.value.status_code == 400
