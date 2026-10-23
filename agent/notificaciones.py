# agent/notificaciones.py — Notificaciones al equipo comercial
# Generado por AgentKit

"""
Mientras la derivación a Genesys Cloud no está lista, avisa por correo
(vía Resend) al equipo comercial cuando un cliente llega al punto de
derivación a un asesor humano — automatiza el primer paso del proceso
actual (supervisor de ventas deriva manualmente al asesor por WhatsApp).
"""

import os
import html
import logging

from agent.http_utils import post_con_reintentos

logger = logging.getLogger("agentkit")

RESEND_API_KEY = os.getenv("RESEND_API_KEY")
REMITENTE = os.getenv("NOTIFICACION_REMITENTE", "onboarding@resend.dev")
DESTINATARIOS = [
    correo.strip()
    for correo in os.getenv("NOTIFICACION_DESTINATARIOS", "").split(",")
    if correo.strip()
]


async def _negocio_cerrado_ahora(negocio_id: str | None) -> bool:
    """True si el negocio está fuera de su horario de atención ahora. Nunca lanza: ante cualquier
    duda (sin negocio, base caída) devuelve False y el correo usa el texto genérico."""
    if not negocio_id:
        return False
    try:
        from agent.tools import obtener_estado_horario_atencion  # import tardío: tools importa de memory
        return not (await obtener_estado_horario_atencion(negocio_id))["dentro_de_horario"]
    except Exception:
        logger.exception("No se pudo consultar el horario de atención para el correo de derivación")
        return False


async def _detalle_del_cierre(negocio_id: str | None) -> str:
    """Calendario de negocio (2026-10-12): el motivo del cierre y cuándo vuelve a atender el equipo, en una frase
    para el correo («Hoy es feriado: Combate de Angamos. El equipo vuelve a atender el viernes 9 a las 8:00 a. m.»).
    Vacío si no hay nada que agregar o ante cualquier falla — el correo sale igual con el texto de siempre."""
    if not negocio_id:
        return ""
    try:
        from agent.tools import obtener_estado_horario_atencion  # import tardío: tools importa de memory
        from agent import calendario_negocio as cal_negocio
        estado = await obtener_estado_horario_atencion(negocio_id)
        if estado.get("dentro_de_horario"):
            return ""
        motivo = cal_negocio.describir_motivo(estado.get("motivo"), estado.get("nombre"))
        partes = []
        if motivo:
            partes.append(f"{motivo[0].upper()}{motivo[1:]}.")
        if estado.get("proxima_apertura_texto"):
            partes.append(f"El equipo vuelve a atender {estado['proxima_apertura_texto']}.")
        return " ".join(partes)
    except Exception:
        logger.exception("No se pudo calcular el detalle del cierre para el correo de derivación")
        return ""


