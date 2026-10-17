# tests/test_anuncios_detectados.py — vista "Anuncios detectados": los anuncios de
# Meta que trajeron leads (evidencia de Attribution V2), a qué campaña
# pertenecen hoy y la asignación posterior cuando la campaña no existía.

import json

import pytest
from fastapi import HTTPException

from agent import dashboard, memory as mem
from agent.campanas import detectar_y_asignar_campana


class _RequestFalso:
    def __init__(self, payload: dict):
        self._payload = payload

    async def json(self):
        return self._payload


def _cuerpo(respuesta) -> dict:
    return json.loads(respuesta.body)


async def _negocio(codigo: str):
    negocio = await mem.crear_negocio(f"Negocio {codigo}", codigo)
    canal = await mem.crear_canal_whatsapp(
        nombre=f"Canal {codigo}", phone_number_id=f"4080000{codigo[-2:]}", negocio_id=negocio["id"],
    )
    return negocio, canal


async def _lead_de_anuncio(negocio, canal, telefono: str, source_id: str, headline: str = "Terma a gas"):
    await mem.actualizar_lead(telefono, negocio_id=negocio["id"], numero_whatsapp_id="x")
    await mem.resolver_conversation_activa(telefono, negocio["id"], canal["id"])
    await mem.registrar_attribution_event(
        telefono, "meta_ads_no_resuelto",
        referral={"source_id": source_id, "headline": headline, "body": "Cuerpo del anuncio", "source_url": "https://fb.me/x"},
    )


async def _totales(negocio_id: str) -> dict:
    return {f["campana"]: f["total"] for f in await mem.contar_opportunities_por_campana(negocio_id)}


async def test_lista_agrupa_por_anuncio_y_muestra_la_campana_actual():
    negocio, canal = await _negocio("g-anu-01")
    julio = await mem.crear_campana("Meta Terma Julio", "referral_meta", "terma", negocio_id=negocio["id"])
    await _lead_de_anuncio(negocio, canal, "51901100001", "AD1")
    await _lead_de_anuncio(negocio, canal, "51901100002", "AD1")
    await _lead_de_anuncio(negocio, canal, "51901100003", "AD2", headline="Secadora")
    await mem.asignar_campana_origen("51901100001", julio["nombre"])

    anuncios = {a["source_id"]: a for a in await mem.listar_anuncios_detectados(negocio["id"])}

    assert anuncios["AD1"]["leads"] == 2 and anuncios["AD1"]["conversaciones"] == 2
    assert anuncios["AD1"]["sin_campana"] == 1
    assert anuncios["AD1"]["campanas"] == [{"campana": "Meta Terma Julio", "conversaciones": 1}]
    assert anuncios["AD1"]["headline"] == "Terma a gas" and anuncios["AD1"]["url"] == "https://fb.me/x"
    assert anuncios["AD2"]["sin_campana"] == 1 and anuncios["AD2"]["campanas"] == []


async def test_asignar_reemplaza_la_campana_y_actualiza_la_analitica():
    negocio, canal = await _negocio("g-anu-02")
    julio = await mem.crear_campana("Meta Terma Julio", "referral_meta", "terma", negocio_id=negocio["id"])
    setiembre = await mem.crear_campana("Meta Terma Setiembre", "referral_meta", "ad1", negocio_id=negocio["id"])
    await _lead_de_anuncio(negocio, canal, "51901100011", "AD1")
    await _lead_de_anuncio(negocio, canal, "51901100012", "AD1")
    await _lead_de_anuncio(negocio, canal, "51901100013", "AD2")
    await mem.asignar_campana_origen("51901100011", julio["nombre"])

    resumen = await mem.asignar_anuncio_a_campana(negocio["id"], "AD1", setiembre["id"], autor="jesus")

    assert resumen == {"conversaciones": 2, "leads": 2}
    totales = await _totales(negocio["id"])
    assert totales["Meta Terma Setiembre"] == 2 and totales["Meta Terma Julio"] == 0
    assert (await mem.obtener_lead("51901100011", negocio_id=negocio["id"]))["campana_origen"] == "Meta Terma Setiembre"
    ad2 = next(a for a in await mem.listar_anuncios_detectados(negocio["id"]) if a["source_id"] == "AD2")
    assert ad2["sin_campana"] == 1


