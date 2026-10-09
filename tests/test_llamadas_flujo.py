# tests/test_llamadas_flujo.py — "Para llamar" (2026-10-09, agent/llamadas.py) contra la base: creación de tareas y sus
# exclusiones, idempotencia, apagado/sombra/activo, compuerta de responsabilidad, horario, reparto, SLA, expiración,
# cancelación por respuesta (hook del webhook y revalidación), el cierre de 15 h y la compatibilidad con los demás Cron.

import os
from datetime import datetime, timedelta

os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")
os.environ.setdefault("WHATSAPP_PROVIDER", "meta")
os.environ["DEBOUNCE_RESPUESTA_SEGUNDOS"] = "0"

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from agent import llamadas as ll
from agent import memory as mem
from tests.test_cierre_cortesia import _correr, _msg, _preparar_webhook

_n = {"i": 0}
TEL = "51987000001"


async def _negocio(codigo: str, horario: str = "abierto"):
    """Un negocio con canal. `horario`: abierto (todos los días 00:00-23:59) | cerrado (00:00-00:01, o sea siempre cerrado)."""
    _n["i"] += 1
    negocio = await mem.crear_negocio(f"Negocio {codigo}", codigo)
    canal = await mem.crear_canal_whatsapp(nombre=f"Canal {codigo}", phone_number_id=f"4098{_n['i']:07d}", negocio_id=negocio["id"])
    await _horario(negocio["id"], horario)
    return negocio, canal


async def _horario(negocio_id: str, horario: str):
    for dia in range(7):
        await mem.guardar_horario_atencion(negocio_id, dia, True, "00:00", "23:59" if horario == "abierto" else "00:01")


async def _cfg(negocio, **claves):
    for clave, valor in claves.items():
        await mem.guardar_configuracion(clave, str(valor), negocio_id=negocio["id"])


async def _encender(negocio, modo="sombra", holdout=0, aceptar=False, **extra):
    """Enciende el módulo. `holdout` 0 = nadie queda en control (salvo que el test lo pida)."""
    await _cfg(negocio, **{ll.CLAVE_GABI_ACTIVO: "1", ll.CLAVE_MODO: modo, ll.CLAVE_HOLDOUT_PCT: holdout}, **{k: v for k, v in extra.items()})
    if aceptar:
        await ll.aceptar_responsabilidad(negocio["id"], "admin", ll.VERSION_TEXTO_RESPONSABILIDAD)


async def _activar(negocio, holdout=0, **extra):
    await _encender(negocio, "activo", holdout, aceptar=True, **extra)


def _guion(horas: float):
    return [
        ("user", "Hola quiero una terma", horas + 0.3),
        ("assistant", "Hola, ¿cómo te llamas?", horas + 0.29),
        ("user", "Soy Ana, la terma de 80 litros", horas),
        ("assistant", "Tiene un precio de S/ 1,200. ¿Me indicas tu DNI para el financiamiento?", horas - 0.01),
    ]


async def _lead(negocio, canal, telefono=TEL, *, horas=6.0, guion=None, nombre="Ana", producto_tipo="terma", paso="comparando_producto", **campos):
    """Un lead callado hace `horas` horas, con guion por defecto de puntaje 12 (segmento A)."""
    nid = negocio["id"]
    conversation, _ = await mem.resolver_conversation_activa(telefono, nid, canal["id"])
    await mem.actualizar_lead(
        telefono, negocio_id=nid, nombre=nombre, producto_tipo=producto_tipo, paso_flujo=paso,
        numero_whatsapp_id=canal["phone_number_id"], **campos,
    )
    ahora = datetime.utcnow()
    for role, texto, hace in (guion if guion is not None else _guion(horas)):
        guardado = await mem.guardar_mensaje(telefono, role, texto, nid)
        async with mem.async_session() as s:
            m = await s.get(mem.Mensaje, guardado["id"])
            m.timestamp = ahora - timedelta(hours=hace)
            await s.commit()
    return conversation


async def _evaluar(telefono=TEL, horas_silencio=4.0):
    async with mem.async_session() as s:
        lead = await s.get(mem.Lead, telefono)
        return await ll.evaluar_lead(s, lead, datetime.utcnow(), horas_silencio)


async def _tareas(negocio_id=None):
    async with mem.async_session() as s:
        q = select(mem.TareaLlamada).order_by(mem.TareaLlamada.creada_en)
        if negocio_id:
            q = q.where(mem.TareaLlamada.negocio_id == negocio_id)
        return (await s.execute(q)).scalars().all()


async def _eventos(tipo=None):
    async with mem.async_session() as s:
        q = select(mem.EventoLead).order_by(mem.EventoLead.id)
        if tipo:
            q = q.where(mem.EventoLead.tipo == tipo)
        return (await s.execute(q)).scalars().all()


async def _asesores(negocio, *nombres):
    for n in nombres:
        await mem.crear_usuario(n, "clave-segura-1", n.capitalize(), "asesor", negocio["id"], nivel="junior")


def _usuario(negocio, username="ana", rol="asesor"):
    return {"username": username, "nombre": username.capitalize(), "rol": rol, "negocio_id": negocio["id"]}


async def _tocar(tarea_id, **campos):
    async with mem.async_session() as s:
        t = await s.get(mem.TareaLlamada, tarea_id)
        for k, v in campos.items():
            setattr(t, k, v)
        await s.commit()


# ── Apagado ──────────────────────────────────────────────────────────────────────────────────────

async def test_apagado_por_defecto_no_ocurre_nada():
    negocio, canal = await _negocio("ll-off")
    await _lead(negocio, canal)
    resumen = await ll.procesar_negocio(negocio["id"])
    assert resumen == {"modo": "apagado"}
    assert await _tareas() == []
    assert await ll.modo_efectivo(negocio["id"]) == "apagado"
    assert (await ll.listar_tareas(negocio["id"], _usuario(negocio, "x", "admin")))["tareas"] == []


