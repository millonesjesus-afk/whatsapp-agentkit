# tests/test_cierre_definitivo.py — Gate 2026-09-23: un `resultado` cerrado
# (ej. "consulta_atc") ya NO reactiva a Gabi por sí solo — hace falta un
# cierre EXPLÍCITO (manual o automático por inactividad del cliente). Caso
# real que esto corrige: Joanna Chuica — un asesor de OTRO tema le escribió
# sobre un caso ya con resultado="consulta_atc", y el siguiente mensaje del
# cliente reactivaba a Gabi sin que ese asesor se enterara.

import os
from datetime import datetime, timedelta

os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")
os.environ.setdefault("WHATSAPP_PROVIDER", "meta")
# Gate 2026-09-23 (debounce, fix #3): ver la misma nota en
# test_gabi_envio_fallido.py — la respuesta de texto ahora se programa con
# una ventana de espera en vez de generarse inline.
os.environ["DEBOUNCE_RESPUESTA_SEGUNDOS"] = "0"

from fastapi import HTTPException
import pytest
from sqlalchemy import select
from starlette.requests import Request

from agent import dashboard
from agent import main as app_main
from agent import memory as mem
from agent.debounce import gestor_debounce_respuestas
from agent.providers.base import MensajeEntrante


async def _esperar_debounce():
    await gestor_debounce_respuestas.esperar_pendientes()


async def _escenario(codigo: str, telefono: str, resultado: str = "consulta_atc"):
    negocio = await mem.crear_negocio(f"Negocio {codigo}", codigo)
    canal = await mem.crear_canal_whatsapp(
        nombre=f"Canal {codigo}", phone_number_id=f"4094000{codigo[-2:]}", negocio_id=negocio["id"],
    )
    await mem.actualizar_lead(telefono, negocio_id=negocio["id"], numero_whatsapp_id="x")
    await mem.resolver_conversation_activa(telefono, negocio["id"], canal["id"])
    await mem.asignar_asesor_a_lead(telefono, "asesor1")
    await mem.actualizar_lead(telefono, resultado=resultado)
    return negocio, canal


async def _conversation_id(negocio_id: str, telefono: str) -> str:
    """Resuelve el id de la Conversation activa de un teléfono — para
    verificar el mirror get-only de `cerrado_definitivamente_en` que la
    Nueva Experiencia (Gate 5.3) lee, separado del `Lead` legacy."""
    async with mem.async_session() as session:
        contact = (await session.execute(
            select(mem.Contact).where(mem.Contact.negocio_id == negocio_id, mem.Contact.telefono == telefono)
        )).scalars().first()
        conversation = (await session.execute(
            select(mem.Conversation)
            .where(mem.Conversation.contact_id == contact.id)
            .order_by(mem.Conversation.creado.desc())
            .limit(1)
        )).scalars().first()
        return conversation.id


# ── memory.py: cerrar_lead_definitivamente (manual) ─────────────────────

async def test_cierre_manual_rechaza_resultado_abierto():
    negocio, _ = await _escenario("g-cd-01", "51904100001", resultado=None)

    assert await mem.cerrar_lead_definitivamente("51904100001", negocio["id"], "admin1") is False
    lead = await mem.obtener_lead("51904100001", negocio_id=negocio["id"])
    assert lead["cerrado_definitivamente_en"] is None


async def test_cierre_manual_rechaza_vendido():
    negocio, _ = await _escenario("g-cd-02", "51904100002", resultado="vendido")

    assert await mem.cerrar_lead_definitivamente("51904100002", negocio["id"], "admin1") is False


async def test_cierre_manual_funciona_con_resultado_cerrado_y_deja_evento():
    negocio, _ = await _escenario("g-cd-03", "51904100003", resultado="consulta_atc")

    assert await mem.cerrar_lead_definitivamente("51904100003", negocio["id"], "admin1") is True
    lead = await mem.obtener_lead("51904100003", negocio_id=negocio["id"])
    assert lead["cerrado_definitivamente_en"] is not None

    eventos = await mem.listar_eventos_lead("51904100003")
    assert any(e["tipo"] == "cerrado_definitivamente" and e["autor"] == "admin1" for e in eventos)

    # Mirror get-only hacia Conversation (Gate 5.3) — la Nueva Experiencia
    # lee esto, no Lead directamente.
    conv_id = await _conversation_id(negocio["id"], "51904100003")
    detalle = await mem.obtener_conversation_detalle(conv_id, negocio["id"])
    assert detalle["cerrado_definitivamente_en"] is not None


