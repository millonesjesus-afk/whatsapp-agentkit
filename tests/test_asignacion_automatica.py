# tests/test_asignacion_automatica.py — elegir_asesor_automatico (Gabi)
# nunca debe elegir un asesor desactivado.
#
# Hallazgo del usuario (2026-09-17): "gabi asigna a un asesor a pesar que
# este inactivo, solo debe asignar a los activos". `elegir_asesor_automatico`
# ya filtraba por `disponible`, pero `listar_asesores()` (de quien depende)
# nunca excluía `activo=False` — y `toggle_usuario_activo` (Equipo) jamás
# toca `disponible`, así que una cuenta desactivada con `disponible=True`
# seguía siendo candidata para siempre (sin forma de corregirlo ella misma,
# porque `activo=False` le bloquea el login). Fix: agent/memory.py::
# listar_asesores ahora también exige `activo.is_(True)`.

from sqlalchemy import select

from agent import asignacion, memory as mem


async def _negocio_con_canal(codigo: str, telefono_canal: str):
    negocio = await mem.crear_negocio(f"Negocio {codigo}", codigo)
    canal = await mem.crear_canal_whatsapp(
        nombre=f"Canal {codigo}", phone_number_id=telefono_canal, negocio_id=negocio["id"],
    )
    return negocio, canal


async def _horario_siempre_abierto(negocio_id: str):
    for dia in range(7):
        await mem.guardar_horario_atencion(negocio_id, dia, True, "00:00", "23:59")


async def _lead_asignado(telefono: str, negocio_id: str, canal_id: int, asesor: str):
    """Reproduce una derivación real (`asignar_asesor_a_lead(automatico=
    True)`, no una escritura directa a la fila) para que `derivado_en`
    quede armado tal como pasa en producción — ver Punto 2, rediseño
    2026-09-30. `paso_flujo="derivado_asesor"` también reproduce lo que
    Gabi deja escrito al derivar de verdad — sin esto, `listar_leads_
    esperando_asesor` (el panel de Inicio del supervisor) no lo detectaría
    si el mecanismo termina liberándolo."""
    await mem.resolver_conversation_activa(telefono, negocio_id, canal_id)
    await mem.actualizar_lead(
        telefono, nombre="Cliente Test", negocio_id=negocio_id,
        campos_explicitos=("paso_flujo",), paso_flujo="derivado_asesor",
    )
    await mem.asignar_asesor_a_lead(telefono, asesor, automatico=True)


async def test_no_elige_asesor_desactivado_aunque_siga_disponible():
    negocio = await mem.crear_negocio("Negocio Asignacion", "asig-1")
    await mem.crear_usuario("ase_activo_asig1", "pw12345", "Asesor Activo", "asesor", negocio["id"])
    await mem.crear_usuario("ase_inactivo_asig1", "pw12345", "Asesor Inactivo", "asesor", negocio["id"])
    # Se desactiva la cuenta (Equipo) SIN tocar `disponible` — reproduce
    # exactamente el estado real: `toggle_usuario_activo` nunca lo hace.
    nuevo_estado = await mem.toggle_usuario_activo("ase_inactivo_asig1", negocio["id"])
    assert nuevo_estado is False
    asesores = await mem.listar_asesores(negocio["id"])
    assert "ase_inactivo_asig1" not in {a["username"] for a in asesores}

    # Con el único asesor "activo" real cargado al máximo (mismo criterio de
    # balanceo por carga que ya usa la función), igual debe elegirlo a él —
    # nunca al desactivado, aunque su `disponible` siga en True.
    elegido = await asignacion.elegir_asesor_automatico("", negocio["id"])
    assert elegido == "ase_activo_asig1"


async def test_no_hay_candidatos_si_el_unico_disponible_esta_desactivado():
    negocio = await mem.crear_negocio("Negocio Asignacion Solo", "asig-2")
    await mem.crear_usuario("ase_unico_asig2", "pw12345", "Asesor Único", "asesor", negocio["id"])
    await mem.toggle_usuario_activo("ase_unico_asig2", negocio["id"])

    elegido = await asignacion.elegir_asesor_automatico("", negocio["id"])
    assert elegido is None


