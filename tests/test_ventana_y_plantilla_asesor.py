# tests/test_ventana_y_plantilla_asesor.py — 2026-10-06, P3: el asesor sabe de antemano si puede escribir
# libre o solo con plantilla, y puede mandar una PLANTILLA aprobada cuando la ventana de 24 h cerró.
#
#   - memory.obtener_estado_ventana: ventana de 24 h (sin contar reacciones) + ventana gratuita de anuncio.
#   - 409 estructurado (`codigo: "ventana_cerrada"`) y mapeo del error 131047 de Meta.
#   - POST /lead/{tel}/responder-plantilla (capa central, origen `asesor_plantilla`, política de costo).
#   - GET /lead/{tel}/plantilla-retomar y la plantilla configurable (agent/plantilla_retomar.py).
#
# Datos sintéticos únicamente. Sin Meta real: proveedor falso y MockTransport.

import json
import os
from datetime import datetime, timedelta

os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")
os.environ.setdefault("WHATSAPP_PROVIDER", "meta")

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import select, update

from agent import dashboard, envios, http_utils, plantilla_retomar, politica_envios
from agent import memory as mem
from agent.api_contrato import registrar_contrato_interno
from agent.http_utils import EnvioIncierto
from agent.providers import meta as meta_provider
from agent.providers.meta import ProveedorMeta

TEL = "51950611894"
NUMERO = "555000111"
FEP = {"billable": False, "pricing_model": "PMP", "type": "free_entry_point", "category": "service"}


def _h(horas: float) -> timedelta:
    return timedelta(hours=horas)


@pytest.fixture(autouse=True)
def _cache_limpia():
    politica_envios.limpiar_cache()
    yield
    politica_envios.limpiar_cache()


# ── Helpers ─────────────────────────────────────────────────────────────────

async def _escenario(codigo, telefono=TEL, *, asesor="lelespuru", nombre="MARÍA  PÉREZ", interes="cocina empotrada"):
    negocio = await mem.crear_negocio(f"Negocio {codigo}", codigo)
    canal = await mem.crear_canal_whatsapp(nombre=f"Canal {codigo}", phone_number_id=NUMERO, negocio_id=negocio["id"])
    conversation, _ = await mem.resolver_conversation_activa(telefono, negocio["id"], canal["id"])
    await mem.actualizar_lead(telefono, nombre=nombre, interes=interes, negocio_id=negocio["id"], numero_whatsapp_id=NUMERO)
    async with mem.async_session() as s:
        lead = await s.get(mem.Lead, telefono)
        lead.asesor_asignado = asesor
        await s.commit()
    return negocio, conversation.id


async def _mensaje(negocio, telefono, role, contenido, hace: timedelta):
    m = await mem.guardar_mensaje(telefono, role, contenido, negocio["id"])
    async with mem.async_session() as s:
        await s.execute(update(mem.Mensaje).where(mem.Mensaje.id == m["id"]).values(timestamp=datetime.utcnow() - hace))
        await s.commit()
    return m["id"]


async def _uso_fep(negocio, wamid, hace_horas, telefono=TEL):
    assert await mem.registrar_estado_mensaje_meta({
        "wamid": wamid, "estado": "delivered", "momento": datetime.utcnow() - _h(hace_horas),
        "phone_number_id": NUMERO, "destinatario": telefono, "pricing": FEP, "negocio_id": negocio["id"],
    })


def _usuario(negocio, username="lelespuru", rol="asesor", nombre="Lelespuru Díaz"):
    return {"negocio_id": negocio["id"], "username": username, "rol": rol, "nombre": nombre}


async def _filas_envios(nid):
    async with mem.async_session() as s:
        return (await s.execute(select(mem.EnvioMeta).where(mem.EnvioMeta.negocio_id == nid).order_by(mem.EnvioMeta.id))).scalars().all()


async def _mensajes(nid, telefono=TEL):
    async with mem.async_session() as s:
        return (await s.execute(
            select(mem.Mensaje).where(mem.Mensaje.negocio_id == nid, mem.Mensaje.telefono == telefono).order_by(mem.Mensaje.id)
        )).scalars().all()


class _Proveedor:
    """Proveedor falso: registra lo que recibe y responde lo que se le configure."""

    def __init__(self, nid, resultado=(True, "wamid.plantilla")):
        self.nid, self.resultado = nid, resultado
        self.plantillas, self.textos = [], []

    async def resolver_canal(self, numero_whatsapp_id, negocio_id=None):
        return {"negocio_id": self.nid, "phone_number_id": NUMERO}

    async def enviar_plantilla(self, telefono, nombre, parametros, idioma="es", canal=None):
        self.plantillas.append((telefono, nombre, list(parametros), idioma))
        if isinstance(self.resultado, Exception):
            raise self.resultado
        return self.resultado

    async def enviar_mensaje(self, telefono, mensaje, canal=None, mensaje_id_citado=None):
        self.textos.append(mensaje)
        if isinstance(self.resultado, Exception):
            raise self.resultado
        return self.resultado


