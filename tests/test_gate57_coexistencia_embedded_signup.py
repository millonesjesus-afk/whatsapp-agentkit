# tests/test_gate57_coexistencia_embedded_signup.py — Gate 5.7, cierre del
# gap confirmado por la Auditoría Histórica de Coexistencia: el callback de
# Embedded Signup trataba TODO como Cloud API estándar (llamaba /register
# siempre), sin distinguir el caso real de Coexistencia (número que ya está
# en la app de WhatsApp Business del celular, ya registrado).
#
# Esta suite NO usa TestClient (no existe esa infraestructura en el
# proyecto, ver test_gate55_legacy_endpoints_cross_tenant.py) — llama la
# función del router directamente como una corrutina, con un Request falso
# y las funciones de HTTP a Meta (get_con_reintentos/post_con_reintentos)
# mockeadas vía monkeypatch. Ningún test acá es evidencia de funcionamiento
# real contra la API de Meta — solo prueban la lógica interna del callback.
# Datos sintéticos únicamente.

import asyncio
import logging

import pytest

from agent import memory as mem
from agent import dashboard


class _RespuestaFalsa:
    def __init__(self, status_code=200, payload=None, texto=""):
        self.status_code = status_code
        self._payload = payload or {}
        self.text = texto

    def json(self):
        return self._payload


class _RequestFalso:
    def __init__(self, payload: dict):
        self._payload = payload

    async def json(self):
        return self._payload


async def _negocio(codigo: str):
    return await mem.crear_negocio(f"Negocio {codigo}", codigo)


def _mock_http(monkeypatch, llamadas: list, respuesta_register=None, respuesta_sync=None,
                numeros_waba=None, respuesta_phone_numbers=None):
    """Registra en `llamadas` cada (url, json_enviado) de post_con_reintentos.
    Permite forzar respuestas específicas para /register y /smb_app_data.

    `numeros_waba`: lista de dicts que simula el `data` de
    `GET /{waba_id}/phone_numbers` (Coexistence Gap Analysis: resolución
    server-side de phone_number_id) — default 1 número sintético.
    `respuesta_phone_numbers`: para forzar una respuesta completa (error,
    vacía, etc.) en vez de construirla desde `numeros_waba`."""
    if numeros_waba is None:
        numeros_waba = [{"id": "90000000000"}]

    async def _get_fake(url, **kwargs):
        if "/phone_numbers" in url:
            return respuesta_phone_numbers or _RespuestaFalsa(200, {"data": numeros_waba})
        return _RespuestaFalsa(200, {"access_token": "token-falso-de-meta"})

    async def _post_fake(url, **kwargs):
        llamadas.append((url, kwargs.get("json")))
        if "/register" in url:
            return respuesta_register or _RespuestaFalsa(200, {})
        if "/smb_app_data" in url:
            return respuesta_sync or _RespuestaFalsa(200, {"request_id": "req-sintetico"})
        if "/subscribed_apps" in url:
            return _RespuestaFalsa(200, {})
        return _RespuestaFalsa(200, {})

    monkeypatch.setattr(dashboard, "get_con_reintentos", _get_fake)
    monkeypatch.setattr(dashboard, "post_con_reintentos", _post_fake)


def _payload_base(phone_number_id: str, es_coexistencia: bool) -> dict:
    return {
        "code": "code-de-meta-sintetico",
        "waba_id": "waba-sintetico-001",
        "phone_number_id": phone_number_id,
        "pin": "123456",
        "nombre": "Canal de prueba",
        "es_coexistencia": es_coexistencia,
    }


@pytest.fixture(autouse=True)
def _env_meta(monkeypatch):
    monkeypatch.setenv("META_APP_ID", "app-id-sintetico")
    monkeypatch.setenv("META_APP_SECRET", "app-secret-sintetico")


# ---------------------------------------------------------------------------
# Flujo estándar — regresión, debe seguir llamando /register igual que antes
# ---------------------------------------------------------------------------

