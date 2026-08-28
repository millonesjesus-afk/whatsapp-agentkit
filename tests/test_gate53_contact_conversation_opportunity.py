# tests/test_gate53_contact_conversation_opportunity.py — Gate 5.3: Contact/
# Conversation/Opportunity/LineaVenta/EventoLead/Mensaje, sobre el modelo
# nuevo. Datos sintéticos únicamente — ningún Tenant 002 real, ningún
# telefono/negocio hardcodeado como "el correcto" (mismo criterio que
# test_gate52_correcciones_h1h2h3.py).

import pytest

from agent import memory as mem


async def _negocio_con_canal(codigo: str, telefono_canal: str):
    """Crea un Negocio + un Canal real (Conversation.canal_id es NOT NULL,
    ninguna prueba puede crear una Conversation sin resolver un Canal)."""
    negocio = await mem.crear_negocio(f"Negocio {codigo}", codigo)
    canal = await mem.crear_canal_whatsapp(
        nombre=f"Canal {codigo}", phone_number_id=telefono_canal, negocio_id=negocio["id"],
    )
    return negocio, canal


async def _abrir_conversacion(negocio: dict, canal: dict, telefono: str):
    conversation, opportunity = await mem.resolver_conversation_activa(
        telefono, negocio["id"], canal["id"], unidad_id=canal.get("unidad_id"),
    )
    return conversation, opportunity


# ---------------------------------------------------------------------------
# Contact
# ---------------------------------------------------------------------------

async def test_contact_se_crea_con_negocio_id_explicito():
    negocio, canal = await _negocio_con_canal("cta1", "10000000001")
    conversation, _ = await _abrir_conversacion(negocio, canal, "51900100001")
    async with mem.async_session() as session:
        contact = await session.get(mem.Contact, conversation.contact_id)
        assert contact.negocio_id == negocio["id"]
        assert contact.telefono == "51900100001"


async def test_mismo_telefono_en_dos_negocios_da_dos_contacts_distintos():
    negocio_a, canal_a = await _negocio_con_canal("ctb1", "10000000002")
    negocio_b, canal_b = await _negocio_con_canal("ctb2", "10000000003")
    telefono_compartido = "51900100002"  # a propósito, el MISMO número en ambos

    conv_a, _ = await _abrir_conversacion(negocio_a, canal_a, telefono_compartido)
    conv_b, _ = await _abrir_conversacion(negocio_b, canal_b, telefono_compartido)

    assert conv_a.contact_id != conv_b.contact_id
    async with mem.async_session() as session:
        contact_a = await session.get(mem.Contact, conv_a.contact_id)
        contact_b = await session.get(mem.Contact, conv_b.contact_id)
        assert contact_a.negocio_id == negocio_a["id"]
        assert contact_b.negocio_id == negocio_b["id"]
        assert contact_a.telefono == contact_b.telefono == telefono_compartido
        assert contact_a.id != contact_b.id


async def test_contact_tiene_columnas_de_soft_delete():
    negocio, canal = await _negocio_con_canal("ctc1", "10000000004")
    conversation, _ = await _abrir_conversacion(negocio, canal, "51900100003")
    async with mem.async_session() as session:
        contact = await session.get(mem.Contact, conversation.contact_id)
        assert contact.eliminado_en is None
        assert contact.eliminado_por is None
        contact.eliminado_en = __import__("datetime").datetime.utcnow()
        contact.eliminado_por = "test"
        await session.commit()
    async with mem.async_session() as session:
        contact = await session.get(mem.Contact, conversation.contact_id)
        assert contact.eliminado_en is not None  # soft delete no borra la fila


# ---------------------------------------------------------------------------
# Conversation — resolución de identidad y DR-4
# ---------------------------------------------------------------------------

async def test_resolver_conversation_activa_es_idempotente_sin_dr4():
    negocio, canal = await _negocio_con_canal("cvd1", "10000000005")
    conv1, opp1 = await _abrir_conversacion(negocio, canal, "51900100004")
    conv2, opp2 = await _abrir_conversacion(negocio, canal, "51900100004")
    assert conv1.id == conv2.id
    assert opp1.id == opp2.id


