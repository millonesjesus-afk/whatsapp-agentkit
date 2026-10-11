# tests/test_llamadas_endpoints.py — "Para llamar" (2026-10-09): endpoints del panel (permisos, CSRF, validación), el
# contrato ADITIVO de inicio.json, los scripts de configuración/medición y la migración de Alembic.

import json
import os
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from agent import dashboard
from agent import llamadas as ll
from agent import memory as mem
from tests.test_llamadas_flujo import (
    TEL, _activar, _asesores, _cfg, _encender, _lead, _negocio, _tareas, _tocar, _usuario,
)
from tests.test_llamadas_resultados import _escenario, _lima

RAIZ = Path(__file__).resolve().parent.parent


class _Peticion:
    def __init__(self, cuerpo):
        self._cuerpo = cuerpo

    async def json(self):
        if isinstance(self._cuerpo, Exception):
            raise self._cuerpo
        return self._cuerpo


def _json(respuesta):
    return json.loads(respuesta.body)


def _ruta(path: str, metodo: str):
    return next(r for r in dashboard.router.routes if getattr(r, "path", None) == f"/dashboard{path}" and metodo in r.methods)


def _dependencias(ruta):
    return [d.call for d in ruta.dependant.dependencies]


# ── Permisos y CSRF (introspección de las rutas) ─────────────────────────────────────────────────

@pytest.mark.parametrize("path", ["/llamadas/{tarea_id}/resultado", "/llamadas/{tarea_id}/reasignar", "/llamadas/{tarea_id}/descartar", "/configuracion/llamadas.json"])
def test_todo_post_exige_csrf(path):
    assert dashboard.verificar_csrf in _dependencias(_ruta(path, "POST"))


@pytest.mark.parametrize("path, metodo, permitidos, prohibidos", [
    ("/configuracion/llamadas.json", "GET", ["admin"], ["supervisor", "asesor"]),
    ("/configuracion/llamadas.json", "POST", ["admin"], ["supervisor", "asesor"]),
    ("/llamadas/{tarea_id}/reasignar", "POST", ["admin", "supervisor"], ["asesor"]),
    ("/llamadas/{tarea_id}/descartar", "POST", ["admin", "supervisor"], ["asesor"]),
])
async def test_roles_de_cada_ruta(path, metodo, permitidos, prohibidos):
    verificador = next(c for c in _dependencias(_ruta(path, metodo)) if getattr(c, "__name__", "") == "_verificar")
    for rol in permitidos:
        assert (await verificador(usuario={"rol": rol, "username": "x", "negocio_id": "n"}))["rol"] == rol
    for rol in prohibidos:
        with pytest.raises(HTTPException) as e:
            await verificador(usuario={"rol": rol, "username": "x", "negocio_id": "n"})
        assert e.value.status_code == 403


@pytest.mark.parametrize("path, metodo", [("/llamadas.json", "GET"), ("/llamadas/{tarea_id}/resultado", "POST")])
def test_el_listado_y_el_resultado_requieren_sesion(path, metodo):
    assert dashboard._usuario_actual in _dependencias(_ruta(path, metodo))


# ── GET /llamadas.json ───────────────────────────────────────────────────────────────────────────

async def test_listado_apagado_devuelve_lista_vacia_con_el_contrato_completo():
    negocio, _ = await _negocio("le-off")
    cuerpo = _json(await dashboard.llamadas_json(usuario=_usuario(negocio, "ana")))
    assert cuerpo["tareas"] == [] and cuerpo["activo"] is False and cuerpo["modo"] == "apagado"
    assert set(cuerpo["kpi"]) == {"pendientes", "programadas", "sin_asignar", "vencidas", "sin_hacer", "llamadas_registradas", "contactos", "tasa_contacto", "ventana_dias"}


