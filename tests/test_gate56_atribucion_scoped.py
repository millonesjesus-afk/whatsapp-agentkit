# tests/test_gate56_atribucion_scoped.py — Gate 5.6, corrección de 3 fugas
# cross-tenant confirmadas en la investigación (Arquitectura Integrada Gate
# 5.6): contar_leads_por_campana(), listar_lineas_venta_de_muchos() y
# contar_leads_activos_por_asesor() agregaban datos SIN negocio_id — con
# Tenant 002 usando el mismo nombre de campaña, el mismo teléfono, o el
# mismo username de asesor que Tenant 001 (Cálidda), los conteos/datos se
# mezclaban entre Negocios. Datos SINTÉTICOS únicamente.

import pytest

from agent import memory as mem


async def _negocio_con_canal(codigo: str, telefono_canal: str):
    negocio = await mem.crear_negocio(f"Negocio {codigo}", codigo)
    canal = await mem.crear_canal_whatsapp(nombre=f"Canal {codigo}", phone_number_id=telefono_canal, negocio_id=negocio["id"])
    return negocio, canal


# ---------------------------------------------------------------------------
# Fix 1/2 — contar_opportunities_por_campana() / eliminar_campana()
# ---------------------------------------------------------------------------

async def test_contar_opportunities_por_campana_no_mezcla_negocios():
    """El escenario exacto que motivó la corrección: Tenant 001 y Tenant 002
    tienen cada uno una campaña de nombre IDÉNTICO ('Promo Verano'), con
    actividad propia — el conteo de uno no debe incluir al otro."""
    negocio_a, canal_a = await _negocio_con_canal("g56-a", "70000000001")
    negocio_b, canal_b = await _negocio_con_canal("g56-b", "70000000002")
    campana_a = await mem.crear_campana(
        "Promo Verano", "texto_saludo", "hola verano", negocio_id=negocio_a["id"],
    )
    campana_b = await mem.crear_campana(
        "Promo Verano", "texto_saludo", "hola verano", negocio_id=negocio_b["id"],
    )

    # Tenant A: 2 conversations atribuidas a su campaña, 1 vendida.
    conv_a1, opp_a1 = await mem.resolver_conversation_activa(
        "51900500001", negocio_a["id"], canal_a["id"], campana_origen_id=campana_a["id"],
    )
    await mem.intentar_cambiar_resultado_opportunity(opp_a1.id, opp_a1.version, {"resultado": "vendido"})
    await mem.resolver_conversation_activa(
        "51900500002", negocio_a["id"], canal_a["id"], campana_origen_id=campana_a["id"],
    )

    # Tenant B: 1 conversation atribuida a SU campaña homónima, sin ventas.
    await mem.resolver_conversation_activa(
        "51900500003", negocio_b["id"], canal_b["id"], campana_origen_id=campana_b["id"],
    )

    conteos_a = {c["campana"]: c for c in await mem.contar_opportunities_por_campana(negocio_a["id"])}
    conteos_b = {c["campana"]: c for c in await mem.contar_opportunities_por_campana(negocio_b["id"])}

    assert conteos_a["Promo Verano"]["total"] == 2
    assert conteos_a["Promo Verano"]["vendidos"] == 1
    assert conteos_b["Promo Verano"]["total"] == 1  # nunca 3 — no se suma con Tenant A
    assert conteos_b["Promo Verano"]["vendidos"] == 0


async def test_contar_opportunities_por_campana_respeta_unidad_id_cuando_se_pasa():
    negocio, canal = await _negocio_con_canal("g56-c", "70000000003")
    unidad_x = "unidad-x-sintetica"
    unidad_y = "unidad-y-sintetica"
    campana_x = await mem.crear_campana(
        "Campana X", "texto_saludo", "hola x", negocio_id=negocio["id"], unidad_id=unidad_x,
    )
    campana_y = await mem.crear_campana(
        "Campana Y", "texto_saludo", "hola y", negocio_id=negocio["id"], unidad_id=unidad_y,
    )
    await mem.resolver_conversation_activa("51900500004", negocio["id"], canal["id"], campana_origen_id=campana_x["id"])
    await mem.resolver_conversation_activa("51900500005", negocio["id"], canal["id"], campana_origen_id=campana_y["id"])

    solo_x = await mem.contar_opportunities_por_campana(negocio["id"], unidad_id=unidad_x)
    nombres_x = {c["campana"] for c in solo_x}
    assert nombres_x == {"Campana X"}  # Campana Y no aparece, es de otra Unidad

    todas = await mem.contar_opportunities_por_campana(negocio["id"])
    assert {c["campana"] for c in todas} == {"Campana X", "Campana Y"}


