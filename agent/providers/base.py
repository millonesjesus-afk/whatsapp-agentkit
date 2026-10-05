# agent/providers/base.py — Clase base para proveedores de WhatsApp
# Generado por AgentKit

"""
Define la interfaz común que todos los proveedores de WhatsApp deben implementar.
Esto permite cambiar de proveedor sin modificar el resto del código.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from fastapi import Request


@dataclass
class MensajeEntrante:
    """Mensaje normalizado — mismo formato sin importar el proveedor."""
    telefono: str       # Número del remitente
    texto: str          # Contenido del mensaje (vacío si el tipo no es "text")
    mensaje_id: str     # ID único del mensaje
    es_propio: bool     # True si lo envió el agente (se ignora)
    tipo: str = "text"  # "text" o el tipo original (audio, image, document, etc.)
    referral: dict | None = None  # Datos del anuncio de origen (Meta Click-to-WhatsApp), si aplica
    # ID (phone_number_id de Meta) del número de WhatsApp del NEGOCIO al que
    # llegó este mensaje — permite tener más de un número activo a la vez
    # (ej. pruebas y producción) y responder siempre por el mismo número por
    # el que entró la conversación. Vacío si el proveedor no distingue canales.
    numero_whatsapp_id: str = ""
    # "mensaje" (el cliente escribió) o "echo" (coexistencia: un asesor le
    # respondió al cliente directo desde la app de WhatsApp Business en el
    # celular, no desde el panel). En "echo", telefono es el número del
    # CLIENTE (destinatario del mensaje), no del negocio.
    tipo_evento: str = "mensaje"
    # Metadata del adjunto entrante cuando tipo es "image", "document" o
    # "audio" — {"media_id": str, "mime_type": str, "filename": str,
    # "caption": str}. El webhook solo trae esto (y el media_id), no el
    # contenido real: hay que descargarlo aparte con
    # ProveedorWhatsApp.descargar_media antes de poder guardarlo/mostrarlo.
    # None para "text" y para cualquier tipo no soportado (video, sticker,
    # ubicación, etc. — fuera de alcance).
    media: dict | None = None
    # Mensajes interactivos (toque en un botón de respuesta o en una fila de
    # lista): `interactivo_id` es el id del botón/fila que tocó el cliente
    # (el `texto` ya trae su título, tratado como si lo hubiera escrito) y
    # `contexto_id` es el wamid del mensaje original al que responde
    # (`context.id` del payload de Meta). Vacíos si no aplican.
    interactivo_id: str = ""
    contexto_id: str = ""


class ProveedorWhatsApp(ABC):
    """Interfaz que cada proveedor de WhatsApp debe implementar."""

    @abstractmethod
    async def parsear_webhook(self, request: Request) -> list[MensajeEntrante]:
        """Extrae y normaliza mensajes del payload del webhook."""
        ...

    @abstractmethod
    async def enviar_mensaje(
        self, telefono: str, mensaje: str, canal: dict | None = None, mensaje_id_citado: str | None = None,
    ) -> tuple[bool, str | None]:
        """Envía un mensaje de texto. Retorna (True, wamid) si fue exitoso
        — wamid es el `id` real que Meta le asignó al mensaje (None si el
        proveedor no lo expone), para poder persistirlo como
        Mensaje.mensaje_id_meta y habilitar citarlo después. (False, None)
        si falló.
        canal: el número de WhatsApp del negocio por el que enviar (ver
        resolver_canal) — None usa el canal por defecto del proveedor.
        mensaje_id_citado: wamid de OTRO mensaje que se está citando
        (Reply/Quote — payload `"context": {"message_id": ...}` de Meta).
        None (default) envía un mensaje normal, sin cita."""
        ...

    async def validar_webhook(self, request: Request) -> dict | int | None:
        """Verificación GET del webhook (solo Meta la requiere). Retorna respuesta o None."""
        return None

    def parsear_estados(self, cuerpo: dict) -> list[dict]:
        """Extrae los ESTADOS de entrega de mensajes que el negocio ya envió
        (sent/delivered/read/failed) del payload del webhook, con el precio
        que el proveedor informó. Lista vacía por defecto: solo Meta los
        manda. Cada evento: {wamid, estado, momento, phone_number_id,
        destinatario, pricing, error} — ver ProveedorMeta.parsear_estados."""
        return []

    async def resolver_canal(self, numero_whatsapp_id: str | None, negocio_id: str | None = None) -> dict | None:
        """Dado el ID de un número de WhatsApp del negocio, retorna su
        configuración (token, etc.) para poder enviar por ese canal
        específico. `negocio_id` (Gate 5.2) acota la resolución cuando no
        hay `numero_whatsapp_id` — evita cruzar canales entre Negocios
        distintos, ver ProveedorMeta.resolver_canal. None por defecto —
        solo los proveedores que soportan varios números a la vez lo
        sobreescriben."""
        return None

    async def verificar_firma(self, request: Request, body: bytes) -> bool:
        """Verifica que el webhook POST realmente venga del proveedor (firma/HMAC).
        Por defecto no verifica — cada proveedor que lo soporte debe sobreescribirlo."""
        return True

    async def marcar_leido_y_escribiendo(self, mensaje_id: str, canal: dict | None = None) -> bool:
        """Marca el mensaje entrante como leído y muestra el indicador de
        'escribiendo...' en WhatsApp mientras se genera la respuesta (puede
        tardar unos segundos por la llamada al modelo). No-op por defecto —
        cada proveedor que lo soporte debe sobreescribirlo."""
        return False

    async def subir_media(self, contenido: bytes, nombre_archivo: str, content_type: str, canal: dict | None = None) -> str | None:
        """Sube un archivo a los servidores del proveedor y retorna su id de
        media, para poder enviarlo después con enviar_documento/enviar_imagen
        sin necesitar alojarlo nosotros mismos. None por defecto — cada
        proveedor que lo soporte debe sobreescribirlo."""
        return None

    async def enviar_documento(self, telefono: str, media_id: str, nombre_archivo: str, caption: str = "", canal: dict | None = None) -> tuple[bool, str | None]:
        """Envía un documento (PDF, etc.) ya subido con subir_media. Retorna
        (éxito, wamid) — ver enviar_mensaje. No-op por defecto — cada
        proveedor que lo soporte debe sobreescribirlo."""
        return False, None

    async def enviar_imagen(self, telefono: str, media_id: str, caption: str = "", canal: dict | None = None) -> tuple[bool, str | None]:
        """Envía una imagen ya subida con subir_media. Retorna (éxito,
        wamid) — ver enviar_mensaje. No-op por defecto — cada proveedor que
        lo soporte debe sobreescribirlo."""
        return False, None

    async def enviar_audio(self, telefono: str, media_id: str, canal: dict | None = None) -> tuple[bool, str | None]:
        """Envía una nota de voz ya subida con subir_media. Retorna (éxito,
        wamid) — ver enviar_mensaje. No-op por defecto — cada proveedor que
        lo soporte debe sobreescribirlo."""
        return False, None

    async def descargar_media(self, media_id: str, canal: dict | None = None) -> tuple[bytes, str] | None:
        """Descarga el contenido real de un adjunto ENTRANTE (imagen,
        documento, audio) a partir de su media_id (ver MensajeEntrante.media)
        — el webhook solo trae el id, no el archivo. Retorna (contenido,
        mime_type), o None si el proveedor no lo soporta o la descarga
        falló. No-op por defecto — cada proveedor que lo soporte debe
        sobreescribirlo."""
        return None

    async def obtener_datos_leadgen(self, leadgen_id: str, canal: dict | None = None) -> dict | None:
        """Trae los datos completos (nombre, teléfono, formulario/anuncio de
        origen) de un lead que llegó por un formulario de Meta Ads (Lead
        Ads/Instant Forms) — el webhook solo avisa el ID, hay que pedir el
        detalle aparte. None por defecto — cada proveedor que lo soporte
        debe sobreescribirlo."""
        return None

    async def enviar_plantilla(
        self, telefono: str, nombre_plantilla: str, parametros: list[str], idioma: str = "es", canal: dict | None = None
    ) -> bool:
        """Envía una plantilla de mensaje aprobada — la única forma de que
        el negocio inicie una conversación con alguien que nunca escribió
        primero (ej. un lead de formulario). No-op por defecto — cada
        proveedor que lo soporte debe sobreescribirlo."""
        return False