async def test_flujo_estandar_llama_register_y_no_llama_smb_app_data(monkeypatch):
    negocio = await _negocio("g57-a")
    llamadas = []
    _mock_http(monkeypatch, llamadas)

    resultado = await dashboard.conectar_whatsapp_embedded_signup(
        request=_RequestFalso(_payload_base("80000000001", es_coexistencia=False)),
        usuario={"negocio_id": negocio["id"]},
        _csrf=None,
    )

    assert resultado.status_code == 200
    urls_llamadas = [u for u, _ in llamadas]
    assert any("/register" in u for u in urls_llamadas)
    assert not any("/smb_app_data" in u for u in urls_llamadas)


async def test_sin_es_coexistencia_en_el_payload_se_comporta_como_estandar(monkeypatch):
    """Compatibilidad hacia atrás explícita: si el campo no viene (cliente
    viejo, o algo lo omite), nunca debe interpretarse como Coexistencia por
    default — fail-closed hacia el camino ya validado en producción."""
    negocio = await _negocio("g57-b")
    llamadas = []
    _mock_http(monkeypatch, llamadas)
    payload = _payload_base("80000000002", es_coexistencia=False)
    del payload["es_coexistencia"]

    resultado = await dashboard.conectar_whatsapp_embedded_signup(
        request=_RequestFalso(payload), usuario={"negocio_id": negocio["id"]}, _csrf=None,
    )

    assert resultado.status_code == 200
    assert any("/register" in u for u, _ in llamadas)


# ---------------------------------------------------------------------------
# Flujo Coexistencia — el gap que este Gate cierra
# ---------------------------------------------------------------------------

async def test_coexistencia_no_llama_register_llama_smb_app_data_dos_veces(monkeypatch):
    negocio = await _negocio("g57-c")
    llamadas = []
    _mock_http(monkeypatch, llamadas, numeros_waba=[{"id": "80000000003"}])

    resultado = await dashboard.conectar_whatsapp_embedded_signup(
        request=_RequestFalso(_payload_base("80000000003", es_coexistencia=True)),
        usuario={"negocio_id": negocio["id"]},
        _csrf=None,
    )

    assert resultado.status_code == 200
    urls_llamadas = [u for u, _ in llamadas]
    assert not any("/register" in u for u in urls_llamadas)  # el punto central del fix
    llamadas_sync = [(u, j) for u, j in llamadas if "/smb_app_data" in u]
    assert len(llamadas_sync) == 2
    tipos_pedidos = {j["sync_type"] for _, j in llamadas_sync}
    assert tipos_pedidos == {"smb_app_state_sync", "history"}


async def test_coexistencia_sync_fallido_no_aborta_creacion_del_canal(monkeypatch):
    negocio = await _negocio("g57-d")
    llamadas = []
    _mock_http(monkeypatch, llamadas, respuesta_sync=_RespuestaFalsa(400, texto="rechazado"),
               numeros_waba=[{"id": "80000000004"}])

    resultado = await dashboard.conectar_whatsapp_embedded_signup(
        request=_RequestFalso(_payload_base("80000000004", es_coexistencia=True)),
        usuario={"negocio_id": negocio["id"]},
        _csrf=None,
    )

    assert resultado.status_code == 200
    canales = await mem.listar_canales_whatsapp(negocio_id=negocio["id"])
    assert any(c["phone_number_id"] == "80000000004" for c in canales)


