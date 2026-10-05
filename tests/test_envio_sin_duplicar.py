# tests/test_envio_sin_duplicar.py — 2026-10-05: los envíos a /messages de Meta nunca
# se reintentan si el mensaje pudo haber salido.
#
# Antes `post_con_reintentos` reintentaba cualquier error de transporte (incluido
# ReadTimeout) y todo 5xx: si Meta aceptaba el mensaje pero la respuesta se perdía,
# el reintento mandaba un duplicado (otro wamid, otro cobro, el cliente lo recibe
# dos veces) y la capa de envíos lo marcaba "fallido". Supuesto de diseño (no
# verificado contra la documentación): Meta Cloud API no tiene clave de idempotencia.
#
# Se simula httpx con MockTransport sobre el cliente compartido de http_utils, así
# que se ejercita el código real de reintentos.

import json
import os
from datetime import datetime, timedelta

os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")
os.environ.setdefault("WHATSAPP_PROVIDER", "meta")

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import select

from agent import dashboard, envios, http_utils
from agent import memory as mem
from agent.http_utils import EnvioIncierto
from agent.providers import meta as meta_provider
from agent.providers.meta import ProveedorMeta

TEL = "51987654321"
PHONE_ID = "111"


class _Ctx:
    def __init__(self):
        self.llamadas: list[httpx.Request] = []
        self.respuestas = []            # cola: Response o Exception a levantar
        self.esperas_http: list[float] = []
        self.esperas_conciliacion: list[float] = []


def _ok(wamid="wamid.NUEVO"):
    return httpx.Response(200, json={"messages": [{"id": wamid}]})


@pytest_asyncio.fixture
async def http(monkeypatch):
    ctx = _Ctx()

    def entregar(request: httpx.Request):
        ctx.llamadas.append(request)
        item = ctx.respuestas.pop(0) if len(ctx.respuestas) > 1 else ctx.respuestas[0]
        if isinstance(item, Exception):
            raise item
        return item

    cliente = httpx.AsyncClient(transport=httpx.MockTransport(entregar))
    monkeypatch.setattr(http_utils, "_client", cliente)

    async def dormir(segundos):
        ctx.esperas_http.append(segundos)

    async def esperar(segundos):
        ctx.esperas_conciliacion.append(segundos)

    monkeypatch.setattr(http_utils, "_dormir", dormir)
    monkeypatch.setattr(meta_provider, "_esperar", esperar)
    yield ctx
    await cliente.aclose()


def _canal(negocio_id=None):
    return {"access_token": "token-falso", "phone_number_id": PHONE_ID, "negocio_id": negocio_id}


async def _uso(wamid, destinatario=TEL, estado="sent", enviado_en=None, phone_number_id=PHONE_ID, negocio_id=None, creado=None):
    async with mem.async_session() as s:
        s.add(mem.UsoMensajeMeta(
            wamid=wamid, phone_number_id=phone_number_id, negocio_id=negocio_id, destinatario=destinatario, estado=estado,
            enviado_en=enviado_en if enviado_en is not None else datetime.utcnow(), creado=creado or datetime.utcnow(),
        ))
        await s.commit()


async def _filas_envios(negocio_id):
    async with mem.async_session() as s:
        return (await s.execute(select(mem.EnvioMeta).where(mem.EnvioMeta.negocio_id == negocio_id).order_by(mem.EnvioMeta.id))).scalars().all()


async def _negocio(codigo):
    n = await mem.crear_negocio(f"Negocio {codigo}", codigo)
    return n["id"], _canal(n["id"])


# ── http_utils.post_sin_duplicar ────────────────────────────────────────────

@pytest.mark.parametrize("error", [
    httpx.ConnectError("sin red"), httpx.ConnectTimeout("lento"), httpx.PoolTimeout("sin conexiones libres"),
])
async def test_si_la_peticion_nunca_salio_se_reintenta(http, error):
    http.respuestas = [error, error, _ok()]
    r = await http_utils.post_sin_duplicar("https://graph.test/messages", json={})
    assert r.status_code == 200
    assert len(http.llamadas) == 3
    assert http.esperas_http == [1, 2]


