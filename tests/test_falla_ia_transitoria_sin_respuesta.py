# tests/test_falla_ia_transitoria_sin_respuesta.py — 2026-10-06, falla transitoria ÚNICA de la IA.
#
# Caso real (Sandra, 04/10): Claude falló una vez (5xx/429/timeout) en el primer turno; el panel guardó como
# "respuesta" de Gabi el texto técnico de `error_message` y, como el cliente no volvió, el contador de fallos
# nunca llegó a 2: nadie lo derivó, el Cron de inactividad le mandó "¡Hola de nuevo!" y a las 15 h lo cerró
# como sin_respuesta; el barrido de mensajes sin respuesta tampoco lo veía (el texto de error contaba como
# respuesta). Cubre:
#   1. el texto de error técnico NO cuenta como respuesta real (barrido + recuperación + derivación);
#   2. el Cron de inactividad deriva a una persona (no reengancha ni cierra en silencio);
#   3. el diagnóstico de solo lectura `listar_leads_afectados_por_falla_ia` y su script;
#   4. no-regresión de los caminos normales.

import importlib.util
import json
import os
from datetime import datetime, timedelta
from pathlib import Path

os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")
os.environ.setdefault("WHATSAPP_PROVIDER", "meta")

import pytest
from sqlalchemy import func, select

from agent import brain, circuito_ia, notificaciones, politica_envios, respaldo_sin_ia
from agent import main as app_main
from agent import memory as mem

RAIZ = Path(__file__).resolve().parent.parent
TEXTO_ERROR = brain.obtener_mensaje_error()
REENGANCHE = (
    "¡Hola de nuevo! 👋 Sigo por aquí si tienes alguna otra pregunta o quieres "
    "retomar donde quedamos. Cuéntame en qué te puedo ayudar 😊"
)
TEXTO_DENTRO = "¡Hola, Cliente! 👋 Gracias por escribirnos. Te estoy transfiriendo con un asesor de nuestro equipo, que te atenderá por este mismo chat en unos minutos. 😊"


# ── Fixtures y helpers ───────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _aislamiento(monkeypatch):
    circuito_ia.reiniciar_memoria()

    async def alerta(abierto, motivo, resumen=None):
        return True

    monkeypatch.setattr(notificaciones, "notificar_circuito_ia", alerta)
    monkeypatch.setattr(circuito_ia, "_crear_cliente_sondeo", lambda: pytest.fail("el sondeo no debía crear un cliente"))
    politica_envios.limpiar_cache()
    yield
    circuito_ia.reiniciar_memoria()


def _cargar_script(nombre: str):
    spec = importlib.util.spec_from_file_location(f"falla_ia_{nombre}", RAIZ / "scripts" / f"{nombre}.py")
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


class _Proveedor:
    def __init__(self):
        self.enviados: list[tuple[str, str]] = []

    async def resolver_canal(self, numero_whatsapp_id, negocio_id=None):
        return {"id": 1, "negocio_id": negocio_id, "unidad_id": None, "phone_number_id": numero_whatsapp_id, "modo": "produccion"}

    async def enviar_mensaje(self, telefono, mensaje, canal=None, mensaje_id_citado=None):
        self.enviados.append((telefono, mensaje))
        return True, f"wamid.falla.{len(self.enviados)}"


async def _negocio(codigo: str, asesores=("ase_a",)):
    negocio = await mem.crear_negocio(f"Negocio {codigo}", codigo)
    canal_db = await mem.crear_canal_whatsapp(
        nombre=f"Canal {codigo}", phone_number_id=f"4099{int(codigo[-3:]):06d}", negocio_id=negocio["id"],
    )
    canal = {"id": canal_db["id"], "negocio_id": negocio["id"], "unidad_id": None,
             "phone_number_id": canal_db["phone_number_id"], "modo": "produccion"}
    for dia in range(7):
        await mem.guardar_horario_atencion(negocio["id"], dia, True, "00:00", "23:59")
    for username in asesores:
        await mem.crear_usuario(username, "pw12345", username.title(), "asesor", negocio["id"])
    return negocio, canal


async def _lead(negocio, canal, telefono: str, **campos_lead):
    """Lead que Gabi atiende sola; `campos_lead` se fijan directo en la fila (resultado, asesor, pausa…)."""
    await mem.resolver_conversation_activa(telefono, negocio["id"], canal["id"])
    await mem.actualizar_lead(telefono, nombre="Cliente", interes="terma", negocio_id=negocio["id"], numero_whatsapp_id=canal["phone_number_id"])
    if campos_lead:
        async with mem.async_session() as session:
            lead = await session.get(mem.Lead, telefono)
            for campo, valor in campos_lead.items():
                setattr(lead, campo, valor)
            await session.commit()


async def _msg(negocio, telefono: str, role: str, contenido: str, hace_min: float, **kwargs):
    guardado = await mem.guardar_mensaje(telefono, role, contenido, negocio["id"], **kwargs)
    async with mem.async_session() as session:
        m = await session.get(mem.Mensaje, guardado["id"])
        m.timestamp = datetime.utcnow() - timedelta(minutes=hace_min)
        await session.commit()
    return guardado