async def test_asignar_no_toca_otro_negocio_ni_acepta_campanas_ajenas():
    negocio_a, canal_a = await _negocio("g-anu-03")
    negocio_b, canal_b = await _negocio("g-anu-04")
    campana_a = await mem.crear_campana("Campaña A", "referral_meta", "ad1", negocio_id=negocio_a["id"])
    campana_b = await mem.crear_campana("Campaña B", "referral_meta", "zzz", negocio_id=negocio_b["id"])
    await _lead_de_anuncio(negocio_a, canal_a, "51901100021", "AD1")
    await _lead_de_anuncio(negocio_b, canal_b, "51901100022", "AD1")

    await mem.asignar_anuncio_a_campana(negocio_a["id"], "AD1", campana_a["id"])

    assert (await _totales(negocio_a["id"]))["Campaña A"] == 1
    assert (await _totales(negocio_b["id"]))["Campaña B"] == 0
    with pytest.raises(LookupError):
        await mem.asignar_anuncio_a_campana(negocio_a["id"], "AD1", campana_b["id"])
    with pytest.raises(LookupError):
        await mem.asignar_anuncio_a_campana(negocio_a["id"], "NO-EXISTE", campana_a["id"])


async def test_endpoint_crea_campana_por_id_de_anuncio_y_asigna():
    negocio, canal = await _negocio("g-anu-05")
    await _lead_de_anuncio(negocio, canal, "51901100031", "AD9")
    usuario = {"negocio_id": negocio["id"], "rol": "admin", "username": "jesus"}

    respuesta = await dashboard.asignar_anuncio_json(
        _RequestFalso({"source_id": "AD9", "nueva_campana": {"nombre": "Meta Terma Setiembre"}}),
        usuario=usuario, _csrf=None,
    )

    cuerpo = _cuerpo(respuesta)
    assert cuerpo["ok"] is True and cuerpo["asignados"] == {"conversaciones": 1, "leads": 1}
    campana = await mem.obtener_campana(cuerpo["campana_id"])
    assert campana["tipo_deteccion"] == "por_anuncio" and campana["patron"] == "ad9"
    assert (await _totales(negocio["id"]))["Meta Terma Setiembre"] == 1


async def test_endpoint_valida_la_entrada():
    negocio, canal = await _negocio("g-anu-06")
    existente = await mem.crear_campana("Ya existe", "referral_meta", "x", negocio_id=negocio["id"])
    await _lead_de_anuncio(negocio, canal, "51901100041", "AD1")
    usuario = {"negocio_id": negocio["id"], "rol": "admin"}

    casos = [
        ({"source_id": "AD1"}, 400),
        ({"source_id": "AD1", "campana_id": existente["id"], "nueva_campana": {"nombre": "Otra"}}, 400),
        ({"source_id": "AD1", "nueva_campana": {"nombre": "ya existe"}}, 400),
        ({"source_id": "NO-EXISTE", "campana_id": existente["id"]}, 404),
        ({"campana_id": existente["id"]}, 400),
    ]
    for payload, esperado in casos:
        with pytest.raises(HTTPException) as e:
            await dashboard.asignar_anuncio_json(_RequestFalso(payload), usuario=usuario, _csrf=None)
        assert e.value.status_code == esperado, payload


async def test_la_deteccion_solo_usa_la_regla_del_anuncio_no_palabras_del_texto():
    negocio, canal = await _negocio("g-anu-07")
    await mem.crear_campana("Meta Terma Julio", "referral_meta", "terma", negocio_id=negocio["id"])  # campaña antigua, por palabra
    await mem.crear_campana_de_anuncio("Meta Terma Setiembre", "120245001", negocio["id"])

    por_regla = await _nuevo_referral(negocio, canal, "51901100051", "120245001", headline="Terma a gas", body="")
    por_texto = await _nuevo_referral(negocio, canal, "51901100052", "OTRO", headline="Terma a gas", body="terma")

    assert por_regla["nombre"] == "Meta Terma Setiembre"
    assert por_texto is None  # el título dice "terma", pero ese anuncio no tiene regla


async def test_el_endpoint_de_lista_devuelve_fechas_y_permiso():
    negocio, canal = await _negocio("g-anu-08")
    await _lead_de_anuncio(negocio, canal, "51901100061", "AD1")

    supervisor = _cuerpo(await dashboard.anuncios_json(usuario={"negocio_id": negocio["id"], "rol": "supervisor"}))
    admin = _cuerpo(await dashboard.anuncios_json(usuario={"negocio_id": negocio["id"], "rol": "admin"}))

    assert supervisor["puede_gestionar"] is False and admin["puede_gestionar"] is True
    assert isinstance(admin["anuncios"][0]["ultimo"], str) and admin["anuncios"][0]["source_id"] == "AD1"


async def _lead_con_url(negocio, canal, telefono: str, source_id: str, source_url):
    await mem.actualizar_lead(telefono, negocio_id=negocio["id"], numero_whatsapp_id="x")
    await mem.resolver_conversation_activa(telefono, negocio["id"], canal["id"])
    referral = {"source_id": source_id, "headline": "H", "body": "B"}
    if source_url is not None:
        referral["source_url"] = source_url
    await mem.registrar_attribution_event(telefono, "meta_ads_no_resuelto", referral=referral)


