"""ampliar historial_precio_producto valores a text

Revision ID: 9b2c4d7e1a35
Revises: 35175f4d063e
Create Date: 2026-08-18

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '9b2c4d7e1a35'
down_revision: Union[str, Sequence[str], None] = '35175f4d063e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # La tabla nació dimensionada para precios y cuotas (números cortos), pero
    # la bitácora audita también descripcion/combo/comentarios, que llegan a
    # 300 caracteres: con String(50) el valor se guardaba recortado y el dato
    # anterior se perdía para siempre (la bitácora es la única copia que queda
    # del valor viejo). Mismo motivo, mismo patrón y mismo tipo destino que
    # productos.combo en fe7af0de58f1.
    #
    # batch_alter_table por lo mismo que allá: SQLite no aplica el límite de
    # VARCHAR, así que local "funcionaría" igual sin migrar, pero el cambio de
    # tipo tiene que quedar registrado y aplicarse de verdad en Postgres
    # (producción). VARCHAR(50) -> TEXT es una ampliación, no trunca ninguna
    # fila existente.
    with op.batch_alter_table('historial_precio_producto') as batch_op:
        batch_op.alter_column('valor_anterior', existing_type=sa.String(length=50), type_=sa.Text(), existing_nullable=True)
        batch_op.alter_column('valor_nuevo', existing_type=sa.String(length=50), type_=sa.Text(), existing_nullable=True)


def downgrade() -> None:
    """Downgrade schema."""
    # Volver a String(50) es destructivo en Postgres si ya hay filas más
    # largas (el ALTER falla, no trunca en silencio). Se deja el downgrade
    # simétrico igual, para no romper la cadena de revisiones.
    with op.batch_alter_table('historial_precio_producto') as batch_op:
        batch_op.alter_column('valor_nuevo', existing_type=sa.Text(), type_=sa.String(length=50), existing_nullable=True)
        batch_op.alter_column('valor_anterior', existing_type=sa.Text(), type_=sa.String(length=50), existing_nullable=True)
