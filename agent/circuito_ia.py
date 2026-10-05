# agent/circuito_ia.py — Circuito de la IA: "modo sin IA" de Gabi (Fase 1)
#
# Cuando la API de Anthropic no puede atender (saldo agotado, tope de gasto, credencial inválida,
# o fallas repetidas), insistir solo empeora las cosas: cada mensaje del cliente gasta una llamada
# que va a fallar y termina con un texto técnico. Este módulo guarda UN interruptor GLOBAL —el
# "circuito"— que dice si Gabi puede usar la IA ahora mismo:
#
#   · abierto  → Gabi NO llama a Claude: responde un mensaje automático y deriva a una persona
#                (ver agent/respaldo_sin_ia.py).
#   · cerrado  → funcionamiento normal.
#
# Cuándo se abre: de inmediato al PRIMER error de saldo/crédito, de tope de gasto o de credencial
# (no se arreglan reintentando); un error transitorio (5xx, 429 normal, timeout) solo la abre tras
# 3 fallas en 60 s, para no apagar la IA por un tropiezo de red.
#
# Cómo se cierra: estando abierto, un mensaje entrante (o un Cron) dispara cada 5 minutos UNA
# llamada de 1 token a Haiku (`sondear_si_corresponde`); si responde bien, el circuito se cierra
# solo. Para el motivo "transitorio" el sondeo es cada 2 minutos: se supone que pasa pronto.
#
# Estado: tabla `configuracion`, clave `ia_circuito`, negocio_id NULL (global de plataforma), como
# JSON {estado, abierto_en, motivo, ultimo_sondeo_en}, para que lo vean todos los procesos (el
# servidor web y los Cron). Caché en memoria de 10 s. Si la base falla al leerlo, se asume
# CERRADO: un fallo del propio mecanismo nunca debe dejar a Gabi sin responder.
#
# Todas las funciones públicas son seguras: ninguna lanza hacia quien la llama.

import asyncio
import json
import logging
import os
import time
import weakref
from collections import deque
from datetime import datetime, timedelta

from agent.errores_ia import (
    CATEGORIAS_QUE_ABREN_DE_INMEDIATO, TRANSITORIO, clasificar_error,
)
from agent.memory import guardar_configuracion, obtener_configuracion

logger = logging.getLogger("agentkit")

CLAVE_CIRCUITO = "ia_circuito"
CACHE_SEGUNDOS = 10.0
INTERVALO_SONDEO = timedelta(minutes=5)
INTERVALO_SONDEO_TRANSITORIO = timedelta(minutes=2)
FALLAS_TRANSITORIAS_PARA_ABRIR = 3
VENTANA_FALLAS_TRANSITORIAS_SEG = 60.0
TIMEOUT_SONDEO_SEG = 10.0

_ESTADO_CERRADO = {"estado": "cerrado", "abierto_en": None, "motivo": None, "ultimo_sondeo_en": None}


class _Memoria:
    """Lo que vive solo en este proceso: la caché del estado, el contador de fallas transitorias y
    los candados. Se recrea si cambia el event loop (en producción hay uno solo; en las pruebas
    cada test tiene el suyo, y así nada se arrastra de un test al siguiente)."""

    def __init__(self):
        self.cache: dict | None = None
        self.cache_en: float = 0.0
        self.fallas: deque[float] = deque()
        self.candado_estado = asyncio.Lock()
        self.candado_sondeo = asyncio.Lock()


_memoria: _Memoria | None = None
_memoria_loop: "weakref.ReferenceType[asyncio.AbstractEventLoop] | None" = None
_tareas_en_segundo_plano: set[asyncio.Task] = set()


def _mem() -> _Memoria:
    global _memoria, _memoria_loop
    loop = asyncio.get_running_loop()
    if _memoria is None or _memoria_loop is None or _memoria_loop() is not loop:
        _memoria = _Memoria()
        _memoria_loop = weakref.ref(loop)
    return _memoria


