"""El script que cambia «Gaso+» por «Cálidda Hogar» en la identidad de Gabi solo toca las frases de identidad."""
import pytest

from scripts import actualizar_identidad_gabi as s

PROMPT = (
    "Eres Gabi, la asesora virtual del programa Gaso+ de Cálidda (Gas Natural de Lima y Callao).\n"
    "- Representas a Gaso+, el programa de financiamiento de gasodomésticos de Cálidda.\n"
    "  Gaso+ permite a clientes de Cálidda con suministro\n"
    "## Uso del contexto que se te proporciona\n"
    "información del catálogo o de la base de conocimiento de Gaso+. Básate\n"
)


def test_solo_cambia_la_identidad_y_deja_el_bloque_uso_del_contexto():
    nuevo, problemas = s.aplicar_reemplazos(PROMPT)
    assert problemas == []
    assert "asesora virtual de Cálidda Hogar" in nuevo and "Representas a Cálidda Hogar" in nuevo
    assert "  Cálidda Hogar permite" in nuevo
    # el bloque que `brain._reducir_texto_legacy_calidda` busca por texto exacto no se toca
    assert "base de conocimiento de Gaso+. Básate" in nuevo


def test_revertir_devuelve_el_texto_original():
    nuevo, _ = s.aplicar_reemplazos(PROMPT)
    assert s.aplicar_reemplazos(nuevo, revertir=True)[0] == PROMPT


def test_si_falta_una_frase_no_cambia_nada():
    sin_una = PROMPT.replace("  Gaso+ permite a clientes de Cálidda con suministro\n", "")
    nuevo, problemas = s.aplicar_reemplazos(sin_una)
    assert nuevo == sin_una and len(problemas) == 1
