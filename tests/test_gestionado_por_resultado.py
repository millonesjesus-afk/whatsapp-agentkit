# tests/test_gestionado_por_resultado.py — R4 (2026-10-07): lo urgente no se mezcla con lo olvidado.
#
# Caso real de producción: "Responde ahora" tenía 13 clientes; 11 con la ventana de 24 h de WhatsApp CERRADA y la
# mayoría ya con un resultado puesto por una persona. Se prueba:
#   1. Gestionado por resultado / venta / "Ya lo atendí": el cliente deja de esperar si el evento es igual o
#      POSTERIOR a su último mensaje real (por timestamp, nunca booleano); si escribe después, vuelve a esperar;
#      un resultado quitado no cuenta.
#   2. Ventana cerrada != urgente: el nivel es `ventana_cerrada`, jamás atrasada/urgente.
#   3. POST /dashboard/conversation/{id}/atendido: permisos, CSRF, idempotencia, 404, motivo.
#   4. Grupos de la zona de acción ("responde_ahora" / "ventana_cerrada"), topes y totales aditivos.
#   5. Vistas de la Bandeja `responde_ahora` (solo ventana abierta) y `ventana_cerrada`, con paridad de totales.
#
# Datos sintéticos únicamente.

import json
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import select, update

from agent import atencion_atrasada as aa
from agent import dashboard, memory as mem


# ── Helpers ──────────────────────────────────────────────────────────────

def _h(horas: float) -> timedelta:
    return timedelta(hours=horas)


async def _negocio(codigo: str, canal_id: str):
    negocio = await mem.crear_negocio(f"Negocio {codigo}", codigo)
    canal = await mem.crear_canal_whatsapp(nombre=f"Canal {codigo}", phone_number_id=canal_id, negocio_id=negocio["id"])
    for dia in range(7):   # abierto las 24 h: la hora de reloj y la de horario coinciden
        await mem.guardar_horario_atencion(negocio["id"], dia, True, "00:00", "23:59")
    await _usuario(negocio, f"admin-{codigo}", "admin")
    return negocio, canal


async def _usuario(negocio, username: str, rol: str):
    await mem.crear_usuario(username, "pw12345", username.title(), rol, negocio["id"])
    return await mem.obtener_usuario(username, negocio_id=negocio["id"])


async def _admin(negocio, codigo: str):
    return await mem.obtener_usuario(f"admin-{codigo}", negocio_id=negocio["id"])


async def _lead(negocio, canal, telefono: str, *, asesor: str | None = "asesor1", resultado: str | None = None,
                escalado: bool = False, paso_flujo: str = "derivado_asesor"):
    await mem.resolver_conversation_activa(telefono, negocio["id"], canal["id"])
    await mem.actualizar_lead(telefono, nombre=f"Cliente {telefono[-4:]}", negocio_id=negocio["id"])
    async with mem.async_session() as session:
        lead = await session.get(mem.Lead, telefono)
        lead.asesor_asignado = asesor
        lead.resultado = resultado
        lead.paso_flujo = paso_flujo
        if escalado:
            lead.escalado_supervision_en = datetime.utcnow()
        await session.commit()
    # `resolver_conversation_operable`/los permisos leen la asignación de la Conversation, no la del Lead.
    async with mem.async_session() as session:
        await session.execute(
            update(mem.Conversation).where(mem.Conversation.id == await _conv_id(negocio, telefono)).values(asesor_asignado_id=asesor)
        )
        await session.commit()


async def _mensaje(negocio, telefono: str, role: str, contenido: str, hace: timedelta):
    m = await mem.guardar_mensaje(telefono, role, contenido, negocio["id"])
    async with mem.async_session() as session:
        await session.execute(update(mem.Mensaje).where(mem.Mensaje.id == m["id"]).values(timestamp=datetime.utcnow() - hace))
        await session.commit()


async def _conv_id(negocio, telefono: str) -> str:
    return (await mem.resolver_conversation_ids_por_telefono(negocio["id"], [telefono]))[telefono]


