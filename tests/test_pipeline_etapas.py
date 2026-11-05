# tests/test_pipeline_etapas.py — La etapa derivada del Pipeline (2026-11-05).
#
# Los 13 resultados no son etapas: la etapa se calcula con resultado + asesora asignada + derivación. La regla vive dos veces
# (`etapa_de` para mostrarla y `condicion_etapa` para filtrar y contar en SQL) y estas pruebas la amarran: la etapa que se ve en una
# fila es la misma por la que se filtra y se cuenta.
import json
import os

os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")

import pytest

from agent import dashboard, memory as mem, pipeline_etapas as pe


@pytest.mark.parametrize("resultado,asesor,paso,esperada", [
    (None, None, None, "gabi"),
    (None, None, "calificando", "gabi"),
    (None, "", None, "gabi"),
    ("producto_sin_stock", None, None, "gabi"),
    (None, "carla", None, "asesora"),
    (None, None, "derivado_asesor", "asesora"),
    ("sin_saldo", "carla", None, "asesora"),
    ("agendado", "carla", "derivado_asesor", "agendado"),
    ("agendado", None, None, "agendado"),
    ("vendido", "carla", None, "vendido"),
    ("postventa", None, None, "vendido"),
    ("no_interesado", "sabarca", None, "cerrado"),
    ("sin_respuesta", None, None, "cerrado"),
    ("consulta_atc", None, None, "cerrado"),
    ("solicita_suministro_gas", None, None, "cerrado"),
])
def test_etapa_de_cada_caso(resultado, asesor, paso, esperada):
    assert pe.etapa_de(resultado, asesor, paso) == esperada


def test_los_resultados_cerrados_y_vendido_se_reparten_sin_perder_ninguno():
    assert set(pe.RESULTADOS_CERRADO) | {"vendido"} == set(mem.RESULTADOS_CERRADOS)
    assert not set(pe.RESULTADOS_CERRADO) & set(pe.RESULTADOS_VENDIDO)


def test_un_nombre_que_no_es_etapa_no_filtra():
    assert pe.condicion_etapa("cualquiera") is None
    assert pe.condicion_etapa("") is None


CASOS = [
    # telefono, resultado, asesor, paso_flujo → etapa esperada
    ("51910000001", None, None, None, "gabi"),
    ("51910000002", None, None, "calificando", "gabi"),
    ("51910000003", None, "carla", None, "asesora"),
    ("51910000004", None, None, "derivado_asesor", "asesora"),
    ("51910000005", "agendado", "carla", None, "agendado"),
    ("51910000006", "vendido", "carla", None, "vendido"),
    ("51910000007", "postventa", None, None, "vendido"),
    ("51910000008", "no_interesado", "sabarca", None, "cerrado"),
    ("51910000009", "sin_respuesta", None, None, "cerrado"),
]


async def _negocio_con_casos(codigo: str, canal_tel: str):
    negocio = await mem.crear_negocio(f"Negocio {codigo}", codigo)
    await mem.crear_canal_whatsapp(nombre=f"Canal {codigo}", phone_number_id=canal_tel, negocio_id=negocio["id"])
    for telefono, resultado, asesor, paso, _ in CASOS:
        campos = {k: v for k, v in {"resultado": resultado, "asesor_asignado": asesor, "paso_flujo": paso}.items() if v}
        await mem.actualizar_lead(telefono, negocio_id=negocio["id"], nombre=f"Cliente {telefono[-2:]}", **campos)
    return negocio


async def test_filtrar_por_etapa_trae_justo_los_casos_de_esa_etapa():
    negocio = await _negocio_con_casos("etp1", "20000000501")
    for etapa in pe.ETAPAS:
        condicion = pe.condicion_etapa(etapa)
        leads, total = await mem.listar_leads_pipeline(negocio_id=negocio["id"], condiciones=(condicion,))
        esperados = {c[0] for c in CASOS if c[4] == etapa}
        assert {l["telefono"] for l in leads} == esperados and total == len(esperados), etapa


