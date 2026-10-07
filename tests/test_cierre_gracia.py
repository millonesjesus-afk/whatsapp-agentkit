# tests/test_cierre_gracia.py — 2026-10-07: LAPSO DE GRACIA del cierre definitivo y AGRADECIMIENTO
# AUTOMÁTICO. Decisión del dueño tras un benchmarking (Gladly, Front/WhatsApp, WATI: 24 h):
#   · DENTRO de 24 h del cierre (`cierre_gracia_horas`, por negocio): un "ok"/"gracias" o una reacción
#     se guardan en el caso cerrado con banner + chip pasivos y "Reabrir caso" lo puede usar quien cierra.
#   · FUERA del lapso: la cortesía queda como "mensaje suelto" (sin banner, chip ni alerta) y reabrir
#     exige admin/supervisor con motivo. Un mensaje REAL abre un ciclo nuevo desde cero, dentro y fuera.
#   · "gracias" a un caso cerrado recibe UNA frase fija (sin IA) por cierre, por la capa central de envíos.

import os
from datetime import datetime, timedelta

os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")
os.environ.setdefault("WHATSAPP_PROVIDER", "meta")
os.environ["DEBOUNCE_RESPUESTA_SEGUNDOS"] = "0"

import pytest
from fastapi import HTTPException
from sqlalchemy import select, update

from agent import dashboard, envios
from agent import main as app_main
from agent import memory as mem
from agent.http_utils import EnvioIncierto
from tests.test_cierre_cortesia import (
    _caso_cerrado, _conversaciones, _correr, _eventos, _evaluar, _mensajes, _msg, _preparar_webhook,
)

AGRADECIMIENTO = "¡Gracias a ti! Si necesitas algo más, escríbenos cuando quieras. 😊"


async def _envejecer(telefono: str, horas: float, minutos: float = 0) -> None:
    """Mueve TODO el caso (cierre, mensajes y eventos) hacia atrás en el tiempo: el cierre queda a
    `horas` h `minutos` min de ahora sin que nada parezca posterior al cierre."""
    delta = timedelta(hours=horas, minutes=minutos)
    async with mem.async_session() as session:
        lead = await session.get(mem.Lead, telefono)
        if lead.cerrado_definitivamente_en is not None:
            lead.cerrado_definitivamente_en -= delta
        convs = (await session.execute(
            select(mem.Conversation).join(mem.Contact, mem.Contact.id == mem.Conversation.contact_id)
            .where(mem.Contact.telefono == telefono)
        )).scalars().all()
        for c in convs:
            if c.cerrado_definitivamente_en is not None:
                c.cerrado_definitivamente_en -= delta
            c.creado -= delta
        for m in (await session.execute(select(mem.Mensaje).where(mem.Mensaje.telefono == telefono))).scalars().all():
            m.timestamp -= delta
        for e in (await session.execute(select(mem.EventoLead).where(mem.EventoLead.conversation_id.in_([c.id for c in convs])))).scalars().all():
            e.creado -= delta
        await session.commit()


async def _caso_cerrado_hace(codigo, telefono, horas, minutos=0, **kw):
    escenario = await _caso_cerrado(codigo, telefono, **kw)
    await _envejecer(telefono, horas, minutos)
    return escenario


async def _fila_bandeja(negocio, telefono):
    filas, _ = await mem.listar_conversaciones_activas(negocio["id"])
    return next(f for f in filas if f["telefono"] == telefono)


def _usuario(negocio, username="angie", rol="admin"):
    return {"username": username, "nombre": username, "rol": rol, "negocio_id": negocio["id"]}


# ── Funciones puras ────────────────────────────────────────────────────────

@pytest.mark.parametrize("valor, esperado", [
    (None, 24), ("", 24), ("abc", 24), ("0", 24), ("-3", 24), ("nan", 24), ("inf", 24), ("-inf", 24), (0, 24),
    ("24", 24), ("12", 12), (48, 48), ("0.5", 0.5), ("1,5", 1.5), (" 6 ", 6),
])
def test_horas_de_gracia_invalidas_o_no_positivas_valen_24(valor, esperado):
    assert mem.normalizar_cierre_gracia_horas(valor) == esperado


def test_el_borde_exacto_del_lapso_cuenta_como_dentro():
    cierre = datetime(2026, 10, 7, 8, 0)
    assert mem.cierre_en_lapso_de_gracia(cierre, cierre + timedelta(hours=23, minutes=59), 24) is True
    assert mem.cierre_en_lapso_de_gracia(cierre, cierre + timedelta(hours=24), 24) is True
    assert mem.cierre_en_lapso_de_gracia(cierre, cierre + timedelta(hours=24, minutes=1), 24) is False
    assert mem.cierre_en_lapso_de_gracia(None, cierre, 24) is False


@pytest.mark.parametrize("texto, esperado", [
    ("gracias", True), ("Muchas gracias", True), ("graciass", True), ("ok gracias", True), ("Gracias!", True),
    ("Perfecto, gracias", True), ("ok", False), ("Oh ya ok", False), ("listo", False), ("👍", False), ("🙏", False),
    ("Reaccionó con 👍", False), ("", False), (None, False), ("gracias, ya compré", False), ("¿gracias?", False),
])
def test_solo_la_gratitud_dispara_el_agradecimiento(texto, esperado):
    assert mem.contiene_gratitud(texto) is esperado


