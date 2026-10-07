# tests/test_probar_restauracion_respaldo.py — scripts/probar_restauracion_respaldo.py.
# Se simulan subprocess (pg_restore / pg_dump --list), boto3 y la conexión a Postgres (asyncpg):
# no hay Postgres real ni bucket en las pruebas. Datos sintéticos únicamente.

import argparse
import asyncio
import importlib.util
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent
URL = "postgresql://usuario:cl%40ve+rara@host.interno:5432/railway"
BASE_VIVA = "railway"


def _cargar():
    spec = importlib.util.spec_from_file_location("script_probar_restauracion", RAIZ / "scripts" / "probar_restauracion_respaldo.py")
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


@pytest.fixture
def pr():
    return _cargar()


@pytest.fixture
def entorno(monkeypatch):
    for k, v in {
        "DATABASE_URL": URL, "S3_ENDPOINT_URL": "https://s3.example", "S3_BUCKET": "bucket",
        "S3_ACCESS_KEY_ID": "AKIA-PRUEBA", "S3_SECRET_ACCESS_KEY": "secreto-de-prueba",
    }.items():
        monkeypatch.setenv(k, v)
    monkeypatch.delenv("BACKUP_PREFIJO", raising=False)


def _ahora():
    return datetime.now(timezone.utc)


class _S3:
    def __init__(self, objetos):
        self.objetos = objetos
        self.descargas = []

    def get_paginator(self, nombre):
        s3 = self

        class _P:
            def paginate(self, Bucket, Prefix):
                yield {"Contents": [o for o in s3.objetos if o["Key"].startswith(Prefix)]}

        return _P()

    def download_file(self, bucket, clave, destino):
        self.descargas.append((bucket, clave))
        Path(destino).write_bytes(b"PGDMP-sintetico")


def _objs():
    return [
        {"Key": "backups/agentkit-20261005-080000.dump", "LastModified": _ahora() - timedelta(days=2), "Size": 900_000},
        {"Key": "backups/agentkit-20261007-080000.dump", "LastModified": _ahora() - timedelta(hours=3), "Size": 1_100_000},
        {"Key": "backups/agentkit-20261006-080000.dump", "LastModified": _ahora() - timedelta(days=1), "Size": 1_000_000},
        {"Key": "backups/LEEME.txt", "LastModified": _ahora(), "Size": 10},
    ]


class _Conn:
    """Conexión asyncpg falsa. `conteos` = {tabla: n | None}; registra todo lo que se ejecuta."""

    def __init__(self, base, solo_lectura, registro, conteos, ultimo, fallar_en=None):
        self.base, self.solo_lectura, self.registro = base, solo_lectura, registro
        self.conteos, self.ultimo, self.fallar_en = conteos, ultimo, fallar_en
        self.cerrada = False

    async def execute(self, sql, *a):
        self.registro.append((self.base, sql))
        if self.fallar_en and sql.startswith(self.fallar_en):
            raise RuntimeError(f"fallo simulado en {self.fallar_en}")

    async def fetchval(self, sql, *a):
        self.registro.append((self.base, sql))
        if "to_regclass" in sql:
            tabla = (a[0] if a else "public.mensajes").split(".")[-1]
            return None if self.conteos.get(tabla) is None else tabla
        if "max(timestamp)" in sql:
            return self.ultimo
        if "count(*)" in sql:
            tabla = sql.split("public.")[1].strip('"')
            return self.conteos[tabla]
        raise AssertionError(sql)

    async def close(self):
        self.cerrada = True


CONTEOS_VIVA = {"leads": 1000, "mensajes": 20000, "conversations": 900, "opportunities": 800, "eventos_lead": 5000,
                "usuarios": 8, "configuracion": 30, "uso_mensajes_meta": 400, "envios_meta": 50}


