# agent/sombra_modelo.py — Respuesta "en sombra" con otro modelo (2026-10-26, auditoría de tokens).
#
# Para decidir si Gabi puede responder con un modelo mucho más barato (Haiku 5.5 cuesta ~20 veces menos que Sonnet 5.5),
# cada respuesta real se genera también con ese modelo, con EXACTAMENTE el mismo pedido (instrucciones, historial y
# contexto del turno), pero esa segunda respuesta NUNCA se envía al cliente ni entra al chat: se guarda como evento
# interno `sombra_modelo` para compararla después (scripts/comparar_sombra_modelo.py).
#
# Se enciende con la configuración `gabi_sombra_modelo` = id del modelo (p. ej. "claude-haiku-5-5"); vacía = apagada.
# Corre en segundo plano: nunca demora ni rompe la respuesta real, y cualquier error se registra y se ignora.

import asyncio
import logging
import time

from agent.memory import EVENTO_SOMBRA_MODELO  # tipo de evento interno (no sale en el Timeline)

logger = logging.getLogger("agentkit")

CLAVE_MODELO_SOMBRA = "gabi_sombra_modelo"

# Referencias vivas a las tareas en curso: asyncio solo guarda referencias débiles y una tarea sin referencia puede
# desaparecer antes de terminar.
_tareas: set[asyncio.Task] = set()


async def modelo_configurado(negocio_id: str | None) -> str:
    from agent.memory import obtener_configuracion

    try:
        return (await obtener_configuracion(CLAVE_MODELO_SOMBRA, "", negocio_id=negocio_id) or "").strip()
    except Exception:
        return ""


def lanzar(system_prompt: str, mensajes: list[dict], respuesta_real: str, lead: dict | None, negocio_id: str | None) -> None:
    """Agenda la respuesta en sombra sin esperarla. Sin lead (sin teléfono donde guardar el evento) no hace nada."""
    if not lead or not lead.get("telefono"):
        return
    try:
        tarea = asyncio.get_running_loop().create_task(
            _generar_y_guardar(system_prompt, mensajes, respuesta_real, lead["telefono"], negocio_id)
        )
    except RuntimeError:
        return
    _tareas.add(tarea)
    tarea.add_done_callback(_tareas.discard)


async def _generar_y_guardar(
    system_prompt: str, mensajes: list[dict], respuesta_real: str, telefono: str, negocio_id: str | None,
) -> None:
    from agent import brain
    from agent.memory import registrar_evento_lead

    try:
        modelo = await modelo_configurado(negocio_id)
        if not modelo:
            return
        inicio = time.monotonic()
        response = await brain.client.messages.create(
            model=modelo,
            max_tokens=1024,
            thinking=brain.SIN_RAZONAMIENTO,
            system=[{"type": "text", "text": system_prompt, "cache_control": brain.CACHE_INSTRUCCIONES}],
            messages=mensajes,
        )
        texto = brain.texto_de_respuesta(response)
        uso = response.usage
        await registrar_evento_lead(
            telefono, tipo=EVENTO_SOMBRA_MODELO, descripcion=f"Respuesta en sombra con {modelo} (no enviada)", autor=None,
            payload={
                "modelo": modelo,
                "modelo_real": brain.MODELO_PRINCIPAL,
                "respuesta_real": respuesta_real,
                "respuesta_sombra": texto,
                "stop_reason": getattr(response, "stop_reason", None),
                "latencia_ms": round((time.monotonic() - inicio) * 1000),
                "tokens_in": uso.input_tokens,
                "tokens_out": uso.output_tokens,
                "cache_read": getattr(uso, "cache_read_input_tokens", None),
                "cache_write": getattr(uso, "cache_creation_input_tokens", None),
            },
        )
    except Exception:
        logger.exception("Respuesta en sombra: no se pudo generar o guardar (la respuesta real no se ve afectada)")
