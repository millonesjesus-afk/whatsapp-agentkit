# agent/providers/meta.py — Adaptador para Meta WhatsApp Cloud API
# Generado por AgentKit

import os
import json
import hmac
import hashlib
import logging
from datetime import datetime, timezone
from fastapi import Request
from agent.providers.base import ProveedorWhatsApp, MensajeEntrante
from agent.memory import listar_canales_whatsapp
from agent.http_utils import post_con_reintentos, get_con_reintentos, post_sin_duplicar, EnvioIncierto, RespuestaEnvio
from agent.memory import buscar_wamid_huerfano
import asyncio

logger = logging.getLogger("agentkit")

# Cuánto se espera, ante un envío incierto, a que llegue el webhook de estado
# "sent" de Meta antes de buscar el wamid en `uso_mensajes_meta`.
ESPERA_CONCILIACION_SEGUNDOS = 5


def _es_bsuid(telefono: str) -> bool:
    """Un BSUID (Business-Scoped User ID) es el identificador opaco que
    Meta manda en vez del teléfono real cuando el cliente activó Usernames
    de WhatsApp — no son solo dígitos (ej. "US.13491208655302741918",
    formato documentado por Meta), a diferencia de un teléfono real. Ver
    `_destinatario` — el payload de envío a un BSUID es distinto (usa
    `recipient`, nunca `to`)."""
    return not telefono.replace("+", "").isdigit()


def _destinatario(telefono: str) -> dict:
    """Arma la clave de destinatario del payload de envío de Meta —
    `to` para un teléfono real, `recipient` para un BSUID (Business-Scoped
    User ID). Documentación de Meta: "To send a message using only the
    user's BSUID [...]: set `recipient` to the user's BSUID [...]; omit
    the `to` property." — mandar un BSUID en `to` lo rechaza la API."""
    return {"recipient": telefono} if _es_bsuid(telefono) else {"to": telefono}


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


def _extraer_codigo_error(respuesta) -> int | None:
    """Código numérico del error que Meta devuelve en el body de una respuesta no-200
    (`{"error": {"code": 131047, ...}}`). None si no viene o no es legible."""
    try:
        codigo = (respuesta.json().get("error") or {}).get("code")
        return int(codigo) if codigo is not None else None
    except (ValueError, TypeError, AttributeError):
        return None


async def _esperar(segundos: float) -> None:
    # Función aparte para poder sustituirla en las pruebas.
    await asyncio.sleep(segundos)