async def _falla(negocio, telefono: str, hace_min: float, texto_cliente: str = "hola, quiero una terma", con_reenganche_hace=None):
    """El rastro del caso real: el cliente escribe y Gabi contesta solo el texto de error técnico."""
    cliente = await _msg(negocio, telefono, "user", texto_cliente, hace_min)
    await _msg(negocio, telefono, "assistant", TEXTO_ERROR, hace_min - 0.1)
    if con_reenganche_hace is not None:
        await _msg(negocio, telefono, "assistant", REENGANCHE, con_reenganche_hace)
    return cliente


async def _lead_db(telefono: str) -> mem.Lead:
    async with mem.async_session() as session:
        return await session.get(mem.Lead, telefono)


async def _eventos(telefono: str, tipo: str) -> list[dict]:
    return [e for e in await mem.listar_eventos_lead(telefono) if e["tipo"] == tipo]


async def _canal_ok(numero_whatsapp_id, negocio_id=None):
    return {"id": 1, "negocio_id": negocio_id, "unidad_id": None, "phone_number_id": numero_whatsapp_id, "modo": "produccion"}


def _script_recuperar():
    script = _cargar_script("recuperar_mensajes_sin_respuesta")
    script.derivaciones = []

    async def derivar_falso(telefono, canal, motivo):
        script.derivaciones.append((telefono, motivo))
        return {"accion": "derivado_asesor", "asesor": None, "texto_enviado": False}

    script._derivar_real = derivar_falso
    return script


# ═══════════════════════════════════════════════════════════════════════════
# 1a. Reconocer el texto de error técnico
# ═══════════════════════════════════════════════════════════════════════════

def test_reconoce_el_texto_configurado_los_historicos_y_variantes_retocadas():
    assert mem.es_texto_de_error_tecnico(TEXTO_ERROR)
    assert mem.es_texto_de_error_tecnico("Uy, estoy teniendo un problema técnico. Por favor intenta de nuevo en unos minutos 🙏")
    assert mem.es_texto_de_error_tecnico("Lo siento, estoy teniendo problemas técnicos. Por favor intenta de nuevo en unos minutos.")
    assert mem.es_texto_de_error_tecnico("  UY, ESTOY TENIENDO UN PROBLEMA TECNICO!!  intenta de nuevo en un rato 🙏 ")  # sin tildes/mayúsculas/emoji
    assert mem.es_texto_de_error_tecnico("Tuvimos un problema técnico, por favor intenta de nuevo más tarde")  # redacción retocada


def test_reconoce_el_texto_que_este_configurado_en_el_yaml_aunque_cambie(monkeypatch):
    monkeypatch.setattr(brain, "obtener_mensaje_error", lambda: "Ups, se nos cruzaron los cables. Escríbenos otra vez en un ratito")
    assert mem.es_texto_de_error_tecnico("Ups, se nos cruzaron los cables. Escríbenos otra vez en un ratito!")


@pytest.mark.parametrize("texto", [
    None, "", "   ",
    "¡Hola! Cuéntame, ¿qué terma te interesa?",
    "Sigo con problemas técnicos, ya te conecto con un asesor. También puedes llamarnos al 614-9002.",  # escalado: es real
    "El problema técnico de tu terma lo revisa el técnico; intenta de nuevo el encendido y me avisas " + "x" * 200,  # largo
    "Mi problema es técnico, ¿puedes ayudarme?",   # dicho por un cliente: sin "intenta de nuevo"
    "Te derivo con un asesor 🙏",
])
def test_no_confunde_mensajes_reales_con_el_aviso_tecnico(texto):
    assert not mem.es_texto_de_error_tecnico(texto)


def test_reconoce_el_reenganche_automatico_y_no_otros_mensajes():
    assert mem.es_texto_de_reenganche_automatico(REENGANCHE)
    assert not mem.es_texto_de_reenganche_automatico("¡Hola! Cuéntame más")
    assert not mem.es_texto_de_reenganche_automatico(None)


# ═══════════════════════════════════════════════════════════════════════════
# 1b. Barrido de mensajes sin respuesta
# ═══════════════════════════════════════════════════════════════════════════

async def _sin_respuesta(**kwargs) -> dict[str, dict]:
    return {f["telefono"]: f for f in await mem.listar_mensajes_sin_respuesta_de_gabi(**kwargs)}


async def test_el_barrido_ve_un_mensaje_seguido_solo_del_texto_de_error_como_sin_respuesta():
    negocio, canal = await _negocio("fia-001")
    tel = "51910000001"
    await _lead(negocio, canal, tel)
    cliente = await _falla(negocio, tel, hace_min=10)

    filas = await _sin_respuesta()

    assert set(filas) == {tel}
    assert filas[tel]["tras_falla_ia"] is True and filas[tel]["intentos"] == 0
    assert filas[tel]["mensaje_id"] == cliente["id"]