async def test_la_lista_cuenta_los_leads_por_red_social():
    negocio, canal = await _negocio("g-anu-09")
    await _lead_con_url(negocio, canal, "51901100071", "MIX", "https://fb.me/abc123")
    await _lead_con_url(negocio, canal, "51901100072", "MIX", "https://www.instagram.com/p/xyz/")
    await _lead_con_url(negocio, canal, "51901100073", "MIX", "https://l.instagram.com/?u=1")
    await _lead_con_url(negocio, canal, "51901100074", "MIX", "https://www.facebook.com/ads/x")
    await _lead_con_url(negocio, canal, "51901100075", "MIX", None)
    await _lead_con_url(negocio, canal, "51901100076", "MIX", "https://otro-sitio.com/a")
    await _lead_con_url(negocio, canal, "51901100077", "SOLO-IG", "https://www.instagram.com/p/solo/")

    anuncios = {a["source_id"]: a for a in await mem.listar_anuncios_detectados(negocio["id"])}

    assert anuncios["MIX"]["redes"] == {"facebook": 2, "instagram": 2, "otra": 2}
    assert anuncios["SOLO-IG"]["redes"] == {"facebook": 0, "instagram": 1, "otra": 0}


def test_dominios_parecidos_no_se_confunden_con_instagram_o_facebook():
    assert mem._red_de_referral({"source_url": "https://notinstagram.com/p/1"}) == "otra"
    assert mem._red_de_referral({"source_url": "https://instagram.com.evil.io/p/1"}) == "otra"
    assert mem._red_de_referral({"source_url": "no es una url"}) == "otra"
    assert mem._red_de_referral(None) == "otra"


# ---------------------------------------------------------------------------
# 2026-10-13 — regla explícita anuncio→campaña, comodines y diagnóstico
# ---------------------------------------------------------------------------

async def _legacy(negocio, canal, telefono, source_id, campana_nombre, headline="x", body="x"):
    """Lead que llegó por un anuncio y quedó atribuido a una campaña ANTES de la unificación (estado histórico)."""
    await _nuevo_referral(negocio, canal, telefono, source_id, headline=headline, body=body)
    await mem.asignar_campana_origen(telefono, campana_nombre)


async def _nuevo_referral(negocio, canal, telefono, source_id, headline="Terma a gas", body="Cuerpo terma"):
    await mem.actualizar_lead(telefono, negocio_id=negocio["id"], numero_whatsapp_id="x")
    await mem.resolver_conversation_activa(telefono, negocio["id"], canal["id"])
    return await detectar_y_asignar_campana(
        telefono, "", {"source_id": source_id, "headline": headline, "body": body}, negocio["id"],
    )


async def test_asignar_a_campana_existente_reconoce_a_los_leads_futuros():
    negocio, canal = await _negocio("g-anu-10")
    existente = await mem.crear_campana("Campaña Existente", "referral_meta", "zzz-no-aparece", negocio_id=negocio["id"])
    await _lead_de_anuncio(negocio, canal, "51901100101", "ADX")

    await mem.asignar_anuncio_a_campana(negocio["id"], "ADX", existente["id"], autor="jesus")
    campana = await _nuevo_referral(negocio, canal, "51901100102", "ADX", headline="Otro", body="Otro")

    assert campana is not None and campana["nombre"] == "Campaña Existente"
    assert (await mem.obtener_lead("51901100102", negocio_id=negocio["id"]))["campana_origen"] == "Campaña Existente"


async def test_la_regla_gana_al_patron_y_rechaza_campanas_ajenas():
    negocio, canal = await _negocio("g-anu-11")
    await mem.crear_campana("Comodín", "referral_meta", "terma", negocio_id=negocio["id"])
    destino = await mem.crear_campana("Destino", "referral_meta", "zzz-no-aparece", negocio_id=negocio["id"])
    await mem.guardar_regla_anuncio(negocio["id"], "ADY", destino["id"])

    ganada = await _nuevo_referral(negocio, canal, "51901100111", "ADY")
    assert ganada["nombre"] == "Destino"

    with pytest.raises(LookupError):
        await mem.guardar_regla_anuncio(negocio["id"], "ADY", 999999)


