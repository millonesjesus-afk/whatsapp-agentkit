# tests/test_politica_envios.py — 2026-10-04, Fase B de la capa central de envíos:
# interruptor por origen (siempre | solo_gratis | nunca) y tope mensual en USD,
# apoyados en lo que Meta ya informó (uso_mensajes_meta), no en reglas fijas.
#
# Regla que manda (Opción A): lo ESENCIAL —respuesta de Gabi, aviso de
# derivación, lo que escribe el asesor— no se frena nunca por costo.

import asyncio
import os
from datetime import datetime, timedelta

os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")
os.environ.setdefault("WHATSAPP_PROVIDER", "meta")

import pytest
from sqlalchemy import select

from agent import envios, politica_envios
from agent import memory as mem

NUMERO = "555000111"
GRATIS_SERVICIO = {"billable": False, "pricing_model": "PMP", "type": "free_customer_service", "category": "service"}
VENTANA = {"billable": False, "pricing_model": "PMP", "type": "free_entry_point", "category": "service"}
COBRABLE = {"billable": True, "pricing_model": "PMP", "type": "regular", "category": "service"}


@pytest.fixture(autouse=True)
def _cache_limpia():
    politica_envios.limpiar_cache()
    yield
    politica_envios.limpiar_cache()


class _Proveedor:
    def __init__(self):
        self.llamadas = []

    async def enviar_mensaje(self, telefono, mensaje, canal=None, mensaje_id_citado=None):
        self.llamadas.append(telefono)
        return True, f"wamid.pol.{len(self.llamadas)}"

    async def enviar_plantilla(self, telefono, nombre, parametros, idioma="es", canal=None):
        self.llamadas.append(telefono)
        return True


async def _negocio(codigo):
    n = await mem.crear_negocio(f"Negocio {codigo}", codigo)
    return n["id"], {"negocio_id": n["id"], "phone_number_id": NUMERO}


async def _ledger(negocio_id, wamid, pricing, destinatario="51922000001", hace_horas=0.0):
    assert await mem.registrar_estado_mensaje_meta({
        "wamid": wamid, "estado": "delivered", "momento": datetime.utcnow() - timedelta(hours=hace_horas),
        "phone_number_id": NUMERO, "destinatario": destinatario, "pricing": pricing, "negocio_id": negocio_id,
    })


async def _agotar_cuota(negocio_id, tarifas=True):
    """Deja la cuota gratis en 1 y la gasta: desde acá un envío de servicio se cobra."""
    await mem.guardar_configuracion("meta_cuota_gratis_servicio", "1", negocio_id=negocio_id)
    await _ledger(negocio_id, "wamid.cuota.1", GRATIS_SERVICIO, destinatario="51922999999")
    if tarifas:
        await mem.guardar_configuracion("meta_tarifa_usd_service", "0.03", negocio_id=negocio_id)
        await mem.guardar_configuracion("meta_tarifa_usd_marketing", "0.0703", negocio_id=negocio_id)


async def _filas(negocio_id):
    async with mem.async_session() as s:
        return (await s.execute(select(mem.EnvioMeta).where(mem.EnvioMeta.negocio_id == negocio_id).order_by(mem.EnvioMeta.id))).scalars().all()


async def _reenganche(p, canal, telefono="51922000001"):
    return await envios.enviar_texto(p, telefono, "hola de nuevo", origen="reenganche_inactividad", canal=canal)


# ── Interruptor solo_gratis ──────────────────────────────────────────────

async def test_con_cuota_disponible_el_reenganche_sale_y_queda_la_estimacion():
    nid, canal = await _negocio("pol-1")
    p = _Proveedor()
    r = await _reenganche(p, canal)
    assert r.enviado and not r.bloqueado
    [fila] = await _filas(nid)
    assert (fila.categoria_esperada, fila.gratis_esperado, fila.costo_esperado_usd) == ("service", True, 0.0)


async def test_con_la_cuota_agotada_el_reenganche_se_frena_y_queda_registrado():
    nid, canal = await _negocio("pol-2")
    await _agotar_cuota(nid)
    p = _Proveedor()
    r = await _reenganche(p, canal)
    assert r.bloqueado and not r.enviado and "solo_gratis" in r.motivo and p.llamadas == []
    [fila] = await _filas(nid)
    assert (fila.decision, fila.gratis_esperado, fila.costo_esperado_usd) == ("bloqueado", False, 0.03)


