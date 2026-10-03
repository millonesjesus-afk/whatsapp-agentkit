# tests/test_bandeja_orden_por_ultimo_mensaje.py — 2026-10-03.
#
# Caso real: los Cron de cierre automático cerraron 57 leads de una vez y cada
# cierre ponía `Conversation.actualizado = ahora`, así que la Bandeja (que
# ordenaba por ese campo) los subía todos al tope con "hace unos minutos"
# aunque su último mensaje real era de hace una semana o más. La Bandeja ahora
# ordena y muestra `ultimo_mensaje_en`: solo un mensaje real (cliente, Gabi o
# asesor) la mueve; asignar, rotar, liberar o cerrar por Cron no.

import os
from datetime import datetime, timedelta

os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")
os.environ.setdefault("WHATSAPP_PROVIDER", "meta")
os.environ["DEBOUNCE_RESPUESTA_SEGUNDOS"] = "0"

from sqlalchemy import select
from starlette.requests import Request

from agent import main as app_main
from agent import memory as mem
from agent.debounce import gestor_debounce_respuestas
from agent.providers.base import MensajeEntrante


async def _negocio_con_canal(codigo: str, telefono_canal: str):
    negocio = await mem.crear_negocio(f"Negocio {codigo}", codigo)
    canal = await mem.crear_canal_whatsapp(
        nombre=f"Canal {codigo}", phone_number_id=telefono_canal, negocio_id=negocio["id"],
    )
    return negocio, canal


async def _lead_con_conversacion(negocio: dict, canal: dict, telefono: str):
    await mem.actualizar_lead(telefono, negocio_id=negocio["id"], numero_whatsapp_id="x")
    conversation, _ = await mem.resolver_conversation_activa(telefono, negocio["id"], canal["id"])
    return conversation


async def _fijar_ultimo_mensaje(conversation_id: str, hace: timedelta):
    async with mem.async_session() as session:
        fila = await session.get(mem.Conversation, conversation_id)
        fila.ultimo_mensaje_en = datetime.utcnow() - hace
        await session.commit()


async def _ids_en_orden(negocio_id: str, **kwargs) -> list[str]:
    filas, _ = await mem.listar_conversaciones_activas(negocio_id=negocio_id, **kwargs)
    return [f["id"] for f in filas]


async def test_acciones_del_sistema_no_mueven_la_bandeja_pero_un_mensaje_si():
    negocio, canal = await _negocio_con_canal("bj-ord-1", "10000000201")
    vieja = await _lead_con_conversacion(negocio, canal, "51900300001")
    reciente = await _lead_con_conversacion(negocio, canal, "51900300002")
    await _fijar_ultimo_mensaje(vieja.id, timedelta(days=9))
    await _fijar_ultimo_mensaje(reciente.id, timedelta(hours=1))
    assert await _ids_en_orden(negocio["id"]) == [reciente.id, vieja.id]

    # Lo que hacen el reparto automático, la rotación, la liberación y el Cron
    # de cierre sobre el chat VIEJO — ninguno es un mensaje.
    await mem.asignar_asesor_a_lead("51900300001", "asesor1", automatico=True)
    await mem.liberar_asignacion("51900300001", motivo="timeout_inactividad")
    await mem.actualizar_lead("51900300001", resultado="consulta_atc")
    await mem.asignar_asesor_a_lead("51900300001", "asesor1")
    assert await mem.cerrar_lead_definitivamente("51900300001", negocio["id"], autor=None) is True

    # Por defecto (orden por actividad real) el chat viejo SIGUE abajo...
    assert await _ids_en_orden(negocio["id"]) == [reciente.id, vieja.id]
    # ...aunque sí "se tocó": con el criterio anterior habría subido al tope.
    assert await _ids_en_orden(negocio["id"], orden="actualizado") == [vieja.id, reciente.id]

    # Un mensaje real sí lo sube, sin abrir el chat (comportamiento del
    # 2026-09-17 que no debe perderse).
    await mem.guardar_mensaje("51900300001", "user", "Hola de nuevo", negocio_id=negocio["id"])
    assert await _ids_en_orden(negocio["id"]) == [vieja.id, reciente.id]


async def test_la_fila_expone_la_hora_del_ultimo_mensaje_no_la_de_la_ultima_modificacion():
    negocio, canal = await _negocio_con_canal("bj-ord-2", "10000000202")
    conversation = await _lead_con_conversacion(negocio, canal, "51900300003")
    await _fijar_ultimo_mensaje(conversation.id, timedelta(days=9))

    await mem.asignar_asesor_a_lead("51900300003", "asesor1", automatico=True)

    filas, _ = await mem.listar_conversaciones_activas(negocio_id=negocio["id"])
    fila = filas[0]
    ultimo = datetime.fromisoformat(fila["ultimo_mensaje_en"].replace("Z", "+00:00")).replace(tzinfo=None)
    modificado = datetime.fromisoformat(fila["actualizado"].replace("Z", "+00:00")).replace(tzinfo=None)
    assert datetime.utcnow() - ultimo > timedelta(days=8)  # hace 9 días: la hora real
    assert datetime.utcnow() - modificado < timedelta(minutes=5)  # la asignación sí tocó `actualizado`


