# tests/test_gate_campanas_p0.py — Gate Campañas P0 (Nueva Experiencia).
#
# Cubre los 4 endpoints JSON nuevos (`GET /campanas.json`, `POST
# /campanas/nueva.json`, `POST /campanas/{id}/editar.json`, `POST
# /campanas/{id}/toggle.json`) y el fortalecimiento de SCR-03
# (`campana_origen` en `_dto_lead_detalle`).
#
# Mismo criterio que el resto de la suite: se llama a la función de la ruta
# directamente en vez de un TestClient HTTP (ningún test de este repo usa
# uno). Para permisos (rol admin-únicamente) se extrae la dependencia real
# de FastAPI y se invoca directo — mismo técnica que ya usa
# test_gate_equipo.py (`_dependencia_usuario`) — y para CSRF se invoca
# `verificar_csrf` directamente con un stand-in mínimo de `Request`, la
# única forma de probar ese candado sin pasar por ASGI: llamar la ruta con
# `_csrf=None` (como el resto de la suite) SALTA la dependencia por
# completo y no demostraría nada sobre ella.

import inspect
import json

import pytest
from fastapi import HTTPException

from agent import dashboard, memory as mem


class _RequestFalso:
    def __init__(self, payload: dict):
        self._payload = payload

    async def json(self):
        return self._payload


class _RequestConCsrf:
    """Duck-type mínimo de `Request` — `verificar_csrf` solo lee
    `.session` y `.headers`, nunca el resto de la superficie de Request."""

    def __init__(self, session: dict, headers: dict):
        self.session = session
        self.headers = headers


def _dependencia_usuario(func):
    """Extrae el callable real detrás de `usuario: dict = Depends(...)` de
    una ruta — el test valida EXACTAMENTE lo que FastAPI ejecutaría en
    producción, sin necesitar un TestClient (mismo criterio de
    test_gate_equipo.py)."""
    parametro = inspect.signature(func).parameters["usuario"]
    return parametro.default.dependency


async def _negocio_con_campana(codigo: str):
    negocio = await mem.crear_negocio(f"Negocio {codigo}", codigo)
    campana = await mem.crear_campana(
        nombre=f"Campaña {codigo}", tipo_deteccion="texto_saludo", patron="hola",
        texto_saludo="Hola, vi su promoción", negocio_id=negocio["id"],
    )
    return negocio, campana


def _cuerpo(respuesta) -> dict:
    return json.loads(respuesta.body)


# ---------------------------------------------------------------------------
# Permisos — GET admin+supervisor, escritura admin-únicamente
# ---------------------------------------------------------------------------

async def test_listado_json_acepta_admin_y_supervisor():
    verificar = _dependencia_usuario(dashboard.campanas_json)
    admin = await verificar(usuario={"rol": "admin"})
    supervisor = await verificar(usuario={"rol": "supervisor"})
    assert admin["rol"] == "admin"
    assert supervisor["rol"] == "supervisor"


async def test_listado_json_rechaza_asesor():
    verificar = _dependencia_usuario(dashboard.campanas_json)
    try:
        await verificar(usuario={"rol": "asesor"})
        assert False, "debía lanzar HTTPException"
    except HTTPException as e:
        assert e.status_code == 403


@pytest.mark.parametrize(
    "ruta",
    [
        dashboard.crear_campana_nueva_json,
        dashboard.editar_promo_campana_json,
        dashboard.toggle_campana_json,
    ],
)
async def test_rutas_de_escritura_rechazan_supervisor_y_asesor(ruta):
    verificar = _dependencia_usuario(ruta)
    for rol in ("supervisor", "asesor"):
        try:
            await verificar(usuario={"rol": rol})
            assert False, f"debía lanzar HTTPException para rol={rol}"
        except HTTPException as e:
            assert e.status_code == 403


@pytest.mark.parametrize(
    "ruta",
    [
        dashboard.crear_campana_nueva_json,
        dashboard.editar_promo_campana_json,
        dashboard.toggle_campana_json,
    ],
)
async def test_rutas_de_escritura_aceptan_admin(ruta):
    verificar = _dependencia_usuario(ruta)
    admin = await verificar(usuario={"rol": "admin"})
    assert admin["rol"] == "admin"


# ---------------------------------------------------------------------------
# CSRF — la única forma de probar el candado real es invocar la dependencia
# directamente, no llamar la ruta con `_csrf=None` (eso la saltea).
# ---------------------------------------------------------------------------

async def test_verificar_csrf_rechaza_sin_token():
    request = _RequestConCsrf(session={"csrf_token": "abc123"}, headers={})
    try:
        await dashboard.verificar_csrf(request)
        assert False, "debía lanzar HTTPException"
    except HTTPException as e:
        assert e.status_code == 403


async def test_verificar_csrf_rechaza_token_no_coincide():
    request = _RequestConCsrf(
        session={"csrf_token": "abc123"}, headers={"x-csrf-token": "otro-token"},
    )
    try:
        await dashboard.verificar_csrf(request)
        assert False, "debía lanzar HTTPException"
    except HTTPException as e:
        assert e.status_code == 403


