# tests/test_triaje_atc_emergencia.py — Emergencia de gas (2026-10-09, decisión del dueño): la línea es COMERCIAL pero DERIVA.
# Ante olor o fuga de gas se envía UN texto fijo hacia Emergencias de Cálidda (1808, 24 h), sin IA (cero tokens), se tipifica
# `consulta_atc` y se cierra sin asesor. Interruptor PROPIO `triaje_atc_emergencia_modo` (apagado | sombra | activo),
# independiente de `triaje_atc_modo`. Detección estricta (precisión > recall), guardas propias (no las de los demás temas),
# repetición acotada a 24 h, lead en gestión (asesor/pausa) o con resultado: se avisa pero NO se cierra.

import os
from datetime import datetime, timedelta

os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")
os.environ.setdefault("WHATSAPP_PROVIDER", "meta")
os.environ["DEBOUNCE_RESPUESTA_SEGUNDOS"] = "0"

import importlib.util
import logging
from pathlib import Path

import pytest
from sqlalchemy import select, update

from agent import envios, politica_envios
from agent import main as app_main
from agent import memory as mem
from agent import triaje_atc as t
from tests.test_cierre_cortesia import _conversaciones, _mensajes
from tests.test_triaje_atc_flujo import _escenario, _filas, _hablar, _lineas_log, _n, _opportunity

LINEA_EM = "1808 (Emergencias 24/7)"
ACTIVA = {t.CLAVE_EMERGENCIA_MODO: "activo", t.CLAVE_LINEA_EMERGENCIA: LINEA_EM}
TEXTO_ESPERADO = t.texto_para(t.TEXTO_EMERGENCIA_POR_DEFECTO, None, "614900", "Gaso+", LINEA_EM)


def _avisos(proveedor) -> list[str]:
    return [m for m in proveedor.enviados if LINEA_EM in m]


def _tel(n: int) -> str:
    return f"519410{n:05d}"


async def _lead(telefono, negocio):
    return await mem.obtener_lead(telefono, negocio_id=negocio["id"])


# ── Detección ────────────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("texto", [
    "huele a gas en mi casa", "Huelo a gas", "HUELE A GAS!!! AYUDA", "Hay olor a gas en la cocina", "tengo olor a gas fuerte",
    "creo que hay una fuga de gas", "hay una fuga de gas en mi casa, qué hago?", "se escapa el gas de la cocina",
    "se está escapando el gas", "escape de gas en el departamento", "huele a gas ¿qué hago?", "hay gas en la cocina",
    "hay gas por toda la casa", "gas por toda la casa", "emergencia de gas", "explosión de gas en el edificio",
    "huele mucho a gas", "no sé qué hacer, huele a gas", "hola, mi cocina huele a gas",
])
def test_frases_de_olor_o_fuga_actuales_se_detectan(texto):
    assert t.detectar_emergencia([texto]), texto


@pytest.mark.parametrize("texto", [
    # el cliente describe otra cosa o quiere comprar
    "mi cocina a gas huele raro a plástico nuevo", "quiero una cocina a gas", "tengo gas natural",
    "cuánto cuesta la instalación de gas", "tengo fuga de agua", "quiero una terma a gas",
    # negación
    "no huele a gas", "no hay fuga de gas", "sin olor a gas", "nunca he tenido olor a gas", "ya no huele a gas",
    # pasado
    "hace años olía a gas", "tuve una fuga de gas hace años", "hubo una explosión", "ayer hubo fuga de gas",
    # hipótesis, pregunta, condicional
    "¿qué hago si huelo gas?", "si huelo gas llamo a emergencias", "cómo saber si hay fuga de gas", "¿hay fuga de gas?",
    "¿es normal que huela a gas?", "en caso de fuga de gas qué debo hacer", "huele a gas cuando prendo la cocina",
    # contexto comercial / servicio
    "¿cuánto cuesta un detector de fuga de gas?", "la cocina incluye válvula contra fuga de gas",
    "hay gas natural en la cocina?", "hay gas en mi casa, quiero una terma", "hay gas en la cocina si tengo el servicio",
])
def test_negaciones_hipotesis_pasado_preguntas_y_contexto_comercial_no_disparan(texto):
    assert not t.detectar_emergencia([texto]), texto


def test_la_deteccion_mira_cada_mensaje_y_no_mezcla_clausulas():
    assert t.detectar_emergencia(["Hola", "no sé, huele a gas", "gracias"])
    assert not t.detectar_emergencia(["no huele a gas", "quiero una cocina"])
    # la negación de una cláusula no tapa la emergencia de la siguiente
    assert t.detectar_emergencia(["no puedo respirar y huele a gas"])
    assert t.detectar_emergencia(["No hay problema con la terma. Huele a gas en la cocina"])


def test_clasificar_con_el_interruptor_apagado_es_alerta_idéntica_a_la_de_siempre():
    d = t.clasificar(["huele a gas"], t.Contexto())
    assert (d.categoria, d.accion, d.bloqueos) == ("emergencia_gas", "alerta_emergencia", ())


