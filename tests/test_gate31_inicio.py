# tests/test_gate31_inicio.py — GATE 3.1 (Inicio, Nueva Experiencia):
# `GET /dashboard/inicio.json` + las funciones de datos estructurados
# (`_zona_accion_*_datos`, `_zona_indicadores_*_datos`) que lo alimentan.
#
# Estas funciones son DELIBERADAMENTE independientes de las que arman el
# HTML legacy (`_zona_accion_asesor`, `_zona_accion_admin`,
# `_zona_indicadores_asesor`, `_zona_indicadores_admin`) — mismo criterio
# de negocio, cero riesgo de regresión porque el legacy no se tocó. Este
# archivo también confirma eso con evidencia (no solo con "no lo edité").
#
# Datos sintéticos únicamente, reutiliza los helpers ya establecidos de
# test_gate53_contact_conversation_opportunity.py.

import json
from datetime import datetime, timedelta

from agent import dashboard, memory as mem


async def _negocio_con_canal(codigo: str, telefono_canal: str):
    negocio = await mem.crear_negocio(f"Negocio {codigo}", codigo)
    canal = await mem.crear_canal_whatsapp(
        nombre=f"Canal {codigo}", phone_number_id=telefono_canal, negocio_id=negocio["id"],
    )
    return negocio, canal


async def _lead_pausado(telefono: str, negocio_id: str, asesor: str, nombre: str, actualizado: datetime):
    await mem.actualizar_lead(telefono, nombre=nombre, negocio_id=negocio_id)
    async with mem.async_session() as session:
        lead = await session.get(mem.Lead, telefono)
        lead.asesor_asignado = asesor
        lead.pausado_manual = True
        lead.actualizado = actualizado
        await session.commit()


async def _lead_agendado(telefono: str, negocio_id: str, asesor: str | None, nombre: str, fecha: datetime):
    await mem.actualizar_lead(telefono, nombre=nombre, negocio_id=negocio_id)
    async with mem.async_session() as session:
        lead = await session.get(mem.Lead, telefono)
        lead.asesor_asignado = asesor
        lead.resultado = "agendado"
        lead.fecha_agendada = fecha
        await session.commit()


async def _lead_sin_asignar(telefono: str, negocio_id: str, nombre: str):
    await mem.actualizar_lead(telefono, nombre=nombre, negocio_id=negocio_id)
    async with mem.async_session() as session:
        lead = await session.get(mem.Lead, telefono)
        lead.paso_flujo = "derivado_asesor"
        lead.asesor_asignado = None
        await session.commit()


# ---------------------------------------------------------------------------
# _zona_accion_asesor_datos / _zona_accion_admin_datos
# ---------------------------------------------------------------------------

async def test_zona_accion_asesor_vacia_cuando_no_hay_nada():
    negocio, _ = await _negocio_con_canal("g31-a", "30100000001")
    usuario = {"username": "asesor1", "negocio_id": negocio["id"]}
    datos = {"leads_todos": []}
    resultado = await dashboard._zona_accion_asesor_datos(usuario, datos)
    assert resultado == {
        "vacio": True,
        "mensaje_vacio": "No tenés conversaciones que requieran tu atención ahora mismo.",
        "items": [],
    }


async def test_zona_accion_asesor_prioriza_esperando_antes_que_agendados_y_resuelve_conversation_id():
    negocio, canal = await _negocio_con_canal("g31-b", "30100000002")
    # Conversation real solo para el lead "esperando" — el agendado se queda
    # sin Conversation a propósito, para probar el fallback.
    conversation, _ = await mem.resolver_conversation_activa("51900400001", negocio["id"], canal["id"])
    await _lead_pausado(
        "51900400001", negocio["id"], "asesor1", "Cliente Esperando",
        datetime.utcnow() - timedelta(hours=2),
    )
    await _lead_agendado(
        "51900400002", negocio["id"], "asesor1", "Cliente Agendado",
        datetime.utcnow() + timedelta(days=1),
    )

    usuario = {"username": "asesor1", "negocio_id": negocio["id"]}
    datos = {"leads_todos": [
        await mem.obtener_lead("51900400001", negocio_id=negocio["id"]),
        await mem.obtener_lead("51900400002", negocio_id=negocio["id"]),
    ]}

    resultado = await dashboard._zona_accion_asesor_datos(usuario, datos)
    assert resultado["vacio"] is False
    assert [i["motivo"] for i in resultado["items"]] == ["Esperando tu respuesta", "Cita agendada — " + (
        datetime.utcnow() + timedelta(days=1)
    ).strftime("%d/%m %H:%M")]
    assert resultado["items"][0]["telefono"] == "51900400001"
    assert resultado["items"][0]["conversation_id"] == conversation.id
    assert resultado["items"][1]["telefono"] == "51900400002"
    assert resultado["items"][1]["conversation_id"] is None  # sin Conversation todavía — fallback correcto


