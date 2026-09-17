# tests/test_asesores_json_selector.py — GET /dashboard/asesores ahora
# negocia contenido (mismo criterio que /pipeline, _pide_json_explicitamente)
# y devuelve `listar_asesores()` en JSON para el selector de reasignación de
# la Nueva Experiencia (`app/api/asesores/route.ts` en maiek-frontend).
#
# Hallazgo del usuario (2026-09-16): "cuando quiero reasignar un lead no
# salen los asesores disponibles que estén habilitados" — antes de este
# fix, esa ruta no existía en JSON y el frontend DERIVABA la lista de los
# asesor_asignado ya presentes en el pipeline, así que un asesor recién
# creado o sin cartera hoy nunca aparecía, sin importar si estaba
# disponible/habilitado. Este test prueba exactamente ese caso: un asesor
# disponible, sin ningún lead asignado todavía, debe aparecer.

import inspect

from fastapi import HTTPException, Request
from sqlalchemy import select

from agent import dashboard, memory as mem


def _dependencia_usuario(func):
    parametro = inspect.signature(func).parameters["usuario"]
    return parametro.default.dependency


def _request_con_accept(accept: str) -> Request:
    return Request(scope={
        "type": "http", "method": "GET", "path": "/dashboard/asesores",
        "headers": [(b"accept", accept.encode())],
        "session": {},
    })


async def _negocio_con_asesores(codigo: str):
    negocio = await mem.crear_negocio(f"Negocio {codigo}", codigo)
    await mem.crear_usuario(f"admin_{codigo}", "pw12345", "Admin", "admin", negocio["id"])
    await mem.crear_usuario(
        f"ase_disp_{codigo}", "pw12345", "Asesor Disponible", "asesor", negocio["id"],
    )
    await mem.crear_usuario(
        f"ase_nodisp_{codigo}", "pw12345", "Asesor No Disponible", "asesor", negocio["id"],
    )
    async with mem.async_session() as session:
        result = await session.execute(
            select(mem.Usuario).where(
                mem.Usuario.negocio_id == negocio["id"],
                mem.Usuario.username == f"ase_nodisp_{codigo}",
            )
        )
        u = result.scalar_one()
        u.disponible = False
        await session.commit()
    return negocio


async def test_json_incluye_asesor_disponible_sin_ningun_lead_asignado():
    negocio = await _negocio_con_asesores("g-json-1")
    dependencia = _dependencia_usuario(dashboard.gestionar_asesores)
    usuario = await dependencia(usuario={
        "username": f"admin_g-json-1", "rol": "admin", "negocio_id": negocio["id"],
    })

    respuesta = await dashboard.gestionar_asesores(
        request=_request_con_accept("application/json"), usuario=usuario,
    )

    cuerpo = respuesta.body.decode() if hasattr(respuesta, "body") else None
    import json as _json
    datos = _json.loads(cuerpo)
    usernames = {a["username"] for a in datos["asesores"]}
    assert "ase_disp_g-json-1" in usernames
    disponibles = {a["username"]: a["disponible"] for a in datos["asesores"]}
    assert disponibles["ase_disp_g-json-1"] is True
    assert disponibles["ase_nodisp_g-json-1"] is False


async def test_json_no_mezcla_asesores_de_otro_negocio():
    negocio_a = await _negocio_con_asesores("g-json-2a")
    await _negocio_con_asesores("g-json-2b")
    dependencia = _dependencia_usuario(dashboard.gestionar_asesores)
    usuario = await dependencia(usuario={
        "username": "admin_g-json-2a", "rol": "admin", "negocio_id": negocio_a["id"],
    })

    respuesta = await dashboard.gestionar_asesores(
        request=_request_con_accept("application/json"), usuario=usuario,
    )
    import json as _json
    datos = _json.loads(respuesta.body.decode())
    usernames = {a["username"] for a in datos["asesores"]}
    assert usernames == {"ase_disp_g-json-2a", "ase_nodisp_g-json-2a"}


