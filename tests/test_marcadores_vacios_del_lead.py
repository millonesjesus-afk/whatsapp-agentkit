# tests/test_marcadores_vacios_del_lead.py — «(desconocido)» ya no se guarda como dato del cliente (2026-10-30, bloque C).
#
# Hallazgo de la auditoría del flujo guiado: la Bandeja mostraba «(desconocido)» como NOMBRE aunque el número existía (25 de 47
# conversaciones). Causa: el prompt de extracción usaba «(desconocido)» como marcador de lo que faltaba y el modelo lo devolvía tal cual.
# Ahora: el marcador no se escribe en el prompt, la respuesta se limpia, la escritura de Gabi lo rechaza y un script limpia lo ya guardado.

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from agent import brain, memory as mem
from scripts import limpiar_marcadores_vacios as limpiar


@pytest.mark.parametrize("texto", [
    "(desconocido)", "Desconocido", "desconocida", " (Desconocido) ", "null", "NULL", "None", "N/A", "sin dato", "(sin dato)", '"null"',
    "no especificado", "unknown", "-", "?", "ninguno",
])
def test_son_marcadores_vacios(texto):
    assert mem.es_marcador_vacio(texto) is True


@pytest.mark.parametrize("valor", [
    "Jorge Luis", "Rheem", "terma para 2 baños", "Ana desconocida de la Cruz", "", None, 5, ["desconocido"],
    "Nan", "Nil", "Na", "nan", "NIL",   # pueden ser nombres reales: nunca se tratan como marcador
])
def test_no_son_marcadores(valor):
    assert mem.es_marcador_vacio(valor) is False


def test_gabi_no_escribe_marcadores_pero_una_persona_si_puede():
    campos = {"nombre": "(desconocido)", "interes": "terma", "producto_marca": "null", "paso_flujo": "explorando"}
    assert mem._filtrar_campos(campos, ()) == {"interes": "terma", "paso_flujo": "explorando"}
    # una decisión humana se respeta tal cual (puede incluso borrar el campo con "")
    assert mem._filtrar_campos({"nombre": "(desconocido)"}, ("nombre",)) == {"nombre": "(desconocido)"}
    assert mem._filtrar_campos({"nombre": ""}, ("nombre",)) == {"nombre": None}


async def test_actualizar_lead_ignora_el_marcador_y_conserva_el_nombre_real():
    negocio = await mem.crear_negocio("Negocio mv-lead", "mv-lead")
    await mem.actualizar_lead("51900300001", negocio_id=negocio["id"], nombre="Marta", interes="secadora")
    await mem.actualizar_lead("51900300001", nombre="(desconocido)", interes="(desconocido)")
    lead = await mem.obtener_lead("51900300001", negocio_id=negocio["id"])
    assert lead["nombre"] == "Marta" and lead["interes"] == "secadora"


async def test_un_lead_nuevo_con_marcador_queda_sin_nombre():
    negocio = await mem.crear_negocio("Negocio mv-nuevo", "mv-nuevo")
    await mem.actualizar_lead("51900300002", negocio_id=negocio["id"], nombre="(desconocido)", interes="terma")
    lead = await mem.obtener_lead("51900300002", negocio_id=negocio["id"])
    assert not lead["nombre"] and lead["interes"] == "terma"


def _respuesta_del_modelo(datos: dict):
    uso = SimpleNamespace(input_tokens=10, output_tokens=10, cache_read_input_tokens=0, cache_creation_input_tokens=0)
    return SimpleNamespace(content=[SimpleNamespace(text=json.dumps(datos))], usage=uso)


async def test_la_extraccion_ya_no_manda_ni_acepta_desconocido():
    devuelto = {"nombre": "(desconocido)", "interes": "Desconocido", "producto_tipo": "terma", "producto_marca": "null",
                "producto_modalidad": None, "paso_flujo": "explorando"}
    with patch.object(brain.client.messages, "create", new=AsyncMock(return_value=_respuesta_del_modelo(devuelto))) as mock_create:
        datos = await brain.extraer_datos_lead("Hola, quiero una terma", "Claro", {"nombre": None, "interes": None})
    enviado = mock_create.await_args.kwargs["messages"][0]["content"]
    assert "nombre: null" in enviado and "(desconocido)" not in enviado.split("Actualiza estos datos")[0]
    assert "NUNCA escribas" in enviado
    assert datos["nombre"] is None and datos["interes"] is None and datos["producto_marca"] is None
    assert datos["producto_tipo"] == "terma" and datos["paso_flujo"] == "explorando"


async def test_la_extraccion_conserva_los_datos_reales():
    devuelto = {"nombre": "Jorge Luis", "interes": "secadora 22 kg", "producto_tipo": "secadora", "producto_marca": "Mabe",
                "producto_modalidad": "solo", "paso_flujo": "derivado_asesor"}
    with patch.object(brain.client.messages, "create", new=AsyncMock(return_value=_respuesta_del_modelo(devuelto))):
        datos = await brain.extraer_datos_lead("Jorge Luis", "Gracias", None)
    assert datos["nombre"] == "Jorge Luis" and datos["interes"] == "secadora 22 kg" and datos["producto_marca"] == "Mabe"


