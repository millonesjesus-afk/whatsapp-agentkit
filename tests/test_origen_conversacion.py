# tests/test_origen_conversacion.py — "De dónde vino y con qué oferta": el objeto `origen`
# que ve el asesor dentro del chat y en la lista de conversaciones (2026-10-14).
#
# Se reutiliza la evidencia y las reglas que ya existen (Attribution V2, campaña vigente de
# la conversación, precio en vivo del catálogo); aquí solo se prueba que se lea y se componga bien.

import json
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import event

from agent import dashboard, memory as mem, origen_conversacion as oc


@pytest.fixture(autouse=True)
def _sin_cache_de_ofertas():
    oc.limpiar_cache_ofertas()
    yield
    oc.limpiar_cache_ofertas()


async def _negocio(codigo: str):
    negocio = await mem.crear_negocio(f"Negocio {codigo}", codigo)
    canal = await mem.crear_canal_whatsapp(
        nombre=f"Canal {codigo}", phone_number_id=f"4090000{codigo[-2:]}", negocio_id=negocio["id"],
    )
    return negocio, canal


async def _conversacion(negocio, canal, telefono: str, *, asesor: str | None = None, origen_contacto: str | None = None) -> str:
    await mem.actualizar_lead(telefono, negocio_id=negocio["id"], numero_whatsapp_id="x", nombre=f"Cliente {telefono[-4:]}")
    conversation, _ = await mem.resolver_conversation_activa(
        telefono, negocio["id"], canal["id"], origen_contacto=origen_contacto,
    )
    if asesor:
        async with mem.async_session() as session:
            lead = await session.get(mem.Lead, telefono)
            lead.asesor_asignado = asesor
            fila = await session.get(mem.Conversation, conversation.id)
            fila.asesor_asignado_id = asesor
            await session.commit()
    return conversation.id


def _referral(source_id="AD1", headline="Terma a gas Rheem", body="Llévatela con instalación", url="https://www.facebook.com/ads/123"):
    return {"source_id": source_id, "headline": headline, "body": body, "source_url": url, "ctwa_clid": "SECRETO"}


async def _origen(negocio, conv_id: str) -> dict:
    return (await oc.origenes_de_conversaciones(negocio["id"], [conv_id]))[conv_id]


async def _producto(negocio, codigo="MAT-1", descripcion="Terma a gas 8 L", marca="Rheem", precio="419.90"):
    await mem.crear_producto(
        {"codigo_hana": codigo, "descripcion": descripcion, "marca": marca, "precio": precio}, "test", negocio["id"],
    )


# ── Los casos ───────────────────────────────────────────────────────────────

async def test_anuncio_con_campana_y_precio_en_vivo_del_catalogo():
    negocio, canal = await _negocio("g-ori-01")
    await _producto(negocio)
    campana = await mem.crear_campana(
        "Meta Terma Octubre", "referral_meta", "ad1", codigo_material="MAT-1", negocio_id=negocio["id"],
    )
    conv = await _conversacion(negocio, canal, "51902200001")
    await mem.registrar_attribution_event("51902200001", "meta_ads", referral=_referral(), campana_nombre=campana["nombre"])
    await mem.asignar_campana_origen("51902200001", campana["nombre"])

    origen = await _origen(negocio, conv)

    assert origen["tipo"] == "anuncio_meta"
    assert origen["campana"] == {"id": campana["id"], "nombre": "Meta Terma Octubre"}
    assert origen["anuncio"] == {
        "titulo": "Terma a gas Rheem", "cuerpo": "Llévatela con instalación",
        "url": "https://www.facebook.com/ads/123", "source_id": "AD1", "red": "facebook",
    }
    assert origen["oferta"]["producto"] == "Rheem Terma a gas 8 L"
    assert origen["oferta"]["precio_promocional"] == "S/ 419.90"
    assert origen["oferta"]["texto"] == "Rheem Terma a gas 8 L · S/ 419.90"
    assert origen["primer_contacto_en"].endswith("Z")
    assert "SECRETO" not in json.dumps(origen)


