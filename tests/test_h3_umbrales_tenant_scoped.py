# tests/test_h3_umbrales_tenant_scoped.py — H3, corrección de aislamiento
# multi-tenant de `umbral_intermedio`/`umbral_senior` (asignación automática
# de leads por nivel de asesor). Antes de este Gate, `_umbrales()` y
# `POST /asesores/umbrales` leían/escribían siempre la fila GLOBAL de
# `Configuracion`, sin negocio_id — cualquier negocio podía pisar el
# comportamiento de asignación de cualquier otro. Datos sintéticos
# únicamente.

from agent import asignacion, memory as mem
from agent.dashboard import actualizar_umbrales_asignacion


async def _negocio(codigo: str):
    return await mem.crear_negocio(f"Negocio {codigo}", codigo)


# ── Test A — lectura aislada ─────────────────────────────────────────────

async def test_umbrales_lectura_aislada_por_negocio():
    negocio_a = await _negocio("h3-umb-a1")
    negocio_b = await _negocio("h3-umb-a2")
    await mem.guardar_configuracion("umbral_intermedio", "700", negocio_id=negocio_a["id"])
    await mem.guardar_configuracion("umbral_senior", "2000", negocio_id=negocio_a["id"])
    await mem.guardar_configuracion("umbral_intermedio", "300", negocio_id=negocio_b["id"])
    await mem.guardar_configuracion("umbral_senior", "900", negocio_id=negocio_b["id"])

    senior_a, intermedio_a = await asignacion._umbrales(negocio_a["id"])
    senior_b, intermedio_b = await asignacion._umbrales(negocio_b["id"])

    assert (senior_a, intermedio_a) == (2000.0, 700.0)
    assert (senior_b, intermedio_b) == (900.0, 300.0)


# ── Test B — escritura aislada ───────────────────────────────────────────

async def test_umbrales_escritura_aislada_no_afecta_otro_negocio():
    negocio_a = await _negocio("h3-umb-b1")
    negocio_b = await _negocio("h3-umb-b2")
    await mem.guardar_configuracion("umbral_intermedio", "500", negocio_id=negocio_a["id"])
    await mem.guardar_configuracion("umbral_intermedio", "500", negocio_id=negocio_b["id"])

    await mem.guardar_configuracion("umbral_intermedio", "888", negocio_id=negocio_a["id"])

    valor_a = await mem.obtener_configuracion("umbral_intermedio", "default", negocio_id=negocio_a["id"])
    valor_b = await mem.obtener_configuracion("umbral_intermedio", "default", negocio_id=negocio_b["id"])
    assert valor_a == "888"
    assert valor_b == "500"


# ── Test C — asignación automática usa el umbral del negocio correcto ───

async def test_nivel_requerido_usa_umbral_del_negocio_correspondiente():
    negocio_a = await _negocio("h3-umb-c1")
    negocio_b = await _negocio("h3-umb-c2")
    await mem.crear_producto(
        {"tipo": "terma", "sub_tipo": "a gas", "marca": "MarcaA", "descripcion": "Terma A", "precio": "2000"},
        autor="test", negocio_id=negocio_a["id"],
    )
    await mem.crear_producto(
        {"tipo": "terma", "sub_tipo": "a gas", "marca": "MarcaB", "descripcion": "Terma B", "precio": "2000"},
        autor="test", negocio_id=negocio_b["id"],
    )
    # Mismo precio (2000) en ambos negocios, pero umbral_senior muy distinto:
    # para A, 2000 alcanza "senior"; para B, ni siquiera alcanza "intermedio".
    await mem.guardar_configuracion("umbral_senior", "1000", negocio_id=negocio_a["id"])
    await mem.guardar_configuracion("umbral_intermedio", "500", negocio_id=negocio_a["id"])
    await mem.guardar_configuracion("umbral_senior", "5000", negocio_id=negocio_b["id"])
    await mem.guardar_configuracion("umbral_intermedio", "3000", negocio_id=negocio_b["id"])

    nivel_a = await asignacion._nivel_requerido("terma", negocio_a["id"])
    nivel_b = await asignacion._nivel_requerido("terma", negocio_b["id"])

    assert nivel_a == "senior"
    assert nivel_b == "junior"


