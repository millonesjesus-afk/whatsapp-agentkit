# tests/test_codigo_envio_sms.py — Código por envío de SMS (2026-10-29).
#
# Cada envío de SMS lleva un código al final del saludo («Cód. SMS-TER-29OCT»).
# Cubre los cuatro casos que se le explicaron al usuario:
#   A. lo envía tal cual          → el envío exacto
#   B. borra solo el código       → la campaña general, por la frase
#   C. cambia la frase, deja el código → el envío exacto
#   D. borra todo                 → sin campaña (igual que hoy)
# más el lead que vuelve con el código de otro envío, la creación desde el panel,
# la edición del texto que se busca y que el arranque ya no pise una corrección manual.

import json

import pytest
from fastapi import HTTPException

from agent import campanas, dashboard, memory as mem

SALUDO_BASE = "¡Hola! 👋 Vi la promoción de la terma Rheem 8L y quisiera información 😊"


class _RequestFalso:
    def __init__(self, payload: dict):
        self._payload = payload

    async def json(self):
        return self._payload


def _cuerpo(respuesta) -> dict:
    return json.loads(respuesta.body)


async def _preparar(sufijo: str, telefono: str):
    negocio = await mem.crear_negocio(f"Negocio {sufijo}", f"negocio-{sufijo}")
    canal = await mem.crear_canal_whatsapp(f"Canal {sufijo}", f"pnid-{sufijo}", negocio_id=negocio["id"])
    await mem.actualizar_lead(telefono, numero_whatsapp_id=canal["phone_number_id"], negocio_id=negocio["id"])
    await mem.resolver_conversation_activa(telefono, negocio["id"], canal["id"])
    general = await mem.crear_campana(
        "SMS Terma a gas", "texto_saludo", "terma rheem 8l", texto_saludo=SALUDO_BASE, negocio_id=negocio["id"],
    )
    envio = await mem.crear_campana(
        "SMS Terma · 29-oct", campanas.TIPO_CODIGO_ENVIO, "SMS-TER-29OCT",
        texto_saludo=campanas.saludo_con_codigo(SALUDO_BASE, "SMS-TER-29OCT"), negocio_id=negocio["id"],
    )
    return negocio, canal, general, envio


# ── Reglas puras ─────────────────────────────────────────────────────────────

def test_normalizar_ignora_mayusculas_tildes_espacios_y_guiones():
    assert campanas.normalizar_codigo("Cód. sms-ter 29oct") == "CODSMSTER29OCT"
    assert campanas.normalizar_codigo("SMS-TER-29OCT") == "SMSTER29OCT"


@pytest.mark.parametrize("codigo", ["TER29", "ter29b", "SMS-TER-29OCT", "T29A12"])
def test_codigos_validos(codigo):
    assert campanas.validar_codigo_envio(codigo) is None


@pytest.mark.parametrize("codigo", ["", "SMSTER", "123456", "T29", "A1", "SMS TER 29", "SMS--TER-1", "-SMS-29OCT"])
def test_codigos_invalidos(codigo):
    assert campanas.validar_codigo_envio(codigo) is not None


def test_el_codigo_corto_solo_se_reconoce_como_palabra_suelta():
    lista = [{"tipo_deteccion": "codigo_envio", "patron": "TER29", "nombre": "terma"}]
    for texto in ("Hola (Cód. TER29)", "cod ter29", "COD.TER29 gracias", "ter29"):
        assert campanas.campana_por_codigo(lista, texto)["nombre"] == "terma", texto
    for texto in ("tengo 29 años y quiero una terma", "ter 29", "ter290", "QTER29", "mi código es ter2 9"):
        assert campanas.campana_por_codigo(lista, texto) is None, texto


@pytest.mark.parametrize("tipo,subtipo,esperado", [
    ("Terma", "Terma", "Terma"),
    ("Termas", "Termas a gas", "Termas a gas"),
    ("Termas", "Tiro natural", "Termas · Tiro natural"),
])
def test_el_grupo_no_repite_el_tipo_en_el_subtipo(tipo, subtipo, esperado):
    campana = {"alcance": "producto", "nivel_producto": "subtipo", "tipo_producto": tipo, "subtipo_producto": subtipo}
    assert campanas.descripcion_del_grupo(campana) == esperado


