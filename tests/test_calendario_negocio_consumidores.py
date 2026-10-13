# tests/test_calendario_negocio_consumidores.py — Calendario de negocio, Fase 1 (2026-10-12): cada consumidor del
# horario con un DÍA CERRADO por calendario (feriado): el estado de tools, el contexto de Gabi y el aviso de derivación,
# la asignación y la cola al abrir, la rotación 30+30, la atención atrasada (y el modo hábil), la pausa de Inicio, la
# plantilla de zona muerta, los correos y el modo sin IA; más los dos parámetros anti-avalancha (apagados por defecto).
#
# Los tests que usan la hora real cierran HOY (día de Lima) y el negocio tiene horario 00:00-23:59 todos los días, así
# que sin el feriado estaría abierto: lo único que cambia es el calendario. Datos sintéticos únicamente.

import json
import os
from datetime import date, datetime, timedelta

os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")
os.environ.setdefault("WHATSAPP_PROVIDER", "meta")

import pytest
from sqlalchemy import select, update

from agent import asignacion, brain, notificaciones, respaldo_sin_ia, tools
from agent import atencion_atrasada as aa
from agent import calendario_negocio as cn
from agent import dashboard, memory as mem
from agent import main as app_main


@pytest.fixture(autouse=True)
def _cache_limpia():
    mem.invalidar_cache_calendario()
    yield
    mem.invalidar_cache_calendario()


def _hoy() -> date:
    return mem.hoy_en_lima()


def lima(mes: int, dia: int, hora: int = 0, minuto: int = 0) -> datetime:
    """Instante UTC naive de una hora de Lima de 2026."""
    return datetime(2026, mes, dia, hora, minuto) + timedelta(hours=5)


async def _negocio_con_canal(codigo: str, telefono_canal: str):
    negocio = await mem.crear_negocio(f"Negocio {codigo}", codigo)
    canal = await mem.crear_canal_whatsapp(nombre=f"Canal {codigo}", phone_number_id=telefono_canal, negocio_id=negocio["id"])
    return negocio, canal


async def _siempre_abierto(negocio_id: str):
    for dia in range(7):
        await mem.guardar_horario_atencion(negocio_id, dia, True, "00:00", "23:59")


async def _dia(negocio_id: str, fecha: date, nombre: str = "Feriado de prueba", tipo: str = "feriado", atiende: bool = False,
               apertura: str | None = None, cierre: str | None = None):
    async with mem.async_session() as session:
        session.add(mem.DiaEspecial(
            negocio_id=negocio_id, fecha=fecha, tipo=tipo, nombre=nombre, atiende=atiende, hora_apertura=apertura, hora_cierre=cierre,
        ))
        await session.commit()
    mem.invalidar_cache_calendario(negocio_id)


async def _feriado_hoy(negocio_id: str, **kw):
    await _dia(negocio_id, _hoy(), **kw)


async def _lead(telefono: str):
    async with mem.async_session() as session:
        return await session.get(mem.Lead, telefono)


async def _derivado_sin_asesor(telefono: str, negocio: dict, canal: dict, hace_h: float):
    await mem.resolver_conversation_activa(telefono, negocio["id"], canal["id"])
    await mem.actualizar_lead(telefono, nombre="Cliente Test", negocio_id=negocio["id"], campos_explicitos=("paso_flujo",), paso_flujo="derivado_asesor")
    await _mensaje(telefono, negocio["id"], "user", hace_h)


async def _derivado_con_asesor(telefono: str, negocio: dict, canal: dict, asesor: str):
    await mem.resolver_conversation_activa(telefono, negocio["id"], canal["id"])
    await mem.actualizar_lead(telefono, nombre="Cliente Test", negocio_id=negocio["id"])
    await mem.asignar_asesor_a_lead(telefono, asesor, automatico=True)


async def _mensaje(telefono: str, negocio_id: str, role: str, hace_h: float | None = None, en: datetime | None = None):
    guardado = await mem.guardar_mensaje(telefono, role, "contenido de prueba", negocio_id)
    async with mem.async_session() as session:
        await session.execute(update(mem.Mensaje).where(mem.Mensaje.id == guardado["id"]).values(
            timestamp=en if en is not None else datetime.utcnow() - timedelta(hours=hace_h or 0),
        ))
        await session.commit()


# ── (a) tools: el estado de horario conoce los feriados ─────────────────────

async def test_el_estado_de_horario_dice_cerrado_motivo_nombre_y_cuando_vuelven():
    negocio, _ = await _negocio_con_canal("cc-a1", "41000000001")
    await _siempre_abierto(negocio["id"])
    assert (await tools.obtener_estado_horario_atencion(negocio["id"]))["dentro_de_horario"] is True

    await _feriado_hoy(negocio["id"], nombre="Combate de Angamos")
    estado = await tools.obtener_estado_horario_atencion(negocio["id"])
    assert estado["dentro_de_horario"] is False and estado["motivo"] == "feriado" and estado["nombre"] == "Combate de Angamos"
    assert estado["proxima_apertura"] is not None and "mañana" in estado["proxima_apertura_texto"]
    assert "(hora de Lima)" in estado["fecha_hora_lima"]               # las claves de siempre siguen ahí

    await mem.eliminar_dia_especial(negocio["id"], _hoy(), autor="admin1")
    assert (await tools.obtener_estado_horario_atencion(negocio["id"]))["dentro_de_horario"] is True


