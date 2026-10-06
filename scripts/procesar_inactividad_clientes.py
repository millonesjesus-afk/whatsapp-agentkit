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

Excepción (2026-10-06, falla transitoria de la IA): si lo ÚNICO que el cliente recibió tras su último
mensaje fue el texto de error técnico de Gabi ("Uy, estoy teniendo un problema técnico…"), Gabi nunca le
respondió de verdad. Esos leads vienen marcados `tras_falla_ia` y NO se reenganchan ni se cierran: se derivan
a una persona con `respaldo_sin_ia.derivar_por_falla_ia` (motivo "sin_respuesta_por_falla_ia": asesor, o cola
de supervisión si no hay asesor o la ventana de 24 h ya cerró — sin texto libre en ese caso). Si la
derivación falla, el lead sigue de candidato en la próxima corrida; nunca queda cerrado en silencio.

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

from scripts._cron import ejecutar_cron  # latido: ver scripts/_cron.py

from agent.memory import esperar_base_de_datos, listar_leads_inactividad_cliente, actualizar_lead, guardar_mensaje
from agent.providers import obtener_proveedor
from agent import circuito_ia, envios
from agent.tiempo_real import gestor_conexiones

MOTIVO_DERIVACION_FALLA_IA = "sin_respuesta_por_falla_ia"
HORAS_REENGANCHE = 2.0
HORAS_CIERRE = 15.0
MENSAJE_REENGANCHE = (
    "¡Hola de nuevo! 👋 Sigo por aquí si tienes alguna otra pregunta o quieres "
    "retomar donde quedamos. Cuéntame en qué te puedo ayudar 😊"
)


async def _derivar_real(proveedor, telefono: str, canal: dict, motivo: str) -> dict:
    """Deriva por el mismo camino que el webhook (asesor o cola de supervisión, un solo texto)."""
    from agent import respaldo_sin_ia  # import tardío: arrastra servicio_inteligencia (Claude) y el panel en tiempo real

    return await respaldo_sin_ia.derivar_por_falla_ia(telefono, canal, motivo, proveedor=proveedor)


