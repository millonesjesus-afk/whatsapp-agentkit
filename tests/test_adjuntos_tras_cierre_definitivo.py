# tests/test_adjuntos_tras_cierre_definitivo.py — decisión del dueño 2026-10-08: con un CIERRE
# DEFINITIVO vigente, un ADJUNTO o AUDIO del cliente (imagen, audio, documento, sticker, video, tipos
# no soportados) reabre el ciclo por DR-4 y deja el estado COHERENTE igual que un mensaje de texto:
# asesor liberado (evento desasignado_automatico), cierre limpio, Gabi activa y el adjunto guardado en
# la Conversation NUEVA con su aviso de contenido no legible. Antes la rama de media retornaba antes de
# `liberar_asignacion`: quedaba una Conversation nueva sin asesor mientras el Lead conservaba el asesor
# y el cierre, con Gabi pausada, hasta que llegara un texto. "vendido" va por posventa (sin liberar);
# los adjuntos jamás se absorben como cierre de cortesía.

import os
from datetime import datetime, timedelta

os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")
os.environ.setdefault("WHATSAPP_PROVIDER", "meta")
os.environ["DEBOUNCE_RESPUESTA_SEGUNDOS"] = "0"

import pytest
from sqlalchemy import select
from starlette.requests import Request

from agent import circuito_ia, envios, main as app_main, memory as mem, politica_envios
from agent.debounce import gestor_debounce_respuestas
from agent.providers.base import MensajeEntrante

MEDIA_POR_TIPO = {
    "image": {"media_id": "M-img", "mime_type": "image/jpeg", "filename": "", "caption": ""},
    "audio": {"media_id": "M-aud", "mime_type": "audio/ogg", "filename": "", "caption": ""},
    "document": {"media_id": "M-doc", "mime_type": "application/pdf", "filename": "recibo.pdf", "caption": ""},
    "sticker": {"media_id": "M-stk", "mime_type": "image/webp", "filename": "", "caption": ""},
    "video": {"media_id": "M-vid", "mime_type": "video/mp4", "filename": "", "caption": ""},
}
TIPOS_CON_ARCHIVO = list(MEDIA_POR_TIPO)
FRASE_AVISO = {"audio": "escuchar audios", "image": "Recibí tu foto", "sticker": "fotos, videos ni stickers",
               "video": "fotos, videos ni stickers", "document": "Recibí tu documento", "unknown": "ese tipo de mensaje"}
# Foto y documento (2026-10-26): Gabi acusa recibo y deriva el caso a un asesor, en vez de pedir que lo escriba.
TIPOS_QUE_DERIVAN = ("image", "document")


@pytest.fixture(autouse=True)
def _aislamiento(monkeypatch):
    circuito_ia.reiniciar_memoria()
    politica_envios.limpiar_cache()
    monkeypatch.setattr(circuito_ia, "sondear_en_segundo_plano", lambda: None)
    yield
    circuito_ia.reiniciar_memoria()


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

    async def descargar_media(self, media_id, canal=None):
        return (b"contenido-de-prueba", self._mensaje.media["mime_type"]) if self._mensaje.media else None

    async def enviar_mensaje(self, telefono, mensaje, canal=None, mensaje_id_citado=None):
        self.enviados.append(mensaje)
        return True, f"wamid.OK{len(self.enviados)}"