def test_ter29_y_ter29b_son_envios_distintos():
    lista = [
        {"tipo_deteccion": "codigo_envio", "patron": "TER29", "nombre": "primero"},
        {"tipo_deteccion": "codigo_envio", "patron": "TER29B", "nombre": "segundo"},
    ]
    assert campanas.campana_por_codigo(lista, "(Cód. TER29B)")["nombre"] == "segundo"
    assert campanas.campana_por_codigo(lista, "(Cód. TER29)")["nombre"] == "primero"
    assert not campanas.codigos_se_cruzan("TER29", "TER29B")
    assert campanas.codigos_se_cruzan("TER-29", "TER29")
    assert campanas.codigos_se_cruzan("TER-29OCT", "SMS-TER-29OCT")


def test_saludo_con_codigo_lo_agrega_al_final_una_sola_vez():
    final = campanas.saludo_con_codigo(SALUDO_BASE, "sms-ter-29oct")
    assert final == f"{SALUDO_BASE} (Cód. SMS-TER-29OCT)"
    assert campanas.saludo_con_codigo(final, "SMS-TER-29OCT") == final


def test_si_dos_codigos_coinciden_gana_el_mas_largo():
    lista = [
        {"tipo_deteccion": "codigo_envio", "patron": "SMS-TER-29OCT", "nombre": "corto"},
        {"tipo_deteccion": "codigo_envio", "patron": "SMS-TER-29OCT-B2", "nombre": "largo"},
    ]
    assert campanas.campana_por_codigo(lista, "hola cód sms ter 29oct b2")["nombre"] == "largo"
    assert campanas.campana_por_codigo(lista, "hola (Cód. SMS-TER-29OCT)")["nombre"] == "corto"
    assert campanas.campana_por_codigo(lista, "hola, quiero una terma") is None


# ── Primer contacto: los casos A, B, C y D ──────────────────────────────────

async def test_caso_a_lo_envia_tal_cual_reconoce_el_envio_exacto():
    negocio, _canal, _general, envio = await _preparar("ce-a", "51900200001")
    detectada = await campanas.detectar_y_asignar_campana(
        "51900200001", envio["texto_saludo"], None, negocio["id"],
    )
    assert detectada["nombre"] == envio["nombre"]
    lead = await mem.obtener_lead("51900200001", negocio_id=negocio["id"])
    assert lead["campana_origen"] == envio["nombre"]
    eventos = await mem.listar_attribution_events("51900200001", negocio_id=negocio["id"])
    assert [(e["tipo_origen"], e["campana_nombre"], e["first_touch"]) for e in eventos] == [("wa_link", envio["nombre"], True)]


async def test_caso_b_borra_el_codigo_cae_en_la_campana_general():
    negocio, _canal, general, _envio = await _preparar("ce-b", "51900200002")
    detectada = await campanas.detectar_y_asignar_campana("51900200002", SALUDO_BASE, None, negocio["id"])
    assert detectada["nombre"] == general["nombre"]


async def test_caso_c_cambia_la_frase_pero_deja_el_codigo():
    negocio, _canal, _general, envio = await _preparar("ce-c", "51900200003")
    detectada = await campanas.detectar_y_asignar_campana(
        "51900200003", "buenas, info de precios porfa cod sms ter 29oct", None, negocio["id"],
    )
    assert detectada["nombre"] == envio["nombre"]


async def test_caso_d_borra_todo_queda_sin_campana():
    negocio, _canal, _general, _envio = await _preparar("ce-d", "51900200004")
    assert await campanas.detectar_y_asignar_campana("51900200004", "hola", None, negocio["id"]) is None
    lead = await mem.obtener_lead("51900200004", negocio_id=negocio["id"])
    assert not lead.get("campana_origen")


async def test_el_codigo_de_una_campana_inactiva_no_se_reconoce():
    negocio, _canal, general, envio = await _preparar("ce-inact", "51900200005")
    await mem.actualizar_campana(envio["id"], activa=False)
    detectada = await campanas.detectar_y_asignar_campana("51900200005", envio["texto_saludo"], None, negocio["id"])
    assert detectada["nombre"] == general["nombre"]  # la frase sigue sirviendo


# ── Lead que ya tenía campaña y vuelve con el código de un envío ───────────

