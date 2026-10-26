# tests/test_metas_analitica.py — metas mensuales de Analítica: cálculo del avance, guardado con auditoría y alcance
# por rol (solo el admin edita; un asesor solo ve la suya).

import json
from datetime import datetime, timedelta

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from agent import analitica_metas as am, dashboard, memory as mem


# ── Cálculo ───────────────────────────────────────────────────────────────────

def test_mes_y_rango():
    assert am.mes_de("2026-10-25") == "2026-10"
    assert am.rango_del_mes("2026-10") == ("2026-10-01", "2026-10-31")
    assert am.rango_del_mes("2028-02") == ("2028-02-01", "2028-02-29")
    assert am.nombre_mes("2026-10") == "octubre"
    for malo in ("2026-13", "2026/10", "", "26-10"):
        with pytest.raises(ValueError):
            am.validar_mes(malo)


def test_mes_en_curso_proyecta_en_linea_recta():
    a = am.avance(30, 20, "2026-10", "2026-10-25")
    assert (a["dias_transcurridos"], a["dias_restantes"], a["dias_mes"]) == (25, 6, 31)
    assert a["ritmo_diario"] == 0.8 and a["proyeccion"] == 24.8
    assert a["faltan"] == 10 and a["necesario_por_dia"] == pytest.approx(1.667, abs=1e-3)
    assert a["estado"] == "por_debajo"
    assert am.avance(24, 20, "2026-10", "2026-10-25")["estado"] == "en_ritmo"


def test_cumplida_mes_cerrado_y_mes_futuro():
    assert am.avance(15, 18, "2026-10", "2026-10-10")["estado"] == "cumplida"
    cerrado = am.avance(30, 25, "2026-09", "2026-10-25")
    assert cerrado["proyeccion"] == 25 and cerrado["dias_restantes"] == 0 and cerrado["necesario_por_dia"] is None
    assert cerrado["estado"] == "por_debajo"
    futuro = am.avance(30, 0, "2026-11", "2026-10-25")
    assert futuro["proyeccion"] is None and futuro["ritmo_diario"] is None and futuro["estado"] is None


# ── Endpoints ─────────────────────────────────────────────────────────────────

async def _negocio(codigo: str):
    negocio = await mem.crear_negocio(f"Negocio {codigo}", codigo)
    canal = await mem.crear_canal_whatsapp(
        nombre=f"Canal {codigo}", phone_number_id=f"4094000{codigo[-2:]}", negocio_id=negocio["id"],
    )
    await mem.crear_usuario("ana", "pw12345", "Ana", "asesor", negocio["id"])
    await mem.crear_usuario("beto", "pw12345", "Beto", "asesor", negocio["id"])
    return negocio, canal


async def _venta(negocio, canal, telefono, asesor):
    await mem.actualizar_lead(telefono, negocio_id=negocio["id"], numero_whatsapp_id="x")
    _, opp = await mem.resolver_conversation_activa(telefono, negocio["id"], canal["id"])
    await mem.asignar_asesor_a_lead(telefono, asesor)
    _, opp = await mem.resolver_conversation_activa(telefono, negocio["id"], canal["id"])
    assert await mem.cerrar_opportunity_con_venta(
        opp.id, opp.version, [{"producto": "Terma", "precio": "100", "marca": "M", "proveedor": "P"}], {"resultado": "vendido"},
    )


class _Peticion:
    def __init__(self, cuerpo):
        self._cuerpo = cuerpo

    async def json(self):
        return self._cuerpo


def _mes_actual() -> str:
    return (datetime.utcnow() - timedelta(hours=5)).strftime("%Y-%m")


