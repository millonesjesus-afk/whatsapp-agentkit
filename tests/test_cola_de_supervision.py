# tests/test_cola_de_supervision.py — 2026-10-04.
#
# Dos problemas reales de la primera corrida del Cron de 5 minutos:
# 1. Liberó a Gabi un lead con resultado "Agendado" (relojes viejos de la
#    versión anterior, leídos como armados tras renombrar la columna).
# 2. Un lead que NINGÚN asesor atendió volvía a Gabi, aunque Gabi ya lo había
#    derivado porque no podía seguir. Ahora pasa a la cola de supervisión:
#    sin asesor, con Gabi pausada, visible para el supervisor, y sin
#    repartirse solo al primer asesor que se ponga disponible.

import importlib.util
import os
from datetime import datetime, timedelta
from pathlib import Path

os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")
os.environ.setdefault("WHATSAPP_PROVIDER", "meta")
os.environ["DEBOUNCE_RESPUESTA_SEGUNDOS"] = "0"

from sqlalchemy import select, text
from starlette.requests import Request

from agent import asignacion, dashboard, memory as mem
from agent import main as app_main
from agent.debounce import gestor_debounce_respuestas
from agent.providers.base import MensajeEntrante


async def _negocio_con_canal(codigo: str, telefono_canal: str):
    negocio = await mem.crear_negocio(f"Negocio {codigo}", codigo)
    canal = await mem.crear_canal_whatsapp(
        nombre=f"Canal {codigo}", phone_number_id=telefono_canal, negocio_id=negocio["id"],
    )
    for dia in range(7):
        await mem.guardar_horario_atencion(negocio["id"], dia, True, "00:00", "23:59")
    return negocio, canal


async def _lead_derivado(telefono: str, negocio: dict, canal: dict, asesor: str):
    await mem.resolver_conversation_activa(telefono, negocio["id"], canal["id"])
    await mem.actualizar_lead(
        telefono, nombre="Cliente Test", negocio_id=negocio["id"],
        campos_explicitos=("paso_flujo",), paso_flujo="derivado_asesor",
    )
    await mem.asignar_asesor_a_lead(telefono, asesor, automatico=True)


async def _lead(telefono: str):
    async with mem.async_session() as session:
        return await session.get(mem.Lead, telefono)


async def _escalar_por_falta_de_asesor(codigo: str, tel_canal: str, telefono: str):
    """Un solo asesor: al cumplirse los 30 min no hay a quién rotar → escala."""
    negocio, canal = await _negocio_con_canal(codigo, tel_canal)
    await mem.crear_usuario(f"ase_{codigo}", "pw12345", "Asesor Unico", "asesor", negocio["id"])
    await _lead_derivado(telefono, negocio, canal, f"ase_{codigo}")
    resultado = await asignacion.ejecutar_ciclo_de_rotacion(intervalo_minutos=30, umbral_rotacion_minutos=30)
    return negocio, canal, resultado


# ── Destino: cola de supervisión, no Gabi ─────────────────────────────────

async def test_sin_otro_asesor_el_lead_pasa_a_supervision_y_no_vuelve_a_gabi():
    telefono = "51900800001"
    negocio, _, resultado = await _escalar_por_falta_de_asesor("sup-1", "40400000001", telefono)

    assert resultado["escalados"] == [telefono] and resultado["rotados"] == []
    lead = await _lead(telefono)
    assert lead.asesor_asignado is None
    assert lead.pausado_manual is True  # Gabi pausada
    assert lead.escalado_supervision_en is not None
    assert lead.derivado_en is None and lead.minutos_espera_asesor == 0 and lead.veces_rotado_espera == 0
    assert lead.paso_flujo == "derivado_asesor"

    eventos = await mem.listar_eventos_lead(telefono)
    evento = next(e for e in eventos if e["tipo"] == "desasignado_automatico")
    assert "cola de supervisión" in evento["descripcion"] and "Gabi no lo retoma" in evento["descripcion"]


