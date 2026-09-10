# tests/test_gate42_identidad_agente.py — GATE 4.2: cierre de las
# Decisiones Pendientes 1 (identidad de Gabi por Negocio) y 5 (horarios por
# Negocio) de Gate 4.1.
#
# Foco especial en el requisito explícito del usuario: "Validación de
# equivalencia del prompt actual" — el contenido que se guarda para
# Cálidda debe ser IGUAL, byte a byte, al que ya corría en producción
# (config/prompts.yaml), y el ensamblado final por negocio_id no debe
# incorporar nunca configuración de otro negocio.

import datetime as _dt

import yaml

from agent import brain, dashboard, memory as mem, tools as herramientas


def _system_prompt_real() -> str:
    """Mismo mecanismo que usa `cargar_system_prompt()` — se relee acá,
    en vez de importar la función, para que este test sea independiente
    de que brain.py siga leyendo el archivo de la misma forma mañana."""
    with open("config/prompts.yaml", "r", encoding="utf-8") as f:
        return yaml.safe_load(f)["system_prompt"]


async def _negocio(codigo: str, nombre: str = "Negocio de prueba"):
    return await mem.crear_negocio(nombre, codigo)


# ---------------------------------------------------------------------------
# Equivalencia del prompt (requisito explícito del usuario)
# ---------------------------------------------------------------------------

async def test_configuracion_negocio_guardada_es_identica_byte_a_byte_al_prompt_real():
    negocio = await _negocio("g42-a")
    original = _system_prompt_real()

    guardada = await mem.crear_o_actualizar_identidad_agente(
        negocio["id"], nombre="Gabi", tono="Cercano, profesional y resolutivo",
        configuracion_negocio=original,
    )

    assert guardada["configuracion_negocio"] == original
    assert len(guardada["configuracion_negocio"]) == len(original)

    releida = await mem.obtener_identidad_agente(negocio["id"])
    assert releida["configuracion_negocio"] == original


async def test_obtener_system_prompt_produccion_devuelve_la_identidad_sin_alterar_una_letra():
    negocio = await _negocio("g42-b")
    original = _system_prompt_real()
    await mem.crear_o_actualizar_identidad_agente(
        negocio["id"], nombre="Gabi", tono="Cercano, profesional y resolutivo",
        configuracion_negocio=original,
    )

    resultado = await brain.obtener_system_prompt("produccion", negocio["id"])
    assert resultado == original


async def test_modo_pruebas_sigue_leyendo_el_archivo_sin_cambios_por_este_gate():
    """El modo "pruebas" es un mecanismo de staging pre-deploy (Gate 4.1
    §P), deliberadamente NO tocado por este Gate — debe seguir devolviendo
    el archivo tal cual, sin importar si el negocio ya tiene identidad."""
    negocio = await _negocio("g42-c")
    await mem.crear_o_actualizar_identidad_agente(
        negocio["id"], nombre="Otro nombre", tono="Otro tono",
        configuracion_negocio="contenido completamente distinto",
    )
    resultado = await brain.obtener_system_prompt("pruebas", negocio["id"])
    assert resultado == _system_prompt_real()
    assert resultado != "contenido completamente distinto"


# ---------------------------------------------------------------------------
# Regresión — negocio sin identidad migrada no cambia de comportamiento
# ---------------------------------------------------------------------------

async def test_negocio_sin_identidad_migrada_cae_al_mecanismo_anterior():
    negocio = await _negocio("g42-d")
    # Sin fila de IdentidadAgente para este negocio — ni override en
    # Configuracion tampoco: debe caer al archivo, exactamente el
    # comportamiento de antes de este Gate para un negocio no migrado.
    resultado = await brain.obtener_system_prompt("produccion", negocio["id"])
    assert resultado == _system_prompt_real()


async def test_negocio_id_none_no_rompe_sigue_cayendo_al_mecanismo_global():
    resultado = await brain.obtener_system_prompt("produccion", None)
    assert resultado == await mem.obtener_configuracion("system_prompt_produccion", _system_prompt_real())


# ---------------------------------------------------------------------------
# Aislamiento multi-tenant — el requisito más explícito del usuario
# ---------------------------------------------------------------------------

