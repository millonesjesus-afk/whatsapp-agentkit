"""aislar archivo adjunto reutilizable por negocio id

Revision ID: 8b7005fbcd65
Revises: e619df043e34
Create Date: 2026-09-12 16:02:57.270648

Gate — Aislamiento multi-tenant de ArchivoAdjunto (catalogo reutilizable).
Cierra el hallazgo confirmado en la Auditoria Maestra: `archivos_adjuntos`
no tenia negocio_id, y las rutas de listar/descargar/enviar/eliminar
catalogo reutilizable no filtraban por tenant (GET /catalogos devolvia el
catalogo de TODOS los negocios a cualquier usuario autenticado).

Alcance deliberadamente restringido a reutilizable=True (decision del
usuario en este Gate): las proformas (reutilizable=False) ya estan
correctamente aisladas de forma indirecta via Mensaje.archivo_id ->
Mensaje.telefono -> Lead.negocio_id (test_gate55_archivo_cross_tenant.py)
y no se tocan aca.

Por eso, a diferencia de e619df043e34 (Producto, donde TODO el universo de
filas se backfillea y luego se fuerza NOT NULL sobre la columna completa),
aca negocio_id se backfillea SOLO para reutilizable=True y la columna
queda nullable a nivel de tabla -las proformas seguiran teniendo
negocio_id NULL indefinidamente, por diseno, no por deuda-. La garantia de
"todo reutilizable tiene negocio_id" se expresa con un CHECK constraint
condicional, no con NOT NULL sobre toda la columna.

Mismo patron EXPAND+BACKFILL+VALIDATE que e619df043e34: Calidda se resuelve
por SELECT contra negocios.codigo (nunca UUID hardcodeado); el backfill es
no-op si Calidda no existe todavia (ej. una base de datos nueva de test).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '8b7005fbcd65'
down_revision: Union[str, Sequence[str], None] = 'e619df043e34'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

CODIGO_CALIDDA = 'calidda'
CHECK_NAME = 'ck_archivos_adjuntos_reutilizable_negocio'


def upgrade() -> None:
    """Upgrade schema + data."""
    bind = op.get_bind()

    # SQLite no soporta ALTER TABLE ADD COLUMN con una constraint (FK)
    # inline -batch mode es obligatorio aca, mismo criterio que
    # e619df043e34.
    with op.batch_alter_table('archivos_adjuntos') as batch_op:
        batch_op.add_column(sa.Column(
            'negocio_id', sa.String(length=36),
            sa.ForeignKey('negocios.id', name='fk_archivos_adjuntos_negocio_id'), nullable=True,
        ))
    op.create_index('ix_archivos_adjuntos_negocio_id', 'archivos_adjuntos', ['negocio_id'])

    negocios = sa.table('negocios', sa.column('id', sa.String), sa.column('codigo', sa.String))
    negocio_id = bind.execute(
        sa.select(negocios.c.id).where(negocios.c.codigo == CODIGO_CALIDDA)
    ).scalar()
    if negocio_id is None:
        # Sin Calidda backfilleada todavia (ej. una base de datos nueva de
        # test) no hay a quien asignarle los reutilizables existentes -no
        # se inventa. La columna y el CHECK quedan sin crear el CHECK; se
        # detiene aca igual que e619df043e34 hace con NOT NULL.
        return

    bind.execute(
        sa.text(
            "UPDATE archivos_adjuntos SET negocio_id = :negocio_id "
            "WHERE reutilizable = true AND negocio_id IS NULL"
        ),
        {"negocio_id": negocio_id},
    )

    huerfanos = bind.execute(sa.text(
        "SELECT COUNT(*) FROM archivos_adjuntos WHERE reutilizable = true AND negocio_id IS NULL"
    )).scalar()
    if huerfanos:
        raise RuntimeError(
            f"{huerfanos} archivo(s) reutilizable(s) sin negocio_id tras el backfill -no "
            "deberia ser posible (Calidda es el unico Negocio hoy con archivos reutilizables, "
            "confirmado por auditoria). No se crea el CHECK constraint; revisar manualmente "
            "antes de reintentar esta migracion (regla: no inventar pertenencia)."
        )

    with op.batch_alter_table('archivos_adjuntos') as batch_op:
        batch_op.create_check_constraint(
            CHECK_NAME,
            "reutilizable = false OR negocio_id IS NOT NULL",
        )


def downgrade() -> None:
    """Downgrade schema + data."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    checks_existentes = {c["name"] for c in inspector.get_check_constraints('archivos_adjuntos')}

    if CHECK_NAME in checks_existentes:
        # El CHECK no se crea en upgrade() si Calidda todavia no existe
        # (ver rama `if negocio_id is None: return`) -downgrade debe ser
        # simetrico y no asumir que siempre se creo.
        with op.batch_alter_table('archivos_adjuntos') as batch_op:
            batch_op.drop_constraint(CHECK_NAME, type_='check')

    with op.batch_alter_table('archivos_adjuntos') as batch_op:
        batch_op.drop_index('ix_archivos_adjuntos_negocio_id')
        batch_op.drop_column('negocio_id')