async def notificar_lead_derivado(telefono: str, lead: dict, ultimo_mensaje: str, fuera_de_horario: bool | None = None) -> bool:
    """
    Envía un correo al equipo comercial avisando que un cliente está listo
    para un asesor. El asunto y el cuerpo dejan explícito si quedó asignado
    automáticamente o si nadie estaba disponible — para que un supervisor
    sepa de inmediato si necesita asignarlo manualmente, en vez de asumir
    que ya lo está atendiendo alguien.

    `fuera_de_horario` (2026-10-07): si el lead quedó sin asesor, dice si fue porque el negocio estaba
    cerrado (el lead espera al primer asesor que abra turno) o porque nadie estaba conectado dentro
    del horario. Si no se pasa, se calcula con el horario de atención del negocio del lead.
    """
    if not RESEND_API_KEY or not DESTINATARIOS:
        logger.warning("RESEND_API_KEY o destinatarios no configurados; no se envía notificación")
        return False

    nombre = lead.get("nombre") or "(sin nombre)"
    interes = lead.get("interes") or "(sin especificar)"
    asesor_asignado = lead.get("asesor_asignado")

    if asesor_asignado:
        asunto = f"Nuevo lead Cálidda Hogar asignado a {asesor_asignado} — {nombre}"
        aviso_asignacion = f"<p style='color:#15803d'><strong>✅ Asignado automáticamente a:</strong> {asesor_asignado}</p>"
    else:
        if fuera_de_horario is None:
            fuera_de_horario = await _negocio_cerrado_ahora(lead.get("negocio_id"))
        if fuera_de_horario:
            asunto = f"⚠️ Lead Cálidda Hogar fuera de horario, sin asesor en turno — {nombre}"
            aviso_asignacion = (
                "<p style='color:#b91c1c'><strong>⚠️ No hay asesor en turno</strong> — el cliente escribió "
                "fuera del horario de atención y este lead quedó SIN asignar. Se asignará al primer "
                "asesor que abra turno, o puedes asignarlo tú manualmente desde el panel ahora mismo.</p>"
            )
            detalle_cierre = await _detalle_del_cierre(lead.get("negocio_id"))
            if detalle_cierre:
                aviso_asignacion += f"<p style='color:#b91c1c'>{html.escape(detalle_cierre)}</p>"
        else:
            asunto = f"⚠️ Lead Cálidda Hogar SIN ASESOR DISPONIBLE — {nombre}"
            aviso_asignacion = (
                "<p style='color:#b91c1c'><strong>⚠️ Ningún asesor estaba disponible</strong> — "
                "este lead quedó SIN asignar. Se le asignará automáticamente al primer asesor que "
                "se conecte, o puedes asignarlo tú manualmente desde el panel ahora mismo.</p>"
            )

    cuerpo_html = f"""
        <h2>Nuevo lead listo para atención de un asesor</h2>
        {aviso_asignacion}
        <p><strong>Nombre:</strong> {nombre}</p>
        <p><strong>Teléfono:</strong> {telefono}</p>
        <p><strong>Interés:</strong> {interes}</p>
        <p><strong>Último mensaje del cliente:</strong> {ultimo_mensaje}</p>
        <p>Este lead fue atendido primero por Gabi, el agente virtual de WhatsApp de Cálidda Hogar.</p>
    """

    headers = {
        "Authorization": f"Bearer {RESEND_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "from": REMITENTE,
        "to": DESTINATARIOS,
        "subject": asunto,
        "html": cuerpo_html,
    }

    r = await post_con_reintentos("https://api.resend.com/emails", json=payload, headers=headers)
    if r.status_code >= 300:
        logger.error(f"Error enviando notificación Resend: {r.status_code} — {r.text}")
        return False
    logger.info(f"Notificación de lead derivado enviada a {DESTINATARIOS}")
    return True


async def notificar_solicitud_reseteo(username: str) -> bool:
    """
    Avisa al equipo administrador que alguien pidió recuperar su contraseña
    del panel. No existe un correo propio por usuario todavía, así que el
    reseteo real lo hace un admin manualmente desde "Gestionar asesores"
    (no se manda ningún link de recuperación por ahora).
    """
    if not RESEND_API_KEY or not DESTINATARIOS:
        logger.warning("RESEND_API_KEY o destinatarios no configurados; no se envía notificación de reseteo")
        return False

    asunto = f"Panel Gaso+ — Solicitud de reseteo de contraseña: {username}"
    cuerpo_html = f"""
        <h2>Solicitud de reseteo de contraseña</h2>
        <p>El usuario <strong>{username}</strong> indicó que olvidó su contraseña del panel interno.</p>
        <p>Puedes generarle una nueva desde "Gestionar asesores" en el panel.</p>
    """

    headers = {
        "Authorization": f"Bearer {RESEND_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "from": REMITENTE,
        "to": DESTINATARIOS,
        "subject": asunto,
        "html": cuerpo_html,
    }

    r = await post_con_reintentos("https://api.resend.com/emails", json=payload, headers=headers)
    if r.status_code >= 300:
        logger.error(f"Error enviando notificación de reseteo: {r.status_code} — {r.text}")
        return False
    logger.info(f"Notificación de reseteo de contraseña enviada para {username}")
    return True


