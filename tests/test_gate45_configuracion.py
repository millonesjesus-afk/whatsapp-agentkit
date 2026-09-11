# tests/test_gate45_configuracion.py — Gate 4.5, Configuración UX
# (Negocio/Gabi/Horarios/Canales). Cobertura: escritura de cada sección,
# aislamiento multi-tenant (Negocio A nunca lee/modifica Negocio B),
# validaciones server-side de horario, y ausencia de secretos en
# GET /dashboard/configuracion.json.

from fastapi import HTTPException

from agent import dashboard, memory as mem


class _RequestFalso:
    def __init__(self, payload: dict):
        self._payload = payload

    async def json(self):
        return self._payload


async def _negocio_con_identidad(sufijo: str):
    negocio = await mem.crear_negocio(f"Negocio {sufijo}", f"g45{sufijo.lower()}")
    identidad = await mem.crear_o_actualizar_identidad_agente(
        negocio["id"], nombre=f"Gabi {sufijo}", tono="Cercano y profesional",
        configuracion_negocio=f"Eres Gabi de {sufijo}.\n\n## Tu identidad\n- Te llamas Gabi {sufijo}.\n",
    )
    return negocio, identidad


# ---------------------------------------------------------------------------
# Negocio
# ---------------------------------------------------------------------------

async def test_actualizar_negocio_cambia_solo_el_propio():
    negocio_a = await mem.crear_negocio("Negocio A", "g45neg-a")
    negocio_b = await mem.crear_negocio("Negocio B", "g45neg-b")

    actualizado = await mem.actualizar_negocio(negocio_a["id"], "Nombre Nuevo A")
    assert actualizado["nombre"] == "Nombre Nuevo A"

    intacto_b = await mem.obtener_negocio(negocio_b["id"])
    assert intacto_b["nombre"] == "Negocio B"


async def test_actualizar_negocio_no_toca_codigo_ni_activo():
    negocio = await mem.crear_negocio("Negocio Original", "g45neg-codigo")
    actualizado = await mem.actualizar_negocio(negocio["id"], "Nombre Cambiado")
    assert actualizado["codigo"] == "g45neg-codigo"
    assert actualizado["activo"] is True


async def test_actualizar_negocio_inexistente_devuelve_none():
    assert await mem.actualizar_negocio("00000000-0000-0000-0000-000000000000", "X") is None


async def test_ruta_negocio_rechaza_nombre_vacio():
    usuario = {"negocio_id": "cualquiera"}
    request = _RequestFalso({"nombre": "   "})
    try:
        await dashboard.actualizar_negocio_ruta(request, usuario=usuario, _csrf=None)
        assert False, "debía lanzar HTTPException"
    except HTTPException as e:
        assert e.status_code == 400


async def test_ruta_negocio_ok_devuelve_negocio_actualizado():
    negocio = await mem.crear_negocio("Negocio Ruta", "g45neg-ruta")
    usuario = {"negocio_id": negocio["id"]}
    request = _RequestFalso({"nombre": "Nombre Vía Ruta"})
    respuesta = await dashboard.actualizar_negocio_ruta(request, usuario=usuario, _csrf=None)
    import json as _json
    cuerpo = _json.loads(respuesta.body)
    assert cuerpo["ok"] is True
    assert cuerpo["negocio"]["nombre"] == "Nombre Vía Ruta"


# ---------------------------------------------------------------------------
# Gabi — solo nombre/tono, configuracion_negocio nunca se toca desde acá
# ---------------------------------------------------------------------------

async def test_actualizar_gabi_no_borra_configuracion_negocio():
    negocio, identidad = await _negocio_con_identidad("GabiEdit")
    usuario = {"negocio_id": negocio["id"]}
    request = _RequestFalso({"nombre": "Gabi Nuevo Nombre", "tono": "Directo y resolutivo"})

    respuesta = await dashboard.actualizar_gabi_ruta(request, usuario=usuario, _csrf=None)
    import json as _json
    cuerpo = _json.loads(respuesta.body)
    assert cuerpo["gabi"]["nombre"] == "Gabi Nuevo Nombre"
    assert cuerpo["gabi"]["tono"] == "Directo y resolutivo"

    # El texto real del prompt (configuracion_negocio) sigue intacto — esta
    # ruta nunca lo toca, ni lo expone en la respuesta.
    actual = await mem.obtener_identidad_agente(negocio["id"])
    assert actual["configuracion_negocio"] == identidad["configuracion_negocio"]
    assert "configuracion_negocio" not in cuerpo["gabi"]
    assert "usa_patron_estructural" not in cuerpo["gabi"]


