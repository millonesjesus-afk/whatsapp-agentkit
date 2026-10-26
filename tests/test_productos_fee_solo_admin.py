"""Los fee de un producto (proveedor y Cálidda) solo los recibe el admin."""
from agent import dashboard


def _producto():
    return {"id": 1, "descripcion": "SECADORA", "precio": "2999", "fee_prv": "0.18", "fee_clda": "0.18"}


def test_el_admin_recibe_los_fee():
    p = dashboard._sin_fee_si_no_es_admin(_producto(), {"rol": "admin"})
    assert p["fee_prv"] == "0.18" and p["fee_clda"] == "0.18"


def test_los_demas_roles_no_reciben_los_fee_pero_si_el_resto():
    for rol in ("supervisor", "asesor", "vendedor", ""):
        p = dashboard._sin_fee_si_no_es_admin(_producto(), {"rol": rol})
        assert "fee_prv" not in p and "fee_clda" not in p
        assert p["precio"] == "2999" and p["descripcion"] == "SECADORA"


def test_no_modifica_el_producto_original():
    original = _producto()
    dashboard._sin_fee_si_no_es_admin(original, {"rol": "asesor"})
    assert "fee_prv" in original


async def test_el_historial_oculta_los_cambios_de_fee_a_quien_no_es_admin(monkeypatch):
    async def fake_obtener(id, negocio_id):
        return {"id": id}

    async def fake_historial(id):
        return [{"campo": "precio"}, {"campo": "fee_prv"}, {"campo": "fee_clda"}, {"campo": "descripcion"}]

    monkeypatch.setattr(dashboard, "obtener_producto", fake_obtener)
    monkeypatch.setattr(dashboard, "listar_historial_producto", fake_historial)
    r = await dashboard.historial_producto_ruta(1, {"rol": "asesor", "negocio_id": 1})
    assert [h["campo"] for h in __import__("json").loads(r.body)["historial"]] == ["precio", "descripcion"]
    r = await dashboard.historial_producto_ruta(1, {"rol": "admin", "negocio_id": 1})
    assert len(__import__("json").loads(r.body)["historial"]) == 4