async def test_sin_accept_json_sigue_devolviendo_html():
    negocio = await _negocio_con_asesores("g-json-3")
    dependencia = _dependencia_usuario(dashboard.gestionar_asesores)
    usuario = await dependencia(usuario={
        "username": "admin_g-json-3", "nombre": "Admin", "rol": "admin", "negocio_id": negocio["id"],
    })

    respuesta = await dashboard.gestionar_asesores(
        request=_request_con_accept("text/html"), usuario=usuario,
    )
    # Sin Accept:application/json explícito, la ruta sigue devolviendo el
    # string HTML del panel legacy (FastAPI lo envuelve en HTMLResponse por
    # el response_class de la ruta) — no el JSONResponse de la rama nueva.
    assert isinstance(respuesta, str)
    assert "<table" in respuesta


async def test_asesor_no_puede_ver_el_selector():
    dependencia = _dependencia_usuario(dashboard.gestionar_asesores)
    try:
        await dependencia(usuario={"username": "ase1", "rol": "asesor", "negocio_id": "neg-1"})
        assert False, "debía lanzar HTTPException"
    except HTTPException as e:
        assert e.status_code == 403


async def test_asesor_eliminado_ya_no_sale_en_el_selector():
    """Segundo hallazgo del mismo reporte: un asesor ya eliminado
    (`eliminar_usuario`, soft delete vía `eliminado_en`) seguía saliendo en
    el selector porque `listar_asesores` nunca filtraba `eliminado_en`, a
    diferencia de `listar_equipo`/`obtener_usuario`/`autenticar`."""
    negocio = await _negocio_con_asesores("g-json-4")
    await mem.eliminar_usuario(f"ase_disp_g-json-4", negocio["id"], eliminado_por="admin_g-json-4")

    dependencia = _dependencia_usuario(dashboard.gestionar_asesores)
    usuario = await dependencia(usuario={
        "username": "admin_g-json-4", "rol": "admin", "negocio_id": negocio["id"],
    })
    respuesta = await dashboard.gestionar_asesores(
        request=_request_con_accept("application/json"), usuario=usuario,
    )
    import json as _json
    datos = _json.loads(respuesta.body.decode())
    usernames = {a["username"] for a in datos["asesores"]}
    assert "ase_disp_g-json-4" not in usernames
    assert "ase_nodisp_g-json-4" in usernames


async def test_asesor_desactivado_ya_no_sale_en_el_selector():
    """Tercer hallazgo (2026-09-17): "gabi asigna a un asesor a pesar que
    este inactivo, solo debe asignar a los activos". `toggle_usuario_activo`
    (Equipo) solo apaga `activo` — nunca toca `disponible` — y una cuenta
    con `activo=False` no puede volver a loguearse para corregirlo ella
    misma, así que sin filtrar por `activo` en `listar_asesores` quedaba
    elegible para siempre, tanto en el selector manual como (más grave) en
    `elegir_asesor_automatico` (asignación de Gabi) — ver
    test_asignacion_automatica.py para ese caso específico."""
    negocio = await _negocio_con_asesores("g-json-5")
    nuevo_estado = await mem.toggle_usuario_activo(f"ase_disp_g-json-5", negocio["id"])
    assert nuevo_estado is False

    dependencia = _dependencia_usuario(dashboard.gestionar_asesores)
    usuario = await dependencia(usuario={
        "username": "admin_g-json-5", "rol": "admin", "negocio_id": negocio["id"],
    })
    respuesta = await dashboard.gestionar_asesores(
        request=_request_con_accept("application/json"), usuario=usuario,
    )
    import json as _json
    datos = _json.loads(respuesta.body.decode())
    usernames = {a["username"] for a in datos["asesores"]}
    assert "ase_disp_g-json-5" not in usernames
    assert "ase_nodisp_g-json-5" in usernames
