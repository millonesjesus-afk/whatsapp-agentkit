# tests/test_modo_sin_ia.py — Fase 1: modo sin IA + circuito de la IA (2026-10-05).
#
# Contexto: el saldo de la API de Anthropic se agotó y Gabi mandaba al cliente un texto técnico,
# prometía un asesor que nadie atendía y dejaba el lead invisible en Inicio. Ahora, al primer error
# de saldo/tope/credencial se abre un circuito global: Gabi NO llama a Claude, responde un mensaje
# automático (sin tokens) UNA vez y deja el caso asignado a un asesor (o en la cola de supervisión
# si no existe ninguno). Todo se simula con excepciones/monkeypatch: nada llama a Anthropic.

import asyncio
import importlib.util
import json
import os
import re
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")
os.environ.setdefault("WHATSAPP_PROVIDER", "meta")

import anthropic
import httpx
import pytest

from agent import brain, circuito_ia, dashboard, envios, errores_ia, notificaciones, politica_envios, respaldo_sin_ia
from agent import main as app_main
from agent import memory as mem
from agent.providers.base import MensajeEntrante

_PETICION = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
_CREAR_CLIENTE_SONDEO_REAL = circuito_ia._crear_cliente_sondeo


# ── Errores simulados del SDK ────────────────────────────────────────────

def _error_http(status: int, mensaje: str = "error", body: dict | None = None, tipo: str = "invalid_request_error"):
    """Una `APIStatusError` como la que lanza el SDK (para el 402 no hay clase propia: es la genérica)."""
    respuesta = httpx.Response(status, request=_PETICION, json=body if body is not None else {})
    if body is None:
        body = {"type": "error", "error": {"type": tipo, "message": mensaje}}
    return anthropic.APIStatusError(mensaje, response=respuesta, body=body)


def _credito():
    return _error_http(400, "Your credit balance is too low to access the Anthropic API. Please go to Plans & Billing to upgrade or purchase credits.")


@pytest.mark.parametrize("exc, esperado", [
    (_error_http(402, "pago requerido", tipo="billing_error"), "credito"),
    (_error_http(400, "x", body={"type": "error", "error": {"type": "billing_error", "message": "x"}}), "credito"),
    (_credito(), "credito"),
    (_error_http(400, "You have reached your specified API usage limits. You will regain access on 2026-11-01 at 00:00 UTC."), "tope_gasto"),
    (_error_http(429, "limite", body={"type": "error", "error": {"type": "rate_limit_error", "message": "limite", "details": {"error_code": "enforced_spend_limit_reached"}}}), "tope_gasto"),
    (_error_http(429, "limite", body={"type": "error", "error": {"type": "rate_limit_error", "message": "limite"}, "error_code": "enforced_spend_limit_reached"}), "tope_gasto"),
    (_error_http(401, "invalid x-api-key", tipo="authentication_error"), "auth"),
    (_error_http(403, "sin permiso", tipo="permission_error"), "auth"),
    (_error_http(429, "Rate limit", tipo="rate_limit_error"), "transitorio"),
    (_error_http(500, "boom", tipo="api_error"), "transitorio"),
    (_error_http(529, "overloaded", tipo="overloaded_error"), "transitorio"),
    (anthropic.APITimeoutError(request=_PETICION), "transitorio"),
    (anthropic.APIConnectionError(request=_PETICION), "transitorio"),
    (asyncio.TimeoutError(), "transitorio"),
    (_error_http(400, "messages: text content blocks must be non-empty"), "otro"),
    (_error_http(404, "model not found", tipo="not_found_error"), "otro"),
    (ValueError("El modelo no devolvió la herramienta forzada"), "otro"),
])
def test_clasificar_error_segun_la_tabla_de_la_doc_oficial(exc, esperado):
    assert errores_ia.clasificar_error(exc) == esperado


def test_clasificar_error_es_defensivo_con_body_ausente_o_raro():
    for body in (None, "texto suelto", [1, 2], {"error": "cadena"}, {"error": None}):
        exc = _error_http(402, "x", body=body if body is not None else {})
        exc.body = body
        assert errores_ia.clasificar_error(exc) == "credito"          # el 402 manda aunque el body no sirva
    sin_status = RuntimeError("algo raro")
    assert errores_ia.clasificar_error(sin_status) == "otro"


# ── Fixtures ─────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _aislamiento(monkeypatch):
    circuito_ia.reiniciar_memoria()
    alertas: list[tuple] = []

    async def alerta(abierto, motivo, resumen=None):
        alertas.append((abierto, motivo, resumen))
        return True

    monkeypatch.setattr(notificaciones, "notificar_circuito_ia", alerta)
    monkeypatch.setattr(circuito_ia, "_crear_cliente_sondeo", lambda: pytest.fail("el sondeo no debía crear un cliente"))
    politica_envios.limpiar_cache()
    yield alertas
    circuito_ia.reiniciar_memoria()


@pytest.fixture
def alertas(_aislamiento):
    return _aislamiento


class _Proveedor:
    def __init__(self, acepta: bool = True):
        self.enviados: list[tuple[str, str]] = []
        self.acepta = acepta

    async def enviar_mensaje(self, telefono, mensaje, canal=None, mensaje_id_citado=None):
        self.enviados.append((telefono, mensaje))
        return (True, f"wamid.sinia.{len(self.enviados)}") if self.acepta else (False, None)


