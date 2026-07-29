# agent/migraciones.py — Aplicar migraciones de Alembic al arrancar
# Generado por AgentKit

"""
Corre `alembic upgrade head` al arrancar el servidor — reemplaza a
Base.metadata.create_all() como mecanismo de cambio de esquema en
producción (Data Architecture, Fase 1: "A partir de acá, create_all deja
de usarse como mecanismo de cambio en producción").

Se ejecuta como subproceso, no con la API programática de Alembic en el
mismo proceso: el env.py async de Alembic hace su propio asyncio.run()
para correr las migraciones, lo cual falla con "asyncio.run() cannot be
called from a running event loop" si se invoca desde dentro del lifespan
async de FastAPI (que ya tiene un loop corriendo). Un subproceso separado
no tiene ese conflicto — hereda las variables de entorno (DATABASE_URL
incluida) del proceso padre sin necesidad de pasarlas explícitamente.

IMPORTANTE — coordinación con producción: la primera vez que este código
se despliegue, la base de datos de producción ya tiene el esquema actual
(no está vacía). Si `alembic upgrade head` corre ahí sin que la base haya
sido marcada primero como "ya en la versión baseline" (`alembic stamp
head`, ejecutado una sola vez, fuera de este código), Alembic intentará
crear tablas que ya existen y el arranque fallará. Ese `stamp` es un paso
manual, único, que debe ejecutarse contra la base de producción ANTES del
primer deploy que incluya este módulo — no algo que este código pueda
hacer por sí solo con seguridad.
"""

import asyncio
import logging
import sys

logger = logging.getLogger("agentkit")


async def aplicar_migraciones():
    """Corre `alembic upgrade head`. Falla el arranque (no atrapa la
    excepción) si la migración no puede aplicarse — un esquema a medio
    migrar es peor que un despliegue visiblemente roto (mismo criterio
    fail-fast de Fase 0)."""
    proceso = await asyncio.create_subprocess_exec(
        sys.executable, "-m", "alembic", "upgrade", "head",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proceso.communicate()
    if proceso.returncode != 0:
        raise RuntimeError(
            f"alembic upgrade head falló (código {proceso.returncode}): {stderr.decode(errors='replace')}"
        )
    # Alembic no escribe su progreso en stdout por defecto (usa el logger
    # "alembic", configurado por fileConfig) — no se puede inferir de acá
    # si hubo cambios reales o el esquema ya estaba al día, solo que el
    # comando terminó sin error.
    salida = stdout.decode(errors="replace").strip()
    logger.info(f"Migraciones aplicadas (alembic upgrade head, rc=0){f': {salida}' if salida else ''}")