async def test_listado_activo_trae_el_contrato_de_cada_tarea():
    negocio, canal, tarea, dueno = await _escenario("le-lista")
    cuerpo = _json(await dashboard.llamadas_json(usuario=_usuario(negocio, dueno)))
    assert cuerpo["activo"] is True and cuerpo["modo"] == "activo" and "medicion" not in cuerpo
    (t,) = cuerpo["tareas"]
    assert set(t) == {
        "id", "conversation_id", "telefono", "nombre", "producto", "estado", "motivo_cierre", "segmento", "puntaje", "senales",
        "asesor", "asesor_nombre", "asignada_en", "programada_para", "intentos", "max_intentos", "ultimo_intento_en",
        "proximo_intento_en", "resultado_llamada", "nota", "vencida", "sin_hacer", "reasignaciones", "creada_en", "cerrada_en", "vence_en",
        "aceptada_por_cliente",     # 2026-10-11 (aditivo): el cliente aceptó la llamada respondiendo a la oferta de Gabi
    }
    assert t["estado"] == "pendiente" and t["segmento"] == "A" and t["puntaje"] == 12 and t["nombre"] == "Ana" and t["asesor"] == dueno
    assert t["max_intentos"] == 3 and t["vencida"] is False and t["creada_en"].endswith("Z") and t["asesor_nombre"] == dueno.capitalize()
    assert cuerpo["kpi"]["pendientes"] == 1
    sup = _json(await dashboard.llamadas_json(usuario=_usuario(negocio, "sup", "supervisor")))
    assert set(sup["medicion"]) >= {"dias", "tareas", "por_modo", "por_grupo", "por_segmento", "por_estado"}


async def test_filtro_de_estado_y_valor_invalido():
    negocio, canal, tarea, dueno = await _escenario("le-estado")
    u = _usuario(negocio, dueno)
    await ll.registrar_resultado(tarea.id, negocio["id"], u, "contesto_agendado")
    assert _json(await dashboard.llamadas_json(usuario=u))["tareas"] == []
    cerradas = _json(await dashboard.llamadas_json(estado="cerradas", usuario=u))
    assert [t["estado"] for t in cerradas["tareas"]] == ["cumplida"] and cerradas["kpi"]["llamadas_registradas"] == 1
    assert cerradas["kpi"]["contactos"] == 1 and cerradas["kpi"]["tasa_contacto"] == 1.0
    assert len(_json(await dashboard.llamadas_json(estado="todas", usuario=u))["tareas"]) == 1
    with pytest.raises(HTTPException) as e:
        await dashboard.llamadas_json(estado="otra", usuario=u)
    assert e.value.status_code == 400


async def test_la_tasa_de_contacto_mezcla_contestadas_y_no_contestadas():
    negocio, canal, tarea, dueno = await _escenario("le-tasa")
    await ll.registrar_resultado(tarea.id, negocio["id"], _usuario(negocio, dueno), "no_contesto")
    kpi = _json(await dashboard.llamadas_json(usuario=_usuario(negocio, dueno)))["kpi"]
    assert kpi["llamadas_registradas"] == 1 and kpi["contactos"] == 0 and kpi["tasa_contacto"] == 0.0


# ── POST resultado / reasignar / descartar ───────────────────────────────────────────────────────

async def test_post_resultado_devuelve_la_tarea_y_la_accion():
    negocio, canal, tarea, dueno = await _escenario("le-res")
    r = await dashboard.llamada_resultado(tarea.id, _Peticion({"resultado": "contesto_agendado", "nota": "mañana 4 pm"}), usuario=_usuario(negocio, dueno), _csrf=None)
    cuerpo = _json(r)
    assert cuerpo["ok"] is True and cuerpo["accion"] == "abrir_agendar" and cuerpo["conversation_id"] == tarea.conversation_id
    assert cuerpo["tarea"]["estado"] == "cumplida" and cuerpo["tarea"]["nota"] == "mañana 4 pm"


@pytest.mark.parametrize("cuerpo, codigo", [
    ({"resultado": "inventado"}, 400), ({}, 400), ({"resultado": "contesto_llamar_luego"}, 400), (["no", "objeto"], 400), (Exception("json roto"), 400),
])
async def test_post_resultado_valida_el_cuerpo(cuerpo, codigo):
    negocio, canal, tarea, dueno = await _escenario("le-res2")
    with pytest.raises(HTTPException) as e:
        await dashboard.llamada_resultado(tarea.id, _Peticion(cuerpo), usuario=_usuario(negocio, dueno), _csrf=None)
    assert e.value.status_code == codigo