async def test_tras_dos_rotaciones_sin_respuesta_tambien_pasa_a_supervision():
    negocio, canal = await _negocio_con_canal("sup-2", "40400000002")
    await mem.crear_usuario("ase_uno_sup2", "pw12345", "Asesor Uno", "asesor", negocio["id"])
    await mem.crear_usuario("ase_dos_sup2", "pw12345", "Asesor Dos", "asesor", negocio["id"])
    telefono = "51900800002"
    await _lead_derivado(telefono, negocio, canal, "ase_uno_sup2")

    primera = await asignacion.ejecutar_ciclo_de_rotacion(intervalo_minutos=30, umbral_rotacion_minutos=30)
    segunda = await asignacion.ejecutar_ciclo_de_rotacion(intervalo_minutos=30, umbral_rotacion_minutos=30)

    assert primera["rotados"] == [telefono] and primera["escalados"] == []
    assert segunda["rotados"] == [] and segunda["escalados"] == [telefono]
    lead = await _lead(telefono)
    assert lead.asesor_asignado is None and lead.pausado_manual is True and lead.escalado_supervision_en is not None


async def test_un_mensaje_del_cliente_a_un_lead_en_supervision_no_lo_responde_gabi(monkeypatch):
    telefono = "51900800003"
    negocio, canal, _ = await _escalar_por_falta_de_asesor("sup-3", "40400000003", telefono)

    class Proveedor:
        enviados: list[str] = []

        async def verificar_firma(self, request, cuerpo):
            return True

        async def parsear_webhook(self, request):
            return [MensajeEntrante(
                telefono=telefono, texto="¿Hay alguien?", mensaje_id="wamid.sup-3", es_propio=False,
                tipo="text", numero_whatsapp_id=canal["phone_number_id"],
            )]

        async def resolver_canal(self, numero_whatsapp_id, negocio_id=None):
            return {"id": canal["id"], "negocio_id": negocio["id"], "unidad_id": None,
                    "phone_number_id": canal["phone_number_id"], "modo": "produccion"}

        async def marcar_leido_y_escribiendo(self, mensaje_id, canal=None):
            return True

        async def enviar_mensaje(self, telefono, mensaje, canal=None, mensaje_id_citado=None):
            self.enviados.append(mensaje)
            return True, "wamid.OK"

    proveedor = Proveedor()
    monkeypatch.setattr(app_main, "proveedor", proveedor)

    async def no_debe_llamarse(*args, **kwargs):
        raise AssertionError("Gabi no debe responder a un lead en la cola de supervisión")
    monkeypatch.setattr(app_main.servicio_inteligencia, "generar_respuesta", no_debe_llamarse)

    cuerpo = b'{"object": "whatsapp_business_account"}'
    entregado = False

    async def recibir():
        nonlocal entregado
        if entregado:
            return {"type": "http.disconnect"}
        entregado = True
        return {"type": "http.request", "body": cuerpo, "more_body": False}

    request = Request({"type": "http", "method": "POST", "path": "/webhook", "headers": [],
                       "query_string": b"", "client": ("203.0.113.9", 1234)}, recibir)
    await app_main.webhook_handler(request)
    await gestor_debounce_respuestas.esperar_pendientes()

    assert proveedor.enviados == []
    lead = await _lead(telefono)
    assert lead.asesor_asignado is None and lead.escalado_supervision_en is not None  # sigue en la cola
    async with mem.async_session() as session:
        guardados = (await session.execute(
            select(mem.Mensaje).where(mem.Mensaje.telefono == telefono, mem.Mensaje.role == "user")
        )).scalars().all()
    assert [m.content for m in guardados] == ["¿Hay alguien?"]  # el supervisor sí ve el mensaje


async def test_el_cron_de_15_horas_no_cierra_un_lead_en_supervision():
    telefono = "51900800004"
    await _escalar_por_falta_de_asesor("sup-4", "40400000004", telefono)
    await mem.guardar_mensaje(telefono, "user", "hola", negocio_id=(await _lead(telefono)).negocio_id)
    await mem.guardar_mensaje(telefono, "assistant", "te derivo", negocio_id=(await _lead(telefono)).negocio_id)
    async with mem.async_session() as session:
        for m in (await session.execute(select(mem.Mensaje).where(mem.Mensaje.telefono == telefono))).scalars():
            m.timestamp = datetime.utcnow() - timedelta(hours=40)
        await session.commit()

    _, cierre = await mem.listar_leads_inactividad_cliente(horas_reenganche=2, horas_cierre=15)

    assert telefono not in {c["telefono"] for c in cierre}


