# tests/test_gate54_listados_scoped.py — Gate 5.4, T2: 7 funciones de
# listado que NUNCA filtraban por negocio_id (listar_asesores,
# listar_campanas, listar_canales_whatsapp, listar_leads,
# listar_leads_agendados, listar_leads_esperando_asesor,
# obtener_ultimos_mensajes) — un Negocio A no debe ver datos de un Negocio B.
# Datos sintéticos únicamente (crear_negocio), mismo criterio que
# test_gate53_cutover_real_opportunity.py — nunca Cálidda hardcodeada.

from datetime import datetime, timedelta

from agent import memory as mem


async def _negocio_con_canal(codigo: str, telefono_canal: str):
    negocio = await mem.crear_negocio(f"Negocio {codigo}", codigo)
    canal = await mem.crear_canal_whatsapp(
        nombre=f"Canal {codigo}", phone_number_id=telefono_canal,
        access_token=f"token-{codigo}", app_secret=f"secret-{codigo}",
        negocio_id=negocio["id"],
    )
    return negocio, canal


# ---------------------------------------------------------------------------
# 1 — listar_asesores
# ---------------------------------------------------------------------------

async def test_listar_asesores_no_ve_asesores_de_otro_negocio():
    negocio_a, _ = await _negocio_con_canal("as-a", "30000000001")
    negocio_b, _ = await _negocio_con_canal("as-b", "30000000002")

    await mem.crear_usuario("asesor_a", "pw12345", "Asesor A", "asesor", negocio_a["id"])
    await mem.crear_usuario("asesor_b", "pw12345", "Asesor B", "asesor", negocio_b["id"])

    asesores_a = await mem.listar_asesores(negocio_a["id"])
    asesores_b = await mem.listar_asesores(negocio_b["id"])

    assert [a["username"] for a in asesores_a] == ["asesor_a"]
    assert [a["username"] for a in asesores_b] == ["asesor_b"]


# ---------------------------------------------------------------------------
# 2 — listar_campanas
# ---------------------------------------------------------------------------

async def test_listar_campanas_no_ve_campanas_de_otro_negocio():
    negocio_a, _ = await _negocio_con_canal("ca-a", "30000000003")
    negocio_b, _ = await _negocio_con_canal("ca-b", "30000000004")

    await mem.crear_campana(
        nombre="Campaña A", tipo_deteccion="texto_saludo", patron="hola a",
        negocio_id=negocio_a["id"],
    )
    await mem.crear_campana(
        nombre="Campaña B", tipo_deteccion="texto_saludo", patron="hola b",
        negocio_id=negocio_b["id"],
    )

    campanas_a = await mem.listar_campanas(negocio_a["id"])
    campanas_b = await mem.listar_campanas(negocio_b["id"])

    assert [c["nombre"] for c in campanas_a] == ["Campaña A"]
    assert [c["nombre"] for c in campanas_b] == ["Campaña B"]


# ---------------------------------------------------------------------------
# 3 — listar_canales_whatsapp: scoped (panel) vs sin scope (resolver_canal)
# ---------------------------------------------------------------------------

async def test_listar_canales_whatsapp_scoped_no_ve_canales_ni_credenciales_de_otro_negocio():
    negocio_a, canal_a = await _negocio_con_canal("ch-a", "30000000005")
    negocio_b, canal_b = await _negocio_con_canal("ch-b", "30000000006")

    canales_a = await mem.listar_canales_whatsapp(negocio_id=negocio_a["id"])
    canales_b = await mem.listar_canales_whatsapp(negocio_id=negocio_b["id"])

    assert [c["id"] for c in canales_a] == [canal_a["id"]]
    assert [c["id"] for c in canales_b] == [canal_b["id"]]
    # Credenciales descifradas van en el dict (uso interno) — confirmar que
    # el panel de administración de Negocio A no recibe ni el token de B.
    assert canales_a[0]["access_token"] == "token-ch-a"
    assert all(c["access_token"] != "token-ch-b" for c in canales_a)


async def test_listar_canales_whatsapp_sin_negocio_id_ve_de_ambos_negocios():
    """Comportamiento INTENCIONAL — única excepción del Gate 5.4 (T2):
    resolver_canal() (agent/providers/meta.py) llama a esta función SIN
    negocio_id porque todavía está averiguando a qué Negocio pertenece un
    mensaje entrante; no hay forma de pedirle de antemano el dato que está
    resolviendo. Con negocio_id=None, la función devuelve canales de TODOS
    los Negocios (nunca para una pantalla del panel, ver
    gestionar_canales_whatsapp en dashboard.py, que siempre pasa negocio_id)."""
    negocio_a, canal_a = await _negocio_con_canal("ch-c", "30000000007")
    negocio_b, canal_b = await _negocio_con_canal("ch-d", "30000000008")

    canales = await mem.listar_canales_whatsapp()

    ids = {c["id"] for c in canales}
    assert canal_a["id"] in ids
    assert canal_b["id"] in ids