async def test_el_estado_acepta_una_hora_fija_y_el_horario_por_defecto_sin_filas():
    negocio, _ = await _negocio_con_canal("cc-a2", "41000000002")        # sin filas de horario: lunes a sábado 8:00-19:00
    await _dia(negocio["id"], date(2026, 10, 8))
    jueves_feriado = await tools.obtener_estado_horario_atencion(negocio["id"], ahora=lima(10, 8, 10))
    assert jueves_feriado["dentro_de_horario"] is False and jueves_feriado["motivo"] == "feriado"
    assert jueves_feriado["fecha_hora_lima"] == "jueves 08/10/2026, 10:00 (hora de Lima)"
    assert jueves_feriado["proxima_apertura_texto"] == "mañana a las 8:00 a. m."
    miercoles = await tools.obtener_estado_horario_atencion(negocio["id"], ahora=lima(10, 7, 10))
    assert miercoles["dentro_de_horario"] is True and miercoles["motivo"] is None
    miercoles_noche = await tools.obtener_estado_horario_atencion(negocio["id"], ahora=lima(10, 7, 21))
    assert miercoles_noche["motivo"] == "fuera_de_horario" and miercoles_noche["proxima_apertura_texto"] == "el viernes 9 a las 8:00 a. m."
    # también acepta un datetime con zona (el de Lima)
    aware = datetime(2026, 10, 8, 10, 0, tzinfo=tools.TZ_LIMA)
    assert (await tools.obtener_estado_horario_atencion(negocio["id"], ahora=aware))["motivo"] == "feriado"


async def test_la_proxima_apertura_salta_el_feriado_y_un_cierre_largo_de_mas_de_8_dias():
    negocio, _ = await _negocio_con_canal("cc-a3", "41000000003")
    await _dia(negocio["id"], date(2026, 10, 8))
    p = await tools.obtener_proxima_apertura(negocio["id"], ahora=datetime(2026, 10, 7, 21, 0, tzinfo=tools.TZ_LIMA))
    assert (p["dia"], p["hora"], p["dias_de_diferencia"], p["hoy_es_dia_de_atencion"]) == ("viernes", "8:00 a. m.", 2, True)
    assert p["texto"] == "el viernes 9 a las 8:00 a. m."
    p = await tools.obtener_proxima_apertura(negocio["id"], ahora=datetime(2026, 10, 8, 10, 0, tzinfo=tools.TZ_LIMA))
    assert (p["dia"], p["dias_de_diferencia"], p["hoy_es_dia_de_atencion"]) == ("viernes", 1, False)     # hoy cerrado por feriado
    assert p["motivo_hoy"] == "feriado"
    for d in range(12, 24):                                           # 12 días de cierre propio
        await _dia(negocio["id"], date(2026, 10, d), "Inventario", "cierre_propio")
    p = await tools.obtener_proxima_apertura(negocio["id"], ahora=datetime(2026, 10, 13, 10, 0, tzinfo=tools.TZ_LIMA))
    assert (p["dia"], p["dias_de_diferencia"]) == ("sábado", 11) and p["fecha"] == date(2026, 10, 24)


async def test_los_rangos_de_atencion_traen_el_calendario_completo():
    negocio, _ = await _negocio_con_canal("cc-a4", "41000000004")
    await _dia(negocio["id"], date(2026, 10, 8))
    rangos = await tools._rangos_de_atencion_por_dia(negocio["id"])
    assert rangos[0] == ("08:00", "19:00") and rangos[6] is None and isinstance(rangos, dict)
    assert date(2026, 10, 8) in rangos.calendario.excepciones
    # las funciones de atencion_atrasada (que usa llamadas.py) conocen el feriado a través de los mismos `rangos`
    assert aa.esta_abierto(rangos, lima(10, 7, 10)) and not aa.esta_abierto(rangos, lima(10, 8, 10))
    assert aa._tramo_del_dia(rangos, date(2026, 10, 8)) is None and aa._tramo_del_dia(rangos, date(2026, 10, 7)) is not None
    assert aa.proxima_apertura(rangos, lima(10, 8, 10)) == lima(10, 9, 8)
    assert aa.horas_de_atencion_abierta(rangos, lima(10, 7, 0), lima(10, 9, 0)) == 11


# ── (b) Gabi: contexto y aviso de derivación ────────────────────────────────

async def test_gabi_sabe_el_motivo_y_cuando_vuelven_los_asesores():
    negocio, _ = await _negocio_con_canal("cc-b1", "41000000011")
    await _siempre_abierto(negocio["id"])
    abierto = (await brain._armar_bloques_contexto("hola", [], None, negocio["id"]))[0]
    assert "DENTRO del horario" in abierto and "vuelven a atender" not in abierto

    await _feriado_hoy(negocio["id"], nombre="Combate de Angamos")
    cerrado = (await brain._armar_bloques_contexto("hola", [], None, negocio["id"]))[0]
    assert "FUERA del horario" in cerrado and "Hoy es feriado: Combate de Angamos." in cerrado
    assert "Los asesores humanos vuelven a atender mañana a las" in cerrado


def test_el_aviso_de_derivacion_fuera_de_horario_cita_la_hora_exacta_sin_prometer_plazos():
    texto = brain.obtener_mensaje_derivacion(False, "el viernes 9 a las 8:00 a. m.", "hoy es feriado: Combate de Angamos")
    assert "el viernes 9 a las 8:00 a. m." in texto and "hoy es feriado: Combate de Angamos" in texto and "horario de atención" in texto
    assert "minutos" not in texto and "en breve" not in texto.lower()
    sin_motivo = brain.obtener_mensaje_derivacion(False, "mañana a las 8:00 a. m.")
    assert "mañana a las 8:00 a. m." in sin_motivo and "(" not in sin_motivo
    # sin hora conocida: el texto de siempre ("apenas se reinicie")
    assert "apenas se reinicie" in brain.obtener_mensaje_derivacion(False)
    assert brain.obtener_mensaje_derivacion(True) != texto and "En breve" in brain.obtener_mensaje_derivacion(True)


