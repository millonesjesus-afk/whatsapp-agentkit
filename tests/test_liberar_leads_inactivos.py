# tests/test_liberar_leads_inactivos.py — Punto 2 (2026-09-29): reemplaza
# al mecanismo anterior (24h de RELOJ, item #1 de los "ajustes" pedidos
# 2026-09-16) por uno que solo cuenta MINUTOS DE TURNO — negocio abierto
# (HorarioAtencion) y el asesor asignado marcado `disponible` — pedido
# explícito del usuario: "no veo viable que una persona permanezca sin
# contestar 24 horas después de que Gabi lo asignó", y "deben considerarse
# en el horario de atención, no deben sumar las horas de fuera de
# atención". Cubre `agent/memory.py::listar_leads_para_rotar_o_liberar`
# (la contabilidad); la rotación real end-to-end (elegir al segundo asesor,
# liberar si ya no hay a quién rotar) vive en
# tests/test_asignacion_automatica.py, junto al resto de
# agent/asignacion.py.

from datetime import datetime, timedelta
from sqlalchemy import select

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


async def _mensaje_cliente(telefono: str, negocio_id: str):
    await mem.guardar_mensaje(telefono, "user", "contenido de prueba", negocio_id)


async def _minutos_y_veces(telefono: str) -> tuple[int, int]:
    async with mem.async_session() as session:
        lead = await session.get(mem.Lead, telefono)
        return lead.minutos_espera_asesor, lead.veces_rotado_espera


# ---------------------------------------------------------------------------
# Solo cuenta minutos de TURNO
# ---------------------------------------------------------------------------

async def test_no_suma_minutos_si_el_negocio_esta_cerrado():
    negocio, canal = await _negocio_con_canal("g-rot-1", "40200000001")
    await _horario_cerrado_hoy(negocio["id"])
    await mem.crear_usuario("asesor_rot1", "pw12345", "Asesor 1", "asesor", negocio["id"])
    telefono = "51900600001"
    await _lead_asignado(telefono, negocio["id"], canal["id"], asesor="asesor_rot1")
    await _mensaje_cliente(telefono, negocio["id"])

    candidatos = await mem.listar_leads_para_rotar_o_liberar(intervalo_minutos=30, umbral_rotacion_minutos=30)

    assert telefono not in {c["telefono"] for c in candidatos}
    minutos, _ = await _minutos_y_veces(telefono)
    assert minutos == 0


async def test_no_suma_minutos_si_el_asesor_no_esta_disponible():
    negocio, canal = await _negocio_con_canal("g-rot-2", "40200000002")
    await _horario_siempre_abierto(negocio["id"])
    await mem.crear_usuario("asesor_rot2", "pw12345", "Asesor 2", "asesor", negocio["id"])
    await mem.actualizar_disponibilidad("asesor_rot2", negocio["id"], False)
    telefono = "51900600002"
    await _lead_asignado(telefono, negocio["id"], canal["id"], asesor="asesor_rot2")
    await _mensaje_cliente(telefono, negocio["id"])

    candidatos = await mem.listar_leads_para_rotar_o_liberar(intervalo_minutos=30, umbral_rotacion_minutos=30)

    assert telefono not in {c["telefono"] for c in candidatos}
    minutos, _ = await _minutos_y_veces(telefono)
    assert minutos == 0


# ---------------------------------------------------------------------------
# Acumulación y umbral
# ---------------------------------------------------------------------------

async def test_marca_para_rotar_al_llegar_al_umbral_en_turno():
    negocio, canal = await _negocio_con_canal("g-rot-3", "40200000003")
    await _horario_siempre_abierto(negocio["id"])
    await mem.crear_usuario("asesor_rot3", "pw12345", "Asesor 3", "asesor", negocio["id"])
    telefono = "51900600003"
    await _lead_asignado(telefono, negocio["id"], canal["id"], asesor="asesor_rot3")
    await _mensaje_cliente(telefono, negocio["id"])

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
    await _lead_asignado(telefono, negocio["id"], canal["id"], asesor="asesor_rot4")
    await _mensaje_cliente(telefono, negocio["id"])

    candidatos = await mem.listar_leads_para_rotar_o_liberar(intervalo_minutos=10, umbral_rotacion_minutos=30)

    assert candidatos == []
    minutos, _ = await _minutos_y_veces(telefono)
    assert minutos == 10


