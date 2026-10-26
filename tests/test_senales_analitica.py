# tests/test_senales_analitica.py — reglas de las señales de Analítica (Etapa 4): estadística, umbrales aprobados,
# prioridad, límite de tres y alcance por rol.

import json
from datetime import datetime, timedelta

import pytest

from agent import analitica_senales as sen, dashboard, memory as mem


def _grupo(titulo, formato, empresa, leads, ventas):
    return {"titulo": titulo, "formato": formato, "empresa": empresa, "leads": leads, "ventas": ventas}


# Los números reales de octubre (1 al 25) de Cálidda Hogar.
GRUPOS_OCTUBRE = [
    _grupo("Se paga en tu recibo", "video", "Estratek", 124, 1),
    _grupo("Chatea con nosotros", "video", "Cálidda", 95, 2),
    _grupo("Chatea con nosotros", "video", "Cálidda", 54, 1),
    _grupo("Financia tu artefacto", "imagen", "Cálidda", 49, 4),
    _grupo("Una sola vez y te vas", "video", "Estratek", 33, 1),
    _grupo("Instalación con obras mínimas", "video", "Estratek", 28, 3),
    _grupo("Financia tu artefacto", "imagen", "Cálidda", 27, 0),
    _grupo("Renueva tu cocina", "imagen", "Estratek", 12, 3),
    _grupo("Agua Caliente Cálidda", "imagen", "Estratek", 9, 1),
    _grupo("Cotiza sin compromiso", "imagen", "Cálidda", 3, 0),
    _grupo("Chatea con nosotros", "imagen", "Cálidda", 1, 0),
    _grupo("Paga tu cocina en cuotas", "imagen", "Estratek", 1, 0),
]


def test_fisher_coincide_con_el_valor_conocido_de_octubre():
    assert sen.fisher_dos_colas(8, 94, 8, 326) == pytest.approx(0.0165, abs=1e-4)
    assert sen.fisher_dos_colas(0, 10, 0, 10) == 1.0  # nada que comparar
    assert sen.fisher_dos_colas(5, 5, 5, 5) == pytest.approx(1.0)


def test_binomial_mitad_dos_colas():
    assert sen.binomial_mitad_dos_colas(5, 10) == pytest.approx(1.0)
    assert sen.binomial_mitad_dos_colas(479, 479 + 283) < 0.001
    assert sen.binomial_mitad_dos_colas(0, 0) == 1.0


def test_confianza_media_alta_o_nada():
    assert sen.confianza_de(0.004) == "alta"
    assert sen.confianza_de(0.017) == "media"
    assert sen.confianza_de(0.055) is None


def test_r1_formato_aparece_con_los_datos_de_octubre():
    s = sen.regla_formato(GRUPOS_OCTUBRE)
    assert s["tipo"] == "formato_rinde_distinto" and s["confianza"] == "media" and s["p"] == pytest.approx(0.0165, abs=1e-3)
    assert s["texto"] == "La imagen cierra 3,3 veces más que el video"
    assert "8 ventas de 102 clientes (7,8 por 100)" in s["que_vi"] and "8 de 334 (2,4 por 100)" in s["que_vi"]


def test_r1_no_aparece_con_poca_muestra_o_pocas_ventas():
    pocos = [_grupo("a", "imagen", "X", 15, 3), _grupo("b", "video", "X", 300, 3)]
    assert sen.regla_formato(pocos) is None  # imagen tiene menos de 20 clientes
    pocas_ventas = [_grupo("a", "imagen", "X", 100, 3), _grupo("b", "video", "X", 300, 1)]
    assert sen.regla_formato(pocas_ventas) is None  # solo 4 ventas en total


def test_r3_empresa_no_aparece_cuando_la_diferencia_es_ruido():
    assert sen.regla_empresa(GRUPOS_OCTUBRE) is None  # 3,1 contra 4,3 por 100, p = 0,47


