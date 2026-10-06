"""Latido de los procesos programados (Cron de Railway) — 2026-10-05.

Cada script de `scripts/` termina con `asyncio.run(ejecutar_cron("<nombre>", main, <minutos>))`.
Eso no cambia lo que el script hace ni lo que imprime: solo anota en la tabla
`cron_ejecuciones` cuándo empezó, cuándo terminó, si salió bien y el resumen (lo que el script
imprimió), para que Inicio avise al admin si un proceso falló o dejó de correr.

Reglas:
  - El registro del latido NUNCA impide que el script haga su trabajo: si la base no contesta, solo
    se deja constancia en el log y el script sigue.
  - Si el script falla se anota ok=False con el error (truncado y sin secretos) y la excepción se
    vuelve a lanzar, así el exit 1 de siempre se conserva.
  - Si existe la variable de entorno HEALTHCHECK_URL_<NOMBRE_EN_MAYUSCULAS> (por ejemplo
    HEALTHCHECK_URL_BACKUP_POSTGRES, de un servicio como healthchecks.io o Better Stack), al
    terminar bien se le hace un GET a esa URL y, si falló, a <url>/fail (timeout 5 s). Ese aviso
    externo tampoco puede romper ni retrasar al script.
"""
import asyncio
import inspect
import logging
import os
import re
import sys
import urllib.request
from datetime import datetime
from urllib.parse import unquote, urlparse

logger = logging.getLogger("agentkit")

LIMITE_RESUMEN = 300
TIMEOUT_REGISTRO_SEG = 15
TIMEOUT_HEALTHCHECK_SEG = 5

# Variables cuyo valor jamás debe quedar escrito en el resumen de un error.
_VARIABLES_SECRETAS = (
    "DATABASE_URL", "S3_SECRET_ACCESS_KEY", "S3_ACCESS_KEY_ID", "PGPASSWORD", "ANTHROPIC_API_KEY",
    "CANAL_ENCRYPTION_KEY", "META_ACCESS_TOKEN", "META_APP_SECRET", "WHAPI_TOKEN",
)


class _Tee:
    """Escribe en la salida real Y guarda lo escrito, para poder usarlo de resumen."""

    def __init__(self, destino):
        self._destino = destino
        self.partes: list[str] = []

    def write(self, texto):
        self.partes.append(texto)
        return self._destino.write(texto)

    def flush(self):
        return self._destino.flush()

    def __getattr__(self, nombre):
        return getattr(self._destino, nombre)

    @property
    def texto(self) -> str:
        return "".join(self.partes)


def _sin_secretos(texto: str) -> str:
    """Quita contraseñas de URLs (esquema://usuario:clave@host) y cualquier valor de las variables
    secretas conocidas que aparezca tal cual en el texto."""
    valores = [os.environ.get(variable) for variable in _VARIABLES_SECRETAS]
    try:   # la contraseña dentro de DATABASE_URL, por si el texto la trae suelta
        valores.append(unquote(urlparse(os.environ.get("DATABASE_URL", "")).password or ""))
    except ValueError:
        pass
    for valor in valores:
        if valor and len(valor) >= 6:
            texto = texto.replace(valor, "***")
    return re.sub(r"([A-Za-z][A-Za-z0-9+.\-]*://)[^\s/@:]+:[^\s/@]+@", r"\1***@", texto)


def _resumir(texto: str) -> str | None:
    lineas = [linea.strip() for linea in (texto or "").splitlines() if linea.strip()]
    resumen = " | ".join(lineas)
    if len(resumen) > LIMITE_RESUMEN:
        resumen = resumen[: LIMITE_RESUMEN - 1] + "…"
    return resumen or None


def _resumen_de_error(error: BaseException) -> str:
    mensaje = str(error).strip() or repr(error)
    texto = _sin_secretos(f"{type(error).__name__}: {mensaje}")
    texto = " ".join(texto.split())
    return texto[: LIMITE_RESUMEN - 1] + "…" if len(texto) > LIMITE_RESUMEN else texto


def _url_healthcheck(nombre: str) -> str | None:
    return (os.environ.get(f"HEALTHCHECK_URL_{nombre.upper()}") or "").strip() or None


