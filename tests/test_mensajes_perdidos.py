# tests/test_mensajes_perdidos.py — 2026-10-05, mensajes del cliente que se perdían.
#
# Dos huecos reales:
#  (a) la marca de idempotencia (`mensajes_procesados`) se ponía ANTES de
#      procesar: si algo fallaba antes de guardar el mensaje, el webhook
#      devolvía 500, Meta reintentaba y el reintento se descartaba como "ya
#      procesado" — el mensaje del cliente desaparecía. Además un fallo en un
#      mensaje del payload dejaba sin procesar a los siguientes.
#  (b) la respuesta de Gabi corre desacoplada en memoria (debounce): si se
#      pierde después de guardar el mensaje, nadie la reintentaba. El barrido
#      `listar_mensajes_sin_respuesta_de_gabi` + scripts/recuperar_mensajes_
#      sin_respuesta.py lo recupera, con tope de 2 intentos por mensaje.

import importlib.util
import os
from datetime import datetime, timedelta
from pathlib import Path

os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")
os.environ.setdefault("WHATSAPP_PROVIDER", "meta")

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from starlette.requests import Request

from agent import main as app_main
from agent import memory as mem
from agent.providers.base import MensajeEntrante


def _cargar_script():
    ruta = Path(__file__).resolve().parent.parent / "scripts" / "recuperar_mensajes_sin_respuesta.py"
    spec = importlib.util.spec_from_file_location("recuperar_mensajes_sin_respuesta", ruta)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


# ═══════════════════════════════════════════════════════════════════════════
# (a) Idempotencia del webhook
# ═══════════════════════════════════════════════════════════════════════════

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
    def __init__(self, canal: dict):
        self._canal = canal
        self._lote: list[MensajeEntrante] = []
        self.enviados: list[str] = []

    def lote(self, mensajes: list[MensajeEntrante]) -> None:
        self._lote = mensajes

    async def verificar_firma(self, request, cuerpo):
        return True

    async def parsear_webhook(self, request):
        return list(self._lote)

    async def resolver_canal(self, numero_whatsapp_id, negocio_id=None):
        return self._canal

    async def marcar_leido_y_escribiendo(self, mensaje_id, canal=None):
        return True

    async def enviar_mensaje(self, telefono, mensaje, canal=None, mensaje_id_citado=None):
        self.enviados.append(mensaje)
        return True, "wamid.OK"


async def _armar(monkeypatch, codigo: str):
    negocio = await mem.crear_negocio(f"Negocio {codigo}", codigo)
    canal_db = await mem.crear_canal_whatsapp(
        nombre=f"Canal {codigo}", phone_number_id=f"4098{codigo[-6:]}", negocio_id=negocio["id"],
    )
    canal = {
        "id": canal_db["id"], "negocio_id": negocio["id"], "unidad_id": None,
        "phone_number_id": canal_db["phone_number_id"], "modo": "produccion",
    }
    proveedor = _ProveedorFalso(canal)
    monkeypatch.setattr(app_main, "proveedor", proveedor)
    # Ventana más larga que lo que tarda guardar un mensaje (SQLite en disco):
    # con una muy corta, la espera del primero vence antes de que llegue el segundo.
    monkeypatch.setenv("DEBOUNCE_RESPUESTA_SEGUNDOS", "0.6")

    llamadas: list[str] = []

    async def respuesta_de_gabi(mensaje, historial, lead, modo="produccion", negocio_id=None):
        llamadas.append(mensaje)
        return "¡Hola! Cuéntame más", False, None, None

    async def sin_datos(*args, **kwargs):
        return {}

    monkeypatch.setattr(app_main.servicio_inteligencia, "generar_respuesta", respuesta_de_gabi)
    monkeypatch.setattr(app_main.servicio_inteligencia, "extraer_datos_lead", sin_datos)
    return negocio, canal, proveedor, llamadas


def _msg(telefono: str, texto: str, wamid: str, canal: dict) -> MensajeEntrante:
    return MensajeEntrante(
        telefono=telefono, texto=texto, mensaje_id=wamid, es_propio=False, tipo="text",
        numero_whatsapp_id=canal["phone_number_id"],
    )


async def _marcas() -> set[str]:
    async with mem.async_session() as session:
        return set((await session.execute(select(mem.MensajeProcesado.mensaje_id))).scalars().all())


