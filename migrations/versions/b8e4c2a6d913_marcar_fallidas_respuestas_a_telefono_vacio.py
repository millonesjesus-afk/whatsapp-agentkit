"""marcar como fallidas las respuestas de Gabi a un telefono vacio

Revision ID: b8e4c2a6d913
Revises: a7d3b91c5e42
Create Date: 2026-09-21

Un mensaje entrante sin `from` creó un lead con teléfono vacío; Meta rechazó
cada respuesta de Gabi ("The parameter to is required") y el panel las mostró
como enviadas. Con teléfono vacío ninguna pudo entregarse, así que se marcan
como fallidas. No toca ningún mensaje con teléfono real.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b8e4c2a6d913'
down_revision: Union[str, Sequence[str], None] = 'a7d3b91c5e42'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SQL_MARCAR_FALLIDAS = """
UPDATE mensajes
SET estado_envio = 'fallido'
WHERE telefono = '' AND role = 'assistant' AND estado_envio IS NULL AND via_app = false
"""


def upgrade() -> None:
    op.get_bind().execute(sa.text(SQL_MARCAR_FALLIDAS))


def downgrade() -> None:
    # No se distingue cuáles se marcaron acá; dejarlas como están no rompe nada.
    pass
