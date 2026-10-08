# tests/test_triaje_atc_flujo.py — Triaje de temas NO comerciales → Consulta ATC (2026-10-08, diseño D2), de punta a
# punta por el webhook: apagado (camino de Gabi IDÉNTICO), sombra (solo log + evento interno), activo (envía el texto
# fijo, guarda el mensaje, cierra con `consulta_atc`), fallos seguros, reapertura, absorción de "gracias"/"ok",
# circuito de IA abierto, canal de pruebas y los cambios de memoria que lo sostienen (`cerrar_por_triaje`,
# reapertura que limpia el cierre del Lead, eventos internos fuera del Timeline).

import inspect
import json
import logging
import os
from datetime import datetime
from pathlib import Path

os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")
os.environ.setdefault("WHATSAPP_PROVIDER", "meta")
os.environ["DEBOUNCE_RESPUESTA_SEGUNDOS"] = "0"

import pytest
from sqlalchemy import select

from agent import envios
from agent import main as app_main
from agent import memory as mem
from agent import respaldo_sin_ia
from agent import triaje_atc as t
from agent.http_utils import EnvioIncierto
from tests.test_cierre_cortesia import (
    _caso_cerrado, _conversaciones, _correr, _mensajes, _msg, _preparar_webhook,
)

LINEA = "614900, opción 5"
_n = {"canal": 0, "wamid": 0}


async def _escenario(monkeypatch, modo: str | None, *, linea: str | None = LINEA, canal_modo: str = "produccion", extra: dict | None = None):
    """Un negocio SIN asesores, su canal y el proveedor/Gabi falsos. `modo`: valor de triaje_atc_modo (None = sin fijar)."""
    _n["canal"] += 1
    codigo = f"tr-{_n['canal']}"
    negocio = await mem.crear_negocio(f"Negocio {codigo}", codigo)
    canal = await mem.crear_canal_whatsapp(nombre=f"Canal {codigo}", phone_number_id=f"4097{_n['canal']:06d}", negocio_id=negocio["id"])
    if modo is not None:
        await mem.guardar_configuracion(t.CLAVE_MODO, modo, negocio_id=negocio["id"])
    if linea is not None:
        await mem.guardar_configuracion(t.CLAVE_LINEA, linea, negocio_id=negocio["id"])
    for clave, valor in (extra or {}).items():
        await mem.guardar_configuracion(clave, valor, negocio_id=negocio["id"])
    canal_dict = {
        "id": canal["id"], "negocio_id": negocio["id"], "unidad_id": None,
        "phone_number_id": canal["phone_number_id"], "modo": canal_modo,
    }
    proveedor, gabi = _preparar_webhook(monkeypatch, canal_dict, canal, [])
    return negocio, canal, canal_dict, proveedor, gabi


async def _hablar(proveedor, canal, telefono, *textos):
    for texto in textos:
        _n["wamid"] += 1
        await _correr(proveedor, [_msg(telefono, canal, texto, f"wamid.tr{_n['wamid']}")])


async def _filas(telefono: str, tipo: str | None = None) -> list:
    """TODOS los eventos de las conversaciones del teléfono, incluidos los internos (el Timeline no los entrega)."""
    async with mem.async_session() as s:
        q = (
            select(mem.EventoLead).join(mem.Conversation, mem.Conversation.id == mem.EventoLead.conversation_id)
            .join(mem.Contact, mem.Contact.id == mem.Conversation.contact_id)
            .where(mem.Contact.telefono == telefono).order_by(mem.EventoLead.id)
        )
        if tipo:
            q = q.where(mem.EventoLead.tipo == tipo)
        return (await s.execute(q)).scalars().all()


async def _opportunity(conversation_id: str):
    async with mem.async_session() as s:
        return (await s.execute(select(mem.Opportunity).where(mem.Opportunity.conversation_id == conversation_id))).scalar_one()


def _del_triaje(proveedor) -> list[str]:
    return [m for m in proveedor.enviados if "614900" in m]


def _lineas_log(caplog) -> list[dict]:
    return [json.loads(r.getMessage()[len("triaje_atc "):]) for r in caplog.records if r.getMessage().startswith("triaje_atc {")]


# ── Apagado: el camino de Gabi es idéntico ───────────────────────────────────────────────────────

@pytest.mark.parametrize("modo", [None, "apagado", "xyz", ""])
async def test_apagado_o_invalido_el_camino_de_gabi_es_identico(monkeypatch, caplog, modo):
    telefono = f"519400{len(str(modo)):05d}"
    negocio, canal, canal_dict, proveedor, gabi = await _escenario(monkeypatch, modo)

    def no_debe_llamarse(*a, **k):
        raise AssertionError("con el triaje apagado no se evalúa nada")
    monkeypatch.setattr(t, "_armar_contexto", no_debe_llamarse)
    monkeypatch.setattr(t, "clasificar", no_debe_llamarse)

    with caplog.at_level(logging.INFO, logger="agentkit"):
        await _hablar(proveedor, canal, telefono, "Hola", "Dori", "Mi recibo")

    assert gabi.llamadas == 3 and len(proveedor.enviados) == 3 and _del_triaje(proveedor) == []
    assert await _filas(telefono, mem.EVENTO_TRIAJE_ATC_SOMBRA) == [] and await _filas(telefono, mem.EVENTO_TRIAJE_ATC_CERRADO) == []
    assert _lineas_log(caplog) == []
    lead = await mem.obtener_lead(telefono, negocio_id=negocio["id"])
    assert lead["resultado"] is None and lead["cerrado_definitivamente_en"] is None
    assert len(await _conversaciones(telefono)) == 1


