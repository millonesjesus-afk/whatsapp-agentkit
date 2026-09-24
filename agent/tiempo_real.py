# agent/tiempo_real.py — WebSockets del panel: chat en vivo, lista de
# conversaciones en vivo, y "escribiendo..." interno entre miembros del
# equipo.

"""
Registro en memoria de las conexiones WebSocket activas del panel — un solo
proceso en Railway para este proyecto, así que no hace falta un pub/sub
externo (Redis) para esta escala; si el día de mañana se corre en varias
instancias a la vez, esto tendría que moverse a algo compartido entre
procesos (confirmado sin evidencia de que haga falta hoy — Arquitectura
Integrada Gate 5.5, sección Multi-proceso).

Gate 5.5 — identidad de Realtime migrada de `telefono` a `conversation_id`
(Arquitectura Integrada Gate 5.5, pregunta central): antes, `emitir_mensaje_
nuevo` resolvía el Negocio de un evento vía `obtener_lead(telefono)`, un
bridge global (`Lead.telefono` es PK global, sin candado de negocio_id) con
una limitación de aislamiento ya documentada y testeada desde Gate 5.3 — con
el mismo teléfono en dos Negocios, el bridge solo podía resolver al que
"ganó" la fila `Lead`. Ahora se resuelve directo por `Conversation.id`
(UUID, sin ambigüedad posible entre Negocios) vía
`obtener_conversation_realtime()`. `conversation_id` es la identidad; el
candado de autorización real sigue siendo `negocio_id`, SEPARADO y siempre
resuelto server-side — un `conversation_id` con formato válido nunca
sustituye ese candado.

`telefono` sigue viajando en ambos eventos, de forma aditiva: el panel
legacy (`/dashboard/...` en HTML) sigue usando `telefono` indefinidamente
(Arquitectura Integrada Gate 5.5, Legacy — coexistencia, no ventana de
transición) y su script filtra por ese campo. No es un campo especulativo:
tiene una razón funcional real y vigente.

Dos tipos de evento:
- "mensaje_nuevo" (conversation_id, telefono): se manda SOLO a las
  conexiones cuyo usuario tiene acceso real a esa Conversation — mismo
  criterio que _verificar_acceso_lead en dashboard.py (admin/supervisor ven
  todo DENTRO DE SU NEGOCIO, un asesor solo lo suyo — ver tiene_acceso_a_lead
  en agent/memory.py), más el candado de negocio_id (Gate 5.4/5.5): antes de
  Gate 5.4, "admin/supervisor ven todo" no distinguía de qué Negocio.
  Además, no se emite si la Conversation ya no está activa (Gate 5.5,
  Contrato WebSocket — una Conversation cerrada no debe seguir generando
  eventos de mensaje nuevo). Cada cliente que SÍ lo recibe decide si le
  importa más allá de eso (si tiene esa conversación abierta, refresca el
  chat; si no, solo dispara un refresco liviano de la lista/tabla).
- "asesor_escribiendo" (conversation_id, telefono, username): solo a
  quienes tienen ESA Conversation abierta en este momento
  (conversation_id_activo) — no tiene sentido mandarlo a todo el mundo, y
  además molestaría a alguien mirando una conversación distinta. No se
  filtra por negocio_id de nuevo acá: si alguien ya tiene la Conversation
  abierta como conversation_id_activo es porque `ver_lead` ya validó su
  acceso (rol + negocio_id) al conectarlo (ver websocket_panel en
  dashboard.py) — filtrar de nuevo acá sería repetir un chequeo que ya se
  hizo en el único punto donde conversation_id_activo pudo haberse fijado.

  La exclusión de quien disparó la señal es por USERNAME, no por identidad
  de objeto WebSocket (ver emitir_escribiendo) — con la arquitectura SSE +
  relay del BFF (maiek-frontend), la señal saliente de "escribiendo" abre
  una conexión WS efímera nueva (POST /api/conversaciones/escribiendo ->
  un WS de un solo uso hacia acá) DISTINTA de la conexión persistente que
  ese mismo usuario tiene abierta para recibir el relay SSE — excluir por
  `ws is not excluir` nunca podía coincidir entre esas dos conexiones, así
  que el usuario terminaba viendo su propio "X está escribiendo...".
  Excluir por username filtra TODAS las conexiones de esa persona sobre
  esa Conversation, sin importar cuál está "escuchando" — sigue funcionando
  igual para el panel legado (una sola conexión persistente por asesor).
"""

import logging
import time
from fastapi import WebSocket

from agent.memory import obtener_conversation_realtime, tiene_acceso_a_lead

logger = logging.getLogger("agentkit")

# 4408: cerrada por inactividad (Gate 4.1, cuarta capa de hardening — ver
# GestorConexiones.cerrar_inactivas). No colisiona con 4401 (sesión), 4403
# (Origin) ni 4409 (duplicada).
CODIGO_WS_INACTIVA = 4408

