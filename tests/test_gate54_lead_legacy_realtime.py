# tests/test_gate54_lead_legacy_realtime.py — Gate 5.4, T1: negocio_id en
# la superficie legacy de Lead (obtener_lead) y en GestorConexiones
# (Realtime). Datos sintéticos únicamente, mismo criterio que el resto del
# Gate 5.3/5.4.

import pytest

from agent import memory as mem
from agent.tiempo_real import GestorConexiones


class _WSFalso:
    """Doble de prueba de `fastapi.WebSocket` — solo la superficie que
    `GestorConexiones` usa: `accept()`, `send_json()`, `close()`. Hashable
    por identidad (default de Python), igual que un WebSocket real, así
    sirve como clave del dict `_conexiones`."""

    def __init__(self):
        self.eventos_recibidos: list[dict] = []
        self.cerrado_con_codigo: int | None = None

    async def accept(self):
        pass

    async def send_json(self, evento: dict):
        self.eventos_recibidos.append(evento)

    async def close(self, code: int | None = None):
        self.cerrado_con_codigo = code


async def _negocio_con_canal(codigo: str, telefono_canal: str):
    negocio = await mem.crear_negocio(f"Negocio {codigo}", codigo)
    canal = await mem.crear_canal_whatsapp(nombre=f"Canal {codigo}", phone_number_id=telefono_canal, negocio_id=negocio["id"])
    return negocio, canal


# ---------------------------------------------------------------------------
# obtener_lead — candado de negocio_id
# ---------------------------------------------------------------------------

async def test_obtener_lead_con_negocio_id_correcto_resuelve():
    negocio, _ = await _negocio_con_canal("t1a", "40000000001")
    telefono = "51900400001"
    await mem.actualizar_lead(telefono, negocio_id=negocio["id"], nombre="Cliente")

    lead = await mem.obtener_lead(telefono, negocio_id=negocio["id"])
    assert lead is not None
    assert lead["nombre"] == "Cliente"


async def test_obtener_lead_con_negocio_id_equivocado_devuelve_none():
    negocio_a, _ = await _negocio_con_canal("t1b", "40000000002")
    negocio_b, _ = await _negocio_con_canal("t1c", "40000000003")
    telefono = "51900400002"
    await mem.actualizar_lead(telefono, negocio_id=negocio_a["id"], nombre="Cliente A")

    assert await mem.obtener_lead(telefono, negocio_id=negocio_b["id"]) is None
    assert await mem.obtener_lead(telefono, negocio_id=negocio_a["id"]) is not None


async def test_obtener_lead_sin_negocio_id_preserva_comportamiento_anterior():
    """Uso interno del webhook (main.py/campanas.py) — sin candado, mismo
    comportamiento que antes de Gate 5.4. Nunca debe usarse desde una ruta
    HTTP/WS autenticada (ver docstring de la función)."""
    negocio, _ = await _negocio_con_canal("t1d", "40000000004")
    telefono = "51900400003"
    await mem.actualizar_lead(telefono, negocio_id=negocio["id"], nombre="Cliente")

    lead = await mem.obtener_lead(telefono)
    assert lead is not None
    assert lead["nombre"] == "Cliente"


async def test_obtener_lead_telefono_inexistente_devuelve_none_con_o_sin_negocio_id():
    assert await mem.obtener_lead("51900499999") is None
    negocio, _ = await _negocio_con_canal("t1e", "40000000005")
    assert await mem.obtener_lead("51900499999", negocio_id=negocio["id"]) is None


# ---------------------------------------------------------------------------
# GestorConexiones — Gate 5.5: identidad migrada de `telefono` a
# `conversation_id` (Arquitectura Integrada Gate 5.5, pregunta central).
# Estos tests reemplazan a los de Gate 5.4/T1 (mismo hallazgo de negocio_id
# en el filtro de emisión, ahora resuelto directo por Conversation.negocio_id
# — sin pasar por el bridge Lead.telefono).
# ---------------------------------------------------------------------------

async def _abrir_conversacion(negocio: dict, canal: dict, telefono: str):
    conversation, opportunity = await mem.resolver_conversation_activa(telefono, negocio["id"], canal["id"])
    return conversation, opportunity


async def test_emitir_mensaje_nuevo_no_cruza_negocios():
    negocio_a, canal_a = await _negocio_con_canal("t1f", "40000000006")
    negocio_b, canal_b = await _negocio_con_canal("t1g", "40000000007")
    telefono_a = "51900400004"
    conversation_a, _ = await _abrir_conversacion(negocio_a, canal_a, telefono_a)

    gestor = GestorConexiones()
    ws_admin_a = _WSFalso()
    ws_admin_b = _WSFalso()
    await gestor.conectar(ws_admin_a, "admin_a", "admin", negocio_a["id"])
    await gestor.conectar(ws_admin_b, "admin_b", "admin", negocio_b["id"])

    await gestor.emitir_mensaje_nuevo(conversation_a.id)

    assert len(ws_admin_a.eventos_recibidos) == 1
    assert ws_admin_a.eventos_recibidos[0]["telefono"] == telefono_a
    assert ws_admin_a.eventos_recibidos[0]["conversation_id"] == conversation_a.id  # Gate 5.5 — identidad real
    assert len(ws_admin_b.eventos_recibidos) == 0  # admin de OTRO Negocio no recibe nada