async def test_lead_con_campana_previa_deja_evidencia_sin_cambiar_su_primer_contacto():
    negocio, canal, general, envio = await _preparar("ce-vuelve", "51900200006")
    await campanas.detectar_y_asignar_campana("51900200006", SALUDO_BASE, None, negocio["id"])

    registrada = await campanas.registrar_codigo_envio_entrante("51900200006", envio["texto_saludo"], negocio["id"])
    assert registrada["nombre"] == envio["nombre"]
    lead = await mem.obtener_lead("51900200006", negocio_id=negocio["id"])
    assert lead["campana_origen"] == general["nombre"]  # first-touch intacto
    eventos = await mem.listar_attribution_events("51900200006", negocio_id=negocio["id"])
    adicionales = [e for e in eventos if e["campana_nombre"] == envio["nombre"]]
    assert len(adicionales) == 1 and adicionales[0]["first_touch"] is False

    # Repetir el código en otro mensaje no duplica la evidencia.
    assert await campanas.registrar_codigo_envio_entrante("51900200006", "cód. SMS-TER-29OCT", negocio["id"]) is None
    eventos = await mem.listar_attribution_events("51900200006", negocio_id=negocio["id"])
    assert len([e for e in eventos if e["campana_nombre"] == envio["nombre"]]) == 1


async def test_lead_con_campana_sin_mencion_de_codigo_no_consulta_campanas(monkeypatch):
    negocio, _canal, _general, _envio = await _preparar("ce-sin", "51900200007")

    async def _no_deberia_llamarse(*_a, **_k):
        raise AssertionError("no debía leer las campañas")

    monkeypatch.setattr(campanas, "listar_campanas", _no_deberia_llamarse)
    assert await campanas.registrar_codigo_envio_entrante("51900200007", "mi DNI es 12345678", negocio["id"]) is None


# ── Panel: crear un envío ────────────────────────────────────────────────────

async def test_panel_crea_el_envio_de_negocio_con_el_codigo_al_final_el_sms_y_el_enlace():
    negocio = await mem.crear_negocio("Negocio ce-panel", "ce-panel")
    usuario = {"negocio_id": negocio["id"], "rol": "admin", "username": "admin"}
    request = _RequestFalso({
        "nombre": "SMS Hogar · 29-oct", "tipo_deteccion": "codigo_envio", "alcance": "negocio",
        "patron": "hog29", "texto_saludo": "¡Hola! Vi el SMS y quisiera información 😊",
        "texto_sms": "Calidda Hogar: encuentra gasodomesticos en cuotas. Escribenos aqui: [enlace]",
    })
    cuerpo = _cuerpo(await dashboard.crear_campana_nueva_json(request, usuario=usuario, _csrf=None))["campana"]
    assert cuerpo["tipo_deteccion"] == "codigo_envio" and cuerpo["alcance"] == "negocio"
    assert cuerpo["patron"] == "HOG29"
    assert cuerpo["texto_saludo"] == "¡Hola! Vi el SMS y quisiera información 😊 (Cód. HOG29)"
    assert cuerpo["texto_sms"].endswith("[enlace]")
    assert cuerpo["link_whatsapp"].startswith("https://wa.me/") and "HOG29" in cuerpo["link_whatsapp"]


async def test_panel_crea_el_envio_por_subtipo_y_gabi_empieza_por_ese_grupo():
    negocio = await mem.crear_negocio("Negocio ce-sub", "ce-sub")
    for codigo, sub, precio in (("T1", "Tiro natural", "419.90"), ("T2", "Tiro forzado", "899"), ("T3", "Tiro natural", "520")):
        await mem.crear_producto(
            {"codigo_hana": codigo, "descripcion": f"Terma {codigo}", "marca": "Rheem", "tipo": "Termas", "sub_tipo": sub, "precio": precio},
            "test", negocio["id"],
        )
    categorias = dashboard.categorias_del_catalogo(await mem.listar_productos_activos(negocio["id"]))
    termas = next(c for c in categorias if c["tipo"].lower() == "termas")
    natural = next(s for s in termas["subtipos"] if s["subtipo"].lower() == "tiro natural")
    assert termas["cantidad"] == 3 and termas["precio_min"] == 419.90
    assert natural["cantidad"] == 2 and natural["precio_min"] == 419.90

    usuario = {"negocio_id": negocio["id"], "rol": "admin", "username": "admin"}
    request = _RequestFalso({
        "nombre": "SMS Termas · 29-oct", "tipo_deteccion": "codigo_envio", "alcance": "producto",
        "nivel_producto": "subtipo", "tipo_producto": termas["tipo"], "subtipo_producto": natural["subtipo"],
        "precio_promocional": "S/ 419.90", "patron": "TER29", "texto_saludo": "¡Hola! Vi el SMS de termas",
    })
    cuerpo = _cuerpo(await dashboard.crear_campana_nueva_json(request, usuario=usuario, _csrf=None))["campana"]
    assert (cuerpo["nivel_producto"], cuerpo["tipo_producto"], cuerpo["subtipo_producto"]) == ("subtipo", termas["tipo"], natural["subtipo"])
    campana = await mem.obtener_campana(cuerpo["id"])
    assert campanas.descripcion_del_grupo(campana) == f"{termas['tipo']} · {natural['subtipo']}"
    # Un envío nunca reserva productos: no esconde nada del catálogo general.
    assert await campanas.obtener_codigos_promocionales_activos(negocio["id"]) == set()


