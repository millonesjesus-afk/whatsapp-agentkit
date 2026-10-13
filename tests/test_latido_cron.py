# tests/test_latido_cron.py — 2026-10-05, Ola 2 (agente A): latido de los procesos
# programados (scripts/_cron.py + tabla cron_ejecuciones), aviso en Inicio solo para
# el admin, y el cron de inactividad que ya no se aborta por un lead con error.
#
# Datos sintéticos únicamente.

import ast
import asyncio
import importlib.util
import os
from datetime import datetime, timedelta
from pathlib import Path

os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")
os.environ.setdefault("WHATSAPP_PROVIDER", "meta")

import pytest
from sqlalchemy import select

from agent import dashboard, memory as mem
from scripts import _cron

RAIZ = Path(__file__).resolve().parent.parent
SCRIPTS = [
    "liberar_leads_inactivos", "procesar_inactividad_clientes", "purgar_archivos_expirados",
    "cerrar_leads_definitivamente", "cerrar_ventas_sin_seguimiento", "backup_postgres",
    "recuperar_mensajes_sin_respuesta", "plantilla_zona_muerta", "crear_tareas_llamada",
]


def _cargar(nombre_script: str):
    spec = importlib.util.spec_from_file_location(f"script_{nombre_script}", RAIZ / "scripts" / f"{nombre_script}.py")
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


async def _filas(script: str | None = None):
    async with mem.async_session() as s:
        consulta = select(mem.CronEjecucion).order_by(mem.CronEjecucion.id)
        if script:
            consulta = consulta.where(mem.CronEjecucion.script == script)
        return (await s.execute(consulta)).scalars().all()


async def _corrida(script, hace_min, ok, resumen=None, dur_min=1):
    """Una corrida sintética que EMPEZÓ hace `hace_min` minutos y duró `dur_min`."""
    inicio = datetime.utcnow() - timedelta(minutes=hace_min)
    async with mem.async_session() as s:
        s.add(mem.CronEjecucion(
            script=script, inicio=inicio, ok=ok, resumen=resumen,
            fin=None if ok is None else inicio + timedelta(minutes=dur_min),
        ))
        await s.commit()


# ---------------------------------------------------------------------------
# ejecutar_cron
# ---------------------------------------------------------------------------

async def test_corrida_buena_registra_inicio_fin_ok_y_resumen_sin_cambiar_la_salida(capsys):
    async def main():
        print("Primera línea")
        print("Resumen final: 3 cosas")

    await _cron.ejecutar_cron("liberar_leads_inactivos", main, 5)

    [fila] = await _filas()
    assert (fila.script, fila.ok) == ("liberar_leads_inactivos", True)
    assert fila.inicio is not None and fila.fin is not None and fila.fin >= fila.inicio
    assert fila.resumen == "Primera línea | Resumen final: 3 cosas"
    # La salida impresa sigue siendo la misma de siempre.
    assert capsys.readouterr().out == "Primera línea\nResumen final: 3 cosas\n"


async def test_el_resumen_se_trunca_a_300_caracteres():
    async def main():
        print("x" * 1000)

    await _cron.ejecutar_cron("purgar_archivos_expirados", main, 1440)
    [fila] = await _filas()
    assert len(fila.resumen) == 300


async def test_un_main_comun_no_async_tambien_funciona(capsys):
    def main():
        print("hecho")

    await _cron.ejecutar_cron("backup_postgres", main, 1440)
    [fila] = await _filas()
    assert (fila.ok, fila.resumen) == (True, "hecho")


async def test_si_el_script_falla_registra_ok_false_sin_secretos_y_vuelve_a_lanzar(monkeypatch):
    monkeypatch.setenv("S3_SECRET_ACCESS_KEY", "super-secreto-123456")

    async def main():
        print("algo salió antes")
        raise RuntimeError("no conecta a postgresql://usuario:ClaveSecreta@host:5432/db con super-secreto-123456")

    with pytest.raises(RuntimeError):
        await _cron.ejecutar_cron("cerrar_leads_definitivamente", main, 1440)

    [fila] = await _filas()
    assert fila.ok is False and fila.fin is not None
    assert "RuntimeError" in fila.resumen and "no conecta" in fila.resumen
    assert "ClaveSecreta" not in fila.resumen and "super-secreto-123456" not in fila.resumen
    assert len(fila.resumen) <= 300