async def test_post_resultado_mapea_los_errores_a_http():
    negocio, canal, tarea, dueno = await _escenario("le-res3")
    otro = "beto" if dueno == "ana" else "ana"
    with pytest.raises(HTTPException) as e:
        await dashboard.llamada_resultado(tarea.id, _Peticion({"resultado": "no_contesto"}), usuario=_usuario(negocio, otro), _csrf=None)
    assert e.value.status_code == 403
    with pytest.raises(HTTPException) as e:
        await dashboard.llamada_resultado("no-existe", _Peticion({"resultado": "no_contesto"}), usuario=_usuario(negocio, dueno), _csrf=None)
    assert e.value.status_code == 404
    await dashboard.llamada_resultado(tarea.id, _Peticion({"resultado": "contesto_agendado"}), usuario=_usuario(negocio, dueno), _csrf=None)
    with pytest.raises(HTTPException) as e:
        await dashboard.llamada_resultado(tarea.id, _Peticion({"resultado": "no_contesto"}), usuario=_usuario(negocio, dueno), _csrf=None)
    assert e.value.status_code == 409
    await _cfg(negocio, **{ll.CLAVE_GABI_ACTIVO: "0"})
    with pytest.raises(HTTPException) as e:
        await dashboard.llamada_resultado(tarea.id, _Peticion({"resultado": "no_contesto"}), usuario=_usuario(negocio, dueno), _csrf=None)
    assert e.value.status_code == 409


async def test_post_reasignar_y_descartar():
    negocio, canal, tarea, dueno = await _escenario("le-reas")
    otro = "beto" if dueno == "ana" else "ana"
    sup = _usuario(negocio, "sup", "supervisor")
    cuerpo = _json(await dashboard.llamada_reasignar(tarea.id, _Peticion({"asesor": otro}), usuario=sup, _csrf=None))
    assert cuerpo["ok"] and cuerpo["tarea"]["asesor"] == otro
    with pytest.raises(HTTPException) as e:
        await dashboard.llamada_reasignar(tarea.id, _Peticion({"asesor": 5}), usuario=sup, _csrf=None)
    assert e.value.status_code == 400
    with pytest.raises(HTTPException) as e:
        await dashboard.llamada_reasignar(tarea.id, _Peticion({"asesor": "fantasma"}), usuario=sup, _csrf=None)
    assert e.value.status_code == 400
    cuerpo = _json(await dashboard.llamada_descartar(tarea.id, _Peticion({"nota": "no hace falta"}), usuario=sup, _csrf=None))
    assert cuerpo["tarea"]["estado"] == "cancelada" and cuerpo["tarea"]["nota"] == "no hace falta"
    with pytest.raises(HTTPException) as e:
        await dashboard.llamada_descartar(tarea.id, _Peticion({}), usuario=sup, _csrf=None)
    assert e.value.status_code == 409


# ── Configuración ────────────────────────────────────────────────────────────────────────────────

def _admin(negocio, username="angie"):
    return _usuario(negocio, username, "admin")


async def _post_config(negocio, cuerpo, username="angie"):
    return _json(await dashboard.actualizar_configuracion_llamadas_json(_Peticion(cuerpo), usuario=_admin(negocio, username), _csrf=None))


async def _get_config(negocio):
    return _json(await dashboard.configuracion_llamadas_json(usuario=_admin(negocio)))


async def test_get_configuracion_por_defecto_esta_todo_apagado_con_los_defaults_del_diseno():
    negocio, _ = await _negocio("lc-def")
    c = await _get_config(negocio)
    assert c["gabi_activo"] is False and c["modo"] == "sombra" and c["modo_efectivo"] == "apagado" and c["motivo_degradado"] is None
    assert (c["horas_silencio"], c["puntaje_minimo"], c["exploracion_pct"], c["holdout_pct"]) == (4.0, 4, 0.0, 30.0)
    assert (c["max_intentos"], c["sla_horas_habiles"], c["vida_max_dias"], c["oferta_activa"], c["oferta_texto"]) == (3, 2.0, 3.0, False, None)
    assert c["oferta_texto_por_defecto"] == ll.OFERTA_TEXTO_POR_DEFECTO
    assert c["respuesta_haiku"] is False        # 2026-10-11: el clasificador Haiku de las respuestas ambiguas viene apagado
    r = c["responsabilidad"]
    assert r["texto"] == ll.TEXTO_RESPONSABILIDAD and r["version_texto"] == "v1" and r["aceptada_vigente"] is False
    assert r["aceptada_por"] is None and r["aceptada_en"] is None
    assert "Maiek AI no brinda asesoría legal" in r["texto"]


