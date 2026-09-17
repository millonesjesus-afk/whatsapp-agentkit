# tests/test_inactividad_cliente.py — listar_leads_inactividad_cliente
# (2026-09-17, pedido explícito del usuario, investigado el estándar real
# de mercado: 2h para un reenganche suave, 15h para cerrar en silencio —
# ver agent/memory.py::listar_leads_inactividad_cliente para el porqué
# completo, y scripts/procesar_inactividad_clientes.py para quién manda el
# mensaje real).
#
# Cubre el criterio real de la función: lead SIN asesor asignado, SIN
# pausar, resultado no cerrado, cuyo último mensaje es de Gabi (nada
# pendiente de nuestro lado) y el ÚLTIMO MENSAJE DEL CLIENTE ya pasó el
# umbral correspondiente. El reenganche no debe repetirse dos veces para
# el mismo silencio.

from datetime import datetime, timedelta

from agent import memory as mem


async def _negocio_con_canal(codigo: str, telefono_canal: str):
    negocio = await mem.crear_negocio(f"Negocio {codigo}", codigo)
    canal = await mem.crear_canal_whatsapp(
        nombre=f"Canal {codigo}", phone_number_id=telefono_canal, negocio_id=negocio["id"],
    )
    return negocio, canal


async def _lead_gabi(telefono: str, negocio_id: str, canal_id: int, resultado: str | None = None):
    """Lead atendido por Gabi — sin asesor, sin pausar (el caso que aplica
    a este mecanismo, a diferencia de liberar_asignaciones_inactivas)."""
    await mem.resolver_conversation_activa(telefono, negocio_id, canal_id)
    await mem.actualizar_lead(telefono, nombre="Cliente Test", negocio_id=negocio_id)
    if resultado is not None:
        async with mem.async_session() as session:
            lead = await session.get(mem.Lead, telefono)
            lead.resultado = resultado
            await session.commit()


async def _mensaje(telefono: str, negocio_id: str, role: str, hace_horas: float):
    guardado = await mem.guardar_mensaje(telefono, role, "contenido de prueba", negocio_id)
    async with mem.async_session() as session:
        msg = await session.get(mem.Mensaje, guardado["id"])
        msg.timestamp = datetime.utcnow() - timedelta(hours=hace_horas)
        await session.commit()
    return guardado


# ---------------------------------------------------------------------------
# Reenganche (2h)
# ---------------------------------------------------------------------------

async def test_candidato_a_reenganche_cliente_silencioso_2h():
    negocio, canal = await _negocio_con_canal("g-inact-1", "40200000001")
    telefono = "51900600001"
    await _lead_gabi(telefono, negocio["id"], canal["id"])
    await _mensaje(telefono, negocio["id"], "user", hace_horas=3)
    await _mensaje(telefono, negocio["id"], "assistant", hace_horas=2.9)

    reenganche, cierre = await mem.listar_leads_inactividad_cliente(horas_reenganche=2.0, horas_cierre=15.0)

    assert telefono in {f["telefono"] for f in reenganche}
    assert telefono not in {f["telefono"] for f in cierre}


async def test_no_reengancha_si_todavia_no_pasa_el_umbral():
    negocio, canal = await _negocio_con_canal("g-inact-2", "40200000002")
    telefono = "51900600002"
    await _lead_gabi(telefono, negocio["id"], canal["id"])
    await _mensaje(telefono, negocio["id"], "user", hace_horas=1)
    await _mensaje(telefono, negocio["id"], "assistant", hace_horas=0.9)

    reenganche, cierre = await mem.listar_leads_inactividad_cliente(horas_reenganche=2.0, horas_cierre=15.0)

    assert telefono not in {f["telefono"] for f in reenganche}
    assert telefono not in {f["telefono"] for f in cierre}


async def test_no_reengancha_dos_veces_para_el_mismo_silencio():
    """Ya se mandó el reenganche (2 mensajes "assistant" seguidos después
    del último mensaje del cliente) — no debe volver a aparecer como
    candidato aunque siga sin responder."""
    negocio, canal = await _negocio_con_canal("g-inact-3", "40200000003")
    telefono = "51900600003"
    await _lead_gabi(telefono, negocio["id"], canal["id"])
    await _mensaje(telefono, negocio["id"], "user", hace_horas=5)
    await _mensaje(telefono, negocio["id"], "assistant", hace_horas=4.9)  # respuesta real de Gabi
    await _mensaje(telefono, negocio["id"], "assistant", hace_horas=3)  # el reenganche ya enviado

    reenganche, cierre = await mem.listar_leads_inactividad_cliente(horas_reenganche=2.0, horas_cierre=15.0)

    assert telefono not in {f["telefono"] for f in reenganche}
    assert telefono not in {f["telefono"] for f in cierre}


async def test_no_reengancha_si_el_ultimo_mensaje_es_del_cliente():
    """Gabi todavía no respondió lo último — no hay nada pendiente de
    nuestro lado, el mecanismo no aplica (evita chocar con un mensaje que
    está a punto de procesarse)."""
    negocio, canal = await _negocio_con_canal("g-inact-4", "40200000004")
    telefono = "51900600004"
    await _lead_gabi(telefono, negocio["id"], canal["id"])
    await _mensaje(telefono, negocio["id"], "assistant", hace_horas=5)
    await _mensaje(telefono, negocio["id"], "user", hace_horas=3)

    reenganche, cierre = await mem.listar_leads_inactividad_cliente(horas_reenganche=2.0, horas_cierre=15.0)

    assert telefono not in {f["telefono"] for f in reenganche}
    assert telefono not in {f["telefono"] for f in cierre}


