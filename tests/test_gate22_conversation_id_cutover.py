# tests/test_gate22_conversation_id_cutover.py — GATE 2.2 (Conversation ID
# Cutover): `obtener_historial_de_conversation()` + `GET
# /dashboard/conversation/{id}/mensajes.json` — la Nueva Experiencia lee el
# historial por `conversation_id`, nunca por `telefono`, así que dos
# Conversation sucesivas del mismo Contact (DR-4, Gate 5.3) no mezclan su
# historial. `obtener_historial(telefono)` y `/lead/{telefono}/mensajes.json`
# (panel legacy) NO se tocan — se verifica explícitamente que siguen igual.
#
# Datos sintéticos únicamente, mismo criterio que
# test_gate53_contact_conversation_opportunity.py (reutiliza sus helpers).

import pytest
from fastapi import HTTPException

from agent import memory as mem, dashboard


async def _negocio_con_canal(codigo: str, telefono_canal: str):
    negocio = await mem.crear_negocio(f"Negocio {codigo}", codigo)
    canal = await mem.crear_canal_whatsapp(
        nombre=f"Canal {codigo}", phone_number_id=telefono_canal, negocio_id=negocio["id"],
    )
    return negocio, canal


async def _abrir_conversacion(negocio: dict, canal: dict, telefono: str):
    return await mem.resolver_conversation_activa(telefono, negocio["id"], canal["id"], unidad_id=canal.get("unidad_id"))


async def _cerrar_no_venta_y_asignar(conversation_id: str, opportunity_id: str, asesor: str = "asesor1"):
    """Fuerza la condición exacta de DR-4 (asignada/pausada + Opportunity
    cerrada != vendido) escribiendo directo el modelo — mismo patrón que
    test_dr4_no_venta_abre_conversation_nueva_y_preserva_la_anterior en
    test_gate53_contact_conversation_opportunity.py."""
    async with mem.async_session() as session:
        c = await session.get(mem.Conversation, conversation_id)
        c.asesor_asignado_id = asesor
        o = await session.get(mem.Opportunity, opportunity_id)
        o.resultado = "no_interesado"
        await session.commit()


# ---------------------------------------------------------------------------
# Caso crítico obligatorio (Sección 5 del Gate)
# ---------------------------------------------------------------------------

async def test_historial_no_mezcla_conversation_1_y_2_del_mismo_contact():
    negocio, canal = await _negocio_con_canal("g22-a", "20000000001")
    telefono = "51900200001"

    conv1, opp1 = await _abrir_conversacion(negocio, canal, telefono)
    a1 = await mem.guardar_mensaje(telefono, "user", "A1", negocio_id=negocio["id"])
    a2 = await mem.guardar_mensaje(telefono, "assistant", "A2", negocio_id=negocio["id"])
    assert a1["conversation_id"] == conv1.id
    assert a2["conversation_id"] == conv1.id

    await _cerrar_no_venta_y_asignar(conv1.id, opp1.id)
    conv2, opp2 = await _abrir_conversacion(negocio, canal, telefono)
    assert conv2.id != conv1.id  # DR-4 confirmado: se abrió una nueva

    b1 = await mem.guardar_mensaje(telefono, "user", "B1", negocio_id=negocio["id"])
    b2 = await mem.guardar_mensaje(telefono, "assistant", "B2", negocio_id=negocio["id"])
    assert b1["conversation_id"] == conv2.id
    assert b2["conversation_id"] == conv2.id

    historial_1 = await mem.obtener_historial_de_conversation(conv1.id, negocio["id"])
    historial_2 = await mem.obtener_historial_de_conversation(conv2.id, negocio["id"])

    assert [m["content"] for m in historial_1] == ["A1", "A2"]
    assert [m["content"] for m in historial_2] == ["B1", "B2"]
    # La aserción central del Gate: nunca los 4 mensajes juntos en ningún historial.
    assert "B1" not in [m["content"] for m in historial_1]
    assert "A1" not in [m["content"] for m in historial_2]


async def test_conversation_nueva_sin_historial_previo():
    negocio, canal = await _negocio_con_canal("g22-b", "20000000002")
    conv, _ = await _abrir_conversacion(negocio, canal, "51900200002")
    assert await mem.obtener_historial_de_conversation(conv.id, negocio["id"]) == []


async def test_dos_conversations_mismo_contact_listadas_completas():
    """Complementa el caso crítico: `listar_conversaciones_de_contact` (ya
    existente, sin tocar) sigue devolviendo ambas — la Sección 5 no le pide
    a este Gate ocultar Conversation 1, solo no mezclar sus mensajes."""
    negocio, canal = await _negocio_con_canal("g22-c", "20000000003")
    telefono = "51900200003"
    conv1, opp1 = await _abrir_conversacion(negocio, canal, telefono)
    await _cerrar_no_venta_y_asignar(conv1.id, opp1.id)
    conv2, _ = await _abrir_conversacion(negocio, canal, telefono)

    conversaciones = await mem.listar_conversaciones_de_contact(conv1.contact_id, negocio["id"])
    ids = {c["id"] for c in conversaciones}
    assert {conv1.id, conv2.id} <= ids


# ---------------------------------------------------------------------------
# Multi-tenant (Sección 6 del Gate)
# ---------------------------------------------------------------------------

