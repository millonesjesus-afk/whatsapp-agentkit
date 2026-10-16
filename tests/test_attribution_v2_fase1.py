# tests/test_attribution_v2_fase1.py — Attribution V2, Fase 1 (persistencia
# de evidencia de atribución). Cubre los Casos A-F del Human Decision Gate:
# Meta Ads resoluble, Meta Ads NO resoluble (nunca cae a "organico"),
# mensaje sin referral (no se inventa nada), referral parcial (no rompe),
# aislamiento multi-tenant, y first-touch. El Caso G (regresión) se cubre
# corriendo la suite completa del proyecto, no un test unitario aparte.

from agent import memory as mem
from agent import campanas


async def _preparar_conversacion(sufijo: str, telefono: str):
    """Arma el contexto mínimo real (Negocio + Canal + Lead + Conversation
    activa) en el mismo orden en que main.py lo resuelve para un mensaje
    entrante — así los tests ejercitan exactamente la misma precondición
    que registrar_attribution_event asume en producción."""
    negocio = await mem.crear_negocio(f"Negocio {sufijo}", f"negocio-{sufijo}")
    canal = await mem.crear_canal_whatsapp(
        f"Canal {sufijo}", f"pnid-{sufijo}", negocio_id=negocio["id"],
    )
    await mem.actualizar_lead(telefono, numero_whatsapp_id=canal["phone_number_id"], negocio_id=negocio["id"])
    conversation, _opportunity = await mem.resolver_conversation_activa(telefono, negocio["id"], canal["id"])
    return negocio, canal, conversation


REFERRAL_ANUNCIO = {
    "source_id": "120211122233",
    "headline": "Terma a gas desde S/419.90",
    "body": "Financiada y sin inicial",
}


# ---------------------------------------------------------------------------
# Caso A — Meta Ads resoluble
# ---------------------------------------------------------------------------

async def test_caso_a_meta_ads_resoluble_crea_evento_y_mantiene_campana_origen():
    negocio, _canal, _conv = await _preparar_conversacion("a", "51900000101")
    await mem.crear_campana_de_anuncio("SMS Terma a gas", REFERRAL_ANUNCIO["source_id"], negocio["id"])

    resultado = await campanas.detectar_y_asignar_campana(
        "51900000101", "Hola, quiero información", REFERRAL_ANUNCIO, negocio["id"],
    )
    assert resultado["nombre"] == "SMS Terma a gas"

    lead = await mem.obtener_lead("51900000101", negocio_id=negocio["id"])
    assert lead["campana_origen"] == "SMS Terma a gas"  # comportamiento actual, sin cambios

    eventos = await mem.listar_attribution_events("51900000101", negocio_id=negocio["id"])
    assert len(eventos) == 1
    evento = eventos[0]
    assert evento["tipo_origen"] == "meta_ads"
    assert evento["source_id"] == "120211122233"
    assert evento["headline"] == REFERRAL_ANUNCIO["headline"]
    assert evento["body"] == REFERRAL_ANUNCIO["body"]
    assert evento["campana_nombre"] == "SMS Terma a gas"
    assert evento["referral_raw"] == REFERRAL_ANUNCIO
    assert evento["first_touch"] is True


# ---------------------------------------------------------------------------
# Caso B — Meta Ads NO resoluble (nunca debe quedar como orgánico)
# ---------------------------------------------------------------------------

async def test_caso_b_meta_ads_no_resoluble_nunca_queda_como_organico():
    negocio, _canal, _conv = await _preparar_conversacion("b", "51900000102")
    # Ninguna campaña configurada que coincida con este referral.
    await mem.crear_campana(
        nombre="Otra campaña", tipo_deteccion="referral_meta", patron="secadora rinnai",
        negocio_id=negocio["id"],
    )

    resultado = await campanas.detectar_y_asignar_campana(
        "51900000102", "Hola", REFERRAL_ANUNCIO, negocio["id"],
    )
    assert resultado is None  # comportamiento actual sin cambios

    lead = await mem.obtener_lead("51900000102", negocio_id=negocio["id"])
    assert not lead.get("campana_origen")  # sigue vacío, como hoy

    eventos = await mem.listar_attribution_events("51900000102", negocio_id=negocio["id"])
    assert len(eventos) == 1
    assert eventos[0]["tipo_origen"] == "meta_ads_no_resuelto"
    assert eventos[0]["tipo_origen"] != "organico"
    assert eventos[0]["source_id"] == "120211122233"  # la evidencia no se perdió