@pytest.fixture
def panel(monkeypatch):
    emitidos = []

    async def emitir(conversation_id):
        emitidos.append(conversation_id)

    monkeypatch.setattr(dashboard.gestor_conexiones, "emitir_mensaje_nuevo", emitir)

    def instalar(proveedor):
        monkeypatch.setattr(dashboard, "obtener_proveedor", lambda: proveedor)
        return proveedor

    return instalar


async def _configurar_plantilla(nid):
    return await plantilla_retomar.configurar_plantilla(nid, "retomar_consulta", "es")


# ═══ Estado de la ventana ═══════════════════════════════════════════════════

async def test_ventana_abierta_con_su_vencimiento():
    negocio, _ = await _escenario("vpa-1")
    await _mensaje(negocio, TEL, "user", "Hola, quiero una cocina", _h(5))
    e = await mem.obtener_estado_ventana(TEL, negocio["id"])
    assert e["ventana_24h_abierta"] is True and e["puede_texto_libre"] is True and e["puede_plantilla"] is True
    assert abs((e["vence_en"] - (e["ultimo_mensaje_cliente_en"] + _h(24))).total_seconds()) < 1
    assert abs((e["vence_en"] - (datetime.utcnow() + _h(19))).total_seconds()) < 5
    assert e["fep_abierta"] is False and e["fep_vence_en"] is None and e["negocio_id"] == negocio["id"]


async def test_ventana_cerrada_pasadas_las_24_horas_o_sin_mensajes_del_cliente():
    negocio, _ = await _escenario("vpa-2")
    e = await mem.obtener_estado_ventana(TEL, negocio["id"])           # el cliente nunca escribió
    assert (e["ventana_24h_abierta"], e["puede_texto_libre"], e["vence_en"], e["ultimo_mensaje_cliente_en"]) == (False, False, None, None)
    await _mensaje(negocio, TEL, "user", "Hola", _h(25))
    await _mensaje(negocio, TEL, "assistant", "Hola, soy Gabi", _h(1))   # lo nuestro no abre la ventana
    e = await mem.obtener_estado_ventana(TEL, negocio["id"])
    assert e["ventana_24h_abierta"] is False and e["puede_texto_libre"] is False and e["vence_en"] is None
    assert e["puede_plantilla"] is True


async def test_telefono_sin_lead_queda_todo_cerrado_y_el_negocio_se_resuelve_desde_el_lead():
    e = await mem.obtener_estado_ventana("51900000000")
    assert (e["ventana_24h_abierta"], e["fep_abierta"], e["puede_texto_libre"]) == (False, False, False)
    negocio, _ = await _escenario("vpa-3")
    await _mensaje(negocio, TEL, "user", "Hola", _h(1))
    assert (await mem.obtener_estado_ventana(TEL))["ventana_24h_abierta"] is True       # sin negocio_id explícito


async def test_regla_unica_las_reacciones_no_abren_ni_renuevan_la_ventana():
    """Meta no documenta que una reacción abra la ventana: lo prudente es no contarla para PERMITIR texto
    libre. Inicio ya las ignoraba; ahora el envío también."""
    negocio, _ = await _escenario("vpa-4")
    await _mensaje(negocio, TEL, "user", "Quiero una cocina", _h(30))
    await _mensaje(negocio, TEL, "user", "Reaccionó con 👍", _h(1))
    e = await mem.obtener_estado_ventana(TEL, negocio["id"])
    assert e["ventana_24h_abierta"] is False
    assert abs((e["ultimo_mensaje_cliente_en"] - (datetime.utcnow() - _h(30))).total_seconds()) < 5
    ultimo = await mem.obtener_timestamp_ultimo_mensaje_usuario(TEL)
    assert abs((ultimo - (datetime.utcnow() - _h(30))).total_seconds()) < 5          # misma regla en las dos funciones

    # Un mensaje real que menciona "reaccionó" sí cuenta; solo el prefijo exacto de una reacción no.
    await _mensaje(negocio, TEL, "user", "Mi esposo reaccionó con enojo al precio", _h(2))
    assert (await mem.obtener_estado_ventana(TEL, negocio["id"]))["ventana_24h_abierta"] is True