async def _evento(negocio, telefono: str, tipo: str, hace: timedelta, payload: dict | None = None):
    """Inserta un EventoLead en la conversación activa del teléfono, con `creado` controlado."""
    conv_id = await _conv_id(negocio, telefono)
    async with mem.async_session() as session:
        session.add(mem.EventoLead(
            negocio_id=negocio["id"], conversation_id=conv_id, tipo=tipo, descripcion=tipo, autor="Ana",
            payload=payload, creado=datetime.utcnow() - hace,
        ))
        await session.commit()


async def _esperando(negocio) -> dict[str, dict]:
    return {c["telefono"]: c for c in await mem.listar_clientes_esperando(negocio["id"])}


async def _inicio(usuario: dict) -> dict:
    return json.loads((await dashboard.inicio_json(usuario=usuario)).body)


def _request(**query):
    return SimpleNamespace(query_params=query)


async def _bandeja(usuario: dict, **kw) -> dict:
    args = dict(
        request=_request(), usuario=usuario, q="", asesor="", alcance="", resultado="", orden="actividad",
        dir="desc", pagina=1, por_pagina=dashboard.POR_PAGINA_PIPELINE,
    )
    args.update(kw)
    return json.loads((await dashboard.bandeja_conversaciones(**args)).body)


def _telefonos(cuerpo: dict) -> list[str]:
    return [f["telefono"] for f in cuerpo["conversaciones"]]


async def _eventos(conv_id: str, tipo: str) -> list:
    async with mem.async_session() as session:
        return (await session.execute(
            select(mem.EventoLead).where(mem.EventoLead.conversation_id == conv_id, mem.EventoLead.tipo == tipo)
        )).scalars().all()


# ── 1. Gestionado por resultado / venta / "Ya lo atendí" ─────────────────

async def test_un_resultado_puesto_despues_del_ultimo_mensaje_saca_al_cliente_de_esperando():
    negocio, canal = await _negocio("gr1", "40500000001")
    await _lead(negocio, canal, "51910000001")
    await _mensaje(negocio, "51910000001", "user", "Quiero una cocina", _h(30))
    assert "51910000001" in await _esperando(negocio)

    await _evento(negocio, "51910000001", "resultado_cambiado", _h(5), {"campo": "resultado", "anterior": None, "nuevo": "no_interesado"})
    assert "51910000001" not in await _esperando(negocio)


async def test_si_el_cliente_escribe_despues_del_resultado_vuelve_a_esperar():
    negocio, canal = await _negocio("gr2", "40500000002")
    await _lead(negocio, canal, "51910000002")
    await _mensaje(negocio, "51910000002", "user", "Hola", _h(30))
    await _evento(negocio, "51910000002", "resultado_cambiado", _h(20), {"anterior": None, "nuevo": "sin_respuesta"})
    assert "51910000002" not in await _esperando(negocio)

    await _mensaje(negocio, "51910000002", "user", "Sigo interesado", _h(2))   # DESPUÉS del evento
    assert "51910000002" in await _esperando(negocio)


async def test_un_evento_anterior_al_ultimo_mensaje_no_cubre_ese_mensaje():
    negocio, canal = await _negocio("gr3", "40500000003")
    await _lead(negocio, canal, "51910000003")
    await _evento(negocio, "51910000003", "resultado_cambiado", _h(10), {"nuevo": "agendado"})
    await _mensaje(negocio, "51910000003", "user", "Una consulta más", _h(1))
    assert "51910000003" in await _esperando(negocio)


async def test_un_resultado_quitado_no_cuenta_como_gestion():
    negocio, canal = await _negocio("gr4", "40500000004")
    await _lead(negocio, canal, "51910000004")
    await _mensaje(negocio, "51910000004", "user", "Hola", _h(30))
    await _evento(negocio, "51910000004", "resultado_cambiado", _h(5), {"campo": "resultado", "anterior": "agendado", "nuevo": None})
    assert "51910000004" in await _esperando(negocio)
    await _evento(negocio, "51910000004", "resultado_cambiado", _h(4), {"campo": "resultado", "anterior": "agendado", "nuevo": ""})
    assert "51910000004" in await _esperando(negocio)
    # sin payload tampoco
    await _evento(negocio, "51910000004", "resultado_cambiado", _h(3), None)
    assert "51910000004" in await _esperando(negocio)


