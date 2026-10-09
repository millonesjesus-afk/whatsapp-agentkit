"""tareas de llamada ("Para llamar"), contacts.no_llamar_en y configuracion.valor a 1000 caracteres

Revision ID: b8e2d4f6a1c3
Revises: a7d3b9e2c4f1
Create Date: 2026-10-09 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b8e2d4f6a1c3'
down_revision: Union[str, Sequence[str], None] = 'a7d3b9e2c4f1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # 1) Tabla nueva, aditiva: una fila por tarea de llamada (ver agent/llamadas.py y TareaLlamada).
    #    No toca ninguna fila existente. El indice unico parcial garantiza a lo sumo UNA tarea abierta
    #    (programada o pendiente) por conversacion; funciona igual en SQLite y en Postgres.
    op.create_table(
        'tareas_llamada',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('negocio_id', sa.String(length=36), nullable=False),
        sa.Column('conversation_id', sa.String(length=36), nullable=False),
        sa.Column('contact_id', sa.String(length=36), nullable=False),
        sa.Column('telefono', sa.String(length=150), nullable=False),
        sa.Column('estado', sa.String(length=20), nullable=False),
        sa.Column('motivo_cierre', sa.String(length=40), nullable=True),
        sa.Column('segmento', sa.String(length=20), nullable=False),
        sa.Column('puntaje', sa.Integer(), nullable=False),
        sa.Column('senales', sa.JSON(), nullable=True),
        sa.Column('grupo', sa.String(length=10), nullable=False),
        sa.Column('modo', sa.String(length=10), nullable=False),
        sa.Column('asesor_username', sa.String(length=50), nullable=True),
        sa.Column('asignada_en', sa.DateTime(), nullable=True),
        sa.Column('programada_para', sa.DateTime(), nullable=True),
        sa.Column('intentos', sa.Integer(), nullable=False),
        sa.Column('ultimo_intento_en', sa.DateTime(), nullable=True),
        sa.Column('proximo_intento_en', sa.DateTime(), nullable=True),
        sa.Column('resultado_llamada', sa.String(length=40), nullable=True),
        sa.Column('nota', sa.String(length=500), nullable=True),
        sa.Column('reasignaciones', sa.Integer(), nullable=False),
        sa.Column('escalada_en', sa.DateTime(), nullable=True),
        sa.Column('creada_en', sa.DateTime(), nullable=False),
        sa.Column('cerrada_en', sa.DateTime(), nullable=True),
        sa.Column('vence_en', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['negocio_id'], ['negocios.id']),
        sa.ForeignKeyConstraint(['conversation_id'], ['conversations.id']),
        sa.ForeignKeyConstraint(['contact_id'], ['contacts.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_tareas_llamada_negocio_id', 'tareas_llamada', ['negocio_id'], unique=False)
    op.create_index('ix_tareas_llamada_conversation_id', 'tareas_llamada', ['conversation_id'], unique=False)
    op.create_index('ix_tareas_llamada_contact_id', 'tareas_llamada', ['contact_id'], unique=False)
    op.create_index('ix_tareas_llamada_estado', 'tareas_llamada', ['estado'], unique=False)
    op.create_index('ix_tareas_llamada_asesor_username', 'tareas_llamada', ['asesor_username'], unique=False)
    op.create_index('ix_tareas_llamada_creada_en', 'tareas_llamada', ['creada_en'], unique=False)
    op.create_index('ix_tareas_llamada_negocio_estado', 'tareas_llamada', ['negocio_id', 'estado'], unique=False)
    op.create_index(
        'ix_tarea_llamada_una_abierta_por_conversation', 'tareas_llamada', ['conversation_id'], unique=True,
        sqlite_where=sa.text("estado IN ('programada', 'pendiente')"),
        postgresql_where=sa.text("estado IN ('programada', 'pendiente')"),
    )

    # 2) "No llamar": instante desde el que la persona pidio que no se la llame. Columna nullable, sin relleno.
    op.add_column('contacts', sa.Column('no_llamar_en', sa.DateTime(), nullable=True))

    # 3) configuracion.valor de 200 a 1000: el texto de la oferta de llamada (y los textos configurables
    #    del triaje, de hasta 600) no cabian en 200 en Postgres. Ampliar un VARCHAR es solo un cambio de
    #    metadatos. En SQLite no hace falta (no valida longitudes, y reconstruir la tabla perderia los
    #    indices unicos parciales).
    if op.get_bind().dialect.name != 'sqlite':
        op.alter_column(
            'configuracion', 'valor', existing_type=sa.String(length=200), type_=sa.String(length=1000), existing_nullable=False,
        )


def downgrade() -> None:
    """Downgrade schema."""
    # El ancho de configuracion.valor NO se reduce a proposito: acortarlo fallaria si ya hay valores de mas
    # de 200 caracteres.
    if op.get_bind().dialect.name == 'sqlite':
        with op.batch_alter_table('contacts') as batch_op:
            batch_op.drop_column('no_llamar_en')
    else:
        op.drop_column('contacts', 'no_llamar_en')
    op.drop_index('ix_tarea_llamada_una_abierta_por_conversation', table_name='tareas_llamada')
    op.drop_index('ix_tareas_llamada_negocio_estado', table_name='tareas_llamada')
    op.drop_index('ix_tareas_llamada_creada_en', table_name='tareas_llamada')
    op.drop_index('ix_tareas_llamada_asesor_username', table_name='tareas_llamada')
    op.drop_index('ix_tareas_llamada_estado', table_name='tareas_llamada')
    op.drop_index('ix_tareas_llamada_contact_id', table_name='tareas_llamada')
    op.drop_index('ix_tareas_llamada_conversation_id', table_name='tareas_llamada')
    op.drop_index('ix_tareas_llamada_negocio_id', table_name='tareas_llamada')
    op.drop_table('tareas_llamada')
