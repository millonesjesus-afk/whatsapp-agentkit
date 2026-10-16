# tests/test_solo_clic_flujo.py — Experimento «solo clic» (2026-10-16, agent/solo_clic.py) contra la base: configuración,
# prellenados frecuentes, la definición sobre datos reales, la EXCLUSIÓN en «Para llamar», la SOMBRA (idempotencia, sin envíos,
# sin tareas, oculta en el Timeline, aislada por negocio, desenlaces a 24/72 h) y los scripts de medición, análisis y
# configuración. Datos sintéticos únicamente.

import importlib.util
import logging
import os
import re
from datetime import datetime, timedelta
from pathlib import Path

os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")
os.environ.setdefault("WHATSAPP_PROVIDER", "meta")
os.environ["DEBOUNCE_RESPUESTA_SEGUNDOS"] = "0"

import pytest
from sqlalchemy import event, select

from agent import llamadas as ll
from agent import memory as mem
from agent import solo_clic as sc
from tests.test_llamadas_flujo import _cfg, _eventos, _negocio, _tareas

RAIZ = Path(__file__).resolve().parent.parent
TEL = "51987100001"
PRELLENADO = "Hola, quiero más información de este producto"
GABI_SALUDO = "¡Hola! Soy Gabi, de Gaso+. ¿En qué te puedo ayudar hoy?"
GABI_PRECIO = "Hola Ana, la terma de 80 litros cuesta S/ 1,200. ¿Me indicas tu DNI para ver el financiamiento?"
REENGANCHE = (
    "¡Hola de nuevo! 👋 Sigo por aquí si tienes alguna otra pregunta o quieres "
    "retomar donde quedamos. Cuéntame en qué te puedo ayudar 😊"
)

_contador = {"i": 0}


@pytest.fixture(autouse=True)
def _cache_limpia():
    sc.limpiar_cache()
    sc._avisos_degradacion.clear()
    yield
    sc.limpiar_cache()


def _tel():
    _contador["i"] += 1
    return f"5198720{_contador['i']:04d}"


async def _poner_hora(mensaje_id, instante):
    async with mem.async_session() as s:
        m = await s.get(mem.Mensaje, mensaje_id)
        m.timestamp = instante
        await s.commit()


async def _conv(
    negocio, canal, guion, *, telefono=None, ahora=None, origen="meta_ads", referral=None, campana_origen=None,
    nombre="Ana", **campos_lead,
):
    """Una conversación con su lead y su atribución. `guion`: lista de (role, texto, minutos_atras[, kwargs de guardar_mensaje])."""
    nid = negocio["id"]
    telefono = telefono or _tel()
    ahora = ahora or datetime.utcnow()
    conversation, _ = await mem.resolver_conversation_activa(telefono, nid, canal["id"])
    await mem.actualizar_lead(
        telefono, negocio_id=nid, nombre=nombre, producto_tipo="terma", paso_flujo="comparando_producto",
        numero_whatsapp_id=canal["phone_number_id"], **campos_lead,
    )
    if campana_origen:
        async with mem.async_session() as s:
            lead = await s.get(mem.Lead, telefono)
            lead.campana_origen = campana_origen
            await s.commit()
    if origen:
        await mem.registrar_attribution_event(telefono, origen, referral=referral)
    for item in guion:
        role, texto, minutos_atras, *extra = item
        guardado = await mem.guardar_mensaje(telefono, role, texto, nid, **(extra[0] if extra else {}))
        await _poner_hora(guardado["id"], ahora - timedelta(minutes=minutos_atras))
    return conversation, telefono


def _solo_clic(minutos=31, texto="hola", gabi=GABI_SALUDO):
    """Guion mínimo de «solo clic»: el cliente manda el saludo y Gabi responde 7 s después; `minutos` = hace cuánto."""
    return [("user", texto, minutos), ("assistant", gabi, minutos - 7 / 60)]


async def _mensaje_en(negocio, telefono, role, texto, instante, **kw):
    guardado = await mem.guardar_mensaje(telefono, role, texto, negocio["id"], **kw)
    await _poner_hora(guardado["id"], instante)


async def _veredicto(negocio, conversation, **kw):
    ctx = await sc.contexto_de_negocio(negocio["id"])
    async with mem.async_session() as s:
        conv = await s.get(mem.Conversation, conversation.id)
        return await sc.evaluar_conversacion(s, conv, ctx, **kw)


async def _tocar(modelo, clave, **campos):
    async with mem.async_session() as s:
        fila = await s.get(modelo, clave)
        for k, v in campos.items():
            setattr(fila, k, v)
        await s.commit()


async def _eventos_sc(tipo=None, negocio_id=None):
    tipos = (tipo,) if tipo else mem.TIPOS_EVENTO_EXP_SOLO_CLIC
    async with mem.async_session() as s:
        q = select(mem.EventoLead).where(mem.EventoLead.tipo.in_(tipos)).order_by(mem.EventoLead.id)
        if negocio_id:
            q = q.where(mem.EventoLead.negocio_id == negocio_id)
        return (await s.execute(q)).scalars().all()


async def _sombra(negocio, **claves):
    await _cfg(negocio, **{sc.CLAVE_MODO: "sombra", **claves})


# ── Configuración ────────────────────────────────────────────────────────────────────────────────────────

async def test_por_defecto_el_experimento_esta_apagado_con_los_defaults_aprobados():
    negocio, _ = await _negocio("sc-cfg1")
    config = await sc.leer_config(negocio["id"])
    assert config.modo == "apagado" and config.modo_configurado == "apagado"
    assert (config.epoca, config.pct_c, config.pct_t1, config.pct_t2, config.pct_t3) == ("v1", 40.0, 20.0, 40.0, 0.0)
    assert (config.cohorte_min, config.toque_min, config.oferta_min, config.ventana_max_horas, config.max_intentos) == (20, 20, 60, 22.0, 2)
    assert await sc.modo_efectivo(negocio["id"]) == "apagado"
    assert (await sc.estado_configuracion(negocio["id"]))["pct_t3_bloqueada"] is True


@pytest.mark.parametrize("valor,esperado", [("sombra", "sombra"), (" SOMBRA ", "sombra"), ("apagado", "apagado"), ("xyz", "apagado"), ("", "apagado"), ("1", "apagado")])
async def test_el_modo_se_lee_con_tolerancia_y_un_valor_raro_es_apagado(valor, esperado):
    negocio, _ = await _negocio("sc-cfg2")
    await _cfg(negocio, **{sc.CLAVE_MODO: valor})
    assert await sc.modo_efectivo(negocio["id"]) == esperado


async def test_activo_esta_reservado_y_opera_como_sombra_con_un_aviso_en_el_log(caplog):
    negocio, _ = await _negocio("sc-cfg3")
    await _cfg(negocio, **{sc.CLAVE_MODO: "activo"})
    with caplog.at_level(logging.WARNING, logger="agentkit"):
        config = await sc.leer_config(negocio["id"])
    assert config.modo_configurado == "activo" and config.modo == "sombra" and config.motivo_degradado == "fase_c_no_construida"
    assert any("RESERVADO" in r.getMessage() and "SOMBRA" in r.getMessage() for r in caplog.records)
    assert await sc.modo_efectivo(negocio["id"]) == "sombra"


async def test_pct_t3_esta_bloqueada_aunque_alguien_la_guarde_en_la_base():
    negocio, _ = await _negocio("sc-cfg4")
    await _sombra(negocio, **{sc.CLAVE_PCT_T3: "50"})
    config = await sc.leer_config(negocio["id"])
    assert config.pct_t3 == 0.0 and "T3" not in sc.BRAZOS
    with pytest.raises(ValueError, match="BLOQUEADA"):
        await sc.guardar_cambios(negocio["id"], {"pct_t3": 10})