async def test_venta_registrada_y_atendido_manual_tambien_sacan_al_cliente():
    negocio, canal = await _negocio("gr5", "40500000005")
    await _lead(negocio, canal, "51910000005", resultado="vendido")
    await _lead(negocio, canal, "51910000006")
    await _lead(negocio, canal, "51910000007")
    for tel in ("51910000005", "51910000006", "51910000007"):
        await _mensaje(negocio, tel, "user", "Hola", _h(30))
    await _evento(negocio, "51910000005", "venta_registrada", _h(10), {"modalidad_pago": "contado"})
    await _evento(negocio, "51910000006", mem.EVENTO_ATENDIDO_MANUAL, _h(10), {})
    # otro tipo de evento (asignación) NO es gestión
    await _evento(negocio, "51910000007", "asignado", _h(10), {"nuevo": "asesor1"})
    assert set(await _esperando(negocio)) == {"51910000007"}


async def test_vendido_que_escribe_despues_de_la_venta_si_espera():
    """El matiz del test 'vendido y agendado siempre aparecen': la venta cubre el mensaje de antes, no el de después."""
    negocio, canal = await _negocio("gr6", "40500000006")
    await _lead(negocio, canal, "51910000008", resultado="vendido")
    await _mensaje(negocio, "51910000008", "user", "Ya pagué, gracias por todo", _h(30))
    await _evento(negocio, "51910000008", "venta_registrada", _h(25), {"modalidad_pago": "contado"})
    assert "51910000008" not in await _esperando(negocio)
    await _mensaje(negocio, "51910000008", "user", "Se dañó la hornilla", _h(1))
    espera = await _esperando(negocio)
    assert "51910000008" in espera and espera["51910000008"]["resultado"] == "vendido"


async def test_el_evento_de_otra_conversacion_o_negocio_no_oculta():
    negocio, canal = await _negocio("gr7", "40500000007")
    otro, canal_otro = await _negocio("gr7b", "40500000008")
    await _lead(negocio, canal, "51910000009")
    await _lead(otro, canal_otro, "51910000010")
    await _mensaje(negocio, "51910000009", "user", "Hola", _h(30))
    await _evento(otro, "51910000010", "resultado_cambiado", _h(5), {"nuevo": "agendado"})
    assert "51910000009" in await _esperando(negocio)


async def test_ya_lo_atendi_tambien_saca_al_lead_de_sin_asesor_y_reaparece_si_el_cliente_escribe():
    negocio, canal = await _negocio("gr8", "40500000009")
    await _lead(negocio, canal, "51910000011", asesor=None)
    await _mensaje(negocio, "51910000011", "user", "Necesito ayuda", _h(6))
    assert [l["telefono"] for l in await mem.listar_leads_esperando_asesor(negocio["id"])] == ["51910000011"]
    await _evento(negocio, "51910000011", mem.EVENTO_ATENDIDO_MANUAL, _h(2), {})
    assert await mem.listar_leads_esperando_asesor(negocio["id"]) == []
    # con excluir_atendidos=False (reparto) sigue visible
    assert len(await mem.listar_leads_esperando_asesor(negocio["id"], excluir_atendidos=False)) == 1
    await _mensaje(negocio, "51910000011", "user", "¿Hola?", _h(0.5))
    assert [l["telefono"] for l in await mem.listar_leads_esperando_asesor(negocio["id"])] == ["51910000011"]


async def test_un_resultado_abierto_no_le_quita_al_lead_sin_asesor_su_necesidad_de_dueno():
    negocio, canal = await _negocio("gr9", "40500000010")
    await _lead(negocio, canal, "51910000012", asesor=None)
    await _mensaje(negocio, "51910000012", "user", "Hola", _h(6))
    await _evento(negocio, "51910000012", "resultado_cambiado", _h(2), {"nuevo": "agendado"})
    assert len(await mem.listar_leads_esperando_asesor(negocio["id"])) == 1


# ── 2. Ventana cerrada != urgente ────────────────────────────────────────

