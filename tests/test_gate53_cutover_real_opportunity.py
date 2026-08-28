# tests/test_gate53_cutover_real_opportunity.py — Gate 5.3, cutover real:
# Opportunity/Conversation como fuente de verdad de las 3 escrituras humanas
# (resultado/venta/asignación), Lead como compatibilidad legacy con
# sincronización mínima. Datos sintéticos únicamente, mismo criterio que
# test_gate53_contact_conversation_opportunity.py — ningún Tenant 002 real,
# ningún telefono/negocio hardcodeado como "el correcto".

import pytest

from agent import memory as mem


async def _negocio_con_canal(codigo: str, telefono_canal: str):
    negocio = await mem.crear_negocio(f"Negocio {codigo}", codigo)
    canal = await mem.crear_canal_whatsapp(
        nombre=f"Canal {codigo}", phone_number_id=telefono_canal, negocio_id=negocio["id"],
    )
    return negocio, canal


async def _abrir_conversacion(negocio: dict, canal: dict, telefono: str):
    return await mem.resolver_conversation_activa(
        telefono, negocio["id"], canal["id"], unidad_id=canal.get("unidad_id"),
    )


# ---------------------------------------------------------------------------
# 1/2/3 — las 3 escrituras humanas, camino nuevo (Opportunity/Conversation
# como fuente de verdad), sin pasar por Lead en absoluto
# ---------------------------------------------------------------------------

async def test_opportunity_resultado_exitoso_no_depende_de_lead():
    """Nueva Experiencia: cambia el resultado usando solo opportunity_version
    — NUNCA crea ni toca un Lead (cutover real §1/§13: la escritura nueva no
    depende del endpoint legacy)."""
    negocio, canal = await _negocio_con_canal("cut1", "20000000001")
    telefono = "51900200001"
    conv, opp = await _abrir_conversacion(negocio, canal, telefono)

    ok = await mem.intentar_cambiar_resultado_opportunity(opp.id, 0, {"resultado": "no_interesado"})
    assert ok

    async with mem.async_session() as session:
        opportunity = await session.get(mem.Opportunity, opp.id)
        assert opportunity.resultado == "no_interesado"
        assert opportunity.version == 1
        lead = await session.get(mem.Lead, telefono)
        assert lead is None  # nunca se creó — el camino nuevo no depende de Lead


async def test_opportunity_venta_exitosa_registra_lineaventa_y_marca_vendido():
    negocio, canal = await _negocio_con_canal("cut2", "20000000002")
    telefono = "51900200002"
    conv, opp = await _abrir_conversacion(negocio, canal, telefono)

    ok = await mem.cerrar_opportunity_con_venta(
        opp.id, 0, [{"producto": "Balón 10kg", "precio": "45"}], {"modalidad_pago": "contado", "medio_pago": "QR", "resultado": "vendido"},
    )
    assert ok

    async with mem.async_session() as session:
        from sqlalchemy import select
        opportunity = await session.get(mem.Opportunity, opp.id)
        assert opportunity.resultado == "vendido"
        assert opportunity.fecha_cierre is not None
        lineas = (await session.execute(
            select(mem.LineaVenta).where(mem.LineaVenta.opportunity_id == opp.id)
        )).scalars().all()
        assert [l.producto for l in lineas] == ["Balón 10kg"]
        conversation = await session.get(mem.Conversation, conv.id)
        assert conversation.pausado_manual is True


async def test_conversation_asignacion_exitosa():
    negocio, canal = await _negocio_con_canal("cut3", "20000000003")
    telefono = "51900200003"
    conv, opp = await _abrir_conversacion(negocio, canal, telefono)

    ok = await mem.intentar_asignar_conversation(conv.id, 0, "asesor1")
    assert ok

    async with mem.async_session() as session:
        conversation = await session.get(mem.Conversation, conv.id)
        assert conversation.asesor_asignado_id == "asesor1"
        assert conversation.visto_asesor is False
        assert conversation.version == 1


# ---------------------------------------------------------------------------
# 5/6 — conflicto de version, cada entidad con su propio contador
# ---------------------------------------------------------------------------