async def test_si_siempre_falla_la_conexion_se_relanza_el_error_tras_3_intentos(http):
    http.respuestas = [httpx.ConnectError("sin red")]
    with pytest.raises(httpx.ConnectError):
        await http_utils.post_sin_duplicar("https://graph.test/messages", json={})
    assert len(http.llamadas) == 3


@pytest.mark.parametrize("error", [
    httpx.ReadTimeout("sin respuesta"), httpx.WriteTimeout("a medias"), httpx.ReadError("cortada"),
    httpx.WriteError("cortada"), httpx.RemoteProtocolError("Meta cerró la conexión"),
])
async def test_si_pudo_haber_salido_no_se_reintenta_y_es_incierto(http, error):
    http.respuestas = [error, _ok()]            # el segundo valor NO debe usarse
    with pytest.raises(EnvioIncierto) as e:
        await http_utils.post_sin_duplicar("https://graph.test/messages", json={})
    assert len(http.llamadas) == 1 and http.esperas_http == []
    assert type(error).__name__ in e.value.motivo and e.value.__cause__ is error


@pytest.mark.parametrize("estado", [500, 502, 503, 504])
async def test_un_5xx_no_se_reintenta_y_es_incierto(http, estado):
    http.respuestas = [httpx.Response(estado, text="error"), _ok()]
    with pytest.raises(EnvioIncierto) as e:
        await http_utils.post_sin_duplicar("https://graph.test/messages", json={})
    assert len(http.llamadas) == 1 and http.esperas_http == []
    assert e.value.status_code == estado


async def test_un_4xx_se_devuelve_tal_cual_sin_reintentar(http):
    http.respuestas = [httpx.Response(400, json={"error": {"code": 131047}}), _ok()]
    r = await http_utils.post_sin_duplicar("https://graph.test/messages", json={})
    assert r.status_code == 400 and len(http.llamadas) == 1


async def test_un_429_respeta_retry_after(http):
    limite = httpx.Response(429, headers={"Retry-After": "3"})
    http.respuestas = [limite, limite, _ok()]
    r = await http_utils.post_sin_duplicar("https://graph.test/messages", json={})
    assert r.status_code == 200 and len(http.llamadas) == 3
    assert http.esperas_http == [3.0, 3.0]


async def test_un_429_sin_retry_after_usa_la_espera_de_siempre(http):
    http.respuestas = [httpx.Response(429), _ok()]
    r = await http_utils.post_sin_duplicar("https://graph.test/messages", json={})
    assert r.status_code == 200 and http.esperas_http == [1]


async def test_un_429_que_pide_esperar_mas_que_el_tope_no_se_reintenta(http):
    http.respuestas = [httpx.Response(429, headers={"Retry-After": "300"}), _ok()]
    r = await http_utils.post_sin_duplicar("https://graph.test/messages", json={})
    assert r.status_code == 429 and len(http.llamadas) == 1 and http.esperas_http == []


async def test_un_429_persistente_devuelve_el_429_tras_3_intentos(http):
    http.respuestas = [httpx.Response(429, headers={"Retry-After": "1"})]
    r = await http_utils.post_sin_duplicar("https://graph.test/messages", json={})
    assert r.status_code == 429 and len(http.llamadas) == 3


async def test_post_con_reintentos_sigue_igual_para_los_demas_usos(http):
    """No se tocó: sigue reintentando el 5xx (se usa para marcar leído, subir media...)."""
    http.respuestas = [httpx.Response(502), _ok()]
    r = await http_utils.post_con_reintentos("https://graph.test/x", json={})
    assert r.status_code == 200 and len(http.llamadas) == 2


# ── Proveedor Meta: incierto → conciliar con uso_mensajes_meta ──────────────

async def test_un_envio_normal_devuelve_el_wamid(http):
    http.respuestas = [_ok("wamid.A")]
    assert await ProveedorMeta().enviar_mensaje(TEL, "hola", canal=_canal()) == (True, "wamid.A")
    assert json.loads(http.llamadas[0].content)["to"] == TEL
    assert http.esperas_conciliacion == []