def test_r3_empresa_aparece_con_una_diferencia_clara():
    grupos = [_grupo("a", "imagen", "Cálidda", 100, 20), _grupo("b", "imagen", "Estratek", 100, 3)]
    s = sen.regla_empresa(grupos)
    assert s and s["texto"] == "Cálidda cierra 6,7 veces más que Estratek"


def test_r2_anuncio_exige_diferencia_muy_clara_y_ningun_anuncio_de_octubre_la_cumple():
    assert sen.regla_anuncio(GRUPOS_OCTUBRE) is None
    grupos = [_grupo("Bueno", "video", "X", 40, 14), _grupo("Resto", "video", "X", 200, 6)]
    s = sen.regla_anuncio(grupos)
    assert s and s["confianza"] == "alta" and s["texto"] == "«Bueno» cierra más que el resto de los anuncios"


def test_r4_cambio_frente_al_anterior_con_base_completa():
    s = sen.regla_cambio_frente_al_anterior({"leads": 300, "ventas": 20}, {"leads": 200, "ventas": 18}, "06/11 – 30/11")
    assert s and s["texto"] == "Los clientes nuevos subieron 50% frente al período anterior"
    assert sen.regla_cambio_frente_al_anterior({"leads": 105, "ventas": 6}, {"leads": 100, "ventas": 5}, "x") is None


def test_r4_y_r6_no_se_evaluan_con_base_corta():
    p = sen.periodo_anterior("2026-10-01", "2026-10-25")
    assert p == {"desde": "2026-09-06", "hasta": "2026-09-30", "dias": 25, "base_corta": True}
    assert sen.periodo_anterior("2026-11-01", "2026-11-25")["base_corta"] is False
    assert sen.periodo_anterior("x", "y") is None and sen.periodo_anterior("2026-11-25", "2026-11-01") is None


def test_r5_casos_sin_asesor_con_los_umbrales_aprobados():
    s = sen.regla_sin_asesor({"oportunidades": 122, "ventas": 0}, 487)
    assert s["texto"] == "122 casos (25%) no tienen asesor asignado" and s["confianza"] == "alta"
    assert sen.regla_sin_asesor({"oportunidades": 19, "ventas": 0}, 100) is None  # menos de 20 casos
    assert sen.regla_sin_asesor({"oportunidades": 30, "ventas": 0}, 487) is None  # menos del 10 %
    assert sen.regla_sin_asesor(None, 100) is None


def test_r6_sin_respuesta_cambia_frente_al_anterior():
    ahora = [{"resultado": "sin_respuesta", "total": 120}, {"resultado": "vendido", "total": 30}, {"resultado": "consulta_atc", "total": 50}]
    antes = [{"resultado": "sin_respuesta", "total": 60}, {"resultado": "vendido", "total": 90}]
    s = sen.regla_sin_respuesta(ahora, antes, True, "06/11 – 30/11")
    assert s and s["tipo"] == "sin_respuesta_cambia" and "20 puntos más" not in s["texto"]
    assert "80% de los casos (120 de 150)" in s["que_vi"] and "40% (60 de 150)" in s["que_vi"]
    assert sen.regla_sin_respuesta(ahora, ahora, True, "x") is None


def test_r7_datos_incompletos():
    r = sen.reglas_datos_incompletos(
        {"ventas_excluidas": 2}, [_grupo("a", "video", None, 30, 1), _grupo("b", "video", "X", 80, 1)], 20, 8,
    )
    assert [x["tipo"] for x in r] == ["ventas_excluidas", "grupos_sin_empresa", "ventas_sin_origen"]
    assert sen.reglas_datos_incompletos({"ventas_excluidas": 0}, GRUPOS_OCTUBRE, 20, 4) == []  # 20 % no pasa de 25 %


def _evaluar(**sobre):
    base = dict(
        flujo={"leads": 479, "oportunidades": 487, "ventas": 20}, valor_vendido={"ventas_excluidas": 0},
        embudo={"excluye_consulta_atc": True}, distribucion=[], grupos=GRUPOS_OCTUBRE, ventas_total=20,
        ventas_sin_origen=4, casos_sin_asesor={"oportunidades": 122, "ventas": 0}, anterior=None,
    )
    base.update(sobre)
    return sen.evaluar_senales(**base)