async def test_valores_fuera_de_rango_se_ajustan_y_los_no_numericos_caen_al_default():
    negocio, _ = await _negocio("sc-cfg5")
    await _sombra(negocio, **{sc.CLAVE_COHORTE_MIN: "9999", sc.CLAVE_TOQUE_MIN: "abc", sc.CLAVE_VENTANA_MAX_HORAS: "30", sc.CLAVE_MAX_INTENTOS: "0", sc.CLAVE_EPOCA: "no valida!"})
    config = await sc.leer_config(negocio["id"])
    assert config.cohorte_min == 120 and config.toque_min == 20 and config.ventana_max_horas == 23.5 and config.max_intentos == 1
    assert config.epoca == "v1"
    await _sombra(negocio, **{sc.CLAVE_COHORTE_MIN: "90", sc.CLAVE_OFERTA_MIN: "30"})
    assert (await sc.leer_config(negocio["id"])).oferta_min == 90          # la oferta nunca es antes de la cohorte


async def test_guardar_cambios_valida_todo_o_nada_y_es_por_negocio():
    a, _ = await _negocio("sc-cfg6a")
    b, _ = await _negocio("sc-cfg6b")
    estado = await sc.guardar_cambios(a["id"], {"modo": "sombra", "epoca": "v2", "pct_c": 50, "pct_t1": 25, "pct_t2": 25, "cohorte_min": 25})
    assert estado["modo_efectivo"] == "sombra" and estado["epoca"] == "v2" and estado["pct_c"] == 50.0 and estado["cohorte_min"] == 25
    with pytest.raises(ValueError):
        await sc.guardar_cambios(a["id"], {"modo": "apagado", "cohorte_min": 1})
    assert (await sc.estado_configuracion(a["id"]))["modo"] == "sombra"        # nada se guardó
    assert (await sc.estado_configuracion(b["id"]))["modo"] == "apagado"


# ── Prellenados frecuentes ───────────────────────────────────────────────────────────────────────────────

async def _n_conversaciones(negocio, canal, texto, n, **kw):
    for _ in range(n):
        await _conv(negocio, canal, _solo_clic(60, texto), **kw)


async def test_un_texto_en_5_conversaciones_distintas_es_prellenado_conocido_y_con_4_no():
    negocio, canal = await _negocio("sc-frec1")
    await _n_conversaciones(negocio, canal, PRELLENADO, 4)
    ctx = await sc.contexto_de_negocio(negocio["id"])
    assert sc.normalizar_texto(PRELLENADO) not in ctx.textos_conocidos
    sc.limpiar_cache()
    await _n_conversaciones(negocio, canal, PRELLENADO, 1)
    ctx = await sc.contexto_de_negocio(negocio["id"])
    assert sc.normalizar_texto(PRELLENADO) in ctx.textos_conocidos
    conteo = await sc.conteo_prellenados(negocio["id"])
    assert conteo[sc.normalizar_texto(PRELLENADO)] == 5


async def test_las_variantes_de_mayusculas_tildes_y_espacios_suman_al_mismo_prellenado():
    negocio, canal = await _negocio("sc-frec2")
    variantes = [PRELLENADO, PRELLENADO.upper(), "hola, quiero mas informacion de este producto", "Hola,  quiero más información de este   producto ", PRELLENADO.lower()]
    for texto in variantes:
        await _conv(negocio, canal, _solo_clic(60, texto))
    assert sc.normalizar_texto(PRELLENADO) in (await sc.contexto_de_negocio(negocio["id"])).textos_conocidos


async def test_el_texto_de_un_mismo_cliente_repetido_no_cuenta_varias_veces():
    negocio, canal = await _negocio("sc-frec3")
    guion = [("user", PRELLENADO, 120), ("assistant", GABI_SALUDO, 119.9)] + [("user", PRELLENADO, 100 - i) for i in range(6)]
    await _conv(negocio, canal, guion)
    assert (await sc.conteo_prellenados(negocio["id"]))[sc.normalizar_texto(PRELLENADO)] == 1


async def test_los_organicos_sin_origen_prellenado_no_cuentan_para_la_frecuencia():
    negocio, canal = await _negocio("sc-frec4")
    await _n_conversaciones(negocio, canal, "precio de la terma", 6, origen=None)
    assert "precio de la terma" not in (await sc.contexto_de_negocio(negocio["id"])).textos_conocidos


async def test_solo_cuenta_el_primer_mensaje_de_cada_conversacion_y_solo_texto():
    negocio, canal = await _negocio("sc-frec5")
    for _ in range(6):
        await _conv(negocio, canal, [("user", "hola", 60), ("assistant", GABI_SALUDO, 59.9), ("user", "quiero el gasfitero", 50)])
    for _ in range(6):
        await _conv(negocio, canal, [("user", "[audio]", 60), ("assistant", GABI_SALUDO, 59.9)])
    conocidos = (await sc.contexto_de_negocio(negocio["id"])).textos_conocidos
    assert "quiero el gasfitero" not in conocidos and "[audio]" not in conocidos and "hola" in conocidos


async def test_el_texto_de_saludo_de_una_campana_es_prellenado_conocido():
    negocio, canal = await _negocio("sc-frec6")
    await mem.crear_campana("Termas octubre", "texto_saludo", "termas octubre", texto_saludo="Hola, vi su promo de termas de octubre", negocio_id=negocio["id"])
    conversation, _ = await _conv(negocio, canal, _solo_clic(60, "Hola, vi su promo de termas de OCTUBRE"))
    v = await _veredicto(negocio, conversation)
    assert v.es_solo_clic and v.tipo_primer_turno == "prellenado_conocido"


async def test_el_body_y_el_headline_del_referral_de_la_conversacion_cuentan_como_prellenado():
    negocio, canal = await _negocio("sc-frec7")
    referral = {"source_id": "ad1", "body": "Calentador al mejor precio, escríbenos", "headline": "Termas Gaso+"}
    conversation, _ = await _conv(negocio, canal, _solo_clic(60, "Termas Gaso+"), referral=referral)
    assert (await _veredicto(negocio, conversation)).es_solo_clic
    # ese referral no vale para OTRA conversación sin él
    otra, _ = await _conv(negocio, canal, _solo_clic(60, "Termas Gaso+"), referral={"source_id": "ad2"})
    assert (await _veredicto(negocio, otra)).motivo == "primer_turno_no_prellenado"


async def test_los_prellenados_frecuentes_no_se_filtran_entre_negocios():
    a, canal_a = await _negocio("sc-frec8a")
    b, canal_b = await _negocio("sc-frec8b")
    await _n_conversaciones(a, canal_a, PRELLENADO, 5)
    assert sc.normalizar_texto(PRELLENADO) in (await sc.contexto_de_negocio(a["id"])).textos_conocidos
    assert sc.normalizar_texto(PRELLENADO) not in (await sc.contexto_de_negocio(b["id"])).textos_conocidos
    conversation, _ = await _conv(b, canal_b, _solo_clic(60, PRELLENADO))
    assert (await _veredicto(b, conversation)).motivo == "primer_turno_no_prellenado"


