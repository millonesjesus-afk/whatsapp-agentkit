# agent/dashboard.py — Panel interno de leads y conversaciones
# Generado por AgentKit

"""
Panel interno para que el equipo comercial vea el embudo de ventas, la
lista de leads, revise la calidad de atención de Gabi (transcripción
completa), asigne leads a asesores, y registre el resultado/cierre de
venta de cada lead tras la derivación a un asesor humano.

Layout tipo bandeja (como WhatsApp Web): barra lateral con las
conversaciones del usuario + panel de chat en vivo (se actualiza solo,
sin recargar la página, para no perder lo que el asesor está escribiendo).
Usa Bootstrap 5 vía CDN para los estilos (sin build step).

Roles:
- admin / supervisor: ven todos los leads, pueden asignarlos a un asesor.
- asesor: solo ve y actualiza los leads que le asignaron.

Autenticación con sesión (cookie firmada) contra la tabla `usuarios`
(contraseñas encriptadas con bcrypt). Vive en su propio módulo, separado
de la lógica del bot, para poder extraerse a otro servicio más adelante
sin tocar main.py/brain.py.
"""

import asyncio
import csv
import io
import html
import json
import logging
import mimetypes
import os
import re
import secrets
import subprocess
import tempfile
import uuid
import bcrypt
from datetime import datetime, timedelta, timezone, date as _date
from urllib.parse import quote_plus, urlencode
from fastapi import APIRouter, Depends, HTTPException, Form, Request, UploadFile, File, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse, Response, FileResponse
from sqlalchemy.exc import IntegrityError

from agent.tiempo_real import gestor_conexiones, emitir_ticket_ws, validar_y_consumir_ticket_ws
from agent.rate_limit import limitador_login, bloqueo_login, ip_cliente
from agent.panel_antiguo import url_panel_nuevo
from agent.memory import (
    resumen_uso_mensual,
    guardar_configuracion_uso_meta,
    estimar_uso_previo_servicio,
    primer_momento_de_uso_registrado,
    resumen_envios_por_origen,
    listar_envios_inciertos_o_huerfanos,
    obtener_configuracion_envios,
    listar_cambios_configuracion,
    _limites_de_mes_utc,
    listar_leads, obtener_lead, actualizar_lead,
    obtener_usuario, listar_asesores, listar_equipo, crear_usuario,
    asignar_asesor_a_lead, marcar_lead_visto, limpiar_revision_prioritaria, actualizar_disponibilidad, actualizar_nivel_asesor,
    toggle_usuario_activo, eliminar_usuario,
    listar_campanas, crear_campana, actualizar_campana, contar_opportunities_por_campana, eliminar_campana,
    listar_unidades_de_negocio, listar_productos_activos,
    obtener_campana, obtener_canal_whatsapp, listar_anuncios_detectados, asignar_anuncio_a_campana,
    diagnostico_anuncios_sin_campana, plan_migrar_comodines, aplicar_migrar_comodines, obtener_reglas_anuncio, guardar_regla_anuncio,
    historico_rellenar_conversaciones, historico_corregir_anuncios, historico_revertir,
    diagnostico_atribucion_multiple, historico_recalcular_primer_anuncio, auditoria_cierre_conversaciones_multiples,
    obtener_modo_reingreso_anuncio, guardar_modo_reingreso_anuncio, resumen_reingreso_anuncio, diagnostico_campos_referral,
    rendimiento_por_anuncio, guardar_empresa_grupo, aplicar_empresas_sugeridas, ventas_detalle_periodo,
    ids_conversacion_de_segmento, listar_empresas_anuncio, FORMATOS_FILTRO_ANUNCIO, PRODUCTOS_FILTRO_ANUNCIO,
    listar_atribucion_sin_campana_periodo, cerrar_lead_definitivamente_via_conversation, reabrir_caso_cerrado, MOTIVO_REABRIR_MAXIMO, CIERRE_GRACIA_HORAS_POR_DEFECTO,
    obtener_metas, guardar_metas,
    rango_periodo_utc, contar_flujo_periodo, calcular_embudo_comercial, contar_oportunidades_por_asesor,
    distribucion_resultados_periodo, resumen_ventas_periodo, productos_vendidos_periodo,
    cambiar_password, contar_conversations_activas_por_asesor, RESULTADOS_CERRADOS, listar_leads_agendados,
    contar_rotaciones_por_inactividad_por_asesor,
    listar_leads_esperando_asesor, listar_leads_pipeline, COLUMNAS_ORDEN_PIPELINE,
    listar_conversaciones_activas, obtener_contact_detalle, obtener_conversation_detalle, listar_eventos_de_conversation,
    listar_conversaciones_de_contact, resolver_opportunity_operable, resolver_conversation_operable,
    intentar_cambiar_resultado_opportunity, intentar_asignar_conversation, liberar_asignacion_via_conversation,
    cerrar_opportunity_con_venta, resolver_ids_operables_por_telefono, listar_lineas_venta_por_opportunity,
    registrar_evento_lead, listar_eventos_lead, intentar_avanzar_version,
    obtener_configuracion, guardar_configuracion,
    listar_lineas_venta, listar_lineas_venta_de_muchos,
    listar_canales_whatsapp, crear_canal_whatsapp, actualizar_canal_whatsapp,
    listar_productos, obtener_producto, crear_producto, editar_producto,
    toggle_producto, listar_historial_producto, importar_catalogo_desde_csv,
    CAMPOS_NEGOCIO_PRODUCTO, PLAZOS_CUOTAS_CATALOGO,
    iso_utc, ROLES_CON_VISION_TOTAL, tiene_acceso_a_lead, liberar_asignacion,
    obtener_conversation_realtime, obtener_conversation_activa_de_telefono,
    resolver_conversation_ids_por_telefono, listar_clientes_esperando, contar_casos_activos,
    VISTAS_INICIO, componer_vista_inicio, resolver_entradas_vista_inicio,
    MOTIVO_ATENDIDO_MAXIMO, registrar_atendido_manual,
    obtener_negocio, obtener_identidad_agente, listar_horarios_atencion,
    actualizar_negocio, crear_o_actualizar_identidad_agente, guardar_horario_atencion,
)
from agent.services.servicio_conversacion import servicio_conversacion
from agent.http_utils import get_con_reintentos, post_con_reintentos
from agent.meta_timezones import zona_iana_de_meta
from agent import envios
from agent import circuito_ia
from agent import plantilla_retomar
from agent import atencion_atrasada
from agent import calendario_negocio as cal_negocio
from agent import llamadas
from agent import pipeline_etapas
from agent import derivacion_automatica
from agent import plantillas_sms
from agent import origen_conversacion
from agent.politica_password import validar_password
from agent.analitica_tendencia import partir_periodo
from agent import analitica_senales
from agent import analitica_metas
from agent import memory as mem
from agent.calidad_catalogo import avisos_de_calidad_catalogo
from agent.memory import FILAS_CATALOGO_EXCLUIDAS, _fila_csv_a_datos
from agent.memory import obtener_estado_ventana

# Paleta de colores para distinguir canales de WhatsApp en el panel — se
# asigna por posición (orden de creación), no por nombre, así que un canal
# siempre se ve del mismo color mientras no se agreguen/quiten otros antes
# que él en la lista.
_PALETA_CANAL = [
    ("#e0f2fe", "#0369a1"),  # celeste
    ("#ede9fe", "#6d28d9"),  # morado
    ("#dcfce7", "#15803d"),  # verde
    ("#fef3c7", "#b45309"),  # ámbar
    ("#fce7f3", "#be185d"),  # rosa
]


async def _mapa_canales(negocio_id: str) -> dict:
    """Nombre + color de cada canal de WhatsApp, indexado por phone_number_id
    — para pintar el badge de canal en leads/conversaciones sin repetir la
    consulta en cada fila."""
    canales = await listar_canales_whatsapp(negocio_id=negocio_id)
    return {
        c["phone_number_id"]: {"nombre": c["nombre"], "color": _PALETA_CANAL[i % len(_PALETA_CANAL)]}
        for i, c in enumerate(canales)
    }


def _badge_canal(numero_whatsapp_id: str | None, mapa_canales: dict, compacto: bool = False) -> str:
    """Badge con el nombre del canal (número de WhatsApp) por el que entró
    la conversación — vacío si el lead es de antes de esta función o si solo
    hay un canal configurado (no aporta nada distinguirlo en ese caso)."""
    if not numero_whatsapp_id or len(mapa_canales) <= 1:
        return ""
    extra = "font-size:.62rem;padding:.1rem .4rem;" if compacto else ""
    canal = mapa_canales.get(numero_whatsapp_id)
    if not canal:
        return f'<span class="badge-suave" style="{extra}background-color:#f1f5f9;color:#64748b">Canal desconocido</span>'
    bg, texto = canal["color"]
    return f'<span class="badge-suave" style="{extra}background-color:{bg};color:{texto}">{html.escape(canal["nombre"])}</span>'
from agent.services.servicio_canales import servicio_canales
from agent.brain import RESUMEN_FALLIDO, RESUMEN_SIN_SALDO, cargar_system_prompt, generar_resumen_conversacion
from agent.tools import (
    obtener_producto_por_codigo, buscar_productos, CUOTAS_MIN, CUOTAS_MAX,
    calcular_cuota_producto, obtener_tasas_financiamiento,
    CLAVE_CONFIG_TEA, CLAVE_CONFIG_IGV,
)
from agent.notificaciones import notificar_solicitud_reseteo, notificar_lead_derivado
from agent.asignacion import UMBRAL_SENIOR_DEFAULT, UMBRAL_INTERMEDIO_DEFAULT
from agent.services.servicio_comercial import (
    servicio_comercial, MODALIDADES_PAGO, MEDIO_PAGO_FINANCIADO, MEDIOS_PAGO_CONTADO,
)
from agent.services.servicio_identidad import servicio_identidad, NoAutenticado
from agent.providers import obtener_proveedor

logger = logging.getLogger("agentkit")

router = APIRouter(prefix="/dashboard")

# Carpeta donde viven los archivos adjuntos (proformas/catálogos) enviados
# por los asesores. En Railway apunta a un Volume persistente (el disco del
# contenedor es efímero — se pierde en cada redeploy); en local, una carpeta
# normal alcanza. Ver ArchivoAdjunto en agent/memory.py para los metadatos.
ARCHIVOS_DIR = os.getenv("ARCHIVOS_DIR", "data/archivos")
# Gate 2026-09-23 (pedido del usuario: "los asesores también deben poder
# enviar Word, PPT, imagen o Excel") — el set completo que WhatsApp Cloud
# API acepta para mensajes de documento (confirmado contra la referencia
# oficial de Meta: text/plain, Word, Excel, PowerPoint y PDF, todos hasta
# 100MB — ver "Supported Media Types" en developers.facebook.com/docs/
# whatsapp/cloud-api/reference/media). No es una elección nuestra: ninguna
# herramienta que use la API de WhatsApp puede ir más allá de este set,
# así que "lo que usa el mercado" es exactamente esto.
EXTENSIONES_DOCUMENTO_PERMITIDAS = {".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".txt"}
EXTENSIONES_IMAGEN_PERMITIDAS = {".jpg", ".jpeg", ".png"}
EXTENSIONES_ARCHIVO_PERMITIDAS = EXTENSIONES_DOCUMENTO_PERMITIDAS | EXTENSIONES_IMAGEN_PERMITIDAS
TAMANO_MAXIMO_ARCHIVO_MB = 20  # audio / adjunto reutilizable / import CSV — sin cambios, no es el gap reportado
# 2026-09-16, hallazgo del usuario: un PDF real (catálogo/proforma) de más
# de 20MB no se podía adjuntar en el chat, aunque Meta acepta documentos
# hasta 100MB — un solo tope de 20MB para todo (arriba) era innecesariamente
# conservador para PDFs. Se separa por tipo: documentos con margen bajo el
# límite real de Meta, imágenes en su límite real (5MB, no negociable — ahí
# si Meta rechaza más arriba). Solo aplica a `enviar_archivo_chat`.
TAMANO_MAXIMO_DOCUMENTO_MB = 75
TAMANO_MAXIMO_IMAGEN_MB = 5


def _tamano_maximo_para_extension(extension: str) -> int:
    """Tope de tamaño en MB para un adjunto de chat, según su extensión —
    documentos (PDF/Word/Excel/PowerPoint/texto) con margen bajo el límite
    real de Meta (100MB), imágenes en su límite real (5MB). Antes solo
    reconocía ".pdf" como documento — cualquier extensión nueva (Word,
    Excel, PowerPoint) caía por descarte en el tope de 5MB de imagen, muy
    por debajo de lo que Meta realmente permite para esos tipos. Función
    separada (no inline en `enviar_archivo_chat`) para poder probar la
    selección del tope sin tener que armar un UploadFile/lead/canal real."""
    return TAMANO_MAXIMO_DOCUMENTO_MB if extension in EXTENSIONES_DOCUMENTO_PERMITIDAS else TAMANO_MAXIMO_IMAGEN_MB

NIVELES_ASESOR = ["junior", "intermedio", "senior"]
ETAPAS_FUNNEL = ["explorando", "comparando_producto", "evaluando_financiamiento", "derivado_asesor"]
ETIQUETAS_FUNNEL = {
    "explorando": "Explorando",
    "comparando_producto": "Comparando producto",
    "evaluando_financiamiento": "Evaluando financiamiento",
    "derivado_asesor": "Derivado a asesor",
    "vendido": "Vendido",
}
RESULTADOS = [
    "agendado", "vendido", "no_interesado", "no_califica", "no_es_cliente_calidda",
    "producto_sin_stock", "otro", "consulta_atc", "sin_saldo",
    "servicio_postventa", "cartera_fnb", "sin_respuesta", "postventa", "solicita_suministro_gas",
]
# Los que NO están en RESULTADOS_CERRADOS (importado de memory.py) se
# consideran "en seguimiento" — casos activos, con algo pendiente por
# resolver (una cita, esperar stock, esperar que el cliente tenga saldo).
RESULTADOS_SEGUIMIENTO = tuple(r for r in RESULTADOS if r not in RESULTADOS_CERRADOS)
ETIQUETAS_RESULTADO = {
    "agendado": "Agendado",
    "vendido": "Vendido",
    "no_interesado": "No interesado",
    "no_califica": "No califica",
    "no_es_cliente_calidda": "No es cliente Calidda",
    "producto_sin_stock": "Producto sin stock",
    "otro": "Otro",
    "consulta_atc": "Consulta ATC",
    "sin_saldo": "Sin saldo",
    # Renombrado (2026-09-28, hallazgo del usuario): la clave `servicio_postventa`
    # es de un negocio distinto — servicios adicionales de gas, no el
    # seguimiento posventa de una venta de producto que se está diseñando
    # ahora (punto 3, ese va a ser un resultado NUEVO, "Postventa", todavía
    # sin construir). Se deja la clave en la base tal cual (nadie migra datos
    # por un cambio de etiqueta) — solo cambia el texto que ve la persona.
    "servicio_postventa": "Servicio adicional Gas",
    "cartera_fnb": "Cartera FNB",
    "sin_respuesta": "Sin respuesta",
    # Resultado nuevo (Punto 3, 2026-09-28): lo pone SOLO `enrutar_
    # posventa_si_corresponde` (agent/memory.py), nunca un asesor a mano —
    # marca la Conversation nueva que se abre cuando un cliente con una
    # venta ("vendido") ya cerrada definitivamente vuelve a escribir.
    "postventa": "Postventa",
    # Lo pone SOLO Gabi (agent/calificacion_guiada.py): el cliente no tiene gas natural y quiere contratarlo; esa venta es de
    # otra subunidad de Cálidda Hogar (Nuevos suministros), a la que se le dio el teléfono. Cierra el caso.
    "solicita_suministro_gas": "Solicita suministro de gas",
}
# ROLES_CON_VISION_TOTAL vive en agent/memory.py (importado arriba) — no acá:
# agent/tiempo_real.py (el WebSocket) necesita el mismo valor para filtrar a
# quién emitirle un evento, y no puede importar este módulo sin crear un
# ciclo (dashboard.py ya importa tiempo_real.py). Antes eran dos copias del
# mismo valor, con riesgo real de desincronizarse.

COLOR_RESULTADO = {
    "agendado": "#2563eb",
    "vendido": "#16a34a",
    "no_interesado": "#ef4444",
    "no_califica": "#e11d48",
    "no_es_cliente_calidda": "#b91c1c",
    "producto_sin_stock": "#f97316",
    "otro": "#6b7280",
    "consulta_atc": "#7c3aed",
    "solicita_suministro_gas": "#0891b2",
    "sin_saldo": "#d97706",
    "servicio_postventa": "#0d9488",
    "cartera_fnb": "#4f46e5",
    "sin_respuesta": "#94a3b8",
    "postventa": "#ca8a04",
}

# Estados de conversación para las pestañas de filtro del panel — dos grupos:
# los de Gabi (antes de derivar a un humano) y los del asesor humano (después
# de derivar). "todos" no es un estado real del lead, es la vista sin filtrar.
ESTADOS_GABI = ["explorando", "comparando_producto", "evaluando_financiamiento"]
ESTADOS_DERIVADO = ["pendiente_asignar", "asignado", "en_atencion", "resuelto"]
ETIQUETAS_ESTADO = {
    "explorando": "Explorando",
    "comparando_producto": "Comparando producto",
    "evaluando_financiamiento": "Evaluando financiamiento",
    "pendiente_asignar": "Pendiente asignar",
    "asignado": "Asignados",
    "en_atencion": "En atención",
    "resuelto": "Resueltos",
}
ICONO_ESTADO = {
    "explorando": ("bi-search", "#0284c7"),
    "comparando_producto": ("bi-basket-fill", "#4f46e5"),
    "evaluando_financiamiento": ("bi-cash-coin", "#d97706"),
    "pendiente_asignar": ("bi-hourglass-split", "#dc2626"),
    "asignado": ("bi-person-check-fill", "#2563eb"),
    "en_atencion": ("bi-chat-dots-fill", "#7c3aed"),
    "resuelto": ("bi-check-circle-fill", "#15803d"),
}
# Versión "suave" (fondo pastel + texto de color) de la misma paleta, para
# badges menos saturados/tipo spreadsheet — look ejecutivo, no alerta.
COLOR_ESTADO_SUAVE = {
    "explorando": ("#e0f2fe", "#0369a1"),
    "comparando_producto": ("#eef2ff", "#4338ca"),
    "evaluando_financiamiento": ("#fef3c7", "#b45309"),
    "pendiente_asignar": ("#fee2e2", "#b91c1c"),
    "asignado": ("#dbeafe", "#1d4ed8"),
    "en_atencion": ("#f3e8ff", "#6d28d9"),
    "resuelto": ("#dcfce7", "#15803d"),
}


def _estado_conversacion(lead: dict) -> str:
    """
    Clasifica un lead en un único estado de conversación, combinando el
    flujo de Gabi (paso_flujo, antes de derivar a un humano) con el estado
    del asesor humano (después de derivar) — usando solo los campos que ya
    existen (paso_flujo, asesor_asignado, resultado), sin necesitar un
    campo nuevo en la base de datos.
    """
    if lead.get("resultado") in RESULTADOS_CERRADOS:
        return "resuelto"
    paso = lead.get("paso_flujo")
    if paso != "derivado_asesor":
        return paso if paso in ESTADOS_GABI else "explorando"
    if not lead.get("asesor_asignado"):
        return "pendiente_asignar"
    if lead.get("resultado") in RESULTADOS_SEGUIMIENTO:
        return "en_atencion"
    return "asignado"


def _calcular_embudo(leads: list[dict]) -> list[tuple[str, int, int]]:
    """
    Calcula el embudo de forma ACUMULADA: cada etapa cuenta los leads que
    llegaron a ESA etapa o más allá (asumiendo progreso lineal por
    paso_flujo), terminando en "vendido" (via resultado). El porcentaje es
    respecto al total de leads con una etapa conocida (= 100% la primera).

    Nota: como paso_flujo se sobreescribe (no guardamos historial de por
    qué etapas pasó cada lead), esto es una aproximación razonable, no una
    medición exacta — si un lead "retrocede" de etapa, distorsiona un poco
    el conteo.

    Retorna lista de (etiqueta, cantidad, porcentaje).
    """
    indice_etapa = {etapa: i for i, etapa in enumerate(ETAPAS_FUNNEL)}
    indices_leads = [indice_etapa[l["paso_flujo"]] for l in leads if l.get("paso_flujo") in indice_etapa]
    total_base = len(indices_leads)

    resultado = []
    for i, etapa in enumerate(ETAPAS_FUNNEL):
        cantidad = sum(1 for idx in indices_leads if idx >= i)
        pct = round(cantidad / total_base * 100) if total_base else 0
        resultado.append((ETIQUETAS_FUNNEL[etapa], cantidad, pct))

    vendidos = sum(1 for l in leads if l.get("resultado") == "vendido")
    pct_vendidos = round(vendidos / total_base * 100) if total_base else 0
    resultado.append((ETIQUETAS_FUNNEL["vendido"], vendidos, pct_vendidos))

    return resultado


# NoAutenticado y la resolución de usuario actual viven ahora en
# ServicioIdentidad (Backend Architecture) — se mantienen estos nombres
# como alias para no tocar los ~50 call sites existentes de
# Depends(_usuario_actual) en este archivo.
_usuario_actual = servicio_identidad.usuario_actual


# ── CSRF explícito (Security Architecture, Decisión local ya "Objetivo") ──
#
# El token se genera una sola vez por sesión, lazy, en
# ServicioIdentidad.usuario_actual() — acá solo se consume: se inyecta en
# los formularios clásicos (_csrf_campo) y se valida en cada POST protegido
# (Depends(verificar_csrf)). /login y /recuperar quedan fuera a propósito:
# son pre-sesión, todavía no existe ningún token que comparar (ya mitigados
# por rate limiting + bloqueo por intentos). /webhook (agent/main.py) ni
# siquiera pasa por este router — se autentica por firma HMAC de Meta, no
# por sesión, y no debe llevar CSRF.

def _csrf_campo(request: Request | None) -> str:
    """Campo oculto con el token CSRF de la sesión actual, para insertar
    dentro de cualquier <form method="post"> clásico del panel. Tolera
    request=None (páginas pre-sesión como login/recuperar, que no llevan
    este campo en sus propios forms) sin romper — devuelve un campo vacío
    en vez de lanzar, para no crashear un render por un dato que esas
    páginas no necesitan."""
    token = request.session.get("csrf_token", "") if request is not None else ""
    return f'<input type="hidden" name="csrf_token" value="{html.escape(token)}">'


async def verificar_csrf(request: Request) -> None:
    """Dependency reutilizable — mismo patrón que requiere_rol(), agregada
    a cada ruta POST protegida. Acepta el token por header (fetch/JS, los 6
    call sites que no usan un <form>) o por campo de formulario (form
    clásico, urlencoded/multipart). No consume el body si el header ya trajo
    el token, y solo intenta leer el form cuando el Content-Type es
    compatible — evita interferir con bodies JSON (Embedded Signup) y
    reutiliza el cache de Starlette del body en vez de consumir el stream
    dos veces, así que no rompe el parseo de archivos que hace la propia
    ruta después (UploadFile/Form)."""
    token_sesion = request.session.get("csrf_token")
    token_enviado = request.headers.get("x-csrf-token")
    if not token_enviado:
        content_type = request.headers.get("content-type", "")
        if "form" in content_type:
            formulario = await request.form()
            token_enviado = formulario.get("csrf_token")
    if not token_sesion or not token_enviado or not secrets.compare_digest(str(token_sesion), str(token_enviado)):
        raise HTTPException(status_code=403, detail="Token CSRF inválido o ausente — recarga la página e intenta de nuevo")


def _verificar_acceso_lead(usuario: dict, lead: dict):
    """Un asesor solo puede ver/editar sus propios leads asignados."""
    if not tiene_acceso_a_lead(usuario["rol"], usuario["username"], lead.get("asesor_asignado")):
        raise HTTPException(status_code=403, detail="No tienes acceso a este lead")


# ── WebSocket del panel (chat en vivo, lista en vivo, "escribiendo...") ─
#
# Una sola conexión persistente por sesión de navegador — se abre una vez al
# cargar la página (ver _script_tiempo_real) y sobrevive a la navegación
# AJAX interna (no se re-crea en cada clic), así que no hay que reconectar
# cada vez que se abre un chat distinto. El cliente avisa qué lead tiene
# activo con el mensaje "ver_lead"; el servidor usa eso para saber a quién
# mandarle el "escribiendo..." de otro miembro del equipo.

# Allowlist de orígenes cross-origin autorizados a abrir este WebSocket —
# hoy solo hace falta para la Nueva Experiencia (Next.js/Vercel), que corre
# en un origen DISTINTO al de este backend. El panel legacy (servido por
# este mismo FastAPI) siempre es same-origin y se detecta comparando el
# Origin del navegador contra el Host de la propia solicitud (ver
# _origen_websocket_permitido) — no necesita estar en esta lista, y no se
# hardcodea acá el dominio de Railway porque Railway lo asigna, no nosotros.
#
# IMPORTANTE — pendiente operativo: hay que configurar FRONTEND_ORIGINS_PERMITIDOS
# en las variables de entorno de Railway con el dominio real de producción
# del frontend en Vercel antes de que la Nueva Experiencia pueda abrir este
# WebSocket contra el backend en producción — no está documentado en este
# repo cuál es ese dominio, así que no se puede hardcodear con certeza acá.
_ORIGENES_WS_PERMITIDOS = {
    o.strip() for o in os.getenv(
        "FRONTEND_ORIGINS_PERMITIDOS", "http://localhost:3000,http://127.0.0.1:3000",
    ).split(",") if o.strip()
}


def _origen_websocket_permitido(websocket: WebSocket) -> bool:
    """True si el Origin del navegador es el mismo origen que este backend
    (panel legacy, calculado a partir del propio Host de la solicitud — sin
    hardcodear el dominio de Railway) o si está en la allowlist explícita de
    FRONTEND_ORIGINS_PERMITIDOS (la Nueva Experiencia, en otro origen).
    Clientes que no mandan Origin (algunos clientes no-navegador) se dejan
    pasar — no hay nada que validar sin ese header, mismo comportamiento que
    antes de este chequeo."""
    origen = websocket.headers.get("origin")
    if not origen:
        return True
    host = websocket.headers.get("host", "")
    esquema_http = "https" if websocket.url.scheme == "wss" else "http"
    if origen == f"{esquema_http}://{host}":
        return True
    return origen in _ORIGENES_WS_PERMITIDOS


async def _resolver_conversation_ws(datos: dict, negocio_id: str) -> dict | None:
    """Resuelve la Conversation pedida por un mensaje `ver_lead`/`escribiendo`
    del cliente WS, aceptando CUALQUIERA de los dos identificadores que hoy
    coexisten (Gate 5.5, Legacy — coexistencia, no ventana de transición):
    `conversation_id` (Nueva Experiencia, una vez migrado el BFF) o
    `telefono` (panel legacy, que sigue usándolo indefinidamente). Ambos se
    resuelven con candado de `negocio_id` — SIEMPRE de la sesión WS ya
    resuelta en `websocket_panel`, nunca del mensaje del cliente (mismo
    criterio Gate 5.4/T1, extendido a la identidad nueva)."""
    conversation_id = datos.get("conversation_id") or None
    if conversation_id:
        return await obtener_conversation_realtime(conversation_id, negocio_id=negocio_id)
    telefono = datos.get("telefono") or None
    if telefono:
        return await obtener_conversation_activa_de_telefono(telefono, negocio_id)
    return None


PLAZO_AUTH_WS_TICKET_SEG = 5.0


@router.post("/ws-ticket")
async def emitir_ticket_ws_ruta(usuario: dict = Depends(_usuario_actual), _csrf: None = Depends(verificar_csrf)):
    """Fase 2, tiempo real directo (MAIEK_AI_REALTIME_DIRECT_DESIGN.md) — la
    Nueva Experiencia (Vercel, otro origen) llama esto ANTES de abrir el
    WebSocket directo, con la cookie de sesión que sí le llega vía el BFF
    (same-origin desde el navegador hasta ahí). Exige sesión + CSRF, mismo
    candado que cualquier POST del panel — sin sesión válida no hay ticket."""
    return {"ticket": emitir_ticket_ws(usuario["username"])}


@router.websocket("/ws")
async def websocket_panel(websocket: WebSocket):
    if not _origen_websocket_permitido(websocket):
        logger.warning(f"WebSocket del panel rechazado por Origin no permitido: {websocket.headers.get('origin')}")
        await websocket.close(code=4403)
        return

    username_sesion = websocket.session.get("username")
    if username_sesion:
        # Camino legacy — cookie de sesión de Starlette, same-origin (panel
        # HTML servido por este mismo FastAPI). Sin cambios de comportamiento.
        usuario = await obtener_usuario(username_sesion)
        if usuario is None:
            await websocket.close(code=4401)
            return
        username = username_sesion
        await gestor_conexiones.conectar(websocket, username, usuario["rol"], usuario["negocio_id"])
    else:
        # Camino del ticket (Fase 2) — sin cookie de sesión (cross-origin: la
        # Nueva Experiencia). Se acepta la conexión para poder leer el primer
        # mensaje (el protocolo WS exige aceptar antes de recibir nada) y se
        # exige {"tipo":"auth","ticket":...} dentro de PLAZO_AUTH_WS_TICKET_SEG.
        # Cualquier fallo (sin mensaje a tiempo, ticket inválido/vencido/
        # reutilizado, usuario inexistente) cierra con 4401 — mismo código que
        # el camino legacy usa para "sin sesión válida".
        await websocket.accept()
        try:
            datos_auth = await asyncio.wait_for(websocket.receive_json(), timeout=PLAZO_AUTH_WS_TICKET_SEG)
        except (TimeoutError, WebSocketDisconnect, ValueError, RuntimeError):
            await websocket.close(code=4401)
            return
        ticket = datos_auth.get("ticket") if isinstance(datos_auth, dict) and datos_auth.get("tipo") == "auth" else None
        username = validar_y_consumir_ticket_ws(ticket) if ticket else None
        usuario = await obtener_usuario(username) if username else None
        if usuario is None:
            await websocket.close(code=4401)
            return
        await gestor_conexiones.conectar(websocket, username, usuario["rol"], usuario["negocio_id"], ya_aceptado=True)
    try:
        while True:
            datos = await websocket.receive_json()
            tipo = datos.get("tipo")
            if tipo == "ver_lead":
                conversation_pedida = None
                if datos.get("conversation_id") or datos.get("telefono"):
                    # Mismo criterio de acceso que _verificar_acceso_lead —
                    # antes se aceptaba cualquier teléfono que el cliente
                    # mandara sin validar nada, así que un asesor podía
                    # marcarse como "viendo" un lead ajeno y recibir el
                    # "escribiendo..." de esa conversación. Gate 5.4/5.5:
                    # negocio_id siempre de la sesión WS ya resuelta arriba
                    # (usuario["negocio_id"]), nunca del mensaje del cliente.
                    conversation_pedida = await _resolver_conversation_ws(datos, usuario["negocio_id"])
                    if conversation_pedida is None or not tiene_acceso_a_lead(
                        usuario["rol"], usuario["username"], conversation_pedida.get("asesor_asignado_id"),
                    ):
                        continue
                await gestor_conexiones.set_conversation_activa(
                    websocket, conversation_pedida["id"] if conversation_pedida else None,
                )
            elif tipo == "escribiendo":
                conversation_actual = await _resolver_conversation_ws(datos, usuario["negocio_id"])
                if conversation_actual:
                    # excluir_username (no `excluir=websocket`): la conexión
                    # que dispara esta señal puede ser la efímera que abre el
                    # relay del BFF para POST /api/conversaciones/escribiendo,
                    # distinta de la conexión persistente de este mismo
                    # usuario que recibe el relay SSE — excluir por identidad
                    # de socket nunca las hacía coincidir (ver
                    # agent/tiempo_real.py).
                    await gestor_conexiones.emitir_escribiendo(
                        conversation_actual["id"], conversation_actual.get("telefono"),
                        usuario["nombre"], excluir_username=username,
                    )
    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.warning(f"Error en WebSocket del panel ({username}): {e}")
    finally:
        gestor_conexiones.desconectar(websocket)


# ── Estilos y layout (Bootstrap 5 vía CDN + ajustes propios) ──────────

BOOTSTRAP_CSS = '<link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css" rel="stylesheet">'
BOOTSTRAP_ICONS = '<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.3/font/bootstrap-icons.css">'
BOOTSTRAP_JS = '<script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/js/bootstrap.bundle.min.js"></script>'
FUENTE_INTER = (
    '<link rel="preconnect" href="https://fonts.googleapis.com">'
    '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
    '<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap" rel="stylesheet">'
)

ESTILOS_PROPIOS = """
  :root { --gaso-azul: #00A1DE; --gaso-azul-osc: #075E85; --gaso-secundario: #3CCBDA; --gaso-fondo: #F8FAFC; }
  html { height: 100%; }
  body {
    background: var(--gaso-fondo);
    height: 100vh; height: 100dvh;
    display: flex; flex-direction: column;
    overflow: hidden;
    font-family: 'Inter', 'Segoe UI', Arial, sans-serif;
  }

  /* #contenido-app envuelve el cuerpo de cada página para poder
     reemplazarlo por AJAX sin recargar (ver navegarAjax). Sin display:flex
     acá, el flex:1 1 auto/min-height:0 de .shell y .login-shell más abajo
     no tenían efecto (no son hijos flex de nada) y el contenido se salía
     de la pantalla en vez de ocupar el alto disponible y scrollear adentro. */
  #contenido-app { flex: 1 1 auto; min-height: 0; display: flex; flex-direction: column; }

  /* Bootstrap 5.3 define los colores de .btn-primary como variables propias
     del componente (no heredan de --bs-primary en :root), así que hay que
     pisarlas directo para que el celeste de marca llegue a los botones. */
  .btn-primary {
    --bs-btn-bg: var(--gaso-azul); --bs-btn-border-color: var(--gaso-azul);
    --bs-btn-hover-bg: var(--gaso-azul-osc); --bs-btn-hover-border-color: var(--gaso-azul-osc);
    --bs-btn-active-bg: var(--gaso-azul-osc); --bs-btn-active-border-color: var(--gaso-azul-osc);
    --bs-btn-disabled-bg: var(--gaso-azul); --bs-btn-disabled-border-color: var(--gaso-azul);
    --bs-btn-focus-shadow-rgb: 0,161,222;
  }
  .btn-outline-primary {
    --bs-btn-color: var(--gaso-azul); --bs-btn-border-color: var(--gaso-azul);
    --bs-btn-hover-bg: var(--gaso-azul); --bs-btn-hover-border-color: var(--gaso-azul);
    --bs-btn-active-bg: var(--gaso-azul); --bs-btn-active-border-color: var(--gaso-azul);
  }
  .text-primary { color: var(--gaso-azul) !important; }
  .form-control:focus, .form-select:focus { border-color: var(--gaso-azul); box-shadow: 0 0 0 .25rem rgba(0,161,222,.25); }

  /* El navbar y la franja de resumen tienen su alto natural (varía en
     mobile porque el navbar se envuelve a 2 líneas); .shell ocupa TODO lo
     que sobra con flex, en vez de un cálculo de píxeles fijo que se
     desalinea apenas el navbar cambia de alto. */
  .navbar-gaso {
    background: radial-gradient(circle at top left, var(--gaso-azul), var(--gaso-azul-osc) 70%);
    box-shadow: 0 2px 10px rgba(7,94,133,0.35);
    flex-shrink: 0;
  }

  #barra-carga {
    position: fixed; top: 0; left: 0; height: 3px; width: 0%;
    background: var(--gaso-secundario); z-index: 2000;
    transition: width 0.4s ease-out, opacity 0.2s ease-out; opacity: 0;
  }
  #barra-carga.activa { opacity: 1; }
  .navbar-gaso .navbar-brand { color: white !important; font-weight: 800; letter-spacing: -0.02em; font-size: 1.15rem; }
  .navbar-gaso .navbar-brand .plus { color: var(--gaso-secundario); }
  /* Sección activa en la barra superior (Métricas/Campañas/etc.) — se
     asigna por JS (ver actualizarNavActiva en _pagina), no por Python, porque
     la barra es parte del shell fijo de la página y no se vuelve a renderizar
     en cada navegación AJAX interna. */
  .nav-superior-link { padding: 4px 8px; border-radius: 6px; border-bottom: 2px solid transparent; transition: background-color .15s ease, border-color .15s ease; }
  .nav-superior-link.activo { background: rgba(255,255,255,.16); border-bottom-color: var(--gaso-secundario); color: #fff !important; }

  .avatar {
    display: inline-flex; align-items: center; justify-content: center;
    border-radius: 50%; font-weight: 700; color: white; flex-shrink: 0;
    background: linear-gradient(135deg, var(--gaso-azul), var(--gaso-secundario));
  }

  /* Sidebar de navegación de nivel 1 (MAIEK_AI_PRODUCT_PATTERNS.md, Cap. 1 —
     Shell de Navegación), implementación incremental — lista vertical fija,
     hermana de #contenido-app dentro de .app-shell, así que el shell no se
     reconstruye en cada navegación AJAX interna (solo #contenido-app se
     reemplaza). Colores del Gaso+ actual (no --mdl-*): queda pegado al
     navbar, que todavía no migró — un segundo azul de marca ahí se vería
     como dos identidades distintas en la misma franja. */
  .app-shell { flex: 1 1 auto; min-height: 0; display: flex; overflow: hidden; }
  .nav-lateral {
    width: 210px; min-width: 210px; flex-shrink: 0; overflow-y: auto;
    background: #fff; border-right: 1px solid #e2e8f0; padding: 10px 8px;
  }
  .nav-lateral-link {
    display: flex; align-items: center; gap: 10px; padding: 8px 12px; margin-bottom: 2px;
    border-radius: 8px; color: #334155; text-decoration: none; font-size: .87rem; font-weight: 500;
    transition: background-color .15s ease, color .15s ease;
  }
  .nav-lateral-link i { font-size: .95rem; width: 18px; text-align: center; color: #64748b; }
  .nav-lateral-link:hover { background: #f1f5f9; color: #0f172a; }
  .nav-lateral-link.activo { background: #e0f2fe; color: var(--gaso-azul-osc); }
  .nav-lateral-link.activo i { color: var(--gaso-azul); }

  /* Sidebar colapsable a solo íconos (MAIEK_AI_PRODUCT_PATTERNS.md, Cap. 1,
     sección 5 — "280px expandido / 64px colapsado"). Solo en desktop: en
     mobile el Sidebar ya es un overlay a pantalla completa (más abajo, con
     !important) y nunca debe reducirse a un ancho intermedio ilegible —
     por eso esta regla vive detrás de min-width, nunca puede pisar esa otra. */
  @media (min-width: 769px) {
    .nav-lateral { transition: width var(--t-fast, .15s) ease; }
    .nav-lateral.colapsado { width: 56px !important; min-width: 56px; flex-basis: 56px; }
    .nav-lateral.colapsado .nav-lateral-link { justify-content: center; padding: 8px; }
    .nav-lateral.colapsado .nav-lateral-link span { display: none; }
  }
  .nav-lateral-toggle {
    display: flex; align-items: center; gap: 10px; width: 100%;
    padding: 8px 12px; margin-top: 4px; border: none; background: none;
    border-radius: 8px; color: #64748b; font-size: .82rem; font-weight: 500;
    cursor: pointer; transition: background-color .15s ease, color .15s ease;
  }
  .nav-lateral-toggle i { font-size: .95rem; width: 18px; text-align: center; flex-shrink: 0; }
  .nav-lateral-toggle:hover { background: #f1f5f9; color: #0f172a; }
  .nav-lateral.colapsado .nav-lateral-toggle { justify-content: center; padding: 8px; }
  .nav-lateral.colapsado .nav-lateral-toggle span { display: none; }

  .shell { flex: 1 1 auto; min-height: 0; }
  .rail-estados { width: 230px; min-width: 230px; flex-shrink: 0; overflow-y: auto; background: #fbfcfe; }
  .sidebar { width: 320px; min-width: 320px; flex-shrink: 0; overflow-y: auto; background: #fff; }
  .sidebar-head { background: var(--gaso-fondo); }

  .barra-resumen {
    display: flex; flex-wrap: wrap; gap: 18px; align-items: center;
    padding: 8px 20px; background: #fff; border-bottom: 1px solid #e2e8f0;
    font-size: .78rem; color: #475569; flex-shrink: 0;
  }
  .barra-resumen strong { color: var(--gaso-azul-osc); font-size: .95rem; }
  .convo-item { border: none !important; border-bottom: 1px solid #eef1f5 !important; border-radius: 0 !important; }
  .convo-item.activo { background-color: #e0f7fa; box-shadow: inset 3px 0 0 var(--gaso-azul); }
  .convo-item:hover { background-color: #f8fafc; }
  .convo-preview { font-size: 11.5px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .main-pane { overflow-y: auto; min-height: 0; }

  /* Panel de chat: header y cuadro de respuesta fijos y compactos, solo los mensajes hacen scroll */
  .main-pane.chat-mode { overflow-y: hidden; padding: 0 !important; display: flex; flex-direction: column; }
  .chat-header-fijo { flex-shrink: 0; padding: .55rem 1.25rem; border-bottom: 1px solid #e2e8f0; background: #fff; }
  .chat-header-fijo .badge { vertical-align: middle; margin-left: 4px; }
  .chat-mensajes-wrap { flex: 1 1 auto; min-height: 0; padding: .75rem 1.25rem 0; display: flex; flex-direction: column; }
  .chat-mensajes-wrap .card { flex: 1 1 auto; min-height: 0; margin: 0; }
  .chat-mensajes-wrap #chat { height: 100%; overflow-y: auto; }
  .chat-reply-fijo { flex-shrink: 0; padding: .6rem 1.25rem; background: #fff; border-top: 1px solid #e2e8f0; transition: background-color .15s, box-shadow .15s; }
  .chat-reply-fijo.zona-soltar-activa { background: #eaf7fd; box-shadow: inset 0 0 0 2px var(--gaso-azul); }
  #btn-audio.grabando { background: #ef4444; border-color: #ef4444; color: #fff; animation: pulso-grabando 1.2s ease-in-out infinite; }
  @keyframes pulso-grabando { 0%, 100% { opacity: 1; } 50% { opacity: .55; } }

  /* Botones de acción del chat (adjuntar/catálogo/micrófono) — grupo de
     íconos con fondo suave celeste en vez del outline gris genérico de
     Bootstrap, consistente con la paleta del resto del panel. */
  .btn-icono-chat {
    width: 38px; height: 38px; flex-shrink: 0; padding: 0;
    display: inline-flex; align-items: center; justify-content: center;
    border: none; border-radius: 12px; background: #eaf7fd; color: var(--gaso-azul-osc);
    transition: background-color .15s, color .15s;
  }
  .btn-icono-chat:hover { background: #d5eefb; color: var(--gaso-azul); }
  .btn-icono-chat:disabled { opacity: .5; }

  /* Reproductor de audio propio (notas de voz) — reemplaza el <audio
     controls> nativo del navegador (look "Windows 95") tanto en las
     burbujas del chat como en la previsualización antes de enviar. */
  .reproductor-audio {
    display: inline-flex; align-items: center; gap: 8px;
    background: #eaf7fd; border-radius: 999px; padding: 4px 14px 4px 4px;
    max-width: 220px; min-width: 170px;
  }
  .btn-play-audio {
    width: 28px; height: 28px; flex-shrink: 0; padding: 0; border: none; border-radius: 50%;
    background: var(--gaso-azul); color: #fff; display: inline-flex; align-items: center; justify-content: center;
    cursor: pointer; font-size: .8rem; transition: background-color .15s;
  }
  .btn-play-audio:hover { background: var(--gaso-azul-osc); }
  .barra-audio-wrap { flex: 1 1 auto; min-width: 50px; height: 4px; background: #bcdff1; border-radius: 999px; position: relative; cursor: pointer; }
  .barra-audio-progreso { position: absolute; left: 0; top: 0; height: 100%; width: 0%; background: var(--gaso-azul); border-radius: 999px; }
  .tiempo-audio { font-size: .68rem; color: var(--gaso-azul-osc); flex-shrink: 0; min-width: 30px; text-align: right; }
  #chat .msg .reproductor-audio { background: rgba(255,255,255,.6); }
  .btn-icono-chat.btn-descartar-audio { background: #fdeaea; color: #b91c1c; }
  .btn-icono-chat.btn-descartar-audio:hover { background: #fbd5d5; color: #991b1b; }

  /* A propósito NO usa la utilidad .d-flex de Bootstrap: esa clase trae
     !important, que le gana a un style="display:none" en línea — el JS que
     muestra/oculta esta barra según haya o no una nota de voz pendiente
     terminaba sin efecto visual y la barra quedaba SIEMPRE visible. */
  .previsualizacion-audio-bar { display: flex; }

  /* Banner para pedir permiso de notificaciones de escritorio — discreto,
     arriba de todo, se descarta solo (el navegador ya recuerda la decisión
     de Notification.requestPermission, así que no hace falta guardar nada
     propio para no volver a mostrarlo). */
  .banner-notificaciones {
    position: fixed; top: 0; left: 0; right: 0; z-index: 1500;
    background: var(--gaso-azul-osc); color: #fff;
    padding: 10px 16px; display: flex; align-items: center; justify-content: center;
    gap: 10px; font-size: .85rem; flex-wrap: wrap; text-align: center;
  }
  .btn-volver-movil { display: none; text-decoration: none; }
  .btn-filtros-movil { display: none; }
  .btn-resumen-movil { display: none; }
  .btn-menu-movil { display: none; }

  /* Vista de un lead: resumen del cliente + chat, lado a lado, ambos visibles
     a la vez (en vez de saltar entre dos páginas distintas). */
  .lead-vista { flex: 1 1 auto; min-height: 0; display: flex; overflow: hidden; }
  .lead-resumen-col { width: 380px; min-width: 380px; min-height: 0; flex-shrink: 0; overflow-y: auto; padding: 1rem; background: #f8fafc; border-right: 1px solid #e2e8f0; }
  .lead-chat-col { flex: 1 1 auto; min-width: 0; min-height: 0; display: flex; flex-direction: column; }

  /* Mobile: el rail y la lista de conversaciones ocupan toda la pantalla
     por turnos (como una app de chat), no columnas fijas apretadas. */
  @media (max-width: 768px) {
    /* !important porque .rail-estados también trae la utilidad .d-flex de
       Bootstrap (display:flex !important), que si no queda por encima. */
    .rail-estados { display: none !important; position: fixed; inset: 0; top: 58px; z-index: 1500; width: 100%; }
    .rail-estados.abierto { display: flex !important; }
    .btn-filtros-movil { display: inline-flex; }
    .sidebar { width: 100%; min-width: 0; }
    .main-pane { padding: 1rem !important; }
    /* La bajada de marca ("Commercial Operating System · Powered by
       Maiek AI") no entra en el navbar angosto de mobile sin romper el
       alto fijo de 58px que asume .rail-estados más abajo — se oculta y
       queda solo "Gaso+", igual que antes del rebrand. */
    .brand-subtitulo { display: none; }

    /* Sidebar de navegación (.nav-lateral) no entra apretado en el navbar de
       mobile — se oculta detrás de un botón ☰ y se despliega como panel,
       mismo patrón que .rail-estados.abierto. */
    .nav-lateral { display: none !important; }
    .nav-lateral.abierto {
      display: flex !important; flex-direction: column; align-items: stretch !important;
      position: fixed; inset: 0; top: 58px; z-index: 1600;
      background: #fff; padding: 10px 8px; gap: 2px !important;
      box-shadow: 0 4px 12px rgba(0,0,0,.25);
    }
    .btn-menu-movil { display: inline-flex !important; }

    /* El toggle de colapsar a íconos no existe en mobile — acá el Sidebar
       siempre es overlay a pantalla completa, nunca íconos solos (Cap. 1,
       sección 7: "nunca se comprime a un ancho intermedio ilegible"). */
    .nav-lateral-toggle { display: none !important; }

    /* Con un chat abierto: solo el chat se ve, a pantalla completa */
    body.pagina-chat .rail-estados,
    body.pagina-chat .nav-lateral,
    body.pagina-chat .sidebar { display: none !important; }
    body.pagina-chat .main-pane.chat-mode { width: 100%; }
    .btn-volver-movil { display: inline-flex; align-items: center; }

    .barra-resumen { overflow-x: auto; flex-wrap: nowrap; white-space: nowrap; }

    /* No entran las 2 columnas lado a lado: el chat queda de fondo (a pantalla
       completa) y el resumen del cliente se despliega arriba con el botón. */
    .lead-vista { flex-direction: column; }
    .lead-resumen-col { display: none; width: 100%; min-width: 0; max-height: 55vh; border-right: none; border-bottom: 1px solid #e2e8f0; }
    .lead-resumen-col.abierto { display: block; }
    .btn-resumen-movil { display: inline-flex; align-items: center; }
  }

  .estado-nav a, .equipo-item {
    display: flex; align-items: center; justify-content: space-between; gap: 6px;
    padding: 7px 16px; margin: 1px 8px; border-radius: 8px;
    text-decoration: none; color: #334155; font-size: .85rem;
  }
  /* Las etiquetas largas ("Pendiente asignar", nombres de asesor de dos
     palabras) se truncan con "..." en vez de partirse en dos líneas.
     .rail-label es el texto en sí (no el wrapper flex del avatar+nombre en
     .equipo-item, porque text-overflow no trunca bien dentro de un flex
     container); min-width:0 deja que el span se achique por debajo de su
     ancho de contenido natural, cosa que un hijo flex no hace por defecto. */
  .estado-nav a > span:first-child, .equipo-item > span:first-child { min-width: 0; }
  .rail-label { display: block; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; min-width: 0; }
  .estado-nav a:hover, .equipo-item:hover { background: #f1f5f9; }
  .estado-nav a.activo, .equipo-item.activo { background: var(--gaso-azul); color: #fff; font-weight: 600; }
  .estado-nav a.activo .badge-count, .equipo-item.activo .badge-count { background: rgba(255,255,255,.25); color: #fff; }
  .badge-count { background: #e2e8f0; color: #475569; border-radius: 999px; padding: 2px 9px; font-size: .72rem; font-weight: 600; flex-shrink: 0; }
  .mini-embudo { display: flex; flex-wrap: wrap; align-items: center; gap: 4px; }
  .chip-embudo {
    display: inline-flex; align-items: center; gap: 4px;
    padding: 3px 7px; border-radius: 999px; font-size: .72rem; font-weight: 700;
    text-decoration: none; border: 1.5px solid transparent; line-height: 1;
  }
  .chip-embudo:hover { filter: brightness(.95); }
  .chip-embudo.activo { border-color: currentColor; }
  .separador-embudo { color: #cbd5e1; font-size: .7rem; margin: 0 1px; }
  .sidebar-subtitulo { font-size: .68rem; letter-spacing: .05em; color: #94a3b8; padding: 10px 16px 4px; }

  .card { border: none; border-radius: 16px !important; }
  .card.funnel-card { border-radius: 12px !important; }

  /* Tabla de leads — look ejecutivo: filas tipo tarjeta de contacto, badges
     suaves, jerarquía tipográfica clara, sin grilla pesada tipo spreadsheet. */
  .leads-card { border-radius: 16px !important; overflow: hidden; box-shadow: 0 4px 24px rgba(15,23,42,.06) !important; }
  .leads-card .barra-acento { height: 4px; background: linear-gradient(90deg, var(--gaso-azul), var(--gaso-secundario)); }
  .tabla-ejecutiva thead th {
    border: none; border-bottom: 1px solid #eef1f5; background: #fff;
    text-transform: none; font-size: .78rem; font-weight: 700; color: #334155;
    padding: 10px 16px; letter-spacing: 0; white-space: nowrap;
  }
  .tabla-ejecutiva thead th .bi-arrow-down-up { opacity: 0; transition: opacity .15s; margin-left: 2px; }
  .tabla-ejecutiva thead th:hover .bi-arrow-down-up { opacity: .55; }
  .tabla-ejecutiva tbody tr { border-bottom: 1px solid #f4f6f8; transition: background-color .15s; }
  .tabla-ejecutiva tbody tr:last-child { border-bottom: none; }
  .tabla-ejecutiva tbody tr:hover { background: #f8fafc; }
  .tabla-ejecutiva tbody td { padding: 7px 16px; border: none; vertical-align: middle; font-size: .85rem; white-space: nowrap; }
  .avatar-anillo { display: inline-flex; border-radius: 50%; padding: 2px; border: 2px solid var(--anillo, #cbd5e1); flex-shrink: 0; }
  .badge-suave { padding: 5px 13px; border-radius: 999px; font-weight: 600; font-size: .74rem; display: inline-block; }

  #chat { background: #fbfcfe; }
  #chat .msg-row { display: flex; align-items: flex-end; gap: 6px; margin: 6px 0; }
  #chat .msg-row.mio { flex-direction: row-reverse; }
  #chat .msg { padding: 7px 11px; border-radius: 12px; max-width: 72%; white-space: pre-wrap; font-size: 13px; line-height: 1.45; box-shadow: 0 1px 2px rgba(0,0,0,0.05); }
  #chat .msg.user { background: white; border: 1px solid #e2e8f0; border-bottom-left-radius: 4px; }
  #chat .msg.assistant { background: #d9fdd3; border-bottom-right-radius: 4px; }
  #chat .msg.asesor { background: #ffe8cc; border-bottom-right-radius: 4px; }
  #chat .avatar-sm { width: 22px; height: 22px; font-size: 10px; }

  .funnel-card .icono { width: 36px; height: 36px; border-radius: 10px; display: flex; align-items: center; justify-content: center; font-size: 16px; color: white; box-shadow: 0 2px 6px rgba(0,0,0,0.15); }

  .login-shell { flex: 1 1 auto; background: radial-gradient(circle at top left, #e0f7fa, var(--gaso-fondo) 60%); }
  .login-card { border-radius: 16px !important; }
  .link-btn { border: none; margin: 0; }

  /* ── Inicio (MAIEK_AI_PRODUCT_PATTERNS.md, Cap. 3) ──────────────────
     Construido directamente con tokens del MDL (namespace --mdl-*, para no
     chocar con --gaso-*) — migración incremental (Principio 3 del corpus):
     el resto del panel no se toca, solo lo nuevo nace ya alineado. */
  :root {
    --mdl-primary-600: #1677FF; --mdl-navy-900: #0B1D3A; --mdl-navy-800: #0F2647;
    --mdl-neutral-0: #FFFFFF; --mdl-neutral-50: #F2F4F7; --mdl-neutral-200: #D2D7E0;
    --mdl-neutral-400: #9AA3B2; --mdl-neutral-600: #626C7E; --mdl-border: #E7EAEF;
    --mdl-success-text: #0F6E3B; --mdl-error-text: #9E1F1F;
    --mdl-space-4: 16px; --mdl-space-5: 20px; --mdl-space-6: 24px;
    --mdl-radius-lg: 14px;
    --mdl-elev-1: 0 1px 2px rgba(11,29,58,.06);
    --mdl-elev-2: 0 4px 12px rgba(11,29,58,.08), 0 1px 3px rgba(11,29,58,.06);
  }

  .vista-inicio { padding: var(--mdl-space-6); overflow-y: auto; flex: 1 1 auto; }

  /* Zona de acción — siempre primera, nunca la Zona de indicadores
     (Cap. 3: "acción antes que observación", en todo breakpoint). */
  .zona-accion { margin-bottom: var(--mdl-space-6); max-width: 640px; }
  .zona-accion-titulo {
    font-size: .8rem; font-weight: 600; color: var(--mdl-navy-900);
    text-transform: uppercase; letter-spacing: .04em; margin-bottom: var(--mdl-space-4);
  }
  .zona-accion-item {
    display: flex; align-items: center; gap: var(--mdl-space-4);
    background: var(--mdl-neutral-0); border: 1px solid var(--mdl-border);
    border-radius: var(--mdl-radius-lg); padding: var(--mdl-space-4) var(--mdl-space-5);
    margin-bottom: 10px; text-decoration: none; color: inherit;
    box-shadow: var(--mdl-elev-1); transition: box-shadow .15s ease;
  }
  .zona-accion-item:hover { box-shadow: var(--mdl-elev-2); color: inherit; }
  .zona-accion-item .nombre { font-weight: 600; color: var(--mdl-navy-900); font-size: .92rem; }
  .zona-accion-item .motivo { font-size: .78rem; color: var(--mdl-neutral-600); margin-top: 2px; }
  .zona-accion-vacio {
    background: var(--mdl-neutral-50); border-radius: var(--mdl-radius-lg);
    padding: var(--mdl-space-6); text-align: center; color: var(--mdl-neutral-600); font-size: .85rem;
  }

  /* Zona de indicadores — segunda, de apoyo (Cap. 3). */
  .zona-indicadores { display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: var(--mdl-space-4); max-width: 640px; }
  .kpi-card {
    background: var(--mdl-neutral-0); border: 1px solid var(--mdl-border);
    border-radius: var(--mdl-radius-lg); padding: var(--mdl-space-5);
    box-shadow: var(--mdl-elev-1);
  }
  .kpi-card .kpi-numero {
    font-size: 2rem; font-weight: 700; color: var(--mdl-navy-900); line-height: 1.1;
    font-variant-numeric: tabular-nums;
  }
  .kpi-card .kpi-etiqueta { font-size: .78rem; color: var(--mdl-neutral-600); margin-top: 4px; }

  /* ── Copiloto IA (MAIEK_AI_PRODUCT_PATTERNS.md, Cap. 5) ──────────────
     Primera implementación: contenedor extensible (AI Action Panel, CDS)
     con 3 zonas; en este Sprint solo la Zona de contexto tiene una
     capacidad activa (Resumen IA / AI Summary). Colapsado por defecto —
     "el panel nunca se auto-expande sin que el usuario lo pida". */
  .copiloto-panel { border: 1px solid var(--mdl-border); border-radius: var(--mdl-radius-lg); background: var(--mdl-neutral-0); margin-bottom: 10px; overflow: hidden; box-shadow: var(--mdl-elev-1); }
  .copiloto-header { display: flex; align-items: center; justify-content: space-between; gap: 8px; padding: 10px 14px; cursor: pointer; user-select: none; }
  .copiloto-header .titulo { display: flex; align-items: center; gap: 8px; font-weight: 600; font-size: .85rem; color: var(--mdl-navy-900); }
  .copiloto-header i.bi-stars { color: var(--mdl-primary-600); }
  .copiloto-cuerpo { display: none; padding: 0 14px 14px; border-top: 1px solid var(--mdl-border); }
  .copiloto-panel.abierto .copiloto-cuerpo { display: block; padding-top: 12px; }
  .copiloto-panel.abierto .copiloto-chevron { transform: rotate(180deg); }
  .copiloto-chevron { transition: transform .15s ease; color: var(--mdl-neutral-400); }
  .copiloto-zona-titulo { font-size: .72rem; font-weight: 600; text-transform: uppercase; letter-spacing: .03em; color: var(--mdl-neutral-600); margin-bottom: 6px; }
  .copiloto-resumen-texto { font-size: .83rem; color: var(--mdl-navy-900); line-height: 1.45; white-space: pre-wrap; }
  .copiloto-resumen-meta { font-size: .7rem; color: var(--mdl-neutral-400); margin-top: 6px; }
  .copiloto-resumen-desactualizado { color: #b45309 !important; font-weight: 600; }
"""

ICONO_ETAPA = {
    "Explorando": ("bi-search", "#0284c7"),
    "Comparando producto": ("bi-basket-fill", "#4f46e5"),
    "Evaluando financiamiento": ("bi-cash-coin", "#d97706"),
    "Derivado a asesor": ("bi-person-check-fill", "#be123c"),
    "Vendido": ("bi-trophy-fill", "#15803d"),
}


def _iniciales(nombre: str) -> str:
    partes = [p for p in nombre.strip().split() if p]
    if not partes:
        return "?"
    if len(partes) == 1:
        return partes[0][:2].upper()
    return (partes[0][0] + partes[-1][0]).upper()


def _avatar(nombre: str, size: int = 36, clase: str = "") -> str:
    return (
        f'<span class="avatar {clase}" style="width:{size}px;height:{size}px;font-size:{round(size * 0.4)}px">'
        f'{html.escape(_iniciales(nombre))}</span>'
    )


def _pill_resultado(resultado: str | None) -> str:
    if not resultado:
        return '<span class="badge rounded-pill text-white" style="background-color:#94a3b8">Pendiente</span>'
    color = COLOR_RESULTADO.get(resultado, "#94a3b8")
    etiqueta = ETIQUETAS_RESULTADO.get(resultado, resultado.replace("_", " ").capitalize())
    # "Agendado" lleva ícono de calendario para resaltarlo — es un caso
    # sensible al tiempo (hay una cita con el cliente) frente a los demás
    # resultados, que son solo texto.
    icono = '<i class="bi bi-calendar-event me-1"></i>' if resultado == "agendado" else ""
    return f'<span class="badge rounded-pill text-white" style="background-color:{color}">{icono}{html.escape(etiqueta)}</span>'


def _resumen_venta(lineas: list[dict]) -> dict:
    """Convierte la lista de líneas de venta de un lead en los mismos 4
    campos de texto que antes eran columnas sueltas en Lead
    (producto_vendido/marca_venta/proveedor_venta/precio_venta) — así la
    tabla de leads y la exportación (que ya leen esos nombres de campo)
    siguen funcionando igual sin reescribirse, ahora resumiendo N líneas
    en un solo texto por columna."""
    if not lineas:
        return {"producto_vendido": "", "marca_venta": "", "proveedor_venta": "", "precio_venta": "", "_busqueda_venta": ""}
    productos = [l["producto"] for l in lineas]
    marcas = sorted({l["marca"] for l in lineas if l.get("marca")})
    proveedores = sorted({l["proveedor"] for l in lineas if l.get("proveedor")})
    texto_producto = productos[0] if len(productos) == 1 else f"{productos[0]} +{len(productos) - 1} más"
    total = 0.0
    todos_numericos = True
    for l in lineas:
        try:
            total += float((l.get("precio") or "0").replace(",", ""))
        except ValueError:
            todos_numericos = False
    precio_texto = (
        # 2 decimales, no 0: redondear a entero acá era lo que hacía que
        # el ConfirmDialog (que suma a precisión completa en el cliente)
        # mostrara un monto distinto del que quedaba persistido — el
        # asesor aprobaba un número y el sistema guardaba otro.
        f"{total:.2f}" if todos_numericos
        else " + ".join(l.get("precio") or "0" for l in lineas)
    )
    return {
        "producto_vendido": texto_producto,
        "marca_venta": ", ".join(marcas),
        "proveedor_venta": ", ".join(proveedores),
        "precio_venta": precio_texto,
        # El texto resumido ("+1 más") no alcanza para buscar por un
        # producto que no sea el primero — este campo lleva TODOS los
        # nombres, solo para el buscador de la tabla, no para mostrar.
        "_busqueda_venta": " ".join(productos + marcas + proveedores),
    }


async def _adjuntar_resumen_ventas(leads: list[dict], negocio_id: str) -> list[dict]:
    """Sobreescribe producto_vendido/marca_venta/proveedor_venta/precio_venta
    de cada lead con el resumen de sus líneas de venta (una consulta para
    todos los leads, no una por fila) — para que la tabla/exportación, que
    ya leen esos 4 campos, muestren el cierre real sin cambiar su código."""
    telefonos = [l["telefono"] for l in leads]
    lineas_por_lead = await listar_lineas_venta_de_muchos(telefonos, negocio_id)
    for lead in leads:
        lead.update(_resumen_venta(lineas_por_lead.get(lead["telefono"], [])))
    return leads


def _titulo_seccion(icono: str, texto: str) -> str:
    """Encabezado de sección consistente (icono + texto) para armonizar toda la vista."""
    return (
        f'<div class="d-flex align-items-center gap-2 mb-3">'
        f'<i class="bi {icono}" style="color:var(--gaso-azul)"></i>'
        f'<h5 class="mb-0 fw-semibold">{html.escape(texto)}</h5></div>'
    )


def _script_notificaciones(usuario: dict | None) -> str:
    """Notificaciones de escritorio (como WhatsApp Web) para un lead nuevo
    asignado o un agendado a punto de tocar. Vive en el shell base de la
    página (fuera de #contenido-app, junto al script de navegación AJAX),
    no dentro de un chat — así el sondeo sigue corriendo sin importar qué
    pantalla del panel esté mirando el asesor en ese momento."""
    if not usuario:
        return ""
    username_js = json.dumps(usuario["username"])
    return f"""
    <script>
    (function() {{
        if (typeof Notification === 'undefined') return;

        const claveLeads = 'gaso_notif_leads_' + {username_js};
        const claveCitas = 'gaso_notif_citas_' + {username_js};

        function leerSet(clave) {{
            try {{ return new Set(JSON.parse(localStorage.getItem(clave) || '[]')); }}
            catch (e) {{ return new Set(); }}
        }}
        function guardarSet(clave, valores) {{
            localStorage.setItem(clave, JSON.stringify(Array.from(valores)));
        }}

        function mostrarBanner() {{
            if (document.getElementById('banner-notif')) return;
            const banner = document.createElement('div');
            banner.id = 'banner-notif';
            banner.className = 'banner-notificaciones';
            banner.innerHTML = '<i class="bi bi-bell-fill"></i> Activa las notificaciones de escritorio para enterarte de leads nuevos y citas próximas sin tener el panel abierto.' +
                ' <button type="button" class="btn btn-sm btn-light" id="btn-activar-notif">Activar</button>' +
                ' <button type="button" class="btn-close btn-close-white" id="btn-cerrar-notif" aria-label="Cerrar"></button>';
            document.body.appendChild(banner);
            document.getElementById('btn-activar-notif').addEventListener('click', function() {{
                Notification.requestPermission().then(function(permiso) {{
                    banner.remove();
                    if (permiso === 'granted') revisar();
                }});
            }});
            document.getElementById('btn-cerrar-notif').addEventListener('click', function() {{ banner.remove(); }});
        }}
        if (Notification.permission === 'default') mostrarBanner();

        function notificar(titulo, cuerpo, telefono) {{
            if (Notification.permission !== 'granted') return;
            const n = new Notification(titulo, {{ body: cuerpo, tag: 'gaso-' + telefono }});
            n.onclick = function() {{
                window.focus();
                window.location.href = '/dashboard/lead/' + encodeURIComponent(telefono);
            }};
        }}

        // A propósito NO se salta el sondeo si document.hidden es true — a
        // diferencia del poll del chat, esta es la situación exacta en la
        // que más sirve una notificación de escritorio: el asesor está en
        // otra pestaña o con el navegador minimizado.
        function revisar() {{
            if (Notification.permission !== 'granted') return;
            fetch('/dashboard/notificaciones.json')
                .then(function(r) {{ return r.json(); }})
                .then(function(datos) {{
                    const vistosLeads = leerSet(claveLeads);
                    const idsActuales = new Set();
                    datos.leads_nuevos.forEach(function(l) {{
                        idsActuales.add(l.telefono);
                        if (!vistosLeads.has(l.telefono)) {{
                            notificar('Nuevo lead asignado', l.nombre, l.telefono);
                        }}
                    }});
                    guardarSet(claveLeads, idsActuales);

                    const vistasCitas = leerSet(claveCitas);
                    const idsCitas = new Set();
                    datos.agendados_proximos.forEach(function(a) {{
                        const clave = a.telefono + '|' + a.fecha_agendada;
                        idsCitas.add(clave);
                        if (!vistasCitas.has(clave)) {{
                            notificar('Cita próxima con ' + a.nombre, 'A las ' + a.hora, a.telefono);
                        }}
                    }});
                    guardarSet(claveCitas, idsCitas);
                }})
                .catch(function() {{}});
        }}
        revisar();
        setInterval(revisar, 30000);
    }})();
    </script>
    """


def _script_tiempo_real(usuario: dict | None) -> str:
    """Conexión WebSocket única y persistente para toda la sesión del panel
    — vive en el shell base (fuera de #contenido-app, igual que el script de
    navegación AJAX y _script_notificaciones), así que NO se recrea en cada
    navegación interna: se abre una vez al cargar la página y se reconecta
    sola (con backoff) si se corta.

    Expone window.__gasoWS = {{on, off, verLead, escribiendo}} para que
    scripts de una pantalla puntual (ej. _script_chat_en_vivo, que sí se
    re-ejecuta en cada navegación AJAX) puedan suscribirse a eventos sin
    manejar su propia conexión."""
    if not usuario:
        return ""
    return """
    <script>
    (function() {
        if (!window.WebSocket) return;  // navegador muy viejo: sin tiempo real, el panel sigue funcionando igual

        const listeners = [];
        let socket = null;
        let intentos = 0;
        let telefonoActivo = null;
        let colaEnviar = [];

        function enviar(msg) {
            if (socket && socket.readyState === WebSocket.OPEN) {
                socket.send(JSON.stringify(msg));
            } else {
                colaEnviar.push(msg);
            }
        }

        function conectar() {
            const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
            socket = new WebSocket(proto + '//' + location.host + '/dashboard/ws');
            socket.addEventListener('open', function() {
                intentos = 0;
                if (telefonoActivo !== null) enviar({tipo: 'ver_lead', telefono: telefonoActivo});
                const pendientes = colaEnviar;
                colaEnviar = [];
                pendientes.forEach(enviar);
            });
            socket.addEventListener('message', function(ev) {
                let evento;
                try { evento = JSON.parse(ev.data); } catch (e) { return; }
                listeners.forEach(function(fn) {
                    try { fn(evento); } catch (e) {}
                });
            });
            socket.addEventListener('close', function() {
                intentos++;
                const espera = Math.min(1000 * Math.pow(1.5, intentos), 15000);
                setTimeout(conectar, espera);
            });
            socket.addEventListener('error', function() { socket.close(); });
        }

        window.__gasoWS = {
            on: function(fn) { listeners.push(fn); },
            off: function(fn) {
                const i = listeners.indexOf(fn);
                if (i >= 0) listeners.splice(i, 1);
            },
            verLead: function(telefono) { telefonoActivo = telefono; enviar({tipo: 'ver_lead', telefono: telefono}); },
            escribiendo: function(telefono) { enviar({tipo: 'escribiendo', telefono: telefono}); },
        };

        // Un mensaje nuevo en un lead que NO es el que está abierto ahora
        // mismo: refresca la lista/tabla (contadores, vista previa) en vez
        // de dejarla desactualizada hasta el próximo clic. Reusa la
        // navegación AJAX que ya existe (misma URL) — con un pequeño
        // debounce para no repintar de más si llegan varios mensajes
        // seguidos de golpe.
        let temporizadorLista = null;
        window.__gasoWS.on(function(evento) {
            if (evento.tipo !== 'mensaje_nuevo') return;
            // Si hay un chat abierto (telefonoActivo != null), NO refrescar
            // la página aunque el mensaje sea de otro lead — la URL actual
            // ES ese chat, así que un refresco "silencioso" terminaría
            // re-renderizando el chat abierto entero (vuelve a ejecutar su
            // script vía ejecutarScripts) cada vez que CUALQUIER otro lead
            // recibe un mensaje. Eso acumula listeners/intervalos viejos que
            // tardan hasta 20s en limpiarse solos y hacía que el panel se
            // sintiera cada vez más lento. Solo tiene sentido refrescar la
            // lista sola cuando se está mirando la tabla/lista, no un chat.
            if (telefonoActivo !== null) return;
            if (typeof window.__navegarAjax !== 'function') return;
            clearTimeout(temporizadorLista);
            temporizadorLista = setTimeout(function() {
                window.__navegarAjax(window.location.href, false, true);
            }, 1200);
        });

        conectar();
    })();
    </script>
    """


# Destinos de navegación de nivel 1 (MAIEK_AI_PRODUCT_ARCHITECTURE.md §10),
# en su mismo orden. "Conversaciones" y "CRM / Pipeline" comparten la misma
# ruta /dashboard con Inicio/Bandeja hoy (Inicio se llega sin query string) —
# se separan explícitamente en data-ruta para que actualizarNavActiva() los
# distinga (ver _pagina) hasta la futura migración a /dashboard/conversations.
_NAV_LATERAL_ITEMS = [
    ("inicio", "Inicio", "bi-house-door-fill", "/dashboard", "/dashboard", None),
    ("conversaciones", "Conversaciones", "bi-chat-dots-fill", "/dashboard?estado=todos", "/dashboard?estado=todos", None),
    ("pipeline", "CRM / Pipeline", "bi-briefcase-fill", "/dashboard/pipeline", "/dashboard/pipeline", None),
    ("campanas", "Campañas", "bi-megaphone-fill", "/dashboard/campanas", "/dashboard/campanas", ("admin", "supervisor")),
    ("catalogos", "Catálogo", "bi-folder-fill", "/dashboard/catalogos", "/dashboard/catalogos", None),
    ("equipo", "Equipo", "bi-people-fill", "/dashboard/asesores", "/dashboard/asesores", ROLES_CON_VISION_TOTAL),
    ("analitica", "Analítica", "bi-graph-up-arrow", "/dashboard/metricas", "/dashboard/metricas", ("admin", "supervisor", "asesor")),
    ("canales", "Canales de WhatsApp", "bi-whatsapp", "/dashboard/canales-whatsapp", "/dashboard/canales-whatsapp", ("admin",)),
]


def _nav_lateral(usuario: dict) -> str:
    """Sidebar de navegación (MAIEK_AI_PRODUCT_PATTERNS.md, Cap. 1 — Shell de
    Navegación) — implementación incremental: lista vertical con los destinos
    de MPA §10, filtrados por rol con el mismo criterio de permisos que ya
    usan las rutas (no se agregan accesos nuevos). Sin la variante colapsable
    280px/64px ni el buscador global de la versión completa del capítulo —
    se agregan cuando el próximo módulo lo justifique, no por anticipación."""
    items = []
    for _, etiqueta, icono, href, data_ruta, roles in _NAV_LATERAL_ITEMS:
        if roles and usuario["rol"] not in roles:
            continue
        items.append(
            f'<a href="{href}" data-ajax="1" data-ruta="{data_ruta}" class="nav-lateral-link">'
            f'<i class="bi {icono}"></i><span>{html.escape(etiqueta)}</span></a>'
        )
    # Toggle expandido/colapsado (Cap. 1, sección 5) — solo desktop, el CSS
    # de mobile ya oculta/expande el Sidebar completo por su cuenta y no
    # depende de este botón para nada.
    toggle = (
        '<button type="button" class="nav-lateral-toggle" id="nav-lateral-toggle" '
        'title="Contraer o expandir el menú">'
        '<i class="bi bi-arrow-bar-left"></i><span>Contraer</span></button>'
    )
    return f'<div class="nav-lateral" id="nav-lateral">{"".join(items)}{toggle}</div>'


def _pagina(
    titulo: str,
    usuario: dict | None,
    cuerpo: str,
    es_chat: bool = False,
    request: Request | None = None,
) -> HTMLResponse:
    """Envoltura HTML base — incluye Bootstrap y, si hay sesión, la barra superior.
    es_chat=True marca la página de chat abierto, para que en mobile se muestre
    a pantalla completa (ocultando rail/lista) en vez de las 3 columnas.

    Si la petición trae el header X-Panel-Fragment (navegación AJAX sin recarga
    de página), se devuelve solo el fragmento (`cuerpo`) con el título y el modo
    chat como headers de respuesta, en vez de la página completa — así cualquier
    ruta puede volverse navegable por AJAX con solo pasar `request`."""
    if request is not None and request.headers.get("x-panel-fragment"):
        headers = {"X-Page-Title": titulo}
        if es_chat:
            headers["X-Page-Chat"] = "1"
        return HTMLResponse(cuerpo, headers=headers)

    topbar = ""
    nav_lateral = ""
    if usuario:
        nav_lateral = _nav_lateral(usuario)
        disp_html = ""
        if usuario["rol"] == "asesor":
            en_linea = usuario.get("disponible", True)
            disp_html = (
                '<form method="post" action="/dashboard/disponibilidad" class="d-inline m-0">'
                f'{_csrf_campo(request)}'
                f'<button type="submit" class="link-btn badge '
                f'{"text-bg-success" if en_linea else "text-bg-secondary"}">'
                f'{"🟢 Disponible" if en_linea else "⚪ No disponible"}</button></form>'
            )
        topbar = f"""
        <nav class="navbar navbar-gaso navbar-dark px-3 py-2">
            <div class="d-flex align-items-center gap-2">
                <button type="button" class="btn btn-sm btn-outline-light rounded-circle btn-menu-movil" onclick="var m=document.getElementById(&#39;nav-lateral&#39;); if (m) m.classList.toggle(&#39;abierto&#39;)" aria-label="Menú de navegación"><i class="bi bi-list"></i></button>
                <a class="navbar-brand mb-0 d-flex align-items-center gap-2" href="/dashboard" data-ajax="1">
                    <i class="bi bi-droplet-fill" style="color:var(--gaso-secundario)"></i>
                    <span class="d-flex flex-column lh-1">
                        <span>Gaso<span class="plus">+</span></span>
                        <span class="fw-normal opacity-75 brand-subtitulo" style="font-size:.62rem;letter-spacing:.02em">Commercial Operating System <span class="opacity-50">&middot; Powered by Maiek <span style="font-weight:300">AI</span></span></span>
                    </span>
                </a>
            </div>
            <div class="d-flex align-items-center gap-3 text-white-50 small">
                <a href="/dashboard/perfil" data-ajax="1" class="text-white d-flex align-items-center gap-2 text-decoration-none">
                    {_avatar(usuario['nombre'], 30, 'avatar-sm')}
                    {html.escape(usuario['nombre'])} &middot; {html.escape(usuario['rol'])}
                </a>
                {disp_html}
                <form method="post" action="/dashboard/logout" class="d-inline m-0">
                    {_csrf_campo(request)}
                    <button type="submit" class="btn btn-sm btn-outline-light rounded-pill"><i class="bi bi-box-arrow-right"></i> Salir</button>
                </form>
            </div>
        </nav>"""
    # Precalculado fuera del f-string de abajo: Python 3.11 (la versión del
    # Dockerfile de producción) no permite backslashes dentro de una
    # expresión {} de un f-string — a diferencia de versiones más nuevas de
    # Python, donde este mismo código compila sin avisar nada.
    boton_filtros_movil = (
        '<button type="button" class="btn btn-primary rounded-circle btn-filtros-movil shadow" '
        'style="position:fixed;bottom:20px;left:16px;width:50px;height:50px;z-index:1400" '
        "onclick=\"document.getElementById('rail-estados') && document.getElementById('rail-estados').classList.add('abierto')\">"
        '<i class="bi bi-funnel-fill"></i></button>'
        if usuario and not es_chat else ''
    )
    csrf_token = request.session.get("csrf_token", "") if (request is not None and usuario) else ""
    meta_csrf = f'<meta name="csrf-token" content="{html.escape(csrf_token)}">' if csrf_token else ""
    return f"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
{meta_csrf}
<title>{html.escape(titulo)} — Gaso+ Panel</title>
{BOOTSTRAP_CSS}
{BOOTSTRAP_ICONS}
{FUENTE_INTER}
<style>{ESTILOS_PROPIOS}</style>
</head>
<body class="{'pagina-chat' if es_chat else ''}">
{_script_tiempo_real(usuario)}
<div id="barra-carga"></div>
{topbar}
<div class="app-shell">
{nav_lateral}
{boton_filtros_movil}
<div id="contenido-app">{cuerpo}</div>
</div>
{BOOTSTRAP_JS}
<script>
    // Token CSRF de la sesión — leído una sola vez del <meta> de esta misma
    // carga de página (el shell/head no se vuelve a renderizar en las
    // navegaciones data-ajax, así que este valor sigue siendo válido para
    // cualquier fetch() posterior mientras dure la sesión). Los 6 POST por
    // fetch del panel lo usan como header X-CSRF-Token en vez de duplicar
    // este querySelector en cada uno.
    window.__csrfToken = function() {{
        var meta = document.querySelector('meta[name="csrf-token"]');
        return meta ? meta.content : '';
    }};
</script>
<script>
(function() {{
    // Barra de carga fina arriba de la página: como no hay framework de JS,
    // cada clic navega recargando la página entera — esto da una señal
    // inmediata de que el clic sí se registró, en vez de dejar la pantalla
    // sin respuesta hasta que la página nueva termine de cargar.
    var barra = document.getElementById('barra-carga');
    function iniciar() {{
        barra.classList.add('activa');
        barra.style.width = '75%';
    }}
    function terminar() {{
        barra.classList.remove('activa');
        barra.style.width = '0%';
    }}

    // Navegación dinámica (sin recargar toda la página) — cualquier link
    // marcado con data-ajax="1" navega por fetch en vez de recarga completa
    // (tabla de leads, rail de estados/equipo, barra superior, chat). Las
    // rutas de login/logout y la descarga de CSV se dejan fuera a propósito.
    var contenedor = document.getElementById('contenido-app');

    function ejecutarScripts(raiz) {{
        raiz.querySelectorAll('script').forEach(function(viejo) {{
            var nuevo = document.createElement('script');
            for (var i = 0; i < viejo.attributes.length; i++) {{
                nuevo.setAttribute(viejo.attributes[i].name, viejo.attributes[i].value);
            }}
            nuevo.textContent = viejo.textContent;
            viejo.replaceWith(nuevo);
        }});
    }}

    // Marca cuál link de la barra superior corresponde a la pantalla actual
    // — la barra es parte del shell fijo (no se vuelve a renderizar en cada
    // navegación AJAX interna), así que el estado "activo" se calcula acá en
    // vez de en el servidor. Se llama al cargar la página y después de cada
    // navegación (normal o silenciosa).
    function actualizarNavActiva() {{
        var ruta = window.location.pathname;
        // Caso especial temporal: Inicio y Conversaciones comparten la misma
        // ruta /dashboard (se bifurcan por query string, ver panel_principal)
        // — hasta que exista /dashboard/conversations como ruta propia, acá
        // se decide cuál de las dos marcar activa según haya o no query string.
        var esInicio = ruta === '/dashboard' && !window.location.search;
        var esConversaciones = ruta === '/dashboard' && !!window.location.search;
        document.querySelectorAll('.nav-superior-link, .nav-lateral-link').forEach(function(link) {{
            var destino = link.getAttribute('data-ruta');
            var activo;
            if (destino === '/dashboard') activo = esInicio;
            else if (destino === '/dashboard?estado=todos') activo = esConversaciones;
            else activo = (destino === ruta);
            link.classList.toggle('activo', activo);
        }});
    }}
    actualizarNavActiva();

    // Sidebar colapsable a solo íconos (Product Patterns Cap. 1, sección 5:
    // "reposo — Sidebar en el estado que el usuario dejó en su sesión
    // anterior, persistido entre sesiones"). El Sidebar no se reconstruye
    // en cada navegación AJAX (ver comentario más arriba), así que esto
    // corre una sola vez por carga real de página, no por cada navegación.
    (function() {{
        var nav = document.getElementById('nav-lateral');
        var toggle = document.getElementById('nav-lateral-toggle');
        if (!nav || !toggle) return;
        var CLAVE = 'gaso_nav_colapsado';
        function aplicar(colapsado) {{
            nav.classList.toggle('colapsado', colapsado);
            toggle.querySelector('i').className = 'bi ' + (colapsado ? 'bi-arrow-bar-right' : 'bi-arrow-bar-left');
            toggle.querySelector('span').textContent = colapsado ? 'Expandir' : 'Contraer';
        }}
        aplicar(localStorage.getItem(CLAVE) === '1');
        toggle.addEventListener('click', function() {{
            var colapsado = !nav.classList.contains('colapsado');
            localStorage.setItem(CLAVE, colapsado ? '1' : '0');
            aplicar(colapsado);
        }});
    }})();

    function navegarAjax(url, agregarHistorial, silencioso) {{
        if (!silencioso) iniciar();
        fetch(url, {{ headers: {{ 'X-Panel-Fragment': '1' }} }})
            .then(function(r) {{
                if (!r.ok) throw new Error('HTTP ' + r.status);
                var titulo = r.headers.get('X-Page-Title');
                var esChat = r.headers.get('X-Page-Chat') === '1';
                return r.text().then(function(html) {{ return {{ html: html, titulo: titulo, esChat: esChat }}; }});
            }})
            .then(function(datos) {{
                // Si el contenido que se va a reemplazar tenía un chat con
                // su propia conexión WS activa, límpialo YA (deja de
                // escuchar eventos, avisa al servidor que ya no lo mira) —
                // si no, el listener queda vivo hasta que su propio
                // intervalo de respaldo lo note (hasta 20s después).
                if (window.__gasoChatLimpiar) window.__gasoChatLimpiar();
                contenedor.innerHTML = datos.html;
                ejecutarScripts(contenedor);
                if (datos.titulo) document.title = datos.titulo + ' — Gaso+ Panel';
                document.body.classList.toggle('pagina-chat', datos.esChat);
                if (agregarHistorial) history.pushState({{ ajax: true }}, '', url);
                actualizarNavActiva();
                if (!silencioso) {{ window.scrollTo(0, 0); terminar(); }}
            }})
            .catch(function() {{
                // Si algo falla (red, error del servidor): en un refresco
                // silencioso simplemente no pasa nada (se reintenta con el
                // próximo evento); en una navegación normal, no deja
                // colgado — navega normal como si nunca hubiera intentado ir por AJAX.
                if (!silencioso) window.location.href = url;
            }});
    }}
    // Expuesto para que _script_tiempo_real (fuera de esta IIFE) pueda
    // disparar un refresco silencioso de la lista/tabla cuando llega un
    // mensaje de un lead que no es el que está abierto ahora mismo.
    window.__navegarAjax = navegarAjax;

    document.addEventListener('click', function(ev) {{
        var link = ev.target.closest('a[href]');
        if (!link) return;
        var href = link.getAttribute('href') || '';
        if (link.target === '_blank' || href.startsWith('#') || href.startsWith('javascript:')) return;
        if (ev.metaKey || ev.ctrlKey || ev.shiftKey) return;

        if (link.hasAttribute('data-ajax')) {{
            ev.preventDefault();
            navegarAjax(link.href, true);
            return;
        }}
        iniciar();
    }});

    window.addEventListener('popstate', function() {{
        navegarAjax(window.location.href, false);
    }});

    document.addEventListener('submit', function(ev) {{
        // form-respuesta se envía por fetch (sin recargar la página) — no aplica acá.
        if (ev.target.tagName === 'FORM' && ev.target.id !== 'form-respuesta') iniciar();
    }});
    window.addEventListener('pageshow', terminar);
}})();
</script>
{_script_notificaciones(usuario)}
</body>
</html>"""


def _item_nav_estado(etiqueta: str, icono: str, cantidad: int, estado_valor: str, activo: bool) -> str:
    clase = " activo" if activo else ""
    return (
        f'<a href="/dashboard?estado={estado_valor}" data-ajax="1" class="{clase}" title="{html.escape(etiqueta)}">'
        f'<span class="rail-label"><i class="bi {icono} me-2"></i>{html.escape(etiqueta)}</span>'
        f'<span class="badge-count">{cantidad}</span></a>'
    )


def _item_equipo(nombre: str, username: str, cantidad: int, activo: bool) -> str:
    clase = " activo" if activo else ""
    return (
        f'<a href="/dashboard?asesor={html.escape(username)}" data-ajax="1" class="equipo-item{clase}" title="{html.escape(nombre)}">'
        f'<span class="d-flex align-items-center gap-2">{_avatar(nombre, 24)}<span class="rail-label">{html.escape(nombre)}</span></span>'
        f'<span class="badge-count">{cantidad}</span></a>'
    )


def _item_canal(nombre: str, phone_number_id: str, color: tuple, activo: bool) -> str:
    clase = " activo" if activo else ""
    _, texto = color
    href = "/dashboard" if activo else f"/dashboard?canal={html.escape(phone_number_id)}"
    icono_quitar = '<i class="bi bi-x-circle"></i>' if activo else ""
    return (
        f'<a href="{href}" data-ajax="1" class="equipo-item{clase}" title="{html.escape(nombre)}">'
        f'<span class="d-flex align-items-center gap-2">'
        f'<span style="width:10px;height:10px;border-radius:50%;background-color:{texto};display:inline-block;flex-shrink:0"></span>'
        f'<span class="rail-label">{html.escape(nombre)}</span></span>'
        f'{icono_quitar}</a>'
    )


async def _datos_bandeja(usuario: dict, estado_filtro: str, asesor_filtro: str, canal_filtro: str = "") -> dict:
    """Consulta y filtra los leads una sola vez, para que el rail de estados
    y la lista de conversaciones (columnas separadas) no dupliquen queries."""
    vision_total = usuario["rol"] in ROLES_CON_VISION_TOTAL
    leads_todos = await listar_leads(
        usuario["negocio_id"], asesor_asignado=None if vision_total else usuario["username"]
    )
    mapa_canales = await _mapa_canales(usuario["negocio_id"])
    if canal_filtro:
        leads_todos = [l for l in leads_todos if l.get("numero_whatsapp_id") == canal_filtro]

    # La bandeja de conversaciones es para lo que un humano necesita mirar:
    # solo leads que ya se derivaron a un asesor (con sus 4 sub-estados) por
    # defecto. Lo que Gabi todavía atiende sola (explorando/comparando/
    # evaluando) queda en un filtro aparte, "con_gabi" — admin/supervisor
    # pueden entrar ahí a mirar cualquier conversación en vivo aunque nadie
    # la haya derivado todavía (antes solo se veía el conteo, sin poder
    # abrir ninguna). Un asesor normal nunca ve nada acá de todos modos,
    # porque listar_leads ya solo le trae SUS leads asignados (línea de
    # arriba), y un lead que Gabi sigue atendiendo sola no tiene asesor.
    leads_derivados = [l for l in leads_todos if _estado_conversacion(l) in ESTADOS_DERIVADO]
    leads_con_gabi = [l for l in leads_todos if _estado_conversacion(l) in ESTADOS_GABI]

    conteos = {estado: 0 for estado in ESTADOS_DERIVADO}
    for lead in leads_derivados:
        conteos[_estado_conversacion(lead)] += 1

    # Mismo patrón que conteos, pero para los 3 sub-estados de "Con Gabi"
    # (Explorando/Comparando producto/Evaluando financiamiento) — permite un
    # drill-down igual de granular al que ya existe para Conversaciones.
    conteos_gabi = {estado: 0 for estado in ESTADOS_GABI}
    for lead in leads_con_gabi:
        conteos_gabi[_estado_conversacion(lead)] += 1

    if estado_filtro == "con_gabi":
        leads_filtrados = leads_con_gabi
    elif estado_filtro in ESTADOS_GABI:
        leads_filtrados = [l for l in leads_con_gabi if _estado_conversacion(l) == estado_filtro]
    else:
        leads = leads_derivados
        if vision_total and asesor_filtro:
            leads = [l for l in leads if l.get("asesor_asignado") == asesor_filtro]
        leads_filtrados = leads if estado_filtro == "todos" else [l for l in leads if _estado_conversacion(l) == estado_filtro]

    return {
        "vision_total": vision_total,
        "leads_todos": leads_todos,
        "leads_derivados": leads_derivados,
        "leads_con_gabi": leads_con_gabi,
        "leads_filtrados": leads_filtrados,
        "conteos": conteos,
        "conteos_gabi": conteos_gabi,
        "mapa_canales": mapa_canales,
        "canal_filtro": canal_filtro,
    }


def _mini_embudo_unificado(datos: dict, estado_filtro: str) -> str:
    """Embudo completo (7 etapas, "con Gabi" + "conversaciones") como fila
    de chips clicables — vive en la barra superior (_barra_resumen), no en
    el rail: mostrarlo en los dos lados a la vez era el mismo dato con el
    mismo link tres veces en una sola pantalla (los chips + las dos
    secciones separadas del rail), justo lo que esto buscaba resolver."""
    conteos_gabi = datos["conteos_gabi"]
    conteos = datos["conteos"]
    chips = []
    for estado in ESTADOS_GABI + ESTADOS_DERIVADO:
        cantidad = conteos_gabi[estado] if estado in conteos_gabi else conteos[estado]
        icono, _ = ICONO_ESTADO[estado]
        bg, texto = COLOR_ESTADO_SUAVE[estado]
        activo = " activo" if estado_filtro == estado else ""
        etiqueta = ETIQUETAS_ESTADO[estado]
        chips.append(
            f'<a href="/dashboard?estado={estado}" data-ajax="1" class="chip-embudo{activo}" '
            f'style="background-color:{bg};color:{texto}" title="{html.escape(etiqueta)}: {cantidad}">'
            f'<i class="bi {icono}"></i><span>{cantidad}</span></a>'
        )
        if estado == ESTADOS_GABI[-1]:
            chips.append('<span class="separador-embudo">&rarr;</span>')
    return f'<div class="mini-embudo">{"".join(chips)}</div>'


def _item_agendados(cantidad: int) -> str:
    """Atajo fijo arriba del rail hacia las próximas citas — no es un
    filtro de estado más (paso_flujo puede ser cualquiera; "agendado" es
    un cruce ortogonal vía resultado), así que no encaja en la lista de 7
    estados de abajo. Enlaza a /dashboard, donde ya vive la tarjeta
    "Próximas citas" (_aviso_proximas_citas), en vez de duplicar esa
    lógica de filtrado en el rail."""
    return (
        '<div class="estado-nav pt-2 pb-1">'
        '<a href="/dashboard" data-ajax="1" title="Próximas citas agendadas">'
        '<span class="rail-label"><i class="bi bi-calendar-event me-2"></i>Agendados</span>'
        f'<span class="badge-count">{cantidad}</span></a>'
        '</div>'
    )


async def _renderizar_rail_estados(usuario: dict, datos: dict, estado_filtro: str, asesor_filtro: str, canal_filtro: str = "") -> str:
    vision_total = datos["vision_total"]
    conteos = datos["conteos"]
    conteos_gabi = datos["conteos_gabi"]

    # Una sola lista con las 7 etapas en orden de embudo (antes: dos
    # secciones separadas, "CON GABI" y "CONVERSACIONES", con vocabularios
    # sin conexión visual entre sí — el mismo lead avanzando por un único
    # proceso se leía como dos procesos distintos). Para un asesor normal
    # los 3 estados "con Gabi" siempre dan 0 (listar_leads ya le trae solo
    # SUS leads asignados, y un lead que Gabi todavía atiende sola no tiene
    # asesor), así que solo ve los 4 derivados — mismo resultado que antes.
    estados_a_mostrar = (ESTADOS_GABI + ESTADOS_DERIVADO) if vision_total else ESTADOS_DERIVADO
    nav_estados = "".join(
        _item_nav_estado(
            ETIQUETAS_ESTADO[e], ICONO_ESTADO[e][0],
            conteos_gabi[e] if e in conteos_gabi else conteos[e],
            e, estado_filtro == e and not asesor_filtro,
        )
        for e in estados_a_mostrar
    )
    # Todo lead cae en exactamente uno de los 7 estados (ver
    # _estado_conversacion), así que leads_todos ya es el total combinado —
    # no hace falta sumar leads_derivados + leads_con_gabi a mano.
    item_todos = _item_nav_estado(
        "Todos", "bi-collection-fill", len(datos["leads_todos"]), "todos", estado_filtro == "todos" and not asesor_filtro
    )

    equipo_html = ""
    if vision_total:
        asesores = await listar_asesores(usuario["negocio_id"])
        filas_equipo = []
        if estado_filtro == "todos":
            # Sin filtro de estado: se muestra la carga activa total de cada
            # asesor — una sola consulta para todo el equipo, no una por
            # asesor (ver contar_leads_activos_por_asesor).
            conteos_carga = await contar_conversations_activas_por_asesor(usuario["negocio_id"], [a["username"] for a in asesores])
            for a in asesores:
                carga = conteos_carga.get(a["username"], 0)
                filas_equipo.append(_item_equipo(a["nombre"], a["username"], carga, asesor_filtro == a["username"]))
        else:
            # Con un estado filtrado (ej. "En atención"): solo se listan los
            # asesores que tienen al menos un lead en ESE estado específico,
            # con el conteo de ese estado — no su carga general.
            conteo_por_asesor = {}
            for lead in datos["leads_derivados"]:
                if _estado_conversacion(lead) == estado_filtro and lead.get("asesor_asignado"):
                    conteo_por_asesor[lead["asesor_asignado"]] = conteo_por_asesor.get(lead["asesor_asignado"], 0) + 1
            for a in asesores:
                cantidad = conteo_por_asesor.get(a["username"], 0)
                if cantidad > 0:
                    filas_equipo.append(_item_equipo(a["nombre"], a["username"], cantidad, asesor_filtro == a["username"]))
        equipo_html = f"""
        {_subtitulo_contraible("EQUIPO", "equipo-contenido")}
        <div id="equipo-contenido">
            {''.join(filas_equipo) or '<p class="px-3 text-muted small">Ningún asesor tiene leads en este estado.</p>'}
        </div>
        """

    # Solo se muestra si hay más de un canal configurado — con uno solo, un
    # filtro por canal no distingue nada y solo agregaría ruido visual. Va
    # primero en el rail (antes de "Conversaciones") porque es el filtro más
    # amplio — qué número — antes de refinar por estado o asesor.
    mapa_canales = datos.get("mapa_canales") or {}
    canales_html = ""
    if len(mapa_canales) > 1:
        filas_canal = [
            _item_canal(info["nombre"], numero, info["color"], canal_filtro == numero)
            for numero, info in mapa_canales.items()
        ]
        canales_html = f"""
        {_subtitulo_contraible("CANALES", "canales-contenido")}
        <div id="canales-contenido">
            {''.join(filas_canal)}
        </div>
        """

    # Atajo a "Próximas citas" arriba de todo lo demás en el rail — es lo
    # más sensible al tiempo (hay una cita con el cliente), así que va antes
    # que cualquier filtro de estado o canal.
    agendados_cantidad = sum(1 for l in datos["leads_todos"] if l.get("resultado") == "agendado")
    agendados_html = _item_agendados(agendados_cantidad)

    return f"""
    <div class="rail-estados border-end d-flex flex-column" id="rail-estados">
        <div class="sidebar-subtitulo d-flex justify-content-between align-items-center pe-2 d-md-none">
            <span>&nbsp;</span>
            <button type="button" class="btn-close" style="font-size:.65rem" onclick="document.getElementById('rail-estados').classList.remove('abierto')"></button>
        </div>
        {agendados_html}
        {canales_html}
        {_subtitulo_contraible("CONVERSACIONES", "conversaciones-contenido")}
        <div id="conversaciones-contenido">
            <div class="estado-nav pb-2">
                {item_todos}
                {nav_estados}
            </div>
        </div>
        {equipo_html}
    </div>
    """


def _subtitulo_contraible(etiqueta: str, id_contenido: str) -> str:
    """Título de sección del rail lateral que se puede contraer/expandir con
    un clic — el contenido (id_contenido) alterna entre visible y oculto por
    estilo inline en JS (no una clase de Bootstrap, para no repetir el bug
    de d-flex + !important peleando con display:none de nuevo)."""
    return f"""
    <div class="sidebar-subtitulo d-flex justify-content-between align-items-center pe-2" style="cursor:pointer"
        onclick="var el = document.getElementById('{id_contenido}');
                 var colapsando = el.style.display !== 'none';
                 el.style.display = colapsando ? 'none' : '';
                 var ic = this.querySelector('.chevron-contraible');
                 ic.classList.toggle('bi-chevron-down', !colapsando);
                 ic.classList.toggle('bi-chevron-right', colapsando);">
        <span>{etiqueta}</span>
        <i class="bi bi-chevron-down chevron-contraible" style="font-size:.65rem"></i>
    </div>
    """


async def _renderizar_lista_conversaciones(
    usuario: dict, datos: dict, telefono_activo: str | None, asesor_filtro: str = "",
) -> str:
    vision_total = datos["vision_total"]
    leads_filtrados = datos["leads_filtrados"]

    # Si se llegó filtrando por un asesor del equipo, ese filtro se propaga en
    # el link de cada conversación — así, al abrir un lead, la vista sabe que
    # viene de esa lista y la mantiene visible junto al resumen y el chat.
    query = f"?asesor={html.escape(asesor_filtro)}" if asesor_filtro else ""
    mapa_canales = datos.get("mapa_canales") or {}

    # Una sola consulta para el último mensaje de TODOS los leads visibles,
    # no una por lead (ver obtener_ultimos_mensajes) — con Postgres en
    # producción, N consultas secuenciales se sienten en cada carga de página.
    ultimos_mensajes = await servicio_conversacion.obtener_ultimos_mensajes(
        [l["telefono"] for l in leads_filtrados], usuario["negocio_id"]
    )

    items = []
    for lead in leads_filtrados:
        ultimo = ultimos_mensajes.get(lead["telefono"])
        preview = (ultimo["content"][:60] + "…") if ultimo and len(ultimo["content"]) > 60 else (ultimo["content"] if ultimo else "")
        hora = lead["actualizado"].strftime("%d/%m %H:%M")
        activo = " activo" if lead["telefono"] == telefono_activo else ""
        es_nuevo = (not vision_total) and not lead.get("visto_asesor", True)
        badge_nuevo = ' <span class="badge text-bg-warning">Nuevo</span>' if es_nuevo else ""
        badge_revision = (
            ' <span class="badge text-bg-info" title="La IA respondió, pero un asesor debería revisar esta conversación">Revisión prioritaria</span>'
            if lead.get("revision_prioritaria") else ""
        )
        badge_canal = _badge_canal(lead.get("numero_whatsapp_id"), mapa_canales, compacto=True)
        nombre_lead = lead.get("nombre") or lead["telefono"]
        items.append(f"""
        <a class="list-group-item list-group-item-action convo-item d-flex gap-2 py-1{activo}" href="/dashboard/lead/{html.escape(lead['telefono'])}{query}" data-ajax="1">
            {_avatar(nombre_lead, 30)}
            <div class="flex-grow-1 overflow-hidden">
                <div class="d-flex justify-content-between align-items-center">
                    <span class="fw-semibold" style="font-size:13.5px">{html.escape(nombre_lead)}{badge_nuevo}{badge_revision}</span>
                    <small class="text-muted" style="font-size:10.5px">{hora}</small>
                </div>
                <div class="convo-preview text-muted">{html.escape(preview)}</div>
                {badge_canal}
            </div>
        </a>
        """)

    return f"""
    <div class="sidebar bg-white border-end d-flex flex-column">
        <div class="sidebar-subtitulo"><i class="bi bi-chat-dots"></i> CONVERSACIONES ({len(leads_filtrados)})</div>
        <div class="list-group list-group-flush">
            {''.join(items) or '<p class="px-3 text-muted small">No hay conversaciones en este estado.</p>'}
        </div>
    </div>
    """


async def _renderizar_sidebar(usuario: dict, telefono_activo: str | None, estado_filtro: str = "todos", asesor_filtro: str = "") -> str:
    """Solo el rail de estados (sin la lista de conversaciones) — para
    páginas secundarias (Métricas, Asesores, Campañas, Mi perfil), que no
    necesitan mostrar la bandeja de chats, solo la navegación."""
    datos = await _datos_bandeja(usuario, estado_filtro, asesor_filtro)
    return await _renderizar_rail_estados(usuario, datos, estado_filtro, asesor_filtro)


def _badge_estado_conversacion(lead: dict) -> str:
    estado = _estado_conversacion(lead)
    color = ICONO_ESTADO.get(estado, ("bi-circle", "#94a3b8"))[1]
    return f'<span class="badge text-white fw-normal" style="background-color:{color}">{html.escape(ETIQUETAS_ESTADO.get(estado, estado))}</span>'


def _badge_estado_suave(lead: dict) -> str:
    """Versión pastel del badge de estado — fondo suave + texto de color,
    look ejecutivo en vez de badge sólido saturado tipo alerta."""
    estado = _estado_conversacion(lead)
    bg, texto = COLOR_ESTADO_SUAVE.get(estado, ("#f1f5f9", "#475569"))
    return (
        f'<span class="badge-suave" style="background-color:{bg};color:{texto}">'
        f'{html.escape(ETIQUETAS_ESTADO.get(estado, estado))}</span>'
    )


def _tiempo_relativo(momento: datetime) -> str:
    """Formatea una fecha como tiempo relativo ('Hace 5 min', 'Ayer') para
    que la tabla se lea más humana — con la fecha exacta siempre disponible
    en el atributo title al pasar el mouse."""
    diferencia = datetime.utcnow() - momento
    segundos = diferencia.total_seconds()
    if segundos < 60:
        return "Ahora"
    minutos = int(segundos // 60)
    if minutos < 60:
        return f"Hace {minutos} min"
    horas = int(minutos // 60)
    if horas < 24:
        return f"Hace {horas} h"
    dias = int(horas // 24)
    if dias == 1:
        return "Ayer"
    if dias < 7:
        return f"Hace {dias} d"
    return momento.strftime("%d/%m/%y")


def _tabla_todos_los_leads(leads: list[dict], mapa_canales: dict | None = None) -> str:
    """Tabla resumen de todos los leads con su estado, con búsqueda, orden
    por columna y paginación (todo client-side con JS liviano, sin
    framework) — se muestra en el panel de chat cuando aún no se seleccionó
    ninguna conversación, en vez de dejar ese espacio vacío."""
    mapa_canales = mapa_canales or {}
    mostrar_canal = len(mapa_canales) > 1
    filas = "".join(
        f"""<tr data-buscar="{html.escape((lead.get('nombre') or '') + ' ' + lead['telefono'] + ' ' + (lead.get('interes') or '') + ' ' + (lead.get('asesor_asignado') or '') + ' ' + (lead.get('campana_origen') or ''), quote=True).lower()}">
            <td class="ps-4">
                <a href="/dashboard/lead/{html.escape(lead['telefono'])}" class="d-flex align-items-center gap-2 text-decoration-none text-dark" data-ajax="1">
                    {_avatar(lead.get('nombre') or lead['telefono'], 26)}
                    <span class="text-truncate"><span class="fw-semibold">{html.escape(lead.get('nombre') or '(sin nombre)')}</span>
                    <span class="text-muted" style="font-size:.8rem"> &middot; {html.escape(lead['telefono'])}</span></span>
                </a>
            </td>
            <td class="text-muted"><span class="d-inline-block text-truncate align-bottom" style="max-width:180px" title="{html.escape(lead.get('interes') or '')}">{html.escape(lead.get('interes') or '-')}</span></td>
            <td>{_badge_estado_suave(lead)}</td>
            <td class="text-muted">{html.escape(lead.get('asesor_asignado') or 'Sin asignar')}</td>
            <td class="text-muted">{html.escape(lead.get('campana_origen') or '-')}</td>
            <td class="text-muted" data-ts="{lead['creado'].isoformat()}" title="{lead['creado'].strftime('%d/%m/%Y %H:%M')}">{lead['creado'].strftime('%d/%m/%Y')}</td>
            <td class="text-muted text-end pe-4" data-ts="{lead['actualizado'].isoformat()}" title="{lead['actualizado'].strftime('%d/%m/%Y %H:%M')}">{_tiempo_relativo(lead['actualizado'])}</td>
            {f'<td>{_badge_canal(lead.get("numero_whatsapp_id"), mapa_canales)}</td>' if mostrar_canal else ''}
        </tr>"""
        for lead in leads
    )
    columnas = ["Cliente", "Interés", "Estado", "Asesor", "Campaña", "Creado el", "Actividad"]
    if mostrar_canal:
        columnas.append("Canal")
    encabezados = "".join(
        f'<th class="{"ps-4" if i == 0 else ("text-end pe-4" if col == "Actividad" and not mostrar_canal else "")}" '
        f'style="cursor:pointer;user-select:none" data-col="{i}">{html.escape(col)} <i class="bi bi-arrow-down-up" style="font-size:.7em"></i></th>'
        for i, col in enumerate(columnas)
    )
    return f"""
    {_titulo_seccion('bi-list-ul', f'Todos los leads ({len(leads)})')}
    <div class="d-flex justify-content-between align-items-center mb-3 gap-2">
        <div class="input-group input-group-sm" style="max-width:320px">
            <span class="input-group-text bg-white border-end-0"><i class="bi bi-search text-muted"></i></span>
            <input type="text" id="buscar-leads" class="form-control border-start-0" placeholder="Buscar por nombre, teléfono, interés, asesor o campaña...">
        </div>
        <span class="text-muted small" id="leads-contador"></span>
    </div>
    <div class="card leads-card shadow-sm">
        <div class="barra-acento"></div>
        <div class="table-responsive">
            <table class="table align-middle mb-0 tabla-ejecutiva" id="tabla-leads">
                <thead>
                    <tr>{encabezados}</tr>
                </thead>
                <tbody>{filas or f'<tr><td colspan="{len(columnas)}" class="text-center text-muted py-5">Aún no hay leads.</td></tr>'}</tbody>
            </table>
        </div>
        <div class="d-flex justify-content-between align-items-center p-3 border-top small" id="leads-paginacion" style="display:none !important">
            <button type="button" class="btn btn-sm btn-outline-secondary" id="leads-prev">&laquo; Anterior</button>
            <span class="text-muted" id="leads-pag-info"></span>
            <button type="button" class="btn btn-sm btn-outline-secondary" id="leads-next">Siguiente &raquo;</button>
        </div>
    </div>
    {_script_tabla_dinamica("leads")}
    """


def _script_tabla_dinamica(prefijo: str) -> str:
    """Búsqueda, orden por columna y paginación client-side — genérico para
    cualquier tabla que use el markup de _tabla_ejecutiva (mismos ids con un
    prefijo distinto), para no duplicar esta lógica en cada tabla nueva."""
    return f"""
    <script>
    (function() {{
        var FILAS_POR_PAGINA = 15;
        var tabla = document.getElementById('tabla-{prefijo}');
        if (!tabla) return;
        var tbody = tabla.querySelector('tbody');
        var buscar = document.getElementById('buscar-{prefijo}');
        var contador = document.getElementById('{prefijo}-contador');
        var paginacionBox = document.getElementById('{prefijo}-paginacion');
        var pagInfo = document.getElementById('{prefijo}-pag-info');
        var btnPrev = document.getElementById('{prefijo}-prev');
        var btnNext = document.getElementById('{prefijo}-next');
        var paginaActual = 1;
        var ordenCol = null, ordenAsc = true;

        function filasBase() {{
            return Array.prototype.slice.call(tbody.querySelectorAll('tr[data-buscar]'));
        }}

        // Quita tildes/diéresis para que buscar "jesus" también encuentre
        // "Jesús" — sin esto, la búsqueda solo hacía match exacto de caracteres.
        function sinAcentos(texto) {{
            return (texto || '').normalize('NFD').replace(/[\\u0300-\\u036f]/g, '');
        }}

        function aplicar() {{
            var termino = sinAcentos((buscar.value || '').toLowerCase().trim());
            var todas = filasBase();
            var coinciden = todas.filter(function(f) {{
                return !termino || sinAcentos(f.getAttribute('data-buscar') || '').indexOf(termino) !== -1;
            }});
            todas.forEach(function(f) {{ f.style.display = 'none'; }});

            var totalPaginas = Math.max(1, Math.ceil(coinciden.length / FILAS_POR_PAGINA));
            if (paginaActual > totalPaginas) paginaActual = totalPaginas;
            var inicio = (paginaActual - 1) * FILAS_POR_PAGINA;
            coinciden.slice(inicio, inicio + FILAS_POR_PAGINA).forEach(function(f) {{ f.style.display = ''; }});

            contador.textContent = termino ? (coinciden.length + ' de ' + todas.length) : (todas.length + ' en total');
            if (coinciden.length > FILAS_POR_PAGINA) {{
                paginacionBox.style.setProperty('display', 'flex', 'important');
                pagInfo.textContent = 'Página ' + paginaActual + ' de ' + totalPaginas;
                btnPrev.disabled = paginaActual <= 1;
                btnNext.disabled = paginaActual >= totalPaginas;
            }} else {{
                paginacionBox.style.setProperty('display', 'none', 'important');
            }}
        }}

        buscar.addEventListener('input', function() {{ paginaActual = 1; aplicar(); }});
        btnPrev.addEventListener('click', function() {{ paginaActual--; aplicar(); }});
        btnNext.addEventListener('click', function() {{ paginaActual++; aplicar(); }});

        tabla.querySelectorAll('th[data-col]').forEach(function(th) {{
            th.addEventListener('click', function() {{
                var col = parseInt(th.getAttribute('data-col'), 10);
                ordenAsc = (ordenCol === col) ? !ordenAsc : true;
                ordenCol = col;
                var filas = filasBase();
                filas.sort(function(a, b) {{
                    var celdaA = a.children[col], celdaB = b.children[col];
                    var va = celdaA.getAttribute('data-ts') || celdaA.textContent.trim().toLowerCase();
                    var vb = celdaB.getAttribute('data-ts') || celdaB.textContent.trim().toLowerCase();
                    if (va < vb) return ordenAsc ? -1 : 1;
                    if (va > vb) return ordenAsc ? 1 : -1;
                    return 0;
                }});
                filas.forEach(function(f) {{ tbody.appendChild(f); }});
                paginaActual = 1;
                aplicar();
            }});
        }});

        aplicar();
    }})();
    </script>
    """


def _barra_resumen(datos: dict, asesores: list[dict], estado_filtro: str) -> str:
    """Franja fija y delgada debajo del navbar — el embudo completo (7
    chips clicables, ver _mini_embudo_unificado) más la disponibilidad del
    equipo. Antes tenía los mismos 5 conteos como texto plano, que además
    se repetían tal cual en el rail izquierdo (ver auditoría UX: el mismo
    dato con el mismo link, tres veces en una sola pantalla) — "Agendados"
    se movió al rail (_item_agendados, arriba de todo) porque es un atajo
    de navegación, no un KPI de resumen."""
    disponibles = sum(1 for a in asesores if a.get("disponible"))
    embudo = _mini_embudo_unificado(datos, estado_filtro)
    disponibilidad = f'<span>Asesores disponibles: <strong>{disponibles}/{len(asesores)}</strong></span>'
    return f'<div class="barra-resumen">{embudo}{disponibilidad}</div>'


# ── Login / Logout ────────────────────────────────────────────────────

@router.get("/login")
async def login_form():
    """Ya no hay pantalla de login en el servidor (2026-11-11): el formulario vive en el panel nuevo (`/login`). Esta ruta solo manda
    allá a quien entre por un favorito o un enlace viejo. El proceso de validar la clave sigue siendo `POST /login` (más abajo): el
    intermediario del panel nuevo (`app/api/login`) lo llama y reenvía la cookie de sesión."""
    return RedirectResponse(url=f"{url_panel_nuevo()}/login", status_code=302)


@router.get("/recuperar")
async def recuperar_form():
    """Igual que `/login`: la pantalla de recuperar contraseña vive en el panel nuevo (`/recuperar`); `POST /recuperar` sigue aquí."""
    return RedirectResponse(url=f"{url_panel_nuevo()}/recuperar", status_code=302)


@router.post("/recuperar")
async def recuperar_submit(username: str = Form(...)):
    usuario = await obtener_usuario(username.strip())
    if usuario is not None:
        await notificar_solicitud_reseteo(usuario["username"])
    # Mismo mensaje exista o no el usuario, para no revelar qué usuarios son válidos.
    return RedirectResponse(url="/dashboard/recuperar?enviado=1", status_code=303)


MAX_INTENTOS_LOGIN = 5
BLOQUEO_LOGIN_SEGUNDOS = 15 * 60
MAX_LOGIN_POR_IP_POR_MINUTO = 10


async def _resolver_login(username: str) -> tuple[dict | None, str]:
    """Resuelve la cuenta candidata para un intento de login y la clave a
    usar para el bloqueo por intentos fallidos.

    Gate 5.4 (hallazgo B del checkpoint de auditoría): `username` ya no es
    único globalmente (dos Negocios pueden tener legítimamente el mismo
    username, ver T3) — bloquear por el username crudo permitía que un
    ataque de fuerza bruta contra "admin" de un Negocio bloqueara también a
    "admin" de otro Negocio (denegación de servicio cross-tenant por destino
    compartido). Se resuelve la cuenta PRIMERO (antes se llamaba más abajo,
    después del chequeo de bloqueo — el costo de la consulta extra ya está
    acotado por el rate limit de IP que corre antes) para poder candadear
    por `(negocio_id, username)` cuando la cuenta es identificable sin
    ambigüedad. Si el username no existe o es ambiguo entre Negocios (mismo
    caso límite ya documentado en `obtener_usuario`), no hay una cuenta
    específica de un Negocio real que aislar — se conserva el candado por
    el username crudo, comportamiento idéntico al de antes de este fix."""
    usuario = await obtener_usuario(username)
    clave_bloqueo = f"{usuario['negocio_id']}:{username}" if usuario else username
    return usuario, clave_bloqueo


@router.post("/login")
async def login_submit(request: Request, username: str = Form(...), password: str = Form(...)):
    # Rate limiting por IP — mitiga fuerza bruta distribuida entre varios
    # usuarios probados desde el mismo origen (Security Architecture, P1).
    ip = ip_cliente(request)
    if not limitador_login.permitir(ip, MAX_LOGIN_POR_IP_POR_MINUTO, 60):
        return RedirectResponse(
            url="/dashboard/login?error=Demasiados+intentos+—+espera+un+minuto+y+vuelve+a+intentar",
            status_code=303,
        )

    usuario, clave_bloqueo = await _resolver_login(username)

    # Bloqueo por intentos fallidos consecutivos sobre la misma cuenta
    # (Security Architecture, P1 — antes no había ningún límite).
    restante = bloqueo_login.segundos_restantes(clave_bloqueo)
    if restante is not None:
        minutos = max(1, round(restante / 60))
        return RedirectResponse(
            url=f"/dashboard/login?error=Cuenta+bloqueada+temporalmente+—+intenta+en+{minutos}+minuto(s)",
            status_code=303,
        )

    # Gate Equipo (2026-09-14): una cuenta apagada (`activo=False`) no puede
    # iniciar sesión — sin esto, "apagar" en la pantalla Equipo sería solo
    # cosmético. Se trata igual que una credencial inválida a propósito (sin
    # mensaje distinto "cuenta desactivada"): no revela a quien intenta
    # loguearse si el username existe pero está apagado.
    credenciales_validas = (
        usuario is not None and usuario.get("activo", True)
        and bcrypt.checkpw(password.encode(), usuario["password_hash"].encode())
    )
    if not credenciales_validas:
        bloqueo_login.registrar_fallo(clave_bloqueo, MAX_INTENTOS_LOGIN, BLOQUEO_LOGIN_SEGUNDOS)
        return RedirectResponse(url="/dashboard/login?error=Usuario+o+contraseña+incorrectos", status_code=303)

    bloqueo_login.registrar_exito(clave_bloqueo)
    request.session["username"] = usuario["username"]
    return RedirectResponse(url="/dashboard", status_code=303)


@router.post("/logout")
async def logout(request: Request, _csrf: None = Depends(verificar_csrf)):
    request.session.clear()
    return RedirectResponse(url="/dashboard/login", status_code=303)


# ── Bandeja principal (sin conversación seleccionada) ─────────────────

async def _contenido_metricas(leads: list[dict], mostrar_derivados: bool = True, mostrar_exportar: bool = True) -> str:
    """Embudo + tabla completa de leads + exportar — página separada de Métricas.
    Reutilizada también para la vista personal del Asesor (Bloque Analítica —
    vista personal de Asesor): mismo render, con `leads` ya pre-filtrados a su
    propia cartera y los flags en False (derivados/exportar no aplican a la
    vista de un único asesor sobre sí mismo)."""
    embudo = _calcular_embudo(leads)
    tarjetas = "".join(
        f"""<div class="col">
            <div class="card funnel-card shadow-sm h-100">
                <div class="card-body py-2 text-center">
                    <div class="icono mx-auto mb-1" style="background:{ICONO_ETAPA.get(etiqueta, ('bi-circle', '#94a3b8'))[1]}">
                        <i class="bi {ICONO_ETAPA.get(etiqueta, ('bi-circle', '#94a3b8'))[0]}"></i>
                    </div>
                    <div class="d-flex align-items-baseline justify-content-center gap-2">
                        <span class="fs-5 fw-bold" style="color:var(--gaso-azul)">{cantidad}</span>
                        <span class="badge-suave" style="background-color:#f1f5f9;color:#475569">{pct}%</span>
                    </div>
                    <div class="text-muted mt-1" style="font-size:.76rem">{html.escape(etiqueta)}</div>
                </div>
            </div>
        </div>"""
        for etiqueta, cantidad, pct in embudo
    )

    derivados_html = ""
    if mostrar_derivados:
        conteos_derivado = {estado: 0 for estado in ESTADOS_DERIVADO}
        for lead in leads:
            estado = _estado_conversacion(lead)
            if estado in conteos_derivado:
                conteos_derivado[estado] += 1
        total_derivados = sum(conteos_derivado.values())

        tarjetas_derivado = "".join(
            f"""<div class="col">
                <div class="card funnel-card shadow-sm h-100">
                    <div class="card-body py-2 text-center">
                        <div class="icono mx-auto mb-1" style="background:{ICONO_ESTADO[estado][1]}">
                            <i class="bi {ICONO_ESTADO[estado][0]}"></i>
                        </div>
                        <div class="d-flex align-items-baseline justify-content-center gap-2">
                            <span class="fs-5 fw-bold" style="color:var(--gaso-azul)">{conteos_derivado[estado]}</span>
                            <span class="badge-suave" style="background-color:#f1f5f9;color:#475569">
                                {round(conteos_derivado[estado] / total_derivados * 100) if total_derivados else 0}%
                            </span>
                        </div>
                        <div class="text-muted mt-1" style="font-size:.76rem">{html.escape(ETIQUETAS_ESTADO[estado])}</div>
                    </div>
                </div>
            </div>"""
            for estado in ESTADOS_DERIVADO
        )
        derivados_html = f"""
    {_titulo_seccion('bi-person-check-fill', 'Estado con asesor humano (derivados)')}
    <div class="row row-cols-2 row-cols-md-4 g-2 mb-3">{tarjetas_derivado}</div>
    """

    filas = "".join(
        f"""<tr data-buscar="{html.escape((lead.get('nombre') or '') + ' ' + lead['telefono'] + ' ' + (lead.get('interes') or '') + ' ' + (lead.get('producto_tipo') or '') + ' ' + (lead.get('producto_marca') or '') + ' ' + (lead.get('asesor_asignado') or '') + ' ' + (lead.get('campana_origen') or '') + ' ' + (lead.get('_busqueda_venta') or ''), quote=True).lower()}">
            <td class="ps-4">
                <a href="/dashboard/lead/{html.escape(lead['telefono'])}" class="d-flex align-items-center gap-2 text-decoration-none text-dark" data-ajax="1">
                    {_avatar(lead.get('nombre') or lead['telefono'], 26)}
                    <span class="fw-semibold">{html.escape(lead.get('nombre') or '(sin nombre)')}</span>
                </a>
            </td>
            <td class="text-muted">{html.escape(lead['telefono'])}</td>
            <td class="text-muted">{html.escape((lead.get('producto_tipo') or '-').capitalize())}</td>
            <td class="text-muted">{html.escape(lead.get('producto_marca') or '-')}</td>
            <td class="text-muted">{html.escape((lead.get('producto_modalidad') or '-').capitalize())}</td>
            <td><span class="badge-suave" style="background-color:#f1f5f9;color:#475569">{html.escape((lead.get('paso_flujo') or '-').replace('_', ' '))}</span></td>
            <td>{_pill_resultado(lead.get('resultado'))}</td>
            <td class="text-muted">{html.escape(lead.get('asesor_asignado') or 'Sin asignar')}</td>
            <td class="text-muted">{html.escape(lead.get('producto_vendido') or '-')}</td>
            <td class="text-muted">{html.escape(lead.get('marca_venta') or '-')}</td>
            <td class="text-muted">{html.escape(lead.get('proveedor_venta') or '-')}</td>
            <td class="text-muted">{f"S/ {html.escape(lead['precio_venta'])}" if lead.get('precio_venta') else '-'}</td>
            <td class="text-muted">{html.escape((lead.get('modalidad_pago') or '-').capitalize())}</td>
            <td class="text-muted">{html.escape(lead.get('cuotas') + ' meses' if lead.get('cuotas') else '-')}</td>
            <td class="text-muted">{html.escape(lead.get('medio_pago') or '-')}</td>
            <td class="text-muted">{html.escape(lead.get('campana_origen') or '-')}</td>
            <td class="text-muted" data-ts="{lead['creado'].isoformat()}" title="{lead['creado'].strftime('%d/%m/%Y %H:%M')}">{lead['creado'].strftime('%d/%m/%Y')}</td>
            <td class="text-muted text-end pe-4" data-ts="{lead['actualizado'].isoformat()}" title="{lead['actualizado'].strftime('%d/%m/%Y %H:%M')}">{_tiempo_relativo(lead['actualizado'])}</td>
        </tr>"""
        for lead in leads
    )
    columnas_metricas = [
        "Cliente", "Teléfono", "Tipo", "Marca", "Modalidad", "Etapa", "Resultado", "Asesor",
        "Producto vendido", "Marca vendida", "Proveedor", "Precio", "Tipo de pago", "Cuotas", "Medio de pago",
        "Campaña", "Creado el", "Última actividad",
    ]
    encabezados_metricas = "".join(
        f'<th class="{"ps-4" if i == 0 else ("text-end pe-4" if i == len(columnas_metricas) - 1 else "")}" '
        f'style="cursor:pointer;user-select:none" data-col="{i}">{html.escape(col)} <i class="bi bi-arrow-down-up" style="font-size:.7em"></i></th>'
        for i, col in enumerate(columnas_metricas)
    )

    exportar_html = (
        """<div class="d-flex gap-2">
            <a href="/dashboard/metricas/exportar.csv" class="btn btn-sm btn-outline-primary"><i class="bi bi-download"></i> CSV</a>
            <a href="/dashboard/metricas/exportar.xlsx" class="btn btn-sm btn-outline-primary"><i class="bi bi-file-earmark-excel"></i> Excel</a>
        </div>"""
        if mostrar_exportar else ""
    )

    return f"""
    <div class="d-flex justify-content-between align-items-center mb-3">
        {_titulo_seccion('bi-graph-up-arrow', 'Métricas')}
        {exportar_html}
    </div>

    {_titulo_seccion('bi-funnel-fill', 'Embudo de ventas (con Gabi)')}
    <div class="row row-cols-2 row-cols-md-3 row-cols-lg-5 g-2 mb-3">{tarjetas}</div>

    {derivados_html}

    {_titulo_seccion('bi-people-fill', f'Leads ({len(leads)})')}
    <div class="d-flex justify-content-between align-items-center mb-3 gap-2">
        <div class="input-group input-group-sm" style="max-width:320px">
            <span class="input-group-text bg-white border-end-0"><i class="bi bi-search text-muted"></i></span>
            <input type="text" id="buscar-metricas" class="form-control border-start-0" placeholder="Buscar por nombre, teléfono, interés, asesor, campaña o producto...">
        </div>
        <span class="text-muted small" id="metricas-contador"></span>
    </div>
    <div class="card leads-card shadow-sm">
        <div class="barra-acento"></div>
        <div class="table-responsive">
            <table class="table align-middle mb-0 tabla-ejecutiva" id="tabla-metricas">
                <thead>
                    <tr>{encabezados_metricas}</tr>
                </thead>
                <tbody>{filas or '<tr><td colspan="18" class="text-center text-muted py-5">Aún no hay leads.</td></tr>'}</tbody>
            </table>
        </div>
        <div class="d-flex justify-content-between align-items-center p-3 border-top small" id="metricas-paginacion" style="display:none !important">
            <button type="button" class="btn btn-sm btn-outline-secondary" id="metricas-prev">&laquo; Anterior</button>
            <span class="text-muted" id="metricas-pag-info"></span>
            <button type="button" class="btn btn-sm btn-outline-secondary" id="metricas-next">Siguiente &raquo;</button>
        </div>
    </div>
    {_script_tabla_dinamica("metricas")}
    """


@router.get("/metricas", response_class=HTMLResponse)
async def metricas(request: Request, usuario: dict = Depends(servicio_identidad.requiere_rol("admin", "supervisor", "asesor"))):
    # Sin rail de conversaciones acá a propósito (a diferencia de otras
    # páginas secundarias) — esta vista ya muestra su propio embudo
    # (Cap. 4.3), repetirlo en el rail era literalmente la misma
    # información duplicada dos veces en la misma pantalla.
    # Bloque Analítica — vista personal de Asesor: mismo patrón de alcance
    # por rol que ya usa CRM/Pipeline — el asesor nunca puede elegir otro
    # asesor (no hay parámetro de query para eso), su cartera se resuelve
    # server-side con su propio username.
    vision_total = usuario["rol"] in ROLES_CON_VISION_TOTAL
    leads = await _adjuntar_resumen_ventas(
        await listar_leads(usuario["negocio_id"], asesor_asignado=None if vision_total else usuario["username"]),
        usuario["negocio_id"],
    )
    panel = await _contenido_metricas(leads, mostrar_derivados=vision_total, mostrar_exportar=vision_total)
    cuerpo = f"""<div class="shell d-flex"><div class="main-pane flex-grow-1 p-4">{panel}</div></div>"""
    return _pagina("Métricas", usuario, cuerpo, request=request)


# ── CRM / Pipeline (MAIEK_AI_PRODUCT_PATTERNS.md, Cap. 6) ──────────────
#
# Destino de navegación propio (decisión de producto 2026-07-30): "gestionar
# la cartera de oportunidades", distinto de la Bandeja ("qué hacer ahora en
# mis conversaciones"). Construido de forma independiente de
# _tabla_todos_los_leads/_contenido_metricas a propósito — mismo criterio
# del Sprint 2 de aceptar duplicación temporal antes que forzar una
# abstracción compartida sobre un Data Grid que todavía está evolucionando.
# Reutiliza sí las clases CSS ya existentes (tabla-ejecutiva, leads-card,
# barra-acento) para consistencia visual, y reutiliza detalle_lead sin
# cambios como vista de detalle (clic en una fila).

_COLUMNAS_PIPELINE = [
    (None, "Cliente"), (None, "Interés"), ("resultado", "Resultado"),
    ("asesor", "Asesor"), ("actualizado", "Actividad"),
]

# Tamaño de página del Pipeline en el panel HTML. Fijo a propósito: los links
# de paginación (_url_pipeline) no arrastran `por_pagina`, así que dejarlo
# configurable desde la URL se perdería al pasar de página. La API JSON sí lo
# acepta como parámetro, porque ahí el cliente arma cada request completo.
POR_PAGINA_PIPELINE = 20
POR_PAGINA_PIPELINE_MAXIMO = 200

# Alcance de la cartera pedido por el cliente. Es una PREFERENCIA, no un
# permiso: quien no tiene visión total termina en "mi_pipeline" mande lo que
# mande (ver _alcance_pipeline).
ALCANCES_PIPELINE = ("mi_pipeline", "todos")


def _badge_resultado(lead: dict) -> str:
    resultado = lead.get("resultado")
    if not resultado:
        return '<span class="badge-suave" style="background-color:#f1f5f9;color:#64748b">Sin resultado</span>'
    color = COLOR_RESULTADO.get(resultado, "#6b7280")
    etiqueta = ETIQUETAS_RESULTADO.get(resultado, resultado)
    return f'<span class="badge-suave" style="background-color:{color}22;color:{color}">{html.escape(etiqueta)}</span>'


def _fila_pipeline(lead: dict) -> str:
    nombre = lead.get("nombre") or lead["telefono"]
    return f"""<tr>
        <td class="ps-4">
            <a href="/dashboard/lead/{html.escape(lead['telefono'])}" class="d-flex align-items-center gap-2 text-decoration-none text-dark" data-ajax="1">
                {_avatar(nombre, 26)}
                <span class="text-truncate"><span class="fw-semibold">{html.escape(nombre)}</span>
                <span class="text-muted" style="font-size:.8rem"> &middot; {html.escape(lead['telefono'])}</span></span>
            </a>
        </td>
        <td class="text-muted"><span class="d-inline-block text-truncate align-bottom" style="max-width:220px" title="{html.escape(lead.get('interes') or '')}">{html.escape(lead.get('interes') or '-')}</span></td>
        <td>{_badge_resultado(lead)}</td>
        <td class="text-muted">{html.escape(lead.get('asesor_asignado') or 'Sin asignar')}</td>
        <td class="text-muted text-end pe-4" title="{lead['actualizado'].strftime('%d/%m/%Y %H:%M')}">{_tiempo_relativo(lead['actualizado'])}</td>
    </tr>"""


def _url_pipeline(params: dict) -> str:
    limpio = {k: v for k, v in params.items() if v not in (None, "") and not (k == "pagina" and v == 1)}
    return "/dashboard/pipeline?" + urlencode(limpio)


def _header_pipeline(col_key: str | None, etiqueta: str, params: dict, orden_actual: str, dir_actual: str) -> str:
    if not col_key:
        clase = ' class="ps-4"' if etiqueta == "Cliente" else ""
        return f'<th{clase}>{html.escape(etiqueta)}</th>'
    activa = orden_actual == col_key
    nuevo_dir = "asc" if (activa and dir_actual == "desc") else "desc" if activa else "asc"
    href = _url_pipeline({**params, "orden": col_key, "dir": nuevo_dir, "pagina": 1})
    icono = ("bi-arrow-down" if dir_actual == "desc" else "bi-arrow-up") if activa else "bi-arrow-down-up"
    return (
        f'<th><a href="{href}" data-ajax="1" class="text-decoration-none text-dark d-inline-flex align-items-center gap-1">'
        f'{html.escape(etiqueta)} <i class="bi {icono}" style="font-size:.7em"></i></a></th>'
    )


def _contenido_pipeline(
    leads: list[dict], total: int, q: str, resultado: str, asesor: str,
    orden: str, dir_: str, pagina: int, por_pagina: int, asesores: list[dict], vision_total: bool,
) -> str:
    params = {"q": q, "resultado": resultado, "asesor": asesor, "orden": orden, "dir": dir_}
    opciones_resultado = "".join(
        f'<option value="{r}"{" selected" if resultado == r else ""}>{html.escape(ETIQUETAS_RESULTADO[r])}</option>'
        for r in RESULTADOS
    )
    select_asesor = ""
    if vision_total:
        opciones_asesor = "".join(
            f'<option value="{html.escape(a["username"])}"{" selected" if asesor == a["username"] else ""}>{html.escape(a["nombre"])}</option>'
            for a in asesores
        )
        select_asesor = f"""
        <select name="asesor" id="pipeline-asesor" class="form-select form-select-sm" style="max-width:200px">
            <option value="">Todos los asesores</option>
            {opciones_asesor}
        </select>"""
    encabezados = "".join(_header_pipeline(col, etiqueta, params, orden, dir_) for col, etiqueta in _COLUMNAS_PIPELINE)
    filas = "".join(_fila_pipeline(lead) for lead in leads) or (
        f'<tr><td colspan="{len(_COLUMNAS_PIPELINE)}" class="text-center text-muted py-5">'
        f'{"No hay leads que coincidan con los filtros." if (q or resultado or asesor) else "Todavía no hay leads en tu cartera."}</td></tr>'
    )
    total_paginas = max(1, -(-total // por_pagina))
    href_prev = _url_pipeline({**params, "pagina": pagina - 1}) if pagina > 1 else ""
    href_next = _url_pipeline({**params, "pagina": pagina + 1}) if pagina < total_paginas else ""
    return f"""
    {_titulo_seccion('bi-briefcase-fill', f'CRM / Pipeline ({total})')}
    <form id="form-filtros-pipeline" class="d-flex flex-wrap align-items-center gap-2 mb-3">
        <input type="hidden" name="orden" value="{html.escape(orden)}">
        <input type="hidden" name="dir" value="{html.escape(dir_)}">
        <div class="input-group input-group-sm" style="max-width:280px">
            <span class="input-group-text bg-white border-end-0"><i class="bi bi-search text-muted"></i></span>
            <input type="text" name="q" value="{html.escape(q)}" class="form-control border-start-0" placeholder="Buscar por nombre, teléfono o interés...">
        </div>
        <select name="resultado" class="form-select form-select-sm" style="max-width:200px">
            <option value="">Todos los resultados</option>
            {opciones_resultado}
        </select>
        {select_asesor}
        <button type="submit" class="btn btn-sm btn-outline-primary">Filtrar</button>
    </form>
    <div class="card leads-card shadow-sm">
        <div class="barra-acento"></div>
        <div class="table-responsive">
            <table class="table align-middle mb-0 tabla-ejecutiva">
                <thead><tr>{encabezados}</tr></thead>
                <tbody>{filas}</tbody>
            </table>
        </div>
        <div class="d-flex justify-content-between align-items-center p-3 border-top small">
            <a href="{href_prev}" data-ajax="1" class="btn btn-sm btn-outline-secondary{' disabled' if not href_prev else ''}">&laquo; Anterior</a>
            <span class="text-muted">Página {pagina} de {total_paginas}</span>
            <a href="{href_next}" data-ajax="1" class="btn btn-sm btn-outline-secondary{' disabled' if not href_next else ''}">Siguiente &raquo;</a>
        </div>
    </div>
    <script>
    (function() {{
        var form = document.getElementById('form-filtros-pipeline');
        if (!form) return;
        form.addEventListener('submit', function(ev) {{
            ev.preventDefault();
            var datos = new FormData(form);
            var params = new URLSearchParams();
            datos.forEach(function(valor, clave) {{ if (valor) params.set(clave, valor); }});
            window.__navegarAjax('/dashboard/pipeline?' + params.toString(), true);
        }});
    }})();
    </script>
    """


# ── Contrato JSON del Pipeline (vertical Pipeline → Lead → Close-Won) ──────
#
# La MISMA ruta /dashboard/pipeline sirve el panel HTML y el DTO JSON, por
# negociación de contenido (`Accept: application/json`). Se eligió eso en vez
# de una ruta paralela (/dashboard/pipeline.json, /api/pipeline) porque el
# recurso es idéntico —mismos filtros, mismo orden server-side y, sobre todo,
# el mismo forzado de alcance por rol—: separar las rutas obligaría a duplicar
# ese forzado, que es justo la pieza que no puede desincronizarse. Productos
# (sub-bloque b) sí es una ruta JSON pura, pero ahí no existía una vista HTML
# previa con la que compartir el recurso.
#
# No colisiona con el panel: la navegación del navegador manda
# `Accept: text/html,...` y el fetch de la navegación AJAX (X-Panel-Fragment)
# manda `*/*`; ninguno de los dos contiene "application/json".


def _pide_json_explicitamente(request: Request) -> bool:
    """Negociación de contenido explícita: solo un Accept que NOMBRE
    application/json pide el DTO; el comodín `*/*` no cuenta. Cualquier otra
    cosa —incluido un cliente sin Accept— sigue recibiendo el panel HTML.

    Mismo criterio (y mismo nombre) que el de agent/main.py, que ya lo usa
    para decidir si un no-autenticado recibe 401 JSON o el redirect al login.
    Está duplicado a propósito: dashboard.py no puede importar de main.py sin
    ciclo (main importa este router). Si aparece un tercer uso, el lugar
    natural es agent/http_utils.py."""
    return "application/json" in (request.headers.get("accept") or "").lower()


def _alcance_pipeline(usuario: dict, alcance: str, asesor: str) -> tuple[str | None, str]:
    """Resuelve a qué cartera mira este usuario. Retorna (asesor a filtrar,
    alcance realmente aplicado).

    El alcance pedido por el cliente es una preferencia; el rol es la regla
    (MPA §9: el asesor ve 'Solo sus leads'). Un asesor que mande
    `alcance=todos` o `asesor=otra_persona` recibe igual su propia cartera —
    no un 403, porque no está pidiendo un recurso prohibido sino uno más
    amplio del que le corresponde, y el panel HTML ya se comportaba así."""
    if usuario["rol"] not in ROLES_CON_VISION_TOTAL:
        return usuario["username"], "mi_pipeline"
    if alcance == "mi_pipeline":
        return usuario["username"], "mi_pipeline"
    return (asesor or None), "todos"


def _dto_lead_pipeline(lead: dict) -> dict:
    """Fila del Pipeline tal como la consume la Nueva Experiencia (Next.js).

    Incluye a propósito más que las 5 columnas visibles: Pipeline es la
    pantalla que navega hacia el detalle del Lead, así que los 6 campos del
    contrato de Lead viajan desde ya —`id`, `telefono`, `version`,
    `revision_prioritaria`, `pausado_manual`, `asesor_asignado`— para que el
    destino no tenga que volver a pedirlos ni inferirlos.

    `id` y `telefono` se exponen SEPARADOS aunque hoy valgan lo mismo: `id` es
    la identidad del recurso (la que arma la URL /leads/[id]) y `telefono` es
    un dato de negocio que se muestra y con el que se escribe por WhatsApp.
    Cuando la identidad migre a UUID (MAIEK_AI_DATA_ARCHITECTURE.md), cambia
    `id` y `telefono` se queda donde está, sin tocar el cliente.

    `actualizado`/`creado` llevan sufijo `Z`: son instantes reales, guardados
    en UTC (`datetime.utcnow()`), y sin declarar la zona `new Date()` del
    navegador los interpreta como hora LOCAL — 5 h adelantados para un
    usuario en Lima. `fecha_agendada` NO lleva `Z` a propósito: no es un
    instante, es la hora de una cita tal como la tipeó un humano en su propia
    zona horaria (`<input type=datetime-local>`); envolverla en UTC la
    corrompería, por eso usa `_iso()` sin sufijo, igual que siempre.

    `iso_utc()` es la misma función que usan los DTO de Productos; vive a nivel
    de módulo en agent/memory.py para no volver a copiarla por cada consumidor."""
    def _iso(valor):
        return valor.isoformat() if isinstance(valor, datetime) else valor

    return {
        # Identidad + contrato de Lead — Gate 5.3 cutover real §8: `id` deja
        # de ser el teléfono. Es el `conversation_id` (real, navegable hacia
        # `/dashboard/conversation/{id}`) cuando ya existe Contact/Conversation
        # para este lead; si todavía no existe (sin backfill/webhook), cae a
        # telefono como fallback — esa fila sigue funcionando por el camino
        # legacy hasta que exista.
        "id": lead.get("conversation_id") or lead["telefono"],
        "telefono": lead["telefono"],
        "version": lead.get("version"),
        "revision_prioritaria": lead.get("revision_prioritaria"),
        "pausado_manual": lead.get("pausado_manual"),
        "asesor_asignado": lead.get("asesor_asignado"),
        # Columnas visibles del Pipeline
        "nombre": lead.get("nombre"),
        "interes": lead.get("interes"),
        "resultado": lead.get("resultado"),
        "actualizado": iso_utc(lead.get("actualizado")),
        # Contexto mínimo de la fila (badges/estado), en ISO como el resto de
        # las APIs JSON del panel
        "creado": iso_utc(lead.get("creado")),
        "fecha_agendada": _iso(lead.get("fecha_agendada")),
        "visto_asesor": lead.get("visto_asesor"),
        # Etapa derivada (2026-11-05): dónde va el caso, calculada con resultado + asesora + derivación. Ver agent/pipeline_etapas.py.
        "etapa": pipeline_etapas.etapa_de(lead.get("resultado"), lead.get("asesor_asignado"), lead.get("paso_flujo")),
    }


async def _telefonos_de_vista_pipeline(vista: str, usuario: dict) -> list[str] | None:
    """Teléfonos que forman una vista del Pipeline que sale de otra consulta, o None si `vista` no es una de ellas.

    «sin_asesor» es la MISMA lista que muestra Inicio (`listar_leads_esperando_asesor`), solo para admin/supervisor; «para_llamar»
    son las tareas abiertas de «Llamadas» que ve esta persona (`llamadas.listar_tareas`: respeta el modo del módulo y la cartera)."""
    if vista == "sin_asesor":
        if usuario["rol"] not in ROLES_CON_VISION_TOTAL:
            return []
        return [l["telefono"] for l in await listar_leads_esperando_asesor(usuario["negocio_id"])]
    if vista == "para_llamar":
        datos = await llamadas.listar_tareas(usuario["negocio_id"], usuario)
        return sorted({t["telefono"] for t in datos.get("tareas", []) if t.get("telefono")})
    return None


# response_class=HTMLResponse sigue siendo obligatorio aunque esta ruta ahora
# también responda JSON: _pagina() devuelve un str crudo, no un Response, así
# que sin esto FastAPI lo serializaría como JSON y el panel entero llegaría
# escapado dentro de comillas (probado). El JSONResponse que se devuelve más
# abajo es un Response explícito y pasa de largo por esta clase por defecto.
@router.get("/pipeline", response_class=HTMLResponse)
async def crm_pipeline(
    request: Request,
    usuario: dict = Depends(_usuario_actual),
    q: str = "",
    resultado: str = "",
    asesor: str = "",
    interes: str = "",
    alcance: str = "",
    orden: str = "actualizado",
    dir: str = "desc",
    pagina: int = 1,
    por_pagina: int = POR_PAGINA_PIPELINE,
    etapa: str = "",
    vista: str = "",
):
    """CRM / Pipeline — alcance por rol: admin/supervisor ven toda la
    cartera (con filtro opcional por asesor); asesor ve solo sus propios
    leads (MPA §9: 'Solo sus leads'), sin poder elegir otro asesor.

    Devuelve HTML (panel) o JSON (Nueva Experiencia) según el Accept — ver
    _pide_json_explicitamente más arriba. `orden`, `dir`, `pagina` y
    `por_pagina` se NORMALIZAN en vez de rechazarse con 400: mismo criterio
    que Productos, un parámetro de presentación fuera de rango no es motivo
    para no mostrarle su cartera a nadie."""
    vision_total = usuario["rol"] in ROLES_CON_VISION_TOTAL
    asesor_filtro, alcance_aplicado = _alcance_pipeline(usuario, alcance, asesor)
    if orden not in COLUMNAS_ORDEN_PIPELINE:
        orden = "actualizado"
    if dir not in ("asc", "desc"):
        dir = "desc"
    pagina = max(1, pagina)
    quiere_json = _pide_json_explicitamente(request)
    # El panel HTML pagina siempre de a 20 (ver POR_PAGINA_PIPELINE); solo la
    # API deja elegir, con tope para que nadie pida la cartera entera.
    por_pagina = min(max(1, por_pagina), POR_PAGINA_PIPELINE_MAXIMO) if quiere_json else POR_PAGINA_PIPELINE
    # 2026-11-05 — `etapa` y `vista` solo los manda la Nueva Experiencia; un valor desconocido se ignora, igual que `resultado`.
    condicion_etapa = pipeline_etapas.condicion_etapa(etapa) if quiere_json else None
    telefonos_vista = await _telefonos_de_vista_pipeline(vista, usuario) if quiere_json else None
    leads, total = await listar_leads_pipeline(
        negocio_id=usuario["negocio_id"],
        asesor_asignado=asesor_filtro, resultado=resultado or None, busqueda=q.strip(),
        interes=interes.strip() or None,
        orden=orden, direccion=dir, pagina=pagina, por_pagina=por_pagina,
        condiciones=(condicion_etapa,) if condicion_etapa is not None else (), telefonos=telefonos_vista,
    )
    if quiere_json:
        # P1-A (UX-03 Fase 0/1): el frontend ya calculaba y mandaba `alcance`,
        # pero nunca sabía cuál se aplicó DE VERDAD — para un Asesor,
        # `_alcance_pipeline` siempre fuerza "mi_pipeline" server-side aunque
        # el cliente pida "todos", y el selector de la Nueva Experiencia no
        # tenía forma de reflejarlo. Se expone el valor ya resuelto, no se
        # cambia ninguna regla de autorización.
        return JSONResponse({
            "leads": [_dto_lead_pipeline(lead) for lead in leads],
            "total": total, "pagina": pagina, "por_pagina": por_pagina,
            "alcance_aplicado": alcance_aplicado,
        })

    asesores = await listar_asesores(usuario["negocio_id"]) if vision_total else []
    panel = _contenido_pipeline(
        leads, total, q, resultado,
        asesor if (vision_total and alcance_aplicado == "todos") else "",
        orden, dir, pagina, por_pagina, asesores, vision_total,
    )
    cuerpo = f"""<div class="shell d-flex"><div class="main-pane flex-grow-1 p-4">{panel}</div></div>"""
    return _pagina("CRM / Pipeline", usuario, cuerpo, request=request)


@router.get("/pipeline/conteos")
async def crm_pipeline_conteos(request: Request, usuario: dict = Depends(_usuario_actual), alcance: str = "", asesor: str = ""):
    """Conteos para la franja de etapas y las pestañas del Pipeline (2026-11-05). Mismo alcance por rol que `/pipeline`: un
    Asesor cuenta solo su cartera. `vistas.sin_asesor` es `null` para quien no tiene visión total (esa vista no existe para él)."""
    asesor_filtro, alcance_aplicado = _alcance_pipeline(usuario, alcance, asesor)
    vision_total = usuario["rol"] in ROLES_CON_VISION_TOTAL
    etapas = await pipeline_etapas.contar_por_etapa(usuario["negocio_id"], asesor_filtro)
    sin_asesor = len(await _telefonos_de_vista_pipeline("sin_asesor", usuario) or []) if vision_total else None
    para_llamar = len(await _telefonos_de_vista_pipeline("para_llamar", usuario) or [])
    return JSONResponse({
        "etapas": etapas,
        "total": sum(etapas.values()),
        "vistas": {
            "mios": await pipeline_etapas.contar_asignados_a(usuario["negocio_id"], usuario["username"]),
            "sin_asesor": sin_asesor,
            "para_llamar": para_llamar,
            "citas": etapas["agendado"],
        },
        "alcance_aplicado": alcance_aplicado,
    })


@router.get("/conversaciones")
async def bandeja_conversaciones(
    request: Request,
    usuario: dict = Depends(_usuario_actual),
    q: str = "",
    asesor: str = "",
    alcance: str = "",
    resultado: str = "",
    orden: str = "actividad",
    dir: str = "desc",
    pagina: int = 1,
    por_pagina: int = POR_PAGINA_PIPELINE,
    vista: str = "",
):
    """Gate 5.3 — Bandeja de Conversaciones, endpoint JSON dedicado (Diseño
    Técnico §13/§18). Reemplaza el reuso de `/pipeline` que hacía
    `maiek-frontend/app/api/conversaciones/route.ts` — deja de ser válido en
    cuanto una Conversation pueda tener más de una Opportunity secuencial
    (DR-3): reusar Pipeline mostraría cada Opportunity como una fila
    separada, duplicando la conversación en la Bandeja. Esta ruta lista
    `Conversation` (con `estado == "activa"`), no `Opportunity` — mismo
    alcance por rol que Pipeline (`_alcance_pipeline`, reutilizado tal
    cual: es el eje RBAC, no cambia por representar Conversation en vez de
    Opportunity). Solo responde JSON — no tiene contraparte HTML en el
    panel legacy, que sigue sirviéndose de `/pipeline`."""
    asesor_filtro, _ = _alcance_pipeline(usuario, alcance, asesor)
    if orden not in ("nombre", "resultado", "asesor", "actualizado", "creado", "actividad"):
        orden = "actividad"
    if dir not in ("asc", "desc"):
        dir = "desc"
    # Punto 4 (2026-09-28): filtro por resultado en la Bandeja — mismo
    # catálogo que ya usa la Ficha del Lead, así que un valor fuera de
    # RESULTADOS es un cliente desactualizado o manipulando la URL a mano,
    # nunca un caso real; se ignora en vez de fallar.
    # 2026-10-06: además de los resultados del catálogo, `sin_resultado` pide
    # las conversaciones SIN resultado (Opportunity vigente con resultado
    # vacío) — no es un valor guardado, es la ausencia de uno (ver
    # `listar_conversaciones_activas`). Mismo literal que usa Analítica.
    if resultado != "sin_resultado" and resultado not in RESULTADOS:
        resultado = ""
    pagina = max(1, pagina)
    por_pagina = min(max(1, por_pagina), POR_PAGINA_PIPELINE_MAXIMO)
    # 2026-10-06 (P2) — `vista`: los grupos de Inicio ("Ver los N en
    # Conversaciones"). Un valor desconocido se ignora, igual que `resultado`.
    # El criterio NO se reimplementa: se invocan las MISMAS funciones, con los
    # mismos argumentos, que `inicio_json` (`_zona_accion_datos`), así la
    # lista y los totales de Inicio coinciden siempre. Con vista la página es
    # de 50 salvo que el cliente pida otro tamaño.
    vista = vista if vista in VISTAS_INICIO else ""
    ids_ordenados: list[str] | None = None
    entradas_vista: dict[str, dict] = {}
    if vista:
        vision_total = usuario["rol"] in ROLES_CON_VISION_TOTAL
        negocio_id = usuario["negocio_id"]
        ahora = datetime.utcnow()
        es_vista_de_citas = vista in ("citas", "citas_vencidas", "citas_vencidas_antiguas")
        esperando = [] if es_vista_de_citas else await listar_clientes_esperando(
            negocio_id, asesor=asesor_filtro, ahora=ahora, con_desde=False,
        )
        proximas, vencidas = [], []
        if es_vista_de_citas:
            proximas, vencidas, _ = await _citas_inicio(negocio_id, asesor_filtro, ahora)
            if vista == "citas_vencidas_antiguas":
                vencidas = await _citas_vencidas_antiguas(negocio_id, asesor_filtro, ahora)
        # Escalados / sin asesor: solo visión total y sin acotar a un asesor
        # (un lead sin asesor no pertenece a la cartera de nadie).
        incluir_supervision = vision_total and not asesor_filtro
        esperando_asignar = (
            await listar_leads_esperando_asesor(negocio_id)
            if incluir_supervision and vista in ("responde_ahora", "sin_asesor", "escalados") else []
        )
        entradas = await resolver_entradas_vista_inicio(
            negocio_id,
            componer_vista_inicio(vista, esperando, esperando_asignar, proximas, vencidas, incluir_supervision),
        )
        ids_ordenados = [e["conversation_id"] for e in entradas]
        entradas_vista = {e["conversation_id"]: e for e in entradas}
        if "por_pagina" not in request.query_params:
            por_pagina = 50
    conversaciones, total = await listar_conversaciones_activas(
        negocio_id=usuario["negocio_id"], asesor_asignado=asesor_filtro, busqueda=q.strip(),
        resultado=resultado, orden=orden, direccion=dir, pagina=pagina, por_pagina=por_pagina,
        ids_ordenados=ids_ordenados,
    )
    # De dónde vino cada conversación (chip de campaña y banner de origen), en lote. Aditivo:
    # si falla, la bandeja sale igual, sin `origen`.
    try:
        origenes = await origen_conversacion.origenes_de_conversaciones(
            usuario["negocio_id"], [fila["id"] for fila in conversaciones],
        )
    except Exception:
        logger.exception("No se pudo calcular el origen de las conversaciones de la bandeja")
        origenes = {}
    for fila in conversaciones:
        fila["origen"] = origenes.get(fila["id"])
    if vista:
        for fila in conversaciones:
            e = entradas_vista[fila["id"]]
            fila["inicio"] = {
                "categoria": e["categoria"],
                "ultimo_mensaje_cliente_en": iso_utc(e["ultimo_mensaje_cliente_en"]) if e["ultimo_mensaje_cliente_en"] else None,
                "ventana_vence_en": iso_utc(e["ventana_vence_en"]) if e["ventana_vence_en"] else None,
                "ventana_abierta": e["ventana_abierta"],
            }
    # Misma señal de actividad real para el idle timeout de conexiones WS
    # (Gate 4.1) que ya usan `mensajes_json`/`obtener_mensajes_conversation`
    # — la conexión de LISTA de `ConversacionesVista` (sin `ver_lead`,
    # `conversation_id_activo=None`) nunca pasa por esos endpoints, así que
    # sin este golpe el barrido de inactividad la cerraría cada ~2 min
    # aunque el navegador siga ahí (ver `tocar_actividad`).
    gestor_conexiones.tocar_actividad(usuario["username"], None)
    return JSONResponse({
        "conversaciones": conversaciones, "total": total, "pagina": pagina, "por_pagina": por_pagina,
        **({"vista": vista} if vista else {}),
    })


def _verificar_acceso_conversation(usuario: dict, asesor_asignado: str | None):
    """Mismo criterio que `_verificar_acceso_lead` (línea ~309), aplicado a
    Conversation en vez de Lead: un Asesor solo ve lo que tiene asignado."""
    if not tiene_acceso_a_lead(usuario["rol"], usuario["username"], asesor_asignado):
        raise HTTPException(status_code=403, detail="No tienes acceso a esta conversación")


async def _contact_autorizado(contact_id: str, usuario: dict) -> dict:
    """404 si el Contact no existe o es de otro Negocio; 403 si es de este
    Negocio pero el usuario (rol asesor) no tiene ninguna Conversation propia
    ahí — mismo criterio de dos capas que el resto del Gate (ver
    `_verificar_acceso_conversation`)."""
    contact = await obtener_contact_detalle(contact_id, usuario["negocio_id"])
    if contact is None:
        raise HTTPException(status_code=404, detail="Contact no encontrado")
    if usuario["rol"] not in ROLES_CON_VISION_TOTAL:
        tiene_alguna = any(
            c["asesor_asignado"] == usuario["username"] for c in contact["conversaciones"]
        )
        if not tiene_alguna:
            raise HTTPException(status_code=403, detail="No tienes acceso a este contacto")
    return contact


@router.get("/contact/{contact_id}")
async def contact_detalle(contact_id: str, usuario: dict = Depends(_usuario_actual)):
    """Gate 5.3 §17 — historial estructural del Contact: identidad + todas
    sus Conversation (activas y cerradas). `negocio_id` SIEMPRE resuelto de
    la sesión — nunca del path/query (regla de API del Gate). Solo la
    estructura de datos: la UI de este historial es de un Gate posterior."""
    return JSONResponse(await _contact_autorizado(contact_id, usuario))


@router.get("/contact/{contact_id}/conversaciones")
async def contact_conversaciones(contact_id: str, usuario: dict = Depends(_usuario_actual)):
    """Endpoint dedicado del Diseño Técnico Gate 5.3 §13/§17 (cutover real —
    antes solo viajaba embebido dentro de `/contact/{id}`; se agrega la ruta
    propia para que el contrato de API coincida exactamente con el
    ratificado, sin quitar el campo embebido de arriba)."""
    contact = await _contact_autorizado(contact_id, usuario)
    return JSONResponse({"conversaciones": contact["conversaciones"]})


def _dto_conversation_detalle(conversation: dict, lineas: list[dict], eventos: list[dict]) -> dict:
    """Gate 5.3 cutover real §8/§13 — equivalente Opportunity/Conversation de
    `_dto_lead_detalle` (misma forma de `venta`/campos, mismo criterio de
    sufijo `Z` en instantes reales vs. `fecha_agendada` sin `Z` por ser hora
    tipeada por un humano): el `id` es `conversation_id`, no telefono; el
    control de concurrencia viaja partido en `conversation_version`/
    `opportunity_version` en vez de un solo `version`."""
    def _iso(valor):
        return valor.isoformat() if isinstance(valor, datetime) else valor

    venta = None
    if lineas:
        venta = {
            "lineas": [
                {
                    "id": l.get("id"), "producto_id": l.get("producto_id"),
                    "producto": l.get("producto"), "precio": l.get("precio"),
                    "marca": l.get("marca"), "proveedor": l.get("proveedor"), "creado": iso_utc(l.get("creado")),
                }
                for l in lineas
            ],
            "modalidad_pago": conversation.get("modalidad_pago"),
            "cuotas": conversation.get("cuotas"),
            "cuota_pactada": conversation.get("cuota_pactada"),
            "monto_financiado": conversation.get("monto_financiado"),
            "tea_pactada": conversation.get("tea_pactada"),
            "igv_pactado": conversation.get("igv_pactado"),
            "medio_pago": conversation.get("medio_pago"),
            "total": _resumen_venta(lineas)["precio_venta"],
        }

    return {
        "id": conversation["id"],
        "opportunity_id": conversation.get("opportunity_id"),
        "telefono": conversation.get("telefono"),
        "nombre": conversation.get("nombre"),
        "interes": conversation.get("interes"),
        "resultado": conversation.get("resultado"),
        "fecha_agendada": _iso(conversation.get("fecha_agendada")),
        "fecha_cierre": iso_utc(conversation.get("fecha_cierre")),
        "asesor_asignado": conversation.get("asesor_asignado"),
        "pausado_manual": bool(conversation.get("pausado_manual")),
        "cerrado_definitivamente_en": iso_utc(conversation.get("cerrado_definitivamente_en")),
        # Lapso de gracia del cierre definitivo (horas, por negocio): decide en el frontend si
        # "Reabrir caso" pide motivo y si se muestra el banner "El cliente respondió tras el cierre".
        "cierre_gracia_horas": conversation.get("cierre_gracia_horas", CIERRE_GRACIA_HORAS_POR_DEFECTO),
        "revision_prioritaria": bool(conversation.get("revision_prioritaria")),
        "conversation_version": conversation.get("conversation_version"),
        "opportunity_version": conversation.get("opportunity_version"),
        "creado": iso_utc(conversation.get("creado")),
        "actualizado": iso_utc(conversation.get("actualizado")),
        "venta": venta,
        "eventos": [
            {
                "id": e.get("id"), "tipo": e["tipo"], "descripcion": e["descripcion"],
                "autor": e.get("autor"), "creado": e["creado"], "payload": e.get("payload"),
            }
            for e in eventos
        ],
    }


@router.get("/conversation/{conversation_id}")
async def conversation_detalle(conversation_id: str, usuario: dict = Depends(_usuario_actual)):
    """Detalle puntual de una Conversation (activa o cerrada) — REEMPLAZA,
    para la Nueva Experiencia, la rama JSON de `/lead/{telefono}` (Diseño
    Técnico Gate 5.3 §13): mismo contenido que ese DTO (venta + Timeline),
    resuelto desde Opportunity/Conversation/Contact en vez de Lead."""
    conversation = await obtener_conversation_detalle(conversation_id, usuario["negocio_id"])
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversación no encontrada")
    _verificar_acceso_conversation(usuario, conversation["asesor_asignado"])
    lineas = []
    if conversation.get("opportunity_id"):
        lineas = await listar_lineas_venta_por_opportunity(conversation["opportunity_id"], usuario["negocio_id"])
    eventos = await listar_eventos_de_conversation(conversation_id, usuario["negocio_id"])
    dto = _dto_conversation_detalle(conversation, lineas, eventos)
    # P3 (2026-10-06): estado de la ventana de WhatsApp, ADITIVO. Nunca rompe el detalle si falla.
    try:
        dto["ventana_whatsapp"] = await _dto_ventana_whatsapp(conversation["telefono"], usuario["negocio_id"])
    except Exception:
        logger.exception(f"No se pudo calcular el estado de la ventana de la conversación {conversation_id}")
        dto["ventana_whatsapp"] = None
    # De dónde vino y con qué oferta (aditivo; `None` si no se pudo calcular). `campana_origen` es
    # el nombre vigente de la campaña: la ficha del lead lo muestra y este DTO nunca lo traía.
    dto["origen"] = await origen_conversacion.origen_de_conversacion(usuario["negocio_id"], conversation_id)
    dto["campana_origen"] = ((dto["origen"] or {}).get("campana") or {}).get("nombre")
    # 2026-11-09 — etapa derivada del caso (la misma regla del Pipeline, `agent/pipeline_etapas.py`) para el recorrido de la ficha. Necesita
    # `paso_flujo`, que vive en el Lead. ADITIVO: si no se puede calcular el detalle sigue (`null` = la pantalla no dibuja el recorrido).
    try:
        lead_de_etapa = await obtener_lead(conversation["telefono"], negocio_id=usuario["negocio_id"])
        dto["etapa"] = pipeline_etapas.etapa_de(
            conversation.get("resultado"), conversation.get("asesor_asignado"), (lead_de_etapa or {}).get("paso_flujo"),
        )
    except Exception:
        logger.exception(f"No se pudo calcular la etapa de la conversación {conversation_id}")
        dto["etapa"] = None
    return JSONResponse(dto)


@router.get("/conversation/{conversation_id}/timeline")
async def conversation_timeline(conversation_id: str, usuario: dict = Depends(_usuario_actual)):
    """Conversation Timeline de una Conversation puntual — a diferencia de
    `/lead/{telefono}` (que solo puede mostrar el timeline de la Conversation
    ACTIVA vía el puente telefono→Lead), esto sirve el timeline de cualquier
    Conversation, incluida una ya cerrada por DR-4."""
    conversation = await obtener_conversation_detalle(conversation_id, usuario["negocio_id"])
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversación no encontrada")
    _verificar_acceso_conversation(usuario, conversation["asesor_asignado"])
    eventos = await listar_eventos_de_conversation(conversation_id, usuario["negocio_id"])
    return JSONResponse({"eventos": eventos})


# ── Gate 5.3 — cutover real: Opportunity/Conversation como fuente de verdad
# de las 3 escrituras humanas del CRM (Resolución Arquitectónica Gate 5.3,
# Diseño Técnico Gate 5.3 §13). REEMPLAZAN el camino real de
# `/lead/{telefono}/resultado|venta|asignar` — esos endpoints siguen
# existiendo, pero como wrappers delgados que delegan acá (ver más abajo,
# donde están definidos). `negocio_id` siempre de la sesión; el
# `opportunity_id`/`conversation_id` del cliente identifica el recurso, nunca
# autoriza sobre él (§9): primero ownership (404), después rol (403), recién
# ahí se opera.
#
# Mismo contrato de envelope que ya usan Productos y `/lead/{telefono}/...`
# (ver comentario más abajo, junto a `_json_lead_actualizado`):
# {"ok": true, "lead": DTO} en éxito, {"ok": false, "detail": ...,
# "version_actual": N} con 409 en conflicto — la clave sigue llamándose
# "lead" (no "conversacion") a propósito: es el mismo contrato que ya
# entiende `lib/api.ts` (`desenvolver<LeadDetalle>(crudo, "lead")`), renombrar
# la clave no aporta nada y obligaría a tocar código del frontend que no
# necesita cambiar.


async def _json_conversation_actualizada(conversation_id: str, negocio_id: str) -> JSONResponse:
    """Éxito de una escritura sobre Opportunity/Conversation: relee el estado
    YA actualizado (misma razón que `_json_lead_actualizado`: la escritura
    tocó la version, LineaVenta y/o el Timeline; devolver el estado real le
    ahorra un GET al cliente y le da la version nueva)."""
    conversation = await obtener_conversation_detalle(conversation_id, negocio_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversación no encontrada")
    lineas = []
    if conversation.get("opportunity_id"):
        lineas = await listar_lineas_venta_por_opportunity(conversation["opportunity_id"], negocio_id)
    eventos = await listar_eventos_de_conversation(conversation_id, negocio_id)
    return JSONResponse({"ok": True, "lead": _dto_conversation_detalle(conversation, lineas, eventos)})


async def _json_conflicto_opportunity(opportunity_id: str, negocio_id: str) -> JSONResponse:
    actual = await resolver_opportunity_operable(opportunity_id, negocio_id)
    if actual is None:
        raise HTTPException(status_code=404, detail="Opportunity no encontrada")
    return JSONResponse(
        {
            "ok": False,
            "detail": "Alguien más modificó esta conversación mientras la editabas. Revisa los datos actuales antes de volver a guardar.",
            "version_actual": actual["version"],
        },
        status_code=409,
    )


async def _json_conflicto_conversation(conversation_id: str, negocio_id: str) -> JSONResponse:
    actual = await resolver_conversation_operable(conversation_id, negocio_id)
    if actual is None:
        raise HTTPException(status_code=404, detail="Conversación no encontrada")
    return JSONResponse(
        {
            "ok": False,
            "detail": "Alguien más modificó esta conversación mientras la editabas. Revisa los datos actuales antes de volver a guardar.",
            "version_actual": actual["version"],
        },
        status_code=409,
    )


@router.post("/opportunity/{opportunity_id}/resultado")
async def opportunity_resultado(
    opportunity_id: str,
    request: Request,
    resultado: str = Form(""),
    fecha_agendada: str = Form(""),
    version: int = Form(...),
    usuario: dict = Depends(_usuario_actual),
    _csrf: None = Depends(verificar_csrf),
):
    opp = await resolver_opportunity_operable(opportunity_id, usuario["negocio_id"])
    if opp is None:
        raise HTTPException(status_code=404, detail="Opportunity no encontrada")
    _verificar_acceso_conversation(usuario, opp["asesor_asignado"])
    if resultado and resultado not in RESULTADOS:
        raise HTTPException(status_code=400, detail="Resultado inválido")

    # Misma distinción que el endpoint legacy (dashboard.py, actualizar_resultado):
    # "resultado" ausente del formulario = no tocar; presente y vacío = quitarlo.
    formulario = await request.form()
    campos: dict = {}
    if "resultado" in formulario:
        campos["resultado"] = resultado or None
        if resultado != "agendado":
            campos["fecha_agendada"] = None
        elif fecha_agendada:
            try:
                campos["fecha_agendada"] = datetime.fromisoformat(fecha_agendada)
            except ValueError:
                raise HTTPException(status_code=400, detail="Fecha de la cita inválida")
        elif opp.get("resultado") != "agendado":
            # Volver a 'agendado' sin fecha nueva dejaba la fecha vieja de otra
            # cita (o ninguna): un dato huérfano en "Citas" de Inicio.
            raise HTTPException(status_code=400, detail="Indica la fecha y hora de la cita para marcarla como agendada")

    descripcion = (
        f"Cambió el resultado a «{ETIQUETAS_RESULTADO.get(resultado, resultado)}»"
        if resultado else "Quitó el resultado"
    )
    evento = {
        "tipo": "resultado_cambiado", "descripcion": descripcion, "autor": usuario["nombre"],
        "payload": {"campo": "resultado", "anterior": opp.get("resultado"), "nuevo": resultado or None},
    }
    if not await intentar_cambiar_resultado_opportunity(opportunity_id, version, campos, evento=evento):
        return await _json_conflicto_opportunity(opportunity_id, usuario["negocio_id"])
    return await _json_conversation_actualizada(opp["conversation_id"], usuario["negocio_id"])


@router.get("/financiamiento/cuota")
async def financiamiento_cuota_preview(
    monto: float, cuotas: int,
    usuario: dict = Depends(_usuario_actual),
):
    """Gate 2026-09-23 — preview en vivo de la cuota mensual para
    "Registrar venta": antes de guardar nada, el asesor ve cuánto sería el
    pago real con la tasa configurada de este Negocio (nunca una de las 9
    columnas fijas del catálogo, calculada al momento con
    `calcular_cuota_producto`). Cualquier usuario autenticado puede
    pedirlo — no expone nada que ya no vea en "Registrar venta"."""
    if monto <= 0:
        raise HTTPException(status_code=400, detail="El monto debe ser mayor a cero")
    calculo = await calcular_cuota_producto(monto, usuario["negocio_id"], cuotas)
    if calculo is None:
        raise HTTPException(status_code=400, detail=f"Cuotas debe ser un número entre {CUOTAS_MIN} y {CUOTAS_MAX}")
    return JSONResponse({"ok": True, **calculo})


@router.post("/opportunity/{opportunity_id}/venta")
async def opportunity_venta(
    opportunity_id: str,
    lineas_venta: str = Form("[]"),
    modalidad_pago: str = Form(""),
    cuotas: str = Form(""),
    medio_pago: str = Form(""),
    version: int = Form(...),
    usuario: dict = Depends(_usuario_actual),
    _csrf: None = Depends(verificar_csrf),
):
    opp = await resolver_opportunity_operable(opportunity_id, usuario["negocio_id"])
    if opp is None:
        raise HTTPException(status_code=404, detail="Opportunity no encontrada")
    _verificar_acceso_conversation(usuario, opp["asesor_asignado"])

    try:
        venta = servicio_comercial.validar_venta(lineas_venta, modalidad_pago, cuotas, medio_pago)
        await servicio_comercial.validar_productos_de_venta(venta, usuario["negocio_id"])
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    pacto = await servicio_comercial.calcular_pacto_financiamiento(venta, usuario["negocio_id"], previo=opp)
    campos: dict = {
        "modalidad_pago": venta["modalidad_pago"], "cuotas": venta["cuotas"], "medio_pago": venta["medio_pago"],
        **pacto,
    }
    if venta["lineas"]:
        campos["resultado"] = "vendido"
        # Una venta cierra la cita: sin esto la fecha quedaba huérfana en Lead y
        # Opportunity (aparecía en "Citas" si el resultado volvía a 'agendado').
        campos["fecha_agendada"] = None

    evento = {
        "tipo": "venta_registrada",
        "descripcion": f"Registró una venta ({len(venta['lineas'])} producto(s), {venta['modalidad_pago'] or 'sin modalidad'})",
        "autor": usuario["nombre"],
        "payload": {
            "lineas_venta": venta["lineas"], "modalidad_pago": venta["modalidad_pago"],
            "cuotas": venta["cuotas"], "medio_pago": venta["medio_pago"],
            "cuota_pactada": pacto["cuota_pactada"],
        },
    }
    ok = await cerrar_opportunity_con_venta(
        opportunity_id, version, venta["lineas"], campos,
        revertir_resultado_al_vaciar=True, evento=evento,
    )
    if not ok:
        return await _json_conflicto_opportunity(opportunity_id, usuario["negocio_id"])
    return await _json_conversation_actualizada(opp["conversation_id"], usuario["negocio_id"])


@router.post("/conversation/{conversation_id}/asignar")
async def conversation_asignar(
    conversation_id: str,
    asesor_asignado: str = Form(""),
    version: int = Form(...),
    usuario: dict = Depends(servicio_identidad.requiere_rol(*ROLES_CON_VISION_TOTAL)),
    _csrf: None = Depends(verificar_csrf),
):
    conv = await resolver_conversation_operable(conversation_id, usuario["negocio_id"])
    if conv is None:
        raise HTTPException(status_code=404, detail="Conversación no encontrada")

    anterior = conv["asesor_asignado"]
    evento = None
    if asesor_asignado:
        asesor_info = await obtener_usuario(asesor_asignado, negocio_id=usuario["negocio_id"])
        nombre_asesor = asesor_info["nombre"] if asesor_info else asesor_asignado
        evento = {
            "tipo": "asignado", "descripcion": f"Asignó la conversación a {nombre_asesor}", "autor": usuario["nombre"],
            "payload": {"campo": "asesor_asignado", "anterior": anterior, "nuevo": asesor_asignado},
        }
    elif anterior:
        # "Sin asignar" (value="") es una decisión explícita del supervisor —
        # mismo criterio que el endpoint legacy (dashboard.py, asignar_lead).
        asesor_info = await obtener_usuario(anterior, negocio_id=usuario["negocio_id"])
        nombre_anterior = asesor_info["nombre"] if asesor_info else anterior
        evento = {
            "tipo": "desasignado", "descripcion": f"Quitó la asignación de {nombre_anterior}", "autor": usuario["nombre"],
            "payload": {"campo": "asesor_asignado", "anterior": anterior, "nuevo": None},
        }

    if not await intentar_asignar_conversation(conversation_id, version, asesor_asignado or None, evento=evento):
        return await _json_conflicto_conversation(conversation_id, usuario["negocio_id"])
    return await _json_conversation_actualizada(conversation_id, usuario["negocio_id"])


@router.post("/conversation/{conversation_id}/liberar")
async def conversation_liberar(
    conversation_id: str,
    usuario: dict = Depends(_usuario_actual),
    _csrf: None = Depends(verificar_csrf),
):
    """Devuelve el control a Gabi — equivalente Conversation-first de
    `/lead/{telefono}/reactivar-gabi`. Sin chequeo de `version`: el endpoint
    legacy nunca lo tuvo (es un efecto de un clic, no un formulario con datos
    que puedan chocar) — mismo contrato real, no uno más estricto inventado
    acá (cutover real §2)."""
    conv = await resolver_conversation_operable(conversation_id, usuario["negocio_id"])
    if conv is None:
        raise HTTPException(status_code=404, detail="Conversación no encontrada")
    _verificar_acceso_conversation(usuario, conv["asesor_asignado"])

    telefono = await liberar_asignacion_via_conversation(conversation_id, usuario["negocio_id"], autor=usuario["nombre"])
    if telefono is None:
        raise HTTPException(status_code=400, detail="Esta conversación ya está vendida — no se puede reactivar a Gabi desde acá")
    return await _json_conversation_actualizada(conversation_id, usuario["negocio_id"])


@router.post("/conversation/{conversation_id}/cerrar-definitivamente")
async def conversation_cerrar_definitivamente(
    conversation_id: str,
    usuario: dict = Depends(_usuario_actual),
    _csrf: None = Depends(verificar_csrf),
):
    """Cierre EXPLÍCITO manual (Gate 2026-09-23) — separado de `resultado`:
    marca que este caso NO vuelve, así que si el cliente escribe de nuevo,
    Gabi retoma sola en vez de quedar mostrando "asignado a X" para
    siempre sobre un caso que en la práctica ya murió. No hace nada por sí
    solo más allá de esa marca — ver `agent/main.py` para el efecto real
    y `agent/memory.py::cerrar_lead_definitivamente` para las
    validaciones (resultado ya cerrado).

    Punto 3 (2026-09-28): "vendido" ya no está excluido acá — si el cliente
    vuelve a escribir, `agent/main.py` lo rutea en silencio al mismo asesor
    que hizo la venta (nunca a Gabi, ver `enrutar_posventa_si_corresponde`).

    Mismo patrón que `/conversation/{id}/liberar` (Conversation-first, sin
    chequeo de `version` — un clic, no un formulario)."""
    conv = await resolver_conversation_operable(conversation_id, usuario["negocio_id"])
    if conv is None:
        raise HTTPException(status_code=404, detail="Conversación no encontrada")
    _verificar_acceso_conversation(usuario, conv["asesor_asignado"])

    telefono = await cerrar_lead_definitivamente_via_conversation(conversation_id, usuario["negocio_id"], usuario["nombre"])
    if telefono is None:
        raise HTTPException(
            status_code=400,
            detail="Solo se puede cerrar definitivamente un caso con resultado ya cerrado.",
        )
    return await _json_conversation_actualizada(conversation_id, usuario["negocio_id"])


@router.post("/conversation/{conversation_id}/atendido")
async def conversation_atendido(
    conversation_id: str,
    motivo: str = Form(""),
    usuario: dict = Depends(_usuario_actual),
    _csrf: None = Depends(verificar_csrf),
):
    """"Ya lo atendí" (R4, 2026-10-07): la persona ya gestionó este caso fuera del chat (llamó, lo vio
    en persona…) y no hay nada que contestar por WhatsApp. Registra el evento `atendido_manual`
    (autor + `motivo` opcional, máx. `MOTIVO_ATENDIDO_MAXIMO` caracteres) y el cliente sale de "esperando"
    hasta que vuelva a escribir. Mismos permisos que `cerrar-definitivamente`: el asesor asignado,
    supervisor o admin (404 si la conversación no existe o es de otro negocio, 403 si no es suya).
    Idempotente: repetirlo sin un mensaje nuevo del cliente no agrega otro evento. No cambia el
    resultado, la asignación ni a Gabi. Responde `{"ok": true}`."""
    if not isinstance(motivo, str):   # llamada directa sin el campo (los tests): el default de Form
        motivo = ""
    motivo = motivo.strip()
    if len(motivo) > MOTIVO_ATENDIDO_MAXIMO:
        raise HTTPException(status_code=400, detail=f"El motivo no puede pasar de {MOTIVO_ATENDIDO_MAXIMO} caracteres.")
    conv = await resolver_conversation_operable(conversation_id, usuario["negocio_id"])
    if conv is None:
        raise HTTPException(status_code=404, detail="Conversación no encontrada")
    _verificar_acceso_conversation(usuario, conv["asesor_asignado"])

    estado = await registrar_atendido_manual(conversation_id, usuario["negocio_id"], usuario["nombre"], motivo)
    if estado == "no_encontrada":
        raise HTTPException(status_code=404, detail="Conversación no encontrada")
    if estado == "motivo_largo":
        raise HTTPException(status_code=400, detail=f"El motivo no puede pasar de {MOTIVO_ATENDIDO_MAXIMO} caracteres.")
    return JSONResponse({"ok": True})


@router.post("/conversation/{conversation_id}/reabrir")
async def conversation_reabrir(
    conversation_id: str,
    motivo: str = Form(""),
    usuario: dict = Depends(_usuario_actual),
    _csrf: None = Depends(verificar_csrf),
):
    """Botón "Reabrir caso" (Q3, 2026-10-07): deshace un cierre definitivo que
    fue un error. Limpia el cierre en Lead y Conversation y CONSERVA asesor,
    resultado y mensajes; Gabi queda como estaba.

    Lapso de gracia (`cierre_gracia_horas`, default 24 h): DENTRO del lapso, mismos
    permisos que `cerrar-definitivamente` (cualquiera que pueda operar la conversación) y
    el `motivo` es opcional. PASADO el lapso, solo admin o supervisor (403 si no) y el
    `motivo` es obligatorio (400 si falta; máx. 300 caracteres), y queda en el evento
    `cierre_deshecho` y en la auditoría. 409 si el cierre ya no se puede deshacer porque el
    cliente reabrió el caso por su cuenta (hay una conversación más nueva) o si el caso ya
    estaba abierto."""
    if not isinstance(motivo, str):   # llamada directa sin el campo (los tests): el default de Form
        motivo = ""
    motivo = motivo.strip()
    if len(motivo) > MOTIVO_REABRIR_MAXIMO:
        raise HTTPException(status_code=400, detail=f"El motivo no puede pasar de {MOTIVO_REABRIR_MAXIMO} caracteres.")
    conv = await resolver_conversation_operable(conversation_id, usuario["negocio_id"])
    if conv is None:
        raise HTTPException(status_code=404, detail="Conversación no encontrada")
    _verificar_acceso_conversation(usuario, conv["asesor_asignado"])

    estado = await reabrir_caso_cerrado(
        conversation_id, usuario["negocio_id"], usuario["nombre"], rol=usuario["rol"], motivo=motivo,
    )
    if estado == "no_encontrada":
        raise HTTPException(status_code=404, detail="Conversación no encontrada")
    if estado == "sustituida":
        raise HTTPException(
            status_code=409,
            detail="El cliente ya reabrió este caso por su cuenta: esta conversación quedó en el historial y no hay un cierre que deshacer.",
        )
    if estado == "no_cerrada":
        raise HTTPException(status_code=409, detail="Este caso no está cerrado definitivamente.")
    if estado == "sin_permiso_fuera_de_lapso":
        raise HTTPException(
            status_code=403,
            detail="Pasado el lapso de gracia del cierre, solo un administrador o supervisor puede reabrir el caso.",
        )
    if estado == "motivo_requerido":
        raise HTTPException(
            status_code=400, detail="Escribe el motivo para reabrir el caso: pasó más tiempo que el lapso de gracia del cierre.",
        )
    if estado == "motivo_largo":
        raise HTTPException(status_code=400, detail=f"El motivo no puede pasar de {MOTIVO_REABRIR_MAXIMO} caracteres.")
    return await _json_conversation_actualizada(conversation_id, usuario["negocio_id"])


COLUMNAS_EXPORTACION = [
    "telefono", "nombre", "interes", "producto_tipo", "producto_marca", "producto_modalidad",
    "paso_flujo", "estado_conversacion", "resultado", "asesor_asignado", "producto_vendido",
    "precio_venta", "modalidad_pago", "cuotas", "medio_pago", "campana_origen", "creado", "actualizado",
]


def _filas_exportacion(leads: list[dict]) -> list[list[str]]:
    """Una fila por lead con TODOS los campos relevantes (mismo orden que
    COLUMNAS_EXPORTACION) — la usan tanto el export a CSV como a Excel, para
    que no se desalineen entre sí si se agrega una columna más adelante."""
    return [
        [
            lead.get("telefono") or "", lead.get("nombre") or "", lead.get("interes") or "",
            lead.get("producto_tipo") or "", lead.get("producto_marca") or "", lead.get("producto_modalidad") or "",
            lead.get("paso_flujo") or "", _estado_conversacion(lead), lead.get("resultado") or "",
            lead.get("asesor_asignado") or "", lead.get("producto_vendido") or "", lead.get("precio_venta") or "",
            lead.get("modalidad_pago") or "", lead.get("cuotas") or "", lead.get("medio_pago") or "",
            lead.get("campana_origen") or "", lead["creado"].strftime("%Y-%m-%d %H:%M"),
            lead["actualizado"].strftime("%Y-%m-%d %H:%M"),
        ]
        for lead in leads
    ]


async def _auditar_exportacion_leads(usuario: dict, formato: str, filas: int) -> None:
    """Deja constancia en `RegistroAuditoria` de cada exportación de leads (CSV o Excel): quién (`actor`), con qué rol,
    en qué formato, cuántas filas y con qué filtros. Sin PII en el payload (ni teléfonos ni nombres). Si no se puede
    dejar constancia, la exportación NO se entrega (misma regla que los cambios de configuración)."""
    await mem.registrar_auditoria(
        "leads_exportados", actor=usuario.get("username"), negocio_id=usuario["negocio_id"], entidad_tipo="exportacion",
        payload={
            "actor_rol": usuario.get("rol"), "formato": formato, "filas": filas,
            "filtros": {"alcance": "todos_los_leads_del_negocio"},   # la exportación no admite filtros: siempre son todos
        },
    )


@router.get("/metricas/exportar.csv")
async def exportar_metricas_csv(usuario: dict = Depends(servicio_identidad.requiere_rol(*ROLES_CON_VISION_TOTAL))):
    import csv
    import io

    leads = await _adjuntar_resumen_ventas(await listar_leads(usuario["negocio_id"]), usuario["negocio_id"])
    await _auditar_exportacion_leads(usuario, "csv", len(leads))
    buffer = io.StringIO()
    escritor = csv.writer(buffer)
    escritor.writerow(COLUMNAS_EXPORTACION)
    escritor.writerows(_filas_exportacion(leads))

    nombre_archivo = f"leads_gaso_plus_{datetime.now().strftime('%Y%m%d_%H%M')}.csv"
    return Response(
        content=buffer.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{nombre_archivo}"'},
    )


@router.get("/metricas/exportar.xlsx")
async def exportar_metricas_xlsx(usuario: dict = Depends(servicio_identidad.requiere_rol(*ROLES_CON_VISION_TOTAL))):
    import io
    from openpyxl import Workbook
    from openpyxl.styles import Font

    leads = await _adjuntar_resumen_ventas(await listar_leads(usuario["negocio_id"]), usuario["negocio_id"])
    filas = _filas_exportacion(leads)
    await _auditar_exportacion_leads(usuario, "xlsx", len(filas))
    libro = Workbook()
    hoja = libro.active
    hoja.title = "Leads"

    hoja.append(COLUMNAS_EXPORTACION)
    for celda in hoja[1]:
        celda.font = Font(bold=True)
    for fila in filas:
        hoja.append(fila)

    # Ancho de columna aproximado al contenido más largo de esa columna,
    # para que se pueda leer sin tener que ajustar manualmente en Excel.
    for i, columna in enumerate(COLUMNAS_EXPORTACION, start=1):
        letra = hoja.cell(row=1, column=i).column_letter
        ancho_maximo = max(
            (len(str(valor)) for valor in [columna] + [fila[i - 1] for fila in filas]),
            default=10,
        )
        hoja.column_dimensions[letra].width = min(ancho_maximo + 2, 40)

    buffer = io.BytesIO()
    libro.save(buffer)
    buffer.seek(0)

    nombre_archivo = f"leads_gaso_plus_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx"
    return Response(
        content=buffer.getvalue(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{nombre_archivo}"'},
    )


# ── Inicio (MAIEK_AI_PRODUCT_PATTERNS.md, Cap. 3) ──────────────────────

def _kpi_card(numero, etiqueta: str) -> str:
    """KPI Card del CDS — el número es el protagonista, nunca más de 8 en
    una franja (regla ya fijada por el propio componente)."""
    return (
        f'<div class="kpi-card">'
        f'<div class="kpi-numero">{numero}</div>'
        f'<div class="kpi-etiqueta">{html.escape(etiqueta)}</div>'
        f'</div>'
    )


def _item_zona_accion(telefono: str, nombre: str, motivo: str) -> str:
    """Un ítem de la Zona de acción — lleva directo a esa conversación
    específica dentro de la Bandeja (Cap. 2), nunca a la lista completa."""
    return (
        f'<a href="/dashboard/lead/{html.escape(telefono)}" data-ajax="1" class="zona-accion-item">'
        f'{_avatar(nombre or telefono, 40)}'
        f'<div><div class="nombre">{html.escape(nombre or telefono)}</div>'
        f'<div class="motivo">{html.escape(motivo)}</div></div>'
        f'</a>'
    )


def _zona_accion_vacia(mensaje: str) -> str:
    return f'<div class="zona-accion-vacio">{html.escape(mensaje)}</div>'


# ── Inicio (Nueva Experiencia — GATE 3.1) ───────────────────────────────
#
# Las funciones de abajo (`_zona_accion_*_datos`, `_zona_indicadores_*_datos`)
# son la versión estructurada (JSON, sin HTML) de las funciones de arriba
# (`_zona_accion_asesor`, `_zona_accion_admin`, `_zona_indicadores_asesor`,
# `_zona_indicadores_admin`) — MISMA lógica de negocio (mismo orden, mismos
# límites 5+3, mismos filtros), deliberadamente NO refactorizadas para
# compartir código con esas: el legacy HTML queda intacto, byte a byte, sin
# ningún riesgo de regresión (Gate 3.0 §Q, "garantiza que Legacy conserve
# exactamente su comportamiento actual"). Único agregado real: resuelven
# `conversation_id` en bloque (mismo patrón que `listar_leads_pipeline`,
# Gate 5.3 §8) para que cada ítem pueda navegar a la Nueva Experiencia, no
# solo al panel legacy.


# ── Inicio verdadero (paquete B, 2026-10-05) ───────────────────────────
#
# Contrato ADITIVO de `GET /dashboard/inicio.json`: los campos de siempre
# (`vision_total`, `zona_accion.{vacio,mensaje_vacio,items[{telefono,
# conversation_id,nombre,motivo}]}`, `zona_indicadores[{valor,etiqueta}]`) se
# conservan; se agregan `categoria` (y datos de ventana de Meta) en cada
# ítem, `zona_accion.totales` y `avisos`.
#
# "Cliente esperando" ya no es `pausado_manual`: es una conversación activa
# cuyo último mensaje real es del cliente y nadie respondió después, con un
# asesor/supervisión de por medio (ver `memory.listar_clientes_esperando`).
# Aplica a cualquier resultado, incluido vendido y agendado.

# R4 (2026-10-07): `cliente_esperando` (8) es SOLO el grupo "Responde ahora" (ventana de 24 h abierta);
# `cliente_esperando_ventana_cerrada` (5) es el grupo secundario "Con ventana cerrada" (clave aditiva).
TOPES_ZONA_ACCION = {
    "escalados": 5, "sin_asesor": 5, "cliente_esperando": 8, "cliente_esperando_ventana_cerrada": 5,
    "citas_proximas": 3, "citas_vencidas": 3,
    "llamar": 5,   # "Para llamar" (2026-10-09, agent/llamadas.py): tareas de llamada accionables
}
# fecha_agendada se guarda como hora local de Lima, SIN zona (la tipea un
# humano en un datetime-local) — para compararla con "ahora" hay que llevar
# "ahora" a Lima (UTC-5, sin horario de verano). Un instante UTC (Mensaje.
# timestamp) NO se mueve: va con iso_utc.
_OFFSET_LIMA = timedelta(hours=5)
# Un solo umbral para «ventana por vencer» y «Última llamada» (decisión del dueño, 2026-10-12): la clave configurable
# `atencion_ultima_llamada_horas` (ver `atencion_atrasada.obtener_umbrales`). Esta constante es solo el valor por defecto (6 h).
_VENTANA_POR_VENCER = timedelta(hours=atencion_atrasada.UMBRALES_POR_DEFECTO["ultima_llamada"])
# La campana avisa de clientes con la ventana de WhatsApp abierta o cerrada hace
# menos de estas horas; un cliente que dejó de escribir hace días sigue en
# Inicio pero ya no suma al badge.
HORAS_CAMPANA_VENTANA_CERRADA = 72
_MENSAJE_VACIO_ASESOR = "No tienes conversaciones que requieran tu atención ahora mismo."
_MENSAJE_VACIO_ADMIN = "El equipo no tiene conversaciones que requieran tu intervención ahora mismo."
_RUTA_USO = "/configuracion/uso"


def _texto_cita(lead: dict, prefijo: str) -> str:
    fecha = lead["fecha_agendada"].strftime("%d/%m %H:%M") if lead.get("fecha_agendada") else "sin hora"
    return f"{prefijo} — {fecha}"


def _item_zona(lead: dict, motivo: str, categoria: str) -> dict:
    return {
        "telefono": lead["telefono"], "conversation_id": lead.get("conversation_id"),
        "nombre": lead.get("nombre"), "motivo": motivo, "categoria": categoria,
    }


def _producto_legible(lead: dict) -> str | None:
    """«Terma Rheem», «Cocina»… a partir de `producto_tipo` / `producto_marca` (los datos que ya extrae Gabi). None si
    ninguno es un dato real (se ignoran los «null» / «desconocido» que a veces devuelve el modelo)."""
    tipo = lead.get("producto_tipo")
    marca = lead.get("producto_marca")
    partes = []
    if llamadas.dato_conocido(tipo):
        partes.append(tipo.strip().capitalize())
    if llamadas.dato_conocido(marca):
        partes.append(marca.strip())
    return " ".join(partes) or None


def _item_cita(lead: dict, motivo: str, categoria: str, vista_admin: bool = False) -> dict:
    """Ítem de cita. Aditivo (Inicio nuevo, 2026-10-12): `cita_en`, el instante de la cita en UTC con `Z`
    (`fecha_agendada` es hora de Lima sin zona: se lleva a UTC sumando el offset). None si la cita no tiene hora.

    Aditivos (2026-10-13, «Mi día»): `producto` legible (tipo + marca; None si no se sabe) y, solo en la vista
    admin/supervisor, `asesor` (a quién le toca la llamada; igual que `_item_cliente_esperando`). Una cita es una LLAMADA
    PROGRAMADA con el cliente: no lleva dirección, zona ni tipo de visita."""
    item = _item_zona(lead, motivo, categoria)
    fecha = lead.get("fecha_agendada")
    item["cita_en"] = iso_utc(fecha + _OFFSET_LIMA) if fecha else None
    item["producto"] = _producto_legible(lead)
    if vista_admin:
        item["asesor"] = lead.get("asesor_asignado")
    return item


def _item_cliente_esperando(cliente: dict, vista_admin: bool) -> dict:
    asesor = cliente.get("asesor_asignado")
    item = _item_zona(
        cliente,
        f"Esperando respuesta — {asesor or 'sin asesor'}" if vista_admin else "Esperando tu respuesta",
        "cliente_esperando",
    )
    item.update({
        "ultimo_mensaje_cliente_en": iso_utc(cliente["ultimo_mensaje_cliente_en"]),
        "ventana_vence_en": iso_utc(cliente["ventana_vence_en"]),
        "ventana_abierta": cliente["ventana_abierta"],
        "probable_cierre": cliente["probable_cierre"],
        "resultado": cliente.get("resultado"),
        # Aditivo (R4, 2026-10-07): a qué grupo de Inicio pertenece — "Responde ahora" (ventana abierta)
        # o "Con ventana cerrada" (llamar o enviar plantilla).
        "grupo": "responde_ahora" if cliente["ventana_abierta"] else "ventana_cerrada",
    })
    if cliente.get("atencion") is not None:
        # Aditivo (2026-10-07, Atención atrasada): {nivel, edad_horas, ventana_restante_horas}.
        item["atencion"] = cliente["atencion"]
    if vista_admin:
        item["asesor"] = asesor
    return item


# Una cita vencida sin cerrar solo se ofrece en Inicio durante esta ventana;
# las más viejas ya no son "pendientes del día": se cuentan aparte
# (`totales.citas_vencidas_antiguas`) para que no desaparezcan sin dejar rastro.
DIAS_CITA_VENCIDA_VIGENTE = 7


# Tope de citas de HOY que se envían además de las 3 de siempre (no se pierden filas del día, pero tampoco se manda
# una lista sin fin si alguien agenda decenas en un día).
TOPE_CITAS_HOY_EXTRA = 12


def _con_citas_de_hoy(citas: list[dict], tope: int, hoy_lima) -> list[dict]:
    """Las primeras `tope` citas (el orden ya viene dado) más las demás cuyo DÍA en Lima es hoy, hasta
    `TOPE_CITAS_HOY_EXTRA` extra. Conserva el orden de `citas`."""
    resto_de_hoy = [l for l in citas[tope:] if l["fecha_agendada"].date() == hoy_lima][:TOPE_CITAS_HOY_EXTRA]
    return citas[:tope] + resto_de_hoy


def _contar_citas_hoy(con_fecha: list[dict], ahora_lima: datetime) -> int:
    """Citas cuyo DÍA en Lima es hoy (Tira de acción de Inicio, 2026-10-13, `totales.citas_hoy`).

    Definición: leads con cita viva (`listar_leads_agendados` ya descarta los cerrados definitivamente y los que dejaron
    de estar 'agendado') cuya `fecha_agendada` (hora local de Lima, sin zona) cae en el mismo día calendario que
    `ahora_lima`. Cuenta las de hoy que todavía no empiezan Y las de hoy que ya pasaron y siguen sin cerrar (siguen
    siendo trabajo del día: hay que cerrarlas o reprogramarlas). NO cuenta las vencidas de días anteriores (esas siguen
    en `citas_vencidas`) ni las de mañana en adelante. El día se corta a medianoche de Lima (UTC-5), no de UTC."""
    hoy = ahora_lima.date()
    return sum(1 for l in con_fecha if l["fecha_agendada"].date() == hoy)


async def _citas_inicio_detalle(
    negocio_id: str, asesor: str | None, ahora_utc: datetime,
) -> tuple[list, list, int, int, int]:
    """(próximas, vencidas de los últimos 7 días, cuántas próximas en 7 días,
    cuántas vencidas MÁS antiguas, cuántas citas son de HOY en Lima). Próximas: la más cercana primero (antes
    mostraba las 3 más VIEJAS). Vencidas: la fecha ya pasó y el lead sigue
    'agendado' (nadie la cerró) — la más reciente primero. Un lead cerrado
    definitivamente ya no entra (lo filtra `listar_leads_agendados`)."""
    agendados = await listar_leads_agendados(negocio_id, asesor_asignado=asesor)
    ahora_lima = ahora_utc - _OFFSET_LIMA
    limite_vencidas = ahora_lima - timedelta(days=DIAS_CITA_VENCIDA_VIGENTE)
    con_fecha = [l for l in agendados if l.get("fecha_agendada")]
    proximas = sorted((l for l in con_fecha if l["fecha_agendada"] >= ahora_lima), key=lambda l: l["fecha_agendada"])
    vencidas_todas = [l for l in con_fecha if l["fecha_agendada"] < ahora_lima]
    vencidas = sorted(
        (l for l in vencidas_todas if l["fecha_agendada"] >= limite_vencidas),
        key=lambda l: l["fecha_agendada"], reverse=True,
    )
    en_7_dias = sum(1 for l in proximas if l["fecha_agendada"] <= ahora_lima + timedelta(days=7))
    return proximas, vencidas, en_7_dias, len(vencidas_todas) - len(vencidas), _contar_citas_hoy(con_fecha, ahora_lima)


async def _citas_vencidas_antiguas(negocio_id: str, asesor: str | None, ahora_utc: datetime) -> list[dict]:
    """Citas vencidas sin cerrar de hace MÁS de `DIAS_CITA_VENCIDA_VIGENTE` días (las que Inicio solo cuenta en
    `totales.citas_vencidas_antiguas`), la más reciente primero. Es la lista de la vista `citas_vencidas_antiguas`."""
    limite = ahora_utc - _OFFSET_LIMA - timedelta(days=DIAS_CITA_VENCIDA_VIGENTE)
    agendados = await listar_leads_agendados(negocio_id, asesor_asignado=asesor)
    return sorted(
        (l for l in agendados if l.get("fecha_agendada") and l["fecha_agendada"] < limite),
        key=lambda l: l["fecha_agendada"], reverse=True,
    )


async def _citas_inicio(negocio_id: str, asesor: str | None, ahora_utc: datetime) -> tuple[list, list, int]:
    """(próximas, vencidas de los últimos 7 días, cuántas en los próximos 7
    días). Misma firma de siempre; ver `_citas_inicio_detalle` para el conteo
    de las vencidas más antiguas."""
    proximas, vencidas, en_7_dias, _antiguas, _hoy = await _citas_inicio_detalle(negocio_id, asesor, ahora_utc)
    return proximas, vencidas, en_7_dias


async def _llamadas_activo(negocio_id: str) -> bool:
    """¿«Para llamar» está encendido y en modo efectivo `activo`? Nunca lanza: Inicio no puede romperse por esto."""
    try:
        return (await llamadas.modo_efectivo(negocio_id)) == llamadas.MODO_ACTIVO
    except Exception:  # noqa: BLE001
        logger.exception("Para llamar: no se pudo leer el modo efectivo para Inicio")
        return False


async def _zona_accion_datos(negocio_id: str, asesor: str | None, vista_admin: bool) -> dict:
    """Zona de acción de Inicio. `asesor` acota a los leads de ese asesor
    (vista Asesor); la vista admin/supervisor ve el negocio completo y suma
    los que están sin asesor / escalados a supervisión."""
    ahora = datetime.utcnow()
    esperando = await listar_clientes_esperando(negocio_id, asesor=asesor, ahora=ahora)
    # Atención atrasada (2026-10-07): cada cliente esperando trae `atencion` {nivel, edad_horas,
    # ventana_restante_horas}. Los más graves van primero (orden estable: dentro de un mismo nivel se
    # conserva el de siempre) para que entren en el tope de ítems de Inicio.
    await atencion_atrasada.anotar_atencion(negocio_id, esperando, ahora)
    # Calendario de negocio (2026-10-12): hoy cerrado por feriado/día especial = pausa de los relojes de atención.
    pausa = await atencion_atrasada.pausa_de_atencion(negocio_id, ahora)
    # Umbral único de «ventana por vencer» = «Última llamada» (configurable, 6 h por defecto).
    umbral_ventana_horas = (await atencion_atrasada.obtener_umbrales(negocio_id))["ultima_llamada"]
    umbral_ventana = timedelta(hours=umbral_ventana_horas)
    esperando.sort(key=lambda c: -atencion_atrasada.gravedad(c))
    atencion_por_telefono = {c["telefono"]: c["atencion"] for c in esperando}
    proximas, vencidas, citas_7_dias, vencidas_antiguas, citas_hoy = await _citas_inicio_detalle(negocio_id, asesor, ahora)

    escalados: list[dict] = []
    sin_asesor: list[dict] = []
    if vista_admin:
        esperando_asignar = await listar_leads_esperando_asesor(negocio_id)
        # 2026-10-04: los que ningún asesor atendió (pasaron a la cola de
        # supervisión) van primero y con su propio motivo — Gabi no los
        # retoma, así que si el supervisor no los trata, nadie lo hace.
        escalados = [l for l in esperando_asignar if l.get("escalado_supervision_en")]
        sin_asesor = [l for l in esperando_asignar if not l.get("escalado_supervision_en")]

    pares: list[tuple[dict, dict]] = []   # (lead_o_cliente, item sin conversation_id resuelto)
    mostrados: set[str] = set()
    for l in escalados[:TOPES_ZONA_ACCION["escalados"]]:
        item_escalado = _item_zona(l, "Escalado a supervisión — ningún asesor respondió", "escalado")
        # Aditivo (Inicio nuevo, 2026-10-12): desde cuándo está en la cola de supervisión (ordena los escalados).
        item_escalado["escalado_en"] = iso_utc(l["escalado_supervision_en"])
        pares.append((l, item_escalado))
        mostrados.add(l["telefono"])
    for l in sin_asesor[:TOPES_ZONA_ACCION["sin_asesor"]]:
        pares.append((l, _item_zona(l, "Sin asesor asignado", "sin_asesor")))
        mostrados.add(l["telefono"])
    # Un mismo cliente no aparece dos veces (escalado/sin asesor ya lo cubren). R4 (2026-10-07): dos
    # grupos, cada uno con su tope — "Responde ahora" (ventana abierta, por gravedad) y "Con ventana
    # cerrada" (del más reciente al más antiguo, que es el orden en que `listar_clientes_esperando` los
    # entrega y la gravedad 0 de todos conserva).
    por_mostrar = [c for c in esperando if c["telefono"] not in mostrados]
    for c in [c for c in por_mostrar if c["ventana_abierta"]][:TOPES_ZONA_ACCION["cliente_esperando"]]:
        pares.append((c, _item_cliente_esperando(c, vista_admin)))
    for c in [c for c in por_mostrar if not c["ventana_abierta"]][:TOPES_ZONA_ACCION["cliente_esperando_ventana_cerrada"]]:
        pares.append((c, _item_cliente_esperando(c, vista_admin)))
    # Las citas de HOY no se topan (se «pinean» en Inicio, 2026-10-13): además de las 3 de siempre se envían las demás de hoy
    # (hasta `TOPE_CITAS_HOY_EXTRA`). Las de otros días conservan el tope.
    hoy_lima = (ahora - _OFFSET_LIMA).date()
    for l in _con_citas_de_hoy(proximas, TOPES_ZONA_ACCION["citas_proximas"], hoy_lima):
        pares.append((l, _item_cita(l, _texto_cita(l, "Cita agendada"), "cita", vista_admin)))
    for l in _con_citas_de_hoy(vencidas, TOPES_ZONA_ACCION["citas_vencidas"], hoy_lima):
        pares.append((l, _item_cita(l, _texto_cita(l, "Cita vencida sin cerrar"), "cita_vencida", vista_admin)))
    # Aditivo (2026-10-09, "Para llamar"): las tareas de llamada accionables de este usuario (o de todo el negocio en la
    # vista admin/supervisor), las vencidas primero. Con el módulo apagado, en sombra o sin aceptación vigente no hay
    # ningún ítem y los dos totales valen 0: el contrato de siempre no cambia.
    llamar = await llamadas.datos_para_inicio(negocio_id, asesor, ahora, tope=TOPES_ZONA_ACCION["llamar"])
    for t in llamar["items"]:
        item = _item_zona(t, "Para llamar — sin hacer a tiempo" if t["vencida"] else "Para llamar", "llamar")
        item.update({
            "tarea_id": t["tarea_id"], "segmento": t["segmento"], "vencida": t["vencida"], "asesor": t["asesor"],
            "programada_para": t["programada_para"],
        })
        pares.append((t, item))

    abiertas = [c for c in esperando if c["ventana_abierta"]]
    # Aditivo — alimenta SOLO el badge de la campana: ventana abierta o cerrada
    # hace menos de HORAS_CAMPANA_VENTANA_CERRADA (los demás siguen en Inicio).
    para_campana = [
        c for c in esperando
        if c["ventana_abierta"] or ahora - c["ventana_vence_en"] < timedelta(hours=HORAS_CAMPANA_VENTANA_CERRADA)
    ]
    totales = {
        "cliente_esperando": len(esperando),
        "ventana_abierta": len(abiertas),
        # Aditivos (R4, 2026-10-07): el total de cada grupo de Inicio ("Responde ahora" / "Con ventana
        # cerrada"); suman `cliente_esperando`. Un cliente escalado/sin asesor también cuenta aquí.
        "esperando_ventana_abierta": len(abiertas),
        "esperando_ventana_cerrada": len(esperando) - len(abiertas),
        # Casos DISTINTOS de "Responde ahora" con ventana abierta (escalados + sin asesor + esperando con
        # la ventana abierta) — es el total que lleva la vista `responde_ahora` de la Bandeja.
        "responde_ahora_total": len(
            {l["telefono"] for l in escalados} | {l["telefono"] for l in sin_asesor} | {c["telefono"] for c in abiertas}
        ),
        # Con la pausa vigente la campana no suma «clientes esperando»: la entrada informativa de `avisos` lo explica.
        "esperando_campana": 0 if pausa is not None else len(para_campana),
        "ventana_por_vencer": sum(1 for c in abiertas if c["ventana_vence_en"] - ahora < umbral_ventana),
        # Aditivo: el umbral (en horas) con el que se cuenta lo anterior; el mismo de la insignia «Última llamada».
        "ventana_umbral_horas": umbral_ventana_horas,
        "escalados": len(escalados), "sin_asesor": len(sin_asesor),
        # Casos DISTINTOS de la sección "Responde ahora" (escalados + sin asesor +
        # clientes esperando): un escalado suele ser también cliente esperando,
        # así que sumar los tres totales contaría dos veces al mismo cliente.
        "ahora_total": len(
            {l["telefono"] for l in escalados} | {l["telefono"] for l in sin_asesor} | {c["telefono"] for c in esperando}
        ),
        "citas_proximas": len(proximas), "citas_vencidas": len(vencidas),
        # Aditivo: vencidas de hace MÁS de 7 días (no se listan en Inicio).
        "citas_vencidas_antiguas": vencidas_antiguas,
        # Aditivos (2026-10-09, "Para llamar"): tareas de llamada pendientes y cuántas están vencidas por SLA.
        "llamadas_pendientes": llamar["pendientes"], "llamadas_vencidas": llamar["vencidas"],
        # Aditivo (2026-10-13): el módulo está encendido Y en modo efectivo `activo`. Con 0 pendientes la celda «Llamar» de
        # Inicio se muestra igual («Nada pendiente») solo si esto es True; en sombra o apagado se oculta.
        "llamadas_activo": await _llamadas_activo(negocio_id),
        # Extra (no estaba en el contrato original): alimenta el indicador
        # "Citas próximas (7 días)" de la vista Asesor.
        "citas_7_dias": citas_7_dias,
        # Aditivo (2026-10-13, Tira de acción): citas cuyo día en Lima es hoy (futuras y ya pasadas sin cerrar).
        "citas_hoy": citas_hoy,
        # Aditivo (2026-10-07): atencion_atrasada | atencion_urgente | atencion_ultima_llamada (excluyentes),
        # atencion_total y los dos de la campana (ver `atencion_atrasada.totales_de_atencion`).
        **atencion_atrasada.totales_de_atencion(esperando, para_campana, pausa),
    }

    if not pares:
        mensaje = _MENSAJE_VACIO_ADMIN if vista_admin else _MENSAJE_VACIO_ASESOR
        return {"vacio": True, "mensaje_vacio": mensaje, "items": [], "totales": totales, "pausa": pausa}

    # Los clientes esperando ya traen su conversation_id; el resto (leads sin
    # asignar, citas) se resuelve en bloque, no uno por uno.
    faltantes = [fuente["telefono"] for fuente, item in pares if not item["conversation_id"]]
    conversation_ids = await resolver_conversation_ids_por_telefono(negocio_id, faltantes) if faltantes else {}
    items = []
    for fuente, item in pares:
        if not item["conversation_id"]:
            item["conversation_id"] = conversation_ids.get(fuente["telefono"])
        # Un escalado o sin asesor que además espera respuesta también muestra su antigüedad.
        if "atencion" not in item and item["categoria"] in ("escalado", "sin_asesor") and fuente["telefono"] in atencion_por_telefono:
            item["atencion"] = atencion_por_telefono[fuente["telefono"]]
        items.append(item)
    return {"vacio": False, "mensaje_vacio": None, "items": items, "totales": totales, "pausa": pausa}


async def _zona_accion_asesor_datos(usuario: dict, datos: dict) -> dict:
    """Estructura de datos de la Zona de acción — Asesor (Product Patterns
    Cap. 3 §3: lista priorizada de conversaciones/oportunidades propias)."""
    return await _zona_accion_datos(usuario["negocio_id"], usuario["username"], vista_admin=False)


async def _zona_accion_admin_datos(datos: dict, negocio_id: str) -> dict:
    """Estructura de datos de la Zona de acción — Administrador/Supervisor
    (Product Patterns Cap. 3 §3: qué requiere intervención hoy, alcance del
    Negocio)."""
    return await _zona_accion_datos(negocio_id, None, vista_admin=True)


def _indicador_esperando(totales: dict) -> dict:
    """«Esperando respuesta» = los que se pueden responder AHORA (ventana abierta): el mismo número que el
    badge de «Responde ahora». Si hay clientes con la ventana cerrada, se suman como nota secundaria (`nota`, aditivo);
    el valor total (`cliente_esperando`) sigue en `totales`. Sin `esperando_ventana_abierta` (totales viejos) cae al total."""
    abiertos = totales.get("esperando_ventana_abierta", totales["cliente_esperando"])
    indicador = {"valor": abiertos, "etiqueta": "Esperando respuesta"}
    cerrados = totales.get("esperando_ventana_cerrada", 0) or 0
    if cerrados > 0:
        indicador["nota"] = f"+{cerrados} con ventana cerrada"
    return indicador


def _zona_indicadores_asesor_datos(casos_activos: int, totales: dict) -> list[dict]:
    # Antes "Conversaciones activas" y "Leads asignados" eran el MISMO número
    # (y contaban cerrados). Ahora: casos vivos, los que esperan, y agenda.
    return [
        {"valor": casos_activos, "etiqueta": "Mis casos activos"},
        _indicador_esperando(totales),
        {"valor": totales["citas_7_dias"], "etiqueta": "Citas próximas (7 días)"},
    ]


def _zona_indicadores_admin_datos(casos_activos: int, totales: dict, asesores: list[dict]) -> list[dict]:
    disponibles = sum(1 for a in asesores if a.get("disponible"))
    return [
        {"valor": casos_activos, "etiqueta": "Casos activos"},
        _indicador_esperando(totales),
        {"valor": f"{disponibles}/{len(asesores)}", "etiqueta": "Asesores disponibles"},
    ]


def _aviso(id_: str, nivel: str, titulo: str, detalle: str) -> dict:
    return {"id": id_, "nivel": nivel, "titulo": titulo, "detalle": detalle, "enlace": _RUTA_USO}


async def _avisos_circuito_ia(negocio_id: str) -> list[dict]:
    """Aviso de que Gabi está en modo sin IA (Fase 1): el circuito de la IA está abierto.
    Detalle: desde qué hora (Lima) y cuántos clientes ya se transfirieron a un asesor con el
    mensaje automático / cuántos no tuvieron asesor y están en la cola de supervisión (sale de los
    eventos `derivado_sin_ia` desde que se abrió). Sin enlace: no hay a dónde ir a arreglarlo
    desde el panel. Nunca rompe Inicio."""
    try:
        estado = await circuito_ia.obtener_estado()
        if estado.get("estado") != "abierto":
            return []
        abierto_en = circuito_ia.parsear_momento(estado.get("abierto_en"))
        if abierto_en is None:
            return []
        from agent.memory import contar_derivados_sin_ia
        from agent.tools import TZ_LIMA
        from zoneinfo import ZoneInfo
        conteo = await contar_derivados_sin_ia(abierto_en, negocio_id)
        hora = abierto_en.replace(tzinfo=ZoneInfo("UTC")).astimezone(TZ_LIMA).strftime("%H:%M")
        return [{
            "id": "ia_circuito_abierto", "nivel": "error", "titulo": "Gabi está en modo sin IA",
            "detalle": (
                f"Desde las {hora}. {conteo['total']} clientes ya fueron transferidos a tu equipo con un mensaje "
                f"automático; {conteo['en_cola']} no tuvieron asesor disponible y están en la cola de supervisión."
            ),
            "enlace": None,
        }]
    except Exception:
        logger.exception("Inicio: no se pudo calcular el aviso del circuito de la IA")
        return []


def _duracion_legible(delta: timedelta) -> str:
    """"7 min", "3 h 10 min", "2 días" — para "no corre desde hace …"."""
    minutos = max(0, int(delta.total_seconds() // 60))
    if minutos < 60:
        return f"{minutos} min"
    if minutos < 48 * 60:
        horas, resto = divmod(minutos, 60)
        return f"{horas} h {resto} min" if resto else f"{horas} h"
    return f"{minutos // (24 * 60)} días"


async def _avisos_campanas_sin_material(negocio_id: str) -> list[dict]:
    """Aviso SOLO para el admin (lo llama `_avisos_inicio`): campañas ACTIVAS cuyo material (`codigo_material`) ya no está
    activo con precio en el catálogo. Gabi no cita precio de esa campaña (brain.py, mejora M1) hasta que se actualice el
    catálogo o la campaña. Sin campañas afectadas no hay aviso. Nunca rompe Inicio."""
    try:
        campanas = [c for c in await mem.listar_campanas(negocio_id, solo_activas=True) if c.get("codigo_material")]
        if not campanas:
            return []
        vigentes = await mem.codigos_hana_activos(negocio_id, [c["codigo_material"] for c in campanas])
        # Con precio manual de respaldo la campaña sigue dando precio: no cuenta como afectada.
        afectadas = [c for c in campanas if c["codigo_material"].strip() not in vigentes and not c.get("precio_promocional")]
        if not afectadas:
            return []
        nombres = ", ".join(c["nombre"] for c in afectadas[:3]) + (f" y {len(afectadas) - 3} más" if len(afectadas) > 3 else "")
        plural = len(afectadas) != 1
        return [{
            "id": "campanas_sin_material", "nivel": "warning",
            "titulo": f"{len(afectadas)} campaña{'s' if plural else ''} sin precio vigente en el catálogo",
            "detalle": (
                f"{nombres}: su material ya no está activo en el catálogo, así que Gabi no dará precio de "
                f"{'esas campañas' if plural else 'esa campaña'}. Actualiza el catálogo del mes o la campaña."
            ),
            "enlace": "/campanas",
        }]
    except Exception:
        logger.exception("Inicio: no se pudo calcular el aviso de campañas sin material en el catálogo")
        return []


async def _avisos_anuncios_sin_clientes(negocio_id: str) -> list[dict]:
    """Aviso SOLO para el admin (lo llama `_avisos_inicio`): los anuncios dejaron de traer clientes o un anuncio que
    traía clientes se calló (ver `agent/alertas_anuncios.py`). Solo lee `attribution_events`. Nunca rompe Inicio."""
    try:
        from agent import alertas_anuncios
        return await alertas_anuncios.avisos(negocio_id)
    except Exception:
        logger.exception("Inicio: no se pudo calcular el aviso de anuncios sin clientes")
        return []


async def _avisos_procesos_programados() -> list[dict]:
    """Avisos del latido de los procesos programados (Cron de Railway), solo para el admin (lo
    llama `_avisos_inicio`). Por cada script vigilado (`CRONES_ESPERADOS`) que haya corrido ALGUNA
    vez: si su última corrida falló → aviso de error; si la última corrida exitosa terminó hace
    más del doble de su intervalo → aviso de advertencia. Un script que nunca corrió no avisa (el
    Cron puede no estar creado todavía). Una sola consulta agrupada; nunca rompe Inicio."""
    try:
        from agent.memory import CRONES_ESPERADOS, resumen_corridas_cron

        corridas = await resumen_corridas_cron(list(CRONES_ESPERADOS))
        ahora = datetime.utcnow()
        avisos: list[dict] = []
        for script, (nombre, intervalo_min) in CRONES_ESPERADOS.items():
            datos = corridas.get(script)
            if not datos:
                continue
            ultima = datos["ultima"]
            if ultima["ok"] is False:
                avisos.append({
                    "id": f"cron-{script}-fallo", "nivel": "error",
                    "titulo": f'El proceso programado "{nombre}" falló en su última corrida',
                    "detalle": (ultima.get("resumen") or "Sin detalle del error.")[:300], "enlace": None,
                })
                continue
            referencia = datos["ultimo_ok_fin"] or ultima["inicio"]
            if ahora - referencia > timedelta(minutes=2 * intervalo_min):
                avisos.append({
                    "id": f"cron-{script}-atrasado", "nivel": "warning",
                    "titulo": f'El proceso programado "{nombre}" no corre desde hace {_duracion_legible(ahora - referencia)}',
                    "detalle": f"Debería correr cada {_duracion_legible(timedelta(minutes=intervalo_min))}. Revisa el servicio Cron en Railway.",
                    "enlace": None,
                })
        return avisos
    except Exception:
        logger.exception("Inicio: no se pudieron calcular los avisos de procesos programados")
        return []


def _aviso_pausa_calendario(pausa: dict | None, esperando: int) -> dict | None:
    """Calendario de negocio (2026-10-12): la ÚNICA entrada de la campana mientras hoy es feriado o día especial
    cerrado («Hoy es feriado: Combate de Angamos» / «3 clientes esperan; se atienden mañana a las 8:00 a. m.»).
    Informativa (`nivel: "info"`), sin enlace. None si no hay pausa."""
    if pausa is None:
        return None
    titulo = cal_negocio.describir_motivo(pausa.get("motivo"), pausa.get("nombre")) or "Hoy no hay atención"
    titulo = f"{titulo[0].upper()}{titulo[1:]}"
    cuando = f"se atienden {pausa['reanuda_texto']}" if pausa.get("reanuda_texto") else "se atienden cuando el equipo vuelva"
    punto = "" if cuando.endswith(".") else "."     # «8:00 a. m.» ya termina en punto
    if esperando > 0:
        detalle = f"{esperando} cliente{'s' if esperando != 1 else ''} {'esperan' if esperando != 1 else 'espera'}; {cuando}{punto}"
    else:
        detalle = f"No hay clientes esperando; la atención se retoma así: {cuando}{punto}"
    return {"id": "calendario_pausa", "nivel": "info", "titulo": titulo, "detalle": detalle, "enlace": None}


async def _avisos_inicio(usuario: dict) -> list[dict]:
    """Avisos para Inicio — SOLO para el rol 'admin' (decisión del usuario: supervisor y
    asesor no los ven): el del modo sin IA (si está activo) y los de uso/costos de WhatsApp.
    Nunca rompe Inicio: ante cualquier falla se registra y devuelve lo que sí se pudo calcular."""
    avisos_llamadas = await _avisos_llamadas(usuario)
    if usuario.get("rol") != "admin":
        return avisos_llamadas
    avisos = await _avisos_circuito_ia(usuario["negocio_id"])
    return (
        avisos + await _avisos_procesos_programados() + await _avisos_uso_inicio(usuario) + avisos_llamadas
        + await _avisos_cambios_calendario_supervisor(usuario["negocio_id"])
        + await _avisos_campanas_sin_material(usuario["negocio_id"])
        + await _avisos_anuncios_sin_clientes(usuario["negocio_id"])
    )


_ENLACE_HISTORIAL_CALENDARIO = "/calendario#historial"


async def _avisos_cambios_calendario_supervisor(negocio_id: str) -> list[dict]:
    """Aviso SOLO para el admin (lo llama `_avisos_inicio`): cuántos cambios al calendario hicieron usuarios con rol
    supervisor en las últimas 24 h («El supervisor ana cambió el calendario: 3 cambios en 24 h»), con enlace al historial
    del calendario. Informativo (`nivel: "info"`); sin cambios de supervisores no hay aviso. Nunca rompe Inicio."""
    try:
        r = await mem.resumen_cambios_calendario_de_supervisores(negocio_id, datetime.utcnow() - timedelta(hours=24))
        if not r["total"]:
            return []
        nombres = r["supervisores"]
        quien = (
            f"El supervisor {nombres[0]}" if len(nombres) == 1
            else f"Los supervisores {', '.join(nombres[:-1])} y {nombres[-1]}"
        )
        verbo = "cambió" if len(nombres) == 1 else "cambiaron"
        cambios = f"{r['total']} cambio{'s' if r['total'] != 1 else ''}"
        return [{
            "id": "calendario_cambios_supervisor", "nivel": "info",
            "titulo": f"{quien} {verbo} el calendario: {cambios} en 24 h",
            "detalle": "Revisa en el historial del calendario qué días se agregaron, cambiaron o quitaron.",
            "enlace": _ENLACE_HISTORIAL_CALENDARIO,
        }]
    except Exception:
        logger.exception("Inicio: no se pudo calcular el aviso de cambios del calendario por supervisores")
        return []


async def _avisos_llamadas(usuario: dict) -> list[dict]:
    """Aviso de "Para llamar" (2026-10-09), para supervisor y admin y SOLO si hay llamadas vencidas por SLA (llevan más
    de `llamadas_sla_horas_habiles` sin hacerse) o "sin hacer". Nunca rompe Inicio."""
    if usuario.get("rol") not in ("admin", "supervisor"):
        return []
    try:
        vencidas = (await llamadas.datos_para_inicio(usuario["negocio_id"], None, tope=1))["vencidas"]
        if not vencidas:
            return []
        return [{
            "id": "llamadas-vencidas", "nivel": "warning",
            "titulo": f"{vencidas} llamada{'s' if vencidas != 1 else ''} sin hacer a tiempo",
            "detalle": "Pasaron más de las horas de atención permitidas sin que nadie las haga. Revísalas y reasígnalas si hace falta.",
            "enlace": None,
        }]
    except Exception:
        logger.exception("Inicio: no se pudo calcular el aviso de llamadas vencidas")
        return []


async def _avisos_uso_inicio(usuario: dict) -> list[dict]:
    """Avisos de uso/costos de WhatsApp para Inicio (ver `_avisos_inicio`)."""
    if usuario.get("rol") != "admin":
        return []
    try:
        negocio_id = usuario["negocio_id"]
        resumen = await resumen_uso_mensual(negocio_id)
        try:
            mapa_canales = await _mapa_canales(negocio_id)
        except Exception:
            mapa_canales = {}
        avisos: list[dict] = []

        for numero in resumen.get("numeros", []):
            alertas = numero.get("alertas") or []
            if not alertas:
                continue
            pid = numero["phone_number_id"]
            nombre = (mapa_canales.get(pid) or {}).get("nombre") or pid
            cuota = resumen.get("cuota_gratis_servicio")
            usados = numero.get("servicio_gratis_total", 0)
            restantes = numero.get("gratis_restantes", 0)
            cobrables = numero.get("servicio_cobrables", 0)
            nivel_alerta = max(alertas)
            if nivel_alerta >= 100:
                avisos.append(_aviso(
                    f"cuota-{pid}-100", "error", "Se acabaron los mensajes gratis de WhatsApp este mes",
                    f"{nombre}: usaste {usados} de {cuota} mensajes gratis. Te quedan {restantes} gratis "
                    f"y ya hay {cobrables} mensajes de servicio cobrables este mes.",
                ))
            elif nivel_alerta >= 95:
                avisos.append(_aviso(
                    f"cuota-{pid}-95", "warning", "Te quedan muy pocos mensajes gratis de WhatsApp este mes",
                    f"{nombre}: usaste {usados} de {cuota} mensajes gratis; te quedan {restantes}.",
                ))
            else:
                avisos.append(_aviso(
                    f"cuota-{pid}-80", "warning", "Usaste el 80 % de tus mensajes gratis de WhatsApp",
                    f"{nombre}: usaste {usados} de {cuota} mensajes gratis; te quedan {restantes}.",
                ))

        alertas_tope = resumen.get("alertas_tope") or []
        if alertas_tope:
            gasto = resumen.get("gasto_estimado_usd")
            tope = resumen.get("tope_mensual_usd")
            detalle_tope = f"Gasto estimado USD {gasto} sobre un tope de USD {tope}."
            if max(alertas_tope) >= 100:
                avisos.append(_aviso("tope-100", "error", "Llegaste al tope de gasto mensual", detalle_tope))
            else:
                avisos.append(_aviso("tope-80", "warning", "Estás cerca del tope de gasto mensual (80 %)", detalle_tope))

        faltantes = resumen.get("tarifas_faltantes") or []
        if faltantes:
            avisos.append(_aviso(
                "tarifas-faltantes", "warning", "Faltan tarifas: el costo y el tope no se pueden calcular",
                "Configura la tarifa de: " + ", ".join(faltantes) + ".",
            ))

        gasto = resumen.get("gasto_estimado_usd")
        if resumen.get("autorecarga") is False and resumen.get("tope_mensual_usd") == 0 and gasto and gasto > 0:
            avisos.append(_aviso(
                "tope-cero", "warning", "Tienes el tope en USD 0: los envíos no esenciales que se cobren se frenarán",
                f"Ya hay un gasto estimado de USD {gasto} este mes. Sube el tope o activa la autorecarga si quieres que sigan saliendo.",
            ))

        orden = {"error": 0, "warning": 1, "info": 2}
        avisos.sort(key=lambda a: orden.get(a["nivel"], 3))
        return avisos
    except Exception:
        logger.exception("Inicio: no se pudieron calcular los avisos de uso (se devuelve lista vacía)")
        return []


async def _zona_accion_asesor(usuario: dict, datos: dict) -> str:
    """Deterministica, sin depender del Copiloto IA ni de ninguna señal de
    protocolo de confianza (Cap. 3 de Product Patterns) — reglas sobre datos
    ya existentes: conversaciones esperando respuesta humana primero (más
    antiguas primero), después próximas citas agendadas."""
    esperando = sorted(
        (l for l in datos["leads_todos"] if l.get("pausado_manual")),
        key=lambda l: l.get("actualizado") or datetime.min,
    )
    agendados = await listar_leads_agendados(usuario["negocio_id"], asesor_asignado=usuario["username"])

    if not esperando and not agendados:
        return _zona_accion_vacia(_MENSAJE_VACIO_ASESOR)

    items = [_item_zona_accion(l["telefono"], l.get("nombre"), "Esperando tu respuesta") for l in esperando[:5]]
    for l in agendados[:3]:
        fecha = l["fecha_agendada"].strftime("%d/%m %H:%M") if l.get("fecha_agendada") else "sin hora"
        items.append(_item_zona_accion(l["telefono"], l.get("nombre"), f"Cita agendada — {fecha}"))
    return "".join(items)


async def _zona_accion_admin(datos: dict, negocio_id: str) -> str:
    """Deterministica, misma disciplina que la del Asesor — qué requiere
    intervención de Administrador/Supervisor hoy, no un resumen pasivo."""
    esperando_asignar = await listar_leads_esperando_asesor(negocio_id)
    esperando_respuesta = sorted(
        (l for l in datos["leads_todos"] if l.get("pausado_manual")),
        key=lambda l: l.get("actualizado") or datetime.min,
    )
    agendados = await listar_leads_agendados(negocio_id)

    if not esperando_asignar and not esperando_respuesta and not agendados:
        return _zona_accion_vacia("El equipo no tiene conversaciones que requieran tu intervención ahora mismo.")

    items = [_item_zona_accion(l["telefono"], l.get("nombre"), "Sin asesor asignado") for l in esperando_asignar[:5]]
    for l in esperando_respuesta[:5]:
        asesor_nombre = l.get("asesor_asignado") or "sin asesor"
        items.append(_item_zona_accion(l["telefono"], l.get("nombre"), f"Esperando respuesta — {asesor_nombre}"))
    for l in agendados[:3]:
        fecha = l["fecha_agendada"].strftime("%d/%m %H:%M") if l.get("fecha_agendada") else "sin hora"
        items.append(_item_zona_accion(l["telefono"], l.get("nombre"), f"Cita agendada — {fecha}"))
    return "".join(items)


def _zona_indicadores_asesor(datos: dict) -> str:
    activas = len(datos["leads_derivados"]) + len(datos["leads_con_gabi"])
    return (
        '<div class="zona-indicadores">'
        + _kpi_card(activas, "Conversaciones activas")
        + _kpi_card(len(datos["leads_todos"]), "Leads asignados")
        + '</div>'
    )


def _zona_indicadores_admin(datos: dict, asesores: list[dict]) -> str:
    disponibles = sum(1 for a in asesores if a.get("disponible"))
    activas = len(datos["leads_derivados"]) + len(datos["leads_con_gabi"])
    return (
        '<div class="zona-indicadores">'
        + _kpi_card(activas, "Conversaciones activas")
        + _kpi_card(len(datos["leads_todos"]), "Leads en curso")
        + _kpi_card(f"{disponibles}/{len(asesores)}", "Asesores disponibles")
        + '</div>'
    )


async def _vista_inicio(request: Request, usuario: dict) -> HTMLResponse:
    """Patrón Inicio (MAIEK_AI_PRODUCT_PATTERNS.md, Cap. 3) — único patrón
    para los 3 roles; cambia el contenido de cada zona según el rol, nunca
    su existencia ni el orden: Zona de acción siempre antes que Zona de
    indicadores (Principio "acción antes que observación", Cap. 8)."""
    datos = await _datos_bandeja(usuario, "todos", "", "")

    if datos["vision_total"]:
        zona_accion_html = await _zona_accion_admin(datos, usuario["negocio_id"])
        asesores = await listar_asesores(usuario["negocio_id"])
        zona_indicadores_html = _zona_indicadores_admin(datos, asesores)
    else:
        zona_accion_html = await _zona_accion_asesor(usuario, datos)
        zona_indicadores_html = _zona_indicadores_asesor(datos)

    cuerpo = f"""
    <div class="vista-inicio">
        <div class="zona-accion">
            <div class="zona-accion-titulo">Tu siguiente mejor acción</div>
            {zona_accion_html}
        </div>
        {zona_indicadores_html}
    </div>
    """
    return _pagina("Inicio", usuario, cuerpo, request=request)


@router.get("/inicio.json")
async def inicio_json(usuario: dict = Depends(_usuario_actual)):
    """GATE 3.1 — Inicio para la Nueva Experiencia (Product Patterns Cap. 3).
    Misma fuente de datos que `_vista_inicio` (arriba, panel legacy) — ver
    el bloque de comentario sobre `_zona_accion_*_datos` para por qué son
    funciones separadas de las que arman el HTML legacy, no una reutilizando
    a la otra."""
    datos = await _datos_bandeja(usuario, "todos", "", "")

    if datos["vision_total"]:
        zona_accion = await _zona_accion_admin_datos(datos, usuario["negocio_id"])
        asesores = await listar_asesores(usuario["negocio_id"])
        casos_activos = await contar_casos_activos(usuario["negocio_id"])
        zona_indicadores = _zona_indicadores_admin_datos(casos_activos, zona_accion["totales"], asesores)
    else:
        zona_accion = await _zona_accion_asesor_datos(usuario, datos)
        casos_activos = await contar_casos_activos(usuario["negocio_id"], asesor=usuario["username"])
        zona_indicadores = _zona_indicadores_asesor_datos(casos_activos, zona_accion["totales"])

    avisos = await _avisos_inicio(usuario)
    aviso_calendario = _aviso_pausa_calendario(zona_accion.get("pausa"), zona_accion["totales"].get("atencion_en_pausa", 0))
    if aviso_calendario is not None:
        avisos = [aviso_calendario] + avisos   # para TODOS los roles: es la única entrada de la campana durante la pausa
    return JSONResponse({
        "vision_total": datos["vision_total"],
        "zona_accion": zona_accion,
        "zona_indicadores": zona_indicadores,
        "avisos": avisos,
    })


# ── "Para llamar" (2026-10-09, agent/llamadas.py) ───────────────────────────────────────────────────────
#
# Tarea de llamada para leads callados que mostraron interés. Contratos completos en docs/contrato_para_llamar.md.
# Todo el módulo viene APAGADO: mientras `llamadas_gabi_activo` no sea "1" (y, para ver tareas, el modo no sea `activo` con
# la aceptación de responsabilidad vigente) el listado devuelve la lista vacía y las acciones responden 409.

_HTTP_DE_LLAMADA = {"no_encontrada": 404, "sin_permiso": 403, "no_abierta": 409, "no_disponible": 409, "invalido": 400}


def _error_http_de_llamada(error: "llamadas.ErrorLlamada") -> HTTPException:
    return HTTPException(status_code=_HTTP_DE_LLAMADA.get(error.codigo, 400), detail=error.mensaje)


async def _cuerpo_objeto_json(request: Request) -> dict:
    try:
        cuerpo = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="El cuerpo debe ser JSON.")
    if not isinstance(cuerpo, dict):
        raise HTTPException(status_code=400, detail="El cuerpo debe ser un objeto JSON.")
    return cuerpo


@router.get("/llamadas.json")
async def llamadas_json(estado: str = "abiertas", usuario: dict = Depends(_usuario_actual)):
    """Tareas de llamada. Un asesor ve las suyas; admin y supervisor ven todas, con los KPI del equipo y la medición.
    `estado`: abiertas (default) | cerradas (últimos 7 días) | todas. Fuera del modo `activo` devuelve `tareas: []`."""
    if estado not in ("abiertas", "cerradas", "todas"):
        raise HTTPException(status_code=400, detail="estado debe ser abiertas, cerradas o todas.")
    return JSONResponse(await llamadas.listar_tareas(usuario["negocio_id"], usuario, estado))


@router.post("/llamadas/{tarea_id}/resultado")
async def llamada_resultado(
    tarea_id: str, request: Request, usuario: dict = Depends(_usuario_actual), _csrf: None = Depends(verificar_csrf),
):
    """Registra el resultado de una llamada. Cuerpo: `{resultado, nota?, hora?}`; `hora` (AAAA-MM-DDTHH:MM, hora de Lima)
    es obligatoria solo con `contesto_llamar_luego`. El asesor solo puede registrar sobre SUS tareas."""
    cuerpo = await _cuerpo_objeto_json(request)
    try:
        resultado = await llamadas.registrar_resultado(
            tarea_id, usuario["negocio_id"], usuario, cuerpo.get("resultado"), nota=cuerpo.get("nota"), hora=cuerpo.get("hora"),
        )
    except llamadas.ErrorLlamada as e:
        raise _error_http_de_llamada(e)
    return JSONResponse({"ok": True, **resultado})


@router.post("/llamadas/{tarea_id}/reasignar")
async def llamada_reasignar(
    tarea_id: str, request: Request,
    usuario: dict = Depends(servicio_identidad.requiere_rol(*ROLES_CON_VISION_TOTAL)), _csrf: None = Depends(verificar_csrf),
):
    """Supervisor/admin: cambia el asesor de la tarea. Cuerpo: `{asesor: "<username>"|null}` (null = vuelve al reparto)."""
    cuerpo = await _cuerpo_objeto_json(request)
    asesor = cuerpo.get("asesor")
    if asesor is not None and not isinstance(asesor, str):
        raise HTTPException(status_code=400, detail="asesor debe ser un username o null.")
    try:
        resultado = await llamadas.reasignar(tarea_id, usuario["negocio_id"], usuario, asesor)
    except llamadas.ErrorLlamada as e:
        raise _error_http_de_llamada(e)
    return JSONResponse({"ok": True, **resultado})


@router.post("/llamadas/{tarea_id}/descartar")
async def llamada_descartar(
    tarea_id: str, request: Request,
    usuario: dict = Depends(servicio_identidad.requiere_rol(*ROLES_CON_VISION_TOTAL)), _csrf: None = Depends(verificar_csrf),
):
    """Supervisor/admin: descarta la tarea (no hace falta llamar). Cuerpo opcional: `{nota?}`. No toca el lead."""
    cuerpo = await _cuerpo_objeto_json(request)
    try:
        resultado = await llamadas.descartar(tarea_id, usuario["negocio_id"], usuario, nota=cuerpo.get("nota"))
    except llamadas.ErrorLlamada as e:
        raise _error_http_de_llamada(e)
    return JSONResponse({"ok": True, **resultado})


@router.get("/configuracion/llamadas.json")
async def configuracion_llamadas_json(usuario: dict = Depends(servicio_identidad.requiere_rol("admin"))):
    """Configuración de "Para llamar" del negocio de la sesión, con el modo EFECTIVO, el texto de responsabilidad vigente y
    el estado de su aceptación. Solo Admin."""
    return JSONResponse(await llamadas.estado_configuracion(usuario["negocio_id"]))


@router.post("/configuracion/llamadas.json")
async def actualizar_configuracion_llamadas_json(
    request: Request, usuario: dict = Depends(servicio_identidad.requiere_rol("admin")), _csrf: None = Depends(verificar_csrf),
):
    """Guarda la configuración (cualquier subconjunto de campos; todo o nada). Aceptar la responsabilidad legal:
    `{aceptar_responsabilidad: true, version_texto: "v1"}`; revocarla: `{revocar_responsabilidad: true}` (apaga el modo
    activo y cancela las tareas abiertas). Del negocio de la sesión, nunca del cuerpo. Solo Admin."""
    cuerpo = await _cuerpo_objeto_json(request)
    try:
        estado = await llamadas.guardar_cambios(usuario["negocio_id"], usuario["username"], cuerpo, actor_rol=usuario.get("rol"))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except llamadas.ErrorLlamada as e:
        raise _error_http_de_llamada(e)
    return JSONResponse({"ok": True, **estado})


@router.get("", response_class=HTMLResponse)
async def panel_principal(
    request: Request, usuario: dict = Depends(_usuario_actual), estado: str = "todos", asesor: str = "", canal: str = "",
):
    # Orquestador del flujo de entrada (MAIEK_AI_PRODUCT_PATTERNS.md, Cap. 3):
    # sin ningún filtro explícito en la URL (aterrizaje real, no un clic
    # desde el rail) se muestra Inicio. Cualquier filtro explícito —incluido
    # "?estado=todos" al hacer clic en "Todos" del rail— sigue mostrando la
    # Bandeja exactamente como funciona hoy, sin cambios.
    if not any(k in request.query_params for k in ("estado", "asesor", "canal")):
        return await _vista_inicio(request, usuario)

    datos = await _datos_bandeja(usuario, estado, asesor, canal)
    rail = await _renderizar_rail_estados(usuario, datos, estado, asesor, canal)

    asesores = await listar_asesores(usuario["negocio_id"]) if datos["vision_total"] else []
    resumen = _barra_resumen(datos, asesores, estado) if datos["vision_total"] else ""

    if asesor:
        # Clic en un asesor del equipo: se navega su bandeja de conversaciones
        # (estilo WhatsApp) para poder abrir un chat directo con un cliente.
        lista = await _renderizar_lista_conversaciones(usuario, datos, telefono_activo=None, asesor_filtro=asesor)
        panel = """
            <div class="text-center text-muted mt-5 pt-5">
                <h5>Selecciona una conversación</h5>
                <p>Elige un lead de la lista para ver el chat.</p>
            </div>
        """
        columnas = f"{rail}{lista}"
    else:
        # Clic en un estado (o sin filtro): se muestra la tabla, filtrada por
        # ese estado si corresponde, para que el supervisor pueda revisar y
        # reasignar directamente desde ahí.
        leads_tabla = datos["leads_todos"]
        if estado == "con_gabi":
            # "con_gabi" es un balde sintético (explorando/comparando/
            # evaluando juntos) — ningún lead tiene ese valor exacto en
            # _estado_conversacion, así que no puede filtrarse con == estado
            # como los demás.
            leads_tabla = datos["leads_con_gabi"]
        elif estado != "todos":
            leads_tabla = [l for l in leads_tabla if _estado_conversacion(l) == estado]
        if not datos["vision_total"] and estado == "todos" and not leads_tabla:
            # Un asesor sin NINGÚN lead asignado (no un filtro sin resultados)
            # no sabe si eso es normal o un error — la asignación es automática
            # y silenciosa, así que explicamos de dónde le van a llegar.
            panel = _estado_vacio_asesor_sin_leads(usuario)
        else:
            panel = _tabla_todos_los_leads(leads_tabla, datos["mapa_canales"])
        columnas = rail

    # Aviso de "Próximas citas" en la vista principal — sin correo/dominio
    # configurado todavía, esta es la notificación real: lo primero que ve
    # el asesor (o el supervisor, con las de todo el equipo) al entrar.
    aviso_citas = ""
    if estado == "todos" and not asesor:
        agendados = await listar_leads_agendados(
            usuario["negocio_id"], asesor_asignado=None if datos["vision_total"] else usuario["username"]
        )
        aviso_citas = _aviso_proximas_citas(agendados, datos["vision_total"])

    cuerpo = f"""
    {resumen}
    <div class="shell{' con-resumen' if resumen else ''} d-flex">
        {columnas}
        <div class="main-pane flex-grow-1 p-4">{aviso_citas}{panel}</div>
    </div>
    """
    return _pagina("Bandeja", usuario, cuerpo, request=request)


def _estado_vacio_asesor_sin_leads(usuario: dict) -> str:
    """Vacío explicativo para un asesor sin ningún lead asignado todavía.
    Distinto de "sin resultados para este filtro": alguien nuevo no sabe que
    la asignación es automática y silenciosa (nadie le "entrega" nada a
    mano), así que sin contexto esta pantalla en blanco parece un error."""
    en_linea = usuario.get("disponible", True)
    aviso_disponibilidad = (
        '<p class="text-muted small mb-0">Estás <strong>🟢 Disponible</strong> — en cuanto Gabi derive '
        'una conversación a un asesor, te puede tocar a ti.</p>'
        if en_linea else
        '<p class="text-muted small mb-0">Estás marcado como <strong>⚪ No disponible</strong> arriba, así '
        'que por ahora no te están llegando leads nuevos. Cambia tu estado cuando quieras volver a recibir.</p>'
    )
    return f"""
    <div class="text-center mt-5 pt-4">
        <div class="mb-3" style="font-size:2.5rem">🗂️</div>
        <h5>Todavía no tienes leads asignados</h5>
        <p class="text-muted mb-2" style="max-width:420px;margin-inline:auto">
            Los leads se asignan automáticamente a un asesor disponible cuando Gabi
            deriva una conversación desde WhatsApp — no hace falta buscarlos ni pedirlos.
        </p>
        {aviso_disponibilidad}
    </div>
    """


def _aviso_proximas_citas(agendados: list[dict], vision_total: bool) -> str:
    """Franja con las próximas citas agendadas — para el asesor, las suyas;
    para un supervisor, las de todo el equipo. No depende de correo: es lo
    primero que se ve al entrar a la bandeja."""
    if not agendados:
        return ""
    filas = "".join(
        f"""<a href="/dashboard/lead/{html.escape(lead['telefono'])}" data-ajax="1"
              class="d-flex align-items-center justify-content-between gap-2 text-decoration-none text-dark py-1">
            <span class="d-flex align-items-center gap-2 overflow-hidden">
                {_avatar(lead.get('nombre') or lead['telefono'], 24)}
                <span class="text-truncate">{html.escape(lead.get('nombre') or lead['telefono'])}</span>
                {f'<span class="text-muted small">&middot; {html.escape(lead["asesor_asignado"])}</span>' if vision_total and lead.get('asesor_asignado') else ''}
            </span>
            <span class="text-muted small flex-shrink-0">{lead['fecha_agendada'].strftime('%d/%m %H:%M')}</span>
        </a>"""
        for lead in agendados[:5]
    )
    return f"""
    <div class="card leads-card shadow-sm mb-3">
        <div class="barra-acento"></div>
        <div class="card-body p-3">
            <h6 class="text-uppercase text-muted small fw-bold mb-2">
                <i class="bi bi-calendar-event"></i> Próximas citas ({len(agendados)})
            </h6>
            {filas}
        </div>
    </div>
    """


# ── Conversación / detalle de lead ────────────────────────────────────

async def _bloque_respuesta(telefono: str, lead: dict) -> str:
    if not lead.get("asesor_asignado"):
        return (
            '<p class="text-muted small mb-0">'
            '<i class="bi bi-info-circle"></i> Asigna este lead a un asesor para poder responder '
            'manualmente (mientras tanto, Gabi sigue atendiendo automáticamente).</p>'
        )
    catalogos = await servicio_conversacion.listar_archivos_reutilizables(lead["negocio_id"])
    opciones_catalogos = "".join(
        f'<li><button type="button" class="dropdown-item small catalogo-item" data-archivo-id="{c["id"]}">'
        f'<i class="bi bi-file-earmark-fill me-1"></i>{html.escape(c["etiqueta"] or c["nombre_original"])}</button></li>'
        for c in catalogos
    ) or '<li><span class="dropdown-item-text text-muted small">Aún no hay catálogos disponibles.</span></li>'

    return f"""
    <form id="form-respuesta" class="d-flex gap-2 align-items-end" method="post" action="/dashboard/lead/{html.escape(telefono)}/responder">
        <div class="flex-grow-1">
            <textarea name="mensaje" id="input-mensaje" class="form-control" placeholder="Escribe tu respuesta..." rows="1" maxlength="200" style="resize:none;overflow-y:auto;max-height:140px;"></textarea>
            <div class="text-end" style="font-size:.68rem;line-height:1.3">
                <span id="contador-mensaje" class="text-muted">0/200</span>
            </div>
        </div>
        <div class="dropdown">
            <button class="btn-icono-chat" type="button" id="btn-catalogo-dropdown" data-bs-toggle="dropdown" aria-expanded="false" title="Enviar catálogo">
                <i class="bi bi-folder-fill"></i>
            </button>
            <ul class="dropdown-menu dropdown-menu-end" id="lista-catalogos" style="max-height:260px;overflow-y:auto;">
                {opciones_catalogos}
            </ul>
        </div>
        <button type="button" class="btn-icono-chat" id="btn-adjuntar" title="Adjuntar PDF o imagen">
            <i class="bi bi-paperclip"></i>
        </button>
        <input type="file" id="input-archivo" accept=".pdf,.jpg,.jpeg,.png" style="display:none">
        <button type="button" class="btn-icono-chat" id="btn-audio" title="Grabar nota de voz">
            <i class="bi bi-mic-fill"></i>
        </button>
        <button type="submit" class="btn btn-primary flex-shrink-0" style="width:38px;height:38px;padding:0;border-radius:12px;"><i class="bi bi-send-fill"></i></button>
    </form>
    <div id="estado-adjunto" class="small text-muted mt-1" style="display:none"></div>
    <div id="previsualizacion-audio" class="previsualizacion-audio-bar align-items-center gap-2 mt-1" style="display:none">
        <button type="button" class="btn-icono-chat btn-descartar-audio" id="btn-descartar-audio" title="Descartar grabación">
            <i class="bi bi-trash-fill"></i>
        </button>
        <div class="reproductor-audio" id="reproductor-preview-audio">
            <button type="button" class="btn-play-audio"><i class="bi bi-play-fill"></i></button>
            <div class="barra-audio-wrap"><div class="barra-audio-progreso"></div></div>
            <span class="tiempo-audio">0:00</span>
        </div>
        <span class="small text-muted">Toca <i class="bi bi-send-fill"></i> para enviar</span>
    </div>
    """


def _script_chat_en_vivo(telefono: str, tiene_asesor: bool) -> str:
    """Poll liviano en JS: actualiza el chat sin recargar la página, mantiene
    el scroll abajo, y no borra lo que el asesor está escribiendo. También
    envía la respuesta del asesor por fetch, sin navegar."""
    return f"""
    <script>
    (function() {{
        const telefono = {telefono!r};
        const chatDiv = document.getElementById('chat');
        const etiquetas = {{user: 'Cliente', assistant: 'Gabi', asesor: 'Asesor'}};
        let ultimaFirma = '';

        const inicial = {{user: 'C', assistant: 'G', asesor: 'A'}};

        function pintarMensajes(mensajes) {{
            const firma = mensajes.length + ':' + (mensajes.length ? mensajes[mensajes.length - 1].content : '');
            if (firma === ultimaFirma) return;
            ultimaFirma = firma;
            chatDiv.innerHTML = mensajes.map(function(m) {{
                // Un mensaje via_app lo mandó un asesor directo desde la app
                // de WhatsApp Business en el celular (coexistencia), no Gabi
                // ni el panel — Meta no dice qué asesor fue, así que se
                // marca genérico en vez de atribuirlo a "Gabi" (su role
                // guardado sigue siendo "assistant" para el historial).
                const rol = m.via_app ? 'Asesor (desde app)' : (etiquetas[m.role] || m.role);
                const texto = m.content.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
                const mio = m.role !== 'user' ? ' mio' : '';
                const esAudio = m.archivo_tipo && m.archivo_tipo.indexOf('audio/') === 0;
                const cuerpo = !m.archivo_id ? texto
                    : esAudio
                        ? '<div class="reproductor-audio" data-src="/dashboard/archivo/' + m.archivo_id + '">' +
                          '<button type="button" class="btn-play-audio"><i class="bi bi-play-fill"></i></button>' +
                          '<div class="barra-audio-wrap"><div class="barra-audio-progreso"></div></div>' +
                          '<span class="tiempo-audio">0:00</span></div>'
                        : '<a href="/dashboard/archivo/' + m.archivo_id + '" target="_blank" class="text-reset">' +
                          '<i class="bi bi-file-earmark-arrow-down"></i> ' + texto + '</a>';
                return '<div class="msg-row' + mio + '">' +
                    '<span class="avatar avatar-sm">' + (m.via_app ? 'A' : (inicial[m.role] || '?')) + '</span>' +
                    '<div class="msg ' + m.role + '"><strong>' + rol + ':</strong> ' + cuerpo + '</div>' +
                    '</div>';
            }}).join('') || '<p class="text-muted">Sin mensajes.</p>';
            chatDiv.scrollTop = chatDiv.scrollHeight;
        }}

        // Reproductor de audio propio (nota de voz recibida/enviada, y la
        // previsualización antes de mandar) — reemplaza el <audio controls>
        // nativo del navegador, que se ve distinto y anticuado según el
        // sistema operativo. Un objeto Audio() por reproductor, guardado
        // directo en el elemento del DOM (se recrea solo si ese nodo se
        // vuelve a pintar); delegado en el documento porque el chat se
        // reemplaza entero (innerHTML) en cada actualización.
        function formatearTiempoAudio(segundos) {{
            segundos = Math.floor(segundos || 0);
            const m = Math.floor(segundos / 60);
            const s = segundos % 60;
            return m + ':' + (s < 10 ? '0' : '') + s;
        }}

        function obtenerAudioDe(contenedor) {{
            if (contenedor._audioObj) return contenedor._audioObj;
            const audio = new Audio(contenedor.getAttribute('data-src'));
            contenedor._audioObj = audio;
            const barraProgreso = contenedor.querySelector('.barra-audio-progreso');
            const tiempoEl = contenedor.querySelector('.tiempo-audio');
            const btnPlay = contenedor.querySelector('.btn-play-audio');
            audio.addEventListener('loadedmetadata', function() {{
                if (isFinite(audio.duration)) tiempoEl.textContent = formatearTiempoAudio(audio.duration);
            }});
            audio.addEventListener('timeupdate', function() {{
                if (audio.duration) barraProgreso.style.width = (audio.currentTime / audio.duration * 100) + '%';
                tiempoEl.textContent = formatearTiempoAudio(audio.currentTime);
            }});
            audio.addEventListener('ended', function() {{
                btnPlay.innerHTML = '<i class="bi bi-play-fill"></i>';
                barraProgreso.style.width = '0%';
                tiempoEl.textContent = isFinite(audio.duration) ? formatearTiempoAudio(audio.duration) : '0:00';
            }});
            return audio;
        }}

        let audioEnReproduccion = null;

        function alternarReproduccionAudio(contenedor) {{
            const audio = obtenerAudioDe(contenedor);
            const btnPlay = contenedor.querySelector('.btn-play-audio');
            if (audio.paused) {{
                if (audioEnReproduccion && audioEnReproduccion !== audio) {{
                    audioEnReproduccion.pause();
                    const otroBtn = document.querySelector('.reproductor-audio .btn-play-audio.reproduciendo');
                    if (otroBtn) {{
                        otroBtn.innerHTML = '<i class="bi bi-play-fill"></i>';
                        otroBtn.classList.remove('reproduciendo');
                    }}
                }}
                audio.play();
                audioEnReproduccion = audio;
                btnPlay.innerHTML = '<i class="bi bi-pause-fill"></i>';
                btnPlay.classList.add('reproduciendo');
            }} else {{
                audio.pause();
                btnPlay.innerHTML = '<i class="bi bi-play-fill"></i>';
                btnPlay.classList.remove('reproduciendo');
            }}
        }}

        function buscarEnAudio(contenedor, clienteX) {{
            const audio = obtenerAudioDe(contenedor);
            const barra = contenedor.querySelector('.barra-audio-wrap');
            const rect = barra.getBoundingClientRect();
            if (!audio.duration || !rect.width) return;
            const porcentaje = Math.min(1, Math.max(0, (clienteX - rect.left) / rect.width));
            audio.currentTime = porcentaje * audio.duration;
        }}

        document.addEventListener('click', function(ev) {{
            const btnPlay = ev.target.closest('.btn-play-audio');
            if (btnPlay) {{
                alternarReproduccionAudio(btnPlay.closest('.reproductor-audio'));
                return;
            }}
            const barra = ev.target.closest('.barra-audio-wrap');
            if (barra) {{
                buscarEnAudio(barra.closest('.reproductor-audio'), ev.clientX);
            }}
        }});

        function actualizar() {{
            if (document.hidden) return;  // pestaña en segundo plano: no gastar requests
            fetch('/dashboard/lead/' + encodeURIComponent(telefono) + '/mensajes.json')
                .then(function(r) {{ return r.json(); }})
                .then(pintarMensajes)
                .catch(function() {{}});
        }}

        actualizar();
        chatDiv.scrollTop = chatDiv.scrollHeight;

        // Indicador de "X está escribiendo..." (otro miembro del equipo
        // mirando el mismo lead) — se crea al vuelo, no depende de HTML del
        // servidor. Se auto-oculta si no llega otro aviso en 3s.
        let elEscribiendo = null;
        let temporizadorEscribiendo = null;
        function mostrarEscribiendo(nombre) {{
            if (!elEscribiendo) {{
                elEscribiendo = document.createElement('div');
                elEscribiendo.className = 'text-muted small px-2 py-1 fst-italic';
                chatDiv.parentElement.appendChild(elEscribiendo);
            }}
            elEscribiendo.textContent = nombre + ' está escribiendo...';
            elEscribiendo.style.display = '';
            clearTimeout(temporizadorEscribiendo);
            temporizadorEscribiendo = setTimeout(function() {{
                if (elEscribiendo) elEscribiendo.style.display = 'none';
            }}, 3000);
        }}

        // Chat en vivo por WebSocket (ver _script_tiempo_real, conexión
        // persistente para toda la sesión) — con sondeo lento de respaldo
        // por si la conexión se cae y no logra reconectar. Este chat puede
        // quedar reemplazado por una navegación AJAX (tabla -> detalle ->
        // chat) sin recargar la página, así que el listener/intervalo se
        // auto-desactivan apenas su chatDiv ya no está en el documento —
        // para no seguir escuchando/pidiendo mensajes de un chat que ya no
        // se ve, ni acumular listeners cada vez que se vuelve a entrar.
        function alEventoWS(evento) {{
            if (evento.tipo === 'mensaje_nuevo' && evento.telefono === telefono) {{
                actualizar();
            }} else if (evento.tipo === 'asesor_escribiendo' && evento.telefono === telefono) {{
                mostrarEscribiendo(evento.username);
            }}
        }}
        function limpiarWS() {{
            if (window.__gasoWS) {{
                window.__gasoWS.off(alEventoWS);
                window.__gasoWS.verLead(null);
            }}
            if (window.__gasoChatLimpiar === limpiarWS) window.__gasoChatLimpiar = null;
        }}
        // Referencia global para que la navegación AJAX (ver navegarAjax en
        // _pagina) pueda limpiar ESTE chat de inmediato apenas se navega a
        // otro lado, en vez de esperar hasta 20s a que el intervalo de
        // respaldo note que el chatDiv ya no está — así no quedan listeners
        // viejos acumulados escuchando eventos de chats que ya se dejaron
        // de ver.
        window.__gasoChatLimpiar = limpiarWS;
        if (window.__gasoWS) {{
            window.__gasoWS.on(alEventoWS);
            window.__gasoWS.verLead(telefono);
        }}

        // Dos chances de limpiar (lo que pase primero): el intervalo de
        // respaldo (máx. 20s de retraso) o el cambio de visibilidad de la
        // pestaña — así no queda un listener fantasma escuchando eventos de
        // un chat que ya no está en pantalla por mucho tiempo.
        const intervaloRespaldo = setInterval(function() {{
            if (!document.body.contains(chatDiv)) {{ clearInterval(intervaloRespaldo); limpiarWS(); return; }}
            actualizar();
        }}, 20000);
        function alCambiarVisibilidad() {{
            if (!document.body.contains(chatDiv)) {{
                document.removeEventListener('visibilitychange', alCambiarVisibilidad);
                limpiarWS();
                return;
            }}
            if (!document.hidden) actualizar();
        }}
        // Al volver a la pestaña, refresca al toque en vez de esperar el próximo tick
        document.addEventListener('visibilitychange', alCambiarVisibilidad);

        {"" if not tiene_asesor else '''
        const form = document.getElementById('form-respuesta');
        const input = document.getElementById('input-mensaje');
        const contadorMensaje = document.getElementById('contador-mensaje');
        const LIMITE_MENSAJE = 200;
        const btnAdjuntar = document.getElementById('btn-adjuntar');
        const inputArchivo = document.getElementById('input-archivo');
        const estadoAdjunto = document.getElementById('estado-adjunto');
        const zonaSoltar = document.querySelector('.chat-reply-fijo');
        const btnAudio = document.getElementById('btn-audio');
        const previsualizacionAudio = document.getElementById('previsualizacion-audio');
        const reproductorPreview = document.getElementById('reproductor-preview-audio');
        const btnDescartarAudio = document.getElementById('btn-descartar-audio');
        const btnCatalogoDropdown = document.getElementById('btn-catalogo-dropdown');
        const DURACION_MAXIMA_AUDIO = 60;
        let mediaRecorder = null;
        let fragmentosAudio = [];
        let grabando = false;
        let iniciandoGrabacion = false;
        let segundosGrabados = 0;
        let intervaloGrabacion = null;
        let blobPendiente = null;
        let urlPendiente = null;

        // El input crece con el texto (en vez de quedar como una sola línea
        // fija) y el maxlength="200" del textarea impide escribir (o pegar)
        // más allá del límite — el contador solo informa cuánto espacio
        // queda, ya no hace falta que avise "te pasaste" porque no se puede.
        function ajustarInputMensaje() {
            input.style.height = 'auto';
            input.style.height = input.scrollHeight + 'px';
            if (!contadorMensaje) return;
            contadorMensaje.textContent = input.value.length + '/' + LIMITE_MENSAJE;
        }
        // Avisa "escribiendo..." a otros miembros del equipo que tengan este
        // mismo lead abierto (ej. supervisor mirando en paralelo) — máximo
        // un aviso cada 2.5s mientras el asesor sigue tipeando, para no
        // saturar el WebSocket con un mensaje por tecla.
        let ultimoAvisoEscribiendo = 0;
        function avisarEscribiendo() {
            if (!window.__gasoWS) return;
            const ahora = Date.now();
            if (ahora - ultimoAvisoEscribiendo < 2500) return;
            ultimoAvisoEscribiendo = ahora;
            window.__gasoWS.escribiendo(telefono);
        }
        if (input) {
            input.addEventListener('input', ajustarInputMensaje);
            input.addEventListener('input', avisarEscribiendo);
            ajustarInputMensaje();
        }

        function formatearTiempo(segundos) {
            const m = Math.floor(segundos / 60);
            const s = segundos % 60;
            return m + ':' + (s < 10 ? '0' : '') + s;
        }

        // Mientras hay una nota de voz previsualizándose, adjuntar archivo y
        // catálogo quedan deshabilitados (no tiene sentido mezclar un envío
        // con otro a medio armar) — grabar de nuevo sigue habilitado, sirve
        // para regrabar (descarta la anterior sola).
        function habilitarAdjuntosNoAudio(habilitado) {
            if (btnAdjuntar) btnAdjuntar.disabled = !habilitado;
            if (btnCatalogoDropdown) btnCatalogoDropdown.disabled = !habilitado;
        }

        function reiniciarReproductorPreview() {
            if (reproductorPreview._audioObj) reproductorPreview._audioObj.pause();
            reproductorPreview._audioObj = null;
            reproductorPreview.querySelector('.btn-play-audio').innerHTML = '<i class="bi bi-play-fill"></i>';
            reproductorPreview.querySelector('.barra-audio-progreso').style.width = '0%';
            reproductorPreview.querySelector('.tiempo-audio').textContent = '0:00';
        }

        function limpiarPrevisualizacion() {
            if (urlPendiente) URL.revokeObjectURL(urlPendiente);
            urlPendiente = null;
            blobPendiente = null;
            reiniciarReproductorPreview();
            previsualizacionAudio.style.display = 'none';
            habilitarAdjuntosNoAudio(true);
        }

        function mostrarPrevisualizacion(blob) {
            blobPendiente = blob;
            urlPendiente = URL.createObjectURL(blob);
            reiniciarReproductorPreview();
            reproductorPreview.setAttribute('data-src', urlPendiente);
            previsualizacionAudio.style.display = 'flex';
            habilitarAdjuntosNoAudio(false);
        }

        function enviarNotaDeVoz(blob) {
            const datos = new FormData();
            datos.append('audio', blob, 'nota.webm');
            estadoAdjunto.style.display = 'block';
            estadoAdjunto.textContent = 'Procesando y enviando nota de voz...';
            fetch('/dashboard/lead/' + encodeURIComponent(telefono) + '/enviar-audio', {
                method: 'POST',
                headers: {'X-CSRF-Token': window.__csrfToken()},
                body: datos
            }).then(function(r) {
                if (!r.ok) throw new Error('fallo el envio');
                estadoAdjunto.style.display = 'none';
                actualizar();
            }).catch(function() {
                estadoAdjunto.textContent = 'No se pudo enviar la nota de voz.';
            });
        }

        function detenerGrabacion() {
            if (!grabando) return;
            mediaRecorder.stop();
            grabando = false;
            clearInterval(intervaloGrabacion);
            btnAudio.classList.remove('grabando');
            btnAudio.title = 'Grabar nota de voz';
        }

        function subirYEnviarArchivo(archivo) {
            if (!archivo || !estadoAdjunto) return;
            const datos = new FormData();
            datos.append('archivo', archivo);
            datos.append('caption', input.value.trim());
            input.value = '';
            ajustarInputMensaje();
            estadoAdjunto.style.display = 'block';
            estadoAdjunto.textContent = 'Enviando ' + archivo.name + '...';
            fetch('/dashboard/lead/' + encodeURIComponent(telefono) + '/enviar-archivo', {
                method: 'POST',
                headers: {'X-CSRF-Token': window.__csrfToken()},
                body: datos
            }).then(function(r) {
                if (!r.ok) throw new Error('fallo el envio');
                estadoAdjunto.style.display = 'none';
                actualizar();
            }).catch(function() {
                estadoAdjunto.textContent = 'No se pudo enviar el archivo — verifica el tamaño/formato e intenta de nuevo.';
            });
        }

        if (form) {
            form.addEventListener('submit', function(ev) {
                ev.preventDefault();

                // El mismo botón de enviar (avión de papel) manda la nota de
                // voz pendiente en vez del texto, si hay una previsualización
                // activa — igual que hace WhatsApp Web con un solo botón.
                if (blobPendiente) {
                    const blob = blobPendiente;
                    limpiarPrevisualizacion();
                    enviarNotaDeVoz(blob);
                    return;
                }

                const texto = input.value.trim();
                if (!texto) return;
                input.value = '';
                ajustarInputMensaje();

                // Optimista: muestra el mensaje al instante, sin esperar la
                // ida y vuelta a WhatsApp/la base de datos
                const fila = document.createElement('div');
                fila.className = 'msg-row mio';
                const textoSeguro = texto.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
                fila.innerHTML = '<span class="avatar avatar-sm">A</span><div class="msg asesor"><strong>Asesor:</strong> ' + textoSeguro + '</div>';
                chatDiv.appendChild(fila);
                chatDiv.scrollTop = chatDiv.scrollHeight;

                fetch(form.action, {
                    method: 'POST',
                    headers: {'Content-Type': 'application/x-www-form-urlencoded', 'X-CSRF-Token': window.__csrfToken()},
                    body: 'mensaje=' + encodeURIComponent(texto)
                }).then(actualizar);
            });
            // Enter envía el mensaje, Shift+Enter agrega un salto de línea
            // (el input ahora es multilínea, ya no una sola línea fija)
            input.addEventListener('keydown', function(ev) {
                if (ev.key === 'Enter' && !ev.shiftKey) {
                    ev.preventDefault();
                    form.requestSubmit ? form.requestSubmit() : form.dispatchEvent(new Event('submit', {cancelable: true}));
                }
            });
        }

        // Adjuntar archivo: el botón de clip abre el selector nativo, pero
        // subirYEnviarArchivo() es la función real de envío — la reusa tanto
        // el selector como arrastrar-y-soltar sobre la barra de respuesta.
        if (btnAdjuntar && inputArchivo) {
            btnAdjuntar.addEventListener('click', function() { inputArchivo.click(); });
            inputArchivo.addEventListener('change', function() {
                subirYEnviarArchivo(inputArchivo.files[0]);
                inputArchivo.value = '';
            });
        }

        // Arrastrar y soltar un archivo directo sobre la barra de respuesta
        // — mismo envío que el botón de clip, solo cambia cómo se eligió
        // el archivo. preventDefault en dragover es obligatorio: sin eso el
        // navegador abre/descarga el archivo en vez de disparar 'drop'.
        if (zonaSoltar) {
            let contadorDrag = 0;
            zonaSoltar.addEventListener('dragenter', function(ev) {
                ev.preventDefault();
                contadorDrag++;
                zonaSoltar.classList.add('zona-soltar-activa');
            });
            zonaSoltar.addEventListener('dragover', function(ev) { ev.preventDefault(); });
            zonaSoltar.addEventListener('dragleave', function() {
                contadorDrag = Math.max(0, contadorDrag - 1);
                if (contadorDrag === 0) zonaSoltar.classList.remove('zona-soltar-activa');
            });
            zonaSoltar.addEventListener('drop', function(ev) {
                ev.preventDefault();
                contadorDrag = 0;
                zonaSoltar.classList.remove('zona-soltar-activa');
                const archivo = ev.dataTransfer.files[0];
                if (archivo) subirYEnviarArchivo(archivo);
            });
        }

        if (btnDescartarAudio) {
            btnDescartarAudio.addEventListener('click', limpiarPrevisualizacion);
        }

        // Grabar nota de voz: primer clic pide permiso del micrófono y
        // empieza a grabar (botón en rojo, pulsando, con cronómetro); segundo
        // clic o llegar a DURACION_MAXIMA_AUDIO corta la grabación — pero no
        // la manda todavía, muestra una previsualización (igual que WhatsApp)
        // con reproductor + tacho de descartar, y el envío real pasa por el
        // mismo botón que manda texto. El navegador solo sabe grabar en
        // WebM/Opus, el servidor la convierte a OGG/Opus antes de mandarla.
        if (btnAudio && estadoAdjunto && previsualizacionAudio) {
            btnAudio.addEventListener('click', function() {
                if (grabando) {
                    detenerGrabacion();
                    return;
                }
                // Un doble clic (o un clic mientras el navegador aún está
                // pidiendo permiso del micrófono) podía arrancar DOS
                // grabaciones a la vez — la segunda pisaba la referencia
                // compartida a la primera, que quedaba grabando sola en
                // segundo plano sin forma de detenerla hasta que el propio
                // navegador la cortara sola, mostrando la previsualización
                // "de la nada" mucho después, sin un clic reciente al mic.
                if (iniciandoGrabacion) return;
                iniciandoGrabacion = true;
                limpiarPrevisualizacion();
                navigator.mediaDevices.getUserMedia({audio: true}).then(function(stream) {
                    iniciandoGrabacion = false;
                    fragmentosAudio = [];
                    segundosGrabados = 0;
                    mediaRecorder = new MediaRecorder(stream);
                    mediaRecorder.addEventListener('dataavailable', function(ev) {
                        if (ev.data.size > 0) fragmentosAudio.push(ev.data);
                    });
                    mediaRecorder.addEventListener('stop', function() {
                        stream.getTracks().forEach(function(t) { t.stop(); });
                        const blob = new Blob(fragmentosAudio, {type: mediaRecorder.mimeType || 'audio/webm'});
                        estadoAdjunto.style.display = 'none';
                        mostrarPrevisualizacion(blob);
                    });
                    mediaRecorder.start();
                    grabando = true;
                    btnAudio.classList.add('grabando');
                    btnAudio.title = 'Detener grabación';
                    estadoAdjunto.style.display = 'block';
                    estadoAdjunto.textContent = 'Grabando... 0:00 / ' + formatearTiempo(DURACION_MAXIMA_AUDIO);
                    intervaloGrabacion = setInterval(function() {
                        segundosGrabados++;
                        estadoAdjunto.textContent = 'Grabando... ' + formatearTiempo(segundosGrabados) + ' / ' + formatearTiempo(DURACION_MAXIMA_AUDIO);
                        if (segundosGrabados >= DURACION_MAXIMA_AUDIO) detenerGrabacion();
                    }, 1000);
                }).catch(function() {
                    iniciandoGrabacion = false;
                    estadoAdjunto.style.display = 'block';
                    estadoAdjunto.textContent = 'No se pudo acceder al micrófono — revisa los permisos del navegador.';
                });
            });
        }

        // Si el navegador restaura esta página desde su caché de
        // adelante/atrás (bfcache — pasa al usar el botón Atrás/Adelante,
        // no los links internos), lo hace congelando y descongelando el
        // JS tal como estaba, sin volver a ejecutar este script. Si en ese
        // momento había una grabación o previsualización pendiente, queda
        // "resucitada" en pantalla sin que el asesor haya tocado el
        // micrófono en la sesión actual — se limpia todo al restaurar.
        window.addEventListener('pageshow', function(ev) {
            if (!ev.persisted) return;
            if (grabando) detenerGrabacion();
            limpiarPrevisualizacion();
            if (estadoAdjunto) estadoAdjunto.style.display = 'none';
        });

        // Enviar catálogo: un clic en la lista, sin subir nada de nuevo
        // (ya está guardado del lado del servidor).
        const listaCatalogos = document.getElementById('lista-catalogos');
        if (listaCatalogos && estadoAdjunto) {
            listaCatalogos.addEventListener('click', function(ev) {
                const item = ev.target.closest('.catalogo-item');
                if (!item) return;
                const archivoId = item.getAttribute('data-archivo-id');
                estadoAdjunto.style.display = 'block';
                estadoAdjunto.textContent = 'Enviando catálogo...';
                fetch('/dashboard/lead/' + encodeURIComponent(telefono) + '/enviar-catalogo/' + archivoId, {
                    method: 'POST',
                    headers: {'X-CSRF-Token': window.__csrfToken()}
                }).then(function(r) {
                    if (!r.ok) throw new Error('fallo el envio');
                    estadoAdjunto.style.display = 'none';
                    actualizar();
                }).catch(function() {
                    estadoAdjunto.textContent = 'No se pudo enviar el catálogo.';
                });
            });
        }
        '''}
    }})();
    </script>
    """


def _banner_conflicto_edicion(evento: dict | None) -> str:
    """Human Decision Gate ante un conflicto de edición (MAIEK_AI_PRODUCT_PATTERNS.md,
    Cap. 6 y 8) — el cambio del usuario NO se aplicó; se le muestra quién
    escribió último, cuándo y qué, para que decida cómo seguir: recargar
    (descartar su intento y ver el estado actual) o rehacer su cambio, que
    esta vez sí se guardará porque el formulario ya quedó con la versión
    vigente. Nunca se sobrescribe en silencio."""
    if evento:
        autor = html.escape(evento.get("autor") or "otro usuario")
        detalle = f"{autor} hizo un cambio ({html.escape(evento['descripcion'])}) {_tiempo_relativo(evento['creado'])}."
    else:
        detalle = "El lead cambió mientras editabas."
    return f"""
    <div class="alert alert-warning py-2 px-3 mb-2">
        <div><i class="bi bi-exclamation-triangle-fill"></i> <strong>Conflicto de edición.</strong> {detalle}</div>
        <div class="small text-muted mt-1">Tu cambio NO se guardó. Los datos de abajo ya están actualizados — revisalos y, si querés, volvé a intentar tu cambio.</div>
    </div>
    """


async def _bloque_gestion_lead(
    telefono: str, lead: dict, usuario: dict, request: Request | None = None,
    hay_conflicto: bool = False, evento_conflicto: dict | None = None,
) -> str:
    """Formularios de Asignación / Resultado / Cierre de venta — se muestran
    siempre junto al resumen del cliente (columna del lead), así que el POST
    siempre vuelve a la misma página del lead."""
    opciones_resultado = '<option value="">Selecciona...</option>' + "".join(
        f'<option value="{r}" {"selected" if lead.get("resultado") == r else ""}>{html.escape(ETIQUETAS_RESULTADO[r])}</option>'
        for r in RESULTADOS
    )

    bloque_asignacion = ""
    if usuario["rol"] in ROLES_CON_VISION_TOTAL:
        asesores = await listar_asesores(usuario["negocio_id"])
        opciones_asesor = '<option value="">Sin asignar</option>' + "".join(
            f'<option value="{html.escape(a["username"])}" {"selected" if lead.get("asesor_asignado") == a["username"] else ""}>'
            f'{html.escape(a["nombre"])} — {html.escape((a.get("nivel") or "sin nivel").capitalize())}'
            f'{" (disponible)" if a.get("disponible") else " (no disponible)"}</option>'
            for a in asesores
        )
        bloque_asignacion = f"""
        <div class="card leads-card shadow-sm mb-2">
            <div class="barra-acento"></div>
            <div class="card-body p-3">
                <h6 class="text-uppercase text-muted small fw-bold mb-2">Asignación</h6>
                <form method="post" action="/dashboard/lead/{html.escape(telefono)}/asignar" class="d-flex gap-2">
                    {_csrf_campo(request)}
                    <input type="hidden" name="version" value="{lead.get('version', 0)}">
                    <select name="asesor_asignado" class="form-select form-select-sm">{opciones_asesor}</select>
                    <button type="submit" class="btn btn-sm btn-primary">Asignar</button>
                </form>
            </div>
        </div>
        """
    else:
        bloque_asignacion = f'<p class="text-muted small"><strong>Asesor asignado:</strong> {html.escape(usuario["nombre"])} (tú)</p>'

    opciones_modalidad = "".join(
        f'<option value="{m}" {"selected" if lead.get("modalidad_pago") == m else ""}>{html.escape(m.capitalize())}</option>'
        for m in MODALIDADES_PAGO
    )
    opciones_medio_contado = "".join(
        f'<option value="{html.escape(m)}" {"selected" if lead.get("medio_pago") == m else ""}>{html.escape(m)}</option>'
        for m in MEDIOS_PAGO_CONTADO
    )

    fecha_agendada_valor = lead["fecha_agendada"].strftime("%Y-%m-%dT%H:%M") if lead.get("fecha_agendada") else ""
    es_agendado = lead.get("resultado") == "agendado"

    # El cierre de venta admite VARIAS líneas (un cliente puede comprar un
    # artefacto, varios, un servicio, o un mix) — el carrito arranca
    # precargado con lo que ya esté guardado, para poder agregar/quitar
    # productos en cierres que se editan más de una vez.
    lineas_venta = await listar_lineas_venta(telefono)
    # Va crudo dentro de un <script>, no como atributo HTML — nada de
    # html.escape acá (rompería el JSON). Solo hay que evitar que un "</"
    # dentro de algún texto cierre la etiqueta <script> antes de tiempo.
    lineas_venta_json = json.dumps(lineas_venta).replace("</", "<\\/")

    return f"""
    {_banner_conflicto_edicion(evento_conflicto) if hay_conflicto else ""}
    {bloque_asignacion}
    <div class="card leads-card shadow-sm mb-2">
        <div class="barra-acento"></div>
        <div class="card-body p-3">
            <h6 class="text-uppercase text-muted small fw-bold mb-2">Resultado tras derivación a asesor</h6>
            <form method="post" action="/dashboard/lead/{html.escape(telefono)}/resultado" id="form-resultado">
                {_csrf_campo(request)}
                <input type="hidden" name="version" value="{lead.get('version', 0)}">
                <div class="d-flex gap-2">
                    <select name="resultado" id="resultado-select" class="form-select form-select-sm">{opciones_resultado}</select>
                    <button type="submit" class="btn btn-sm btn-primary flex-shrink-0">Guardar</button>
                </div>
                <div class="mt-2" id="resultado-campo-fecha" style="display:{'' if es_agendado else 'none'}">
                    <label class="form-label small text-muted mb-0">Fecha y hora de la cita</label>
                    <input type="datetime-local" name="fecha_agendada" id="resultado-fecha" class="form-control form-control-sm" value="{fecha_agendada_valor}">
                </div>
            </form>
            <script>
            (function() {{
                var select = document.getElementById('resultado-select');
                var campoFecha = document.getElementById('resultado-campo-fecha');
                var inputFecha = document.getElementById('resultado-fecha');
                if (!select) return;
                function actualizar() {{
                    var esAgendado = select.value === 'agendado';
                    campoFecha.style.display = esAgendado ? '' : 'none';
                    inputFecha.disabled = !esAgendado;
                }}
                select.addEventListener('change', actualizar);
                actualizar();
            }})();
            </script>
        </div>
    </div>
    <div class="card leads-card shadow-sm mb-2">
        <div class="barra-acento"></div>
        <div class="card-body p-3">
            <h6 class="text-uppercase text-muted small fw-bold mb-2">Cierre de venta (si corresponde)</h6>
            <form method="post" action="/dashboard/lead/{html.escape(telefono)}/venta" id="form-venta">
                {_csrf_campo(request)}
                <input type="hidden" name="version" value="{lead.get('version', 0)}">
                <div class="mb-2">
                    <label class="form-label small text-muted mb-0">Productos vendidos</label>
                    <div id="venta-carrito-lista" class="mb-1"></div>
                    <div class="position-relative" id="venta-producto-catalogo">
                        <input type="text" id="venta-buscar-producto" class="form-control form-control-sm" placeholder="Busca por marca, tipo o modelo y agrégalo..." autocomplete="off">
                        <div id="venta-resultados-producto" class="list-group position-absolute w-100 shadow-sm" style="z-index:10;display:none;max-height:220px;overflow-y:auto;"></div>
                    </div>
                    <button type="button" class="btn btn-link btn-sm p-0 mt-1" id="venta-btn-manual">¿No está en la lista? Agregar manualmente</button>
                </div>
                <div class="mb-2" id="venta-producto-manual" style="display:none;">
                    <label class="form-label small text-muted mb-0">Producto</label>
                    <input type="text" id="venta-manual-producto" class="form-control form-control-sm mb-1" placeholder="Ej: Terma Rheem 10L GN + Combo">
                    <label class="form-label small text-muted mb-0">Precio (S/)</label>
                    <input type="text" id="venta-manual-precio" class="form-control form-control-sm mb-1" placeholder="Ej: 1549">
                    <label class="form-label small text-muted mb-0">Marca</label>
                    <input type="text" id="venta-manual-marca" class="form-control form-control-sm mb-1" placeholder="Ej: Rheem">
                    <label class="form-label small text-muted mb-0">Proveedor</label>
                    <input type="text" id="venta-manual-proveedor" class="form-control form-control-sm mb-1" placeholder="Ej: Dalka S.A.C">
                    <div class="d-flex gap-2">
                        <button type="button" class="btn btn-sm btn-outline-primary" id="venta-btn-agregar-manual">Agregar al carrito</button>
                        <button type="button" class="btn btn-link btn-sm p-0" id="venta-btn-catalogo">Volver a buscar en el catálogo</button>
                    </div>
                </div>
                <input type="hidden" name="lineas_venta" id="venta-lineas-json" value="">
                <div class="mb-2">
                    <label class="form-label small text-muted mb-0">Modalidad de pago</label>
                    <select name="modalidad_pago" id="venta-modalidad" class="form-select form-select-sm">
                        <option value="">Selecciona...</option>
                        {opciones_modalidad}
                    </select>
                </div>
                <div class="mb-2" id="venta-campo-cuotas">
                    <label class="form-label small text-muted mb-0">Cuotas ({CUOTAS_MIN} a {CUOTAS_MAX} meses)</label>
                    <input type="number" name="cuotas" id="venta-cuotas" class="form-control form-control-sm"
                           min="{CUOTAS_MIN}" max="{CUOTAS_MAX}" step="1"
                           value="{html.escape(lead.get('cuotas') or '')}" placeholder="Ej: 24">
                </div>
                <div class="mb-2">
                    <label class="form-label small text-muted mb-0">Medio de pago</label>
                    <input type="text" name="medio_pago" id="venta-medio-financiado" class="form-control form-control-sm" value="{MEDIO_PAGO_FINANCIADO}" readonly>
                    <select name="medio_pago" id="venta-medio-contado" class="form-select form-select-sm">
                        <option value="">Selecciona...</option>
                        {opciones_medio_contado}
                    </select>
                </div>
                <p class="text-danger small mb-2" id="venta-error" style="display:none"></p>
                <button type="button" class="btn btn-sm btn-primary" id="btn-guardar-venta">Guardar venta</button>
            </form>
            <div class="modal fade" id="modal-confirmar-venta" tabindex="-1">
                <div class="modal-dialog">
                    <div class="modal-content">
                        <div class="modal-header">
                            <h5 class="modal-title"><i class="bi bi-bag-check-fill" style="color:var(--gaso-azul)"></i> Confirmar pedido</h5>
                            <button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="Cerrar"></button>
                        </div>
                        <div class="modal-body">
                            <div id="modal-venta-items"></div>
                            <hr class="my-2">
                            <div class="d-flex justify-content-between align-items-center fw-bold">
                                <span>Total</span>
                                <span id="modal-venta-total"></span>
                            </div>
                            <p class="text-muted small mt-3 mb-0">¿Confirmas que quieres registrar este pedido?</p>
                        </div>
                        <div class="modal-footer">
                            <button type="button" class="btn btn-outline-secondary btn-sm" data-bs-dismiss="modal">Cancelar</button>
                            <button type="button" class="btn btn-primary btn-sm" id="btn-confirmar-venta">Sí, guardar venta</button>
                        </div>
                    </div>
                </div>
            </div>
            <script>
            (function() {{
                var form = document.getElementById('form-venta');
                if (!form) return;
                var selectModalidad = document.getElementById('venta-modalidad');
                var campoCuotas = document.getElementById('venta-campo-cuotas');
                var selectCuotas = document.getElementById('venta-cuotas');
                var medioFinanciado = document.getElementById('venta-medio-financiado');
                var medioContado = document.getElementById('venta-medio-contado');

                var buscarInput = document.getElementById('venta-buscar-producto');
                var resultadosBox = document.getElementById('venta-resultados-producto');
                var listaCarrito = document.getElementById('venta-carrito-lista');
                var hiddenLineas = document.getElementById('venta-lineas-json');
                var bloqueManual = document.getElementById('venta-producto-manual');
                var btnManual = document.getElementById('venta-btn-manual');
                var btnCatalogo = document.getElementById('venta-btn-catalogo');
                var btnAgregarManual = document.getElementById('venta-btn-agregar-manual');
                var manualProducto = document.getElementById('venta-manual-producto');
                var manualPrecio = document.getElementById('venta-manual-precio');
                var manualMarca = document.getElementById('venta-manual-marca');
                var manualProveedor = document.getElementById('venta-manual-proveedor');

                var carrito = {lineas_venta_json};

                function escapar(texto) {{
                    var div = document.createElement('div');
                    div.textContent = texto || '';
                    return div.innerHTML;
                }}

                function pintarCarrito() {{
                    if (!carrito.length) {{
                        listaCarrito.innerHTML = '<p class="text-muted small mb-1">Aún no agregaste ningún producto.</p>';
                    }} else {{
                        listaCarrito.innerHTML = carrito.map(function(item, i) {{
                            var etiqueta = (item.marca ? escapar(item.marca) + ' — ' : '') + escapar(item.producto) +
                                (item.precio ? ' &middot; S/ ' + escapar(item.precio) : '');
                            return '<div class="d-flex align-items-center justify-content-between border rounded px-2 py-1 mb-1 small">' +
                                '<span><i class="bi bi-check-circle-fill text-success"></i> ' + etiqueta + '</span>' +
                                '<button type="button" class="btn btn-sm btn-link text-danger p-0 btn-quitar-linea" data-i="' + i + '" title="Quitar"><i class="bi bi-x-lg"></i></button>' +
                                '</div>';
                        }}).join('');
                    }}
                    hiddenLineas.value = JSON.stringify(carrito);
                }}
                pintarCarrito();

                listaCarrito.addEventListener('click', function(ev) {{
                    var btn = ev.target.closest('.btn-quitar-linea');
                    if (!btn) return;
                    carrito.splice(parseInt(btn.getAttribute('data-i'), 10), 1);
                    pintarCarrito();
                }});

                function activarModoManual(manual) {{
                    bloqueManual.style.display = manual ? '' : 'none';
                }}
                btnManual.addEventListener('click', function() {{ activarModoManual(true); }});
                btnCatalogo.addEventListener('click', function() {{ activarModoManual(false); }});

                btnAgregarManual.addEventListener('click', function() {{
                    var producto = manualProducto.value.trim();
                    if (!producto) {{ manualProducto.focus(); return; }}
                    carrito.push({{
                        producto: producto,
                        precio: manualPrecio.value.trim(),
                        marca: manualMarca.value.trim(),
                        proveedor: manualProveedor.value.trim(),
                    }});
                    pintarCarrito();
                    manualProducto.value = '';
                    manualPrecio.value = '';
                    manualMarca.value = '';
                    manualProveedor.value = '';
                    activarModoManual(false);
                }});

                var timeoutBusqueda;
                buscarInput.addEventListener('input', function() {{
                    clearTimeout(timeoutBusqueda);
                    var q = buscarInput.value.trim();
                    if (q.length < 2) {{ resultadosBox.style.display = 'none'; return; }}
                    timeoutBusqueda = setTimeout(function() {{
                        fetch('/dashboard/lead/{html.escape(telefono)}/buscar-producto?q=' + encodeURIComponent(q))
                            .then(function(r) {{ return r.json(); }})
                            .then(function(productos) {{
                                if (!productos.length) {{
                                    resultadosBox.innerHTML = '<div class="list-group-item small text-muted">Sin resultados en el catálogo</div>';
                                }} else {{
                                    resultadosBox.innerHTML = productos.map(function(p) {{
                                        return '<button type="button" class="list-group-item list-group-item-action small py-2" ' +
                                            'data-id="' + escapar(String(p.id == null ? '' : p.id)) + '" ' +
                                            'data-descripcion="' + escapar(p.descripcion) + '" data-marca="' + escapar(p.marca) + '" ' +
                                            'data-proveedor="' + escapar(p.proveedor) + '" data-precio="' + escapar(p.precio) + '">' +
                                            '<strong>' + escapar(p.marca) + '</strong> — ' + escapar(p.descripcion) +
                                            ' <span class="text-muted">S/ ' + escapar(p.precio) + '</span></button>';
                                    }}).join('');
                                }}
                                resultadosBox.style.display = 'block';
                            }});
                    }}, 250);
                }});

                resultadosBox.addEventListener('click', function(ev) {{
                    var btn = ev.target.closest('button[data-descripcion]');
                    if (!btn) return;
                    carrito.push({{
                        // Elegido del catálogo: viaja el id real del producto.
                        // El modo manual de más arriba no lo manda (no hay
                        // producto de catálogo detrás) y el backend lo guarda
                        // como null — sigue siendo opcional a propósito.
                        producto_id: btn.getAttribute('data-id') || null,
                        producto: btn.getAttribute('data-descripcion'),
                        precio: btn.getAttribute('data-precio'),
                        marca: btn.getAttribute('data-marca'),
                        proveedor: btn.getAttribute('data-proveedor'),
                    }});
                    pintarCarrito();
                    buscarInput.value = '';
                    resultadosBox.style.display = 'none';
                    resultadosBox.innerHTML = '';
                }});

                document.addEventListener('click', function(ev) {{
                    if (ev.target !== buscarInput && !resultadosBox.contains(ev.target)) {{
                        resultadosBox.style.display = 'none';
                    }}
                }});

                function actualizar() {{
                    var esFinanciado = selectModalidad.value === 'financiado';
                    campoCuotas.style.display = esFinanciado ? '' : 'none';
                    selectCuotas.disabled = !esFinanciado;
                    medioFinanciado.style.display = esFinanciado ? '' : 'none';
                    medioFinanciado.disabled = !esFinanciado;
                    medioContado.style.display = esFinanciado ? 'none' : '';
                    medioContado.disabled = esFinanciado;
                }}

                selectModalidad.addEventListener('change', actualizar);
                actualizar();

                // Antes de guardar de verdad, un modal tipo "resumen de pedido"
                // (como en retail) con cada producto, su precio y el total —
                // para que el asesor confirme antes de registrar la venta. Si
                // el carrito está vacío no hay pedido que confirmar (ej. borrar
                // una venta ya guardada), así que se manda directo.
                var btnGuardar = document.getElementById('btn-guardar-venta');
                var btnConfirmar = document.getElementById('btn-confirmar-venta');
                var modalEl = document.getElementById('modal-confirmar-venta');
                var modalItems = document.getElementById('modal-venta-items');
                var modalTotal = document.getElementById('modal-venta-total');
                var ventaError = document.getElementById('venta-error');

                // El modal vive dentro del panel "Detalles del lead" (offcanvas),
                // que usa transform para su animación — eso rompe cómo Bootstrap
                // posiciona el modal y su fondo oscuro (queda todo congelado sin
                // responder). Sacarlo al final de <body> antes de mostrarlo lo
                // arregla; es el fix estándar de Bootstrap para este caso.
                if (modalEl.parentElement !== document.body) {{
                    document.body.appendChild(modalEl);
                }}

                function validarFormularioVenta() {{
                    ventaError.style.display = 'none';
                    selectModalidad.classList.remove('is-invalid');
                    selectCuotas.classList.remove('is-invalid');
                    medioContado.classList.remove('is-invalid');
                    if (!selectModalidad.value) {{
                        ventaError.textContent = 'Selecciona la modalidad de pago antes de guardar la venta.';
                        ventaError.style.display = 'block';
                        selectModalidad.classList.add('is-invalid');
                        selectModalidad.focus();
                        return false;
                    }}
                    if (selectModalidad.value === 'financiado' && !selectCuotas.value) {{
                        ventaError.textContent = 'Selecciona las cuotas antes de guardar la venta.';
                        ventaError.style.display = 'block';
                        selectCuotas.classList.add('is-invalid');
                        selectCuotas.focus();
                        return false;
                    }}
                    if (selectModalidad.value === 'contado' && !medioContado.value) {{
                        ventaError.textContent = 'Selecciona el medio de pago antes de guardar la venta.';
                        ventaError.style.display = 'block';
                        medioContado.classList.add('is-invalid');
                        medioContado.focus();
                        return false;
                    }}
                    return true;
                }}

                function calcularTotal() {{
                    var total = 0;
                    var todosNumericos = true;
                    carrito.forEach(function(item) {{
                        var n = parseFloat((item.precio || '0').replace(',', '.'));
                        if (isNaN(n)) {{ todosNumericos = false; return; }}
                        total += n;
                    }});
                    return todosNumericos ? 'S/ ' + total.toFixed(2) : '—';
                }}

                btnGuardar.addEventListener('click', function() {{
                    if (!carrito.length) {{ form.requestSubmit ? form.requestSubmit() : form.submit(); return; }}
                    if (!validarFormularioVenta()) return;
                    modalItems.innerHTML = carrito.map(function(item) {{
                        var etiqueta = (item.marca ? escapar(item.marca) + ' — ' : '') + escapar(item.producto);
                        var precio = item.precio ? 'S/ ' + escapar(item.precio) : '-';
                        return '<div class="d-flex justify-content-between align-items-center py-1 gap-2 small">' +
                            '<span>' + etiqueta + '</span><span class="text-muted flex-shrink-0 ps-2">' + precio + '</span></div>';
                    }}).join('');
                    modalTotal.textContent = calcularTotal();
                    if (window.bootstrap && bootstrap.Modal) {{
                        bootstrap.Modal.getOrCreateInstance(modalEl).show();
                    }} else {{
                        form.requestSubmit ? form.requestSubmit() : form.submit();
                    }}
                }});

                btnConfirmar.addEventListener('click', function() {{
                    if (window.bootstrap && bootstrap.Modal) {{
                        var instancia = bootstrap.Modal.getInstance(modalEl);
                        if (instancia) instancia.hide();
                    }}
                    form.requestSubmit ? form.requestSubmit() : form.submit();
                }});
            }})();
            </script>
        </div>
    </div>
    """


# ── Copiloto IA (MAIEK_AI_PRODUCT_PATTERNS.md, Cap. 5) ─────────────────
#
# Primera implementación: contenedor extensible con 3 zonas (equivalente al
# `AI Action Panel` del CDS). Solo la Zona de contexto tiene una capacidad
# activa en este Sprint — Resumen IA (`AI Summary`), bajo demanda, sin
# protocolo de confianza ni persistencia (independiente de brain.py del
# todo). La Zona de sugerencias (`AI Suggestion Card` + `AI Confidence
# Indicator`) y la Zona de métricas de apoyo NO se renderizan todavía — no
# hay nada real que mostrar ahí (depende de persistir SugerenciaIA, todavía
# diferido a Data Architecture Fase 2) y el propio Cap. 5 prohíbe mostrar un
# ítem vacío/deshabilitado en vez de omitirlo. Cuando esas capacidades
# existan, se agregan como bloques nuevos dentro de _copiloto_ia() sin tocar
# el contenedor ni el mecanismo de colapso.


def _script_copiloto_ia(telefono: str) -> str:
    return f"""
    <script>
    (function() {{
        const telefono = {telefono!r};
        const contenedor = document.getElementById('copiloto-resumen-contenido');
        if (!contenedor) return;
        let resumenGenerado = false;

        function pintarCargando() {{
            contenedor.innerHTML = '<div class="copiloto-resumen-texto text-muted">'
                + '<span class="spinner-border spinner-border-sm"></span> Generando resumen...</div>';
        }}

        function pintarResumen(texto) {{
            resumenGenerado = true;
            contenedor.innerHTML =
                '<div class="copiloto-resumen-texto"></div>'
                + '<div class="copiloto-resumen-meta">Generado ahora</div>'
                + '<button type="button" class="btn btn-sm btn-link p-0 mt-1" id="copiloto-btn-resumen">Actualizar resumen</button>';
            contenedor.querySelector('.copiloto-resumen-texto').textContent = texto;
        }}

        function generar() {{
            pintarCargando();
            fetch('/dashboard/lead/' + encodeURIComponent(telefono) + '/resumen-ia', {{ method: 'POST', headers: {{ 'X-CSRF-Token': window.__csrfToken() }} }})
                .then(function(r) {{ return r.json(); }})
                .then(function(datos) {{ pintarResumen(datos.resumen); }})
                .catch(function() {{ pintarResumen('No se pudo generar el resumen — intentá de nuevo.'); }});
        }}

        contenedor.addEventListener('click', function(ev) {{
            if (ev.target.closest('#copiloto-btn-resumen')) generar();
        }});

        // Marca el resumen ya mostrado como desactualizado si llega un
        // mensaje nuevo de ESTE lead mientras tanto — nunca se regenera
        // solo (el usuario decide cuándo pedir uno nuevo).
        function alEventoWS(evento) {{
            if (!document.getElementById('copiloto-resumen-contenido')) {{
                if (window.__gasoWS) window.__gasoWS.off(alEventoWS);
                return;
            }}
            if (evento.tipo === 'mensaje_nuevo' && evento.telefono === telefono && resumenGenerado) {{
                var meta = contenedor.querySelector('.copiloto-resumen-meta');
                if (meta && !meta.classList.contains('copiloto-resumen-desactualizado')) {{
                    meta.classList.add('copiloto-resumen-desactualizado');
                    meta.innerHTML = '<i class="bi bi-arrow-clockwise"></i> Hay mensajes nuevos — este resumen puede estar desactualizado.';
                }}
            }}
        }}
        if (window.__gasoWS) window.__gasoWS.on(alEventoWS);
    }})();
    </script>
    """


def _copiloto_ia(telefono: str) -> str:
    return f"""
    <div class="copiloto-panel" id="copiloto-panel">
        <div class="copiloto-header" onclick="document.getElementById('copiloto-panel').classList.toggle('abierto')">
            <span class="titulo"><i class="bi bi-stars"></i> Copiloto IA</span>
            <i class="bi bi-chevron-down copiloto-chevron"></i>
        </div>
        <div class="copiloto-cuerpo">
            <div class="copiloto-zona-titulo">Resumen de la conversación</div>
            <div id="copiloto-resumen-contenido">
                <button type="button" class="btn btn-sm btn-outline-primary" id="copiloto-btn-resumen">
                    <i class="bi bi-magic"></i> Generar resumen
                </button>
            </div>
        </div>
    </div>
    {_script_copiloto_ia(telefono)}
    """


_ICONOS_EVENTO_LEAD = {
    "resultado_cambiado": "bi-flag-fill",
    "asignado": "bi-person-check-fill",
    "desasignado": "bi-person-dash-fill",
    "venta_registrada": "bi-cash-coin",
    "atendido_manual": "bi-check2-circle",
}


async def _render_timeline_lead(telefono: str) -> str:
    """Conversation Timeline (MAIEK_AI_PRODUCT_PATTERNS.md, Cap. 6) — eventos
    de NEGOCIO del lead (resultado/asignación/venta), del más reciente al más
    antiguo; distinto del chat crudo, que se ve aparte en la columna del chat."""
    eventos = await listar_eventos_lead(telefono)
    if not eventos:
        return ""
    items = "".join(
        f'<div class="d-flex align-items-start gap-2 py-1">'
        f'<i class="bi {_ICONOS_EVENTO_LEAD.get(e["tipo"], "bi-dot")} text-muted" style="font-size:.8rem;margin-top:3px"></i>'
        f'<div class="flex-grow-1" style="font-size:.78rem">'
        f'<div>{html.escape(e["descripcion"])}</div>'
        f'<div class="text-muted" style="font-size:.7rem">{html.escape(e.get("autor") or "Automático")} &middot; {_tiempo_relativo(e["creado"])}</div>'
        f'</div></div>'
        for e in eventos
    )
    return f"""
    <div class="card leads-card shadow-sm mb-2">
        <div class="barra-acento"></div>
        <div class="card-body p-3">
            <h6 class="text-uppercase text-muted small fw-bold mb-2">Historial</h6>
            {items}
        </div>
    </div>
    """


async def _bloque_resumen_cliente(
    telefono: str, lead: dict, usuario: dict, request: Request | None = None,
    hay_conflicto: bool = False, evento_conflicto: dict | None = None,
) -> str:
    """Resumen del cliente con el mismo lenguaje visual 'ejecutivo' de la
    tabla de leads (card con barra de acento, badge suave, tipografía
    compacta) — seguido de los formularios de gestión, todo en una sola
    columna que se muestra siempre junto al chat."""
    nombre_mostrado = lead.get("nombre") or "(sin nombre)"
    badge_canal = _badge_canal(lead.get("numero_whatsapp_id"), await _mapa_canales(usuario["negocio_id"]))

    filas_info = "".join(
        f'<div class="d-flex justify-content-between align-items-center py-1 gap-2">'
        f'<span class="text-muted text-truncate" style="font-size:.76rem">{html.escape(etq)}</span>'
        f'<span class="fw-semibold text-end text-truncate" style="font-size:.83rem">{val}</span></div>'
        for etq, val in [
            ("Interés", html.escape(lead.get("interes") or "-")),
            ("Etapa", html.escape((lead.get("paso_flujo") or "-").replace("_", " ").capitalize())),
            ("Resultado", _pill_resultado(lead.get("resultado"))),
            ("Cita agendada", lead["fecha_agendada"].strftime("%d/%m/%Y %H:%M") if lead.get("fecha_agendada") else "-"),
            ("Campaña", html.escape(lead.get("campana_origen") or "-")),
            ("Modalidad de pago", html.escape((lead.get("modalidad_pago") or "-").capitalize())),
            ("Última actividad", lead["actualizado"].strftime("%d/%m/%Y %H:%M")),
        ]
    )

    # Un lead puede vender varios artefactos, un servicio, o un mix — se
    # lista cada línea en vez de un solo campo "Producto vendido".
    lineas_venta = await listar_lineas_venta(telefono)
    bloque_lineas_venta = ""
    if lineas_venta:
        filas_venta_partes = []
        for l in lineas_venta:
            etiqueta = html.escape((l["marca"] + " — " if l.get("marca") else "") + l["producto"])
            precio_texto = f"S/ {html.escape(l['precio'])}" if l.get("precio") else "-"
            filas_venta_partes.append(
                '<div class="d-flex justify-content-between align-items-center py-1 gap-2">'
                f'<span class="text-truncate" style="font-size:.8rem">{etiqueta}</span>'
                f'<span class="fw-semibold text-end flex-shrink-0 ps-2" style="font-size:.8rem">{precio_texto}</span></div>'
            )
        filas_venta = "".join(filas_venta_partes)
        bloque_lineas_venta = f"""
        <div class="text-muted" style="font-size:.76rem">Productos vendidos</div>
        {filas_venta}
        """

    return f"""
    {_copiloto_ia(telefono)}
    <div class="card leads-card shadow-sm mb-2">
        <div class="barra-acento"></div>
        <div class="card-body p-3">
            <div class="d-flex align-items-center gap-2 mb-2">
                {_avatar(nombre_mostrado, 44)}
                <div class="overflow-hidden">
                    <div class="fw-bold text-truncate">{html.escape(nombre_mostrado)}</div>
                    <div class="text-muted text-truncate" style="font-size:.8rem">{html.escape(telefono)}</div>
                </div>
            </div>
            {_badge_estado_suave(lead)} {badge_canal}
            <hr class="my-2">
            {filas_info}
            {bloque_lineas_venta}
        </div>
    </div>
    {await _render_timeline_lead(telefono)}
    {await _bloque_gestion_lead(telefono, lead, usuario, request=request, hay_conflicto=hay_conflicto, evento_conflicto=evento_conflicto)}
    """


async def _renderizar_detalle_lead(
    telefono: str, request: Request, usuario: dict, estado: str = "todos", asesor: str = "",
    hay_conflicto: bool = False,
) -> HTMLResponse:
    """Vista de un lead: resumen del cliente (datos + formularios de gestión)
    y la conversación completa visibles a la vez, sin tener que saltar entre
    dos páginas distintas. Función interna (no ruta) para que los 3 endpoints
    de escritura del CRM (resultado/venta/asignar) puedan reusarla tal cual
    cuando detectan un conflicto de edición (Cap. 6) — mismo render que la
    ruta GET, con el banner de conflicto de más."""
    lead = await obtener_lead(telefono, negocio_id=usuario["negocio_id"])
    if lead is None:
        raise HTTPException(status_code=404, detail="Lead no encontrado")
    _verificar_acceso_lead(usuario, lead)

    if usuario["rol"] == "asesor" and not lead.get("visto_asesor", True):
        await marcar_lead_visto(telefono)
        lead["visto_asesor"] = True

    if lead.get("revision_prioritaria"):
        await limpiar_revision_prioritaria(telefono)
        lead["revision_prioritaria"] = False

    datos = await _datos_bandeja(usuario, estado, asesor)
    rail = await _renderizar_rail_estados(usuario, datos, estado, asesor)
    asesores_equipo = await listar_asesores(usuario["negocio_id"]) if datos["vision_total"] else []
    resumen_barra = _barra_resumen(datos, asesores_equipo, estado) if datos["vision_total"] else ""

    # La lista de conversaciones solo se muestra si se llegó filtrando por un
    # asesor del equipo (se abrió desde su bandeja de chats) — así se puede
    # seguir eligiendo otra conversación sin volver atrás. Si se entró desde
    # la tabla de "Todos los leads", no hace falta y solo quita espacio.
    lista = await _renderizar_lista_conversaciones(usuario, datos, telefono_activo=telefono, asesor_filtro=asesor) if asesor else ""

    evento_conflicto = None
    if hay_conflicto:
        eventos_recientes = await listar_eventos_lead(telefono, limite=1)
        evento_conflicto = eventos_recientes[0] if eventos_recientes else None

    nombre_mostrado = lead.get("nombre") or "(sin nombre)"
    resumen_cliente_html = await _bloque_resumen_cliente(
        telefono, lead, usuario, request=request, hay_conflicto=hay_conflicto, evento_conflicto=evento_conflicto,
    )
    bloque_respuesta_html = await _bloque_respuesta(telefono, lead)

    if asesor:
        # Ya se ve la lista de conversaciones del asesor junto al chat — con
        # el resumen también fijo serían 4 columnas apretadas. Acá el resumen
        # vuelve a ser un panel de acceso rápido (offcanvas) como antes.
        boton_resumen = """
        <button class="btn btn-outline-secondary btn-sm" type="button" data-bs-toggle="offcanvas" data-bs-target="#offcanvasResumen">
            <i class="bi bi-person-vcard"></i> Detalles del lead
        </button>
        """
        cuerpo_chat = f"""
        <div class="chat-mensajes-wrap">
            <div class="card shadow-sm">
                <div class="card-body h-100" id="chat" style="overflow-y:auto;"><p class="text-muted">Cargando...</p></div>
            </div>
        </div>
        <div class="chat-reply-fijo">
            {bloque_respuesta_html}
        </div>
        <div class="offcanvas offcanvas-end" tabindex="-1" id="offcanvasResumen">
            <div class="offcanvas-header border-bottom">
                <h5 class="offcanvas-title fw-semibold"><i class="bi bi-person-vcard" style="color:var(--gaso-azul)"></i> Detalles del lead</h5>
                <button type="button" class="btn-close" data-bs-dismiss="offcanvas"></button>
            </div>
            <div class="offcanvas-body">
                {resumen_cliente_html}
            </div>
        </div>
        """
    else:
        # Sin lista de conversaciones (se entró desde la tabla de leads): el
        # resumen queda fijo al lado del chat, las 2 secciones siempre visibles.
        boton_resumen = """
        <button type="button" class="btn btn-outline-secondary btn-sm btn-resumen-movil" onclick="document.getElementById('lead-resumen-col').classList.toggle('abierto')">
            <i class="bi bi-person-vcard"></i> Resumen
        </button>
        """
        cuerpo_chat = f"""
        <div class="lead-vista">
            <div class="lead-resumen-col" id="lead-resumen-col">
                {resumen_cliente_html}
            </div>
            <div class="lead-chat-col">
                <div class="chat-mensajes-wrap">
                    <div class="card shadow-sm">
                        <div class="card-body h-100" id="chat" style="overflow-y:auto;"><p class="text-muted">Cargando...</p></div>
                    </div>
                </div>
                <div class="chat-reply-fijo">
                    {bloque_respuesta_html}
                </div>
            </div>
        </div>
        """

    # El interés va directo en la cabecera (no solo en el resumen lateral)
    # porque en la vista filtrada por asesor el resumen queda detrás de un
    # botón (offcanvas, para no apretar el layout a 4 columnas) — sin esto,
    # el dato más importante para responder quedaba a un clic de distancia.
    interes_linea = ""
    if lead.get("interes"):
        interes_linea = (
            f'<div class="text-muted text-truncate" style="font-size:.72rem" title="{html.escape(lead["interes"])}">'
            f'<i class="bi bi-tag-fill"></i> {html.escape(lead["interes"])}</div>'
        )

    panel = f"""
    <div class="chat-header-fijo d-flex align-items-center justify-content-between gap-2">
        <div class="d-flex align-items-center gap-2 overflow-hidden">
            <a href="/dashboard" class="btn-volver-movil text-dark" data-ajax="1"><i class="bi bi-arrow-left fs-5"></i></a>
            {_avatar(nombre_mostrado, 32)}
            <div class="overflow-hidden lh-sm">
                <div class="text-truncate">
                    <span class="fw-semibold">{html.escape(nombre_mostrado)}</span>
                    <span class="text-muted small">&middot; {html.escape(telefono)}</span>
                </div>
                {interes_linea}
            </div>
        </div>
        {boton_resumen}
    </div>

    {cuerpo_chat}

    {_script_chat_en_vivo(telefono, bool(lead.get("asesor_asignado")))}
    """

    cuerpo = f"""
    {resumen_barra}
    <div class="shell{' con-resumen' if resumen_barra else ''} d-flex">
        {rail}
        {lista}
        <div class="main-pane chat-mode flex-grow-1">{panel}</div>
    </div>
    """
    return _pagina(nombre_mostrado, usuario, cuerpo, es_chat=True, request=request)


def _dto_lead_detalle(lead: dict, lineas: list[dict], eventos: list[dict]) -> dict:
    """Detalle de un Lead tal como lo consume la Nueva Experiencia (Next.js).

    Superconjunto del DTO de la fila de Pipeline (_dto_lead_pipeline): mismos
    nombres para los mismos campos —incluida la separación `id`/`telefono`—
    más lo que solo tiene sentido en el detalle: la venta y el Conversation
    Timeline. Los campos internos del panel (paso_flujo, visto_asesor,
    fallos_tecnicos, numero_whatsapp_id, los producto_*/…_venta superados por
    LineaVenta) NO viajan: esto es el contrato de la pantalla de detalle, no
    un volcado de la fila.

    `venta` es un objeto propio (no campos sueltos del lead) porque la venta
    es una sola unidad: líneas + una forma de pago para todas. Es null cuando
    no hay ninguna línea — así el cliente distingue "no hay venta" de "hay una
    venta sin forma de pago cargada" sin inspeccionar campo por campo.

    `creado`/`actualizado`/`eventos[].creado`/`venta.lineas[].creado` llevan
    sufijo `Z`: son instantes reales en UTC, y `new Date()` en el navegador
    los interpreta como hora LOCAL si no declaran la zona (5 h adelantado
    para Lima). `fecha_agendada` NO lleva `Z`: es la hora de una cita tal
    como la tipeó un humano en su propia zona, no un instante — mismo
    criterio que _dto_lead_pipeline. `iso_utc()` vive en agent/memory.py, la
    capa que comparten este DTO y los de Productos."""
    def _iso(valor):
        return valor.isoformat() if isinstance(valor, datetime) else valor

    venta = None
    if lineas:
        venta = {
            "lineas": [
                {
                    "id": l.get("id"), "producto_id": l.get("producto_id"),
                    "producto": l.get("producto"), "precio": l.get("precio"),
                    "marca": l.get("marca"), "proveedor": l.get("proveedor"), "creado": iso_utc(l.get("creado")),
                }
                for l in lineas
            ],
            "modalidad_pago": lead.get("modalidad_pago"),
            "cuotas": lead.get("cuotas"),
            "cuota_pactada": lead.get("cuota_pactada"),
            "monto_financiado": lead.get("monto_financiado"),
            "tea_pactada": lead.get("tea_pactada"),
            "igv_pactado": lead.get("igv_pactado"),
            "medio_pago": lead.get("medio_pago"),
            # Mismo total que ya muestra la columna "Precio" de la tabla de
            # leads y de la exportación — se reusa _resumen_venta a propósito,
            # para que no existan dos fórmulas del total de una venta que
            # puedan dar números distintos. Es texto, no número, porque el
            # precio de una línea puede no ser numérico (venta manual): en ese
            # caso _resumen_venta devuelve la suma sin resolver ("1200 + a
            # convenir") en vez de mentir con un total.
            "total": _resumen_venta(lineas)["precio_venta"],
        }

    return {
        "id": lead["telefono"],
        "telefono": lead["telefono"],
        "nombre": lead.get("nombre"),
        "interes": lead.get("interes"),
        # Gate Campañas P0 — SCR-03: valor histórico inmutable capturado en el
        # primer contacto (ver `Lead.campana_origen`, first-touch, nunca se
        # sobreescribe). Nunca se resuelve en vivo contra la tabla `Campana`
        # actual — evita mostrar una atribución desincronizada si la campaña
        # cambió de nombre o se desactivó después.
        "campana_origen": lead.get("campana_origen"),
        "resultado": lead.get("resultado"),
        "fecha_agendada": _iso(lead.get("fecha_agendada")),
        # `fecha_cierre` SÍ lleva `Z` (a diferencia de fecha_agendada, justo
        # arriba): es el instante real en que se cerró la venta, no una hora
        # que alguien tipeó.
        "fecha_cierre": iso_utc(lead.get("fecha_cierre")),
        "asesor_asignado": lead.get("asesor_asignado"),
        "pausado_manual": bool(lead.get("pausado_manual")),
        "cerrado_definitivamente_en": iso_utc(lead.get("cerrado_definitivamente_en")),
        "revision_prioritaria": bool(lead.get("revision_prioritaria")),
        "version": lead.get("version"),
        "creado": iso_utc(lead.get("creado")),
        "actualizado": iso_utc(lead.get("actualizado")),
        "venta": venta,
        "eventos": [
            {
                # `id` estable del evento (PK de EventoLead, que es
                # append-only): le da al cliente una clave que no cambia para
                # cada línea del Timeline, en vez de tener que inventarse una
                # con el índice o la fecha.
                "id": e.get("id"),
                "tipo": e.get("tipo"), "descripcion": e.get("descripcion"), "payload": e.get("payload"),
                "autor": e.get("autor"), "creado": iso_utc(e.get("creado")),
            }
            for e in eventos
        ],
    }


# ── Rama JSON de las 3 escrituras del CRM (resultado / venta / asignar) ────
#
# Misma negociación de contenido que el GET (_pide_json_explicitamente): el
# panel legacy sigue recibiendo 303/HTML sin enterarse, y solo quien NOMBRA
# application/json recibe el contrato de abajo. Se extiende la ruta existente
# en vez de abrir rutas paralelas por el mismo motivo que en el GET: mismo
# recurso, mismo control de acceso, mismo forzado por rol — duplicarlas
# obligaría a duplicar esas tres piezas, que son las que no pueden
# desincronizarse.
#
# El contrato es el de Productos, adaptado a lead: {"ok": true, "lead": DTO}
# en éxito, 409 {"ok": false, "detail": ..., "version_actual": N} en conflicto.
# Los errores reales (404 / 403 / 400 / 422) NO se tocan: siguen saliendo por
# HTTPException con su status real y el envelope de agent/api_contrato.py. Un
# conflicto de versión es "tu copia quedó vieja, recargá"; un error real es
# otra cosa, y confundirlos le haría mostrar al frontend un mensaje falso.


async def _json_lead_actualizado(telefono: str, negocio_id: str) -> JSONResponse:
    """Éxito de una escritura: relee el lead YA actualizado y devuelve el
    mismo DTO que sirve GET /dashboard/lead/{telefono} en JSON.

    Se relee a propósito (en vez de parchear en memoria el dict que se leyó al
    entrar a la ruta): la escritura tocó la versión, el `actualizado`, y en el
    caso de venta también LineaVenta y el Timeline. Devolver el estado real
    posterior le ahorra al cliente un GET de vuelta y, sobre todo, le da la
    `version` nueva —sin ella su próximo guardado chocaría siempre.

    `negocio_id` (Gate 5.4, T1): siempre el de la sesión de quien llama —
    nunca se infiere ni se vuelve a resolver acá."""
    lead = await obtener_lead(telefono, negocio_id=negocio_id)
    if lead is None:
        # Solo si alguien borró el lead entre la escritura y esta relectura.
        raise HTTPException(status_code=404, detail="Lead no encontrado")
    lineas = await listar_lineas_venta(telefono, con_metadatos=True)
    eventos = await listar_eventos_lead(telefono)
    return JSONResponse({"ok": True, "lead": _dto_lead_detalle(lead, lineas, eventos)})


async def _json_conflicto_lead(telefono: str, negocio_id: str) -> JSONResponse:
    """409 de conflicto de edición con la versión vigente, para que el cliente
    pueda recargar y comparar sin adivinar (Human Decision Gate). Mismo texto
    que Productos, adaptado a lead. `negocio_id` — mismo criterio que
    `_json_lead_actualizado` (Gate 5.4, T1)."""
    actual = await obtener_lead(telefono, negocio_id=negocio_id)
    if actual is None:
        # intentar_avanzar_version() también da False si el lead ya no existe:
        # eso es un 404, no un conflicto.
        raise HTTPException(status_code=404, detail="Lead no encontrado")
    return JSONResponse(
        {
            "ok": False,
            "detail": "Alguien más modificó este lead mientras lo editabas. Revisa los datos actuales antes de volver a guardar.",
            "version_actual": actual["version"],
        },
        status_code=409,
    )


@router.get("/lead/{telefono}", response_class=HTMLResponse)
async def detalle_lead(
    telefono: str, request: Request, usuario: dict = Depends(_usuario_actual), estado: str = "todos", asesor: str = "",
):
    """Detalle de un Lead — HTML (panel) o JSON (Nueva Experiencia) según el
    Accept, misma negociación de contenido que /dashboard/pipeline (ver
    _pide_json_explicitamente): mismo recurso, mismo control de acceso, una
    sola ruta que forzar.

    La rama JSON NO tiene los efectos de lectura del panel (marcar visto,
    limpiar revisión prioritaria): esos los dispara una persona abriendo la
    conversación, y el frontend nuevo tendrá su propio momento para hacerlo.
    Un GET de API no debería escribir de paso."""
    if _pide_json_explicitamente(request):
        lead = await obtener_lead(telefono, negocio_id=usuario["negocio_id"])
        if lead is None:
            raise HTTPException(status_code=404, detail="Lead no encontrado")
        _verificar_acceso_lead(usuario, lead)
        lineas = await listar_lineas_venta(telefono, con_metadatos=True)
        eventos = await listar_eventos_lead(telefono)
        return JSONResponse(_dto_lead_detalle(lead, lineas, eventos))
    return await _renderizar_detalle_lead(telefono, request, usuario, estado, asesor)


@router.get("/lead/{telefono}/mensajes.json")
async def mensajes_json(telefono: str, usuario: dict = Depends(_usuario_actual)):
    """Endpoint liviano para que el chat se actualice solo, sin recargar la página.

    También es la señal de actividad real para el idle timeout de conexiones
    WS del panel (Gate 4.1 — ver `GestorConexiones.tocar_actividad`): esta
    ruta es la que golpea `usePollingIncondicional` cada 20s desde el
    navegador SIEMPRE que la conversación sigue abierta en pantalla, sin
    importar el estado del WS/SSE — por eso es la fuente de verdad de "el
    navegador sigue ahí", no el tráfico del propio WS."""
    lead = await obtener_lead(telefono, negocio_id=usuario["negocio_id"])
    if lead is None:
        raise HTTPException(status_code=404, detail="Lead no encontrado")
    _verificar_acceso_lead(usuario, lead)
    conversation_activa = await obtener_conversation_activa_de_telefono(telefono, usuario["negocio_id"])
    if conversation_activa:
        gestor_conexiones.tocar_actividad(usuario["username"], conversation_activa["id"])
    historial = await servicio_conversacion.obtener_historial(telefono, limite=200)
    return JSONResponse(historial)


@router.get("/conversation/{conversation_id}/mensajes.json")
async def conversation_mensajes_json(conversation_id: str, usuario: dict = Depends(_usuario_actual)):
    """GATE 2.2 (Conversation ID Cutover) — equivalente de `mensajes_json`
    (arriba) para la Nueva Experiencia: historial de UNA Conversation
    puntual, identificada por `conversation_id`, no por `telefono`. Corrige
    el hallazgo del Gate 2: `/lead/{telefono}/mensajes.json` devuelve el
    historial mezclado de TODAS las Conversation sucesivas de un mismo
    Contact (DR-4) porque filtra por teléfono; esta ruta filtra por la
    Conversation exacta que se pide.

    Mismo criterio de acceso de dos capas que el resto de las rutas
    `/conversation/{id}...` (Gate 5.3): `obtener_conversation_detalle` da
    404 cross-tenant, `_verificar_acceso_conversation` da 403 si es del
    mismo Negocio pero no es la propia cartera del Asesor.

    `/lead/{telefono}/mensajes.json` NO se toca ni se elimina — sigue
    siendo la ruta del panel legacy, sin cambios de comportamiento."""
    conversation = await obtener_conversation_detalle(conversation_id, usuario["negocio_id"])
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversación no encontrada")
    _verificar_acceso_conversation(usuario, conversation["asesor_asignado"])
    # Misma señal de actividad real para el idle timeout de conexiones WS
    # que ya usa `mensajes_json` (Gate 4.1) — este endpoint reemplaza a ese
    # para la Nueva Experiencia, así que tiene que conservar el mismo golpe
    # de "el navegador sigue ahí" o el WS se cerraría por inactividad
    # mientras la conversación sigue abierta en pantalla.
    gestor_conexiones.tocar_actividad(usuario["username"], conversation_id)
    historial = await servicio_conversacion.obtener_historial_de_conversation(
        conversation_id, usuario["negocio_id"], limite=200,
    )
    return JSONResponse(historial)


@router.get("/conversation/{conversation_id}/conversaciones-previas.json")
async def conversation_previas_json(conversation_id: str, usuario: dict = Depends(_usuario_actual)):
    """Gate 2026-09-23 (punto b del hallazgo DR-4) — Conversation(s)
    CERRADAS anteriores del mismo Contact, cada una con su propio
    historial, para que el panel las muestre como contexto por encima de
    la conversación activa. Endpoint NUEVO y separado de `mensajes.json`
    a propósito: no cambia esa forma de respuesta (un array plano que ya
    consume el frontend en producción) — el panel pide esto aparte,
    solo cuando quiere pintar el contexto previo.

    Mismo control de acceso de dos capas que el resto de rutas
    `/conversation/{id}...`: 404 cross-tenant, 403 si es de otro Asesor."""
    conversation = await obtener_conversation_detalle(conversation_id, usuario["negocio_id"])
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversación no encontrada")
    _verificar_acceso_conversation(usuario, conversation["asesor_asignado"])
    previas = await servicio_conversacion.listar_conversaciones_previas_con_historial(
        conversation_id, usuario["negocio_id"],
    )
    return JSONResponse(previas)


@router.post("/lead/{telefono}/resumen-ia")
async def generar_resumen_ia(telefono: str, usuario: dict = Depends(_usuario_actual), _csrf: None = Depends(verificar_csrf)):
    """Resumen IA bajo demanda (Copiloto — Cap. 5, primera capacidad activa)
    — sin persistir nada: se genera cada vez que se pide, no hay "el" resumen
    guardado del lead. Mismo control de acceso que el resto de endpoints del
    lead (un Asesor solo puede pedirlo de sus propios leads)."""
    lead = await obtener_lead(telefono, negocio_id=usuario["negocio_id"])
    if lead is None:
        raise HTTPException(status_code=404, detail="Lead no encontrado")
    _verificar_acceso_lead(usuario, lead)
    historial = await servicio_conversacion.obtener_historial(telefono, limite=200)
    resumen = await generar_resumen_conversacion(historial)
    # `error` (2026-11-04): «sin_saldo» o «fallo» cuando el texto es el aviso fijo y no un resumen. `resumen` se
    # mantiene igual, porque el panel legacy solo lee ese campo.
    error = "sin_saldo" if resumen == RESUMEN_SIN_SALDO else "fallo" if resumen == RESUMEN_FALLIDO else None
    return JSONResponse({"resumen": resumen, "error": error})


@router.get("/notificaciones.json")
async def notificaciones_json(usuario: dict = Depends(_usuario_actual)):
    """Endpoint liviano para las notificaciones de escritorio (lead nuevo
    asignado / agendado próximo) — lo sondea el shell base de la página,
    no el chat, así funciona sin importar qué pantalla del panel esté
    mirando el asesor. Solo lo que le corresponde a él mismo (no lo que ve
    un admin/supervisor de vision total, para no saturarlo con lo de todos)."""
    username = usuario["username"]
    # fecha_agendada se guarda tal cual la tipeó el asesor en su navegador
    # (hora de Perú, sin zona horaria) — Railway corre en UTC, así que hay
    # que restar el offset acá para comparar peras con peras.
    ahora_peru = datetime.utcnow() - timedelta(hours=5)
    limite_peru = ahora_peru + timedelta(minutes=10)

    leads = await listar_leads(usuario["negocio_id"], asesor_asignado=username)
    leads_nuevos = [
        {"telefono": l["telefono"], "nombre": l["nombre"] or l["telefono"]}
        for l in leads if not l["visto_asesor"]
    ]

    agendados = await listar_leads_agendados(usuario["negocio_id"], asesor_asignado=username)
    agendados_proximos = [
        {
            "telefono": a["telefono"],
            "nombre": a["nombre"] or a["telefono"],
            "fecha_agendada": a["fecha_agendada"].isoformat(),
            "hora": a["fecha_agendada"].strftime("%H:%M"),
        }
        for a in agendados
        if a["fecha_agendada"] and ahora_peru <= a["fecha_agendada"] <= limite_peru
    ]

    return JSONResponse({"leads_nuevos": leads_nuevos, "agendados_proximos": agendados_proximos})


# Ventana de atención de 24 horas de WhatsApp (Meta): un negocio solo puede
# mandar mensajes "libres" (no-plantilla) dentro de las 24h desde el ÚLTIMO
# mensaje entrante real del cliente — pasado ese plazo, Meta rechaza el envío
# y solo una plantilla aprobada puede reabrir la conversación. Desde el 2026-10-06
# el asesor puede mandar esa plantilla desde el chat (`/lead/{tel}/responder-plantilla`,
# ver agent/plantilla_retomar.py). La regla de "último mensaje del cliente" (sin
# contar reacciones) vive en `memory.obtener_estado_ventana`.
VENTANA_ATENCION_HORAS = 24

TEXTO_VENTANA_CERRADA = (
    "La ventana de 24 horas de WhatsApp está cerrada para este cliente: Meta solo permite enviarle "
    "una plantilla aprobada hasta que él vuelva a escribir."
)


class ErrorConCodigo(HTTPException):
    """HTTPException con un `codigo` semántico y campos propios en el cuerpo (ver `api_contrato`: suma
    `cuerpo_extra` al cuerpo uniforme del error, que sigue trayendo `mensaje`; aquí además `detail`)."""

    def __init__(self, status_code: int, detail: str, codigo: str, **extra):
        super().__init__(status_code=status_code, detail=detail)
        self.cuerpo_extra = {"codigo": codigo, "detail": detail, **extra}


class VentanaCerradaError(ErrorConCodigo):
    """409 de "ventana de 24 h cerrada" con cuerpo estructurado: además del `mensaje`/`detail` en
    español, el cuerpo trae `codigo: "ventana_cerrada"`, `puede_plantilla`, `plantilla_disponible`
    y los datos del anuncio (`fep_abierta`, `fep_vence_en`) para que el panel ofrezca la
    plantilla sin adivinar."""

    def __init__(self, extra: dict):
        super().__init__(409, TEXTO_VENTANA_CERRADA, "ventana_cerrada", **extra)


async def _dto_ventana_whatsapp(telefono: str, negocio_id: str | None, estado: dict | None = None) -> dict:
    """Estado de la ventana de WhatsApp de un cliente listo para el panel. Los nombres
    `ventana_abierta` / `ventana_vence_en` son los mismos que ya usa Inicio (el panel los pasa tal
    cual a `calcularVentana`)."""
    estado = estado or await obtener_estado_ventana(telefono, negocio_id)
    negocio_id = negocio_id or estado.get("negocio_id")
    plantilla = await plantilla_retomar.obtener_plantilla(negocio_id)
    return {
        "ventana_abierta": estado["ventana_24h_abierta"],
        "ventana_vence_en": iso_utc(estado["vence_en"]) if estado["vence_en"] else None,
        "ultimo_mensaje_cliente_en": iso_utc(estado["ultimo_mensaje_cliente_en"]) if estado["ultimo_mensaje_cliente_en"] else None,
        "puede_texto_libre": estado["puede_texto_libre"],
        "puede_plantilla": estado["puede_plantilla"],
        "plantilla_disponible": plantilla["disponible"],
        "fep_abierta": estado["fep_abierta"],
        "fep_vence_en": iso_utc(estado["fep_vence_en"]) if estado["fep_vence_en"] else None,
        "fep_origen": estado["fep_origen"],
    }


async def _error_ventana_cerrada(telefono: str, negocio_id: str | None = None, estado: dict | None = None) -> VentanaCerradaError:
    """El 409 estructurado. Siempre dice `ventana_abierta: False` (es lo que acaba de ocurrir, aunque
    Meta la haya dado por cerrada con un 131047 mientras nuestro cálculo aún la veía abierta)."""
    try:
        dto = await _dto_ventana_whatsapp(telefono, negocio_id, estado)
    except Exception:
        logger.exception(f"No se pudo armar el estado de la ventana de {telefono} para el 409")
        dto = {"puede_plantilla": True, "plantilla_disponible": False, "fep_abierta": False, "fep_vence_en": None}
    dto.update({"ventana_abierta": False, "puede_texto_libre": False})
    return VentanaCerradaError(dto)


async def _verificar_ventana_atencion(telefono: str):
    """Antes de intentar cualquier envío libre a un lead: si ya se cerró la
    ventana de 24h, se rechaza acá con un error diferenciado (409) en vez de
    dejar que Meta lo rechace y mostrar el mismo 502 genérico que cualquier
    otra falla (token vencido, canal caído, etc.) — el asesor necesita saber
    que ESTO puntualmente es la ventana cerrada, no un problema técnico. El 409
    es estructurado (`VentanaCerradaError`): dice si hay plantilla para ofrecer."""
    estado = await obtener_estado_ventana(telefono, con_fep=False)   # camino de envío: solo importan las 24 h
    if not estado["puede_texto_libre"]:
        # Recién ahora, ya fallando, se consulta lo del anuncio y la plantilla.
        completo = await obtener_estado_ventana(telefono)
        raise await _error_ventana_cerrada(telefono, estado=completo)


@router.post("/lead/{telefono}/responder")
async def responder_cliente(
    telefono: str,
    mensaje: str = Form(...),
    # Id interno (Mensaje.id, NO el wamid de Meta) del mensaje que se está
    # citando — Reply/Quote. Se resuelve acá contra la base para sacar su
    # mensaje_id_meta real y armar el `context` del envío; si ese mensaje no
    # tiene wamid (histórico previo a este campo, o un envío que falló) la
    # cita se rechaza en vez de mandarle a Meta un context inválido.
    mensaje_id_citado: int | None = Form(None),
    usuario: dict = Depends(_usuario_actual),
    _csrf: None = Depends(verificar_csrf),
):
    """El asesor humano responde al cliente por el mismo número de WhatsApp
    (Gabi ya está pausada para este lead porque tiene asesor_asignado)."""
    lead = await obtener_lead(telefono, negocio_id=usuario["negocio_id"])
    if lead is None:
        raise HTTPException(status_code=404, detail="Lead no encontrado")
    # Antes había acá un guard adicional (`if not lead.get("asesor_asignado"):
    # raise HTTPException(400, ...)`) que exigía un lead ya asignado para
    # poder responderle. Se removió a propósito: contradecía la matriz de
    # permisos aprobada (MPA §9 — admin ve/actúa sobre todas, supervisor sobre
    # su equipo, asesor sobre las propias, sin condicionar a que el lead esté
    # asignado). El control de acceso real ya lo hace `_verificar_acceso_lead`
    # (arriba), que delega en `tiene_acceso_a_lead`; ese chequeo de asignación
    # era redundante y además bloqueaba casos legítimos (ej. supervisor
    # respondiendo un lead de su equipo todavía sin asesor).
    _verificar_acceso_lead(usuario, lead)

    mensaje = mensaje.strip()
    if not mensaje:
        raise HTTPException(status_code=400, detail="El mensaje no puede estar vacío")

    await _verificar_ventana_atencion(telefono)

    wamid_citado = None
    if mensaje_id_citado is not None:
        mensaje_original = await servicio_conversacion.obtener_mensaje_por_id(mensaje_id_citado)
        if mensaje_original is None or mensaje_original["telefono"] != telefono:
            raise HTTPException(status_code=404, detail="El mensaje que quieres citar no existe en esta conversación")
        if not mensaje_original.get("mensaje_id_meta"):
            raise HTTPException(
                status_code=422,
                detail="Este mensaje no se puede citar — no tiene un identificador de WhatsApp asociado (por ejemplo, es anterior a esta función, o su envío falló)",
            )
        wamid_citado = mensaje_original["mensaje_id_meta"]

    proveedor = obtener_proveedor()
    canal = await proveedor.resolver_canal(lead.get("numero_whatsapp_id"))
    resultado_envio = await envios.enviar_texto(proveedor, telefono, mensaje, origen="asesor_texto", canal=canal, mensaje_id_citado=wamid_citado, asesor=usuario["username"])
    enviado, wamid = resultado_envio

    # Meta dijo "fuera de la ventana de 24 h" (131047) aunque nuestro cálculo la veía abierta: es el
    # mismo caso que el 409 de arriba. El mensaje no llegó ni hay nada que reintentar, así que no se
    # guarda; el panel recibe el 409 estructurado y ofrece la plantilla.
    if getattr(resultado_envio, "fuera_de_ventana", False):
        raise await _error_ventana_cerrada(telefono, negocio_id=usuario["negocio_id"])

    # A diferencia del comportamiento anterior (no guardar nada si el envío
    # fallaba), el mensaje se persiste igual con estado_envio="fallido" —
    # para que el frontend lo muestre con opción de reintento en vez de
    # perderlo en silencio. La respuesta también deja de ser un 502 sin más
    # información: trae el id del mensaje ya guardado para que el frontend
    # pueda ofrecer "reintentar" sobre ÉL, no solo mostrar un error genérico.
    mensaje_guardado = await servicio_conversacion.guardar_mensaje(
        telefono, "asesor", mensaje, negocio_id=usuario["negocio_id"],
        mensaje_id_meta=wamid, estado_envio=_estado_envio_guardado(resultado_envio),
        # Persiste la relación con el mensaje citado (Reply/Quote) — antes
        # solo se resolvía el wamid para el envío a Meta y se perdía acá, así
        # que la cita salía bien por WhatsApp pero desaparecía del panel en
        # cuanto se recargaba la conversación (mensajes.json no tenía de
        # dónde sacarla). mensaje_id_citado ya viene validado arriba (existe,
        # es de esta conversación, tiene wamid) antes de llegar a este punto.
        respondido_a_id=mensaje_id_citado,
    )
    await gestor_conexiones.emitir_mensaje_nuevo(mensaje_guardado["conversation_id"])

    if resultado_envio.incierto:
        return _respuesta_envio_incierto(mensaje_guardado["id"])
    if not enviado:
        return _respuesta_envio_fallido(
            "No se pudo enviar el mensaje por WhatsApp — el mensaje quedó guardado, puedes reintentar.",
            mensaje_guardado["id"],
        )
    return JSONResponse({"status": "ok", "mensaje_id": mensaje_guardado["id"]})


@router.get("/conversation/{conversation_id}/ventana-whatsapp")
async def conversation_ventana_whatsapp(conversation_id: str, usuario: dict = Depends(_usuario_actual)):
    """Estado de la ventana de WhatsApp de ESTA conversación (P3, 2026-10-06): si se le puede escribir
    libre o solo con plantilla, cuándo vence y si un envío ahora sería gratis por anuncio. Ligero y de
    solo lectura — el panel lo pide al abrir el chat y cuando llega un mensaje del cliente. Mismo control
    de acceso de dos capas que el resto de `/conversation/{id}/...`."""
    conversation = await obtener_conversation_detalle(conversation_id, usuario["negocio_id"])
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversación no encontrada")
    _verificar_acceso_conversation(usuario, conversation["asesor_asignado"])
    return JSONResponse(await _dto_ventana_whatsapp(conversation["telefono"], usuario["negocio_id"]))


def _variables_plantilla_del_lead(lead: dict, usuario: dict) -> list[str]:
    return plantilla_retomar.variables_de_plantilla(
        lead.get("nombre"), usuario.get("nombre") or usuario.get("username"), lead.get("interes"),
    )


@router.get("/lead/{telefono}/plantilla-retomar")
async def plantilla_retomar_del_lead(telefono: str, usuario: dict = Depends(_usuario_actual)):
    """La plantilla de "retomar consulta" configurada, con su vista previa YA rellena para este lead
    (cliente, asesor que la manda e interés) y el estado de su ventana — lo que el asesor ve antes de
    confirmar el envío. Mismo control de acceso que `/responder`. `disponible: false` si todavía no hay
    una plantilla aprobada configurada (clave `plantilla_retomar_nombre`)."""
    lead = await obtener_lead(telefono, negocio_id=usuario["negocio_id"])
    if lead is None:
        raise HTTPException(status_code=404, detail="Lead no encontrado")
    _verificar_acceso_lead(usuario, lead)
    plantilla = await plantilla_retomar.obtener_plantilla(usuario["negocio_id"])
    variables = _variables_plantilla_del_lead(lead, usuario)
    ventana = await _dto_ventana_whatsapp(telefono, usuario["negocio_id"])
    return JSONResponse({
        **plantilla,
        "variables_valores": variables[:plantilla_retomar.cantidad_de_variables(plantilla["cuerpo"])],
        "texto": plantilla_retomar.renderizar(plantilla["cuerpo"], variables),
        "categoria_supuesta": await obtener_configuracion(
            "envios_categoria_asesor_plantilla", envios.ORIGENES["asesor_plantilla"]["categoria_plantilla"], negocio_id=usuario["negocio_id"],
        ),
        "ventana": ventana,
    })


@router.post("/lead/{telefono}/responder-plantilla")
async def responder_cliente_con_plantilla(
    telefono: str,
    usuario: dict = Depends(_usuario_actual),
    _csrf: None = Depends(verificar_csrf),
):
    """El asesor manda la plantilla aprobada de "retomar consulta" cuando la ventana de 24 h cerró
    (P3, 2026-10-06). Mismos permisos que `/responder`. Sale por la capa central de envíos con el
    origen `asesor_plantilla` (no esencial: respeta el interruptor y el tope mensual de costo; dentro
    de la ventana gratuita de un anuncio pasa sin costo) y atribuida al asesor. Con la ventana abierta
    se rechaza: ahí corresponde escribirle libre. El mensaje se guarda en el chat con el texto que ve
    el cliente y su `estado_envio` (enviado / incierto / fallido), igual que `/responder`. Cuando el
    cliente toca un botón o responde, entra como mensaje suyo y abre una ventana nueva de 24 h."""
    lead = await obtener_lead(telefono, negocio_id=usuario["negocio_id"])
    if lead is None:
        raise HTTPException(status_code=404, detail="Lead no encontrado")
    _verificar_acceso_lead(usuario, lead)

    plantilla = await plantilla_retomar.obtener_plantilla(usuario["negocio_id"])
    if not plantilla["disponible"]:
        raise ErrorConCodigo(
            409, "Todavía no hay una plantilla aprobada configurada. Pide a un administrador que la configure.",
            "plantilla_no_configurada",
        )

    estado = await obtener_estado_ventana(telefono, usuario["negocio_id"])
    if estado["puede_texto_libre"]:
        raise ErrorConCodigo(409, "La ventana de 24 horas sigue abierta: puedes escribirle directamente, sin plantilla.", "ventana_abierta")

    variables = _variables_plantilla_del_lead(lead, usuario)
    parametros = plantilla_retomar.parametros_para_envio(plantilla["cuerpo"], variables)
    texto = plantilla_retomar.renderizar(plantilla["cuerpo"], variables)

    proveedor = obtener_proveedor()
    canal = await proveedor.resolver_canal(lead.get("numero_whatsapp_id"))
    resultado_envio = await envios.enviar_plantilla(
        proveedor, telefono, plantilla["nombre"], parametros, plantilla["idioma"],
        origen="asesor_plantilla", canal=canal, asesor=usuario["username"],
    )
    enviado, wamid = resultado_envio

    # La política de costo la frenó (interruptor en "nunca" o tope mensual): no salió nada, no hay
    # mensaje que guardar ni reintentar.
    if resultado_envio.bloqueado:
        raise ErrorConCodigo(
            409,
            f"La plantilla no se envió: {resultado_envio.motivo}. Un administrador puede ajustarlo en Uso y envíos.",
            "plantilla_bloqueada_por_costo", motivo=resultado_envio.motivo, fep_abierta=estado["fep_abierta"],
        )

    mensaje_guardado = await servicio_conversacion.guardar_mensaje(
        telefono, "asesor", texto, negocio_id=usuario["negocio_id"],
        mensaje_id_meta=wamid, estado_envio=_estado_envio_guardado(resultado_envio),
    )
    await gestor_conexiones.emitir_mensaje_nuevo(mensaje_guardado["conversation_id"])

    if resultado_envio.incierto:
        return _respuesta_envio_incierto(mensaje_guardado["id"])
    if not enviado:
        return _respuesta_envio_fallido(
            "No se pudo enviar la plantilla por WhatsApp. Revisa que su nombre e idioma coincidan con los aprobados en Meta.",
            mensaje_guardado["id"],
        )
    return JSONResponse({"status": "ok", "mensaje_id": mensaje_guardado["id"], "texto": texto})


def _convertir_a_ogg_opus(contenido_webm: bytes) -> bytes:
    """Convierte audio WebM/Opus (lo único que MediaRecorder graba de forma
    confiable en el navegador) a OGG/Opus mono — el único formato de audio
    que la API de WhatsApp acepta para notas de voz. Usa archivos temporales
    en vez de pipes: el demuxer de WebM/Matroska necesita poder buscar
    dentro del archivo, no lee bien un stream continuo. Los descriptores se
    cierran apenas se crean (en vez de mantenerlos abiertos con un context
    manager) para que ffmpeg, un proceso aparte, pueda abrir esos mismos
    archivos sin toparse con el bloqueo exclusivo que impone Windows."""
    entrada_fd, entrada_ruta = tempfile.mkstemp(suffix=".webm")
    salida_fd, salida_ruta = tempfile.mkstemp(suffix=".ogg")
    os.close(entrada_fd)
    os.close(salida_fd)
    try:
        with open(entrada_ruta, "wb") as f:
            f.write(contenido_webm)
        resultado = subprocess.run(
            ["ffmpeg", "-y", "-i", entrada_ruta, "-c:a", "libopus", "-ac", "1", "-b:a", "32k", salida_ruta],
            capture_output=True, timeout=30,
        )
        if resultado.returncode != 0:
            logger.error(f"Error convirtiendo audio con ffmpeg: {resultado.stderr.decode(errors='replace')}")
            raise HTTPException(status_code=502, detail="No se pudo procesar el audio")
        with open(salida_ruta, "rb") as f:
            return f.read()
    finally:
        for ruta in (entrada_ruta, salida_ruta):
            try:
                os.remove(ruta)
            except OSError:
                pass


def _guardar_archivo_en_disco(nombre_original: str, contenido: bytes) -> str:
    """Escribe el archivo en ARCHIVOS_DIR con un nombre único (evita
    colisiones/sobrescrituras) y retorna la ruta en disco resultante."""
    extension = os.path.splitext(nombre_original)[1].lower()
    nombre_disco = f"{uuid.uuid4().hex}{extension}"
    os.makedirs(ARCHIVOS_DIR, exist_ok=True)
    ruta_disco = os.path.join(ARCHIVOS_DIR, nombre_disco)
    with open(ruta_disco, "wb") as f:
        f.write(contenido)
    return ruta_disco


async def _subir_y_enviar_media(telefono: str, nombre_archivo: str, content_type: str, contenido: bytes, caption: str, canal: dict | None = None, asesor: str | None = None) -> "envios.ResultadoEnvio":
    """Sube el archivo a WhatsApp y lo envía como imagen o documento según
    su tipo — común entre el envío de una proforma nueva y el reenvío de un
    catálogo ya guardado. Retorna (enviado, wamid) — a diferencia de antes,
    YA NO lanza HTTPException si la subida o el envío fallan: el llamador
    necesita poder guardar igual el mensaje con estado_envio="fallido" (ver
    responder_cliente) en vez de perder el intento por completo. Una subida
    fallida (media_id vacío) se trata como el mismo tipo de falla que un
    envío fallido — desde la óptica del asesor, el archivo no le llegó al
    cliente en ninguno de los dos casos."""
    proveedor = obtener_proveedor()
    media_id = await proveedor.subir_media(contenido, nombre_archivo, content_type, canal=canal)
    if not media_id:
        return envios.ResultadoEnvio(False, None)
    es_imagen = content_type.startswith("image/")
    # Devuelve el ResultadoEnvio completo (se desempaqueta igual que la tupla
    # `(enviado, wamid)` de antes) para que el llamador vea `.incierto`.
    return (
        await envios.enviar_imagen(proveedor, telefono, media_id, caption, origen="asesor_archivo", canal=canal, asesor=asesor)
        if es_imagen else
        await envios.enviar_documento(proveedor, telefono, media_id, nombre_archivo, caption, origen="asesor_archivo", canal=canal, asesor=asesor)
    )


def _estado_envio_guardado(resultado) -> str | None:
    """Valor de `Mensaje.estado_envio` para un envío del asesor: None si salió,
    "incierto" si el POST pudo llegar a Meta y no se supo el resultado (NO es
    "fallido": el cliente pudo recibirlo y reenviarlo a ciegas lo duplicaría),
    "fallido" en cualquier otro caso."""
    if resultado.enviado:
        return None
    return "incierto" if getattr(resultado, "incierto", False) else "fallido"


def _respuesta_envio_incierto(mensaje_id: int) -> JSONResponse:
    """Respuesta de los 4 endpoints de envío cuando el resultado es incierto.
    Es un 200 a propósito: un error HTTP hace que el panel marque la burbuja
    como fallida y ofrezca "Reintentar", justo lo que duplicaría el mensaje."""
    return JSONResponse({
        "status": "incierto", "estado_envio": "incierto", "mensaje_id": mensaje_id,
        "detail": "WhatsApp no confirmó el envío — el mensaje pudo haber llegado. No lo reenvíes sin revisar antes con el cliente.",
    })


def _respuesta_envio_fallido(detalle: str, mensaje_id: int) -> JSONResponse:
    """Misma forma de respuesta para los 4 endpoints de envío cuando Meta no
    confirma la entrega — el mensaje YA quedó guardado (estado_envio=
    "fallido") antes de llegar acá, así que el frontend recibe el id real
    para ofrecer reintentar sobre ÉL, no solo un error genérico."""
    return JSONResponse(
        {"status": "error", "estado_envio": "fallido", "mensaje_id": mensaje_id, "detail": detalle},
        status_code=502,
    )


@router.post("/lead/{telefono}/enviar-archivo")
async def enviar_archivo_chat(
    telefono: str,
    archivo: UploadFile = File(...),
    caption: str = Form(""),
    usuario: dict = Depends(_usuario_actual),
    _csrf: None = Depends(verificar_csrf),
):
    """El asesor sube una proforma/imagen puntual y se la manda al cliente
    de una — se guarda en ARCHIVOS_DIR (persistente) para poder reabrirla
    después desde el historial del chat."""
    lead = await obtener_lead(telefono, negocio_id=usuario["negocio_id"])
    if lead is None:
        raise HTTPException(status_code=404, detail="Lead no encontrado")
    # Mismo criterio que responder_cliente: se removió a propósito el guard
    # `if not lead.get("asesor_asignado"): raise HTTPException(400, ...)` que
    # exigía asignación previa — contradecía la matriz de permisos aprobada
    # (MPA §9). El control de acceso real lo hace `_verificar_acceso_lead`.
    _verificar_acceso_lead(usuario, lead)
    await _verificar_ventana_atencion(telefono)

    extension = os.path.splitext(archivo.filename or "")[1].lower()
    if extension not in EXTENSIONES_ARCHIVO_PERMITIDAS:
        raise HTTPException(status_code=400, detail="Solo se aceptan PDF, Word, Excel, PowerPoint, texto (.txt), JPG o PNG")

    # Tope por tipo (ver constantes arriba) — el frontend ya valida esto
    # ANTES de subir (`composer-conversacion.tsx`, `validarTamano`), esta es
    # la defensa de fondo si alguien llama la API directo.
    tamano_maximo_mb = _tamano_maximo_para_extension(extension)
    contenido = await archivo.read()
    if len(contenido) > tamano_maximo_mb * 1024 * 1024:
        raise HTTPException(status_code=400, detail=f"El archivo supera los {tamano_maximo_mb}MB permitidos")

    content_type = archivo.content_type or "application/octet-stream"
    canal = await obtener_proveedor().resolver_canal(lead.get("numero_whatsapp_id"))
    resultado_envio = await _subir_y_enviar_media(telefono, archivo.filename, content_type, contenido, caption.strip(), canal=canal, asesor=usuario["username"])
    enviado, wamid = resultado_envio

    # El archivo se guarda en disco y el mensaje se persiste SIEMPRE, haya
    # llegado o no a Meta — igual que responder_cliente: si el envío falla,
    # el asesor no tiene que volver a elegir el archivo desde su equipo para
    # reintentar, el adjunto ya quedó guardado.
    ruta_disco = _guardar_archivo_en_disco(archivo.filename, contenido)
    archivo_guardado = await servicio_conversacion.crear_archivo_adjunto(
        nombre_original=archivo.filename, ruta_disco=ruta_disco, content_type=content_type,
        tamano_bytes=len(contenido), subido_por=usuario["username"], reutilizable=False,
    )
    mensaje_guardado = await servicio_conversacion.guardar_mensaje(
        telefono, "asesor", caption.strip() or archivo.filename, negocio_id=usuario["negocio_id"],
        archivo_id=archivo_guardado["id"], mensaje_id_meta=wamid, estado_envio=_estado_envio_guardado(resultado_envio),
    )
    await gestor_conexiones.emitir_mensaje_nuevo(mensaje_guardado["conversation_id"])

    if resultado_envio.incierto:
        return _respuesta_envio_incierto(mensaje_guardado["id"])
    if not enviado:
        return _respuesta_envio_fallido(
            "No se pudo enviar el archivo por WhatsApp — el mensaje quedó guardado, puedes reintentar.",
            mensaje_guardado["id"],
        )
    return JSONResponse({"status": "ok", "mensaje_id": mensaje_guardado["id"]})


@router.post("/lead/{telefono}/enviar-audio")
async def enviar_audio_chat(
    telefono: str,
    audio: UploadFile = File(...),
    usuario: dict = Depends(_usuario_actual),
    _csrf: None = Depends(verificar_csrf),
):
    """El asesor graba una nota de voz en el navegador (WebM/Opus) — se
    convierte a OGG/Opus (único formato de audio que acepta WhatsApp) antes
    de subirla y enviarla, y se guarda ya convertida para poder reabrirla."""
    lead = await obtener_lead(telefono, negocio_id=usuario["negocio_id"])
    if lead is None:
        raise HTTPException(status_code=404, detail="Lead no encontrado")
    # Mismo criterio que responder_cliente: se removió a propósito el guard
    # `if not lead.get("asesor_asignado"): raise HTTPException(400, ...)` que
    # exigía asignación previa — contradecía la matriz de permisos aprobada
    # (MPA §9). El control de acceso real lo hace `_verificar_acceso_lead`.
    _verificar_acceso_lead(usuario, lead)
    await _verificar_ventana_atencion(telefono)

    contenido_webm = await audio.read()
    if len(contenido_webm) > TAMANO_MAXIMO_ARCHIVO_MB * 1024 * 1024:
        raise HTTPException(status_code=400, detail=f"El audio supera los {TAMANO_MAXIMO_ARCHIVO_MB}MB permitidos")
    if not contenido_webm:
        raise HTTPException(status_code=400, detail="No se recibió audio")

    # La conversión WebM→OGG es un paso de PROCESAMIENTO local, previo a
    # cualquier intento de contacto con Meta — si ffmpeg falla, no hay un
    # audio válido que guardar ni que reintentar con los mismos bytes
    # (reintentar daría el mismo error), así que sigue siendo un error duro
    # (502) en vez de un estado_envio="fallido" persistido. Distinto del
    # resto de este endpoint, donde la falla SÍ es "se generó el archivo
    # pero Meta no lo confirmó" — ahí sí aplica el patrón de reintento.
    contenido_ogg = _convertir_a_ogg_opus(contenido_webm)

    proveedor = obtener_proveedor()
    canal = await proveedor.resolver_canal(lead.get("numero_whatsapp_id"))
    media_id = await proveedor.subir_media(contenido_ogg, "nota_de_voz.ogg", "audio/ogg", canal=canal)
    resultado_envio = envios.ResultadoEnvio(False, None)
    if media_id:
        resultado_envio = await envios.enviar_audio(proveedor, telefono, media_id, origen="asesor_audio", canal=canal, asesor=usuario["username"])
    enviado, wamid = resultado_envio

    # Mismo criterio que enviar-archivo: la nota de voz ya convertida se
    # guarda y el mensaje se persiste SIEMPRE, para que un envío fallido se
    # pueda reintentar sin tener que volver a grabar/convertir el audio.
    ruta_disco = _guardar_archivo_en_disco("nota_de_voz.ogg", contenido_ogg)
    archivo_guardado = await servicio_conversacion.crear_archivo_adjunto(
        nombre_original="nota_de_voz.ogg", ruta_disco=ruta_disco, content_type="audio/ogg",
        tamano_bytes=len(contenido_ogg), subido_por=usuario["username"], reutilizable=False,
    )
    mensaje_guardado = await servicio_conversacion.guardar_mensaje(
        telefono, "asesor", "Nota de voz", negocio_id=usuario["negocio_id"], archivo_id=archivo_guardado["id"],
        mensaje_id_meta=wamid, estado_envio=_estado_envio_guardado(resultado_envio),
    )
    await gestor_conexiones.emitir_mensaje_nuevo(mensaje_guardado["conversation_id"])

    if resultado_envio.incierto:
        return _respuesta_envio_incierto(mensaje_guardado["id"])
    if not enviado:
        return _respuesta_envio_fallido(
            "No se pudo enviar el audio por WhatsApp — el mensaje quedó guardado, puedes reintentar.",
            mensaje_guardado["id"],
        )
    return JSONResponse({"status": "ok", "mensaje_id": mensaje_guardado["id"]})


@router.post("/lead/{telefono}/enviar-catalogo/{archivo_id}")
async def enviar_catalogo_chat(telefono: str, archivo_id: int, usuario: dict = Depends(_usuario_actual), _csrf: None = Depends(verificar_csrf)):
    """Reenvía un archivo de la librería de catálogos reutilizables — se
    vuelve a subir a WhatsApp desde nuestra copia en disco (el media_id de
    Meta es de un solo uso/temporal, no se reutiliza entre conversaciones)."""
    lead = await obtener_lead(telefono, negocio_id=usuario["negocio_id"])
    if lead is None:
        raise HTTPException(status_code=404, detail="Lead no encontrado")
    # Mismo criterio que responder_cliente: se removió a propósito el guard
    # `if not lead.get("asesor_asignado"): raise HTTPException(400, ...)` que
    # exigía asignación previa — contradecía la matriz de permisos aprobada
    # (MPA §9). El control de acceso real lo hace `_verificar_acceso_lead`.
    _verificar_acceso_lead(usuario, lead)
    await _verificar_ventana_atencion(telefono)

    archivo = await servicio_conversacion.obtener_archivo_adjunto(archivo_id)
    if archivo is None or not archivo["reutilizable"]:
        raise HTTPException(status_code=404, detail="Catálogo no encontrado")
    _verificar_acceso_archivo_reutilizable(archivo, usuario)
    if not os.path.exists(archivo["ruta_disco"]):
        raise HTTPException(status_code=404, detail="Este catálogo ya no está disponible en el servidor — vuelve a subirlo desde Catálogo.")

    with open(archivo["ruta_disco"], "rb") as f:
        contenido = f.read()
    canal = await obtener_proveedor().resolver_canal(lead.get("numero_whatsapp_id"))
    resultado_envio = await _subir_y_enviar_media(telefono, archivo["nombre_original"], archivo["content_type"], contenido, "", canal=canal, asesor=usuario["username"])
    enviado, wamid = resultado_envio

    # No hay nada nuevo que guardar en disco acá (el catálogo ya vive en la
    # librería reutilizable) — pero el mensaje se persiste igual con
    # estado_envio="fallido" si Meta no lo confirmó, mismo patrón que los
    # otros 3 endpoints de envío.
    mensaje_guardado = await servicio_conversacion.guardar_mensaje(
        telefono, "asesor", archivo["nombre_original"], negocio_id=usuario["negocio_id"], archivo_id=archivo["id"],
        mensaje_id_meta=wamid, estado_envio=_estado_envio_guardado(resultado_envio),
    )
    await gestor_conexiones.emitir_mensaje_nuevo(mensaje_guardado["conversation_id"])

    if resultado_envio.incierto:
        return _respuesta_envio_incierto(mensaje_guardado["id"])
    if not enviado:
        return _respuesta_envio_fallido(
            "No se pudo enviar el catálogo por WhatsApp — el mensaje quedó guardado, puedes reintentar.",
            mensaje_guardado["id"],
        )
    return JSONResponse({"status": "ok", "mensaje_id": mensaje_guardado["id"]})


async def _verificar_acceso_archivo(archivo_id: int, usuario: dict) -> None:
    """Candado de acceso a un archivo NO reutilizable — mismo criterio que
    ver la conversación a la que se le mandó.

    Corrección residual de Gate 5.4 (hallazgo Alta severidad, checkpoint de
    investigación de Gate 5.5): cuando `telefono_lead` existe pero
    `obtener_lead(..., negocio_id=...)` devuelve `None` — el lead pertenece a
    OTRO Negocio — el chequeo `if lead:` se saltaba en silencio y el archivo
    se servía igual. Ahora un `telefono_lead` sin lead resoluble PARA ESTE
    Negocio es un 403 explícito, no un fallthrough."""
    telefono_lead = await servicio_conversacion.obtener_telefono_de_archivo(archivo_id)
    if not telefono_lead:
        return
    lead = await obtener_lead(telefono_lead, negocio_id=usuario["negocio_id"])
    if lead is None:
        raise HTTPException(status_code=403, detail="No tienes acceso a este archivo")
    _verificar_acceso_lead(usuario, lead)


def _verificar_acceso_archivo_reutilizable(archivo: dict, usuario: dict) -> None:
    """Candado de acceso a un catálogo reutilizable — negocio_id de la
    sesión autenticada contra negocio_id del archivo, nunca `subido_por`
    ni ningún valor recibido del cliente.

    Cierra el hallazgo de la Auditoría Maestra: antes de este Gate, un
    archivo reutilizable no tenía NINGÚN chequeo de tenant — cualquier
    usuario autenticado de cualquier negocio podía descargarlo. Un
    `negocio_id` ausente en el archivo (no debería ocurrir tras la
    migración, salvo un dato huérfano no resuelto) también se rechaza —
    nunca se trata `None == None` como acceso válido."""
    if not usuario["negocio_id"] or archivo["negocio_id"] != usuario["negocio_id"]:
        raise HTTPException(status_code=403, detail="No tienes acceso a este catálogo")


@router.get("/archivo/{archivo_id}")
async def descargar_archivo(archivo_id: int, usuario: dict = Depends(_usuario_actual)):
    """Sirve un archivo adjunto ya enviado — si es una proforma puntual (no
    reutilizable), verifica que el usuario tenga acceso al lead al que se le
    mandó, igual que para ver la conversación misma; si es un catálogo
    reutilizable, verifica que pertenezca a su propio negocio."""
    archivo = await servicio_conversacion.obtener_archivo_adjunto(archivo_id)
    if archivo is None:
        raise HTTPException(status_code=404, detail="Archivo no encontrado")
    if not archivo["reutilizable"]:
        await _verificar_acceso_archivo(archivo_id, usuario)
    else:
        _verificar_acceso_archivo_reutilizable(archivo, usuario)
    if not os.path.exists(archivo["ruta_disco"]):
        raise HTTPException(status_code=404, detail="El archivo ya no está disponible")
    return FileResponse(archivo["ruta_disco"], filename=archivo["nombre_original"], media_type=archivo["content_type"])


@router.get("/catalogos", response_class=HTMLResponse)
async def gestionar_catalogos(request: Request, usuario: dict = Depends(_usuario_actual), subido: str = ""):
    """Librería de catálogos reutilizables — subir una vez, cualquier asesor
    los puede mandar en cualquier conversación sin volver a subirlos.
    Visible a los 3 roles (Product Patterns Cap. 7.A §4: "el patrón existe
    para los tres roles"); solo Administrador puede subir o eliminar —
    Supervisor y Asesor tienen alcance de solo lectura, para citar en la
    conversación."""
    sidebar = await _renderizar_sidebar(usuario, telefono_activo=None)
    archivos = await servicio_conversacion.listar_archivos_reutilizables(usuario["negocio_id"])
    es_admin = usuario["rol"] == "admin"

    mensaje_html = ""
    if subido:
        mensaje_html = '<div class="alert alert-success py-2 px-3 mb-3"><i class="bi bi-check-circle-fill"></i> Catálogo subido.</div>'

    columna_eliminar = '<th class="pe-3"></th>' if es_admin else ''
    filas = "".join(
        f"""<tr>
            <td class="ps-3">
                <div class="fw-semibold">{html.escape(a['etiqueta'] or a['nombre_original'])}</div>
                <div class="text-muted" style="font-size:.75rem">{html.escape(a['nombre_original'])} &middot; {round(a['tamano_bytes'] / 1024)} KB</div>
            </td>
            <td class="text-muted">{html.escape(a['subido_por'])}</td>
            <td><a href="/dashboard/archivo/{a['id']}" target="_blank" class="btn btn-sm btn-outline-secondary"><i class="bi bi-download"></i> Ver</a></td>
            {f'''<td class="pe-3">
                <form method="post" action="/dashboard/catalogos/{a['id']}/eliminar" onsubmit="return confirm('¿Quitar este catálogo de la librería? Ya no se podrá elegir para enviar en nuevas conversaciones.')">
                    {_csrf_campo(request)}
                    <button type="submit" class="btn btn-sm btn-outline-danger"><i class="bi bi-trash"></i></button>
                </form>
            </td>''' if es_admin else ''}
        </tr>"""
        for a in archivos
    )

    subir_html = f"""
    {_titulo_seccion('bi-plus-circle-fill', 'Subir catálogo nuevo')}
    <div class="card leads-card shadow-sm">
        <div class="barra-acento"></div>
        <div class="card-body">
            <form method="post" action="/dashboard/catalogos/nuevo" enctype="multipart/form-data" class="row g-2">
                {_csrf_campo(request)}
                <div class="col-md-4">
                    <label class="form-label small text-muted mb-0">Nombre para identificarlo</label>
                    <input type="text" name="etiqueta" class="form-control form-control-sm" required placeholder="Ej: Catálogo general 2026">
                </div>
                <div class="col-md-6">
                    <label class="form-label small text-muted mb-0">Archivo (PDF, Word, Excel, PowerPoint, texto, JPG o PNG, máx. {TAMANO_MAXIMO_ARCHIVO_MB}MB)</label>
                    <input type="file" name="archivo" class="form-control form-control-sm" accept=".pdf,.doc,.docx,.xls,.xlsx,.ppt,.pptx,.txt,.jpg,.jpeg,.png" required>
                </div>
                <div class="col-md-2 d-flex align-items-end">
                    <button type="submit" class="btn btn-sm btn-primary w-100">Subir</button>
                </div>
            </form>
        </div>
    </div>
    """ if es_admin else ""

    panel = f"""
    {_titulo_seccion('bi-folder-fill', 'Librería de catálogos')}
    <p class="text-muted small mb-3">
        Catálogos, listas de precios en PDF, Word, Excel, PowerPoint o imágenes de referencia
        disponibles para elegir y enviar desde el chat en cualquier conversación.
    </p>
    {mensaje_html}
    <div class="card leads-card shadow-sm mb-4">
        <div class="barra-acento"></div>
        <div class="table-responsive">
            <table class="table table-hover align-middle mb-0 tabla-ejecutiva">
                <thead><tr><th class="ps-3">Catálogo</th><th>Subido por</th><th></th>{columna_eliminar}</tr></thead>
                <tbody>{filas or f'<tr><td colspan="{4 if es_admin else 3}" class="text-center text-muted py-4">Aún no hay catálogos.</td></tr>'}</tbody>
            </table>
        </div>
    </div>

    {subir_html}
    """
    cuerpo = f"""<div class="shell d-flex">{sidebar}<div class="main-pane flex-grow-1 p-4">{panel}</div></div>"""
    return _pagina("Librería de catálogos", usuario, cuerpo, request=request)


@router.post("/catalogos/nuevo")
async def subir_catalogo(
    etiqueta: str = Form(...),
    archivo: UploadFile = File(...),
    usuario: dict = Depends(servicio_identidad.requiere_rol("admin")),
    _csrf: None = Depends(verificar_csrf),
):
    extension = os.path.splitext(archivo.filename or "")[1].lower()
    if extension not in EXTENSIONES_ARCHIVO_PERMITIDAS:
        raise HTTPException(status_code=400, detail="Solo se aceptan PDF, Word, Excel, PowerPoint, texto (.txt), JPG o PNG")

    contenido = await archivo.read()
    if len(contenido) > TAMANO_MAXIMO_ARCHIVO_MB * 1024 * 1024:
        raise HTTPException(status_code=400, detail=f"El archivo supera los {TAMANO_MAXIMO_ARCHIVO_MB}MB permitidos")

    ruta_disco = _guardar_archivo_en_disco(archivo.filename, contenido)
    await servicio_conversacion.crear_archivo_adjunto(
        nombre_original=archivo.filename, ruta_disco=ruta_disco,
        content_type=archivo.content_type or "application/octet-stream",
        tamano_bytes=len(contenido), subido_por=usuario["username"],
        reutilizable=True, etiqueta=etiqueta.strip(), negocio_id=usuario["negocio_id"],
    )
    return RedirectResponse(url="/dashboard/catalogos?subido=1", status_code=303)


@router.post("/catalogos/{archivo_id}/eliminar")
async def quitar_catalogo(archivo_id: int, usuario: dict = Depends(servicio_identidad.requiere_rol("admin")), _csrf: None = Depends(verificar_csrf)):
    eliminado = await servicio_conversacion.eliminar_archivo_reutilizable(archivo_id, usuario["negocio_id"])
    if not eliminado:
        raise HTTPException(status_code=404, detail="Catálogo no encontrado")
    return RedirectResponse(url="/dashboard/catalogos", status_code=303)


# ── Biblioteca de archivos (API JSON del panel nuevo, Configuración v2) ─────
#
# Misma librería que `/catalogos` (archivos_adjuntos con reutilizable=True), pero con respuestas JSON para el BFF de
# Next.js. Los permisos son los de siempre: los tres roles ven la lista; solo el administrador sube y quita. Nunca se
# expone `ruta_disco`.

TAMANO_MAXIMO_ETIQUETA = 150  # ArchivoAdjunto.etiqueta es String(150)
TAMANO_MAXIMO_NOMBRE_ARCHIVO = 255  # ArchivoAdjunto.nombre_original es String(255)


def _archivo_biblioteca_a_json(archivo: dict) -> dict:
    return {
        "id": archivo["id"],
        "etiqueta": archivo["etiqueta"] or archivo["nombre_original"],
        "nombre_original": archivo["nombre_original"],
        "content_type": archivo["content_type"],
        "tamano_bytes": archivo["tamano_bytes"],
        "subido_por": archivo["subido_por"],
        "creado": iso_utc(archivo["creado"]),
    }


@router.get("/biblioteca.json")
async def listar_biblioteca(usuario: dict = Depends(_usuario_actual)):
    archivos = await servicio_conversacion.listar_archivos_reutilizables(usuario["negocio_id"])
    return JSONResponse({
        "archivos": [_archivo_biblioteca_a_json(a) for a in archivos],
        "puede_gestionar": usuario["rol"] == "admin",
        "extensiones": sorted(EXTENSIONES_ARCHIVO_PERMITIDAS),
        "tamano_maximo_mb": TAMANO_MAXIMO_ARCHIVO_MB,
    })


@router.post("/biblioteca/nuevo")
async def subir_a_biblioteca(
    etiqueta: str = Form(...),
    archivo: UploadFile = File(...),
    usuario: dict = Depends(servicio_identidad.requiere_rol("admin")),
    _csrf: None = Depends(verificar_csrf),
):
    etiqueta = etiqueta.strip()
    if not etiqueta:
        raise HTTPException(status_code=400, detail="Ponle un nombre al archivo para identificarlo")
    if len(etiqueta) > TAMANO_MAXIMO_ETIQUETA:
        raise HTTPException(status_code=400, detail=f"El nombre no puede superar los {TAMANO_MAXIMO_ETIQUETA} caracteres")
    nombre = os.path.basename((archivo.filename or "").replace("\\", "/"))
    if not nombre:
        raise HTTPException(status_code=400, detail="Elige un archivo")
    if len(nombre) > TAMANO_MAXIMO_NOMBRE_ARCHIVO:
        raise HTTPException(status_code=400, detail="El nombre del archivo es demasiado largo")
    extension = os.path.splitext(nombre)[1].lower()
    if extension not in EXTENSIONES_ARCHIVO_PERMITIDAS:
        raise HTTPException(status_code=400, detail="Solo se aceptan PDF, Word, Excel, PowerPoint, texto (.txt), JPG o PNG")

    limite = TAMANO_MAXIMO_ARCHIVO_MB * 1024 * 1024
    contenido = await archivo.read(limite + 1)  # nunca carga en memoria más de lo permitido
    if not contenido:
        raise HTTPException(status_code=400, detail="El archivo está vacío")
    if len(contenido) > limite:
        raise HTTPException(status_code=400, detail=f"El archivo supera los {TAMANO_MAXIMO_ARCHIVO_MB}MB permitidos")

    ruta_disco = _guardar_archivo_en_disco(nombre, contenido)
    creado = await servicio_conversacion.crear_archivo_adjunto(
        nombre_original=nombre, ruta_disco=ruta_disco,
        # El tipo lo decide la extensión validada, no lo que declare el navegador (con él se elige imagen o documento al enviar por WhatsApp).
        content_type=mimetypes.guess_type(nombre)[0] or "application/octet-stream",
        tamano_bytes=len(contenido), subido_por=usuario["username"],
        reutilizable=True, etiqueta=etiqueta, negocio_id=usuario["negocio_id"],
    )
    return JSONResponse({"ok": True, "archivo": _archivo_biblioteca_a_json(creado)}, status_code=201)


@router.post("/biblioteca/{archivo_id}/eliminar")
async def quitar_de_biblioteca(
    archivo_id: int,
    usuario: dict = Depends(servicio_identidad.requiere_rol("admin")),
    _csrf: None = Depends(verificar_csrf),
):
    """Deja de ofrecer el archivo para envíos nuevos; no borra el archivo del disco (mensajes viejos pueden referenciarlo)."""
    if not await servicio_conversacion.eliminar_archivo_reutilizable(archivo_id, usuario["negocio_id"]):
        raise HTTPException(status_code=404, detail="Archivo no encontrado")
    return JSONResponse({"ok": True})


# response_class=HTMLResponse en las 3 escrituras del CRM: cuando detectan un
# conflicto de edición devuelven _renderizar_detalle_lead(), que es un str de
# HTML (no un Response). Sin esta clase por defecto, FastAPI lo serializaba
# como JSON y el navegador mostraba la página entera escapada entre comillas
# en vez del banner de conflicto (mismo motivo que en /pipeline). El camino
# feliz devuelve un RedirectResponse, que pasa de largo por esta clase.
@router.post("/lead/{telefono}/resultado", response_class=HTMLResponse)
async def actualizar_resultado(
    telefono: str,
    request: Request,
    # Form("") y no Form(...): con FastAPI 0.139 un campo de formulario que
    # llega VACÍO (`resultado=`) se valida como "missing", así que un
    # Form(...) obligatorio respondía 422 a la opción "Selecciona..." del
    # panel (value="") — el usuario no podía quitar un resultado ya puesto.
    # El contrato no se relaja para nadie más: cualquier valor no vacío se
    # comporta igual que antes, y "no me lo mandaron" vs "me lo mandaron
    # vacío" se distingue por la presencia de la clave en request.form().
    resultado: str = Form(""),
    fecha_agendada: str = Form(""),
    version: int = Form(...),
    usuario: dict = Depends(_usuario_actual),
    _csrf: None = Depends(verificar_csrf),
):
    lead = await obtener_lead(telefono, negocio_id=usuario["negocio_id"])
    if lead is None:
        raise HTTPException(status_code=404, detail="Lead no encontrado")
    _verificar_acceso_lead(usuario, lead)
    if resultado and resultado not in RESULTADOS:
        raise HTTPException(status_code=400, detail="Resultado inválido")

    # Presencia de la clave en el formulario, no su valor: "resultado" vacío
    # es una decisión ("quítalo") y "resultado" ausente es "no lo toques" —
    # una distinción que el parámetro tipado no puede hacer, porque FastAPI
    # colapsa las dos cosas en el mismo default (ver el comentario de la
    # firma). El tipo del parámetro no cambia, así que el panel legacy le
    # sigue posteando igual. request.form() ya viene parseado y cacheado por
    # FastAPI, no relee el body.
    formulario = await request.form()
    resultado_enviado = "resultado" in formulario

    campos: dict = {}
    campos_explicitos: list[str] = []
    if resultado_enviado:
        campos["resultado"] = resultado
        campos_explicitos.append("resultado")
        # fecha_agendada solo tiene sentido con resultado == "agendado" (ver
        # el modelo Lead). Si el resultado deja de ser "agendado", la fecha se
        # borra explícitamente en vez de quedar como dato huérfano; si sigue
        # siendo "agendado" y no se mandó fecha nueva, se conserva la que había.
        if resultado != "agendado":
            campos["fecha_agendada"] = None
            campos_explicitos.append("fecha_agendada")
        elif fecha_agendada:
            try:
                campos["fecha_agendada"] = datetime.fromisoformat(fecha_agendada)
            except ValueError:
                raise HTTPException(status_code=400, detail="Fecha de la cita inválida")
        elif lead.get("resultado") != "agendado":
            # Volver a 'agendado' sin fecha nueva: antes conservaba la vieja (huérfana).
            raise HTTPException(status_code=400, detail="Indica la fecha y hora de la cita para marcarla como agendada")

    # Concurrencia optimista sobre Lead.version — SIGUE siendo el gate de
    # ESTE endpoint (el panel HTML legacy nunca conoció opportunity_version,
    # ver Gate 5.3 cutover real §2). Lo que cambia con el cutover es lo que
    # pasa DESPUÉS de que este chequeo pasa: la escritura real delega a
    # Opportunity (fuente de verdad) en vez de aplicarse sobre Lead — todo
    # camino nuevo también avanza Lead.version de forma incondicional, así
    # que este chequeo sigue protegiendo contra cualquier escritura
    # concurrente, venga por el endpoint que venga.
    if not await intentar_avanzar_version(telefono, version):
        if _pide_json_explicitamente(request):
            return await _json_conflicto_lead(telefono, usuario["negocio_id"])
        return await _renderizar_detalle_lead(telefono, request, usuario, hay_conflicto=True)

    descripcion = (
        f"Cambió el resultado a «{ETIQUETAS_RESULTADO.get(resultado, resultado)}»"
        if resultado else "Quitó el resultado"
    )
    evento = {
        "tipo": "resultado_cambiado", "descripcion": descripcion, "autor": usuario["nombre"],
        "payload": {"campo": "resultado", "anterior": lead.get("resultado"), "nuevo": resultado or None},
    }
    ids = await resolver_ids_operables_por_telefono(telefono)
    if ids is not None:
        # Camino REAL — LEGACY / COMPATIBILIDAD: delega hacia Opportunity
        # (cutover real §1/§7). La version vigente de la Opportunity se
        # resuelve server-side (nunca la manda este cliente, que no la
        # conoce); el chequeo de Lead.version de arriba ya serializó este
        # request contra cualquier otra escritura, así que el 409 acá solo
        # puede darse por una ventana de carrera extremadamente angosta.
        #
        # Gate 5.5 — corrección de escritura cross-tenant (checkpoint de
        # investigación): `resolver_ids_operables_por_telefono` resuelve el
        # `opportunity_id` vía el bridge legacy `Lead.telefono` (PK global,
        # sin candado de negocio_id) — con el mismo teléfono en dos
        # Negocios, podía resolver el `opportunity_id` de OTRO Negocio.
        # `intentar_cambiar_resultado_opportunity` no tiene candado propio
        # (confía en que quien la llama ya validó ownership, mismo patrón
        # que los endpoints NUEVOS ya usan). Acá faltaba esa revalidación —
        # se agrega con la misma función ya usada por /opportunity/{id}/resultado.
        if await resolver_opportunity_operable(ids["opportunity_id"], usuario["negocio_id"]) is None:
            raise HTTPException(status_code=404, detail="Lead no encontrado")
        campos_opportunity = {k: (v if v != "" else None) for k, v in campos.items()}
        if not await intentar_cambiar_resultado_opportunity(
            ids["opportunity_id"], ids["opportunity_version"], campos_opportunity, evento=evento,
        ):
            raise HTTPException(status_code=409, detail="La conversación fue modificada por otra sesión — recargá para ver el estado actual")
    else:
        # Fallback — todavía no hay Contact/Conversation/Opportunity para
        # este teléfono (no pasó por el webhook, o falta backfill). Lead
        # sigue siendo la única fuente hasta que exista; no se inventa nada.
        await actualizar_lead(telefono, campos_explicitos=tuple(campos_explicitos), **campos)
        await registrar_evento_lead(
            telefono, tipo=evento["tipo"], descripcion=evento["descripcion"],
            autor=evento["autor"], payload=evento["payload"],
        )
    if _pide_json_explicitamente(request):
        return await _json_lead_actualizado(telefono, usuario["negocio_id"])
    return RedirectResponse(url=f"/dashboard/lead/{telefono}", status_code=303)


@router.get("/lead/{telefono}/buscar-producto")
async def buscar_producto_venta(telefono: str, q: str = "", usuario: dict = Depends(_usuario_actual)):
    """Autocompletar del catálogo real (lista de precios) para el formulario
    de Cierre de venta — el mismo buscador que ya usa Gabi por chat, para que
    el producto/marca/precio/proveedor de la venta salgan siempre de la lista
    de precios vigente en vez de que el asesor los tipee a mano."""
    if len(q.strip()) < 2:
        return JSONResponse([])
    productos = await buscar_productos(q, usuario["negocio_id"], limite=8)
    return JSONResponse([
        {
            # `id` real del producto: es lo que el carrito devuelve como
            # producto_id al guardar la venta, para que la línea quede ligada
            # al registro del catálogo y no solo a una copia de su
            # descripción. CODIGO HANA no sirve para eso (no es único).
            "id": p.get("ID"),
            "codigo": p.get("CODIGO HANA", ""),
            "descripcion": p.get("DESCRIPCIÓN", ""),
            "marca": p.get("MARCA", ""),
            "proveedor": p.get("PROVEEDOR", ""),
            "precio": p.get("PRECIO", ""),
        }
        for p in productos
    ])


@router.post("/lead/{telefono}/venta", response_class=HTMLResponse)
async def registrar_venta(
    telefono: str,
    request: Request,
    lineas_venta: str = Form("[]"),
    modalidad_pago: str = Form(""),
    cuotas: str = Form(""),
    medio_pago: str = Form(""),
    version: int = Form(...),
    usuario: dict = Depends(_usuario_actual),
    _csrf: None = Depends(verificar_csrf),
):
    lead = await obtener_lead(telefono, negocio_id=usuario["negocio_id"])
    if lead is None:
        raise HTTPException(status_code=404, detail="Lead no encontrado")
    _verificar_acceso_lead(usuario, lead)

    # Validación ANTES de tocar la versión: `intentar_avanzar_version` es una
    # escritura (avanza el contador aunque después no se aplique nada), así que
    # ejecutarla primero hacía que un simple 400 por datos inválidos consumiera
    # la versión del lead — y con eso, otra sesión que tenía el mismo lead
    # abierto legítimamente recibía un 409 de conflicto provocado por un intento
    # que nunca llegó a guardar nada. Rechazar la entrada acá deja el lead
    # exactamente como estaba.
    try:
        venta = servicio_comercial.validar_venta(lineas_venta, modalidad_pago, cuotas, medio_pago)
        # Los producto_id se comprueban contra el catálogo real acá, en el
        # mismo tramo "antes de tocar la versión" y por el mismo motivo: un id
        # que ya no existe es un 400, y un 400 no puede consumir la versión del
        # lead ni provocarle un conflicto falso a otra sesión.
        await servicio_comercial.validar_productos_de_venta(venta, usuario["negocio_id"])
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    if not await intentar_avanzar_version(telefono, version):
        # Simplificación deliberada (Sprint 2): a diferencia de resultado/
        # asignación, acá no se reintenta precargando el carrito que el
        # usuario armó — se descarta y se le pide rearmarlo contra el estado
        # ya actualizado. Evita tener que hacer viajar el carrito completo
        # (JSON del catálogo) de ida y vuelta solo para este caso, poco
        # frecuente en la práctica (dos cierres de venta simultáneos sobre
        # el mismo lead).
        if _pide_json_explicitamente(request):
            return await _json_conflicto_lead(telefono, usuario["negocio_id"])
        return await _renderizar_detalle_lead(telefono, request, usuario, hay_conflicto=True)

    # El Timeline registra lo que REALMENTE se guardó (las líneas ya validadas y
    # recortadas, la forma de pago ya normalizada), no el crudo del formulario:
    # antes anotaba `medio_pago: ""` en una venta financiada que en la fila
    # quedó como "Recibo de gas".
    pacto = await servicio_comercial.calcular_pacto_financiamiento(venta, usuario["negocio_id"], previo=lead)
    evento = {
        "tipo": "venta_registrada",
        "descripcion": f"Registró una venta ({len(venta['lineas'])} producto(s), {venta['modalidad_pago'] or 'sin modalidad'})",
        "autor": usuario["nombre"],
        "payload": {
            "lineas_venta": venta["lineas"], "modalidad_pago": venta["modalidad_pago"],
            "cuotas": venta["cuotas"], "medio_pago": venta["medio_pago"],
            "cuota_pactada": pacto["cuota_pactada"],
        },
    }
    campos = {
        "modalidad_pago": venta["modalidad_pago"], "cuotas": venta["cuotas"], "medio_pago": venta["medio_pago"],
        **pacto,
    }
    if venta["lineas"]:
        campos["resultado"] = "vendido"
        campos["fecha_agendada"] = None  # la venta cierra la cita (ver /opportunity/{id}/venta)

    ids = await resolver_ids_operables_por_telefono(telefono)
    if ids is not None:
        # Camino REAL — LEGACY / COMPATIBILIDAD (cutover real §1/§7/§10): la
        # version vigente de la Opportunity se resuelve server-side, el
        # chequeo de Lead.version de arriba ya serializó este request.
        #
        # Gate 5.5 — mismo hallazgo/corrección que /resultado: `ids` viene
        # del bridge legacy sin candado — revalidar ownership antes de
        # escribir la venta, con la misma función que ya usa el endpoint
        # nuevo /opportunity/{id}/venta.
        if await resolver_opportunity_operable(ids["opportunity_id"], usuario["negocio_id"]) is None:
            raise HTTPException(status_code=404, detail="Lead no encontrado")
        if not await cerrar_opportunity_con_venta(
            ids["opportunity_id"], ids["opportunity_version"], venta["lineas"], campos,
            revertir_resultado_al_vaciar=True, evento=evento,
        ):
            raise HTTPException(status_code=409, detail="La conversación fue modificada por otra sesión — recargá para ver el estado actual")
    else:
        # Fallback — sin Contact/Conversation/Opportunity todavía para este
        # teléfono; Lead sigue siendo la única fuente hasta que exista.
        await servicio_comercial.persistir_venta(telefono, venta, pacto)
        await registrar_evento_lead(
            telefono, tipo=evento["tipo"], descripcion=evento["descripcion"],
            autor=evento["autor"], payload=evento["payload"],
        )
    if _pide_json_explicitamente(request):
        return await _json_lead_actualizado(telefono, usuario["negocio_id"])
    return RedirectResponse(url=f"/dashboard/lead/{telefono}", status_code=303)


@router.post("/lead/{telefono}/asignar", response_class=HTMLResponse)
async def asignar_lead(
    telefono: str,
    request: Request,
    # "" = "Sin asignar" (la opción vacía del select del panel) — ver más
    # abajo: ahora desasigna de verdad en vez de no hacer nada.
    asesor_asignado: str = Form(""),
    version: int = Form(...),
    usuario: dict = Depends(servicio_identidad.requiere_rol(*ROLES_CON_VISION_TOTAL)),
    _csrf: None = Depends(verificar_csrf),
):
    lead = await obtener_lead(telefono, negocio_id=usuario["negocio_id"])
    if lead is None:
        raise HTTPException(status_code=404, detail="Lead no encontrado")

    if not await intentar_avanzar_version(telefono, version):
        if _pide_json_explicitamente(request):
            return await _json_conflicto_lead(telefono, usuario["negocio_id"])
        return await _renderizar_detalle_lead(telefono, request, usuario, hay_conflicto=True)

    evento = None
    if asesor_asignado:
        asesor_info = await obtener_usuario(asesor_asignado, negocio_id=usuario["negocio_id"])
        nombre_asesor = asesor_info["nombre"] if asesor_info else asesor_asignado
        evento = {
            "tipo": "asignado", "descripcion": f"Asignó el lead a {nombre_asesor}", "autor": usuario["nombre"],
            "payload": {"campo": "asesor_asignado", "anterior": lead.get("asesor_asignado"), "nuevo": asesor_asignado},
        }
    elif lead.get("asesor_asignado"):
        # "Sin asignar" (value="") es una decisión explícita del supervisor, no
        # un formulario incompleto: hay que desasignar. Solo si había alguien
        # asignado — desasignar un lead que ya está libre no cambia nada y no
        # merece una línea en el Timeline.
        anterior = lead["asesor_asignado"]
        asesor_info = await obtener_usuario(anterior, negocio_id=usuario["negocio_id"])
        nombre_anterior = asesor_info["nombre"] if asesor_info else anterior
        evento = {
            "tipo": "desasignado", "descripcion": f"Quitó la asignación de {nombre_anterior}", "autor": usuario["nombre"],
            "payload": {"campo": "asesor_asignado", "anterior": anterior, "nuevo": None},
        }

    ids = await resolver_ids_operables_por_telefono(telefono)
    if ids is not None:
        # Camino REAL — LEGACY / COMPATIBILIDAD (cutover real §1/§7):
        # asesor_asignado_id es campo de Conversation, no de Opportunity.
        # `evento is None` implica que no había nada que cambiar (ni asignar
        # ni un asesor previo que desasignar) — mismo criterio que el
        # original, que en ese caso tampoco escribía nada.
        if evento is not None:
            # Gate 5.5 — mismo hallazgo/corrección que /resultado y /venta:
            # `ids` viene del bridge legacy sin candado — revalidar
            # ownership antes de escribir la asignación, con la misma
            # función que ya usa el endpoint nuevo /conversation/{id}/asignar.
            if await resolver_conversation_operable(ids["conversation_id"], usuario["negocio_id"]) is None:
                raise HTTPException(status_code=404, detail="Lead no encontrado")
            if not await intentar_asignar_conversation(
                ids["conversation_id"], ids["conversation_version"], asesor_asignado or None, evento=evento,
            ):
                raise HTTPException(status_code=409, detail="La conversación fue modificada por otra sesión — recargá para ver el estado actual")
    else:
        # Fallback — sin Contact/Conversation todavía para este teléfono.
        if asesor_asignado:
            await asignar_asesor_a_lead(telefono, asesor_asignado)
        elif lead.get("asesor_asignado"):
            await asignar_asesor_a_lead(telefono, None)
        if evento is not None:
            await registrar_evento_lead(
                telefono, tipo=evento["tipo"], descripcion=evento["descripcion"],
                autor=evento["autor"], payload=evento["payload"],
            )
    if _pide_json_explicitamente(request):
        return await _json_lead_actualizado(telefono, usuario["negocio_id"])
    return RedirectResponse(url=f"/dashboard/lead/{telefono}", status_code=303)


@router.post("/lead/{telefono}/reactivar-gabi", response_class=HTMLResponse)
async def reactivar_gabi(
    telefono: str,
    request: Request,
    usuario: dict = Depends(_usuario_actual),
    _csrf: None = Depends(verificar_csrf),
):
    """Devuelve el control de la conversación a Gabi — limpia
    asesor_asignado Y pausado_manual (reusa liberar_asignacion, la misma
    función que ya usa el webhook para el caso automático de un caso cerrado
    que vuelve a escribir). Handoff manual: hoy no existe ninguna ruta para
    que un caso ABIERTO (asignado o pausado por coexistencia) vuelva a
    Gabi sin esperar a que se cierre.

    Permisos: el mismo criterio que _verificar_acceso_lead — el asesor
    dueño del lead puede devolver el control él mismo (no depende de un
    supervisor, a diferencia de "Sin asignar" en /asignar, que sí es
    exclusivo de admin/supervisor), más admin/supervisor con visión total.

    Salvaguarda de producto explícita (verificada en QA): un lead
    "vendido" NUNCA se reactiva por acá — Gabi debe quedar pausada
    indefinidamente en ese estado, sin ninguna ruta indirecta que la
    reactive."""
    lead = await obtener_lead(telefono, negocio_id=usuario["negocio_id"])
    if lead is None:
        raise HTTPException(status_code=404, detail="Lead no encontrado")
    _verificar_acceso_lead(usuario, lead)

    mensaje_vendido = "Este lead ya está vendido — Gabi permanece pausada indefinidamente y no se puede reactivar desde acá"
    ids = await resolver_ids_operables_por_telefono(telefono)
    if ids is not None:
        # Camino REAL — LEGACY / COMPATIBILIDAD (cutover real §1/§6): el
        # guardia de "vendido" se resuelve sobre Opportunity (fuente de
        # verdad), no sobre Lead.resultado — `liberar_asignacion_via_conversation`
        # ya lo hace así y reusa `liberar_asignacion()` tal cual.
        telefono_liberado = await liberar_asignacion_via_conversation(
            ids["conversation_id"], usuario["negocio_id"], autor=usuario["nombre"], motivo="reactivado_manual",
        )
        if telefono_liberado is None:
            raise HTTPException(status_code=400, detail=mensaje_vendido)
    else:
        # Fallback — sin Contact/Conversation todavía para este teléfono.
        if lead.get("resultado") == "vendido":
            raise HTTPException(status_code=400, detail=mensaje_vendido)
        await liberar_asignacion(telefono, autor=usuario["nombre"], motivo="reactivado_manual")

    if _pide_json_explicitamente(request):
        return await _json_lead_actualizado(telefono, usuario["negocio_id"])
    return RedirectResponse(url=f"/dashboard/lead/{telefono}", status_code=303)


@router.post("/disponibilidad")
async def toggle_disponibilidad(
    request: Request,
    usuario: dict = Depends(servicio_identidad.requiere_rol("asesor")), _csrf: None = Depends(verificar_csrf),
):
    """El asesor togglea si está disponible para recibir leads nuevos
    automáticamente.

    Punto 2 (2026-09-29): ahora también define si CUENTAN los minutos de
    espera que pueden rotarlo/liberarlo de un lead ya asignado (ver
    agent/memory.py::listar_leads_para_rotar_o_liberar) — antes solo
    afectaba si Gabi/`asignar_lead_pendiente_a_asesor` lo consideraban
    candidato para leads NUEVOS. Responde JSON cuando lo pide la Nueva
    Experiencia (mismo criterio que el resto del panel, ver
    `_pide_json_explicitamente`) — antes esta ruta solo existía en el panel
    viejo, así que un asesor usando el panel nuevo no tenía forma de
    marcarse a sí mismo "en turno"."""
    ahora_disponible = not usuario.get("disponible", True)
    await actualizar_disponibilidad(usuario["username"], usuario["negocio_id"], ahora_disponible)

    # Si se acaba de poner disponible, revisa si hay algún lead que se quedó
    # esperando (derivado a un asesor, pero sin nadie disponible en su
    # momento) y le asigna SOLO EL MÁS ANTIGUO — así no queda huérfano, pero
    # tampoco se le dumpea toda la cola acumulada a quien se conecta primero;
    # si hay más pendientes, se reparten con el siguiente asesor que conecte.
    if ahora_disponible:
        telefono_asignado = await servicio_comercial.asignar_lead_pendiente_a_asesor(
            usuario["username"], usuario.get("nivel"), usuario["negocio_id"]
        )
        if telefono_asignado:
            lead_asignado = await obtener_lead(telefono_asignado, negocio_id=usuario["negocio_id"])
            await notificar_lead_derivado(
                telefono_asignado, lead_asignado or {},
                "[Asignado automáticamente al ponerse disponible el asesor — estaba en espera]",
            )

    if _pide_json_explicitamente(request):
        return JSONResponse({"disponible": ahora_disponible})
    return RedirectResponse(url="/dashboard", status_code=303)


async def _pagina_gestionar_asesores(usuario: dict, request: Request | None = None, mensaje_html: str = "") -> str:
    sidebar = await _renderizar_sidebar(usuario, telefono_activo=None)
    asesores = await listar_asesores(usuario["negocio_id"])
    umbral_senior = await obtener_configuracion("umbral_senior", str(UMBRAL_SENIOR_DEFAULT), negocio_id=usuario["negocio_id"])
    umbral_intermedio = await obtener_configuracion("umbral_intermedio", str(UMBRAL_INTERMEDIO_DEFAULT), negocio_id=usuario["negocio_id"])

    # Gate UX Equipo (Decisión 5) — el backend ya exige admin para
    # nivel/resetear (ver `actualizar_nivel`/`resetear_password_asesor`);
    # acá se oculta la acción para quien de todos modos recibiría un 403
    # al enviarla (hoy Supervisor, que sigue viendo la tabla — MPA §9,
    # "Solo lectura de carga/disponibilidad") en vez de mostrar un botón
    # que siempre falla.
    es_admin_viendo = usuario["rol"] == "admin"
    filas = "".join(
        f"""<tr>
            <td class="ps-3">
                <div class="d-flex align-items-center gap-2">
                    {_avatar(a['nombre'], 30)}
                    <span class="fw-semibold">{html.escape(a['nombre'])}</span>
                </div>
            </td>
            <td>{'<span class="badge rounded-pill text-bg-success">Disponible</span>' if a.get('disponible') else '<span class="badge rounded-pill text-bg-secondary">No disponible</span>'}</td>
            <td>{f'''<form method="post" action="/dashboard/asesores/{html.escape(a["username"])}/nivel" class="d-flex gap-2">
                    {_csrf_campo(request)}
                    <select name="nivel" class="form-select form-select-sm" style="width:auto">
                        {"".join(f'<option value="{n}" {"selected" if a.get("nivel") == n else ""}>{n.capitalize()}</option>' for n in NIVELES_ASESOR)}
                    </select>
                    <button type="submit" class="btn btn-sm btn-outline-primary">Guardar</button>
                </form>''' if es_admin_viendo else html.escape((a.get('nivel') or 'sin nivel').capitalize())}</td>
            <td class="pe-3">{f'''<form method="post" action="/dashboard/asesores/{html.escape(a["username"])}/resetear" onsubmit="return confirm('¿Generar una contraseña nueva para {html.escape(a["nombre"])}? La contraseña actual dejará de funcionar.')">
                    {_csrf_campo(request)}
                    <button type="submit" class="btn btn-sm btn-outline-secondary">Resetear contraseña</button>
                </form>''' if es_admin_viendo else ''}</td>
        </tr>"""
        for a in asesores
    )

    nuevo_usuario_html = ""
    if usuario["rol"] == "admin":
        opciones_rol = "".join(
            f'<option value="{r}">{etiqueta}</option>'
            for r, etiqueta in (("asesor", "Asesor"), ("supervisor", "Supervisor"), ("admin", "Admin"))
        )
        opciones_nivel = "".join(f'<option value="{n}">{n.capitalize()}</option>' for n in NIVELES_ASESOR)
        nuevo_usuario_html = f"""
        <div class="card leads-card shadow-sm mb-3" style="max-width:480px">
            <div class="barra-acento"></div>
            <div class="card-body p-3">
                <h6 class="text-uppercase text-muted small fw-bold mb-1">Crear usuario</h6>
                <p class="text-muted small mb-2">La contraseña se genera automáticamente y se muestra una sola vez al crear la cuenta.</p>
                <form method="post" action="/dashboard/asesores/nuevo" class="row g-2">
                    {_csrf_campo(request)}
                    <div class="col-6">
                        <label class="form-label small text-muted mb-0">Usuario</label>
                        <input type="text" name="username" class="form-control form-control-sm" required autocomplete="off">
                    </div>
                    <div class="col-6">
                        <label class="form-label small text-muted mb-0">Nombre</label>
                        <input type="text" name="nombre" class="form-control form-control-sm" required>
                    </div>
                    <div class="col-6">
                        <label class="form-label small text-muted mb-0">Rol</label>
                        <select name="rol" id="rol-nuevo-usuario" class="form-select form-select-sm" onchange="document.getElementById('nivel-nuevo-usuario-wrap').style.display = this.value === 'asesor' ? '' : 'none'">
                            {opciones_rol}
                        </select>
                    </div>
                    <div class="col-6" id="nivel-nuevo-usuario-wrap">
                        <label class="form-label small text-muted mb-0">Nivel</label>
                        <select name="nivel" class="form-select form-select-sm">
                            {opciones_nivel}
                        </select>
                    </div>
                    <div class="col-12">
                        <button type="submit" class="btn btn-sm btn-primary">Crear usuario</button>
                    </div>
                </form>
            </div>
        </div>
        """

    panel = f"""
    {_titulo_seccion('bi-people-fill', 'Gestionar asesores')}
    <p class="text-muted small mb-3">El nivel se usa para la asignación automática de leads según el valor del producto de interés. La disponibilidad la controla cada asesor desde su propia sesión.</p>
    {mensaje_html}
    {nuevo_usuario_html}
    <div class="card leads-card shadow-sm mb-3" style="max-width:480px">
        <div class="barra-acento"></div>
        <div class="card-body p-3">
            <h6 class="text-uppercase text-muted small fw-bold mb-1">Umbrales de asignación automática</h6>
            <p class="text-muted small mb-2">Monto mínimo del producto de interés para requerir cada nivel de asesor.</p>
            <form method="post" action="/dashboard/asesores/umbrales" class="d-flex align-items-end gap-2">
                {_csrf_campo(request)}
                <div>
                    <label class="form-label small text-muted mb-0">Nivel Intermedio (S/)</label>
                    <input type="number" name="umbral_intermedio" min="0" step="1" class="form-control form-control-sm" value="{html.escape(umbral_intermedio)}">
                </div>
                <div>
                    <label class="form-label small text-muted mb-0">Nivel Senior (S/)</label>
                    <input type="number" name="umbral_senior" min="0" step="1" class="form-control form-control-sm" value="{html.escape(umbral_senior)}">
                </div>
                <button type="submit" class="btn btn-sm btn-primary">Guardar</button>
            </form>
        </div>
    </div>
    <div class="card shadow-sm">
        <div class="table-responsive">
            <table class="table table-hover align-middle mb-0 small">
                <thead style="background:#f8fafc">
                    <tr class="text-uppercase text-muted" style="font-size:.7rem;letter-spacing:.04em">
                        <th class="ps-3 py-3">Nombre</th><th>Disponibilidad</th><th>Nivel</th><th class="pe-3">Acceso</th>
                    </tr>
                </thead>
                <tbody>{filas or '<tr><td colspan="4" class="text-center text-muted py-4">Aún no hay asesores registrados.</td></tr>'}</tbody>
            </table>
        </div>
    </div>
    """
    sidebar_wrap = sidebar
    return f"""<div class="shell d-flex">{sidebar_wrap}<div class="main-pane flex-grow-1 p-4">{panel}</div></div>"""


@router.get("/asesores", response_class=HTMLResponse)
async def gestionar_asesores(request: Request, usuario: dict = Depends(servicio_identidad.requiere_rol(*ROLES_CON_VISION_TOTAL))):
    """Devuelve HTML (panel legacy) o JSON (selector de reasignación de la
    Nueva Experiencia) según el Accept — mismo criterio que `/pipeline`
    (`_pide_json_explicitamente`). Antes de esto, `app/api/asesores/
    route.ts` en maiek-frontend no tenía ninguna ruta JSON real que llamar
    y DERIVABA la lista de los `asesor_asignado` ya presentes en el
    pipeline — un asesor recién creado o sin cartera nunca aparecía en el
    selector, aunque estuviera disponible/habilitado (hallazgo del usuario,
    2026-09-16). `listar_asesores()` ya traía username/nombre/nivel/
    disponible filtrado por negocio_id — solo faltaba exponerlo acá."""
    if _pide_json_explicitamente(request):
        return JSONResponse({"asesores": await listar_asesores(usuario["negocio_id"])})
    cuerpo = await _pagina_gestionar_asesores(usuario, request=request)
    return _pagina("Gestionar asesores", usuario, cuerpo, request=request)


@router.post("/asesores/{username}/resetear", response_class=HTMLResponse)
async def resetear_password_asesor(
    username: str,
    request: Request,
    usuario: dict = Depends(servicio_identidad.requiere_rol("admin")),
    _csrf: None = Depends(verificar_csrf),
):
    """Genera una contraseña temporal nueva para una cuenta — para cuando
    pide recuperar acceso. Se muestra una sola vez aquí; el admin debe
    pasársela por su canal habitual, y la cuenta puede cambiarla luego desde
    su perfil.

    Gate UX Equipo (Decisión 5) — MPA §9 ("Permisos de alto nivel") no le da
    a Supervisor ninguna acción administrativa de cuenta, solo "Solo lectura
    de carga/disponibilidad": el reset de contraseña es admin-únicamente.
    Antes de esta corrección, `requiere_rol(*ROLES_CON_VISION_TOTAL)`
    permitía a un Supervisor resetear la contraseña de cualquier cuenta de
    su Negocio — una desviación de la arquitectura aprobada, no una decisión
    deliberada (ver `MAIEK_AI_PRODUCT_ARCHITECTURE.md:224-234`).

    Gate 5.4 (T3) — hallazgo real corregido: antes NO verificaba que
    `username` perteneciera al mismo Negocio del admin que ejecuta la
    acción — toma de cuenta cross-tenant real (reset de contraseña ajena,
    visible en texto plano abajo). `negocio_id` de la sesión es ahora el
    candado: `obtener_usuario`/`cambiar_password` fallan (devuelven None /
    no aplican nada) si `username` es de otro Negocio."""
    objetivo = await obtener_usuario(username, negocio_id=usuario["negocio_id"])
    if objetivo is None:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")

    nueva_password = secrets.token_urlsafe(9)
    await cambiar_password(username, usuario["negocio_id"], nueva_password)

    mensaje_html = (
        '<div class="alert alert-success py-2 small">'
        f'Nueva contraseña para <strong>{html.escape(objetivo["nombre"])}</strong> ({html.escape(username)}): '
        f'<code>{html.escape(nueva_password)}</code> — pásasela por tu canal habitual, no se volverá a mostrar.'
        '</div>'
    )
    cuerpo = await _pagina_gestionar_asesores(usuario, request=request, mensaje_html=mensaje_html)
    return _pagina("Gestionar asesores", usuario, cuerpo, request=request)


@router.post("/asesores/nuevo", response_class=HTMLResponse)
async def crear_usuario_nuevo(
    request: Request,
    username: str = Form(...),
    nombre: str = Form(...),
    rol: str = Form(...),
    nivel: str = Form(""),
    usuario: dict = Depends(servicio_identidad.requiere_rol("admin")),
    _csrf: None = Depends(verificar_csrf),
):
    """Alta de cuentas del panel — exclusivamente Admin. Rechaza si el
    username ya existe EN ESTE MISMO NEGOCIO en vez de dejar que
    crear_usuario() lo sobreescriba silenciosamente (Security Current State
    Assessment, hallazgo ya registrado — y Gate 5.4, T3: el mismo username
    SÍ puede existir en OTRO Negocio ahora, `username` es único por
    `(negocio_id, username)`, no globalmente)."""
    username = username.strip()
    if not username:
        raise HTTPException(status_code=400, detail="El usuario no puede estar vacío")
    if rol not in ("admin", "supervisor", "asesor"):
        raise HTTPException(status_code=400, detail="Rol inválido")
    if rol == "asesor" and nivel not in NIVELES_ASESOR:
        raise HTTPException(status_code=400, detail="Nivel inválido")

    if await obtener_usuario(username, negocio_id=usuario["negocio_id"]) is not None:
        mensaje_html = (
            '<div class="alert alert-danger py-2 small">'
            f'Ya existe una cuenta con el usuario <strong>{html.escape(username)}</strong> — elige otro.'
            '</div>'
        )
        cuerpo = await _pagina_gestionar_asesores(usuario, request=request, mensaje_html=mensaje_html)
        return _pagina("Gestionar asesores", usuario, cuerpo, request=request)

    nueva_password = secrets.token_urlsafe(9)
    # Gate 5.2 (corrección H3): negocio_id se toma del Negocio del propio
    # admin que está creando la cuenta — contexto explícito, ya resuelto por
    # ServicioIdentidad, nunca un default global. Generaliza sin cambios a
    # un futuro Negocio 002: su admin crea usuarios con su propio negocio_id.
    await crear_usuario(
        username, nueva_password, nombre, rol, negocio_id=usuario["negocio_id"],
        nivel=nivel if rol == "asesor" else None,
    )

    mensaje_html = (
        '<div class="alert alert-success py-2 small">'
        f'Cuenta creada para <strong>{html.escape(nombre)}</strong> ({html.escape(username)}, rol {html.escape(rol)}). '
        f'Contraseña: <code>{html.escape(nueva_password)}</code> — pásasela por tu canal habitual, no se volverá a mostrar.'
        '</div>'
    )
    cuerpo = await _pagina_gestionar_asesores(usuario, request=request, mensaje_html=mensaje_html)
    return _pagina("Gestionar asesores", usuario, cuerpo, request=request)


@router.post("/asesores/{username}/nivel")
async def actualizar_nivel(
    username: str,
    nivel: str = Form(...),
    usuario: dict = Depends(servicio_identidad.requiere_rol("admin")),
    _csrf: None = Depends(verificar_csrf),
):
    """Gate UX Equipo (Decisión 5) — edición de nivel es admin-únicamente,
    mismo criterio y misma evidencia que `resetear_password_asesor` arriba."""
    if nivel not in NIVELES_ASESOR:
        raise HTTPException(status_code=400, detail="Nivel inválido")
    await actualizar_nivel_asesor(username, usuario["negocio_id"], nivel)
    return RedirectResponse(url="/dashboard/asesores", status_code=303)


@router.post("/asesores/umbrales")
async def actualizar_umbrales_asignacion(
    umbral_intermedio: str = Form(...),
    umbral_senior: str = Form(...),
    usuario: dict = Depends(servicio_identidad.requiere_rol("admin")),
    _csrf: None = Depends(verificar_csrf),
):
    """Gate UX Equipo (Decisión 5) — umbrales de asignación automática son
    una acción administrativa de cuenta/configuración, admin-únicamente,
    mismo criterio que las dos rutas anteriores.

    Tenant-scoped (auditoría H3): negocio_id sale siempre de usuario["negocio_id"]
    (sesión), nunca del cliente — cierra el hallazgo de que estos umbrales
    escribían siempre la fila global de Configuracion, afectando a
    cualquier otro negocio que llegara a existir."""
    try:
        valor_intermedio = float(umbral_intermedio)
        valor_senior = float(umbral_senior)
    except ValueError:
        raise HTTPException(status_code=400, detail="Los umbrales deben ser números")
    if valor_intermedio < 0 or valor_senior < 0:
        raise HTTPException(status_code=400, detail="Los umbrales no pueden ser negativos")
    if valor_senior < valor_intermedio:
        raise HTTPException(status_code=400, detail="El umbral Senior no puede ser menor que el de Intermedio")

    await guardar_configuracion("umbral_intermedio", str(valor_intermedio), negocio_id=usuario["negocio_id"])
    await guardar_configuracion("umbral_senior", str(valor_senior), negocio_id=usuario["negocio_id"])
    return RedirectResponse(url="/dashboard/asesores", status_code=303)


# ── Equipo (Nueva Experiencia — Gate UX Equipo) ─────────────────────────
#
# Deliberadamente separado de `/dashboard/asesores` (arriba): esa ruta sigue
# siendo el panel legacy HTML + el listado asesor-únicamente que ya
# consumen los selectores de asignación de leads (`listar_asesores`, sin
# tocar — ver `app/api/asesores/route.ts` en maiek-frontend, que documenta
# ese contrato). Estas rutas nuevas son JSON puro, para la pantalla Equipo
# de la Nueva Experiencia, y sí exponen TODAS las cuentas (Decisión 6).


@router.get("/equipo")
async def listar_equipo_json(usuario: dict = Depends(_usuario_actual)):
    """Listado de cuentas para la pantalla Equipo — MPA §9: Admin y
    Supervisor ven TODAS las cuentas del Negocio (Decisión 6 del Gate UX
    Equipo); un Asesor ve únicamente su propia fila (MPA §9: "Solo su
    propia disponibilidad" — CDS Cap. 7.C, "Errores comunes": nunca la
    disponibilidad/carga de otro asesor). Solo JSON, mismo patrón que
    `/dashboard/sesion` — sin negociación de contenido porque no hay un
    render HTML equivalente que conservar."""
    if usuario["rol"] in ROLES_CON_VISION_TOTAL:
        miembros = await listar_equipo(usuario["negocio_id"])
    else:
        miembros = [{
            "username": usuario["username"], "nombre": usuario["nombre"], "rol": usuario["rol"],
            "nivel": usuario.get("nivel"), "disponible": usuario.get("disponible"),
        }]

    usernames_asesor = [m["username"] for m in miembros if m["rol"] == "asesor"]
    conteos_carga = (
        await contar_conversations_activas_por_asesor(usuario["negocio_id"], usernames_asesor)
        if usernames_asesor else {}
    )
    # Punto 2 (2026-09-29) — seguimiento de rotación por inactividad, la
    # data cruda de eficiencia que pidió el usuario ("esto debe salir en el
    # seguimiento del supervisor"). Últimos 30 días; solo tiene sentido para
    # asesores, mismo criterio que "carga".
    rotaciones = (
        await contar_rotaciones_por_inactividad_por_asesor(usuario["negocio_id"])
        if usernames_asesor else {}
    )
    return JSONResponse({
        "miembros": [
            # "carga" (leads activos) solo tiene sentido para asesores — Admin/
            # Supervisor nunca reciben asignación directa. `None` acá es lo que
            # la pantalla Equipo traduce a "—" (Decisión aprobada: nunca
            # inventar una métrica de disponibilidad/carga para esos roles).
            {
                **m,
                "carga": conteos_carga.get(m["username"]) if m["rol"] == "asesor" else None,
                "veces_rotado_desde": rotaciones.get(m["username"], {}).get("veces_rotado_desde") if m["rol"] == "asesor" else None,
                "promedio_minutos_sin_responder": rotaciones.get(m["username"], {}).get("promedio_minutos_sin_responder") if m["rol"] == "asesor" else None,
            }
            for m in miembros
        ],
    })


@router.post("/equipo/nuevo")
async def crear_equipo_usuario(
    request: Request,
    usuario: dict = Depends(servicio_identidad.requiere_rol("admin")),
    _csrf: None = Depends(verificar_csrf),
):
    """Versión JSON de `crear_usuario_nuevo` (arriba) para la pantalla Equipo
    de la Nueva Experiencia — mismas reglas (admin-only, username único por
    Negocio, rol/nivel válidos). Devuelve la contraseña temporal UNA vez; el
    frontend no la vuelve a poder pedir (mismo contrato que el reset)."""
    try:
        datos = await request.json()
    except Exception:
        datos = {}
    if not isinstance(datos, dict):
        datos = {}
    username = str(datos.get("username") or "").strip()
    nombre = str(datos.get("nombre") or "").strip()
    rol = str(datos.get("rol") or "")
    nivel = str(datos.get("nivel") or "")

    if not username or len(username) > 50:
        raise HTTPException(status_code=400, detail="El usuario es obligatorio (máximo 50 caracteres)")
    if not nombre or len(nombre) > 100:
        raise HTTPException(status_code=400, detail="El nombre es obligatorio (máximo 100 caracteres)")
    if rol not in ("admin", "supervisor", "asesor"):
        raise HTTPException(status_code=400, detail="Rol inválido")
    if rol == "asesor" and nivel not in NIVELES_ASESOR:
        raise HTTPException(status_code=400, detail="Nivel inválido")

    if await obtener_usuario(username, negocio_id=usuario["negocio_id"]) is not None:
        raise HTTPException(status_code=409, detail=f"Ya existe una cuenta con el usuario {username} — elige otro.")

    nueva_password = secrets.token_urlsafe(9)
    await crear_usuario(
        username, nueva_password, nombre, rol, negocio_id=usuario["negocio_id"],
        nivel=nivel if rol == "asesor" else None,
    )
    return JSONResponse({
        "username": username,
        "nombre": nombre,
        "rol": rol,
        "password_temporal": nueva_password,
    })


@router.post("/equipo/{username}/resetear")
async def resetear_password_equipo(
    username: str,
    usuario: dict = Depends(servicio_identidad.requiere_rol("admin")),
    _csrf: None = Depends(verificar_csrf),
):
    """Versión JSON de `resetear_password_asesor` (arriba), para el flujo de
    Confirm Dialog de la pantalla Equipo: el frontend confirma con el
    usuario ANTES de llamar esta ruta (nunca al revés — Human Decision
    Gate), y esta ruta ejecuta y devuelve la contraseña temporal una sola
    vez — el frontend no vuelve a poder pedirla, no queda guardada en
    ningún estado que sobreviva al cierre del diálogo."""
    objetivo = await obtener_usuario(username, negocio_id=usuario["negocio_id"])
    if objetivo is None:
        raise HTTPException(status_code=404, detail="Cuenta no encontrada")

    nueva_password = secrets.token_urlsafe(9)
    await cambiar_password(username, usuario["negocio_id"], nueva_password)
    return JSONResponse({
        "username": username,
        "nombre": objetivo["nombre"],
        "password_temporal": nueva_password,
    })


@router.post("/equipo/{username}/toggle")
async def toggle_equipo_usuario(
    username: str,
    usuario: dict = Depends(servicio_identidad.requiere_rol("admin")),
    _csrf: None = Depends(verificar_csrf),
):
    """Apaga/prende una cuenta del panel (Gate Equipo, 2026-09-14) — mismo
    patrón que `resetear_password_equipo`: sin cuerpo, la confirmación ya
    ocurrió en el cliente. Reversible: el mismo botón vuelve a activarla."""
    nuevo_estado = await toggle_usuario_activo(username, usuario["negocio_id"])
    if nuevo_estado is None:
        raise HTTPException(status_code=404, detail="Cuenta no encontrada")
    return JSONResponse({"ok": True, "activo": nuevo_estado})


@router.post("/equipo/{username}/eliminar")
async def eliminar_equipo_usuario(
    username: str,
    usuario: dict = Depends(servicio_identidad.requiere_rol("admin")),
    _csrf: None = Depends(verificar_csrf),
):
    """Elimina (soft delete) una cuenta del panel — el rol admin nunca se
    puede eliminar (decisión del usuario, Gate Equipo 2026-09-14), reforzado
    acá con un 403 explícito además del chequeo en la capa de datos."""
    resultado = await eliminar_usuario(username, usuario["negocio_id"], eliminado_por=usuario["username"])
    if resultado == "no_encontrado":
        raise HTTPException(status_code=404, detail="Cuenta no encontrada")
    if resultado == "admin_protegido":
        raise HTTPException(status_code=403, detail="No se puede eliminar una cuenta con rol admin.")
    return JSONResponse({"ok": True})


@router.get("/equipo/eliminados")
async def listar_equipo_eliminados(usuario: dict = Depends(servicio_identidad.requiere_rol("admin"))):
    """Cuentas eliminadas del Negocio, para poder restaurarlas (solo admin). Nunca incluye contraseñas."""
    eliminados = await mem.listar_usuarios_eliminados(usuario["negocio_id"])
    return JSONResponse({
        "eliminados": [{**u, "eliminado_en": iso_utc(u["eliminado_en"])} for u in eliminados],
    })


@router.post("/equipo/{username}/restaurar")
async def restaurar_equipo_usuario(
    username: str,
    usuario: dict = Depends(servicio_identidad.requiere_rol("admin")),
    _csrf: None = Depends(verificar_csrf),
):
    """Deshace la eliminación de una cuenta (solo admin). La cuenta vuelve DESACTIVADA y no disponible: no recibe
    leads ni puede entrar hasta que el admin la active con el toggle de Equipo (restaurar nunca reparte leads solo)."""
    resultado = await mem.restaurar_usuario(username, usuario["negocio_id"])
    if resultado == "no_encontrado":
        raise HTTPException(status_code=404, detail="Cuenta no encontrada")
    if resultado == "no_eliminado":
        raise HTTPException(status_code=409, detail="Esa cuenta no está eliminada.")
    return JSONResponse({"ok": True, "activo": False})


# ── Gestión de campañas ────────────────────────────────────────────────

TIPOS_DETECCION = {
    "texto_saludo": "Texto del saludo (wa.link)",
    "referral_meta": "Anuncio de Meta (referral)",
    "por_anuncio": "Anuncio de Meta (regla por anuncio)",
    "leadgen_meta": "Formulario de Meta (Lead Ads)",
}
# La Nueva Experiencia suma el envío de SMS con código (2026-10-29); el panel Legacy no lo ofrece (no sabe armar el
# saludo con el código) pero sí lo muestra con su nombre.
TIPOS_DETECCION_JSON = {**TIPOS_DETECCION, "codigo_envio": "Envío SMS (código)"}


async def _preparar_deteccion_meta(tipo_deteccion: str, patron: str, negocio_id: str) -> tuple[str, str]:
    """Las campañas de anuncios de Meta tienen UN solo mecanismo: la regla
    anuncio→campaña. Cualquier alta de tipo "referral_meta"/"por_anuncio" se normaliza a
    "por_anuncio" y exige el ID NUMÉRICO del anuncio como patrón (nunca una palabra
    clave); además ese anuncio no puede pertenecer ya a otra campaña."""
    if tipo_deteccion not in ("referral_meta", "por_anuncio"):
        return tipo_deteccion, patron
    patron = patron.strip()
    if not patron.isdigit():
        raise HTTPException(
            status_code=400,
            detail="Para una campaña de anuncio de Meta indica el ID numérico del anuncio (lo ves en «Anuncios detectados»), no una palabra clave.",
        )
    if patron in await obtener_reglas_anuncio(negocio_id):
        raise HTTPException(status_code=400, detail="Ese anuncio ya pertenece a otra campaña.")
    return "por_anuncio", patron


def _campana_a_json(c: dict) -> dict:
    """Forma JSON de una Campana para la Nueva Experiencia (Gate Campañas P0)
    — nunca incluye `negocio_id`/`unidad_id` (internos, ya implícitos en la
    sesión). Compartida entre listado/crear/editar/toggle para que las 4
    rutas `.json` nunca describan la misma campaña de dos formas distintas."""
    return {
        "id": c["id"],
        "nombre": c["nombre"],
        "tipo_deteccion": c["tipo_deteccion"],
        "patron": c["patron"],
        "codigo_material": c["codigo_material"],
        "producto_promocional": c["producto_promocional"],
        "precio_promocional": c["precio_promocional"],
        "texto_saludo": c["texto_saludo"],
        # Enlace de WhatsApp con el saludo ya escrito, listo para pegar en el SMS (2026-10-29).
        "link_whatsapp": servicio_canales.generar_link_whatsapp(c["texto_saludo"]) if c.get("texto_saludo") else None,
        # Envío de SMS: qué promociona y el texto del SMS (None en el resto de campañas).
        "alcance": c.get("alcance"),
        "nivel_producto": c.get("nivel_producto"),
        "tipo_producto": c.get("tipo_producto"),
        "subtipo_producto": c.get("subtipo_producto"),
        "texto_sms": c.get("texto_sms"),
        "activa": c["activa"],
        "creado": iso_utc(c["creado"]),
    }


@router.get("/campanas.json")
async def campanas_json(usuario: dict = Depends(servicio_identidad.requiere_rol("admin", "supervisor"))):
    """Listado de campañas para la Nueva Experiencia (Gate Campañas P0) —
    mismo dato que ya sirve `gestionar_campanas` en HTML (`listar_campanas` +
    `contar_opportunities_por_campana`, sin tocar ninguna), sin el HTML.
    `puede_gestionar` replica el mismo criterio que `puede_escribir` en la
    pantalla Legacy: el Supervisor ve todo, ningún botón de escritura."""
    campanas = await listar_campanas(usuario["negocio_id"])
    conteos = {c["campana"]: c for c in await contar_opportunities_por_campana(usuario["negocio_id"])}
    return JSONResponse({
        "campanas": [
            {
                **_campana_a_json(c),
                "conteo": {
                    "total": conteos.get(c["nombre"], {}).get("total", 0),
                    "vendidos": conteos.get(c["nombre"], {}).get("vendidos", 0),
                },
            }
            for c in campanas
        ],
        "puede_gestionar": usuario["rol"] == "admin",
        # Para el formulario «Envío SMS» (2026-10-29): el nombre del negocio y su rubro rellenan las plantillas del SMS
        # ({negocio}, {rubro}); las unidades, si las hay, permiten un SMS de una sola unidad.
        "negocio": await _negocio_para_sms(usuario["negocio_id"]),
    })


CLAVE_RUBRO_NEGOCIO = "negocio_rubro"
RUBRO_POR_DEFECTO = "nuestros productos"
LARGO_MAXIMO_RUBRO = 60
LARGO_MAXIMO_TEXTO_SMS = 500
MARCA_ENLACE_SMS = "[enlace]"


async def _negocio_para_sms(negocio_id: str) -> dict:
    negocio = await obtener_negocio(negocio_id)
    unidades = await listar_unidades_de_negocio(negocio_id, solo_activas=True)
    return {
        "nombre": (negocio or {}).get("nombre") or "",
        "rubro": await obtener_configuracion(CLAVE_RUBRO_NEGOCIO, "", negocio_id=negocio_id) or "",
        "rubro_por_defecto": RUBRO_POR_DEFECTO,
        "unidades": [{"id": u["id"], "nombre": u["nombre"]} for u in unidades],
        # Plantillas propias de SMS del negocio y si su remitente ya muestra el nombre (parte 2, 2026-10-29).
        "sms": await plantillas_sms.estado(negocio_id),
    }


def _precio_a_numero(precio) -> float | None:
    texto = re.sub(r"[^\d.,]", "", str(precio or "")).replace(",", "")
    try:
        valor = float(texto)
    except ValueError:
        return None
    return valor if valor > 0 else None


def categorias_del_catalogo(productos: list[dict]) -> list[dict]:
    """Tipos y subtipos del catálogo activo con cuántos productos tienen y el precio más bajo — para elegir el grupo de
    un envío de SMS y proponer su precio «desde». Puro: recibe las filas de `listar_productos_activos`."""
    grupos: dict[str, dict] = {}
    for p in productos:
        tipo = (p.get("TIPO") or "").strip()
        if not tipo:
            continue
        subtipo = (p.get("SUB TIPO") or "").strip()
        precio = _precio_a_numero(p.get("PRECIO"))
        grupo = grupos.setdefault(tipo, {"tipo": tipo, "cantidad": 0, "precio_min": None, "subtipos": {}})
        destinos = [grupo] + ([grupo["subtipos"].setdefault(subtipo, {"subtipo": subtipo, "cantidad": 0, "precio_min": None})] if subtipo else [])
        for destino in destinos:
            destino["cantidad"] += 1
            if precio is not None and (destino["precio_min"] is None or precio < destino["precio_min"]):
                destino["precio_min"] = precio
    return [
        {**g, "subtipos": sorted(g["subtipos"].values(), key=lambda s: s["subtipo"].lower())}
        for g in sorted(grupos.values(), key=lambda g: g["tipo"].lower())
    ]


@router.get("/campanas/categorias.json")
async def campanas_categorias_json(usuario: dict = Depends(servicio_identidad.requiere_rol("admin", "supervisor"))):
    """Tipos y subtipos del catálogo del negocio (con cantidad y precio más bajo) para el envío de SMS por grupo."""
    return JSONResponse({"categorias": categorias_del_catalogo(await listar_productos_activos(usuario["negocio_id"]))})


@router.post("/campanas/rubro.json")
async def guardar_rubro_negocio_json(
    request: Request,
    usuario: dict = Depends(servicio_identidad.requiere_rol("admin")),
    _csrf: None = Depends(verificar_csrf),
):
    """Rubro del negocio ("gasodomésticos", "muebles y colchones"): rellena {rubro} en el SMS de alcance «Negocio».
    Uno por negocio, así Maiek sirve igual a cualquier empresa sin textos propios de Cálidda."""
    body = await request.json()
    rubro = " ".join((body.get("rubro") or "").split())
    if len(rubro) > LARGO_MAXIMO_RUBRO:
        raise HTTPException(status_code=400, detail=f"El rubro admite hasta {LARGO_MAXIMO_RUBRO} caracteres.")
    await guardar_configuracion(CLAVE_RUBRO_NEGOCIO, rubro, negocio_id=usuario["negocio_id"])
    return JSONResponse({"ok": True, "rubro": rubro})


@router.get("/configuracion/sms.json")
async def configuracion_sms_json(usuario: dict = Depends(servicio_identidad.requiere_rol("admin"))):
    """Configuración de los SMS del negocio (solo Admin, como el resto de Configuración): `{negocio, rubro,
    plantillas: [{id, alcance, texto, creado_por, creado, actualizado}], remitente_muestra_negocio}`."""
    datos = await _negocio_para_sms(usuario["negocio_id"])
    return JSONResponse({
        "negocio": datos["nombre"], "rubro": datos["rubro"], "rubro_por_defecto": datos["rubro_por_defecto"], **datos["sms"],
    })


@router.post("/configuracion/sms.json")
async def actualizar_configuracion_sms_json(
    request: Request,
    usuario: dict = Depends(servicio_identidad.requiere_rol("admin")),
    _csrf: None = Depends(verificar_csrf),
):
    """Una acción por llamada, en el negocio de la sesión (nunca del cuerpo):
    `{accion: "guardar", alcance, texto, id?}` crea o edita una plantilla · `{accion: "eliminar", id}` ·
    `{accion: "remitente", muestra_negocio: bool}` · `{accion: "rubro", rubro}`. Responde el estado completo."""
    cuerpo = await _cuerpo_objeto_json(request)
    negocio_id, autor = usuario["negocio_id"], usuario.get("username")
    accion = cuerpo.get("accion")
    try:
        if accion == "guardar":
            await plantillas_sms.guardar(negocio_id, autor, cuerpo.get("alcance") or "", cuerpo.get("texto") or "", cuerpo.get("id") or None)
        elif accion == "eliminar":
            await plantillas_sms.eliminar(negocio_id, autor, str(cuerpo.get("id") or ""))
        elif accion == "remitente":
            if not isinstance(cuerpo.get("muestra_negocio"), bool):
                raise ValueError("Indica si el remitente muestra el nombre del negocio (sí o no).")
            await plantillas_sms.fijar_remitente(negocio_id, autor, cuerpo["muestra_negocio"])
        elif accion == "rubro":
            rubro = " ".join((cuerpo.get("rubro") or "").split())
            if len(rubro) > LARGO_MAXIMO_RUBRO:
                raise ValueError(f"El rubro admite hasta {LARGO_MAXIMO_RUBRO} caracteres.")
            await guardar_configuracion(CLAVE_RUBRO_NEGOCIO, rubro, negocio_id=negocio_id)
        else:
            raise ValueError("Acción desconocida.")
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return await configuracion_sms_json(usuario)


async def _validar_alcance_envio(body: dict, negocio_id: str, codigo_material: str) -> dict:
    """Campos de qué promociona un envío de SMS, ya validados contra el catálogo del negocio."""
    alcance = (body.get("alcance") or "").strip()
    if alcance not in servicio_canales.ALCANCES_ENVIO:
        raise HTTPException(status_code=400, detail="Elige qué promociona el SMS: el negocio o un producto.")
    campos = {"alcance": alcance, "nivel_producto": None, "tipo_producto": None, "subtipo_producto": None, "unidad_id": None}
    if alcance == "negocio":
        unidad_id = (body.get("unidad_id") or "").strip() or None
        if unidad_id and unidad_id not in {u["id"] for u in await listar_unidades_de_negocio(negocio_id, solo_activas=True)}:
            raise HTTPException(status_code=400, detail="Esa unidad de negocio no existe o está inactiva.")
        campos["unidad_id"] = unidad_id
        return campos
    nivel = (body.get("nivel_producto") or "").strip()
    if nivel not in servicio_canales.NIVELES_PRODUCTO:
        raise HTTPException(status_code=400, detail="Elige si el SMS es de un tipo, un subtipo o un producto.")
    campos["nivel_producto"] = nivel
    if nivel == "producto":
        if not codigo_material:
            raise HTTPException(status_code=400, detail="Elige el producto del catálogo.")
        return campos
    categorias = {c["tipo"]: c for c in categorias_del_catalogo(await listar_productos_activos(negocio_id))}
    tipo = (body.get("tipo_producto") or "").strip()
    if tipo not in categorias:
        raise HTTPException(status_code=400, detail="Ese tipo no está en el catálogo vigente.")
    campos["tipo_producto"] = tipo
    if nivel == "subtipo":
        subtipo = (body.get("subtipo_producto") or "").strip()
        if subtipo not in {s["subtipo"] for s in categorias[tipo]["subtipos"]}:
            raise HTTPException(status_code=400, detail="Ese subtipo no está en el catálogo vigente.")
        campos["subtipo_producto"] = subtipo
    return campos


@router.post("/campanas/nueva.json")
async def crear_campana_nueva_json(
    request: Request,
    usuario: dict = Depends(servicio_identidad.requiere_rol("admin")),
    _csrf: None = Depends(verificar_csrf),
):
    """Variante JSON de `crear_campana_nueva` para la Nueva Experiencia (Gate
    Campañas P0) — path `.json` distinto del Legacy (`POST /campanas/nueva`,
    que sigue esperando `Form(...)` sin ningún cambio) para no colisionar;
    misma validación y la misma `crear_campana` de `memory.py`, sin duplicar
    lógica."""
    body = await request.json()
    nombre = (body.get("nombre") or "").strip()
    tipo_deteccion = (body.get("tipo_deteccion") or "").strip()
    patron = (body.get("patron") or "").strip()
    texto_saludo = (body.get("texto_saludo") or "").strip()
    codigo_material = (body.get("codigo_material") or "").strip()
    producto_promocional = (body.get("producto_promocional") or "").strip()
    precio_promocional = (body.get("precio_promocional") or "").strip()

    if not nombre:
        raise HTTPException(status_code=400, detail="El nombre es obligatorio")
    if tipo_deteccion not in TIPOS_DETECCION_JSON:
        raise HTTPException(status_code=400, detail="Tipo de detección inválido")
    if not patron:
        raise HTTPException(status_code=400, detail="El patrón de detección es obligatorio")
    if codigo_material and await obtener_producto_por_codigo(codigo_material, usuario["negocio_id"]) is None:
        raise HTTPException(status_code=400, detail=f"El código de material '{codigo_material}' no existe en la lista de precios vigente")
    envio = {}
    if tipo_deteccion == servicio_canales.TIPO_CODIGO_ENVIO:
        # Envío de SMS: el patrón es el código; el saludo del enlace es el del usuario con el código al final.
        patron = patron.upper()
        error = servicio_canales.validar_codigo_envio(patron)
        if error:
            raise HTTPException(status_code=400, detail=error)
        if not texto_saludo:
            raise HTTPException(status_code=400, detail="Escribe el saludo de WhatsApp: el código se agrega al final.")
        for otra in await listar_campanas(usuario["negocio_id"]):
            if otra["tipo_deteccion"] == servicio_canales.TIPO_CODIGO_ENVIO and servicio_canales.codigos_se_cruzan(patron, otra["patron"]):
                raise HTTPException(status_code=400, detail=f"El código se cruza con el de «{otra['nombre']}» ({otra['patron']}). Usa uno distinto.")
        texto_saludo = servicio_canales.saludo_con_codigo(texto_saludo, patron)
        if len(texto_saludo) > 500:
            raise HTTPException(status_code=400, detail="El saludo con el código supera los 500 caracteres. Acórtalo.")
        envio = await _validar_alcance_envio(body, usuario["negocio_id"], codigo_material)
        texto_sms = (body.get("texto_sms") or "").strip()
        if texto_sms and MARCA_ENLACE_SMS not in texto_sms:
            raise HTTPException(status_code=400, detail=f"El texto del SMS debe incluir {MARCA_ENLACE_SMS}, donde va el enlace de WhatsApp.")
        if len(texto_sms) > LARGO_MAXIMO_TEXTO_SMS:
            raise HTTPException(status_code=400, detail=f"El texto del SMS admite hasta {LARGO_MAXIMO_TEXTO_SMS} caracteres.")
        envio["texto_sms"] = texto_sms or None
    if tipo_deteccion == "texto_saludo" and texto_saludo:
        if patron.lower() not in texto_saludo.lower():
            raise HTTPException(
                status_code=400,
                detail="El patrón no aparece dentro del mensaje de saludo — así nunca se detectaría esta campaña. Usa un fragmento que sí esté en el saludo.",
            )

    tipo_deteccion, patron = await _preparar_deteccion_meta(tipo_deteccion, patron, usuario["negocio_id"])
    campana_creada = await crear_campana(
        nombre=nombre, tipo_deteccion=tipo_deteccion,
        # El código de envío se guarda tal cual se ve en el saludo (mayúsculas); la detección no distingue mayúsculas.
        patron=patron if tipo_deteccion == servicio_canales.TIPO_CODIGO_ENVIO else patron.lower(),
        texto_saludo=texto_saludo, codigo_material=codigo_material,
        producto_promocional=producto_promocional, precio_promocional=precio_promocional,
        negocio_id=usuario["negocio_id"], **envio,
    )
    if tipo_deteccion == "por_anuncio":
        await guardar_regla_anuncio(usuario["negocio_id"], patron, campana_creada["id"], autor=usuario.get("username"))
    return JSONResponse({"ok": True, "campana": {**_campana_a_json(campana_creada), "conteo": {"total": 0, "vendidos": 0}}})


@router.post("/campanas/{campana_id}/editar.json")
async def editar_promo_campana_json(
    campana_id: int,
    request: Request,
    usuario: dict = Depends(servicio_identidad.requiere_rol("admin")),
    _csrf: None = Depends(verificar_csrf),
):
    """Variante JSON de `editar_promo_campana` (Gate Campañas P0) — mismos
    campos editables que el Legacy (producto/precio/código de material).
    `nombre`/`tipo_deteccion` no viajan. Desde 2026-10-29 también `patron`,
    SOLO en campañas de saludo ("texto_saludo") y solo si aparece en su
    saludo: antes corregir un patrón mal escrito exigía la consola. El código
    de un envío de SMS no se edita: los enlaces ya enviados lo llevan."""
    campana = await _verificar_ownership_campana(usuario, campana_id)
    body = await request.json()
    codigo_material = (body.get("codigo_material") or "").strip()
    producto_promocional = (body.get("producto_promocional") or "").strip()
    precio_promocional = (body.get("precio_promocional") or "").strip()
    if codigo_material and await obtener_producto_por_codigo(codigo_material, usuario["negocio_id"]) is None:
        raise HTTPException(status_code=400, detail=f"El código de material '{codigo_material}' no existe en la lista de precios vigente")
    cambios = {}
    if "patron" in body:
        patron = (body.get("patron") or "").strip().lower()
        if campana["tipo_deteccion"] != "texto_saludo":
            if patron != (campana["patron"] or "").lower():
                raise HTTPException(status_code=400, detail="Solo se puede editar el texto que se busca en campañas de saludo.")
        elif patron != campana["patron"]:
            if len(patron) < 8:
                raise HTTPException(status_code=400, detail="El texto que se busca debe tener al menos 8 caracteres para no confundirse con otros mensajes.")
            if campana.get("texto_saludo") and patron not in campana["texto_saludo"].lower():
                raise HTTPException(
                    status_code=400,
                    detail="Ese texto no aparece en el saludo de la campaña: así nunca se detectaría. Copia un fragmento del saludo.",
                )
            cambios["patron"] = patron
    await actualizar_campana(
        campana_id,
        codigo_material=codigo_material or None,
        producto_promocional=producto_promocional,
        precio_promocional=precio_promocional,
        **cambios,
    )
    if cambios:
        logger.info(f"Campaña {campana_id}: texto que se busca cambiado por {usuario.get('username')}")
    campana_actualizada = await obtener_campana(campana_id)
    return JSONResponse({"ok": True, "campana": _campana_a_json(campana_actualizada)})


@router.post("/campanas/{campana_id}/eliminar.json")
async def eliminar_campana_json(
    campana_id: int,
    usuario: dict = Depends(servicio_identidad.requiere_rol("admin")),
    _csrf: None = Depends(verificar_csrf),
):
    """Elimina una campaña SOLO si nunca tuvo conversaciones (así no se pierde historial). Con
    actividad, el camino es desactivarla. Sus reglas de anuncio se borran con ella."""
    campana = await _verificar_ownership_campana(usuario, campana_id)
    if not await eliminar_campana(campana_id, usuario["negocio_id"], eliminado_por=usuario["username"]):
        raise HTTPException(
            status_code=400,
            detail=f"«{campana['nombre']}» ya tiene conversaciones: no se puede eliminar sin perder su historial. Desactívala en su lugar.",
        )
    return JSONResponse({"ok": True})


@router.get("/campanas/eliminadas.json")
async def campanas_eliminadas_json(usuario: dict = Depends(servicio_identidad.requiere_rol("admin"))):
    """Campañas eliminadas del Negocio (borrado lógico), para poder restaurarlas — solo admin, igual que eliminar.
    Cada una trae los `anuncios` (source_id) que tenía vinculados."""
    eliminadas = await mem.listar_campanas_eliminadas(usuario["negocio_id"])
    return JSONResponse({
        "eliminadas": [
            {"id": c["id"], "nombre": c["nombre"], "tipo_deteccion": c["tipo_deteccion"],
             "eliminado_en": iso_utc(c["eliminado_en"]), "eliminado_por": c["eliminado_por"], "anuncios": c["anuncios"]}
            for c in eliminadas
        ],
    })


@router.post("/campanas/{campana_id}/restaurar.json")
async def restaurar_campana_json(
    campana_id: int,
    usuario: dict = Depends(servicio_identidad.requiere_rol("admin")),
    _csrf: None = Depends(verificar_csrf),
):
    """Deshace la eliminación de una campaña (solo admin). Vuelve DESACTIVADA: no detecta leads hasta que un admin la
    active. Re-vincula sus anuncios si siguen libres y devuelve cuáles no pudo (otra campaña ya los tiene)."""
    r = await mem.restaurar_campana(campana_id, usuario["negocio_id"])
    if r["resultado"] == "no_encontrada":
        raise HTTPException(status_code=404, detail="Campaña no encontrada")
    if r["resultado"] == "no_eliminada":
        raise HTTPException(status_code=409, detail="Esa campaña no está eliminada.")
    if r["resultado"] == "nombre_en_uso":
        raise HTTPException(status_code=409, detail="Ya existe otra campaña con ese nombre: cámbiale el nombre a una de las dos antes de restaurar.")
    return JSONResponse({
        "ok": True, "activa": False,
        "anuncios_restaurados": r["anuncios_restaurados"], "anuncios_no_restaurados": r["anuncios_no_restaurados"],
    })


@router.post("/campanas/{campana_id}/toggle.json")
async def toggle_campana_json(
    campana_id: int,
    usuario: dict = Depends(servicio_identidad.requiere_rol("admin")),
    _csrf: None = Depends(verificar_csrf),
):
    """Variante JSON de `toggle_campana` (Gate Campañas P0) — mismo candado
    de ownership y misma `actualizar_campana`, sin duplicar lógica."""
    actual = await _verificar_ownership_campana(usuario, campana_id)
    await actualizar_campana(campana_id, activa=not actual["activa"])
    campana_actualizada = await obtener_campana(campana_id)
    return JSONResponse({"ok": True, "campana": _campana_a_json(campana_actualizada)})


def _anuncio_a_json(a: dict) -> dict:
    return {**a, "primero": iso_utc(a["primero"]), "ultimo": iso_utc(a["ultimo"])}


@router.get("/uso-mensajes.json")
async def uso_mensajes_json(
    mes: str = "", usuario: dict = Depends(servicio_identidad.requiere_rol("admin")),
):
    """Uso y costo de mensajes de WhatsApp del mes, por número del negocio,
    según los estados que Meta informó (ver `resumen_uso_mensual`): gratis de
    la cuota usados/restantes, cobrables, ventana gratuita de anuncios y
    alertas 80/95/100 %. `mes` = YYYY-MM (por defecto, el mes en curso). Solo
    lectura; SOLO Admin (2026-10-12: entrega costos de Meta; supervisor y
    asesor reciben 403)."""
    if mes and not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", mes):
        raise HTTPException(status_code=400, detail="El mes debe tener el formato AAAA-MM")
    return JSONResponse(await resumen_uso_mensual(usuario["negocio_id"], mes or None))


@router.get("/uso-mensajes/envios.json")
async def uso_mensajes_envios_json(
    mes: str = "", usuario: dict = Depends(servicio_identidad.requiere_rol("admin")),
):
    """Envíos del mes por origen (Gabi, reenganche, asesores, plantillas...):
    cuántos salieron, cuántos frenó la política de costo y por qué, y qué terminó
    cobrando Meta por cada origen (ver `resumen_envios_por_origen`). Solo lectura;
    SOLO Admin (2026-10-12: trae costos de Meta y `por_asesor`)."""
    if mes and not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", mes):
        raise HTTPException(status_code=400, detail="El mes debe tener el formato AAAA-MM")
    return JSONResponse(await resumen_envios_por_origen(usuario["negocio_id"], mes or None))


@router.get("/uso-mensajes/conciliacion.json")
async def uso_mensajes_conciliacion_json(
    dias: int = 7, usuario: dict = Depends(servicio_identidad.requiere_rol("admin")),
):
    """Informe de conciliación de envíos de los últimos `dias` días (1 a 90, por
    defecto 7): envíos de la capa central con resultado incierto (el POST pudo
    llegar a Meta y no se supo) o "enviado" sin wamid, y mensajes que Meta
    informó (y cobra) que el sistema no tiene registrados — posibles copias
    duplicadas o envíos hechos fuera de la capa (ver
    `listar_envios_inciertos_o_huerfanos`). Solo lectura; solo Admin."""
    if not 1 <= dias <= 90:
        raise HTTPException(status_code=400, detail="`dias` debe estar entre 1 y 90")
    return JSONResponse(await listar_envios_inciertos_o_huerfanos(usuario["negocio_id"], datetime.utcnow() - timedelta(days=dias)))


@router.get("/uso-mensajes/estimacion-previa.json")
async def uso_mensajes_estimacion_previa_json(
    desde: str = "", hasta: str = "", usuario: dict = Depends(servicio_identidad.requiere_rol("admin")),
):
    """Estima cuántos mensajes de servicio gratis se consumieron antes de que el
    registro de estados de Meta empezara a medir (ver
    `estimar_uso_previo_servicio`). `desde`/`hasta` en UTC ISO (AAAA-MM-DDTHH:MM);
    por defecto, desde el inicio del mes hasta el primer estado registrado.
    Solo lectura; solo Admin."""
    def _fecha(texto: str) -> datetime:
        try:
            return datetime.fromisoformat(texto).replace(tzinfo=None)
        except ValueError:
            raise HTTPException(status_code=400, detail="Las fechas deben ir como AAAA-MM-DDTHH:MM (UTC).")

    negocio_id = usuario["negocio_id"]
    if desde:
        inicio = _fecha(desde)
    else:
        zona = await obtener_configuracion("meta_zona_horaria_mes", "UTC", negocio_id=negocio_id)
        inicio = _limites_de_mes_utc(None, zona)[0]
    fin = _fecha(hasta) if hasta else await primer_momento_de_uso_registrado(negocio_id)
    if fin <= inicio:
        raise HTTPException(status_code=400, detail="'hasta' debe ser posterior a 'desde'.")
    return JSONResponse(await estimar_uso_previo_servicio(negocio_id, inicio, fin))


@router.get("/uso-mensajes/configuracion.json")
async def uso_mensajes_configuracion_actual_json(usuario: dict = Depends(servicio_identidad.requiere_rol("admin"))):
    """Configuración vigente de uso y envíos (interruptor de cada origen, tope,
    autorecarga, tarifas...) para pintar la pantalla. Solo lectura; solo Admin."""
    return JSONResponse(await obtener_configuracion_envios(usuario["negocio_id"]))


@router.get("/uso-mensajes/historial-cambios.json")
async def uso_mensajes_historial_cambios_json(
    limite: int = 50, antes_de: str | None = None,
    usuario: dict = Depends(servicio_identidad.requiere_rol("admin")),
):
    """Quién cambió qué de la configuración de uso y envíos, y cuándo (con el
    valor anterior y el nuevo). Solo lectura; solo Admin. Paginado hacia atrás (2026-11-03): `antes_de` (el `creado`
    del último ítem recibido, ISO 8601) trae los más antiguos y `hay_mas` dice si queda historial. Sin `antes_de` la
    respuesta es la de siempre más `hay_mas`."""
    corte = None
    if antes_de:
        try:
            corte = datetime.fromisoformat(antes_de.strip().replace("Z", "+00:00"))
            if corte.tzinfo is not None:
                corte = corte.astimezone(timezone.utc).replace(tzinfo=None)
        except ValueError:
            raise HTTPException(status_code=400, detail="`antes_de` debe ser una fecha y hora ISO 8601 (el `creado` de un ítem).")
    pagina = await mem.listar_cambios_configuracion_pagina(usuario["negocio_id"], limite, corte)
    return JSONResponse({
        "cambios": [{**c, "creado": c["creado"].isoformat() + "Z"} for c in pagina["items"]],
        "hay_mas": pagina["hay_mas"],
    })


@router.post("/uso-mensajes/detectar-zona.json")
async def uso_mensajes_detectar_zona_json(
    request: Request,
    usuario: dict = Depends(servicio_identidad.requiere_rol("admin")),
    _csrf: None = Depends(verificar_csrf),
):
    """Lee de Meta la zona horaria de la cuenta de WhatsApp Business
    (`GET /{waba_id}?fields=timezone_id`) — la que decide cuándo se reinicia la
    cuota gratis del mes — y la guarda como `meta_zona_horaria_mes`. Con
    `{"guardar": false}` solo informa, sin guardar. Si ningún canal tiene
    `waba_id`, o Meta devuelve un id que no está en la tabla de
    `meta_timezones`, no adivina: explica qué falta y la zona se elige a mano
    en la configuración. Solo Admin."""
    try:
        body = await request.json()
    except Exception:
        body = {}
    guardar = not (isinstance(body, dict) and body.get("guardar") is False)

    canales = [c for c in await listar_canales_whatsapp(negocio_id=usuario["negocio_id"], solo_activos=True) if c.get("waba_id") and c.get("access_token")]
    if not canales:
        raise HTTPException(status_code=409, detail="Ningún canal activo tiene el ID de la cuenta de WhatsApp Business (waba_id). Cárgalo en Canales o elige la zona a mano.")
    canal = canales[0]
    r = await get_con_reintentos(
        f"https://graph.facebook.com/v21.0/{canal['waba_id']}",
        params={"fields": "timezone_id"}, headers={"Authorization": f"Bearer {canal['access_token']}"},
    )
    if r.status_code != 200:
        logger.error(f"Detección de zona horaria de la cuenta: {_resumen_seguro_error_meta(r)}")
        raise HTTPException(status_code=502, detail="Meta no devolvió la zona horaria de la cuenta (revisa los permisos del token). Elige la zona a mano.")
    timezone_id = (r.json() or {}).get("timezone_id")
    zona = zona_iana_de_meta(timezone_id)
    if zona is None:
        raise HTTPException(status_code=422, detail=f"Meta informó la zona horaria con el id {timezone_id}, que todavía no está en la tabla del sistema. Elige la zona a mano.")
    if guardar:
        await guardar_configuracion_uso_meta(usuario["negocio_id"], {"zona_horaria_mes": zona}, autor=usuario.get("username"))
    return JSONResponse({"ok": True, "zona_horaria": zona, "timezone_id": str(timezone_id), "guardada": guardar})


@router.post("/uso-mensajes/configuracion.json")
async def uso_mensajes_configuracion_json(
    request: Request,
    usuario: dict = Depends(servicio_identidad.requiere_rol("admin")),
    _csrf: None = Depends(verificar_csrf),
):
    """Guarda la configuración del control de uso de mensajes de Meta: cuota
    gratis, zona horaria del mes, tarifas en USD por categoría y uso previo
    estimado por número y mes (ver `guardar_configuracion_uso_meta`). Solo
    Admin; todo o nada."""
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="El cuerpo debe ser JSON.")
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="El cuerpo debe ser un objeto JSON.")
    try:
        guardado = await guardar_configuracion_uso_meta(usuario["negocio_id"], body, autor=usuario.get("username"))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    logger.info("Configuración de uso de mensajes Meta actualizada por %s: %s", usuario.get("username"), guardado["modificadas"])
    return JSONResponse({"ok": True, **guardado})


@router.get("/anuncios.json")
async def anuncios_json(usuario: dict = Depends(servicio_identidad.requiere_rol("admin", "supervisor"))):
    """Anuncios de Meta que trajeron leads, con la campaña a la que pertenecen
    hoy sus conversaciones — incluidos los que ninguna campaña reconoció.
    Solo lectura; asignar requiere Admin (`POST /anuncios/asignar.json`)."""
    anuncios = await listar_anuncios_detectados(usuario["negocio_id"])
    return JSONResponse({
        "anuncios": [_anuncio_a_json(a) for a in anuncios],
        "puede_gestionar": usuario["rol"] == "admin",
    })


@router.get("/anuncios/diagnostico.json")
async def anuncios_diagnostico_json(usuario: dict = Depends(servicio_identidad.requiere_rol("admin"))):
    """Solo lectura, admin. Leads de anuncios que hoy están "Sin campaña", con la
    evidencia que trajeron (¿título/texto presentes?, ¿primer contacto?), para
    saber POR QUÉ un anuncio ya reconocido dejó leads sin campaña."""
    filas = await diagnostico_anuncios_sin_campana(usuario["negocio_id"])
    return JSONResponse({"total": len(filas), "filas": [
        {**f, "evento_creado": iso_utc(f["evento_creado"]), "conversacion_creada": iso_utc(f["conversacion_creada"])}
        for f in filas
    ]})


@router.get("/anuncios/multiples.json")
async def anuncios_multiples_json(usuario: dict = Depends(servicio_identidad.requiere_rol("admin"))):
    """Solo lectura, admin. Conversaciones con anuncios de dos orígenes: de qué anuncio entraron primero,
    en qué campaña están hoy y cuál es la regla de su primer anuncio."""
    return JSONResponse(await diagnostico_atribucion_multiple(usuario["negocio_id"]))


@router.get("/anuncios/multiples/cierre.json")
async def anuncios_multiples_cierre_json(usuario: dict = Depends(servicio_identidad.requiere_rol("admin"))):
    """Solo lectura, admin. Para cada conversación con anuncios de dos orígenes: por qué no se
    cerró definitivamente (y por eso no se abrió una conversación nueva), contra las reglas reales."""
    datos = await auditoria_cierre_conversaciones_multiples(usuario["negocio_id"])
    return JSONResponse({
        **datos,
        "conversaciones": [
            {k: (iso_utc(v) if k in ("primer_contacto", "segundo_anuncio_en", "ultimo_mensaje_cliente", "cerrada_definitivamente_en") else v)
             for k, v in c.items()}
            for c in datos["conversaciones"]
        ],
    })


@router.get("/anuncios/campos-referral.json")
async def anuncios_campos_referral_json(usuario: dict = Depends(servicio_identidad.requiere_rol("admin"))):
    """Solo lectura, admin. Qué campos trae el `referral` de Meta en los avisos reales (media_type, source_type,
    presencia de imagen/video/miniatura, `ref`). Nunca devuelve enlaces, textos ni teléfonos."""
    return JSONResponse(await diagnostico_campos_referral(usuario["negocio_id"]))


@router.get("/anuncios/reingreso.json")
async def anuncios_reingreso_json(usuario: dict = Depends(servicio_identidad.requiere_rol("admin"))):
    """Solo lectura, admin. Modo del reingreso por otro anuncio y lo que habría hecho (sombra) o hizo (activo)
    en los últimos 7 días. Teléfonos enmascarados."""
    negocio_id = usuario["negocio_id"]
    resumen = await resumen_reingreso_anuncio(negocio_id)
    return JSONResponse({
        "modo": await obtener_modo_reingreso_anuncio(negocio_id),
        **resumen,
        "ultimos": [{**u, "creado": iso_utc(u["creado"])} for u in resumen["ultimos"]],
    })


@router.post("/anuncios/reingreso/modo.json")
async def anuncios_reingreso_modo_json(
    request: Request,
    usuario: dict = Depends(servicio_identidad.requiere_rol("admin")),
    _csrf: None = Depends(verificar_csrf),
):
    """Cambia el modo del reingreso por otro anuncio: "apagado", "sombra" o "activo" (solo admin)."""
    cuerpo = await request.json()
    modo = str((cuerpo or {}).get("modo") or "") if isinstance(cuerpo, dict) else ""
    try:
        guardado = await guardar_modo_reingreso_anuncio(usuario["negocio_id"], modo, autor=usuario.get("username"))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return JSONResponse({"ok": True, "modo": guardado})


@router.post("/anuncios/comodines.json")
async def migrar_comodines_json(
    request: Request,
    usuario: dict = Depends(servicio_identidad.requiere_rol("admin")),
    _csrf: None = Depends(verificar_csrf),
):
    """Campañas "comodín" (detectan por una palabra clave y atribuyen anuncios
    que no son suyos) → solo por regla de anuncio. Por defecto SOLO muestra el
    plan; con `{"confirmar": true}` lo aplica. Las conversaciones ya atribuidas
    no cambian."""
    try:
        cuerpo = await request.json()
    except Exception:
        cuerpo = {}
    cuerpo = cuerpo if isinstance(cuerpo, dict) else {}
    excluir = [str(x) for x in (cuerpo.get("excluir") or [])]
    if cuerpo.get("confirmar") is True:
        return JSONResponse({"aplicado": True, **await aplicar_migrar_comodines(
            usuario["negocio_id"], autor=usuario.get("username"), excluir=excluir,
        )})
    return JSONResponse({"aplicado": False, **await plan_migrar_comodines(usuario["negocio_id"], excluir=excluir)})


@router.post("/anuncios/historico.json")
async def corregir_historico_json(
    request: Request,
    usuario: dict = Depends(servicio_identidad.requiere_rol("admin")),
    _csrf: None = Depends(verificar_csrf),
):
    """Corrección de la atribución HISTÓRICA (solo admin). `accion`:
    - "rellenar": conversaciones sin campaña cuyo evento sí resolvió una.
    - "corregir": `source_ids` + `desde_campana_ids` (campañas de las que se corrige) + `campana_id` (null = sin campaña).
    - "recalcular_primer_anuncio": cada conversación con anuncios de dos orígenes vuelve a la campaña de su primer anuncio.
    - "revertir": `auditoria_id` de una corrección anterior.
    Sin `confirmar: true` solo cuenta lo que cambiaría. Nunca toca la evidencia de Meta."""
    cuerpo = await request.json()
    if not isinstance(cuerpo, dict):
        raise HTTPException(status_code=400, detail="El cuerpo debe ser un objeto JSON.")
    negocio_id, autor = usuario["negocio_id"], usuario.get("username")
    aplicar = cuerpo.get("confirmar") is True
    accion = cuerpo.get("accion")
    try:
        if accion == "rellenar":
            return JSONResponse(await historico_rellenar_conversaciones(negocio_id, aplicar, autor=autor))
        if accion == "corregir":
            source_ids = [str(x) for x in (cuerpo.get("source_ids") or [])]
            campana_id = cuerpo.get("campana_id")
            desde = [int(x) for x in (cuerpo.get("desde_campana_ids") or [])]
            return JSONResponse(await historico_corregir_anuncios(
                negocio_id, source_ids, int(campana_id) if campana_id is not None else None, aplicar, autor=autor,
                desde_campana_ids=desde,
            ))
        if accion == "recalcular_primer_anuncio":
            return JSONResponse(await historico_recalcular_primer_anuncio(negocio_id, aplicar, autor=autor))
        if accion == "revertir":
            return JSONResponse({"aplicado": True, **await historico_revertir(
                negocio_id, str(cuerpo.get("auditoria_id") or ""), autor=autor,
            )})
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    raise HTTPException(status_code=400, detail="Acción inválida.")


@router.post("/anuncios/asignar.json")
async def asignar_anuncio_json(
    request: Request,
    usuario: dict = Depends(servicio_identidad.requiere_rol("admin")),
    _csrf: None = Depends(verificar_csrf),
):
    """Asigna todos los leads de un anuncio a una campaña existente
    (`campana_id`) o a una NUEVA que se crea para ese anuncio
    (`nueva_campana: {nombre}`, detectada por el ID del anuncio, así los leads
    futuros del mismo anuncio caen en ella solos)."""
    body = await request.json()
    source_id = (body.get("source_id") or "").strip()
    campana_id = body.get("campana_id")
    nombre_nueva = ((body.get("nueva_campana") or {}).get("nombre") or "").strip()
    if not source_id:
        raise HTTPException(status_code=400, detail="Falta el anuncio.")
    if (campana_id is None) == (not nombre_nueva):
        raise HTTPException(status_code=400, detail="Elige una campaña existente o escribe el nombre de una nueva, no ambas.")

    negocio_id = usuario["negocio_id"]
    if not any(a["source_id"] == source_id for a in await listar_anuncios_detectados(negocio_id)):
        raise HTTPException(status_code=404, detail="Ese anuncio no tiene leads registrados.")

    if nombre_nueva:
        if any(c["nombre"].strip().lower() == nombre_nueva.lower() for c in await listar_campanas(negocio_id)):
            raise HTTPException(status_code=400, detail="Ya existe una campaña con ese nombre.")
        campana = await crear_campana(
            nombre=nombre_nueva, tipo_deteccion="por_anuncio", patron=source_id.lower(), negocio_id=negocio_id,
        )
        campana_id = campana["id"]
    try:
        resumen = await asignar_anuncio_a_campana(negocio_id, source_id, int(campana_id), autor=usuario.get("username"))
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return JSONResponse({"ok": True, "campana_id": campana_id, "asignados": resumen})


@router.get("/campanas", response_class=HTMLResponse)
async def gestionar_campanas(request: Request, usuario: dict = Depends(servicio_identidad.requiere_rol("admin", "supervisor")), creada: int | None = None):
    # Sin rail de conversaciones acá a propósito — esta pantalla gestiona
    # campañas de Meta Ads, no conversaciones; el rail de estados no aporta
    # contexto útil acá (a diferencia de Catálogo/Equipo/Canales/Perfil,
    # donde sí queda).
    # Supervisor entra en modo solo lectura (Bloque Campañas — Supervisor
    # solo lectura): ve la misma tabla, sin ningún form de escritura ni la
    # card "Nueva campaña". Las rutas POST de escritura siguen siendo
    # admin-only del lado del servidor, no solo ocultas acá.
    puede_escribir = usuario["rol"] == "admin"
    campanas = await listar_campanas(usuario["negocio_id"])
    conteos = {c["campana"]: c for c in await contar_opportunities_por_campana(usuario["negocio_id"])}

    banner_html = ""
    if creada:
        campana_nueva = next((c for c in campanas if c["id"] == creada), None)
        if campana_nueva:
            if campana_nueva.get("texto_saludo"):
                link_nueva = servicio_canales.generar_link_whatsapp(campana_nueva["texto_saludo"])
                banner_html = f"""
                <div class="alert alert-success py-2 px-3 mb-3 d-flex align-items-center gap-2">
                    <i class="bi bi-check-circle-fill"></i>
                    <div class="flex-grow-1">
                        <strong>Campaña &ldquo;{html.escape(campana_nueva['nombre'])}&rdquo; creada.</strong> Enlace de WhatsApp listo para compartir:
                        <div class="input-group input-group-sm mt-1" style="max-width:520px">
                            <input type="text" class="form-control form-control-sm" value="{html.escape(link_nueva)}" readonly onclick="this.select()">
                            <button class="btn btn-outline-secondary" type="button"
                                onclick="navigator.clipboard.writeText(this.previousElementSibling.value); this.textContent='Copiado!'">Copiar</button>
                        </div>
                    </div>
                </div>"""
            else:
                banner_html = (
                    f'<div class="alert alert-success py-2 px-3 mb-3"><i class="bi bi-check-circle-fill"></i> '
                    f'Campaña &ldquo;{html.escape(campana_nueva["nombre"])}&rdquo; creada.</div>'
                )

    filas = []
    for c in campanas:
        promo = await servicio_canales.resolver_promo(c, usuario["negocio_id"])
        if promo and promo["fuente"] == "catalogo":
            promo_html = (
                f'<div><span class="badge text-bg-success-subtle text-success-emphasis">Catálogo</span> '
                f'{html.escape(promo["producto"])} — {html.escape(promo["precio"])}</div>'
            )
        elif promo:
            promo_html = (
                f'<div><span class="badge text-bg-secondary-subtle text-secondary-emphasis">Manual</span> '
                f'{html.escape(promo["producto"])} — {html.escape(promo["precio"])}</div>'
            )
        elif c.get("codigo_material"):
            promo_html = f'<div class="text-danger small">Código {html.escape(c["codigo_material"])} no encontrado en el catálogo actual</div>'
        else:
            promo_html = '<div class="text-muted small">Sin promoción específica</div>'

        link_html = ""
        if c.get("texto_saludo"):
            link = servicio_canales.generar_link_whatsapp(c["texto_saludo"])
            link_html = (
                f'<div class="input-group input-group-sm mt-1">'
                f'<input type="text" class="form-control form-control-sm text-muted" value="{html.escape(link)}" readonly '
                f'onclick="this.select()">'
                f'<button class="btn btn-outline-secondary" type="button" '
                f'onclick="navigator.clipboard.writeText(this.previousElementSibling.value); this.textContent=\'Copiado!\'">Copiar</button>'
                f'</div>'
            )

        # Eliminar de verdad (no solo desactivar) solo se permite si la
        # campaña nunca tuvo ningún lead atribuido — si no, se pierde
        # historial de conversión real. El botón ni siquiera se muestra en
        # el otro caso (ver memory.py:eliminar_campana, que igual lo valida
        # de nuevo del lado del servidor).
        boton_eliminar_campana = ""
        if puede_escribir and conteos.get(c["nombre"], {}).get("total", 0) == 0:
            nombre_js = html.escape(c["nombre"]).replace("'", "\\'")
            boton_eliminar_campana = (
                f'<form method="post" action="/dashboard/campanas/{c["id"]}/eliminar" '
                f"onsubmit=\"return confirm('¿Eliminar la campaña {nombre_js}? Esta acción no se puede deshacer.');\">"
                f'{_csrf_campo(request)}'
                f'<button type="submit" class="btn btn-sm btn-outline-danger" title="Eliminar (sin leads asociados)">'
                f'<i class="bi bi-trash"></i></button></form>'
            )

        # Modo manual arranca activo solo si ya tiene promo manual guardada y
        # ningún código de catálogo — igual que en Cierre de venta, los dos
        # bloques son mutuamente excluyentes (inputs disabled en el que no
        # está activo, para que el POST solo mande uno de los dos).
        rowid = str(c["id"])
        manual_activo = bool(c.get("producto_promocional")) and not c.get("codigo_material")

        if puede_escribir:
            promo_celda = f"""{promo_html}
                <form method="post" action="/dashboard/campanas/{c['id']}/editar" class="d-flex flex-column gap-1 mt-2" style="min-width:240px">
                    {_csrf_campo(request)}
                    <div id="campana-producto-catalogo-{rowid}" style="{'display:none' if manual_activo else ''}">
                        <div class="position-relative">
                            <input type="text" id="campana-buscar-producto-{rowid}" class="form-control form-control-sm campana-buscar-producto" placeholder="Busca por marca, tipo o modelo..." autocomplete="off">
                            <div id="campana-resultados-producto-{rowid}" class="list-group position-absolute w-100 shadow-sm campana-resultados-producto" style="z-index:10;display:none;max-height:220px;overflow-y:auto;"></div>
                        </div>
                        <div id="campana-seleccionado-{rowid}" class="small mt-1 campana-seleccionado" style="display:none"></div>
                        <input type="hidden" name="codigo_material" id="campana-codigo-{rowid}" class="campana-codigo-hidden" value="{html.escape(c.get('codigo_material') or '')}" {'disabled' if manual_activo else ''}>
                        <button type="button" class="btn btn-link btn-sm p-0 mt-1 campana-btn-manual" data-rowid="{rowid}">¿No está en la lista? Escribir manualmente</button>
                    </div>
                    <div id="campana-producto-manual-{rowid}" style="{'' if manual_activo else 'display:none;'}">
                        <input type="text" name="producto_promocional" class="form-control form-control-sm mb-1 campana-manual-input" value="{html.escape(c.get('producto_promocional') or '')}" placeholder="Producto manual (sin código)" {'' if manual_activo else 'disabled'}>
                        <input type="text" name="precio_promocional" class="form-control form-control-sm mb-1 campana-manual-input" value="{html.escape(c.get('precio_promocional') or '')}" placeholder="Precio manual (ej: S/ 419.90)" {'' if manual_activo else 'disabled'}>
                        <button type="button" class="btn btn-link btn-sm p-0 campana-btn-catalogo" data-rowid="{rowid}">Volver a buscar en el catálogo</button>
                    </div>
                    <button type="submit" class="btn btn-sm btn-outline-primary align-self-start">Guardar promo</button>
                </form>"""
            estado_celda = f"""<div class="d-flex gap-1">
                    <form method="post" action="/dashboard/campanas/{c['id']}/toggle">
                        {_csrf_campo(request)}
                        <button type="submit" class="btn btn-sm {'btn-success' if c['activa'] else 'btn-outline-secondary'}">
                            {'Activa' if c['activa'] else 'Inactiva'}
                        </button>
                    </form>
                    {boton_eliminar_campana}
                </div>"""
        else:
            # Supervisor — solo lectura: mismo dato, sin ningún form de
            # escritura (Bloque Campañas — Supervisor solo lectura).
            promo_celda = promo_html
            estado_celda = (
                '<span class="badge rounded-pill text-bg-success">Activa</span>' if c['activa']
                else '<span class="badge rounded-pill text-bg-secondary">Inactiva</span>'
            )

        filas.append(f"""<tr>
            <td class="ps-3">
                <div class="fw-semibold">{html.escape(c['nombre'])}</div>
                <div class="text-muted" style="font-size:.75rem">{html.escape(TIPOS_DETECCION_JSON.get(c['tipo_deteccion'], c['tipo_deteccion']))} &middot; patrón: &ldquo;{html.escape(c['patron'])}&rdquo;</div>
                {link_html}
            </td>
            <td class="text-muted">{conteos.get(c['nombre'], {}).get('total', 0)} leads / {conteos.get(c['nombre'], {}).get('vendidos', 0)} vendidos</td>
            <td>{promo_celda}</td>
            <td class="pe-3">{estado_celda}</td>
        </tr>""")

    opciones_tipo = "".join(f'<option value="{v}">{html.escape(t)}</option>' for v, t in TIPOS_DETECCION.items())
    ids_filas_js = "".join(f"inicializarBuscadorCampana('{c['id']}');\n        " for c in campanas) if puede_escribir else ""

    nueva_campana_html = ""
    if puede_escribir:
        nueva_campana_html = f"""
    {_titulo_seccion('bi-plus-circle-fill', 'Nueva campaña')}
    <p class="text-muted small mb-2">
        Escribe el mensaje de saludo tal como debe llegar por SMS/anuncio — se usa para detectar
        la campaña automáticamente y para generar el enlace de WhatsApp listo para compartir (puedes
        acortarlo después en wa.link.com si lo necesitas para SMS).
    </p>
    <div class="card leads-card shadow-sm">
        <div class="barra-acento"></div>
        <div class="card-body">
            <form method="post" action="/dashboard/campanas/nueva" class="row g-2">
                {_csrf_campo(request)}
                <div class="col-md-3">
                    <label class="form-label small text-muted mb-0">Nombre</label>
                    <input type="text" name="nombre" class="form-control form-control-sm" required placeholder="Ej: Meta Terma Marzo">
                </div>
                <div class="col-md-3">
                    <label class="form-label small text-muted mb-0">Cómo se detecta</label>
                    <select name="tipo_deteccion" id="input-tipo-deteccion" class="form-select form-select-sm">{opciones_tipo}</select>
                </div>
                <div class="col-md-6">
                    <label class="form-label small text-muted mb-0">Mensaje de saludo completo (wa.link/SMS) — opcional para anuncios de Meta</label>
                    <textarea name="texto_saludo" id="input-texto-saludo" rows="2" class="form-control form-control-sm" placeholder="Ej: ¡Hola! Vi la promoción de la terma Rheem 8L y quisiera más información sobre cuotas y disponibilidad"></textarea>
                </div>
                <div class="col-md-6">
                    <label class="form-label small text-muted mb-0">Patrón de detección (fragmento distintivo del saludo, o dato del anuncio de Meta)</label>
                    <input type="text" name="patron" id="input-patron" class="form-control form-control-sm" required placeholder="Se autocompleta con el saludo si lo dejas vacío">
                    <div id="patron-advertencia" class="text-danger small mt-1" style="display:none">
                        <i class="bi bi-exclamation-triangle-fill"></i> Este patrón no aparece en el mensaje de saludo — la campaña nunca se detectaría.
                    </div>
                </div>
                <div class="col-md-6">
                    <label class="form-label small text-muted mb-0">Producto de la promoción (catálogo)</label>
                    <div id="campana-producto-catalogo-nueva">
                        <div class="position-relative">
                            <input type="text" id="campana-buscar-producto-nueva" class="form-control form-control-sm campana-buscar-producto" placeholder="Busca por marca, tipo o modelo..." autocomplete="off">
                            <div id="campana-resultados-producto-nueva" class="list-group position-absolute w-100 shadow-sm campana-resultados-producto" style="z-index:10;display:none;max-height:220px;overflow-y:auto;"></div>
                        </div>
                        <div id="campana-seleccionado-nueva" class="small mt-1 campana-seleccionado" style="display:none"></div>
                        <input type="hidden" name="codigo_material" id="campana-codigo-nueva" class="campana-codigo-hidden">
                        <button type="button" class="btn btn-link btn-sm p-0 mt-1 campana-btn-manual" data-rowid="nueva">¿No está en la lista? Escribir manualmente</button>
                    </div>
                    <div id="campana-producto-manual-nueva" style="display:none;">
                        <input type="text" name="producto_promocional" class="form-control form-control-sm mb-1 campana-manual-input" placeholder="Producto manual (sin código)" disabled>
                        <input type="text" name="precio_promocional" class="form-control form-control-sm mb-1 campana-manual-input" placeholder="Precio manual (ej: S/ 419.90)" disabled>
                        <button type="button" class="btn btn-link btn-sm p-0 campana-btn-catalogo" data-rowid="nueva">Volver a buscar en el catálogo</button>
                    </div>
                </div>
                <div class="col-12">
                    <button type="submit" class="btn btn-sm btn-primary">Crear campaña</button>
                </div>
            </form>
        </div>
    </div>
    <script>
    (function() {{
        var saludo = document.getElementById('input-texto-saludo');
        var patron = document.getElementById('input-patron');
        var tipoDeteccion = document.getElementById('input-tipo-deteccion');
        var advertencia = document.getElementById('patron-advertencia');
        var formNueva = saludo.closest('form');

        saludo.addEventListener('input', function() {{
            if (!patron.value.trim()) {{ patron.value = saludo.value.trim().toLowerCase(); }}
            validarPatron();
        }});

        // Avisa ANTES de guardar si el patrón no aparece en el saludo — la
        // campaña quedaría creada pero nunca se detectaría (el bug real que
        // pasó con 4 campañas cargadas a mano). El servidor también lo
        // valida, esto es para que el admin lo note al toque, sin tener que
        // enviar el formulario para enterarse.
        function validarPatron() {{
            var esTextoSaludo = tipoDeteccion.value === 'texto_saludo';
            var hayMismatch = esTextoSaludo && saludo.value.trim() && patron.value.trim() &&
                saludo.value.toLowerCase().indexOf(patron.value.trim().toLowerCase()) === -1;
            advertencia.style.display = hayMismatch ? 'block' : 'none';
            return !hayMismatch;
        }}
        patron.addEventListener('input', validarPatron);
        tipoDeteccion.addEventListener('change', validarPatron);
        formNueva.addEventListener('submit', function(ev) {{
            if (!validarPatron()) {{
                ev.preventDefault();
                patron.focus();
            }}
        }});

        function escapar(texto) {{
            var div = document.createElement('div');
            div.textContent = texto || '';
            return div.innerHTML;
        }}

        function inicializarBuscadorCampana(rowId) {{
            var buscarInput = document.getElementById('campana-buscar-producto-' + rowId);
            var resultadosBox = document.getElementById('campana-resultados-producto-' + rowId);
            var seleccionadoBox = document.getElementById('campana-seleccionado-' + rowId);
            var hiddenCodigo = document.getElementById('campana-codigo-' + rowId);
            var bloqueCatalogo = document.getElementById('campana-producto-catalogo-' + rowId);
            var bloqueManual = document.getElementById('campana-producto-manual-' + rowId);
            if (!buscarInput) return;
            var btnManual = bloqueCatalogo.querySelector('.campana-btn-manual');
            var btnCatalogo = bloqueManual.querySelector('.campana-btn-catalogo');
            var inputsManual = bloqueManual.querySelectorAll('.campana-manual-input');

            function activarModoManual(manual) {{
                bloqueCatalogo.style.display = manual ? 'none' : '';
                bloqueManual.style.display = manual ? '' : 'none';
                hiddenCodigo.disabled = manual;
                inputsManual.forEach(function(i) {{ i.disabled = !manual; }});
            }}
            btnManual.addEventListener('click', function() {{ activarModoManual(true); }});
            btnCatalogo.addEventListener('click', function() {{ activarModoManual(false); }});

            var timeoutBusqueda;
            buscarInput.addEventListener('input', function() {{
                clearTimeout(timeoutBusqueda);
                var q = buscarInput.value.trim();
                if (q.length < 2) {{ resultadosBox.style.display = 'none'; return; }}
                timeoutBusqueda = setTimeout(function() {{
                    fetch('/dashboard/campanas/buscar-producto?q=' + encodeURIComponent(q))
                        .then(function(r) {{ return r.json(); }})
                        .then(function(productos) {{
                            if (!productos.length) {{
                                resultadosBox.innerHTML = '<div class="list-group-item small text-muted">Sin resultados en el catálogo</div>';
                            }} else {{
                                resultadosBox.innerHTML = productos.map(function(p) {{
                                    return '<button type="button" class="list-group-item list-group-item-action small py-2" ' +
                                        'data-codigo="' + escapar(p.codigo) + '" data-descripcion="' + escapar(p.descripcion) + '" ' +
                                        'data-marca="' + escapar(p.marca) + '" data-precio="' + escapar(p.precio) + '">' +
                                        '<strong>' + escapar(p.marca) + '</strong> — ' + escapar(p.descripcion) +
                                        ' <span class="text-muted">S/ ' + escapar(p.precio) + '</span></button>';
                                }}).join('');
                            }}
                            resultadosBox.style.display = 'block';
                        }});
                }}, 250);
            }});

            resultadosBox.addEventListener('click', function(ev) {{
                var btn = ev.target.closest('button[data-codigo]');
                if (!btn) return;
                hiddenCodigo.value = btn.getAttribute('data-codigo');
                seleccionadoBox.innerHTML = '<i class="bi bi-check-circle-fill text-success"></i> ' +
                    escapar(btn.getAttribute('data-marca')) + ' — ' + escapar(btn.getAttribute('data-descripcion')) +
                    ' &middot; S/ ' + escapar(btn.getAttribute('data-precio'));
                seleccionadoBox.style.display = 'block';
                buscarInput.value = '';
                resultadosBox.style.display = 'none';
                resultadosBox.innerHTML = '';
            }});

            document.addEventListener('click', function(ev) {{
                if (ev.target !== buscarInput && !resultadosBox.contains(ev.target)) {{
                    resultadosBox.style.display = 'none';
                }}
            }});
        }}

        inicializarBuscadorCampana('nueva');
        {ids_filas_js}
    }})();
    </script>
    """

    panel = f"""
    {_titulo_seccion('bi-megaphone-fill', 'Gestionar campañas')}
    <p class="text-muted small mb-3">
        Cada campaña se detecta una sola vez, en el primer contacto del lead, y ya no cambia
        durante la conversación. Si eliges un <strong>producto del catálogo</strong>, el precio
        que ofrece Gabi se toma siempre en vivo de la lista de precios vigente — no puede
        desincronizarse. El producto/precio manual es solo un respaldo para promociones que no
        están en la lista de precios.
    </p>
    {banner_html}

    <div class="card leads-card shadow-sm mb-4">
        <div class="barra-acento"></div>
        <div class="table-responsive">
            <table class="table table-hover align-middle mb-0 tabla-ejecutiva">
                <thead>
                    <tr>
                        <th class="ps-3">Campaña / enlace de WhatsApp</th><th>Leads / Ventas</th><th>Promoción vigente</th><th class="pe-3">Estado</th>
                    </tr>
                </thead>
                <tbody>{''.join(filas) or '<tr><td colspan="4" class="text-center text-muted py-4">Aún no hay campañas.</td></tr>'}</tbody>
            </table>
        </div>
    </div>

    {nueva_campana_html}
    """
    cuerpo = f"""<div class="shell d-flex"><div class="main-pane flex-grow-1 p-4">{panel}</div></div>"""
    return _pagina("Gestionar campañas", usuario, cuerpo, request=request)


@router.get("/campanas/buscar-producto")
async def buscar_producto_campana(q: str = "", usuario: dict = Depends(servicio_identidad.requiere_rol("admin"))):
    """Autocompletar del catálogo real para el producto de una campaña — mismo
    buscador que ya usa Gabi por chat y el Cierre de venta, para que la promo
    siempre salga de la lista de precios vigente en vez de tipearla a mano."""
    if len(q.strip()) < 2:
        return JSONResponse([])
    productos = await buscar_productos(q, usuario["negocio_id"], limite=8)
    return JSONResponse([
        {
            "codigo": p.get("CODIGO HANA", ""),
            "descripcion": p.get("DESCRIPCIÓN", ""),
            "marca": p.get("MARCA", ""),
            "proveedor": p.get("PROVEEDOR", ""),
            "precio": p.get("PRECIO", ""),
        }
        for p in productos
    ])


@router.post("/campanas/nueva")
async def crear_campana_nueva(
    nombre: str = Form(...),
    tipo_deteccion: str = Form(...),
    patron: str = Form(...),
    texto_saludo: str = Form(""),
    codigo_material: str = Form(""),
    producto_promocional: str = Form(""),
    precio_promocional: str = Form(""),
    usuario: dict = Depends(servicio_identidad.requiere_rol("admin")),
    _csrf: None = Depends(verificar_csrf),
):
    if tipo_deteccion not in TIPOS_DETECCION:
        raise HTTPException(status_code=400, detail="Tipo de detección inválido")
    codigo_material = codigo_material.strip()
    if codigo_material and await obtener_producto_por_codigo(codigo_material, usuario["negocio_id"]) is None:
        raise HTTPException(status_code=400, detail=f"El código de material '{codigo_material}' no existe en la lista de precios vigente")
    # El patrón se compara contra el mensaje real que manda el cliente (que
    # es texto_saludo, tal cual) — si no aparece ahí, la campaña nunca se va
    # a detectar (bug real que pasó con 4 campañas sembradas a mano, donde
    # patrón y saludo se escribieron por separado y quedaron desalineados).
    if tipo_deteccion == "texto_saludo" and texto_saludo.strip():
        if patron.strip().lower() not in texto_saludo.strip().lower():
            raise HTTPException(
                status_code=400,
                detail="El patrón no aparece dentro del mensaje de saludo — así nunca se detectaría esta campaña. Usa un fragmento que sí esté en el saludo.",
            )
    # Gate 5.2 (corrección H3): negocio_id del admin que crea la campaña —
    # mismo criterio que crear_usuario_nuevo. unidad_id queda sin pasar
    # (None) — las Unidades reales de Cálidda son dato pendiente, no se
    # inventa (Arquitectura Contractual §5, excepción de migración).
    tipo_deteccion, patron = await _preparar_deteccion_meta(tipo_deteccion, patron, usuario["negocio_id"])
    campana_creada = await crear_campana(
        nombre=nombre.strip(), tipo_deteccion=tipo_deteccion, patron=patron.strip().lower(),
        texto_saludo=texto_saludo.strip(), codigo_material=codigo_material,
        producto_promocional=producto_promocional.strip(), precio_promocional=precio_promocional.strip(),
        negocio_id=usuario["negocio_id"],
    )
    if tipo_deteccion == "por_anuncio":
        await guardar_regla_anuncio(usuario["negocio_id"], patron, campana_creada["id"], autor=usuario.get("username"))
    return RedirectResponse(url=f"/dashboard/campanas?creada={campana_creada['id']}", status_code=303)


async def _verificar_ownership_campana(usuario: dict, campana_id: int) -> dict:
    """Gate 5.3 — corrección pequeña: el gate de rol (`admin`) ya existía,
    pero ninguna de las 3 rutas verificaba que la campaña perteneciera al
    mismo Negocio del admin que la edita/apaga/borra (hallazgo del bloque de
    Diseño Técnico). 404 (no 403): no confirma la existencia del recurso a
    quien no tiene acceso — mismo criterio que se aplicará al resto de
    chequeos de ownership nuevos de este Gate."""
    campana = await obtener_campana(campana_id)
    if campana is None or campana.get("negocio_id") != usuario.get("negocio_id"):
        raise HTTPException(status_code=404, detail="Campaña no encontrada")
    return campana


@router.post("/campanas/{campana_id}/editar")
async def editar_promo_campana(
    campana_id: int,
    codigo_material: str = Form(""),
    producto_promocional: str = Form(""),
    precio_promocional: str = Form(""),
    usuario: dict = Depends(servicio_identidad.requiere_rol("admin")),
    _csrf: None = Depends(verificar_csrf),
):
    await _verificar_ownership_campana(usuario, campana_id)
    codigo_material = codigo_material.strip()
    if codigo_material and await obtener_producto_por_codigo(codigo_material, usuario["negocio_id"]) is None:
        raise HTTPException(status_code=400, detail=f"El código de material '{codigo_material}' no existe en la lista de precios vigente")
    await actualizar_campana(
        campana_id,
        codigo_material=codigo_material or None,
        producto_promocional=producto_promocional.strip(),
        precio_promocional=precio_promocional.strip(),
    )
    return RedirectResponse(url="/dashboard/campanas", status_code=303)


@router.post("/campanas/{campana_id}/toggle")
async def toggle_campana(campana_id: int, usuario: dict = Depends(servicio_identidad.requiere_rol("admin")), _csrf: None = Depends(verificar_csrf)):
    actual = await _verificar_ownership_campana(usuario, campana_id)
    await actualizar_campana(campana_id, activa=not actual["activa"])
    return RedirectResponse(url="/dashboard/campanas", status_code=303)


@router.post("/campanas/{campana_id}/eliminar")
async def eliminar_campana_ruta(campana_id: int, usuario: dict = Depends(servicio_identidad.requiere_rol("admin")), _csrf: None = Depends(verificar_csrf)):
    await _verificar_ownership_campana(usuario, campana_id)
    borrada = await eliminar_campana(campana_id, usuario["negocio_id"], eliminado_por=usuario["username"])
    if not borrada:
        raise HTTPException(
            status_code=400,
            detail="Esta campaña ya tiene leads asociados — no se puede eliminar, desactívala en su lugar.",
        )
    return RedirectResponse(url="/dashboard/campanas", status_code=303)


# ── Analítica (Nueva Experiencia — Gate Analítica P0) ───────────────────
#
# Product Patterns Cap. 4: KPI Cards + Zona de siguiente mejor acción +
# Zona de detalle comparativo + Zona de configuración (admin-only, no
# construida en P0 — no hay nada que configurar todavía). Sin restricción
# de rol vía `requiere_rol` (mismo criterio que `inicio_json`): el alcance
# se resuelve adentro del handler porque Admin/Supervisor/Asesor comparten
# el mismo contrato JSON con distintos datos, no rutas separadas.


def _mes_actual_lima() -> tuple[str, str]:
    """Período por defecto de Analítica P0 cuando no llegan `desde`/`hasta`
    por query string: el mes calendario en curso, en Lima (UTC-5 fijo, sin
    horario de verano) — mismo offset que `rango_periodo_utc`, nunca el mes
    calendario en UTC (que a partir de las 19:00 hora Lima ya adelantaría
    un día)."""
    ahora_lima = datetime.utcnow() - timedelta(hours=5)
    inicio_mes = ahora_lima.replace(day=1)
    return inicio_mes.strftime("%Y-%m-%d"), ahora_lima.strftime("%Y-%m-%d")


def _senales_analitica_p0(flujo_periodo: dict, valor_vendido: dict) -> list[dict]:
    """Las dos señales clásicas de Analítica (sin oportunidades y ventas con precio no numérico), con su forma de
    siempre `{tipo, texto}`. Las reglas viven en `agent/analitica_senales.py`; `analitica.json` usa el conjunto completo
    (con qué se vio, por qué ahora, qué hacer y confianza) vía `analitica_senales.evaluar_senales`."""
    reglas = analitica_senales.reglas_sin_oportunidades(flujo_periodo) + analitica_senales.reglas_datos_incompletos(
        valor_vendido, None, 0, None,
    )
    return [{"tipo": r["tipo"], "texto": r["texto"]} for r in reglas][:3]


def _validar_segmento_anuncios(empresa: str, formato: str, producto: str) -> tuple[str | None, str | None, str | None]:
    """Filtros globales por anuncio (empresa, formato, producto): vacíos = sin filtro. Valores fuera de lista, 400."""
    if formato and formato not in FORMATOS_FILTRO_ANUNCIO:
        raise HTTPException(status_code=400, detail="Formato inválido.")
    if producto and producto not in PRODUCTOS_FILTRO_ANUNCIO:
        raise HTTPException(status_code=400, detail="Producto inválido.")
    return (empresa.strip()[:60] or None), (formato or None), (producto or None)


@router.get("/analitica/anuncios.json")
async def analitica_anuncios_json(
    usuario: dict = Depends(_usuario_actual),
    desde: str = "",
    hasta: str = "",
    asesor: str = "",
    empresa: str = "",
    formato: str = "",
    producto: str = "",
):
    """Rendimiento por anuncio (2026-10-19): conversaciones, leads y ventas por GRUPO de anuncios (título + texto +
    formato), con sus anuncios y el enlace "Ver anuncio". Sin asignar campañas. Mismo alcance por rol que
    `analitica.json`: un Asesor solo ve lo suyo. La empresa de cada grupo la pone un admin una vez."""
    vision_total = usuario["rol"] in ROLES_CON_VISION_TOTAL
    asesor_scope = asesor if (vision_total and asesor) else (None if vision_total else usuario["username"])
    if not desde or not hasta:
        desde, hasta = _mes_actual_lima()
    try:
        inicio, fin = rango_periodo_utc(desde, hasta)
    except ValueError:
        raise HTTPException(status_code=400, detail="Fechas inválidas.")
    ids_conv = await ids_conversacion_de_segmento(usuario["negocio_id"], *_validar_segmento_anuncios(empresa, formato, producto))
    datos = await rendimiento_por_anuncio(usuario["negocio_id"], inicio, fin, asesor=asesor_scope, ids_conversacion=ids_conv)
    por_campana = await mem.rendimiento_por_campana(usuario["negocio_id"], inicio, fin, asesor=asesor_scope, ids_conversacion=ids_conv)
    return JSONResponse({
        "periodo": {"desde": desde, "hasta": hasta},
        # Agrupación «Campaña» (2026-10-26, aditivo): clientes, conversaciones y ventas por campaña, con sus anuncios.
        "por_campana": {**por_campana, "campanas": [
            {**c, "anuncios": [{**a, "ultimo": iso_utc(a["ultimo"])} for a in c["anuncios"]]} for c in por_campana["campanas"]
        ]},
        **{**datos, "grupos": [
            {**g, "anuncios": [{**a, "ultimo": iso_utc(a["ultimo"])} for a in g["anuncios"]]} for g in datos["grupos"]
        ]},
        "puede_gestionar": usuario["rol"] == "admin",
    })


@router.get("/analitica/ventas.json")
async def analitica_ventas_json(
    usuario: dict = Depends(_usuario_actual),
    desde: str = "",
    hasta: str = "",
    asesor: str = "",
    empresa: str = "",
    formato: str = "",
    producto: str = "",
):
    """Detalle de las ventas del período — las MISMAS que cuenta "Ventas" en Analítica — con sus productos, valor y
    origen (grupo de anuncios con su empresa y formato, campaña no publicitaria o sin origen). Mismo alcance por rol que
    `analitica.json`: un Asesor solo ve las suyas. Teléfonos enmascarados."""
    vision_total = usuario["rol"] in ROLES_CON_VISION_TOTAL
    asesor_scope = asesor if (vision_total and asesor) else (None if vision_total else usuario["username"])
    if not desde or not hasta:
        desde, hasta = _mes_actual_lima()
    try:
        inicio, fin = rango_periodo_utc(desde, hasta)
    except ValueError:
        raise HTTPException(status_code=400, detail="Fechas inválidas.")
    ids_conv = await ids_conversacion_de_segmento(usuario["negocio_id"], *_validar_segmento_anuncios(empresa, formato, producto))
    datos = await ventas_detalle_periodo(usuario["negocio_id"], inicio, fin, asesor=asesor_scope, ids_conversacion=ids_conv)
    return JSONResponse({
        "periodo": {"desde": desde, "hasta": hasta}, **datos,
        "ventas": [{**v, "fecha_cierre": iso_utc(v["fecha_cierre"])} for v in datos["ventas"]],
    })


@router.get("/analitica/tendencia.json")
async def analitica_tendencia_json(
    usuario: dict = Depends(_usuario_actual),
    desde: str = "",
    hasta: str = "",
    asesor: str = "",
    campana_id: int | None = None,
    empresa: str = "",
    formato: str = "",
    producto: str = "",
):
    """Tendencia del período (2026-10-26): clientes nuevos, casos comerciales, ventas y valor vendido por día, semana o
    mes (según lo largo del período). Cada tramo usa EXACTAMENTE las mismas funciones que el Resumen de `analitica.json`
    sobre su propio rango, y los tramos no se solapan ni dejan huecos: la suma de los tramos es el total del período.
    Mismo alcance por rol y mismos filtros que `analitica.json`. Un tramo `parcial` es uno que el período recorta."""
    vision_total = usuario["rol"] in ROLES_CON_VISION_TOTAL
    asesor_scope = asesor if (vision_total and asesor) else (None if vision_total else usuario["username"])
    if not desde or not hasta:
        desde, hasta = _mes_actual_lima()
    try:
        granularidad, tramos = partir_periodo(desde, hasta)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    ids_conv = await ids_conversacion_de_segmento(usuario["negocio_id"], *_validar_segmento_anuncios(empresa, formato, producto))

    puntos = []
    for t in tramos:
        inicio, fin = rango_periodo_utc(t["desde"], t["hasta"])
        flujo = await contar_flujo_periodo(
            usuario["negocio_id"], inicio, fin, asesor=asesor_scope, campana_id=campana_id, ids_conversacion=ids_conv,
        )
        valor = await resumen_ventas_periodo(
            usuario["negocio_id"], inicio, fin, asesor=asesor_scope, campana_id=campana_id, ids_conversacion=ids_conv,
        )
        puntos.append({
            **t,
            "clientes": flujo["leads"],
            "casos": flujo["oportunidades"],
            "ventas": flujo["ventas"],
            "valor": valor["monto"],
            "ventas_excluidas": valor["ventas_excluidas"],
        })
    return JSONResponse({"periodo": {"desde": desde, "hasta": hasta}, "granularidad": granularidad, "puntos": puntos})


def _hoy_lima() -> str:
    return (datetime.utcnow() - timedelta(hours=5)).strftime("%Y-%m-%d")


@router.get("/analitica/metas.json")
async def analitica_metas_json(usuario: dict = Depends(_usuario_actual), mes: str = "", hasta: str = ""):
    """Metas del mes (2026-10-27): la del negocio y la de cada asesor, con lo logrado, el ritmo y la proyección lineal al
    cierre del mes. El mes es `mes` (AAAA-MM) o, si no llega, el del día `hasta` del período elegido, o el mes en curso.
    Lo logrado son las ventas CERRADAS en el mes completo, con la misma definición que «Ventas», y NO cambia con los
    filtros de empresa, formato o campaña. Alcance por rol: un Asesor solo ve su propia meta (ni la del negocio ni la de
    otros); solo el admin puede editarlas (`puede_editar`)."""
    try:
        mes = analitica_metas.validar_mes(mes) if mes else analitica_metas.mes_de(hasta or _hoy_lima())
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    negocio_id = usuario["negocio_id"]
    vision_total = usuario["rol"] in ROLES_CON_VISION_TOTAL
    desde_mes, hasta_mes = analitica_metas.rango_del_mes(mes)
    inicio, fin = rango_periodo_utc(desde_mes, hasta_mes)
    hoy = _hoy_lima()
    metas = await obtener_metas(negocio_id, mes)

    asesores = await listar_asesores(negocio_id)
    if not vision_total:
        asesores = [a for a in asesores if a["username"] == usuario["username"]]
    usernames = [a["username"] for a in asesores]
    por_asesor = (
        await contar_oportunidades_por_asesor(negocio_id, usernames, inicio, fin) if usernames else {}
    )

    def _con_avance(objetivo: float | None, logrado: int) -> dict:
        base = {"objetivo": objetivo, "logrado": logrado}
        return {**base, **analitica_metas.avance(objetivo, logrado, mes, hoy)} if objetivo else base

    total = None
    if vision_total:
        logrado_total = (await contar_flujo_periodo(negocio_id, inicio, fin))["ventas"]
        total = _con_avance(metas.get(""), logrado_total)
    filas = [
        {"username": a["username"], "nombre": a["nombre"],
         **_con_avance(metas.get(a["username"]), por_asesor.get(a["username"], {}).get("ventas", 0))}
        for a in asesores
    ]
    suma_asesores = sum(metas.get(a["username"], 0) for a in asesores)
    return JSONResponse({
        "mes": mes, "nombre_mes": analitica_metas.nombre_mes(mes), "tipo": "ventas",
        "desde": desde_mes, "hasta": hasta_mes, "hoy": hoy,
        "total": total, "asesores": filas,
        "suma_asesores": suma_asesores if vision_total else None,
        # La meta total es independiente: si no coincide con la suma de las de los asesores, la pantalla lo avisa.
        "suma_distinta": bool(vision_total and total and total["objetivo"] and suma_asesores and suma_asesores != total["objetivo"]),
        "puede_editar": usuario["rol"] == "admin",
    })


@router.post("/analitica/metas.json")
async def analitica_metas_guardar_json(
    request: Request,
    usuario: dict = Depends(servicio_identidad.requiere_rol("admin")),
    _csrf: None = Depends(verificar_csrf),
):
    """Admin. Pone o quita metas de un mes: `{mes, metas: [{asesor, objetivo}]}`; `asesor` vacío es la meta del negocio
    y `objetivo` vacío o 0 la borra. Solo se aceptan asesores del negocio y objetivos enteros entre 0 y 100 000."""
    cuerpo = await request.json()
    if not isinstance(cuerpo, dict) or not isinstance(cuerpo.get("metas"), list):
        raise HTTPException(status_code=400, detail="Se espera {mes, metas: [...]}.")
    try:
        mes = analitica_metas.validar_mes(str(cuerpo.get("mes") or ""))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    validos = {a["username"] for a in await listar_asesores(usuario["negocio_id"])} | {""}
    metas: list[tuple[str, float | None]] = []
    for m in cuerpo["metas"]:
        if not isinstance(m, dict):
            raise HTTPException(status_code=400, detail="Cada meta debe ser un objeto.")
        asesor = str(m.get("asesor") or "")
        if asesor not in validos:
            raise HTTPException(status_code=400, detail=f"Asesor desconocido: {asesor}.")
        crudo = m.get("objetivo")
        if crudo in (None, ""):
            metas.append((asesor, None))
            continue
        if isinstance(crudo, bool) or not isinstance(crudo, (int, float)) or crudo < 0 or crudo > 100_000 or int(crudo) != crudo:
            raise HTTPException(status_code=400, detail="El objetivo debe ser un número entero entre 0 y 100 000.")
        metas.append((asesor, float(crudo)))
    vigentes = await guardar_metas(usuario["negocio_id"], mes, metas, autor=usuario.get("username"))
    return JSONResponse({"ok": True, "mes": mes, "metas": vigentes})


@router.post("/analitica/anuncios/empresa.json")
async def analitica_anuncios_empresa_json(
    request: Request,
    usuario: dict = Depends(servicio_identidad.requiere_rol("admin")),
    _csrf: None = Depends(verificar_csrf),
):
    """Admin. Pone la empresa de UN grupo (`{clave_grupo, empresa}`; empresa vacía la quita) o aplica las sugeridas
    desde los nombres de campaña (`{aplicar_sugeridas: true}`; sin `confirmar: true` solo muestra qué haría)."""
    cuerpo = await request.json()
    if not isinstance(cuerpo, dict):
        raise HTTPException(status_code=400, detail="El cuerpo debe ser un objeto JSON.")
    if cuerpo.get("aplicar_sugeridas") is True:
        return JSONResponse(await aplicar_empresas_sugeridas(
            usuario["negocio_id"], cuerpo.get("confirmar") is True, autor=usuario.get("username"),
        ))
    try:
        empresa = await guardar_empresa_grupo(
            usuario["negocio_id"], str(cuerpo.get("clave_grupo") or ""), str(cuerpo.get("empresa") or ""),
            autor=usuario.get("username"),
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return JSONResponse({"ok": True, "empresa": empresa})


@router.get("/analitica.json")
async def analitica_json(
    usuario: dict = Depends(_usuario_actual),
    desde: str = "",
    hasta: str = "",
    asesor: str = "",
    campana_id: int | None = None,
    red: str = "",
    empresa: str = "",
    formato: str = "",
    producto: str = "",
    sin_senales: bool = False,
):
    """GATE ANALÍTICA P0 — Analítica para la Nueva Experiencia.

    `sin_senales` (2026-10-26) omite las señales (`senales` queda vacío): las usa el período anterior que el frontend pide
    solo para comparar números, donde evaluarlas sería trabajo perdido.

    `empresa`/`formato`/`producto` (2026-10-21) acotan TODA la pantalla (menos «Pulso», que es una foto del momento) a los
    clientes que entraron por anuncios de ese segmento: el grupo de anuncios del primer aviso de cada conversación.

    `red` ("facebook" | "instagram" | "otra") acota SOLO la tabla de campañas
    a las conversaciones de esa red — se deduce del enlace del anuncio de
    Meta, no es un dato oficial de la plataforma. El resto de los bloques no
    cambia.

    Alcance por rol (Product Patterns Cap. 4 §4, aplica a TODA la
    pantalla, no solo al bloque Equipo): un Asesor NUNCA ve indicadores de
    otro asesor — el `asesor` que llega por query string se ignora por
    completo para ese rol y se reemplaza server-side por su propio
    username. Admin/Supervisor sí pueden usarlo para acotar a un asesor
    puntual; no existe una partición más fina de "mi equipo" (ver
    `ROLES_CON_VISION_TOTAL`), así que Supervisor ve el mismo universo de
    asesores que Admin.

    `equipo` está AUSENTE del JSON (no `null`) para rol asesor — nunca
    tiene sentido mostrarle "el equipo" a quien no puede ver a nadie más.
    """
    vision_total = usuario["rol"] in ROLES_CON_VISION_TOTAL
    asesor_scope = asesor if (vision_total and asesor) else (None if vision_total else usuario["username"])
    if red and red not in ("facebook", "instagram", "otra"):
        raise HTTPException(status_code=400, detail="Red inválida.")

    if not desde or not hasta:
        desde, hasta = _mes_actual_lima()
    inicio, fin = rango_periodo_utc(desde, hasta)
    ids_conv = await ids_conversacion_de_segmento(usuario["negocio_id"], *_validar_segmento_anuncios(empresa, formato, producto))

    # "estado_actual" es una FOTO del momento (nunca filtrada por período) —
    # misma fuente que Inicio (Pulso: "leads en curso"/"conversaciones con
    # Gabi"), reutilizada sin cambios.
    datos_bandeja = await _datos_bandeja(usuario, "todos", "", "")
    estado_actual = {
        "leads_en_curso": len(datos_bandeja["leads_derivados"]) + len(datos_bandeja["leads_con_gabi"]),
        "conversaciones_con_gabi": len(datos_bandeja["leads_con_gabi"]),
    }

    flujo_periodo = await contar_flujo_periodo(usuario["negocio_id"], inicio, fin, asesor=asesor_scope, campana_id=campana_id, ids_conversacion=ids_conv)
    embudo = await calcular_embudo_comercial(usuario["negocio_id"], inicio, fin, asesor=asesor_scope, campana_id=campana_id, ids_conversacion=ids_conv)
    distribucion = await distribucion_resultados_periodo(usuario["negocio_id"], inicio, fin, asesor=asesor_scope, campana_id=campana_id, ids_conversacion=ids_conv)
    valor_vendido = await resumen_ventas_periodo(usuario["negocio_id"], inicio, fin, asesor=asesor_scope, campana_id=campana_id, ids_conversacion=ids_conv)
    productos = await productos_vendidos_periodo(usuario["negocio_id"], inicio, fin, asesor=asesor_scope, campana_id=campana_id, ids_conversacion=ids_conv)
    campanas = await contar_opportunities_por_campana(
        usuario["negocio_id"], desde=inicio, hasta=fin, asesor=asesor_scope, red=red or None, ids_conversacion=ids_conv,
    )
    # Complementa `campanas`: mismo universo/filtros, para las conversaciones
    # SIN campana_origen_id — anuncios de Meta pendientes de asignar y
    # conversaciones genuinamente orgánicas. `campana_id` (el filtro de
    # arriba de toda la pantalla) tampoco aplica acá, igual que en
    # `campanas`: la tabla de Campañas siempre muestra el desglose completo.
    atribucion_sin_campana = await listar_atribucion_sin_campana_periodo(
        usuario["negocio_id"], desde=inicio, hasta=fin, asesor=asesor_scope, red=red or None, ids_conversacion=ids_conv,
    )

    # "Brecha del período" / "Brecha oportunidad → venta" (Gate Analítica
    # P0, Decisión Opción C + refinamiento de terminología posterior):
    # NUNCA "oportunidades pendientes actuales" — es una diferencia agregada
    # del período entre dos conjuntos de Opportunity potencialmente
    # distintos (uno filtrado por `creado`, el otro por `fecha_cierre`), así
    # que puede no corresponder 1:1 a ninguna oportunidad puntual todavía
    # abierta. `max(0, ...)` documentado: un cruce de cohortes que diera un
    # resultado negativo nunca se presenta como un hueco negativo.
    brecha = max(0, embudo["oportunidades"] - embudo["ventas"])
    fugas = {
        "sin_cierre": brecha,
        "sin_cierre_descripcion": (
            "Diferencia entre oportunidades creadas y ventas cerradas durante el "
            "período; no representa oportunidades actualmente pendientes."
        ),
        "distribucion_resultados": distribucion,
    }

    respuesta = {
        "periodo": {"desde": desde, "hasta": hasta},
        "estado_actual": estado_actual,
        "flujo_periodo": flujo_periodo,
        "embudo": embudo,
        "fugas": fugas,
        "campanas": campanas,
        "atribucion_sin_campana": atribucion_sin_campana,
        "productos": productos,
        "valor_vendido": valor_vendido,
        "puede_ver_equipo": vision_total,
        "senales": [],
        # Opciones de los filtros por anuncio (aditivo): el selector de empresa se arma con las empresas del negocio.
        "opciones_filtro": {
            "empresas": await listar_empresas_anuncio(usuario["negocio_id"]),
            "formatos": list(FORMATOS_FILTRO_ANUNCIO),
            "productos": list(PRODUCTOS_FILTRO_ANUNCIO),
        },
    }

    if vision_total:
        asesores = await listar_asesores(usuario["negocio_id"])
        usernames = [a["username"] for a in asesores]
        carga = await contar_conversations_activas_por_asesor(usuario["negocio_id"], usernames) if usernames else {}
        resultados_asesor = await contar_oportunidades_por_asesor(
            usuario["negocio_id"], usernames, inicio, fin, campana_id=campana_id, incluir_sin_asesor=True,
            ids_conversacion=ids_conv,
        )
        respuesta["equipo"] = [
            {
                **a,
                "carga": carga.get(a["username"]),
                **resultados_asesor.get(a["username"], {"oportunidades": 0, "ventas": 0, "tasa_cierre": None}),
            }
            for a in asesores
        ]
        # Lo que no tiene un asesor de esta lista (sin asesor, o de un usuario que ya no está) va en su propia fila: así
        # la tabla suma el mismo total que «Ventas» y «Oportunidades».
        sin_asesor = resultados_asesor.get("", {"oportunidades": 0, "ventas": 0, "tasa_cierre": None})
        if sin_asesor["oportunidades"] or sin_asesor["ventas"]:
            respuesta["equipo"].append({
                "username": "", "nombre": "Sin asesor asignado", "nivel": None, "disponible": None, "carga": None,
                **sin_asesor,
            })

    if not sin_senales:
        respuesta["senales"] = await _evaluar_senales_analitica(
            usuario=usuario, desde=desde, hasta=hasta, inicio=inicio, fin=fin, asesor_scope=asesor_scope,
            campana_id=campana_id, ids_conv=ids_conv, vision_total=vision_total, flujo=flujo_periodo, embudo=embudo,
            distribucion=distribucion, valor_vendido=valor_vendido,
            casos_sin_asesor=(resultados_asesor.get("") if vision_total else None),
        )

    return JSONResponse(respuesta)


async def _evaluar_senales_analitica(
    *, usuario: dict, desde: str, hasta: str, inicio, fin, asesor_scope, campana_id, ids_conv, vision_total: bool,
    flujo: dict, embudo: dict, distribucion: list, valor_vendido: dict, casos_sin_asesor: dict | None,
) -> list[dict]:
    """Junta lo que necesitan las reglas de `agent/analitica_senales.py` (grupos de anuncios, origen de las ventas y el
    período anterior) y las evalúa. Alcance por rol: un Asesor solo recibe las señales de datos incompletos y de «sin
    oportunidades» sobre lo suyo, nunca comparativas ni cambios frente al período anterior. Con un filtro de campaña no se
    comparan anuncios (ese filtro no acota los grupos)."""
    negocio_id = usuario["negocio_id"]
    comparativas = vision_total and campana_id is None
    grupos = None
    if comparativas:
        grupos = (await rendimiento_por_anuncio(negocio_id, inicio, fin, asesor=asesor_scope, ids_conversacion=ids_conv))["grupos"]
    ventas_total, sin_origen = 0, None
    if campana_id is None:
        detalle = (await ventas_detalle_periodo(negocio_id, inicio, fin, asesor=asesor_scope, ids_conversacion=ids_conv))["resumen"]
        ventas_total, sin_origen = int(detalle["total"]), int(detalle["por_origen"]["sin_origen"])

    anterior, rotulo = None, ""
    previo = analitica_senales.periodo_anterior(desde, hasta)
    if vision_total and previo and not previo["base_corta"] and previo["dias"] >= analitica_senales.MIN_DIAS_COMPARACION:
        ini_prev, fin_prev = rango_periodo_utc(previo["desde"], previo["hasta"])
        anterior = {
            "flujo": await contar_flujo_periodo(
                negocio_id, ini_prev, fin_prev, asesor=asesor_scope, campana_id=campana_id, ids_conversacion=ids_conv,
            ),
            "distribucion": await distribucion_resultados_periodo(
                negocio_id, ini_prev, fin_prev, asesor=asesor_scope, campana_id=campana_id, ids_conversacion=ids_conv,
            ),
        }
        rotulo = f"{previo['desde'][8:10]}/{previo['desde'][5:7]} – {previo['hasta'][8:10]}/{previo['hasta'][5:7]}"

    return analitica_senales.evaluar_senales(
        flujo=flujo, valor_vendido=valor_vendido, embudo=embudo, distribucion=distribucion, grupos=grupos,
        ventas_total=ventas_total, ventas_sin_origen=sin_origen, casos_sin_asesor=casos_sin_asesor, anterior=anterior,
        rotulo_anterior=rotulo, comparativas=comparativas,
    )


# ── Canales de WhatsApp (admin) ─────────────────────────────────────

def _enmascarar_token(token: str | None) -> str:
    """Nunca se muestra un token completo en la pantalla — solo alcanza para
    reconocer cuál es cuál (ej. al confirmar que se pegó el correcto)."""
    if not token:
        return "—"
    if len(token) <= 8:
        return "••••" + token[-2:]
    return "••••" + token[-6:]


async def _bloque_promover_prompt(request: Request | None = None, negocio_id: str | None = None) -> str:
    """Compara el prompt del archivo (config/prompts.yaml, lo que ya corre en
    los canales de prueba) contra el promovido a producción, y ofrece el
    botón para igualarlos — así no hace falta un deploy para que producción
    reciba un cambio ya probado.

    GATE 4.2 — desde que este Negocio tiene una `IdentidadAgente` migrada,
    `obtener_system_prompt("produccion", negocio_id)` deja de leer
    `Configuracion["system_prompt_produccion"]` (ver `agent/brain.py`): este
    botón, para ese Negocio, dejaría de tener efecto real. Se avisa acá en
    vez de dejarlo silenciosamente inerte — Legacy no se elimina (todavía
    sirve para cualquier Negocio sin identidad migrada), solo se aclara."""
    if negocio_id is not None and await obtener_identidad_agente(negocio_id) is not None:
        return (
            '<div class="alert alert-info py-2 px-3 small mb-0">'
            '<i class="bi bi-info-circle-fill"></i> Este negocio ya tiene una Identidad de Agente '
            'propia (Gate 4.2) — el prompt de producción se administra ahí, este botón ya no '
            'tiene efecto para este negocio.</div>'
        )
    prompt_archivo = cargar_system_prompt()
    prompt_produccion = await obtener_configuracion("system_prompt_produccion", prompt_archivo)
    sincronizados = prompt_archivo == prompt_produccion

    def _vista_previa(texto: str) -> str:
        recorte = texto.strip()[:280]
        return html.escape(recorte + ("…" if len(texto.strip()) > 280 else ""))

    if sincronizados:
        return """
        <div class="alert alert-success py-2 px-3 small mb-0">
            <i class="bi bi-check-circle-fill"></i> El prompt de producción ya está al día con el
            recién desplegado — no hay nada pendiente de promover.
        </div>
        """

    return f"""
    <div class="card leads-card shadow-sm">
        <div class="barra-acento"></div>
        <div class="card-body">
            <div class="alert alert-warning py-2 px-3 small">
                <i class="bi bi-exclamation-triangle-fill"></i> El prompt recién desplegado es distinto
                al que está corriendo en producción — revísalo antes de promoverlo.
            </div>
            <div class="row g-3">
                <div class="col-md-6">
                    <div class="text-muted small mb-1">Recién desplegado (canales de prueba)</div>
                    <div class="border rounded p-2 small text-muted" style="max-height:160px;overflow-y:auto;white-space:pre-wrap">{_vista_previa(prompt_archivo)}</div>
                </div>
                <div class="col-md-6">
                    <div class="text-muted small mb-1">Actualmente en producción</div>
                    <div class="border rounded p-2 small text-muted" style="max-height:160px;overflow-y:auto;white-space:pre-wrap">{_vista_previa(prompt_produccion)}</div>
                </div>
            </div>
            <form method="post" action="/dashboard/canales-whatsapp/promover-prompt" class="mt-3">
                {_csrf_campo(request)}
                <button type="submit" class="btn btn-sm btn-warning">
                    <i class="bi bi-rocket-takeoff-fill"></i> Promover a producción
                </button>
            </form>
        </div>
    </div>
    """


TOKEN_COEXISTENCIA_DIAS = 60
UMBRAL_AVISO_TOKEN_DIAS = 10
UMBRAL_CRITICO_TOKEN_DIAS = 3


def _estado_token_canal(canal: dict) -> str:
    """Aviso de vencimiento del token, solo para canales de Coexistencia
    (Embedded Signup — únicos con `waba_id` y con el token de 60 días
    confirmado por Meta sin excepción; ver project_coexistencia_embedded_signup_requerido
    en memoria). Un canal creado a mano puede tener un token permanente sin
    ninguna caducidad conocida, así que nunca muestra nada acá. Puramente
    informativo — no bloquea ninguna acción ni afecta el funcionamiento del
    canal."""
    if not canal.get("waba_id"):
        return ""
    renovado_en = canal.get("token_renovado_en")
    if renovado_en is None:
        return (
            '<div class="small text-muted mt-1"><i class="bi bi-info-circle"></i> '
            'Sin fecha de renovación registrada — vuelve a guardar el token en '
            '"Editar canal" para empezar a trackear el vencimiento.</div>'
        )
    dias_restantes = (renovado_en + timedelta(days=TOKEN_COEXISTENCIA_DIAS) - datetime.utcnow()).days
    if dias_restantes > UMBRAL_AVISO_TOKEN_DIAS:
        return ""
    if dias_restantes < 0:
        return (
            f'<div class="alert alert-danger py-1 px-2 small mt-1 mb-0">'
            f'<i class="bi bi-exclamation-octagon-fill"></i> Token vencido hace {abs(dias_restantes)} día(s) '
            f'— Coexistencia probablemente dejó de enviar mensajes. Renueva desde "Editar canal".</div>'
        )
    if dias_restantes <= UMBRAL_CRITICO_TOKEN_DIAS:
        return (
            f'<div class="alert alert-danger py-1 px-2 small mt-1 mb-0">'
            f'<i class="bi bi-exclamation-octagon-fill"></i> El token vence en {dias_restantes} día(s) '
            f'— renueva desde "Editar canal" cuanto antes.</div>'
        )
    return (
        f'<div class="alert alert-warning py-1 px-2 small mt-1 mb-0">'
        f'<i class="bi bi-exclamation-triangle-fill"></i> El token vence en {dias_restantes} día(s) '
        f'— renueva desde "Editar canal".</div>'
    )


@router.get("/configuracion.json")
async def configuracion_json(usuario: dict = Depends(servicio_identidad.requiere_rol("admin"))):
    """GATE 4.2 — Decisión 6 de Gate 4.1: estructura base de Configuración
    (Negocio / Gabi / Canales), la misma que valida el informe de este
    Gate contra MPA §7 + MSA Cap. 9. Backend-únicamente a propósito —
    ninguna pantalla de Nueva Experiencia la consume todavía (eso es
    Gate 4.4-4.6, "no avanzar funcionalidades de Gates posteriores"); esta
    ruta prueba que la separación es real y consultable, no construye la UI.

    `gabi` no expone `configuracion_negocio` completo (el texto del
    prompt) — solo confirma que existe y su tamaño, para no comprometerse
    todavía con un contrato de API que Gate 4.4-4.6 puede necesitar
    rediseñar al construir la pantalla real de edición.

    GATE 4.5: esta es la ruta que consume la pantalla real de Configuración
    de Nueva Experiencia — el contrato de arriba se mantiene sin romper
    (mismos campos), y `canales` gana `token_renovado_en` (fecha, no
    secreto — ya es información de "estado de conexión" permitida) para
    poder mostrar el mismo aviso de vencimiento que ya existe en el panel
    Legacy. `access_token`/`app_secret`/`page_access_token`/`phone_number_id`/
    `waba_id` siguen sin exponerse acá."""
    negocio = await obtener_negocio(usuario["negocio_id"])
    identidad = await obtener_identidad_agente(usuario["negocio_id"])
    horarios = await listar_horarios_atencion(usuario["negocio_id"])
    canales = await listar_canales_whatsapp(negocio_id=usuario["negocio_id"])
    tea, igv = await obtener_tasas_financiamiento(usuario["negocio_id"])

    negocio_json = None
    if negocio:
        negocio_json = {**negocio, "creado": iso_utc(negocio["creado"]), "actualizado": iso_utc(negocio["actualizado"])}

    # Nueva Experiencia — botón "Conectar WhatsApp" (Gate Canales, 2026-09-14):
    # mismos 2 valores que ya vive en texto plano en el HTML del panel Legacy
    # (`gestionar_canales_whatsapp`, más abajo) — no son secretos (Meta los
    # trata como IDs públicos de la app/configuración, nunca como
    # credenciales), así que exponerlos acá no cambia la superficie de riesgo
    # real. `None` si el servidor todavía no los tiene cargados — la Nueva
    # Experiencia oculta el botón en ese caso, igual que Legacy.
    app_id = os.getenv("META_APP_ID", "")
    config_id = os.getenv("META_EMBEDDED_SIGNUP_CONFIG_ID", "")

    return JSONResponse({
        "negocio": negocio_json,
        "meta": {"app_id": app_id, "config_id": config_id} if app_id and config_id else None,
        "gabi": {
            "nombre": identidad["nombre"], "tono": identidad["tono"],
            "prompt_configurado": True, "prompt_longitud": len(identidad["configuracion_negocio"]),
        } if identidad else None,
        "horarios": horarios,
        "canales": [
            {
                "id": c["id"], "nombre": c["nombre"], "modo": c.get("modo", "produccion"), "activo": c["activo"],
                "token_renovado_en": iso_utc(c["token_renovado_en"]) if c.get("token_renovado_en") else None,
            }
            for c in canales
        ],
        # Gate 2026-09-23 — tasa de financiamiento (TEA) e IGV que se usan
        # para calcular EN VIVO las cuotas que Gabi menciona y las que se
        # registran al cerrar una venta (ver agent/tools.py::
        # calcular_cuota_producto). "La tasa puede variar en el tiempo"
        # (pedido explícito) — por eso es editable acá, nunca hardcodeada.
        "financiamiento": {"tea": tea, "igv": igv, "cuotas_min": CUOTAS_MIN, "cuotas_max": CUOTAS_MAX},
    })


@router.get("/canales-whatsapp/estado.json")
async def canales_whatsapp_estado_json(
    refrescar: bool = False,
    usuario: dict = Depends(servicio_identidad.requiere_rol("admin")),
):
    """Estado de cada número de WhatsApp del Negocio para el panel Canales (mejora #2, 2026-11-05): número visible,
    estado y calidad según Meta (consulta en vivo con el token del canal, guardada 60 s; `?refrescar=true` la salta),
    unidad de negocio y último mensaje recibido de un cliente. Solo Admin; nunca devuelve credenciales."""
    from agent import estado_canales
    try:
        canales = await estado_canales.estado(usuario["negocio_id"], iso_utc, usar_cache=not refrescar)
    except Exception:
        logger.exception("Canales: no se pudo calcular el estado")
        raise HTTPException(status_code=500, detail="No se pudo calcular el estado de los canales.")
    return JSONResponse({"canales": canales})


# ── Configuración — escritura (Gate 4.5) ────────────────────────────────
#
# Mismo criterio que Productos: body JSON (no form-encoded), body de la API
# pensada para el BFF de Nueva Experiencia. admin-únicamente + CSRF, mismo
# patrón que las rutas de Canales de arriba. negocio_id SIEMPRE resuelto de
# la sesión (usuario["negocio_id"]) — nunca aceptado del body.


@router.post("/configuracion/negocio")
async def actualizar_negocio_ruta(
    request: Request,
    usuario: dict = Depends(servicio_identidad.requiere_rol("admin")),
    _csrf: None = Depends(verificar_csrf),
):
    """Edita el nombre del Negocio — único campo editable (ver
    actualizar_negocio en memory.py para por qué codigo/activo no lo son)."""
    body = await request.json()
    nombre = (body.get("nombre") or "").strip()
    if not nombre:
        raise HTTPException(status_code=400, detail="El nombre es obligatorio")
    if len(nombre) > 150:
        raise HTTPException(status_code=400, detail="El nombre no puede superar los 150 caracteres")
    negocio = await actualizar_negocio(usuario["negocio_id"], nombre)
    if negocio is None:
        raise HTTPException(status_code=404, detail="Negocio no encontrado")
    return JSONResponse({
        "ok": True,
        "negocio": {**negocio, "creado": iso_utc(negocio["creado"]), "actualizado": iso_utc(negocio["actualizado"])},
    })


@router.post("/configuracion/gabi")
async def actualizar_gabi_ruta(
    request: Request,
    usuario: dict = Depends(servicio_identidad.requiere_rol("admin")),
    _csrf: None = Depends(verificar_csrf),
):
    """Edita SOLO nombre/tono de la identidad de Gabi — nunca
    `configuracion_negocio` (el texto del prompt) ni `usa_patron_estructural`
    (mecanismo interno, no expuesto como opción de producto, Gate 4.5 §10).
    Lee la identidad actual y reenvía su `configuracion_negocio` intacto a
    `crear_o_actualizar_identidad_agente` — esa función hace upsert
    completo, así que omitir este paso borraría el prompt real sin
    querer."""
    body = await request.json()
    nombre = (body.get("nombre") or "").strip()
    tono = (body.get("tono") or "").strip()
    if not nombre or not tono:
        raise HTTPException(status_code=400, detail="Nombre y tono son obligatorios")
    if len(nombre) > 50:
        raise HTTPException(status_code=400, detail="El nombre no puede superar los 50 caracteres")
    if len(tono) > 200:
        raise HTTPException(status_code=400, detail="El tono no puede superar los 200 caracteres")
    identidad_actual = await obtener_identidad_agente(usuario["negocio_id"])
    if identidad_actual is None:
        raise HTTPException(status_code=404, detail="Este negocio todavía no tiene una identidad de Gabi configurada")
    identidad = await crear_o_actualizar_identidad_agente(
        usuario["negocio_id"], nombre, tono, identidad_actual["configuracion_negocio"],
    )
    return JSONResponse({
        "ok": True,
        "gabi": {
            "nombre": identidad["nombre"], "tono": identidad["tono"],
            "prompt_configurado": True, "prompt_longitud": len(identidad["configuracion_negocio"]),
        },
    })


@router.post("/configuracion/financiamiento")
async def actualizar_financiamiento_ruta(
    request: Request,
    usuario: dict = Depends(servicio_identidad.requiere_rol("admin")),
    _csrf: None = Depends(verificar_csrf),
):
    """Edita la TEA/IGV que usa este Negocio para calcular cuotas en vivo
    (Gate 2026-09-23) — "la tasa puede variar en el tiempo" (pedido
    explícito), así que queda editable acá en vez de hardcodeada. Ambas se
    guardan como fracción (0.40, no 40) — mismo criterio que el resto del
    catálogo financiero del sistema."""
    body = await request.json()
    try:
        tea = float(body.get("tea"))
        igv = float(body.get("igv"))
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="TEA e IGV deben ser números")
    if not (0 <= tea <= 5):
        raise HTTPException(status_code=400, detail="La TEA debe ser un valor entre 0 y 5 (ej. 0.40 = 40%)")
    if not (0 <= igv <= 1):
        raise HTTPException(status_code=400, detail="El IGV debe ser un valor entre 0 y 1 (ej. 0.18 = 18%)")
    await guardar_configuracion(CLAVE_CONFIG_TEA, str(tea), negocio_id=usuario["negocio_id"])
    await guardar_configuracion(CLAVE_CONFIG_IGV, str(igv), negocio_id=usuario["negocio_id"])
    return JSONResponse({
        "ok": True,
        "financiamiento": {"tea": tea, "igv": igv, "cuotas_min": CUOTAS_MIN, "cuotas_max": CUOTAS_MAX},
    })


async def _estado_configuracion_metricas(negocio_id: str) -> dict:
    """Política vigente de la métrica del embudo + cuántas consultas no comerciales hubo en los últimos 30 días
    (contexto para decidir; se calcula aunque la exclusión esté apagada). El contexto es opcional: si falla, la
    configuración se sigue pudiendo ver y cambiar."""
    estado = await mem.obtener_configuracion_metricas(negocio_id)
    try:
        estado["consultas_atc_ultimos_30_dias"] = await mem.contar_consultas_atc_recientes(negocio_id, 30)
    except Exception:
        logger.warning("No se pudo contar las consultas ATC recientes para la configuración de métricas", exc_info=True)
        estado["consultas_atc_ultimos_30_dias"] = None
    return estado


@router.get("/configuracion/metricas.json")
async def configuracion_metricas_json(usuario: dict = Depends(servicio_identidad.requiere_rol("admin"))):
    """Política de la métrica del embudo comercial (decisión del dueño, 2026-10-08): si las consultas de atención
    al cliente (`consulta_atc`) cuentan en el denominador de la tasa de cierre. Contrato:
    `{excluir_consulta_atc: bool, excluir_desde: "AAAA-MM-DD"|null, consultas_atc_ultimos_30_dias:
    {dias, consultas, oportunidades, porcentaje}|null}`. Del negocio de la sesión; solo lectura; solo Admin."""
    return JSONResponse(await _estado_configuracion_metricas(usuario["negocio_id"]))


@router.post("/configuracion/metricas.json")
async def actualizar_configuracion_metricas_json(
    request: Request,
    usuario: dict = Depends(servicio_identidad.requiere_rol("admin")),
    _csrf: None = Depends(verificar_csrf),
):
    """Guarda la política de la métrica. Cuerpo: `{excluir_consulta_atc: bool, excluir_desde?: "AAAA-MM-DD"|null}`
    (la fecha es día de Lima; `null`/vacía = todo el período; si no viene, se deja la que había). No borra ni
    reclasifica datos: solo cambia cómo se calcula la tasa. Queda en el historial de cambios (quién, cuándo,
    antes y después). Del negocio de la sesión, nunca del cuerpo; solo Admin; todo o nada."""
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="El cuerpo debe ser JSON.")
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="El cuerpo debe ser un objeto JSON.")
    try:
        guardado = await mem.guardar_configuracion_metricas(
            usuario["negocio_id"], body.get("excluir_consulta_atc"),
            body["excluir_desde"] if "excluir_desde" in body else mem.SIN_CAMBIO_METRICAS,
            autor=usuario.get("username"),
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    logger.info("Métrica del embudo actualizada por %s: %s", usuario.get("username"), guardado["modificadas"])
    return JSONResponse({"ok": True, "modificadas": guardado["modificadas"], **await _estado_configuracion_metricas(usuario["negocio_id"])})


@router.get("/configuracion/derivacion-automatica.json")
async def configuracion_derivacion_automatica_json(usuario: dict = Depends(servicio_identidad.requiere_rol("admin"))):
    """Derivación automática (decisión del dueño, 2026-10-11): los casos SIN posibilidad de venta (recibo, número de
    cliente, pago o deuda y emergencia de gas) se derivan al canal correcto y se tipifican y cierran solos, sin asesor y
    sin tokens. Devuelve la configuración del negocio de la sesión con el estado EFECTIVO de cada categoría (p. ej. «activo»
    sin línea degrada a sombra), los textos y las líneas, el resultado de cierre y sus opciones, las variables permitidas,
    lo que nunca se cierra y la actividad de los últimos 30 días (solo conteos; `null` si no pudo calcularse).
    Solo lectura; solo Admin."""
    return JSONResponse(await derivacion_automatica.estado_configuracion(usuario["negocio_id"]))


@router.post("/configuracion/derivacion-automatica.json")
async def actualizar_configuracion_derivacion_automatica_json(
    request: Request,
    usuario: dict = Depends(servicio_identidad.requiere_rol("admin")),
    _csrf: None = Depends(verificar_csrf),
):
    """Guarda cualquier subconjunto de: `modo` y `emergencia_modo` (apagado|sombra|activo; interruptores distintos),
    `categorias` (lista de las incluidas en el modo general), `lineas` ({atencion?, emergencia?, ventas?}),
    `nombre_negocio`, `texto_general`, `textos_categoria` ({categoría: texto}), `texto_emergencia` (un texto vacío vuelve
    al original) y `resultado` (con que se tipifica y cierra; default consulta_atc). Todo o nada, con las mismas validaciones
    que scripts/configurar_triaje_atc.py. Solo se escribe lo que cambia: guardar sin cambiar nada no activa nada. Queda en
    el Historial de configuración (quién, cuándo, antes y después). Del negocio de la sesión, nunca del cuerpo; solo Admin."""
    cuerpo = await _cuerpo_objeto_json(request)
    try:
        resultado = await derivacion_automatica.guardar_cambios(usuario["negocio_id"], usuario.get("username"), cuerpo)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    logger.info("Derivación automática actualizada por %s: %s", usuario.get("username"), resultado["modificadas"])
    return JSONResponse({"ok": True, **resultado})


def _validar_hora(valor: str, etiqueta: str) -> None:
    try:
        datetime.strptime(valor, "%H:%M")
    except ValueError:
        raise HTTPException(status_code=400, detail=f"{etiqueta} debe tener formato HH:MM (ej. 08:00)")


@router.post("/configuracion/horario")
async def guardar_horario_ruta(
    request: Request,
    usuario: dict = Depends(servicio_identidad.requiere_rol("admin")),
    _csrf: None = Depends(verificar_csrf),
):
    """Guarda el horario de UN día — el frontend llama esta ruta una vez por
    día editado, mismo contrato que `guardar_horario_atencion`. Validación
    de formato/rango server-side (Gate 4.5 §8): nunca confiar solo en el
    input type=time del navegador."""
    body = await request.json()
    dia_semana = body.get("dia_semana")
    if not isinstance(dia_semana, int) or not (0 <= dia_semana <= 6):
        raise HTTPException(status_code=400, detail="dia_semana debe ser un entero entre 0 (lunes) y 6 (domingo)")
    habilitado = bool(body.get("habilitado"))
    hora_apertura = (body.get("hora_apertura") or "").strip() or None
    hora_cierre = (body.get("hora_cierre") or "").strip() or None

    if habilitado:
        if not hora_apertura or not hora_cierre:
            raise HTTPException(status_code=400, detail="Selecciona hora de apertura y de cierre para un día habilitado")
        _validar_hora(hora_apertura, "La hora de apertura")
        _validar_hora(hora_cierre, "La hora de cierre")
        if hora_apertura >= hora_cierre:
            raise HTTPException(status_code=400, detail="La hora de apertura debe ser anterior a la hora de cierre")

    horario = await guardar_horario_atencion(usuario["negocio_id"], dia_semana, habilitado, hora_apertura, hora_cierre)
    return JSONResponse({"ok": True, "horario": horario})


# ── Calendario de negocio: días especiales (2026-10-12, Fase 1) ──────────────────────────────────────────
#
# Feriados, días no laborables, puentes, atención especial y cierres propios del negocio de la sesión. Contrato JSON
# completo (request/response/errores/auditoría) en docs/contrato_calendario_negocio.md. Lectura y escritura: admin y
# supervisor. Todo del negocio de la sesión, nunca del cuerpo. El GET de horario existente no cambia.

_ETIQUETAS_TIPO_DIA_ESPECIAL = {
    cal_negocio.TIPO_FERIADO: "Feriado",
    cal_negocio.TIPO_NO_LABORABLE: "Día no laborable",
    cal_negocio.TIPO_PUENTE: "Puente",
    cal_negocio.TIPO_ATENCION_ESPECIAL: "Atención especial",
    cal_negocio.TIPO_CIERRE_PROPIO: "Cierre propio",
}
_OPERACIONES_DIAS_ESPECIALES = ("guardar", "marcar_manana_no_laborable", "cargar_feriados_peru")
_MAX_DIAS_CONSULTA_CALENDARIO = 800


def _dia_especial_a_json(d: dict, hoy) -> dict:
    from agent import calendario_peru
    fecha = d["fecha"]
    verificado = None
    if d.get("origen") == mem.ORIGEN_DIA_PRECARGADO_PE:
        precargado = calendario_peru.buscar_feriado(fecha)
        verificado = precargado["verificado"] if precargado else None
    dias_atras = (hoy - fecha).days
    return {
        "id": d["id"], "fecha": fecha.isoformat(), "dia_semana": cal_negocio.DIAS_ES[fecha.weekday()],
        "tipo": d["tipo"], "nombre": d["nombre"], "atiende": d["atiende"],
        "hora_apertura": d["hora_apertura"], "hora_cierre": d["hora_cierre"],
        "origen": d["origen"], "fuente_url": d["fuente_url"], "verificado": verificado,
        "pasado": dias_atras > 0,
        "requiere_motivo": 0 < dias_atras <= mem.DIAS_EDICION_RETROACTIVA,
        "editable": dias_atras <= mem.DIAS_EDICION_RETROACTIVA,
        "creado": iso_utc(d["creado"]), "creado_por": d["creado_por"], "actualizado": iso_utc(d["actualizado"]),
    }


def _fecha_param_calendario(valor: str | None, nombre: str):
    if not valor:
        return None
    try:
        return _date.fromisoformat(valor.strip())
    except ValueError:
        raise HTTPException(status_code=400, detail=f"`{nombre}` debe tener el formato AAAA-MM-DD.")


def _exigir_guardas_calendario(usuario: dict, operacion: str, cuerpo: dict, hoy) -> None:
    """Guardas de negocio del calendario para quien NO es admin (hoy, el supervisor; decisiones D4 y D5 del dueño,
    2026-10-12): 403 si intenta (1) cambiar o quitar un día PASADO (la regla de hasta 7 días con motivo queda solo para
    el admin) o (2) cargar los feriados de un año con lista NO verificada (hoy 2027). El admin conserva todo. Un valor
    mal escrito no se decide acá: sigue su camino y recibe el 400 de siempre."""
    if usuario.get("rol") == "admin":
        return
    if operacion == "cargar_feriados_peru":
        from agent import calendario_peru
        anio = cuerpo.get("anio")
        if (
            isinstance(anio, int) and not isinstance(anio, bool) and anio in calendario_peru.ANIOS_DISPONIBLES
            and not calendario_peru.VERIFICADO_POR_ANIO.get(anio, False)
        ):
            raise HTTPException(
                status_code=403,
                detail=f"Los feriados de {anio} todavía no están verificados con la fuente oficial. Solo un administrador puede cargarlos.",
            )
    elif operacion in ("guardar", "quitar"):
        try:
            fecha = mem._fecha_dia_especial(cuerpo.get("fecha"))
        except ValueError:
            return
        if fecha < hoy:
            raise HTTPException(status_code=403, detail="Solo un administrador puede cambiar o quitar un día que ya pasó.")


def _entero_positivo_config(valor: str | None, por_defecto: int) -> int:
    try:
        n = int(str(valor).strip())
    except (TypeError, ValueError):
        return por_defecto
    return n if n >= 1 else por_defecto


async def _exigir_limite_escrituras_calendario(usuario: dict) -> None:
    """Límite de frecuencia de las escrituras al calendario (decisión D7): máximo `calendario_max_escrituras_hora`
    (por defecto 20) por usuario por hora, con ventana deslizante. Se cuenta contra la auditoría en la base (no en
    memoria del proceso), así vale igual con varias réplicas. El admin también cuenta, con un tope propio más alto
    (`calendario_max_escrituras_hora_admin`, por defecto 100: cargar un año de puentes y cierres a mano no debe
    toparse). Excedido → 429 con `Retry-After`."""
    negocio_id = usuario["negocio_id"]
    if usuario.get("rol") == "admin":
        clave, por_defecto = mem.CLAVE_CALENDARIO_MAX_ESCRITURAS_HORA_ADMIN, mem.CALENDARIO_MAX_ESCRITURAS_HORA_ADMIN_POR_DEFECTO
    else:
        clave, por_defecto = mem.CLAVE_CALENDARIO_MAX_ESCRITURAS_HORA, mem.CALENDARIO_MAX_ESCRITURAS_HORA_POR_DEFECTO
    maximo = _entero_positivo_config(await obtener_configuracion(clave, str(por_defecto), negocio_id=negocio_id), por_defecto)
    uso = await mem.contar_escrituras_calendario(negocio_id, usuario.get("username"))
    if uso["cantidad"] < maximo:
        return
    segundos = max(1, int((uso["libera_en"] - datetime.utcnow()).total_seconds())) if uso["libera_en"] else 60
    minutos = max(1, -(-segundos // 60))
    raise HTTPException(
        status_code=429,
        detail=(
            f"Hiciste {maximo} cambios al calendario en la última hora, que es el máximo permitido. "
            f"Podrás hacer otro en {minutos} min."
        ),
        headers={"Retry-After": str(segundos)},
    )


async def _estado_calendario(usuario: dict, desde, hasta) -> dict:
    from agent import calendario_peru
    negocio_id = usuario["negocio_id"]
    hoy = mem.hoy_en_lima()
    ahora = datetime.utcnow()
    dias = await mem.listar_dias_especiales(negocio_id, desde, hasta)
    cal = await mem.obtener_calendario_negocio(negocio_id)
    est = cal_negocio.estado(ahora, cal)
    cobertura = await mem.resumen_cobertura_calendario(negocio_id, hoy)
    todos_feriados = {
        d["fecha"] for d in await mem.listar_dias_especiales(negocio_id, _date(hoy.year - 1, 1, 1), _date(hoy.year + 3, 12, 31))
        if d["tipo"] == cal_negocio.TIPO_FERIADO
    }
    return {
        "hoy": hoy.isoformat(), "desde": desde.isoformat(), "hasta": hasta.isoformat(),
        "dias": [_dia_especial_a_json(d, hoy) for d in dias],
        "estado_actual": {
            "abierto": est["abierto"], "motivo": est["motivo"], "nombre": est["nombre"],
            "proxima_apertura": iso_utc(est["proxima_apertura"]) if est["proxima_apertura"] else None,
            "proxima_apertura_texto": cal_negocio.describir_proxima_apertura(est["proxima_apertura"], ahora),
        },
        "cobertura": {
            "ultima_fecha_cargada": cobertura["ultima_fecha_cargada"].isoformat() if cobertura["ultima_fecha_cargada"] else None,
            "dias_restantes": cobertura["dias_restantes"], "aviso": cobertura["aviso"], "mensaje": cobertura["mensaje"],
        },
        "anios_precargables": [
            {
                "anio": anio, "verificado": calendario_peru.VERIFICADO_POR_ANIO.get(anio, False),
                "nota": calendario_peru.nota_del_anio(anio), "total": len(calendario_peru.feriados_de(anio)),
                "cargados": sum(1 for f in calendario_peru.feriados_de(anio) if f["fecha"] in todos_feriados),
            }
            for anio in calendario_peru.ANIOS_DISPONIBLES
        ],
        "tipos": [
            {"valor": t, "etiqueta": _ETIQUETAS_TIPO_DIA_ESPECIAL[t], "atiende_por_defecto": mem.ATIENDE_POR_DEFECTO[t]}
            for t in cal_negocio.TIPOS_DIA_ESPECIAL
        ],
        "dias_edicion_retroactiva": mem.DIAS_EDICION_RETROACTIVA,
    }


@router.get("/configuracion/dias-especiales.json")
async def dias_especiales_json(
    desde: str | None = None, hasta: str | None = None,
    usuario: dict = Depends(servicio_identidad.requiere_rol(*ROLES_CON_VISION_TOTAL)),
):
    """Días especiales del negocio de la sesión entre `desde` y `hasta` (AAAA-MM-DD; por defecto desde hace 7 días hasta
    dentro de un año), más el estado actual del negocio (abierto/cerrado y por qué), la cobertura del calendario
    (`aviso` si faltan menos de 60 días de feriados cargados) y los años que se pueden precargar. Admin y supervisor."""
    hoy = mem.hoy_en_lima()
    f_desde = _fecha_param_calendario(desde, "desde") or (hoy - timedelta(days=mem.DIAS_EDICION_RETROACTIVA))
    f_hasta = _fecha_param_calendario(hasta, "hasta") or (hoy + timedelta(days=365))
    if f_hasta < f_desde:
        raise HTTPException(status_code=400, detail="`hasta` no puede ser anterior a `desde`.")
    if (f_hasta - f_desde).days > _MAX_DIAS_CONSULTA_CALENDARIO:
        raise HTTPException(status_code=400, detail=f"El rango no puede pasar de {_MAX_DIAS_CONSULTA_CALENDARIO} días.")
    return JSONResponse(await _estado_calendario(usuario, f_desde, f_hasta))


@router.post("/configuracion/dias-especiales.json")
async def dias_especiales_guardar_json(
    request: Request,
    usuario: dict = Depends(servicio_identidad.requiere_rol(*ROLES_CON_VISION_TOTAL)),
    _csrf: None = Depends(verificar_csrf),
):
    """Tres operaciones según `operacion` (por defecto `guardar`):
      · `guardar`: `{fecha, tipo, nombre, atiende?, hora_apertura?, hora_cierre?, motivo?}` — crea el día especial de esa
        fecha o cambia el que ya existe (una sola fila viva por fecha). Respuesta `resultado`: creado | modificado |
        sin_cambios.
      · `marcar_manana_no_laborable`: `{nombre?}` — mañana (día de Lima) queda cerrado; rige en ≤ 60 s.
      · `cargar_feriados_peru`: `{anio}` — siembra los feriados nacionales (idempotente; restaura los que se quitaron).
    Un día pasado solo se puede tocar hasta 7 días atrás y con `motivo`. Todo queda en el historial de cambios (quién,
    cuándo, antes y después, motivo, rol del autor). Del negocio de la sesión, nunca del cuerpo. Admin y supervisor.
    Solo el admin puede tocar un día pasado o cargar los feriados de un año no verificado (el supervisor recibe 403).
    Máximo `calendario_max_escrituras_hora` escrituras por usuario por hora (429)."""
    cuerpo = await _cuerpo_objeto_json(request)
    operacion = cuerpo.get("operacion", "guardar")
    if operacion not in _OPERACIONES_DIAS_ESPECIALES:
        raise HTTPException(status_code=400, detail=f"`operacion` debe ser una de: {', '.join(_OPERACIONES_DIAS_ESPECIALES)}.")
    negocio_id, autor, autor_rol = usuario["negocio_id"], usuario.get("username"), usuario.get("rol")
    hoy = mem.hoy_en_lima()
    _exigir_guardas_calendario(usuario, operacion, cuerpo, hoy)
    await _exigir_limite_escrituras_calendario(usuario)
    try:
        if operacion == "cargar_feriados_peru":
            anio = cuerpo.get("anio")
            if not isinstance(anio, int) or isinstance(anio, bool):
                raise ValueError("`anio` debe ser un número entero (por ejemplo 2026).")
            r = await mem.sembrar_calendario(negocio_id, anio, autor=autor, restaurar_eliminados=True, autor_rol=autor_rol)
            logger.info("Calendario: %s cargó los feriados de Perú %s (%d nuevos)", autor, anio, len(r["insertados"]))
            return JSONResponse({
                "ok": True, "operacion": operacion, "anio": anio, "verificado": r["verificado"], "nota": r["nota"],
                "insertados": [d.isoformat() for d in r["insertados"]],
                "ya_existian": [d.isoformat() for d in r["ya_existian"]],
            })
        if operacion == "marcar_manana_no_laborable":
            nombre = cuerpo.get("nombre")
            if nombre is not None and not isinstance(nombre, str):
                raise ValueError("`nombre` debe ser texto.")
            r = await mem.marcar_manana_no_laborable(negocio_id, autor=autor, nombre=nombre, hoy=hoy, autor_rol=autor_rol)
        else:
            r = await mem.guardar_dia_especial(
                negocio_id, cuerpo.get("fecha"), cuerpo.get("tipo"), cuerpo.get("nombre"), cuerpo.get("atiende"),
                cuerpo.get("hora_apertura"), cuerpo.get("hora_cierre"), autor=autor, motivo=cuerpo.get("motivo"), hoy=hoy,
                autor_rol=autor_rol,
            )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    logger.info("Calendario: %s %s el día especial %s", autor, r["resultado"] if "resultado" in r else r["accion"], r["dia"]["fecha"])
    return JSONResponse({
        "ok": True, "operacion": operacion, "resultado": r["accion"], "dia": _dia_especial_a_json(r["dia"], hoy),
    })


@router.delete("/configuracion/dias-especiales.json")
async def dias_especiales_quitar_json(
    fecha: str | None = None, motivo: str | None = None,
    usuario: dict = Depends(servicio_identidad.requiere_rol(*ROLES_CON_VISION_TOTAL)),
    _csrf: None = Depends(verificar_csrf),
):
    """Quita (borrado lógico) el día especial de `fecha` (query, AAAA-MM-DD). Un día pasado solo hasta 7 días atrás y
    con `motivo` (query). 404 si esa fecha no tiene día especial. Queda en el historial de cambios. Admin y supervisor;
    el supervisor no puede quitar un día pasado (403) y comparte el límite de escrituras por hora (429)."""
    f = _fecha_param_calendario(fecha, "fecha")
    if f is None:
        raise HTTPException(status_code=400, detail="Indica la `fecha` (AAAA-MM-DD) del día que quieres quitar.")
    _exigir_guardas_calendario(usuario, "quitar", {"fecha": f}, mem.hoy_en_lima())
    await _exigir_limite_escrituras_calendario(usuario)
    try:
        quitado = await mem.eliminar_dia_especial(
            usuario["negocio_id"], f, autor=usuario.get("username"), motivo=motivo, hoy=mem.hoy_en_lima(),
            autor_rol=usuario.get("rol"),
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if quitado is None:
        raise HTTPException(status_code=404, detail="Esa fecha no tiene un día especial cargado.")
    logger.info("Calendario: %s quitó el día especial %s", usuario.get("username"), f.isoformat())
    return JSONResponse({"ok": True, "eliminado": _dia_especial_a_json(quitado, mem.hoy_en_lima())})


@router.get("/calendario/horario.json")
async def calendario_horario_json(usuario: dict = Depends(servicio_identidad.requiere_rol(*ROLES_CON_VISION_TOTAL))):
    """Horario SEMANAL del negocio de la sesión en SOLO LECTURA (admin y supervisor): una entrada por día de la
    semana (lunes a domingo) más el estado actual (abierto/cerrado, motivo, próxima apertura). El supervisor lo ve para
    entender el calendario, pero no puede cambiarlo: la escritura sigue siendo `POST /dashboard/configuracion/horario`
    (solo admin). Contrato en docs/contrato_calendario_supervisor.md."""
    from agent import calendario_negocio
    negocio_id = usuario["negocio_id"]
    ahora = datetime.utcnow()
    filas = {f["dia_semana"]: f for f in await listar_horarios_atencion(negocio_id)}
    cal = await mem.obtener_calendario_negocio(negocio_id)
    rangos = calendario_negocio.rangos_de_semana(cal)
    est = calendario_negocio.estado(ahora, cal)
    return JSONResponse({
        "hoy": mem.hoy_en_lima().isoformat(),
        "solo_lectura": True,
        "dias": [
            {
                "dia_semana": dia, "nombre": calendario_negocio.DIAS_ES[dia], "habilitado": rangos[dia] is not None,
                "hora_apertura": rangos[dia][0] if rangos[dia] else None, "hora_cierre": rangos[dia][1] if rangos[dia] else None,
                "es_por_defecto": dia not in filas,   # el negocio nunca configuró ese día: rige el horario de siempre
            }
            for dia in range(7)
        ],
        "estado_actual": {
            "abierto": est["abierto"], "motivo": est["motivo"], "nombre": est["nombre"],
            "proxima_apertura": iso_utc(est["proxima_apertura"]) if est["proxima_apertura"] else None,
            "proxima_apertura_texto": calendario_negocio.describir_proxima_apertura(est["proxima_apertura"], ahora),
        },
    })


@router.get("/configuracion/dias-especiales/historial.json")
async def dias_especiales_historial_json(
    limite: int = mem.LIMITE_HISTORIAL_CALENDARIO, antes_de: str | None = None,
    usuario: dict = Depends(servicio_identidad.requiere_rol(*ROLES_CON_VISION_TOTAL)),
):
    """Historial legible de cambios del calendario del negocio de la sesión (admin y supervisor), más reciente
    primero: quién, con qué rol, cuándo, qué acción, qué día, antes y después, y el motivo. `limite` 1-200 (por defecto
    100); `antes_de` (el `fecha_hora` del último ítem recibido) pagina hacia atrás. Del negocio de la sesión, nunca
    del cuerpo ni de la query. Contrato en docs/contrato_calendario_supervisor.md."""
    if not 1 <= limite <= mem.MAX_HISTORIAL_CALENDARIO:
        raise HTTPException(status_code=400, detail=f"`limite` debe estar entre 1 y {mem.MAX_HISTORIAL_CALENDARIO}.")
    from datetime import timezone as _timezone
    corte = None
    if antes_de:
        try:
            corte = datetime.fromisoformat(antes_de.strip().replace("Z", "+00:00"))
            if corte.tzinfo is not None:
                corte = corte.astimezone(_timezone.utc).replace(tzinfo=None)
        except ValueError:
            raise HTTPException(status_code=400, detail="`antes_de` debe ser una fecha y hora ISO 8601 (la `fecha_hora` de un ítem).")
    r = await mem.listar_historial_calendario(usuario["negocio_id"], limite, corte)
    return JSONResponse({
        "items": [
            {
                "fecha_hora": iso_utc(i["creado"]), "actor": i["actor"], "actor_rol": i["actor_rol"], "accion": i["accion"],
                "fecha_dia": i["fecha_dia"], "antes": i["antes"], "despues": i["despues"], "motivo": i["motivo"],
            }
            for i in r["items"]
        ],
        "hay_mas": r["hay_mas"],
    })


MAX_DIAS_RANGO_CITAS = 62


@router.get("/calendario/citas.json")
async def calendario_citas_json(desde: str, hasta: str, usuario: dict = Depends(_usuario_actual)):
    """Citas vivas (leads «agendado» no cerrados) cuyo DÍA en Lima cae entre `desde` y `hasta`, ambos inclusive
    (`AAAA-MM-DD`), la más próxima primero — para la grilla del Calendario. Solo lectura. Alcance: el Asesor ve solo
    las suyas; Admin y Supervisor ven las del negocio (con `asesor` en cada ítem). El negocio sale de la sesión.
    Rango máximo `MAX_DIAS_RANGO_CITAS` días. Mismos ítems que las citas de Inicio (`_item_cita`)."""
    try:
        dia_desde, dia_hasta = _date.fromisoformat(desde.strip()), _date.fromisoformat(hasta.strip())
    except ValueError:
        raise HTTPException(status_code=400, detail="`desde` y `hasta` deben ser fechas AAAA-MM-DD.")
    if dia_hasta < dia_desde:
        raise HTTPException(status_code=400, detail="`hasta` no puede ser anterior a `desde`.")
    if (dia_hasta - dia_desde).days + 1 > MAX_DIAS_RANGO_CITAS:
        raise HTTPException(status_code=400, detail=f"El rango no puede superar {MAX_DIAS_RANGO_CITAS} días.")
    vista_admin = usuario["rol"] in ROLES_CON_VISION_TOTAL
    agendados = await mem.listar_leads_agendados(
        usuario["negocio_id"], asesor_asignado=None if vista_admin else usuario["username"],
    )
    citas = [
        _item_cita(l, _texto_cita(l, "Cita"), "cita", vista_admin)
        for l in agendados
        if l.get("fecha_agendada") and dia_desde <= l["fecha_agendada"].date() <= dia_hasta
    ]
    # 2026-11-09: `listar_leads_agendados` trae leads (por teléfono), no conversaciones: sin este paso cada cita salía con
    # `conversation_id: null` y en el Calendario «Abrir lead» y «Reprogramar» no funcionaban. Se resuelve en bloque
    # (no uno por uno), igual que la Zona de acción de Inicio; un teléfono sin conversación activa queda en null.
    faltantes = [c["telefono"] for c in citas if not c["conversation_id"]]
    if faltantes:
        conversation_ids = await resolver_conversation_ids_por_telefono(usuario["negocio_id"], faltantes)
        for c in citas:
            if not c["conversation_id"]:
                c["conversation_id"] = conversation_ids.get(c["telefono"])
    return JSONResponse({"desde": dia_desde.isoformat(), "hasta": dia_hasta.isoformat(), "citas": citas})


@router.get("/canales-whatsapp", response_class=HTMLResponse)
async def gestionar_canales_whatsapp(request: Request, usuario: dict = Depends(servicio_identidad.requiere_rol("admin"))):
    sidebar = await _renderizar_sidebar(usuario, telefono_activo=None)
    canales = await listar_canales_whatsapp(negocio_id=usuario["negocio_id"])

    filas = []
    for c in canales:
        es_produccion = c.get("modo", "produccion") == "produccion"
        filas.append(f"""<tr>
            <td class="ps-3">
                <div class="fw-semibold">{html.escape(c['nombre'])}</div>
                <div class="text-muted" style="font-size:.75rem">Phone Number ID: {html.escape(c['phone_number_id'])}</div>
            </td>
            <td class="text-muted small">
                Token: {html.escape(_enmascarar_token(c.get('access_token')))}<br>
                App Secret: {html.escape(_enmascarar_token(c.get('app_secret')))}
                {_estado_token_canal(c)}
            </td>
            <td>
                <form method="post" action="/dashboard/canales-whatsapp/{c['id']}/modo">
                    {_csrf_campo(request)}
                    <button type="submit" class="btn btn-sm {'btn-outline-primary' if es_produccion else 'btn-outline-warning'}"
                        title="Click para cambiar a {'pruebas' if es_produccion else 'producción'}">
                        {'🟢 Producción' if es_produccion else '🧪 Pruebas'}
                    </button>
                </form>
            </td>
            <td>
                <form method="post" action="/dashboard/canales-whatsapp/{c['id']}/toggle">
                    {_csrf_campo(request)}
                    <button type="submit" class="btn btn-sm {'btn-success' if c['activo'] else 'btn-outline-secondary'}">
                        {'Activo' if c['activo'] else 'Inactivo'}
                    </button>
                </form>
            </td>
            <td class="pe-3">
                <a href="/dashboard/canales-whatsapp?editar={c['id']}" class="btn btn-sm btn-outline-secondary" title="Editar nombre o credenciales">
                    <i class="bi bi-pencil"></i>
                </a>
            </td>
        </tr>""")

    app_id = os.getenv("META_APP_ID", "")
    config_id = os.getenv("META_EMBEDDED_SIGNUP_CONFIG_ID", "")
    if app_id and config_id:
        conectar_html = f"""
        <p class="text-muted small mb-3">
            El único camino soportado por Meta para conectar un número que sigue usando la app de
            WhatsApp Business en el celular sin perder su historial (Coexistencia). Para números
            nuevos sin nada que conservar, el formulario manual de abajo alcanza igual.
        </p>
        <div id="estado-conectar-whatsapp" class="small mb-2"></div>
        <div class="row g-2">
            <div class="col-md-4">
                <label class="form-label small text-muted mb-0">Nombre (para identificarlo en el panel)</label>
                <input type="text" id="conectar-whatsapp-nombre" class="form-control form-control-sm" placeholder="Ej: Cálidda - Producción">
            </div>
            <div class="col-md-4">
                <label class="form-label small text-muted mb-0">PIN de verificación en dos pasos (6 dígitos)</label>
                <input type="text" id="conectar-whatsapp-pin" class="form-control form-control-sm" maxlength="6" placeholder="El que ya tenga el número, o uno nuevo">
            </div>
            <div class="col-md-4 d-flex align-items-end">
                <button type="button" id="btn-conectar-whatsapp" class="btn btn-sm btn-primary w-100">
                    <i class="bi bi-whatsapp"></i> Conectar WhatsApp
                </button>
            </div>
        </div>
        <script>
        (function() {{
            var appId = '{html.escape(app_id)}';
            var configId = '{html.escape(config_id)}';
            var btn = document.getElementById('btn-conectar-whatsapp');
            var estado = document.getElementById('estado-conectar-whatsapp');
            var pinInput = document.getElementById('conectar-whatsapp-pin');
            var nombreInput = document.getElementById('conectar-whatsapp-nombre');
            var datosSignup = {{}};

            function mostrarEstado(texto, tipo) {{
                estado.className = 'small mb-2 text-' + (tipo || 'muted');
                estado.textContent = texto;
            }}

            window.fbAsyncInit = function() {{
                FB.init({{ appId: appId, version: 'v21.0' }});
            }};
            (function(d, s, id) {{
                if (d.getElementById(id)) return;
                var js = d.createElement(s);
                js.id = id;
                js.src = 'https://connect.facebook.net/es_LA/sdk.js';
                d.getElementsByTagName(s)[0].parentNode.insertBefore(js, d.getElementsByTagName(s)[0]);
            }})(document, 'script', 'facebook-jssdk-conectar');

            window.addEventListener('message', function(event) {{
                if (!event.origin || event.origin.indexOf('facebook.com') === -1) return;
                var datos;
                try {{ datos = JSON.parse(event.data); }} catch (e) {{ return; }}
                if (datos.type !== 'WA_EMBEDDED_SIGNUP') return;
                if (datos.event === 'CANCEL') {{
                    mostrarEstado('Conexión cancelada.', 'muted');
                }} else if (datos.event === 'ERROR') {{
                    mostrarEstado('Meta reportó un error: ' + ((datos.data && datos.data.error_message) || 'desconocido'), 'danger');
                }} else if (datos.event === 'FINISH' && datos.data) {{
                    // Cloud API estándar — el número es nuevo, hay que registrarlo.
                    datosSignup = datos.data;
                    datosSignup.es_coexistencia = false;
                }} else if (datos.event === 'FINISH_WHATSAPP_BUSINESS_APP_ONBOARDING' && datos.data) {{
                    // Gate 5.7 — Coexistencia: el número ya está en la app de
                    // WhatsApp Business del celular y ya está registrado en
                    // Cloud API. Es la señal que Meta ya nos da — nunca se
                    // infiere del lado del servidor.
                    datosSignup = datos.data;
                    datosSignup.es_coexistencia = true;
                }}
            }});

            if (btn) {{
                btn.addEventListener('click', function() {{
                    if (!nombreInput.value.trim()) {{
                        mostrarEstado('Ingresa un nombre para identificar el canal.', 'danger');
                        nombreInput.focus();
                        return;
                    }}
                    if (!/^\\d{{6}}$/.test(pinInput.value)) {{
                        mostrarEstado('Ingresa el PIN de verificación en dos pasos (6 dígitos).', 'danger');
                        pinInput.focus();
                        return;
                    }}
                    mostrarEstado('Abriendo ventana de Meta...', 'muted');
                    FB.login(function(response) {{
                        if (!response.authResponse || !response.authResponse.code) {{
                            mostrarEstado('No se completó la conexión.', 'muted');
                            return;
                        }}
                        mostrarEstado('Conectando...', 'muted');
                        fetch('/dashboard/canales-whatsapp/embedded-signup/callback', {{
                            method: 'POST',
                            headers: {{ 'Content-Type': 'application/json', 'X-CSRF-Token': window.__csrfToken() }},
                            body: JSON.stringify({{
                                code: response.authResponse.code,
                                waba_id: datosSignup.waba_id || '',
                                phone_number_id: datosSignup.phone_number_id || '',
                                pin: pinInput.value,
                                nombre: nombreInput.value.trim(),
                                es_coexistencia: datosSignup.es_coexistencia || false,
                            }}),
                        }}).then(function(r) {{
                            return r.json().then(function(j) {{ return {{ status: r.status, j: j }}; }});
                        }}).then(function(res) {{
                            if (res.j.ok) {{
                                window.location.href = '/dashboard/canales-whatsapp?conectado=1';
                            }} else {{
                                mostrarEstado(res.j.detail || 'No se pudo completar la conexión.', 'danger');
                            }}
                        }}).catch(function() {{
                            mostrarEstado('Error de red al conectar.', 'danger');
                        }});
                    }}, {{
                        config_id: configId,
                        response_type: 'code',
                        override_default_response_type: true,
                        extras: {{
                            setup: {{}},
                            featureType: 'whatsapp_business_app_onboarding',
                            sessionInfoVersion: '3',
                        }},
                    }});
                }});
            }}
        }})();
        </script>
        """
    else:
        conectar_html = (
            '<p class="text-muted small mb-0">'
            'No configurado todavía — faltan <code>META_APP_ID</code> y '
            '<code>META_EMBEDDED_SIGNUP_CONFIG_ID</code> en las variables de entorno del servidor. '
            'Mientras tanto, usa el formulario manual de abajo.</p>'
        )
    conectado_ok = (
        '<div class="alert alert-success py-2 px-3 mb-3"><i class="bi bi-check-circle-fill"></i> '
        'Canal conectado.</div>'
    ) if request.query_params.get("conectado") else ""
    editado_ok = (
        '<div class="alert alert-success py-2 px-3 mb-3"><i class="bi bi-check-circle-fill"></i> '
        'Canal actualizado.</div>'
    ) if request.query_params.get("editado") else ""
    registrado_html = ""
    if request.query_params.get("registrado"):
        r_register = request.query_params.get("register")
        r_webhook = request.query_params.get("webhook")
        detalle_register = (
            "número ya estaba registrado (no hizo falta)" if r_register == "fallo" else "número registrado"
        )
        detalle_webhook = {
            "ok": "webhooks suscritos", "fallo": "⚠️ no se pudo suscribir los webhooks — revisa los logs",
            "sin_waba_id": "⚠️ sin WhatsApp Business Account ID, no se pudo suscribir los webhooks",
        }.get(r_webhook, "")
        registrado_html = (
            f'<div class="alert alert-info py-2 px-3 mb-3"><i class="bi bi-info-circle-fill"></i> '
            f'Registro completado — {detalle_register}, {detalle_webhook}.</div>'
        )

    # Edición de un canal existente — solo nombre/credenciales (Alcance A,
    # aprobado 2026-08-14): phone_number_id queda fuera a propósito, porque es
    # la clave que usa resolver_canal() para enrutar mensajes entrantes — un
    # error de tipeo ahí desconectaría el canal, a diferencia de un token mal
    # puesto, que solo falla al enviar (más fácil de notar y corregir).
    editar_id = request.query_params.get("editar")
    editar_html = ""
    if editar_id:
        canal_editar = next((c for c in canales if str(c["id"]) == editar_id), None)
        if canal_editar:
            editar_html = f"""
            {_titulo_seccion('bi-pencil-fill', f"Editar canal — {html.escape(canal_editar['nombre'])}")}
            <p class="text-muted small mb-2">
                Deja en blanco cualquier credencial que no quieras cambiar — no se borra la que ya
                está guardada. El Phone Number ID no se puede editar acá (identifica al canal).
            </p>
            <div class="card leads-card shadow-sm mb-4">
                <div class="barra-acento"></div>
                <div class="card-body">
                    <form method="post" action="/dashboard/canales-whatsapp/{canal_editar['id']}/editar" class="row g-2">
                        {_csrf_campo(request)}
                        <div class="col-md-4">
                            <label class="form-label small text-muted mb-0">Nombre</label>
                            <input type="text" name="nombre" class="form-control form-control-sm" value="{html.escape(canal_editar['nombre'])}" required>
                        </div>
                        <div class="col-md-4">
                            <label class="form-label small text-muted mb-0">Access Token <span class="text-muted">(actual: {html.escape(_enmascarar_token(canal_editar.get('access_token')))})</span></label>
                            <input type="text" name="access_token" class="form-control form-control-sm" placeholder="Dejar en blanco para no cambiar">
                        </div>
                        <div class="col-md-4">
                            <label class="form-label small text-muted mb-0">App Secret <span class="text-muted">(actual: {html.escape(_enmascarar_token(canal_editar.get('app_secret')))})</span></label>
                            <input type="text" name="app_secret" class="form-control form-control-sm" placeholder="Dejar en blanco para no cambiar">
                        </div>
                        <div class="col-md-4">
                            <label class="form-label small text-muted mb-0">Page Access Token <span class="text-muted">(actual: {html.escape(_enmascarar_token(canal_editar.get('page_access_token')))})</span></label>
                            <input type="text" name="page_access_token" class="form-control form-control-sm" placeholder="Dejar en blanco para no cambiar">
                        </div>
                        <div class="col-12 d-flex gap-2">
                            <button type="submit" class="btn btn-sm btn-primary">Guardar cambios</button>
                            <a href="/dashboard/canales-whatsapp" class="btn btn-sm btn-outline-secondary">Cancelar</a>
                        </div>
                    </form>
                </div>
            </div>
            """

    panel = f"""
    {_titulo_seccion('bi-whatsapp', 'Canales de WhatsApp')}
    <p class="text-muted small mb-3">
        Cada canal es un número de WhatsApp que Gabi puede usar para recibir y responder mensajes.
        Se puede tener más de uno activo a la vez (ej. un número de pruebas y el de producción) —
        cada mensaje se identifica y se responde siempre por el mismo número por el que entró.
        Los tokens se guardan cifrados en la base de datos.
    </p>
    {conectado_ok}
    {editado_ok}
    {registrado_html}

    <div class="card leads-card shadow-sm mb-4">
        <div class="barra-acento"></div>
        <div class="table-responsive">
            <table class="table table-hover align-middle mb-0 tabla-ejecutiva">
                <thead>
                    <tr><th class="ps-3">Canal</th><th>Credenciales</th><th>Modo</th><th>Estado</th><th class="pe-3"></th></tr>
                </thead>
                <tbody>{''.join(filas) or '<tr><td colspan="5" class="text-center text-muted py-4">Aún no hay canales configurados.</td></tr>'}</tbody>
            </table>
        </div>
    </div>

    {editar_html}

    {_titulo_seccion('bi-plug-fill', 'Conectar WhatsApp')}
    <div class="card leads-card shadow-sm mb-4">
        <div class="barra-acento"></div>
        <div class="card-body">
            {conectar_html}
        </div>
    </div>

    {_titulo_seccion('bi-plus-circle-fill', 'Nuevo canal (manual)')}
    <p class="text-muted small mb-2">
        Estos datos se obtienen desde Meta for Developers → tu app → WhatsApp → Configuración de la API.
    </p>
    <div class="card leads-card shadow-sm">
        <div class="barra-acento"></div>
        <div class="card-body">
            <form method="post" action="/dashboard/canales-whatsapp/nuevo" class="row g-2">
                {_csrf_campo(request)}
                <div class="col-md-4">
                    <label class="form-label small text-muted mb-0">Nombre (para identificarlo en el panel)</label>
                    <input type="text" name="nombre" class="form-control form-control-sm" required placeholder="Ej: Cálidda - Producción">
                </div>
                <div class="col-md-4">
                    <label class="form-label small text-muted mb-0">Phone Number ID</label>
                    <input type="text" name="phone_number_id" class="form-control form-control-sm" required placeholder="Ej: 418282818043771">
                </div>
                <div class="col-md-4">
                    <label class="form-label small text-muted mb-0">Access Token</label>
                    <input type="text" name="access_token" class="form-control form-control-sm" required placeholder="Token permanente del número">
                </div>
                <div class="col-md-4">
                    <label class="form-label small text-muted mb-0">App Secret</label>
                    <input type="text" name="app_secret" class="form-control form-control-sm" placeholder="Para verificar la firma del webhook">
                </div>
                <div class="col-md-4">
                    <label class="form-label small text-muted mb-0">Page Access Token <span class="text-muted">(opcional, solo Lead Ads)</span></label>
                    <input type="text" name="page_access_token" class="form-control form-control-sm" placeholder="Solo si usas leads de formulario de Meta">
                </div>
                <div class="col-md-4">
                    <label class="form-label small text-muted mb-0">Modo</label>
                    <select name="modo" class="form-select form-select-sm">
                        <option value="produccion">🟢 Producción (usa el prompt promovido)</option>
                        <option value="pruebas">🧪 Pruebas (usa siempre el prompt recién desplegado)</option>
                    </select>
                </div>
                <div class="col-12">
                    <button type="submit" class="btn btn-sm btn-primary">Agregar canal</button>
                </div>
            </form>
        </div>
    </div>

    {_titulo_seccion('bi-broadcast', 'Completar registro en Meta')}
    <p class="text-muted small mb-2">
        Un canal creado con "Nuevo canal" arriba queda guardado en el panel, pero Meta todavía no
        lo activó para la Cloud API — falta esta llamada aparte (el alta por "Conectar WhatsApp"
        ya la hace sola). Sin esto el canal se ve "Activo" acá pero no envía ni recibe mensajes de
        verdad. Usa este formulario una sola vez por canal manual.
    </p>
    <div class="card leads-card shadow-sm">
        <div class="barra-acento"></div>
        <div class="card-body">
            <form method="post" action="/dashboard/canales-whatsapp/registrar" class="row g-2">
                {_csrf_campo(request)}
                <div class="col-md-4">
                    <label class="form-label small text-muted mb-0">Canal</label>
                    <select name="canal_id" class="form-select form-select-sm" required>
                        {''.join(f'<option value="{c["id"]}">{html.escape(c["nombre"])} ({html.escape(c["phone_number_id"])})</option>' for c in canales)}
                    </select>
                </div>
                <div class="col-md-4">
                    <label class="form-label small text-muted mb-0">PIN de verificación en dos pasos (6 dígitos)</label>
                    <input type="text" name="pin" class="form-control form-control-sm" required maxlength="6" placeholder="El que ya tenga, o uno nuevo">
                </div>
                <div class="col-md-4">
                    <label class="form-label small text-muted mb-0">WhatsApp Business Account ID</label>
                    <input type="text" name="waba_id" class="form-control form-control-sm" placeholder="Ej: 1453263996623875">
                </div>
                <div class="col-12">
                    <button type="submit" class="btn btn-sm btn-primary">Registrar y suscribir webhooks</button>
                </div>
            </form>
        </div>
    </div>

    {_titulo_seccion('bi-chat-square-text-fill', 'Prompt de Gabi')}
    <p class="text-muted small mb-2">
        El prompt recién desplegado corre de inmediato en los canales marcados "Pruebas". Los
        canales en "Producción" usan la última versión promovida acá — no cambia sola con un deploy.
    </p>
    {await _bloque_promover_prompt(request, usuario["negocio_id"])}
    """
    cuerpo = f"""<div class="shell d-flex">{sidebar}<div class="main-pane flex-grow-1 p-4">{panel}</div></div>"""
    return _pagina("Canales de WhatsApp", usuario, cuerpo, request=request)


@router.post("/canales-whatsapp/nuevo")
async def crear_canal_whatsapp_nuevo(
    nombre: str = Form(...),
    phone_number_id: str = Form(...),
    access_token: str = Form(...),
    app_secret: str = Form(""),
    page_access_token: str = Form(""),
    modo: str = Form("produccion"),
    usuario: dict = Depends(servicio_identidad.requiere_rol("admin")),
    _csrf: None = Depends(verificar_csrf),
):
    # Gate 5.2 (corrección H3): negocio_id del admin que da de alta el canal
    # — mismo criterio que crear_usuario_nuevo/crear_campana_nueva.
    await crear_canal_whatsapp(
        nombre=nombre.strip(), phone_number_id=phone_number_id.strip(),
        access_token=access_token.strip(), app_secret=app_secret.strip(),
        page_access_token=page_access_token.strip(), modo=modo,
        negocio_id=usuario["negocio_id"],
    )
    return RedirectResponse(url="/dashboard/canales-whatsapp", status_code=303)


_LIMITE_TRUNCADO_LOG_META = 300


def _resumen_seguro_error_meta(r) -> str:
    """Hardening de logging (auditoría Coexistence Gap Analysis, hallazgo
    §6): nunca volcar `r.text` completo de una respuesta de error de Graph
    API al logger — podría en teoría reflejar datos sensibles de la
    request. Allowlist, no blocklist: si el cuerpo es JSON con forma de
    error de Meta, solo se toman los campos documentados
    (`type`/`code`/`message`/`fbtrace_id`) — nada fuera de esa lista sale al
    log jamás, así que `access_token`, `Authorization` o `code` no pueden
    aparecer aunque el cuerpo los contuviera. Si no es JSON o no tiene esa
    forma, se cae a una representación truncada del texto (nunca sin
    límite) — mismo criterio que pidió el usuario para ese caso."""
    try:
        cuerpo = r.json()
    except Exception:
        cuerpo = None

    if isinstance(cuerpo, dict) and isinstance(cuerpo.get("error"), dict):
        error = cuerpo["error"]
        campos = {
            campo: error[campo]
            for campo in ("type", "code", "message", "fbtrace_id")
            if campo in error
        }
        return f"status={r.status_code} error={campos}"

    texto = (r.text or "")[:_LIMITE_TRUNCADO_LOG_META]
    return f"status={r.status_code} body(truncado a {_LIMITE_TRUNCADO_LOG_META}c)={texto!r}"


async def _resolver_phone_number_id_desde_waba(waba_id: str, headers: dict, api_version: str) -> tuple[str | None, str | None]:
    """Corrección de gap confirmado (Coexistence Gap Analysis): el evento
    `FINISH_WHATSAPP_BUSINESS_APP_ONBOARDING` de Meta solo entrega `waba_id`
    en su payload — a diferencia de `FINISH` (Cloud API estándar), NUNCA
    trae `phone_number_id`, confirmado contra la documentación oficial de
    Meta (`.../embedded-signup/onboarding-business-app-users/`). Se resuelve
    acá vía `GET /{waba_id}/phone_numbers` con el mismo token del intercambio
    de `code` — ese token ya demuestra tener alcance a nivel de esa WABA (el
    mismo se usa para `/{waba_id}/subscribed_apps` más abajo, ya en
    producción).

    Devuelve `(phone_number_id, None)` en éxito, o `(None, detalle_error)`
    si no se puede resolver de forma inequívoca. Fail-closed deliberado: 0
    números o más de uno son ambos errores — nunca se elige un número al
    azar entre varios."""
    r = await get_con_reintentos(
        f"https://graph.facebook.com/{api_version}/{waba_id}/phone_numbers",
        headers=headers,
    )
    if r.status_code != 200:
        logger.error(f"Embedded Signup (Coexistencia): fallo al resolver phone_number_id desde waba_id={waba_id} — {_resumen_seguro_error_meta(r)}")
        return None, "No se pudo obtener el número de teléfono desde Meta. Intenta de nuevo."
    numeros = r.json().get("data", [])
    if len(numeros) == 0:
        return None, "La cuenta de WhatsApp Business no tiene ningún número de teléfono asociado."
    if len(numeros) > 1:
        logger.warning(f"Embedded Signup (Coexistencia): waba_id={waba_id} tiene {len(numeros)} números — no se elige automáticamente.")
        return None, "La cuenta de WhatsApp Business tiene más de un número — contacta a soporte para completar la conexión manualmente."
    phone_number_id = (numeros[0].get("id") or "").strip()
    if not phone_number_id:
        return None, "Meta no devolvió un identificador de número válido."
    return phone_number_id, None


@router.post("/canales-whatsapp/embedded-signup/callback")
async def conectar_whatsapp_embedded_signup(
    request: Request,
    usuario: dict = Depends(servicio_identidad.requiere_rol("admin")),
    _csrf: None = Depends(verificar_csrf),
):
    """Recibe el `code` que entrega el SDK de Facebook Login for Business al
    completar Embedded Signup ("Conectar WhatsApp") y termina de registrar
    el número para Cloud API — reemplaza, para el caso de Coexistencia, el
    copiar/pegar manual del formulario "Nuevo canal" de abajo. Ver plan en
    memoria del proyecto: project_coexistencia_embedded_signup_requerido.

    Gate 5.7 — cierra el gap confirmado por la Auditoría Histórica de
    Coexistencia: hasta acá, el callback trataba TODO como Cloud API
    estándar (llamaba `/register` siempre), sin distinguir el caso real de
    Coexistencia (número que ya está en la app de WhatsApp Business del
    celular, ya registrado). `es_coexistencia` viaja desde el frontend,
    resuelto por el propio evento que Meta entrega
    (`FINISH_WHATSAPP_BUSINESS_APP_ONBOARDING` vs `FINISH`) — nunca inferido
    acá. Alcance mínimo aprobado (Diseño Técnico Gate 5.7 §10): se cumple el
    protocolo de Meta (sincronización de contactos/historial solicitada,
    dentro de la ventana de 24h) sin persistir ese contenido en
    Contact/Conversation/Mensaje — esa importación queda fuera de este Gate."""
    datos = await request.json()
    code = (datos.get("code") or "").strip()
    waba_id = (datos.get("waba_id") or "").strip()
    phone_number_id = (datos.get("phone_number_id") or "").strip()
    pin = (datos.get("pin") or "").strip()
    nombre = (datos.get("nombre") or "").strip()
    es_coexistencia = bool(datos.get("es_coexistencia"))

    if not code or not waba_id or not nombre or len(pin) != 6:
        return JSONResponse({"ok": False, "detail": "Faltan datos para completar la conexión."}, status_code=400)
    # Coexistencia: Meta NO entrega phone_number_id en el evento
    # FINISH_WHATSAPP_BUSINESS_APP_ONBOARDING (documentación oficial: el
    # payload de ese evento solo trae waba_id) — se resuelve server-side más
    # abajo. Para el flujo estándar (FINISH) sí lo entrega y sigue siendo
    # obligatorio acá, sin cambios.
    if not es_coexistencia and not phone_number_id:
        return JSONResponse({"ok": False, "detail": "Faltan datos para completar la conexión."}, status_code=400)

    app_id = os.getenv("META_APP_ID", "")
    app_secret = os.getenv("META_APP_SECRET", "")
    if not app_id or not app_secret:
        return JSONResponse(
            {"ok": False, "detail": "META_APP_ID/META_APP_SECRET no están configurados en el servidor."},
            status_code=500,
        )

    api_version = "v21.0"

    r = await get_con_reintentos(
        f"https://graph.facebook.com/{api_version}/oauth/access_token",
        params={"client_id": app_id, "client_secret": app_secret, "code": code},
    )
    if r.status_code != 200:
        logger.error(f"Embedded Signup: fallo al intercambiar code — {_resumen_seguro_error_meta(r)}")
        return JSONResponse({"ok": False, "detail": "Meta rechazó el código de conexión. Intenta de nuevo."}, status_code=400)
    access_token = r.json().get("access_token", "")
    if not access_token:
        return JSONResponse({"ok": False, "detail": "Meta no devolvió un token válido."}, status_code=400)

    headers = {"Authorization": f"Bearer {access_token}"}

    if es_coexistencia:
        phone_number_id, error_resolucion = await _resolver_phone_number_id_desde_waba(waba_id, headers, api_version)
        if error_resolucion:
            return JSONResponse({"ok": False, "detail": error_resolucion}, status_code=400)

    if not es_coexistencia:
        r = await post_con_reintentos(
            f"https://graph.facebook.com/{api_version}/{phone_number_id}/register",
            headers=headers, json={"messaging_product": "whatsapp", "pin": pin},
        )
        if r.status_code != 200:
            logger.error(f"Embedded Signup: fallo al registrar el número — {_resumen_seguro_error_meta(r)}")
            return JSONResponse(
                {"ok": False, "detail": "No se pudo registrar el número en Cloud API. Verifica el PIN e intenta de nuevo."},
                status_code=400,
            )
    else:
        # Gate 5.7 — Coexistencia: el número YA está registrado (viene de la
        # app de WhatsApp Business del celular) — Meta indica explícitamente
        # que hay que SALTAR /register acá, no repetirlo. En su lugar, se
        # solicita la sincronización de contactos e historial (SMB App Data
        # API) dentro de la ventana de 24h que exige Meta — sin esto, o el
        # negocio debe re-onboardear. Un fallo acá no aborta la creación del
        # canal (mismo criterio que /subscribed_apps más abajo): mejor un
        # canal conectado sin sincronización que perder todo el trabajo ya
        # hecho. El contenido sincronizado no se persiste en este Gate (ver
        # docstring arriba) — la solicitud en sí es lo que exige Meta.
        for tipo_sync in ("smb_app_state_sync", "history"):
            r_sync = await post_con_reintentos(
                f"https://graph.facebook.com/{api_version}/{phone_number_id}/smb_app_data",
                headers=headers, json={"messaging_product": "whatsapp", "sync_type": tipo_sync},
            )
            if r_sync.status_code != 200:
                logger.warning(
                    f"Embedded Signup (Coexistencia): fallo al solicitar sincronización "
                    f"'{tipo_sync}' — {r_sync.status_code} {r_sync.text}"
                )
            else:
                logger.info(
                    f"Embedded Signup (Coexistencia): sincronización '{tipo_sync}' solicitada, "
                    f"request_id={r_sync.json().get('request_id', '')}"
                )

    # Sin esto, ningún mensaje de esta WABA llegaría a nuestro /webhook — el
    # número quedaría registrado pero mudo. Si falla, no abortamos: el canal
    # se guarda igual y queda pendiente suscribir a mano desde WhatsApp
    # Manager (mejor eso que perder todo el trabajo de arriba).
    r_webhook = await post_con_reintentos(
        f"https://graph.facebook.com/{api_version}/{waba_id}/subscribed_apps",
        headers=headers,
    )
    if r_webhook.status_code != 200:
        logger.error(f"Embedded Signup: fallo al suscribir la WABA a los webhooks — {r_webhook.status_code} {r_webhook.text}")

    # Gate 5.2 (corrección H3): mismo criterio — negocio_id del admin que
    # completó el flujo de Embedded Signup.
    try:
        await crear_canal_whatsapp(
            nombre=nombre, phone_number_id=phone_number_id,
            access_token=access_token, app_secret=app_secret, waba_id=waba_id,
            negocio_id=usuario["negocio_id"],
        )
    except IntegrityError:
        # Gate 5.7 — idempotencia: doble click, o el número ya fue conectado
        # antes (a mano o por un intento previo de Embedded Signup).
        # phone_number_id es unique — la fila ya existe, no hay nada que
        # romper, solo informarlo con claridad en vez de un 500 genérico.
        logger.warning(f"Embedded Signup: intento de crear un canal duplicado para phone_number_id={phone_number_id}")
        return JSONResponse(
            {"ok": False, "detail": "Este número ya está conectado como canal — revisa la lista de canales."},
            status_code=409,
        )
    return JSONResponse({"ok": True})


async def _verificar_ownership_canal(usuario: dict, canal_id: int) -> dict:
    """Gate 5.3 — corrección pequeña, misma familia que
    `_verificar_ownership_campana`, con prioridad más alta acá por tocar
    credenciales de canal (access_token/app_secret) — un admin de otro
    Negocio no debe poder ni siquiera confirmar que el canal existe."""
    canal = await obtener_canal_whatsapp(canal_id)
    if canal is None or canal.get("negocio_id") != usuario.get("negocio_id"):
        raise HTTPException(status_code=404, detail="Canal no encontrado")
    return canal


@router.post("/canales-whatsapp/{canal_id}/editar")
async def editar_canal_whatsapp_ruta(
    canal_id: int,
    nombre: str = Form(...),
    access_token: str = Form(""),
    app_secret: str = Form(""),
    page_access_token: str = Form(""),
    usuario: dict = Depends(servicio_identidad.requiere_rol("admin")),
    _csrf: None = Depends(verificar_csrf),
):
    """Edita nombre/credenciales de un canal ya existente — Alcance A
    (aprobado 2026-08-14): sin phone_number_id ni waba_id, sin alertas de
    caducidad. Resuelve el caso real de hoy: renovar el Access Token de
    Coexistencia antes de que caduque a los 60 días."""
    await _verificar_ownership_canal(usuario, canal_id)
    await actualizar_canal_whatsapp(
        canal_id, nombre=nombre.strip(), access_token=access_token.strip(),
        app_secret=app_secret.strip(), page_access_token=page_access_token.strip(),
    )
    return RedirectResponse(url="/dashboard/canales-whatsapp?editado=1", status_code=303)


@router.post("/canales-whatsapp/{canal_id}/toggle")
async def toggle_canal_whatsapp(canal_id: int, usuario: dict = Depends(servicio_identidad.requiere_rol("admin")), _csrf: None = Depends(verificar_csrf)):
    actual = await _verificar_ownership_canal(usuario, canal_id)
    await actualizar_canal_whatsapp(canal_id, activo=not actual["activo"])
    return RedirectResponse(url="/dashboard/canales-whatsapp", status_code=303)


@router.post("/canales-whatsapp/{canal_id}/modo")
async def toggle_modo_canal_whatsapp(canal_id: int, usuario: dict = Depends(servicio_identidad.requiere_rol("admin")), _csrf: None = Depends(verificar_csrf)):
    actual = await _verificar_ownership_canal(usuario, canal_id)
    nuevo_modo = "pruebas" if actual.get("modo", "produccion") == "produccion" else "produccion"
    await actualizar_canal_whatsapp(canal_id, modo=nuevo_modo)
    return RedirectResponse(url="/dashboard/canales-whatsapp", status_code=303)


@router.post("/canales-whatsapp/registrar")
async def registrar_canal_whatsapp_ruta(
    canal_id: int = Form(...),
    pin: str = Form(...),
    waba_id: str = Form(""),
    usuario: dict = Depends(servicio_identidad.requiere_rol("admin")),
    _csrf: None = Depends(verificar_csrf),
):
    """Completa en Meta lo que el alta manual ("Nuevo canal" arriba) no hace
    sola: `POST /{phone_number_id}/register` (activa el número para la Cloud
    API — sin esto Meta lo deja "registrado pero mudo": mensajes entrantes
    se quedan en un solo check, nada llega a nuestro /webhook) y
    `POST /{waba_id}/subscribed_apps` (suscribe la app a los webhooks de esa
    WABA — mismo motivo, ver el comentario idéntico en el callback de
    Embedded Signup más abajo). El alta por "Conectar WhatsApp" (Embedded
    Signup) hace las dos llamadas sola porque pasa por el popup de Meta; el
    formulario manual, al no pasar por ahí, se queda sin ellas.

    Hallazgo real (2026-09-16): un canal de Cálidda Hogar creado a mano
    quedaba "Activo" en el panel pero no enviaba ni recibía mensajes de
    verdad — este paso faltante era la causa."""
    canal = await _verificar_ownership_canal(usuario, canal_id)
    access_token = canal.get("access_token")
    if not access_token:
        raise HTTPException(status_code=400, detail="Este canal no tiene un Access Token guardado.")
    pin_limpio = pin.strip()
    if not (pin_limpio.isdigit() and len(pin_limpio) == 6):
        raise HTTPException(status_code=422, detail="El PIN debe tener 6 dígitos.")

    api_version = "v21.0"
    headers = {"Authorization": f"Bearer {access_token}"}

    # `/register` NO aborta si falla (2026-09-16, corrección tras el primer
    # uso real): un número que Meta ya dejó "Conectado" por su cuenta
    # (ej. una vez que termina la revisión del nombre) rechaza un segundo
    # `/register` con "(#100) Invalid parameter" — no es un error real, es
    # que ya no hace falta. Mismo criterio que ya usa el bloque de
    # Coexistencia más abajo para `/smb_app_data`: mejor seguir hacia la
    # suscripción de webhooks (la pieza que de verdad falta comprobar) que
    # cortar acá por un registro que probablemente ya estaba hecho.
    resultado_register = "ok"
    r = await post_con_reintentos(
        f"https://graph.facebook.com/{api_version}/{canal['phone_number_id']}/register",
        headers=headers, json={"messaging_product": "whatsapp", "pin": pin_limpio},
    )
    if r.status_code != 200:
        resultado_register = "fallo"
        logger.warning(f"Registrar canal {canal_id}: /register no aplicó (probablemente ya estaba registrado) — {_resumen_seguro_error_meta(r)}")

    resultado_webhook = "sin_waba_id"
    waba_id_final = (waba_id.strip() or canal.get("waba_id") or "").strip()
    if waba_id_final:
        r_webhook = await post_con_reintentos(
            f"https://graph.facebook.com/{api_version}/{waba_id_final}/subscribed_apps",
            headers=headers,
        )
        resultado_webhook = "ok" if r_webhook.status_code == 200 else "fallo"
        if r_webhook.status_code != 200:
            logger.error(
                f"Registrar canal {canal_id}: fallo al suscribir webhooks — {_resumen_seguro_error_meta(r_webhook)}"
            )
        if waba_id_final != canal.get("waba_id"):
            await actualizar_canal_whatsapp(canal_id, waba_id=waba_id_final)

    return RedirectResponse(
        url=f"/dashboard/canales-whatsapp?registrado=1&register={resultado_register}&webhook={resultado_webhook}",
        status_code=303,
    )


@router.post("/canales-whatsapp/promover-prompt")
async def promover_prompt_produccion_route(usuario: dict = Depends(servicio_identidad.requiere_rol("admin")), _csrf: None = Depends(verificar_csrf)):
    """Copia el prompt recién desplegado (config/prompts.yaml) hacia la
    versión que usan los canales de producción — sin necesitar un deploy
    para que el cambio ya probado en el número de pruebas llegue allá."""
    await guardar_configuracion("system_prompt_produccion", cargar_system_prompt())
    return RedirectResponse(url="/dashboard/canales-whatsapp", status_code=303)


# ── Mi perfil / cambio de contraseña (self-service, cualquier rol) ────

@router.get("/perfil", response_class=HTMLResponse)
async def mi_perfil(request: Request, usuario: dict = Depends(_usuario_actual), error: str = "", ok: str = ""):
    sidebar = await _renderizar_sidebar(usuario, telefono_activo=None)

    mensaje = ""
    if error:
        mensaje = f'<div class="alert alert-danger py-2 small">{html.escape(error)}</div>'
    elif ok:
        mensaje = f'<div class="alert alert-success py-2 small">{html.escape(ok)}</div>'

    panel = f"""
    {_titulo_seccion('bi-person-circle', 'Mi perfil')}
    <div class="card shadow-sm" style="max-width:420px;">
        <div class="card-body">
            <div class="d-flex align-items-center gap-2 mb-3">
                {_avatar(usuario['nombre'], 44)}
                <div>
                    <div class="fw-semibold">{html.escape(usuario['nombre'])}</div>
                    <div class="text-muted small">{html.escape(usuario['username'])} &middot; {html.escape(usuario['rol'])}</div>
                </div>
            </div>
            <hr>
            <h6 class="text-uppercase text-muted small fw-bold mb-2">Cambiar contraseña</h6>
            {mensaje}
            <form method="post" action="/dashboard/perfil/password">
                {_csrf_campo(request)}
                <div class="mb-2">
                    <label class="form-label small text-muted mb-0">Contraseña actual</label>
                    <input type="password" name="password_actual" class="form-control form-control-sm" required>
                </div>
                <div class="mb-2">
                    <label class="form-label small text-muted mb-0">Contraseña nueva</label>
                    <input type="password" name="password_nueva" class="form-control form-control-sm" required minlength="12" maxlength="128" autocomplete="new-password">
                </div>
                <div class="mb-3">
                    <label class="form-label small text-muted mb-0">Repetir contraseña nueva</label>
                    <input type="password" name="password_nueva_repetir" class="form-control form-control-sm" required minlength="12" maxlength="128" autocomplete="new-password">
                </div>
                <button type="submit" class="btn btn-sm btn-primary">Guardar contraseña</button>
            </form>
        </div>
    </div>
    """
    cuerpo = f"""<div class="shell d-flex">{sidebar}<div class="main-pane flex-grow-1 p-4">{panel}</div></div>"""
    return _pagina("Mi perfil", usuario, cuerpo, request=request)


@router.post("/perfil/password")
async def cambiar_password_propia(
    password_actual: str = Form(...),
    password_nueva: str = Form(...),
    password_nueva_repetir: str = Form(...),
    usuario: dict = Depends(_usuario_actual),
    _csrf: None = Depends(verificar_csrf),
):
    if not bcrypt.checkpw(password_actual.encode(), usuario["password_hash"].encode()):
        return RedirectResponse(url="/dashboard/perfil?error=La+contraseña+actual+no+es+correcta", status_code=303)
    if password_nueva != password_nueva_repetir:
        return RedirectResponse(url="/dashboard/perfil?error=Las+contraseñas+nuevas+no+coinciden", status_code=303)
    motivo = validar_password(password_nueva, username=usuario["username"], nombre=usuario.get("nombre"))
    if motivo:
        return RedirectResponse(url="/dashboard/perfil?error=" + quote_plus(motivo), status_code=303)

    await cambiar_password(usuario["username"], usuario["negocio_id"], password_nueva)
    return RedirectResponse(url="/dashboard/perfil?ok=Contraseña+actualizada+correctamente", status_code=303)


# ── Catálogo de productos (API JSON del panel — sub-bloque b) ──────────────
#
# Todas las escrituras son POST (ni PUT/PATCH/DELETE), igual que el resto del
# panel: la sesión se valida por cookie y el CSRF por token de formulario, y
# ese esquema solo cubre POST. Las lecturas son GET y las puede hacer
# cualquier rol autenticado — el catálogo es información de trabajo diaria de
# los asesores; escribirlo es administración, y queda en "admin".


def _capacidades_de(rol: str) -> list[str]:
    """Qué puede hacer este rol, en el vocabulario del producto — derivado de
    los roles que las rutas de este mismo archivo ya exigen hoy, no de una
    tabla de permisos nueva. Sirve para que un frontend externo (Next.js)
    pinte u oculte acciones sin tener que replicar la lógica de roles, pero
    NO es el control de acceso: el que manda sigue siendo `requiere_rol` en
    cada ruta. Un cliente que mienta sobre sus capacidades igual recibe 403."""
    vision_total = rol in ROLES_CON_VISION_TOTAL
    es_admin = rol == "admin"
    # "catalogo.*" es la librería de archivos/PDF (/dashboard/catalogos), ya
    # existente — "productos:*" es el catálogo de precios (Producto), nuevo
    # con este vertical. Nombres a propósito distintos para no repetir la
    # colisión que ya se resolvió en el naming de las pantallas.
    #
    # Convención nueva "namespace:accion" (dos puntos), la que estrenó
    # "productos:*" y que usa la Nueva Experiencia (Next.js). Las capacidades
    # legacy con punto NO se migran: conviven, porque el panel HTML y sus
    # consumidores actuales ya las leen. Mapping legacy -> nuevo, para cuando
    # se unifiquen en un solo vocabulario:
    #     leads.ver_asignados  ->  pipeline:ver + leads:ver   (alcance propio)
    #     leads.ver_todos      ->  pipeline:ver + leads:ver   (alcance total)
    #     leads.asignar        ->  leads:reasignar
    #     (sin legacy)         ->  leads:editar   (POST /lead/{tel}/resultado)
    #     (sin legacy)         ->  closewon:ver / closewon:crear (POST /lead/{tel}/venta)
    # El alcance (propio vs. total) no se codifica en el nombre de la
    # capacidad nueva: lo resuelve el servidor en cada consulta (ver
    # _alcance_pipeline), y el cliente lo pide con `alcance=`.
    capacidades = [
        "leads.ver_asignados", "catalogo.ver", "metricas.ver", "productos:ver",
        "pipeline:ver", "leads:ver", "leads:editar", "closewon:ver", "closewon:crear",
    ]
    if vision_total:
        capacidades += [
            "leads.ver_todos", "leads.asignar", "asesores.gestionar", "metricas.exportar", "campanas.ver",
            "leads:reasignar",
            # Calendario de negocio (2026-10-12, decisión D1/D2 del dueño): el supervisor LEE siempre y ESCRIBE solo
            # hacia adelante (las guardas de día pasado y año no verificado viven en las rutas, no acá). Es una
            # capacidad operativa propia: NO implica "configuracion:ver", que sigue siendo solo del admin.
            "calendario:ver", "calendario:editar",
        ]
    if es_admin:
        capacidades += [
            "usuarios.crear", "campanas.gestionar", "canales.gestionar", "catalogo.gestionar", "prompt.promover",
            "productos:crear", "productos:editar", "productos:activar", "productos:importar",
            # Gate de unificación de permisos (Nueva Experiencia): visibilidad
            # del módulo "Configuración" en el sidebar — mismo patrón namespace
            # "modulo:accion" que ya usan productos:*/pipeline:ver/leads:*, no
            # una tabla de permisos aparte.
            #
            # GATE 4.2 (Decisión 4 de Gate 4.1, cerrada): esta sigue siendo la
            # ÚNICA capacidad de todo el módulo Configuración — se evaluaron
            # `negocio:editar`/`gabi:editar`/`canales:editar` y NO se crearon.
            # MPA §9 hace de Configuración un módulo binario (Admin: Completo
            # · Supervisor/Asesor: Sin acceso, sin ningún nivel de lectura
            # intermedio) — a diferencia de Catálogo/Campañas, donde SÍ hace
            # falta separar `:ver` de `:editar` porque un rol ve y otro edita.
            # Acá no existe ese caso: quien puede ver, siempre puede editar, y
            # quien no puede ver, tampoco necesita un candado de edición
            # aparte. Agregar capacidades ahí sería exactamente lo que Gate
            # 4.2 §4 pide no hacer: "no crear permisos redundantes".
            "configuracion:ver",
            # Gate UX Equipo (Decisión 5): distinta de "asesores.gestionar"
            # (arriba, vision_total = admin+supervisor, que solo cubre VER el
            # equipo completo — Supervisor: "Solo lectura de carga/
            # disponibilidad", MPA §9). Resetear contraseña / editar nivel
            # son acciones administrativas de cuenta, admin-únicamente — se
            # necesita una capacidad propia porque ninguna existente
            # significaba exactamente esto ("usuarios.crear" es solo alta de
            # cuentas nuevas, no cubre acciones sobre cuentas existentes).
            "equipo:administrar",
        ]
    if rol == "asesor":
        capacidades.append("disponibilidad.toggle")
    return sorted(capacidades)


@router.get("/sesion")
async def sesion_actual(request: Request, usuario: dict = Depends(_usuario_actual)):
    """Quién soy, qué puedo hacer y con qué token escribo — el primer llamado
    que hace un frontend externo al montar. No genera nada nuevo: reutiliza la
    resolución de sesión de ServicioIdentidad (que además siembra el
    csrf_token de la sesión de forma lazy) y el mismo token que ya viaja como
    <meta name="csrf-token"> en el panel HTML."""
    return JSONResponse({
        # Gate 5.3 — corrección pequeña ya identificada en rondas anteriores:
        # `usuario["negocio_id"]` ya está disponible acá (viene de
        # ServicioIdentidad -> obtener_usuario, poblado desde Gate 5.2) pero
        # se descartaba al armar esta respuesta — es el bloqueador exacto del
        # futuro chip de contexto Negocio/Unidad (Gate 5.6). El BFF de
        # maiek-frontend (app/api/sesion/route.ts) ya es passthrough puro, no
        # necesita cambios para que este campo llegue al cliente.
        "usuario": {
            "username": usuario["username"], "rol": usuario["rol"], "negocio_id": usuario.get("negocio_id"),
            "nombre": usuario.get("nombre") or usuario["username"],
            # Punto 2 (2026-09-29): solo tiene sentido para un asesor — el
            # switch de disponibilidad de la Nueva Experiencia lo necesita
            # para saber cómo renderizarse al montar, sin esperar a que el
            # propio asesor lo togglee una vez para recién ahí saber su
            # estado real.
            "disponible": usuario.get("disponible") if usuario["rol"] == "asesor" else None,
        },
        "capacidades": _capacidades_de(usuario["rol"]),
        "csrf_token": request.session.get("csrf_token", ""),
    })


def _parsear_cuotas(cuotas) -> dict:
    """Las cuotas llegan como dict ({"12": "160.01", ...}) en el body JSON de
    Productos — se acepta también como string JSON por compatibilidad con el
    mismo patrón que usa `lineas_venta` en el cierre de venta."""
    if cuotas is None or cuotas == "":
        return {}
    if isinstance(cuotas, str):
        if not cuotas.strip():
            return {}
        try:
            cuotas = json.loads(cuotas)
        except (json.JSONDecodeError, TypeError, ValueError):
            raise HTTPException(status_code=400, detail="El campo cuotas no es un JSON válido")
    if not isinstance(cuotas, dict):
        raise HTTPException(status_code=400, detail="El campo cuotas debe ser un objeto {plazo: valor}")
    plazos_invalidos = [p for p in cuotas if str(p) not in PLAZOS_CUOTAS_CATALOGO]
    if plazos_invalidos:
        raise HTTPException(status_code=400, detail=f"Plazos de cuota no válidos: {', '.join(map(str, plazos_invalidos))}")
    return {str(p): str(v).strip() for p, v in cuotas.items() if str(v).strip()}


def _datos_producto_del_form(form: dict) -> dict:
    """Solo los campos realmente enviados llegan a memory.py — así una edición
    parcial no borra en silencio los campos que el formulario no incluyó
    (_diferencias_producto ignora las claves ausentes)."""
    datos = {campo: form[campo] for campo in CAMPOS_NEGOCIO_PRODUCTO if form.get(campo) is not None}
    if form.get("cuotas") is not None:
        datos["cuotas"] = _parsear_cuotas(form["cuotas"])
    return datos


CAMPOS_FEE_PRODUCTO = ("fee_prv", "fee_clda")


def _sin_fee_si_no_es_admin(producto: dict, usuario: dict) -> dict:
    """Los fee (proveedor y Cálidda) son de uso interno de la administración: los demás roles no los reciben
    (ni en el listado, ni en la ficha), así no dependen de que el frontend los esconda."""
    if usuario.get("rol") == "admin":
        return producto
    return {k: v for k, v in producto.items() if k not in CAMPOS_FEE_PRODUCTO}


@router.get("/productos")
async def listar_productos_ruta(
    q: str = "", canal: str = "", marca: str = "", tipo: str = "", activo: str = "",
    pagina: int = 1, por_pagina: int = 20,
    usuario: dict = Depends(_usuario_actual),
):
    """Catálogo paginado. `activo` acepta "1"/"0" (o vacío = todos) porque un
    query param nunca es un bool real; se traduce a True/False/None antes de
    bajar a memory.py."""
    activo_filtro = None
    if activo not in ("", None):
        activo_filtro = activo.lower() in ("1", "true", "si", "sí")
    por_pagina = min(max(1, por_pagina), 200)  # tope para que un cliente no pida el catálogo entero por accidente
    productos, total = await listar_productos(
        {"q": q, "canal": canal, "marca": marca, "tipo": tipo, "activo": activo_filtro},
        pagina=pagina, por_pagina=por_pagina, negocio_id=usuario["negocio_id"],
    )
    return JSONResponse({
        "productos": [_sin_fee_si_no_es_admin(p, usuario) for p in productos], "total": total,
        "pagina": max(1, pagina), "por_pagina": por_pagina,
    })


@router.get("/productos/{id}")
async def obtener_producto_ruta(id: int, usuario: dict = Depends(_usuario_actual)):
    producto = await obtener_producto(id, usuario["negocio_id"])
    if producto is None:
        raise HTTPException(status_code=404, detail="Producto no encontrado")
    return JSONResponse(_sin_fee_si_no_es_admin(producto, usuario))


@router.get("/productos/{id}/historial")
async def historial_producto_ruta(id: int, usuario: dict = Depends(_usuario_actual)):
    """Bitácora del producto — quién cambió qué y cuándo. Visible para todos
    los roles a propósito: un asesor que ve un precio distinto al de ayer
    necesita poder confirmar que cambió de verdad y no es un error suyo
    (Explainability First)."""
    if await obtener_producto(id, usuario["negocio_id"]) is None:
        raise HTTPException(status_code=404, detail="Producto no encontrado")
    historial = await listar_historial_producto(id)
    if usuario.get("rol") != "admin":
        historial = [h for h in historial if h["campo"] not in CAMPOS_FEE_PRODUCTO]
    return JSONResponse({"historial": historial})


def _version_del_body(body: dict) -> int:
    """Mismo 422 que daba la validación automática de FastAPI sobre
    `Form(...)`, ahora a mano porque el body es JSON, no form-encoded."""
    if "version" not in body:
        raise HTTPException(status_code=422, detail="Falta 'version' en el cuerpo de la petición")
    try:
        return int(body["version"])
    except (TypeError, ValueError):
        raise HTTPException(status_code=422, detail="'version' debe ser un entero")


@router.post("/productos")
async def crear_producto_ruta(
    request: Request,
    usuario: dict = Depends(servicio_identidad.requiere_rol("admin")),
    _csrf: None = Depends(verificar_csrf),
):
    """Body JSON (no form-encoded): Productos es la API pensada para el BFF
    de Next.js, a diferencia del resto de este archivo que sirve HTML."""
    body = await request.json()
    descripcion = (body.get("descripcion") or "").strip()
    if not descripcion:
        raise HTTPException(status_code=400, detail="La descripción es obligatoria")
    datos = _datos_producto_del_form(body)
    producto = await crear_producto(datos, autor=usuario["nombre"], negocio_id=usuario["negocio_id"])
    return JSONResponse({"ok": True, "producto": producto}, status_code=201)


@router.post("/productos/{id}/editar")
async def editar_producto_ruta(
    id: int,
    request: Request,
    usuario: dict = Depends(servicio_identidad.requiere_rol("admin")),
    _csrf: None = Depends(verificar_csrf),
):
    """Concurrencia optimista, mismo criterio que la edición de un lead: si
    alguien más guardó desde que se abrió el formulario, no se aplica nada y
    se responde 409 con la versión vigente, para que el cliente muestre el
    conflicto en vez de pisar el cambio ajeno (Human Decision Gate)."""
    body = await request.json()
    version = _version_del_body(body)
    datos = _datos_producto_del_form({k: v for k, v in body.items() if k != "version"})
    producto = await editar_producto(
        id, datos, version_esperada=version, autor=usuario["nombre"], negocio_id=usuario["negocio_id"],
    )
    if producto is None:
        # None cubre tres casos distintos (no existe / de otro Negocio /
        # conflicto de versión); se separan acá para no devolver un 409 por
        # un producto inexistente o ajeno.
        actual = await obtener_producto(id, usuario["negocio_id"])
        if actual is None:
            raise HTTPException(status_code=404, detail="Producto no encontrado")
        return JSONResponse(
            {
                "ok": False,
                "detail": "Alguien más modificó este producto mientras lo editabas. Revisa los datos actuales antes de volver a guardar.",
                "version_actual": actual["version"],
            },
            status_code=409,
        )
    return JSONResponse({"ok": True, "producto": producto})


@router.post("/productos/{id}/toggle")
async def toggle_producto_ruta(
    id: int,
    request: Request,
    usuario: dict = Depends(servicio_identidad.requiere_rol("admin")),
    _csrf: None = Depends(verificar_csrf),
):
    """Activa/desactiva — nunca borra. Mismo manejo de versión/409 que editar."""
    body = await request.json()
    version = _version_del_body(body)
    producto = await toggle_producto(
        id, version_esperada=version, autor=usuario["nombre"], negocio_id=usuario["negocio_id"],
    )
    if producto is None:
        actual = await obtener_producto(id, usuario["negocio_id"])
        if actual is None:
            raise HTTPException(status_code=404, detail="Producto no encontrado")
        return JSONResponse(
            {
                "ok": False,
                "detail": "Alguien más modificó este producto mientras lo editabas. Revisa los datos actuales antes de volver a guardar.",
                "version_actual": actual["version"],
            },
            status_code=409,
        )
    return JSONResponse({"ok": True, "producto": producto})


@router.post("/productos/importar")
async def importar_productos_ruta(
    archivo: UploadFile = File(...),
    usuario: dict = Depends(servicio_identidad.requiere_rol("admin")),
    _csrf: None = Depends(verificar_csrf),
):
    """Importación masiva desde la lista de precios en CSV. Sincroniza por
    diferencias (ver importar_catalogo_desde_csv): no borra el catálogo, no
    rompe los ids y deja bitácora de cada campo que cambió."""
    if not (archivo.filename or "").lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail="Solo se acepta un archivo .csv")

    contenido = await archivo.read()
    if len(contenido) > TAMANO_MAXIMO_ARCHIVO_MB * 1024 * 1024:
        raise HTTPException(status_code=400, detail=f"El archivo supera los {TAMANO_MAXIMO_ARCHIVO_MB}MB permitidos")
    try:
        contenido.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise HTTPException(
            status_code=400,
            detail="El CSV no está en UTF-8. Vuelve a exportarlo desde Excel como «CSV UTF-8 (delimitado por comas)».",
        )

    # A disco temporal: importar_catalogo_desde_csv recibe una ruta (el mismo
    # contrato que usa el arranque del proceso con el CSV del repo), y el
    # archivo se borra apenas termina — no es un adjunto que haya que guardar.
    with tempfile.NamedTemporaryFile("wb", suffix=".csv", delete=False) as tmp:
        tmp.write(contenido)
        ruta_tmp = tmp.name
    try:
        resumen = await importar_catalogo_desde_csv(ruta_tmp, negocio_id=usuario["negocio_id"], autor=usuario["nombre"])
    finally:
        os.unlink(ruta_tmp)

    logger.info("Importación de catálogo por %s: %s", usuario["username"], resumen)
    # Avisos NO bloqueantes: filas que dejarían a Gabi sin un dato que necesita (capacidad, precio...). La
    # importación ya se hizo; esto solo le dice al admin qué corregir.
    filas = [_fila_csv_a_datos(f) for f in csv.DictReader(io.StringIO(contenido.decode("utf-8-sig")))]
    calidad = avisos_de_calidad_catalogo(filas, excluidas=FILAS_CATALOGO_EXCLUIDAS)
    return JSONResponse({"ok": True, "resumen": resumen, "calidad": calidad})
