# tests/test_gate43_separacion_prompt.py — GATE 4.3: migración controlada
# de la Decisión Pendiente 2 de Gate 4.1 (separación física del prompt en
# "patrón estructural" + "configuración del negocio").
#
# Disciplina explícita pedida por el usuario: NO aceptar diferencias
# textuales en silencio — cada una se identifica, se explica y se prueba
# que es consecuencia necesaria de la nueva arquitectura (reordenamiento),
# nunca pérdida ni invención de contenido. Validación a nivel de
# CONTENIDO/texto (determinista) — no se llama a la API real de Claude,
# tal como se acordó explícitamente para este Gate.
#
# INACTIVO A PROPÓSITO: ninguno de estos tests ejercita el flujo real de
# WhatsApp con el ensamblado nuevo — `obtener_system_prompt()` para
# Cálidda sigue devolviendo el baseline verbatim (ver el test dedicado más
# abajo que lo prueba explícitamente).

import re

import yaml

from agent import brain, memory as mem


def _baseline_real() -> str:
    """El mismo baseline ya congelado en Gate 4.2 — releído fresco del
    archivo en cada corrida, nunca hardcodeado en este test."""
    with open("config/prompts.yaml", "r", encoding="utf-8") as f:
        return yaml.safe_load(f)["system_prompt"]


def _normalizar(texto: str) -> str:
    """Colapsa runs de whitespace a un solo espacio — para comparar
    CONTENIDO sin que diferencias de saltos de línea en los empalmes
    (esperadas al remover secciones del medio de un documento) cuenten
    como una diferencia real."""
    return re.sub(r"\s+", " ", texto).strip()


def _secciones_normalizadas(texto: str) -> set[str]:
    return {_normalizar(s) for s in re.split(r"(?=^## )", texto, flags=re.MULTILINE) if s.strip()}


# ---------------------------------------------------------------------------
# Baseline congelado
# ---------------------------------------------------------------------------

def test_baseline_coincide_con_lo_ya_congelado_en_gate_42():
    """El baseline de este Gate es el MISMO que Gate 4.2 ya guardó verbatim
    en IdentidadAgente para Cálidda — no se inventa uno nuevo."""
    baseline = _baseline_real()
    assert len(baseline) == 8198


# ---------------------------------------------------------------------------
# Separación física — nada se pierde, nada se inventa
# ---------------------------------------------------------------------------

def test_patron_estructural_son_exactamente_las_3_secciones_clasificadas_en_gate_42():
    titulos = [s.strip().split("\n")[0] for s in re.split(r"(?=^## )", brain.PATRON_ESTRUCTURAL_AGENTE.strip(), flags=re.MULTILINE) if s.strip()]
    assert titulos == [
        "## Reglas de estilo (síguelas siempre)",
        "## Uso del contexto que se te proporciona",
        "## Reglas de comportamiento",
    ]


def test_reduccion_legacy_extrae_exactamente_el_patron_estructural_sin_tocar_el_resto():
    baseline = _baseline_real()
    reducido = brain._reducir_texto_legacy_calidda(baseline)
    # Ninguno de los 3 títulos estructurales sigue en el texto reducido.
    for titulo in ("## Reglas de estilo", "## Uso del contexto", "## Reglas de comportamiento"):
        assert titulo not in reducido
    # Todo lo demás SÍ sigue — algunos anclajes de cada sección restante.
    for fragmento in (
        "Eres Gabi, la asesora virtual",
        "## Sobre el negocio",
        "## Validación para financiamiento",
        "## Cuándo derivar a un asesor humano",
        "## Restricciones",
        "## Filosofía comercial",
    ):
        assert fragmento in reducido


def test_ensamblado_conserva_exactamente_el_mismo_set_de_secciones_que_el_baseline():
    """La prueba central de equivalencia de CONTENIDO (condición 6/7 del
    usuario): mismas 13 secciones (línea de apertura + 12 "##"), mismo
    texto normalizado en cada una — ninguna perdida, ninguna inventada,
    ninguna duplicada. El ORDEN se prueba aparte (test siguiente) porque
    ESE sí cambia, a propósito."""
    baseline = _baseline_real()
    reducido = brain._reducir_texto_legacy_calidda(baseline)
    ensamblado = brain.ensamblar_system_prompt(reducido)

    secciones_base = _secciones_normalizadas(baseline)
    secciones_ens = _secciones_normalizadas(ensamblado)
    assert secciones_ens == secciones_base
    assert len(secciones_base) == 13


def test_diferencia_de_orden_es_la_unica_diferencia_real_y_esta_documentada():
    """Condición 8 del usuario: si el orden cambia, prueba de regresión
    explícita + documentación. La diferencia real (no de whitespace): en
    el baseline, "Reglas de estilo" aparece justo después de "Validación
    para financiamiento"; en el ensamblado, aparece al final (después de
    "Filosofía comercial"), como parte del patrón estructural."""
    baseline = _baseline_real()
    reducido = brain._reducir_texto_legacy_calidda(baseline)
    ensamblado = brain.ensamblar_system_prompt(reducido)

    assert baseline != ensamblado  # el orden SÍ difiere — esperado, no un bug
    assert ensamblado.rstrip().endswith("muestra empatía antes de resolver.")  # termina con el patrón estructural
    assert baseline.index("## Reglas de estilo") < baseline.index("## Filosofía comercial")
    assert ensamblado.index("## Reglas de estilo") > ensamblado.index("## Filosofía comercial")


