"""gate 4.2 identidad agente y horarios atencion

Revision ID: e726728060b8
Revises: a05737d4c680
Create Date: 2026-09-09 22:22:18.324700

GATE 4.2 — cierra las Decisiones Pendientes 1 y 5 de Gate 4.1:

1. `identidades_agente` — identidad/comportamiento de Gabi POR NEGOCIO (ver
   `agent/memory.py::IdentidadAgente` para la evidencia completa de por qué
   una tabla propia, no claves namespaced en `Configuracion`). Backfill:
   una fila para Cálidda con `configuracion_negocio` = el `system_prompt`
   EXACTO de `config/prompts.yaml` al momento de correr esta migración —
   leído del archivo en vez de transcrito a mano, para que la igualdad sea
   estructuralmente imposible de romper por un error de transcripción
   (verificado además con test de igualdad exacta,
   `tests/test_gate42_identidad_agente.py`).

2. `horarios_atencion` — horario de atención POR NEGOCIO (reemplaza la
   constante hardcodeada de `agent/tools.py::obtener_estado_horario_atencion`,
   lunes a sábado 8:00-19:00). Backfill: los mismos 7 días/horas que ya
   estaban hardcodeados para Cálidda — mismo resultado exacto, ninguna
   diferencia de comportamiento observable para el único Negocio real hoy.

Ambos backfills son no-op (no insertan nada) si no existe un Negocio con
`codigo='calidda'` — nunca inventan a qué Negocio pertenece un dato.
"""
from typing import Sequence, Union
import os

from alembic import op
import sqlalchemy as sa
import yaml


# revision identifiers, used by Alembic.
revision: str = 'e726728060b8'
down_revision: Union[str, Sequence[str], None] = 'a05737d4c680'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

CODIGO_CALIDDA = 'calidda'
NOMBRE_AGENTE_CALIDDA = 'Gabi'
TONO_AGENTE_CALIDDA = 'Cercano, profesional y resolutivo'

# Rango que corría hardcodeado en agent/tools.py antes de este Gate — se
# repite acá literalmente (no se reinterpreta) para que el backfill sea
# garantizadamente equivalente al comportamiento anterior.
_DIAS_HABILITADOS = {0, 1, 2, 3, 4, 5}  # lunes a sábado
_HORA_APERTURA = '08:00'
_HORA_CIERRE = '19:00'


def upgrade() -> None:
    """Upgrade schema + data."""
    bind = op.get_bind()

    op.create_table(
        'identidades_agente',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('negocio_id', sa.String(length=36), sa.ForeignKey('negocios.id'), nullable=False),
        sa.Column('codigo', sa.String(length=30), nullable=False),
        sa.Column('nombre', sa.String(length=50), nullable=False),
        sa.Column('tono', sa.String(length=200), nullable=False),
        sa.Column('configuracion_negocio', sa.Text(), nullable=False),
        sa.Column('creado', sa.DateTime(), nullable=False),
        sa.Column('actualizado', sa.DateTime(), nullable=False),
    )
    op.create_index('ix_identidades_agente_negocio_id', 'identidades_agente', ['negocio_id'])
    op.create_index(
        'ix_identidad_agente_negocio_codigo', 'identidades_agente', ['negocio_id', 'codigo'], unique=True,
    )

    op.create_table(
        'horarios_atencion',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('negocio_id', sa.String(length=36), sa.ForeignKey('negocios.id'), nullable=False),
        sa.Column('dia_semana', sa.Integer(), nullable=False),
        sa.Column('habilitado', sa.Boolean(), nullable=False),
        sa.Column('hora_apertura', sa.String(length=5), nullable=True),
        sa.Column('hora_cierre', sa.String(length=5), nullable=True),
    )
    op.create_index('ix_horarios_atencion_negocio_id', 'horarios_atencion', ['negocio_id'])
    op.create_index(
        'ix_horario_negocio_dia', 'horarios_atencion', ['negocio_id', 'dia_semana'], unique=True,
    )

    negocios = sa.table('negocios', sa.column('id', sa.String), sa.column('codigo', sa.String))
    negocio_id = bind.execute(
        sa.select(negocios.c.id).where(negocios.c.codigo == CODIGO_CALIDDA)
    ).scalar()
    if negocio_id is None:
        # Sin Cálidda backfilleada todavía (ej. una base de datos nueva de
        # test) no hay a quién asignarle la identidad/horario — no se
        # inventa. Las tablas quedan creadas y vacías.
        return

    ruta_prompts = os.path.join(os.path.dirname(__file__), '..', '..', 'config', 'prompts.yaml')
    with open(ruta_prompts, 'r', encoding='utf-8') as f:
        system_prompt = yaml.safe_load(f)['system_prompt']

    identidades = sa.table(
        'identidades_agente',
        sa.column('negocio_id', sa.String), sa.column('codigo', sa.String),
        sa.column('nombre', sa.String), sa.column('tono', sa.String),
        sa.column('configuracion_negocio', sa.Text),
        sa.column('creado', sa.DateTime), sa.column('actualizado', sa.DateTime),
    )
    bind.execute(
        identidades.insert().values(
            negocio_id=negocio_id, codigo='gabi', nombre=NOMBRE_AGENTE_CALIDDA, tono=TONO_AGENTE_CALIDDA,
            configuracion_negocio=system_prompt,
            creado=sa.func.current_timestamp(), actualizado=sa.func.current_timestamp(),
        )
    )

    horarios = sa.table(
        'horarios_atencion',
        sa.column('negocio_id', sa.String), sa.column('dia_semana', sa.Integer),
        sa.column('habilitado', sa.Boolean), sa.column('hora_apertura', sa.String), sa.column('hora_cierre', sa.String),
    )
    for dia in range(7):
        habilitado = dia in _DIAS_HABILITADOS
        bind.execute(
            horarios.insert().values(
                negocio_id=negocio_id, dia_semana=dia, habilitado=habilitado,
                hora_apertura=_HORA_APERTURA if habilitado else None,
                hora_cierre=_HORA_CIERRE if habilitado else None,
            )
        )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_horario_negocio_dia', table_name='horarios_atencion')
    op.drop_index('ix_horarios_atencion_negocio_id', table_name='horarios_atencion')
    op.drop_table('horarios_atencion')
    op.drop_index('ix_identidad_agente_negocio_codigo', table_name='identidades_agente')
    op.drop_index('ix_identidades_agente_negocio_id', table_name='identidades_agente')
    op.drop_table('identidades_agente')