async def test_la_agregacion_de_prellenados_se_cachea():
    negocio, canal = await _negocio("sc-frec9")
    await _n_conversaciones(negocio, canal, PRELLENADO, 5)
    primero = await sc.conteo_prellenados(negocio["id"])
    contadas = []

    @event.listens_for(mem.engine.sync_engine, "before_cursor_execute")
    def _contar(conn, cursor, statement, *a):
        contadas.append(statement)
    try:
        segundo = await sc.conteo_prellenados(negocio["id"])
    finally:
        event.remove(mem.engine.sync_engine, "before_cursor_execute", _contar)
    assert segundo == primero and contadas == []


# ── La definición sobre datos reales ─────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("origen", ["meta_ads", "meta_ads_no_resuelto", "wa_link"])
async def test_los_tres_origenes_con_texto_prellenado_cuentan(origen):
    negocio, canal = await _negocio("sc-def1")
    conversation, _ = await _conv(negocio, canal, _solo_clic(), origen=origen)
    v = await _veredicto(negocio, conversation)
    assert v.es_solo_clic and v.tipo_primer_turno == "saludo"


@pytest.mark.parametrize("origen", [None, "organico", "otro"])
async def test_sin_origen_prellenado_el_hola_a_mano_queda_fuera(origen):
    negocio, canal = await _negocio("sc-def2")
    conversation, _ = await _conv(negocio, canal, _solo_clic(), origen=origen)
    assert (await _veredicto(negocio, conversation)).motivo == "sin_origen_prellenado"


async def test_lead_campana_origen_basta_como_origen():
    negocio, canal = await _negocio("sc-def3")
    conversation, _ = await _conv(negocio, canal, _solo_clic(), origen=None, campana_origen="Termas octubre")
    assert (await _veredicto(negocio, conversation)).es_solo_clic


async def test_formulario_meta_queda_fuera():
    negocio, canal = await _negocio("sc-def4")
    conversation, tel = await _conv(negocio, canal, _solo_clic())
    await _tocar(mem.Lead, tel, origen_contacto="formulario_meta")
    assert (await _veredicto(negocio, conversation)).motivo == "origen_formulario"


async def test_cada_exclusion_previa_se_aplica_sobre_datos_reales():
    negocio, canal = await _negocio("sc-def5")
    casos = {}

    async def nuevo(clave, **kw):
        casos[clave] = await _conv(negocio, canal, _solo_clic(), **kw)
        return casos[clave]

    conv, tel = await nuevo("no_llamar")
    async with mem.async_session() as s:
        contacto = (await s.execute(select(mem.Contact).where(mem.Contact.negocio_id == negocio["id"], mem.Contact.telefono == tel))).scalar_one()
        contacto.no_llamar_en = datetime.utcnow()
        await s.commit()
    conv, tel = await nuevo("triaje")
    async with mem.async_session() as s:
        s.add(mem.EventoLead(conversation_id=conv.id, negocio_id=negocio["id"], tipo=mem.EVENTO_TRIAJE_ATC_CERRADO, descripcion="x"))
        await s.commit()
    conv, tel = await nuevo("asesor")
    await _tocar(mem.Lead, tel, asesor_asignado="ana")
    conv, tel = await nuevo("pausa")
    await _tocar(mem.Conversation, conv.id, pausado_manual=True)
    conv, tel = await nuevo("escalado")
    await _tocar(mem.Lead, tel, escalado_supervision_en=datetime.utcnow())
    conv, tel = await nuevo("derivado")
    await _tocar(mem.Lead, tel, paso_flujo="derivado_asesor")
    conv, tel = await nuevo("cerrada")
    await _tocar(mem.Conversation, conv.id, cerrado_definitivamente_en=datetime.utcnow() - timedelta(minutes=40))
    conv, tel = await nuevo("resultado")
    await _tocar(mem.Lead, tel, resultado="vendido")
    conv, tel = await nuevo("humano", telefono=None)
    await _mensaje_en(negocio, tel, "assistant", "te escribo desde el celular", datetime.utcnow() - timedelta(minutes=29), via_app=True)
    conv, tel = await nuevo("asesor_msg")
    await _mensaje_en(negocio, tel, "asesor", "Hola, soy Luis", datetime.utcnow() - timedelta(minutes=29))
    await nuevo("bsuid", telefono="US.13491208655302741918")
    await nuevo("extranjero", telefono="14155550123")
    conv, tel = await nuevo("excluido")
    await _cfg(negocio, **{"triaje_atc_telefonos_excluidos": f"51999000000, +{tel[:2]} {tel[2:]}"})
    conv, tel = await nuevo("pruebas")
    esperados = {
        "no_llamar": "no_llamar", "triaje": "triaje_atc", "asesor": "asesor", "pausa": "pausa", "escalado": "escalado",
        "derivado": "derivado", "cerrada": "conversacion_cerrada", "resultado": "con_resultado", "humano": "humano",
        "asesor_msg": "humano", "bsuid": "telefono_no_peruano", "extranjero": "telefono_no_peruano", "excluido": "numero_interno",
    }
    for clave, motivo in esperados.items():
        assert (await _veredicto(negocio, casos[clave][0])).motivo == motivo, clave
    # un canal en modo pruebas también es «número interno»
    canal_pruebas = await mem.crear_canal_whatsapp(nombre="Pruebas", phone_number_id="409800099", negocio_id=negocio["id"], modo="pruebas")
    conversation, _ = await _conv(negocio, canal_pruebas, _solo_clic())
    assert (await _veredicto(negocio, conversation)).motivo == "numero_interno"


async def test_ciclo_reabierto_y_cierre_posterior_a_la_cohorte():
    negocio, canal = await _negocio("sc-def6")
    conversation, tel = await _conv(negocio, canal, _solo_clic(120))
    async with mem.async_session() as s:
        s.add(mem.Conversation(
            negocio_id=negocio["id"], contact_id=conversation.contact_id, canal_id=canal["id"], estado="cerrada",
            creado=datetime.utcnow() - timedelta(days=20),
        ))
        await s.commit()
    assert (await _veredicto(negocio, conversation)).motivo == "ciclo_reabierto"
    # un cierre definitivo POSTERIOR al T+20 no descalifica cuando se evalúa «como estaba a T+20», pero sí hoy
    otra, tel2 = await _conv(negocio, canal, _solo_clic(120))
    await _tocar(mem.Conversation, otra.id, cerrado_definitivamente_en=datetime.utcnow() - timedelta(minutes=10))
    assert (await _veredicto(negocio, otra, cohorte_min=20)).es_solo_clic
    assert (await _veredicto(negocio, otra)).motivo == "conversacion_cerrada"


async def test_el_cierre_automatico_sin_respuesta_no_saca_a_nadie_del_universo():
    negocio, canal = await _negocio("sc-def7")
    conversation, tel = await _conv(negocio, canal, _solo_clic(60 * 20))
    await _tocar(mem.Lead, tel, resultado="sin_respuesta")
    assert (await _veredicto(negocio, conversation)).es_solo_clic


async def test_el_cliente_que_escribe_despues_deja_de_ser_solo_clic():
    negocio, canal = await _negocio("sc-def8")
    for extra in ("gracias", "[audio]", "[image]", "[sticker]", "Reaccionó con 👍"):
        conversation, _ = await _conv(negocio, canal, _solo_clic(60) + [("user", extra, 40)])
        assert (await _veredicto(negocio, conversation)).motivo == "cliente_interactuo", extra