async def test_gabi_recibe_el_grupo_del_sms_y_lo_suma_a_la_busqueda(monkeypatch):
    from agent import brain

    negocio, _canal, _general, _envio = await _preparar("ce-gabi", "51900200010")
    await mem.crear_campana(
        "SMS Termas · 29-oct", campanas.TIPO_CODIGO_ENVIO, "TER29", texto_saludo="Hola (Cód. TER29)",
        precio_promocional="S/ 419.90", alcance="producto", nivel_producto="tipo", tipo_producto="Termas",
        negocio_id=negocio["id"],
    )
    await campanas.detectar_y_asignar_campana("51900200010", "Hola (Cód. TER29)", None, negocio["id"])
    lead = await mem.obtener_lead("51900200010", negocio_id=negocio["id"])
    buscado = {}

    async def _contexto_falso(texto, *_a, **_k):
        buscado["texto"] = texto
        return None

    monkeypatch.setattr(brain, "obtener_contexto_relevante", _contexto_falso)
    bloques = await brain._armar_bloques_contexto("quiero información", [], lead, negocio["id"])
    grupo = [b for b in bloques if "que promocionaba Termas desde S/ 419.90" in b]
    assert grupo and "Empieza recomendando productos de ese grupo" in grupo[0]
    assert buscado["texto"].startswith("Termas ")


async def test_un_envio_por_producto_no_esconde_el_producto_a_los_demas_clientes():
    negocio = await mem.crear_negocio("Negocio ce-prod", "ce-prod")
    await mem.crear_producto({"codigo_hana": "MAT-1", "descripcion": "Terma", "marca": "Rheem", "precio": "419.90"}, "test", negocio["id"])
    usuario = {"negocio_id": negocio["id"], "rol": "admin", "username": "admin"}
    request = _RequestFalso({
        "nombre": "SMS Terma Rheem", "tipo_deteccion": "codigo_envio", "alcance": "producto", "nivel_producto": "producto",
        "codigo_material": "MAT-1", "patron": "TER29", "texto_saludo": "Hola",
    })
    await dashboard.crear_campana_nueva_json(request, usuario=usuario, _csrf=None)
    assert await campanas.obtener_codigos_promocionales_activos(negocio["id"]) == set()


@pytest.mark.parametrize("indice,patron", enumerate(["TER29", "ter-29", "SMS-TER29"]))
async def test_panel_rechaza_un_codigo_que_se_cruza_con_otro_envio(indice, patron):
    negocio = await mem.crear_negocio(f"Negocio ce-cruce-{indice}", f"ce-cruce-{indice}")
    await mem.crear_campana("Ya existe", "codigo_envio", "TER29", texto_saludo="x", negocio_id=negocio["id"])
    usuario = {"negocio_id": negocio["id"], "rol": "admin"}
    request = _RequestFalso({"nombre": "Otro", "tipo_deteccion": "codigo_envio", "alcance": "negocio", "patron": patron, "texto_saludo": "Hola"})
    with pytest.raises(HTTPException) as error:
        await dashboard.crear_campana_nueva_json(request, usuario=usuario, _csrf=None)
    assert error.value.status_code == 400 and "Ya existe" in error.value.detail


@pytest.mark.parametrize("indice,cuerpo", enumerate([
    {"patron": "SMSSEC", "texto_saludo": "Hola", "alcance": "negocio"},                       # código sin número
    {"patron": "SEC29", "texto_saludo": "", "alcance": "negocio"},                            # sin saludo
    {"patron": "SEC29", "texto_saludo": "Hola"},                                              # sin alcance
    {"patron": "SEC29", "texto_saludo": "Hola", "alcance": "producto", "nivel_producto": "producto"},  # sin producto
    {"patron": "SEC29", "texto_saludo": "Hola", "alcance": "producto", "nivel_producto": "tipo", "tipo_producto": "Inexistente"},
    {"patron": "SEC29", "texto_saludo": "Hola", "alcance": "negocio", "texto_sms": "SMS sin el enlace"},
]))
async def test_panel_rechaza_envio_incompleto(indice, cuerpo):
    negocio = await mem.crear_negocio(f"Negocio ce-inc-{indice}", f"ce-inc-{indice}")
    usuario = {"negocio_id": negocio["id"], "rol": "admin"}
    request = _RequestFalso({"nombre": "Envío", "tipo_deteccion": "codigo_envio", **cuerpo})
    with pytest.raises(HTTPException) as error:
        await dashboard.crear_campana_nueva_json(request, usuario=usuario, _csrf=None)
    assert error.value.status_code == 400