async def test_ejecutar_corrida_con_todo_apagado_no_escribe_nada():
    negocio, canal = await _negocio("ll-off2")
    await _lead(negocio, canal)
    resultados = await ll.ejecutar_corrida()
    assert resultados[negocio["id"]] == {"modo": "apagado"}
    assert await _tareas() == [] and await _eventos() == []


@pytest.mark.parametrize("valor", ["0", "", "no", "xyz"])
async def test_un_valor_que_no_es_uno_deja_el_modulo_apagado(valor):
    negocio, canal = await _negocio("ll-off3")
    await _cfg(negocio, **{ll.CLAVE_GABI_ACTIVO: valor, ll.CLAVE_MODO: "activo"})
    assert await ll.modo_efectivo(negocio["id"]) == "apagado"


# ── Sombra ───────────────────────────────────────────────────────────────────────────────────────

async def test_sombra_registra_la_tarea_pero_no_se_muestra_ni_se_asigna():
    negocio, canal = await _negocio("ll-sombra")
    await _asesores(negocio, "ana")
    await _lead(negocio, canal)
    await _encender(negocio, "sombra")
    resumen = await ll.procesar_negocio(negocio["id"])
    assert resumen["modo"] == "sombra" and resumen["creacion"]["creadas"] == 1
    (tarea,) = await _tareas()
    assert tarea.modo == "sombra" and tarea.estado == "pendiente" and tarea.asesor_username is None
    assert tarea.segmento == "A" and tarea.puntaje == 12 and tarea.grupo == "llamar"
    for rol in ("admin", "asesor"):
        vista = await ll.listar_tareas(negocio["id"], _usuario(negocio, "ana", rol))
        assert vista["tareas"] == [] and vista["activo"] is False and vista["modo"] == "sombra"
    datos = await ll.datos_para_inicio(negocio["id"], None)
    assert datos == {"items": [], "pendientes": 0, "vencidas": 0}
    # tampoco se reparte en sombra, aunque haya asesores disponibles
    await ll.procesar_negocio(negocio["id"])
    assert (await _tareas())[0].asesor_username is None


async def test_la_sombra_deja_el_evento_interno_para_medir():
    negocio, canal = await _negocio("ll-sombra2")
    await _lead(negocio, canal)
    await _encender(negocio, "sombra")
    await ll.procesar_negocio(negocio["id"])
    (evento,) = await _eventos(mem.EVENTO_LLAMADA_PENDIENTE_CREADA)
    assert evento.payload["modo"] == "sombra" and evento.payload["segmento"] == "A"
    assert mem.EVENTO_LLAMADA_PENDIENTE_CREADA in mem.TIPOS_EVENTO_INTERNOS
    assert [e for e in await mem.listar_eventos_lead(TEL) if e["tipo"] == mem.EVENTO_LLAMADA_PENDIENTE_CREADA] == []   # no es ruido en el Timeline


async def test_la_sombra_no_cambia_el_cierre_de_15_horas():
    negocio, canal = await _negocio("ll-sombra3")
    await _lead(negocio, canal, horas=16)
    await _encender(negocio, "sombra")
    await ll.procesar_negocio(negocio["id"])
    assert len(await _tareas()) == 1
    _, cierre = await mem.listar_leads_inactividad_cliente()
    assert TEL in {f["telefono"] for f in cierre}


# ── Compuerta de responsabilidad ─────────────────────────────────────────────────────────────────

async def test_activo_sin_aceptacion_se_degrada_a_sombra():
    negocio, canal = await _negocio("ll-gate")
    await _lead(negocio, canal)
    await _encender(negocio, "activo")
    config = await ll.leer_config(negocio["id"])
    assert config.modo_configurado == "activo" and config.modo == "sombra" and config.motivo_degradado == "sin_aceptacion_de_responsabilidad"
    await ll.procesar_negocio(negocio["id"])
    (tarea,) = await _tareas()
    assert tarea.modo == "sombra"
    assert (await ll.listar_tareas(negocio["id"], _usuario(negocio, "x", "admin")))["tareas"] == []


async def test_con_aceptacion_vigente_activo_funciona_y_queda_registrada():
    negocio, canal = await _negocio("ll-gate2")
    await _encender(negocio, "activo")
    aceptacion = await ll.aceptar_responsabilidad(negocio["id"], "angie", "v1")
    assert aceptacion["vigente"] is True and aceptacion["usuario"] == "angie" and aceptacion["version_texto"] == "v1"
    assert (await ll.leer_config(negocio["id"])).modo == "activo"
    async with mem.async_session() as s:
        auditoria = (await s.execute(select(mem.RegistroAuditoria).where(mem.RegistroAuditoria.accion == "llamadas_responsabilidad_aceptada"))).scalars().all()
    assert len(auditoria) == 1 and auditoria[0].actor == "angie" and auditoria[0].payload["texto"] == ll.TEXTO_RESPONSABILIDAD


async def test_aceptar_exige_la_version_vigente_del_texto():
    negocio, _ = await _negocio("ll-gate3")
    with pytest.raises(ll.ErrorLlamada):
        await ll.aceptar_responsabilidad(negocio["id"], "angie", "v0")
    assert (await ll.obtener_aceptacion(negocio["id"]))["vigente"] is False


async def test_una_aceptacion_de_otra_version_no_es_vigente():
    negocio, _ = await _negocio("ll-gate4")
    await _cfg(negocio, **{ll.CLAVE_RESPONSABILIDAD: '{"aceptada":true,"usuario":"a","fecha":"2026-01-01T00:00:00Z","version_texto":"v0"}'})
    assert (await ll.obtener_aceptacion(negocio["id"]))["vigente"] is False


@pytest.mark.parametrize("basura", ["no es json", "[]", "null", '{"aceptada":"true"}', '{"aceptada":1,"version_texto":"v1"}'])
async def test_una_aceptacion_ilegible_o_a_medias_no_vale(basura):
    negocio, _ = await _negocio("ll-gate5")
    await _cfg(negocio, **{ll.CLAVE_RESPONSABILIDAD: basura})
    assert (await ll.obtener_aceptacion(negocio["id"]))["vigente"] is False


