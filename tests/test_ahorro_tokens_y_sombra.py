# tests/test_ahorro_tokens_y_sombra.py — auditoría de tokens (2026-10-26): caché de 1 h en las instrucciones de Gabi,
# Haiku 5.5 sin razonamiento en las tareas cortas, y la respuesta "en sombra" con otro modelo (nunca enviada).

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from agent import brain, memory as mem, sombra_modelo


def _respuesta(texto="Hola", con_razonamiento=False):
    bloques = [SimpleNamespace(type="text", text=texto)]
    if con_razonamiento:
        bloques.insert(0, SimpleNamespace(type="thinking", thinking="", signature="x"))
    uso = SimpleNamespace(input_tokens=100, output_tokens=20, cache_read_input_tokens=0, cache_creation_input_tokens=0)
    return SimpleNamespace(content=bloques, usage=uso, stop_reason="end_turn")


async def _esperar_sombras():
    for _ in range(50):
        if not sombra_modelo._tareas:
            return
        await asyncio.sleep(0.02)


def test_el_texto_se_lee_por_tipo_aunque_venga_razonamiento_antes():
    assert brain.texto_de_respuesta(_respuesta("Listo", con_razonamiento=True)) == "Listo"
    assert brain.texto_de_respuesta(SimpleNamespace(content=[])) == ""


async def test_las_instrucciones_de_gabi_se_cachean_una_hora():
    with patch.object(brain.client.messages, "create", new=AsyncMock(return_value=_respuesta())) as mock:
        await brain.generar_respuesta("Hola", historial=[], modo="produccion", negocio_id=None)
    assert mock.await_args.kwargs["system"][0]["cache_control"] == {"type": "ephemeral", "ttl": "1h"}


async def test_la_extraccion_usa_haiku_5_5_sin_razonamiento():
    respuesta = _respuesta('{"nombre": "Ana", "interes": "terma", "producto_tipo": null, "producto_marca": null, '
                           '"producto_modalidad": null, "paso_flujo": "explorando"}', con_razonamiento=True)
    with patch.object(brain.client.messages, "create", new=AsyncMock(return_value=respuesta)) as mock:
        datos = await brain.extraer_datos_lead("Soy Ana", "Hola Ana", {})
    kwargs = mock.await_args.kwargs
    assert kwargs["model"] == "claude-haiku-5-5" and kwargs["thinking"] == {"type": "disabled"}
    assert "temperature" not in kwargs
    assert datos["nombre"] == "Ana"


async def test_sin_configuracion_no_hay_sombra():
    with patch.object(brain.client.messages, "create", new=AsyncMock(return_value=_respuesta())) as mock:
        await brain.generar_respuesta("Hola", historial=[], lead={"telefono": "51900000001"}, modo="produccion")
        await _esperar_sombras()
    assert mock.await_count == 1


async def test_con_sombra_se_genera_con_el_otro_modelo_y_se_guarda_sin_enviarla(monkeypatch):
    negocio = await mem.crear_negocio("Negocio Sombra", "sombra1")
    await mem.guardar_configuracion(sombra_modelo.CLAVE_MODELO_SOMBRA, "claude-haiku-5-5", negocio_id=negocio["id"])
    guardados = []

    async def registrar(telefono, tipo, descripcion, autor, payload=None):
        guardados.append({"telefono": telefono, "tipo": tipo, "payload": payload})
    monkeypatch.setattr(mem, "registrar_evento_lead", registrar)

    async def crear(**kwargs):
        return _respuesta("respuesta barata" if kwargs["model"] == "claude-haiku-5-5" else "respuesta real")

    with patch.object(brain.client.messages, "create", new=AsyncMock(side_effect=crear)) as mock:
        texto, error, _, _ = await brain.generar_respuesta(
            "Hola", historial=[], lead={"telefono": "51900000002"}, modo="produccion", negocio_id=negocio["id"],
        )
        await _esperar_sombras()

    assert texto == "respuesta real" and error is False           # al cliente le llega solo la real
    llamadas = [c.kwargs for c in mock.await_args_list]
    assert [c["model"] for c in llamadas] == [brain.MODELO_PRINCIPAL, "claude-haiku-5-5"]
    assert llamadas[1]["messages"] == llamadas[0]["messages"] and llamadas[1]["system"] == llamadas[0]["system"]
    assert llamadas[1]["thinking"] == {"type": "disabled"}
    [evento] = guardados
    assert evento["telefono"] == "51900000002" and evento["tipo"] == "sombra_modelo"
    assert evento["payload"]["respuesta_real"] == "respuesta real" and evento["payload"]["respuesta_sombra"] == "respuesta barata"
    assert evento["payload"]["modelo"] == "claude-haiku-5-5"
    assert "sombra_modelo" in mem.TIPOS_EVENTO_INTERNOS        # evento interno: no sale en el Timeline