async def test_el_modo_se_normaliza_a_minusculas_y_sin_espacios():
    assert t._parsear_modo(" Activo ") == "activo" and t._parsear_modo("SOMBRA") == "sombra"
    assert t._parsear_modo(None) == "apagado" and t._parsear_modo("encendido") == "apagado"


# ── Sombra: solo observa ─────────────────────────────────────────────────────────────────────────

async def test_sombra_no_cambia_la_conducta_y_deja_una_linea_de_log_y_un_evento_interno(monkeypatch, caplog):
    telefono = "51940000101"
    negocio, canal, canal_dict, proveedor, gabi = await _escenario(monkeypatch, "sombra", linea=None)
    with caplog.at_level(logging.INFO, logger="agentkit"):
        await _hablar(proveedor, canal, telefono, "Hola", "Dori", "Mi recibo")

    # Gabi responde los tres turnos; nada de triaje sale al cliente ni cierra el caso.
    assert gabi.llamadas == 3 and len(proveedor.enviados) == 3
    lead = await mem.obtener_lead(telefono, negocio_id=negocio["id"])
    assert lead["resultado"] is None and lead["cerrado_definitivamente_en"] is None

    lineas = _lineas_log(caplog)
    decision = [l for l in lineas if l["categoria"] != "ninguna"]
    assert len(decision) == 1
    l = decision[0]
    assert l["categoria"] == "recibo" and l["accion_propuesta"] == "cerrar" and l["modo"] == "sombra" and l["capa"] == "reglas"
    assert l["señales"] == ["recibo_palabra"] and l["n_msgs_cliente"] == 3 and l["n_msgs_gabi_previos"] == 2
    assert l["guardas_que_bloquearon"] == [] and l["tiene_campana"] is False and l["confianza"] == 0.8
    assert set(l) == {
        "conv", "capa", "categoria", "accion_propuesta", "confianza", "señales", "n_msgs_cliente",
        "n_msgs_gabi_previos", "paso_flujo", "tiene_campana", "modo", "guardas_que_bloquearon",
    }
    # SIN teléfono, nombre ni texto en el log
    registro = " ".join(r.getMessage() for r in caplog.records if r.getMessage().startswith("triaje_atc"))
    assert telefono not in registro and "Dori" not in registro and "recibo" not in registro.replace('"categoria": "recibo"', "").replace("recibo_palabra", "")

    eventos = await _filas(telefono, mem.EVENTO_TRIAJE_ATC_SOMBRA)
    assert len(eventos) == 1 and eventos[0].autor is None and len(eventos[0].tipo) <= 60
    assert eventos[0].payload["categoria"] == "recibo" and eventos[0].payload["accion_propuesta"] == "cerrar"
    assert "614900" not in json.dumps(eventos[0].payload, ensure_ascii=False)


async def test_los_eventos_internos_no_salen_en_el_timeline_pero_el_cierre_si(monkeypatch):
    telefono = "51940000102"
    negocio, canal, canal_dict, proveedor, gabi = await _escenario(monkeypatch, "sombra")
    await _hablar(proveedor, canal, telefono, "Hola", "Dori", "Mi recibo", "ok")
    assert await _filas(telefono, mem.EVENTO_TRIAJE_ATC_SOMBRA)
    assert [e for e in await mem.listar_eventos_lead(telefono) if e["tipo"] in mem.TIPOS_EVENTO_INTERNOS] == []
    assert mem.EVENTO_TRIAJE_ATC_CERRADO not in mem.TIPOS_EVENTO_INTERNOS


async def test_la_misma_decision_no_repite_el_evento_en_cada_mensaje(monkeypatch):
    telefono = "51940000103"
    negocio, canal, canal_dict, proveedor, gabi = await _escenario(monkeypatch, "sombra")
    await _hablar(proveedor, canal, telefono, "Dori", "Mi recibo", "ok", "gracias")
    assert len(await _filas(telefono, mem.EVENTO_TRIAJE_ATC_SOMBRA)) == 1


async def test_sin_candidato_solo_deja_log_y_no_escribe_eventos(monkeypatch, caplog):
    telefono = "51940000104"
    negocio, canal, canal_dict, proveedor, gabi = await _escenario(monkeypatch, "sombra")
    with caplog.at_level(logging.INFO, logger="agentkit"):
        await _hablar(proveedor, canal, telefono, "Hola", "Quiero una terma")
    assert await _filas(telefono, mem.EVENTO_TRIAJE_ATC_SOMBRA) == []
    assert [l["categoria"] for l in _lineas_log(caplog)] == ["ninguna", "ninguna"]


async def test_un_candidato_bloqueado_queda_registrado_con_su_guarda(monkeypatch):
    telefono = "51940000105"
    negocio, canal, canal_dict, proveedor, gabi = await _escenario(monkeypatch, "sombra")
    await _hablar(proveedor, canal, telefono, "Hola", "Quiero un horno", "¿Las cuotas salen en el recibo?")
    [e] = await _filas(telefono, mem.EVENTO_TRIAJE_ATC_SOMBRA)
    assert e.payload["accion_propuesta"] == "ninguna" and "comercial_cuota" in e.payload["guardas_que_bloquearon"]


