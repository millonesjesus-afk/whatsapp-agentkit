"""attribution v2 fase 1 - crear attribution_events

Revision ID: a05737d4c680
Revises: 4642f3d55e15
Create Date: 2026-09-09 13:06:13.384847

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a05737d4c680'
down_revision: Union[str, Sequence[str], None] = '4642f3d55e15'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('attribution_events',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('negocio_id', sa.String(length=36), nullable=False),
    sa.Column('conversation_id', sa.String(length=36), nullable=False),
    sa.Column('lead_telefono', sa.String(length=50), nullable=False),
    sa.Column('tipo_origen', sa.String(length=30), nullable=False),
    sa.Column('referral_raw', sa.JSON(), nullable=True),
    sa.Column('source_id', sa.String(length=200), nullable=True),
    sa.Column('headline', sa.Text(), nullable=True),
    sa.Column('body', sa.Text(), nullable=True),
    sa.Column('ctwa_clid', sa.String(length=200), nullable=True),
    sa.Column('campana_nombre', sa.String(length=100), nullable=True),
    sa.Column('first_touch', sa.Boolean(), nullable=False),
    sa.Column('creado', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['conversation_id'], ['conversations.id'], ),
    sa.ForeignKeyConstraint(['lead_telefono'], ['leads.telefono'], ),
    sa.ForeignKeyConstraint(['negocio_id'], ['negocios.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_attribution_events_conversation_id'), 'attribution_events', ['conversation_id'], unique=False)
    op.create_index(op.f('ix_attribution_events_creado'), 'attribution_events', ['creado'], unique=False)
    op.create_index(op.f('ix_attribution_events_lead_telefono'), 'attribution_events', ['lead_telefono'], unique=False)
    op.create_index(op.f('ix_attribution_events_negocio_id'), 'attribution_events', ['negocio_id'], unique=False)
    op.create_index('ix_attribution_negocio_lead_creado', 'attribution_events', ['negocio_id', 'lead_telefono', 'creado'], unique=False)
    op.create_index('ix_attribution_negocio_tipo', 'attribution_events', ['negocio_id', 'tipo_origen'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_attribution_negocio_tipo', table_name='attribution_events')
    op.drop_index('ix_attribution_negocio_lead_creado', table_name='attribution_events')
    op.drop_index(op.f('ix_attribution_events_negocio_id'), table_name='attribution_events')
    op.drop_index(op.f('ix_attribution_events_lead_telefono'), table_name='attribution_events')
    op.drop_index(op.f('ix_attribution_events_creado'), table_name='attribution_events')
    op.drop_index(op.f('ix_attribution_events_conversation_id'), table_name='attribution_events')
    op.drop_table('attribution_events')
