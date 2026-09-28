# tests/test_ws_ticket_directo.py — Fase 2, tiempo real directo
# (MAIEK_AI_REALTIME_DIRECT_DESIGN.md, 2026-09-28): la Nueva Experiencia
# (Vercel, otro origen) no puede mandarle a Railway la cookie de sesión de
# FastAPI — pide un ticket de un solo uso por HTTP y lo manda como primer
# mensaje al abrir el WebSocket directo. Mismo criterio de estos tests que
# el resto de la suite (ver test_gate_logout_sesion.py): se llama a las
# funciones reales con duck-types mínimos, sin TestClient/ASGI.

import asyncio
from types import SimpleNamespace

import pytest
from fastapi import WebSocketDisconnect

from agent import dashboard, memory as mem, tiempo_real as tr
from agent.tiempo_real import GestorConexiones, emitir_ticket_ws, validar_y_consumir_ticket_ws


async def _negocio_con_usuario(codigo: str, rol: str = "admin"):
    negocio = await mem.crear_negocio(f"Negocio {codigo}", codigo)
    await mem.crear_usuario(f"u_{codigo}", "pw12345", f"Persona {codigo}", rol, negocio["id"])
    return negocio, f"u_{codigo}"


# ── emitir_ticket_ws / validar_y_consumir_ticket_ws ─────────────────────

def test_un_ticket_valido_resuelve_al_mismo_username():
    ticket = emitir_ticket_ws("asesor1")
    assert validar_y_consumir_ticket_ws(ticket) == "asesor1"


def test_un_ticket_no_se_puede_usar_dos_veces():
    ticket = emitir_ticket_ws("asesor1")
    assert validar_y_consumir_ticket_ws(ticket) == "asesor1"
    assert validar_y_consumir_ticket_ws(ticket) is None  # ya se consumió


def test_un_ticket_vencido_no_vale(monkeypatch):
    ticket = emitir_ticket_ws("asesor1")
    monkeypatch.setattr(tr, "TICKET_WS_MAX_AGE_SEG", -1)  # cualquier edad ya "vencida"
    assert validar_y_consumir_ticket_ws(ticket) is None


def test_un_ticket_alterado_no_vale():
    ticket = emitir_ticket_ws("asesor1")
    # El caracter del MEDIO (no el último): en base64 sin relleno, el último
    # caracter de un grupo incompleto solo codifica unos pocos bits reales —
    # cambiarlo puede decodificar al mismo byte por casualidad. El del medio
    # siempre cae en una posición de precisión completa.
    partes = list(ticket)
    idx = len(partes) // 2
    partes[idx] = "0" if partes[idx] != "0" else "1"
    alterado = "".join(partes)
    assert validar_y_consumir_ticket_ws(alterado) is None


def test_basura_no_es_un_ticket_valido():
    assert validar_y_consumir_ticket_ws("esto-no-es-un-ticket") is None
    assert validar_y_consumir_ticket_ws("") is None


def test_dos_tickets_del_mismo_usuario_son_independientes():
    """No comparten jti — reutilizar uno no invalida al otro."""
    t1, t2 = emitir_ticket_ws("asesor1"), emitir_ticket_ws("asesor1")
    assert validar_y_consumir_ticket_ws(t1) == "asesor1"
    assert validar_y_consumir_ticket_ws(t2) == "asesor1"


# ── POST /dashboard/ws-ticket ────────────────────────────────────────────

async def test_la_ruta_emite_un_ticket_que_resuelve_al_username_de_la_sesion():
    negocio, username = await _negocio_con_usuario("wt1")
    usuario = await mem.obtener_usuario(username)

    respuesta = await dashboard.emitir_ticket_ws_ruta(usuario=usuario, _csrf=None)

    assert validar_y_consumir_ticket_ws(respuesta["ticket"]) == username


# ── GestorConexiones.conectar — ya_aceptado ──────────────────────────────

class _WSSoloAccept:
    def __init__(self):
        self.veces_aceptado = 0

    async def accept(self):
        self.veces_aceptado += 1


async def test_conectar_acepta_por_defecto():
    ws = _WSSoloAccept()
    await GestorConexiones().conectar(ws, "u1", "admin", "negocio1")
    assert ws.veces_aceptado == 1


async def test_conectar_no_vuelve_a_aceptar_si_ya_aceptado():
    ws = _WSSoloAccept()
    await GestorConexiones().conectar(ws, "u1", "admin", "negocio1", ya_aceptado=True)
    assert ws.veces_aceptado == 0


# ── websocket_panel — camino del ticket ──────────────────────────────────

ORIGEN_NE_DE_PRUEBA = "https://maiek-frontend-test.vercel.app"


