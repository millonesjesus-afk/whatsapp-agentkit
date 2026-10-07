# tests/test_cierre_cortesia.py — Q3 (2026-10-07): un mensaje de cierre de
# cortesía ("ok", "oh ya ok", "gracias") de un cliente cuyo caso ya está CERRADO
# DEFINITIVAMENTE no abre un ciclo nuevo (DR-4), no despierta a Gabi y no avisa a
# nadie. Caso real: Mercy 51939567302 — la supervisora cerró como "no interesado"
# y 28 s después la clienta contestó "Oh ya ok": se abrió una Conversation nueva,
# se borró el resultado, se liberó la asignación y Gabi respondió largo.
# Reacciones y echo de coexistencia tampoco abren ciclo. Adjuntos, referral y
# botones SIGUEN reabriendo. Todo filtro falla hacia "reabrir" (comportamiento de siempre).

import os
from datetime import datetime, timedelta

os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")
os.environ.setdefault("WHATSAPP_PROVIDER", "meta")
os.environ["DEBOUNCE_RESPUESTA_SEGUNDOS"] = "0"

import pytest
from sqlalchemy import select
from starlette.requests import Request

from agent import main as app_main
from agent import memory as mem
from agent.debounce import gestor_debounce_respuestas
from agent.providers.base import MensajeEntrante


# ── es_cierre_cortesia: función pura ─────────────────────────────────────

@pytest.mark.parametrize("texto", [
    "ok", "Oh ya ok", "gracias", "ok gracias", "listo", "👍", "graciass", "Muchas gracias por todo",
    "okk", "ok pe", "🙏", "Gracias!", "ok 👍", "Perfecto, gracias", "Muchas gracias 🙏🏽", "vale", "Entendido",
    "Gracias, quedo atento", "buen dia, gracias", "genial", "❤️", "Okey gracias",
])
def test_es_cierre_cortesia_positivos(texto):
    assert mem.es_cierre_cortesia(texto) is True


@pytest.mark.parametrize("texto", [
    "dale", "ok, ¿y la fecha?", "ok mañana", "gracias, ya compré", "no gracias", "sí", "si", "claro",
    "ok te llamo a las 5", "", None, "   ", "entonces ok", "te aviso", "ok\ngracias", "gracias https://x.pe",
    "gracias 2", "ok?", "¿gracias", "Muchas gracias por toda la atención que me brindaron el día de hoy",
    "buen dia", "muchas", "mil", "hola", "no", "Reaccionó con 👍",
])
def test_es_cierre_cortesia_negativos(texto):
    assert mem.es_cierre_cortesia(texto) is False


def test_nivel_a_es_solo_gratitud_o_emoji_y_nivel_b_lleva_acuse():
    assert mem.nivel_cierre_cortesia("gracias") == "A"
    assert mem.nivel_cierre_cortesia("🙏") == "A"
    assert mem.nivel_cierre_cortesia("Muchas gracias") == "A"
    assert mem.nivel_cierre_cortesia("ok") == "B"
    assert mem.nivel_cierre_cortesia("ok gracias") == "B"
    assert mem.nivel_cierre_cortesia("Oh ya ok") == "B"
    assert mem.nivel_cierre_cortesia("dale") is None


def test_es_probable_cierre_no_se_modifico():
    # La etiqueta de Inicio sigue como estaba: falla en "Oh ya ok" y da True en "dale".
    assert mem.es_probable_cierre("Oh ya ok") is False
    assert mem.es_probable_cierre("dale") is True


@pytest.mark.parametrize("saliente, deja_pendiente", [
    ("Perfecto, quedo atento a cualquier consulta.", False),
    ("¿Te llamamos hoy?", True),
    ("Te llamo mañana a las 10", True),
    ("Nos vemos el viernes", True),
    ("Quedamos a las 5 pm", True),
    ("Envíame tu DNI por favor", True),
    ("Pásame una foto del recibo", True),
    ("Confirma por este medio", True),
    ("Listo, ya quedó registrado tu pedido.", False),
])
def test_filtro_de_contexto_del_ultimo_saliente(saliente, deja_pendiente):
    assert mem.saliente_deja_algo_pendiente(saliente) is deja_pendiente


def test_pregunta_solo_cuenta_en_los_ultimos_160_caracteres():
    largo = "¿Cómo estás? " + "x" * 300 + " saludos."
    assert mem.saliente_deja_algo_pendiente(largo) is False
    assert mem.saliente_deja_algo_pendiente("x" * 300 + " ¿te parece?") is True


def test_el_tipo_de_evento_nuevo_cabe_incluso_en_30():
    assert len("mensaje_de_cierre_sin_reabrir") <= 30


# ── Escenario ────────────────────────────────────────────────────────────

SALIENTE_OK = "Perfecto, quedo atento a cualquier duda que tengas."