async def _mensajes_usuario(negocio_id: str, telefono: str) -> list[str]:
    async with mem.async_session() as session:
        r = await session.execute(
            select(mem.Mensaje.content).where(
                mem.Mensaje.negocio_id == negocio_id, mem.Mensaje.telefono == telefono, mem.Mensaje.role == "user",
            ).order_by(mem.Mensaje.id)
        )
        return list(r.scalars().all())


def _fallar_al_guardar(monkeypatch, contenidos: set[str]) -> list[str]:
    """Hace que guardar un mensaje del cliente con esos contenidos reviente
    (ANTES de escribir nada) mientras la lista devuelta no se vacíe."""
    fallos: list[str] = list(contenidos)
    original = app_main.servicio_conversacion.guardar_mensaje

    async def guardar(telefono, role, content, *args, **kwargs):
        if role == "user" and content in fallos:
            raise RuntimeError("la base se cayó justo ahora")
        return await original(telefono, role, content, *args, **kwargs)

    monkeypatch.setattr(app_main.servicio_conversacion, "guardar_mensaje", guardar)
    return fallos


async def test_si_falla_antes_de_guardar_se_libera_la_marca_y_el_reintento_de_meta_lo_procesa(monkeypatch):
    telefono = "51907000001"
    negocio, canal, proveedor, llamadas = await _armar(monkeypatch, "g-per-01")
    fallos = _fallar_al_guardar(monkeypatch, {"Hola"})
    proveedor.lote([_msg(telefono, "Hola", "wamid.per01", canal)])

    with pytest.raises(HTTPException) as exc:
        await app_main.webhook_handler(_request())
    assert exc.value.status_code == 500  # Meta va a reintentar
    assert "wamid.per01" not in await _marcas()  # la marca NO queda puesta
    assert await _mensajes_usuario(negocio["id"], telefono) == []

    fallos.clear()  # la base ya responde: llega el reintento de Meta
    assert await app_main.webhook_handler(_request()) == {"status": "ok"}
    await app_main.gestor_debounce_respuestas.esperar_pendientes()

    assert await _mensajes_usuario(negocio["id"], telefono) == ["Hola"]
    assert llamadas == ["Hola"] and proveedor.enviados == ["¡Hola! Cuéntame más"]
    assert "wamid.per01" in await _marcas()


async def test_el_reintento_se_procesa_una_sola_vez(monkeypatch):
    """Tras recuperarse, un TERCER envío del mismo wamid (Meta reentrega) ya es duplicado."""
    telefono = "51907000002"
    negocio, canal, proveedor, llamadas = await _armar(monkeypatch, "g-per-02")
    fallos = _fallar_al_guardar(monkeypatch, {"Hola"})
    proveedor.lote([_msg(telefono, "Hola", "wamid.per02", canal)])
    with pytest.raises(HTTPException):
        await app_main.webhook_handler(_request())
    fallos.clear()

    await app_main.webhook_handler(_request())      # reintento: se procesa
    await app_main.webhook_handler(_request())      # reentrega extra: se descarta
    await app_main.gestor_debounce_respuestas.esperar_pendientes()

    assert await _mensajes_usuario(negocio["id"], telefono) == ["Hola"]
    assert llamadas == ["Hola"] and len(proveedor.enviados) == 1


async def test_si_falla_despues_de_guardar_la_marca_se_conserva_y_no_se_duplica(monkeypatch):
    telefono = "51907000003"
    negocio, canal, proveedor, llamadas = await _armar(monkeypatch, "g-per-03")

    def revienta(*args, **kwargs):
        raise RuntimeError("falló al programar la respuesta")

    with monkeypatch.context() as parche:
        parche.setattr(app_main.gestor_debounce_respuestas, "reprogramar", revienta)
        proveedor.lote([_msg(telefono, "Hola", "wamid.per03", canal)])
        with pytest.raises(HTTPException):
            await app_main.webhook_handler(_request())

    # El mensaje SÍ quedó guardado y su marca se conserva.
    assert await _mensajes_usuario(negocio["id"], telefono) == ["Hola"]
    assert "wamid.per03" in await _marcas()

    # El reintento de Meta se descarta como duplicado: no se guarda otra vez.
    assert await app_main.webhook_handler(_request()) == {"status": "ok"}
    await app_main.gestor_debounce_respuestas.esperar_pendientes()
    assert await _mensajes_usuario(negocio["id"], telefono) == ["Hola"]
    assert llamadas == []  # (lo que faltó —la respuesta— lo recupera el barrido)