async def test_conflicto_conversation_version_en_asignacion():
    negocio, canal = await _negocio_con_canal("cut4", "20000000004")
    telefono = "51900200004"
    conv, opp = await _abrir_conversacion(negocio, canal, telefono)

    assert await mem.intentar_asignar_conversation(conv.id, 0, "asesor1")
    # version vieja (0) — ya avanzó a 1 arriba.
    ok = await mem.intentar_asignar_conversation(conv.id, 0, "asesor2")
    assert not ok
    async with mem.async_session() as session:
        conversation = await session.get(mem.Conversation, conv.id)
        assert conversation.asesor_asignado_id == "asesor1"  # nada se sobrescribió


async def test_conflicto_opportunity_version_en_resultado():
    negocio, canal = await _negocio_con_canal("cut5", "20000000005")
    telefono = "51900200005"
    conv, opp = await _abrir_conversacion(negocio, canal, telefono)

    assert await mem.intentar_cambiar_resultado_opportunity(opp.id, 0, {"resultado": "agendado"})
    ok = await mem.intentar_cambiar_resultado_opportunity(opp.id, 0, {"resultado": "no_interesado"})
    assert not ok
    async with mem.async_session() as session:
        opportunity = await session.get(mem.Opportunity, opp.id)
        assert opportunity.resultado == "agendado"  # nada se sobrescribió


async def test_rollback_completo_si_version_no_coincide_en_venta():
    """§12 — si el chequeo de version falla, NADA se toca: ni Opportunity, ni
    LineaVenta, ni Conversation, ni Lead."""
    negocio, canal = await _negocio_con_canal("cut6", "20000000006")
    telefono = "51900200006"
    conv, opp = await _abrir_conversacion(negocio, canal, telefono)
    await mem.actualizar_lead(telefono, negocio_id=negocio["id"], nombre="Cliente cut6")

    ok = await mem.cerrar_opportunity_con_venta(
        opp.id, 99, [{"producto": "X"}], {"resultado": "vendido"},
    )
    assert not ok
    async with mem.async_session() as session:
        from sqlalchemy import select
        opportunity = await session.get(mem.Opportunity, opp.id)
        assert opportunity.resultado is None
        assert opportunity.version == 0
        lineas = (await session.execute(select(mem.LineaVenta).where(mem.LineaVenta.opportunity_id == opp.id))).scalars().all()
        assert lineas == []
        lead = await session.get(mem.Lead, telefono)
        assert lead.version == 0


# ---------------------------------------------------------------------------
# 9/10 — ownership: mismo Negocio vs Negocio cruzado
# ---------------------------------------------------------------------------

async def test_resolver_opportunity_operable_ownership_correcto():
    negocio, canal = await _negocio_con_canal("cut7", "20000000007")
    telefono = "51900200007"
    conv, opp = await _abrir_conversacion(negocio, canal, telefono)
    await mem.intentar_asignar_conversation(conv.id, 0, "asesor1")

    resuelto = await mem.resolver_opportunity_operable(opp.id, negocio["id"])
    assert resuelto is not None
    assert resuelto["asesor_asignado"] == "asesor1"
    assert resuelto["version"] == 0


async def test_resolver_opportunity_operable_404_si_negocio_cruzado():
    negocio_a, canal_a = await _negocio_con_canal("cut8a", "20000000008")
    negocio_b, _ = await _negocio_con_canal("cut8b", "20000000009")
    conv, opp = await _abrir_conversacion(negocio_a, canal_a, "51900200008")

    assert await mem.resolver_opportunity_operable(opp.id, negocio_b["id"]) is None
    assert await mem.resolver_opportunity_operable(opp.id, negocio_a["id"]) is not None


async def test_resolver_conversation_operable_404_si_negocio_cruzado():
    negocio_a, canal_a = await _negocio_con_canal("cut9a", "20000000010")
    negocio_b, _ = await _negocio_con_canal("cut9b", "20000000011")
    conv, opp = await _abrir_conversacion(negocio_a, canal_a, "51900200009")

    assert await mem.resolver_conversation_operable(conv.id, negocio_b["id"]) is None
    assert await mem.resolver_conversation_operable(conv.id, negocio_a["id"]) is not None


