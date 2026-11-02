# tests/test_triaje_reclamos.py — Reclamos y cambio de titular van a la línea de atención al cliente (2026-10-31).
#
# Caso real (+51 970 712 280, 30-oct 22:35): «Deseo hacer un reclamo». El triaje no tenía esa categoría, Gabi le dio la línea de atención y
# después el aviso de respaldo le dijo «Te estoy derivando con un asesor comercial» (la extracción marcó `derivado_asesor`). Un reclamo no
# es una venta: se responde con la línea, se cierra como consulta ATC y no se deriva a nadie.
import os

os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")
os.environ.setdefault("WHATSAPP_PROVIDER", "meta")
os.environ["DEBOUNCE_RESPUESTA_SEGUNDOS"] = "0"

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from agent import brain, calificacion_guiada as cg, derivacion_automatica as da, memory as mem, triaje_atc as t
from tests.test_cierre_cortesia import _correr, _msg
from tests.test_triaje_atc_flujo import LINEA, _escenario, _hablar


def _decidir(*mensajes: str):
    return t.clasificar(list(mensajes), t.Contexto(evaluar_atc=True, categorias_activas=t.CATEGORIAS_FASE_1))


@pytest.mark.parametrize("mensajes", [
    ["Deseo hacer un reclamo"], ["Buenas noches", "Otro", "Deseo hacer un reclamo"], ["tengo una queja del servicio"],
    ["quiero reclamar"], ["quiero cambiar el titular del suministro"], ["quiero cambio de nombre del contrato"],
    ["necesito cambiar de titular"], ["cambio de titularidad"], ["pésimo servicio, nadie me ayuda"],
])
def test_un_reclamo_o_tramite_se_cierra_como_consulta_atc(mensajes):
    d = _decidir(*mensajes)
    assert d.categoria == "reclamo" and d.accion == t.ACCION_CERRAR and d.bloqueos == ()


@pytest.mark.parametrize("mensajes,bloqueo", [
    (["quiero una terma, tengo un reclamo"], "comercial_producto"),
    (["quiero reclamar el precio de la cocina"], "comercial_precio"),
    (["quiero cambiar el nombre de la cocina"], "comercial_producto"),
    (["quiero una terma y cambiar de titular"], "comercial_producto"),
])
def test_si_el_cliente_habla_de_comprar_no_se_cierra(mensajes, bloqueo):
    d = _decidir(*mensajes)
    assert d.accion == t.ACCION_NINGUNA and bloqueo in d.bloqueos


@pytest.mark.parametrize("mensajes", [["mi nombre es Ana"], ["cambio de turno"], ["hola, quiero información"], ["el titular de la oferta"]])
def test_lo_que_no_es_un_reclamo_no_se_toca(mensajes):
    d = _decidir(*mensajes)
    assert d.categoria != "reclamo"


def test_la_categoria_nueva_esta_en_las_listas_y_etiquetas():
    assert "reclamo" in t.CATEGORIAS_FASE_1 and "reclamo" in t.CATEGORIAS_ATC
    assert da.ETIQUETAS_CATEGORIA["reclamo"] == "Reclamo o trámite"
    assert mem._ETIQUETAS_CATEGORIA_TRIAJE["reclamo"] == "reclamo o trámite"
    assert "reclamos" in t.TEXTO_POR_DEFECTO


async def _tocar_producto_otro(proveedor, canal, telefono):
    await _correr(proveedor, [_msg(telefono, canal, "Otro", "wamid.rec-otro", interactivo_id="cal:producto:otro")])


async def test_el_caso_real_se_cierra_sin_ia_sin_derivar_y_con_la_linea(monkeypatch):
    telefono = "51970712280"
    negocio, canal, canal_dict, proveedor, gabi = await _escenario(
        monkeypatch, "activo", extra={cg.CLAVE_MODO: "activo"},
    )
    proveedor.interactivos = []

    async def enviar_interactivo(telefono, interactivo, canal=None):
        proveedor.interactivos.append(interactivo)
        return True, f"wamid.INT{len(proveedor.interactivos)}"
    proveedor.enviar_interactivo = enviar_interactivo

    async def no_notificar(*a, **k):
        raise AssertionError("un reclamo no se notifica ni se deriva a un asesor")
    from agent import main as app_main
    monkeypatch.setattr(app_main, "notificar_lead_derivado", no_notificar)

    await _hablar(proveedor, canal, telefono, "Buenas noches")
    assert proveedor.interactivos[-1]["type"] == "list"                 # la lista de producto
    await _tocar_producto_otro(proveedor, canal, telefono)
    await _hablar(proveedor, canal, telefono, "Deseo hacer un reclamo")

    assert gabi.llamadas == 0                                            # ni Gabi ni la IA de extracción
    assert LINEA in proveedor.enviados[-1] and "reclamos" in proveedor.enviados[-1]
    assert not any("derivando" in texto for texto in proveedor.enviados)
    lead = await mem.obtener_lead(telefono, negocio_id=negocio["id"])
    assert lead["resultado"] == "consulta_atc" and lead["cerrado_definitivamente_en"] is not None
    assert lead["paso_flujo"] != "derivado_asesor" and lead["asesor_asignado"] is None


async def test_un_cliente_con_ganas_de_comprar_y_un_reclamo_sigue_con_gabi(monkeypatch):
    telefono = "51970712281"
    negocio, canal, canal_dict, proveedor, gabi = await _escenario(monkeypatch, "activo")
    await _hablar(proveedor, canal, telefono, "Quiero una terma y tengo un reclamo")
    assert gabi.llamadas == 1
    lead = await mem.obtener_lead(telefono, negocio_id=negocio["id"])
    assert lead["cerrado_definitivamente_en"] is None


async def test_la_extraccion_de_datos_ya_no_deriva_un_reclamo():
    devuelto = {"nombre": None, "interes": "reclamo", "producto_tipo": None, "producto_marca": None,
                "producto_modalidad": None, "paso_flujo": "explorando"}
    uso = SimpleNamespace(input_tokens=10, output_tokens=10, cache_read_input_tokens=0, cache_creation_input_tokens=0)
    respuesta = SimpleNamespace(content=[SimpleNamespace(text=json.dumps(devuelto))], usage=uso)
    with patch.object(brain.client.messages, "create", new=AsyncMock(return_value=respuesta)) as mock_create:
        await brain.extraer_datos_lead("Deseo hacer un reclamo", "Llama al 614-9000 opción 5", None)
    enviado = mock_create.await_args.kwargs["messages"][0]["content"]
    assert "NO uses derivado_asesor cuando el cliente solo trae un reclamo" in enviado
    assert "línea de atención al cliente" in enviado