async def test_no_duplica_aunque_la_marca_no_exista_si_el_mensaje_ya_estaba_guardado(monkeypatch):
    """Escudo extra: marca perdida/borrada pero el wamid ya está en `mensajes`."""
    telefono = "51907000004"
    negocio, canal, proveedor, llamadas = await _armar(monkeypatch, "g-per-04")
    proveedor.lote([_msg(telefono, "Hola", "wamid.per04", canal)])
    await app_main.webhook_handler(_request())
    await app_main.gestor_debounce_respuestas.esperar_pendientes()
    assert await mem.liberar_marca_mensaje_procesado("wamid.per04") is True  # se pierde la marca

    await app_main.webhook_handler(_request())
    await app_main.gestor_debounce_respuestas.esperar_pendientes()

    assert await _mensajes_usuario(negocio["id"], telefono) == ["Hola"]
    assert llamadas == ["Hola"] and len(proveedor.enviados) == 1


async def test_un_fallo_en_un_mensaje_no_pierde_los_siguientes_del_mismo_payload(monkeypatch):
    telefono = "51907000005"
    negocio, canal, proveedor, llamadas = await _armar(monkeypatch, "g-per-05")
    fallos = _fallar_al_guardar(monkeypatch, {"primero"})
    proveedor.lote([
        _msg(telefono, "primero", "wamid.per05a", canal),
        _msg(telefono, "segundo", "wamid.per05b", canal),
        _msg(telefono, "tercero", "wamid.per05c", canal),
    ])

    with pytest.raises(HTTPException):
        await app_main.webhook_handler(_request())

    # El primero falló antes de guardarse (marca liberada); los otros dos se procesaron.
    assert await _mensajes_usuario(negocio["id"], telefono) == ["segundo", "tercero"]
    assert await _marcas() == {"wamid.per05b", "wamid.per05c"}

    # Reintento de Meta con el mismo payload: solo el primero es nuevo, los otros son duplicados.
    fallos.clear()
    assert await app_main.webhook_handler(_request()) == {"status": "ok"}
    await app_main.gestor_debounce_respuestas.esperar_pendientes()

    assert sorted(await _mensajes_usuario(negocio["id"], telefono)) == ["primero", "segundo", "tercero"]
    assert await _marcas() == {"wamid.per05a", "wamid.per05b", "wamid.per05c"}


async def test_un_payload_sin_fallos_se_procesa_igual_que_antes(monkeypatch):
    telefono = "51907000006"
    negocio, canal, proveedor, llamadas = await _armar(monkeypatch, "g-per-06")
    proveedor.lote([
        _msg(telefono, "Hola", "wamid.per06a", canal), _msg(telefono, "una terma", "wamid.per06b", canal),
    ])

    assert await app_main.webhook_handler(_request()) == {"status": "ok"}
    await app_main.gestor_debounce_respuestas.esperar_pendientes()

    assert await _mensajes_usuario(negocio["id"], telefono) == ["Hola", "una terma"]
    assert llamadas == ["una terma"]  # debounce: una sola llamada con todo acumulado
    assert await _marcas() == {"wamid.per06a", "wamid.per06b"}


async def test_si_el_aviso_al_panel_falla_la_respuesta_de_gabi_igual_se_programa(monkeypatch):
    """El aviso en tiempo real y el "escribiendo..." son cosméticos: no pueden
    dejar al mensaje guardado sin respuesta."""
    telefono = "51907000007"
    negocio, canal, proveedor, llamadas = await _armar(monkeypatch, "g-per-07")

    async def revienta(*args, **kwargs):
        raise RuntimeError("websocket caído")

    monkeypatch.setattr(app_main.gestor_conexiones, "emitir_mensaje_nuevo", revienta)
    monkeypatch.setattr(proveedor, "marcar_leido_y_escribiendo", revienta)
    proveedor.lote([_msg(telefono, "Hola", "wamid.per07", canal)])

    assert await app_main.webhook_handler(_request()) == {"status": "ok"}
    await app_main.gestor_debounce_respuestas.esperar_pendientes()

    assert llamadas == ["Hola"] and proveedor.enviados == ["¡Hola! Cuéntame más"]


