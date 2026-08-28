"""crear negocio unidad y registro auditoria

Revision ID: 61836c757b25
Revises: 3f5bd9ab58f0
Create Date: 2026-08-27 23:03:23.557142

Gate 5.2 — Fundación Negocio/Unidad. Migración puramente aditiva (EXPAND):
crea las tres tablas fundacionales del aislamiento Multi-Tenant (Arquitectura
Contractual, Gate 5.1) sin tocar ninguna tabla existente. `Negocio`/
`negocio_id` es el nombre técnico de contrato — "Tenant" sigue siendo
vocabulario de producto, nunca nombre de tabla/columna.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '61836c757b25'
down_revision: Union[str, Sequence[str], None] = '3f5bd9ab58f0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'negocios',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('nombre', sa.String(length=150), nullable=False),
        sa.Column('codigo', sa.String(length=30), nullable=False),
        sa.Column('activo', sa.Boolean(), nullable=False),
        sa.Column('eliminado_en', sa.DateTime(), nullable=True),
        sa.Column('eliminado_por', sa.String(length=50), nullable=True),
        sa.Column('creado', sa.DateTime(), nullable=False),
        sa.Column('actualizado', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_negocios_codigo', 'negocios', ['codigo'], unique=True)

    op.create_table(
        'unidades_de_negocio',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('negocio_id', sa.String(length=36), nullable=False),
        sa.Column('nombre', sa.String(length=150), nullable=False),
        sa.Column('codigo_interno', sa.String(length=30), nullable=False),
        sa.Column('activo', sa.Boolean(), nullable=False),
        sa.Column('eliminado_en', sa.DateTime(), nullable=True),
        sa.Column('eliminado_por', sa.String(length=50), nullable=True),
        sa.Column('creado', sa.DateTime(), nullable=False),
        sa.Column('actualizado', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['negocio_id'], ['negocios.id']),
    )
    op.create_index('ix_unidades_de_negocio_negocio_id', 'unidades_de_negocio', ['negocio_id'])
    op.create_index(
        'ix_unidad_negocio_codigo', 'unidades_de_negocio', ['negocio_id', 'codigo_interno'], unique=True,
    )

    op.create_table(
        'registro_auditoria',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('negocio_id', sa.String(length=36), nullable=True),
        sa.Column('actor', sa.String(length=50), nullable=True),
        sa.Column('accion', sa.String(length=50), nullable=False),
        sa.Column('entidad_tipo', sa.String(length=50), nullable=True),
        sa.Column('entidad_id', sa.String(length=100), nullable=True),
        sa.Column('payload', sa.JSON(), nullable=True),
        sa.Column('creado', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['negocio_id'], ['negocios.id']),
    )
    op.create_index('ix_registro_auditoria_negocio_id', 'registro_auditoria', ['negocio_id'])
    op.create_index('ix_registro_auditoria_creado', 'registro_auditoria', ['creado'])
    op.create_index(
        'ix_auditoria_negocio_entidad', 'registro_auditoria', ['negocio_id', 'entidad_tipo', 'entidad_id'],
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('registro_auditoria')
    op.drop_table('unidades_de_negocio')
    op.drop_index('ix_negocios_codigo', table_name='negocios')
    op.drop_table('negocios')