def _montar(pr, monkeypatch, restaurado=None, ultimo=None, viva=None, run=None, fallar_en=None, s3=None, nombre_temp=None):
    """Prepara el entorno simulado. Devuelve (registro_sql, comandos, s3)."""
    registro, comandos = [], []
    restaurado = dict(CONTEOS_VIVA) if restaurado is None else restaurado
    ultimo = (datetime.utcnow() - timedelta(hours=5)) if ultimo is None else ultimo
    viva = dict(CONTEOS_VIVA) if viva is None else viva
    s3 = s3 or _S3(_objs())

    async def conectar(db, base, solo_lectura=False):
        if base == BASE_VIVA:
            return _Conn(base, solo_lectura, registro, viva, None)
        if base.startswith("restauracion_prueba_"):
            return _Conn(base, solo_lectura, registro, restaurado, ultimo)
        return _Conn(base, solo_lectura, registro, {}, None, fallar_en=fallar_en)

    def subproceso(cmd, **kw):
        comandos.append((cmd, kw))
        if run:
            return run(cmd, kw)
        return subprocess.CompletedProcess(cmd, 0, stdout="; Archive\n123; 1259 TABLE leads\n", stderr="")

    monkeypatch.setattr(pr, "_conectar", conectar)
    monkeypatch.setattr(pr, "_cliente_s3", lambda cfg: s3)
    monkeypatch.setattr(pr.subprocess, "run", subproceso)
    if nombre_temp:
        monkeypatch.setattr(pr, "_nombre_temporal", lambda: nombre_temp)
    return registro, comandos, s3


def _args(**kw):
    base = dict(clave=None, dry_run=False, solo_listar=False, base_admin=None)
    base.update(kw)
    return argparse.Namespace(**base)


def _correr(pr, **kw):
    return asyncio.run(pr.ejecutar(_args(**kw)))


# ── Elección del respaldo ───────────────────────────────────────────────────

def test_elige_el_respaldo_mas_reciente_por_fecha_y_ignora_lo_que_no_es_dump(pr):
    respaldos = pr._listar_respaldos(_S3(_objs()), "bucket", "backups/")
    assert [r["clave"] for r in respaldos][0] == "backups/agentkit-20261007-080000.dump"
    assert all(r["clave"].endswith(".dump") for r in respaldos) and len(respaldos) == 3
    assert pr._elegir_respaldo(respaldos, None)["clave"] == "backups/agentkit-20261007-080000.dump"


def test_clave_explicita_y_clave_inexistente(pr):
    respaldos = pr._listar_respaldos(_S3(_objs()), "bucket", "backups/")
    assert pr._elegir_respaldo(respaldos, "backups/agentkit-20261005-080000.dump")["tamano"] == 900_000
    with pytest.raises(RuntimeError, match="No existe"):
        pr._elegir_respaldo(respaldos, "backups/otro.dump")
    with pytest.raises(RuntimeError, match="ningún respaldo"):
        pr._elegir_respaldo([], None)


def test_solo_listar_muestra_los_respaldos_y_no_toca_ninguna_base(pr, entorno, monkeypatch, capsys):
    registro, comandos, s3 = _montar(pr, monkeypatch)
    assert _correr(pr, solo_listar=True) == 0
    salida = capsys.readouterr().out
    assert "agentkit-20261007-080000.dump" in salida and "1.0 MB" in salida
    assert registro == [] and comandos == [] and s3.descargas == []


def test_solo_listar_no_exige_database_url(pr, entorno, monkeypatch):
    monkeypatch.delenv("DATABASE_URL")
    _montar(pr, monkeypatch)
    assert _correr(pr, solo_listar=True) == 0


# ── Dry-run ─────────────────────────────────────────────────────────────────

def test_dry_run_descarga_y_verifica_pero_no_crea_ninguna_base(pr, entorno, monkeypatch, capsys):
    registro, comandos, s3 = _montar(pr, monkeypatch)
    assert _correr(pr, dry_run=True) == 0
    assert s3.descargas == [("bucket", "backups/agentkit-20261007-080000.dump")]
    assert registro == []                                             # ninguna conexión ni SQL
    assert [c[0][:2] for c in comandos] == [["pg_restore", "--list"]]  # solo se lista el índice
    assert "OK (dry-run)" in capsys.readouterr().out


