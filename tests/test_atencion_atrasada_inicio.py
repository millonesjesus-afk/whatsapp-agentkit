# tests/test_atencion_atrasada_inicio.py — Atención atrasada en Inicio (2026-10-07, Q2).
#
# `listar_clientes_esperando` trae `esperando_desde`; `agent/atencion_atrasada.py` calcula `atencion`
# ({nivel, edad_horas, ventana_restante_horas}) al vuelo y `GET /dashboard/inicio.json` lo expone de forma
# ADITIVA (por ítem y en `zona_accion.totales`), más graves primero.
#
# Datos sintéticos únicamente.

import json
from datetime import datetime, timedelta

from sqlalchemy import update

from agent import atencion_atrasada as aa
from agent import dashboard, memory as mem

# Lunes a sábado 8:00-19:00 (hora de Lima), como el horario real del negocio.
RANGOS = {d: ("08:00", "19:00") for d in range(6)} | {6: None}


def lima(dia: int, hora: int, minuto: int = 0, mes: int = 10) -> datetime:
    """Instante UTC naive de una hora de Lima de 2026 (5/10 = lunes, 10/10 = sábado)."""
    return datetime(2026, mes, dia, hora, minuto) + timedelta(hours=5)


def _h(horas: float) -> timedelta:
    return timedelta(hours=horas)


# ── Horas de horario de atención ────────────────────────────────────────────

def test_horas_de_atencion_abierta_solo_cuenta_el_horario_del_negocio():
    # viernes 17:00 → sábado 10:00: 2 h del viernes + 2 h del sábado
    assert aa.horas_de_atencion_abierta(RANGOS, lima(9, 17), lima(10, 10)) == 4
    # sábado 18:00 → lunes 9:00: 1 h del sábado, el domingo cerrado, 1 h del lunes
    assert aa.horas_de_atencion_abierta(RANGOS, lima(10, 18), lima(12, 9)) == 2
    # todo dentro de la noche / del domingo
    assert aa.horas_de_atencion_abierta(RANGOS, lima(10, 20), lima(11, 23)) == 0
    assert aa.horas_de_atencion_abierta(RANGOS, lima(9, 10), lima(9, 9)) == 0


def test_esta_abierto_y_proxima_apertura():
    assert aa.esta_abierto(RANGOS, lima(10, 18, 59)) and not aa.esta_abierto(RANGOS, lima(10, 19))
    assert not aa.esta_abierto(RANGOS, lima(11, 12))
    assert aa.proxima_apertura(RANGOS, lima(10, 19, 30)) == lima(12, 8)   # sábado noche → lunes 8:00
    assert aa.proxima_apertura(RANGOS, lima(12, 7, 59)) == lima(12, 8)
    assert aa.proxima_apertura(RANGOS, lima(12, 9)) == lima(13, 8)         # abierto ahora → la del día siguiente
    assert aa.proxima_apertura({d: None for d in range(7)}, lima(12, 9)) is None


# ── Niveles ─────────────────────────────────────────────────────────────────

def _atencion(desde: datetime, ahora: datetime, vence: datetime | None = None, rangos=RANGOS, umbrales=None) -> dict:
    ultimo = vence - _h(24) if vence else desde
    vence = vence or ultimo + _h(24)
    return aa.calcular_atencion(desde, vence, vence > ahora, ahora, rangos, umbrales)


def test_sin_nivel_cuando_lleva_poco_tiempo_esperando():
    r = _atencion(lima(6, 10), lima(6, 11))
    assert r == {"nivel": None, "edad_horas": 1.0, "ventana_restante_horas": 23.0}


def test_atrasada_desde_2_horas_de_horario_abierto():
    r = _atencion(lima(6, 10), lima(6, 13))
    assert r["nivel"] == "atrasada" and r["edad_horas"] == 3.0 and r["ventana_restante_horas"] == 21.0


def test_atrasada_no_cuenta_las_horas_con_el_negocio_cerrado():
    # escribió el lunes 20:00; el martes 9:00 han pasado 13 h de reloj pero solo 1 h con el negocio abierto
    assert _atencion(lima(5, 20), lima(6, 9))["nivel"] is None
    # el martes 10:30 ya son 2,5 h de horario abierto (y más de 8 h de reloj) → urgente
    assert _atencion(lima(5, 20), lima(6, 10, 30))["nivel"] == "urgente"