async def test_actualizar_gabi_de_A_no_afecta_a_B():
    negocio_a, _ = await _negocio_con_identidad("GabiA")
    negocio_b, identidad_b = await _negocio_con_identidad("GabiB")

    request = _RequestFalso({"nombre": "Gabi Solo A", "tono": "Cercano"})
    await dashboard.actualizar_gabi_ruta(request, usuario={"negocio_id": negocio_a["id"]}, _csrf=None)

    intacta_b = await mem.obtener_identidad_agente(negocio_b["id"])
    assert intacta_b["nombre"] == identidad_b["nombre"]
    assert intacta_b["tono"] == identidad_b["tono"]


async def test_actualizar_gabi_sin_identidad_previa_da_404():
    negocio = await mem.crear_negocio("Negocio Sin Gabi", "g45neg-sin-gabi")
    request = _RequestFalso({"nombre": "X", "tono": "Y"})
    try:
        await dashboard.actualizar_gabi_ruta(request, usuario={"negocio_id": negocio["id"]}, _csrf=None)
        assert False, "debía lanzar HTTPException"
    except HTTPException as e:
        assert e.status_code == 404


async def test_ruta_gabi_rechaza_tono_vacio():
    negocio, _ = await _negocio_con_identidad("GabiValida")
    request = _RequestFalso({"nombre": "Gabi", "tono": "  "})
    try:
        await dashboard.actualizar_gabi_ruta(request, usuario={"negocio_id": negocio["id"]}, _csrf=None)
        assert False, "debía lanzar HTTPException"
    except HTTPException as e:
        assert e.status_code == 400


# ---------------------------------------------------------------------------
# Horarios — validación server-side + aislamiento
# ---------------------------------------------------------------------------

async def test_guardar_horario_dia_habilitado_ok():
    negocio, _ = await _negocio_con_identidad("Horario1")
    request = _RequestFalso({"dia_semana": 0, "habilitado": True, "hora_apertura": "08:00", "hora_cierre": "18:00"})
    respuesta = await dashboard.guardar_horario_ruta(request, usuario={"negocio_id": negocio["id"]}, _csrf=None)
    import json as _json
    cuerpo = _json.loads(respuesta.body)
    assert cuerpo["horario"]["habilitado"] is True
    assert cuerpo["horario"]["hora_apertura"] == "08:00"


async def test_guardar_horario_dia_deshabilitado_limpia_horas():
    negocio, _ = await _negocio_con_identidad("Horario2")
    request = _RequestFalso({"dia_semana": 6, "habilitado": False, "hora_apertura": "", "hora_cierre": ""})
    respuesta = await dashboard.guardar_horario_ruta(request, usuario={"negocio_id": negocio["id"]}, _csrf=None)
    import json as _json
    cuerpo = _json.loads(respuesta.body)
    assert cuerpo["horario"]["habilitado"] is False
    assert cuerpo["horario"]["hora_apertura"] is None
    assert cuerpo["horario"]["hora_cierre"] is None


async def test_guardar_horario_rechaza_formato_invalido():
    negocio, _ = await _negocio_con_identidad("Horario3")
    request = _RequestFalso({"dia_semana": 1, "habilitado": True, "hora_apertura": "8am", "hora_cierre": "18:00"})
    try:
        await dashboard.guardar_horario_ruta(request, usuario={"negocio_id": negocio["id"]}, _csrf=None)
        assert False, "debía lanzar HTTPException"
    except HTTPException as e:
        assert e.status_code == 400


async def test_guardar_horario_rechaza_apertura_despues_de_cierre():
    negocio, _ = await _negocio_con_identidad("Horario4")
    request = _RequestFalso({"dia_semana": 2, "habilitado": True, "hora_apertura": "20:00", "hora_cierre": "08:00"})
    try:
        await dashboard.guardar_horario_ruta(request, usuario={"negocio_id": negocio["id"]}, _csrf=None)
        assert False, "debía lanzar HTTPException"
    except HTTPException as e:
        assert e.status_code == 400


async def test_guardar_horario_rechaza_dia_fuera_de_rango():
    negocio, _ = await _negocio_con_identidad("Horario5")
    request = _RequestFalso({"dia_semana": 7, "habilitado": True, "hora_apertura": "08:00", "hora_cierre": "18:00"})
    try:
        await dashboard.guardar_horario_ruta(request, usuario={"negocio_id": negocio["id"]}, _csrf=None)
        assert False, "debía lanzar HTTPException"
    except HTTPException as e:
        assert e.status_code == 400


async def test_horario_de_A_no_afecta_a_B():
    negocio_a, _ = await _negocio_con_identidad("HorA")
    negocio_b, _ = await _negocio_con_identidad("HorB")

    await dashboard.guardar_horario_ruta(
        _RequestFalso({"dia_semana": 3, "habilitado": True, "hora_apertura": "09:00", "hora_cierre": "17:00"}),
        usuario={"negocio_id": negocio_a["id"]}, _csrf=None,
    )

    horarios_b = await mem.listar_horarios_atencion(negocio_b["id"])
    dia_3_b = next((h for h in horarios_b if h["dia_semana"] == 3), None)
    assert dia_3_b is None  # B nunca tuvo ese día guardado — A no lo contaminó


