# tests/test_llamadas_respuesta_oferta.py — "Para llamar" (2026-10-11): Gabi entiende la PRIMERA respuesta del cliente a la oferta de
# llamada. Clasificador determinista (tabla de frases, falsos positivos), Haiku opcional para lo ambiguo, efectos sobre la tarea
# (acepta / hora / rechaza), compuerta legal, idempotencia, plazo de la oferta, una sola vez por oferta, horario, rechazo posterior
# y el camino real del webhook (confirmación fija sin que Gabi converse encima).

import json
import os
from datetime import datetime, timedelta

os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")
os.environ.setdefault("WHATSAPP_PROVIDER", "meta")
os.environ["DEBOUNCE_RESPUESTA_SEGUNDOS"] = "0"

import pytest
from sqlalchemy import select

from agent import envios
from agent import llamadas as ll
from agent import memory as mem
from tests.test_cierre_cortesia import _correr, _mensajes, _msg, _preparar_webhook
from tests.test_llamadas_flujo import (
    TEL, _activar, _asesores, _cfg, _encender, _eventos, _lead, _negocio, _tareas, _tocar, _usuario,
)

# ── El clasificador (puro) ───────────────────────────────────────────────────────────────────────

ACEPTA = [
    "sí", "Sí!", "si", "sii", "claro", "Claro que sí", "ok", "okey", "dale", "por favor", "Si por favor", "está bien", "esta bien",
    "de acuerdo", "ya pues", "listo", "perfecto", "sí, gracias", "Buenas tardes, sí por favor", "ahora", "ahorita", "ya mismo",
    "cuando puedan", "cuando quieran", "llámame", "si, llamenme", "sí, pueden llamarme",
]


@pytest.mark.parametrize("texto", ACEPTA)
def test_las_frases_de_aceptacion_se_reconocen(texto):
    r = ll.clasificar_respuesta(texto)
    assert r["intencion"] == "acepta" and r["pura"] is True, r


HORAS = [
    ("a las 3", {"hora": (3, 0)}), ("A las 3.", {"hora": (3, 0)}), ("3pm", {"hora": (3, 0), "meridiano": "pm"}),
    ("a las 3 p.m.", {"hora": (3, 0), "meridiano": "pm"}), ("a las 3:30", {"hora": (3, 30)}), ("a las 15:00", {"hora": (15, 0)}),
    ("después de las 5", {"hora": (5, 0), "limite": "despues"}), ("a las 3 de la tarde", {"hora": (3, 0), "franja": "tarde"}),
    ("a las tres", {"hora": (3, 0)}), ("a las 11 y media", {"hora": (11, 30)}), ("a la 1", {"hora": (1, 0)}),
    ("sí, a las 2 de la tarde", {"hora": (2, 0), "franja": "tarde"}), ("mañana", {"dia": 1}), ("hoy", {"dia": 0}),
    ("pasado mañana", {"dia": 2}), ("en la tarde", {"franja": "tarde", "dia": None}), ("en la noche", {"franja": "noche"}),
    ("en la mañana", {"franja": "manana", "dia": None}),            # «en la mañana» es la franja, NO «mañana» (el día)
    ("mañana en la tarde", {"dia": 1, "franja": "tarde"}), ("mañana por la mañana", {"dia": 1, "franja": "manana"}),
    ("mañana a las 10", {"dia": 1, "hora": (10, 0)}), ("mañana temprano", {"dia": 1, "franja": "manana"}),
    ("en 2 horas", {"en_minutos": 120}), ("en media hora", {"en_minutos": 30}), ("a las 3?", {"hora": (3, 0)}), ("¿mañana?", {"dia": 1}),
    ("3", {"hora": (3, 0)}),
]


@pytest.mark.parametrize("texto, esperado", HORAS)
def test_las_horas_y_franjas_se_extraen(texto, esperado):
    r = ll.clasificar_respuesta(texto)
    assert r["intencion"] == "hora", r
    for clave, valor in esperado.items():
        assert r["info"][clave] == valor, (texto, clave, r["info"])


RECHAZA = [
    "no me llamen", "No me llamen por favor", "no quiero llamadas", "Ya no quiero que me llamen", "prefiero por escrito",
    "prefiero por whatsapp", "prefiero por aquí", "mejor por aquí", "no gracias", "No, gracias", "no me interesa", "ya no me interesa",
    "no estoy interesada", "no", "nop", "mejor no", "no llames", "dejen de llamar", "no me contacten por teléfono", "sin llamadas",
]


@pytest.mark.parametrize("texto", RECHAZA)
def test_los_rechazos_se_reconocen(texto):
    r = ll.clasificar_respuesta(texto)
    assert r["intencion"] == "rechaza", r


OTRO = [
    # los falsos positivos que NO pueden contarse como aceptación: el cliente quiere otra cosa y Gabi debe contestarle
    "sí, ¿cuánto cuesta?", "claro, y el precio?", "sí pero antes dime el precio", "ok, y tienen financiamiento", "dale, ¿cómo funciona?",
    "sí, ¿qué incluye la instalación?", "claro que sí, mándame el catálogo", "ok, necesito la terma de 80 litros",
    "dale gracias por la info", "mañana te escribo", "te contesto mañana", "sí, ¿a qué hora llaman?",
    # ni aceptación ni rechazo
    "gracias", "ok gracias", "hola", "👍", "no sé", "no puedo hoy", "ahora no", "tengo una duda", "¿cómo funciona?",
    "sí, llámame al 987654321", "mi otro número es 987 654 321", "escríbeme a juan@correo.com",
    "sí, llámenme y no me escriban",      # contradictorio: que lo vea una persona
    "x" * 300, "sí " * 20,
    "", "   ",
]


@pytest.mark.parametrize("texto", OTRO)
def test_lo_que_no_es_una_respuesta_a_la_oferta_es_otro(texto):
    assert ll.clasificar_respuesta(texto)["intencion"] == "otro", ll.clasificar_respuesta(texto)


def test_solo_lo_que_no_tiene_ningun_patron_es_ambiguo_y_va_a_haiku():
    assert ll.clasificar_respuesta("gracias")["ambiguo"] is True
    assert ll.clasificar_respuesta("pasamos al otro tema")["ambiguo"] is True
    for texto in ("sí, ¿cuánto cuesta?", "no puedo hoy", "mi otro número es 987 654 321", "x" * 300, "mañana te escribo"):
        assert ll.clasificar_respuesta(texto)["ambiguo"] is False, texto


