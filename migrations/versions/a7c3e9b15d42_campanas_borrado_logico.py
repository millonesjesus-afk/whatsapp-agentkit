"""campañas: borrado lógico (eliminado_en, eliminado_por, reglas_anuncio_eliminadas)

Revision ID: a7c3e9b15d42
Revises: d8b4f2a6c3e1
Create Date: 2026-11-04 00:00:00.000000

Pendiente de la auditoría de UX (2026-11-04): «restaurar campañas eliminadas». Hoy eliminar una campaña BORRA la fila y sus
reglas anuncio→campaña. Con estas 3 columnas, eliminar pasa a marcar la fila y guardar los anuncios que tenía, y restaurar
los vuelve a vincular. Las tres son NULL en toda campaña existente (nada que rellenar) y aditivas: la versión anterior del
código las ignora, así que volver atrás es seguro.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a7c3e9b15d42'
down_revision: Union[str, Sequence[str], None] = 'd8b4f2a6c3e1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('campanas', sa.Column('eliminado_en', sa.DateTime(), nullable=True))
    op.add_column('campanas', sa.Column('eliminado_por', sa.String(length=50), nullable=True))
    op.add_column('campanas', sa.Column('reglas_anuncio_eliminadas', sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column('campanas', 'reglas_anuncio_eliminadas')
    op.drop_column('campanas', 'eliminado_por')
    op.drop_column('campanas', 'eliminado_en')
