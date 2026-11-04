# tests/test_mix_haiku_y_modelo_principal.py — Sonnet 5.5 como modelo principal y mix Haiku → principal (2026-11-03).
#
# Auditoría de la sombra (147 respuestas): Haiku 5.5 sale ~22 veces más barato pero en 6 situaciones cometió 3 errores que una regla
# simple detecta (afirmar un DNI que no llegó, dar un precio que nadie pidió, ofrecer ductería para una secadora). El mix deja que
# Haiku responda solo si una revisión sin IA lo aprueba; si no, responde el modelo principal.
import asyncio
import os

os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")
os.environ.setdefault("WHATSAPP_PROVIDER", "meta")

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from anthropic import NotFoundError

from agent import brain, memory as mem, mix_haiku
from agent import sombra_modelo
from scripts import modelo_gabi

PEDIDO_NORMAL = dict(mensajes_cliente=["Quiero una secadora"], pidio_precio=False, tipo_producto="secadora", contexto="")


def _respuesta(texto="Hola", stop="end_turn", tin=100, tout=20):
    uso = SimpleNamespace(input_tokens=tin, output_tokens=tout, cache_read_input_tokens=0, cache_creation_input_tokens=0)
    return SimpleNamespace(content=[SimpleNamespace(text=texto)], usage=uso, stop_reason=stop)


async def _esperar_tareas():
    for _ in range(100):
        if not mix_haiku._tareas and not sombra_modelo._tareas:
            return
        await asyncio.sleep(0.02)


# ── La revisión (pura) ──────────────────────────────────────────────────────

def test_una_respuesta_normal_pasa():
    assert mix_haiku.revisar("Perfecto. ¿Me das el DNI del titular (8 dígitos)?", **PEDIDO_NORMAL) == []


def test_afirmar_un_dni_que_no_llego_se_rechaza_y_con_el_dni_escrito_pasa():
    texto = "Gracias. Ya tengo tu DNI. Un asesor continuará la evaluación desde mañana."
    assert "afirma_dato_que_no_llego" in mix_haiku.revisar(texto, **PEDIDO_NORMAL)
    assert mix_haiku.revisar(texto, **{**PEDIDO_NORMAL, "mensajes_cliente": ["secadora", "mi dni es 45781236"]}) == []
    assert mix_haiku.revisar(texto, **{**PEDIDO_NORMAL, "mensajes_cliente": ["secadora", "45 781 236"]}) == []
    # un número de otra longitud no cuenta como DNI
    assert "afirma_dato_que_no_llego" in mix_haiku.revisar(texto, **{**PEDIDO_NORMAL, "mensajes_cliente": ["somos 5", "123456"]})


def test_un_precio_que_nadie_pidio_se_rechaza_y_si_lo_pidio_pasa():
    texto = "La secadora de 22 kg (MABE, S/ 2,999) es la que mejor se adapta."
    assert "precio_que_nadie_pidio" in mix_haiku.revisar(texto, **PEDIDO_NORMAL)
    assert "precio_que_nadie_pidio" not in mix_haiku.revisar(texto, **{**PEDIDO_NORMAL, "pidio_precio": True})
    assert "precio_que_nadie_pidio" in mix_haiku.revisar("Cuesta 3500 soles", **PEDIDO_NORMAL)


def test_la_ducteria_solo_va_con_terma():
    texto = "Como no tienes punto de gas, también puedes solicitar un punto adicional o una ductería como servicio aparte."
    assert "ducteria_sin_terma" in mix_haiku.revisar(texto, **PEDIDO_NORMAL)
    assert "ducteria_sin_terma" not in mix_haiku.revisar(texto, **{**PEDIDO_NORMAL, "tipo_producto": "terma"})
    assert "ducteria_sin_terma" not in mix_haiku.revisar(texto, **{**PEDIDO_NORMAL, "tipo_producto": "otro"})   # producto desconocido: no se adivina


def test_muy_larga_muletilla_y_cortes():
    assert "muy_larga" in mix_haiku.revisar("a" * (mix_haiku.LARGO_MAXIMO + 1), **PEDIDO_NORMAL)
    assert "anuncia_pregunta" in mix_haiku.revisar("Listo. Te hago una consulta rápida para orientarte mejor", **PEDIDO_NORMAL)
    assert mix_haiku.revisar("", **PEDIDO_NORMAL) == ["vacia"]
    assert "corte_max_tokens" in mix_haiku.revisar("Texto cortado", stop_reason="max_tokens", **PEDIDO_NORMAL)