class _WSFalsoTicket:
    """Duck-type mínimo de `starlette.websockets.WebSocket` para el camino
    cross-origin: sin `.session` con username (a diferencia del panel legacy,
    que sí la trae), con `.headers`/`.url` para el chequeo de Origin, y una
    cola de mensajes que `receive_json()` va entregando uno por uno."""

    def __init__(
        self, origin: str | None = ORIGEN_NE_DE_PRUEBA, mensajes: list | None = None, tardar: bool = False,
    ):
        self.session = {}
        self.headers = {"host": "gaso-plus-agente-production.up.railway.app"}
        if origin is not None:
            self.headers["origin"] = origin
        self.url = SimpleNamespace(scheme="wss")
        self._mensajes = list(mensajes or [])
        self._tardar = tardar
        self.aceptado = False
        self.cerrado_con_codigo: int | None = None

    async def accept(self):
        self.aceptado = True

    async def receive_json(self):
        if self._tardar:
            await asyncio.sleep(10)  # el timeout del caller debe cortar esto mucho antes
        if self._mensajes:
            return self._mensajes.pop(0)
        # Sin más mensajes: simula que el navegador cerró la conexión — el
        # bucle principal de websocket_panel (sin cambios de este Gate, ver
        # dashboard.py) lo atrapa y desconecta limpio. No hace falta simular
        # una conexión colgada indefinidamente: alcanza con comprobar CON QUÉ
        # datos se llamó a `conectar()`, ver `_ConectarEspia` más abajo.
        raise WebSocketDisconnect()

    async def close(self, code: int | None = None):
        self.cerrado_con_codigo = code

    async def send_json(self, evento: dict):
        pass


@pytest.fixture(autouse=True)
def _permitir_origen_de_prueba(monkeypatch):
    monkeypatch.setattr(dashboard, "_ORIGENES_WS_PERMITIDOS", {ORIGEN_NE_DE_PRUEBA})


class _ConectarEspia:
    """`websocket_panel` corre durante TODA la vida de la conexión (el bucle
    `while True: receive_json()`, sin cambios de este Gate) — para comprobar
    con qué datos autenticó sin tener que dejar una tarea de fondo corriendo
    entre tests (ningún otro test de este repo lo hace — ver
    test_gate_logout_sesion.py), se espía el MÉTODO de la instancia real de
    `GestorConexiones` en vez de correr `websocket_panel` como tarea aparte:
    se registra la llamada y se delega en la implementación real, así que
    `conectar()` (accept/registro en `_conexiones`) sigue corriendo tal cual."""

    def __init__(self, gestor: GestorConexiones):
        self.gestor = gestor
        self.llamadas: list[dict] = []
        self._original = gestor.conectar

    async def __call__(self, ws, username, rol, negocio_id, ya_aceptado=False):
        self.llamadas.append({"username": username, "rol": rol, "negocio_id": negocio_id, "ya_aceptado": ya_aceptado})
        await self._original(ws, username, rol, negocio_id, ya_aceptado=ya_aceptado)


async def test_ticket_valido_conecta_sin_cookie_de_sesion(monkeypatch):
    negocio, username = await _negocio_con_usuario("wp1")
    ticket = emitir_ticket_ws(username)
    gestor = GestorConexiones()
    espia = _ConectarEspia(gestor)
    gestor.conectar = espia
    monkeypatch.setattr(dashboard, "gestor_conexiones", gestor)
    ws = _WSFalsoTicket(mensajes=[{"tipo": "auth", "ticket": ticket}])

    await dashboard.websocket_panel(ws)

    assert ws.aceptado is True
    # `cerrado_con_codigo` sigue None: la conexión terminó por el
    # WebSocketDisconnect normal del bucle (el fake ya no tiene más mensajes),
    # nunca por un `close()` explícito de rechazo — se autenticó de verdad.
    assert ws.cerrado_con_codigo is None
    assert espia.llamadas == [{"username": username, "rol": "admin", "negocio_id": negocio["id"], "ya_aceptado": True}]


async def test_ticket_ya_usado_no_conecta(monkeypatch):
    _, username = await _negocio_con_usuario("wp2")
    ticket = emitir_ticket_ws(username)
    validar_y_consumir_ticket_ws(ticket)  # lo consume por adelantado
    gestor = GestorConexiones()
    monkeypatch.setattr(dashboard, "gestor_conexiones", gestor)
    ws = _WSFalsoTicket(mensajes=[{"tipo": "auth", "ticket": ticket}])

    await dashboard.websocket_panel(ws)

    assert ws.cerrado_con_codigo == 4401
    assert ws not in gestor._conexiones


async def test_ticket_de_usuario_que_ya_no_existe_no_conecta(monkeypatch):
    ticket = emitir_ticket_ws("nadie-existe-con-este-username")
    gestor = GestorConexiones()
    monkeypatch.setattr(dashboard, "gestor_conexiones", gestor)
    ws = _WSFalsoTicket(mensajes=[{"tipo": "auth", "ticket": ticket}])

    await dashboard.websocket_panel(ws)

    assert ws.cerrado_con_codigo == 4401


