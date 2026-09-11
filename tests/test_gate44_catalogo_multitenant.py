# tests/test_gate44_catalogo_multitenant.py — Gate 4.4, Producto/Catálogo
# multi-tenant. Cobertura de aislamiento exigida por el Gate: dos Negocios
# sintéticos (A/B), cada operación (listar, buscar, código HANA, crear,
# editar, desactivar, importar, validar venta, Gabi) probada en ambas
# direcciones — A nunca ve/toca datos de B, y viceversa.

import csv
import io

from agent import brain, memory as mem
from agent.tools import buscar_productos, obtener_producto_por_codigo, obtener_familia_producto
from agent.services.servicio_comercial import servicio_comercial


async def _dos_negocios_con_producto():
    """Fixture compartida: Negocio A con Producto A, Negocio B con Producto
    B — mismo tipo/sub_tipo para que una búsqueda por texto libre matchee
    a ambos si el aislamiento fallara."""
    negocio_a = await mem.crear_negocio("Negocio A", "g44a")
    negocio_b = await mem.crear_negocio("Negocio B", "g44b")
    producto_a = await mem.crear_producto(
        {"tipo": "terma", "sub_tipo": "a gas", "marca": "MarcaA", "descripcion": "Terma A",
         "codigo_hana": "HANA-A-001", "precio": "500"},
        autor="test", negocio_id=negocio_a["id"],
    )
    producto_b = await mem.crear_producto(
        {"tipo": "terma", "sub_tipo": "a gas", "marca": "MarcaB", "descripcion": "Terma B",
         "codigo_hana": "HANA-B-001", "precio": "600"},
        autor="test", negocio_id=negocio_b["id"],
    )
    return negocio_a, negocio_b, producto_a, producto_b


# ---------------------------------------------------------------------------
# Modelo / migración
# ---------------------------------------------------------------------------

def test_producto_tiene_negocio_id_not_null_con_fk_e_indice():
    tabla = mem.Producto.__table__
    columna = tabla.columns["negocio_id"]
    assert columna.nullable is False
    assert columna.index is True
    fks = {fk.column.table.name for fk in columna.foreign_keys}
    assert "negocios" in fks


# ---------------------------------------------------------------------------
# Aislamiento — listar_productos_activos / listar_productos (panel)
# ---------------------------------------------------------------------------

async def test_listar_productos_activos_A_solo_ve_A():
    negocio_a, negocio_b, producto_a, producto_b = await _dos_negocios_con_producto()

    productos_a = await mem.listar_productos_activos(negocio_a["id"])
    productos_b = await mem.listar_productos_activos(negocio_b["id"])

    marcas_a = {p["MARCA"] for p in productos_a}
    marcas_b = {p["MARCA"] for p in productos_b}
    assert "MarcaA" in marcas_a and "MarcaB" not in marcas_a
    assert "MarcaB" in marcas_b and "MarcaA" not in marcas_b


async def test_listar_productos_panel_solo_ve_su_negocio():
    negocio_a, negocio_b, producto_a, producto_b = await _dos_negocios_con_producto()

    productos_a, total_a = await mem.listar_productos({}, pagina=1, por_pagina=20, negocio_id=negocio_a["id"])
    ids_a = {p["id"] for p in productos_a}
    assert producto_a["id"] in ids_a
    assert producto_b["id"] not in ids_a
    assert total_a == 1


# ---------------------------------------------------------------------------
# Búsqueda (Gabi / cierre de venta / campañas comparten esta función)
# ---------------------------------------------------------------------------

async def test_buscar_productos_A_no_encuentra_producto_exclusivo_de_B():
    negocio_a, negocio_b, producto_a, producto_b = await _dos_negocios_con_producto()

    resultados_a = await buscar_productos("terma a gas", negocio_a["id"])
    marcas_a = {p.get("MARCA") for p in resultados_a}
    assert "MarcaA" in marcas_a
    assert "MarcaB" not in marcas_a


async def test_buscar_productos_negocio_id_none_falla_cerrado():
    """El Canal no resolvió Negocio todavía (webhook) — nunca debe caer a
    buscar en el catálogo de cualquier Negocio."""
    await _dos_negocios_con_producto()
    resultados = await buscar_productos("terma a gas", None)
    assert resultados == []


# ---------------------------------------------------------------------------
# Código HANA
# ---------------------------------------------------------------------------

async def test_codigo_hana_de_B_no_se_ve_desde_A():
    negocio_a, negocio_b, producto_a, producto_b = await _dos_negocios_con_producto()

    resultado = await mem.obtener_producto_por_codigo_hana("HANA-B-001", negocio_a["id"])
    assert resultado is None

    resultado_propio = await mem.obtener_producto_por_codigo_hana("HANA-A-001", negocio_a["id"])
    assert resultado_propio is not None
    assert resultado_propio["MARCA"] == "MarcaA"


