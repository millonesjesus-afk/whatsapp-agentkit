# tests/test_respaldos_postgres.py — 2026-10-05, Ola 2 (agente A): scripts/backup_postgres.py
# endurecido. Se simulan subprocess (pg_dump / pg_restore) y boto3: nada toca una base ni un bucket.

import importlib.util
import os
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent
URL = "postgresql://usuario:cl%40ve+rara@host.interno:5432/railway"


def _cargar():
    spec = importlib.util.spec_from_file_location("script_backup_postgres", RAIZ / "scripts" / "backup_postgres.py")
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


@pytest.fixture
def bk():
    return _cargar()


@pytest.fixture
def entorno(monkeypatch):
    for k, v in {
        "DATABASE_URL": URL, "S3_ENDPOINT_URL": "https://s3.example", "S3_BUCKET": "bucket",
        "S3_ACCESS_KEY_ID": "AKIA-PRUEBA", "S3_SECRET_ACCESS_KEY": "secreto-de-prueba",
    }.items():
        monkeypatch.setenv(k, v)


class _Completado:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode, self.stdout, self.stderr = returncode, stdout, stderr


class _S3:
    """Cliente S3 falso con paginación simple."""

    def __init__(self, objetos=()):
        self.objetos = list(objetos)       # [{"Key", "LastModified", "Size"}]
        self.subidos, self.borrados = [], []

    def upload_file(self, ruta, bucket, clave):
        self.subidos.append((ruta, bucket, clave))
        self.objetos.append({"Key": clave, "LastModified": datetime.now(timezone.utc), "Size": 1000})

    def get_paginator(self, nombre):
        assert nombre == "list_objects_v2"
        s3 = self

        class _P:
            def paginate(self, Bucket, Prefix):
                yield {"Contents": [o for o in s3.objetos if o["Key"].startswith(Prefix)]}

        return _P()

    def delete_objects(self, Bucket, Delete):
        claves = {o["Key"] for o in Delete["Objects"]}
        self.borrados.extend(sorted(claves))
        self.objetos = [o for o in self.objetos if o["Key"] not in claves]


def _viejo(clave, dias, size=1000):
    return {"Key": clave, "LastModified": datetime.now(timezone.utc) - timedelta(days=dias), "Size": size}


# ── La contraseña no viaja en los argumentos ────────────────────────────────

def test_separar_clave_quita_la_contrasena_de_la_url_y_la_decodifica(bk):
    url, clave = bk._separar_clave(URL)
    assert clave == "cl@ve+rara"
    assert "cl%40ve" not in url and "cl@ve" not in url and "rara" not in url
    assert url == "postgresql://usuario@host.interno:5432/railway"
    assert bk._separar_clave("postgresql://host/db") == ("postgresql://host/db", None)


def test_pg_dump_recibe_la_contrasena_por_pgpassword_y_no_por_argumento(bk, monkeypatch, tmp_path):
    llamadas = []

    def run(cmd, **kw):
        llamadas.append((cmd, kw))
        return _Completado(0)

    monkeypatch.setattr(bk.subprocess, "run", run)
    bk._ejecutar_pg_dump(URL, tmp_path / "x.dump")
    [(cmd, kw)] = llamadas
    assert cmd[0] == "pg_dump"
    assert not any("rara" in a or "cl%40ve" in a or "cl@ve" in a for a in cmd)
    assert kw["env"]["PGPASSWORD"] == "cl@ve+rara"


def test_un_error_de_pg_dump_no_filtra_la_contrasena(bk, monkeypatch, tmp_path):
    monkeypatch.setattr(
        bk.subprocess, "run",
        lambda cmd, **kw: _Completado(1, stderr='pg_dump: error: connection to "postgresql://usuario:cl@ve+rara@host/db" failed: cl@ve+rara'),
    )
    with pytest.raises(RuntimeError) as e:
        bk._ejecutar_pg_dump(URL, tmp_path / "x.dump")
    assert "rara" not in str(e.value) and "pg_dump falló" in str(e.value)