async def test_el_reenganche_que_siguio_al_error_tampoco_cuenta_como_respuesta():
    negocio, canal = await _negocio("fia-002")
    tel = "51910000002"
    await _lead(negocio, canal, tel)
    await _falla(negocio, tel, hace_min=10, con_reenganche_hace=2)

    assert (await _sin_respuesta())[tel]["tras_falla_ia"] is True


async def test_una_reaccion_despues_del_error_no_lo_tapa():
    negocio, canal = await _negocio("fia-003")
    tel = "51910000003"
    await _lead(negocio, canal, tel)
    await _falla(negocio, tel, hace_min=10)
    await _msg(negocio, tel, "user", "Reaccionó con 👍", 5)

    assert tel in await _sin_respuesta()


async def test_un_mensaje_real_despues_del_error_lo_saca_del_barrido():
    negocio, canal = await _negocio("fia-004")
    tel, tel_asesor = "51910000004", "51910000005"
    for t in (tel, tel_asesor):
        await _lead(negocio, canal, t)
        await _falla(negocio, t, hace_min=10)
    await _msg(negocio, tel, "assistant", "¡Hola! Disculpa la demora, ¿qué terma buscas?", 5)                # Gabi, ya real
    await _msg(negocio, tel_asesor, "assistant", "Hola, soy Pedro, te ayudo con tu terma", 5, via_app=True)  # una persona

    assert await _sin_respuesta() == {}


@pytest.mark.parametrize("campos", [
    {"asesor_asignado": "ase_a"},
    {"pausado_manual": True},
    {"escalado_supervision_en": datetime.utcnow()},
    {"cerrado_definitivamente_en": datetime.utcnow()},
    {"resultado": "vendido"}, {"resultado": "agendado"}, {"resultado": "postventa"},
    {"resultado": "no_interesado"}, {"resultado": "sin_respuesta"},
])
async def test_las_exclusiones_de_siempre_se_respetan_tambien_tras_una_falla(campos):
    negocio, canal = await _negocio("fia-005")
    tel = "51910000006"
    await _lead(negocio, canal, tel, **campos)
    await _falla(negocio, tel, hace_min=10)

    assert await _sin_respuesta() == {}


async def test_conversacion_cerrada_no_se_recupera_aunque_el_lead_no_tenga_marca():
    negocio, canal = await _negocio("fia-006")
    tel = "51910000007"
    await _lead(negocio, canal, tel)
    await _falla(negocio, tel, hace_min=10)
    async with mem.async_session() as session:
        contact = await mem._obtener_contact(session, negocio["id"], tel)
        conversation = await mem._obtener_conversation_activa(session, contact.id)
        conversation.pausado_manual = True
        await session.commit()

    assert await _sin_respuesta() == {}


async def test_ventana_de_tiempo_y_tope_de_intentos_se_respetan():
    negocio, canal = await _negocio("fia-007")
    reciente, viejo, agotado = "51910000008", "51910000009", "51910000010"
    for t in (reciente, viejo, agotado):
        await _lead(negocio, canal, t)
    await _falla(negocio, reciente, hace_min=1)            # menos de 3 min: el debounce aún puede estar trabajando
    await _falla(negocio, viejo, hace_min=60 * 25)         # >20 h
    cliente = await _falla(negocio, agotado, hace_min=30)
    for _ in range(2):
        await mem.registrar_evento_lead(agotado, tipo=mem.TIPO_EVENTO_RESPUESTA_RECUPERADA, descripcion="intento", autor=None, payload={"mensaje_id": cliente["id"]})

    assert await _sin_respuesta(max_intentos=2) == {}
    assert set(await _sin_respuesta(max_horas=72)) == {viejo, agotado}  # sin tope de intentos, y la ventana ancha del paso de "agotados"


async def test_no_regresion_barrido_normal_sin_respuesta_sigue_igual():
    negocio, canal = await _negocio("fia-008")
    sin_responder, respondido = "51910000011", "51910000012"
    for t in (sin_responder, respondido):
        await _lead(negocio, canal, t)
        await _msg(negocio, t, "user", "hola, quiero una terma", 10)
    await _msg(negocio, respondido, "assistant", "¡Hola! ¿Cuál terma?", 9)

    filas = await _sin_respuesta()

    assert set(filas) == {sin_responder} and filas[sin_responder]["tras_falla_ia"] is False


async def test_no_regresion_un_reenganche_solo_no_convierte_un_lead_en_candidato():
    """Sin texto de error en medio, «cliente → respuesta real → reenganche» sigue sin ser un caso a recuperar."""
    negocio, canal = await _negocio("fia-009")
    tel = "51910000013"
    await _lead(negocio, canal, tel)
    await _msg(negocio, tel, "user", "hola", 30)
    await _msg(negocio, tel, "assistant", "¡Hola! ¿Qué buscas?", 29)
    await _msg(negocio, tel, "assistant", REENGANCHE, 10)

    assert await _sin_respuesta() == {}


# ═══════════════════════════════════════════════════════════════════════════
# 1c. Script de recuperación
# ═══════════════════════════════════════════════════════════════════════════

