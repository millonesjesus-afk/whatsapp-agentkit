# tests/test_gate_analitica_p0.py — Gate Analítica P0 (Nueva Experiencia).
#
# Cubre las nuevas agregaciones de agent/memory.py (rango_periodo_utc,
# contar_flujo_periodo, calcular_embudo_comercial, contar_oportunidades_por_asesor,
# distribucion_resultados_periodo, resumen_ventas_periodo, productos_vendidos_periodo)
# y el endpoint GET /dashboard/analitica.json.
#
# Mismo criterio que el resto de la suite: se llama a la función/ruta
# directamente en vez de un TestClient HTTP, con datos SINTÉTICOS únicamente.
# "Leads sin atención"/"Leads estancados" NO se cubren acá — fueron
# retirados de P0 (Opción C, Gate Analítica P0: `Conversation.paso_flujo`
# es una columna muerta, nunca leída/escrita, y no se aproxima con
# `asesor_asignado_id IS NULL` ni se revierte a `Lead.paso_flujo`).

import json
from datetime import datetime, timedelta

from agent import dashboard, memory as mem


def _cuerpo(respuesta) -> dict:
    return json.loads(respuesta.body)


async def _negocio_con_canal(codigo: str, telefono_canal: str):
    negocio = await mem.crear_negocio(f"Negocio {codigo}", codigo)
    canal = await mem.crear_canal_whatsapp(nombre=f"Canal {codigo}", phone_number_id=telefono_canal, negocio_id=negocio["id"])
    return negocio, canal


async def _vender(opp, producto: str = "Terma", precio: str = "100", marca: str = "M", proveedor: str = "P"):
    ok = await mem.cerrar_opportunity_con_venta(
        opp.id, opp.version, [{"producto": producto, "precio": precio, "marca": marca, "proveedor": proveedor}],
        {"resultado": "vendido"},
    )
    assert ok
    return ok


def _periodo_hoy() -> tuple[str, datetime, datetime]:
    hoy = (datetime.utcnow() - timedelta(hours=5)).strftime("%Y-%m-%d")
    inicio, fin = mem.rango_periodo_utc(hoy, hoy)
    return hoy, inicio, fin


# ---------------------------------------------------------------------------
# rango_periodo_utc — límite de medianoche Lima (UTC-5 fijo)
# ---------------------------------------------------------------------------

def test_rango_periodo_utc_convierte_medianoche_lima():
    inicio, fin = mem.rango_periodo_utc("2026-03-10", "2026-03-10")
    assert inicio == datetime(2026, 3, 10, 5, 0)
    assert fin == datetime(2026, 3, 11, 5, 0)  # "hasta" es el ÚLTIMO día incluido


def test_rango_periodo_utc_multidia():
    inicio, fin = mem.rango_periodo_utc("2026-03-01", "2026-03-31")
    assert inicio == datetime(2026, 3, 1, 5, 0)
    assert fin == datetime(2026, 4, 1, 5, 0)


async def test_limite_medianoche_lima_incluye_y_excluye_correctamente():
    """Una Opportunity cerrada 1 segundo antes del límite cuenta; exactamente
    EN el límite (medianoche Lima del día siguiente) no — `< hasta`, nunca
    `<= hasta`."""
    negocio, canal = await _negocio_con_canal("ana-lim", "80000000001")
    conv, opp = await mem.resolver_conversation_activa("51900600001", negocio["id"], canal["id"])
    await _vender(opp)
    inicio, fin = mem.rango_periodo_utc("2026-05-15", "2026-05-15")

    async with mem.async_session() as session:
        o = await session.get(mem.Opportunity, opp.id)
        o.fecha_cierre = fin - timedelta(seconds=1)
        await session.commit()
    assert await mem._contar_ventas_periodo(negocio["id"], inicio, fin) == 1

    async with mem.async_session() as session:
        o = await session.get(mem.Opportunity, opp.id)
        o.fecha_cierre = fin
        await session.commit()
    assert await mem._contar_ventas_periodo(negocio["id"], inicio, fin) == 0


