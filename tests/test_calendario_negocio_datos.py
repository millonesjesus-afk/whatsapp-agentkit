# tests/test_calendario_negocio_datos.py — Calendario de negocio, Fase 1 (2026-10-12): tabla `dias_especiales`, siembra
# de feriados, CRUD con auditoría, edición retroactiva, caché de 60 s, aislamiento multi-tenant, vigencia de las métricas
# hábiles y la migración. Datos sintéticos únicamente.

import os
import subprocess
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest
import sqlalchemy as sa
from sqlalchemy import select

from agent import calendario_negocio as cn
from agent import memory as mem

RAIZ = Path(__file__).resolve().parent.parent
HOY = date(2026, 10, 12)      # lunes


@pytest.fixture(autouse=True)
def _cache_limpia():
    mem.invalidar_cache_calendario()
    yield
    mem.invalidar_cache_calendario()


async def _negocio(codigo: str):
    return await mem.crear_negocio(f"Negocio {codigo}", codigo)


async def _vivos(negocio_id: str) -> list[dict]:
    return await mem.listar_dias_especiales(negocio_id)


async def _auditoria(negocio_id: str, accion: str | None = None) -> list:
    async with mem.async_session() as session:
        q = select(mem.RegistroAuditoria).where(mem.RegistroAuditoria.negocio_id == negocio_id)
        if accion:
            q = q.where(mem.RegistroAuditoria.accion == accion)
        return list((await session.execute(q.order_by(mem.RegistroAuditoria.creado.asc()))).scalars().all())


# ── Siembra de feriados ─────────────────────────────────────────────────────

async def test_sembrar_calendario_inserta_los_feriados_2026_solo_como_feriado_cerrado():
    n = await _negocio("cal-s1")
    r = await mem.sembrar_calendario(n["id"], 2026, autor="admin1")
    assert len(r["insertados"]) == 16 and r["ya_existian"] == [] and r["verificado"] is True and r["nota"] is None
    filas = await _vivos(n["id"])
    assert len(filas) == 16
    assert {f["tipo"] for f in filas} == {"feriado"} and {f["atiende"] for f in filas} == {False}
    assert {f["origen"] for f in filas} == {"precargado_pe"} and all(f["fuente_url"] for f in filas)
    assert all(f["creado_por"] == "admin1" for f in filas)
    angamos = next(f for f in filas if f["fecha"] == date(2026, 10, 8))
    assert angamos["nombre"] == "Combate de Angamos"
    # ningún no_laborable ni puente
    assert not [f for f in filas if f["tipo"] in ("no_laborable", "puente")]


async def test_sembrar_calendario_es_idempotente():
    n = await _negocio("cal-s2")
    await mem.sembrar_calendario(n["id"], 2026)
    r = await mem.sembrar_calendario(n["id"], 2026)
    assert r["insertados"] == [] and len(r["ya_existian"]) == 16
    assert len(await _vivos(n["id"])) == 16
    # una sola fila de auditoría de carga (la segunda corrida no inserta nada)
    assert len(await _auditoria(n["id"], "calendario_feriados_cargados")) == 1


async def test_sembrar_2027_avisa_que_no_esta_verificado():
    n = await _negocio("cal-s3")
    r = await mem.sembrar_calendario(n["id"], 2027)
    assert len(r["insertados"]) == 16 and r["verificado"] is False and "no verificado" in r["nota"]


async def test_sembrar_un_anio_sin_lista_falla_con_un_mensaje_claro():
    n = await _negocio("cal-s4")
    with pytest.raises(ValueError, match="No hay feriados precargados"):
        await mem.sembrar_calendario(n["id"], 2035)


async def test_simular_no_escribe_nada():
    n = await _negocio("cal-s5")
    r = await mem.sembrar_calendario(n["id"], 2026, simular=True)
    assert len(r["insertados"]) == 16
    assert await _vivos(n["id"]) == [] and await _auditoria(n["id"]) == []