async def test_read_timeout_no_reenvia_espera_5s_y_consulta_la_tabla(http):
    http.respuestas = [httpx.ReadTimeout("sin respuesta"), _ok("wamid.DUPLICADO")]
    with pytest.raises(EnvioIncierto):
        await ProveedorMeta().enviar_mensaje(TEL, "hola", canal=_canal())
    assert len(http.llamadas) == 1                       # UNA sola llamada: no se duplicó
    assert http.esperas_conciliacion == [meta_provider.ESPERA_CONCILIACION_SEGUNDOS] == [5]


async def test_incierto_se_resuelve_como_enviado_si_aparece_la_fila_en_uso_mensajes_meta(http):
    await _uso("wamid.LLEGO", enviado_en=datetime.utcnow() + timedelta(seconds=2))
    http.respuestas = [httpx.ReadTimeout("sin respuesta"), _ok("wamid.DUPLICADO")]
    assert await ProveedorMeta().enviar_mensaje(TEL, "hola", canal=_canal()) == (True, "wamid.LLEGO")
    assert len(http.llamadas) == 1


async def test_un_5xx_tambien_se_concilia(http):
    await _uso("wamid.LLEGO")
    http.respuestas = [httpx.Response(502, text="bad gateway"), _ok()]
    assert await ProveedorMeta().enviar_mensaje(TEL, "hola", canal=_canal()) == (True, "wamid.LLEGO")
    assert len(http.llamadas) == 1


async def test_la_conciliacion_acepta_el_telefono_con_mas(http):
    await _uso("wamid.LLEGO", destinatario=TEL)
    http.respuestas = [httpx.ReadTimeout("x")]
    assert await ProveedorMeta().enviar_mensaje("+" + TEL, "hola", canal=_canal()) == (True, "wamid.LLEGO")


async def test_la_conciliacion_ignora_filas_que_no_son_de_este_envio(http):
    ahora = datetime.utcnow()
    await _uso("wamid.OTRO_CLIENTE", destinatario="51900000000")
    await _uso("wamid.VIEJO", enviado_en=ahora - timedelta(minutes=5))
    await _uso("wamid.FALLIDO", estado="failed")
    await _uso("wamid.OTRO_NUMERO", phone_number_id="999")
    http.respuestas = [httpx.ReadTimeout("x")]
    with pytest.raises(EnvioIncierto):
        await ProveedorMeta().enviar_mensaje(TEL, "hola", canal=_canal())


async def test_la_conciliacion_ignora_wamids_ya_reclamados(http):
    nid, canal = await _negocio("sd-reclamado")
    await _uso("wamid.EN_MENSAJES")
    await _uso("wamid.EN_ENVIOS")
    async with mem.async_session() as s:
        s.add(mem.Mensaje(telefono=TEL, role="asesor", content="x", timestamp=datetime.utcnow(), negocio_id=nid, mensaje_id_meta="wamid.EN_MENSAJES"))
        s.add(mem.EnvioMeta(negocio_id=nid, origen="asesor_texto", telefono=TEL, tipo="texto", decision="enviado", wamid="wamid.EN_ENVIOS"))
        await s.commit()
    http.respuestas = [httpx.ReadTimeout("x")]
    with pytest.raises(EnvioIncierto):
        await ProveedorMeta().enviar_mensaje(TEL, "hola", canal=canal)
    # …y una fila libre sí se toma.
    await _uso("wamid.LIBRE")
    assert await ProveedorMeta().enviar_mensaje(TEL, "hola", canal=canal) == (True, "wamid.LIBRE")


async def test_si_falla_la_consulta_de_conciliacion_queda_incierto(http, monkeypatch):
    async def explota(*a, **k):
        raise RuntimeError("base caída")

    monkeypatch.setattr(meta_provider, "buscar_wamid_huerfano", explota)
    http.respuestas = [httpx.ReadTimeout("x")]
    with pytest.raises(EnvioIncierto):
        await ProveedorMeta().enviar_mensaje(TEL, "hola", canal=_canal())


