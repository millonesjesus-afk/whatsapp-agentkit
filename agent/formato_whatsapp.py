# agent/formato_whatsapp.py — Limpieza determinista del markdown que Claude mete en los mensajes de Gabi
# (Mejoras de Gabi, Fase 1, 2026-10-07).
#
# WhatsApp NO interpreta markdown: usa un solo asterisco para la negrita (`*así*`), un guion bajo para la
# cursiva y una tilde para el tachado. Claude escribe `**negrita**`, encabezados `#`, tablas y listas con `-`,
# y el cliente los ve crudos. Auditoría de 399 chats: 41 % de los mensajes de Gabi traían `**` visibles.
#
# `formatear_para_whatsapp` es PURA, idempotente (f(f(x)) == f(x)) y no lanza. Respeta los bloques ``` ```.
# Solo se aplica a texto que escribe Gabi; los mensajes del asesor no pasan por acá jamás.
#
# `limpieza_activa()` lee el interruptor `gabi_limpieza_formato_activo` (default "1") con caché corta, para no
# consultar la base en cada mensaje. "0" apaga TODA la limpieza (origen, historial y red de seguridad).

import logging
import re
import time
from contextvars import ContextVar

logger = logging.getLogger("agentkit")

CLAVE_INTERRUPTOR = "gabi_limpieza_formato_activo"
CACHE_SEGUNDOS = 60

_CERCO = re.compile(r"(```.*?```)", re.S)


def formatear_para_whatsapp(texto: str) -> str:
    """Convierte el markdown de Claude en el formato que WhatsApp sí muestra. Devuelve el texto original
    ante cualquier error, y tal cual None / cadena vacía."""
    if not texto or not isinstance(texto, str):
        return texto
    try:
        partes = _CERCO.split(texto)   # los bloques ``` ``` se respetan tal cual
        return "".join(p if i % 2 else _limpiar(p) for i, p in enumerate(partes)).strip()
    except Exception:
        logger.exception("formatear_para_whatsapp falló — se deja el texto original")
        return texto


def _limpiar(t: str) -> str:
    t = re.sub(r"(?m)^[ \t]{0,3}#{1,6}[ \t]+(.+?)[ \t]*#*[ \t]*$",
               lambda m: f"*{m.group(1).strip().strip('*')}*", t)             # '## Título' -> '*Título*'
    t = re.sub(r"\*\*(?=\S)([^*\n]+?)(?<=\S)\*\*", r"*\1*", t)                # **x** -> *x*
    t = re.sub(r"(?<![\w_])__(?=\S)([^_\n]+?)(?<=\S)__(?![\w_])", r"*\1*", t) # __x__ -> *x*
    t = re.sub(r"~~(?=\S)([^~\n]+?)(?<=\S)~~", r"~\1~", t)                    # ~~x~~ -> ~x~
    t = re.sub(r"\[([^\]\n]+)\]\((https?://[^)\s]+)\)", r"\1: \2", t)         # [txt](url) -> txt: url
    t = re.sub(r"(?m)^([ \t]*)[-+*][ \t]+(?=\S)", r"\1• ", t)                 # listas -> viñeta
    t = re.sub(r"(?m)^[ \t]*([-*_])\1{2,}[ \t]*$\n?", "", t)                  # reglas horizontales
    t = re.sub(r"\*\*(?!\w)|(?<![\w*])\*\*", "", t)                           # ** huérfanos
    t = re.sub(r"(?m)^[ \t]*\|?[ \t]*:?-{3,}:?[ \t]*(\|[ \t]*:?-{3,}:?[ \t]*)+\|?[ \t]*\n?", "", t)  # línea |---|
    t = re.sub(r"(?m)^[ \t]*\|(.+)\|[ \t]*$",
               lambda m: " · ".join(c.strip() for c in m.group(1).split("|") if c.strip()), t)       # fila de tabla
    return re.sub(r"\n{3,}", "\n\n", t)


def limpiar_historial_assistant(mensajes: list[dict]) -> list[dict]:
    """Copia de `mensajes` con el contenido de los turnos `assistant` limpio, EN MEMORIA: no toca la lista
    original ni los dicts originales (la base nunca se modifica). Corta el contagio: Claude imita el `**` que
    ve en sus propios mensajes anteriores. Ante cualquier error devuelve la lista original."""
    try:
        limpios = []
        for m in mensajes:
            if m.get("role") == "assistant" and isinstance(m.get("content"), str):
                m = {**m, "content": formatear_para_whatsapp(m["content"])}
            limpios.append(m)
        return limpios
    except Exception:
        logger.exception("limpiar_historial_assistant falló — se deja el historial original")
        return mensajes


# ── Interruptor (caché de ~60 s) ─────────────────────────────────────────────

_cache: tuple[float, bool] | None = None


def limpiar_cache() -> None:
    global _cache
    _cache = None


async def limpieza_activa() -> bool:
    """¿Está encendida la limpieza? Clave global `gabi_limpieza_formato_activo`, default encendida. Nunca
    lanza: si la base falla, se queda con lo último conocido (o encendida si no hay nada)."""
    global _cache
    ahora = time.monotonic()
    if _cache is not None and ahora - _cache[0] < CACHE_SEGUNDOS:
        return _cache[1]
    try:
        from agent.memory import obtener_configuracion   # import tardío: memory no debe depender de este módulo
        valor = (await obtener_configuracion(CLAVE_INTERRUPTOR, "1")).strip().lower()
        activa = valor not in ("0", "false", "no", "off")
    except Exception:
        logger.exception("No se pudo leer el interruptor de limpieza de formato")
        return _cache[1] if _cache is not None else True
    _cache = (ahora, activa)
    return activa


# ── Salida de Gabi (lo llama agent/brain.py) ─────────────────────────────────

# Texto tal como lo devolvió Claude, ANTES de limpiar, para las métricas en modo sombra (agent/main.py lo lee
# justo después de `generar_respuesta`, en la misma tarea asyncio). Es una ContextVar: dos conversaciones que
# se procesan a la vez no se pisan.
ORIGINAL_ANTES_DE_LIMPIAR: ContextVar[str | None] = ContextVar("gabi_original_antes_de_limpiar", default=None)


async def limpiar_salida_gabi(texto: str) -> str:
    """Limpia la respuesta de Claude si el interruptor está encendido; si no, la deja igual. Guarda el
    original para las métricas. Nunca lanza."""
    try:
        ORIGINAL_ANTES_DE_LIMPIAR.set(texto)
        if not await limpieza_activa():
            return texto
        limpio = formatear_para_whatsapp(texto)
        return limpio if limpio else texto   # nunca dejar la respuesta vacía por limpiar
    except Exception:
        logger.exception("limpiar_salida_gabi falló — se deja el texto original")
        return texto