async def test_la_siembra_respeta_lo_que_el_administrador_quito_salvo_que_se_pida_restaurar():
    n = await _negocio("cal-s6")
    await mem.sembrar_calendario(n["id"], 2026)
    await mem.eliminar_dia_especial(n["id"], date(2026, 12, 8), autor="admin1", hoy=HOY)
    r = await mem.sembrar_calendario(n["id"], 2026)
    assert r["insertados"] == [] and r["omitidos_por_eliminados"] == [date(2026, 12, 8)]
    assert date(2026, 12, 8) not in {f["fecha"] for f in await _vivos(n["id"])}
    r = await mem.sembrar_calendario(n["id"], 2026, restaurar_eliminados=True)
    assert r["insertados"] == [date(2026, 12, 8)]
    assert date(2026, 12, 8) in {f["fecha"] for f in await _vivos(n["id"])}


async def test_la_siembra_no_pisa_un_dia_que_el_administrador_ya_cargo_a_mano():
    n = await _negocio("cal-s7")
    await mem.guardar_dia_especial(n["id"], date(2026, 12, 8), "feriado", "Feriado con atención", True, "09:00", "13:00", autor="admin1", hoy=HOY)
    r = await mem.sembrar_calendario(n["id"], 2026)
    assert date(2026, 12, 8) in r["ya_existian"] and len(r["insertados"]) == 15
    dia = next(f for f in await _vivos(n["id"]) if f["fecha"] == date(2026, 12, 8))
    assert dia["atiende"] is True and dia["hora_apertura"] == "09:00" and dia["origen"] == "manual"


# ── Aislamiento multi-tenant ────────────────────────────────────────────────

async def test_los_dias_especiales_son_de_cada_negocio():
    a, b = await _negocio("cal-m1"), await _negocio("cal-m2")
    await mem.sembrar_calendario(a["id"], 2026)
    await mem.guardar_dia_especial(b["id"], date(2026, 11, 20), "cierre_propio", "Inventario", False, autor="admin_b", hoy=HOY)
    assert len(await _vivos(a["id"])) == 16 and [d["fecha"] for d in await _vivos(b["id"])] == [date(2026, 11, 20)]
    # el calendario de A no ve el cierre de B ni al revés
    cal_a, cal_b = await mem.obtener_calendario_negocio(a["id"]), await mem.obtener_calendario_negocio(b["id"])
    assert date(2026, 11, 20) not in cal_a.excepciones and date(2026, 10, 8) not in cal_b.excepciones
    # quitar el día de A no toca el mismo día de B
    await mem.guardar_dia_especial(b["id"], date(2026, 12, 8), "feriado", "Feriado propio", False, autor="admin_b", hoy=HOY)
    await mem.eliminar_dia_especial(a["id"], date(2026, 12, 8), autor="admin_a", hoy=HOY)
    assert date(2026, 12, 8) in {d["fecha"] for d in await _vivos(b["id"])}
    # y un negocio no puede quitar el día de otro
    assert await mem.eliminar_dia_especial(a["id"], date(2026, 11, 20), autor="admin_a", hoy=HOY) is None
    assert date(2026, 11, 20) in {d["fecha"] for d in await _vivos(b["id"])}


async def test_negocio_sin_dias_especiales_o_sin_negocio_conserva_el_horario_de_siempre():
    n = await _negocio("cal-m3")
    assert (await mem.obtener_calendario_negocio(n["id"])).excepciones == {}
    cal = await mem.obtener_calendario_negocio(None)
    assert cn.rangos_de_semana(cal) == {d: ("08:00", "19:00") for d in range(6)} | {6: None}