RANGOS = {d: ("00:00", "23:59") for d in range(7)}


def _calc(edad_h: float, ventana_abierta: bool, restante_h: float = 0.0):
    ahora = datetime(2026, 10, 7, 12, 0)
    desde = ahora - _h(edad_h)
    vence = ahora + _h(restante_h) if ventana_abierta else ahora - _h(1)
    return aa.calcular_atencion(desde, vence, ventana_abierta, ahora, RANGOS)


def test_con_la_ventana_cerrada_jamas_es_urgente_ni_atrasada_aunque_lleve_dias():
    for edad in (1, 5, 30, 24 * 3, 24 * 14):
        r = _calc(edad, False)
        assert r["nivel"] == "ventana_cerrada" and r["ventana_restante_horas"] is None and r["edad_horas"] == float(edad)


def test_urgente_atrasada_y_ultima_llamada_solo_con_la_ventana_abierta():
    assert _calc(10, True, restante_h=14)["nivel"] == "urgente"
    assert _calc(3, True, restante_h=21)["nivel"] == "atrasada"
    assert _calc(20, True, restante_h=4)["nivel"] == "ultima_llamada"
    assert _calc(0.5, True, restante_h=23.5)["nivel"] is None


def test_una_ventana_que_vence_justo_ahora_cuenta_como_cerrada():
    ahora = datetime(2026, 10, 7, 12, 0)
    r = aa.calcular_atencion(ahora - _h(24), ahora, True, ahora, RANGOS)
    assert r["nivel"] == "ventana_cerrada" and r["ventana_restante_horas"] is None


# ── 3. Endpoint "Ya lo atendí" ───────────────────────────────────────────

async def test_atendido_registra_el_evento_con_autor_y_motivo_y_saca_al_cliente():
    negocio, canal = await _negocio("at1", "40500000011")
    admin = await _admin(negocio, "at1")
    await _lead(negocio, canal, "51920000001")
    await _mensaje(negocio, "51920000001", "user", "Hola", _h(30))
    conv_id = await _conv_id(negocio, "51920000001")

    respuesta = await dashboard.conversation_atendido(conv_id, motivo="  Lo llamé por teléfono  ", usuario=admin, _csrf=None)
    assert json.loads(respuesta.body) == {"ok": True}
    eventos = await _eventos(conv_id, "atendido_manual")
    assert len(eventos) == 1 and len("atendido_manual") == 15
    assert eventos[0].autor == admin["nombre"] and eventos[0].payload == {"motivo": "Lo llamé por teléfono"}
    assert "51920000001" not in await _esperando(negocio)


async def test_atendido_sin_motivo_y_con_el_default_del_form():
    negocio, canal = await _negocio("at2", "40500000012")
    admin = await _admin(negocio, "at2")
    await _lead(negocio, canal, "51920000002")
    conv_id = await _conv_id(negocio, "51920000002")
    # llamada directa sin el campo: `motivo` llega como el objeto Form por defecto (no es str)
    respuesta = await dashboard.conversation_atendido(conv_id, usuario=admin, _csrf=None)
    assert json.loads(respuesta.body) == {"ok": True}
    assert (await _eventos(conv_id, "atendido_manual"))[0].payload == {}


async def test_atendido_es_idempotente_hasta_que_el_cliente_escriba_de_nuevo():
    negocio, canal = await _negocio("at3", "40500000013")
    admin = await _admin(negocio, "at3")
    await _lead(negocio, canal, "51920000003")
    await _mensaje(negocio, "51920000003", "user", "Hola", _h(30))
    conv_id = await _conv_id(negocio, "51920000003")

    for _ in range(3):
        assert json.loads((await dashboard.conversation_atendido(conv_id, motivo="", usuario=admin, _csrf=None)).body) == {"ok": True}
    assert len(await _eventos(conv_id, "atendido_manual")) == 1

    async with mem.async_session() as session:   # el "Ya lo atendí" se hizo hace 2 h
        await session.execute(
            update(mem.EventoLead).where(mem.EventoLead.conversation_id == conv_id).values(creado=datetime.utcnow() - _h(2))
        )
        await session.commit()
    await _mensaje(negocio, "51920000003", "user", "¿Y mi cocina?", _h(0.1))
    assert "51920000003" in await _esperando(negocio)
    await dashboard.conversation_atendido(conv_id, motivo="", usuario=admin, _csrf=None)
    assert len(await _eventos(conv_id, "atendido_manual")) == 2
    assert "51920000003" not in await _esperando(negocio)