# ---------------------------------------------------------------------------
# 4 — listar_leads
# ---------------------------------------------------------------------------

async def test_listar_leads_no_ve_leads_de_otro_negocio():
    negocio_a, _ = await _negocio_con_canal("ld-a", "30000000009")
    negocio_b, _ = await _negocio_con_canal("ld-b", "30000000010")

    await mem.actualizar_lead("51900300001", nombre="Cliente A", negocio_id=negocio_a["id"])
    await mem.actualizar_lead("51900300002", nombre="Cliente B", negocio_id=negocio_b["id"])

    leads_a = await mem.listar_leads(negocio_a["id"])
    leads_b = await mem.listar_leads(negocio_b["id"])

    assert [l["telefono"] for l in leads_a] == ["51900300001"]
    assert [l["telefono"] for l in leads_b] == ["51900300002"]


# ---------------------------------------------------------------------------
# 5 — listar_leads_agendados
# ---------------------------------------------------------------------------

async def test_listar_leads_agendados_no_ve_agendados_de_otro_negocio():
    negocio_a, _ = await _negocio_con_canal("ag-a", "30000000011")
    negocio_b, _ = await _negocio_con_canal("ag-b", "30000000012")

    manana = datetime.utcnow() + timedelta(days=1)
    await mem.actualizar_lead(
        "51900300003", nombre="Cliente A", resultado="agendado", fecha_agendada=manana,
        negocio_id=negocio_a["id"],
    )
    await mem.actualizar_lead(
        "51900300004", nombre="Cliente B", resultado="agendado", fecha_agendada=manana,
        negocio_id=negocio_b["id"],
    )

    agendados_a = await mem.listar_leads_agendados(negocio_a["id"])
    agendados_b = await mem.listar_leads_agendados(negocio_b["id"])

    assert [l["telefono"] for l in agendados_a] == ["51900300003"]
    assert [l["telefono"] for l in agendados_b] == ["51900300004"]


# ---------------------------------------------------------------------------
# 6 — listar_leads_esperando_asesor
# ---------------------------------------------------------------------------

async def test_listar_leads_esperando_asesor_no_ve_pendientes_de_otro_negocio():
    negocio_a, _ = await _negocio_con_canal("es-a", "30000000013")
    negocio_b, _ = await _negocio_con_canal("es-b", "30000000014")

    await mem.actualizar_lead(
        "51900300005", nombre="Cliente A", paso_flujo="derivado_asesor",
        negocio_id=negocio_a["id"],
    )
    await mem.actualizar_lead(
        "51900300006", nombre="Cliente B", paso_flujo="derivado_asesor",
        negocio_id=negocio_b["id"],
    )

    esperando_a = await mem.listar_leads_esperando_asesor(negocio_a["id"])
    esperando_b = await mem.listar_leads_esperando_asesor(negocio_b["id"])

    assert [l["telefono"] for l in esperando_a] == ["51900300005"]
    assert [l["telefono"] for l in esperando_b] == ["51900300006"]


# ---------------------------------------------------------------------------
# 7 — obtener_ultimos_mensajes
# ---------------------------------------------------------------------------

async def test_obtener_ultimos_mensajes_no_trae_mensajes_de_otro_negocio():
    negocio_a, _ = await _negocio_con_canal("mn-a", "30000000015")
    negocio_b, _ = await _negocio_con_canal("mn-b", "30000000016")

    telefono_a = "51900300007"
    telefono_b = "51900300008"
    await mem.actualizar_lead(telefono_a, nombre="Cliente A", negocio_id=negocio_a["id"])
    await mem.actualizar_lead(telefono_b, nombre="Cliente B", negocio_id=negocio_b["id"])
    await mem.guardar_mensaje(telefono_a, "user", "Hola desde A", negocio_id=negocio_a["id"])
    await mem.guardar_mensaje(telefono_b, "user", "Hola desde B", negocio_id=negocio_b["id"])

    # Un bug de otro lado podría colar un teléfono ajeno en la lista — el
    # candado real acá es negocio_id, no confiar en que `telefonos` venga
    # ya bien filtrado.
    ultimos_a = await mem.obtener_ultimos_mensajes([telefono_a, telefono_b], negocio_a["id"])

    assert telefono_a in ultimos_a
    assert telefono_b not in ultimos_a
    assert ultimos_a[telefono_a]["content"] == "Hola desde A"