# ── No se reparte solo, y sale de la cola cuando una persona decide ───────

async def test_no_se_reasigna_solo_al_primer_asesor_que_se_pone_disponible():
    telefono = "51900800005"
    negocio, canal, _ = await _escalar_por_falta_de_asesor("sup-5", "40400000005", telefono)
    await mem.crear_usuario("ase_nuevo_sup5", "pw12345", "Asesor Nuevo", "asesor", negocio["id"])

    asignado = await asignacion.asignar_lead_pendiente_a_asesor("ase_nuevo_sup5", "intermedio", negocio["id"])

    assert asignado is None
    assert (await _lead(telefono)).asesor_asignado is None


async def test_un_lead_pendiente_normal_sigue_repartiendose_igual():
    """No se rompe la cola de pendientes de siempre (nadie disponible al
    derivar): ese lead SÍ se asigna al ponerse disponible un asesor."""
    negocio, canal = await _negocio_con_canal("sup-6", "40400000006")
    telefono = "51900800006"
    await mem.resolver_conversation_activa(telefono, negocio["id"], canal["id"])
    await mem.actualizar_lead(
        telefono, nombre="Cliente Test", negocio_id=negocio["id"],
        campos_explicitos=("paso_flujo",), paso_flujo="derivado_asesor",
    )
    await mem.crear_usuario("ase_sup6", "pw12345", "Asesor", "asesor", negocio["id"])

    asignado = await asignacion.asignar_lead_pendiente_a_asesor("ase_sup6", "intermedio", negocio["id"])

    assert asignado == telefono


async def test_asignarlo_a_mano_lo_saca_de_la_cola_de_supervision():
    telefono = "51900800007"
    negocio, canal, _ = await _escalar_por_falta_de_asesor("sup-7", "40400000007", telefono)
    await mem.crear_usuario("ase_manual_sup7", "pw12345", "Asesor Manual", "asesor", negocio["id"])

    await mem.asignar_asesor_a_lead(telefono, "ase_manual_sup7", automatico=False)

    lead = await _lead(telefono)
    assert lead.asesor_asignado == "ase_manual_sup7" and lead.escalado_supervision_en is None


async def test_devolverlo_a_gabi_a_mano_lo_saca_de_la_cola_de_supervision():
    telefono = "51900800008"
    await _escalar_por_falta_de_asesor("sup-8", "40400000008", telefono)

    await mem.liberar_asignacion(telefono, autor="Supervisora", motivo="reactivado_manual")

    lead = await _lead(telefono)
    assert lead.escalado_supervision_en is None and lead.pausado_manual is False


# ── Inicio del supervisor ─────────────────────────────────────────────────

async def test_inicio_del_supervisor_muestra_primero_los_escalados_con_su_motivo():
    telefono = "51900800009"
    negocio, _, _ = await _escalar_por_falta_de_asesor("sup-9", "40400000009", telefono)
    # Otro lead derivado sin asesor (cola de pendientes de siempre).
    pendiente = "51900800010"
    canal = await mem.crear_canal_whatsapp(nombre="Canal sup-9b", phone_number_id="40400000019", negocio_id=negocio["id"])
    await mem.resolver_conversation_activa(pendiente, negocio["id"], canal["id"])
    await mem.actualizar_lead(
        pendiente, nombre="Pendiente", negocio_id=negocio["id"],
        campos_explicitos=("paso_flujo",), paso_flujo="derivado_asesor",
    )

    leads = await mem.listar_leads(negocio["id"])
    zona = await dashboard._zona_accion_admin_datos({"leads_todos": leads}, negocio["id"])

    motivos = [(i["telefono"], i["motivo"]) for i in zona["items"]]
    assert motivos[0] == (telefono, "Escalado a supervisión — ningún asesor respondió")
    assert (pendiente, "Sin asesor asignado") in motivos
    # El escalado aparece UNA sola vez (no también como "Esperando respuesta").
    assert [t for t, _ in motivos].count(telefono) == 1


