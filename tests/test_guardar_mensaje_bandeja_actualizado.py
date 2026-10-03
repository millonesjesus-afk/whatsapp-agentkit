# tests/test_guardar_mensaje_bandeja_actualizado.py — guardar_mensaje debe
# bumpear Conversation.actualizado.
#
# Hallazgo del usuario (2026-09-17), validando el fix de tiempo real de la
# Bandeja: "ya la lista se actualiza en tiempo real pero no se prioriza
# primero en la lista sino hasta que abro el chat y tampoco genera la bola
# de conteo de mensajes pendientes de leer". Causa real: `guardar_mensaje`
# nunca tocaba `Conversation.actualizado` — la Bandeja ordena por ese campo
# (`listar_conversaciones_activas`, orden="actualizado" por defecto) y está
# paginada, así que una conversación activa que solo recibe mensajes nuevos
# se iba quedando cada vez más "vieja" en el orden hasta caer fuera de la
# página 1 en cuanto hubiera suficientes conversaciones más recientes por
# delante — ahí ni se reordena ni el badge de pendientes es visible, porque
# la fila entera deja de traerse (abrir el chat "arregla" la fila porque esa
# acción SÍ toca `actualizado` en otro flujo, no porque el mensaje nuevo lo
# hubiera hecho).

from datetime import datetime, timedelta

from agent import memory as mem


async def _negocio_con_canal(codigo: str, telefono_canal: str):
    negocio = await mem.crear_negocio(f"Negocio {codigo}", codigo)
    canal = await mem.crear_canal_whatsapp(
        nombre=f"Canal {codigo}", phone_number_id=telefono_canal, negocio_id=negocio["id"],
    )
    return negocio, canal


async def _abrir_conversacion(negocio: dict, canal: dict, telefono: str):
    conversation, opportunity = await mem.resolver_conversation_activa(
        telefono, negocio["id"], canal["id"], unidad_id=canal.get("unidad_id"),
    )
    return conversation, opportunity


async def test_guardar_mensaje_bumpea_actualizado_de_la_conversation():
    negocio, canal = await _negocio_con_canal("gm-act-1", "10000000101")
    conversation, _ = await _abrir_conversacion(negocio, canal, "51900200001")

    # Se envejece artificialmente `actualizado`, simulando una conversación
    # activa que lleva un rato sin recibir mensajes.
    async with mem.async_session() as session:
        fila = await session.get(mem.Conversation, conversation.id)
        fila.actualizado = datetime.utcnow() - timedelta(hours=5)
        await session.commit()

    await mem.guardar_mensaje("51900200001", "user", "¿Siguen ahí?", negocio_id=negocio["id"])

    async with mem.async_session() as session:
        fila = await session.get(mem.Conversation, conversation.id)
        assert fila.actualizado > datetime.utcnow() - timedelta(minutes=1)


async def test_conversacion_con_mensaje_nuevo_sube_al_tope_de_la_bandeja():
    """Reproduce el escenario real: dos conversaciones, la más vieja recibe
    un mensaje nuevo — debe pasar a ser la primera en la Bandeja (orden por
    defecto, actualizado DESC), sin tener que abrir el chat."""
    negocio, canal = await _negocio_con_canal("gm-act-2", "10000000102")
    conversation_vieja, _ = await _abrir_conversacion(negocio, canal, "51900200002")
    conversation_reciente, _ = await _abrir_conversacion(negocio, canal, "51900200003")

    async with mem.async_session() as session:
        vieja = await session.get(mem.Conversation, conversation_vieja.id)
        vieja.actualizado = datetime.utcnow() - timedelta(hours=5)
        vieja.ultimo_mensaje_en = datetime.utcnow() - timedelta(hours=5)
        reciente = await session.get(mem.Conversation, conversation_reciente.id)
        reciente.actualizado = datetime.utcnow() - timedelta(hours=1)
        reciente.ultimo_mensaje_en = datetime.utcnow() - timedelta(hours=1)
        await session.commit()

    filas, _ = await mem.listar_conversaciones_activas(negocio_id=negocio["id"])
    assert [f["id"] for f in filas] == [conversation_reciente.id, conversation_vieja.id]

    # La conversación vieja recibe un mensaje nuevo del cliente — sin abrir
    # ningún chat, debe saltar al primer lugar.
    await mem.guardar_mensaje("51900200002", "user", "Hola de nuevo", negocio_id=negocio["id"])

    filas, _ = await mem.listar_conversaciones_activas(negocio_id=negocio["id"])
    assert [f["id"] for f in filas] == [conversation_vieja.id, conversation_reciente.id]


async def test_mensajes_pendientes_no_depende_de_abrir_el_chat():
    """El conteo de pendientes ya se calculaba fresco en cada consulta — este
    test documenta que sigue siendo correcto sin ninguna acción adicional
    (abrir el chat, marcar como visto), independiente del fix de `actualizado`."""
    negocio, canal = await _negocio_con_canal("gm-act-3", "10000000103")
    conversation, _ = await _abrir_conversacion(negocio, canal, "51900200004")

    await mem.guardar_mensaje("51900200004", "user", "Mensaje 1", negocio_id=negocio["id"])
    await mem.guardar_mensaje("51900200004", "user", "Mensaje 2", negocio_id=negocio["id"])

    filas, _ = await mem.listar_conversaciones_activas(negocio_id=negocio["id"])
    fila = next(f for f in filas if f["id"] == conversation.id)
    assert fila["mensajes_pendientes"] == 2