async def test_revocar_apaga_el_modo_activo_y_cancela_las_tareas_abiertas():
    negocio, canal = await _negocio("ll-gate6")
    await _asesores(negocio, "ana")
    await _lead(negocio, canal)
    await _activar(negocio)
    await ll.procesar_negocio(negocio["id"])
    (tarea,) = await _tareas()
    assert tarea.modo == "activo" and tarea.asesor_username == "ana"
    aceptacion = await ll.revocar_responsabilidad(negocio["id"], "angie")
    assert aceptacion["vigente"] is False and aceptacion["aceptada"] is False
    config = await ll.leer_config(negocio["id"])
    assert config.modo_configurado == "sombra" and config.modo == "sombra"
    (tarea,) = await _tareas()
    assert tarea.estado == "cancelada" and tarea.motivo_cierre == "compuerta_cerrada"
    assert (await ll.listar_tareas(negocio["id"], _usuario(negocio, "ana")))["tareas"] == []
    # y el cierre de 15 h vuelve a ser el de siempre
    async with mem.async_session() as s:
        assert await ll.reconciliar_compuerta(negocio["id"]) == 0


async def test_apagar_el_modulo_cancela_las_tareas_activas_en_la_siguiente_corrida():
    negocio, canal = await _negocio("ll-gate7")
    await _asesores(negocio, "ana")
    await _lead(negocio, canal, horas=16)
    await _activar(negocio)
    await ll.procesar_negocio(negocio["id"])
    _, cierre = await mem.listar_leads_inactividad_cliente()
    assert TEL not in {f["telefono"] for f in cierre}                 # con la tarea activa abierta no se cierra
    await _cfg(negocio, **{ll.CLAVE_GABI_ACTIVO: "0"})
    resumen = await ll.procesar_negocio(negocio["id"])
    assert resumen["canceladas_por_compuerta"] == 1
    _, cierre = await mem.listar_leads_inactividad_cliente()
    assert TEL in {f["telefono"] for f in cierre}


# ── Exclusiones (E1-E4) ──────────────────────────────────────────────────────────────────────────

async def test_el_lead_base_es_elegible_con_puntaje_12():
    negocio, canal = await _negocio("ll-ex0")
    await _lead(negocio, canal)
    ev = await _evaluar()
    assert ev.elegible and ev.puntaje == 12
    assert ev.senales["mensajes_cliente"] == 2 and ev.senales["pidio_dni_o_financiamiento"] and ev.senales["dio_precio"]
    assert set(ev.senales["puntos"]) == {"mensajes_cliente", "datos_o_financiamiento", "precio", "producto", "nombre", "paso"}


async def _asesor_asignado(negocio, canal):
    await mem.asignar_asesor_a_lead(TEL, "rvilchez")

async def _pausado(negocio, canal):
    await mem.actualizar_lead(TEL, campos_explicitos=("pausado_manual",), pausado_manual=True)

async def _derivado(negocio, canal):
    await mem.actualizar_lead(TEL, paso_flujo="derivado_asesor")

async def _escalado(negocio, canal):
    async with mem.async_session() as s:
        (await s.get(mem.Lead, TEL)).escalado_supervision_en = datetime.utcnow()
        await s.commit()

async def _con_resultado(negocio, canal):
    await mem.actualizar_lead(TEL, campos_explicitos=("resultado",), resultado="agendado")

async def _sin_saldo(negocio, canal):
    await mem.actualizar_lead(TEL, campos_explicitos=("resultado",), resultado="sin_saldo")

async def _sin_stock(negocio, canal):
    await mem.actualizar_lead(TEL, campos_explicitos=("resultado",), resultado="producto_sin_stock")

async def _formulario(negocio, canal):
    await mem.actualizar_lead(TEL, origen_contacto="formulario_meta")

async def _cerrado_def(negocio, canal):
    async with mem.async_session() as s:
        (await s.get(mem.Lead, TEL)).cerrado_definitivamente_en = datetime.utcnow()
        await s.commit()

async def _no_llamar(negocio, canal):
    async with mem.async_session() as s:
        contacto = (await s.execute(select(mem.Contact).where(mem.Contact.telefono == TEL))).scalar_one()
        contacto.no_llamar_en = datetime.utcnow()
        await s.commit()

async def _humano(negocio, canal):
    await mem.guardar_mensaje(TEL, "asesor", "Hola, soy un asesor", negocio["id"])
    await mem.guardar_mensaje(TEL, "assistant", "Gabi retoma", negocio["id"])

async def _eco_app(negocio, canal):
    await mem.guardar_mensaje(TEL, "assistant", "Escrito desde el celular", negocio["id"], via_app=True)

async def _ultimo_del_cliente(negocio, canal):
    await mem.guardar_mensaje(TEL, "user", "¿sigues ahí?", negocio["id"])

async def _rechazo(negocio, canal):
    for role, texto, hace in (("user", "No me interesa, gracias", 5.5), ("assistant", "Entendido, avísame si cambias de idea", 5.4)):
        guardado = await mem.guardar_mensaje(TEL, role, texto, negocio["id"])
        async with mem.async_session() as s:
            (await s.get(mem.Mensaje, guardado["id"])).timestamp = datetime.utcnow() - timedelta(hours=hace)
            await s.commit()

async def _envio_fallido(negocio, canal):
    await mem.guardar_mensaje(TEL, "assistant", "Mensaje que no llegó", negocio["id"], estado_envio="fallido")


@pytest.mark.parametrize("preparar, motivo", [
    (_asesor_asignado, "asesor"), (_pausado, "pausa"), (_derivado, "derivado"), (_escalado, "escalado"),
    (_con_resultado, "con_resultado"), (_sin_saldo, "con_resultado"), (_sin_stock, "con_resultado"),
    (_formulario, "origen_formulario"), (_cerrado_def, "cerrado"), (_no_llamar, "no_llamar"), (_humano, "humano"),
    (_eco_app, "humano"), (_ultimo_del_cliente, "ultimo_no_es_bot"), (_rechazo, "rechazo"),
])
async def test_tabla_de_exclusiones(preparar, motivo):
    negocio, canal = await _negocio(f"ll-ex-{preparar.__name__.strip('_')}")
    await _lead(negocio, canal)
    await preparar(negocio, canal)
    ev = await _evaluar()
    assert ev.elegible is False and ev.motivo == motivo