async def _caso_cerrado(
    codigo: str, telefono: str, *, saliente: str | None = SALIENTE_OK, rol_saliente: str = "asesor",
    resultado: str = "no_interesado", cierre: str = "manual", asesor: str = "rvilchez",
):
    """Un caso con asesor, un intercambio cliente→asesor y cierre definitivo (manual o por Cron)."""
    negocio = await mem.crear_negocio(f"Negocio {codigo}", codigo)
    canal = await mem.crear_canal_whatsapp(
        nombre=f"Canal {codigo}", phone_number_id=f"4095000{codigo[-2:]}", negocio_id=negocio["id"],
    )
    await mem.actualizar_lead(telefono, negocio_id=negocio["id"], numero_whatsapp_id="x")
    conversation, _ = await mem.resolver_conversation_activa(telefono, negocio["id"], canal["id"])
    await mem.asignar_asesor_a_lead(telefono, asesor)
    await mem.actualizar_lead(telefono, campos_explicitos=("resultado",), resultado=resultado)
    await mem.guardar_mensaje(telefono, "user", "Hola, me interesa", negocio_id=negocio["id"])
    if saliente is not None:
        await mem.guardar_mensaje(telefono, rol_saliente, saliente, negocio_id=negocio["id"])
    if cierre == "cron":
        async with mem.async_session() as session:
            for m in (await session.execute(select(mem.Mensaje).where(mem.Mensaje.telefono == telefono))).scalars().all():
                m.timestamp = datetime.utcnow() - timedelta(days=9)
            await session.commit()
        assert telefono in await mem.cerrar_leads_definitivamente_inactivos(dias=7)
    else:
        assert await mem.cerrar_lead_definitivamente(telefono, negocio["id"], "angie") is True
    canal_dict = {
        "id": canal["id"], "negocio_id": negocio["id"], "unidad_id": None,
        "phone_number_id": canal["phone_number_id"], "modo": "produccion",
    }
    return negocio, canal, canal_dict, conversation


async def _evaluar(telefono, negocio, texto, **kw):
    return await mem.evaluar_cierre_cortesia(telefono, negocio["id"], texto, kw.pop("tipo", "texto"), **kw)


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
    def __init__(self, mensajes, canal):
        self._mensajes, self._canal = list(mensajes), canal
        self.enviados: list[str] = []

    async def verificar_firma(self, request, cuerpo):
        return True

    async def parsear_webhook(self, request):
        return list(self._mensajes)

    async def resolver_canal(self, numero_whatsapp_id, negocio_id=None):
        return self._canal

    async def marcar_leido_y_escribiendo(self, mensaje_id, canal=None):
        return True

    async def enviar_mensaje(self, telefono, mensaje, canal=None, mensaje_id_citado=None):
        self.enviados.append(mensaje)
        return True, "wamid.OK"


class _Gabi:
    def __init__(self):
        self.llamadas = 0


def _preparar_webhook(monkeypatch, canal_dict, canal, mensajes):
    proveedor = _ProveedorFalso(mensajes, canal_dict)
    monkeypatch.setattr(app_main, "proveedor", proveedor)
    gabi = _Gabi()

    async def respuesta_de_gabi(*args, **kwargs):
        gabi.llamadas += 1
        return "¡Hola! Te cuento todo sobre nuestras promociones...", False, None, None

    async def sin_datos(*args, **kwargs):
        return {}
    monkeypatch.setattr(app_main.servicio_inteligencia, "generar_respuesta", respuesta_de_gabi)
    monkeypatch.setattr(app_main.servicio_inteligencia, "extraer_datos_lead", sin_datos)
    return proveedor, gabi


def _msg(telefono, canal, texto, wamid, **kw):
    return MensajeEntrante(
        telefono=telefono, texto=texto, mensaje_id=wamid, es_propio=False, tipo=kw.pop("tipo", "text"),
        numero_whatsapp_id=canal["phone_number_id"], **kw,
    )


async def _correr(proveedor, mensajes):
    proveedor._mensajes = list(mensajes)
    await app_main.webhook_handler(_request())
    await gestor_debounce_respuestas.esperar_pendientes()


async def _conversaciones(telefono: str) -> list:
    async with mem.async_session() as session:
        return (await session.execute(
            select(mem.Conversation).join(mem.Contact, mem.Contact.id == mem.Conversation.contact_id)
            .where(mem.Contact.telefono == telefono).order_by(mem.Conversation.creado.asc())
        )).scalars().all()


async def _mensajes(telefono: str, role: str | None = None) -> list:
    async with mem.async_session() as session:
        q = select(mem.Mensaje).where(mem.Mensaje.telefono == telefono).order_by(mem.Mensaje.id.asc())
        if role:
            q = q.where(mem.Mensaje.role == role)
        return (await session.execute(q)).scalars().all()