async def test_el_boton_de_la_plantilla_entra_como_mensaje_del_cliente_y_abre_ventana_nueva():
    negocio, _ = await _escenario("vpa-5")
    await _mensaje(negocio, TEL, "user", "Hola", _h(40))
    assert (await mem.obtener_estado_ventana(TEL, negocio["id"]))["ventana_24h_abierta"] is False

    class _Peticion:
        async def json(self):
            return {"entry": [{"changes": [{"value": {
                "metadata": {"phone_number_id": NUMERO},
                "messages": [{"from": TEL, "id": "wamid.boton", "type": "button", "button": {"text": "Sí, continuemos", "payload": "si"}}],
            }}]}]}

    [entrante] = await ProveedorMeta().parsear_webhook(_Peticion())
    assert (entrante.tipo, entrante.texto) == ("text", "Sí, continuemos")
    await mem.guardar_mensaje(TEL, "user", entrante.texto, negocio["id"])           # como lo guarda el webhook
    e = await mem.obtener_estado_ventana(TEL, negocio["id"])
    assert e["ventana_24h_abierta"] is True and e["puede_texto_libre"] is True


# ── Ventana gratuita de anuncio (FEP) ───────────────────────────────────────

async def test_fep_visto_dura_72_horas_desde_el_primer_mensaje_de_la_racha():
    negocio, _ = await _escenario("fep-1")
    await _mensaje(negocio, TEL, "user", "Hola", _h(30))
    await _uso_fep(negocio, "wamid.a", 50)                  # abre la ventana hace 50 h → vence en ~22 h
    await _uso_fep(negocio, "wamid.b", 10)                  # un mensaje más dentro de la misma ventana
    e = await mem.obtener_estado_ventana(TEL, negocio["id"])
    assert e["ventana_24h_abierta"] is False                # el permiso (24 h) y el precio (FEP) son cosas distintas
    assert e["fep_abierta"] is True and e["fep_origen"] == "visto"
    assert abs((e["fep_vence_en"] - (datetime.utcnow() + _h(22))).total_seconds()) < 5
    assert await politica_envios._ventana_de_anuncio_abierta(negocio["id"], TEL) is True    # misma conclusión que la política


async def test_fep_vencido_no_cuenta_y_una_racha_nueva_reemplaza_a_la_vieja():
    negocio, _ = await _escenario("fep-2")
    await _uso_fep(negocio, "wamid.vieja", 100)             # terminó hace ~28 h
    e = await mem.obtener_estado_ventana(TEL, negocio["id"])
    assert e["fep_abierta"] is False and e["fep_vence_en"] is None and e["fep_origen"] is None
    await _uso_fep(negocio, "wamid.nueva", 5)               # otro anuncio, otra ventana
    e = await mem.obtener_estado_ventana(TEL, negocio["id"])
    assert e["fep_abierta"] is True
    assert abs((e["fep_vence_en"] - (datetime.utcnow() + _h(67))).total_seconds()) < 5


async def test_fep_por_abrir_cliente_llego_por_anuncio_y_nadie_le_ha_respondido():
    negocio, _ = await _escenario("fep-3")
    await mem.registrar_attribution_event(TEL, "meta_ads", referral={"source_id": "123"})
    await _mensaje(negocio, TEL, "user", "Vi su anuncio", _h(1))
    e = await mem.obtener_estado_ventana(TEL, negocio["id"])
    assert e["fep_abierta"] is True and e["fep_origen"] == "por_abrir" and e["fep_vence_en"] is None
    assert await politica_envios._ventana_de_anuncio_abierta(negocio["id"], TEL) is True
    # Nuestra respuesta desde el panel abre la ventana de precio: sin ninguna fila de Meta todavía, ya no queda "por abrir".
    await mem.guardar_mensaje(TEL, "asesor", "Hola, te ayudo", negocio["id"])
    e = await mem.obtener_estado_ventana(TEL, negocio["id"])
    assert e["fep_abierta"] is False
    assert await politica_envios._ventana_de_anuncio_abierta(negocio["id"], TEL) is False


async def test_sin_fep_no_se_consultan_los_anuncios():
    negocio, _ = await _escenario("fep-4")
    await _uso_fep(negocio, "wamid.a", 2)
    await _mensaje(negocio, TEL, "user", "Hola", _h(3))
    e = await mem.obtener_estado_ventana(TEL, negocio["id"], con_fep=False)
    assert e["ventana_24h_abierta"] is True and e["fep_abierta"] is False


# ═══ 409 estructurado y error 131047 ════════════════════════════════════════

