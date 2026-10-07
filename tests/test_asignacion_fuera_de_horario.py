# tests/test_asignacion_fuera_de_horario.py — Fase 1 de la política de asignación (2026-10-07).
#
# Hallazgo real de la semana: 12 leads con asesor asignado, ningún mensaje humano y la ventana de 24 h
# de WhatsApp ya cerrada; 8 se asignaron FUERA de horario (sábado noche, madrugada, domingo). La
# asignación automática solo miraba el interruptor `disponible`, Gabi se pausaba al instante y nadie
# veía el caso. Ahora:
#   1. con el negocio cerrado `elegir_asesor_automatico` no asigna: el lead queda derivado, sin asesor
#      y con Gabi activa;
#   2. el Cron reparte esa cola al abrir (primero el que antes cierra su ventana de 24 h, con tope);
#   3. esos leads no reciben el reenganche de 2 h ni el cierre `sin_respuesta` de 15 h;
#   4. el correo dice la verdad ("no hay asesor en turno");
#   5. una asignación automática nueva reinicia los contadores de rotación.
#
# Datos sintéticos únicamente.

import importlib.util
import os
from datetime import datetime, timedelta
from pathlib import Path

os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")
os.environ.setdefault("WHATSAPP_PROVIDER", "meta")

from sqlalchemy import select

from agent import asignacion, notificaciones, memory as mem
from agent import main as app_main

RAIZ = Path(__file__).resolve().parent.parent


# ── helpers ───────────────────────────────────────────────────────────────────

async def _negocio_con_canal(codigo: str, telefono_canal: str):
    negocio = await mem.crear_negocio(f"Negocio {codigo}", codigo)
    canal = await mem.crear_canal_whatsapp(
        nombre=f"Canal {codigo}", phone_number_id=telefono_canal, negocio_id=negocio["id"],
    )
    return negocio, canal


async def _abierto(negocio_id: str):
    for dia in range(7):
        await mem.guardar_horario_atencion(negocio_id, dia, True, "00:00", "23:59")


async def _cerrado(negocio_id: str):
    for dia in range(7):
        await mem.guardar_horario_atencion(negocio_id, dia, False, None, None)


async def _lead_derivado_sin_asesor(telefono: str, negocio: dict, canal: dict, cliente_escribio_hace_h: float | None):
    """Lo que deja una derivación con el negocio cerrado: derivado_asesor, sin asesor, Gabi activa."""
    await mem.resolver_conversation_activa(telefono, negocio["id"], canal["id"])
    await mem.actualizar_lead(
        telefono, nombre="Cliente Test", negocio_id=negocio["id"],
        campos_explicitos=("paso_flujo",), paso_flujo="derivado_asesor",
    )
    if cliente_escribio_hace_h is not None:
        await _mensaje(telefono, negocio["id"], "user", cliente_escribio_hace_h)


async def _mensaje(telefono: str, negocio_id: str, role: str, hace_horas: float):
    guardado = await mem.guardar_mensaje(telefono, role, "contenido de prueba", negocio_id)
    async with mem.async_session() as session:
        msg = await session.get(mem.Mensaje, guardado["id"])
        msg.timestamp = datetime.utcnow() - timedelta(hours=hace_horas)
        await session.commit()


async def _lead(telefono: str):
    async with mem.async_session() as session:
        return await session.get(mem.Lead, telefono)


# ── 1. Con el negocio cerrado no se asigna ────────────────────────────────────

async def test_con_el_negocio_cerrado_no_elige_asesor_aunque_haya_disponibles():
    negocio, _ = await _negocio_con_canal("fh-1", "40500000001")
    await _cerrado(negocio["id"])
    await mem.crear_usuario("ase_fh1", "pw12345", "Asesor", "asesor", negocio["id"])

    assert await asignacion.elegir_asesor_automatico("", negocio["id"]) is None


