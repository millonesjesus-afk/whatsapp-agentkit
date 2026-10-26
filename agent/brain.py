# agent/brain.py — Cerebro del agente: conexión con Claude API
# Generado por AgentKit

"""
Lógica de IA del agente. Lee el system prompt de prompts.yaml, agrega
contexto relevante del catálogo/base de conocimiento y genera respuestas
usando la API de Anthropic Claude.

Implementa el AI Orchestrator (AI Architecture Sec.1) — no como una clase
separada, sino como las 5 responsabilidades ya distribuidas entre estas
funciones: recuperación de contexto (_armar_bloques_contexto),
construcción del prompt (_delimitar_contexto_y_mensaje), invocación del
modelo y emisión de confianza (_generar_respuesta_protocolo_confianza), y
registro de inferencias (log estructurado dentro de esa misma función).
`ServicioInteligencia` (Backend Architecture) es lo único que invoca este
módulo desde fuera del dominio de AI.
"""

import os
import re
import json
import time
import yaml
import logging
from anthropic import AsyncAnthropic
from dotenv import load_dotenv

from agent.tools import (
    obtener_contexto_relevante, obtener_estado_horario_atencion, formatear_producto,
    obtener_tasas_financiamiento,
)
from agent.memory import (
    obtener_campana_por_nombre, obtener_configuracion, obtener_identidad_agente, obtener_negocio,
    obtener_conversation_activa_de_telefono, obtener_estado_calificacion,
)
from agent.campanas import resolver_promo, resolver_familia_promo, obtener_codigos_promocionales_activos
from agent import circuito_ia, formato_whatsapp, contexto_anuncio, calificacion_guiada
from agent.origen_conversacion import origen_de_conversacion
from agent import calendario_negocio as cal_negocio

load_dotenv()
logger = logging.getLogger("agentkit")

# Cliente de Anthropic — timeout y reintentos explícitos (DevOps Architecture,
# Decisión local: toda llamada externa debe tener timeout explícito y al menos
# un reintento con backoff, en vez de depender de los defaults implícitos del
# SDK). 30s alcanza de sobra para una respuesta conversacional; una llamada
# colgada más que eso bloquea el mensaje de WhatsApp que depende de ella.
client = AsyncAnthropic(api_key=os.getenv("ANTHROPIC_API_KEY"), timeout=30.0, max_retries=2)

MODELO_PRINCIPAL = "claude-sonnet-4-6"
MODELO_EXTRACCION = "claude-haiku-4-5-20251001"

# Vocabulario del protocolo de confianza — MPX Cap. 2, heredado sin
# redefinir por Backend/AI Architecture. AI Architecture Sec.6: si el
# modelo no puede emitir confianza válida en una respuesta dada, el caso
# se trata como Baja por defecto (fail-safe hacia el humano).
CONFIANZA_ALTA = "Alta"
CONFIANZA_REQUIERE_VALIDACION = "Requiere validación"
CONFIANZA_BAJA = "Baja"
NIVELES_CONFIANZA = [CONFIANZA_ALTA, CONFIANZA_REQUIERE_VALIDACION, CONFIANZA_BAJA]

# AI Architecture Sec.6/Sec.1 (AI Orchestrator, "Emisión de confianza"):
# la llamada principal debe retornar el texto de respuesta y la señal de
# confianza en la misma inferencia, con salida estructurada forzada
# (Backend Architecture, Decisión local) — nunca texto libre a parsear.
_HERRAMIENTA_PROTOCOLO_CONFIANZA = {
    "name": "responder_con_confianza",
    "description": (
        "Responde al cliente y emite un nivel de confianza sobre esa "
        "respuesta, según el protocolo de confianza de Maiek AI."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "respuesta": {
                "type": "string",
                "description": "La respuesta para el cliente, en español, siguiendo el system prompt.",
            },
            "confianza": {
                "type": "string",
                "enum": NIVELES_CONFIANZA,
                "description": (
                    "Alta: la respuesta es correcta y completa con la información disponible. "
                    "Requiere validación: la respuesta es razonable pero un asesor debería "
                    "revisarla (ambigüedad, información incompleta, o el cliente pide algo fuera "
                    "de lo usual). Baja: no hay información suficiente o confiable para responder "
                    "bien — un especialista humano debe tomar la conversación."
                ),
            },
            "razon": {
                "type": "string",
                "description": "Justificación breve (una oración) de por qué se emitió ese nivel de confianza.",
            },
        },
        "required": ["respuesta", "confianza", "razon"],
    },
}

# Tipos de producto que puede identificar la extracción de datos del lead —
# basado en las categorías reales del catálogo (columna SUB TIPO de
# lista_precios_canales_propios.csv), acotado a lo que un cliente pregunta
# más seguido. "otro" cubre lo que no calza (microondas, licuadora, etc.)
TIPOS_PRODUCTO = [
    "terma", "secadora", "cocina", "horno", "encimera", "lavadora",
    "campana", "refrigeradora", "microondas", "frigobar", "licuadora", "otro",
]


