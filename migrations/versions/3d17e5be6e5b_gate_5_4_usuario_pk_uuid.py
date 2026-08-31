"""gate 5.4 usuario pk uuid

Revision ID: 3d17e5be6e5b
Revises: 6834f5dd636d
Create Date: 2026-08-31 05:05:42.182640

Gate 5.4 (T3) — migra `Usuario.username` de PK global a `Usuario.id` (UUID),
con `username` único por `(negocio_id, username)` en vez de globalmente
(Arquitectura Integrada Gate 5.4 / Resolución Arquitectónica Gate 5.3, DR-2
ya lo agendaba explícitamente para este Gate). Mismo patrón ya usado en
`e2e0f49996ce` (Configuracion → clave compuesta): recrear la tabla en vez de
un ALTER en el lugar, porque el cambio de PK lo exige en SQLite — portable a
Postgres por consistencia, sin usar `gen_random_uuid()` nativo.

EXPAND + BACKFILL + VALIDATE + CONTRACT en una sola migración: a diferencia
de `66ab4085660a`/`e4d943403e19`/`6834f5dd636d` (Contact/Conversation/
Opportunity), acá no hace falta correlacionar UUIDs entre varias tablas
nuevas — es una tabla única, sin fan-out, así que separar las 4 fases en
archivos distintos no aporta nada (confirmado antes de escribir esto:
ningún FK real apunta a `usuarios.username` en todo el repo — `asesor_asignado`
en `leads` y `conversations.asesor_asignado_id` son `String` sueltos por
diseño, ver comentario de la clase `Usuario` en `agent/memory.py` — la
migración no tiene cascada que reparar).

VALIDATE (antes de Contract): cero `id` NULL, cero duplicados de `id`,
misma cantidad de filas que la tabla original, ningún usuario perdido. Si
alguna de esas comprobaciones falla, la migración se detiene con
`RuntimeError` — no se inventa nada.
"""
from typing import Sequence, Union
import uuid

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '3d17e5be6e5b'
down_revision: Union[str, Sequence[str], None] = '6834f5dd636d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema + data."""
    bind = op.get_bind()

    usuarios = bind.execute(sa.text(
        "SELECT username, password_hash, nombre, rol, nivel, disponible, negocio_id "
        "FROM usuarios"
    )).mappings().all()

    total_original = len(usuarios)

    # EXPAND — tabla nueva con id UUID como PK real, username+negocio_id
    # únicos (no global). Nombre temporal para no chocar con la existente
    # mientras se copian los datos.
    op.create_table(
        'usuarios_nueva',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('username', sa.String(length=50), nullable=False),
        sa.Column('password_hash', sa.String(length=200), nullable=False),
        sa.Column('nombre', sa.String(length=100), nullable=False),
        sa.Column('rol', sa.String(length=20), nullable=False),
        sa.Column('nivel', sa.String(length=20), nullable=True),
        sa.Column('disponible', sa.Boolean(), nullable=False),
        sa.Column('negocio_id', sa.String(length=36), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['negocio_id'], ['negocios.id']),
    )

    # BACKFILL — un id UUID nuevo por fila existente. Python, no SQL puro
    # (mismo motivo que 6834f5dd636d): gen_random_uuid() no es portable
    # entre SQLite y Postgres sin round-trip a la aplicación.
    ids_generados: set[str] = set()
    for u in usuarios:
        nuevo_id = str(uuid.uuid4())
        ids_generados.add(nuevo_id)
        bind.execute(
            sa.text(
                "INSERT INTO usuarios_nueva "
                "(id, username, password_hash, nombre, rol, nivel, disponible, negocio_id) "
                "VALUES (:id, :username, :password_hash, :nombre, :rol, :nivel, :disponible, :negocio_id)"
            ),
            {
                "id": nuevo_id, "username": u["username"], "password_hash": u["password_hash"],
                "nombre": u["nombre"], "rol": u["rol"], "nivel": u["nivel"],
                "disponible": u["disponible"], "negocio_id": u["negocio_id"],
            },
        )

    # VALIDATE — cero perdidos, cero ids NULL/duplicados, misma cardinalidad.
    total_nuevo = bind.execute(sa.text("SELECT COUNT(*) FROM usuarios_nueva")).scalar_one()
    if total_nuevo != total_original:
        raise RuntimeError(
            f"gate 5.4 usuario pk uuid: {total_original} usuarios en la tabla original, "
            f"{total_nuevo} copiados a usuarios_nueva — no coincide, abortando sin tocar la tabla real."
        )
    if len(ids_generados) != total_original:
        raise RuntimeError(
            "gate 5.4 usuario pk uuid: colisión de UUID generados (extremadamente improbable) "
            "— abortando sin tocar la tabla real."
        )
    nulos = bind.execute(sa.text("SELECT COUNT(*) FROM usuarios_nueva WHERE id IS NULL")).scalar_one()
    if nulos:
        raise RuntimeError(f"gate 5.4 usuario pk uuid: {nulos} filas con id NULL tras el backfill — abortando.")

    # CONTRACT — la tabla nueva reemplaza a la vieja; username+negocio_id
    # únicos (mismo patrón que Contact.negocio_id+telefono, Gate 5.3).
    op.drop_table('usuarios')
    op.rename_table('usuarios_nueva', 'usuarios')

    op.create_index('ix_usuario_negocio_id', 'usuarios', ['negocio_id'])
    op.create_index('ix_usuario_negocio_username', 'usuarios', ['negocio_id', 'username'], unique=True)


def downgrade() -> None:
    """Downgrade schema."""
    bind = op.get_bind()

    usuarios = bind.execute(sa.text(
        "SELECT username, password_hash, nombre, rol, nivel, disponible, negocio_id "
        "FROM usuarios ORDER BY username"
    )).mappings().all()

    # Si dos filas comparten username (posible solo si, entre el upgrade y
    # este downgrade, se llegó a crear un segundo Negocio con un username ya
    # usado por otro) no hay forma de volver a la PK vieja sin perder una de
    # las dos — se detiene en vez de perder datos en silencio.
    usernames = [u["username"] for u in usuarios]
    if len(usernames) != len(set(usernames)):
        raise RuntimeError(
            "gate 5.4 usuario pk uuid (downgrade): existen usernames duplicados entre Negocios — "
            "la PK vieja (username global) no puede representarlos a todos. Resolver manualmente "
            "la colisión antes de hacer downgrade."
        )

    op.create_table(
        'usuarios_vieja',
        sa.Column('username', sa.String(length=50), nullable=False),
        sa.Column('password_hash', sa.String(length=200), nullable=False),
        sa.Column('nombre', sa.String(length=100), nullable=False),
        sa.Column('rol', sa.String(length=20), nullable=False),
        sa.Column('nivel', sa.String(length=20), nullable=True),
        sa.Column('disponible', sa.Boolean(), nullable=False),
        sa.Column('negocio_id', sa.String(length=36), nullable=False),
        sa.PrimaryKeyConstraint('username'),
        sa.ForeignKeyConstraint(['negocio_id'], ['negocios.id']),
    )
    for u in usuarios:
        bind.execute(
            sa.text(
                "INSERT INTO usuarios_vieja "
                "(username, password_hash, nombre, rol, nivel, disponible, negocio_id) "
                "VALUES (:username, :password_hash, :nombre, :rol, :nivel, :disponible, :negocio_id)"
            ),
            dict(u),
        )
    op.drop_index('ix_usuario_negocio_username', table_name='usuarios')
    op.drop_index('ix_usuario_negocio_id', table_name='usuarios')
    op.drop_table('usuarios')
    op.rename_table('usuarios_vieja', 'usuarios')
