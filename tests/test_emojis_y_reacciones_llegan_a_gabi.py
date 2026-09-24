# Los emojis escritos en un mensaje y las reacciones (👍, ❤️…) son texto: Gabi
# (Claude) los entiende sin ningún trabajo extra, pero hay que asegurar que NADA
# en el camino los altere ni los pierda (2026-09-24, pedido del usuario:
# "asegúrate que esté activo y funcione"). Estos tests fijan ese camino:
#   · un mensaje con emojis llega a Claude tal cual, byte por byte.
#   · una reacción queda en el historial y viaja a Claude en el turno siguiente.

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from agent import brain


def _respuesta_falsa():
    uso = SimpleNamespace(input_tokens=100, output_tokens=20, cache_read_input_tokens=0, cache_creation_input_tokens=0)
    return SimpleNamespace(content=[SimpleNamespace(text="ok")], usage=uso)


def _texto_del_turno(mensaje: dict) -> str:
    contenido = mensaje["content"]
    return contenido if isinstance(contenido, str) else "".join(b["text"] for b in contenido)


async def test_un_mensaje_con_emojis_llega_a_claude_sin_alteraciones():
    texto = "¡Me interesa la terma! 😊👍🔥 ¿Cuánto cuesta? ❤️"
    with patch.object(brain.client.messages, "create", new=AsyncMock(return_value=_respuesta_falsa())) as create:
        await brain.generar_respuesta(texto, historial=[], modo="produccion", negocio_id=None)

    enviado = _texto_del_turno(create.await_args.kwargs["messages"][-1])
    assert texto in enviado


async def test_un_mensaje_que_es_solo_un_emoji_tampoco_se_descarta():
    with patch.object(brain.client.messages, "create", new=AsyncMock(return_value=_respuesta_falsa())) as create:
        respuesta, hubo_error, _, _ = await brain.generar_respuesta("👍", historial=[], modo="produccion", negocio_id=None)

    assert create.await_count == 1 and hubo_error is False
    assert "👍" in _texto_del_turno(create.await_args.kwargs["messages"][-1])


async def test_una_reaccion_guardada_en_el_historial_viaja_a_claude():
    historial = [
        {"role": "user", "content": "Hola"},
        {"role": "assistant", "content": "¡Hola! ¿Qué te interesa?"},
        {"role": "user", "content": "Reaccionó con 👍"},
    ]
    with patch.object(brain.client.messages, "create", new=AsyncMock(return_value=_respuesta_falsa())) as create:
        await brain.generar_respuesta("Cuéntame más", historial=historial, modo="produccion", negocio_id=None)

    turnos = [_texto_del_turno(m) for m in create.await_args.kwargs["messages"]]
    assert "Reaccionó con 👍" in turnos
    assert "Cuéntame más" in turnos[-1]
