"""ampliar columnas de teléfono a 150 caracteres (BSUID)

Revision ID: afd93064ba83
Revises: f10c9d0f9996
Create Date: 2026-09-22

Un BSUID (Business-Scoped User ID, el identificador que Meta manda en vez
del teléfono real cuando el cliente activó Usernames de WhatsApp — ver Gate
del 2026-09-22, `agent/providers/meta.py`) puede tener hasta 128 caracteres
según la documentación de Meta. `String(50)` lo rechazaría en Postgres
(mismo tipo de descubrimiento que fe7af0de58f1 con `productos.combo` —
SQLite no aplica el límite de VARCHAR, Postgres sí). Amplía las 4 columnas
que guardan `telefono`/`lead_telefono` a 150, con margen. `batch_alter_table`
para que funcione igual en SQLite (tests) y Postgres (producción).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'afd93064ba83'
down_revision: Union[str, Sequence[str], None] = 'f10c9d0f9996'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('mensajes') as batch_op:
        batch_op.alter_column('telefono', existing_type=sa.String(length=50), type_=sa.String(length=150), existing_nullable=False)
    with op.batch_alter_table('leads') as batch_op:
        batch_op.alter_column('telefono', existing_type=sa.String(length=50), type_=sa.String(length=150), existing_nullable=False)
    with op.batch_alter_table('attribution_events') as batch_op:
        batch_op.alter_column('lead_telefono', existing_type=sa.String(length=50), type_=sa.String(length=150), existing_nullable=False)
    with op.batch_alter_table('contacts') as batch_op:
        batch_op.alter_column('telefono', existing_type=sa.String(length=50), type_=sa.String(length=150), existing_nullable=False)


def downgrade() -> None:
    with op.batch_alter_table('contacts') as batch_op:
        batch_op.alter_column('telefono', existing_type=sa.String(length=150), type_=sa.String(length=50), existing_nullable=False)
    with op.batch_alter_table('attribution_events') as batch_op:
        batch_op.alter_column('lead_telefono', existing_type=sa.String(length=150), type_=sa.String(length=50), existing_nullable=False)
    with op.batch_alter_table('leads') as batch_op:
        batch_op.alter_column('telefono', existing_type=sa.String(length=150), type_=sa.String(length=50), existing_nullable=False)
    with op.batch_alter_table('mensajes') as batch_op:
        batch_op.alter_column('telefono', existing_type=sa.String(length=150), type_=sa.String(length=50), existing_nullable=False)