class _ProveedorFalso:
    def __init__(self):
        self.enviados: list[str] = []

    async def enviar_mensaje(self, telefono, mensaje, canal=None, mensaje_id_citado=None):
        self.enviados.append(mensaje)
        return True, "wamid.OK"


async def _armar_derivacion(monkeypatch, codigo: str, telefono: str, respuesta_gabi: str):
    negocio, canal_db = await _negocio_con_canal(codigo, f"4101{codigo[-6:]}")
    await _siempre_abierto(negocio["id"])
    await _feriado_hoy(negocio["id"], nombre="Combate de Angamos")
    await mem.crear_usuario(f"ase_{codigo[-4:]}", "pw12345", "Asesor", "asesor", negocio["id"])
    canal = {"id": canal_db["id"], "negocio_id": negocio["id"], "unidad_id": None, "phone_number_id": canal_db["phone_number_id"], "modo": "produccion"}
    await mem.actualizar_lead(telefono, negocio_id=negocio["id"], numero_whatsapp_id="x")
    await mem.resolver_conversation_activa(telefono, negocio["id"], canal_db["id"])
    await mem.guardar_mensaje(telefono, "user", "pásame con un asesor", negocio_id=negocio["id"])
    proveedor = _ProveedorFalso()
    monkeypatch.setattr(app_main, "proveedor", proveedor)
    correos: list[str] = []

    async def gabi(mensaje, historial, lead, modo="produccion", negocio_id=None):
        return respuesta_gabi, False, None, None

    async def deriva(*a, **k):
        return {"paso_flujo": "derivado_asesor"}

    async def notificar(telefono, lead, texto):
        correos.append(telefono)

    monkeypatch.setattr(app_main.servicio_inteligencia, "generar_respuesta", gabi)
    monkeypatch.setattr(app_main.servicio_inteligencia, "extraer_datos_lead", deriva)
    monkeypatch.setattr(app_main, "notificar_lead_derivado", notificar)
    return negocio, canal, proveedor, correos


async def test_el_aviso_de_respaldo_al_derivar_un_feriado_dice_cuando_vuelve_el_equipo(monkeypatch):
    telefono = "51910100001"
    # Gabi NO menciona al asesor: el sistema manda el aviso de respaldo, que cita la hora exacta
    negocio, canal, proveedor, _ = await _armar_derivacion(monkeypatch, "cc-b2-000001", telefono, "Listo, ya tengo tus datos 😊")
    await app_main._generar_y_enviar_respuesta_ia(telefono, canal)
    aviso = proveedor.enviados[-1]
    assert "fuera del horario de atención" in aviso and "hoy es feriado: Combate de Angamos" in aviso
    assert "mañana a las" in aviso


# ── (c) asignación y cola al abrir ──────────────────────────────────────────

async def test_con_un_feriado_hoy_no_se_asigna_y_el_lead_queda_derivado_sin_asesor_con_gabi_activa(monkeypatch):
    telefono = "51910100002"
    negocio, canal, proveedor, correos = await _armar_derivacion(monkeypatch, "cc-c1-000002", telefono, "Te derivo con un asesor comercial 😊")
    assert await asignacion.elegir_asesor_automatico("", negocio["id"]) is None
    await app_main._generar_y_enviar_respuesta_ia(telefono, canal)
    lead = await _lead(telefono)
    assert lead.paso_flujo == "derivado_asesor" and lead.asesor_asignado is None
    assert lead.pausado_manual is False and lead.escalado_supervision_en is None and lead.derivado_en is None
    assert correos == [telefono]

    await mem.eliminar_dia_especial(negocio["id"], _hoy(), autor="admin1")      # se levanta el feriado
    assert await asignacion.elegir_asesor_automatico("", negocio["id"]) is not None


async def test_la_cola_al_abrir_no_asigna_en_feriado_y_reparte_al_levantarlo():
    negocio, canal = await _negocio_con_canal("cc-c2", "41000000021")
    await _siempre_abierto(negocio["id"])
    await mem.crear_usuario("ase_cc2", "pw12345", "Asesor", "asesor", negocio["id"])
    await _derivado_sin_asesor("51910100003", negocio, canal, 3)
    await _feriado_hoy(negocio["id"])
    assert (await asignacion.asignar_cola_pendiente_al_abrir())["asignados"] == []
    assert (await _lead("51910100003")).asesor_asignado is None
    await mem.eliminar_dia_especial(negocio["id"], _hoy(), autor="admin1")
    assert [t for t, _ in (await asignacion.asignar_cola_pendiente_al_abrir())["asignados"]] == ["51910100003"]


# ── (d) rotación 30+30: el reloj no avanza en día cerrado por calendario ─────

async def test_la_rotacion_suma_minutos_con_el_negocio_abierto_y_no_en_un_feriado():
    negocio, canal = await _negocio_con_canal("cc-d1", "41000000031")
    await _siempre_abierto(negocio["id"])
    await mem.crear_usuario("ase_cc_d1", "pw12345", "Asesor", "asesor", negocio["id"])
    await _derivado_con_asesor("51910100011", negocio, canal, "ase_cc_d1")

    await _feriado_hoy(negocio["id"])
    r = await mem.ejecutar_ciclo_de_espera(intervalo_minutos=5, umbral_rotacion_minutos=30)
    assert r["a_rotar"] == [] and (await _lead("51910100011")).minutos_espera_asesor == 0       # feriado: el reloj no avanza

    await mem.eliminar_dia_especial(negocio["id"], _hoy(), autor="admin1")
    await mem.ejecutar_ciclo_de_espera(intervalo_minutos=5, umbral_rotacion_minutos=30)
    assert (await _lead("51910100011")).minutos_espera_asesor == 5                               # abierto: avanza como siempre