# ── Validación ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize("campos,mensaje", [
    (dict(fecha="2026-13-40", tipo="feriado", nombre="X"), "AAAA-MM-DD"),
    (dict(fecha="2026-12-08", tipo="vacaciones", nombre="X"), "tipo"),
    (dict(fecha="2026-12-08", tipo="feriado", nombre="   "), "nombre"),
    (dict(fecha="2026-12-08", tipo="feriado", nombre="X" * 101), "100"),
    (dict(fecha="2026-12-08", tipo="feriado", nombre="X", atiende="si"), "true o false"),
    (dict(fecha="2026-12-08", tipo="feriado", nombre="X", atiende=True, hora_apertura="09:00"), "apertura y la de cierre"),
    (dict(fecha="2026-12-08", tipo="feriado", nombre="X", atiende=True, hora_apertura="9am", hora_cierre="13:00"), "HH:MM"),
    (dict(fecha="2026-12-08", tipo="feriado", nombre="X", atiende=True, hora_apertura="13:00", hora_cierre="09:00"), "anterior"),
    (dict(fecha="2026-12-08", tipo="atencion_especial", nombre="X"), "atención especial"),
    (dict(fecha="1999-01-01", tipo="feriado", nombre="X"), "2020 y 2100"),
])
def test_validar_dia_especial_rechaza_lo_invalido(campos, mensaje):
    with pytest.raises(ValueError, match=mensaje):
        mem.validar_dia_especial(**campos)


def test_el_valor_por_defecto_de_atiende_depende_del_tipo():
    def atiende(tipo):
        return mem.validar_dia_especial("2026-12-08", tipo, "X", None, None, None)["atiende"]
    # el feriado y el cierre propio cierran; el no laborable y el puente son voluntarios: siguen atendiendo salvo que se marque
    assert atiende("feriado") is False and atiende("cierre_propio") is False
    assert atiende("no_laborable") is True and atiende("puente") is True


def test_un_dia_cerrado_ignora_las_horas_y_un_feriado_puede_atender_con_horario_especial():
    cerrado = mem.validar_dia_especial("2026-12-08", "feriado", "X", False, "09:00", "13:00")
    assert cerrado["hora_apertura"] is None and cerrado["hora_cierre"] is None
    abierto = mem.validar_dia_especial("2026-12-08", "feriado", " Feriado   con atención ", True, "09:00", "13:00")
    assert abierto["atiende"] is True and abierto["hora_cierre"] == "13:00" and abierto["nombre"] == "Feriado con atención"


# ── CRUD y auditoría ────────────────────────────────────────────────────────

async def test_alta_cambio_y_baja_dejan_auditoria_con_quien_cuando_antes_y_despues():
    n = await _negocio("cal-a1")
    r = await mem.guardar_dia_especial(n["id"], "2026-11-20", "no_laborable", "Día no laborable", False, autor="sup1", hoy=HOY)
    assert r["accion"] == "creado" and r["dia"]["atiende"] is False and r["dia"]["creado_por"] == "sup1"
    r = await mem.guardar_dia_especial(n["id"], "2026-11-20", "no_laborable", "Día no laborable", True, "10:00", "14:00", autor="admin1", hoy=HOY)
    assert r["accion"] == "modificado" and r["dia"]["hora_apertura"] == "10:00"
    r = await mem.guardar_dia_especial(n["id"], "2026-11-20", "no_laborable", "Día no laborable", True, "10:00", "14:00", autor="admin1", hoy=HOY)
    assert r["accion"] == "sin_cambios"
    quitado = await mem.eliminar_dia_especial(n["id"], "2026-11-20", autor="admin1", hoy=HOY)
    assert quitado["eliminado_en"] is not None and await _vivos(n["id"]) == []

    filas = await _auditoria(n["id"])
    assert [f.accion for f in filas] == ["dia_especial_creado", "dia_especial_modificado", "dia_especial_eliminado"]
    assert [f.actor for f in filas] == ["sup1", "admin1", "admin1"]
    assert all(f.entidad_tipo == "dia_especial" and f.creado is not None for f in filas)
    modificado = filas[1].payload
    assert modificado["antes"]["atiende"] is False and modificado["despues"]["atiende"] is True
    assert modificado["despues"]["hora_apertura"] == "10:00" and modificado["antes"]["fecha"] == "2026-11-20"
    assert filas[2].payload["antes"]["hora_cierre"] == "14:00"