async def test_el_409_de_ventana_cerrada_trae_codigo_y_datos_de_la_plantilla():
    negocio, _ = await _escenario("v409-1")
    await _mensaje(negocio, TEL, "user", "Hola", _h(30))
    await _uso_fep(negocio, "wamid.a", 20)
    await _configurar_plantilla(negocio["id"])
    with pytest.raises(HTTPException) as e:
        await dashboard._verificar_ventana_atencion(TEL)
    assert e.value.status_code == 409
    assert isinstance(e.value, dashboard.VentanaCerradaError)
    assert "ventana de 24 horas" in e.value.detail and "plantilla" in e.value.detail and "no disponible todavía" not in e.value.detail
    extra = e.value.cuerpo_extra
    assert extra["codigo"] == "ventana_cerrada" and extra["detail"] == e.value.detail
    assert (extra["puede_plantilla"], extra["plantilla_disponible"], extra["fep_abierta"]) == (True, True, True)
    assert extra["fep_vence_en"].endswith("Z") and extra["ventana_abierta"] is False and extra["puede_texto_libre"] is False


async def test_con_la_ventana_abierta_la_verificacion_pasa_sin_consultar_anuncios():
    negocio, _ = await _escenario("v409-2")
    await _mensaje(negocio, TEL, "user", "Hola", _h(2))
    assert await dashboard._verificar_ventana_atencion(TEL) is None


def test_el_cuerpo_http_del_409_conserva_mensaje_y_suma_los_campos_nuevos():
    app = FastAPI()
    registrar_contrato_interno(app)

    @app.get("/cerrada")
    async def cerrada():
        raise dashboard.VentanaCerradaError({"puede_plantilla": True, "plantilla_disponible": False, "fep_abierta": False, "fep_vence_en": None})

    @app.get("/comun")
    async def comun():
        raise HTTPException(status_code=409, detail="otro conflicto")

    cliente = TestClient(app)
    r = cliente.get("/cerrada")
    cuerpo = r.json()
    assert r.status_code == 409 and cuerpo["codigo"] == "ventana_cerrada"
    assert cuerpo["mensaje"] == cuerpo["detail"] == dashboard.TEXTO_VENTANA_CERRADA
    assert cuerpo["puede_plantilla"] is True and cuerpo["plantilla_disponible"] is False and "request_id" in cuerpo
    comun = cliente.get("/comun").json()           # el resto de los errores no cambia
    assert comun["codigo"] == "HTTP_409" and comun["mensaje"] == "otro conflicto" and "detail" not in comun


async def _http_de_meta(monkeypatch, respuesta):
    llamadas = []

    def entregar(request):
        llamadas.append(request)
        return respuesta

    cliente = httpx.AsyncClient(transport=httpx.MockTransport(entregar))
    monkeypatch.setattr(http_utils, "_client", cliente)
    return llamadas, cliente


async def test_el_error_131047_de_meta_se_reconoce_como_ventana_cerrada(monkeypatch):
    negocio, _ = await _escenario("m131-1")
    canal = {"access_token": "t", "phone_number_id": NUMERO, "negocio_id": negocio["id"]}
    _, cliente = await _http_de_meta(monkeypatch, httpx.Response(
        400, json={"error": {"message": "Re-engagement message", "type": "OAuthException", "code": 131047}},
    ))
    try:
        crudo = await ProveedorMeta().enviar_mensaje(TEL, "hola", canal=canal)
        assert crudo == (False, None) and crudo.codigo_error == 131047        # sigue desempaquetándose igual
        r = await envios.enviar_texto(ProveedorMeta(), TEL, "hola", origen="asesor_texto", canal=canal)
    finally:
        await cliente.aclose()
    assert (r.enviado, r.incierto, r.bloqueado, r.fuera_de_ventana, r.codigo_error) == (False, False, False, True, 131047)
    assert r.estado_envio == "fallido"
    [fila] = await _filas_envios(negocio["id"])
    assert fila.decision != "enviado"


@pytest.mark.parametrize("cuerpo", [{"error": {"code": 190}}, {"error": {}}, {}, None])
async def test_otros_errores_de_meta_no_se_confunden_con_ventana_cerrada(monkeypatch, cuerpo):
    negocio, _ = await _escenario("m131-2")
    canal = {"access_token": "t", "phone_number_id": NUMERO, "negocio_id": negocio["id"]}
    respuesta = httpx.Response(400, json=cuerpo) if cuerpo is not None else httpx.Response(400, content=b"no es json")
    _, cliente = await _http_de_meta(monkeypatch, respuesta)
    try:
        r = await envios.enviar_texto(ProveedorMeta(), TEL, "hola", origen="asesor_texto", canal=canal)
    finally:
        await cliente.aclose()
    assert r.enviado is False and r.fuera_de_ventana is False


