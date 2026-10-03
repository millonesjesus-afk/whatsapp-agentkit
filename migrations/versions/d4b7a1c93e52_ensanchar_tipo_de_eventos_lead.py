"""ensanchar eventos_lead.tipo de 30 a 60 caracteres

Revision ID: d4b7a1c93e52
Revises: 3a9fea397640
Create Date: 2026-10-03 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd4b7a1c93e52'
down_revision: Union[str, Sequence[str], None] = '3a9fea397640'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # 2026-10-02: en Postgres, `cerrado_definitivamente_automatico` (34) y
    # `rotado_automatico_sin_respuesta` (31) no cabían en VARCHAR(30) y los
    # Cron de cierre/rotación caían al registrar su evento. SQLite no impone
    # el largo, así que los tests no lo vieron. Solo se ensancha: no cambia
    # ningún dato ni ningún nombre de evento (el frontend los lee tal cual).
    with op.batch_alter_table('eventos_lead') as batch_op:
        batch_op.alter_column(
            'tipo', existing_type=sa.String(length=30), type_=sa.String(length=60), existing_nullable=False,
        )


def downgrade() -> None:
    """Downgrade schema."""
    # Deliberadamente sin efecto: volver a 30 haría fallar la migración (o
    # truncaría) en cuanto exista un evento con un tipo largo, y el modelo
    # ensanchado es compatible hacia atrás con cualquier valor anterior.
    pass