async def test_dr4_no_venta_abre_conversation_nueva_y_preserva_la_anterior():
    """DR-4: Contact recurrente tras cierre NO-venta → nueva Conversation.
    La Conversation anterior queda intacta (cerrada, no borrada)."""
    negocio, canal = await _negocio_con_canal("cve1", "10000000006")
    telefono = "51900100005"
    conv1, opp1 = await _abrir_conversacion(negocio, canal, telefono)

    # Simula: asesor asignado + Opportunity cerrada "no_interesado" (no-venta)
    async with mem.async_session() as session:
        c = await session.get(mem.Conversation, conv1.id)
        c.asesor_asignado_id = "asesor1"
        o = await session.get(mem.Opportunity, opp1.id)
        o.resultado = "no_interesado"
        await session.commit()

    conv2, opp2 = await _abrir_conversacion(negocio, canal, telefono)

    assert conv2.id != conv1.id
    assert opp2.id != opp1.id
    assert conv2.contact_id == conv1.contact_id  # mismo Contact
    async with mem.async_session() as session:
        anterior = await session.get(mem.Conversation, conv1.id)
        assert anterior.estado == "cerrada"  # no se borró, se cerró
        nueva = await session.get(mem.Conversation, conv2.id)
        assert nueva.estado == "activa"
        assert nueva.asesor_asignado_id is None  # arranca limpia


async def test_dr4_vendido_no_reabre_automaticamente():
    """DR-4: 'vendido' NUNCA reabre solo — el mensaje entra a la Conversation
    existente para revisión humana (Human Decision Gate)."""
    negocio, canal = await _negocio_con_canal("cvf1", "10000000007")
    telefono = "51900100006"
    conv1, opp1 = await _abrir_conversacion(negocio, canal, telefono)

    async with mem.async_session() as session:
        c = await session.get(mem.Conversation, conv1.id)
        c.pausado_manual = True
        o = await session.get(mem.Opportunity, opp1.id)
        o.resultado = "vendido"
        await session.commit()

    conv2, opp2 = await _abrir_conversacion(negocio, canal, telefono)

    assert conv2.id == conv1.id  # NO se abrió una nueva
    assert opp2.id == opp1.id


async def test_conversation_hereda_unidad_id_del_canal():
    negocio = await mem.crear_negocio("Negocio Unidad", "cvg1")
    unidad = await mem.crear_unidad_de_negocio(negocio["id"], "Unidad Uno", "u1")
    canal = await mem.crear_canal_whatsapp(
        nombre="Canal con unidad", phone_number_id="10000000008",
        negocio_id=negocio["id"], unidad_id=unidad["id"],
    )
    conversation, opportunity = await _abrir_conversacion(negocio, canal, "51900100007")
    assert conversation.unidad_id == unidad["id"]
    assert opportunity.unidad_id == unidad["id"]  # heredado de Conversation


# ---------------------------------------------------------------------------
# Opportunity — DR-3, cardinalidad 1:0..N
# ---------------------------------------------------------------------------

async def test_opportunity_es_1_a_n_secuencial_por_conversation():
    """No se crea una Opportunity nueva dentro de una Conversation ya
    existente (sin evidencia de necesidad, Diseño Técnico Gate 5.3 §6) —
    solo aparece una segunda Opportunity cuando DR-4 abre una Conversation
    nueva."""
    negocio, canal = await _negocio_con_canal("op1", "10000000009")
    telefono = "51900100008"
    conv1, opp1 = await _abrir_conversacion(negocio, canal, telefono)

    async with mem.async_session() as session:
        c = await session.get(mem.Conversation, conv1.id)
        c.asesor_asignado_id = "asesor1"
        o = await session.get(mem.Opportunity, opp1.id)
        o.resultado = "no_califica"
        await session.commit()

    conv2, opp2 = await _abrir_conversacion(negocio, canal, telefono)
    assert conv2.id != conv1.id

    async with mem.async_session() as session:
        from sqlalchemy import select
        opps_conv1 = (await session.execute(
            select(mem.Opportunity).where(mem.Opportunity.conversation_id == conv1.id)
        )).scalars().all()
        assert len(opps_conv1) == 1  # nunca 2 dentro de la misma Conversation


