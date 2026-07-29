# agent/providers/__init__.py — Factory de proveedores
# Generado por AgentKit

"""
Selecciona el proveedor de WhatsApp según la variable WHATSAPP_PROVIDER en .env.

Único proveedor soportado hoy: Meta Cloud API. El branch de Twilio se retiró
(Backend Architecture, Decisión local "Retiro del branch roto de twilio",
Fase 1 del Implementation Roadmap) — apuntaba a agent/providers/twilio.py,
que nunca llegó a implementarse; seleccionarlo causaba una falla de arranque
real (ImportError), no una opción funcional.
"""

import os
from agent.providers.base import ProveedorWhatsApp


def obtener_proveedor() -> ProveedorWhatsApp:
    """Retorna el proveedor de WhatsApp configurado en .env."""
    proveedor = os.getenv("WHATSAPP_PROVIDER", "").lower()

    if not proveedor:
        raise ValueError("WHATSAPP_PROVIDER no configurado en .env. Usa: meta")

    if proveedor == "meta":
        from agent.providers.meta import ProveedorMeta
        return ProveedorMeta()
    else:
        raise ValueError(f"Proveedor no soportado: {proveedor}. Usa: meta")