async def test_coexistencia_state_sync_ok_history_2593109_ambas_se_intentan_igual(monkeypatch):
    """Caso asimétrico explícito de la auditoría final: state_sync funciona,
    history devuelve 2593109 — las dos llamadas deben intentarse igual (el
    loop no corta al primer fallo, cada tipo_sync es independiente), y el
    canal se crea de todos modos."""
    negocio = await _negocio("g57-i")
    llamadas = []

    async def _get_fake(url, **kwargs):
        if "/phone_numbers" in url:
            return _RespuestaFalsa(200, {"data": [{"id": "80000000009"}]})
        return _RespuestaFalsa(200, {"access_token": "token-falso-de-meta"})

    async def _post_fake(url, **kwargs):
        llamadas.append((url, kwargs.get("json")))
        if "/smb_app_data" in url:
            tipo = kwargs["json"]["sync_type"]
            if tipo == "smb_app_state_sync":
                return _RespuestaFalsa(200, {"request_id": "req-state-sync-ok"})
            return _RespuestaFalsa(400, payload={"error": {"code": 2593109}}, texto='{"error":{"code":2593109}}')
        return _RespuestaFalsa(200, {})

    monkeypatch.setattr(dashboard, "get_con_reintentos", _get_fake)
    monkeypatch.setattr(dashboard, "post_con_reintentos", _post_fake)

    resultado = await dashboard.conectar_whatsapp_embedded_signup(
        request=_RequestFalso(_payload_base("80000000009", es_coexistencia=True)),
        usuario={"negocio_id": negocio["id"]},
        _csrf=None,
    )

    assert resultado.status_code == 200
    llamadas_sync = [(u, j) for u, j in llamadas if "/smb_app_data" in u]
    assert len(llamadas_sync) == 2  # las dos se intentaron, ninguna canceló a la otra
    canales = await mem.listar_canales_whatsapp(negocio_id=negocio["id"])
    assert any(c["phone_number_id"] == "80000000009" for c in canales)


async def test_coexistencia_rechazo_historial_2593109_no_rompe_el_flujo(monkeypatch):
    """El código 2593109 (negocio declina compartir historial) es un estado
    terminal válido según Meta — no debe tratarse distinto de cualquier otro
    fallo no-200 de /smb_app_data: se loguea, no aborta la creación del
    canal (mismo camino que el test de sync fallido)."""
    negocio = await _negocio("g57-e")
    llamadas = []
    _mock_http(
        monkeypatch, llamadas,
        respuesta_sync=_RespuestaFalsa(400, payload={"error": {"code": 2593109}}, texto='{"error":{"code":2593109}}'),
        numeros_waba=[{"id": "80000000005"}],
    )

    resultado = await dashboard.conectar_whatsapp_embedded_signup(
        request=_RequestFalso(_payload_base("80000000005", es_coexistencia=True)),
        usuario={"negocio_id": negocio["id"]},
        _csrf=None,
    )

    assert resultado.status_code == 200
    canales = await mem.listar_canales_whatsapp(negocio_id=negocio["id"])
    assert any(c["phone_number_id"] == "80000000005" for c in canales)


# ---------------------------------------------------------------------------
# Idempotencia — doble ejecución / canal ya existente
# ---------------------------------------------------------------------------

async def test_canal_duplicado_devuelve_409_no_500(monkeypatch):
    negocio = await _negocio("g57-f")
    await mem.crear_canal_whatsapp(
        nombre="Ya conectado antes", phone_number_id="80000000006", negocio_id=negocio["id"],
    )
    llamadas = []
    _mock_http(monkeypatch, llamadas)

    resultado = await dashboard.conectar_whatsapp_embedded_signup(
        request=_RequestFalso(_payload_base("80000000006", es_coexistencia=False)),
        usuario={"negocio_id": negocio["id"]},
        _csrf=None,
    )

    assert resultado.status_code == 409
    canales = await mem.listar_canales_whatsapp(negocio_id=negocio["id"])
    assert len([c for c in canales if c["phone_number_id"] == "80000000006"]) == 1  # nunca 2


async def test_doble_ejecucion_coexistencia_tampoco_duplica_el_canal(monkeypatch):
    negocio = await _negocio("g57-g")
    llamadas = []
    _mock_http(monkeypatch, llamadas, numeros_waba=[{"id": "80000000007"}])
    payload = _payload_base("80000000007", es_coexistencia=True)

    primero = await dashboard.conectar_whatsapp_embedded_signup(
        request=_RequestFalso(payload), usuario={"negocio_id": negocio["id"]}, _csrf=None,
    )
    segundo = await dashboard.conectar_whatsapp_embedded_signup(
        request=_RequestFalso(payload), usuario={"negocio_id": negocio["id"]}, _csrf=None,
    )

    assert primero.status_code == 200
    assert segundo.status_code == 409
    canales = await mem.listar_canales_whatsapp(negocio_id=negocio["id"])
    assert len([c for c in canales if c["phone_number_id"] == "80000000007"]) == 1