async def test_migrar_comodines_conserva_los_anuncios_y_deja_de_atribuir_los_nuevos():
    negocio, canal = await _negocio("g-anu-12")
    comodin = await mem.crear_campana("Meta Terma Julio", "referral_meta", "terma", negocio_id=negocio["id"])
    por_id = await mem.crear_campana("Con ID", "referral_meta", "12024860142", negocio_id=negocio["id"])
    await _legacy(negocio, canal, "51901100121", "AD-VIEJO", "Meta Terma Julio")
    await _legacy(negocio, canal, "51901100122", "12024860142", "Con ID", headline="Otro", body="Otro")

    plan = await mem.plan_migrar_comodines(negocio["id"])
    assert {c["nombre"] for c in plan["campanas_a_convertir"]} == {"Meta Terma Julio", "Con ID"}
    assert {r["source_id"] for r in plan["reglas_a_crear"]} == {"AD-VIEJO", "12024860142"}
    assert (await mem.obtener_campana(comodin["id"]))["tipo_deteccion"] == "referral_meta"  # el plan no toca nada

    resumen = await mem.aplicar_migrar_comodines(negocio["id"], autor="jesus")
    assert (resumen["campanas"], resumen["reglas"]) == (2, 2)
    assert (await mem.obtener_campana(comodin["id"]))["tipo_deteccion"] == "por_anuncio"
    assert (await mem.obtener_campana(por_id["id"]))["tipo_deteccion"] == "por_anuncio"

    assert (await _nuevo_referral(negocio, canal, "51901100123", "AD-VIEJO"))["nombre"] == "Meta Terma Julio"
    assert (await _nuevo_referral(negocio, canal, "51901100125", "12024860142", headline="z", body="z"))["nombre"] == "Con ID"
    assert await _nuevo_referral(negocio, canal, "51901100124", "AD-NUEVO") is None  # ya no se atribuye por palabra


async def test_diagnostico_muestra_la_evidencia_de_los_leads_sin_campana():
    negocio, canal = await _negocio("g-anu-13")
    await mem.actualizar_lead("51901100131", negocio_id=negocio["id"], numero_whatsapp_id="x")
    await mem.resolver_conversation_activa("51901100131", negocio["id"], canal["id"])
    await mem.registrar_attribution_event("51901100131", "meta_ads_no_resuelto", referral={"source_id": "ADZ"})

    filas = await mem.diagnostico_anuncios_sin_campana(negocio["id"])

    assert len(filas) == 1 and filas[0]["source_id"] == "ADZ"
    assert filas[0]["tiene_headline"] is False and filas[0]["tiene_body"] is False
    assert filas[0]["telefono"] == "…0131"


# ---------------------------------------------------------------------------
# 2026-10-16 — atribución por conversación y corrección histórica
# ---------------------------------------------------------------------------

from agent.campanas import registrar_referral_entrante


async def _cerrar_conversacion(telefono: str, negocio_id: str, canal_id: int):
    """Simula que el cliente vuelve: cierra la conversación activa y abre otra nueva."""
    from sqlalchemy import update
    async with mem.async_session() as session:
        contact = await mem._obtener_contact(session, negocio_id, telefono)
        await session.execute(
            update(mem.Conversation).where(mem.Conversation.contact_id == contact.id).values(estado="cerrada")
        )
        await session.commit()
    await mem.resolver_conversation_activa(telefono, negocio_id, canal_id)


async def test_lead_que_vuelve_por_otro_anuncio_conserva_su_primer_contacto_y_la_conversacion_nueva_toma_la_nueva():
    negocio, canal = await _negocio("g-anu-20")
    await mem.crear_campana_de_anuncio("Primera", "ad-uno", negocio["id"])
    await mem.crear_campana_de_anuncio("Segunda", "ad-dos", negocio["id"])
    await _nuevo_referral(negocio, canal, "51901100201", "ad-uno", headline="x", body="x")
    assert (await mem.obtener_lead("51901100201", negocio_id=negocio["id"]))["campana_origen"] == "Primera"

    await _cerrar_conversacion("51901100201", negocio["id"], canal["id"])
    await registrar_referral_entrante(
        "51901100201", "", {"source_id": "ad-dos", "headline": "y", "body": "y"}, negocio["id"],
    )

    assert (await mem.obtener_lead("51901100201", negocio_id=negocio["id"]))["campana_origen"] == "Primera"
    totales = await _totales(negocio["id"])
    assert totales["Primera"] == 1 and totales["Segunda"] == 1


async def test_la_conversacion_que_ya_tiene_campana_no_se_pisa():
    negocio, canal = await _negocio("g-anu-21")
    await mem.crear_campana_de_anuncio("Primera", "ad-uno", negocio["id"])
    await mem.crear_campana_de_anuncio("Segunda", "ad-dos", negocio["id"])
    await _nuevo_referral(negocio, canal, "51901100211", "ad-uno", headline="x", body="x")
    await registrar_referral_entrante(
        "51901100211", "", {"source_id": "ad-dos", "headline": "y", "body": "y"}, negocio["id"],
    )
    totales = await _totales(negocio["id"])
    assert totales["Primera"] == 1 and totales["Segunda"] == 0