async def test_una_sola_fila_viva_por_fecha_y_el_indice_parcial_lo_garantiza():
    n = await _negocio("cal-a2")
    await mem.guardar_dia_especial(n["id"], "2026-11-20", "cierre_propio", "Inventario", False, autor="a", hoy=HOY)
    await mem.guardar_dia_especial(n["id"], "2026-11-20", "cierre_propio", "Inventario anual", False, autor="a", hoy=HOY)
    assert len(await _vivos(n["id"])) == 1                                  # cambió el existente, no agregó otro
    async with mem.async_session() as session:                              # la base misma rechaza un segundo vivo
        session.add(mem.DiaEspecial(negocio_id=n["id"], fecha=date(2026, 11, 20), tipo="feriado", nombre="Dup", atiende=False))
        with pytest.raises(sa.exc.IntegrityError):
            await session.commit()
    await mem.eliminar_dia_especial(n["id"], "2026-11-20", autor="a", hoy=HOY)
    await mem.guardar_dia_especial(n["id"], "2026-11-20", "feriado", "Otra vez", False, autor="a", hoy=HOY)    # el eliminado no cuenta
    assert [d["nombre"] for d in await _vivos(n["id"])] == ["Otra vez"]
    assert len(await mem.listar_dias_especiales(n["id"], incluir_eliminados=True)) == 2


async def test_quitar_un_dia_que_no_existe_devuelve_none():
    n = await _negocio("cal-a3")
    assert await mem.eliminar_dia_especial(n["id"], "2026-11-20", autor="a", hoy=HOY) is None


async def test_listar_filtra_por_rango_y_ordena_por_fecha():
    n = await _negocio("cal-a4")
    for d in ("2026-12-25", "2026-11-20", "2026-12-08"):
        await mem.guardar_dia_especial(n["id"], d, "feriado", f"F {d}", False, autor="a", hoy=HOY)
    assert [x["fecha"].isoformat() for x in await mem.listar_dias_especiales(n["id"])] == ["2026-11-20", "2026-12-08", "2026-12-25"]
    assert [x["fecha"].isoformat() for x in await mem.listar_dias_especiales(n["id"], date(2026, 12, 1), date(2026, 12, 10))] == ["2026-12-08"]


# ── Edición retroactiva ─────────────────────────────────────────────────────

async def test_un_dia_de_hace_mas_de_7_dias_no_se_puede_tocar():
    n = await _negocio("cal-r1")
    vieja = HOY - timedelta(days=8)
    with pytest.raises(ValueError, match="más de 7 días"):
        await mem.guardar_dia_especial(n["id"], vieja, "feriado", "X", False, autor="a", motivo="se me olvidó", hoy=HOY)
    with pytest.raises(ValueError, match="más de 7 días"):
        await mem.eliminar_dia_especial(n["id"], vieja, autor="a", motivo="x", hoy=HOY)


async def test_un_dia_pasado_dentro_de_7_dias_exige_motivo_y_lo_deja_en_la_auditoria():
    n = await _negocio("cal-r2")
    ayer = HOY - timedelta(days=1)
    for motivo in (None, "", "   "):
        with pytest.raises(ValueError, match="motivo"):
            await mem.guardar_dia_especial(n["id"], ayer, "no_laborable", "Cerramos ayer", False, autor="a", motivo=motivo, hoy=HOY)
    r = await mem.guardar_dia_especial(
        n["id"], ayer, "no_laborable", "Cerramos ayer", False, autor="a", motivo="El Gobierno lo declaró tarde", hoy=HOY,
    )
    assert r["accion"] == "creado"
    assert (await _auditoria(n["id"], "dia_especial_creado"))[0].payload["motivo"] == "El Gobierno lo declaró tarde"
    hace_7 = HOY - timedelta(days=7)      # el límite inclusive
    await mem.guardar_dia_especial(n["id"], hace_7, "no_laborable", "Límite", False, autor="a", motivo="ok", hoy=HOY)
    with pytest.raises(ValueError, match="motivo"):
        await mem.eliminar_dia_especial(n["id"], ayer, autor="a", hoy=HOY)
    assert (await mem.eliminar_dia_especial(n["id"], ayer, autor="a", motivo="Fue un error", hoy=HOY))["eliminado_en"] is not None
    assert (await _auditoria(n["id"], "dia_especial_eliminado"))[0].payload["motivo"] == "Fue un error"


