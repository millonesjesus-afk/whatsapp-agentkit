# agent/brain.py — Cerebro del agente: conexión con Claude API
# Generado por AgentKit

"""
Lógica de IA del agente. Lee el system prompt de prompts.yaml, agrega
contexto relevante del catálogo/base de conocimiento y genera respuestas
usando la API de Anthropic Claude.
"""

import os
import json
import yaml
import logging
from anthropic import AsyncAnthropic
from dotenv import load_dotenv

from agent.tools import obtener_contexto_relevante, obtener_estado_horario_atencion, formatear_producto
from agent.memory import obtener_campana_por_nombre, obtener_configuracion
from agent.campanas import resolver_promo, resolver_familia_promo, obtener_codigos_promocionales_activos

load_dotenv()
logger = logging.getLogger("agentkit")

# Cliente de Anthropic
client = AsyncAnthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

MODELO_PRINCIPAL = "claude-sonnet-4-6"
MODELO_EXTRACCION = "claude-haiku-4-5-20251001"

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


async def generar_respuesta(mensaje: str, historial: list[dict], lead: dict | None = None, modo: str = "produccion") -> tuple[str, bool]:
    """
    Genera una respuesta usando Claude API.

    Args:
        mensaje: El mensaje nuevo del usuario
        historial: Lista de mensajes anteriores [{"role": "user/assistant", "content": "..."}]
        lead: Datos estructurados ya conocidos del cliente (nombre, interes, paso_flujo)
        modo: "produccion" o "pruebas" — el modo del canal por el que llegó
            este mensaje, para saber qué versión del system prompt usar (ver
            obtener_system_prompt).

    Returns:
        Tupla (texto_respuesta, hubo_error). hubo_error=True solo cuando la
        llamada a Claude falló (para que main.py pueda escalar a un asesor
        tras fallas técnicas repetidas, sin confundirlo con un fallback normal).
    """
    # Si el mensaje está vacío, usar fallback (mensajes cortos como "5" o "sí" son válidos)
    if not mensaje or not mensaje.strip():
        return obtener_mensaje_fallback(), False

    system_prompt = await obtener_system_prompt(modo)

    bloques_contexto = await _armar_bloques_contexto(mensaje, historial, lead)
    mensaje_para_claude = mensaje
    if bloques_contexto:
        mensaje_para_claude = "\n\n".join(bloques_contexto) + f"\n\nMensaje del cliente: {mensaje}"

    # Construir mensajes para la API. Claude solo acepta los roles "user" y
    # "assistant" — los mensajes que escribió un asesor humano (guardados con
    # role="asesor" para distinguirlos en el panel) se mapean a "assistant",
    # ya que para el cliente es la misma "voz" del negocio.
    mensajes = [
        {"role": "assistant" if m["role"] == "asesor" else m["role"], "content": m["content"]}
        for m in historial
    ]
    mensajes.append({"role": "user", "content": mensaje_para_claude})

    try:
        response = await client.messages.create(
            model=MODELO_PRINCIPAL,
            max_tokens=1024,
            system=system_prompt,
            messages=mensajes
        )

        respuesta = response.content[0].text
        logger.info(f"Respuesta generada ({response.usage.input_tokens} in / {response.usage.output_tokens} out)")
        return respuesta, False

    except Exception as e:
        logger.error(f"Error Claude API: {e}")
        return obtener_mensaje_error(), True


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
