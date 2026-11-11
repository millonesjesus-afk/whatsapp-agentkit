# tests/test_canal_editar_token.py — Editar un número de WhatsApp desde el panel nuevo (2026-11-11): nombre y
# credenciales, con el token de acceso comprobado con Meta ANTES de guardarse. Lo que más importa aquí: un token
# nunca vuelve en una respuesta, en un mensaje de error ni en el historial. Meta se simula. Datos sintéticos.

import inspect
import json

import httpx
import pytest
from fastapi import HTTPException
from sqlalchemy import select
from starlette.requests import Request

from agent import dashboard, estado_canales, memory as mem

TOKEN_VIEJO = "EAAviejo" + "v" * 40
TOKEN_NUEVO = "EAAnuevo" + "n" * 40
SECRETO = "abcdef0123456789abcdef0123456789"


def _request(cuerpo=None, crudo: bytes | None = None) -> Request:
    datos = crudo if crudo is not None else json.dumps(cuerpo if cuerpo is not None else {}).encode()
    enviado = False

    async def recibir():
        nonlocal enviado
        if enviado:
            return {"type": "http.disconnect"}
        enviado = True
        return {"type": "http.request", "body": datos, "more_body": False}

    return Request(scope={"type": "http", "method": "POST", "path": "/dashboard/canales-whatsapp/1/editar.json",
                          "headers": [(b"content-type", b"application/json")], "session": {}}, receive=recibir)


async def _escenario(codigo: str):
    negocio = await mem.crear_negocio(f"Negocio {codigo}", codigo)
    canal = await mem.crear_canal_whatsapp(
        nombre="Cálidda - Producción", phone_number_id=f"9{abs(hash(codigo)) % 10**10:010d}",
        access_token=TOKEN_VIEJO, app_secret=SECRETO, negocio_id=negocio["id"],
    )
    admin = {"username": f"admin_{codigo}", "rol": "admin", "negocio_id": negocio["id"]}
    return negocio, canal, admin


class _MetaFalsa:
    """Responde a `get_con_reintentos` como Meta y anota lo que se le pidió."""

    def __init__(self, status=200, cuerpo=None, error=None):
        self.status, self.cuerpo, self.error, self.llamadas = status, cuerpo, error, []

    async def __call__(self, url, **kwargs):
        self.llamadas.append((url, kwargs))
        if self.error:
            raise self.error
        return httpx.Response(self.status, json=self.cuerpo if self.cuerpo is not None else {"display_phone_number": "+51 998 317 970"})


@pytest.fixture
def meta(monkeypatch):
    def instalar(**kw):
        falsa = _MetaFalsa(**kw)
        monkeypatch.setattr("agent.http_utils.get_con_reintentos", falsa)
        return falsa
    return instalar


async def _editar(canal, admin, cuerpo):
    return await dashboard.editar_canal_whatsapp_json(canal["id"], request=_request(cuerpo), usuario=admin, _csrf=None)


async def _auditoria(negocio_id):
    async with mem.async_session() as s:
        return list((await s.execute(select(mem.RegistroAuditoria).where(
            mem.RegistroAuditoria.negocio_id == negocio_id, mem.RegistroAuditoria.accion == "canal_whatsapp_editado",
        ))).scalars().all())


def _sin_secretos(texto: str):
    for secreto in (TOKEN_VIEJO, TOKEN_NUEVO, SECRETO):
        assert secreto not in texto


# ── Renovar el token ───────────────────────────────────────────────────────

async def test_renovar_token_lo_comprueba_con_meta_y_lo_guarda(meta):
    negocio, canal, admin = await _escenario("tok-1")
    falsa = meta()
    estado_canales._cache[str(canal["id"])] = (0.0, {"ok": False, "motivo": "viejo"})

    r = await _editar(canal, admin, {"access_token": f"  {TOKEN_NUEVO}  "})

    # se preguntó a Meta por ESTE número con el token NUEVO
    assert len(falsa.llamadas) == 1
    url, kw = falsa.llamadas[0]
    assert url.endswith("/" + canal["phone_number_id"])
    assert kw["headers"]["Authorization"] == f"Bearer {TOKEN_NUEVO}"
    # se guardó, renovó la fecha y limpió el estado en caché
    guardado = await mem.obtener_canal_whatsapp(canal["id"])
    assert guardado["access_token"] == TOKEN_NUEVO
    assert guardado["app_secret"] == SECRETO  # lo que no se mandó, no cambia
    assert guardado["token_renovado_en"] is not None
    assert str(canal["id"]) not in estado_canales._cache
    # la respuesta no trae ningún secreto
    cuerpo = json.loads(r.body)
    assert cuerpo["ok"] is True and cuerpo["canal"]["token_renovado_en"]
    _sin_secretos(r.body.decode())


async def test_el_historial_dice_que_cambio_el_token_pero_nunca_cual(meta):
    negocio, canal, admin = await _escenario("tok-2")
    meta()
    await _editar(canal, admin, {"access_token": TOKEN_NUEVO, "app_secret": "f" * 32})
    [fila] = await _auditoria(negocio["id"])
    assert fila.actor == admin["username"] and fila.entidad_tipo == "configuracion" and fila.entidad_id == str(canal["id"])
    cambios = fila.payload["cambios"]
    assert cambios == {
        "canal_whatsapp|Cálidda - Producción|access_token": {"antes": None, "despues": "cambiado"},
        "canal_whatsapp|Cálidda - Producción|app_secret": {"antes": None, "despues": "cambiado"},
    }
    _sin_secretos(json.dumps(fila.payload))
    assert "f" * 32 not in json.dumps(fila.payload)
    # y aparece en el historial de cambios que ve el administrador
    historial = await mem.listar_cambios_configuracion(negocio["id"])
    assert any(h["accion"] == "canal_whatsapp_editado" for h in historial)


