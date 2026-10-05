# tests/test_seguridad_configuracion_dinero.py — 2026-10-05, paquete A "seguridad
# del dinero": la configuración que mueve dinero o puede callar a Gabi se
# valida con salvaguardas, deja constancia de quién cambió qué (en la misma
# transacción) y se puede leer y auditar.

import json
import os
from datetime import datetime

os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")
os.environ.setdefault("WHATSAPP_PROVIDER", "meta")

import pytest
from sqlalchemy import select
from starlette.requests import Request

from agent import dashboard
from agent import memory as mem
from agent import politica_envios


@pytest.fixture(autouse=True)
def _cache_limpia():
    politica_envios.limpiar_cache()
    yield


async def _negocio(codigo):
    return (await mem.crear_negocio(f"Negocio {codigo}", codigo))["id"]


async def _auditoria(nid):
    async with mem.async_session() as s:
        return (await s.execute(select(mem.RegistroAuditoria).where(mem.RegistroAuditoria.negocio_id == nid).order_by(mem.RegistroAuditoria.creado))).scalars().all()


# ── Salvaguardas ─────────────────────────────────────────────────────────

async def test_el_tope_que_frena_lo_esencial_se_rechaza_si_el_tope_es_cero():
    nid = await _negocio("seg-1")
    with pytest.raises(ValueError, match="Gabi dejaría de responder"):
        await mem.guardar_configuracion_uso_meta(nid, {"confirmar_riesgo": True, "envios": {"tope_bloquea_esenciales": True}})
    # tampoco con tope explícito en 0
    with pytest.raises(ValueError, match="USD 0"):
        await mem.guardar_configuracion_uso_meta(nid, {"confirmar_riesgo": True, "envios": {"tope_mensual_usd": 0, "tope_bloquea_esenciales": True}})
    assert await mem.obtener_configuracion("envios_tope_bloquea_esenciales", "false", negocio_id=nid) == "false"


async def test_con_un_monto_el_tope_puede_frenar_lo_esencial_pero_solo_con_confirmacion():
    nid = await _negocio("seg-2")
    datos = {"envios": {"tope_mensual_usd": 20, "tope_bloquea_esenciales": True}}
    with pytest.raises(ValueError, match="Confirma el riesgo"):
        await mem.guardar_configuracion_uso_meta(nid, datos)
    assert await mem.obtener_configuracion("envios_tope_mensual_usd", "", negocio_id=nid) == ""     # nada se guardó
    await mem.guardar_configuracion_uso_meta(nid, {**datos, "confirmar_riesgo": True})
    assert await mem.obtener_configuracion("envios_tope_bloquea_esenciales", "false", negocio_id=nid) == "true"


async def test_quitar_el_limite_y_una_cuota_inflada_tambien_piden_confirmacion():
    nid = await _negocio("seg-3")
    for datos, texto in (
        ({"envios": {"autorecarga": True}}, "quitar el límite"),
        ({"cuota_gratis_servicio": 5000}, "cuota gratis mayor a 1000"),
    ):
        with pytest.raises(ValueError, match=texto):
            await mem.guardar_configuracion_uso_meta(nid, datos)
        await mem.guardar_configuracion_uso_meta(nid, {**datos, "confirmar_riesgo": True})
    # lo no sensible no pide confirmación
    await mem.guardar_configuracion_uso_meta(nid, {"envios": {"tope_mensual_usd": 30}})


# ── Auditoría ────────────────────────────────────────────────────────────

async def test_cada_cambio_deja_quien_cuando_y_el_valor_anterior_y_nuevo():
    nid = await _negocio("seg-4")
    await mem.guardar_configuracion_uso_meta(nid, {"envios": {"tope_mensual_usd": 20}}, autor="jmillones")
    await mem.guardar_configuracion_uso_meta(nid, {"envios": {"tope_mensual_usd": 50, "modos": {"reenganche_inactividad": "nunca"}}}, autor="jmillones")
    filas = await _auditoria(nid)
    assert [f.actor for f in filas] == ["jmillones", "jmillones"] and {f.accion for f in filas} == {"uso_meta_configuracion"}
    assert filas[0].payload["cambios"] == {"envios_tope_mensual_usd": {"antes": None, "despues": "20.0"}}
    assert filas[1].payload["cambios"]["envios_tope_mensual_usd"] == {"antes": "20.0", "despues": "50.0"}
    assert filas[1].payload["cambios"]["envios_modo_reenganche_inactividad"] == {"antes": None, "despues": "nunca"}

    historial = await mem.listar_cambios_configuracion(nid)
    assert [h["actor"] for h in historial] == ["jmillones", "jmillones"]
    assert historial[0]["cambios"]["envios_modo_reenganche_inactividad"]["despues"] == "nunca"   # más reciente primero


async def test_guardar_el_mismo_valor_no_ensucia_el_historial_y_marca_el_riesgo_confirmado():
    nid = await _negocio("seg-5")
    r1 = await mem.guardar_configuracion_uso_meta(nid, {"envios": {"tope_mensual_usd": 20}}, autor="a")
    r2 = await mem.guardar_configuracion_uso_meta(nid, {"envios": {"tope_mensual_usd": 20}}, autor="a")
    assert r1["modificadas"] and r2["modificadas"] == [] and len(await _auditoria(nid)) == 1
    await mem.guardar_configuracion_uso_meta(nid, {"confirmar_riesgo": True, "envios": {"autorecarga": True}}, autor="a")
    assert (await mem.listar_cambios_configuracion(nid))[0]["riesgo_confirmado"] is True


