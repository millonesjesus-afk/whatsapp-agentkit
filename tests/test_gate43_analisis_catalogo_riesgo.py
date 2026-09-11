# tests/test_gate43_analisis_catalogo_riesgo.py — Gate 4.3, auditoría de
# determinación (NO corrección): ¿el problema de aislamiento de `Producto`
# puede provocar que Gabi, en producción, consulte productos de otro
# Negocio? ¿Ese riesgo bloquea la activación de Gabi/ensamblado para
# Cálidda?
#
# Este archivo documentó originalmente (Gate 4.3) que `Producto` NO tenía
# `negocio_id` — deuda real pero ORTOGONAL a la activación de Gabi, y por
# eso no bloqueante. Gate 4.4 cerró esa deuda (ver
# tests/test_gate44_catalogo_multitenant.py para la cobertura completa de
# aislamiento). Las secciones 1 y 2 de abajo se actualizaron para afirmar
# el estado POST-Gate 4.4 (la corrección se aplicó) en vez de dejar
# aserciones que ahora serían falsas — la sección 3 (determinación de que
# `usa_patron_estructural` es independiente del catálogo) sigue siendo
# válida tal cual y no se tocó.

from agent import brain, memory as mem


# ---------------------------------------------------------------------------
# 1. Confirmación estructural — Producto SÍ tiene negocio_id (Gate 4.4)
# ---------------------------------------------------------------------------

def test_producto_tiene_columna_negocio_id():
    """Invierte test_producto_no_tiene_columna_negocio_id de Gate 4.3 — la
    deuda que ese test documentaba ya se cerró."""
    columnas = {c.name for c in mem.Producto.__table__.columns}
    assert "negocio_id" in columnas


def test_crear_producto_no_acepta_negocio_id_en_campos_de_negocio():
    """`CAMPOS_NEGOCIO_PRODUCTO` sigue siendo el nombre histórico de los
    campos COMERCIALES del producto (canal, proveedor, marca, precio...) —
    NO tiene relación con la entidad `Negocio` (tenant); `negocio_id` se
    pasa a crear_producto()/editar_producto() como parámetro aparte, nunca
    mezclado en este set. Confirmado leyendo su contenido real, para no
    asumir por el nombre."""
    assert "negocio_id" not in mem.CAMPOS_NEGOCIO_PRODUCTO
    assert set(mem.CAMPOS_NEGOCIO_PRODUCTO) == {
        "canal", "proveedor", "marca", "tipo", "sub_tipo", "codigo_hana",
        "descripcion", "combo", "comentarios", "fee_prv", "fee_clda", "precio",
    }


# ---------------------------------------------------------------------------
# 2. El riesgo documentado en Gate 4.3 ya NO es reproducible (Gate 4.4) —
# buscar_productos ahora exige negocio_id y filtra en el WHERE.
# ---------------------------------------------------------------------------

async def test_buscar_productos_ya_filtra_por_negocio():
    """Invierte test_buscar_productos_no_filtra_por_ningun_concepto_de_negocio
    de Gate 4.3 — antes demostraba que dos "orígenes" de producto se
    mezclaban; ahora demuestra que, dados dos Negocios reales, cada
    búsqueda solo ve el suyo."""
    negocio_a = await mem.crear_negocio("Negocio Origen A", "g44origena")
    negocio_b = await mem.crear_negocio("Negocio Origen B", "g44origenb")
    await mem.crear_producto(
        {"tipo": "terma", "sub_tipo": "a gas", "marca": "MarcaOrigenA", "descripcion": "Terma Origen A",
         "codigo_hana": "TEST-A-001", "precio": "500"},
        autor="test", negocio_id=negocio_a["id"],
    )
    await mem.crear_producto(
        {"tipo": "terma", "sub_tipo": "a gas", "marca": "MarcaOrigenB", "descripcion": "Terma Origen B",
         "codigo_hana": "TEST-B-001", "precio": "600"},
        autor="test", negocio_id=negocio_b["id"],
    )

    from agent.tools import buscar_productos
    resultados_a = await buscar_productos("terma a gas", negocio_a["id"])
    marcas_a = {p.get("MARCA") for p in resultados_a}

    assert "MarcaOrigenA" in marcas_a
    assert "MarcaOrigenB" not in marcas_a


