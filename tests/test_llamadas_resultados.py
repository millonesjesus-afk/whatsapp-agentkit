# tests/test_llamadas_resultados.py — "Para llamar" (2026-10-09): el resultado de cada llamada, reasignar/descartar, y la
# oferta de Gabi (Fase 3, apagada por defecto) de punta a punta con el script de inactividad.

import importlib.util
import os
from datetime import datetime, timedelta
from pathlib import Path

os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")
os.environ.setdefault("WHATSAPP_PROVIDER", "meta")

import pytest
from sqlalchemy import select

from agent import llamadas as ll
from agent import memory as mem
from tests.test_llamadas_flujo import (
    TEL, _activar, _asesores, _cfg, _encender, _eventos, _lead, _negocio, _tareas, _tocar, _usuario,
)

RAIZ = Path(__file__).resolve().parent.parent


async def _escenario(codigo: str, asesores=("ana", "beto"), **cfg):
    """Un negocio en modo activo con UNA tarea ya asignada. Devuelve (negocio, canal, tarea, asesor dueño)."""
    negocio, canal = await _negocio(codigo)
    await _asesores(negocio, *asesores)
    await _lead(negocio, canal)
    await _activar(negocio, **cfg)
    await ll.procesar_negocio(negocio["id"])
    (tarea,) = await _tareas()
    assert tarea.asesor_username in asesores
    return negocio, canal, tarea, tarea.asesor_username


async def _registrar(negocio, tarea, usuario, resultado, **kw):
    return await ll.registrar_resultado(tarea.id, negocio["id"], usuario, resultado, **kw)


async def _tarea(tarea_id):
    async with mem.async_session() as s:
        return await s.get(mem.TareaLlamada, tarea_id)


def _lima(delta: timedelta) -> str:
    return (datetime.utcnow() - timedelta(hours=5) + delta).strftime("%Y-%m-%dT%H:%M")


# ── Los siete resultados ─────────────────────────────────────────────────────────────────────────

async def test_contesto_sigo_yo_asigna_el_lead_al_asesor_y_pausa_a_gabi():
    negocio, canal, tarea, dueno = await _escenario("lr-sigo")
    r = await _registrar(negocio, tarea, _usuario(negocio, dueno), "contesto_sigo_yo", nota="Quiere terma de 80 L")
    assert r["accion"] == "ninguna" and r["tarea"]["estado"] == "cumplida" and r["tarea"]["resultado_llamada"] == "contesto_sigo_yo"
    lead = await mem.obtener_lead(TEL, negocio_id=negocio["id"])
    assert lead["asesor_asignado"] == dueno                                # desde ahora Gabi se pausa (hay asesor asignado)
    t = await _tarea(tarea.id)
    assert t.estado == "cumplida" and t.motivo_cierre == "contesto_sigo_yo" and t.nota == "Quiere terma de 80 L" and t.cerrada_en
    visibles = [e["tipo"] for e in await mem.listar_eventos_lead(TEL)]
    assert mem.EVENTO_LLAMADA_REGISTRADA in visibles and "asignado" in visibles


async def test_la_llamada_registrada_deja_el_resultado_y_la_nota_en_el_payload():
    negocio, canal, tarea, dueno = await _escenario("lr-payload")
    await _registrar(negocio, tarea, _usuario(negocio, dueno), "contesto_sigo_yo", nota="nota X")
    (e,) = await _eventos(mem.EVENTO_LLAMADA_REGISTRADA)
    assert e.payload["resultado"] == "contesto_sigo_yo" and e.payload["nota"] == "nota X" and e.autor == dueno.capitalize()


async def test_contesto_agendado_pide_abrir_el_formulario_de_agendar_y_cierra_la_tarea():
    negocio, canal, tarea, dueno = await _escenario("lr-agenda")
    r = await _registrar(negocio, tarea, _usuario(negocio, dueno), "contesto_agendado")
    assert r["accion"] == "abrir_agendar" and r["conversation_id"] == tarea.conversation_id
    assert (await _tarea(tarea.id)).estado == "cumplida"


async def test_contesto_no_interesado_pone_el_resultado_del_caso():
    negocio, canal, tarea, dueno = await _escenario("lr-noint")
    await _registrar(negocio, tarea, _usuario(negocio, dueno), "contesto_no_interesado")
    assert (await mem.obtener_lead(TEL, negocio_id=negocio["id"]))["resultado"] == "no_interesado"
    async with mem.async_session() as s:
        opp = (await s.execute(select(mem.Opportunity).where(mem.Opportunity.conversation_id == tarea.conversation_id))).scalar_one()
    assert opp.resultado == "no_interesado"
    assert (await _tarea(tarea.id)).estado == "cumplida"


