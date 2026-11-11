# agent/panel_antiguo.py — Las pantallas del panel antiguo mandan al panel nuevo (2026-11-11).
#
# Decisión del dueño (2026-11-11): el panel antiguo (HTML de dashboard.py, en la dirección de Railway) se apaga en menos de una semana.
# NO se borra código: dashboard.py también sirve la API JSON del panel nuevo, el inicio de sesión y el WebSocket, y main.py importa de él.
# Lo único que cambia es la puerta: quien NAVEGA a una pantalla vieja con un navegador (Accept con text/html y sin application/json)
# recibe un redirect al panel nuevo. El servidor del panel nuevo (BFF) siempre pide `Accept: application/json`, así que nunca cae acá.
#
# Interruptor sin desplegar: la variable PANEL_ANTIGUO_REDIRIGIR=0 apaga el redirect (vuelve la pantalla vieja).
# Destino: PANEL_NUEVO_URL (por defecto el panel de producción).
#
# Quedan FUERA del redirect a propósito (siguen funcionando): login y recuperación de contraseña (el panel nuevo los sirve por rewrite),
# sesión, logout, WebSocket, archivos, todas las rutas `.json`, las exportaciones CSV/Excel y cualquier POST.

import os
import re

from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse

PANEL_NUEVO_URL_DEFECTO = "https://maiek-frontend.vercel.app"

# (ruta del panel antiguo, destino en el panel nuevo). Solo pantallas HTML conocidas del panel antiguo.
_DESTINOS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"^/dashboard/?$"), "/inicio"),
    (re.compile(r"^/dashboard/metricas/?$"), "/inicio"),
    (re.compile(r"^/dashboard/pipeline/?$"), "/pipeline"),
    (re.compile(r"^/dashboard/lead/[^/]+/?$"), "/conversaciones"),
    (re.compile(r"^/dashboard/asesores/?$"), "/equipo"),
    (re.compile(r"^/dashboard/campanas/?$"), "/campanas"),
    (re.compile(r"^/dashboard/canales-whatsapp/?$"), "/configuracion?s=whatsapp"),
    (re.compile(r"^/dashboard/catalogos/?$"), "/configuracion?s=biblioteca"),  # 2026-11-11: apartado propio
    (re.compile(r"^/dashboard/perfil/?$"), "/configuracion?s=perfil"),  # 2026-11-11: apartado propio
]


def _redirigir_activo() -> bool:
    return os.getenv("PANEL_ANTIGUO_REDIRIGIR", "1").strip().lower() not in ("0", "false", "no", "off")


def url_panel_nuevo() -> str:
    return (os.getenv("PANEL_NUEVO_URL") or PANEL_NUEVO_URL_DEFECTO).strip().rstrip("/")


def _navegacion_de_navegador(accept: str) -> bool:
    accept = (accept or "").lower()
    return "text/html" in accept and "application/json" not in accept


def destino_panel_nuevo(metodo: str, ruta: str, accept: str) -> str | None:
    """URL del panel nuevo a la que hay que mandar esta petición, o None si debe seguir su curso. PURA salvo por las variables de entorno."""
    if metodo != "GET" or not _redirigir_activo() or not _navegacion_de_navegador(accept):
        return None
    for patron, destino in _DESTINOS:
        if patron.match(ruta):
            return url_panel_nuevo() + destino
    return None


def registrar_redireccion_panel_antiguo(app: FastAPI) -> None:
    @app.middleware("http")
    async def _redirigir_panel_antiguo(request: Request, call_next):
        destino = destino_panel_nuevo(request.method, request.url.path, request.headers.get("accept", ""))
        if destino:
            return RedirectResponse(url=destino, status_code=302)
        return await call_next(request)