def test_dry_run_con_dump_corrupto_da_error_y_codigo_1(pr, entorno, monkeypatch, capsys):
    _montar(pr, monkeypatch, run=lambda cmd, kw: subprocess.CompletedProcess(cmd, 1, stdout="", stderr="no es un dump"))
    assert _correr(pr, dry_run=True) == 1
    assert "corrupto" in capsys.readouterr().err


def test_respaldo_vacio_en_el_bucket_es_error_sin_saltar_al_anterior(pr, entorno, monkeypatch, capsys):
    objs = _objs()
    objs[1]["Size"] = 0
    registro, comandos, s3 = _montar(pr, monkeypatch, s3=_S3(objs))
    assert _correr(pr) == 1
    assert "vacío" in capsys.readouterr().err
    assert s3.descargas == [] and registro == []      # no se descargó ni se creó ninguna base


# ── Protección de la base viva ──────────────────────────────────────────────

def test_el_nombre_temporal_tiene_la_forma_esperada(pr):
    assert pr.PATRON_BASE_TEMPORAL.match(pr._nombre_temporal())


@pytest.mark.parametrize("nombre", ["railway", "RAILWAY", "postgres", "restauracion_prueba_", "restauracion_prueba_123", "x; DROP DATABASE railway"])
def test_validar_nombre_temporal_rechaza_la_viva_y_cualquier_nombre_ajeno(pr, nombre):
    with pytest.raises(RuntimeError, match="ABORTADO"):
        pr._validar_nombre_temporal(nombre, BASE_VIVA)


def test_si_la_viva_se_llamara_como_la_temporal_aborta_sin_crear_ni_borrar_nada(pr, entorno, monkeypatch, capsys):
    viva = "restauracion_prueba_20261007080000"
    monkeypatch.setenv("DATABASE_URL", f"postgresql://usuario:cl%40ve+rara@host.interno:5432/{viva}")
    registro, comandos, _ = _montar(pr, monkeypatch, nombre_temp=viva)

    async def conectar(db, base, solo_lectura=False):
        registro.append((base, "conectar"))
        return _Conn(base, solo_lectura, registro, CONTEOS_VIVA, None)

    monkeypatch.setattr(pr, "_conectar", conectar)
    assert _correr(pr) == 1
    assert "ABORTADO" in capsys.readouterr().err
    assert not [r for r in registro if "DATABASE" in r[1]]
    assert not [c for c in comandos if c[0][0] == "pg_restore" and "--list" not in c[0]]


def test_la_conexion_administrativa_nunca_es_a_la_base_viva(pr, entorno, monkeypatch):
    registro, _, _ = _montar(pr, monkeypatch)
    assert _correr(pr) == 0
    creates = [r for r in registro if r[1].startswith("CREATE DATABASE")]
    assert [c[0] for c in creates] == ["postgres"]


# ── Camino feliz y veredicto ────────────────────────────────────────────────

def test_camino_feliz_restaura_compara_borra_y_sale_con_0(pr, entorno, monkeypatch, capsys):
    registro, comandos, _ = _montar(pr, monkeypatch, nombre_temp="restauracion_prueba_20261007090000")
    assert _correr(pr) == 0
    salida = capsys.readouterr().out
    assert "VEREDICTO: OK" in salida and "Base temporal restauracion_prueba_20261007090000 eliminada" in salida
    assert "Archivos temporales eliminados" in salida
    assert "leads" in salida and "1,000" in salida and "mensajes" in salida
    restaurar = [c[0] for c in comandos if c[0][0] == "pg_restore" and "--list" not in c[0]]
    assert len(restaurar) == 1
    assert {"--no-owner", "--no-privileges", "--exit-on-error"} <= set(restaurar[0])
    assert restaurar[0][restaurar[0].index("-d") + 1] == "restauracion_prueba_20261007090000"