async def test_contesto_llamar_luego_reprograma_sin_contar_como_intento_fallido():
    negocio, canal, tarea, dueno = await _escenario("lr-luego")
    hora = _lima(timedelta(hours=26))
    r = await _registrar(negocio, tarea, _usuario(negocio, dueno), "contesto_llamar_luego", hora=hora, nota="Después del almuerzo")
    t = await _tarea(tarea.id)
    assert t.estado == "programada" and t.intentos == 0 and t.asesor_username == dueno
    assert t.programada_para == datetime.fromisoformat(hora) + timedelta(hours=5) == t.proximo_intento_en
    assert r["tarea"]["programada_para"].endswith("Z")
    (e,) = await _eventos(mem.EVENTO_LLAMADA_REPROGRAMADA)
    assert e.payload["nueva_hora"].endswith("Z") and e.payload["resultado"] == "contesto_llamar_luego"
    # sigue siendo del asesor, pero todavía no es accionable
    assert (await ll.datos_para_inicio(negocio["id"], dueno))["pendientes"] == 0


@pytest.mark.parametrize("hora", [None, "", "mañana", "2020-01-01T10:00", "no-es-fecha"])
async def test_llamar_luego_exige_una_hora_futura_valida(hora):
    negocio, canal, tarea, dueno = await _escenario("lr-luego2")
    with pytest.raises(ll.ErrorLlamada) as e:
        await _registrar(negocio, tarea, _usuario(negocio, dueno), "contesto_llamar_luego", hora=hora)
    assert e.value.codigo == "invalido"
    assert (await _tarea(tarea.id)).estado == "pendiente"


async def test_llamar_luego_no_puede_pasarse_de_la_vida_maxima():
    negocio, canal, tarea, dueno = await _escenario("lr-luego3")
    with pytest.raises(ll.ErrorLlamada) as e:
        await _registrar(negocio, tarea, _usuario(negocio, dueno), "contesto_llamar_luego", hora=_lima(timedelta(days=10)))
    assert e.value.codigo == "invalido"


async def test_la_hora_con_zona_se_convierte_a_utc():
    negocio, canal, tarea, dueno = await _escenario("lr-luego4")
    futuro_utc = (datetime.utcnow() + timedelta(hours=30)).replace(microsecond=0)
    await _registrar(negocio, tarea, _usuario(negocio, dueno), "contesto_llamar_luego", hora=futuro_utc.isoformat() + "Z")
    assert (await _tarea(tarea.id)).programada_para == futuro_utc


async def test_no_contesto_reprograma_en_otra_franja_y_al_tercer_intento_se_agota_y_cierra_sin_respuesta():
    negocio, canal, tarea, dueno = await _escenario("lr-noc")
    u = _usuario(negocio, dueno)
    for intento in (1, 2):
        r = await _registrar(negocio, tarea, u, "no_contesto")
        t = await _tarea(tarea.id)
        assert t.estado == "programada" and t.intentos == intento and t.programada_para > datetime.utcnow()
        assert t.programada_para - datetime.utcnow() >= timedelta(hours=2, minutes=59)
        assert t.cerrada_en is None
    r = await _registrar(negocio, tarea, u, "no_contesto", nota="Sonó apagado")
    t = await _tarea(tarea.id)
    assert t.estado == "agotada" and t.motivo_cierre == "sin_contacto" and t.intentos == 3 and t.cerrada_en
    assert (await mem.obtener_lead(TEL, negocio_id=negocio["id"]))["resultado"] == "sin_respuesta"
    tipos = [e["tipo"] for e in await mem.listar_eventos_lead(TEL)]
    assert tipos.count(mem.EVENTO_LLAMADA_REGISTRADA) == 3 and tipos.count(mem.EVENTO_LLAMADA_AGOTADA) == 1
    assert tipos.count(mem.EVENTO_LLAMADA_REPROGRAMADA) == 2
    with pytest.raises(ll.ErrorLlamada) as e:
        await _registrar(negocio, tarea, u, "no_contesto")
    assert e.value.codigo == "no_abierta"


async def test_el_maximo_de_intentos_se_configura():
    negocio, canal, tarea, dueno = await _escenario("lr-noc2", **{ll.CLAVE_MAX_INTENTOS: 1})
    await _registrar(negocio, tarea, _usuario(negocio, dueno), "no_contesto")
    assert (await _tarea(tarea.id)).estado == "agotada"