async def main() -> None:
    await esperar_base_de_datos()
    # Modo sin IA (Fase 1): con el circuito de la IA abierto Gabi no está conversando — los clientes
    # que escribieron ya se derivaron a una persona. Reenganchar ("¡Hola de nuevo!") o cerrar como
    # "sin_respuesta" a quien está esperando a un asesor sería un error. Antes de rendirse se intenta
    # el sondeo (1 token, como mucho cada 5 min): este Cron puede ser quien detecte que ya volvió.
    await circuito_ia.sondear_si_corresponde()
    if await circuito_ia.esta_abierto():
        print("Inactividad de clientes: omitida — Gabi está en modo sin IA (circuito de la IA abierto). No se reengancha ni se cierra a nadie.")
        return
    candidatos_reenganche, candidatos_cierre = await listar_leads_inactividad_cliente(
        horas_reenganche=HORAS_REENGANCHE, horas_cierre=HORAS_CIERRE,
    )

    # Los marcados `tras_falla_ia` se derivan (más abajo); el resto sigue el camino de siempre.
    con_falla_ia = [f for f in candidatos_reenganche + candidatos_cierre if f.get("tras_falla_ia")]
    candidatos_reenganche = [f for f in candidatos_reenganche if not f.get("tras_falla_ia")]
    candidatos_cierre = [f for f in candidatos_cierre if not f.get("tras_falla_ia")]

    proveedor = obtener_proveedor()
    reenganchados: list[str] = []
    bloqueados: list[str] = []
    inciertos: list[str] = []
    fallidos: list[str] = []
    invalidos: list[str] = []
    errores: list[str] = []
    for fila in candidatos_reenganche:
        # Un fallo inesperado con UN lead (red, Meta, base) no aborta la corrida: ni a los demás
        # leads ni al cierre por sin_respuesta de más abajo. Se cuenta como "error" y ese lead
        # sigue de candidato para la próxima corrida.
        try:
            if not fila["telefono"].isdigit():
                invalidos.append(repr(fila["telefono"]))
                continue
            canal = await proveedor.resolver_canal(fila["numero_whatsapp_id"], negocio_id=fila["negocio_id"])
            resultado = await envios.enviar_texto(
                proveedor, fila["telefono"], MENSAJE_REENGANCHE, origen="reenganche_inactividad", canal=canal,
            )
            if resultado.bloqueado:
                # La política de costo lo frenó (ver agent/politica_envios.py): no es una falla.
                # Sigue siendo candidato y se vuelve a evaluar en la próxima corrida.
                bloqueados.append(fila["telefono"])
                continue
            enviado, wamid = resultado
            if resultado.incierto:
                # Meta pudo haber aceptado el mensaje (se perdió la respuesta): NO se reenvía en la
                # próxima corrida. Se guarda como "incierto" para que el lead no siga de candidato.
                await guardar_mensaje(
                    fila["telefono"], "assistant", MENSAJE_REENGANCHE,
                    negocio_id=fila["negocio_id"], mensaje_id_meta=None, estado_envio="incierto",
                )
                inciertos.append(fila["telefono"])
                continue
            if not enviado:
                fallidos.append(fila["telefono"])
                continue
            mensaje_guardado = await guardar_mensaje(
                fila["telefono"], "assistant", MENSAJE_REENGANCHE,
                negocio_id=fila["negocio_id"], mensaje_id_meta=wamid,
            )
            await gestor_conexiones.emitir_mensaje_nuevo(mensaje_guardado["conversation_id"])
            reenganchados.append(fila["telefono"])
        except Exception as e:  # noqa: BLE001 — ver el comentario de arriba
            errores.append(fila.get("telefono", "?"))
            print(f"ERROR reenganchando a {fila.get('telefono', '?')}: {type(e).__name__}: {e}", file=sys.stderr)

    derivados: list[str] = []
    for fila in con_falla_ia:
        try:
            if not fila["telefono"].isdigit():
                invalidos.append(repr(fila["telefono"]))
                continue
            canal = await proveedor.resolver_canal(fila["numero_whatsapp_id"], negocio_id=fila["negocio_id"])
            if not canal:
                # Sin canal no se sabe por cuál número contestar (responder desde otro sería peor): se
                # cuenta como error y el lead sigue de candidato.
                raise RuntimeError("no se pudo resolver el canal de WhatsApp del lead")
            resultado = await _derivar_real(proveedor, fila["telefono"], canal, MOTIVO_DERIVACION_FALLA_IA)
            if resultado.get("accion") in ("derivado_asesor", "cola_supervision"):
                derivados.append(fila["telefono"])
        except Exception as e:  # noqa: BLE001 — un lead con problemas no frena a los demás; se reintenta
            errores.append(fila.get("telefono", "?"))
            print(f"ERROR derivando por falla de la IA a {fila.get('telefono', '?')}: {type(e).__name__}: {e}", file=sys.stderr)

    cerrados = 0
    for fila in candidatos_cierre:
        try:
            await actualizar_lead(fila["telefono"], resultado="sin_respuesta")
            cerrados += 1
        except Exception as e:  # noqa: BLE001
            errores.append(fila.get("telefono", "?"))
            print(f"ERROR cerrando por sin respuesta a {fila.get('telefono', '?')}: {type(e).__name__}: {e}", file=sys.stderr)

    print(
        f"Inactividad de clientes: {len(reenganchados)} reenganchado(s) tras {HORAS_REENGANCHE}h "
        f"({len(fallidos)} fallo(s) de envío, {len(inciertos)} sin confirmar, {len(bloqueados)} frenado(s) por la política de costo), "
        f"{cerrados} cerrado(s) por sin respuesta tras {HORAS_CIERRE}h, {len(errores)} error(es)."
        + (f" {len(derivados)} derivado(s) a una persona por falla de la IA." if con_falla_ia else "")
    )
    if fallidos:
        print(f"  Envíos fallidos a: {', '.join(fallidos)}")
    if errores:
        print(f"  Con error inesperado (se reintentan en la próxima corrida): {', '.join(errores)}")
    if invalidos:
        print(f"  Omitidos por teléfono inválido: {', '.join(invalidos)}")


if __name__ == "__main__":
    try:
        asyncio.run(ejecutar_cron("procesar_inactividad_clientes", main, 30))
    except Exception as e:
        print(f"ERROR: procesamiento de inactividad de clientes falló — {e}", file=sys.stderr)
        sys.exit(1)
