# agent/services/servicio_conversacion.py — ServicioConversacion (fachada)
# Generado por AgentKit

"""
Punto de integración del Dominio con la memoria conversacional — Backend
Architecture, componente `ServicioConversacion` ("mensajes, adjuntos,
memoria conversacional y persistente. Reemplaza la lógica de chat hoy
dispersa entre main.py y dashboard.py").

Fase 2 de Backend Architecture (segundo tramo, tras el protocolo de
confianza de IA — MAIEK_AI_PHASE_1_EXECUTION_PLAN.md v1.2, sección 4):
fachada pura sobre las funciones de mensajes/adjuntos de agent/memory.py,
sin reescribir su comportamiento. `agent/main.py` y `agent/dashboard.py`
dejan de llamar a esas funciones de memory.py directamente y pasan a usar
esta clase — es la pieza que formaliza la lógica ya dispersa entre ambos
archivos, tal como pide la definición del componente.
"""

from agent.memory import (
    guardar_mensaje, obtener_historial, obtener_ultimos_mensajes, limpiar_historial,
    crear_archivo_adjunto, obtener_archivo_adjunto, listar_archivos_reutilizables,
    eliminar_archivo_reutilizable, obtener_telefono_de_archivo,
    obtener_mensaje_por_id, obtener_timestamp_ultimo_mensaje_usuario,
)


class ServicioConversacion:
    """Fachada sobre las funciones de mensajes/adjuntos de agent/memory.py
    — ningún otro módulo de Backend las llama directamente, todos pasan
    por acá."""

    async def guardar_mensaje(
        self, telefono: str, role: str, content: str, negocio_id: str, archivo_id: int | None = None, via_app: bool = False,
        mensaje_id_meta: str | None = None, estado_envio: str | None = None,
        respondido_a_id: int | None = None,
    ) -> dict:
        return await guardar_mensaje(
            telefono, role, content, negocio_id, archivo_id=archivo_id, via_app=via_app,
            mensaje_id_meta=mensaje_id_meta, estado_envio=estado_envio,
            respondido_a_id=respondido_a_id,
        )

    async def obtener_mensaje_por_id(self, mensaje_id: int) -> dict | None:
        return await obtener_mensaje_por_id(mensaje_id)

    async def obtener_timestamp_ultimo_mensaje_usuario(self, telefono: str):
        return await obtener_timestamp_ultimo_mensaje_usuario(telefono)

    async def obtener_historial(self, telefono: str, limite: int = 20) -> list[dict]:
        return await obtener_historial(telefono, limite=limite)

    async def obtener_ultimos_mensajes(self, telefonos: list[str], negocio_id: str) -> dict[str, dict]:
        return await obtener_ultimos_mensajes(telefonos, negocio_id)

    async def limpiar_historial(self, telefono: str):
        return await limpiar_historial(telefono)

    async def crear_archivo_adjunto(
        self, nombre_original: str, ruta_disco: str, content_type: str, tamano_bytes: int,
        subido_por: str, reutilizable: bool = False, etiqueta: str | None = None,
    ) -> dict:
        return await crear_archivo_adjunto(
            nombre_original, ruta_disco, content_type, tamano_bytes,
            subido_por, reutilizable=reutilizable, etiqueta=etiqueta,
        )

    async def obtener_archivo_adjunto(self, archivo_id: int) -> dict | None:
        return await obtener_archivo_adjunto(archivo_id)

    async def listar_archivos_reutilizables(self) -> list[dict]:
        return await listar_archivos_reutilizables()

    async def eliminar_archivo_reutilizable(self, archivo_id: int):
        return await eliminar_archivo_reutilizable(archivo_id)

    async def obtener_telefono_de_archivo(self, archivo_id: int) -> str | None:
        return await obtener_telefono_de_archivo(archivo_id)


# Instancia compartida por todo el proceso — mismo patrón que
# servicio_inteligencia, servicio_comercial y servicio_canales.
servicio_conversacion = ServicioConversacion()