@pytest.mark.parametrize("metodo,args", [
    ("enviar_mensaje", ("hola",)),
    ("enviar_imagen", ("media-1", "pie")),
    ("enviar_documento", ("media-2", "a.pdf", "pie")),
    ("enviar_audio", ("media-3",)),
    ("enviar_plantilla", ("bienvenida", ["Ana"], "es")),
])
async def test_los_5_envios_usan_post_sin_duplicar(http, metodo, args):
    http.respuestas = [httpx.ReadTimeout("x"), _ok("wamid.DUPLICADO")]
    with pytest.raises(EnvioIncierto):
        await getattr(ProveedorMeta(), metodo)(TEL, *args, canal=_canal())
    assert len(http.llamadas) == 1

    http.llamadas.clear()
    http.respuestas = [_ok("wamid.B")]
    assert await getattr(ProveedorMeta(), metodo)(TEL, *args, canal=_canal()) == (True, "wamid.B")


async def test_un_rechazo_definitivo_sigue_siendo_false_none(http):
    http.respuestas = [httpx.Response(400, json={"error": {"code": 131047}})]
    assert await ProveedorMeta().enviar_mensaje(TEL, "hola", canal=_canal()) == (False, None)
    assert await ProveedorMeta().enviar_plantilla(TEL, "b", [], "es", canal=_canal()) == (False, None)


# ── Capa central (envios.py) ────────────────────────────────────────────────

async def test_la_capa_nunca_marca_fallido_un_incierto(http):
    nid, canal = await _negocio("sd-capa-1")
    http.respuestas = [httpx.ReadTimeout("x"), _ok()]
    r = await envios.enviar_texto(ProveedorMeta(), TEL, "hola", origen="asesor_texto", canal=canal)
    assert r.incierto is True and r.enviado is False and r.bloqueado is False and not bool(r)
    assert tuple(r) == (False, None)
    assert "incierto" in r.motivo
    assert len(http.llamadas) == 1
    [fila] = await _filas_envios(nid)
    assert fila.decision == "incierto" and fila.wamid is None
    assert "incierto" in fila.motivo and len(fila.motivo) <= 200


async def test_la_capa_marca_enviado_si_la_conciliacion_encuentra_el_wamid(http):
    nid, canal = await _negocio("sd-capa-2")
    await _uso("wamid.LLEGO")
    http.respuestas = [httpx.Response(503), _ok()]
    r = await envios.enviar_texto(ProveedorMeta(), TEL, "hola", origen="asesor_texto", canal=canal)
    assert (r.enviado, r.wamid, r.incierto) == (True, "wamid.LLEGO", False)
    [fila] = await _filas_envios(nid)
    assert (fila.decision, fila.wamid) == ("enviado", "wamid.LLEGO")


@pytest.mark.parametrize("llamar", [
    lambda p, c: envios.enviar_texto(p, TEL, "x", origen="asesor_texto", canal=c),
    lambda p, c: envios.enviar_imagen(p, TEL, "m", "pie", origen="asesor_archivo", canal=c),
    lambda p, c: envios.enviar_documento(p, TEL, "m", "a.pdf", "pie", origen="asesor_archivo", canal=c),
    lambda p, c: envios.enviar_audio(p, TEL, "m", origen="asesor_audio", canal=c),
])
async def test_cada_tipo_de_envio_queda_incierto_y_nunca_fallido(llamar):
    nid, canal = await _negocio("sd-capa-3")

    class Incierto:
        async def _falla(self, *a, **k):
            raise EnvioIncierto("Meta respondió 502", status_code=502)

        enviar_mensaje = enviar_imagen = enviar_documento = enviar_audio = _falla

    r = await llamar(Incierto(), canal)
    assert r.incierto and not r.enviado
    assert [f.decision for f in await _filas_envios(nid)] == ["incierto"]


