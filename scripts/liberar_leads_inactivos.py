"""Libera automáticamente la asignación de leads cuyo asesor no respondió
en las últimas N horas — Gabi retoma la atención en silencio (2026-09-16,
Opción 1 de la decisión tomada con el usuario: sin plantilla aprobada de
Meta todavía, avisarle al cliente que su caso se cerró justo al cumplirse
el timeout caería fuera de la ventana de servicio de 24h de WhatsApp,
donde solo se permite una Plantilla — no texto libre. Cuando el cliente
vuelva a escribir, ESE mensaje abre una ventana nueva gratis y Gabi lo
atiende como lead nuevo en el flujo regular, sin fricción ni costo).

Ver agent/memory.py::liberar_asignaciones_inactivas para la lógica real y
el porqué completo — este script es solo el punto de entrada que Railway
Cron ejecuta.

Pensado para correr como un Cron Schedule de Railway, en un servicio
aparte del proceso web principal (mismo repo/imagen, comando de arranque
distinto) — no dentro de main.py. Recomendado: cada hora.

Uso local (prueba manual, no corre en Railway automáticamente):
    python scripts/liberar_leads_inactivos.py
"""
import asyncio
import sys
from pathlib import Path

# Permite correr este script directo (python scripts/archivo.py) sin que
# Python se queje de no encontrar el paquete `agent` — mismo motivo/mismo
# patrón que scripts/migrar_usuarios_a_railway.py.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent.memory import liberar_asignaciones_inactivas

HORAS_INACTIVIDAD = 24


async def main() -> None:
    liberados = await liberar_asignaciones_inactivas(horas=HORAS_INACTIVIDAD)
    if liberados:
        print(
            f"Liberados {len(liberados)} lead(s) por inactividad del asesor "
            f"({HORAS_INACTIVIDAD}h sin responder): {', '.join(liberados)}"
        )
    else:
        print("Ningún lead cruzó el umbral de inactividad.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as e:
        print(f"ERROR: liberación de leads inactivos falló — {e}", file=sys.stderr)
        sys.exit(1)