async def test_el_precio_sigue_al_catalogo_si_cambia():
    negocio, canal = await _negocio("g-ori-02")
    await _producto(negocio, precio="500")
    campana = await mem.crear_campana("Terma", "referral_meta", "ad1", codigo_material="MAT-1", negocio_id=negocio["id"])
    conv = await _conversacion(negocio, canal, "51902200002")
    await mem.asignar_campana_origen("51902200002", campana["nombre"])
    assert (await _origen(negocio, conv))["oferta"]["precio_promocional"] == "S/ 500"

    # La campaña se edita (precio manual distinto, sin código): la clave de caché cambia sola.
    async with mem.async_session() as session:
        fila = await session.get(mem.Campana, campana["id"])
        fila.codigo_material = None
        fila.producto_promocional = "Secadora Rinnai 10 Kg"
        fila.precio_promocional = "899"
        await session.commit()
    oferta = (await _origen(negocio, conv))["oferta"]
    assert oferta["texto"] == "Secadora Rinnai 10 Kg · S/ 899"


async def test_anuncio_sin_campana_conserva_la_evidencia_del_anuncio():
    negocio, canal = await _negocio("g-ori-03")
    conv = await _conversacion(negocio, canal, "51902200003")
    await mem.registrar_attribution_event("51902200003", "meta_ads_no_resuelto", referral=_referral("AD9", "Secadora"))

    origen = await _origen(negocio, conv)

    assert origen["tipo"] == "anuncio_sin_campana"
    assert origen["campana"] is None and origen["oferta"] is None
    assert origen["anuncio"]["titulo"] == "Secadora" and origen["anuncio"]["source_id"] == "AD9"


async def test_anuncio_asignado_a_mano_despues_pasa_a_anuncio_meta_con_la_campana_vigente():
    negocio, canal = await _negocio("g-ori-04")
    campana = await mem.crear_campana("Meta Secadoras", "referral_meta", "zzz", negocio_id=negocio["id"])
    conv = await _conversacion(negocio, canal, "51902200004")
    await mem.registrar_attribution_event("51902200004", "meta_ads_no_resuelto", referral=_referral("AD9"))
    assert (await _origen(negocio, conv))["tipo"] == "anuncio_sin_campana"

    await mem.asignar_anuncio_a_campana(negocio["id"], "AD9", campana["id"], autor="jesus")

    origen = await _origen(negocio, conv)
    assert origen["tipo"] == "anuncio_meta" and origen["campana"]["nombre"] == "Meta Secadoras"


async def test_wa_link_por_texto_saludo():
    negocio, canal = await _negocio("g-ori-05")
    await mem.crear_campana(
        "SMS Terma a gas", "texto_saludo", "terma a gas", producto_promocional="Terma a gas 8 L",
        precio_promocional="419.90", negocio_id=negocio["id"],
    )
    conv = await _conversacion(negocio, canal, "51902200005")
    from agent.campanas import detectar_y_asignar_campana
    await detectar_y_asignar_campana("51902200005", "Hola, quiero la terma a gas en promoción", None, negocio["id"])

    origen = await _origen(negocio, conv)

    assert origen["tipo"] == "enlace_wa"
    assert origen["campana"]["nombre"] == "SMS Terma a gas"
    assert origen["anuncio"] is None
    assert origen["oferta"]["texto"] == "Terma a gas 8 L · S/ 419.90"


async def test_organico_no_trae_campana_ni_anuncio_ni_oferta():
    negocio, canal = await _negocio("g-ori-06")
    conv = await _conversacion(negocio, canal, "51902200006")

    origen = await _origen(negocio, conv)

    assert origen["tipo"] == "organico"
    assert origen["campana"] is None and origen["anuncio"] is None and origen["oferta"] is None