def test_urgente_con_8_horas_de_reloj_y_atrasada_por_horario():
    assert _atencion(lima(6, 8, 30), lima(6, 16))["nivel"] == "atrasada"        # 7,5 h
    r = _atencion(lima(6, 8, 30), lima(6, 17, 30))                              # 9 h
    assert r["nivel"] == "urgente" and r["edad_horas"] == 9.0


def test_ultima_llamada_cuando_a_la_ventana_le_quedan_menos_de_6_horas():
    r = _atencion(lima(6, 9), lima(7, 4), vence=lima(7, 9))   # le quedan 5 h; el negocio ni abrió desde las 19:00
    assert r["nivel"] == "ultima_llamada" and r["ventana_restante_horas"] == 5.0
    # con 6 h justas todavía no es "última llamada"
    assert _atencion(lima(6, 9), lima(7, 3), vence=lima(7, 9))["nivel"] == "urgente"


def test_ultima_llamada_gana_sobre_los_demas_aunque_el_negocio_estuviera_cerrado():
    # escribió el sábado 19:30: vence el domingo 19:30; el domingo 15:00 le quedan 4,5 h y nadie pudo atenderlo
    r = _atencion(lima(10, 19, 30), lima(11, 15), vence=lima(11, 19, 30))
    assert r["nivel"] == "ultima_llamada" and r["ventana_restante_horas"] == 4.5


def test_con_la_ventana_cerrada_es_urgente_aunque_nadie_pudiera_atenderlo():
    # escribió el sábado 20:00; el lunes 8:30 la ventana (domingo 20:00) ya cerró y solo hubo 30 min de horario abierto
    r = _atencion(lima(10, 20), lima(12, 8, 30), vence=lima(11, 20))
    assert r["nivel"] == "urgente" and r["ventana_restante_horas"] is None and r["edad_horas"] == 36.5


def test_los_umbrales_son_configurables():
    umbrales = {"atrasada": 1.0, "urgente": 4.0, "ultima_llamada": 2.0}
    assert _atencion(lima(6, 10), lima(6, 11, 30), umbrales=umbrales)["nivel"] == "atrasada"
    assert _atencion(lima(6, 10), lima(6, 14, 30), umbrales=umbrales)["nivel"] == "urgente"
    assert _atencion(lima(6, 9), lima(7, 8), vence=lima(7, 9), umbrales=umbrales)["nivel"] == "ultima_llamada"


# ── esperando_desde (memory) ────────────────────────────────────────────────

async def _negocio(codigo: str, canal_id: str, *, horario_siempre: bool = True):
    negocio = await mem.crear_negocio(f"Negocio {codigo}", codigo)
    canal = await mem.crear_canal_whatsapp(nombre=f"Canal {codigo}", phone_number_id=canal_id, negocio_id=negocio["id"])
    if horario_siempre:   # abierto las 24 h: la hora de reloj y la de horario coinciden (casi) siempre
        for dia in range(7):
            await mem.guardar_horario_atencion(negocio["id"], dia, True, "00:00", "23:59")
    return negocio, canal


async def _lead(negocio, canal, telefono: str, *, asesor: str | None = "asesor1", resultado: str | None = None, escalado=False):
    await mem.resolver_conversation_activa(telefono, negocio["id"], canal["id"])
    await mem.actualizar_lead(telefono, nombre=f"Cliente {telefono[-4:]}", negocio_id=negocio["id"])
    async with mem.async_session() as session:
        lead = await session.get(mem.Lead, telefono)
        lead.asesor_asignado = asesor
        lead.resultado = resultado
        lead.paso_flujo = "derivado_asesor"
        if escalado:
            lead.escalado_supervision_en = datetime.utcnow()
        await session.commit()


async def _mensaje(negocio, telefono: str, role: str, contenido: str, hace: timedelta, estado_envio: str | None = None):
    m = await mem.guardar_mensaje(telefono, role, contenido, negocio["id"], estado_envio=estado_envio)
    async with mem.async_session() as session:
        await session.execute(update(mem.Mensaje).where(mem.Mensaje.id == m["id"]).values(timestamp=datetime.utcnow() - hace))
        await session.commit()