async def test_zona_accion_admin_incluye_sin_asignar_y_esperando_con_nombre_de_asesor():
    negocio, _ = await _negocio_con_canal("g31-c", "30100000003")
    await _lead_sin_asignar("51900400003", negocio["id"], "Sin Asignar")
    await _lead_pausado(
        "51900400004", negocio["id"], "asesor2", "Cliente Pausado", datetime.utcnow(),
    )

    datos = {"leads_todos": [
        await mem.obtener_lead("51900400003", negocio_id=negocio["id"]),
        await mem.obtener_lead("51900400004", negocio_id=negocio["id"]),
    ]}
    resultado = await dashboard._zona_accion_admin_datos(datos, negocio["id"])
    motivos = [i["motivo"] for i in resultado["items"]]
    assert "Sin asesor asignado" in motivos
    assert "Esperando respuesta — asesor2" in motivos


async def test_zona_accion_admin_vacia_mensaje_distinto_del_asesor():
    negocio, _ = await _negocio_con_canal("g31-d", "30100000004")
    resultado = await dashboard._zona_accion_admin_datos({"leads_todos": []}, negocio["id"])
    assert resultado["vacio"] is True
    assert resultado["mensaje_vacio"] == "El equipo no tiene conversaciones que requieran tu intervención ahora mismo."


# ---------------------------------------------------------------------------
# _zona_indicadores_*_datos
# ---------------------------------------------------------------------------

def test_zona_indicadores_asesor_datos():
    datos = {"leads_derivados": [1, 2], "leads_con_gabi": [1], "leads_todos": [1, 2, 3]}
    resultado = dashboard._zona_indicadores_asesor_datos(datos)
    assert resultado == [
        {"valor": 3, "etiqueta": "Conversaciones activas"},
        {"valor": 3, "etiqueta": "Leads asignados"},
    ]


def test_zona_indicadores_admin_datos():
    datos = {"leads_derivados": [1], "leads_con_gabi": [], "leads_todos": [1, 2]}
    asesores = [{"disponible": True}, {"disponible": False}, {"disponible": True}]
    resultado = dashboard._zona_indicadores_admin_datos(datos, asesores)
    assert resultado == [
        {"valor": 1, "etiqueta": "Conversaciones activas"},
        {"valor": 2, "etiqueta": "Leads en curso"},
        {"valor": "2/3", "etiqueta": "Asesores disponibles"},
    ]


# ---------------------------------------------------------------------------
# resolver_conversation_ids_por_telefono — multi-tenant
# ---------------------------------------------------------------------------

async def test_resolver_conversation_ids_no_cruza_negocio():
    negocio_a, canal_a = await _negocio_con_canal("g31-e", "30100000005")
    negocio_b, canal_b = await _negocio_con_canal("g31-f", "30100000006")
    telefono_compartido = "51900400005"

    conv_a, _ = await mem.resolver_conversation_activa(telefono_compartido, negocio_a["id"], canal_a["id"])
    await mem.resolver_conversation_activa(telefono_compartido, negocio_b["id"], canal_b["id"])

    resultado = await mem.resolver_conversation_ids_por_telefono(negocio_a["id"], [telefono_compartido])
    assert resultado == {telefono_compartido: conv_a.id}


async def test_resolver_conversation_ids_telefono_sin_conversation_no_aparece():
    negocio, _ = await _negocio_con_canal("g31-g", "30100000007")
    resultado = await mem.resolver_conversation_ids_por_telefono(negocio["id"], ["51900400006"])
    assert resultado == {}


# ---------------------------------------------------------------------------
# Ruta HTTP — GET /dashboard/inicio.json
# ---------------------------------------------------------------------------