async def test_rubro_del_negocio_se_guarda_y_sale_en_el_listado():
    negocio = await mem.crear_negocio("Muebles Sol", "ce-rubro")
    usuario = {"negocio_id": negocio["id"], "rol": "admin"}
    await dashboard.guardar_rubro_negocio_json(_RequestFalso({"rubro": "  muebles  y colchones "}), usuario=usuario, _csrf=None)
    listado = _cuerpo(await dashboard.campanas_json(usuario=usuario))
    assert listado["negocio"]["nombre"] == "Muebles Sol"
    assert listado["negocio"]["rubro"] == "muebles y colchones"
    assert listado["negocio"]["unidades"] == []


# ── Panel: editar el texto que se busca ─────────────────────────────────────

async def test_panel_edita_el_texto_que_se_busca_de_una_campana_de_saludo():
    negocio = await mem.crear_negocio("Negocio ce-edit", "ce-edit")
    campana = await mem.crear_campana(
        "SMS Clientes que ya tienen gas", "texto_saludo", "ya tienes gas natural",
        texto_saludo="¡Hola! 👋\r\nYa cuento con gas natural en casa 🔥", negocio_id=negocio["id"],
    )
    usuario = {"negocio_id": negocio["id"], "rol": "admin", "username": "admin"}
    request = _RequestFalso({"patron": "Cuento con gas natural"})
    cuerpo = _cuerpo(await dashboard.editar_promo_campana_json(campana["id"], request, usuario=usuario, _csrf=None))
    assert cuerpo["campana"]["patron"] == "cuento con gas natural"


@pytest.mark.parametrize("patron", ["no aparece en el saludo", "gas"])
async def test_panel_rechaza_un_texto_que_no_esta_en_el_saludo_o_es_muy_corto(patron):
    negocio = await mem.crear_negocio(f"Negocio ce-edmal-{len(patron)}", f"ce-edmal-{len(patron)}")
    campana = await mem.crear_campana(
        "Campaña", "texto_saludo", "cuento con gas natural", texto_saludo="Ya cuento con gas natural", negocio_id=negocio["id"],
    )
    usuario = {"negocio_id": negocio["id"], "rol": "admin"}
    with pytest.raises(HTTPException) as error:
        await dashboard.editar_promo_campana_json(campana["id"], _RequestFalso({"patron": patron}), usuario=usuario, _csrf=None)
    assert error.value.status_code == 400


async def test_panel_no_deja_cambiar_el_codigo_de_un_envio():
    negocio = await mem.crear_negocio("Negocio ce-edcod", "ce-edcod")
    campana = await mem.crear_campana("Envío", "codigo_envio", "SMS-TER-29OCT", texto_saludo="x", negocio_id=negocio["id"])
    usuario = {"negocio_id": negocio["id"], "rol": "admin"}
    with pytest.raises(HTTPException):
        await dashboard.editar_promo_campana_json(campana["id"], _RequestFalso({"patron": "SMS-TER-30OCT"}), usuario=usuario, _csrf=None)
    # Mandar el mismo código (el formulario lo reenvía tal cual) no es un cambio.
    cuerpo = _cuerpo(await dashboard.editar_promo_campana_json(
        campana["id"], _RequestFalso({"patron": "SMS-TER-29OCT", "precio_promocional": "S/ 399"}), usuario=usuario, _csrf=None,
    ))
    assert cuerpo["campana"]["patron"] == "SMS-TER-29OCT" and cuerpo["campana"]["precio_promocional"] == "S/ 399"


# ── El arranque ya no pisa una corrección manual ────────────────────────────

async def test_el_arranque_respeta_un_patron_que_si_esta_en_el_saludo():
    negocio = await mem.crear_negocio("Negocio ce-arr", "ce-arr")
    campana = await mem.crear_campana(
        "SMS Clientes que ya tienen gas", "texto_saludo", "cuento con gas natural",
        texto_saludo="¡Hola! 👋\r\nYa cuento con gas natural en casa 🔥", negocio_id=negocio["id"],
    )
    await campanas.corregir_patrones_desalineados(negocio["id"])
    assert (await mem.obtener_campana(campana["id"]))["patron"] == "cuento con gas natural"