async def test_multi_tenant_mismo_telefono_dos_negocios_no_cruza_historial():
    negocio_a, canal_a = await _negocio_con_canal("g22-d", "20000000004")
    negocio_b, canal_b = await _negocio_con_canal("g22-e", "20000000005")
    telefono_compartido = "51900200004"

    conv_a, _ = await _abrir_conversacion(negocio_a, canal_a, telefono_compartido)
    await mem.guardar_mensaje(telefono_compartido, "user", "Hola A", negocio_id=negocio_a["id"])

    conv_b, _ = await _abrir_conversacion(negocio_b, canal_b, telefono_compartido)
    await mem.guardar_mensaje(telefono_compartido, "user", "Hola B", negocio_id=negocio_b["id"])

    historial_a = await mem.obtener_historial_de_conversation(conv_a.id, negocio_a["id"])
    historial_b = await mem.obtener_historial_de_conversation(conv_b.id, negocio_b["id"])
    assert [m["content"] for m in historial_a] == ["Hola A"]
    assert [m["content"] for m in historial_b] == ["Hola B"]

    # Candado doble: pedir la Conversation de A con el negocio_id de B no debe traer nada.
    cruzado = await mem.obtener_historial_de_conversation(conv_a.id, negocio_b["id"])
    assert cruzado == []


# ---------------------------------------------------------------------------
# Legacy sin regresión (Sección 7, punto 10 / Sección 9)
# ---------------------------------------------------------------------------

async def test_legacy_obtener_historial_sigue_mezclando_sin_cambios():
    """`obtener_historial(telefono)` (panel legacy) NO se toca en este Gate
    — sigue devolviendo el historial de TODAS las Conversation sucesivas
    mezclado, tal como lo hacía antes. Este test congela ese comportamiento
    a propósito (no es el bug que se corrige acá, es el contrato legacy)."""
    negocio, canal = await _negocio_con_canal("g22-f", "20000000006")
    telefono = "51900200005"
    conv1, opp1 = await _abrir_conversacion(negocio, canal, telefono)
    await mem.guardar_mensaje(telefono, "user", "A1", negocio_id=negocio["id"])
    await _cerrar_no_venta_y_asignar(conv1.id, opp1.id)
    await _abrir_conversacion(negocio, canal, telefono)
    await mem.guardar_mensaje(telefono, "user", "B1", negocio_id=negocio["id"])

    historial_legacy = await mem.obtener_historial(telefono)
    assert [m["content"] for m in historial_legacy] == ["A1", "B1"]


# ---------------------------------------------------------------------------
# Ruta HTTP nueva — GET /dashboard/conversation/{id}/mensajes.json
# ---------------------------------------------------------------------------

async def test_ruta_conversation_mensajes_devuelve_historial_scoped():
    negocio, canal = await _negocio_con_canal("g22-g", "20000000007")
    telefono = "51900200006"
    conv1, opp1 = await _abrir_conversacion(negocio, canal, telefono)
    await mem.guardar_mensaje(telefono, "user", "A1", negocio_id=negocio["id"])
    await _cerrar_no_venta_y_asignar(conv1.id, opp1.id)
    conv2, _ = await _abrir_conversacion(negocio, canal, telefono)
    await mem.guardar_mensaje(telefono, "user", "B1", negocio_id=negocio["id"])

    admin = {"username": "admin1", "rol": "admin", "negocio_id": negocio["id"]}
    respuesta_1 = await dashboard.conversation_mensajes_json(conv1.id, usuario=admin)
    respuesta_2 = await dashboard.conversation_mensajes_json(conv2.id, usuario=admin)

    import json
    assert [m["content"] for m in json.loads(respuesta_1.body)] == ["A1"]
    assert [m["content"] for m in json.loads(respuesta_2.body)] == ["B1"]


async def test_ruta_conversation_mensajes_404_cross_tenant():
    negocio_a, canal_a = await _negocio_con_canal("g22-h", "20000000008")
    negocio_b, _ = await _negocio_con_canal("g22-i", "20000000009")
    conv_a, _ = await _abrir_conversacion(negocio_a, canal_a, "51900200007")

    admin_b = {"username": "admin_b", "rol": "admin", "negocio_id": negocio_b["id"]}
    with pytest.raises(HTTPException) as exc:
        await dashboard.conversation_mensajes_json(conv_a.id, usuario=admin_b)
    assert exc.value.status_code == 404


async def test_ruta_conversation_mensajes_403_asesor_sin_acceso():
    negocio, canal = await _negocio_con_canal("g22-j", "20000000010")
    conv, _ = await _abrir_conversacion(negocio, canal, "51900200008")
    async with mem.async_session() as session:
        c = await session.get(mem.Conversation, conv.id)
        c.asesor_asignado_id = "asesor_dueno"
        await session.commit()

    asesor_ajeno = {"username": "otro_asesor", "rol": "asesor", "negocio_id": negocio["id"]}
    with pytest.raises(HTTPException) as exc:
        await dashboard.conversation_mensajes_json(conv.id, usuario=asesor_ajeno)
    assert exc.value.status_code == 403


async def test_ruta_conversation_mensajes_asesor_dueno_si_puede():
    negocio, canal = await _negocio_con_canal("g22-k", "20000000011")
    telefono = "51900200009"
    conv, _ = await _abrir_conversacion(negocio, canal, telefono)
    async with mem.async_session() as session:
        c = await session.get(mem.Conversation, conv.id)
        c.asesor_asignado_id = "asesor_dueno"
        await session.commit()
    await mem.guardar_mensaje(telefono, "user", "Hola", negocio_id=negocio["id"])

    asesor_dueno = {"username": "asesor_dueno", "rol": "asesor", "negocio_id": negocio["id"]}
    import json
    respuesta = await dashboard.conversation_mensajes_json(conv.id, usuario=asesor_dueno)
    assert [m["content"] for m in json.loads(respuesta.body)] == ["Hola"]
