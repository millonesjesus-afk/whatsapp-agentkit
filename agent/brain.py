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
import json
import time
import yaml
import logging
from anthropic import AsyncAnthropic
from dotenv import load_dotenv

from agent.tools import obtener_contexto_relevante, obtener_estado_horario_atencion, formatear_producto
from agent.memory import obtener_campana_por_nombre, obtener_configuracion
from agent.campanas import resolver_promo, resolver_familia_promo, obtener_codigos_promocionales_activos

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


async def obtener_system_prompt(modo: str) -> str:
    """Resuelve qué system prompt usar según el modo del canal:
    - "pruebas": siempre el de config/prompts.yaml, tal cual está desplegado
      — así se puede probar un cambio de Gabi en el número de pruebas apenas
      se hace un deploy, sin esperar nada más.
    - "produccion": el prompt PROMOVIDO manualmente desde el panel (guardado
      en la tabla Configuracion, clave "system_prompt_produccion") — no
      cambia solo con un deploy. Si todavía no se promovió nada (instalación
      nueva, o nadie usó el botón de promover aún), cae de vuelta al del
      archivo, para que producción nunca quede con un prompt vacío."""
    prompt_archivo = cargar_system_prompt()
    if modo == "pruebas":
        return prompt_archivo
    return await obtener_configuracion("system_prompt_produccion", prompt_archivo)


def obtener_mensaje_error() -> str:
    """Retorna el mensaje de error configurado en prompts.yaml."""
    config = cargar_config_prompts()
    return config.get("error_message", "Lo siento, estoy teniendo problemas técnicos. Por favor intenta de nuevo en unos minutos.")


def obtener_mensaje_fallback() -> str:
    """Retorna el mensaje de fallback configurado en prompts.yaml."""
    config = cargar_config_prompts()
    return config.get("fallback_message", "Disculpa, no entendí tu mensaje. ¿Podrías reformularlo?")


def obtener_mensaje_no_soportado() -> str:
    """Retorna el mensaje para tipos de contenido que el agente aún no procesa (audio, imagen, etc.)."""
    config = cargar_config_prompts()
    return config.get("mensaje_no_soportado", "Por ahora no puedo procesar ese tipo de mensaje. ¿me lo escribes por texto?")


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


async def _armar_bloques_contexto(mensaje: str, historial: list[dict], lead: dict | None) -> list[str]:
    """Arma los bloques de contexto dinámico (datos del lead + catálogo/base de
    conocimiento) para este turno puntual. Van en el mensaje del usuario, NUNCA
    en el system prompt, para que este último quede idéntico entre llamadas."""
    bloques = []

    # Un modelo de lenguaje no tiene reloj propio: hay que decirle la hora
    # real para que sepa si un asesor está disponible ahora mismo o no.
    estado_horario = obtener_estado_horario_atencion()
    disponibilidad = "DENTRO del horario de atención" if estado_horario["dentro_de_horario"] else "FUERA del horario de atención"
    bloques.append(f"Ahora mismo es {estado_horario['fecha_hora_lima']} — estás {disponibilidad} de los asesores humanos.")

    codigos_propios = set()
    if lead:
        campos_relevantes = ("nombre", "interes", "paso_flujo")
        datos_lead = ", ".join(f"{campo}: {lead[campo]}" for campo in campos_relevantes if lead.get(campo))
        if datos_lead:
            bloques.append(f"Datos ya conocidos de este cliente: {datos_lead}")

        # Si el lead llegó por una campaña con promoción vigente, se prioriza
        # ese producto/precio sobre el catálogo general — es lo que el
        # cliente vio en el anuncio/SMS antes de escribir.
        if lead.get("campana_origen"):
            campana = await obtener_campana_por_nombre(lead["campana_origen"])
            promo = resolver_promo(campana) if campana else None
            if promo:
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
                familia = resolver_familia_promo(campana)
                codigos_propios = {p.get("CODIGO HANA", "") for p in familia}
                otras_variantes = [p for p in familia if p.get("CODIGO HANA") != campana.get("codigo_material")]
                if otras_variantes:
                    variantes_texto = "\n".join(f"- {formatear_producto(p)}" for p in otras_variantes)
                    bloques.append(
                        f"Otras variantes de instalación de ese mismo producto, también a precio "
                        f"promocional de esta campaña (ofrécelas solo si el cliente pregunta por "
                        f"instalación/conexión/combo, no de entrada):\n{variantes_texto}"
                    )

    # Los precios promocionales reservados a una campaña específica (ej. la
    # Terma a S/419.90 de "SMS Terma a gas") no deben aparecer en la búsqueda
    # general del catálogo para clientes que no vinieron de esa campaña —
    # si no, cualquiera que mencione "terma" vería ese precio sin haber
    # llegado por la promo. Esto incluye TODA la familia de combos del
    # producto, no solo el código exacto. Los códigos de LA PROPIA campaña
    # del cliente (si tiene) no se excluyen, para que también salgan con
    # detalle de cuotas en el listado numerado del catálogo.
    codigos_promocionales = await obtener_codigos_promocionales_activos()
    codigos_a_excluir = codigos_promocionales - codigos_propios

    # Se incluyen los últimos mensajes del cliente (no solo el actual) para no
    # perder el contexto en preguntas de seguimiento como "¿y en 12 cuotas?".
    # También se incluye lead.interes: si el cliente mencionó "terma" al inicio
    # de la conversación y luego pasaron varios turnos (nombre, cantidad de
    # personas, etc.), la palabra clave puede salir de la ventana de mensajes
    # recientes — lead.interes persiste el tema durante toda la conversación.
    mensajes_previos = [m["content"] for m in historial if m["role"] == "user"][-2:]
    interes_lead = [lead["interes"]] if lead and lead.get("interes") else []
    contexto = obtener_contexto_relevante(
        " ".join(interes_lead + mensajes_previos + [mensaje]), excluir_codigos=codigos_a_excluir
    )
    if contexto:
        bloques.append(f"Contexto relevante del catálogo/base de conocimiento:\n{contexto}")

    return bloques


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
        respuesta = (datos.get("respuesta") or "").strip()
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
        return respuesta, False, confianza, razon

    except Exception as e:
        logger.error(f"Error Claude API (protocolo de confianza): {e}")
        return obtener_mensaje_error(), True, None, None