def test_el_evento_y_el_origen_nuevos_respetan_los_limites():
    assert mem.EVENTO_AGRADECIMIENTO_CIERRE == "agradecimiento_cierre_enviado"
    assert len(mem.EVENTO_AGRADECIMIENTO_CIERRE) <= 30
    assert len("agradecimiento_cierre") <= 40   # EnvioMeta.origen es VARCHAR(40)
    assert envios.ORIGENES["agradecimiento_cierre"] == {"esencial": False, "modo": "siempre"}
    assert len(envios.ORIGENES) >= 12


# ── evaluar_cierre_cortesia: el borde del lapso ────────────────────────────

async def test_borde_23h59_dentro_y_24h01_fuera_con_el_valor_por_defecto():
    n1, *_ = await _caso_cerrado_hace("g-gr-a1", "51939568001", 23, 59)
    n2, *_ = await _caso_cerrado_hace("g-gr-a2", "51939568002", 24, 1)
    dentro = await _evaluar("51939568001", n1, "gracias")
    fuera = await _evaluar("51939568002", n2, "gracias")
    assert dentro["tardio"] is False and dentro["gracia_horas"] == 24 and dentro["gratitud"] is True
    assert fuera["tardio"] is True and fuera["gracia_horas"] == 24
    # reacciones y echo traen la misma marca
    assert (await _evaluar("51939568001", n1, "x", tipo="reaccion"))["tardio"] is False
    assert (await _evaluar("51939568002", n2, "x", tipo="reaccion"))["tardio"] is True
    assert (await _evaluar("51939568002", n2, "x", tipo="echo"))["tardio"] is True


async def test_el_lapso_es_configurable_por_negocio():
    n, *_ = await _caso_cerrado_hace("g-gr-b1", "51939568003", 30)       # 30 h
    assert (await _evaluar("51939568003", n, "ok"))["tardio"] is True    # con 24 h por defecto
    await mem.guardar_configuracion("cierre_gracia_horas", "48", negocio_id=n["id"])
    ctx = await _evaluar("51939568003", n, "ok")
    assert ctx["tardio"] is False and ctx["gracia_horas"] == 48
    await mem.guardar_configuracion("cierre_gracia_horas", "12", negocio_id=n["id"])
    assert (await _evaluar("51939568003", n, "ok"))["tardio"] is True      # 30 h > 12 h


@pytest.mark.parametrize("valor", ["abc", "0", "-5", ""])
async def test_un_valor_invalido_de_la_clave_vuelve_a_24(valor):
    n, *_ = await _caso_cerrado_hace(f"g-gr-c{abs(hash(valor)) % 90 + 10}", f"519395680{abs(hash(valor)) % 90 + 10}", 25)
    await mem.guardar_configuracion("cierre_gracia_horas", valor, negocio_id=n["id"])
    assert await mem.obtener_cierre_gracia_horas(n["id"]) == 24


async def test_el_tope_de_cinco_solo_rige_dentro_del_lapso(monkeypatch):
    telefono = "51939568004"
    negocio, canal, canal_dict, conv = await _caso_cerrado_hace("g-gr-d", telefono, 30)
    proveedor, gabi = _preparar_webhook(monkeypatch, canal_dict, canal, [])
    for i in range(mem.TOPE_CIERRES_DE_CORTESIA + 2):
        await _correr(proveedor, [_msg(telefono, canal, "ok", f"wamid.gr-d{i}")])
    # Fuera del lapso nadie se entera: ninguno reabre, ni el sexto ni el séptimo
    assert len(await _conversaciones(telefono)) == 1 and gabi.llamadas == 0


# ── Webhook: cortesía dentro del lapso ─────────────────────────────────────

async def test_dentro_del_lapso_la_cortesia_deja_banner_chip_y_evento_normal(monkeypatch):
    telefono = "51939568010"
    negocio, canal, canal_dict, conv = await _caso_cerrado_hace("g-gr-e", telefono, 23, 59)
    proveedor, gabi = _preparar_webhook(monkeypatch, canal_dict, canal, [])

    await _correr(proveedor, [_msg(telefono, canal, "Oh ya ok", "wamid.gr-e")])

    assert len(await _conversaciones(telefono)) == 1 and gabi.llamadas == 0 and proveedor.enviados == []
    eventos = await _eventos(telefono, "mensaje_de_cierre_sin_reabrir")
    assert len(eventos) == 1 and eventos[0]["payload"]["tardio"] is False
    assert "tras el cierre" in eventos[0]["descripcion"]
    fila = await _fila_bandeja(negocio, telefono)
    assert fila["respondio_tras_cierre_en"] is not None and fila["mensajes_tras_cierre"] == 1
    assert fila["mensajes_pendientes"] == 0 and fila["cierre_gracia_horas"] == 24
    assert [c for c in await mem.listar_clientes_esperando(negocio["id"]) if c["telefono"] == telefono] == []
    detalle = await mem.obtener_conversation_detalle(conv.id, negocio["id"])
    assert detalle["cierre_gracia_horas"] == 24
    assert dashboard._dto_conversation_detalle(detalle, [], [])["cierre_gracia_horas"] == 24


# ── Webhook: cortesía FUERA del lapso (mensaje suelto) ─────────────────────