async def _eventos(telefono: str, tipo: str) -> list[dict]:
    return [e for e in await mem.listar_eventos_lead(telefono) if e["tipo"] == tipo]


# ── Webhook: el caso real de Mercy ────────────────────────────────────────

@pytest.mark.parametrize("cierre", ["manual", "cron"])
async def test_webhook_ok_tras_cierre_no_reabre_no_despierta_a_gabi_ni_toca_la_asignacion(monkeypatch, cierre):
    telefono = f"519395673{'01' if cierre == 'manual' else '02'}"
    negocio, canal, canal_dict, conv = await _caso_cerrado(f"g-cc-a{cierre[0]}", telefono, cierre=cierre)
    proveedor, gabi = _preparar_webhook(monkeypatch, canal_dict, canal, [])

    await _correr(proveedor, [_msg(telefono, canal, "Oh ya ok", f"wamid.cc-ok-{cierre}")])

    convs = await _conversaciones(telefono)
    assert [c.id for c in convs] == [conv.id] and convs[0].estado == "activa"  # una sola, la misma
    assert await _eventos(telefono, "reabierto_por_cliente") == []
    assert gabi.llamadas == 0 and proveedor.enviados == []
    assert await _mensajes(telefono, "assistant") == []
    lead = await mem.obtener_lead(telefono, negocio_id=negocio["id"])
    assert lead["asesor_asignado"] == "rvilchez"
    assert lead["resultado"] == "no_interesado"
    assert lead["cerrado_definitivamente_en"] is not None  # el cierre sigue vigente
    eventos = await _eventos(telefono, "mensaje_de_cierre_sin_reabrir")
    assert len(eventos) == 1
    assert eventos[0]["conversation_id"] == conv.id
    p = eventos[0]["payload"]
    assert p["texto"] == "Oh ya ok" and p["numero_absorbido"] == 1 and p["cierre_en"] and p["ultimo_saliente_id"]
    assert p["mensaje_id"]
    # El mensaje quedó en la conversación cerrada
    guardado = [m for m in await _mensajes(telefono, "user") if m.content == "Oh ya ok"]
    assert len(guardado) == 1 and guardado[0].conversation_id == conv.id


async def test_webhook_el_cierre_de_cortesia_no_marca_no_visto(monkeypatch):
    telefono = "51939567303"
    negocio, canal, canal_dict, conv = await _caso_cerrado("g-cc-nv", telefono)
    async with mem.async_session() as session:
        c = await session.get(mem.Conversation, conv.id)
        c.visto_asesor = True
        lead = await session.get(mem.Lead, telefono)
        lead.visto_asesor = True
        await session.commit()
    proveedor, gabi = _preparar_webhook(monkeypatch, canal_dict, canal, [])

    await _correr(proveedor, [_msg(telefono, canal, "gracias", "wamid.cc-nv")])

    async with mem.async_session() as session:
        assert (await session.get(mem.Lead, telefono)).visto_asesor is True
        assert (await session.get(mem.Conversation, conv.id)).visto_asesor is True


async def test_webhook_pregunta_real_tras_cierre_reabre_como_hoy(monkeypatch):
    telefono = "51939567304"
    negocio, canal, canal_dict, conv = await _caso_cerrado("g-cc-b", telefono)
    proveedor, gabi = _preparar_webhook(monkeypatch, canal_dict, canal, [])

    await _correr(proveedor, [_msg(telefono, canal, "¿Cuándo me instalan?", "wamid.cc-q")])

    convs = await _conversaciones(telefono)
    assert len(convs) == 2 and convs[0].estado == "cerrada" and convs[1].estado == "activa"
    assert len(await _eventos(telefono, "reabierto_por_cliente")) == 1
    assert await _eventos(telefono, "mensaje_de_cierre_sin_reabrir") == []
    assert gabi.llamadas == 1  # Gabi retomó, como siempre
    lead = await mem.obtener_lead(telefono, negocio_id=negocio["id"])
    assert lead["asesor_asignado"] is None and lead["resultado"] is None


async def test_webhook_ok_y_luego_mensaje_real_el_segundo_reabre(monkeypatch):
    telefono = "51939567305"
    negocio, canal, canal_dict, conv = await _caso_cerrado("g-cc-c", telefono)
    proveedor, gabi = _preparar_webhook(monkeypatch, canal_dict, canal, [])

    await _correr(proveedor, [_msg(telefono, canal, "ok", "wamid.cc-c1")])
    assert len(await _conversaciones(telefono)) == 1
    await _correr(proveedor, [_msg(telefono, canal, "Quiero contratar el servicio", "wamid.cc-c2")])

    convs = await _conversaciones(telefono)
    assert len(convs) == 2 and convs[0].id == conv.id and convs[0].estado == "cerrada"
    # El "ok" quedó en la conversación vieja; el mensaje real, en la nueva
    ok = [m for m in await _mensajes(telefono, "user") if m.content == "ok"]
    real = [m for m in await _mensajes(telefono, "user") if m.content == "Quiero contratar el servicio"]
    assert ok[0].conversation_id == conv.id and real[0].conversation_id == convs[1].id
    assert len(await _eventos(telefono, "reabierto_por_cliente")) == 1