def test_clasificar_con_el_interruptor_encendido_propone_derivar_y_solo_aplica_sus_propias_guardas():
    # NO aplican asesor/pausa, resultado, cierre, paso_flujo, humano, media ni "demasiados mensajes"
    ctx = t.Contexto(
        emergencia_propone=True, con_asesor_o_pausa=True, resultado="vendido", cerrado=True, paso_flujo="derivado_asesor",
        hay_humano=True, hay_media=True, n_msgs_cliente=40,
    )
    d = t.clasificar(["huele a gas"], ctx)
    assert (d.categoria, d.accion, d.bloqueos) == ("emergencia_gas", "derivar_emergencia", ())
    for campo, valor, guarda in (
        ("canal_pruebas", True, "canal_de_pruebas"), ("telefono_excluido", True, "equipo_o_prueba"),
        ("emergencia_reciente", True, "emergencia_reciente_24h"),
    ):
        d = t.clasificar(["huele a gas"], t.Contexto(emergencia_propone=True, **{campo: valor}))
        assert d.accion == "alerta_emergencia" and d.bloqueos == (guarda,), campo
    assert t.clasificar(["prueba", "huele a gas"], t.Contexto(emergencia_propone=True)).bloqueos == ("equipo_o_prueba",)


def test_con_solo_emergencia_las_demas_categorias_no_se_evaluan():
    assert t.clasificar(["Dori", "mi recibo"], t.Contexto(evaluar_atc=False)).categoria == "ninguna"
    assert t.clasificar(["huele a gas"], t.Contexto(evaluar_atc=False)).categoria == "emergencia_gas"


def test_solo_cuentan_los_mensajes_pendientes_cuando_el_contexto_los_trae():
    ctx = t.Contexto(emergencia_propone=True, mensajes_pendientes=("ok gracias",))
    assert t.clasificar(["huele a gas", "ok gracias"], ctx).categoria == "ninguna"      # ya se atendió
    ctx = t.Contexto(emergencia_propone=True, mensajes_pendientes=("huele a gas",))
    assert t.clasificar(["Hola", "huele a gas"], ctx).accion == "derivar_emergencia"


# ── Texto ────────────────────────────────────────────────────────────────────────────────────────

def test_el_texto_por_defecto_es_corto_sin_pregunta_y_no_deja_nada_pendiente_para_el_cierre_de_cortesia():
    assert "?" not in TEXTO_ESPERADO and "¿" not in TEXTO_ESPERADO and "{" not in TEXTO_ESPERADO
    assert LINEA_EM in TEXTO_ESPERADO and "{linea_emergencia}" in t.TEXTO_EMERGENCIA_POR_DEFECTO
    assert TEXTO_ESPERADO.startswith("⚠️ Si hueles a gas") and "solo de ventas" in TEXTO_ESPERADO
    # C2/C3 de evaluar_cierre_cortesia: un «ok» posterior se absorbe
    assert mem.saliente_deja_algo_pendiente(TEXTO_ESPERADO) is False
    assert mem.nivel_cierre_cortesia("ok") == "B"


def test_decision_c3_con_llama_el_cierre_de_cortesia_lo_leeria_como_compromiso_pendiente():
    # Por eso el texto por defecto dice «Comunícate ya con…» y NO «Llama ya a…».
    con_llama = TEXTO_ESPERADO.replace("Comunícate ya con", "Llama ya a")
    assert mem.saliente_deja_algo_pendiente(con_llama) is True
    assert "Llama" not in t.TEXTO_EMERGENCIA_POR_DEFECTO


# ── Interruptor independiente ────────────────────────────────────────────────────────────────────