def test_el_rechazo_con_mas_contenido_no_es_pura():
    assert ll.clasificar_respuesta("no me llamen")["pura"] is True
    assert ll.clasificar_respuesta("no me llamen, ¿cuánto cuesta?")["pura"] is False
    assert ll.clasificar_respuesta("no me llamen, ¿cuánto cuesta?")["intencion"] == "rechaza"      # el rechazo se registra igual


def test_la_regex_de_rechazo_reutiliza_los_patrones_de_e4_menos_los_situacionales():
    for frase in ("no me interesa", "ya no me interesa", "no estoy interesado", "no gracias", "no me llames", "dejen de llamar"):
        assert ll.hay_rechazo([frase]) and ll._es_rechazo_de_llamada(ll._plano_respuesta(frase)), frase
    for frase in ("me equivoqué de número", "ya compré", "no soy cliente"):                          # sacan al lead de la lista, no son un «no me llamen»
        assert ll.hay_rechazo([frase]) and not ll._es_rechazo_de_llamada(ll._plano_respuesta(frase)), frase


# ── Resolver el cuándo (puro, con horario fijo) ──────────────────────────────────────────────────

RANGOS = {d: ("09:00", "18:00") for d in range(5)}                  # lunes a viernes 09:00-18:00 (Lima)


def _lima(texto: str) -> datetime:
    return datetime.fromisoformat(texto) + timedelta(hours=5)       # hora de Lima → UTC


def _cuando(texto: str, ahora_lima: str):
    ahora = _lima(ahora_lima)
    r = ll.clasificar_respuesta(texto)
    utc, exacta = ll.resolver_cuando(r["info"] or {"ahora": True}, ahora, RANGOS)
    return (utc - timedelta(hours=5)).strftime("%Y-%m-%dT%H:%M"), exacta, ll.etiqueta_cuando(utc, ahora, exacta)


@pytest.mark.parametrize("texto, ahora_lima, esperado, exacta, etiqueta", [
    ("a las 3", "2026-10-12T10:00", "2026-10-12T15:00", True, "hoy alrededor de las 3 p. m."),          # lunes 10:00
    ("3pm", "2026-10-12T10:00", "2026-10-12T15:00", True, "hoy alrededor de las 3 p. m."),
    ("a las 3:30 pm", "2026-10-12T10:00", "2026-10-12T15:30", True, "hoy alrededor de las 3:30 p. m."),
    ("a la 1", "2026-10-12T10:00", "2026-10-12T13:00", True, "hoy alrededor de la 1 p. m."),
    ("a las 3", "2026-10-12T16:00", "2026-10-13T15:00", True, "mañana alrededor de las 3 p. m."),       # ya pasó hoy → mañana
    ("después de las 5", "2026-10-12T10:00", "2026-10-12T17:00", True, "hoy alrededor de las 5 p. m."),
    ("ahora", "2026-10-12T10:00", "2026-10-12T10:00", False, "en breve"),                                 # abierto: lo antes posible
    ("hoy", "2026-10-12T10:00", "2026-10-12T10:00", False, "en breve"),
    ("ya", "2026-10-12T18:30", "2026-10-13T09:00", False, "mañana a partir de las 9 a. m."),             # cerrado: próxima apertura
    ("ahora", "2026-10-16T18:30", "2026-10-19T09:00", False, "el lunes a partir de las 9 a. m."),        # viernes tarde → lunes
    ("a las 3", "2026-10-12T18:30", "2026-10-13T15:00", True, "mañana alrededor de las 3 p. m."),
    ("a las 8 de la noche", "2026-10-12T10:00", "2026-10-13T09:00", False, "mañana a partir de las 9 a. m."),  # fuera de horario → apertura
    ("mañana", "2026-10-12T10:00", "2026-10-13T09:00", False, "mañana a partir de las 9 a. m."),
    ("mañana", "2026-10-16T10:00", "2026-10-19T09:00", False, "el lunes a partir de las 9 a. m."),       # sábado cerrado → lunes
    ("mañana a las 10", "2026-10-12T10:00", "2026-10-13T10:00", True, "mañana alrededor de las 10 a. m."),
    ("pasado mañana", "2026-10-12T10:00", "2026-10-14T09:00", False, "el miércoles a partir de las 9 a. m."),
    ("en la tarde", "2026-10-12T10:00", "2026-10-12T14:00", False, "hoy a partir de las 2 p. m."),
    ("en la tarde", "2026-10-12T15:00", "2026-10-12T15:00", False, "en breve"),                            # ya estamos en la tarde
    ("en la mañana", "2026-10-12T13:00", "2026-10-13T09:00", False, "mañana a partir de las 9 a. m."),   # la mañana de hoy ya pasó
    ("en la noche", "2026-10-12T10:00", "2026-10-13T09:00", False, "mañana a partir de las 9 a. m."),    # la noche cae fuera del horario
    ("mañana temprano", "2026-10-12T10:00", "2026-10-13T09:00", False, "mañana a partir de las 9 a. m."),
    ("en 2 horas", "2026-10-12T10:00", "2026-10-12T12:00", False, "hoy a partir de las 12 p. m."),
    ("antes de las 5", "2026-10-12T10:00", "2026-10-12T10:00", False, "en breve"),
    ("antes de las 5", "2026-10-12T17:30", "2026-10-13T09:00", False, "mañana a partir de las 9 a. m."), # ya no da tiempo hoy
])
def test_resolver_cuando(texto, ahora_lima, esperado, exacta, etiqueta):
    assert _cuando(texto, ahora_lima) == (esperado, exacta, etiqueta)


def test_los_textos_de_confirmacion():
    assert ll.texto_confirma_llamada("Ana María", "hoy alrededor de las 3 p. m.") == \
        "Perfecto, Ana. Un asesor te llamará hoy alrededor de las 3 p. m. Si cambias de idea, avísame por aquí."
    assert ll.texto_confirma_llamada(None, "en breve") == "Perfecto. Un asesor te llamará en breve. Si cambias de idea, avísame por aquí."
    assert ll.texto_confirma_llamada("desconocido", "en breve").startswith("Perfecto. ")
    assert ll.texto_confirma_no_llamar("Ana") == "Listo, Ana, no te llamaremos. Seguimos por aquí por WhatsApp si lo necesitas."
    assert ll.texto_confirma_no_llamar(None) == "Listo, no te llamaremos. Seguimos por aquí por WhatsApp si lo necesitas."


