# agent/main.py — Servidor FastAPI + Webhook de WhatsApp
# Generado por AgentKit

"""
Servidor principal del agente de WhatsApp.
Funciona con el proveedor Meta Cloud API a través de la capa de providers.
"""

import os
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import PlainTextResponse, RedirectResponse
from starlette.middleware.sessions import SessionMiddleware
from dotenv import load_dotenv

from agent.services.servicio_inteligencia import servicio_inteligencia
from agent.memory import (
    inicializar_db, obtener_lead, actualizar_lead,
    asignar_asesor_a_lead, marcar_lead_no_visto, liberar_asignacion,
    registrar_fallo_tecnico, resetear_fallos_tecnicos, RESULTADOS_CERRADOS,
    sembrar_canales_desde_env, pausar_gabi_manual, marcar_revision_prioritaria,
)
from agent.providers import obtener_proveedor
from agent.dashboard import router as dashboard_router, NoAutenticado
from agent.tiempo_real import gestor_conexiones
from agent.notificaciones import notificar_lead_derivado
from agent.services.servicio_comercial import servicio_comercial
from agent.services.servicio_canales import servicio_canales
from agent.services.servicio_conversacion import servicio_conversacion
from agent.rate_limit import limitador_webhook
from agent.http_utils import cerrar_cliente_http

load_dotenv()

# Configuración de logging según entorno
ENVIRONMENT = os.getenv("ENVIRONMENT", "development")
log_level = logging.DEBUG if ENVIRONMENT == "development" else logging.INFO
logging.basicConfig(level=log_level)
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
# Por IP de origen (request.client.host); si Railway antepone un proxy que
# oculta la IP real, esto limita por la IP que el proxy expone, no por
# cliente final — suficiente hoy, sin evidencia de que haga falta más.
MAX_WEBHOOK_POR_IP_POR_MINUTO = 60


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Inicializa la base de datos al arrancar el servidor."""
    await inicializar_db()
    await sembrar_canales_desde_env()
    await servicio_canales.sembrar_campanas_iniciales()
    await servicio_canales.corregir_patrones_desalineados()
    logger.info("Base de datos inicializada")
    logger.info(f"Servidor AgentKit corriendo en puerto {PORT}")
    logger.info(f"Proveedor de WhatsApp: {proveedor.__class__.__name__}")
    yield
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
app.include_router(dashboard_router)


@app.exception_handler(NoAutenticado)
async def no_autenticado_handler(request: Request, exc: NoAutenticado):
    """Sin sesión válida en el panel: redirige al login en vez de romper con un error."""
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
    ip = request.client.host if request.client else "desconocida"
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

            # Número de WhatsApp del NEGOCIO por el que entró este mensaje —
            # permite tener varios números activos a la vez (ej. pruebas y
            # producción); se responde siempre por el mismo canal, y se deja
            # guardado en el lead para que respuestas posteriores (asesor
            # desde el panel) también sepan por cuál número contestar.
            canal = await proveedor.resolver_canal(msg.numero_whatsapp_id)
            if msg.numero_whatsapp_id:
                await actualizar_lead(msg.telefono, numero_whatsapp_id=msg.numero_whatsapp_id)

            # Coexistencia: un asesor le respondió al cliente directo desde
            # la app de WhatsApp Business en el celular, no desde Gabi ni el
            # panel. Solo se registra en el historial (para que el panel
            # quede completo) y se pausa a Gabi si nadie más estaba
            # atendiendo — no pasa por detección de campaña ni genera
            # respuesta, porque no es un mensaje nuevo del cliente.
            if msg.tipo_evento == "echo":
                contenido = msg.texto if msg.texto else f"[{msg.tipo}]"
                await servicio_conversacion.guardar_mensaje(msg.telefono, "assistant", contenido, via_app=True)
                lead_actual = await obtener_lead(msg.telefono)
                if not (lead_actual and lead_actual.get("asesor_asignado")):
                    await pausar_gabi_manual(msg.telefono)
                logger.info(f"Echo de app registrado para {msg.telefono}: {contenido}")
                await gestor_conexiones.emitir_mensaje_nuevo(msg.telefono)
                continue

            # Tipos que aún no procesamos (audio, imagen, documento, etc.):
            # avisamos al cliente en vez de dejarlo sin respuesta
            if msg.tipo != "text":
                logger.info(f"Mensaje no soportado ({msg.tipo}) de {msg.telefono}")
                respuesta = servicio_inteligencia.obtener_mensaje_no_soportado()
                await servicio_conversacion.guardar_mensaje(msg.telefono, "user", f"[{msg.tipo}]")
                await servicio_conversacion.guardar_mensaje(msg.telefono, "assistant", respuesta)
                await proveedor.enviar_mensaje(msg.telefono, respuesta, canal=canal)
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
                if lead.get("resultado") in RESULTADOS_CERRADOS:
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
                    await servicio_conversacion.guardar_mensaje(msg.telefono, "user", msg.texto)
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

            await servicio_conversacion.guardar_mensaje(msg.telefono, "user", msg.texto)
            await servicio_conversacion.guardar_mensaje(msg.telefono, "assistant", respuesta)
            await proveedor.enviar_mensaje(msg.telefono, respuesta, canal=canal)
            await gestor_conexiones.emitir_mensaje_nuevo(msg.telefono)
            logger.info(f"Respuesta a {msg.telefono}: {respuesta}")

            if escalado_por_falla:
                asesor = await servicio_comercial.elegir_asesor_automatico((lead or {}).get("interes") or "")
                if asesor:
                    await asignar_asesor_a_lead(msg.telefono, asesor)
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
                    await asignar_asesor_a_lead(msg.telefono, asesor)
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
                        await asignar_asesor_a_lead(msg.telefono, asesor)
                        lead_actualizado = await obtener_lead(msg.telefono)
                await notificar_lead_derivado(msg.telefono, lead_actualizado or {}, msg.texto)

        return {"status": "ok"}

    except HTTPException:
        raise  # ej. firma inválida (403) — no lo envuelvas como error 500

    except Exception as e:
        logger.error(f"Error en webhook: {e}")
        raise HTTPException(status_code=500, detail="Error interno procesando el webhook")