async def test_un_systemexit_se_registra_como_falla_y_se_conserva():
    def main():
        raise SystemExit("Faltan variables de entorno: S3_BUCKET")

    with pytest.raises(SystemExit):
        await _cron.ejecutar_cron("backup_postgres", main, 1440)
    [fila] = await _filas()
    assert fila.ok is False and "Faltan variables de entorno: S3_BUCKET" in fila.resumen


async def test_si_la_base_no_esta_disponible_el_script_igual_hace_su_trabajo(monkeypatch):
    async def inicio_roto(*a, **k):
        raise ConnectionRefusedError("sin base")

    async def fin_roto(*a, **k):
        raise ConnectionRefusedError("sin base")

    monkeypatch.setattr(mem, "registrar_inicio_cron", inicio_roto)
    monkeypatch.setattr(mem, "registrar_fin_cron", fin_roto)
    hecho = []

    async def main():
        hecho.append(True)

    await _cron.ejecutar_cron("liberar_leads_inactivos", main, 5)   # no lanza
    assert hecho == [True]

    # Tampoco enmascara la falla real del script.
    async def main_malo():
        raise ValueError("falla real")

    with pytest.raises(ValueError, match="falla real"):
        await _cron.ejecutar_cron("liberar_leads_inactivos", main_malo, 5)


async def test_si_no_se_pudo_anotar_el_inicio_el_fin_inserta_la_fila_completa(monkeypatch):
    async def inicio_roto(*a, **k):
        raise ConnectionRefusedError("aún sin red")

    monkeypatch.setattr(mem, "registrar_inicio_cron", inicio_roto)

    async def main():
        print("ok igual")

    await _cron.ejecutar_cron("liberar_leads_inactivos", main, 5)
    [fila] = await _filas()
    assert (fila.ok, fila.resumen) == (True, "ok igual") and fila.inicio <= fila.fin


async def test_registrar_inicio_borra_las_corridas_de_mas_de_30_dias_del_mismo_script():
    await _corrida("liberar_leads_inactivos", hace_min=40 * 24 * 60, ok=True)
    await _corrida("backup_postgres", hace_min=40 * 24 * 60, ok=True)   # otro script: no se toca
    await mem.registrar_inicio_cron("liberar_leads_inactivos")
    assert len(await _filas("liberar_leads_inactivos")) == 1
    assert len(await _filas("backup_postgres")) == 1


# ---------------------------------------------------------------------------
# Healthcheck externo
# ---------------------------------------------------------------------------

class _Respuesta:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self, n=-1):
        return b""


async def test_healthcheck_bien_hace_get_a_la_url_y_falla_a_url_fail(monkeypatch):
    llamadas = []

    def urlopen(url, timeout=None):
        llamadas.append((url, timeout))
        return _Respuesta()

    monkeypatch.setattr(_cron.urllib.request, "urlopen", urlopen)
    monkeypatch.setenv("HEALTHCHECK_URL_BACKUP_POSTGRES", "https://hc.example/ping/abc")

    async def bien():
        pass

    async def mal():
        raise RuntimeError("x")

    await _cron.ejecutar_cron("backup_postgres", bien, 1440)
    with pytest.raises(RuntimeError):
        await _cron.ejecutar_cron("backup_postgres", mal, 1440)
    assert llamadas == [("https://hc.example/ping/abc", 5), ("https://hc.example/ping/abc/fail", 5)]


