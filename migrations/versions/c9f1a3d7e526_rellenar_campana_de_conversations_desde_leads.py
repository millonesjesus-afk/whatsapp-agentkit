"""rellenar conversations.campana_origen_id desde leads.campana_origen

Revision ID: c9f1a3d7e526
Revises: b8e4c2a6d913
Create Date: 2026-09-21

Desde la migración del Gate 5.3 la detección de campañas solo guardaba el
nombre en `leads.campana_origen` y nunca `conversations.campana_origen_id`,
que es lo que cuenta la Analítica: toda campaña salía en 0. Esta migración
copia la campaña del lead a la PRIMERA conversación de su contacto (el
first-touch), solo donde falta; nunca pisa una campaña ya asignada.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c9f1a3d7e526'
down_revision: Union[str, Sequence[str], None] = 'b8e4c2a6d913'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_CAMPANA_DEL_LEAD = """
SELECT ca.id FROM campanas ca
JOIN leads l ON l.negocio_id = ca.negocio_id AND l.campana_origen = ca.nombre
JOIN contacts ct ON ct.negocio_id = l.negocio_id AND ct.telefono = l.telefono
WHERE ct.id = conversations.contact_id
"""

SQL_RELLENAR_CAMPANAS = f"""
UPDATE conversations
SET campana_origen_id = ({_CAMPANA_DEL_LEAD} LIMIT 1)
WHERE campana_origen_id IS NULL
AND creado = (SELECT MIN(c2.creado) FROM conversations c2 WHERE c2.contact_id = conversations.contact_id)
AND EXISTS ({_CAMPANA_DEL_LEAD})
"""


def upgrade() -> None:
    op.get_bind().execute(sa.text(SQL_RELLENAR_CAMPANAS))


def downgrade() -> None:
    # No se distingue cuáles se rellenaron acá; dejarlas no rompe nada.
    pass
