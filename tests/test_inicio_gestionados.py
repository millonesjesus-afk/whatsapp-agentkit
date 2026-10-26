# tests/test_inicio_gestionados.py — Inicio y campana dejan de mostrar casos YA
# GESTIONADOS (2026-10-06, paquete P1).
#
# Regla por TIMESTAMP, nunca por booleano:
#   - un cierre definitivo (Lead o Conversation) igual o posterior al último
#     mensaje real del cliente saca el caso de "Clientes esperando";
#   - si el cliente escribe DESPUÉS del cierre, vuelve a aparecer;
#   - "Sin asesor"/"Escalado" excluye cerrados y los que un humano ya contestó
#     (asesor, o la línea desde el celular), y reaparece si el cliente escribe;
#   - citas: venta limpia la fecha, volver a 'agendado' exige fecha nueva, las
#     vencidas de más de 7 días se cuentan aparte.
#
# Datos sintéticos únicamente.

import json
from datetime import datetime, timedelta

import pytest
from fastapi import HTTPException
from sqlalchemy import update

from agent import dashboard, memory as mem


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _negocio_con_canal(codigo: str, telefono_canal: str):
    negocio = await mem.crear_negocio(f"Negocio {codigo}", codigo)
    canal = await mem.crear_canal_whatsapp(
        nombre=f"Canal {codigo}", phone_number_id=telefono_canal, negocio_id=negocio["id"],
    )
    return negocio, canal


async def _lead(
    negocio, canal, telefono: str, *, asesor: str | None = None, pausado: bool = False,
    escalado: bool = False, resultado: str | None = None, paso_flujo: str | None = None,
    fecha_agendada: datetime | None = None,
):
    await mem.resolver_conversation_activa(telefono, negocio["id"], canal["id"])
    await mem.actualizar_lead(telefono, nombre=f"Cliente {telefono[-4:]}", negocio_id=negocio["id"])
    async with mem.async_session() as session:
        lead = await session.get(mem.Lead, telefono)
        lead.asesor_asignado = asesor
        lead.pausado_manual = pausado
        lead.resultado = resultado
        lead.paso_flujo = paso_flujo
        lead.fecha_agendada = fecha_agendada
        if escalado:
            lead.escalado_supervision_en = datetime.utcnow()
        await session.commit()


async def _mensaje(negocio, telefono: str, role: str, contenido: str, hace: timedelta, via_app: bool = False,
                   estado_envio: str | None = None):
    m = await mem.guardar_mensaje(telefono, role, contenido, negocio["id"], via_app=via_app)
    async with mem.async_session() as session:
        await session.execute(
            update(mem.Mensaje).where(mem.Mensaje.id == m["id"]).values(
                timestamp=datetime.utcnow() - hace, estado_envio=estado_envio,
            )
        )
        await session.commit()


def _h(horas: float) -> timedelta:
    return timedelta(hours=horas)


async def _cerrar(telefono: str, hace: timedelta, *, en_lead: bool = True, en_conversacion: bool = False):
    """Cierre definitivo con la hora controlada (`hace` respecto de ahora)."""
    momento = datetime.utcnow() - hace
    async with mem.async_session() as session:
        if en_lead:
            await session.execute(
                update(mem.Lead).where(mem.Lead.telefono == telefono).values(cerrado_definitivamente_en=momento)
            )
        if en_conversacion:
            contact = (await session.execute(
                mem.select(mem.Contact).where(mem.Contact.telefono == telefono)
            )).scalar_one()
            await session.execute(
                update(mem.Conversation).where(mem.Conversation.contact_id == contact.id)
                .values(cerrado_definitivamente_en=momento)
            )
        await session.commit()


async def _esperando(negocio, **kw):
    return {c["telefono"] for c in await mem.listar_clientes_esperando(negocio["id"], **kw)}


async def _sin_asesor(negocio, **kw):
    return {l["telefono"] for l in await mem.listar_leads_esperando_asesor(negocio["id"], **kw)}


async def _usuario(negocio, username: str, rol: str):
    await mem.crear_usuario(username, "pw12345", username.title(), rol, negocio["id"])
    return await mem.obtener_usuario(username, negocio_id=negocio["id"])


async def _inicio(usuario: dict) -> dict:
    return json.loads((await dashboard.inicio_json(usuario=usuario)).body)


# ---------------------------------------------------------------------------
# Clientes esperando — cierre definitivo por timestamp
# ---------------------------------------------------------------------------

