# tests/test_gate55_legacy_endpoints_cross_tenant.py — Gate 5.5, defensa en
# profundidad agregada en la auditoría adversarial final a 3 de los 4
# endpoints legacy de escritura (/lead/{telefono}/resultado, /venta,
# /asignar).
#
# Dos capas de ownership, cada una probada por separado:
#
#   1. `obtener_lead(telefono, negocio_id=usuario["negocio_id"])` — primera
#      línea de cada uno de estos 3 route handlers. `Lead.telefono` es PK
#      global (una sola fila por teléfono), así que esta capa YA hace
#      inalcanzable el cruce entre Negocios en el diseño actual: un usuario
#      de Negocio B nunca pasa de acá para un teléfono cuyo Lead pertenece a
#      Negocio A — 404 antes de llegar a cualquier otro código.
#
#   2. `resolver_opportunity_operable()`/`resolver_conversation_operable()`
#      — agregada en esta ronda ANTES de las funciones atómicas
#      (`intentar_cambiar_resultado_opportunity`, `cerrar_opportunity_con_
#      venta`, `intentar_asignar_conversation`), que no candadean por sí
#      mismas (confían en que quien las llama ya validó ownership, mismo
#      patrón que ya usan los endpoints NUEVOS). Es defensa en profundidad,
#      no el cierre de una brecha alcanzable hoy: el bridge legacy por
#      teléfono (`resolver_ids_operables_por_telefono`) es una capa de
#      compatibilidad, y no debe convertirse en fuente implícita de
#      autorización del recurso NUEVO que realmente se modifica — la capa 1
#      protege el recurso legacy (Lead), la capa 2 protege el recurso nuevo
#      (Opportunity/Conversation), y un endpoint no debe asumir que
#      aprobar la primera implica la segunda, incluso si hoy coinciden
#      siempre por construcción.
#
# Estos tests ejercitan la MISMA secuencia que corre dentro de los 3 route
# handlers de dashboard.py, sin necesitar un cliente HTTP — no existe
# infraestructura de TestClient en esta suite. Datos sintéticos únicamente.

import pytest

from agent import memory as mem


async def _negocio_con_canal(codigo: str, telefono_canal: str):
    negocio = await mem.crear_negocio(f"Negocio {codigo}", codigo)
    canal = await mem.crear_canal_whatsapp(nombre=f"Canal {codigo}", phone_number_id=telefono_canal, negocio_id=negocio["id"])
    return negocio, canal


async def _tenant_001_y_002_mismo_telefono(sufijo: str, telefono: str):
    """Setup común: Tenant 001 (negocio_a) y Tenant 002 (negocio_b), cada
    uno con su propio Contact/Conversation/Opportunity para el MISMO
    teléfono. El Lead global (PK por teléfono) queda anclado a Tenant 001 —
    exactamente el escenario donde el bridge legacy resuelve "el que ganó
    la fila", sin importar quién esté preguntando en realidad."""
    negocio_a, canal_a = await _negocio_con_canal(f"t1-{sufijo}-a", f"600000{sufijo}01")
    negocio_b, canal_b = await _negocio_con_canal(f"t1-{sufijo}-b", f"600000{sufijo}02")

    await mem.actualizar_lead(telefono, negocio_id=negocio_a["id"], nombre="Cliente compartido")
    conv_a, opp_a = await mem.resolver_conversation_activa(telefono, negocio_a["id"], canal_a["id"])
    conv_b, opp_b = await mem.resolver_conversation_activa(telefono, negocio_b["id"], canal_b["id"])

    return negocio_a, negocio_b, conv_a, opp_a, conv_b, opp_b


# ---------------------------------------------------------------------------
# Capa 1 — obtener_lead(telefono, negocio_id): candado del recurso LEGACY
# (Lead), primera línea de cada uno de los 3 route handlers. Por sí sola ya
# hace inalcanzable el escenario cross-tenant en el diseño actual.
# ---------------------------------------------------------------------------