async def test_si_la_sombra_falla_la_respuesta_real_no_se_entera():
    negocio = await mem.crear_negocio("Negocio Sombra 2", "sombra2")
    await mem.guardar_configuracion(sombra_modelo.CLAVE_MODELO_SOMBRA, "claude-haiku-5-5", negocio_id=negocio["id"])

    async def crear(**kwargs):
        if kwargs["model"] == "claude-haiku-5-5":
            raise RuntimeError("falla simulada")
        return _respuesta("respuesta real")

    with patch.object(brain.client.messages, "create", new=AsyncMock(side_effect=crear)):
        texto, error, _, _ = await brain.generar_respuesta(
            "Hola", historial=[], lead={"telefono": "51900000003"}, modo="produccion", negocio_id=negocio["id"],
        )
        await _esperar_sombras()
    assert texto == "respuesta real" and error is False


def test_el_resumen_de_la_sombra_compara_largo_costo_y_rechazos():
    from scripts.sombra_modelo import costo_estimado, resumir
    pares = [
        {"modelo": "claude-haiku-5-5", "respuesta_real": "x" * 300, "respuesta_sombra": "y" * 200, "stop_reason": "end_turn",
         "latencia_ms": 900, "tokens_in": 1500, "tokens_out": 120, "cache_read": 2600, "cache_write": 0},
        {"modelo": "claude-haiku-5-5", "respuesta_real": "x" * 100, "respuesta_sombra": "", "stop_reason": "refusal",
         "latencia_ms": 500, "tokens_in": 1500, "tokens_out": 0, "cache_read": 2600, "cache_write": 0},
    ]
    r = resumir(pares)
    assert r["respuestas"] == 2 and r["sombra_vacias_o_rechazadas"] == 1
    assert r["largo_real_mediana"] == 200 and r["stop_reasons"]["refusal"] == 1
    assert abs(costo_estimado("claude-haiku-5-5", pares[0]) - (1500 * 0.10 + 120 * 0.50 + 2600 * 0.01) / 1e6) < 1e-12
    assert costo_estimado("modelo-desconocido", pares[0]) is None
    assert resumir([]) == {"respuestas": 0}


async def test_si_haiku_5_5_no_esta_disponible_la_extraccion_vuelve_a_haiku_4_5():
    import httpx
    from anthropic import NotFoundError

    no_existe = NotFoundError("model not found", response=httpx.Response(404, request=httpx.Request("POST", "https://x")), body=None)
    respuesta = _respuesta('{"nombre": "Ana", "interes": null, "producto_tipo": null, "producto_marca": null, '
                           '"producto_modalidad": null, "paso_flujo": "derivado_asesor"}')

    async def crear(**kwargs):
        if kwargs["model"] == "claude-haiku-5-5":
            raise no_existe
        return respuesta

    with patch.object(brain.client.messages, "create", new=AsyncMock(side_effect=crear)) as mock:
        datos = await brain.extraer_datos_lead("Mi DNI es 12345678", "Te derivo con un asesor", {})
    assert [c.kwargs["model"] for c in mock.await_args_list] == ["claude-haiku-5-5", brain.MODELO_EXTRACCION_RESPALDO]
    assert "thinking" not in mock.await_args_list[1].kwargs
    assert datos["paso_flujo"] == "derivado_asesor"        # la derivación se sigue detectando


def test_turnos_que_no_necesitan_catalogo():
    t = brain.turno_sin_catalogo
    assert t("12345678") and t("  4501 2345 ") and t("Muchas gracias") and t("ok") and t("👍")
    assert not t("sí") and not t("no") and not t("¿cuánto cuesta?") and not t("quiero la de 10 litros")
    assert not t("Juan") and not t("123")           # un nombre o un número corto (capacidad, cuotas) sí puede necesitarlo


def test_las_cuotas_por_producto_solo_si_el_cliente_hablo_de_precio():
    from agent.tools import formatear_producto
    p = {"MARCA": "SOLE", "DESCRIPCIÓN": "TERMA SOLE 10 LT", "PRECIO": "699", "CANAL": "ALOC"}
    con = formatear_producto(p, 0.40, 0.18)
    sin = formatear_producto(p, 0.40, 0.18, con_cuotas=False)
    assert "Cuotas:" in con and "Cuotas:" not in sin and "S/ 699" in sin


async def test_sombra_con_dos_modelos_usa_el_razonamiento_que_acepta_cada_uno(monkeypatch):
    negocio = await mem.crear_negocio("Negocio Sombra 3", "sombra3")
    await mem.guardar_configuracion(
        sombra_modelo.CLAVE_MODELO_SOMBRA, "claude-haiku-5-5, claude-sonnet-5-5", negocio_id=negocio["id"],
    )
    guardados = []

    async def registrar(telefono, tipo, descripcion, autor, payload=None):
        guardados.append(payload["modelo"])
    monkeypatch.setattr(mem, "registrar_evento_lead", registrar)

    with patch.object(brain.client.messages, "create", new=AsyncMock(return_value=_respuesta("x"))) as mock:
        await brain.generar_respuesta("Hola", historial=[], lead={"telefono": "51900000004"}, modo="produccion",
                                      negocio_id=negocio["id"])
        await _esperar_sombras()
    razonamiento = {c.kwargs["model"]: c.kwargs.get("thinking") for c in mock.await_args_list}
    assert razonamiento["claude-haiku-5-5"] == {"type": "disabled"}
    assert razonamiento["claude-sonnet-5-5"] == {"type": "between_tools"}
    assert brain.MODELO_PRINCIPAL in razonamiento and sorted(guardados) == ["claude-haiku-5-5", "claude-sonnet-5-5"]
