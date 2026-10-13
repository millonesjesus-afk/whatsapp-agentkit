# tests/test_calendario_negocio_endpoints.py — Calendario de negocio, Fase 1 (2026-10-12): GET/POST/DELETE
# /dashboard/configuracion/dias-especiales.json (permisos, CSRF, contrato, errores, auditoría, aislamiento por negocio) y
# que el contrato de configuración/horario existente no cambie. El contrato completo está en
# docs/contrato_calendario_negocio.md. Datos sintéticos únicamente.

import json
import os
from datetime import date, timedelta
from pathlib import Path

os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")
os.environ.setdefault("WHATSAPP_PROVIDER", "meta")

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from agent import dashboard
from agent import memory as mem

RAIZ = Path(__file__).resolve().parent.parent


@pytest.fixture(autouse=True)
def _cache_limpia():
    mem.invalidar_cache_calendario()
    yield
    mem.invalidar_cache_calendario()


class _Peticion:
    def __init__(self, cuerpo):
        self._cuerpo = cuerpo

    async def json(self):
        if isinstance(self._cuerpo, Exception):
            raise self._cuerpo
        return self._cuerpo


def _json(respuesta) -> dict:
    return json.loads(respuesta.body)


def _ruta(metodo: str):
    return next(
        r for r in dashboard.router.routes
        if getattr(r, "path", None) == "/dashboard/configuracion/dias-especiales.json" and metodo in r.methods
    )


def _dependencias(ruta):
    return [d.call for d in ruta.dependant.dependencies]


def _usuario(negocio, username="admin1", rol="admin"):
    return {"negocio_id": negocio["id"], "username": username, "rol": rol}


async def _negocio(codigo: str):
    return await mem.crear_negocio(f"Negocio {codigo}", codigo)


def _hoy():
    return mem.hoy_en_lima()


async def _post(negocio, cuerpo, usuario=None):
    return _json(await dashboard.dias_especiales_guardar_json(_Peticion(cuerpo), usuario=usuario or _usuario(negocio), _csrf=None))


async def _get(negocio, usuario=None, **params):
    return _json(await dashboard.dias_especiales_json(usuario=usuario or _usuario(negocio), **params))


async def _error(coro) -> HTTPException:
    with pytest.raises(HTTPException) as e:
        await coro
    return e.value


# ── Permisos y CSRF ─────────────────────────────────────────────────────────

@pytest.mark.parametrize("metodo", ["POST", "DELETE"])
def test_toda_escritura_exige_csrf(metodo):
    assert dashboard.verificar_csrf in _dependencias(_ruta(metodo))


def test_el_get_no_pide_csrf_pero_si_sesion_con_rol():
    deps = _dependencias(_ruta("GET"))
    assert dashboard.verificar_csrf not in deps and any(getattr(c, "__name__", "") == "_verificar" for c in deps)


@pytest.mark.parametrize("metodo", ["GET", "POST", "DELETE"])
async def test_solo_admin_y_supervisor(metodo):
    verificador = next(c for c in _dependencias(_ruta(metodo)) if getattr(c, "__name__", "") == "_verificar")
    for rol in ("admin", "supervisor"):
        assert (await verificador(usuario={"rol": rol, "username": "x", "negocio_id": "n"}))["rol"] == rol
    with pytest.raises(HTTPException) as e:
        await verificador(usuario={"rol": "asesor", "username": "x", "negocio_id": "n"})
    assert e.value.status_code == 403


# ── GET ─────────────────────────────────────────────────────────────────────

async def test_get_vacio_trae_el_contrato_completo():
    n = await _negocio("ep-g1")
    cuerpo = await _get(n)
    assert set(cuerpo) == {"hoy", "desde", "hasta", "dias", "estado_actual", "cobertura", "anios_precargables", "tipos", "dias_edicion_retroactiva"}
    assert cuerpo["hoy"] == _hoy().isoformat() and cuerpo["dias"] == [] and cuerpo["dias_edicion_retroactiva"] == 7
    assert cuerpo["desde"] == (_hoy() - timedelta(days=7)).isoformat() and cuerpo["hasta"] == (_hoy() + timedelta(days=365)).isoformat()
    assert set(cuerpo["estado_actual"]) == {"abierto", "motivo", "nombre", "proxima_apertura", "proxima_apertura_texto"}
    assert isinstance(cuerpo["estado_actual"]["abierto"], bool)
    assert cuerpo["cobertura"] == {
        "ultima_fecha_cargada": None, "dias_restantes": None, "aviso": True, "mensaje": cuerpo["cobertura"]["mensaje"],
    } and "No hay feriados" in cuerpo["cobertura"]["mensaje"]
    assert [a["anio"] for a in cuerpo["anios_precargables"]] == [2026, 2027]
    a26, a27 = cuerpo["anios_precargables"]
    assert a26 == {"anio": 2026, "verificado": True, "nota": None, "total": 16, "cargados": 0}
    assert a27["verificado"] is False and "no verificado" in a27["nota"] and a27["total"] == 16
    assert [t["valor"] for t in cuerpo["tipos"]] == ["feriado", "no_laborable", "puente", "atencion_especial", "cierre_propio"]
    assert {t["valor"]: t["atiende_por_defecto"] for t in cuerpo["tipos"]} == {
        "feriado": False, "no_laborable": True, "puente": True, "atencion_especial": True, "cierre_propio": False,
    }
    assert all(t["etiqueta"] for t in cuerpo["tipos"])