async def _armar(
    monkeypatch, codigo: str, telefono: str = "51940000001", *, asesores=(("ase_a", True),), horario="siempre",
    nombre: str | None = "Juan Pérez", user_ts: datetime | None = None, interes: str | None = None,
    bloquear_claude: bool = True,
):
    """Negocio + canal + horario + asesores + lead con un mensaje del cliente. `asesores`:
    ((username, disponible), …). `horario`: "siempre" (abierto las 24 h) o "lun-sab" (8:00 a 19:00)."""
    negocio = await mem.crear_negocio(f"Negocio {codigo}", codigo)
    canal_db = await mem.crear_canal_whatsapp(
        nombre=f"Canal {codigo}", phone_number_id=f"4097{int(codigo[-3:]):06d}", negocio_id=negocio["id"],
    )
    canal = {"id": canal_db["id"], "negocio_id": negocio["id"], "unidad_id": None,
             "phone_number_id": canal_db["phone_number_id"], "modo": "produccion"}
    for dia in range(7):
        if horario == "siempre":
            await mem.guardar_horario_atencion(negocio["id"], dia, True, "00:00", "23:59")
        else:
            await mem.guardar_horario_atencion(negocio["id"], dia, dia <= 5, "08:00", "19:00")
    for username, disponible in asesores:
        await mem.crear_usuario(username, "pw12345", username.title(), "asesor", negocio["id"])
        if not disponible:
            await mem.actualizar_disponibilidad(username, negocio["id"], False)
    await mem.resolver_conversation_activa(telefono, negocio["id"], canal_db["id"])
    campos = {"negocio_id": negocio["id"], "numero_whatsapp_id": canal["phone_number_id"]}
    if nombre:
        campos["nombre"] = nombre
    if interes:
        campos["interes"] = interes
    await mem.actualizar_lead(telefono, **campos)
    guardado = await mem.guardar_mensaje(telefono, "user", "hola, quiero una terma", negocio_id=negocio["id"])
    if user_ts is not None:
        async with mem.async_session() as session:
            (await session.get(mem.Mensaje, guardado["id"])).timestamp = user_ts
            await session.commit()
    proveedor = _Proveedor()
    monkeypatch.setattr(app_main, "proveedor", proveedor)
    if horario == "siempre":
        # "Dentro de horario" sin depender de la hora real (el rango 00:00-23:59 deja fuera un minuto al día).
        async def dentro(negocio_id):
            return {"dentro_de_horario": True, "fecha_hora_lima": "x"}

        monkeypatch.setattr(respaldo_sin_ia, "obtener_estado_horario_atencion", dentro)

    if bloquear_claude:
        async def claude_no_debe_llamarse(*a, **k):
            raise AssertionError("Con el circuito abierto NO se debe llamar a Claude")

        monkeypatch.setattr(app_main.servicio_inteligencia, "generar_respuesta", claude_no_debe_llamarse)
    return negocio, canal, proveedor


async def _lead(telefono: str) -> mem.Lead:
    async with mem.async_session() as session:
        return await session.get(mem.Lead, telefono)


async def _estado(telefono: str) -> tuple:
    lead = await _lead(telefono)
    return (lead.resultado, lead.asesor_asignado, lead.paso_flujo, lead.pausado_manual, lead.escalado_supervision_en, lead.cerrado_definitivamente_en)


async def _eventos_sin_ia(telefono: str) -> list[dict]:
    return [e for e in await mem.listar_eventos_lead(telefono) if e["tipo"] == "derivado_sin_ia"]


async def _mensajes_de_gabi(negocio_id: str, telefono: str) -> list[mem.Mensaje]:
    async with mem.async_session() as session:
        return list((await session.execute(
            mem.select(mem.Mensaje).where(
                mem.Mensaje.negocio_id == negocio_id, mem.Mensaje.telefono == telefono, mem.Mensaje.role == "assistant",
            ).order_by(mem.Mensaje.id)
        )).scalars().all())


def _fuera_de_horario(monkeypatch, *, dia="martes", hora="8:00 a. m.", dias=1, hoy_es_dia=True):
    async def estado(negocio_id):
        return {"dentro_de_horario": False, "fecha_hora_lima": "x"}

    async def proxima(negocio_id, ahora=None):
        return {"inicio": datetime.utcnow(), "dia": dia, "hora": hora, "dias_de_diferencia": dias, "hoy_es_dia_de_atencion": hoy_es_dia}

    monkeypatch.setattr(respaldo_sin_ia, "obtener_estado_horario_atencion", estado)
    monkeypatch.setattr(respaldo_sin_ia, "obtener_proxima_apertura", proxima)


TEXTO_DENTRO = "¡Hola, Juan! 👋 Gracias por escribirnos. Te estoy transfiriendo con un asesor de nuestro equipo, que te atenderá por este mismo chat en unos minutos. 😊"
TEXTO_FUERA = "¡Hola, Juan! 👋 Gracias por escribirnos. Te transferí con un asesor y te atenderá en nuestro horario de atención (lunes a sábado, de 8:00 a. m. a 7:00 p. m.). Si prefieres, también puedes llamarnos al 614-9002."
TEXTO_FIN_DE_SEMANA = "¡Hola, Juan! 👋 Gracias por escribirnos. Te transferí con un asesor y te atenderá el lunes desde las 8:00 a. m. Si prefieres, también puedes llamarnos al 614-9002."


# ── El circuito: cuándo se abre ──────────────────────────────────────────

async def _generar_con_error(exc):
    brain.client = SimpleNamespace(messages=SimpleNamespace(create=AsyncMock(side_effect=exc)))
    return await brain.generar_respuesta("hola", [], None, modo="produccion", negocio_id=None)


@pytest.fixture
def _restaurar_cliente():
    original = brain.client
    yield
    brain.client = original


async def test_el_primer_error_de_credito_abre_el_circuito_y_avisa_una_sola_vez(_restaurar_cliente, alertas):
    assert not await circuito_ia.esta_abierto()
    respuesta, hubo_error, confianza, razon = await _generar_con_error(_credito())
    assert hubo_error is True and (confianza, razon) == (None, None)       # la firma de 4 valores sigue igual
    assert await circuito_ia.esta_abierto()
    estado = await circuito_ia.obtener_estado()
    assert estado["motivo"] == "credito" and estado["abierto_en"]

    await _generar_con_error(_credito())                                   # idempotente: no re-abre ni re-avisa
    await circuito_ia.esperar_tareas_en_segundo_plano()
    assert alertas == [(True, "credito", None)]
    guardado = json.loads(await mem.obtener_configuracion("ia_circuito", ""))
    assert guardado["estado"] == "abierto" and guardado["motivo"] == "credito"
    assert len(json.dumps(guardado)) <= 200                                # cabe en configuracion.valor (VARCHAR(200))