async def test_con_el_negocio_abierto_elige_como_siempre():
    negocio, _ = await _negocio_con_canal("fh-2", "40500000002")
    await _abierto(negocio["id"])
    await mem.crear_usuario("ase_fh2", "pw12345", "Asesor", "asesor", negocio["id"])

    assert await asignacion.elegir_asesor_automatico("", negocio["id"]) == "ase_fh2"


async def test_el_modo_sin_ia_puede_pedir_no_respetar_el_horario():
    """respaldo_sin_ia tiene su propia regla fuera de horario: no debe cambiar."""
    negocio, _ = await _negocio_con_canal("fh-3", "40500000003")
    await _cerrado(negocio["id"])
    await mem.crear_usuario("ase_fh3", "pw12345", "Asesor", "asesor", negocio["id"])

    assert await asignacion.elegir_asesor_automatico("", negocio["id"], respetar_horario=False) == "ase_fh3"


async def test_sin_filas_de_horario_rige_el_fallback_lunes_a_sabado_8_a_19(monkeypatch):
    """El fallback sale de agent/tools.py; acá solo se prueba que la asignación lo consulta."""
    negocio, _ = await _negocio_con_canal("fh-4", "40500000004")
    await mem.crear_usuario("ase_fh4", "pw12345", "Asesor", "asesor", negocio["id"])
    consultas = []

    async def estado(negocio_id):
        consultas.append(negocio_id)
        return {"dentro_de_horario": False}

    monkeypatch.setattr(asignacion, "obtener_estado_horario_atencion", estado)
    assert await asignacion.elegir_asesor_automatico("", negocio["id"]) is None
    assert consultas == [negocio["id"]]


async def test_la_asignacion_manual_no_se_bloquea_con_el_negocio_cerrado():
    negocio, canal = await _negocio_con_canal("fh-5", "40500000005")
    await _cerrado(negocio["id"])
    await mem.crear_usuario("ase_fh5", "pw12345", "Asesor", "asesor", negocio["id"])
    telefono = "51910000005"
    await _lead_derivado_sin_asesor(telefono, negocio, canal, 1)

    await mem.asignar_asesor_a_lead(telefono, "ase_fh5")  # automatico=False: una persona desde el panel

    assert (await _lead(telefono)).asesor_asignado == "ase_fh5"


# ── Derivación de punta a punta con el negocio cerrado ────────────────────────

class _ProveedorFalso:
    def __init__(self):
        self.enviados: list[str] = []

    async def enviar_mensaje(self, telefono, mensaje, canal=None, mensaje_id_citado=None):
        self.enviados.append(mensaje)
        return True, "wamid.OK"


async def _armar_derivacion(monkeypatch, codigo: str, telefono: str, ya_derivado: bool):
    negocio, canal_db = await _negocio_con_canal(codigo, f"4051{codigo[-6:]}")
    await _cerrado(negocio["id"])
    await mem.crear_usuario(f"ase_{codigo[-4:]}", "pw12345", "Asesor", "asesor", negocio["id"])
    canal = {"id": canal_db["id"], "negocio_id": negocio["id"], "unidad_id": None,
             "phone_number_id": canal_db["phone_number_id"], "modo": "produccion"}
    await mem.actualizar_lead(telefono, negocio_id=negocio["id"], numero_whatsapp_id="x")
    await mem.resolver_conversation_activa(telefono, negocio["id"], canal_db["id"])
    if ya_derivado:
        await mem.actualizar_lead(telefono, negocio_id=negocio["id"], paso_flujo="derivado_asesor")
    await mem.guardar_mensaje(telefono, "user", "pásame con un asesor", negocio_id=negocio["id"])

    proveedor = _ProveedorFalso()
    monkeypatch.setattr(app_main, "proveedor", proveedor)
    correos: list[str] = []

    async def gabi(mensaje, historial, lead, modo="produccion", negocio_id=None):
        return "Te derivo con un asesor comercial 😊", False, None, None

    async def deriva(*a, **k):
        return {"paso_flujo": "derivado_asesor"}

    async def notificar(telefono, lead, texto):
        correos.append(telefono)

    monkeypatch.setattr(app_main.servicio_inteligencia, "generar_respuesta", gabi)
    monkeypatch.setattr(app_main.servicio_inteligencia, "extraer_datos_lead", deriva)
    monkeypatch.setattr(app_main, "notificar_lead_derivado", notificar)
    return negocio, canal, proveedor, correos