def test_los_eventos_nuevos_son_visibles_y_caben_en_la_columna():
    for tipo in (mem.EVENTO_LLAMADA_ACEPTADA, mem.EVENTO_LLAMADA_RECHAZADA):
        assert len(tipo) <= mem.TIPO_EVENTO_LARGO_MAX and tipo not in mem.TIPOS_EVENTO_INTERNOS
    assert (mem.EVENTO_LLAMADA_ACEPTADA, mem.EVENTO_LLAMADA_RECHAZADA) == ("llamada_aceptada_por_cliente", "llamada_rechazada_por_cliente")


def test_el_origen_de_la_confirmacion_esta_registrado():
    assert envios.ORIGENES["gabi_confirma_llamada"] == {"esencial": True}
    assert "gabi_confirma_llamada" in envios.ORIGENES_CON_LIMPIEZA_DE_FORMATO


# ── Escenario con la base ────────────────────────────────────────────────────────────────────────

async def _ofertado(codigo, *, horario="abierto", con_tarea=False, asesores=("ana",), **cfg):
    """Un lead callado hace 3 h al que Gabi YA le mandó la oferta (evidencia registrada), con el módulo en modo activo."""
    negocio, canal = await _negocio(codigo, horario)
    if asesores:
        await _asesores(negocio, *asesores)
    await _lead(negocio, canal, horas=3)
    await _activar(negocio, **{ll.CLAVE_OFERTA_ACTIVA: 1, ll.CLAVE_HORAS_SILENCIO: 1}, **cfg)
    oferta = (await ll.preparar_ofertas([{"telefono": TEL, "negocio_id": negocio["id"]}]))[TEL]
    assert oferta["accion"] == "ofrecer"
    await mem.guardar_mensaje(TEL, "assistant", oferta["texto"], negocio["id"])
    await ll.registrar_oferta_enviada(TEL, negocio["id"], oferta)
    if con_tarea:
        await ll.procesar_negocio(negocio["id"])
        assert len(await _tareas()) == 1
    return negocio, canal


async def _responde(negocio, texto, mensaje_id=None, *, guardar=True, ahora=None):
    """Lo que hace el webhook: interpreta la respuesta y DESPUÉS guarda el mensaje del cliente."""
    r = await ll.procesar_respuesta_del_cliente(TEL, negocio["id"], texto, mensaje_id, ahora)
    if guardar:
        await mem.guardar_mensaje(TEL, "user", texto, negocio["id"])
    return r


async def _contacto():
    async with mem.async_session() as s:
        return (await s.execute(select(mem.Contact).where(mem.Contact.telefono == TEL))).scalar_one()


def _manana_lima(hora: int) -> datetime:
    hoy = (datetime.utcnow() - timedelta(hours=5)).date()
    return datetime(hoy.year, hoy.month, hoy.day, hora) + timedelta(days=1, hours=5)


# ── Aceptar ──────────────────────────────────────────────────────────────────────────────────────

async def test_aceptar_con_la_tarea_ya_creada_la_deja_pendiente_protegida_y_registra_la_evidencia():
    negocio, canal = await _ofertado("ro-acepta", con_tarea=True)
    (antes,) = await _tareas()
    r = await _responde(negocio, "Sí, claro!", "wamid.ro-1")
    assert r["efecto"] == "aceptada" and r["intencion"] == "acepta"
    assert r["texto"] == "Perfecto, Ana. Un asesor te llamará en breve. Si cambias de idea, avísame por aquí."
    (t,) = await _tareas()
    assert t.id == antes.id and t.estado == "pendiente" and t.programada_para is None and t.modo == "activo" and t.grupo == "llamar"
    assert t.senales["aceptada_por_cliente"] is True and t.senales["con_hora"] is False
    (e,) = await _eventos(mem.EVENTO_LLAMADA_ACEPTADA)
    assert e.payload["texto"] == "Sí, claro!" and e.payload["mensaje_id"] == "wamid.ro-1" and e.payload["capa"] == "reglas"
    assert e.payload["tarea_id"] == t.id and e.payload["intencion"] == "acepta" and e.descripcion == "El cliente aceptó la llamada"
    assert "telefono" not in e.payload and TEL not in json.dumps(e.payload)                   # sin más PII que el texto literal
    visibles = [x["tipo"] for x in await mem.listar_eventos_lead(TEL)]
    assert mem.EVENTO_LLAMADA_ACEPTADA in visibles                                              # evidencia visible en el Timeline


async def test_aceptar_sin_que_el_cron_haya_creado_la_tarea_la_crea():
    negocio, canal = await _ofertado("ro-acepta2")
    assert await _tareas() == []
    r = await _responde(negocio, "dale", "wamid.ro-2")
    assert r["efecto"] == "aceptada"
    (t,) = await _tareas()
    assert t.estado == "pendiente" and t.modo == "activo" and t.grupo == "llamar" and t.segmento == "A" and t.puntaje == 12
    assert t.senales["aceptada_por_cliente"] is True and t.vence_en > datetime.utcnow() + timedelta(days=2)
    assert len(await _eventos(mem.EVENTO_LLAMADA_PENDIENTE_CREADA)) == 1
    # y el reparto normal la toma
    await ll.procesar_negocio(negocio["id"])
    vista = await ll.listar_tareas(negocio["id"], _usuario(negocio, "ana"))
    assert [x["aceptada_por_cliente"] for x in vista["tareas"]] == [True]


async def test_la_tarea_aceptada_sobrevive_a_que_el_cliente_siga_escribiendo():
    negocio, canal = await _ofertado("ro-sobrevive", con_tarea=True)
    await _responde(negocio, "sí", "wamid.ro-3")
    await mem.guardar_mensaje(TEL, "user", "gracias", negocio["id"])
    assert await ll.cancelar_por_respuesta_del_cliente(TEL, negocio["id"]) == 0               # el hook del webhook no la toca
    assert await ll.revalidar_abiertas(negocio["id"]) == 0                                     # ni la revalidación del Cron/listado
    (t,) = await _tareas()
    assert t.estado in ("pendiente", "programada")
    # pero si una persona toma el caso, sí se cancela
    assert await ll.cancelar_por_respuesta_del_cliente(TEL, negocio["id"], motivo="paso_a_humano") == 1