async def test_la_plantilla_incierta_tambien_queda_incierta():
    nid, canal = await _negocio("sd-capa-4")
    await mem.guardar_configuracion_uso_meta(nid, {"confirmar_riesgo": True, "envios": {"autorecarga": True}})

    class Incierto:
        async def enviar_plantilla(self, *a, **k):
            raise EnvioIncierto("ReadTimeout")

    r = await envios.enviar_plantilla(Incierto(), TEL, "b", ["A"], "es", origen="plantilla_formulario", canal=canal)
    assert r.incierto and [f.decision for f in await _filas_envios(nid)] == ["incierto"]


async def test_un_incierto_no_cuenta_como_enviado_para_la_agrupacion_ni_se_reintenta_solo():
    nid, canal = await _negocio("sd-capa-5")

    class Incierto:
        async def enviar_mensaje(self, *a, **k):
            raise EnvioIncierto("ReadTimeout")

    class Bueno:
        llamadas = 0

        async def enviar_mensaje(self, *a, **k):
            Bueno.llamadas += 1
            return True, "wamid.B"

    r1 = await envios.enviar_texto(Incierto(), TEL, "no leo fotos", origen="gabi_aviso_no_legible", canal=canal)
    assert r1.incierto
    r2 = await envios.enviar_texto(Bueno(), TEL, "no leo fotos", origen="gabi_aviso_no_legible", canal=canal)
    assert r2.enviado and not r2.bloqueado                 # el incierto no bloquea por "agrupado"
    assert [f.decision for f in await _filas_envios(nid)] == ["incierto", "enviado"]
    assert Bueno.llamadas == 1                              # nada reenvió el incierto por su cuenta


async def test_otras_excepciones_siguen_marcando_fallido_y_propagandose():
    nid, canal = await _negocio("sd-capa-6")

    class Roto:
        async def enviar_mensaje(self, *a, **k):
            raise httpx.ConnectError("sin red")           # nunca salió: fallo definitivo

    with pytest.raises(httpx.ConnectError):
        await envios.enviar_texto(Roto(), TEL, "x", origen="gabi_respuesta", canal=canal)
    assert [f.decision for f in await _filas_envios(nid)] == ["fallido"]


async def test_los_proveedores_falsos_existentes_siguen_funcionando():
    class Falso:
        async def enviar_mensaje(self, telefono, mensaje, canal=None, mensaje_id_citado=None):
            return True, "wamid.F"

        async def enviar_plantilla(self, telefono, nombre, parametros, idioma="es", canal=None):
            return True   # booleano, como el proveedor de antes

    p = Falso()
    r = await envios.enviar_texto(p, TEL, "x", origen="gabi_respuesta", canal=None)
    enviado, wamid = r
    assert (enviado, wamid, r.incierto, bool(r)) == (True, "wamid.F", False, True)
    rp = await envios.enviar_plantilla(p, TEL, "b", [], origen="gabi_respuesta", canal=None)   # esencial: la política de costo no la frena
    assert rp.enviado and rp.wamid is None and rp.incierto is False


def test_resultado_envio_conserva_la_firma_posicional_de_antes():
    r = envios.ResultadoEnvio(False, None, True, "motivo")
    assert (r.bloqueado, r.motivo, r.incierto) == (True, "motivo", False)
    assert envios.ResultadoEnvio(False, None, incierto=True).incierto
    # valor para Mensaje.estado_envio (lo usarán main.py y los scripts)
    assert envios.ResultadoEnvio(True, "w").estado_envio is None
    assert envios.ResultadoEnvio(False, None, incierto=True).estado_envio == "incierto"
    assert envios.ResultadoEnvio(False, None).estado_envio == "fallido"
    assert envios.ResultadoEnvio(False, None, bloqueado=True).estado_envio == "fallido"