# ---------------------------------------------------------------------------
# 12/13 — delegación legacy y no-dependencia del endpoint legacy
# ---------------------------------------------------------------------------

async def test_legacy_delega_correctamente_hacia_opportunity_via_puente():
    """Simula lo que hace el router legacy `/lead/{telefono}/resultado`: el
    gate de concurrencia sigue siendo Lead.version, pero la escritura real
    cae sobre Opportunity — resuelto vía `resolver_ids_operables_por_telefono`
    (mismo puente que usa dashboard.py)."""
    negocio, canal = await _negocio_con_canal("cut10", "20000000012")
    telefono = "51900200010"
    conv, opp = await _abrir_conversacion(negocio, canal, telefono)
    await mem.actualizar_lead(telefono, negocio_id=negocio["id"], nombre="Cliente cut10")

    assert await mem.intentar_avanzar_version(telefono, 0)  # gate legacy, como haría el router
    ids = await mem.resolver_ids_operables_por_telefono(telefono)
    assert ids["opportunity_id"] == opp.id
    assert ids["opportunity_version"] == 0  # todavía no tocado por el camino nuevo

    ok = await mem.intentar_cambiar_resultado_opportunity(ids["opportunity_id"], ids["opportunity_version"], {"resultado": "agendado"})
    assert ok

    async with mem.async_session() as session:
        opportunity = await session.get(mem.Opportunity, opp.id)
        lead = await session.get(mem.Lead, telefono)
        assert opportunity.resultado == "agendado"  # fuente de verdad: Opportunity
        assert lead.resultado == "agendado"  # sincronización mínima hacia Lead
        # version == 2, no 1: el gate legacy (intentar_avanzar_version) ya
        # avanzó una vez (0→1) y la sincronización de la escritura delegada
        # avanza otra vez, incondicional (1→2) — dos incrementos reales para
        # una sola acción humana, inofensivo (el número solo se usa para
        # comparar igualdad, nunca su magnitud) pero documentado a propósito
        # para que no se lea como un bug la próxima vez que se toque esto.
        assert lead.version == 2


async def test_escritura_via_lead_version_no_pisa_en_silencio_un_cambio_hecho_por_opportunity():
    """La razón de ser de sincronizar Lead.version incondicionalmente (cutover
    real §2): si Nueva Experiencia escribe primero sobre Opportunity, un
    cliente legacy con una Lead.version vieja debe recibir 409, no
    sobrescribir en silencio."""
    negocio, canal = await _negocio_con_canal("cut11", "20000000013")
    telefono = "51900200011"
    conv, opp = await _abrir_conversacion(negocio, canal, telefono)
    await mem.actualizar_lead(telefono, negocio_id=negocio["id"], nombre="Cliente cut11")

    version_legacy_vieja = 0  # la que "cargó" el panel legacy antes de que NE escribiera

    # Nueva Experiencia escribe primero, directo sobre Opportunity.
    assert await mem.intentar_cambiar_resultado_opportunity(opp.id, 0, {"resultado": "vendido"})

    # El cliente legacy, con su version vieja, intenta escribir después.
    assert not await mem.intentar_avanzar_version(telefono, version_legacy_vieja)


async def test_nueva_experiencia_no_depende_de_lead_version_para_operar():
    """§13 — dos escrituras sucesivas de Nueva Experiencia sobre la misma
    Opportunity funcionan usando solo opportunity_version, sin que exista
    ningún Lead en absoluto."""
    negocio, canal = await _negocio_con_canal("cut12", "20000000014")
    telefono = "51900200012"
    conv, opp = await _abrir_conversacion(negocio, canal, telefono)

    assert await mem.intentar_cambiar_resultado_opportunity(opp.id, 0, {"resultado": "agendado"})
    assert await mem.intentar_cambiar_resultado_opportunity(opp.id, 1, {"resultado": "no_interesado"})
    async with mem.async_session() as session:
        assert await session.get(mem.Lead, telefono) is None


