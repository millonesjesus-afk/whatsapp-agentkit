"""dias_especiales: calendario de negocio (feriados y dias especiales) y siembra de los feriados 2026

Revision ID: d1a4c7e92b58
Revises: b8e2d4f6a1c3
Create Date: 2026-10-12 00:00:00.000000

"""
import uuid
from datetime import date, datetime
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd1a4c7e92b58'
down_revision: Union[str, Sequence[str], None] = 'b8e2d4f6a1c3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Feriados nacionales de Peru 2026 (verificados por el agente de diseno H1, 2026-10-12; Jueves y Viernes Santo
# calculados desde la Pascua del 5-abr-2026). Copia CONGELADA a proposito: una migracion no debe cambiar de efecto si
# alguien edita agent/calendario_peru.py mas adelante. 2027 NO se siembra aqui (no esta verificado): se carga con
# `python scripts/sembrar_calendario.py --anio 2027 --aplicar` o con el boton «Cargar feriados» del panel.
FUENTE = "https://www.elperuano.pe"
FERIADOS_2026 = [
    (date(2026, 1, 1), "Año Nuevo"),
    (date(2026, 4, 2), "Jueves Santo"),
    (date(2026, 4, 3), "Viernes Santo"),
    (date(2026, 5, 1), "Día del Trabajo"),
    (date(2026, 6, 7), "Batalla de Arica y Día de la Bandera"),
    (date(2026, 6, 29), "San Pedro y San Pablo"),
    (date(2026, 7, 23), "Día de la Fuerza Aérea del Perú"),
    (date(2026, 7, 28), "Fiestas Patrias"),
    (date(2026, 7, 29), "Fiestas Patrias"),
    (date(2026, 8, 6), "Batalla de Junín"),
    (date(2026, 8, 30), "Santa Rosa de Lima"),
    (date(2026, 10, 8), "Combate de Angamos"),
    (date(2026, 11, 1), "Día de Todos los Santos"),
    (date(2026, 12, 8), "Inmaculada Concepción"),
    (date(2026, 12, 9), "Batalla de Ayacucho"),
    (date(2026, 12, 25), "Navidad"),
]


def upgrade() -> None:
    """Upgrade schema."""
    # 1) Tabla nueva, aditiva: una fila por dia de Lima con excepcion al horario semanal. El indice unico parcial
    #    garantiza una sola fila VIVA por (negocio, fecha); las eliminadas (borrado logico) no cuentan. Funciona igual
    #    en SQLite y en Postgres.
    op.create_table(
        'dias_especiales',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('negocio_id', sa.String(length=36), nullable=False),
        sa.Column('fecha', sa.Date(), nullable=False),
        sa.Column('tipo', sa.String(length=20), nullable=False),
        sa.Column('nombre', sa.String(length=100), nullable=False),
        sa.Column('atiende', sa.Boolean(), nullable=False),
        sa.Column('hora_apertura', sa.String(length=5), nullable=True),
        sa.Column('hora_cierre', sa.String(length=5), nullable=True),
        sa.Column('origen', sa.String(length=20), nullable=False),
        sa.Column('fuente_url', sa.String(length=300), nullable=True),
        sa.Column('creado', sa.DateTime(), nullable=False),
        sa.Column('creado_por', sa.String(length=50), nullable=True),
        sa.Column('actualizado', sa.DateTime(), nullable=False),
        sa.Column('eliminado_en', sa.DateTime(), nullable=True),
        sa.Column('eliminado_por', sa.String(length=50), nullable=True),
        sa.ForeignKeyConstraint(['negocio_id'], ['negocios.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_dias_especiales_negocio_id', 'dias_especiales', ['negocio_id'], unique=False)
    op.create_index('ix_dias_especiales_negocio_fecha', 'dias_especiales', ['negocio_id', 'fecha'], unique=False)
    op.create_index(
        'ix_dia_especial_una_viva_por_fecha', 'dias_especiales', ['negocio_id', 'fecha'], unique=True,
        sqlite_where=sa.text("eliminado_en IS NULL"),
        postgresql_where=sa.text("eliminado_en IS NULL"),
    )

    # 2) Siembra: los feriados nacionales 2026 (SOLO feriados, atiende = falso) para cada negocio que ya existe. No
    #    inserta dias no laborables ni puentes: los decide el administrador. Un negocio sin filas de dias especiales
    #    parte de cero, asi que no hay nada que duplicar; el indice unico parcial protege igual.
    bind = op.get_bind()
    tabla = sa.table(
        'dias_especiales',
        sa.column('id', sa.String), sa.column('negocio_id', sa.String), sa.column('fecha', sa.Date),
        sa.column('tipo', sa.String), sa.column('nombre', sa.String), sa.column('atiende', sa.Boolean),
        sa.column('origen', sa.String), sa.column('fuente_url', sa.String), sa.column('creado', sa.DateTime),
        sa.column('actualizado', sa.DateTime),
    )
    ahora = datetime.utcnow()
    negocios = [fila[0] for fila in bind.execute(sa.text("SELECT id FROM negocios")).fetchall()]
    filas = [
        {
            'id': str(uuid.uuid4()), 'negocio_id': negocio_id, 'fecha': fecha, 'tipo': 'feriado', 'nombre': nombre,
            'atiende': False, 'origen': 'precargado_pe', 'fuente_url': FUENTE, 'creado': ahora, 'actualizado': ahora,
        }
        for negocio_id in negocios for fecha, nombre in FERIADOS_2026
    ]
    if filas:
        op.bulk_insert(tabla, filas)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_dia_especial_una_viva_por_fecha', table_name='dias_especiales')
    op.drop_index('ix_dias_especiales_negocio_fecha', table_name='dias_especiales')
    op.drop_index('ix_dias_especiales_negocio_id', table_name='dias_especiales')
    op.drop_table('dias_especiales')