# ---------------------------------------------------------------------------
# Runtime — Gabi usa lo persistido (Gate 4.5 §21: no basta con que cambie la DB)
# ---------------------------------------------------------------------------

async def test_horario_guardado_afecta_estado_horario_en_runtime(tmp_path, monkeypatch):
    from agent.tools import obtener_estado_horario_atencion
    from datetime import datetime as _dt, time as _time
    from zoneinfo import ZoneInfo

    negocio, _ = await _negocio_con_identidad("HorarioRuntime")
    ahora_lima = _dt.now(ZoneInfo("America/Lima"))
    dia_hoy = ahora_lima.weekday()

    # Configura el día de HOY como deshabilitado — el runtime debe reflejarlo,
    # sin importar el fallback hardcodeado (lunes-sábado 8-19).
    await dashboard.guardar_horario_ruta(
        _RequestFalso({"dia_semana": dia_hoy, "habilitado": False, "hora_apertura": "", "hora_cierre": ""}),
        usuario={"negocio_id": negocio["id"]}, _csrf=None,
    )
    estado = await obtener_estado_horario_atencion(negocio["id"])
    assert estado["dentro_de_horario"] is False


async def test_gabi_nombre_tono_editados_se_reflejan_en_identidad_para_runtime():
    """obtener_system_prompt() para un negocio SIN usa_patron_estructural
    devuelve configuracion_negocio verbatim — confirma que editar
    nombre/tono desde Configuración no lo altera (ver test de arriba) y
    que la identidad que brain.py leería sigue siendo la correcta."""
    from agent.brain import obtener_system_prompt

    negocio, identidad = await _negocio_con_identidad("GabiRuntime")
    await dashboard.actualizar_gabi_ruta(
        _RequestFalso({"nombre": "Gabi Runtime", "tono": "Cálido"}),
        usuario={"negocio_id": negocio["id"]}, _csrf=None,
    )
    prompt = await obtener_system_prompt("produccion", negocio["id"])
    assert prompt == identidad["configuracion_negocio"]


# ---------------------------------------------------------------------------
# Secretos — configuracion.json nunca expone tokens/secrets
# ---------------------------------------------------------------------------

async def test_configuracion_json_no_expone_secretos_de_canal():
    negocio, _ = await _negocio_con_identidad("Secretos")
    await mem.crear_canal_whatsapp(
        nombre="Canal Test", phone_number_id="999888777", access_token="TOKEN-SECRETO-XYZ",
        app_secret="APP-SECRET-XYZ", page_access_token="PAGE-TOKEN-XYZ", negocio_id=negocio["id"],
    )
    respuesta = await dashboard.configuracion_json(usuario={"negocio_id": negocio["id"]})
    import json as _json
    cuerpo = _json.loads(respuesta.body)

    assert len(cuerpo["canales"]) == 1
    canal = cuerpo["canales"][0]
    assert set(canal.keys()) == {"id", "nombre", "modo", "activo", "token_renovado_en"}
    texto_completo = _json.dumps(cuerpo)
    assert "TOKEN-SECRETO-XYZ" not in texto_completo
    assert "APP-SECRET-XYZ" not in texto_completo
    assert "PAGE-TOKEN-XYZ" not in texto_completo
    assert "999888777" not in texto_completo  # phone_number_id tampoco se expone acá


async def test_configuracion_json_no_expone_prompt_completo():
    negocio, identidad = await _negocio_con_identidad("PromptOculto")
    respuesta = await dashboard.configuracion_json(usuario={"negocio_id": negocio["id"]})
    import json as _json
    cuerpo = _json.loads(respuesta.body)
    assert set(cuerpo["gabi"].keys()) == {"nombre", "tono", "prompt_configurado", "prompt_longitud"}
    texto_completo = _json.dumps(cuerpo)
    assert identidad["configuracion_negocio"] not in texto_completo


async def test_configuracion_json_aislada_por_negocio():
    negocio_a, identidad_a = await _negocio_con_identidad("ConfigA")
    negocio_b, identidad_b = await _negocio_con_identidad("ConfigB")

    resp_a = await dashboard.configuracion_json(usuario={"negocio_id": negocio_a["id"]})
    import json as _json
    cuerpo_a = _json.loads(resp_a.body)
    assert cuerpo_a["negocio"]["id"] == negocio_a["id"]
    assert cuerpo_a["gabi"]["nombre"] == identidad_a["nombre"]
    assert cuerpo_a["gabi"]["nombre"] != identidad_b["nombre"]
