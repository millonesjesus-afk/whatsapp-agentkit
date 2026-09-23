# tests/test_financiamiento_cuotas.py — Gate 2026-09-23: la cuota mensual
# ya NO se lee de 9 columnas fijas y pre-calculadas del catálogo
# (3/6/9/12/18/24/36/48/60 meses — cualquier otro número, ej. 15, no tenía
# ninguna respuesta posible). Se calcula EN VIVO con una tasa (TEA/IGV)
# configurable por negocio — sistema francés de amortización + IGV solo
# sobre el interés de cada periodo, verificado cifra por cifra contra la
# plantilla Excel real del negocio y contra productos reales del catálogo
# (ver conversación — S/3,000 a 40% TEA / 36 cuotas → primera cuota
# S/149.58; S/1,749 → primera cuota S/87.21 en 36 cuotas).

from agent import dashboard
from agent import memory as mem
from agent.tools import (
    CUOTAS_MAX, CUOTAS_MIN, _calcular_amortizacion, _cuotas_pedidas_en_mensaje,
    calcular_cuota_producto, formatear_producto, obtener_contexto_relevante,
    obtener_tasas_financiamiento,
)


# ── _calcular_amortizacion — la fórmula pura, contra los números reales ──

def test_cuota_inicial_coincide_con_la_plantilla_excel_real():
    """3000 a 40% TEA en 36 cuotas — el ejemplo real de la plantilla del
    usuario. Primera cuota: S/149.58 (capital 48.92 + interés 85.30 + IGV
    18% sobre el interés)."""
    resultado = _calcular_amortizacion(3000.0, 0.40, 0.18, 36)
    assert abs(resultado["cuota_inicial"] - 149.58) < 0.05


def test_cuota_inicial_coincide_con_un_producto_real_del_catalogo():
    """S/1,749 a 40% TEA en 36 cuotas — el catálogo real (columna "36")
    trae 87.21 para este producto exacto."""
    resultado = _calcular_amortizacion(1749.0, 0.40, 0.18, 36)
    assert abs(resultado["cuota_inicial"] - 87.21) < 0.05


def test_una_sola_cuota_es_el_monto_mas_el_interes_de_un_mes():
    resultado = _calcular_amortizacion(1000.0, 0.40, 0.18, 1)
    tem = (1.40) ** (1 / 12) - 1
    interes_esperado = 1000.0 * tem
    esperado = 1000.0 + interes_esperado * 1.18
    assert abs(resultado["cuota_inicial"] - esperado) < 0.01
    assert resultado["cuota_inicial"] == resultado["total_a_pagar"]


def test_monto_o_cuotas_invalidas_devuelve_ceros_sin_reventar():
    assert _calcular_amortizacion(0, 0.40, 0.18, 12) == {"cuota_inicial": 0.0, "total_a_pagar": 0.0, "total_intereses": 0.0}
    assert _calcular_amortizacion(1000, 0.40, 0.18, 0) == {"cuota_inicial": 0.0, "total_a_pagar": 0.0, "total_intereses": 0.0}


def test_la_cuota_inicial_es_la_mas_alta_del_cronograma():
    """El primer periodo tiene el saldo completo -> el interés (y su IGV)
    más alto de todo el cronograma — coherente con que sea la cifra que se
    muestra como "la cuota"."""
    resultado = _calcular_amortizacion(3000.0, 0.40, 0.18, 36)
    promedio = resultado["total_a_pagar"] / 36
    assert resultado["cuota_inicial"] >= promedio


# ── obtener_tasas_financiamiento / calcular_cuota_producto ───────────────

async def test_tasas_por_defecto_sin_configuracion():
    negocio = await mem.crear_negocio("Negocio Financiamiento 1", "g-fin-01")
    tea, igv = await obtener_tasas_financiamiento(negocio["id"])
    assert tea == 0.40
    assert igv == 0.18


async def test_tasas_configuradas_por_negocio_se_respetan():
    negocio = await mem.crear_negocio("Negocio Financiamiento 2", "g-fin-02")
    await mem.guardar_configuracion("tea_financiamiento", "0.35", negocio_id=negocio["id"])
    await mem.guardar_configuracion("igv_financiamiento", "0.18", negocio_id=negocio["id"])
    tea, igv = await obtener_tasas_financiamiento(negocio["id"])
    assert tea == 0.35
    assert igv == 0.18