async def test_sin_variable_no_hay_llamada_y_un_healthcheck_roto_nunca_lanza(monkeypatch):
    llamadas = []

    def urlopen(url, timeout=None):
        llamadas.append(url)
        raise OSError("sin internet")

    monkeypatch.setattr(_cron.urllib.request, "urlopen", urlopen)

    async def bien():
        pass

    monkeypatch.delenv("HEALTHCHECK_URL_LIBERAR_LEADS_INACTIVOS", raising=False)
    await _cron.ejecutar_cron("liberar_leads_inactivos", bien, 5)
    assert llamadas == []

    monkeypatch.setenv("HEALTHCHECK_URL_LIBERAR_LEADS_INACTIVOS", "https://hc.example/x")
    await _cron.ejecutar_cron("liberar_leads_inactivos", bien, 5)   # el fallo del ping no rompe nada
    assert llamadas == ["https://hc.example/x"]


# ---------------------------------------------------------------------------
# Los 7 scripts
# ---------------------------------------------------------------------------

def _llamada_a_ejecutar_cron(nombre_script: str):
    arbol = ast.parse((RAIZ / "scripts" / f"{nombre_script}.py").read_text(encoding="utf-8"))
    for nodo in ast.walk(arbol):
        if isinstance(nodo, ast.Call) and getattr(nodo.func, "id", None) == "ejecutar_cron":
            return nodo
    return None


def _valor(nodo, arbol):
    """Valor literal de un argumento; si es una constante de módulo (NOMBRE_CRON = "x"), la resuelve."""
    if isinstance(nodo, ast.Constant):
        return nodo.value
    for n in arbol.body:
        if isinstance(n, ast.Assign) and any(getattr(t, "id", None) == getattr(nodo, "id", object()) for t in n.targets):
            return n.value.value
    raise AssertionError("argumento de ejecutar_cron no resoluble")


@pytest.mark.parametrize("nombre", SCRIPTS)
def test_cada_script_usa_ejecutar_cron_con_su_nombre_y_el_intervalo_que_vigila_el_panel(nombre):
    llamada = _llamada_a_ejecutar_cron(nombre)
    assert llamada is not None, f"{nombre} no llama a ejecutar_cron"
    arbol = ast.parse((RAIZ / "scripts" / f"{nombre}.py").read_text(encoding="utf-8"))
    assert _valor(llamada.args[0], arbol) == nombre
    assert _valor(llamada.args[2], arbol) == mem.CRONES_ESPERADOS[nombre][1]


def test_los_nueve_scripts_estan_vigilados_y_cargan_por_ruta():
    assert set(mem.CRONES_ESPERADOS) == set(SCRIPTS)
    for nombre in SCRIPTS:
        modulo = _cargar(nombre)
        assert callable(modulo.main)


# ---------------------------------------------------------------------------
# Aviso en Inicio
# ---------------------------------------------------------------------------

async def _avisos():
    return await dashboard._avisos_procesos_programados()


async def test_un_script_que_nunca_corrio_no_genera_aviso():
    assert await _avisos() == []


async def test_corrida_reciente_y_buena_no_avisa():
    await _corrida("liberar_leads_inactivos", hace_min=3, ok=True)
    await _corrida("backup_postgres", hace_min=60 * 20, ok=True)   # 20 h, intervalo 24 h
    assert await _avisos() == []


async def test_la_ultima_corrida_fallida_avisa_error_con_el_nombre_legible():
    await _corrida("backup_postgres", hace_min=60 * 30, ok=True)
    await _corrida("backup_postgres", hace_min=5, ok=False, resumen="RuntimeError: pg_dump falló")
    [aviso] = await _avisos()
    assert aviso["nivel"] == "error"
    assert aviso["titulo"] == 'El proceso programado "Respaldo de la base de datos" falló en su última corrida'
    assert "pg_dump falló" in aviso["detalle"]


async def test_una_falla_vieja_ya_superada_por_una_corrida_buena_no_avisa():
    await _corrida("liberar_leads_inactivos", hace_min=60, ok=False, resumen="boom")
    await _corrida("liberar_leads_inactivos", hace_min=2, ok=True)
    assert await _avisos() == []