def reiniciar_memoria() -> None:
    """Descarta la caché y el contador de fallas de ESTE proceso (no toca la base). Para pruebas."""
    global _memoria, _memoria_loop
    _memoria = None
    _memoria_loop = None


def _ahora() -> datetime:
    """UTC sin zona, como el resto del proyecto (datetime.utcnow). Aparte para poder fijarlo en pruebas."""
    return datetime.utcnow()


def _a_iso(momento: datetime) -> str:
    return momento.replace(microsecond=0).isoformat()


def parsear_momento(valor: str | None) -> datetime | None:
    try:
        return datetime.fromisoformat(valor) if valor else None
    except (TypeError, ValueError):
        return None


def _normalizar(crudo) -> dict:
    estado = dict(_ESTADO_CERRADO)
    if isinstance(crudo, dict) and crudo.get("estado") == "abierto":
        estado.update({
            "estado": "abierto", "abierto_en": crudo.get("abierto_en"), "motivo": crudo.get("motivo"),
            "ultimo_sondeo_en": crudo.get("ultimo_sondeo_en"),
        })
    return estado


async def _leer_bd() -> dict:
    texto = await obtener_configuracion(CLAVE_CIRCUITO, "")
    if not texto:
        return dict(_ESTADO_CERRADO)
    try:
        return _normalizar(json.loads(texto))
    except (TypeError, ValueError):
        logger.warning(f"El estado del circuito de la IA no se pudo leer ({texto!r}) — se asume cerrado")
        return dict(_ESTADO_CERRADO)


async def _guardar_bd(estado: dict) -> None:
    if estado["estado"] == "abierto":
        valor = {k: estado[k] for k in ("estado", "abierto_en", "motivo", "ultimo_sondeo_en")}
    else:
        valor = {"estado": "cerrado"}
    texto = json.dumps(valor, separators=(",", ":"))
    # configuracion.valor es VARCHAR(200): con las fechas sin microsegundos y un motivo corto sobra.
    await guardar_configuracion(CLAVE_CIRCUITO, texto[:200])


async def obtener_estado(forzar: bool = False) -> dict:
    """El estado del circuito, con caché de 10 s (`forzar=True` la salta). Nunca lanza: si la base
    no responde devuelve lo último que se sabía, o "cerrado" si no se sabía nada."""
    m = _mem()
    if not forzar and m.cache is not None and time.monotonic() - m.cache_en < CACHE_SEGUNDOS:
        return dict(m.cache)
    try:
        estado = await _leer_bd()
    except Exception:
        logger.exception("No se pudo leer el estado del circuito de la IA — se usa el último conocido")
        return dict(m.cache) if m.cache is not None else dict(_ESTADO_CERRADO)
    m.cache, m.cache_en = estado, time.monotonic()
    return dict(estado)


async def esta_abierto() -> bool:
    return (await obtener_estado())["estado"] == "abierto"


def _en_segundo_plano(corrutina) -> None:
    """Lanza `corrutina` sin esperarla, con referencia fuerte (el loop solo guarda referencias
    débiles a las tareas) y sin que un error suyo llegue a nadie."""
    async def _envuelta():
        try:
            await corrutina
        except Exception:
            logger.exception("Falló una tarea en segundo plano del circuito de la IA")

    tarea = asyncio.create_task(_envuelta())
    _tareas_en_segundo_plano.add(tarea)
    tarea.add_done_callback(_tareas_en_segundo_plano.discard)


async def esperar_tareas_en_segundo_plano() -> None:
    """SOLO para pruebas: espera las alertas y sondeos lanzados en segundo plano."""
    tareas = list(_tareas_en_segundo_plano)
    if tareas:
        await asyncio.gather(*tareas, return_exceptions=True)