async def test_caso_b_meta_ads_no_resoluble_sin_ninguna_campana_configurada():
    """Mismo caso B, pero cuando el negocio todavía no tiene NINGUNA campaña
    en la tabla — la rama de retorno anticipado también debe persistir la
    evidencia, no solo la rama con campañas."""
    negocio, _canal, _conv = await _preparar_conversacion("b2", "51900000103")

    resultado = await campanas.detectar_y_asignar_campana(
        "51900000103", "Hola", REFERRAL_ANUNCIO, negocio["id"],
    )
    assert resultado is None

    eventos = await mem.listar_attribution_events("51900000103", negocio_id=negocio["id"])
    assert len(eventos) == 1
    assert eventos[0]["tipo_origen"] == "meta_ads_no_resuelto"


# ---------------------------------------------------------------------------
# Caso B.2 — Referral sin resolver + texto_saludo SÍ matchea (aprobación
# Opción B): un solo AttributionEvent (meta_ads_no_resuelto, sin
# campana_nombre), pero Lead.campana_origen se sigue asignando exactamente
# igual que si Attribution V2 no existiera — la evidencia de Meta no se
# mezcla con la interpretación de texto.
# ---------------------------------------------------------------------------

async def test_caso_b2_referral_sin_resolver_y_texto_saludo_matchea_un_solo_evento():
    negocio, _canal, _conv = await _preparar_conversacion("b3", "51900000110")
    # Ninguna campaña "referral_meta" coincide con este referral, pero SÍ hay
    # una campaña "texto_saludo" que coincide con el texto del mensaje.
    await mem.crear_campana(
        nombre="Otra campaña Ads", tipo_deteccion="referral_meta", patron="secadora rinnai",
        negocio_id=negocio["id"],
    )
    await mem.crear_campana(
        nombre="Catálogo web", tipo_deteccion="texto_saludo", patron="vi el catálogo web",
        negocio_id=negocio["id"],
    )

    resultado = await campanas.detectar_y_asignar_campana(
        "51900000110", "Hola, vi el catálogo web y quisiera info", REFERRAL_ANUNCIO, negocio["id"],
    )
    assert resultado["nombre"] == "Catálogo web"  # texto_saludo sigue funcionando igual que siempre

    lead = await mem.obtener_lead("51900000110", negocio_id=negocio["id"])
    assert lead["campana_origen"] == "Catálogo web"  # comportamiento actual, sin cambios

    eventos = await mem.listar_attribution_events("51900000110", negocio_id=negocio["id"])
    assert len(eventos) == 1  # nunca 2 — evidencia y lógica comercial no se mezclan
    assert eventos[0]["tipo_origen"] == "meta_ads_no_resuelto"
    assert eventos[0]["campana_nombre"] is None  # sin nombre de campaña textual en este evento
    assert eventos[0]["source_id"] == REFERRAL_ANUNCIO["source_id"]  # la evidencia cruda no se pierde


# ---------------------------------------------------------------------------
# Caso C — Sin referral: no se inventa atribución
# ---------------------------------------------------------------------------

async def test_caso_c_mensaje_sin_referral_no_crea_ningun_evento():
    negocio, _canal, _conv = await _preparar_conversacion("c", "51900000104")

    resultado = await campanas.detectar_y_asignar_campana(
        "51900000104", "Hola, un saludo cualquiera", None, negocio["id"],
    )
    assert resultado is None

    eventos = await mem.listar_attribution_events("51900000104", negocio_id=negocio["id"])
    assert eventos == []  # comportamiento mínimo: nada que registrar, nada se inventa


# ---------------------------------------------------------------------------
# Caso D — Referral parcial: no debe romper el procesamiento
# ---------------------------------------------------------------------------