def test_version_distinta_da_un_mensaje_en_espanol_que_explica_que_hacer(bk, monkeypatch, tmp_path):
    monkeypatch.setattr(bk.subprocess, "run", lambda cmd, **kw: _Completado(
        1, stderr="pg_dump: error: aborting because of server version mismatch\npg_dump: detail: server version: 17.2; pg_dump version: 15.8",
    ))
    with pytest.raises(RuntimeError) as e:
        bk._ejecutar_pg_dump(URL, tmp_path / "x.dump")
    mensaje = str(e.value)
    assert "versión del cliente de Postgres" in mensaje and "postgresql-client" in mensaje
    assert "docs/respaldos_postgres.md" in mensaje and "server version: 17.2" in mensaje


def test_si_no_hay_conexion_reintenta_y_luego_funciona(bk, monkeypatch, tmp_path):
    respuestas = [_Completado(1, stderr="could not connect to server: Connection refused"), _Completado(0)]
    monkeypatch.setattr(bk.subprocess, "run", lambda cmd, **kw: respuestas.pop(0))
    monkeypatch.setattr(bk.time, "sleep", lambda s: None)
    bk._ejecutar_pg_dump(URL, tmp_path / "x.dump")
    assert respuestas == []


# ── Verificación del volcado ────────────────────────────────────────────────

def test_un_volcado_vacio_o_inexistente_falla_con_mensaje_claro(bk, tmp_path):
    vacio = tmp_path / "v.dump"
    vacio.write_bytes(b"")
    with pytest.raises(RuntimeError, match="vacío"):
        bk._verificar_volcado(vacio)
    with pytest.raises(RuntimeError, match="vacío"):
        bk._verificar_volcado(tmp_path / "no-existe.dump")


def test_un_volcado_corrupto_falla_y_uno_sano_cuenta_sus_objetos(bk, monkeypatch, tmp_path):
    ruta = tmp_path / "d.dump"
    ruta.write_bytes(b"PGDMP-basura")
    monkeypatch.setattr(bk.subprocess, "run", lambda cmd, **kw: _Completado(1, stderr="pg_restore: error: unsupported version (0.0) in file header"))
    with pytest.raises(RuntimeError, match="corrupto"):
        bk._verificar_volcado(ruta)

    listado = ";\n; Archive created at ...\n;\n215; 1259 16385 TABLE public leads postgres\n216; 1259 16390 TABLE public mensajes postgres\n"
    llamadas = []

    def run(cmd, **kw):
        llamadas.append(cmd)
        return _Completado(0, stdout=listado)

    monkeypatch.setattr(bk.subprocess, "run", run)
    assert bk._verificar_volcado(ruta) == 2
    assert llamadas == [["pg_restore", "--list", str(ruta)]]


def test_un_volcado_sin_objetos_falla(bk, monkeypatch, tmp_path):
    ruta = tmp_path / "d.dump"
    ruta.write_bytes(b"x")
    monkeypatch.setattr(bk.subprocess, "run", lambda cmd, **kw: _Completado(0, stdout=";\n; solo comentarios\n"))
    with pytest.raises(RuntimeError, match="ningún objeto"):
        bk._verificar_volcado(ruta)


# ── Purga solo con un respaldo bueno reciente ───────────────────────────────

def test_hay_respaldo_reciente_solo_cuenta_los_de_menos_de_48_horas_y_no_vacios(bk):
    assert bk._hay_respaldo_reciente(_S3([_viejo("backups/a.dump", 1)]), "b") is True
    assert bk._hay_respaldo_reciente(_S3([_viejo("backups/a.dump", 3)]), "b") is False
    assert bk._hay_respaldo_reciente(_S3([_viejo("backups/a.dump", 0, size=0)]), "b") is False
    assert bk._hay_respaldo_reciente(_S3([]), "b") is False


