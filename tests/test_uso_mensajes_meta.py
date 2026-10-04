# tests/test_uso_mensajes_meta.py — 2026-10-04, paso 1 de la adaptación al cobro
# por mensaje de Meta (desde 2026-10-01): leer los estados de entrega
# (sent/delivered/read/failed) con su `pricing` y llevar el uso del mes por
# número. Hasta ahora esos estados se ignoraban por completo.
#
# Regla de diseño que estos tests protegen: el sistema NO decide qué es gratis
# ni qué se cobra — transcribe el `pricing.type` que Meta informa en cada
# mensaje (regular | free_customer_service | free_entry_point), porque esas
# reglas cambian por fecha, país y categoría.

import os
from datetime import datetime, timezone

os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")
os.environ.setdefault("WHATSAPP_PROVIDER", "meta")

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from starlette.requests import Request

from agent import dashboard
from agent import main as app_main
from agent import memory as mem
from agent.providers.meta import ProveedorMeta


def _epoch(*args) -> str:
    return str(int(datetime(*args, tzinfo=timezone.utc).timestamp()))


def _payload(estados: list[dict], phone_number_id: str = "100200300") -> dict:
    return {
        "object": "whatsapp_business_account",
        "entry": [{"id": "waba-1", "changes": [{"field": "messages", "value": {
            "messaging_product": "whatsapp",
            "metadata": {"display_phone_number": "51999000000", "phone_number_id": phone_number_id},
            "statuses": estados,
        }}]}],
    }


GRATIS_SERVICIO = {"billable": False, "pricing_model": "PMP", "type": "free_customer_service", "category": "service"}
COBRABLE_SERVICIO = {"billable": True, "pricing_model": "PMP", "type": "regular", "category": "service"}
VENTANA_ANUNCIO = {"billable": False, "pricing_model": "PMP", "type": "free_entry_point", "category": "service"}
COBRABLE_UTILIDAD = {"billable": True, "pricing_model": "PMP", "type": "regular", "category": "utility"}


async def _negocio(codigo: str):
    return await mem.crear_negocio(f"Negocio {codigo}", codigo)


async def _entregado(negocio_id: str, wamid: str, pricing: dict | None, momento: datetime, phone: str = "100200300"):
    assert await mem.registrar_estado_mensaje_meta({
        "wamid": wamid, "estado": "delivered", "momento": momento, "phone_number_id": phone,
        "destinatario": "51999000111", "pricing": pricing, "negocio_id": negocio_id,
    })


# ── Parseo del payload ───────────────────────────────────────────────────

def test_parsear_estados_transcribe_el_pricing_y_solo_codigo_y_titulo_del_error():
    cuerpo = _payload([
        {"id": "wamid.A", "status": "sent", "timestamp": _epoch(2026, 10, 5, 12), "recipient_id": "51999000111", "pricing": GRATIS_SERVICIO},
        {"id": "wamid.A", "status": "delivered", "timestamp": _epoch(2026, 10, 5, 12, 0, 3), "recipient_id": "51999000111", "pricing": GRATIS_SERVICIO},
        {"id": "wamid.A", "status": "read", "timestamp": _epoch(2026, 10, 5, 12, 5), "recipient_id": "51999000111"},
        {"id": "wamid.B", "status": "failed", "timestamp": _epoch(2026, 10, 5, 13), "recipient_id": "51999000222",
         "errors": [{"code": 131047, "title": "Re-engagement message", "message": "texto largo del error", "error_data": {"details": "secreto"}}]},
        {"id": "wamid.C", "status": "deleted", "timestamp": _epoch(2026, 10, 5, 14)},   # estado desconocido: se omite
        {"status": "sent", "timestamp": _epoch(2026, 10, 5, 14)},                          # sin id: se omite
    ])

    eventos = ProveedorMeta.parsear_estados(cuerpo)

    assert [(e["wamid"], e["estado"]) for e in eventos] == [
        ("wamid.A", "sent"), ("wamid.A", "delivered"), ("wamid.A", "read"), ("wamid.B", "failed"),
    ]
    assert eventos[0]["pricing"] == GRATIS_SERVICIO and eventos[2]["pricing"] is None
    assert eventos[0]["phone_number_id"] == "100200300" and eventos[0]["destinatario"] == "51999000111"
    assert eventos[0]["momento"] == datetime(2026, 10, 5, 12, 0, 0)
    assert eventos[3]["error"] == {"codigo": 131047, "titulo": "Re-engagement message"}  # sin message ni error_data


