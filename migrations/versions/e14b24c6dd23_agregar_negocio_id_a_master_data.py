"""agregar negocio_id a master data

Revision ID: e14b24c6dd23
Revises: 61836c757b25
Create Date: 2026-08-27 23:03:31.000000

Gate 5.2 — EXPAND: agrega `negocio_id` (nullable, se puebla en la migración
de backfill siguiente) a leads, usuarios, canales_whatsapp, campanas y
mensajes — el primer nivel de aislamiento estructural definido en la
Arquitectura Contractual de Gate 5.1. También agrega `unidad_id` (nullable,
sin fecha de cierre — las Unidades reales de Cálidda son dato de negocio
pendiente, no se inventan) a canales_whatsapp y campanas.

Lead.telefono NO se toca como PK — esa separación es Gate 5.3.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e14b24c6dd23'
down_revision: Union[str, Sequence[str], None] = '61836c757b25'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('leads', sa.Column('negocio_id', sa.String(length=36), nullable=True))
    op.create_index('ix_leads_negocio_id', 'leads', ['negocio_id'])

    op.add_column('usuarios', sa.Column('negocio_id', sa.String(length=36), nullable=True))
    op.create_index('ix_usuarios_negocio_id', 'usuarios', ['negocio_id'])

    op.add_column('canales_whatsapp', sa.Column('negocio_id', sa.String(length=36), nullable=True))
    op.add_column('canales_whatsapp', sa.Column('unidad_id', sa.String(length=36), nullable=True))
    op.create_index('ix_canales_whatsapp_negocio_id', 'canales_whatsapp', ['negocio_id'])

    op.add_column('campanas', sa.Column('negocio_id', sa.String(length=36), nullable=True))
    op.add_column('campanas', sa.Column('unidad_id', sa.String(length=36), nullable=True))
    op.create_index('ix_campanas_negocio_id', 'campanas', ['negocio_id'])

    op.add_column('mensajes', sa.Column('negocio_id', sa.String(length=36), nullable=True))
    op.create_index('ix_mensajes_negocio_id', 'mensajes', ['negocio_id'])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_mensajes_negocio_id', table_name='mensajes')
    op.drop_column('mensajes', 'negocio_id')

    op.drop_index('ix_campanas_negocio_id', table_name='campanas')
    op.drop_column('campanas', 'unidad_id')
    op.drop_column('campanas', 'negocio_id')

    op.drop_index('ix_canales_whatsapp_negocio_id', table_name='canales_whatsapp')
    op.drop_column('canales_whatsapp', 'unidad_id')
    op.drop_column('canales_whatsapp', 'negocio_id')

    op.drop_index('ix_usuarios_negocio_id', table_name='usuarios')
    op.drop_column('usuarios', 'negocio_id')

    op.drop_index('ix_leads_negocio_id', table_name='leads')
    op.drop_column('leads', 'negocio_id')
