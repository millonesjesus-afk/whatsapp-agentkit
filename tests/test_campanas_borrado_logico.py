# tests/test_campanas_borrado_logico.py — 2026-11-04: eliminar una campaña es un borrado LÓGICO y se puede restaurar.
# Datos sintéticos únicamente.

import json

import pytest
from fastapi import HTTPException

from agent import dashboard, memory as mem


def _json(r) -> dict:
    return json.loads(r.body)


def _admin(negocio):
    return {"negocio_id": negocio["id"], "username": "admin_x", "rol": "admin"}


async def _negocio(codigo):
    return await mem.crear_negocio(f"Negocio {codigo}", codigo)


async def _con_anuncios(negocio, nombre, *source_ids):
    c = await mem.crear_campana(nombre, "por_anuncio", source_ids[0], negocio_id=negocio["id"])
    for s in source_ids:
        await mem.guardar_regla_anuncio(negocio["id"], s, c["id"], autor="t")
    return c


async def test_eliminar_oculta_la_campana_en_todas_partes_y_libera_sus_anuncios():
    n = await _negocio("bl-1")
    c = await _con_anuncios(n, "Promo", "111", "222")

    assert await mem.eliminar_campana(c["id"], n["id"], eliminado_por="admin_x") is True

    assert [x["id"] for x in await mem.listar_campanas(n["id"])] == []
    assert [x["id"] for x in await mem.listar_campanas(n["id"], solo_activas=True)] == []
    assert await mem.obtener_campana(c["id"]) is None
    assert await mem.obtener_campana_por_nombre("Promo", n["id"]) is None
    assert await mem.obtener_reglas_anuncio(n["id"]) == {}  # sus anuncios quedan libres, como antes

    eliminadas = await mem.listar_campanas_eliminadas(n["id"])
    assert [(e["id"], e["eliminado_por"], e["anuncios"]) for e in eliminadas] == [(c["id"], "admin_x", ["111", "222"])]
    assert [x["id"] for x in await mem.listar_campanas(n["id"], incluir_eliminadas=True)] == [c["id"]]


async def test_una_eliminada_ya_no_se_puede_eliminar_ni_editar_de_nuevo():
    n = await _negocio("bl-2")
    c = await _con_anuncios(n, "Promo", "111")
    await mem.eliminar_campana(c["id"], n["id"])
    assert await mem.eliminar_campana(c["id"], n["id"]) is False
    with pytest.raises(HTTPException) as e:
        await dashboard._verificar_ownership_campana(_admin(n), c["id"])
    assert e.value.status_code == 404


async def test_restaurar_vuelve_desactivada_y_revincula_sus_anuncios():
    n = await _negocio("bl-3")
    c = await _con_anuncios(n, "Promo", "111", "222")
    await mem.eliminar_campana(c["id"], n["id"])

    r = _json(await dashboard.restaurar_campana_json(campana_id=c["id"], usuario=_admin(n), _csrf=None))

    assert r["ok"] is True and r["activa"] is False
    assert r["anuncios_restaurados"] == ["111", "222"] and r["anuncios_no_restaurados"] == []
    viva = await mem.obtener_campana(c["id"])
    assert viva is not None and viva["activa"] is False  # no detecta leads hasta que un admin la active
    assert await mem.obtener_reglas_anuncio(n["id"]) == {"111": c["id"], "222": c["id"]}
    assert await mem.listar_campanas_eliminadas(n["id"]) == []


async def test_restaurar_no_pisa_un_anuncio_que_otra_campana_ya_tomo():
    n = await _negocio("bl-4")
    c = await _con_anuncios(n, "Promo", "111", "222")
    await mem.eliminar_campana(c["id"], n["id"])
    otra = await _con_anuncios(n, "Otra", "222")  # se quedó con uno de los anuncios liberados

    r = _json(await dashboard.restaurar_campana_json(campana_id=c["id"], usuario=_admin(n), _csrf=None))

    assert r["anuncios_restaurados"] == ["111"] and r["anuncios_no_restaurados"] == ["222"]
    assert await mem.obtener_reglas_anuncio(n["id"]) == {"111": c["id"], "222": otra["id"]}