async def test_cliente_que_edita_el_prellenado_y_escribe_una_pregunta_real():
    negocio, canal = await _negocio("sc-def9")
    await _n_conversaciones(negocio, canal, PRELLENADO, 5)
    conversation, _ = await _conv(negocio, canal, _solo_clic(60, PRELLENADO + ", ¿tienen cocinas de 4 hornillas?"))
    assert (await _veredicto(negocio, conversation)).motivo == "primer_turno_no_prellenado"
    ok, _ = await _conv(negocio, canal, _solo_clic(60, PRELLENADO))
    assert (await _veredicto(negocio, ok)).tipo_primer_turno == "prellenado_conocido"


async def test_audio_o_imagen_como_primer_turno_no_son_solo_clic():
    negocio, canal = await _negocio("sc-def10")
    for contenido in ("[audio]", "[image]", "[sticker]", "Reaccionó con ❤️"):
        conversation, _ = await _conv(negocio, canal, _solo_clic(60, contenido))
        assert (await _veredicto(negocio, conversation)).motivo == "primer_turno_no_texto", contenido


async def test_envio_caido_y_falla_de_ia():
    negocio, canal = await _negocio("sc-def11")
    caido, _ = await _conv(negocio, canal, [("user", "hola", 60), ("assistant", GABI_SALUDO, 59.9, {"estado_envio": "fallido"})])
    assert (await _veredicto(negocio, caido)).motivo == "envio_caido"
    error, _ = await _conv(negocio, canal, [("user", "hola", 60), ("assistant", "Uy, estoy teniendo un problema técnico. Intenta de nuevo en unos minutos.", 59.9)])
    assert (await _veredicto(negocio, error)).motivo == "falla_ia"


async def test_aislamiento_la_evaluacion_de_una_conversacion_ajena_no_se_cuela():
    a, canal_a = await _negocio("sc-def12a")
    b, _ = await _negocio("sc-def12b")
    conversation, _ = await _conv(a, canal_a, _solo_clic())
    assert await sc.es_solo_clic_conversacion(conversation.id, a["id"]) is True
    assert await sc.es_solo_clic_conversacion(conversation.id, b["id"]) is False       # otro negocio: no existe para él
    assert await sc.es_solo_clic_conversacion("no-existe", a["id"]) is False


# ── EXCLUSIÓN en «Para llamar» ───────────────────────────────────────────────────────────────────────────

def _con_puntaje_alto(horas=6):
    """Solo clic cuyo puntaje en «Para llamar» llega a 9 solo por lo que DIJO Gabi (precio + financiamiento): el atajo."""
    m = horas * 60
    return [("user", "hola", m), ("assistant", GABI_PRECIO, m - 7 / 60)]


async def _encender_llamadas(negocio, modo="sombra"):
    from tests.test_llamadas_flujo import _activar, _encender
    if modo == "activo":
        await _activar(negocio)
    else:
        await _encender(negocio, modo)


async def test_con_el_experimento_apagado_el_modulo_de_llamadas_es_identico(monkeypatch):
    negocio, canal = await _negocio("sc-exc1")
    await _conv(negocio, canal, _con_puntaje_alto())
    await _encender_llamadas(negocio, "sombra")

    async def prohibido(*a, **k):
        raise AssertionError("con sc_exp_modo apagado no se debe evaluar «solo clic»")
    monkeypatch.setattr(sc, "es_solo_clic_conversacion", prohibido)
    monkeypatch.setattr(sc, "contexto_de_negocio", prohibido)
    resumen = await ll.procesar_negocio(negocio["id"])
    assert resumen["creacion"]["creadas"] == 1 and "solo_clic_en_experimento" not in resumen["creacion"]["por_motivo"]
    (tarea,) = await _tareas()
    assert tarea.segmento == "A" and tarea.puntaje == 9
    assert await _eventos_sc() == []


async def test_con_apagado_explicito_o_basura_el_resultado_es_el_mismo():
    for valor in ("apagado", "xyz", ""):
        negocio, canal = await _negocio(f"sc-exc2-{valor or 'vacio'}")
        await _conv(negocio, canal, _con_puntaje_alto())
        await _encender_llamadas(negocio, "sombra")
        await _cfg(negocio, **{sc.CLAVE_MODO: valor})
        resumen = await ll.procesar_negocio(negocio["id"])
        assert resumen["creacion"]["creadas"] == 1, valor


@pytest.mark.parametrize("modo_sc", ["sombra", "activo"])
async def test_con_el_experimento_encendido_un_solo_clic_no_genera_tarea(modo_sc):
    negocio, canal = await _negocio(f"sc-exc3-{modo_sc}")
    await _conv(negocio, canal, _con_puntaje_alto())
    await _encender_llamadas(negocio, "sombra")
    await _cfg(negocio, **{sc.CLAVE_MODO: modo_sc})
    resumen = await ll.procesar_negocio(negocio["id"])
    assert resumen["creacion"]["creadas"] == 0 and resumen["creacion"]["por_motivo"] == {"solo_clic_en_experimento": 1}
    assert await _tareas() == []


async def test_con_llamadas_en_modo_activo_ningun_solo_clic_se_llama_sin_un_si():
    negocio, canal = await _negocio("sc-exc4")
    await _conv(negocio, canal, _con_puntaje_alto())
    await _encender_llamadas(negocio, "activo")
    await _cfg(negocio, **{sc.CLAVE_MODO: "sombra"})
    assert await ll.modo_efectivo(negocio["id"]) == "activo"
    await ll.procesar_negocio(negocio["id"])
    assert await _tareas() == []


async def test_un_lead_que_si_escribio_algo_propio_sigue_su_camino_con_el_experimento_encendido():
    negocio, canal = await _negocio("sc-exc5")
    guion = _con_puntaje_alto() + [("user", "¿cuánto sale la cuota mensual?", 300), ("assistant", "Depende del plazo.", 299.9)]
    await _conv(negocio, canal, guion)
    await _encender_llamadas(negocio, "sombra")
    await _cfg(negocio, **{sc.CLAVE_MODO: "sombra"})
    resumen = await ll.procesar_negocio(negocio["id"])
    assert resumen["creacion"]["creadas"] == 1 and "solo_clic_en_experimento" not in resumen["creacion"]["por_motivo"]


async def test_si_la_comprobacion_falla_con_el_experimento_encendido_el_lead_se_omite(monkeypatch):
    negocio, canal = await _negocio("sc-exc6")
    await _conv(negocio, canal, _con_puntaje_alto())
    await _encender_llamadas(negocio, "sombra")
    await _cfg(negocio, **{sc.CLAVE_MODO: "sombra"})

    async def falla(*a, **k):
        raise RuntimeError("base caída")
    monkeypatch.setattr(sc, "es_solo_clic_conversacion", falla)
    resumen = await ll.procesar_negocio(negocio["id"])
    assert resumen["creacion"]["creadas"] == 0 and resumen["creacion"]["por_motivo"] == {"solo_clic_error": 1}
    assert await _tareas() == []


async def test_la_exclusion_es_por_negocio():
    a, canal_a = await _negocio("sc-exc7a")
    b, canal_b = await _negocio("sc-exc7b")
    await _conv(a, canal_a, _con_puntaje_alto())
    await _conv(b, canal_b, _con_puntaje_alto())
    for n in (a, b):
        await _encender_llamadas(n, "sombra")
    await _cfg(a, **{sc.CLAVE_MODO: "sombra"})            # solo A tiene el experimento
    await ll.procesar_negocio(a["id"])
    await ll.procesar_negocio(b["id"])
    assert await _tareas(a["id"]) == [] and len(await _tareas(b["id"])) == 1


# ── La SOMBRA ────────────────────────────────────────────────────────────────────────────────────────────