@pytest.mark.parametrize("exc, motivo", [
    (_error_http(400, "You have reached your specified API usage limits."), "tope_gasto"),
    (_error_http(401, "invalid x-api-key", tipo="authentication_error"), "auth"),
])
async def test_tope_de_gasto_y_credencial_invalida_tambien_abren_de_inmediato(_restaurar_cliente, exc, motivo):
    await _generar_con_error(exc)
    assert (await circuito_ia.obtener_estado())["motivo"] == motivo


async def test_un_400_de_contenido_no_abre_el_circuito(_restaurar_cliente):
    _, hubo_error, _, _ = await _generar_con_error(_error_http(400, "messages: text content blocks must be non-empty"))
    assert hubo_error is True and not await circuito_ia.esta_abierto()


async def test_los_errores_transitorios_abren_solo_tras_tres_fallas_en_60_segundos(monkeypatch):
    reloj = {"t": 1000.0}
    monkeypatch.setattr(circuito_ia, "time", SimpleNamespace(monotonic=lambda: reloj["t"]))
    transitorio = _error_http(500, "boom", tipo="api_error")

    assert await circuito_ia.registrar_error(transitorio) == "transitorio"
    reloj["t"] += 10
    await circuito_ia.registrar_error(transitorio)
    assert not await circuito_ia.esta_abierto()                            # 2 fallas: todavía no
    reloj["t"] += 10
    await circuito_ia.registrar_error(transitorio)
    assert await circuito_ia.esta_abierto()
    assert (await circuito_ia.obtener_estado())["motivo"] == "transitorio"


async def test_tres_fallas_transitorias_repartidas_en_mas_de_60_segundos_no_abren(monkeypatch):
    reloj = {"t": 1000.0}
    monkeypatch.setattr(circuito_ia, "time", SimpleNamespace(monotonic=lambda: reloj["t"]))
    transitorio = _error_http(529, "overloaded", tipo="overloaded_error")
    for _ in range(3):
        await circuito_ia.registrar_error(transitorio)
        reloj["t"] += 40
    assert not await circuito_ia.esta_abierto()


async def test_un_exito_reinicia_la_cuenta_de_fallas_transitorias():
    transitorio = _error_http(500, "boom", tipo="api_error")
    await circuito_ia.registrar_error(transitorio)
    await circuito_ia.registrar_error(transitorio)
    circuito_ia.registrar_exito()
    await circuito_ia.registrar_error(transitorio)
    assert not await circuito_ia.esta_abierto()


async def test_abrir_es_idempotente_y_conserva_la_hora_original(alertas):
    assert await circuito_ia.abrir("credito") is True
    primera = (await circuito_ia.obtener_estado(forzar=True))["abierto_en"]
    assert await circuito_ia.abrir("auth") is False
    estado = await circuito_ia.obtener_estado(forzar=True)
    assert (estado["abierto_en"], estado["motivo"]) == (primera, "credito")
    await circuito_ia.esperar_tareas_en_segundo_plano()
    assert len(alertas) == 1


# ── Con el circuito abierto: texto fijo, una sola vez, y el caso queda con una persona ──

async def test_con_el_circuito_abierto_no_se_llama_a_claude_y_el_cliente_recibe_el_texto_de_dentro_de_horario(monkeypatch):
    negocio, canal, proveedor = await _armar(monkeypatch, "sia-001")
    await circuito_ia.abrir("credito")

    await app_main._generar_y_enviar_respuesta_ia("51940000001", canal)

    assert proveedor.enviados == [("51940000001", TEXTO_DENTRO)]
    (guardado,) = await _mensajes_de_gabi(negocio["id"], "51940000001")
    assert guardado.content == TEXTO_DENTRO and guardado.estado_envio is None and guardado.mensaje_id_meta == "wamid.sinia.1"


async def test_fuera_de_horario_el_texto_cita_el_horario_real_del_negocio(monkeypatch):
    negocio, canal, proveedor = await _armar(monkeypatch, "sia-002", horario="lun-sab")
    _fuera_de_horario(monkeypatch, dia="martes", dias=1, hoy_es_dia=True)
    await circuito_ia.abrir("credito")

    await app_main._generar_y_enviar_respuesta_ia("51940000001", canal)

    assert proveedor.enviados == [("51940000001", TEXTO_FUERA)]


async def test_en_fin_de_semana_el_texto_dice_cuando_abre(monkeypatch):
    negocio, canal, proveedor = await _armar(monkeypatch, "sia-003", horario="lun-sab")
    _fuera_de_horario(monkeypatch, dia="lunes", hora="8:00 a. m.", dias=1, hoy_es_dia=False)    # domingo
    await circuito_ia.abrir("credito")

    await app_main._generar_y_enviar_respuesta_ia("51940000001", canal)

    assert proveedor.enviados == [("51940000001", TEXTO_FIN_DE_SEMANA)]


async def test_sabado_de_noche_con_apertura_a_dos_dias_tambien_usa_el_texto_de_fin_de_semana(monkeypatch):
    negocio, canal, proveedor = await _armar(monkeypatch, "sia-004", horario="lun-sab")
    _fuera_de_horario(monkeypatch, dia="lunes", hora="8:00 a. m.", dias=2, hoy_es_dia=True)
    await circuito_ia.abrir("credito")
    await app_main._generar_y_enviar_respuesta_ia("51940000001", canal)
    assert proveedor.enviados == [("51940000001", TEXTO_FIN_DE_SEMANA)]


async def test_el_cliente_que_escribe_varias_veces_recibe_el_aviso_una_sola_vez(monkeypatch):
    negocio, canal, proveedor = await _armar(monkeypatch, "sia-005")
    await circuito_ia.abrir("credito")

    for _ in range(3):
        await app_main._generar_y_enviar_respuesta_ia("51940000001", canal)

    assert len(proveedor.enviados) == 1
    assert len(await _eventos_sin_ia("51940000001")) == 1
    assert len(await _mensajes_de_gabi(negocio["id"], "51940000001")) == 1


async def test_sin_nombre_el_saludo_no_lleva_coma(monkeypatch):
    negocio, canal, proveedor = await _armar(monkeypatch, "sia-006", nombre=None)
    await circuito_ia.abrir("credito")
    await app_main._generar_y_enviar_respuesta_ia("51940000001", canal)
    assert proveedor.enviados[0][1].startswith("¡Hola! 👋 Gracias por escribirnos.")


