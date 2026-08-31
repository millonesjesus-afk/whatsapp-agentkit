# tests/test_gate55_concurrencia_conversation.py — Gate 5.5, hallazgo de
# concurrencia del checkpoint de investigación: DR-4 ("un Contact nunca
# tiene dos Conversation activas simultáneas") estaba declarada pero no
# forzada por la base de datos. Prueba el candado real (índice único
# parcial `ix_conversation_una_activa_por_contact`) y el manejo de la
# colisión en `resolver_conversation_activa`. Datos sintéticos únicamente.

import asyncio

import pytest
from sqlalchemy.exc import IntegrityError

from agent import memory as mem


async def _negocio_con_canal(codigo: str, telefono_canal: str):
    negocio = await mem.crear_negocio(f"Negocio {codigo}", codigo)
    canal = await mem.crear_canal_whatsapp(
        nombre=f"Canal {codigo}", phone_number_id=telefono_canal, negocio_id=negocio["id"],
    )
    return negocio, canal


async def test_indice_unico_impide_dos_conversation_activas_por_contact():
    """Candado real a nivel de base de datos, sin pasar por la lógica de
    aplicación — inserta directamente dos filas 'activa' para el mismo
    Contact y confirma que la segunda es rechazada por el motor."""
    negocio, canal = await _negocio_con_canal("conc-a", "40000000101")
    async with mem.async_session() as session:
        contact = await mem.obtener_o_crear_contact(session, negocio["id"], "51900600001")
        await session.commit()

        conv_1 = mem.Conversation(
            negocio_id=negocio["id"], contact_id=contact.id, canal_id=canal["id"], estado="activa",
        )
        session.add(conv_1)
        await session.commit()

        conv_2 = mem.Conversation(
            negocio_id=negocio["id"], contact_id=contact.id, canal_id=canal["id"], estado="activa",
        )
        session.add(conv_2)
        with pytest.raises(IntegrityError):
            await session.flush()


async def test_resolver_conversation_activa_bajo_carrera_no_duplica():
    """Simula el escenario real del hallazgo: dos 'webhooks' concurrentes
    para el mismo Contact nuevo, ninguno viendo todavía la escritura del
    otro. Ambas llamadas deben completar sin excepción, devolver la MISMA
    Conversation (una gana, la otra relee), y la base debe terminar con
    exactamente una fila activa — nunca dos."""
    negocio, canal = await _negocio_con_canal("conc-b", "40000000102")
    telefono = "51900600002"

    resultados = await asyncio.gather(
        mem.resolver_conversation_activa(telefono, negocio["id"], canal["id"]),
        mem.resolver_conversation_activa(telefono, negocio["id"], canal["id"]),
    )

    (conversation_1, _), (conversation_2, _) = resultados
    assert conversation_1.id == conversation_2.id

    async with mem.async_session() as session:
        from sqlalchemy import select, func
        contact = await mem._obtener_contact(session, negocio["id"], telefono)
        total_activas = (await session.execute(
            select(func.count()).select_from(mem.Conversation).where(
                mem.Conversation.contact_id == contact.id, mem.Conversation.estado == "activa",
            )
        )).scalar_one()
        assert total_activas == 1