async def test_post_configuracion_guarda_un_subconjunto_y_devuelve_el_estado():
    negocio, _ = await _negocio("lc-post")
    c = await _post_config(negocio, {"gabi_activo": True, "modo": "sombra", "horas_silencio": 6, "puntaje_minimo": 5, "holdout_pct": 50, "sla_horas_habiles": 1.5})
    assert c["ok"] is True and c["gabi_activo"] is True and c["modo_efectivo"] == "sombra"
    assert (c["horas_silencio"], c["puntaje_minimo"], c["holdout_pct"], c["sla_horas_habiles"], c["max_intentos"]) == (6.0, 5, 50.0, 1.5, 3)
    assert await ll.modo_efectivo(negocio["id"]) == "sombra"


@pytest.mark.parametrize("cuerpo", [
    {"inventado": 1}, {"gabi_activo": "si"}, {"gabi_activo": 1}, {"modo": "apagado"}, {"modo": "ACTIVO"},
    {"horas_silencio": 0}, {"horas_silencio": 73}, {"horas_silencio": "4"}, {"horas_silencio": True},
    {"puntaje_minimo": 0}, {"puntaje_minimo": 13}, {"puntaje_minimo": 4.5},
    {"exploracion_pct": -1}, {"exploracion_pct": 101}, {"holdout_pct": 150},
    {"max_intentos": 0}, {"max_intentos": 11}, {"max_intentos": 2.5},
    {"sla_horas_habiles": 0.1}, {"sla_horas_habiles": 25}, {"vida_max_dias": 0}, {"vida_max_dias": 15},
    {"oferta_activa": "1"}, {"oferta_texto": 5}, {"oferta_texto": "Hola, te cuento de las termas"}, {"oferta_texto": "x" * 700},
    {"aceptar_responsabilidad": True}, {"aceptar_responsabilidad": "si", "version_texto": "v1"},
    {"aceptar_responsabilidad": True, "revocar_responsabilidad": True, "version_texto": "v1"},
])
async def test_post_configuracion_rechaza_lo_invalido(cuerpo):
    negocio, _ = await _negocio("lc-inv")
    with pytest.raises(HTTPException) as e:
        await _post_config(negocio, cuerpo)
    assert e.value.status_code == 400


async def test_post_configuracion_es_todo_o_nada():
    negocio, _ = await _negocio("lc-todo")
    with pytest.raises(HTTPException):
        await _post_config(negocio, {"gabi_activo": True, "horas_silencio": 999})
    assert (await _get_config(negocio))["gabi_activo"] is False


async def test_post_configuracion_exige_un_cuerpo_json_objeto():
    negocio, _ = await _negocio("lc-json")
    for cuerpo in (Exception("roto"), [1, 2], "texto"):
        with pytest.raises(HTTPException) as e:
            await _post_config(negocio, cuerpo)
        assert e.value.status_code == 400


async def test_aceptar_y_revocar_la_responsabilidad_desde_el_panel():
    negocio, _ = await _negocio("lc-resp")
    c = await _post_config(negocio, {"gabi_activo": True, "modo": "activo"})
    assert c["modo"] == "activo" and c["modo_efectivo"] == "sombra" and c["motivo_degradado"] == "sin_aceptacion_de_responsabilidad"
    with pytest.raises(HTTPException) as e:
        await _post_config(negocio, {"aceptar_responsabilidad": True, "version_texto": "v0"})
    assert e.value.status_code == 400
    c = await _post_config(negocio, {"aceptar_responsabilidad": True, "version_texto": "v1"}, username="angie")
    assert c["modo_efectivo"] == "activo" and c["motivo_degradado"] is None
    r = c["responsabilidad"]
    assert r["aceptada_vigente"] is True and r["aceptada_por"] == "angie" and r["aceptada_en"].endswith("Z") and r["version_aceptada"] == "v1"
    c = await _post_config(negocio, {"revocar_responsabilidad": True}, username="jefe")
    assert c["modo"] == "sombra" and c["modo_efectivo"] == "sombra"
    r = c["responsabilidad"]
    assert r["aceptada_vigente"] is False and r["aceptada_por"] is None and r["revocada_por"] == "jefe"
    acciones = [a.accion for a in (await _auditoria())]
    assert acciones == ["llamadas_responsabilidad_aceptada", "llamadas_responsabilidad_revocada"]


