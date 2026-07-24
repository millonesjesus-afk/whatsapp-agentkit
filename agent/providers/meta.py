# agent/providers/meta.py — Adaptador para Meta WhatsApp Cloud API
# Generado por AgentKit

import os
import hmac
import hashlib
import logging
import httpx
from fastapi import Request
from agent.providers.base import ProveedorWhatsApp, MensajeEntrante
from agent.memory import listar_canales_whatsapp

logger = logging.getLogger("agentkit")


class ProveedorMeta(ProveedorWhatsApp):
    """Proveedor de WhatsApp usando la API oficial de Meta (Cloud API).
    Soporta uno o varios números de WhatsApp (canales) a la vez — los
    canales se administran desde el panel y viven en la base de datos (ver
    memory.py: CanalWhatsApp/listar_canales_whatsapp), así que siempre se
    leen frescos en cada llamada en vez de fijarse al arrancar el proceso."""

    def __init__(self):
        self.verify_token = os.getenv("META_VERIFY_TOKEN", "agentkit-verify")
        self.api_version = "v21.0"

    async def resolver_canal(self, numero_whatsapp_id: str | None) -> dict | None:
        """Encuentra el canal por su phone_number_id. Si no se indica uno
        (código que todavía no lo pasa, o leads creados antes de esta
        función) usa el primero activo como canal por defecto — así una
        instalación con un solo número no nota ninguna diferencia."""
        canales = await listar_canales_whatsapp(solo_activos=True)
        if numero_whatsapp_id:
            for canal in canales:
                if canal["phone_number_id"] == numero_whatsapp_id:
                    return canal
        return canales[0] if canales else None

    async def verificar_firma(self, request: Request, body: bytes) -> bool:
        """Verifica la firma HMAC-SHA256 que Meta envía en X-Hub-Signature-256,
        para confirmar que el webhook realmente viene de Meta y no de un
        tercero. Prueba contra el app_secret de cada canal activo (hoy
        normalmente el mismo para todos, pero no se asume) — basta con que
        uno coincida."""
        canales = await listar_canales_whatsapp(solo_activos=True)
        secretos = {c["app_secret"] for c in canales if c.get("app_secret")}
        if not secretos:
            logger.warning(
                "Ningún canal tiene app_secret configurado — el webhook NO está "
                "verificando la firma de Meta. Configúralo antes de ir a producción."
            )
            return True
        firma_header = request.headers.get("x-hub-signature-256", "")
        if not firma_header.startswith("sha256="):
            return False
        firma_recibida = firma_header.removeprefix("sha256=")
        for secreto in secretos:
            firma_esperada = hmac.new(secreto.encode(), body, hashlib.sha256).hexdigest()
            if hmac.compare_digest(firma_esperada, firma_recibida):
                return True
        return False

    async def validar_webhook(self, request: Request) -> dict | int | None:
        """Meta requiere verificación GET con hub.verify_token."""
        params = request.query_params
        mode = params.get("hub.mode")
        token = params.get("hub.verify_token")
        challenge = params.get("hub.challenge")
        if mode == "subscribe" and token == self.verify_token:
            # Meta espera el challenge como respuesta en texto plano
            return int(challenge)
        return None

    async def parsear_webhook(self, request: Request) -> list[MensajeEntrante]:
        """Parsea el payload anidado de Meta Cloud API."""
        body = await request.json()
        mensajes = []
        for entry in body.get("entry", []):
            for change in entry.get("changes", []):
                value = change.get("value", {})
                numero_whatsapp_id = value.get("metadata", {}).get("phone_number_id", "")
                for msg in value.get("messages", []):
                    tipo = msg.get("type", "unknown")
                    if tipo == "text":
                        texto = msg.get("text", {}).get("body", "")
                    elif tipo == "button":
                        # Clic en un botón de respuesta rápida de una
                        # plantilla (ej. "Sí, cuéntame más" / "No, gracias")
                        # — se trata igual que si el cliente hubiera escrito
                        # ese texto a mano, así Gabi lo procesa normal en
                        # vez de recibir un mensaje vacío o "no soportado".
                        texto = msg.get("button", {}).get("text", "")
                        tipo = "text"
                    else:
                        texto = ""
                    mensajes.append(MensajeEntrante(
                        telefono=msg.get("from", ""),
                        texto=texto,
                        mensaje_id=msg.get("id", ""),
                        es_propio=False,  # Meta solo envía mensajes entrantes
                        tipo=tipo,
                        # Presente solo si el cliente llegó desde un anuncio de
                        # Click-to-WhatsApp (Meta Ads) — trae source_id, headline, etc.
                        referral=msg.get("referral"),
                        numero_whatsapp_id=numero_whatsapp_id,
                    ))
                # Coexistencia: un asesor respondió al cliente directo desde
                # la app de WhatsApp Business en el celular (no desde Gabi ni
                # el panel). Meta lo manda en un campo aparte, "message_echoes"
                # — "to" es el cliente (el negocio es "from" acá, al revés
                # que en un mensaje entrante normal).
                for echo in value.get("message_echoes", []):
                    tipo_echo = echo.get("type", "unknown")
                    texto_echo = echo.get("text", {}).get("body", "") if tipo_echo == "text" else ""
                    mensajes.append(MensajeEntrante(
                        telefono=echo.get("to", ""),
                        texto=texto_echo,
                        mensaje_id=echo.get("id", ""),
                        es_propio=False,
                        tipo=tipo_echo,
                        numero_whatsapp_id=numero_whatsapp_id,
                        tipo_evento="echo",
                    ))
        return mensajes

    async def marcar_leido_y_escribiendo(self, mensaje_id: str, canal: dict | None = None) -> bool:
        """Marca el mensaje como leído (doble check azul) y activa el
        indicador de 'escribiendo...' en WhatsApp mientras Gabi genera la
        respuesta — dura hasta 25s o hasta que se envíe el siguiente mensaje,
        que alcanza de sobra para una llamada típica a Claude."""
        canal = canal or await self.resolver_canal(None)
        if not canal or not canal.get("access_token") or not mensaje_id:
            return False
        url = f"https://graph.facebook.com/{self.api_version}/{canal['phone_number_id']}/messages"
        headers = {
            "Authorization": f"Bearer {canal['access_token']}",
            "Content-Type": "application/json",
        }
        payload = {
            "messaging_product": "whatsapp",
            "status": "read",
            "message_id": mensaje_id,
            "typing_indicator": {"type": "text"},
        }
        async with httpx.AsyncClient() as client:
            r = await client.post(url, json=payload, headers=headers)
            if r.status_code != 200:
                logger.warning(f"No se pudo marcar leído/escribiendo: {r.status_code} — {r.text}")
            return r.status_code == 200

    async def enviar_mensaje(self, telefono: str, mensaje: str, canal: dict | None = None) -> bool:
        """Envía mensaje via Meta WhatsApp Cloud API."""
        canal = canal or await self.resolver_canal(None)
        if not canal or not canal.get("access_token"):
            logger.warning("Ningún canal de WhatsApp configurado (META_CANAL_1_* o META_ACCESS_TOKEN/META_PHONE_NUMBER_ID)")
            return False
        url = f"https://graph.facebook.com/{self.api_version}/{canal['phone_number_id']}/messages"
        headers = {
            "Authorization": f"Bearer {canal['access_token']}",
            "Content-Type": "application/json",
        }
        payload = {
            "messaging_product": "whatsapp",
            "to": telefono,
            "type": "text",
            "text": {"body": mensaje},
        }
        async with httpx.AsyncClient() as client:
            r = await client.post(url, json=payload, headers=headers)
            if r.status_code != 200:
                logger.error(f"Error Meta API: {r.status_code} — {r.text}")
            return r.status_code == 200

    async def subir_media(self, contenido: bytes, nombre_archivo: str, content_type: str, canal: dict | None = None) -> str | None:
        """Sube un archivo a los servidores de Meta (quedan alojados ahí
        temporalmente, ~30 días) y retorna su media_id para poder enviarlo
        con enviar_documento/enviar_imagen. La subida queda asociada al
        número (canal) que se use — hay que usar el mismo canal al enviarlo."""
        canal = canal or await self.resolver_canal(None)
        if not canal or not canal.get("access_token"):
            logger.warning("Ningún canal de WhatsApp configurado")
            return None
        url = f"https://graph.facebook.com/{self.api_version}/{canal['phone_number_id']}/media"
        headers = {"Authorization": f"Bearer {canal['access_token']}"}
        data = {"messaging_product": "whatsapp"}
        files = {"file": (nombre_archivo, contenido, content_type)}
        async with httpx.AsyncClient() as client:
            r = await client.post(url, headers=headers, data=data, files=files)
            if r.status_code != 200:
                logger.error(f"Error subiendo media a Meta: {r.status_code} — {r.text}")
                return None
            return r.json().get("id")

    async def enviar_documento(self, telefono: str, media_id: str, nombre_archivo: str, caption: str = "", canal: dict | None = None) -> bool:
        """Envía un documento (PDF, etc.) ya subido con subir_media."""
        canal = canal or await self.resolver_canal(None)
        if not canal or not canal.get("access_token"):
            logger.warning("Ningún canal de WhatsApp configurado")
            return False
        url = f"https://graph.facebook.com/{self.api_version}/{canal['phone_number_id']}/messages"
        headers = {
            "Authorization": f"Bearer {canal['access_token']}",
            "Content-Type": "application/json",
        }
        documento = {"id": media_id, "filename": nombre_archivo}
        if caption:
            documento["caption"] = caption
        payload = {
            "messaging_product": "whatsapp",
            "to": telefono,
            "type": "document",
            "document": documento,
        }
        async with httpx.AsyncClient() as client:
            r = await client.post(url, json=payload, headers=headers)
            if r.status_code != 200:
                logger.error(f"Error Meta API (documento): {r.status_code} — {r.text}")
            return r.status_code == 200

    async def enviar_imagen(self, telefono: str, media_id: str, caption: str = "", canal: dict | None = None) -> bool:
        """Envía una imagen ya subida con subir_media."""
        canal = canal or await self.resolver_canal(None)
        if not canal or not canal.get("access_token"):
            logger.warning("Ningún canal de WhatsApp configurado")
            return False
        url = f"https://graph.facebook.com/{self.api_version}/{canal['phone_number_id']}/messages"
        headers = {
            "Authorization": f"Bearer {canal['access_token']}",
            "Content-Type": "application/json",
        }
        imagen = {"id": media_id}
        if caption:
            imagen["caption"] = caption
        payload = {
            "messaging_product": "whatsapp",
            "to": telefono,
            "type": "image",
            "image": imagen,
        }
        async with httpx.AsyncClient() as client:
            r = await client.post(url, json=payload, headers=headers)
            if r.status_code != 200:
                logger.error(f"Error Meta API (imagen): {r.status_code} — {r.text}")
            return r.status_code == 200

    async def enviar_audio(self, telefono: str, media_id: str, canal: dict | None = None) -> bool:
        """Envía una nota de voz ya subida con subir_media (debe ser OGG/Opus
        — el mensaje tipo audio de WhatsApp no admite caption)."""
        canal = canal or await self.resolver_canal(None)
        if not canal or not canal.get("access_token"):
            logger.warning("Ningún canal de WhatsApp configurado")
            return False
        url = f"https://graph.facebook.com/{self.api_version}/{canal['phone_number_id']}/messages"
        headers = {
            "Authorization": f"Bearer {canal['access_token']}",
            "Content-Type": "application/json",
        }
        payload = {
            "messaging_product": "whatsapp",
            "to": telefono,
            "type": "audio",
            "audio": {"id": media_id},
        }
        async with httpx.AsyncClient() as client:
            r = await client.post(url, json=payload, headers=headers)
            if r.status_code != 200:
                logger.error(f"Error Meta API (audio): {r.status_code} — {r.text}")
            return r.status_code == 200

    async def obtener_datos_leadgen(self, leadgen_id: str, canal: dict | None = None) -> dict | None:
        """Trae nombre/teléfono/formulario de origen de un lead de Meta Lead
        Ads — el webhook de leadgen solo manda el ID, no los datos."""
        canal = canal or await self.resolver_canal(None)
        page_access_token = canal.get("page_access_token") if canal else None
        if not page_access_token:
            logger.warning("page_access_token no configurado para este canal — no se pueden traer datos de leads de formulario")
            return None
        url = f"https://graph.facebook.com/{self.api_version}/{leadgen_id}"
        params = {"access_token": page_access_token}
        async with httpx.AsyncClient() as client:
            r = await client.get(url, params=params)
            if r.status_code != 200:
                logger.error(f"Error trayendo datos de leadgen {leadgen_id}: {r.status_code} — {r.text}")
                return None
            datos = r.json()
            # field_data trae los campos del formulario como una lista de
            # {name, values} — los nombres estándar son full_name/phone_number,
            # pero puede haber preguntas personalizadas con otros nombres.
            campos = {
                f.get("name", ""): (f.get("values") or [""])[0]
                for f in datos.get("field_data", [])
            }
            return {
                "leadgen_id": leadgen_id,
                "nombre": campos.get("full_name") or campos.get("nombre") or "",
                "telefono": campos.get("phone_number") or campos.get("telefono") or "",
                "ad_id": datos.get("ad_id", ""),
                "form_id": datos.get("form_id", ""),
            }

    async def enviar_plantilla(
        self, telefono: str, nombre_plantilla: str, parametros: list[str], idioma: str = "es", canal: dict | None = None
    ) -> bool:
        """Envía una plantilla de mensaje aprobada por Meta — necesaria para
        iniciar una conversación con alguien que nunca escribió primero."""
        canal = canal or await self.resolver_canal(None)
        if not canal or not canal.get("access_token"):
            logger.warning("Ningún canal de WhatsApp configurado")
            return False
        url = f"https://graph.facebook.com/{self.api_version}/{canal['phone_number_id']}/messages"
        headers = {
            "Authorization": f"Bearer {canal['access_token']}",
            "Content-Type": "application/json",
        }
        componentes = []
        if parametros:
            componentes.append({
                "type": "body",
                "parameters": [{"type": "text", "text": p} for p in parametros],
            })
        payload = {
            "messaging_product": "whatsapp",
            "to": telefono,
            "type": "template",
            "template": {
                "name": nombre_plantilla,
                "language": {"code": idioma},
                "components": componentes,
            },
        }
        async with httpx.AsyncClient() as client:
            r = await client.post(url, json=payload, headers=headers)
            if r.status_code != 200:
                logger.error(f"Error Meta API (plantilla): {r.status_code} — {r.text}")
            return r.status_code == 200