async def test_con_el_triaje_general_en_sombra_la_emergencia_activa_envia_y_cierra_sin_llamar_a_gabi(monkeypatch):
    telefono = _tel(1)
    negocio, canal, canal_dict, proveedor, gabi = await _escenario(monkeypatch, "sombra", extra=ACTIVA)
    avisos_panel = []

    async def emite(conversation_id):
        avisos_panel.append(conversation_id)
    monkeypatch.setattr(t.gestor_conexiones, "emitir_mensaje_nuevo", emite)

    async def no_notificar(*a, **k):
        raise AssertionError("la emergencia no notifica a nadie")
    monkeypatch.setattr(app_main, "notificar_lead_derivado", no_notificar)

    await _hablar(proveedor, canal, telefono, "Hola", "Dori")
    await mem.actualizar_lead(telefono, nombre="Yasmin Pérez", paso_flujo="calificando", negocio_id=negocio["id"])
    llamadas = gabi.llamadas
    await _hablar(proveedor, canal, telefono, "Huele a gas en mi cocina!!")

    assert gabi.llamadas == llamadas                                   # el turno lo atendió el aviso, no Gabi
    assert _avisos(proveedor) == [TEXTO_ESPERADO] and proveedor.enviados[-1] == TEXTO_ESPERADO
    lead = await _lead(telefono, negocio)
    [conv] = await _conversaciones(telefono)
    opp = await _opportunity(conv.id)
    assert lead["resultado"] == "consulta_atc" and opp.resultado == "consulta_atc"
    assert lead["cerrado_definitivamente_en"] is not None and conv.cerrado_definitivamente_en is not None
    assert lead["asesor_asignado"] is None and conv.asesor_asignado_id is None and lead["paso_flujo"] == "calificando"

    # tipificación y eventos
    [cambio] = await _filas(telefono, "resultado_cambiado")
    assert cambio.autor is None and cambio.payload == {
        "campo": "resultado", "anterior": None, "nuevo": "consulta_atc", "origen": "triaje_atc", "categoria": "emergencia_gas",
    }
    [cerrado] = await _filas(telefono, mem.EVENTO_TRIAJE_ATC_CERRADO)
    assert cerrado.payload["categoria"] == "emergencia_gas" and "emergencia" in cerrado.descripcion.lower()
    [derivada] = await _filas(telefono, mem.EVENTO_EMERGENCIA_GAS_DERIVADA)
    assert len(derivada.tipo) <= 60 and derivada.autor is None and derivada.payload["cerrado"] is True
    assert telefono not in derivada.descripcion and "Yasmin" not in derivada.descripcion
    assert mem.EVENTO_EMERGENCIA_GAS_DERIVADA in {e["tipo"] for e in await mem.listar_eventos_lead(telefono)}   # visible
    assert mem.EVENTO_EMERGENCIA_GAS_DERIVADA not in mem.TIPOS_EVENTO_INTERNOS
    assert await _filas(telefono, "asignado_automatico") == [] and await _filas(telefono, "asignado") == []

    # el mensaje del aviso se guardó ANTES del cierre (C4) y como mensaje de Gabi, una sola vez
    ultimo = (await _mensajes(telefono, "assistant"))[-1]
    assert ultimo.content == TEXTO_ESPERADO and ultimo.estado_envio is None
    assert ultimo.timestamp <= conv.cerrado_definitivamente_en
    assert len([m for m in await _mensajes(telefono, "assistant") if LINEA_EM in m.content]) == 1
    assert avisos_panel and avisos_panel[-1] == conv.id

    # envío registrado con su origen y el triaje general siguió en sombra (no cerró nada por su cuenta)
    async with mem.async_session() as s:
        fila = (await s.execute(select(mem.EnvioMeta).where(mem.EnvioMeta.origen == "triaje_emergencia_gas"))).scalar_one()
    assert fila.decision == "enviado" and fila.telefono == telefono


async def test_con_el_triaje_general_apagado_la_emergencia_activa_funciona_y_las_demas_categorias_siguen_con_gabi(monkeypatch):
    negocio, canal, canal_dict, proveedor, gabi = await _escenario(monkeypatch, None, extra=ACTIVA)
    await _hablar(proveedor, canal, _tel(2), "Dori", "Mi recibo")                      # recibo: el general está apagado
    assert gabi.llamadas == 2 and (await _lead(_tel(2), negocio))["resultado"] is None
    assert await _filas(_tel(2), mem.EVENTO_TRIAJE_ATC_SOMBRA) == []                   # ni siquiera se evalúa
    await _hablar(proveedor, canal, _tel(3), "Hola", "huele a gas")
    assert gabi.llamadas == 3 and _avisos(proveedor) == [TEXTO_ESPERADO]               # solo 'Hola' llegó a Gabi
    assert (await _lead(_tel(3), negocio))["resultado"] == "consulta_atc"


async def test_la_emergencia_apagada_es_identica_a_la_de_siempre_aunque_el_general_este_activo(monkeypatch, caplog):
    telefono = _tel(4)
    negocio, canal, canal_dict, proveedor, gabi = await _escenario(
        monkeypatch, "activo", extra={t.CLAVE_LINEA_EMERGENCIA: LINEA_EM},          # línea configurada, interruptor sin fijar
    )
    with caplog.at_level(logging.INFO, logger="agentkit"):
        await _hablar(proveedor, canal, telefono, "Hola", "huele a gas en mi cocina")
    assert gabi.llamadas == 2 and _avisos(proveedor) == []
    [e] = await _filas(telefono, mem.EVENTO_TRIAJE_ATC_SOMBRA)
    assert e.payload["categoria"] == "emergencia_gas" and e.payload["accion_propuesta"] == "alerta_emergencia"
    assert e.payload["guardas_que_bloquearon"] == []
    assert any("triaje_atc_emergencia_gas" in r.getMessage() for r in caplog.records)
    assert (await _lead(telefono, negocio))["resultado"] is None
    assert await _filas(telefono, mem.EVENTO_EMERGENCIA_GAS_DERIVADA) == []


@pytest.mark.parametrize("valor", [None, "apagado", "xyz", ""])
async def test_con_ambos_interruptores_apagados_no_se_evalua_nada(monkeypatch, valor):
    extra = {} if valor is None else {t.CLAVE_EMERGENCIA_MODO: valor}
    negocio, canal, canal_dict, proveedor, gabi = await _escenario(monkeypatch, None, extra=extra)

    def no_debe_llamarse(*a, **k):
        raise AssertionError("con todo apagado no se evalúa nada")
    monkeypatch.setattr(t, "_armar_contexto", no_debe_llamarse)
    monkeypatch.setattr(t, "clasificar", no_debe_llamarse)
    await _hablar(proveedor, canal, _tel(5), "Hola", "huele a gas")
    assert gabi.llamadas == 2 and _avisos(proveedor) == []