async def test_opportunity_negocio_id_y_unidad_id_se_asignan_server_side():
    """negocio_id/unidad_id de Opportunity derivan de Conversation, nunca de
    un parámetro externo — resolver_conversation_activa no acepta esos
    campos como parte de un payload de cliente."""
    negocio, canal = await _negocio_con_canal("op2", "10000000010")
    conversation, opportunity = await _abrir_conversacion(negocio, canal, "51900100009")
    assert opportunity.negocio_id == conversation.negocio_id == negocio["id"]


# ---------------------------------------------------------------------------
# LineaVenta — regla crítica: nunca telefono, siempre opportunity_id+negocio_id
# ---------------------------------------------------------------------------

async def test_cerrar_opportunity_con_venta_no_destruye_lineas_de_otra_opportunity():
    """Test de regresión directo del hallazgo original: una venta de la
    Opportunity A NUNCA borra las líneas de la Opportunity B, aunque
    compartan el mismo Contact/teléfono (dos ciclos comerciales sucesivos)."""
    negocio, canal = await _negocio_con_canal("lv1", "10000000011")
    telefono = "51900100010"
    conv1, opp1 = await _abrir_conversacion(negocio, canal, telefono)

    ok1 = await mem.cerrar_opportunity_con_venta(
        opp1.id, 0, lineas=[{"producto": "Cocina A", "precio": "100"}],
        campos={"resultado": "vendido"},
    )
    assert ok1 is True

    # DR-4 no aplica tras "vendido" automáticamente — abrimos la 2da
    # Opportunity a mano, simulando una recompra real (ciclo comercial nuevo).
    async with mem.async_session() as session:
        c = await session.get(mem.Conversation, conv1.id)
        c.estado = "cerrada"
        opp2 = mem.Opportunity(
            negocio_id=negocio["id"], conversation_id=conv1.id, contact_id=conv1.contact_id,
        )
        session.add(opp2)
        await session.commit()
        await session.refresh(opp2)

    ok2 = await mem.cerrar_opportunity_con_venta(
        opp2.id, 0, lineas=[{"producto": "Terma B", "precio": "200"}],
        campos={"resultado": "vendido"},
    )
    assert ok2 is True

    async with mem.async_session() as session:
        from sqlalchemy import select
        lineas_opp1 = (await session.execute(
            select(mem.LineaVenta).where(mem.LineaVenta.opportunity_id == opp1.id)
        )).scalars().all()
        lineas_opp2 = (await session.execute(
            select(mem.LineaVenta).where(mem.LineaVenta.opportunity_id == opp2.id)
        )).scalars().all()
        assert len(lineas_opp1) == 1 and lineas_opp1[0].producto == "Cocina A"
        assert len(lineas_opp2) == 1 and lineas_opp2[0].producto == "Terma B"


async def test_lineaventa_no_tiene_columna_telefono():
    """Regla crítica del Gate: LineaVenta ya no tiene `telefono` como
    identidad — confirma que el modelo ORM no expone ese atributo."""
    assert not hasattr(mem.LineaVenta, "telefono")


async def test_venta_de_negocio_a_no_cruza_lineas_con_negocio_b_mismo_telefono():
    """Tenant 002 — LineaVenta: mismo teléfono en dos Negocios, cada venta
    queda aislada por opportunity_id+negocio_id."""
    negocio_a, canal_a = await _negocio_con_canal("lvb1", "10000000012")
    negocio_b, canal_b = await _negocio_con_canal("lvb2", "10000000013")
    telefono = "51900100011"

    _, opp_a = await _abrir_conversacion(negocio_a, canal_a, telefono)
    _, opp_b = await _abrir_conversacion(negocio_b, canal_b, telefono)

    await mem.cerrar_opportunity_con_venta(opp_a.id, 0, [{"producto": "Prod A"}], {"resultado": "vendido"})
    await mem.cerrar_opportunity_con_venta(opp_b.id, 0, [{"producto": "Prod B"}], {"resultado": "vendido"})

    async with mem.async_session() as session:
        from sqlalchemy import select
        lineas_a = (await session.execute(
            select(mem.LineaVenta).where(mem.LineaVenta.negocio_id == negocio_a["id"])
        )).scalars().all()
        lineas_b = (await session.execute(
            select(mem.LineaVenta).where(mem.LineaVenta.negocio_id == negocio_b["id"])
        )).scalars().all()
        assert [l.producto for l in lineas_a] == ["Prod A"]
        assert [l.producto for l in lineas_b] == ["Prod B"]