async def test_ruta_inicio_json_asesor_ve_solo_lo_propio():
    negocio, canal = await _negocio_con_canal("g31-h", "30100000008")
    await mem.crear_usuario("asesor1", "pw12345", "Asesor Uno", "asesor", negocio["id"])
    await mem.resolver_conversation_activa("51900400007", negocio["id"], canal["id"])
    await _lead_pausado("51900400007", negocio["id"], "asesor1", "Mío", datetime.utcnow())
    await _lead_pausado("51900400008", negocio["id"], "otro_asesor", "Ajeno", datetime.utcnow())

    usuario = await mem.obtener_usuario("asesor1", negocio_id=negocio["id"])
    respuesta = await dashboard.inicio_json(usuario=usuario)
    cuerpo = json.loads(respuesta.body)

    assert cuerpo["vision_total"] is False
    telefonos = [i["telefono"] for i in cuerpo["zona_accion"]["items"]]
    assert "51900400007" in telefonos
    assert "51900400008" not in telefonos
    assert cuerpo["zona_indicadores"][1]["etiqueta"] == "Leads asignados"


async def test_ruta_inicio_json_admin_ve_alcance_global():
    negocio, canal = await _negocio_con_canal("g31-i", "30100000009")
    await mem.crear_usuario("admin1", "pw12345", "Admin", "admin", negocio["id"])
    await mem.crear_usuario("asesor_x", "pw12345", "Asesor X", "asesor", negocio["id"])
    await mem.resolver_conversation_activa("51900400009", negocio["id"], canal["id"])
    await _lead_pausado("51900400009", negocio["id"], "asesor_x", "De Otro Asesor", datetime.utcnow())

    usuario = await mem.obtener_usuario("admin1", negocio_id=negocio["id"])
    respuesta = await dashboard.inicio_json(usuario=usuario)
    cuerpo = json.loads(respuesta.body)

    assert cuerpo["vision_total"] is True
    telefonos = [i["telefono"] for i in cuerpo["zona_accion"]["items"]]
    assert "51900400009" in telefonos  # admin ve leads de cualquier asesor
    assert any(e["etiqueta"] == "Asesores disponibles" for e in cuerpo["zona_indicadores"])


# ---------------------------------------------------------------------------
# Regresión — el HTML legacy sigue funcionando exactamente igual (no se tocó)
# ---------------------------------------------------------------------------

async def test_legacy_zona_accion_asesor_sigue_generando_html_equivalente():
    negocio, canal = await _negocio_con_canal("g31-j", "30100000010")
    await mem.resolver_conversation_activa("51900400010", negocio["id"], canal["id"])
    await _lead_pausado("51900400010", negocio["id"], "asesor1", "Cliente Legacy", datetime.utcnow())

    usuario = {"username": "asesor1", "negocio_id": negocio["id"]}
    datos = {"leads_todos": [await mem.obtener_lead("51900400010", negocio_id=negocio["id"])]}

    html_legacy = await dashboard._zona_accion_asesor(usuario, datos)
    datos_nuevos = await dashboard._zona_accion_asesor_datos(usuario, datos)

    assert "Cliente Legacy" in html_legacy
    assert "Esperando tu respuesta" in html_legacy
    assert datos_nuevos["items"][0]["nombre"] == "Cliente Legacy"
    assert datos_nuevos["items"][0]["motivo"] == "Esperando tu respuesta"


async def test_pipeline_conversation_id_sigue_correcto_tras_extraer_el_helper():
    """Regresión del refactor en memory.py: listar_leads_pipeline() delega
    ahora en _conversation_ids_por_telefono() — confirma que el resultado
    sigue siendo el mismo de siempre (Gate 5.3 §8)."""
    negocio, canal = await _negocio_con_canal("g31-k", "30100000011")
    conversation, _ = await mem.resolver_conversation_activa("51900400011", negocio["id"], canal["id"])
    await mem.actualizar_lead("51900400011", nombre="Pipeline", negocio_id=negocio["id"])

    leads, total = await mem.listar_leads_pipeline(negocio_id=negocio["id"])
    fila = next(l for l in leads if l["telefono"] == "51900400011")
    assert fila["conversation_id"] == conversation.id
    assert total >= 1
