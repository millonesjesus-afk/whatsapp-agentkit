"""gate 5.3 crear contact conversation opportunity

Revision ID: 66ab4085660a
Revises: e2e0f49996ce
Create Date: 2026-08-28 11:58:25.022548

Gate 5.3 — EXPAND (M1). Crea las 3 tablas nuevas del modelo objetivo
(Diseño Técnico Gate 5.3 §4-6): `contacts`, `conversations`, `opportunities`.
Aditivo puro — cero riesgo, ningún dato existente se toca todavía.

`Contact.telefono` es único COMPUESTO con `negocio_id` (Arquitectura
Contractual §8: el mismo teléfono puede existir como Contact distinto en
dos Negocios). `Conversation.canal_id`/`campanas.campana_origen_id` son
Integer (FK real hacia canales_whatsapp/campanas) — Canal y Campaña NO
migran a UUID en este Gate (Data Architecture v1 ya las excluye
explícitamente de migración retroactiva de PK).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '66ab4085660a'
down_revision: Union[str, Sequence[str], None] = 'e2e0f49996ce'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'contacts',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('negocio_id', sa.String(length=36), nullable=False),
        sa.Column('telefono', sa.String(length=50), nullable=False),
        sa.Column('nombre', sa.String(length=100), nullable=True),
        sa.Column('eliminado_en', sa.DateTime(), nullable=True),
        sa.Column('eliminado_por', sa.String(length=50), nullable=True),
        sa.Column('creado', sa.DateTime(), nullable=False),
        sa.Column('actualizado', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['negocio_id'], ['negocios.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_contacts_negocio_id', 'contacts', ['negocio_id'])
    op.create_index('ix_contacts_actualizado', 'contacts', ['actualizado'])
    op.create_index('ix_contact_negocio_telefono', 'contacts', ['negocio_id', 'telefono'], unique=True)

    op.create_table(
        'conversations',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('negocio_id', sa.String(length=36), nullable=False),
        sa.Column('unidad_id', sa.String(length=36), nullable=True),
        sa.Column('contact_id', sa.String(length=36), nullable=False),
        sa.Column('canal_id', sa.Integer(), nullable=False),
        sa.Column('campana_origen_id', sa.Integer(), nullable=True),
        sa.Column('estado', sa.String(length=20), nullable=False),
        sa.Column('asesor_asignado_id', sa.String(length=50), nullable=True),
        sa.Column('paso_flujo', sa.String(length=50), nullable=True),
        sa.Column('origen_contacto', sa.String(length=30), nullable=True),
        sa.Column('visto_asesor', sa.Boolean(), nullable=False),
        sa.Column('fallos_tecnicos', sa.Integer(), nullable=False),
        sa.Column('pausado_manual', sa.Boolean(), nullable=False),
        sa.Column('revision_prioritaria', sa.Boolean(), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.Column('creado', sa.DateTime(), nullable=False),
        sa.Column('actualizado', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['negocio_id'], ['negocios.id']),
        sa.ForeignKeyConstraint(['unidad_id'], ['unidades_de_negocio.id']),
        sa.ForeignKeyConstraint(['contact_id'], ['contacts.id']),
        sa.ForeignKeyConstraint(['canal_id'], ['canales_whatsapp.id']),
        sa.ForeignKeyConstraint(['campana_origen_id'], ['campanas.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_conversations_negocio_id', 'conversations', ['negocio_id'])
    op.create_index('ix_conversations_unidad_id', 'conversations', ['unidad_id'])
    op.create_index('ix_conversations_contact_id', 'conversations', ['contact_id'])
    op.create_index('ix_conversations_canal_id', 'conversations', ['canal_id'])
    op.create_index('ix_conversations_estado', 'conversations', ['estado'])
    op.create_index('ix_conversations_asesor_asignado_id', 'conversations', ['asesor_asignado_id'])
    op.create_index('ix_conversations_creado', 'conversations', ['creado'])
    op.create_index('ix_conversations_actualizado', 'conversations', ['actualizado'])
    op.create_index('ix_conversation_negocio_unidad', 'conversations', ['negocio_id', 'unidad_id'])
    op.create_index('ix_conversation_contact_creado', 'conversations', ['contact_id', 'creado'])
    op.create_index('ix_conversation_negocio_asesor', 'conversations', ['negocio_id', 'asesor_asignado_id'])

    op.create_table(
        'opportunities',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('negocio_id', sa.String(length=36), nullable=False),
        sa.Column('unidad_id', sa.String(length=36), nullable=True),
        sa.Column('conversation_id', sa.String(length=36), nullable=False),
        sa.Column('contact_id', sa.String(length=36), nullable=False),
        sa.Column('interes', sa.String(length=200), nullable=True),
        sa.Column('producto_tipo', sa.String(length=50), nullable=True),
        sa.Column('producto_marca', sa.String(length=50), nullable=True),
        sa.Column('producto_modalidad', sa.String(length=20), nullable=True),
        sa.Column('resultado', sa.String(length=50), nullable=True),
        sa.Column('fecha_agendada', sa.DateTime(), nullable=True),
        sa.Column('fecha_cierre', sa.DateTime(), nullable=True),
        sa.Column('modalidad_pago', sa.String(length=30), nullable=True),
        sa.Column('cuotas', sa.String(length=10), nullable=True),
        sa.Column('medio_pago', sa.String(length=50), nullable=True),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.Column('creado', sa.DateTime(), nullable=False),
        sa.Column('actualizado', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['negocio_id'], ['negocios.id']),
        sa.ForeignKeyConstraint(['unidad_id'], ['unidades_de_negocio.id']),
        sa.ForeignKeyConstraint(['conversation_id'], ['conversations.id']),
        sa.ForeignKeyConstraint(['contact_id'], ['contacts.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_opportunities_negocio_id', 'opportunities', ['negocio_id'])
    op.create_index('ix_opportunities_unidad_id', 'opportunities', ['unidad_id'])
    op.create_index('ix_opportunities_conversation_id', 'opportunities', ['conversation_id'])
    op.create_index('ix_opportunities_contact_id', 'opportunities', ['contact_id'])
    op.create_index('ix_opportunities_resultado', 'opportunities', ['resultado'])
    op.create_index('ix_opportunities_creado', 'opportunities', ['creado'])
    op.create_index('ix_opportunity_negocio_resultado', 'opportunities', ['negocio_id', 'resultado'])
    op.create_index('ix_opportunity_conversation_creado', 'opportunities', ['conversation_id', 'creado'])


def downgrade() -> None:
    """Downgrade schema. Reversible sin pérdida — en este punto las 3 tablas
    están vacías (M1 es aditivo puro, el backfill es una migración
    posterior)."""
    op.drop_table('opportunities')
    op.drop_table('conversations')
    op.drop_table('contacts')