async def test_elegir_asesor_automatico_respeta_umbral_por_negocio():
    """Mismo escenario que arriba, pero de punta a punta: dos asesores de
    nivel distinto por negocio, y el elegido debe ser el que corresponde al
    nivel que el umbral DE ESE NEGOCIO exige — no el de otro."""
    negocio_a = await _negocio("h3-umb-c3")
    negocio_b = await _negocio("h3-umb-c4")
    await mem.crear_producto(
        {"tipo": "terma", "sub_tipo": "a gas", "marca": "MarcaA", "descripcion": "Terma A", "precio": "2000"},
        autor="test", negocio_id=negocio_a["id"],
    )
    await mem.crear_producto(
        {"tipo": "terma", "sub_tipo": "a gas", "marca": "MarcaB", "descripcion": "Terma B", "precio": "2000"},
        autor="test", negocio_id=negocio_b["id"],
    )
    await mem.guardar_configuracion("umbral_senior", "1000", negocio_id=negocio_a["id"])
    await mem.guardar_configuracion("umbral_intermedio", "500", negocio_id=negocio_a["id"])
    # B: mismo precio (2000) exige "intermedio" acá (>= 1000, < 5000) —
    # deliberadamente distinto del umbral de A, para que el asesor elegido
    # solo pueda explicarse por el umbral DE ESTE negocio.
    await mem.guardar_configuracion("umbral_senior", "5000", negocio_id=negocio_b["id"])
    await mem.guardar_configuracion("umbral_intermedio", "1000", negocio_id=negocio_b["id"])

    await mem.crear_usuario("junior_a", "x", "Junior A", "asesor", negocio_a["id"], nivel="junior")
    await mem.crear_usuario("senior_a", "x", "Senior A", "asesor", negocio_a["id"], nivel="senior")
    await mem.crear_usuario("junior_b", "x", "Junior B", "asesor", negocio_b["id"], nivel="junior")
    await mem.crear_usuario("intermedio_b", "x", "Intermedio B", "asesor", negocio_b["id"], nivel="intermedio")

    elegido_a = await asignacion.elegir_asesor_automatico("terma", negocio_a["id"])
    elegido_b = await asignacion.elegir_asesor_automatico("terma", negocio_b["id"])

    assert elegido_a == "senior_a"  # A exige "senior" (2000 >= umbral_senior=1000)
    assert elegido_b == "intermedio_b"  # B exige "intermedio" (2000 >= umbral_intermedio=1000, < umbral_senior=5000)


# ── Test D — Cálidda conserva 500/1500 ───────────────────────────────────

async def test_calidda_sin_override_conserva_500_1500():
    """Cálidda nunca tuvo un override propio (solo la fila global histórica,
    con valores 500/1500 — idénticos a los defaults de código, confirmado
    en producción). Tras el fix, sin override, _umbrales(negocio_id) cae al
    default de asignacion.py — que produce exactamente el mismo resultado
    observable que antes del fix."""
    calidda = await _negocio("h3-umb-calidda")
    senior, intermedio = await asignacion._umbrales(calidda["id"])
    assert (senior, intermedio) == (
        asignacion.UMBRAL_SENIOR_DEFAULT, asignacion.UMBRAL_INTERMEDIO_DEFAULT,
    )
    assert (senior, intermedio) == (1500.0, 500.0)

    # Mismo resultado de nivel para un precio representativo, antes y después.
    await mem.crear_producto(
        {"tipo": "terma", "sub_tipo": "a gas", "marca": "Calidda", "descripcion": "Terma Calidda", "precio": "1600"},
        autor="test", negocio_id=calidda["id"],
    )
    nivel = await asignacion._nivel_requerido("terma", calidda["id"])
    assert nivel == "senior"  # 1600 >= 1500, igual que siempre


# ── Test E — ausencia de override nunca hereda de OTRO negocio ─────────

async def test_negocio_sin_override_no_hereda_de_otro_negocio():
    negocio_con_override = await _negocio("h3-umb-e1")
    negocio_sin_override = await _negocio("h3-umb-e2")
    await mem.guardar_configuracion("umbral_senior", "9999", negocio_id=negocio_con_override["id"])
    await mem.guardar_configuracion("umbral_intermedio", "8888", negocio_id=negocio_con_override["id"])

    senior, intermedio = await asignacion._umbrales(negocio_sin_override["id"])

    # Debe caer al default del módulo — nunca a los valores del otro negocio.
    assert (senior, intermedio) == (
        asignacion.UMBRAL_SENIOR_DEFAULT, asignacion.UMBRAL_INTERMEDIO_DEFAULT,
    )
    assert senior != 9999.0
    assert intermedio != 8888.0


# ── Test F — la ruta guarda con el negocio_id de la sesión ──────────────

async def test_actualizar_umbrales_asignacion_guarda_con_negocio_id_de_sesion():
    negocio_a = await _negocio("h3-umb-f1")
    negocio_b = await _negocio("h3-umb-f2")
    admin_a = {"username": "admin_a", "rol": "admin", "negocio_id": negocio_a["id"]}

    await actualizar_umbrales_asignacion(
        umbral_intermedio="321", umbral_senior="654", usuario=admin_a, _csrf=None,
    )

    valor_a = await mem.obtener_configuracion("umbral_intermedio", "default", negocio_id=negocio_a["id"])
    valor_b = await mem.obtener_configuracion("umbral_intermedio", "default", negocio_id=negocio_b["id"])
    assert valor_a == "321.0"
    assert valor_b == "default"  # negocio B nunca fue tocado por la escritura de A
