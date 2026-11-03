# tests/test_backend_ux_citas_restaurar_historial.py — 2026-11-03, pendientes de la auditoría de UX de Maiek:
#   1. GET /dashboard/calendario/citas.json (citas por rango, con alcance por rol)
#   2. GET /dashboard/equipo/eliminados y POST /dashboard/equipo/{username}/restaurar
#   3. GET /dashboard/uso-mensajes/historial-cambios.json paginado (`antes_de` + `hay_mas`)
# Datos sintéticos únicamente.

import json
from datetime import datetime, timedelta

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from agent import dashboard, memory as mem


def _json(respuesta) -> dict:
    return json.loads(respuesta.body)


def _usuario(negocio, username, rol):
    return {"negocio_id": negocio["id"], "username": username, "rol": rol}


async def _negocio(codigo: str):
    negocio = await mem.crear_negocio(f"Negocio {codigo}", codigo)
    await mem.crear_usuario(f"admin_{codigo}", "pw12345", "Admin", "admin", negocio["id"])
    await mem.crear_usuario(f"ase1_{codigo}", "pw12345", "Asesor Uno", "asesor", negocio["id"])
    await mem.crear_usuario(f"ase2_{codigo}", "pw12345", "Asesor Dos", "asesor", negocio["id"])
    return negocio


async def _cita(negocio, telefono, asesor, fecha, resultado="agendado", cerrado=None):
    async with mem.async_session() as session:
        session.add(mem.Lead(
            telefono=telefono, negocio_id=negocio["id"], nombre=f"Cliente {telefono}", resultado=resultado,
            fecha_agendada=fecha, asesor_asignado=asesor, cerrado_definitivamente_en=cerrado,
        ))
        await session.commit()


async def _citas(usuario, desde, hasta):
    return _json(await dashboard.calendario_citas_json(desde=desde, hasta=hasta, usuario=usuario))["citas"]


# ── 1. Citas por rango ──────────────────────────────────────────────────────

async def test_citas_por_rango_incluye_extremos_y_deja_fuera_lo_demas():
    n = await _negocio("citas-1")
    await _cita(n, "51900000001", "ase1_citas-1", datetime(2026, 11, 3, 9, 0))     # primer día: entra
    await _cita(n, "51900000002", "ase1_citas-1", datetime(2026, 11, 5, 23, 59))   # último día: entra
    await _cita(n, "51900000003", "ase1_citas-1", datetime(2026, 11, 6, 0, 0))     # un día después: no
    await _cita(n, "51900000004", "ase1_citas-1", datetime(2026, 11, 2, 23, 59))   # un día antes: no

    citas = await _citas(_usuario(n, "admin_citas-1", "admin"), "2026-11-03", "2026-11-05")

    assert [c["telefono"] for c in citas] == ["51900000001", "51900000002"]
    assert citas[0]["cita_en"] == "2026-11-03T14:00:00Z"  # Lima UTC-5 → UTC
    assert citas[0]["asesor"] == "ase1_citas-1"           # la vista admin trae el asesor


async def test_citas_el_asesor_ve_solo_las_suyas_y_sin_campo_asesor():
    n = await _negocio("citas-2")
    await _cita(n, "51900000011", "ase1_citas-2", datetime(2026, 11, 3, 10, 0))
    await _cita(n, "51900000012", "ase2_citas-2", datetime(2026, 11, 3, 11, 0))

    citas = await _citas(_usuario(n, "ase1_citas-2", "asesor"), "2026-11-03", "2026-11-03")

    assert [c["telefono"] for c in citas] == ["51900000011"]
    assert "asesor" not in citas[0]


async def test_citas_excluye_cerradas_y_no_agendadas():
    n = await _negocio("citas-3")
    await _cita(n, "51900000021", "ase1_citas-3", datetime(2026, 11, 3, 10, 0), cerrado=datetime(2026, 11, 3, 8, 0))
    await _cita(n, "51900000022", "ase1_citas-3", datetime(2026, 11, 3, 11, 0), resultado="vendido")
    await _cita(n, "51900000023", "ase1_citas-3", datetime(2026, 11, 3, 12, 0))

    citas = await _citas(_usuario(n, "admin_citas-3", "admin"), "2026-11-03", "2026-11-03")

    assert [c["telefono"] for c in citas] == ["51900000023"]


async def test_citas_no_mezcla_negocios():
    a = await _negocio("citas-4a")
    b = await _negocio("citas-4b")
    await _cita(b, "51900000031", "ase1_citas-4b", datetime(2026, 11, 3, 10, 0))

    assert await _citas(_usuario(a, "admin_citas-4a", "admin"), "2026-11-03", "2026-11-03") == []


@pytest.mark.parametrize("desde,hasta", [
    ("03/11/2026", "2026-11-05"),   # formato inválido
    ("2026-11-05", "2026-11-03"),   # al revés
    ("2026-01-01", "2026-12-31"),   # demasiado largo
])
async def test_citas_rechaza_rangos_invalidos(desde, hasta):
    n = await _negocio("citas-5")
    with pytest.raises(HTTPException) as e:
        await dashboard.calendario_citas_json(desde=desde, hasta=hasta, usuario=_usuario(n, "admin_citas-5", "admin"))
    assert e.value.status_code == 400


# ── 2. Restaurar usuarios eliminados ────────────────────────────────────────

