# agent/envios.py — Capa central de envíos de WhatsApp (Fase A, 2026-10-04)
#
# Todo mensaje que el sistema manda a un cliente pasa por acá, con la etiqueta
# del ORIGEN que lo pidió. Desde el 2026-10-01 Meta cobra los mensajes de
# servicio tras una cuota gratuita, y antes cada lugar del código llamaba al
# proveedor por su cuenta: no había forma de saber qué origen gasta cuánto ni de
# frenar uno sin tocar a los demás.
#
# Fase A: registrar cada envío con su origen y agrupar los avisos repetidos.
# Fase B: antes de enviar, agent/politica_envios.py estima si el envío sería
# gratis o cobrable y aplica el interruptor del origen (siempre | solo_gratis |
# nunca) y el tope mensual en USD. Lo esencial no se frena nunca por costo.
#
# Los envíos llaman al proveedor con los MISMOS argumentos de siempre (el
# proveedor es el que recibe quien llama, así que sustituirlo en pruebas sigue
# funcionando) y la respuesta se puede desempaquetar igual: `enviado, wamid = …`.

import asyncio
import logging
import weakref

from agent import politica_envios
from agent.http_utils import EnvioIncierto
from agent.memory import (
    cerrar_envio_meta, marcar_envio_incierto, obtener_configuracion, registrar_envio_bloqueado, reservar_envio_meta,
)

logger = logging.getLogger("agentkit")

# origen → política.
# `esencial`: un envío que el cliente espera; ningún interruptor ni tope de gasto
#   lo frena (salvo el modo B explícito `envios_tope_bloquea_esenciales`).
# `modo`: interruptor por defecto de un origen no esencial
#   (siempre | solo_gratis | nunca), cambiable con `envios_modo_<origen>`.
# `agrupar_minutos`: no repetir este origen al mismo cliente dentro de esa
#   ventana (configurable con `envios_agrupar_minutos_<origen>`).
# `categoria_plantilla`: categoría de Meta que se supone para una plantilla de
#   este origen al estimar su costo (cambiable con `envios_categoria_<origen>`).
ORIGENES: dict[str, dict] = {
    "gabi_respuesta": {"esencial": True},
    "gabi_aviso_derivacion": {"esencial": True},
    "gabi_aviso_no_legible": {"esencial": False, "modo": "solo_gratis", "agrupar_minutos": 10},
    "reenganche_inactividad": {"esencial": False, "modo": "solo_gratis"},
    "asesor_texto": {"esencial": True},
    "asesor_archivo": {"esencial": True},
    "asesor_audio": {"esencial": True},
    "plantilla_formulario": {"esencial": False, "modo": "siempre", "categoria_plantilla": "marketing"},
}


class ResultadoEnvio:
    """Resultado de un envío. Se desempaqueta como `(enviado, wamid)` y es
    verdadero si se envió, para que los llamadores que antes recibían una
    tupla o un booleano no cambien.

    `incierto` (2026-10-05): el POST a Meta pudo haber llegado pero no se supo
    el resultado (ReadTimeout, 5xx) y tampoco apareció el mensaje en
    `uso_mensajes_meta`. Ahí `enviado` es False —no se confirmó— pero NO es un
    fallo definitivo: el mensaje pudo salir, así que quien llama no debe
    reenviarlo a ciegas ni ofrecer "Reintentar" como si no hubiera salido."""

    def __init__(
        self, enviado: bool, wamid: str | None = None, bloqueado: bool = False, motivo: str | None = None,
        incierto: bool = False,
    ):
        self.enviado, self.wamid, self.bloqueado, self.motivo, self.incierto = enviado, wamid, bloqueado, motivo, incierto

    def __iter__(self):
        yield self.enviado
        yield self.wamid

    def __bool__(self) -> bool:
        return self.enviado

    @property
    def estado_envio(self) -> str | None:
        """Valor para `Mensaje.estado_envio` al guardar el mensaje que se
        intentó enviar: None si salió, "incierto" si pudo haber salido y no se
        supo, "fallido" en cualquier otro caso."""
        if self.enviado:
            return None
        return "incierto" if self.incierto else "fallido"

    def __repr__(self) -> str:
        return (
            f"ResultadoEnvio(enviado={self.enviado}, wamid={self.wamid!r}, bloqueado={self.bloqueado}, "
            f"motivo={self.motivo!r}, incierto={self.incierto})"
        )


# Un candado por event loop: el chequeo de agrupación y la reserva tienen que ser
# atómicos entre los mensajes simultáneos de un mismo cliente (tres fotos
# seguidas llegan como tres webhooks en paralelo).
_candados: "weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, asyncio.Lock]" = weakref.WeakKeyDictionary()


def _candado_de_reserva() -> asyncio.Lock:
    loop = asyncio.get_running_loop()
    if loop not in _candados:
        _candados[loop] = asyncio.Lock()
    return _candados[loop]


async def _minutos_de_agrupacion(origen: str, negocio_id: str | None) -> int:
    por_defecto = ORIGENES[origen].get("agrupar_minutos", 0)
    if not por_defecto:
        return 0
    try:
        valor = await obtener_configuracion(f"envios_agrupar_minutos_{origen}", str(por_defecto), negocio_id=negocio_id)
        return max(0, int(float(valor)))
    except Exception:
        return por_defecto


