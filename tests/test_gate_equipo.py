# tests/test_gate_equipo.py — Gate UX Equipo (Nueva Experiencia):
#
#  Decisión 5 — reset de contraseña, edición de nivel y umbrales de
#  asignación pasan a ser admin-únicamente (antes ROLES_CON_VISION_TOTAL =
#  admin+supervisor, una desviación de MPA §9 "Permisos de alto nivel"
#  corregida en este Gate — Supervisor solo tiene "Solo lectura de
#  carga/disponibilidad", ninguna acción administrativa de cuenta).
#
#  Decisión 6 — la pantalla Equipo debe listar TODAS las cuentas del
#  Negocio (Admin+Supervisor+Asesor), no solo `rol=="asesor"` como
#  `listar_asesores()` (que se conserva sin tocar — sigue siendo
#  asesor-únicamente para los selectores de asignación de leads, que nunca
#  asignan a Admin/Supervisor).
#
# Datos sintéticos únicamente, mismo criterio que test_gate54_listados_scoped.py.

import inspect
import json

import pytest
from fastapi import HTTPException

from agent import dashboard, memory as mem


async def _negocio_con_equipo(codigo: str):
    negocio = await mem.crear_negocio(f"Negocio {codigo}", codigo)
    await mem.crear_usuario(f"admin_{codigo}", "pw12345", "Admin", "admin", negocio["id"])
    await mem.crear_usuario(f"sup_{codigo}", "pw12345", "Supervisor", "supervisor", negocio["id"])
    await mem.crear_usuario(f"ase1_{codigo}", "pw12345", "Asesor Uno", "asesor", negocio["id"], nivel="junior")
    await mem.crear_usuario(f"ase2_{codigo}", "pw12345", "Asesor Dos", "asesor", negocio["id"], nivel="senior")
    return negocio


def _dependencia_usuario(func):
    """Extrae el callable real detrás de `usuario: dict = Depends(...)` de
    una ruta — el test valida EXACTAMENTE lo que FastAPI ejecutaría en
    producción, sin necesidad de un TestClient con sesión/cookies reales
    (ningún test de este repo lo usa — mismo criterio de
    test_gate55_archivo_cross_tenant.py, llamar directo a la función)."""
    parametro = inspect.signature(func).parameters["usuario"]
    return parametro.default.dependency


# ---------------------------------------------------------------------------
# Decisión 5 — admin-únicamente
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("ruta_func", [
    dashboard.resetear_password_asesor,
    dashboard.actualizar_nivel,
    dashboard.actualizar_umbrales_asignacion,
    dashboard.resetear_password_equipo,
    dashboard.crear_equipo_usuario,
])
async def test_supervisor_recibe_403(ruta_func):
    dependencia = _dependencia_usuario(ruta_func)
    with pytest.raises(HTTPException) as exc:
        await dependencia(usuario={"username": "sup1", "rol": "supervisor", "negocio_id": "neg-1"})
    assert exc.value.status_code == 403


@pytest.mark.parametrize("ruta_func", [
    dashboard.resetear_password_asesor,
    dashboard.actualizar_nivel,
    dashboard.actualizar_umbrales_asignacion,
    dashboard.resetear_password_equipo,
    dashboard.crear_equipo_usuario,
])
async def test_asesor_recibe_403(ruta_func):
    dependencia = _dependencia_usuario(ruta_func)
    with pytest.raises(HTTPException) as exc:
        await dependencia(usuario={"username": "ase1", "rol": "asesor", "negocio_id": "neg-1"})
    assert exc.value.status_code == 403


@pytest.mark.parametrize("ruta_func", [
    dashboard.resetear_password_asesor,
    dashboard.actualizar_nivel,
    dashboard.actualizar_umbrales_asignacion,
    dashboard.resetear_password_equipo,
    dashboard.crear_equipo_usuario,
])
async def test_admin_pasa(ruta_func):
    dependencia = _dependencia_usuario(ruta_func)
    usuario = {"username": "admin1", "rol": "admin", "negocio_id": "neg-1"}
    resultado = await dependencia(usuario=usuario)
    assert resultado["rol"] == "admin"


# ---------------------------------------------------------------------------
# Decisión 5 — capacidad "equipo:administrar" (_capacidades_de, para que el
# frontend pinte/oculte el botón de acciones — la autorización real sigue
# siendo requiere_rol, ya cubierto arriba)
# ---------------------------------------------------------------------------

def test_capacidad_equipo_administrar_solo_admin():
    assert "equipo:administrar" in dashboard._capacidades_de("admin")
    assert "equipo:administrar" not in dashboard._capacidades_de("supervisor")
    assert "equipo:administrar" not in dashboard._capacidades_de("asesor")


