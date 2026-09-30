# tests/test_liberar_leads_inactivos.py — Punto 2, REDISEÑADO 2026-09-30
# tras un incidente real en producción: la primera versión (2026-09-29)
# detectaba "ciclo nuevo" comparando el timestamp del ÚLTIMO MENSAJE DEL
# CLIENTE — así que reabrir un resultado viejo (sin mensaje nuevo real)
# arrancaba una cuenta regresiva de 30 min falsa sobre un mensaje de hace
# días, y una reasignación MANUAL no apagaba nada (el cron siguiente la
# deshacía igual). Ver agent/memory.py::listar_leads_para_rotar_o_liberar
# para el rediseño completo: ahora todo gira sobre `Lead.derivado_en`, un
# timestamp de EVENTO (armado solo por una asignación automática real,
# desarmado por una respuesta real del asesor o por una reasignación
# manual) — nunca por contenido de mensajes ni por cambios de resultado.

from datetime import datetime, timedelta

from agent import memory as mem


async def _negocio_con_canal(codigo: str, telefono_canal: str):
    negocio = await mem.crear_negocio(f"Negocio {codigo}", codigo)
    canal = await mem.crear_canal_whatsapp(
        nombre=f"Canal {codigo}", phone_number_id=telefono_canal, negocio_id=negocio["id"],
    )
    return negocio, canal


async def _horario_siempre_abierto(negocio_id: str):
    for dia in range(7):
        await mem.guardar_horario_atencion(negocio_id, dia, True, "00:00", "23:59")


async def _horario_cerrado_hoy(negocio_id: str):
    # El mismo día de la semana que usa _dentro_de_horario_ahora (hora de
    # Lima, UTC-5 fijo) — así el test no depende de a qué hora real corre.
    ahora_lima = datetime.utcnow() - timedelta(hours=5)
    await mem.guardar_horario_atencion(negocio_id, ahora_lima.weekday(), False, None, None)


async def _lead_derivado(telefono: str, negocio_id: str, canal_id: int, asesor: str):
    """Reproduce una derivación real: Contact/Conversation creados, y
    `derivado_en` armado a través de `asignar_asesor_a_lead(automatico=
    True)` — no a mano — para que los tests ejerciten el mismo camino que
    produce el armado en producción (Gabi derivando, o una rotación)."""
    await mem.resolver_conversation_activa(telefono, negocio_id, canal_id)
    await mem.actualizar_lead(telefono, nombre="Cliente Test", negocio_id=negocio_id)
    await mem.asignar_asesor_a_lead(telefono, asesor, automatico=True)


async def _estado(telefono: str) -> dict:
    async with mem.async_session() as session:
        lead = await session.get(mem.Lead, telefono)
        return {
            "minutos": lead.minutos_espera_asesor, "veces_rotado": lead.veces_rotado_espera,
            "derivado_en": lead.derivado_en, "asesor": lead.asesor_asignado,
        }


# ---------------------------------------------------------------------------
# Solo cuenta minutos de TURNO
# ---------------------------------------------------------------------------

async def test_no_suma_minutos_si_el_negocio_esta_cerrado():
    negocio, canal = await _negocio_con_canal("g-rot-1", "40200000001")
    await _horario_cerrado_hoy(negocio["id"])
    await mem.crear_usuario("asesor_rot1", "pw12345", "Asesor 1", "asesor", negocio["id"])
    telefono = "51900600001"
    await _lead_derivado(telefono, negocio["id"], canal["id"], asesor="asesor_rot1")

    candidatos = await mem.listar_leads_para_rotar_o_liberar(intervalo_minutos=30, umbral_rotacion_minutos=30)

    assert telefono not in {c["telefono"] for c in candidatos}
    assert (await _estado(telefono))["minutos"] == 0


async def test_no_suma_minutos_si_el_asesor_no_esta_disponible():
    negocio, canal = await _negocio_con_canal("g-rot-2", "40200000002")
    await _horario_siempre_abierto(negocio["id"])
    await mem.crear_usuario("asesor_rot2", "pw12345", "Asesor 2", "asesor", negocio["id"])
    await mem.actualizar_disponibilidad("asesor_rot2", negocio["id"], False)
    telefono = "51900600002"
    await _lead_derivado(telefono, negocio["id"], canal["id"], asesor="asesor_rot2")

    candidatos = await mem.listar_leads_para_rotar_o_liberar(intervalo_minutos=30, umbral_rotacion_minutos=30)

    assert telefono not in {c["telefono"] for c in candidatos}
    assert (await _estado(telefono))["minutos"] == 0