async def test_responder_con_131047_devuelve_el_409_estructurado_y_no_guarda_el_mensaje(panel):
    """Nuestro cálculo veía la ventana abierta pero Meta dijo que no: mismo caso que el 409 previo."""
    negocio, _ = await _escenario("m131-3")
    await _mensaje(negocio, TEL, "user", "Hola", _h(2))
    await _configurar_plantilla(negocio["id"])

    class _Rechaza(_Proveedor):
        async def enviar_mensaje(self, telefono, mensaje, canal=None, mensaje_id_citado=None):
            return http_utils.RespuestaEnvio(False, None, 131047)

    panel(_Rechaza(negocio["id"]))
    antes = len(await _mensajes(negocio["id"]))
    with pytest.raises(dashboard.VentanaCerradaError) as e:
        await dashboard.responder_cliente(TEL, mensaje="hola", mensaje_id_citado=None, usuario=_usuario(negocio), _csrf=None)
    assert e.value.status_code == 409 and e.value.cuerpo_extra["codigo"] == "ventana_cerrada"
    assert e.value.cuerpo_extra["plantilla_disponible"] is True and e.value.cuerpo_extra["ventana_abierta"] is False
    assert len(await _mensajes(negocio["id"])) == antes


# ═══ Plantilla de retomar consulta ══════════════════════════════════════════

def test_las_variables_van_en_una_linea_sin_vacios_y_con_genericos():
    assert plantilla_retomar.variables_de_plantilla("MARÍA  PÉREZ", "Lelespuru Díaz", "cocina\nempotrada\t y  campana") == [
        "María", "Lelespuru Díaz", "cocina empotrada y campana",
    ]
    assert plantilla_retomar.variables_de_plantilla("51950611894", "", None) == ["cliente", "tu asesor", "nuestros servicios"]
    assert plantilla_retomar.variables_de_plantilla(None, None, "   ")[0] == "cliente"
    largo = plantilla_retomar.variables_de_plantilla("Ana", "Beto", "x" * 200)[2]
    assert len(largo) <= 60 and largo.endswith("…")


def test_la_vista_previa_rellena_el_cuerpo_propuesto():
    variables = plantilla_retomar.variables_de_plantilla("Josué Ríos", "Lelespuru", "termas")
    assert plantilla_retomar.renderizar(plantilla_retomar.CUERPO_POR_DEFECTO, variables) == (
        "Hola Josué, soy Lelespuru de Gaso+. Vi que consultaste por termas y quiero ayudarte a continuar. ¿Seguimos por aquí?"
    )
    assert plantilla_retomar.cantidad_de_variables(plantilla_retomar.CUERPO_POR_DEFECTO) == 3
    assert plantilla_retomar.parametros_para_envio("Hola {{1}}, ¿seguimos?", variables) == ["Josué"]   # tantos como {{n}} tenga


async def test_sin_configurar_la_plantilla_no_esta_disponible_y_configurar_valida():
    negocio = await mem.crear_negocio("Negocio pl-1", "pl-1")
    p = await plantilla_retomar.obtener_plantilla(negocio["id"])
    assert p["disponible"] is False and p["nombre"] is None and p["idioma"] == "es"
    assert p["cuerpo"] == plantilla_retomar.CUERPO_POR_DEFECTO and p["botones"] == ["Sí, continuemos", "Prefiero que me llamen"]
    for nombre, idioma in (("Retomar Consulta", "es"), ("retomar-consulta", "es"), ("retomar_consulta", "español")):
        with pytest.raises(ValueError):
            await plantilla_retomar.configurar_plantilla(negocio["id"], nombre, idioma)
    with pytest.raises(ValueError):
        await plantilla_retomar.configurar_plantilla(negocio["id"], "retomar_consulta", "es", "Hola {{1}} y {{3}}")        # se salta {{2}}
    with pytest.raises(ValueError):
        await plantilla_retomar.configurar_plantilla(negocio["id"], "retomar_consulta", "es", "{{1}}{{2}}{{3}}{{4}}")
    assert (await plantilla_retomar.obtener_plantilla(negocio["id"]))["disponible"] is False      # nada se guardó a medias
    p = await plantilla_retomar.configurar_plantilla(negocio["id"], "retomar_consulta", "es_PE")
    assert (p["disponible"], p["nombre"], p["idioma"]) == (True, "retomar_consulta", "es_PE")
    p = await plantilla_retomar.configurar_plantilla(negocio["id"], "", "es_PE")
    assert p["disponible"] is False                                                                 # vaciar la desactiva


async def test_la_plantilla_es_por_negocio():
    a = await mem.crear_negocio("Negocio pl-2a", "pl-2a")
    b = await mem.crear_negocio("Negocio pl-2b", "pl-2b")
    await _configurar_plantilla(a["id"])
    assert (await plantilla_retomar.obtener_plantilla(a["id"]))["disponible"] is True
    assert (await plantilla_retomar.obtener_plantilla(b["id"]))["disponible"] is False


