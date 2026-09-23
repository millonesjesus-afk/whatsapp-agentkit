"""agregar pacto de financiamiento congelado a leads y opportunities

Revision ID: a7c2d4e91b35
Revises: f1e58ada9343
Create Date: 2026-09-23

Gate 2026-09-23 — la cuota se calcula con la TEA/IGV configurables del
negocio, y esa tasa puede cambiar. Para que una venta ya pactada no se
recalcule sola, se congela al cerrarla: monto financiado, cuota mensual
pactada y la TEA/IGV vigentes en ese momento. Lead y Opportunity llevan las
mismas columnas (mirror, mismo patrón que `cuotas`). Todas nullable, sin
backfill: las ventas anteriores no tienen pacto registrado y no se inventa uno.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a7c2d4e91b35'
down_revision: Union[str, Sequence[str], None] = 'f1e58ada9343'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLAS = ('leads', 'opportunities')


def upgrade() -> None:
    for tabla in _TABLAS:
        op.add_column(tabla, sa.Column('monto_financiado', sa.String(30), nullable=True))
        op.add_column(tabla, sa.Column('cuota_pactada', sa.String(30), nullable=True))
        op.add_column(tabla, sa.Column('tea_pactada', sa.String(10), nullable=True))
        op.add_column(tabla, sa.Column('igv_pactado', sa.String(10), nullable=True))


def downgrade() -> None:
    for tabla in _TABLAS:
        for col in ('igv_pactado', 'tea_pactada', 'cuota_pactada', 'monto_financiado'):
            op.drop_column(tabla, col)