async def test_liberar_asignacion_limpia_el_cierre_definitivo():
    negocio, _ = await _escenario("g-cd-04", "51904100004", resultado="consulta_atc")
    await mem.cerrar_lead_definitivamente("51904100004", negocio["id"], "admin1")

    await mem.liberar_asignacion("51904100004", motivo="cierre_definitivo")

    lead = await mem.obtener_lead("51904100004", negocio_id=negocio["id"])
    assert lead["cerrado_definitivamente_en"] is None
    assert lead["asesor_asignado"] is None


# ── memory.py: cerrar_leads_definitivamente_inactivos (cron) ────────────

async def test_cron_cierra_solo_tras_el_umbral_de_dias_sin_respuesta_del_cliente():
    negocio, canal = await _escenario("g-cd-05", "51904100005", resultado="consulta_atc")
    # El único mensaje real es el de _escenario (resolver_conversation_activa
    # no manda mensajes) — se fuerza uno del cliente viejo directamente.
    await mem.guardar_mensaje("51904100005", "user", "hola", negocio_id=negocio["id"])
    async with mem.async_session() as session:
        msg = (await session.execute(
            select(mem.Mensaje).where(mem.Mensaje.telefono == "51904100005", mem.Mensaje.role == "user")
        )).scalars().first()
        msg.timestamp = datetime.utcnow() - timedelta(days=8)
        await session.commit()

    cerrados = await mem.cerrar_leads_definitivamente_inactivos(dias=7)

    assert "51904100005" in cerrados
    lead = await mem.obtener_lead("51904100005", negocio_id=negocio["id"])
    assert lead["cerrado_definitivamente_en"] is not None

    # El cron también debe mirror-escribir a Conversation (mismo camino que
    # el cierre manual, vía cerrar_lead_definitivamente reusada).
    conv_id = await _conversation_id(negocio["id"], "51904100005")
    detalle = await mem.obtener_conversation_detalle(conv_id, negocio["id"])
    assert detalle["cerrado_definitivamente_en"] is not None

    eventos = await mem.listar_eventos_lead("51904100005")
    assert any(e["tipo"] == "cerrado_definitivamente_automatico" and e["autor"] is None for e in eventos)


async def test_cron_no_cierra_dentro_del_umbral():
    negocio, _ = await _escenario("g-cd-06", "51904100006", resultado="consulta_atc")
    await mem.guardar_mensaje("51904100006", "user", "hola, hace 1 dia", negocio_id=negocio["id"])

    cerrados = await mem.cerrar_leads_definitivamente_inactivos(dias=7)

    assert "51904100006" not in cerrados
    lead = await mem.obtener_lead("51904100006", negocio_id=negocio["id"])
    assert lead["cerrado_definitivamente_en"] is None


async def test_cron_no_toca_resultado_abierto_ni_vendido():
    negocio, _ = await _escenario("g-cd-07", "51904100007", resultado=None)
    await _escenario("g-cd-07b", "51904100008", resultado="vendido")
    async with mem.async_session() as session:
        for telefono in ("51904100007", "51904100008"):
            await mem.guardar_mensaje(telefono, "user", "hola", negocio_id=negocio["id"])
        for m in (await session.execute(
            select(mem.Mensaje).where(mem.Mensaje.telefono.in_(["51904100007", "51904100008"]), mem.Mensaje.role == "user")
        )).scalars().all():
            m.timestamp = datetime.utcnow() - timedelta(days=30)
        await session.commit()

    cerrados = await mem.cerrar_leads_definitivamente_inactivos(dias=7)

    assert "51904100007" not in cerrados and "51904100008" not in cerrados


