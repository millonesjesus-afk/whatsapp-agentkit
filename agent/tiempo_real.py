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
- "mensaje_nuevo" (telefono): se manda SOLO a las conexiones cuyo usuario
  tiene acceso real a ese lead (mismo criterio que _verificar_acceso_lead en
  dashboard.py: admin/supervisor ven todo, un asesor solo lo suyo — ver
  tiene_acceso_a_lead en agent/memory.py). Antes se mandaba a TODAS las
  conexiones sin filtrar: cualquier miembro del equipo conectado al panel
  se enteraba del teléfono (PII) de leads ajenos con solo tener el panel
  abierto. Cada cliente que SÍ lo recibe decide si le importa más allá de
  eso (si tiene esa conversación abierta, refresca el chat; si no, solo
  dispara un refresco liviano de la lista/tabla).
- "asesor_escribiendo" (telefono, username): solo a quienes tienen ESE lead
  abierto en este momento (telefono_activo) — no tiene sentido mandarlo a
  todo el mundo, y además molestaría a alguien mirando una conversación
  distinta. No se filtra por acceso además de eso: si alguien ya tiene el
  lead abierto como telefono_activo es porque `ver_lead` ya validó su
  acceso al conectarlo (ver websocket_panel en dashboard.py).

  La exclusión de quien disparó la señal es por USERNAME, no por identidad
  de objeto WebSocket (ver emitir_escribiendo) — con la arquitectura SSE +
  relay del BFF (maiek-frontend), la señal saliente de "escribiendo" abre
  una conexión WS efímera nueva (POST /api/conversaciones/escribiendo ->
  un WS de un solo uso hacia acá) DISTINTA de la conexión persistente que
  ese mismo usuario tiene abierta para recibir el relay SSE — excluir por
  `ws is not excluir` nunca podía coincidir entre esas dos conexiones, así
  que el usuario terminaba viendo su propio "X está escribiendo...".
  Excluir por username filtra TODAS las conexiones de esa persona sobre
  ese lead, sin importar cuál está "escuchando" — sigue funcionando igual
  para el panel legado (una sola conexión persistente por asesor).
