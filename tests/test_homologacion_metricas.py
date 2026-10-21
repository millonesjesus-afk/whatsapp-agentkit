# tests/test_homologacion_metricas.py — todos los paneles de Analítica cuentan las ventas con LA MISMA base (cerradas en el
# período, `fecha_cierre`) y suman el mismo total: total «Ventas», asesores (con su fila «Sin asesor»), campañas, anuncios
# sin campaña, orgánico, Rendimiento por anuncio y detalle de ventas. Una venta de un cliente que entró en un período
# anterior cuenta en el total (se cerró ahora) y se desglosa aparte.

from datetime import datetime, timedelta

from sqlalchemy import update

from agent import memory as mem


async def _negocio(codigo: str):
    negocio = await mem.crear_negocio(f"Negocio {codigo}", codigo)
    canal = await mem.crear_canal_whatsapp(
        nombre=f"Canal {codigo}", phone_number_id=f"4097000{codigo[-2:]}", negocio_id=negocio["id"],
    )
    return negocio, canal


async def _cliente(negocio, canal, telefono, anuncio=None, asesor=None, campana=None, hace_dias=0):
    """Cliente con su conversación; opcionalmente entró por un anuncio, tiene asesor, campaña, o entró hace N días."""
    await mem.actualizar_lead(telefono, negocio_id=negocio["id"], numero_whatsapp_id="x")
    conversation, opp = await mem.resolver_conversation_activa(telefono, negocio["id"], canal["id"])
    if anuncio:
        await mem.registrar_attribution_event(telefono, "meta_ads_no_resuelto", referral={
            "source_id": anuncio, "headline": f"Anuncio {anuncio}", "body": "texto", "media_type": "image",
            "source_url": f"https://fb.me/{anuncio}",
        })
    if campana:
        await mem.asignar_campana_origen(telefono, campana)
    if asesor:
        await mem.asignar_asesor_a_lead(telefono, asesor)
    if hace_dias:
        antes = datetime.utcnow() - timedelta(days=hace_dias)
        async with mem.async_session() as session:
            await session.execute(update(mem.Conversation).where(mem.Conversation.id == conversation.id).values(creado=antes))
            await session.execute(update(mem.Opportunity).where(mem.Opportunity.id == opp.id).values(creado=antes))
            await session.commit()
    return opp


async def _vender(negocio, canal, telefono, producto, precio):
    _, opp = await mem.resolver_conversation_activa(telefono, negocio["id"], canal["id"])
    ok = await mem.cerrar_opportunity_con_venta(
        opp.id, opp.version, [{"producto": producto, "precio": precio, "marca": "M", "proveedor": "P"}],
        {"resultado": "vendido"},
    )
    assert ok


