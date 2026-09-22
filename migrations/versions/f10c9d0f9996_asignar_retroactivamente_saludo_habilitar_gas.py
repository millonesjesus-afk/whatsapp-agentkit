"""asignar retroactivamente conversaciones con el saludo corregido de habilitar gas

Revision ID: f10c9d0f9996
Revises: c9f1a3d7e526
Create Date: 2026-09-22

El patrón de la campaña "SMS Clientes próximos a habilitar gas" se corrigió
recién el 2026-09-21 (commit eed20ae) para coincidir con el saludo real de
esa SMS ("Pronto habilitarán mi servicio de gas natural..."). La detección
de campaña corre solo en el momento en que llega el mensaje — nunca
reprocesa mensajes viejos — así que las conversaciones ANTERIORES a esa
fecha con ese saludo exacto quedaron sin campaña asignada (confirmado
investigando el bloque "Orgánicos" de Analítica: 2 conversaciones,
2026-09-16 y 2026-09-18, con ese texto exacto). Esta migración aplica el
patrón ya corregido a esas conversaciones históricas.

Mismo criterio que c9f1a3d7e526: nunca pisa una campaña ya asignada (ni en
`conversations.campana_origen_id` ni en `leads.campana_origen`), y solo
actualiza `leads.campana_origen` para el lead cuya conversación quedó
asignada acá — no reconstruye historial de ningún otro caso.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'f10c9d0f9996'
down_revision: Union[str, Sequence[str], None] = 'c9f1a3d7e526'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_NOMBRE_CAMPANA = 'SMS Clientes próximos a habilitar gas'
# Mismo substring que agent/campanas.py PATRONES_CORREGIDOS — LOWER()+LIKE
# en vez de ILIKE: tiene que funcionar igual en SQLite (tests) y Postgres
# (producción), y el único carácter que necesita normalizarse acá es la
# "P" mayúscula — "habilitarán" ya llega en minúscula en los datos reales.
_SALUDO = 'pronto habilitarán mi servicio de gas natural'

_SIGUIENTE_CONVERSATION = """
    SELECT MIN(c2.creado) FROM conversations c2
    WHERE c2.contact_id = conversations.contact_id AND c2.creado > conversations.creado
"""

# Cualquier mensaje entrante DENTRO de la ventana de esta conversation (no
# solo el primero) que contenga el saludo — acotado por la conversation
# siguiente del mismo contacto para no cruzar mensajes de otro hilo.
_TIENE_SALUDO = f"""
    EXISTS (
        SELECT 1 FROM mensajes m
        JOIN contacts ct ON ct.telefono = m.telefono
        WHERE ct.id = conversations.contact_id
        AND m.role = 'user'
        AND m.timestamp >= conversations.creado
        AND m.timestamp < COALESCE(({_SIGUIENTE_CONVERSATION}), '9999-12-31')
        AND LOWER(m.content) LIKE '%{_SALUDO}%'
    )
"""

_CAMPANA_ID = f"""
    SELECT ca.id FROM campanas ca
    WHERE ca.negocio_id = conversations.negocio_id AND ca.nombre = '{_NOMBRE_CAMPANA}'
"""

SQL_ASIGNAR_CONVERSATIONS = f"""
UPDATE conversations
SET campana_origen_id = ({_CAMPANA_ID} LIMIT 1)
WHERE campana_origen_id IS NULL
AND EXISTS ({_CAMPANA_ID})
AND {_TIENE_SALUDO}
"""

# Corre DESPUÉS de la de arriba — se apoya en conversations.campana_origen_id
# ya actualizado para saber qué lead completar, sin repetir el match de texto.
SQL_ASIGNAR_LEADS = f"""
UPDATE leads
SET campana_origen = '{_NOMBRE_CAMPANA}'
WHERE campana_origen IS NULL
AND EXISTS (
    SELECT 1 FROM contacts ct
    JOIN conversations cn ON cn.contact_id = ct.id
    JOIN campanas ca ON ca.id = cn.campana_origen_id
    WHERE ct.telefono = leads.telefono AND ct.negocio_id = leads.negocio_id
    AND ca.nombre = '{_NOMBRE_CAMPANA}'
)
"""


def upgrade() -> None:
    conexion = op.get_bind()
    conexion.execute(sa.text(SQL_ASIGNAR_CONVERSATIONS))
    conexion.execute(sa.text(SQL_ASIGNAR_LEADS))


def downgrade() -> None:
    # No se distingue cuáles se asignaron acá de las que ya estaban
    # asignadas correctamente antes; dejarlas no rompe nada (mismo criterio
    # que c9f1a3d7e526).
    pass
