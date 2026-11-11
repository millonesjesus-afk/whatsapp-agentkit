"""El panel antiguo se apaga: sus pantallas mandan al panel nuevo (2026-11-11).

Lo que NO debe pasar: que el redirect toque algo que el panel nuevo necesita (su API JSON, login, recuperar, sesión, WebSocket, archivos).
"""
import os

os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")   # para poder importar agent.main (la app real)
os.environ.setdefault("WHATSAPP_PROVIDER", "meta")

import httpx
import pytest
from fastapi import FastAPI

from agent import panel_antiguo
from agent.panel_antiguo import destino_panel_nuevo

NAVEGADOR = "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
BFF = "application/json"          # lo que manda siempre el servidor del panel nuevo (lib/bff.ts)
NUEVO = "https://maiek-frontend.vercel.app"


@pytest.fixture(autouse=True)
def _entorno(monkeypatch):
    monkeypatch.delenv("PANEL_ANTIGUO_REDIRIGIR", raising=False)
    monkeypatch.delenv("PANEL_NUEVO_URL", raising=False)


@pytest.mark.parametrize("ruta,esperado", [
    ("/dashboard", "/inicio"),
    ("/dashboard/", "/inicio"),
    ("/dashboard/metricas", "/inicio"),
    ("/dashboard/pipeline", "/pipeline"),
    ("/dashboard/lead/51999999999", "/conversaciones"),
    ("/dashboard/asesores", "/equipo"),
    ("/dashboard/campanas", "/campanas"),
    ("/dashboard/canales-whatsapp", "/configuracion?s=whatsapp"),
    ("/dashboard/catalogos", "/configuracion?s=biblioteca"),
    ("/dashboard/perfil", "/configuracion?s=perfil"),
])
def test_las_pantallas_del_panel_antiguo_redirigen_al_panel_nuevo(ruta, esperado):
    assert destino_panel_nuevo("GET", ruta, NAVEGADOR) == NUEVO + esperado


@pytest.mark.parametrize("ruta", [
    "/dashboard/pipeline", "/dashboard/lead/51999999999", "/dashboard/asesores", "/dashboard/canales-whatsapp",
    "/dashboard/inicio.json", "/dashboard/conversaciones", "/dashboard/productos",
])
def test_el_servidor_del_panel_nuevo_nunca_es_redirigido(ruta):
    """Las rutas compartidas (mismo URL: HTML para el antiguo, JSON para el nuevo) siguen dando JSON a quien lo pide."""
    assert destino_panel_nuevo("GET", ruta, BFF) is None


@pytest.mark.parametrize("ruta", [
    "/dashboard/login", "/dashboard/recuperar", "/dashboard/logout", "/dashboard/sesion", "/dashboard/ws",
    "/dashboard/archivo/12", "/dashboard/metricas/exportar.csv", "/dashboard/metricas/exportar.xlsx",
    "/dashboard/inicio.json", "/dashboard/calendario/citas.json", "/webhook", "/",
])
def test_lo_que_el_panel_nuevo_necesita_no_se_redirige_aunque_venga_de_un_navegador(ruta):
    assert destino_panel_nuevo("GET", ruta, NAVEGADOR) is None


def test_solo_se_redirigen_las_navegaciones_get():
    assert destino_panel_nuevo("POST", "/dashboard/lead/51999999999/resultado", NAVEGADOR) is None
    assert destino_panel_nuevo("POST", "/dashboard/pipeline", NAVEGADOR) is None


def test_un_cliente_sin_accept_no_se_redirige():
    assert destino_panel_nuevo("GET", "/dashboard/pipeline", "") is None
    assert destino_panel_nuevo("GET", "/dashboard/pipeline", "*/*") is None


def test_interruptor_apaga_el_redirect_sin_desplegar(monkeypatch):
    monkeypatch.setenv("PANEL_ANTIGUO_REDIRIGIR", "0")
    assert destino_panel_nuevo("GET", "/dashboard", NAVEGADOR) is None


def test_el_destino_se_puede_cambiar_por_variable(monkeypatch):
    monkeypatch.setenv("PANEL_NUEVO_URL", "https://panel.ejemplo.pe/")
    assert destino_panel_nuevo("GET", "/dashboard", NAVEGADOR) == "https://panel.ejemplo.pe/inicio"


async def test_el_middleware_responde_302_al_panel_nuevo_y_deja_pasar_lo_demas():
    app = FastAPI()
    panel_antiguo.registrar_redireccion_panel_antiguo(app)

    @app.get("/dashboard/pipeline")
    async def _pipeline():
        return {"datos": "json del panel nuevo"}

    @app.get("/dashboard/login")
    async def _login():
        return {"login": True}

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://prueba") as http:
        r = await http.get("/dashboard/pipeline", headers={"accept": NAVEGADOR}, follow_redirects=False)
        assert r.status_code == 302 and r.headers["location"] == NUEVO + "/pipeline"
        r = await http.get("/dashboard/pipeline", headers={"accept": BFF}, follow_redirects=False)
        assert r.status_code == 200 and r.json() == {"datos": "json del panel nuevo"}
        r = await http.get("/dashboard/login", headers={"accept": NAVEGADOR}, follow_redirects=False)
        assert r.status_code == 200


def test_la_app_real_lo_tiene_registrado():
    from agent.main import app

    nombres = [m.cls.__name__ for m in app.user_middleware]
    assert "BaseHTTPMiddleware" in nombres
    assert any(getattr(m.kwargs.get("dispatch"), "__name__", "") == "_redirigir_panel_antiguo" for m in app.user_middleware)