def test_la_base_viva_solo_se_abre_en_solo_lectura_y_solo_con_select(pr, entorno, monkeypatch):
    abiertas = []
    registro, _, _ = _montar(pr, monkeypatch)
    original = pr._conectar

    async def espia(db, base, solo_lectura=False):
        abiertas.append((base, solo_lectura))
        return await original(db, base, solo_lectura)

    monkeypatch.setattr(pr, "_conectar", espia)
    assert _correr(pr) == 0
    assert (BASE_VIVA, True) in abiertas
    assert not [s for b, s in registro if b == BASE_VIVA and not s.upper().startswith("SELECT")]


def test_viva_con_mas_filas_que_el_respaldo_se_tolera_si_llega_al_90_por_ciento(pr):
    restaurado = dict(CONTEOS_VIVA, leads=950, mensajes=18500)     # 95 % y 92.5 %
    filas, alertas = pr._evaluar(restaurado, CONTEOS_VIVA, datetime.utcnow() - timedelta(hours=2))
    assert alertas == [] and all(f["estado"] in ("OK", "no existe") for f in filas)


def test_menos_del_90_por_ciento_en_tabla_principal_es_alerta(pr):
    restaurado = dict(CONTEOS_VIVA, leads=850)                      # 85 %
    filas, alertas = pr._evaluar(restaurado, CONTEOS_VIVA, datetime.utcnow() - timedelta(hours=2))
    assert len(alertas) == 1 and "leads" in alertas[0] and "90%" in alertas[0]
    assert next(f for f in filas if f["tabla"] == "leads")["estado"] == "ALERTA"


def test_tabla_secundaria_no_exige_90_pero_si_que_no_este_vacia(pr):
    ok = pr._evaluar(dict(CONTEOS_VIVA, usuarios=3), CONTEOS_VIVA, datetime.utcnow())
    assert ok[1] == []
    vacia = pr._evaluar(dict(CONTEOS_VIVA, usuarios=0), CONTEOS_VIVA, datetime.utcnow())
    assert len(vacia[1]) == 1 and "usuarios" in vacia[1][0]


def test_tabla_vacia_en_ambas_o_inexistente_en_ambas_no_es_alerta(pr):
    viva = dict(CONTEOS_VIVA, envios_meta=0, uso_mensajes_meta=None)
    restaurado = dict(CONTEOS_VIVA, envios_meta=0, uso_mensajes_meta=None)
    assert pr._evaluar(restaurado, viva, datetime.utcnow())[1] == []


def test_tabla_que_existe_en_viva_pero_no_en_el_respaldo_es_alerta(pr):
    assert len(pr._evaluar(dict(CONTEOS_VIVA, opportunities=None), CONTEOS_VIVA, datetime.utcnow())[1]) == 1


def test_ultimo_mensaje_de_mas_de_36_horas_es_alerta(pr):
    ahora = datetime(2026, 10, 7, 12, 0)
    assert pr._evaluar(CONTEOS_VIVA, CONTEOS_VIVA, ahora - timedelta(hours=35), ahora)[1] == []
    alertas = pr._evaluar(CONTEOS_VIVA, CONTEOS_VIVA, ahora - timedelta(hours=40), ahora)[1]
    assert len(alertas) == 1 and "36 h" in alertas[0]
    assert len(pr._evaluar(CONTEOS_VIVA, CONTEOS_VIVA, None, ahora)[1]) == 1


def test_alerta_de_conteos_da_veredicto_alerta_codigo_1_y_aun_asi_borra_la_base(pr, entorno, monkeypatch, capsys):
    registro, _, _ = _montar(pr, monkeypatch, restaurado=dict(CONTEOS_VIVA, mensajes=100), nombre_temp="restauracion_prueba_20261007090000")
    assert _correr(pr) == 1
    salida = capsys.readouterr().out
    assert "VEREDICTO: ALERTA" in salida and "ALERTA" in salida.split("VEREDICTO")[0]   # también en la tabla
    assert any(s.startswith("DROP DATABASE") for _, s in registro)


# ── Limpieza garantizada ────────────────────────────────────────────────────