async def test_el_script_reintenta_el_mensaje_tras_la_falla_y_si_responde_queda_resuelto():
    script = _script_recuperar()
    negocio, canal = await _negocio("fia-010")
    tel = "51910000020"
    await _lead(negocio, canal, tel)
    await _falla(negocio, tel, hace_min=10)
    atendidos = []

    async def generar(telefono, canal_):
        atendidos.append(telefono)
        await mem.guardar_mensaje(telefono, "assistant", "¡Hola! Cuéntame, ¿qué terma buscas?", negocio["id"])

    resumen = await script.recuperar_mensajes_sin_respuesta(generar_respuesta=generar, resolver_canal=_canal_ok)

    assert atendidos == [tel] and resumen["intentados"] == 1 and resumen["derivados_agotados"] == 0
    assert len(await _eventos(tel, mem.TIPO_EVENTO_RESPUESTA_RECUPERADA)) == 1
    assert (await script.recuperar_mensajes_sin_respuesta(generar_respuesta=generar, resolver_canal=_canal_ok))["encontrados"] == 0
    assert script.derivaciones == []


async def test_el_script_hace_maximo_dos_intentos_y_agotados_deriva_con_el_motivo_de_falla_de_ia():
    script = _script_recuperar()
    negocio, canal = await _negocio("fia-011")
    tel = "51910000021"
    await _lead(negocio, canal, tel)
    await _falla(negocio, tel, hace_min=10)
    intentos = []

    async def generar_sin_efecto(telefono, canal_):
        intentos.append(telefono)   # sigue sin respuesta real

    for _ in range(4):
        await script.recuperar_mensajes_sin_respuesta(generar_respuesta=generar_sin_efecto, resolver_canal=_canal_ok)

    assert intentos == [tel, tel]
    assert set(script.derivaciones) == {(tel, "sin_respuesta_por_falla_ia")}


async def test_una_falla_de_ia_ya_vencida_sin_reintentar_se_deriva_igual_y_un_mensaje_normal_vencido_no():
    script = _script_recuperar()
    negocio, canal = await _negocio("fia-012")
    con_falla, normal_vencido = "51910000022", "51910000023"
    await _lead(negocio, canal, con_falla)
    await _lead(negocio, canal, normal_vencido)
    await _falla(negocio, con_falla, hace_min=60 * 30)                                  # 30 h: ya no se reintenta con la IA
    await _msg(negocio, normal_vencido, "user", "hola", 60 * 30)                        # comportamiento de hoy: se deja
    intentos = []

    async def generar(telefono, canal_):
        intentos.append(telefono)

    resumen = await script.recuperar_mensajes_sin_respuesta(generar_respuesta=generar, resolver_canal=_canal_ok)

    assert intentos == [] and resumen["derivados_agotados"] == 1
    assert script.derivaciones == [(con_falla, "sin_respuesta_por_falla_ia")]


async def test_si_el_reintento_vuelve_a_fallar_y_deriva_el_barrido_lo_cuenta_como_falla_de_ia():
    """La 2.ª falla deriva y REINICIA fallos_tecnicos: sin mirar el evento `derivado_sin_ia` el barrido creería
    que funcionó y seguiría golpeando a una IA caída."""
    script = _script_recuperar()
    negocio, canal = await _negocio("fia-013")
    telefonos = ["51910000024", "51910000025", "51910000026"]
    for i, t in enumerate(telefonos):
        await _lead(negocio, canal, t)
        await _falla(negocio, t, hace_min=20 + i)
    atendidos = []

    async def generar_que_falla_y_deriva(telefono, canal_):
        atendidos.append(telefono)
        await mem.registrar_evento_lead(
            telefono, tipo=mem.TIPO_EVENTO_DERIVADO_SIN_IA, descripcion="derivado", autor=None,
            payload={"motivo": "falla_tecnica_repetida", "destino": "asesor"},
        )
        await mem.resetear_fallos_tecnicos(telefono)

    resumen = await script.recuperar_mensajes_sin_respuesta(generar_respuesta=generar_que_falla_y_deriva, resolver_canal=_canal_ok)

    assert resumen["ia_caida"] is True and resumen["fallos_ia"] == 2 and len(atendidos) == 2   # se detuvo, no insistió con el 3.º


async def test_con_el_circuito_abierto_el_barrido_no_toca_un_caso_tras_falla():
    script = _script_recuperar()
    negocio, canal = await _negocio("fia-014")
    tel = "51910000027"
    await _lead(negocio, canal, tel)
    await _falla(negocio, tel, hace_min=10)
    await circuito_ia.abrir("credito")

    async def generar(*a):
        raise AssertionError("con el circuito abierto no se recupera nada")

    resumen = await script.recuperar_mensajes_sin_respuesta(generar_respuesta=generar, resolver_canal=_canal_ok)

    assert resumen["circuito_abierto"] is True and resumen["intentados"] == 0 and script.derivaciones == []


# ═══════════════════════════════════════════════════════════════════════════
# 1d. El camino real de la respuesta (agent.main) puede reintentar tras la falla
# ═══════════════════════════════════════════════════════════════════════════

