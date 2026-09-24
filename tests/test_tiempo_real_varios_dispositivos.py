# tests/test_tiempo_real_varios_dispositivos.py — hallazgo real (2026-09-23):
# con la laptop y el celular del MISMO usuario en el MISMO chat, cada conexión
# nueva cerraba a la otra (máximo 1), la cerrada reconectaba y el ciclo se
# repetía cada ~5 s, dejando las dos pantallas sin aviso instantáneo. Ahora se
# toleran hasta MAX_CONEXIONES_POR_USUARIO_Y_CONVERSACION a la vez.

from agent.tiempo_real import GestorConexiones, MAX_CONEXIONES_POR_USUARIO_Y_CONVERSACION


class _WebSocketFalso:
    def __init__(self):
        self.cerrado_con: int | None = None

    async def accept(self):
        pass

    async def close(self, code=None):
        self.cerrado_con = code


async def _conectar_a_chat(gestor, usuario: str, conversation_id: str):
    ws = _WebSocketFalso()
    await gestor.conectar(ws, usuario, "admin", "negocio-1")
    await gestor.set_conversation_activa(ws, conversation_id)
    return ws


async def test_laptop_y_celular_del_mismo_usuario_conviven_en_el_mismo_chat():
    gestor = GestorConexiones()
    laptop = await _conectar_a_chat(gestor, "jesus", "conv-1")
    celular = await _conectar_a_chat(gestor, "jesus", "conv-1")

    assert laptop.cerrado_con is None and celular.cerrado_con is None
    assert laptop in gestor._conexiones and celular in gestor._conexiones


async def test_pasado_el_tope_se_cierra_solo_la_mas_antigua_con_4409():
    gestor = GestorConexiones()
    conexiones = [
        await _conectar_a_chat(gestor, "jesus", "conv-1")
        for _ in range(MAX_CONEXIONES_POR_USUARIO_Y_CONVERSACION + 1)
    ]
    assert conexiones[0].cerrado_con == 4409
    assert conexiones[0] not in gestor._conexiones
    assert all(c.cerrado_con is None for c in conexiones[1:])
    assert len([c for c in conexiones if c in gestor._conexiones]) == MAX_CONEXIONES_POR_USUARIO_Y_CONVERSACION


async def test_otro_usuario_o_otro_chat_nunca_se_cuentan_contra_el_tope():
    gestor = GestorConexiones()
    for _ in range(MAX_CONEXIONES_POR_USUARIO_Y_CONVERSACION):
        await _conectar_a_chat(gestor, "jesus", "conv-1")
    de_otro_usuario = await _conectar_a_chat(gestor, "lisbet", "conv-1")
    en_otro_chat = await _conectar_a_chat(gestor, "jesus", "conv-2")
    assert de_otro_usuario.cerrado_con is None and en_otro_chat.cerrado_con is None