# ---------------------------------------------------------------------------
# 11 — Tenant 002 sobre el camino nuevo específicamente
# ---------------------------------------------------------------------------

async def test_tenant_002_camino_nuevo_no_cruza_resultado_venta_ni_asignacion():
    """Repite el criterio de Tenant 002 (Cálidda no es un caso especial),
    esta vez ejercitando las 3 funciones atómicas nuevas directamente, con
    Negocio A y Negocio B compartiendo el mismo teléfono."""
    negocio_a, canal_a = await _negocio_con_canal("cut13a", "20000000015")
    negocio_b, canal_b = await _negocio_con_canal("cut13b", "20000000016")
    telefono = "51900200013"

    conv_a, opp_a = await _abrir_conversacion(negocio_a, canal_a, telefono)
    conv_b, opp_b = await _abrir_conversacion(negocio_b, canal_b, telefono)
    await mem.actualizar_lead(telefono, negocio_id=negocio_a["id"], nombre="Cliente A")

    assert await mem.intentar_cambiar_resultado_opportunity(opp_a.id, 0, {"resultado": "vendido"})
    assert await mem.intentar_asignar_conversation(conv_b.id, 0, "asesor_b")

    async with mem.async_session() as session:
        opp_a_db = await session.get(mem.Opportunity, opp_a.id)
        opp_b_db = await session.get(mem.Opportunity, opp_b.id)
        conv_a_db = await session.get(mem.Conversation, conv_a.id)
        conv_b_db = await session.get(mem.Conversation, conv_b.id)
        assert opp_a_db.resultado == "vendido"
        assert opp_b_db.resultado is None  # B no se contaminó con el cambio de A
        assert conv_a_db.asesor_asignado_id is None  # A no se contaminó con la asignación de B
        assert conv_b_db.asesor_asignado_id == "asesor_b"

        # La sincronización de Lead solo tocó el Lead de Negocio A (el único
        # que existe con ese negocio_id) — nunca "adivinó" ni tocó B.
        lead = await session.get(mem.Lead, telefono)
        assert lead.negocio_id == negocio_a["id"]
        assert lead.resultado == "vendido"


async def test_liberar_asignacion_via_conversation_respeta_negocio_y_guardia_vendido():
    negocio, canal = await _negocio_con_canal("cut14", "20000000017")
    telefono = "51900200014"
    conv, opp = await _abrir_conversacion(negocio, canal, telefono)
    await mem.intentar_asignar_conversation(conv.id, 0, "asesor1")

    # Con Opportunity vendida, no debe liberar.
    await mem.intentar_cambiar_resultado_opportunity(opp.id, 0, {"resultado": "vendido"})
    resultado = await mem.liberar_asignacion_via_conversation(conv.id, negocio["id"], autor="supervisor1")
    assert resultado is None
    async with mem.async_session() as session:
        conversation = await session.get(mem.Conversation, conv.id)
        assert conversation.asesor_asignado_id == "asesor1"  # no se tocó


async def test_liberar_asignacion_via_conversation_404_por_negocio_cruzado():
    negocio_a, canal_a = await _negocio_con_canal("cut15a", "20000000018")
    negocio_b, _ = await _negocio_con_canal("cut15b", "20000000019")
    conv, opp = await _abrir_conversacion(negocio_a, canal_a, "51900200015")

    resultado = await mem.liberar_asignacion_via_conversation(conv.id, negocio_b["id"], autor="x")
    assert resultado is None


# ---------------------------------------------------------------------------
# Hallazgo de la auditoría adversarial (§18): listar_leads_pipeline nunca
# filtraba por negocio_id — un admin/supervisor con alcance=todos veía el
# Pipeline de TODOS los Negocios, no solo el propio.
# ---------------------------------------------------------------------------