async def test_formulario_de_meta():
    negocio, canal = await _negocio("g-ori-07")
    campana = await mem.crear_campana("Formulario Termas", "referral_meta", "form1", negocio_id=negocio["id"])
    conv = await _conversacion(negocio, canal, "51902200007", origen_contacto="formulario_meta")
    await mem.asignar_campana_origen("51902200007", campana["nombre"])

    origen = await _origen(negocio, conv)

    assert origen["tipo"] == "formulario_meta"
    assert origen["campana"]["nombre"] == "Formulario Termas" and origen["anuncio"] is None


@pytest.mark.parametrize("url", [
    "javascript:alert(1)", "data:text/html,<b>x</b>", "ftp://fb.me/x", "//fb.me/x", "/ads/1", "https://user:clave@fb.me/x",
    "https://fb.me/a b", "", None, 123, "https:///sin-host", "https://fb.me/" + "a" * 1100,
])
async def test_url_que_no_es_http_o_https_valida_se_descarta(url):
    assert oc.validar_url_anuncio(url) is None


def test_url_http_y_https_se_aceptan():
    assert oc.validar_url_anuncio(" https://www.instagram.com/p/abc/?x=1 ") == "https://www.instagram.com/p/abc/?x=1"
    assert oc.validar_url_anuncio("http://fb.me/x") == "http://fb.me/x"


async def test_un_anuncio_con_url_peligrosa_se_muestra_sin_enlace():
    negocio, canal = await _negocio("g-ori-08")
    conv = await _conversacion(negocio, canal, "51902200008")
    await mem.registrar_attribution_event(
        "51902200008", "meta_ads_no_resuelto", referral=_referral(url="javascript:alert(1)", body="x" * 500),
    )

    anuncio = (await _origen(negocio, conv))["anuncio"]

    assert anuncio["url"] is None and anuncio["titulo"] == "Terma a gas Rheem"
    assert len(anuncio["cuerpo"]) == 200 and anuncio["cuerpo"].endswith("…")


async def test_first_touch_con_varios_eventos_usa_el_primero():
    negocio, canal = await _negocio("g-ori-09")
    conv = await _conversacion(negocio, canal, "51902200009")
    await mem.registrar_attribution_event("51902200009", "meta_ads_no_resuelto", referral=_referral("AD-PRIMERO", "Primer anuncio"))
    await mem.registrar_attribution_event_adicional("51902200009", "meta_ads_no_resuelto", referral=_referral("AD-SEGUNDO", "Segundo anuncio"))

    anuncio = (await _origen(negocio, conv))["anuncio"]

    assert anuncio["source_id"] == "AD-PRIMERO" and anuncio["titulo"] == "Primer anuncio"


async def test_el_titulo_que_falta_se_completa_con_otro_evento_del_mismo_anuncio():
    negocio, canal = await _negocio("g-ori-10")
    conv = await _conversacion(negocio, canal, "51902200010")
    await mem.registrar_attribution_event("51902200010", "meta_ads_no_resuelto", referral={"source_id": "AD5"})
    await mem.registrar_attribution_event_adicional("51902200010", "meta_ads_no_resuelto", referral=_referral("AD5", "Título tardío"))

    anuncio = (await _origen(negocio, conv))["anuncio"]

    assert anuncio["source_id"] == "AD5" and anuncio["titulo"] == "Título tardío"


async def test_campana_comodin_migrada_respeta_la_regla_y_la_campana_vigente():
    """Convive con el trabajo de campañas: la campaña mostrada es la vigente de la conversación,
    aunque el evento original (append-only) guardara otro nombre."""
    negocio, canal = await _negocio("g-ori-11")
    comodin = await mem.crear_campana("Meta Terma", "referral_meta", "terma", negocio_id=negocio["id"])
    exacta = await mem.crear_campana("Meta Terma AD1", "referral_meta", "ad1", negocio_id=negocio["id"])
    conv = await _conversacion(negocio, canal, "51902200011")
    await mem.registrar_attribution_event("51902200011", "meta_ads", referral=_referral("AD1"), campana_nombre=comodin["nombre"])
    await mem.asignar_campana_origen("51902200011", comodin["nombre"])

    await mem.asignar_anuncio_a_campana(negocio["id"], "AD1", exacta["id"], autor="jesus")

    assert (await _origen(negocio, conv))["campana"]["nombre"] == "Meta Terma AD1"