# ---------------------------------------------------------------------------
# EventoLead — aislamiento por Negocio/Conversation, nunca telefono solo
# ---------------------------------------------------------------------------

async def test_eventolead_no_tiene_columna_telefono():
    assert not hasattr(mem.EventoLead, "telefono")


async def test_registrar_y_listar_eventos_via_telefono_resuelve_por_conversation():
    negocio, canal = await _negocio_con_canal("ev1", "10000000014")
    telefono = "51900100012"
    await mem.actualizar_lead(telefono, negocio_id=negocio["id"], nombre="Test")
    await _abrir_conversacion(negocio, canal, telefono)

    await mem.registrar_evento_lead(telefono, tipo="asignado", descripcion="Asignó a X", autor="admin")
    eventos = await mem.listar_eventos_lead(telefono)
    assert len(eventos) == 1
    assert eventos[0]["tipo"] == "asignado"


async def test_eventolead_aislado_por_negocio_id_en_consulta_directa():
    """Aislamiento real de EventoLead: dos Negocios, cada uno con su propio
    Contact/Conversation (teléfonos DISTINTOS — ver nota de la limitación
    conocida abajo), cada evento queda atado únicamente a su negocio_id/
    conversation_id."""
    negocio_a, canal_a = await _negocio_con_canal("evb1", "10000000015")
    negocio_b, canal_b = await _negocio_con_canal("evb2", "10000000016")

    await mem.actualizar_lead("51900100013", negocio_id=negocio_a["id"], nombre="A")
    await _abrir_conversacion(negocio_a, canal_a, "51900100013")
    await mem.actualizar_lead("51900100014", negocio_id=negocio_b["id"], nombre="B")
    await _abrir_conversacion(negocio_b, canal_b, "51900100014")

    await mem.registrar_evento_lead("51900100013", tipo="asignado", descripcion="Evento en A", autor="admin_a")
    await mem.registrar_evento_lead("51900100014", tipo="asignado", descripcion="Evento en B", autor="admin_b")

    async with mem.async_session() as session:
        from sqlalchemy import select
        eventos_a = (await session.execute(
            select(mem.EventoLead).where(mem.EventoLead.negocio_id == negocio_a["id"])
        )).scalars().all()
        eventos_b = (await session.execute(
            select(mem.EventoLead).where(mem.EventoLead.negocio_id == negocio_b["id"])
        )).scalars().all()
        assert [e.descripcion for e in eventos_a] == ["Evento en A"]
        assert [e.descripcion for e in eventos_b] == ["Evento en B"]


async def test_limitacion_conocida_bridge_telefono_solo_sirve_al_negocio_del_lead():
    """LIMITACIÓN CONOCIDA, no introducida por Gate 5.3 — heredada de la
    corrección H1 de Gate 5.2: `registrar_evento_lead`/`listar_eventos_lead`/
    `guardar_mensaje` resuelven negocio_id/conversation_id vía `Lead.telefono`,
    que sigue siendo PK GLOBAL (no compuesta con negocio_id todavía — esa
    migración de identidad es explícitamente Gate 5.4+). Si el MISMO teléfono
    tuviera Lead en dos Negocios a la vez, estas funciones basadas en
    `telefono` solo pueden resolver correctamente al Negocio que "ganó" la
    fila global de Lead — la primera vez que se llama `actualizar_lead` para
    ese teléfono. Los datos de Contact/Conversation/Opportunity/EventoLead/
    LineaVenta en sí SIGUEN aislados correctamente cuando se consultan por su
    propio id (ver test_eventolead_aislado_por_negocio_id_en_consulta_directa,
    test_tenant_002_aislamiento_completo_mismo_telefono) — la limitación es
    específica de las 3 funciones que todavía usan `telefono` como puente de
    interfaz pública, documentada explícitamente para que no se lea como una
    fuga silenciosa si alguien la redescubre después."""
    negocio_a, canal_a = await _negocio_con_canal("evb3", "10000000024")
    negocio_b, canal_b = await _negocio_con_canal("evb4", "10000000025")
    telefono = "51900100020"

    await mem.actualizar_lead(telefono, negocio_id=negocio_a["id"], nombre="Primero")
    conv_a, _ = await _abrir_conversacion(negocio_a, canal_a, telefono)
    conv_b, _ = await _abrir_conversacion(negocio_b, canal_b, telefono)

    await mem.registrar_evento_lead(telefono, tipo="asignado", descripcion="Vía bridge telefono", autor="admin")

    async with mem.async_session() as session:
        from sqlalchemy import select
        eventos = (await session.execute(select(mem.EventoLead))).scalars().all()
        assert len(eventos) == 1
        # Resuelve al Negocio A — el que "ganó" la fila global de Lead.
        assert eventos[0].negocio_id == negocio_a["id"]
        assert eventos[0].conversation_id == conv_a.id
        assert eventos[0].conversation_id != conv_b.id