async def test_obtener_producto_por_codigo_tools_respeta_negocio():
    negocio_a, negocio_b, producto_a, producto_b = await _dos_negocios_con_producto()

    assert await obtener_producto_por_codigo("HANA-B-001", negocio_a["id"]) is None
    assert (await obtener_producto_por_codigo("HANA-A-001", negocio_a["id"]))["MARCA"] == "MarcaA"
    # negocio_id=None falla cerrado, igual que buscar_productos.
    assert await obtener_producto_por_codigo("HANA-A-001", None) is None


async def test_obtener_familia_producto_no_cruza_negocio():
    negocio_a, negocio_b, producto_a, producto_b = await _dos_negocios_con_producto()
    # Segundo producto en B, mismo modelo base que producto_b, para que
    # "familia" tenga algo que agrupar sin salirse de B.
    await mem.crear_producto(
        {"tipo": "terma", "sub_tipo": "a gas", "marca": "MarcaB", "descripcion": "Terma B + CONEXIÓN",
         "codigo_hana": "HANA-B-002", "precio": "650"},
        autor="test", negocio_id=negocio_b["id"],
    )
    familia_desde_a = await obtener_familia_producto("HANA-B-001", negocio_a["id"])
    assert familia_desde_a == []  # el ancla ni siquiera resuelve desde A


# ---------------------------------------------------------------------------
# Creación
# ---------------------------------------------------------------------------

async def test_crear_producto_queda_ligado_al_negocio_del_creador():
    negocio_a, _, _, _ = await _dos_negocios_con_producto()
    nuevo = await mem.crear_producto(
        {"tipo": "cocina", "marca": "MarcaNueva", "descripcion": "Cocina nueva", "precio": "300"},
        autor="test", negocio_id=negocio_a["id"],
    )
    async with mem.async_session() as session:
        fila = await session.get(mem.Producto, nuevo["id"])
        assert fila.negocio_id == negocio_a["id"]


# ---------------------------------------------------------------------------
# Edición — A no puede editar producto de B
# ---------------------------------------------------------------------------

async def test_editar_producto_de_otro_negocio_devuelve_none():
    negocio_a, negocio_b, producto_a, producto_b = await _dos_negocios_con_producto()

    resultado = await mem.editar_producto(
        producto_b["id"], {"precio": "1"}, version_esperada=producto_b["version"],
        autor="test", negocio_id=negocio_a["id"],
    )
    assert resultado is None

    # Confirma que NO se aplicó nada — mismo precio, misma versión.
    intacto = await mem.obtener_producto(producto_b["id"], negocio_b["id"])
    assert intacto["precio"] == "600"
    assert intacto["version"] == producto_b["version"]


async def test_editar_producto_propio_si_funciona():
    negocio_a, _, producto_a, _ = await _dos_negocios_con_producto()
    resultado = await mem.editar_producto(
        producto_a["id"], {"precio": "550"}, version_esperada=producto_a["version"],
        autor="test", negocio_id=negocio_a["id"],
    )
    assert resultado is not None
    assert resultado["precio"] == "550"


# ---------------------------------------------------------------------------
# Desactivación (toggle) — A no puede desactivar producto de B
# ---------------------------------------------------------------------------

async def test_toggle_producto_de_otro_negocio_devuelve_none():
    negocio_a, negocio_b, producto_a, producto_b = await _dos_negocios_con_producto()

    resultado = await mem.toggle_producto(
        producto_b["id"], version_esperada=producto_b["version"], autor="test", negocio_id=negocio_a["id"],
    )
    assert resultado is None

    intacto = await mem.obtener_producto(producto_b["id"], negocio_b["id"])
    assert intacto["activo"] is True  # nunca se tocó


# ---------------------------------------------------------------------------
# Lectura por PK — candado de ownership (404, no 403 — no confirma existencia)
# ---------------------------------------------------------------------------

async def test_obtener_producto_de_otro_negocio_es_none():
    negocio_a, negocio_b, producto_a, producto_b = await _dos_negocios_con_producto()
    assert await mem.obtener_producto(producto_b["id"], negocio_a["id"]) is None
    assert await mem.obtener_producto(producto_a["id"], negocio_a["id"]) is not None


# ---------------------------------------------------------------------------
# Importación CSV — solo toca el catálogo del negocio_id dado
# ---------------------------------------------------------------------------