def _hacer_ping(url: str) -> None:
    with urllib.request.urlopen(url, timeout=TIMEOUT_HEALTHCHECK_SEG) as respuesta:  # noqa: S310 — URL que configura el dueño
        respuesta.read(1)


async def _avisar_healthcheck(nombre: str, ok: bool) -> None:
    """GET a la URL configurada (o a <url>/fail). Nunca lanza."""
    url = _url_healthcheck(nombre)
    if not url:
        return
    destino = url if ok else url.rstrip("/") + "/fail"
    try:
        await asyncio.wait_for(asyncio.to_thread(_hacer_ping, destino), timeout=TIMEOUT_HEALTHCHECK_SEG + 2)
    except BaseException as e:  # noqa: BLE001 — incluye el timeout; ni siquiera se muestra la URL (puede llevar una clave)
        if isinstance(e, (KeyboardInterrupt, SystemExit)):
            raise
        logger.warning(f"Cron {nombre}: no se pudo avisar al healthcheck ({type(e).__name__})")


async def _registrar_inicio(nombre: str, inicio: datetime) -> int | None:
    try:
        from agent.memory import esperar_base_de_datos, registrar_inicio_cron

        async def _intento() -> int:
            await esperar_base_de_datos(intentos=5, pausa_seg=1.0)
            return await registrar_inicio_cron(nombre, inicio)

        return await asyncio.wait_for(_intento(), timeout=TIMEOUT_REGISTRO_SEG)
    except Exception as e:  # noqa: BLE001 — el latido no puede impedir el trabajo del script
        logger.warning(f"Cron {nombre}: no se pudo registrar el inicio del latido ({type(e).__name__}: {_sin_secretos(str(e))[:120]})")
        return None


async def _registrar_fin(nombre: str, ejecucion_id: int | None, inicio: datetime, ok: bool, resumen: str | None) -> None:
    try:
        from agent.memory import registrar_fin_cron

        await asyncio.wait_for(registrar_fin_cron(ejecucion_id, nombre, inicio, ok, resumen), timeout=TIMEOUT_REGISTRO_SEG)
    except Exception as e:  # noqa: BLE001
        logger.warning(f"Cron {nombre}: no se pudo registrar el fin del latido ({type(e).__name__}: {_sin_secretos(str(e))[:120]})")


def _avisar_si_el_intervalo_no_coincide(nombre: str, intervalo_esperado_min: int) -> None:
    try:
        from agent.memory import CRONES_ESPERADOS

        esperado = CRONES_ESPERADOS.get(nombre)
        if esperado and esperado[1] != intervalo_esperado_min:
            logger.warning(
                f"Cron {nombre}: el script declara {intervalo_esperado_min} min pero el panel vigila {esperado[1]} min "
                f"(agent/memory.py::CRONES_ESPERADOS) — alinéalos."
            )
    except Exception:  # noqa: BLE001
        pass


async def ejecutar_cron(nombre: str, main, intervalo_esperado_min: int) -> None:
    """Corre `main` (una función async, o una común) registrando el latido.

    `intervalo_esperado_min`: cada cuántos minutos debería correr este proceso; el panel avisa si
    pasan más de el doble sin una corrida exitosa. La excepción de `main` (incluido `SystemExit`)
    se registra y se vuelve a lanzar tal cual."""
    _avisar_si_el_intervalo_no_coincide(nombre, intervalo_esperado_min)
    inicio = datetime.utcnow()
    ejecucion_id = await _registrar_inicio(nombre, inicio)

    tee = _Tee(sys.stdout)
    original = sys.stdout
    sys.stdout = tee
    try:
        resultado = main()
        if inspect.isawaitable(resultado):
            await resultado
    except BaseException as error:
        sys.stdout = original
        await _registrar_fin(nombre, ejecucion_id, inicio, False, _resumen_de_error(error))
        await _avisar_healthcheck(nombre, False)
        raise
    finally:
        sys.stdout = original
    await _registrar_fin(nombre, ejecucion_id, inicio, True, _resumir(tee.texto))
    await _avisar_healthcheck(nombre, True)