async def test_dar_una_hora_programa_la_llamada_para_esa_hora():
    negocio, canal = await _ofertado("ro-hora", con_tarea=True)
    r = await _responde(negocio, "mañana a las 10", "wamid.ro-4")
    assert r["efecto"] == "aceptada" and r["intencion"] == "hora"
    assert "mañana alrededor de las 10 a. m." in r["texto"]
    (t,) = await _tareas()
    assert t.estado == "programada" and t.programada_para == _manana_lima(10) == t.proximo_intento_en
    assert t.senales["con_hora"] is True and t.vence_en >= t.programada_para + timedelta(hours=23)
    (e,) = await _eventos(mem.EVENTO_LLAMADA_ACEPTADA)
    assert e.payload["intencion"] == "hora" and e.payload["programada_para"].endswith("Z") and "mañana" in e.payload["cuando"]
    # todavía no es accionable
    assert (await ll.datos_para_inicio(negocio["id"], "ana"))["pendientes"] == 0


async def test_una_hora_fuera_del_horario_de_atencion_pasa_a_la_proxima_apertura():
    negocio, canal = await _ofertado("ro-horario")
    for dia in range(7):
        await mem.guardar_horario_atencion(negocio["id"], dia, True, "09:00", "18:00")
    r = await _responde(negocio, "mañana a las 8 de la noche", "wamid.ro-5")
    assert r["efecto"] == "aceptada" and "a partir de las 9 a. m." in r["texto"]
    (t,) = await _tareas()
    hoy = (datetime.utcnow() - timedelta(hours=5)).date()
    esperado = datetime(hoy.year, hoy.month, hoy.day, 9) + timedelta(days=2, hours=5)         # la noche de mañana cae fuera: pasado mañana 09:00
    assert t.estado == "programada" and t.programada_para == esperado


async def test_aceptar_con_el_negocio_cerrado_queda_programada_para_la_apertura():
    negocio, canal = await _ofertado("ro-cerrado", horario="cerrado")
    r = await _responde(negocio, "ahora", "wamid.ro-6")
    assert r["efecto"] == "aceptada" and "a partir de las 12 a. m." in r["texto"]
    (t,) = await _tareas()
    assert t.estado == "programada" and t.programada_para > datetime.utcnow()


async def test_aceptar_ya_o_ahora_con_el_negocio_abierto_es_inmediato():
    negocio, canal = await _ofertado("ro-ya")
    r = await _responde(negocio, "ya mismo")
    assert "en breve" in r["texto"]
    (t,) = await _tareas()
    assert t.estado == "pendiente" and t.programada_para is None


# ── Compuerta legal, plazo, una sola vez, idempotencia ───────────────────────────────────────────

@pytest.mark.parametrize("escenario", ["apagado", "sombra", "sin_aceptacion"])
async def test_aceptar_sin_el_modo_efectivo_activo_no_programa_nada(escenario):
    negocio, canal = await _ofertado(f"ro-compuerta-{escenario}")
    if escenario == "apagado":
        await _cfg(negocio, **{ll.CLAVE_GABI_ACTIVO: 0})
    elif escenario == "sombra":
        await _cfg(negocio, **{ll.CLAVE_MODO: "sombra"})
    else:
        await ll.revocar_responsabilidad(negocio["id"], "admin")
        await _cfg(negocio, **{ll.CLAVE_MODO: "activo"})
        assert await ll.modo_efectivo(negocio["id"]) == "sombra"
    assert await _responde(negocio, "sí, a las 3") is None
    assert await _tareas() == [] and await _eventos(mem.EVENTO_LLAMADA_ACEPTADA) == []


@pytest.mark.parametrize("escenario", ["apagado", "sombra", "sin_aceptacion"])
async def test_el_rechazo_se_registra_siempre_aunque_el_modulo_este_en_sombra_o_apagado(escenario):
    negocio, canal = await _ofertado(f"ro-rech-{escenario}")
    if escenario == "apagado":
        await _cfg(negocio, **{ll.CLAVE_GABI_ACTIVO: 0})
    elif escenario == "sombra":
        await _cfg(negocio, **{ll.CLAVE_MODO: "sombra"})
    else:
        await ll.revocar_responsabilidad(negocio["id"], "admin")
    r = await _responde(negocio, "no me llamen")
    assert r["efecto"] == "rechazada" and r["texto"].startswith("Listo, Ana, no te llamaremos.")
    assert (await _contacto()).no_llamar_en is not None
    (e,) = await _eventos(mem.EVENTO_LLAMADA_RECHAZADA)
    assert e.payload["texto"] == "no me llamen" and e.payload["primera_respuesta"] is True


async def test_una_oferta_vencida_ya_no_se_interpreta():
    negocio, canal = await _ofertado("ro-vencida")
    async with mem.async_session() as s:
        for e in (await s.execute(select(mem.EventoLead).where(mem.EventoLead.tipo == mem.EVENTO_LLAMADA_OFERTA_ENVIADA))).scalars().all():
            e.creado = datetime.utcnow() - timedelta(hours=25)
        await s.commit()
    assert await _responde(negocio, "sí") is None
    assert await _tareas() == [] and await _eventos(mem.EVENTO_LLAMADA_ACEPTADA) == []
    assert (await _contacto()).no_llamar_en is None


async def test_dentro_del_plazo_de_24_horas_si_se_interpreta():
    negocio, canal = await _ofertado("ro-plazo")
    async with mem.async_session() as s:               # todo ocurrió hace 23 h: la oferta y los mensajes de antes
        for e in (await s.execute(select(mem.EventoLead).where(mem.EventoLead.tipo == mem.EVENTO_LLAMADA_OFERTA_ENVIADA))).scalars().all():
            e.creado = datetime.utcnow() - timedelta(hours=23)
        for m in (await s.execute(select(mem.Mensaje))).scalars().all():
            m.timestamp = m.timestamp - timedelta(hours=23)
        await s.commit()
    assert (await _responde(negocio, "sí"))["efecto"] == "aceptada"


async def test_solo_la_primera_respuesta_de_texto_cuenta_una_vez_por_oferta():
    negocio, canal = await _ofertado("ro-una")
    assert await _responde(negocio, "¿cuánto cuesta?", "wamid.ro-7") is None                  # primera respuesta: «otro» → sigue Gabi
    assert await _responde(negocio, "sí, a las 3", "wamid.ro-8") is None                       # la segunda ya no se interpreta
    assert await _tareas() == [] and await _eventos(mem.EVENTO_LLAMADA_ACEPTADA) == []


async def test_una_reaccion_o_un_adjunto_no_gastan_la_unica_oportunidad():
    negocio, canal = await _ofertado("ro-react")
    await mem.guardar_mensaje(TEL, "user", f"{mem.PREFIJO_REACCION} 👍", negocio["id"])
    await mem.guardar_mensaje(TEL, "user", "[image]", negocio["id"])
    assert (await _responde(negocio, "sí"))["efecto"] == "aceptada"