async def test_listar_leads_pipeline_no_cruza_negocios():
    negocio_a, canal_a = await _negocio_con_canal("cut16a", "20000000020")
    negocio_b, canal_b = await _negocio_con_canal("cut16b", "20000000021")
    await mem.actualizar_lead("51900200016", negocio_id=negocio_a["id"], nombre="Lead A")
    await mem.actualizar_lead("51900200017", negocio_id=negocio_b["id"], nombre="Lead B")

    leads_a, total_a = await mem.listar_leads_pipeline(negocio_id=negocio_a["id"])
    leads_b, total_b = await mem.listar_leads_pipeline(negocio_id=negocio_b["id"])

    assert total_a == 1 and [l["telefono"] for l in leads_a] == ["51900200016"]
    assert total_b == 1 and [l["telefono"] for l in leads_b] == ["51900200017"]


async def test_listar_lineas_venta_por_opportunity_scoped_por_negocio():
    negocio_a, canal_a = await _negocio_con_canal("cut18a", "20000000024")
    negocio_b, _ = await _negocio_con_canal("cut18b", "20000000025")
    conv, opp = await _abrir_conversacion(negocio_a, canal_a, "51900200019")
    await mem.cerrar_opportunity_con_venta(opp.id, 0, [{"producto": "Cocina 4 hornillas"}], {"resultado": "vendido"})

    lineas_a = await mem.listar_lineas_venta_por_opportunity(opp.id, negocio_a["id"])
    lineas_b = await mem.listar_lineas_venta_por_opportunity(opp.id, negocio_b["id"])
    assert [l["producto"] for l in lineas_a] == ["Cocina 4 hornillas"]
    assert lineas_b == []  # doble candado: negocio_id equivocado no ve nada


async def test_listar_leads_pipeline_resuelve_conversation_id_scoped_por_negocio():
    """El `id` de la fila (conversation_id) se resuelve con el mismo doble
    candado negocio_id+telefono — nunca podría devolver por error la
    Conversation de OTRO Negocio con el mismo teléfono."""
    negocio_a, canal_a = await _negocio_con_canal("cut17a", "20000000022")
    negocio_b, canal_b = await _negocio_con_canal("cut17b", "20000000023")
    telefono = "51900200018"
    conv_a, _ = await _abrir_conversacion(negocio_a, canal_a, telefono)
    conv_b, _ = await _abrir_conversacion(negocio_b, canal_b, telefono)
    await mem.actualizar_lead(telefono, negocio_id=negocio_a["id"], nombre="Cliente compartido")

    leads_a, _ = await mem.listar_leads_pipeline(negocio_id=negocio_a["id"])
    assert leads_a[0]["conversation_id"] == conv_a.id
    assert leads_a[0]["conversation_id"] != conv_b.id


# ---------------------------------------------------------------------------
# Cierre técnico pre-commit §1 — auditoría explícita de concurrencia
# Legacy ↔ Nueva Experiencia, paso a paso tal como pide la instrucción.
# ---------------------------------------------------------------------------

