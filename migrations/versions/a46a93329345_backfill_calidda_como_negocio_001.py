"""backfill calidda como negocio 001

Revision ID: a46a93329345
Revises: e14b24c6dd23
Create Date: 2026-08-27 23:03:38.000000

Gate 5.2 — BACKFILL + VALIDATE. Crea la fila de `Negocio` correspondiente a
Cálidda (primer Negocio real de Maiek AI, sin arquitectura especial — mismo
código común que usará cualquier Negocio futuro) y puebla `negocio_id` en
leads/usuarios/canales_whatsapp/campanas/mensajes con ese id.

`unidad_id` NO se backfillea acá — las Unidades de Negocio reales de Cálidda
son dato de negocio pendiente (ver informe de cierre de Gate 5.2, sección
"Cálidda"): no se inventa ninguna Unidad solo para llenar la FK.

Tras el backfill, esta migración fija `negocio_id` como NOT NULL en las 5
tablas — verificado contra la base local antes de escribir esta migración
que el backfill es 100% inequívoco (cero registros huérfanos). Esa misma
verificación de "cero huérfanos" debe repetirse independientemente contra
los datos reales de producción antes de que esta migración se aplique ahí
(fuera del alcance de este Gate — no se ejecuta contra producción).
"""
from typing import Sequence, Union
import uuid

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a46a93329345'
down_revision: Union[str, Sequence[str], None] = 'e14b24c6dd23'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

CODIGO_CALIDDA = 'calidda'


def upgrade() -> None:
    """Upgrade schema + data."""
    bind = op.get_bind()

    negocios = sa.table(
        'negocios',
        sa.column('id', sa.String), sa.column('nombre', sa.String), sa.column('codigo', sa.String),
        sa.column('activo', sa.Boolean), sa.column('creado', sa.DateTime), sa.column('actualizado', sa.DateTime),
    )

    negocio_id = str(uuid.uuid4())
    ahora = sa.func.now()
    bind.execute(
        negocios.insert().values(
            id=negocio_id, nombre='Cálidda', codigo=CODIGO_CALIDDA, activo=True,
            creado=sa.func.current_timestamp(), actualizado=sa.func.current_timestamp(),
        )
    )

    # Backfill directo: hoy TODO registro existente en estas 5 tablas
    # pertenece a Cálidda (único Negocio real operando) — sin ambigüedad.
    for tabla in ('leads', 'usuarios', 'canales_whatsapp', 'campanas'):
        bind.execute(sa.text(f"UPDATE {tabla} SET negocio_id = :negocio_id WHERE negocio_id IS NULL"), {"negocio_id": negocio_id})

    # mensajes: negocio_id se resuelve vía Lead.telefono (subquery
    # correlacionada — portable entre SQLite y Postgres, a diferencia de
    # UPDATE...FROM que tiene sintaxis distinta en cada uno). Un mensaje
    # cuyo telefono ya no tiene un Lead correspondiente queda sin backfillear
    # (no se le asigna Cálidda a ciegas) — se verifica después que no haya
    # casos así.
    bind.execute(sa.text(
        "UPDATE mensajes SET negocio_id = "
        "(SELECT negocio_id FROM leads WHERE leads.telefono = mensajes.telefono) "
        "WHERE negocio_id IS NULL"
    ))

    huerfanos = bind.execute(sa.text("SELECT COUNT(*) FROM mensajes WHERE negocio_id IS NULL")).scalar()
    if huerfanos:
        raise RuntimeError(
            f"{huerfanos} mensaje(s) sin Lead correspondiente — no se puede completar el "
            "backfill de forma inequívoca. No se fuerza NOT NULL; revisar manualmente "
            "antes de reintentar esta migración (Gate 5.2, regla: no inventar pertenencia)."
        )

    # VALIDATE: NOT NULL solo donde el backfill es 100% inequívoco (verificado
    # arriba). unidad_id NO se toca — sigue nullable indefinidamente hasta
    # que existan Unidades reales.
    with op.batch_alter_table('leads') as batch_op:
        batch_op.alter_column('negocio_id', existing_type=sa.String(length=36), nullable=False)
    with op.batch_alter_table('usuarios') as batch_op:
        batch_op.alter_column('negocio_id', existing_type=sa.String(length=36), nullable=False)
    with op.batch_alter_table('canales_whatsapp') as batch_op:
        batch_op.alter_column('negocio_id', existing_type=sa.String(length=36), nullable=False)
    with op.batch_alter_table('campanas') as batch_op:
        batch_op.alter_column('negocio_id', existing_type=sa.String(length=36), nullable=False)
    with op.batch_alter_table('mensajes') as batch_op:
        batch_op.alter_column('negocio_id', existing_type=sa.String(length=36), nullable=False)


def downgrade() -> None:
    """Downgrade schema + data."""
    with op.batch_alter_table('mensajes') as batch_op:
        batch_op.alter_column('negocio_id', existing_type=sa.String(length=36), nullable=True)
    with op.batch_alter_table('campanas') as batch_op:
        batch_op.alter_column('negocio_id', existing_type=sa.String(length=36), nullable=True)
    with op.batch_alter_table('canales_whatsapp') as batch_op:
        batch_op.alter_column('negocio_id', existing_type=sa.String(length=36), nullable=True)
    with op.batch_alter_table('usuarios') as batch_op:
        batch_op.alter_column('negocio_id', existing_type=sa.String(length=36), nullable=True)
    with op.batch_alter_table('leads') as batch_op:
        batch_op.alter_column('negocio_id', existing_type=sa.String(length=36), nullable=True)

    bind = op.get_bind()
    for tabla in ('leads', 'usuarios', 'canales_whatsapp', 'campanas', 'mensajes'):
        bind.execute(sa.text(f"UPDATE {tabla} SET negocio_id = NULL"))
    bind.execute(sa.text("DELETE FROM negocios WHERE codigo = :codigo"), {"codigo": CODIGO_CALIDDA})