async def test_la_emergencia_de_gas_solo_se_registra_y_gabi_sigue_normal(monkeypatch, caplog):
    telefono = "51940000106"
    negocio, canal, canal_dict, proveedor, gabi = await _escenario(monkeypatch, "activo")
    with caplog.at_level(logging.INFO, logger="agentkit"):
        await _hablar(proveedor, canal, telefono, "Hola", "huele a gas en mi cocina")
    assert gabi.llamadas == 2 and _del_triaje(proveedor) == []
    [e] = await _filas(telefono, mem.EVENTO_TRIAJE_ATC_SOMBRA)
    assert e.payload["categoria"] == "emergencia_gas" and e.payload["accion_propuesta"] == "alerta_emergencia"
    assert any("triaje_atc_emergencia_gas" in r.getMessage() for r in caplog.records)
    assert (await mem.obtener_lead(telefono, negocio_id=negocio["id"]))["resultado"] is None


# ── Activo: cierra ───────────────────────────────────────────────────────────────────────────────

async def test_activo_envia_el_texto_guarda_el_mensaje_y_cierra_con_consulta_atc(monkeypatch):
    telefono = "51940000201"
    negocio, canal, canal_dict, proveedor, gabi = await _escenario(monkeypatch, "activo")
    avisos = []

    async def emite(conversation_id):
        avisos.append(conversation_id)
    monkeypatch.setattr(t.gestor_conexiones, "emitir_mensaje_nuevo", emite)

    async def no_notificar(*a, **k):
        raise AssertionError("el triaje no notifica a nadie")
    monkeypatch.setattr(app_main, "notificar_lead_derivado", no_notificar)

    await _hablar(proveedor, canal, telefono, "Hola", "Dori")
    await mem.actualizar_lead(telefono, nombre="Yasmin Pérez", paso_flujo="calificando", negocio_id=negocio["id"])
    await _hablar(proveedor, canal, telefono, "Mi recibo")

    assert gabi.llamadas == 2                      # el tercer turno lo atiende el triaje, no Gabi
    [texto] = _del_triaje(proveedor)
    assert texto == t.texto_para(None, "Yasmin Pérez", LINEA) and texto.startswith("¡Hola Yasmin! 😊")
    assert proveedor.enviados[-1] == texto

    lead = await mem.obtener_lead(telefono, negocio_id=negocio["id"])
    [conv] = await _conversaciones(telefono)
    opp = await _opportunity(conv.id)
    assert lead["resultado"] == "consulta_atc" and opp.resultado == "consulta_atc"
    assert lead["cerrado_definitivamente_en"] is not None and conv.cerrado_definitivamente_en is not None
    assert lead["asesor_asignado"] is None and conv.asesor_asignado_id is None and lead["pausado_manual"] is False
    assert lead["paso_flujo"] == "calificando"     # NO toca paso_flujo
    assert conv.estado == "activa"

    # el mensaje de Gabi se guardó ANTES del cierre (condición C4 del cierre de cortesía)
    ultimo = (await _mensajes(telefono, "assistant"))[-1]
    assert ultimo.content == texto and ultimo.estado_envio is None
    assert ultimo.timestamp <= conv.cerrado_definitivamente_en

    cambio = [e for e in await _filas(telefono, "resultado_cambiado")]
    assert len(cambio) == 1 and cambio[0].autor is None
    assert cambio[0].payload == {"campo": "resultado", "anterior": None, "nuevo": "consulta_atc", "origen": "triaje_atc", "categoria": "recibo"}
    [cerrado] = await _filas(telefono, mem.EVENTO_TRIAJE_ATC_CERRADO)
    assert cerrado.payload["categoria"] == "recibo" and cerrado.payload["origen"] == "triaje_atc" and cerrado.autor is None
    assert {"resultado_cambiado", "triaje_atc_cerrado"} <= {e["tipo"] for e in await mem.listar_eventos_lead(telefono)}
    assert await _filas(telefono, "asignado_automatico") == [] and await _filas(telefono, "asignado") == []

    # envío registrado con su origen, y el panel avisado
    async with mem.async_session() as s:
        fila = (await s.execute(select(mem.EnvioMeta).where(mem.EnvioMeta.origen == "triaje_atc"))).scalar_one()
    assert fila.decision == "enviado" and fila.telefono == telefono
    assert avisos and avisos[-1] == conv.id


async def test_la_categoria_numero_de_cliente_y_pago_cierran_con_su_categoria(monkeypatch):
    negocio, canal, canal_dict, proveedor, gabi = await _escenario(monkeypatch, "activo")
    await _hablar(proveedor, canal, "51940000202", "Hola", "Quiero saber un número de cliente")
    await _hablar(proveedor, canal, "51940000203", "Hola", "Tengo una deuda con Cálidda")
    cats = [e.payload["categoria"] for e in await _filas("51940000202", "resultado_cambiado")] + \
           [e.payload["categoria"] for e in await _filas("51940000203", "resultado_cambiado")]
    assert cats == ["numero_cliente", "pago_deuda"]


async def test_gracias_y_ok_posteriores_se_absorben_con_un_solo_agradecimiento(monkeypatch):
    telefono = "51940000204"
    negocio, canal, canal_dict, proveedor, gabi = await _escenario(monkeypatch, "activo")
    await _hablar(proveedor, canal, telefono, "Hola", "Dori", "Mi recibo")
    llamadas = gabi.llamadas
    await _hablar(proveedor, canal, telefono, "gracias", "ok", "muchas gracias")

    assert gabi.llamadas == llamadas                         # nadie despierta a Gabi
    assert len(await _conversaciones(telefono)) == 1         # no se abre un ciclo nuevo
    assert (await mem.obtener_lead(telefono, negocio_id=negocio["id"]))["resultado"] == "consulta_atc"
    assert proveedor.enviados.count(mem.AGRADECIMIENTO_CIERRE_TEXTO_POR_DEFECTO) == 1   # un solo agradecimiento
    assert len(_del_triaje(proveedor)) == 1
    assert len(await mem.listar_eventos_lead(telefono)) >= 3


