"""Copia los usuarios REALES (no cuentas demo/prueba) de la base de datos
local hacia el Postgres de Railway, preservando el hash de contraseña tal
cual — nadie tiene que resetear su contraseña por el deploy.

Uso (después de agregar el plugin de Postgres en Railway y copiar su
DATABASE_URL desde la pestaña "Variables" del servicio Postgres):

    DATABASE_URL_DESTINO="postgresql://usuario:clave@host:puerto/db" \
        python scripts/migrar_usuarios_a_railway.py
"""
import asyncio
import os
import sqlite3

from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from agent.memory import Base, Usuario

USUARIOS_A_EXCLUIR = {"asesor_demo", "supervisor_demo", "debug_temp", "debug_temp_asesor"}


async def main():
    destino_url = os.environ.get("DATABASE_URL_DESTINO")
    if not destino_url:
        raise SystemExit("Falta la variable DATABASE_URL_DESTINO (el connection string de Postgres de Railway).")
    if destino_url.startswith("postgresql://"):
        destino_url = destino_url.replace("postgresql://", "postgresql+asyncpg://", 1)

    conn = sqlite3.connect("agentkit.db")
    cur = conn.cursor()
    cur.execute("SELECT username, password_hash, nombre, rol, nivel, disponible FROM usuarios")
    filas = [f for f in cur.fetchall() if f[0] not in USUARIOS_A_EXCLUIR]
    conn.close()

    if not filas:
        print("No hay usuarios reales para copiar.")
        return

    engine = create_async_engine(destino_url, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as session:
        for username, password_hash, nombre, rol, nivel, disponible in filas:
            existente = await session.get(Usuario, username)
            if existente is not None:
                print(f"  - {username}: ya existe en destino, se omite")
                continue
            session.add(Usuario(
                username=username, password_hash=password_hash, nombre=nombre,
                rol=rol, nivel=nivel, disponible=bool(disponible),
            ))
            print(f"  - {username} ({nombre}, {rol}): copiado")
        await session.commit()

    await engine.dispose()
    print(f"Listo — {len(filas)} usuario(s) revisado(s).")


if __name__ == "__main__":
    asyncio.run(main())