async def test_cron_no_cierra_dos_veces():
    negocio, _ = await _escenario("g-cd-08", "51904100009", resultado="consulta_atc")
    await mem.guardar_mensaje("51904100009", "user", "hola", negocio_id=negocio["id"])
    async with mem.async_session() as session:
        msg = (await session.execute(
            select(mem.Mensaje).where(mem.Mensaje.telefono == "51904100009", mem.Mensaje.role == "user")
        )).scalars().first()
        msg.timestamp = datetime.utcnow() - timedelta(days=8)
        await session.commit()

    primera = await mem.cerrar_leads_definitivamente_inactivos(dias=7)
    segunda = await mem.cerrar_leads_definitivamente_inactivos(dias=7)

    assert "51904100009" in primera
    assert "51904100009" not in segunda  # ya tiene cerrado_definitivamente_en, no vuelve a calificar


# ── main.py: el webhook respeta el nuevo gatillo ─────────────────────────

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


async def test_webhook_no_reactiva_a_gabi_con_resultado_cerrado_sin_cierre_definitivo(monkeypatch):
    telefono = "51904200001"
    negocio, canal = await _escenario("g-cdw-01", telefono, resultado="consulta_atc")
    canal_dict = {
        "id": canal["id"], "negocio_id": negocio["id"], "unidad_id": None,
        "phone_number_id": canal["phone_number_id"], "modo": "produccion",
    }
    mensaje = MensajeEntrante(
        telefono=telefono, texto="Necesito saber mi deuda", mensaje_id="wamid.g-cdw-01",
        es_propio=False, tipo="text", numero_whatsapp_id=canal["phone_number_id"],
    )
    proveedor = _ProveedorFalso(mensaje, canal_dict)
    monkeypatch.setattr(app_main, "proveedor", proveedor)

    async def respuesta_de_gabi(*args, **kwargs):
        return "no debería llamarse", False, None, None
    monkeypatch.setattr(app_main.servicio_inteligencia, "generar_respuesta", respuesta_de_gabi)

    await app_main.webhook_handler(_request())

    # Sin cierre definitivo, el resultado cerrado YA NO reactiva a Gabi —
    # el mensaje se guarda para el asesor, sin respuesta automática.
    assert await _mensajes_assistant(negocio["id"], telefono) == []
    assert proveedor.enviados == []
    lead = await mem.obtener_lead(telefono, negocio_id=negocio["id"])
    assert lead["asesor_asignado"] == "asesor1"