async def test_un_cliente_en_ventana_de_anuncio_recibe_el_reenganche_aunque_la_cuota_este_agotada():
    nid, canal = await _negocio("pol-3")
    await _agotar_cuota(nid)
    await _ledger(nid, "wamid.fep.1", VENTANA, destinatario="51922000003", hace_horas=5)
    r = await _reenganche(_Proveedor(), canal, telefono="51922000003")
    assert r.enviado
    assert (await _filas(nid))[-1].gratis_esperado is True


async def test_la_ventana_de_anuncio_vista_hace_mas_de_la_duracion_configurada_ya_no_cuenta():
    nid, canal = await _negocio("pol-4")
    await _agotar_cuota(nid)
    await _ledger(nid, "wamid.fep.2", VENTANA, destinatario="51922000004", hace_horas=100)
    assert (await _reenganche(_Proveedor(), canal, telefono="51922000004")).bloqueado          # 72 h por defecto
    politica_envios.limpiar_cache()
    await mem.guardar_configuracion("meta_fep_horas", "168", negocio_id=nid)
    assert (await _reenganche(_Proveedor(), canal, telefono="51922000004")).enviado           # con 7 días sí


async def test_un_cliente_que_llego_por_anuncio_y_no_tiene_respuesta_aun_se_considera_gratis():
    nid, canal = await _negocio("pol-5")
    await _agotar_cuota(nid)
    async with mem.async_session() as s:
        s.add(mem.AttributionEvent(negocio_id=nid, conversation_id="c1", lead_telefono="51922000005", tipo_origen="meta_ads", creado=datetime.utcnow() - timedelta(hours=1)))
        await s.commit()
    assert (await _reenganche(_Proveedor(), canal, telefono="51922000005")).enviado
    # Si ya se le respondió, esa primera respuesta ya abrió (o no) el intervalo: sin evidencia, se cobra.
    await mem.guardar_mensaje("51922000005", "assistant", "hola", negocio_id=nid)
    assert (await _reenganche(_Proveedor(), canal, telefono="51922000005")).bloqueado


# ── Interruptor por configuración ────────────────────────────────────────

async def test_modo_siempre_envia_aunque_cueste_y_modo_nunca_no_envia_aunque_sea_gratis():
    nid, canal = await _negocio("pol-6")
    await _agotar_cuota(nid)
    await mem.guardar_configuracion_uso_meta(nid, {"envios": {"autorecarga": True, "modos": {"reenganche_inactividad": "siempre"}}})
    assert (await _reenganche(_Proveedor(), canal)).enviado
    await mem.guardar_configuracion_uso_meta(nid, {"envios": {"modos": {"reenganche_inactividad": "nunca"}}})
    r = await _reenganche(_Proveedor(), canal, telefono="51922000006")
    assert r.bloqueado and "nunca" in r.motivo


async def test_la_plantilla_de_formulario_se_envia_por_defecto_y_se_puede_apagar():
    nid, canal = await _negocio("pol-7")
    await _agotar_cuota(nid)
    await mem.guardar_configuracion_uso_meta(nid, {"envios": {"autorecarga": True}})
    p = _Proveedor()
    assert (await envios.enviar_plantilla(p, "51922000007", "bienvenida", ["Ana"], "es", origen="plantilla_formulario", canal=canal)).enviado
    await mem.guardar_configuracion_uso_meta(nid, {"envios": {"modos": {"plantilla_formulario": "solo_gratis"}}})
    r = await envios.enviar_plantilla(p, "51922000008", "bienvenida", ["Ana"], "es", origen="plantilla_formulario", canal=canal)
    assert r.bloqueado                                       # una plantilla de marketing nunca usa la cuota de servicio
    fila = (await _filas(nid))[-1]
    assert (fila.categoria_esperada, fila.costo_esperado_usd) == ("marketing", 0.0703)


