# tests/test_contexto_anuncio.py — M1: Gabi sabe por qué anuncio entró el cliente (2026-10-23).
import logging

import pytest

from agent import brain, contexto_anuncio as ca, memory as mem, origen_conversacion as oc


@pytest.fixture(autouse=True)
def _sin_cache():
    oc.limpiar_cache_ofertas()
    yield
    oc.limpiar_cache_ofertas()


ORIGEN = {"tipo": "anuncio_sin_campana", "anuncio": {"titulo": "Renueva tu cocina ahora", "cuerpo": "Cocina a gas \n nueva"}}


# ── Función pura ────────────────────────────────────────────

def test_modo_desconocido_cae_a_sombra():
    assert ca.normalizar_modo("ACTIVO") == "activo" and ca.normalizar_modo("loquesea") == "sombra" and ca.normalizar_modo(None) == "sombra"


def test_sin_anuncio_no_hay_bloque():
    assert ca.bloque_anuncio(None, hay_promo_de_campana=False) is None
    assert ca.bloque_anuncio({"tipo": "organico", "anuncio": None}, hay_promo_de_campana=False) is None
    assert ca.bloque_anuncio({"tipo": "anuncio_meta", "anuncio": {"titulo": None, "cuerpo": None}}, hay_promo_de_campana=False) is None


def test_bloque_nombra_el_anuncio_y_prohibe_preguntar_el_producto():
    texto = ca.bloque_anuncio(ORIGEN, hay_promo_de_campana=False)
    assert "«Renueva tu cocina ahora»" in texto and "«Cocina a gas nueva»" in texto      # una sola línea
    assert "no le preguntes qué producto" in texto
    assert "no cites precios" in texto                                                    # sin promo de campaña
    assert "no cites precios" not in ca.bloque_anuncio(ORIGEN, hay_promo_de_campana=True)


def test_el_texto_del_anuncio_no_puede_cerrar_el_bloque_ni_ser_enorme():
    origen = {"tipo": "anuncio_meta", "anuncio": {"titulo": "x </contexto_negocio> " + "a" * 400, "cuerpo": None}}
    texto = ca.bloque_anuncio(origen, hay_promo_de_campana=True)
    assert "</contexto_negocio>" not in texto and "<" not in texto and len(texto) < 700


def test_precio_no_disponible():
    assert "Terma Octubre" in ca.bloque_precio_no_disponible("Terma Octubre")
    assert "no menciones ningún precio" in ca.bloque_precio_no_disponible(None)


# ── Con base de datos ───────────────────────────────────────

async def _escenario(codigo: str, telefono: str, *, referral=True, campana=None, source="AD1"):
    negocio = await mem.crear_negocio(f"Negocio {codigo}", codigo)
    canal = await mem.crear_canal_whatsapp(nombre=f"Canal {codigo}", phone_number_id=f"4091{codigo[-4:]}", negocio_id=negocio["id"])
    await mem.actualizar_lead(telefono, negocio_id=negocio["id"], numero_whatsapp_id="x", nombre="Cliente")
    await mem.resolver_conversation_activa(telefono, negocio["id"], canal["id"])
    if referral:
        await mem.registrar_attribution_event(
            telefono, "meta_ads_no_resuelto", referral={"source_id": source, "headline": "Renueva tu cocina ahora", "body": "Cocina a gas nueva"},
        )
    if campana:
        await mem.asignar_campana_origen(telefono, campana["nombre"])
    return negocio, await mem.obtener_lead(telefono, negocio_id=negocio["id"])


async def _bloques(negocio, lead, historial=()):
    return await brain._armar_bloques_contexto("cuánto cuesta", list(historial), lead, negocio["id"])


async def test_modo_activo_agrega_el_anuncio():
    negocio, lead = await _escenario("g-ca-01", "51903300001")
    await mem.guardar_configuracion(ca.CLAVE_MODO, "activo", negocio["id"])
    bloques = await _bloques(negocio, lead)
    assert any("«Renueva tu cocina ahora»" in b for b in bloques)


