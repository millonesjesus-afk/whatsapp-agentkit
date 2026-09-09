# tests/test_gate_logout_sesion.py — GATE 1: Seguridad de Sesión (Nueva
# Experiencia). El hallazgo de auditoría fue puramente de frontend
# ("Cerrar sesión" llamaba a `reautenticar()` en vez de `POST /api/logout`,
# la cookie nunca se invalidaba) — el mecanismo real de invalidación del
# backend (`POST /dashboard/logout`) ya existía y ya funcionaba, así que
# estos tests demuestran ese comportamiento real (Tests 1/3/4 de la
# instrucción del Gate), no lo inventan.
#
# Mismo criterio que el resto de la suite: se llama a la función de la ruta
# directamente en vez de un TestClient HTTP (ningún test de este repo usa
# uno) — acá con un stand-in mínimo de `Request` porque `logout()` solo
# toca `request.session`, nunca el resto de la API de Starlette.

import pytest

from agent import dashboard, memory as mem
from agent.services.servicio_identidad import NoAutenticado, servicio_identidad


class _RequestConSesion:
    """Duck-type mínimo de `starlette.requests.Request` — `logout()` y
    `usuario_actual()` solo leen/escriben `.session` (un dict), nunca el
    resto de la superficie de Request, así que no hace falta un ASGI scope
    real para probar el comportamiento real de invalidación."""

    def __init__(self, session: dict):
        self.session = session


async def _negocio_con_admin(codigo: str):
    negocio = await mem.crear_negocio(f"Negocio {codigo}", codigo)
    await mem.crear_usuario(f"admin_{codigo}", "pw12345", "Admin", "admin", negocio["id"])
    return negocio


async def test_sesion_valida_resuelve_usuario_y_logout_la_invalida_realmente():
    await _negocio_con_admin("lg-a")
    request = _RequestConSesion({"username": "admin_lg-a"})

    # Test 1 — usuario autenticado puede "acceder a una ruta protegida":
    # usuario_actual() es la dependencia real que protege cada ruta.
    usuario = await servicio_identidad.usuario_actual(request)
    assert usuario["username"] == "admin_lg-a"
    # Sembrado lazy real de ServicioIdentidad — confirma que esta sesión
    # está genuinamente activa, no un dict vacío que por casualidad pasa.
    assert "csrf_token" in request.session

    # Test 3 — logout invalida la sesión de verdad (no solo un flag de UI):
    # request.session.clear() es EXACTAMENTE lo que ejecuta la ruta real.
    await dashboard.logout(request, _csrf=None)
    assert request.session == {}

    # Test 4 — después del logout, la misma sesión ya NO resuelve ningún
    # usuario: la ruta protegida queda inaccesible, server-side, no por UI.
    with pytest.raises(NoAutenticado):
        await servicio_identidad.usuario_actual(request)


async def test_logout_es_idempotente_sobre_una_sesion_ya_vacia():
    """Cerrar sesión sin sesión activa no debe fallar — mismo criterio que
    ya documenta `app/api/logout/route.ts` en el frontend (idempotente)."""
    request = _RequestConSesion({})
    await dashboard.logout(request, _csrf=None)
    assert request.session == {}


async def test_logout_no_afecta_una_sesion_de_otro_negocio():
    """Cross-tenant: invalidar la sesión de un Request no debe tocar la de
    otro — cada Request tiene su propio dict de sesión, sin estado
    compartido a nivel de proceso (confirma que no hay un caché global)."""
    await _negocio_con_admin("lg-b")
    await _negocio_con_admin("lg-c")
    request_b = _RequestConSesion({"username": "admin_lg-b"})
    request_c = _RequestConSesion({"username": "admin_lg-c"})

    await servicio_identidad.usuario_actual(request_b)
    await servicio_identidad.usuario_actual(request_c)

    await dashboard.logout(request_b, _csrf=None)

    assert request_b.session == {}
    assert request_c.session.get("username") == "admin_lg-c"
    usuario_c = await servicio_identidad.usuario_actual(request_c)
    assert usuario_c["username"] == "admin_lg-c"