async def test_el_lead_queda_asignado_al_asesor_disponible_con_paso_flujo_y_evento(monkeypatch):
    negocio, canal, proveedor = await _armar(monkeypatch, "sia-007", asesores=(("ase_ocupado", False), ("ase_libre", True)))
    await circuito_ia.abrir("credito")

    await app_main._generar_y_enviar_respuesta_ia("51940000001", canal)

    lead = await _lead("51940000001")
    assert lead.asesor_asignado == "ase_libre" and lead.paso_flujo == "derivado_asesor"
    assert lead.derivado_en is not None                                   # armó la rotación a 30 min (automatico=True)
    assert lead.escalado_supervision_en is None
    (evento,) = await _eventos_sin_ia("51940000001")
    assert evento["payload"]["destino"] == "asesor" and evento["payload"]["asesor"] == "ase_libre"
    assert evento["payload"]["motivo"] == "credito"


async def test_fuera_de_horario_sin_ningun_asesor_disponible_se_asigna_al_activo_con_menos_carga(monkeypatch):
    negocio, canal, proveedor = await _armar(
        monkeypatch, "sia-008", horario="lun-sab", asesores=(("ase_cargado", False), ("ase_liviano", False)),
    )
    _fuera_de_horario(monkeypatch)
    # ase_cargado ya tiene un caso en curso.
    await mem.resolver_conversation_activa("51940000099", negocio["id"], canal["id"])
    await mem.actualizar_lead("51940000099", negocio_id=negocio["id"], nombre="Otro")
    await mem.asignar_asesor_a_lead("51940000099", "ase_cargado")
    await circuito_ia.abrir("credito")

    await app_main._generar_y_enviar_respuesta_ia("51940000001", canal)

    lead = await _lead("51940000001")
    assert lead.asesor_asignado == "ase_liviano" and lead.escalado_supervision_en is None
    assert lead.derivado_en is not None
    assert [m for _, m in proveedor.enviados] == [TEXTO_FUERA]


async def test_un_asesor_inactivo_o_eliminado_no_recibe_el_caso_y_sin_ninguno_activo_va_a_la_cola(monkeypatch):
    negocio, canal, proveedor = await _armar(
        monkeypatch, "sia-009", asesores=(("ase_apagado", True), ("ase_eliminado", True)),
    )
    await mem.toggle_usuario_activo("ase_apagado", negocio["id"])
    await mem.eliminar_usuario("ase_eliminado", negocio["id"], "admin")
    await circuito_ia.abrir("credito")

    await app_main._generar_y_enviar_respuesta_ia("51940000001", canal)

    lead = await _lead("51940000001")
    assert lead.asesor_asignado is None and lead.escalado_supervision_en is not None and lead.pausado_manual is True
    assert lead.paso_flujo == "derivado_asesor"
    (evento,) = await _eventos_sin_ia("51940000001")
    assert evento["payload"]["destino"] == "supervision"
    assert [m for _, m in proveedor.enviados] == [TEXTO_DENTRO]            # igual se le avisa al cliente, una vez
    await app_main._generar_y_enviar_respuesta_ia("51940000001", canal)    # en cola ⇒ pausado: no repite nada
    assert len(proveedor.enviados) == 1


async def test_sin_asesor_disponible_pero_con_uno_activo_el_caso_se_le_asigna_igual(monkeypatch):
    negocio, canal, proveedor = await _armar(monkeypatch, "sia-010", asesores=(("ase_dormido", False),))
    await circuito_ia.abrir("credito")
    await app_main._generar_y_enviar_respuesta_ia("51940000001", canal)
    lead = await _lead("51940000001")
    assert lead.asesor_asignado == "ase_dormido" and lead.escalado_supervision_en is None   # activo aunque no esté disponible


@pytest.mark.parametrize("preparar", [
    lambda t, n: mem.actualizar_lead(t, campos_explicitos=("resultado",), resultado="vendido"),
    lambda t, n: mem.actualizar_lead(t, campos_explicitos=("resultado",), resultado="agendado"),
    lambda t, n: mem.actualizar_lead(t, campos_explicitos=("resultado",), resultado="postventa"),
    lambda t, n: mem.actualizar_lead(t, campos_explicitos=("resultado",), resultado="no_interesado"),
    lambda t, n: mem.asignar_asesor_a_lead(t, "ase_a"),
    lambda t, n: mem.pausar_gabi_manual(t),
])
async def test_un_lead_vendido_agendado_postventa_cerrado_o_con_asesor_no_se_toca(monkeypatch, preparar):
    negocio, canal, proveedor = await _armar(monkeypatch, "sia-011", asesores=(("ase_a", True), ("ase_b", True)))
    await preparar("51940000001", negocio["id"])
    antes = await _estado("51940000001")
    await circuito_ia.abrir("credito")

    resultado = await respaldo_sin_ia.derivar_por_falla_ia("51940000001", canal, "credito", proveedor=proveedor)

    assert resultado["accion"] in ("no_aplica", "ya_derivado") and resultado["texto_enviado"] is False
    assert await _estado("51940000001") == antes
    assert proveedor.enviados == [] and await _eventos_sin_ia("51940000001") == []


async def test_si_la_ventana_de_24_horas_ya_cerro_no_se_manda_texto_libre_y_va_a_la_cola(monkeypatch):
    negocio, canal, proveedor = await _armar(monkeypatch, "sia-012", user_ts=datetime.utcnow() - timedelta(hours=30))
    await circuito_ia.abrir("credito")

    resultado = await respaldo_sin_ia.derivar_por_falla_ia("51940000001", canal, "mensaje_sin_respuesta", proveedor=proveedor)

    assert resultado["accion"] == "cola_supervision" and proveedor.enviados == []
    lead = await _lead("51940000001")
    assert lead.asesor_asignado is None and lead.escalado_supervision_en is not None
    (evento,) = await _eventos_sin_ia("51940000001")
    assert evento["payload"]["ventana_abierta"] is False


