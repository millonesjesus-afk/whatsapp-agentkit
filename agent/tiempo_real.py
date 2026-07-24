# agent/tiempo_real.py — WebSockets del panel: chat en vivo, lista de
# conversaciones en vivo, y "escribiendo..." interno entre miembros del
# equipo.

"""
Registro en memoria de las conexiones WebSocket activas del panel — un solo
proceso en Railway para este proyecto, así que no hace falta un pub/sub
externo (Redis) para esta escala; si el día de mañana se corre en varias
instancias a la vez, esto tendría que moverse a algo compartido entre
procesos.

Dos tipos de evento:
- "mensaje_nuevo" (telefono): se manda a TODAS las conexiones — cada cliente
  decide si le importa (si tiene esa conversación abierta, refresca el chat;
  si no, solo dispara un refresco liviano de la lista/tabla, para que los
  contadores y la vista previa del último mensaje se vean al día).
- "asesor_escribiendo" (telefono, username): solo a quienes tienen ESE lead
  abierto en este momento — no tiene sentido mandarlo a todo el mundo, y
  además molestaría a alguien mirando una conversación distinta.
"""

import logging
from fastapi import WebSocket

logger = logging.getLogger("agentkit")


class GestorConexiones:
    def __init__(self):
        # ws -> {"username": str, "telefono_activo": str | None}
        self._conexiones: dict[WebSocket, dict] = {}

    async def conectar(self, ws: WebSocket, username: str):
        await ws.accept()
        self._conexiones[ws] = {"username": username, "telefono_activo": None}

    def desconectar(self, ws: WebSocket):
        self._conexiones.pop(ws, None)

    def set_telefono_activo(self, ws: WebSocket, telefono: str | None):
        if ws in self._conexiones:
            self._conexiones[ws]["telefono_activo"] = telefono

    async def emitir_mensaje_nuevo(self, telefono: str):
        await self._emitir_a_todos({"tipo": "mensaje_nuevo", "telefono": telefono})

    async def emitir_escribiendo(self, telefono: str, username: str, excluir: WebSocket | None = None):
        evento = {"tipo": "asesor_escribiendo", "telefono": telefono, "username": username}
        for ws, info in list(self._conexiones.items()):
            if info["telefono_activo"] == telefono and ws is not excluir:
                await self._enviar_seguro(ws, evento)

    async def _emitir_a_todos(self, evento: dict):
        for ws in list(self._conexiones.keys()):
            await self._enviar_seguro(ws, evento)

    async def _enviar_seguro(self, ws: WebSocket, evento: dict):
        try:
            await ws.send_json(evento)
        except Exception:
            self.desconectar(ws)


gestor_conexiones = GestorConexiones()