# ---------------------------------------------------------------------------
# contar_flujo_periodo — volumen de contexto, no funnel de conversión
# ---------------------------------------------------------------------------

async def test_contar_flujo_periodo_conteos_basicos():
    negocio, canal = await _negocio_con_canal("ana-flujo", "80000000002")
    _, opp1 = await mem.resolver_conversation_activa("51900600002", negocio["id"], canal["id"])
    await mem.resolver_conversation_activa("51900600003", negocio["id"], canal["id"])
    await _vender(opp1)

    hoy, inicio, fin = _periodo_hoy()
    flujo = await mem.contar_flujo_periodo(negocio["id"], inicio, fin)
    assert flujo == {
        "leads": 2, "conversaciones": 2, "oportunidades": 2, "ventas": 1,
        "ventas_de_leads_del_periodo": 1, "ventas_de_periodos_anteriores": 0,
    }


async def test_contar_flujo_periodo_leads_redefinido_como_contacts_distintos_con_filtro():
    negocio, canal = await _negocio_con_canal("ana-flujoasesor", "80000000003")
    conv1, _ = await mem.resolver_conversation_activa("51900600004", negocio["id"], canal["id"])
    await mem.intentar_asignar_conversation(conv1.id, conv1.version, "asesor_x")
    await mem.resolver_conversation_activa("51900600005", negocio["id"], canal["id"])  # sin asignar

    hoy, inicio, fin = _periodo_hoy()
    flujo = await mem.contar_flujo_periodo(negocio["id"], inicio, fin, asesor="asesor_x")
    assert flujo["leads"] == 1
    assert flujo["conversaciones"] == 1
    assert flujo["oportunidades"] == 1


# ---------------------------------------------------------------------------
# calcular_embudo_comercial — único funnel real: Oportunidad → Venta
# ---------------------------------------------------------------------------

async def test_calcular_embudo_comercial_tasa_cierre_none_sin_oportunidades():
    negocio, _ = await _negocio_con_canal("ana-embnone", "80000000004")
    hoy, inicio, fin = _periodo_hoy()
    embudo = await mem.calcular_embudo_comercial(negocio["id"], inicio, fin)
    assert embudo == {"oportunidades": 0, "ventas": 0, "tasa_cierre": None}


async def test_calcular_embudo_comercial_tasa_cierre_calculada():
    negocio, canal = await _negocio_con_canal("ana-embtasa", "80000000005")
    _, opp1 = await mem.resolver_conversation_activa("51900600006", negocio["id"], canal["id"])
    await mem.resolver_conversation_activa("51900600007", negocio["id"], canal["id"])
    await _vender(opp1)

    hoy, inicio, fin = _periodo_hoy()
    embudo = await mem.calcular_embudo_comercial(negocio["id"], inicio, fin)
    assert embudo["oportunidades"] == 2
    assert embudo["ventas"] == 1
    assert embudo["tasa_cierre"] == 0.5


async def test_flujo_periodo_ventas_coincide_con_embudo_ventas_por_construccion():
    """Ambos llaman EXACTAMENTE a `_contar_ventas_periodo` — nunca deben
    poder mostrar números distintos de 'ventas' en la misma respuesta."""
    negocio, canal = await _negocio_con_canal("ana-mismasventas", "80000000006")
    _, opp = await mem.resolver_conversation_activa("51900600008", negocio["id"], canal["id"])
    await _vender(opp)

    hoy, inicio, fin = _periodo_hoy()
    flujo = await mem.contar_flujo_periodo(negocio["id"], inicio, fin)
    embudo = await mem.calcular_embudo_comercial(negocio["id"], inicio, fin)
    assert flujo["ventas"] == embudo["ventas"] == 1


# ---------------------------------------------------------------------------
# Filtro de asesor — responsable ACTUAL, nunca reconstruye el histórico
# ---------------------------------------------------------------------------