async def test_el_resumen_por_origen_cuenta_los_inciertos_aparte():
    nid, canal = await _negocio("sd-resumen")

    class Incierto:
        async def enviar_mensaje(self, *a, **k):
            raise EnvioIncierto("ReadTimeout")

    await envios.enviar_texto(Incierto(), TEL, "x", origen="gabi_respuesta", canal=canal)
    resumen = await mem.resumen_envios_por_origen(nid)
    [o] = [x for x in resumen["origenes"] if x["origen"] == "gabi_respuesta"]
    assert (o["enviados"], o["fallidos"], o["inciertos"], o["sin_estado"]) == (0, 0, 1, 0)


# ── Panel del asesor: estado_envio="incierto", no "fallido" ─────────────────

def test_estado_envio_guardado_distingue_enviado_incierto_y_fallido():
    assert dashboard._estado_envio_guardado(envios.ResultadoEnvio(True, "w")) is None
    assert dashboard._estado_envio_guardado(envios.ResultadoEnvio(False, None, incierto=True)) == "incierto"
    assert dashboard._estado_envio_guardado(envios.ResultadoEnvio(False, None)) == "fallido"
    assert len("incierto") <= mem.Mensaje.__table__.c.estado_envio.type.length
    assert len("incierto") <= mem.EnvioMeta.__table__.c.decision.type.length


def test_la_respuesta_incierta_no_es_un_error_http_para_que_el_panel_no_ofrezca_reintentar():
    r = dashboard._respuesta_envio_incierto(7)
    cuerpo = json.loads(r.body)
    assert r.status_code == 200 and cuerpo["status"] == "incierto" and cuerpo["estado_envio"] == "incierto" and cuerpo["mensaje_id"] == 7
    assert dashboard._respuesta_envio_fallido("x", 7).status_code == 502


@pytest.mark.parametrize("resultado,estado_esperado,status_http", [
    (envios.ResultadoEnvio(False, None, incierto=True), "incierto", 200),
    (envios.ResultadoEnvio(False, None), "fallido", 502),
    (envios.ResultadoEnvio(True, "wamid.OK"), None, 200),
])
async def test_responder_cliente_guarda_el_estado_correcto(monkeypatch, resultado, estado_esperado, status_http):
    guardados = []

    class ProveedorFalso:
        async def resolver_canal(self, numero_whatsapp_id, negocio_id=None):
            return {"phone_number_id": PHONE_ID}

    async def lead(telefono, negocio_id=None):
        return {"telefono": telefono, "numero_whatsapp_id": PHONE_ID}

    async def ventana(telefono):
        return None

    async def enviar_texto(*a, **k):
        return resultado

    async def guardar_mensaje(telefono, role, contenido, **kw):
        guardados.append(kw)
        return {"id": 5, "conversation_id": "c-1"}

    async def emitir(conversation_id):
        return None

    monkeypatch.setattr(dashboard, "obtener_lead", lead)
    monkeypatch.setattr(dashboard, "_verificar_acceso_lead", lambda usuario, lead: None)
    monkeypatch.setattr(dashboard, "_verificar_ventana_atencion", ventana)
    monkeypatch.setattr(dashboard, "obtener_proveedor", lambda: ProveedorFalso())
    monkeypatch.setattr(dashboard.envios, "enviar_texto", enviar_texto)
    monkeypatch.setattr(dashboard.servicio_conversacion, "guardar_mensaje", guardar_mensaje)
    monkeypatch.setattr(dashboard.gestor_conexiones, "emitir_mensaje_nuevo", emitir)

    r = await dashboard.responder_cliente(TEL, mensaje="hola", mensaje_id_citado=None, usuario={"negocio_id": "n1", "username": "a"}, _csrf=None)
    assert r.status_code == status_http
    assert guardados[0]["estado_envio"] == estado_esperado
    assert guardados[0]["mensaje_id_meta"] == resultado.wamid


# ── Informe de conciliación ─────────────────────────────────────────────────