async def test_historico_rellena_conversaciones_vacias_y_se_puede_revertir():
    negocio, canal = await _negocio("g-anu-22")
    julio = await mem.crear_campana("Julio", "referral_meta", "ad-julio", negocio_id=negocio["id"])
    await mem.guardar_regla_anuncio(negocio["id"], "ad-julio", julio["id"])
    await _nuevo_referral(negocio, canal, "51901100221", "ad-julio", headline="x", body="x")
    await _cerrar_conversacion("51901100221", negocio["id"], canal["id"])
    # Evento del segundo ingreso que SÍ resolvió campaña, pero la conversación nueva quedó vacía (comportamiento anterior).
    await mem.registrar_attribution_event_adicional(
        "51901100221", "meta_ads", referral={"source_id": "ad-julio"}, campana_nombre="Julio",
    )
    assert (await _totales(negocio["id"]))["Julio"] == 1

    vista = await mem.historico_rellenar_conversaciones(negocio["id"], aplicar=False)
    assert vista == {"aplicado": False, "conversaciones": 1, "por_campana": {"Julio": 1}}
    assert (await _totales(negocio["id"]))["Julio"] == 1

    hecho = await mem.historico_rellenar_conversaciones(negocio["id"], aplicar=True, autor="jesus")
    assert hecho["aplicado"] is True and (await _totales(negocio["id"]))["Julio"] == 2

    await mem.historico_revertir(negocio["id"], hecho["auditoria_id"], autor="jesus")
    assert (await _totales(negocio["id"]))["Julio"] == 1


async def test_historico_corrige_anuncios_a_sin_campana_y_revierte():
    negocio, canal = await _negocio("g-anu-23")
    comodin = await mem.crear_campana("Meta Secadora Julio", "referral_meta", "secadora", negocio_id=negocio["id"])
    await _legacy(negocio, canal, "51901100231", "AD-DUAL", "Meta Secadora Julio", headline="Financia", body="secadora y terma")
    await _legacy(negocio, canal, "51901100232", "AD-BUENO", "Meta Secadora Julio", headline="Secadora", body="secadora")
    assert (await _totales(negocio["id"]))["Meta Secadora Julio"] == 2

    vista = await mem.historico_corregir_anuncios(negocio["id"], ["AD-DUAL"], None, aplicar=False, desde_campana_ids=[comodin["id"]])
    assert vista == {"aplicado": False, "conversaciones": 1, "leads": 1, "campana_nueva": None}
    assert (await _totales(negocio["id"]))["Meta Secadora Julio"] == 2

    hecho = await mem.historico_corregir_anuncios(negocio["id"], ["AD-DUAL"], None, aplicar=True, autor="jesus", desde_campana_ids=[comodin["id"]])
    assert hecho["aplicado"] is True and hecho["conversaciones"] == 1
    assert (await _totales(negocio["id"]))["Meta Secadora Julio"] == 1
    assert (await mem.obtener_lead("51901100231", negocio_id=negocio["id"]))["campana_origen"] is None
    assert (await mem.obtener_lead("51901100232", negocio_id=negocio["id"]))["campana_origen"] == "Meta Secadora Julio"

    await mem.historico_revertir(negocio["id"], hecho["auditoria_id"], autor="jesus")
    assert (await _totales(negocio["id"]))["Meta Secadora Julio"] == 2
    assert (await mem.obtener_lead("51901100231", negocio_id=negocio["id"]))["campana_origen"] == "Meta Secadora Julio"

    with pytest.raises(LookupError):
        await mem.historico_corregir_anuncios(negocio["id"], ["AD-DUAL"], 999999, aplicar=False, desde_campana_ids=[comodin["id"]])
    with pytest.raises(ValueError):
        await mem.historico_corregir_anuncios(negocio["id"], [], None, aplicar=False, desde_campana_ids=[comodin["id"]])
    with pytest.raises(ValueError):
        await mem.historico_corregir_anuncios(negocio["id"], ["AD-DUAL"], None, aplicar=False)


async def test_historico_no_toca_conversaciones_de_campanas_con_id_ni_de_otro_anuncio():
    negocio, canal = await _negocio("g-anu-24")
    con_id = await mem.crear_campana("Con ID", "referral_meta", "120245009911", negocio_id=negocio["id"])
    comodin = await mem.crear_campana("Comodín", "referral_meta", "zzz", negocio_id=negocio["id"])
    await _legacy(negocio, canal, "51901100241", "120245009911", "Con ID")
    hecho = await mem.historico_corregir_anuncios(
        negocio["id"], ["120245009911"], None, aplicar=True, desde_campana_ids=[comodin["id"]],
    )
    _ = con_id
    assert hecho["conversaciones"] == 0 and (await _totales(negocio["id"]))["Con ID"] == 1


