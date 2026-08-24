"""agregar fecha_cierre a leads y producto_id a lineas_venta

Revision ID: b7c1f4d92e08
Revises: 9b2c4d7e1a35
Create Date: 2026-08-23 09:10:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b7c1f4d92e08'
down_revision: Union[str, Sequence[str], None] = '9b2c4d7e1a35'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Ambas columnas son nullable y SIN server_default, a propósito y sin
    # backfill (mismo criterio que token_renovado_en/waba_id):
    #
    # - leads.fecha_cierre: solo se conoce el instante real del cierre desde
    #   este cambio en adelante. Un lead ya vendido antes se queda en NULL —
    #   inventarle una fecha (ej. `actualizado`) sería fabricar un dato de
    #   negocio que nadie registró.
    # - lineas_venta.producto_id: las líneas históricas no guardan qué
    #   producto del catálogo se vendió, solo una copia de su descripción, y
    #   CODIGO HANA no es único, así que no hay forma segura de deducirlo.
    #   Además queda nullable de forma permanente: el cierre de venta admite
    #   el modo manual (producto fuera del catálogo).
    op.add_column('leads', sa.Column('fecha_cierre', sa.DateTime(), nullable=True))
    op.add_column('lineas_venta', sa.Column('producto_id', sa.Integer(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('lineas_venta', 'producto_id')
    op.drop_column('leads', 'fecha_cierre')