async def test_un_feriado_con_horario_especial_deja_correr_el_reloj_solo_dentro_de_ese_horario():
    negocio, canal = await _negocio_con_canal("cc-d2", "41000000032")
    await _siempre_abierto(negocio["id"])
    await mem.crear_usuario("ase_cc_d2", "pw12345", "Asesor", "asesor", negocio["id"])
    await _derivado_con_asesor("51910100012", negocio, canal, "ase_cc_d2")
    ahora_lima = datetime.utcnow() - timedelta(hours=5)
    # horario especial de hoy que NO incluye el momento actual (empieza una hora después del cierre del día): cerrado
    await _feriado_hoy(negocio["id"], atiende=True, apertura="00:00", cierre="00:01")
    if ahora_lima.hour == 0 and ahora_lima.minute == 0:
        pytest.skip("el test cae justo en el único minuto abierto")
    await mem.ejecutar_ciclo_de_espera(intervalo_minutos=5, umbral_rotacion_minutos=30)
    assert (await _lead("51910100012")).minutos_espera_asesor == 0


# ── (e) atención atrasada y modo hábil ──────────────────────────────────────

RANGOS = {d: ("08:00", "19:00") for d in range(6)} | {6: None}


def test_el_tiempo_en_feriado_no_cuenta_para_atrasada_ni_urgente():
    cal = cn.calendario_desde_rangos(RANGOS, [cn.DiaEspecial(date(2026, 10, 8), "feriado", "Combate de Angamos")])
    # escribió el miércoles 7 a las 18:00 (1 h hábil ese día); el jueves 8 es feriado; el viernes 9 abre a las 8:00
    desde = lima(10, 7, 18)
    vence = desde + timedelta(days=30)                      # una ventana lejana: solo se prueba la demora
    viernes_8_30, viernes_9 = lima(10, 9, 8, 30), lima(10, 9, 9)
    # sin el feriado: 1 h + 11 h del jueves + 0,5 h = 12,5 h hábiles y más de 8 h de reloj → urgente (la avalancha de la mañana)
    assert aa.calcular_atencion(desde, vence, True, viernes_8_30, RANGOS)["nivel"] == "urgente"
    # con el feriado el jueves no cuenta: 1 h + 0,5 h = 1,5 h hábiles → todavía nada
    assert aa.calcular_atencion(desde, vence, True, viernes_8_30, cal)["nivel"] is None
    # a las 9:00 ya son 2 h hábiles (y 39 h de reloj): atrasada por horario y urgente por reloj, como siempre
    assert aa.calcular_atencion(desde, vence, True, viernes_9, cal)["nivel"] == "urgente"
    # en modo hábil, 2 h hábiles es solo «atrasada» (urgente pide 4 h hábiles)
    assert aa.calcular_atencion(desde, vence, True, viernes_9, cal, modo_habil=True)["nivel"] == "atrasada"
    assert aa.calcular_atencion(desde, vence, True, lima(10, 9, 11), cal, modo_habil=True)["nivel"] == "urgente"


def test_modo_habil_atrasada_2_h_y_urgente_4_h_habiles_y_la_ultima_llamada_sigue_de_reloj():
    vence = lambda desde: desde + timedelta(hours=24)
    desde = lima(10, 6, 9)
    def nivel(horas, **kw):
        ahora = desde + timedelta(hours=horas)
        return aa.calcular_atencion(desde, vence(desde), True, ahora, RANGOS, **kw)["nivel"]
    # clásico: urgente = 8 h de reloj; modo hábil: 4 h hábiles
    assert nivel(3) == "atrasada" and nivel(5) == "atrasada" and nivel(8) == "urgente"
    assert nivel(1.5, modo_habil=True) is None and nivel(3, modo_habil=True) == "atrasada"
    assert nivel(5, modo_habil=True) == "urgente" and nivel(9, modo_habil=True) == "urgente"
    # la noche no cuenta en modo hábil: escribió a las 17:00; a las 9:00 del día siguiente van 2 + 1 = 3 h hábiles
    tarde = lima(10, 6, 17)
    r = aa.calcular_atencion(tarde, tarde + timedelta(hours=24), True, lima(10, 7, 9), RANGOS, modo_habil=True)
    assert r["nivel"] == "atrasada"
    # la ventana de Meta es de reloj aun en modo hábil
    assert aa.calcular_atencion(desde, vence(desde), True, desde + timedelta(hours=19), RANGOS, modo_habil=True)["nivel"] == "ultima_llamada"
    assert aa.UMBRALES_HABILES_POR_DEFECTO == {"atrasada": 2.0, "urgente": 4.0, "ultima_llamada": 6.0}


def test_en_pausa_agrega_la_clave_solo_cuando_hay_pausa():
    desde = lima(10, 6, 9)
    sin = aa.calcular_atencion(desde, desde + timedelta(hours=24), True, desde + timedelta(hours=3), RANGOS)
    con = aa.calcular_atencion(desde, desde + timedelta(hours=24), True, desde + timedelta(hours=3), RANGOS, en_pausa=True)
    assert "en_pausa" not in sin and con == {**sin, "en_pausa": True}


async def _cliente_esperando(negocio, canal, telefono: str, hace_h: float, asesor: str | None = "asesor1"):
    await mem.resolver_conversation_activa(telefono, negocio["id"], canal["id"])
    await mem.actualizar_lead(telefono, nombre=f"Cliente {telefono[-4:]}", negocio_id=negocio["id"])
    async with mem.async_session() as session:
        lead = await session.get(mem.Lead, telefono)
        lead.asesor_asignado = asesor
        lead.paso_flujo = "derivado_asesor"
        await session.commit()
    await _mensaje(telefono, negocio["id"], "user", hace_h)


async def _atencion(negocio, telefono: str) -> dict:
    esperando = await mem.listar_clientes_esperando(negocio["id"])
    await aa.anotar_atencion(negocio["id"], esperando)
    return {c["telefono"]: c["atencion"] for c in esperando}[telefono]