async def test_fuera_del_lapso_la_cortesia_queda_suelta_sin_banner_chip_ni_alerta(monkeypatch):
    telefono = "51939568011"
    negocio, canal, canal_dict, conv = await _caso_cerrado_hace("g-gr-f", telefono, 24, 1)
    async with mem.async_session() as session:       # el caso estaba "visto": no debe pasar a "Nuevo"
        (await session.get(mem.Lead, telefono)).visto_asesor = True
        (await session.get(mem.Conversation, conv.id)).visto_asesor = True
        await session.commit()
    proveedor, gabi = _preparar_webhook(monkeypatch, canal_dict, canal, [])

    await _correr(proveedor, [_msg(telefono, canal, "Oh ya ok", "wamid.gr-f")])

    convs = await _conversaciones(telefono)
    assert [c.id for c in convs] == [conv.id] and convs[0].estado == "activa"   # sin ciclo nuevo
    assert gabi.llamadas == 0 and proveedor.enviados == []                        # sin Gabi, sin respuesta
    assert await _eventos(telefono, "reabierto_por_cliente") == []
    guardado = [m for m in await _mensajes(telefono, "user") if m.content == "Oh ya ok"]
    assert len(guardado) == 1 and guardado[0].conversation_id == conv.id          # quedó en el caso cerrado
    # Rastro para trazabilidad, marcado como tardío y con descripción neutra (no es una alerta)
    eventos = await _eventos(telefono, "mensaje_de_cierre_sin_reabrir")
    assert len(eventos) == 1 and eventos[0]["payload"]["tardio"] is True
    assert "pasado el lapso" in eventos[0]["descripcion"] and "tras el cierre" not in eventos[0]["descripcion"]
    # Sin chip, sin contador, sin pendiente, sin cliente esperando
    fila = await _fila_bandeja(negocio, telefono)
    assert fila["respondio_tras_cierre_en"] is None and fila["mensajes_tras_cierre"] == 0
    assert fila["mensajes_pendientes"] == 0
    assert [c for c in await mem.listar_clientes_esperando(negocio["id"]) if c["telefono"] == telefono] == []
    async with mem.async_session() as session:
        assert (await session.get(mem.Lead, telefono)).visto_asesor is True
        assert (await session.get(mem.Conversation, conv.id)).visto_asesor is True
    lead = await mem.obtener_lead(telefono, negocio_id=negocio["id"])
    assert lead["asesor_asignado"] == "rvilchez" and lead["cerrado_definitivamente_en"] is not None


async def test_el_lapso_configurable_cambia_que_es_suelto_en_el_webhook(monkeypatch):
    telefono = "51939568012"
    negocio, canal, canal_dict, conv = await _caso_cerrado_hace("g-gr-g", telefono, 30)
    await mem.guardar_configuracion("cierre_gracia_horas", "36", negocio_id=negocio["id"])
    proveedor, gabi = _preparar_webhook(monkeypatch, canal_dict, canal, [])

    await _correr(proveedor, [_msg(telefono, canal, "ok", "wamid.gr-g")])

    fila = await _fila_bandeja(negocio, telefono)
    assert fila["respondio_tras_cierre_en"] is not None and fila["cierre_gracia_horas"] == 36
    assert (await _eventos(telefono, "mensaje_de_cierre_sin_reabrir"))[0]["payload"]["tardio"] is False


# ── Reacciones ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize("horas, minutos, tardio", [(23, 59, False), (24, 1, True)])
async def test_reaccion_no_abre_ciclo_dentro_ni_fuera_del_lapso(monkeypatch, horas, minutos, tardio):
    telefono = f"519395680{20 + int(tardio)}"
    negocio, canal, canal_dict, conv = await _caso_cerrado_hace(f"g-gr-h{int(tardio)}", telefono, horas, minutos)
    proveedor, gabi = _preparar_webhook(monkeypatch, canal_dict, canal, [])

    await _correr(proveedor, [_msg(telefono, canal, "Reaccionó con 👍", f"wamid.gr-h{int(tardio)}", tipo="reaction")])

    convs = await _conversaciones(telefono)
    assert len(convs) == 1 and convs[0].estado == "activa"
    assert gabi.llamadas == 0 and proveedor.enviados == []   # una reacción nunca recibe agradecimiento
    assert await _eventos(telefono, "mensaje_de_cierre_sin_reabrir") == []
    assert await _eventos(telefono, "agradecimiento_cierre_enviado") == []
    fila = await _fila_bandeja(negocio, telefono)
    assert fila["mensajes_pendientes"] == 0
    assert (fila["respondio_tras_cierre_en"] is not None) is (not tardio)
    assert [c for c in await mem.listar_clientes_esperando(negocio["id"]) if c["telefono"] == telefono] == []


# ── Mensaje real: ciclo nuevo desde cero dentro y fuera ────────────────────

@pytest.mark.parametrize("horas, minutos", [(1, 0), (23, 59), (24, 1), (72, 0)])
async def test_un_mensaje_real_abre_un_ciclo_nuevo_dentro_y_fuera_del_lapso(monkeypatch, horas, minutos):
    telefono = f"51939568{30 + horas % 70}"
    negocio, canal, canal_dict, conv = await _caso_cerrado_hace(f"g-gr-i{horas}-{minutos}", telefono, horas, minutos)
    proveedor, gabi = _preparar_webhook(monkeypatch, canal_dict, canal, [])

    await _correr(proveedor, [_msg(telefono, canal, "¿Cuándo me instalan?", f"wamid.gr-i{horas}-{minutos}")])

    convs = await _conversaciones(telefono)
    assert len(convs) == 2 and convs[0].estado == "cerrada" and convs[1].estado == "activa"
    assert len(await _eventos(telefono, "reabierto_por_cliente")) == 1
    assert gabi.llamadas == 1
    lead = await mem.obtener_lead(telefono, negocio_id=negocio["id"])
    assert lead["asesor_asignado"] is None and lead["resultado"] is None