async def test_con_el_experimento_apagado_la_sombra_no_hace_nada():
    negocio, canal = await _negocio("sc-som1")
    await _conv(negocio, canal, _solo_clic())
    assert await sc.procesar_negocio(negocio["id"]) == {"modo": "apagado"}
    assert await sc.ejecutar_sombra() == {negocio["id"]: {"modo": "apagado"}}
    assert await _eventos_sc() == []


async def test_la_sombra_registra_brazo_accion_y_demas_campos():
    negocio, canal = await _negocio("sc-som2")
    await _sombra(negocio)
    ahora = datetime.utcnow()
    conversation, tel = await _conv(negocio, canal, _solo_clic(31), ahora=ahora)
    resumen = await sc.procesar_negocio(negocio["id"], ahora)
    assert resumen["modo"] == "sombra" and resumen["cohorte"]["registradas"] == 1
    (evento,) = await _eventos_sc(mem.EVENTO_EXP_SOLO_CLIC_SOMBRA)
    p = evento.payload
    assert evento.negocio_id == negocio["id"] and evento.conversation_id == conversation.id and evento.autor is None
    assert p["epoca"] == "v1" and p["brazo"] == sc.brazo_de(conversation.id, "v1") and p["brazo"] in ("C", "T1", "T2")
    assert p["accion_habria"] in ("control_2h", "toque_20", "oferta_60")
    for clave in ("hora_real_evaluacion", "cayo_en_horario_a_T60", "ventana_cierra_antes_de_apertura", "minutos_desde_gabi", "primer_gabi_en", "ancla_en", "oferta_hipotetica"):
        assert clave in p, clave
    assert p["cayo_en_horario_a_T60"] is True and p["ventana_cierra_antes_de_apertura"] is False       # el negocio de prueba siempre abre
    assert 30 < p["minutos_desde_gabi"] < 31.5
    assert p["tipo_primer_turno"] == "saludo" and p["modo"] == "sombra" and p["pct"] == {"c": 40.0, "t1": 20.0, "t2": 40.0, "t3": 0.0}
    # PII: ni el teléfono ni el texto del cliente van en el evento
    assert tel not in str(p) and tel not in evento.descripcion and "hola" not in str(p).lower().replace("hora_real", "")


async def test_el_evento_es_interno_no_sale_en_el_timeline_y_su_tipo_cabe():
    negocio, canal = await _negocio("sc-som3")
    await _sombra(negocio)
    ahora = datetime.utcnow()
    _, tel = await _conv(negocio, canal, _solo_clic(31), ahora=ahora)
    await sc.procesar_negocio(negocio["id"], ahora)
    assert len(await _eventos_sc()) == 1
    assert [e for e in await mem.listar_eventos_lead(tel) if e["tipo"] in mem.TIPOS_EVENTO_EXP_SOLO_CLIC] == []
    for tipo in mem.TIPOS_EVENTO_EXP_SOLO_CLIC:
        assert tipo in mem.TIPOS_EVENTO_INTERNOS and len(tipo) <= mem.TIPO_EVENTO_LARGO_MAX
    assert mem.EVENTO_EXP_SOLO_CLIC_SOMBRA == "exp_solo_clic_sombra"


async def test_la_sombra_es_idempotente_por_conversacion_y_epoca():
    negocio, canal = await _negocio("sc-som4")
    await _sombra(negocio)
    ahora = datetime.utcnow()
    await _conv(negocio, canal, _solo_clic(31), ahora=ahora)
    primera = await sc.procesar_negocio(negocio["id"], ahora)
    segunda = await sc.procesar_negocio(negocio["id"], ahora + timedelta(minutes=15))
    tercera = await sc.procesar_negocio(negocio["id"], ahora + timedelta(minutes=30))
    assert primera["cohorte"]["registradas"] == 1 and segunda["cohorte"].get("registradas", 0) == 0 and tercera["cohorte"].get("registradas", 0) == 0
    assert len(await _eventos_sc(mem.EVENTO_EXP_SOLO_CLIC_SOMBRA)) == 1
    # una época nueva abre una cohorte nueva (y re-asigna brazos)
    await _cfg(negocio, **{sc.CLAVE_EPOCA: "v2"})
    cuarta = await sc.procesar_negocio(negocio["id"], ahora + timedelta(minutes=35))
    assert cuarta["cohorte"]["registradas"] == 1
    assert sorted(e.payload["epoca"] for e in await _eventos_sc(mem.EVENTO_EXP_SOLO_CLIC_SOMBRA)) == ["v1", "v2"]


async def test_solo_se_evalua_en_la_ventana_de_la_cohorte():
    negocio, canal = await _negocio("sc-som5")
    await _sombra(negocio)
    ahora = datetime.utcnow()
    await _conv(negocio, canal, _solo_clic(10), ahora=ahora)            # aún no llega a T+20
    await _conv(negocio, canal, _solo_clic(200), ahora=ahora)           # ya pasó demasiado (más de 60 min de retraso)
    await _conv(negocio, canal, _solo_clic(45), ahora=ahora)            # T+45: dentro de la tolerancia
    resumen = await sc.procesar_negocio(negocio["id"], ahora)
    assert resumen["cohorte"]["registradas"] == 1
    (evento,) = await _eventos_sc(mem.EVENTO_EXP_SOLO_CLIC_SOMBRA)
    assert 44 < evento.payload["minutos_desde_gabi"] < 46


async def test_la_cohorte_es_el_silencio_hasta_t_mas_20_no_hasta_que_corra_el_cron():
    negocio, canal = await _negocio("sc-som6")
    await _sombra(negocio)
    ahora = datetime.utcnow()
    tardio, _ = await _conv(negocio, canal, _solo_clic(35) + [("user", "gracias", 5)], ahora=ahora)        # escribió a T+30
    temprano, _ = await _conv(negocio, canal, _solo_clic(35) + [("user", "gracias", 25)], ahora=ahora)     # escribió a T+10
    resumen = await sc.procesar_negocio(negocio["id"], ahora)
    assert resumen["cohorte"]["registradas"] == 1
    (evento,) = await _eventos_sc(mem.EVENTO_EXP_SOLO_CLIC_SOMBRA)
    assert evento.conversation_id == tardio.id
    assert resumen["cohorte"]["descartes"] == {"cliente_interactuo": 1}


async def test_lo_que_no_es_solo_clic_no_se_registra():
    negocio, canal = await _negocio("sc-som7")
    await _sombra(negocio)
    ahora = datetime.utcnow()
    await _conv(negocio, canal, _solo_clic(31, "Quiero una cocina de 4 hornillas"), ahora=ahora)
    await _conv(negocio, canal, _solo_clic(31), ahora=ahora, origen=None)
    await _conv(negocio, canal, [("user", "hola", 31)], ahora=ahora)          # Gabi no respondió
    resumen = await sc.procesar_negocio(negocio["id"], ahora)
    assert resumen["cohorte"].get("registradas", 0) == 0 and await _eventos_sc() == []


@pytest.mark.parametrize("claves,brazo,accion", [
    ({"sc_exp_pct_c": "100", "sc_exp_pct_t1": "0", "sc_exp_pct_t2": "0"}, "C", "control_2h"),
    ({"sc_exp_pct_c": "0", "sc_exp_pct_t1": "100", "sc_exp_pct_t2": "0"}, "T1", "toque_20"),
    ({"sc_exp_pct_c": "0", "sc_exp_pct_t1": "0", "sc_exp_pct_t2": "100"}, "T2", "oferta_60"),
])
async def test_la_accion_hipotetica_sigue_al_brazo(claves, brazo, accion):
    negocio, canal = await _negocio("sc-som8")
    await _sombra(negocio, **claves)
    ahora = datetime.utcnow()
    await _conv(negocio, canal, _solo_clic(31), ahora=ahora)
    await sc.procesar_negocio(negocio["id"], ahora)
    (evento,) = await _eventos_sc(mem.EVENTO_EXP_SOLO_CLIC_SOMBRA)
    assert evento.payload["brazo"] == brazo and evento.payload["accion_habria"] == accion


