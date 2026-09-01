"""gate 5.6 indice conversation campana origen

Revision ID: 4642f3d55e15
Revises: dc2e52d83280
Create Date: 2026-08-31 18:49:20.111704

Gate 5.6 — optimización recomendada (no bloqueante), aprobada explícitamente
por el usuario con la condición de que la migración sea segura y reversible.
Índice simple, no único, no condicional — no valida ni fuerza ninguna regla
de negocio, solo acelera un lookup.

Beneficia a `contar_opportunities_por_campana()` (Gate 5.6), que filtra
`Conversation.campana_origen_id IN (...)` para agregar leads/ventas por
campaña, scoped por Negocio. Nota de implementación: el Diseño Técnico
aprobado proponía un índice compuesto `(negocio_id, campana_origen_id)`,
pero la query final no filtra `Conversation.negocio_id` en absoluto (el
scope por Negocio ya se resuelve antes, filtrando las Campana por
negocio_id) — un índice compuesto con `negocio_id` como columna líder no
aceleraría este lookup (un B-tree no puede usar la segunda columna de un
índice compuesto sin filtrar primero por la primera). Se crea en cambio un
índice simple sobre la columna que la query realmente usa.

100% aditivo: no toca ninguna fila existente, no puede fallar contra datos
existentes, reversible con un simple DROP INDEX.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '4642f3d55e15'
down_revision: Union[str, Sequence[str], None] = 'dc2e52d83280'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index(
        "ix_conversation_campana_origen", "conversations", ["campana_origen_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_conversation_campana_origen", table_name="conversations")