async def test_numero_errado_pone_resultado_otro_y_guarda_la_nota():
    negocio, canal, tarea, dueno = await _escenario("lr-err")
    await _registrar(negocio, tarea, _usuario(negocio, dueno), "numero_errado", nota="Era de otra persona")
    assert (await mem.obtener_lead(TEL, negocio_id=negocio["id"]))["resultado"] == "otro"
    t = await _tarea(tarea.id)
    assert t.estado == "cumplida" and t.nota == "Era de otra persona"


async def test_no_llamar_marca_el_contacto_y_cierra_como_no_interesado():
    negocio, canal, tarea, dueno = await _escenario("lr-nollamar")
    await _registrar(negocio, tarea, _usuario(negocio, dueno), "no_llamar")
    async with mem.async_session() as s:
        contacto = (await s.execute(select(mem.Contact).where(mem.Contact.telefono == TEL))).scalar_one()
    assert contacto.no_llamar_en is not None
    assert (await mem.obtener_lead(TEL, negocio_id=negocio["id"]))["resultado"] == "no_interesado"
    assert (await _tarea(tarea.id)).estado == "cumplida"
    # y nunca más se le crea una tarea, ni siquiera en un ciclo nuevo
    async with mem.async_session() as s:
        lead = await s.get(mem.Lead, TEL)
        assert (await ll.evaluar_lead(s, lead, datetime.utcnow(), 4.0)).elegible is False


async def test_si_la_persona_pidio_no_ser_llamada_antes_de_registrar_la_tarea_se_cancela():
    negocio, canal, tarea, dueno = await _escenario("lr-nollamar2")
    async with mem.async_session() as s:
        (await s.execute(select(mem.Contact).where(mem.Contact.telefono == TEL))).scalar_one().no_llamar_en = datetime.utcnow()
        await s.commit()
    with pytest.raises(ll.ErrorLlamada):
        await _registrar(negocio, tarea, _usuario(negocio, dueno), "contesto_sigo_yo")
    assert (await _tarea(tarea.id)).motivo_cierre == "no_llamar"


# ── Validaciones y permisos ──────────────────────────────────────────────────────────────────────

async def test_resultado_invalido_nota_larga_y_modulo_no_activo():
    negocio, canal, tarea, dueno = await _escenario("lr-val")
    u = _usuario(negocio, dueno)
    with pytest.raises(ll.ErrorLlamada) as e:
        await _registrar(negocio, tarea, u, "me_colgo")
    assert e.value.codigo == "invalido"
    with pytest.raises(ll.ErrorLlamada) as e:
        await _registrar(negocio, tarea, u, "no_contesto", nota="x" * 501)
    assert e.value.codigo == "invalido"
    await _cfg(negocio, **{ll.CLAVE_MODO: "sombra"})
    with pytest.raises(ll.ErrorLlamada) as e:
        await _registrar(negocio, tarea, u, "no_contesto")
    assert e.value.codigo == "no_disponible"


async def test_un_asesor_no_registra_sobre_la_tarea_de_otro_pero_un_supervisor_si():
    negocio, canal, tarea, dueno = await _escenario("lr-perm")
    otro = "beto" if dueno == "ana" else "ana"
    with pytest.raises(ll.ErrorLlamada) as e:
        await _registrar(negocio, tarea, _usuario(negocio, otro), "no_contesto")
    assert e.value.codigo == "sin_permiso" and (await _tarea(tarea.id)).intentos == 0
    await _registrar(negocio, tarea, _usuario(negocio, "sup", "supervisor"), "no_contesto")
    assert (await _tarea(tarea.id)).intentos == 1


async def test_una_tarea_de_otro_negocio_no_existe_para_mi():
    negocio, canal, tarea, dueno = await _escenario("lr-tenant")
    otro_negocio, _ = await _negocio("lr-tenant-b")
    await _activar(otro_negocio)
    with pytest.raises(ll.ErrorLlamada) as e:
        await ll.registrar_resultado(tarea.id, otro_negocio["id"], _usuario(otro_negocio, dueno, "admin"), "no_contesto")
    assert e.value.codigo == "no_encontrada"
    with pytest.raises(ll.ErrorLlamada) as e:
        await ll.registrar_resultado("no-existe", negocio["id"], _usuario(negocio, dueno), "no_contesto")
    assert e.value.codigo == "no_encontrada"


async def test_las_tareas_de_sombra_y_de_control_no_se_pueden_operar():
    negocio, canal, tarea, dueno = await _escenario("lr-ctl")
    await _tocar(tarea.id, grupo="control")
    with pytest.raises(ll.ErrorLlamada) as e:
        await _registrar(negocio, tarea, _usuario(negocio, "sup", "supervisor"), "no_contesto")
    assert e.value.codigo == "no_encontrada"


