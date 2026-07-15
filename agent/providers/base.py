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


class ProveedorWhatsApp(ABC):
    """Interfaz que cada proveedor de WhatsApp debe implementar."""

    @abstractmethod
    async def parsear_webhook(self, request: Request) -> list[MensajeEntrante]:
        """Extrae y normaliza mensajes del payload del webhook."""
        ...

    @abstractmethod
    async def enviar_mensaje(self, telefono: str, mensaje: str) -> bool:
        """Envía un mensaje de texto. Retorna True si fue exitoso."""
        ...

    async def validar_webhook(self, request: Request) -> dict | int | None:
        """Verificación GET del webhook (solo Meta la requiere). Retorna respuesta o None."""
        return None

    async def verificar_firma(self, request: Request, body: bytes) -> bool:
        """Verifica que el webhook POST realmente venga del proveedor (firma/HMAC).
        Por defecto no verifica — cada proveedor que lo soporte debe sobreescribirlo."""
        return True

    async def marcar_leido_y_escribiendo(self, mensaje_id: str) -> bool:
        """Marca el mensaje entrante como leído y muestra el indicador de
        'escribiendo...' en WhatsApp mientras se genera la respuesta (puede
        tardar unos segundos por la llamada al modelo). No-op por defecto —
        cada proveedor que lo soporte debe sobreescribirlo."""
        return False