@pytest.mark.parametrize("tipo", ["dentro_horario", "fuera_horario", "fin_de_semana"])
def test_los_textos_fijos_nunca_mencionan_ia_tokens_ni_creditos(tipo):
    for nombre in (None, "Juan Pérez"):
        texto = brain.obtener_mensaje_sin_ia(tipo, nombre, horario="lunes a sábado, de 8:00 a. m. a 7:00 p. m.", dia="lunes", hora="8:00 a. m.")
        assert "token" not in texto.lower() and "crédito" not in texto.lower() and "credito" not in texto.lower()
        assert not re.search(r"\bIA\b|inteligencia artificial|saldo", texto, re.IGNORECASE)
        assert "{" not in texto and "}" not in texto                       # ningún marcador sin reemplazar


async def test_el_texto_enviado_al_cliente_no_menciona_ia_tokens_ni_creditos(monkeypatch):
    negocio, canal, proveedor = await _armar(monkeypatch, "sia-013")
    await circuito_ia.abrir("credito")
    await app_main._generar_y_enviar_respuesta_ia("51940000001", canal)
    texto = proveedor.enviados[0][1].lower()
    assert "token" not in texto and "crédito" not in texto and not re.search(r"\bia\b", texto)


async def test_un_envio_fallido_del_aviso_se_guarda_como_fallido_pero_el_caso_queda_derivado(monkeypatch):
    negocio, canal, proveedor = await _armar(monkeypatch, "sia-014")
    proveedor.acepta = False
    await circuito_ia.abrir("credito")
    await app_main._generar_y_enviar_respuesta_ia("51940000001", canal)
    (guardado,) = await _mensajes_de_gabi(negocio["id"], "51940000001")
    assert guardado.estado_envio == "fallido"
    assert (await _lead("51940000001")).asesor_asignado == "ase_a"


# ── Integración con brain: el error real abre el circuito y no se manda el texto técnico ──

async def test_un_error_de_credito_en_la_llamada_deriva_sin_mandar_el_texto_tecnico(monkeypatch, _restaurar_cliente):
    negocio, canal, proveedor = await _armar(monkeypatch, "sia-015", bloquear_claude=False)   # generar_respuesta REAL
    brain.client = SimpleNamespace(messages=SimpleNamespace(create=AsyncMock(side_effect=_credito())))

    await app_main._generar_y_enviar_respuesta_ia("51940000001", canal)

    assert await circuito_ia.esta_abierto()
    assert [m for _, m in proveedor.enviados] == [TEXTO_DENTRO]
    assert all("problema" not in m.lower() for _, m in proveedor.enviados)
    lead = await _lead("51940000001")
    assert lead.asesor_asignado == "ase_a" and lead.paso_flujo == "derivado_asesor" and (lead.fallos_tecnicos or 0) == 0


async def test_falla_transitoria_primera_pide_reintentar_y_la_segunda_deriva_por_el_camino_nuevo(monkeypatch):
    negocio, canal, proveedor = await _armar(monkeypatch, "sia-016")

    async def falla(mensaje, historial, lead, modo="produccion", negocio_id=None):
        return brain.obtener_mensaje_error(), True, None, None

    monkeypatch.setattr(app_main.servicio_inteligencia, "generar_respuesta", falla)

    await app_main._generar_y_enviar_respuesta_ia("51940000001", canal)         # 1.ª falla
    assert [m for _, m in proveedor.enviados] == [brain.obtener_mensaje_error()]
    assert (await _lead("51940000001")).asesor_asignado is None

    await mem.guardar_mensaje("51940000001", "user", "¿hola?", negocio_id=negocio["id"])   # el cliente insiste
    await app_main._generar_y_enviar_respuesta_ia("51940000001", canal)         # 2.ª falla: escala
    lead = await _lead("51940000001")
    assert lead.asesor_asignado == "ase_a" and lead.paso_flujo == "derivado_asesor"     # el hueco: antes no fijaba paso_flujo
    assert [m for _, m in proveedor.enviados] == [brain.obtener_mensaje_error(), TEXTO_DENTRO]   # sin repetir el texto técnico
    assert len(await _eventos_sin_ia("51940000001")) == 1
    assert (await _lead("51940000001")).fallos_tecnicos == 0


async def test_falla_transitoria_repetida_sin_ningun_asesor_deja_el_caso_en_la_cola(monkeypatch):
    negocio, canal, proveedor = await _armar(monkeypatch, "sia-017", asesores=())

    async def falla(mensaje, historial, lead, modo="produccion", negocio_id=None):
        return brain.obtener_mensaje_error(), True, None, None

    monkeypatch.setattr(app_main.servicio_inteligencia, "generar_respuesta", falla)
    await app_main._generar_y_enviar_respuesta_ia("51940000001", canal)
    await mem.guardar_mensaje("51940000001", "user", "¿hola?", negocio_id=negocio["id"])
    await app_main._generar_y_enviar_respuesta_ia("51940000001", canal)
    lead = await _lead("51940000001")
    assert lead.asesor_asignado is None and lead.escalado_supervision_en is not None and lead.paso_flujo == "derivado_asesor"


async def test_un_adjunto_con_el_circuito_abierto_y_sin_asesor_se_deriva_en_vez_de_avisar_que_no_se_lee(monkeypatch):
    negocio, canal, proveedor = await _armar(monkeypatch, "sia-018")
    await circuito_ia.abrir("credito")
    msg = MensajeEntrante(
        telefono="51940000001", texto="", mensaje_id="wamid.adj1", es_propio=False, tipo="audio",
        numero_whatsapp_id=canal["phone_number_id"],
    )

    await app_main._atender_mensaje_no_legible(msg, canal, "[audio]")

    assert [m for _, m in proveedor.enviados] == [TEXTO_DENTRO]
    assert (await _lead("51940000001")).asesor_asignado == "ase_a"


# ── Sondeo ───────────────────────────────────────────────────────────────

def _cliente_de_sondeo(monkeypatch, *, falla: Exception | None = None):
    llamadas = AsyncMock(side_effect=falla) if falla else AsyncMock(return_value=SimpleNamespace(content=[]))
    cliente = SimpleNamespace(messages=SimpleNamespace(create=llamadas), close=AsyncMock())
    monkeypatch.setattr(circuito_ia, "_crear_cliente_sondeo", lambda: cliente)
    return llamadas