def _normalizar(respuesta) -> tuple[bool, str | None]:
    if isinstance(respuesta, tuple):
        return bool(respuesta[0]), (respuesta[1] if len(respuesta) > 1 else None)
    return bool(respuesta), None


async def _enviar(origen: str, tipo: str, telefono: str, canal: dict | None, llamada) -> ResultadoEnvio:
    if origen not in ORIGENES:
        raise ValueError(f"Origen de envío desconocido: {origen!r}. Registrarlo en agent/envios.py::ORIGENES.")
    negocio_id = (canal or {}).get("negocio_id")

    # Política de costo (Fase B): interruptor del origen y tope mensual. Lo
    # esencial nunca se frena por costo; `decidir` no lanza.
    decision = await politica_envios.decidir(origen, tipo, telefono, canal, ORIGENES[origen])
    if decision.bloquear:
        logger.info(f"Envío {origen} a {telefono} omitido — {decision.motivo}")
        try:
            await registrar_envio_bloqueado(negocio_id, origen, telefono, tipo, decision.motivo or "bloqueado", decision.estimacion)
        except Exception:
            logger.exception(f"No se pudo registrar el envío bloqueado {origen} a {telefono}")
        return ResultadoEnvio(False, None, bloqueado=True, motivo=decision.motivo)

    # El registro nunca puede impedir un envío: si falla, se envía igual.
    envio_id: int | None = None
    try:
        agrupar = await _minutos_de_agrupacion(origen, negocio_id)
        if agrupar:
            async with _candado_de_reserva():
                envio_id, motivo = await reservar_envio_meta(negocio_id, origen, telefono, tipo, agrupar, decision.estimacion)
        else:
            envio_id, motivo = await reservar_envio_meta(negocio_id, origen, telefono, tipo, 0, decision.estimacion)
        if envio_id is None and motivo:
            logger.info(f"Envío {origen} a {telefono} omitido — {motivo}")
            return ResultadoEnvio(False, None, bloqueado=True, motivo=motivo)
    except Exception:
        logger.exception(f"No se pudo registrar el envío {origen} a {telefono} — se envía igual")
        envio_id = None

    try:
        enviado, wamid = _normalizar(await llamada())
    except EnvioIncierto as incierto:
        # El mensaje pudo haber salido (y Meta cobrarlo): no es "fallido", no se
        # reenvía solo y no cuenta como enviado para la agrupación.
        motivo = f"incierto: {incierto.motivo} — el mensaje pudo haberse enviado, no se reenvía automáticamente"
        logger.warning(f"Envío {origen} a {telefono} con resultado incierto — {motivo}")
        await _cerrar_incierto(envio_id, motivo)
        return ResultadoEnvio(False, None, motivo=motivo, incierto=True)
    except BaseException:
        await _cerrar(envio_id, False, None)
        raise
    await _cerrar(envio_id, enviado, wamid)
    return ResultadoEnvio(enviado, wamid)


async def _cerrar_incierto(envio_id: int | None, motivo: str) -> None:
    if envio_id is None:
        return
    try:
        await marcar_envio_incierto(envio_id, motivo)
    except Exception:
        logger.exception(f"No se pudo marcar como incierto el registro de envío {envio_id}")


async def _cerrar(envio_id: int | None, enviado: bool, wamid: str | None) -> None:
    if envio_id is None:
        return
    try:
        await cerrar_envio_meta(envio_id, enviado, wamid)
    except Exception:
        logger.exception(f"No se pudo cerrar el registro de envío {envio_id}")


async def enviar_texto(proveedor, telefono: str, texto: str, *, origen: str, canal: dict | None = None, **extra) -> ResultadoEnvio:
    """`extra` se reenvía tal cual al proveedor (ej. `mensaje_id_citado`)."""
    return await _enviar(origen, "texto", telefono, canal, lambda: proveedor.enviar_mensaje(telefono, texto, canal=canal, **extra))


async def enviar_imagen(proveedor, telefono: str, media_id: str, caption: str = "", *, origen: str, canal: dict | None = None) -> ResultadoEnvio:
    return await _enviar(origen, "imagen", telefono, canal, lambda: proveedor.enviar_imagen(telefono, media_id, caption, canal=canal))


async def enviar_documento(
    proveedor, telefono: str, media_id: str, nombre_archivo: str, caption: str = "", *, origen: str, canal: dict | None = None,
) -> ResultadoEnvio:
    return await _enviar(origen, "documento", telefono, canal, lambda: proveedor.enviar_documento(telefono, media_id, nombre_archivo, caption, canal=canal))


async def enviar_audio(proveedor, telefono: str, media_id: str, *, origen: str, canal: dict | None = None) -> ResultadoEnvio:
    return await _enviar(origen, "audio", telefono, canal, lambda: proveedor.enviar_audio(telefono, media_id, canal=canal))


async def enviar_plantilla(
    proveedor, telefono: str, nombre_plantilla: str, parametros: list[str], idioma: str = "es", *, origen: str, canal: dict | None = None,
) -> ResultadoEnvio:
    return await _enviar(origen, "plantilla", telefono, canal, lambda: proveedor.enviar_plantilla(telefono, nombre_plantilla, parametros, idioma, canal=canal))