# ---------------------------------------------------------------------------
# Acumulación y umbral
# ---------------------------------------------------------------------------

async def test_marca_para_rotar_al_llegar_al_umbral_en_turno():
    negocio, canal = await _negocio_con_canal("g-rot-3", "40200000003")
    await _horario_siempre_abierto(negocio["id"])
    await mem.crear_usuario("asesor_rot3", "pw12345", "Asesor 3", "asesor", negocio["id"])
    telefono = "51900600003"
    await _lead_derivado(telefono, negocio["id"], canal["id"], asesor="asesor_rot3")

    candidatos = await mem.listar_leads_para_rotar_o_liberar(intervalo_minutos=30, umbral_rotacion_minutos=30)

    assert len(candidatos) == 1
    assert candidatos[0]["telefono"] == telefono
    assert candidatos[0]["asesor_actual"] == "asesor_rot3"
    assert candidatos[0]["minutos_espera"] == 30


async def test_no_marca_para_rotar_antes_del_umbral_pero_sigue_acumulando():
    negocio, canal = await _negocio_con_canal("g-rot-4", "40200000004")
    await _horario_siempre_abierto(negocio["id"])
    await mem.crear_usuario("asesor_rot4", "pw12345", "Asesor 4", "asesor", negocio["id"])
    telefono = "51900600004"
    await _lead_derivado(telefono, negocio["id"], canal["id"], asesor="asesor_rot4")

    candidatos = await mem.listar_leads_para_rotar_o_liberar(intervalo_minutos=10, umbral_rotacion_minutos=30)

    assert candidatos == []
    assert (await _estado(telefono))["minutos"] == 10


# ---------------------------------------------------------------------------
# El incidente real (2026-09-29): reabrir un resultado viejo NO debe
# arrancar nada, y una reasignación manual SIEMPRE apaga el reloj.
# ---------------------------------------------------------------------------

async def test_reabrir_un_resultado_viejo_no_arranca_el_conteo():
    negocio, canal = await _negocio_con_canal("g-rot-5", "40200000005")
    await _horario_siempre_abierto(negocio["id"])
    await mem.crear_usuario("asesor_rot5", "pw12345", "Asesor 5", "asesor", negocio["id"])
    telefono = "51900600005"
    # Deriva, el asesor responde de verdad (desarma), y días después alguien
    # simplemente cambia el resultado — sin ninguna asignación automática de por medio.
    await _lead_derivado(telefono, negocio["id"], canal["id"], asesor="asesor_rot5")
    await mem.guardar_mensaje(telefono, "asesor", "ya te ayudo", negocio_id=negocio["id"])
    await mem.actualizar_lead(telefono, campos_explicitos=("resultado",), resultado="sin_respuesta")
    await mem.actualizar_lead(telefono, campos_explicitos=("resultado",), resultado=None)

    candidatos = await mem.listar_leads_para_rotar_o_liberar(intervalo_minutos=30, umbral_rotacion_minutos=30)

    assert candidatos == []
    assert (await _estado(telefono))["derivado_en"] is None


async def test_respuesta_real_del_asesor_desarma_el_reloj():
    negocio, canal = await _negocio_con_canal("g-rot-6", "40200000006")
    await _horario_siempre_abierto(negocio["id"])
    await mem.crear_usuario("asesor_rot6", "pw12345", "Asesor 6", "asesor", negocio["id"])
    telefono = "51900600006"
    await _lead_derivado(telefono, negocio["id"], canal["id"], asesor="asesor_rot6")
    assert (await _estado(telefono))["derivado_en"] is not None

    await mem.guardar_mensaje(telefono, "asesor", "aquí ando", negocio_id=negocio["id"])

    assert (await _estado(telefono))["derivado_en"] is None
    candidatos = await mem.listar_leads_para_rotar_o_liberar(intervalo_minutos=30, umbral_rotacion_minutos=30)
    assert candidatos == []


async def test_echo_de_coexistencia_tambien_desarma_el_reloj():
    negocio, canal = await _negocio_con_canal("g-rot-7", "40200000007")
    await _horario_siempre_abierto(negocio["id"])
    await mem.crear_usuario("asesor_rot7", "pw12345", "Asesor 7", "asesor", negocio["id"])
    telefono = "51900600007"
    await _lead_derivado(telefono, negocio["id"], canal["id"], asesor="asesor_rot7")

    await mem.guardar_mensaje(telefono, "assistant", "ya te contesto por acá", negocio_id=negocio["id"], via_app=True)

    assert (await _estado(telefono))["derivado_en"] is None