async def test_webhook_el_sexto_mensaje_de_cierre_reabre(monkeypatch):
    telefono = "51939567306"
    negocio, canal, canal_dict, conv = await _caso_cerrado("g-cc-d", telefono)
    proveedor, gabi = _preparar_webhook(monkeypatch, canal_dict, canal, [])

    for i in range(mem.TOPE_CIERRES_DE_CORTESIA):
        await _correr(proveedor, [_msg(telefono, canal, "gracias", f"wamid.cc-d{i}")])
    assert len(await _conversaciones(telefono)) == 1
    assert len(await _eventos(telefono, "mensaje_de_cierre_sin_reabrir")) == 5

    await _correr(proveedor, [_msg(telefono, canal, "gracias", "wamid.cc-d-sexto")])

    convs = await _conversaciones(telefono)
    assert len(convs) == 2 and convs[0].estado == "cerrada"
    assert len(await _eventos(telefono, "reabierto_por_cliente")) == 1


async def test_webhook_reintento_del_mismo_wamid_deja_un_solo_evento(monkeypatch):
    telefono = "51939567307"
    negocio, canal, canal_dict, conv = await _caso_cerrado("g-cc-e", telefono)
    proveedor, gabi = _preparar_webhook(monkeypatch, canal_dict, canal, [])
    mensaje = _msg(telefono, canal, "ok", "wamid.cc-e")

    await _correr(proveedor, [mensaje])
    await _correr(proveedor, [mensaje])  # Meta reentrega el mismo wamid

    assert len(await _eventos(telefono, "mensaje_de_cierre_sin_reabrir")) == 1
    assert len([m for m in await _mensajes(telefono, "user") if m.content == "ok"]) == 1
    assert len(await _conversaciones(telefono)) == 1


async def test_webhook_vendido_con_cierre_y_gracias_no_crea_postventa(monkeypatch):
    telefono = "51939567308"
    negocio, canal, canal_dict, conv = await _caso_cerrado(
        "g-cc-f", telefono, resultado="vendido", asesor="sabarca", saliente="Listo, tu instalación quedó coordinada.",
    )
    proveedor, gabi = _preparar_webhook(monkeypatch, canal_dict, canal, [])

    await _correr(proveedor, [_msg(telefono, canal, "gracias", "wamid.cc-f1")])

    assert await _eventos(telefono, "asignado_automatico_postventa") == []
    assert len(await _conversaciones(telefono)) == 1
    lead = await mem.obtener_lead(telefono, negocio_id=negocio["id"])
    assert lead["resultado"] == "vendido" and lead["asesor_asignado"] == "sabarca"
    assert lead["cerrado_definitivamente_en"] is not None
    assert gabi.llamadas == 0

    await _correr(proveedor, [_msg(telefono, canal, "¿Cuándo me instalan?", "wamid.cc-f2")])

    assert len(await _eventos(telefono, "asignado_automatico_postventa")) == 1  # como hoy
    lead = await mem.obtener_lead(telefono, negocio_id=negocio["id"])
    assert lead["resultado"] == "postventa" and lead["asesor_asignado"] == "sabarca"
    assert gabi.llamadas == 0


@pytest.mark.parametrize("kw", [
    {"referral": {"source_url": "https://fb.me/ad", "source_type": "ad", "source_id": "1"}},
    {"interactivo_id": "btn_ok"},
])
async def test_webhook_referral_o_boton_reabren(monkeypatch, kw):
    telefono = "51939567309" if "referral" in kw else "51939567310"
    negocio, canal, canal_dict, conv = await _caso_cerrado(f"g-cc-g{telefono[-1]}", telefono)
    proveedor, gabi = _preparar_webhook(monkeypatch, canal_dict, canal, [])

    await _correr(proveedor, [_msg(telefono, canal, "ok", f"wamid.cc-g{telefono[-1]}", **kw)])

    assert len(await _conversaciones(telefono)) == 2
    assert len(await _eventos(telefono, "reabierto_por_cliente")) == 1