async def test_verificar_csrf_acepta_token_coincidente():
    request = _RequestConCsrf(
        session={"csrf_token": "abc123"}, headers={"x-csrf-token": "abc123"},
    )
    await dashboard.verificar_csrf(request)  # no lanza


# ---------------------------------------------------------------------------
# Listado — forma de respuesta, conteo, puede_gestionar
# ---------------------------------------------------------------------------

async def test_listado_json_forma_y_puede_gestionar():
    negocio, campana = await _negocio_con_campana("p0-list")
    respuesta = await dashboard.campanas_json(usuario={"negocio_id": negocio["id"], "rol": "admin"})
    cuerpo = _cuerpo(respuesta)
    assert cuerpo["puede_gestionar"] is True
    assert len(cuerpo["campanas"]) == 1
    fila = cuerpo["campanas"][0]
    assert fila["id"] == campana["id"]
    assert fila["nombre"] == campana["nombre"]
    assert fila["conteo"] == {"total": 0, "vendidos": 0}
    # Nunca expone negocio_id/unidad_id — internos, ya implícitos en sesión.
    assert "negocio_id" not in fila
    assert "unidad_id" not in fila


async def test_listado_json_supervisor_puede_gestionar_false():
    negocio, _ = await _negocio_con_campana("p0-sup")
    respuesta = await dashboard.campanas_json(usuario={"negocio_id": negocio["id"], "rol": "supervisor"})
    cuerpo = _cuerpo(respuesta)
    assert cuerpo["puede_gestionar"] is False


# ---------------------------------------------------------------------------
# Multi-tenant — Tenant A nunca ve/edita/toggle campañas de Tenant B
# ---------------------------------------------------------------------------

async def test_listado_json_no_mezcla_negocios():
    negocio_a, campana_a = await _negocio_con_campana("p0-mtA")
    negocio_b, campana_b = await _negocio_con_campana("p0-mtB")

    respuesta_a = await dashboard.campanas_json(usuario={"negocio_id": negocio_a["id"], "rol": "admin"})
    ids_a = {c["id"] for c in _cuerpo(respuesta_a)["campanas"]}
    assert ids_a == {campana_a["id"]}


async def test_editar_json_campana_de_otro_negocio_da_404():
    negocio_a, _ = await _negocio_con_campana("p0-edA")
    _, campana_b = await _negocio_con_campana("p0-edB")
    usuario_a = {"negocio_id": negocio_a["id"], "rol": "admin"}

    request = _RequestFalso({"producto_promocional": "Secuestrado", "precio_promocional": "S/ 1"})
    try:
        await dashboard.editar_promo_campana_json(campana_b["id"], request, usuario=usuario_a, _csrf=None)
        assert False, "debía lanzar HTTPException"
    except HTTPException as e:
        assert e.status_code == 404

    intacta = await mem.obtener_campana(campana_b["id"])
    assert intacta["producto_promocional"] is None


async def test_toggle_json_campana_de_otro_negocio_da_404():
    negocio_a, _ = await _negocio_con_campana("p0-tgA")
    _, campana_b = await _negocio_con_campana("p0-tgB")
    usuario_a = {"negocio_id": negocio_a["id"], "rol": "admin"}

    try:
        await dashboard.toggle_campana_json(campana_b["id"], usuario=usuario_a, _csrf=None)
        assert False, "debía lanzar HTTPException"
    except HTTPException as e:
        assert e.status_code == 404

    intacta = await mem.obtener_campana(campana_b["id"])
    assert intacta["activa"] is True  # nunca se tocó


# ---------------------------------------------------------------------------
# Crear — validación, alcance de edición, respuesta real
# ---------------------------------------------------------------------------

async def test_crear_json_campana_completa():
    negocio, _ = await _negocio_con_campana("p0-crear")
    usuario = {"negocio_id": negocio["id"], "rol": "admin"}
    request = _RequestFalso({
        "nombre": "Meta Terma Marzo", "tipo_deteccion": "texto_saludo",
        "patron": "terma marzo", "texto_saludo": "Vi la promo de terma marzo",
        "producto_promocional": "Terma Rheem 8L", "precio_promocional": "S/ 419.90",
    })
    respuesta = await dashboard.crear_campana_nueva_json(request, usuario=usuario, _csrf=None)
    cuerpo = _cuerpo(respuesta)
    assert cuerpo["ok"] is True
    assert cuerpo["campana"]["nombre"] == "Meta Terma Marzo"
    assert cuerpo["campana"]["patron"] == "terma marzo"  # se guarda en minúsculas, igual que Legacy
    assert cuerpo["campana"]["conteo"] == {"total": 0, "vendidos": 0}

    en_bd = await mem.obtener_campana(cuerpo["campana"]["id"])
    assert en_bd["negocio_id"] == negocio["id"]


