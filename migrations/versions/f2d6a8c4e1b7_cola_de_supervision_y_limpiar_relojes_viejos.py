"""cola de supervision y limpieza de relojes de espera viejos

Revision ID: f2d6a8c4e1b7
Revises: e8c2f4a1b6d9
Create Date: 2026-10-04 00:00:00.000000

"""
from datetime import datetime
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f2d6a8c4e1b7'
down_revision: Union[str, Sequence[str], None] = 'e8c2f4a1b6d9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# La versión anterior del mecanismo (v1, 2026-09-29 19:00 a 2026-09-30 05:20 UTC,
# cuando se pausó el Cron) escribía en `espera_medida_desde` el instante del
# último mensaje del cliente de cada lead con asesor. La migración 3a9fea397640
# renombró esa columna a `derivado_en` suponiendo que estaba vacía; no lo
# estaba, y esos valores viejos se leyeron como "relojes armados": en la primera
# corrida del Cron de 5 minutos (2026-10-03 08:45 Lima) se liberó a Gabi un lead
# con resultado "Agendado". El rediseño solo escribe `derivado_en` al asignar
# automáticamente, o sea siempre DESPUÉS de este corte.
CORTE_RELOJES_VIEJOS = datetime(2026, 9, 30, 6, 0, 0)

# Expuesta como constante para que un test pueda ejecutar EXACTAMENTE esta
# sentencia sobre datos de prueba.
SQL_LIMPIEZA_RELOJES = (
    "UPDATE leads SET derivado_en = NULL, minutos_espera_asesor = 0, veces_rotado_espera = 0 "
    "WHERE derivado_en IS NOT NULL AND ("
    "derivado_en < :corte OR (resultado IS NOT NULL AND resultado <> ''))"
)


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('leads', sa.Column('escalado_supervision_en', sa.DateTime(), nullable=True))

    # Apaga los relojes de espera que no nacieron de una derivación real, y los
    # de cualquier lead que ya tenga resultado (una persona ya lo trabajó).
    op.execute(sa.text(SQL_LIMPIEZA_RELOJES).bindparams(corte=CORTE_RELOJES_VIEJOS))


def downgrade() -> None:
    """Downgrade schema."""
    # La limpieza de relojes no se deshace (no hay forma de saber qué valor
    # tenía cada uno ni sería correcto restaurarlo).
    op.drop_column('leads', 'escalado_supervision_en')