async def test_emitir_mensaje_nuevo_respeta_asesor_asignado_dentro_del_mismo_negocio():
    negocio, canal = await _negocio_con_canal("t1h", "40000000008")
    telefono = "51900400005"
    conversation, _ = await _abrir_conversacion(negocio, canal, telefono)
    assert await mem.intentar_asignar_conversation(conversation.id, conversation.version, "asesor_dueno")

    gestor = GestorConexiones()
    ws_dueno = _WSFalso()
    ws_otro_asesor = _WSFalso()
    ws_admin = _WSFalso()
    await gestor.conectar(ws_dueno, "asesor_dueno", "asesor", negocio["id"])
    await gestor.conectar(ws_otro_asesor, "otro_asesor", "asesor", negocio["id"])
    await gestor.conectar(ws_admin, "admin1", "admin", negocio["id"])

    await gestor.emitir_mensaje_nuevo(conversation.id)

    assert len(ws_dueno.eventos_recibidos) == 1       # es el asesor asignado
    assert len(ws_admin.eventos_recibidos) == 1        # admin ve todo DENTRO de su Negocio
    assert len(ws_otro_asesor.eventos_recibidos) == 0  # asesor sin acceso a ESTA Conversation


async def test_emitir_mensaje_nuevo_conversation_inexistente_no_emite_a_nadie():
    gestor = GestorConexiones()
    ws = _WSFalso()
    negocio, _ = await _negocio_con_canal("t1i", "40000000009")
    await gestor.conectar(ws, "admin1", "admin", negocio["id"])

    await gestor.emitir_mensaje_nuevo("00000000-0000-0000-0000-000000000000")  # nunca existió

    assert len(ws.eventos_recibidos) == 0


async def test_emitir_mensaje_nuevo_sin_conversation_id_no_emite_a_nadie():
    """conversation_id=None (mensaje sin Conversation resoluble, huérfano
    histórico) — fail-closed, no hay a quién emitirle con seguridad."""
    gestor = GestorConexiones()
    ws = _WSFalso()
    negocio, _ = await _negocio_con_canal("t1i2", "40000000013")
    await gestor.conectar(ws, "admin1", "admin", negocio["id"])

    await gestor.emitir_mensaje_nuevo(None)

    assert len(ws.eventos_recibidos) == 0


async def test_emitir_mensaje_nuevo_no_emite_si_conversation_no_esta_activa():
    """Contrato WebSocket, Arquitectura Integrada Gate 5.5 — una Conversation
    cerrada no debe seguir generando eventos de mensaje nuevo."""
    negocio, canal = await _negocio_con_canal("t1i3", "40000000014")
    telefono = "51900400009"
    conversation, _ = await _abrir_conversacion(negocio, canal, telefono)
    async with mem.async_session() as session:
        conv = await session.get(mem.Conversation, conversation.id)
        conv.estado = "cerrada"
        await session.commit()

    gestor = GestorConexiones()
    ws = _WSFalso()
    await gestor.conectar(ws, "admin1", "admin", negocio["id"])

    await gestor.emitir_mensaje_nuevo(conversation.id)

    assert len(ws.eventos_recibidos) == 0


async def test_emitir_escribiendo_filtra_por_conversation_id_activo():
    gestor = GestorConexiones()
    ws = _WSFalso()
    negocio, canal = await _negocio_con_canal("t1j", "40000000010")
    telefono = "51900400006"
    conversation, _ = await _abrir_conversacion(negocio, canal, telefono)
    await gestor.conectar(ws, "admin1", "admin", negocio["id"])
    await gestor.set_conversation_activa(ws, conversation.id)

    await gestor.emitir_escribiendo(conversation.id, telefono, "Otro Asesor", excluir_username="alguien_mas")

    assert len(ws.eventos_recibidos) == 1
    assert ws.eventos_recibidos[0]["conversation_id"] == conversation.id
    assert ws.eventos_recibidos[0]["telefono"] == telefono


async def test_tenant_002_realtime_mismo_telefono_dos_conversations_activas_no_cruza():
    """Caso obligatorio del Gate: mismo teléfono en dos Negocios, CADA UNO
    con su propia Conversation activa simultánea — el evento de una nunca le
    llega al admin del otro Negocio. A diferencia de Gate 5.4 (donde
    `Lead.telefono` como PK global hacía este escenario "imposible hoy"),
    Gate 5.5 lo prueba de verdad: `conversation_id` es la identidad real,
    sin depender de esa coincidencia."""
    negocio_a, canal_a = await _negocio_con_canal("t1k", "40000000011")
    negocio_b, canal_b = await _negocio_con_canal("t1l", "40000000012")
    telefono = "51900400007"
    conversation_a, _ = await _abrir_conversacion(negocio_a, canal_a, telefono)
    conversation_b, _ = await _abrir_conversacion(negocio_b, canal_b, telefono)
    assert conversation_a.id != conversation_b.id

    gestor = GestorConexiones()
    ws_a = _WSFalso()
    ws_b = _WSFalso()
    await gestor.conectar(ws_a, "admin_a", "admin", negocio_a["id"])
    await gestor.conectar(ws_b, "admin_b", "admin", negocio_b["id"])

    await gestor.emitir_mensaje_nuevo(conversation_a.id)

    assert len(ws_a.eventos_recibidos) == 1
    assert len(ws_b.eventos_recibidos) == 0

    await gestor.emitir_mensaje_nuevo(conversation_b.id)

    assert len(ws_a.eventos_recibidos) == 1  # sin cambios — el segundo evento no era suyo
    assert len(ws_b.eventos_recibidos) == 1
