# tests/conftest.py — Fixtures de aislamiento de BD para los tests de Gate 5.2.
#
# Fuerza DATABASE_URL/CANAL_ENCRYPTION_KEY a valores de prueba ANTES de que
# cualquier test importe agent.memory (que crea su engine/async_session a
# nivel de módulo, leyendo esas variables al importarse) — así los tests
# nunca tocan agentkit.db (la base de desarrollo real) ni requieren que el
# desarrollador tenga configurado un .env local.

import os
import asyncio
import tempfile

os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{tempfile.gettempdir()}/gate52_test.db"
os.environ.setdefault("CANAL_ENCRYPTION_KEY", "zzqUtYlDYe2FxH5yL9P1WTjMESEVFO3lShs7An_E73g=")

import pytest
import pytest_asyncio

from agent import memory as mem


@pytest_asyncio.fixture(autouse=True)
async def _base_de_datos_limpia():
    """Recrea el esquema completo (todas las tablas de Base.metadata, ya
    con los modelos de Gate 5.2 incluidos) antes de CADA test, y lo borra
    después — cada test arranca de una base vacía, sin depender del orden
    de ejecución ni de datos que dejó otro test."""
    async with mem.engine.begin() as conn:
        await conn.run_sync(mem.Base.metadata.drop_all)
        await conn.run_sync(mem.Base.metadata.create_all)
    yield
    async with mem.engine.begin() as conn:
        await conn.run_sync(mem.Base.metadata.drop_all)


@pytest.fixture
def anyio_backend():
    return "asyncio"
