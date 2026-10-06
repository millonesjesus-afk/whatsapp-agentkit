# tests/test_reapertura_tras_cierre_definitivo.py — P4 (2026-10-06): cuando un
# cliente vuelve a escribir DESPUÉS de un cierre definitivo, DR-4 abre un ciclo
# nuevo (Conversation + Opportunity sin resultado). Antes, la conversación nueva
# no dejaba huella de lo anterior y el Lead conservaba el resultado viejo
# (Pipeline lo veía, Bandeja no). Ahora: evento `reabierto_por_cliente` en la
# conversación nueva y Lead.resultado vuelve a NULL (salvo "vendido", que va por
# la lógica de posventa). Caso real: Mario 51962726506 (lelespuru).

import importlib.util
import os
from datetime import datetime, timedelta
from pathlib import Path

os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")
os.environ.setdefault("WHATSAPP_PROVIDER", "meta")
os.environ["DEBOUNCE_RESPUESTA_SEGUNDOS"] = "0"

from sqlalchemy import select
from starlette.requests import Request

from agent import main as app_main
from agent import memory as mem
from agent.debounce import gestor_debounce_respuestas
from agent.providers.base import MensajeEntrante


def _cargar_script_backfill():
    ruta = Path(__file__).resolve().parent.parent / "scripts" / "backfill_reaperturas.py"
    spec = importlib.util.spec_from_file_location("backfill_reaperturas", ruta)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


async def _escenario(codigo: str, telefono: str, resultado: str | None = "sin_respuesta", asesor: str = "lelespuru"):
    negocio = await mem.crear_negocio(f"Negocio {codigo}", codigo)
    canal = await mem.crear_canal_whatsapp(
        nombre=f"Canal {codigo}", phone_number_id=f"4096000{codigo[-2:]}", negocio_id=negocio["id"],
    )
    await mem.actualizar_lead(telefono, negocio_id=negocio["id"], numero_whatsapp_id="x")
    conv_vieja, _ = await mem.resolver_conversation_activa(telefono, negocio["id"], canal["id"])
    await mem.asignar_asesor_a_lead(telefono, asesor)
    if resultado:
        await mem.actualizar_lead(telefono, campos_explicitos=("resultado",), resultado=resultado)
    return negocio, canal, conv_vieja


async def _eventos(telefono: str, tipo: str = "reabierto_por_cliente") -> list[dict]:
    return [e for e in await mem.listar_eventos_lead(telefono) if e["tipo"] == tipo]


async def _opportunities(conversation_id: str) -> list:
    async with mem.async_session() as session:
        return (await session.execute(
            select(mem.Opportunity).where(mem.Opportunity.conversation_id == conversation_id)
        )).scalars().all()


# ── memory.py: resolver_conversation_activa ──────────────────────────────

async def test_reapertura_deja_evento_y_limpia_el_resultado_del_lead():
    telefono = "51906100001"
    negocio, canal, conv_vieja = await _escenario("g-rp-01", telefono)
    assert await mem.cerrar_lead_definitivamente(telefono, negocio["id"], "lelespuru") is True

    conv_nueva, opp_nueva = await mem.resolver_conversation_activa(telefono, negocio["id"], canal["id"])

    assert conv_nueva.id != conv_vieja.id
    assert opp_nueva.resultado is None
    eventos = await _eventos(telefono)
    assert len(eventos) == 1
    evento = eventos[0]
    assert evento["conversation_id"] == conv_nueva.id and evento["opportunity_id"] == opp_nueva.id
    assert evento["autor"] is None
    assert evento["descripcion"] == "Reabierto por el cliente — antes: Sin respuesta (gestionado por lelespuru)"
    assert evento["payload"]["resultado_anterior"] == "sin_respuesta"
    assert evento["payload"]["asesor_anterior"] == "lelespuru"
    assert evento["payload"]["conversation_anterior_id"] == conv_vieja.id
    assert evento["payload"]["cerrado_en"] is not None

    # R4: el Lead ya no diverge de la Opportunity nueva (que nació sin resultado)
    lead = await mem.obtener_lead(telefono, negocio_id=negocio["id"])
    assert lead["resultado"] is None
    # La Opportunity de la conversación cerrada conserva su resultado (historia)
    viejas = await _opportunities(conv_vieja.id)
    assert [o.resultado for o in viejas] == ["sin_respuesta"]


