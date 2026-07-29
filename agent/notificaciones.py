# agent/notificaciones.py — Notificaciones al equipo comercial
# Generado por AgentKit

"""
Mientras la derivación a Genesys Cloud no está lista, avisa por correo
(vía Resend) al equipo comercial cuando un cliente llega al punto de
derivación a un asesor humano — automatiza el primer paso del proceso
actual (supervisor de ventas deriva manualmente al asesor por WhatsApp).
"""

import os
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


async def notificar_lead_derivado(telefono: str, lead: dict, ultimo_mensaje: str) -> bool:
    """
    Envía un correo al equipo comercial avisando que un cliente está listo
    para un asesor. El asunto y el cuerpo dejan explícito si quedó asignado
    automáticamente o si nadie estaba disponible — para que un supervisor
    sepa de inmediato si necesita asignarlo manualmente, en vez de asumir
    que ya lo está atendiendo alguien.
    """
    if not RESEND_API_KEY or not DESTINATARIOS:
        logger.warning("RESEND_API_KEY o destinatarios no configurados; no se envía notificación")
        return False

    nombre = lead.get("nombre") or "(sin nombre)"
    interes = lead.get("interes") or "(sin especificar)"
    asesor_asignado = lead.get("asesor_asignado")

    if asesor_asignado:
        asunto = f"Nuevo lead Gaso+ asignado a {asesor_asignado} — {nombre}"
        aviso_asignacion = f"<p style='color:#15803d'><strong>✅ Asignado automáticamente a:</strong> {asesor_asignado}</p>"
    else:
        asunto = f"⚠️ Lead Gaso+ SIN ASESOR DISPONIBLE — {nombre}"
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
        <p>Este lead fue atendido primero por Gabi, el agente virtual de WhatsApp de Gaso+.</p>
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
