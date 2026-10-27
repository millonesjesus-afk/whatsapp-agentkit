# agent/sombra_modelo.py — Respuesta "en sombra" con otros modelos (2026-10-26, auditoría de tokens).
#
# Para decidir con qué modelo conviene que responda Gabi (Haiku 5.5 cuesta ~20 veces menos que Sonnet 5.5, y Sonnet 5.5 un
# tercio menos por token que el actual Sonnet 4.6), cada respuesta real se genera también con esos modelos, con EXACTAMENTE
# el mismo pedido (instrucciones, historial y contexto del turno), pero esas respuestas NUNCA se envían al cliente ni entran
# al chat: se guardan como evento interno `sombra_modelo` para compararlas después (scripts/sombra_modelo.py).
#
# Se enciende con la configuración `gabi_sombra_modelo` = uno o varios ids separados por coma
# (p. ej. "claude-haiku-5-5,claude-sonnet-5-5"); vacía = apagada.
# Corre en segundo plano: nunca demora ni rompe la respuesta real, y cualquier error se registra y se ignora.

import asyncio
import logging
import time

from agent.memory import EVENTO_SOMBRA_MODELO  # tipo de evento interno (no sale en el Timeline)

logger = logging.getLogger("agentkit")

CLAVE_MODELO_SOMBRA = "gabi_sombra_modelo"

# Cómo se apaga el razonamiento en cada familia (se cobra y en una respuesta de chat no hace falta):
# Haiku 5.5 acepta "disabled"; Sonnet 5.5 lo rechaza con un 400 y usa "between_tools".
RAZONAMIENTO_POR_MODELO = {
    "claude-sonnet-5-5": {"type": "between_tools"},
}
RAZONAMIENTO_POR_DEFECTO = {"type": "disabled"}

# Referencias vivas a las tareas en curso: asyncio solo guarda referencias débiles y una tarea sin referencia puede
# desaparecer antes de terminar.
_tareas: set[asyncio.Task] = set()


async def modelos_configurados(negocio_id: str | None) -> list[str]:
    from agent.memory import obtener_configuracion

    try:
        valor = await obtener_configuracion(CLAVE_MODELO_SOMBRA, "", negocio_id=negocio_id) or ""
    except Exception:
        return []
    return [m.strip() for m in valor.split(",") if m.strip()]


def lanzar(system_prompt: str, mensajes: list[dict], respuesta_real: str, lead: dict | None, negocio_id: str | None) -> None:
    """Agenda las respuestas en sombra sin esperarlas. Sin lead (sin teléfono donde guardar el evento) no hace nada."""
    if not lead or not lead.get("telefono"):
        return
    try:
        tarea = asyncio.get_running_loop().create_task(
            _generar_todas(system_prompt, mensajes, respuesta_real, lead["telefono"], negocio_id)
        )
    except RuntimeError:
        return
    _tareas.add(tarea)
    tarea.add_done_callback(_tareas.discard)


async def _generar_todas(
    system_prompt: str, mensajes: list[dict], respuesta_real: str, telefono: str, negocio_id: str | None,
) -> None:
    modelos = await modelos_configurados(negocio_id)
    await asyncio.gather(*(
        _generar_y_guardar(modelo, system_prompt, mensajes, respuesta_real, telefono) for modelo in modelos
    ))


async def _generar_y_guardar(
    modelo: str, system_prompt: str, mensajes: list[dict], respuesta_real: str, telefono: str,
) -> None:
    from agent import brain
    from agent.memory import registrar_evento_lead

    try:
        inicio = time.monotonic()
        response = await brain.client.messages.create(
            model=modelo,
            max_tokens=1024,
            thinking=RAZONAMIENTO_POR_MODELO.get(modelo, RAZONAMIENTO_POR_DEFECTO),
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
        logger.exception(f"Respuesta en sombra con {modelo}: no se pudo generar o guardar (la respuesta real no se ve afectada)")
