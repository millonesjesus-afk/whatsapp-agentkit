# tests/test_tendencia_analitica.py — tendencia de Analítica: cómo se parte el período y que la suma de los tramos sea
# exactamente el total que muestra el Resumen.

import json
from datetime import datetime, timedelta
from decimal import Decimal

import pytest
from fastapi import HTTPException

from agent import dashboard, memory as mem
from agent.analitica_tendencia import MAX_TRAMOS, partir_periodo


def test_hasta_14_dias_es_un_punto_por_dia():
    g, t = partir_periodo("2026-10-01", "2026-10-03")
    assert g == "dia" and [x["desde"] for x in t] == ["2026-10-01", "2026-10-02", "2026-10-03"]
    assert all(x["desde"] == x["hasta"] and x["parcial"] is False for x in t)


def test_un_mes_corrido_son_semanas_desde_el_primer_dia_y_la_ultima_es_parcial():
    g, t = partir_periodo("2026-10-01", "2026-10-25")
    assert g == "semana"
    assert [(x["desde"], x["hasta"], x["parcial"]) for x in t] == [
        ("2026-10-01", "2026-10-07", False),
        ("2026-10-08", "2026-10-14", False),
        ("2026-10-15", "2026-10-21", False),
        ("2026-10-22", "2026-10-25", True),
    ]


def test_los_tramos_no_se_solapan_ni_dejan_huecos():
    for desde, hasta in (("2026-01-01", "2026-03-31"), ("2026-02-27", "2026-04-10"), ("2025-11-03", "2026-12-20")):
        _, t = partir_periodo(desde, hasta)
        assert t[0]["desde"] == desde and t[-1]["hasta"] == hasta
        for a, b in zip(t, t[1:]):
            siguiente = datetime.strptime(a["hasta"], "%Y-%m-%d") + timedelta(days=1)
            assert b["desde"] == siguiente.strftime("%Y-%m-%d")


def test_periodos_largos_van_por_mes_y_marcan_los_meses_incompletos():
    g, t = partir_periodo("2026-01-15", "2026-05-10")
    assert g == "mes"
    assert [(x["desde"], x["hasta"], x["parcial"]) for x in t] == [
        ("2026-01-15", "2026-01-31", True),
        ("2026-02-01", "2026-02-28", False),
        ("2026-03-01", "2026-03-31", False),
        ("2026-04-01", "2026-04-30", False),
        ("2026-05-01", "2026-05-10", True),
    ]


def test_rango_invertido_o_demasiado_largo_se_rechaza():
    with pytest.raises(ValueError):
        partir_periodo("2026-10-25", "2026-10-01")
    with pytest.raises(ValueError):
        partir_periodo("2020-01-01", "2026-12-31")
    assert MAX_TRAMOS == 36


async def _negocio(codigo: str):
    negocio = await mem.crear_negocio(f"Negocio {codigo}", codigo)
    canal = await mem.crear_canal_whatsapp(
        nombre=f"Canal {codigo}", phone_number_id=f"4097000{codigo[-2:]}", negocio_id=negocio["id"],
    )
    return negocio, canal


def _dia_lima(delta: int = 0) -> str:
    return ((datetime.utcnow() - timedelta(hours=5)) + timedelta(days=delta)).strftime("%Y-%m-%d")


async def test_la_suma_de_los_tramos_es_el_total_del_resumen():
    negocio, canal = await _negocio("tnd-01")
    admin = {"negocio_id": negocio["id"], "rol": "admin", "username": "jesus"}
    for i in range(1, 5):
        tel = f"51906601{i:02d}"
        await mem.actualizar_lead(tel, negocio_id=negocio["id"], numero_whatsapp_id="x")
        await mem.resolver_conversation_activa(tel, negocio["id"], canal["id"])
    for tel, producto, precio in (("5190660101", "Terma", "400"), ("5190660102", "Secadora", "250.50")):
        _, opp = await mem.resolver_conversation_activa(tel, negocio["id"], canal["id"])
        assert await mem.cerrar_opportunity_con_venta(
            opp.id, opp.version, [{"producto": producto, "precio": precio, "marca": "M", "proveedor": "P"}],
            {"resultado": "vendido"},
        )

    desde, hasta = _dia_lima(-2), _dia_lima(0)
    tendencia = json.loads((await dashboard.analitica_tendencia_json(usuario=admin, desde=desde, hasta=hasta)).body)
    resumen = json.loads((await dashboard.analitica_json(usuario=admin, desde=desde, hasta=hasta)).body)

    assert tendencia["granularidad"] == "dia" and len(tendencia["puntos"]) == 3
    assert sum(p["clientes"] for p in tendencia["puntos"]) == resumen["flujo_periodo"]["leads"] == 4
    assert sum(p["casos"] for p in tendencia["puntos"]) == resumen["flujo_periodo"]["oportunidades"]
    assert sum(p["ventas"] for p in tendencia["puntos"]) == resumen["flujo_periodo"]["ventas"] == 2
    assert sum(Decimal(p["valor"]) for p in tendencia["puntos"]) == Decimal(resumen["valor_vendido"]["monto"]) == Decimal("650.50")


async def test_un_asesor_solo_ve_su_propia_tendencia_y_los_filtros_se_validan():
    negocio, canal = await _negocio("tnd-02")
    tel = "5190660109"
    await mem.actualizar_lead(tel, negocio_id=negocio["id"], numero_whatsapp_id="x")
    await mem.resolver_conversation_activa(tel, negocio["id"], canal["id"])
    await mem.asignar_asesor_a_lead(tel, "ana")
    hoy = _dia_lima(0)
    de_ana = {"negocio_id": negocio["id"], "rol": "asesor", "username": "ana"}
    de_beto = {"negocio_id": negocio["id"], "rol": "asesor", "username": "beto"}
    # el asesor pide a otro por query string: se ignora y se le aplica el suyo
    ana = json.loads((await dashboard.analitica_tendencia_json(usuario=de_ana, desde=hoy, hasta=hoy, asesor="beto")).body)
    beto = json.loads((await dashboard.analitica_tendencia_json(usuario=de_beto, desde=hoy, hasta=hoy)).body)
    assert ana["puntos"][0]["clientes"] == 1 and beto["puntos"][0]["clientes"] == 0

    admin = {"negocio_id": negocio["id"], "rol": "admin", "username": "jesus"}
    with pytest.raises(HTTPException) as e:
        await dashboard.analitica_tendencia_json(usuario=admin, desde=hoy, hasta=hoy, formato="gif")
    assert e.value.status_code == 400
    with pytest.raises(HTTPException) as e:
        await dashboard.analitica_tendencia_json(usuario=admin, desde="2026-10-25", hasta="2026-10-01")
    assert e.value.status_code == 400