# ── Reasignar y descartar (supervisor) ───────────────────────────────────────────────────────────

async def test_el_supervisor_reasigna_y_devuelve_al_reparto():
    negocio, canal, tarea, dueno = await _escenario("lr-reas")
    otro = "beto" if dueno == "ana" else "ana"
    sup = _usuario(negocio, "sup", "supervisor")
    r = await ll.reasignar(tarea.id, negocio["id"], sup, otro)
    assert r["tarea"]["asesor"] == otro
    r = await ll.reasignar(tarea.id, negocio["id"], sup, None)
    assert r["tarea"]["asesor"] is None
    with pytest.raises(ll.ErrorLlamada) as e:
        await ll.reasignar(tarea.id, negocio["id"], sup, "fantasma")
    assert e.value.codigo == "invalido"
    await ll.procesar_negocio(negocio["id"])                                # el reparto la vuelve a asignar
    assert (await _tarea(tarea.id)).asesor_username in ("ana", "beto")


async def test_el_supervisor_descarta_sin_tocar_el_lead():
    negocio, canal, tarea, dueno = await _escenario("lr-desc")
    r = await ll.descartar(tarea.id, negocio["id"], _usuario(negocio, "sup", "supervisor"), nota="Ya lo llamó el jefe")
    assert r["tarea"]["estado"] == "cancelada" and r["tarea"]["motivo_cierre"] == "descartada_supervisor"
    lead = await mem.obtener_lead(TEL, negocio_id=negocio["id"])
    assert lead["resultado"] is None and lead["asesor_asignado"] is None


# ── Oferta de Gabi ───────────────────────────────────────────────────────────────────────────────

async def _candidato(codigo, *, activar=True, oferta="1", holdout=0, horas=6.0, **cfg):
    negocio, canal = await _negocio(codigo)
    await _lead(negocio, canal, horas=horas)
    if activar:
        await _activar(negocio, holdout=holdout, **{ll.CLAVE_OFERTA_ACTIVA: oferta}, **cfg)
    return negocio, canal, [{"telefono": TEL, "negocio_id": negocio["id"]}]


async def test_la_oferta_reemplaza_al_reenganche_de_un_segmento_a_con_el_nombre_y_el_producto():
    negocio, canal, filas = await _candidato("lo-ok")
    oferta = (await ll.preparar_ofertas(filas))[TEL]
    assert oferta["accion"] == "ofrecer" and oferta["segmento"] == "A" and oferta["puntaje"] == 12
    assert oferta["texto"].startswith("Hola Ana, soy Gabi.") and "consulta de" in oferta["texto"]
    assert "Si prefieres que no te llamemos" in oferta["texto"]


async def test_la_oferta_usa_el_texto_configurado():
    plantilla = "Hola {nombre}, un asesor puede llamarte por {producto}. Si no quieres que te llamemos, avísame."
    negocio, canal, filas = await _candidato("lo-texto", **{ll.CLAVE_OFERTA_TEXTO: plantilla})
    assert (await ll.preparar_ofertas(filas))[TEL]["texto"].startswith("Hola Ana, un asesor puede llamarte por")


@pytest.mark.parametrize("escenario", ["apagada", "oferta_off", "sombra", "sin_aceptacion", "control"])
async def test_sin_las_condiciones_no_hay_oferta(escenario):
    if escenario == "apagada":
        negocio, canal, filas = await _candidato("lo-no1", activar=False)
    elif escenario == "oferta_off":
        negocio, canal, filas = await _candidato("lo-no2", oferta="0")
    elif escenario == "sombra":
        negocio, canal, filas = await _candidato("lo-no3", activar=False)
        await _encender(negocio, "sombra", **{ll.CLAVE_OFERTA_ACTIVA: 1})
    elif escenario == "sin_aceptacion":
        negocio, canal, filas = await _candidato("lo-no4", activar=False)
        await _encender(negocio, "activo", aceptar=False, **{ll.CLAVE_OFERTA_ACTIVA: 1})
    else:
        negocio, canal, filas = await _candidato("lo-no5", holdout=100)
    assert await ll.preparar_ofertas(filas) == {}


async def test_con_la_ventana_de_24_horas_cerrada_no_se_envia_nada():
    negocio, canal, filas = await _candidato("lo-vent", horas=30)
    assert (await ll.preparar_ofertas(filas))[TEL] == {"accion": "omitir"}