async def test_un_cliente_no_se_vuelve_atrasado_por_horas_de_un_dia_cerrado_pero_la_ultima_llamada_si_corre():
    negocio, canal = await _negocio_con_canal("cc-e1", "41000000041")
    await _siempre_abierto(negocio["id"])
    await _cliente_esperando(negocio, canal, "51910100021", 10)          # 10 h esperando
    await _cliente_esperando(negocio, canal, "51910100022", 20)          # a su ventana le quedan 4 h
    assert (await _atencion(negocio, "51910100021"))["nivel"] == "urgente"

    for delta in (-1, 0, 1):
        await _dia(negocio["id"], _hoy() + timedelta(days=delta))        # ayer, hoy y mañana cerrados: ni una hora hábil
    atencion = await _atencion(negocio, "51910100021")
    assert atencion["nivel"] is None and atencion["en_pausa"] is True and atencion["edad_horas"] >= 9.9
    ultima = await _atencion(negocio, "51910100022")
    assert ultima["nivel"] == "ultima_llamada" and ultima["en_pausa"] is True      # el reloj de Meta no se pausa


async def test_el_modo_habil_solo_rige_desde_calendario_habil_desde():
    negocio, canal = await _negocio_con_canal("cc-e2", "41000000042")
    await _siempre_abierto(negocio["id"])
    await _cliente_esperando(negocio, canal, "51910100023", 5)
    assert (await _atencion(negocio, "51910100023"))["nivel"] == "atrasada"          # sin la clave: reglas de siempre (8 h de reloj)
    assert await aa.modo_habil_vigente(negocio["id"], datetime.utcnow()) is False

    await mem.fijar_calendario_habil_desde(negocio["id"], _hoy() + timedelta(days=1), autor="script")
    assert (await _atencion(negocio, "51910100023"))["nivel"] == "atrasada"          # vigencia a futuro: todavía no

    await mem.fijar_calendario_habil_desde(negocio["id"], _hoy(), autor="script")
    assert await aa.modo_habil_vigente(negocio["id"], datetime.utcnow()) is True
    assert (await _atencion(negocio, "51910100023"))["nivel"] == "urgente"           # 5 h hábiles >= 4 h

    await mem.guardar_configuracion(aa.CLAVE_URGENTE_HORAS_HABILES, "6", negocio_id=negocio["id"])      # configurable
    assert (await _atencion(negocio, "51910100023"))["nivel"] == "atrasada"
    await mem.guardar_configuracion(aa.CLAVE_URGENTE_HORAS_HABILES, "abc", negocio_id=negocio["id"])    # inválido: cae al 4
    assert (await _atencion(negocio, "51910100023"))["nivel"] == "urgente"
    await mem.guardar_configuracion(aa.CLAVE_ATRASADA_HORAS_HABILES, "10", negocio_id=negocio["id"])
    await mem.guardar_configuracion(aa.CLAVE_URGENTE_HORAS_HABILES, "20", negocio_id=negocio["id"])
    assert (await _atencion(negocio, "51910100023"))["nivel"] is None


# ── (f) Inicio: pausa y campana ─────────────────────────────────────────────

async def _usuario(negocio, username: str, rol: str):
    await mem.crear_usuario(username, "pw12345", username.title(), rol, negocio["id"])
    return await mem.obtener_usuario(username, negocio_id=negocio["id"])


async def _inicio(usuario: dict) -> dict:
    return json.loads((await dashboard.inicio_json(usuario=usuario)).body)


async def test_inicio_en_dia_normal_no_tiene_pausa_y_el_contrato_de_siempre_sigue_igual():
    negocio, canal = await _negocio_con_canal("cc-f1", "41000000051")
    await _siempre_abierto(negocio["id"])
    await _cliente_esperando(negocio, canal, "51910100031", 3)
    admin = await _usuario(negocio, "admin_f1", "admin")
    datos = await _inicio(admin)
    zona = datos["zona_accion"]
    assert zona["pausa"] is None and zona["totales"]["atencion_en_pausa"] == 0
    assert not [a for a in datos["avisos"] if a["id"] == "calendario_pausa"]
    assert zona["totales"]["atencion_campana"] == 1 and zona["totales"]["esperando_campana"] == 1
    assert {"cliente_esperando", "ventana_abierta", "atencion_atrasada", "atencion_total", "atencion_ventana_cerrada"} <= zona["totales"].keys()
    assert "en_pausa" not in next(i for i in zona["items"] if i["categoria"] == "cliente_esperando")["atencion"]


async def test_inicio_con_pausa_la_campana_no_suma_y_muestra_una_sola_entrada_informativa():
    negocio, canal = await _negocio_con_canal("cc-f2", "41000000052")
    await _siempre_abierto(negocio["id"])
    await _cliente_esperando(negocio, canal, "51910100032", 10)          # urgente si el negocio atendiera
    await _cliente_esperando(negocio, canal, "51910100033", 20)          # última llamada (reloj de Meta)
    await _cliente_esperando(negocio, canal, "51910100034", 1)
    admin = await _usuario(negocio, "admin_f2", "admin")
    antes = (await _inicio(admin))["zona_accion"]["totales"]
    assert antes["atencion_campana"] == 2 and antes["esperando_campana"] == 3

    for delta in (-1, 0, 1):
        await _dia(negocio["id"], _hoy() + timedelta(days=delta), nombre="Combate de Angamos")
    datos = await _inicio(admin)
    zona, t = datos["zona_accion"], datos["zona_accion"]["totales"]
    assert zona["pausa"]["motivo"] == "feriado" and zona["pausa"]["nombre"] == "Combate de Angamos"
    assert zona["pausa"]["reanuda_en"].endswith("Z") and zona["pausa"]["reanuda_texto"]
    assert t["atencion_en_pausa"] == 3
    assert t["atencion_campana"] == 1 and t["atencion_campana_urgentes"] == 1        # solo la última llamada: es de Meta
    assert t["esperando_campana"] == 0                                               # la campana no suma «clientes esperando»
    assert t["cliente_esperando"] == 3 and t["ventana_abierta"] == 3                 # el resto del contrato no cambia
    entradas = [a for a in datos["avisos"] if a["id"] == "calendario_pausa"]
    assert len(entradas) == 1 and entradas[0]["nivel"] == "info" and entradas[0]["enlace"] is None
    assert entradas[0]["titulo"] == "Hoy es feriado: Combate de Angamos"
    assert entradas[0]["detalle"].startswith("3 clientes esperan; se atienden ")
    # la pausa es del negocio: la ve también un asesor
    asesor = await _usuario(negocio, "asesor1", "asesor")
    assert (await _inicio(asesor))["zona_accion"]["pausa"]["motivo"] == "feriado"