async def test_hoy_y_el_futuro_no_piden_motivo():
    n = await _negocio("cal-r3")
    assert (await mem.guardar_dia_especial(n["id"], HOY, "cierre_propio", "Hoy cerramos", False, autor="a", hoy=HOY))["accion"] == "creado"
    assert (await mem.guardar_dia_especial(n["id"], HOY + timedelta(days=200), "feriado", "Lejano", False, autor="a", hoy=HOY))["accion"] == "creado"


# ── Atajo «marcar mañana como no laborable» ─────────────────────────────────

async def test_marcar_manana_no_laborable_cierra_manana_al_instante():
    n = await _negocio("cal-t1")
    # fija el reloj: lunes 12-oct 15:00 de Lima; mañana es martes 13 (día hábil normal)
    antes = await mem.obtener_calendario_negocio(n["id"])                      # calienta la caché SIN excepciones
    assert cn.esta_abierto(datetime(2026, 10, 13, 15, 0) + timedelta(hours=5), antes)
    r = await mem.marcar_manana_no_laborable(n["id"], autor="sup1", hoy=HOY)
    assert r["accion"] == "creado" and r["dia"]["fecha"] == date(2026, 10, 13)
    assert r["dia"]["tipo"] == "no_laborable" and r["dia"]["atiende"] is False and r["dia"]["nombre"] == "Día no laborable"
    despues = await mem.obtener_calendario_negocio(n["id"])                    # la caché se invalidó al guardar: efecto inmediato
    assert not cn.esta_abierto(datetime(2026, 10, 13, 15, 0) + timedelta(hours=5), despues)
    assert cn.estado(datetime(2026, 10, 13, 15, 0) + timedelta(hours=5), despues)["motivo"] == "no_laborable"
    assert (await mem.marcar_manana_no_laborable(n["id"], autor="sup1", hoy=HOY))["accion"] == "sin_cambios"


async def test_marcar_manana_sobre_un_feriado_con_horario_especial_solo_lo_cierra():
    n = await _negocio("cal-t2")
    await mem.guardar_dia_especial(n["id"], "2026-10-13", "feriado", "Feriado raro", True, "09:00", "13:00", autor="a", hoy=HOY)
    r = await mem.marcar_manana_no_laborable(n["id"], autor="a", hoy=HOY)
    assert r["accion"] == "modificado" and r["dia"]["tipo"] == "feriado" and r["dia"]["nombre"] == "Feriado raro"
    assert r["dia"]["atiende"] is False and r["dia"]["hora_apertura"] is None


# ── Caché de 60 s ───────────────────────────────────────────────────────────

async def test_la_cache_dura_60_segundos_y_se_invalida_al_guardar(monkeypatch):
    n = await _negocio("cal-c1")
    reloj = {"t": 1000.0}
    monkeypatch.setattr(mem, "_reloj_cache_calendario", lambda: reloj["t"])
    assert (await mem.obtener_calendario_negocio(n["id"])).excepciones == {}
    # alguien (otro proceso) inserta un día directo en la base: esta caché no se entera todavía
    async with mem.async_session() as session:
        session.add(mem.DiaEspecial(negocio_id=n["id"], fecha=date(2026, 12, 8), tipo="feriado", nombre="Directo", atiende=False))
        await session.commit()
    assert (await mem.obtener_calendario_negocio(n["id"])).excepciones == {}
    reloj["t"] += 59
    assert (await mem.obtener_calendario_negocio(n["id"])).excepciones == {}
    assert date(2026, 12, 8) in (await mem.obtener_calendario_negocio(n["id"], fresco=True)).excepciones     # el Cron lee fresco
    reloj["t"] += 2                                                                                          # pasaron 61 s
    assert date(2026, 12, 8) in (await mem.obtener_calendario_negocio(n["id"])).excepciones


