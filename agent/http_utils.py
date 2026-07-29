# agent/http_utils.py — Cliente HTTP con timeout y reintentos por defecto
# Generado por AgentKit

"""
Helper compartido para llamadas HTTP salientes a proveedores externos
(Meta, Resend). Implementa la Decisión local de DevOps Architecture:
toda llamada externa debe tener timeout explícito y al menos un
reintento con backoff — antes cada llamada usaba httpx.AsyncClient()
sin ningún timeout ni reintento configurado.

No se usa para la API de Anthropic, que ya trae su propio manejo de
timeout/reintentos vía el SDK (ver agent/brain.py).
"""

import asyncio
import logging
import httpx

logger = logging.getLogger("agentkit")

# Timeout total generoso para no cortar una subida de archivo grande,
# pero acotado — una llamada colgada indefinidamente bloquea el mensaje
# de WhatsApp que depende de ella.
TIMEOUT_HTTP = httpx.Timeout(20.0, connect=5.0)

# Reintentos solo ante fallas transitorias (timeout, conexión, 5xx) — un
# error 4xx (token inválido, payload mal formado) nunca se reintenta,
# reintentarlo no cambiaría el resultado.
MAX_INTENTOS = 3
ESPERA_ENTRE_INTENTOS_SEGUNDOS = (1, 2)


async def _con_reintentos(metodo: str, url: str, **kwargs) -> httpx.Response:
    ultimo_error: Exception | None = None
    async with httpx.AsyncClient(timeout=TIMEOUT_HTTP) as client:
        for intento in range(MAX_INTENTOS):
            try:
                r = await client.request(metodo, url, **kwargs)
            except httpx.TransportError as e:
                ultimo_error = e
            else:
                if r.status_code < 500:
                    return r
                ultimo_error = None
                logger.warning(f"{metodo} {url} respondió {r.status_code} (intento {intento + 1}/{MAX_INTENTOS})")

            if intento < MAX_INTENTOS - 1:
                espera = ESPERA_ENTRE_INTENTOS_SEGUNDOS[min(intento, len(ESPERA_ENTRE_INTENTOS_SEGUNDOS) - 1)]
                await asyncio.sleep(espera)

        if ultimo_error is not None:
            raise ultimo_error
        return r


async def post_con_reintentos(url: str, **kwargs) -> httpx.Response:
    """POST con timeout y hasta MAX_INTENTOS intentos ante timeout/conexión/5xx."""
    return await _con_reintentos("POST", url, **kwargs)


async def get_con_reintentos(url: str, **kwargs) -> httpx.Response:
    """GET con timeout y hasta MAX_INTENTOS intentos ante timeout/conexión/5xx."""
    return await _con_reintentos("GET", url, **kwargs)