# ---------------------------------------------------------------------------
# Decisión 6 — listar_equipo() (memory.py)
# ---------------------------------------------------------------------------

async def test_listar_equipo_incluye_los_3_roles():
    negocio = await _negocio_con_equipo("eq-a")
    miembros = await mem.listar_equipo(negocio["id"])
    assert {m["rol"] for m in miembros} == {"admin", "supervisor", "asesor"}
    assert len(miembros) == 4


async def test_listar_equipo_no_ve_cuentas_de_otro_negocio():
    negocio_a = await _negocio_con_equipo("eq-b")
    await _negocio_con_equipo("eq-c")
    miembros_a = await mem.listar_equipo(negocio_a["id"])
    assert all(m["username"].endswith("eq-b") for m in miembros_a)
    assert len(miembros_a) == 4


async def test_listar_equipo_nivel_y_disponible_none_para_no_asesor():
    negocio = await _negocio_con_equipo("eq-d")
    miembros = await mem.listar_equipo(negocio["id"])
    for m in miembros:
        if m["rol"] == "asesor":
            assert m["nivel"] is not None
        else:
            assert m["nivel"] is None
            assert m["disponible"] is None


async def test_listar_asesores_conserva_semantica_solo_asesores():
    """No cambiar innecesariamente: listar_asesores() sigue devolviendo
    SOLO asesores — la sigue usando agent/asignacion.py (auto-asignación,
    nunca puede asignar un lead a Admin/Supervisor) y los selectores de
    reasignación de leads en dashboard.py (bandeja/pipeline/lead detail)."""
    negocio = await _negocio_con_equipo("eq-k")
    asesores = await mem.listar_asesores(negocio["id"])
    assert {a["username"] for a in asesores} == {"ase1_eq-k", "ase2_eq-k"}


# ---------------------------------------------------------------------------
# Decisión 6 — GET /dashboard/equipo (ruta JSON)
# ---------------------------------------------------------------------------

async def test_ruta_json_equipo_admin_ve_todas_las_cuentas():
    negocio = await _negocio_con_equipo("eq-e")
    usuario_admin = {"username": "admin_eq-e", "rol": "admin", "negocio_id": negocio["id"]}
    respuesta = await dashboard.listar_equipo_json(usuario=usuario_admin)
    cuerpo = json.loads(respuesta.body)
    assert len(cuerpo["miembros"]) == 4


async def test_ruta_json_equipo_supervisor_ve_todas_las_cuentas_solo_lectura():
    negocio = await _negocio_con_equipo("eq-l")
    usuario_sup = {"username": "sup_eq-l", "rol": "supervisor", "negocio_id": negocio["id"]}
    respuesta = await dashboard.listar_equipo_json(usuario=usuario_sup)
    cuerpo = json.loads(respuesta.body)
    assert len(cuerpo["miembros"]) == 4


async def test_ruta_json_equipo_asesor_ve_solo_su_propia_fila():
    negocio = await _negocio_con_equipo("eq-f")
    usuario_asesor = {
        "username": "ase1_eq-f", "rol": "asesor", "negocio_id": negocio["id"],
        "nombre": "Asesor Uno", "nivel": "junior", "disponible": True,
    }
    respuesta = await dashboard.listar_equipo_json(usuario=usuario_asesor)
    cuerpo = json.loads(respuesta.body)
    assert len(cuerpo["miembros"]) == 1
    assert cuerpo["miembros"][0]["username"] == "ase1_eq-f"


async def test_ruta_json_equipo_carga_none_para_admin_y_supervisor():
    negocio = await _negocio_con_equipo("eq-m")
    usuario_admin = {"username": "admin_eq-m", "rol": "admin", "negocio_id": negocio["id"]}
    respuesta = await dashboard.listar_equipo_json(usuario=usuario_admin)
    cuerpo = json.loads(respuesta.body)
    for m in cuerpo["miembros"]:
        if m["rol"] == "asesor":
            assert m["carga"] is not None
        else:
            assert m["carga"] is None


# ---------------------------------------------------------------------------
# Decisión 5 + flujo de reset — POST /dashboard/equipo/{username}/resetear
# ---------------------------------------------------------------------------

async def test_resetear_password_equipo_actualiza_el_hash_y_lo_devuelve_una_vez():
    negocio = await _negocio_con_equipo("eq-g")
    antes = await mem.obtener_usuario("ase1_eq-g", negocio_id=negocio["id"])
    usuario_admin = {"username": "admin_eq-g", "rol": "admin", "negocio_id": negocio["id"]}

    respuesta = await dashboard.resetear_password_equipo(
        username="ase1_eq-g", usuario=usuario_admin, _csrf=None,
    )
    cuerpo = json.loads(respuesta.body)
    despues = await mem.obtener_usuario("ase1_eq-g", negocio_id=negocio["id"])

    assert cuerpo["username"] == "ase1_eq-g"
    assert cuerpo["password_temporal"]
    assert despues["password_hash"] != antes["password_hash"]