async def test_emergencia_en_sombra_solo_registra_log_y_evento_y_gabi_responde(monkeypatch, caplog):
    telefono = _tel(6)
    negocio, canal, canal_dict, proveedor, gabi = await _escenario(
        monkeypatch, None, extra={t.CLAVE_EMERGENCIA_MODO: "sombra", t.CLAVE_LINEA_EMERGENCIA: LINEA_EM},
    )
    with caplog.at_level(logging.INFO, logger="agentkit"):
        await _hablar(proveedor, canal, telefono, "Hola", "huele a gas en mi cocina")
    assert gabi.llamadas == 2 and _avisos(proveedor) == []
    [e] = await _filas(telefono, mem.EVENTO_TRIAJE_ATC_SOMBRA)
    assert e.payload["categoria"] == "emergencia_gas" and e.payload["modo"] == "sombra" and "614900" not in str(e.payload)
    assert [l for l in _lineas_log(caplog) if l["categoria"] == "emergencia_gas"][-1]["modo"] == "sombra"
    assert (await _lead(telefono, negocio))["resultado"] is None
    assert await _filas(telefono, mem.EVENTO_EMERGENCIA_GAS_DERIVADA) == []


async def test_sin_linea_ni_texto_propio_activo_se_degrada_a_sombra_pero_con_texto_propio_con_numero_si_sale(monkeypatch, caplog):
    negocio, canal, canal_dict, proveedor, gabi = await _escenario(
        monkeypatch, None, extra={t.CLAVE_EMERGENCIA_MODO: "activo"},               # sin línea de emergencia
    )
    with caplog.at_level(logging.INFO, logger="agentkit"):
        await _hablar(proveedor, canal, _tel(7), "Hola", "huele a gas")
    assert gabi.llamadas == 2 and len(proveedor.enviados) == 2                         # nunca sale un texto sin número
    assert (await _lead(_tel(7), negocio))["resultado"] is None
    assert [l for l in _lineas_log(caplog) if l["categoria"] == "emergencia_gas"][-1]["modo"] == "sombra"
    await mem.guardar_configuracion(t.CLAVE_LINEA_EMERGENCIA, "   ", negocio_id=negocio["id"])
    await _hablar(proveedor, canal, _tel(8), "Hola", "huele a gas")
    assert (await _lead(_tel(8), negocio))["resultado"] is None
    # con un texto propio que ya trae el número, no hace falta la clave de la línea
    await mem.guardar_configuracion(
        t.CLAVE_EMERGENCIA_TEXTO, "Sal de la casa y comunícate con Cálidda al 1808, las 24 horas.", negocio_id=negocio["id"],
    )
    await _hablar(proveedor, canal, _tel(9), "Hola", "huele a gas")
    assert proveedor.enviados[-1] == "Sal de la casa y comunícate con Cálidda al 1808, las 24 horas."
    assert (await _lead(_tel(9), negocio))["resultado"] == "consulta_atc"


async def test_texto_propio_con_marcador_usa_la_linea_configurada(monkeypatch):
    negocio, canal, canal_dict, proveedor, gabi = await _escenario(
        monkeypatch, None, extra={**ACTIVA, t.CLAVE_EMERGENCIA_TEXTO: "Sal ya. Emergencias: {linea_emergencia}. Atención de {negocio}."},
    )
    await _hablar(proveedor, canal, _tel(10), "Hola", "hay fuga de gas")
    assert proveedor.enviados[-1] == f"Sal ya. Emergencias: {LINEA_EM}. Atención de Cálidda Hogar."


# ── Cero tokens ──────────────────────────────────────────────────────────────────────────────────

async def test_el_camino_de_la_emergencia_no_llama_a_gabi_ni_a_claude(monkeypatch):
    negocio, canal, canal_dict, proveedor, gabi = await _escenario(monkeypatch, None, extra=ACTIVA)
    llamadas = []

    async def explota(*a, **k):
        llamadas.append(a)
        raise AssertionError("la emergencia es determinista: no puede llamar a la IA")
    monkeypatch.setattr(app_main.servicio_inteligencia, "generar_respuesta", explota)
    monkeypatch.setattr(app_main.servicio_inteligencia, "extraer_datos_lead", explota)
    from agent import brain
    monkeypatch.setattr(brain, "generar_respuesta", explota, raising=False)
    await _hablar(proveedor, canal, _tel(11), "huele a gas en mi casa")                 # primer mensaje del chat
    assert llamadas == [] and _avisos(proveedor) == [TEXTO_ESPERADO]
    assert (await _lead(_tel(11), negocio))["resultado"] == "consulta_atc"


# ── Exento del tope ──────────────────────────────────────────────────────────────────────────────

async def test_con_el_tope_mensual_agotado_y_la_opcion_b_el_aviso_igual_sale(monkeypatch):
    negocio, canal, canal_dict, proveedor, gabi = await _escenario(monkeypatch, None, extra={
        **ACTIVA, "envios_tope_mensual_usd": "0", "envios_tope_bloquea_esenciales": "true",
        "meta_cuota_gratis_servicio": "0", "envios_modo_triaje_emergencia_gas": "nunca",
    })
    politica_envios.limpiar_cache()
    await _hablar(proveedor, canal, _tel(12), "Hola", "huele a gas")
    assert _avisos(proveedor) == [TEXTO_ESPERADO] and gabi.llamadas == 1
    async with mem.async_session() as s:
        fila = (await s.execute(select(mem.EnvioMeta).where(
            mem.EnvioMeta.origen == "triaje_emergencia_gas", mem.EnvioMeta.telefono == _tel(12)))).scalar_one()
    assert fila.decision == "enviado"


