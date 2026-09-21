"""Reengancha (2h) y cierra en silencio (15h) leads donde Gabi respondió y
el CLIENTE se quedó sin contestar — 2026-09-17, pedido explícito del
usuario, investigado el estándar real de mercado para seguimiento de leads
por WhatsApp (horas/días, no los 5-10 min típicos de un widget de chat en
vivo — ver conversación: un timeout de minutos cerraría leads que solo
están ocupados, no perdidos).

Distinto de scripts/liberar_leads_inactivos.py (asesor inactivo, siempre
silencioso): acá el lead NUNCA tuvo asesor asignado ni está pausado — Gabi
sigue activa y respondiendo con normalidad, así que SÍ se le puede mandar
texto libre sin depender de una Plantilla de Meta (seguimos dentro de la
ventana de servicio de 24h que abrió el propio mensaje del cliente).

Dos pasos, ambos medidos desde el MISMO último mensaje del cliente (no
desde el reenganche):
  - A las 2h sin respuesta: UN mensaje de reenganche suave.
  - A las 15h sin respuesta: se cierra en silencio (resultado=
    "sin_respuesta") — la puerta queda abierta, si el cliente escribe en
    cualquier momento después Gabi le responde normal (ver el bloque en
    agent/main.py que limpia "sin_respuesta" apenas eso pasa).

Ver agent/memory.py::listar_leads_inactividad_cliente para la consulta
real — este script es el único punto que hace I/O externo (enviar por
WhatsApp), a propósito fuera de memory.py.

Pensado para correr como un Cron Schedule de Railway (mismo patrón que
scripts/liberar_leads_inactivos.py). Recomendado: cada 30-60 min — el
umbral de 2h tolera perfectamente ese margen de reintento.

Uso local (prueba manual, no corre en Railway automáticamente):
    python scripts/procesar_inactividad_clientes.py
"""
import asyncio
import sys
from pathlib import Path

# Permite correr este script directo (python scripts/archivo.py) sin que
# Python se queje de no encontrar el paquete `agent` — mismo motivo/mismo
# patrón que scripts/liberar_leads_inactivos.py.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent.memory import listar_leads_inactividad_cliente, actualizar_lead, guardar_mensaje
from agent.providers import obtener_proveedor
from agent.tiempo_real import gestor_conexiones

HORAS_REENGANCHE = 2.0
HORAS_CIERRE = 15.0
MENSAJE_REENGANCHE = (
    "¡Hola de nuevo! 👋 Sigo por aquí si tienes alguna otra pregunta o quieres "
    "retomar donde quedamos. Cuéntame en qué te puedo ayudar 😊"
)


async def main() -> None:
    candidatos_reenganche, candidatos_cierre = await listar_leads_inactividad_cliente(
        horas_reenganche=HORAS_REENGANCHE, horas_cierre=HORAS_CIERRE,
    )

    proveedor = obtener_proveedor()
    reenganchados: list[str] = []
    fallidos: list[str] = []
    invalidos: list[str] = []
    for fila in candidatos_reenganche:
        if not fila["telefono"].isdigit():
            invalidos.append(repr(fila["telefono"]))
            continue
        canal = await proveedor.resolver_canal(fila["numero_whatsapp_id"], negocio_id=fila["negocio_id"])
        enviado, wamid = await proveedor.enviar_mensaje(fila["telefono"], MENSAJE_REENGANCHE, canal=canal)
        if not enviado:
            fallidos.append(fila["telefono"])
            continue
        mensaje_guardado = await guardar_mensaje(
            fila["telefono"], "assistant", MENSAJE_REENGANCHE,
            negocio_id=fila["negocio_id"], mensaje_id_meta=wamid,
        )
        await gestor_conexiones.emitir_mensaje_nuevo(mensaje_guardado["conversation_id"])
        reenganchados.append(fila["telefono"])

    for fila in candidatos_cierre:
        await actualizar_lead(fila["telefono"], resultado="sin_respuesta")

    print(
        f"Inactividad de clientes: {len(reenganchados)} reenganchado(s) tras {HORAS_REENGANCHE}h "
        f"({len(fallidos)} fallo(s) de envío), {len(candidatos_cierre)} cerrado(s) por sin respuesta "
        f"tras {HORAS_CIERRE}h."
    )
    if fallidos:
        print(f"  Envíos fallidos a: {', '.join(fallidos)}")
    if invalidos:
        print(f"  Omitidos por teléfono inválido: {', '.join(invalidos)}")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as e:
        print(f"ERROR: procesamiento de inactividad de clientes falló — {e}", file=sys.stderr)
        sys.exit(1)