# Dispositivos/pestañas del MISMO usuario que pueden mirar la MISMA
# conversación a la vez (laptop + celular + otra pestaña). Ver
# `GestorConexiones.set_conversation_activa`.
MAX_CONEXIONES_POR_USUARIO_Y_CONVERSACION = 3


class GestorConexiones:
    def __init__(self):
        # ws -> {"username": str, "rol": str, "negocio_id": str,
        #        "conversation_id_activo": str | None,
        #        "ultima_actividad": float (time.monotonic())}
        self._conexiones: dict[WebSocket, dict] = {}

    async def conectar(self, ws: WebSocket, username: str, rol: str, negocio_id: str):
        """`rol`/`negocio_id` se guardan al conectar (no se vuelven a
        resolver en cada emisión) — evita una consulta a la base de datos
        por conexión en cada mensaje nuevo del sistema entero, a costa de
        que un cambio de rol/Negocio de alguien no tome efecto hasta que
        reconecte (misma sesión de navegador ya trae el panel recargado si
        eso pasa, en la práctica no es un problema real — un usuario no
        cambia de Negocio en caliente).

        `negocio_id` (Gate 5.4, T1): candado real de emisión — ver
        `emitir_mensaje_nuevo`. Sin este campo, "admin/supervisor ven todo"
        significaba "ven todo de cualquier Negocio"."""
        await ws.accept()
        self._conexiones[ws] = {
            "username": username, "rol": rol, "negocio_id": negocio_id, "conversation_id_activo": None,
            "ultima_actividad": time.monotonic(), "conectada_en": time.monotonic(),
        }

    def desconectar(self, ws: WebSocket):
        self._conexiones.pop(ws, None)

    async def set_conversation_activa(self, ws: WebSocket, conversation_id: str | None):
        """Garantiza como máximo 1 conexión activa por usuario+conversación
        (Gate 4.1, remediación de conexión huérfana; Gate 5.5, clave
        migrada de `telefono` a `conversation_id`).

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
        (usuario, conversation_id) — no a "1 conexión por usuario" a secas —
        para no romper el caso legítimo de un usuario con 2 pestañas mirando
        2 conversaciones distintas al mismo tiempo.

        Limitación conocida: esto cierra duplicados cuando una conexión
        NUEVA para la misma (usuario, conversation_id) efectivamente llega.
        Si una conexión queda huérfana y el usuario nunca vuelve a esa MISMA
        conversación (p. ej. cerró la pestaña y el aviso de cierre se perdió
        en el mismo viaje), esta conexión puntual no tiene un mecanismo que
        la reclame — no se resolvió acá por no ampliar el alcance de esta
        remediación; ver reporte de la investigación."""
        if ws not in self._conexiones:
            return
        self._conexiones[ws]["conversation_id_activo"] = conversation_id
        self._conexiones[ws]["ultima_actividad"] = time.monotonic()
        if conversation_id is None:
            return
        username = self._conexiones[ws]["username"]
        # 2026-09-23 — antes el máximo era 1: con la laptop y el celular del
        # mismo usuario en el mismo chat, cada conexión nueva cerraba a la
        # otra, la cerrada reconectaba y volvía a cerrar a la primera, en
        # bucle cada ~5 s (visto en producción) — las dos pantallas quedaban
        # sin aviso instantáneo buena parte del tiempo. Ahora se toleran
        # varios dispositivos a la vez y solo se cierra la MÁS ANTIGUA cuando
        # se pasa del tope, que sigue existiendo por el motivo original:
        # conexiones huérfanas cuyo cierre se perdió en el transporte.
        mismas = [
            otro for otro, info in list(self._conexiones.items())
            if otro is not ws and info["username"] == username and info["conversation_id_activo"] == conversation_id
        ]
        mismas.sort(key=lambda otro: self._conexiones[otro].get("conectada_en", 0.0))
        sobrantes = len(mismas) + 1 - MAX_CONEXIONES_POR_USUARIO_Y_CONVERSACION
        duplicadas = mismas[:sobrantes] if sobrantes > 0 else []
        for otro in duplicadas:
            logger.info(
                "Cerrando conexión WS duplicada del panel (usuario=%s, conversation_id=%s) — "
                "reemplazada por una conexión más nueva para la misma conversación.",
                username, conversation_id,
            )
            try:
                await otro.close(code=4409)  # 4409: cerrada por duplicado (mismo usuario+conversación) — no colisiona con 4401/4403 (sesión/origin).
            except Exception:
                pass
            self.desconectar(otro)

    def tocar_actividad(self, username: str, conversation_id: str | None) -> None:
        """Marca a (usuario, conversation_id) como recién visto — llamado
        desde el endpoint de mensajes del panel, que el polling incondicional
        golpea cada 20s SIEMPRE que esa conversación está abierta en pantalla
        (`usePollingIncondicional` en maiek-frontend), sin importar el
        estado del WS/SSE.

        `conversation_id=None` (2026-09-17): además de una conversación
        puntual, ahora también existen conexiones de LISTA — sin `ver_lead`,
        `conversation_id_activo` se queda en `None` para siempre (ver
        `ConversacionesVista` en maiek-frontend, que abre una de estas para
        mantener la Bandeja al día sin depender de que además haya un
        `PanelChat` montado). Sin este caso, esas conexiones nunca recibían
        ningún golpe de actividad y el barrido de inactividad (Gate 4.1,
        `cerrar_inactivas`) las cerraría cada ~2 min aunque el navegador
        siguiera ahí de verdad — `None == None` las toca igual que cualquier
        conversación puntual toca a las suyas, mismo mecanismo, sin caso
        especial en la comparación de abajo.

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
            if info["username"] == username and info["conversation_id_activo"] == conversation_id:
                info["ultima_actividad"] = ahora

    async def cerrar_inactivas(self, umbral_segundos: float) -> int:
        """Barrido periódico (ver la tarea en segundo plano de
        `agent/main.py`, `lifespan`) — cierra activamente cualquier conexión
        cuya última actividad real (`tocar_actividad`, o el `ver_lead`
        inicial) tenga más de `umbral_segundos`.

        Gate 4.1, cuarta capa de hardening: a diferencia de la expulsión de
        duplicados (`set_conversation_activa`), esta NO depende de que
        llegue una conexión nueva para la MISMA conversación — cubre
        exactamente lo que esa limitación conocida deja afuera (ver su
        docstring): el usuario nunca vuelve a esa conversación, así que
        ninguna conexión nueva va a llegar nunca a expulsar a la vieja.

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
                "Cerrando conexión WS del panel por inactividad (usuario=%s, conversation_id=%s, "
                "inactiva hace %.0fs) — Gate 4.1, idle timeout.",
                info.get("username", "?"), info.get("conversation_id_activo", "?"),
                ahora - info.get("ultima_actividad", ahora),
            )
            try:
                await ws.close(code=CODIGO_WS_INACTIVA)
            except Exception:
                pass
            self.desconectar(ws)
        return len(inactivas)

    async def emitir_mensaje_nuevo(self, conversation_id: str | None):
        """Filtra por acceso ANTES de emitir — una sola consulta a la
        Conversation (no una por conexión) para saber a quién le corresponde.

        Gate 5.5: `obtener_conversation_realtime(conversation_id)` SIN
        `negocio_id` es intencional — es descubrimiento de identidad, no
        verificación del acceso de un tercero (mismo criterio que tenía
        `obtener_lead(telefono)` antes de esta migración, pero ahora sin la
        ambigüedad del bridge: `conversation_id` es una PK real, nunca
        colisiona entre Negocios). El candado real es el filtro de abajo:
        cada conexión solo recibe el evento si su `negocio_id` coincide con
        el de la Conversation, además del criterio de rol de siempre. No se
        emite si la Conversation ya no está activa (Contrato WebSocket,
        Arquitectura Integrada Gate 5.5)."""
        if conversation_id is None:
            return  # mensaje sin Conversation resoluble (huérfano histórico) — no hay a quién emitirle con seguridad
        conversation = await obtener_conversation_realtime(conversation_id)
        if conversation is None or conversation["estado"] != "activa":
            return
        evento = {
            "tipo": "mensaje_nuevo", "conversation_id": conversation_id,
            "telefono": conversation["telefono"],
        }
        asesor_asignado = conversation.get("asesor_asignado_id")
        negocio_id_conversation = conversation["negocio_id"]
        for ws, info in list(self._conexiones.items()):
            if info.get("negocio_id") != negocio_id_conversation:
                continue
            if tiene_acceso_a_lead(info["rol"], info["username"], asesor_asignado):
                await self._enviar_seguro(ws, evento)

    async def emitir_escribiendo(self, conversation_id: str, telefono: str | None, nombre_mostrar: str, excluir_username: str):
        """`nombre_mostrar` es lo que se muestra en el aviso ("X está
        escribiendo...") — puede repetirse entre personas. `excluir_username`
        es el username (login, único) de quien disparó la señal: se excluyen
        TODAS sus conexiones sobre esta Conversation, no solo la que originó
        el evento (ver comentario de cabecera — la conexión que dispara la
        señal y la que la recibiría de vuelta pueden ser dos WebSockets
        distintos del mismo usuario).

        Sin candado de `negocio_id` explícito acá (Gate 5.4/5.5): a
        diferencia de `emitir_mensaje_nuevo`, esta función solo le llega a
        conexiones cuyo `conversation_id_activo` ya fue fijado por
        `ver_lead`, que ya exige el mismo candado de negocio_id antes de
        aceptar la Conversation — repetir el chequeo acá sería redundante,
        no una protección adicional real."""
        evento = {
            "tipo": "asesor_escribiendo", "conversation_id": conversation_id,
            "telefono": telefono, "username": nombre_mostrar,
        }
        for ws, info in list(self._conexiones.items()):
            if info["conversation_id_activo"] == conversation_id and info["username"] != excluir_username:
                await self._enviar_seguro(ws, evento)

    async def _enviar_seguro(self, ws: WebSocket, evento: dict):
        try:
            await ws.send_json(evento)
        except Exception:
            self.desconectar(ws)


gestor_conexiones = GestorConexiones()
