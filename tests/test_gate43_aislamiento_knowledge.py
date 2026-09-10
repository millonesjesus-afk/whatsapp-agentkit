# tests/test_gate43_aislamiento_knowledge.py — auditoría puntual y acotada
# de `agent/tools.py::buscar_en_knowledge` (hallazgo de la validación de
# activación de Gabi, Gate 4.3): antes de esta corrección, `/knowledge/`
# era una sola carpeta compartida por todo el proceso, sin relación con
# `negocio_id` — un segundo Negocio real habría recibido, sin darse
# cuenta, contenido de la base de conocimiento de Cálidda (contratos,
# políticas comerciales, speech de televentas) en sus propias
# conversaciones.
#
# Corrección: `knowledge/<codigo_de_negocio>/` — cada Negocio con su
# propia subcarpeta, resuelta por `Negocio.codigo` (slug estable, no
# `negocio_id`, que es un UUID distinto por entorno).

import os

from agent import brain, memory as mem, tools as herramientas


def test_conocimiento_de_un_negocio_no_se_filtra_a_otro(tmp_path, monkeypatch):
    monkeypatch.setattr(herramientas, "KNOWLEDGE_DIR", str(tmp_path))
    (tmp_path / "negocio_a").mkdir()
    (tmp_path / "negocio_b").mkdir()
    (tmp_path / "negocio_a" / "contrato.md").write_text(
        "Este documento pertenece exclusivamente al negocio Alfa Ferreteria.", encoding="utf-8",
    )
    (tmp_path / "negocio_b" / "contrato.md").write_text(
        "Este documento pertenece exclusivamente al negocio Beta Gasodomesticos.", encoding="utf-8",
    )

    resultado_a = herramientas.buscar_en_knowledge("documento pertenece exclusivamente negocio", "negocio_a")
    resultado_b = herramientas.buscar_en_knowledge("documento pertenece exclusivamente negocio", "negocio_b")

    assert "Alfa Ferreteria" in resultado_a
    assert "Beta Gasodomesticos" not in resultado_a
    assert "Beta Gasodomesticos" in resultado_b
    assert "Alfa Ferreteria" not in resultado_b


def test_negocio_sin_carpeta_de_conocimiento_no_recibe_contexto(tmp_path, monkeypatch):
    monkeypatch.setattr(herramientas, "KNOWLEDGE_DIR", str(tmp_path))
    (tmp_path / "negocio_a").mkdir()
    (tmp_path / "negocio_a" / "doc.md").write_text("contenido de negocio a sobre termas", encoding="utf-8")

    # "negocio_c" no tiene carpeta -- fail-safe: sin contexto, NUNCA cae a
    # la raiz de /knowledge/ ni a la carpeta de otro negocio.
    resultado = herramientas.buscar_en_knowledge("contenido termas", "negocio_c")
    assert resultado == ""


def test_negocio_codigo_none_no_recibe_contexto(tmp_path, monkeypatch):
    monkeypatch.setattr(herramientas, "KNOWLEDGE_DIR", str(tmp_path))
    (tmp_path / "negocio_a").mkdir()
    (tmp_path / "negocio_a" / "doc.md").write_text("contenido de negocio a sobre termas", encoding="utf-8")

    resultado = herramientas.buscar_en_knowledge("contenido termas", None)
    assert resultado == ""


def test_archivos_sueltos_en_la_raiz_de_knowledge_nunca_se_devuelven(tmp_path, monkeypatch):
    """Ningún negocio_codigo (ni None) debe poder leer accidentalmente un
    archivo que quedó en la raíz de /knowledge/ — la búsqueda es SIEMPRE
    dentro de una subcarpeta de negocio, nunca en la raíz."""
    monkeypatch.setattr(herramientas, "KNOWLEDGE_DIR", str(tmp_path))
    (tmp_path / "archivo_suelto.md").write_text("informacion sensible sin negocio asignado", encoding="utf-8")
    (tmp_path / "negocio_a").mkdir()
    (tmp_path / "negocio_a" / "doc.md").write_text("contenido de negocio a", encoding="utf-8")

    resultado = herramientas.buscar_en_knowledge("informacion sensible sin negocio asignado", "negocio_a")
    assert "sensible" not in resultado