async def test_contar_opportunities_por_campana_incluye_historico_no_solo_activas():
    """Regresión: el conteo legacy nunca filtraba por estado — una
    Conversation cerrada (ej. reemplazada por una nueva del mismo Contact,
    DR-4) sigue contando para la campaña que la originó."""
    negocio, canal = await _negocio_con_canal("g56-d", "70000000004")
    campana = await mem.crear_campana("Campana Historica", "texto_saludo", "hola", negocio_id=negocio["id"])
    conv, _ = await mem.resolver_conversation_activa("51900500006", negocio["id"], canal["id"], campana_origen_id=campana["id"])
    async with mem.async_session() as session:
        c = await session.get(mem.Conversation, conv.id)
        c.estado = "cerrada"
        await session.commit()

    conteos = {c["campana"]: c for c in await mem.contar_opportunities_por_campana(negocio["id"])}
    assert conteos["Campana Historica"]["total"] == 1  # sigue contando, aunque esté cerrada


async def test_eliminar_campana_no_bloqueada_por_actividad_de_otro_negocio():
    negocio_a, canal_a = await _negocio_con_canal("g56-e", "70000000005")
    negocio_b, _ = await _negocio_con_canal("g56-f", "70000000006")
    campana_b_vacia = await mem.crear_campana("Sin Actividad", "texto_saludo", "hola", negocio_id=negocio_b["id"])
    campana_a_homonima = await mem.crear_campana("Sin Actividad", "texto_saludo", "hola", negocio_id=negocio_a["id"])
    # Actividad SOLO en la campaña de Tenant A — la de Tenant B, con el mismo
    # nombre, sigue vacía y debe poder borrarse igual.
    await mem.resolver_conversation_activa("51900500007", negocio_a["id"], canal_a["id"], campana_origen_id=campana_a_homonima["id"])

    borrada_b = await mem.eliminar_campana(campana_b_vacia["id"], negocio_b["id"])
    assert borrada_b is True  # Tenant B puede borrar la suya, sin importar la actividad de Tenant A

    borrada_a = await mem.eliminar_campana(campana_a_homonima["id"], negocio_a["id"])
    assert borrada_a is False  # Tenant A no puede borrar la suya — tiene actividad real


async def test_eliminar_campana_rechaza_negocio_id_ajeno():
    negocio_a, _ = await _negocio_con_canal("g56-g", "70000000007")
    negocio_b, _ = await _negocio_con_canal("g56-h", "70000000008")
    campana_a = await mem.crear_campana("Solo de A", "texto_saludo", "hola", negocio_id=negocio_a["id"])

    # Defensa en profundidad — Tenant B no puede borrar una campaña de A
    # aunque conozca su id, incluso sin actividad.
    assert await mem.eliminar_campana(campana_a["id"], negocio_b["id"]) is False


# ---------------------------------------------------------------------------
# Fix 3 — listar_lineas_venta_de_muchos()
# ---------------------------------------------------------------------------

