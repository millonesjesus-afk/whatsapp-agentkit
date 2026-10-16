# agent/solo_clic.py — Experimento «solo clic»: medición, definición, exclusión y SOMBRA (2026-10-16, Fases A y B).
#
# Problema: el cliente que toca un anuncio de Click-to-WhatsApp (o un enlace wa.me) abre el chat con un texto PRELLENADO,
# lo envía sin escribir nada propio, Gabi le contesta… y no vuelve a decir nada. Es el grupo más grande de leads callados
# y el que menos se sabe cómo recuperar (¿un toque a los 20 min? ¿ofrecer una llamada a la hora? ¿esperar 2 h como hoy?).
# El dueño aprobó (2026-10-16) un experimento por brazos; ESTE módulo construye solo lo que NO envía ni llama a nadie:
#   · FASE A — la DEFINICIÓN de «solo clic» (función pura `es_solo_clic`), la asignación de brazo por hash determinista
#     (`brazo_de`) y la EXCLUSIÓN obligatoria: con el experimento encendido, «Para llamar» (agent/llamadas.py) no crea
#     tarea automática para un «solo clic» (motivo `solo_clic_en_experimento`), de modo que ninguno sea llamado sin un SÍ
#     explícito aunque «Para llamar» pase a modo activo. Con el experimento APAGADO el módulo de llamadas es idéntico.
#   · FASE B — la SOMBRA de 14 días: a los `sc_cohorte_min` minutos del primer mensaje entregado de Gabi, cada conversación
#     «solo clic» recibe un brazo y se REGISTRA (evento interno `exp_solo_clic_sombra`) qué habría hecho el sistema; después,
#     a las 24 h y 72 h, se registra el desenlace NATURAL (`exp_solo_clic_resultado`). NADA se envía y NADA se llama: este
#     módulo no importa `envios` ni el proveedor de WhatsApp, y no crea `TareaLlamada` (hay pruebas que lo verifican).
#
# DEFINICIÓN DE «SOLO CLIC» (informe D9, aprobada por el dueño). Una conversación lo es cuando se cumplen TODAS:
#   (a) origen con texto prellenado: `AttributionEvent` de tipo meta_ads | meta_ads_no_resuelto | wa_link, o
#       `Lead.campana_origen` (o la campaña de la Conversation). Un orgánico que escribe «hola» a mano queda fuera.
#   (b) el primer turno del cliente —todo mensaje suyo ANTERIOR al primer mensaje ENTREGADO de Gabi (Gabi responde en ~7 s)—
#       es exactamente UN texto, igual a un «prellenado conocido» o un saludo trivial («hola», «buenas»…).
#       «Prellenado conocido» = texto normalizado (minúsculas, sin tildes, espacios colapsados) que aparece en ≥ 5
#       conversaciones distintas (con origen prellenado) en 30 días, o que coincide con `Campana.texto_saludo`, o con el
#       `body`/`headline` del referral de ESA conversación.
#   (c) Gabi sí le escribió: ≥ 1 mensaje de Gabi entregado (estado_envio no fallido/incierto), sin falla de IA ni envío caído.
#   (d) CERO eventos del cliente después del primer mensaje de Gabi, de cualquier tipo (texto, audio, imagen, sticker y
#       reacción cuentan como interacción).
#   (e) exclusiones previas al tratamiento, idénticas en todos los brazos: triaje ATC cerrado, con asesor / pausado /
#       escalado / derivado, mensaje humano (role asesor, o assistant con via_app), `Contact.no_llamar_en`, teléfono no
#       peruano o BSUID, conversación cerrada o ciclo reabierto, números internos o de prueba (`triaje_atc_telefonos_excluidos`
#       y canal en modo pruebas), caso con resultado (salvo `sin_respuesta`) y origen `formulario_meta`.
#
# HALLAZGO QUE ESTA DEFINICIÓN CORRIGE (sin tocar el puntaje de «Para llamar»). `llamadas.evaluar_lead` resta 1 mensaje real
# si hay `campana_origen` o `AttributionEvent` SIN comprobar que ese mensaje sea el prellenado: un cliente que edita el
# prellenado y escribe algo real, o que manda solo un audio/imagen, se cuenta mal. Además el puntaje de un solo clic puede
# llegar a 4 solo por lo que DIJO Gabi (precio + financiamiento). Aquí «solo clic» es una propiedad del primer turno y del
# silencio, no del puntaje; por eso la exclusión es explícita (en `crear_tareas`) y no un cambio al puntaje.
#
# CONFIGURACIÓN (por negocio, tabla `configuracion`; todo APAGADO por defecto):
#   sc_exp_modo           apagado (default) | sombra | activo. `activo` está RESERVADO: no existe la Fase C (envío real), así
#                         que se degrada a `sombra` con un aviso en el log. Un valor desconocido = apagado.
#   sc_exp_epoca          "v1". Cambiarla re-asigna los brazos (la sal del hash incluye la época) y abre una cohorte nueva.
#   sc_exp_pct_c/t1/t2    40 / 20 / 40 (control / toque genérico / oferta de llamada). Se normalizan a 100.
#   sc_exp_pct_t3         SIEMPRE 0 — BLOQUEADA: la llamada directa sin consentimiento previo (T3) queda fuera de plan hasta
#                         después de las pruebas; luego habrá un botón de aprobación legal versionada. Esta clave se ignora.
#   sc_cohorte_min 20 · sc_toque_min 20 · sc_oferta_min 60 · sc_ventana_max_horas 22 · sc_max_intentos 2 (esta última
#                         solo la usará la Fase C).
#
# DÓNDE CORRE LA SOMBRA: dentro del Cron ya existente `scripts/crear_tareas_llamada.py` (*/15, servicio sunny-embrace), en un
# bloque aislado con try/except que nunca rompe la creación de tareas. No hay Cron nuevo. Con el modo apagado el bloque solo
# lee `sc_exp_modo` y sale.

import logging
import math
import re
import time
import unicodedata
from collections import Counter
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from statistics import NormalDist
from typing import Callable, Sequence

from sqlalchemy import func, select

from agent import atencion_atrasada
from agent.llamadas import _numero, _percentil_de, es_telefono_peruano
from agent.memory import (
    EVENTO_EMERGENCIA_GAS_DERIVADA, EVENTO_EXP_SOLO_CLIC_RESULTADO, EVENTO_EXP_SOLO_CLIC_SOMBRA, EVENTO_TRIAJE_ATC_CERRADO,
    EVENTO_TRIAJE_ATC_FALLIDO, PREFIJO_REACCION, AttributionEvent, Campana, CanalWhatsApp, Contact, Conversation, EventoLead,
    Lead, Mensaje, async_session, es_texto_de_error_tecnico, es_texto_de_reenganche_automatico, iso_utc, listar_negocios,
    obtener_configuracion, guardar_configuracion, textos_de_error_tecnico_conocidos,
)
from agent.tools import _rangos_de_atencion_por_dia

logger = logging.getLogger("agentkit")