# ---------------------------------------------------------------------------
# Mensaje — conversation_id
# ---------------------------------------------------------------------------

async def test_guardar_mensaje_resuelve_conversation_id_internamente():
    negocio, canal = await _negocio_con_canal("ms1", "10000000017")
    telefono = "51900100014"
    conversation, _ = await _abrir_conversacion(negocio, canal, telefono)
    await mem.actualizar_lead(telefono, negocio_id=negocio["id"], nombre="Test")

    mensaje = await mem.guardar_mensaje(telefono, "user", "Hola")
    assert mensaje["conversation_id"] == conversation.id


async def test_guardar_mensaje_nunca_acepta_conversation_id_como_parametro():
    """El mismo criterio ya usado para negocio_id (H1, Gate 5.2): guardar_mensaje
    nunca recibe conversation_id como argumento externo — lo resuelve siempre
    internamente, para que no sea una ruta de resolución manipulable."""
    import inspect
    firma = inspect.signature(mem.guardar_mensaje)
    assert "conversation_id" not in firma.parameters


# ---------------------------------------------------------------------------
# Concurrencia — DR-1: version independiente Conversation/Opportunity
# ---------------------------------------------------------------------------

async def test_version_de_conversation_y_opportunity_son_independientes():
    negocio, canal = await _negocio_con_canal("cc1", "10000000018")
    conversation, opportunity = await _abrir_conversacion(negocio, canal, "51900100015")
    assert conversation.version == 0
    assert opportunity.version == 0

    ok = await mem.intentar_avanzar_version_opportunity(opportunity.id, 0)
    assert ok is True
    async with mem.async_session() as session:
        conv_fresca = await session.get(mem.Conversation, conversation.id)
        assert conv_fresca.version == 0  # avanzar Opportunity NO tocó Conversation


async def test_conflicto_409_en_opportunity_con_version_vieja():
    negocio, canal = await _negocio_con_canal("cc2", "10000000019")
    _, opportunity = await _abrir_conversacion(negocio, canal, "51900100016")
    assert await mem.intentar_avanzar_version_opportunity(opportunity.id, 0) is True
    # version vieja (0) — alguien más ya avanzó a 1
    assert await mem.intentar_avanzar_version_opportunity(opportunity.id, 0) is False


async def test_cerrar_opportunity_con_venta_es_atomico_no_aplica_nada_si_version_no_coincide():
    """Corrección del defecto preexistente: si el chequeo de versión falla,
    NO se toca ni Opportunity ni LineaVenta ni Conversation — todo o nada,
    en una sola transacción."""
    negocio, canal = await _negocio_con_canal("cc3", "10000000020")
    conversation, opportunity = await _abrir_conversacion(negocio, canal, "51900100017")

    resultado = await mem.cerrar_opportunity_con_venta(
        opportunity.id, version_esperada=99,  # version incorrecta a propósito
        lineas=[{"producto": "No debería guardarse"}], campos={"resultado": "vendido"},
    )
    assert resultado is False

    async with mem.async_session() as session:
        from sqlalchemy import select
        opp_fresca = await session.get(mem.Opportunity, opportunity.id)
        assert opp_fresca.resultado is None  # nada se aplicó
        assert opp_fresca.version == 0
        lineas = (await session.execute(
            select(mem.LineaVenta).where(mem.LineaVenta.opportunity_id == opportunity.id)
        )).scalars().all()
        assert lineas == []
        conv_fresca = await session.get(mem.Conversation, conversation.id)
        assert conv_fresca.pausado_manual is False