def cargar_config_prompts() -> dict:
    """Lee toda la configuración desde config/prompts.yaml."""
    try:
        with open("config/prompts.yaml", "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except FileNotFoundError:
        logger.error("config/prompts.yaml no encontrado")
        return {}


def cargar_system_prompt() -> str:
    """Lee el system prompt desde config/prompts.yaml — la versión "de
    pruebas": es la que corre apenas se despliega un cambio, sin pasar por
    ninguna aprobación. Se mantiene 100% estático entre llamadas (sin datos
    dinámicos del turno) para poder aprovechar prompt caching más adelante
    si el volumen lo justifica."""
    config = cargar_config_prompts()
    return config.get("system_prompt", "Eres un asistente útil. Responde en español.")


async def obtener_system_prompt(modo: str, negocio_id: str | None = None) -> str:
    """Resuelve qué system prompt usar según el modo del canal Y el Negocio
    de ese canal:
    - "pruebas": siempre el de config/prompts.yaml, tal cual está desplegado
      — así se puede probar un cambio de Gabi en el número de pruebas apenas
      se hace un deploy, sin esperar nada más. Sin cambios de Gate 4.2: es
      un mecanismo de staging pre-deploy, no de identidad por Negocio, y no
      había evidencia de que debiera cambiar.
    - "produccion": Gate 4.2 (cierre de la Decisión Pendiente 1/P0 de Gate
      4.1) — si el Negocio de este canal ya tiene una `IdentidadAgente`
      migrada (`codigo="gabi"`), usa su `configuracion_negocio` (hoy, para
      Cálidda, el mismo texto que ya corría en producción — ver
      `tests/test_gate42_identidad_agente.py`, comparación de igualdad
      exacta). Si el Negocio todavía no tiene identidad migrada, cae al
      mecanismo anterior (`Configuracion["system_prompt_produccion"]`,
      global de plataforma, con el archivo como último fallback) — ningún
      Negocio sin migrar cambia de comportamiento por este Gate.

      Gate 4.3 — activación controlada: si `identidad.usa_patron_estructural`
      es True, en vez de devolver `configuracion_negocio` verbatim, devuelve
      `ensamblar_system_prompt(_reducir_texto_legacy_calidda(configuracion_negocio))`
      — patrón estructural + configuración de negocio ensamblados. Default
      `False` (columna nueva, ver `IdentidadAgente`): ningún Negocio existente
      cambia de comportamiento solo por esta migración de esquema. Revertir
      es un solo campo (`activar_patron_estructural(negocio_id, False)`),
      nunca requiere tocar `configuracion_negocio` ni ningún otro dato."""
    prompt_archivo = cargar_system_prompt()
    if modo == "pruebas":
        return prompt_archivo
    if negocio_id is not None:
        identidad = await obtener_identidad_agente(negocio_id)
        if identidad is not None:
            if identidad.get("usa_patron_estructural"):
                return ensamblar_system_prompt(_reducir_texto_legacy_calidda(identidad["configuracion_negocio"]))
            return identidad["configuracion_negocio"]
    return await obtener_configuracion("system_prompt_produccion", prompt_archivo)


# -- GATE 4.3 (Decision Pendiente 2 de Gate 4.1, migracion controlada) --
# -- CORREGIDO tras revision del usuario (dos hallazgos, ver mas abajo) --
#
# Patron estructural de Gabi, reutilizable por cualquier Negocio sobre
# MAIEK AI Platform -- vive en CODIGO (Gate 4.2 instruccion 2: "ESTRUCTURAL:
# debe permanecer controlado por codigo/patron de producto", no editable via
# panel).
#
# v1 (primera pasada de Gate 4.3) extraia 3 secciones TEXTUALMENTE sin
# reescribir nada -- pero eso dejo dos problemas reales, encontrados en
# revision del usuario:
#
#   1. "Uso del contexto" mencionaba "Gaso+" por nombre -- informacion
#      especifica de Calidda colada en lo que debia ser 100% generico.
#      CORREGIDO: "de la base de conocimiento de Gaso+." -> "de la base
#      de conocimiento del negocio." -- sustitucion minima, el mismo
#      significado exacto (de que fuente sacar el contexto), sin el
#      nombre de marca. Esta SI es una edicion de texto (no solo
#      extraccion) -- ocurre UNICAMENTE en esta constante (arquitectura
#      paralela/inactiva), nunca en config/prompts.yaml ni en
#      IdentidadAgente.configuracion_negocio de Calidda.
#
#   2. El horario literal de Calidda vivia dentro de "Cuando derivar a
#      un asesor humano" -- una seccion que YA se clasificaba como
#      configuracion-de-negocio (nunca estuvo en esta constante), pero
#      mezclaba dos cosas de naturaleza distinta: el DATO (el rango de
#      horas, especifico de Calidda, ya representado estructuralmente
#      en HorarioAtencion desde Gate 4.2) y el PRINCIPIO (que decirle
#      al cliente segun si es dentro/fuera de horario -- generico,
#      valido para cualquier Negocio con cualquier horario). CORREGIDO:
#      se separaron. El DATO literal ("Horario de atencion... Lunes a
#      Sabado de 8:00am a 7:00pm.") se QUEDA en la configuracion de
#      negocio de Calidda, sin tocar -- sigue siendo necesario para que
#      Gabi pueda responder directamente si un cliente pregunta el
#      horario (el contexto dinamico de HorarioAtencion, inyectado cada
#      turno via agent/tools.py, solo dice si AHORA esta dentro/fuera,
#      no el rango completo -- perderlo seria una perdida real de
#      funcionalidad, no solo una reorganizacion). El PRINCIPIO (las 2
#      reglas "si estas dentro/fuera, di X/Y") se movio, TEXTUALMENTE
#      sin reescribir una palabra, a esta constante, bajo un titulo
#      nuevo ("## Disponibilidad del asesor humano segun horario") --
#      titulo que no existia en el original, necesario para que el
#      fragmento reubicado sea una seccion valida y no quede huerfano.
#
# Verificacion exhaustiva de la separacion (ver tests/test_gate43_separacion_prompt.py):
# el multiset de caracteres NO-whitespace de (config-de-negocio +
# patron-estructural) es IDENTICO al de (baseline + las 2 sustituciones
# documentadas arriba) -- ninguna otra diferencia, ni una letra.
#
# INACTIVO A PROPOSITO: obtener_system_prompt() (mas abajo) NO usa esta
# constante todavia -- Calidda sigue sirviendose desde su
# IdentidadAgente.configuracion_negocio tal cual, sin pasar por
# ensamblar_system_prompt(). Activarlo es una decision separada, posterior
# a este Gate.
PATRON_ESTRUCTURAL_AGENTE = '## Reglas de estilo (síguelas siempre)\n- Mensajes cortos: máximo 2 o 3 párrafos por respuesta.\n- Nunca envíes bloques largos de texto.\n- Haz UNA SOLA pregunta por mensaje — nunca combines dos preguntas distintas\n  en la misma respuesta (ej. nombre + necesidad), aunque te parezcan\n  relacionadas. Espera la respuesta a la primera antes de hacer la segunda.\n- Antes de preguntar algo, revisa el historial de la conversación: si ya\n  hiciste esa pregunta antes y el cliente respondió otra cosa (sin\n  contestarla), retómala de forma natural en vez de repetirla con las\n  mismas palabras — nunca hagas la misma pregunta dos veces seguidas.\n- Usa emojis con moderación (👋😊✅), solo cuando aporten cercanía.\n- Llama al cliente por su nombre en cuanto lo conozcas por la conversación.\n- Nunca inventes promociones, precios o políticas que no estén en tu información.\n- Si no conoces una respuesta, dilo con honestidad y deriva al asesor.\n\n## Uso del contexto que se te proporciona\nAntes del mensaje del cliente puede incluirse una sección "Contexto relevante" con\ninformación del catálogo de productos o de la base de conocimiento del negocio. Básate\nÚNICAMENTE en ese contexto para dar precios, cuotas o condiciones específicas. Si el\ncontexto no incluye lo que el cliente pregunta, no inventes: dilo y deriva al asesor si\ncorresponde.\n\n## Disponibilidad del asesor humano segun horario\n- Si estás dentro de ese horario, indica que un asesor continuará la conversación en breve.\n- Si estás fuera de ese horario, dilo con claridad e indica que un asesor te contactará\n  apenas se reinicie el horario de atención.\n\n## Reglas de comportamiento\n- SIEMPRE responde en español.\n- Mantén las respuestas concisas pero útiles.\n- Si el cliente parece frustrado, muestra empatía antes de resolver.\n'


def ensamblar_system_prompt(configuracion_negocio: str) -> str:
    """Ensamblador determinista (Gate 4.3): configuracion especifica del
    Negocio + patron estructural compartido. Misma entrada -> misma salida
    siempre, sin aleatoriedad ni dependencia de tiempo.

    El patron estructural va AL FINAL, no intercalado como en el prompt
    monolitico original -- es la unica forma de separar fisicamente sin
    inventar una posicion distinta para cada regla. Justificacion: son
    reglas de comportamiento/estilo que un LLM sigue independientemente de
    su posicion en el prompt (a diferencia de una narrativa paso a paso,
    que si depende del orden) -- y colocarlas al final las deja como
    refuerzo final, un patron de prompting razonable, no arbitrario.

    NO se usa todavia en el flujo real (ver obtener_system_prompt arriba,
    que sigue leyendo `IdentidadAgente.configuracion_negocio` directo) --
    activacion pendiente de aprobacion separada, post Gate 4.3."""
    return f"{configuracion_negocio.rstrip()}\n\n{PATRON_ESTRUCTURAL_AGENTE.strip()}"


# Fragmento reubicado (Gate 4.3, correccion) -- el PRINCIPIO de que decir
# segun el horario, extraido de "Cuando derivar a un asesor humano". Vive
# como constante propia (no solo inline en la funcion de abajo) para que
# el test de equivalencia pueda verificarlo por separado del resto del
# patron estructural.
_FRAGMENTO_PRINCIPIO_HORARIO = (
    "- Si est\u00e1s dentro de ese horario, indica que un asesor continuar\u00e1 la conversaci\u00f3n en breve.\n"
    "- Si est\u00e1s fuera de ese horario, dilo con claridad e indica que un asesor te contactar\u00e1\n"
    "  apenas se reinicie el horario de atenci\u00f3n.\n"
)
# Version ORIGINAL de 'Uso del contexto' (con 'Gaso+'), usada SOLO como
# clave de busqueda/remocion en _reducir_texto_legacy_calidda -- nunca se
# muestra a Gabi asi, la version generica (sin 'Gaso+') es la que vive en
# PATRON_ESTRUCTURAL_AGENTE arriba.
_USO_DEL_CONTEXTO_ORIGINAL_CALIDDA = '## Uso del contexto que se te proporciona\nAntes del mensaje del cliente puede incluirse una sección "Contexto relevante" con\ninformación del catálogo de productos o de la base de conocimiento de Gaso+. Básate\nÚNICAMENTE en ese contexto para dar precios, cuotas o condiciones específicas. Si el\ncontexto no incluye lo que el cliente pregunta, no inventes: dilo y deriva al asesor si\ncorresponde.\n\n'


def _reducir_texto_legacy_calidda(texto_completo: str) -> str:
    """Reconstruye la configuracion-de-negocio de Calidda a partir de su
    prompt monolitico actual (`IdentidadAgente.configuracion_negocio`,
    intacto desde Gate 4.2), quitando
    (textualmente) los 2 bloques completos que pasaron a
    PATRON_ESTRUCTURAL_AGENTE sin cambios ("Reglas de estilo", "Reglas de
    comportamiento"), el bloque "Uso del contexto" en su forma ORIGINAL
    (con "Gaso+" -- la version generica solo existe en
    PATRON_ESTRUCTURAL_AGENTE, nunca en el texto legacy de Calidda), MAS
    el fragmento de principio de horario extraido de "Cuando derivar"
    (correccion tras revision del usuario). Conserva intacta la oracion
    literal del horario -- es informacion especifica de Calidda, no
    estructural.

    Llamada en vivo desde `obtener_system_prompt` (Gate 4.3, activacion
    controlada) cuando `usa_patron_estructural=True` -- ya NO es solo un
    helper de migracion. Especifica del formato legacy de Calidda (busca
    los bloques EXACTOS que su prompt monolitico contenia); un Negocio
    nuevo, cuya `configuracion_negocio` se escribe desde el principio sin
    esos bloques adentro, nunca pasa por esta funcion."""
    import re as _re

    bloques_verbatim = {"## Reglas de estilo (s\u00edguelas siempre)", "## Reglas de comportamiento"}
    partes = _re.split(r"(?=^## )", texto_completo, flags=_re.MULTILINE)

    encontrados_verbatim = {p.strip() for p in partes if p.strip().split("\n")[0] in {b.split("\n")[0] for b in bloques_verbatim}}
    if len(encontrados_verbatim) != len(bloques_verbatim):
        raise ValueError(
            "_reducir_texto_legacy_calidda: no se encontraron los 2 bloques verbatim "
            "esperados -- no se puede reconstruir de forma segura."
        )
    if _USO_DEL_CONTEXTO_ORIGINAL_CALIDDA not in texto_completo:
        raise ValueError(
            "_reducir_texto_legacy_calidda: 'Uso del contexto' (version original con "
            "'Gaso+') no se encontro en el texto -- no se puede reconstruir de forma segura."
        )
    if _FRAGMENTO_PRINCIPIO_HORARIO not in texto_completo:
        raise ValueError(
            "_reducir_texto_legacy_calidda: el fragmento de principio de horario "
            "no se encontro en el texto -- no se puede reconstruir de forma segura."
        )

    titulos_a_remover = {b.split("\n")[0] for b in bloques_verbatim}
    restantes = [p for p in partes if p.strip().split("\n")[0] not in titulos_a_remover]
    reducido = "".join(restantes)
    reducido = reducido.replace(_USO_DEL_CONTEXTO_ORIGINAL_CALIDDA, "")
    reducido = reducido.replace(_FRAGMENTO_PRINCIPIO_HORARIO, "")
    return reducido.strip() + "\n"


def obtener_mensaje_error() -> str:
    """Retorna el mensaje de error configurado en prompts.yaml."""
    config = cargar_config_prompts()
    return config.get("error_message", "Lo siento, estoy teniendo problemas técnicos. Por favor intenta de nuevo en unos minutos.")


def obtener_mensaje_fallback() -> str:
    """Retorna el mensaje de fallback configurado en prompts.yaml."""
    config = cargar_config_prompts()
    return config.get("fallback_message", "Disculpa, no entendí tu mensaje. ¿Podrías reformularlo?")


_TIPOS_VISUALES_NO_SOPORTADOS = ("image", "video", "sticker")


def obtener_mensaje_no_soportado(tipo: str | None = None) -> str:
    """Mensaje para tipos de contenido que el agente aún no procesa. Hasta
    2026-09-24 era UNO solo ("no puedo escuchar audios") aunque el cliente
    hubiera mandado una foto; ahora se ajusta al tipo, con las tres frases
    editables en prompts.yaml:
      · audio (y sin tipo, por compatibilidad) → `mensaje_no_soportado`
      · imagen, video/GIF, sticker → `mensaje_no_soportado_visual`
      · cualquier otro (documento, tipo desconocido) → `mensaje_no_soportado_otro`"""
    config = cargar_config_prompts()
    if tipo in _TIPOS_VISUALES_NO_SOPORTADOS:
        return config.get(
            "mensaje_no_soportado_visual",
            "Por ahora no puedo ver fotos, videos ni stickers 🙏 ¿me lo escribes por texto?",
        )
    if tipo in (None, "audio"):
        return config.get("mensaje_no_soportado", "Por ahora no puedo escuchar audios 🙏 ¿me lo escribes por texto?")
    return config.get(
        "mensaje_no_soportado_otro",
        "Por ahora no puedo abrir ese tipo de mensaje 🙏 ¿me lo escribes por texto?",
    )


def obtener_mensaje_error_escalado() -> str:
    """Retorna el mensaje cuando, tras fallas técnicas repetidas, se escala a un asesor humano."""
    config = cargar_config_prompts()
    return config.get(
        "error_escalado_message",
        "Sigo con problemas técnicos, ya te conecto con un asesor. También puedes llamarnos al 614-9002.",
    )


def obtener_mensaje_escalado_por_confianza() -> str:
    """Retorna el mensaje cuando el protocolo de confianza escala
    automáticamente a un asesor humano (confianza "Baja") — distinto del
    mensaje de fallas técnicas: acá la IA respondió con éxito, pero
    decidió que la conversación necesita un especialista."""
    config = cargar_config_prompts()
    return config.get(
        "confianza_baja_escalado_message",
        "Quiero asegurarme de darte la mejor atención posible — ya te conecto con un especialista "
        "de nuestro equipo. También puedes llamarnos al 614-9002.",
    )


def obtener_mensaje_derivacion(
    dentro_de_horario: bool, proxima_apertura: str | None = None, motivo: str | None = None,
) -> str:
    """Aviso al cliente cuando el sistema lo derivó a un asesor pero la
    respuesta de Gabi no lo dijo (red de seguridad determinista de
    agent/main.py — el prompt lo pide, pero un LLM no lo garantiza).

    Calendario de negocio (2026-10-12): fuera de horario, si se conoce la próxima atención
    (`proxima_apertura`, ej. "mañana a las 8:00 a. m." o "el viernes 9 a las 8:00 a. m.") el aviso dice la hora
    exacta en que se reinicia el horario, y `motivo` (ej. "hoy es feriado: Combate de Angamos") la razón. No promete
    plazos: no dice cuánto tardará el asesor, solo cuándo vuelve el equipo. Si el texto está configurado en
    prompts.yaml (`derivacion_fuera_horario_message`) manda esa configuración, que puede usar `{proxima_apertura}`."""
    config = cargar_config_prompts()
    if dentro_de_horario:
        return config.get(
            "derivacion_dentro_horario_message",
            "Te estoy derivando con un asesor comercial 😊 En breve continuará la conversación contigo.",
        )
    if proxima_apertura:
        configurado = config.get("derivacion_fuera_horario_message")
        if configurado:
            return configurado.replace("{proxima_apertura}", proxima_apertura)
        razon = f" ({motivo})" if motivo else ""
        return (
            f"Te estoy derivando con un asesor comercial 😊 Ahora estamos fuera del horario de atención{razon}; "
            f"nuestro equipo vuelve a atender {proxima_apertura} y apenas se reinicie te contactará."
        )
    return config.get(
        "derivacion_fuera_horario_message",
        "Te estoy derivando con un asesor comercial 😊 Ahora estamos fuera del horario de atención, "
        "pero te contactará apenas se reinicie.",
    )


# Modo sin IA (Fase 1) — mensajes AUTOMÁTICOS (sin tokens) para cuando la IA no está disponible
# y el caso se deriva a una persona. Editables en prompts.yaml; estos son solo el respaldo si la
# clave falta. NUNCA mencionan IA, tokens ni créditos: el cliente solo sabe que lo atenderá un
# asesor. Ojo: estos textos no renuevan la ventana de 24 h de WhatsApp (solo la abre el último
# mensaje del CLIENTE), así que no sirven para "reabrir" una conversación.
_SIN_IA_POR_DEFECTO = {
    "dentro_horario": (
        "¡Hola{nombre}! 👋 Gracias por escribirnos. Te estoy transfiriendo con un asesor de nuestro equipo, "
        "que te atenderá por este mismo chat en unos minutos. 😊"
    ),
    "fuera_horario": (
        "¡Hola{nombre}! 👋 Gracias por escribirnos. Te transferí con un asesor y te atenderá en nuestro "
        "horario de atención ({horario}). Si prefieres, también puedes llamarnos al 614-9002."
    ),
    "fin_de_semana": (
        "¡Hola{nombre}! 👋 Gracias por escribirnos. Te transferí con un asesor y te atenderá el {dia} "
        "desde las {hora}. Si prefieres, también puedes llamarnos al 614-9002."
    ),
}
TIPOS_MENSAJE_SIN_IA = tuple(_SIN_IA_POR_DEFECTO)


def obtener_mensaje_sin_ia(
    tipo: str, nombre: str | None = None, *, horario: str | None = None, dia: str | None = None, hora: str | None = None,
) -> str:
    """Texto fijo del modo sin IA. `tipo`: "dentro_horario" | "fuera_horario" |
    "fin_de_semana". `{nombre}` queda como ", Nombre" (primer nombre) solo si el lead
    tiene nombre; `{horario}`, `{dia}` y `{hora}` vienen del horario real del negocio.
    Se reemplaza a mano (no con str.format) para que una llave suelta en el YAML no
    rompa el envío."""
    if tipo not in _SIN_IA_POR_DEFECTO:
        raise ValueError(f"Tipo de mensaje sin IA desconocido: {tipo!r}")
    config = cargar_config_prompts()
    texto = config.get(f"sin_ia_{tipo}_message") or _SIN_IA_POR_DEFECTO[tipo]
    primer_nombre = (nombre or "").strip().split(" ")[0][:30]
    reemplazos = {
        "{nombre}": f", {primer_nombre}" if primer_nombre else "",
        "{horario}": horario or "nuestro horario de atención",
        "{dia}": dia or "próximo día hábil",
        "{hora}": hora or "la apertura",
    }
    for marca, valor in reemplazos.items():
        texto = texto.replace(marca, valor)
    # "8:00 a. m." ya termina en punto: sin esto, "…desde las {hora}." quedaría "a. m..".
    return re.sub(r"(?<!\.)\.\.(?!\.)", ".", texto)


# Auditoría de 400 chats (2026-10-26): el 5 % de los mensajes de Gabi hacía dos o más preguntas a la vez, y lo que más hace
# responder al cliente es cerrar con UNA pregunta clara. Va en los bloques dinámicos (no en el system prompt) para no romper
# la caché del prompt.
REGLA_FORMA_DEL_MENSAJE = (
    "Forma de tu respuesta: haz como máximo UNA pregunta, al final del mensaje (si necesitas dos datos, pide uno y el otro "
    "después). Frases cortas y sin repetir lo que ya dijiste en esta conversación."
)


async def _armar_bloques_contexto(
    mensaje: str, historial: list[dict], lead: dict | None, negocio_id: str | None,
) -> list[str]:
    """Arma los bloques de contexto dinámico (datos del lead + catálogo/base de
    conocimiento) para este turno puntual. Van en el mensaje del usuario, NUNCA
    en el system prompt, para que este último quede idéntico entre llamadas."""
    bloques = []

    # Un modelo de lenguaje no tiene reloj propio: hay que decirle la hora
    # real para que sepa si un asesor está disponible ahora mismo o no.
    # Gate 4.2: horario resuelto por negocio_id (antes hardcodeado, sin
    # relación con el Negocio del canal por el que llegó el mensaje).
    estado_horario = await obtener_estado_horario_atencion(negocio_id)
    disponibilidad = "DENTRO del horario de atención" if estado_horario["dentro_de_horario"] else "FUERA del horario de atención"
    bloque_horario = f"Ahora mismo es {estado_horario['fecha_hora_lima']} — estás {disponibilidad} de los asesores humanos."
    if not estado_horario["dentro_de_horario"]:
        # Calendario de negocio (2026-10-12): con el negocio cerrado Gabi también sabe POR QUÉ (feriado, día no laborable…)
        # y CUÁNDO vuelven los asesores, para no decirle al cliente «mañana» un día de feriado.
        motivo = cal_negocio.describir_motivo(estado_horario.get("motivo"), estado_horario.get("nombre"))
        if motivo:
            bloque_horario += f" {motivo[0].upper()}{motivo[1:]}."
        if estado_horario.get("proxima_apertura_texto"):
            bloque_horario += f" Los asesores humanos vuelven a atender {estado_horario['proxima_apertura_texto']}."
    bloques.append(bloque_horario)
    bloques.append(REGLA_FORMA_DEL_MENSAJE)

    codigos_propios = set()
    hay_promo_de_campana = False
    campana_sin_precio = None   # nombre de una campaña cuyo material ya no está en el catálogo
    if lead:
        campos_relevantes = ("nombre", "interes", "paso_flujo")
        datos_lead = ", ".join(f"{campo}: {lead[campo]}" for campo in campos_relevantes if lead.get(campo))
        if datos_lead:
            bloques.append(f"Datos ya conocidos de este cliente: {datos_lead}")

        # Si el lead llegó por una campaña con promoción vigente, se prioriza
        # ese producto/precio sobre el catálogo general — es lo que el
        # cliente vio en el anuncio/SMS antes de escribir.
        if lead.get("campana_origen") and negocio_id is not None:
            campana = await obtener_campana_por_nombre(lead["campana_origen"], negocio_id)
            promo = await resolver_promo(campana, negocio_id) if campana else None
            if campana and not promo and campana.get("codigo_material"):
                campana_sin_precio = campana["nombre"]
            if promo:
                hay_promo_de_campana = True
                detalle = f"Producto: {promo['producto']}"
                if promo.get("precio"):
                    detalle += f", Precio promocional: {promo['precio']}"
                bloques.append(
                    f"Este cliente llegó por la campaña \"{campana['nombre']}\" — "
                    f"ofrécele PRIORITARIAMENTE esta promoción vigente ({detalle}) antes que "
                    f"otras opciones del catálogo, salvo que el cliente pida explícitamente algo distinto."
                )

                # Otras variantes de combo/instalación del MISMO modelo
                # promocionado (ej. sin combo, +conexión, +conexión+combo) —
                # también son parte de la promo de esta campaña, por si el
                # cliente pide una combinación distinta a la del SMS/anuncio.
                familia = await resolver_familia_promo(campana, negocio_id)
                codigos_propios = {p.get("CODIGO HANA", "") for p in familia}
                otras_variantes = [p for p in familia if p.get("CODIGO HANA") != campana.get("codigo_material")]
                if otras_variantes:
                    tea_promo, igv_promo = await obtener_tasas_financiamiento(negocio_id)
                    variantes_texto = "\n".join(
                        f"- {formatear_producto(p, tea_promo, igv_promo)}" for p in otras_variantes
                    )
                    bloques.append(
                        f"Otras variantes de instalación de ese mismo producto, también a precio "
                        f"promocional de esta campaña (ofrécelas solo si el cliente pregunta por "
                        f"instalación/conexión/combo, no de entrada):\n{variantes_texto}"
                    )

    await _agregar_bloques_anuncio(bloques, lead, historial, negocio_id, hay_promo_de_campana, campana_sin_precio)
    await _agregar_bloque_calificacion(bloques, lead, historial, negocio_id, mensaje)

    # Los precios promocionales reservados a una campaña específica (ej. la
    # Terma a S/419.90 de "SMS Terma a gas") no deben aparecer en la búsqueda
    # general del catálogo para clientes que no vinieron de esa campaña —
    # si no, cualquiera que mencione "terma" vería ese precio sin haber
    # llegado por la promo. Esto incluye TODA la familia de combos del
    # producto, no solo el código exacto. Los códigos de LA PROPIA campaña
    # del cliente (si tiene) no se excluyen, para que también salgan con
    # detalle de cuotas en el listado numerado del catálogo.
    codigos_promocionales = await obtener_codigos_promocionales_activos(negocio_id)
    codigos_a_excluir = codigos_promocionales - codigos_propios

    # Se incluyen los últimos mensajes del cliente (no solo el actual) para no
    # perder el contexto en preguntas de seguimiento como "¿y en 12 cuotas?".
    # También se incluye lead.interes: si el cliente mencionó "terma" al inicio
    # de la conversación y luego pasaron varios turnos (nombre, cantidad de
    # personas, etc.), la palabra clave puede salir de la ventana de mensajes
    # recientes — lead.interes persiste el tema durante toda la conversación.
    mensajes_previos = [m["content"] for m in historial if m["role"] == "user"][-2:]
    interes_lead = [lead["interes"]] if lead and lead.get("interes") else []
    # Auditoría puntual post Gate 4.3: `negocio_codigo` (el slug estable,
    # ej. "calidda" — no el `negocio_id` UUID, que difiere por entorno)
    # aísla la base de conocimiento de este Negocio
    # (`knowledge/<codigo>/`) de la de cualquier otro. `None` si el canal
    # no resolvió Negocio — fail-safe, sin contexto en vez de adivinar.
    negocio = await obtener_negocio(negocio_id) if negocio_id is not None else None
    negocio_codigo = negocio["codigo"] if negocio else None
    contexto = await obtener_contexto_relevante(
        " ".join(interes_lead + mensajes_previos + [mensaje]), negocio_id, negocio_codigo,
        excluir_codigos=codigos_a_excluir,
    )
    if contexto:
        bloques.append(f"Contexto relevante del catálogo/base de conocimiento:\n{contexto}")

    return bloques


async def _textos_del_cliente_en_la_conversacion(
    telefono: str, negocio_id: str | None, historial: list[dict], mensaje: str,
) -> list[str]:
    """Lo que el cliente dijo ANTES del mensaje actual, solo en la conversación ACTIVA. El `historial` que llega es el del teléfono
    entero (arrastra las conversaciones anteriores de un cliente que volvió tras un cierre), así que sirve de respaldo únicamente
    si la conversación activa aún no tiene mensajes guardados del cliente."""
    en_conversacion = await calificacion_guiada.historial_de_la_conversacion(telefono, negocio_id)
    guardados = [m["content"] for m in (en_conversacion or []) if m.get("role") == "user"]
    if guardados:
        # el mensaje actual ya está guardado y es el último: se quita para devolver solo lo anterior
        es_el_actual = (not mensaje) or guardados[-1] == mensaje
        return guardados[:-1] if es_el_actual else guardados
    return [m["content"] for m in historial if m.get("role") == "user"]


async def _agregar_bloque_calificacion(
    bloques: list[str], lead: dict | None, historial: list[dict], negocio_id: str | None, mensaje: str = "",
) -> None:
    """Calificación guiada con botones (2026-10-23, `calificacion_guiada_modo`, apagada por defecto): le dice a Claude qué preguntó el
    sistema con botones y qué respondió el cliente (para no repetirlo) y, en el turno anterior a la primera pregunta, que no
    pregunte ni pida datos porque el sistema la hará enseguida. Nunca rompe la respuesta."""
    try:
        if not lead or negocio_id is None or not lead.get("telefono"):
            return
        modo = await calificacion_guiada.obtener_modo(negocio_id)
        if modo != calificacion_guiada.MODO_ACTIVO:
            return
        estado = await obtener_estado_calificacion(lead["telefono"])
        dichos = await _textos_del_cliente_en_la_conversacion(lead["telefono"], negocio_id, historial, mensaje)
        mensajes_cliente = len(dichos) + 1
        va_la_primera = calificacion_guiada.lleva_pregunta_de_gas(lead, estado, mensajes_cliente, modo)
        tipo = await calificacion_guiada.tipo_del_lead(lead["telefono"], lead, negocio_id, estado)
        bloque = calificacion_guiada.bloque_contexto(
            estado, va_la_primera_pregunta=va_la_primera, tipo_producto=tipo,
            pidio_el_precio=calificacion_guiada.pidio_precio(mensaje, *dichos),
            derivado=lead.get("paso_flujo") == "derivado_asesor",
        )
        if bloque:
            bloques.append(bloque)
    except Exception:
        logger.exception("No se pudo armar el contexto de la calificación guiada (se responde sin él)")


async def _agregar_bloques_anuncio(
    bloques: list[str], lead: dict | None, historial: list[dict], negocio_id: str | None,
    hay_promo_de_campana: bool, campana_sin_precio: str | None,
) -> None:
    """Mejora M1 (2026-10-23): que Gabi sepa por qué anuncio entró el cliente y no cite precios sin respaldo en el
    catálogo. Modo `gabi_contexto_anuncio_modo` (apagado / sombra / activo; por defecto sombra = solo registra el log
    `contexto_anuncio`). Solo en los primeros mensajes del cliente. Nunca rompe la respuesta."""
    try:
        if not lead or negocio_id is None or not lead.get("telefono"):
            return
        modo = contexto_anuncio.normalizar_modo(
            await obtener_configuracion(contexto_anuncio.CLAVE_MODO, contexto_anuncio.MODO_POR_DEFECTO, negocio_id)
        )
        if modo == contexto_anuncio.MODO_APAGADO:
            return
        dichos = await _textos_del_cliente_en_la_conversacion(lead["telefono"], negocio_id, historial, "")
        mensajes_cliente = len(dichos) + 1
        if mensajes_cliente > contexto_anuncio.MAXIMO_MENSAJES_CLIENTE:
            return
        conversation = await obtener_conversation_activa_de_telefono(lead["telefono"], negocio_id)
        origen = await origen_de_conversacion(negocio_id, conversation["id"]) if conversation else None
        resumen = contexto_anuncio.resumen_sombra(
            origen, hay_promo_de_campana=hay_promo_de_campana, precio_no_disponible=bool(campana_sin_precio),
        )
        logger.info("contexto_anuncio " + json.dumps({"modo": modo, **resumen}, ensure_ascii=False))
        if modo != contexto_anuncio.MODO_ACTIVO:
            return
        if campana_sin_precio:
            bloques.append(contexto_anuncio.bloque_precio_no_disponible(campana_sin_precio))
        bloque = contexto_anuncio.bloque_anuncio(origen, hay_promo_de_campana=hay_promo_de_campana)
        if bloque:
            bloques.append(bloque)
    except Exception:
        logger.exception("No se pudo armar el contexto del anuncio (se responde sin él)")


def _delimitar_contexto_y_mensaje(bloques_contexto: list[str], mensaje: str) -> str:
    """Delimitación estructural del turno `user` (AI Architecture Sec.3):
    el contexto de confianza (catálogo, promoción, configuración del
    negocio) y el mensaje del cliente deben ser distinguibles entre sí,
    mediante bloques marcados — mitigación directa de prompt injection,
    no una simple preferencia de formato. El contenido dentro de
    <mensaje_cliente> es SIEMPRE contenido no confiable, nunca
    instrucciones (AI Architecture Sec.8)."""
    partes = []
    if bloques_contexto:
        partes.append("<contexto_negocio>\n" + "\n\n".join(bloques_contexto) + "\n</contexto_negocio>")
    partes.append(f"<mensaje_cliente>\n{mensaje}\n</mensaje_cliente>")
    return "\n".join(partes)


async def _generar_respuesta_protocolo_confianza(
    system_prompt: str, mensajes: list[dict],
) -> tuple[str, bool, str | None, str | None]:
    """AI Orchestrator — invocación del modelo con salida estructurada
    forzada (tool-calling) y prompt caching del system prompt estático
    (AI Architecture Sec.1, Sec.7). Única llamada por mensaje: la señal
    de confianza viaja en la misma inferencia que la respuesta
    (Architectural Constraint, máximo 2 llamadas de IA por mensaje)."""
    try:
        response = await client.messages.create(
            model=MODELO_PRINCIPAL,
            max_tokens=1024,
            system=[{"type": "text", "text": system_prompt, "cache_control": {"type": "ephemeral"}}],
            messages=mensajes,
            tools=[_HERRAMIENTA_PROTOCOLO_CONFIANZA],
            tool_choice={"type": "tool", "name": _HERRAMIENTA_PROTOCOLO_CONFIANZA["name"]},
        )

        bloque_tool = next((b for b in response.content if b.type == "tool_use"), None)
        if bloque_tool is None:
            raise ValueError("El modelo no devolvió la herramienta forzada (respuesta sin tool_use)")

        datos = bloque_tool.input
        respuesta = await formato_whatsapp.limpiar_salida_gabi((datos.get("respuesta") or "").strip())
        confianza = datos.get("confianza")
        razon = (datos.get("razon") or "").strip()

        if confianza not in NIVELES_CONFIANZA:
            # Fail-safe hacia el humano (AI Architecture Sec.6) — nunca se
            # infiere ni se recalcula la confianza, pero un valor fuera
            # del vocabulario no puede tratarse como "sin riesgo".
            logger.warning(f"Confianza fuera de vocabulario ('{confianza}') — fail-safe a '{CONFIANZA_BAJA}'")
            confianza = CONFIANZA_BAJA

        if not respuesta:
            return obtener_mensaje_fallback(), False, confianza, razon

        # Registro de inferencias (AI Orchestrator, AI Architecture Sec.1/9):
        # log estructurado con las dos capas de trazabilidad que exige
        # Explainability First — qué vio el modelo (turno user delimitado,
        # ya incluye el contexto de negocio) y qué decidió (confianza,
        # razón, respuesta). Persistencia formal como SugerenciaIA queda
        # diferida a Data Architecture Fase 2 (Execution Plan v1.2, sección 2)
        # — esto es evidencia suficiente para verificar manualmente en esta fase.
        turno_user = mensajes[-1]["content"] if mensajes else None
        logger.info(
            "inferencia_ia "
            + json.dumps(
                {
                    "modelo": MODELO_PRINCIPAL,
                    "prompt_usuario": turno_user,
                    "confianza": confianza,
                    "razon": razon,
                    "respuesta_preview": respuesta[:200],
                    "tokens_in": response.usage.input_tokens,
                    "tokens_out": response.usage.output_tokens,
                    "cache_read_tokens": getattr(response.usage, "cache_read_input_tokens", None),
                },
                ensure_ascii=False,
            )
        )
        circuito_ia.registrar_exito()
        return respuesta, False, confianza, razon

    except Exception as e:
        logger.error(f"Error Claude API (protocolo de confianza): {e}")
        # Modo sin IA: un saldo agotado / tope / credencial inválida abre el circuito al PRIMER
        # error; main.py lo consulta tras `hubo_error` para derivar en vez de mandar el texto
        # técnico. La firma de 4 valores no cambia.
        await circuito_ia.registrar_error(e)
        return obtener_mensaje_error(), True, None, None


async def generar_respuesta(
    mensaje: str, historial: list[dict], lead: dict | None = None, modo: str = "produccion",
    negocio_id: str | None = None,
) -> tuple[str, bool, str | None, str | None]:
    """
    Genera una respuesta usando Claude API.

    Args:
        mensaje: El mensaje nuevo del usuario
        historial: Lista de mensajes anteriores [{"role": "user/assistant", "content": "..."}]
        lead: Datos estructurados ya conocidos del cliente (nombre, interes, paso_flujo)
        modo: "produccion" o "pruebas" — el modo del canal por el que llegó
            este mensaje. Además de decidir qué versión del system prompt
            usar (ver obtener_system_prompt), en modo "pruebas" activa el
            protocolo de confianza con salida estructurada forzada,
            delimitación estructural y prompt caching (Execution Plan
            v1.2, sección 9 — activación gradual antes de promoverlo a
            producción). En modo "produccion" el comportamiento es
            exactamente el mismo que antes de esta sub-etapa: texto libre,
            sin tools.
        negocio_id: Negocio resuelto del Canal por el que llegó el mensaje
            (Gate 5.4, T2) — puede ser None si el webhook no pudo resolver el
            Canal todavía; en ese caso el contexto de campañas/promociones se
            arma vacío (fail-safe), nunca se listan campañas de cualquier
            Negocio.

    Returns:
        Tupla (texto_respuesta, hubo_error, confianza, razon). hubo_error=True
        solo cuando la llamada a Claude falló (para que main.py pueda
        escalar a un asesor tras fallas técnicas repetidas). confianza y
        razon son None en modo "produccion" (protocolo todavía no
        activo ahí) o si hubo_error — nunca se inventan ni se infieren.
    """
    formato_whatsapp.ORIGINAL_ANTES_DE_LIMPIAR.set(None)   # modo sombra: main lo lee tras la llamada
    # Si el mensaje está vacío, usar fallback (mensajes cortos como "5" o "sí" son válidos)
    if not mensaje or not mensaje.strip():
        return obtener_mensaje_fallback(), False, None, None

    system_prompt = await obtener_system_prompt(modo, negocio_id)
    bloques_contexto = await _armar_bloques_contexto(mensaje, historial, lead, negocio_id)

    # Construir mensajes para la API. Claude solo acepta los roles "user" y
    # "assistant" — los mensajes que escribió un asesor humano (guardados con
    # role="asesor" para distinguirlos en el panel) se mapean a "assistant",
    # ya que para el cliente es la misma "voz" del negocio.
    # Formato de WhatsApp (Mejoras de Gabi, Fase 1): Claude imita el `**` que ve en sus propios mensajes
    # anteriores (contagio). Los turnos de Gabi (role "assistant") se limpian EN MEMORIA para este envío a
    # Claude; la base y la lista `historial` original no se tocan. Los del asesor humano no se tocan.
    if await formato_whatsapp.limpieza_activa():
        historial = formato_whatsapp.limpiar_historial_assistant(historial)
    mensajes_historial = [
        {"role": "assistant" if m["role"] == "asesor" else m["role"], "content": m["content"]}
        for m in historial
    ]

    # Prompt caching del historial (2026-09-17, prioridad #1 del usuario tras
    # revisar su consumo real de la API) — hasta acá solo se cacheaba el
    # system prompt (~40% de los tokens de entrada); el otro ~60% es
    # contexto dinámico + HISTORIAL, y el historial se reenviaba entero a
    # precio completo en cada turno, aunque en una conversación larga la
    # mayor parte de él es idéntica de una llamada a la siguiente.
    #
    # Por qué no se rompe con el turno "actual" (armado más abajo,
    # decorado con catálogo/hora — SIEMPRE distinto): guardar_mensaje()
    # nunca persiste esa decoración, solo el texto crudo del cliente — así
    # que un turno decorado en la llamada N aparece sin decorar en la
    # llamada N+1 (ya como "historial"). Poner el breakpoint accá, al FINAL
    # del historial YA GUARDADO (nunca en el turno actual, que se arma
    # después), evita ese problema: desde la llamada N+2 en adelante ese
    # turno se renderiza siempre igual (texto crudo), así que esta posición
    # sí queda estable y cacheable — el "reset" de caché por la decoración
    # ocurre una sola vez por turno, no en cada llamada.
    #
    # Igual que el system prompt: el mínimo cacheable de Sonnet 4.6 es 1024
    # tokens — en conversaciones cortas esto simplemente no llega a cachear
    # (sin error, sin costo extra), no hace daño dejarlo puesto siempre.
    if mensajes_historial:
        ultimo_historial = mensajes_historial[-1]
        mensajes_historial[-1] = {
            "role": ultimo_historial["role"],
            "content": [
                {"type": "text", "text": ultimo_historial["content"], "cache_control": {"type": "ephemeral"}}
            ],
        }

    if modo == "pruebas":
        mensaje_para_claude = _delimitar_contexto_y_mensaje(bloques_contexto, mensaje)
        mensajes = mensajes_historial + [{"role": "user", "content": mensaje_para_claude}]
        return await _generar_respuesta_protocolo_confianza(system_prompt, mensajes)

    # modo == "produccion": texto libre, sin tools, sin delimitación
    # estructural — comportamiento sin cambios respecto a antes de esta
    # sub-etapa, hasta que se decida promover el protocolo nuevo.
    #
    # Prompt caching (2026-09-17, hallazgo del usuario tras revisar su
    # consumo real de la API: "por qué se consumió tan rápido") — este
    # `system_prompt` (la identidad de Gabi + configuración del negocio,
    # ver obtener_system_prompt) es IDÉNTICO en cada mensaje de cada
    # conversación de este Negocio; sin cache_control se reenviaba entero a
    # precio completo en cada turno. `cache_control` acá cachea SOLO ese
    # bloque (system se renderiza antes que `messages` — ver Anthropic,
    # "Render order: tools -> system -> messages"); el contexto dinámico
    # (catálogo/hora/historial, armado en `mensaje_para_claude` más abajo)
    # sigue sin cachearse, porque cambia en cada turno — cachearlo no
    # ahorraría nada y solo pagaría la prima de escritura sin ninguna
    # lectura. Mismo patrón que ya usa `_generar_respuesta_protocolo_
    # confianza` (modo "pruebas") — acá solo se extiende al modo
    # "produccion", que es el que corre el canal real.
    mensaje_para_claude = mensaje
    if bloques_contexto:
        mensaje_para_claude = "\n\n".join(bloques_contexto) + f"\n\nMensaje del cliente: {mensaje}"
    mensajes = mensajes_historial + [{"role": "user", "content": mensaje_para_claude}]

    try:
        response = await client.messages.create(
            model=MODELO_PRINCIPAL,
            max_tokens=1024,
            system=[{"type": "text", "text": system_prompt, "cache_control": {"type": "ephemeral"}}],
            messages=mensajes
        )

        # Se limpia el markdown AQUÍ (en el origen) para que lo que se envía, lo que se guarda en el chat y lo
        # que lee extraer_datos_lead sea el mismo texto (agent/formato_whatsapp.py). Nunca lanza.
        respuesta = await formato_whatsapp.limpiar_salida_gabi(response.content[0].text)
        # cache_read/cache_creation en el log (no solo in/out) — es la única
        # forma de confirmar que el caching de arriba realmente está
        # pegando en producción, no solo que el código no rompió nada.
        logger.info(
            f"Respuesta generada ({response.usage.input_tokens} in / {response.usage.output_tokens} out"
            f" / {getattr(response.usage, 'cache_read_input_tokens', None)} cache_read"
            f" / {getattr(response.usage, 'cache_creation_input_tokens', None)} cache_write)"
        )
        circuito_ia.registrar_exito()
        return respuesta, False, None, None

    except Exception as e:
        logger.error(f"Error Claude API: {e}")
        await circuito_ia.registrar_error(e)  # ver el comentario del protocolo de confianza, arriba
        return obtener_mensaje_error(), True, None, None


async def extraer_datos_lead(mensaje_cliente: str, respuesta_gabi: str, lead_actual: dict | None) -> dict:
    """
    Extrae/actualiza los datos estructurados del cliente (nombre, interés,
    desglose del producto de interés, paso del flujo) a partir del último
    intercambio, usando un modelo económico. Así estos datos no dependen de
    sobrevivir en el historial crudo si este se trunca o se pierde contexto
    entre turnos.
    """
    actual = lead_actual or {}
    prompt = (
        "Datos ya conocidos del cliente (puede haber campos vacíos):\n"
        f"nombre: {actual.get('nombre') or '(desconocido)'}\n"
        f"interes: {actual.get('interes') or '(desconocido)'}\n"
        f"producto_tipo: {actual.get('producto_tipo') or '(desconocido)'}\n"
        f"producto_marca: {actual.get('producto_marca') or '(desconocido)'}\n"
        f"producto_modalidad: {actual.get('producto_modalidad') or '(desconocido)'}\n"
        f"paso_flujo: {actual.get('paso_flujo') or '(desconocido)'}\n\n"
        f"Último mensaje del cliente: {mensaje_cliente}\n"
        f"Respuesta de la asesora: {respuesta_gabi}\n\n"
        "Actualiza estos datos según este intercambio. paso_flujo debe ser uno de: "
        "explorando, comparando_producto, evaluando_financiamiento, derivado_asesor. "
        f"producto_tipo debe ser uno de: {', '.join(TIPOS_PRODUCTO)} (o null si aún no se sabe qué "
        "tipo de producto busca). producto_marca es el nombre de la marca mencionada (ej. Rheem, "
        "Rinnai, LG, Samsung), o null si no se mencionó ninguna. producto_modalidad es \"combo\" si "
        "el cliente pregunta por instalación/ductería/punto de gas junto al producto, \"solo\" si "
        "pregunta solo por el equipo, o null si aún no se sabe. "
        "Responde ÚNICAMENTE un JSON con las claves nombre, interes, producto_tipo, producto_marca, "
        "producto_modalidad, paso_flujo (sin texto adicional, sin bloque de código). Si un dato no "
        "cambia ni se menciona, repite el valor actual (o null si sigue desconocido)."
    )
    try:
        response = await client.messages.create(
            model=MODELO_EXTRACCION,
            max_tokens=200,
            messages=[{"role": "user", "content": prompt}],
        )
        texto = response.content[0].text.strip()
        texto = texto.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        datos = json.loads(texto)
        producto_tipo = datos.get("producto_tipo") or None
        if producto_tipo not in TIPOS_PRODUCTO:
            producto_tipo = None
        producto_modalidad = datos.get("producto_modalidad") or None
        if producto_modalidad not in ("combo", "solo"):
            producto_modalidad = None
        return {
            "nombre": datos.get("nombre") or None,
            "interes": datos.get("interes") or None,
            "producto_tipo": producto_tipo,
            "producto_marca": datos.get("producto_marca") or None,
            "producto_modalidad": producto_modalidad,
            "paso_flujo": datos.get("paso_flujo") or None,
        }
    except Exception as e:
        logger.warning(f"No se pudo extraer datos del lead: {e}")
        await circuito_ia.registrar_error(e)
        return {}


async def generar_resumen_conversacion(historial: list[dict]) -> str:
    """Resumen IA bajo demanda (Copiloto — MAIEK_AI_PRODUCT_PATTERNS.md, Cap. 5,
    primera capacidad activa). Deliberadamente independiente del protocolo de
    confianza (_generar_respuesta_protocolo_confianza): no emite confianza/razon
    ni pasa por tool-calling — es una sola inferencia de lectura, sin decisión
    de negocio que justificar. Usa el modelo económico, igual que
    extraer_datos_lead, porque resumir no necesita el modelo principal.

    Logging estructurado (evento "resumen_ia", mismo criterio que
    "inferencia_ia" del protocolo de confianza) — prerrequisito del Sprint de
    Validación del Copiloto (MAIEK_AI_CONVERSATIONAL_VALIDATION_PLAN.md v1.1):
    sin esto no había ningún rastro de latencia ni de qué se generó, más allá
    de lo que se veía en pantalla en el momento."""
    inicio = time.monotonic()
    if not historial:
        logger.info(
            "resumen_ia "
            + json.dumps(
                {"cantidad_mensajes": 0, "historial_vacio": True, "latencia_ms": 0, "error": None},
                ensure_ascii=False,
            )
        )
        return "Todavía no hay mensajes en esta conversación."

    texto_historial = "\n".join(
        f"{'Cliente' if m['role'] == 'user' else 'Asesor/Gabi'}: {m['content']}"
        for m in historial if m.get("content")
    )
    prompt = (
        "Resumí esta conversación entre un cliente y el equipo comercial (Gabi, la IA, o un asesor "
        "humano) para que un asesor que recién la abre entienda de un vistazo qué pasó, sin tener que "
        "leer todos los mensajes. 3-5 líneas como máximo, en español, tono directo. Incluí: qué busca "
        "el cliente, en qué quedó la conversación, y cualquier dato clave (producto, presupuesto, "
        "urgencia) si se mencionó.\n\n"
        f"Conversación:\n{texto_historial}"
    )
    try:
        response = await client.messages.create(
            model=MODELO_EXTRACCION,
            max_tokens=300,
            messages=[{"role": "user", "content": prompt}],
        )
        resumen = response.content[0].text.strip()
        latencia_ms = round((time.monotonic() - inicio) * 1000)
        logger.info(
            "resumen_ia "
            + json.dumps(
                {
                    "cantidad_mensajes": len(historial),
                    "historial_vacio": False,
                    "latencia_ms": latencia_ms,
                    "resumen_preview": resumen[:300],
                    "tokens_in": response.usage.input_tokens,
                    "tokens_out": response.usage.output_tokens,
                    "error": None,
                },
                ensure_ascii=False,
            )
        )
        return resumen
    except Exception as e:
        latencia_ms = round((time.monotonic() - inicio) * 1000)
        logger.warning(f"No se pudo generar el resumen de la conversación: {e}")
        await circuito_ia.registrar_error(e)
        logger.info(
            "resumen_ia "
            + json.dumps(
                {
                    "cantidad_mensajes": len(historial),
                    "historial_vacio": False,
                    "latencia_ms": latencia_ms,
                    "resumen_preview": None,
                    "error": str(e),
                },
                ensure_ascii=False,
            )
        )
        return "No se pudo generar el resumen — intentá de nuevo en un momento."