async def test_un_envio_fallido_no_cuenta_como_ultimo_mensaje_del_bot():
    """El cliente nunca recibió ese mensaje: el último mensaje REAL del bot sigue siendo el anterior."""
    negocio, canal = await _negocio("ll-ex-fallido")
    await _lead(negocio, canal)
    await _envio_fallido(negocio, canal)
    assert (await _evaluar()).elegible is True


@pytest.mark.parametrize("telefono, motivo", [
    ("A1B2C3D4E5F6G7H8", "telefono_no_peruano"),     # BSUID
    ("14155550123", "telefono_no_peruano"),          # otro país
    ("987654321", "telefono_no_peruano"),
])
async def test_no_se_llama_a_un_bsuid_ni_a_un_numero_que_no_es_peruano(telefono, motivo):
    negocio, canal = await _negocio(f"ll-tel-{telefono[:4]}")
    await _lead(negocio, canal, telefono)
    ev = await _evaluar(telefono)
    assert ev.elegible is False and ev.motivo == motivo


async def test_el_silencio_corto_y_el_demasiado_largo_no_son_candidatos():
    negocio, canal = await _negocio("ll-silencio")
    await _lead(negocio, canal, horas=2)
    assert (await _evaluar(horas_silencio=4)).motivo == "silencio_corto"
    assert (await _evaluar(horas_silencio=None)).elegible is True        # la oferta no exige silencio mínimo
    negocio2, canal2 = await _negocio("ll-silencio2")
    await _lead(negocio2, canal2, "51987000002", horas=100)
    assert (await _evaluar("51987000002")).motivo == "silencio_largo"


async def test_la_falla_de_la_ia_no_es_un_lead_callado():
    negocio, canal = await _negocio("ll-falla")
    texto_error = "Uy, estoy teniendo un problema técnico. Por favor intenta de nuevo en unos minutos 🙏"
    await _lead(negocio, canal, guion=[("user", "Hola quiero una terma", 6.0), ("assistant", texto_error, 5.9)])
    assert (await _evaluar()).motivo == "falla_ia"


async def test_un_lead_sin_ningun_mensaje_del_cliente_no_es_candidato():
    negocio, canal = await _negocio("ll-sinmsg")
    await _lead(negocio, canal, guion=[("assistant", "Hola", 6.0)])
    assert (await _evaluar()).motivo == "sin_mensajes_cliente"


async def test_el_saludo_prellenado_del_anuncio_no_cuenta_como_mensaje_real():
    negocio, canal = await _negocio("ll-prell")
    guion = [("user", "Hola, quiero más información", 6.3), ("assistant", "¡Hola! ¿Qué producto buscas?", 6.2),
             ("user", "una terma", 6.0), ("assistant", "Perfecto, te cuento", 5.9)]
    await _lead(negocio, canal, guion=guion, campana_origen="Campaña terma")
    ev = await _evaluar()
    assert ev.senales["mensajes_cliente"] == 1 and ev.senales["prellenado"] is True
    assert ev.puntaje == 2 + 1 + 1                                          # producto + nombre + paso, SIN los 3 de mensajes


async def test_los_adjuntos_y_reacciones_no_son_mensajes_reales():
    negocio, canal = await _negocio("ll-adj")
    guion = [("user", "[image]", 6.3), ("user", "Reaccionó con 👍", 6.2), ("user", "una terma", 6.0), ("assistant", "Perfecto", 5.9)]
    await _lead(negocio, canal, guion=guion)
    assert (await _evaluar()).senales["mensajes_cliente"] == 1


# ── Datos nulos del modelo económico ─────────────────────────────────────────────────────────────

async def test_datos_nulos_del_modelo_no_suman_puntos_ni_rompen_nada():
    negocio, canal = await _negocio("ll-nulos")
    guion = [("user", "Hola", 6.1), ("assistant", "Hola, ¿qué buscas?", 6.0), ("user", "no sé aún", 5.9), ("assistant", "Cuéntame con calma", 5.8)]
    for nulo in ("null", "None", "N/A", "desconocido", "  "):
        telefono = "519870" + str(abs(hash(nulo)) % 100000).zfill(5)
        await _lead(negocio, canal, telefono, guion=guion, nombre=nulo, producto_tipo=nulo, paso=nulo, producto_marca=nulo)
        ev = await _evaluar(telefono)
        assert ev.elegible and ev.puntaje == 3, nulo                         # solo los 2 mensajes reales
        assert ev.senales["producto_conocido"] is False and ev.senales["nombre_conocido"] is False and ev.senales["paso_flujo"] is None


async def test_un_lead_con_todo_nulo_y_un_solo_mensaje_queda_sin_puntaje_y_sin_tarea():
    negocio, canal = await _negocio("ll-nulos2")
    await _lead(negocio, canal, guion=[("user", "Hola", 6.1), ("assistant", "Hola", 6.0)], nombre=None, producto_tipo=None, paso=None)
    await _encender(negocio)
    resumen = await ll.procesar_negocio(negocio["id"])
    assert resumen["creacion"]["creadas"] == 0 and resumen["creacion"]["por_motivo"] == {"puntaje_bajo": 1}


# ── Segmentos, mínimo y exploración ──────────────────────────────────────────────────────────────

async def test_el_puntaje_minimo_configurable_decide_si_hay_tarea():
    negocio, canal = await _negocio("ll-min")
    guion = [("user", "Hola", 6.1), ("assistant", "Hola, ¿qué buscas?", 6.0), ("user", "una terma", 5.9), ("assistant", "Perfecto", 5.8)]
    await _lead(negocio, canal, guion=guion, nombre=None, producto_tipo="terma", paso=None)       # 3 (mensajes) + 2 (producto) = 5 → B
    await _encender(negocio)
    assert (await ll.procesar_negocio(negocio["id"]))["creacion"]["por_segmento"] == {"B": 1}
    negocio2, canal2 = await _negocio("ll-min2")
    await _lead(negocio2, canal2, "51987000002", guion=guion, nombre=None, producto_tipo="terma", paso=None)
    await _encender(negocio2, **{ll.CLAVE_PUNTAJE_MINIMO: 6})
    assert (await ll.procesar_negocio(negocio2["id"]))["creacion"]["creadas"] == 0