async def test_despues_de_aceptar_otra_respuesta_no_cambia_la_hora():
    negocio, canal = await _ofertado("ro-despues")
    await _responde(negocio, "mañana a las 10", "wamid.ro-9")
    (antes,) = await _tareas()
    assert await _responde(negocio, "mejor a las 4", "wamid.ro-10") is None
    (despues,) = await _tareas()
    assert despues.programada_para == antes.programada_para and len(await _eventos(mem.EVENTO_LLAMADA_ACEPTADA)) == 1


async def test_el_mismo_mensaje_dos_veces_no_repite_el_efecto_pero_si_la_confirmacion():
    negocio, canal = await _ofertado("ro-idem")
    r1 = await _responde(negocio, "sí", "wamid.ro-11", guardar=False)
    r2 = await _responde(negocio, "sí", "wamid.ro-11", guardar=False)                          # reintento antes de que se guardara el mensaje
    assert r1["efecto"] == r2["efecto"] == "aceptada" and r1["texto"] == r2["texto"] and r1["tarea_id"] == r2["tarea_id"]
    assert len(await _tareas()) == 1 and len(await _eventos(mem.EVENTO_LLAMADA_ACEPTADA)) == 1


async def test_el_mismo_rechazo_dos_veces_no_repite_el_efecto_pero_si_la_confirmacion():
    negocio, canal = await _ofertado("ro-idem2")
    n1 = await _responde(negocio, "no me llamen", "wamid.ro-12", guardar=False)
    n2 = await _responde(negocio, "no me llamen", "wamid.ro-12", guardar=False)
    assert n1["efecto"] == n2["efecto"] == "rechazada" and n1["texto"] == n2["texto"] and n1["texto"].startswith("Listo, Ana")
    assert len(await _eventos(mem.EVENTO_LLAMADA_RECHAZADA)) == 1


async def test_el_mismo_rechazo_con_mas_contenido_no_se_confirma_ni_al_repetirse():
    negocio, canal = await _ofertado("ro-idem3")
    c1 = await _responde(negocio, "no me llamen, ¿cuánto cuesta?", "wamid.ro-12b", guardar=False)         # sin confirmación: Gabi contesta
    c2 = await _responde(negocio, "no me llamen, ¿cuánto cuesta?", "wamid.ro-12b", guardar=False)
    assert c1["efecto"] == c2["efecto"] == "rechazada" and c1["texto"] is None and c2["texto"] is None


async def test_sin_oferta_ni_tarea_no_pasa_nada():
    negocio, canal = await _negocio("ro-nada")
    await _lead(negocio, canal, horas=3)
    await _activar(negocio, **{ll.CLAVE_OFERTA_ACTIVA: 1})
    for texto in ("sí", "a las 3", "gracias", "no me interesa"):
        assert await ll.procesar_respuesta_del_cliente(TEL, negocio["id"], texto, None) is None
    assert await _tareas() == [] and await _eventos() == [] and (await _contacto()).no_llamar_en is None
    assert await ll.procesar_respuesta_del_cliente(TEL, negocio["id"], "", None) is None
    assert await ll.procesar_respuesta_del_cliente("51000000000", negocio["id"], "sí", None) is None


async def test_un_lead_que_ya_no_es_llamable_no_se_agenda():
    negocio, canal = await _ofertado("ro-gating")
    await mem.asignar_asesor_a_lead(TEL, "ana")                                                 # una persona tomó el caso tras la oferta
    assert await _responde(negocio, "sí") is None
    assert await _tareas() == []


async def test_el_grupo_de_control_nunca_se_toca():
    negocio, canal = await _ofertado("ro-control", con_tarea=True)
    (t,) = await _tareas()
    await _tocar(t.id, grupo="control")
    assert await _responde(negocio, "sí") is None
    assert (await _tareas())[0].grupo == "control" and (await _tareas())[0].senales.get("aceptada_por_cliente") is None


async def test_una_tarea_de_sombra_abierta_pasa_a_activa_al_aceptar():
    negocio, canal = await _ofertado("ro-sombra-previa")
    await _cfg(negocio, **{ll.CLAVE_MODO: "sombra"})
    await ll.procesar_negocio(negocio["id"])                                                    # el Cron crea una tarea de sombra
    (t,) = await _tareas()
    assert t.modo == "sombra"
    await _cfg(negocio, **{ll.CLAVE_MODO: "activo"})
    assert (await _responde(negocio, "sí"))["efecto"] == "aceptada"
    (t2,) = await _tareas()
    assert t2.id == t.id and t2.modo == "activo" and t2.senales["aceptada_por_cliente"] is True


# ── Rechazar ─────────────────────────────────────────────────────────────────────────────────────

async def test_rechazar_marca_al_contacto_cancela_la_tarea_y_registra_la_evidencia():
    negocio, canal = await _ofertado("ro-rechaza", con_tarea=True)
    r = await _responde(negocio, "No me llamen por favor", "wamid.ro-13")
    assert r["efecto"] == "rechazada" and r["texto"] == "Listo, Ana, no te llamaremos. Seguimos por aquí por WhatsApp si lo necesitas."
    (t,) = await _tareas()
    assert t.estado == "cancelada" and t.motivo_cierre == "no_llamar"
    assert (await _contacto()).no_llamar_en is not None
    (e,) = await _eventos(mem.EVENTO_LLAMADA_RECHAZADA)
    assert e.payload["texto"] == "No me llamen por favor" and e.payload["tarea_id"] == t.id and e.descripcion == "El cliente pidió que no lo llamen"
    assert mem.EVENTO_LLAMADA_RECHAZADA in [x["tipo"] for x in await mem.listar_eventos_lead(TEL)]
    # la conversación sigue normal para los próximos mensajes
    assert await _responde(negocio, "hola, ¿tienen termas de 80 litros?") is None


async def test_el_rechazo_con_mas_contenido_se_registra_pero_deja_que_gabi_conteste():
    negocio, canal = await _ofertado("ro-rechaza2")
    r = await _responde(negocio, "no me llamen, ¿cuánto cuesta la terma?")
    assert r["efecto"] == "rechazada" and r["texto"] is None
    assert (await _contacto()).no_llamar_en is not None


