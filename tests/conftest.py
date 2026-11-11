# tests/conftest.py — Fixtures de aislamiento de BD para los tests de Gate 5.2.
#
# Fuerza DATABASE_URL/CANAL_ENCRYPTION_KEY a valores de prueba ANTES de que
# cualquier test importe agent.memory (que crea su engine/async_session a
# nivel de módulo, leyendo esas variables al importarse) — así los tests
# nunca tocan agentkit.db (la base de desarrollo real) ni requieren que el
# desarrollador tenga configurado un .env local.
#
# CÓMO SE AÍSLA CADA TEST (2026-10-08)
# ------------------------------------
# Antes, una fixture autouse hacía `drop_all` + `create_all` de las ~24 tablas
# antes de CADA test (≈1,65 s por prueba: casi todo el tiempo de la suite
# completa). Ahora:
#   1. El ESQUEMA se crea UNA sola vez por sesión de pytest
#      (`_esquema_de_pruebas`, síncrona: así no depende del event loop ni del
#      engine async de agent.memory, que se crea a nivel de módulo).
#   2. ENTRE tests solo se VACÍAN las tablas (`_base_de_datos_limpia`): DELETE
#      en orden inverso de dependencias (≈0,06 s) y se reinician los
#      contadores autoincrement (sqlite_sequence). Cada test arranca de una
#      base vacía igual que antes.
#   3. Un test que necesite recrear/alterar el esquema o depender de que una
#      tabla no exista se marca con `@pytest.mark.esquema_propio`: para él
#      se conserva el comportamiento antiguo (drop_all + create_all antes y
#      drop_all después; el esquema vuelve a quedar creado al terminar).
#      Hoy ningún test lo necesita (los de migración corren Alembic en un
#      subproceso sobre su propia base en tmp_path; los que cambian
#      `mem.engine` lo hacen con un motor falso, sin tocar el esquema).
#
# CÓMO CORRER
# -----------
# La base de pruebas es un archivo SQLite POR PROCESO
# (`<tmp>/gate52_test_<worker>_<pid>.db`), así que dos corridas de pytest a la
# vez —o los workers de pytest-xdist— nunca comparten archivo ni se pisan:
#
#   python -m pytest tests/                 # un solo proceso
#   python -m pytest tests/ -n 4 --capture=sys   # en paralelo (pip install -r requirements-dev.txt)
#   python -m pytest tests/ -n auto --capture=sys # un worker por CPU
#
# IMPORTANTE (Windows + Python 3.14): con -n hay que pasar `--capture=sys` (o
# `-s`). Con la captura por defecto (fd) el worker de xdist muere al arrancar de
# forma intermitente ("INTERNALERROR ... EOFError: couldn't load message header",
# ~50 % de las veces); es un problema del arranque de xdist/execnet, no de esta
# suite. Con `--capture=sys` no se reprodujo en ninguna de las corridas.
#
# Los archivos temporales se borran al terminar la sesión.

import os
import asyncio
import sqlite3
import tempfile
from pathlib import Path

_worker = os.environ.get("PYTEST_XDIST_WORKER", "main")  # "gw0", "gw1"... bajo xdist
_RUTA_BASE_PRUEBAS = Path(tempfile.gettempdir()) / f"gate52_test_{_worker}_{os.getpid()}.db"

os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{_RUTA_BASE_PRUEBAS.as_posix()}"
os.environ.setdefault("CANAL_ENCRYPTION_KEY", "zzqUtYlDYe2FxH5yL9P1WTjMESEVFO3lShs7An_E73g=")

import pytest
import pytest_asyncio
import sqlalchemy as sa

from agent import memory as mem


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "esquema_propio: el test crea/borra/altera tablas o depende de que no existan; "
        "conserva el drop_all+create_all por test en vez de solo vaciar las tablas",
    )


def _borrar_archivos_de_la_base() -> None:
    for sufijo in ("", "-journal", "-wal", "-shm"):
        try:
            Path(f"{_RUTA_BASE_PRUEBAS}{sufijo}").unlink()
        except OSError:
            pass


