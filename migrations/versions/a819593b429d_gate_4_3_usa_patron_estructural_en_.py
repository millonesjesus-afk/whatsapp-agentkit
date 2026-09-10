"""gate 4.3 usa patron estructural en identidad agente

Revision ID: a819593b429d
Revises: e726728060b8
Create Date: 2026-09-09 23:52:26.566677

GATE 4.3 — activación controlada y reversible del ensamblador (patrón
estructural + configuración de negocio) para `IdentidadAgente`. Columna
nueva con `server_default=false`: ningún Negocio existente cambia de
comportamiento solo por aplicarse esta migración — `configuracion_negocio`
(el baseline verbatim de cada Negocio) queda completamente intacto, y
`obtener_system_prompt()` sigue devolviéndolo tal cual mientras esta
columna sea False (ver `agent/brain.py`).

Sin backfill de datos — activar para un Negocio puntual (hoy, Cálidda,
solo en validación local) es una acción explícita y separada
(`activar_patron_estructural(negocio_id, True)`), nunca algo que esta
migración decida por su cuenta.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a819593b429d'
down_revision: Union[str, Sequence[str], None] = 'e726728060b8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('identidades_agente') as batch_op:
        batch_op.add_column(
            sa.Column('usa_patron_estructural', sa.Boolean(), nullable=False, server_default=sa.false())
        )


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('identidades_agente') as batch_op:
        batch_op.drop_column('usa_patron_estructural')
