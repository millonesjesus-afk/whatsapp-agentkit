# tests/test_webhook_tiempos.py — 2026-09-24: guardar un mensaje entrante pasó a
# tardar 1.3-2.5 s en producción sin explicación en el código. Se agregaron dos
# mediciones para ver con datos reales dónde se va el tiempo: la línea de log
# `webhook_tiempos` (un tramo por paso del camino del mensaje) y la sonda
# `medir_latencia_db` al arrancar.

import logging
import os

os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")
os.environ.setdefault("WHATSAPP_PROVIDER", "meta")

from starlette.requests import Request

from agent import main as app_main
from agent import memory as mem
from agent.providers.base import MensajeEntrante


def _request() -> Request:
    cuerpo = b'{"object": "whatsapp_business_account"}'
    entregado = False

    async def recibir():
        nonlocal entregado
        if entregado:
            return {"type": "http.disconnect"}
        entregado = True
        return {"type": "http.request", "body": cuerpo, "more_body": False}

    return Request({"type": "http", "method": "POST", "path": "/webhook", "headers": [], "query_string": b"",
                    "client": ("203.0.113.9", 1234)}, recibir)


class _Proveedor:
    def __init__(self, canal, msg):
        self.canal, self.msg = canal, msg

    async def verificar_firma(self, request, cuerpo):
        return True

    async def parsear_webhook(self, request):
        return [self.msg]

    async def resolver_canal(self, numero_whatsapp_id, negocio_id=None):
        return self.canal

    async def marcar_leido_y_escribiendo(self, mensaje_id, canal=None):
        return True

    async def enviar_mensaje(self, telefono, mensaje, canal=None, mensaje_id_citado=None):
        return True, "wamid.OK"


def test_cronometro_reporta_total_y_cada_tramo():
    cron = app_main._Cronometro()
    cron.marca("canal")
    cron.marca("guardar")
    resumen = cron.resumen()
    assert resumen.startswith("total=") and "canal=" in resumen and "guardar=" in resumen
    assert set(cron.tramos) == {"canal", "guardar"}


async def test_medir_latencia_db_devuelve_min_prom_max():
    r = await mem.medir_latencia_db(muestras=3)
    assert set(r) == {"min_ms", "prom_ms", "max_ms"}
    assert 0 <= r["min_ms"] <= r["prom_ms"] <= r["max_ms"]


async def test_un_mensaje_a_lead_asignado_deja_la_linea_webhook_tiempos(monkeypatch, caplog):
    negocio = await mem.crear_negocio("Negocio Tiempos", "g-tie-01")
    canal_db = await mem.crear_canal_whatsapp(nombre="C", phone_number_id="40991001", negocio_id=negocio["id"])
    canal = {"id": canal_db["id"], "negocio_id": negocio["id"], "unidad_id": None,
             "phone_number_id": "40991001", "modo": "produccion"}
    telefono = "51941000001"
    await mem.actualizar_lead(telefono, negocio_id=negocio["id"], numero_whatsapp_id="x")
    await mem.resolver_conversation_activa(telefono, negocio["id"], canal_db["id"])
    await mem.asignar_asesor_a_lead(telefono, "asesor1")
    msg = MensajeEntrante(telefono=telefono, texto="hola", mensaje_id="wamid.tie1", es_propio=False,
                          tipo="text", numero_whatsapp_id="40991001")
    monkeypatch.setattr(app_main, "proveedor", _Proveedor(canal, msg))

    with caplog.at_level(logging.INFO, logger="agentkit"):
        await app_main.webhook_handler(_request())

    lineas = [r.getMessage() for r in caplog.records if r.getMessage().startswith("webhook_tiempos")]
    assert len(lineas) == 1
    for tramo in ("idempotencia", "canal", "lead_y_conversacion", "obtener_lead", "guardar_y_marcar", "emitir"):
        assert f"{tramo}=" in lineas[0]