async def test_un_ok_solo_tras_el_triaje_tambien_se_absorbe_sin_agradecer(monkeypatch):
    telefono = "51940000205"
    negocio, canal, canal_dict, proveedor, gabi = await _escenario(monkeypatch, "activo")
    await _hablar(proveedor, canal, telefono, "Dori", "Mi recibo")
    enviados, llamadas = len(proveedor.enviados), gabi.llamadas
    await _hablar(proveedor, canal, telefono, "ok")
    assert gabi.llamadas == llamadas and len(proveedor.enviados) == enviados
    assert len(await _conversaciones(telefono)) == 1


async def test_un_mensaje_real_tras_el_cierre_reabre_un_ciclo_y_limpia_el_cierre_del_lead(monkeypatch):
    telefono = "51940000206"
    negocio, canal, canal_dict, proveedor, gabi = await _escenario(monkeypatch, "activo")
    await _hablar(proveedor, canal, telefono, "Dori", "Mi recibo")
    llamadas = gabi.llamadas
    await _hablar(proveedor, canal, telefono, "Ahora quiero una cocina")

    convs = await _conversaciones(telefono)
    assert len(convs) == 2 and convs[0].estado == "cerrada" and convs[1].estado == "activa"
    assert gabi.llamadas == llamadas + 1                      # Gabi retoma
    lead = await mem.obtener_lead(telefono, negocio_id=negocio["id"])
    assert lead["resultado"] is None and lead["cerrado_definitivamente_en"] is None
    [reapertura] = await _filas(telefono, "reabierto_por_cliente")
    assert reapertura.payload["resultado_anterior"] == "consulta_atc" and reapertura.payload["asesor_anterior"] is None
    # y el modo sin IA ya no ignora a este lead (antes lo veía "cerrado")
    assert respaldo_sin_ia._lead_fuera_de_alcance(lead) is False


async def test_un_triaje_por_ciclo_y_un_ciclo_nuevo_puede_volver_a_triar(monkeypatch):
    telefono = "51940000207"
    negocio, canal, canal_dict, proveedor, gabi = await _escenario(monkeypatch, "activo")
    await _hablar(proveedor, canal, telefono, "Dori", "Mi recibo")
    await _hablar(proveedor, canal, telefono, "Hola de nuevo", "Mi factura")
    convs = await _conversaciones(telefono)
    assert len(convs) == 2
    assert len(await _filas(telefono, mem.EVENTO_TRIAJE_ATC_CERRADO)) == 2
    assert len(_del_triaje(proveedor)) == 2
    assert (await mem.obtener_lead(telefono, negocio_id=negocio["id"]))["resultado"] == "consulta_atc"


# ── Fallos seguros ───────────────────────────────────────────────────────────────────────────────

async def test_si_el_envio_falla_no_cierra_y_sigue_con_gabi_y_no_reintenta_en_el_ciclo(monkeypatch):
    telefono = "51940000301"
    negocio, canal, canal_dict, proveedor, gabi = await _escenario(monkeypatch, "activo")
    intentos = []

    async def enviar_falla(telefono_, mensaje, canal=None, mensaje_id_citado=None):
        intentos.append(mensaje)
        return False, None
    proveedor.enviar_mensaje = enviar_falla

    await _hablar(proveedor, canal, telefono, "Dori", "Mi recibo")
    assert gabi.llamadas == 2                                  # Gabi sigue: el triaje no atendió el turno
    lead = await mem.obtener_lead(telefono, negocio_id=negocio["id"])
    assert lead["resultado"] is None and lead["cerrado_definitivamente_en"] is None
    assert len([m for m in intentos if "614900" in m]) == 1
    [fallido] = await _filas(telefono, mem.EVENTO_TRIAJE_ATC_FALLIDO)
    assert fallido.payload["categoria"] == "recibo"
    assert [e for e in await mem.listar_eventos_lead(telefono) if e["tipo"] == mem.EVENTO_TRIAJE_ATC_FALLIDO] == []
    assert await _filas(telefono, mem.EVENTO_TRIAJE_ATC_CERRADO) == []
    # ningún mensaje del triaje quedó guardado como si hubiera salido
    assert [m for m in await _mensajes(telefono, "assistant") if "614900" in m.content] == []

    await _hablar(proveedor, canal, telefono, "mi recibo por favor")   # un triaje (o intento) por ciclo
    assert len([m for m in intentos if "614900" in m]) == 1 and gabi.llamadas == 3


async def test_si_el_proveedor_lanza_una_excepcion_el_caso_sigue_con_gabi(monkeypatch):
    telefono = "51940000302"
    negocio, canal, canal_dict, proveedor, gabi = await _escenario(monkeypatch, "activo")
    original = proveedor.enviar_mensaje

    async def enviar(telefono_, mensaje, canal=None, mensaje_id_citado=None):
        if "614900" in mensaje:
            raise RuntimeError("red caída")
        return await original(telefono_, mensaje, canal=canal, mensaje_id_citado=mensaje_id_citado)
    proveedor.enviar_mensaje = enviar

    await _hablar(proveedor, canal, telefono, "Dori", "Mi recibo")
    assert gabi.llamadas == 2
    assert (await mem.obtener_lead(telefono, negocio_id=negocio["id"]))["resultado"] is None
    assert len(await _filas(telefono, mem.EVENTO_TRIAJE_ATC_FALLIDO)) == 1


