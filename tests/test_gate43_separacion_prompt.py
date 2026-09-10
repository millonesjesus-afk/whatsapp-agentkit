# tests/test_gate43_separacion_prompt.py — GATE 4.3: migración controlada
# de la Decisión Pendiente 2 de Gate 4.1 (separación física del prompt en
# "patrón estructural" + "configuración del negocio").
#
# CORREGIDO tras revisión del usuario: la v1 de este Gate dejaba dos
# problemas — "Gaso+" mencionado dentro del patrón estructural, y el
# horario literal de Cálidda mezclado con un principio genérico dentro de
# "Cuándo derivar". Ambos corregidos en `agent/brain.py` (ver el comentario
# largo sobre `PATRON_ESTRUCTURAL_AGENTE`) — este archivo prueba el
# resultado corregido.
#
# Disciplina: NO aceptar diferencias textuales en silencio — cada una se
# identifica, se explica y se prueba que es consecuencia necesaria de la
# nueva arquitectura, nunca pérdida ni invención de contenido no
# documentada. Validación a nivel de CONTENIDO/texto (determinista) — sin
# llamadas a la API real de Claude.
#
# INACTIVO A PROPÓSITO: ningún test ejercita el flujo real de WhatsApp con
# el ensamblado nuevo — `obtener_system_prompt()` para Cálidda sigue
# devolviendo el baseline verbatim (test dedicado al final).

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
    (esperadas al remover/mover fragmentos) cuenten como diferencia real."""
    return re.sub(r"\s+", " ", texto).strip()


def _sin_espacios(texto: str) -> list[str]:
    """Multiset de caracteres NO-whitespace, ordenado — la prueba más
    fuerte de "ningún contenido perdido ni inventado más allá de lo
    documentado explícitamente"."""
    return sorted(c for c in texto if not c.isspace())


FRASE_ORIGINAL_GASO_MAS = "de la base de conocimiento de Gaso+."
FRASE_GENERICA_NEGOCIO = "de la base de conocimiento del negocio."
TITULO_NUEVO_DISPONIBILIDAD = "## Disponibilidad del asesor humano segun horario"


def _baseline_mas_los_2_cambios_documentados() -> str:
    """El baseline real, con ÚNICAMENTE las 2 ediciones explícitamente
    autorizadas por el usuario aplicadas — el "resultado esperado" contra
    el que se compara el ensamblado corregido."""
    baseline = _baseline_real()
    con_frase_generica = baseline.replace(FRASE_ORIGINAL_GASO_MAS, FRASE_GENERICA_NEGOCIO)
    return con_frase_generica + "\n" + TITULO_NUEVO_DISPONIBILIDAD + "\n"


# ---------------------------------------------------------------------------
# A. "Gaso+" — confirmado y corregido
# ---------------------------------------------------------------------------

def test_gaso_mas_ya_no_esta_en_el_patron_estructural():
    assert "Gaso+" not in brain.PATRON_ESTRUCTURAL_AGENTE


def test_patron_estructural_usa_la_frase_generica():
    assert FRASE_GENERICA_NEGOCIO in brain.PATRON_ESTRUCTURAL_AGENTE


def test_la_regla_de_uso_de_contexto_sigue_intacta_solo_cambio_la_frase():
    """El resto de "Uso del contexto" (la instrucción real: usar SOLO el
    contexto dado, no inventar) no se tocó — solo la mención de marca."""
    assert "Básate" in brain.PATRON_ESTRUCTURAL_AGENTE
    assert "ÚNICAMENTE en ese contexto" in brain.PATRON_ESTRUCTURAL_AGENTE
    assert "no inventes" in brain.PATRON_ESTRUCTURAL_AGENTE


# ---------------------------------------------------------------------------
# B. Horario — principio movido a estructural, dato se queda en negocio
# ---------------------------------------------------------------------------

def test_dato_literal_de_horario_se_queda_en_configuracion_de_negocio():
    baseline = _baseline_real()
    reducido = brain._reducir_texto_legacy_calidda(baseline)
    assert "Lunes a Sábado de 8:00am a 7:00pm" in reducido


def test_dato_literal_de_horario_no_esta_en_el_patron_estructural():
    assert "Lunes a Sábado" not in brain.PATRON_ESTRUCTURAL_AGENTE
    assert "8:00am" not in brain.PATRON_ESTRUCTURAL_AGENTE


def test_principio_de_disponibilidad_esta_en_el_patron_estructural():
    assert "Si estás dentro de ese horario" in brain.PATRON_ESTRUCTURAL_AGENTE
    assert "Si estás fuera de ese horario" in brain.PATRON_ESTRUCTURAL_AGENTE


def test_principio_de_disponibilidad_ya_no_esta_en_configuracion_de_negocio():
    baseline = _baseline_real()
    reducido = brain._reducir_texto_legacy_calidda(baseline)
    assert "Si estás dentro de ese horario" not in reducido
    assert "Si estás fuera de ese horario" not in reducido


def test_cuando_derivar_conserva_su_lista_de_triggers_especificos():
    """Los triggers de escalamiento (DNI dado, cotización, visita técnica,
    reclamo, condiciones especiales) son información de negocio real —
    ninguno se tocó."""
    baseline = _baseline_real()
    reducido = brain._reducir_texto_legacy_calidda(baseline)
    for trigger in (
        "Pida una cotización personalizada",
        "Necesite una visita técnica o instalación",
        "Tenga un reclamo",
        "Pida condiciones comerciales especiales",
    ):
        assert trigger in reducido