def test_un_payload_de_mensajes_sin_estados_no_produce_eventos():
    cuerpo = {"entry": [{"changes": [{"value": {"metadata": {"phone_number_id": "1"}, "messages": [{"id": "x"}]}}]}]}
    assert ProveedorMeta.parsear_estados(cuerpo) == []
    assert ProveedorMeta.parsear_estados({}) == []


# ── Registro idempotente ─────────────────────────────────────────────────

async def test_registro_idempotente_el_estado_no_retrocede_y_conserva_el_pricing():
    negocio = await _negocio("uso-1")
    base = {"wamid": "wamid.uso1", "phone_number_id": "100200301", "negocio_id": negocio["id"], "destinatario": "51999000111"}
    # Orden real de Meta, con repeticiones y fuera de orden.
    await mem.registrar_estado_mensaje_meta({**base, "estado": "read", "momento": datetime(2026, 10, 5, 12, 5)})
    await mem.registrar_estado_mensaje_meta({**base, "estado": "sent", "momento": datetime(2026, 10, 5, 12, 0), "pricing": GRATIS_SERVICIO})
    await mem.registrar_estado_mensaje_meta({**base, "estado": "delivered", "momento": datetime(2026, 10, 5, 12, 1), "pricing": GRATIS_SERVICIO})
    await mem.registrar_estado_mensaje_meta({**base, "estado": "delivered", "momento": datetime(2026, 10, 5, 12, 9), "pricing": GRATIS_SERVICIO})  # reenvío
    await mem.registrar_estado_mensaje_meta({**base, "estado": "sent", "momento": datetime(2026, 10, 5, 12, 0)})                                        # reenvío

    async with mem.async_session() as session:
        filas = (await session.execute(select(mem.UsoMensajeMeta).where(mem.UsoMensajeMeta.wamid == "wamid.uso1"))).scalars().all()
    assert len(filas) == 1
    f = filas[0]
    assert f.estado == "read"
    assert f.enviado_en == datetime(2026, 10, 5, 12, 0) and f.entregado_en == datetime(2026, 10, 5, 12, 1)  # conserva el PRIMER momento
    assert (f.pricing_type, f.pricing_categoria, f.pricing_model, f.pricing_billable) == ("free_customer_service", "service", "PMP", False)
    assert f.negocio_id == negocio["id"] and f.destinatario == "51999000111"


async def test_un_fallo_no_pisa_un_mensaje_entregado_pero_si_marca_uno_que_nunca_llego():
    negocio = await _negocio("uso-2")
    base = {"phone_number_id": "100200302", "negocio_id": negocio["id"]}
    await mem.registrar_estado_mensaje_meta({**base, "wamid": "wamid.ok", "estado": "delivered", "momento": datetime(2026, 10, 5, 12)})
    await mem.registrar_estado_mensaje_meta({**base, "wamid": "wamid.ok", "estado": "failed", "momento": datetime(2026, 10, 5, 12, 1)})
    await mem.registrar_estado_mensaje_meta({**base, "wamid": "wamid.mal", "estado": "sent", "momento": datetime(2026, 10, 5, 12)})
    await mem.registrar_estado_mensaje_meta({
        **base, "wamid": "wamid.mal", "estado": "failed", "momento": datetime(2026, 10, 5, 12, 1),
        "error": {"codigo": 131047, "titulo": "Re-engagement message"},
    })

    async with mem.async_session() as session:
        ok = await session.get(mem.UsoMensajeMeta, "wamid.ok")
        mal = await session.get(mem.UsoMensajeMeta, "wamid.mal")
    assert ok.estado == "delivered"
    assert mal.estado == "failed" and (mal.error_codigo, mal.error_titulo) == (131047, "Re-engagement message")