async def test_conversacion_nueva_tras_cierre_usa_el_primer_evento_del_telefono():
    negocio, canal = await _negocio("g-ori-12")
    campana = await mem.crear_campana("Meta Terma", "referral_meta", "ad1", negocio_id=negocio["id"])
    conv1 = await _conversacion(negocio, canal, "51902200012")
    await mem.registrar_attribution_event("51902200012", "meta_ads", referral=_referral(), campana_nombre=campana["nombre"])
    await mem.asignar_campana_origen("51902200012", campana["nombre"])
    async with mem.async_session() as session:
        c = await session.get(mem.Conversation, conv1)
        c.estado = "cerrada"
        await session.commit()
    conv2, _ = await mem.resolver_conversation_activa("51902200012", negocio["id"], canal["id"])

    origen = await _origen(negocio, conv2.id)

    assert origen["anuncio"]["source_id"] == "AD1" and origen["campana"]["nombre"] == "Meta Terma"


# ── Rendimiento, aislamiento y permisos ─────────────────────────────────────

async def test_la_lista_no_hace_una_consulta_por_conversacion():
    negocio, canal = await _negocio("g-ori-13")
    await _producto(negocio)
    campana = await mem.crear_campana("Meta Terma", "referral_meta", "ad1", codigo_material="MAT-1", negocio_id=negocio["id"])

    async def contar(n: int, base: int) -> int:
        ids = []
        for i in range(n):
            tel = f"519{base + i:08d}"
            ids.append(await _conversacion(negocio, canal, tel))
            await mem.registrar_attribution_event(tel, "meta_ads", referral=_referral(), campana_nombre=campana["nombre"])
            await mem.asignar_campana_origen(tel, campana["nombre"])
        oc.limpiar_cache_ofertas()
        consultas = []

        def _cuenta(conn, cursor, statement, parameters, context, executemany):
            consultas.append(statement)

        event.listen(mem.engine.sync_engine, "before_cursor_execute", _cuenta)
        try:
            origenes = await oc.origenes_de_conversaciones(negocio["id"], ids)
        finally:
            event.remove(mem.engine.sync_engine, "before_cursor_execute", _cuenta)
        assert len(origenes) == n and all(o["tipo"] == "anuncio_meta" for o in origenes.values())
        return len(consultas)

    assert await contar(3, 61000) == await contar(25, 62000)


async def test_no_cruza_negocios():
    negocio_a, canal_a = await _negocio("g-ori-14")
    negocio_b, canal_b = await _negocio("g-ori-15")
    await mem.crear_campana("Campaña B", "referral_meta", "ad1", negocio_id=negocio_b["id"])
    conv_a = await _conversacion(negocio_a, canal_a, "51902200014")
    conv_b = await _conversacion(negocio_b, canal_b, "51902200015")
    await mem.registrar_attribution_event("51902200015", "meta_ads_no_resuelto", referral=_referral("ADB", "Anuncio de B"))

    # Pedir la conversación de B con el negocio A no devuelve nada ni mezcla evidencia.
    assert await oc.origenes_de_conversaciones(negocio_a["id"], [conv_b]) == {}
    assert await oc.origen_de_conversacion(negocio_a["id"], conv_b) is None
    assert (await _origen(negocio_a, conv_a))["anuncio"] is None
    assert (await _origen(negocio_b, conv_b))["anuncio"]["titulo"] == "Anuncio de B"


def _request(**query):
    return SimpleNamespace(query_params=query)


