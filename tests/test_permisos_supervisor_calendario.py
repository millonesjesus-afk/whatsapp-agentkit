# tests/test_permisos_supervisor_calendario.py — Permisos del supervisor sobre el calendario (2026-10-12, D1/D4/D5/D7):
# guardas (día pasado, año no verificado), límite de frecuencia, CSRF, aislamiento entre negocios (IDOR), auditoría con
# `actor_rol`, historial legible, horario semanal en solo lectura y capacidades. Las pruebas "de punta a punta" montan el
# router real del panel en una app mínima (sesión con token CSRF fijo; el usuario de la sesión se inyecta) y llaman por HTTP,
# así que prueban lo que ejecutaría FastAPI en producción. Contrato: docs/contrato_calendario_supervisor.md. Datos sintéticos.

import json
import os
from datetime import datetime, timedelta

os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")
os.environ.setdefault("WHATSAPP_PROVIDER", "meta")

import pytest
from sqlalchemy import select

from agent import dashboard
from agent import memory as mem
from tests._cliente_http import ClienteHttp

RUTA = "/dashboard/configuracion/dias-especiales.json"
HISTORIAL = "/dashboard/configuracion/dias-especiales/historial.json"
HORARIO = "/dashboard/calendario/horario.json"


@pytest.fixture(autouse=True)
def _cache_limpia():
    mem.invalidar_cache_calendario()
    yield
    mem.invalidar_cache_calendario()


def _hoy():
    return mem.hoy_en_lima()


def _iso(dias: int) -> str:
    return (_hoy() + timedelta(days=dias)).isoformat()


async def _negocio(codigo: str):
    return await mem.crear_negocio(f"Negocio {codigo}", codigo)


def _usuario(negocio, username="sup1", rol="supervisor"):
    return {"negocio_id": negocio["id"], "username": username, "rol": rol}


@pytest.fixture
async def cliente():
    c = ClienteHttp()
    yield c
    await c.cerrar()


async def _auditoria(negocio_id, accion=None):
    async with mem.async_session() as session:
        consulta = select(mem.RegistroAuditoria).where(mem.RegistroAuditoria.negocio_id == negocio_id)
        if accion:
            consulta = consulta.where(mem.RegistroAuditoria.accion == accion)
        return list((await session.execute(consulta.order_by(mem.RegistroAuditoria.creado.asc()))).scalars().all())


# ── Capacidades ─────────────────────────────────────────────────────────────

def test_capacidades_de_calendario_por_rol():
    for rol in ("admin", "supervisor"):
        assert {"calendario:ver", "calendario:editar"} <= set(dashboard._capacidades_de(rol))
    assert not {"calendario:ver", "calendario:editar"} & set(dashboard._capacidades_de("asesor"))


def test_el_supervisor_con_calendario_sigue_sin_configuracion():
    capacidades = dashboard._capacidades_de("supervisor")
    assert "configuracion:ver" not in capacidades and "canales.gestionar" not in capacidades
    assert "equipo:administrar" not in capacidades and "usuarios.crear" not in capacidades
    assert "configuracion:ver" in dashboard._capacidades_de("admin")


# ── Roles ───────────────────────────────────────────────────────────────────

async def test_el_asesor_recibe_403_en_todo_el_calendario(cliente):
    asesor = cliente.con(_usuario({"id": "n"}, "ase1", "asesor"))
    assert (await asesor.get(RUTA)).status_code == 403
    assert (await asesor.get(HISTORIAL)).status_code == 403
    assert (await asesor.get(HORARIO)).status_code == 403
    assert (await asesor.post(RUTA, {"fecha": _iso(3), "tipo": "feriado", "nombre": "X"})).status_code == 403
    assert (await asesor.delete(RUTA, fecha=_iso(3))).status_code == 403


async def test_el_supervisor_lee_y_escribe_hacia_adelante(cliente):
    n = await _negocio("ps-1")
    sup = cliente.con(_usuario(n))
    assert (await sup.get(RUTA)).status_code == 200 and (await sup.get(HISTORIAL)).status_code == 200
    r = await sup.post(RUTA, {"fecha": _iso(3), "tipo": "cierre_propio", "nombre": "Inventario"})
    assert r.status_code == 200 and r.json()["resultado"] == "creado"
    assert (await sup.post(RUTA, {"operacion": "marcar_manana_no_laborable"})).status_code == 200
    assert (await sup.delete(RUTA, fecha=_iso(3))).status_code == 200


