"""Cierra definitivamente (ver `Lead.cerrado_definitivamente_en`) toda venta
("vendido") con asesor asignado y 5 días sin respuesta del cliente — Punto 3
(2026-09-28): hasta este Gate NINGÚN Cron cubría "vendido" (la exclusión
histórica de Close-Won es indefinido bloqueaba también el cierre, no solo la
reactivación de Gabi), así que una venta con seguimiento pendiente podía
quedar sin que nadie se enterara si el cliente no volvía a escribir.

Distinto de scripts/cerrar_leads_definitivamente.py (mismo mecanismo, pero
para los otros 8 resultados cerrados, con un umbral de 7 días): este es un
4to escenario deliberadamente separado, con un umbral más corto porque
reabrir no tiene downside — si el cliente vuelve a escribir en cualquier
momento, agent/main.py (enrutar_posventa_si_corresponde) reabre la atención
sin pérdida, ruteándola de una al mismo asesor que hizo la venta, nunca a
Gabi (Close-Won sigue siendo indefinido para Gabi — ver agent/memory.py).

Ver agent/memory.py::cerrar_ventas_sin_seguimiento para la lógica real y el
porqué completo del umbral — este script es solo el punto de entrada que
Railway Cron ejecuta. Solo MARCA el cierre; la liberación real de la
asignación (y el ruteo al asesor original) pasa recién cuando el cliente
vuelve a escribir (agent/main.py).

Pensado para correr como un Cron Schedule de Railway, en un servicio
aparte del proceso web principal (mismo repo/imagen, comando de arranque
distinto) — no dentro de main.py. Recomendado: una vez al día, igual que
cerrar_leads_definitivamente.py.

Uso local (prueba manual, no corre en Railway automáticamente):
    python scripts/cerrar_ventas_sin_seguimiento.py
"""
import asyncio
import sys
from pathlib import Path

# Permite correr este script directo (python scripts/archivo.py) sin que
# Python se queje de no encontrar el paquete `agent` — mismo motivo/mismo
# patrón que scripts/cerrar_leads_definitivamente.py.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent.memory import cerrar_ventas_sin_seguimiento, esperar_base_de_datos

DIAS_INACTIVIDAD = 5


async def main() -> None:
    await esperar_base_de_datos()
    cerrados = await cerrar_ventas_sin_seguimiento(dias=DIAS_INACTIVIDAD)
    if cerrados:
        print(
            f"Cerradas definitivamente {len(cerrados)} venta(s) sin seguimiento del cliente "
            f"({DIAS_INACTIVIDAD} días sin responder sobre una venta ya cerrada): {', '.join(cerrados)}"
        )
    else:
        print("Ninguna venta cruzó el umbral de cierre definitivo.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as e:
        print(f"ERROR: cierre definitivo de ventas sin seguimiento falló — {e}", file=sys.stderr)
        sys.exit(1)