async def test_exploracion_toma_una_fraccion_del_puntaje_2_a_3():
    negocio, canal = await _negocio("ll-expl")
    guion = [("user", "Hola", 6.1), ("assistant", "Hola", 6.0)]
    await _lead(negocio, canal, guion=guion, nombre="Ana", producto_tipo="terma", paso=None)     # 1 + 2 = 3
    await _encender(negocio, **{ll.CLAVE_EXPLORACION_PCT: 100})
    resumen = await ll.procesar_negocio(negocio["id"])
    assert resumen["creacion"]["por_segmento"] == {"exploracion": 1}
    negocio2, canal2 = await _negocio("ll-expl2")
    await _lead(negocio2, canal2, "51987000002", guion=guion, nombre="Ana", producto_tipo="terma", paso=None)
    await _encender(negocio2)                                                                    # exploración 0 por defecto
    assert (await ll.procesar_negocio(negocio2["id"]))["creacion"]["creadas"] == 0


# ── Idempotencia ─────────────────────────────────────────────────────────────────────────────────

async def test_dos_corridas_no_duplican_la_tarea():
    negocio, canal = await _negocio("ll-idem")
    await _lead(negocio, canal)
    await _encender(negocio)
    await ll.procesar_negocio(negocio["id"])
    segunda = await ll.procesar_negocio(negocio["id"])
    assert segunda["creacion"]["creadas"] == 0 and segunda["creacion"]["por_motivo"].get("ya_hubo_tarea") == 1
    assert len(await _tareas()) == 1


async def test_el_indice_unico_impide_dos_tareas_abiertas_en_la_misma_conversacion():
    negocio, canal = await _negocio("ll-idem2")
    await _lead(negocio, canal)
    await _encender(negocio)
    await ll.procesar_negocio(negocio["id"])
    (t,) = await _tareas()
    async with mem.async_session() as s:
        s.add(mem.TareaLlamada(
            negocio_id=t.negocio_id, conversation_id=t.conversation_id, contact_id=t.contact_id, telefono=t.telefono,
            estado="programada", segmento="B", puntaje=5, grupo="llamar", modo="sombra", creada_en=datetime.utcnow(),
        ))
        with pytest.raises(IntegrityError):
            await s.commit()


async def test_una_tarea_cerrada_no_bloquea_el_indice_pero_el_ciclo_no_vuelve_a_generar():
    negocio, canal = await _negocio("ll-idem3")
    await _lead(negocio, canal)
    await _encender(negocio)
    await ll.procesar_negocio(negocio["id"])
    (t,) = await _tareas()
    await _tocar(t.id, estado="cancelada")
    again = await ll.procesar_negocio(negocio["id"])
    assert again["creacion"]["creadas"] == 0 and len(await _tareas()) == 1       # "ya hubo tarea en este ciclo"


# ── Holdout ──────────────────────────────────────────────────────────────────────────────────────

async def test_el_grupo_de_control_se_registra_pero_nunca_se_muestra_ni_se_reparte():
    negocio, canal = await _negocio("ll-ctrl")
    await _asesores(negocio, "ana")
    await _lead(negocio, canal)
    await _activar(negocio, holdout=100)
    await ll.procesar_negocio(negocio["id"])
    (t,) = await _tareas()
    assert t.grupo == "control" and t.modo == "activo" and t.estado == "pendiente"
    await ll.procesar_negocio(negocio["id"])
    assert (await _tareas())[0].asesor_username is None
    assert (await ll.listar_tareas(negocio["id"], _usuario(negocio, "ana")))["tareas"] == []
    _, cierre = await mem.listar_leads_inactividad_cliente(horas_reenganche=2, horas_cierre=5)
    assert TEL in {f["telefono"] for f in cierre}                                # el control se comporta como siempre


# ── Activo: reparto, horario, visibilidad ────────────────────────────────────────────────────────

async def test_activo_asigna_y_solo_el_dueno_ve_la_tarea():
    negocio, canal = await _negocio("ll-act")
    await _asesores(negocio, "ana", "beto")
    await _lead(negocio, canal)
    await _activar(negocio)
    await ll.procesar_negocio(negocio["id"])
    (t,) = await _tareas()
    assert t.estado == "pendiente" and t.asesor_username in ("ana", "beto") and t.asignada_en is not None
    # la asignación es de la TAREA: el lead no cambia de dueño y Gabi sigue activa
    lead = await mem.obtener_lead(TEL, negocio_id=negocio["id"])
    assert lead["asesor_asignado"] is None and not lead.get("pausado_manual")
    dueno, otro = (t.asesor_username, "beto" if t.asesor_username == "ana" else "ana")
    assert len((await ll.listar_tareas(negocio["id"], _usuario(negocio, dueno)))["tareas"]) == 1
    assert (await ll.listar_tareas(negocio["id"], _usuario(negocio, otro)))["tareas"] == []
    todas = await ll.listar_tareas(negocio["id"], _usuario(negocio, "sup", "supervisor"))
    assert len(todas["tareas"]) == 1 and todas["kpi"]["pendientes"] == 1 and "medicion" in todas
    assert "medicion" not in await ll.listar_tareas(negocio["id"], _usuario(negocio, dueno))


async def test_fuera_de_horario_la_tarea_queda_programada_y_no_se_asigna_hasta_la_apertura():
    negocio, canal = await _negocio("ll-hor", horario="cerrado")
    await _asesores(negocio, "ana")
    await _lead(negocio, canal)
    await _activar(negocio)
    await ll.procesar_negocio(negocio["id"])
    (t,) = await _tareas()
    assert t.estado == "programada" and t.programada_para is not None and t.programada_para > datetime.utcnow()
    assert t.asesor_username is None
    await ll.procesar_negocio(negocio["id"])
    assert (await _tareas())[0].estado == "programada" and (await _tareas())[0].asesor_username is None
    # el negocio abre
    await _horario(negocio["id"], "abierto")
    await _tocar(t.id, programada_para=datetime.utcnow() - timedelta(minutes=1))
    resumen = await ll.procesar_negocio(negocio["id"])
    assert resumen["activadas"] == 1 and resumen["asignadas"] == 1
    (t,) = await _tareas()
    assert t.estado == "pendiente" and t.asesor_username == "ana"