async def test_get_plantilla_retomar_trae_la_vista_previa_del_lead_y_el_estado_de_la_ventana():
    negocio, _ = await _escenario("pl-3", nombre="Josué Ríos", interes="termas")
    await _mensaje(negocio, TEL, "user", "Hola", _h(30))
    await _uso_fep(negocio, "wamid.a", 10)
    r = await dashboard.plantilla_retomar_del_lead(TEL, usuario=_usuario(negocio, nombre="Lelespuru Díaz"))
    d = json.loads(r.body)
    assert d["disponible"] is False and d["nombre"] is None
    assert d["texto"] == "Hola Josué, soy Lelespuru Díaz de Gaso+. Vi que consultaste por termas y quiero ayudarte a continuar. ¿Seguimos por aquí?"
    assert d["variables_valores"] == ["Josué", "Lelespuru Díaz", "termas"] and d["categoria_supuesta"] == "marketing"
    assert d["ventana"]["ventana_abierta"] is False and d["ventana"]["fep_abierta"] is True and d["ventana"]["plantilla_disponible"] is False
    await _configurar_plantilla(negocio["id"])
    d = json.loads((await dashboard.plantilla_retomar_del_lead(TEL, usuario=_usuario(negocio))).body)
    assert d["disponible"] is True and d["nombre"] == "retomar_consulta" and d["ventana"]["plantilla_disponible"] is True


# ═══ POST /lead/{telefono}/responder-plantilla ═══════════════════════════════

async def test_sin_plantilla_configurada_responde_409_claro_y_no_envia_nada(panel):
    negocio, _ = await _escenario("rp-1")
    await _mensaje(negocio, TEL, "user", "Hola", _h(30))
    p = panel(_Proveedor(negocio["id"]))
    with pytest.raises(HTTPException) as e:
        await dashboard.responder_cliente_con_plantilla(TEL, usuario=_usuario(negocio), _csrf=None)
    assert e.value.status_code == 409 and "Todavía no hay una plantilla aprobada configurada" in e.value.detail
    assert e.value.cuerpo_extra["codigo"] == "plantilla_no_configurada"
    assert p.plantillas == [] and await _filas_envios(negocio["id"]) == []


async def test_con_la_ventana_abierta_no_se_manda_plantilla(panel):
    negocio, _ = await _escenario("rp-2")
    await _mensaje(negocio, TEL, "user", "Hola", _h(2))
    await _configurar_plantilla(negocio["id"])
    p = panel(_Proveedor(negocio["id"]))
    with pytest.raises(HTTPException) as e:
        await dashboard.responder_cliente_con_plantilla(TEL, usuario=_usuario(negocio), _csrf=None)
    assert e.value.status_code == 409 and e.value.cuerpo_extra["codigo"] == "ventana_abierta" and p.plantillas == []


async def test_envia_la_plantilla_atribuida_al_asesor_y_la_guarda_en_el_chat(panel):
    negocio, conversation_id = await _escenario("rp-3", nombre="MARÍA  PÉREZ", interes="cocina empotrada")
    await _mensaje(negocio, TEL, "user", "Hola", _h(30))
    await _uso_fep(negocio, "wamid.fep", 10)                       # ventana gratuita de anuncio abierta
    await _configurar_plantilla(negocio["id"])
    p = panel(_Proveedor(negocio["id"]))

    r = await dashboard.responder_cliente_con_plantilla(TEL, usuario=_usuario(negocio, nombre="Lelespuru Díaz"), _csrf=None)
    d = json.loads(r.body)
    texto = "Hola María, soy Lelespuru Díaz de Gaso+. Vi que consultaste por cocina empotrada y quiero ayudarte a continuar. ¿Seguimos por aquí?"
    assert r.status_code == 200 and d["status"] == "ok" and d["texto"] == texto

    # A Meta le llegan el nombre y el idioma aprobados y SOLO los parámetros del cuerpo (los botones no llevan).
    assert p.plantillas == [(TEL, "retomar_consulta", ["María", "Lelespuru Díaz", "cocina empotrada"], "es")]
    [fila] = await _filas_envios(negocio["id"])
    assert (fila.origen, fila.tipo, fila.asesor_usuario, fila.decision, fila.wamid) == ("asesor_plantilla", "plantilla", "lelespuru", "enviado", "wamid.plantilla")

    ultimo = (await _mensajes(negocio["id"]))[-1]
    assert (ultimo.role, ultimo.content, ultimo.estado_envio, ultimo.mensaje_id_meta) == ("asesor", texto, None, "wamid.plantilla")
    assert ultimo.conversation_id == conversation_id


async def test_un_envio_fallido_se_guarda_como_fallido_y_responde_502(panel):
    negocio, _ = await _escenario("rp-4")
    await _mensaje(negocio, TEL, "user", "Hola", _h(30))
    await _uso_fep(negocio, "wamid.fep", 10)
    await _configurar_plantilla(negocio["id"])
    panel(_Proveedor(negocio["id"], resultado=http_utils.RespuestaEnvio(False, None, 132001)))      # plantilla inexistente en Meta
    r = await dashboard.responder_cliente_con_plantilla(TEL, usuario=_usuario(negocio), _csrf=None)
    assert r.status_code == 502 and json.loads(r.body)["estado_envio"] == "fallido"
    assert "nombre e idioma" in json.loads(r.body)["detail"]
    assert (await _mensajes(negocio["id"]))[-1].estado_envio == "fallido"


