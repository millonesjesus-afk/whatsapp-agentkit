# tests/test_gate55_guardar_mensaje_scoped.py — Gate 5.5, hallazgo de
# integridad de escritura surgido durante la propia implementación de
# Realtime: guardar_mensaje() resolvía su negocio_id/conversation_id
# internamente vía el bridge global Lead.telefono (Gate 5.2, H1) — el mismo
# hallazgo de raíz que motivó Gate 5.4/5.5, ahora también cerrado en
# escritura, no solo en lectura/emisión. Datos sintéticos únicamente.

import pytest

from agent import memory as mem


async def _negocio_con_canal(codigo: str, telefono_canal: str):
    negocio = await mem.crear_negocio(f"Negocio {codigo}", codigo)
    canal = await mem.crear_canal_whatsapp(nombre=f"Canal {codigo}", phone_number_id=telefono_canal, negocio_id=negocio["id"])
    return negocio, canal


async def test_guardar_mensaje_ignora_negocio_id_erroneo_del_lead_global():
    """El caso adversarial exacto que motivó la corrección: un Lead (PK
    global por telefono) apunta a Negocio A porque fue el primero en
    escribirle a ese número — pero el MENSAJE actual llega por el Canal de
    Negocio B (mismo teléfono, Contact/Conversation propios de B). Antes de
    esta corrección, guardar_mensaje() habría resuelto negocio_id/
    conversation_id desde el Lead (→ A, incorrecto). Ahora el llamador pasa
    negocio_id=B explícito y la función nunca consulta a Lead — el mensaje
    queda correctamente en la Conversation de B."""
    negocio_a, canal_a = await _negocio_con_canal("gm-a", "50000000001")
    negocio_b, canal_b = await _negocio_con_canal("gm-b", "50000000002")
    telefono = "51900700001"

    # Lead global — "gana" Negocio A por ser el primero en existir para este
    # teléfono (comportamiento ya documentado de actualizar_lead: nunca
    # sobreescribe el negocio_id de un Lead ya existente).
    await mem.actualizar_lead(telefono, negocio_id=negocio_a["id"], nombre="Cliente A")

    # Contact + Conversation propios de Negocio B, para el MISMO teléfono —
    # el escenario real de Tenant 002.
    conversation_b, _ = await mem.resolver_conversation_activa(telefono, negocio_b["id"], canal_b["id"])

    # El mensaje llega por el Canal de B — el llamador (webhook) pasa
    # negocio_id=B, tal como main.py hace con canal["negocio_id"].
    mensaje = await mem.guardar_mensaje(telefono, "user", "Mensaje que llegó por el Canal de B", negocio_id=negocio_b["id"])

    assert mensaje["conversation_id"] == conversation_b.id
    async with mem.async_session() as session:
        fila = await session.get(mem.Mensaje, mensaje["id"])
        assert fila.negocio_id == negocio_b["id"]
        assert fila.negocio_id != negocio_a["id"]  # nunca el Negocio del Lead global


async def test_guardar_mensaje_sin_contact_previo_guarda_con_conversation_id_none():
    """Si todavía no existe Contact/Conversation PARA ESE Negocio (caso
    borde real: primer mensaje antes de que el webhook los cree), el
    mensaje se guarda igual con conversation_id=None — nunca falla, nunca
    inventa una Conversation en un contexto get-only."""
    negocio, _ = await _negocio_con_canal("gm-c", "50000000003")
    telefono = "51900700002"
    await mem.actualizar_lead(telefono, negocio_id=negocio["id"], nombre="Cliente")

    mensaje = await mem.guardar_mensaje(telefono, "user", "Primer contacto", negocio_id=negocio["id"])
    assert mensaje["conversation_id"] is None


async def test_guardar_mensaje_falla_cerrado_sin_negocio_id_nunca_adivina():
    """Fail-closed explícito — nunca cae a 'el único Lead', 'el primero',
    ni ningún otro fallback implícito."""
    with pytest.raises(ValueError, match="negocio_id"):
        await mem.guardar_mensaje("51900700003", "user", "sin contexto de Negocio", negocio_id=None)