async def test_con_no_llamar_en_nunca_mas_hay_tareas_ni_aceptacion():
    negocio, canal = await _ofertado("ro-nunca", con_tarea=True)
    await _responde(negocio, "prefiero por escrito")
    await mem.guardar_mensaje(TEL, "assistant", "Perfecto, seguimos por aquí.", negocio["id"])
    resumen = await ll.procesar_negocio(negocio["id"])
    assert resumen["creacion"]["creadas"] == 0
    assert (await _tareas())[0].estado == "cancelada" and len(await _tareas()) == 1
    async with mem.async_session() as s:
        assert (await ll.evaluar_lead(s, await s.get(mem.Lead, TEL), datetime.utcnow(), None)).motivo == "no_llamar"
    assert await ll.preparar_ofertas([{"telefono": TEL, "negocio_id": negocio["id"]}]) == {}


async def test_el_rechazo_posterior_a_la_primera_respuesta_tambien_marca_al_contacto():
    negocio, canal = await _ofertado("ro-posterior", con_tarea=True)
    await _responde(negocio, "sí, a las 3 de la tarde")
    (t,) = await _tareas()
    assert t.estado in ("pendiente", "programada")
    r = await _responde(negocio, "mejor ya no quiero que me llamen", "wamid.ro-14")             # segundo mensaje, tarea aceptada abierta
    assert r == {"efecto": "rechazada", "intencion": "rechaza", "texto": None, "conversation_id": t.conversation_id, "tarea_id": None}
    assert (await _tareas())[0].estado == "cancelada" and (await _tareas())[0].motivo_cierre == "no_llamar"
    assert (await _contacto()).no_llamar_en is not None
    (e,) = await _eventos(mem.EVENTO_LLAMADA_RECHAZADA)
    assert e.payload["primera_respuesta"] is False


async def test_el_rechazo_antes_de_que_exista_la_tarea_marca_al_contacto():
    negocio, canal = await _ofertado("ro-antes")
    assert await _responde(negocio, "¿cuánto cuesta?") is None                                 # primera respuesta: otro
    r = await _responde(negocio, "no gracias, no me interesa", "wamid.ro-15")                  # segunda, la oferta sigue sin tarea
    assert r["efecto"] == "rechazada" and r["texto"] is None
    assert (await _contacto()).no_llamar_en is not None


async def test_un_no_gracias_suelto_a_mitad_de_conversacion_no_marca_sin_oferta_ni_tarea_abierta():
    negocio, canal = await _ofertado("ro-nomarca", con_tarea=True)
    await _responde(negocio, "¿cuánto cuesta?")                                                # primera respuesta: el hook cancela la tarea
    await ll.cancelar_por_respuesta_del_cliente(TEL, negocio["id"])
    assert await _responde(negocio, "no gracias, ese modelo no me gusta") is None
    assert (await _contacto()).no_llamar_en is None


async def test_un_no_me_llamen_sin_oferta_ni_tarea_marca_solo_con_el_modulo_encendido():
    negocio, canal = await _negocio("ro-sinctx")
    await _lead(negocio, canal, horas=3)
    assert await ll.procesar_respuesta_del_cliente(TEL, negocio["id"], "no me llamen", None) is None      # módulo apagado
    assert (await _contacto()).no_llamar_en is None
    await _encender(negocio, "sombra")
    assert await ll.procesar_respuesta_del_cliente(TEL, negocio["id"], "no gracias", None) is None        # desinterés genérico: no
    r = await ll.procesar_respuesta_del_cliente(TEL, negocio["id"], "por favor no me llamen", "wamid.ro-16")
    assert r["efecto"] == "rechazada" and r["texto"] is None
    assert (await _contacto()).no_llamar_en is not None


# ── Haiku ────────────────────────────────────────────────────────────────────────────────────────

class _Haiku:
    def __init__(self, respuesta=None, error=None):
        self.respuesta, self.error, self.llamadas = respuesta, error, []

    async def __call__(self, texto, ahora_lima):
        self.llamadas.append(texto)
        if self.error:
            raise self.error
        return self.respuesta if isinstance(self.respuesta, str) else json.dumps(self.respuesta)


async def test_con_haiku_apagado_lo_ambiguo_es_otro_y_no_se_llama_a_nadie(monkeypatch):
    haiku = _Haiku({"intencion": "acepta", "hora_iso": None, "confianza": 0.99})
    monkeypatch.setattr(ll, "_llamar_haiku", haiku)
    negocio, canal = await _ofertado("ro-h0")
    assert (await ll.leer_config(negocio["id"])).respuesta_haiku is False
    assert await _responde(negocio, "pasamos al otro tema") is None
    assert haiku.llamadas == [] and await _tareas() == []


async def test_con_haiku_encendido_una_respuesta_ambigua_se_interpreta(monkeypatch):
    haiku = _Haiku({"intencion": "acepta", "hora_iso": None, "confianza": 0.9})
    monkeypatch.setattr(ll, "_llamar_haiku", haiku)
    negocio, canal = await _ofertado("ro-h1", **{ll.CLAVE_RESPUESTA_HAIKU: 1})
    r = await _responde(negocio, "me parece bien lo que dicen")
    assert haiku.llamadas == ["me parece bien lo que dicen"] and r["efecto"] == "aceptada"
    (e,) = await _eventos(mem.EVENTO_LLAMADA_ACEPTADA)
    assert e.payload["capa"] == "haiku" and e.payload["texto"] == "me parece bien lo que dicen"


async def test_haiku_con_una_hora_programa_la_llamada(monkeypatch):
    lima = (datetime.utcnow() - timedelta(hours=5)) + timedelta(days=1)
    objetivo = datetime(lima.year, lima.month, lima.day, 16, 30)
    haiku = _Haiku({"intencion": "hora", "hora_iso": objetivo.strftime("%Y-%m-%dT%H:%M"), "confianza": 0.95})
    monkeypatch.setattr(ll, "_llamar_haiku", haiku)
    negocio, canal = await _ofertado("ro-h2", **{ll.CLAVE_RESPUESTA_HAIKU: 1})
    r = await _responde(negocio, "cuando salga de mi reunión del jueves")
    assert r["intencion"] == "hora" and "alrededor de las 4:30 p. m." in r["texto"]
    assert (await _tareas())[0].programada_para == objetivo + timedelta(hours=5)