async def test_reinicia_el_contador_solo_cuando_cambia_el_ultimo_mensaje_del_cliente():
    negocio, canal = await _negocio_con_canal("g-rot-5", "40200000005")
    await _horario_siempre_abierto(negocio["id"])
    await mem.crear_usuario("asesor_rot5", "pw12345", "Asesor 5", "asesor", negocio["id"])
    telefono = "51900600005"
    await _lead_asignado(telefono, negocio["id"], canal["id"], asesor="asesor_rot5")
    await _mensaje_cliente(telefono, negocio["id"])

    await mem.listar_leads_para_rotar_o_liberar(intervalo_minutos=15, umbral_rotacion_minutos=30)
    minutos, _ = await _minutos_y_veces(telefono)
    assert minutos == 15

    # El cliente escribe de nuevo sin que el asesor haya respondido — es un
    # ciclo de espera NUEVO, el contador debe reiniciarse (no seguir en 15).
    await _mensaje_cliente(telefono, negocio["id"])
    await mem.listar_leads_para_rotar_o_liberar(intervalo_minutos=15, umbral_rotacion_minutos=30)
    minutos, _ = await _minutos_y_veces(telefono)
    assert minutos == 15  # 0 (reiniciado) + 15, no 15+15=30


async def test_libera_directo_si_ya_habia_rotado_una_vez():
    negocio, canal = await _negocio_con_canal("g-rot-6", "40200000006")
    await _horario_siempre_abierto(negocio["id"])
    await mem.crear_usuario("asesor_rot6", "pw12345", "Asesor 6", "asesor", negocio["id"])
    telefono = "51900600006"
    await _lead_asignado(telefono, negocio["id"], canal["id"], asesor="asesor_rot6")
    await _mensaje_cliente(telefono, negocio["id"])
    async with mem.async_session() as session:
        lead = await session.get(mem.Lead, telefono)
        lead.veces_rotado_espera = 1  # simula: ya rotó una vez, este es el segundo asesor
        lead.espera_medida_desde = (await session.execute(
            select(mem.Mensaje.timestamp).where(mem.Mensaje.telefono == telefono).order_by(mem.Mensaje.timestamp.desc()).limit(1)
        )).scalar_one()
        await session.commit()

    candidatos = await mem.listar_leads_para_rotar_o_liberar(intervalo_minutos=30, umbral_rotacion_minutos=30)

    assert candidatos == []  # no pide rotar de nuevo — se liberó directo
    async with mem.async_session() as session:
        lead = await session.get(mem.Lead, telefono)
        assert lead.asesor_asignado is None


# ---------------------------------------------------------------------------
# Casos negativos ya cubiertos por el mecanismo anterior — siguen aplicando
# ---------------------------------------------------------------------------

async def test_no_marca_si_el_ultimo_mensaje_es_del_asesor():
    negocio, canal = await _negocio_con_canal("g-rot-7", "40200000007")
    await _horario_siempre_abierto(negocio["id"])
    await mem.crear_usuario("asesor_rot7", "pw12345", "Asesor 7", "asesor", negocio["id"])
    telefono = "51900600007"
    await _lead_asignado(telefono, negocio["id"], canal["id"], asesor="asesor_rot7")
    await _mensaje_cliente(telefono, negocio["id"])
    await mem.guardar_mensaje(telefono, "asesor", "ya te respondo", negocio["id"])

    candidatos = await mem.listar_leads_para_rotar_o_liberar(intervalo_minutos=30, umbral_rotacion_minutos=30)

    assert candidatos == []


async def test_no_marca_lead_sin_asesor_asignado():
    negocio, _ = await _negocio_con_canal("g-rot-8", "40200000008")
    await _horario_siempre_abierto(negocio["id"])
    telefono = "51900600008"
    await mem.actualizar_lead(telefono, nombre="Cliente Test", negocio_id=negocio["id"])
    await _mensaje_cliente(telefono, negocio["id"])

    candidatos = await mem.listar_leads_para_rotar_o_liberar(intervalo_minutos=30, umbral_rotacion_minutos=30)

    assert candidatos == []


async def test_no_marca_lead_con_resultado_vendido():
    negocio, canal = await _negocio_con_canal("g-rot-9", "40200000009")
    await _horario_siempre_abierto(negocio["id"])
    await mem.crear_usuario("asesor_rot9", "pw12345", "Asesor 9", "asesor", negocio["id"])
    telefono = "51900600009"
    await _lead_asignado(telefono, negocio["id"], canal["id"], asesor="asesor_rot9", resultado="vendido")
    await _mensaje_cliente(telefono, negocio["id"])

    candidatos = await mem.listar_leads_para_rotar_o_liberar(intervalo_minutos=30, umbral_rotacion_minutos=30)

    assert candidatos == []
    async with mem.async_session() as session:
        lead = await session.get(mem.Lead, telefono)
        assert lead.asesor_asignado == "asesor_rot9"