async def test_get_lista_los_dias_con_su_contrato_y_filtra_por_rango():
    n = await _negocio("ep-g2")
    await _post(n, {"fecha": "2026-12-08", "tipo": "feriado", "nombre": "Inmaculada Concepción"})
    await _post(n, {"fecha": "2027-02-01", "tipo": "cierre_propio", "nombre": "Inventario"})
    todos = await _get(n, desde="2026-12-01", hasta="2027-03-01")
    assert [d["fecha"] for d in todos["dias"]] == ["2026-12-08", "2027-02-01"]
    d = todos["dias"][0]
    assert set(d) == {
        "id", "fecha", "dia_semana", "tipo", "nombre", "atiende", "hora_apertura", "hora_cierre", "origen", "fuente_url", "verificado",
        "pasado", "requiere_motivo", "editable", "creado", "creado_por", "actualizado",
    }
    assert d["dia_semana"] == "martes" and d["tipo"] == "feriado" and d["atiende"] is False and d["origen"] == "manual"
    assert d["creado_por"] == "admin1" and d["creado"].endswith("Z") and d["verificado"] is None
    assert d["pasado"] is False and d["requiere_motivo"] is False and d["editable"] is True
    solo_diciembre = await _get(n, desde="2026-12-01", hasta="2026-12-31")
    assert [d["fecha"] for d in solo_diciembre["dias"]] == ["2026-12-08"]


async def test_get_marca_si_un_feriado_precargado_esta_verificado():
    n = await _negocio("ep-g3")
    await _post(n, {"operacion": "cargar_feriados_peru", "anio": 2026})
    await _post(n, {"operacion": "cargar_feriados_peru", "anio": 2027})
    cuerpo = await _get(n, desde="2026-12-24", hasta="2027-01-02")
    por_fecha = {d["fecha"]: d for d in cuerpo["dias"]}
    assert por_fecha["2026-12-25"]["verificado"] is True and por_fecha["2026-12-25"]["origen"] == "precargado_pe"
    assert por_fecha["2026-12-25"]["fuente_url"].startswith("https://www.elperuano.pe")
    assert por_fecha["2027-01-01"]["verificado"] is False
    assert [a["cargados"] for a in cuerpo["anios_precargables"]] == [16, 16]


async def test_get_el_aviso_de_cobertura_desaparece_con_el_calendario_cargado():
    n = await _negocio("ep-g4")
    assert (await _get(n))["cobertura"]["aviso"] is True
    await _post(n, {"operacion": "cargar_feriados_peru", "anio": 2027})            # llega hasta el 25-dic-2027
    cobertura = (await _get(n))["cobertura"]
    assert cobertura["ultima_fecha_cargada"] == "2027-12-25" and cobertura["aviso"] is False and cobertura["mensaje"] is None
    assert cobertura["dias_restantes"] == (date(2027, 12, 25) - _hoy()).days


async def test_get_estado_actual_refleja_un_cierre_de_hoy():
    n = await _negocio("ep-g5")
    for dia in range(7):
        await mem.guardar_horario_atencion(n["id"], dia, True, "00:00", "23:59")
    assert (await _get(n))["estado_actual"]["abierto"] is True
    await _post(n, {"fecha": _hoy().isoformat(), "tipo": "feriado", "nombre": "Feriado de hoy"})
    estado = (await _get(n))["estado_actual"]
    assert estado["abierto"] is False and estado["motivo"] == "feriado" and estado["nombre"] == "Feriado de hoy"
    assert estado["proxima_apertura"].endswith("Z") and "mañana" in estado["proxima_apertura_texto"]