# ── Guardas del supervisor (D4 y D5) ────────────────────────────────────────

async def test_supervisor_403_al_cambiar_o_quitar_un_dia_pasado_pero_el_admin_si_puede(cliente):
    n = await _negocio("ps-2")
    ayer = _iso(-1)
    admin = cliente.con(_usuario(n, "adm1", "admin"))
    assert (await admin.post(RUTA, {"fecha": ayer, "tipo": "cierre_propio", "nombre": "Cierre", "motivo": "Falla eléctrica"})).status_code == 200
    sup = cliente.con(_usuario(n))
    for cuerpo in (
        {"fecha": ayer, "tipo": "cierre_propio", "nombre": "Otro nombre", "motivo": "Corrección"},       # editar
        {"fecha": ayer, "tipo": "cierre_propio", "nombre": "Nuevo", "motivo": "x"},
        {"fecha": _iso(-30), "tipo": "feriado", "nombre": "Muy viejo", "motivo": "x"},                    # ni con motivo
        {"fecha": _iso(-1), "tipo": "cierre_propio", "nombre": "Sin motivo"},                              # ni sin motivo: 403, no 400
    ):
        r = await sup.post(RUTA, cuerpo)
        assert r.status_code == 403 and "administrador" in r.json()["detail"] and "ya pasó" in r.json()["detail"]
    r = await sup.delete(RUTA, fecha=ayer, motivo="Fue un error")
    assert r.status_code == 403 and "administrador" in r.json()["detail"]
    dias = await mem.listar_dias_especiales(n["id"], _hoy() - timedelta(days=40), _hoy())
    assert [d["nombre"] for d in dias] == ["Cierre"]                                                       # nada cambió
    assert (await admin.post(RUTA, {"fecha": ayer, "tipo": "cierre_propio", "nombre": "Corregido", "motivo": "Corrección"})).status_code == 200
    assert (await admin.delete(RUTA, fecha=ayer, motivo="Fue un error")).status_code == 200


async def test_supervisor_puede_tocar_hoy_y_el_futuro(cliente):
    n = await _negocio("ps-3")
    sup = cliente.con(_usuario(n))
    for dias in (0, 1, 400):
        assert (await sup.post(RUTA, {"fecha": _iso(dias), "tipo": "no_laborable", "nombre": f"Día {dias}"})).status_code == 200
    assert (await sup.delete(RUTA, fecha=_iso(0))).status_code == 200


async def test_una_fecha_mal_escrita_del_supervisor_sigue_dando_400(cliente):
    n = await _negocio("ps-4")
    sup = cliente.con(_usuario(n))
    r = await sup.post(RUTA, {"fecha": "ayer", "tipo": "feriado", "nombre": "X"})
    assert r.status_code == 400 and "AAAA-MM-DD" in r.json()["detail"]
    assert (await sup.delete(RUTA, fecha="ayer")).status_code == 400


async def test_supervisor_403_al_cargar_feriados_de_un_anio_no_verificado_pero_el_admin_si(cliente):
    n = await _negocio("ps-5")
    sup = cliente.con(_usuario(n))
    r = await sup.post(RUTA, {"operacion": "cargar_feriados_peru", "anio": 2027})
    assert r.status_code == 403 and "2027" in r.json()["detail"] and "verificados" in r.json()["detail"]
    assert await mem.listar_dias_especiales(n["id"]) == []                                                 # no se cargó nada
    assert (await sup.post(RUTA, {"operacion": "cargar_feriados_peru", "anio": 2026})).status_code == 200  # el verificado sí
    admin = cliente.con(_usuario(n, "adm1", "admin"))
    r = await admin.post(RUTA, {"operacion": "cargar_feriados_peru", "anio": 2027})
    assert r.status_code == 200 and r.json()["verificado"] is False and len(r.json()["insertados"]) == 16


async def test_un_anio_sin_lista_o_mal_escrito_del_supervisor_da_400_no_403(cliente):
    n = await _negocio("ps-6")
    sup = cliente.con(_usuario(n))
    assert (await sup.post(RUTA, {"operacion": "cargar_feriados_peru", "anio": 2040})).status_code == 400
    assert (await sup.post(RUTA, {"operacion": "cargar_feriados_peru", "anio": "2027"})).status_code == 400
    assert (await sup.post(RUTA, {"operacion": "cargar_feriados_peru"})).status_code == 400