async def test_un_adjunto_fuera_del_lapso_sigue_reabriendo(monkeypatch):
    telefono = "51939568040"
    negocio, canal, canal_dict, conv = await _caso_cerrado_hace("g-gr-j", telefono, 48)
    proveedor, gabi = _preparar_webhook(monkeypatch, canal_dict, canal, [])

    async def media_falsa(msg, canal_):
        return None
    monkeypatch.setattr(app_main, "_guardar_media_entrante", media_falsa)
    from agent.providers.base import MensajeEntrante
    await _correr(proveedor, [MensajeEntrante(
        telefono=telefono, texto="", mensaje_id="wamid.gr-j", es_propio=False, tipo="audio",
        numero_whatsapp_id=canal["phone_number_id"], media={"media_id": "m1", "mime_type": "audio/ogg"},
    )])

    assert len(await _conversaciones(telefono)) == 2


async def test_vendido_fuera_del_lapso_cortesia_absorbida_y_mensaje_real_va_a_postventa(monkeypatch):
    telefono = "51939568041"
    negocio, canal, canal_dict, conv = await _caso_cerrado_hace(
        "g-gr-k", telefono, 48, resultado="vendido", asesor="sabarca", saliente="Listo, tu instalación quedó coordinada.",
    )
    proveedor, gabi = _preparar_webhook(monkeypatch, canal_dict, canal, [])

    await _correr(proveedor, [_msg(telefono, canal, "ok", "wamid.gr-k1")])
    assert len(await _conversaciones(telefono)) == 1 and await _eventos(telefono, "asignado_automatico_postventa") == []

    await _correr(proveedor, [_msg(telefono, canal, "¿Cuándo me instalan?", "wamid.gr-k2")])
    assert len(await _eventos(telefono, "asignado_automatico_postventa")) == 1
    lead = await mem.obtener_lead(telefono, negocio_id=negocio["id"])
    assert lead["resultado"] == "postventa" and lead["asesor_asignado"] == "sabarca" and gabi.llamadas == 0


# ── Reabrir caso: dentro y fuera del lapso ─────────────────────────────────

async def test_reabrir_dentro_del_lapso_lo_puede_el_asesor_dueno_sin_motivo():
    telefono = "51939568050"
    negocio, canal, _, conv = await _caso_cerrado_hace("g-gr-l", telefono, 23, 59)
    r = await dashboard.conversation_reabrir(conv.id, usuario=_usuario(negocio, "rvilchez", "asesor"), _csrf=None)
    assert r.status_code == 200
    ev = (await _eventos(telefono, "cierre_deshecho"))[0]
    assert ev["payload"]["fuera_de_lapso"] is False and ev["payload"]["motivo"] is None


async def test_reabrir_dentro_del_lapso_guarda_el_motivo_si_se_da():
    telefono = "51939568051"
    negocio, canal, _, conv = await _caso_cerrado_hace("g-gr-m", telefono, 2)
    await dashboard.conversation_reabrir(conv.id, motivo="  Sí quería el servicio ", usuario=_usuario(negocio), _csrf=None)
    assert (await _eventos(telefono, "cierre_deshecho"))[0]["payload"]["motivo"] == "Sí quería el servicio"


async def test_reabrir_fuera_del_lapso_el_asesor_recibe_403_aunque_sea_el_dueno_y_no_se_reabre():
    telefono = "51939568052"
    negocio, canal, _, conv = await _caso_cerrado_hace("g-gr-n", telefono, 24, 1)
    with pytest.raises(HTTPException) as exc:
        await dashboard.conversation_reabrir(
            conv.id, motivo="Quiere seguir", usuario=_usuario(negocio, "rvilchez", "asesor"), _csrf=None,
        )
    assert exc.value.status_code == 403
    assert (await mem.obtener_lead(telefono, negocio_id=negocio["id"]))["cerrado_definitivamente_en"] is not None
    assert await _eventos(telefono, "cierre_deshecho") == []


@pytest.mark.parametrize("motivo", ["", "   ", "\n"])
async def test_reabrir_fuera_del_lapso_sin_motivo_es_400(motivo):
    telefono = "51939568053"
    negocio, canal, _, conv = await _caso_cerrado_hace("g-gr-o", telefono, 30)
    for rol in ("admin", "supervisor"):
        with pytest.raises(HTTPException) as exc:
            await dashboard.conversation_reabrir(conv.id, motivo=motivo, usuario=_usuario(negocio, "jefa", rol), _csrf=None)
        assert exc.value.status_code == 400 and "motivo" in exc.value.detail.lower()
    assert (await mem.obtener_lead(telefono, negocio_id=negocio["id"]))["cerrado_definitivamente_en"] is not None


async def test_reabrir_con_un_motivo_de_mas_de_300_caracteres_es_400():
    telefono = "51939568054"
    negocio, canal, _, conv = await _caso_cerrado_hace("g-gr-p", telefono, 30)
    with pytest.raises(HTTPException) as exc:
        await dashboard.conversation_reabrir(conv.id, motivo="x" * 301, usuario=_usuario(negocio), _csrf=None)
    assert exc.value.status_code == 400
    r = await dashboard.conversation_reabrir(conv.id, motivo="x" * 300, usuario=_usuario(negocio), _csrf=None)
    assert r.status_code == 200