async def test_corrida_buena_de_hace_mas_del_doble_del_intervalo_avisa_advertencia():
    await _corrida("liberar_leads_inactivos", hace_min=70, ok=True)     # intervalo 5 min → límite 10 min
    [aviso] = await _avisos()
    assert aviso["nivel"] == "warning"
    assert aviso["titulo"].startswith('El proceso programado "Rotación de leads inactivos" no corre desde hace ')
    assert "1 h" in aviso["titulo"]


async def test_justo_dentro_del_doble_del_intervalo_no_avisa():
    await _corrida("procesar_inactividad_clientes", hace_min=50, ok=True, dur_min=1)   # intervalo 30 → límite 60
    assert await _avisos() == []


async def test_una_corrida_que_empezo_y_nunca_cerro_cuenta_como_atrasada_si_pasa_el_limite():
    await _corrida("recuperar_mensajes_sin_respuesta", hace_min=120, ok=True)
    await _corrida("recuperar_mensajes_sin_respuesta", hace_min=60, ok=None)   # murió a mitad
    [aviso] = await _avisos()
    assert aviso["nivel"] == "warning" and "Recuperación de mensajes sin respuesta" in aviso["titulo"]


async def test_un_fallo_calculando_los_avisos_no_rompe_inicio(monkeypatch):
    async def roto(scripts):
        raise RuntimeError("base caída")

    monkeypatch.setattr(mem, "resumen_corridas_cron", roto)
    assert await _avisos() == []


async def test_los_avisos_de_procesos_solo_van_al_admin():
    await _corrida("backup_postgres", hace_min=5, ok=False, resumen="mal")
    negocio = await mem.crear_negocio("Negocio latido", "latido-1")
    admin = {"rol": "admin", "negocio_id": negocio["id"], "username": "adm"}
    avisos = await dashboard._avisos_inicio(admin)
    assert any(a["id"] == "cron-backup_postgres-fallo" for a in avisos)
    for rol in ("supervisor", "asesor"):
        assert await dashboard._avisos_inicio({**admin, "rol": rol}) == []


async def test_resumen_corridas_usa_dos_consultas_agrupadas_y_devuelve_ultimo_ok():
    await _corrida("liberar_leads_inactivos", hace_min=30, ok=True)
    await _corrida("liberar_leads_inactivos", hace_min=10, ok=False, resumen="x")
    await _corrida("backup_postgres", hace_min=10, ok=True)
    r = await mem.resumen_corridas_cron(["liberar_leads_inactivos", "backup_postgres", "purgar_archivos_expirados"])
    assert set(r) == {"liberar_leads_inactivos", "backup_postgres"}      # el que nunca corrió no aparece
    assert r["liberar_leads_inactivos"]["ultima"]["ok"] is False
    assert r["liberar_leads_inactivos"]["ultimo_ok_fin"] is not None


# ---------------------------------------------------------------------------
# Migración
# ---------------------------------------------------------------------------

def test_hay_un_solo_head_y_la_migracion_cuelga_del_head_anterior():
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    cfg = Config(str(RAIZ / "alembic.ini"))
    cfg.set_main_option("script_location", str(RAIZ / "migrations"))
    guion = ScriptDirectory.from_config(cfg)
    # 2026-10-12: la migración del calendario de negocio (d1a4c7e92b58) cuelga de la de "Para llamar" y es el head actual.
    assert guion.get_heads() == ["d1a4c7e92b58"]
    assert guion.get_revision("d1a4c7e92b58").down_revision == "b8e2d4f6a1c3"
    assert guion.get_revision("b8e2d4f6a1c3").down_revision == "a7d3b9e2c4f1"
    assert guion.get_revision("a7d3b9e2c4f1").down_revision == "e5a1c8f3b2d7"


