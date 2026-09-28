# agent/main.py — Servidor FastAPI + Webhook de WhatsApp
# Generado por AgentKit

"""
Servidor principal del agente de WhatsApp.
Funciona con el proveedor Meta Cloud API a través de la capa de providers.
"""

import asyncio
import contextlib
import os
import re
import time
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse, PlainTextResponse, RedirectResponse
from starlette.middleware.sessions import SessionMiddleware
from dotenv import load_dotenv

from agent.services.servicio_inteligencia import servicio_inteligencia
from agent.memory import (
    inicializar_db, obtener_lead, actualizar_lead,
    asignar_asesor_a_lead, marcar_lead_no_visto, liberar_asignacion,
    registrar_fallo_tecnico, resetear_fallos_tecnicos,
    sembrar_canales_desde_env, pausar_gabi_manual, marcar_revision_prioritaria,
    marcar_mensaje_procesado, obtener_negocio_por_codigo,
    resolver_conversation_activa, medir_latencia_db, obtener_conversation_activa_de_telefono,
)
from agent.providers import obtener_proveedor
from agent.dashboard import (
    router as dashboard_router, NoAutenticado,
    ARCHIVOS_DIR, EXTENSIONES_ARCHIVO_PERMITIDAS, TAMANO_MAXIMO_ARCHIVO_MB, _guardar_archivo_en_disco,
)
from agent.tiempo_real import gestor_conexiones
from agent.debounce import gestor_debounce_respuestas
from agent.notificaciones import notificar_lead_derivado
from agent.tools import obtener_estado_horario_atencion
from agent.services.servicio_comercial import servicio_comercial
from agent.services.servicio_canales import servicio_canales
from agent.services.servicio_conversacion import servicio_conversacion
from agent.rate_limit import limitador_webhook, ip_cliente
from agent.http_utils import cerrar_cliente_http
from agent.api_contrato import registrar_contrato_interno, FiltroRequestId

load_dotenv()

# Configuración de logging según entorno — %(request_id)s correlaciona cada
# línea de log con la solicitud que la originó (API Architecture, contrato
# interno). El filtro se agrega a los handlers del logger raíz para que
# aplique a TODOS los loggers (agentkit, uvicorn, httpx, etc.), no solo al
# propio — si no, cualquier log de una librería de terceros rompería el
# formato por no tener el campo request_id.
ENVIRONMENT = os.getenv("ENVIRONMENT", "development")
log_level = logging.DEBUG if ENVIRONMENT == "development" else logging.INFO
logging.basicConfig(level=log_level, format="%(asctime)s %(levelname)s [%(request_id)s] %(name)s: %(message)s")
for _handler in logging.root.handlers:
    _handler.addFilter(FiltroRequestId())
logger = logging.getLogger("agentkit")

# La cookie de sesión del panel se firma con esta clave — en producción es
# obligatoria (si falta, alguien podría falsificar sesiones con la clave por
# defecto). En desarrollo local se permite un valor por defecto para no
# bloquear las pruebas.
SESSION_SECRET_KEY = os.getenv("SESSION_SECRET_KEY")
if ENVIRONMENT == "production" and not SESSION_SECRET_KEY:
    raise RuntimeError(
        "SESSION_SECRET_KEY no está configurado. Es obligatorio en producción "
        "para que nadie pueda falsificar sesiones del panel."
    )
SESSION_SECRET_KEY = SESSION_SECRET_KEY or "cambia-esta-clave-solo-para-desarrollo-local"

# Variables cuya ausencia antes causaba una falla silenciosa más adelante
# (el proceso arrancaba "bien" y solo fallaba al primer uso real) — DevOps
# Architecture, Decisión local: toda variable crítica falla el arranque,
# no su primer uso. ANTHROPIC_API_KEY es el núcleo del producto (sin ella
# ningún mensaje se puede responder); CANAL_ENCRYPTION_KEY antes fallaba
# recién al primer intento de leer/guardar un canal de WhatsApp cifrado
# (ver agent/memory.py:_obtener_fernet).
_VARIABLES_CRITICAS = ["ANTHROPIC_API_KEY", "CANAL_ENCRYPTION_KEY"]
_faltantes = [v for v in _VARIABLES_CRITICAS if not os.getenv(v)]
if _faltantes:
    raise RuntimeError(
        f"Faltan variables de entorno obligatorias: {', '.join(_faltantes)}. "
        "Configúralas antes de arrancar — ver .env.example."
    )

# Proveedor de WhatsApp (se configura en .env con WHATSAPP_PROVIDER)
proveedor = obtener_proveedor()
PORT = int(os.getenv("PORT", 8000))

# Rate limiting del webhook — Security Architecture, Decisión local P1.
# Por IP de origen, resuelta con agent.rate_limit.ip_cliente() según la
# variable PROXIES_CONFIABLES. Con el valor por defecto (0) la clave es la IP
# del socket: detrás del proxy de Railway eso es la IP del borde, no la del
# cliente final, así que el límite es de hecho GLOBAL y no por cliente. Ver
# la nota de PROXIES_CONFIABLES en agent/rate_limit.py antes de cambiarlo.
MAX_WEBHOOK_POR_IP_POR_MINUTO = 60

# Tipos de adjunto entrante que se guardan como archivo real para que el panel
# los muestre. Imagen/documento/audio son los que el panel también sabe ENVIAR;
# sticker y video (los GIF de WhatsApp llegan como video) se agregaron el
# 2026-09-24 solo para VERLOS — el panel no los envía. Lo demás que Meta
# manda (p. ej. tipos desconocidos) sigue el camino de "no soportado".
TIPOS_MEDIA_SOPORTADOS = ("image", "document", "audio", "sticker", "video")

# Mismas restricciones de extensión que ya aplican al envío saliente de una
# proforma (EXTENSIONES_ARCHIVO_PERMITIDAS, importado de dashboard.py) para
# image/document. Audio queda fuera de esa lista a propósito, igual que ya
# pasa con las notas de voz salientes (enviar-audio en dashboard.py no
# valida extensión, solo tamaño) — las notas de voz de WhatsApp son siempre
# OGG/Opus.
_MIME_A_EXTENSION_IMAGEN = {"image/jpeg": ".jpg", "image/png": ".png"}