async def test_restaurar_usuario_lo_deja_inactivo_y_no_disponible():
    n = await _negocio("rest-1")
    admin = _usuario(n, "admin_rest-1", "admin")
    await mem.eliminar_usuario("ase1_rest-1", n["id"], eliminado_por="admin_rest-1")
    assert "ase1_rest-1" not in {m["username"] for m in await mem.listar_equipo(n["id"])}

    eliminados = _json(await dashboard.listar_equipo_eliminados(usuario=admin))["eliminados"]
    assert [u["username"] for u in eliminados] == ["ase1_rest-1"]
    assert "password_hash" not in eliminados[0]

    r = _json(await dashboard.restaurar_equipo_usuario(username="ase1_rest-1", usuario=admin, _csrf=None))
    assert r == {"ok": True, "activo": False}

    miembro = next(m for m in await mem.listar_equipo(n["id"]) if m["username"] == "ase1_rest-1")
    assert miembro["activo"] is False and miembro["disponible"] is False
    # Inactivo ⇒ no entra en el reparto automático de leads.
    assert "ase1_rest-1" not in {a["username"] for a in await mem.listar_asesores(n["id"])}
    assert _json(await dashboard.listar_equipo_eliminados(usuario=admin))["eliminados"] == []


async def test_restaurar_errores_404_y_409():
    n = await _negocio("rest-2")
    admin = _usuario(n, "admin_rest-2", "admin")
    with pytest.raises(HTTPException) as e404:
        await dashboard.restaurar_equipo_usuario(username="no_existe", usuario=admin, _csrf=None)
    assert e404.value.status_code == 404
    with pytest.raises(HTTPException) as e409:
        await dashboard.restaurar_equipo_usuario(username="ase1_rest-2", usuario=admin, _csrf=None)
    assert e409.value.status_code == 409


async def test_restaurar_no_toca_cuentas_de_otro_negocio():
    a = await _negocio("rest-3a")
    b = await _negocio("rest-3b")
    await mem.eliminar_usuario("ase1_rest-3b", b["id"], eliminado_por="admin_rest-3b")
    with pytest.raises(HTTPException) as e:
        await dashboard.restaurar_equipo_usuario(
            username="ase1_rest-3b", usuario=_usuario(a, "admin_rest-3a", "admin"), _csrf=None,
        )
    assert e.value.status_code == 404
    assert [u["username"] for u in await mem.listar_usuarios_eliminados(b["id"])] == ["ase1_rest-3b"]


def test_restaurar_y_eliminados_son_solo_admin_y_con_csrf():
    def ruta(path, metodo):
        return next(r for r in dashboard.router.routes if getattr(r, "path", None) == path and metodo in r.methods)

    for r in (ruta("/dashboard/equipo/eliminados", "GET"), ruta("/dashboard/equipo/{username}/restaurar", "POST")):
        textos = [repr(d.call) + repr(getattr(d.call, "__closure__", None)) for d in r.dependant.dependencies]
        assert any("admin" in t or "requiere_rol" in t for t in textos)
    nombres = [d.call.__name__ for d in ruta("/dashboard/equipo/{username}/restaurar", "POST").dependant.dependencies]
    assert "verificar_csrf" in nombres


# ── 3. Historial de configuración paginado ──────────────────────────────────

async def _auditar(negocio, cuantos):
    base = datetime(2026, 10, 1, 12, 0, 0)
    async with mem.async_session() as session:
        for i in range(cuantos):
            session.add(mem.RegistroAuditoria(
                negocio_id=negocio["id"], entidad_tipo="configuracion", entidad_id="x", accion=f"cambio_{i:03d}",
                actor="admin", creado=base + timedelta(minutes=i), payload={"cambios": {"k": {"antes": "a", "despues": "b"}}},
            ))
        await session.commit()


async def _pagina(admin, **kw):
    return _json(await dashboard.uso_mensajes_historial_cambios_json(usuario=admin, **kw))


async def test_historial_pagina_hacia_atras_sin_repetir_ni_perder():
    n = await _negocio("hist-1")
    admin = _usuario(n, "admin_hist-1", "admin")
    await _auditar(n, 120)

    primera = await _pagina(admin, limite=50, antes_de=None)
    assert len(primera["cambios"]) == 50 and primera["hay_mas"] is True
    assert primera["cambios"][0]["accion"] == "cambio_119"  # más reciente primero

    segunda = await _pagina(admin, limite=50, antes_de=primera["cambios"][-1]["creado"])
    tercera = await _pagina(admin, limite=50, antes_de=segunda["cambios"][-1]["creado"])
    assert len(segunda["cambios"]) == 50 and segunda["hay_mas"] is True
    assert len(tercera["cambios"]) == 20 and tercera["hay_mas"] is False

    acciones = [c["accion"] for p in (primera, segunda, tercera) for c in p["cambios"]]
    assert len(acciones) == len(set(acciones)) == 120


async def test_historial_corto_dice_que_no_hay_mas_y_antes_de_invalido_da_400():
    n = await _negocio("hist-2")
    admin = _usuario(n, "admin_hist-2", "admin")
    await _auditar(n, 3)
    assert (await _pagina(admin, limite=50, antes_de=None))["hay_mas"] is False
    with pytest.raises(HTTPException) as e:
        await _pagina(admin, limite=50, antes_de="ayer")
    assert e.value.status_code == 400
