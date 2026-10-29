"""campanas_envio_sms: alcance, nivel, tipo/subtipo y texto del SMS en las campañas de envío de SMS

Revision ID: d8b4f2a6c3e1
Revises: c5e1a7d3f9b2
Create Date: 2026-10-29 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd8b4f2a6c3e1'
down_revision: Union[str, Sequence[str], None] = 'c5e1a7d3f9b2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Columnas nuevas, todas nullable: las campañas existentes quedan exactamente igual (NULL = sin alcance)."""
    op.add_column('campanas', sa.Column('alcance', sa.String(length=20), nullable=True))
    op.add_column('campanas', sa.Column('nivel_producto', sa.String(length=20), nullable=True))
    op.add_column('campanas', sa.Column('tipo_producto', sa.String(length=100), nullable=True))
    op.add_column('campanas', sa.Column('subtipo_producto', sa.String(length=100), nullable=True))
    op.add_column('campanas', sa.Column('texto_sms', sa.String(length=500), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('campanas', 'texto_sms')
    op.drop_column('campanas', 'subtipo_producto')
    op.drop_column('campanas', 'tipo_producto')
    op.drop_column('campanas', 'nivel_producto')
    op.drop_column('campanas', 'alcance')