async def test_reasignacion_manual_desarma_el_reloj_aunque_ya_estuviera_contando():
    """Cubre el camino FALLBACK de `asignar_asesor_a_lead(automatico=False)`
    — el que usa dashboard.py solo cuando el Lead todavía no tiene Contact/
    Conversation/Opportunity. Ver `test_reasignacion_manual_real_via_
    conversation_desarma_el_reloj` para el camino REAL de producción
    (`intentar_asignar_conversation`, que es el que usa `/conversation/{id}/
    asignar` y el legacy `/lead/{telefono}/asignar` en el caso normal)."""
    negocio, canal = await _negocio_con_canal("g-rot-8", "40200000008")
    await _horario_siempre_abierto(negocio["id"])
    await mem.crear_usuario("asesor_rot8a", "pw12345", "Asesor 8a", "asesor", negocio["id"])
    await mem.crear_usuario("asesor_rot8b", "pw12345", "Asesor 8b", "asesor", negocio["id"])
    telefono = "51900600008"
    await _lead_derivado(telefono, negocio["id"], canal["id"], asesor="asesor_rot8a")
    await mem.listar_leads_para_rotar_o_liberar(intervalo_minutos=20, umbral_rotacion_minutos=30)
    assert (await _estado(telefono))["minutos"] == 20

    # Una PERSONA (no el sistema) reasigna a mano — mismo patrón real
    # (Angie Huarcaya reasignando manualmente en el incidente real).
    await mem.asignar_asesor_a_lead(telefono, "asesor_rot8b", automatico=False)

    estado = await _estado(telefono)
    assert estado["derivado_en"] is None
    assert estado["asesor"] == "asesor_rot8b"
    candidatos = await mem.listar_leads_para_rotar_o_liberar(intervalo_minutos=30, umbral_rotacion_minutos=30)
    assert candidatos == []  # no revive el conteo viejo ni arranca uno nuevo solo


async def test_reasignacion_manual_real_via_conversation_desarma_el_reloj():
    """El camino REAL de producción (2026-09-30) — el hueco más serio que
    destapó la pregunta del usuario: `/conversation/{id}/asignar` (y el
    legacy `/lead/{telefono}/asignar` una vez que ya existe Contact/
    Conversation/Opportunity, que es el caso normal) llaman a
    `intentar_asignar_conversation`, NO a `asignar_asesor_a_lead` — así que
    el test de arriba, que sí pasaba, NUNCA había ejercitado el camino que
    usa el panel de verdad. Mismo hueco exacto que el incidente de Pedro
    Padilla Medrano (reasignación manual que el cron deshacía), reubicado
    acá sin que nadie lo hubiera notado."""
    negocio, canal = await _negocio_con_canal("g-rot-13", "40200000013")
    await _horario_siempre_abierto(negocio["id"])
    await mem.crear_usuario("asesor_rot13a", "pw12345", "Asesor 13a", "asesor", negocio["id"])
    await mem.crear_usuario("asesor_rot13b", "pw12345", "Asesor 13b", "asesor", negocio["id"])
    telefono = "51900600013"
    await _lead_derivado(telefono, negocio["id"], canal["id"], asesor="asesor_rot13a")
    assert (await _estado(telefono))["derivado_en"] is not None

    conv, opp = await mem.resolver_conversation_activa(telefono, negocio["id"], canal["id"])
    ok = await mem.intentar_asignar_conversation(conv.id, conv.version, "asesor_rot13b")

    assert ok
    estado = await _estado(telefono)
    assert estado["derivado_en"] is None
    assert estado["asesor"] == "asesor_rot13b"
    candidatos = await mem.listar_leads_para_rotar_o_liberar(intervalo_minutos=30, umbral_rotacion_minutos=30)
    assert candidatos == []


# ---------------------------------------------------------------------------
# Segunda rotación → libera
# ---------------------------------------------------------------------------