# ── CSRF ────────────────────────────────────────────────────────────────────

async def test_post_y_delete_sin_token_o_con_token_invalido_dan_403(cliente):
    n = await _negocio("ps-7")
    for usuario in (_usuario(n), _usuario(n, "adm1", "admin")):
        c = cliente.con(usuario)
        cuerpo = {"fecha": _iso(5), "tipo": "feriado", "nombre": "X"}
        assert (await c.post(RUTA, cuerpo, token=None)).status_code == 403
        assert (await c.post(RUTA, cuerpo, token="otro-token")).status_code == 403
        assert (await c.delete(RUTA, token=None, fecha=_iso(5))).status_code == 403
        assert (await c.delete(RUTA, token="otro-token", fecha=_iso(5))).status_code == 403
    assert await mem.listar_dias_especiales(n["id"]) == []
    assert await _auditoria(n["id"]) == []


# ── Aislamiento entre negocios (IDOR) ───────────────────────────────────────

async def test_un_supervisor_no_lee_ni_escribe_el_calendario_de_otro_negocio(cliente):
    a, b = await _negocio("ps-a"), await _negocio("ps-b")
    admin_a = cliente.con(_usuario(a, "adm_a", "admin"))
    await admin_a.post(RUTA, {"fecha": _iso(10), "tipo": "cierre_propio", "nombre": "Solo de A"})
    sup_b = cliente.con(_usuario(b, "sup_b"))
    # lectura: ni con `negocio_id` en la query
    assert (await sup_b.get(RUTA, desde=_iso(0), hasta=_iso(30), negocio_id=a["id"])).json()["dias"] == []
    assert (await sup_b.get(HISTORIAL, negocio_id=a["id"])).json()["items"] == []
    # escritura: el `negocio_id` del cuerpo y de la query se ignora
    r = await sup_b.post(RUTA + f"?negocio_id={a['id']}", {"fecha": _iso(11), "tipo": "feriado", "nombre": "De B", "negocio_id": a["id"]})
    assert r.status_code == 200
    assert [d["nombre"] for d in await mem.listar_dias_especiales(a["id"], _hoy())] == ["Solo de A"]
    assert [d["nombre"] for d in await mem.listar_dias_especiales(b["id"], _hoy())] == ["De B"]
    # borrar la fecha de A desde B: 404 (B no tiene ese día) y A conserva el suyo
    assert (await sup_b.delete(RUTA, fecha=_iso(10), negocio_id=a["id"])).status_code == 404
    assert len(await mem.listar_dias_especiales(a["id"], _hoy())) == 1
    # la auditoría de B quedó en B
    assert len(await _auditoria(b["id"])) == 1 and len(await _auditoria(a["id"])) == 1


async def test_el_horario_y_el_historial_son_del_negocio_de_la_sesion(cliente):
    a, b = await _negocio("ps-c"), await _negocio("ps-d")
    await mem.guardar_horario_atencion(a["id"], 0, True, "09:00", "13:00")
    await mem.guardar_horario_atencion(b["id"], 0, True, "07:00", "21:00")
    horario_b = (await cliente.con(_usuario(b)).get(HORARIO, negocio_id=a["id"])).json()
    assert horario_b["dias"][0]["hora_apertura"] == "07:00" and horario_b["dias"][0]["hora_cierre"] == "21:00"
    horario_a = (await cliente.con(_usuario(a)).get(HORARIO)).json()
    assert horario_a["dias"][0]["hora_apertura"] == "09:00"


# ── Horario semanal en solo lectura ─────────────────────────────────────────

async def test_horario_json_trae_la_semana_y_el_estado_actual(cliente):
    n = await _negocio("ps-h1")
    await mem.guardar_horario_atencion(n["id"], 0, True, "08:00", "19:00")
    await mem.guardar_horario_atencion(n["id"], 6, False, None, None)
    for rol in ("supervisor", "admin"):
        r = await cliente.con(_usuario(n, "u", rol)).get(HORARIO)
        assert r.status_code == 200
        cuerpo = r.json()
        assert set(cuerpo) == {"hoy", "solo_lectura", "dias", "estado_actual"} and cuerpo["solo_lectura"] is True
        assert cuerpo["hoy"] == _hoy().isoformat() and [d["dia_semana"] for d in cuerpo["dias"]] == list(range(7))
        assert set(cuerpo["dias"][0]) == {"dia_semana", "nombre", "habilitado", "hora_apertura", "hora_cierre", "es_por_defecto"}
        lunes, martes, domingo = cuerpo["dias"][0], cuerpo["dias"][1], cuerpo["dias"][6]
        assert lunes["nombre"] == "lunes" and lunes["habilitado"] is True and lunes["es_por_defecto"] is False
        assert (lunes["hora_apertura"], lunes["hora_cierre"]) == ("08:00", "19:00")
        assert martes["es_por_defecto"] is True and martes["habilitado"] is True                      # sin fila: horario de siempre
        assert domingo["habilitado"] is False and domingo["hora_apertura"] is None and domingo["es_por_defecto"] is False
        assert set(cuerpo["estado_actual"]) == {"abierto", "motivo", "nombre", "proxima_apertura", "proxima_apertura_texto"}


