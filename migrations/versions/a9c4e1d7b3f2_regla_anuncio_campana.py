"""anuncio_campana: regla explicita anuncio de Meta -> campana

Revision ID: a9c4e1d7b3f2
Revises: d1a4c7e92b58
Create Date: 2026-10-13 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a9c4e1d7b3f2'
down_revision: Union[str, Sequence[str], None] = 'd1a4c7e92b58'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Tabla nueva, aditiva: no toca ningun dato existente."""
    op.create_table(
        'anuncio_campana',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('negocio_id', sa.String(length=36), nullable=False),
        sa.Column('source_id', sa.String(length=200), nullable=False),
        sa.Column('campana_id', sa.Integer(), nullable=False),
        sa.Column('creado', sa.DateTime(), nullable=False),
        sa.Column('creado_por', sa.String(length=50), nullable=True),
        sa.ForeignKeyConstraint(['negocio_id'], ['negocios.id']),
        sa.ForeignKeyConstraint(['campana_id'], ['campanas.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_anuncio_campana_negocio_id', 'anuncio_campana', ['negocio_id'], unique=False)
    op.create_index('ix_anuncio_campana_negocio_source', 'anuncio_campana', ['negocio_id', 'source_id'], unique=True)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_anuncio_campana_negocio_source', table_name='anuncio_campana')
    op.drop_index('ix_anuncio_campana_negocio_id', table_name='anuncio_campana')
    op.drop_table('anuncio_campana')
