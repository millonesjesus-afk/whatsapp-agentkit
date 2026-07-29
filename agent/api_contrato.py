# agent/api_contrato.py — Contrato interno de plataforma (API Architecture)
# Generado por AgentKit

"""
`request_id` (generado en el borde de cada solicitud, propagado a logs y
a toda respuesta) y el modelo uniforme de errores `{codigo, mensaje,
detalle, request_id}` — API Architecture, Decisiones locales ya
`Objetivo`.

Esto es aditivo sobre el borde HTTP de la aplicación — no redefine el
contrato interno con AI Architecture, que ya es la interfaz de función de
`ServicioInteligencia` (API Architecture Sec.1: "el 'contrato interno' es,
literalmente, la interfaz de función ya fijada ahí").

`codigo` usa un valor por defecto derivado del status HTTP (`HTTP_404`,
etc.) — API Architecture exige un código string estable, no solo el
status, pero no exige que cada uno de los ~50 sitios `raise
HTTPException(...)` ya existentes tenga un código semántico propio desde
el día uno. Códigos específicos (`LEAD_NO_ENCONTRADO`, etc.) se agregan
de forma incremental donde aporten valor real, sin tocar el resto.
"""

import contextvars
import logging
import uuid

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

_request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="-")

logger = logging.getLogger("agentkit")


class FiltroRequestId(logging.Filter):
    """Inyecta el request_id de la solicitud actual (si hay una) en cada
    registro de log — así cualquier logger.info/warning/error ya
    existente queda correlacionado con su solicitud, sin tener que tocar
    cada sitio donde ya se loguea."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = _request_id_var.get()
        return True


def _codigo_desde_status(status_code: int) -> str:
    return f"HTTP_{status_code}"


def registrar_contrato_interno(app: FastAPI) -> None:
    """Registra el middleware de request_id y los exception handlers del
    modelo uniforme de errores — se llama una sola vez al armar la app."""

    @app.middleware("http")
    async def middleware_request_id(request: Request, call_next):
        # Propaga el request_id del consumidor si ya trae uno (header
        # X-Request-Id), o genera uno nuevo — API Architecture Sec.3.
        # No se resetea el contextvar al final a propósito: si una
        # excepción no controlada escapa hasta ServerErrorMiddleware (fuera
        # de este middleware), su handler todavía necesita poder leer este
        # mismo request_id — resetear acá lo borraría antes de que llegue.
        # Cada solicitud corre en su propio Task de asyncio, así que no hay
        # fuga real entre solicitudes distintas.
        request_id = request.headers.get("X-Request-Id") or str(uuid.uuid4())
        _request_id_var.set(request_id)
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers["X-Request-Id"] = request_id
        return response

    @app.exception_handler(HTTPException)
    async def manejador_error_uniforme(request: Request, exc: HTTPException):
        request_id = _request_id_var.get()
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "codigo": _codigo_desde_status(exc.status_code),
                "mensaje": str(exc.detail),
                "detalle": None,
                "request_id": request_id,
            },
            headers={"X-Request-Id": request_id, **(exc.headers or {})},
        )

    @app.exception_handler(Exception)
    async def manejador_error_no_controlado(request: Request, exc: Exception):
        request_id = _request_id_var.get()
        logger.error(f"Error no controlado: {exc}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={
                "codigo": "HTTP_500",
                "mensaje": "Error interno del servidor",
                "detalle": None,
                "request_id": request_id,
            },
            headers={"X-Request-Id": request_id},
        )
