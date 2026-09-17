# tests/test_tiempo_real_conexion_lista.py — GestorConexiones.tocar_actividad
# con conversation_id=None (conexión de LISTA, sin `ver_lead`).
#
# Hallazgo propio (2026-09-17, durante el fix de "la lista de chats solo se
# ven los nuevos chats cuando se recarga la página"): `ConversacionesVista`
# ahora abre una conexión WS SIN `ver_lead` para mantener la Bandeja al día
# sin depender de que además haya un `PanelChat` montado (ver
# hooks/use-conversacion-realtime.ts). Esa conexión se queda con
# `conversation_id_activo=None` para siempre — antes de este fix,
# `tocar_actividad` solo aceptaba un `conversation_id` real, así que esa
# conexión nunca recibía ningún golpe de actividad y el barrido de Gate 4.1
# (`cerrar_inactivas`, cada ~2 min) la cerraría aunque el navegador siguiera
# ahí de verdad.

from agent.tiempo_real import GestorConexiones


class _WebSocketFalso:
    """Doble mínimo — `GestorConexiones` solo necesita `accept()`/`close()`,
    nunca lee ni escribe datos reales en estos tests."""

    async def accept(self):
        pass

    async def close(self, code=None):
        pass


async def test_tocar_actividad_none_refresca_conexion_de_lista():
    gestor = GestorConexiones()
    ws_lista = _WebSocketFalso()
    await gestor.conectar(ws_lista, "admin1", "admin", "negocio-1")
    # Nunca se llama a `set_conversation_activa` — simula la conexión de
    # `ConversacionesVista`, que jamás manda `ver_lead`.
    info = gestor._conexiones[ws_lista]
    assert info["conversation_id_activo"] is None

    info["ultima_actividad"] = 0.0  # simula "hace mucho que no se toca"
    gestor.tocar_actividad("admin1", None)
    assert info["ultima_actividad"] > 0.0


async def test_tocar_actividad_none_no_toca_conexion_de_conversacion_puntual():
    gestor = GestorConexiones()
    ws_chat = _WebSocketFalso()
    await gestor.conectar(ws_chat, "admin1", "admin", "negocio-1")
    await gestor.set_conversation_activa(ws_chat, "conv-123")
    info = gestor._conexiones[ws_chat]

    info["ultima_actividad"] = 0.0
    gestor.tocar_actividad("admin1", None)  # golpe de la conexión de LISTA
    assert info["ultima_actividad"] == 0.0  # esta conexión (conv-123) no debe moverse


async def test_barrido_de_inactivas_no_cierra_conexion_de_lista_tocada_reciente():
    """Reproduce el escenario real: barrido de Gate 4.1 corre, la conexión
    de lista fue tocada hace poco (por el polling incondicional de la
    Bandeja o por su propia carga inicial) — no debe cerrarse."""
    gestor = GestorConexiones()
    ws_lista = _WebSocketFalso()
    await gestor.conectar(ws_lista, "admin1", "admin", "negocio-1")
    gestor.tocar_actividad("admin1", None)

    cerradas = await gestor.cerrar_inactivas(umbral_segundos=120.0)
    assert cerradas == 0
    assert ws_lista in gestor._conexiones


async def test_barrido_de_inactivas_si_cierra_conexion_de_lista_nunca_tocada():
    """Sin el fix (conversation_id=None nunca soportado), esta conexión
    jamás recibiría un golpe de actividad y el barrido la cerraría siempre
    — ver que, con un umbral ya vencido, el barrido efectivamente actúa."""
    gestor = GestorConexiones()
    ws_lista = _WebSocketFalso()
    await gestor.conectar(ws_lista, "admin1", "admin", "negocio-1")
    gestor._conexiones[ws_lista]["ultima_actividad"] -= 200.0  # ya vencida

    cerradas = await gestor.cerrar_inactivas(umbral_segundos=120.0)
    assert cerradas == 1
    assert ws_lista not in gestor._conexiones
