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

Falla transitoria de la IA (2026-10-06): si Claude falló UNA vez (5xx/429/timeout) y el cliente no volvió a
escribir, lo último que hay guardado es «mensaje del cliente → texto de error técnico de Gabi». Ese texto NO
cuenta como respuesta (agent/memory.py::es_texto_de_error_tecnico): el mensaje se recupera como cualquier otro
(`tras_falla_ia` en la fila). Si el reintento vuelve a fallar, `_generar_y_enviar_respuesta_ia` ya lo deriva
(2.ª falla) sin repetirle el texto técnico al cliente. Y un caso así que pasó de las 20 h sin que se alcanzara a
reintentar se deriva igual (a la cola de supervisión si ya pasaron 24 h): nunca se abandona.

Tope por mensaje: MÁXIMO 2 intentos de recuperación por mensaje del cliente.
Cada intento queda registrado ANTES de ejecutarse como un evento
`respuesta_recuperada` (payload {mensaje_id}) en el Timeline del lead, así que
un intento que revienta también cuenta. Si la IA está caída, además, el barrido
se DETIENE tras 2 recuperaciones seguidas que fallan por la IA: no martilla a
Anthropic ni al cliente.

Modo sin IA (Fase 1): con el circuito de la IA abierto (agent/circuito_ia.py) el barrido no hace
nada — los clientes que escriben ya se derivan a una persona sin llamar a Claude. Antes de rendirse
intenta el sondeo de 1 token (como mucho cada 5 min), así que este Cron también puede ser quien
detecte que la IA volvió. Un fallo por saldo/tope/credencial NO cuenta como intento: el caso se
deriva en el acto (el barrido se detiene, la siguiente corrida sale al ver el circuito abierto). Y
cuando un mensaje ya agotó sus 2 intentos sin respuesta, en vez de abandonarlo se deriva con
`derivar_por_falla_ia` (asesor, o cola de supervisión si no hay ninguno o si pasaron más de 24 h
desde el último mensaje del cliente: la ventana de WhatsApp cerró y no se manda texto libre).

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

from scripts._cron import ejecutar_cron  # latido: ver scripts/_cron.py

from agent import circuito_ia
from datetime import datetime

from agent.memory import (
    esperar_base_de_datos, listar_mensajes_sin_respuesta_de_gabi, registrar_evento_lead,
    obtener_lead, contar_derivados_sin_ia, TIPO_EVENTO_RESPUESTA_RECUPERADA,
)

MIN_MINUTOS = 3
MAX_HORAS = 20
LIMITE = 50
MAX_INTENTOS_POR_MENSAJE = 2
# Recuperaciones seguidas que terminan en falla de la IA antes de abortar el barrido.
MAX_FALLOS_IA_SEGUIDOS = 2
# Los agotados se buscan en una ventana más ancha que la de recuperación: pasadas las 20 h ya no se
# reintenta con la IA, pero un mensaje que se quedó sin respuesta tras sus 2 intentos sigue
# necesitando que una persona lo atienda (si ya pasaron 24 h, derivar lo manda a la cola).
MAX_HORAS_AGOTADOS = 72


async def _derivar_real(telefono: str, canal: dict, motivo: str) -> dict:
    """Deriva por el mismo camino que el webhook: asesor o cola de supervisión, un solo texto."""
    from agent import main as app_main  # import tardío: arrastra FastAPI, dashboard y las claves de entorno
    from agent import respaldo_sin_ia

    return await respaldo_sin_ia.derivar_por_falla_ia(telefono, canal, motivo, proveedor=app_main.proveedor)