async def test_sin_asesores_disponibles_la_tarea_espera_sin_asignar():
    negocio, canal = await _negocio("ll-sinase")
    await _asesores(negocio, "ana")
    await mem.actualizar_disponibilidad("ana", negocio["id"], False)
    await _lead(negocio, canal)
    await _activar(negocio)
    resumen = await ll.procesar_negocio(negocio["id"])
    assert resumen["sin_asesor_disponible"] == 1
    assert (await _tareas())[0].asesor_username is None
    await mem.actualizar_disponibilidad("ana", negocio["id"], True)
    await ll.procesar_negocio(negocio["id"])
    assert (await _tareas())[0].asesor_username == "ana"


async def test_el_reparto_es_equitativo_y_no_alfabetico():
    negocio, canal = await _negocio("ll-rep")
    await _asesores(negocio, "ana", "beto", "carla")
    nid = negocio["id"]
    ahora = datetime.utcnow()
    conversation, _ = await mem.resolver_conversation_activa(TEL, nid, canal["id"])
    # Historia: ana recibió hace 1 h, beto hace 3 h y carla hace 6 h → toca carla (la de más tiempo sin llamadas), no ana.
    async with mem.async_session() as s:
        contacto = (await s.execute(select(mem.Contact).where(mem.Contact.telefono == TEL))).scalar_one()
        for usuario, hace in (("ana", 1), ("beto", 3), ("carla", 6)):
            s.add(mem.TareaLlamada(
                negocio_id=nid, conversation_id=conversation.id, contact_id=contacto.id, telefono=TEL, estado="cumplida",
                segmento="B", puntaje=5, grupo="llamar", modo="activo", asesor_username=usuario, creada_en=ahora - timedelta(hours=hace),
                asignada_en=ahora - timedelta(hours=hace), cerrada_en=ahora - timedelta(hours=hace - 0.5),
            ))
        await s.commit()
    await _activar(negocio)
    assert await ll.elegir_asesor(nid) == "carla"
    assert await ll.elegir_asesor(nid, excluir="carla") == "beto"
    assert await ll.elegir_asesor(nid) == "carla"              # sin historia nueva sigue siendo carla (determinista)


async def test_menos_carga_gana_al_round_robin():
    negocio, canal = await _negocio("ll-rep2")
    await _asesores(negocio, "ana", "beto")
    nid = negocio["id"]
    ahora = datetime.utcnow()
    conversation, _ = await mem.resolver_conversation_activa(TEL, nid, canal["id"])
    async with mem.async_session() as s:
        contacto = (await s.execute(select(mem.Contact).where(mem.Contact.telefono == TEL))).scalar_one()
        # beto lleva más tiempo sin recibir, pero tiene una llamada abierta; ana tiene la última asignación pero ninguna abierta
        s.add(mem.TareaLlamada(negocio_id=nid, conversation_id=conversation.id, contact_id=contacto.id, telefono=TEL, estado="pendiente",
                               segmento="A", puntaje=9, grupo="llamar", modo="activo", asesor_username="beto",
                               creada_en=ahora - timedelta(hours=9), asignada_en=ahora - timedelta(hours=9)))
        await s.commit()
    assert await ll.elegir_asesor(nid) == "ana"


async def test_el_reparto_reparte_varias_tareas_entre_todos():
    negocio, canal = await _negocio("ll-rep3")
    await _asesores(negocio, "ana", "beto", "carla")
    for i in range(3):
        await _lead(negocio, canal, f"5198710000{i}")
    await _activar(negocio)
    await ll.procesar_negocio(negocio["id"])
    asignados = sorted(t.asesor_username for t in await _tareas())
    assert asignados == ["ana", "beto", "carla"]


# ── SLA ──────────────────────────────────────────────────────────────────────────────────────────

async def test_sla_reasigna_una_vez_y_luego_deja_la_tarea_sin_hacer_para_el_supervisor():
    negocio, canal = await _negocio("ll-sla")
    await _asesores(negocio, "ana", "beto")
    await _lead(negocio, canal)
    await _activar(negocio)
    await ll.procesar_negocio(negocio["id"])
    (t,) = await _tareas()
    primero = t.asesor_username
    otro = "beto" if primero == "ana" else "ana"
    # pasan 3 h hábiles sin que nadie la haga (el horario del test es de 24 h)
    await _tocar(t.id, asignada_en=datetime.utcnow() - timedelta(hours=3), programada_para=None)
    resumen = await ll.procesar_negocio(negocio["id"])
    assert resumen["reasignadas"] == 1
    (t,) = await _tareas()
    assert t.asesor_username == otro and t.reasignaciones == 1 and t.escalada_en is None
    # otra vez sin hacerse → "sin hacer", visible al supervisor
    await _tocar(t.id, asignada_en=datetime.utcnow() - timedelta(hours=3))
    resumen = await ll.procesar_negocio(negocio["id"])
    assert resumen["escaladas"] == 1
    (t,) = await _tareas()
    assert t.escalada_en is not None and t.asesor_username == otro
    vista = await ll.listar_tareas(negocio["id"], _usuario(negocio, "sup", "supervisor"))
    assert vista["kpi"]["vencidas"] == 1 and vista["kpi"]["sin_hacer"] == 1 and vista["tareas"][0]["sin_hacer"] is True
    assert len(await _eventos(mem.EVENTO_LLAMADA_ESCALADA)) == 1
    # no se escala dos veces
    await ll.procesar_negocio(negocio["id"])
    assert len(await _eventos(mem.EVENTO_LLAMADA_ESCALADA)) == 1