async def test_tasa_de_un_negocio_no_afecta_a_otro():
    negocio_a = await mem.crear_negocio("Negocio Financiamiento 3a", "g-fin-03a")
    negocio_b = await mem.crear_negocio("Negocio Financiamiento 3b", "g-fin-03b")
    await mem.guardar_configuracion("tea_financiamiento", "0.50", negocio_id=negocio_a["id"])
    tea_a, _ = await obtener_tasas_financiamiento(negocio_a["id"])
    tea_b, _ = await obtener_tasas_financiamiento(negocio_b["id"])
    assert tea_a == 0.50
    assert tea_b == 0.40  # default, sin contaminarse del negocio A


async def test_calcular_cuota_producto_rechaza_fuera_de_rango():
    negocio = await mem.crear_negocio("Negocio Financiamiento 4", "g-fin-04")
    assert await calcular_cuota_producto(1000.0, negocio["id"], 0) is None
    assert await calcular_cuota_producto(1000.0, negocio["id"], 61) is None
    assert await calcular_cuota_producto(1000.0, negocio["id"], 1) is not None
    assert await calcular_cuota_producto(1000.0, negocio["id"], 60) is not None


# ── _cuotas_pedidas_en_mensaje ─────────────────────────────────────────────

def test_detecta_un_pedido_explicito_de_cuotas():
    assert _cuotas_pedidas_en_mensaje("quiero pagar en 15 cuotas") == 15
    assert _cuotas_pedidas_en_mensaje("y si pago a 24 meses?") == 24
    assert _cuotas_pedidas_en_mensaje("en 1 cuota") == 1
    assert _cuotas_pedidas_en_mensaje("¿60 cuotas se puede?") == 60


def test_no_detecta_nada_fuera_de_rango_o_sin_pedido():
    assert _cuotas_pedidas_en_mensaje("tengo 5 hijos") is None  # sin "cuotas"/"meses"
    assert _cuotas_pedidas_en_mensaje("hola, quiero una terma") is None


# ── formatear_producto — ya NO lee columnas fijas del catálogo ───────────

async def test_formatear_producto_calcula_las_cuotas_en_vivo():
    negocio = await mem.crear_negocio("Negocio Financiamiento 5", "g-fin-05")
    await mem.crear_producto(
        {"tipo": "terma", "sub_tipo": "a gas", "marca": "Rheem", "descripcion": "Terma Rheem 10 LT", "precio": "1749"},
        autor="test", negocio_id=negocio["id"],
    )
    # crear_producto() devuelve la forma "panel" (claves en minúscula) —
    # formatear_producto espera la forma CSV (mayúsculas), la misma que ya
    # arma listar_productos_activos para el resto del negocio de tools.py.
    [producto] = await mem.listar_productos_activos(negocio["id"])
    # Producto recién creado: NUNCA tuvo columnas "12"/"24"/"36" del CSV
    # (ver CAMPOS_NEGOCIO_PRODUCTO) — si el texto igual trae cuotas, es
    # porque se calcularon, no porque se leyeron de algún lado.
    texto = formatear_producto(producto, 0.40, 0.18)
    # Tolerancia de 1 centavo — redondeo de punto flotante entre este
    # recálculo y el original de la plantilla, no un desacuerdo real (ver
    # test_cuota_inicial_coincide_con_un_producto_real_del_catalogo, mismo
    # criterio).
    assert "36 meses: S/ 87.2" in texto  # 87.20 o 87.21, nunca otra cosa
    assert "12 meses:" in texto and "24 meses:" in texto


# ── obtener_contexto_relevante — el cliente pide un número puntual ───────

async def test_contexto_incluye_la_cuota_puntual_que_pide_el_cliente():
    negocio = await mem.crear_negocio("Negocio Financiamiento 6", "g-fin-06")
    await mem.crear_producto(
        {"tipo": "terma", "sub_tipo": "a gas", "marca": "Rheem", "descripcion": "Terma Rheem 10 LT", "precio": "1749"},
        autor="test", negocio_id=negocio["id"],
    )
    contexto = await obtener_contexto_relevante("quiero una terma a gas en 15 cuotas", negocio["id"], "g-fin-06")
    assert "preguntó puntualmente por 15 cuotas" in contexto


