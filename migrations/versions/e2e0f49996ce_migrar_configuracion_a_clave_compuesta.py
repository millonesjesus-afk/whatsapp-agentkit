"""migrar configuracion a clave compuesta

Revision ID: e2e0f49996ce
Revises: a46a93329345
Create Date: 2026-08-27 23:03:45.000000

Gate 5.2 — migra `Configuracion` al contrato de Arquitectura Contractual §7:
clave compuesta (clave, negocio_id), con negocio_id NULL = configuración
GLOBAL de plataforma. Postgres no admite NULL dentro de una PRIMARY KEY, así
que la tabla pasa a tener un `id` autoincremental como PK real, con la
unicidad (clave) para filas globales y (clave, negocio_id) para overrides
por Negocio aplicada con dos índices únicos PARCIALES — no con la PK.

Todas las filas existentes se preservan con negocio_id = NULL (config
global), que es EXACTAMENTE el mismo dato que `obtener_configuracion`
resuelve hoy sin este cambio — el fallback no se rompe (verificado: las
funciones obtener_configuracion/guardar_configuracion ya se actualizaron
en agent/memory.py para usar negocio_id=None por defecto, mismo
comportamiento observable para todo llamador existente).

Recrea la tabla en vez de un ALTER en el lugar (el cambio de PK lo exige en
SQLite; se usa el mismo patrón portable para Postgres por consistencia).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e2e0f49996ce'
down_revision: Union[str, Sequence[str], None] = 'a46a93329345'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'configuracion_nueva',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('clave', sa.String(length=50), nullable=False),
        sa.Column('negocio_id', sa.String(length=36), nullable=True),
        sa.Column('valor', sa.String(length=200), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['negocio_id'], ['negocios.id']),
    )

    bind = op.get_bind()
    # Copia 1:1 — toda fila existente queda como configuración GLOBAL
    # (negocio_id NULL), preservando el valor exacto que ya tenía.
    bind.execute(sa.text(
        "INSERT INTO configuracion_nueva (clave, negocio_id, valor) "
        "SELECT clave, NULL, valor FROM configuracion"
    ))

    op.drop_table('configuracion')
    op.rename_table('configuracion_nueva', 'configuracion')

    op.create_index(
        'ix_config_global_unica', 'configuracion', ['clave'], unique=True,
        sqlite_where=sa.text('negocio_id IS NULL'),
        postgresql_where=sa.text('negocio_id IS NULL'),
    )
    op.create_index(
        'ix_config_por_negocio_unica', 'configuracion', ['clave', 'negocio_id'], unique=True,
        sqlite_where=sa.text('negocio_id IS NOT NULL'),
        postgresql_where=sa.text('negocio_id IS NOT NULL'),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.create_table(
        'configuracion_vieja',
        sa.Column('clave', sa.String(length=50), nullable=False),
        sa.Column('valor', sa.String(length=200), nullable=False),
        sa.PrimaryKeyConstraint('clave'),
    )
    bind = op.get_bind()
    # Solo se puede volver a una PK simple (clave) preservando las filas
    # GLOBALES — un override por Negocio no tiene dónde volver en el
    # esquema viejo, así que downgrade es deliberadamente con pérdida para
    # esas filas (no deberían existir todavía en este punto del roadmap).
    bind.execute(sa.text(
        "INSERT INTO configuracion_vieja (clave, valor) "
        "SELECT clave, valor FROM configuracion WHERE negocio_id IS NULL"
    ))
    op.drop_index('ix_config_por_negocio_unica', table_name='configuracion')
    op.drop_index('ix_config_global_unica', table_name='configuracion')
    op.drop_table('configuracion')
    op.rename_table('configuracion_vieja', 'configuracion')
