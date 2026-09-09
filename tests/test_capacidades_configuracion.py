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