async def test_vendido_cerrado_despues_del_gracias_ya_no_espera():
    negocio, canal = await _negocio_con_canal("ig-a", "50100000001")
    await _lead(negocio, canal, "51920000001", asesor="asesor1", resultado="vendido")
    await _mensaje(negocio, "51920000001", "user", "Muchas gracias", _h(30))
    assert await _esperando(negocio) == set()                # 2026-10-26: un «gracias» solo ya no espera
    await _cerrar("51920000001", _h(10))                      # cierre DESPUÉS del último mensaje
    assert await _esperando(negocio) == set()


async def test_si_el_cliente_escribe_despues_del_cierre_vuelve_a_esperar():
    negocio, canal = await _negocio_con_canal("ig-b", "50100000002")
    await _lead(negocio, canal, "51920000002", asesor="asesor1", resultado="vendido")
    await _mensaje(negocio, "51920000002", "user", "Gracias", _h(30))
    await _cerrar("51920000002", _h(10))
    await _mensaje(negocio, "51920000002", "user", "Se me dañó la hornilla", _h(2))
    assert await _esperando(negocio) == {"51920000002"}


async def test_cierre_en_la_conversation_tambien_cuenta_aunque_el_lead_no_lo_tenga():
    negocio, canal = await _negocio_con_canal("ig-c", "50100000003")
    await _lead(negocio, canal, "51920000003", asesor="asesor1", resultado="no_interesado")
    await _mensaje(negocio, "51920000003", "user", "ok", _h(20))
    await _cerrar("51920000003", _h(5), en_lead=False, en_conversacion=True)
    assert await _esperando(negocio) == set()


async def test_cierre_igual_al_ultimo_mensaje_cuenta_como_gestionado():
    negocio, canal = await _negocio_con_canal("ig-d", "50100000004")
    await _lead(negocio, canal, "51920000004", asesor="asesor1", resultado="vendido")
    await _mensaje(negocio, "51920000004", "user", "gracias", _h(3))
    async with mem.async_session() as session:
        ts = (await session.execute(
            mem.select(mem.Mensaje.timestamp).where(mem.Mensaje.telefono == "51920000004")
        )).scalar_one()
        await session.execute(
            update(mem.Lead).where(mem.Lead.telefono == "51920000004").values(cerrado_definitivamente_en=ts)
        )
        await session.commit()
    assert await _esperando(negocio) == set()


async def test_cierre_anterior_al_ultimo_mensaje_no_oculta_nada():
    negocio, canal = await _negocio_con_canal("ig-e", "50100000005")
    await _lead(negocio, canal, "51920000005", asesor="asesor1", resultado="vendido")
    await _cerrar("51920000005", _h(10))
    await _mensaje(negocio, "51920000005", "user", "Hola de nuevo", _h(1))
    assert await _esperando(negocio) == {"51920000005"}


async def test_totales_de_inicio_y_badge_se_corrigen_solos_con_el_cierre():
    negocio, canal = await _negocio_con_canal("ig-f", "50100000006")
    admin = await _usuario(negocio, "admin1", "admin")
    await _lead(negocio, canal, "51920000006", asesor="asesor1", resultado="vendido")
    await _lead(negocio, canal, "51920000007", asesor="asesor1")
    await _mensaje(negocio, "51920000006", "user", "gracias", _h(5))
    await _mensaje(negocio, "51920000007", "user", "Hola", _h(2))
    await _cerrar("51920000006", _h(1))

    t = (await _inicio(admin))["zona_accion"]["totales"]
    assert (t["cliente_esperando"], t["ventana_abierta"], t["ahora_total"], t["esperando_campana"]) == (1, 1, 1, 1)


# ---------------------------------------------------------------------------
# Campana: ventana abierta o cerrada hace menos de 72 h
# ---------------------------------------------------------------------------

async def test_esperando_campana_cuenta_abiertas_y_cerradas_hace_menos_de_72_horas():
    negocio, canal = await _negocio_con_canal("ig-g", "50100000007")
    admin = await _usuario(negocio, "admin1", "admin")
    casos = {
        "51920000010": 2,    # abierta
        "51920000011": 40,   # cerrada hace 16 h
        "51920000012": 90,   # cerrada hace 66 h  (< 72 h)
        "51920000013": 100,  # cerrada hace 76 h  (> 72 h): solo Inicio
        "51920000014": 300,  # cerrada hace días: solo Inicio
    }
    for tel, hace in casos.items():
        await _lead(negocio, canal, tel, asesor="asesor1")
        await _mensaje(negocio, tel, "user", "Hola", _h(hace))

    t = (await _inicio(admin))["zona_accion"]["totales"]
    assert t["cliente_esperando"] == 5          # Inicio los sigue viendo todos
    assert t["ventana_abierta"] == 1
    assert t["esperando_campana"] == 3          # abierta + 2 cerradas recientes