async def test_fuera_de_horario_la_sombra_lo_registra():
    negocio, canal = await _negocio("sc-som9", horario="cerrado")
    await _sombra(negocio, **{"sc_exp_pct_c": "0", "sc_exp_pct_t1": "0", "sc_exp_pct_t2": "100"})
    ahora = datetime.utcnow()
    await _conv(negocio, canal, _solo_clic(31), ahora=ahora)
    await sc.procesar_negocio(negocio["id"], ahora)
    (evento,) = await _eventos_sc(mem.EVENTO_EXP_SOLO_CLIC_SOMBRA)
    p = evento.payload
    assert p["cayo_en_horario_a_T60"] is False
    assert p["accion_habria"] in ("oferta_60", "omitida_ventana", "omitida_fuera_de_horario")
    if p["accion_habria"] == "oferta_60":
        assert p["oferta_hipotetica"]["diferida"] is True


async def test_la_sombra_no_envia_nada_no_llama_a_meta_ni_crea_tareas(monkeypatch):
    from agent import envios, providers

    llamado = []

    async def prohibido(*a, **k):
        llamado.append(1)
        raise AssertionError("la sombra no puede enviar nada")
    for nombre in ("enviar_texto", "enviar_imagen", "enviar_documento", "enviar_audio", "enviar_plantilla"):
        monkeypatch.setattr(envios, nombre, prohibido)
    monkeypatch.setattr(providers, "obtener_proveedor", lambda *a, **k: (_ for _ in ()).throw(AssertionError("sin proveedor")))

    negocio, canal = await _negocio("sc-som10")
    await _sombra(negocio)
    ahora = datetime.utcnow()
    await _conv(negocio, canal, _solo_clic(31), ahora=ahora)
    async with mem.async_session() as s:
        antes = (await s.execute(select(mem.Mensaje.id))).scalars().all()
    resumen = await sc.procesar_negocio(negocio["id"], ahora)
    assert resumen["cohorte"]["registradas"] == 1 and llamado == []
    async with mem.async_session() as s:
        assert (await s.execute(select(mem.Mensaje.id))).scalars().all() == antes
        assert (await s.execute(select(mem.TareaLlamada.id))).scalars().all() == []
    # y el módulo ni siquiera tiene a mano el envío ni al proveedor
    for prohibida in ("envios", "providers", "obtener_proveedor", "TareaLlamada", "enviar_texto"):
        assert not hasattr(sc, prohibida), prohibida
    fuente = (RAIZ / "agent" / "solo_clic.py").read_text(encoding="utf-8")
    assert not re.search(r"^\s*(from|import)\s+agent(\.\s*|\s+import\s+)(\w+,\s*)*(envios|providers)", fuente, re.M)
    assert not re.search(r"^\s*(from|import)\s+agent\.(envios|providers)", fuente, re.M)


async def test_aislamiento_por_negocio_en_la_sombra():
    a, canal_a = await _negocio("sc-som11a")
    b, canal_b = await _negocio("sc-som11b")
    ahora = datetime.utcnow()
    conv_a, _ = await _conv(a, canal_a, _solo_clic(31), ahora=ahora)
    conv_b, _ = await _conv(b, canal_b, _solo_clic(31), ahora=ahora)
    await _sombra(a)                                                     # solo A tiene la sombra encendida
    resultados = await sc.ejecutar_sombra(ahora)
    assert resultados[a["id"]]["cohorte"]["registradas"] == 1 and resultados[b["id"]] == {"modo": "apagado"}
    assert [e.conversation_id for e in await _eventos_sc()] == [conv_a.id]
    await _sombra(b, **{sc.CLAVE_EPOCA: "b1"})
    await sc.ejecutar_sombra(ahora)
    por_negocio = {e.negocio_id: e.payload["epoca"] for e in await _eventos_sc()}
    assert por_negocio == {a["id"]: "v1", b["id"]: "b1"}


async def test_un_error_en_una_conversacion_no_frena_a_las_demas(monkeypatch):
    negocio, canal = await _negocio("sc-som12")
    await _sombra(negocio)
    ahora = datetime.utcnow()
    await _conv(negocio, canal, _solo_clic(31), ahora=ahora)
    await _conv(negocio, canal, _solo_clic(31), ahora=ahora)
    original = sc.brazo_de
    estado = {"n": 0}

    def inestable(*a, **k):
        estado["n"] += 1
        if estado["n"] == 1:
            raise RuntimeError("boom")
        return original(*a, **k)
    monkeypatch.setattr(sc, "brazo_de", inestable)
    resumen = await sc.procesar_negocio(negocio["id"], ahora)
    assert resumen["cohorte"]["registradas"] == 1 and resumen["cohorte"]["errores"] == 1
    # en la próxima corrida se reintenta la que falló
    monkeypatch.setattr(sc, "brazo_de", original)
    resumen = await sc.procesar_negocio(negocio["id"], ahora + timedelta(minutes=15))
    assert resumen["cohorte"]["registradas"] == 1 and len(await _eventos_sc(mem.EVENTO_EXP_SOLO_CLIC_SOMBRA)) == 2


# ── Desenlace natural a 24 h y 72 h ──────────────────────────────────────────────────────────────────────

async def _sombra_en_el_pasado(negocio, canal, ahora_sim, **kw):
    """Una conversación «solo clic» cuyo primer mensaje de Gabi fue hace 31 min respecto de `ahora_sim`, ya registrada en sombra."""
    conversation, tel = await _conv(negocio, canal, _solo_clic(31), ahora=ahora_sim, **kw)
    await sc.procesar_negocio(negocio["id"], ahora_sim)
    return conversation, tel


async def test_el_desenlace_se_registra_a_las_24_y_72_horas_una_sola_vez():
    negocio, canal = await _negocio("sc-res1")
    await _sombra(negocio)
    t0 = datetime.utcnow() - timedelta(days=6)
    conversation, tel = await _sombra_en_el_pasado(negocio, canal, t0)
    (sombra,) = await _eventos_sc(mem.EVENTO_EXP_SOLO_CLIC_SOMBRA)
    ancla = sc._de_iso(sombra.payload["ancla_en"])
    await _mensaje_en(negocio, tel, "assistant", REENGANCHE, ancla + timedelta(hours=1, minutes=40))
    await _mensaje_en(negocio, tel, "user", "ahora sí, cuánto cuesta", ancla + timedelta(hours=30))

    assert (await sc.procesar_negocio(negocio["id"], ancla + timedelta(hours=23)))["resultados_registrados"] == 0
    assert (await sc.procesar_negocio(negocio["id"], ancla + timedelta(hours=25)))["resultados_registrados"] == 1
    assert (await sc.procesar_negocio(negocio["id"], ancla + timedelta(hours=26)))["resultados_registrados"] == 0      # idempotente
    assert (await sc.procesar_negocio(negocio["id"], ancla + timedelta(hours=73)))["resultados_registrados"] == 1
    assert (await sc.procesar_negocio(negocio["id"], ancla + timedelta(hours=90)))["resultados_registrados"] == 0
    resultados = {e.payload["horizonte_h"]: e.payload for e in await _eventos_sc(mem.EVENTO_EXP_SOLO_CLIC_RESULTADO)}
    assert sorted(resultados) == [24, 72]
    r24, r72 = resultados[24], resultados[72]
    assert r24["respondio"] is False and r24["reenganche_enviado"] is True and r24["horas_hasta_respuesta"] is None
    assert r72["respondio"] is True and r72["respondio_real"] is True and r72["horas_hasta_respuesta"] == 30.0
    assert r72["brazo"] == sombra.payload["brazo"] and r72["epoca"] == "v1" and r72["cerrado_sin_respuesta"] is False
    assert len(mem.EVENTO_EXP_SOLO_CLIC_RESULTADO) <= mem.TIPO_EVENTO_LARGO_MAX
    assert [e for e in await mem.listar_eventos_lead(tel) if e["tipo"] in mem.TIPOS_EVENTO_EXP_SOLO_CLIC] == []
    assert tel not in str([e.payload for e in await _eventos_sc()])