async def test_guardar_invalida_la_cache_del_negocio_pero_no_la_de_otro(monkeypatch):
    a, b = await _negocio("cal-c2"), await _negocio("cal-c3")
    monkeypatch.setattr(mem, "_reloj_cache_calendario", lambda: 5000.0)
    await mem.obtener_calendario_negocio(a["id"])
    await mem.obtener_calendario_negocio(b["id"])
    await mem.guardar_dia_especial(a["id"], "2026-12-08", "feriado", "Propio", False, autor="x", hoy=HOY)
    assert date(2026, 12, 8) in (await mem.obtener_calendario_negocio(a["id"])).excepciones     # inmediato
    assert a["id"] in mem._cache_excepciones and b["id"] in mem._cache_excepciones


async def test_si_la_tabla_no_se_puede_leer_el_calendario_cae_al_horario_semanal(monkeypatch):
    n = await _negocio("cal-c4")

    class _SesionRota:
        async def __aenter__(self):
            raise RuntimeError("no such table: dias_especiales")

        async def __aexit__(self, *a):
            return False

    original = mem.async_session
    llamadas = {"n": 0}

    def sesion():
        llamadas["n"] += 1
        if llamadas["n"] == 2:       # la 1ª es listar_horarios_atencion; la 2ª es la lectura de excepciones
            return _SesionRota()
        return original()

    monkeypatch.setattr(mem, "async_session", sesion)
    cal = await mem.obtener_calendario_negocio(n["id"], fresco=True)
    assert cal.excepciones == {} and cn.rangos_de_semana(cal)[0] == ("08:00", "19:00")


# ── Cobertura ───────────────────────────────────────────────────────────────

async def test_el_aviso_de_cobertura_salta_con_menos_de_60_dias_cargados():
    n = await _negocio("cal-k1")
    r = await mem.resumen_cobertura_calendario(n["id"], HOY)
    assert r["ultima_fecha_cargada"] is None and r["aviso"] is True and "No hay feriados" in r["mensaje"]
    await mem.sembrar_calendario(n["id"], 2026)
    r = await mem.resumen_cobertura_calendario(n["id"], HOY)
    assert r["ultima_fecha_cargada"] == date(2026, 12, 25) and r["dias_restantes"] == 74 and r["aviso"] is False and r["mensaje"] is None
    r = await mem.resumen_cobertura_calendario(n["id"], date(2026, 11, 1))          # faltan 54 días
    assert r["dias_restantes"] == 54 and r["aviso"] is True and "25 de diciembre de 2026" in r["mensaje"]
    await mem.sembrar_calendario(n["id"], 2027)
    assert (await mem.resumen_cobertura_calendario(n["id"], date(2026, 11, 1)))["aviso"] is False


# ── Vigencia de las métricas hábiles ────────────────────────────────────────

async def test_calendario_habil_desde_se_fija_se_lee_y_se_audita():
    n = await _negocio("cal-v1")
    assert await mem.obtener_calendario_habil_desde(n["id"]) is None
    assert await mem.obtener_calendario_habil_desde(None) is None
    r = await mem.fijar_calendario_habil_desde(n["id"], date(2026, 10, 13), autor="script")
    assert r == {"antes": None, "despues": "2026-10-13"}
    assert await mem.obtener_calendario_habil_desde(n["id"]) == date(2026, 10, 13)
    await mem.fijar_calendario_habil_desde(n["id"], None, autor="script")
    assert await mem.obtener_calendario_habil_desde(n["id"]) is None
    assert [f.accion for f in await _auditoria(n["id"])] == ["calendario_habil_desde", "calendario_habil_desde"]
    await mem.guardar_configuracion(mem.CLAVE_CALENDARIO_HABIL_DESDE, "no-es-fecha", negocio_id=n["id"])
    assert await mem.obtener_calendario_habil_desde(n["id"]) is None             # un valor inválido = no fijado


