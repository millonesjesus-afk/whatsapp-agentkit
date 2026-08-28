# agent/main.py — Servidor FastAPI + Webhook de WhatsApp
# Generado por AgentKit

"""
Servidor principal del agente de WhatsApp.
Funciona con el proveedor Meta Cloud API a través de la capa de providers.
"""

import asyncio
import contextlib
import os
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
    registrar_fallo_tecnico, resetear_fallos_tecnicos, RESULTADOS_CERRADOS,
    sembrar_canales_desde_env, pausar_gabi_manual, marcar_revision_prioritaria,
    marcar_mensaje_procesado, obtener_negocio_por_codigo,
)
from agent.providers import obtener_proveedor
from agent.dashboard import (
    router as dashboard_router, NoAutenticado,
    ARCHIVOS_DIR, EXTENSIONES_ARCHIVO_PERMITIDAS, TAMANO_MAXIMO_ARCHIVO_MB, _guardar_archivo_en_disco,
)
from agent.tiempo_real import gestor_conexiones
from agent.notificaciones import notificar_lead_derivado
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

# Tipos de adjunto entrante que este Gate soporta guardar como archivo real
# — los mismos que el panel ya sabe ENVIAR del lado saliente (ver
# dashboard.py: enviar-archivo/enviar-audio). Video, sticker, ubicación,
# etc. quedan fuera a propósito y siguen el camino de "no soportado" de
# siempre — no hay envío saliente equivalente que los reciba en el panel.
TIPOS_MEDIA_SOPORTADOS = ("image", "document", "audio")

# Mismas restricciones de extensión que ya aplican al envío saliente de una
# proforma (EXTENSIONES_ARCHIVO_PERMITIDAS, importado de dashboard.py) para
# image/document. Audio queda fuera de esa lista a propósito, igual que ya
# pasa con las notas de voz salientes (enviar-audio en dashboard.py no
# valida extensión, solo tamaño) — las notas de voz de WhatsApp son siempre
# OGG/Opus.
_MIME_A_EXTENSION_IMAGEN = {"image/jpeg": ".jpg", "image/png": ".png"}


