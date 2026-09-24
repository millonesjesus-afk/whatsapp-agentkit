"""agregar a la identidad de Gabi la regla de derivación directa

Revision ID: c5d9e2b7a481
Revises: b3e8f5a2c716
Create Date: 2026-09-24

Gabi le preguntaba al cliente "¿quieres que te conecte con un asesor?" aun
cuando este ya lo había pedido, y en otras conversaciones derivaba sin decirlo.
El prompt de Cálidda vive en `identidades_agente.configuracion_negocio` (no en
el código), así que la regla se agrega ahí: un párrafo NUEVO dentro de "Cuándo
derivar a un asesor humano", justo antes de la línea del horario. No edita
ningún fragmento existente — `_reducir_texto_legacy_calidda` (agent/brain.py)
exige que los bloques que reconoce sigan idénticos.

Idempotente (si el párrafo ya está, no hace nada) y conservadora (si no
encuentra la línea del horario donde insertarlo, no toca esa fila). El mismo
párrafo está en config/prompts.yaml, de donde sale el prompt del número de
pruebas y los tests.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c5d9e2b7a481'
down_revision: Union[str, Sequence[str], None] = 'b3e8f5a2c716'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

PARRAFO = 'Cuando el cliente pida hablar con un asesor, una persona o un ejecutivo, o se cumpla alguno\nde los criterios anteriores, derívalo tú directamente en ese mismo mensaje: dile que lo estás\nderivando con un asesor comercial. NUNCA le preguntes si quiere que lo derives, ni pidas su\npermiso, ni se lo ofrezcas como pregunta ("¿quieres que te conecte?", "¿te parece bien?").\nSi ya lo derivaste antes en esta conversación, confírmalo brevemente en vez de volver a\nofrecerlo.\n\n'
ANCLA = "Horario de atención de los asesores humanos:"
MARCA = "Cuando el cliente pida hablar con un asesor, una persona o un ejecutivo"


def insertar(texto: str) -> str:
    """Devuelve `texto` con el párrafo antes de la línea del horario, o
    `texto` sin cambios si ya lo tiene o no hay dónde insertarlo."""
    if MARCA in texto or texto.count(ANCLA) != 1:
        return texto
    return texto.replace(ANCLA, PARRAFO + ANCLA, 1)


def upgrade() -> None:
    conn = op.get_bind()
    filas = conn.execute(sa.text("SELECT id, configuracion_negocio FROM identidades_agente")).fetchall()
    for fila_id, texto in filas:
        nuevo = insertar(texto or "")
        if nuevo != texto:
            conn.execute(
                sa.text("UPDATE identidades_agente SET configuracion_negocio = :t WHERE id = :id"),
                {"t": nuevo, "id": fila_id},
            )


def downgrade() -> None:
    conn = op.get_bind()
    filas = conn.execute(sa.text("SELECT id, configuracion_negocio FROM identidades_agente")).fetchall()
    for fila_id, texto in filas:
        if texto and PARRAFO in texto:
            conn.execute(
                sa.text("UPDATE identidades_agente SET configuracion_negocio = :t WHERE id = :id"),
                {"t": texto.replace(PARRAFO, "", 1), "id": fila_id},
            )