async def test_el_supervisor_no_puede_escribir_el_horario_semanal(cliente):
    n = await _negocio("ps-h2")
    sup = cliente.con(_usuario(n))
    r = await sup.post("/dashboard/configuracion/horario", {"dia_semana": 0, "habilitado": True, "hora_apertura": "01:00", "hora_cierre": "02:00"})
    assert r.status_code == 403
    assert await mem.listar_horarios_atencion(n["id"]) == []


# ── Límite de frecuencia (D7) ───────────────────────────────────────────────

async def test_la_escritura_21_del_supervisor_en_una_hora_da_429(cliente):
    n = await _negocio("ps-l1")
    sup = cliente.con(_usuario(n))
    for i in range(20):                                                                 # el límite por defecto es 20
        r = await sup.post(RUTA, {"fecha": _iso(2 + i), "tipo": "cierre_propio", "nombre": f"Cierre {i}"})
        assert r.status_code == 200, (i, r.text)
    r = await sup.post(RUTA, {"fecha": _iso(40), "tipo": "cierre_propio", "nombre": "Una más"})
    assert r.status_code == 429 and "20 cambios" in r.json()["detail"] and "en la última hora" in r.json()["detail"]
    assert 1 <= int(r.headers["retry-after"]) <= 3600
    assert (await sup.delete(RUTA, fecha=_iso(2))).status_code == 429
    assert (await sup.post(RUTA, {"operacion": "marcar_manana_no_laborable"})).status_code == 429
    assert (await sup.get(RUTA)).status_code == 200                                     # leer nunca se limita
    assert len(await mem.listar_dias_especiales(n["id"], _hoy())) == 20
    # el límite es POR USUARIO y por negocio: otro supervisor del mismo negocio y otro negocio siguen escribiendo
    assert (await cliente.con(_usuario(n, "sup2")).post(RUTA, {"fecha": _iso(50), "tipo": "feriado", "nombre": "Otro"})).status_code == 200
    otro = await _negocio("ps-l2")
    assert (await cliente.con(_usuario(otro)).post(RUTA, {"fecha": _iso(50), "tipo": "feriado", "nombre": "Otro"})).status_code == 200


async def test_el_limite_es_una_ventana_deslizante_de_una_hora(cliente):
    n = await _negocio("ps-l3")
    await mem.guardar_configuracion(mem.CLAVE_CALENDARIO_MAX_ESCRITURAS_HORA, "2", negocio_id=n["id"])
    sup = cliente.con(_usuario(n))
    for i in range(2):
        assert (await sup.post(RUTA, {"fecha": _iso(3 + i), "tipo": "feriado", "nombre": f"F{i}"})).status_code == 200
    assert (await sup.post(RUTA, {"fecha": _iso(9), "tipo": "feriado", "nombre": "F"})).status_code == 429
    # una escritura de hace más de una hora sale de la ventana
    async with mem.async_session() as session:
        filas = (await session.execute(select(mem.RegistroAuditoria).where(mem.RegistroAuditoria.negocio_id == n["id"]))).scalars().all()
        filas[0].creado = datetime.utcnow() - timedelta(minutes=61)
        await session.commit()
    assert (await sup.post(RUTA, {"fecha": _iso(9), "tipo": "feriado", "nombre": "F"})).status_code == 200


