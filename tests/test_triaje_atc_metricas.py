# tests/test_triaje_atc_metricas.py — Métrica del embudo CONFIGURABLE (2026-10-08, decisión del dueño): cada
# `consulta_atc` es una Opportunity más y baja la tasa de cierre aunque nunca fue comercial. Por negocio:
#   metricas_excluir_consulta_atc        "1"/"0"   (default "0" = comportamiento de siempre, SIN campos nuevos)
#   metricas_excluir_consulta_atc_desde  AAAA-MM-DD (Lima, opcional): solo se excluyen las creadas desde ese día
# Con la exclusión activa el contrato es ADITIVO: las claves de siempre quedan (con la cifra comercial) y se suman la
# bruta, la tasa bruta y `consultas_no_comerciales {cantidad, porcentaje_de_contactos}`.

import json
from datetime import datetime, timedelta

import pytest

from agent import dashboard
from agent import memory as mem

_n = {"i": 0}


async def _negocio(codigo: str):
    negocio = await mem.crear_negocio(f"Negocio {codigo}", codigo)
    _n["i"] += 1
    canal = await mem.crear_canal_whatsapp(nombre="C", phone_number_id=f"4099{_n['i']:06d}", negocio_id=negocio["id"])
    return negocio, canal


async def _opp(negocio, canal, telefono, resultado=None, creado=None, asesor=None):
    conv, opp = await mem.resolver_conversation_activa(telefono, negocio["id"], canal["id"])
    if asesor:
        await mem.intentar_asignar_conversation(conv.id, conv.version, asesor)
    async with mem.async_session() as s:
        o = await s.get(mem.Opportunity, opp.id)
        o.resultado = resultado
        if creado is not None:
            o.creado = creado
        await s.commit()
    return opp


async def _vender(opp):
    assert await mem.cerrar_opportunity_con_venta(
        opp.id, opp.version, [{"producto": "Terma", "precio": "100", "marca": "M", "proveedor": "P"}], {"resultado": "vendido"},
    )


def _hoy():
    dia = (datetime.utcnow() - timedelta(hours=5)).strftime("%Y-%m-%d")
    return mem.rango_periodo_utc(dia, dia)


async def _sembrar_base(negocio, canal):
    """4 oportunidades: 2 consulta_atc, 1 vendida, 1 sin resultado."""
    await _opp(negocio, canal, "51950000001", "consulta_atc")
    await _opp(negocio, canal, "51950000002", "consulta_atc")
    vendida = await _opp(negocio, canal, "51950000003")
    await _vender(vendida)
    await _opp(negocio, canal, "51950000004")


async def test_por_defecto_el_contrato_no_cambia_ni_una_clave():
    negocio, canal = await _negocio("mt-a")
    await _sembrar_base(negocio, canal)
    inicio, fin = _hoy()
    assert await mem.calcular_embudo_comercial(negocio["id"], inicio, fin) == {"oportunidades": 4, "ventas": 1, "tasa_cierre": 0.25}
    assert await mem.contar_flujo_periodo(negocio["id"], inicio, fin) == {
        "leads": 4, "conversaciones": 4, "oportunidades": 4, "ventas": 1,
        "ventas_de_leads_del_periodo": 1, "ventas_de_periodos_anteriores": 0,
    }
    assert await mem.obtener_politica_metricas(negocio["id"]) == {"excluir_consulta_atc": False, "desde": None}


@pytest.mark.parametrize("valor", ["0", "", "no", "xyz", "2", "false"])
async def test_un_valor_apagado_o_invalido_deja_todo_como_estaba(valor):
    negocio, canal = await _negocio("mt-b")
    await _sembrar_base(negocio, canal)
    await mem.guardar_configuracion(mem.CLAVE_METRICAS_EXCLUIR_ATC, valor, negocio_id=negocio["id"])
    inicio, fin = _hoy()
    assert await mem.calcular_embudo_comercial(negocio["id"], inicio, fin) == {"oportunidades": 4, "ventas": 1, "tasa_cierre": 0.25}


