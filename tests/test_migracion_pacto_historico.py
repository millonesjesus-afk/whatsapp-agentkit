# tests/test_migracion_pacto_historico.py — la migración de datos b3e8f5a2c716
# completa con TEA 40 % / IGV 18 % las ventas financiadas cerradas antes de que
# existiera el pacto congelado. Se ejecuta la migración REAL sobre datos
# creados con el código de la app (sin pacto), no una copia de su lógica.

import importlib.util
from pathlib import Path

from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext

from agent import memory as mem

_RUTA = Path(__file__).resolve().parent.parent / "migrations" / "versions" / "b3e8f5a2c716_completar_pacto_historico_con_tea_40.py"


async def _correr_migracion():
    spec = importlib.util.spec_from_file_location("mig_pacto_historico", _RUTA)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)

    def _upgrade(sync_conn):
        with Operations.context(MigrationContext.configure(sync_conn)):
            modulo.upgrade()

    async with mem.engine.begin() as conn:
        await conn.run_sync(_upgrade)


async def _venta_historica(codigo: str, telefono: str, precios: list[str], modalidad: str, cuotas: str | None):
    negocio = await mem.crear_negocio(f"Negocio Hist {codigo}", codigo)
    canal = await mem.crear_canal_whatsapp(
        nombre=f"Canal {codigo}", phone_number_id=f"6091{codigo[-4:]}", negocio_id=negocio["id"],
    )
    await mem.actualizar_lead(telefono, negocio_id=negocio["id"], numero_whatsapp_id="x")
    _, opp = await mem.resolver_conversation_activa(telefono, negocio["id"], canal["id"])
    await mem.cerrar_opportunity_con_venta(
        opp.id, opp.version, [{"producto": f"P{i}", "precio": p} for i, p in enumerate(precios)],
        {"resultado": "vendido", "modalidad_pago": modalidad, "cuotas": cuotas},
    )
    return opp.id


async def _leer(opp_id: str, telefono: str):
    async with mem.async_session() as session:
        return await session.get(mem.Opportunity, opp_id), await session.get(mem.Lead, telefono)


async def test_completa_la_venta_financiada_historica_con_tea_40():
    opp_id = await _venta_historica("g-mig-01", "51920000001", ["1749"], "financiado", "36")
    o, l = await _leer(opp_id, "51920000001")
    assert o.cuota_pactada is None  # punto de partida: histórica, sin pacto

    await _correr_migracion()
    o, l = await _leer(opp_id, "51920000001")
    assert abs(float(o.cuota_pactada) - 87.20) < 0.05
    assert float(o.monto_financiado) == 1749.0
    assert o.tea_pactada == "0.4" and o.igv_pactado == "0.18"
    assert l.cuota_pactada == o.cuota_pactada and l.tea_pactada == "0.4"


async def test_suma_varias_lineas_y_es_idempotente():
    opp_id = await _venta_historica("g-mig-02", "51920000002", ["1000", "S/ 500.00"], "financiado", "12")
    await _correr_migracion()
    o1, _ = await _leer(opp_id, "51920000002")
    assert float(o1.monto_financiado) == 1500.0
    await _correr_migracion()
    o2, _ = await _leer(opp_id, "51920000002")
    assert o2.cuota_pactada == o1.cuota_pactada


async def test_no_toca_contado_ni_precios_no_numericos_ni_pactos_reales():
    contado = await _venta_historica("g-mig-03", "51920000003", ["1749"], "contado", None)
    no_num = await _venta_historica("g-mig-04", "51920000004", ["EN CREACIÓN"], "financiado", "12")
    real = await _venta_historica("g-mig-05", "51920000005", ["1000"], "financiado", "12")
    async with mem.async_session() as session:
        o = await session.get(mem.Opportunity, real)
        o.monto_financiado, o.cuota_pactada, o.tea_pactada, o.igv_pactado = "1000.00", "77.77", "0.55", "0.18"
        await session.commit()

    await _correr_migracion()
    assert (await _leer(contado, "51920000003"))[0].cuota_pactada is None
    assert (await _leer(no_num, "51920000004"))[0].cuota_pactada is None
    o_real = (await _leer(real, "51920000005"))[0]
    assert o_real.cuota_pactada == "77.77" and o_real.tea_pactada == "0.55"