async def test_un_evento_invalido_no_se_registra():
    assert await mem.registrar_estado_mensaje_meta({"wamid": "", "estado": "sent", "phone_number_id": "1"}) is False
    assert await mem.registrar_estado_mensaje_meta({"wamid": "x", "estado": "raro", "phone_number_id": "1"}) is False
    assert await mem.registrar_estado_mensaje_meta({"wamid": "x", "estado": "sent", "phone_number_id": ""}) is False


# ── Resumen mensual: cuota, cobrables, ventana de anuncios, alertas, costo ─

async def _sembrar_octubre(negocio_id: str):
    n = 0

    async def poner(pricing, dia=5, estado="delivered", phone="100200303"):
        nonlocal n
        n += 1
        if estado == "delivered":
            await _entregado(negocio_id, f"wamid.res.{n}", pricing, datetime(2026, 10, dia, 12), phone)
        else:
            await mem.registrar_estado_mensaje_meta({
                "wamid": f"wamid.res.{n}", "estado": estado, "momento": datetime(2026, 10, dia, 12),
                "phone_number_id": phone, "negocio_id": negocio_id,
            })

    for _ in range(3):
        await poner(GRATIS_SERVICIO)
    for _ in range(2):
        await poner(COBRABLE_SERVICIO)
    for _ in range(4):
        await poner(VENTANA_ANUNCIO)
    await poner(COBRABLE_UTILIDAD)
    await poner(None)                                   # entregado sin pricing
    await poner(None, estado="failed")                   # fallido: no cuenta
    await poner(GRATIS_SERVICIO, dia=1, phone="100200304")  # otro número
    await _entregado(negocio_id, "wamid.res.sept", GRATIS_SERVICIO, datetime(2026, 9, 30, 12))  # otro mes


async def test_resumen_separa_cuota_cobrables_ventana_de_anuncios_y_sin_clasificar():
    negocio = await _negocio("uso-3")
    await mem.guardar_configuracion("meta_cuota_gratis_servicio", "5", negocio_id=negocio["id"])
    await _sembrar_octubre(negocio["id"])
    # Otro negocio con filas propias: no debe mezclarse.
    otro = await _negocio("uso-3b")
    await _entregado(otro["id"], "wamid.otro", GRATIS_SERVICIO, datetime(2026, 10, 5, 12), "999")

    r = await mem.resumen_uso_mensual(negocio["id"], "2026-10")

    assert (r["mes"], r["cuota_gratis_servicio"], r["zona_horaria"]) == ("2026-10", 5, "UTC")
    a, b = r["numeros"]
    assert (a["phone_number_id"], b["phone_number_id"]) == ("100200303", "100200304")
    assert a["servicio_gratis_usados"] == 3 and a["gratis_restantes"] == 2 and a["porcentaje_cuota"] == 60.0
    assert a["servicio_cobrables"] == 2
    assert a["ventana_anuncio_gratis"] == 4
    assert a["otros_cobrables"] == {"utility": 1}
    assert a["sin_clasificar"] == 1
    assert a["entregados"] == 3 + 2 + 4 + 1 + 1  # el fallido y el de septiembre no cuentan
    assert b["servicio_gratis_usados"] == 1 and b["entregados"] == 1
    assert a["alertas"] == [100]  # ya hay cobrables de servicio: la cuota se agotó aunque el % sea 60