async def test_el_informe_lista_inciertos_enviados_sin_wamid_y_uso_huerfano():
    nid, _ = await _negocio("sd-inf-1")
    otro, _ = await _negocio("sd-inf-2")
    ahora = datetime.utcnow()
    async with mem.async_session() as s:
        def envio(**kw):
            base = dict(negocio_id=nid, origen="gabi_respuesta", telefono=TEL, tipo="texto", decision="enviado", creado=ahora - timedelta(hours=1))
            return mem.EnvioMeta(**{**base, **kw})

        s.add_all([
            envio(decision="incierto", motivo="incierto: Meta respondió 502"),
            envio(decision="enviado", wamid=None, creado=ahora - timedelta(minutes=10)),    # abierta hace > 5 min
            envio(decision="enviado", wamid=None, creado=ahora - timedelta(minutes=1)),     # reciente: todavía en curso
            envio(decision="enviado", wamid="wamid.OK"),
            envio(decision="fallido"),
            envio(decision="incierto", negocio_id=otro),                                    # de otro negocio
            envio(decision="incierto", creado=ahora - timedelta(days=30)),                   # fuera del rango
            mem.Mensaje(telefono=TEL, role="asesor", content="x", timestamp=ahora, negocio_id=nid, mensaje_id_meta="wamid.EN_MENSAJES"),
        ])
        await s.commit()
    await _uso("wamid.OK", negocio_id=nid)
    await _uso("wamid.EN_MENSAJES", negocio_id=nid)
    await _uso("wamid.HUERFANO", negocio_id=nid, destinatario="51911111111")
    await _uso("wamid.HUERFANO_AJENO", negocio_id=otro)
    await _uso("wamid.HUERFANO_VIEJO", negocio_id=nid, enviado_en=ahora - timedelta(days=30), creado=ahora - timedelta(days=30))

    r = await mem.listar_envios_inciertos_o_huerfanos(nid, ahora - timedelta(days=7))
    assert sorted(e["decision"] for e in r["envios_inciertos"]) == ["enviado", "incierto"]
    assert [e["motivo"] for e in r["envios_inciertos"] if e["decision"] == "incierto"] == ["incierto: Meta respondió 502"]
    assert all(e["creado"].endswith("Z") for e in r["envios_inciertos"])
    assert [u["wamid"] for u in r["uso_sin_envio"]] == ["wamid.HUERFANO"]


async def test_la_ruta_de_conciliacion_es_get_solo_admin_y_valida_el_rango():
    rutas = [r for r in dashboard.router.routes if getattr(r, "path", "").endswith("/uso-mensajes/conciliacion.json")]
    assert len(rutas) == 1 and "GET" in rutas[0].methods
    # el candado de rol es una dependencia: solo "admin" (supervisor y asesor reciben 403)
    from fastapi import HTTPException

    candado = next(d.call for d in rutas[0].dependant.dependencies if d.call.__name__ == "_verificar")
    assert (await candado(usuario={"rol": "admin"}))["rol"] == "admin"
    for rol in ("supervisor", "asesor"):
        with pytest.raises(HTTPException) as e403:
            await candado(usuario={"rol": rol})
        assert e403.value.status_code == 403

    nid, _ = await _negocio("sd-ruta")
    admin = {"negocio_id": nid, "rol": "admin", "username": "a"}
    r = await dashboard.uso_mensajes_conciliacion_json(dias=7, usuario=admin)
    assert r.status_code == 200 and set(json.loads(r.body)) == {"desde", "envios_inciertos", "uso_sin_envio"}
    for malo in (0, 91):
        with pytest.raises(HTTPException) as e:
            await dashboard.uso_mensajes_conciliacion_json(dias=malo, usuario=admin)
        assert e.value.status_code == 400


def test_el_provider_ya_no_usa_reintentos_amplios_en_los_envios():
    """Los únicos POST a Meta con reintentos amplios son marcar leído y subir media
    (no crean un mensaje al cliente)."""
    from pathlib import Path

    texto = (Path(meta_provider.__file__)).read_text(encoding="utf-8")
    usos = [l.strip() for l in texto.splitlines() if "await post_con_reintentos(" in l]
    assert len(usos) == 2
    assert any("headers=headers, data=data, files=files" in l for l in usos)    # subir_media
    assert any('json=payload' in l for l in usos)                                # marcar_leido_y_escribiendo