async def test_el_admin_tiene_su_propio_tope_mas_alto_y_un_valor_invalido_usa_el_defecto(cliente):
    n = await _negocio("ps-l4")
    await mem.guardar_configuracion(mem.CLAVE_CALENDARIO_MAX_ESCRITURAS_HORA, "no-es-numero", negocio_id=n["id"])
    await mem.guardar_configuracion(mem.CLAVE_CALENDARIO_MAX_ESCRITURAS_HORA_ADMIN, "21", negocio_id=n["id"])
    admin = cliente.con(_usuario(n, "adm1", "admin"))
    for i in range(21):                                                                 # pasa de 20: el admin tiene tope propio
        assert (await admin.post(RUTA, {"fecha": _iso(2 + i), "tipo": "cierre_propio", "nombre": f"C{i}"})).status_code == 200
    r = await admin.post(RUTA, {"fecha": _iso(40), "tipo": "cierre_propio", "nombre": "Una más"})
    assert r.status_code == 429 and "21 cambios" in r.json()["detail"]
    sup = cliente.con(_usuario(n))                                                      # valor inválido → defecto 20 para el supervisor
    assert (await sup.post(RUTA, {"fecha": _iso(41), "tipo": "feriado", "nombre": "F"})).status_code == 200


async def test_lo_que_no_escribe_no_cuenta_para_el_limite(cliente):
    n = await _negocio("ps-l5")
    await mem.guardar_configuracion(mem.CLAVE_CALENDARIO_MAX_ESCRITURAS_HORA, "2", negocio_id=n["id"])
    sup = cliente.con(_usuario(n))
    cuerpo = {"fecha": _iso(3), "tipo": "feriado", "nombre": "F"}
    assert (await sup.post(RUTA, cuerpo)).status_code == 200
    for _ in range(5):
        assert (await sup.post(RUTA, cuerpo)).json()["resultado"] == "sin_cambios"        # sin cambios: no escribe
        assert (await sup.post(RUTA, {"fecha": "mal", "tipo": "feriado", "nombre": "F"})).status_code == 400
        assert (await sup.delete(RUTA, fecha=_iso(200))).status_code == 404
    assert (await sup.post(RUTA, {"fecha": _iso(4), "tipo": "feriado", "nombre": "G"})).status_code == 200


# ── Auditoría con actor_rol ─────────────────────────────────────────────────

async def test_cada_escritura_deja_auditoria_con_actor_y_actor_rol(cliente):
    n = await _negocio("ps-au")
    sup, admin = cliente.con(_usuario(n, "sup1")), None
    await sup.post(RUTA, {"fecha": _iso(5), "tipo": "cierre_propio", "nombre": "Inventario"})                       # alta
    await sup.post(RUTA, {"fecha": _iso(5), "tipo": "cierre_propio", "nombre": "Inventario general"})                # cambio
    await sup.delete(RUTA, fecha=_iso(5), motivo="Se canceló")                                                       # baja
    await sup.post(RUTA, {"operacion": "marcar_manana_no_laborable"})                                                # atajo
    await sup.post(RUTA, {"operacion": "cargar_feriados_peru", "anio": 2026})                                        # carga
    admin = cliente.con(_usuario(n, "adm1", "admin"))
    await admin.post(RUTA, {"operacion": "cargar_feriados_peru", "anio": 2027})
    filas = await _auditoria(n["id"])
    assert [f.accion for f in filas] == [
        "dia_especial_creado", "dia_especial_modificado", "dia_especial_eliminado", "dia_especial_creado",
        "calendario_feriados_cargados", "calendario_feriados_cargados",
    ]
    assert [(f.actor, f.payload["actor_rol"]) for f in filas] == [("sup1", "supervisor")] * 5 + [("adm1", "admin")]
    assert filas[2].payload["motivo"] == "Se canceló"


async def test_fijar_la_vigencia_habil_deja_actor_rol_y_los_lectores_viejos_siguen_igual():
    n = await _negocio("ps-hd")
    await mem.fijar_calendario_habil_desde(n["id"], _hoy(), autor="adm1", autor_rol="admin")
    await mem.fijar_calendario_habil_desde(n["id"], None, autor="script:x")             # sin rol: queda None, no rompe
    filas = await _auditoria(n["id"], "calendario_habil_desde")
    assert filas[0].payload == {"antes": None, "despues": _hoy().isoformat(), "actor_rol": "admin"}
    assert filas[1].payload["actor_rol"] is None and filas[1].payload["antes"] == _hoy().isoformat()


# ── Historial legible ───────────────────────────────────────────────────────