def test_las_capacidades_deben_existir_en_lo_que_vio_el_modelo():
    contexto = "Catálogo: Secadora MABE 22 kg. Guía: terma de 5,5 a 10 litros por minuto."
    pedido = {**PEDIDO_NORMAL, "contexto": contexto}
    assert mix_haiku.revisar("Te sirve la secadora de 22 kg.", **pedido) == []
    assert mix_haiku.revisar("Una terma de 5.5 litros cubre bien.", **pedido) == []
    assert mix_haiku.revisar("Te sirve la secadora de 17 kg.", **pedido) == ["capacidad_sin_respaldo_17"]
    assert mix_haiku.revisar("Una secadora de 17 kg.", **PEDIDO_NORMAL) == []       # sin contexto no se puede comprobar


# ── El modelo principal ─────────────────────────────────────────────────────

def test_el_modelo_principal_por_defecto_es_sonnet_5_5_y_el_anterior_sigue_disponible():
    assert brain.MODELO_PRINCIPAL == "claude-sonnet-5-5" and brain.MODELO_PRINCIPAL_ANTERIOR == "claude-sonnet-4-6"


async def test_por_defecto_responde_sonnet_5_5_con_between_tools():
    with patch.object(brain.client.messages, "create", new=AsyncMock(return_value=_respuesta("Hola"))) as mock:
        texto, error, _, _ = await brain.generar_respuesta("Hola", historial=[], modo="produccion", negocio_id=None)
    kwargs = mock.await_args.kwargs
    assert texto == "Hola" and error is False and mock.await_count == 1
    assert kwargs["model"] == "claude-sonnet-5-5" and kwargs["thinking"] == {"type": "between_tools"}


async def test_se_vuelve_al_modelo_anterior_con_la_configuracion_y_sin_el_parametro_de_razonamiento():
    negocio = await mem.crear_negocio("Negocio mix-ant", "mix-ant")
    await mem.guardar_configuracion(brain.CLAVE_MODELO_PRINCIPAL, "claude-sonnet-4-6", negocio_id=negocio["id"])
    with patch.object(brain.client.messages, "create", new=AsyncMock(return_value=_respuesta())) as mock:
        await brain.generar_respuesta("Hola", historial=[], modo="produccion", negocio_id=negocio["id"])
    kwargs = mock.await_args.kwargs
    assert kwargs["model"] == "claude-sonnet-4-6" and "thinking" not in kwargs


async def test_un_valor_invalido_en_la_configuracion_cae_al_modelo_por_defecto():
    negocio = await mem.crear_negocio("Negocio mix-inv", "mix-inv")
    await mem.guardar_configuracion(brain.CLAVE_MODELO_PRINCIPAL, "gpt-9", negocio_id=negocio["id"])
    assert await brain.modelo_principal(negocio["id"]) == "claude-sonnet-5-5"


async def test_si_5_5_no_esta_disponible_responde_el_anterior_en_vez_de_dejar_al_cliente_sin_respuesta():
    llamadas = []

    async def crear(**kwargs):
        llamadas.append(kwargs["model"])
        if kwargs["model"] == "claude-sonnet-5-5":
            raise NotFoundError("no hay modelo", response=SimpleNamespace(status_code=404, headers={}, request=None), body=None)
        return _respuesta("respuesta del anterior")

    with patch.object(brain.client.messages, "create", new=AsyncMock(side_effect=crear)):
        texto, error, _, _ = await brain.generar_respuesta("Hola", historial=[], modo="produccion", negocio_id=None)
    assert texto == "respuesta del anterior" and error is False and llamadas == ["claude-sonnet-5-5", "claude-sonnet-4-6"]


# ── El mix ──────────────────────────────────────────────────────────────────

async def _negocio_con_mix(codigo: str, modo: str | None):
    negocio = await mem.crear_negocio(f"Negocio {codigo}", codigo)
    if modo is not None:
        await mem.guardar_configuracion(mix_haiku.CLAVE_MODO, modo, negocio_id=negocio["id"])
    return negocio