async def _escenario(codigo: str, telefono: str, resultado: str = "consulta_atc", asesor: str = "asesor1", cierre: str = "manual"):
    """Caso con asesor y resultado, CERRADO definitivamente: `cierre` = "manual" (botón de la Ficha) o
    "cron" (cerrar_leads_definitivamente_inactivos / cerrar_ventas_sin_seguimiento)."""
    negocio = await mem.crear_negocio(f"Negocio {codigo}", codigo)
    canal_db = await mem.crear_canal_whatsapp(
        nombre=f"Canal {codigo}", phone_number_id=f"4098{int(codigo[-3:]):06d}", negocio_id=negocio["id"],
    )
    canal = {"id": canal_db["id"], "negocio_id": negocio["id"], "unidad_id": None,
             "phone_number_id": canal_db["phone_number_id"], "modo": "produccion"}
    await mem.actualizar_lead(telefono, negocio_id=negocio["id"], numero_whatsapp_id="x")
    conv_vieja, _ = await mem.resolver_conversation_activa(telefono, negocio["id"], canal["id"])
    await mem.asignar_asesor_a_lead(telefono, asesor)
    await mem.actualizar_lead(telefono, campos_explicitos=("resultado",), resultado=resultado)
    if cierre == "manual":
        assert await mem.cerrar_lead_definitivamente(telefono, negocio["id"], "admin1") is True
    else:
        await mem.guardar_mensaje(telefono, "user", "hola", negocio_id=negocio["id"])
        async with mem.async_session() as session:
            viejo = (await session.execute(
                select(mem.Mensaje).where(mem.Mensaje.telefono == telefono, mem.Mensaje.role == "user")
            )).scalars().first()
            viejo.timestamp = datetime.utcnow() - timedelta(days=8)
            await session.commit()
        cerrados = (
            await mem.cerrar_ventas_sin_seguimiento(dias=5) if resultado == "vendido"
            else await mem.cerrar_leads_definitivamente_inactivos(dias=7)
        )
        assert telefono in cerrados
    lead = await mem.obtener_lead(telefono, negocio_id=negocio["id"])
    assert lead["cerrado_definitivamente_en"] is not None and lead["asesor_asignado"] == asesor
    return negocio, canal, conv_vieja


def _armar_mensaje(monkeypatch, tmp_path, canal: dict, telefono: str, tipo: str, wamid: str):
    con_archivo = tipo in MEDIA_POR_TIPO
    mensaje = MensajeEntrante(
        telefono=telefono, texto="", mensaje_id=wamid, es_propio=False, tipo=tipo,
        numero_whatsapp_id=canal["phone_number_id"], media=dict(MEDIA_POR_TIPO[tipo]) if con_archivo else None,
    )
    proveedor = _ProveedorFalso(mensaje, canal)
    monkeypatch.setattr(app_main, "proveedor", proveedor)
    monkeypatch.setattr(app_main, "_guardar_archivo_en_disco", lambda nombre, contenido: str(tmp_path / "adjunto.bin"))
    return proveedor


async def _eventos(telefono: str, tipo: str) -> list[dict]:
    return [e for e in await mem.listar_eventos_lead(telefono) if e["tipo"] == tipo]


async def _conversaciones(negocio_id: str, telefono: str) -> list:
    async with mem.async_session() as session:
        contact = (await session.execute(
            select(mem.Contact).where(mem.Contact.negocio_id == negocio_id, mem.Contact.telefono == telefono)
        )).scalars().first()
        return (await session.execute(
            select(mem.Conversation).where(mem.Conversation.contact_id == contact.id).order_by(mem.Conversation.creado)
        )).scalars().all()


async def _mensajes(negocio_id: str, telefono: str, role: str) -> list:
    async with mem.async_session() as session:
        return (await session.execute(
            select(mem.Mensaje).where(
                mem.Mensaje.negocio_id == negocio_id, mem.Mensaje.telefono == telefono, mem.Mensaje.role == role,
                mem.Mensaje.content != "hola",  # el mensaje viejo que arma el cierre por Cron
            ).order_by(mem.Mensaje.id)
        )).scalars().all()