async def test_webhook_reactiva_a_gabi_cuando_el_caso_esta_cerrado_definitivamente(monkeypatch):
    telefono = "51904200002"
    negocio, canal = await _escenario("g-cdw-02", telefono, resultado="consulta_atc")
    await mem.cerrar_lead_definitivamente(telefono, negocio["id"], "admin1")
    canal_dict = {
        "id": canal["id"], "negocio_id": negocio["id"], "unidad_id": None,
        "phone_number_id": canal["phone_number_id"], "modo": "produccion",
    }
    mensaje = MensajeEntrante(
        telefono=telefono, texto="Hola de nuevo", mensaje_id="wamid.g-cdw-02",
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
    await _esperar_debounce()

    assert len(await _mensajes_assistant(negocio["id"], telefono)) == 1
    assert proveedor.enviados == ["¡Hola! ¿En qué te ayudo?"]
    lead = await mem.obtener_lead(telefono, negocio_id=negocio["id"])
    assert lead["asesor_asignado"] is None  # se liberó — Gabi retomó
    assert lead["cerrado_definitivamente_en"] is None  # se limpió, no queda "consumido"


# ── dashboard.py: GET /conversation/{id} y POST .../cerrar-definitivamente ──
# (lo que de verdad consume el frontend — PanelCierreDefinitivo en
# ficha-lead.tsx — no solo las funciones de memory.py de más arriba)

async def test_ruta_conversation_detalle_expone_cerrado_definitivamente_en():
    negocio, _ = await _escenario("g-cdh-01", "51904300001", resultado="consulta_atc")
    conv_id = await _conversation_id(negocio["id"], "51904300001")
    admin = {"username": "admin1", "rol": "admin", "negocio_id": negocio["id"]}

    antes = await dashboard.conversation_detalle(conv_id, usuario=admin)
    import json
    assert json.loads(antes.body)["cerrado_definitivamente_en"] is None

    await mem.cerrar_lead_definitivamente("51904300001", negocio["id"], "admin1")

    despues = await dashboard.conversation_detalle(conv_id, usuario=admin)
    assert json.loads(despues.body)["cerrado_definitivamente_en"] is not None


async def test_ruta_cerrar_definitivamente_funciona_desde_el_endpoint_http():
    negocio, _ = await _escenario("g-cdh-02", "51904300002", resultado="consulta_atc")
    conv_id = await _conversation_id(negocio["id"], "51904300002")
    admin = {"username": "admin1", "nombre": "admin1", "rol": "admin", "negocio_id": negocio["id"]}

    respuesta = await dashboard.conversation_cerrar_definitivamente(conv_id, usuario=admin, _csrf=None)

    import json
    cuerpo = json.loads(respuesta.body)
    assert cuerpo["ok"] is True
    assert cuerpo["lead"]["cerrado_definitivamente_en"] is not None

    eventos = await mem.listar_eventos_lead("51904300002")
    assert any(e["tipo"] == "cerrado_definitivamente" and e["autor"] == "admin1" for e in eventos)


async def test_ruta_cerrar_definitivamente_400_si_resultado_abierto():
    negocio, _ = await _escenario("g-cdh-03", "51904300003", resultado=None)
    conv_id = await _conversation_id(negocio["id"], "51904300003")
    admin = {"username": "admin1", "nombre": "admin1", "rol": "admin", "negocio_id": negocio["id"]}

    with pytest.raises(HTTPException) as exc:
        await dashboard.conversation_cerrar_definitivamente(conv_id, usuario=admin, _csrf=None)
    assert exc.value.status_code == 400


async def test_ruta_cerrar_definitivamente_400_si_vendido():
    negocio, _ = await _escenario("g-cdh-04", "51904300004", resultado="vendido")
    conv_id = await _conversation_id(negocio["id"], "51904300004")
    admin = {"username": "admin1", "nombre": "admin1", "rol": "admin", "negocio_id": negocio["id"]}

    with pytest.raises(HTTPException) as exc:
        await dashboard.conversation_cerrar_definitivamente(conv_id, usuario=admin, _csrf=None)
    assert exc.value.status_code == 400


async def test_ruta_cerrar_definitivamente_404_cross_tenant():
    negocio_a, _ = await _escenario("g-cdh-05", "51904300005", resultado="consulta_atc")
    negocio_b = await mem.crear_negocio("Negocio g-cdh-05b", "g-cdh-05b")
    conv_id = await _conversation_id(negocio_a["id"], "51904300005")

    admin_b = {"username": "admin_b", "rol": "admin", "negocio_id": negocio_b["id"]}
    with pytest.raises(HTTPException) as exc:
        await dashboard.conversation_cerrar_definitivamente(conv_id, usuario=admin_b, _csrf=None)
    assert exc.value.status_code == 404


async def test_ruta_cerrar_definitivamente_403_asesor_sin_acceso():
    negocio, _ = await _escenario("g-cdh-06", "51904300006", resultado="consulta_atc")
    conv_id = await _conversation_id(negocio["id"], "51904300006")

    asesor_ajeno = {"username": "otro_asesor", "rol": "asesor", "negocio_id": negocio["id"]}
    with pytest.raises(HTTPException) as exc:
        await dashboard.conversation_cerrar_definitivamente(conv_id, usuario=asesor_ajeno, _csrf=None)
    assert exc.value.status_code == 403


async def test_ruta_cerrar_definitivamente_asesor_dueno_si_puede():
    negocio, _ = await _escenario("g-cdh-07", "51904300007", resultado="consulta_atc")
    conv_id = await _conversation_id(negocio["id"], "51904300007")

    asesor_dueno = {"username": "asesor1", "nombre": "asesor1", "rol": "asesor", "negocio_id": negocio["id"]}
    respuesta = await dashboard.conversation_cerrar_definitivamente(conv_id, usuario=asesor_dueno, _csrf=None)

    import json
    assert json.loads(respuesta.body)["lead"]["cerrado_definitivamente_en"] is not None