async def test_cerrar_opportunity_con_venta_pausa_conversation_al_vender():
    negocio, canal = await _negocio_con_canal("cc4", "10000000021")
    conversation, opportunity = await _abrir_conversacion(negocio, canal, "51900100018")
    ok = await mem.cerrar_opportunity_con_venta(
        opportunity.id, 0, lineas=[{"producto": "X"}], campos={"resultado": "vendido"},
    )
    assert ok is True
    async with mem.async_session() as session:
        conv_fresca = await session.get(mem.Conversation, conversation.id)
        assert conv_fresca.pausado_manual is True
        assert conv_fresca.version == 1  # avanzó como efecto automático, sin exigir su version


# ---------------------------------------------------------------------------
# Tenant 002 — Negocio 002 sintético, aislamiento completo de punta a punta
# ---------------------------------------------------------------------------

async def test_listar_conversaciones_activas_solo_muestra_activas_del_negocio():
    """Bandeja de Conversaciones (Diseño Técnico §18): lista Conversation,
    no Opportunity — un Contact con Opportunities secuenciales (DR-4) sigue
    apareciendo como UNA sola fila mientras su Conversation esté activa."""
    negocio_a, canal_a = await _negocio_con_canal("bnd1", "10000000026")
    negocio_b, canal_b = await _negocio_con_canal("bnd2", "10000000027")

    await _abrir_conversacion(negocio_a, canal_a, "51900100021")
    await _abrir_conversacion(negocio_a, canal_a, "51900100022")
    await _abrir_conversacion(negocio_b, canal_b, "51900100023")

    filas_a, total_a = await mem.listar_conversaciones_activas(negocio_a["id"])
    filas_b, total_b = await mem.listar_conversaciones_activas(negocio_b["id"])

    assert total_a == 2
    assert total_b == 1
    assert {f["telefono"] for f in filas_a} == {"51900100021", "51900100022"}
    assert {f["telefono"] for f in filas_b} == {"51900100023"}


async def test_listar_conversaciones_activas_no_duplica_por_multiples_opportunities():
    """Confirma explícitamente la razón de ser de este endpoint: aunque el
    Contact ya haya tenido una Conversation cerrada (con su propia
    Opportunity), la Bandeja solo cuenta la ACTIVA — nunca 2 filas para el
    mismo Contact."""
    negocio, canal = await _negocio_con_canal("bnd3", "10000000028")
    telefono = "51900100024"
    conv1, opp1 = await _abrir_conversacion(negocio, canal, telefono)
    async with mem.async_session() as session:
        c = await session.get(mem.Conversation, conv1.id)
        c.asesor_asignado_id = "asesor1"
        o = await session.get(mem.Opportunity, opp1.id)
        o.resultado = "no_interesado"
        await session.commit()
    await _abrir_conversacion(negocio, canal, telefono)  # DR-4 abre una nueva

    filas, total = await mem.listar_conversaciones_activas(negocio["id"])
    assert total == 1
    assert filas[0]["telefono"] == telefono


async def test_ownership_campana_y_canal_no_cruzan_negocios():
    """Corrección pequeña de seguridad: obtener_campana/obtener_canal_whatsapp
    (usadas por los chequeos de ownership de dashboard.py) devuelven
    negocio_id correcto para que la ruta pueda rechazar con 404 cuando no
    coincide con el negocio_id del admin que llama."""
    negocio_a = await mem.crear_negocio("Negocio Own A", "own-a")
    negocio_b = await mem.crear_negocio("Negocio Own B", "own-b")
    campana = await mem.crear_campana(
        nombre="Promo A", tipo_deteccion="texto_saludo", patron="hola",
        negocio_id=negocio_a["id"],
    )
    canal = await mem.crear_canal_whatsapp(
        nombre="Canal A", phone_number_id="10000000029", negocio_id=negocio_a["id"],
    )
    campana_leida = await mem.obtener_campana(campana["id"])
    canal_leido = await mem.obtener_canal_whatsapp(canal["id"])
    assert campana_leida["negocio_id"] == negocio_a["id"] != negocio_b["id"]
    assert canal_leido["negocio_id"] == negocio_a["id"] != negocio_b["id"]