async def test_doble_ejecucion_concurrente_real_nunca_duplica_el_canal(monkeypatch):
    """Auditoría final Gate 5.7 — a diferencia de los tests de arriba (secuenciales,
    primero termina y después arranca el segundo), esto ejercita una carrera
    REAL vía asyncio.gather, mismo patrón que probó la carrera de
    Contact/Conversation en Gate 5.5 (SQLite serializa escrituras a nivel de
    archivo, pero permite interleaving cooperativo real entre awaits dentro
    de un mismo proceso — alcanza para reproducir la carrera sin Postgres).
    Dos requests simultáneas para el MISMO phone_number_id (doble click real,
    o un reintento de red superpuesto con el request original) nunca deben
    producir dos filas de CanalWhatsApp ni un estado a medio escribir."""
    negocio = await _negocio("g57-h")
    llamadas = []
    _mock_http(monkeypatch, llamadas, numeros_waba=[{"id": "80000000008"}])
    payload = _payload_base("80000000008", es_coexistencia=True)

    resultados = await asyncio.gather(
        dashboard.conectar_whatsapp_embedded_signup(
            request=_RequestFalso(payload), usuario={"negocio_id": negocio["id"]}, _csrf=None,
        ),
        dashboard.conectar_whatsapp_embedded_signup(
            request=_RequestFalso(payload), usuario={"negocio_id": negocio["id"]}, _csrf=None,
        ),
        return_exceptions=True,
    )

    # Ninguna corrutina debe reventar con una excepción sin capturar (el
    # IntegrityError se maneja adentro de la función, nunca debería escapar).
    for r in resultados:
        assert not isinstance(r, Exception), f"excepción no capturada: {r!r}"

    codigos = sorted(r.status_code for r in resultados)
    assert codigos == [200, 409]  # exactamente un ganador, el otro rechazado — nunca los dos 200

    canales = await mem.listar_canales_whatsapp(negocio_id=negocio["id"])
    coincidencias = [c for c in canales if c["phone_number_id"] == "80000000008"]
    assert len(coincidencias) == 1  # nunca dos filas, ni un estado a medio escribir


# ---------------------------------------------------------------------------
# Coexistence Gap Analysis — resolución server-side de phone_number_id desde
# waba_id (Meta no lo entrega en FINISH_WHATSAPP_BUSINESS_APP_ONBOARDING).
# ---------------------------------------------------------------------------

async def test_coexistencia_sin_phone_number_id_en_payload_se_resuelve_igual(monkeypatch):
    """Caso real: el frontend nunca tiene phone_number_id para Coexistencia
    (Meta no lo manda en el evento) — el payload le llega vacío. No debe
    devolver 400 por 'faltan datos'; se resuelve server-side."""
    negocio = await _negocio("g57-j")
    llamadas = []
    _mock_http(monkeypatch, llamadas, numeros_waba=[{"id": "80000000010"}])
    payload = _payload_base("", es_coexistencia=True)

    resultado = await dashboard.conectar_whatsapp_embedded_signup(
        request=_RequestFalso(payload), usuario={"negocio_id": negocio["id"]}, _csrf=None,
    )

    assert resultado.status_code == 200
    canales = await mem.listar_canales_whatsapp(negocio_id=negocio["id"])
    assert any(c["phone_number_id"] == "80000000010" for c in canales)


async def test_coexistencia_ignora_phone_number_id_del_payload_si_viene(monkeypatch):
    """Nunca confiar en un phone_number_id que el cliente mande para
    Coexistencia, aunque venga (cliente viejo, o manipulado): el servidor
    siempre resuelve el suyo propio vía Graph API y ese es el que se usa."""
    negocio = await _negocio("g57-k")
    llamadas = []
    _mock_http(monkeypatch, llamadas, numeros_waba=[{"id": "80000000011"}])
    payload = _payload_base("99999999999", es_coexistencia=True)  # valor falso/ajeno

    resultado = await dashboard.conectar_whatsapp_embedded_signup(
        request=_RequestFalso(payload), usuario={"negocio_id": negocio["id"]}, _csrf=None,
    )

    assert resultado.status_code == 200
    canales = await mem.listar_canales_whatsapp(negocio_id=negocio["id"])
    assert any(c["phone_number_id"] == "80000000011" for c in canales)
    assert not any(c["phone_number_id"] == "99999999999" for c in canales)


