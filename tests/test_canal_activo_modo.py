# tests/test_canal_activo_modo.py — Activar o desactivar un número de WhatsApp y cambiar su modo desde el panel nuevo
# (2026-11-11). El cuerpo dice el valor DESEADO (no «invertir»), así un doble clic no lo deja al revés. Datos sintéticos.

import inspect
import json

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from starlette.requests import Request

from agent import dashboard, memory as mem


def _request(cuerpo=None, crudo: bytes | None = None) -> Request:
    datos = crudo if crudo is not None else json.dumps(cuerpo if cuerpo is not None else {}).encode()
    enviado = False

    async def recibir():
        nonlocal enviado
        if enviado:
            return {"type": "http.disconnect"}
        enviado = True
        return {"type": "http.request", "body": datos, "more_body": False}

    return Request(scope={"type": "http", "method": "POST", "path": "/dashboard/canales-whatsapp/1/activo.json",
                          "headers": [(b"content-type", b"application/json")], "session": {}}, receive=recibir)


async def _escenario(codigo: str, modo="produccion"):
    negocio = await mem.crear_negocio(f"Negocio {codigo}", codigo)
    canal = await mem.crear_canal_whatsapp(
        nombre="Cálidda - Producción", phone_number_id=f"8{abs(hash(codigo)) % 10**10:010d}",
        access_token="EAA" + "t" * 40, modo=modo, negocio_id=negocio["id"],
    )
    admin = {"username": f"admin_{codigo}", "rol": "admin", "negocio_id": negocio["id"]}
    return negocio, canal, admin


async def _activo(canal, admin, cuerpo):
    return await dashboard.canal_whatsapp_activo_json(canal["id"], request=_request(cuerpo), usuario=admin, _csrf=None)


async def _modo(canal, admin, cuerpo):
    return await dashboard.canal_whatsapp_modo_json(canal["id"], request=_request(cuerpo), usuario=admin, _csrf=None)


async def _auditoria(negocio_id):
    async with mem.async_session() as s:
        return list((await s.execute(select(mem.RegistroAuditoria).where(
            mem.RegistroAuditoria.negocio_id == negocio_id, mem.RegistroAuditoria.accion == "canal_whatsapp_editado",
        ))).scalars().all())


# ── Activar / desactivar ───────────────────────────────────────────────────

async def test_desactivar_y_volver_a_activar_con_historial():
    negocio, canal, admin = await _escenario("act-1")
    r = json.loads((await _activo(canal, admin, {"activo": False})).body)
    assert r == {"ok": True, "cambio": True, "canal": {"id": canal["id"], "nombre": "Cálidda - Producción", "activo": False}}
    assert (await mem.obtener_canal_whatsapp(canal["id"]))["activo"] is False

    await _activo(canal, admin, {"activo": True})
    assert (await mem.obtener_canal_whatsapp(canal["id"]))["activo"] is True

    filas = await _auditoria(negocio["id"])
    assert [f.payload["cambios"] for f in filas] == [
        {"canal_whatsapp|Cálidda - Producción|activo": {"antes": "activo", "despues": "inactivo"}},
        {"canal_whatsapp|Cálidda - Producción|activo": {"antes": "inactivo", "despues": "activo"}},
    ]
    assert all(f.actor == admin["username"] and f.entidad_tipo == "configuracion" for f in filas)


async def test_pedir_lo_que_ya_esta_no_cambia_nada_ni_deja_historial():
    negocio, canal, admin = await _escenario("act-2")
    r = json.loads((await _activo(canal, admin, {"activo": True})).body)
    assert r["cambio"] is False
    assert await _auditoria(negocio["id"]) == []


@pytest.mark.parametrize("cuerpo", [{}, {"activo": "no"}, {"activo": 1}, {"activo": None}])
async def test_activo_exige_un_booleano_de_verdad(cuerpo):
    negocio, canal, admin = await _escenario("act-3")
    with pytest.raises(HTTPException) as exc:
        await _activo(canal, admin, cuerpo)
    assert exc.value.status_code == 422
    assert (await mem.obtener_canal_whatsapp(canal["id"]))["activo"] is True


# ── Modo ───────────────────────────────────────────────────────────────────

async def test_cambiar_de_modo_con_historial_y_sin_tocar_las_credenciales():
    negocio, canal, admin = await _escenario("mod-1")
    r = json.loads((await _modo(canal, admin, {"modo": "pruebas"})).body)
    assert r["cambio"] is True and r["canal"]["modo"] == "pruebas"
    guardado = await mem.obtener_canal_whatsapp(canal["id"])
    assert guardado["modo"] == "pruebas" and guardado["access_token"] == "EAA" + "t" * 40 and guardado["activo"] is True
    [fila] = await _auditoria(negocio["id"])
    assert fila.payload["cambios"] == {"canal_whatsapp|Cálidda - Producción|modo": {"antes": "produccion", "despues": "pruebas"}}


async def test_mismo_modo_no_cambia_nada():
    negocio, canal, admin = await _escenario("mod-2", modo="pruebas")
    assert json.loads((await _modo(canal, admin, {"modo": "pruebas"})).body)["cambio"] is False
    assert await _auditoria(negocio["id"]) == []


@pytest.mark.parametrize("cuerpo", [{}, {"modo": "Produccion"}, {"modo": "desarrollo"}, {"modo": True}, {"modo": None}])
async def test_modo_invalido(cuerpo):
    negocio, canal, admin = await _escenario("mod-3")
    with pytest.raises(HTTPException) as exc:
        await _modo(canal, admin, cuerpo)
    assert exc.value.status_code == 422
    assert (await mem.obtener_canal_whatsapp(canal["id"]))["modo"] == "produccion"


@pytest.mark.parametrize("crudo", [b"no es json", b"[true]"])
async def test_cuerpo_que_no_es_un_objeto(crudo):
    negocio, canal, admin = await _escenario("mod-4")
    for ruta in (dashboard.canal_whatsapp_activo_json, dashboard.canal_whatsapp_modo_json):
        with pytest.raises(HTTPException) as exc:
            await ruta(canal["id"], request=_request(crudo=crudo), usuario=admin, _csrf=None)
        assert exc.value.status_code == 422


# ── Aislamiento y permisos ─────────────────────────────────────────────────

async def test_un_canal_de_otro_negocio_da_404_y_no_cambia():
    negocio_a, canal_a, _ = await _escenario("aisl-a")
    _, _, admin_b = await _escenario("aisl-b")
    for llamada, cuerpo in ((_activo, {"activo": False}), (_modo, {"modo": "pruebas"})):
        with pytest.raises(HTTPException) as exc:
            await llamada(canal_a, admin_b, cuerpo)
        assert exc.value.status_code == 404
    guardado = await mem.obtener_canal_whatsapp(canal_a["id"])
    assert guardado["activo"] is True and guardado["modo"] == "produccion"
    assert await _auditoria(negocio_a["id"]) == []


@pytest.mark.parametrize("ruta", ["canal_whatsapp_activo_json", "canal_whatsapp_modo_json"])
@pytest.mark.parametrize("rol", ["supervisor", "asesor"])
async def test_solo_el_administrador(ruta, rol):
    dependencia = inspect.signature(getattr(dashboard, ruta)).parameters["usuario"].default.dependency
    with pytest.raises(HTTPException) as exc:
        await dependencia(usuario={"username": "x", "rol": rol, "negocio_id": "n"})
    assert exc.value.status_code == 403