async def test_capa_1_obtener_lead_rechaza_a_tenant_002_antes_de_cualquier_otro_codigo():
    telefono = "51900800008"
    negocio_a, negocio_b, conv_a, opp_a, conv_b, opp_b = await _tenant_001_y_002_mismo_telefono("cap1", telefono)

    # El Lead global (PK por telefono) quedó anclado a Tenant 001 — Tenant
    # 002 pidiéndolo con SU PROPIO negocio_id nunca lo obtiene, exactamente
    # el 404 que corta cada uno de los 3 route handlers en su primera línea.
    assert await mem.obtener_lead(telefono, negocio_id=negocio_b["id"]) is None
    assert await mem.obtener_lead(telefono, negocio_id=negocio_a["id"]) is not None


# ---------------------------------------------------------------------------
# Capa 2 — resolver_opportunity_operable()/resolver_conversation_operable():
# candado del recurso NUEVO (Opportunity/Conversation) que la escritura
# realmente modifica — defensa en profundidad agregada en esta ronda,
# independiente de la Capa 1.
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# B — /resultado
# ---------------------------------------------------------------------------

async def test_tenant_002_no_puede_cambiar_resultado_de_tenant_001():
    telefono = "51900800001"
    negocio_a, negocio_b, conv_a, opp_a, conv_b, opp_b = await _tenant_001_y_002_mismo_telefono("res", telefono)

    ids = await mem.resolver_ids_operables_por_telefono(telefono)
    assert ids["opportunity_id"] == opp_a.id  # el bridge encuentra el de Tenant 001

    # La revalidación de ownership (lo que ahora hace el endpoint) rechaza
    # el intento de Tenant 002 — ANTES de tocar la función atómica.
    autorizado = await mem.resolver_opportunity_operable(ids["opportunity_id"], negocio_b["id"])
    assert autorizado is None

    # Prueba negativa explícita del punto F: la función atómica nunca se
    # invoca en este camino (si `autorizado is None`, el endpoint corta acá
    # con 404) — se confirma releyendo el estado real, sin haberla llamado.
    async with mem.async_session() as session:
        opp_fila = await session.get(mem.Opportunity, opp_a.id)
        assert opp_fila.resultado is None  # intacta — nunca se escribió nada


async def test_tenant_001_si_puede_cambiar_su_propio_resultado():
    telefono = "51900800002"
    negocio_a, negocio_b, conv_a, opp_a, conv_b, opp_b = await _tenant_001_y_002_mismo_telefono("res2", telefono)

    ids = await mem.resolver_ids_operables_por_telefono(telefono)
    autorizado = await mem.resolver_opportunity_operable(ids["opportunity_id"], negocio_a["id"])
    assert autorizado is not None

    ok = await mem.intentar_cambiar_resultado_opportunity(
        ids["opportunity_id"], ids["opportunity_version"], {"resultado": "agendado"},
    )
    assert ok
    async with mem.async_session() as session:
        opp_fila = await session.get(mem.Opportunity, opp_a.id)
        assert opp_fila.resultado == "agendado"


# ---------------------------------------------------------------------------
# C — /venta
# ---------------------------------------------------------------------------

async def test_tenant_002_no_puede_registrar_venta_sobre_tenant_001():
    telefono = "51900800003"
    negocio_a, negocio_b, conv_a, opp_a, conv_b, opp_b = await _tenant_001_y_002_mismo_telefono("ven", telefono)

    ids = await mem.resolver_ids_operables_por_telefono(telefono)
    assert ids["opportunity_id"] == opp_a.id

    autorizado = await mem.resolver_opportunity_operable(ids["opportunity_id"], negocio_b["id"])
    assert autorizado is None  # Tenant 002 rechazado antes de cerrar_opportunity_con_venta

    async with mem.async_session() as session:
        from sqlalchemy import select
        lineas = (await session.execute(
            select(mem.LineaVenta).where(mem.LineaVenta.opportunity_id == opp_a.id)
        )).scalars().all()
        assert lineas == []  # ninguna LineaVenta creada
        opp_fila = await session.get(mem.Opportunity, opp_a.id)
        assert opp_fila.resultado is None  # Opportunity de Tenant 001 sin cambios


