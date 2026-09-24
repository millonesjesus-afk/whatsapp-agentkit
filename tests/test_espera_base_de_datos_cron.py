# Los Cron de Railway conectan a la base en el mismo segundo en que arranca su
# contenedor; con la red PRIVADA eso falla con "Connection refused" (2026-09-24:
# liberar-leads-inactivos y reliable-imagination fallaron a las 11:01/11:04).
# Estas pruebas fijan que el arranque de cada script reintenta en vez de caerse.
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

import agent.memory as mem

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts import backup_postgres  # noqa: E402


class _MotorQueFallaNVeces:
    """Simula la base 'aún no lista': las primeras `fallos` conexiones se rechazan."""

    def __init__(self, fallos: int):
        self.fallos = fallos
        self.intentos = 0

    def connect(self):
        self.intentos += 1
        if self.intentos <= self.fallos:
            raise ConnectionRefusedError("[Errno 111] Connect call failed")
        return _ConexionFalsa()


class _ConexionFalsa:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def execute(self, *_a, **_k):
        return None


async def test_esperar_base_termina_a_la_primera_si_la_base_ya_responde():
    await mem.esperar_base_de_datos(intentos=3, pausa_seg=0)


async def test_esperar_base_reintenta_hasta_que_la_base_contesta(monkeypatch):
    motor = _MotorQueFallaNVeces(fallos=3)
    monkeypatch.setattr(mem, "engine", motor)
    await mem.esperar_base_de_datos(intentos=10, pausa_seg=0)
    assert motor.intentos == 4  # 3 rechazos + el intento que sí entró


async def test_esperar_base_se_rinde_con_el_ultimo_error_si_nunca_contesta(monkeypatch):
    motor = _MotorQueFallaNVeces(fallos=99)
    monkeypatch.setattr(mem, "engine", motor)
    with pytest.raises(ConnectionRefusedError):
        await mem.esperar_base_de_datos(intentos=4, pausa_seg=0)
    assert motor.intentos == 4


def _pg_dump_falso(monkeypatch, resultados):
    llamadas = []

    def falso(*_a, **_k):
        llamadas.append(1)
        return resultados[min(len(llamadas), len(resultados)) - 1]

    monkeypatch.setattr(subprocess, "run", falso)
    monkeypatch.setattr(backup_postgres.time, "sleep", lambda _s: None)
    return llamadas


def test_backup_reintenta_si_pg_dump_no_pudo_conectar(monkeypatch):
    sin_red = SimpleNamespace(returncode=1, stderr='pg_dump: error: connection to server failed: Connection refused')
    bien = SimpleNamespace(returncode=0, stderr="")
    llamadas = _pg_dump_falso(monkeypatch, [sin_red, sin_red, bien])
    backup_postgres._ejecutar_pg_dump("postgresql://u:p@h/db", Path("x.dump"))
    assert len(llamadas) == 3


def test_backup_no_reintenta_un_error_que_no_es_de_conexion(monkeypatch):
    otro = SimpleNamespace(returncode=1, stderr="pg_dump: error: permission denied for table x")
    llamadas = _pg_dump_falso(monkeypatch, [otro])
    with pytest.raises(RuntimeError):
        backup_postgres._ejecutar_pg_dump("postgresql://u:p@h/db", Path("x.dump"))
    assert len(llamadas) == 1