async def test_endpoint_historico_valida_accion_y_permiso():
    negocio, _ = await _negocio("g-anu-25")
    admin = {"negocio_id": negocio["id"], "rol": "admin", "username": "jesus"}
    with pytest.raises(HTTPException) as e:
        await dashboard.corregir_historico_json(_RequestFalso({"accion": "inventada"}), usuario=admin, _csrf=None)
    assert e.value.status_code == 400
    with pytest.raises(HTTPException) as e:
        await dashboard.corregir_historico_json(_RequestFalso({"accion": "corregir", "source_ids": []}), usuario=admin, _csrf=None)
    assert e.value.status_code == 400
    with pytest.raises(HTTPException) as e:
        await dashboard.corregir_historico_json(_RequestFalso({"accion": "corregir", "source_ids": ["1"]}), usuario=admin, _csrf=None)
    assert e.value.status_code == 400
    with pytest.raises(HTTPException) as e:
        await dashboard.corregir_historico_json(_RequestFalso({"accion": "revertir", "auditoria_id": "no-existe"}), usuario=admin, _csrf=None)
    assert e.value.status_code == 404
    vista = json.loads((await dashboard.corregir_historico_json(_RequestFalso({"accion": "rellenar"}), usuario=admin, _csrf=None)).body)
    assert vista["aplicado"] is False


# ---------------------------------------------------------------------------
# 2026-10-16 — un solo mecanismo para Meta: la regla anuncio→campaña
# ---------------------------------------------------------------------------

async def test_unificar_pasa_todas_las_campanas_de_meta_a_regla_y_se_revierte():
    negocio, canal = await _negocio("g-anu-30")
    con_id = await mem.crear_campana("Con ID", "referral_meta", "120245000111", negocio_id=negocio["id"])
    comodin = await mem.crear_campana("Comodín", "referral_meta", "terma", negocio_id=negocio["id"])
    saludo = await mem.crear_campana("SMS", "texto_saludo", "hola gas", negocio_id=negocio["id"])
    await _legacy(negocio, canal, "51901100301", "AD-UNO", "Comodín", headline="Terma", body="terma")
    await _legacy(negocio, canal, "51901100302", "AD-DOS", "Comodín", headline="Terma", body="terma")
    await _legacy(negocio, canal, "51901100307", "120245000111", "Con ID")

    plan = await mem.plan_migrar_comodines(negocio["id"], excluir=["AD-DOS"])
    assert {c["nombre"] for c in plan["campanas_a_convertir"]} == {"Con ID", "Comodín"}
    assert {(r["source_id"], r["origen"]) for r in plan["reglas_a_crear"]} == {("120245000111", "id"), ("AD-UNO", "comodin")}

    hecho = await mem.aplicar_migrar_comodines(negocio["id"], autor="jesus", excluir=["AD-DOS"])
    assert hecho["campanas"] == 2 and hecho["reglas"] == 2
    assert (await mem.obtener_campana(con_id["id"]))["tipo_deteccion"] == "por_anuncio"
    assert (await mem.obtener_campana(saludo["id"]))["tipo_deteccion"] == "texto_saludo"
    assert await mem.obtener_reglas_anuncio(negocio["id"]) == {"120245000111": con_id["id"], "AD-UNO": comodin["id"]}

    # El anuncio con ID y el de un producto siguen reconociéndose; el excluido y uno nuevo ya no se atribuyen por palabra.
    assert (await _nuevo_referral(negocio, canal, "51901100303", "120245000111", headline="x", body="x"))["nombre"] == "Con ID"
    assert (await _nuevo_referral(negocio, canal, "51901100304", "AD-UNO", headline="x", body="x"))["nombre"] == "Comodín"
    assert await _nuevo_referral(negocio, canal, "51901100305", "AD-DOS") is None
    assert await _nuevo_referral(negocio, canal, "51901100306", "AD-NUEVO") is None

    await mem.historico_revertir(negocio["id"], hecho["auditoria_id"], autor="jesus")
    assert (await mem.obtener_campana(con_id["id"]))["tipo_deteccion"] == "referral_meta"
    assert await mem.obtener_reglas_anuncio(negocio["id"]) == {}


async def test_alta_de_campana_de_meta_exige_id_de_anuncio_y_crea_su_regla():
    negocio, _ = await _negocio("g-anu-31")
    admin = {"negocio_id": negocio["id"], "rol": "admin", "username": "jesus"}
    base = {"nombre": "Meta Nueva", "tipo_deteccion": "referral_meta"}

    with pytest.raises(HTTPException) as e:
        await dashboard.crear_campana_nueva_json(_RequestFalso({**base, "patron": "terma"}), usuario=admin, _csrf=None)
    assert e.value.status_code == 400

    creada = _cuerpo(await dashboard.crear_campana_nueva_json(_RequestFalso({**base, "patron": "120245000222"}), usuario=admin, _csrf=None))
    assert creada["campana"]["tipo_deteccion"] == "por_anuncio"
    assert await mem.obtener_reglas_anuncio(negocio["id"]) == {"120245000222": creada["campana"]["id"]}

    with pytest.raises(HTTPException) as e:  # ese anuncio ya pertenece a otra campaña
        await dashboard.crear_campana_nueva_json(
            _RequestFalso({"nombre": "Otra", "tipo_deteccion": "por_anuncio", "patron": "120245000222"}), usuario=admin, _csrf=None,
        )
    assert e.value.status_code == 400

    # Las campañas de saludo (SMS, wa.link) no cambian.
    sms = _cuerpo(await dashboard.crear_campana_nueva_json(
        _RequestFalso({"nombre": "SMS X", "tipo_deteccion": "texto_saludo", "patron": "hola"}), usuario=admin, _csrf=None,
    ))
    assert sms["campana"]["tipo_deteccion"] == "texto_saludo"


