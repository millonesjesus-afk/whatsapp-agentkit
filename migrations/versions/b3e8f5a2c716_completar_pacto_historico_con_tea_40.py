"""completar el pacto de financiamiento de las ventas históricas con TEA 40 %

Revision ID: b3e8f5a2c716
Revises: a7c2d4e91b35
Create Date: 2026-09-23

Las ventas financiadas cerradas ANTES de que existiera el pacto congelado
(a7c2d4e91b35) no tienen cuota pactada. Por indicación del negocio, todas se
cerraron con TEA 40 % e IGV 18 % sobre el interés, así que se completan con
esa tasa: monto financiado = suma de sus líneas, cuota = primera cuota del
sistema francés con IGV solo sobre el interés (misma fórmula que
agent/tools.py::_calcular_amortizacion, copiada acá a propósito: una
migración no puede cambiar de comportamiento si esa función evoluciona).

Solo toca filas con `cuota_pactada` NULL (idempotente, nunca pisa un pacto
real) y se salta cualquier venta sin monto numérico exacto o con cuotas fuera
de 1-60: sin dato no se inventa nada. Lead recibe el mismo valor que la
Opportunity más reciente de su contacto, siempre que las cuotas coincidan.
"""
import re
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b3e8f5a2c716'
down_revision: Union[str, Sequence[str], None] = 'a7c2d4e91b35'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TEA = 0.40
_IGV = 0.18
_PATRON_PRECIO = re.compile(r"^\s*(?:S/\.?)?\s*([\d.,]+)\s*$", re.IGNORECASE)


def _monto(precios: list) -> float | None:
    total = 0.0
    for precio in precios:
        m = _PATRON_PRECIO.match(str(precio or ""))
        if not m:
            return None
        try:
            total += float(m.group(1).replace(",", ""))
        except ValueError:
            return None
    return total if total > 0 else None


def _primera_cuota(monto: float, n: int) -> float:
    tem = (1 + _TEA) ** (1 / 12) - 1
    if n == 1:
        return monto + monto * tem * (1 + _IGV)
    cuota_base = monto * tem / (1 - (1 + tem) ** -n)
    interes = monto * tem
    return (cuota_base - interes) + interes * (1 + _IGV)


def upgrade() -> None:
    conn = op.get_bind()
    opps = conn.execute(sa.text(
        "SELECT o.id, o.cuotas, ct.telefono FROM opportunities o "
        "JOIN conversations cv ON cv.id = o.conversation_id "
        "JOIN contacts ct ON ct.id = cv.contact_id "
        "WHERE o.modalidad_pago = 'financiado' AND o.cuotas IS NOT NULL "
        "AND o.cuota_pactada IS NULL ORDER BY o.creado DESC"
    )).fetchall()

    for opp_id, cuotas, telefono in opps:
        try:
            n = int(cuotas)
        except (TypeError, ValueError):
            continue
        if not 1 <= n <= 60:
            continue
        precios = [r[0] for r in conn.execute(
            sa.text("SELECT precio FROM lineas_venta WHERE opportunity_id = :id"), {"id": opp_id},
        )]
        if not precios:
            continue
        monto = _monto(precios)
        if monto is None:
            continue

        valores = {
            "monto": f"{monto:.2f}", "cuota": f"{_primera_cuota(monto, n):.2f}",
            "tea": str(_TEA), "igv": str(_IGV),
        }
        conn.execute(sa.text(
            "UPDATE opportunities SET monto_financiado = :monto, cuota_pactada = :cuota, "
            "tea_pactada = :tea, igv_pactado = :igv WHERE id = :id AND cuota_pactada IS NULL"
        ), {**valores, "id": opp_id})
        conn.execute(sa.text(
            "UPDATE leads SET monto_financiado = :monto, cuota_pactada = :cuota, "
            "tea_pactada = :tea, igv_pactado = :igv "
            "WHERE telefono = :tel AND cuota_pactada IS NULL "
            "AND modalidad_pago = 'financiado' AND cuotas = :cuotas"
        ), {**valores, "tel": telefono, "cuotas": cuotas})


def downgrade() -> None:
    # Datos retroactivos: no se distinguen de un pacto real, así que no se
    # revierten (borrarlos también borraría pactos legítimos posteriores).
    pass