# ═══════════════════════════════════════════════════════════════════════════
# (b) Barrido: listar_mensajes_sin_respuesta_de_gabi
# ═══════════════════════════════════════════════════════════════════════════

async def _negocio_con_canal(codigo: str, phone_number_id: str):
    negocio = await mem.crear_negocio(f"Negocio {codigo}", codigo)
    canal = await mem.crear_canal_whatsapp(nombre=f"Canal {codigo}", phone_number_id=phone_number_id, negocio_id=negocio["id"])
    return negocio, canal


async def _lead_gabi(telefono: str, negocio_id: str, canal_id: int):
    """Lead que Gabi atiende sola: sin asesor, sin pausar, conversación activa."""
    await mem.resolver_conversation_activa(telefono, negocio_id, canal_id)
    await mem.actualizar_lead(telefono, nombre="Cliente Test", negocio_id=negocio_id, numero_whatsapp_id="x")


async def _mensaje(telefono: str, negocio_id: str, role: str, hace_min: float, contenido: str = "hola, quiero una terma", **kwargs):
    guardado = await mem.guardar_mensaje(telefono, role, contenido, negocio_id, **kwargs)
    async with mem.async_session() as session:
        m = await session.get(mem.Mensaje, guardado["id"])
        m.timestamp = datetime.utcnow() - timedelta(minutes=hace_min)
        await session.commit()
    return guardado


async def _telefonos_sin_respuesta(**kwargs) -> set[str]:
    return {f["telefono"] for f in await mem.listar_mensajes_sin_respuesta_de_gabi(**kwargs)}


async def test_el_barrido_encuentra_un_mensaje_del_cliente_sin_respuesta():
    negocio, canal = await _negocio_con_canal("g-bar-01", "40300000001")
    telefono = "51908000001"
    await _lead_gabi(telefono, negocio["id"], canal["id"])
    await _mensaje(telefono, negocio["id"], "assistant", hace_min=30)
    ultimo = await _mensaje(telefono, negocio["id"], "user", hace_min=10)

    filas = await mem.listar_mensajes_sin_respuesta_de_gabi()

    assert [f["telefono"] for f in filas] == [telefono]
    assert filas[0]["mensaje_id"] == ultimo["id"] and filas[0]["intentos"] == 0
    assert filas[0]["negocio_id"] == negocio["id"] and filas[0]["numero_whatsapp_id"] == "x"


async def test_el_barrido_ignora_lo_ya_respondido_lo_muy_reciente_y_lo_muy_viejo():
    negocio, canal = await _negocio_con_canal("g-bar-02", "40300000002")
    respondido, reciente, viejo, borde = "51908000011", "51908000012", "51908000013", "51908000014"
    for tel in (respondido, reciente, viejo, borde):
        await _lead_gabi(tel, negocio["id"], canal["id"])
    await _mensaje(respondido, negocio["id"], "user", hace_min=30)
    await _mensaje(respondido, negocio["id"], "assistant", hace_min=29)
    await _mensaje(reciente, negocio["id"], "user", hace_min=1)          # el debounce normal aún puede estar trabajando
    await _mensaje(viejo, negocio["id"], "user", hace_min=21 * 60)       # > 20 h
    await _mensaje(borde, negocio["id"], "user", hace_min=19 * 60)       # dentro de las 20 h

    assert await _telefonos_sin_respuesta() == {borde}
    assert await _telefonos_sin_respuesta(min_minutos=0.5) == {reciente, borde}
    assert await _telefonos_sin_respuesta(max_horas=25) == {viejo, borde}