async def test_un_origen_esencial_no_se_puede_poner_en_otro_modo_que_siempre():
    nid, _ = await _negocio("pol-8")
    for origen in ("gabi_respuesta", "gabi_aviso_derivacion", "asesor_texto", "asesor_archivo", "asesor_audio"):
        with pytest.raises(ValueError):
            await mem.guardar_configuracion_uso_meta(nid, {"envios": {"modos": {origen: "nunca"}}})
        with pytest.raises(ValueError):
            await mem.guardar_configuracion_uso_meta(nid, {"envios": {"modos": {origen: "solo_gratis"}}})


async def test_aunque_la_configuracion_se_corrompa_un_esencial_sigue_saliendo():
    nid, canal = await _negocio("pol-9")
    await _agotar_cuota(nid)
    await mem.guardar_configuracion("envios_modo_gabi_respuesta", "nunca", negocio_id=nid)   # escrito a mano, saltándose la validación
    r = await envios.enviar_texto(_Proveedor(), "51922000009", "hola", origen="gabi_respuesta", canal=canal)
    assert r.enviado


@pytest.mark.parametrize("datos", [
    {"envios": "x"}, {"envios": {"modos": {"inventado": "nunca"}}}, {"envios": {"modos": {"reenganche_inactividad": "a veces"}}},
    {"envios": {"tope_mensual_usd": -1}}, {"envios": {"autorecarga": "si"}}, {"envios": {"tope_mensual_usd": "10"}}, {"envios": {"tope_bloquea_esenciales": "si"}},
    {"envios": {"agrupar_minutos": {"gabi_aviso_no_legible": -5}}}, {"envios": {"agrupar_minutos": {"inventado": 5}}},
])
async def test_la_configuracion_de_envios_invalida_se_rechaza(datos):
    nid, _ = await _negocio("pol-10")
    with pytest.raises(ValueError):
        await mem.guardar_configuracion_uso_meta(nid, datos)


# ── Tope mensual ─────────────────────────────────────────────────────────

async def _gastar(nid, n):
    """n mensajes de servicio ya cobrados este mes (a 0.03 cada uno)."""
    for i in range(n):
        await _ledger(nid, f"wamid.gasto.{i}", COBRABLE, destinatario=f"519330000{i:02d}")
    politica_envios.limpiar_cache()


async def test_el_tope_frena_lo_no_esencial_que_se_cobraria_pero_nunca_lo_gratis():
    nid, canal = await _negocio("pol-11")
    await _agotar_cuota(nid)
    await mem.guardar_configuracion_uso_meta(nid, {"envios": {
        "modos": {"plantilla_formulario": "siempre"}, "tope_mensual_usd": 0.10,
    }})
    await _gastar(nid, 3)                                        # USD 0.09 gastados
    p = _Proveedor()
    # una plantilla de marketing (0.0703) llevaría el gasto a 0.1603 > 0.10
    r = await envios.enviar_plantilla(p, "51922000011", "bienvenida", ["Ana"], "es", origen="plantilla_formulario", canal=canal)
    assert r.bloqueado and "tope mensual" in r.motivo
    # el mismo envío a un cliente en ventana de anuncio es gratis: pasa
    await _ledger(nid, "wamid.fep.t", VENTANA, destinatario="51922000012", hace_horas=1)
    r2 = await envios.enviar_plantilla(p, "51922000012", "bienvenida", ["Ana"], "es", origen="plantilla_formulario", canal=canal)
    assert r2.enviado


async def test_el_tope_nunca_frena_a_los_esenciales_opcion_a():
    nid, canal = await _negocio("pol-12")
    await _agotar_cuota(nid)
    await mem.guardar_configuracion_uso_meta(nid, {"envios": {"tope_mensual_usd": 0.01}})
    await _gastar(nid, 3)
    for origen in ("gabi_respuesta", "gabi_aviso_derivacion", "asesor_texto"):
        assert (await envios.enviar_texto(_Proveedor(), "51922000013", "x", origen=origen, canal=canal)).enviado


async def test_con_la_opcion_b_activada_el_tope_tambien_frena_a_los_esenciales():
    nid, canal = await _negocio("pol-13")
    await _agotar_cuota(nid)
    await mem.guardar_configuracion_uso_meta(nid, {"envios": {"tope_mensual_usd": 0.05, "tope_bloquea_esenciales": True}})
    await _gastar(nid, 3)
    r = await envios.enviar_texto(_Proveedor(), "51922000014", "x", origen="gabi_respuesta", canal=canal)
    assert r.bloqueado and "tope mensual" in r.motivo


