"""estimacion de costo de cada envio (capa central de envios, fase B)

Revision ID: c3f8a2e6d1b9
Revises: b7d4e1a9c2f6
Create Date: 2026-10-04 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c3f8a2e6d1b9'
down_revision: Union[str, Sequence[str], None] = 'b7d4e1a9c2f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Tres columnas nullable en una tabla recien creada (envios_meta): lo que la
    # politica de envios estimo antes de enviar. Nada existente cambia.
    op.add_column('envios_meta', sa.Column('categoria_esperada', sa.String(length=30), nullable=True))
    op.add_column('envios_meta', sa.Column('gratis_esperado', sa.Boolean(), nullable=True))
    op.add_column('envios_meta', sa.Column('costo_esperado_usd', sa.Float(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('envios_meta', 'costo_esperado_usd')
    op.drop_column('envios_meta', 'gratis_esperado')
    op.drop_column('envios_meta', 'categoria_esperada')