# ── Script de limpieza ───────────────────────────────────────────────────────

async def _sembrar_sucios():
    negocio = await mem.crear_negocio("Negocio mv-script", "mv-script")
    canal = await mem.crear_canal_whatsapp("Canal mv", "pnid-mv-script", negocio_id=negocio["id"])
    for telefono, nombre in (("51900300010", "(desconocido)"), ("51900300011", "Rosa")):
        await mem.actualizar_lead(telefono, numero_whatsapp_id=canal["phone_number_id"], negocio_id=negocio["id"])
        await mem.resolver_conversation_activa(telefono, negocio["id"], canal["id"])
    # Se escribe directo (como quedaron en producción antes del arreglo): la escritura normal ya lo rechaza.
    async with mem.async_session() as session:
        lead = await session.get(mem.Lead, "51900300010")
        lead.nombre, lead.interes, lead.producto_marca = "(desconocido)", "Desconocido", "null"
        lead2 = await session.get(mem.Lead, "51900300011")
        lead2.nombre, lead2.interes = "Rosa", "terma"
        await session.commit()
    return negocio


async def test_el_script_por_defecto_solo_cuenta_y_con_aplicar_limpia_sin_tocar_datos_reales():
    await _sembrar_sucios()
    contado = await limpiar.main([])
    assert contado["aplicado"] is False and contado["detalle"]["leads.nombre"] >= 1 and contado["detalle"]["leads.interes"] >= 1
    async with mem.async_session() as session:
        assert (await session.get(mem.Lead, "51900300010")).nombre == "(desconocido)"   # no cambió nada

    aplicado = await limpiar.main(["--aplicar"])
    assert aplicado["aplicado"] is True and aplicado["total"] >= 3
    async with mem.async_session() as session:
        sucio = await session.get(mem.Lead, "51900300010")
        real = await session.get(mem.Lead, "51900300011")
        assert (sucio.nombre, sucio.interes, sucio.producto_marca) == (None, None, None)
        assert (real.nombre, real.interes) == ("Rosa", "terma")
    # una segunda corrida ya no encuentra nada
    assert (await limpiar.main(["--aplicar"]))["total"] == 0


async def test_la_limpieza_no_mueve_la_fecha_actualizado_en_ninguna_tabla():
    """Revisión del bloque C: `actualizado` tiene onupdate y el Pipeline ordena por ella. Si el script usara setattr, los clientes limpiados
    subirían al tope con «hace instantes» sin que el cliente hiciera nada."""
    from datetime import datetime

    from sqlalchemy import select, update

    negocio = await _sembrar_sucios()
    antigua = datetime(2026, 7, 15, 9, 30, 0)
    async with mem.async_session() as session:
        lead = await session.get(mem.Lead, "51900300010")
        contacto = (await session.execute(select(mem.Contact).where(mem.Contact.telefono == "51900300010"))).scalars().first()
        oportunidad = (await session.execute(
            select(mem.Opportunity).join(mem.Conversation, mem.Opportunity.conversation_id == mem.Conversation.id)
            .where(mem.Conversation.contact_id == contacto.id)
        )).scalars().first()
        # Se escriben con UPDATE directo (así quedaron en producción) y con una fecha vieja fija.
        await session.execute(update(mem.Lead).where(mem.Lead.telefono == lead.telefono).values(actualizado=antigua))
        await session.execute(update(mem.Contact).where(mem.Contact.id == contacto.id).values(nombre="(desconocido)", actualizado=antigua))
        await session.execute(update(mem.Opportunity).where(mem.Opportunity.id == oportunidad.id).values(interes="Desconocido", actualizado=antigua))
        await session.commit()

    resultado = await limpiar.main(["--aplicar"])
    assert resultado["detalle"]["leads.nombre"] >= 1 and resultado["detalle"]["contacts.nombre"] >= 1 and resultado["detalle"]["opportunities.interes"] >= 1

    async with mem.async_session() as session:
        lead = await session.get(mem.Lead, "51900300010")
        contacto = await session.get(mem.Contact, contacto.id)
        oportunidad = await session.get(mem.Opportunity, oportunidad.id)
        assert (lead.nombre, contacto.nombre, oportunidad.interes) == (None, None, None)   # se limpió…
        assert lead.actualizado == antigua                                                  # …y ninguna fecha se movió
        assert contacto.actualizado == antigua
        assert oportunidad.actualizado == antigua
    # el cliente con nombre real no se tocó
    async with mem.async_session() as session:
        real = await session.get(mem.Lead, "51900300011")
        assert real.nombre == "Rosa"
    assert negocio["id"]