async def test_admin_guarda_y_ve_metas_con_lo_logrado():
    negocio, canal = await _negocio("met-01")
    await _venta(negocio, canal, "51904800001", "ana")
    await _venta(negocio, canal, "51904800002", "ana")
    await _venta(negocio, canal, "51904800003", "beto")
    admin = {"negocio_id": negocio["id"], "rol": "admin", "username": "jesus"}
    mes = _mes_actual()

    r = json.loads((await dashboard.analitica_metas_guardar_json(
        _Peticion({"mes": mes, "metas": [{"asesor": "", "objetivo": 30}, {"asesor": "ana", "objetivo": 10}, {"asesor": "beto", "objetivo": 5}]}),
        usuario=admin,
    )).body)
    assert r["metas"] == {"": 30.0, "ana": 10.0, "beto": 5.0}

    m = json.loads((await dashboard.analitica_metas_json(usuario=admin)).body)
    assert m["mes"] == mes and m["puede_editar"] is True
    assert (m["total"]["objetivo"], m["total"]["logrado"]) == (30.0, 3)
    por = {a["username"]: a for a in m["asesores"]}
    assert (por["ana"]["objetivo"], por["ana"]["logrado"]) == (10.0, 2)
    assert (por["beto"]["objetivo"], por["beto"]["logrado"]) == (5.0, 1)
    assert m["suma_asesores"] == 15 and m["suma_distinta"] is True  # la total es independiente y se avisa

    # quedó en el registro de auditoría con el antes y el después
    async with mem.async_session() as s:
        aud = (await s.execute(select(mem.RegistroAuditoria).where(
            mem.RegistroAuditoria.negocio_id == negocio["id"], mem.RegistroAuditoria.accion == "metas_actualizadas",
        ))).scalars().all()
    assert len(aud) == 1 and aud[0].payload["antes"] == {} and aud[0].payload["despues"]["ana"] == 10.0

    # objetivo vacío la borra; sin cambios no se audita otra vez
    await dashboard.analitica_metas_guardar_json(_Peticion({"mes": mes, "metas": [{"asesor": "beto", "objetivo": None}]}), usuario=admin)
    assert await mem.obtener_metas(negocio["id"], mes) == {"": 30.0, "ana": 10.0}


async def test_un_asesor_solo_ve_su_meta_y_el_supervisor_no_edita():
    negocio, canal = await _negocio("met-02")
    mes = _mes_actual()
    await mem.guardar_metas(negocio["id"], mes, [("", 30), ("ana", 10), ("beto", 5)], autor="jesus")
    ana = json.loads((await dashboard.analitica_metas_json(usuario={"negocio_id": negocio["id"], "rol": "asesor", "username": "ana"})).body)
    assert ana["total"] is None and [a["username"] for a in ana["asesores"]] == ["ana"] and ana["puede_editar"] is False
    assert ana["suma_asesores"] is None
    sup = json.loads((await dashboard.analitica_metas_json(usuario={"negocio_id": negocio["id"], "rol": "supervisor", "username": "s"})).body)
    assert sup["total"]["objetivo"] == 30 and sup["puede_editar"] is False
    # la ruta de guardar exige el rol admin y la protección CSRF
    deps = {d.call.__name__ for d in next(
        r for r in dashboard.router.routes if getattr(r, "path", "") == "/dashboard/analitica/metas.json" and "POST" in r.methods
    ).dependant.dependencies}
    assert "verificar_csrf" in deps


async def test_el_mes_sale_del_periodo_y_se_validan_los_datos():
    negocio, _ = await _negocio("met-03")
    admin = {"negocio_id": negocio["id"], "rol": "admin", "username": "jesus"}
    m = json.loads((await dashboard.analitica_metas_json(usuario=admin, hasta="2026-09-30")).body)
    assert m["mes"] == "2026-09" and m["nombre_mes"] == "septiembre" and m["total"]["objetivo"] is None
    with pytest.raises(HTTPException) as e:
        await dashboard.analitica_metas_json(usuario=admin, mes="2026-13")
    assert e.value.status_code == 400
    for malo in ({"mes": "2026-10", "metas": [{"asesor": "nadie", "objetivo": 3}]},
                 {"mes": "2026-10", "metas": [{"asesor": "", "objetivo": -1}]},
                 {"mes": "2026-10", "metas": [{"asesor": "", "objetivo": 2.5}]},
                 {"mes": "2026-10", "metas": [{"asesor": "", "objetivo": "30"}]},
                 {"mes": "x", "metas": []}):
        with pytest.raises(HTTPException) as e:
            await dashboard.analitica_metas_guardar_json(_Peticion(malo), usuario=admin)
        assert e.value.status_code == 400