def test_los_avisos_automaticos_finales_se_quitan_solo_si_hay_un_error_tecnico():
    u = {"role": "user", "content": "hola"}
    real = {"role": "assistant", "content": "¡Hola! ¿Qué buscas?"}
    error = {"role": "assistant", "content": TEXTO_ERROR}
    reenganche = {"role": "assistant", "content": REENGANCHE}
    quitar = app_main._sin_avisos_automaticos_finales

    assert quitar([real, u, error]) == [real, u]
    assert quitar([real, u, error, reenganche]) == [real, u]
    assert quitar([real, u, reenganche]) == [real, u, reenganche]     # sin error: tal cual (no es este caso)
    assert quitar([u, real, error]) == [u, real]                      # un error DESPUÉS de una respuesta real: solo se quita el aviso
    assert quitar([u, error, real]) == [u, error, real]               # un error viejo en medio no se toca
    assert quitar([u]) == [u] and quitar([]) == []


async def _armar_flujo_real(monkeypatch, codigo: str, asesores=("ase_a",)):
    negocio, canal = await _negocio(codigo, asesores=asesores)
    tel = "51910000030"
    await _lead(negocio, canal, tel)

    async def dentro(negocio_id):
        return {"dentro_de_horario": True, "fecha_hora_lima": "x"}

    monkeypatch.setattr(respaldo_sin_ia, "obtener_estado_horario_atencion", dentro)
    proveedor = _Proveedor()
    monkeypatch.setattr(app_main, "proveedor", proveedor)
    return negocio, canal, tel, proveedor


async def test_el_reintento_ve_el_mensaje_del_cliente_como_ultimo_turno_y_responde_de_verdad(monkeypatch):
    negocio, canal, tel, proveedor = await _armar_flujo_real(monkeypatch, "fia-015")
    await _msg(negocio, tel, "user", "¿cuánto cuesta la terma de 80 litros?", 15)
    await _msg(negocio, tel, "assistant", TEXTO_ERROR, 14.9)
    visto = {}

    async def respuesta_de_gabi(mensaje, historial, lead, modo="produccion", negocio_id=None):
        visto.update(mensaje=mensaje, historial=historial)
        return "La terma de 80 litros cuesta S/ 599 🙌", False, None, None

    async def sin_datos(*a, **k):
        return {}

    monkeypatch.setattr(app_main.servicio_inteligencia, "generar_respuesta", respuesta_de_gabi)
    monkeypatch.setattr(app_main.servicio_inteligencia, "extraer_datos_lead", sin_datos)

    await app_main._generar_y_enviar_respuesta_ia(tel, canal)

    assert visto["mensaje"] == "¿cuánto cuesta la terma de 80 litros?"
    assert all(m["content"] != TEXTO_ERROR for m in visto["historial"])      # Claude no ve su propio "problema técnico"
    assert [m for _, m in proveedor.enviados] == ["La terma de 80 litros cuesta S/ 599 🙌"]
    assert (await _sin_respuesta()) == {}                                     # ya no está pendiente


async def test_si_el_reintento_vuelve_a_fallar_deriva_a_un_asesor_sin_repetir_el_texto_tecnico(monkeypatch):
    negocio, canal, tel, proveedor = await _armar_flujo_real(monkeypatch, "fia-016")
    await _msg(negocio, tel, "user", "hola, quiero una terma", 15)
    await _msg(negocio, tel, "assistant", TEXTO_ERROR, 14.9)
    await mem.registrar_fallo_tecnico(tel)           # la falla original dejó el contador en 1

    async def falla(mensaje, historial, lead, modo="produccion", negocio_id=None):
        return TEXTO_ERROR, True, None, None

    monkeypatch.setattr(app_main.servicio_inteligencia, "generar_respuesta", falla)

    await app_main._generar_y_enviar_respuesta_ia(tel, canal)

    lead = await _lead_db(tel)
    assert lead.asesor_asignado == "ase_a" and lead.paso_flujo == "derivado_asesor"
    assert [m for _, m in proveedor.enviados] == [TEXTO_DENTRO]               # un solo texto, el automático; no el técnico
    (evento,) = await _eventos(tel, mem.TIPO_EVENTO_DERIVADO_SIN_IA)
    assert evento["payload"]["motivo"] == "falla_tecnica_repetida"


async def test_no_regresion_un_historial_que_termina_en_asistente_sin_error_se_sigue_descartando(monkeypatch):
    negocio, canal, tel, proveedor = await _armar_flujo_real(monkeypatch, "fia-017")
    await _msg(negocio, tel, "user", "hola", 15)
    await _msg(negocio, tel, "assistant", "¡Hola! ¿Qué buscas?", 14)

    async def no_debe_llamarse(*a, **k):
        raise AssertionError("no hay un mensaje del cliente pendiente")

    monkeypatch.setattr(app_main.servicio_inteligencia, "generar_respuesta", no_debe_llamarse)
    await app_main._generar_y_enviar_respuesta_ia(tel, canal)

    assert proveedor.enviados == []