async def test_filtro_asesor_refleja_responsable_actual_no_historico():
    negocio, canal = await _negocio_con_canal("ana-reasig", "80000000007")
    conv, opp = await mem.resolver_conversation_activa("51900600009", negocio["id"], canal["id"])

    assert await mem.intentar_asignar_conversation(conv.id, conv.version, "asesor_viejo")
    await _vender(opp)  # la venta ocurre mientras "asesor_viejo" es responsable — cerrar
    # la venta también avanza Conversation.version (pausado_manual, efecto de sistema),
    # así que se relee la version vigente en vez de asumir un solo incremento.
    async with mem.async_session() as session:
        conv_actualizada = await session.get(mem.Conversation, conv.id)
        version_vigente = conv_actualizada.version
    assert await mem.intentar_asignar_conversation(conv.id, version_vigente, "asesor_nuevo")  # reasignación posterior

    hoy, inicio, fin = _periodo_hoy()
    resultados = await mem.contar_oportunidades_por_asesor(
        negocio["id"], ["asesor_viejo", "asesor_nuevo"], inicio, fin,
    )
    assert resultados["asesor_viejo"] == {"oportunidades": 0, "ventas": 0, "tasa_cierre": None}
    assert resultados["asesor_nuevo"] == {"oportunidades": 1, "ventas": 1, "tasa_cierre": 1.0}

    ventas_viejo = await mem._contar_ventas_periodo(negocio["id"], inicio, fin, asesor="asesor_viejo")
    ventas_nuevo = await mem._contar_ventas_periodo(negocio["id"], inicio, fin, asesor="asesor_nuevo")
    assert ventas_viejo == 0
    assert ventas_nuevo == 1


# ---------------------------------------------------------------------------
# Filtro de campaña — excluye conversations orgánicas (sin campana_origen_id)
# ---------------------------------------------------------------------------

async def test_filtro_campana_excluye_conversations_organicas():
    negocio, canal = await _negocio_con_canal("ana-camp", "80000000008")
    campana = await mem.crear_campana("Campana Analitica", "texto_saludo", "hola", negocio_id=negocio["id"])
    await mem.resolver_conversation_activa("51900600010", negocio["id"], canal["id"], campana_origen_id=campana["id"])
    await mem.resolver_conversation_activa("51900600011", negocio["id"], canal["id"])  # orgánica

    hoy, inicio, fin = _periodo_hoy()
    flujo_total = await mem.contar_flujo_periodo(negocio["id"], inicio, fin)
    flujo_campana = await mem.contar_flujo_periodo(negocio["id"], inicio, fin, campana_id=campana["id"])
    assert flujo_total["oportunidades"] == 2
    assert flujo_campana["oportunidades"] == 1
    assert flujo_campana["leads"] == 1
    assert flujo_campana["conversaciones"] == 1


# ---------------------------------------------------------------------------
# Multi-tenant — 2 negocios homónimos (mismos teléfonos/asesores) no se mezclan
# ---------------------------------------------------------------------------

async def test_contar_flujo_periodo_no_mezcla_negocios_homonimos():
    negocio_a, canal_a = await _negocio_con_canal("ana-mtA", "80000000009")
    negocio_b, canal_b = await _negocio_con_canal("ana-mtB", "80000000010")
    telefono_compartido = "51900600012"

    _, opp_a = await mem.resolver_conversation_activa(telefono_compartido, negocio_a["id"], canal_a["id"])
    await mem.resolver_conversation_activa(telefono_compartido, negocio_b["id"], canal_b["id"])
    await _vender(opp_a)

    hoy, inicio, fin = _periodo_hoy()
    flujo_a = await mem.contar_flujo_periodo(negocio_a["id"], inicio, fin)
    flujo_b = await mem.contar_flujo_periodo(negocio_b["id"], inicio, fin)
    assert flujo_a == {
        "leads": 1, "conversaciones": 1, "oportunidades": 1, "ventas": 1,
        "ventas_de_leads_del_periodo": 1, "ventas_de_periodos_anteriores": 0,
    }
    assert flujo_b == {
        "leads": 1, "conversaciones": 1, "oportunidades": 1, "ventas": 0,
        "ventas_de_leads_del_periodo": 0, "ventas_de_periodos_anteriores": 0,
    }