async def test_apagado_por_defecto_no_se_llama_a_haiku():
    negocio = await _negocio_con_mix("mix-off", None)
    with patch.object(brain.client.messages, "create", new=AsyncMock(return_value=_respuesta("principal"))) as mock:
        texto, _, _, _ = await brain.generar_respuesta("Hola", historial=[], modo="produccion", negocio_id=negocio["id"])
        await _esperar_tareas()
    assert texto == "principal" and [c.kwargs["model"] for c in mock.await_args_list] == ["claude-sonnet-5-5"]


async def test_activo_si_la_revision_aprueba_responde_haiku_y_el_principal_no_se_llama():
    negocio = await _negocio_con_mix("mix-on-ok", "activo")
    with patch.object(brain.client.messages, "create", new=AsyncMock(return_value=_respuesta("Perfecto. ¿Me das el DNI del titular?"))) as mock:
        texto, error, _, _ = await brain.generar_respuesta("Quiero una secadora", historial=[], modo="produccion", negocio_id=negocio["id"])
    assert texto == "Perfecto. ¿Me das el DNI del titular?" and error is False
    [llamada] = mock.await_args_list
    assert llamada.kwargs["model"] == "claude-haiku-5-5" and llamada.kwargs["thinking"] == {"type": "disabled"}


async def test_activo_si_la_revision_rechaza_se_regenera_con_el_principal_y_el_cliente_no_ve_lo_de_haiku():
    negocio = await _negocio_con_mix("mix-on-mal", "activo")

    async def crear(**kwargs):
        if kwargs["model"] == "claude-haiku-5-5":
            return _respuesta("Gracias. Ya tengo tu DNI. Un asesor continuará mañana.")
        return _respuesta("Pásame el DNI del titular (8 dígitos) para iniciar tu evaluación.")

    with patch.object(brain.client.messages, "create", new=AsyncMock(side_effect=crear)) as mock:
        texto, error, _, _ = await brain.generar_respuesta("Quiero una secadora", historial=[], modo="produccion", negocio_id=negocio["id"])
    assert texto == "Pásame el DNI del titular (8 dígitos) para iniciar tu evaluación." and error is False
    assert [c.kwargs["model"] for c in mock.await_args_list] == ["claude-haiku-5-5", "claude-sonnet-5-5"]


async def test_activo_si_haiku_falla_responde_el_principal():
    negocio = await _negocio_con_mix("mix-on-fallo", "activo")

    async def crear(**kwargs):
        if kwargs["model"] == "claude-haiku-5-5":
            raise RuntimeError("Haiku caído")
        return _respuesta("respuesta del principal")

    with patch.object(brain.client.messages, "create", new=AsyncMock(side_effect=crear)):
        texto, error, _, _ = await brain.generar_respuesta("Hola", historial=[], modo="produccion", negocio_id=negocio["id"])
    assert texto == "respuesta del principal" and error is False


async def test_observacion_el_cliente_recibe_la_del_principal_y_se_guarda_que_habria_hecho_el_mix(monkeypatch):
    negocio = await _negocio_con_mix("mix-obs", "observacion")
    guardados = []

    async def registrar(telefono, tipo, descripcion, autor, payload=None):
        guardados.append({"telefono": telefono, "tipo": tipo, "descripcion": descripcion, "payload": payload})
    monkeypatch.setattr(mem, "registrar_evento_lead", registrar)

    async def crear(**kwargs):
        if kwargs["model"] == "claude-haiku-5-5":
            return _respuesta("La secadora cuesta S/ 2,999. Ya tengo tu DNI.", tin=1000, tout=60)
        return _respuesta("respuesta real")

    with patch.object(brain.client.messages, "create", new=AsyncMock(side_effect=crear)):
        texto, error, _, _ = await brain.generar_respuesta(
            "Quiero una secadora", historial=[], lead={"telefono": "51900000077", "interes": "secadora"}, modo="produccion", negocio_id=negocio["id"],
        )
        await _esperar_tareas()
    assert texto == "respuesta real" and error is False
    [evento] = [g for g in guardados if g["tipo"] == "mix_haiku"]
    p = evento["payload"]
    assert p["aprobada"] is False and {"precio_que_nadie_pidio", "afirma_dato_que_no_llego"} <= set(p["motivos"])
    assert p["respuesta_real"] == "respuesta real" and "S/ 2,999" in p["respuesta_haiku"] and p["tokens_in"] == 1000
    assert len(evento["descripcion"]) <= 300