async def _abrir_hace(minutos: float, motivo: str = "credito", ultimo_sondeo_hace: float | None = None):
    """Deja el circuito abierto con `abierto_en` hace `minutos` (escribe el estado directo)."""
    ahora = datetime.utcnow()
    estado = {
        "estado": "abierto", "abierto_en": (ahora - timedelta(minutes=minutos)).replace(microsecond=0).isoformat(),
        "motivo": motivo,
        "ultimo_sondeo_en": (ahora - timedelta(minutes=ultimo_sondeo_hace)).replace(microsecond=0).isoformat() if ultimo_sondeo_hace is not None else None,
    }
    await circuito_ia._guardar_bd(estado)
    circuito_ia.reiniciar_memoria()


async def test_el_sondeo_respeta_los_5_minutos(monkeypatch):
    llamadas = _cliente_de_sondeo(monkeypatch)
    await _abrir_hace(2)
    assert await circuito_ia.sondear_si_corresponde() is False
    llamadas.assert_not_awaited()
    assert await circuito_ia.esta_abierto()

    await _abrir_hace(30, ultimo_sondeo_hace=3)                           # abrió hace rato, pero sondeó hace 3 min
    assert await circuito_ia.sondear_si_corresponde() is False
    llamadas.assert_not_awaited()


async def test_el_sondeo_hace_una_llamada_de_un_token_y_cierra_el_circuito_si_responde(monkeypatch, alertas):
    llamadas = _cliente_de_sondeo(monkeypatch)
    await _abrir_hace(6)

    assert await circuito_ia.sondear_si_corresponde() is True

    llamadas.assert_awaited_once()
    argumentos = llamadas.await_args.kwargs
    # 2026-10-26: el sondeo usa el modelo económico de respaldo (siempre disponible), no el nuevo Haiku 5.5
    assert argumentos["max_tokens"] == 1 and argumentos["model"] == brain.MODELO_EXTRACCION_RESPALDO
    assert not await circuito_ia.esta_abierto()
    assert json.loads(await mem.obtener_configuracion("ia_circuito", "")) == {"estado": "cerrado"}
    await circuito_ia.esperar_tareas_en_segundo_plano()
    assert alertas == [(False, "credito", {"total": 0, "en_cola": 0})]


async def test_el_sondeo_usa_un_cliente_aparte_sin_reintentos_y_con_timeout_corto(monkeypatch):
    creados = {}

    class _Falso:
        def __init__(self, **kw):
            creados.update(kw)
            self.messages = SimpleNamespace(create=AsyncMock(return_value=None))

        async def close(self):
            pass

    monkeypatch.setattr(anthropic, "AsyncAnthropic", _Falso)
    cliente = _CREAR_CLIENTE_SONDEO_REAL()
    assert creados["max_retries"] == 0 and creados["timeout"] == 10.0
    assert cliente is not brain.client


async def test_un_sondeo_fallido_solo_actualiza_la_hora_del_ultimo_sondeo(monkeypatch):
    llamadas = _cliente_de_sondeo(monkeypatch, falla=_credito())
    await _abrir_hace(6)

    assert await circuito_ia.sondear_si_corresponde() is False

    llamadas.assert_awaited_once()
    estado = await circuito_ia.obtener_estado(forzar=True)
    assert estado["estado"] == "abierto" and estado["ultimo_sondeo_en"] is not None
    assert await circuito_ia.sondear_si_corresponde() is False             # recién sondeó: otros 5 min
    llamadas.assert_awaited_once()


async def test_solo_un_mensaje_dispara_el_sondeo_aunque_lleguen_varios_a_la_vez(monkeypatch):
    llamadas = _cliente_de_sondeo(monkeypatch)
    await _abrir_hace(6)
    resultados = await asyncio.gather(*[circuito_ia.sondear_si_corresponde() for _ in range(5)])
    llamadas.assert_awaited_once()
    assert sorted(resultados) == [False] * 4 + [True]


async def test_un_error_transitorio_se_sondea_cada_2_minutos(monkeypatch):
    llamadas = _cliente_de_sondeo(monkeypatch)
    await _abrir_hace(3, motivo="transitorio")
    assert await circuito_ia.sondear_si_corresponde() is True
    llamadas.assert_awaited_once()


async def test_sin_el_circuito_abierto_el_sondeo_no_hace_nada(monkeypatch):
    llamadas = _cliente_de_sondeo(monkeypatch)
    assert await circuito_ia.sondear_si_corresponde() is False
    llamadas.assert_not_awaited()


async def test_con_el_circuito_abierto_el_mensaje_dispara_el_sondeo_en_segundo_plano_sin_bloquearse(monkeypatch):
    negocio, canal, proveedor = await _armar(monkeypatch, "sia-019")
    llamadas = _cliente_de_sondeo(monkeypatch)
    await _abrir_hace(6)

    await app_main._generar_y_enviar_respuesta_ia("51940000001", canal)
    await circuito_ia.esperar_tareas_en_segundo_plano()

    llamadas.assert_awaited_once()                                         # el sondeo corrió y cerró el circuito…
    assert not await circuito_ia.esta_abierto()
    assert [m for _, m in proveedor.enviados] == [TEXTO_DENTRO]            # …pero ESTE cliente ya había sido derivado


async def test_un_sondeo_que_revienta_nunca_rompe_el_mensaje(monkeypatch):
    negocio, canal, proveedor = await _armar(monkeypatch, "sia-020")
    monkeypatch.setattr(circuito_ia, "_crear_cliente_sondeo", lambda: (_ for _ in ()).throw(RuntimeError("sin red")))
    await _abrir_hace(6)
    await app_main._generar_y_enviar_respuesta_ia("51940000001", canal)
    await circuito_ia.esperar_tareas_en_segundo_plano()
    assert await circuito_ia.esta_abierto() and len(proveedor.enviados) == 1


# ── Origen de envío ──────────────────────────────────────────────────────

def test_el_origen_del_modo_sin_ia_es_esencial_agrupa_60_minutos_y_esta_exento_del_tope():
    assert envios.ORIGENES["gabi_respaldo_sin_ia"] == {"esencial": True, "agrupar_minutos": 60, "exento_tope": True}
    assert len(envios.ORIGENES) >= 11 and "plantilla_automatica" in envios.ORIGENES