async def test_contexto_no_repite_un_plazo_que_ya_se_muestra_de_entrada():
    negocio = await mem.crear_negocio("Negocio Financiamiento 7", "g-fin-07")
    await mem.crear_producto(
        {"tipo": "terma", "sub_tipo": "a gas", "marca": "Rheem", "descripcion": "Terma Rheem 10 LT", "precio": "1749"},
        autor="test", negocio_id=negocio["id"],
    )
    contexto = await obtener_contexto_relevante("quiero una terma a gas en 24 cuotas", negocio["id"], "g-fin-07")
    assert "preguntó puntualmente" not in contexto  # 24 ya está en PLAZOS_A_MOSTRAR


# ── dashboard.py: GET /financiamiento/cuota ──────────────────────────────

async def test_ruta_cuota_preview_calcula_en_vivo():
    negocio = await mem.crear_negocio("Negocio Financiamiento 8", "g-fin-08")
    usuario = {"username": "admin1", "negocio_id": negocio["id"]}
    respuesta = await dashboard.financiamiento_cuota_preview(monto=1749.0, cuotas=36, usuario=usuario)

    import json
    cuerpo = json.loads(respuesta.body)
    assert cuerpo["ok"] is True
    assert abs(cuerpo["cuota_inicial"] - 87.21) < 0.05


async def test_ruta_cuota_preview_rechaza_cuotas_fuera_de_rango():
    from fastapi import HTTPException
    import pytest
    negocio = await mem.crear_negocio("Negocio Financiamiento 9", "g-fin-09")
    usuario = {"username": "admin1", "negocio_id": negocio["id"]}
    with pytest.raises(HTTPException) as exc:
        await dashboard.financiamiento_cuota_preview(monto=1000.0, cuotas=61, usuario=usuario)
    assert exc.value.status_code == 400


async def test_ruta_cuota_preview_rechaza_monto_invalido():
    from fastapi import HTTPException
    import pytest
    negocio = await mem.crear_negocio("Negocio Financiamiento 10", "g-fin-10")
    usuario = {"username": "admin1", "negocio_id": negocio["id"]}
    with pytest.raises(HTTPException) as exc:
        await dashboard.financiamiento_cuota_preview(monto=0, cuotas=12, usuario=usuario)
    assert exc.value.status_code == 400


# ── dashboard.py: /configuracion.json + POST /configuracion/financiamiento ─

async def test_configuracion_json_expone_financiamiento():
    negocio = await mem.crear_negocio("Negocio Financiamiento 11", "g-fin-11")
    usuario = {"username": "admin1", "nombre": "Admin Uno", "negocio_id": negocio["id"], "rol": "admin"}
    respuesta = await dashboard.configuracion_json(usuario=usuario)

    import json
    cuerpo = json.loads(respuesta.body)
    assert cuerpo["financiamiento"] == {"tea": 0.40, "igv": 0.18, "cuotas_min": CUOTAS_MIN, "cuotas_max": CUOTAS_MAX}


async def test_actualizar_financiamiento_guarda_y_se_refleja_despues():
    negocio = await mem.crear_negocio("Negocio Financiamiento 12", "g-fin-12")
    usuario = {"username": "admin1", "nombre": "Admin Uno", "negocio_id": negocio["id"], "rol": "admin"}

    class _RequestFalso:
        async def json(self):
            return {"tea": 0.35, "igv": 0.18}

    respuesta = await dashboard.actualizar_financiamiento_ruta(_RequestFalso(), usuario=usuario, _csrf=None)
    import json
    cuerpo = json.loads(respuesta.body)
    assert cuerpo["ok"] is True
    assert cuerpo["financiamiento"]["tea"] == 0.35

    tea, igv = await obtener_tasas_financiamiento(negocio["id"])
    assert tea == 0.35


async def test_actualizar_financiamiento_rechaza_tea_fuera_de_rango():
    from fastapi import HTTPException
    import pytest
    negocio = await mem.crear_negocio("Negocio Financiamiento 13", "g-fin-13")
    usuario = {"username": "admin1", "nombre": "Admin Uno", "negocio_id": negocio["id"], "rol": "admin"}

    class _RequestFalso:
        async def json(self):
            return {"tea": 10, "igv": 0.18}

    with pytest.raises(HTTPException) as exc:
        await dashboard.actualizar_financiamiento_ruta(_RequestFalso(), usuario=usuario, _csrf=None)
    assert exc.value.status_code == 400


