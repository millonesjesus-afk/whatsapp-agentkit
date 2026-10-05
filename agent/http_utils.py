# agent/http_utils.py — Cliente HTTP con timeout y reintentos por defecto
# Generado por AgentKit

"""
Helper compartido para llamadas HTTP salientes a proveedores externos
(Meta, Resend). Implementa la Decisión local de DevOps Architecture:
toda llamada externa debe tener timeout explícito y al menos un
reintento con backoff — antes cada llamada usaba httpx.AsyncClient()
sin ningún timeout ni reintento configurado.

El cliente httpx.AsyncClient es un único objeto reusado por todo el
proceso (Backend Architecture, Decisión local "Cliente HTTP compartido
con timeout explícito": *"Un cliente httpx.AsyncClient reusado — no uno
nuevo por llamada — con timeout configurado por defecto, para Meta y
Resend"*) — antes se creaba (y cerraba) uno nuevo en cada llamada, lo que
descartaba el pooling de conexiones entre requests. Se crea de forma
perezosa en el primer uso y se cierra explícitamente en el shutdown del
servidor (ver `cerrar_cliente_http` en agent/main.py).

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

_client: httpx.AsyncClient | None = None


def _obtener_cliente() -> httpx.AsyncClient:
    """Cliente compartido por todo el proceso — se crea una sola vez, no
    por llamada (Backend Architecture, Decisión local)."""
    global _client
    if _client is None:
        _client = httpx.AsyncClient(timeout=TIMEOUT_HTTP)
    return _client


async def cerrar_cliente_http():
    """Cierra el cliente compartido — se llama en el shutdown del
    servidor (lifespan de agent/main.py), no antes."""
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None


async def _con_reintentos(metodo: str, url: str, **kwargs) -> httpx.Response:
    ultimo_error: Exception | None = None
    client = _obtener_cliente()
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
    """POST con timeout y hasta MAX_INTENTOS intentos ante timeout/conexión/5xx.

    NO usar para enviar mensajes a un cliente (ver `post_sin_duplicar`): si
    Meta aceptó el mensaje pero la respuesta se perdió, este reintento lo
    manda de nuevo."""
    return await _con_reintentos("POST", url, **kwargs)


# ── Envíos que no deben duplicarse ────────────────────────────────────────────
#
# La API de mensajes de Meta Cloud NO tiene clave de idempotencia (supuesto de
# diseño, no verificado contra la documentación): dos POST iguales producen dos
# mensajes, cada uno con su wamid, y Meta cobra cada copia. Por eso un envío
# solo se puede reintentar cuando la petición SEGURO nunca salió.

# Fallas en las que la petición nunca llegó a Meta: no se pudo abrir la
# conexión o no hubo una conexión libre en el pool.
_NUNCA_SALIO = (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout)

MAX_INTENTOS_SIN_DUPLICAR = 3
# Tope de espera ante un 429. Si Meta pide esperar más que esto no se
# reintenta: bloquear el webhook más tiempo no vale la pena.
ESPERA_MAXIMA_429_SEGUNDOS = 10.0


class EnvioIncierto(Exception):
    """El POST de un envío pudo haber llegado a Meta pero no se conoce el
    resultado: la respuesta se perdió (ReadTimeout, error de lectura/escritura,
    conexión cortada) o Meta respondió 5xx. El mensaje PUDO haberse enviado:
    quien capture esto NO debe reenviarlo ni darlo por fallido."""

    def __init__(self, motivo: str, status_code: int | None = None):
        super().__init__(motivo)
        self.motivo = motivo
        self.status_code = status_code


async def _dormir(segundos: float) -> None:
    # Función aparte para poder sustituirla en las pruebas sin tocar asyncio.sleep.
    await asyncio.sleep(segundos)


def _espera_retry_after(respuesta: httpx.Response) -> float | None:
    """Segundos que Meta pide esperar (cabecera Retry-After en segundos), o
    None si no viene o no es un número."""
    valor = respuesta.headers.get("retry-after")
    if valor is None:
        return None
    try:
        return max(0.0, float(valor))
    except ValueError:
        return None


async def post_sin_duplicar(url: str, **kwargs) -> httpx.Response:
    """POST de un envío de mensaje — nunca lo repite si pudo haber salido.

    - Reintenta (hasta MAX_INTENTOS_SIN_DUPLICAR, con la misma espera de
      siempre) solo ConnectError, ConnectTimeout y PoolTimeout: la petición
      nunca salió. Agotados los intentos relanza la última excepción.
    - Reintenta un 429 de Meta (rechazo por ritmo, el mensaje no se creó)
      esperando lo que diga Retry-After, hasta ESPERA_MAXIMA_429_SEGUNDOS; si
      pide más, o se agotan los intentos, devuelve el 429 tal cual.
    - NUNCA reintenta ReadTimeout, WriteTimeout, ReadError, WriteError,
      RemoteProtocolError ni un 5xx: levanta `EnvioIncierto`.
    - Cualquier otra respuesta (200, 4xx) se devuelve tal cual."""
    client = _obtener_cliente()
    ultimo_error: Exception | None = None
    respuesta: httpx.Response | None = None
    for intento in range(MAX_INTENTOS_SIN_DUPLICAR):
        espera = ESPERA_ENTRE_INTENTOS_SEGUNDOS[min(intento, len(ESPERA_ENTRE_INTENTOS_SEGUNDOS) - 1)]
        try:
            respuesta = await client.request("POST", url, **kwargs)
        except _NUNCA_SALIO as e:
            ultimo_error = e
            logger.warning(f"POST {url} no pudo salir ({type(e).__name__}) — intento {intento + 1}/{MAX_INTENTOS_SIN_DUPLICAR}")
        except httpx.TransportError as e:
            logger.warning(f"POST {url} falló con {type(e).__name__} — resultado incierto, no se reintenta")
            raise EnvioIncierto(f"{type(e).__name__}: la petición pudo haber llegado a Meta") from e
        else:
            if respuesta.status_code >= 500:
                logger.warning(f"POST {url} respondió {respuesta.status_code} — resultado incierto, no se reintenta")
                raise EnvioIncierto(f"Meta respondió {respuesta.status_code}", status_code=respuesta.status_code)
            if respuesta.status_code != 429:
                return respuesta
            ultimo_error = None
            pedida = _espera_retry_after(respuesta)
            if pedida is not None:
                if pedida > ESPERA_MAXIMA_429_SEGUNDOS:
                    logger.warning(f"POST {url} respondió 429 con Retry-After {pedida}s (> tope) — no se reintenta")
                    return respuesta
                espera = pedida
            logger.warning(f"POST {url} respondió 429 — intento {intento + 1}/{MAX_INTENTOS_SIN_DUPLICAR}")
        if intento < MAX_INTENTOS_SIN_DUPLICAR - 1:
            await _dormir(espera)

    if ultimo_error is not None:
        raise ultimo_error
    return respuesta


async def get_con_reintentos(url: str, **kwargs) -> httpx.Response:
    """GET con timeout y hasta MAX_INTENTOS intentos ante timeout/conexión/5xx."""
    return await _con_reintentos("GET", url, **kwargs)
