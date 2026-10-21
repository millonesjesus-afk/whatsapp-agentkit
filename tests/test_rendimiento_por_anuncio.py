# tests/test_rendimiento_por_anuncio.py — Analítica "Rendimiento por anuncio": conversaciones, leads y ventas por GRUPO
# de anuncios (título + texto + formato), sin asignar campañas; empresa como etiqueta por grupo.

import json
from datetime import datetime, timedelta

import pytest
from fastapi import HTTPException

from agent import dashboard, memory as mem


async def _negocio(codigo: str):
    negocio = await mem.crear_negocio(f"Negocio {codigo}", codigo)
    canal = await mem.crear_canal_whatsapp(
        nombre=f"Canal {codigo}", phone_number_id=f"4096000{codigo[-2:]}", negocio_id=negocio["id"],
    )
    return negocio, canal


async def _lead(
    negocio, canal, telefono, source_id, headline="Financia tu artefacto",
    body="Con el gas natural de Cálidda secadora y terma", media="image", asesor=None,
):
    await mem.actualizar_lead(telefono, negocio_id=negocio["id"], numero_whatsapp_id="x")
    await mem.resolver_conversation_activa(telefono, negocio["id"], canal["id"])
    await mem.registrar_attribution_event(
        telefono, "meta_ads_no_resuelto",
        referral={
            "source_id": source_id, "headline": headline, "body": body, "media_type": media,
            "source_url": f"https://fb.me/{source_id}",
        },
    )
    if asesor:
        await mem.asignar_asesor_a_lead(telefono, asesor)


async def _vender(negocio, canal, telefono, lineas):
    """Cierra la venta de la conversación activa del cliente con el flujo real (deja fecha de cierre y líneas)."""
    _, opp = await mem.resolver_conversation_activa(telefono, negocio["id"], canal["id"])
    ok = await mem.cerrar_opportunity_con_venta(
        opp.id, opp.version,
        [{"producto": p, "precio": pr, "marca": "M", "proveedor": "P"} for p, pr in lineas],
        {"resultado": "vendido"},
    )
    assert ok


def _periodo():
    return datetime.utcnow() - timedelta(days=1), datetime.utcnow() + timedelta(days=1)


def test_clave_de_grupo_incluye_formato_y_normaliza_texto():
    a = mem.clave_grupo_anuncio("Chatea con nosotros", "Hola", "video")
    assert a == mem.clave_grupo_anuncio("  CHATEA con   nosotros", "hola", "video")
    assert a != mem.clave_grupo_anuncio("Chatea con nosotros", "Hola", "image")  # mismo texto, otro formato
    assert mem.formato_de_anuncio("video") == "video" and mem.formato_de_anuncio("image") == "imagen"
    assert mem.formato_de_anuncio(None) == "desconocido"


@pytest.mark.parametrize("titulo,cuerpo,esperado", [
    ("Una sola vez y te vas", "Tender no es la tarea: la secadora", "secadora"),
    ("Agua Caliente Cálidda", "terma a gas", "terma"),
    ("Renueva tu cocina ahora", "", "cocina"),
    ("Financia tu artefacto", "secadora y terma", "varios"),
    ("Hola", "gracias", "sin_definir"),
])
def test_producto_desde_el_texto(titulo, cuerpo, esperado):
    assert mem.producto_de_anuncio(titulo, cuerpo) == esperado


async def test_agrupa_por_texto_y_formato_y_cuenta_una_vez_por_primer_anuncio():
    negocio, canal = await _negocio("rpa-01")
    await _lead(negocio, canal, "51903300101", "AD-1")
    await _lead(negocio, canal, "51903300102", "AD-2")  # mismo texto y formato: mismo grupo, otro anuncio
    await _lead(negocio, canal, "51903300103", "AD-3", media="video")  # mismo texto, otro formato: otro grupo
    # el lead 1 llega después por otro anuncio en la MISMA conversación: no se cuenta dos veces
    await mem.registrar_attribution_event_adicional(
        "51903300101", "meta_ads_no_resuelto",
        referral={
            "source_id": "AD-3", "headline": "Financia tu artefacto",
            "body": "Con el gas natural de Cálidda secadora y terma", "media_type": "video",
        },
    )

    datos = await mem.rendimiento_por_anuncio(negocio["id"], *_periodo())

    por_formato = {g["formato"]: g for g in datos["grupos"]}
    assert len(datos["grupos"]) == 2
    assert por_formato["imagen"]["anuncios_total"] == 2 and por_formato["imagen"]["conversaciones"] == 2
    assert por_formato["video"]["anuncios_total"] == 1 and por_formato["video"]["conversaciones"] == 1
    assert por_formato["imagen"]["producto"] == "varios" and por_formato["imagen"]["leads"] == 2
    assert datos["resumen"]["conversaciones"] == 3 and datos["resumen"]["sin_empresa"] == 2
    assert por_formato["imagen"]["anuncios"][0]["url"].startswith("https://fb.me/")