async def test_atendido_permisos_asesor_dueno_supervisor_admin_si_asesor_ajeno_403():
    negocio, canal = await _negocio("at4", "40500000014")
    await _lead(negocio, canal, "51920000004", asesor="dueno")
    conv_id = await _conv_id(negocio, "51920000004")
    dueno = await _usuario(negocio, "dueno", "asesor")
    ajeno = await _usuario(negocio, "ajeno", "asesor")
    supervisor = await _usuario(negocio, "super1", "supervisor")

    with pytest.raises(HTTPException) as exc:
        await dashboard.conversation_atendido(conv_id, motivo="", usuario=ajeno, _csrf=None)
    assert exc.value.status_code == 403
    assert await _eventos(conv_id, "atendido_manual") == []

    assert json.loads((await dashboard.conversation_atendido(conv_id, motivo="", usuario=dueno, _csrf=None)).body) == {"ok": True}
    assert json.loads((await dashboard.conversation_atendido(conv_id, motivo="", usuario=supervisor, _csrf=None)).body) == {"ok": True}
    assert len(await _eventos(conv_id, "atendido_manual")) == 1   # idempotente entre usuarios


async def test_atendido_404_si_no_existe_o_es_de_otro_negocio():
    negocio, canal = await _negocio("at5", "40500000015")
    otro, canal_otro = await _negocio("at5b", "40500000016")
    admin_otro = await _admin(otro, "at5b")
    await _lead(negocio, canal, "51920000005")
    conv_id = await _conv_id(negocio, "51920000005")

    for cid in ("no-existe", conv_id):
        with pytest.raises(HTTPException) as exc:
            await dashboard.conversation_atendido(cid, motivo="", usuario=admin_otro, _csrf=None)
        assert exc.value.status_code == 404
    assert await _eventos(conv_id, "atendido_manual") == []


async def test_atendido_rechaza_un_motivo_de_mas_de_200_caracteres():
    negocio, canal = await _negocio("at6", "40500000017")
    admin = await _admin(negocio, "at6")
    await _lead(negocio, canal, "51920000006")
    conv_id = await _conv_id(negocio, "51920000006")
    with pytest.raises(HTTPException) as exc:
        await dashboard.conversation_atendido(conv_id, motivo="x" * 201, usuario=admin, _csrf=None)
    assert exc.value.status_code == 400
    assert await _eventos(conv_id, "atendido_manual") == []
    await dashboard.conversation_atendido(conv_id, motivo="x" * 200, usuario=admin, _csrf=None)
    assert len(await _eventos(conv_id, "atendido_manual")) == 1


def test_atendido_exige_csrf_como_las_rutas_vecinas():
    def _dependencias(sufijo: str) -> set[str]:
        ruta = next(r for r in dashboard.router.routes if getattr(r, "path", "").endswith(sufijo))
        assert "POST" in ruta.methods
        return {d.call.__name__ for d in ruta.dependant.dependencies}

    atendido = _dependencias("/conversation/{conversation_id}/atendido")
    assert "verificar_csrf" in atendido
    assert atendido == _dependencias("/conversation/{conversation_id}/cerrar-definitivamente")


# ── 4. Grupos, topes y totales de la zona de acción ──────────────────────

async def _escenario_grupos(codigo: str, canal_id: str, abiertos: int, cerrados: int):
    """`abiertos` clientes con la ventana abierta (el i-ésimo escribió hace 1 + i h) y `cerrados` con la ventana
    cerrada (el i-ésimo escribió hace 30 + 10 i h: i=0 es el más reciente)."""
    negocio, canal = await _negocio(codigo, canal_id)
    for i in range(abiertos):
        tel = f"5193{i:07d}"
        await _lead(negocio, canal, tel)
        await _mensaje(negocio, tel, "user", "Hola", _h(1 + i))
    for i in range(cerrados):
        tel = f"5194{i:07d}"
        await _lead(negocio, canal, tel)
        await _mensaje(negocio, tel, "user", "Hola", _h(30 + 10 * i))
    return negocio, canal