@pytest.mark.parametrize("rol", ["admin", "supervisor"])
async def test_reabrir_fuera_del_lapso_con_motivo_funciona_y_queda_en_el_evento_y_la_auditoria(rol):
    telefono = "51939568055" if rol == "admin" else "51939568056"
    negocio, canal, _, conv = await _caso_cerrado_hace(f"g-gr-q{rol[0]}", telefono, 50)
    r = await dashboard.conversation_reabrir(
        conv.id, motivo="La clienta llamó y sí quiere el servicio", usuario=_usuario(negocio, "jefa", rol), _csrf=None,
    )
    assert r.status_code == 200
    lead = await mem.obtener_lead(telefono, negocio_id=negocio["id"])
    assert lead["cerrado_definitivamente_en"] is None and lead["asesor_asignado"] == "rvilchez"
    ev = (await _eventos(telefono, "cierre_deshecho"))[0]
    assert ev["payload"]["motivo"] == "La clienta llamó y sí quiere el servicio"
    assert ev["payload"]["fuera_de_lapso"] is True and ev["payload"]["gracia_horas"] == 24
    assert "motivo: La clienta llamó" in ev["descripcion"] and len(ev["descripcion"]) <= 300
    async with mem.async_session() as session:
        filas = (await session.execute(
            select(mem.RegistroAuditoria).where(mem.RegistroAuditoria.accion == "caso_reabierto_fuera_de_lapso")
        )).scalars().all()
    assert len(filas) == 1 and filas[0].actor == "jefa" and filas[0].entidad_id == conv.id
    assert filas[0].payload["motivo"] == "La clienta llamó y sí quiere el servicio"


async def test_reabrir_dentro_del_lapso_no_deja_auditoria():
    telefono = "51939568057"
    negocio, canal, _, conv = await _caso_cerrado_hace("g-gr-r", telefono, 1)
    await dashboard.conversation_reabrir(conv.id, usuario=_usuario(negocio), _csrf=None)
    async with mem.async_session() as session:
        assert (await session.execute(select(mem.RegistroAuditoria).where(
            mem.RegistroAuditoria.accion == "caso_reabierto_fuera_de_lapso"))).first() is None


async def test_el_lapso_configurable_tambien_manda_en_reabrir():
    telefono = "51939568058"
    negocio, canal, _, conv = await _caso_cerrado_hace("g-gr-s", telefono, 30)
    await mem.guardar_configuracion("cierre_gracia_horas", "48", negocio_id=negocio["id"])
    r = await dashboard.conversation_reabrir(conv.id, usuario=_usuario(negocio, "rvilchez", "asesor"), _csrf=None)
    assert r.status_code == 200      # a las 30 h con 48 h de gracia: dentro, asesor y sin motivo


async def test_los_409_y_404_siguen_igual_fuera_del_lapso():
    telefono = "51939568059"
    negocio, canal, _, conv = await _caso_cerrado_hace("g-gr-t", telefono, 30)
    nueva, _ = await mem.resolver_conversation_activa(telefono, negocio["id"], canal["id"])  # DR-4: el cliente volvió
    assert nueva.id != conv.id
    with pytest.raises(HTTPException) as exc:
        await dashboard.conversation_reabrir(conv.id, motivo="x", usuario=_usuario(negocio), _csrf=None)
    assert exc.value.status_code == 409
    with pytest.raises(HTTPException) as exc:
        await dashboard.conversation_reabrir("no-existe", motivo="x", usuario=_usuario(negocio), _csrf=None)
    assert exc.value.status_code == 404
    # y un caso abierto es 409 antes que cualquier chequeo de motivo
    abierta, *_ = await _caso_cerrado("g-gr-t2", "51939568060")
    await dashboard.conversation_reabrir(
        (await _conversaciones("51939568060"))[0].id, usuario=_usuario(abierta), _csrf=None,
    )
    with pytest.raises(HTTPException) as exc:
        await dashboard.conversation_reabrir(
            (await _conversaciones("51939568060"))[0].id, usuario=_usuario(abierta, "otro", "supervisor"), _csrf=None,
        )
    assert exc.value.status_code == 409


def test_la_ruta_recibe_el_motivo_como_campo_de_formulario():
    ruta = next(r for r in dashboard.router.routes if getattr(r, "path", "").endswith("/conversation/{conversation_id}/reabrir"))
    assert "motivo" in {c.name for c in ruta.dependant.body_params}


# ── Agradecimiento automático ──────────────────────────────────────────────

async def _marcas(telefono):
    return await _eventos(telefono, "agradecimiento_cierre_enviado")


async def test_gracias_dentro_del_lapso_responde_una_sola_vez_con_la_frase_fija(monkeypatch):
    telefono = "51939568070"
    negocio, canal, canal_dict, conv = await _caso_cerrado("g-gr-u", telefono)
    proveedor, gabi = _preparar_webhook(monkeypatch, canal_dict, canal, [])

    await _correr(proveedor, [_msg(telefono, canal, "Muchas gracias", "wamid.gr-u1")])

    assert proveedor.enviados == [AGRADECIMIENTO] and gabi.llamadas == 0
    assert len(await _conversaciones(telefono)) == 1
    salientes = [m for m in await _mensajes(telefono, "assistant") if m.content == AGRADECIMIENTO]
    assert len(salientes) == 1 and salientes[0].conversation_id == conv.id and salientes[0].via_app is False
    assert salientes[0].mensaje_id_meta == "wamid.OK" and salientes[0].estado_envio is None
    marcas = await _marcas(telefono)
    assert len(marcas) == 1 and marcas[0]["payload"]["resultado"] == "enviado" and marcas[0]["payload"]["texto"] == AGRADECIMIENTO
    async with mem.async_session() as session:
        envio = (await session.execute(select(mem.EnvioMeta).where(mem.EnvioMeta.origen == "agradecimiento_cierre"))).scalars().all()
    assert len(envio) == 1 and envio[0].telefono == telefono and envio[0].tipo == "texto" and envio[0].decision == "enviado"
    assert envio[0].categoria_esperada == "service"

    # Una vez por cierre: otro "gracias" se absorbe pero no vuelve a responder
    await _correr(proveedor, [_msg(telefono, canal, "gracias", "wamid.gr-u2")])
    assert proveedor.enviados == [AGRADECIMIENTO] and len(await _marcas(telefono)) == 1
    assert len(await _conversaciones(telefono)) == 1
    assert len(await _eventos(telefono, "mensaje_de_cierre_sin_reabrir")) == 2