async def _desde(negocio, telefono: str):
    return {c["telefono"]: c for c in await mem.listar_clientes_esperando(negocio["id"])}[telefono]["esperando_desde"]


async def test_esperando_desde_es_el_primer_mensaje_del_cliente_tras_la_ultima_respuesta():
    negocio, canal = await _negocio("aa-1", "40200000001")
    tel = "51920000001"
    await _lead(negocio, canal, tel)
    await _mensaje(negocio, tel, "user", "hola", _h(30))
    await _mensaje(negocio, tel, "assistant", "te atiende un asesor", _h(29))
    await _mensaje(negocio, tel, "user", "sigo esperando", _h(5))
    await _mensaje(negocio, tel, "user", "¿alguien?", _h(3))
    desde = await _desde(negocio, tel)
    assert abs((datetime.utcnow() - desde) - _h(5)) < timedelta(seconds=30)


async def test_esperando_desde_ignora_envios_fallidos_y_reacciones_y_sin_respuesta_usa_el_primer_mensaje():
    negocio, canal = await _negocio("aa-2", "40200000002")
    tel = "51920000002"
    await _lead(negocio, canal, tel)
    await _mensaje(negocio, tel, "user", "hola", _h(10))
    await _mensaje(negocio, tel, "asesor", "te respondo", _h(9), estado_envio="fallido")   # no llegó: no cuenta
    await _mensaje(negocio, tel, "user", "Reaccionó con 👍", _h(8))                         # no es un mensaje real
    await _mensaje(negocio, tel, "user", "¿me ayudan?", _h(2))
    assert abs((datetime.utcnow() - await _desde(negocio, tel)) - _h(10)) < timedelta(seconds=30)


# ── Inicio ──────────────────────────────────────────────────────────────────

async def _usuario(negocio, username: str, rol: str):
    await mem.crear_usuario(username, "pw12345", username.title(), rol, negocio["id"])
    return await mem.obtener_usuario(username, negocio_id=negocio["id"])


async def _inicio(usuario: dict) -> dict:
    return json.loads((await dashboard.inicio_json(usuario=usuario)).body)


async def test_inicio_expone_atencion_por_item_y_totales_aditivos_mas_graves_primero():
    negocio, canal = await _negocio("aa-3", "40200000003")
    # (teléfono, horas desde su último mensaje, nivel esperado)
    casos = [("51930000001", 1, None), ("51930000002", 3, "atrasada"), ("51930000003", 10, "urgente"), ("51930000004", 20, "ultima_llamada")]
    for tel, horas, _nivel in casos:
        await _lead(negocio, canal, tel)
        await _mensaje(negocio, tel, "user", "necesito ayuda", _h(horas))
    admin = await _usuario(negocio, "admin1", "admin")

    datos = await _inicio(admin)
    items = {i["telefono"]: i for i in datos["zona_accion"]["items"] if i["categoria"] == "cliente_esperando"}
    for tel, horas, nivel in casos:
        atencion = items[tel]["atencion"]
        assert atencion["nivel"] == nivel and abs(atencion["edad_horas"] - horas) < 0.1, (tel, atencion)
    assert items["51930000004"]["atencion"]["ventana_restante_horas"] == 4.0 or abs(items["51930000004"]["atencion"]["ventana_restante_horas"] - 4.0) < 0.1

    totales = datos["zona_accion"]["totales"]
    assert totales["atencion_atrasada"] == 1 and totales["atencion_urgente"] == 1 and totales["atencion_ultima_llamada"] == 1
    assert totales["atencion_total"] == 3 and totales["atencion_campana"] == 3 and totales["atencion_campana_urgentes"] == 2
    # el contrato de siempre sigue ahí
    assert totales["cliente_esperando"] == 4 and totales["ventana_por_vencer"] == 1
    assert {"telefono", "conversation_id", "nombre", "motivo", "categoria", "ventana_vence_en"} <= items["51930000002"].keys()

    # orden: última llamada, urgente, atrasada, sin nivel
    orden = [i["telefono"] for i in datos["zona_accion"]["items"] if i["categoria"] == "cliente_esperando"]
    assert orden == ["51930000004", "51930000003", "51930000002", "51930000001"]