# ── Claves de configuración y límites ────────────────────────────────────────────────────────────────────
CLAVE_MODO = "sc_exp_modo"
CLAVE_EPOCA = "sc_exp_epoca"
CLAVE_PCT_C = "sc_exp_pct_c"
CLAVE_PCT_T1 = "sc_exp_pct_t1"
CLAVE_PCT_T2 = "sc_exp_pct_t2"
CLAVE_PCT_T3 = "sc_exp_pct_t3"          # BLOQUEADA: ver la cabecera. Existe como nombre reservado; su valor se ignora.
CLAVE_COHORTE_MIN = "sc_cohorte_min"
CLAVE_TOQUE_MIN = "sc_toque_min"
CLAVE_OFERTA_MIN = "sc_oferta_min"
CLAVE_VENTANA_MAX_HORAS = "sc_ventana_max_horas"
CLAVE_MAX_INTENTOS = "sc_max_intentos"

MODO_APAGADO, MODO_SOMBRA, MODO_ACTIVO = "apagado", "sombra", "activo"
MODOS_VALIDOS = (MODO_APAGADO, MODO_SOMBRA, MODO_ACTIVO)

EPOCA_POR_DEFECTO = "v1"
PCT_C_POR_DEFECTO, PCT_T1_POR_DEFECTO, PCT_T2_POR_DEFECTO = 40.0, 20.0, 40.0
PCT_T3 = 0.0                             # constante: la llamada directa (T3) NO existe en esta entrega
BRAZO_C, BRAZO_T1, BRAZO_T2 = "C", "T1", "T2"
BRAZOS = (BRAZO_C, BRAZO_T1, BRAZO_T2)  # T3 no está: el hash nunca la asigna

# (mínimo, máximo, default) de las claves numéricas. Fuera de rango se ajusta al borde; un no-número cae al default.
LIMITES = {
    CLAVE_COHORTE_MIN: (5, 120, 20),
    CLAVE_TOQUE_MIN: (5, 240, 20),
    CLAVE_OFERTA_MIN: (10, 360, 60),
    CLAVE_VENTANA_MAX_HORAS: (1.0, 23.5, 22.0),
    CLAVE_MAX_INTENTOS: (1, 5, 2),
}
LIMITES_PCT = (0.0, 100.0)
_RE_EPOCA = re.compile(r"[A-Za-z0-9._-]{1,20}")

# Acciones que la sombra dice que HABRÍA hecho (nombres nominales de cada brazo; los minutos reales van en el payload).
ACCION_TOQUE = "toque_20"
ACCION_OFERTA = "oferta_60"
ACCION_CONTROL = "control_2h"
ACCION_OMITIDA_FUERA_DE_HORARIO = "omitida_fuera_de_horario"   # el negocio no abre en el horizonte: no hay a qué hora ofrecer
ACCION_OMITIDA_VENTANA = "omitida_ventana"                      # la apertura cae después de `sc_ventana_max_horas`
HORIZONTES_RESULTADO_H = (24, 72)
VENTANA_WHATSAPP_HORAS = 24.0

# Mensajes de la sombra: se evalúa a los `sc_cohorte_min` minutos; si el Cron estuvo caído se tolera este retraso máximo
# (pasado ese tiempo la conversación ya no se registra: el momento del tratamiento dejó de ser comparable).
RETRASO_MAXIMO_EVALUACION_MIN = 60
DIAS_BUSQUEDA_RESULTADOS = 10

# Prellenados frecuentes
MINIMO_CONVERSACIONES_PRELLENADO = 5
DIAS_PRELLENADOS = 30
CACHE_PRELLENADOS_SEGUNDOS = 600
LARGO_MAXIMO_PRELLENADO = 500

ORIGENES_PRELLENADO = ("meta_ads", "meta_ads_no_resuelto", "wa_link")
ESTADOS_NO_ENTREGADOS = ("fallido", "incierto")
RESULTADOS_ADMITIDOS = (None, "", "sin_respuesta")   # el cierre automático de 15 h NO saca a nadie del universo
CLAVE_TELEFONOS_EXCLUIDOS = "triaje_atc_telefonos_excluidos"   # la misma lista de números del equipo/pruebas del triaje ATC

# Motivos de descarte (en el orden en que se evalúan).
MOTIVOS_EXCLUSION = (
    "numero_interno", "telefono_no_peruano", "no_llamar", "triaje_atc", "asesor", "pausa", "escalado", "derivado",
    "conversacion_cerrada", "ciclo_reabierto", "con_resultado", "origen_formulario", "humano",
)
MOTIVOS_DEFINICION = (
    "sin_origen_prellenado", "sin_mensajes", "falla_ia", "envio_caido", "gabi_no_escribio", "sin_primer_turno",
    "primer_turno_multiple", "primer_turno_no_texto", "primer_turno_no_prellenado", "cliente_interactuo",
)
MOTIVOS = MOTIVOS_EXCLUSION + MOTIVOS_DEFINICION


# ── Utilidades puras ─────────────────────────────────────────────────────────────────────────────────────