@pytest.mark.parametrize("params,mensaje", [
    ({"desde": "ayer"}, "AAAA-MM-DD"), ({"hasta": "2026-13-01"}, "AAAA-MM-DD"),
    ({"desde": "2026-12-01", "hasta": "2026-11-01"}, "anterior"), ({"desde": "2020-01-01", "hasta": "2026-01-01"}, "800"),
])
async def test_get_rechaza_rangos_invalidos(params, mensaje):
    n = await _negocio("ep-g6")
    e = await _error(dashboard.dias_especiales_json(usuario=_usuario(n), **params))
    assert e.status_code == 400 and mensaje in e.detail


# ── POST: guardar ───────────────────────────────────────────────────────────

async def test_post_crea_modifica_y_no_cambia_nada_si_es_igual():
    n = await _negocio("ep-p1")
    cuerpo = {"fecha": "2026-11-20", "tipo": "no_laborable", "nombre": "Día no laborable", "atiende": False}
    r = await _post(n, cuerpo)
    assert r["ok"] is True and r["operacion"] == "guardar" and r["resultado"] == "creado"
    assert r["dia"]["fecha"] == "2026-11-20" and r["dia"]["atiende"] is False and r["dia"]["hora_apertura"] is None
    r = await _post(n, {**cuerpo, "atiende": True, "hora_apertura": "10:00", "hora_cierre": "14:00"})
    assert r["resultado"] == "modificado" and r["dia"]["atiende"] is True and r["dia"]["hora_cierre"] == "14:00"
    assert (await _post(n, {**cuerpo, "atiende": True, "hora_apertura": "10:00", "hora_cierre": "14:00"}))["resultado"] == "sin_cambios"
    assert len((await _get(n, desde="2026-11-01", hasta="2026-11-30"))["dias"]) == 1


async def test_post_sin_atiende_usa_el_valor_por_defecto_del_tipo():
    n = await _negocio("ep-p2")
    assert (await _post(n, {"fecha": "2026-11-20", "tipo": "feriado", "nombre": "F"}))["dia"]["atiende"] is False
    assert (await _post(n, {"fecha": "2026-11-21", "tipo": "no_laborable", "nombre": "NL"}))["dia"]["atiende"] is True
    assert (await _post(n, {"fecha": "2026-11-22", "tipo": "puente", "nombre": "P"}))["dia"]["atiende"] is True


async def test_post_el_negocio_sale_de_la_sesion_nunca_del_cuerpo():
    a, b = await _negocio("ep-p3"), await _negocio("ep-p4")
    await _post(a, {"fecha": "2026-11-20", "tipo": "feriado", "nombre": "X", "negocio_id": b["id"]})
    assert [d["fecha"] for d in await mem.listar_dias_especiales(a["id"])] == [date(2026, 11, 20)]
    assert await mem.listar_dias_especiales(b["id"]) == []


@pytest.mark.parametrize("cuerpo,mensaje", [
    ({"tipo": "feriado", "nombre": "X"}, "fecha"),
    ({"fecha": "mañana", "tipo": "feriado", "nombre": "X"}, "AAAA-MM-DD"),
    ({"fecha": "2026-11-20", "tipo": "vacaciones", "nombre": "X"}, "tipo"),
    ({"fecha": "2026-11-20", "tipo": "feriado", "nombre": ""}, "nombre"),
    ({"fecha": "2026-11-20", "tipo": "feriado", "nombre": "X", "atiende": "no"}, "true o false"),
    ({"fecha": "2026-11-20", "tipo": "atencion_especial", "nombre": "X"}, "hora de apertura"),
    ({"fecha": "2026-11-20", "tipo": "feriado", "nombre": "X", "atiende": True, "hora_apertura": "9", "hora_cierre": "13:00"}, "HH:MM"),
    ({"operacion": "borrar_todo"}, "operacion"),
    ({"operacion": "cargar_feriados_peru"}, "anio"),
    ({"operacion": "cargar_feriados_peru", "anio": "2026"}, "anio"),
    ({"operacion": "cargar_feriados_peru", "anio": 2040}, "No hay feriados precargados"),
    ({"operacion": "marcar_manana_no_laborable", "nombre": 7}, "nombre"),
])
async def test_post_devuelve_400_con_el_motivo_en_espanol(cuerpo, mensaje):
    n = await _negocio("ep-p5")
    e = await _error(dashboard.dias_especiales_guardar_json(_Peticion(cuerpo), usuario=_usuario(n), _csrf=None))
    assert e.status_code == 400 and mensaje in e.detail
    assert await mem.listar_dias_especiales(n["id"]) == []             # todo o nada


