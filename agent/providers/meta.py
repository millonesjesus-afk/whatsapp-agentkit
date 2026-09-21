# agent/providers/meta.py — Adaptador para Meta WhatsApp Cloud API
# Generado por AgentKit

import os
import json
import hmac
import hashlib
import logging
from fastapi import Request
from agent.providers.base import ProveedorWhatsApp, MensajeEntrante
from agent.memory import listar_canales_whatsapp
from agent.http_utils import post_con_reintentos, get_con_reintentos

logger = logging.getLogger("agentkit")


def _extraer_wamid(respuesta) -> str | None:
    """Extrae el wamid (`id` real del mensaje en WhatsApp) que Meta devuelve
    en el body de una respuesta 200 a un envío — se persiste como
    Mensaje.mensaje_id_meta para poder citarlo después (Reply/Quote) o
    correlacionar reintentos. None si la respuesta no trae el campo
    esperado (no debería pasar con status 200, pero no se asume)."""
    try:
        mensajes = respuesta.json().get("messages") or []
        return mensajes[0].get("id") or None
    except (ValueError, IndexError, AttributeError, KeyError):
        return None


class ProveedorMeta(ProveedorWhatsApp):
    """Proveedor de WhatsApp usando la API oficial de Meta (Cloud API).
    Soporta uno o varios números de WhatsApp (canales) a la vez — los
    canales se administran desde el panel y viven en la base de datos (ver
    memory.py: CanalWhatsApp/listar_canales_whatsapp), así que siempre se
    leen frescos en cada llamada en vez de fijarse al arrancar el proceso."""

    def __init__(self):
        self.verify_token = os.getenv("META_VERIFY_TOKEN", "agentkit-verify")
        self.api_version = "v21.0"

    async def resolver_canal(self, numero_whatsapp_id: str | None, negocio_id: str | None = None) -> dict | None:
        """Encuentra el canal correcto — scoped por Negocio (Gate 5.2,
        Arquitectura Contractual §6/§15: riesgo 🔴 confirmado en Gate 5.1,
        `resolver_canal(None)` podía devolver el canal de otro Negocio).

        Orden de resolución:
        1. `numero_whatsapp_id` (phone_number_id) — ya es una clave única
           real por canal, sin importar a qué Negocio pertenece; resolver
           por acá SIEMPRE es seguro y no cambia de comportamiento.
        2. `negocio_id` explícito — filtra los canales activos a ESE Negocio
           y devuelve el primero. Nunca cruza a canales de otro Negocio.
        3. Sin ningún contexto (ni número ni negocio_id): solo se resuelve
           si TODOS los canales activos pertenecen al mismo Negocio (o no
           tienen `negocio_id` asignado todavía, caso legado) — preserva el
           comportamiento actual para una instalación de un solo Negocio
           real (Cálidda) sin arriesgar nada. Si hay canales de MÁS de un
           Negocio y no hay forma de saber a cuál pertenece esta llamada,
           **falla cerrado** (retorna None) en vez de adivinar — nunca se
           inventa un canal ni se usa "el primero" a ciegas entre Negocios
           distintos."""
        # Gate 5.4 (T2): listar_canales_whatsapp() ahora exige negocio_id en
        # todos sus demás llamadores (panel de administración) — ESTA es la
        # única excepción documentada, a propósito sin negocio_id: esta
        # función es la resolución de identidad en sí (todavía no sabe a qué
        # Negocio pertenece el mensaje entrante), así que filtra por Negocio
        # en Python más abajo, sobre TODOS los canales activos.
        canales = await listar_canales_whatsapp(solo_activos=True)

        if numero_whatsapp_id:
            for canal in canales:
                if canal["phone_number_id"] == numero_whatsapp_id:
                    return canal
            return None

        if negocio_id:
            candidatos = [c for c in canales if c.get("negocio_id") == negocio_id]
            return candidatos[0] if candidatos else None

        negocios_distintos = {c.get("negocio_id") for c in canales}
        if len(negocios_distintos) <= 1:
            # Cero o un solo Negocio detectado entre los canales activos —
            # sin ambigüedad posible, se mantiene el comportamiento actual.
            return canales[0] if canales else None

        logger.error(
            "resolver_canal(None) sin negocio_id: hay canales activos de más de "
            "un Negocio (%s) y no hay contexto suficiente para elegir uno sin "
            "riesgo de cruzar Negocios — se rechaza (fail-closed), no se "
            "selecciona ningún canal por defecto.",
            len(negocios_distintos),
        )
        return None

    async def verificar_firma(self, request: Request, body: bytes) -> bool:
        """Verifica la firma HMAC-SHA256 que Meta envía en X-Hub-Signature-256,
        para confirmar que el webhook realmente viene de Meta y no de un
        tercero.

        Gate 5.2 (Arquitectura Contractual §6): antes de este cambio, la
        firma se probaba contra el app_secret de TODOS los canales activos
        del sistema — "basta con que uno coincida". Con más de un Negocio,
        eso significa que conocer el app_secret de un canal de CUALQUIER
        Negocio bastaba para que un webhook fraudulento, con un
        phone_number_id de OTRO Negocio en el payload, pasara la
        verificación. Ahora: si el payload trae un `phone_number_id`
        identificable (el caso normal, `object == "whatsapp_business_account"`),
        la firma se valida ÚNICAMENTE contra el app_secret del canal
        correspondiente a ESE phone_number_id — nunca contra el de otro
        canal. Si no hay un `phone_number_id` resoluble en el payload (ej.
        webhook de Página/leadgen, `object == "page"`, que no lleva ese
        campo), se conserva el comportamiento anterior (probar contra todos
        los canales activos) porque hoy no hay una forma más precisa de
        acotar ese caso sin anticipar el Gate de atribución.

        Fail-closed en todos los casos: si no hay ningún secreto contra el
        que validar, se rechaza la solicitud (Decisión ya Objetivo de
        Security Architecture, sección 3 — antes esto fallaba abierto)."""
        # Gate 5.4 (T2): mismo motivo que resolver_canal() arriba — antes de
        # verificar la firma todavía no se sabe a qué Negocio pertenece el
        # webhook (ni siquiera hay phone_number_id resoluble en algunos
        # casos, ver comentario de arriba), así que se necesita el universo
        # completo de canales activos para probar la firma contra todos.
        canales = await listar_canales_whatsapp(solo_activos=True)

        phone_number_id = self._extraer_phone_number_id(body)
        if phone_number_id:
            canal = next((c for c in canales if c["phone_number_id"] == phone_number_id), None)
            secretos = {canal["app_secret"]} if canal and canal.get("app_secret") else set()
            if not secretos:
                logger.error(
                    "Webhook con phone_number_id=%s sin canal activo con app_secret "
                    "configurado — se rechaza (fail-closed).", phone_number_id,
                )
                return False
        else:
            secretos = {c["app_secret"] for c in canales if c.get("app_secret")}
            if not secretos:
                logger.error(
                    "Ningún canal tiene app_secret configurado — el webhook rechaza "
                    "la solicitud (fail-closed). Configura app_secret en al menos un canal."
                )
                return False

        firma_header = request.headers.get("x-hub-signature-256", "")
        if not firma_header.startswith("sha256="):
            return False
        firma_recibida = firma_header.removeprefix("sha256=")
        for secreto in secretos:
            firma_esperada = hmac.new(secreto.encode(), body, hashlib.sha256).hexdigest()
            if hmac.compare_digest(firma_esperada, firma_recibida):
                return True
        return False

    @staticmethod
    def _extraer_phone_number_id(body: bytes) -> str | None:
        """Lee `entry[].changes[].value.metadata.phone_number_id` del body
        crudo sin depender de `request.json()` (que ya se consumió/cachea
        aparte en el handler) — devuelve None si el payload no es JSON
        válido o no trae ese campo (ej. webhook de Página/leadgen)."""
        try:
            datos = json.loads(body)
        except (ValueError, TypeError):
            return None
        for entry in datos.get("entry", []):
            for change in entry.get("changes", []):
                phone_number_id = change.get("value", {}).get("metadata", {}).get("phone_number_id")
                if phone_number_id:
                    return phone_number_id
        return None

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
                    media = None
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
                    elif tipo in ("image", "document", "audio"):
                        # Adjunto real (imagen/documento/nota de voz) — el
                        # webhook solo trae el media_id y su metadata, no el
                        # contenido: hay que descargarlo aparte (ver
                        # descargar_media) antes de poder guardarlo/
                        # mostrarlo en el panel. "filename" solo viene en
                        # tipo "document"; "caption" puede venir en
                        # image/document, nunca en audio.
                        objeto_media = msg.get(tipo, {})
                        media = {
                            "media_id": objeto_media.get("id", ""),
                            "mime_type": objeto_media.get("mime_type", ""),
                            "filename": objeto_media.get("filename", ""),
                            "caption": objeto_media.get("caption", ""),
                        }
                        texto = ""
                    else:
                        texto = ""
                    if not msg.get("from"):
                        logger.warning(
                            f"Mensaje entrante sin teléfono (from): id={msg.get('id')} tipo={tipo} "
                            f"campos={sorted(msg.keys())}"
                        )
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
                        media=media,
                    ))
                # Coexistencia: un asesor respondió al cliente directo desde
                # la app de WhatsApp Business en el celular (no desde Gabi ni
                # el panel). Meta lo manda en un campo aparte, "message_echoes"
                # — "to" es el cliente (el negocio es "from" acá, al revés
                # que en un mensaje entrante normal).
                for echo in value.get("message_echoes", []):
                    tipo_echo = echo.get("type", "unknown")
                    texto_echo = echo.get("text", {}).get("body", "") if tipo_echo == "text" else ""
                    if not echo.get("to"):
                        logger.warning(
                            f"Eco sin teléfono (to): id={echo.get('id')} tipo={tipo_echo} "
                            f"campos={sorted(echo.keys())}"
                        )
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
        r = await post_con_reintentos(url, json=payload, headers=headers)
        if r.status_code != 200:
            logger.warning(f"No se pudo marcar leído/escribiendo: {r.status_code} — {r.text}")
        return r.status_code == 200

    async def enviar_mensaje(
        self, telefono: str, mensaje: str, canal: dict | None = None, mensaje_id_citado: str | None = None,
    ) -> tuple[bool, str | None]:
        """Envía mensaje via Meta WhatsApp Cloud API.

        mensaje_id_citado: wamid de otro mensaje que se está citando
        (Reply/Quote) — arma el `context` del payload de Meta. Quien llama
        (dashboard.py:responder_cliente) ya validó que ese wamid exista
        antes de pasarlo acá; esta función no vuelve a validar nada, solo
        lo reenvía tal cual."""
        canal = canal or await self.resolver_canal(None)
        if not canal or not canal.get("access_token"):
            logger.warning("Ningún canal de WhatsApp configurado (META_CANAL_1_* o META_ACCESS_TOKEN/META_PHONE_NUMBER_ID)")
            return False, None
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
        if mensaje_id_citado:
            payload["context"] = {"message_id": mensaje_id_citado}
        r = await post_con_reintentos(url, json=payload, headers=headers)
        if r.status_code != 200:
            logger.error(f"Error Meta API: {r.status_code} — {r.text}")
            return False, None
        return True, _extraer_wamid(r)

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
        r = await post_con_reintentos(url, headers=headers, data=data, files=files)
        if r.status_code != 200:
            logger.error(f"Error subiendo media a Meta: {r.status_code} — {r.text}")
            return None
        return r.json().get("id")

    async def enviar_documento(self, telefono: str, media_id: str, nombre_archivo: str, caption: str = "", canal: dict | None = None) -> tuple[bool, str | None]:
        """Envía un documento (PDF, etc.) ya subido con subir_media."""
        canal = canal or await self.resolver_canal(None)
        if not canal or not canal.get("access_token"):
            logger.warning("Ningún canal de WhatsApp configurado")
            return False, None
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
        r = await post_con_reintentos(url, json=payload, headers=headers)
        if r.status_code != 200:
            logger.error(f"Error Meta API (documento): {r.status_code} — {r.text}")
            return False, None
        return True, _extraer_wamid(r)

    async def enviar_imagen(self, telefono: str, media_id: str, caption: str = "", canal: dict | None = None) -> tuple[bool, str | None]:
        """Envía una imagen ya subida con subir_media."""
        canal = canal or await self.resolver_canal(None)
        if not canal or not canal.get("access_token"):
            logger.warning("Ningún canal de WhatsApp configurado")
            return False, None
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
        r = await post_con_reintentos(url, json=payload, headers=headers)
        if r.status_code != 200:
            logger.error(f"Error Meta API (imagen): {r.status_code} — {r.text}")
            return False, None
        return True, _extraer_wamid(r)

    async def enviar_audio(self, telefono: str, media_id: str, canal: dict | None = None) -> tuple[bool, str | None]:
        """Envía una nota de voz ya subida con subir_media (debe ser OGG/Opus
        — el mensaje tipo audio de WhatsApp no admite caption)."""
        canal = canal or await self.resolver_canal(None)
        if not canal or not canal.get("access_token"):
            logger.warning("Ningún canal de WhatsApp configurado")
            return False, None
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
        r = await post_con_reintentos(url, json=payload, headers=headers)
        if r.status_code != 200:
            logger.error(f"Error Meta API (audio): {r.status_code} — {r.text}")
            return False, None
        return True, _extraer_wamid(r)

    async def descargar_media(self, media_id: str, canal: dict | None = None) -> tuple[bytes, str] | None:
        """Descarga un adjunto ENTRANTE (imagen/documento/nota de voz) desde
        los servidores de Meta. Dos pasos, como exige la API: primero un GET
        a `/{media_id}` para resolver la URL temporal de descarga (expira a
        los pocos minutos, no se puede cachear), después el GET real del
        contenido — ambos con el mismo Bearer token del canal. Retorna
        (contenido, mime_type), o None si el canal no está configurado o
        cualquiera de los dos pasos falla."""
        canal = canal or await self.resolver_canal(None)
        if not canal or not canal.get("access_token"):
            logger.warning("Ningún canal de WhatsApp configurado")
            return None
        headers = {"Authorization": f"Bearer {canal['access_token']}"}
        url_metadata = f"https://graph.facebook.com/{self.api_version}/{media_id}"
        r = await get_con_reintentos(url_metadata, headers=headers)
        if r.status_code != 200:
            logger.error(f"Error obteniendo metadata de media {media_id}: {r.status_code} — {r.text}")
            return None
        datos = r.json()
        url_descarga = datos.get("url")
        mime_type = datos.get("mime_type", "application/octet-stream")
        if not url_descarga:
            logger.error(f"Metadata de media {media_id} sin URL de descarga")
            return None
        r2 = await get_con_reintentos(url_descarga, headers=headers)
        if r2.status_code != 200:
            logger.error(f"Error descargando contenido de media {media_id}: {r2.status_code}")
            return None
        return r2.content, mime_type

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
        r = await get_con_reintentos(url, params=params)
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
        r = await post_con_reintentos(url, json=payload, headers=headers)
        if r.status_code != 200:
            logger.error(f"Error Meta API (plantilla): {r.status_code} — {r.text}")
        return r.status_code == 200