# ── Un lead con resultado nunca rota ni escala (incidente: agendado) ──────

async def test_un_lead_con_resultado_nunca_rota_ni_escala_aunque_su_reloj_este_armado():
    negocio, canal = await _negocio_con_canal("sup-10", "40400000010")
    await mem.crear_usuario("ase_uno_sup10", "pw12345", "Asesor Uno", "asesor", negocio["id"])
    await mem.crear_usuario("ase_dos_sup10", "pw12345", "Asesor Dos", "asesor", negocio["id"])
    telefono = "51900800011"
    await _lead_derivado(telefono, negocio, canal, "ase_uno_sup10")
    # Reproduce el incidente: reloj armado (relojes viejos de la v1) sobre un
    # lead que una persona ya marcó "agendado".
    async with mem.async_session() as session:
        lead = await session.get(mem.Lead, telefono)
        lead.resultado = "agendado"
        lead.derivado_en = datetime.utcnow() - timedelta(days=3)
        lead.minutos_espera_asesor = 120
        lead.veces_rotado_espera = 1
        await session.commit()

    for _ in range(3):
        resultado = await asignacion.ejecutar_ciclo_de_rotacion(intervalo_minutos=30, umbral_rotacion_minutos=30)
        assert resultado == {"rotados": [], "escalados": []}

    lead = await _lead(telefono)
    assert lead.asesor_asignado == "ase_uno_sup10" and lead.resultado == "agendado"
    assert lead.escalado_supervision_en is None and lead.pausado_manual is False


async def test_enviar_a_cola_de_supervision_rechaza_un_lead_con_resultado():
    negocio, canal = await _negocio_con_canal("sup-11", "40400000011")
    telefono = "51900800012"
    await _lead_derivado(telefono, negocio, canal, "asesor_x")
    await mem.actualizar_lead(telefono, campos_explicitos=("resultado",), resultado="agendado")

    assert await mem.enviar_a_cola_de_supervision(telefono) is False
    lead = await _lead(telefono)
    assert lead.asesor_asignado == "asesor_x" and lead.escalado_supervision_en is None


# ── Migración: limpia los relojes viejos sin tocar los reales ─────────────

async def test_la_migracion_apaga_relojes_viejos_y_los_de_leads_con_resultado_pero_no_los_reales():
    ruta = next((Path(__file__).resolve().parent.parent / "migrations" / "versions").glob("f2d6a8c4e1b7_*.py"))
    spec = importlib.util.spec_from_file_location("mig_f2d6", ruta)
    migracion = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migracion)

    negocio, canal = await _negocio_con_canal("sup-12", "40400000012")
    casos = {
        "51900800021": ("viejo_sin_resultado", datetime(2026, 9, 29, 20, 0), None),
        "51900800022": ("real_sin_resultado", datetime(2026, 10, 2, 15, 0), None),
        "51900800023": ("real_con_resultado", datetime(2026, 10, 2, 15, 0), "agendado"),
    }
    for tel, (_, derivado, resultado) in casos.items():
        await mem.resolver_conversation_activa(tel, negocio["id"], canal["id"])
        await mem.actualizar_lead(tel, nombre="Cliente Test", negocio_id=negocio["id"])
        async with mem.async_session() as session:
            lead = await session.get(mem.Lead, tel)
            lead.asesor_asignado = "asesor_x"
            lead.derivado_en = derivado
            lead.minutos_espera_asesor = 25
            lead.veces_rotado_espera = 1
            lead.resultado = resultado
            await session.commit()

    async with mem.async_session() as session:
        await session.execute(text(migracion.SQL_LIMPIEZA_RELOJES), {"corte": migracion.CORTE_RELOJES_VIEJOS})
        await session.commit()

    viejo, real, con_resultado = [await _lead(t) for t in casos]
    assert viejo.derivado_en is None and viejo.minutos_espera_asesor == 0 and viejo.veces_rotado_espera == 0
    assert real.derivado_en == datetime(2026, 10, 2, 15, 0) and real.minutos_espera_asesor == 25  # legítimo: intacto
    assert con_resultado.derivado_en is None and con_resultado.minutos_espera_asesor == 0