async def test_derivacion_fuera_de_horario_deja_el_lead_sin_asesor_con_gabi_activa_y_un_solo_correo(monkeypatch):
    telefono = "51910000006"
    negocio, canal, proveedor, correos = await _armar_derivacion(monkeypatch, "fh-d-000006", telefono, ya_derivado=False)

    await app_main._generar_y_enviar_respuesta_ia(telefono, canal)

    lead = await _lead(telefono)
    assert lead.paso_flujo == "derivado_asesor"
    assert lead.asesor_asignado is None
    assert lead.pausado_manual is False and lead.escalado_supervision_en is None  # Gabi sigue activa
    assert lead.derivado_en is None  # sin reloj de rotación: no hay nadie a quien monitorear
    assert correos == [telefono]

    # El cliente insiste: no se re-deriva ni se manda otro correo.
    await mem.guardar_mensaje(telefono, "user", "¿alguien me atiende?", negocio_id=negocio["id"])
    await app_main._generar_y_enviar_respuesta_ia(telefono, canal)
    assert (await _lead(telefono)).asesor_asignado is None
    assert correos == [telefono]


# ── 2. La cola se reparte al abrir ────────────────────────────────────────────

async def test_al_abrir_asigna_la_cola_primero_la_ventana_que_antes_cierra():
    negocio, canal = await _negocio_con_canal("fh-c-1", "40500000011")
    await _abierto(negocio["id"])
    # Último mensaje del cliente hace: 20 h (cierra en 4 h), 5 h (cierra en 19 h), 30 h y 26 h (ya cerradas).
    await _lead_derivado_sin_asesor("51920000001", negocio, canal, 20)
    await _lead_derivado_sin_asesor("51920000002", negocio, canal, 5)
    await _lead_derivado_sin_asesor("51920000003", negocio, canal, 30)
    await _lead_derivado_sin_asesor("51920000004", negocio, canal, 26)

    cola = await asignacion.listar_cola_pendiente_por_urgencia(negocio["id"])

    # Abiertas por cierre más próximo; luego cerradas, la más reciente primero.
    assert [l["telefono"] for l in cola] == ["51920000001", "51920000002", "51920000004", "51920000003"]


async def test_al_abrir_asigna_respetando_el_orden_el_tope_y_es_idempotente():
    negocio, canal = await _negocio_con_canal("fh-c-2", "40500000012")
    await _abierto(negocio["id"])
    await mem.crear_usuario("ase_fhc2", "pw12345", "Asesor", "asesor", negocio["id"])
    await _lead_derivado_sin_asesor("51920000011", negocio, canal, 5)
    await _lead_derivado_sin_asesor("51920000012", negocio, canal, 20)
    await _lead_derivado_sin_asesor("51920000013", negocio, canal, 30)

    r1 = await asignacion.asignar_cola_pendiente_al_abrir(max_por_corrida=2)
    assert [t for t, _ in r1["asignados"]] == ["51920000012", "51920000011"]  # cierra antes, primero
    assert r1["pendientes"] == 1
    assert (await _lead("51920000013")).asesor_asignado is None

    r2 = await asignacion.asignar_cola_pendiente_al_abrir(max_por_corrida=2)
    assert [t for t, _ in r2["asignados"]] == ["51920000013"]
    assert r2["pendientes"] == 0

    r3 = await asignacion.asignar_cola_pendiente_al_abrir(max_por_corrida=2)  # nada más que hacer
    assert r3 == {"asignados": [], "pendientes": 0}

    lead = await _lead("51920000011")
    assert lead.asesor_asignado == "ase_fhc2" and lead.derivado_en is not None  # arma el reloj de rotación
    eventos = await mem.listar_eventos_lead("51920000011")
    assert "asignado_automatico" in {e["tipo"] for e in eventos}


