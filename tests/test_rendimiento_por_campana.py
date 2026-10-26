# tests/test_rendimiento_por_campana.py — agrupación «Campaña» de Analítica (2026-10-26): clientes, conversaciones y
# ventas por campaña con las mismas reglas de atribución que el resto, sin doble conteo y cuadrando con «Ventas».

import json
from datetime import datetime, timedelta

from agent import dashboard, memory as mem


async def _negocio(codigo: str):
    negocio = await mem.crear_negocio(f"Negocio {codigo}", codigo)
    canal = await mem.crear_canal_whatsapp(
        nombre=f"Canal {codigo}", phone_number_id=f"4095000{codigo[-2:]}", negocio_id=negocio["id"],
    )
    return negocio, canal


async def _entra(negocio, canal, telefono, anuncio=None, titulo="Anuncio", media="image"):
    await mem.actualizar_lead(telefono, negocio_id=negocio["id"], numero_whatsapp_id="x")
    await mem.resolver_conversation_activa(telefono, negocio["id"], canal["id"])
    if anuncio:
        await mem.registrar_attribution_event(telefono, "meta_ads_no_resuelto", referral={
            "source_id": anuncio, "headline": titulo, "body": "texto", "media_type": media, "source_url": f"https://fb.me/{anuncio}",
        })


async def _vender(negocio, canal, telefono, precio="100"):
    _, opp = await mem.resolver_conversation_activa(telefono, negocio["id"], canal["id"])
    assert await mem.cerrar_opportunity_con_venta(
        opp.id, opp.version, [{"producto": "Terma", "precio": precio, "marca": "M", "proveedor": "P"}], {"resultado": "vendido"},
    )


def _periodo():
    return datetime.utcnow() - timedelta(days=1), datetime.utcnow() + timedelta(days=1)


async def test_agrupa_por_campana_con_sin_asignar_y_organicos_y_cuadra_con_las_ventas():
    negocio, canal = await _negocio("cmp-01")
    await mem.crear_campana_de_anuncio("Estratek - Reel Terma 1", "AD-A", negocio["id"])
    await mem.crear_campana_de_anuncio("Calidda - Pieza Secadora 1", "AD-B", negocio["id"])
    # 3 clientes por AD-A (1 vende), 2 por AD-B (sin ventas), 2 por un anuncio sin campaña (1 vende), 1 orgánico (vende).
    for i in range(3):
        await _entra(negocio, canal, f"5190440100{i}", "AD-A", "Reel terma", "video")
    for i in range(2):
        await _entra(negocio, canal, f"5190440200{i}", "AD-B", "Pieza secadora")
    for i in range(2):
        await _entra(negocio, canal, f"5190440300{i}", "AD-SIN", "Financia tu artefacto")
    await _entra(negocio, canal, "51904404000")
    for tel in ("51904401000", "51904403000", "51904404000"):
        await _vender(negocio, canal, tel)

    inicio, fin = _periodo()
    r = await mem.rendimiento_por_campana(negocio["id"], inicio, fin)
    por_nombre = {c["nombre"]: c for c in r["campanas"]}
    assert [c["tipo"] for c in r["campanas"]] == ["campana", "campana", "sin_asignar", "organico"]
    a = por_nombre["Estratek - Reel Terma 1"]
    assert (a["clientes"], a["conversaciones"], a["ventas"], a["activa"]) == (3, 3, 1, True)
    assert a["anuncios_total"] == 1 and a["anuncios"][0]["source_id"] == "AD-A" and a["anuncios"][0]["formato"] == "video"
    assert (por_nombre["Calidda - Pieza Secadora 1"]["clientes"], por_nombre["Calidda - Pieza Secadora 1"]["ventas"]) == (2, 0)
    sin = por_nombre["Sin campaña asignada"]
    assert (sin["clientes"], sin["ventas"], sin["activa"]) == (2, 1, None)
    org = por_nombre["Orgánicos"]
    assert (org["clientes"], org["ventas"], org["anuncios_total"]) == (1, 1, 0)
    assert org["redes"]["otra"]["conversaciones"] == 1
    # Lo que se muestra cuadra con «Ventas» y con el total de conversaciones
    assert r["resumen"]["ventas_periodo"] == r["resumen"]["ventas_en_filas"] == 3
    assert sum(c["conversaciones"] for c in r["campanas"]) == r["resumen"]["conversaciones"] == 8
    assert r["resumen"]["clientes"] == 8
    # El detalle de ventas nombra la campaña igual que esta tabla (así el botón «ventas» de cada fila abre las mismas)
    detalle = (await mem.ventas_detalle_periodo(negocio["id"], inicio, fin))["ventas"]
    assert sorted(((v["origen"], v["campana"]) for v in detalle), key=lambda t: (t[0], t[1] or "")) == [
        ("anuncio", None), ("anuncio", "Estratek - Reel Terma 1"), ("sin_origen", None),
    ]


