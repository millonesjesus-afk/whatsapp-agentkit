"""Rota automáticamente un lead a un segundo asesor cuando el asignado no
responde en 30 minutos de TURNO (negocio abierto según su Horario de
Atención Y el asesor marcado `disponible`) — y lo libera del todo si ese
segundo asesor tampoco responde en otros 30. Punto 2 (2026-09-29): reemplaza
al mecanismo anterior (24h de RELOJ, sin distinguir turno), pedido explícito
del usuario tras confirmar que 24h era demasiado tiempo sin que nadie se
enterara ("no veo viable que una persona permanezca sin contestar 24 horas
después de que Gabi lo asignó").

SIN avisar al cliente en ningún paso (mismo motivo que el mecanismo
anterior): sin plantilla de WhatsApp aprobada todavía, un mensaje fuera de
la ventana de servicio de 24h de Meta no se puede mandar como texto libre.
Cuando el cliente vuelva a escribir, esa Conversation ya tiene un asesor
(el rotado, o ninguno si se liberó) y el flujo normal de agent/main.py se
encarga solo.

2026-10-07: este mismo Cron también reparte la cola de leads derivados SIN asesor cuando el negocio abre
(agent/asignacion.py::asignar_cola_pendiente_al_abrir).

Ver agent/memory.py::listar_leads_para_rotar_o_liberar y
agent/asignacion.py::rotar_leads_inactivos para la lógica real y el
porqué completo — este script es solo el punto de entrada que Railway
Cron ejecuta.

Pensado para correr como un Cron Schedule de Railway cada 5 minutos (antes
corría cada hora — la granularidad de 30 min por paso de rotación no es
medible con una corrida por hora).

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

from scripts._cron import ejecutar_cron  # latido: ver scripts/_cron.py

from agent.memory import esperar_base_de_datos
from agent.asignacion import ejecutar_ciclo_de_rotacion, asignar_cola_pendiente_al_abrir

INTERVALO_MINUTOS = 5
UMBRAL_ROTACION_MINUTOS = 30


async def main() -> None:
    await esperar_base_de_datos()
    resultado = await ejecutar_ciclo_de_rotacion(
        intervalo_minutos=INTERVALO_MINUTOS, umbral_rotacion_minutos=UMBRAL_ROTACION_MINUTOS,
    )
    rotados, escalados = resultado["rotados"], resultado["escalados"]
    if rotados:
        print(f"Rotados {len(rotados)} lead(s) por inactividad del asesor: {', '.join(rotados)}")
    if escalados:
        print(f"Pasaron a la cola de supervisión {len(escalados)} lead(s) que ningún asesor atendió: {', '.join(escalados)}")
    if not rotados and not escalados:
        print("Ningún lead rotó ni pasó a supervisión en esta corrida.")

    # 2026-10-07 (Fase 1 de la política de asignación): un lead derivado con el negocio cerrado queda sin
    # asesor y con Gabi activa; apenas el negocio abre se reparte acá, primero el que antes cierra su
    # ventana de 24 h de WhatsApp. Va DESPUÉS de la rotación: los que esta acaba de pasar a supervisión
    # ya no están en la cola.
    cola = await asignar_cola_pendiente_al_abrir()
    asignados, pendientes = cola["asignados"], cola["pendientes"]
    if asignados:
        print(f"Cola al abrir: asignó {len(asignados)} lead(s) derivado(s) sin asesor: "
              + ", ".join(f"{tel}->{asesor}" for tel, asesor in asignados))
    else:
        print("Cola al abrir: asignó 0 lead(s).")
    if pendientes:
        print(f"Quedan {pendientes} lead(s) derivado(s) esperando asesor (tope por corrida o sin asesores disponibles).")


if __name__ == "__main__":
    try:
        asyncio.run(ejecutar_cron("liberar_leads_inactivos", main, 5))
    except Exception as e:
        print(f"ERROR: rotación de leads inactivos falló — {e}", file=sys.stderr)
        sys.exit(1)
