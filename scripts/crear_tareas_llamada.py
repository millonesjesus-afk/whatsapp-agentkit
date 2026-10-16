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

Además corre, AISLADO al final, la SOMBRA del experimento «solo clic» (agent/solo_clic.py, Fase B, 2026-10-16): registra qué
brazo y qué acción le tocarían a cada conversación de «solo clic» y su desenlace a 24/72 h, sin enviar ni llamar a nadie.
Apagada por defecto (`sc_exp_modo`); un error ahí nunca afecta a la creación de tareas. Se configura con
scripts/configurar_solo_clic.py. No hay Cron nuevo: corre dentro de éste.

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


async def _sombra_solo_clic() -> None:
    """Experimento «solo clic», Fase B (agent/solo_clic.py): REGISTRA a qué brazo iría cada conversación de «solo clic» y qué
    habría hecho el sistema, y el desenlace natural a 24 h y 72 h. NO envía ni llama a nadie. Va AISLADO: pase lo que pase aquí
    (la base, un dato raro, un error de código) la creación de tareas de llamada de arriba ya terminó y este bloque jamás lanza.
    Con `sc_exp_modo` apagado (default) solo lee esa clave por negocio y sale. Con la IA caída no corre (Gabi no está
    conversando y el «primer mensaje de Gabi» dejaría de ser comparable)."""
    try:
        from agent import circuito_ia, solo_clic

        if await circuito_ia.esta_abierto():
            return
        resultados = await solo_clic.ejecutar_sombra()
        for negocio_id, r in resultados.items():
            if "error" in r:
                print(f"ERROR en la sombra «solo clic» del negocio {negocio_id[:8]} (no afecta a las tareas de llamada): {r['error']}", file=sys.stderr)
            elif r.get("modo") == solo_clic.MODO_SOMBRA:
                c = r.get("cohorte") or {}
                print(
                    f"Solo clic [sombra] negocio {negocio_id[:8]}: {c.get('registradas', 0)} conversación(es) registrada(s) de "
                    f"{c.get('candidatas', 0)} candidata(s), {r.get('resultados_registrados', 0)} desenlace(s) a 24/72 h."
                )
    except Exception as e:  # noqa: BLE001 — nunca debe romper el Cron de las tareas de llamada
        print(f"ERROR en la sombra «solo clic» (no afecta a las tareas de llamada): {type(e).__name__}: {e}", file=sys.stderr)


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
    await _sombra_solo_clic()
    if errores:
        print(f"Con error (se reintentan en la próxima corrida): {', '.join(n[:8] for n in errores)}")
        raise RuntimeError(f"{len(errores)} negocio(s) con error")


if __name__ == "__main__":
    try:
        asyncio.run(ejecutar_cron("crear_tareas_llamada", main, 15))
    except Exception as e:
        print(f"ERROR: la creación de tareas de llamada falló — {e}", file=sys.stderr)
        sys.exit(1)