async def test_restaurar_con_el_nombre_ocupado_da_409_y_no_cambia_nada():
    n = await _negocio("bl-5")
    c = await _con_anuncios(n, "Promo", "111")
    await mem.eliminar_campana(c["id"], n["id"])
    await mem.crear_campana("promo", "texto_saludo", "hola", negocio_id=n["id"])  # mismo nombre, otra mayúscula

    with pytest.raises(HTTPException) as e:
        await dashboard.restaurar_campana_json(campana_id=c["id"], usuario=_admin(n), _csrf=None)
    assert e.value.status_code == 409
    assert [x["id"] for x in await mem.listar_campanas_eliminadas(n["id"])] == [c["id"]]


async def test_restaurar_errores_404_y_409_y_aislamiento_entre_negocios():
    a, b = await _negocio("bl-6a"), await _negocio("bl-6b")
    viva = await mem.crear_campana("Viva", "texto_saludo", "hola", negocio_id=a["id"])
    eliminada_b = await mem.crear_campana("De B", "texto_saludo", "hola", negocio_id=b["id"])
    await mem.eliminar_campana(eliminada_b["id"], b["id"])

    for campana_id, codigo in ((9999, 404), (eliminada_b["id"], 404), (viva["id"], 409)):
        with pytest.raises(HTTPException) as e:
            await dashboard.restaurar_campana_json(campana_id=campana_id, usuario=_admin(a), _csrf=None)
        assert e.value.status_code == codigo
    assert [x["id"] for x in await mem.listar_campanas_eliminadas(b["id"])] == [eliminada_b["id"]]
    assert await mem.listar_campanas_eliminadas(a["id"]) == []


async def test_listado_json_de_eliminadas_trae_quien_cuando_y_anuncios():
    n = await _negocio("bl-7")
    c = await _con_anuncios(n, "Promo", "111")
    await mem.eliminar_campana(c["id"], n["id"], eliminado_por="admin_x")
    cuerpo = _json(await dashboard.campanas_eliminadas_json(usuario=_admin(n)))["eliminadas"]
    assert cuerpo[0]["nombre"] == "Promo" and cuerpo[0]["anuncios"] == ["111"]
    assert cuerpo[0]["eliminado_por"] == "admin_x" and cuerpo[0]["eliminado_en"].endswith("Z")


def test_rutas_nuevas_son_solo_admin_y_restaurar_exige_csrf():
    def ruta(path, metodo):
        return next(r for r in dashboard.router.routes if getattr(r, "path", None) == path and metodo in r.methods)

    for path, metodo in (("/dashboard/campanas/eliminadas.json", "GET"), ("/dashboard/campanas/{campana_id}/restaurar.json", "POST")):
        deps = [repr(d.call) + repr(getattr(d.call, "__closure__", None)) for d in ruta(path, metodo).dependant.dependencies]
        assert any("admin" in t or "requiere_rol" in t for t in deps)
    nombres = [d.call.__name__ for d in ruta("/dashboard/campanas/{campana_id}/restaurar.json", "POST").dependant.dependencies]
    assert "verificar_csrf" in nombres


async def test_con_conversaciones_sigue_sin_poder_eliminarse():
    n = await _negocio("bl-8")
    canal = await mem.crear_canal_whatsapp(nombre="Canal", phone_number_id="70000009999", negocio_id=n["id"])
    c = await mem.crear_campana("Con actividad", "texto_saludo", "hola", negocio_id=n["id"])
    await mem.resolver_conversation_activa("51900700001", n["id"], canal["id"], campana_origen_id=c["id"])
    assert await mem.eliminar_campana(c["id"], n["id"]) is False
    assert (await mem.obtener_campana(c["id"])) is not None
    assert await mem.listar_campanas_eliminadas(n["id"]) == []