async def test_ventas_periodo_y_alcance_por_asesor():
    negocio, canal = await _negocio("rpa-02")
    await _lead(negocio, canal, "51903300201", "AD-1", asesor="ana")
    await _lead(negocio, canal, "51903300202", "AD-1", asesor="beto")
    await _vender(negocio, canal, "51903300201", [("Terma 8L", "100")])

    todos = await mem.rendimiento_por_anuncio(negocio["id"], *_periodo())
    de_ana = await mem.rendimiento_por_anuncio(negocio["id"], *_periodo(), asesor="ana")
    fuera = await mem.rendimiento_por_anuncio(
        negocio["id"], datetime.utcnow() - timedelta(days=30), datetime.utcnow() - timedelta(days=20),
    )

    assert todos["grupos"][0]["conversaciones"] == 2 and todos["grupos"][0]["ventas"] == 1
    assert de_ana["grupos"][0]["conversaciones"] == 1 and de_ana["grupos"][0]["ventas"] == 1
    assert fuera["grupos"] == []


async def test_empresa_sugerida_desde_nombres_de_campana_y_etiqueta_manual():
    negocio, canal = await _negocio("rpa-03")
    await _lead(negocio, canal, "51903300301", "AD-E", headline="Se paga en tu recibo", body="secadora", media="video")
    await _lead(negocio, canal, "51903300302", "AD-C", headline="Financia", body="otra", media="image")
    await _lead(negocio, canal, "51903300303", "AD-X", headline="Sin pista", body="nada", media="image")
    await mem.crear_campana_de_anuncio("Meta Estratek - Reel Secadora", "AD-E", negocio["id"])
    await mem.crear_campana_de_anuncio("Meta Calidda - Pieza Terma", "AD-C", negocio["id"])
    await mem.crear_campana_de_anuncio("Meta Calidda Estratek mezcla", "AD-X", negocio["id"])  # ambigua: no se adivina

    datos = await mem.rendimiento_por_anuncio(negocio["id"], *_periodo())
    sug = {g["titulo"]: g["empresa_sugerida"] for g in datos["grupos"]}
    assert sug == {"Se paga en tu recibo": "Estratek", "Financia": "Cálidda", "Sin pista": None}

    plan = await mem.aplicar_empresas_sugeridas(negocio["id"], aplicar=False)
    assert plan["aplicado"] is False and len(plan["grupos_a_etiquetar"]) == 2 and len(plan["sin_sugerencia"]) == 1
    assert (await mem.rendimiento_por_anuncio(negocio["id"], *_periodo()))["resumen"]["sin_empresa"] == 3

    hecho = await mem.aplicar_empresas_sugeridas(negocio["id"], aplicar=True, autor="jesus")
    assert hecho["aplicado"] is True
    datos = await mem.rendimiento_por_anuncio(negocio["id"], *_periodo())
    assert {g["titulo"]: g["empresa"] for g in datos["grupos"]} == {
        "Se paga en tu recibo": "Estratek", "Financia": "Cálidda", "Sin pista": None,
    }

    clave = next(g["clave"] for g in datos["grupos"] if g["titulo"] == "Sin pista")
    assert await mem.guardar_empresa_grupo(negocio["id"], clave, "Estratek", autor="jesus") == "Estratek"
    assert await mem.guardar_empresa_grupo(negocio["id"], clave, "") is None  # vacía = quitar
    assert (await mem.rendimiento_por_anuncio(negocio["id"], *_periodo()))["resumen"]["sin_empresa"] == 1
    with pytest.raises(ValueError):
        await mem.guardar_empresa_grupo(negocio["id"], "", "X")


async def test_un_anuncio_nuevo_con_el_mismo_contenido_hereda_la_empresa():
    negocio, canal = await _negocio("rpa-04")
    await _lead(negocio, canal, "51903300401", "AD-1")
    clave = (await mem.rendimiento_por_anuncio(negocio["id"], *_periodo()))["grupos"][0]["clave"]
    await mem.guardar_empresa_grupo(negocio["id"], clave, "Cálidda")
    await _lead(negocio, canal, "51903300402", "AD-NUEVO")  # otro ID, mismo contenido

    grupo = (await mem.rendimiento_por_anuncio(negocio["id"], *_periodo()))["grupos"]
    assert len(grupo) == 1 and grupo[0]["anuncios_total"] == 2 and grupo[0]["empresa"] == "Cálidda"


