"""Borra del disco las proformas y notas de voz (`ArchivoAdjunto`
`reutilizable=False`) subidas hace más de `DIAS_RETENCION` días — Cron
Schedule de Railway, mismo patrón que scripts/backup_postgres.py y
scripts/liberar_leads_inactivos.py (2026-09-16, pedido explícito del
usuario, después del fix de tamaño de adjuntos: "esos catalogos pesados se
queden en la memoria ocupando espacio o lo podemos expirar").

DIAS_RETENCION = 90, confirmado con el usuario — más generoso que el
límite propio de Meta para media de WhatsApp Cloud API (30 días), y en
línea con referencias de retención de CRMs para datos de alto volumen
(ej. Marketo, 90 días).

Alcance — SOLO archivos NO reutilizables (proformas/notas de voz puntuales,
un archivo por envío). Los catálogos reutilizables de la librería
(`reutilizable=True`) NUNCA se tocan acá: se referencian desde muchos leads
a la vez, y su borrado sigue siendo una acción manual explícita desde el
panel. Ver `agent/memory.py::listar_archivos_no_reutilizables_antes_de`
para el criterio completo.

Qué NO borra — el mensaje del chat, quién lo subió, cuándo: solo el
archivo físico. `GET /dashboard/archivo/{id}` (agent/dashboard.py) ya
maneja bien un archivo ausente en disco (devuelve "El archivo ya no está
disponible" en vez de romperse), así que el historial de la conversación
queda intacto — reabrir un adjunto viejo simplemente ya no muestra el
archivo.

Uso local (prueba manual, no corre en Railway automáticamente):
    python scripts/purgar_archivos_expirados.py
"""
import asyncio
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

# Permite correr este script directo (python scripts/archivo.py) sin que
# Python se queje de no encontrar el paquete `agent` — mismo motivo/mismo
# patrón que scripts/liberar_leads_inactivos.py.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent.memory import esperar_base_de_datos, listar_archivos_no_reutilizables_antes_de

DIAS_RETENCION = 90


async def main() -> None:
    await esperar_base_de_datos()
    corte = datetime.utcnow() - timedelta(days=DIAS_RETENCION)
    candidatos = await listar_archivos_no_reutilizables_antes_de(corte)

    borrados = 0
    ya_ausentes = 0
    fallidos = 0
    for archivo in candidatos:
        ruta = archivo["ruta_disco"]
        if not os.path.exists(ruta):
            # Ya lo borró una corrida anterior del Cron — no es un error,
            # solo significa que esta fila sigue siendo "elegible" (no hay
            # columna de "ya purgado" — ver decisión en memory.py) pero no
            # queda nada físico que borrar de nuevo.
            ya_ausentes += 1
            continue
        try:
            os.remove(ruta)
            borrados += 1
        except OSError as e:
            fallidos += 1
            print(f"ERROR borrando {ruta} (archivo id={archivo['id']}): {e}", file=sys.stderr)

    print(
        f"Expiración de adjuntos ({DIAS_RETENCION} días, corte={corte.date()}): "
        f"{borrados} archivo(s) borrado(s) del disco, {ya_ausentes} ya no estaban "
        f"(corridas previas), {fallidos} fallaron. {len(candidatos)} fila(s) "
        f"elegible(s) en total — el mensaje/registro del chat no se toca."
    )


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as e:
        print(f"ERROR: purga de adjuntos expirados falló — {e}", file=sys.stderr)
        sys.exit(1)