def test_el_aviso_de_pausa_singular_y_sin_clientes():
    pausa = {"motivo": "no_laborable", "nombre": "Elecciones", "reanuda_en": "2026-10-13T13:00:00Z", "reanuda_texto": "mañana a las 8:00 a. m."}
    assert dashboard._aviso_pausa_calendario(None, 5) is None
    uno = dashboard._aviso_pausa_calendario(pausa, 1)
    assert uno["titulo"] == "Hoy es día no laborable: Elecciones" and uno["detalle"] == "1 cliente espera; se atienden mañana a las 8:00 a. m."
    assert "No hay clientes esperando" in dashboard._aviso_pausa_calendario(pausa, 0)["detalle"]


# ── (g) zona muerta ─────────────────────────────────────────────────────────

async def _cliente_zona_muerta(negocio, canal, telefono: str, escribio: datetime):
    await mem.resolver_conversation_activa(telefono, negocio["id"], canal["id"])
    await mem.actualizar_lead(telefono, nombre="Cliente", negocio_id=negocio["id"])
    async with mem.async_session() as session:
        lead = await session.get(mem.Lead, telefono)
        lead.asesor_asignado = "asesor1"
        lead.paso_flujo = "derivado_asesor"
        await session.commit()
    await _mensaje(telefono, negocio["id"], "user", en=escribio)


async def test_zona_muerta_marca_candidatos_en_un_feriado_y_en_su_vispera():
    negocio, canal = await _negocio_con_canal("cc-g1", "41000000061")      # horario por defecto: lunes a sábado 8:00-19:00
    await _dia(negocio["id"], date(2026, 10, 8), nombre="Combate de Angamos")
    # escribió el martes 6 a las 20:00 → su ventana cierra el miércoles 7 a las 20:00
    await _cliente_zona_muerta(negocio, canal, "51910100041", lima(10, 6, 20))
    # y otro que escribió el miércoles 7 a las 12:00 → su ventana cierra el jueves 8 (feriado) a las 12:00
    await _cliente_zona_muerta(negocio, canal, "51910100042", lima(10, 7, 12))

    # miércoles 10:00, abierto y sin víspera (faltan 9 h para cerrar): nadie
    assert await aa.candidatos_zona_muerta(negocio["id"], ahora=lima(10, 7, 10)) == []
    # miércoles 18:00 = VÍSPERA del feriado (cierra a las 19:00 y mañana está cerrado por excepción): marca al primero,
    # que ya está a 2 h de perder la ventana y nadie abre antes de que cierre
    candidatos = await aa.candidatos_zona_muerta(negocio["id"], ahora=lima(10, 7, 18))
    assert [(c["telefono"], c["momento"]) for c in candidatos] == [("51910100041", "vispera")]
    # jueves 8 a las 10:00 (feriado, cerrado todo el día): el segundo ve cerrarse su ventana en 2 h sin que nadie abra
    candidatos = await aa.candidatos_zona_muerta(negocio["id"], ahora=lima(10, 8, 10))
    assert [(c["telefono"], c["momento"]) for c in candidatos] == [("51910100042", "cerrado")]


async def test_zona_muerta_en_un_dia_normal_sigue_igual_que_antes():
    negocio, canal = await _negocio_con_canal("cc-g2", "41000000062")
    await _cliente_zona_muerta(negocio, canal, "51910100043", lima(10, 7, 12))
    assert await aa.candidatos_zona_muerta(negocio["id"], ahora=lima(10, 8, 10)) == []        # abierto y sin feriado: nadie
    # domingo 10:00 con otro cliente (escribió el sábado 12:00, su ventana cierra el domingo 12:00): cerrado hasta el
    # lunes → candidato, como siempre
    await _cliente_zona_muerta(negocio, canal, "51910100044", lima(10, 10, 12))
    r = await aa.candidatos_zona_muerta(negocio["id"], ahora=lima(10, 11, 10))
    assert "51910100044" in {c["telefono"] for c in r} and all(c["momento"] == "cerrado" for c in r)


def test_la_vispera_solo_vale_antes_de_un_cierre_por_excepcion():
    cal = cn.calendario_desde_rangos(RANGOS, [cn.DiaEspecial(date(2026, 10, 8), "feriado", "X")])
    assert aa._en_vispera_de_cierre(lima(10, 7, 17), cal) and aa._en_vispera_de_cierre(lima(10, 7, 18, 59), cal)
    assert not aa._en_vispera_de_cierre(lima(10, 7, 16, 59), cal)         # faltan más de 2 h
    assert not aa._en_vispera_de_cierre(lima(10, 6, 18), cal)             # mañana es día normal
    assert not aa._en_vispera_de_cierre(lima(10, 10, 18), cal)            # sábado: mañana es domingo (descanso normal, no excepción)


# ── (h) correos y modo sin IA ───────────────────────────────────────────────

