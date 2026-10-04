# tests/test_detectar_zona_cuenta_meta.py — 2026-10-04: la cuota gratis mensual
# de Meta se reinicia a medianoche de la zona horaria de la CUENTA de WhatsApp
# Business. Se lee de Meta (`timezone_id` de la WABA) y se guarda como
# `meta_zona_horaria_mes`; si no se puede, no se adivina y se elige a mano.

import json
import os

os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")
os.environ.setdefault("WHATSAPP_PROVIDER", "meta")

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from agent import dashboard
from agent import memory as mem
from agent.meta_timezones import TIMEZONE_ID_A_IANA, zona_iana_de_meta


class _Respuesta:
    def __init__(self, status: int, cuerpo: dict):
        self.status_code, self._cuerpo, self.text = status, cuerpo, json.dumps(cuerpo)

    def json(self):
        return self._cuerpo


def _peticion(cuerpo) -> Request:
    datos = json.dumps(cuerpo).encode()
    enviado = False

    async def recibir():
        nonlocal enviado
        if enviado:
            return {"type": "http.disconnect"}
        enviado = True
        return {"type": "http.request", "body": datos, "more_body": False}

    return Request({"type": "http", "method": "POST", "path": "/x", "headers": [], "query_string": b"",
                    "client": ("203.0.113.9", 1)}, recibir)


async def _negocio_con_canal(codigo: str, waba_id: str = "777000111"):
    n = await mem.crear_negocio(f"Negocio {codigo}", codigo)
    await mem.crear_canal_whatsapp("Canal", f"1000{codigo}", access_token="tok-secreto", waba_id=waba_id, negocio_id=n["id"])
    return n, {"negocio_id": n["id"], "rol": "admin"}


def test_la_tabla_de_ids_mapea_a_zonas_que_zoneinfo_entiende():
    from zoneinfo import ZoneInfo
    try:
        ZoneInfo("America/Lima")
    except Exception:
        pytest.skip("este sistema no tiene la base de zonas horarias")
    for zona in TIMEZONE_ID_A_IANA.values():
        ZoneInfo(zona)
    assert zona_iana_de_meta("103") == "America/Lima" and zona_iana_de_meta(103) == "America/Lima"
    assert zona_iana_de_meta("999999") is None


async def test_detecta_la_zona_de_la_cuenta_y_la_guarda_sin_enviar_el_token_fuera_del_header(monkeypatch):
    n, admin = await _negocio_con_canal("901")
    vistos = {}

    async def falso_get(url, **kwargs):
        vistos.update(url=url, **kwargs)
        return _Respuesta(200, {"timezone_id": "103", "id": "777000111"})

    monkeypatch.setattr(dashboard, "get_con_reintentos", falso_get)
    r = await dashboard.uso_mensajes_detectar_zona_json(_peticion({}), usuario=admin, _csrf=None)
    datos = json.loads(r.body)
    assert datos == {"ok": True, "zona_horaria": "America/Lima", "timezone_id": "103", "guardada": True}
    assert vistos["url"].endswith("/777000111") and vistos["params"] == {"fields": "timezone_id"}
    assert "tok-secreto" not in vistos["url"] and "tok-secreto" not in r.body.decode()
    assert await mem.obtener_configuracion("meta_zona_horaria_mes", "UTC", negocio_id=n["id"]) == "America/Lima"


async def test_con_guardar_false_solo_informa(monkeypatch):
    n, admin = await _negocio_con_canal("902")

    async def falso_get(url, **kwargs):
        return _Respuesta(200, {"timezone_id": "43"})

    monkeypatch.setattr(dashboard, "get_con_reintentos", falso_get)
    r = await dashboard.uso_mensajes_detectar_zona_json(_peticion({"guardar": False}), usuario=admin, _csrf=None)
    assert json.loads(r.body)["guardada"] is False
    assert await mem.obtener_configuracion("meta_zona_horaria_mes", "UTC", negocio_id=n["id"]) == "UTC"


async def test_sin_waba_id_explica_que_falta_y_no_llama_a_meta(monkeypatch):
    n = await mem.crear_negocio("Negocio 903", "903")
    await mem.crear_canal_whatsapp("Canal", "1000903", access_token="t", negocio_id=n["id"])   # sin waba_id

    async def no_debe_llamarse(url, **kwargs):
        raise AssertionError("no debería llamar a Meta")

    monkeypatch.setattr(dashboard, "get_con_reintentos", no_debe_llamarse)
    with pytest.raises(HTTPException) as e:
        await dashboard.uso_mensajes_detectar_zona_json(_peticion({}), usuario={"negocio_id": n["id"], "rol": "admin"}, _csrf=None)
    assert e.value.status_code == 409 and "waba_id" in e.value.detail


@pytest.mark.parametrize("respuesta,estado", [
    (_Respuesta(400, {"error": {"message": "(#100) permiso"}}), 502),
    (_Respuesta(200, {"timezone_id": "999999"}), 422),
    (_Respuesta(200, {}), 422),
])
async def test_un_error_de_meta_o_un_id_desconocido_no_adivina_ni_guarda(monkeypatch, respuesta, estado):
    n, admin = await _negocio_con_canal("904")

    async def falso_get(url, **kwargs):
        return respuesta

    monkeypatch.setattr(dashboard, "get_con_reintentos", falso_get)
    with pytest.raises(HTTPException) as e:
        await dashboard.uso_mensajes_detectar_zona_json(_peticion({}), usuario=admin, _csrf=None)
    assert e.value.status_code == estado
    assert await mem.obtener_configuracion("meta_zona_horaria_mes", "UTC", negocio_id=n["id"]) == "UTC"


def test_la_ruta_exige_csrf():
    ruta = next(r for r in dashboard.router.routes if getattr(r, "path", "").endswith("/uso-mensajes/detectar-zona.json"))
    assert ruta.methods == {"POST"}
    assert "verificar_csrf" in {d.call.__name__ for d in ruta.dependant.dependencies}
