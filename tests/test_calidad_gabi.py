# tests/test_calidad_gabi.py — Mejoras de Gabi, Fase 1 (2026-10-07): métricas de calidad en MODO SOMBRA.
# agent/calidad_gabi.py es puro; agent/main.py deja una línea INFO `gabi_calidad {json}` por respuesta enviada,
# sin texto de mensajes ni teléfonos, y sin cambiar lo que recibe el cliente.

import json
import logging
import os

os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")
os.environ.setdefault("WHATSAPP_PROVIDER", "meta")

import pytest

from agent import calidad_gabi as q
from agent import formato_whatsapp
from agent import main as app_main
from agent import memory as mem


# ── Validador ────────────────────────────────────────────────────────────────

def test_pregunta_en_los_ultimos_120_caracteres():
    assert q.termina_en_pregunta_o_cta("Tenemos termas desde S/ 389. ¿Qué capacidad necesitas?")
    assert not q.termina_en_pregunta_o_cta("Tenemos termas desde S/ 389.")


def test_una_pregunta_lejos_del_final_no_cuenta():
    texto = "¿Quieres una terma?" + " Detalle de la oferta." * 12
    assert not q.termina_en_pregunta_o_cta(texto)


@pytest.mark.parametrize("cta", ["Cuéntame qué necesitas", "dime tu distrito", "Escríbeme tu DNI", "envíame una foto",
                                 "compárteme tu correo", "indícame el modelo", "avísame si te sirve", "déjame tu número",
                                 "mándame tu recibo", "cuentame mas", "escribeme"])
def test_llamado_verbal_cuenta_como_cta(cta):
    texto = "Perfecto, así avanzamos con tu solicitud. " + cta + "."
    assert q.termina_en_pregunta_o_cta(texto)
    assert not q.tiene_pregunta(texto)


def test_llamado_verbal_fuera_de_los_ultimos_200_no_cuenta():
    assert not q.termina_en_pregunta_o_cta("Cuéntame qué necesitas. " + "x" * 210)


def test_texto_vacio_o_none():
    assert not q.termina_en_pregunta_o_cta(None)
    assert not q.termina_en_pregunta_o_cta("")


def test_exentos_derivacion_y_cierre_del_cliente():
    assert q.es_exento("Te derivo con un asesor comercial 😊")
    assert q.es_exento("Un especialista te contactará")
    assert q.es_exento("Tu ejecutiva te escribirá")
    assert not q.es_exento("Tenemos termas desde S/ 389.")
    assert q.es_exento("¡De nada! Aquí estoy.", cliente_dijo_gracias=True)


def test_medir_calidad_devuelve_las_cinco_metricas():
    original = "**Hola Ana**, la terma cuesta **S/ 419**. ¿Qué uso le darás?"
    limpio = formato_whatsapp.formatear_para_whatsapp(original)
    m = q.medir_calidad(original, limpio)
    assert m == {"largo": len(limpio), "tiene_pregunta": True, "cumple_cta": True, "exento": False,
                 "tenia_doble_asterisco": True}


def test_medir_calidad_sin_doble_asterisco_ni_pregunta():
    m = q.medir_calidad("Listo, quedó registrado.", "Listo, quedó registrado.")
    assert m["tenia_doble_asterisco"] is False and m["cumple_cta"] is False and m["tiene_pregunta"] is False


def test_medir_calidad_con_agradecimiento_es_exento():
    assert q.medir_calidad("De nada.", "De nada.", cliente_dijo_gracias=True)["exento"] is True


# ── Log gabi_calidad en main (modo sombra) ───────────────────────────────────

class _ProveedorFalso:
    def __init__(self, enviado=True):
        self.enviados, self.enviado = [], enviado

    async def enviar_mensaje(self, telefono, mensaje, canal=None, mensaje_id_citado=None):
        self.enviados.append(mensaje)
        return self.enviado, ("wamid.OK" if self.enviado else None)


