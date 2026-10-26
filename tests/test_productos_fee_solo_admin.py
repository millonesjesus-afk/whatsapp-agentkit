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


async def test_el_buscador_del_catalogo_busca_por_palabra_en_varios_campos_y_nunca_por_fee():
    from agent import memory as mem
    negocio = await mem.crear_negocio("Negocio Busca", "busca1")
    for desc, cod, extra in (
        ("SECADORA MABE 22 KG BLANCO", "4506068", {"comentarios": "PROMOCIONAL MES"}),
        ("SECADORA MABE 24 KG NEGRO", "4508634", {"combo": "PUNTO ADICIONAL"}),
        ("TERMA SOLE 10 L", "4500001", {}),
    ):
        await mem.crear_producto(
            {"tipo": "SECADORA" if "SECAD" in desc else "TERMA", "marca": "MABE" if "MABE" in desc else "SOLE",
             "descripcion": desc, "codigo_hana": cod, "precio": "1000", "fee_prv": "0.77", **extra},
            autor="t", negocio_id=negocio["id"],
        )

    async def buscar(q):
        productos, total = await mem.listar_productos({"q": q}, pagina=1, por_pagina=20, negocio_id=negocio["id"])
        return sorted(p["codigo_hana"] for p in productos), total

    assert (await buscar("secadora negro"))[0] == ["4508634"]          # palabras en cualquier orden
    assert (await buscar("negro secadora"))[0] == ["4508634"]
    assert (await buscar("4506068"))[0] == ["4506068"]                 # por código
    assert (await buscar("promocional"))[0] == ["4506068"]             # por comentarios
    assert (await buscar("punto adicional"))[0] == ["4508634"]         # por combo
    assert (await buscar("mabe 22"))[0] == ["4506068"]
    assert (await buscar("secadora"))[1] == 2 and (await buscar(""))[1] == 3
    assert (await buscar("0.77"))[0] == []                             # los fee no se pueden buscar