async def test_todos_los_paneles_suman_las_mismas_ventas():
    negocio, canal = await _negocio("hom-01")
    sms = await mem.crear_campana("SMS Secadora", "texto_saludo", "hola secadora", negocio_id=negocio["id"])
    nid = negocio["id"]
    # A y B: entraron ahora por anuncios, con asesor. C: entró hace 40 días (otro período), por anuncio, con asesor.
    await _cliente(negocio, canal, "51904400101", anuncio="AD-1", asesor="ana")
    await _cliente(negocio, canal, "51904400102", anuncio="AD-2", asesor="beto")
    await _cliente(negocio, canal, "51904400103", anuncio="AD-1", asesor="ana", hace_dias=40)
    # D: campaña no publicitaria, sin asesor. E: orgánico, sin asesor. G: orgánico con un asesor que ya no está en la lista.
    await _cliente(negocio, canal, "51904400104", campana=sms["nombre"])
    await _cliente(negocio, canal, "51904400105")
    await _cliente(negocio, canal, "51904400106", asesor="fantasma")
    # H: entró ahora y NO compró (solo cuenta como oportunidad).
    await _cliente(negocio, canal, "51904400107", anuncio="AD-2", asesor="beto")
    for telefono, precio in (("51904400101", "100"), ("51904400102", "200"), ("51904400103", "300"),
                             ("51904400104", "400"), ("51904400105", "500"), ("51904400106", "600")):
        await _vender(negocio, canal, telefono, f"Producto {telefono[-2:]}", precio)

    inicio, fin = datetime.utcnow() - timedelta(days=1), datetime.utcnow() + timedelta(days=1)
    flujo = await mem.contar_flujo_periodo(nid, inicio, fin)
    equipo = await mem.contar_oportunidades_por_asesor(nid, ["ana", "beto"], inicio, fin, incluir_sin_asesor=True)
    campanas = await mem.contar_opportunities_por_campana(nid, desde=inicio, hasta=fin)
    sin_campana = await mem.listar_atribucion_sin_campana_periodo(nid, inicio, fin)
    anuncios = await mem.rendimiento_por_anuncio(nid, inicio, fin)
    detalle = await mem.ventas_detalle_periodo(nid, inicio, fin)
    resumen_ventas = await mem.resumen_ventas_periodo(nid, inicio, fin)

    # TOTAL de ventas cerradas en el período
    assert flujo["ventas"] == 6
    assert (await mem.calcular_embudo_comercial(nid, inicio, fin))["ventas"] == 6
    # desglose: 5 de clientes que entraron en el período, 1 (C) de un período anterior
    assert flujo["ventas_de_leads_del_periodo"] == 5 and flujo["ventas_de_periodos_anteriores"] == 1
    # ASESORES: ana (A + C), beto (B), y «Sin asesor» reúne D, E y G (asesor que ya no está en la lista)
    assert (equipo["ana"]["ventas"], equipo["beto"]["ventas"], equipo[""]["ventas"]) == (2, 1, 3)
    assert sum(f["ventas"] for f in equipo.values()) == flujo["ventas"]
    # oportunidades: la tabla de asesores suma lo mismo que el total (C entró antes y no cuenta en este período)
    assert sum(f["oportunidades"] for f in equipo.values()) == flujo["oportunidades"] == 6
    # CAMPAÑAS + ANUNCIOS sin campaña + ORGÁNICO = el mismo total
    vend_campanas = sum(c["vendidos"] for c in campanas)
    vend_anuncios = sum(a["vendidos"] for a in sin_campana["anuncios"])
    assert (vend_campanas, vend_anuncios, sin_campana["organico"]["vendidos"]) == (1, 3, 2)
    assert vend_campanas + vend_anuncios + sin_campana["organico"]["vendidos"] == flujo["ventas"]
    # las conversaciones del período también suman: la venta de C no infla el total de entradas
    assert sum(c["total"] for c in campanas) + sum(a["total"] for a in sin_campana["anuncios"]) + sin_campana["organico"]["total"] == flujo["conversaciones"] == 6
    # RENDIMIENTO POR ANUNCIO y DETALLE DE VENTAS: mismo total, con su origen
    assert anuncios["resumen"]["ventas_periodo"] == 6 and anuncios["resumen"]["ventas_de_anuncios"] == 3
    assert anuncios["resumen"]["ventas_otras"] == 3
    assert detalle["resumen"]["total"] == 6 and detalle["resumen"]["por_origen"] == {"anuncio": 3, "campana": 1, "sin_origen": 2}
    # VALOR: el detalle suma lo mismo que el resumen de Analítica
    assert detalle["resumen"]["valor_total"] == resumen_ventas["monto"] == "2100.00"


async def test_la_fila_sin_asesor_no_aparece_si_todo_tiene_asesor():
    negocio, canal = await _negocio("hom-02")
    await _cliente(negocio, canal, "51904400201", anuncio="AD-1", asesor="ana")
    await _vender(negocio, canal, "51904400201", "Terma", "100")
    inicio, fin = datetime.utcnow() - timedelta(days=1), datetime.utcnow() + timedelta(days=1)

    equipo = await mem.contar_oportunidades_por_asesor(negocio["id"], ["ana"], inicio, fin, incluir_sin_asesor=True)

    assert equipo["ana"]["ventas"] == 1 and equipo[""] == {"oportunidades": 0, "ventas": 0, "tasa_cierre": None}
    # sin pedir la fila «sin asesor», el comportamiento es el de siempre
    assert set(await mem.contar_oportunidades_por_asesor(negocio["id"], ["ana"], inicio, fin)) == {"ana"}