async def _verificar_estado_coherente(negocio: dict, telefono: str, conv_vieja, tipo: str, proveedor, esperar_archivo: bool):
    """El MISMO estado final que deja un mensaje de texto tras un cierre definitivo."""
    conversaciones = await _conversaciones(negocio["id"], telefono)
    assert len(conversaciones) == 2 and conversaciones[0].id == conv_vieja.id
    vieja, nueva = conversaciones
    assert vieja.estado == "cerrada" and nueva.estado == "activa"
    # Conversation nueva sin pausa ni cierre; el Lead coincide (ya no hay inconsistencia). Sin asesor, salvo foto/documento,
    # que derivan el caso (puede quedar asignado automáticamente).
    assert nueva.pausado_manual is False and nueva.cerrado_definitivamente_en is None
    lead = await mem.obtener_lead(telefono, negocio_id=negocio["id"])
    assert lead["pausado_manual"] is False
    if tipo in TIPOS_QUE_DERIVAN:
        assert lead["paso_flujo"] == "derivado_asesor"
    else:
        assert nueva.asesor_asignado_id is None and lead["asesor_asignado"] is None
    assert lead["cerrado_definitivamente_en"] is None and lead["resultado"] is None
    # Eventos: reapertura (DR-4) y liberación, una sola vez cada uno
    assert len(await _eventos(telefono, "reabierto_por_cliente")) == 1
    [liberado] = await _eventos(telefono, "desasignado_automatico")
    assert liberado["payload"]["motivo"] == "cierre_definitivo" and liberado["payload"]["anterior"] == "asesor1"
    # El adjunto vive en la Conversation NUEVA (con su archivo) y el cliente recibió el aviso
    [guardado] = await _mensajes(negocio["id"], telefono, "user")
    assert guardado.conversation_id == nueva.id
    assert guardado.content == f"[{tipo}]"
    if esperar_archivo:
        assert guardado.archivo_id is not None
    assert len(proveedor.enviados) == 1 and FRASE_AVISO[tipo] in proveedor.enviados[0]
    [respuesta] = await _mensajes(negocio["id"], telefono, "assistant")
    assert respuesta.conversation_id == nueva.id and respuesta.content == proveedor.enviados[0]
    # La ventana de 24 h de Meta cuenta el adjunto como mensaje normal del cliente
    ultimo = await mem.obtener_timestamp_ultimo_mensaje_usuario(telefono)
    assert ultimo == guardado.timestamp
    estado = await mem.obtener_estado_ventana(telefono, negocio["id"], con_fep=False)
    assert estado["ventana_24h_abierta"] is True and estado["puede_texto_libre"] is True


@pytest.mark.parametrize("cierre", ["manual", "cron"])
@pytest.mark.parametrize("tipo", TIPOS_CON_ARCHIVO)
async def test_adjunto_tras_cierre_definitivo_deja_el_mismo_estado_que_un_texto(monkeypatch, tmp_path, tipo, cierre):
    telefono = f"519071{TIPOS_CON_ARCHIVO.index(tipo)}{'0' if cierre == 'manual' else '1'}001"
    negocio, canal, conv_vieja = await _escenario(
        f"g-adj-{TIPOS_CON_ARCHIVO.index(tipo)}{'0' if cierre == 'manual' else '1'}", telefono, cierre=cierre,
    )
    proveedor = _armar_mensaje(monkeypatch, tmp_path, canal, telefono, tipo, f"wamid.adj-{tipo}-{cierre}")

    await app_main.webhook_handler(_request())
    await gestor_debounce_respuestas.esperar_pendientes()

    await _verificar_estado_coherente(negocio, telefono, conv_vieja, tipo, proveedor, esperar_archivo=True)


async def test_tipo_no_soportado_tras_cierre_definitivo_tambien_queda_coherente(monkeypatch, tmp_path):
    telefono = "51907200001"
    negocio, canal, conv_vieja = await _escenario("g-adj-201", telefono)
    proveedor = _armar_mensaje(monkeypatch, tmp_path, canal, telefono, "unknown", "wamid.adj-unknown")

    await app_main.webhook_handler(_request())

    await _verificar_estado_coherente(negocio, telefono, conv_vieja, "unknown", proveedor, esperar_archivo=False)


async def test_el_texto_deja_el_mismo_estado_final_que_el_adjunto(monkeypatch, tmp_path):
    """Control: el estado tras el texto es el que el adjunto debe igualar (liberado, Gabi activa)."""
    telefono = "51907200002"
    negocio, canal, _ = await _escenario("g-adj-202", telefono)
    proveedor = _armar_mensaje(monkeypatch, tmp_path, canal, telefono, "image", "wamid.adj-ctrl")
    proveedor._mensaje = MensajeEntrante(
        telefono=telefono, texto="Hola de nuevo", mensaje_id="wamid.adj-ctrl", es_propio=False, tipo="text",
        numero_whatsapp_id=canal["phone_number_id"],
    )

    async def respuesta_de_gabi(*args, **kwargs):
        return "¡Hola!", False, None, None

    async def sin_datos(*args, **kwargs):
        return {}
    monkeypatch.setattr(app_main.servicio_inteligencia, "generar_respuesta", respuesta_de_gabi)
    monkeypatch.setattr(app_main.servicio_inteligencia, "extraer_datos_lead", sin_datos)

    await app_main.webhook_handler(_request())
    await gestor_debounce_respuestas.esperar_pendientes()

    lead = await mem.obtener_lead(telefono, negocio_id=negocio["id"])
    assert lead["asesor_asignado"] is None and lead["cerrado_definitivamente_en"] is None and lead["resultado"] is None
    assert len(await _eventos(telefono, "reabierto_por_cliente")) == 1
    assert len(await _eventos(telefono, "desasignado_automatico")) == 1


