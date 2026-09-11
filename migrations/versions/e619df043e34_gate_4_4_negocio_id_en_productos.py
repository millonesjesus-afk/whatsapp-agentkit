"""gate 4.4 negocio_id en productos

Revision ID: e619df043e34
Revises: a819593b429d
Create Date: 2026-09-10 06:30:00.000000

GATE 4.4 — cierra la deuda arquitectónica documentada en Gate 4.3
(tests/test_gate43_analisis_catalogo_riesgo.py): `Producto` no tenía
ningún concepto de tenant, y todas las consultas del catálogo mezclaban
productos de cualquier origen.

EXPAND + BACKFILL + VALIDATE en una sola migración, mismo patrón que
e726728060b8 (Gate 4.2): Cálidda ya existe como Negocio en este punto de
la cadena, así que se resuelve su id por SELECT (nunca se inventa ni se
hardcodea el UUID) y el backfill es no-op si no existe ('calidda') —
ej. una base de datos nueva de test.

El backfill es 100% inequívoco: HOY Cálidda es el único Negocio con
productos reales (confirmado en la auditoría de Gate 4.4), así que TODO
producto existente pertenece a Cálidda sin ambigüedad — a diferencia del
backfill de `mensajes` en a46a93329345, acá no hay ningún caso "huérfano"
posible, pero se verifica igual antes de forzar NOT NULL (mismo criterio
de "no confiar a ciegas", aunque el resultado ya se sepa).

`codigo_hana` NO pasa a ser UNIQUE(negocio_id, codigo_hana): nunca fue
único siquiera dentro de un solo negocio (el catálogo real tiene
productos "EN CREACIÓN" sin código asignado, ver Producto en
agent/memory.py) — no hay ninguna restricción de unicidad que migrar.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e619df043e34'
down_revision: Union[str, Sequence[str], None] = 'a819593b429d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

CODIGO_CALIDDA = 'calidda'


def upgrade() -> None:
    """Upgrade schema + data."""
    bind = op.get_bind()

    # SQLite no soporta ALTER TABLE ADD COLUMN con una constraint (FK)
    # inline — batch mode (copy-and-move) es obligatorio acá, a diferencia
    # de e726728060b8 donde la FK se declaraba en un create_table nuevo.
    with op.batch_alter_table('productos') as batch_op:
        batch_op.add_column(sa.Column(
            'negocio_id', sa.String(length=36),
            sa.ForeignKey('negocios.id', name='fk_productos_negocio_id'), nullable=True,
        ))
    op.create_index('ix_productos_negocio_id', 'productos', ['negocio_id'])

    negocios = sa.table('negocios', sa.column('id', sa.String), sa.column('codigo', sa.String))
    negocio_id = bind.execute(
        sa.select(negocios.c.id).where(negocios.c.codigo == CODIGO_CALIDDA)
    ).scalar()
    if negocio_id is None:
        # Sin Cálidda backfilleada todavía (ej. una base de datos nueva de
        # test) no hay a quién asignarle los productos existentes — no se
        # inventa. La columna queda creada, nullable, vacía.
        return

    bind.execute(
        sa.text("UPDATE productos SET negocio_id = :negocio_id WHERE negocio_id IS NULL"),
        {"negocio_id": negocio_id},
    )

    huerfanos = bind.execute(sa.text("SELECT COUNT(*) FROM productos WHERE negocio_id IS NULL")).scalar()
    if huerfanos:
        raise RuntimeError(
            f"{huerfanos} producto(s) sin negocio_id tras el backfill — no debería ser posible "
            "(Cálidda es el único Negocio con productos hoy). No se fuerza NOT NULL; revisar "
            "manualmente antes de reintentar esta migración (Gate 4.4, regla: no inventar pertenencia)."
        )

    with op.batch_alter_table('productos') as batch_op:
        batch_op.alter_column('negocio_id', existing_type=sa.String(length=36), nullable=False)


def downgrade() -> None:
    """Downgrade schema + data."""
    with op.batch_alter_table('productos') as batch_op:
        batch_op.alter_column('negocio_id', existing_type=sa.String(length=36), nullable=True)
    with op.batch_alter_table('productos') as batch_op:
        batch_op.drop_index('ix_productos_negocio_id')
        batch_op.drop_column('negocio_id')