def test_si_pg_restore_falla_igual_se_elimina_la_base_y_sale_con_1(pr, entorno, monkeypatch, capsys):
    def run(cmd, kw):
        if "--list" in cmd:
            return subprocess.CompletedProcess(cmd, 0, stdout="123; 1259 TABLE leads\n", stderr="")
        return subprocess.CompletedProcess(cmd, 1, stdout="", stderr='pg_restore: error: connection to "postgresql://usuario:cl@ve+rara@host/db" failed: cl@ve+rara')

    registro, _, _ = _montar(pr, monkeypatch, run=run, nombre_temp="restauracion_prueba_20261007090000")
    assert _correr(pr) == 1
    captura = capsys.readouterr()
    assert "pg_restore falló" in captura.err and "rara" not in captura.err and "rara" not in captura.out
    assert ("postgres", 'DROP DATABASE IF EXISTS "restauracion_prueba_20261007090000" WITH (FORCE)') in registro
    assert "eliminada" in captura.out


def test_si_el_create_falla_a_medias_se_intenta_borrar_igual(pr, entorno, monkeypatch):
    registro, _, _ = _montar(pr, monkeypatch, fallar_en="CREATE DATABASE", nombre_temp="restauracion_prueba_20261007090000")
    assert _correr(pr) == 1
    assert any(s.startswith("DROP DATABASE IF EXISTS") for _, s in registro)


def test_si_falla_la_comparacion_tambien_se_limpia(pr, entorno, monkeypatch):
    registro, _, _ = _montar(pr, monkeypatch, nombre_temp="restauracion_prueba_20261007090000")

    async def revienta(conn, tablas):
        raise RuntimeError("consulta imposible")

    monkeypatch.setattr(pr, "_contar", revienta)
    assert _correr(pr) == 1
    assert any(s.startswith("DROP DATABASE IF EXISTS") for _, s in registro)


def test_si_no_se_puede_borrar_la_base_temporal_es_alerta_con_codigo_1(pr, entorno, monkeypatch, capsys):
    _montar(pr, monkeypatch, fallar_en="DROP DATABASE", nombre_temp="restauracion_prueba_20261007090000")
    assert _correr(pr) == 1
    captura = capsys.readouterr()
    assert "Elimínala a mano" in captura.err and "VEREDICTO: ALERTA" in captura.out


def test_los_archivos_temporales_se_borran_incluso_si_falla(pr, entorno, monkeypatch):
    directorios = []
    real = pr.tempfile.TemporaryDirectory

    class Espia(real):
        def __init__(self, *a, **k):
            super().__init__(*a, **k)
            directorios.append(Path(self.name))

    monkeypatch.setattr(pr.tempfile, "TemporaryDirectory", Espia)
    _montar(pr, monkeypatch, run=lambda cmd, kw: subprocess.CompletedProcess(cmd, 1, stdout="", stderr="roto"))
    assert _correr(pr) == 1
    assert directorios and not any(d.exists() for d in directorios)


# ── Nunca DROP sobre otra base ──────────────────────────────────────────────

@pytest.mark.parametrize("fallo", [None, "CREATE DATABASE", "DROP DATABASE"])
def test_ningun_drop_apunta_a_una_base_distinta_de_la_temporal(pr, entorno, monkeypatch, fallo):
    registro, _, _ = _montar(pr, monkeypatch, fallar_en=fallo, nombre_temp="restauracion_prueba_20261007090000")
    _correr(pr)
    drops = [s for _, s in registro if "DROP" in s.upper()]
    assert all('"restauracion_prueba_20261007090000"' in s for s in drops)
    assert not any(BASE_VIVA in s and "restauracion_prueba" not in s for s in drops)
    assert not [s for b, s in registro if b == BASE_VIVA and ("DROP" in s.upper() or "CREATE" in s.upper())]