# ---------------------------------------------------------------------------
# Regresión — el contenido real de Cálidda sigue siendo encontrable
# ---------------------------------------------------------------------------

def test_busqueda_real_de_calidda_sigue_funcionando_tras_la_migracion_de_carpeta():
    """Sin monkeypatch -- contra el /knowledge/calidda/ real del repo,
    confirma que mover los 8 archivos no rompió la búsqueda."""
    resultado = herramientas.buscar_en_knowledge(
        "contrato de financiamiento de gasodomesticos", "calidda",
    )
    assert resultado != ""
    assert "financiamiento" in resultado.lower()


def test_knowledge_dir_raiz_ya_no_tiene_archivos_md_o_txt_de_calidda():
    """Confirma la migración física: ya no quedan .md/.txt sueltos en la
    raíz de /knowledge/ (los que quedan, los 2 CSV, son respaldo inerte de
    importación de catálogo — no los busca esta función, ver
    agent/tools.py comentario en obtener_contexto_relevante)."""
    raiz = herramientas.KNOWLEDGE_DIR
    sueltos = [
        f for f in os.listdir(raiz)
        if os.path.isfile(os.path.join(raiz, f)) and (f.endswith(".md") or f.endswith(".txt"))
    ]
    assert sueltos == []


# ---------------------------------------------------------------------------
# Integración — obtener_contexto_relevante propaga negocio_codigo
# ---------------------------------------------------------------------------

async def test_obtener_contexto_relevante_propaga_negocio_codigo(tmp_path, monkeypatch):
    monkeypatch.setattr(herramientas, "KNOWLEDGE_DIR", str(tmp_path))
    (tmp_path / "negocio_x").mkdir()
    (tmp_path / "negocio_x" / "doc.md").write_text(
        "Politica exclusiva del negocio x sobre garantias extendidas.", encoding="utf-8",
    )

    contexto = await herramientas.obtener_contexto_relevante(
        "garantias extendidas politica", negocio_codigo="negocio_x",
    )
    assert "garantias extendidas" in contexto.lower()

    contexto_otro = await herramientas.obtener_contexto_relevante(
        "garantias extendidas politica", negocio_codigo="negocio_y",
    )
    assert "negocio x" not in contexto_otro.lower()


# ---------------------------------------------------------------------------
# End-to-end — _armar_bloques_contexto (vía generar_respuesta) resuelve el
# codigo del Negocio real y aísla su conocimiento
# ---------------------------------------------------------------------------

async def test_generar_respuesta_resuelve_codigo_de_negocio_para_aislar_conocimiento(tmp_path, monkeypatch):
    """No llama a la API real de Claude (sin credenciales en este entorno
    de test) -- verifica hasta el punto en que `_armar_bloques_contexto`
    resuelve `negocio_codigo` y arma el bloque de contexto, que es
    exactamente lo que este hallazgo necesitaba corregir."""
    monkeypatch.setattr(herramientas, "KNOWLEDGE_DIR", str(tmp_path))
    negocio = await mem.crear_negocio("Negocio E2E", "g43k-e2e")
    (tmp_path / negocio["codigo"]).mkdir()
    (tmp_path / negocio["codigo"] / "doc.md").write_text(
        "Informacion end to end exclusiva de este negocio de prueba.", encoding="utf-8",
    )

    bloques = await brain._armar_bloques_contexto(
        "informacion end to end exclusiva", historial=[], lead=None, negocio_id=negocio["id"],
    )
    texto = "\n".join(bloques)
    assert "end to end exclusiva" in texto.lower()


async def test_generar_respuesta_con_negocio_id_none_no_filtra_conocimiento_de_nadie(tmp_path, monkeypatch):
    monkeypatch.setattr(herramientas, "KNOWLEDGE_DIR", str(tmp_path))
    (tmp_path / "otro_negocio").mkdir()
    (tmp_path / "otro_negocio" / "doc.md").write_text("contenido que no deberia aparecer", encoding="utf-8")

    bloques = await brain._armar_bloques_contexto(
        "contenido que no deberia aparecer", historial=[], lead=None, negocio_id=None,
    )
    texto = "\n".join(bloques)
    assert "no deberia aparecer" not in texto.lower()