@pytest.mark.parametrize("respuesta_meta, fragmento", [
    ({"error": {"code": 190, "message": "Error validating access token"}}, "no es válido"),
    ({"error": {"code": 100, "message": "Unsupported get request"}}, "no tiene permiso"),
])
async def test_si_meta_rechaza_el_token_no_se_guarda_nada(meta, respuesta_meta, fragmento):
    negocio, canal, admin = await _escenario("tok-3")
    meta(status=400, cuerpo=respuesta_meta)
    with pytest.raises(HTTPException) as exc:
        await _editar(canal, admin, {"access_token": TOKEN_NUEVO, "nombre": "Otro nombre"})
    assert exc.value.status_code == 422
    assert fragmento in exc.value.detail and "anterior sigue funcionando" in exc.value.detail
    _sin_secretos(exc.value.detail)
    intacto = await mem.obtener_canal_whatsapp(canal["id"])
    assert intacto["access_token"] == TOKEN_VIEJO and intacto["nombre"] == "Cálidda - Producción"
    assert await _auditoria(negocio["id"]) == []


async def test_si_meta_repite_el_token_en_su_mensaje_se_tapa(meta):
    negocio, canal, admin = await _escenario("tok-4")
    meta(status=400, cuerpo={"error": {"code": 1, "message": f"bad token {TOKEN_NUEVO}"}})
    with pytest.raises(HTTPException) as exc:
        await _editar(canal, admin, {"access_token": TOKEN_NUEVO})
    _sin_secretos(exc.value.detail)


async def test_si_no_se_puede_preguntar_a_meta_no_se_guarda(meta):
    negocio, canal, admin = await _escenario("tok-5")
    meta(error=httpx.ConnectError("sin red"))
    with pytest.raises(HTTPException) as exc:
        await _editar(canal, admin, {"access_token": TOKEN_NUEVO})
    assert exc.value.status_code == 502
    assert "No se pudo contactar a Meta" in exc.value.detail
    assert (await mem.obtener_canal_whatsapp(canal["id"]))["access_token"] == TOKEN_VIEJO


# ── Validaciones (sin preguntar a Meta) ────────────────────────────────────

@pytest.mark.parametrize("cuerpo, fragmento", [
    ({"access_token": "corto"}, "token de acceso no tiene un formato válido"),
    ({"access_token": "EAA con espacios dentro del token largo"}, "token de acceso no tiene un formato válido"),
    ({"app_secret": "abc def ghi jkl mno pqr"}, "App Secret no tiene un formato válido"),
    ({"access_token": 12345}, "formato válido"),
    ({"nombre": ""}, "no puede quedar vacío"),
    ({"nombre": "x" * 101}, "100 caracteres"),
    ({"nombre": "Cálidda - Producción"}, "No hay cambios"),
    ({"access_token": "", "app_secret": "   "}, "No hay cambios"),
    ({}, "No hay cambios"),
])
async def test_validaciones_sin_eco_del_valor(meta, cuerpo, fragmento):
    negocio, canal, admin = await _escenario("tok-6")
    falsa = meta()
    with pytest.raises(HTTPException) as exc:
        await _editar(canal, admin, cuerpo)
    assert exc.value.status_code == 422 and fragmento in exc.value.detail
    assert falsa.llamadas == []
    for v in cuerpo.values():
        if isinstance(v, str) and len(v) > 3:
            assert v not in exc.value.detail


@pytest.mark.parametrize("crudo", [b"no es json", b"[1, 2]"])
async def test_cuerpo_que_no_es_un_objeto(crudo):
    negocio, canal, admin = await _escenario("tok-7")
    with pytest.raises(HTTPException) as exc:
        await dashboard.editar_canal_whatsapp_json(canal["id"], request=_request(crudo=crudo), usuario=admin, _csrf=None)
    assert exc.value.status_code == 422


async def test_cambiar_solo_el_nombre_no_pregunta_a_meta(meta):
    negocio, canal, admin = await _escenario("tok-8")
    falsa = meta()
    r = await _editar(canal, admin, {"nombre": "  Cálidda Hogar  ", "access_token": ""})
    assert falsa.llamadas == []
    assert json.loads(r.body)["canal"]["nombre"] == "Cálidda Hogar"
    guardado = await mem.obtener_canal_whatsapp(canal["id"])
    assert guardado["nombre"] == "Cálidda Hogar" and guardado["access_token"] == TOKEN_VIEJO
    [fila] = await _auditoria(negocio["id"])
    assert fila.payload["cambios"] == {"canal_whatsapp|Cálidda Hogar|nombre": {"antes": "Cálidda - Producción", "despues": "Cálidda Hogar"}}


# ── Permisos y aislamiento ─────────────────────────────────────────────────

async def test_canal_de_otro_negocio_da_404_y_no_cambia(meta):
    _, canal_a, _ = await _escenario("tok-9a")
    _, _, admin_b = await _escenario("tok-9b")
    falsa = meta()
    with pytest.raises(HTTPException) as exc:
        await _editar(canal_a, admin_b, {"access_token": TOKEN_NUEVO})
    assert exc.value.status_code == 404
    assert falsa.llamadas == []
    assert (await mem.obtener_canal_whatsapp(canal_a["id"]))["access_token"] == TOKEN_VIEJO


@pytest.mark.parametrize("rol", ["supervisor", "asesor"])
async def test_solo_el_administrador(rol):
    dependencia = inspect.signature(dashboard.editar_canal_whatsapp_json).parameters["usuario"].default.dependency
    with pytest.raises(HTTPException) as exc:
        await dependencia(usuario={"username": "x", "rol": rol, "negocio_id": "n"})
    assert exc.value.status_code == 403