def test_la_purga_borra_solo_lo_vencido_y_nunca_lo_de_las_ultimas_48_horas(bk):
    s3 = _S3([_viejo("backups/viejo.dump", 40), _viejo("backups/medio.dump", 10), _viejo("backups/ayer.dump", 1), _viejo("otra/cosa.dump", 99)])
    assert bk._purgar_antiguos(s3, "b", 30) == 1
    assert s3.borrados == ["backups/viejo.dump"]
    # Con una retención absurda (0 días) igual se respetan los respaldos de las últimas 48 h.
    s3b = _S3([_viejo("backups/hoy.dump", 0), _viejo("backups/ayer.dump", 1), _viejo("backups/anteayer.dump", 3)])
    assert bk._purgar_antiguos(s3b, "b", 0) == 1
    assert s3b.borrados == ["backups/anteayer.dump"]


def _simular(bk, monkeypatch, s3, volcado_ok=True):
    def run(cmd, **kw):
        if cmd[0] == "pg_dump":
            Path(cmd[cmd.index("--file") + 1]).write_bytes(b"PGDMP" + b"x" * 2048)
            return _Completado(0)
        return _Completado(0, stdout="215; 1259 16385 TABLE public leads postgres\n") if volcado_ok else _Completado(1, stderr="corrupto")

    monkeypatch.setattr(bk.subprocess, "run", run)
    monkeypatch.setattr(bk, "_cliente_s3", lambda config: s3)


def test_flujo_completo_sube_purga_y_resume_con_tamano_y_duracion(bk, entorno, monkeypatch, capsys):
    s3 = _S3([_viejo("backups/viejo.dump", 45), _viejo("backups/ayer.dump", 1)])
    _simular(bk, monkeypatch, s3)
    bk.main()
    salida = capsys.readouterr().out
    [(_, bucket, clave)] = s3.subidos
    assert bucket == "bucket" and clave.startswith("backups/agentkit-") and clave.endswith(".dump")
    assert s3.borrados == ["backups/viejo.dump"]
    assert "verificado" in salida and "Purgados 1" in salida
    assert "MB" in salida and "total" in salida and "pg_dump" in salida and "subida" in salida


def test_si_el_volcado_esta_corrupto_no_se_sube_ni_se_purga_nada(bk, entorno, monkeypatch):
    s3 = _S3([_viejo("backups/viejo.dump", 45)])
    _simular(bk, monkeypatch, s3, volcado_ok=False)
    with pytest.raises(RuntimeError, match="corrupto"):
        bk.main()
    assert s3.subidos == [] and s3.borrados == []


def test_si_tras_subir_el_bucket_no_muestra_un_respaldo_reciente_no_purga(bk, entorno, monkeypatch, capsys):
    s3 = _S3([_viejo("backups/viejo.dump", 45)])
    _simular(bk, monkeypatch, s3)
    s3.upload_file = lambda ruta, bucket, clave: s3.subidos.append((ruta, bucket, clave))   # la subida "no aparece" en el listado
    bk.main()
    assert s3.borrados == []
    assert "no se purgó nada" in capsys.readouterr().out


def test_el_contrato_de_variables_s3_no_cambio(bk, monkeypatch):
    for v in ("DATABASE_URL", "S3_ENDPOINT_URL", "S3_BUCKET", "S3_ACCESS_KEY_ID", "S3_SECRET_ACCESS_KEY"):
        monkeypatch.delenv(v, raising=False)
    with pytest.raises(SystemExit) as e:
        bk._validar_config()
    assert all(v in str(e.value) for v in ("DATABASE_URL", "S3_ENDPOINT_URL", "S3_BUCKET", "S3_ACCESS_KEY_ID", "S3_SECRET_ACCESS_KEY"))
    monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///x.db")
    for v in ("S3_ENDPOINT_URL", "S3_BUCKET", "S3_ACCESS_KEY_ID", "S3_SECRET_ACCESS_KEY"):
        monkeypatch.setenv(v, "x")
    with pytest.raises(SystemExit, match="no es Postgres"):
        bk._validar_config()
