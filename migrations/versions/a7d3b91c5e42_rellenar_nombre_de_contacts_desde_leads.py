"""rellenar contacts.nombre desde leads.nombre

Revision ID: a7d3b91c5e42
Revises: f3a8c1d6e924
Create Date: 2026-09-21

La Bandeja de Conversaciones lee el nombre de `contacts.nombre`, pero Gabi y el
panel solo escribían `leads.nombre`, así que los contactos existentes quedaron
sin nombre. Esta migración copia el nombre del lead (mismo negocio y teléfono)
a los contactos que no tienen uno; nunca pisa un nombre ya presente.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a7d3b91c5e42'
down_revision: Union[str, Sequence[str], None] = 'f3a8c1d6e924'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SQL_RELLENAR_NOMBRES = """
UPDATE contacts
SET nombre = (
    SELECT l.nombre FROM leads l
    WHERE l.negocio_id = contacts.negocio_id AND l.telefono = contacts.telefono
)
WHERE (nombre IS NULL OR nombre = '')
AND EXISTS (
    SELECT 1 FROM leads l
    WHERE l.negocio_id = contacts.negocio_id AND l.telefono = contacts.telefono
    AND l.nombre IS NOT NULL AND l.nombre <> ''
)
"""


def upgrade() -> None:
    op.get_bind().execute(sa.text(SQL_RELLENAR_NOMBRES))


def downgrade() -> None:
    # No hay forma de distinguir qué nombres se rellenaron acá de los que ya
    # existían; dejarlos no rompe nada.
    pass