class _Respuesta:
    status_code = 200
    text = "ok"


async def test_el_correo_de_derivacion_en_un_feriado_dice_el_motivo_y_cuando_vuelve_el_equipo(monkeypatch):
    negocio, _ = await _negocio_con_canal("cc-h1", "41000000071")
    await _siempre_abierto(negocio["id"])
    await _feriado_hoy(negocio["id"], nombre="Combate <de> Angamos")
    enviados = []

    async def post(url, json=None, headers=None):
        enviados.append(json)
        return _Respuesta()

    monkeypatch.setattr(notificaciones, "RESEND_API_KEY", "clave-de-prueba")
    monkeypatch.setattr(notificaciones, "DESTINATARIOS", ["equipo@example.com"])
    monkeypatch.setattr(notificaciones, "post_con_reintentos", post)
    assert await notificaciones.notificar_lead_derivado("51940000001", {"nombre": "Cliente", "negocio_id": negocio["id"]}, "hola")
    html = enviados[0]["html"]
    assert "No hay asesor en turno" in html and "primer asesor que abra turno" in html          # el texto de siempre
    assert "Hoy es feriado: Combate &lt;de&gt; Angamos." in html and "El equipo vuelve a atender mañana a las" in html
    # en un día normal el correo no agrega nada
    await mem.eliminar_dia_especial(negocio["id"], _hoy(), autor="admin1")
    assert await notificaciones._detalle_del_cierre(negocio["id"]) == ""
    assert await notificaciones._detalle_del_cierre(None) == ""


async def test_el_modo_sin_ia_en_un_feriado_cita_el_proximo_dia_habil():
    negocio, _ = await _negocio_con_canal("cc-h2", "41000000072")
    await _siempre_abierto(negocio["id"])
    await _feriado_hoy(negocio["id"], nombre="Combate de Angamos")
    texto = await respaldo_sin_ia._texto_para_el_cliente(negocio["id"], "Ana")
    assert "Ana" in texto and "te atenderá el" in texto and "desde las 12:00 a. m." in texto            # abre mañana a las 00:00
    # el cierre largo (12 días) cita también la fecha
    for d in range(1, 13):
        await _dia(negocio["id"], _hoy() + timedelta(days=d), "Inventario", "cierre_propio")
    texto = await respaldo_sin_ia._texto_para_el_cliente(negocio["id"], "Ana")
    destino = _hoy() + timedelta(days=13)
    assert f"{destino.day} de {cn.MESES_ES[destino.month - 1]}" in texto


# ── Anti-avalancha ──────────────────────────────────────────────────────────

async def test_la_cola_al_abrir_con_tope_de_activos_por_asesor_no_los_satura():
    negocio, canal = await _negocio_con_canal("cc-i1", "41000000081")
    await _siempre_abierto(negocio["id"])
    await mem.crear_usuario("ase_i1a", "pw12345", "A", "asesor", negocio["id"])
    await mem.crear_usuario("ase_i1b", "pw12345", "B", "asesor", negocio["id"])
    for i in range(12):
        await _derivado_sin_asesor(f"519102000{i:02d}", negocio, canal, 3 + i / 10)

    # sin el parámetro (0): se reparten hasta el tope por corrida (10), como siempre
    sin_tope = await asignacion.asignar_cola_pendiente_al_abrir()
    assert len(sin_tope["asignados"]) == 10 and sin_tope["pendientes"] == 2


async def test_la_cola_con_tope_de_3_activos_por_asesor_reparte_6_y_deja_6_en_espera():
    negocio, canal = await _negocio_con_canal("cc-i2", "41000000082")
    await _siempre_abierto(negocio["id"])
    await mem.crear_usuario("ase_i2a", "pw12345", "A", "asesor", negocio["id"])
    await mem.crear_usuario("ase_i2b", "pw12345", "B", "asesor", negocio["id"])
    await mem.guardar_configuracion(asignacion.CLAVE_COLA_MAX_ACTIVOS_POR_ASESOR, "3", negocio_id=negocio["id"])
    telefonos = [f"519103000{i:02d}" for i in range(12)]
    for i, t in enumerate(telefonos):
        await _derivado_sin_asesor(t, negocio, canal, 3 + i / 10)

    r = await asignacion.asignar_cola_pendiente_al_abrir()
    por_asesor = {}
    for _, asesor in r["asignados"]:
        por_asesor[asesor] = por_asesor.get(asesor, 0) + 1
    assert por_asesor == {"ase_i2a": 3, "ase_i2b": 3} and r["pendientes"] == 6
    assert await asignacion.asignar_cola_pendiente_al_abrir() == {"asignados": [], "pendientes": 6}     # tope alcanzado: nadie más

    # cuando un asesor despeja un caso (le pone resultado), recibe otro de la cola
    primero = r["asignados"][0][0]
    await mem.actualizar_lead(primero, campos_explicitos=("resultado",), resultado="sin_respuesta")
    r2 = await asignacion.asignar_cola_pendiente_al_abrir()
    assert len(r2["asignados"]) == 1 and r2["pendientes"] == 5


async def test_el_tope_de_activos_se_ignora_si_el_valor_es_invalido_o_cero():
    negocio, _ = await _negocio_con_canal("cc-i3", "41000000083")
    assert await asignacion._max_activos_por_asesor(negocio["id"]) == 0
    await mem.guardar_configuracion(asignacion.CLAVE_COLA_MAX_ACTIVOS_POR_ASESOR, "basura", negocio_id=negocio["id"])
    assert await asignacion._max_activos_por_asesor(negocio["id"]) == 0
    await mem.guardar_configuracion(asignacion.CLAVE_COLA_MAX_ACTIVOS_POR_ASESOR, "-4", negocio_id=negocio["id"])
    assert await asignacion._max_activos_por_asesor(negocio["id"]) == 0


