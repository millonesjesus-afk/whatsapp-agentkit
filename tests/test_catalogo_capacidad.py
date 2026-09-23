# tests/test_catalogo_capacidad.py — Gate 2026-09-23: hallazgo real, Gabi
# solo ofrecía termas de 5.5L (la capacidad más barata) aunque el cliente
# necesitaba más — no porque el cliente lo haya pedido, sino porque
# `buscar_productos` nunca distinguía productos por capacidad (ese dato solo
# vive en DESCRIPCIÓN, texto libre) y el corte por `limite` tomaba
# sencillamente las más baratas, que en un catálogo real son casi todas de
# la capacidad chica (ej. Cálidda: 22 termas de 5.5L vs. 13 de 10L).

from agent import memory as mem
from agent.tools import _capacidad_de, _capacidad_pedida_en_mensaje, buscar_productos


async def _crear_terma(negocio_id: str, codigo: str, marca: str, descripcion: str, precio: str):
    return await mem.crear_producto(
        {
            "tipo": "terma", "sub_tipo": "a gas", "marca": marca,
            "descripcion": descripcion, "codigo_hana": codigo, "precio": precio,
        },
        autor="test", negocio_id=negocio_id,
    )


# ── _capacidad_de / _capacidad_pedida_en_mensaje — extracción pura ──────────

def test_capacidad_de_reconoce_formatos_reales_del_catalogo():
    assert _capacidad_de({"DESCRIPCIÓN": "TERMA SOLE 5.5 LT - BASIC"}) == 5.5
    assert _capacidad_de({"DESCRIPCIÓN": "TERMA RHEEM 8 LT TIRO NATURAL + CONEXIÓN"}) == 8.0
    assert _capacidad_de({"DESCRIPCIÓN": "TERMA AQUAMAXX DE PASO A GN TIPO A 10 LTS/MIN + KIT"}) == 10.0
    assert _capacidad_de({"DESCRIPCIÓN": "TERMA FDV 12 LITROS"}) == 12.0


def test_capacidad_de_none_si_no_hay_capacidad_en_la_descripcion():
    assert _capacidad_de({"DESCRIPCIÓN": "TERMOTANQUE ELÉCTRICO 50L"}) is None  # "50L" sin espacio/unidad reconocida
    assert _capacidad_de({"DESCRIPCIÓN": "KIT DE INSTALACIÓN"}) is None
    assert _capacidad_de({}) is None


def test_capacidad_pedida_en_mensaje_exige_la_unidad_pegada_al_numero():
    """El caso que justifica exigir la unidad: "somos 5 personas" NO debe
    interpretarse como un pedido de "5 litros" — son cosas completamente
    distintas."""
    assert _capacidad_pedida_en_mensaje("quiero una terma de 12 litros") == 12.0
    assert _capacidad_pedida_en_mensaje("necesito 18 lt de capacidad") == 18.0
    assert _capacidad_pedida_en_mensaje("somos 5 personas en casa") is None
    assert _capacidad_pedida_en_mensaje("mi hijo tiene 8 años") is None


# ── buscar_productos — el comportamiento real que ve Gabi ──────────────────

async def test_termas_de_mayor_capacidad_ya_no_quedan_tapadas_por_las_baratas():
    """Reproduce el hallazgo real: muchas termas baratas de 5.5L y pocas más
    caras de 10L/18L — un cliente que solo dice "terma" (sin pedir una
    capacidad puntual) debe seguir viendo variedad, no solo la capacidad
    barata repetida."""
    negocio = await mem.crear_negocio("Negocio Capacidad 1", "g-cap-01")
    for i in range(6):
        await _crear_terma(negocio["id"], f"HANA-CAP1-{i:03d}", f"Marca{i}", f"Terma modelo {i} 5.5 LT", str(400 + i * 10))
    await _crear_terma(negocio["id"], "HANA-CAP1-010", "MarcaGrande", "Terma familiar 18 LT", "1200")
    await _crear_terma(negocio["id"], "HANA-CAP1-011", "MarcaMedia", "Terma media 10 LT", "800")

    resultado = await buscar_productos("quiero una terma a gas para mi casa", negocio["id"], limite=5)

    capacidades = {p.get("DESCRIPCIÓN") for p in resultado}
    assert len(resultado) == 5
    assert any("18 LT" in d for d in capacidades)  # la de mayor capacidad SÍ aparece
    assert any("10 LT" in d for d in capacidades)  # la intermedia también
    # Sigue ordenado de menor a mayor precio dentro de lo que se muestra.
    precios = [float(p["PRECIO"]) for p in resultado]
    assert precios == sorted(precios)


async def test_pedido_explicito_de_capacidad_prioriza_esa_capacidad():
    negocio = await mem.crear_negocio("Negocio Capacidad 2", "g-cap-02")
    for i in range(6):
        await _crear_terma(negocio["id"], f"HANA-CAP2-{i:03d}", f"Marca{i}", f"Terma modelo {i} 5.5 LT", str(400 + i * 10))
    await _crear_terma(negocio["id"], "HANA-CAP2-010", "MarcaGrande", "Terma familiar 18 LT", "1200")

    resultado = await buscar_productos("quiero una terma de 18 litros", negocio["id"], limite=5)

    assert resultado[0]["DESCRIPCIÓN"] == "Terma familiar 18 LT"  # la pedida, primera


async def test_pocos_candidatos_no_se_alteran_por_la_diversificacion():
    """Si el total de candidatos ya entra dentro del límite, el resultado es
    el mismo conjunto de siempre (solo por precio) — la diversificación no
    inventa recortes donde no hacían falta."""
    negocio = await mem.crear_negocio("Negocio Capacidad 3", "g-cap-03")
    await _crear_terma(negocio["id"], "HANA-CAP3-001", "Rheem", "Terma Rheem 8 LT", "500")
    await _crear_terma(negocio["id"], "HANA-CAP3-002", "Rheem", "Terma Rheem 10 LT", "700")

    resultado = await buscar_productos("busco una terma Rheem", negocio["id"], limite=8)

    assert len(resultado) == 2
    assert [p["PRECIO"] for p in resultado] == ["500", "700"]


async def test_busqueda_por_marca_sigue_funcionando_igual_que_antes():
    """Regresión: mencionar una marca puntual sigue priorizándola por sobre
    productos que solo comparten el tipo — sin cambios de comportamiento."""
    negocio = await mem.crear_negocio("Negocio Capacidad 4", "g-cap-04")
    await _crear_terma(negocio["id"], "HANA-CAP4-001", "Rheem", "Terma Rheem 8 LT", "500")
    for i in range(5):
        await _crear_terma(negocio["id"], f"HANA-CAP4-{i+10:03d}", "OtraMarca", f"Terma genérica {i} 5.5 LT", str(300 + i))

    resultado = await buscar_productos("quiero una terma Rheem", negocio["id"], limite=8)

    assert resultado[0]["MARCA"] == "Rheem"