async def test_la_zona_de_accion_separa_los_grupos_con_su_tope_y_su_orden():
    negocio, _ = await _escenario_grupos("gz1", "40500000020", abiertos=10, cerrados=7)
    admin = await _admin(negocio, "gz1")
    zona = (await _inicio(admin))["zona_accion"]
    esperando = [i for i in zona["items"] if i["categoria"] == "cliente_esperando"]

    abiertos = [i for i in esperando if i["grupo"] == "responde_ahora"]
    cerrados = [i for i in esperando if i["grupo"] == "ventana_cerrada"]
    assert dashboard.TOPES_ZONA_ACCION["cliente_esperando"] == 8
    assert dashboard.TOPES_ZONA_ACCION["cliente_esperando_ventana_cerrada"] == 5
    assert len(abiertos) == 8 and len(cerrados) == 5 and len(esperando) == 13
    assert all(i["ventana_abierta"] is True for i in abiertos)
    assert all(i["ventana_abierta"] is False and i["atencion"]["nivel"] == "ventana_cerrada" for i in cerrados)
    # los de ventana cerrada: del más reciente al más antiguo
    assert [i["telefono"] for i in cerrados] == [f"5194{i:07d}" for i in range(5)]
    # la lista sigue plana y los abiertos van antes que los cerrados
    assert esperando == abiertos + cerrados
    # dentro de "responde ahora" el orden por gravedad se mantiene (urgente 8+ h primero)
    gravedades = [{None: 0, "atrasada": 1, "urgente": 2, "ultima_llamada": 3}[i["atencion"]["nivel"]] for i in abiertos]
    assert gravedades == sorted(gravedades, reverse=True)


async def test_totales_aditivos_y_los_de_siempre_conservan_su_significado():
    negocio, _ = await _escenario_grupos("gz2", "40500000021", abiertos=10, cerrados=7)
    t = (await _inicio(await _admin(negocio, "gz2")))["zona_accion"]["totales"]
    assert t["esperando_ventana_abierta"] == 10 and t["esperando_ventana_cerrada"] == 7
    assert t["atencion_ventana_cerrada"] == 7
    # contratos viejos intactos
    assert t["cliente_esperando"] == 17 and t["ahora_total"] == 17 and t["ventana_abierta"] == 10
    assert t["esperando_campana"] == 17   # abiertos + cerrados hace < 72 h (el más viejo lleva 66 h cerrada: entra)
    # atención: SOLO ventana abierta en los de siempre
    assert t["atencion_total"] == t["atencion_atrasada"] + t["atencion_urgente"] + t["atencion_ultima_llamada"]
    assert t["atencion_campana"] <= 10 and t["atencion_campana_urgentes"] <= t["atencion_campana"]
    assert t["responde_ahora_total"] == 10


async def test_atencion_campana_cuenta_solo_ventana_abierta_y_esperando_campana_no_cambia():
    negocio, canal = await _negocio("gz3", "40500000022")
    await _lead(negocio, canal, "51950000001")
    await _mensaje(negocio, "51950000001", "user", "Hola", _h(10))     # abierta, urgente
    await _lead(negocio, canal, "51950000002")
    await _mensaje(negocio, "51950000002", "user", "Hola", _h(40))     # cerrada hace 16 h: dentro de la campana
    await _lead(negocio, canal, "51950000003")
    await _mensaje(negocio, "51950000003", "user", "Hola", _h(24 * 8))  # cerrada hace días: fuera de la campana
    t = (await _inicio(await _admin(negocio, "gz3")))["zona_accion"]["totales"]
    assert t["esperando_campana"] == 2          # la regla de la campana (72 h) no se toca
    assert t["atencion_campana"] == 1 and t["atencion_campana_urgentes"] == 1
    assert t["atencion_urgente"] == 1 and t["atencion_ventana_cerrada"] == 2
    assert t["cliente_esperando"] == 3