async def test_webhook_media_tras_cierre_sigue_reabriendo(monkeypatch):
    telefono = "51939567311"
    negocio, canal, canal_dict, conv = await _caso_cerrado("g-cc-h", telefono)
    proveedor, gabi = _preparar_webhook(monkeypatch, canal_dict, canal, [])

    async def media_falsa(msg, canal_):
        return None
    monkeypatch.setattr(app_main, "_guardar_media_entrante", media_falsa)

    await _correr(proveedor, [MensajeEntrante(
        telefono=telefono, texto="", mensaje_id="wamid.cc-h", es_propio=False, tipo="audio",
        numero_whatsapp_id=canal["phone_number_id"], media={"media_id": "m1", "mime_type": "audio/ogg"},
    )])

    assert len(await _conversaciones(telefono)) == 2
    assert await _eventos(telefono, "mensaje_de_cierre_sin_reabrir") == []


# ── Webhook: reacciones y echo ─────────────────────────────────────────────

async def test_webhook_reaccion_tras_cierre_no_abre_ciclo(monkeypatch):
    telefono = "51939567312"
    negocio, canal, canal_dict, conv = await _caso_cerrado("g-cc-i", telefono)
    proveedor, gabi = _preparar_webhook(monkeypatch, canal_dict, canal, [])

    await _correr(proveedor, [_msg(telefono, canal, "Reaccionó con 👍", "wamid.cc-i", tipo="reaction")])

    convs = await _conversaciones(telefono)
    assert len(convs) == 1 and convs[0].estado == "activa"
    assert await _eventos(telefono, "reabierto_por_cliente") == []
    assert gabi.llamadas == 0 and proveedor.enviados == []
    guardada = [m for m in await _mensajes(telefono, "user") if m.content == "Reaccionó con 👍"]
    assert len(guardada) == 1 and guardada[0].conversation_id == conv.id
    lead = await mem.obtener_lead(telefono, negocio_id=negocio["id"])
    assert lead["asesor_asignado"] == "rvilchez" and lead["cerrado_definitivamente_en"] is not None


async def test_webhook_reaccion_sin_cierre_se_comporta_como_siempre(monkeypatch):
    telefono = "51939567313"
    negocio = await mem.crear_negocio("Negocio g-cc-j", "g-cc-j")
    canal = await mem.crear_canal_whatsapp(nombre="Canal g-cc-j", phone_number_id="409500099", negocio_id=negocio["id"])
    await mem.actualizar_lead(telefono, negocio_id=negocio["id"], numero_whatsapp_id="x")
    await mem.resolver_conversation_activa(telefono, negocio["id"], canal["id"])
    canal_dict = {"id": canal["id"], "negocio_id": negocio["id"], "unidad_id": None,
                  "phone_number_id": canal["phone_number_id"], "modo": "produccion"}
    proveedor, gabi = _preparar_webhook(monkeypatch, canal_dict, canal, [])

    await _correr(proveedor, [_msg(telefono, canal, "Reaccionó con 👍", "wamid.cc-j", tipo="reaction")])

    assert len(await _conversaciones(telefono)) == 1
    assert gabi.llamadas == 0
    assert await _eventos(telefono, "mensaje_de_cierre_sin_reabrir") == []


async def test_webhook_echo_tras_cierre_no_se_marca_como_reapertura(monkeypatch):
    telefono = "51939567314"
    negocio, canal, canal_dict, conv = await _caso_cerrado("g-cc-k", telefono)
    proveedor, gabi = _preparar_webhook(monkeypatch, canal_dict, canal, [])

    await _correr(proveedor, [_msg(telefono, canal, "Hola Mercy, te escribo desde mi celular", "wamid.cc-k", tipo_evento="echo")])

    convs = await _conversaciones(telefono)
    assert len(convs) == 1 and convs[0].estado == "activa"
    assert await _eventos(telefono, "reabierto_por_cliente") == []
    assert await _eventos(telefono, "desasignado_automatico") == []
    eco = [m for m in await _mensajes(telefono, "assistant") if m.via_app]
    assert len(eco) == 1 and eco[0].conversation_id == conv.id
    lead = await mem.obtener_lead(telefono, negocio_id=negocio["id"])
    assert lead["asesor_asignado"] == "rvilchez" and lead["resultado"] == "no_interesado"
    assert gabi.llamadas == 0

    # Cuenta como contacto humano posterior al cierre: un "ok" ya no se absorbe (C4)
    assert await _evaluar(telefono, negocio, "ok") is None


async def test_webhook_echo_sin_cierre_sigue_su_camino_de_siempre(monkeypatch):
    telefono = "51939567315"
    negocio = await mem.crear_negocio("Negocio g-cc-l", "g-cc-l")
    canal = await mem.crear_canal_whatsapp(nombre="Canal g-cc-l", phone_number_id="409500098", negocio_id=negocio["id"])
    await mem.actualizar_lead(telefono, negocio_id=negocio["id"], numero_whatsapp_id="x")
    await mem.resolver_conversation_activa(telefono, negocio["id"], canal["id"])
    canal_dict = {"id": canal["id"], "negocio_id": negocio["id"], "unidad_id": None,
                  "phone_number_id": canal["phone_number_id"], "modo": "produccion"}
    proveedor, gabi = _preparar_webhook(monkeypatch, canal_dict, canal, [])

    await _correr(proveedor, [_msg(telefono, canal, "Hola desde mi celular", "wamid.cc-l", tipo_evento="echo")])

    assert len([m for m in await _mensajes(telefono, "assistant") if m.via_app]) == 1
    lead = await mem.obtener_lead(telefono, negocio_id=negocio["id"])
    assert lead["pausado_manual"] is True  # sin asesor: se pausa a Gabi, igual que antes