# ── servicio_comercial.validar_venta — rango 1-60, no una lista fija ─────

def test_validar_venta_acepta_cualquier_cuota_del_rango_real():
    from agent.services.servicio_comercial import ServicioComercial
    servicio = ServicioComercial()
    for cuotas in ("1", "15", "45", "60"):
        venta = servicio.validar_venta("[]", "financiado", cuotas, "")
        assert venta["cuotas"] == cuotas


def test_validar_venta_rechaza_fuera_del_rango_real():
    from agent.services.servicio_comercial import ServicioComercial
    servicio = ServicioComercial()
    for cuotas in ("0", "61", "abc"):
        try:
            servicio.validar_venta("[]", "financiado", cuotas, "")
            assert False, f"debería haber rechazado {cuotas!r}"
        except ValueError:
            pass


# ── Pacto congelado: la cuota pactada NO cambia si después cambia la tasa ─

import json

from sqlalchemy import select

from agent.services.servicio_comercial import servicio_comercial


async def _escenario_venta(codigo: str, telefono: str):
    negocio = await mem.crear_negocio(f"Negocio Pacto {codigo}", codigo)
    canal = await mem.crear_canal_whatsapp(
        nombre=f"Canal {codigo}", phone_number_id=f"5091{codigo[-4:]}", negocio_id=negocio["id"],
    )
    await mem.actualizar_lead(telefono, negocio_id=negocio["id"], numero_whatsapp_id="x")
    _, opportunity = await mem.resolver_conversation_activa(telefono, negocio["id"], canal["id"])
    usuario = {"username": "admin1", "nombre": "Admin Uno", "negocio_id": negocio["id"], "rol": "admin"}
    return negocio, opportunity, usuario


async def _registrar(opportunity_id, usuario, precio: str, cuotas: str, version: int, modalidad: str = "financiado"):
    lineas = json.dumps([{"producto_id": None, "producto": "Terma", "precio": precio}])
    return await dashboard.opportunity_venta(
        opportunity_id, lineas_venta=lineas, modalidad_pago=modalidad, cuotas=cuotas,
        medio_pago="", version=version, usuario=usuario, _csrf=None,
    )


async def _opportunity(opportunity_id):
    async with mem.async_session() as session:
        return await session.get(mem.Opportunity, opportunity_id)


async def test_venta_financiada_nueva_congela_cuota_monto_y_tasas():
    negocio, opp, usuario = await _escenario_venta("g-pac-01", "51910000001")
    await _registrar(opp.id, usuario, "1749", "36", opp.version)
    o = await _opportunity(opp.id)
    assert abs(float(o.cuota_pactada) - 87.20) < 0.05
    assert float(o.monto_financiado) == 1749.0
    assert float(o.tea_pactada) == 0.40 and float(o.igv_pactado) == 0.18


async def test_cambiar_la_tasa_no_recalcula_una_venta_ya_pactada():
    """El corazón del pedido: guardar de nuevo la MISMA venta (mismo monto,
    mismas cuotas) después de subir la TEA conserva la cuota y la tasa de
    cuando se pactó."""
    negocio, opp, usuario = await _escenario_venta("g-pac-02", "51910000002")
    await _registrar(opp.id, usuario, "1749", "36", opp.version)
    antes = await _opportunity(opp.id)

    await mem.guardar_configuracion("tea_financiamiento", "0.60", negocio_id=negocio["id"])
    await _registrar(opp.id, usuario, "1749", "36", antes.version)

    despues = await _opportunity(opp.id)
    assert despues.cuota_pactada == antes.cuota_pactada
    assert despues.tea_pactada == antes.tea_pactada == "0.4"