async def test_el_barrido_nunca_toca_leads_con_asesor_pausados_escalados_ni_cerrados():
    negocio, canal = await _negocio_con_canal("g-bar-03", "40300000003")
    bueno = "51908000020"
    con_asesor, pausado, escalado, cerrado_def = "51908000021", "51908000022", "51908000023", "51908000024"
    cerrados = {r: f"519080001{i:02d}" for i, r in enumerate(
        ["vendido", "agendado", "postventa", "no_interesado", "sin_respuesta", "consulta_atc"])}
    todos = [bueno, con_asesor, pausado, escalado, cerrado_def, *cerrados.values()]
    for tel in todos:
        await _lead_gabi(tel, negocio["id"], canal["id"])
        await _mensaje(tel, negocio["id"], "user", hace_min=10)

    await mem.asignar_asesor_a_lead(con_asesor, "asesor1")
    await mem.pausar_gabi_manual(pausado)
    async with mem.async_session() as session:
        (await session.get(mem.Lead, escalado)).escalado_supervision_en = datetime.utcnow()
        (await session.get(mem.Lead, cerrado_def)).cerrado_definitivamente_en = datetime.utcnow()
        for resultado, tel in cerrados.items():
            (await session.get(mem.Lead, tel)).resultado = resultado
        await session.commit()

    assert await _telefonos_sin_respuesta() == {bueno}


async def test_el_barrido_respeta_tambien_la_conversation_y_la_opportunity():
    """Las dos fuentes cuentan: aunque Lead diga "libre", si la Conversation está
    asignada/pausada o su Opportunity ya está vendida, no se toca."""
    negocio, canal = await _negocio_con_canal("g-bar-04", "40300000004")
    conv_asignada, conv_pausada, opp_vendida, libre = "51908000031", "51908000032", "51908000033", "51908000034"
    for tel in (conv_asignada, conv_pausada, opp_vendida, libre):
        await _lead_gabi(tel, negocio["id"], canal["id"])
        await _mensaje(tel, negocio["id"], "user", hace_min=10)
    async with mem.async_session() as session:
        contacto = lambda tel: mem._obtener_contact(session, negocio["id"], tel)  # noqa: E731
        c1 = await mem._obtener_conversation_activa(session, (await contacto(conv_asignada)).id)
        c1.asesor_asignado_id = "asesor1"
        c2 = await mem._obtener_conversation_activa(session, (await contacto(conv_pausada)).id)
        c2.pausado_manual = True
        c3 = await mem._obtener_conversation_activa(session, (await contacto(opp_vendida)).id)
        (await mem._obtener_opportunity_vigente(session, c3.id)).resultado = "vendido"
        await session.commit()

    assert await _telefonos_sin_respuesta() == {libre}


async def test_una_reaccion_al_final_no_cuenta_como_mensaje_ni_tapa_uno_sin_contestar():
    negocio, canal = await _negocio_con_canal("g-bar-05", "40300000005")
    tapado, respondido_y_reaccion = "51908000041", "51908000042"
    for tel in (tapado, respondido_y_reaccion):
        await _lead_gabi(tel, negocio["id"], canal["id"])
    # Mensaje real sin contestar, y después una reacción: SIGUE pendiente.
    await _mensaje(tapado, negocio["id"], "user", hace_min=20, contenido="¿tienen termas de 5.5 L?")
    await _mensaje(tapado, negocio["id"], "user", hace_min=15, contenido="Reaccionó con 👍")
    # Gabi ya contestó y el cliente solo reaccionó: NO hay nada que recuperar.
    await _mensaje(respondido_y_reaccion, negocio["id"], "user", hace_min=20, contenido="gracias")
    await _mensaje(respondido_y_reaccion, negocio["id"], "assistant", hace_min=19, contenido="¡De nada!")
    await _mensaje(respondido_y_reaccion, negocio["id"], "user", hace_min=15, contenido="Reaccionó con ❤️")

    assert await _telefonos_sin_respuesta() == {tapado}


async def test_un_mensaje_del_asesor_o_de_gabi_al_final_no_es_un_pendiente():
    negocio, canal = await _negocio_con_canal("g-bar-06", "40300000006")
    tel_asesor_ultimo = "51908000051"
    await _lead_gabi(tel_asesor_ultimo, negocio["id"], canal["id"])
    await _mensaje(tel_asesor_ultimo, negocio["id"], "user", hace_min=20)
    await _mensaje(tel_asesor_ultimo, negocio["id"], "asesor", hace_min=15)

    assert await _telefonos_sin_respuesta() == set()