# ── evaluar_cierre_cortesia: los filtros de contexto ───────────────────────

async def test_contexto_saliente_con_pregunta_reabre_en_nivel_b_pero_no_en_nivel_a():
    negocio, canal, _, _ = await _caso_cerrado("g-cc-m", "51939567320", saliente="¿Te parece si coordinamos?")
    assert await _evaluar("51939567320", negocio, "ok") is None
    assert await _evaluar("51939567320", negocio, "Oh ya ok") is None
    # Nivel A (solo gratitud) exige únicamente C1 y C4
    assert (await _evaluar("51939567320", negocio, "gracias"))["nivel"] == "A"


@pytest.mark.parametrize("saliente", [
    "Te llamo mañana temprano", "Quedamos a las 5 pm entonces", "Envíame tu DNI cuando puedas", "Nos vemos el lunes",
])
async def test_contexto_saliente_con_compromiso_reabre_en_nivel_b(saliente):
    negocio, *_ = await _caso_cerrado("g-cc-n", "51939567321", saliente=saliente)
    assert await _evaluar("51939567321", negocio, "ok") is None
    assert (await _evaluar("51939567321", negocio, "muchas gracias")) is not None


async def test_contexto_sin_ningun_saliente_reabre_incluso_el_nivel_a():
    negocio, *_ = await _caso_cerrado("g-cc-o", "51939567322", saliente=None)
    assert await _evaluar("51939567322", negocio, "gracias") is None
    assert await _evaluar("51939567322", negocio, "ok") is None


async def test_contexto_saliente_fallido_no_cuenta_como_saliente():
    negocio, *_ = await _caso_cerrado("g-cc-p", "51939567323", saliente=None)
    await mem.guardar_mensaje("51939567323", "asesor", "Mensaje que no salió", negocio_id=negocio["id"], estado_envio="fallido")
    assert await _evaluar("51939567323", negocio, "gracias") is None


async def test_contexto_saliente_posterior_al_cierre_reabre():
    # C4: un humano escribió DESPUÉS de cerrar → el caso volvió a tener movimiento
    negocio, *_ = await _caso_cerrado("g-cc-q", "51939567324")
    assert await _evaluar("51939567324", negocio, "ok") is not None
    await mem.guardar_mensaje("51939567324", "asesor", "Una cosa más", negocio_id=negocio["id"])
    assert await _evaluar("51939567324", negocio, "ok") is None
    assert await _evaluar("51939567324", negocio, "gracias") is None


async def test_contexto_citado_reemplaza_al_ultimo_saliente():
    negocio, *_ = await _caso_cerrado("g-cc-r", "51939567325", saliente="Perfecto, quedo atento.")
    # El saliente citado tiene una petición pendiente: el "ok" ya es una respuesta real
    # (se guarda ANTES del cierre en el tiempo no hace falta: el filtro mira el citado)
    async with mem.async_session() as session:
        citado = mem.Mensaje(
            telefono="51939567325", negocio_id=negocio["id"], role="asesor", content="Envíame tu DNI por favor",
            timestamp=datetime.utcnow() - timedelta(days=1), mensaje_id_meta="wamid.citado",
        )
        conv = (await session.execute(
            select(mem.Mensaje.conversation_id).where(mem.Mensaje.telefono == "51939567325").limit(1)
        )).scalar_one()
        citado.conversation_id = conv
        session.add(citado)
        await session.commit()
    assert await _evaluar("51939567325", negocio, "ok") is not None  # sin cita: el último saliente está bien
    assert await _evaluar("51939567325", negocio, "ok", contexto_id="wamid.citado") is None
    assert await _evaluar("51939567325", negocio, "ok", contexto_id="wamid.desconocido") is not None


async def test_sin_cierre_definitivo_no_se_absorbe_nada():
    negocio = await mem.crear_negocio("Negocio g-cc-s", "g-cc-s")
    canal = await mem.crear_canal_whatsapp(nombre="Canal g-cc-s", phone_number_id="409500097", negocio_id=negocio["id"])
    await mem.actualizar_lead("51939567326", negocio_id=negocio["id"], numero_whatsapp_id="x")
    await mem.resolver_conversation_activa("51939567326", negocio["id"], canal["id"])
    await mem.guardar_mensaje("51939567326", "asesor", SALIENTE_OK, negocio_id=negocio["id"])
    for tipo in ("texto", "reaccion", "echo"):
        assert await _evaluar("51939567326", negocio, "gracias", tipo=tipo) is None
    assert await mem.evaluar_cierre_cortesia("51939567999", negocio["id"], "gracias") is None  # teléfono sin contacto


