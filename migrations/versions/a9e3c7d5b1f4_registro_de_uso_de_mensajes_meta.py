"""registro de uso y costo de mensajes de Meta (estados de entrega)

Revision ID: a9e3c7d5b1f4
Revises: f2d6a8c4e1b7
Create Date: 2026-10-04 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a9e3c7d5b1f4'
down_revision: Union[str, Sequence[str], None] = 'f2d6a8c4e1b7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Desde el 2026-10-01 Meta cobra los mensajes de servicio tras una cuota
    # gratuita por número, y hasta ahora los estados (sent/delivered/read/
    # failed) con su `pricing` se ignoraban. Tabla aditiva: nada existente
    # cambia. El único cambio sobre una tabla existente es un índice (no
    # único) sobre mensajes.mensaje_id_meta, para cruzar cada wamid con su
    # mensaje; la tabla es chica y el índice se crea en segundos.
    op.create_table(
        'uso_mensajes_meta',
        sa.Column('wamid', sa.String(length=100), nullable=False),
        sa.Column('phone_number_id', sa.String(length=50), nullable=False),
        sa.Column('negocio_id', sa.String(length=36), nullable=True),
        sa.Column('destinatario', sa.String(length=50), nullable=True),
        sa.Column('estado', sa.String(length=20), nullable=False),
        sa.Column('enviado_en', sa.DateTime(), nullable=True),
        sa.Column('entregado_en', sa.DateTime(), nullable=True),
        sa.Column('leido_en', sa.DateTime(), nullable=True),
        sa.Column('fallido_en', sa.DateTime(), nullable=True),
        sa.Column('error_codigo', sa.Integer(), nullable=True),
        sa.Column('error_titulo', sa.String(length=200), nullable=True),
        sa.Column('pricing_billable', sa.Boolean(), nullable=True),
        sa.Column('pricing_model', sa.String(length=10), nullable=True),
        sa.Column('pricing_type', sa.String(length=30), nullable=True),
        sa.Column('pricing_categoria', sa.String(length=40), nullable=True),
        sa.Column('creado', sa.DateTime(), nullable=False),
        sa.Column('actualizado', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('wamid'),
    )
    op.create_index('ix_uso_mensajes_meta_negocio_id', 'uso_mensajes_meta', ['negocio_id'], unique=False)
    op.create_index('ix_uso_mensajes_phone_entregado', 'uso_mensajes_meta', ['phone_number_id', 'entregado_en'], unique=False)
    op.create_index('ix_uso_mensajes_negocio_entregado', 'uso_mensajes_meta', ['negocio_id', 'entregado_en'], unique=False)
    op.create_index('ix_mensajes_mensaje_id_meta', 'mensajes', ['mensaje_id_meta'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_mensajes_mensaje_id_meta', table_name='mensajes')
    op.drop_index('ix_uso_mensajes_negocio_entregado', table_name='uso_mensajes_meta')
    op.drop_index('ix_uso_mensajes_phone_entregado', table_name='uso_mensajes_meta')
    op.drop_index('ix_uso_mensajes_meta_negocio_id', table_name='uso_mensajes_meta')
    op.drop_table('uso_mensajes_meta')