async def _auditoria():
    async with mem.async_session() as s:
        return (await s.execute(select(mem.RegistroAuditoria).where(mem.RegistroAuditoria.accion.like("llamadas_%")).order_by(mem.RegistroAuditoria.creado))).scalars().all()


async def test_apagar_o_pasar_a_sombra_desde_el_panel_cancela_las_tareas_abiertas():
    negocio, canal, tarea, dueno = await _escenario("lc-apagar")
    c = await _post_config(negocio, {"modo": "sombra"})
    assert c["modo_efectivo"] == "sombra"
    (t,) = await _tareas()
    assert t.estado == "cancelada" and t.motivo_cierre == "compuerta_cerrada"


async def test_el_texto_de_la_oferta_se_guarda_y_se_puede_volver_al_por_defecto():
    negocio, _ = await _negocio("lc-texto")
    texto = "Hola {nombre}, un asesor puede llamarte hoy. Si no quieres que te llamemos, avísame y no lo hacemos. " * 3
    c = await _post_config(negocio, {"oferta_texto": texto})
    assert c["oferta_texto"] == texto.strip() and len(texto) > 200          # más de 200: por eso configuracion.valor pasó a 1000
    c = await _post_config(negocio, {"oferta_texto": ""})
    assert c["oferta_texto"] is None


async def test_la_advertencia_del_silencio_largo():
    negocio, _ = await _negocio("lc-adv")
    c = await _post_config(negocio, {"horas_silencio": 20})
    assert c["advertencias"] and "15 h" in c["advertencias"][0]
    assert (await _post_config(negocio, {"horas_silencio": 4}))["advertencias"] == []


async def test_la_configuracion_es_del_negocio_de_la_sesion():
    a, _ = await _negocio("lc-ten-a")
    b, _ = await _negocio("lc-ten-b")
    await _post_config(a, {"gabi_activo": True, "holdout_pct": 10})
    assert (await _get_config(b))["gabi_activo"] is False and (await _get_config(b))["holdout_pct"] == 30.0


# ── Inicio: contrato ADITIVO ─────────────────────────────────────────────────────────────────────

async def _inicio(usuario):
    return _json(await dashboard.inicio_json(usuario=usuario))


async def test_inicio_con_el_modulo_apagado_solo_suma_dos_totales_en_cero():
    negocio, canal = await _negocio("li-off")
    await _lead(negocio, canal)
    cuerpo = await _inicio(_admin(negocio))
    assert cuerpo["zona_accion"]["totales"]["llamadas_pendientes"] == 0 and cuerpo["zona_accion"]["totales"]["llamadas_vencidas"] == 0
    assert [i for i in cuerpo["zona_accion"]["items"] if i["categoria"] == "llamar"] == []
    assert set(cuerpo) == {"vision_total", "zona_accion", "zona_indicadores", "avisos"} and cuerpo["avisos"] == []


async def test_inicio_activo_muestra_las_llamadas_al_dueno_y_al_supervisor():
    negocio, canal, tarea, dueno = await _escenario("li-act")
    otro = "beto" if dueno == "ana" else "ana"
    for usuario in (_usuario(negocio, dueno), _usuario(negocio, "sup", "supervisor"), _admin(negocio)):
        z = (await _inicio(usuario))["zona_accion"]
        (item,) = [i for i in z["items"] if i["categoria"] == "llamar"]
        assert item["telefono"] == TEL and item["conversation_id"] == tarea.conversation_id and item["nombre"] == "Ana"
        assert item["motivo"] == "Para llamar" and item["segmento"] == "A" and item["vencida"] is False and item["tarea_id"] == tarea.id
        assert item["asesor"] == dueno and item["programada_para"] is None
        assert z["totales"]["llamadas_pendientes"] == 1 and z["totales"]["llamadas_vencidas"] == 0 and z["vacio"] is False
    ajena = (await _inicio(_usuario(negocio, otro)))["zona_accion"]
    assert [i for i in ajena["items"] if i["categoria"] == "llamar"] == [] and ajena["totales"]["llamadas_pendientes"] == 0


