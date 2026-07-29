# agent/rate_limit.py — Rate limiting y bloqueo por intentos, en memoria
# Generado por AgentKit

"""
Mecanismos en memoria de proceso para dos Decisiones locales P1 de Security
Architecture (Fase 0 del Implementation Roadmap):

1. Rate limiting en /login y /webhook — LimitadorTasa.
2. Bloqueo temporal tras intentos fallidos consecutivos de login — BloqueoPorIntentos.

Simplificación deliberada: el estado vive en memoria del proceso, no en un
almacén compartido (Redis u otro) — válido hoy porque el despliegue es de
una sola instancia (confirmado en DevOps Architecture, sin config de
réplicas). Si el despliegue pasa a múltiples instancias, ambos mecanismos
necesitarán un almacén compartido para seguir siendo efectivos — brecha ya
conocida, no resuelta acá.
"""

import time
from collections import defaultdict


class LimitadorTasa:
    """Ventana fija: como máximo `max_eventos` eventos por `clave` dentro
    de `ventana_segundos`."""

    def __init__(self):
        self._eventos: dict[str, list[float]] = defaultdict(list)

    def permitir(self, clave: str, max_eventos: int, ventana_segundos: float) -> bool:
        ahora = time.monotonic()
        eventos = self._eventos[clave]
        limite = ahora - ventana_segundos
        while eventos and eventos[0] < limite:
            eventos.pop(0)
        if len(eventos) >= max_eventos:
            return False
        eventos.append(ahora)
        return True


class BloqueoPorIntentos:
    """Bloquea una clave (ej. un username) tras `max_intentos` fallos
    consecutivos dentro de `bloqueo_segundos` — se resetea con un éxito."""

    def __init__(self):
        self._fallos: dict[str, list[float]] = defaultdict(list)
        self._bloqueado_hasta: dict[str, float] = {}

    def segundos_restantes(self, clave: str) -> float | None:
        """None si no está bloqueada; si no, segundos que faltan para liberarse."""
        hasta = self._bloqueado_hasta.get(clave)
        if hasta is None:
            return None
        restante = hasta - time.monotonic()
        if restante <= 0:
            del self._bloqueado_hasta[clave]
            self._fallos.pop(clave, None)
            return None
        return restante

    def registrar_fallo(self, clave: str, max_intentos: int, bloqueo_segundos: float) -> None:
        ahora = time.monotonic()
        limite = ahora - bloqueo_segundos
        fallos = [f for f in self._fallos[clave] if f >= limite]
        fallos.append(ahora)
        self._fallos[clave] = fallos
        if len(fallos) >= max_intentos:
            self._bloqueado_hasta[clave] = ahora + bloqueo_segundos

    def registrar_exito(self, clave: str) -> None:
        self._fallos.pop(clave, None)
        self._bloqueado_hasta.pop(clave, None)


# Instancias compartidas por todo el proceso — un solo estado, no uno por request.
limitador_login = LimitadorTasa()
limitador_webhook = LimitadorTasa()
bloqueo_login = BloqueoPorIntentos()