async def test_un_envio_incierto_cierra_y_guarda_el_mensaje_como_incierto(monkeypatch):
    telefono = "51940000303"
    negocio, canal, canal_dict, proveedor, gabi = await _escenario(monkeypatch, "activo")
    original = proveedor.enviar_mensaje

    async def enviar(telefono_, mensaje, canal=None, mensaje_id_citado=None):
        if "614900" in mensaje:
            raise EnvioIncierto("ReadTimeout")
        return await original(telefono_, mensaje, canal=canal, mensaje_id_citado=mensaje_id_citado)
    proveedor.enviar_mensaje = enviar

    await _hablar(proveedor, canal, telefono, "Dori", "Mi recibo")
    assert gabi.llamadas == 1
    assert (await mem.obtener_lead(telefono, negocio_id=negocio["id"]))["resultado"] == "consulta_atc"
    guardado = [m for m in await _mensajes(telefono, "assistant") if "614900" in m.content]
    assert len(guardado) == 1 and guardado[0].estado_envio == "incierto"


async def test_el_envio_frenado_por_la_politica_no_cierra(monkeypatch):
    # El origen es esencial: ningún interruptor lo frena, pero un envío bloqueado (p. ej. agrupado) nunca cierra.
    telefono = "51940000304"
    negocio, canal, canal_dict, proveedor, gabi = await _escenario(monkeypatch, "activo")

    async def bloqueado(*a, **k):
        return envios.ResultadoEnvio(False, None, bloqueado=True, motivo="política")
    monkeypatch.setattr(envios, "enviar_texto", bloqueado)
    await _hablar(proveedor, canal, telefono, "Dori", "Mi recibo")
    assert gabi.llamadas == 2 and (await mem.obtener_lead(telefono, negocio_id=negocio["id"]))["resultado"] is None


async def test_sin_linea_configurada_activo_se_degrada_a_sombra(monkeypatch, caplog):
    telefono = "51940000305"
    negocio, canal, canal_dict, proveedor, gabi = await _escenario(monkeypatch, "activo", linea=None)
    with caplog.at_level(logging.INFO, logger="agentkit"):
        await _hablar(proveedor, canal, telefono, "Dori", "Mi recibo")
    assert gabi.llamadas == 2 and len(proveedor.enviados) == 2
    assert (await mem.obtener_lead(telefono, negocio_id=negocio["id"]))["resultado"] is None
    assert _lineas_log(caplog)[-1]["modo"] == "sombra" and _lineas_log(caplog)[-1]["accion_propuesta"] == "cerrar"
    # con la línea en blanco pasa lo mismo
    await mem.guardar_configuracion(t.CLAVE_LINEA, "   ", negocio_id=negocio["id"])
    await _hablar(proveedor, canal, "51940000306", "Dori", "Mi recibo")
    assert (await mem.obtener_lead("51940000306", negocio_id=negocio["id"]))["resultado"] is None


async def test_un_error_al_evaluar_nunca_rompe_a_gabi(monkeypatch):
    telefono = "51940000307"
    negocio, canal, canal_dict, proveedor, gabi = await _escenario(monkeypatch, "activo")

    async def explota(*a, **k):
        raise RuntimeError("base caída")
    monkeypatch.setattr(t, "_armar_contexto", explota)
    await _hablar(proveedor, canal, telefono, "Dori", "Mi recibo")
    assert gabi.llamadas == 2 and (await mem.obtener_lead(telefono, negocio_id=negocio["id"]))["resultado"] is None
    ev = await t.evaluar(telefono, canal_dict, await mem.obtener_lead(telefono, negocio_id=negocio["id"]))
    assert ev.decision.categoria == "ninguna" and ev.modo == "apagado"


async def test_si_ejecutar_explota_antes_de_enviar_gabi_responde(monkeypatch):
    telefono = "51940000308"
    negocio, canal, canal_dict, proveedor, gabi = await _escenario(monkeypatch, "activo")

    async def explota(*a, **k):
        raise RuntimeError("fallo inesperado")
    monkeypatch.setattr(t, "_texto_final", explota)
    await _hablar(proveedor, canal, telefono, "Dori", "Mi recibo")
    assert gabi.llamadas == 2 and _del_triaje(proveedor) == []


async def test_si_el_texto_salio_pero_falla_el_cierre_gabi_no_responde_encima(monkeypatch):
    telefono = "51940000309"
    negocio, canal, canal_dict, proveedor, gabi = await _escenario(monkeypatch, "activo")

    async def explota(*a, **k):
        raise RuntimeError("base caída")
    monkeypatch.setattr(t, "cerrar_por_triaje", explota)
    await _hablar(proveedor, canal, telefono, "Dori", "Mi recibo")
    assert gabi.llamadas == 1 and len(_del_triaje(proveedor)) == 1       # un solo mensaje al cliente


# ── Interacción con otras piezas ─────────────────────────────────────────────────────────────────

async def test_con_el_circuito_de_ia_abierto_el_triaje_determinista_igual_funciona(monkeypatch):
    telefono = "51940000401"
    negocio, canal, canal_dict, proveedor, gabi = await _escenario(monkeypatch, "activo")
    derivaciones = []

    async def abierto():
        return True

    async def derivar(telefono_, canal_, motivo, *, proveedor=None):
        derivaciones.append(telefono_)
        return {"accion": "ya_derivado"}
    monkeypatch.setattr(app_main.circuito_ia, "esta_abierto", abierto)
    monkeypatch.setattr(app_main.circuito_ia, "sondear_en_segundo_plano", lambda: None)
    monkeypatch.setattr(app_main.respaldo_sin_ia, "derivar_por_falla_ia", derivar)

    await _hablar(proveedor, canal, telefono, "Dori", "Mi recibo")
    assert derivaciones == [telefono]                          # solo el primer mensaje; el recibo lo cerró el triaje
    assert len(_del_triaje(proveedor)) == 1
    assert (await mem.obtener_lead(telefono, negocio_id=negocio["id"]))["resultado"] == "consulta_atc"