async def test_un_adjunto_sin_texto_no_se_recupera_porque_nunca_paso_por_claude():
    negocio, canal = await _negocio_con_canal("g-bar-07", "40300000007")
    con_placeholder, con_archivo, texto = "51908000061", "51908000062", "51908000063"
    for tel in (con_placeholder, con_archivo, texto):
        await _lead_gabi(tel, negocio["id"], canal["id"])
    await _mensaje(con_placeholder, negocio["id"], "user", hace_min=10, contenido="[audio]")
    archivo = await mem.crear_archivo_adjunto("foto.jpg", "/tmp/foto.jpg", "image/jpeg", 10, "cliente")
    await _mensaje(con_archivo, negocio["id"], "user", hace_min=10, contenido="mira esto", archivo_id=archivo["id"])
    await _mensaje(texto, negocio["id"], "user", hace_min=10)

    assert await _telefonos_sin_respuesta() == {texto}


async def test_el_barrido_filtra_por_negocio_y_aplica_el_limite_del_mas_antiguo_al_mas_reciente():
    neg_a, canal_a = await _negocio_con_canal("g-bar-08a", "40300000008")
    neg_b, canal_b = await _negocio_con_canal("g-bar-08b", "40300000009")
    await _lead_gabi("51908000071", neg_a["id"], canal_a["id"])
    await _lead_gabi("51908000072", neg_a["id"], canal_a["id"])
    await _lead_gabi("51908000073", neg_b["id"], canal_b["id"])
    await _mensaje("51908000071", neg_a["id"], "user", hace_min=10)
    await _mensaje("51908000072", neg_a["id"], "user", hace_min=30)
    await _mensaje("51908000073", neg_b["id"], "user", hace_min=20)

    assert await _telefonos_sin_respuesta(negocio_id=neg_a["id"]) == {"51908000071", "51908000072"}
    ordenados = [f["telefono"] for f in await mem.listar_mensajes_sin_respuesta_de_gabi()]
    assert ordenados == ["51908000072", "51908000073", "51908000071"]  # el que más espera, primero
    assert [f["telefono"] for f in await mem.listar_mensajes_sin_respuesta_de_gabi(limite=1)] == ["51908000072"]


async def test_el_barrido_cuenta_intentos_por_mensaje_y_puede_excluir_los_agotados():
    negocio, canal = await _negocio_con_canal("g-bar-09", "40300000010")
    telefono = "51908000081"
    await _lead_gabi(telefono, negocio["id"], canal["id"])
    primero = await _mensaje(telefono, negocio["id"], "user", hace_min=40, contenido="uno")
    await mem.registrar_evento_lead(telefono, tipo="respuesta_recuperada", descripcion="x", autor=None, payload={"mensaje_id": primero["id"]})
    await mem.registrar_evento_lead(telefono, tipo="respuesta_recuperada", descripcion="x", autor=None, payload={"mensaje_id": primero["id"]})

    (fila,) = await mem.listar_mensajes_sin_respuesta_de_gabi()
    assert fila["intentos"] == 2
    assert await mem.listar_mensajes_sin_respuesta_de_gabi(max_intentos=2) == []

    # Un mensaje NUEVO del cliente es otro mensaje: sus intentos arrancan de cero.
    await _mensaje(telefono, negocio["id"], "user", hace_min=10, contenido="dos")
    (fila,) = await mem.listar_mensajes_sin_respuesta_de_gabi(max_intentos=2)
    assert fila["intentos"] == 0


def test_el_tipo_de_evento_de_recuperacion_cabe_en_la_columna():
    assert mem.TIPO_EVENTO_RESPUESTA_RECUPERADA == "respuesta_recuperada"
    assert len(mem.TIPO_EVENTO_RESPUESTA_RECUPERADA) <= mem.TIPO_EVENTO_LARGO_MAX


# ═══════════════════════════════════════════════════════════════════════════
# (b) Script de recuperación
# ═══════════════════════════════════════════════════════════════════════════

async def _canal_ok(numero_whatsapp_id, negocio_id=None):
    return {"id": 1, "negocio_id": negocio_id, "unidad_id": None, "phone_number_id": numero_whatsapp_id, "modo": "produccion"}


async def _eventos_de_recuperacion(telefono: str) -> list[dict]:
    return [e for e in await mem.listar_eventos_lead(telefono) if e["tipo"] == "respuesta_recuperada"]