# Alerta al DUEÑO DE LA PLATAFORMA (no al equipo comercial) cuando el circuito de la IA se abre o
# se cierra (Fase 1, modo sin IA). Una lista aparte de NOTIFICACION_DESTINATARIOS a propósito:
# aquella es el equipo comercial (supervisores), y esta alerta habla de saldo y credenciales de la
# API — un asunto de quien paga la plataforma, no de las asesoras. Mismo servicio de correo (Resend).
DESTINATARIOS_PLATAFORMA = [
    correo.strip()
    for correo in os.getenv("ALERTA_PLATAFORMA_DESTINATARIOS", "").split(",")
    if correo.strip()
]

_MOTIVO_LEGIBLE = {
    "credito": "el saldo (créditos) de la API de Anthropic se agotó",
    "tope_gasto": "se alcanzó el límite de gasto de la API de Anthropic",
    "auth": "la API de Anthropic rechazó la credencial (clave inválida o sin permiso)",
    "transitorio": "la API de Anthropic falla de forma repetida (errores transitorios)",
}


async def notificar_circuito_ia(abierto: bool, motivo: str, resumen: dict | None = None) -> bool:
    """Un RESUMEN (nunca un correo por lead) para el dueño de la plataforma: el circuito de la IA
    se abrió (Gabi pasa a modo sin IA) o se cerró (Gabi vuelve a responder con IA). `resumen`
    ({"total", "en_cola"}) solo se usa al cerrar: cuántos casos derivó el modo sin IA.

    Siempre deja una línea WARNING en el log (es lo que queda si el correo no está configurado
    o falla). Nunca lanza: una alerta no puede romper el camino de un mensaje."""
    razon = _MOTIVO_LEGIBLE.get(motivo, motivo)
    if abierto:
        asunto = "Maiek AI — Gabi está en MODO SIN IA"
        cuerpo = (
            f"<h2>Gabi pasó a modo sin IA</h2><p>Motivo: {razon}.</p>"
            "<p>Mientras tanto Gabi responde un mensaje automático (sin gastar tokens), transfiere cada "
            "cliente a un asesor y, si no hay ninguno, lo deja en la cola de supervisión. "
            "Se prueba la API con una llamada mínima cada pocos minutos y Gabi vuelve sola cuando responda.</p>"
            "<p>Revisa el saldo y la clave en la consola de Anthropic.</p>"
        )
        logger.warning(f"ALERTA PLATAFORMA — circuito de la IA ABIERTO: {razon}")
    else:
        derivados = (resumen or {}).get("total", 0)
        en_cola = (resumen or {}).get("en_cola", 0)
        asunto = "Maiek AI — Gabi volvió a responder con IA"
        cuerpo = (
            "<h2>Gabi volvió a responder con IA</h2>"
            f"<p>Durante el modo sin IA se derivaron {derivados} cliente(s) a un asesor con un mensaje "
            f"automático; {en_cola} quedaron en la cola de supervisión por no haber asesor.</p>"
        )
        logger.warning(f"ALERTA PLATAFORMA — circuito de la IA CERRADO: {derivados} derivado(s), {en_cola} en cola")

    if not RESEND_API_KEY or not DESTINATARIOS_PLATAFORMA:
        logger.warning("RESEND_API_KEY o ALERTA_PLATAFORMA_DESTINATARIOS no configurados; la alerta del circuito de la IA solo queda en el log")
        return False
    try:
        r = await post_con_reintentos(
            "https://api.resend.com/emails",
            json={"from": REMITENTE, "to": DESTINATARIOS_PLATAFORMA, "subject": asunto, "html": cuerpo},
            headers={"Authorization": f"Bearer {RESEND_API_KEY}", "Content-Type": "application/json"},
        )
        if r.status_code >= 300:
            logger.error(f"Error enviando la alerta del circuito de la IA: {r.status_code} — {r.text}")
            return False
        return True
    except Exception:
        logger.exception("No se pudo enviar la alerta del circuito de la IA")
        return False