async def test_dar_cualquier_resultado_desarma_el_reloj_sin_mensaje():
    """Pregunta del usuario (2026-09-30): "la regla... es cuando el asesor
    no responde o no le da algún resultado (cualquiera que sea)" — dar un
    resultado por el panel, SIN mandar ningún mensaje de chat, también debe
    apagar el reloj. Camino real: `intentar_cambiar_resultado_opportunity`."""
    negocio, canal = await _negocio_con_canal("g-rot-10", "40200000010")
    await _horario_siempre_abierto(negocio["id"])
    await mem.crear_usuario("asesor_rot10", "pw12345", "Asesor 10", "asesor", negocio["id"])
    telefono = "51900600010"
    await _lead_derivado(telefono, negocio["id"], canal["id"], asesor="asesor_rot10")
    assert (await _estado(telefono))["derivado_en"] is not None

    conv, opp = await mem.resolver_conversation_activa(telefono, negocio["id"], canal["id"])
    ok = await mem.intentar_cambiar_resultado_opportunity(opp.id, opp.version, {"resultado": "sin_respuesta"})

    assert ok
    assert (await _estado(telefono))["derivado_en"] is None
    candidatos = await mem.listar_leads_para_rotar_o_liberar(intervalo_minutos=30, umbral_rotacion_minutos=30)
    assert candidatos == []


async def test_cerrar_una_venta_desarma_el_reloj_aunque_no_haya_mensaje():
    """El hueco más grave que destapó la pregunta del usuario: cerrar una
    venta (resultado="vendido") es el camino real de `cerrar_opportunity_
    con_venta`, distinto del de arriba — sin este desarme, un "vendido" sin
    mensaje de chat posterior quedaba con el reloj corriendo, en contra de
    "Close-Won es indefinido"."""
    negocio, canal = await _negocio_con_canal("g-rot-11", "40200000011")
    await _horario_siempre_abierto(negocio["id"])
    await mem.crear_usuario("asesor_rot11", "pw12345", "Asesor 11", "asesor", negocio["id"])
    telefono = "51900600011"
    await _lead_derivado(telefono, negocio["id"], canal["id"], asesor="asesor_rot11")

    conv, opp = await mem.resolver_conversation_activa(telefono, negocio["id"], canal["id"])
    ok = await mem.cerrar_opportunity_con_venta(
        opp.id, opp.version, [{"producto": "Balón 10kg", "precio": "45"}],
        {"modalidad_pago": "contado", "medio_pago": "QR", "resultado": "vendido"},
    )

    assert ok
    estado = await _estado(telefono)
    assert estado["derivado_en"] is None

    async with mem.async_session() as session:
        lead = await session.get(mem.Lead, telefono)
        assert lead.pausado_manual is True


async def test_defensa_en_profundidad_lead_pausado_nunca_rota_ni_libera():
    """Aunque `derivado_en` quedara armado a mano sobre un lead ya pausado
    (`pausado_manual=True`) — por el motivo que sea, incluso un bug futuro
    en otro camino de escritura — la query de candidatos lo excluye igual.
    Última línea de defensa de "Close-Won es indefinido", no la primera."""
    negocio, canal = await _negocio_con_canal("g-rot-12", "40200000012")
    await _horario_siempre_abierto(negocio["id"])
    await mem.crear_usuario("asesor_rot12", "pw12345", "Asesor 12", "asesor", negocio["id"])
    telefono = "51900600012"
    await _lead_derivado(telefono, negocio["id"], canal["id"], asesor="asesor_rot12")

    async with mem.async_session() as session:
        lead = await session.get(mem.Lead, telefono)
        lead.pausado_manual = True  # simula que quedó armado sobre un lead pausado
        await session.commit()

    candidatos = await mem.listar_leads_para_rotar_o_liberar(intervalo_minutos=30, umbral_rotacion_minutos=30)

    assert candidatos == []


async def test_libera_directo_si_ya_habia_rotado_una_vez():
    negocio, canal = await _negocio_con_canal("g-rot-9", "40200000009")
    await _horario_siempre_abierto(negocio["id"])
    await mem.crear_usuario("asesor_rot9", "pw12345", "Asesor 9", "asesor", negocio["id"])
    telefono = "51900600009"
    await _lead_derivado(telefono, negocio["id"], canal["id"], asesor="asesor_rot9")
    async with mem.async_session() as session:
        lead = await session.get(mem.Lead, telefono)
        lead.veces_rotado_espera = 1  # simula: ya rotó una vez, este es el segundo asesor
        await session.commit()

    candidatos = await mem.listar_leads_para_rotar_o_liberar(intervalo_minutos=30, umbral_rotacion_minutos=30)

    assert candidatos == []  # no pide rotar de nuevo — se liberó directo
    async with mem.async_session() as session:
        lead = await session.get(mem.Lead, telefono)
        assert lead.asesor_asignado is None
