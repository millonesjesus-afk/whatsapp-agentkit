"""agregar cerrado_definitivamente_en a leads

Revision ID: d3571f130326
Revises: afd93064ba83
Create Date: 2026-09-23

Gate 2026-09-23 — nuevo concepto, separado de `resultado`: un cierre
EXPLÍCITO (manual desde la Ficha del Lead, o automático tras 7 días de
silencio del cliente sobre un resultado ya cerrado) que reemplaza al
"resultado en RESULTADOS_CERRADOS" como gatillo de "Gabi retoma la
atención" en agent/main.py — ver Mapped[...] en agent/memory.py para el
porqué completo. nullable=True, sin backfill: los leads ya cerrados hoy se
quedan en NULL (no reactivan a Gabi automáticamente hasta que alguien los
cierre a mano o pase el cron), mismo criterio que otras columnas nuevas
de este proyecto (ej. token_renovado_en).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'd3571f130326'
down_revision: Union[str, Sequence[str], None] = 'afd93064ba83'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('leads', sa.Column('cerrado_definitivamente_en', sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_column('leads', 'cerrado_definitivamente_en')