# ═══════════════════════════════════════════════════════════════════════════
# 2. Inactividad del cliente: deriva, no reengancha ni cierra en silencio
# ═══════════════════════════════════════════════════════════════════════════

async def test_la_consulta_marca_los_leads_con_falla_y_los_reparte_por_tiempo():
    negocio, canal = await _negocio("fia-020")
    a_las_3h, a_las_16h, con_reenganche_16h, a_la_1h, normal_3h = (f"5191000004{i}" for i in range(5))
    for t in (a_las_3h, a_las_16h, con_reenganche_16h, a_la_1h, normal_3h):
        await _lead(negocio, canal, t)
    await _falla(negocio, a_las_3h, hace_min=180)
    await _falla(negocio, a_las_16h, hace_min=16 * 60)
    await _falla(negocio, con_reenganche_16h, hace_min=16 * 60, con_reenganche_hace=14 * 60)
    await _falla(negocio, a_la_1h, hace_min=60)
    await _msg(negocio, normal_3h, "user", "hola", 180)
    await _msg(negocio, normal_3h, "assistant", "¡Hola! ¿Qué buscas?", 179)

    reenganche, cierre = await mem.listar_leads_inactividad_cliente(horas_reenganche=2.0, horas_cierre=15.0)

    marcados = lambda filas: {f["telefono"] for f in filas if f.get("tras_falla_ia")}
    assert marcados(reenganche) == {a_las_3h} and marcados(cierre) == {a_las_16h, con_reenganche_16h}
    assert a_la_1h not in {f["telefono"] for f in reenganche + cierre}
    normal = [f for f in reenganche if f["telefono"] == normal_3h]
    assert len(normal) == 1 and not normal[0].get("tras_falla_ia")     # el camino normal no cambia


async def test_un_mensaje_real_despues_del_error_devuelve_al_lead_al_camino_normal():
    negocio, canal = await _negocio("fia-021")
    tel = "51910000050"
    await _lead(negocio, canal, tel)
    await _falla(negocio, tel, hace_min=16 * 60)
    await _msg(negocio, tel, "assistant", "Hola, soy Pedro, ¿en qué te ayudo?", 15 * 60, via_app=True)

    _, cierre = await mem.listar_leads_inactividad_cliente(horas_reenganche=2.0, horas_cierre=15.0)

    fila = next(f for f in cierre if f["telefono"] == tel)
    assert not fila.get("tras_falla_ia")


def _preparar_script_inactividad(monkeypatch, proveedor):
    script = _cargar_script("procesar_inactividad_clientes")
    monkeypatch.setattr(script, "obtener_proveedor", lambda: proveedor)
    return script


async def test_el_cron_deriva_a_quien_solo_recibio_el_error_y_no_lo_reengancha_ni_lo_cierra(monkeypatch, capsys):
    negocio, canal, tel, proveedor = await _armar_flujo_real(monkeypatch, "fia-022")
    tardio = "51910000051"
    await _lead(negocio, canal, tardio)
    await _falla(negocio, tel, hace_min=3 * 60)               # 3 h: antes recibía "¡Hola de nuevo!"
    await _falla(negocio, tardio, hace_min=16 * 60)           # 16 h: antes se cerraba como sin_respuesta
    script = _preparar_script_inactividad(monkeypatch, proveedor)

    await script.main()

    for t in (tel, tardio):
        lead = await _lead_db(t)
        assert lead.asesor_asignado == "ase_a" and lead.paso_flujo == "derivado_asesor"
        assert (lead.resultado or "") != "sin_respuesta"
        (evento,) = await _eventos(t, mem.TIPO_EVENTO_DERIVADO_SIN_IA)
        assert evento["payload"]["motivo"] == "sin_respuesta_por_falla_ia"
    assert sorted(t for t, _ in proveedor.enviados) == sorted([tel, tardio])
    assert all(m == TEXTO_DENTRO for _, m in proveedor.enviados)          # ni rastro de "Hola de nuevo"
    assert "2 derivado(s) a una persona por falla de la IA" in capsys.readouterr().out

    capsys.readouterr()
    await script.main()                                                    # idempotente: ya tienen asesor
    assert len(proveedor.enviados) == 2


async def test_pasadas_24_horas_el_cron_no_manda_texto_libre_y_lo_deja_en_la_cola_de_supervision(monkeypatch):
    negocio, canal, tel, proveedor = await _armar_flujo_real(monkeypatch, "fia-023")
    await _falla(negocio, tel, hace_min=30 * 60)
    script = _preparar_script_inactividad(monkeypatch, proveedor)

    await script.main()

    lead = await _lead_db(tel)
    assert lead.asesor_asignado is None and lead.escalado_supervision_en is not None
    assert (lead.resultado or "") != "sin_respuesta" and proveedor.enviados == []