# ---------------------------------------------------------------------------
# Equivalencia exhaustiva — ningún contenido perdido ni inventado más allá
# de los 2 cambios documentados en A y B
# ---------------------------------------------------------------------------

def test_multiset_no_whitespace_identico_salvo_los_2_cambios_documentados():
    """La prueba central: (configuración-de-negocio + patrón-estructural),
    como multiset de caracteres NO-whitespace, es IDÉNTICO a (baseline +
    las 2 ediciones documentadas) — ninguna otra diferencia, ni una letra
    de más ni de menos."""
    baseline = _baseline_real()
    reducido = brain._reducir_texto_legacy_calidda(baseline)
    ensamblado = brain.ensamblar_system_prompt(reducido)

    esperado = _baseline_mas_los_2_cambios_documentados()
    assert _sin_espacios(ensamblado) == _sin_espacios(esperado)


def test_ensamblado_conserva_14_secciones_normalizadas():
    """13 del original + 1 nueva ("Disponibilidad...", necesaria para que
    el fragmento reubicado sea una sección válida) = 14."""
    baseline = _baseline_real()
    reducido = brain._reducir_texto_legacy_calidda(baseline)
    ensamblado = brain.ensamblar_system_prompt(reducido)

    secciones = {_normalizar(s) for s in re.split(r"(?=^## )", ensamblado, flags=re.MULTILINE) if s.strip()}
    assert len(secciones) == 14


def test_ensamblado_es_determinista():
    baseline = _baseline_real()
    reducido = brain._reducir_texto_legacy_calidda(baseline)
    a = brain.ensamblar_system_prompt(reducido)
    b = brain.ensamblar_system_prompt(reducido)
    assert a == b


def test_reduccion_es_idempotente_dado_el_mismo_baseline():
    baseline = _baseline_real()
    r1 = brain._reducir_texto_legacy_calidda(baseline)
    r2 = brain._reducir_texto_legacy_calidda(baseline)
    assert r1 == r2


def test_reduccion_falla_ruidosamente_si_falta_el_fragmento_de_horario():
    baseline = _baseline_real()
    ya_reducido = brain._reducir_texto_legacy_calidda(baseline)  # ya no tiene el fragmento
    import pytest
    with pytest.raises(ValueError, match="no se encontr"):
        brain._reducir_texto_legacy_calidda(ya_reducido)


# ---------------------------------------------------------------------------
# Validación de contenido crítico (condición 9 del Gate 4.3 original) —
# presencia textual de cada área exigida, en el prompt YA ENSAMBLADO.
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
    assert "Lunes a Sábado de 8:00am a 7:00pm" in e  # el dato sigue disponible
    assert "Si estás dentro de ese horario" in e  # y el principio también, aunque en otra posición


def test_validacion_comportamiento_de_financiamiento():
    e = _prompt_ensamblado_calidda()
    assert "Si la instalación sería en una vivienda con suministro de gas natural de Cálidda" in e
    assert "NUNCA afirmes que el cliente está aprobado o desaprobado" in e


def test_validacion_sin_informacion_de_otro_negocio():
    prompt_calidda = _prompt_ensamblado_calidda()
    prompt_otro = brain.ensamblar_system_prompt("Eres Nova, la asistente de Ferretería Central. Vendemos herramientas.")

    assert "Ferretería Central" not in prompt_calidda
    assert "Cálidda" not in prompt_otro
    assert "gasodoméstico" not in prompt_otro
    assert "Lunes a Sábado de 8:00am a 7:00pm" not in prompt_otro  # el dato de Cálidda no se filtra
    # el patrón estructural SÍ es compartido a propósito — no es contaminación
    assert "SIEMPRE responde en español" in prompt_calidda
    assert "SIEMPRE responde en español" in prompt_otro
    assert "Si estás dentro de ese horario" in prompt_otro  # el PRINCIPIO sí aplica a cualquier negocio


def test_patron_estructural_es_verdaderamente_agnostico_al_negocio():
    """Criterio de éxito actualizado del usuario, verificado directamente:
    ninguna referencia a Cálidda, Gaso+, ni a ningún dato específico de
    negocio (horario literal incluido) dentro de PATRON_ESTRUCTURAL_AGENTE."""
    for referencia_prohibida in ("Cálidda", "Gaso+", "gasodoméstico", "8:00am", "Lunes a Sábado", "financiamiento"):
        assert referencia_prohibida not in brain.PATRON_ESTRUCTURAL_AGENTE, (
            f"'{referencia_prohibida}' no debería aparecer en el patrón estructural"
        )


# ---------------------------------------------------------------------------
# Inactividad — el ensamblado NO se usa en el flujo real todavía
# ---------------------------------------------------------------------------

async def test_obtener_system_prompt_para_calidda_sigue_sirviendo_el_baseline_verbatim():
    """La prueba más importante de este Gate: confirma que la migración
    queda en paralelo/inactiva."""
    negocio = await mem.crear_negocio("Cálidda (simulada)", "g43b-calidda-sim")
    baseline = _baseline_real()
    await mem.crear_o_actualizar_identidad_agente(
        negocio["id"], nombre="Gabi", tono="Cercano, profesional y resolutivo",
        configuracion_negocio=baseline,
    )

    resultado = await brain.obtener_system_prompt("produccion", negocio["id"])

    assert resultado == baseline  # NO el ensamblado — el verbatim tal cual
    ensamblado = brain.ensamblar_system_prompt(brain._reducir_texto_legacy_calidda(baseline))
    assert resultado != ensamblado