@pytest.mark.parametrize("cuerpo", [ValueError("no es json"), ["una", "lista"], "texto"])
async def test_post_exige_un_cuerpo_json_objeto(cuerpo):
    n = await _negocio("ep-p6")
    e = await _error(dashboard.dias_especiales_guardar_json(_Peticion(cuerpo), usuario=_usuario(n), _csrf=None))
    assert e.status_code == 400 and "JSON" in e.detail


async def test_post_edicion_retroactiva_hasta_7_dias_y_con_motivo():
    n = await _negocio("ep-p7")
    ayer, hace_8 = (_hoy() - timedelta(days=1)).isoformat(), (_hoy() - timedelta(days=8)).isoformat()
    base = {"tipo": "no_laborable", "nombre": "Se cerró ayer", "atiende": False}
    e = await _error(dashboard.dias_especiales_guardar_json(_Peticion({**base, "fecha": ayer}), usuario=_usuario(n), _csrf=None))
    assert e.status_code == 400 and "motivo" in e.detail
    r = await _post(n, {**base, "fecha": ayer, "motivo": "Lo declararon tarde"})
    assert r["resultado"] == "creado" and r["dia"]["pasado"] is True and r["dia"]["requiere_motivo"] is True and r["dia"]["editable"] is True
    e = await _error(dashboard.dias_especiales_guardar_json(_Peticion({**base, "fecha": hace_8, "motivo": "x"}), usuario=_usuario(n), _csrf=None))
    assert e.status_code == 400 and "más de 7 días" in e.detail


async def test_post_deja_auditoria_con_el_usuario_de_la_sesion_y_el_motivo():
    n = await _negocio("ep-p8")
    ayer = (_hoy() - timedelta(days=1)).isoformat()
    await _post(n, {"fecha": ayer, "tipo": "cierre_propio", "nombre": "Cierre", "motivo": "Falla eléctrica"}, usuario=_usuario(n, "adm2", "admin"))     # un día pasado solo lo toca el admin (D4)
    async with mem.async_session() as session:
        filas = list((await session.execute(select(mem.RegistroAuditoria).where(mem.RegistroAuditoria.negocio_id == n["id"]))).scalars().all())
    assert len(filas) == 1 and filas[0].accion == "dia_especial_creado" and filas[0].actor == "adm2"
    assert filas[0].payload["actor_rol"] == "admin"
    assert filas[0].payload["motivo"] == "Falla eléctrica" and filas[0].payload["despues"]["fecha"] == ayer


# ── POST: marcar mañana ─────────────────────────────────────────────────────

async def test_post_marcar_manana_cierra_manana_y_se_ve_enseguida():
    n = await _negocio("ep-m1")
    manana = (_hoy() + timedelta(days=1)).isoformat()
    r = await _post(n, {"operacion": "marcar_manana_no_laborable"})
    assert r["operacion"] == "marcar_manana_no_laborable" and r["resultado"] == "creado"
    assert r["dia"]["fecha"] == manana and r["dia"]["tipo"] == "no_laborable" and r["dia"]["atiende"] is False
    cal = await mem.obtener_calendario_negocio(n["id"])               # ≤ 60 s: aquí al instante (se invalidó la caché)
    assert _hoy() + timedelta(days=1) in cal.excepciones
    assert (await _post(n, {"operacion": "marcar_manana_no_laborable"}))["resultado"] == "sin_cambios"
    con_nombre = await _negocio("ep-m2")
    assert (await _post(con_nombre, {"operacion": "marcar_manana_no_laborable", "nombre": "Paro de transporte"}))["dia"]["nombre"] == "Paro de transporte"


# ── POST: cargar feriados ───────────────────────────────────────────────────

async def test_post_cargar_feriados_es_idempotente_y_restaura_los_quitados():
    n = await _negocio("ep-f1")
    r = await _post(n, {"operacion": "cargar_feriados_peru", "anio": 2026})
    assert r["ok"] is True and r["anio"] == 2026 and r["verificado"] is True and r["nota"] is None
    assert len(r["insertados"]) == 16 and r["ya_existian"] == [] and r["insertados"][0] == "2026-01-01"
    r = await _post(n, {"operacion": "cargar_feriados_peru", "anio": 2026})
    assert r["insertados"] == [] and len(r["ya_existian"]) == 16
    assert (await _get(n, desde="2026-12-08", hasta="2026-12-08"))["dias"][0]["nombre"] == "Inmaculada Concepción"
    # el administrador quita uno y luego pulsa «Cargar feriados» a propósito: vuelve
    quitado = _json(await dashboard.dias_especiales_quitar_json(fecha="2026-12-08", usuario=_usuario(n), _csrf=None))
    assert quitado["ok"] is True
    r = await _post(n, {"operacion": "cargar_feriados_peru", "anio": 2026})
    assert r["insertados"] == ["2026-12-08"]
    r = await _post(n, {"operacion": "cargar_feriados_peru", "anio": 2027})
    assert r["verificado"] is False and "no verificado" in r["nota"] and len(r["insertados"]) == 16