async def abrir(motivo: str) -> bool:
    """Abre el circuito. Idempotente: si ya estaba abierto no cambia nada (conserva su `abierto_en`).
    Devuelve True solo si ESTA llamada lo abrió (la apertura nueva), para que quien llama sepa si
    corresponde avisar. Registra una línea WARNING y le avisa al dueño de la plataforma."""
    try:
        m = _mem()
        async with m.candado_estado:
            try:
                actual = await _leer_bd()
            except Exception:
                logger.exception("No se pudo leer el circuito de la IA antes de abrirlo")
                actual = dict(m.cache) if m.cache is not None else dict(_ESTADO_CERRADO)
            if actual["estado"] == "abierto":
                m.cache, m.cache_en = actual, time.monotonic()
                return False
            nuevo = {"estado": "abierto", "abierto_en": _a_iso(_ahora()), "motivo": motivo, "ultimo_sondeo_en": None}
            # Primero la memoria: aunque la base falle, este proceso ya deja de llamar a Claude.
            m.cache, m.cache_en = nuevo, time.monotonic()
            m.fallas.clear()
            try:
                await _guardar_bd(nuevo)
            except Exception:
                logger.exception("No se pudo guardar el circuito de la IA abierto (queda abierto solo en este proceso)")
        logger.warning(f"circuito_ia ABIERTO (motivo={motivo}) — Gabi pasa a modo sin IA: mensaje automático y derivación a un asesor")
        from agent import notificaciones  # import tardío: evita arrastrar el correo al importar el circuito
        _en_segundo_plano(notificaciones.notificar_circuito_ia(True, motivo))
        return True
    except Exception:
        logger.exception("Falló la apertura del circuito de la IA")
        return False


async def cerrar() -> bool:
    """Cierra el circuito (Gabi vuelve a usar la IA). Devuelve True solo si estaba abierto y ESTA
    llamada lo cerró. Registra una línea WARNING y le manda al dueño de la plataforma un resumen."""
    try:
        m = _mem()
        async with m.candado_estado:
            try:
                actual = await _leer_bd()
            except Exception:
                logger.exception("No se pudo leer el circuito de la IA antes de cerrarlo")
                actual = dict(m.cache) if m.cache is not None else dict(_ESTADO_CERRADO)
            if actual["estado"] != "abierto":
                m.cache, m.cache_en = actual, time.monotonic()
                return False
            m.cache, m.cache_en = dict(_ESTADO_CERRADO), time.monotonic()
            m.fallas.clear()
            try:
                await _guardar_bd(m.cache)
            except Exception:
                logger.exception("No se pudo guardar el circuito de la IA cerrado")
        logger.warning(f"circuito_ia CERRADO (estaba abierto por {actual.get('motivo')}, desde {actual.get('abierto_en')}) — Gabi vuelve a usar la IA")
        _en_segundo_plano(_avisar_cierre(actual))
        return True
    except Exception:
        logger.exception("Falló el cierre del circuito de la IA")
        return False


async def _avisar_cierre(estado_previo: dict) -> None:
    from agent import notificaciones
    from agent.memory import contar_derivados_sin_ia

    resumen = None
    desde = parsear_momento(estado_previo.get("abierto_en"))
    if desde is not None:
        try:
            resumen = await contar_derivados_sin_ia(desde)
        except Exception:
            logger.exception("No se pudo contar los casos derivados por el modo sin IA")
    await notificaciones.notificar_circuito_ia(False, estado_previo.get("motivo") or "", resumen)


async def registrar_error(exc: BaseException) -> str:
    """Lo llama brain.py desde el `except` de cada llamada a Claude. Clasifica el error y decide:
    saldo/tope/credencial → abre el circuito de inmediato; transitorio → lo abre solo tras 3 fallas
    en 60 s; cualquier otro error (un 400 de contenido) no lo toca. Devuelve la categoría. No lanza."""
    categoria = clasificar_error(exc)
    try:
        if categoria in CATEGORIAS_QUE_ABREN_DE_INMEDIATO:
            await abrir(categoria)
        elif categoria == TRANSITORIO:
            m = _mem()
            ahora = time.monotonic()
            m.fallas.append(ahora)
            while m.fallas and ahora - m.fallas[0] > VENTANA_FALLAS_TRANSITORIAS_SEG:
                m.fallas.popleft()
            if len(m.fallas) >= FALLAS_TRANSITORIAS_PARA_ABRIR:
                await abrir(TRANSITORIO)
    except Exception:
        logger.exception("No se pudo registrar el error de la IA en el circuito")
    return categoria