# ── Lead en gestión o con resultado: se avisa, NO se cierra ──────────────────────────────────────

async def test_con_asesor_asignado_se_envia_el_aviso_sin_quitar_al_asesor_ni_cerrar(monkeypatch):
    telefono = _tel(13)
    negocio, canal, canal_dict, proveedor, gabi = await _escenario(monkeypatch, None, extra=ACTIVA)
    await _hablar(proveedor, canal, telefono, "Hola")
    await mem.asignar_asesor_a_lead(telefono, "rvilchez")
    llamadas = gabi.llamadas
    await _hablar(proveedor, canal, telefono, "huele a gas en mi cocina")

    assert gabi.llamadas == llamadas and _avisos(proveedor) == [TEXTO_ESPERADO]
    lead = await _lead(telefono, negocio)
    [conv] = await _conversaciones(telefono)
    assert lead["asesor_asignado"] == "rvilchez" and conv.asesor_asignado_id is not None
    assert lead["resultado"] is None and lead["cerrado_definitivamente_en"] is None and conv.cerrado_definitivamente_en is None
    assert (await _opportunity(conv.id)).resultado is None
    [derivada] = await _filas(telefono, mem.EVENTO_EMERGENCIA_GAS_DERIVADA)
    assert derivada.payload["cerrado"] is False and derivada.payload["motivo_sin_cierre"] == "con_asesor_o_pausa"
    assert await _filas(telefono, "resultado_cambiado") == [] and await _filas(telefono, mem.EVENTO_TRIAJE_ATC_CERRADO) == []
    assert [m.content for m in await _mensajes(telefono, "assistant") if LINEA_EM in m.content] == [TEXTO_ESPERADO]
    assert [m.content for m in await _mensajes(telefono, "user")][-1] == "huele a gas en mi cocina"


async def test_con_gabi_pausada_se_envia_el_aviso_y_la_pausa_se_conserva(monkeypatch):
    telefono = _tel(14)
    negocio, canal, canal_dict, proveedor, gabi = await _escenario(monkeypatch, "sombra", extra=ACTIVA)
    await _hablar(proveedor, canal, telefono, "Hola")
    await mem.pausar_gabi_manual(telefono)
    await _hablar(proveedor, canal, telefono, "hay fuga de gas")
    lead = await _lead(telefono, negocio)
    assert _avisos(proveedor) == [TEXTO_ESPERADO] and lead["pausado_manual"] is True
    assert lead["resultado"] is None and lead["cerrado_definitivamente_en"] is None


async def test_un_lead_con_asesor_no_recibe_nada_si_la_emergencia_esta_apagada_o_en_sombra(monkeypatch):
    for modo, base in (("apagado", 15), ("sombra", 16)):
        negocio, canal, canal_dict, proveedor, gabi = await _escenario(
            monkeypatch, None, extra={t.CLAVE_EMERGENCIA_MODO: modo, t.CLAVE_LINEA_EMERGENCIA: LINEA_EM},
        )
        await _hablar(proveedor, canal, _tel(base), "Hola")
        await mem.asignar_asesor_a_lead(_tel(base), "rvilchez")
        await _hablar(proveedor, canal, _tel(base), "huele a gas")
        assert _avisos(proveedor) == [] and (await _lead(_tel(base), negocio))["asesor_asignado"] == "rvilchez"


@pytest.mark.parametrize("resultado, con_asesor", [("agendado", False), ("vendido", True), ("agendado", True)])
async def test_un_lead_vendido_o_agendado_recibe_el_aviso_sin_cerrar_ni_cambiar_el_resultado(monkeypatch, resultado, con_asesor):
    telefono = _tel(17 + (resultado == "vendido") * 2 + con_asesor)
    negocio, canal, canal_dict, proveedor, gabi = await _escenario(monkeypatch, "sombra", extra=ACTIVA)
    await _hablar(proveedor, canal, telefono, "Hola")
    if con_asesor:
        await mem.asignar_asesor_a_lead(telefono, "rvilchez")
    await mem.actualizar_lead(telefono, campos_explicitos=("resultado",), resultado=resultado)
    await _hablar(proveedor, canal, telefono, "huele a gas")

    assert _avisos(proveedor) == [TEXTO_ESPERADO]
    lead = await _lead(telefono, negocio)
    [conv] = await _conversaciones(telefono)
    assert lead["resultado"] == resultado and (await _opportunity(conv.id)).resultado == resultado
    assert lead["cerrado_definitivamente_en"] is None and conv.cerrado_definitivamente_en is None
    assert (lead["asesor_asignado"] == "rvilchez") is con_asesor
    [derivada] = await _filas(telefono, mem.EVENTO_EMERGENCIA_GAS_DERIVADA)
    assert derivada.payload["cerrado"] is False and derivada.payload["motivo_sin_cierre"] in ("ya_tiene_resultado", "con_asesor_o_pausa")
    assert await _filas(telefono, "resultado_cambiado") == []


# ── Repetición: 24 h ─────────────────────────────────────────────────────────────────────────────