class _Cronometro:
    """Mide cuánto tarda cada tramo del camino de un mensaje entrante y lo deja
    en UNA línea de log (`webhook_tiempos`). 2026-09-24: guardar un mensaje
    pasó a tardar 1.3-2.5 s sin que el código lo explicara (22 consultas SQL en
    total); esta línea dice qué tramo se lleva el tiempo, con datos de
    producción, antes de tocar nada."""

    def __init__(self):
        self._inicio = self._ultimo = time.perf_counter()
        self.tramos: dict[str, int] = {}

    def marca(self, nombre: str) -> None:
        ahora = time.perf_counter()
        self.tramos[nombre] = round((ahora - self._ultimo) * 1000)
        self._ultimo = ahora

    def resumen(self) -> str:
        total = round((time.perf_counter() - self._inicio) * 1000)
        return f"total={total}ms " + " ".join(f"{k}={v}ms" for k, v in self.tramos.items())


def _gabi_debe_pausarse(lead: dict | None) -> bool:
    """Único criterio de "¿hay un humano atendiendo esto ahora mismo?" —
    usado por las 3 ramas del webhook que pueden llegar a responder
    automáticamente (texto, media soportada, tipo no soportado). Antes del
    Gate 2026-09-23 cada rama repetía esta condición por su cuenta y la de
    media/no-soportado simplemente NO la tenía — un adjunto de un lead ya
    asignado hacía que Gabi respondiera igual, aunque un asesor ya
    estuviera atendiendo (hallazgo real: 2 casos en la misma conversación)."""
    return bool(lead and (lead.get("asesor_asignado") or lead.get("pausado_manual")))


def _extension_permitida_para_media(tipo: str, mime_type: str, filename: str) -> str | None:
    """Resuelve y valida la extensión a usar para un adjunto ENTRANTE.
    Retorna None si el tipo/mime no está permitido — el llamador degrada
    entonces al placeholder de texto anterior en vez de guardar un archivo
    con un tipo no soportado."""
    if tipo == "audio":
        return ".ogg"
    # Solo para VERLOS en el panel — no entran en la lista de extensiones que
    # el panel deja ENVIAR (EXTENSIONES_ARCHIVO_PERMITIDAS), a propósito.
    if tipo == "sticker":
        return ".webp" if (mime_type or "").startswith("image/webp") else None
    if tipo == "video":
        return ".mp4" if (mime_type or "").startswith("video/mp4") else None
    if tipo == "image":
        extension = _MIME_A_EXTENSION_IMAGEN.get(mime_type)
    else:  # document
        extension = ".pdf" if mime_type == "application/pdf" else (os.path.splitext(filename or "")[1].lower() or None)
    return extension if extension in EXTENSIONES_ARCHIVO_PERMITIDAS else None


async def _guardar_media_entrante(msg, canal: dict | None) -> int | None:
    """Descarga un adjunto ENTRANTE (imagen/documento/nota de voz) de Meta y
    lo guarda como ArchivoAdjunto real — mismo directorio (ARCHIVOS_DIR) y
    mismas restricciones de tamaño (TAMANO_MAXIMO_ARCHIVO_MB) que ya aplican
    al envío saliente de un asesor (ver dashboard.py).

    Retorna el id del ArchivoAdjunto creado, o None si la descarga falló o
    el tipo/tamaño no está permitido — en ese caso el llamador degrada al
    placeholder de texto `f"[{tipo}]"` en vez de perder el mensaje entero."""
    media = msg.media or {}
    media_id = media.get("media_id")
    if not media_id:
        return None

    resultado = await proveedor.descargar_media(media_id, canal=canal)
    if resultado is None:
        logger.warning(f"No se pudo descargar el media {media_id} ({msg.tipo}) de {msg.telefono}")
        return None
    contenido, mime_type = resultado

    if len(contenido) > TAMANO_MAXIMO_ARCHIVO_MB * 1024 * 1024:
        logger.info(f"Media entrante de {msg.telefono} descartado por tamaño ({len(contenido)} bytes)")
        return None

    extension = _extension_permitida_para_media(msg.tipo, mime_type, media.get("filename", ""))
    if not extension:
        logger.info(f"Media entrante de {msg.telefono} descartado por tipo no permitido ({mime_type!r}, {msg.tipo})")
        return None

    nombre_original = media.get("filename") or f"adjunto{extension}"
    ruta_disco = _guardar_archivo_en_disco(nombre_original, contenido)
    # subido_por="cliente": sentinel — este adjunto no lo subió ningún
    # asesor (a diferencia de todo lo demás que crea un ArchivoAdjunto),
    # sino que llegó del cliente por WhatsApp. El campo es obligatorio en
    # ArchivoAdjunto y no admite NULL; no hay un username real que ponerle.
    archivo = await servicio_conversacion.crear_archivo_adjunto(
        nombre_original=nombre_original, ruta_disco=ruta_disco, content_type=mime_type or "application/octet-stream",
        tamano_bytes=len(contenido), subido_por="cliente", reutilizable=False,
    )
    return archivo["id"]


# Gate 4.1 — cuarta capa de hardening: barrido periódico de conexiones WS del
# panel abandonadas (ver agent/tiempo_real.py, GestorConexiones.cerrar_inactivas
# y tocar_actividad para la justificación completa de estos dos valores).
#
# UMBRAL_INACTIVIDAD_WS_SEG (120s = 2 min) tiene que quedar cómodamente por
# ENCIMA de los 20s del polling incondicional del panel (usePollingIncondicional
# en maiek-frontend — 6x de margen ante jitter de red o un tab en segundo plano
# que Chrome enlentece) y cómodamente por DEBAJO de los ~270s
# (RECONEXION_PROACTIVA_MS) del reconnect proactivo del relay del BFF
# (app/api/conversaciones/stream/route.ts) — si no fuera así, una conexión de
# relay huérfana se seguiría auto-renovando sola antes de que este barrido
# llegara a cerrarla (ver el docstring de tocar_actividad: ese reconnect
# proactivo manda "ver_lead" sin que haya navegador real detrás).
UMBRAL_INACTIVIDAD_WS_SEG = 120.0
INTERVALO_BARRIDO_INACTIVAS_SEG = 30.0