def test_longitud_normalizada_identica_solo_difiere_por_whitespace_de_empalme():
    """Condición 6 (longitud/caracteres): la longitud CRUDA difiere en un
    puñado de caracteres (runs de salto de línea distintos en los puntos
    de empalme, inevitable al remover secciones del medio de un
    documento) — pero la longitud NORMALIZADA (whitespace colapsado) es
    IDÉNTICA, prueba de que no se perdió ni se agregó contenido real."""
    baseline = _baseline_real()
    reducido = brain._reducir_texto_legacy_calidda(baseline)
    ensamblado = brain.ensamblar_system_prompt(reducido)

    assert len(_normalizar(baseline)) == len(_normalizar(ensamblado))


def test_hallazgo_documentado_gaso_mas_en_bloque_estructural_no_es_perdida_de_contenido():
    """Hallazgo de este Gate, NO corregido a propósito (ver comentario en
    brain.py): "Uso del contexto" menciona "Gaso+" por nombre — el texto
    sigue siendo válido para Cálidda (no es un error de contenido), pero
    el patrón no es 100% genérico todavía. Se deja documentado con un
    test explícito, no oculto."""
    assert "Gaso+" in brain.PATRON_ESTRUCTURAL_AGENTE


def test_ensamblado_es_determinista():
    baseline = _baseline_real()
    reducido = brain._reducir_texto_legacy_calidda(baseline)
    a = brain.ensamblar_system_prompt(reducido)
    b = brain.ensamblar_system_prompt(reducido)
    assert a == b


def test_doble_ciclo_reduccion_y_ensamblado_es_idempotente():
    baseline = _baseline_real()
    primera_vuelta = brain.ensamblar_system_prompt(brain._reducir_texto_legacy_calidda(baseline))
    segunda_vuelta = brain.ensamblar_system_prompt(brain._reducir_texto_legacy_calidda(baseline))
    assert primera_vuelta == segunda_vuelta


def test_reduccion_falla_ruidosamente_si_falta_un_bloque_estructural():
    """Fail-loud a propósito: mejor romper la migración que reconstruir un
    prompt con un bloque duplicado en silencio si el texto y el patrón
    estructural alguna vez divergen."""
    import pytest
    texto_sin_reglas_de_estilo = brain._reducir_texto_legacy_calidda(_baseline_real())  # ya no tiene los 3 bloques
    with pytest.raises(ValueError, match="no se encontraron en el texto"):
        brain._reducir_texto_legacy_calidda(texto_sin_reglas_de_estilo)


# ---------------------------------------------------------------------------
# Validación de contenido crítico (condición 9 del usuario) — presencia
# textual de cada área exigida, en el prompt YA ENSAMBLADO.
# ---------------------------------------------------------------------------

def _prompt_ensamblado_calidda() -> str:
    baseline = _baseline_real()
    return brain.ensamblar_system_prompt(brain._reducir_texto_legacy_calidda(baseline))


def test_validacion_identidad():
    e = _prompt_ensamblado_calidda()
    assert "Te llamas Gabi" in e
    assert "cercano, profesional y resolutivo" in e


def test_validacion_contexto_de_negocio():
    e = _prompt_ensamblado_calidda()
    assert "40% TEA" in e
    assert "gasodomésticos" in e


def test_validacion_restricciones():
    e = _prompt_ensamblado_calidda()
    assert 'Decir que un cliente "califica" o "no califica"' in e
    assert "Aprobar o rechazar solicitudes de financiamiento" in e


def test_validacion_flujo_de_atencion():
    e = _prompt_ensamblado_calidda()
    assert "Saluda cordialmente" in e
    assert "Recomienda el producto más adecuado del catálogo" in e


def test_validacion_derivacion():
    e = _prompt_ensamblado_calidda()
    assert "Pida una cotización personalizada" in e
    assert "Necesite una visita técnica o instalación" in e


def test_validacion_comportamiento_de_financiamiento():
    e = _prompt_ensamblado_calidda()
    assert "Si la instalación sería en una vivienda con suministro de gas natural de Cálidda" in e
    assert "NUNCA afirmes que el cliente está aprobado o desaprobado" in e


def test_validacion_sin_informacion_de_otro_negocio():
    """Mismo criterio de aislamiento que Gate 4.2 — ensamblar para un
    Negocio sintético con configuración distinta y confirmar que el
    resultado de Cálidda nunca aparece ahí, y viceversa."""
    prompt_calidda = _prompt_ensamblado_calidda()
    prompt_otro = brain.ensamblar_system_prompt("Eres Nova, la asistente de Ferretería Central. Vendemos herramientas.")

    assert "Ferretería Central" not in prompt_calidda
    assert "Cálidda" not in prompt_otro
    assert "gasodoméstico" not in prompt_otro
    # el patrón estructural SÍ es compartido a propósito — no es contaminación
    assert "SIEMPRE responde en español" in prompt_calidda
    assert "SIEMPRE responde en español" in prompt_otro


# ---------------------------------------------------------------------------
# Inactividad — el ensamblado NO se usa en el flujo real todavía
# ---------------------------------------------------------------------------

async def test_obtener_system_prompt_para_calidda_sigue_sirviendo_el_baseline_verbatim():
    """La prueba más importante de este Gate: confirma que la migración
    queda en paralelo/inactiva. Si este test alguna vez falla, significa
    que algo activó el ensamblado sin la aprobación separada que este
    Gate dejó pendiente."""
    negocio = await mem.crear_negocio("Cálidda (simulada)", "g43-calidda-sim")
    baseline = _baseline_real()
    await mem.crear_o_actualizar_identidad_agente(
        negocio["id"], nombre="Gabi", tono="Cercano, profesional y resolutivo",
        configuracion_negocio=baseline,
    )

    resultado = await brain.obtener_system_prompt("produccion", negocio["id"])

    assert resultado == baseline  # NO el ensamblado — el verbatim tal cual
    ensamblado = brain.ensamblar_system_prompt(brain._reducir_texto_legacy_calidda(baseline))
    assert resultado != ensamblado
