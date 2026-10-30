"""Limpia los «(desconocido)» que el modelo de extracción dejó guardados como si fueran datos del cliente (2026-10-30).

El prompt de extracción de datos usaba «(desconocido)» como marcador de los datos que faltaban; el modelo lo devolvía tal cual y se
guardaba COMO NOMBRE (y a veces como interés o marca). Efecto: la Bandeja mostraba «(desconocido)» aunque el número existía y Gabi creía
conocer el nombre. Desde el cambio del 2026-10-30 eso ya no se vuelve a guardar; este script limpia lo que quedó.

Qué toca: SOLO pone en NULL el texto que es un marcador de «no sé» (desconocido, null, n/a, sin dato…), en `leads` (nombre, interes,
producto_marca), `contacts` (nombre) y `opportunities` (interes, producto_marca). No toca ningún dato real ni ninguna otra tabla.

Uso (la base sale de DATABASE_URL, como en los demás scripts):
    python scripts/limpiar_marcadores_vacios.py             # solo cuenta lo que limpiaría (no cambia nada)
    python scripts/limpiar_marcadores_vacios.py --aplicar   # lo limpia
"""
import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select

from agent import memory as mem
from agent.memory import esperar_base_de_datos

# (modelo, columnas de texto libre que escribe el modelo de extracción)
OBJETIVOS = (
    (mem.Lead, ("nombre", "interes", "producto_marca")),
    (mem.Contact, ("nombre",)),
    (mem.Opportunity, ("interes", "producto_marca")),
)


async def main(argv=None) -> dict:
    p = argparse.ArgumentParser(description="Limpia los «(desconocido)» guardados como datos del cliente.")
    p.add_argument("--aplicar", action="store_true", help="Escribe los cambios (sin esto solo cuenta).")
    args = p.parse_args(argv)
    await esperar_base_de_datos()
    resumen: dict[str, int] = {}
    async with mem.async_session() as session:
        for modelo, columnas in OBJETIVOS:
            for columna in columnas:
                atributo = getattr(modelo, columna)
                filas = (await session.execute(select(modelo).where(atributo.is_not(None)))).scalars().all()
                a_limpiar = [f for f in filas if mem.es_marcador_vacio(getattr(f, columna))]
                resumen[f"{modelo.__tablename__}.{columna}"] = len(a_limpiar)
                if args.aplicar:
                    for fila in a_limpiar:
                        setattr(fila, columna, None)
        if args.aplicar:
            await session.commit()
    total = sum(resumen.values())
    for clave, n in resumen.items():
        print(f"{clave}: {n}")
    print(f"Total: {total} {'limpiados' if args.aplicar else 'por limpiar (no se cambió nada; usa --aplicar)'}")
    return {"aplicado": args.aplicar, "total": total, "detalle": resumen}


if __name__ == "__main__":
    asyncio.run(main())