async def test_la_etapa_de_cada_fila_coincide_con_la_etapa_por_la_que_se_filtra():
    negocio = await _negocio_con_casos("etp2", "20000000502")
    leads, _ = await mem.listar_leads_pipeline(negocio_id=negocio["id"])
    por_telefono = {c[0]: c[4] for c in CASOS}
    assert len(leads) == len(CASOS)
    for lead in leads:
        assert dashboard._dto_lead_pipeline(lead)["etapa"] == por_telefono[lead["telefono"]]


async def test_contar_por_etapa_suma_todos_los_casos_y_respeta_la_cartera():
    negocio = await _negocio_con_casos("etp3", "20000000503")
    conteos = await pe.contar_por_etapa(negocio["id"])
    assert conteos == {"gabi": 2, "asesora": 2, "agendado": 1, "vendido": 2, "cerrado": 2}
    assert sum(conteos.values()) == len(CASOS)
    # La cartera de una persona: solo lo que tiene asignado.
    assert (await pe.contar_por_etapa(negocio["id"], "carla"))["asesora"] == 1
    assert await pe.contar_asignados_a(negocio["id"], "carla") == 3


async def test_las_etapas_no_cruzan_negocios():
    a = await _negocio_con_casos("etp4a", "20000000504")
    b = await mem.crear_negocio("Negocio etp4b", "etp4b")
    assert sum((await pe.contar_por_etapa(b["id"])).values()) == 0
    assert sum((await pe.contar_por_etapa(a["id"])).values()) == len(CASOS)


async def test_una_lista_de_telefonos_vacia_no_trae_casos_y_una_con_telefonos_acota():
    negocio = await _negocio_con_casos("etp5", "20000000505")
    assert await mem.listar_leads_pipeline(negocio_id=negocio["id"], telefonos=[]) == ([], 0)
    leads, total = await mem.listar_leads_pipeline(negocio_id=negocio["id"], telefonos=["51910000003", "51910000006"])
    assert total == 2 and {l["telefono"] for l in leads} == {"51910000003", "51910000006"}


async def test_el_endpoint_de_conteos_responde_con_etapas_y_vistas(monkeypatch):
    negocio = await _negocio_con_casos("etp6", "20000000506")

    async def _sin_tareas(negocio_id, usuario, **kwargs):
        return {"tareas": [{"telefono": "51910000003"}, {"telefono": "51910000003"}]}

    async def _esperando(negocio_id, **kwargs):
        return [{"telefono": "51910000004"}]

    monkeypatch.setattr(dashboard.llamadas, "listar_tareas", _sin_tareas)
    monkeypatch.setattr(dashboard, "listar_leads_esperando_asesor", _esperando)

    admin = {"negocio_id": negocio["id"], "rol": "admin", "username": "carla"}
    respuesta = await dashboard.crm_pipeline_conteos(request=None, usuario=admin, alcance="todos", asesor="")
    cuerpo = json.loads(respuesta.body)
    assert cuerpo["etapas"] == {"gabi": 2, "asesora": 2, "agendado": 1, "vendido": 2, "cerrado": 2}
    assert cuerpo["total"] == len(CASOS)
    assert cuerpo["vistas"] == {"mios": 3, "sin_asesor": 1, "para_llamar": 1, "citas": 1}
    assert cuerpo["alcance_aplicado"] == "todos"

    # Una Asesora cuenta solo su cartera y la vista «Sin asesor» no existe para ella.
    asesora = {"negocio_id": negocio["id"], "rol": "asesor", "username": "carla"}
    cuerpo = json.loads((await dashboard.crm_pipeline_conteos(request=None, usuario=asesora, alcance="todos", asesor="")).body)
    assert cuerpo["alcance_aplicado"] == "mi_pipeline"
    assert cuerpo["total"] == 3 and cuerpo["vistas"]["sin_asesor"] is None