def test_el_tipo_de_evento_cabe_en_la_columna_y_es_interno():
    assert mem.EVENTO_MIX_HAIKU == "mix_haiku" and len(mem.EVENTO_MIX_HAIKU) <= 30
    assert mem.EVENTO_MIX_HAIKU in mem.TIPOS_EVENTO_INTERNOS          # nunca sale en el Timeline del asesor


# ── El script de la consola ─────────────────────────────────────────────────

def test_el_resumen_estima_el_costo_y_el_ahorro_del_mix():
    haiku = {"modelo": "claude-haiku-5-5", "tokens_in": 1000, "tokens_out": 100, "cache_read": 0, "cache_write": 0}
    payloads = [{**haiku, "aprobada": True, "motivos": []} for _ in range(3)] + [
        {**haiku, "aprobada": False, "motivos": ["precio_que_nadie_pidio", "capacidad_sin_respaldo_17"]},
    ]
    r = modelo_gabi.resumir_mix(payloads, costo_principal=0.0100)
    assert r["respuestas"] == 4 and r["aprobadas"] == 3 and r["aprobadas_pct"] == 75.0
    assert r["motivos_de_rechazo"] == {"precio_que_nadie_pidio": 1, "capacidad_sin_respaldo": 1}
    assert r["costo_haiku_promedio_usd"] == 0.00015 and r["costo_mix_estimado_usd"] == 0.00265   # 0.00015 + 25 % × 0.0100
    assert r["ahorro_estimado_pct"] == 73.5
    assert modelo_gabi.resumir_mix([]) == {"respuestas": 0}


async def test_el_script_cambia_y_muestra_la_configuracion():
    negocio = await mem.crear_negocio("Negocio mix-script", "mix-script")
    r = await modelo_gabi.main(["--negocio-id", negocio["id"]])
    assert r["principal"] == "claude-sonnet-5-5" and r["mix"] == "apagado"
    r = await modelo_gabi.main(["--negocio-id", negocio["id"], "--principal", "claude-sonnet-4-6", "--mix", "observacion", "--resumen"])
    assert r["principal"] == "claude-sonnet-4-6" and r["mix"] == "observacion" and r["resumen"] == {"respuestas": 0}
    with pytest.raises(SystemExit):
        await modelo_gabi.main(["--negocio-id", negocio["id"], "--principal", "gpt-9"])


# ── Turnos delicados: nunca los responde Haiku (2026-11-04) ─────────────────

@pytest.mark.parametrize("mensajes,esperado", [
    (["Hola", "somos 5 personas"], []),
    (["Estoy interesado en financiar una Terma"], []),            # «interesado» no es una pregunta por intereses: casi todos los anuncios lo dicen
    (["me interesa una cocina"], []),
    (["quiero una terma de 2 baños"], []),
    (["Deseo hacer un reclamo"], ["atencion_al_cliente"]),
    (["no me llega el recibo"], ["atencion_al_cliente"]),
    (["quiero cambiar el titular del suministro"], ["atencion_al_cliente"]),
    (["en cuántas cuotas puedo pagar"], ["precio_o_cuotas"]),
    (["¿cuál es el interés?"], ["precio_o_cuotas"]),
    (["huele a gas en mi cocina"], ["emergencia_de_gas"]),
])
def test_turno_delicado_por_lo_que_escribio_el_cliente(mensajes, esperado):
    r = mix_haiku.turno_delicado(mensajes_cliente=mensajes)
    assert [m for m in esperado if m in r] == esperado and (not esperado or r) and (esperado or r == [])


def test_turno_delicado_en_la_etapa_final_o_si_ya_pidio_precio():
    assert mix_haiku.turno_delicado(mensajes_cliente=["2 baños"], contexto="... ETAPA FINAL de la calificación. En UN solo mensaje ...") == ["etapa_final"]
    assert mix_haiku.turno_delicado(mensajes_cliente=["ok"], pidio_precio=True) == ["pidio_precio"]