async def test_mensajes_de_cualquier_rol_mueven_ultimo_mensaje_en():
    negocio, canal = await _negocio_con_canal("bj-ord-3", "10000000203")
    conversation = await _lead_con_conversacion(negocio, canal, "51900300004")
    for rol in ("user", "assistant", "asesor"):
        await _fijar_ultimo_mensaje(conversation.id, timedelta(days=3))
        await mem.guardar_mensaje("51900300004", rol, f"mensaje de {rol}", negocio_id=negocio["id"])
        async with mem.async_session() as session:
            fila = await session.get(mem.Conversation, conversation.id)
            assert datetime.utcnow() - fila.ultimo_mensaje_en < timedelta(minutes=1), rol


async def test_el_evento_de_cierre_de_un_vendido_no_promete_que_gabi_retoma():
    negocio, canal = await _negocio_con_canal("bj-ord-4", "10000000204")
    await _lead_con_conversacion(negocio, canal, "51900300005")
    await mem.asignar_asesor_a_lead("51900300005", "asesor1")
    await mem.actualizar_lead("51900300005", resultado="vendido")
    assert await mem.cerrar_lead_definitivamente("51900300005", negocio["id"], autor=None) is True

    eventos = await mem.listar_eventos_lead("51900300005")
    cierre = next(e for e in eventos if e["tipo"] == "cerrado_definitivamente_automatico")
    assert "postventa" in cierre["descripcion"]
    assert "Gabi retomará" not in cierre["descripcion"]


async def test_el_evento_de_cierre_de_otro_resultado_sigue_diciendo_que_gabi_retoma():
    negocio, canal = await _negocio_con_canal("bj-ord-5", "10000000205")
    await _lead_con_conversacion(negocio, canal, "51900300006")
    await mem.asignar_asesor_a_lead("51900300006", "asesor1")
    await mem.actualizar_lead("51900300006", resultado="no_interesado")
    assert await mem.cerrar_lead_definitivamente("51900300006", negocio["id"], autor=None) is True

    eventos = await mem.listar_eventos_lead("51900300006")
    cierre = next(e for e in eventos if e["tipo"] == "cerrado_definitivamente_automatico")
    assert "Gabi retomará" in cierre["descripcion"]


# ── main.py: un vendido con cierre a medias nunca se le entrega a Gabi ────

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


async def test_webhook_no_libera_a_un_vendido_cuyo_cierre_quedo_a_medias(monkeypatch):
    """El cierre marcó el Lead pero NO la Conversation (el espejo es get-only
    y puede no aplicarse): DR-4 no abre una Conversation nueva, el ruteo a
    postventa no corre y el lead sigue 'vendido' con cierre. Antes ese caso
    llegaba a `liberar_asignacion` y Gabi retomaba a un cliente vendido."""
    telefono = "51900300007"
    negocio, canal = await _negocio_con_canal("bj-ord-6", "10000000206")
    await _lead_con_conversacion(negocio, canal, telefono)
    await mem.asignar_asesor_a_lead(telefono, "asesor1")
    await mem.actualizar_lead(telefono, resultado="vendido")
    async with mem.async_session() as session:
        lead = await session.get(mem.Lead, telefono)
        lead.cerrado_definitivamente_en = datetime.utcnow()  # solo el Lead, no la Conversation
        await session.commit()

    canal_dict = {
        "id": canal["id"], "negocio_id": negocio["id"], "unidad_id": None,
        "phone_number_id": canal["phone_number_id"], "modo": "produccion",
    }
    mensaje = MensajeEntrante(
        telefono=telefono, texto="¿Cuándo viene el técnico?", mensaje_id="wamid.bj-ord-6",
        es_propio=False, tipo="text", numero_whatsapp_id=canal["phone_number_id"],
    )
    proveedor = _ProveedorFalso(mensaje, canal_dict)
    monkeypatch.setattr(app_main, "proveedor", proveedor)

    async def no_debe_llamarse(*args, **kwargs):
        raise AssertionError("Gabi no debe responderle a un cliente vendido")
    monkeypatch.setattr(app_main.servicio_inteligencia, "generar_respuesta", no_debe_llamarse)

    await app_main.webhook_handler(_request())
    await gestor_debounce_respuestas.esperar_pendientes()

    assert proveedor.enviados == []
    lead = await mem.obtener_lead(telefono, negocio_id=negocio["id"])
    assert lead["asesor_asignado"] == "asesor1"  # NO se liberó
    async with mem.async_session() as session:
        mensajes = (await session.execute(
            select(mem.Mensaje).where(mem.Mensaje.telefono == telefono, mem.Mensaje.role == "user")
        )).scalars().all()
    assert [m.content for m in mensajes] == ["¿Cuándo viene el técnico?"]  # el asesor sí lo ve