"""

import logging
import time
from fastapi import WebSocket

from agent.memory import obtener_lead, tiene_acceso_a_lead

logger = logging.getLogger("agentkit")

# 4408: cerrada por inactividad (Gate 4.1, cuarta capa de hardening — ver
# GestorConexiones.cerrar_inactivas). No colisiona con 4401 (sesión), 4403
# (Origin) ni 4409 (duplicada).
CODIGO_WS_INACTIVA = 4408


class GestorConexiones:
    def __init__(self):
        # ws -> {"username": str, "rol": str, "telefono_activo": str | None,
        #        "ultima_actividad": float (time.monotonic())}
        self._conexiones: dict[WebSocket, dict] = {}

    async def conectar(self, ws: WebSocket, username: str, rol: str):
        """`rol` se guarda al conectar (no se vuelve a resolver en cada
        emisión) — evita una consulta a la base de datos por conexión en
        cada mensaje nuevo del sistema entero, a costa de que un cambio de
        rol de alguien no tome efecto hasta que reconecte (misma sesión de
        navegador ya trae el panel recargado si eso pasa, en la práctica no
        es un problema real)."""
        await ws.accept()
        self._conexiones[ws] = {
            "username": username, "rol": rol, "telefono_activo": None,
            "ultima_actividad": time.monotonic(),
        }

    def desconectar(self, ws: WebSocket):
        self._conexiones.pop(ws, None)

    async def set_telefono_activo(self, ws: WebSocket, telefono: str | None):
        """Garantiza como máximo 1 conexión activa por usuario+conversación
        (Gate 4.1, remediación de conexión huérfana).

        Por qué esto vive ACÁ y no depende de que el cliente avise que se
        desconectó: instrumentando el relay del BFF (`app/api/conversaciones/
        stream/route.ts`) y este mismo gestor se confirmó en vivo que, bajo
        ráfagas de navegación muy rápida entre conversaciones, el cierre de
        una conexión vieja puede perderse A NIVEL DE TRANSPORTE antes de
        llegar al servidor — ni `cancel()` del `ReadableStream` ni el evento
        `abort` de `req.signal` del lado del relay llegan a dispararse para
        esa conexión puntual. Cuando eso pasa, esa conexión queda con su WS
        servidor-a-servidor abierto para siempre, sin que ningún aviso de
        cierre vaya a llegar nunca — no hay forma de "esperar la señal"
        porque la señal directamente no existe para esa conexión.

        Por eso la garantía real de "máximo 1" se aplica acá, al REVÉS: en
        vez de esperar a que la conexión vieja avise que se va, la conexión
        NUEVA (cuyo `ver_lead` sí llegó, por definición, porque es la que se
        está procesando ahora) cierra activamente cualquier otra que ya esté
        mirando la MISMA conversación bajo el MISMO usuario. Acotado a
        (usuario, teléfono) — no a "1 conexión por usuario" a secas — para no
        romper el caso legítimo de un usuario con 2 pestañas mirando 2
        conversaciones distintas al mismo tiempo.

        Limitación conocida: esto cierra duplicados cuando una conexión
        NUEVA para la misma (usuario, teléfono) efectivamente llega. Si una
        conexión queda huérfana y el usuario nunca vuelve a esa MISMA
        conversación (p. ej. cerró la pestaña y el aviso de cierre se perdió
        en el mismo viaje), esta conexión puntual no tiene un mecanismo que
        la reclame — no se resolvió acá por no ampliar el alcance de esta
        remediación; ver reporte de la investigación."""
        if ws not in self._conexiones:
            return
        self._conexiones[ws]["telefono_activo"] = telefono
        self._conexiones[ws]["ultima_actividad"] = time.monotonic()
        if telefono is None:
            return
        username = self._conexiones[ws]["username"]
        duplicadas = [
            otro for otro, info in list(self._conexiones.items())
            if otro is not ws and info["username"] == username and info["telefono_activo"] == telefono
        ]
        for otro in duplicadas:
            logger.info(
                "Cerrando conexión WS duplicada del panel (usuario=%s, telefono=%s) — "
                "reemplazada por una conexión más nueva para la misma conversación.",
                username, telefono,
            )
            try:
                await otro.close(code=4409)  # 4409: cerrada por duplicado (mismo usuario+conversación) — no colisiona con 4401/4403 (sesión/origin).
            except Exception:
                pass
            self.desconectar(otro)

    def tocar_actividad(self, username: str, telefono: str) -> None:
        """Marca a (usuario, teléfono) como recién visto — llamado desde
        `GET /lead/{telefono}/mensajes.json` (agent/dashboard.py), el
        endpoint que el polling incondicional del panel golpea cada 20s
        SIEMPRE que esa conversación está abierta en pantalla
        (`usePollingIncondicional` en maiek-frontend), sin importar el
        estado del WS/SSE.

        Por qué ESTA señal y no el tráfico del propio WS (p. ej. "ver_lead"):
        investigado en vivo (Gate 4.1, hardening de idle timeout) que el
        relay del BFF (`app/api/conversaciones/stream/route.ts`) reconecta
        PROACTIVAMENTE su WS a este backend cada `RECONEXION_PROACTIVA_MS`
        (~4.5 min) para sobrevivir al tope de duración de una Function de
        Vercel — y ese reconnect vuelve a mandar "ver_lead" él solo, sin que
        haya ningún navegador real del otro lado. Si "actividad" se midiera
        con ese tráfico, una conexión de relay huérfana (el caso confirmado
        de este Gate: la señal de cierre del navegador se pierde a nivel de
        transporte) se mantendría viva PARA SIEMPRE, renovándose sola cada
        ~4.5 min — exactamente el bug que este mecanismo tiene que cerrar.
        El polling incondicional, en cambio, es una petición HTTP nueva y
        autenticada que SOLO un navegador real con la conversación montada
        en pantalla puede generar — el relay no tiene forma de simularla por
        su cuenta."""
        ahora = time.monotonic()
        for info in self._conexiones.values():
            if info["username"] == username and info["telefono_activo"] == telefono:
                info["ultima_actividad"] = ahora

    async def cerrar_inactivas(self, umbral_segundos: float) -> int:
        """Barrido periódico (ver la tarea en segundo plano de
        `agent/main.py`, `lifespan`) — cierra activamente cualquier conexión
        cuya última actividad real (`tocar_actividad`, o el `ver_lead`
        inicial) tenga más de `umbral_segundos`.

        Gate 4.1, cuarta capa de hardening: a diferencia de la expulsión de
        duplicados (`set_telefono_activo`), esta NO depende de que llegue una
        conexión nueva para la MISMA conversación — cubre exactamente lo que
        esa limitación conocida deja afuera (ver su docstring): el usuario
        nunca vuelve a esa conversación, así que ninguna conexión nueva va a
        llegar nunca a expulsar a la vieja.

        Retorna cuántas conexiones cerró (para logging/instrumentación de
        pruebas)."""
        ahora = time.monotonic()
        inactivas = [
            ws for ws, info in list(self._conexiones.items())
            if ahora - info["ultima_actividad"] > umbral_segundos
        ]
        for ws in inactivas:
            info = self._conexiones.get(ws, {})
            logger.info(
                "Cerrando conexión WS del panel por inactividad (usuario=%s, telefono=%s, "
                "inactiva hace %.0fs) — Gate 4.1, idle timeout.",
                info.get("username", "?"), info.get("telefono_activo", "?"),
                ahora - info.get("ultima_actividad", ahora),
            )
            try:
                await ws.close(code=CODIGO_WS_INACTIVA)
            except Exception:
                pass
            self.desconectar(ws)
        return len(inactivas)

    async def emitir_mensaje_nuevo(self, telefono: str):
        """Filtra por acceso ANTES de emitir — una sola consulta al lead
        (no una por conexión) para saber a quién le corresponde."""
        lead = await obtener_lead(telefono)
        asesor_asignado = lead.get("asesor_asignado") if lead else None
        evento = {"tipo": "mensaje_nuevo", "telefono": telefono}
        for ws, info in list(self._conexiones.items()):
            if tiene_acceso_a_lead(info["rol"], info["username"], asesor_asignado):
                await self._enviar_seguro(ws, evento)

    async def emitir_escribiendo(self, telefono: str, nombre_mostrar: str, excluir_username: str):
        """`nombre_mostrar` es lo que se muestra en el aviso ("X está
        escribiendo...") — puede repetirse entre personas. `excluir_username`
        es el username (login, único) de quien disparó la señal: se excluyen
        TODAS sus conexiones sobre este lead, no solo la que originó el
        evento (ver comentario de cabecera — la conexión que dispara la señal
        y la que la recibiría de vuelta pueden ser dos WebSockets distintos
        del mismo usuario)."""
        evento = {"tipo": "asesor_escribiendo", "telefono": telefono, "username": nombre_mostrar}
        for ws, info in list(self._conexiones.items()):
            if info["telefono_activo"] == telefono and info["username"] != excluir_username:
                await self._enviar_seguro(ws, evento)

    async def _enviar_seguro(self, ws: WebSocket, evento: dict):
        try:
            await ws.send_json(evento)
        except Exception:
            self.desconectar(ws)


gestor_conexiones = GestorConexiones()