async def test_la_opcion_b_con_tope_cero_frena_a_gabi_pero_no_al_aviso_del_modo_sin_ia():
    negocio = await mem.crear_negocio("Negocio sia-tope", "sia-tope")
    nid = negocio["id"]
    canal = {"negocio_id": nid, "phone_number_id": "555000111"}
    await mem.guardar_configuracion("meta_cuota_gratis_servicio", "1", negocio_id=nid)
    assert await mem.registrar_estado_mensaje_meta({
        "wamid": "wamid.cuota.sia", "estado": "delivered", "momento": datetime.utcnow(), "phone_number_id": "555000111",
        "destinatario": "51922999999", "negocio_id": nid,
        "pricing": {"billable": False, "pricing_model": "PMP", "type": "free_customer_service", "category": "service"},
    })
    await mem.guardar_configuracion("meta_tarifa_usd_service", "0.03", negocio_id=nid)
    await mem.guardar_configuracion_uso_meta(nid, {"confirmar_riesgo": True, "envios": {"tope_mensual_usd": 0.01, "tope_bloquea_esenciales": True}})
    politica_envios.limpiar_cache()
    proveedor = _Proveedor()

    normal = await envios.enviar_texto(proveedor, "51922000021", "hola", origen="gabi_respuesta", canal=canal)
    respaldo = await envios.enviar_texto(proveedor, "51922000021", "hola", origen="gabi_respaldo_sin_ia", canal=canal)
    repetido = await envios.enviar_texto(proveedor, "51922000021", "hola", origen="gabi_respaldo_sin_ia", canal=canal)

    assert normal.bloqueado and "tope mensual" in normal.motivo            # la Opción B sigue frenando lo esencial normal
    assert respaldo.enviado and not respaldo.bloqueado                     # el aviso sin IA sale igual
    assert repetido.bloqueado                                              # y agrupa 60 min: no se repite al mismo cliente


# ── Crons ────────────────────────────────────────────────────────────────

def _cargar_script(nombre: str):
    ruta = Path(__file__).resolve().parent.parent / "scripts" / nombre
    spec = importlib.util.spec_from_file_location(nombre.removesuffix(".py"), ruta)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


async def test_el_cron_de_inactividad_no_reengancha_ni_cierra_con_el_circuito_abierto(monkeypatch, capsys):
    script = _cargar_script("procesar_inactividad_clientes.py")
    consultas = []

    async def no_debe_consultar(*a, **k):
        consultas.append(1)
        raise AssertionError("no debía ni consultar candidatos")

    async def sin_espera():
        return None

    monkeypatch.setattr(script, "esperar_base_de_datos", sin_espera)
    monkeypatch.setattr(script, "listar_leads_inactividad_cliente", no_debe_consultar)
    monkeypatch.setattr(script, "actualizar_lead", no_debe_consultar)
    await _abrir_hace(1)

    await script.main()

    salida = capsys.readouterr().out
    assert consultas == [] and "omitida" in salida and "modo sin IA" in salida


async def test_el_cron_de_inactividad_sigue_igual_con_el_circuito_cerrado(monkeypatch, capsys):
    script = _cargar_script("procesar_inactividad_clientes.py")

    async def sin_candidatos(*a, **k):
        return [], []

    async def sin_espera():
        return None

    monkeypatch.setattr(script, "esperar_base_de_datos", sin_espera)
    monkeypatch.setattr(script, "listar_leads_inactividad_cliente", sin_candidatos)
    monkeypatch.setattr(script, "obtener_proveedor", lambda: _Proveedor())
    await script.main()
    assert "0 reenganchado(s)" in capsys.readouterr().out


async def test_el_barrido_de_mensajes_sin_respuesta_sale_sin_hacer_nada_con_el_circuito_abierto(monkeypatch):
    script = _cargar_script("recuperar_mensajes_sin_respuesta.py")
    negocio, canal, proveedor = await _armar(monkeypatch, "sia-021", user_ts=datetime.utcnow() - timedelta(minutes=10))
    llamadas: list[str] = []

    async def generar(tel, canal_):
        llamadas.append(tel)

    async def resolver(numero, negocio_id=None):
        return canal

    await _abrir_hace(1)
    resumen = await script.recuperar_mensajes_sin_respuesta(generar_respuesta=generar, resolver_canal=resolver)

    assert resumen["circuito_abierto"] is True and resumen["encontrados"] == 0 and llamadas == []
    assert [e for e in await mem.listar_eventos_lead("51940000001") if e["tipo"] == "respuesta_recuperada"] == []


async def test_en_el_barrido_un_fallo_de_credito_no_cuenta_como_intento_y_detiene_el_barrido(monkeypatch):
    script = _cargar_script("recuperar_mensajes_sin_respuesta.py")
    negocio, canal, proveedor = await _armar(monkeypatch, "sia-022", user_ts=datetime.utcnow() - timedelta(minutes=10))
    llamadas: list[str] = []

    async def generar(tel, canal_):
        llamadas.append(tel)
        await circuito_ia.abrir("credito")                                 # lo que hace brain.py ante un error de saldo
        await respaldo_sin_ia.derivar_por_falla_ia(tel, canal_, "credito", proveedor=proveedor)

    async def resolver(numero, negocio_id=None):
        return canal

    resumen = await script.recuperar_mensajes_sin_respuesta(generar_respuesta=generar, resolver_canal=resolver)

    assert llamadas == ["51940000001"]
    assert resumen["circuito_abierto"] is True and resumen["intentados"] == 0 and resumen["fallos_ia"] == 0 and resumen["ia_caida"] is False
    assert (await _lead("51940000001")).asesor_asignado == "ase_a"