async def test_listar_lineas_venta_de_muchos_no_cruza_negocios_mismo_telefono():
    """El escenario adversarial exacto reportado en la investigación: mismo
    teléfono, Contact/Conversation/Opportunity propios en cada Negocio, venta
    cerrada SOLO en Tenant B — Tenant A no debe ver ese producto/precio."""
    negocio_a, canal_a = await _negocio_con_canal("g56-i", "70000000009")
    negocio_b, canal_b = await _negocio_con_canal("g56-j", "70000000010")
    telefono = "51900500008"

    conv_a, opp_a = await mem.resolver_conversation_activa(telefono, negocio_a["id"], canal_a["id"])
    conv_b, opp_b = await mem.resolver_conversation_activa(telefono, negocio_b["id"], canal_b["id"])

    ok = await mem.cerrar_opportunity_con_venta(
        opp_b.id, opp_b.version,
        [{"producto": "Terma B", "precio": "999", "marca": "MarcaB", "proveedor": "ProveedorB"}],
        {"resultado": "vendido"},
    )
    assert ok

    lineas_a = await mem.listar_lineas_venta_de_muchos([telefono], negocio_a["id"])
    lineas_b = await mem.listar_lineas_venta_de_muchos([telefono], negocio_b["id"])

    assert lineas_a.get(telefono, []) == []  # Tenant A no ve nada — su Opportunity nunca vendió
    assert len(lineas_b[telefono]) == 1
    assert lineas_b[telefono][0]["producto"] == "Terma B"


async def test_listar_lineas_venta_de_muchos_caso_normal_un_negocio():
    negocio, canal = await _negocio_con_canal("g56-k", "70000000011")
    telefono = "51900500009"
    conv, opp = await mem.resolver_conversation_activa(telefono, negocio["id"], canal["id"])
    await mem.cerrar_opportunity_con_venta(
        opp.id, opp.version,
        [{"producto": "Cocina X", "precio": "500", "marca": "M", "proveedor": "P"}],
        {"resultado": "vendido"},
    )
    lineas = await mem.listar_lineas_venta_de_muchos([telefono], negocio["id"])
    assert len(lineas[telefono]) == 1
    assert lineas[telefono][0]["producto"] == "Cocina X"


# ---------------------------------------------------------------------------
# Fix 4 — contar_conversations_activas_por_asesor()
# ---------------------------------------------------------------------------

async def test_contar_conversations_activas_por_asesor_no_mezcla_negocios_mismo_username():
    negocio_a, canal_a = await _negocio_con_canal("g56-l", "70000000012")
    negocio_b, canal_b = await _negocio_con_canal("g56-m", "70000000013")
    username_compartido = "asesor_compartido"

    conv_a, _ = await mem.resolver_conversation_activa("51900500010", negocio_a["id"], canal_a["id"])
    await mem.intentar_asignar_conversation(conv_a.id, conv_a.version, username_compartido)
    conv_a2, _ = await mem.resolver_conversation_activa("51900500011", negocio_a["id"], canal_a["id"])
    await mem.intentar_asignar_conversation(conv_a2.id, conv_a2.version, username_compartido)

    conv_b, _ = await mem.resolver_conversation_activa("51900500012", negocio_b["id"], canal_b["id"])
    await mem.intentar_asignar_conversation(conv_b.id, conv_b.version, username_compartido)

    conteos_a = await mem.contar_conversations_activas_por_asesor(negocio_a["id"], [username_compartido])
    conteos_b = await mem.contar_conversations_activas_por_asesor(negocio_b["id"], [username_compartido])

    assert conteos_a[username_compartido] == 2  # nunca 3 — no se suma con Tenant B
    assert conteos_b[username_compartido] == 1


async def test_contar_conversations_activas_por_asesor_excluye_resultados_cerrados():
    negocio, canal = await _negocio_con_canal("g56-n", "70000000014")
    conv1, opp1 = await mem.resolver_conversation_activa("51900500013", negocio["id"], canal["id"])
    await mem.intentar_asignar_conversation(conv1.id, conv1.version, "asesor_x")
    conv2, opp2 = await mem.resolver_conversation_activa("51900500014", negocio["id"], canal["id"])
    await mem.intentar_asignar_conversation(conv2.id, conv2.version, "asesor_x")
    # Solo la segunda llega a un resultado cerrado — deja de contar como carga activa.
    await mem.intentar_cambiar_resultado_opportunity(opp2.id, opp2.version, {"resultado": "vendido"})

    conteos = await mem.contar_conversations_activas_por_asesor(negocio["id"], ["asesor_x"])
    assert conteos["asesor_x"] == 1