# ── DELETE ──────────────────────────────────────────────────────────────────

async def test_delete_quita_el_dia_y_responde_404_si_no_existe():
    n = await _negocio("ep-d1")
    await _post(n, {"fecha": "2026-11-20", "tipo": "cierre_propio", "nombre": "Inventario"})
    r = _json(await dashboard.dias_especiales_quitar_json(fecha="2026-11-20", usuario=_usuario(n), _csrf=None))
    assert r["ok"] is True and r["eliminado"]["fecha"] == "2026-11-20" and r["eliminado"]["nombre"] == "Inventario"
    assert (await _get(n, desde="2026-11-01", hasta="2026-11-30"))["dias"] == []
    e = await _error(dashboard.dias_especiales_quitar_json(fecha="2026-11-20", usuario=_usuario(n), _csrf=None))
    assert e.status_code == 404


@pytest.mark.parametrize("fecha,mensaje", [(None, "fecha"), ("", "fecha"), ("hoy", "AAAA-MM-DD")])
async def test_delete_exige_una_fecha_valida(fecha, mensaje):
    n = await _negocio("ep-d2")
    e = await _error(dashboard.dias_especiales_quitar_json(fecha=fecha, usuario=_usuario(n), _csrf=None))
    assert e.status_code == 400 and mensaje in e.detail


async def test_delete_de_un_dia_pasado_pide_motivo_y_tiene_limite():
    n = await _negocio("ep-d3")
    ayer = (_hoy() - timedelta(days=1)).isoformat()
    await _post(n, {"fecha": ayer, "tipo": "cierre_propio", "nombre": "Cierre", "motivo": "Alta"})
    e = await _error(dashboard.dias_especiales_quitar_json(fecha=ayer, usuario=_usuario(n), _csrf=None))
    assert e.status_code == 400 and "motivo" in e.detail
    r = _json(await dashboard.dias_especiales_quitar_json(fecha=ayer, motivo="Fue un error", usuario=_usuario(n), _csrf=None))
    assert r["ok"] is True
    e = await _error(dashboard.dias_especiales_quitar_json(fecha=(_hoy() - timedelta(days=9)).isoformat(), motivo="x", usuario=_usuario(n), _csrf=None))
    assert e.status_code == 400 and "más de 7 días" in e.detail


async def test_aislamiento_un_negocio_no_ve_ni_quita_los_dias_de_otro():
    a, b = await _negocio("ep-i1"), await _negocio("ep-i2")
    await _post(a, {"fecha": "2026-11-20", "tipo": "cierre_propio", "nombre": "Solo de A"})
    assert (await _get(b, desde="2026-11-01", hasta="2026-11-30"))["dias"] == []
    e = await _error(dashboard.dias_especiales_quitar_json(fecha="2026-11-20", usuario=_usuario(b), _csrf=None))
    assert e.status_code == 404
    assert len((await _get(a, desde="2026-11-01", hasta="2026-11-30"))["dias"]) == 1
    assert (await _get(b))["cobertura"]["ultima_fecha_cargada"] is None


# ── El contrato de configuración / horario no cambia ────────────────────────

async def test_configuracion_json_y_el_horario_existente_siguen_igual():
    n = await _negocio("ep-h1")
    await mem.guardar_horario_atencion(n["id"], 0, True, "08:00", "19:00")
    await _post(n, {"fecha": "2026-11-20", "tipo": "feriado", "nombre": "X"})
    cuerpo = _json(await dashboard.configuracion_json(usuario=_usuario(n)))
    assert {"negocio", "gabi", "horarios", "canales"} <= set(cuerpo)
    assert len(cuerpo["horarios"]) == 1 and cuerpo["horarios"][0]["dia_semana"] == 0
    assert not [k for k in cuerpo if "dia" in k and "especial" in k]            # el calendario va en su propia ruta (aditivo)


def test_el_contrato_documentado_describe_las_tres_rutas():
    doc = (RAIZ / "docs" / "contrato_calendario_negocio.md").read_text(encoding="utf-8")
    for fragmento in (
        "/dashboard/configuracion/dias-especiales.json", "GET", "POST", "DELETE", "marcar_manana_no_laborable", "cargar_feriados_peru",
        "zona_accion.pausa", "atencion_en_pausa", "calendario_pausa", "calendario_habil_desde", "X-CSRF-Token",
    ):
        assert fragmento in doc, fragmento