async def test_elegir_asesor_automatico_excluye_al_pedido():
    negocio = await mem.crear_negocio("Negocio Asignacion Excluir", "asig-3")
    await mem.crear_usuario("ase_a_asig3", "pw12345", "Asesor A", "asesor", negocio["id"])
    await mem.crear_usuario("ase_b_asig3", "pw12345", "Asesor B", "asesor", negocio["id"])

    elegido = await asignacion.elegir_asesor_automatico("", negocio["id"], excluir="ase_a_asig3")

    assert elegido == "ase_b_asig3"


# ---------------------------------------------------------------------------
# rotar_leads_inactivos — Punto 2 (2026-09-29): rotación por inactividad del
# asesor, 30 min de turno con el primero, 30 más con el segundo antes de
# liberar. Ver tests/test_liberar_leads_inactivos.py para la contabilidad
# de minutos de turno (agent/memory.py::listar_leads_para_rotar_o_liberar);
# acá se prueba el flujo completo: elegir al segundo asesor y aplicarlo.
# ---------------------------------------------------------------------------

async def test_rota_al_segundo_asesor_tras_30_min_de_turno_sin_respuesta():
    negocio, canal = await _negocio_con_canal("g-rotf-1", "40300000001")
    await _horario_siempre_abierto(negocio["id"])
    await mem.crear_usuario("ase_uno_rotf1", "pw12345", "Asesor Uno", "asesor", negocio["id"])
    await mem.crear_usuario("ase_dos_rotf1", "pw12345", "Asesor Dos", "asesor", negocio["id"])
    telefono = "51900700001"
    await _lead_asignado(telefono, negocio["id"], canal["id"], asesor="ase_uno_rotf1")

    rotados = await asignacion.rotar_leads_inactivos(intervalo_minutos=30, umbral_rotacion_minutos=30)

    assert telefono in rotados
    async with mem.async_session() as session:
        lead = await session.get(mem.Lead, telefono)
        assert lead.asesor_asignado == "ase_dos_rotf1"
        assert lead.veces_rotado_espera == 1
        assert lead.minutos_espera_asesor == 0

        evento = (await session.execute(
            select(mem.EventoLead)
            .where(mem.EventoLead.negocio_id == negocio["id"], mem.EventoLead.tipo == "rotado_automatico_sin_respuesta")
        )).scalars().first()
        assert evento is not None
        assert evento.payload["asesor_anterior"] == "ase_uno_rotf1"
        assert evento.payload["asesor_nuevo"] == "ase_dos_rotf1"


async def test_libera_si_el_segundo_asesor_tampoco_responde_en_30_min():
    negocio, canal = await _negocio_con_canal("g-rotf-2", "40300000002")
    await _horario_siempre_abierto(negocio["id"])
    await mem.crear_usuario("ase_uno_rotf2", "pw12345", "Asesor Uno", "asesor", negocio["id"])
    await mem.crear_usuario("ase_dos_rotf2", "pw12345", "Asesor Dos", "asesor", negocio["id"])
    telefono = "51900700002"
    await _lead_asignado(telefono, negocio["id"], canal["id"], asesor="ase_uno_rotf2")

    # Primera pasada: rota de "uno" a "dos".
    await asignacion.rotar_leads_inactivos(intervalo_minutos=30, umbral_rotacion_minutos=30)
    # Segunda pasada: "dos" tampoco respondió en otros 30 min de turno.
    rotados = await asignacion.rotar_leads_inactivos(intervalo_minutos=30, umbral_rotacion_minutos=30)

    assert telefono not in rotados
    async with mem.async_session() as session:
        lead = await session.get(mem.Lead, telefono)
        assert lead.asesor_asignado is None