async def test_dentro_del_sla_no_se_toca_la_tarea():
    negocio, canal = await _negocio("ll-sla2")
    await _asesores(negocio, "ana", "beto")
    await _lead(negocio, canal)
    await _activar(negocio)
    await ll.procesar_negocio(negocio["id"])
    antes = (await _tareas())[0].asesor_username
    resumen = await ll.procesar_negocio(negocio["id"])
    assert "reasignadas" not in resumen and (await _tareas())[0].asesor_username == antes


async def test_el_sla_cuenta_solo_las_horas_del_horario_de_atencion():
    negocio, _ = await _negocio("ll-sla3", horario="cerrado")
    rangos = {d: ("08:00", "19:00") for d in range(7)}
    t = mem.TareaLlamada(creada_en=datetime(2026, 10, 7, 23, 0), asignada_en=datetime(2026, 10, 7, 23, 0), estado="pendiente", asesor_username="ana")
    # 18:00 Lima = 23:00 UTC; hasta las 12:00 Lima del día siguiente solo cuentan 1 h (18-19) + 4 h (8-12)
    assert round(ll.horas_habiles_esperando(t, rangos, datetime(2026, 10, 8, 17, 0)), 1) == 5.0
    assert ll.esta_vencida(t, rangos, datetime(2026, 10, 8, 17, 0), 2.0) is True
    assert ll.esta_vencida(t, rangos, datetime(2026, 10, 7, 23, 30), 2.0) is False


# ── Expiración ───────────────────────────────────────────────────────────────────────────────────

async def test_la_tarea_expira_a_los_dias_de_vida_maxima_y_el_cierre_de_siempre_vuelve():
    negocio, canal = await _negocio("ll-exp")
    await _asesores(negocio, "ana")
    await _lead(negocio, canal, horas=16)
    await _activar(negocio)
    await ll.procesar_negocio(negocio["id"])
    (t,) = await _tareas()
    assert t.vence_en - t.creada_en == timedelta(days=3)
    await _tocar(t.id, vence_en=datetime.utcnow() - timedelta(minutes=1))
    resumen = await ll.procesar_negocio(negocio["id"])
    assert resumen["expiradas"] == 1
    (t,) = await _tareas()
    assert t.estado == "expirada" and t.motivo_cierre == "vida_maxima" and t.cerrada_en is not None
    assert len(await _eventos(mem.EVENTO_LLAMADA_EXPIRADA)) == 1
    _, cierre = await mem.listar_leads_inactividad_cliente()
    assert TEL in {f["telefono"] for f in cierre}


async def test_la_vida_maxima_se_configura():
    negocio, canal = await _negocio("ll-exp2")
    await _lead(negocio, canal)
    await _encender(negocio, **{ll.CLAVE_VIDA_MAX_DIAS: 1})
    await ll.procesar_negocio(negocio["id"])
    (t,) = await _tareas()
    assert t.vence_en - t.creada_en == timedelta(days=1)


# ── Cancelación por respuesta ────────────────────────────────────────────────────────────────────

async def test_el_hook_del_webhook_cancela_la_tarea_cuando_el_cliente_vuelve_a_escribir(monkeypatch):
    negocio, canal = await _negocio("ll-hook")
    await _asesores(negocio, "ana")
    await _lead(negocio, canal)
    await _activar(negocio)
    await ll.procesar_negocio(negocio["id"])
    assert (await _tareas())[0].estado == "pendiente"
    canal_dict = {"id": canal["id"], "negocio_id": negocio["id"], "unidad_id": None, "phone_number_id": canal["phone_number_id"], "modo": "produccion"}
    proveedor, gabi = _preparar_webhook(monkeypatch, canal_dict, canal, [])
    await _correr(proveedor, [_msg(TEL, canal, "Hola, ya me decidí", "wamid.ll-hook-1")])
    (t,) = await _tareas()
    assert t.estado == "cancelada" and t.motivo_cierre == "respondio_cliente" and t.cerrada_en is not None
    (evento,) = await _eventos(mem.EVENTO_LLAMADA_CANCELADA_POR_RESPUESTA)
    assert evento.payload["motivo"] == "respondio_cliente"
    assert (await ll.listar_tareas(negocio["id"], _usuario(negocio, "ana")))["tareas"] == []


async def test_una_reaccion_no_cancela_la_tarea(monkeypatch):
    negocio, canal = await _negocio("ll-hook2")
    await _lead(negocio, canal)
    await _encender(negocio)
    await ll.procesar_negocio(negocio["id"])
    canal_dict = {"id": canal["id"], "negocio_id": negocio["id"], "unidad_id": None, "phone_number_id": canal["phone_number_id"], "modo": "produccion"}
    proveedor, _ = _preparar_webhook(monkeypatch, canal_dict, canal, [])
    await _correr(proveedor, [_msg(TEL, canal, "👍", "wamid.ll-hook-2", tipo="reaction")])
    assert (await _tareas())[0].estado == "pendiente"


async def test_el_hook_no_hace_nada_sin_tareas_ni_cuando_el_modulo_esta_apagado():
    negocio, canal = await _negocio("ll-hook3")
    assert await ll.cancelar_por_respuesta_del_cliente(TEL, negocio["id"]) == 0


async def test_la_revalidacion_cancela_en_el_listado_si_el_cliente_escribio_por_otro_camino():
    negocio, canal = await _negocio("ll-reval")
    await _asesores(negocio, "ana")
    await _lead(negocio, canal)
    await _activar(negocio)
    await ll.procesar_negocio(negocio["id"])
    assert len((await ll.listar_tareas(negocio["id"], _usuario(negocio, "ana")))["tareas"]) == 1
    await mem.guardar_mensaje(TEL, "user", "Hola de nuevo", negocio["id"])           # sin pasar por el webhook
    vista = await ll.listar_tareas(negocio["id"], _usuario(negocio, "ana"))
    assert vista["tareas"] == []
    assert (await _tareas())[0].estado == "cancelada" and (await _tareas())[0].motivo_cierre == "respondio_cliente"