async def test_haiku_con_rechazo_marca_al_contacto(monkeypatch):
    monkeypatch.setattr(ll, "_llamar_haiku", _Haiku({"intencion": "rechaza", "hora_iso": None, "confianza": 0.9}))
    negocio, canal = await _ofertado("ro-h3", **{ll.CLAVE_RESPUESTA_HAIKU: 1})
    r = await _responde(negocio, "mejor déjenlo así")
    assert r["efecto"] == "rechazada" and (await _contacto()).no_llamar_en is not None
    assert (await _eventos(mem.EVENTO_LLAMADA_RECHAZADA))[0].payload["capa"] == "haiku"


@pytest.mark.parametrize("respuesta", [
    {"intencion": "acepta", "hora_iso": None, "confianza": 0.5},                                  # confianza baja
    {"intencion": "otro", "hora_iso": None, "confianza": 0.99},
    {"intencion": "quizas", "hora_iso": None, "confianza": 0.99},                                 # intención desconocida
    {"intencion": "hora", "hora_iso": None, "confianza": 0.99},                                   # hora sin hora
    {"intencion": "hora", "hora_iso": "2020-01-01T10:00", "confianza": 0.99},                     # hora pasada
    {"intencion": "hora", "hora_iso": "2999-01-01T10:00", "confianza": 0.99},                     # hora absurda
    {"intencion": "acepta", "hora_iso": None, "confianza": "mucha"},
    "esto no es json", "", "[]",
])
async def test_haiku_con_una_respuesta_inutil_es_otro(monkeypatch, respuesta):
    haiku = _Haiku(respuesta)
    monkeypatch.setattr(ll, "_llamar_haiku", haiku)
    negocio, canal = await _ofertado("ro-h4", **{ll.CLAVE_RESPUESTA_HAIKU: 1})
    assert await _responde(negocio, "pasamos al otro tema") is None
    assert len(haiku.llamadas) == 1 and await _tareas() == []


@pytest.mark.parametrize("error", [TimeoutError(), RuntimeError("API caída"), ConnectionError("red")])
async def test_haiku_que_falla_o_tarda_es_otro_y_no_rompe_nada(monkeypatch, error):
    monkeypatch.setattr(ll, "_llamar_haiku", _Haiku(error=error))
    negocio, canal = await _ofertado("ro-h5", **{ll.CLAVE_RESPUESTA_HAIKU: 1})
    assert await _responde(negocio, "pasamos al otro tema") is None
    assert await _tareas() == []


async def test_haiku_solo_para_lo_ambiguo_nunca_para_preguntas_ni_reglas_claras(monkeypatch):
    haiku = _Haiku({"intencion": "acepta", "hora_iso": None, "confianza": 0.99})
    monkeypatch.setattr(ll, "_llamar_haiku", haiku)
    negocio, canal = await _ofertado("ro-h6", **{ll.CLAVE_RESPUESTA_HAIKU: 1})
    assert await _responde(negocio, "sí, ¿cuánto cuesta?") is None                               # pregunta: Gabi contesta, no Haiku
    assert haiku.llamadas == []


async def test_haiku_sin_el_modo_activo_no_se_llama(monkeypatch):
    haiku = _Haiku({"intencion": "acepta", "hora_iso": None, "confianza": 0.99})
    monkeypatch.setattr(ll, "_llamar_haiku", haiku)
    negocio, canal = await _ofertado("ro-h7", **{ll.CLAVE_RESPUESTA_HAIKU: 1})
    await _cfg(negocio, **{ll.CLAVE_MODO: "sombra"})
    assert await _responde(negocio, "pasamos al otro tema") is None
    assert haiku.llamadas == []


async def test_haiku_usa_un_cliente_con_timeout_de_4_segundos_y_sin_reintentos():
    assert ll.HAIKU_TIMEOUT_SEG == 4.0
    cliente = ll._crear_cliente_haiku()
    try:
        assert cliente.timeout == 4.0 and cliente.max_retries == 0
    finally:
        await cliente.close()


# ── Configuración ────────────────────────────────────────────────────────────────────────────────

async def test_la_clave_de_haiku_se_configura_y_viene_apagada():
    negocio, _ = await _negocio("ro-cfg")
    assert (await ll.estado_configuracion(negocio["id"]))["respuesta_haiku"] is False
    estado = await ll.guardar_cambios(negocio["id"], "admin", {"respuesta_haiku": True})
    assert estado["respuesta_haiku"] is True and await mem.obtener_configuracion("llamadas_respuesta_haiku", "", negocio_id=negocio["id"]) == "1"
    assert (await ll.guardar_cambios(negocio["id"], "admin", {"respuesta_haiku": False}))["respuesta_haiku"] is False
    for invalido in ("1", 1, None):
        with pytest.raises(ValueError):
            ll.validar_cambios({"respuesta_haiku": invalido})


# ── El camino real del webhook ───────────────────────────────────────────────────────────────────

def _canal_dict(canal, negocio):
    return {"id": canal["id"], "negocio_id": negocio["id"], "unidad_id": None, "phone_number_id": canal["phone_number_id"], "modo": "produccion"}


async def test_webhook_aceptar_confirma_con_el_texto_fijo_y_gabi_no_conversa_encima(monkeypatch):
    negocio, canal = await _ofertado("ro-wh1", con_tarea=True)
    proveedor, gabi = _preparar_webhook(monkeypatch, _canal_dict(canal, negocio), canal, [])
    await _correr(proveedor, [_msg(TEL, canal, "Sí, a las 3 de la tarde por favor", "wamid.ro-wh1")])
    assert gabi.llamadas == 0
    assert len(proveedor.enviados) == 1 and proveedor.enviados[0].startswith("Perfecto, Ana. Un asesor te llamará ")
    guardados = [(m.role, m.content) for m in await _mensajes(TEL) if m.timestamp > datetime.utcnow() - timedelta(minutes=5)]
    assert guardados[-2:] == [("user", "Sí, a las 3 de la tarde por favor"), ("assistant", proveedor.enviados[0])]    # en ese orden
    (t,) = await _tareas()
    assert t.estado in ("pendiente", "programada") and t.senales["aceptada_por_cliente"] is True
    async with mem.async_session() as s:
        envio = (await s.execute(select(mem.EnvioMeta).where(mem.EnvioMeta.telefono == TEL, mem.EnvioMeta.origen == "gabi_confirma_llamada"))).scalars().all()
    assert len(envio) == 1
    # el siguiente mensaje del cliente sí lo atiende Gabi, y la llamada sigue en pie
    await _correr(proveedor, [_msg(TEL, canal, "gracias", "wamid.ro-wh1b")])
    assert gabi.llamadas == 1
    assert (await _tareas())[0].estado in ("pendiente", "programada")


