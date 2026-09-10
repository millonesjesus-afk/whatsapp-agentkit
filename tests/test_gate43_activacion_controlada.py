# tests/test_gate43_activacion_controlada.py — GATE 4.3: mecanismo de
# activación controlada y reversible del ensamblador (`usa_patron_estructural`).
#
# Precondición pedida por el usuario antes de activar: 291/291, working
# tree limpio, baseline intacto, ensamblador correcto, aislamiento por
# negocio — este archivo prueba específicamente el TOGGLE en sí (default
# seguro, reversibilidad, aislamiento), no vuelve a probar la separación
# del prompt (eso ya está en test_gate43_separacion_prompt.py).

import yaml

from agent import brain, memory as mem


def _baseline_real() -> str:
    with open("config/prompts.yaml", "r", encoding="utf-8") as f:
        return yaml.safe_load(f)["system_prompt"]


async def _negocio_con_identidad_real(codigo: str):
    negocio = await mem.crear_negocio("Cálidda (validación)", codigo)
    baseline = _baseline_real()
    await mem.crear_o_actualizar_identidad_agente(
        negocio["id"], nombre="Gabi", tono="Cercano, profesional y resolutivo",
        configuracion_negocio=baseline,
    )
    return negocio, baseline


# ---------------------------------------------------------------------------
# Default seguro
# ---------------------------------------------------------------------------

async def test_default_usa_patron_estructural_es_false():
    negocio, baseline = await _negocio_con_identidad_real("g43c-default")
    identidad = await mem.obtener_identidad_agente(negocio["id"])
    assert identidad["usa_patron_estructural"] is False


async def test_sin_activar_obtener_system_prompt_devuelve_verbatim():
    negocio, baseline = await _negocio_con_identidad_real("g43c-sinactivar")
    resultado = await brain.obtener_system_prompt("produccion", negocio["id"])
    assert resultado == baseline


# ---------------------------------------------------------------------------
# Activación
# ---------------------------------------------------------------------------

async def test_activar_patron_estructural_cambia_obtener_system_prompt():
    negocio, baseline = await _negocio_con_identidad_real("g43c-activar")
    antes = await brain.obtener_system_prompt("produccion", negocio["id"])
    assert antes == baseline

    resultado_activacion = await mem.activar_patron_estructural(negocio["id"], True)
    assert resultado_activacion["usa_patron_estructural"] is True

    despues = await brain.obtener_system_prompt("produccion", negocio["id"])
    esperado = brain.ensamblar_system_prompt(brain._reducir_texto_legacy_calidda(baseline))
    assert despues == esperado
    assert despues != baseline  # el ensamblado, confirmado, no es igual al verbatim (orden distinto)


async def test_activar_patron_estructural_en_negocio_sin_identidad_devuelve_none():
    negocio = await mem.crear_negocio("Negocio sin identidad", "g43c-sinidentidad")
    resultado = await mem.activar_patron_estructural(negocio["id"], True)
    assert resultado is None


# ---------------------------------------------------------------------------
# Reversibilidad — "revertir es un solo campo"
# ---------------------------------------------------------------------------

async def test_revertir_activacion_vuelve_exactamente_al_baseline():
    negocio, baseline = await _negocio_con_identidad_real("g43c-revertir")
    await mem.activar_patron_estructural(negocio["id"], True)
    activado = await brain.obtener_system_prompt("produccion", negocio["id"])
    assert activado != baseline

    resultado_reversion = await mem.activar_patron_estructural(negocio["id"], False)
    assert resultado_reversion["usa_patron_estructural"] is False

    revertido = await brain.obtener_system_prompt("produccion", negocio["id"])
    assert revertido == baseline  # exactamente el mismo verbatim de antes — sin pérdida, sin residuo


async def test_configuracion_negocio_nunca_se_modifica_al_activar_ni_revertir():
    """La regla fundamental del usuario: activar/revertir no toca
    `configuracion_negocio` — solo el flag."""
    negocio, baseline = await _negocio_con_identidad_real("g43c-inmutable")
    await mem.activar_patron_estructural(negocio["id"], True)
    identidad_activada = await mem.obtener_identidad_agente(negocio["id"])
    assert identidad_activada["configuracion_negocio"] == baseline

    await mem.activar_patron_estructural(negocio["id"], False)
    identidad_revertida = await mem.obtener_identidad_agente(negocio["id"])
    assert identidad_revertida["configuracion_negocio"] == baseline


# ---------------------------------------------------------------------------
# Aislamiento por negocio — activar uno no activa otro
# ---------------------------------------------------------------------------

async def test_activar_un_negocio_no_activa_otro():
    negocio_a, baseline_a = await _negocio_con_identidad_real("g43c-aislado-a")
    negocio_b, baseline_b = await _negocio_con_identidad_real("g43c-aislado-b")

    await mem.activar_patron_estructural(negocio_a["id"], True)

    prompt_a = await brain.obtener_system_prompt("produccion", negocio_a["id"])
    prompt_b = await brain.obtener_system_prompt("produccion", negocio_b["id"])

    assert prompt_a != baseline_a  # A: activado
    assert prompt_b == baseline_b  # B: sigue en verbatim, sin tocar


async def test_modo_pruebas_no_se_afecta_por_la_activacion():
    """El modo "pruebas" (archivo tal cual) es deliberadamente ajeno a
    todo este mecanismo — confirmado que activar no lo toca."""
    negocio, baseline = await _negocio_con_identidad_real("g43c-modopruebas")
    await mem.activar_patron_estructural(negocio["id"], True)
    resultado = await brain.obtener_system_prompt("pruebas", negocio["id"])
    assert resultado == baseline
