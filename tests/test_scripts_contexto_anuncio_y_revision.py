# tests/test_scripts_contexto_anuncio_y_revision.py — modo del contexto del anuncio y revisión previa al despliegue (solo lectura).
from pathlib import Path

from agent import contexto_anuncio as ca, memory as mem
from scripts import configurar_contexto_anuncio as conf
from scripts import revisar_antes_de_desplegar as rev


async def test_el_modo_del_anuncio_se_muestra_y_se_cambia_sin_tocar_otros_negocios():
    negocio = await mem.crear_negocio("Negocio ca-1", "ca-1")
    otro = await mem.crear_negocio("Negocio ca-2", "ca-2")
    base = ["--negocio-id", negocio["id"]]
    assert await conf.main(base) == {"modo_anterior": "sombra", "modo": "sombra", "cambio": False}
    assert (await conf.main(base + ["--modo", "activo"])) == {"modo_anterior": "sombra", "modo": "activo", "cambio": True}
    assert await mem.obtener_configuracion(ca.CLAVE_MODO, "sombra", negocio_id=otro["id"]) == "sombra"      # el otro negocio no cambia
    assert (await conf.main(base + ["--modo", "sombra"]))["modo"] == "sombra"


def test_una_sola_cabeza_de_migracion_en_el_repositorio():
    assert len(rev.cabezas_de_migracion()) == 1


def test_cabezas_de_migracion_detecta_una_bifurcacion(tmp_path: Path):
    (tmp_path / "a1.py").write_text("revision = 'a1'\ndown_revision = None\n", encoding="utf-8")
    (tmp_path / "b2.py").write_text("revision: str = 'b2'\ndown_revision: Union[str, None] = 'a1'\n", encoding="utf-8")
    assert rev.cabezas_de_migracion(tmp_path) == ["b2"]
    (tmp_path / "c3.py").write_text("revision = 'c3'\ndown_revision = 'a1'\n", encoding="utf-8")
    assert rev.cabezas_de_migracion(tmp_path) == ["b2", "c3"]


def test_diagnostico():
    uno = [{"sha": "x", "autor": "A", "fecha": "2026-10-25", "mensaje": "m"}]
    assert rev.diagnostico(uno, [], [], ["h1"]) == []
    assert "ATRASADA 1" in rev.diagnostico(uno, uno, [], ["h1"])[0]
    assert "2 cabezas de migración" in rev.diagnostico(uno, [], [], ["h1", "h2"])[0]
    dos_autores = uno + [{"sha": "y", "autor": "B", "fecha": "2026-10-25", "mensaje": "n"}]
    assert "más de un autor" in rev.diagnostico(dos_autores, [], [], ["h1"])[0]


def test_commits_entre_en_el_repositorio_real():
    # HEAD..HEAD no tiene commits; HEAD~1..HEAD tiene exactamente uno (si el repositorio tiene historia)
    assert rev.commits_entre("HEAD", "HEAD") == []
    uno = rev.commits_entre("HEAD~1", "HEAD")
    assert len(uno) == 1 and set(uno[0]) == {"sha", "autor", "fecha", "mensaje"}