def test_la_migracion_sube_y_baja_en_sqlite_y_coincide_con_los_modelos(tmp_path):
    import sqlalchemy as sa
    import subprocess
    import sys

    # Alembic async corre su propio asyncio.run: se ejecuta en un subproceso con otra base.
    base = tmp_path / "mig.db"
    entorno = {**os.environ, "DATABASE_URL": f"sqlite+aiosqlite:///{base.as_posix()}"}

    def alembic(*args):
        return subprocess.run(
            [sys.executable, "-m", "alembic", *args], cwd=RAIZ, env=entorno, capture_output=True, text=True, timeout=300, stdin=subprocess.DEVNULL,
        )

    previa = alembic("upgrade", "e5a1c8f3b2d7")
    if previa.returncode != 0:
        pytest.skip(f"la cadena anterior de migraciones no corre sobre SQLite vacía en este entorno: {previa.stderr[-200:]}")
    sube = alembic("upgrade", "a7d3b9e2c4f1")
    assert sube.returncode == 0, sube.stderr
    motor = sa.create_engine(f"sqlite:///{base.as_posix()}")
    insp = sa.inspect(motor)
    assert {c["name"] for c in insp.get_columns("cron_ejecuciones")} == {"id", "script", "inicio", "fin", "ok", "resumen"}
    assert "asesor_usuario" in {c["name"] for c in insp.get_columns("envios_meta")}
    assert any(i["name"] == "ix_cron_ejecuciones_script_inicio" for i in insp.get_indexes("cron_ejecuciones"))
    motor.dispose()

    baja = alembic("downgrade", "e5a1c8f3b2d7")
    assert baja.returncode == 0, baja.stderr
    motor = sa.create_engine(f"sqlite:///{base.as_posix()}")
    insp = sa.inspect(motor)
    assert "cron_ejecuciones" not in insp.get_table_names()
    assert "asesor_usuario" not in {c["name"] for c in insp.get_columns("envios_meta")}
    motor.dispose()


# ---------------------------------------------------------------------------
# procesar_inactividad_clientes: un lead con error no aborta la corrida
# ---------------------------------------------------------------------------

async def test_un_lead_con_error_de_red_no_aborta_el_reenganche_ni_el_cierre(monkeypatch, capsys):
    script = _cargar("procesar_inactividad_clientes")
    enviados, cerrados = [], []

    class ProveedorFalso:
        async def resolver_canal(self, numero_whatsapp_id, negocio_id=None):
            return {"phone_number_id": "x", "negocio_id": "n"}

        async def enviar_mensaje(self, telefono, mensaje, canal=None):
            if telefono == "51900000001":
                raise ConnectionError("red caída")
            enviados.append(telefono)
            return True, "wamid.1"

    async def candidatos(horas_reenganche, horas_cierre):
        fila = {"negocio_id": "n", "numero_whatsapp_id": "x"}
        reenganche = [{**fila, "telefono": "51900000001"}, {**fila, "telefono": "51900000002"}]
        cierre = [{**fila, "telefono": "51900000003"}, {**fila, "telefono": "51900000004"}]
        return reenganche, cierre

    async def guardar(*args, **kwargs):
        return {"conversation_id": None}

    async def emitir(_):
        return None

    async def actualizar(telefono, **kwargs):
        if telefono == "51900000003":
            raise TimeoutError("base lenta")
        cerrados.append((telefono, kwargs))

    async def sondeo():
        return None

    async def abierto():
        return False

    async def esperar():
        return None

    monkeypatch.setattr(script, "esperar_base_de_datos", esperar)
    monkeypatch.setattr(script.circuito_ia, "sondear_si_corresponde", sondeo)
    monkeypatch.setattr(script.circuito_ia, "esta_abierto", abierto)
    monkeypatch.setattr(script, "listar_leads_inactividad_cliente", candidatos)
    monkeypatch.setattr(script, "obtener_proveedor", lambda: ProveedorFalso())
    monkeypatch.setattr(script, "guardar_mensaje", guardar)
    monkeypatch.setattr(script, "actualizar_lead", actualizar)
    monkeypatch.setattr(script.gestor_conexiones, "emitir_mensaje_nuevo", emitir)

    await script.main()   # no lanza

    assert enviados == ["51900000002"]                                   # el siguiente lead sí se procesó
    assert cerrados == [("51900000004", {"resultado": "sin_respuesta"})]  # el cierre corrió pese al error
    salida = capsys.readouterr()
    assert "1 reenganchado(s)" in salida.out and "1 cerrado(s)" in salida.out and "2 error(es)" in salida.out