async def _enviar_a_meta(url: str, payload: dict, headers: dict, telefono: str, canal: dict, tipo: str = "") -> tuple[bool, str | None]:
    """POST de un envío a /messages SIN reintentos que puedan duplicarlo (ver
    `http_utils.post_sin_duplicar`; Meta Cloud API no tiene clave de
    idempotencia, así que cada copia sería un mensaje más, cobrado y recibido
    por el cliente). Retorna (enviado, wamid) como siempre.

    Si el resultado es incierto (ReadTimeout, 5xx, conexión cortada tras
    enviar) NO reenvía: espera unos segundos, y busca en `uso_mensajes_meta` un
    mensaje a ese cliente, enviado justo ahora, cuyo wamid nadie haya
    reclamado. Si aparece, lo da por enviado con ese wamid. Si no, relanza
    `EnvioIncierto` — NO es un fallo definitivo: el mensaje pudo salir."""
    momento = datetime.utcnow()
    try:
        r = await post_sin_duplicar(url, json=payload, headers=headers)
    except EnvioIncierto as incierto:
        await _esperar(ESPERA_CONCILIACION_SEGUNDOS)
        try:
            wamid = await buscar_wamid_huerfano(canal.get("phone_number_id"), telefono, momento)
        except Exception:
            logger.exception(f"No se pudo consultar uso_mensajes_meta para conciliar el envío incierto a {telefono}")
            wamid = None
        if wamid:
            logger.warning(f"Envío incierto a {telefono} ({incierto.motivo}) conciliado: Meta sí lo recibió ({wamid})")
            return True, wamid
        logger.error(f"Envío incierto a {telefono} ({incierto.motivo}): no apareció en uso_mensajes_meta — no se reenvía")
        raise
    if r.status_code != 200:
        codigo = _extraer_codigo_error(r)
        logger.error(f"Error Meta API{f' ({tipo})' if tipo else ''}: {r.status_code} — {r.text}")
        # Con el código de Meta a la vista, la capa de envíos distingue "fuera de la ventana de 24 h"
        # (131047) de cualquier otra falla (token vencido, canal caído…). Sigue desempaquetándose como (False, None).
        return RespuestaEnvio(False, None, codigo)
    return True, _extraer_wamid(r)


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

    @staticmethod
    def parsear_estados(cuerpo: dict) -> list[dict]:
        """Extrae los estados de entrega (`value.statuses`) del payload de Meta:
        sent / delivered / read / failed de mensajes que el negocio YA envió,
        con el objeto `pricing` que Meta adjunta (en `sent` y en `delivered`
        o `read`) — es la fuente de verdad de si un mensaje fue gratis
        (`free_customer_service`, `free_entry_point`) o cobrable (`regular`) y
        de su categoría (service, utility, marketing, ...). No se calcula ni
        se supone nada acá: se transcribe lo que Meta informó.

        Cada evento: {wamid, estado, momento (UTC naive), phone_number_id,
        destinatario, pricing: {billable, pricing_model, type, category} | None,
        error: {codigo, titulo} | None}. Estados desconocidos y entradas sin
        id se omiten. Solo se conservan código y título de un error —nunca el
        texto libre ni `error_data`— para no volcar nada innecesario."""
        eventos: list[dict] = []
        for entry in cuerpo.get("entry", []) or []:
            for change in entry.get("changes", []) or []:
                value = change.get("value", {}) or {}
                phone_number_id = (value.get("metadata") or {}).get("phone_number_id", "")
                for estado_meta in value.get("statuses", []) or []:
                    wamid = estado_meta.get("id")
                    estado = estado_meta.get("status")
                    if not wamid or estado not in ("sent", "delivered", "read", "failed"):
                        continue
                    try:
                        momento = datetime.fromtimestamp(int(estado_meta.get("timestamp")), tz=timezone.utc).replace(tzinfo=None)
                    except (TypeError, ValueError):
                        momento = None
                    pricing = estado_meta.get("pricing")
                    if isinstance(pricing, dict):
                        pricing = {
                            "billable": pricing.get("billable"),
                            "pricing_model": pricing.get("pricing_model"),
                            "type": pricing.get("type"),
                            "category": pricing.get("category"),
                        }
                    else:
                        pricing = None
                    errores = estado_meta.get("errors") or []
                    error = None
                    if errores and isinstance(errores[0], dict):
                        error = {"codigo": errores[0].get("code"), "titulo": str(errores[0].get("title") or "")[:200]}
                    eventos.append({
                        "wamid": wamid, "estado": estado, "momento": momento,
                        "phone_number_id": phone_number_id, "destinatario": estado_meta.get("recipient_id"),
                        "pricing": pricing, "error": error,
                    })
        return eventos

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
                    interactivo_id = ""
                    if tipo == "text":
                        texto = msg.get("text", {}).get("body", "")
                    elif tipo == "interactive" and (msg.get("interactive") or {}).get("type") in ("button_reply", "list_reply"):
                        # Toque en un botón de respuesta o en una fila de lista
                        # de un mensaje interactivo — se trata igual que si el
                        # cliente hubiera escrito ese título a mano (como el
                        # tipo "button" de plantillas, abajo). El id del botón/
                        # fila queda aparte en `interactivo_id`. Otros subtipos
                        # (nfm_reply de Flows, etc.) siguen como antes: caen en
                        # el `else` final con texto vacío y tipo "interactive".
                        interactivo = msg.get("interactive") or {}
                        respuesta_interactiva = interactivo.get(interactivo["type"]) or {}
                        texto = respuesta_interactiva.get("title") or ""
                        interactivo_id = respuesta_interactiva.get("id") or ""
                        tipo = "text"
                    elif tipo == "button":
                        # Clic en un botón de respuesta rápida de una
                        # plantilla (ej. "Sí, cuéntame más" / "No, gracias")
                        # — se trata igual que si el cliente hubiera escrito
                        # ese texto a mano, así Gabi lo procesa normal en
                        # vez de recibir un mensaje vacío o "no soportado".
                        texto = msg.get("button", {}).get("text", "")
                        tipo = "text"
                    elif tipo == "reaction":
                        # Reacción con un emoji a un mensaje (👍, ❤️…). No es un
                        # mensaje nuevo que atender: main.py lo guarda como una
                        # línea en el historial y nunca dispara a Gabi. Sin
                        # `emoji` el cliente QUITÓ su reacción — no hay nada que
                        # mostrar, `texto` queda vacío.
                        emoji = msg.get("reaction", {}).get("emoji", "")
                        texto = f"Reaccionó con {emoji}" if emoji else ""
                    elif tipo == "location":
                        # Ubicación compartida — se convierte en texto legible
                        # (con enlace a Maps) y se trata como un mensaje normal,
                        # así Gabi lo ve y responde en vez de "no se procesa".
                        ubicacion = msg.get("location", {})
                        detalle = ", ".join(p for p in (ubicacion.get("name"), ubicacion.get("address")) if p)
                        latitud, longitud = ubicacion.get("latitude"), ubicacion.get("longitude")
                        texto = "📍 Ubicación compartida" + (f": {detalle}" if detalle else "")
                        if latitud is not None and longitud is not None:
                            texto += f"\nhttps://maps.google.com/?q={latitud},{longitud}"
                        tipo = "text"
                    elif tipo == "contacts":
                        # Contacto(s) compartido(s) — mismo criterio que la ubicación.
                        compartidos = []
                        for contacto in msg.get("contacts", []):
                            nombre = contacto.get("name", {}).get("formatted_name", "")
                            telefonos = [t.get("phone") or t.get("wa_id") for t in contacto.get("phones", [])]
                            telefono_compartido = next((t for t in telefonos if t), "")
                            compartidos.append(" ".join(p for p in (nombre, f"({telefono_compartido})" if telefono_compartido else "") if p))
                        texto = "👤 Contacto compartido" + (f": {'; '.join(c for c in compartidos if c)}" if any(compartidos) else "")
                        tipo = "text"
                    elif tipo in ("image", "document", "audio", "sticker", "video"):
                        # Adjunto real (imagen/documento/nota de voz/sticker/
                        # video —los GIF de WhatsApp llegan como video—) — el
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
                    # BSUID (Business-Scoped User ID, docs de Meta) — cuando el
                    # cliente activó Usernames de WhatsApp, Meta oculta el
                    # teléfono real y manda `from_user_id` en su lugar (el
                    # contacto trae `user_id` en vez de `wa_id`, mismo patrón).
                    # `_destinatario()` en los envíos ya sabe distinguir un
                    # BSUID de un teléfono real y arma el payload correcto.
                    if not msg.get("from") and not msg.get("from_user_id"):
                        logger.warning(
                            f"Mensaje entrante sin teléfono (from) ni BSUID (from_user_id): id={msg.get('id')} tipo={tipo} "
                            f"campos={sorted(msg.keys())} "
                            f"campos_contacto={[sorted(c.keys()) for c in value.get('contacts', [])]}"
                        )
                    elif not msg.get("from"):
                        logger.info(
                            f"Mensaje entrante con BSUID en vez de teléfono: id={msg.get('id')} tipo={tipo}"
                        )
                    mensajes.append(MensajeEntrante(
                        telefono=msg.get("from") or msg.get("from_user_id", ""),
                        texto=texto,
                        mensaje_id=msg.get("id", ""),
                        es_propio=False,  # Meta solo envía mensajes entrantes
                        tipo=tipo,
                        # Presente solo si el cliente llegó desde un anuncio de
                        # Click-to-WhatsApp (Meta Ads) — trae source_id, headline, etc.
                        referral=msg.get("referral"),
                        numero_whatsapp_id=numero_whatsapp_id,
                        media=media,
                        interactivo_id=interactivo_id,
                        # wamid del mensaje al que el cliente respondió (si
                        # respondió/tocó un botón de uno nuestro).
                        contexto_id=(msg.get("context") or {}).get("id") or "",
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
                            f"campos={sorted(echo.keys())} "
                            f"campos_contacto={[sorted(c.keys()) for c in value.get('contacts', [])]}"
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
            **_destinatario(telefono),
            "type": "text",
            "text": {"body": mensaje},
        }
        if mensaje_id_citado:
            payload["context"] = {"message_id": mensaje_id_citado}
        return await _enviar_a_meta(url, payload, headers, telefono, canal)

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
            **_destinatario(telefono),
            "type": "document",
            "document": documento,
        }
        return await _enviar_a_meta(url, payload, headers, telefono, canal, "documento")

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
            **_destinatario(telefono),
            "type": "image",
            "image": imagen,
        }
        return await _enviar_a_meta(url, payload, headers, telefono, canal, "imagen")

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
            **_destinatario(telefono),
            "type": "audio",
            "audio": {"id": media_id},
        }
        return await _enviar_a_meta(url, payload, headers, telefono, canal, "audio")

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

    async def enviar_interactivo(self, telefono: str, interactivo: dict, canal: dict | None = None) -> tuple[bool, str | None]:
        """Envía un mensaje interactivo de Meta (`reply buttons` de hasta 3 botones, o `list`) dentro de la ventana de
        24 h. `interactivo` es el objeto `interactive` completo (lo arma agent/calificacion_guiada.py). Retorna
        (enviado, wamid) como los demás envíos."""
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
            **_destinatario(telefono),
            "type": "interactive",
            "interactive": interactivo,
        }
        return await _enviar_a_meta(url, payload, headers, telefono, canal, "interactivo")

    async def enviar_plantilla(
        self, telefono: str, nombre_plantilla: str, parametros: list[str], idioma: str = "es", canal: dict | None = None
    ) -> tuple[bool, str | None]:
        """Envía una plantilla de mensaje aprobada por Meta — necesaria para
        iniciar una conversación con alguien que nunca escribió primero.
        Retorna (enviado, wamid), como los demás envíos (antes solo un
        booleano: sin el wamid no se podía cruzar con lo que Meta cobró). La
        capa central (agent/envios.py) acepta ambas formas."""
        canal = canal or await self.resolver_canal(None)
        if not canal or not canal.get("access_token"):
            logger.warning("Ningún canal de WhatsApp configurado")
            return False, None
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
            **_destinatario(telefono),
            "type": "template",
            "template": {
                "name": nombre_plantilla,
                "language": {"code": idioma},
                "components": componentes,
            },
        }
        return await _enviar_a_meta(url, payload, headers, telefono, canal, "plantilla")