async def recuperar_mensajes_sin_respuesta(
    generar_respuesta: Callable[[str, dict | None], Awaitable[None]] | None = None,
    resolver_canal: Callable[..., Awaitable[dict | None]] | None = None,
    negocio_id: str | None = None,
    derivar: Callable[[str, dict, str], Awaitable[dict]] | None = None,
) -> dict:
    """Una pasada del barrido. `generar_respuesta(telefono, canal)` y
    `resolver_canal(numero_whatsapp_id, negocio_id=...)` se inyectan en las
    pruebas; sin ellas se usa el camino real del webhook (agent.main).

    `derivar(telefono, canal, motivo)` también se inyecta en las pruebas; sin ella se usa
    `respaldo_sin_ia.derivar_por_falla_ia` con el proveedor real.

    Retorna los contadores: encontrados, intentados, sin_canal, con_error,
    ia_caida (True si se abortó por fallas seguidas de la IA), `fallos_ia`,
    `circuito_abierto` (True si el circuito de la IA estaba abierto al empezar o se abrió durante
    la corrida) y `derivados_agotados` (mensajes que agotaron sus intentos y se derivaron)."""
    resumen = {
        "encontrados": 0, "intentados": 0, "sin_canal": 0, "con_error": 0,
        "fallos_ia": 0, "ia_caida": False, "circuito_abierto": False, "derivados_agotados": 0,
    }

    # Modo sin IA: con el circuito abierto no se hace nada (se prueba antes si ya volvió).
    await circuito_ia.sondear_si_corresponde()
    if await circuito_ia.esta_abierto():
        resumen["circuito_abierto"] = True
        return resumen

    if generar_respuesta is None or resolver_canal is None:
        from agent import main as app_main  # import tardío: arrastra FastAPI, dashboard y las claves de entorno
        generar_respuesta = generar_respuesta or app_main._generar_y_enviar_respuesta_ia
        resolver_canal = resolver_canal or app_main.proveedor.resolver_canal
    derivar = derivar or _derivar_real

    casos = await listar_mensajes_sin_respuesta_de_gabi(
        negocio_id=negocio_id, min_minutos=MIN_MINUTOS, max_horas=MAX_HORAS, limite=LIMITE,
        max_intentos=MAX_INTENTOS_POR_MENSAJE,
    )
    resumen["encontrados"] = len(casos)
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
        inicio_intento = datetime.utcnow()
        try:
            await generar_respuesta(telefono, canal)
        except Exception as e:
            print(f"  Falló la recuperación de {telefono}: {e}", file=sys.stderr)
            resumen["con_error"] += 1
            fallo_ia = True
        else:
            # Un fallo por saldo/tope/credencial abre el circuito y `_generar_y_enviar_respuesta_ia`
            # ya derivó al cliente: no es un intento fallido (el lead sale solo de los candidatos) y
            # el barrido se detiene — seguir solo gastaría llamadas que van a fallar.
            if await circuito_ia.esta_abierto():
                resumen["intentados"] -= 1
                resumen["circuito_abierto"] = True
                break
            # `_generar_y_enviar_respuesta_ia` no lanza cuando Claude falla: cuenta la
            # falla en el lead (fallos_tecnicos) y responde con el aviso de reintento.
            lead = await obtener_lead(telefono, negocio_id=neg_id)
            fallo_ia = bool(lead and (lead.get("fallos_tecnicos") or 0) > 0)
            if not fallo_ia:
                # La 2.ª falla técnica deriva al cliente y REINICIA el contador (fallos_tecnicos = 0): esa
                # falla se reconoce por el evento `derivado_sin_ia` que dejó durante este intento. Sin esto
                # el barrido creería que funcionó y seguiría golpeando a una IA caída.
                fallo_ia = (await contar_derivados_sin_ia(inicio_intento, negocio_id=neg_id))["total"] > 0

        if fallo_ia:
            resumen["fallos_ia"] += 1
            fallos_ia_seguidos += 1
            if fallos_ia_seguidos >= MAX_FALLOS_IA_SEGUIDOS:
                resumen["ia_caida"] = True
                break
        else:
            fallos_ia_seguidos = 0

    # Los que ya agotaron sus intentos sin respuesta no se abandonan: se derivan a una persona.
    if not resumen["circuito_abierto"]:
        agotados = await listar_mensajes_sin_respuesta_de_gabi(
            negocio_id=negocio_id, min_minutos=MIN_MINUTOS, max_horas=MAX_HORAS_AGOTADOS, limite=LIMITE,
        )
        for caso in agotados:
            # Agotó sus intentos, o es una falla transitoria de la IA que ya pasó de las 20 h sin alcanzar a
            # reintentarse (fuera de la ventana de recuperación): en ambos casos lo atiende una persona.
            vencido_tras_falla = (
                caso.get("tras_falla_ia")
                and (datetime.utcnow() - caso["ultimo_mensaje_en"]).total_seconds() > MAX_HORAS * 3600
            )
            if caso["intentos"] < MAX_INTENTOS_POR_MENSAJE and not vencido_tras_falla:
                continue
            canal = await resolver_canal(caso["numero_whatsapp_id"], negocio_id=caso["negocio_id"])
            if not canal:
                resumen["sin_canal"] += 1
                continue
            try:
                await derivar(
                    caso["telefono"], canal,
                    "sin_respuesta_por_falla_ia" if caso.get("tras_falla_ia") else "mensaje_sin_respuesta",
                )
                resumen["derivados_agotados"] += 1
            except Exception as e:
                print(f"  No se pudo derivar a {caso['telefono']}: {e}", file=sys.stderr)
                resumen["con_error"] += 1

    return resumen


async def main() -> None:
    await esperar_base_de_datos()
    r = await recuperar_mensajes_sin_respuesta()
    if r["circuito_abierto"] and not r["intentados"] and not r["encontrados"]:
        print("Mensajes sin respuesta: omitido — Gabi está en modo sin IA (circuito de la IA abierto).")
        return
    print(
        f"Mensajes sin respuesta: {r['encontrados']} encontrado(s), {r['intentados']} recuperación(es) "
        f"intentada(s) (máx. {MAX_INTENTOS_POR_MENSAJE} por mensaje), {r['sin_canal']} sin canal, "
        f"{r['con_error']} con error, {r['fallos_ia']} con falla de la IA, "
        f"{r['derivados_agotados']} derivado(s) a una persona tras agotar sus intentos."
    )
    if r["circuito_abierto"]:
        print("  El circuito de la IA se abrió durante la corrida: el barrido se detuvo (los casos quedaron derivados).")
    if r["ia_caida"]:
        print(
            f"  La IA parece caída ({MAX_FALLOS_IA_SEGUIDOS} fallas seguidas): el barrido se detuvo para no "
            f"insistir. Los casos pendientes se reintentarán en la próxima corrida (hasta su tope)."
        )


if __name__ == "__main__":
    try:
        asyncio.run(ejecutar_cron("recuperar_mensajes_sin_respuesta", main, 10))
    except Exception as e:
        print(f"ERROR: la recuperación de mensajes sin respuesta falló — {e}", file=sys.stderr)
        sys.exit(1)