async def _armar(monkeypatch, codigo, telefono, respuesta, mensaje_cliente="hola, quiero una terma", enviado=True,
                 original=None):
    negocio = await mem.crear_negocio(f"Negocio {codigo}", codigo)
    canal_db = await mem.crear_canal_whatsapp(
        nombre=f"Canal {codigo}", phone_number_id=f"5098{codigo[-6:]}", negocio_id=negocio["id"],
    )
    canal = {"id": canal_db["id"], "negocio_id": negocio["id"], "unidad_id": None,
             "phone_number_id": canal_db["phone_number_id"], "modo": "produccion"}
    await mem.actualizar_lead(telefono, negocio_id=negocio["id"], numero_whatsapp_id="x")
    await mem.resolver_conversation_activa(telefono, negocio["id"], canal_db["id"])
    await mem.guardar_mensaje(telefono, "user", mensaje_cliente, negocio_id=negocio["id"])
    proveedor = _ProveedorFalso(enviado)
    monkeypatch.setattr(app_main, "proveedor", proveedor)

    async def gabi(mensaje, historial, lead, modo="produccion", negocio_id=None):
        if original is not None:
            formato_whatsapp.ORIGINAL_ANTES_DE_LIMPIAR.set(original)
        return respuesta, False, None, None

    async def datos(*a, **k):
        return {}

    monkeypatch.setattr(app_main.servicio_inteligencia, "generar_respuesta", gabi)
    monkeypatch.setattr(app_main.servicio_inteligencia, "extraer_datos_lead", datos)
    return canal, proveedor


def _lineas_calidad(caplog):
    return [r.getMessage() for r in caplog.records if r.getMessage().startswith("gabi_calidad ")]


async def test_se_registra_una_linea_gabi_calidad_sin_pii(monkeypatch, caplog):
    telefono = "51940000001"
    respuesta = "Tenemos termas desde S/ 389 con instalación incluida. ¿Qué capacidad necesitas?"
    canal, proveedor = await _armar(
        monkeypatch, "cal-001", telefono, respuesta,
        original="**Tenemos** termas desde S/ 389 con instalación incluida. ¿Qué capacidad necesitas?",
    )
    with caplog.at_level(logging.INFO, logger="agentkit"):
        await app_main._generar_y_enviar_respuesta_ia(telefono, canal)
    assert proveedor.enviados == [respuesta]    # el cliente recibe exactamente lo mismo (modo sombra)
    [linea] = _lineas_calidad(caplog)
    metricas = json.loads(linea.removeprefix("gabi_calidad "))
    assert metricas == {"largo": len(respuesta), "tiene_pregunta": True, "cumple_cta": True, "exento": False,
                        "tenia_doble_asterisco": True}
    assert telefono not in linea and "termas" not in linea and "capacidad" not in linea


async def test_respuesta_sin_pregunta_se_mide_pero_no_se_reintenta(monkeypatch, caplog):
    telefono = "51940000002"
    canal, proveedor = await _armar(monkeypatch, "cal-002", telefono, "Listo, quedó registrado.")
    with caplog.at_level(logging.INFO, logger="agentkit"):
        await app_main._generar_y_enviar_respuesta_ia(telefono, canal)
    assert proveedor.enviados == ["Listo, quedó registrado."]   # un solo envío, sin reintento
    [linea] = _lineas_calidad(caplog)
    metricas = json.loads(linea.removeprefix("gabi_calidad "))
    assert metricas["cumple_cta"] is False and metricas["exento"] is False and metricas["tenia_doble_asterisco"] is False


async def test_respuesta_a_un_gracias_es_exenta(monkeypatch, caplog):
    telefono = "51940000003"
    canal, proveedor = await _armar(monkeypatch, "cal-003", telefono, "¡De nada! Aquí estoy 😊", mensaje_cliente="gracias")
    with caplog.at_level(logging.INFO, logger="agentkit"):
        await app_main._generar_y_enviar_respuesta_ia(telefono, canal)
    [linea] = _lineas_calidad(caplog)
    assert json.loads(linea.removeprefix("gabi_calidad "))["exento"] is True


async def test_si_el_envio_no_sale_no_se_registra_calidad(monkeypatch, caplog):
    telefono = "51940000004"
    canal, proveedor = await _armar(monkeypatch, "cal-004", telefono, "Hola, ¿en qué te ayudo?", enviado=False)
    with caplog.at_level(logging.INFO, logger="agentkit"):
        await app_main._generar_y_enviar_respuesta_ia(telefono, canal)
    assert _lineas_calidad(caplog) == []


async def test_un_error_al_medir_nunca_rompe_el_envio(monkeypatch, caplog):
    telefono = "51940000005"
    canal, proveedor = await _armar(monkeypatch, "cal-005", telefono, "Hola, ¿en qué te ayudo?")

    def falla(*a, **k):
        raise RuntimeError("boom")

    monkeypatch.setattr(app_main.calidad_gabi, "medir_calidad", falla)
    with caplog.at_level(logging.INFO, logger="agentkit"):
        await app_main._generar_y_enviar_respuesta_ia(telefono, canal)
    assert proveedor.enviados == ["Hola, ¿en qué te ayudo?"]
    assert _lineas_calidad(caplog) == []