async def test_maximo_una_oferta_por_ciclo():
    negocio, canal, filas = await _candidato("lo-una")
    oferta = (await ll.preparar_ofertas(filas))[TEL]
    await ll.registrar_oferta_enviada(TEL, negocio["id"], oferta)
    assert await ll.preparar_ofertas(filas) == {}
    (e,) = await _eventos(mem.EVENTO_LLAMADA_OFERTA_ENVIADA)
    assert e.payload["segmento"] == "A" and e.payload["texto"] == oferta["texto"]
    assert mem.EVENTO_LLAMADA_OFERTA_ENVIADA in [x["tipo"] for x in await mem.listar_eventos_lead(TEL)]   # evidencia visible


async def test_solo_los_segmentos_a_y_b_reciben_la_oferta():
    negocio, canal = await _negocio("lo-seg")
    guion = [("user", "Hola", 6.1), ("assistant", "Hola", 6.0)]
    await _lead(negocio, canal, guion=guion, nombre="Ana", producto_tipo="terma", paso=None)       # puntaje 3 = exploración
    await _activar(negocio, **{ll.CLAVE_OFERTA_ACTIVA: 1, ll.CLAVE_EXPLORACION_PCT: 100})
    assert await ll.preparar_ofertas([{"telefono": TEL, "negocio_id": negocio["id"]}]) == {}


async def test_un_error_al_preparar_la_oferta_no_rompe_nada(monkeypatch):
    negocio, canal, filas = await _candidato("lo-err")

    async def falla(*a, **k):
        raise RuntimeError("base caída")
    monkeypatch.setattr(ll, "leer_config", falla)
    assert await ll.preparar_ofertas(filas) == {}


def _cargar_script(nombre):
    spec = importlib.util.spec_from_file_location(f"script_{nombre}", RAIZ / "scripts" / f"{nombre}.py")
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


class _Proveedor:
    def __init__(self):
        self.enviados = []

    async def resolver_canal(self, numero_whatsapp_id, negocio_id=None):
        return {"phone_number_id": numero_whatsapp_id, "negocio_id": negocio_id}

    async def enviar_mensaje(self, telefono, mensaje, canal=None):
        self.enviados.append((telefono, mensaje))
        return True, f"wamid.lo{len(self.enviados)}"


async def _correr_script(monkeypatch, capsys):
    script = _cargar_script("procesar_inactividad_clientes")
    proveedor = _Proveedor()

    async def sondeo():
        return None

    async def abierto():
        return False

    async def emitir(_):
        return None
    monkeypatch.setattr(script.circuito_ia, "sondear_si_corresponde", sondeo)
    monkeypatch.setattr(script.circuito_ia, "esta_abierto", abierto)
    monkeypatch.setattr(script, "obtener_proveedor", lambda: proveedor)
    monkeypatch.setattr(script.gestor_conexiones, "emitir_mensaje_nuevo", emitir)
    await script.main()
    return proveedor, capsys.readouterr().out


async def test_el_script_manda_la_oferta_en_lugar_del_reenganche_y_deja_la_evidencia(monkeypatch, capsys):
    negocio, canal, filas = await _candidato("lo-script", horas=3)
    await _cfg(negocio, envios_modo_gabi_oferta_llamada="siempre")
    proveedor, salida = await _correr_script(monkeypatch, capsys)
    assert [m for _, m in proveedor.enviados if "llamarte" in m] and not [m for _, m in proveedor.enviados if "Hola de nuevo" in m]
    assert len(proveedor.enviados) == 1 and "1 oferta(s) de llamada" in salida
    async with mem.async_session() as s:
        envio = (await s.execute(select(mem.EnvioMeta).where(mem.EnvioMeta.telefono == TEL))).scalars().all()
    assert [e.origen for e in envio] == ["gabi_oferta_llamada"]
    assert len(await _eventos(mem.EVENTO_LLAMADA_OFERTA_ENVIADA)) == 1
    # la segunda corrida ya no manda otra (ni el reenganche genérico: ya hay 2 mensajes del bot tras el cliente)
    proveedor2, _ = await _correr_script(monkeypatch, capsys)
    assert proveedor2.enviados == []


async def test_el_script_con_la_oferta_apagada_manda_el_reenganche_de_siempre(monkeypatch, capsys):
    negocio, canal, filas = await _candidato("lo-script2", horas=3, oferta="0")
    await _cfg(negocio, envios_modo_reenganche_inactividad="siempre")
    proveedor, salida = await _correr_script(monkeypatch, capsys)
    assert [m for _, m in proveedor.enviados] == [_cargar_script("procesar_inactividad_clientes").MENSAJE_REENGANCHE]
    assert "oferta" not in salida