async def test_cierre_sobrante_de_un_ciclo_anterior_no_cuenta():
    negocio, canal, _, conv = await _caso_cerrado("g-cc-t", "51939567327")
    # Un cierre del Lead que quedó atrás: la Conversation activa es POSTERIOR a ese cierre
    async with mem.async_session() as session:
        c = await session.get(mem.Conversation, conv.id)
        c.cerrado_definitivamente_en = None
        lead = await session.get(mem.Lead, "51939567327")
        lead.cerrado_definitivamente_en = datetime.utcnow() - timedelta(days=30)
        c.creado = datetime.utcnow() - timedelta(days=1)
        await session.commit()
    assert await _evaluar("51939567327", negocio, "gracias") is None


async def test_el_cierre_del_lead_sirve_si_la_conversacion_no_tiene_espejo():
    negocio, canal, _, conv = await _caso_cerrado("g-cc-u", "51939567328")
    async with mem.async_session() as session:
        c = await session.get(mem.Conversation, conv.id)
        c.cerrado_definitivamente_en = None  # el espejo no se aplicó
        await session.commit()
    assert await _evaluar("51939567328", negocio, "gracias") is not None


async def test_evaluar_es_de_solo_lectura():
    negocio, canal, _, conv = await _caso_cerrado("g-cc-v", "51939567329")
    antes = len(await _mensajes("51939567329"))
    await _evaluar("51939567329", negocio, "ok")
    assert len(await _mensajes("51939567329")) == antes
    assert await _eventos("51939567329", "mensaje_de_cierre_sin_reabrir") == []


async def test_fail_open_si_evaluar_falla_se_sigue_por_el_camino_actual(monkeypatch):
    telefono = "51939567330"
    negocio, canal, canal_dict, conv = await _caso_cerrado("g-cc-w", telefono)
    proveedor, gabi = _preparar_webhook(monkeypatch, canal_dict, canal, [])

    async def rota(*a, **k):
        raise RuntimeError("falla simulada")
    monkeypatch.setattr(app_main, "evaluar_cierre_cortesia", rota)

    await _correr(proveedor, [_msg(telefono, canal, "ok", "wamid.cc-w")])

    assert len(await _conversaciones(telefono)) == 2  # como hoy: DR-4 reabre
    assert len(await _eventos(telefono, "reabierto_por_cliente")) == 1


# ── Lecturas: Inicio, Bandeja, ventana de Meta, mensajes perdidos ─────────

async def test_clientes_esperando_ignora_el_cierre_de_cortesia(monkeypatch):
    telefono = "51939567331"
    negocio, canal, canal_dict, conv = await _caso_cerrado("g-cc-x", telefono)
    # Antes del "ok" el caso cerrado no espera a nadie
    assert [c for c in await mem.listar_clientes_esperando(negocio["id"]) if c["telefono"] == telefono] == []
    proveedor, gabi = _preparar_webhook(monkeypatch, canal_dict, canal, [])

    await _correr(proveedor, [_msg(telefono, canal, "Oh ya ok", "wamid.cc-x")])

    assert [c for c in await mem.listar_clientes_esperando(negocio["id"]) if c["telefono"] == telefono] == []


async def test_clientes_esperando_si_incluye_un_mensaje_real_posterior_al_cierre():
    telefono = "51939567332"
    negocio, canal, canal_dict, conv = await _caso_cerrado("g-cc-y", telefono)
    # Datos viejos (sin marca): un mensaje real tras el cierre, con el caso todavía en la conversación
    await mem.guardar_mensaje(telefono, "user", "Ya mandé mi DNI, ¿lo recibiste?", negocio_id=negocio["id"])
    esperando = [c for c in await mem.listar_clientes_esperando(negocio["id"]) if c["telefono"] == telefono]
    assert len(esperando) == 1


async def test_clientes_esperando_funciona_con_datos_viejos_sin_marca():
    telefono = "51939567333"
    negocio, canal, canal_dict, conv = await _caso_cerrado("g-cc-z", telefono)
    # Un "ok" guardado tras el cierre sin pasar por el webhook (ni evento ni marca)
    await mem.guardar_mensaje(telefono, "user", "ok gracias", negocio_id=negocio["id"])
    assert [c for c in await mem.listar_clientes_esperando(negocio["id"]) if c["telefono"] == telefono] == []