async def test_no_se_repite_el_aviso_dentro_de_24_horas_y_pasado_el_lapso_si(monkeypatch):
    telefono = _tel(30)
    negocio, canal, canal_dict, proveedor, gabi = await _escenario(monkeypatch, None, extra=ACTIVA)
    await _hablar(proveedor, canal, telefono, "Hola", "huele a gas")
    assert len(_avisos(proveedor)) == 1
    llamadas = gabi.llamadas
    await _hablar(proveedor, canal, telefono, "sigue oliendo, huele a gas todavía")   # ciclo nuevo (reabre), mismo cliente
    assert len(_avisos(proveedor)) == 1                                                # NO se repite
    assert gabi.llamadas == llamadas + 1                                               # Gabi atiende como siempre
    assert len(await _filas(telefono, mem.EVENTO_EMERGENCIA_GAS_DERIVADA)) == 1

    # pasadas 24 h (envío y evento viejos) se vuelve a avisar
    viejo = datetime.utcnow() - timedelta(hours=25)
    async with mem.async_session() as s:
        await s.execute(update(mem.EnvioMeta).where(mem.EnvioMeta.telefono == telefono, mem.EnvioMeta.origen == "triaje_emergencia_gas").values(creado=viejo))
        await s.execute(update(mem.EventoLead).where(mem.EventoLead.tipo == mem.EVENTO_EMERGENCIA_GAS_DERIVADA).values(creado=viejo))
        await s.commit()
    await _hablar(proveedor, canal, telefono, "huele a gas otra vez")
    assert len(_avisos(proveedor)) == 2


# ── Después del aviso: cortesía, reapertura ──────────────────────────────────────────────────────

async def test_gracias_y_ok_posteriores_se_absorben_sin_reabrir_ni_despertar_a_gabi(monkeypatch):
    telefono = _tel(31)
    negocio, canal, canal_dict, proveedor, gabi = await _escenario(monkeypatch, None, extra=ACTIVA)
    await _hablar(proveedor, canal, telefono, "Hola", "huele a gas")
    llamadas = gabi.llamadas
    await _hablar(proveedor, canal, telefono, "ok", "gracias", "muchas gracias")
    assert gabi.llamadas == llamadas
    assert len(await _conversaciones(telefono)) == 1
    assert (await _lead(telefono, negocio))["resultado"] == "consulta_atc"
    assert len(_avisos(proveedor)) == 1


async def test_un_ok_solo_tras_el_aviso_tambien_se_absorbe(monkeypatch):
    telefono = _tel(32)
    negocio, canal, canal_dict, proveedor, gabi = await _escenario(monkeypatch, None, extra=ACTIVA)
    await _hablar(proveedor, canal, telefono, "huele a gas")
    enviados, llamadas = len(proveedor.enviados), gabi.llamadas
    await _hablar(proveedor, canal, telefono, "ok")
    assert gabi.llamadas == llamadas and len(proveedor.enviados) == enviados and len(await _conversaciones(telefono)) == 1


async def test_con_un_texto_con_llama_un_ok_reabriria_el_caso_y_gabi_responderia(monkeypatch):
    # la razón de la decisión sobre C3: con «Llama ya…» el «ok» NO se absorbe
    telefono = _tel(33)
    negocio, canal, canal_dict, proveedor, gabi = await _escenario(monkeypatch, None, extra={
        **ACTIVA, t.CLAVE_EMERGENCIA_TEXTO: "Sal de la vivienda. Llama ya a Emergencias de Cálidda: {linea_emergencia}.",
    })
    await _hablar(proveedor, canal, telefono, "huele a gas")
    llamadas = gabi.llamadas
    await _hablar(proveedor, canal, telefono, "ok")
    assert gabi.llamadas == llamadas + 1 and len(await _conversaciones(telefono)) == 2


async def test_un_mensaje_real_tras_el_aviso_reabre_un_ciclo_y_limpia_el_cierre(monkeypatch):
    telefono = _tel(34)
    negocio, canal, canal_dict, proveedor, gabi = await _escenario(monkeypatch, None, extra=ACTIVA)
    await _hablar(proveedor, canal, telefono, "huele a gas")
    llamadas = gabi.llamadas
    await _hablar(proveedor, canal, telefono, "Ahora quiero una cocina")
    convs = await _conversaciones(telefono)
    assert len(convs) == 2 and convs[0].estado == "cerrada" and convs[1].estado == "activa"
    assert gabi.llamadas == llamadas + 1 and len(_avisos(proveedor)) == 1
    lead = await _lead(telefono, negocio)
    assert lead["resultado"] is None and lead["cerrado_definitivamente_en"] is None
    [reapertura] = await _filas(telefono, "reabierto_por_cliente")
    assert reapertura.payload["resultado_anterior"] == "consulta_atc"


async def test_una_frase_vieja_ya_atendida_no_vuelve_a_disparar_el_aviso(monkeypatch):
    # Con la emergencia apagada Gabi respondió; al encenderla, un mensaje posterior no relacionado no dispara el aviso.
    telefono = _tel(35)
    negocio, canal, canal_dict, proveedor, gabi = await _escenario(monkeypatch, None, extra={t.CLAVE_LINEA_EMERGENCIA: LINEA_EM})
    await _hablar(proveedor, canal, telefono, "huele a gas")
    assert gabi.llamadas == 1
    await mem.guardar_configuracion(t.CLAVE_EMERGENCIA_MODO, "activo", negocio_id=negocio["id"])
    await _hablar(proveedor, canal, telefono, "gracias por la ayuda, ya está resuelto")
    assert _avisos(proveedor) == [] and gabi.llamadas == 2


