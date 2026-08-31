# tests/test_gate54_campana_por_nombre_scoped.py — Gate 5.4, hallazgo B del
# checkpoint anterior: obtener_campana_por_nombre() no filtraba por
# negocio_id. Con Campana.nombre sin restricción UNIQUE, dos Negocios podían
# tener una campaña con el MISMO nombre — sin candado, se podía devolver la
# fila del Negocio equivocado (precio/promoción cruzados hacia el contexto
# de IA de un cliente de otro Negocio). Datos sintéticos únicamente
# (crear_negocio), mismo criterio que el resto de Gate 5.3/5.4.

from agent import memory as mem


async def _negocio(codigo: str):
    return await mem.crear_negocio(f"Negocio {codigo}", codigo)


async def test_obtener_campana_por_nombre_no_cruza_negocios_con_nombre_igual():
    """El caso central del hallazgo: mismo nombre de campaña en dos
    Negocios, cada uno con su propia promoción — nunca debe mezclarse."""
    negocio_a = await _negocio("camp-a")
    negocio_b = await _negocio("camp-b")

    await mem.crear_campana(
        "Promo Verano", "texto_saludo", "promo verano",
        producto_promocional="Terma A", precio_promocional="999",
        negocio_id=negocio_a["id"],
    )
    await mem.crear_campana(
        "Promo Verano", "texto_saludo", "promo verano",
        producto_promocional="Terma B", precio_promocional="1500",
        negocio_id=negocio_b["id"],
    )

    campana_a = await mem.obtener_campana_por_nombre("Promo Verano", negocio_a["id"])
    campana_b = await mem.obtener_campana_por_nombre("Promo Verano", negocio_b["id"])

    assert campana_a["producto_promocional"] == "Terma A"
    assert campana_b["producto_promocional"] == "Terma B"
    assert campana_a["negocio_id"] == negocio_a["id"]
    assert campana_b["negocio_id"] == negocio_b["id"]


async def test_obtener_campana_por_nombre_negocio_sin_esa_campana_devuelve_none():
    negocio_a = await _negocio("camp-c")
    negocio_b = await _negocio("camp-d")
    await mem.crear_campana(
        "Solo en A", "texto_saludo", "solo en a", negocio_id=negocio_a["id"],
    )

    assert await mem.obtener_campana_por_nombre("Solo en A", negocio_b["id"]) is None
    assert await mem.obtener_campana_por_nombre("Solo en A", negocio_a["id"]) is not None


async def test_obtener_campana_por_nombre_exige_negocio_id():
    """negocio_id es obligatorio en la firma (Python, no runtime check) —
    ningún llamador puede omitirlo ni caer en un default silencioso."""
    import pytest

    with pytest.raises(TypeError):
        await mem.obtener_campana_por_nombre("Cualquiera")


async def test_corregir_patrones_desalineados_scoped_y_fail_closed_sin_negocio():
    """corregir_patrones_desalineados (arranque del servidor) solo corrige
    la campaña del Negocio que se le pasa, y no hace nada si negocio_id es
    None (Canal/bootstrap no resuelto) — nunca adivina ni cae a Cálidda."""
    from agent.campanas import corregir_patrones_desalineados, PATRONES_CORREGIDOS

    negocio_a = await _negocio("camp-e")
    negocio_b = await _negocio("camp-f")
    nombre, patron_correcto = next(iter(PATRONES_CORREGIDOS.items()))

    await mem.crear_campana(nombre, "texto_saludo", "patron viejo desalineado", negocio_id=negocio_a["id"])
    await mem.crear_campana(nombre, "texto_saludo", "patron viejo desalineado", negocio_id=negocio_b["id"])

    await corregir_patrones_desalineados(None)  # fail-closed: no debe tocar nada
    campana_a_sin_tocar = await mem.obtener_campana_por_nombre(nombre, negocio_a["id"])
    assert campana_a_sin_tocar["patron"] == "patron viejo desalineado"

    await corregir_patrones_desalineados(negocio_a["id"])
    campana_a = await mem.obtener_campana_por_nombre(nombre, negocio_a["id"])
    campana_b = await mem.obtener_campana_por_nombre(nombre, negocio_b["id"])
    assert campana_a["patron"] == patron_correcto
    assert campana_b["patron"] == "patron viejo desalineado"  # intacta, otro Negocio
