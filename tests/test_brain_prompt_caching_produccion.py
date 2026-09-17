# tests/test_brain_prompt_caching_produccion.py — modo "produccion" ahora
# cachea el system prompt (Prompt Caching, Anthropic).
#
# Hallazgo del usuario (2026-09-17), revisando su consumo real de la API:
# "por qué se consumió tan rápido si en teoría 5 dólares alcanzaban para
# muchas conversaciones". Causa confirmada con logs reales de producción:
# el modo "produccion" (el que corre el canal real de Cálidda, a diferencia
# de "pruebas") mandaba el system prompt completo — idéntico en cada
# mensaje de cada conversación de un mismo Negocio — a precio completo en
# cada llamada, porque nunca llevaba `cache_control`. Solo
# `_generar_respuesta_protocolo_confianza` (modo "pruebas") lo tenía.
#
# Este test NO llama a la API real — mockea `client.messages.create` y
# verifica la FORMA del request (`system` como lista de bloques con
# `cache_control`), que es lo único que se puede probar sin gastar dinero
# real. La confirmación de que el caching efectivamente "pega" en
# producción vive en el log nuevo de `generar_respuesta` (cache_read/
# cache_write), no en un test.

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from agent import brain


def _respuesta_falsa(texto: str = "Respuesta de prueba"):
    bloque = SimpleNamespace(text=texto)
    uso = SimpleNamespace(input_tokens=100, output_tokens=20, cache_read_input_tokens=0, cache_creation_input_tokens=100)
    return SimpleNamespace(content=[bloque], usage=uso)


async def test_modo_produccion_manda_system_con_cache_control():
    with patch.object(brain.client.messages, "create", new=AsyncMock(return_value=_respuesta_falsa())) as mock_create:
        await brain.generar_respuesta("Hola", historial=[], modo="produccion", negocio_id=None)

    assert mock_create.await_count == 1
    kwargs = mock_create.await_args.kwargs
    assert kwargs["model"] == brain.MODELO_PRINCIPAL
    system_enviado = kwargs["system"]
    assert isinstance(system_enviado, list), "system debe ser una lista de bloques, no un string plano, para poder cachear"
    assert len(system_enviado) == 1
    assert system_enviado[0]["type"] == "text"
    assert system_enviado[0]["cache_control"] == {"type": "ephemeral"}


async def test_modo_produccion_el_texto_del_system_no_cambia():
    """El caching es aditivo — el contenido real del system prompt que ve
    Gabi debe seguir siendo exactamente el mismo texto que antes, solo
    envuelto en la forma que permite cachear."""
    esperado = brain.cargar_system_prompt()
    with patch.object(brain.client.messages, "create", new=AsyncMock(return_value=_respuesta_falsa())) as mock_create:
        await brain.generar_respuesta("Hola", historial=[], modo="produccion", negocio_id=None)

    system_enviado = mock_create.await_args.kwargs["system"]
    assert system_enviado[0]["text"] == esperado


async def test_historial_vacio_no_rompe_nada():
    """Sin historial previo (primer mensaje de una conversación nueva), no
    debe haber ningún IndexError al intentar marcar "el último mensaje del
    historial" — simplemente no hay nada que cachear todavía."""
    with patch.object(brain.client.messages, "create", new=AsyncMock(return_value=_respuesta_falsa())) as mock_create:
        await brain.generar_respuesta("Hola", historial=[], modo="produccion", negocio_id=None)

    mensajes = mock_create.await_args.kwargs["messages"]
    assert len(mensajes) == 1  # solo el turno actual, sin historial


async def test_solo_el_ultimo_mensaje_del_historial_lleva_cache_control():
    """2026-09-17, prioridad #1 del usuario (reducir el consumo de la API
    más allá del system prompt): el historial de la conversación (idéntico
    de una llamada a la siguiente, salvo el turno que se acaba de agregar)
    ahora también se cachea — pero SOLO se marca el último bloque del
    historial YA GUARDADO, nunca el turno actual (que va decorado con
    catálogo/hora y es distinto en cada llamada por diseño)."""
    historial = [
        {"role": "user", "content": "Hola, buenas"},
        {"role": "assistant", "content": "¡Hola! ¿En qué te ayudo?"},
        {"role": "user", "content": "Busco una terma"},
        {"role": "asesor", "content": "Claro, te ayudo con eso"},
    ]
    with patch.object(brain.client.messages, "create", new=AsyncMock(return_value=_respuesta_falsa())) as mock_create:
        await brain.generar_respuesta("¿Cuánto cuesta?", historial=historial, modo="produccion", negocio_id=None)

    mensajes = mock_create.await_args.kwargs["messages"]
    assert len(mensajes) == 5  # 4 de historial + 1 turno actual

    # Los primeros 3 mensajes del historial quedan tal cual (content plano,
    # sin cache_control) — solo el ÚLTIMO se marca.
    for i in range(3):
        assert isinstance(mensajes[i]["content"], str)

    ultimo_historial = mensajes[3]
    assert ultimo_historial["role"] == "assistant"  # "asesor" se mapea a "assistant"
    assert isinstance(ultimo_historial["content"], list)
    assert ultimo_historial["content"][0]["text"] == "Claro, te ayudo con eso"
    assert ultimo_historial["content"][0]["cache_control"] == {"type": "ephemeral"}

    # El turno ACTUAL (el que se acaba de recibir) nunca lleva cache_control
    # — es contenido nuevo en cada llamada, cachearlo no ahorraría nada.
    turno_actual = mensajes[4]
    assert turno_actual["role"] == "user"
    assert isinstance(turno_actual["content"], str)
    assert "¿Cuánto cuesta?" in turno_actual["content"]