async def test_endpoints_alcance_y_permiso():
    negocio, canal = await _negocio("rpa-05")
    await _lead(negocio, canal, "51903300501", "AD-1", asesor="ana")
    await _lead(negocio, canal, "51903300502", "AD-1", asesor="beto")
    admin = {"negocio_id": negocio["id"], "rol": "admin", "username": "jesus"}
    asesor = {"negocio_id": negocio["id"], "rol": "asesor", "username": "ana"}

    ve_todo = json.loads((await dashboard.analitica_anuncios_json(usuario=admin)).body)
    ve_lo_suyo = json.loads((await dashboard.analitica_anuncios_json(usuario=asesor, asesor="beto")).body)
    assert ve_todo["grupos"][0]["conversaciones"] == 2 and ve_todo["puede_gestionar"] is True
    # el filtro de otro asesor se ignora: un asesor solo ve lo suyo
    assert ve_lo_suyo["grupos"][0]["conversaciones"] == 1 and ve_lo_suyo["puede_gestionar"] is False
    assert isinstance(ve_todo["grupos"][0]["anuncios"][0]["ultimo"], str)
    with pytest.raises(HTTPException) as e:
        await dashboard.analitica_anuncios_json(usuario=admin, desde="mal", hasta="fecha")
    assert e.value.status_code == 400

    class _Req:
        def __init__(self, d):
            self._d = d

        async def json(self):
            return self._d

    clave = ve_todo["grupos"][0]["clave"]
    ok = json.loads((await dashboard.analitica_anuncios_empresa_json(
        _Req({"clave_grupo": clave, "empresa": "Estratek"}), usuario=admin, _csrf=None,
    )).body)
    assert ok == {"ok": True, "empresa": "Estratek"}
    with pytest.raises(HTTPException) as e:
        await dashboard.analitica_anuncios_empresa_json(_Req({"clave_grupo": "", "empresa": "X"}), usuario=admin, _csrf=None)
    assert e.value.status_code == 400
    vista = json.loads((await dashboard.analitica_anuncios_empresa_json(
        _Req({"aplicar_sugeridas": True}), usuario=admin, _csrf=None,
    )).body)
    assert vista["aplicado"] is False


async def test_la_sugerencia_exige_mayoria_y_no_la_deciden_conversaciones_sueltas():
    negocio, canal = await _negocio("rpa-06")
    # 4 conversaciones del grupo en una campaña SIN empresa; 1 suelta en una campaña con empresa
    for i in range(4):
        await _lead(negocio, canal, f"5190330070{i}", "AD-MAYORIA", headline="Chatea", body="mismo")
    await _lead(negocio, canal, "51903300709", "AD-SUELTA", headline="Chatea", body="mismo")
    await mem.crear_campana_de_anuncio("Secadora Julio", "AD-MAYORIA", negocio["id"])
    await mem.crear_campana_de_anuncio("Meta Estratek - Reel", "AD-SUELTA", negocio["id"])
    for i in range(4):
        await mem.asignar_campana_origen(f"5190330070{i}", "Secadora Julio")
    await mem.asignar_campana_origen("51903300709", "Meta Estratek - Reel")

    datos = await mem.rendimiento_por_anuncio(negocio["id"], *_periodo())

    assert datos["grupos"][0]["conversaciones"] == 5
    assert datos["grupos"][0]["empresa_sugerida"] is None  # 1 de 5 no alcanza


async def test_la_sugerencia_no_se_da_si_hay_dos_empresas_presentes():
    negocio, canal = await _negocio("rpa-07")
    for i in range(3):
        await _lead(negocio, canal, f"5190330080{i}", "AD-A", headline="Mixto", body="mismo")
    await _lead(negocio, canal, "51903300809", "AD-B", headline="Mixto", body="mismo")
    await mem.crear_campana_de_anuncio("Meta Estratek - A", "AD-A", negocio["id"])
    await mem.crear_campana_de_anuncio("Meta Calidda - B", "AD-B", negocio["id"])
    for i in range(3):
        await mem.asignar_campana_origen(f"5190330080{i}", "Meta Estratek - A")
    await mem.asignar_campana_origen("51903300809", "Meta Calidda - B")

    datos = await mem.rendimiento_por_anuncio(negocio["id"], *_periodo())

    assert datos["grupos"][0]["empresa_sugerida"] is None  # 75% Estratek pero 25% Cálidda: ambiguo