# ── Migración ───────────────────────────────────────────────────────────────

def test_la_migracion_sube_siembra_los_feriados_2026_y_baja_en_sqlite(tmp_path):
    base = tmp_path / "mig_calendario.db"
    entorno = {**os.environ, "DATABASE_URL": f"sqlite+aiosqlite:///{base.as_posix()}"}

    def alembic(*args):
        return subprocess.run(
            [sys.executable, "-m", "alembic", *args], cwd=RAIZ, env=entorno, capture_output=True, text=True, timeout=300,
            stdin=subprocess.DEVNULL,
        )

    previa = alembic("upgrade", "b8e2d4f6a1c3")
    if previa.returncode != 0:
        pytest.skip(f"la cadena anterior de migraciones no corre sobre SQLite vacía en este entorno: {previa.stderr[-200:]}")
    motor = sa.create_engine(f"sqlite:///{base.as_posix()}")
    with motor.begin() as con:     # dos negocios que YA existían antes de la migración
        for i in (1, 2):
            con.execute(sa.text(
                "INSERT INTO negocios (id, nombre, codigo, activo, creado, actualizado) "
                "VALUES (:id, :n, :c, 1, '2026-10-01 00:00:00', '2026-10-01 00:00:00')"
            ), {"id": f"neg-{i}", "n": f"Negocio {i}", "c": f"mig-{i}"})
    motor.dispose()

    sube = alembic("upgrade", "head")
    assert sube.returncode == 0, sube.stderr
    motor = sa.create_engine(f"sqlite:///{base.as_posix()}")
    insp = sa.inspect(motor)
    assert {c["name"] for c in insp.get_columns("dias_especiales")} == {c.name for c in mem.DiaEspecial.__table__.columns}
    indices = {i["name"]: i for i in insp.get_indexes("dias_especiales")}
    assert indices["ix_dia_especial_una_viva_por_fecha"]["unique"] == 1
    assert {"ix_dias_especiales_negocio_id", "ix_dias_especiales_negocio_fecha"} <= set(indices)
    with motor.connect() as con:
        for negocio in ("neg-1", "neg-2"):
            filas = con.execute(sa.text(
                "SELECT fecha, tipo, atiende, origen FROM dias_especiales WHERE negocio_id = :n ORDER BY fecha"
            ), {"n": negocio}).fetchall()
            assert len(filas) == 16 and {f[1] for f in filas} == {"feriado"} and {f[2] for f in filas} == {0}
            assert {f[3] for f in filas} == {"precargado_pe"} and filas[0][0] == "2026-01-01" and filas[-1][0] == "2026-12-25"
            assert not [f for f in filas if f[1] in ("no_laborable", "puente")]
        con.execute(sa.text("PRAGMA foreign_keys=OFF"))
        with pytest.raises(sa.exc.IntegrityError):      # el índice parcial: segundo vivo en la misma fecha
            con.execute(sa.text(
                "INSERT INTO dias_especiales (id, negocio_id, fecha, tipo, nombre, atiende, origen, creado, actualizado) "
                "VALUES ('x', 'neg-1', '2026-12-25', 'feriado', 'Dup', 0, 'manual', '2026-10-12 00:00:00', '2026-10-12 00:00:00')"
            ))
        con.rollback()
    motor.dispose()

    baja = alembic("downgrade", "b8e2d4f6a1c3")
    assert baja.returncode == 0, baja.stderr
    motor = sa.create_engine(f"sqlite:///{base.as_posix()}")
    assert "dias_especiales" not in sa.inspect(motor).get_table_names()
    motor.dispose()
    sube_otra_vez = alembic("upgrade", "head")
    assert sube_otra_vez.returncode == 0, sube_otra_vez.stderr


