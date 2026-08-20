"""agregar version a productos

Revision ID: 35175f4d063e
Revises: fe7af0de58f1
Create Date: 2026-08-17

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '35175f4d063e'
down_revision: Union[str, Sequence[str], None] = 'fe7af0de58f1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Concurrencia optimista para el catálogo editable, mismo mecanismo que
    # leads.version (ver a2a084de5a76). server_default es necesario acá por
    # el mismo motivo: la tabla productos de producción ya tiene ~360 filas
    # reales y un ADD COLUMN NOT NULL sin default falla en Postgres sobre una
    # tabla no vacía. Todas las filas existentes arrancan en versión 0.
    #
    # Sin batch_alter_table a propósito: es un add_column simple, no cambia
    # el tipo de una columna existente (a diferencia de fe7af0de58f1).
    op.add_column('productos', sa.Column('version', sa.Integer(), nullable=False, server_default='0'))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('productos', 'version')
