# agent/errores_ia.py — Clasificación de los errores de la API de Anthropic (Fase 1, modo sin IA)
#
# Un error de la API no vale lo mismo según qué lo causó: un saldo agotado o un tope de gasto no
# se arreglan reintentando (hay que abrir el circuito y pasar al modo sin IA), un 5xx o un
# timeout sí suelen pasar solos, y un 400 de contenido es culpa de ese mensaje en particular.
#
# Tabla verificada contra la documentación oficial (https://platform.claude.com/docs/en/api/errors):
#   · HTTP 402, o body.error.type == "billing_error"            → "credito"
#   · 400 con "credit balance" en el mensaje                    → "credito"
#   · 400 con "specified API usage limits" en el mensaje        → "tope_gasto"
#   · 429 con error_code "enforced_spend_limit_reached" en el body → "tope_gasto"
#   · 401 / 403                                                 → "auth"
#   · 429 normal, 5xx, 529, timeouts y errores de conexión      → "transitorio"
#   · cualquier otra cosa (400 de contenido, 404, 413, 422…)    → "otro"
#
# El SDK local no tiene una clase para el 402: llega como `APIStatusError` genérica. Por eso se
# mira `status_code` y `body`, nunca el tipo de la excepción, y se es defensivo con un body
# ausente o con otra forma.

import asyncio
import json
import logging

logger = logging.getLogger("agentkit")

CREDITO = "credito"
TOPE_GASTO = "tope_gasto"
AUTH = "auth"
TRANSITORIO = "transitorio"
OTRO = "otro"

# Categorías que NO se arreglan reintentando: abren el circuito al primer error.
CATEGORIAS_QUE_ABREN_DE_INMEDIATO = (CREDITO, TOPE_GASTO, AUTH)

_CODIGO_TOPE_GASTO = "enforced_spend_limit_reached"


def _cuerpo_como_texto(body) -> str:
    if body is None:
        return ""
    if isinstance(body, (bytes, bytearray)):
        return bytes(body).decode("utf-8", errors="ignore")
    if isinstance(body, str):
        return body
    try:
        return json.dumps(body, ensure_ascii=False, default=str)
    except Exception:
        return str(body)


def _tipo_y_mensaje_del_body(body) -> tuple[str, str]:
    """`body.error.type` y `body.error.message` (con tolerancia a otras formas)."""
    if not isinstance(body, dict):
        return "", ""
    error = body.get("error")
    if isinstance(error, dict):
        return str(error.get("type") or ""), str(error.get("message") or "")
    return str(body.get("type") or ""), str(body.get("message") or "")


def clasificar_error(exc: BaseException) -> str:
    """Devuelve "credito" | "tope_gasto" | "auth" | "transitorio" | "otro". Nunca lanza."""
    try:
        status = getattr(exc, "status_code", None)
        body = getattr(exc, "body", None)
        tipo_body, mensaje_body = _tipo_y_mensaje_del_body(body)
        texto = f"{mensaje_body} {getattr(exc, 'message', '') or ''} {exc}".lower()
        texto_body = _cuerpo_como_texto(body).lower()

        if isinstance(status, int):
            if status == 402 or tipo_body == "billing_error":
                return CREDITO
            if _CODIGO_TOPE_GASTO in texto_body and status in (400, 429):
                return TOPE_GASTO
            if status == 400:
                if "credit balance" in texto:
                    return CREDITO
                if "specified api usage limits" in texto:
                    return TOPE_GASTO
                return OTRO
            if status in (401, 403):
                return AUTH
            if status in (408, 409, 429) or status >= 500:
                return TRANSITORIO
            return OTRO

        if tipo_body == "billing_error":
            return CREDITO

        # Sin código HTTP: timeouts y errores de conexión (incluye APITimeoutError y
        # APIConnectionError del SDK, httpx.TimeoutException y los de red del sistema).
        nombre = type(exc).__name__
        if isinstance(exc, (asyncio.TimeoutError, TimeoutError, ConnectionError, OSError)) or any(
            marca in nombre for marca in ("Timeout", "Connection", "Connect", "Transport", "ReadError", "RemoteProtocol")
        ):
            return TRANSITORIO
        return OTRO
    except Exception:  # un clasificador nunca puede romper el camino de un mensaje
        logger.exception("No se pudo clasificar el error de la API de Anthropic")
        return OTRO
