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
# GestorConexiones — negocio_id en el filtro de emisión (el hallazgo T1
# confirmado independientemente por 3 ángulos de investigación)
# ---------------------------------------------------------------------------

async def test_emitir_mensaje_nuevo_no_cruza_negocios():
    negocio_a, canal_a = await _negocio_con_canal("t1f", "40000000006")
    negocio_b, canal_b = await _negocio_con_canal("t1g", "40000000007")
    telefono_a = "51900400004"
    await mem.actualizar_lead(telefono_a, negocio_id=negocio_a["id"], nombre="Cliente A")

    gestor = GestorConexiones()
    ws_admin_a = _WSFalso()
    ws_admin_b = _WSFalso()
    await gestor.conectar(ws_admin_a, "admin_a", "admin", negocio_a["id"])
    await gestor.conectar(ws_admin_b, "admin_b", "admin", negocio_b["id"])

    await gestor.emitir_mensaje_nuevo(telefono_a)

    assert len(ws_admin_a.eventos_recibidos) == 1
    assert ws_admin_a.eventos_recibidos[0]["telefono"] == telefono_a
    assert ws_admin_a.eventos_recibidos[0]["conversation_id"] is None  # aditivo, Gate 5.4
    assert len(ws_admin_b.eventos_recibidos) == 0  # admin de OTRO Negocio no recibe nada


async def test_emitir_mensaje_nuevo_respeta_asesor_asignado_dentro_del_mismo_negocio():
    negocio, canal = await _negocio_con_canal("t1h", "40000000008")
    telefono = "51900400005"
    await mem.actualizar_lead(telefono, negocio_id=negocio["id"], nombre="Cliente")
    await mem.asignar_asesor_a_lead(telefono, "asesor_dueno")

    gestor = GestorConexiones()
    ws_dueno = _WSFalso()
    ws_otro_asesor = _WSFalso()
    ws_admin = _WSFalso()
    await gestor.conectar(ws_dueno, "asesor_dueno", "asesor", negocio["id"])
    await gestor.conectar(ws_otro_asesor, "otro_asesor", "asesor", negocio["id"])
    await gestor.conectar(ws_admin, "admin1", "admin", negocio["id"])

    await gestor.emitir_mensaje_nuevo(telefono)

    assert len(ws_dueno.eventos_recibidos) == 1       # es el asesor asignado
    assert len(ws_admin.eventos_recibidos) == 1        # admin ve todo DENTRO de su Negocio
    assert len(ws_otro_asesor.eventos_recibidos) == 0  # asesor sin acceso a ESTE lead


async def test_emitir_mensaje_nuevo_lead_inexistente_no_emite_a_nadie():
    gestor = GestorConexiones()
    ws = _WSFalso()
    negocio, _ = await _negocio_con_canal("t1i", "40000000009")
    await gestor.conectar(ws, "admin1", "admin", negocio["id"])

    await gestor.emitir_mensaje_nuevo("51900499998")  # nunca existió

    assert len(ws.eventos_recibidos) == 0


async def test_emitir_escribiendo_incluye_conversation_id_aditivo():
    gestor = GestorConexiones()
    ws = _WSFalso()
    negocio, _ = await _negocio_con_canal("t1j", "40000000010")
    await gestor.conectar(ws, "admin1", "admin", negocio["id"])
    await gestor.set_telefono_activo(ws, "51900400006")

    await gestor.emitir_escribiendo("51900400006", "Otro Asesor", excluir_username="alguien_mas")

    assert len(ws.eventos_recibidos) == 1
    assert ws.eventos_recibidos[0]["conversation_id"] is None


async def test_tenant_002_realtime_mismo_telefono_no_cruza():
    """Caso obligatorio del Gate: mismo teléfono en dos Negocios — el evento
    de uno nunca le llega al admin del otro, aunque casualmente compartan
    el número (colisión hoy imposible por Lead.telefono como PK global,
    pero el filtro de negocio_id no depende de esa coincidencia)."""
    negocio_a, canal_a = await _negocio_con_canal("t1k", "40000000011")
    negocio_b, canal_b = await _negocio_con_canal("t1l", "40000000012")
    telefono = "51900400007"
    await mem.actualizar_lead(telefono, negocio_id=negocio_a["id"], nombre="Cliente compartido")

    gestor = GestorConexiones()
    ws_a = _WSFalso()
    ws_b = _WSFalso()
    await gestor.conectar(ws_a, "admin_a", "admin", negocio_a["id"])
    await gestor.conectar(ws_b, "admin_b", "admin", negocio_b["id"])

    await gestor.emitir_mensaje_nuevo(telefono)

    assert len(ws_a.eventos_recibidos) == 1
    assert len(ws_b.eventos_recibidos) == 0