async def test_las_ventas_se_cuentan_por_fecha_de_cierre_y_cuadran_con_el_total_de_analitica():
    negocio, canal = await _negocio("rpa-10")
    await _lead(negocio, canal, "51903301001", "AD-1", asesor="ana")                       # entra por anuncio
    await _lead(negocio, canal, "51903301002", "AD-2", headline="Otro", body="otro", media="video")
    await mem.actualizar_lead("51903301003", negocio_id=negocio["id"], numero_whatsapp_id="x")  # sin anuncio ni campaña
    await mem.resolver_conversation_activa("51903301003", negocio["id"], canal["id"])
    await _vender(negocio, canal, "51903301001", [("Terma 8L", "100"), ("Punto adicional", "50")])
    await _vender(negocio, canal, "51903301002", [("Secadora", "300")])
    await _vender(negocio, canal, "51903301003", [("Cocina", "200")])

    inicio, fin = _periodo()
    datos = await mem.rendimiento_por_anuncio(negocio["id"], inicio, fin)
    total_analitica = await mem._contar_ventas_periodo(negocio["id"], inicio, fin)

    assert total_analitica == 3
    assert datos["resumen"]["ventas_periodo"] == total_analitica  # mismo total que "Ventas" de Analítica
    assert datos["resumen"]["ventas_de_anuncios"] == 2 and datos["resumen"]["ventas_otras"] == 1
    assert sum(g["ventas"] for g in datos["grupos"]) == 2
    assert all(a["ventas"] in (0, 1) for g in datos["grupos"] for a in g["anuncios"])


async def test_una_venta_cerrada_hoy_de_un_cliente_que_entro_antes_cuenta_en_su_grupo():
    negocio, canal = await _negocio("rpa-11")
    await _lead(negocio, canal, "51903301101", "AD-1")
    await _vender(negocio, canal, "51903301101", [("Terma", "100")])
    # período que NO incluye el ingreso del cliente pero SÍ el cierre de la venta
    desde, hasta = datetime.utcnow() - timedelta(hours=1), datetime.utcnow() + timedelta(days=1)
    antes_del_ingreso = datetime.utcnow() - timedelta(days=30), datetime.utcnow() - timedelta(days=20)

    datos = await mem.rendimiento_por_anuncio(negocio["id"], desde, hasta)
    fuera = await mem.rendimiento_por_anuncio(negocio["id"], *antes_del_ingreso)

    assert datos["grupos"][0]["ventas"] == 1 and datos["grupos"][0]["leads"] == 1
    assert fuera["grupos"] == [] and fuera["resumen"]["ventas_periodo"] == 0


async def test_detalle_de_ventas_con_productos_valor_origen_y_telefono_enmascarado():
    negocio, canal = await _negocio("rpa-12")
    campana = await mem.crear_campana("SMS Secadora", "texto_saludo", "hola secadora", negocio_id=negocio["id"])
    await _lead(negocio, canal, "51903301201", "AD-1", headline="Financia", body="secadora", media="image", asesor="ana")
    await mem.actualizar_lead("51903301202", negocio_id=negocio["id"], numero_whatsapp_id="x")
    await mem.resolver_conversation_activa("51903301202", negocio["id"], canal["id"])
    await mem.asignar_campana_origen("51903301202", campana["nombre"])
    await mem.actualizar_lead("51903301203", negocio_id=negocio["id"], numero_whatsapp_id="x")
    await mem.resolver_conversation_activa("51903301203", negocio["id"], canal["id"])
    await _vender(negocio, canal, "51903301201", [("Terma 8L", "100"), ("Punto adicional", "50")])
    await _vender(negocio, canal, "51903301202", [("Secadora", "300")])
    await _vender(negocio, canal, "51903301203", [("Ducteria", "consultar")])
    clave = (await mem.rendimiento_por_anuncio(negocio["id"], *_periodo()))["grupos"][0]["clave"]
    await mem.guardar_empresa_grupo(negocio["id"], clave, "Cálidda")

    datos = await mem.ventas_detalle_periodo(negocio["id"], *_periodo())

    por_origen = {v["origen"]: v for v in datos["ventas"]}
    assert datos["resumen"]["total"] == 3
    assert datos["resumen"]["por_origen"] == {"anuncio": 1, "campana": 1, "sin_origen": 1}
    anuncio = por_origen["anuncio"]
    assert [p["producto"] for p in anuncio["productos"]] == ["Terma 8L", "Punto adicional"] and anuncio["valor"] == "150.00"
    assert anuncio["grupo_titulo"] == "Financia" and anuncio["formato"] == "imagen" and anuncio["empresa"] == "Cálidda"
    assert anuncio["source_id"] == "AD-1" and anuncio["url"].startswith("https://fb.me/") and anuncio["asesor"] == "ana"
    assert anuncio["telefono"] == "…1201" and "5190330" not in json.dumps(datos, default=str)
    assert por_origen["campana"]["campana"] == "SMS Secadora" and por_origen["campana"]["valor"] == "300.00"
    assert por_origen["sin_origen"]["valor"] is None  # precio no numérico: el valor no se inventa
    # el valor total excluye la venta con precio no numérico (mismo criterio que resumen_ventas_periodo)
    assert datos["resumen"]["valor_total"] == "450.00" and datos["resumen"]["ventas_sin_valor"] == 1
    assert (await mem.resumen_ventas_periodo(negocio["id"], *_periodo()))["monto"] == "450.00"


