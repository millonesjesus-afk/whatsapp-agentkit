"""Recupera mensajes del cliente que se quedaron SIN respuesta de Gabi —
2026-10-05 (mensajes perdidos).

El webhook guarda el mensaje del cliente de inmediato, pero la respuesta de
Gabi corre después, desacoplada y en MEMORIA (agent/debounce.py): si el
proceso se reinicia o se redespliega en ese rato, o la tarea revienta, el
mensaje queda guardado y nadie lo contesta ni lo vuelve a intentar (la marca
de idempotencia impide que el reintento de Meta lo procese otra vez). Este
barrido busca esos casos y vuelve a disparar la respuesta POR EL MISMO CAMINO
que usa el webhook (`agent.main._generar_y_enviar_respuesta_ia`): mismo
contexto, mismas reglas, mismo envío, mismo guardado.

Qué recupera (ver agent/memory.py::listar_mensajes_sin_respuesta_de_gabi):
leads que Gabi atiende sola (sin asesor, sin pausar, sin escalar a
supervisión, sin cierre, conversación activa) cuyo ÚLTIMO mensaje real es del
cliente y lleva entre 3 minutos y 20 horas sin respuesta. NUNCA toca leads con
asesor, pausados, escalados ni cerrados (vendido / agendado / postventa
incluidos): el filtro vive en la consulta, no aquí.

Tope por mensaje: MÁXIMO 2 intentos de recuperación por mensaje del cliente.
Cada intento queda registrado ANTES de ejecutarse como un evento
`respuesta_recuperada` (payload {mensaje_id}) en el Timeline del lead, así que
un intento que revienta también cuenta. Si la IA está caída, además, el barrido
se DETIENE tras 2 recuperaciones seguidas que fallan por la IA: no martilla a
Anthropic ni al cliente.

Pensado para correr como un Cron Schedule de Railway cada 5-10 minutos (NO está
programado ni desplegado: lo crea el usuario). Necesita las mismas variables de
entorno que el servicio web (ANTHROPIC_API_KEY, CANAL_ENCRYPTION_KEY, base de
datos y credenciales del proveedor): importa agent.main para reutilizar el camino
real de la respuesta.

Uso local (prueba manual):
    python scripts/recuperar_mensajes_sin_respuesta.py
"""
import asyncio
import sys
from pathlib import Path
from typing import Awaitable, Callable

# Permite correr este script directo (python scripts/archivo.py) sin que
# Python se queje de no encontrar el paquete `agent` — mismo patrón que
# scripts/procesar_inactividad_clientes.py.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent.memory import (
    esperar_base_de_datos, listar_mensajes_sin_respuesta_de_gabi, registrar_evento_lead,
    obtener_lead, TIPO_EVENTO_RESPUESTA_RECUPERADA,
)

MIN_MINUTOS = 3
MAX_HORAS = 20
LIMITE = 50
MAX_INTENTOS_POR_MENSAJE = 2
# Recuperaciones seguidas que terminan en falla de la IA antes de abortar el barrido.
MAX_FALLOS_IA_SEGUIDOS = 2


async def recuperar_mensajes_sin_respuesta(
    generar_respuesta: Callable[[str, dict | None], Awaitable[None]] | None = None,
    resolver_canal: Callable[..., Awaitable[dict | None]] | None = None,
    negocio_id: str | None = None,
) -> dict:
    """Una pasada del barrido. `generar_respuesta(telefono, canal)` y
    `resolver_canal(numero_whatsapp_id, negocio_id=...)` se inyectan en las
    pruebas; sin ellas se usa el camino real del webhook (agent.main).

    Retorna los contadores: encontrados, intentados, sin_canal, con_error,
    ia_caida (True si se abortó por fallas seguidas de la IA) y `fallos_ia`."""
    if generar_respuesta is None or resolver_canal is None:
        from agent import main as app_main  # import tardío: arrastra FastAPI, dashboard y las claves de entorno
        generar_respuesta = generar_respuesta or app_main._generar_y_enviar_respuesta_ia
        resolver_canal = resolver_canal or app_main.proveedor.resolver_canal

    casos = await listar_mensajes_sin_respuesta_de_gabi(
        negocio_id=negocio_id, min_minutos=MIN_MINUTOS, max_horas=MAX_HORAS, limite=LIMITE,
        max_intentos=MAX_INTENTOS_POR_MENSAJE,
    )
    resumen = {
        "encontrados": len(casos), "intentados": 0, "sin_canal": 0, "con_error": 0,
        "fallos_ia": 0, "ia_caida": False,
    }
    fallos_ia_seguidos = 0

    for caso in casos:
        telefono, neg_id = caso["telefono"], caso["negocio_id"]
        canal = await resolver_canal(caso["numero_whatsapp_id"], negocio_id=neg_id)
        if not canal:
            # Sin canal no se sabe por cuál número contestar: mandar por el canal
            # por defecto podría responderle desde otro número. Se omite.
            resumen["sin_canal"] += 1
            continue

        # El intento se registra ANTES de ejecutarlo: así cuenta aunque reviente.
        # Si ni siquiera se puede registrar, no se intenta (sin registro no hay tope).
        numero_intento = caso["intentos"] + 1
        try:
            await registrar_evento_lead(
                telefono, tipo=TIPO_EVENTO_RESPUESTA_RECUPERADA,
                descripcion=(
                    f"Se reintentó la respuesta de Gabi a un mensaje del cliente que había quedado sin "
                    f"contestar (intento {numero_intento} de {MAX_INTENTOS_POR_MENSAJE})"
                ),
                autor=None, payload={"mensaje_id": caso["mensaje_id"]},
            )
        except Exception as e:
            print(f"  No se pudo registrar el intento de {telefono}: {e} — se omite", file=sys.stderr)
            resumen["con_error"] += 1
            continue

        resumen["intentados"] += 1
        fallo_ia = False
        try:
            await generar_respuesta(telefono, canal)
        except Exception as e:
            print(f"  Falló la recuperación de {telefono}: {e}", file=sys.stderr)
            resumen["con_error"] += 1
            fallo_ia = True
        else:
            # `_generar_y_enviar_respuesta_ia` no lanza cuando Claude falla: cuenta la
            # falla en el lead (fallos_tecnicos) y responde con el aviso de reintento.
            lead = await obtener_lead(telefono, negocio_id=neg_id)
            fallo_ia = bool(lead and (lead.get("fallos_tecnicos") or 0) > 0)

        if fallo_ia:
            resumen["fallos_ia"] += 1
            fallos_ia_seguidos += 1
            if fallos_ia_seguidos >= MAX_FALLOS_IA_SEGUIDOS:
                resumen["ia_caida"] = True
                break
        else:
            fallos_ia_seguidos = 0

    return resumen


async def main() -> None:
    await esperar_base_de_datos()
    r = await recuperar_mensajes_sin_respuesta()
    print(
        f"Mensajes sin respuesta: {r['encontrados']} encontrado(s), {r['intentados']} recuperación(es) "
        f"intentada(s) (máx. {MAX_INTENTOS_POR_MENSAJE} por mensaje), {r['sin_canal']} sin canal, "
        f"{r['con_error']} con error, {r['fallos_ia']} con falla de la IA."
    )
    if r["ia_caida"]:
        print(
            f"  La IA parece caída ({MAX_FALLOS_IA_SEGUIDOS} fallas seguidas): el barrido se detuvo para no "
            f"insistir. Los casos pendientes se reintentarán en la próxima corrida (hasta su tope)."
        )


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as e:
        print(f"ERROR: la recuperación de mensajes sin respuesta falló — {e}", file=sys.stderr)
        sys.exit(1)