async def test_si_no_se_puede_dejar_constancia_no_se_cambia_nada(monkeypatch):
    nid = await _negocio("seg-6")

    class Roto:
        def __init__(self, *a, **k):
            raise RuntimeError("auditoría caída")

    monkeypatch.setattr(mem, "RegistroAuditoria", Roto)
    with pytest.raises(RuntimeError):
        await mem.guardar_configuracion_uso_meta(nid, {"envios": {"tope_mensual_usd": 99}}, autor="a")
    assert await mem.obtener_configuracion("envios_tope_mensual_usd", "", negocio_id=nid) == ""


async def test_el_historial_es_por_negocio():
    a, b = await _negocio("seg-7a"), await _negocio("seg-7b")
    await mem.guardar_configuracion_uso_meta(a, {"envios": {"tope_mensual_usd": 20}}, autor="x")
    assert await mem.listar_cambios_configuracion(b) == []


# ── Lectura de la configuración y rutas ──────────────────────────────────

async def test_la_configuracion_vigente_trae_los_ocho_origenes_con_sus_defaults_y_lo_que_se_cambio():
    nid = await _negocio("seg-8")
    c = await mem.obtener_configuracion_envios(nid)
    por = {o["origen"]: o for o in c["origenes"]}
    assert len(por) == 8
    assert all(por[o]["esencial"] and por[o]["modo"] == "siempre" for o in ("gabi_respuesta", "gabi_aviso_derivacion", "asesor_texto", "asesor_archivo", "asesor_audio"))
    assert (por["reenganche_inactividad"]["modo"], por["gabi_aviso_no_legible"]["modo"], por["gabi_aviso_no_legible"]["agrupar_minutos"]) == ("solo_gratis", "solo_gratis", 10)
    assert (por["plantilla_formulario"]["modo"], por["plantilla_formulario"]["categoria_plantilla"]) == ("siempre", "marketing")
    assert (c["tope_mensual_usd"], c["autorecarga"], c["tope_bloquea_esenciales"], c["meta_fep_horas"], c["cuota_gratis_servicio"]) == (0, False, False, 72, 1000)

    await mem.guardar_configuracion_uso_meta(nid, {"tarifas_usd": {"service": 0.03}, "envios": {"tope_mensual_usd": 15, "modos": {"reenganche_inactividad": "nunca"}}})
    c2 = await mem.obtener_configuracion_envios(nid)
    assert c2["tope_mensual_usd"] == 15 and c2["tarifas_usd"] == {"service": 0.03}
    assert {o["origen"]: o for o in c2["origenes"]}["reenganche_inactividad"]["modo"] == "nunca"


def _peticion(sesion=None):
    return Request({"type": "http", "method": "GET", "path": "/x", "headers": [], "query_string": b"",
                    "client": ("203.0.113.9", 1), "session": sesion or {}})


async def test_las_rutas_nuevas_responden_y_la_sesion_trae_el_nombre():
    nid = await _negocio("seg-9")
    admin = {"negocio_id": nid, "rol": "admin", "username": "jmillones"}
    await mem.guardar_configuracion_uso_meta(nid, {"envios": {"tope_mensual_usd": 20}}, autor="jmillones")

    conf = json.loads((await dashboard.uso_mensajes_configuracion_actual_json(usuario=admin)).body)
    assert conf["tope_mensual_usd"] == 20
    hist = json.loads((await dashboard.uso_mensajes_historial_cambios_json(usuario=admin)).body)
    assert hist["cambios"][0]["actor"] == "jmillones" and hist["cambios"][0]["creado"].endswith("Z")

    r = await dashboard.sesion_actual(_peticion({"csrf_token": "t"}), usuario={**admin, "nombre": "Jesús Millones", "disponible": None})
    assert json.loads(r.body)["usuario"]["nombre"] == "Jesús Millones"
    sin_nombre = await dashboard.sesion_actual(_peticion(), usuario={**admin, "nombre": None, "disponible": None})
    assert json.loads(sin_nombre.body)["usuario"]["nombre"] == "jmillones"


def test_las_rutas_de_lectura_nuevas_existen_y_son_get():
    for ruta in ("/uso-mensajes/configuracion.json", "/uso-mensajes/historial-cambios.json"):
        encontradas = [r for r in dashboard.router.routes if getattr(r, "path", "").endswith(ruta) and "GET" in r.methods]
        assert len(encontradas) == 1


# ── Largo de las claves de configuración ─────────────────────────────────

def test_toda_clave_de_configuracion_generada_cabe_en_la_columna():
    """SQLite no impone el largo y Postgres sí (el mismo origen del incidente de
    eventos_lead.tipo VARCHAR(30)): hay que comprobarlo a mano."""
    from agent.envios import ORIGENES

    limite = mem.Configuracion.__table__.c.clave.type.length
    claves = ["meta_cuota_gratis_servicio", "meta_zona_horaria_mes", "meta_fep_horas", "envios_tope_mensual_usd",
              "envios_tope_modo", "envios_tope_bloquea_esenciales"]
    claves += [f"meta_tarifa_usd_{'x' * 40}"]                                         # categoría del largo máximo permitido
    claves += [f"meta_uso_previo_servicio_2026-10:{'9' * 30}"]                         # phone_number_id del largo máximo permitido
    for origen in ORIGENES:
        claves += [f"envios_modo_{origen}", f"envios_agrupar_minutos_{origen}", f"envios_categoria_{origen}"]
    largas = [c for c in claves if len(c) > limite]
    assert limite >= 100 and largas == []