async def test_libera_directo_si_no_hay_otro_asesor_para_rotar():
    negocio, canal = await _negocio_con_canal("g-rotf-3", "40300000003")
    await _horario_siempre_abierto(negocio["id"])
    await mem.crear_usuario("ase_unico_rotf3", "pw12345", "Asesor Único", "asesor", negocio["id"])
    telefono = "51900700003"
    await _lead_asignado(telefono, negocio["id"], canal["id"], asesor="ase_unico_rotf3")

    rotados = await asignacion.rotar_leads_inactivos(intervalo_minutos=30, umbral_rotacion_minutos=30)

    assert telefono not in rotados
    async with mem.async_session() as session:
        lead = await session.get(mem.Lead, telefono)
        assert lead.asesor_asignado is None

    # Pedido del usuario: un lead liberado por inactividad debe aparecer en
    # el panel de Inicio del supervisor ("Sin asesor asignado") — confirma
    # que no hace falta código nuevo para eso: `paso_flujo` sigue en
    # "derivado_asesor" (nada en la rotación/liberación lo toca), que es
    # exactamente lo que `listar_leads_esperando_asesor` exige.
    esperando = await mem.listar_leads_esperando_asesor(negocio["id"])
    assert telefono in {l["telefono"] for l in esperando}


# ---------------------------------------------------------------------------
# Incidente real (Pedro Padilla Medrano, 2026-09-29) — extremo a extremo
# contra el orquestador real, no solo la contabilidad de memory.py.
# ---------------------------------------------------------------------------

async def test_reasignacion_manual_nunca_se_deshace_sola():
    negocio, canal = await _negocio_con_canal("g-rotf-4", "40300000004")
    await _horario_siempre_abierto(negocio["id"])
    await mem.crear_usuario("ase_uno_rotf4", "pw12345", "Asesor Uno", "asesor", negocio["id"])
    await mem.crear_usuario("ase_dos_rotf4", "pw12345", "Asesor Dos", "asesor", negocio["id"])
    telefono = "51900700004"
    await _lead_asignado(telefono, negocio["id"], canal["id"], asesor="ase_uno_rotf4")

    # Una PERSONA reasigna a mano (no el sistema) — mismo patrón real del
    # incidente (Angie Huarcaya reasignando a Pedro Padilla Medrano).
    await mem.asignar_asesor_a_lead(telefono, "ase_dos_rotf4", automatico=False)

    # El siguiente Cron (varias corridas seguidas, como pasaba cada 5 min en
    # el incidente real) NUNCA debe deshacer esto.
    for _ in range(3):
        rotados = await asignacion.rotar_leads_inactivos(intervalo_minutos=30, umbral_rotacion_minutos=30)
        assert telefono not in rotados

    async with mem.async_session() as session:
        lead = await session.get(mem.Lead, telefono)
        assert lead.asesor_asignado == "ase_dos_rotf4"


async def test_reabrir_resultado_viejo_no_dispara_rotacion_ni_liberacion():
    negocio, canal = await _negocio_con_canal("g-rotf-5", "40300000005")
    await _horario_siempre_abierto(negocio["id"])
    await mem.crear_usuario("ase_uno_rotf5", "pw12345", "Asesor Uno", "asesor", negocio["id"])
    await mem.crear_usuario("ase_dos_rotf5", "pw12345", "Asesor Dos", "asesor", negocio["id"])
    telefono = "51900700005"
    await _lead_asignado(telefono, negocio["id"], canal["id"], asesor="ase_uno_rotf5")
    # El asesor responde de verdad y cierra el caso — semanas/días después
    # alguien reabre el resultado sin que el cliente haya escrito nada nuevo
    # (el gatillo real del incidente con Pedro Padilla Medrano).
    await mem.guardar_mensaje(telefono, "asesor", "listo, quedamos así", negocio_id=negocio["id"])
    await mem.actualizar_lead(telefono, campos_explicitos=("resultado",), resultado="sin_respuesta")
    await mem.actualizar_lead(telefono, campos_explicitos=("resultado",), resultado=None)

    rotados = await asignacion.rotar_leads_inactivos(intervalo_minutos=30, umbral_rotacion_minutos=30)

    assert telefono not in rotados
    async with mem.async_session() as session:
        lead = await session.get(mem.Lead, telefono)
        assert lead.asesor_asignado == "ase_uno_rotf5"  # nadie lo tocó