# ---------------------------------------------------------------------------
# Sin asesor / Escalados
# ---------------------------------------------------------------------------

async def test_sin_asesor_excluye_cerrados_por_timestamp_y_reaparece_si_el_cliente_escribe():
    negocio, canal = await _negocio_con_canal("ig-h", "50100000008")
    await _lead(negocio, canal, "51920000020", paso_flujo="derivado_asesor")
    await _mensaje(negocio, "51920000020", "user", "Quiero una cocina", _h(30))
    assert await _sin_asesor(negocio) == {"51920000020"}
    await _cerrar("51920000020", _h(10), en_lead=True, en_conversacion=True)
    assert await _sin_asesor(negocio) == set()
    await _mensaje(negocio, "51920000020", "user", "¿Sigue disponible?", _h(1))
    assert await _sin_asesor(negocio) == {"51920000020"}


async def test_sin_asesor_excluye_si_un_asesor_ya_contesto_y_reaparece_si_el_cliente_escribe_de_nuevo():
    negocio, canal = await _negocio_con_canal("ig-i", "50100000009")
    await _lead(negocio, canal, "51920000021", paso_flujo="derivado_asesor")
    await _mensaje(negocio, "51920000021", "user", "Hola", _h(5))
    await _mensaje(negocio, "51920000021", "asesor", "Te atiendo ahora", _h(4))
    assert await _sin_asesor(negocio) == set()
    assert await _sin_asesor(negocio, excluir_atendidos=False) == {"51920000021"}
    await _mensaje(negocio, "51920000021", "user", "¿Y el precio?", _h(1))
    assert await _sin_asesor(negocio) == {"51920000021"}


async def test_sin_asesor_excluye_la_atencion_por_celular_sin_asesor_registrado():
    negocio, canal = await _negocio_con_canal("ig-j", "50100000010")
    await _lead(negocio, canal, "51920000022", paso_flujo="derivado_asesor", pausado=True)
    await _mensaje(negocio, "51920000022", "user", "Hola", _h(5))
    await _mensaje(negocio, "51920000022", "assistant", "Hola, te escribo desde el celular", _h(4), via_app=True)
    assert await _sin_asesor(negocio) == set()


async def test_una_respuesta_de_gabi_o_un_envio_fallido_no_cuentan_como_atencion_humana():
    negocio, canal = await _negocio_con_canal("ig-k", "50100000011")
    await _lead(negocio, canal, "51920000023", paso_flujo="derivado_asesor")
    await _lead(negocio, canal, "51920000024", paso_flujo="derivado_asesor")
    await _mensaje(negocio, "51920000023", "user", "Hola", _h(5))
    await _mensaje(negocio, "51920000023", "assistant", "Soy Gabi", _h(4))                       # Gabi, no humano
    await _mensaje(negocio, "51920000024", "user", "Hola", _h(5))
    await _mensaje(negocio, "51920000024", "asesor", "Te respondo", _h(4), estado_envio="fallido")  # no salió
    assert await _sin_asesor(negocio) == {"51920000023", "51920000024"}


async def test_sin_asesor_deja_de_esperar_si_todas_sus_conversaciones_estan_cerradas():
    negocio, canal = await _negocio_con_canal("ig-l", "50100000012")
    await _lead(negocio, canal, "51920000025", paso_flujo="derivado_asesor")
    await _mensaje(negocio, "51920000025", "user", "Hola", _h(5))
    async with mem.async_session() as session:
        await session.execute(update(mem.Conversation).values(estado="cerrada"))
        await session.commit()
    assert await _sin_asesor(negocio) == set()


async def test_sin_asesor_mantiene_agendado_y_postventa_porque_siguen_necesitando_dueno():
    negocio, canal = await _negocio_con_canal("ig-m", "50100000013")
    futuro = datetime.utcnow() - timedelta(hours=5) + timedelta(days=2)
    await _lead(negocio, canal, "51920000026", paso_flujo="derivado_asesor", resultado="agendado", fecha_agendada=futuro)
    await _lead(negocio, canal, "51920000027", paso_flujo="derivado_asesor", resultado="postventa")
    await _lead(negocio, canal, "51920000028", paso_flujo="derivado_asesor", resultado="vendido")
    for tel in ("51920000026", "51920000027", "51920000028"):
        await _mensaje(negocio, tel, "user", "Hola", _h(2))
    assert await _sin_asesor(negocio) == {"51920000026", "51920000027"}


