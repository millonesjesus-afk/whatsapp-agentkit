"""gate 5.5 una conversation activa por contact

Revision ID: dc2e52d83280
Revises: 3d17e5be6e5b
Create Date: 2026-08-31 12:00:00.000000

Gate 5.5 — candado de concurrencia real (hallazgo del checkpoint de
investigación de Gate 5.5): DR-4 (Resolución Arquitectónica Gate 5.3, "un
Contact nunca tiene dos Conversation activas simultáneas") estaba declarada
en el docstring del modelo pero NUNCA forzada por la base de datos. Bajo
Postgres real, dos webhooks concurrentes para el mismo Contact podían crear
dos filas `estado="activa"` — SQLite serializa escrituras a nivel de
archivo y enmascara el riesgo en desarrollo local, por eso no se detectó
antes.

Mismo patrón ya usado en `Configuracion` (ix_config_global_unica /
ix_config_por_negocio_unica, Gate 5.x): índice único parcial con
`sqlite_where`/`postgresql_where`, no una migración de datos — solo agrega
el candado, no toca ninguna fila existente. VALIDATE previo (fuera de esta
migración, ya confirmado antes de escribirla): cero duplicados de
Conversation activa por Contact en la base real, así que crear el índice
único no puede fallar contra datos existentes.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'dc2e52d83280'
down_revision: Union[str, Sequence[str], None] = '3d17e5be6e5b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    dialecto = bind.dialect.name
    condicion = "estado = 'activa'"
    kwargs = {"sqlite_where": sa.text(condicion)} if dialecto == "sqlite" else {"postgresql_where": sa.text(condicion)}
    op.create_index(
        "ix_conversation_una_activa_por_contact", "conversations", ["contact_id"],
        unique=True, **kwargs,
    )


def downgrade() -> None:
    op.drop_index("ix_conversation_una_activa_por_contact", table_name="conversations")