@pytest.mark.parametrize("cierre", ["manual", "cron"])
async def test_vendido_cerrado_y_adjunto_va_por_posventa_sin_liberar(monkeypatch, tmp_path, cierre):
    telefono = f"519073{'0' if cierre == 'manual' else '1'}0001"
    negocio, canal, _ = await _escenario(
        f"g-adj-30{'0' if cierre == 'manual' else '1'}", telefono, resultado="vendido", asesor="sabarca", cierre=cierre,
    )
    proveedor = _armar_mensaje(monkeypatch, tmp_path, canal, telefono, "image", f"wamid.adj-vend-{cierre}")

    await app_main.webhook_handler(_request())
    await gestor_debounce_respuestas.esperar_pendientes()

    lead = await mem.obtener_lead(telefono, negocio_id=negocio["id"])
    assert lead["resultado"] == "postventa" and lead["asesor_asignado"] == "sabarca"
    assert lead["cerrado_definitivamente_en"] is None
    assert len(await _eventos(telefono, "asignado_automatico_postventa")) == 1
    assert await _eventos(telefono, "desasignado_automatico") == []
    assert await _eventos(telefono, "reabierto_por_cliente") == []
    # El asesor lo ve, Gabi no responde nada
    assert proveedor.enviados == [] and await _mensajes(negocio["id"], telefono, "assistant") == []
    [guardado] = await _mensajes(negocio["id"], telefono, "user")
    assert guardado.archivo_id is not None
    assert lead["visto_asesor"] is False


async def test_sin_cierre_definitivo_el_adjunto_con_asesor_se_guarda_sin_gabi_y_sin_cambios(monkeypatch, tmp_path):
    telefono = "51907400001"
    negocio, canal, _ = await _escenario("g-adj-401", telefono)
    # Se deshace el cierre: el caso sigue abierto con su asesor
    async with mem.async_session() as session:
        lead = await session.get(mem.Lead, telefono)
        lead.cerrado_definitivamente_en = None
        conv = (await _conversaciones(negocio["id"], telefono))[-1]
        conv_db = await session.get(mem.Conversation, conv.id)
        conv_db.cerrado_definitivamente_en = None
        await session.commit()
    proveedor = _armar_mensaje(monkeypatch, tmp_path, canal, telefono, "audio", "wamid.adj-abierto")

    await app_main.webhook_handler(_request())

    lead = await mem.obtener_lead(telefono, negocio_id=negocio["id"])
    assert lead["asesor_asignado"] == "asesor1" and lead["resultado"] == "consulta_atc" and lead["visto_asesor"] is False
    assert len(await _conversaciones(negocio["id"], telefono)) == 1
    assert await _eventos(telefono, "desasignado_automatico") == [] and await _eventos(telefono, "reabierto_por_cliente") == []
    assert proveedor.enviados == [] and await _mensajes(negocio["id"], telefono, "assistant") == []
    [guardado] = await _mensajes(negocio["id"], telefono, "user")
    assert guardado.archivo_id is not None


async def test_reintento_del_mismo_wamid_no_duplica_nada(monkeypatch, tmp_path):
    telefono = "51907500001"
    negocio, canal, conv_vieja = await _escenario("g-adj-501", telefono)
    proveedor = _armar_mensaje(monkeypatch, tmp_path, canal, telefono, "image", "wamid.adj-reintento")

    await app_main.webhook_handler(_request())
    await app_main.webhook_handler(_request())  # Meta reintenta el mismo mensaje
    await app_main.webhook_handler(_request())

    await _verificar_estado_coherente(negocio, telefono, conv_vieja, "image", proveedor, esperar_archivo=True)


