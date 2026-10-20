"""etiquetas_grupo_anuncio: empresa de cada grupo de anuncios (Rendimiento por anuncio)

Revision ID: b7e3c9a5d1f4
Revises: a9c4e1d7b3f2
Create Date: 2026-10-19 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b7e3c9a5d1f4'
down_revision: Union[str, Sequence[str], None] = 'a9c4e1d7b3f2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Tabla nueva, aditiva: no toca ningun dato existente."""
    op.create_table(
        'etiquetas_grupo_anuncio',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('negocio_id', sa.String(length=36), nullable=False),
        sa.Column('clave_grupo', sa.String(length=40), nullable=False),
        sa.Column('empresa', sa.String(length=60), nullable=False),
        sa.Column('actualizado', sa.DateTime(), nullable=False),
        sa.Column('actualizado_por', sa.String(length=50), nullable=True),
        sa.ForeignKeyConstraint(['negocio_id'], ['negocios.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_etiqueta_grupo_anuncio_negocio_id', 'etiquetas_grupo_anuncio', ['negocio_id'], unique=False)
    op.create_index(
        'ix_etiqueta_grupo_anuncio_negocio_clave', 'etiquetas_grupo_anuncio', ['negocio_id', 'clave_grupo'], unique=True,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_etiqueta_grupo_anuncio_negocio_clave', table_name='etiquetas_grupo_anuncio')
    op.drop_index('ix_etiqueta_grupo_anuncio_negocio_id', table_name='etiquetas_grupo_anuncio')
    op.drop_table('etiquetas_grupo_anuncio')