async def _bandeja(usuario: dict) -> dict:
    respuesta = await dashboard.bandeja_conversaciones(
        request=_request(), usuario=usuario, q="", asesor="", alcance="", resultado="", orden="actividad",
        dir="desc", pagina=1, por_pagina=dashboard.POR_PAGINA_PIPELINE,
    )
    return json.loads(respuesta.body)


async def test_la_bandeja_trae_origen_y_el_asesor_solo_ve_sus_conversaciones():
    negocio, canal = await _negocio("g-ori-16")
    campana = await mem.crear_campana("Meta Terma", "referral_meta", "ad1", negocio_id=negocio["id"])
    suya = await _conversacion(negocio, canal, "51902200016", asesor="asesor1")
    ajena = await _conversacion(negocio, canal, "51902200017", asesor="asesor2")
    await mem.registrar_attribution_event("51902200016", "meta_ads", referral=_referral(), campana_nombre=campana["nombre"])
    await mem.asignar_campana_origen("51902200016", campana["nombre"])
    await mem.registrar_attribution_event("51902200017", "meta_ads_no_resuelto", referral=_referral("ADX", "Secreto de otro"))
    asesor = {"username": "asesor1", "rol": "asesor", "negocio_id": negocio["id"]}
    admin = {"username": "admin1", "rol": "admin", "negocio_id": negocio["id"]}

    cuerpo_asesor = await _bandeja(asesor)
    cuerpo_admin = await _bandeja(admin)

    assert [f["id"] for f in cuerpo_asesor["conversaciones"]] == [suya]
    assert cuerpo_asesor["conversaciones"][0]["origen"]["campana"]["nombre"] == "Meta Terma"
    assert "Secreto de otro" not in json.dumps(cuerpo_asesor)
    por_id = {f["id"]: f for f in cuerpo_admin["conversaciones"]}
    assert por_id[ajena]["origen"]["tipo"] == "anuncio_sin_campana"


async def test_el_detalle_trae_origen_y_respeta_el_permiso_del_chat():
    negocio, canal = await _negocio("g-ori-17")
    campana = await mem.crear_campana("Meta Terma", "referral_meta", "ad1", negocio_id=negocio["id"])
    conv = await _conversacion(negocio, canal, "51902200018", asesor="asesor1")
    await mem.registrar_attribution_event("51902200018", "meta_ads", referral=_referral(), campana_nombre=campana["nombre"])
    await mem.asignar_campana_origen("51902200018", campana["nombre"])

    dueño = {"username": "asesor1", "rol": "asesor", "negocio_id": negocio["id"]}
    otro = {"username": "asesor2", "rol": "asesor", "negocio_id": negocio["id"]}
    ajeno = {"username": "admin9", "rol": "admin", "negocio_id": "otro-negocio"}

    cuerpo = json.loads((await dashboard.conversation_detalle(conv, usuario=dueño)).body)
    assert cuerpo["origen"]["tipo"] == "anuncio_meta" and cuerpo["campana_origen"] == "Meta Terma"
    with pytest.raises(HTTPException) as e:
        await dashboard.conversation_detalle(conv, usuario=otro)
    assert e.value.status_code == 403
    with pytest.raises(HTTPException) as e:
        await dashboard.conversation_detalle(conv, usuario=ajeno)
    assert e.value.status_code == 404


async def test_si_falla_el_origen_la_bandeja_sale_igual(monkeypatch):
    negocio, canal = await _negocio("g-ori-18")
    await _conversacion(negocio, canal, "51902200019", asesor="asesor1")

    async def _roto(*a, **k):
        raise RuntimeError("falla simulada")

    monkeypatch.setattr(oc, "origenes_de_conversaciones", _roto)
    cuerpo = await _bandeja({"username": "admin1", "rol": "admin", "negocio_id": negocio["id"]})

    assert cuerpo["total"] == 1 and cuerpo["conversaciones"][0]["origen"] is None
