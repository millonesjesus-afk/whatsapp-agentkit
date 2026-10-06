"""Cierra definitivamente (ver `Lead.cerrado_definitivamente_en`) todo lead
con asesor asignado, resultado ya cerrado y 7 días sin respuesta del
cliente — Gate 2026-09-23, pedido explícito del usuario tras encontrar que
un `resultado` cerrado por sí solo reactivaba a Gabi sin que el asesor que
seguía atendiendo (por otro motivo) se enterara.

Distinto de scripts/liberar_leads_inactivos.py (mide silencio del ASESOR
sobre un resultado ABIERTO) y de scripts/procesar_inactividad_clientes.py
(exclusivo de leads que NUNCA tuvieron asesor): este es el 3er escenario —
silencio del CLIENTE sobre un resultado YA CERRADO con asesor asignado.

Ver agent/memory.py::cerrar_leads_definitivamente_inactivos para la lógica
real y el porqué completo — este script es solo el punto de entrada que
Railway Cron ejecuta. Solo MARCA el cierre; la liberación real de la
asignación pasa recién cuando el cliente vuelve a escribir (agent/main.py).

Pensado para correr como un Cron Schedule de Railway, en un servicio
aparte del proceso web principal (mismo repo/imagen, comando de arranque
distinto) — no dentro de main.py. Recomendado: una vez al día (el umbral
son días, no horas — no necesita la frecuencia de los otros dos).

Uso local (prueba manual, no corre en Railway automáticamente):
    python scripts/cerrar_leads_definitivamente.py
"""
import asyncio
import sys
from pathlib import Path

# Permite correr este script directo (python scripts/archivo.py) sin que
# Python se queje de no encontrar el paquete `agent` — mismo motivo/mismo
# patrón que scripts/liberar_leads_inactivos.py.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts._cron import ejecutar_cron  # latido: ver scripts/_cron.py

from agent.memory import cerrar_leads_definitivamente_inactivos, esperar_base_de_datos

DIAS_INACTIVIDAD = 7


async def main() -> None:
    await esperar_base_de_datos()
    cerrados = await cerrar_leads_definitivamente_inactivos(dias=DIAS_INACTIVIDAD)
    if cerrados:
        print(
            f"Cerrados definitivamente {len(cerrados)} lead(s) por inactividad del cliente "
            f"({DIAS_INACTIVIDAD} días sin responder sobre un resultado ya cerrado): {', '.join(cerrados)}"
        )
    else:
        print("Ningún lead cruzó el umbral de cierre definitivo.")


if __name__ == "__main__":
    try:
        asyncio.run(ejecutar_cron("cerrar_leads_definitivamente", main, 1440))
    except Exception as e:
        print(f"ERROR: cierre definitivo de leads inactivos falló — {e}", file=sys.stderr)
        sys.exit(1)