INTERVALO_LATIDO_WS_SEG = 20.0


async def _emitir_latido_ws_periodicamente():
    """Fase 2, tiempo real directo (MAIEK_AI_REALTIME_DIRECT_DESIGN.md) — ver
    GestorConexiones.emitir_latido_a_todos. Tarea aparte de
    _barrer_conexiones_ws_inactivas a propósito: son dos frecuencias
    distintas con dos propósitos distintos, y mezclarlas arriesgaba el margen
    ya calculado de esa otra (ver su comentario, más abajo)."""
    while True:
        await asyncio.sleep(INTERVALO_LATIDO_WS_SEG)
        try:
            await gestor_conexiones.emitir_latido_a_todos()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Error al emitir el latido del WebSocket del panel")


async def _barrer_conexiones_ws_inactivas():
    """Tarea de background del ciclo de vida del proceso — cierra
    activamente conexiones WS del panel abandonadas (Gate 4.1, ver
    agent/tiempo_real.py:GestorConexiones.cerrar_inactivas). Se cancela
    limpio al apagar (ver lifespan); un error de un barrido puntual se
    loguea y no tumba la tarea entera (el próximo barrido, 30s después,
    igual corre)."""
    while True:
        await asyncio.sleep(INTERVALO_BARRIDO_INACTIVAS_SEG)
        try:
            await gestor_conexiones.cerrar_inactivas(UMBRAL_INACTIVIDAD_WS_SEG)
        except Exception:
            logger.exception("Error en el barrido de conexiones WS del panel inactivas")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Inicializa la base de datos al arrancar el servidor."""
    await inicializar_db()
    try:
        logger.info(f"latencia_db {await medir_latencia_db()}")
    except Exception as e:  # una sonda nunca puede impedir que el servicio arranque
        logger.warning(f"No se pudo medir la latencia de la base: {e}")
    # Corrección arquitectónica post-auditoría de Gate 5.2: el bootstrap de
    # canales desde .env ya no adivina a qué Negocio pertenecen (ni "el
    # único que hay", ni ningún nombre fijo) — el Negocio se identifica
    # EXPLÍCITAMENTE por la variable de entorno NEGOCIO_BOOTSTRAP_CODIGO
    # (ver .env.example). Que hoy solo exista Cálidda es dato de
    # configuración de este .env, no una propiedad del código: un futuro
    # Negocio 002 solo necesita su propio NEGOCIO_BOOTSTRAP_CODIGO en su
    # propio entorno, sin tocar esta lógica. Sin la variable, o si no
    # corresponde a ningún Negocio existente, el bootstrap de canales
    # queda deshabilitado (fail-closed) — nunca se asume Cálidda.
    codigo_negocio_bootstrap = os.getenv("NEGOCIO_BOOTSTRAP_CODIGO")
    negocio_bootstrap = await obtener_negocio_por_codigo(codigo_negocio_bootstrap) if codigo_negocio_bootstrap else None
    if codigo_negocio_bootstrap and not negocio_bootstrap:
        logger.error(
            f"NEGOCIO_BOOTSTRAP_CODIGO='{codigo_negocio_bootstrap}' no corresponde a ningún "
            f"Negocio existente — el bootstrap de canales desde variables de entorno queda "
            f"deshabilitado (fail-closed)."
        )
    elif not codigo_negocio_bootstrap:
        logger.warning(
            "NEGOCIO_BOOTSTRAP_CODIGO no está configurado — el bootstrap de canales desde "
            "variables de entorno queda deshabilitado (fail-closed). Configúrala si este "
            "entorno necesita sembrar canales desde .env."
        )
    await sembrar_canales_desde_env(negocio_bootstrap["id"] if negocio_bootstrap else None)
    await servicio_canales.sembrar_campanas_iniciales(negocio_bootstrap["id"] if negocio_bootstrap else None)
    await servicio_canales.corregir_patrones_desalineados(negocio_bootstrap["id"] if negocio_bootstrap else None)
    logger.info("Base de datos inicializada")
    logger.info(f"Servidor AgentKit corriendo en puerto {PORT}")
    logger.info(f"Proveedor de WhatsApp: {proveedor.__class__.__name__}")
    tarea_barrido_ws = asyncio.create_task(_barrer_conexiones_ws_inactivas())
    tarea_latido_ws = asyncio.create_task(_emitir_latido_ws_periodicamente())
    yield
    # Gate 2026-09-23 (debounce, fix #3) — le da a las respuestas de Gabi ya
    # programadas (esperando su ventana, o ya llamando a Claude) una
    # oportunidad real de terminar antes de que Railway mate el proceso en
    # un deploy; sin esto, un mensaje que llegó justo antes del redeploy se
    # quedaría sin respuesta y sin ningún aviso. Con timeout acotado — nunca
    # bloquea el apagado indefinidamente si algo quedó colgado (ej.
    # Anthropic caído en ese momento).
    with contextlib.suppress(asyncio.TimeoutError):
        await asyncio.wait_for(gestor_debounce_respuestas.esperar_pendientes(), timeout=15.0)
    tarea_barrido_ws.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await tarea_barrido_ws
    tarea_latido_ws.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await tarea_latido_ws
    await cerrar_cliente_http()


# /docs, /redoc y /openapi.json quedan deshabilitados por defecto (API
# Architecture, Architecture Success Criteria: "no son accesibles sin
# autenticación") hasta que exista una decisión explícita de Security
# Architecture de publicarlos — hoy no existe esa decisión.
app = FastAPI(
    title="Gaso+ — Agente Gabi",
    version="1.0.0",
    lifespan=lifespan,
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)
app.add_middleware(
    SessionMiddleware,
    secret_key=SESSION_SECRET_KEY,
    session_cookie="gaso_panel_sesion",
    https_only=(ENVIRONMENT == "production"),
)
registrar_contrato_interno(app)
app.include_router(dashboard_router)


def _pide_json_explicitamente(request: Request) -> bool:
    """True solo si el cliente NOMBRA `application/json` en su Accept.

    El comodín `*/*` NO cuenta, y esa es toda la razón por la que este
    criterio es seguro: `fetch()` manda `Accept: */*` cuando no se le
    especifica otra cosa, que es exactamente lo que hace la navegación AJAX
    del panel (`X-Panel-Fragment`) y cada llamada JS de dashboard.py — esos
    clientes siguen recibiendo el redirect al login igual que antes. Un
    navegador navegando manda `text/html,...` y tampoco nombra JSON. Solo un
    consumidor de la API JSON (el frontend externo, curl, un test) pide
    `application/json` de forma explícita."""
    return "application/json" in request.headers.get("accept", "").lower()


@app.exception_handler(NoAutenticado)
async def no_autenticado_handler(request: Request, exc: NoAutenticado):
    """Sin sesión válida en el panel: redirige al login en vez de romper con un error.

    Excepción: a un cliente que pidió JSON explícitamente se le responde 401
    con el mismo envelope de error del contrato interno (agent/api_contrato.py).
    Un 307 al HTML del login no es una respuesta que un consumidor de API pueda
    interpretar — ve un 200 con una página de login donde esperaba datos, y no
    tiene forma de distinguir "no estás autenticado" de "esto respondió raro"."""
    if _pide_json_explicitamente(request):
        request_id = getattr(request.state, "request_id", "-")
        return JSONResponse(
            status_code=401,
            content={
                "codigo": "HTTP_401",
                "mensaje": "No hay una sesión activa. Inicia sesión para continuar.",
                "detalle": None,
                "request_id": request_id,
            },
            headers={"X-Request-Id": request_id},
        )
    return RedirectResponse(url="/dashboard/login")


@app.get("/")
async def health_check():
    """Endpoint de salud para Railway/monitoreo."""
    return {"status": "ok", "service": "agentkit"}


@app.get("/webhook")
async def webhook_verificacion(request: Request):
    """Verificación GET del webhook (requerido por Meta Cloud API, no-op para otros)."""
    resultado = await proveedor.validar_webhook(request)
    if resultado is not None:
        return PlainTextResponse(str(resultado))
    return {"status": "ok"}


async def _atender_mensaje_no_legible(msg, canal: dict | None, contenido: str, archivo_id: int | None = None) -> None:
    """Un mensaje que Gabi no puede leer (nota de voz, imagen, sticker, video/GIF,
    documento, tipo desconocido). Siempre se guarda —con su archivo, si lo hay—
    para que el equipo lo vea en el panel. Después:
      · con asesor asignado (o Gabi pausada): NO se responde nada automático y el
        lead queda marcado "Nuevo" — un adjunto nunca hace que Gabi se meta en
        una conversación que un humano ya atiende (Gate 2026-09-23).
      · sin asesor: se avisa al cliente, con una frase según el tipo (audio /
        foto-video-sticker / otro, editables en prompts.yaml), que ese contenido
        no se lee y que lo escriba."""
    negocio_id = canal.get("negocio_id") if canal else None
    lead = await obtener_lead(msg.telefono, negocio_id=negocio_id)
    if _gabi_debe_pausarse(lead):
        mensaje_guardado = await servicio_conversacion.guardar_mensaje(
            msg.telefono, "user", contenido, negocio_id=negocio_id,
            archivo_id=archivo_id, mensaje_id_meta=msg.mensaje_id or None,
        )
        await marcar_lead_no_visto(msg.telefono)
        logger.info(f"Mensaje de {msg.telefono} ({msg.tipo}) guardado sin respuesta automática (asignado a {lead['asesor_asignado']})")
        await gestor_conexiones.emitir_mensaje_nuevo(mensaje_guardado["conversation_id"])
        return
    respuesta = servicio_inteligencia.obtener_mensaje_no_soportado(msg.tipo)
    await servicio_conversacion.guardar_mensaje(
        msg.telefono, "user", contenido, negocio_id=negocio_id,
        archivo_id=archivo_id, mensaje_id_meta=msg.mensaje_id or None,
    )
    enviado, wamid = await proveedor.enviar_mensaje(msg.telefono, respuesta, canal=canal)
    mensaje_guardado = await servicio_conversacion.guardar_mensaje(
        msg.telefono, "assistant", respuesta, negocio_id=negocio_id,
        mensaje_id_meta=wamid, estado_envio=None if enviado else "fallido",
    )
    await gestor_conexiones.emitir_mensaje_nuevo(mensaje_guardado["conversation_id"])


async def _avisar_que_gabi_escribe(telefono: str, canal: dict | None) -> None:
    """Le avisa al panel que Gabi empezó a preparar su respuesta, para que
    muestre los tres puntos de "escribiendo…" mientras tanto (2026-09-24). Es
    solo un aviso visual: si algo falla acá se registra y se sigue — nunca puede
    impedir ni retrasar la respuesta al cliente."""
    negocio_id = (canal or {}).get("negocio_id")
    if not negocio_id:
        return
    try:
        conversation = await obtener_conversation_activa_de_telefono(telefono, negocio_id)
        if conversation is not None:
            await gestor_conexiones.emitir_gabi_escribiendo(conversation["id"])
    except Exception as e:
        logger.warning(f"No se pudo avisar al panel que Gabi está escribiendo ({telefono}): {e}")


async def _generar_y_enviar_respuesta_ia(telefono: str, canal: dict | None) -> None:
    """Gate 2026-09-23 (fix #3, debounce) — el trabajo REAL que antes corría
    inline dentro de `webhook_handler` para cada mensaje de texto: arma el
    contexto, llama a Claude, maneja fallos/confianza, envía la respuesta y
    actualiza los datos del lead. Ahora corre desacoplado, programado por
    `agent.debounce.gestor_debounce_respuestas` — el webhook ya devolvió su
    200 OK a Meta hace rato para cuando esto se ejecuta.

    El mensaje del cliente YA está guardado en la base (se guarda de
    inmediato al llegar, antes de programar esto — ver `webhook_handler`) así
    que `obtener_historial` ya lo incluye: se separa el ÚLTIMO turno como
    `mensaje` (lo que `generar_respuesta` espera recibir aparte, ver su
    docstring) y el resto queda como `historial` — reproduce exactamente la
    misma forma de llamada que antes, sin tocar `brain.py`. Si varios
    mensajes se acumularon en la misma ventana de espera, los intermedios
    quedan dentro de `historial` (Claude los ve como turnos normales ya
    escritos) y el más reciente es el que se trata como "el mensaje actual".

    Re-chequea `_gabi_debe_pausarse` con el lead FRESCO (no el que existía
    cuando se programó esto) — si en el rato que pasó un asesor tomó el
    caso, esto se cancela solo en vez de que Gabi le pise la respuesta."""
    lead = await obtener_lead(telefono, negocio_id=canal.get("negocio_id") if canal else None)
    if _gabi_debe_pausarse(lead):
        logger.info(f"Respuesta debounced de {telefono} cancelada — un humano tomó el caso mientras se esperaba")
        return

    historial_completo = await servicio_conversacion.obtener_historial(telefono)
    if not historial_completo or historial_completo[-1]["role"] != "user":
        # No debería pasar (esto se programa siempre justo después de
        # guardar un mensaje "user") — fail-safe, nunca se inventa una
        # respuesta a algo que no está ahí.
        logger.warning(f"Respuesta debounced de {telefono} sin un mensaje 'user' al final del historial — se descarta")
        return
    mensaje_actual = historial_completo[-1]
    historial = historial_completo[:-1]
    texto_actual = mensaje_actual["content"]

    await _avisar_que_gabi_escribe(telefono, canal)

    modo_canal = (canal or {}).get("modo", "produccion")
    respuesta, hubo_error, confianza, razon = await servicio_inteligencia.generar_respuesta(
        texto_actual, historial, lead, modo=modo_canal,
        negocio_id=canal.get("negocio_id") if canal else None,
    )

    # Si Claude falla, se pide reintentar la primera vez. Si vuelve a
    # fallar (2 veces seguidas), se escala a un asesor en vez de seguir
    # insistiendo — ver conversación sobre las 3 opciones evaluadas
    # (esperar / escalar / call center 614002). Sin cambios respecto a
    # antes: esto cubre fallas de la llamada en sí (API caída), no la
    # confianza de una respuesta exitosa — ver el bloque de confianza
    # más abajo.
    escalado_por_falla = False
    if hubo_error:
        fallos = await registrar_fallo_tecnico(telefono)
        if fallos >= 2:
            respuesta = servicio_inteligencia.obtener_mensaje_error_escalado()
            escalado_por_falla = True
    else:
        await resetear_fallos_tecnicos(telefono)

    # Protocolo de confianza (solo disponible en modo "pruebas" por ahora —
    # confianza es None en modo "producción" hasta que se promueva, ver
    # agent/brain.py). AI Architecture Sec.5: el AI Engine solo emite la
    # señal, nunca decide la acción — acá es donde Backend la consume
    # (ServicioInteligencia.resolver_accion_confianza).
    escalado_por_confianza = False
    if not hubo_error and confianza is not None:
        accion_confianza = await servicio_inteligencia.resolver_accion_confianza(confianza)
        if accion_confianza == "escalar":
            respuesta = servicio_inteligencia.obtener_mensaje_escalado_por_confianza()
            escalado_por_confianza = True
        elif accion_confianza == "revision_prioritaria":
            await marcar_revision_prioritaria(telefono)
        logger.info(
            f"Confianza emitida para {telefono}: {confianza} "
            f"(acción: {accion_confianza}) — razón: {razon}"
        )

    # El mensaje del cliente ya se guardó al llegar (ver webhook_handler) —
    # acá solo falta la respuesta de Gabi.
    enviado, wamid = await proveedor.enviar_mensaje(telefono, respuesta, canal=canal)
    mensaje_guardado = await servicio_conversacion.guardar_mensaje(
        telefono, "assistant", respuesta, negocio_id=canal.get("negocio_id") if canal else None,
        mensaje_id_meta=wamid, estado_envio=None if enviado else "fallido",
    )
    await gestor_conexiones.emitir_mensaje_nuevo(mensaje_guardado["conversation_id"])
    logger.info(f"Respuesta a {telefono}: {respuesta}")

    if escalado_por_falla:
        asesor = await servicio_comercial.elegir_asesor_automatico(
            (lead or {}).get("interes") or "", canal.get("negocio_id") if canal else None,
        )
        if asesor:
            await asignar_asesor_a_lead(telefono, asesor, automatico=True)
        lead_actualizado = await obtener_lead(telefono, negocio_id=canal.get("negocio_id") if canal else None)
        await notificar_lead_derivado(
            telefono, lead_actualizado or {},
            "[Escalado automáticamente por fallas técnicas repetidas del bot]",
        )
        logger.warning(f"Escalado {telefono} a asesor por fallas técnicas repetidas")
        return

    if escalado_por_confianza:
        # La IA deja de tomar decisiones sobre esta conversación — mismo
        # patrón de asignación que el escalado por falla técnica, pero
        # disparado por la señal de confianza real del modelo.
        asesor = await servicio_comercial.elegir_asesor_automatico(
            (lead or {}).get("interes") or "", canal.get("negocio_id") if canal else None,
        )
        if asesor:
            await asignar_asesor_a_lead(telefono, asesor, automatico=True)
        lead_actualizado = await obtener_lead(telefono, negocio_id=canal.get("negocio_id") if canal else None)
        await notificar_lead_derivado(
            telefono, lead_actualizado or {},
            f"[Escalado automáticamente por baja confianza de la IA — razón: {razon}]",
        )
        logger.warning(f"Escalado {telefono} a asesor por baja confianza de la IA")
        return

    if hubo_error:
        # Primera falla: solo se pidió reintentar — no hay una respuesta
        # real de la que extraer datos del lead.
        return

    # Actualizar datos estructurados del lead (nombre, interés, paso del
    # flujo) para que no dependan de sobrevivir en el historial crudo
    datos_lead = await servicio_inteligencia.extraer_datos_lead(texto_actual, respuesta, lead)
    await actualizar_lead(telefono, **datos_lead)

    # Derivación a asesor. Se decide por HECHOS —el lead está derivado y no
    # tiene asesor— y no por "acaba de pasar a derivado" (2026-09-23, hallazgo
    # real en una demo): un lead que ya había sido derivado antes y cuya
    # asignación se liberó (a mano, o por el timeout de inactividad) volvía a
    # pedir un asesor, nunca contaba como transición y quedaba sin asignar y
    # sin aviso. `paso_flujo` no se reinicia al liberar: alimenta el embudo de
    # Analítica, y borrarlo sacaría esos leads de la cuenta.
    #
    # Aviso por correo: una vez por ciclo de derivación, o cuando esta vez SÍ
    # se asignó un asesor — un cliente que insiste mientras nadie está
    # disponible no le dispara un correo al equipo en cada mensaje.
    ya_estaba_derivado = bool(lead) and lead.get("paso_flujo") == "derivado_asesor"
    ahora_derivado = datos_lead.get("paso_flujo") == "derivado_asesor"
    if ahora_derivado:
        negocio_id = canal.get("negocio_id") if canal else None
        lead_actualizado = await obtener_lead(telefono, negocio_id=negocio_id)
        asignado_ahora = False
        if lead_actualizado and not lead_actualizado.get("asesor_asignado"):
            asesor = await servicio_comercial.elegir_asesor_automatico(
                lead_actualizado.get("interes") or "", negocio_id,
            )
            if asesor:
                await asignar_asesor_a_lead(telefono, asesor, automatico=True)
                lead_actualizado = await obtener_lead(telefono, negocio_id=negocio_id)
                asignado_ahora = True
        if not ya_estaba_derivado or asignado_ahora:
            await notificar_lead_derivado(telefono, lead_actualizado or {}, texto_actual)
            await _avisar_derivacion_si_falto(telefono, respuesta, canal)


_MENCIONA_ASESOR = re.compile(r"asesor|especialista|ejecutiv", re.IGNORECASE)


async def _avisar_derivacion_si_falto(telefono: str, respuesta: str, canal: dict | None) -> None:
    """Red de seguridad determinista: si el sistema acaba de derivar al
    cliente pero la respuesta de Gabi no menciona a un asesor, el cliente
    quedaría derivado sin enterarse (y Gabi calla desde ahí, con el asesor
    asignado) — es el caso de "deriva sin decir nada" que se vio en varias
    conversaciones. El prompt ya pide avisarlo; esto lo garantiza."""
    if _MENCIONA_ASESOR.search(respuesta):
        return
    negocio_id = canal.get("negocio_id") if canal else None
    estado = await obtener_estado_horario_atencion(negocio_id)
    aviso = servicio_inteligencia.obtener_mensaje_derivacion(estado["dentro_de_horario"])
    enviado, wamid = await proveedor.enviar_mensaje(telefono, aviso, canal=canal)
    mensaje_guardado = await servicio_conversacion.guardar_mensaje(
        telefono, "assistant", aviso, negocio_id=negocio_id,
        mensaje_id_meta=wamid, estado_envio=None if enviado else "fallido",
    )
    await gestor_conexiones.emitir_mensaje_nuevo(mensaje_guardado["conversation_id"])
    logger.info(f"Derivación de {telefono} sin aviso en la respuesta de Gabi — se envió el aviso de respaldo")


@app.post("/webhook")
async def webhook_handler(request: Request):
    """
    Recibe mensajes de WhatsApp via el proveedor configurado.
    Procesa el mensaje, genera respuesta con Claude y la envía de vuelta.
    """
    ip = ip_cliente(request)
    if not limitador_webhook.permitir(ip, MAX_WEBHOOK_POR_IP_POR_MINUTO, 60):
        logger.warning(f"Rate limit excedido en /webhook desde {ip}")
        raise HTTPException(status_code=429, detail="Demasiadas solicitudes")

    try:
        # Verificar que el webhook realmente venga de Meta antes de procesar nada
        cuerpo_crudo = await request.body()
        if not await proveedor.verificar_firma(request, cuerpo_crudo):
            logger.warning("Firma de webhook inválida — solicitud rechazada")
            raise HTTPException(status_code=403, detail="Firma inválida")

        # Los leads de formulario (Meta Lead Ads/Instant Forms) llegan por un
        # webhook de PÁGINA distinto al de WhatsApp — objeto "page" en vez de
        # "whatsapp_business_account". El cliente nunca escribió primero, así
        # que este camino no toca nada del flujo normal de mensajes de abajo.
        body = await request.json()
        if body.get("object") == "page":
            await servicio_canales.procesar_leads_formulario(body, proveedor)
            return {"status": "ok"}

        # Parsear webhook — el proveedor normaliza el formato
        mensajes = await proveedor.parsear_webhook(request)

        for msg in mensajes:
            # Ignorar mensajes propios
            if msg.es_propio:
                continue
            cron = _Cronometro()

            # Idempotencia general (API Architecture) — Meta puede reentregar
            # el mismo mensaje (reintentos de webhook, entregas duplicadas).
            # mensaje_id vacío (no debería pasar, pero el proveedor no lo
            # garantiza) se deja procesar en vez de arriesgar colisionar
            # contra otros mensajes vacíos y descartarlos en silencio.
            if msg.mensaje_id:
                ya_procesado = await marcar_mensaje_procesado(msg.mensaje_id)
                if ya_procesado:
                    logger.info(f"Mensaje {msg.mensaje_id} ya procesado antes — ignorado (idempotencia)")
                    continue

            cron.marca("idempotencia")

            # Número de WhatsApp del NEGOCIO por el que entró este mensaje —
            # permite tener varios números activos a la vez (ej. pruebas y
            # producción); se responde siempre por el mismo canal, y se deja
            # guardado en el lead para que respuestas posteriores (asesor
            # desde el panel) también sepan por cuál número contestar.
            canal = await proveedor.resolver_canal(msg.numero_whatsapp_id)
            cron.marca("canal")
            if msg.numero_whatsapp_id:
                # Gate 5.2 (corrección H2): negocio_id se resuelve del Canal
                # ya identificado por su phone_number_id — nunca un default
                # global. Si el canal no pudo resolverse (numero_whatsapp_id
                # desconocido, o ambiguo entre Negocios sin match exacto),
                # canal es None y negocio_id queda None — actualizar_lead()
                # falla cerrado si eso implica crear un Lead nuevo sin poder
                # determinar su Negocio, en vez de adivinar.
                await actualizar_lead(
                    msg.telefono, numero_whatsapp_id=msg.numero_whatsapp_id,
                    negocio_id=canal.get("negocio_id") if canal else None,
                )
                if canal and canal.get("negocio_id"):
                    # Gate 5.3 — punto de entrada único para Contact/
                    # Conversation/Opportunity (Diseño Técnico Gate 5.3 §10).
                    # Aplica DR-4 acá mismo: si la Conversation activa está
                    # asignada/pausada y su Opportunity vigente tiene un
                    # resultado cerrado distinto de "vendido", la cierra y
                    # abre una nueva ANTES de que el resto del flujo (guardar
                    # mensaje, liberar_asignacion) corra — así todo lo que
                    # sigue ya opera sobre la Conversation correcta. Sin
                    # canal resuelto no se puede crear ninguna (canal_id es
                    # NOT NULL) — se deja para el próximo mensaje que sí
                    # resuelva canal, mismo criterio fail-closed que ya usa
                    # actualizar_lead() arriba.
                    await resolver_conversation_activa(
                        msg.telefono, canal["negocio_id"], canal["id"],
                        unidad_id=canal.get("unidad_id"),
                    )

            cron.marca("lead_y_conversacion")

            # Coexistencia: un asesor le respondió al cliente directo desde
            # la app de WhatsApp Business en el celular, no desde Gabi ni el
            # panel. Solo se registra en el historial (para que el panel
            # quede completo) y se pausa a Gabi si nadie más estaba
            # atendiendo — no pasa por detección de campaña ni genera
            # respuesta, porque no es un mensaje nuevo del cliente.
            if msg.tipo_evento == "echo":
                contenido = msg.texto if msg.texto else f"[{msg.tipo}]"
                mensaje_guardado = await servicio_conversacion.guardar_mensaje(
                    msg.telefono, "assistant", contenido, negocio_id=canal.get("negocio_id") if canal else None,
                    via_app=True, mensaje_id_meta=msg.mensaje_id or None,
                )
                lead_actual = await obtener_lead(msg.telefono, negocio_id=canal.get("negocio_id") if canal else None)
                if not (lead_actual and lead_actual.get("asesor_asignado")):
                    await pausar_gabi_manual(msg.telefono)
                logger.info(f"Echo de app registrado para {msg.telefono}: {contenido}")
                await gestor_conexiones.emitir_mensaje_nuevo(mensaje_guardado["conversation_id"])
                continue

            # Reacción a un mensaje (👍, ❤️…): se deja como una línea en el
            # historial para que el asesor vea que el cliente reaccionó, y
            # NADA más — nunca dispara a Gabi ni el aviso de "tipo no
            # soportado" (antes una reacción recibía esa respuesta absurda), ni
            # marca el lead como "Nuevo": no pide atención. Sin emoji, el
            # cliente quitó su reacción y no hay nada que guardar.
            if msg.tipo == "reaction":
                if msg.texto:
                    mensaje_guardado = await servicio_conversacion.guardar_mensaje(
                        msg.telefono, "user", msg.texto, negocio_id=canal.get("negocio_id") if canal else None,
                        mensaje_id_meta=msg.mensaje_id or None,
                    )
                    await gestor_conexiones.emitir_mensaje_nuevo(mensaje_guardado["conversation_id"])
                continue

            # Multimedia entrante soportada (imagen, documento, nota de voz,
            # sticker, video/GIF) — se descarga el archivo real de Meta y se guarda como adjunto
            # real del mensaje, en vez de descartar el contenido con el
            # placeholder de texto f"[{tipo}]" (comportamiento anterior).
            # Gabi sigue sin poder "leer" el contenido (no tiene visión ni
            # transcripción — entender imágenes/stickers/audio queda para una
            # fase posterior, decisión del usuario 2026-09-24): al cliente se
            # le sigue avisando, con una frase según el tipo, que ese contenido
            # no se lee y que lo escriba (ver `_atender_mensaje_no_legible`).
            if msg.tipo in TIPOS_MEDIA_SOPORTADOS:
                logger.info(f"Media entrante ({msg.tipo}) de {msg.telefono}")
                archivo_id_creado = await _guardar_media_entrante(msg, canal)
                contenido_usuario = (msg.media or {}).get("caption") or f"[{msg.tipo}]"
                await _atender_mensaje_no_legible(msg, canal, contenido_usuario, archivo_id_creado)
                continue

            # Tipos que aún no procesamos (ubicación ya no: llega como texto;
            # queda p. ej. lo desconocido): mismo tratamiento que la media.
            if msg.tipo != "text":
                logger.info(f"Mensaje no soportado ({msg.tipo}) de {msg.telefono}")
                await _atender_mensaje_no_legible(msg, canal, f"[{msg.tipo}]")
                continue

            if not msg.texto:
                continue

            logger.info(f"Mensaje de {msg.telefono}: {msg.texto}")

            lead = await obtener_lead(msg.telefono, negocio_id=canal.get("negocio_id") if canal else None)
            cron.marca("obtener_lead")

            # Primer contacto (o aún sin campaña detectada): se intenta
            # reconocer de qué campaña viene el lead — por el texto del
            # saludo de wa.link o por el objeto referral de un anuncio de
            # Meta — para medir conversión por campaña y ofrecer la promo
            # correcta. Se guarda una sola vez y nunca se sobreescribe.
            if not lead or not lead.get("campana_origen"):
                campana = await servicio_canales.detectar_y_asignar_campana(
                    msg.telefono, msg.texto, msg.referral, canal.get("negocio_id") if canal else None,
                )
                if campana:
                    lead = await obtener_lead(msg.telefono, negocio_id=canal.get("negocio_id") if canal else None)

            # Cierre automático por inactividad del CLIENTE (2026-09-17,
            # pedido explícito del usuario) — scripts/procesar_inactividad_
            # clientes.py marca resultado="sin_respuesta" en un lead SIN
            # asesor asignado y SIN pausar, así que a diferencia del bloque
            # de abajo (que solo libera cuando SÍ hay asesor/pausa) Gabi
            # nunca dejó de responderle a este cliente — si vuelve a
            # escribir, ese "sin_respuesta" queda desactualizado apenas
            # este mensaje entra. Se limpia acá, antes de cualquier otro
            # flujo, para que el pipeline/bandeja no siga mostrando
            # "Sin respuesta" sobre una conversación que ya está activa de
            # nuevo.
            if lead and lead.get("resultado") == "sin_respuesta":
                await actualizar_lead(msg.telefono, campos_explicitos=("resultado",), resultado=None)
                lead = await obtener_lead(msg.telefono, negocio_id=canal.get("negocio_id") if canal else None)

            # Si ya hay un asesor humano asignado (o alguien le respondió
            # directo desde la app en coexistencia, sin asignación formal),
            # Gabi se pausa: solo se guarda el mensaje para que un humano lo
            # vea y responda — así no chocan las respuestas del bot y el humano.
            if _gabi_debe_pausarse(lead):
                # Gate 2026-09-23 — ANTES se usaba "resultado en
                # RESULTADOS_CERRADOS" como señal de "probablemente algo
                # nuevo, Gabi retoma" — hallazgo real (Joanna Chuica):
                # "consulta_atc" es un resultado cerrado, pero un asesor de
                # OTRO tema (Televentas) le había escrito un minuto antes;
                # el siguiente mensaje del cliente reactivaba a Gabi de
                # todas formas, sin que el asesor activo se enterara.
                # `resultado` sigue siendo el dato de CRM/reporting, sin
                # tocar — el gatillo de reactivación ahora es un cierre
                # EXPLÍCITO (manual desde la Ficha del Lead, o automático
                # por `cerrar_leads_definitivamente.py` tras 7 días de
                # silencio del cliente), nunca el `resultado` por sí solo.
                # "vendido" sigue excluido: `cerrado_definitivamente_en`
                # nunca se setea en un caso vendido (ver Human Decision
                # Gate ya documentado — Close-Won es indefinido).
                if lead.get("cerrado_definitivamente_en") is not None:
                    # El caso quedó cerrado de verdad — DR-4 (resolver_
                    # conversation_activa, ya corrió arriba con este mismo
                    # mensaje) ya abrió una Conversation nueva sin asesor;
                    # acá solo falta liberar el Lead (legacy) para que el
                    # panel dashboard.py deje de mostrarlo bajo el asesor
                    # anterior. Gabi retoma como si fuera un lead nuevo — el
                    # asesor anterior no recibe ningún aviso de esto.
                    await liberar_asignacion(msg.telefono, motivo="cierre_definitivo")
                    logger.info(f"Caso de {msg.telefono} estaba cerrado definitivamente — Gabi retoma la atención")
                    lead = await obtener_lead(msg.telefono, negocio_id=canal.get("negocio_id") if canal else None)
                else:
                    # Caso todavía abierto: se guarda el mensaje y se reactiva
                    # el indicador de "Nuevo" para que el asesor no se lo pierda,
                    # aunque ya hubiera visto mensajes anteriores de este lead.
                    mensaje_guardado = await servicio_conversacion.guardar_mensaje(
                        msg.telefono, "user", msg.texto, negocio_id=canal.get("negocio_id") if canal else None,
                        mensaje_id_meta=msg.mensaje_id or None,
                    )
                    await marcar_lead_no_visto(msg.telefono)
                    logger.info(
                        f"Mensaje de {msg.telefono} guardado sin respuesta automática "
                        f"(asignado a {lead['asesor_asignado']})"
                    )
                    cron.marca("guardar_y_marcar")
                    await gestor_conexiones.emitir_mensaje_nuevo(mensaje_guardado["conversation_id"])
                    cron.marca("emitir")
                    logger.info(f"webhook_tiempos {cron.resumen()}")
                    continue

            # Gate 2026-09-23 (fix #3, debounce) — el mensaje se guarda de
            # inmediato (aparece en el panel en tiempo real apenas llega, un
            # mensaje por burbuja, igual que en WhatsApp) pero la llamada a
            # Claude ya NO corre acá inline. En vez de eso se (re)programa una
            # ventana corta (`DEBOUNCE_RESPUESTA_SEGUNDOS`, 3s por defecto):
            # si el cliente manda otro mensaje antes de que pase, esta espera
            # se cancela y se reinicia con el nuevo — recién cuando el
            # cliente se queda tranquilo un momento se dispara UNA sola
            # llamada que ya ve todos los mensajes acumulados (ver
            # `_generar_y_enviar_respuesta_ia` y `agent/debounce.py` para el
            # razonamiento completo). Esto es lo que de verdad decide el
            # comportamiento: mandar 3 mensajes seguidos ya no dispara 3
            # llamadas a Claude ni 3 respuestas separadas.
            mensaje_guardado = await servicio_conversacion.guardar_mensaje(
                msg.telefono, "user", msg.texto, negocio_id=canal.get("negocio_id") if canal else None,
                mensaje_id_meta=msg.mensaje_id or None,
            )
            await gestor_conexiones.emitir_mensaje_nuevo(mensaje_guardado["conversation_id"])

            # Le muestra "escribiendo..." en WhatsApp de una vez — aunque la
            # respuesta real todavía no arranca (está en la ventana de
            # espera), esto ya le confirma al cliente que su mensaje llegó.
            cron.marca("guardar")
            await proveedor.marcar_leido_y_escribiendo(msg.mensaje_id, canal=canal)
            cron.marca("meta_escribiendo")
            logger.info(f"webhook_tiempos {cron.resumen()}")

            clave_debounce = f"{canal.get('negocio_id') if canal else None}:{msg.telefono}"
            gestor_debounce_respuestas.reprogramar(
                clave_debounce,
                lambda telefono=msg.telefono, canal=canal: _generar_y_enviar_respuesta_ia(telefono, canal),
            )

        return {"status": "ok"}

    except HTTPException:
        raise  # ej. firma inválida (403) — no lo envuelvas como error 500

    except Exception as e:
        logger.error(f"Error en webhook: {e}")
        raise HTTPException(status_code=500, detail="Error interno procesando el webhook")