async def test_un_cliente_que_vuelve_por_otra_campana_cuenta_como_cliente_en_cada_una():
    negocio, canal = await _negocio("cmp-02")
    await mem.crear_campana_de_anuncio("Campaña A", "AD-A", negocio["id"])
    await mem.crear_campana_de_anuncio("Campaña B", "AD-B", negocio["id"])
    tel = "51904405000"
    await _entra(negocio, canal, tel, "AD-A", "A")
    await mem.actualizar_lead(tel, negocio_id=negocio["id"], resultado="sin_respuesta")
    assert await mem.cerrar_lead_definitivamente(tel, negocio["id"], "test")
    # vuelve por otro anuncio: conversación nueva, que cuenta para la campaña por la que entró ahora
    await mem.resolver_conversation_activa(tel, negocio["id"], canal["id"])
    await mem.registrar_attribution_event(tel, "meta_ads_no_resuelto", referral={"source_id": "AD-B", "headline": "B", "body": "b"})

    inicio, fin = _periodo()
    r = await mem.rendimiento_por_campana(negocio["id"], inicio, fin)
    por_nombre = {c["nombre"]: c for c in r["campanas"]}
    assert por_nombre["Campaña A"]["clientes"] == 1 and por_nombre["Campaña B"]["clientes"] == 1
    assert r["resumen"]["conversaciones"] == 2
    # el mismo cliente en dos campañas: las filas suman 2 pero el total de clientes distintos es 1
    assert r["resumen"]["clientes"] == 1 and sum(c["clientes"] for c in r["campanas"]) == 2


async def test_los_filtros_de_asesor_y_segmento_acotan_igual_que_el_resto():
    negocio, canal = await _negocio("cmp-03")
    await mem.crear_campana_de_anuncio("Campaña A", "AD-A", negocio["id"])
    await _entra(negocio, canal, "51904406000", "AD-A", "A")
    await _entra(negocio, canal, "51904406001", "AD-A", "A")
    await mem.asignar_asesor_a_lead("51904406000", "ana")
    inicio, fin = _periodo()
    de_ana = await mem.rendimiento_por_campana(negocio["id"], inicio, fin, asesor="ana")
    assert de_ana["resumen"]["conversaciones"] == 1
    vacio = await mem.rendimiento_por_campana(negocio["id"], inicio, fin, ids_conversacion=set())
    assert vacio["campanas"] == [] and vacio["resumen"]["conversaciones"] == 0


async def test_el_endpoint_trae_por_campana_sin_romper_lo_que_ya_traia():
    negocio, canal = await _negocio("cmp-04")
    await mem.crear_campana_de_anuncio("Campaña A", "AD-A", negocio["id"])
    await _entra(negocio, canal, "51904407000", "AD-A", "A")
    admin = {"negocio_id": negocio["id"], "rol": "admin", "username": "jesus"}
    hoy = (datetime.utcnow() - timedelta(hours=5)).strftime("%Y-%m-%d")
    r = json.loads((await dashboard.analitica_anuncios_json(usuario=admin, desde=hoy, hasta=hoy)).body)
    assert {"grupos", "empresas", "resumen", "por_campana"} <= set(r)
    [fila] = r["por_campana"]["campanas"]
    assert fila["nombre"] == "Campaña A" and fila["anuncios"][0]["ultimo"].endswith("Z")