async def test_el_cron_sin_asesores_deja_al_cliente_en_la_cola_de_supervision(monkeypatch):
    negocio, canal, tel, proveedor = await _armar_flujo_real(monkeypatch, "fia-024", asesores=())
    await _falla(negocio, tel, hace_min=3 * 60)
    script = _preparar_script_inactividad(monkeypatch, proveedor)

    await script.main()

    lead = await _lead_db(tel)
    assert lead.escalado_supervision_en is not None and (lead.resultado or "") != "sin_respuesta"


async def test_si_la_derivacion_falla_el_lead_no_se_cierra_y_los_demas_siguen(monkeypatch, capsys):
    negocio, canal, tel, proveedor = await _armar_flujo_real(monkeypatch, "fia-025")
    otro = "51910000052"
    await _lead(negocio, canal, otro)
    await _falla(negocio, tel, hace_min=16 * 60)
    await _falla(negocio, otro, hace_min=16 * 60)
    script = _preparar_script_inactividad(monkeypatch, proveedor)
    derivados = []

    async def derivar(proveedor_, telefono, canal_, motivo):
        if telefono == tel:
            raise TimeoutError("base lenta")
        derivados.append((telefono, motivo))
        return {"accion": "derivado_asesor"}

    cerrados = []

    async def actualizar(telefono, **kwargs):
        cerrados.append(telefono)

    monkeypatch.setattr(script, "_derivar_real", derivar)
    monkeypatch.setattr(script, "actualizar_lead", actualizar)

    await script.main()   # no lanza

    assert derivados == [(otro, "sin_respuesta_por_falla_ia")] and cerrados == []
    assert "1 error(es)" in capsys.readouterr().out
    assert (await _lead_db(tel)).resultado is None             # sigue candidato, no quedó cerrado en silencio


async def test_no_regresion_el_cron_sigue_reenganchando_y_cerrando_a_los_leads_normales(monkeypatch, capsys):
    negocio, canal, tel, proveedor = await _armar_flujo_real(monkeypatch, "fia-026")
    a_cerrar = "51910000053"
    await _lead(negocio, canal, a_cerrar)
    for t, horas in ((tel, 3), (a_cerrar, 16)):
        await _msg(negocio, t, "user", "hola", horas * 60)
        await _msg(negocio, t, "assistant", "¡Hola! ¿Qué buscas?", horas * 60 - 1)
    script = _preparar_script_inactividad(monkeypatch, proveedor)

    await script.main()

    assert [m for t, m in proveedor.enviados if t == tel] == [script.MENSAJE_REENGANCHE]
    assert (await _lead_db(a_cerrar)).resultado == "sin_respuesta" and (await _lead_db(tel)).asesor_asignado is None
    salida = capsys.readouterr().out
    assert "1 reenganchado(s)" in salida and "1 cerrado(s)" in salida and "derivado(s) a una persona" not in salida


# ═══════════════════════════════════════════════════════════════════════════
# 3. Diagnóstico de solo lectura
# ═══════════════════════════════════════════════════════════════════════════

async def _conteos() -> tuple:
    async with mem.async_session() as session:
        return tuple([
            (await session.execute(select(func.count()).select_from(t))).scalar()
            for t in (mem.Mensaje, mem.EventoLead, mem.Lead)
        ])


async def test_el_diagnostico_lista_los_afectados_con_todos_sus_datos_y_no_modifica_nada():
    negocio, canal = await _negocio("fia-030")
    abierta, cerrada, con_asesor = "51910000060", "51910000061", "51910000062"
    for t in (abierta, cerrada, con_asesor):
        await _lead(negocio, canal, t)
    await _lead(negocio, canal, cerrada, resultado="sin_respuesta")   # como quedaron los casos reales: cerrado en silencio
    await _lead(negocio, canal, con_asesor, asesor_asignado="ase_a")
    await _falla(negocio, abierta, hace_min=6 * 60, texto_cliente="quiero una terma")
    await _falla(negocio, cerrada, hace_min=40 * 60, con_reenganche_hace=38 * 60)
    await _falla(negocio, con_asesor, hace_min=2 * 60)
    antes = await _conteos()

    filas = await mem.listar_leads_afectados_por_falla_ia()

    assert await _conteos() == antes
    assert [f["telefono"] for f in filas] == [con_asesor, abierta, cerrada]         # ventana abierta primero, más reciente antes
    por_tel = {f["telefono"]: f for f in filas}
    a = por_tel[abierta]
    assert a["nombre"] == "Cliente" and a["interes"] == "terma" and a["resultado"] is None
    assert a["ventana_24h_abierta"] is True and a["ya_derivado"] is False
    assert a["ultimo_mensaje_cliente"] == "quiero una terma"
    assert 5.9 <= a["horas_desde_mensaje"] <= 6.1
    en_utc = datetime.fromisoformat(a["ultimo_mensaje_cliente_en"])
    assert datetime.strptime(a["ultimo_mensaje_cliente_lima"], "%Y-%m-%d %H:%M") == (en_utc - timedelta(hours=5)).replace(second=0, microsecond=0)
    cierre = datetime.strptime(a["ventana_cierra_en_lima"], "%Y-%m-%d %H:%M")
    assert cierre == (en_utc + timedelta(hours=19)).replace(second=0, microsecond=0)   # 24 h después, en hora de Lima
    c = por_tel[cerrada]
    assert c["ventana_24h_abierta"] is False and c["ventana_cierra_en_lima"] is None and c["resultado"] == "sin_respuesta"
    assert por_tel[con_asesor]["ya_derivado"] is True and por_tel[con_asesor]["asesor_asignado"] == "ase_a"
    json.dumps(filas)       # serializable tal cual