def test_eliminar_base_se_niega_con_la_viva_o_nombres_ajenos(pr):
    class C:
        async def execute(self, sql):
            raise AssertionError("no debía ejecutarse")

    for nombre in ("railway", "postgres", "template1"):
        with pytest.raises(RuntimeError, match="ABORTADO"):
            asyncio.run(pr._eliminar_base(C(), nombre, BASE_VIVA))
        with pytest.raises(RuntimeError, match="ABORTADO"):
            asyncio.run(pr._crear_base(C(), nombre, BASE_VIVA))


# ── La contraseña no se ve ──────────────────────────────────────────────────

def test_ningun_comando_lleva_la_contrasena_ni_la_url_y_va_por_pgpassword(pr, entorno, monkeypatch, capsys):
    _, comandos, _ = _montar(pr, monkeypatch)
    assert _correr(pr) == 0
    assert comandos
    for cmd, kw in comandos:
        texto = " ".join(cmd)
        assert "rara" not in texto and "cl%40ve" not in texto and "cl@ve" not in texto and "://" not in texto
    restaurar = next(c for c in comandos if "--list" not in c[0])
    assert restaurar[1]["env"]["PGPASSWORD"] == "cl@ve+rara"
    assert restaurar[0][restaurar[0].index("-h") + 1] == "host.interno"
    assert restaurar[0][restaurar[0].index("-U") + 1] == "usuario"
    captura = capsys.readouterr()
    assert "rara" not in captura.out + captura.err


def test_parsear_url_decodifica_y_acepta_el_esquema_asyncpg(pr):
    db = pr._parsear_url("postgresql+asyncpg://usuario:cl%40ve+rara@host.interno:6543/railway")
    assert db == {"host": "host.interno", "puerto": 6543, "usuario": "usuario", "clave": "cl@ve+rara", "base": "railway"}


# ── Configuración y códigos de salida ───────────────────────────────────────

def test_faltan_variables_sale_con_1(pr, monkeypatch, capsys):
    for v in ("DATABASE_URL", "S3_ENDPOINT_URL", "S3_BUCKET", "S3_ACCESS_KEY_ID", "S3_SECRET_ACCESS_KEY"):
        monkeypatch.delenv(v, raising=False)
    assert _correr(pr) == 1
    assert "Faltan variables de entorno" in capsys.readouterr().err


def test_sqlite_se_rechaza(pr, entorno, monkeypatch, capsys):
    monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///./x.db")
    _montar(pr, monkeypatch)
    assert _correr(pr) == 1
    assert "no es Postgres" in capsys.readouterr().err


def test_main_devuelve_el_codigo_de_ejecutar_y_parsea_las_banderas(pr, entorno, monkeypatch):
    _montar(pr, monkeypatch)
    assert pr.main(["--solo-listar"]) == 0
    assert pr.main(["--dry-run", "--clave", "backups/agentkit-20261005-080000.dump"]) == 0
    assert pr.main(["--dry-run", "--clave", "backups/no-existe.dump"]) == 1


def test_el_script_no_registra_latido_ni_esta_en_crones_esperados(pr):
    from agent import memory as mem
    codigo = (RAIZ / "scripts" / "probar_restauracion_respaldo.py").read_text(encoding="utf-8")
    assert "ejecutar_cron(" not in codigo
    assert "probar_restauracion_respaldo" not in mem.CRONES_ESPERADOS


def test_eventos_lead_tiene_un_piso_menor_porque_crece_mas_rapido(pr):
    # 83 %: lo que se vio en una restauración sana con un respaldo de ~14 h.
    ok = pr._evaluar(dict(CONTEOS_VIVA, eventos_lead=4150), CONTEOS_VIVA, datetime.utcnow() - timedelta(hours=2))
    assert ok[1] == []
    # 65 %: ahí sí es alerta, y el mensaje cita el piso real de esa tabla (70 %).
    mal = pr._evaluar(dict(CONTEOS_VIVA, eventos_lead=3250), CONTEOS_VIVA, datetime.utcnow() - timedelta(hours=2))
    assert len(mal[1]) == 1 and "eventos_lead" in mal[1][0] and "70%" in mal[1][0]