def normalizar_texto(texto: str | None) -> str:
    """Minúsculas, sin tildes y espacios colapsados (la puntuación se conserva: el prellenado se compara tal cual)."""
    t = unicodedata.normalize("NFKD", (texto or "").lower())
    t = "".join(c for c in t if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", t).strip()


_SALUDOS_NUCLEO = frozenset({"hola", "holi", "buenas", "buenos", "buen", "hey", "hi", "hello", "saludos", "ola"})
_SALUDOS_RELLENO = frozenset({"dias", "dia", "tardes", "noches", "a", "todos", "que", "tal", "amigos", "amigo", "gaso"})


def es_saludo_trivial(texto: str | None) -> bool:
    """«hola», «buenas», «buenos días», «hola buenas tardes», «holaaa 👋»: solo saludo, sin pregunta ni dato. Hasta 4
    palabras, todas del vocabulario de saludo, con al menos una palabra de saludo."""
    plano = re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", normalizar_texto(texto))).strip()
    plano = re.sub(r"(.)\1{2,}", r"\1", plano)           # «holaaa» → «hola», «buenasss» → «buenas»
    palabras = plano.split()
    if not 1 <= len(palabras) <= 4:
        return False
    return all(p in _SALUDOS_NUCLEO or p in _SALUDOS_RELLENO for p in palabras) and any(p in _SALUDOS_NUCLEO for p in palabras)


def brazo_de(
    conversation_id: str, epoca: str = EPOCA_POR_DEFECTO,
    pct_c: float = PCT_C_POR_DEFECTO, pct_t1: float = PCT_T1_POR_DEFECTO, pct_t2: float = PCT_T2_POR_DEFECTO,
) -> str:
    """Brazo (C | T1 | T2) de una conversación: HASH DETERMINISTA con sal propia `exp_solo_clic_<época>` (estable entre
    procesos y reinicios; DISTINTA de la sal del holdout de «Para llamar» y de la de exploración, así el brazo no se
    correlaciona con ellos). Reparto por defecto C 40 % / T2 40 % / T1 20 %: se normaliza a 100 si los porcentajes no
    suman 100. T3 NO existe (`PCT_T3` = 0, bloqueada). Con todos los porcentajes en 0 todo cae en control."""
    c, t1, t2 = (max(0.0, float(x)) for x in (pct_c, pct_t1, pct_t2))
    total = c + t1 + t2
    if total <= 0:
        return BRAZO_C
    posicion = _percentil_de(conversation_id, f"exp_solo_clic_{epoca}") * total / 100.0
    if posicion < c:
        return BRAZO_C
    if posicion < c + t2:
        return BRAZO_T2
    return BRAZO_T1


def lunes_de_la_semana_lima(instante_utc: datetime) -> str:
    lima = instante_utc - timedelta(hours=5)
    return (lima - timedelta(days=lima.weekday())).strftime("%Y-%m-%d")


# ── Definición «solo clic» (PURA) ────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class MensajeSC:
    """Lo mínimo de un `Mensaje` que necesita la definición. `role`: user | assistant | asesor."""
    role: str
    contenido: str
    timestamp: datetime
    estado_envio: str | None = None
    via_app: bool = False
    archivo_id: int | None = None


@dataclass(frozen=True)
class DatosSC:
    """Todo lo que `es_solo_clic` necesita, ya cargado (la función no toca la base ni el reloj)."""
    mensajes: Sequence[MensajeSC]                 # de ESTA conversación (cualquier orden: se ordena por timestamp)
    origen_prellenado: bool
    textos_conocidos: frozenset = frozenset()     # YA normalizados: frecuentes ∪ campañas ∪ referral de la conversación
    telefono: str | None = None
    errores_conocidos: frozenset | None = None    # textos de error técnico de Gabi (None = los del sistema)
    hasta: datetime | None = None                 # evalúa «como estaba a esa hora»: ignora lo posterior (None = todo)
    numero_interno: bool = False
    no_llamar: bool = False
    triaje_atc_cerrado: bool = False
    con_asesor: bool = False
    pausado: bool = False
    escalado: bool = False
    derivado: bool = False
    cerrado: bool = False
    ciclo_reabierto: bool = False
    con_resultado: bool = False
    origen_formulario: bool = False


@dataclass(frozen=True)
class VeredictoSC:
    es_solo_clic: bool
    motivo: str | None = None                     # por qué NO (primera regla que falla); None si lo es
    tipo_primer_turno: str | None = None          # prellenado_conocido | saludo
    primer_gabi_en: datetime | None = None        # primer mensaje de Gabi ENTREGADO (la «T» del experimento)
    ultimo_cliente_en: datetime | None = None     # el mensaje del cliente (la ventana de 24 h corre desde aquí)


def _no(motivo: str, **resto) -> VeredictoSC:
    return VeredictoSC(False, motivo, **resto)


def _es_reaccion(m: MensajeSC) -> bool:
    return m.role == "user" and (m.contenido or "").startswith(PREFIJO_REACCION)


_RE_PLACEHOLDER = re.compile(r"^\[[a-z_]+\]$")


def _es_texto_del_cliente(m: MensajeSC) -> bool:
    """Un mensaje del cliente que es TEXTO (no reacción, ni adjunto, ni el marcador «[audio]»/«[image]»…)."""
    contenido = (m.contenido or "").strip()
    return bool(
        m.role == "user" and contenido and m.archivo_id is None
        and not contenido.startswith(PREFIJO_REACCION) and not _RE_PLACEHOLDER.match(contenido)
    )


def _entregado(m: MensajeSC) -> bool:
    return (m.estado_envio or "") not in ESTADOS_NO_ENTREGADOS


def primer_mensaje_de_gabi_entregado(mensajes: Sequence[MensajeSC]) -> MensajeSC | None:
    """El primer mensaje de Gabi que el cliente RECIBIÓ (no fallido/incierto, no de un humano desde el celular)."""
    ordenados = sorted(enumerate(mensajes), key=lambda p: (p[1].timestamp, p[0]))
    return next((m for _, m in ordenados if m.role == "assistant" and not m.via_app and _entregado(m)), None)


def es_solo_clic(d: DatosSC) -> VeredictoSC:
    """¿Esta conversación es «solo clic»? PURA: ver la definición en la cabecera del módulo. Devuelve el veredicto y, si no,
    la PRIMERA regla que falla (ver `MOTIVOS`: las exclusiones (e) se evalúan antes que la definición (a)-(d))."""
    for motivo, falla in (
        ("numero_interno", d.numero_interno), ("telefono_no_peruano", not es_telefono_peruano(d.telefono)),
        ("no_llamar", d.no_llamar), ("triaje_atc", d.triaje_atc_cerrado), ("asesor", d.con_asesor), ("pausa", d.pausado),
        ("escalado", d.escalado), ("derivado", d.derivado), ("conversacion_cerrada", d.cerrado),
        ("ciclo_reabierto", d.ciclo_reabierto), ("con_resultado", d.con_resultado), ("origen_formulario", d.origen_formulario),
    ):
        if falla:
            return _no(motivo)

    ordenados = [m for _, m in sorted(enumerate(d.mensajes), key=lambda p: (p[1].timestamp, p[0]))]
    if d.hasta is not None:
        ordenados = [m for m in ordenados if m.timestamp <= d.hasta]
    if any(m.role == "asesor" or (m.role == "assistant" and m.via_app) for m in ordenados):
        return _no("humano")
    if not d.origen_prellenado:                                                     # (a)
        return _no("sin_origen_prellenado")
    if not ordenados:
        return _no("sin_mensajes")

    # (c) Gabi sí le escribió, sin falla de IA ni envío caído.
    conocidos = d.errores_conocidos if d.errores_conocidos is not None else textos_de_error_tecnico_conocidos()
    de_gabi = [m for m in ordenados if m.role == "assistant"]
    if any(es_texto_de_error_tecnico(m.contenido, conocidos) for m in de_gabi):
        return _no("falla_ia")
    primero = next((i for i, m in enumerate(ordenados) if m.role == "assistant" and _entregado(m)), None)
    if primero is None:
        return _no("envio_caido" if de_gabi else "gabi_no_escribio")
    if any(not _entregado(m) for m in ordenados[:primero] if m.role == "assistant"):
        return _no("envio_caido")                                                   # el primer intento se cayó: T no es comparable
    primer_gabi = ordenados[primero]
    if es_texto_de_reenganche_automatico(primer_gabi.contenido):
        return _no("gabi_no_escribio")                                              # el «primer» mensaje fue un reenganche: Gabi no respondió

    # (b) primer turno: todo lo del cliente anterior al primer mensaje entregado de Gabi.
    turno = [m for m in ordenados[:primero] if m.role == "user"]
    if not turno:
        return _no("sin_primer_turno", primer_gabi_en=primer_gabi.timestamp)
    if len(turno) > 1:
        return _no("primer_turno_multiple", primer_gabi_en=primer_gabi.timestamp)
    mensaje = turno[0]
    if not _es_texto_del_cliente(mensaje):
        return _no("primer_turno_no_texto", primer_gabi_en=primer_gabi.timestamp)
    if normalizar_texto(mensaje.contenido) in d.textos_conocidos:
        tipo = "prellenado_conocido"
    elif es_saludo_trivial(mensaje.contenido):
        tipo = "saludo"
    else:
        return _no("primer_turno_no_prellenado", primer_gabi_en=primer_gabi.timestamp)

    # (d) cero eventos del cliente después del primer mensaje de Gabi (reacciones, audios, imágenes y stickers cuentan).
    if any(m.role == "user" for m in ordenados[primero + 1:]):
        return _no("cliente_interactuo", primer_gabi_en=primer_gabi.timestamp, ultimo_cliente_en=mensaje.timestamp)
    return VeredictoSC(True, None, tipo, primer_gabi.timestamp, mensaje.timestamp)


# ── Plan de acción de la sombra (PURO) ───────────────────────────────────────────────────────────────────

def plan_de_accion(
    brazo: str, *, primer_gabi_en: datetime, ultimo_cliente_en: datetime, abierto: Callable[[datetime], bool],
    proxima_apertura: Callable[[datetime], datetime | None], toque_min: float = 20, oferta_min: float = 60,
    ventana_max_horas: float = 22.0,
) -> dict:
    """Qué HABRÍA hecho el sistema con esta conversación según su brazo (solo se registra; nada se envía):
      C  → `control_2h`: el reenganche de 2 h y el cierre de 15 h de siempre.
      T1 → `toque_20`: UN toque genérico (el texto de reenganche actual) a ~T+20..35 min.
      T2 → `oferta_60`: oferta de llamada con SÍ explícito a T+60 min si el negocio está abierto; si no, se difiere a la
           próxima apertura (`diferida`). `omitida_ventana` si esa hora cae después de `ventana_max_horas` desde el último
           mensaje del cliente (la ventana de 24 h de WhatsApp, con margen) y `omitida_fuera_de_horario` si el calendario
           no tiene ninguna apertura próxima.
    Además, para CUALQUIER brazo, describe lo que T2 habría podido hacer (`oferta_hipotetica`): sirve para medir qué %
    es alcanzable a T+60 aunque la conversación haya caído en otro brazo."""
    t60 = primer_gabi_en + timedelta(minutes=oferta_min)
    cierre_ventana = ultimo_cliente_en + timedelta(hours=VENTANA_WHATSAPP_HORAS)
    limite_oferta = ultimo_cliente_en + timedelta(hours=ventana_max_horas)
    en_horario = bool(abierto(t60))
    oferta_en: datetime | None = t60
    diferida = False
    cierra_antes = False
    if en_horario:
        estado = ACCION_OFERTA
    else:
        apertura = proxima_apertura(t60)
        if apertura is None:
            oferta_en, estado = None, ACCION_OMITIDA_FUERA_DE_HORARIO
        else:
            oferta_en, diferida = apertura, True
            cierra_antes = cierre_ventana <= apertura
            estado = ACCION_OFERTA if apertura <= limite_oferta else ACCION_OMITIDA_VENTANA
    if estado != ACCION_OFERTA and oferta_en is not None:
        oferta_en = None
    accion = {BRAZO_C: ACCION_CONTROL, BRAZO_T1: ACCION_TOQUE, BRAZO_T2: estado}.get(brazo, ACCION_CONTROL)
    return {
        "accion_habria": accion,
        "cayo_en_horario_a_T60": en_horario,
        "ventana_cierra_antes_de_apertura": cierra_antes,
        "oferta_hipotetica": {"estado": estado, "en": iso_utc(oferta_en) if oferta_en else None, "diferida": diferida},
        "toque_en": iso_utc(primer_gabi_en + timedelta(minutes=toque_min)),
        "ventana_cierra_en": iso_utc(cierre_ventana),
    }


# ── Estadística (PURA, para el análisis) ─────────────────────────────────────────────────────────────────

def intervalo_wilson(k: int, n: int, z: float = 1.959964) -> tuple[float | None, float | None]:
    """Intervalo de Wilson al 95 % para una proporción k/n. (None, None) si n = 0."""
    if n <= 0:
        return None, None
    p = k / n
    den = 1 + z * z / n
    centro = (p + z * z / (2 * n)) / den
    mitad = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return max(0.0, centro - mitad), min(1.0, centro + mitad)


def n_por_brazo(p0: float, p1: float, alfa: float = 0.05, potencia: float = 0.8) -> float:
    """Tamaño por brazo para detectar p0 → p1 con una prueba de dos proporciones (bilateral). inf si p0 = p1."""
    if p0 == p1:
        return math.inf
    nd = NormalDist()
    za, zb = nd.inv_cdf(1 - alfa / 2), nd.inv_cdf(potencia)
    pbar = (p0 + p1) / 2
    num = (za * math.sqrt(2 * pbar * (1 - pbar)) + zb * math.sqrt(p0 * (1 - p0) + p1 * (1 - p1))) ** 2
    return num / (p1 - p0) ** 2


def efecto_minimo_detectable(p0: float, n: int, alfa: float = 0.05, potencia: float = 0.8) -> float | None:
    """El menor aumento absoluto (p1 - p0) que se detectaría con `n` casos por brazo (α, potencia). None si ni un aumento
    hasta 100 % se detectaría (n demasiado chico) o si n ≤ 0."""
    if n <= 0 or not 0 <= p0 < 1:
        return None
    techo = 1 - p0
    if n_por_brazo(p0, min(1.0, p0 + techo * 0.999999), alfa, potencia) > n:
        return None
    bajo, alto = 1e-6, techo * 0.999999
    for _ in range(80):
        medio = (bajo + alto) / 2
        if n_por_brazo(p0, p0 + medio, alfa, potencia) <= n:
            alto = medio
        else:
            bajo = medio
    return alto


# ── Configuración ────────────────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class ConfigSC:
    modo_configurado: str            # apagado | sombra | activo (lo guardado)
    modo: str                        # EFECTIVO: apagado | sombra (`activo` queda reservado y opera como sombra)
    motivo_degradado: str | None
    epoca: str
    pct_c: float
    pct_t1: float
    pct_t2: float
    pct_t3: float                    # siempre 0 (bloqueada)
    cohorte_min: int
    toque_min: int
    oferta_min: int
    ventana_max_horas: float
    max_intentos: int


_avisos_degradacion: set[str] = set()


def _porcentaje(valor, defecto: float) -> float:
    return float(_numero(valor, LIMITES_PCT[0], LIMITES_PCT[1], defecto))


async def leer_config(negocio_id: str, avisar: bool = True) -> ConfigSC:
    """Configuración del experimento con sus defaults y el modo EFECTIVO. `activo` se degrada a `sombra` (la Fase C —envío
    real— no existe): se deja un aviso en el log, una vez por proceso y negocio."""
    async def v(clave, defecto=""):
        return await obtener_configuracion(clave, defecto, negocio_id=negocio_id)

    configurado = (await v(CLAVE_MODO, MODO_APAGADO) or "").strip().lower()
    if configurado not in MODOS_VALIDOS:
        configurado = MODO_APAGADO
    modo, motivo = configurado, None
    if configurado == MODO_APAGADO:
        return ConfigSC(
            configurado, MODO_APAGADO, None, EPOCA_POR_DEFECTO, PCT_C_POR_DEFECTO, PCT_T1_POR_DEFECTO, PCT_T2_POR_DEFECTO, PCT_T3,
            *(LIMITES[c][2] for c in (CLAVE_COHORTE_MIN, CLAVE_TOQUE_MIN, CLAVE_OFERTA_MIN, CLAVE_VENTANA_MAX_HORAS, CLAVE_MAX_INTENTOS)),
        )
    if configurado == MODO_ACTIVO:
        modo, motivo = MODO_SOMBRA, "fase_c_no_construida"
        if avisar and negocio_id not in _avisos_degradacion:
            _avisos_degradacion.add(negocio_id)
            logger.warning(
                "solo_clic: sc_exp_modo=activo está RESERVADO (la Fase C —envío real— no está construida): el negocio %s "
                "opera como SOMBRA. No se enviará ni se llamará a nadie.", negocio_id[:8],
            )

    async def n(clave):
        minimo, maximo, defecto = LIMITES[clave]
        return _numero(await v(clave, str(defecto)), minimo, maximo, defecto)

    epoca = (await v(CLAVE_EPOCA, EPOCA_POR_DEFECTO) or "").strip()
    if not _RE_EPOCA.fullmatch(epoca):
        epoca = EPOCA_POR_DEFECTO
    cohorte = await n(CLAVE_COHORTE_MIN)
    return ConfigSC(
        configurado, modo, motivo, epoca,
        _porcentaje(await v(CLAVE_PCT_C, str(PCT_C_POR_DEFECTO)), PCT_C_POR_DEFECTO),
        _porcentaje(await v(CLAVE_PCT_T1, str(PCT_T1_POR_DEFECTO)), PCT_T1_POR_DEFECTO),
        _porcentaje(await v(CLAVE_PCT_T2, str(PCT_T2_POR_DEFECTO)), PCT_T2_POR_DEFECTO),
        PCT_T3, cohorte, await n(CLAVE_TOQUE_MIN), max(cohorte, await n(CLAVE_OFERTA_MIN)), await n(CLAVE_VENTANA_MAX_HORAS),
        await n(CLAVE_MAX_INTENTOS),
    )


async def modo_efectivo(negocio_id: str) -> str:
    """apagado | sombra. Con el experimento apagado cuesta UNA lectura de configuración."""
    configurado = (await obtener_configuracion(CLAVE_MODO, MODO_APAGADO, negocio_id=negocio_id) or "").strip().lower()
    if configurado in (MODO_SOMBRA, MODO_ACTIVO):
        return (await leer_config(negocio_id)).modo
    return MODO_APAGADO


CAMPOS_ENTEROS = {
    "cohorte_min": CLAVE_COHORTE_MIN, "toque_min": CLAVE_TOQUE_MIN, "oferta_min": CLAVE_OFERTA_MIN, "max_intentos": CLAVE_MAX_INTENTOS,
}
CAMPOS_PCT = {"pct_c": CLAVE_PCT_C, "pct_t1": CLAVE_PCT_T1, "pct_t2": CLAVE_PCT_T2}


def validar_cambios(cuerpo: dict, actual: ConfigSC | None = None) -> dict[str, str]:
    """Valida un cambio de configuración y devuelve {clave: valor}. Todo o nada (ValueError en español). Rechaza `pct_t3`
    (bloqueada) y cualquier campo desconocido; si se toca algún porcentaje, los tres deben sumar 100 (los que no se envían
    se toman de `actual`)."""
    conocidos = {"modo", "epoca", "ventana_max_horas", *CAMPOS_ENTEROS, *CAMPOS_PCT}
    if "pct_t3" in cuerpo:
        raise ValueError("pct_t3 está BLOQUEADA: la llamada directa (T3) queda fuera del plan hasta después de las pruebas y de una aprobación legal.")
    desconocidos = sorted(set(cuerpo) - conocidos)
    if desconocidos:
        raise ValueError(f"Campos desconocidos: {', '.join(desconocidos)}.")
    cambios: dict[str, str] = {}
    if "modo" in cuerpo:
        if cuerpo["modo"] not in MODOS_VALIDOS:
            raise ValueError("modo debe ser «apagado», «sombra» o «activo».")
        cambios[CLAVE_MODO] = cuerpo["modo"]
    if "epoca" in cuerpo:
        if not isinstance(cuerpo["epoca"], str) or not _RE_EPOCA.fullmatch(cuerpo["epoca"].strip()):
            raise ValueError("epoca debe tener de 1 a 20 caracteres (letras, números, punto, guion o guion bajo).")
        cambios[CLAVE_EPOCA] = cuerpo["epoca"].strip()
    for campo, clave in CAMPOS_ENTEROS.items():
        if campo in cuerpo:
            valor, (minimo, maximo, _) = cuerpo[campo], LIMITES[clave]
            if isinstance(valor, bool) or not isinstance(valor, (int, float)) or int(valor) != valor:
                raise ValueError(f"{campo} debe ser un número entero entre {minimo} y {maximo}.")
            if not minimo <= valor <= maximo:
                raise ValueError(f"{campo} debe estar entre {minimo} y {maximo}.")
            cambios[clave] = str(int(valor))
    if "ventana_max_horas" in cuerpo:
        valor, (minimo, maximo, _) = cuerpo["ventana_max_horas"], LIMITES[CLAVE_VENTANA_MAX_HORAS]
        if isinstance(valor, bool) or not isinstance(valor, (int, float)) or not minimo <= valor <= maximo:
            raise ValueError(f"ventana_max_horas debe ser un número entre {minimo} y {maximo}.")
        cambios[CLAVE_VENTANA_MAX_HORAS] = str(valor)
    if any(c in cuerpo for c in CAMPOS_PCT):
        base = actual or ConfigSC(MODO_APAGADO, MODO_APAGADO, None, EPOCA_POR_DEFECTO, PCT_C_POR_DEFECTO, PCT_T1_POR_DEFECTO,
                                  PCT_T2_POR_DEFECTO, PCT_T3, 20, 20, 60, 22.0, 2)
        finales = {}
        for campo in CAMPOS_PCT:
            valor = cuerpo.get(campo, getattr(base, campo))
            if isinstance(valor, bool) or not isinstance(valor, (int, float)) or not LIMITES_PCT[0] <= valor <= LIMITES_PCT[1]:
                raise ValueError(f"{campo} debe ser un número entre 0 y 100.")
            finales[campo] = float(valor)
        if abs(sum(finales.values()) - 100.0) > 0.01:
            raise ValueError(f"pct_c + pct_t1 + pct_t2 debe sumar 100 (suman {sum(finales.values()):g}).")
        for campo in CAMPOS_PCT:
            if campo in cuerpo:
                cambios[CAMPOS_PCT[campo]] = str(finales[campo])
    return cambios


async def estado_configuracion(negocio_id: str) -> dict:
    config = await leer_config(negocio_id, avisar=False)
    return {
        "modo": config.modo_configurado, "modo_efectivo": config.modo, "motivo_degradado": config.motivo_degradado,
        "epoca": config.epoca, "pct_c": config.pct_c, "pct_t1": config.pct_t1, "pct_t2": config.pct_t2,
        "pct_t3": config.pct_t3, "pct_t3_bloqueada": True, "cohorte_min": config.cohorte_min, "toque_min": config.toque_min,
        "oferta_min": config.oferta_min, "ventana_max_horas": config.ventana_max_horas, "max_intentos": config.max_intentos,
    }


async def guardar_cambios(negocio_id: str, cuerpo: dict) -> dict:
    cambios = validar_cambios(cuerpo, await leer_config(negocio_id, avisar=False))
    for clave, valor in cambios.items():
        await guardar_configuracion(clave, valor, negocio_id=negocio_id)
    if cambios:
        logger.info("solo_clic: configuración actualizada: %s", sorted(cambios))
    return await estado_configuracion(negocio_id)


# ── Contexto del negocio (prellenados frecuentes, cacheable) ─────────────────────────────────────────────

_cache_prellenados: dict[tuple, tuple[float, Counter]] = {}


def limpiar_cache() -> None:
    _cache_prellenados.clear()


async def _conversaciones_con_origen_prellenado(session, negocio_id: str, desde: datetime) -> set[str]:
    """Ids de las conversaciones creadas desde `desde` con origen prellenado (atribución, campaña de la conversación o
    `Lead.campana_origen`)."""
    ids = set((await session.execute(
        select(AttributionEvent.conversation_id).join(Conversation, Conversation.id == AttributionEvent.conversation_id).where(
            AttributionEvent.negocio_id == negocio_id, AttributionEvent.tipo_origen.in_(ORIGENES_PRELLENADO),
            Conversation.creado >= desde,
        )
    )).scalars().all())
    ids |= set((await session.execute(
        select(Conversation.id).where(
            Conversation.negocio_id == negocio_id, Conversation.creado >= desde, Conversation.campana_origen_id.is_not(None),
        )
    )).scalars().all())
    ids |= set((await session.execute(
        select(Conversation.id).join(Contact, Contact.id == Conversation.contact_id).join(
            Lead, (Lead.telefono == Contact.telefono) & (Lead.negocio_id == Conversation.negocio_id),
        ).where(
            Conversation.negocio_id == negocio_id, Conversation.creado >= desde,
            Lead.campana_origen.is_not(None), Lead.campana_origen != "",
        )
    )).scalars().all())
    return ids


async def conteo_prellenados(negocio_id: str, ahora: datetime | None = None, dias: int = DIAS_PRELLENADOS) -> Counter:
    """Cuántas conversaciones DISTINTAS (con origen prellenado, creadas en los últimos `dias`) abrieron con cada texto
    normalizado. Solo el PRIMER mensaje de texto del cliente de cada conversación. Cacheado 10 minutos."""
    ahora = ahora or datetime.utcnow()
    clave = (negocio_id, dias, int(ahora.timestamp() // CACHE_PRELLENADOS_SEGUNDOS))
    en_cache = _cache_prellenados.get(clave)
    if en_cache is not None and time.monotonic() - en_cache[0] < CACHE_PRELLENADOS_SEGUNDOS:
        return Counter(en_cache[1])
    desde = ahora - timedelta(days=dias)
    conteo: Counter = Counter()
    async with async_session() as session:
        ids = await _conversaciones_con_origen_prellenado(session, negocio_id, desde)
        ids_lista = sorted(ids)
        for i in range(0, len(ids_lista), 500):        # en tandas: un IN enorme revienta el límite de parámetros
            filas = (await session.execute(
                select(Mensaje.conversation_id, Mensaje.id, Mensaje.content, Mensaje.archivo_id).where(
                    Mensaje.negocio_id == negocio_id, Mensaje.role == "user", Mensaje.timestamp >= desde - timedelta(days=1),
                    Mensaje.conversation_id.in_(ids_lista[i:i + 500]),
                ).order_by(Mensaje.conversation_id, Mensaje.timestamp, Mensaje.id)
            )).all()
            vistos: set[str] = set()
            for conversation_id, _, contenido, archivo_id in filas:
                if conversation_id in vistos:
                    continue
                vistos.add(conversation_id)                       # solo el PRIMER mensaje del cliente de cada conversación
                m = MensajeSC("user", contenido or "", ahora, archivo_id=archivo_id)
                if _es_texto_del_cliente(m) and len(m.contenido) <= LARGO_MAXIMO_PRELLENADO:
                    conteo[normalizar_texto(contenido)] += 1
    _cache_prellenados[clave] = (time.monotonic(), Counter(conteo))
    return conteo


@dataclass(frozen=True)
class ContextoNegocio:
    negocio_id: str
    textos_conocidos: frozenset          # frecuentes (≥ 5 conversaciones en 30 días) ∪ textos de campañas
    telefonos_excluidos: frozenset       # solo dígitos
    errores_conocidos: frozenset


def _solo_digitos(texto: str) -> str:
    return re.sub(r"\D", "", texto or "")


async def contexto_de_negocio(negocio_id: str, ahora: datetime | None = None) -> ContextoNegocio:
    ahora = ahora or datetime.utcnow()
    conteo = await conteo_prellenados(negocio_id, ahora)
    textos = {t for t, n in conteo.items() if n >= MINIMO_CONVERSACIONES_PRELLENADO and t}
    async with async_session() as session:
        for texto_saludo, patron, tipo in (await session.execute(
            select(Campana.texto_saludo, Campana.patron, Campana.tipo_deteccion).where(Campana.negocio_id == negocio_id)
        )).all():
            if texto_saludo and texto_saludo.strip():
                textos.add(normalizar_texto(texto_saludo))
            if tipo == "texto_saludo" and patron and patron.strip():
                textos.add(normalizar_texto(patron))
    crudo = await obtener_configuracion(CLAVE_TELEFONOS_EXCLUIDOS, "", negocio_id=negocio_id)
    excluidos = {d for d in (_solo_digitos(x) for x in re.split(r"[,;\n]+", crudo or "")) if d}
    return ContextoNegocio(negocio_id, frozenset(textos), frozenset(excluidos), textos_de_error_tecnico_conocidos())


# ── Evaluación de una conversación contra la base ────────────────────────────────────────────────────────

async def _datos_de_conversacion(session, conversation: Conversation, ctx: ContextoNegocio) -> tuple[DatosSC, list[datetime]] | None:
    """Arma `DatosSC` de una conversación (solo lectura) con el estado ACTUAL y, aparte, los instantes de cierre definitivo
    (para poder evaluar «como estaba a cierta hora»). None si no hay contacto."""
    from agent.llamadas import _alcance_de_mensajes   # import tardío: privado de «Para llamar», mismo criterio de alcance

    negocio_id = conversation.negocio_id
    contact = await session.get(Contact, conversation.contact_id)
    if contact is None:
        return None
    telefono = contact.telefono
    lead = await session.get(Lead, telefono)
    if lead is not None and lead.negocio_id != negocio_id:
        lead = None
    filas = (await session.execute(
        select(Mensaje).where(*_alcance_de_mensajes(negocio_id, telefono, conversation.id)).order_by(Mensaje.timestamp, Mensaje.id)
    )).scalars().all()
    mensajes = [
        MensajeSC(m.role, m.content or "", m.timestamp, m.estado_envio, bool(m.via_app), m.archivo_id) for m in filas
    ]
    atribuciones = (await session.execute(
        select(AttributionEvent.tipo_origen, AttributionEvent.body, AttributionEvent.headline).where(
            AttributionEvent.negocio_id == negocio_id, AttributionEvent.conversation_id == conversation.id,
        )
    )).all()
    referral = {normalizar_texto(t) for _, body, headline in atribuciones for t in (body, headline) if t and t.strip()}
    origen = (
        any(tipo in ORIGENES_PRELLENADO for tipo, _, _ in atribuciones) or conversation.campana_origen_id is not None
        or bool(lead is not None and lead.campana_origen)
    )
    triaje = (await session.execute(
        select(EventoLead.id).where(
            EventoLead.negocio_id == negocio_id, EventoLead.conversation_id == conversation.id,
            EventoLead.tipo.in_((EVENTO_TRIAJE_ATC_CERRADO, EVENTO_TRIAJE_ATC_FALLIDO, EVENTO_EMERGENCIA_GAS_DERIVADA)),
        ).limit(1)
    )).first() is not None
    previas = (await session.execute(
        select(func.count(Conversation.id)).where(
            Conversation.contact_id == conversation.contact_id, Conversation.id != conversation.id,
            Conversation.creado < conversation.creado,
        )
    )).scalar_one()
    canal = await session.get(CanalWhatsApp, conversation.canal_id) if conversation.canal_id is not None else None

    cierres = [c for c in (conversation.cerrado_definitivamente_en, lead.cerrado_definitivamente_en if lead else None) if c is not None]
    resultado = lead.resultado if lead is not None else None
    datos = DatosSC(
        mensajes=mensajes, origen_prellenado=origen, textos_conocidos=ctx.textos_conocidos | frozenset(referral),
        telefono=telefono, errores_conocidos=ctx.errores_conocidos, hasta=None,
        numero_interno=bool(_solo_digitos(telefono) in ctx.telefonos_excluidos or (canal is not None and canal.modo == "pruebas")),
        no_llamar=contact.no_llamar_en is not None,
        triaje_atc_cerrado=triaje,
        con_asesor=bool(conversation.asesor_asignado_id or (lead is not None and lead.asesor_asignado)),
        pausado=bool(conversation.pausado_manual or (lead is not None and lead.pausado_manual)),
        escalado=bool(lead is not None and lead.escalado_supervision_en is not None),
        derivado=bool(
            conversation.paso_flujo == "derivado_asesor" or (lead is not None and lead.paso_flujo == "derivado_asesor")
        ),
        cerrado=bool(cierres),
        ciclo_reabierto=previas > 0,
        con_resultado=resultado not in RESULTADOS_ADMITIDOS,
        origen_formulario=bool(
            (lead is not None and lead.origen_contacto == "formulario_meta") or conversation.origen_contacto == "formulario_meta"
        ),
    )
    return datos, cierres


async def evaluar_conversacion(
    session, conversation: Conversation, ctx: ContextoNegocio, hasta: datetime | None = None, cohorte_min: float | None = None,
) -> VeredictoSC:
    """`es_solo_clic` de una conversación. `hasta`: evalúa lo que había hasta esa hora; si en cambio se pasa `cohorte_min`
    se evalúa como estaba a las T + `cohorte_min` (T = primer mensaje entregado de Gabi): así la cohorte queda definida por
    el silencio hasta T+20, sin depender de cuándo corrió el Cron. Sin ninguno, evalúa el estado actual."""
    armado = await _datos_de_conversacion(session, conversation, ctx)
    if armado is None:
        return _no("sin_mensajes")
    datos, cierres = armado
    if hasta is None and cohorte_min is not None:
        primero = primer_mensaje_de_gabi_entregado(datos.mensajes)
        if primero is not None:
            hasta = primero.timestamp + timedelta(minutes=cohorte_min)
    if hasta is not None:
        # «Como estaba a esa hora»: un cierre POSTERIOR no descalifica (los cierres definitivos llegan días después).
        datos = replace(datos, hasta=hasta, cerrado=any(c <= hasta for c in cierres))
    return es_solo_clic(datos)


async def es_solo_clic_conversacion(conversation_id: str, negocio_id: str, ctx: ContextoNegocio | None = None, ahora: datetime | None = None) -> bool:
    """Para la EXCLUSIÓN de «Para llamar»: ¿esta conversación es «solo clic» HOY (estado actual)? Solo lectura."""
    ctx = ctx or await contexto_de_negocio(negocio_id, ahora)
    async with async_session() as session:
        conversation = await session.get(Conversation, conversation_id)
        if conversation is None or conversation.negocio_id != negocio_id:
            return False
        return (await evaluar_conversacion(session, conversation, ctx)).es_solo_clic


# ── Desenlace natural (24 h / 72 h) ──────────────────────────────────────────────────────────────────────

async def desenlace(session, conversation: Conversation, telefono: str, ancla: datetime, horizonte_h: float) -> dict:
    """Lo que ocurrió entre `ancla` (T+20) y `ancla + horizonte_h`, SIN enviar ni cambiar nada. `respondio` cuenta cualquier
    evento del cliente (como la definición (d)); `respondio_real` excluye las reacciones."""
    from agent.llamadas import _alcance_de_mensajes

    fin = ancla + timedelta(hours=horizonte_h)
    filas = (await session.execute(
        select(Mensaje).where(
            *_alcance_de_mensajes(conversation.negocio_id, telefono, conversation.id),
            Mensaje.timestamp > ancla, Mensaje.timestamp <= fin,
        ).order_by(Mensaje.timestamp, Mensaje.id)
    )).scalars().all()
    del_cliente = [m for m in filas if m.role == "user"]
    reales = [m for m in del_cliente if not (m.content or "").startswith(PREFIJO_REACCION)]
    cierre = (await session.execute(
        select(EventoLead.payload).where(
            EventoLead.negocio_id == conversation.negocio_id, EventoLead.conversation_id == conversation.id,
            EventoLead.tipo == "resultado_cambiado", EventoLead.creado > ancla, EventoLead.creado <= fin,
        )
    )).scalars().all()
    return {
        "horizonte_h": horizonte_h,
        "respondio": bool(del_cliente),
        "respondio_real": bool(reales),
        "horas_hasta_respuesta": round((del_cliente[0].timestamp - ancla).total_seconds() / 3600, 2) if del_cliente else None,
        "reenganche_enviado": any(
            m.role == "assistant" and _entregado_orm(m) and es_texto_de_reenganche_automatico(m.content) for m in filas
        ),
        "intervencion_humana": any(m.role == "asesor" or (m.role == "assistant" and m.via_app) for m in filas),
        "cerrado_sin_respuesta": any(isinstance(p, dict) and p.get("nuevo") == "sin_respuesta" for p in cierre),
    }


def _entregado_orm(m) -> bool:
    return (m.estado_envio or "") not in ESTADOS_NO_ENTREGADOS


# ── La SOMBRA ────────────────────────────────────────────────────────────────────────────────────────────

def _de_iso(valor) -> datetime | None:
    if not isinstance(valor, str):
        return None
    try:
        return datetime.fromisoformat(valor.rstrip("Z"))
    except ValueError:
        return None


async def registrar_cohorte(negocio_id: str, config: ConfigSC, ahora: datetime, rangos, ctx: ContextoNegocio) -> dict:
    """Registra el evento `exp_solo_clic_sombra` de cada conversación «solo clic» cuyo primer mensaje entregado de Gabi
    cayó entre T+cohorte y T+cohorte+retraso máximo y que aún no tiene evento en esta época. IDEMPOTENTE. No envía nada."""
    desde = ahora - timedelta(minutes=config.cohorte_min + RETRASO_MAXIMO_EVALUACION_MIN)
    hasta = ahora - timedelta(minutes=config.cohorte_min)
    cont: Counter = Counter()
    descartes: Counter = Counter()
    async with async_session() as session:
        candidatas = list((await session.execute(
            select(Mensaje.conversation_id).where(
                Mensaje.negocio_id == negocio_id, Mensaje.role == "assistant", Mensaje.estado_envio.is_(None),
                Mensaje.conversation_id.is_not(None), Mensaje.timestamp >= desde, Mensaje.timestamp <= hasta,
            ).distinct()
        )).scalars().all())
        if not candidatas:
            return {"candidatas": 0, "registradas": 0}
        ya = {
            conv for conv, payload in (await session.execute(
                select(EventoLead.conversation_id, EventoLead.payload).where(
                    EventoLead.negocio_id == negocio_id, EventoLead.tipo == EVENTO_EXP_SOLO_CLIC_SOMBRA,
                    EventoLead.conversation_id.in_(candidatas),
                )
            )).all() if isinstance(payload, dict) and payload.get("epoca") == config.epoca
        }
    for conversation_id in candidatas:
        if conversation_id in ya:
            cont["ya_registradas"] += 1
            continue
        try:
            async with async_session() as session:
                conversation = await session.get(Conversation, conversation_id)
                if conversation is None or conversation.negocio_id != negocio_id:
                    continue
                veredicto = await evaluar_conversacion(session, conversation, ctx, cohorte_min=config.cohorte_min)
                if not veredicto.es_solo_clic:
                    descartes[veredicto.motivo] += 1
                    continue
                primer_gabi = veredicto.primer_gabi_en
                if not (desde <= primer_gabi <= hasta):
                    descartes["fuera_de_la_ventana_de_evaluacion"] += 1      # su primer mensaje de Gabi es de otra hora
                    continue
                brazo = brazo_de(conversation_id, config.epoca, config.pct_c, config.pct_t1, config.pct_t2)
                plan = plan_de_accion(
                    brazo, primer_gabi_en=primer_gabi, ultimo_cliente_en=veredicto.ultimo_cliente_en,
                    abierto=lambda t: atencion_atrasada.esta_abierto(rangos, t),
                    proxima_apertura=lambda t: atencion_atrasada.proxima_apertura(rangos, t),
                    toque_min=config.toque_min, oferta_min=config.oferta_min, ventana_max_horas=config.ventana_max_horas,
                )
                payload = {
                    "version": 1, "epoca": config.epoca, "brazo": brazo, **plan, "modo": config.modo,
                    "hora_real_evaluacion": iso_utc(ahora),
                    "minutos_desde_gabi": round((ahora - primer_gabi).total_seconds() / 60, 1),
                    "primer_gabi_en": iso_utc(primer_gabi), "ancla_en": iso_utc(primer_gabi + timedelta(minutes=config.cohorte_min)),
                    "tipo_primer_turno": veredicto.tipo_primer_turno, "cohorte_min": config.cohorte_min,
                    "toque_min": config.toque_min, "oferta_min": config.oferta_min, "ventana_max_horas": config.ventana_max_horas,
                    "pct": {"c": config.pct_c, "t1": config.pct_t1, "t2": config.pct_t2, "t3": config.pct_t3},
                }
                session.add(EventoLead(
                    conversation_id=conversation_id, negocio_id=negocio_id, opportunity_id=None,
                    tipo=EVENTO_EXP_SOLO_CLIC_SOMBRA, autor=None, payload=payload,
                    descripcion=f"Experimento solo clic (sombra): brazo {brazo} → habría hecho {plan['accion_habria']}"[:300],
                ))
                await session.commit()
                cont["registradas"] += 1
                cont[f"brazo_{brazo}"] += 1
        except Exception:  # noqa: BLE001 — una conversación con problemas no frena a las demás
            logger.exception("solo_clic: no se pudo registrar la sombra de una conversación (se reintenta en la próxima corrida)")
            cont["errores"] += 1
    return {"candidatas": len(candidatas), **dict(cont), "descartes": dict(descartes)}


async def registrar_resultados(negocio_id: str, config: ConfigSC, ahora: datetime) -> dict:
    """Registra `exp_solo_clic_resultado` (uno por horizonte: 24 h y 72 h) para los eventos de sombra de esta época cuyo
    horizonte ya se cumplió. Append-only (un EventoLead no se actualiza): el desenlace se congela al momento de cumplirse el
    horizonte. IDEMPOTENTE por (conversación, época, horizonte). Solo lectura de mensajes; no envía nada."""
    registrados = 0
    async with async_session() as session:
        sombras = (await session.execute(
            select(EventoLead.conversation_id, EventoLead.payload).where(
                EventoLead.negocio_id == negocio_id, EventoLead.tipo == EVENTO_EXP_SOLO_CLIC_SOMBRA,
                EventoLead.creado >= ahora - timedelta(days=DIAS_BUSQUEDA_RESULTADOS),
            )
        )).all()
        sombras = [(c, p) for c, p in sombras if isinstance(p, dict) and p.get("epoca") == config.epoca]
        if not sombras:
            return {"resultados_registrados": 0}
        hechos = {
            (conv, payload.get("horizonte_h")) for conv, payload in (await session.execute(
                select(EventoLead.conversation_id, EventoLead.payload).where(
                    EventoLead.negocio_id == negocio_id, EventoLead.tipo == EVENTO_EXP_SOLO_CLIC_RESULTADO,
                    EventoLead.conversation_id.in_([c for c, _ in sombras]),
                )
            )).all() if isinstance(payload, dict) and payload.get("epoca") == config.epoca
        }
    for conversation_id, sombra in sombras:
        ancla = _de_iso(sombra.get("ancla_en"))
        if ancla is None:
            continue
        for horizonte in HORIZONTES_RESULTADO_H:
            if (conversation_id, horizonte) in hechos or ahora < ancla + timedelta(hours=horizonte):
                continue
            try:
                async with async_session() as session:
                    conversation = await session.get(Conversation, conversation_id)
                    contact = await session.get(Contact, conversation.contact_id) if conversation else None
                    if conversation is None or contact is None:
                        continue
                    datos = await desenlace(session, conversation, contact.telefono, ancla, horizonte)
                    payload = {
                        "version": 1, "epoca": config.epoca, "brazo": sombra.get("brazo"), "ancla_en": sombra.get("ancla_en"),
                        **datos, "observado_en": iso_utc(ahora),
                    }
                    session.add(EventoLead(
                        conversation_id=conversation_id, negocio_id=negocio_id, opportunity_id=None,
                        tipo=EVENTO_EXP_SOLO_CLIC_RESULTADO, autor=None, payload=payload,
                        descripcion=f"Experimento solo clic: desenlace a {horizonte} h (respondió: {'sí' if datos['respondio'] else 'no'})"[:300],
                    ))
                    await session.commit()
                    registrados += 1
            except Exception:  # noqa: BLE001
                logger.exception("solo_clic: no se pudo registrar el desenlace (se reintenta en la próxima corrida)")
    return {"resultados_registrados": registrados}


async def procesar_negocio(negocio_id: str, ahora: datetime | None = None) -> dict:
    """Una corrida de la sombra para UN negocio. Con el experimento apagado no hace nada (una lectura de configuración)."""
    ahora = ahora or datetime.utcnow()
    config = await leer_config(negocio_id)
    resumen: dict = {"modo": config.modo}
    if config.modo == MODO_APAGADO:
        return resumen
    ctx = await contexto_de_negocio(negocio_id, ahora)
    rangos = await _rangos_de_atencion_por_dia(negocio_id)
    resumen["cohorte"] = await registrar_cohorte(negocio_id, config, ahora, rangos, ctx)
    resumen.update(await registrar_resultados(negocio_id, config, ahora))
    return resumen


async def ejecutar_sombra(ahora: datetime | None = None) -> dict:
    """Todas las empresas activas. Un negocio con problemas no frena a los demás. Devuelve {negocio_id: resumen}."""
    resultados: dict = {}
    for negocio in await listar_negocios(solo_activos=True):
        try:
            resultados[negocio["id"]] = await procesar_negocio(negocio["id"], ahora)
        except Exception as e:  # noqa: BLE001
            logger.exception("solo_clic: falló la sombra del negocio %s", negocio["id"])
            resultados[negocio["id"]] = {"error": f"{type(e).__name__}: {str(e)[:120]}"}
    return resultados