# ── Guardas y fallos ─────────────────────────────────────────────────────────────────────────────

async def test_canal_de_pruebas_no_avisa_salvo_que_se_permita(monkeypatch):
    negocio, canal, canal_dict, proveedor, gabi = await _escenario(monkeypatch, None, extra=ACTIVA, canal_modo="pruebas")
    await _hablar(proveedor, canal, _tel(40), "Hola", "huele a gas")
    assert _avisos(proveedor) == [] and gabi.llamadas == 2
    await mem.guardar_configuracion(t.CLAVE_PERMITIR_CANAL_PRUEBAS, "1", negocio_id=negocio["id"])
    await _hablar(proveedor, canal, _tel(41), "Hola", "huele a gas")
    assert _avisos(proveedor) == [TEXTO_ESPERADO]


async def test_telefonos_excluidos_y_mensajes_de_prueba_no_reciben_el_aviso(monkeypatch):
    negocio, canal, canal_dict, proveedor, gabi = await _escenario(
        monkeypatch, None, extra={**ACTIVA, t.CLAVE_TELEFONOS_EXCLUIDOS: _tel(42)},
    )
    await _hablar(proveedor, canal, _tel(42), "huele a gas")
    await _hablar(proveedor, canal, _tel(43), "prueba flow", "huele a gas")
    assert _avisos(proveedor) == []
    await _hablar(proveedor, canal, _tel(44), "huele a gas")
    assert len(_avisos(proveedor)) == 1


async def test_ni_el_asesor_ni_el_paso_de_flujo_ni_los_numeros_largos_bloquean_el_aviso(monkeypatch):
    # las guardas del triaje ATC (DNI, muchos mensajes, flujo de financiamiento…) NO aplican a una emergencia
    telefono = _tel(45)
    negocio, canal, canal_dict, proveedor, gabi = await _escenario(monkeypatch, "sombra", extra=ACTIVA)
    await _hablar(proveedor, canal, telefono, "Hola", "mi dni es 12345678", "uno", "dos", "tres")
    await mem.actualizar_lead(telefono, paso_flujo="evaluando_financiamiento", negocio_id=negocio["id"])
    await _hablar(proveedor, canal, telefono, "huele a gas")
    assert _avisos(proveedor) == [TEXTO_ESPERADO]
    assert (await _lead(telefono, negocio))["paso_flujo"] == "evaluando_financiamiento"


async def test_si_el_envio_falla_gabi_responde_no_se_cierra_y_el_siguiente_mensaje_reintenta(monkeypatch):
    telefono = _tel(46)
    negocio, canal, canal_dict, proveedor, gabi = await _escenario(monkeypatch, None, extra=ACTIVA)
    intentos = []

    async def enviar_falla(telefono_, mensaje, canal=None, mensaje_id_citado=None):
        intentos.append(mensaje)
        return False, None
    original = proveedor.enviar_mensaje
    proveedor.enviar_mensaje = enviar_falla
    await _hablar(proveedor, canal, telefono, "Hola", "huele a gas")
    lead = await _lead(telefono, negocio)
    assert gabi.llamadas == 2 and lead["resultado"] is None and lead["cerrado_definitivamente_en"] is None
    assert [m for m in intentos if LINEA_EM in m] == [TEXTO_ESPERADO]
    assert len(await _filas(telefono, mem.EVENTO_TRIAJE_ATC_FALLIDO)) == 1
    assert await _filas(telefono, mem.EVENTO_EMERGENCIA_GAS_DERIVADA) == []
    assert [m for m in await _mensajes(telefono, "assistant") if LINEA_EM in m.content] == []

    proveedor.enviar_mensaje = original                                              # el proveedor se recupera
    await _hablar(proveedor, canal, telefono, "huele a gas, ayuda")
    assert _avisos(proveedor) == [TEXTO_ESPERADO]                                    # un fallo NO cuenta como aviso
    assert (await _lead(telefono, negocio))["resultado"] == "consulta_atc"


async def test_si_el_proveedor_lanza_una_excepcion_el_caso_sigue_con_gabi(monkeypatch):
    telefono = _tel(47)
    negocio, canal, canal_dict, proveedor, gabi = await _escenario(monkeypatch, None, extra=ACTIVA)
    original = proveedor.enviar_mensaje

    async def enviar(telefono_, mensaje, canal=None, mensaje_id_citado=None):
        if LINEA_EM in mensaje:
            raise RuntimeError("red caída")
        return await original(telefono_, mensaje, canal=canal, mensaje_id_citado=mensaje_id_citado)
    proveedor.enviar_mensaje = enviar
    await _hablar(proveedor, canal, telefono, "Hola", "huele a gas")
    assert gabi.llamadas == 2 and (await _lead(telefono, negocio))["resultado"] is None


