"""metas_ventas: metas mensuales de Analítica (total del negocio y por asesor)

Revision ID: c5e1a7d3f9b2
Revises: b7e3c9a5d1f4
Create Date: 2026-10-27 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c5e1a7d3f9b2'
down_revision: Union[str, Sequence[str], None] = 'b7e3c9a5d1f4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Tabla nueva, aditiva: no toca ningun dato existente. `asesor` vacío = meta total del negocio."""
    op.create_table(
        'metas_ventas',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('negocio_id', sa.String(length=36), nullable=False),
        sa.Column('mes', sa.String(length=7), nullable=False),
        sa.Column('asesor', sa.String(length=50), nullable=False, server_default=''),
        sa.Column('tipo', sa.String(length=10), nullable=False, server_default='ventas'),
        sa.Column('objetivo', sa.Float(), nullable=False),
        sa.Column('actualizado', sa.DateTime(), nullable=False),
        sa.Column('actualizado_por', sa.String(length=50), nullable=True),
        sa.ForeignKeyConstraint(['negocio_id'], ['negocios.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_metas_ventas_negocio_id', 'metas_ventas', ['negocio_id'], unique=False)
    op.create_index(
        'ix_metas_ventas_negocio_mes_asesor_tipo', 'metas_ventas', ['negocio_id', 'mes', 'asesor', 'tipo'], unique=True,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_metas_ventas_negocio_mes_asesor_tipo', table_name='metas_ventas')
    op.drop_index('ix_metas_ventas_negocio_id', table_name='metas_ventas')
    op.drop_table('metas_ventas')