def test_existe_negocio_id_en_toda_la_cadena():
    """Invierte test_no_existe_ningun_parametro_de_negocio_en_toda_la_cadena
    de Gate 4.3 — confirma que TODA la cadena
    obtener_contexto_relevante -> buscar_productos -> listar_productos_activos
    -> obtener_producto_por_codigo_hana ahora exige negocio_id."""
    import inspect
    from agent import tools as herramientas

    for funcion in (herramientas.buscar_productos, mem.listar_productos_activos, mem.obtener_producto_por_codigo_hana):
        parametros = inspect.signature(funcion).parameters
        assert "negocio_id" in parametros, f"{funcion.__name__} debería exigir negocio_id tras Gate 4.4"


# ---------------------------------------------------------------------------
# 3. Determinación — el flag de Gabi (usa_patron_estructural) sigue siendo
# ORTOGONAL al catálogo, ahora con negocio_id real de por medio.
# ---------------------------------------------------------------------------

async def test_activar_o_revertir_gabi_no_cambia_en_nada_el_resultado_del_catalogo(tmp_path, monkeypatch):
    """La pregunta específica del usuario en Gate 4.3: ¿la activación de
    Gabi (usa_patron_estructural) puede hacer que Gabi consulte/reciba
    productos de otro Negocio? Respuesta demostrada: NO — el flag de Gabi
    solo cambia qué devuelve `obtener_system_prompt()` (identidad/reglas
    de texto). La búsqueda de productos (`buscar_productos`, llamada
    dentro de `obtener_contexto_relevante`, en el MENSAJE del turno, no en
    el system prompt) es exactamente la MISMA función, con el MISMO
    resultado, actives o no el ensamblador — porque son dos piezas de
    código completamente distintas que ni se tocan ni se conocen entre
    sí. Sigue siendo cierto tras Gate 4.4 (negocio_id real de por medio)."""
    from agent import tools as herramientas
    monkeypatch.setattr(herramientas, "KNOWLEDGE_DIR", str(tmp_path))  # sin conocimiento de por medio, foco en catálogo

    negocio = await mem.crear_negocio("Negocio Determinación", "g43det")
    await mem.crear_producto(
        {"tipo": "cocina", "sub_tipo": "empotrable", "marca": "MarcaDeterminacion",
         "descripcion": "Cocina Determinación", "codigo_hana": "TEST-DET-001", "precio": "800"},
        autor="test", negocio_id=negocio["id"],
    )
    await mem.crear_o_actualizar_identidad_agente(
        negocio["id"], nombre="Gabi", tono="Cercano",
        configuracion_negocio="Eres Gabi.\n\n## Tu identidad\n- Te llamas Gabi.\n",
    )

    # Rama 1: Gabi SIN activar (usa_patron_estructural=False, default)
    bloques_sin_activar = await brain._armar_bloques_contexto(
        "cocina empotrable", historial=[], lead=None, negocio_id=negocio["id"],
    )

    # Rama 2: Gabi ACTIVADA (usa_patron_estructural=True)
    await mem.activar_patron_estructural(negocio["id"], True)
    bloques_activado = await brain._armar_bloques_contexto(
        "cocina empotrable", historial=[], lead=None, negocio_id=negocio["id"],
    )

    # El bloque de contexto (que incluye el catálogo) es IDÉNTICO en ambas
    # ramas -- la activación de Gabi no tocó, ni pudo tocar, el resultado
    # del catálogo. `_armar_bloques_contexto` ni siquiera consulta
    # `usa_patron_estructural` -- ese campo solo lo lee `obtener_system_prompt`,
    # una función completamente distinta, llamada en otro punto de
    # `generar_respuesta`.
    assert bloques_sin_activar == bloques_activado
    assert any("MarcaDeterminacion" in b for b in bloques_sin_activar)
    assert any("MarcaDeterminacion" in b for b in bloques_activado)


async def test_armar_bloques_contexto_nunca_lee_usa_patron_estructural():
    """Confirmación directa a nivel de código (no solo de comportamiento
    observado): `_armar_bloques_contexto` no importa ni referencia
    `usa_patron_estructural` en absoluto -- son dos funciones sin ninguna
    dependencia entre sí."""
    import inspect
    codigo_fuente = inspect.getsource(brain._armar_bloques_contexto)
    assert "usa_patron_estructural" not in codigo_fuente
