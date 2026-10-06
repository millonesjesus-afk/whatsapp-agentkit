"""Lista (SOLO LECTURA) los leads afectados por una falla transitoria de la IA — 2026-10-06.

Caso real (Sandra, 04/10): Claude falló una vez, Gabi le guardó al cliente el texto técnico de error
("Uy, estoy teniendo un problema técnico…") y, como el cliente no volvió a escribir, nadie lo derivó. Este
diagnóstico encuentra a los leads de los últimos N días cuyo último intercambio REAL fue «el cliente escribió →
Gabi contestó solo el texto de error técnico» y a quienes nadie respondió después (ver
agent/memory.py::listar_leads_afectados_por_falla_ia).

No modifica nada, no manda nada, no usa la IA. No es un Cron: por eso NO se envuelve con `ejecutar_cron` (no
debe dejar latidos en `cron_ejecuciones` ni aparecer en el panel como proceso vigilado).

Uso (la base sale de DATABASE_URL, como en los demás scripts):
    python scripts/listar_leads_con_falla_ia.py                    # tabla legible, últimos 14 días
    python scripts/listar_leads_con_falla_ia.py --dias 30
    python scripts/listar_leads_con_falla_ia.py --json             # JSON puro por stdout (para otro proceso)
    python scripts/listar_leads_con_falla_ia.py --solo-ventana-abierta --negocio-id <id>
"""
import argparse
import asyncio
import json
import sys
from pathlib import Path

# Permite correr este script directo (python scripts/archivo.py) — mismo patrón que los demás scripts.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent.memory import esperar_base_de_datos, listar_leads_afectados_por_falla_ia

DIAS_POR_DEFECTO = 14


def formatear_tabla(filas: list[dict]) -> str:
    """Texto legible (una línea por lead) para quien lo corre a mano."""
    if not filas:
        return "Ningún lead afectado por una falla de la IA en el período."
    lineas = [f"{len(filas)} lead(s) afectado(s) por una falla de la IA (hora de Lima):", ""]
    for f in filas:
        ventana = f"ventana abierta hasta {f['ventana_cierra_en_lima']}" if f["ventana_24h_abierta"] else "VENTANA CERRADA (>24 h)"
        estado = (
            f"con {f['asesor_asignado']}" if f["asesor_asignado"]
            else "en cola de supervisión" if f["escalado_supervision_en"]
            else "Gabi pausada" if f["pausado_manual"]
            else "sin asesor"
        )
        lineas.append(
            f"- {f['telefono']} | {f['nombre'] or '(sin nombre)'} | interés: {f['interes'] or '-'} | "
            f"resultado: {f['resultado'] or '-'} | {estado}"
        )
        lineas.append(
            f"    último mensaje del cliente: {f['ultimo_mensaje_cliente_lima']} (hace {f['horas_desde_mensaje']} h) — {ventana}"
        )
        if f["ultimo_mensaje_cliente"]:
            lineas.append(f"    dijo: {f['ultimo_mensaje_cliente']!r}")
    return "\n".join(lineas)


def _argumentos(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Lista leads afectados por una falla transitoria de la IA (solo lectura).")
    parser.add_argument("--dias", type=float, default=DIAS_POR_DEFECTO, help=f"Cuántos días mirar atrás (por defecto {DIAS_POR_DEFECTO}).")
    parser.add_argument("--negocio-id", default=None, help="Limitar a un negocio (por defecto, todos).")
    parser.add_argument("--solo-ventana-abierta", action="store_true", help="Solo los que aún están dentro de las 24 h de WhatsApp.")
    parser.add_argument("--limite", type=int, default=500, help="Máximo de filas (por defecto 500).")
    parser.add_argument("--json", action="store_true", dest="como_json", help="Imprimir JSON puro (lista de objetos) en vez de la tabla.")
    return parser.parse_args(argv)


async def main(argv: list[str] | None = None) -> list[dict]:
    args = _argumentos(argv)
    await esperar_base_de_datos()
    filas = await listar_leads_afectados_por_falla_ia(
        dias=args.dias, negocio_id=args.negocio_id, solo_ventana_abierta=args.solo_ventana_abierta, limite=args.limite,
    )
    if args.como_json:
        print(json.dumps(filas, ensure_ascii=False, indent=2, default=str))
    else:
        print(formatear_tabla(filas))
    return filas


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as e:
        print(f"ERROR: el diagnóstico de falla de la IA falló — {e}", file=sys.stderr)
        sys.exit(1)