def test_la_migracion_cuelga_del_head_anterior():
    asunto = (RAIZ / "migrations" / "versions" / "d1a4c7e92b58_dias_especiales_calendario_de_negocio.py").read_text(encoding="utf-8")
    assert "down_revision: Union[str, Sequence[str], None] = 'b8e2d4f6a1c3'" in asunto
    versiones = (RAIZ / "migrations" / "versions").glob("*.py")
    assert sum("'d1a4c7e92b58'" in v.read_text(encoding="utf-8") and "down_revision" in v.read_text(encoding="utf-8") for v in versiones) == 1


# ── Script scripts/sembrar_calendario.py ────────────────────────────────────

def _cargar_script(monkeypatch):
    import importlib.util
    spec = importlib.util.spec_from_file_location("script_sembrar_calendario", RAIZ / "scripts" / "sembrar_calendario.py")
    script = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(script)

    async def sin_espera():
        return None

    monkeypatch.setattr(script, "esperar_base_de_datos", sin_espera)
    return script


async def test_el_script_sin_opciones_solo_muestra_lo_que_insertaria(monkeypatch, capsys):
    script = _cargar_script(monkeypatch)
    n = await _negocio("cal-x1")                     # el único negocio activo: se usa sin --negocio-id
    r = await script.main([])
    salida = capsys.readouterr().out
    assert r["aplicado"] is False and sorted(r["anios"]) == [2026, 2027]
    assert "insertaría 16 feriado(s)" in salida and "Simulación: no se escribió nada" in salida and "no verificado" in salida
    assert await mem.listar_dias_especiales(n["id"]) == []
    assert "no fijada" in salida


async def test_el_script_con_aplicar_siembra_un_anio_y_es_idempotente(monkeypatch, capsys):
    script = _cargar_script(monkeypatch)
    n = await _negocio("cal-x2")
    await script.main(["--anio", "2026", "--aplicar"])
    assert "insertó 16 feriado(s)" in capsys.readouterr().out and len(await mem.listar_dias_especiales(n["id"])) == 16
    await script.main(["--anio", "2026", "--aplicar"])
    assert "insertó 0 feriado(s); ya existían 16" in capsys.readouterr().out and len(await mem.listar_dias_especiales(n["id"])) == 16


async def test_el_script_fija_y_borra_la_vigencia_de_las_metricas_habiles(monkeypatch, capsys):
    script = _cargar_script(monkeypatch)
    n = await _negocio("cal-x3")
    r = await script.main(["--fijar-habil-desde", "2026-10-13"])
    assert r["calendario_habil_desde"] == {"antes": None, "despues": "2026-10-13"} and r["anios"] == {}      # solo toca esa clave
    assert await mem.obtener_calendario_habil_desde(n["id"]) == date(2026, 10, 13)
    assert await mem.listar_dias_especiales(n["id"]) == []
    await script.main(["--fijar-habil-desde", "hoy"])
    assert await mem.obtener_calendario_habil_desde(n["id"]) == mem.hoy_en_lima()
    await script.main(["--fijar-habil-desde", "borrar"])
    assert await mem.obtener_calendario_habil_desde(n["id"]) is None
    with pytest.raises(ValueError, match="AAAA-MM-DD"):
        await script.main(["--fijar-habil-desde", "mañana"])


async def test_el_script_exige_negocio_id_con_varios_negocios(monkeypatch):
    script = _cargar_script(monkeypatch)
    a = await _negocio("cal-x4")
    await _negocio("cal-x5")
    with pytest.raises(ValueError, match="--negocio-id"):
        await script.main(["--anio", "2026"])
    await script.main(["--negocio-id", a["id"], "--anio", "2026", "--aplicar"])
    assert len(await mem.listar_dias_especiales(a["id"])) == 16