async def test_tenant_002_aislamiento_completo_mismo_telefono():
    """Negocio 002 (sintético) puede operar con el mismo teléfono que
    Cálidda/Negocio A sin cruzar nunca Contact, Conversation, Opportunity,
    Mensaje, Evento ni Venta."""
    negocio_1, canal_1 = await _negocio_con_canal("t002-1", "10000000022")
    negocio_2, canal_2 = await _negocio_con_canal("t002-2", "10000000023")
    telefono = "51900100019"

    conv1, opp1 = await _abrir_conversacion(negocio_1, canal_1, telefono)
    conv2, opp2 = await _abrir_conversacion(negocio_2, canal_2, telefono)

    assert conv1.id != conv2.id and opp1.id != opp2.id
    assert conv1.negocio_id == negocio_1["id"]
    assert conv2.negocio_id == negocio_2["id"]

    await mem.actualizar_lead(telefono, negocio_id=negocio_1["id"], nombre="Cliente T002")
    m1 = await mem.guardar_mensaje(telefono, "user", "Mensaje en Negocio 1")
    assert m1["conversation_id"] == conv1.id  # resuelve por el Lead ya scoped a Negocio 1

    await mem.cerrar_opportunity_con_venta(opp1.id, 0, [{"producto": "P1"}], {"resultado": "vendido"})
    await mem.cerrar_opportunity_con_venta(opp2.id, 0, [{"producto": "P2"}], {"resultado": "vendido"})

    async with mem.async_session() as session:
        from sqlalchemy import select
        contacts = (await session.execute(
            select(mem.Contact).where(mem.Contact.telefono == telefono)
        )).scalars().all()
        assert len(contacts) == 2
        assert {c.negocio_id for c in contacts} == {negocio_1["id"], negocio_2["id"]}

        lineas_1 = (await session.execute(
            select(mem.LineaVenta).where(mem.LineaVenta.negocio_id == negocio_1["id"])
        )).scalars().all()
        lineas_2 = (await session.execute(
            select(mem.LineaVenta).where(mem.LineaVenta.negocio_id == negocio_2["id"])
        )).scalars().all()
        assert [l.producto for l in lineas_1] == ["P1"]
        assert [l.producto for l in lineas_2] == ["P2"]


# ---------------------------------------------------------------------------
# Historial estructural del Contact — obtener_contact_detalle /
# obtener_conversation_detalle / listar_eventos_de_conversation (Diseño
# Técnico Gate 5.3 §17: la ESTRUCTURA de datos, la UI queda para más adelante)
# ---------------------------------------------------------------------------

async def test_obtener_contact_detalle_lista_conversaciones_activas_y_cerradas():
    negocio, canal = await _negocio_con_canal("cdt1", "10000000030")
    telefono = "51900100025"
    conv1, opp1 = await _abrir_conversacion(negocio, canal, telefono)
    async with mem.async_session() as session:
        c = await session.get(mem.Conversation, conv1.id)
        c.asesor_asignado_id = "asesor1"
        o = await session.get(mem.Opportunity, opp1.id)
        o.resultado = "no_interesado"
        await session.commit()
    conv2, _ = await _abrir_conversacion(negocio, canal, telefono)  # DR-4 cierra conv1, abre conv2

    contact_id = conv2.contact_id
    detalle = await mem.obtener_contact_detalle(contact_id, negocio["id"])
    assert detalle is not None
    assert detalle["telefono"] == telefono
    ids_conversaciones = {c["id"] for c in detalle["conversaciones"]}
    assert ids_conversaciones == {conv1.id, conv2.id}
    estados = {c["id"]: c["estado"] for c in detalle["conversaciones"]}
    assert estados[conv1.id] == "cerrada"
    assert estados[conv2.id] == "activa"