async def test_reapertura_es_idempotente_ante_reintentos():
    telefono = "51906100002"
    negocio, canal, _ = await _escenario("g-rp-02", telefono)
    await mem.cerrar_lead_definitivamente(telefono, negocio["id"], "lelespuru")

    await mem.resolver_conversation_activa(telefono, negocio["id"], canal["id"])
    await mem.resolver_conversation_activa(telefono, negocio["id"], canal["id"])  # reintento del webhook
    await mem.resolver_conversation_activa(telefono, negocio["id"], canal["id"])

    assert len(await _eventos(telefono)) == 1


async def test_sin_cierre_definitivo_no_hay_reapertura_ni_se_toca_el_resultado():
    telefono = "51906100003"
    negocio, canal, conv_vieja = await _escenario("g-rp-03", telefono, resultado="consulta_atc")

    conv, _ = await mem.resolver_conversation_activa(telefono, negocio["id"], canal["id"])

    assert conv.id == conv_vieja.id  # no se abrió ciclo nuevo
    assert await _eventos(telefono) == []
    lead = await mem.obtener_lead(telefono, negocio_id=negocio["id"])
    assert lead["resultado"] == "consulta_atc"


async def test_primer_contacto_no_registra_reapertura():
    negocio = await mem.crear_negocio("Negocio g-rp-04", "g-rp-04")
    canal = await mem.crear_canal_whatsapp(nombre="Canal g-rp-04", phone_number_id="409600004", negocio_id=negocio["id"])
    await mem.actualizar_lead("51906100004", negocio_id=negocio["id"], numero_whatsapp_id="x")

    await mem.resolver_conversation_activa("51906100004", negocio["id"], canal["id"])

    assert await _eventos("51906100004") == []


async def test_vendido_queda_fuera_de_r4_va_por_posventa():
    # Un vendido que vuelve a escribir NO se reinicia en el resolver: el
    # resultado lo decide enrutar_posventa_si_corresponde (mismo asesor,
    # "postventa"), que deja su propio evento.
    telefono = "51906100005"
    negocio, canal, _ = await _escenario("g-rp-05", telefono, resultado="vendido", asesor="sabarca")
    await mem.cerrar_lead_definitivamente(telefono, negocio["id"], "admin1")

    await mem.resolver_conversation_activa(telefono, negocio["id"], canal["id"])

    assert await _eventos(telefono) == []
    lead = await mem.obtener_lead(telefono, negocio_id=negocio["id"])
    assert lead["resultado"] == "vendido"  # sin tocar: lo resuelve la posventa


async def test_reapertura_limpia_la_cita_del_ciclo_anterior():
    telefono = "51906100006"
    negocio, canal, _ = await _escenario("g-rp-06", telefono, resultado="no_interesado")
    cita = datetime(2026, 10, 10, 15, 0)
    async with mem.async_session() as session:
        lead = await session.get(mem.Lead, telefono)
        lead.fecha_agendada = cita  # resto de una cita vieja: el resultado cambió después
        lead.veces_rotado_espera = 1
        lead.minutos_espera_asesor = 25
        await session.commit()
    await mem.cerrar_lead_definitivamente(telefono, negocio["id"], "lelespuru")

    await mem.resolver_conversation_activa(telefono, negocio["id"], canal["id"])

    lead = await mem.obtener_lead(telefono, negocio_id=negocio["id"])
    assert lead["resultado"] is None and lead["fecha_agendada"] is None
    async with mem.async_session() as session:
        crudo = await session.get(mem.Lead, telefono)
        assert crudo.veces_rotado_espera == 0 and crudo.minutos_espera_asesor == 0 and crudo.derivado_en is None
    evento = (await _eventos(telefono))[0]
    assert evento["payload"]["fecha_agendada_anterior"] == cita.isoformat()


async def test_reapertura_sin_asesor_anterior_omite_gestionado_por():
    telefono = "51906100007"
    negocio = await mem.crear_negocio("Negocio g-rp-07", "g-rp-07")
    canal = await mem.crear_canal_whatsapp(nombre="Canal g-rp-07", phone_number_id="409600007", negocio_id=negocio["id"])
    await mem.actualizar_lead(telefono, negocio_id=negocio["id"], numero_whatsapp_id="x")
    await mem.resolver_conversation_activa(telefono, negocio["id"], canal["id"])
    # sin_respuesta automático: lead sin asesor (lo que deja procesar_inactividad_clientes)
    await mem.actualizar_lead(telefono, campos_explicitos=("resultado",), resultado="sin_respuesta")
    assert await mem.cerrar_lead_definitivamente(telefono, negocio["id"], None) is True

    await mem.resolver_conversation_activa(telefono, negocio["id"], canal["id"])

    evento = (await _eventos(telefono))[0]
    assert evento["descripcion"] == "Reabierto por el cliente — antes: Sin respuesta"
    assert evento["payload"]["asesor_anterior"] is None


