"""Login y recuperar ya no tienen pantalla en el servidor (2026-11-11): el formulario vive en el panel nuevo.

El proceso (POST /dashboard/login, /logout, /recuperar) NO cambia: el intermediario del panel nuevo (app/api/login, logout, recuperar) lo llama,
lee la ubicación del 303 y reenvía la cookie. Estas pruebas recorren el flujo de punta a punta sobre la APP REAL (agent.main.app):
ingresar, equivocar la clave, cerrar sesión, sesión vencida y recuperar contraseña.
"""
import os

os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")   # para poder importar agent.main (la app real)
os.environ.setdefault("WHATSAPP_PROVIDER", "meta")

import httpx
import pytest

from agent import dashboard, memory as mem
from agent.rate_limit import BloqueoPorIntentos, LimitadorTasa

NUEVO = "https://maiek-frontend.vercel.app"
NAVEGADOR = "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
JSON = "application/json"
COOKIE = "gaso_panel_sesion"


@pytest.fixture(autouse=True)
def _aislar(monkeypatch):
    monkeypatch.delenv("PANEL_NUEVO_URL", raising=False)
    monkeypatch.setattr(dashboard, "limitador_login", LimitadorTasa())      # el límite por IP no se arrastra entre pruebas
    monkeypatch.setattr(dashboard, "bloqueo_login", BloqueoPorIntentos())


@pytest.fixture
def cliente():
    from agent.main import app

    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://prueba")


async def _usuario(username="ana_login", clave="clave-de-prueba-123"):
    negocio = await mem.crear_negocio("Negocio login", "login-e2e")
    await mem.crear_usuario(username, clave, "Ana", "admin", negocio_id=negocio["id"])
    return username, clave


# ── Las pantallas ya no existen en el servidor: mandan al panel nuevo ──────────────────────────────────────────────

@pytest.mark.parametrize("ruta,destino", [("/dashboard/login", "/login"), ("/dashboard/recuperar", "/recuperar")])
@pytest.mark.parametrize("accept", [NAVEGADOR, JSON, "*/*", ""])
async def test_las_pantallas_de_login_y_recuperar_mandan_al_panel_nuevo(cliente, ruta, destino, accept):
    async with cliente as http:
        r = await http.get(ruta, headers={"accept": accept} if accept else {}, follow_redirects=False)
    assert r.status_code == 302 and r.headers["location"] == NUEVO + destino
    assert "<form" not in r.text                                              # ya no se dibuja ningún formulario


# ── Ingresar ──────────────────────────────────────────────────────────────────────────────────────────────────────

async def test_ingresar_con_la_clave_correcta_da_303_a_dashboard_y_la_cookie(cliente):
    usuario, clave = await _usuario()
    async with cliente as http:
        r = await http.post("/dashboard/login", data={"username": usuario, "password": clave}, follow_redirects=False)
        assert r.status_code == 303 and r.headers["location"] == "/dashboard"   # lo que lee app/api/login para decir «ok»
        assert COOKIE in r.headers.get("set-cookie", "")
        # La sesión sirve: el panel nuevo la usa en /dashboard/sesion.
        s = await http.get("/dashboard/sesion", headers={"accept": JSON})
        assert s.status_code == 200 and s.json()["usuario"]["username"] == usuario


async def test_ingresar_con_la_clave_equivocada_vuelve_con_el_mensaje_en_la_ubicacion(cliente):
    usuario, _ = await _usuario()
    async with cliente as http:
        r = await http.post("/dashboard/login", data={"username": usuario, "password": "otra-clave"}, follow_redirects=False)
        assert r.status_code == 303
        assert r.headers["location"].startswith("/dashboard/login?error=")        # app/api/login extrae el mensaje de ahí
        assert "incorrectos" in httpx.URL(r.headers["location"]).params["error"]
        assert COOKIE not in r.headers.get("set-cookie", "")
        s = await http.get("/dashboard/sesion", headers={"accept": JSON})
        assert s.status_code == 401                                              # no quedó sesión


async def test_demasiados_intentos_siguen_bloqueando(cliente):
    usuario, _ = await _usuario()
    async with cliente as http:
        for _ in range(5):
            await http.post("/dashboard/login", data={"username": usuario, "password": "mal"}, follow_redirects=False)
        r = await http.post("/dashboard/login", data={"username": usuario, "password": "mal"}, follow_redirects=False)
    assert "bloqueada" in httpx.URL(r.headers["location"]).params["error"].lower()


# ── Cerrar sesión ───────────────────────────────────────────────────────────────────────────────────────────────

async def test_cerrar_sesion_limpia_la_cookie_y_ya_no_hay_sesion(cliente):
    usuario, clave = await _usuario()
    async with cliente as http:
        await http.post("/dashboard/login", data={"username": usuario, "password": clave}, follow_redirects=False)
        csrf = (await http.get("/dashboard/sesion", headers={"accept": JSON})).json()["csrf_token"]
        r = await http.post("/dashboard/logout", headers={"x-csrf-token": csrf}, follow_redirects=False)
        assert r.status_code == 303 and r.headers["location"] == "/dashboard/login"   # app/api/logout lo lee como «cerrada»
        s = await http.get("/dashboard/sesion", headers={"accept": JSON})
        assert s.status_code == 401


async def test_cerrar_sesion_sin_csrf_se_rechaza(cliente):
    usuario, clave = await _usuario()
    async with cliente as http:
        await http.post("/dashboard/login", data={"username": usuario, "password": clave}, follow_redirects=False)
        r = await http.post("/dashboard/logout", follow_redirects=False)
        assert r.status_code == 403


# ── Sesión vencida o inexistente ────────────────────────────────────────────────────────────────────────────────

async def test_sin_sesion_el_panel_nuevo_recibe_401_json(cliente):
    """El intermediario del panel nuevo siempre pide JSON: recibe 401 (no un redirect) y lleva al usuario a su propio /login."""
    async with cliente as http:
        r = await http.get("/dashboard/inicio.json", headers={"accept": JSON}, follow_redirects=False)
    assert r.status_code == 401 and r.json()["codigo"] == "HTTP_401"


async def test_sin_sesion_un_navegador_va_al_login_del_panel_nuevo(cliente):
    async with cliente as http:
        r = await http.get("/dashboard/inicio.json", headers={"accept": NAVEGADOR}, follow_redirects=False)
    assert r.status_code in (302, 307) and r.headers["location"] == NUEVO + "/login"


# ── Recuperar contraseña ────────────────────────────────────────────────────────────────────────────────────────

async def test_recuperar_avisa_al_admin_y_responde_igual_exista_o_no_el_usuario(cliente, monkeypatch):
    usuario, _ = await _usuario()
    avisados = []

    async def _avisar(username):
        avisados.append(username)

    monkeypatch.setattr(dashboard, "notificar_solicitud_reseteo", _avisar)
    async with cliente as http:
        existe = await http.post("/dashboard/recuperar", data={"username": usuario}, follow_redirects=False)
        no_existe = await http.post("/dashboard/recuperar", data={"username": "nadie"}, follow_redirects=False)
    assert existe.status_code == no_existe.status_code == 303
    assert existe.headers["location"] == no_existe.headers["location"] == "/dashboard/recuperar?enviado=1"   # app/api/recuperar lo lee
    assert avisados == [usuario]                                                                           # solo avisa si existe
