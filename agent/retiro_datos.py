# agent/retiro_datos.py — Pedido de retiro de datos / «no me escriban más» → texto fijo + una persona se encarga (2026-11-11).
#
# Problema (visto en la muestra de calidad del mix Haiku, 2026-11-11): un cliente escribió «quita mi número de su base de datos, para que no me
# escriban». Es un pedido sobre sus datos personales y no es un tema comercial: lo debe gestionar una persona, no un modelo que puede inventar
# datos (Haiku inventó un teléfono de atención). Este módulo lo detecta con REGLAS DETERMINISTAS (sin IA, costo 0, funciona aunque la IA esté caída),
# ANTES de llamar a Claude, y: (1) envía UN texto fijo; (2) pasa el caso a la cola de supervisión (Gabi queda pausada, aparece en la Zona de acción
# de Inicio); (3) deja un evento visible en el Timeline.
#
# El texto NO promete «no te escribiremos más»: hoy no existe una marca de «no contactar» que lo respalde. Promete lo que sí pasa: un asesor gestiona
# la solicitud.
#
# Interruptor por negocio `retiro_datos_modo` = apagado (default) | sombra | activo:
#   · apagado: el camino de Gabi es IDÉNTICO al de siempre (solo se lee esa clave).
#   · sombra:  se evalúa en cada turno; si hay pedido se deja UN evento interno `retiro_datos_sombra` y una línea de log (sin teléfono ni texto). Gabi
#              responde normal.
#   · activo:  lo de arriba. Si el texto no sale, no se toca nada y sigue Gabi.
# Texto configurable con `retiro_datos_texto` (vacío = el de por defecto).
#
# Precisión > recall: ante la duda NO dispara (Gabi responde como siempre). «No me llamen» NO cuenta (muchos clientes piden que no los llamen y
# quieren seguir por WhatsApp). Nunca lanza.

import json
import logging
import re
import unicodedata

from agent import envios
from agent import memory as mem
from agent.services.servicio_conversacion import servicio_conversacion
from agent.tiempo_real import gestor_conexiones

logger = logging.getLogger("agentkit")

CLAVE_MODO = "retiro_datos_modo"
CLAVE_TEXTO = "retiro_datos_texto"
MODO_APAGADO, MODO_SOMBRA, MODO_ACTIVO = "apagado", "sombra", "activo"
MODOS = (MODO_APAGADO, MODO_SOMBRA, MODO_ACTIVO)
TEXTO_POR_DEFECTO = "Entendido, lamento la molestia. Un asesor gestionará tu solicitud para retirar tu número de nuestros contactos."
MENSAJES_DEL_CLIENTE_A_MIRAR = 3      # los últimos mensajes seguidos del cliente que aún no se le respondieron

_VERBO = r"(?:quit|borr|elimin|retir|saqu|sac)\w*"
_DATO = r"(?:numero|contacto|telefono|celular|datos|informacion)"
_PATRONES = (
    re.compile(rf"\b{_VERBO}\b[^.?!]{{0,25}}\b(?:mi|mis) {_DATO}\b"),                     # «quita mi número», «borren mis datos»
    re.compile(rf"\b{_VERBO}\b[^.?!]{{0,40}}\bde (?:su|sus|la|esa|vuestra) base de datos\b"),     # «sáquenme de su base de datos»
    re.compile(r"\bno me (?:escriban|escribas|molesten|molestes|contacten|contactes|sigan escribiendo|sigas escribiendo)\b"),
    re.compile(r"\bdej\w+ de (?:escribir|molestar|contactar)(?:me)?\b"),                    # «dejen de escribirme», «deja de molestar»
    re.compile(r"\bno quiero (?:recibir )?(?:mas )?(?:mensajes|publicidad|que me (?:escriban|contacten|molesten))\b"),
)
_EXCLUYE = re.compile(r"\bno quiero que me (?:quiten|borren|eliminen|retiren|saquen)\b|\bno (?:me )?(?:quiten|borren|eliminen)\b")


def _normalizar(texto: str | None) -> str:
    sin_tildes = "".join(c for c in unicodedata.normalize("NFD", (texto or "").lower()) if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9ñ?!.¿¡ ]+", " ", sin_tildes)).strip()


def detectar(mensajes_cliente: list[str]) -> bool:
    """True si alguno de estos mensajes pide retirar los datos / el número del cliente o que no se le escriba más. PURA."""
    for mensaje in mensajes_cliente:
        n = _normalizar(mensaje)
        if not n or _EXCLUYE.search(n):
            continue
        if any(p.search(n) for p in _PATRONES):
            return True
    return False