async def test_el_historial_devuelve_las_filas_legibles_mas_reciente_primero(cliente):
    n = await _negocio("ps-hi")
    sup = cliente.con(_usuario(n, "sup1"))
    await sup.post(RUTA, {"fecha": _iso(5), "tipo": "cierre_propio", "nombre": "Inventario"})
    await sup.post(RUTA, {"fecha": _iso(5), "tipo": "cierre_propio", "nombre": "Inventario general", "atiende": False})
    await sup.delete(RUTA, fecha=_iso(5), motivo="Se canceló")
    admin = cliente.con(_usuario(n, "adm1", "admin"))
    await admin.post(RUTA, {"operacion": "cargar_feriados_peru", "anio": 2026})
    await mem.fijar_calendario_habil_desde(n["id"], _hoy(), autor="adm1", autor_rol="admin")
    r = await cliente.con(_usuario(n, "sup9")).get(HISTORIAL)
    cuerpo = r.json()
    assert r.status_code == 200 and set(cuerpo) == {"items", "hay_mas"} and cuerpo["hay_mas"] is False
    assert [i["accion"] for i in cuerpo["items"]] == [
        "calendario_habil_desde", "calendario_feriados_cargados", "dia_especial_eliminado", "dia_especial_modificado", "dia_especial_creado",
    ]
    for item in cuerpo["items"]:
        assert set(item) == {"fecha_hora", "actor", "actor_rol", "accion", "fecha_dia", "antes", "despues", "motivo"}
        assert item["fecha_hora"].endswith("Z")
    habil, feriados, baja, cambio, alta = cuerpo["items"]
    assert (habil["actor"], habil["actor_rol"], habil["antes"], habil["despues"]) == ("adm1", "admin", None, _hoy().isoformat())
    assert habil["fecha_dia"] is None
    assert feriados["despues"]["anio"] == 2026 and len(feriados["despues"]["insertados"]) == 16 and feriados["despues"]["verificado"] is True
    assert feriados["antes"] is None and feriados["fecha_dia"] is None
    assert (baja["actor"], baja["actor_rol"], baja["fecha_dia"], baja["motivo"]) == ("sup1", "supervisor", _iso(5), "Se canceló")
    assert baja["antes"]["nombre"] == "Inventario general" and baja["despues"] is None
    assert cambio["antes"]["nombre"] == "Inventario" and cambio["despues"]["nombre"] == "Inventario general"
    assert alta["antes"] is None and alta["despues"] == {
        "fecha": _iso(5), "tipo": "cierre_propio", "nombre": "Inventario", "atiende": False, "hora_apertura": None, "hora_cierre": None,
    }


async def test_el_historial_pagina_y_valida_sus_parametros(cliente):
    n = await _negocio("ps-hp")
    sup = cliente.con(_usuario(n))
    for i in range(5):
        await sup.post(RUTA, {"fecha": _iso(3 + i), "tipo": "feriado", "nombre": f"F{i}"})
    pagina1 = (await sup.get(HISTORIAL, limite=2)).json()
    assert [i["despues"]["nombre"] for i in pagina1["items"]] == ["F4", "F3"] and pagina1["hay_mas"] is True
    pagina2 = (await sup.get(HISTORIAL, limite=2, antes_de=pagina1["items"][-1]["fecha_hora"])).json()
    assert [i["despues"]["nombre"] for i in pagina2["items"]] == ["F2", "F1"] and pagina2["hay_mas"] is True
    pagina3 = (await sup.get(HISTORIAL, limite=2, antes_de=pagina2["items"][-1]["fecha_hora"])).json()
    assert [i["despues"]["nombre"] for i in pagina3["items"]] == ["F0"] and pagina3["hay_mas"] is False
    assert len((await sup.get(HISTORIAL)).json()["items"]) == 5                         # por defecto 100
    for malo in (0, 201, -1):
        assert (await sup.get(HISTORIAL, limite=malo)).status_code == 400
    r = await sup.get(HISTORIAL, antes_de="ayer")
    assert r.status_code == 400 and "ISO" in r.json()["detail"]


async def test_filas_viejas_sin_actor_rol_se_listan_con_actor_rol_nulo(cliente):
    n = await _negocio("ps-vi")
    await mem.registrar_auditoria(
        "dia_especial_creado", actor="adm0", negocio_id=n["id"], entidad_tipo="dia_especial", entidad_id="x",
        payload={"despues": {"fecha": "2026-11-20", "tipo": "feriado", "nombre": "Viejo", "atiende": False,
                              "hora_apertura": None, "hora_cierre": None}, "origen": "manual", "motivo": None},
    )
    item = (await cliente.con(_usuario(n)).get(HISTORIAL)).json()["items"][0]
    assert item["actor"] == "adm0" and item["actor_rol"] is None and item["fecha_dia"] == "2026-11-20"