async def test_tenant_001_si_puede_registrar_venta_sobre_su_propia_opportunity():
    telefono = "51900800004"
    negocio_a, negocio_b, conv_a, opp_a, conv_b, opp_b = await _tenant_001_y_002_mismo_telefono("ven2", telefono)

    ids = await mem.resolver_ids_operables_por_telefono(telefono)
    autorizado = await mem.resolver_opportunity_operable(ids["opportunity_id"], negocio_a["id"])
    assert autorizado is not None

    ok = await mem.cerrar_opportunity_con_venta(
        ids["opportunity_id"], ids["opportunity_version"],
        [{"producto": "Terma X", "precio": 999, "marca": "M", "proveedor": "P"}],
        {"resultado": "vendido"},
    )
    assert ok
    async with mem.async_session() as session:
        from sqlalchemy import select
        lineas = (await session.execute(
            select(mem.LineaVenta).where(mem.LineaVenta.opportunity_id == opp_a.id)
        )).scalars().all()
        assert [l.producto for l in lineas] == ["Terma X"]


# ---------------------------------------------------------------------------
# D — /asignar
# ---------------------------------------------------------------------------

async def test_tenant_002_no_puede_asignar_asesor_en_conversation_de_tenant_001():
    telefono = "51900800005"
    negocio_a, negocio_b, conv_a, opp_a, conv_b, opp_b = await _tenant_001_y_002_mismo_telefono("asig", telefono)

    ids = await mem.resolver_ids_operables_por_telefono(telefono)
    assert ids["conversation_id"] == conv_a.id

    autorizado = await mem.resolver_conversation_operable(ids["conversation_id"], negocio_b["id"])
    assert autorizado is None  # Tenant 002 rechazado antes de intentar_asignar_conversation

    async with mem.async_session() as session:
        conv_fila = await session.get(mem.Conversation, conv_a.id)
        assert conv_fila.asesor_asignado_id is None  # Conversation de Tenant 001 sin cambios


async def test_tenant_001_si_puede_asignar_asesor_en_su_propia_conversation():
    telefono = "51900800006"
    negocio_a, negocio_b, conv_a, opp_a, conv_b, opp_b = await _tenant_001_y_002_mismo_telefono("asig2", telefono)

    ids = await mem.resolver_ids_operables_por_telefono(telefono)
    autorizado = await mem.resolver_conversation_operable(ids["conversation_id"], negocio_a["id"])
    assert autorizado is not None

    ok = await mem.intentar_asignar_conversation(ids["conversation_id"], ids["conversation_version"], "asesor_a")
    assert ok
    async with mem.async_session() as session:
        conv_fila = await session.get(mem.Conversation, conv_a.id)
        assert conv_fila.asesor_asignado_id == "asesor_a"


# ---------------------------------------------------------------------------
# F — ninguna ventana entre resolución por teléfono y el check de ownership
# ---------------------------------------------------------------------------

async def test_ids_resueltos_por_telefono_nunca_se_usan_sin_revalidar_ownership():
    """Prueba explícita del punto F: aunque `resolver_ids_operables_por_
    telefono` YA devolvió IDs reales y utilizables (no None, no un error),
    esos IDs por sí solos NO autorizan nada — solo `resolver_opportunity_
    operable`/`resolver_conversation_operable` con el negocio_id de la
    sesión autenticada lo hacen. Mismos IDs, dos negocio_id distintos, dos
    resultados distintos."""
    telefono = "51900800007"
    negocio_a, negocio_b, conv_a, opp_a, conv_b, opp_b = await _tenant_001_y_002_mismo_telefono("vent", telefono)
    ids = await mem.resolver_ids_operables_por_telefono(telefono)

    assert await mem.resolver_opportunity_operable(ids["opportunity_id"], negocio_a["id"]) is not None
    assert await mem.resolver_opportunity_operable(ids["opportunity_id"], negocio_b["id"]) is None
    assert await mem.resolver_conversation_operable(ids["conversation_id"], negocio_a["id"]) is not None
    assert await mem.resolver_conversation_operable(ids["conversation_id"], negocio_b["id"]) is None