async def test_inicio_no_muestra_las_programadas_ni_las_de_control_ni_las_de_sombra():
    negocio, canal, tarea, dueno = await _escenario("li-prog")
    await _tocar(tarea.id, estado="programada", programada_para=datetime.utcnow() + timedelta(hours=5))
    assert (await _inicio(_admin(negocio)))["zona_accion"]["totales"]["llamadas_pendientes"] == 0
    await _tocar(tarea.id, estado="pendiente", grupo="control")
    assert (await _inicio(_admin(negocio)))["zona_accion"]["totales"]["llamadas_pendientes"] == 0


async def test_el_aviso_de_llamadas_vencidas_es_para_supervisor_y_admin_y_solo_si_hay_vencidas():
    negocio, canal, tarea, dueno = await _escenario("li-aviso")
    for usuario in (_usuario(negocio, "sup", "supervisor"), _admin(negocio)):
        assert [a for a in (await _inicio(usuario))["avisos"] if a["id"] == "llamadas-vencidas"] == []
    await _tocar(tarea.id, asignada_en=datetime.utcnow() - timedelta(hours=3))
    for usuario in (_usuario(negocio, "sup", "supervisor"), _admin(negocio)):
        avisos = [a for a in (await _inicio(usuario))["avisos"] if a["id"] == "llamadas-vencidas"]
        assert len(avisos) == 1 and avisos[0]["nivel"] == "warning" and "1 llamada sin hacer" in avisos[0]["titulo"]
        assert set(avisos[0]) == {"id", "nivel", "titulo", "detalle", "enlace"}
    asesor = await _inicio(_usuario(negocio, dueno))
    assert asesor["avisos"] == []
    z = (await _inicio(_admin(negocio)))["zona_accion"]
    assert z["totales"]["llamadas_vencidas"] == 1 and [i for i in z["items"] if i["categoria"] == "llamar"][0]["vencida"] is True


# ── Scripts de configuración y medición ──────────────────────────────────────────────────────────

def _cargar(nombre):
    import importlib.util
    spec = importlib.util.spec_from_file_location(f"script_{nombre}", RAIZ / "scripts" / f"{nombre}.py")
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


async def test_el_script_de_configuracion_muestra_y_cambia_con_la_misma_validacion(capsys):
    negocio, _ = await _negocio("ls-conf")
    script = _cargar("configurar_llamadas")
    estado = await script.main(["--negocio-id", negocio["id"]])
    assert estado["modo_efectivo"] == "apagado"
    estado = await script.main(["--negocio-id", negocio["id"], "--activo", "1", "--modo", "sombra", "--holdout-pct", "20"])
    assert estado["gabi_activo"] is True and estado["modo_efectivo"] == "sombra" and estado["holdout_pct"] == 20.0
    estado = await script.main(["--negocio-id", negocio["id"], "--modo", "activo"])
    assert estado["modo_efectivo"] == "sombra" and "NO está en juego" in capsys.readouterr().out
    with pytest.raises(ValueError):
        await script.main(["--negocio-id", negocio["id"], "--aceptar-responsabilidad", "v1"])          # falta --como
    with pytest.raises(ValueError):
        await script.main(["--negocio-id", negocio["id"], "--horas-silencio", "500"])
    estado = await script.main(["--negocio-id", negocio["id"], "--aceptar-responsabilidad", "v1", "--como", "angie"])
    assert estado["modo_efectivo"] == "activo" and estado["responsabilidad"]["aceptada_por"] == "angie"
    estado = await script.main(["--negocio-id", negocio["id"], "--activo", "0"])
    assert estado["modo_efectivo"] == "apagado"