async def test_si_el_aviso_salio_pero_falla_el_cierre_gabi_no_responde_encima(monkeypatch):
    telefono = _tel(48)
    negocio, canal, canal_dict, proveedor, gabi = await _escenario(monkeypatch, None, extra=ACTIVA)

    async def explota(*a, **k):
        raise RuntimeError("base caída")
    monkeypatch.setattr(t, "cerrar_por_triaje", explota)
    await _hablar(proveedor, canal, telefono, "huele a gas")
    assert gabi.llamadas == 0 and len(_avisos(proveedor)) == 1
    [derivada] = await _filas(telefono, mem.EVENTO_EMERGENCIA_GAS_DERIVADA)
    assert derivada.payload["cerrado"] is False and derivada.payload["motivo_sin_cierre"] == "no_se_pudo_cerrar"


async def test_la_emergencia_gana_a_un_tema_de_atc_en_el_mismo_mensaje(monkeypatch):
    negocio, canal, canal_dict, proveedor, gabi = await _escenario(monkeypatch, "activo", extra=ACTIVA)
    await _hablar(proveedor, canal, _tel(49), "Dori", "mi recibo, además huele a gas")
    assert _avisos(proveedor) == [TEXTO_ESPERADO] and not [m for m in proveedor.enviados if "614900" in m]
    [cambio] = await _filas(_tel(49), "resultado_cambiado")
    assert cambio.payload["categoria"] == "emergencia_gas"


async def test_una_pregunta_hipotetica_no_dispara_el_aviso_y_gabi_responde(monkeypatch):
    negocio, canal, canal_dict, proveedor, gabi = await _escenario(monkeypatch, None, extra=ACTIVA)
    await _hablar(proveedor, canal, _tel(50), "Hola", "¿qué hago si huelo gas?", "quiero una cocina a gas")
    assert _avisos(proveedor) == [] and gabi.llamadas == 3
    assert (await _lead(_tel(50), negocio))["resultado"] is None


# ── Origen y estructura ──────────────────────────────────────────────────────────────────────────

def test_el_origen_esta_registrado_como_esencial_exento_del_tope_y_con_limpieza_de_formato():
    assert envios.ORIGENES["triaje_emergencia_gas"] == {"esencial": True, "exento_tope": True}
    assert "triaje_emergencia_gas" in envios.ORIGENES_CON_LIMPIEZA_DE_FORMATO
    assert t.ORIGEN_EMERGENCIA == "triaje_emergencia_gas"


def test_el_texto_de_emergencia_pasa_intacto_por_la_limpieza_de_formato():
    from agent import formato_whatsapp
    assert formato_whatsapp.formatear_para_whatsapp(TEXTO_ESPERADO) == TEXTO_ESPERADO


def test_el_tipo_de_evento_cabe_en_la_columna():
    assert len(mem.EVENTO_EMERGENCIA_GAS_DERIVADA) <= mem.TIPO_EVENTO_LARGO_MAX


def test_el_enganche_de_los_leads_en_gestion_esta_en_la_rama_del_webhook_que_no_llega_a_gabi():
    import inspect
    fuente = inspect.getsource(app_main.webhook_handler)
    pausa = fuente.index("Caso todavía abierto")
    llamada = fuente.index("triaje_atc.procesar(msg.telefono, canal, lead, proveedor, solo_emergencia=True)")
    debounce = fuente.index("gestor_debounce_respuestas.reprogramar(")
    assert pausa < llamada < debounce


# ── Análisis (agregado, sin PII) ─────────────────────────────────────────────────────────────────

def _cargar_analisis():
    ruta = Path(__file__).resolve().parent.parent / "scripts" / "analisis_triaje_atc.py"
    spec = importlib.util.spec_from_file_location("analisis_triaje_atc_em", ruta)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


async def test_el_analisis_cuenta_las_emergencias_aparte_sin_contaminar_las_metricas_de_recibo_y_pago(monkeypatch):
    at = _cargar_analisis()
    negocio, canal, canal_dict, proveedor, gabi = await _escenario(monkeypatch, "sombra", extra=ACTIVA)
    await _hablar(proveedor, canal, _tel(60), "Hola", "huele a gas")                    # avisada y cerrada
    await _hablar(proveedor, canal, _tel(61), "Hola")
    await mem.asignar_asesor_a_lead(_tel(61), "rvilchez")
    await _hablar(proveedor, canal, _tel(61), "hay fuga de gas")                         # avisada SIN cerrar
    [conv60] = await _conversaciones(_tel(60))
    [conv61] = await _conversaciones(_tel(61))
    async with mem.async_session() as s:
        datos = await at.cargar_datos(s, datetime(2000, 1, 1), datetime.utcnow() + timedelta(days=1))
        await s.rollback()
    em = datos.emergencias
    assert em[conv60.id]["avisada"] and em[conv60.id]["cerrada"]
    assert em[conv61.id]["avisada"] and not em[conv61.id]["cerrada"] and em[conv61.id]["motivo"] == "con_asesor_o_pausa"
    assert conv60.id not in datos.convs and conv60.id not in {c.id for c in datos.universo_recall}
    r = at.resumir(datos)
    assert r["emergencia"]["avisadas"] >= 2 and r["emergencia"]["cerradas"] >= 1 and r["emergencia"]["avisadas_sin_cierre"] >= 1
    texto = "\n".join(at.formatear(datos, r, "2000-01-01", "2099-01-01"))
    assert "5. EMERGENCIA DE GAS" in texto
    for secreto in (_tel(60), _tel(61), conv60.id, conv61.id, "huele a gas"):
        assert secreto not in texto