async def test_el_desenlace_distingue_reaccion_cierre_y_humano():
    negocio, canal = await _negocio("sc-res2")
    await _sombra(negocio)
    t0 = datetime.utcnow() - timedelta(days=6)
    conversation, tel = await _sombra_en_el_pasado(negocio, canal, t0)
    (sombra,) = await _eventos_sc(mem.EVENTO_EXP_SOLO_CLIC_SOMBRA)
    ancla = sc._de_iso(sombra.payload["ancla_en"])
    await _mensaje_en(negocio, tel, "user", "Reaccionó con 👍", ancla + timedelta(hours=3))
    async with mem.async_session() as s:
        s.add(mem.EventoLead(
            conversation_id=conversation.id, negocio_id=negocio["id"], tipo="resultado_cambiado", descripcion="cierre",
            payload={"campo": "resultado", "anterior": None, "nuevo": "sin_respuesta"}, creado=ancla + timedelta(hours=15),
        ))
        await s.commit()
    await sc.procesar_negocio(negocio["id"], ancla + timedelta(hours=80))
    r = {e.payload["horizonte_h"]: e.payload for e in await _eventos_sc(mem.EVENTO_EXP_SOLO_CLIC_RESULTADO)}
    assert r[24]["respondio"] is True and r[24]["respondio_real"] is False and r[24]["cerrado_sin_respuesta"] is True
    assert r[72]["horas_hasta_respuesta"] == 3.0


async def test_los_desenlaces_solo_se_registran_para_la_epoca_vigente_y_su_negocio():
    a, canal_a = await _negocio("sc-res3a")
    b, canal_b = await _negocio("sc-res3b")
    for n in (a, b):
        await _sombra(n)
    t0 = datetime.utcnow() - timedelta(days=6)
    await _sombra_en_el_pasado(a, canal_a, t0)
    (sombra,) = await _eventos_sc(mem.EVENTO_EXP_SOLO_CLIC_SOMBRA)
    ancla = sc._de_iso(sombra.payload["ancla_en"])
    await sc.procesar_negocio(b["id"], ancla + timedelta(hours=80))
    assert await _eventos_sc(mem.EVENTO_EXP_SOLO_CLIC_RESULTADO) == []              # el negocio B no ve la sombra de A
    await _cfg(a, **{sc.CLAVE_EPOCA: "v2"})
    await sc.procesar_negocio(a["id"], ancla + timedelta(hours=80))
    assert await _eventos_sc(mem.EVENTO_EXP_SOLO_CLIC_RESULTADO) == []              # otra época: no se mezcla


# ── Scripts ──────────────────────────────────────────────────────────────────────────────────────────────

def _cargar(nombre):
    spec = importlib.util.spec_from_file_location(f"script_{nombre}", RAIZ / "scripts" / f"{nombre}.py")
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


class _Sentencias:
    """Registra las sentencias SQL que se ejecutan (para probar que un script es de SOLO LECTURA)."""

    def __enter__(self):
        self.sentencias = []
        self._f = lambda conn, cursor, statement, *a: self.sentencias.append(statement)
        event.listen(mem.engine.sync_engine, "before_cursor_execute", self._f)
        return self

    def __exit__(self, *a):
        event.remove(mem.engine.sync_engine, "before_cursor_execute", self._f)

    def escrituras(self):
        return [s for s in self.sentencias if re.match(r"\s*(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE)", s, re.I)]


async def _escenario_de_medicion():
    negocio, canal = await _negocio("sc-med")
    ahora = datetime.utcnow()
    telefonos = []
    for _ in range(3):
        _, tel = await _conv(negocio, canal, _con_puntaje_alto(6), ahora=ahora)
        telefonos.append(tel)
    _, tel = await _conv(negocio, canal, _solo_clic(120), ahora=ahora)
    telefonos.append(tel)
    await _conv(negocio, canal, _solo_clic(120, "quiero una terma"), ahora=ahora)                    # no es solo clic
    await _conv(negocio, canal, _solo_clic(120), ahora=ahora, origen=None)                           # orgánico
    return negocio, ahora, telefonos


async def test_la_medicion_solo_clic_es_de_solo_lectura_y_sin_pii():
    medir = _cargar("medir_candidatos_llamada")
    negocio, ahora, telefonos = await _escenario_de_medicion()
    with _Sentencias() as sentencias:
        resultado = await medir.medir_solo_clic(negocio["id"], 7, 4.0, 4, ahora)
    assert sentencias.escrituras() == []
    assert resultado["evaluadas"] == 6 and resultado["solo_clic"] == 4
    assert resultado["descartes"] == {"primer_turno_no_prellenado": 1, "sin_origen_prellenado": 1}
    assert sum(resultado["semanas"].values()) == 4 and sum(resultado["por_hora_lima"].values()) == 4 and sum(resultado["por_dia_semana"].values()) == 4
    assert resultado["en_horario_t60"] == 4 and resultado["fuera_de_horario_t60"] == 0 and resultado["ventana_cerrada_al_abrir"] == 0
    assert resultado["puntaje_evaluable"] == 3 and resultado["puntaje_pasa"] == 3        # los 3 con 6 h de silencio y precio+financiamiento pasan el atajo (9 ≥ 4); el de 2 h aún no es evaluable
    texto = medir.formatear_solo_clic(resultado)
    for tel in telefonos:
        assert tel not in texto
    assert "Ana" not in texto and "AVISO" not in texto.replace("AVISO: muestra insuficiente", "") and "muestra insuficiente" in texto   # n = 4 < 10
    assert "Motivos de descarte" in texto and "Por hora de Lima" in texto and "dentro del horario" in texto


async def test_la_medicion_cuenta_los_prellenados_frecuentes_solo_como_texto_repetido():
    medir = _cargar("medir_candidatos_llamada")
    negocio, canal = await _negocio("sc-med2")
    ahora = datetime.utcnow()
    for _ in range(5):
        await _conv(negocio, canal, _solo_clic(120, PRELLENADO), ahora=ahora)
    await _conv(negocio, canal, _solo_clic(120, "mi dni es 45678912 quiero info"), ahora=ahora)
    resultado = await medir.medir_solo_clic(negocio["id"], 7, 4.0, 4, ahora)
    assert resultado["prellenados_frecuentes"] == [(sc.normalizar_texto(PRELLENADO), 5)]
    assert resultado["prellenados_otros_distintos"] == 1
    assert "45678912" not in medir.formatear_solo_clic(resultado)
    assert medir._texto_seguro("llámame al 987654321 ya") == "llámame al # ya"