async def test_un_envio_incierto_se_guarda_como_incierto_y_responde_200(panel):
    negocio, _ = await _escenario("rp-5")
    await _mensaje(negocio, TEL, "user", "Hola", _h(30))
    await _uso_fep(negocio, "wamid.fep", 10)
    await _configurar_plantilla(negocio["id"])
    panel(_Proveedor(negocio["id"], resultado=EnvioIncierto("ReadTimeout")))
    r = await dashboard.responder_cliente_con_plantilla(TEL, usuario=_usuario(negocio), _csrf=None)
    d = json.loads(r.body)
    assert r.status_code == 200 and d["status"] == "incierto"
    assert (await _mensajes(negocio["id"]))[-1].estado_envio == "incierto"


async def test_politica_de_costo_sin_anuncio_y_tope_cero_la_plantilla_se_frena(panel):
    """No es esencial: respeta el tope mensual existente (USD 0 por defecto). No sale nada ni se guarda mensaje."""
    negocio, _ = await _escenario("rp-6")
    await _mensaje(negocio, TEL, "user", "Hola", _h(30))
    await _configurar_plantilla(negocio["id"])
    p = panel(_Proveedor(negocio["id"]))
    antes = len(await _mensajes(negocio["id"]))
    with pytest.raises(HTTPException) as e:
        await dashboard.responder_cliente_con_plantilla(TEL, usuario=_usuario(negocio), _csrf=None)
    assert e.value.status_code == 409 and e.value.cuerpo_extra["codigo"] == "plantilla_bloqueada_por_costo"
    assert "tope mensual" in e.value.detail and "Uso y envíos" in e.value.detail
    assert p.plantillas == [] and len(await _mensajes(negocio["id"])) == antes
    [fila] = await _filas_envios(negocio["id"])
    assert (fila.origen, fila.decision, fila.asesor_usuario) == ("asesor_plantilla", "bloqueado", "lelespuru")


async def test_politica_de_costo_con_tope_y_tarifa_configurados_la_plantilla_cobrable_sale(panel):
    negocio, _ = await _escenario("rp-7")
    await _mensaje(negocio, TEL, "user", "Hola", _h(30))
    await _configurar_plantilla(negocio["id"])
    await mem.guardar_configuracion_uso_meta(negocio["id"], {"tarifas_usd": {"marketing": 0.07}, "envios": {"tope_mensual_usd": 5}})
    p = panel(_Proveedor(negocio["id"]))
    r = await dashboard.responder_cliente_con_plantilla(TEL, usuario=_usuario(negocio), _csrf=None)
    assert r.status_code == 200 and len(p.plantillas) == 1


async def test_el_interruptor_del_origen_en_nunca_la_frena_incluso_en_anuncio(panel):
    negocio, _ = await _escenario("rp-8")
    await _mensaje(negocio, TEL, "user", "Hola", _h(30))
    await _uso_fep(negocio, "wamid.fep", 10)
    await _configurar_plantilla(negocio["id"])
    await mem.guardar_configuracion_uso_meta(negocio["id"], {"envios": {"modos": {"asesor_plantilla": "nunca"}}})
    p = panel(_Proveedor(negocio["id"]))
    with pytest.raises(dashboard.ErrorConCodigo) as e:
        await dashboard.responder_cliente_con_plantilla(TEL, usuario=_usuario(negocio), _csrf=None)
    assert e.value.cuerpo_extra["codigo"] == "plantilla_bloqueada_por_costo" and p.plantillas == []


async def test_permisos_como_responder_asesor_ajeno_403_y_lead_inexistente_404(panel):
    negocio, _ = await _escenario("rp-9", asesor="otro_asesor")
    await _mensaje(negocio, TEL, "user", "Hola", _h(30))
    await _configurar_plantilla(negocio["id"])
    p = panel(_Proveedor(negocio["id"]))
    with pytest.raises(HTTPException) as e:
        await dashboard.responder_cliente_con_plantilla(TEL, usuario=_usuario(negocio, username="lelespuru", rol="asesor"), _csrf=None)
    assert e.value.status_code == 403
    with pytest.raises(HTTPException) as e:
        await dashboard.responder_cliente_con_plantilla("51999999999", usuario=_usuario(negocio), _csrf=None)
    assert e.value.status_code == 404
    with pytest.raises(HTTPException) as e:
        await dashboard.plantilla_retomar_del_lead(TEL, usuario=_usuario(negocio, username="lelespuru", rol="asesor"))
    assert e.value.status_code == 403
    assert p.plantillas == []
    # Un administrador sí puede (mismo criterio que /responder). Con anuncio abierto no hay costo que frene el envío.
    await _uso_fep(negocio, "wamid.fep", 10)
    r = await dashboard.responder_cliente_con_plantilla(TEL, usuario=_usuario(negocio, username="admin1", rol="admin"), _csrf=None)
    assert r.status_code == 200 and len(p.plantillas) == 1