async def test_el_tope_por_corrida_se_lee_de_la_configuracion_del_negocio():
    negocio, canal = await _negocio_con_canal("fh-c-3", "40500000013")
    await _abierto(negocio["id"])
    await mem.crear_usuario("ase_fhc3", "pw12345", "Asesor", "asesor", negocio["id"])
    await mem.guardar_configuracion("cola_apertura_max_por_corrida", "1", negocio_id=negocio["id"])
    for i in range(3):
        await _lead_derivado_sin_asesor(f"5192000002{i}", negocio, canal, 3 + i)

    resultado = await asignacion.asignar_cola_pendiente_al_abrir()

    assert len(resultado["asignados"]) == 1 and resultado["pendientes"] == 2


async def test_el_tope_por_defecto_es_10():
    assert asignacion.COLA_APERTURA_MAX_POR_CORRIDA_DEFAULT == 10
    negocio, _ = await _negocio_con_canal("fh-c-3b", "40500000023")
    assert await asignacion._limite_por_corrida(negocio["id"]) == 10
    await mem.guardar_configuracion("cola_apertura_max_por_corrida", "basura", negocio_id=negocio["id"])
    assert await asignacion._limite_por_corrida(negocio["id"]) == 10


async def test_con_el_negocio_cerrado_el_cron_no_asigna_nada():
    negocio, canal = await _negocio_con_canal("fh-c-4", "40500000014")
    await _cerrado(negocio["id"])
    await mem.crear_usuario("ase_fhc4", "pw12345", "Asesor", "asesor", negocio["id"])
    await _lead_derivado_sin_asesor("51920000031", negocio, canal, 3)

    resultado = await asignacion.asignar_cola_pendiente_al_abrir()

    assert resultado["asignados"] == []
    assert (await _lead("51920000031")).asesor_asignado is None


async def test_sin_asesores_disponibles_no_asigna_y_el_lead_sigue_en_la_cola():
    negocio, canal = await _negocio_con_canal("fh-c-5", "40500000015")
    await _abierto(negocio["id"])
    await mem.crear_usuario("ase_fhc5", "pw12345", "Asesor", "asesor", negocio["id"])
    await mem.actualizar_disponibilidad("ase_fhc5", negocio["id"], False)
    await _lead_derivado_sin_asesor("51920000041", negocio, canal, 3)

    resultado = await asignacion.asignar_cola_pendiente_al_abrir()

    assert resultado == {"asignados": [], "pendientes": 1}
    assert (await _lead("51920000041")).asesor_asignado is None


async def test_la_cola_no_toca_escalados_pausados_cerrados_ni_los_que_ya_tienen_asesor():
    negocio, canal = await _negocio_con_canal("fh-c-6", "40500000016")
    await _abierto(negocio["id"])
    await mem.crear_usuario("ase_fhc6", "pw12345", "Asesor", "asesor", negocio["id"])
    await mem.crear_usuario("ase_fhc6b", "pw12345", "Asesor B", "asesor", negocio["id"])
    for tel in ("51920000051", "51920000052", "51920000053", "51920000054", "51920000055"):
        await _lead_derivado_sin_asesor(tel, negocio, canal, 3)
    await mem.enviar_a_cola_de_supervision("51920000051")               # escalado a supervisión
    await mem.pausar_gabi_manual("51920000052")                          # pausado a mano (sin mensaje humano)
    await mem.actualizar_lead("51920000053", campos_explicitos=("resultado",), resultado="sin_respuesta")  # cerrado
    await mem.asignar_asesor_a_lead("51920000054", "ase_fhc6b")          # ya tiene dueño

    resultado = await asignacion.asignar_cola_pendiente_al_abrir()

    assert [t for t, _ in resultado["asignados"]] == ["51920000055"]
    assert (await _lead("51920000051")).asesor_asignado is None and (await _lead("51920000051")).escalado_supervision_en
    assert (await _lead("51920000052")).asesor_asignado is None
    assert (await _lead("51920000053")).asesor_asignado is None
    assert (await _lead("51920000054")).asesor_asignado == "ase_fhc6b"  # no se reasigna