async def _modo(negocio_id: str | None) -> str:
    try:
        valor = (await mem.obtener_configuracion(CLAVE_MODO, MODO_APAGADO, negocio_id=negocio_id) or "").strip().lower()
    except Exception:
        return MODO_APAGADO
    return valor if valor in MODOS else MODO_APAGADO


async def _texto(negocio_id: str | None) -> str:
    try:
        propio = " ".join((await mem.obtener_configuracion(CLAVE_TEXTO, "", negocio_id=negocio_id) or "").split())
    except Exception:
        propio = ""
    return propio or TEXTO_POR_DEFECTO


def _en_gestion(lead: dict) -> bool:
    """Un lead que una persona ya trabaja o que ya tiene resultado no es de este módulo: Gabi no responde (o ya cerró) y lo ve su asesor."""
    return bool(
        lead.get("asesor_asignado") or lead.get("pausado_manual") or lead.get("escalado_supervision_en") or (lead.get("resultado") or "")
    )


async def _mensajes_sin_responder(telefono: str) -> list[str]:
    historial = await servicio_conversacion.obtener_historial(telefono)
    seguidos: list[str] = []
    for m in reversed(historial or []):
        if m.get("role") != "user":
            break
        seguidos.append(m.get("content") or "")
        if len(seguidos) >= MENSAJES_DEL_CLIENTE_A_MIRAR:
            break
    return seguidos


async def procesar(telefono: str, canal: dict | None, lead: dict | None, proveedor) -> bool:
    """Punto de entrada desde `main._generar_y_enviar_respuesta_ia`, antes del circuito de IA. True si el turno lo atendió este módulo (Gabi NO
    responde); False en cualquier otro caso —apagado, sombra, sin pedido, lead en gestión, envío fallido o error—: el camino de Gabi sigue igual."""
    try:
        negocio_id = (canal or {}).get("negocio_id")
        modo = await _modo(negocio_id)
        if modo == MODO_APAGADO or not lead or not negocio_id or _en_gestion(lead):
            return False
        if not detectar(await _mensajes_sin_responder(telefono)):
            return False
        logger.info("retiro_datos " + json.dumps({"modo": modo}))
        if modo == MODO_SOMBRA:
            await mem.registrar_evento_lead(
                telefono, tipo=mem.EVENTO_RETIRO_DATOS_SOMBRA, descripcion="Retiro de datos (sombra): se habría derivado a supervisión", autor=None,
                payload={"modo": modo},
            )
            return False
        if (canal or {}).get("modo") == "pruebas":
            return False          # un canal de pruebas no deriva a supervisión (mismo criterio que el triaje)
        return await _ejecutar(telefono, canal, proveedor, negocio_id)
    except Exception:
        logger.exception("retiro_datos: error inesperado — se sigue con Gabi")
        return False


async def _ejecutar(telefono: str, canal: dict | None, proveedor, negocio_id: str) -> bool:
    texto = await _texto(negocio_id)
    try:
        resultado = await envios.enviar_texto(proveedor, telefono, texto, origen="retiro_datos", canal=canal)
    except Exception:
        logger.exception("retiro_datos: falló el envío — el caso sigue su camino")
        return False
    if not (resultado.enviado or resultado.incierto):
        logger.warning(f"retiro_datos: el texto no salió ({resultado.motivo or 'envío fallido'}) — sigue Gabi")
        return False
    conversation_id = None
    try:
        guardado = await servicio_conversacion.guardar_mensaje(
            telefono, "assistant", texto, negocio_id=negocio_id, mensaje_id_meta=resultado.wamid, estado_envio=resultado.estado_envio,
        )
        conversation_id = guardado.get("conversation_id")
    except Exception:
        logger.exception("retiro_datos: el texto salió pero no se pudo guardar el mensaje")
    escalado = False
    try:
        escalado = bool(await mem.enviar_a_cola_de_supervision(telefono, motivo="retiro_datos"))
    except Exception:
        logger.exception("retiro_datos: no se pudo pasar el caso a supervisión")
    try:
        await mem.registrar_evento_lead(
            telefono, tipo=mem.EVENTO_RETIRO_DATOS,
            descripcion=("Pidió que se retire su número o que no se le escriba más — se le respondió con un texto fijo"
                         + (" y el caso pasó a supervisión" if escalado else "; no se pudo pasar a supervisión, revisar a mano")),
            autor=None, payload={"origen": "retiro_datos", "escalado": escalado},
        )
    except Exception:
        logger.exception("retiro_datos: no se pudo registrar el evento")
    try:
        if conversation_id:
            await gestor_conexiones.emitir_mensaje_nuevo(conversation_id)
    except Exception:
        logger.exception("retiro_datos: no se pudo avisar al panel")
    return True