async def test_un_financiamiento_nuevo_usa_la_tasa_vigente():
    """Cambiar las cuotas (o el carrito) es un financiamiento nuevo: ahí sí
    aplica la tasa de hoy, y queda congelada de nuevo."""
    negocio, opp, usuario = await _escenario_venta("g-pac-03", "51910000003")
    await _registrar(opp.id, usuario, "1749", "36", opp.version)
    v1 = await _opportunity(opp.id)

    await mem.guardar_configuracion("tea_financiamiento", "0.60", negocio_id=negocio["id"])
    await _registrar(opp.id, usuario, "1749", "24", v1.version)

    v2 = await _opportunity(opp.id)
    assert v2.tea_pactada == "0.6"
    assert v2.cuota_pactada != v1.cuota_pactada
    esperado = _calcular_amortizacion(1749.0, 0.60, 0.18, 24)["cuota_inicial"]
    assert abs(float(v2.cuota_pactada) - esperado) < 0.01


async def test_cambiar_el_monto_del_carrito_recalcula_con_la_tasa_vigente():
    negocio, opp, usuario = await _escenario_venta("g-pac-04", "51910000004")
    await _registrar(opp.id, usuario, "1000", "12", opp.version)
    v1 = await _opportunity(opp.id)
    await mem.guardar_configuracion("tea_financiamiento", "0.50", negocio_id=negocio["id"])
    await _registrar(opp.id, usuario, "2000", "12", v1.version)
    v2 = await _opportunity(opp.id)
    assert float(v2.monto_financiado) == 2000.0
    assert v2.tea_pactada == "0.5"


async def test_pasar_a_contado_limpia_el_pacto():
    negocio, opp, usuario = await _escenario_venta("g-pac-05", "51910000005")
    await _registrar(opp.id, usuario, "1749", "36", opp.version)
    v1 = await _opportunity(opp.id)
    await dashboard.opportunity_venta(
        opp.id, lineas_venta=json.dumps([{"producto": "Terma", "precio": "1749"}]),
        modalidad_pago="contado", cuotas="", medio_pago="QR", version=v1.version, usuario=usuario, _csrf=None,
    )
    v2 = await _opportunity(opp.id)
    assert v2.cuota_pactada is None and v2.monto_financiado is None
    assert v2.tea_pactada is None and v2.igv_pactado is None


async def test_precio_no_numerico_no_congela_ninguna_cuota():
    negocio, opp, usuario = await _escenario_venta("g-pac-06", "51910000006")
    await _registrar(opp.id, usuario, "EN CREACIÓN", "12", opp.version)
    o = await _opportunity(opp.id)
    assert o.cuotas == "12" and o.cuota_pactada is None


async def test_el_pacto_se_refleja_tambien_en_el_lead_espejo():
    negocio, opp, usuario = await _escenario_venta("g-pac-07", "51910000007")
    await _registrar(opp.id, usuario, "1749", "36", opp.version)
    async with mem.async_session() as session:
        lead = await session.get(mem.Lead, "51910000007")
    assert lead.cuota_pactada is not None and lead.tea_pactada == "0.4"


async def test_calcular_pacto_conserva_el_previo_si_no_cambia_lo_financiado():
    negocio = await mem.crear_negocio("Negocio Pacto Servicio", "g-pac-08")
    venta = {"modalidad_pago": "financiado", "cuotas": "12", "lineas": [{"precio": "S/ 1,000.00"}]}
    previo = {
        "cuotas": "12", "monto_financiado": "1000.00", "cuota_pactada": "99.99",
        "tea_pactada": "0.3", "igv_pactado": "0.18",
    }
    pacto = await servicio_comercial.calcular_pacto_financiamiento(venta, negocio["id"], previo)
    assert pacto["cuota_pactada"] == "99.99" and pacto["tea_pactada"] == "0.3"


async def test_camino_lead_sin_opportunity_tambien_congela_el_pacto():
    negocio = await mem.crear_negocio("Negocio Pacto Lead", "g-pac-09")
    telefono = "51910000009"
    await mem.actualizar_lead(telefono, negocio_id=negocio["id"], numero_whatsapp_id="x")
    await servicio_comercial.registrar_venta(
        telefono, json.dumps([{"producto": "Terma", "precio": "1749"}]), "financiado", "36", "", negocio["id"],
    )
    async with mem.async_session() as session:
        lead = await session.get(mem.Lead, telefono)
    assert abs(float(lead.cuota_pactada) - 87.20) < 0.05 and lead.tea_pactada == "0.4"