async def test_coexistencia_waba_sin_numeros_rechazo_controlado(monkeypatch):
    negocio = await _negocio("g57-l")
    llamadas = []
    _mock_http(monkeypatch, llamadas, numeros_waba=[])
    payload = _payload_base("", es_coexistencia=True)

    resultado = await dashboard.conectar_whatsapp_embedded_signup(
        request=_RequestFalso(payload), usuario={"negocio_id": negocio["id"]}, _csrf=None,
    )

    assert resultado.status_code == 400
    canales = await mem.listar_canales_whatsapp(negocio_id=negocio["id"])
    assert canales == []


async def test_coexistencia_waba_con_varios_numeros_no_elige_arbitrariamente(monkeypatch):
    negocio = await _negocio("g57-m")
    llamadas = []
    _mock_http(monkeypatch, llamadas, numeros_waba=[{"id": "80000000012"}, {"id": "80000000013"}])
    payload = _payload_base("", es_coexistencia=True)

    resultado = await dashboard.conectar_whatsapp_embedded_signup(
        request=_RequestFalso(payload), usuario={"negocio_id": negocio["id"]}, _csrf=None,
    )

    assert resultado.status_code == 400
    canales = await mem.listar_canales_whatsapp(negocio_id=negocio["id"])
    assert canales == []


async def test_coexistencia_error_graph_api_al_resolver_no_crea_canal_incompleto(monkeypatch):
    negocio = await _negocio("g57-n")
    llamadas = []
    _mock_http(
        monkeypatch, llamadas,
        respuesta_phone_numbers=_RespuestaFalsa(400, texto="Graph API caída"),
    )
    payload = _payload_base("", es_coexistencia=True)

    resultado = await dashboard.conectar_whatsapp_embedded_signup(
        request=_RequestFalso(payload), usuario={"negocio_id": negocio["id"]}, _csrf=None,
    )

    assert resultado.status_code == 400
    canales = await mem.listar_canales_whatsapp(negocio_id=negocio["id"])
    assert canales == []


# ---------------------------------------------------------------------------
# Hardening de logging (auditoría de la implementación, hallazgo §6) — nunca
# volcar r.text crudo de una respuesta de error de Graph API al logger;
# allowlist de campos seguros (status/type/code/message/fbtrace_id), y
# truncamiento seguro cuando el cuerpo no es JSON reconocible.
# ---------------------------------------------------------------------------

async def test_log_error_meta_conserva_informacion_util_para_diagnostico(monkeypatch, caplog):
    negocio = await _negocio("g57-o")
    llamadas = []
    _mock_http(
        monkeypatch, llamadas,
        respuesta_phone_numbers=_RespuestaFalsa(
            400,
            payload={"error": {"type": "OAuthException", "code": 190,
                                "message": "Invalid OAuth access token", "fbtrace_id": "AbCdEfGhIjK"}},
        ),
    )
    payload = _payload_base("", es_coexistencia=True)

    with caplog.at_level(logging.ERROR):
        resultado = await dashboard.conectar_whatsapp_embedded_signup(
            request=_RequestFalso(payload), usuario={"negocio_id": negocio["id"]}, _csrf=None,
        )

    assert resultado.status_code == 400
    assert "400" in caplog.text
    assert "OAuthException" in caplog.text
    assert "190" in caplog.text
    assert "Invalid OAuth access token" in caplog.text
    assert "AbCdEfGhIjK" in caplog.text