async def test_inicio_admin_no_muestra_sin_asesor_ni_escalado_ya_gestionados():
    negocio, canal = await _negocio_con_canal("ig-n", "50100000014")
    admin = await _usuario(negocio, "admin1", "admin")
    await _lead(negocio, canal, "51920000030", paso_flujo="derivado_asesor")                 # pendiente real
    await _lead(negocio, canal, "51920000031", paso_flujo="derivado_asesor", escalado=True)  # escalado, ya contestado
    await _lead(negocio, canal, "51920000032", paso_flujo="derivado_asesor", resultado="no_interesado")
    await _mensaje(negocio, "51920000030", "user", "Hola", _h(3))
    await _mensaje(negocio, "51920000031", "user", "Hola", _h(6))
    await _mensaje(negocio, "51920000031", "asesor", "Ya te atiendo", _h(5))
    await _mensaje(negocio, "51920000032", "user", "Hola", _h(3))
    await _cerrar("51920000032", _h(1))

    z = (await _inicio(admin))["zona_accion"]
    por_cat = {}
    for i in z["items"]:
        por_cat.setdefault(i["categoria"], []).append(i["telefono"])
    assert por_cat.get("sin_asesor") == ["51920000030"]
    assert "escalado" not in por_cat
    assert z["totales"]["sin_asesor"] == 1 and z["totales"]["escalados"] == 0


# ---------------------------------------------------------------------------
# Citas
# ---------------------------------------------------------------------------

async def test_listar_leads_agendados_exige_que_el_lead_siga_vivo():
    negocio, canal = await _negocio_con_canal("ig-o", "50100000015")
    futuro = datetime.utcnow() - timedelta(hours=5) + timedelta(days=1)
    await _lead(negocio, canal, "51920000040", asesor="a1", resultado="agendado", fecha_agendada=futuro)
    await _lead(negocio, canal, "51920000041", asesor="a1", resultado="agendado", fecha_agendada=futuro)
    await _cerrar("51920000041", _h(1))
    assert [l["telefono"] for l in await mem.listar_leads_agendados(negocio["id"])] == ["51920000040"]


async def test_citas_vencidas_de_mas_de_7_dias_se_cuentan_aparte_y_no_se_listan():
    negocio, canal = await _negocio_con_canal("ig-p", "50100000016")
    asesor = await _usuario(negocio, "asesor1", "asesor")
    ahora_lima = datetime.utcnow() - timedelta(hours=5)
    for tel, dias in (("51920000050", 1), ("51920000051", 6), ("51920000052", 8), ("51920000053", 30)):
        await _lead(negocio, canal, tel, asesor="asesor1", resultado="agendado",
                    fecha_agendada=ahora_lima - timedelta(days=dias))

    z = (await _inicio(asesor))["zona_accion"]
    vencidas = [i["telefono"] for i in z["items"] if i["categoria"] == "cita_vencida"]
    assert vencidas == ["51920000050", "51920000051"]
    t = z["totales"]
    assert (t["citas_vencidas"], t["citas_vencidas_antiguas"]) == (2, 2)
    # La firma de siempre sigue devolviendo solo las vigentes (la usa la vista de la Bandeja).
    _, vencidas_firma, _ = await dashboard._citas_inicio(negocio["id"], "asesor1", datetime.utcnow())
    assert [l["telefono"] for l in vencidas_firma] == ["51920000050", "51920000051"]


async def test_la_venta_limpia_la_fecha_de_la_cita_en_lead_y_opportunity():
    negocio, canal = await _negocio_con_canal("ig-q", "50100000017")
    telefono = "51920000060"
    futuro = datetime.utcnow() - timedelta(hours=5) + timedelta(days=2)
    await _lead(negocio, canal, telefono, asesor="admin1", resultado="agendado", fecha_agendada=futuro)
    async with mem.async_session() as session:
        contact = (await session.execute(mem.select(mem.Contact).where(mem.Contact.telefono == telefono))).scalar_one()
        conv = (await session.execute(
            mem.select(mem.Conversation).where(mem.Conversation.contact_id == contact.id)
        )).scalar_one()
        opp = (await session.execute(
            mem.select(mem.Opportunity).where(mem.Opportunity.conversation_id == conv.id)
        )).scalar_one()
        opp.fecha_agendada = futuro
        opp.resultado = "agendado"
        await session.commit()
        opp_id, opp_version = opp.id, opp.version

    usuario = {"username": "admin1", "nombre": "Admin Uno", "negocio_id": negocio["id"], "rol": "admin"}
    lineas = json.dumps([{"producto_id": None, "producto": "Terma", "precio": "1500"}])
    await dashboard.opportunity_venta(
        opp_id, lineas_venta=lineas, modalidad_pago="contado", cuotas="", medio_pago="QR",
        version=opp_version, usuario=usuario, _csrf=None,
    )
    async with mem.async_session() as session:
        assert (await session.get(mem.Opportunity, opp_id)).fecha_agendada is None
        lead = await session.get(mem.Lead, telefono)
        assert lead.resultado == "vendido" and lead.fecha_agendada is None
    assert await mem.listar_leads_agendados(negocio["id"]) == []


