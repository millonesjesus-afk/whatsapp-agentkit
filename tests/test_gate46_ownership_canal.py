# tests/test_gate46_ownership_canal.py — Gate 4.6, gap interno identificado
# en la auditoría: `_verificar_ownership_canal` existe y su lógica ya está
# cubierta indirectamente (test_ownership_campana_y_canal_no_cruzan_negocios,
# test_gate53_contact_conversation_opportunity.py:482), pero ningún test
# ejercita las 3 rutas HTTP de mutación puntual (editar/toggle/modo) para
# confirmar que el candado realmente bloquea un intento cross-tenant —
# mismo patrón que ya existe para Campañas.

from fastapi import HTTPException

from agent import dashboard, memory as mem


async def _dos_negocios_con_canal():
    negocio_a = await mem.crear_negocio("Negocio Canal A", "g46cana")
    negocio_b = await mem.crear_negocio("Negocio Canal B", "g46canb")
    canal_a = await mem.crear_canal_whatsapp(
        nombre="Canal A", phone_number_id="20000000001", access_token="token-a",
        negocio_id=negocio_a["id"],
    )
    canal_b = await mem.crear_canal_whatsapp(
        nombre="Canal B", phone_number_id="20000000002", access_token="token-b",
        modo="pruebas", negocio_id=negocio_b["id"],
    )
    return negocio_a, negocio_b, canal_a, canal_b


# ---------------------------------------------------------------------------
# Editar — cross-tenant bloqueado, propio funciona
# ---------------------------------------------------------------------------

async def test_editar_canal_de_otro_negocio_da_404():
    negocio_a, negocio_b, canal_a, canal_b = await _dos_negocios_con_canal()
    usuario_a = {"negocio_id": negocio_a["id"]}

    try:
        await dashboard.editar_canal_whatsapp_ruta(
            canal_b["id"], nombre="Secuestrado", access_token="robado",
            app_secret="", page_access_token="", usuario=usuario_a, _csrf=None,
        )
        assert False, "debía lanzar HTTPException"
    except HTTPException as e:
        assert e.status_code == 404

    intacto = await mem.obtener_canal_whatsapp(canal_b["id"])
    assert intacto["nombre"] == "Canal B"
    assert intacto["access_token"] == "token-b"


async def test_editar_canal_propio_si_funciona():
    negocio_a, negocio_b, canal_a, canal_b = await _dos_negocios_con_canal()
    usuario_a = {"negocio_id": negocio_a["id"]}

    await dashboard.editar_canal_whatsapp_ruta(
        canal_a["id"], nombre="Canal A Renombrado", access_token="token-a-nuevo",
        app_secret="", page_access_token="", usuario=usuario_a, _csrf=None,
    )
    actualizado = await mem.obtener_canal_whatsapp(canal_a["id"])
    assert actualizado["nombre"] == "Canal A Renombrado"
    assert actualizado["access_token"] == "token-a-nuevo"


# ---------------------------------------------------------------------------
# Toggle (activo/inactivo) — cross-tenant bloqueado, propio funciona
# ---------------------------------------------------------------------------

async def test_toggle_canal_de_otro_negocio_da_404():
    negocio_a, negocio_b, canal_a, canal_b = await _dos_negocios_con_canal()
    usuario_a = {"negocio_id": negocio_a["id"]}

    try:
        await dashboard.toggle_canal_whatsapp(canal_b["id"], usuario=usuario_a, _csrf=None)
        assert False, "debía lanzar HTTPException"
    except HTTPException as e:
        assert e.status_code == 404

    intacto = await mem.obtener_canal_whatsapp(canal_b["id"])
    assert intacto["activo"] is True  # nunca se tocó


async def test_toggle_canal_propio_si_funciona():
    negocio_a, negocio_b, canal_a, canal_b = await _dos_negocios_con_canal()
    usuario_a = {"negocio_id": negocio_a["id"]}

    await dashboard.toggle_canal_whatsapp(canal_a["id"], usuario=usuario_a, _csrf=None)
    actualizado = await mem.obtener_canal_whatsapp(canal_a["id"])
    assert actualizado["activo"] is False


# ---------------------------------------------------------------------------
# Modo (producción/pruebas) — cross-tenant bloqueado, propio funciona
# ---------------------------------------------------------------------------

async def test_modo_canal_de_otro_negocio_da_404():
    negocio_a, negocio_b, canal_a, canal_b = await _dos_negocios_con_canal()
    usuario_a = {"negocio_id": negocio_a["id"]}

    try:
        await dashboard.toggle_modo_canal_whatsapp(canal_b["id"], usuario=usuario_a, _csrf=None)
        assert False, "debía lanzar HTTPException"
    except HTTPException as e:
        assert e.status_code == 404

    intacto = await mem.obtener_canal_whatsapp(canal_b["id"])
    assert intacto["modo"] == "pruebas"  # nunca se tocó


async def test_modo_canal_propio_si_funciona():
    negocio_a, negocio_b, canal_a, canal_b = await _dos_negocios_con_canal()
    usuario_a = {"negocio_id": negocio_a["id"]}

    await dashboard.toggle_modo_canal_whatsapp(canal_a["id"], usuario=usuario_a, _csrf=None)
    actualizado = await mem.obtener_canal_whatsapp(canal_a["id"])
    assert actualizado["modo"] == "pruebas"  # canal_a nació en "produccion" (default)


# ---------------------------------------------------------------------------
# Candado también bloquea un canal que directamente no existe (no solo cross-tenant)
# ---------------------------------------------------------------------------

async def test_editar_canal_inexistente_da_404():
    negocio_a, _, _, _ = await _dos_negocios_con_canal()
    usuario_a = {"negocio_id": negocio_a["id"]}
    try:
        await dashboard.editar_canal_whatsapp_ruta(
            999999, nombre="X", access_token="", app_secret="", page_access_token="",
            usuario=usuario_a, _csrf=None,
        )
        assert False, "debía lanzar HTTPException"
    except HTTPException as e:
        assert e.status_code == 404