async def generar_respuesta(
    mensaje: str, historial: list[dict], lead: dict | None = None, modo: str = "produccion",
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

    Returns:
        Tupla (texto_respuesta, hubo_error, confianza, razon). hubo_error=True
        solo cuando la llamada a Claude falló (para que main.py pueda
        escalar a un asesor tras fallas técnicas repetidas). confianza y
        razon son None en modo "produccion" (protocolo todavía no
        activo ahí) o si hubo_error — nunca se inventan ni se infieren.
    """
    # Si el mensaje está vacío, usar fallback (mensajes cortos como "5" o "sí" son válidos)
    if not mensaje or not mensaje.strip():
        return obtener_mensaje_fallback(), False, None, None

    system_prompt = await obtener_system_prompt(modo)
    bloques_contexto = await _armar_bloques_contexto(mensaje, historial, lead)

    # Construir mensajes para la API. Claude solo acepta los roles "user" y
    # "assistant" — los mensajes que escribió un asesor humano (guardados con
    # role="asesor" para distinguirlos en el panel) se mapean a "assistant",
    # ya que para el cliente es la misma "voz" del negocio.
    mensajes_historial = [
        {"role": "assistant" if m["role"] == "asesor" else m["role"], "content": m["content"]}
        for m in historial
    ]

    if modo == "pruebas":
        mensaje_para_claude = _delimitar_contexto_y_mensaje(bloques_contexto, mensaje)
        mensajes = mensajes_historial + [{"role": "user", "content": mensaje_para_claude}]
        return await _generar_respuesta_protocolo_confianza(system_prompt, mensajes)

    # modo == "produccion": comportamiento sin cambios respecto a antes de
    # esta sub-etapa — texto libre, sin tools, sin delimitación estructural
    # ni prompt caching, hasta que se decida promover el protocolo nuevo.
    mensaje_para_claude = mensaje
    if bloques_contexto:
        mensaje_para_claude = "\n\n".join(bloques_contexto) + f"\n\nMensaje del cliente: {mensaje}"
    mensajes = mensajes_historial + [{"role": "user", "content": mensaje_para_claude}]

    try:
        response = await client.messages.create(
            model=MODELO_PRINCIPAL,
            max_tokens=1024,
            system=system_prompt,
            messages=mensajes
        )

        respuesta = response.content[0].text
        logger.info(f"Respuesta generada ({response.usage.input_tokens} in / {response.usage.output_tokens} out)")
        return respuesta, False, None, None

    except Exception as e:
        logger.error(f"Error Claude API: {e}")
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
