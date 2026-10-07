"""El script de plantilla usa el único negocio activo si no se indica --negocio-id."""
import pytest

from scripts.configurar_plantilla_retomar import resolver_negocio_id


def test_id_explicito_gana():
    assert resolver_negocio_id("n-2", [{"id": "n-1", "activo": True}]) == "n-2"


def test_un_solo_negocio_activo_se_usa_solo():
    negocios = [{"id": "n-1", "activo": True, "nombre": "Gaso+"}, {"id": "n-9", "activo": False}]
    assert resolver_negocio_id(None, negocios) == "n-1"


def test_varios_o_ninguno_exigen_id():
    varios = [{"id": "n-1", "activo": True, "nombre": "A"}, {"id": "n-2", "activo": True, "nombre": "B"}]
    with pytest.raises(ValueError) as e:
        resolver_negocio_id(None, varios)
    assert "n-1" in str(e.value) and "n-2" in str(e.value)
    with pytest.raises(ValueError):
        resolver_negocio_id(None, [])