async def test_gracias_fuera_del_lapso_tambien_se_agradece_una_vez(monkeypatch):
    telefono = "51939568071"
    negocio, canal, canal_dict, conv = await _caso_cerrado_hace("g-gr-v", telefono, 40)
    proveedor, gabi = _preparar_webhook(monkeypatch, canal_dict, canal, [])

    await _correr(proveedor, [_msg(telefono, canal, "gracias", "wamid.gr-v1")])
    await _correr(proveedor, [_msg(telefono, canal, "gracias", "wamid.gr-v2")])

    assert proveedor.enviados == [AGRADECIMIENTO] and gabi.llamadas == 0
    assert len(await _conversaciones(telefono)) == 1
    fila = await _fila_bandeja(negocio, telefono)
    assert fila["respondio_tras_cierre_en"] is None and fila["mensajes_pendientes"] == 0   # sigue siendo "suelto"


@pytest.mark.parametrize("texto, tipo", [
    ("ok", "text"), ("Oh ya ok", "text"), ("listo", "text"), ("Perfecto", "text"), ("👍", "text"), ("🙏", "text"),
    ("Reaccionó con 👍", "reaction"),
])
async def test_ok_emoji_y_reacciones_no_reciben_agradecimiento(monkeypatch, texto, tipo):
    telefono = f"519395681{abs(hash(texto)) % 90 + 10}"
    negocio, canal, canal_dict, conv = await _caso_cerrado(f"g-gr-w{abs(hash(texto)) % 90 + 10}", telefono)
    proveedor, gabi = _preparar_webhook(monkeypatch, canal_dict, canal, [])

    await _correr(proveedor, [_msg(telefono, canal, texto, "wamid.gr-w", tipo=tipo)])

    assert proveedor.enviados == [] and await _marcas(telefono) == []
    assert len(await _conversaciones(telefono)) == 1 and gabi.llamadas == 0


async def test_ok_gracias_cuenta_como_gratitud(monkeypatch):
    telefono = "51939568072"
    negocio, canal, canal_dict, conv = await _caso_cerrado("g-gr-x", telefono)
    proveedor, gabi = _preparar_webhook(monkeypatch, canal_dict, canal, [])
    await _correr(proveedor, [_msg(telefono, canal, "ok gracias", "wamid.gr-x")])
    assert proveedor.enviados == [AGRADECIMIENTO]


async def test_el_ok_posterior_al_agradecimiento_sigue_absorbido_y_no_reabre(monkeypatch):
    telefono = "51939568073"
    negocio, canal, canal_dict, conv = await _caso_cerrado("g-gr-y", telefono)
    proveedor, gabi = _preparar_webhook(monkeypatch, canal_dict, canal, [])

    await _correr(proveedor, [_msg(telefono, canal, "gracias", "wamid.gr-y1")])
    assert proveedor.enviados == [AGRADECIMIENTO]
    # el agradecimiento automático NO es una respuesta humana: C4 y el último saliente lo ignoran
    ctx = await _evaluar(telefono, negocio, "ok")
    assert ctx is not None and ctx["ultimo_saliente_id"] == (await _mensajes(telefono, "asesor"))[-1].id

    await _correr(proveedor, [_msg(telefono, canal, "ok", "wamid.gr-y2")])
    await _correr(proveedor, [_msg(telefono, canal, "Oh ya ok", "wamid.gr-y3")])

    assert len(await _conversaciones(telefono)) == 1 and gabi.llamadas == 0
    assert await _eventos(telefono, "reabierto_por_cliente") == []
    assert proveedor.enviados == [AGRADECIMIENTO]


async def test_un_humano_que_escribe_despues_si_reabre_aunque_haya_agradecimiento(monkeypatch):
    telefono = "51939568074"
    negocio, canal, canal_dict, conv = await _caso_cerrado("g-gr-z", telefono)
    proveedor, gabi = _preparar_webhook(monkeypatch, canal_dict, canal, [])
    await _correr(proveedor, [_msg(telefono, canal, "gracias", "wamid.gr-z1")])
    assert await _evaluar(telefono, negocio, "ok") is not None
    await mem.guardar_mensaje(telefono, "asesor", "Una cosa más", negocio_id=negocio["id"])
    assert await _evaluar(telefono, negocio, "ok") is None       # C4 sigue funcionando para humanos


async def test_citar_el_agradecimiento_no_cambia_el_contexto(monkeypatch):
    telefono = "51939568075"
    negocio, canal, canal_dict, conv = await _caso_cerrado("g-gr-aa", telefono)
    proveedor, gabi = _preparar_webhook(monkeypatch, canal_dict, canal, [])
    await _correr(proveedor, [_msg(telefono, canal, "gracias", "wamid.gr-aa1")])
    # "necesitas" del agradecimiento activaría C3 si se tomara como contexto
    assert mem.saliente_deja_algo_pendiente(AGRADECIMIENTO) is True
    ctx = await _evaluar(telefono, negocio, "ok", contexto_id="wamid.OK")
    assert ctx is not None