async def test_el_barrido_deriva_a_una_persona_el_mensaje_que_agoto_sus_dos_intentos(monkeypatch):
    script = _cargar_script("recuperar_mensajes_sin_respuesta.py")
    negocio, canal, proveedor = await _armar(monkeypatch, "sia-023", user_ts=datetime.utcnow() - timedelta(minutes=10))
    derivados: list[tuple] = []

    async def generar_sin_efecto(tel, canal_):
        return None

    async def resolver(numero, negocio_id=None):
        return canal

    async def derivar(tel, canal_, motivo):
        derivados.append((tel, motivo))
        return await respaldo_sin_ia.derivar_por_falla_ia(tel, canal_, motivo, proveedor=proveedor)

    for _ in range(3):
        resumen = await script.recuperar_mensajes_sin_respuesta(generar_respuesta=generar_sin_efecto, resolver_canal=resolver, derivar=derivar)

    assert derivados == [("51940000001", "mensaje_sin_respuesta")]         # solo una vez: ya quedó con un asesor
    assert (await _lead("51940000001")).asesor_asignado == "ase_a"
    assert [m for _, m in proveedor.enviados] == [TEXTO_DENTRO]
    assert resumen["encontrados"] == 0


# ── Aviso en Inicio ──────────────────────────────────────────────────────

async def test_el_aviso_de_modo_sin_ia_es_solo_para_el_admin_y_cuenta_derivados_y_cola(monkeypatch):
    negocio, canal, proveedor = await _armar(monkeypatch, "sia-024", asesores=(("ase_a", True),))
    await _abrir_hace(60)
    await app_main._generar_y_enviar_respuesta_ia("51940000001", canal)    # → asesor
    await mem.resolver_conversation_activa("51940000002", negocio["id"], canal["id"])
    await mem.actualizar_lead("51940000002", negocio_id=negocio["id"], numero_whatsapp_id=canal["phone_number_id"], nombre="Ana")
    await mem.guardar_mensaje("51940000002", "user", "hola", negocio_id=negocio["id"])
    await mem.toggle_usuario_activo("ase_a", negocio["id"])                # ya no queda ningún asesor activo
    await app_main._generar_y_enviar_respuesta_ia("51940000002", canal)    # → cola

    await mem.crear_usuario("admin1", "pw12345", "Admin", "admin", negocio["id"])
    await mem.crear_usuario("super1", "pw12345", "Super", "supervisor", negocio["id"])
    await mem.crear_usuario("ase_z", "pw12345", "Z", "asesor", negocio["id"])
    admin = await mem.obtener_usuario("admin1", negocio_id=negocio["id"])
    supervisor = await mem.obtener_usuario("super1", negocio_id=negocio["id"])
    asesor = await mem.obtener_usuario("ase_z", negocio_id=negocio["id"])

    async def inicio(usuario):
        return json.loads((await dashboard.inicio_json(usuario=usuario)).body)

    avisos = (await inicio(admin))["avisos"]
    (aviso,) = [a for a in avisos if a["id"] == "ia_circuito_abierto"]
    assert aviso["nivel"] == "error" and aviso["titulo"] == "Gabi está en modo sin IA" and aviso["enlace"] is None
    assert "2 clientes ya fueron transferidos a tu equipo con un mensaje automático" in aviso["detalle"]
    assert "1 no tuvieron asesor disponible y están en la cola de supervisión" in aviso["detalle"]
    assert aviso["detalle"].startswith("Desde las ")
    assert set(aviso) == {"id", "nivel", "titulo", "detalle", "enlace"}
    assert (await inicio(supervisor))["avisos"] == []
    assert (await inicio(asesor))["avisos"] == []


async def test_el_aviso_muestra_la_hora_de_lima_y_desaparece_al_cerrarse_el_circuito(monkeypatch):
    negocio = await mem.crear_negocio("Negocio sia-aviso", "sia-aviso")
    await mem.crear_usuario("admin1", "pw12345", "Admin", "admin", negocio["id"])
    admin = await mem.obtener_usuario("admin1", negocio_id=negocio["id"])
    monkeypatch.setattr(circuito_ia, "_ahora", lambda: datetime(2026, 10, 5, 19, 3, 40))      # 14:03 en Lima (UTC-5)
    await circuito_ia.abrir("credito")

    avisos = await dashboard._avisos_inicio(admin)
    assert avisos[0]["detalle"].startswith("Desde las 14:03. 0 clientes")

    await circuito_ia.cerrar()
    assert [a for a in await dashboard._avisos_inicio(admin) if a["id"] == "ia_circuito_abierto"] == []


# ── Horario real: próxima apertura ───────────────────────────────────────

async def test_obtener_proxima_apertura_usa_los_horarios_reales_y_el_horario_por_defecto():
    from zoneinfo import ZoneInfo
    from agent import tools

    lima = ZoneInfo("America/Lima")
    negocio = await mem.crear_negocio("Negocio sia-horario", "sia-horario")
    for dia in range(7):
        await mem.guardar_horario_atencion(negocio["id"], dia, dia <= 5, "08:00", "19:00")

    domingo = datetime(2026, 10, 4, 11, 0, tzinfo=lima)
    p = await tools.obtener_proxima_apertura(negocio["id"], ahora=domingo)
    assert (p["dia"], p["hora"], p["dias_de_diferencia"], p["hoy_es_dia_de_atencion"]) == ("lunes", "8:00 a. m.", 1, False)

    sabado_noche = datetime(2026, 10, 3, 20, 0, tzinfo=lima)
    p = await tools.obtener_proxima_apertura(negocio["id"], ahora=sabado_noche)
    assert (p["dia"], p["dias_de_diferencia"], p["hoy_es_dia_de_atencion"]) == ("lunes", 2, True)

    martes_temprano = datetime(2026, 10, 6, 6, 0, tzinfo=lima)
    p = await tools.obtener_proxima_apertura(negocio["id"], ahora=martes_temprano)
    assert (p["dia"], p["hora"], p["dias_de_diferencia"]) == ("martes", "8:00 a. m.", 0)

    assert await tools.describir_horario_atencion(negocio["id"]) == "lunes a sábado, de 8:00 a. m. a 7:00 p. m."
    # Sin filas para el negocio: el mismo horario de siempre (lunes a sábado, 8:00 a 19:00).
    assert await tools.describir_horario_atencion(None) == "lunes a sábado, de 8:00 a. m. a 7:00 p. m."
    p = await tools.obtener_proxima_apertura(None, ahora=domingo)
    assert p["dia"] == "lunes"