@pytest.mark.parametrize("valor", ["1", "true", "si", "sí", "ON", " 1 "])
async def test_activa_excluye_del_denominador_y_reporta_las_consultas_sin_ocultarlas(valor):
    negocio, canal = await _negocio("mt-c")
    await _sembrar_base(negocio, canal)
    await mem.guardar_configuracion(mem.CLAVE_METRICAS_EXCLUIR_ATC, valor, negocio_id=negocio["id"])
    inicio, fin = _hoy()

    embudo = await mem.calcular_embudo_comercial(negocio["id"], inicio, fin)
    assert embudo["oportunidades"] == 2 and embudo["ventas"] == 1 and embudo["tasa_cierre"] == 0.5     # comercial
    assert embudo["oportunidades_brutas"] == 4 and embudo["tasa_cierre_bruta"] == 0.25                  # bruta sigue disponible
    assert embudo["consultas_no_comerciales"] == {"cantidad": 2, "porcentaje_de_contactos": 50.0, "excluidas_desde": None}
    assert embudo["excluye_consulta_atc"] is True
    assert {"oportunidades", "ventas", "tasa_cierre"} <= set(embudo)                                    # no se quita nada

    flujo = await mem.contar_flujo_periodo(negocio["id"], inicio, fin)
    assert flujo["oportunidades"] == 2 and flujo["oportunidades_brutas"] == 4 and flujo["ventas"] == 1
    assert flujo["consultas_no_comerciales"] == embudo["consultas_no_comerciales"]
    assert {"leads", "conversaciones", "oportunidades", "ventas"} <= set(flujo)
    assert flujo["oportunidades"] == embudo["oportunidades"]                                            # misma cifra en ambos


async def test_si_todo_fueron_consultas_la_tasa_comercial_es_none_y_no_cero():
    negocio, canal = await _negocio("mt-d")
    await _opp(negocio, canal, "51950000011", "consulta_atc")
    await mem.guardar_configuracion(mem.CLAVE_METRICAS_EXCLUIR_ATC, "1", negocio_id=negocio["id"])
    inicio, fin = _hoy()
    embudo = await mem.calcular_embudo_comercial(negocio["id"], inicio, fin)
    assert embudo["oportunidades"] == 0 and embudo["tasa_cierre"] is None and embudo["tasa_cierre_bruta"] == 0.0
    assert embudo["consultas_no_comerciales"]["porcentaje_de_contactos"] == 100.0


async def test_sin_oportunidades_el_porcentaje_es_none():
    negocio, _ = await _negocio("mt-e")
    await mem.guardar_configuracion(mem.CLAVE_METRICAS_EXCLUIR_ATC, "1", negocio_id=negocio["id"])
    inicio, fin = _hoy()
    embudo = await mem.calcular_embudo_comercial(negocio["id"], inicio, fin)
    assert embudo["oportunidades"] == 0 and embudo["tasa_cierre"] is None and embudo["tasa_cierre_bruta"] is None
    assert embudo["consultas_no_comerciales"] == {"cantidad": 0, "porcentaje_de_contactos": None, "excluidas_desde": None}


async def test_la_fecha_de_corte_solo_excluye_las_consultas_creadas_desde_ese_dia():
    negocio, canal = await _negocio("mt-f")
    inicio, fin = mem.rango_periodo_utc("2026-05-10", "2026-05-12")
    await _opp(negocio, canal, "51950000021", "consulta_atc", creado=datetime(2026, 5, 10, 15, 0))   # 10:00 Lima del 10
    await _opp(negocio, canal, "51950000022", "consulta_atc", creado=datetime(2026, 5, 12, 15, 0))   # 10:00 Lima del 12
    await _opp(negocio, canal, "51950000023", None, creado=datetime(2026, 5, 11, 15, 0))
    await mem.guardar_configuracion(mem.CLAVE_METRICAS_EXCLUIR_ATC, "1", negocio_id=negocio["id"])

    async def embudo():
        return await mem.calcular_embudo_comercial(negocio["id"], inicio, fin)

    assert (await embudo())["consultas_no_comerciales"]["cantidad"] == 2                  # sin corte: todo el período
    await mem.guardar_configuracion(mem.CLAVE_METRICAS_EXCLUIR_ATC_DESDE, "2026-05-12", negocio_id=negocio["id"])
    e = await embudo()
    assert e["consultas_no_comerciales"]["cantidad"] == 1 and e["oportunidades"] == 2 and e["oportunidades_brutas"] == 3
    assert e["consultas_no_comerciales"]["excluidas_desde"] == "2026-05-12T05:00:00"      # medianoche de Lima en UTC
    await mem.guardar_configuracion(mem.CLAVE_METRICAS_EXCLUIR_ATC_DESDE, "2026-05-13", negocio_id=negocio["id"])
    assert (await embudo())["consultas_no_comerciales"]["cantidad"] == 0                  # corte posterior al período
    await mem.guardar_configuracion(mem.CLAVE_METRICAS_EXCLUIR_ATC_DESDE, "2026-01-01", negocio_id=negocio["id"])
    assert (await embudo())["consultas_no_comerciales"]["cantidad"] == 2                  # corte anterior al período
    await mem.guardar_configuracion(mem.CLAVE_METRICAS_EXCLUIR_ATC_DESDE, "no-es-fecha", negocio_id=negocio["id"])
    assert (await embudo())["consultas_no_comerciales"]["cantidad"] == 2                  # inválida = sin corte