async def test_otro_negocio_no_ve_ni_envia_a_un_lead_ajeno(panel):
    negocio, _ = await _escenario("rp-10")
    otro = await mem.crear_negocio("Negocio rp-10b", "rp-10b")
    panel(_Proveedor(otro["id"]))
    with pytest.raises(HTTPException) as e:
        await dashboard.responder_cliente_con_plantilla(TEL, usuario=_usuario(otro, username="admin2", rol="admin"), _csrf=None)
    assert e.value.status_code == 404


def test_las_rutas_nuevas_exigen_csrf_solo_las_que_escriben():
    rutas = {getattr(r, "path", ""): r for r in dashboard.router.routes}
    post = next(r for p, r in rutas.items() if p.endswith("/lead/{telefono}/responder-plantilla"))
    assert post.methods == {"POST"}
    assert "verificar_csrf" in {d.call.__name__ for d in post.dependant.dependencies}
    leer = next(r for p, r in rutas.items() if p.endswith("/lead/{telefono}/plantilla-retomar"))
    assert leer.methods == {"GET"}


def test_el_origen_nuevo_es_no_esencial_con_categoria_configurable():
    assert envios.ORIGENES["asesor_plantilla"] == {"esencial": False, "modo": "siempre", "categoria_plantilla": "marketing"}
    assert len(envios.ORIGENES) == 10


# ═══ Estado en el detalle y en la ruta de la conversación ═══════════════════

async def test_el_detalle_de_la_conversacion_trae_la_ventana_de_forma_aditiva():
    negocio, conversation_id = await _escenario("det-1")
    await _mensaje(negocio, TEL, "user", "Hola", _h(30))
    await _uso_fep(negocio, "wamid.fep", 10)
    await _configurar_plantilla(negocio["id"])
    admin = _usuario(negocio, username="admin1", rol="admin")
    d = json.loads((await dashboard.conversation_detalle(conversation_id, usuario=admin)).body)
    assert d["id"] == conversation_id and d["telefono"] == TEL and "eventos" in d        # lo de siempre sigue
    v = d["ventana_whatsapp"]
    assert v["ventana_abierta"] is False and v["ventana_vence_en"] is None and v["puede_texto_libre"] is False
    assert (v["puede_plantilla"], v["plantilla_disponible"], v["fep_abierta"], v["fep_origen"]) == (True, True, True, "visto")
    assert v["fep_vence_en"].endswith("Z") and v["ultimo_mensaje_cliente_en"].endswith("Z")

    solo = json.loads((await dashboard.conversation_ventana_whatsapp(conversation_id, usuario=admin)).body)
    assert solo == v


async def test_la_ruta_de_ventana_respeta_el_acceso_de_la_conversacion():
    negocio, conversation_id = await _escenario("det-2", asesor="otro_asesor")
    with pytest.raises(HTTPException) as e:
        await dashboard.conversation_ventana_whatsapp(conversation_id, usuario=_usuario(negocio, rol="asesor"))
    assert e.value.status_code == 403
    otro = await mem.crear_negocio("Negocio det-2b", "det-2b")
    with pytest.raises(HTTPException) as e:
        await dashboard.conversation_ventana_whatsapp(conversation_id, usuario=_usuario(otro, username="admin2", rol="admin"))
    assert e.value.status_code == 404


async def test_la_ventana_abierta_se_expone_con_su_vencimiento_en_la_ruta():
    negocio, conversation_id = await _escenario("det-3")
    await _mensaje(negocio, TEL, "user", "Hola", _h(21))
    v = json.loads((await dashboard.conversation_ventana_whatsapp(conversation_id, usuario=_usuario(negocio, rol="admin", username="admin1"))).body)
    assert v["ventana_abierta"] is True and v["puede_texto_libre"] is True and v["ventana_vence_en"].endswith("Z")
    vence = datetime.strptime(v["ventana_vence_en"], "%Y-%m-%dT%H:%M:%S.%fZ") if "." in v["ventana_vence_en"] else datetime.strptime(v["ventana_vence_en"], "%Y-%m-%dT%H:%M:%SZ")
    assert abs((vence - (datetime.utcnow() + _h(3))).total_seconds()) < 10