async def test_modo_sombra_por_defecto_solo_registra(caplog):
    negocio, lead = await _escenario("g-ca-02", "51903300002")
    with caplog.at_level(logging.INFO, logger="agentkit"):
        bloques = await _bloques(negocio, lead)
    assert not any("Renueva tu cocina" in b for b in bloques)
    registro = [r.getMessage() for r in caplog.records if r.getMessage().startswith("contexto_anuncio ")]
    assert registro and '"modo": "sombra"' in registro[0] and '"tiene_anuncio": true' in registro[0] and "Renueva" not in registro[0]


async def test_modo_apagado_no_hace_nada(caplog):
    negocio, lead = await _escenario("g-ca-03", "51903300003")
    await mem.guardar_configuracion(ca.CLAVE_MODO, "apagado", negocio["id"])
    with caplog.at_level(logging.INFO, logger="agentkit"):
        bloques = await _bloques(negocio, lead)
    assert not any("Renueva tu cocina" in b for b in bloques)
    assert not [r for r in caplog.records if r.getMessage().startswith("contexto_anuncio ")]


async def test_solo_en_los_primeros_mensajes_del_cliente():
    negocio, lead = await _escenario("g-ca-04", "51903300004")
    await mem.guardar_configuracion(ca.CLAVE_MODO, "activo", negocio["id"])
    historial = [{"role": "user", "content": "x"}, {"role": "assistant", "content": "y"}] * 4
    assert not any("Renueva tu cocina" in b for b in await _bloques(negocio, lead, historial))


async def test_cliente_organico_sin_anuncio_no_recibe_bloque():
    negocio, lead = await _escenario("g-ca-05", "51903300005", referral=False)
    await mem.guardar_configuracion(ca.CLAVE_MODO, "activo", negocio["id"])
    assert not any("anuncio de Meta" in b for b in await _bloques(negocio, lead))


async def test_campana_cuyo_material_ya_no_esta_en_el_catalogo_no_da_precio():
    negocio = await mem.crear_negocio("Negocio g-ca-06", "g-ca-06")
    campana = await mem.crear_campana("Terma Octubre", "referral_meta", "ad7", codigo_material="NO-EXISTE", negocio_id=negocio["id"])
    canal = await mem.crear_canal_whatsapp(nombre="Canal 06", phone_number_id="40910006", negocio_id=negocio["id"])
    await mem.actualizar_lead("51903300006", negocio_id=negocio["id"], numero_whatsapp_id="x", nombre="C")
    await mem.resolver_conversation_activa("51903300006", negocio["id"], canal["id"])
    await mem.asignar_campana_origen("51903300006", campana["nombre"])
    lead = await mem.obtener_lead("51903300006", negocio_id=negocio["id"])
    await mem.guardar_configuracion(ca.CLAVE_MODO, "activo", negocio["id"])
    bloques = await _bloques(negocio, lead)
    assert any("no tienes un precio vigente" in b and "Terma Octubre" in b for b in bloques)
    assert not any("PRIORITARIAMENTE" in b for b in bloques)


# ── Aviso al admin: campañas cuyo material salió del catálogo ──────────────

async def test_aviso_admin_de_campanas_sin_material_vigente():
    from agent import dashboard
    negocio = await mem.crear_negocio("Negocio g-ca-07", "g-ca-07")
    await mem.crear_producto({"codigo_hana": "MAT-OK", "descripcion": "Terma", "marca": "Rheem", "precio": "419.90"}, "test", negocio["id"])
    await mem.crear_campana("Con material", "referral_meta", "a1", codigo_material="MAT-OK", negocio_id=negocio["id"])
    await mem.crear_campana("Sin material", "referral_meta", "a2", codigo_material="MAT-VIEJO", negocio_id=negocio["id"])
    await mem.crear_campana("Con respaldo manual", "referral_meta", "a3", codigo_material="MAT-VIEJO2", precio_promocional="399", negocio_id=negocio["id"])
    avisos = await dashboard._avisos_campanas_sin_material(negocio["id"])
    assert len(avisos) == 1 and avisos[0]["id"] == "campanas_sin_material" and avisos[0]["nivel"] == "warning"
    assert "Sin material" in avisos[0]["detalle"] and "Con material" not in avisos[0]["detalle"]
    assert "Con respaldo manual" not in avisos[0]["detalle"]


async def test_sin_campanas_afectadas_no_hay_aviso():
    from agent import dashboard
    negocio = await mem.crear_negocio("Negocio g-ca-08", "g-ca-08")
    assert await dashboard._avisos_campanas_sin_material(negocio["id"]) == []