async def test_resetear_password_equipo_usuario_inexistente_404():
    negocio = await _negocio_con_equipo("eq-h")
    usuario_admin = {"username": "admin_eq-h", "rol": "admin", "negocio_id": negocio["id"]}
    with pytest.raises(HTTPException) as exc:
        await dashboard.resetear_password_equipo(username="no_existe", usuario=usuario_admin, _csrf=None)
    assert exc.value.status_code == 404


async def test_resetear_password_equipo_no_cruza_negocio():
    negocio_a = await _negocio_con_equipo("eq-n")
    await _negocio_con_equipo("eq-o")
    usuario_admin_a = {"username": "admin_eq-n", "rol": "admin", "negocio_id": negocio_a["id"]}
    with pytest.raises(HTTPException) as exc:
        await dashboard.resetear_password_equipo(username="ase1_eq-o", usuario=usuario_admin_a, _csrf=None)
    assert exc.value.status_code == 404


# ---------------------------------------------------------------------------
# Decisión 5 — panel legacy HTML (/dashboard/asesores) oculta acciones que
# ahora fallarían con 403 si el viewer no es admin
# ---------------------------------------------------------------------------

async def test_pagina_legacy_oculta_acciones_para_supervisor():
    negocio = await _negocio_con_equipo("eq-i")
    usuario_sup = {"username": "sup_eq-i", "rol": "supervisor", "negocio_id": negocio["id"], "nombre": "Supervisor"}
    html_out = await dashboard._pagina_gestionar_asesores(usuario_sup)
    assert "Resetear contraseña" not in html_out
    assert 'name="nivel"' not in html_out


async def test_pagina_legacy_muestra_acciones_para_admin():
    negocio = await _negocio_con_equipo("eq-j")
    usuario_admin = {"username": "admin_eq-j", "rol": "admin", "negocio_id": negocio["id"], "nombre": "Admin"}
    html_out = await dashboard._pagina_gestionar_asesores(usuario_admin)
    assert "Resetear contraseña" in html_out
    assert 'name="nivel"' in html_out


# ---------------------------------------------------------------------------
# Alta de cuenta desde la Nueva Experiencia — POST /dashboard/equipo/nuevo
# ---------------------------------------------------------------------------

class _ReqJson:
    def __init__(self, datos):
        self._datos = datos

    async def json(self):
        return self._datos


async def test_crear_equipo_usuario_crea_asesor_y_devuelve_password_una_vez():
    negocio = await _negocio_con_equipo("eq-nuevo")
    admin = {"username": "admin_eq-nuevo", "rol": "admin", "negocio_id": negocio["id"]}
    respuesta = await dashboard.crear_equipo_usuario(
        _ReqJson({"username": "nueva_ase", "nombre": "Nueva Asesora", "rol": "asesor", "nivel": "intermedio"}),
        usuario=admin, _csrf=None,
    )
    cuerpo = json.loads(respuesta.body)
    creado = await mem.obtener_usuario("nueva_ase", negocio_id=negocio["id"])
    assert cuerpo["password_temporal"]
    assert creado["rol"] == "asesor" and creado["nivel"] == "intermedio"


async def test_crear_equipo_usuario_duplicado_409_y_datos_invalidos_400():
    negocio = await _negocio_con_equipo("eq-dup")
    admin = {"username": "admin_eq-dup", "rol": "admin", "negocio_id": negocio["id"]}
    with pytest.raises(HTTPException) as exc:
        await dashboard.crear_equipo_usuario(
            _ReqJson({"username": "ase1_eq-dup", "nombre": "X", "rol": "asesor", "nivel": "junior"}),
            usuario=admin, _csrf=None,
        )
    assert exc.value.status_code == 409
    for malo in (
        {"username": "", "nombre": "X", "rol": "asesor", "nivel": "junior"},
        {"username": "u1", "nombre": "", "rol": "asesor", "nivel": "junior"},
        {"username": "u1", "nombre": "X", "rol": "dios"},
        {"username": "u1", "nombre": "X", "rol": "asesor", "nivel": "mega"},
    ):
        with pytest.raises(HTTPException) as exc:
            await dashboard.crear_equipo_usuario(_ReqJson(malo), usuario=admin, _csrf=None)
        assert exc.value.status_code == 400