async def test_los_mas_graves_entran_en_el_tope_de_items_aunque_haya_muchos_esperando():
    negocio, canal = await _negocio("aa-4", "40200000004")
    for i in range(10):    # 10 recientes: llenarían el tope de 8
        tel = f"519400000{i:02d}"
        await _lead(negocio, canal, tel)
        await _mensaje(negocio, tel, "user", "hola", _h(0.2 + i * 0.01))
    await _lead(negocio, canal, "51940000099")
    await _mensaje(negocio, "51940000099", "user", "hola", _h(9))
    admin = await _usuario(negocio, "admin2", "admin")
    items = [i for i in (await _inicio(admin))["zona_accion"]["items"] if i["categoria"] == "cliente_esperando"]
    assert len(items) == dashboard.TOPES_ZONA_ACCION["cliente_esperando"]
    assert items[0]["telefono"] == "51940000099" and items[0]["atencion"]["nivel"] == "urgente"


async def test_el_asesor_ve_solo_los_suyos_y_el_admin_todos():
    negocio, canal = await _negocio("aa-5", "40200000005")
    await _lead(negocio, canal, "51950000001", asesor="ana")
    await _lead(negocio, canal, "51950000002", asesor="beto")
    for tel in ("51950000001", "51950000002"):
        await _mensaje(negocio, tel, "user", "hola", _h(4))
    ana = await _usuario(negocio, "ana", "asesor")
    admin = await _usuario(negocio, "admin3", "admin")

    t_ana = (await _inicio(ana))["zona_accion"]["totales"]
    t_admin = (await _inicio(admin))["zona_accion"]["totales"]
    assert t_ana["atencion_atrasada"] == 1 and t_ana["atencion_total"] == 1
    assert t_admin["atencion_atrasada"] == 2 and t_admin["atencion_total"] == 2


async def test_un_escalado_que_espera_tambien_muestra_su_atencion_y_cuenta_en_los_totales():
    negocio, canal = await _negocio("aa-6", "40200000006")
    await _lead(negocio, canal, "51960000001", asesor=None, escalado=True)
    await _mensaje(negocio, "51960000001", "user", "nadie me responde", _h(12))
    admin = await _usuario(negocio, "admin4", "admin")
    datos = await _inicio(admin)
    escalado = next(i for i in datos["zona_accion"]["items"] if i["categoria"] == "escalado")
    assert escalado["atencion"]["nivel"] == "urgente"
    assert datos["zona_accion"]["totales"]["atencion_urgente"] == 1


async def test_los_umbrales_de_configuracion_se_respetan_y_un_valor_invalido_cae_al_defecto():
    negocio, canal = await _negocio("aa-7", "40200000007")
    await _lead(negocio, canal, "51970000001")
    await _mensaje(negocio, "51970000001", "user", "hola", _h(1.5))
    admin = await _usuario(negocio, "admin5", "admin")
    assert (await _inicio(admin))["zona_accion"]["totales"]["atencion_total"] == 0     # 1,5 h < 2 h por defecto

    await mem.guardar_configuracion(aa.CLAVE_ATRASADA_HORAS, "1", negocio_id=negocio["id"])
    assert (await _inicio(admin))["zona_accion"]["totales"]["atencion_atrasada"] == 1

    await mem.guardar_configuracion(aa.CLAVE_ATRASADA_HORAS, "abc", negocio_id=negocio["id"])
    assert (await _inicio(admin))["zona_accion"]["totales"]["atencion_total"] == 0


async def test_un_cliente_sin_asesor_ni_pausa_no_esta_esperando_y_no_trae_atencion():
    negocio, canal = await _negocio("aa-8", "40200000008")
    await _lead(negocio, canal, "51980000001", asesor=None)
    await _mensaje(negocio, "51980000001", "user", "hola", _h(30))
    admin = await _usuario(negocio, "admin6", "admin")
    totales = (await _inicio(admin))["zona_accion"]["totales"]
    assert totales["cliente_esperando"] == 0 and totales["atencion_total"] == 0