async def test_el_diagnostico_excluye_a_quien_ya_recibio_una_respuesta_real_o_esta_fuera_del_periodo():
    negocio, canal = await _negocio("fia-031")
    respondido, derivado_sin_ia, viejo, normal = "51910000063", "51910000064", "51910000065", "51910000066"
    for t in (respondido, derivado_sin_ia, viejo, normal):
        await _lead(negocio, canal, t)
    await _falla(negocio, respondido, hace_min=300)
    await _msg(negocio, respondido, "assistant", "Hola, soy Pedro, ya te ayudo con tu terma", 200, via_app=True)
    await _falla(negocio, derivado_sin_ia, hace_min=300)
    await _msg(negocio, derivado_sin_ia, "assistant", TEXTO_DENTRO, 299)       # el modo sin IA ya lo derivó
    await _falla(negocio, viejo, hace_min=20 * 24 * 60)                        # más de 14 días
    await _msg(negocio, normal, "user", "hola", 300)
    await _msg(negocio, normal, "assistant", "¡Hola! ¿Qué buscas?", 299)

    assert await mem.listar_leads_afectados_por_falla_ia() == []
    assert [f["telefono"] for f in await mem.listar_leads_afectados_por_falla_ia(dias=30)] == [viejo]


async def test_el_diagnostico_acepta_filtros_de_ventana_y_negocio():
    negocio, canal = await _negocio("fia-032")
    otro_negocio, otro_canal = await _negocio("fia-033", asesores=())
    abierta, cerrada, ajeno = "51910000067", "51910000068", "51910000069"
    await _lead(negocio, canal, abierta)
    await _lead(negocio, canal, cerrada)
    await _lead(otro_negocio, otro_canal, ajeno)
    await _falla(negocio, abierta, hace_min=60)
    await _falla(negocio, cerrada, hace_min=60 * 30)
    await _falla(otro_negocio, ajeno, hace_min=60)

    assert {f["telefono"] for f in await mem.listar_leads_afectados_por_falla_ia(solo_ventana_abierta=True)} == {abierta, ajeno}
    assert {f["telefono"] for f in await mem.listar_leads_afectados_por_falla_ia(negocio_id=negocio["id"])} == {abierta, cerrada}
    assert len(await mem.listar_leads_afectados_por_falla_ia(limite=1)) == 1


async def test_el_script_de_diagnostico_imprime_json_puro_y_tabla(capsys):
    negocio, canal = await _negocio("fia-034")
    tel = "51910000070"
    await _lead(negocio, canal, tel)
    await _falla(negocio, tel, hace_min=120, texto_cliente="quiero una terma")
    script = _cargar_script("listar_leads_con_falla_ia")

    filas = await script.main(["--json", "--dias", "7"])
    datos = json.loads(capsys.readouterr().out)           # stdout es JSON y nada más
    assert [d["telefono"] for d in datos] == [tel] == [f["telefono"] for f in filas]
    assert datos[0]["ventana_24h_abierta"] is True and datos[0]["ultimo_mensaje_cliente_lima"]

    await script.main([])
    tabla = capsys.readouterr().out
    assert tel in tabla and "Cliente" in tabla and "ventana abierta hasta" in tabla and "1 lead(s) afectado(s)" in tabla

    await script.main(["--negocio-id", "no-existe"])
    assert "Ningún lead afectado" in capsys.readouterr().out


# ── R2 (2026-10-06): un "sin_respuesta" puesto por una persona no se borra solo ──────────────

def test_sin_respuesta_automatico_se_limpia_al_escribir_el_cliente():
    from agent.main import _debe_limpiar_sin_respuesta
    assert _debe_limpiar_sin_respuesta({"resultado": "sin_respuesta", "asesor_asignado": None, "pausado_manual": False})


def test_sin_respuesta_de_una_persona_no_se_borra_solo():
    from agent.main import _debe_limpiar_sin_respuesta
    assert not _debe_limpiar_sin_respuesta({"resultado": "sin_respuesta", "asesor_asignado": "lelespuru", "pausado_manual": False})
    assert not _debe_limpiar_sin_respuesta({"resultado": "sin_respuesta", "asesor_asignado": None, "pausado_manual": True})


def test_otros_resultados_o_sin_lead_no_se_limpian():
    from agent.main import _debe_limpiar_sin_respuesta
    assert not _debe_limpiar_sin_respuesta(None)
    assert not _debe_limpiar_sin_respuesta({"resultado": "agendado", "asesor_asignado": None, "pausado_manual": False})
    assert not _debe_limpiar_sin_respuesta({"resultado": None, "asesor_asignado": None, "pausado_manual": False})
