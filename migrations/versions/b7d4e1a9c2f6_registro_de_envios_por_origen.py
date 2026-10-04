"""registro de envios de WhatsApp por origen (capa central de envios, fase A)

Revision ID: b7d4e1a9c2f6
Revises: a9e3c7d5b1f4
Create Date: 2026-10-04 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b7d4e1a9c2f6'
down_revision: Union[str, Sequence[str], None] = 'a9e3c7d5b1f4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Tabla aditiva: una fila por intento de envio con el origen que lo pidio
    # (gabi_respuesta, reenganche_inactividad, asesor_texto...). Nada existente
    # cambia.
    op.create_table(
        'envios_meta',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('negocio_id', sa.String(length=36), nullable=True),
        sa.Column('origen', sa.String(length=40), nullable=False),
        sa.Column('telefono', sa.String(length=150), nullable=False),
        sa.Column('tipo', sa.String(length=20), nullable=False),
        sa.Column('decision', sa.String(length=20), nullable=False),
        sa.Column('motivo', sa.String(length=200), nullable=True),
        sa.Column('wamid', sa.String(length=100), nullable=True),
        sa.Column('creado', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_envios_meta_negocio_id', 'envios_meta', ['negocio_id'], unique=False)
    op.create_index('ix_envios_meta_wamid', 'envios_meta', ['wamid'], unique=False)
    op.create_index('ix_envios_meta_agrupacion', 'envios_meta', ['negocio_id', 'origen', 'telefono', 'creado'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_envios_meta_agrupacion', table_name='envios_meta')
    op.drop_index('ix_envios_meta_wamid', table_name='envios_meta')
    op.drop_index('ix_envios_meta_negocio_id', table_name='envios_meta')
    op.drop_table('envios_meta')
