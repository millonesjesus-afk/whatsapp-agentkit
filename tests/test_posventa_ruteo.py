# tests/test_posventa_ruteo.py — Punto 3 (2026-09-28): hasta este Gate
# ningún Cron cubría "vendido" (Close-Won es indefinido bloqueaba también el
# cierre, no solo la reactivación de Gabi) — una venta con seguimiento
# pendiente podía quedar sin que nadie se enterara si el cliente no volvía a
# escribir (caso real investigado: Mariella Lachira Ramirez, 2026-09-28).
#
# Diseño aprobado: 1) un "vendido" ahora SÍ puede cerrarse definitivamente
# (automático a los 5 días de silencio del cliente, o manual desde la Ficha
# del Lead); 2) cuando el cliente de una venta ya cerrada vuelve a escribir,
# se rutea en silencio al MISMO asesor que la vendió — resultado="postventa"
# — sin ninguna llamada a IA y SIN que Gabi vuelva a responderle nunca (el
# guardado "Close-Won es indefinido" para Gabi sigue intacto en
# reactivar_gabi(), sin tocar).

import os
from datetime import datetime, timedelta

os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")
os.environ.setdefault("WHATSAPP_PROVIDER", "meta")
# Gate 2026-09-23 (debounce, fix #3) — mismo motivo que el resto de los
# tests de webhook: la respuesta de Gabi se programa con una ventana de
# espera en vez de generarse inline.
os.environ["DEBOUNCE_RESPUESTA_SEGUNDOS"] = "0"

from sqlalchemy import select
from starlette.requests import Request

from agent import main as app_main
from agent import memory as mem
from agent.debounce import gestor_debounce_respuestas
from agent.providers.base import MensajeEntrante


async def _esperar_debounce():
    await gestor_debounce_respuestas.esperar_pendientes()


async def _escenario_vendido_abierto(codigo: str, telefono: str, asesor: str = "asesor1"):
    """Lead con una venta asignada y resultado="vendido", SIN cerrar
    definitivamente todavía — punto de partida para probar el cron."""
    negocio = await mem.crear_negocio(f"Negocio {codigo}", codigo)
    canal = await mem.crear_canal_whatsapp(
        nombre=f"Canal {codigo}", phone_number_id=f"4095000{codigo[-2:]}", negocio_id=negocio["id"],
    )
    await mem.actualizar_lead(telefono, negocio_id=negocio["id"], numero_whatsapp_id="x")
    await mem.resolver_conversation_activa(telefono, negocio["id"], canal["id"])
    await mem.asignar_asesor_a_lead(telefono, asesor)
    await mem.actualizar_lead(telefono, resultado="vendido")
    return negocio, canal


async def _escenario_vendido_cerrado(codigo: str, telefono: str, asesor: str = "asesor1"):
    """Igual que arriba, pero ya cerrado definitivamente — punto de partida
    para probar el ruteo cuando el cliente vuelve a escribir."""
    negocio, canal = await _escenario_vendido_abierto(codigo, telefono, asesor)
    assert await mem.cerrar_lead_definitivamente(telefono, negocio["id"], "admin1") is True
    return negocio, canal


async def _contact_id(negocio_id: str, telefono: str) -> str:
    async with mem.async_session() as session:
        contact = (await session.execute(
            select(mem.Contact).where(mem.Contact.negocio_id == negocio_id, mem.Contact.telefono == telefono)
        )).scalars().first()
        return contact.id


async def _conversation_activa_id(negocio_id: str, telefono: str) -> str:
    async with mem.async_session() as session:
        contact = (await session.execute(
            select(mem.Contact).where(mem.Contact.negocio_id == negocio_id, mem.Contact.telefono == telefono)
        )).scalars().first()
        conversation = (await session.execute(
            select(mem.Conversation)
            .where(mem.Conversation.contact_id == contact.id, mem.Conversation.estado == "activa")
        )).scalars().first()
        return conversation.id


# ── memory.py: cerrar_ventas_sin_seguimiento (cron, 4to escenario) ──────

async def test_cron_ventas_cierra_tras_el_umbral_de_dias_sin_respuesta():
    negocio, _ = await _escenario_vendido_abierto("g-pv-01", "51905100001")
    await mem.guardar_mensaje("51905100001", "user", "hola", negocio_id=negocio["id"])
    async with mem.async_session() as session:
        msg = (await session.execute(
            select(mem.Mensaje).where(mem.Mensaje.telefono == "51905100001", mem.Mensaje.role == "user")
        )).scalars().first()
        msg.timestamp = datetime.utcnow() - timedelta(days=6)
        await session.commit()

    cerrados = await mem.cerrar_ventas_sin_seguimiento(dias=5)

    assert "51905100001" in cerrados
    lead = await mem.obtener_lead("51905100001", negocio_id=negocio["id"])
    assert lead["cerrado_definitivamente_en"] is not None
    assert lead["resultado"] == "vendido"  # el cierre no toca el resultado