# ── main.py: el webhook de punta a punta ─────────────────────────────────

def _request() -> Request:
    cuerpo = b'{"object": "whatsapp_business_account"}'
    entregado = False

    async def recibir():
        nonlocal entregado
        if entregado:
            return {"type": "http.disconnect"}
        entregado = True
        return {"type": "http.request", "body": cuerpo, "more_body": False}

    return Request({
        "type": "http", "method": "POST", "path": "/webhook", "headers": [], "query_string": b"",
        "client": ("203.0.113.9", 1234),
    }, recibir)


class _ProveedorFalso:
    def __init__(self, mensaje, canal):
        self._mensaje, self._canal = mensaje, canal
        self.enviados: list[str] = []

    async def verificar_firma(self, request, cuerpo):
        return True

    async def parsear_webhook(self, request):
        return [self._mensaje]

    async def resolver_canal(self, numero_whatsapp_id, negocio_id=None):
        return self._canal

    async def marcar_leido_y_escribiendo(self, mensaje_id, canal=None):
        return True

    async def enviar_mensaje(self, telefono, mensaje, canal=None, mensaje_id_citado=None):
        self.enviados.append(mensaje)
        return True, "wamid.OK"


async def test_webhook_reapertura_registra_evento_una_vez_y_gabi_retoma(monkeypatch):
    telefono = "51906200001"
    negocio, canal, conv_vieja = await _escenario("g-rpw-01", telefono)
    await mem.cerrar_lead_definitivamente(telefono, negocio["id"], "lelespuru")
    canal_dict = {
        "id": canal["id"], "negocio_id": negocio["id"], "unidad_id": None,
        "phone_number_id": canal["phone_number_id"], "modo": "produccion",
    }
    mensaje = MensajeEntrante(
        telefono=telefono, texto="Hola de nuevo", mensaje_id="wamid.g-rpw-01",
        es_propio=False, tipo="text", numero_whatsapp_id=canal["phone_number_id"],
    )
    proveedor = _ProveedorFalso(mensaje, canal_dict)
    monkeypatch.setattr(app_main, "proveedor", proveedor)

    async def respuesta_de_gabi(*args, **kwargs):
        return "¡Hola! ¿En qué te ayudo?", False, None, None
    async def sin_datos(*args, **kwargs):
        return {}
    monkeypatch.setattr(app_main.servicio_inteligencia, "generar_respuesta", respuesta_de_gabi)
    monkeypatch.setattr(app_main.servicio_inteligencia, "extraer_datos_lead", sin_datos)

    await app_main.webhook_handler(_request())
    await gestor_debounce_respuestas.esperar_pendientes()
    await app_main.webhook_handler(_request())  # reintento de Meta con el mismo mensaje
    await gestor_debounce_respuestas.esperar_pendientes()

    eventos = await _eventos(telefono)
    assert len(eventos) == 1
    assert eventos[0]["payload"]["conversation_anterior_id"] == conv_vieja.id
    lead = await mem.obtener_lead(telefono, negocio_id=negocio["id"])
    assert lead["resultado"] is None  # ya no diverge de la Opportunity nueva
    assert lead["asesor_asignado"] is None and lead["cerrado_definitivamente_en"] is None  # Gabi retomó
    # La liberación sigue dejando su propio evento, además del de reapertura
    assert len(await _eventos(telefono, "desasignado_automatico")) == 1
    assert proveedor.enviados[:1] == ["¡Hola! ¿En qué te ayudo?"]


async def test_webhook_vendido_sigue_por_posventa_sin_evento_de_reapertura(monkeypatch):
    telefono = "51906200002"
    negocio, canal, _ = await _escenario("g-rpw-02", telefono, resultado="vendido", asesor="sabarca")
    await mem.cerrar_lead_definitivamente(telefono, negocio["id"], "admin1")
    canal_dict = {
        "id": canal["id"], "negocio_id": negocio["id"], "unidad_id": None,
        "phone_number_id": canal["phone_number_id"], "modo": "produccion",
    }
    mensaje = MensajeEntrante(
        telefono=telefono, texto="¿Cuándo me instalan?", mensaje_id="wamid.g-rpw-02",
        es_propio=False, tipo="text", numero_whatsapp_id=canal["phone_number_id"],
    )
    monkeypatch.setattr(app_main, "proveedor", _ProveedorFalso(mensaje, canal_dict))

    async def respuesta_de_gabi(*args, **kwargs):
        raise AssertionError("Gabi no debe llamarse para una venta cerrada")
    monkeypatch.setattr(app_main.servicio_inteligencia, "generar_respuesta", respuesta_de_gabi)

    await app_main.webhook_handler(_request())
    await gestor_debounce_respuestas.esperar_pendientes()

    assert await _eventos(telefono) == []
    assert len(await _eventos(telefono, "asignado_automatico_postventa")) == 1
    lead = await mem.obtener_lead(telefono, negocio_id=negocio["id"])
    assert lead["resultado"] == "postventa" and lead["asesor_asignado"] == "sabarca"