async def test_la_avalancha_de_12_leads_con_2_asesores_no_rota_a_nadie_antes_de_tiempo_con_los_parametros_activos():
    negocio, canal = await _negocio_con_canal("cc-i4", "41000000084")
    await _siempre_abierto(negocio["id"])
    for a in ("ase_i4a", "ase_i4b"):
        await mem.crear_usuario(a, "pw12345", a, "asesor", negocio["id"])
    await mem.guardar_configuracion(asignacion.CLAVE_COLA_MAX_ACTIVOS_POR_ASESOR, "3", negocio_id=negocio["id"])
    await mem.guardar_configuracion(mem.CLAVE_ROTACION_RELOJ_MAX_CASOS, "2", negocio_id=negocio["id"])
    for i in range(12):
        await _derivado_sin_asesor(f"519104000{i:02d}", negocio, canal, 3 + i / 10)

    await asignacion.asignar_cola_pendiente_al_abrir()          # 3 + 3 asignados, 6 en cola
    rotados = (await asignacion.ejecutar_ciclo_de_rotacion(intervalo_minutos=30, umbral_rotacion_minutos=30))["rotados"]
    # con los dos parámetros activos solo 2 casos por asesor corren el reloj: 4 rotan (y no los 12 de golpe)
    assert len(rotados) == 4
    async with mem.async_session() as session:
        en_fila = [l for l in (await session.execute(select(mem.Lead))).scalars().all()
                   if l.asesor_asignado and l.derivado_en is not None and l.minutos_espera_asesor == 0 and l.veces_rotado_espera == 0]
    assert len(en_fila) == 2          # el tercer caso de cada asesor sigue «en fila», sin minutos corridos


async def test_la_rotacion_con_tope_de_casos_solo_corre_el_reloj_de_los_mas_antiguos():
    negocio, canal = await _negocio_con_canal("cc-i5", "41000000085")
    await _siempre_abierto(negocio["id"])
    await mem.crear_usuario("ase_i5", "pw12345", "A", "asesor", negocio["id"])
    telefonos = [f"519105000{i:02d}" for i in range(6)]
    for t in telefonos:
        await _derivado_con_asesor(t, negocio, canal, "ase_i5")
    await mem.guardar_configuracion(mem.CLAVE_ROTACION_RELOJ_MAX_CASOS, "2", negocio_id=negocio["id"])

    r = await mem.ejecutar_ciclo_de_espera(intervalo_minutos=30, umbral_rotacion_minutos=30)
    assert [c["telefono"] for c in r["a_rotar"]] == telefonos[:2]                     # los 2 más antiguos
    assert [(await _lead(t)).minutos_espera_asesor for t in telefonos] == [30, 30, 0, 0, 0, 0]


async def test_la_rotacion_sin_el_parametro_corre_el_reloj_de_todos_como_siempre():
    negocio, canal = await _negocio_con_canal("cc-i6", "41000000086")
    await _siempre_abierto(negocio["id"])
    await mem.crear_usuario("ase_i6", "pw12345", "A", "asesor", negocio["id"])
    telefonos = [f"519106000{i:02d}" for i in range(6)]
    for t in telefonos:
        await _derivado_con_asesor(t, negocio, canal, "ase_i6")
    r = await mem.ejecutar_ciclo_de_espera(intervalo_minutos=30, umbral_rotacion_minutos=30)
    assert len(r["a_rotar"]) == 6
    await mem.guardar_configuracion(mem.CLAVE_ROTACION_RELOJ_MAX_CASOS, "basura", negocio_id=negocio["id"])
    assert len((await mem.ejecutar_ciclo_de_espera(intervalo_minutos=30, umbral_rotacion_minutos=30))["a_rotar"]) == 6


# ── Lo que NO se pausa: los relojes del cliente ─────────────────────────────

async def test_el_reenganche_y_el_cierre_por_inactividad_del_cliente_no_se_pausan_en_feriado():
    negocio, canal = await _negocio_con_canal("cc-n1", "41000000091")
    await _siempre_abierto(negocio["id"])
    await _feriado_hoy(negocio["id"])
    for tel, paso in (("51910109001", "explorando"), ("51910109002", "comparando_producto")):
        await mem.resolver_conversation_activa(tel, negocio["id"], canal["id"])
        await mem.actualizar_lead(tel, nombre="Cliente Test", negocio_id=negocio["id"])
        await mem.actualizar_lead(tel, negocio_id=negocio["id"], campos_explicitos=("paso_flujo",), paso_flujo=paso)
    await _mensaje("51910109001", negocio["id"], "user", 3)
    await _mensaje("51910109001", negocio["id"], "assistant", 2.9)
    await _mensaje("51910109002", negocio["id"], "user", 20)
    await _mensaje("51910109002", negocio["id"], "assistant", 19.9)

    reenganche, cierre = await mem.listar_leads_inactividad_cliente(horas_reenganche=2.0, horas_cierre=15.0)

    assert {c["telefono"] for c in reenganche} == {"51910109001"}      # el reenganche de 2 h corre aunque hoy sea feriado
    assert {c["telefono"] for c in cierre} == {"51910109002"}          # y el cierre de 15 h también


async def test_la_ventana_de_24_h_de_meta_no_depende_del_calendario():
    negocio, canal = await _negocio_con_canal("cc-n2", "41000000092")
    await _siempre_abierto(negocio["id"])
    await _cliente_esperando(negocio, canal, "51910109003", 3)
    await _feriado_hoy(negocio["id"])
    esperando = {c["telefono"]: c for c in await mem.listar_clientes_esperando(negocio["id"])}
    c = esperando["51910109003"]
    assert c["ventana_abierta"] is True and 20.9 < (c["ventana_vence_en"] - datetime.utcnow()).total_seconds() / 3600 < 21.1
