# tests/test_tipo_evento_cabe_en_columna.py — SQLite no impone el largo de un
# VARCHAR, así que un tipo de evento demasiado largo pasaba todos los tests y
# recién fallaba en Postgres (2026-10-02: cerrado_definitivamente_automatico,
# 34 caracteres, tumbó los Cron de cierre; rotado_automatico_sin_respuesta, 31,
# habría tumbado el de rotación). Este test lee el código fuente y exige que
# TODO tipo de evento escrito en él quepa en la columna.

import re
from pathlib import Path

from agent import memory as mem

RAIZ = Path(__file__).resolve().parent.parent
LITERAL = re.compile(r'"([a-z][a-z_]+)"')
# `tipo="x"` y `tipo="x" if ... else "y"` pasados a registrar_evento_lead, y los
# `"tipo": "x"` de los eventos que arma dashboard.py para el Timeline.
FRAGMENTO_TIPO = re.compile(r'tipo\s*=\s*([^,\n]*)|"tipo":\s*"([a-z_]+)"')


def _tipos_de_evento_en_el_codigo() -> set[str]:
    tipos: set[str] = set()
    for ruta in (RAIZ / "agent").glob("*.py"):
        for m in FRAGMENTO_TIPO.finditer(ruta.read_text(encoding="utf-8")):
            if m.group(2):
                tipos.add(m.group(2))
            elif m.group(1):
                tipos.update(LITERAL.findall(m.group(1)))
    return tipos


def test_la_columna_tipo_tiene_el_largo_declarado():
    assert mem.EventoLead.__table__.c.tipo.type.length == mem.TIPO_EVENTO_LARGO_MAX >= 60


def test_el_detector_encuentra_los_tipos_que_antes_no_cabian():
    tipos = _tipos_de_evento_en_el_codigo()
    assert {"cerrado_definitivamente_automatico", "rotado_automatico_sin_respuesta"} <= tipos


def test_reabierto_por_cliente_se_detecta_y_cabe_hasta_en_30():
    # P4 (2026-10-06): el tipo nuevo respeta incluso el VARCHAR(30) viejo, por
    # si alguna base todavía no corrió la migración que lo amplió a 60.
    tipos = _tipos_de_evento_en_el_codigo()
    assert "reabierto_por_cliente" in tipos
    assert len("reabierto_por_cliente") <= 30


def test_todo_tipo_de_evento_cabe_en_la_columna():
    demasiado_largos = {t: len(t) for t in _tipos_de_evento_en_el_codigo() if len(t) > mem.TIPO_EVENTO_LARGO_MAX}
    assert not demasiado_largos, f"Tipos de evento que no caben en eventos_lead.tipo: {demasiado_largos}"