def registrar_exito() -> None:
    """Una llamada a Claude salió bien: las fallas transitorias acumuladas ya no cuentan."""
    try:
        _mem().fallas.clear()
    except RuntimeError:  # sin event loop corriendo (no debería pasar en brain.py)
        pass


def _crear_cliente_sondeo():
    """Cliente APARTE del de brain.py: sin reintentos y con un timeout corto, para que el sondeo sea
    una sola llamada barata y rápida."""
    from anthropic import AsyncAnthropic

    return AsyncAnthropic(api_key=os.getenv("ANTHROPIC_API_KEY"), timeout=TIMEOUT_SONDEO_SEG, max_retries=0)


async def _llamada_de_sondeo() -> bool:
    from agent.brain import MODELO_EXTRACCION  # import tardío: brain importa este módulo

    cliente = _crear_cliente_sondeo()
    try:
        await cliente.messages.create(
            model=MODELO_EXTRACCION, max_tokens=1, messages=[{"role": "user", "content": "ok"}],
        )
        return True
    except Exception as e:
        logger.warning(f"Sondeo del circuito de la IA falló ({clasificar_error(e)}): {e}")
        return False
    finally:
        try:
            await cliente.close()
        except Exception:
            pass


async def sondear_si_corresponde() -> bool:
    """Con el circuito abierto y ≥5 min desde el último sondeo (2 min si el motivo es "transitorio"),
    hace UNA llamada de 1 token y, si responde bien, cierra el circuito. Devuelve True si lo cerró.

    Un candado por proceso hace que solo UN mensaje dispare el sondeo (los demás salen al instante),
    y `ultimo_sondeo_en` se guarda ANTES de llamar, para que otro proceso (un Cron) tampoco lo
    repita. Un sondeo fallido solo deja `ultimo_sondeo_en` actualizado. Sin ANTHROPIC_API_KEY en
    este proceso no se sondea (no se gasta el turno del sondeo en algo que no puede salir bien)."""
    try:
        m = _mem()
        if m.candado_sondeo.locked():
            return False
        async with m.candado_sondeo:
            estado = await obtener_estado()
            if estado["estado"] != "abierto" or not os.getenv("ANTHROPIC_API_KEY"):
                return False
            ahora = _ahora()
            referencia = parsear_momento(estado.get("ultimo_sondeo_en")) or parsear_momento(estado.get("abierto_en"))
            intervalo = INTERVALO_SONDEO_TRANSITORIO if estado.get("motivo") == TRANSITORIO else INTERVALO_SONDEO
            if referencia is not None and ahora - referencia < intervalo:
                return False

            reclamado = {**estado, "ultimo_sondeo_en": _a_iso(ahora)}
            m.cache, m.cache_en = reclamado, time.monotonic()
            try:
                await _guardar_bd(reclamado)
            except Exception:
                logger.exception("No se pudo guardar la hora del sondeo del circuito de la IA")
            logger.info("circuito_ia: sondeando la API de Anthropic (1 token)")
            if not await _llamada_de_sondeo():
                return False
        return await cerrar()
    except Exception:
        logger.exception("Falló el sondeo del circuito de la IA")
        return False


def sondear_en_segundo_plano() -> None:
    """Dispara `sondear_si_corresponde()` sin esperarla ni arriesgar el mensaje en curso."""
    _en_segundo_plano(sondear_si_corresponde())