async def test_la_cola_no_reparte_un_lead_que_una_persona_ya_atendio():
    negocio, canal = await _negocio_con_canal("fh-c-7", "40500000017")
    await _abierto(negocio["id"])
    await mem.crear_usuario("ase_fhc7", "pw12345", "Asesor", "asesor", negocio["id"])
    telefono = "51920000061"
    await _lead_derivado_sin_asesor(telefono, negocio, canal, 5)
    await _mensaje(telefono, negocio["id"], "asesor", 4)  # un asesor contestó después del cliente

    resultado = await asignacion.asignar_cola_pendiente_al_abrir()

    assert resultado["asignados"] == []


async def test_la_cola_reparte_entre_los_asesores_por_carga():
    negocio, canal = await _negocio_con_canal("fh-c-8", "40500000018")
    await _abierto(negocio["id"])
    await mem.crear_usuario("ase_fhc8a", "pw12345", "Asesor A", "asesor", negocio["id"])
    await mem.crear_usuario("ase_fhc8b", "pw12345", "Asesor B", "asesor", negocio["id"])
    for i in range(4):
        await _lead_derivado_sin_asesor(f"5192000007{i}", negocio, canal, 2 + i)

    resultado = await asignacion.asignar_cola_pendiente_al_abrir()

    asesores = [a for _, a in resultado["asignados"]]
    assert sorted(asesores) == ["ase_fhc8a", "ase_fhc8a", "ase_fhc8b", "ase_fhc8b"]


async def test_el_cron_imprime_cuantos_asigno(capsys, monkeypatch):
    negocio, canal = await _negocio_con_canal("fh-c-9", "40500000019")
    await _abierto(negocio["id"])
    await mem.crear_usuario("ase_fhc9", "pw12345", "Asesor", "asesor", negocio["id"])
    await _lead_derivado_sin_asesor("51920000081", negocio, canal, 3)
    spec = importlib.util.spec_from_file_location("script_liberar_q1", RAIZ / "scripts" / "liberar_leads_inactivos.py")
    script = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(script)

    async def sin_espera():
        return None

    monkeypatch.setattr(script, "esperar_base_de_datos", sin_espera)
    await script.main()

    salida = capsys.readouterr().out
    assert "Cola al abrir: asignó 1 lead(s)" in salida
    assert (await _lead("51920000081")).asesor_asignado == "ase_fhc9"

    await script.main()  # idempotente: ahora no queda nada
    assert "Cola al abrir: asignó 0 lead(s)." in capsys.readouterr().out


# ── 3. Sin reenganche de 2 h ni cierre de 15 h ────────────────────────────────

async def test_un_lead_derivado_sin_asesor_no_recibe_reenganche_ni_cierre():
    negocio, canal = await _negocio_con_canal("fh-i-1", "40500000021")
    telefono = "51930000001"
    await _lead_derivado_sin_asesor(telefono, negocio, canal, 40)
    await _mensaje(telefono, negocio["id"], "assistant", 39)

    reenganche, cierre = await mem.listar_leads_inactividad_cliente(horas_reenganche=2.0, horas_cierre=15.0)

    assert telefono not in {c["telefono"] for c in reenganche + cierre}