async def test_sin_monto_elegido_el_tope_es_cero_y_la_autorecarga_o_un_monto_lo_levantan():
    nid, canal = await _negocio("pol-14")
    await _agotar_cuota(nid)
    p = _Proveedor()
    enviar = lambda: envios.enviar_plantilla(p, "51922000015", "b", ["A"], "es", origen="plantilla_formulario", canal=canal)
    # Sin elegir nada: tope de USD 0 → lo no esencial que se cobraría no sale.
    r = await enviar()
    assert r.bloqueado and "tope mensual de USD 0" in r.motivo
    # Un monto suficiente lo permite.
    await mem.guardar_configuracion_uso_meta(nid, {"envios": {"tope_mensual_usd": 5}})
    assert (await enviar()).enviado
    # Quitar el monto (null) vuelve a USD 0, no a "sin límite".
    await mem.guardar_configuracion_uso_meta(nid, {"envios": {"tope_mensual_usd": None}})
    assert (await enviar()).bloqueado
    # La autorecarga sí es "sin tope": se paga lo que cueste.
    await mem.guardar_configuracion_uso_meta(nid, {"envios": {"autorecarga": True}})
    assert (await enviar()).enviado
    # Volver a elegir un monto sale de la autorecarga.
    await mem.guardar_configuracion_uso_meta(nid, {"envios": {"tope_mensual_usd": 0.01}})
    assert (await enviar()).bloqueado


async def test_una_tarifa_desconocida_con_tope_de_cero_frena_lo_no_esencial_y_nunca_lo_esencial():
    nid, canal = await _negocio("pol-14b")
    await mem.guardar_configuracion("meta_cuota_gratis_servicio", "1", negocio_id=nid)
    await _ledger(nid, "wamid.cuota.x", GRATIS_SERVICIO, destinatario="51922999998")     # cuota agotada, SIN tarifas
    p = _Proveedor()
    assert (await envios.enviar_plantilla(p, "51922000030", "b", ["A"], "es", origen="plantilla_formulario", canal=canal)).bloqueado
    assert (await envios.enviar_texto(p, "51922000030", "x", origen="gabi_respuesta", canal=canal)).enviado


async def test_el_resumen_del_mes_informa_gasto_porcentaje_y_alertas_del_tope():
    nid, _ = await _negocio("pol-15")
    await _agotar_cuota(nid)
    await mem.guardar_configuracion_uso_meta(nid, {"envios": {"tope_mensual_usd": 0.10}})
    await _gastar(nid, 3)                                        # 0.09 → 90 %
    r = await mem.resumen_uso_mensual(nid)
    assert (r["tope_mensual_usd"], r["gasto_estimado_usd"], r["porcentaje_tope"], r["alertas_tope"], r["autorecarga"]) == (0.1, 0.09, 90.0, [80], False)
    await _gastar(nid, 1)                                        # el cuarto reutiliza wamid.gasto.0: sigue en 0.09
    await _ledger(nid, "wamid.gasto.extra", COBRABLE, destinatario="51933999999")
    r2 = await mem.resumen_uso_mensual(nid)
    assert r2["alertas_tope"] == [80, 100]
    sin_monto = await mem.resumen_uso_mensual((await _negocio("pol-15b"))[0])
    assert (sin_monto["tope_mensual_usd"], sin_monto["porcentaje_tope"], sin_monto["alertas_tope"], sin_monto["autorecarga"]) == (0, None, [], False)
    await mem.guardar_configuracion_uso_meta(nid, {"envios": {"autorecarga": True}})
    con_autorecarga = await mem.resumen_uso_mensual(nid)
    assert (con_autorecarga["autorecarga"], con_autorecarga["tope_mensual_usd"], con_autorecarga["alertas_tope"]) == (True, None, [])


# ── Fallas de la estimación ──────────────────────────────────────────────

