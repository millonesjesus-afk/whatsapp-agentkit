# tests/test_liberar_leads_inactivos.py — item #1 de los "ajustes" pedidos
# 2026-09-16 ("valida porque cuando escribi del numero 998130455 no atendio
# la ia..."), Opción 1 (liberación silenciosa, sin avisar al cliente — ver
# agent/memory.py::liberar_asignaciones_inactivas para el porqué completo).
#
# Cubre el criterio real de la función: lead con asesor_asignado + resultado
# no cerrado + último Mensaje (de cualquier origen) es del cliente
# (role="user") y ya pasó el umbral de horas -> se libera. Cualquier otra
# combinación no debe tocarse.

from datetime import datetime, timedelta
from sqlalchemy import select

from agent import memory as mem


async def _negocio_con_canal(codigo: str, telefono_canal: str):
    negocio = await mem.crear_negocio(f"Negocio {codigo}", codigo)
    canal = await mem.crear_canal_whatsapp(
        nombre=f"Canal {codigo}", phone_number_id=telefono_canal, negocio_id=negocio["id"],
    )
    return negocio, canal


async def _lead_asignado(telefono: str, negocio_id: str, canal_id: int, asesor: str, resultado: str | None = None):
    # resolver_conversation_activa crea Contact+Conversation — registrar_evento_lead
    # (que liberar_asignacion llama siempre) falla cerrado sin eso.
    await mem.resolver_conversation_activa(telefono, negocio_id, canal_id)
    await mem.actualizar_lead(telefono, nombre="Cliente Test", negocio_id=negocio_id)
    async with mem.async_session() as session:
        lead = await session.get(mem.Lead, telefono)
        lead.asesor_asignado = asesor
        lead.resultado = resultado
        await session.commit()


async def _mensaje(telefono: str, negocio_id: str, role: str, hace_horas: float):
    guardado = await mem.guardar_mensaje(telefono, role, "contenido de prueba", negocio_id)
    async with mem.async_session() as session:
        msg = await session.get(mem.Mensaje, guardado["id"])
        msg.timestamp = datetime.utcnow() - timedelta(hours=hace_horas)
        await session.commit()


# ---------------------------------------------------------------------------
# Caso positivo — último mensaje del cliente, viejo -> se libera
# ---------------------------------------------------------------------------

async def test_libera_lead_cuando_ultimo_mensaje_del_cliente_supera_el_umbral():
    negocio, canal = await _negocio_con_canal("g-lib-1", "40100000001")
    telefono = "51900500001"
    await _lead_asignado(telefono, negocio["id"], canal["id"], asesor="asesor1")
    await _mensaje(telefono, negocio["id"], "user", hace_horas=25)

    liberados = await mem.liberar_asignaciones_inactivas(horas=24)

    assert telefono in liberados
    async with mem.async_session() as session:
        lead = await session.get(mem.Lead, telefono)
        assert lead.asesor_asignado is None
        assert lead.pausado_manual is False


async def test_libera_lead_registra_evento_con_motivo_timeout_inactividad():
    negocio, canal = await _negocio_con_canal("g-lib-2", "40100000002")
    telefono = "51900500002"
    await _lead_asignado(telefono, negocio["id"], canal["id"], asesor="asesor1")
    await _mensaje(telefono, negocio["id"], "user", hace_horas=48)

    await mem.liberar_asignaciones_inactivas(horas=24)

    async with mem.async_session() as session:
        result = await session.execute(
            select(mem.EventoLead)
            .where(mem.EventoLead.negocio_id == negocio["id"], mem.EventoLead.tipo == "desasignado_automatico")
            .order_by(mem.EventoLead.creado.desc())
        )
        evento = result.scalars().first()
        assert evento is not None
        assert evento.payload["motivo"] == "timeout_inactividad"


# ---------------------------------------------------------------------------
# Casos negativos — no debe liberarse
# ---------------------------------------------------------------------------

async def test_no_libera_si_el_ultimo_mensaje_es_del_asesor():
    negocio, canal = await _negocio_con_canal("g-lib-3", "40100000003")
    telefono = "51900500003"
    await _lead_asignado(telefono, negocio["id"], canal["id"], asesor="asesor1")
    await _mensaje(telefono, negocio["id"], "user", hace_horas=48)
    await _mensaje(telefono, negocio["id"], "asesor", hace_horas=1)

    liberados = await mem.liberar_asignaciones_inactivas(horas=24)

    assert telefono not in liberados
    async with mem.async_session() as session:
        lead = await session.get(mem.Lead, telefono)
        assert lead.asesor_asignado == "asesor1"


async def test_no_libera_si_el_mensaje_del_cliente_aun_no_supera_el_umbral():
    negocio, canal = await _negocio_con_canal("g-lib-4", "40100000004")
    telefono = "51900500004"
    await _lead_asignado(telefono, negocio["id"], canal["id"], asesor="asesor1")
    await _mensaje(telefono, negocio["id"], "user", hace_horas=2)

    liberados = await mem.liberar_asignaciones_inactivas(horas=24)

    assert telefono not in liberados
    async with mem.async_session() as session:
        lead = await session.get(mem.Lead, telefono)
        assert lead.asesor_asignado == "asesor1"


async def test_no_libera_lead_sin_asesor_asignado():
    negocio, _ = await _negocio_con_canal("g-lib-5", "40100000005")
    telefono = "51900500005"
    await mem.actualizar_lead(telefono, nombre="Cliente Test", negocio_id=negocio["id"])
    await _mensaje(telefono, negocio["id"], "user", hace_horas=48)

    liberados = await mem.liberar_asignaciones_inactivas(horas=24)

    assert telefono not in liberados


async def test_no_libera_lead_con_resultado_vendido():
    negocio, canal = await _negocio_con_canal("g-lib-6", "40100000006")
    telefono = "51900500006"
    await _lead_asignado(telefono, negocio["id"], canal["id"], asesor="asesor1", resultado="vendido")
    await _mensaje(telefono, negocio["id"], "user", hace_horas=48)

    liberados = await mem.liberar_asignaciones_inactivas(horas=24)

    assert telefono not in liberados
    async with mem.async_session() as session:
        lead = await session.get(mem.Lead, telefono)
        assert lead.asesor_asignado == "asesor1"