def test_con_los_datos_de_octubre_se_ven_exactamente_dos_senales_en_orden_de_prioridad():
    senales = _evaluar()
    assert [s["tipo"] for s in senales] == ["casos_sin_asesor", "formato_rinde_distinto"]


def test_nunca_mas_de_tres_y_los_datos_incompletos_van_primero():
    senales = _evaluar(
        valor_vendido={"ventas_excluidas": 1}, ventas_sin_origen=10,
        anterior={"flujo": {"leads": 200, "ventas": 5}, "distribucion": []},
    )
    assert len(senales) == sen.MAX_SENALES
    assert [s["prioridad"] for s in senales] == sorted(s["prioridad"] for s in senales)
    assert senales[0]["tipo"] == "ventas_excluidas"


def test_sin_comparativas_no_hay_r1_r2_r3():
    assert [s["tipo"] for s in _evaluar(comparativas=False)] == ["casos_sin_asesor"]


def test_sin_casos_aparece_la_senal_de_siempre():
    s = _evaluar(flujo={"leads": 0, "oportunidades": 0, "ventas": 0}, grupos=None, casos_sin_asesor=None, ventas_total=0, ventas_sin_origen=None)
    assert s[0]["tipo"] == "sin_oportunidades" and s[0]["texto"] == "No se registraron oportunidades en este período."


# ── Endpoint ──────────────────────────────────────────────────────────────────

async def _negocio_con_casos(codigo: str, sin_asesor: int, con_asesor: int):
    negocio = await mem.crear_negocio(f"Negocio {codigo}", codigo)
    canal = await mem.crear_canal_whatsapp(
        nombre=f"Canal {codigo}", phone_number_id=f"4096000{codigo[-2:]}", negocio_id=negocio["id"],
    )
    await mem.crear_usuario("ana", "pw12345", "Ana", "asesor", negocio["id"])
    for i in range(sin_asesor + con_asesor):
        tel = f"519{codigo[-2:]}0{i:05d}"
        await mem.actualizar_lead(tel, negocio_id=negocio["id"], numero_whatsapp_id="x")
        await mem.resolver_conversation_activa(tel, negocio["id"], canal["id"])
        if i >= sin_asesor:
            await mem.asignar_asesor_a_lead(tel, "ana")
    return negocio


def _hoy_lima() -> str:
    return (datetime.utcnow() - timedelta(hours=5)).strftime("%Y-%m-%d")


async def test_el_endpoint_trae_la_senal_completa_y_respeta_sin_senales_y_el_rol():
    negocio = await _negocio_con_casos("sen-01", sin_asesor=22, con_asesor=3)
    hoy = _hoy_lima()
    admin = {"negocio_id": negocio["id"], "rol": "admin", "username": "jesus"}
    completo = json.loads((await dashboard.analitica_json(usuario=admin, desde=hoy, hasta=hoy)).body)
    [senal] = [s for s in completo["senales"] if s["tipo"] == "casos_sin_asesor"]
    assert senal["texto"] == "22 casos (88%) no tienen asesor asignado"
    assert {"que_vi", "por_que_ahora", "que_hacer", "confianza", "prioridad"} <= set(senal)

    sin = json.loads((await dashboard.analitica_json(usuario=admin, desde=hoy, hasta=hoy, sin_senales=True)).body)
    assert sin["senales"] == []
    # lo demás de la respuesta no cambia
    assert sin["flujo_periodo"] == completo["flujo_periodo"]

    asesor = {"negocio_id": negocio["id"], "rol": "asesor", "username": "ana"}
    suyo = json.loads((await dashboard.analitica_json(usuario=asesor, desde=hoy, hasta=hoy)).body)
    assert all(s["tipo"] != "casos_sin_asesor" for s in suyo["senales"])