# ---------------------------------------------------------------------------
# distribucion_resultados_periodo — usa exactamente los valores ya escritos
# ---------------------------------------------------------------------------

async def test_distribucion_resultados_periodo_agrupa_y_marca_sin_resultado():
    negocio, canal = await _negocio_con_canal("ana-dist", "80000000011")
    _, opp1 = await mem.resolver_conversation_activa("51900600013", negocio["id"], canal["id"])
    _, opp2 = await mem.resolver_conversation_activa("51900600014", negocio["id"], canal["id"])
    await mem.resolver_conversation_activa("51900600015", negocio["id"], canal["id"])  # sin resultado
    await _vender(opp1)
    await mem.intentar_cambiar_resultado_opportunity(opp2.id, opp2.version, {"resultado": "no_interesado"})

    hoy, inicio, fin = _periodo_hoy()
    distribucion = {d["resultado"]: d["total"] for d in await mem.distribucion_resultados_periodo(negocio["id"], inicio, fin)}
    assert distribucion == {"vendido": 1, "no_interesado": 1, "sin_resultado": 1}


# ---------------------------------------------------------------------------
# resumen_ventas_periodo — fail-safe: una línea no numérica excluye TODA la venta
# ---------------------------------------------------------------------------

async def test_resumen_ventas_periodo_excluye_venta_con_precio_no_numerico():
    negocio, canal = await _negocio_con_canal("ana-resumen", "80000000012")
    _, opp_valida = await mem.resolver_conversation_activa("51900600016", negocio["id"], canal["id"])
    _, opp_invalida = await mem.resolver_conversation_activa("51900600017", negocio["id"], canal["id"])
    await _vender(opp_valida, precio="150.50")
    ok = await mem.cerrar_opportunity_con_venta(
        opp_invalida.id, opp_invalida.version,
        [{"producto": "Terma Rota", "precio": "consultar", "marca": "M", "proveedor": "P"}],
        {"resultado": "vendido"},
    )
    assert ok

    hoy, inicio, fin = _periodo_hoy()
    resumen = await mem.resumen_ventas_periodo(negocio["id"], inicio, fin)
    assert resumen == {"monto": "150.50", "ventas_excluidas": 1}


async def test_venta_con_lineas_mixtas_una_valida_una_invalida_en_la_misma_opportunity():
    """Gate Analítica P0, revisión final punto 3 — una ÚNICA venta con 2
    líneas (una válida, una no numérica), no dos ventas separadas de una
    sola línea cada una: confirma que el fail-safe se evalúa por venta
    completa en `resumen_ventas_periodo` (por construcción, agrupa por
    `opportunity_id` antes de decidir validez) y por producto individual en
    `productos_vendidos_periodo` (agrupa por `producto`), sin que una línea
    inválida de un producto contamine el valor de otro producto de la
    MISMA venta."""
    negocio, canal = await _negocio_con_canal("ana-mixta", "80000000019")
    _, opp = await mem.resolver_conversation_activa("51900600026", negocio["id"], canal["id"])
    ok = await mem.cerrar_opportunity_con_venta(
        opp.id, opp.version,
        [
            {"producto": "Terma 8L", "precio": "100", "marca": "M", "proveedor": "P"},
            {"producto": "Cocina 4H", "precio": "consultar", "marca": "M", "proveedor": "P"},
        ],
        {"resultado": "vendido"},
    )
    assert ok

    hoy, inicio, fin = _periodo_hoy()

    # 1. La venta sigue contabilizándose en "ventas".
    flujo = await mem.contar_flujo_periodo(negocio["id"], inicio, fin)
    assert flujo["ventas"] == 1

    # 2. La tasa de cierre no cambia (1 oportunidad, 1 venta → 100%).
    embudo = await mem.calcular_embudo_comercial(negocio["id"], inicio, fin)
    assert embudo == {"oportunidades": 1, "ventas": 1, "tasa_cierre": 1.0}

    # 4 y 5. resumen_ventas_periodo excluye el monto COMPLETO de la venta
    # (no solo la línea inválida) y cuenta la venta como excluida.
    resumen = await mem.resumen_ventas_periodo(negocio["id"], inicio, fin)
    assert resumen == {"monto": "0.00", "ventas_excluidas": 1}

    # 3, 6 y 7. productos_vendidos_periodo: unidades se mantienen para
    # ambos productos; el producto de la línea inválida queda con
    # valor=None; el producto de la línea válida conserva su valor real,
    # sin contaminarse por la otra línea de la MISMA venta.
    productos = {p["producto"]: p for p in await mem.productos_vendidos_periodo(negocio["id"], inicio, fin)}
    assert productos["Terma 8L"] == {"producto": "Terma 8L", "unidades": 1, "valor": "100.00"}
    assert productos["Cocina 4H"] == {"producto": "Cocina 4H", "unidades": 1, "valor": None}