async def test_el_script_reintenta_registra_el_evento_y_no_toca_a_los_leads_con_asesor():
    script = _cargar_script()
    negocio, canal = await _negocio_con_canal("g-scr-01", "40400000001")
    libre, con_asesor, vendido = "51909000001", "51909000002", "51909000003"
    ids: dict[str, int] = {}
    for tel in (libre, con_asesor, vendido):
        await _lead_gabi(tel, negocio["id"], canal["id"])
        ids[tel] = (await _mensaje(tel, negocio["id"], "user", hace_min=10))["id"]
    await mem.asignar_asesor_a_lead(con_asesor, "asesor1")
    async with mem.async_session() as session:
        (await session.get(mem.Lead, vendido)).resultado = "vendido"
        await session.commit()

    atendidos: list[str] = []

    async def generar(telefono, canal_):
        atendidos.append(telefono)
        await mem.guardar_mensaje(telefono, "assistant", "¡Hola! Cuéntame más", negocio["id"])

    resumen = await script.recuperar_mensajes_sin_respuesta(generar_respuesta=generar, resolver_canal=_canal_ok)

    assert atendidos == [libre]
    assert resumen["encontrados"] == 1 and resumen["intentados"] == 1 and resumen["ia_caida"] is False
    (evento,) = await _eventos_de_recuperacion(libre)
    assert evento["payload"] == {"mensaje_id": ids[libre]}
    assert await _eventos_de_recuperacion(con_asesor) == [] and await _eventos_de_recuperacion(vendido) == []
    # Ya respondida: la siguiente pasada no encuentra nada.
    assert (await script.recuperar_mensajes_sin_respuesta(generar_respuesta=generar, resolver_canal=_canal_ok))["encontrados"] == 0
    assert atendidos == [libre]


async def test_el_script_hace_como_maximo_dos_intentos_por_mensaje_aunque_siga_sin_respuesta():
    script = _cargar_script()
    negocio, canal = await _negocio_con_canal("g-scr-02", "40400000002")
    telefono = "51909000011"
    await _lead_gabi(telefono, negocio["id"], canal["id"])
    ultimo = await _mensaje(telefono, negocio["id"], "user", hace_min=10)

    intentos: list[str] = []

    async def generar_sin_efecto(tel, canal_):
        intentos.append(tel)  # la respuesta "se pierde" otra vez: el mensaje sigue sin contestar

    for _ in range(4):
        await script.recuperar_mensajes_sin_respuesta(generar_respuesta=generar_sin_efecto, resolver_canal=_canal_ok)

    assert intentos == [telefono, telefono]
    eventos = await _eventos_de_recuperacion(telefono)
    assert [e["payload"] for e in eventos] == [{"mensaje_id": ultimo["id"]}] * 2


async def test_un_intento_que_revienta_tambien_cuenta_y_no_frena_a_los_demas():
    script = _cargar_script()
    negocio, canal = await _negocio_con_canal("g-scr-03", "40400000003")
    malo, bueno = "51909000021", "51909000022"
    await _lead_gabi(malo, negocio["id"], canal["id"])
    await _lead_gabi(bueno, negocio["id"], canal["id"])
    await _mensaje(malo, negocio["id"], "user", hace_min=30)
    await _mensaje(bueno, negocio["id"], "user", hace_min=20)
    atendidos: list[str] = []

    async def generar(tel, canal_):
        atendidos.append(tel)
        if tel == malo:
            raise RuntimeError("falló")
        await mem.guardar_mensaje(tel, "assistant", "ok", negocio["id"])

    resumen = await script.recuperar_mensajes_sin_respuesta(generar_respuesta=generar, resolver_canal=_canal_ok)
    assert atendidos == [malo, bueno] and resumen["con_error"] == 1
    for _ in range(3):
        await script.recuperar_mensajes_sin_respuesta(generar_respuesta=generar, resolver_canal=_canal_ok)
    assert atendidos.count(malo) == 2  # tope de 2 aunque falle siempre


async def test_si_la_ia_esta_caida_el_barrido_se_detiene_en_vez_de_martillar():
    """`_generar_y_enviar_respuesta_ia` no lanza cuando Claude falla: deja la falla
    contada en el lead (fallos_tecnicos). Dos seguidas = IA caída, se corta."""
    script = _cargar_script()
    negocio, canal = await _negocio_con_canal("g-scr-04", "40400000004")
    telefonos = ["51909000031", "51909000032", "51909000033", "51909000034"]
    for i, tel in enumerate(telefonos):
        await _lead_gabi(tel, negocio["id"], canal["id"])
        await _mensaje(tel, negocio["id"], "user", hace_min=40 - i)
    atendidos: list[str] = []

    async def generar_con_ia_caida(tel, canal_):
        atendidos.append(tel)
        await mem.registrar_fallo_tecnico(tel)

    resumen = await script.recuperar_mensajes_sin_respuesta(generar_respuesta=generar_con_ia_caida, resolver_canal=_canal_ok)

    assert atendidos == telefonos[:2]
    assert resumen["ia_caida"] is True and resumen["fallos_ia"] == 2 and resumen["intentados"] == 2