async def test_un_lead_escalado_a_supervision_no_recibe_reenganche_ni_cierre():
    negocio, canal = await _negocio_con_canal("fh-i-2", "40500000022")
    telefono = "51930000002"
    await mem.resolver_conversation_activa(telefono, negocio["id"], canal["id"])
    await mem.actualizar_lead(telefono, nombre="Cliente Test", negocio_id=negocio["id"])
    await _mensaje(telefono, negocio["id"], "user", 40)
    await _mensaje(telefono, negocio["id"], "assistant", 39)
    async with mem.async_session() as session:  # escalado sin paso_flujo derivado: solo la marca de supervisión
        lead = await session.get(mem.Lead, telefono)
        lead.escalado_supervision_en = datetime.utcnow()
        await session.commit()

    reenganche, cierre = await mem.listar_leads_inactividad_cliente(horas_reenganche=2.0, horas_cierre=15.0)

    assert telefono not in {c["telefono"] for c in reenganche + cierre}


async def test_los_demas_leads_siguen_con_el_reenganche_y_el_cierre_de_siempre():
    negocio, canal = await _negocio_con_canal("fh-i-3", "40500000023")
    for tel, paso in (("51930000003", "explorando"), ("51930000004", None), ("51930000005", "comparando_producto")):
        await mem.resolver_conversation_activa(tel, negocio["id"], canal["id"])
        await mem.actualizar_lead(tel, nombre="Cliente Test", negocio_id=negocio["id"])
        if paso:
            await mem.actualizar_lead(tel, negocio_id=negocio["id"], campos_explicitos=("paso_flujo",), paso_flujo=paso)
    await _mensaje("51930000003", negocio["id"], "user", 3)
    await _mensaje("51930000003", negocio["id"], "assistant", 2.9)
    await _mensaje("51930000004", negocio["id"], "user", 20)
    await _mensaje("51930000004", negocio["id"], "assistant", 19.9)
    await _mensaje("51930000005", negocio["id"], "user", 20)
    await _mensaje("51930000005", negocio["id"], "assistant", 19.9)

    reenganche, cierre = await mem.listar_leads_inactividad_cliente(horas_reenganche=2.0, horas_cierre=15.0)

    assert {c["telefono"] for c in reenganche} == {"51930000003"}
    assert {c["telefono"] for c in cierre} == {"51930000004", "51930000005"}


async def test_la_falla_de_la_ia_sigue_marcando_tras_falla_ia_en_un_lead_normal():
    negocio, canal = await _negocio_con_canal("fh-i-4", "40500000024")
    telefono = "51930000006"
    await mem.resolver_conversation_activa(telefono, negocio["id"], canal["id"])
    await mem.actualizar_lead(telefono, nombre="Cliente Test", negocio_id=negocio["id"])
    await _mensaje(telefono, negocio["id"], "user", 3)
    texto_error = sorted(mem.textos_de_error_tecnico_conocidos())[0]
    guardado = await mem.guardar_mensaje(telefono, "assistant", texto_error, negocio["id"])
    async with mem.async_session() as session:
        msg = await session.get(mem.Mensaje, guardado["id"])
        msg.timestamp = datetime.utcnow() - timedelta(hours=2.9)
        await session.commit()

    reenganche, _ = await mem.listar_leads_inactividad_cliente(horas_reenganche=2.0, horas_cierre=15.0)

    assert [c.get("tras_falla_ia") for c in reenganche if c["telefono"] == telefono] == [True]


# ── 4. El correo dice la verdad ───────────────────────────────────────────────

class _Respuesta:
    status_code = 200
    text = "ok"


async def _correo(monkeypatch, lead: dict, **kwargs) -> dict:
    enviados = []

    async def post(url, json=None, headers=None):
        enviados.append(json)
        return _Respuesta()

    monkeypatch.setattr(notificaciones, "RESEND_API_KEY", "clave-de-prueba")
    monkeypatch.setattr(notificaciones, "DESTINATARIOS", ["equipo@example.com"])
    monkeypatch.setattr(notificaciones, "post_con_reintentos", post)
    assert await notificaciones.notificar_lead_derivado("51940000001", lead, "hola", **kwargs)
    return enviados[0]