async def test_obtener_contact_detalle_devuelve_none_si_negocio_no_coincide():
    negocio_a, canal_a = await _negocio_con_canal("cdt2", "10000000031")
    negocio_b, _ = await _negocio_con_canal("cdt3", "10000000032")
    conv, _ = await _abrir_conversacion(negocio_a, canal_a, "51900100026")
    assert await mem.obtener_contact_detalle(conv.contact_id, negocio_b["id"]) is None


async def test_obtener_conversation_detalle_incluye_opportunity_vigente():
    negocio, canal = await _negocio_con_canal("cdt4", "10000000033")
    conv, opp = await _abrir_conversacion(negocio, canal, "51900100027")
    async with mem.async_session() as session:
        o = await session.get(mem.Opportunity, opp.id)
        o.interes = "Balón de gas"
        await session.commit()

    detalle = await mem.obtener_conversation_detalle(conv.id, negocio["id"])
    assert detalle is not None
    assert detalle["opportunity_id"] == opp.id
    assert detalle["interes"] == "Balón de gas"
    # Gate 5.3 cutover real §8/§13 — obtener_conversation_detalle() se
    # extendió para ser el reemplazo completo de _dto_lead_detalle: forma
    # plana (telefono/nombre), no un objeto "contact" anidado.
    assert detalle["telefono"] == "51900100027"
    assert detalle["conversation_version"] == 0
    assert detalle["opportunity_version"] == 0


async def test_obtener_conversation_detalle_devuelve_none_si_negocio_no_coincide():
    negocio_a, canal_a = await _negocio_con_canal("cdt5", "10000000034")
    negocio_b, _ = await _negocio_con_canal("cdt6", "10000000035")
    conv, _ = await _abrir_conversacion(negocio_a, canal_a, "51900100028")
    assert await mem.obtener_conversation_detalle(conv.id, negocio_b["id"]) is None


async def test_listar_eventos_de_conversation_sirve_timeline_de_conversation_cerrada():
    negocio, canal = await _negocio_con_canal("cdt7", "10000000036")
    telefono = "51900100029"
    conv1, opp1 = await _abrir_conversacion(negocio, canal, telefono)
    await mem.actualizar_lead(telefono, negocio_id=negocio["id"], nombre="Cliente CDT7")
    await mem.registrar_evento_lead(telefono, "asignado", "Asignado a asesor1", autor="admin")
    async with mem.async_session() as session:
        c = await session.get(mem.Conversation, conv1.id)
        c.asesor_asignado_id = "asesor1"
        o = await session.get(mem.Opportunity, opp1.id)
        o.resultado = "no_interesado"
        await session.commit()
    await _abrir_conversacion(negocio, canal, telefono)  # DR-4 cierra conv1

    # listar_eventos_lead (puente por telefono) ya NO ve el evento de conv1 —
    # solo resuelve la Conversation ACTIVA. listar_eventos_de_conversation sí,
    # porque se pide por conversation_id directo, sin pasar por el puente.
    eventos_puente = await mem.listar_eventos_lead(telefono)
    eventos_directos = await mem.listar_eventos_de_conversation(conv1.id, negocio["id"])
    assert eventos_puente == []
    assert len(eventos_directos) == 1
    assert eventos_directos[0]["descripcion"] == "Asignado a asesor1"


async def test_listar_eventos_de_conversation_no_cruza_negocio_id():
    negocio_a, canal_a = await _negocio_con_canal("cdt8", "10000000037")
    negocio_b, _ = await _negocio_con_canal("cdt9", "10000000038")
    telefono = "51900100030"
    conv, _ = await _abrir_conversacion(negocio_a, canal_a, telefono)
    await mem.actualizar_lead(telefono, negocio_id=negocio_a["id"], nombre="Cliente CDT8")
    await mem.registrar_evento_lead(telefono, "asignado", "Asignado a asesor1", autor="admin")

    eventos_negocio_a = await mem.listar_eventos_de_conversation(conv.id, negocio_a["id"])
    eventos_negocio_b = await mem.listar_eventos_de_conversation(conv.id, negocio_b["id"])
    assert len(eventos_negocio_a) == 1
    assert eventos_negocio_b == []