async def test_una_recuperacion_exitosa_reinicia_la_cuenta_de_fallos_de_la_ia():
    script = _cargar_script()
    negocio, canal = await _negocio_con_canal("g-scr-05", "40400000005")
    telefonos = ["51909000041", "51909000042", "51909000043"]
    for i, tel in enumerate(telefonos):
        await _lead_gabi(tel, negocio["id"], canal["id"])
        await _mensaje(tel, negocio["id"], "user", hace_min=40 - i)
    atendidos: list[str] = []

    async def generar(tel, canal_):
        atendidos.append(tel)
        if tel == telefonos[1]:
            await mem.guardar_mensaje(tel, "assistant", "ok", negocio["id"])
            await mem.resetear_fallos_tecnicos(tel)
        else:
            await mem.registrar_fallo_tecnico(tel)

    resumen = await script.recuperar_mensajes_sin_respuesta(generar_respuesta=generar, resolver_canal=_canal_ok)

    assert atendidos == telefonos  # falla, éxito, falla: nunca 2 seguidas
    assert resumen["ia_caida"] is False and resumen["fallos_ia"] == 2


async def test_sin_canal_no_se_intenta_ni_se_registra_nada():
    script = _cargar_script()
    negocio, canal = await _negocio_con_canal("g-scr-06", "40400000006")
    telefono = "51909000051"
    await _lead_gabi(telefono, negocio["id"], canal["id"])
    await _mensaje(telefono, negocio["id"], "user", hace_min=10)
    atendidos: list[str] = []

    async def sin_canal(numero_whatsapp_id, negocio_id=None):
        return None

    async def generar(tel, canal_):
        atendidos.append(tel)

    resumen = await script.recuperar_mensajes_sin_respuesta(generar_respuesta=generar, resolver_canal=sin_canal)

    assert atendidos == [] and resumen["sin_canal"] == 1 and resumen["intentados"] == 0
    assert await _eventos_de_recuperacion(telefono) == []


async def test_el_script_usa_el_mismo_camino_real_que_el_webhook(monkeypatch):
    """Sin inyección, el script llama a `agent.main._generar_y_enviar_respuesta_ia`:
    Gabi responde por el canal, y el mensaje queda guardado."""
    script = _cargar_script()
    negocio, canal = await _negocio_con_canal("g-scr-07", "40400000007")
    telefono = "51909000061"
    await _lead_gabi(telefono, negocio["id"], canal["id"])
    await _mensaje(telefono, negocio["id"], "user", hace_min=10, contenido="quiero una terma")
    canal_dict = {
        "id": canal["id"], "negocio_id": negocio["id"], "unidad_id": None,
        "phone_number_id": canal["phone_number_id"], "modo": "produccion",
    }
    proveedor = _ProveedorFalso(canal_dict)
    monkeypatch.setattr(app_main, "proveedor", proveedor)
    llamadas: list[str] = []

    async def respuesta_de_gabi(mensaje, historial, lead, modo="produccion", negocio_id=None):
        llamadas.append(mensaje)
        return "¡Claro! ¿De cuántos litros?", False, None, None

    async def sin_datos(*args, **kwargs):
        return {}

    monkeypatch.setattr(app_main.servicio_inteligencia, "generar_respuesta", respuesta_de_gabi)
    monkeypatch.setattr(app_main.servicio_inteligencia, "extraer_datos_lead", sin_datos)

    resumen = await script.recuperar_mensajes_sin_respuesta()

    assert resumen["intentados"] == 1 and resumen["ia_caida"] is False
    assert llamadas == ["quiero una terma"] and proveedor.enviados == ["¡Claro! ¿De cuántos litros?"]
    assert await mem.listar_mensajes_sin_respuesta_de_gabi() == []