async def test_rellenar_no_deshace_una_correccion_a_sin_campana():
    negocio, canal = await _negocio("g-anu-32")
    comodin = await mem.crear_campana("Comodín", "referral_meta", "terma", negocio_id=negocio["id"])
    await _legacy(negocio, canal, "51901100321", "AD-DUAL", "Comodín", headline="x", body="terma")
    # La evidencia original del evento dice "Comodín" (así lo resolvía la palabra clave entonces).
    await mem.registrar_attribution_event_adicional(
        "51901100321", "meta_ads", referral={"source_id": "AD-DUAL"}, campana_nombre="Comodín",
    )
    await mem.historico_corregir_anuncios(
        negocio["id"], ["AD-DUAL"], None, aplicar=True, autor="jesus", desde_campana_ids=[comodin["id"]],
    )
    assert (await _totales(negocio["id"]))["Comodín"] == 0

    vista = await mem.historico_rellenar_conversaciones(negocio["id"], aplicar=False)

    assert vista["conversaciones"] == 0


# ---------------------------------------------------------------------------
# 2026-10-16 — conversaciones con anuncios de dos orígenes, asignación segura y eliminar campaña
# ---------------------------------------------------------------------------

async def _conversacion_con_dos_anuncios(negocio, canal, telefono, primero, segundo, regla_primero_id=None):
    """El lead entra por `primero` y, en la MISMA conversación, llega después un referral de `segundo`."""
    await _nuevo_referral(negocio, canal, telefono, primero, headline="h1", body="b1")
    if regla_primero_id is not None:
        await mem.asignar_campana_origen(telefono, (await mem.obtener_campana(regla_primero_id))["nombre"])
    await mem.registrar_attribution_event_adicional(
        telefono, "meta_ads_no_resuelto", referral={"source_id": segundo, "headline": "h2", "body": "b2"},
    )


async def test_asignar_un_anuncio_no_pisa_lo_que_entro_primero_por_otro():
    negocio, canal = await _negocio("g-anu-40")
    x = await mem.crear_campana_de_anuncio("Campaña A", "AD-A", negocio["id"])
    y = await mem.crear_campana("Campaña B", "por_anuncio", "AD-B", negocio_id=negocio["id"])
    await _conversacion_con_dos_anuncios(negocio, canal, "51901100401", "AD-A", "AD-B", regla_primero_id=x["id"])
    await _nuevo_referral(negocio, canal, "51901100402", "AD-B")  # éste entró PRIMERO por AD-B

    anuncios = {a["source_id"]: a for a in await mem.listar_anuncios_detectados(negocio["id"])}
    assert anuncios["AD-B"]["conversaciones"] == 2 and anuncios["AD-B"]["propias"] == 1

    resumen = await mem.asignar_anuncio_a_campana(negocio["id"], "AD-B", y["id"], autor="jesus")

    assert resumen == {"conversaciones": 1, "leads": 1}
    assert (await mem.obtener_lead("51901100401", negocio_id=negocio["id"]))["campana_origen"] == "Campaña A"
    assert (await mem.obtener_lead("51901100402", negocio_id=negocio["id"]))["campana_origen"] == "Campaña B"
    totales = await _totales(negocio["id"])
    assert totales["Campaña A"] == 1 and totales["Campaña B"] == 1


