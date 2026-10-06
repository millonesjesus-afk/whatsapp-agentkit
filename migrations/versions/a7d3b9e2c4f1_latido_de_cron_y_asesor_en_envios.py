"""latido de los Cron (cron_ejecuciones) y asesor que envía (envios_meta.asesor_usuario)

Revision ID: a7d3b9e2c4f1
Revises: e5a1c8f3b2d7
Create Date: 2026-10-05 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a7d3b9e2c4f1'
down_revision: Union[str, Sequence[str], None] = 'e5a1c8f3b2d7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Una fila por corrida de cada script programado (latido): sirve para avisar en Inicio
    # cuando un proceso falló o dejó de correr. Tabla nueva, sin tocar datos existentes.
    op.create_table(
        'cron_ejecuciones',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('script', sa.String(length=60), nullable=False),
        sa.Column('inicio', sa.DateTime(), nullable=False),
        sa.Column('fin', sa.DateTime(), nullable=True),
        sa.Column('ok', sa.Boolean(), nullable=True),
        sa.Column('resumen', sa.String(length=300), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_cron_ejecuciones_script_inicio', 'cron_ejecuciones', ['script', 'inicio'], unique=False)
    # Username del asesor que mandó el mensaje desde el panel (los envíos de Gabi y de los
    # scripts quedan en NULL). Columna nullable: aditiva, sin relleno.
    op.add_column('envios_meta', sa.Column('asesor_usuario', sa.String(length=50), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    if op.get_bind().dialect.name == 'sqlite':
        with op.batch_alter_table('envios_meta') as batch_op:
            batch_op.drop_column('asesor_usuario')
    else:
        op.drop_column('envios_meta', 'asesor_usuario')
    op.drop_index('ix_cron_ejecuciones_script_inicio', table_name='cron_ejecuciones')
    op.drop_table('cron_ejecuciones')