@pytest.fixture(scope="session", autouse=True)
def _esquema_de_pruebas():
    """Crea el esquema completo (todas las tablas de Base.metadata) UNA vez por
    sesión, con un motor síncrono sobre el mismo archivo que usa mem.engine."""
    _borrar_archivos_de_la_base()  # por si un pid reutilizado dejó un archivo viejo
    motor = sa.create_engine(f"sqlite:///{_RUTA_BASE_PRUEBAS.as_posix()}")
    try:
        mem.Base.metadata.create_all(motor)
    finally:
        motor.dispose()
    yield
    try:  # cerrar las conexiones del pool para poder borrar el archivo (Windows)
        asyncio.run(asyncio.wait_for(mem.engine.dispose(), timeout=10))
    except Exception:
        pass
    _borrar_archivos_de_la_base()


async def _recrear_esquema(solo_borrar: bool = False) -> None:
    async with mem.engine.begin() as conn:
        await conn.run_sync(mem.Base.metadata.drop_all)
        if not solo_borrar:
            await conn.run_sync(mem.Base.metadata.create_all)


async def _vaciar_tablas() -> None:
    """DELETE de todas las tablas en orden inverso de dependencias (hijas antes
    que padres) y reinicio de los contadores autoincrement."""
    async with mem.engine.begin() as conn:
        for tabla in reversed(mem.Base.metadata.sorted_tables):
            await conn.execute(tabla.delete())
        hay_secuencias = (
            await conn.execute(sa.text("SELECT 1 FROM sqlite_master WHERE name = 'sqlite_sequence'"))
        ).first()
        if hay_secuencias:
            await conn.execute(sa.text("DELETE FROM sqlite_sequence"))


@pytest_asyncio.fixture(autouse=True)
async def _base_de_datos_limpia(request):
    """Cada test arranca de una base vacía, sin depender del orden de
    ejecución ni de datos que dejó otro test. Ver el encabezado del archivo."""
    if request.node.get_closest_marker("esquema_propio"):
        await _recrear_esquema()
        yield
        await _recrear_esquema()  # deja el esquema creado para los tests siguientes
        return
    try:
        await _vaciar_tablas()
    except sa.exc.OperationalError:
        # Un test anterior dejó el esquema roto (tabla borrada/alterada): se
        # reconstruye completo y se vuelve a vaciar.
        await _recrear_esquema()
        await _vaciar_tablas()
    yield


@pytest.fixture(autouse=True)
def _ia_de_respuestas_escritas_sin_red(monkeypatch):
    """La red de seguridad con IA de la calificación guiada (calificacion_guiada._llamar_ia_interprete) no sale a internet en las pruebas:
    por defecto «no pudo» (el flujo sigue como antes). Las pruebas de la red la reemplazan por un doble."""
    from agent import calificacion_guiada

    async def _sin_red(*args, **kwargs):
        raise RuntimeError("sin red en las pruebas")

    monkeypatch.setattr(calificacion_guiada, "_llamar_ia_interprete", _sin_red)


@pytest.fixture(autouse=True)
def _limitadores_de_tasa_limpios():
    """Los limitadores de agent.rate_limit (webhook: 60 por IP por minuto; login)
    son estado en MEMORIA del proceso, no de la base. Con la recreación del
    esquema por test (≈1,65 s cada una) la suite nunca acumulaba 60 llamadas al
    webhook dentro de un minuto; ahora que cada test tarda décimas de segundo,
    sí, y los tests de webhook empezaban a recibir 429. Se reinician por test,
    igual que la base, para que ninguno dependa de lo que hizo otro ni de la
    velocidad de la máquina."""
    from agent import rate_limit
    for limitador in (rate_limit.limitador_login, rate_limit.limitador_webhook):
        limitador._eventos.clear()
    rate_limit.bloqueo_login._fallos.clear()
    rate_limit.bloqueo_login._bloqueado_hasta.clear()
    rate_limit.bloqueo_cambio_password._fallos.clear()
    rate_limit.bloqueo_cambio_password._bloqueado_hasta.clear()
    from agent.services import servicio_identidad as identidad
    identidad._cambios_recientes.clear()
    yield


@pytest.fixture
def anyio_backend():
    return "asyncio"
