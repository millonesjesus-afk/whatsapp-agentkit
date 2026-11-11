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

import ipaddress
import logging
import os
import time
from collections import defaultdict

logger = logging.getLogger("agentkit")

# Cuántos proxies CONFIABLES hay entre el cliente final y este proceso.
#
# 0 (por defecto) = ninguno: se usa la IP del socket y `X-Forwarded-For` se
# ignora por completo. Es el único valor seguro mientras no se pueda verificar
# la topología real de despliegue, porque cualquier cliente puede inventar ese
# header (medido: un rewrite de Next.js reenvía al backend, tal cual, el
# `X-Forwarded-For` que mandó el navegador).
#
# N >= 1 = hay exactamente N proxies confiables encadenados delante, y cada
# uno agrega UNA entrada a `X-Forwarded-For` con la dirección de quien le
# habló. Bajo esa premisa la IP del cliente final es la N-ésima contando
# desde la DERECHA: las entradas a la derecha las escribieron los proxies
# (no el cliente), y las de la izquierda son las que el cliente pudo haber
# falsificado. Contar desde la izquierda —lo que hace uvicorn cuando se le
# pasa `--forwarded-allow-ips=*`— sería trivialmente falsificable.
#
# Configurarlo con un número mayor al real NO es conservador: abre la puerta a
# que el cliente controle la entrada elegida. Solo subirlo con la topología
# verificada.
VARIABLE_PROXIES = "PROXIES_CONFIABLES"


def _proxies_confiables() -> int:
    crudo = os.getenv(VARIABLE_PROXIES, "0").strip()
    try:
        cantidad = int(crudo or "0")
    except ValueError:
        logger.warning(f"{VARIABLE_PROXIES}={crudo!r} no es un número — se asume 0 (sin proxy confiable)")
        return 0
    if cantidad < 0:
        logger.warning(f"{VARIABLE_PROXIES}={cantidad} es negativo — se asume 0 (sin proxy confiable)")
        return 0
    return cantidad


def _solo_host(valor: str) -> str:
    """Descarta el puerto opcional de una entrada de X-Forwarded-For.

    Acepta `1.2.3.4`, `1.2.3.4:5678`, `[::1]` y `[::1]:5678`. Devuelve la
    entrada intacta si no reconoce el formato — el validador de más arriba
    la descarta después, en vez de normalizar a ciegas algo arbitrario.
    """
    valor = valor.strip()
    if valor.startswith("["):
        cierre = valor.find("]")
        return valor[1:cierre] if cierre != -1 else valor
    if valor.count(":") == 1:  # IPv4:puerto (un IPv6 sin corchetes tiene más de un ':')
        return valor.rsplit(":", 1)[0]
    return valor


def ip_cliente(request) -> str:
    """IP del cliente para usar como clave de rate limiting.

    Con `PROXIES_CONFIABLES=0` (por defecto) devuelve la IP del socket y
    NUNCA mira `X-Forwarded-For`. Con N >= 1 devuelve la N-ésima entrada
    contando desde la derecha, y solo si la cadena trae al menos N entradas:
    una cadena más corta significa que la solicitud NO pasó por los proxies
    esperados, así que se vuelve a la IP del socket en vez de confiar en un
    header que en ese caso solo pudo haber puesto el propio cliente.
    """
    socket_ip = request.client.host if request.client else "desconocida"

    cantidad_proxies = _proxies_confiables()
    if cantidad_proxies == 0:
        return socket_ip

    entradas: list[str] = []
    for cabecera in request.headers.getlist("x-forwarded-for"):
        entradas.extend(parte.strip() for parte in cabecera.split(",") if parte.strip())

    if len(entradas) < cantidad_proxies:
        # Cadena más corta que la topología declarada: no llegó por los
        # proxies esperados. No se confía en nada de este header.
        return socket_ip

    candidata = _solo_host(entradas[-cantidad_proxies])
    try:
        ipaddress.ip_address(candidata)
    except ValueError:
        return socket_ip
    return candidata


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
# S2 (2026-11-11): intentos con la contraseña ACTUAL equivocada al cambiarla desde Mi perfil, por cuenta.
bloqueo_cambio_password = BloqueoPorIntentos()