async def test_el_historial_de_configuracion_del_admin_incluye_el_calendario(cliente):
    n = await _negocio("ps-hc")
    sup = cliente.con(_usuario(n, "sup1"))
    await sup.post(RUTA, {"fecha": _iso(5), "tipo": "atencion_especial", "nombre": "Cierre temprano", "atiende": True,
                          "hora_apertura": "08:00", "hora_cierre": "12:00"})
    await sup.post(RUTA, {"fecha": _iso(5), "tipo": "atencion_especial", "nombre": "Cierre temprano", "atiende": True,
                          "hora_apertura": "08:00", "hora_cierre": "13:00"})
    await sup.delete(RUTA, fecha=_iso(5), motivo="Se canceló")
    admin = cliente.con(_usuario(n, "adm1", "admin"))
    await admin.post(RUTA, {"operacion": "cargar_feriados_peru", "anio": 2026})
    await mem.fijar_calendario_habil_desde(n["id"], _hoy(), autor="adm1", autor_rol="admin")
    await mem.registrar_auditoria(                                                       # una fila de configuración de siempre
        "uso_meta_configuracion", actor="adm1", negocio_id=n["id"], entidad_tipo="configuracion",
        payload={"cambios": {"envios_tope_mensual_usd": {"antes": "0", "despues": "50"}}, "riesgo_confirmado": False},
    )
    r = await admin.get("/dashboard/uso-mensajes/historial-cambios.json")
    assert r.status_code == 200
    cambios = r.json()["cambios"]
    assert [c["accion"] for c in cambios] == [
        "uso_meta_configuracion", "calendario_habil_desde", "calendario_feriados_cargados", "dia_especial_eliminado",
        "dia_especial_modificado", "dia_especial_creado",
    ]
    assert cambios[0]["cambios"] == {"envios_tope_mensual_usd": {"antes": "0", "despues": "50"}}
    assert cambios[1]["cambios"] == {"calendario_habil_desde": {"antes": None, "despues": _hoy().isoformat()}}
    feriados = cambios[2]["cambios"]["calendario_feriados_cargados"]
    assert feriados["antes"] is None and json.loads(feriados["despues"])["anio"] == 2026 and len(json.loads(feriados["despues"])["insertados"]) == 16
    baja = cambios[3]["cambios"]["dia_especial_eliminado"]
    assert baja["despues"] is None and json.loads(baja["antes"])["motivo"] == "Se canceló" and json.loads(baja["antes"])["nombre"] == "Cierre temprano"
    cambio = cambios[4]["cambios"]["dia_especial_modificado"]
    assert json.loads(cambio["antes"])["hora_cierre"] == "12:00" and json.loads(cambio["despues"])["hora_cierre"] == "13:00"
    alta = cambios[5]["cambios"]["dia_especial_creado"]
    assert alta["antes"] is None and json.loads(alta["despues"])["tipo"] == "atencion_especial" and json.loads(alta["despues"])["motivo"] is None
    assert cambios[5]["actor"] == "sup1" and cambios[5]["riesgo_confirmado"] is False
    # …y el supervisor no lee el historial de Configuración
    assert (await cliente.con(_usuario(n)).get("/dashboard/uso-mensajes/historial-cambios.json")).status_code == 403


# ── Aviso al admin (Fase 2) ─────────────────────────────────────────────────

ID_AVISO = "calendario_cambios_supervisor"


async def _avisos(n, rol, username="x"):
    return await dashboard._avisos_inicio(_usuario(n, username, rol))