async def test_un_cliente_con_la_ventana_cerrada_hace_dias_ya_no_es_urgente_en_inicio():
    negocio, canal = await _negocio("gz4", "40500000023")
    await _lead(negocio, canal, "51960000001")
    await _mensaje(negocio, "51960000001", "user", "Hola", _h(24 * 9))
    zona = (await _inicio(await _admin(negocio, "gz4")))["zona_accion"]
    item = next(i for i in zona["items"] if i["categoria"] == "cliente_esperando")
    assert item["grupo"] == "ventana_cerrada" and item["atencion"]["nivel"] == "ventana_cerrada"
    assert item["atencion"]["ventana_restante_horas"] is None and item["atencion"]["edad_horas"] > 24 * 8
    assert zona["totales"]["atencion_urgente"] == 0 and zona["totales"]["atencion_total"] == 0


async def test_un_cliente_gestionado_sale_de_los_dos_grupos_y_de_los_totales():
    negocio, canal = await _negocio("gz5", "40500000024")
    await _lead(negocio, canal, "51970000001")
    await _lead(negocio, canal, "51970000002")
    await _mensaje(negocio, "51970000001", "user", "Hola", _h(40))
    await _mensaje(negocio, "51970000002", "user", "Hola", _h(2))
    admin = await _admin(negocio, "gz5")
    antes = (await _inicio(admin))["zona_accion"]["totales"]
    assert antes["esperando_ventana_cerrada"] == 1 and antes["esperando_ventana_abierta"] == 1

    await _evento(negocio, "51970000001", "resultado_cambiado", _h(10), {"nuevo": "no_interesado"})
    await _evento(negocio, "51970000002", mem.EVENTO_ATENDIDO_MANUAL, _h(1), {})
    zona = (await _inicio(admin))["zona_accion"]
    assert zona["vacio"] is True
    t = zona["totales"]
    assert t["cliente_esperando"] == 0 and t["esperando_ventana_abierta"] == 0 and t["esperando_ventana_cerrada"] == 0
    assert t["atencion_ventana_cerrada"] == 0 and t["ahora_total"] == 0 and t["responde_ahora_total"] == 0


# ── 5. Vistas de la Bandeja ──────────────────────────────────────────────

async def _escenario_vistas(codigo: str, canal_id: str):
    negocio, canal = await _negocio(codigo, canal_id)
    await _lead(negocio, canal, "51980000001")                                # abierta (vence antes)
    await _lead(negocio, canal, "51980000002")                                # abierta
    await _lead(negocio, canal, "51980000003")                                # cerrada, reciente
    await _lead(negocio, canal, "51980000004")                                # cerrada, antigua
    await _lead(negocio, canal, "51980000005", asesor=None, escalado=True)    # escalado con ventana cerrada
    await _lead(negocio, canal, "51980000006", asesor=None)                   # sin asesor, sin mensajes
    await _mensaje(negocio, "51980000001", "user", "Hola", _h(20))
    await _mensaje(negocio, "51980000002", "user", "Hola", _h(2))
    await _mensaje(negocio, "51980000003", "user", "Hola", _h(30))
    await _mensaje(negocio, "51980000004", "user", "Hola", _h(100))
    await _mensaje(negocio, "51980000005", "user", "Hola", _h(50))
    return negocio


async def test_responde_ahora_incluye_solo_ventana_abierta_mas_escalados_y_sin_asesor():
    negocio = await _escenario_vistas("gv1", "40500000030")
    admin = await _admin(negocio, "gv1")
    inicio = await _inicio(admin)
    cuerpo = await _bandeja(admin, vista="responde_ahora")

    assert _telefonos(cuerpo) == ["51980000005", "51980000006", "51980000001", "51980000002"]
    assert [f["inicio"]["categoria"] for f in cuerpo["conversaciones"]] == [
        "escalado", "sin_asesor", "cliente_esperando", "cliente_esperando",
    ]
    assert [f["inicio"]["ventana_abierta"] for f in cuerpo["conversaciones"][2:]] == [True, True]
    # paridad con el bloque "Responde ahora" de Inicio
    assert cuerpo["total"] == inicio["zona_accion"]["totales"]["responde_ahora_total"] == 4