async def test_recalcular_primer_anuncio_devuelve_cada_conversacion_a_su_campana_y_se_revierte():
    negocio, canal = await _negocio("g-anu-41")
    a = await mem.crear_campana_de_anuncio("Campaña A", "AD-A", negocio["id"])
    b = await mem.crear_campana_de_anuncio("Campaña B", "AD-B", negocio["id"])
    await _conversacion_con_dos_anuncios(negocio, canal, "51901100411", "AD-A", "AD-B", regla_primero_id=a["id"])
    # Estado dañado por la asignación antigua: la conversación y el lead quedaron en la campaña del segundo anuncio.
    async with mem.async_session() as session:
        contact = await mem._obtener_contact(session, negocio["id"], "51901100411")
        conv = await mem._obtener_conversation_activa(session, contact.id)
        conv.campana_origen_id = b["id"]
        lead = await session.get(mem.Lead, "51901100411")
        lead.campana_origen = "Campaña B"
        await session.commit()

    diag = await mem.diagnostico_atribucion_multiple(negocio["id"])
    assert diag["conversaciones_con_varios_anuncios"] == 1 and diag["no_coinciden_con_su_primer_anuncio"] == 1
    assert diag["grupos"][0]["campana_actual"] == "Campaña B" and diag["grupos"][0]["campana_regla_del_primero"] == "Campaña A"

    vista = await mem.historico_recalcular_primer_anuncio(negocio["id"], aplicar=False)
    assert vista == {"aplicado": False, "conversaciones": 1, "leads": 1, "por_campana": {"Campaña A": 1}}
    assert (await _totales(negocio["id"]))["Campaña B"] == 1

    hecho = await mem.historico_recalcular_primer_anuncio(negocio["id"], aplicar=True, autor="jesus")
    assert hecho["aplicado"] is True
    totales = await _totales(negocio["id"])
    assert totales["Campaña A"] == 1 and totales["Campaña B"] == 0
    assert (await mem.obtener_lead("51901100411", negocio_id=negocio["id"]))["campana_origen"] == "Campaña A"
    assert (await mem.historico_recalcular_primer_anuncio(negocio["id"], aplicar=False))["conversaciones"] == 0

    await mem.historico_revertir(negocio["id"], hecho["auditoria_id"], autor="jesus")
    assert (await _totales(negocio["id"]))["Campaña B"] == 1
    assert (await mem.obtener_lead("51901100411", negocio_id=negocio["id"]))["campana_origen"] == "Campaña B"


async def test_recalcular_no_toca_el_primer_anuncio_sin_regla():
    negocio, canal = await _negocio("g-anu-42")
    await mem.crear_campana_de_anuncio("Campaña B", "AD-B", negocio["id"])
    await _conversacion_con_dos_anuncios(negocio, canal, "51901100421", "AD-SIN-REGLA", "AD-B")
    assert (await mem.historico_recalcular_primer_anuncio(negocio["id"], aplicar=False))["conversaciones"] == 0


async def test_eliminar_campana_solo_sin_conversaciones_y_borra_sus_reglas():
    negocio, canal = await _negocio("g-anu-43")
    admin = {"negocio_id": negocio["id"], "rol": "admin", "username": "jesus"}
    sin_uso = await mem.crear_campana_de_anuncio("Sin uso", "AD-NUNCA", negocio["id"])
    con_uso = await mem.crear_campana_de_anuncio("Con uso", "AD-USADO", negocio["id"])
    await _legacy(negocio, canal, "51901100431", "AD-USADO", "Con uso")

    with pytest.raises(HTTPException) as e:
        await dashboard.eliminar_campana_json(con_uso["id"], usuario=admin, _csrf=None)
    assert e.value.status_code == 400 and "Desactívala" in e.value.detail
    assert await mem.obtener_campana(con_uso["id"]) is not None

    assert _cuerpo(await dashboard.eliminar_campana_json(sin_uso["id"], usuario=admin, _csrf=None)) == {"ok": True}
    assert await mem.obtener_campana(sin_uso["id"]) is None
    assert "AD-NUNCA" not in await mem.obtener_reglas_anuncio(negocio["id"])

    otro, _ = await _negocio("g-anu-44")
    with pytest.raises(HTTPException) as e:  # de otro Negocio: 404, nunca se toca
        await dashboard.eliminar_campana_json(con_uso["id"], usuario={"negocio_id": otro["id"], "rol": "admin"}, _csrf=None)
    assert e.value.status_code == 404


async def test_auditoria_de_cierre_explica_por_que_no_se_abrio_una_conversacion_nueva():
    negocio, canal = await _negocio("g-anu-50")
    await mem.crear_campana_de_anuncio("Campaña A", "AD-A", negocio["id"])
    await _conversacion_con_dos_anuncios(negocio, canal, "51901100501", "AD-A", "AD-B")  # sin resultado: abierto
    await _conversacion_con_dos_anuncios(negocio, canal, "51901100502", "AD-A", "AD-B")
    await mem.actualizar_lead("51901100502", negocio_id=negocio["id"], resultado="no_interesado")  # cerrado, sin asesor
    await _conversacion_con_dos_anuncios(negocio, canal, "51901100503", "AD-A", "AD-B")
    await mem.actualizar_lead("51901100503", negocio_id=negocio["id"], resultado="vendido")

    datos = await mem.auditoria_cierre_conversaciones_multiples(negocio["id"])

    assert datos["total"] == 3
    assert datos["por_motivo"] == {
        "resultado_abierto_o_sin_resultado": 1, "cerrado_sin_asesor_la_regla_no_aplica": 1,
        "vendido_nunca_se_cierra_solo": 1,
    }
    assert all(c["telefono"].startswith("…") and c["dias_entre_anuncios"] is not None for c in datos["conversaciones"])
    admin = {"negocio_id": negocio["id"], "rol": "admin"}
    respuesta = json.loads((await dashboard.anuncios_multiples_cierre_json(usuario=admin)).body)
    assert respuesta["total"] == 3 and isinstance(respuesta["conversaciones"][0]["primer_contacto"], str)