async def test_el_agradecimiento_se_apaga_con_la_clave(monkeypatch):
    telefono = "51939568076"
    negocio, canal, canal_dict, conv = await _caso_cerrado("g-gr-ab", telefono)
    await mem.guardar_configuracion("agradecimiento_cierre_activo", "0", negocio_id=negocio["id"])
    proveedor, gabi = _preparar_webhook(monkeypatch, canal_dict, canal, [])

    await _correr(proveedor, [_msg(telefono, canal, "gracias", "wamid.gr-ab")])

    assert proveedor.enviados == [] and await _marcas(telefono) == []
    assert len(await _conversaciones(telefono)) == 1                    # sigue absorbido
    assert len(await _eventos(telefono, "mensaje_de_cierre_sin_reabrir")) == 1


@pytest.mark.parametrize("valor, activo", [("1", True), ("0", False), ("", True), ("false", False), ("sí", True)])
async def test_interruptor_del_agradecimiento(valor, activo):
    n = await mem.crear_negocio(f"Negocio sw{valor}", f"g-gr-sw{abs(hash(valor)) % 1000}")
    if valor != "":
        await mem.guardar_configuracion("agradecimiento_cierre_activo", valor, negocio_id=n["id"])
    assert await mem.agradecimiento_cierre_activo(n["id"]) is activo
    sin_config = await mem.crear_negocio("Negocio sw-defecto", f"g-gr-swd{abs(hash(valor)) % 1000}")
    assert await mem.agradecimiento_cierre_activo(sin_config["id"]) is True       # default: encendido


async def test_el_texto_del_agradecimiento_es_configurable(monkeypatch):
    telefono = "51939568077"
    negocio, canal, canal_dict, conv = await _caso_cerrado("g-gr-ac", telefono)
    await mem.guardar_configuracion("agradecimiento_cierre_texto", "Gracias por confiar en nosotros 💙", negocio_id=negocio["id"])
    proveedor, gabi = _preparar_webhook(monkeypatch, canal_dict, canal, [])

    await _correr(proveedor, [_msg(telefono, canal, "gracias", "wamid.gr-ac1")])
    assert proveedor.enviados == ["Gracias por confiar en nosotros 💙"]
    # y su texto (no el de fábrica) es el que se ignora como saliente
    assert await _evaluar(telefono, negocio, "ok") is not None

    # un texto vacío vuelve al de fábrica
    await mem.guardar_configuracion("agradecimiento_cierre_texto", "   ", negocio_id=negocio["id"])
    assert await mem.obtener_texto_agradecimiento_cierre(negocio["id"]) == AGRADECIMIENTO


async def test_no_se_envia_si_la_ventana_de_24_horas_no_esta_abierta(monkeypatch):
    telefono = "51939568078"
    negocio, canal, canal_dict, conv = await _caso_cerrado("g-gr-ad", telefono)
    proveedor, gabi = _preparar_webhook(monkeypatch, canal_dict, canal, [])

    async def ventana_cerrada(*a, **k):
        return {"ventana_24h_abierta": False, "puede_texto_libre": False}
    monkeypatch.setattr(app_main, "obtener_estado_ventana", ventana_cerrada)

    await _correr(proveedor, [_msg(telefono, canal, "gracias", "wamid.gr-ad")])

    assert proveedor.enviados == [] and await _marcas(telefono) == []
    assert len(await _conversaciones(telefono)) == 1


async def test_si_el_envio_falla_no_se_reintenta_y_la_cortesia_igual_se_absorbe(monkeypatch):
    telefono = "51939568079"
    negocio, canal, canal_dict, conv = await _caso_cerrado("g-gr-ae", telefono)
    proveedor, gabi = _preparar_webhook(monkeypatch, canal_dict, canal, [])
    intentos = []

    async def enviar_roto(telefono_, mensaje, canal=None, mensaje_id_citado=None):
        intentos.append(mensaje)
        return False, None
    proveedor.enviar_mensaje = enviar_roto

    await _correr(proveedor, [_msg(telefono, canal, "gracias", "wamid.gr-ae1")])
    await _correr(proveedor, [_msg(telefono, canal, "gracias", "wamid.gr-ae2")])

    assert intentos == [AGRADECIMIENTO]                                   # un solo intento
    marcas = await _marcas(telefono)
    assert len(marcas) == 1 and marcas[0]["payload"]["resultado"] == "fallido"
    assert [m for m in await _mensajes(telefono, "assistant") if m.content == AGRADECIMIENTO] == []   # nada que reintentar en el chat
    assert len(await _conversaciones(telefono)) == 1 and gabi.llamadas == 0
    assert len(await _eventos(telefono, "mensaje_de_cierre_sin_reabrir")) == 2