async def test_activo_en_un_turno_delicado_no_se_llama_a_haiku_y_responde_el_principal():
    negocio = await _negocio_con_mix("mix-delicado", "activo")
    with patch.object(brain.client.messages, "create", new=AsyncMock(return_value=_respuesta("Para reclamos llama al 614-9000 opción 5."))) as mock:
        texto, error, _, _ = await brain.generar_respuesta("Deseo hacer un reclamo", historial=[], modo="produccion", negocio_id=negocio["id"])
    assert texto == "Para reclamos llama al 614-9000 opción 5." and error is False
    assert [c.kwargs["model"] for c in mock.await_args_list] == ["claude-sonnet-5-5"]        # Haiku ni se llamó


async def test_observacion_marca_el_turno_delicado_en_el_evento(monkeypatch):
    negocio = await _negocio_con_mix("mix-obs-del", "observacion")
    guardados = []

    async def registrar(telefono, tipo, descripcion, autor, payload=None):
        guardados.append({"tipo": tipo, "payload": payload})
    monkeypatch.setattr(mem, "registrar_evento_lead", registrar)
    with patch.object(brain.client.messages, "create", new=AsyncMock(return_value=_respuesta("Pásame el DNI."))):
        await brain.generar_respuesta(
            "en cuántas cuotas puedo pagar", historial=[], lead={"telefono": "51900000088"}, modo="produccion", negocio_id=negocio["id"],
        )
        await _esperar_tareas()
    [evento] = [g for g in guardados if g["tipo"] == "mix_haiku"]
    assert evento["payload"]["delicado"] == ["pidio_precio"]       # «cuotas» cuenta como pedir precio (calificacion_guiada.pidio_precio)


def test_el_resumen_separa_los_delicados_del_porcentaje_de_aprobacion_y_los_cobra_al_principal():
    haiku = {"modelo": "claude-haiku-5-5", "tokens_in": 1000, "tokens_out": 100, "cache_read": 0, "cache_write": 0}
    payloads = (
        [{**haiku, "aprobada": True, "motivos": [], "delicado": []} for _ in range(3)]
        + [{**haiku, "aprobada": False, "motivos": ["muy_larga"], "delicado": []}]
        + [{**haiku, "aprobada": True, "motivos": [], "delicado": ["etapa_final"]} for _ in range(4)]
    )
    r = modelo_gabi.resumir_mix(payloads, costo_principal=0.0100)
    assert r["respuestas"] == 8 and r["delicados"] == 4 and r["delicados_pct"] == 50.0
    assert r["revisadas"] == 4 and r["aprobadas"] == 3 and r["aprobadas_pct"] == 75.0
    # simples: 0.00015 + 25 % × 0.0100 = 0.00265; delicados: 0.0100 → mitad y mitad
    assert r["costo_mix_estimado_usd"] == 0.00632 and r["ahorro_estimado_pct"] == 36.8
    assert modelo_gabi.resumir_mix([{**haiku, "aprobada": True, "delicado": ["etapa_final"]}]) == {"respuestas": 1, "delicados": 1, "delicados_pct": 100.0}


# ── Llaves sin reemplazar (2026-11-04) ──────────────────────────────────────

@pytest.mark.parametrize("texto", [
    "Gracias por confirmar, {nombre}. Para tu casa te sirve la terma.",     # el caso real hallado en la sombra de Haiku
    "Hola {{nombre}}, ¿me das tu DNI?", "Listo { nombre }", "Con {producto} cubres tu necesidad.",
])
def test_una_respuesta_con_llaves_sin_reemplazar_se_rechaza(texto):
    assert "llaves_sin_reemplazar" in mix_haiku.revisar(texto, **PEDIDO_NORMAL)


@pytest.mark.parametrize("texto", [
    "Gracias, Oswaldo. ¿Me das el DNI del titular (8 dígitos)?", "Hasta 4 personas (secadora de 10 kg).",
    "Opciones: [1] terma, [2] cocina", "Tu código es {} de ejemplo",       # llaves vacías o con otro contenido no son un campo sin reemplazar
])
def test_el_texto_normal_no_se_rechaza_por_llaves(texto):
    assert "llaves_sin_reemplazar" not in mix_haiku.revisar(texto, **PEDIDO_NORMAL)
