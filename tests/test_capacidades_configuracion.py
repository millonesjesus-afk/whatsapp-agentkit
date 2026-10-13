# tests/test_capacidades_configuracion.py — Gate de unificación de permisos
# (Nueva Experiencia): confirma que `_capacidades_de` emite "configuracion:ver"
# exclusivamente para admin, sin tocar ninguna otra capacidad ya existente.

from agent.dashboard import _capacidades_de


def test_admin_recibe_configuracion_ver():
    assert "configuracion:ver" in _capacidades_de("admin")


def test_supervisor_no_recibe_configuracion_ver():
    assert "configuracion:ver" not in _capacidades_de("supervisor")


def test_asesor_no_recibe_configuracion_ver():
    assert "configuracion:ver" not in _capacidades_de("asesor")


def test_capacidades_previas_de_admin_no_cambian_de_cantidad_inesperada():
    """Regresión mínima: agregar configuracion:ver no debe duplicar ni perder
    ninguna capacidad ya existente para admin."""
    capacidades = _capacidades_de("admin")
    assert len(capacidades) == len(set(capacidades))  # sin duplicados
    for esperada in ("productos:crear", "canales.gestionar", "usuarios.crear", "pipeline:ver"):
        assert esperada in capacidades


# ── Calendario del supervisor (2026-10-12, D1/D2): capacidades propias, sin abrir Configuración ──

def test_calendario_ver_y_editar_son_de_admin_y_supervisor_pero_no_del_asesor():
    for rol in ("admin", "supervisor"):
        capacidades = _capacidades_de(rol)
        assert "calendario:ver" in capacidades and "calendario:editar" in capacidades
    assert "calendario:ver" not in _capacidades_de("asesor") and "calendario:editar" not in _capacidades_de("asesor")


def test_configuracion_ver_sigue_siendo_solo_del_admin_aunque_el_supervisor_tenga_calendario():
    assert "configuracion:ver" in _capacidades_de("admin")
    assert "configuracion:ver" not in _capacidades_de("supervisor")
    assert "configuracion:ver" not in _capacidades_de("asesor")
    assert len(_capacidades_de("supervisor")) == len(set(_capacidades_de("supervisor")))   # sin duplicados