# ── scripts/backfill_reaperturas.py ──────────────────────────────────────

async def _borrar_eventos_de_reapertura():
    """Simula una reapertura de antes del cambio: quita el evento y deja el resto."""
    async with mem.async_session() as session:
        for e in (await session.execute(select(mem.EventoLead).where(mem.EventoLead.tipo == "reabierto_por_cliente"))).scalars().all():
            await session.delete(e)
        await session.commit()


async def test_backfill_dry_run_no_escribe_y_aplicar_es_idempotente():
    backfill = _cargar_script_backfill()
    telefono = "51906300001"
    negocio, canal, conv_vieja = await _escenario("g-rpb-01", telefono)
    await mem.cerrar_lead_definitivamente(telefono, negocio["id"], "lelespuru")
    conv_nueva, _ = await mem.resolver_conversation_activa(telefono, negocio["id"], canal["id"])
    await _borrar_eventos_de_reapertura()
    # Un ciclo más nuevo ya evolucionó: el backfill no debe tocar Lead.resultado
    await mem.actualizar_lead(telefono, campos_explicitos=("resultado",), resultado="agendado")

    async with mem.async_session() as session:
        plan = await backfill.calcular_reaperturas(session)
    assert [(f["telefono"], f["resultado_anterior"], f["asesor_anterior"]) for f in plan] == [
        (telefono, "sin_respuesta", "lelespuru"),
    ]
    assert await _eventos(telefono) == []  # calcular = dry-run, nada escrito

    async with mem.async_session() as session:
        assert await backfill.aplicar_reaperturas(session, plan) == 1
    eventos = await _eventos(telefono)
    assert len(eventos) == 1
    assert eventos[0]["conversation_id"] == conv_nueva.id
    assert eventos[0]["descripcion"] == "Reabierto por el cliente — antes: Sin respuesta (gestionado por lelespuru)"
    assert eventos[0]["payload"]["conversation_anterior_id"] == conv_vieja.id
    lead = await mem.obtener_lead(telefono, negocio_id=negocio["id"])
    assert lead["resultado"] == "agendado"  # intacto

    async with mem.async_session() as session:
        assert await backfill.calcular_reaperturas(session) == []  # ya cubierta
        assert await backfill.aplicar_reaperturas(session, plan) == 0  # plan viejo no duplica


async def test_backfill_toma_el_resultado_del_timeline_si_la_opportunity_no_lo_tiene():
    backfill = _cargar_script_backfill()
    telefono = "51906300002"
    negocio, canal, conv_vieja = await _escenario("g-rpb-02", telefono, resultado="no_interesado")
    await mem.cerrar_lead_definitivamente(telefono, negocio["id"], "lelespuru")
    await mem.registrar_evento_lead(
        telefono, tipo="resultado_cambiado", descripcion="x", autor="lelespuru",
        payload={"campo": "resultado", "anterior": None, "nuevo": "no_interesado"},
    )
    await mem.resolver_conversation_activa(telefono, negocio["id"], canal["id"])
    await _borrar_eventos_de_reapertura()
    async with mem.async_session() as session:  # la Opportunity vieja perdió su resultado
        for o in (await session.execute(select(mem.Opportunity).where(mem.Opportunity.conversation_id == conv_vieja.id))).scalars().all():
            o.resultado = None
        await session.commit()

    async with mem.async_session() as session:
        plan = await backfill.calcular_reaperturas(session)

    assert len(plan) == 1 and plan[0]["resultado_anterior"] == "no_interesado"


async def test_backfill_omite_ventas_y_conversaciones_sin_ciclo_previo():
    backfill = _cargar_script_backfill()
    # Una venta que reabrió (posventa) y un contacto con una sola conversación
    negocio, canal, _ = await _escenario("g-rpb-03", "51906300003", resultado="vendido", asesor="sabarca")
    await mem.cerrar_lead_definitivamente("51906300003", negocio["id"], "admin1")
    await mem.resolver_conversation_activa("51906300003", negocio["id"], canal["id"])
    await mem.actualizar_lead("51906300004", negocio_id=negocio["id"], numero_whatsapp_id="x")
    await mem.resolver_conversation_activa("51906300004", negocio["id"], canal["id"])

    async with mem.async_session() as session:
        assert await backfill.calcular_reaperturas(session) == []