async def test_el_correo_fuera_de_horario_dice_que_no_hay_asesor_en_turno(monkeypatch):
    correo = await _correo(monkeypatch, {"nombre": "Cliente"}, fuera_de_horario=True)

    assert "No hay asesor en turno" in correo["html"]
    assert "primer asesor que abra turno" in correo["html"]
    assert "fuera de horario" in correo["subject"]


async def test_el_correo_dentro_de_horario_sin_asesor_conserva_el_texto_de_siempre(monkeypatch):
    correo = await _correo(monkeypatch, {"nombre": "Cliente"}, fuera_de_horario=False)

    assert "Ningún asesor estaba disponible" in correo["html"]
    assert "SIN ASESOR DISPONIBLE" in correo["subject"]


async def test_el_correo_calcula_solo_si_el_negocio_esta_cerrado(monkeypatch):
    negocio, _ = await _negocio_con_canal("fh-m-1", "40500000031")
    await _cerrado(negocio["id"])

    correo = await _correo(monkeypatch, {"nombre": "Cliente", "negocio_id": negocio["id"]})

    assert "No hay asesor en turno" in correo["html"]


async def test_el_correo_con_asesor_asignado_no_cambia(monkeypatch):
    correo = await _correo(monkeypatch, {"nombre": "Cliente", "asesor_asignado": "ase_x"})

    assert "Asignado automáticamente a:" in correo["html"] and "ase_x" in correo["subject"]


# ── 5. Reinicio de contadores de rotación ─────────────────────────────────────

async def test_una_asignacion_automatica_nueva_reinicia_los_contadores_de_rotacion():
    negocio, canal = await _negocio_con_canal("fh-r-1", "40500000041")
    await mem.crear_usuario("ase_fhr1", "pw12345", "Asesor", "asesor", negocio["id"])
    telefono = "51950000001"
    await _lead_derivado_sin_asesor(telefono, negocio, canal, 3)
    async with mem.async_session() as session:  # secuelas de un ciclo anterior (rotado una vez, 20 min contados)
        lead = await session.get(mem.Lead, telefono)
        lead.minutos_espera_asesor, lead.veces_rotado_espera = 20, 1
        await session.commit()

    await mem.asignar_asesor_a_lead(telefono, "ase_fhr1", automatico=True)

    lead = await _lead(telefono)
    assert (lead.minutos_espera_asesor, lead.veces_rotado_espera) == (0, 0)
    assert lead.derivado_en is not None


async def test_la_rotacion_sigue_dejando_veces_rotado_en_1():
    negocio, canal = await _negocio_con_canal("fh-r-2", "40500000042")
    await mem.crear_usuario("ase_fhr2a", "pw12345", "Asesor A", "asesor", negocio["id"])
    await mem.crear_usuario("ase_fhr2b", "pw12345", "Asesor B", "asesor", negocio["id"])
    telefono = "51950000002"
    await _lead_derivado_sin_asesor(telefono, negocio, canal, 3)
    await mem.asignar_asesor_a_lead(telefono, "ase_fhr2a", automatico=True)

    await mem.rotar_asignacion_por_inactividad(telefono, "ase_fhr2a", "ase_fhr2b", 30)

    lead = await _lead(telefono)
    assert (lead.asesor_asignado, lead.minutos_espera_asesor, lead.veces_rotado_espera) == ("ase_fhr2b", 0, 1)


async def test_una_asignacion_manual_no_arma_el_reloj_de_rotacion():
    negocio, canal = await _negocio_con_canal("fh-r-3", "40500000043")
    await mem.crear_usuario("ase_fhr3", "pw12345", "Asesor", "asesor", negocio["id"])
    telefono = "51950000003"
    await _lead_derivado_sin_asesor(telefono, negocio, canal, 3)

    await mem.asignar_asesor_a_lead(telefono, "ase_fhr3")  # manual: derivado_en queda en None, nadie lo monitorea

    lead = await _lead(telefono)
    assert lead.derivado_en is None