async def test_la_configuracion_es_por_negocio():
    a, canal_a = await _negocio("mt-g1")
    b, canal_b = await _negocio("mt-g2")
    for negocio, canal, base in ((a, canal_a, "5195000003"), (b, canal_b, "5195000004")):
        await _opp(negocio, canal, f"{base}1", "consulta_atc")
        await _opp(negocio, canal, f"{base}2")
    await mem.guardar_configuracion(mem.CLAVE_METRICAS_EXCLUIR_ATC, "1", negocio_id=a["id"])
    inicio, fin = _hoy()
    assert (await mem.calcular_embudo_comercial(a["id"], inicio, fin))["oportunidades"] == 1
    assert await mem.calcular_embudo_comercial(b["id"], inicio, fin) == {"oportunidades": 2, "ventas": 0, "tasa_cierre": None}\
        or (await mem.calcular_embudo_comercial(b["id"], inicio, fin))["oportunidades"] == 2


async def test_los_filtros_de_asesor_y_campana_se_aplican_tambien_a_las_consultas():
    negocio, canal = await _negocio("mt-h")
    await _opp(negocio, canal, "51950000041", "consulta_atc", asesor="ana")
    await _opp(negocio, canal, "51950000042", "consulta_atc", asesor="beto")
    await _opp(negocio, canal, "51950000043", None, asesor="ana")
    await mem.guardar_configuracion(mem.CLAVE_METRICAS_EXCLUIR_ATC, "1", negocio_id=negocio["id"])
    inicio, fin = _hoy()
    e = await mem.calcular_embudo_comercial(negocio["id"], inicio, fin, asesor="ana")
    assert (e["oportunidades"], e["oportunidades_brutas"], e["consultas_no_comerciales"]["cantidad"]) == (1, 2, 1)
    f = await mem.contar_flujo_periodo(negocio["id"], inicio, fin, asesor="ana")
    assert (f["oportunidades"], f["oportunidades_brutas"]) == (1, 2)


async def test_el_endpoint_de_analitica_trae_los_campos_aditivos_solo_si_esta_activo():
    negocio, canal = await _negocio("mt-i")
    await _sembrar_base(negocio, canal)
    usuario = {"negocio_id": negocio["id"], "rol": "admin", "username": "admin1"}
    antes = json.loads((await dashboard.analitica_json(usuario=usuario)).body)
    assert antes["embudo"] == {"oportunidades": 4, "ventas": 1, "tasa_cierre": 0.25}
    await mem.guardar_configuracion(mem.CLAVE_METRICAS_EXCLUIR_ATC, "1", negocio_id=negocio["id"])
    despues = json.loads((await dashboard.analitica_json(usuario=usuario)).body)
    assert despues["embudo"]["tasa_cierre"] == 0.5 and despues["embudo"]["consultas_no_comerciales"]["cantidad"] == 2
    assert despues["flujo_periodo"]["consultas_no_comerciales"]["cantidad"] == 2
    assert set(antes) == set(despues)                         # ninguna clave de primer nivel se quita ni se suma


@pytest.mark.parametrize("excluir, desde, activo, corte", [
    (None, None, False, None), ("1", "", True, None), ("0", "2026-05-12", False, datetime(2026, 5, 12, 5, 0)),
    ("1", "2026-05-12", True, datetime(2026, 5, 12, 5, 0)), ("1", "2026-05-12T10:30", True, datetime(2026, 5, 12, 10, 30)),
    ("1", "basura", True, None), ("sí", "2026-13-45", True, None),
])
def test_normalizar_politica_metricas(excluir, desde, activo, corte):
    assert mem.normalizar_politica_metricas(excluir, desde) == {"excluir_consulta_atc": activo, "desde": corte}


async def test_si_la_lectura_de_la_configuracion_falla_no_se_excluye_nada(monkeypatch):
    async def explota(*a, **k):
        raise RuntimeError("base caída")
    monkeypatch.setattr(mem, "obtener_configuracion", explota)
    assert await mem.obtener_politica_metricas("x") == {"excluir_consulta_atc": False, "desde": None}
