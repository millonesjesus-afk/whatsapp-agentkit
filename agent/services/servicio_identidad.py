# agent/services/servicio_identidad.py — ServicioIdentidad
# Generado por AgentKit

"""
Usuarios, autenticación, autorización centralizada — Backend Architecture,
componente `ServicioIdentidad` ("Nuevo — hoy no existe como servicio, es
lógica repetida inline").

Backend Architecture §3 fija `requiere_rol(*roles)` como la única
dependencia de FastAPI para autorización, viviendo en `ServicioIdentidad`,
para reemplazar los ~26 checks de rol duplicados inline (CSA-Backend).

Fase 1 del Execution Plan (v1.2): esta sub-etapa aplica `requiere_rol`
primero a las rutas administrativas más críticas (canales, asesores),
exactamente como lo fija la Fase 1 de Backend Architecture §5 — no a los
~26 checks completos, eso queda para el segundo tramo de Backend, después
del protocolo de confianza de IA (Backend Architecture Fase 2).

`usuario_actual` y `NoAutenticado` se trasladan tal cual desde
agent/dashboard.py (antes `_usuario_actual`) — es la misma lógica de
resolución de sesión, ahora en el servicio al que Backend Architecture
dice que pertenece. `agent/dashboard.py` mantiene `_usuario_actual` como
alias del método de esta clase, así que ningún otro call site existente
cambia.
"""

from fastapi import Depends, HTTPException, Request

from agent.memory import obtener_usuario


class NoAutenticado(Exception):
    """Se lanza cuando no hay una sesión válida; el handler en main.py redirige al login."""
    pass


class ServicioIdentidad:
    """Resolución de usuario autenticado + autorización por rol,
    centralizada — ningún otro módulo de Backend implementa su propio
    check de rol inline para las rutas ya migradas."""

    async def usuario_actual(self, request: Request) -> dict:
        username = request.session.get("username")
        if not username:
            raise NoAutenticado()
        usuario = await obtener_usuario(username)
        if usuario is None:
            raise NoAutenticado()
        return usuario

    def requiere_rol(self, *roles: str):
        """Devuelve una dependencia de FastAPI: exige que el usuario
        autenticado tenga uno de los `roles` dados, o responde 403."""
        async def _verificar(usuario: dict = Depends(self.usuario_actual)) -> dict:
            if usuario["rol"] not in roles:
                raise HTTPException(status_code=403, detail="No tienes permiso para acceder a esta sección")
            return usuario
        return _verificar


# Instancia compartida por todo el proceso — mismo patrón que
# servicio_inteligencia y servicio_comercial.
servicio_identidad = ServicioIdentidad()
