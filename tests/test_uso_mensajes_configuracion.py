# tests/test_uso_mensajes_configuracion.py — 2026-10-04, paso 1 (continuación) de
# la adaptación al cobro por mensaje de Meta.
#
# Lo que el registro de estados no vio: los mensajes enviados del 1 al 4 de
# octubre, antes de que existiera. Se carga a mano como "uso previo estimado"
# por mes y número; consume la misma cuota de 1 000 gratis, se informa aparte
# de lo medido y entra en las alertas 80/95/100 %. Además, la configuración
# (cuota, zona horaria del mes, tarifas) se guarda por una ruta de Admin que
# valida todo y no guarda nada si algo es inválido.

import json
import os
from datetime import datetime

os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")
os.environ.setdefault("WHATSAPP_PROVIDER", "meta")

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from agent import dashboard
from agent import memory as mem

GRATIS_SERVICIO = {"billable": False, "pricing_model": "PMP", "type": "free_customer_service", "category": "service"}
NUMERO = "100200399"


async def _negocio(codigo: str):
    return await mem.crear_negocio(f"Negocio {codigo}", codigo)


async def _entregado(negocio_id: str, wamid: str, momento: datetime, phone: str = NUMERO):
    assert await mem.registrar_estado_mensaje_meta({
        "wamid": wamid, "estado": "delivered", "momento": momento, "phone_number_id": phone,
        "destinatario": "51999000111", "pricing": GRATIS_SERVICIO, "negocio_id": negocio_id,
    })


def _peticion(cuerpo) -> Request:
    datos = json.dumps(cuerpo).encode()
    entregado = False

    async def recibir():
        nonlocal entregado
        if entregado:
            return {"type": "http.disconnect"}
        entregado = True
        return {"type": "http.request", "body": datos, "more_body": False}

    return Request({"type": "http", "method": "POST", "path": "/dashboard/uso-mensajes/configuracion.json",
                    "headers": [], "query_string": b"", "client": ("203.0.113.9", 1234)}, recibir)


# ── Uso previo estimado ──────────────────────────────────────────────────

async def test_el_uso_previo_consume_la_cuota_y_se_informa_aparte_de_lo_medido():
    negocio = await _negocio("previo-1")
    await mem.guardar_configuracion_uso_meta(negocio["id"], {"uso_previo": {"mes": "2026-10", "phone_number_id": NUMERO, "valor": 544}})
    for i in range(6):
        await _entregado(negocio["id"], f"wamid.prev.{i}", datetime(2026, 10, 6, 12))

    n = (await mem.resumen_uso_mensual(negocio["id"], "2026-10"))["numeros"][0]

    assert n["servicio_gratis_usados"] == 6                  # lo medido por Meta, sin mezclar
    assert n["servicio_gratis_previos_estimados"] == 544     # lo estimado, aparte
    assert n["servicio_gratis_total"] == 550
    assert n["gratis_restantes"] == 450
    assert n["porcentaje_cuota"] == 55.0
    assert n["alertas"] == []


async def test_el_uso_previo_dispara_las_alertas_aunque_todavia_no_haya_estados_medidos():
    negocio = await _negocio("previo-2")
    await mem.guardar_configuracion_uso_meta(negocio["id"], {"uso_previo": {"mes": "2026-10", "phone_number_id": NUMERO, "valor": 850}})

    r = await mem.resumen_uso_mensual(negocio["id"], "2026-10")

    assert [d["phone_number_id"] for d in r["numeros"]] == [NUMERO]   # aparece sin una sola fila medida
    n = r["numeros"][0]
    assert n["entregados"] == 0 and n["servicio_gratis_total"] == 850 and n["alertas"] == [80]


async def test_el_uso_previo_es_por_mes_numero_y_negocio():
    a, b = await _negocio("previo-3a"), await _negocio("previo-3b")
    await mem.guardar_configuracion_uso_meta(a["id"], {"uso_previo": {"mes": "2026-10", "phone_number_id": NUMERO, "valor": 100}})

    assert (await mem.resumen_uso_mensual(a["id"], "2026-11"))["numeros"] == []       # otro mes
    assert (await mem.resumen_uso_mensual(b["id"], "2026-10"))["numeros"] == []       # otro negocio
    await _entregado(a["id"], "wamid.prev3", datetime(2026, 10, 6, 12), phone="555000111")
    numeros = {d["phone_number_id"]: d for d in (await mem.resumen_uso_mensual(a["id"], "2026-10"))["numeros"]}
    assert numeros[NUMERO]["servicio_gratis_previos_estimados"] == 100
    assert numeros["555000111"]["servicio_gratis_previos_estimados"] == 0             # otro número


