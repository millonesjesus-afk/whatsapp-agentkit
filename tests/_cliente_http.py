# tests/_cliente_http.py — Cliente HTTP de pruebas sobre el router REAL del panel (no es un test; pytest no lo recoge).
#
# Monta `dashboard.router` en una app mínima: la sesión lleva un token CSRF fijo (`TOKEN`) y el usuario de la sesión se
# inyecta con `.con(usuario)` en lugar de resolverlo desde una cookie de login. Lo demás es lo que ejecutaría FastAPI en
# producción: la dependencia `requiere_rol` de cada ruta (403 por rol), `verificar_csrf` (403 sin token o con token
# inválido) y el cuerpo de la ruta. Sirve para probar permisos de punta a punta sin TestClient ni cookies reales.

import httpx
from fastapi import FastAPI
from starlette.middleware.sessions import SessionMiddleware

from agent import dashboard
from agent.services.servicio_identidad import servicio_identidad

TOKEN = "token-csrf-de-prueba"


class ClienteHttp:
    def __init__(self):
        self.usuario = None
        app = FastAPI()

        @app.middleware("http")
        async def _sesion(request, call_next):
            request.session["csrf_token"] = TOKEN
            return await call_next(request)

        app.add_middleware(SessionMiddleware, secret_key="clave-de-prueba")
        app.include_router(dashboard.router)
        app.dependency_overrides[servicio_identidad.usuario_actual] = lambda: self.usuario
        self.http = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://prueba")

    def con(self, usuario):
        """Una vista del cliente que siempre actúa como `usuario` (varias vistas conviven en una misma prueba)."""
        return _Vista(self, usuario)

    async def cerrar(self):
        await self.http.aclose()


class _Vista:
    def __init__(self, cliente: ClienteHttp, usuario: dict):
        self._c, self._usuario = cliente, usuario

    async def get(self, ruta, **params):
        self._c.usuario = self._usuario
        return await self._c.http.get(ruta, params=params)

    async def post(self, ruta, cuerpo=None, token=TOKEN):
        self._c.usuario = self._usuario
        return await self._c.http.post(ruta, json=cuerpo if cuerpo is not None else {}, headers={"X-CSRF-Token": token} if token else {})

    async def delete(self, ruta, token=TOKEN, **params):
        self._c.usuario = self._usuario
        return await self._c.http.delete(ruta, params=params, headers={"X-CSRF-Token": token} if token else {})