# ---------------------------------------------------------------------------
# productos_vendidos_periodo — valor None si alguna línea no es numérica
# ---------------------------------------------------------------------------

async def test_productos_vendidos_periodo_valor_none_y_orden_por_unidades():
    negocio, canal = await _negocio_con_canal("ana-productos", "80000000013")
    _, opp1 = await mem.resolver_conversation_activa("51900600018", negocio["id"], canal["id"])
    _, opp2 = await mem.resolver_conversation_activa("51900600019", negocio["id"], canal["id"])
    _, opp3 = await mem.resolver_conversation_activa("51900600020", negocio["id"], canal["id"])
    await _vender(opp1, producto="Terma 8L", precio="100")
    await _vender(opp2, producto="Terma 8L", precio="no numerico")
    await _vender(opp3, producto="Cocina 4H", precio="500")

    hoy, inicio, fin = _periodo_hoy()
    productos = await mem.productos_vendidos_periodo(negocio["id"], inicio, fin)
    por_nombre = {p["producto"]: p for p in productos}
    assert por_nombre["Terma 8L"]["unidades"] == 2
    assert por_nombre["Terma 8L"]["valor"] is None  # una de sus 2 líneas no es numérica
    assert por_nombre["Cocina 4H"]["unidades"] == 1
    assert por_nombre["Cocina 4H"]["valor"] == "500.00"
    assert productos[0]["producto"] == "Terma 8L"  # 2 unidades > 1, va primero


# ---------------------------------------------------------------------------
# Endpoint GET /dashboard/analitica.json
# ---------------------------------------------------------------------------

async def test_analitica_json_equipo_ausente_para_asesor_presente_para_admin():
    negocio, _ = await _negocio_con_canal("ana-ep-equipo", "80000000014")
    usuario_admin = {"negocio_id": negocio["id"], "rol": "admin", "username": "admin1"}
    usuario_asesor = {"negocio_id": negocio["id"], "rol": "asesor", "username": "asesor1"}

    cuerpo_admin = _cuerpo(await dashboard.analitica_json(usuario=usuario_admin))
    cuerpo_asesor = _cuerpo(await dashboard.analitica_json(usuario=usuario_asesor))

    assert "equipo" in cuerpo_admin
    assert cuerpo_admin["puede_ver_equipo"] is True
    assert "equipo" not in cuerpo_asesor
    assert cuerpo_asesor["puede_ver_equipo"] is False