async def test_el_script_de_medicion_cuenta_por_semana_y_segmento_sin_escribir_ni_exponer_datos(capsys):
    negocio, canal = await _negocio("ls-med")
    await _lead(negocio, canal, "51987000001", horas=30)                              # A
    await _lead(negocio, canal, "51987000002", horas=5)                               # A
    await _lead(negocio, canal, "51987000003", horas=5, guion=[("user", "Hola", 5.1), ("assistant", "Hola", 5.0)], nombre="Ana", producto_tipo="terma", paso=None)   # puntaje 3 → no
    await mem.actualizar_lead("51987000001", campos_explicitos=("resultado",), resultado="sin_respuesta")   # lo cerró el Cron de 15 h
    script = _cargar("medir_candidatos_llamada")
    resultado = await script.medir(negocio["id"], 28, 4.0, 4, 0.0)
    assert resultado["evaluados"] == 3 and sum(c["total"] for c in resultado["semanas"].values()) == 2
    assert sum(c["A"] for c in resultado["semanas"].values()) == 2
    assert resultado["descartados"] == {"puntaje_bajo": 1}
    texto = script.formatear(resultado, 0.0)
    assert "51987" not in texto and "Ana" not in texto
    assert await _tareas() == []                                                    # solo lectura
    assert (await mem.obtener_lead("51987000001", negocio_id=negocio["id"]))["resultado"] == "sin_respuesta"


# ── Migración ────────────────────────────────────────────────────────────────────────────────────

def test_la_migracion_sube_y_baja_en_sqlite_con_la_tabla_el_indice_unico_y_la_columna(tmp_path):
    import sqlalchemy as sa

    base = tmp_path / "mig_llamadas.db"
    entorno = {**os.environ, "DATABASE_URL": f"sqlite+aiosqlite:///{base.as_posix()}"}

    def alembic(*args):
        return subprocess.run(
            [sys.executable, "-m", "alembic", *args], cwd=RAIZ, env=entorno, capture_output=True, text=True, timeout=300, stdin=subprocess.DEVNULL,
        )

    previa = alembic("upgrade", "a7d3b9e2c4f1")
    if previa.returncode != 0:
        pytest.skip(f"la cadena anterior de migraciones no corre sobre SQLite vacía en este entorno: {previa.stderr[-200:]}")
    sube = alembic("upgrade", "head")
    assert sube.returncode == 0, sube.stderr
    motor = sa.create_engine(f"sqlite:///{base.as_posix()}")
    insp = sa.inspect(motor)
    columnas = {c["name"] for c in insp.get_columns("tareas_llamada")}
    assert columnas == {c.name for c in mem.TareaLlamada.__table__.columns}
    assert "no_llamar_en" in {c["name"] for c in insp.get_columns("contacts")}
    indices = {i["name"]: i for i in insp.get_indexes("tareas_llamada")}
    assert indices["ix_tarea_llamada_una_abierta_por_conversation"]["unique"] == 1
    assert {"ix_tareas_llamada_negocio_id", "ix_tareas_llamada_conversation_id", "ix_tareas_llamada_estado", "ix_tareas_llamada_negocio_estado"} <= set(indices)
    with motor.connect() as con:      # el índice parcial deja repetir una conversación solo si la anterior ya está cerrada
        con.execute(sa.text("PRAGMA foreign_keys=OFF"))
        fila = dict(id="a", negocio_id="n", conversation_id="c", contact_id="k", telefono="51900000000", estado="pendiente", segmento="A",
                    puntaje=5, grupo="llamar", modo="sombra", intentos=0, reasignaciones=0, creada_en="2026-10-09 00:00:00")
        insert = sa.text("INSERT INTO tareas_llamada (id,negocio_id,conversation_id,contact_id,telefono,estado,segmento,puntaje,grupo,modo,intentos,reasignaciones,creada_en) "
                         "VALUES (:id,:negocio_id,:conversation_id,:contact_id,:telefono,:estado,:segmento,:puntaje,:grupo,:modo,:intentos,:reasignaciones,:creada_en)")
        con.execute(insert, fila)
        with pytest.raises(sa.exc.IntegrityError):
            con.execute(insert, {**fila, "id": "b"})
        con.rollback()
    motor.dispose()

    baja = alembic("downgrade", "a7d3b9e2c4f1")
    assert baja.returncode == 0, baja.stderr
    motor = sa.create_engine(f"sqlite:///{base.as_posix()}")
    insp = sa.inspect(motor)
    assert "tareas_llamada" not in insp.get_table_names()
    assert "no_llamar_en" not in {c["name"] for c in insp.get_columns("contacts")}
    motor.dispose()
