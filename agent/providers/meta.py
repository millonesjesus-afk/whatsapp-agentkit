# agent/providers/meta.py — Adaptador para Meta WhatsApp Cloud API
# Generado por AgentKit

import os
import hmac
import hashlib
import logging
import httpx
from fastapi import Request
from agent.providers.base import ProveedorWhatsApp, MensajeEntrante

logger = logging.getLogger("agentkit")


class ProveedorMeta(ProveedorWhatsApp):
    """Proveedor de WhatsApp usando la API oficial de Meta (Cloud API)."""

    def __init__(self):
        self.access_token = os.getenv("META_ACCESS_TOKEN")
        self.phone_number_id = os.getenv("META_PHONE_NUMBER_ID")
        self.verify_token = os.getenv("META_VERIFY_TOKEN", "agentkit-verify")
        self.app_secret = os.getenv("META_APP_SECRET")
        # Token de la Página (permiso leads_retrieval) — distinto del token
        # de WhatsApp de arriba, solo hace falta si se usan leads de
        # formulario (Meta Lead Ads/Instant Forms).
        self.page_access_token = os.getenv("META_PAGE_ACCESS_TOKEN")
        self.api_version = "v21.0"

    async def verificar_firma(self, request: Request, body: bytes) -> bool:
        """Verifica la firma HMAC-SHA256 que Meta envía en X-Hub-Signature-256,
        para confirmar que el webhook realmente viene de Meta y no de un tercero."""
        if not self.app_secret:
            logger.warning(
                "META_APP_SECRET no configurado — el webhook NO está verificando "
                "la firma de Meta. Configúralo antes de ir a producción."
            )
            return True
        firma_header = request.headers.get("x-hub-signature-256", "")
        if not firma_header.startswith("sha256="):
            return False
        firma_esperada = hmac.new(self.app_secret.encode(), body, hashlib.sha256).hexdigest()
        firma_recibida = firma_header.removeprefix("sha256=")
        return hmac.compare_digest(firma_esperada, firma_recibida)

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
                    ))
        return mensajes

    async def marcar_leido_y_escribiendo(self, mensaje_id: str) -> bool:
        """Marca el mensaje como leído (doble check azul) y activa el
        indicador de 'escribiendo...' en WhatsApp mientras Gabi genera la
        respuesta — dura hasta 25s o hasta que se envíe el siguiente mensaje,
        que alcanza de sobra para una llamada típica a Claude."""
        if not self.access_token or not self.phone_number_id or not mensaje_id:
            return False
        url = f"https://graph.facebook.com/{self.api_version}/{self.phone_number_id}/messages"
        headers = {
            "Authorization": f"Bearer {self.access_token}",
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

    async def enviar_mensaje(self, telefono: str, mensaje: str) -> bool:
        """Envía mensaje via Meta WhatsApp Cloud API."""
        if not self.access_token or not self.phone_number_id:
            logger.warning("META_ACCESS_TOKEN o META_PHONE_NUMBER_ID no configurados")
            return False
        url = f"https://graph.facebook.com/{self.api_version}/{self.phone_number_id}/messages"
        headers = {
            "Authorization": f"Bearer {self.access_token}",
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

    async def subir_media(self, contenido: bytes, nombre_archivo: str, content_type: str) -> str | None:
        """Sube un archivo a los servidores de Meta (quedan alojados ahí
        temporalmente, ~30 días) y retorna su media_id para poder enviarlo
        con enviar_documento/enviar_imagen."""
        if not self.access_token or not self.phone_number_id:
            logger.warning("META_ACCESS_TOKEN o META_PHONE_NUMBER_ID no configurados")
            return None
        url = f"https://graph.facebook.com/{self.api_version}/{self.phone_number_id}/media"
        headers = {"Authorization": f"Bearer {self.access_token}"}
        data = {"messaging_product": "whatsapp"}
        files = {"file": (nombre_archivo, contenido, content_type)}
        async with httpx.AsyncClient() as client:
            r = await client.post(url, headers=headers, data=data, files=files)
            if r.status_code != 200:
                logger.error(f"Error subiendo media a Meta: {r.status_code} — {r.text}")
                return None
            return r.json().get("id")

    async def enviar_documento(self, telefono: str, media_id: str, nombre_archivo: str, caption: str = "") -> bool:
        """Envía un documento (PDF, etc.) ya subido con subir_media."""
        if not self.access_token or not self.phone_number_id:
            logger.warning("META_ACCESS_TOKEN o META_PHONE_NUMBER_ID no configurados")
            return False
        url = f"https://graph.facebook.com/{self.api_version}/{self.phone_number_id}/messages"
        headers = {
            "Authorization": f"Bearer {self.access_token}",
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

    async def enviar_imagen(self, telefono: str, media_id: str, caption: str = "") -> bool:
        """Envía una imagen ya subida con subir_media."""
        if not self.access_token or not self.phone_number_id:
            logger.warning("META_ACCESS_TOKEN o META_PHONE_NUMBER_ID no configurados")
            return False
        url = f"https://graph.facebook.com/{self.api_version}/{self.phone_number_id}/messages"
        headers = {
            "Authorization": f"Bearer {self.access_token}",
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

    async def enviar_audio(self, telefono: str, media_id: str) -> bool:
        """Envía una nota de voz ya subida con subir_media (debe ser OGG/Opus
        — el mensaje tipo audio de WhatsApp no admite caption)."""
        if not self.access_token or not self.phone_number_id:
            logger.warning("META_ACCESS_TOKEN o META_PHONE_NUMBER_ID no configurados")
            return False
        url = f"https://graph.facebook.com/{self.api_version}/{self.phone_number_id}/messages"
        headers = {
            "Authorization": f"Bearer {self.access_token}",
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

    async def obtener_datos_leadgen(self, leadgen_id: str) -> dict | None:
        """Trae nombre/teléfono/formulario de origen de un lead de Meta Lead
        Ads — el webhook de leadgen solo manda el ID, no los datos."""
        if not self.page_access_token:
            logger.warning("META_PAGE_ACCESS_TOKEN no configurado — no se pueden traer datos de leads de formulario")
            return None
        url = f"https://graph.facebook.com/{self.api_version}/{leadgen_id}"
        params = {"access_token": self.page_access_token}
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
        self, telefono: str, nombre_plantilla: str, parametros: list[str], idioma: str = "es"
    ) -> bool:
        """Envía una plantilla de mensaje aprobada por Meta — necesaria para
        iniciar una conversación con alguien que nunca escribió primero."""
        if not self.access_token or not self.phone_number_id:
            logger.warning("META_ACCESS_TOKEN o META_PHONE_NUMBER_ID no configurados")
            return False
        url = f"https://graph.facebook.com/{self.api_version}/{self.phone_number_id}/messages"
        headers = {
            "Authorization": f"Bearer {self.access_token}",
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