async def test_log_error_meta_nunca_expone_access_token_authorization_ni_code(monkeypatch, caplog):
    """Dispara el error en el punto de resolución de phone_number_id y
    confirma que ninguno de los valores sensibles conocidos de este flujo
    — el access_token ya obtenido, el header Authorization, el code de
    intercambio ni el app_secret — aparece nunca en el log."""
    negocio = await _negocio("g57-p")
    llamadas = []
    _mock_http(
        monkeypatch, llamadas,
        respuesta_phone_numbers=_RespuestaFalsa(
            400, payload={"error": {"type": "OAuthException", "code": 190, "message": "token inválido"}},
        ),
    )
    payload = _payload_base("", es_coexistencia=True)
    payload["code"] = "code-de-meta-sintetico-secreto"

    with caplog.at_level(logging.ERROR):
        resultado = await dashboard.conectar_whatsapp_embedded_signup(
            request=_RequestFalso(payload), usuario={"negocio_id": negocio["id"]}, _csrf=None,
        )

    assert resultado.status_code == 400
    assert "token-falso-de-meta" not in caplog.text  # el access_token obtenido
    assert "Authorization" not in caplog.text
    assert "Bearer" not in caplog.text
    assert "code-de-meta-sintetico-secreto" not in caplog.text  # el code de intercambio
    assert "app-secret-sintetico" not in caplog.text  # META_APP_SECRET


async def test_log_error_intercambio_code_tampoco_expone_secretos(monkeypatch, caplog):
    """Mismo chequeo, disparando el fallo en el punto de intercambio de code
    (antes de obtener access_token), con un cuerpo de error NO-JSON para
    ejercitar la ruta de truncamiento — nunca debe filtrarse el app_secret
    ni el code de la request, sin importar qué devuelva Meta en el cuerpo."""
    negocio = await _negocio("g57-q")

    async def _get_fake(url, **kwargs):
        return _RespuestaFalsa(400, texto="Bad Request: the authorization code has expired or is invalid.")

    monkeypatch.setattr(dashboard, "get_con_reintentos", _get_fake)
    payload = _payload_base("", es_coexistencia=True)
    payload["code"] = "code-de-meta-sintetico-secreto"

    with caplog.at_level(logging.ERROR):
        resultado = await dashboard.conectar_whatsapp_embedded_signup(
            request=_RequestFalso(payload), usuario={"negocio_id": negocio["id"]}, _csrf=None,
        )

    assert resultado.status_code == 400
    assert "code-de-meta-sintetico-secreto" not in caplog.text
    assert "app-secret-sintetico" not in caplog.text
    assert "Authorization" not in caplog.text
    assert "Bearer" not in caplog.text


async def test_log_error_no_json_se_trunca_a_un_tamano_razonable(monkeypatch, caplog):
    negocio = await _negocio("g57-r")
    texto_enorme = "x" * 5000

    async def _get_fake(url, **kwargs):
        if "/phone_numbers" in url:
            return _RespuestaFalsa(400, texto=texto_enorme)
        return _RespuestaFalsa(200, {"access_token": "token-falso-de-meta"})

    monkeypatch.setattr(dashboard, "get_con_reintentos", _get_fake)
    payload = _payload_base("", es_coexistencia=True)

    with caplog.at_level(logging.ERROR):
        resultado = await dashboard.conectar_whatsapp_embedded_signup(
            request=_RequestFalso(payload), usuario={"negocio_id": negocio["id"]}, _csrf=None,
        )

    assert resultado.status_code == 400
    assert texto_enorme not in caplog.text  # nunca el cuerpo completo sin límite
    mensajes = [r.getMessage() for r in caplog.records if "resolver phone_number_id" in r.getMessage()]
    assert len(mensajes) == 1
    assert len(mensajes[0]) < len(texto_enorme)
    assert dashboard._LIMITE_TRUNCADO_LOG_META == 300


async def test_resolucion_phone_number_id_comportamiento_sin_cambios_tras_hardening(monkeypatch):
    """Confirma explícitamente, más allá de la suite ya existente, que el
    hardening de logging no alteró el comportamiento funcional de
    _resolver_phone_number_id_desde_waba en el camino exitoso."""
    async def _get_fake(url, **kwargs):
        assert "/phone_numbers" in url
        return _RespuestaFalsa(200, {"data": [{"id": "80000000014"}]})

    monkeypatch.setattr(dashboard, "get_con_reintentos", _get_fake)

    resultado, error = await dashboard._resolver_phone_number_id_desde_waba(
        "waba-x", {"Authorization": "Bearer x"}, "v21.0",
    )

    assert resultado == "80000000014"
    assert error is None