async def test_cron_ventas_no_cierra_dentro_del_umbral():
    negocio, _ = await _escenario_vendido_abierto("g-pv-02", "51905100002")
    await mem.guardar_mensaje("51905100002", "user", "hola, hace 1 dia", negocio_id=negocio["id"])

    cerrados = await mem.cerrar_ventas_sin_seguimiento(dias=5)

    assert "51905100002" not in cerrados
    lead = await mem.obtener_lead("51905100002", negocio_id=negocio["id"])
    assert lead["cerrado_definitivamente_en"] is None


async def test_cron_ventas_no_toca_resultado_no_vendido():
    # El otro cron (cerrar_leads_definitivamente_inactivos) es el dueño de
    # los 8 resultados cerrados que no son "vendido" — este no debe tocarlos.
    negocio = await mem.crear_negocio("Negocio g-pv-03", "g-pv-03")
    canal = await mem.crear_canal_whatsapp(nombre="Canal g-pv-03", phone_number_id="409500003", negocio_id=negocio["id"])
    await mem.actualizar_lead("51905100003", negocio_id=negocio["id"], numero_whatsapp_id="x")
    await mem.resolver_conversation_activa("51905100003", negocio["id"], canal["id"])
    await mem.asignar_asesor_a_lead("51905100003", "asesor1")
    await mem.actualizar_lead("51905100003", resultado="consulta_atc")
    await mem.guardar_mensaje("51905100003", "user", "hola", negocio_id=negocio["id"])
    async with mem.async_session() as session:
        msg = (await session.execute(
            select(mem.Mensaje).where(mem.Mensaje.telefono == "51905100003", mem.Mensaje.role == "user")
        )).scalars().first()
        msg.timestamp = datetime.utcnow() - timedelta(days=30)
        await session.commit()

    cerrados = await mem.cerrar_ventas_sin_seguimiento(dias=5)

    assert "51905100003" not in cerrados


async def test_cron_ventas_no_cierra_dos_veces():
    negocio, _ = await _escenario_vendido_abierto("g-pv-04", "51905100004")
    await mem.guardar_mensaje("51905100004", "user", "hola", negocio_id=negocio["id"])
    async with mem.async_session() as session:
        msg = (await session.execute(
            select(mem.Mensaje).where(mem.Mensaje.telefono == "51905100004", mem.Mensaje.role == "user")
        )).scalars().first()
        msg.timestamp = datetime.utcnow() - timedelta(days=6)
        await session.commit()

    primera = await mem.cerrar_ventas_sin_seguimiento(dias=5)
    segunda = await mem.cerrar_ventas_sin_seguimiento(dias=5)

    assert "51905100004" in primera
    assert "51905100004" not in segunda


# ── memory.py: obtener_vendedor_venta_anterior / enrutar_posventa_si_corresponde ──

async def test_obtener_vendedor_venta_anterior_encuentra_al_asesor():
    negocio, canal = await _escenario_vendido_cerrado("g-pv-05", "51905100005", asesor="sabarca")
    # DR-4: la Conversation vieja ya está cerrada — se abre una nueva "a mano"
    # (como haría resolver_conversation_activa en el próximo mensaje real).
    conv_nueva, _ = await mem.resolver_conversation_activa("51905100005", negocio["id"], canal["id"])
    contact_id = await _contact_id(negocio["id"], "51905100005")

    asesor = await mem.obtener_vendedor_venta_anterior(contact_id, negocio["id"], conv_nueva.id)

    assert asesor == "sabarca"


async def test_obtener_vendedor_venta_anterior_none_para_contact_nuevo():
    negocio = await mem.crear_negocio("Negocio g-pv-06", "g-pv-06")
    canal = await mem.crear_canal_whatsapp(nombre="Canal g-pv-06", phone_number_id="409500006", negocio_id=negocio["id"])
    await mem.actualizar_lead("51905100006", negocio_id=negocio["id"], numero_whatsapp_id="x")
    conv, _ = await mem.resolver_conversation_activa("51905100006", negocio["id"], canal["id"])
    contact_id = await _contact_id(negocio["id"], "51905100006")

    # Sin ninguna Conversation previa que excluir — un contact recién creado.
    asesor = await mem.obtener_vendedor_venta_anterior(contact_id, negocio["id"], conv.id)

    assert asesor is None


