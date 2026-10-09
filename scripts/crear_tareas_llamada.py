"""Crea y mantiene las tareas de llamada del estado "Para llamar" — 2026-10-09 (diseño D3, aprobado por el dueño).

Detecta a los leads CALLADOS que mostraron interés (silencio de varias horas, puntaje de interés suficiente, sin asesor,
sin pausa, sin resultado), crea una tarea de llamada por cada uno y, en modo activo, la reparte entre los asesores dentro
del horario de atención. Además expira las tareas viejas, cancela las que dejaron de ser válidas (el cliente volvió a
escribir, pasó a una persona…) y aplica el SLA (reasignar una vez; luego "sin hacer" visible al supervisor).

ENTREGADO APAGADO: por negocio, mientras `llamadas_gabi_activo` no sea "1", este script no crea ni cambia nada (solo
limpia tareas de modo activo que hubieran quedado vivas tras apagar el módulo). `llamadas_modo` = sombra (default) solo
REGISTRA tareas para medir; `activo` exige además la aceptación de responsabilidad vigente (ver agent/llamadas.py). Para
configurarlo por script: scripts/configurar_llamadas.py.

No envía ningún mensaje (la oferta de Gabi la manda scripts/procesar_inactividad_clientes.py, apagada por defecto).

Pensado para correr como un Cron Schedule de Railway cada 15 minutos:  */15 * * * *
Uso local (prueba manual, no corre en Railway automáticamente):
    python scripts/crear_tareas_llamada.py
"""
import asyncio
import sys
from pathlib import Path

# Permite correr este script directo (python scripts/archivo.py) — mismo patrón que los demás scripts.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts._cron import ejecutar_cron  # latido: ver scripts/_cron.py

from agent import llamadas
from agent.memory import esperar_base_de_datos


async def main() -> None:
    await esperar_base_de_datos()
    resultados = await llamadas.ejecutar_corrida()
    encendidos = {n: r for n, r in resultados.items() if r.get("modo") in (llamadas.MODO_SOMBRA, llamadas.MODO_ACTIVO)}
    errores = [n for n, r in resultados.items() if "error" in r]
    if not encendidos:
        print(f"Tareas de llamada: apagadas en los {len(resultados)} negocio(s); no se hizo nada.")
    for negocio_id, r in encendidos.items():
        creacion = r.get("creacion") or {}
        print(
            f"Tareas de llamada [{r['modo']}] negocio {negocio_id[:8]}: {creacion.get('creadas', 0)} creada(s) de "
            f"{creacion.get('evaluados', 0)} evaluado(s), {r.get('expiradas', 0)} expirada(s), {r.get('canceladas', 0)} cancelada(s), "
            f"{r.get('asignadas', 0)} asignada(s), {r.get('reasignadas', 0)} reasignada(s), {r.get('escaladas', 0)} sin hacer."
            + (f" Creación omitida: {r['creacion_omitida']}." if r.get("creacion_omitida") else "")
        )
    if errores:
        print(f"Con error (se reintentan en la próxima corrida): {', '.join(n[:8] for n in errores)}")
        raise RuntimeError(f"{len(errores)} negocio(s) con error")


if __name__ == "__main__":
    try:
        asyncio.run(ejecutar_cron("crear_tareas_llamada", main, 15))
    except Exception as e:
        print(f"ERROR: la creación de tareas de llamada falló — {e}", file=sys.stderr)
        sys.exit(1)
