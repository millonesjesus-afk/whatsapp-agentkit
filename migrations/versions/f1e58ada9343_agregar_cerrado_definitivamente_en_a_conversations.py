"""agregar cerrado_definitivamente_en a conversations

Revision ID: f1e58ada9343
Revises: d3571f130326
Create Date: 2026-09-23

Gate 2026-09-23 (continuación) — mirror get-only de `Lead.cerrado_definitivamente_en`
hacia `Conversation`, mismo patrón ya existente para `pausado_manual`/
`asesor_asignado_id`: la Nueva Experiencia (ficha-lead.tsx, panel-chat.tsx)
lee y opera sobre Conversation, no sobre Lead directamente (Gate 5.3 cutover
real) — sin esta columna, el endpoint conversation-scoped no tiene dónde
reflejar el cierre. nullable=True, sin backfill, mismo criterio que la
migración anterior (d3571f130326).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'f1e58ada9343'
down_revision: Union[str, Sequence[str], None] = 'd3571f130326'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('conversations', sa.Column('cerrado_definitivamente_en', sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_column('conversations', 'cerrado_definitivamente_en')
