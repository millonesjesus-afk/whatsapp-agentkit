"""ampliar configuracion.clave de 50 a 100 caracteres

Revision ID: e5a1c8f3b2d7
Revises: c3f8a2e6d1b9
Create Date: 2026-10-05 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e5a1c8f3b2d7'
down_revision: Union[str, Sequence[str], None] = 'c3f8a2e6d1b9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # La clave del uso previo de cuota (`meta_uso_previo_servicio_AAAA-MM:<phone_number_id>`)
    # medía 49 de 50 caracteres: un phone_number_id mas largo habria fallado en
    # Postgres (SQLite no impone el largo y no lo habria detectado). Ampliar un
    # VARCHAR en Postgres es solo un cambio de metadatos. En SQLite no hace
    # falta: no valida longitudes (y reconstruir la tabla perderia los indices
    # unicos parciales).
    if op.get_bind().dialect.name == 'sqlite':
        return
    op.alter_column('configuracion', 'clave', existing_type=sa.String(length=50), type_=sa.String(length=100), existing_nullable=False)


def downgrade() -> None:
    """Downgrade schema."""
    # No-op a proposito: acortar fallaria si ya hay claves de mas de 50 caracteres.
    pass