async def test_caso_d_referral_parcial_no_rompe_y_persiste_lo_disponible():
    negocio, _canal, _conv = await _preparar_conversacion("d", "51900000105")
    referral_parcial = {"source_id": "999888777"}  # sin headline/body/ctwa_clid

    resultado = await campanas.detectar_y_asignar_campana(
        "51900000105", "Hola", referral_parcial, negocio["id"],
    )
    assert resultado is None  # sin campañas configuradas, no hay match posible

    eventos = await mem.listar_attribution_events("51900000105", negocio_id=negocio["id"])
    assert len(eventos) == 1
    evento = eventos[0]
    assert evento["source_id"] == "999888777"
    assert evento["headline"] is None
    assert evento["body"] is None
    assert evento["ctwa_clid"] is None


# ---------------------------------------------------------------------------
# Caso E — Multi-tenant: un evento nunca queda asociado a otro negocio
# ---------------------------------------------------------------------------

async def test_caso_e_attribution_event_no_cruza_entre_negocios():
    negocio_a, _canal_a, _conv_a = await _preparar_conversacion("e-a", "51900000106")
    negocio_b, canal_b, _conv_b = await _preparar_conversacion("e-b", "51900000107")

    await campanas.detectar_y_asignar_campana("51900000106", "Hola", REFERRAL_ANUNCIO, negocio_a["id"])
    await campanas.detectar_y_asignar_campana("51900000107", "Hola", REFERRAL_ANUNCIO, negocio_b["id"])

    eventos_a = await mem.listar_attribution_events("51900000106", negocio_id=negocio_a["id"])
    eventos_b = await mem.listar_attribution_events("51900000107", negocio_id=negocio_b["id"])
    assert all(e["negocio_id"] == negocio_a["id"] for e in eventos_a)
    assert all(e["negocio_id"] == negocio_b["id"] for e in eventos_b)

    # Candado explícito: consultar el teléfono del negocio B filtrando por
    # negocio A no debe devolver nada (aislamiento real, no solo por defecto).
    cruzado = await mem.listar_attribution_events("51900000107", negocio_id=negocio_a["id"])
    assert cruzado == []


# ---------------------------------------------------------------------------
# Caso F — First touch: solo el primer evento del lead lo marca
# ---------------------------------------------------------------------------

async def test_caso_f_solo_el_primer_evento_queda_marcado_first_touch():
    negocio, _canal, _conv = await _preparar_conversacion("f", "51900000108")

    primero = await mem.registrar_attribution_event(
        "51900000108", "meta_ads_no_resuelto", referral=REFERRAL_ANUNCIO,
    )
    segundo = await mem.registrar_attribution_event(
        "51900000108", "meta_ads_no_resuelto", referral={"source_id": "otro-anuncio"},
    )

    assert primero["first_touch"] is True
    assert segundo["first_touch"] is False

    eventos = await mem.listar_attribution_events("51900000108", negocio_id=negocio["id"])
    assert len(eventos) == 2
    marcados_first_touch = [e for e in eventos if e["first_touch"]]
    assert len(marcados_first_touch) == 1
    assert marcados_first_touch[0]["id"] == primero["id"]


# ---------------------------------------------------------------------------
# wa_link (texto_saludo) sigue funcionando y también genera evidencia
# ---------------------------------------------------------------------------

async def test_texto_saludo_wa_link_tambien_genera_attribution_event():
    negocio, _canal, _conv = await _preparar_conversacion("g", "51900000109")
    await mem.crear_campana(
        nombre="Catálogo web", tipo_deteccion="texto_saludo", patron="vi el catálogo web",
        negocio_id=negocio["id"],
    )

    resultado = await campanas.detectar_y_asignar_campana(
        "51900000109", "Hola, vi el catálogo web y quisiera info", None, negocio["id"],
    )
    assert resultado["nombre"] == "Catálogo web"

    eventos = await mem.listar_attribution_events("51900000109", negocio_id=negocio["id"])
    assert len(eventos) == 1
    assert eventos[0]["tipo_origen"] == "wa_link"
    assert eventos[0]["campana_nombre"] == "Catálogo web"