async def test_la_vista_ventana_cerrada_lista_los_cerrados_del_mas_reciente_al_mas_antiguo():
    negocio = await _escenario_vistas("gv2", "40500000031")
    admin = await _admin(negocio, "gv2")
    totales = (await _inicio(admin))["zona_accion"]["totales"]
    cuerpo = await _bandeja(admin, vista="ventana_cerrada")

    assert cuerpo["vista"] == "ventana_cerrada"
    assert _telefonos(cuerpo) == ["51980000003", "51980000005", "51980000004"]
    assert cuerpo["total"] == totales["esperando_ventana_cerrada"] == 3
    assert all(f["inicio"]["ventana_abierta"] is False and f["inicio"]["categoria"] == "cliente_esperando"
               for f in cuerpo["conversaciones"])
    # las dos vistas suman los esperando (el escalado con ventana cerrada está en ambas, como escalado y como cerrado)
    assert totales["esperando_ventana_abierta"] + totales["esperando_ventana_cerrada"] == totales["cliente_esperando"]
    # `esperando` sigue siendo todos
    assert (await _bandeja(admin, vista="esperando"))["total"] == totales["cliente_esperando"] == 5


async def test_gestionados_no_aparecen_en_ninguna_vista_y_la_vista_invalida_se_ignora():
    negocio = await _escenario_vistas("gv3", "40500000032")
    admin = await _admin(negocio, "gv3")
    await _evento(negocio, "51980000003", "resultado_cambiado", _h(5), {"nuevo": "sin_respuesta"})
    await _evento(negocio, "51980000001", mem.EVENTO_ATENDIDO_MANUAL, _h(1), {})
    assert _telefonos(await _bandeja(admin, vista="ventana_cerrada")) == ["51980000005", "51980000004"]
    assert "51980000001" not in _telefonos(await _bandeja(admin, vista="responde_ahora"))
    invalida = await _bandeja(admin, vista="no_existe")
    assert "vista" not in invalida and all("inicio" not in f for f in invalida["conversaciones"])


async def test_el_asesor_ve_en_sus_vistas_solo_lo_suyo():
    negocio, canal = await _negocio("gv4", "40500000033")
    await _usuario(negocio, "asesor1", "asesor")
    await _lead(negocio, canal, "51990000001", asesor="asesor1")
    await _lead(negocio, canal, "51990000002", asesor="asesor1")
    await _lead(negocio, canal, "51990000003", asesor="otro")
    await _mensaje(negocio, "51990000001", "user", "Hola", _h(2))
    await _mensaje(negocio, "51990000002", "user", "Hola", _h(40))
    await _mensaje(negocio, "51990000003", "user", "Hola", _h(40))
    asesor = await mem.obtener_usuario("asesor1", negocio_id=negocio["id"])
    totales = (await _inicio(asesor))["zona_accion"]["totales"]
    assert _telefonos(await _bandeja(asesor, vista="responde_ahora")) == ["51990000001"]
    assert totales["responde_ahora_total"] == 1
    cerrada = await _bandeja(asesor, vista="ventana_cerrada", alcance="todos", asesor="otro")
    assert _telefonos(cerrada) == ["51990000002"] and cerrada["total"] == totales["esperando_ventana_cerrada"] == 1


def test_componer_vista_inicio_separa_abiertos_y_cerrados():
    ahora = datetime.utcnow()

    def _c(tel, abierta):
        return {"telefono": tel, "conversation_id": f"c{tel}", "ultimo_mensaje_cliente_en": ahora,
                "ventana_vence_en": ahora, "ventana_abierta": abierta}

    esperando = [_c("1", True), _c("2", False), _c("3", False)]
    assert [e["telefono"] for e in mem.componer_vista_inicio("responde_ahora", esperando, [], [], [], True)] == ["1"]
    assert [e["telefono"] for e in mem.componer_vista_inicio("ventana_cerrada", esperando, [], [], [], False)] == ["2", "3"]
    assert "ventana_cerrada" in mem.VISTAS_INICIO