def _extension_permitida_para_media(tipo: str, mime_type: str, filename: str) -> str | None:
    """Resuelve y valida la extensión a usar para un adjunto ENTRANTE.
    Retorna None si el tipo/mime no está permitido — el llamador degrada
    entonces al placeholder de texto anterior en vez de guardar un archivo
    con un tipo no soportado."""
    if tipo == "audio":
        return ".ogg"
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
    await servicio_canales.sembrar_campanas_iniciales()
    await servicio_canales.corregir_patrones_desalineados()
    logger.info("Base de datos inicializada")
    logger.info(f"Servidor AgentKit corriendo en puerto {PORT}")
    logger.info(f"Proveedor de WhatsApp: {proveedor.__class__.__name__}")
    tarea_barrido_ws = asyncio.create_task(_barrer_conexiones_ws_inactivas())
    yield
    tarea_barrido_ws.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await tarea_barrido_ws
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

            # Número de WhatsApp del NEGOCIO por el que entró este mensaje —
            # permite tener varios números activos a la vez (ej. pruebas y
            # producción); se responde siempre por el mismo canal, y se deja
            # guardado en el lead para que respuestas posteriores (asesor
            # desde el panel) también sepan por cuál número contestar.
            canal = await proveedor.resolver_canal(msg.numero_whatsapp_id)
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

            # Coexistencia: un asesor le respondió al cliente directo desde
            # la app de WhatsApp Business en el celular, no desde Gabi ni el
            # panel. Solo se registra en el historial (para que el panel
            # quede completo) y se pausa a Gabi si nadie más estaba
            # atendiendo — no pasa por detección de campaña ni genera
            # respuesta, porque no es un mensaje nuevo del cliente.
            if msg.tipo_evento == "echo":
                contenido = msg.texto if msg.texto else f"[{msg.tipo}]"
                await servicio_conversacion.guardar_mensaje(
                    msg.telefono, "assistant", contenido, via_app=True, mensaje_id_meta=msg.mensaje_id or None,
                )
                lead_actual = await obtener_lead(msg.telefono)
                if not (lead_actual and lead_actual.get("asesor_asignado")):
                    await pausar_gabi_manual(msg.telefono)
                logger.info(f"Echo de app registrado para {msg.telefono}: {contenido}")
                await gestor_conexiones.emitir_mensaje_nuevo(msg.telefono)
                continue

            # Multimedia entrante soportada (imagen, documento, nota de voz)
            # — se descarga el archivo real de Meta y se guarda como adjunto
            # real del mensaje, en vez de descartar el contenido con el
            # placeholder de texto f"[{tipo}]" (comportamiento anterior).
            # Gabi sigue sin poder "leer" el contenido (no tiene visión ni
            # transcripción — fuera de alcance de este Gate): se le sigue
            # avisando al cliente que este tipo de mensaje no se procesa
            # automáticamente, igual que antes.
            if msg.tipo in TIPOS_MEDIA_SOPORTADOS:
                logger.info(f"Media entrante ({msg.tipo}) de {msg.telefono}")
                respuesta = servicio_inteligencia.obtener_mensaje_no_soportado()
                archivo_id_creado = await _guardar_media_entrante(msg, canal)
                contenido_usuario = (msg.media or {}).get("caption") or f"[{msg.tipo}]"
                await servicio_conversacion.guardar_mensaje(
                    msg.telefono, "user", contenido_usuario,
                    archivo_id=archivo_id_creado, mensaje_id_meta=msg.mensaje_id or None,
                )
                enviado, wamid = await proveedor.enviar_mensaje(msg.telefono, respuesta, canal=canal)
                await servicio_conversacion.guardar_mensaje(msg.telefono, "assistant", respuesta, mensaje_id_meta=wamid)
                await gestor_conexiones.emitir_mensaje_nuevo(msg.telefono)
                continue

            # Tipos que aún no procesamos (video, sticker, ubicación, etc.):
            # avisamos al cliente en vez de dejarlo sin respuesta
            if msg.tipo != "text":
                logger.info(f"Mensaje no soportado ({msg.tipo}) de {msg.telefono}")
                respuesta = servicio_inteligencia.obtener_mensaje_no_soportado()
                await servicio_conversacion.guardar_mensaje(msg.telefono, "user", f"[{msg.tipo}]", mensaje_id_meta=msg.mensaje_id or None)
                enviado, wamid = await proveedor.enviar_mensaje(msg.telefono, respuesta, canal=canal)
                await servicio_conversacion.guardar_mensaje(msg.telefono, "assistant", respuesta, mensaje_id_meta=wamid)
                await gestor_conexiones.emitir_mensaje_nuevo(msg.telefono)
                continue

            if not msg.texto:
                continue

            logger.info(f"Mensaje de {msg.telefono}: {msg.texto}")

            lead = await obtener_lead(msg.telefono)

            # Primer contacto (o aún sin campaña detectada): se intenta
            # reconocer de qué campaña viene el lead — por el texto del
            # saludo de wa.link o por el objeto referral de un anuncio de
            # Meta — para medir conversión por campaña y ofrecer la promo
            # correcta. Se guarda una sola vez y nunca se sobreescribe.
            if not lead or not lead.get("campana_origen"):
                campana = await servicio_canales.detectar_y_asignar_campana(msg.telefono, msg.texto, msg.referral)
                if campana:
                    lead = await obtener_lead(msg.telefono)

            # Si ya hay un asesor humano asignado (o alguien le respondió
            # directo desde la app en coexistencia, sin asignación formal),
            # Gabi se pausa: solo se guarda el mensaje para que un humano lo
            # vea y responda — así no chocan las respuestas del bot y el humano.
            if lead and (lead.get("asesor_asignado") or lead.get("pausado_manual")):
                # "vendido" queda excluido a propósito: es un cierre de
                # negocio real (Close-Won), no solo un estado más de la
                # cola. Los otros 7 resultados cerrados siguen liberando la
                # asignación como siempre — ahí sí es razonable asumir que
                # el cliente escribe por algo nuevo. Acá no: si ya compró,
                # que Gabi vuelva a venderle solo (o a "atenderlo" sin que
                # nadie se entere) es exactamente lo que pausado_manual
                # existe para evitar.
                if lead.get("resultado") in RESULTADOS_CERRADOS and lead.get("resultado") != "vendido":
                    # El caso anterior ya se cerró — si el cliente vuelve a
                    # escribir, probablemente sea por algo nuevo. Se libera
                    # la asignación y Gabi retoma la atención (el supervisor
                    # puede reasignar manualmente si hace falta).
                    await liberar_asignacion(msg.telefono)
                    logger.info(f"Caso de {msg.telefono} ya estaba cerrado — Gabi retoma la atención")
                    lead = await obtener_lead(msg.telefono)
                else:
                    # Caso todavía abierto: se guarda el mensaje y se reactiva
                    # el indicador de "Nuevo" para que el asesor no se lo pierda,
                    # aunque ya hubiera visto mensajes anteriores de este lead.
                    await servicio_conversacion.guardar_mensaje(msg.telefono, "user", msg.texto, mensaje_id_meta=msg.mensaje_id or None)
                    await marcar_lead_no_visto(msg.telefono)
                    logger.info(
                        f"Mensaje de {msg.telefono} guardado sin respuesta automática "
                        f"(asignado a {lead['asesor_asignado']})"
                    )
                    await gestor_conexiones.emitir_mensaje_nuevo(msg.telefono)
                    continue

            # Obtener historial ANTES de guardar el mensaje actual
            # (brain.py agrega el mensaje actual, evitando duplicados)
            historial = await servicio_conversacion.obtener_historial(msg.telefono)

            # Le muestra "escribiendo..." en WhatsApp mientras Claude genera
            # la respuesta (puede tardar unos segundos) — así el cliente sabe
            # que su mensaje sí se está procesando, no que quedó en el aire.
            await proveedor.marcar_leido_y_escribiendo(msg.mensaje_id, canal=canal)

            # Generar respuesta con Claude — el modo del canal decide si usa
            # el prompt "de pruebas" (config/prompts.yaml tal cual) o el
            # promovido a producción desde el panel.
            modo_canal = (canal or {}).get("modo", "produccion")
            respuesta, hubo_error, confianza, razon = await servicio_inteligencia.generar_respuesta(
                msg.texto, historial, lead, modo=modo_canal
            )

            # Si Claude falla, se pide reintentar la primera vez. Si vuelve a
            # fallar (2 veces seguidas), se escala a un asesor en vez de
            # seguir insistiendo — ver conversación sobre las 3 opciones
            # evaluadas (esperar / escalar / call center 614002). Sin cambios
            # respecto a antes de esta sub-etapa: esto cubre fallas de la
            # llamada en sí (API caída), no la confianza de una respuesta
            # exitosa — ver el bloque de confianza más abajo.
            escalado_por_falla = False
            if hubo_error:
                fallos = await registrar_fallo_tecnico(msg.telefono)
                if fallos >= 2:
                    respuesta = servicio_inteligencia.obtener_mensaje_error_escalado()
                    escalado_por_falla = True
            else:
                await resetear_fallos_tecnicos(msg.telefono)

            # Protocolo de confianza (solo disponible en modo "pruebas" por
            # ahora — confianza es None en modo "producción" hasta que se
            # promueva, ver agent/brain.py). AI Architecture Sec.5: el AI
            # Engine solo emite la señal, nunca decide la acción — acá es
            # donde Backend la consume (ServicioInteligencia.resolver_accion_confianza).
            escalado_por_confianza = False
            if not hubo_error and confianza is not None:
                accion_confianza = await servicio_inteligencia.resolver_accion_confianza(confianza)
                if accion_confianza == "escalar":
                    respuesta = servicio_inteligencia.obtener_mensaje_escalado_por_confianza()
                    escalado_por_confianza = True
                elif accion_confianza == "revision_prioritaria":
                    await marcar_revision_prioritaria(msg.telefono)
                logger.info(
                    f"Confianza emitida para {msg.telefono}: {confianza} "
                    f"(acción: {accion_confianza}) — razón: {razon}"
                )

            await servicio_conversacion.guardar_mensaje(msg.telefono, "user", msg.texto, mensaje_id_meta=msg.mensaje_id or None)
            enviado, wamid = await proveedor.enviar_mensaje(msg.telefono, respuesta, canal=canal)
            await servicio_conversacion.guardar_mensaje(msg.telefono, "assistant", respuesta, mensaje_id_meta=wamid)
            await gestor_conexiones.emitir_mensaje_nuevo(msg.telefono)
            logger.info(f"Respuesta a {msg.telefono}: {respuesta}")

            if escalado_por_falla:
                asesor = await servicio_comercial.elegir_asesor_automatico((lead or {}).get("interes") or "")
                if asesor:
                    await asignar_asesor_a_lead(msg.telefono, asesor, automatico=True)
                lead_actualizado = await obtener_lead(msg.telefono)
                await notificar_lead_derivado(
                    msg.telefono, lead_actualizado or {},
                    "[Escalado automáticamente por fallas técnicas repetidas del bot]",
                )
                logger.warning(f"Escalado {msg.telefono} a asesor por fallas técnicas repetidas")
                continue

            if escalado_por_confianza:
                # La IA deja de tomar decisiones sobre esta conversación —
                # mismo patrón de asignación que el escalado por falla técnica,
                # pero disparado por la señal de confianza real del modelo.
                asesor = await servicio_comercial.elegir_asesor_automatico((lead or {}).get("interes") or "")
                if asesor:
                    await asignar_asesor_a_lead(msg.telefono, asesor, automatico=True)
                lead_actualizado = await obtener_lead(msg.telefono)
                await notificar_lead_derivado(
                    msg.telefono, lead_actualizado or {},
                    f"[Escalado automáticamente por baja confianza de la IA — razón: {razon}]",
                )
                logger.warning(f"Escalado {msg.telefono} a asesor por baja confianza de la IA")
                continue

            if hubo_error:
                # Primera falla: solo se pidió reintentar — no hay una
                # respuesta real de la que extraer datos del lead.
                continue

            # Actualizar datos estructurados del lead (nombre, interés, paso del
            # flujo) para que no dependan de sobrevivir en el historial crudo
            datos_lead = await servicio_inteligencia.extraer_datos_lead(msg.texto, respuesta, lead)
            await actualizar_lead(msg.telefono, **datos_lead)

            # Si el lead recién pasa a "derivado_asesor" (no lo estaba antes):
            # se le asigna automáticamente un asesor disponible (según nivel
            # de experiencia y carga actual) y se avisa al equipo por correo.
            # El supervisor/admin siempre puede reasignar manualmente después.
            ya_estaba_derivado = bool(lead) and lead.get("paso_flujo") == "derivado_asesor"
            ahora_derivado = datos_lead.get("paso_flujo") == "derivado_asesor"
            if ahora_derivado and not ya_estaba_derivado:
                lead_actualizado = await obtener_lead(msg.telefono)
                if lead_actualizado and not lead_actualizado.get("asesor_asignado"):
                    asesor = await servicio_comercial.elegir_asesor_automatico(lead_actualizado.get("interes") or "")
                    if asesor:
                        await asignar_asesor_a_lead(msg.telefono, asesor, automatico=True)
                        lead_actualizado = await obtener_lead(msg.telefono)
                await notificar_lead_derivado(msg.telefono, lead_actualizado or {}, msg.texto)

        return {"status": "ok"}

    except HTTPException:
        raise  # ej. firma inválida (403) — no lo envuelvas como error 500

    except Exception as e:
        logger.error(f"Error en webhook: {e}")
        raise HTTPException(status_code=500, detail="Error interno procesando el webhook")