async def test_webhook_rechazar_confirma_y_la_conversacion_sigue_normal(monkeypatch):
    negocio, canal = await _ofertado("ro-wh2", con_tarea=True)
    proveedor, gabi = _preparar_webhook(monkeypatch, _canal_dict(canal, negocio), canal, [])
    await _correr(proveedor, [_msg(TEL, canal, "no me llamen", "wamid.ro-wh2")])
    assert gabi.llamadas == 0 and proveedor.enviados == ["Listo, Ana, no te llamaremos. Seguimos por aquí por WhatsApp si lo necesitas."]
    assert (await _contacto()).no_llamar_en is not None and (await _tareas())[0].motivo_cierre == "no_llamar"
    await _correr(proveedor, [_msg(TEL, canal, "tienen termas de 80 litros?", "wamid.ro-wh2b")])
    assert gabi.llamadas == 1


async def test_webhook_otra_cosa_es_el_comportamiento_de_siempre(monkeypatch):
    negocio, canal = await _ofertado("ro-wh3", con_tarea=True)
    proveedor, gabi = _preparar_webhook(monkeypatch, _canal_dict(canal, negocio), canal, [])
    await _correr(proveedor, [_msg(TEL, canal, "sí, ¿cuánto cuesta?", "wamid.ro-wh3")])
    assert gabi.llamadas == 1 and not [m for m in proveedor.enviados if "te llamará" in m]
    (t,) = await _tareas()
    assert t.estado == "cancelada" and t.motivo_cierre == "respondio_cliente"                    # se cancela por respuesta, como hoy
    assert await _eventos(mem.EVENTO_LLAMADA_ACEPTADA) == [] and (await _contacto()).no_llamar_en is None


async def test_webhook_el_eco_del_celular_no_cuenta_como_respuesta(monkeypatch):
    negocio, canal = await _ofertado("ro-wh4", con_tarea=True)
    proveedor, gabi = _preparar_webhook(monkeypatch, _canal_dict(canal, negocio), canal, [])
    await _correr(proveedor, [_msg(TEL, canal, "sí, claro", "wamid.ro-wh4", tipo_evento="echo")])
    assert await _eventos(mem.EVENTO_LLAMADA_ACEPTADA) == [] and proveedor.enviados == []
    assert (await _tareas())[0].motivo_cierre == "paso_a_humano"                                  # una persona respondió: se cancela como siempre
    await _correr(proveedor, [_msg(TEL, canal, "no me llamen", "wamid.ro-wh4b", tipo_evento="echo")])
    assert (await _contacto()).no_llamar_en is None


async def test_webhook_una_reaccion_no_cuenta(monkeypatch):
    negocio, canal = await _ofertado("ro-wh5", con_tarea=True)
    proveedor, gabi = _preparar_webhook(monkeypatch, _canal_dict(canal, negocio), canal, [])
    await _correr(proveedor, [_msg(TEL, canal, f"{mem.PREFIJO_REACCION} 👍", "wamid.ro-wh5", tipo="reaction")])
    assert await _eventos(mem.EVENTO_LLAMADA_ACEPTADA) == [] and proveedor.enviados == [] and gabi.llamadas == 0
    await _correr(proveedor, [_msg(TEL, canal, "sí", "wamid.ro-wh5b")])                           # la oportunidad sigue intacta
    assert len(await _eventos(mem.EVENTO_LLAMADA_ACEPTADA)) == 1


async def test_webhook_el_mismo_wamid_dos_veces_confirma_una_sola_vez(monkeypatch):
    negocio, canal = await _ofertado("ro-wh6", con_tarea=True)
    proveedor, gabi = _preparar_webhook(monkeypatch, _canal_dict(canal, negocio), canal, [])
    await _correr(proveedor, [_msg(TEL, canal, "sí", "wamid.ro-wh6"), _msg(TEL, canal, "sí", "wamid.ro-wh6")])
    assert len(proveedor.enviados) == 1 and len(await _eventos(mem.EVENTO_LLAMADA_ACEPTADA)) == 1 and len(await _tareas()) == 1


async def test_webhook_si_la_confirmacion_no_sale_el_turno_sigue_con_gabi(monkeypatch):
    negocio, canal = await _ofertado("ro-wh7", con_tarea=True)
    proveedor, gabi = _preparar_webhook(monkeypatch, _canal_dict(canal, negocio), canal, [])
    intentos = []

    async def no_sale(telefono, mensaje, canal=None, mensaje_id_citado=None):
        intentos.append(mensaje)
        return False, None
    monkeypatch.setattr(proveedor, "enviar_mensaje", no_sale)
    await _correr(proveedor, [_msg(TEL, canal, "sí", "wamid.ro-wh7")])
    assert intentos[0].startswith("Perfecto, Ana.") and gabi.llamadas == 1
    assert len(await _eventos(mem.EVENTO_LLAMADA_ACEPTADA)) == 1 and (await _tareas())[0].estado in ("pendiente", "programada")


async def test_webhook_con_el_modulo_apagado_todo_sigue_como_antes(monkeypatch):
    negocio, canal = await _negocio("ro-wh8")
    await _lead(negocio, canal, horas=3)
    proveedor, gabi = _preparar_webhook(monkeypatch, _canal_dict(canal, negocio), canal, [])
    await _correr(proveedor, [_msg(TEL, canal, "sí", "wamid.ro-wh8"), _msg(TEL, canal, "no me llamen", "wamid.ro-wh8b")])
    assert gabi.llamadas >= 1 and not [m for m in proveedor.enviados if "te llamará" in m or "no te llamaremos" in m]
    assert await _tareas() == [] and await _eventos(mem.EVENTO_LLAMADA_ACEPTADA) == [] and (await _contacto()).no_llamar_en is None


async def test_un_error_al_interpretar_la_respuesta_no_frena_el_mensaje(monkeypatch):
    negocio, canal = await _ofertado("ro-wh9", con_tarea=True)
    proveedor, gabi = _preparar_webhook(monkeypatch, _canal_dict(canal, negocio), canal, [])

    async def falla(*a, **k):
        raise RuntimeError("base caída")
    monkeypatch.setattr(ll, "procesar_respuesta_del_cliente", falla)
    await _correr(proveedor, [_msg(TEL, canal, "sí", "wamid.ro-wh9")])
    assert gabi.llamadas == 1                                                                      # Gabi atiende como siempre
    assert (await _tareas())[0].motivo_cierre == "respondio_cliente"