async def test_canal_de_pruebas_no_cierra_salvo_que_se_permita(monkeypatch, caplog):
    telefono = "51940000402"
    negocio, canal, canal_dict, proveedor, gabi = await _escenario(monkeypatch, "activo", canal_modo="pruebas")
    with caplog.at_level(logging.INFO, logger="agentkit"):
        await _hablar(proveedor, canal, telefono, "Dori", "Mi recibo")
    assert gabi.llamadas == 2 and (await mem.obtener_lead(telefono, negocio_id=negocio["id"]))["resultado"] is None
    assert "canal_de_pruebas" in _lineas_log(caplog)[-1]["guardas_que_bloquearon"]

    await mem.guardar_configuracion(t.CLAVE_PERMITIR_CANAL_PRUEBAS, "1", negocio_id=negocio["id"])
    await _hablar(proveedor, canal, "51940000403", "Dori", "Mi recibo")
    assert (await mem.obtener_lead("51940000403", negocio_id=negocio["id"]))["resultado"] == "consulta_atc"


async def test_un_lead_con_asesor_no_pasa_por_el_triaje(monkeypatch):
    telefono = "51940000404"
    negocio, canal, canal_dict, proveedor, gabi = await _escenario(monkeypatch, "activo")
    await _hablar(proveedor, canal, telefono, "Hola")
    await mem.asignar_asesor_a_lead(telefono, "rvilchez")
    await _hablar(proveedor, canal, telefono, "Mi recibo")
    assert gabi.llamadas == 1 and _del_triaje(proveedor) == []
    assert (await mem.obtener_lead(telefono, negocio_id=negocio["id"]))["resultado"] is None
    # y la guarda también vale si alguien llama al triaje directamente con el lead de un humano
    lead = await mem.obtener_lead(telefono, negocio_id=negocio["id"])
    ev = await t.evaluar(telefono, canal_dict, lead)
    assert ev.decision.accion == "ninguna" and "asesor_o_pausa" in ev.decision.bloqueos


async def test_lead_en_cola_de_supervision_o_con_resultado_o_financiamiento_no_se_cierra(monkeypatch):
    negocio, canal, canal_dict, proveedor, gabi = await _escenario(monkeypatch, "sombra")   # sombra: el flujo real no cierra
    await _hablar(proveedor, canal, "51940000405", "Hola", "Mi recibo")
    lead = await mem.obtener_lead("51940000405", negocio_id=negocio["id"])
    for cambio, guarda in (
        ({"escalado_supervision_en": datetime.utcnow()}, "asesor_o_pausa"),
        ({"resultado": "agendado"}, "ya_tiene_resultado"),
        ({"paso_flujo": "evaluando_financiamiento"}, "paso_flujo_evaluando_financiamiento"),
        ({"paso_flujo": "derivado_asesor"}, "paso_flujo_derivado_asesor"),
    ):
        ev = await t.evaluar("51940000405", canal_dict, {**lead, **cambio})
        assert ev.decision.accion == "ninguna" and guarda in ev.decision.bloqueos, (cambio, ev.decision)


async def test_mi_recibo_justo_despues_de_que_gabi_pidio_el_dni_no_cierra(monkeypatch):
    telefono = "51940000406"
    negocio, canal, canal_dict, proveedor, gabi = await _escenario(monkeypatch, "activo")

    async def gabi_pide_dni(*a, **k):
        gabi.llamadas += 1
        return "Para validar tu financiamiento necesito tu DNI.", False, None, None
    monkeypatch.setattr(app_main.servicio_inteligencia, "generar_respuesta", gabi_pide_dni)
    await _hablar(proveedor, canal, telefono, "Dori", "Mi recibo")
    assert gabi.llamadas == 2 and _del_triaje(proveedor) == []
    assert (await mem.obtener_lead(telefono, negocio_id=negocio["id"]))["resultado"] is None


@pytest.mark.parametrize("dato", ["12345678", "mi suministro 9876543210"])
async def test_un_numero_largo_o_dni_del_cliente_no_cierra(monkeypatch, dato):
    telefono = f"519400005{len(dato):02d}"
    negocio, canal, canal_dict, proveedor, gabi = await _escenario(monkeypatch, "activo")
    await _hablar(proveedor, canal, telefono, dato, "Mi recibo")
    assert gabi.llamadas == 2 and (await mem.obtener_lead(telefono, negocio_id=negocio["id"]))["resultado"] is None


async def test_una_foto_del_cliente_no_cierra(monkeypatch):
    telefono = "51940000507"
    negocio, canal, canal_dict, proveedor, gabi = await _escenario(monkeypatch, "activo")
    await _hablar(proveedor, canal, telefono, "Hola")
    await mem.guardar_mensaje(telefono, "user", "[image]", negocio_id=negocio["id"])
    await _hablar(proveedor, canal, telefono, "Mi recibo")
    assert gabi.llamadas == 2 and (await mem.obtener_lead(telefono, negocio_id=negocio["id"]))["resultado"] is None


