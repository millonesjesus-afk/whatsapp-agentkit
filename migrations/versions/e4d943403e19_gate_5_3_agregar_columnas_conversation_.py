"""gate 5.3 agregar columnas conversation_id opportunity_id

Revision ID: e4d943403e19
Revises: 66ab4085660a
Create Date: 2026-08-28 11:58:28.553063

Gate 5.3 — EXPAND (M2). Agrega, todo nullable, las columnas que el backfill
(M3) va a poblar: `mensajes.conversation_id`, `eventos_lead.negocio_id` /
`conversation_id` / `opportunity_id`, `lineas_venta.opportunity_id` /
`negocio_id`.

También relaja `eventos_lead.telefono` y `lineas_venta.telefono` a nullable
(batch_alter_table, portable SQLite/Postgres, mismo patrón que Gate 5.2) —
necesario ANTES del backfill porque el código de aplicación de este mismo
Gate ya deja de escribir esas columnas (registrar_evento_lead/guardar_venta
ahora escriben conversation_id/opportunity_id, no telefono) — sin este paso
los INSERT nuevos violarían el NOT NULL existente. Las columnas `telefono`
NO se eliminan todavía (quedan como dato histórico inerte, sin lectura ni
escritura desde el código) — el CONTRACT que las retira, si se decide
hacerlo, es un paso posterior, explícitamente fuera de este Gate.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e4d943403e19'
down_revision: Union[str, Sequence[str], None] = '66ab4085660a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('mensajes', sa.Column('conversation_id', sa.String(length=36), nullable=True))
    op.create_index('ix_mensajes_conversation_id', 'mensajes', ['conversation_id'])

    op.add_column('eventos_lead', sa.Column('negocio_id', sa.String(length=36), nullable=True))
    op.add_column('eventos_lead', sa.Column('conversation_id', sa.String(length=36), nullable=True))
    op.add_column('eventos_lead', sa.Column('opportunity_id', sa.String(length=36), nullable=True))
    op.create_index('ix_eventos_lead_negocio_id', 'eventos_lead', ['negocio_id'])
    op.create_index('ix_eventos_lead_conversation_id', 'eventos_lead', ['conversation_id'])
    op.create_index('ix_eventos_lead_opportunity_id', 'eventos_lead', ['opportunity_id'])
    op.create_index('ix_evento_negocio_conversation_creado', 'eventos_lead', ['negocio_id', 'conversation_id', 'creado'])
    with op.batch_alter_table('eventos_lead') as batch_op:
        batch_op.alter_column('telefono', existing_type=sa.String(length=50), nullable=True)

    op.add_column('lineas_venta', sa.Column('opportunity_id', sa.String(length=36), nullable=True))
    op.add_column('lineas_venta', sa.Column('negocio_id', sa.String(length=36), nullable=True))
    op.create_index('ix_lineas_venta_opportunity_id', 'lineas_venta', ['opportunity_id'])
    op.create_index('ix_lineas_venta_negocio_id', 'lineas_venta', ['negocio_id'])
    op.create_index('ix_lineaventa_opportunity_negocio', 'lineas_venta', ['opportunity_id', 'negocio_id'])
    with op.batch_alter_table('lineas_venta') as batch_op:
        batch_op.alter_column('telefono', existing_type=sa.String(length=50), nullable=True)


def downgrade() -> None:
    """Downgrade schema. No se restauran los valores de `telefono` que
    hubieran quedado NULL al relajar el constraint (no había ninguno en la
    dirección upgrade, así que no hay pérdida real al revertir esta fase por
    sí sola)."""
    with op.batch_alter_table('lineas_venta') as batch_op:
        batch_op.alter_column('telefono', existing_type=sa.String(length=50), nullable=False)
    op.drop_index('ix_lineaventa_opportunity_negocio', table_name='lineas_venta')
    op.drop_index('ix_lineas_venta_negocio_id', table_name='lineas_venta')
    op.drop_index('ix_lineas_venta_opportunity_id', table_name='lineas_venta')
    op.drop_column('lineas_venta', 'negocio_id')
    op.drop_column('lineas_venta', 'opportunity_id')

    with op.batch_alter_table('eventos_lead') as batch_op:
        batch_op.alter_column('telefono', existing_type=sa.String(length=50), nullable=False)
    op.drop_index('ix_evento_negocio_conversation_creado', table_name='eventos_lead')
    op.drop_index('ix_eventos_lead_opportunity_id', table_name='eventos_lead')
    op.drop_index('ix_eventos_lead_conversation_id', table_name='eventos_lead')
    op.drop_index('ix_eventos_lead_negocio_id', table_name='eventos_lead')
    op.drop_column('eventos_lead', 'opportunity_id')
    op.drop_column('eventos_lead', 'conversation_id')
    op.drop_column('eventos_lead', 'negocio_id')

    op.drop_index('ix_mensajes_conversation_id', table_name='mensajes')
    op.drop_column('mensajes', 'conversation_id')