async def test_un_envio_incierto_se_marca_como_enviado_para_no_duplicar(monkeypatch):
    telefono = "51939568080"
    negocio, canal, canal_dict, conv = await _caso_cerrado("g-gr-af", telefono)
    proveedor, gabi = _preparar_webhook(monkeypatch, canal_dict, canal, [])
    intentos = []

    async def enviar_incierto(telefono_, mensaje, canal=None, mensaje_id_citado=None):
        intentos.append(mensaje)
        raise EnvioIncierto("ReadTimeout")
    proveedor.enviar_mensaje = enviar_incierto

    await _correr(proveedor, [_msg(telefono, canal, "gracias", "wamid.gr-af1")])
    await _correr(proveedor, [_msg(telefono, canal, "gracias", "wamid.gr-af2")])

    assert intentos == [AGRADECIMIENTO]
    marcas = await _marcas(telefono)
    assert len(marcas) == 1 and marcas[0]["payload"]["resultado"] == "incierto"
    guardados = [m for m in await _mensajes(telefono, "assistant") if m.content == AGRADECIMIENTO]
    assert len(guardados) == 1 and guardados[0].estado_envio == "incierto"
    assert len(await _conversaciones(telefono)) == 1
    # y un "ok" posterior sigue absorbido: el incierto tampoco cuenta como respuesta humana
    assert await _evaluar(telefono, negocio, "ok") is not None


async def test_un_envio_frenado_por_la_politica_de_costos_no_rompe_nada(monkeypatch):
    telefono = "51939568081"
    negocio, canal, canal_dict, conv = await _caso_cerrado("g-gr-ag", telefono)
    await mem.guardar_configuracion("envios_modo_agradecimiento_cierre", "nunca", negocio_id=negocio["id"])
    proveedor, gabi = _preparar_webhook(monkeypatch, canal_dict, canal, [])

    await _correr(proveedor, [_msg(telefono, canal, "gracias", "wamid.gr-ag1")])
    await _correr(proveedor, [_msg(telefono, canal, "gracias", "wamid.gr-ag2")])

    assert proveedor.enviados == []
    marcas = await _marcas(telefono)
    assert len(marcas) == 1 and marcas[0]["payload"]["resultado"] == "bloqueado"
    assert len(await _conversaciones(telefono)) == 1 and gabi.llamadas == 0
    async with mem.async_session() as session:
        envio = (await session.execute(select(mem.EnvioMeta).where(mem.EnvioMeta.origen == "agradecimiento_cierre"))).scalars().all()
    assert len(envio) == 1 and envio[0].decision == "bloqueado"


async def test_si_el_agradecimiento_lanza_un_error_la_cortesia_igual_queda_absorbida(monkeypatch):
    telefono = "51939568082"
    negocio, canal, canal_dict, conv = await _caso_cerrado("g-gr-ah", telefono)
    proveedor, gabi = _preparar_webhook(monkeypatch, canal_dict, canal, [])

    async def rota(*a, **k):
        raise RuntimeError("falla simulada")
    monkeypatch.setattr(app_main.envios, "enviar_texto", rota)

    await _correr(proveedor, [_msg(telefono, canal, "gracias", "wamid.gr-ah")])

    assert len(await _conversaciones(telefono)) == 1 and gabi.llamadas == 0
    assert len(await _eventos(telefono, "mensaje_de_cierre_sin_reabrir")) == 1


async def test_un_nuevo_cierre_permite_otro_agradecimiento(monkeypatch):
    telefono = "51939568083"
    negocio, canal, canal_dict, conv = await _caso_cerrado("g-gr-ai", telefono)
    proveedor, gabi = _preparar_webhook(monkeypatch, canal_dict, canal, [])
    await _correr(proveedor, [_msg(telefono, canal, "gracias", "wamid.gr-ai1")])
    assert proveedor.enviados == [AGRADECIMIENTO]

    # Reabrir y volver a cerrar: es OTRO cierre, así que vale otro agradecimiento
    await dashboard.conversation_reabrir(conv.id, usuario=_usuario(negocio), _csrf=None)
    assert await mem.cerrar_lead_definitivamente(telefono, negocio["id"], "angie") is True
    await mem.guardar_mensaje(telefono, "asesor", "Listo, quedo atento.", negocio_id=negocio["id"])
    # (el asesor escribió DESPUÉS del cierre: C4 reabriría; se corrige para aislar la regla de "una vez por cierre")
    async with mem.async_session() as session:
        await session.execute(update(mem.Mensaje).where(
            mem.Mensaje.telefono == telefono, mem.Mensaje.content == "Listo, quedo atento.",
        ).values(timestamp=datetime.utcnow() - timedelta(minutes=5)))
        await session.commit()
    await _correr(proveedor, [_msg(telefono, canal, "gracias", "wamid.gr-ai2")])
    assert proveedor.enviados == [AGRADECIMIENTO, AGRADECIMIENTO]


# ── Configuración de envíos ────────────────────────────────────────────────

async def test_el_origen_aparece_en_la_configuracion_de_envios_con_sus_valores():
    n = await mem.crear_negocio("Negocio g-gr-cfg", "g-gr-cfg")
    c = await mem.obtener_configuracion_envios(n["id"])
    por = {o["origen"]: o for o in c["origenes"]}
    assert set(por) == set(envios.ORIGENES) and len(por) >= 12
    o = por["agradecimiento_cierre"]
    assert (o["esencial"], o["exento_tope"], o["modo"], o["agrupar_minutos"], o["categoria_plantilla"]) == (False, False, "siempre", None, None)
    # se puede frenar con su interruptor, como cualquier origen no esencial
    await mem.guardar_configuracion_uso_meta(n["id"], {"envios": {"modos": {"agradecimiento_cierre": "nunca"}}}, autor="x")
    por = {o["origen"]: o for o in (await mem.obtener_configuracion_envios(n["id"]))["origenes"]}
    assert por["agradecimiento_cierre"]["modo"] == "nunca"