async def test_mas_de_cuatro_mensajes_del_cliente_no_cierra_pero_el_limite_es_configurable(monkeypatch):
    negocio, canal, canal_dict, proveedor, gabi = await _escenario(monkeypatch, "activo")
    await _hablar(proveedor, canal, "51940000508", "uno", "dos", "tres", "cuatro", "Mi recibo")
    assert (await mem.obtener_lead("51940000508", negocio_id=negocio["id"]))["resultado"] is None
    await mem.guardar_configuracion(t.CLAVE_MAX_MENSAJES, "6", negocio_id=negocio["id"])
    await _hablar(proveedor, canal, "51940000509", "uno", "dos", "tres", "cuatro", "Mi recibo")
    assert (await mem.obtener_lead("51940000509", negocio_id=negocio["id"]))["resultado"] == "consulta_atc"


async def test_los_mensajes_de_prueba_y_los_telefonos_excluidos_no_se_triaan(monkeypatch):
    negocio, canal, canal_dict, proveedor, gabi = await _escenario(monkeypatch, "activo", extra={t.CLAVE_TELEFONOS_EXCLUIDOS: "51940000601, +51 940 000 603"})
    await _hablar(proveedor, canal, "51940000601", "Dori", "Mi recibo")
    await _hablar(proveedor, canal, "51940000602", "prueba flow", "Mi recibo")
    await _hablar(proveedor, canal, "51940000603", "Dori", "Mi recibo")
    for tel in ("51940000601", "51940000602", "51940000603"):
        assert (await mem.obtener_lead(tel, negocio_id=negocio["id"]))["resultado"] is None
    await _hablar(proveedor, canal, "51940000604", "Dori", "Mi recibo")       # un teléfono normal sí
    assert (await mem.obtener_lead("51940000604", negocio_id=negocio["id"]))["resultado"] == "consulta_atc"


async def test_las_categorias_activas_son_configurables(monkeypatch):
    negocio, canal, canal_dict, proveedor, gabi = await _escenario(monkeypatch, "activo", extra={t.CLAVE_CATEGORIAS: "numero_cliente, pago_deuda"})
    await _hablar(proveedor, canal, "51940000701", "Dori", "Mi recibo")
    await _hablar(proveedor, canal, "51940000702", "Dori", "Quiero saber mi número de cliente")
    assert (await mem.obtener_lead("51940000701", negocio_id=negocio["id"]))["resultado"] is None
    assert (await mem.obtener_lead("51940000702", negocio_id=negocio["id"]))["resultado"] == "consulta_atc"


async def test_las_plantillas_y_el_nombre_del_negocio_son_por_negocio(monkeypatch):
    extra = {
        t.CLAVE_NOMBRE_NEGOCIO: "Cálidda Hogar",
        t.CLAVE_TEXTO: "Hola{nombre}, en {negocio} no vemos esto; la línea es {linea_atc}.",
        t.CLAVE_TEXTO_CATEGORIA + "numero_cliente": "Tu número de cliente lo ve la línea {linea_atc}. Gracias por escribir a {negocio}.",
        t.CLAVE_LINEA_EMERGENCIA: "1808 (Emergencias 24/7)",
    }
    negocio, canal, canal_dict, proveedor, gabi = await _escenario(monkeypatch, "activo", extra=extra)
    await _hablar(proveedor, canal, "51940000801", "Dori", "Mi recibo")
    await _hablar(proveedor, canal, "51940000802", "Dori", "Quiero saber mi número de cliente")
    assert "Hola, en Cálidda Hogar no vemos esto; la línea es 614900, opción 5." in proveedor.enviados
    assert "Tu número de cliente lo ve la línea 614900, opción 5. Gracias por escribir a Cálidda Hogar." in proveedor.enviados
    # otro negocio sin nada configurado: usa el texto por defecto y su fallback
    otro, canal2, _, proveedor2, _ = await _escenario(monkeypatch, "activo")
    await _hablar(proveedor2, canal2, "51940000803", "Dori", "Mi recibo")
    assert f"Aquí en {t.NOMBRE_NEGOCIO_POR_DEFECTO} te ayudamos" in _del_triaje(proveedor2)[0]


async def test_la_configuracion_no_se_filtra_entre_negocios(monkeypatch):
    a, canal_a, _, prov_a, gabi_a = await _escenario(monkeypatch, "activo")
    b, canal_b, _, prov_b, gabi_b = await _escenario(monkeypatch, "apagado")
    await _hablar(prov_b, canal_b, "51940000901", "Dori", "Mi recibo")
    assert (await mem.obtener_lead("51940000901", negocio_id=b["id"]))["resultado"] is None and gabi_b.llamadas == 2


# ── cerrar_por_triaje y los cambios de memoria ───────────────────────────────────────────────────

async def _caso_abierto(codigo, telefono):
    negocio = await mem.crear_negocio(f"Negocio {codigo}", codigo)
    _n["canal"] += 1
    canal = await mem.crear_canal_whatsapp(nombre="C", phone_number_id=f"4098{_n['canal']:06d}", negocio_id=negocio["id"])
    await mem.actualizar_lead(telefono, negocio_id=negocio["id"], numero_whatsapp_id="x")
    conv, opp = await mem.resolver_conversation_activa(telefono, negocio["id"], canal["id"])
    return negocio, canal, conv, opp


async def test_cerrar_por_triaje_hace_todo_en_una_transaccion():
    negocio, canal, conv, opp = await _caso_abierto("tr-cz-a", "51940001001")
    r = await mem.cerrar_por_triaje("51940001001", negocio["id"], "recibo")
    assert r["conversation_id"] == conv.id and r["opportunity_id"] == opp.id
    lead = await mem.obtener_lead("51940001001", negocio_id=negocio["id"])
    assert lead["resultado"] == "consulta_atc" and lead["cerrado_definitivamente_en"] == r["cierre_en"]
    assert (await _opportunity(conv.id)).resultado == "consulta_atc"
    assert lead["version"] >= 1


