# tests/test_migracion_regla_derivacion.py — la migración c5d9e2b7a481 agrega la
# regla "deriva sin pedir permiso" al prompt de Gabi que vive en la base. Lo
# que se prueba: que el resultado sea IDÉNTICO a config/prompts.yaml (así el
# prompt de producción y el de pruebas no divergen), que no se duplique, que
# no toque nada si no encuentra dónde insertar, y que el prompt siga siendo
# compatible con `_reducir_texto_legacy_calidda` (activación del patrón
# estructural de Gate 4.3).

import importlib.util
from pathlib import Path

import yaml

from agent import brain

_RUTA = Path(__file__).resolve().parent.parent / "migrations" / "versions" / "c5d9e2b7a481_agregar_regla_de_derivacion_a_la_identidad_de_gabi.py"


def _migracion():
    spec = importlib.util.spec_from_file_location("mig_regla_derivacion", _RUTA)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


def _prompt_actual() -> str:
    with open("config/prompts.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)["system_prompt"]


def test_insertar_sobre_el_prompt_anterior_da_exactamente_prompts_yaml():
    m = _migracion()
    actual = _prompt_actual()
    assert m.PARRAFO in actual
    anterior = actual.replace(m.PARRAFO, "", 1)  # el prompt que hoy tiene producción
    assert m.insertar(anterior) == actual


def test_es_idempotente():
    m = _migracion()
    actual = _prompt_actual()
    assert m.insertar(actual) == actual
    assert m.insertar(m.insertar(actual.replace(m.PARRAFO, "", 1))) == actual


def test_sin_la_linea_del_horario_no_toca_nada():
    m = _migracion()
    sin_ancla = "Eres un asistente.\n## Otra cosa\nTexto sin la línea del horario."
    assert m.insertar(sin_ancla) == sin_ancla


def test_no_rompe_la_reduccion_del_patron_estructural():
    """`_reducir_texto_legacy_calidda` exige que ciertos bloques sigan
    idénticos — el párrafo nuevo no puede haber alterado ninguno."""
    reducido = brain._reducir_texto_legacy_calidda(_prompt_actual())
    assert "NUNCA le preguntes si quiere que lo derives" in reducido


def test_la_regla_dice_lo_que_el_usuario_pidio():
    m = _migracion()
    plano = " ".join(m.PARRAFO.split())  # el párrafo viene con saltos de línea de ajuste
    assert "derívalo tú directamente" in plano
    assert "dile que lo estás derivando con un asesor comercial" in plano
    assert "NUNCA le preguntes si quiere que lo derives" in plano