async def test_la_medicion_fuera_de_horario_y_ventana_cerrada():
    medir = _cargar("medir_candidatos_llamada")
    negocio, canal = await _negocio("sc-med3", horario="cerrado")
    ahora = datetime.utcnow()
    await _conv(negocio, canal, _solo_clic(120), ahora=ahora)
    resultado = await medir.medir_solo_clic(negocio["id"], 7, 4.0, 4, ahora)
    assert resultado["solo_clic"] == 1 and resultado["en_horario_t60"] == 0 and resultado["fuera_de_horario_t60"] == 1


async def test_la_medicion_aun_no_cumple_la_cohorte_no_se_cuenta():
    medir = _cargar("medir_candidatos_llamada")
    negocio, canal = await _negocio("sc-med4")
    ahora = datetime.utcnow()
    await _conv(negocio, canal, _solo_clic(10), ahora=ahora)
    resultado = await medir.medir_solo_clic(negocio["id"], 7, 4.0, 4, ahora)
    assert resultado["solo_clic"] == 0 and resultado["descartes"] == {"aun_no_cumple_la_cohorte": 1}


async def test_main_de_medicion_con_la_bandera_solo_clic(capsys):
    medir = _cargar("medir_candidatos_llamada")
    negocio, ahora, _ = await _escenario_de_medicion()
    resultado = await medir.main(["--solo-clic", "--negocio-id", negocio["id"], "--dias", "7"])
    assert resultado["solo_clic"] == 4
    assert "«solo clic»" in capsys.readouterr().out
    # sin la bandera sigue siendo la medición de siempre
    antiguo = await medir.main(["--negocio-id", negocio["id"], "--dias", "7"])
    assert "semanas" in antiguo and "solo_clic" not in antiguo


async def test_el_analisis_es_de_solo_lectura_sin_pii_y_avisa_de_muestra_insuficiente():
    analizar = _cargar("analizar_solo_clic")
    negocio, canal = await _negocio("sc-ana")
    await _sombra(negocio)
    t0 = datetime.utcnow() - timedelta(days=6)
    telefonos, convs = [], []
    for i in range(6):
        conversation, tel = await _conv(negocio, canal, _solo_clic(31), ahora=t0)
        telefonos.append(tel)
        convs.append(conversation.id)
    await sc.procesar_negocio(negocio["id"], t0)
    eventos = await _eventos_sc(mem.EVENTO_EXP_SOLO_CLIC_SOMBRA)
    assert len(eventos) == 6
    ancla = sc._de_iso(eventos[0].payload["ancla_en"])
    # tres de ellos vuelven a escribir a las 5 h
    for tel in telefonos[:3]:
        await _mensaje_en(negocio, tel, "user", "ya me decidí", ancla + timedelta(hours=5))
    with _Sentencias() as sentencias:
        r = await analizar.analizar(negocio["id"])
    assert sentencias.escrituras() == []
    assert r["cohorte_total"] == 6 and sum(d["cohorte"] for d in r["brazos"].values()) == 6
    assert r["todos_p72"]["n"] == 6 and r["todos_p72"]["k"] == 3 and r["todos_p72"]["insuficiente"] is True
    assert r["todos_p72"]["ic_bajo"] < 0.5 < r["todos_p72"]["ic_alto"]
    assert r["brazos"]["C"]["alcanzable_t60"]["n"] == r["brazos"]["C"]["cohorte"]
    assert sum(sum(c.values()) for c in r["por_semana"].values()) == 6
    texto = analizar.formatear(r)
    assert "muestra insuficiente" in texto and "IC95" in texto and "efecto mínimo detectable" in texto
    for tel in telefonos:
        assert tel not in texto
    for cid in convs:
        assert cid not in texto
    assert r["ritmo_diario"] and r["dias_para_90_por_brazo"]["C"] > 0


async def test_el_analisis_solo_cuenta_horizontes_ya_cumplidos_y_la_epoca_pedida():
    analizar = _cargar("analizar_solo_clic")
    negocio, canal = await _negocio("sc-ana2")
    await _sombra(negocio)
    ahora = datetime.utcnow()
    await _conv(negocio, canal, _solo_clic(31), ahora=ahora)
    await sc.procesar_negocio(negocio["id"], ahora)
    r = await analizar.analizar(negocio["id"])
    assert r["cohorte_total"] == 1 and r["todos_p24"]["n"] == 0 and r["todos_p72"]["n"] == 0        # nada observable todavía
    assert "—" in analizar.formatear(r)
    assert (await analizar.analizar(negocio["id"], epoca="otra"))["cohorte_total"] == 0


async def test_el_analisis_sin_datos_no_falla(capsys):
    analizar = _cargar("analizar_solo_clic")
    negocio, _ = await _negocio("sc-ana3")
    resultado = await analizar.main(["--negocio-id", negocio["id"]])
    assert resultado["cohorte_total"] == 0 and "muestra insuficiente" in capsys.readouterr().out


async def test_configurar_solo_clic_muestra_guarda_y_rechaza_t3(capsys):
    configurar = _cargar("configurar_solo_clic")
    negocio, _ = await _negocio("sc-conf")
    estado = await configurar.main(["--negocio-id", negocio["id"]])
    assert estado["modo_efectivo"] == "apagado" and estado["pct_t3"] == 0.0
    estado = await configurar.main(["--negocio-id", negocio["id"], "--modo", "sombra", "--cohorte-min", "25"])
    assert estado["modo_efectivo"] == "sombra" and estado["cohorte_min"] == 25
    assert await sc.modo_efectivo(negocio["id"]) == "sombra"
    with pytest.raises(ValueError, match="sumar 100"):
        await configurar.main(["--negocio-id", negocio["id"], "--pct-c", "10"])
    with pytest.raises(SystemExit):
        await configurar.main(["--negocio-id", negocio["id"], "--pct-t3", "10"])           # la opción no existe
    estado = await configurar.main(["--negocio-id", negocio["id"], "--modo", "activo"])
    assert estado["modo"] == "activo" and estado["modo_efectivo"] == "sombra"
    assert "RESERVADO" in capsys.readouterr().out
    estado = await configurar.main(["--negocio-id", negocio["id"], "--modo", "apagado"])
    assert estado["modo_efectivo"] == "apagado"


async def test_el_cron_de_tareas_corre_la_sombra_y_un_error_ahi_nunca_lo_rompe(monkeypatch, capsys):
    script = _cargar("crear_tareas_llamada")
    negocio, canal = await _negocio("sc-cron")
    await _sombra(negocio)
    ahora = datetime.utcnow()
    await _conv(negocio, canal, _solo_clic(31), ahora=ahora)
    await script.main()
    salida = capsys.readouterr().out
    assert "Solo clic [sombra]" in salida and "1 conversación(es) registrada(s)" in salida
    assert len(await _eventos_sc(mem.EVENTO_EXP_SOLO_CLIC_SOMBRA)) == 1

    async def rota(*a, **k):
        raise RuntimeError("falla de la sombra")
    monkeypatch.setattr(sc, "ejecutar_sombra", rota)
    await script.main()                                                            # no lanza
    assert "no afecta a las tareas de llamada" in capsys.readouterr().err


async def test_el_cron_con_todo_apagado_imprime_lo_de_siempre(capsys):
    script = _cargar("crear_tareas_llamada")
    await _negocio("sc-cron2")
    await script.main()
    salida = capsys.readouterr().out
    assert "apagadas" in salida and "Solo clic" not in salida
    assert await _eventos_sc() == []