async def test_enrutar_posventa_asigna_resultado_y_limpia_cierre():
    negocio, canal = await _escenario_vendido_cerrado("g-pv-07", "51905100007", asesor="lelespuru")
    conv_nueva, _ = await mem.resolver_conversation_activa("51905100007", negocio["id"], canal["id"])
    contact_id = await _contact_id(negocio["id"], "51905100007")

    asesor = await mem.enrutar_posventa_si_corresponde("51905100007", contact_id, negocio["id"], conv_nueva.id)

    assert asesor == "lelespuru"
    lead = await mem.obtener_lead("51905100007", negocio_id=negocio["id"])
    assert lead["asesor_asignado"] == "lelespuru"
    assert lead["resultado"] == "postventa"
    assert lead["cerrado_definitivamente_en"] is None  # limpiado — si no, main.py lo desasignaría de nuevo

    eventos = await mem.listar_eventos_lead("51905100007")
    assert any(e["tipo"] == "asignado_automatico_postventa" and e["autor"] is None for e in eventos)


async def test_enrutar_posventa_no_hace_nada_sin_venta_previa():
    negocio = await mem.crear_negocio("Negocio g-pv-08", "g-pv-08")
    canal = await mem.crear_canal_whatsapp(nombre="Canal g-pv-08", phone_number_id="409500008", negocio_id=negocio["id"])
    await mem.actualizar_lead("51905100008", negocio_id=negocio["id"], numero_whatsapp_id="x")
    conv, _ = await mem.resolver_conversation_activa("51905100008", negocio["id"], canal["id"])
    contact_id = await _contact_id(negocio["id"], "51905100008")

    asesor = await mem.enrutar_posventa_si_corresponde("51905100008", contact_id, negocio["id"], conv.id)

    assert asesor is None
    lead = await mem.obtener_lead("51905100008", negocio_id=negocio["id"])
    assert lead is None or lead.get("asesor_asignado") is None


# ── main.py: el webhook rutea de punta a punta, sin pasar por Gabi ───────

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


async def _mensajes_assistant(negocio_id: str, telefono: str) -> list:
    async with mem.async_session() as session:
        resultado = await session.execute(
            select(mem.Mensaje).where(
                mem.Mensaje.negocio_id == negocio_id, mem.Mensaje.telefono == telefono,
                mem.Mensaje.role == "assistant",
            )
        )
        return resultado.scalars().all()


async def test_webhook_rutea_a_posventa_sin_que_gabi_responda(monkeypatch):
    telefono = "51905200001"
    negocio, canal = await _escenario_vendido_cerrado("g-pvw-01", telefono, asesor="sabarca")
    canal_dict = {
        "id": canal["id"], "negocio_id": negocio["id"], "unidad_id": None,
        "phone_number_id": canal["phone_number_id"], "modo": "produccion",
    }
    mensaje = MensajeEntrante(
        telefono=telefono, texto="Hola, cuándo me instalan la terma?", mensaje_id="wamid.g-pvw-01",
        es_propio=False, tipo="text", numero_whatsapp_id=canal["phone_number_id"],
    )
    proveedor = _ProveedorFalso(mensaje, canal_dict)
    monkeypatch.setattr(app_main, "proveedor", proveedor)

    async def respuesta_de_gabi(*args, **kwargs):
        raise AssertionError("Gabi no debe llamarse nunca para un cliente con una venta ya cerrada")
    monkeypatch.setattr(app_main.servicio_inteligencia, "generar_respuesta", respuesta_de_gabi)

    await app_main.webhook_handler(_request())
    await _esperar_debounce()

    # Gabi nunca respondió — el mensaje quedó guardado para el asesor.
    assert await _mensajes_assistant(negocio["id"], telefono) == []
    assert proveedor.enviados == []

    lead = await mem.obtener_lead(telefono, negocio_id=negocio["id"])
    assert lead["asesor_asignado"] == "sabarca"  # mismo asesor que la venta original
    assert lead["resultado"] == "postventa"
    assert lead["cerrado_definitivamente_en"] is None
    assert lead["visto_asesor"] is False  # debe aparecer como "Nuevo" para el asesor

    eventos = await mem.listar_eventos_lead(telefono)
    assert any(e["tipo"] == "asignado_automatico_postventa" for e in eventos)


async def test_no_rutea_a_posventa_si_la_venta_vigente_sigue_activa():
    # Caso real investigado (Mariella Lachira, 2026-09-28): el "vendido"
    # NUNCA se cerró definitivamente (hoy ningún cron lo cubre), así que la
    # Conversation sigue ACTIVA — obtener_vendedor_venta_anterior solo mira
    # Conversation con estado="cerrada" (ver su docstring), así que no debe
    # encontrar nada acá aunque la Opportunity vigente sea "vendido".
    telefono = "51905200002"
    negocio, canal = await _escenario_vendido_abierto("g-pvw-02", telefono, asesor="sabarca")
    contact_id = await _contact_id(negocio["id"], telefono)
    conv_id = await _conversation_activa_id(negocio["id"], telefono)

    resultado = await mem.enrutar_posventa_si_corresponde(telefono, contact_id, negocio["id"], conv_id)

    assert resultado is None
    lead = await mem.obtener_lead(telefono, negocio_id=negocio["id"])
    assert lead["resultado"] == "vendido"  # sin tocar
