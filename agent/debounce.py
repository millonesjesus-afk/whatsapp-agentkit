# agent/debounce.py — agrupa mensajes rápidos del mismo cliente en una sola
# llamada a Claude (Gate 2026-09-23, fix #3 del bloque de 3 correcciones
# consolidadas con el usuario, junto con el respeto de asignación en media y
# el cierre definitivo).

"""
Mismo patrón que un cliente escribiendo en WhatsApp: manda 3 mensajes
seguidos ("hola", "quiero una terma", "de 5.5L") en vez de uno solo largo.
Sin este módulo, cada uno disparaba SU PROPIA llamada a Claude — 3 llamadas,
3 respuestas separadas, sin que el bot esperara a que la persona terminara
de escribir. Es el mismo comportamiento que ManyChat/Chatwoot/n8n implementan
como "message buffering" — ventana corta (2-5s, acá configurable), se
reinicia con cada mensaje nuevo del mismo cliente, y recién cuando pasa
tranquila sin mensajes nuevos se dispara UNA sola llamada que ya ve todo el
historial acumulado.

Efecto en costo (investigado antes de construir esto): MENOS llamadas a la
API de Anthropic, no más — cada llamada repite el system prompt completo, así
que agrupar 3 mensajes en 1 llamada cuesta menos que 3 llamadas separadas,
además de la reducción real de latencia percibida por overhead de red.

Registro en memoria de las tareas pendientes — mismo criterio que
`agent/tiempo_real.py::GestorConexiones` (un solo proceso en Railway para
este proyecto, no hace falta un almacén compartido como Redis para esta
escala).
"""

import asyncio
import logging
import os
from typing import Awaitable, Callable

logger = logging.getLogger("agentkit")

VENTANA_DEBOUNCE_POR_DEFECTO_SEG = 3.0


class GestorDebounceRespuestas:
    """Por cada `clave` (pensado como `f"{negocio_id}:{telefono}"` — nunca
    solo `telefono`, el mismo número puede existir en dos Negocios a la vez,
    ver Gate 5.2/Tenant 002) mantiene a lo sumo UNA tarea "esperando" a la
    vez. `reprogramar()` la reemplaza en cada mensaje nuevo — cancela la
    anterior SOLO si todavía está en la ventana de espera (sleep); una vez
    que esa ventana pasó y ya empezó a ejecutar el trabajo real (la llamada
    a Claude + el envío), nunca se cancela a mitad de camino — abortar una
    llamada a Claude ya en curso perdería la respuesta sin que nadie se
    entere ni el cliente reciba nada. Un mensaje que llega mientras el
    trabajo anterior sigue ejecutando simplemente arranca SU PROPIA ventana
    nueva e independiente — dos respuestas separadas en vez de una sola,
    pero nunca una perdida.
    """

    def __init__(self, ventana_segundos: float | None = None):
        # None = leer la ventana de DEBOUNCE_RESPUESTA_SEGUNDOS en cada
        # `reprogramar()`, no una sola vez al construirse — así un test que
        # fija esa variable de entorno ANTES de llamar al webhook (no
        # necesariamente antes de que este módulo se importe por primera
        # vez, el orden de import entre archivos de test no está
        # garantizado) siempre ve el valor que espera, sin depender de qué
        # test se ejecutó primero.
        self._ventana_fija = ventana_segundos
        self._pendientes: dict[str, asyncio.Task] = {}
        self._todas: set[asyncio.Task] = set()

    def _ventana(self) -> float:
        if self._ventana_fija is not None:
            return self._ventana_fija
        return float(os.getenv("DEBOUNCE_RESPUESTA_SEGUNDOS", str(VENTANA_DEBOUNCE_POR_DEFECTO_SEG)))

    def reprogramar(self, clave: str, ejecutar: Callable[[], Awaitable[None]]) -> None:
        """Reemplaza el temporizador pendiente de `clave`. `ejecutar` es una
        función SIN argumentos que retorna la corutina a correr cuando pasa
        la ventana sin mensajes nuevos — quien llama la arma con
        `functools.partial`/closure capturando lo que necesite de ESTE
        mensaje puntual (canal, mensaje_id para "escribiendo...", etc.)."""
        anterior = self._pendientes.get(clave)
        if anterior is not None and not anterior.done():
            anterior.cancel()

        async def _ciclo():
            try:
                await asyncio.sleep(self._ventana())
            except asyncio.CancelledError:
                # Lo reemplazó un mensaje más nuevo mientras todavía
                # esperaba — no es un error, simplemente esta ventana ya no
                # corresponde, la que la reemplazó se hace cargo.
                return
            # A partir de acá el trabajo real ya arrancó — se saca de
            # `_pendientes` (ya no es cancelable ni reemplazable) ANTES de
            # llamar a `ejecutar()`, para que un mensaje que llegue justo
            # ahora abra su propia ventana nueva en vez de pisar esta.
            self._pendientes.pop(clave, None)
            try:
                await ejecutar()
            except Exception:
                logger.exception(f"Fallo generando la respuesta debounced de {clave!r}")

        tarea = asyncio.create_task(_ciclo())
        self._pendientes[clave] = tarea
        self._todas.add(tarea)
        tarea.add_done_callback(self._todas.discard)

    async def esperar_pendientes(self) -> None:
        """SOLO para tests — el punto entero de este módulo es que el
        webhook NO espere esto en producción (si esperara, se pierde toda
        la ventaja: Meta seguiría sin su 200 OK rápido). Espera a que
        terminen TODAS las tareas programadas hasta este instante, estén
        todavía en la ventana de espera o ya ejecutando el trabajo real."""
        tareas = list(self._todas)
        if tareas:
            await asyncio.gather(*tareas, return_exceptions=True)


gestor_debounce_respuestas = GestorDebounceRespuestas()