async def test_si_la_estimacion_falla_lo_esencial_sale_y_lo_no_esencial_con_costo_se_frena(monkeypatch):
    nid, canal = await _negocio("pol-16")

    async def explota(*a, **k):
        raise RuntimeError("base lenta")

    monkeypatch.setattr(politica_envios, "estimar_envio", explota)
    assert (await envios.enviar_texto(_Proveedor(), "51922000016", "x", origen="gabi_respuesta", canal=canal)).enviado
    r = await _reenganche(_Proveedor(), canal, telefono="51922000017")
    assert r.bloqueado and "no se pudo estimar" in r.motivo
    # un no esencial en modo "siempre" tampoco se frena por no poder estimar
    await mem.guardar_configuracion_uso_meta(nid, {"envios": {"autorecarga": True, "modos": {"reenganche_inactividad": "siempre"}}})
    assert (await _reenganche(_Proveedor(), canal, telefono="51922000018")).enviado


async def test_una_estimacion_lenta_se_corta_y_no_retrasa_el_envio_esencial(monkeypatch):
    nid, canal = await _negocio("pol-17")

    async def lenta(*a, **k):
        await asyncio.sleep(30)

    monkeypatch.setattr(politica_envios, "estimar_envio", lenta)
    monkeypatch.setattr(politica_envios, "TIEMPO_MAXIMO_ESTIMACION_S", 0.05)
    r = await asyncio.wait_for(envios.enviar_texto(_Proveedor(), "51922000019", "x", origen="gabi_respuesta", canal=canal), 5)
    assert r.enviado


async def test_los_bloqueos_repetidos_del_mismo_cliente_se_anotan_una_vez_por_hora():
    nid, canal = await _negocio("pol-18")
    await _agotar_cuota(nid)
    for _ in range(3):
        assert (await _reenganche(_Proveedor(), canal, telefono="51922000020")).bloqueado
    assert [f.decision for f in await _filas(nid)] == ["bloqueado"]


# ── Informe por origen ───────────────────────────────────────────────────

async def test_el_informe_cruza_cada_envio_con_lo_que_cobro_meta_por_origen():
    nid, canal = await _negocio("pol-19")
    await mem.guardar_configuracion_uso_meta(nid, {"tarifas_usd": {"service": 0.03}})
    p = _Proveedor()
    for i, (origen, pricing) in enumerate([
        ("gabi_respuesta", GRATIS_SERVICIO), ("gabi_respuesta", VENTANA), ("gabi_respuesta", COBRABLE), ("asesor_texto", COBRABLE),
    ]):
        r = await envios.enviar_texto(p, f"519440000{i:02d}", "x", origen=origen, canal=canal)
        await _ledger(nid, r.wamid, pricing, destinatario=f"519440000{i:02d}")
    await envios.enviar_texto(p, "51944000099", "x", origen="gabi_respuesta", canal=canal)     # sin estado todavía

    informe = await mem.resumen_envios_por_origen(nid)
    por = {o["origen"]: o for o in informe["origenes"]}
    g = por["gabi_respuesta"]
    assert (g["enviados"], g["gratis_cuota"], g["gratis_ventana_anuncio"], g["cobrables"], g["sin_estado"], g["costo_estimado_usd"]) == (
        4, 1, 1, {"service": 1}, 1, 0.03)
    assert por["asesor_texto"]["cobrables"] == {"service": 1} and por["asesor_texto"]["costo_estimado_usd"] == 0.03


async def test_el_informe_muestra_los_bloqueos_con_su_motivo_y_el_costo_sin_tarifa_es_desconocido():
    nid, canal = await _negocio("pol-20")
    await _agotar_cuota(nid)
    await _reenganche(_Proveedor(), canal)
    p = _Proveedor()
    r = await envios.enviar_texto(p, "51955000001", "x", origen="gabi_respuesta", canal=canal)
    await _ledger(nid, r.wamid, COBRABLE, destinatario="51955000001")
    await mem.guardar_configuracion("meta_tarifa_usd_service", "", negocio_id=nid)
    informe = await mem.resumen_envios_por_origen(nid)
    por = {o["origen"]: o for o in informe["origenes"]}
    assert por["reenganche_inactividad"]["bloqueados"] == 1
    assert list(por["reenganche_inactividad"]["motivos_bloqueo"]) == ["solo_gratis: este envío se cobraría"]
    assert por["gabi_respuesta"]["costo_estimado_usd"] is None