@pytest.mark.parametrize("cambio, motivo", [
    (_asesor_asignado, "paso_a_humano"), (_pausado, "paso_a_humano"), (_derivado, "paso_a_humano"), (_escalado, "paso_a_humano"),
    (_con_resultado, "lead_cerrado"), (_cerrado_def, "lead_cerrado"), (_no_llamar, "no_llamar"), (_humano, "paso_a_humano"),
])
async def test_la_revalidacion_cancela_si_el_lead_deja_de_ser_elegible(cambio, motivo):
    negocio, canal = await _negocio(f"ll-rv-{cambio.__name__.strip('_')}")
    await _asesores(negocio, "ana")
    await _lead(negocio, canal)
    await _activar(negocio)
    await ll.procesar_negocio(negocio["id"])
    await cambio(negocio, canal)
    assert await ll.revalidar_abiertas(negocio["id"]) == 1
    (t,) = await _tareas()
    assert t.estado == "cancelada" and t.motivo_cierre == motivo


async def test_la_revalidacion_deja_en_paz_a_las_tareas_validas():
    negocio, canal = await _negocio("ll-reval2")
    await _lead(negocio, canal)
    await _encender(negocio)
    await ll.procesar_negocio(negocio["id"])
    assert await ll.revalidar_abiertas(negocio["id"]) == 0


# ── Cierre de 15 h y compatibilidad con los demás Cron ───────────────────────────────────────────

async def test_el_cierre_de_15_horas_salta_los_leads_con_tarea_activa_abierta():
    negocio, canal = await _negocio("ll-15h")
    await _asesores(negocio, "ana")
    await _lead(negocio, canal, horas=16)
    await _lead(negocio, canal, "51987000002", horas=16)                    # otro lead SIN tarea (queda en control)
    await _activar(negocio)
    await ll.procesar_negocio(negocio["id"])
    async with mem.async_session() as s:
        otra = (await s.execute(select(mem.TareaLlamada).where(mem.TareaLlamada.telefono == "51987000002"))).scalar_one()
        await s.delete(otra)
        await s.commit()
    reenganche, cierre = await mem.listar_leads_inactividad_cliente(horas_reenganche=2, horas_cierre=15)
    assert {f["telefono"] for f in cierre} == {"51987000002"}


async def test_sin_tareas_el_listado_de_inactividad_es_el_de_siempre():
    negocio, canal = await _negocio("ll-15h-2")
    await _lead(negocio, canal, horas=16)
    reenganche, cierre = await mem.listar_leads_inactividad_cliente(horas_reenganche=2, horas_cierre=15)
    assert [f["telefono"] for f in cierre] == [TEL] and reenganche == []


async def test_un_candidato_no_es_cliente_esperando_ni_candidato_a_rotacion_ni_a_zona_muerta():
    """Disjunto de liberar_leads_inactivos (asesor inactivo), de la plantilla de zona muerta (derivados que esperan) y de la
    atención atrasada: el candidato a llamada es un lead SIN asesor cuyo último mensaje es de Gabi."""
    negocio, canal = await _negocio("ll-disj")
    await _lead(negocio, canal)
    await _encender(negocio)
    await ll.procesar_negocio(negocio["id"])
    assert len(await _tareas()) == 1
    assert [c for c in await mem.listar_clientes_esperando(negocio["id"]) if c["telefono"] == TEL] == []
    assert await mem.listar_leads_para_rotar_o_liberar() == [] or TEL not in str(await mem.listar_leads_para_rotar_o_liberar())
    from agent import atencion_atrasada
    assert [c for c in await atencion_atrasada.candidatos_zona_muerta(negocio["id"]) if c["telefono"] == TEL] == []


async def test_los_demas_cron_se_comportan_igual_con_el_modulo_apagado():
    """La oferta, el reparto y los eventos no existen: el reenganche y el cierre salen como siempre."""
    negocio, canal = await _negocio("ll-igual")
    await _lead(negocio, canal, horas=3)
    ofertas = await ll.preparar_ofertas([{"telefono": TEL, "negocio_id": negocio["id"]}])
    assert ofertas == {}
    reenganche, cierre = await mem.listar_leads_inactividad_cliente(horas_reenganche=2, horas_cierre=15)
    assert [f["telefono"] for f in reenganche] == [TEL] and cierre == []
    assert await _tareas() == [] and await _eventos() == []


# ── Eventos y Timeline ───────────────────────────────────────────────────────────────────────────

def test_los_tipos_de_evento_caben_en_la_columna_y_los_internos_no_ensucian_el_timeline():
    todos = [
        mem.EVENTO_LLAMADA_PENDIENTE_CREADA, mem.EVENTO_LLAMADA_ASIGNADA, mem.EVENTO_LLAMADA_REGISTRADA, mem.EVENTO_LLAMADA_REPROGRAMADA,
        mem.EVENTO_LLAMADA_CANCELADA_POR_RESPUESTA, mem.EVENTO_LLAMADA_AGOTADA, mem.EVENTO_LLAMADA_EXPIRADA, mem.EVENTO_LLAMADA_ESCALADA,
        mem.EVENTO_LLAMADA_OFERTA_ENVIADA,
    ]
    assert all(len(t) <= mem.TIPO_EVENTO_LARGO_MAX for t in todos)
    visibles = {mem.EVENTO_LLAMADA_REGISTRADA, mem.EVENTO_LLAMADA_REPROGRAMADA, mem.EVENTO_LLAMADA_AGOTADA, mem.EVENTO_LLAMADA_OFERTA_ENVIADA}
    assert not visibles & set(mem.TIPOS_EVENTO_INTERNOS)
    assert set(todos) - visibles <= set(mem.TIPOS_EVENTO_INTERNOS)


def test_el_origen_de_la_oferta_esta_registrado():
    from agent import envios
    assert "gabi_oferta_llamada" in envios.ORIGENES and "gabi_oferta_llamada" in envios.ORIGENES_CON_LIMPIEZA_DE_FORMATO


def test_el_cron_esta_vigilado_cada_15_minutos():
    assert mem.CRONES_ESPERADOS["crear_tareas_llamada"][1] == 15