async def test_bandeja_excluye_los_cierres_de_cortesia_de_los_pendientes_y_expone_el_resumen():
    telefono = "51939567334"
    negocio, canal, canal_dict, conv = await _caso_cerrado("g-cc-aa", telefono)
    filas, _ = await mem.listar_conversaciones_activas(negocio["id"])
    fila = next(f for f in filas if f["telefono"] == telefono)
    assert fila["mensajes_pendientes"] == 0 and fila["mensajes_tras_cierre"] == 0 and fila["respondio_tras_cierre_en"] is None

    await mem.guardar_mensaje(telefono, "user", "Oh ya ok", negocio_id=negocio["id"])
    await mem.guardar_mensaje(telefono, "user", "Reaccionó con 👍", negocio_id=negocio["id"])
    filas, _ = await mem.listar_conversaciones_activas(negocio["id"])
    fila = next(f for f in filas if f["telefono"] == telefono)
    assert fila["mensajes_pendientes"] == 0  # nada que contestar
    assert fila["mensajes_tras_cierre"] == 2
    assert fila["respondio_tras_cierre_en"] is not None

    # Un mensaje real SÍ cuenta como pendiente (datos viejos: no pasó por el webhook)
    await mem.guardar_mensaje(telefono, "user", "Ya mandé mi DNI, ¿lo recibiste?", negocio_id=negocio["id"])
    filas, _ = await mem.listar_conversaciones_activas(negocio["id"])
    fila = next(f for f in filas if f["telefono"] == telefono)
    assert fila["mensajes_pendientes"] == 1 and fila["mensajes_tras_cierre"] == 3


async def test_bandeja_sin_cierre_cuenta_los_pendientes_como_siempre():
    negocio = await mem.crear_negocio("Negocio g-cc-ab", "g-cc-ab")
    canal = await mem.crear_canal_whatsapp(nombre="Canal g-cc-ab", phone_number_id="409500096", negocio_id=negocio["id"])
    await mem.actualizar_lead("51939567335", negocio_id=negocio["id"], numero_whatsapp_id="x")
    await mem.resolver_conversation_activa("51939567335", negocio["id"], canal["id"])
    await mem.guardar_mensaje("51939567335", "user", "ok", negocio_id=negocio["id"])
    filas, _ = await mem.listar_conversaciones_activas(negocio["id"])
    fila = next(f for f in filas if f["telefono"] == "51939567335")
    assert fila["mensajes_pendientes"] == 1 and fila["mensajes_tras_cierre"] == 0


async def test_la_ventana_de_meta_cuenta_el_cierre_de_cortesia(monkeypatch):
    telefono = "51939567336"
    negocio, canal, canal_dict, conv = await _caso_cerrado("g-cc-ac", telefono, cierre="cron")  # mensajes de hace 9 días
    antes = await mem.obtener_estado_ventana(telefono, negocio["id"])
    assert antes["ventana_24h_abierta"] is False
    proveedor, gabi = _preparar_webhook(monkeypatch, canal_dict, canal, [])

    await _correr(proveedor, [_msg(telefono, canal, "gracias", "wamid.cc-ac")])

    assert len(await _conversaciones(telefono)) == 1  # se absorbió
    despues = await mem.obtener_estado_ventana(telefono, negocio["id"])
    assert despues["ventana_24h_abierta"] is True
    assert await mem.obtener_timestamp_ultimo_mensaje_usuario(telefono) is not None
    # y la reacción NO la abre (regla vigente)
    telefono2 = "51939567337"
    negocio2, canal2, canal_dict2, _ = await _caso_cerrado("g-cc-ad", telefono2, cierre="cron")
    proveedor2, _ = _preparar_webhook(monkeypatch, canal_dict2, canal2, [])
    await _correr(proveedor2, [_msg(telefono2, canal2, "Reaccionó con 👍", "wamid.cc-ad", tipo="reaction")])
    assert (await mem.obtener_estado_ventana(telefono2, negocio2["id"]))["ventana_24h_abierta"] is False


async def test_el_barrido_de_mensajes_perdidos_no_recupera_el_cierre_de_cortesia(monkeypatch):
    telefono = "51939567338"
    negocio, canal, canal_dict, conv = await _caso_cerrado("g-cc-ae", telefono)
    proveedor, gabi = _preparar_webhook(monkeypatch, canal_dict, canal, [])
    await _correr(proveedor, [_msg(telefono, canal, "ok", "wamid.cc-ae")])
    assert len(await _conversaciones(telefono)) == 1

    # El "ok" es el último mensaje y nadie le respondió: el barrido NO debe tratarlo como un mensaje perdido
    # (el lead conserva su asesor y su cierre definitivo).
    filas = await mem.listar_mensajes_sin_respuesta_de_gabi(min_minutos=0)
    assert all(f["telefono"] != telefono for f in filas)