async def test_endpoint_de_ventas_alcance_por_rol_y_total_que_cuadra():
    negocio, canal = await _negocio("rpa-13")
    await _lead(negocio, canal, "51903301301", "AD-1", asesor="ana")
    await _lead(negocio, canal, "51903301302", "AD-1", asesor="beto")
    await _vender(negocio, canal, "51903301301", [("Terma", "100")])
    await _vender(negocio, canal, "51903301302", [("Secadora", "200")])
    admin = {"negocio_id": negocio["id"], "rol": "admin", "username": "jesus"}
    ana = {"negocio_id": negocio["id"], "rol": "asesor", "username": "ana"}

    todas = json.loads((await dashboard.analitica_ventas_json(usuario=admin)).body)
    suyas = json.loads((await dashboard.analitica_ventas_json(usuario=ana, asesor="beto")).body)

    assert todas["resumen"]["total"] == 2 and isinstance(todas["ventas"][0]["fecha_cierre"], str)
    assert suyas["resumen"]["total"] == 1 and suyas["ventas"][0]["asesor"] == "ana"  # el filtro de otro asesor se ignora
    with pytest.raises(HTTPException) as e:
        await dashboard.analitica_ventas_json(usuario=admin, desde="mal", hasta="fecha")
    assert e.value.status_code == 400


async def test_red_estimada_por_grupo_con_leads_y_ventas_por_red():
    negocio, canal = await _negocio("rpa-14")
    await mem.actualizar_lead("51903301401", negocio_id=negocio["id"], numero_whatsapp_id="x")
    await mem.resolver_conversation_activa("51903301401", negocio["id"], canal["id"])
    await mem.registrar_attribution_event("51903301401", "meta_ads_no_resuelto", referral={
        "source_id": "AD-1", "headline": "Financia", "body": "x", "media_type": "image", "source_url": "https://fb.me/abc",
    })
    await mem.actualizar_lead("51903301402", negocio_id=negocio["id"], numero_whatsapp_id="x")
    await mem.resolver_conversation_activa("51903301402", negocio["id"], canal["id"])
    await mem.registrar_attribution_event("51903301402", "meta_ads_no_resuelto", referral={
        "source_id": "AD-1", "headline": "Financia", "body": "x", "media_type": "image", "source_url": "https://www.instagram.com/p/xyz/",
    })
    await mem.actualizar_lead("51903301403", negocio_id=negocio["id"], numero_whatsapp_id="x")
    await mem.resolver_conversation_activa("51903301403", negocio["id"], canal["id"])
    await mem.registrar_attribution_event("51903301403", "meta_ads_no_resuelto", referral={
        "source_id": "AD-1", "headline": "Financia", "body": "x", "media_type": "image", "source_url": "https://fb.me/def",
    })
    await _vender(negocio, canal, "51903301402", [("Terma", "100")])  # la venta es de Instagram

    datos = await mem.rendimiento_por_anuncio(negocio["id"], *_periodo())
    redes = datos["grupos"][0]["redes"]
    detalle = await mem.ventas_detalle_periodo(negocio["id"], *_periodo())

    assert redes["facebook"] == {"leads": 2, "conversaciones": 2, "ventas": 0}
    assert redes["instagram"] == {"leads": 1, "conversaciones": 1, "ventas": 1}
    assert redes["otra"] == {"leads": 0, "conversaciones": 0, "ventas": 0}
    assert sum(v["leads"] for v in redes.values()) == datos["grupos"][0]["leads"]  # las redes reparten el total, sin duplicar
    assert detalle["ventas"][0]["red"] == "instagram"