@pytest.mark.parametrize("preparar", ["asesor", "resultado", "cerrado", "pausa", "otro_negocio"])
async def test_cerrar_por_triaje_no_toca_nada_si_el_caso_ya_no_es_cerrable(preparar):
    telefono = "51940001002"
    negocio, canal, conv, opp = await _caso_abierto(f"tr-cz-{preparar}", telefono)
    if preparar == "asesor":
        await mem.asignar_asesor_a_lead(telefono, "rvilchez")
    elif preparar == "resultado":
        await mem.actualizar_lead(telefono, campos_explicitos=("resultado",), resultado="no_interesado")
    elif preparar == "cerrado":
        await mem.cerrar_por_triaje(telefono, negocio["id"], "recibo")
    elif preparar == "pausa":
        await mem.pausar_gabi_manual(telefono)
    antes = await mem.obtener_lead(telefono, negocio_id=negocio["id"])
    negocio_id = (await mem.crear_negocio("Otro", "tr-cz-otro"))["id"] if preparar == "otro_negocio" else negocio["id"]
    assert await mem.cerrar_por_triaje(telefono, negocio_id, "recibo") is None
    despues = await mem.obtener_lead(telefono, negocio_id=negocio["id"])
    assert (despues["resultado"], despues["cerrado_definitivamente_en"], despues["version"]) == (antes["resultado"], antes["cerrado_definitivamente_en"], antes["version"])
    if preparar != "cerrado":
        assert await _filas(telefono, mem.EVENTO_TRIAJE_ATC_CERRADO) == []


async def test_la_reapertura_sin_asesor_limpia_el_cierre_del_lead_y_con_asesor_lo_conserva():
    # sin asesor (el cierre que deja el triaje)
    negocio, canal, conv, opp = await _caso_abierto("tr-re-a", "51940001101")
    await mem.cerrar_por_triaje("51940001101", negocio["id"], "recibo")
    await mem.resolver_conversation_activa("51940001101", negocio["id"], canal["id"])
    lead = await mem.obtener_lead("51940001101", negocio_id=negocio["id"])
    assert lead["resultado"] is None and lead["cerrado_definitivamente_en"] is None
    assert respaldo_sin_ia._lead_fuera_de_alcance(lead) is False
    # con asesor: el cierre se conserva hasta que el webhook libere la asignación (no se rompe ese flujo)
    negocio2, canal2, conv2, opp2 = await _caso_abierto("tr-re-b", "51940001102")
    await mem.asignar_asesor_a_lead("51940001102", "rvilchez")
    await mem.actualizar_lead("51940001102", campos_explicitos=("resultado",), resultado="no_interesado")
    assert await mem.cerrar_lead_definitivamente("51940001102", negocio2["id"], "angie")
    await mem.resolver_conversation_activa("51940001102", negocio2["id"], canal2["id"])
    lead2 = await mem.obtener_lead("51940001102", negocio_id=negocio2["id"])
    assert lead2["asesor_asignado"] == "rvilchez" and lead2["cerrado_definitivamente_en"] is not None
    assert app_main._cierre_definitivo_pendiente_de_liberar(lead2) is True


async def test_el_caso_con_asesor_sigue_liberandose_por_el_webhook(monkeypatch):
    telefono = "51940001103"
    negocio, canal, canal_dict, conv = await _caso_cerrado("tr-re-c", telefono)       # asesor + cierre manual
    proveedor, gabi = _preparar_webhook(monkeypatch, canal_dict, canal, [])
    await _correr(proveedor, [_msg(telefono, canal, "Quiero otra cosa distinta", "wamid.tr-re-c")])
    lead = await mem.obtener_lead(telefono, negocio_id=negocio["id"])
    assert lead["asesor_asignado"] is None and lead["cerrado_definitivamente_en"] is None and gabi.llamadas == 1


# ── Estructura ───────────────────────────────────────────────────────────────────────────────────

def test_el_enganche_esta_despues_de_la_pausa_y_antes_del_circuito_de_ia():
    fuente = inspect.getsource(app_main._generar_y_enviar_respuesta_ia)
    pausa = fuente.index("_gabi_debe_pausarse(lead)")
    triaje = fuente.index("triaje_atc.procesar(")
    circuito = fuente.index("circuito_ia.esta_abierto()")
    assert pausa < triaje < circuito


def test_el_origen_triaje_atc_esta_registrado_como_esencial_y_con_limpieza_de_formato():
    assert envios.ORIGENES["triaje_atc"] == {"esencial": True}
    assert "triaje_atc" in envios.ORIGENES_CON_LIMPIEZA_DE_FORMATO and len("triaje_atc") <= 40


def test_ningun_tipo_de_evento_del_triaje_supera_el_limite_de_la_columna():
    for tipo in (mem.EVENTO_TRIAJE_ATC_CERRADO, mem.EVENTO_TRIAJE_ATC_SOMBRA, mem.EVENTO_TRIAJE_ATC_FALLIDO):
        assert len(tipo) <= 30 <= mem.TIPO_EVENTO_LARGO_MAX


def test_el_modulo_no_hardcodea_el_nombre_del_negocio_fuera_del_fallback_documentado():
    fuente = Path(t.__file__).read_text(encoding="utf-8")
    codigo = [l for l in fuente.splitlines() if not l.lstrip().startswith("#")]
    assert [l.strip() for l in codigo if "Gaso+" in l] == ['NOMBRE_NEGOCIO_POR_DEFECTO = "Gaso+"']