async def test_identidad_de_un_negocio_nunca_se_filtra_a_otro():
    negocio_a = await _negocio("g42-e1")
    negocio_b = await _negocio("g42-e2")

    await mem.crear_o_actualizar_identidad_agente(
        negocio_a["id"], nombre="Gabi A", tono="Tono A", configuracion_negocio="Prompt exclusivo de A",
    )
    await mem.crear_o_actualizar_identidad_agente(
        negocio_b["id"], nombre="Gabi B", tono="Tono B", configuracion_negocio="Prompt exclusivo de B",
    )

    identidad_a = await mem.obtener_identidad_agente(negocio_a["id"])
    identidad_b = await mem.obtener_identidad_agente(negocio_b["id"])

    assert identidad_a["configuracion_negocio"] == "Prompt exclusivo de A"
    assert identidad_b["configuracion_negocio"] == "Prompt exclusivo de B"
    assert identidad_a["configuracion_negocio"] != identidad_b["configuracion_negocio"]

    prompt_a = await brain.obtener_system_prompt("produccion", negocio_a["id"])
    prompt_b = await brain.obtener_system_prompt("produccion", negocio_b["id"])
    assert prompt_a == "Prompt exclusivo de A"
    assert prompt_b == "Prompt exclusivo de B"
    assert "B" not in prompt_a.replace("exclusivo", "")  # A nunca contiene texto de B


async def test_multiples_agentes_del_mismo_negocio_no_colisionan():
    """`codigo` distingue agentes del mismo Negocio — evolución futura a
    multi-agente pedida explícitamente en Gate 4.2 §1."""
    negocio = await _negocio("g42-f")
    await mem.crear_o_actualizar_identidad_agente(
        negocio["id"], nombre="Gabi", tono="Ventas", configuracion_negocio="prompt de ventas", codigo="gabi",
    )
    await mem.crear_o_actualizar_identidad_agente(
        negocio["id"], nombre="Soporte", tono="Técnico", configuracion_negocio="prompt de soporte", codigo="soporte",
    )
    ventas = await mem.obtener_identidad_agente(negocio["id"], codigo="gabi")
    soporte = await mem.obtener_identidad_agente(negocio["id"], codigo="soporte")
    assert ventas["configuracion_negocio"] == "prompt de ventas"
    assert soporte["configuracion_negocio"] == "prompt de soporte"


# ---------------------------------------------------------------------------
# Horarios — mismo resultado que el rango que estaba hardcodeado antes
# ---------------------------------------------------------------------------

class _RelojFijo:
    def __init__(self, instante):
        self._instante = instante

    def now(self, tz=None):
        return self._instante

    def fromisoformat(self, *a, **kw):
        return _dt.time.fromisoformat(*a, **kw)


def _fijar_reloj(monkeypatch, año, mes, dia, hora, minuto):
    instante = _dt.datetime(año, mes, dia, hora, minuto, tzinfo=herramientas.TZ_LIMA)
    monkeypatch.setattr(herramientas, "datetime", _RelojFijo(instante))


async def test_horario_por_negocio_dentro_de_horario_lunes(monkeypatch):
    negocio = await _negocio("g42-g")
    for dia in range(7):
        habilitado = dia < 6
        await mem.guardar_horario_atencion(
            negocio["id"], dia, habilitado,
            "08:00" if habilitado else None, "19:00" if habilitado else None,
        )
    _fijar_reloj(monkeypatch, 2026, 9, 7, 10, 0)  # lunes 7/sep/2026, 10:00
    estado = await herramientas.obtener_estado_horario_atencion(negocio["id"])
    assert estado["dentro_de_horario"] is True


async def test_horario_por_negocio_domingo_cerrado(monkeypatch):
    negocio = await _negocio("g42-h")
    for dia in range(7):
        habilitado = dia < 6
        await mem.guardar_horario_atencion(
            negocio["id"], dia, habilitado,
            "08:00" if habilitado else None, "19:00" if habilitado else None,
        )
    _fijar_reloj(monkeypatch, 2026, 9, 6, 12, 0)  # domingo 6/sep/2026, mediodía
    estado = await herramientas.obtener_estado_horario_atencion(negocio["id"])
    assert estado["dentro_de_horario"] is False