async def test_sin_uso_previo_el_resumen_se_comporta_como_antes():
    negocio = await _negocio("previo-4")
    await _entregado(negocio["id"], "wamid.prev4", datetime(2026, 10, 6, 12))
    n = (await mem.resumen_uso_mensual(negocio["id"], "2026-10"))["numeros"][0]
    assert n["servicio_gratis_previos_estimados"] == 0 and n["servicio_gratis_total"] == 1 and n["gratis_restantes"] == 999


# ── Guardado de la configuración ─────────────────────────────────────────

async def test_guarda_cuota_zona_y_tarifas_y_el_resumen_las_usa():
    negocio = await _negocio("config-1")
    r = await mem.guardar_configuracion_uso_meta(negocio["id"], {
        "cuota_gratis_servicio": 1000, "zona_horaria_mes": "UTC", "tarifas_usd": {"service": 0.03, "marketing": 0.0703},
    })
    assert r["guardadas"] == ["meta_cuota_gratis_servicio", "meta_tarifa_usd_marketing", "meta_tarifa_usd_service", "meta_zona_horaria_mes"]
    assert await mem.obtener_configuracion("meta_tarifa_usd_service", "", negocio_id=negocio["id"]) == "0.03"


@pytest.mark.parametrize("datos", [
    {},                                                                                # nada que guardar
    {"cuota_gratis_servicio": -1}, {"cuota_gratis_servicio": "mil"}, {"cuota_gratis_servicio": True},
    {"cuota_gratis_servicio": 1.5},
    {"zona_horaria_mes": "Mordor/Mount_Doom"},
    {"tarifas_usd": [0.03]}, {"tarifas_usd": {"service": -0.1}}, {"tarifas_usd": {"service": "gratis"}},
    {"tarifas_usd": {"service": 99}}, {"tarifas_usd": {"Serv ice": 0.03}},
    {"uso_previo": {"mes": "2026-13", "phone_number_id": NUMERO, "valor": 5}},
    {"uso_previo": {"mes": "2026-10", "phone_number_id": "abc", "valor": 5}},
    {"uso_previo": {"mes": "2026-10", "phone_number_id": NUMERO, "valor": -5}},
    {"uso_previo": {"mes": "2026-10", "phone_number_id": NUMERO, "valor": 5.5}},
    {"uso_previo": "544"},
])
async def test_un_dato_invalido_se_rechaza(datos):
    negocio = await _negocio("config-2")
    with pytest.raises(ValueError):
        await mem.guardar_configuracion_uso_meta(negocio["id"], datos)


async def test_todo_o_nada_un_dato_invalido_no_deja_guardado_el_valido():
    negocio = await _negocio("config-3")
    with pytest.raises(ValueError):
        await mem.guardar_configuracion_uso_meta(negocio["id"], {"cuota_gratis_servicio": 500, "zona_horaria_mes": "No/Existe"})
    assert await mem.obtener_configuracion("meta_cuota_gratis_servicio", "sin-valor", negocio_id=negocio["id"]) == "sin-valor"


# ── Ruta del panel ───────────────────────────────────────────────────────

async def test_la_ruta_guarda_para_el_negocio_del_admin_y_traduce_los_errores_a_400():
    negocio = await _negocio("ruta-1")
    admin = {"negocio_id": negocio["id"], "rol": "admin", "username": "admin"}

    respuesta = await dashboard.uso_mensajes_configuracion_json(
        _peticion({"uso_previo": {"mes": "2026-10", "phone_number_id": NUMERO, "valor": 544}}), usuario=admin, _csrf=None)
    assert json.loads(respuesta.body)["ok"] is True
    assert (await mem.resumen_uso_mensual(negocio["id"], "2026-10"))["numeros"][0]["servicio_gratis_previos_estimados"] == 544

    for cuerpo in ({"cuota_gratis_servicio": -3}, ["no", "es", "objeto"], {}):
        with pytest.raises(HTTPException) as e:
            await dashboard.uso_mensajes_configuracion_json(_peticion(cuerpo), usuario=admin, _csrf=None)
        assert e.value.status_code == 400


def test_la_ruta_exige_rol_admin_y_csrf():
    ruta = next(r for r in dashboard.router.routes if getattr(r, "path", "").endswith("/uso-mensajes/configuracion.json") and "POST" in r.methods)
    assert ruta.methods == {"POST"}
    dependencias = {d.call.__name__ for d in ruta.dependant.dependencies}
    assert "verificar_csrf" in dependencias