async def test_crear_json_rechaza_nombre_vacio():
    negocio, _ = await _negocio_con_campana("p0-crvacio")
    usuario = {"negocio_id": negocio["id"], "rol": "admin"}
    request = _RequestFalso({"nombre": "  ", "tipo_deteccion": "texto_saludo", "patron": "x"})
    try:
        await dashboard.crear_campana_nueva_json(request, usuario=usuario, _csrf=None)
        assert False, "debía lanzar HTTPException"
    except HTTPException as e:
        assert e.status_code == 400


async def test_crear_json_rechaza_tipo_deteccion_invalido():
    negocio, _ = await _negocio_con_campana("p0-crtipo")
    usuario = {"negocio_id": negocio["id"], "rol": "admin"}
    request = _RequestFalso({"nombre": "X", "tipo_deteccion": "inventado", "patron": "x"})
    try:
        await dashboard.crear_campana_nueva_json(request, usuario=usuario, _csrf=None)
        assert False, "debía lanzar HTTPException"
    except HTTPException as e:
        assert e.status_code == 400


async def test_crear_json_rechaza_patron_desalineado_del_saludo():
    negocio, _ = await _negocio_con_campana("p0-crpatron")
    usuario = {"negocio_id": negocio["id"], "rol": "admin"}
    request = _RequestFalso({
        "nombre": "X", "tipo_deteccion": "texto_saludo",
        "patron": "no aparece", "texto_saludo": "Hola quiero información",
    })
    try:
        await dashboard.crear_campana_nueva_json(request, usuario=usuario, _csrf=None)
        assert False, "debía lanzar HTTPException"
    except HTTPException as e:
        assert e.status_code == 400


# ---------------------------------------------------------------------------
# Editar — SOLO producto/precio/código de material, mismo alcance que Legacy
# ---------------------------------------------------------------------------

async def test_editar_json_actualiza_solo_promo_no_nombre_ni_patron():
    negocio, campana = await _negocio_con_campana("p0-edprom")
    usuario = {"negocio_id": negocio["id"], "rol": "admin"}
    request = _RequestFalso({"producto_promocional": "Cocina 4 hornillas", "precio_promocional": "S/ 899"})
    respuesta = await dashboard.editar_promo_campana_json(campana["id"], request, usuario=usuario, _csrf=None)
    cuerpo = _cuerpo(respuesta)
    assert cuerpo["campana"]["producto_promocional"] == "Cocina 4 hornillas"
    assert cuerpo["campana"]["precio_promocional"] == "S/ 899"
    # Nombre y patrón quedan exactamente como se crearon — esta ruta no los recibe.
    assert cuerpo["campana"]["nombre"] == campana["nombre"]
    assert cuerpo["campana"]["patron"] == campana["patron"]


async def test_editar_json_rechaza_codigo_material_inexistente():
    negocio, campana = await _negocio_con_campana("p0-edcod")
    usuario = {"negocio_id": negocio["id"], "rol": "admin"}
    request = _RequestFalso({"codigo_material": "CODIGO-QUE-NO-EXISTE"})
    try:
        await dashboard.editar_promo_campana_json(campana["id"], request, usuario=usuario, _csrf=None)
        assert False, "debía lanzar HTTPException"
    except HTTPException as e:
        assert e.status_code == 400


# ---------------------------------------------------------------------------
# Toggle — activa/inactiva, reflejado en la respuesta
# ---------------------------------------------------------------------------

async def test_toggle_json_invierte_estado():
    negocio, campana = await _negocio_con_campana("p0-toggle")
    usuario = {"negocio_id": negocio["id"], "rol": "admin"}
    assert campana["activa"] is True

    respuesta = await dashboard.toggle_campana_json(campana["id"], usuario=usuario, _csrf=None)
    assert _cuerpo(respuesta)["campana"]["activa"] is False

    respuesta_2 = await dashboard.toggle_campana_json(campana["id"], usuario=usuario, _csrf=None)
    assert _cuerpo(respuesta_2)["campana"]["activa"] is True


# ---------------------------------------------------------------------------
# SCR-03 — campana_origen en el DTO de Lead Detail (Recorrido #5)
# ---------------------------------------------------------------------------

async def test_dto_lead_detalle_incluye_campana_origen_cuando_existe():
    negocio = await mem.crear_negocio("Negocio SCR03 A", "p0-scrA")
    telefono = "51900700001"
    await mem.actualizar_lead(telefono, negocio_id=negocio["id"], nombre="Cliente con campaña")
    await mem.actualizar_lead(telefono, campana_origen="Meta Terma Marzo")
    lead = await mem.obtener_lead(telefono, negocio_id=negocio["id"])
    dto = dashboard._dto_lead_detalle(lead, [], [])
    assert dto["campana_origen"] == "Meta Terma Marzo"


async def test_dto_lead_detalle_campana_origen_none_sin_atribucion():
    negocio = await mem.crear_negocio("Negocio SCR03 B", "p0-scrB")
    telefono = "51900700002"
    await mem.actualizar_lead(telefono, negocio_id=negocio["id"], nombre="Cliente sin campaña")
    lead = await mem.obtener_lead(telefono, negocio_id=negocio["id"])
    dto = dashboard._dto_lead_detalle(lead, [], [])
    assert dto["campana_origen"] is None