async def test_concurrencia_legacy_no_sobrescribe_silenciosamente_escritura_nueva():
    """Escenario exacto pedido en el cierre técnico:

    1. Un cliente legacy lee Lead.version = N.
    2. La Nueva Experiencia modifica la misma entidad lógica vía Opportunity.
    3. Esa operación sincroniza Lead.version (incondicional, misma transacción).
    4. El cliente legacy intenta escribir con su Lead.version = N (vieja).

    Se demuestra que el intento legacy falla (rowcount 0 → False, sin tocar
    nada) — no hay "conflicto silencioso": intentar_avanzar_version() ejecuta
    `UPDATE leads SET version=:nueva WHERE telefono=:t AND version=:N` en una
    sola sentencia (el chequeo y la escritura son atómicos a nivel de SQL,
    no hay ventana entre leer y escribir donde otra transacción pueda colarse
    — ver memory.py:intentar_avanzar_version). No hay locks explícitos
    porque no hacen falta: la condición WHERE ya sirve de control de
    concurrencia optimista sin retener nada."""
    negocio, canal = await _negocio_con_canal("cierre1", "20000000026")
    telefono = "51900200020"
    conv, opp = await _abrir_conversacion(negocio, canal, telefono)
    await mem.actualizar_lead(telefono, negocio_id=negocio["id"], nombre="Cliente cierre1")

    # 1. El cliente legacy "lee" Lead.version = N.
    async with mem.async_session() as session:
        lead_leido_por_legacy = await session.get(mem.Lead, telefono)
        N = lead_leido_por_legacy.version
    assert N == 0

    # 2. Nueva Experiencia modifica la Opportunity directamente (no pasa por
    #    Lead ni por intentar_avanzar_version en ningún momento).
    ok_nueva_experiencia = await mem.intentar_cambiar_resultado_opportunity(
        opp.id, 0, {"resultado": "vendido"}
    )
    assert ok_nueva_experiencia

    # 3. La sincronización ya ocurrió, en la MISMA transacción que el paso 2
    #    (ver intentar_cambiar_resultado_opportunity: _avanzar_version(lead)
    #    corre dentro del mismo `async with session.begin()` que el UPDATE
    #    de Opportunity — si cualquiera de los dos fallara, ambos hacen
    #    rollback juntos, nunca queda uno aplicado y el otro no).
    async with mem.async_session() as session:
        lead_tras_nueva_experiencia = await session.get(mem.Lead, telefono)
        opportunity_tras_nueva_experiencia = await session.get(mem.Opportunity, opp.id)
        assert lead_tras_nueva_experiencia.version > N  # Lead.version YA avanzó
        assert lead_tras_nueva_experiencia.resultado == "vendido"  # sincronizado
        assert opportunity_tras_nueva_experiencia.version == 1

    # 4. El cliente legacy intenta escribir con la version vieja (N) que
    #    leyó en el paso 1 — DEBE fallar, sin aplicar nada.
    ok_legacy = await mem.intentar_avanzar_version(telefono, N)
    assert ok_legacy is False

    # Confirmación explícita de "nada se tocó": ni el resultado ni la
    # version cambiaron por el intento legacy fallido.
    async with mem.async_session() as session:
        lead_final = await session.get(mem.Lead, telefono)
        assert lead_final.resultado == "vendido"  # sigue siendo lo que puso Nueva Experiencia
        assert lead_final.version == lead_tras_nueva_experiencia.version  # sin cambios


async def test_concurrencia_nueva_experiencia_no_sobrescribe_silenciosamente_escritura_legacy():
    """Dirección inversa del mismo escenario: si el legacy escribe primero
    (avanzando Lead.version Y, al delegar, Opportunity.version también),
    una Nueva Experiencia con `opportunity_version` vieja debe fallar —
    nunca se acepta una escritura basada en un estado que ya cambió,
    sin importar por cuál de los dos caminos llegó el cambio real."""
    negocio, canal = await _negocio_con_canal("cierre2", "20000000027")
    telefono = "51900200021"
    conv, opp = await _abrir_conversacion(negocio, canal, telefono)
    await mem.actualizar_lead(telefono, negocio_id=negocio["id"], nombre="Cliente cierre2")

    # Nueva Experiencia "lee" opportunity_version = 0.
    opportunity_version_leida_por_ne = 0

    # El legacy escribe primero (mismo camino que /lead/{telefono}/resultado:
    # gate de Lead.version + delegación hacia Opportunity).
    assert await mem.intentar_avanzar_version(telefono, 0)
    ids = await mem.resolver_ids_operables_por_telefono(telefono)
    assert ids["opportunity_version"] == 0  # todavía no tocada
    assert await mem.intentar_cambiar_resultado_opportunity(
        ids["opportunity_id"], ids["opportunity_version"], {"resultado": "agendado"}
    )

    # Nueva Experiencia intenta escribir con la opportunity_version vieja.
    ok_nueva_experiencia = await mem.intentar_cambiar_resultado_opportunity(
        opp.id, opportunity_version_leida_por_ne, {"resultado": "no_interesado"}
    )
    assert ok_nueva_experiencia is False

    async with mem.async_session() as session:
        opportunity_final = await session.get(mem.Opportunity, opp.id)
        assert opportunity_final.resultado == "agendado"  # lo que puso el legacy, intacto