async def test_importar_csv_no_toca_productos_de_otro_negocio(tmp_path):
    negocio_a, negocio_b, producto_a, producto_b = await _dos_negocios_con_producto()

    ruta_csv = tmp_path / "catalogo_a.csv"
    buffer = io.StringIO()
    escritor = csv.DictWriter(buffer, fieldnames=["CANAL", "MARCA", "TIPO", "SUB TIPO", "CODIGO HANA", "DESCRIPCIÓN", "PRECIO"])
    escritor.writeheader()
    # Trae de vuelta el producto A (sin cambios) + un producto NUEVO — el
    # CSV representa el catálogo COMPLETO vigente de Negocio A únicamente.
    escritor.writerow({"CANAL": "", "MARCA": "MarcaA", "TIPO": "terma", "SUB TIPO": "a gas",
                        "CODIGO HANA": "HANA-A-001", "DESCRIPCIÓN": "Terma A", "PRECIO": "500"})
    escritor.writerow({"CANAL": "", "MARCA": "MarcaA2", "TIPO": "cocina", "SUB TIPO": "",
                        "CODIGO HANA": "HANA-A-002", "DESCRIPCIÓN": "Cocina A nueva", "PRECIO": "700"})
    ruta_csv.write_text(buffer.getvalue(), encoding="utf-8-sig")

    resumen = await mem.importar_catalogo_desde_csv(str(ruta_csv), negocio_id=negocio_a["id"], autor="test")
    assert resumen["nuevos"] == 1
    assert resumen["sin_cambios"] == 1
    assert resumen["desactivados"] == 0  # el CSV de A no dice nada de B — B no se toca

    # Producto B sigue intacto y activo — la importación de A nunca lo vio.
    intacto = await mem.obtener_producto(producto_b["id"], negocio_b["id"])
    assert intacto["activo"] is True
    assert intacto["marca"] == "MarcaB"

    # El producto nuevo nació en A, no en B.
    productos_b, _ = await mem.listar_productos({}, pagina=1, por_pagina=20, negocio_id=negocio_b["id"])
    assert len(productos_b) == 1  # solo el original de B


# ---------------------------------------------------------------------------
# Validación de venta (servicio_comercial) — producto de B no valida para A
# ---------------------------------------------------------------------------

async def test_validar_productos_de_venta_rechaza_producto_de_otro_negocio():
    negocio_a, negocio_b, producto_a, producto_b = await _dos_negocios_con_producto()

    venta = {"lineas": [{"producto_id": producto_b["id"], "producto": "Terma B", "precio": "600", "marca": "MarcaB", "proveedor": ""}]}
    try:
        await servicio_comercial.validar_productos_de_venta(venta, negocio_a["id"])
        assert False, "debería haber lanzado ValueError"
    except ValueError as e:
        assert str(producto_b["id"]) in str(e)

    # El mismo producto SÍ valida para su propio negocio.
    venta_propia = {"lineas": [{"producto_id": producto_a["id"], "producto": "Terma A", "precio": "500", "marca": "MarcaA", "proveedor": ""}]}
    await servicio_comercial.validar_productos_de_venta(venta_propia, negocio_a["id"])  # no debe lanzar


# ---------------------------------------------------------------------------
# Gabi — el catálogo que arma _armar_bloques_contexto respeta el negocio
# ---------------------------------------------------------------------------

async def test_gabi_de_A_no_recibe_productos_de_B(tmp_path, monkeypatch):
    from agent import tools as herramientas
    monkeypatch.setattr(herramientas, "KNOWLEDGE_DIR", str(tmp_path))  # sin knowledge de por medio, foco en catálogo

    negocio_a, negocio_b, producto_a, producto_b = await _dos_negocios_con_producto()

    bloques_a = await brain._armar_bloques_contexto(
        "quiero una terma a gas", historial=[], lead=None, negocio_id=negocio_a["id"],
    )
    texto_a = "\n".join(bloques_a)
    assert "MarcaA" in texto_a
    assert "MarcaB" not in texto_a

    bloques_b = await brain._armar_bloques_contexto(
        "quiero una terma a gas", historial=[], lead=None, negocio_id=negocio_b["id"],
    )
    texto_b = "\n".join(bloques_b)
    assert "MarcaB" in texto_b
    assert "MarcaA" not in texto_b


async def test_gabi_sin_negocio_resuelto_no_recibe_ningun_producto(tmp_path, monkeypatch):
    """negocio_id=None (Canal aún no resuelto por el webhook) — Gabi no debe
    recibir contexto de catálogo de NINGÚN Negocio."""
    from agent import tools as herramientas
    monkeypatch.setattr(herramientas, "KNOWLEDGE_DIR", str(tmp_path))

    await _dos_negocios_con_producto()

    bloques = await brain._armar_bloques_contexto(
        "quiero una terma a gas", historial=[], lead=None, negocio_id=None,
    )
    texto = "\n".join(bloques)
    assert "MarcaA" not in texto
    assert "MarcaB" not in texto