# ---------------------------------------------------------------------------
# Cierre (15h)
# ---------------------------------------------------------------------------

async def test_candidato_a_cierre_tras_15h():
    negocio, canal = await _negocio_con_canal("g-inact-5", "40200000005")
    telefono = "51900600005"
    await _lead_gabi(telefono, negocio["id"], canal["id"])
    await _mensaje(telefono, negocio["id"], "user", hace_horas=16)
    await _mensaje(telefono, negocio["id"], "assistant", hace_horas=15.9)

    reenganche, cierre = await mem.listar_leads_inactividad_cliente(horas_reenganche=2.0, horas_cierre=15.0)

    assert telefono in {f["telefono"] for f in cierre}
    assert telefono not in {f["telefono"] for f in reenganche}


async def test_cierre_prioridad_sobre_reenganche_aunque_ya_se_reengancho():
    """Pasaron las 15h Y ya se había mandado el reenganche — debe cerrarse,
    no quedarse esperando otro reenganche."""
    negocio, canal = await _negocio_con_canal("g-inact-6", "40200000006")
    telefono = "51900600006"
    await _lead_gabi(telefono, negocio["id"], canal["id"])
    await _mensaje(telefono, negocio["id"], "user", hace_horas=20)
    await _mensaje(telefono, negocio["id"], "assistant", hace_horas=19.9)
    await _mensaje(telefono, negocio["id"], "assistant", hace_horas=18)  # reenganche ya mandado

    reenganche, cierre = await mem.listar_leads_inactividad_cliente(horas_reenganche=2.0, horas_cierre=15.0)

    assert telefono in {f["telefono"] for f in cierre}
    assert telefono not in {f["telefono"] for f in reenganche}


# ---------------------------------------------------------------------------
# Exclusiones — nunca debe tocar leads de asesor/pausados/ya cerrados
# ---------------------------------------------------------------------------

async def test_no_aplica_a_lead_con_asesor_asignado():
    negocio, canal = await _negocio_con_canal("g-inact-7", "40200000007")
    telefono = "51900600007"
    await _lead_gabi(telefono, negocio["id"], canal["id"])
    async with mem.async_session() as session:
        lead = await session.get(mem.Lead, telefono)
        lead.asesor_asignado = "asesor1"
        await session.commit()
    await _mensaje(telefono, negocio["id"], "user", hace_horas=20)
    await _mensaje(telefono, negocio["id"], "assistant", hace_horas=19)

    reenganche, cierre = await mem.listar_leads_inactividad_cliente(horas_reenganche=2.0, horas_cierre=15.0)

    assert telefono not in {f["telefono"] for f in reenganche}
    assert telefono not in {f["telefono"] for f in cierre}


async def test_no_aplica_a_lead_pausado_manual():
    negocio, canal = await _negocio_con_canal("g-inact-8", "40200000008")
    telefono = "51900600008"
    await _lead_gabi(telefono, negocio["id"], canal["id"])
    async with mem.async_session() as session:
        lead = await session.get(mem.Lead, telefono)
        lead.pausado_manual = True
        await session.commit()
    await _mensaje(telefono, negocio["id"], "user", hace_horas=20)
    await _mensaje(telefono, negocio["id"], "assistant", hace_horas=19)

    reenganche, cierre = await mem.listar_leads_inactividad_cliente(horas_reenganche=2.0, horas_cierre=15.0)

    assert telefono not in {f["telefono"] for f in reenganche}
    assert telefono not in {f["telefono"] for f in cierre}


async def test_no_aplica_a_lead_con_resultado_ya_cerrado():
    negocio, canal = await _negocio_con_canal("g-inact-9", "40200000009")
    telefono = "51900600009"
    await _lead_gabi(telefono, negocio["id"], canal["id"], resultado="no_interesado")
    await _mensaje(telefono, negocio["id"], "user", hace_horas=20)
    await _mensaje(telefono, negocio["id"], "assistant", hace_horas=19)

    reenganche, cierre = await mem.listar_leads_inactividad_cliente(horas_reenganche=2.0, horas_cierre=15.0)

    assert telefono not in {f["telefono"] for f in reenganche}
    assert telefono not in {f["telefono"] for f in cierre}


# ---------------------------------------------------------------------------
# Limpieza de "sin_respuesta" cuando el cliente vuelve a escribir
# (mismo mecanismo que usa agent/main.py — probado acá vía actualizar_lead
# directo, sin simular el webhook completo)
# ---------------------------------------------------------------------------

async def test_actualizar_lead_limpia_sin_respuesta_con_campos_explicitos():
    negocio, canal = await _negocio_con_canal("g-inact-10", "40200000010")
    telefono = "51900600010"
    await _lead_gabi(telefono, negocio["id"], canal["id"], resultado="sin_respuesta")

    await mem.actualizar_lead(telefono, campos_explicitos=("resultado",), resultado=None)

    async with mem.async_session() as session:
        lead = await session.get(mem.Lead, telefono)
        assert lead.resultado is None