async def test_analitica_json_asesor_ignora_filtro_de_otro_asesor_en_query():
    negocio, canal = await _negocio_con_canal("ana-ep-scope", "80000000015")
    conv_x, opp_x = await mem.resolver_conversation_activa("51900600021", negocio["id"], canal["id"])
    await mem.intentar_asignar_conversation(conv_x.id, conv_x.version, "asesor_x")
    await _vender(opp_x)
    conv_y, opp_y = await mem.resolver_conversation_activa("51900600022", negocio["id"], canal["id"])
    await mem.intentar_asignar_conversation(conv_y.id, conv_y.version, "asesor_y")
    await _vender(opp_y)

    usuario_asesor_x = {"negocio_id": negocio["id"], "rol": "asesor", "username": "asesor_x"}
    # Un asesor que intenta pedir el scope de otro (`asesor_y`) por query
    # string sigue recibiendo únicamente lo suyo — el parámetro se ignora
    # por completo para su rol.
    cuerpo = _cuerpo(await dashboard.analitica_json(usuario=usuario_asesor_x, asesor="asesor_y"))
    assert cuerpo["embudo"]["ventas"] == 1
    assert cuerpo["flujo_periodo"]["ventas"] == 1


async def test_analitica_json_admin_puede_acotar_por_asesor():
    negocio, canal = await _negocio_con_canal("ana-ep-adminscope", "80000000016")
    conv_x, opp_x = await mem.resolver_conversation_activa("51900600023", negocio["id"], canal["id"])
    await mem.intentar_asignar_conversation(conv_x.id, conv_x.version, "asesor_x")
    await _vender(opp_x)
    conv_y, opp_y = await mem.resolver_conversation_activa("51900600024", negocio["id"], canal["id"])
    await mem.intentar_asignar_conversation(conv_y.id, conv_y.version, "asesor_y")
    await _vender(opp_y)

    usuario_admin = {"negocio_id": negocio["id"], "rol": "admin", "username": "admin1"}
    cuerpo = _cuerpo(await dashboard.analitica_json(usuario=usuario_admin, asesor="asesor_x"))
    assert cuerpo["embudo"]["ventas"] == 1
    assert cuerpo["embudo"]["oportunidades"] == 1


async def test_analitica_json_sin_cierre_nunca_negativo_ni_como_pendientes():
    """'Brecha del período' — si la Opportunity se creó en un período previo
    pero cerró (vendió) dentro del período consultado, `oportunidades` del
    período puede ser MENOR que `ventas`; `fugas.sin_cierre` nunca debe
    mostrar un hueco negativo, y su descripción nunca debe sugerir
    oportunidades pendientes actuales."""
    negocio, canal = await _negocio_con_canal("ana-ep-brecha", "80000000017")
    _, opp = await mem.resolver_conversation_activa("51900600025", negocio["id"], canal["id"])
    await _vender(opp)
    async with mem.async_session() as session:
        o = await session.get(mem.Opportunity, opp.id)
        o.creado = o.creado - timedelta(days=60)  # fuera del mes en curso
        await session.commit()

    usuario_admin = {"negocio_id": negocio["id"], "rol": "admin", "username": "admin1"}
    cuerpo = _cuerpo(await dashboard.analitica_json(usuario=usuario_admin))
    assert cuerpo["embudo"]["oportunidades"] == 0
    assert cuerpo["embudo"]["ventas"] == 1
    assert cuerpo["fugas"]["sin_cierre"] == 0
    assert "no representa oportunidades actualmente pendientes" in cuerpo["fugas"]["sin_cierre_descripcion"]


async def test_analitica_json_periodo_por_defecto_es_mes_actual_lima():
    negocio, _ = await _negocio_con_canal("ana-ep-defecto", "80000000018")
    usuario_admin = {"negocio_id": negocio["id"], "rol": "admin", "username": "admin1"}
    hoy, _, _ = _periodo_hoy()
    cuerpo = _cuerpo(await dashboard.analitica_json(usuario=usuario_admin))
    assert cuerpo["periodo"]["desde"][:7] == hoy[:7]  # mismo mes-año
    assert cuerpo["periodo"]["hasta"] == hoy
    assert cuerpo["periodo"]["desde"].endswith("-01")