async def test_el_aviso_es_solo_para_el_admin_y_cuenta_solo_cambios_de_supervisores(cliente):
    n = await _negocio("ps-av1")
    otro = await _negocio("ps-av2")
    assert [a for a in await _avisos(n, "admin") if a["id"] == ID_AVISO] == []              # sin cambios: sin aviso
    sup = cliente.con(_usuario(n, "ana"))
    for i in range(3):
        await sup.post(RUTA, {"fecha": _iso(3 + i), "tipo": "feriado", "nombre": f"F{i}"})
    await cliente.con(_usuario(n, "adm1", "admin")).post(RUTA, {"fecha": _iso(20), "tipo": "feriado", "nombre": "Del admin"})
    await cliente.con(_usuario(otro, "sup_otro")).post(RUTA, {"fecha": _iso(3), "tipo": "feriado", "nombre": "Otro negocio"})
    avisos = [a for a in await _avisos(n, "admin") if a["id"] == ID_AVISO]
    assert len(avisos) == 1
    assert avisos[0] == {
        "id": ID_AVISO, "nivel": "info", "titulo": "El supervisor ana cambió el calendario: 3 cambios en 24 h",
        "detalle": avisos[0]["detalle"], "enlace": "/calendario#historial",
    }
    for rol in ("supervisor", "asesor"):
        assert [a for a in await _avisos(n, rol, "ana") if a["id"] == ID_AVISO] == []
    assert [a for a in await _avisos(otro, "admin") if a["id"] == ID_AVISO][0]["titulo"].startswith("El supervisor sup_otro cambió el calendario: 1 cambio ")


async def test_el_aviso_usa_la_ventana_de_24_horas_y_nombra_a_varios_supervisores(cliente):
    n = await _negocio("ps-av3")
    for usuario in ("ana", "ana", "beto"):
        await cliente.con(_usuario(n, usuario)).post(RUTA, {"fecha": _iso(3 + len(await _auditoria(n["id"]))), "tipo": "feriado", "nombre": "F"})
    titulo = [a for a in await _avisos(n, "admin") if a["id"] == ID_AVISO][0]["titulo"]
    assert titulo == "Los supervisores ana y beto cambiaron el calendario: 3 cambios en 24 h"
    async with mem.async_session() as session:                                              # dos de las filas pasan de 24 h
        filas = (await session.execute(select(mem.RegistroAuditoria).where(mem.RegistroAuditoria.negocio_id == n["id"]).order_by(mem.RegistroAuditoria.creado.asc()))).scalars().all()
        for f in filas[:2]:
            f.creado = datetime.utcnow() - timedelta(hours=25)
        await session.commit()
    titulo = [a for a in await _avisos(n, "admin") if a["id"] == ID_AVISO][0]["titulo"]
    assert titulo == "El supervisor beto cambió el calendario: 1 cambio en 24 h"
    async with mem.async_session() as session:
        for f in (await session.execute(select(mem.RegistroAuditoria).where(mem.RegistroAuditoria.negocio_id == n["id"]))).scalars().all():
            f.creado = datetime.utcnow() - timedelta(hours=25)
        await session.commit()
    assert [a for a in await _avisos(n, "admin") if a["id"] == ID_AVISO] == []


async def test_las_filas_sin_actor_rol_no_cuentan_como_cambios_de_supervisor():
    n = await _negocio("ps-av4")
    await mem.registrar_auditoria("dia_especial_creado", actor="ana", negocio_id=n["id"], entidad_tipo="dia_especial", payload={"despues": {}})
    assert [a for a in await _avisos(n, "admin") if a["id"] == ID_AVISO] == []


async def test_inicio_json_trae_el_aviso_solo_al_admin(cliente):
    n = await _negocio("ps-av5")
    await cliente.con(_usuario(n, "ana")).post(RUTA, {"fecha": _iso(3), "tipo": "feriado", "nombre": "F"})
    admin = json.loads((await dashboard.inicio_json(usuario=_usuario(n, "adm1", "admin"))).body)
    assert [a["id"] for a in admin["avisos"]].count(ID_AVISO) == 1
    sup = json.loads((await dashboard.inicio_json(usuario=_usuario(n, "ana"))).body)
    assert ID_AVISO not in [a["id"] for a in sup["avisos"]]
    assert {"vision_total", "zona_accion", "zona_indicadores", "avisos"} == set(admin)       # el contrato de Inicio no cambia


def test_el_contrato_del_supervisor_documenta_los_endpoints_las_guardas_y_el_aviso():
    from pathlib import Path
    doc = (Path(__file__).resolve().parent.parent / "docs" / "contrato_calendario_supervisor.md").read_text(encoding="utf-8")
    for fragmento in (
        HORARIO, HISTORIAL, "calendario:ver", "calendario:editar", "configuracion:ver", "429", "Retry-After", "403",
        "calendario_max_escrituras_hora", "calendario_cambios_supervisor", "actor_rol", "leads_exportados", "medicion",
    ):
        assert fragmento in doc, fragmento