async def test_circuito_abierto_responde_el_mensaje_sin_ia_y_deriva(monkeypatch, tmp_path):
    telefono = "51907600001"
    negocio, canal, conv_vieja = await _escenario("g-adj-602", telefono)
    for dia in range(7):
        await mem.guardar_horario_atencion(negocio["id"], dia, True, "00:00", "23:59")
    await mem.crear_usuario("ase_a", "pw12345", "Ase A", "asesor", negocio["id"])
    await circuito_ia.abrir("credito")
    proveedor = _armar_mensaje(monkeypatch, tmp_path, canal, telefono, "audio", "wamid.adj-sinia")

    await app_main.webhook_handler(_request())

    # Se liberó el caso cerrado, el audio quedó guardado en el ciclo nuevo y el cliente recibió el
    # mensaje del modo sin IA (no el "no puedo escuchar audios", que prometería algo que nadie atiende).
    assert len(proveedor.enviados) == 1 and "escuchar audios" not in proveedor.enviados[0]
    assert len(await _eventos(telefono, "reabierto_por_cliente")) == 1
    assert len(await _eventos(telefono, "desasignado_automatico")) == 1
    [guardado] = await _mensajes(negocio["id"], telefono, "user")
    assert guardado.archivo_id is not None
    nueva = (await _conversaciones(negocio["id"], telefono))[-1]
    assert guardado.conversation_id == nueva.id
    lead = await mem.obtener_lead(telefono, negocio_id=negocio["id"])
    assert lead["cerrado_definitivamente_en"] is None and lead["resultado"] is None


@pytest.mark.parametrize("falla", ["liberar", "releer"])
async def test_un_error_al_liberar_nunca_impide_guardar_el_adjunto_ni_avisar(monkeypatch, tmp_path, falla):
    telefono = f"519077{'0' if falla == 'liberar' else '1'}0001"
    negocio, canal, _ = await _escenario(f"g-adj-70{'0' if falla == 'liberar' else '1'}", telefono)
    proveedor = _armar_mensaje(monkeypatch, tmp_path, canal, telefono, "image", f"wamid.adj-falla-{falla}")
    original_obtener_lead = app_main.obtener_lead
    llamadas = {"liberada": False}

    async def liberar_roto(*args, **kwargs):
        raise RuntimeError("fallo simulado al liberar")

    if falla == "liberar":
        monkeypatch.setattr(app_main, "liberar_asignacion", liberar_roto)
    else:
        original_liberar = app_main.liberar_asignacion

        async def liberar_y_marcar(*args, **kwargs):
            await original_liberar(*args, **kwargs)
            llamadas["liberada"] = True

        async def releer_roto(*args, **kwargs):
            if llamadas["liberada"]:
                raise RuntimeError("fallo simulado al releer")
            return await original_obtener_lead(*args, **kwargs)

        monkeypatch.setattr(app_main, "liberar_asignacion", liberar_y_marcar)
        monkeypatch.setattr(app_main, "obtener_lead", releer_roto)

    await app_main.webhook_handler(_request())

    # El adjunto se guardó con su archivo SIEMPRE
    [guardado] = await _mensajes(negocio["id"], telefono, "user")
    assert guardado.archivo_id is not None
    if falla == "liberar":
        # Sin liberar: queda como "hay un humano" (sin respuesta automática, visible para el asesor)
        assert proveedor.enviados == []
        lead = await mem.obtener_lead(telefono, negocio_id=negocio["id"])
        assert lead["asesor_asignado"] == "asesor1" and lead["visto_asesor"] is False
    else:
        # Se liberó de verdad aunque la relectura falló: el cliente sí recibe el aviso (foto: acuse de recibo y derivación)
        assert len(proveedor.enviados) == 1 and "Recibí tu foto" in proveedor.enviados[0]
        monkeypatch.setattr(app_main, "obtener_lead", original_obtener_lead)
        lead = await mem.obtener_lead(telefono, negocio_id=negocio["id"])
        assert lead["cerrado_definitivamente_en"] is None and lead["paso_flujo"] == "derivado_asesor"