async def test_primer_mensaje_sin_tipo_auth_no_conecta(monkeypatch):
    _, username = await _negocio_con_usuario("wp3")
    ticket = emitir_ticket_ws(username)
    gestor = GestorConexiones()
    monkeypatch.setattr(dashboard, "gestor_conexiones", gestor)
    # Manda el ticket, pero con el tipo de mensaje equivocado.
    ws = _WSFalsoTicket(mensajes=[{"tipo": "ver_lead", "ticket": ticket}])

    await dashboard.websocket_panel(ws)

    assert ws.cerrado_con_codigo == 4401


async def test_desconexion_antes_de_mandar_el_ticket_no_conecta(monkeypatch):
    gestor = GestorConexiones()
    monkeypatch.setattr(dashboard, "gestor_conexiones", gestor)
    ws = _WSFalsoTicket(mensajes=[])  # el navegador cierra antes de autenticarse

    await dashboard.websocket_panel(ws)

    assert ws.cerrado_con_codigo == 4401


async def test_sin_mensaje_a_tiempo_se_cierra_por_plazo_vencido(monkeypatch):
    monkeypatch.setattr(dashboard, "PLAZO_AUTH_WS_TICKET_SEG", 0.05)
    gestor = GestorConexiones()
    monkeypatch.setattr(dashboard, "gestor_conexiones", gestor)
    ws = _WSFalsoTicket(tardar=True)

    await dashboard.websocket_panel(ws)

    assert ws.cerrado_con_codigo == 4401


async def test_origin_no_permitido_rechaza_incluso_con_ticket_valido(monkeypatch):
    _, username = await _negocio_con_usuario("wp4")
    ticket = emitir_ticket_ws(username)
    gestor = GestorConexiones()
    monkeypatch.setattr(dashboard, "gestor_conexiones", gestor)
    ws = _WSFalsoTicket(origin="https://sitio-ajeno.example", mensajes=[{"tipo": "auth", "ticket": ticket}])

    await dashboard.websocket_panel(ws)

    assert ws.aceptado is False  # ni siquiera llega a aceptarse — se corta antes
    assert ws.cerrado_con_codigo == 4403


async def test_el_camino_legacy_con_cookie_de_sesion_sigue_igual(monkeypatch):
    """El cambio no debe afectar al panel legacy — sigue resolviendo por la
    cookie de sesión, sin pasar por el ticket."""
    negocio, username = await _negocio_con_usuario("wp5")
    gestor = GestorConexiones()
    espia = _ConectarEspia(gestor)
    gestor.conectar = espia
    monkeypatch.setattr(dashboard, "gestor_conexiones", gestor)
    ws = _WSFalsoTicket(origin=None)  # same-origin real: sin header Origin
    ws.session = {"username": username}  # cookie de sesión ya resuelta por SessionMiddleware

    await dashboard.websocket_panel(ws)

    assert ws.cerrado_con_codigo is None
    assert espia.llamadas == [{"username": username, "rol": "admin", "negocio_id": negocio["id"], "ya_aceptado": False}]


# ── GestorConexiones.emitir_latido_a_todos ───────────────────────────────
# Fase 2: sin el relay de por medio, el navegador necesita una señal de
# aplicación (no solo el ping/pong de protocolo, invisible para JS) para
# notar una conexión que murió en silencio.

class _WSFalsoLatido:
    def __init__(self, falla_al_enviar: bool = False):
        self.eventos_recibidos: list[dict] = []
        self._falla_al_enviar = falla_al_enviar
        self.desconectado_por_el_gestor = False

    async def accept(self):
        pass

    async def send_json(self, evento: dict):
        if self._falla_al_enviar:
            raise RuntimeError("conexión muerta")
        self.eventos_recibidos.append(evento)

    async def close(self, code: int | None = None):
        pass


async def test_el_latido_llega_a_todas_las_conexiones_conectadas():
    gestor = GestorConexiones()
    ws1, ws2 = _WSFalsoLatido(), _WSFalsoLatido()
    await gestor.conectar(ws1, "u1", "admin", "n1")
    await gestor.conectar(ws2, "u2", "asesor", "n1")

    await gestor.emitir_latido_a_todos()

    assert ws1.eventos_recibidos == [{"tipo": "latido"}]
    assert ws2.eventos_recibidos == [{"tipo": "latido"}]


async def test_el_latido_desconecta_sola_una_conexion_ya_muerta():
    gestor = GestorConexiones()
    ws_viva, ws_muerta = _WSFalsoLatido(), _WSFalsoLatido(falla_al_enviar=True)
    await gestor.conectar(ws_viva, "u1", "admin", "n1")
    await gestor.conectar(ws_muerta, "u2", "asesor", "n1")

    await gestor.emitir_latido_a_todos()

    assert ws_viva.eventos_recibidos == [{"tipo": "latido"}]
    assert ws_muerta not in gestor._conexiones  # _enviar_seguro ya la limpió
    assert ws_viva in gestor._conexiones