async def test_persistir_venta_del_servicio_tambien_limpia_la_fecha():
    from agent.services.servicio_comercial import servicio_comercial

    negocio, canal = await _negocio_con_canal("ig-r", "50100000018")
    telefono = "51920000061"
    futuro = datetime.utcnow() - timedelta(hours=5) + timedelta(days=2)
    await _lead(negocio, canal, telefono, asesor="admin1", resultado="agendado", fecha_agendada=futuro)
    venta = servicio_comercial.validar_venta(
        json.dumps([{"producto_id": None, "producto": "Terma", "precio": "1500"}]), "contado", "", "QR",
    )
    await servicio_comercial.persistir_venta(telefono, venta)
    async with mem.async_session() as session:
        lead = await session.get(mem.Lead, telefono)
        assert lead.resultado == "vendido" and lead.fecha_agendada is None


class _FormularioFalso:
    """Duck-type mínimo de `Request` para los endpoints que releen request.form()."""

    def __init__(self, datos: dict):
        self._datos = datos

    async def form(self):
        return self._datos


async def _opportunity_de(telefono: str):
    async with mem.async_session() as session:
        contact = (await session.execute(mem.select(mem.Contact).where(mem.Contact.telefono == telefono))).scalar_one()
        conv = (await session.execute(
            mem.select(mem.Conversation).where(mem.Conversation.contact_id == contact.id)
        )).scalar_one()
        return (await session.execute(
            mem.select(mem.Opportunity).where(mem.Opportunity.conversation_id == conv.id)
        )).scalar_one()


async def test_volver_a_agendado_sin_fecha_nueva_responde_400_y_con_fecha_funciona():
    negocio, canal = await _negocio_con_canal("ig-s", "50100000019")
    telefono = "51920000062"
    await _lead(negocio, canal, telefono, asesor="admin1", resultado="vendido")
    opp = await _opportunity_de(telefono)
    usuario = {"username": "admin1", "nombre": "Admin Uno", "negocio_id": negocio["id"], "rol": "admin"}

    form = {"resultado": "agendado", "fecha_agendada": ""}
    with pytest.raises(HTTPException) as exc:
        await dashboard.opportunity_resultado(
            opp.id, _FormularioFalso(form), resultado="agendado", fecha_agendada="",
            version=opp.version, usuario=usuario, _csrf=None,
        )
    assert exc.value.status_code == 400 and "fecha" in exc.value.detail.lower()
    # El 400 no consumió la versión de concurrencia.
    assert (await _opportunity_de(telefono)).version == opp.version

    fecha = (datetime.utcnow() - timedelta(hours=5) + timedelta(days=3)).replace(microsecond=0)
    await dashboard.opportunity_resultado(
        opp.id, _FormularioFalso({"resultado": "agendado"}), resultado="agendado",
        fecha_agendada=fecha.isoformat(), version=opp.version, usuario=usuario, _csrf=None,
    )
    assert (await _opportunity_de(telefono)).fecha_agendada == fecha


async def test_cambiar_a_otro_resultado_sigue_limpiando_la_fecha():
    negocio, canal = await _negocio_con_canal("ig-t", "50100000020")
    telefono = "51920000063"
    futuro = datetime.utcnow() - timedelta(hours=5) + timedelta(days=2)
    await _lead(negocio, canal, telefono, asesor="admin1", resultado="agendado", fecha_agendada=futuro)
    opp = await _opportunity_de(telefono)
    usuario = {"username": "admin1", "nombre": "Admin Uno", "negocio_id": negocio["id"], "rol": "admin"}
    await dashboard.opportunity_resultado(
        opp.id, _FormularioFalso({"resultado": "no_interesado"}), resultado="no_interesado",
        fecha_agendada="", version=opp.version, usuario=usuario, _csrf=None,
    )
    assert (await _opportunity_de(telefono)).fecha_agendada is None