async def test_alertas_80_95_y_100_por_porcentaje_de_la_cuota():
    negocio = await _negocio("uso-4")
    await mem.guardar_configuracion("meta_cuota_gratis_servicio", "20", negocio_id=negocio["id"])
    for i in range(16):
        await _entregado(negocio["id"], f"wamid.al.{i}", GRATIS_SERVICIO, datetime(2026, 10, 5, 12))
    assert (await mem.resumen_uso_mensual(negocio["id"], "2026-10"))["numeros"][0]["alertas"] == [80]
    await _entregado(negocio["id"], "wamid.al.17", GRATIS_SERVICIO, datetime(2026, 10, 5, 12))
    await _entregado(negocio["id"], "wamid.al.18", GRATIS_SERVICIO, datetime(2026, 10, 5, 12))
    await _entregado(negocio["id"], "wamid.al.19", GRATIS_SERVICIO, datetime(2026, 10, 5, 12))
    assert (await mem.resumen_uso_mensual(negocio["id"], "2026-10"))["numeros"][0]["alertas"] == [80, 95]
    await _entregado(negocio["id"], "wamid.al.20", GRATIS_SERVICIO, datetime(2026, 10, 5, 12))
    assert (await mem.resumen_uso_mensual(negocio["id"], "2026-10"))["numeros"][0]["alertas"] == [80, 95, 100]


async def test_el_costo_solo_se_calcula_con_tarifas_configuradas_nunca_con_valores_fijos():
    negocio = await _negocio("uso-5")
    await _sembrar_octubre(negocio["id"])

    sin_tarifas = await mem.resumen_uso_mensual(negocio["id"], "2026-10")
    assert sin_tarifas["tarifas_faltantes"] == ["service", "utility"]
    assert sin_tarifas["numeros"][0]["costo_estimado_usd"] is None

    await mem.guardar_configuracion("meta_tarifa_usd_service", "0.03", negocio_id=negocio["id"])
    await mem.guardar_configuracion("meta_tarifa_usd_utility", "0.02", negocio_id=negocio["id"])
    con_tarifas = await mem.resumen_uso_mensual(negocio["id"], "2026-10")
    assert con_tarifas["tarifas_faltantes"] == []
    assert con_tarifas["numeros"][0]["costo_estimado_usd"] == pytest.approx(2 * 0.03 + 1 * 0.02)
    assert con_tarifas["tarifas_usd"] == {"service": 0.03, "utility": 0.02}


async def test_el_mes_se_mide_en_la_zona_configurada():
    try:
        from zoneinfo import ZoneInfo
        ZoneInfo("America/Lima")
    except Exception:
        pytest.skip("este sistema no tiene la base de zonas horarias")
    negocio = await _negocio("uso-6")
    # 2026-11-01 02:00 UTC = 2026-10-31 21:00 en Lima.
    await _entregado(negocio["id"], "wamid.zona", GRATIS_SERVICIO, datetime(2026, 11, 1, 2))

    en_utc = await mem.resumen_uso_mensual(negocio["id"], "2026-10")
    assert en_utc["numeros"] == []
    await mem.guardar_configuracion("meta_zona_horaria_mes", "America/Lima", negocio_id=negocio["id"])
    en_lima = await mem.resumen_uso_mensual(negocio["id"], "2026-10")
    assert en_lima["numeros"][0]["servicio_gratis_usados"] == 1


async def test_un_mes_sin_actividad_devuelve_la_estructura_vacia():
    negocio = await _negocio("uso-7")
    r = await mem.resumen_uso_mensual(negocio["id"], "2026-10")
    assert r["numeros"] == [] and r["cuota_gratis_servicio"] == 1000


# ── Webhook: los estados se registran sin afectar nada más ───────────────

def _request(cuerpo: dict) -> Request:
    import json
    datos = json.dumps(cuerpo).encode()
    entregado = False

    async def recibir():
        nonlocal entregado
        if entregado:
            return {"type": "http.disconnect"}
        entregado = True
        return {"type": "http.request", "body": datos, "more_body": False}

    return Request({"type": "http", "method": "POST", "path": "/webhook", "headers": [],
                    "query_string": b"", "client": ("203.0.113.9", 1234)}, recibir)


class _ProveedorSoloEstados:
    def __init__(self, canal):
        self._canal = canal

    parsear_estados = staticmethod(ProveedorMeta.parsear_estados)

    async def verificar_firma(self, request, cuerpo):
        return True

    async def parsear_webhook(self, request):
        return []

    async def resolver_canal(self, numero_whatsapp_id, negocio_id=None):
        return self._canal