async def test_horario_por_negocio_distinto_de_otro_negocio_sin_filtrarse(monkeypatch):
    negocio_a = await _negocio("g42-i1")
    negocio_b = await _negocio("g42-i2")
    # Negocio A: abre solo hasta el mediodía. Negocio B: abre todo el día.
    for dia in range(7):
        await mem.guardar_horario_atencion(negocio_a["id"], dia, True, "08:00", "12:00")
        await mem.guardar_horario_atencion(negocio_b["id"], dia, True, "00:00", "23:59")

    _fijar_reloj(monkeypatch, 2026, 9, 7, 15, 0)  # lunes, 15:00 — fuera para A, dentro para B
    estado_a = await herramientas.obtener_estado_horario_atencion(negocio_a["id"])
    estado_b = await herramientas.obtener_estado_horario_atencion(negocio_b["id"])
    assert estado_a["dentro_de_horario"] is False
    assert estado_b["dentro_de_horario"] is True


async def test_negocio_sin_horarios_backfilleados_cae_al_rango_anterior_hardcodeado(monkeypatch):
    """Mismo criterio de compatibilidad que el system prompt: un negocio
    sin HorarioAtencion todavía no cambia de comportamiento."""
    negocio = await _negocio("g42-j")
    _fijar_reloj(monkeypatch, 2026, 9, 7, 10, 0)  # lunes 10:00 — dentro del rango anterior (8-19)
    estado = await herramientas.obtener_estado_horario_atencion(negocio["id"])
    assert estado["dentro_de_horario"] is True

    _fijar_reloj(monkeypatch, 2026, 9, 6, 10, 0)  # domingo — fuera del rango anterior
    estado_domingo = await herramientas.obtener_estado_horario_atencion(negocio["id"])
    assert estado_domingo["dentro_de_horario"] is False


async def test_negocio_id_none_tambien_cae_al_rango_anterior(monkeypatch):
    _fijar_reloj(monkeypatch, 2026, 9, 7, 10, 0)
    estado = await herramientas.obtener_estado_horario_atencion(None)
    assert estado["dentro_de_horario"] is True


# ---------------------------------------------------------------------------
# Ruta HTTP — GET /dashboard/configuracion.json (Decisión 6)
# ---------------------------------------------------------------------------

async def test_ruta_configuracion_json_estructura_negocio_gabi_canales():
    negocio = await _negocio("g42-k")
    await mem.crear_o_actualizar_identidad_agente(
        negocio["id"], nombre="Gabi", tono="Cercano", configuracion_negocio="x" * 500,
    )
    await mem.guardar_horario_atencion(negocio["id"], 0, True, "08:00", "19:00")
    await mem.crear_canal_whatsapp(
        nombre="Principal", phone_number_id="99900011122", negocio_id=negocio["id"],
    )

    usuario = {"negocio_id": negocio["id"], "rol": "admin"}
    respuesta = await dashboard.configuracion_json(usuario=usuario)
    import json
    cuerpo = json.loads(respuesta.body)

    assert cuerpo["negocio"]["id"] == negocio["id"]
    assert cuerpo["gabi"]["nombre"] == "Gabi"
    assert cuerpo["gabi"]["prompt_longitud"] == 500
    assert "configuracion_negocio" not in cuerpo["gabi"]  # nunca expone el texto completo todavía
    assert len(cuerpo["horarios"]) == 1
    assert len(cuerpo["canales"]) == 1
    assert cuerpo["canales"][0]["nombre"] == "Principal"


async def test_ruta_configuracion_json_gabi_null_si_no_hay_identidad_migrada():
    negocio = await _negocio("g42-l")
    usuario = {"negocio_id": negocio["id"], "rol": "admin"}
    respuesta = await dashboard.configuracion_json(usuario=usuario)
    import json
    cuerpo = json.loads(respuesta.body)
    assert cuerpo["gabi"] is None


# ---------------------------------------------------------------------------
# Legacy — el botón "Promover a producción" avisa en vez de quedar inerte
# ---------------------------------------------------------------------------

async def test_bloque_promover_prompt_avisa_cuando_el_negocio_ya_tiene_identidad():
    negocio = await _negocio("g42-m")
    await mem.crear_o_actualizar_identidad_agente(
        negocio["id"], nombre="Gabi", tono="Cercano", configuracion_negocio=_system_prompt_real(),
    )
    html = await dashboard._bloque_promover_prompt(None, negocio["id"])
    assert "ya no tiene efecto" in html


async def test_bloque_promover_prompt_sigue_funcionando_sin_identidad_migrada():
    negocio = await _negocio("g42-n")
    html = await dashboard._bloque_promover_prompt(None, negocio["id"])
    assert "ya no tiene efecto" not in html
    assert "ya está al día" in html  # archivo y Configuracion global coinciden por fallback
