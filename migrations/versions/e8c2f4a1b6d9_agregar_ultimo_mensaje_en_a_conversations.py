"""agregar ultimo_mensaje_en a conversations

Revision ID: e8c2f4a1b6d9
Revises: d4b7a1c93e52
Create Date: 2026-10-03 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e8c2f4a1b6d9'
down_revision: Union[str, Sequence[str], None] = 'd4b7a1c93e52'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # La Bandeja ordenaba por `conversations.actualizado`, que también se
    # mueve al asignar, rotar, liberar o cerrar automáticamente. Esta columna
    # guarda solo la hora del último mensaje real. Se rellena una vez con el
    # MAX(timestamp) de sus mensajes (o `creado` si no tiene ninguno), así que
    # el orden correcto aparece de inmediato sin tocar ningún dato existente.
    op.add_column('conversations', sa.Column('ultimo_mensaje_en', sa.DateTime(), nullable=True))
    op.create_index('ix_conversations_ultimo_mensaje_en', 'conversations', ['ultimo_mensaje_en'], unique=False)
    op.execute(
        "UPDATE conversations SET ultimo_mensaje_en = COALESCE("
        "(SELECT MAX(m.timestamp) FROM mensajes m WHERE m.conversation_id = conversations.id), "
        "conversations.creado)"
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_conversations_ultimo_mensaje_en', table_name='conversations')
    op.drop_column('conversations', 'ultimo_mensaje_en')