async def test_el_webhook_registra_estados_y_resuelve_el_negocio_por_el_numero(monkeypatch):
    negocio = await _negocio("uso-8")
    canal = await mem.crear_canal_whatsapp(nombre="Canal uso-8", phone_number_id="100200308", negocio_id=negocio["id"])
    monkeypatch.setattr(app_main, "proveedor", _ProveedorSoloEstados({"id": canal["id"], "negocio_id": negocio["id"], "phone_number_id": "100200308"}))
    cuerpo = _payload([
        {"id": "wamid.wh1", "status": "sent", "timestamp": _epoch(2026, 10, 5, 12), "recipient_id": "51999000111", "pricing": GRATIS_SERVICIO},
        {"id": "wamid.wh1", "status": "delivered", "timestamp": _epoch(2026, 10, 5, 12, 0, 2), "recipient_id": "51999000111", "pricing": GRATIS_SERVICIO},
    ], phone_number_id="100200308")

    respuesta = await app_main.webhook_handler(_request(cuerpo))
    await app_main.webhook_handler(_request(cuerpo))  # Meta reenvía: no duplica

    assert respuesta == {"status": "ok"}
    async with mem.async_session() as session:
        filas = (await session.execute(select(mem.UsoMensajeMeta).where(mem.UsoMensajeMeta.wamid == "wamid.wh1"))).scalars().all()
    assert len(filas) == 1 and filas[0].estado == "delivered" and filas[0].negocio_id == negocio["id"]
    assert filas[0].phone_number_id == "100200308" and filas[0].pricing_type == "free_customer_service"


async def test_una_falla_al_registrar_un_estado_nunca_rompe_el_webhook(monkeypatch):
    negocio = await _negocio("uso-9")
    monkeypatch.setattr(app_main, "proveedor", _ProveedorSoloEstados({"id": 1, "negocio_id": negocio["id"]}))

    async def explota(evento):
        raise RuntimeError("base caída")
    monkeypatch.setattr(app_main, "registrar_estado_mensaje_meta", explota)
    cuerpo = _payload([{"id": "wamid.rota", "status": "sent", "timestamp": _epoch(2026, 10, 5, 12)}])

    assert await app_main.webhook_handler(_request(cuerpo)) == {"status": "ok"}  # 200: Meta no reintenta


async def test_un_proveedor_sin_estados_de_entrega_no_rompe_el_webhook(monkeypatch):
    class ProveedorViejo:
        async def verificar_firma(self, request, cuerpo):
            return True

        async def parsear_webhook(self, request):
            return []

    monkeypatch.setattr(app_main, "proveedor", ProveedorViejo())
    assert await app_main.webhook_handler(_request(_payload([]))) == {"status": "ok"}


# ── Ruta del panel y modelo ──────────────────────────────────────────────

async def test_la_ruta_del_panel_devuelve_el_resumen_y_valida_el_formato_del_mes():
    negocio = await _negocio("uso-10")
    await _entregado(negocio["id"], "wamid.ruta", GRATIS_SERVICIO, datetime(2026, 10, 5, 12))

    respuesta = await dashboard.uso_mensajes_json(mes="2026-10", usuario={"negocio_id": negocio["id"], "rol": "admin"})
    import json
    datos = json.loads(respuesta.body)
    assert datos["mes"] == "2026-10" and datos["numeros"][0]["servicio_gratis_usados"] == 1

    for mes_malo in ("2026-13", "octubre", "2026-1", "'; DROP TABLE x;--"):
        with pytest.raises(HTTPException) as e:
            await dashboard.uso_mensajes_json(mes=mes_malo, usuario={"negocio_id": negocio["id"], "rol": "admin"})
        assert e.value.status_code == 400


def test_mensajes_tiene_indice_por_mensaje_id_meta_para_cruzar_con_el_uso():
    assert mem.Mensaje.__table__.c.mensaje_id_meta.index is True
