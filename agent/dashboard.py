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

import html
import json
import logging
import os
import secrets
import subprocess
import tempfile
import uuid
import bcrypt
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException, Form, Request, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse, Response, FileResponse

from agent.memory import (
    listar_leads, obtener_lead, obtener_historial, actualizar_lead,
    obtener_usuario, listar_asesores, guardar_mensaje, obtener_ultimo_mensaje,
    asignar_asesor_a_lead, marcar_lead_visto, actualizar_disponibilidad, actualizar_nivel_asesor,
    listar_campanas, crear_campana, actualizar_campana, contar_leads_por_campana, eliminar_campana,
    cambiar_password, contar_leads_activos, RESULTADOS_CERRADOS, listar_leads_agendados,
    obtener_configuracion, guardar_configuracion,
    crear_archivo_adjunto, obtener_archivo_adjunto, listar_archivos_reutilizables,
    eliminar_archivo_reutilizable, obtener_telefono_de_archivo,
    listar_lineas_venta, listar_lineas_venta_de_muchos, guardar_lineas_venta,
    listar_canales_whatsapp, crear_canal_whatsapp, actualizar_canal_whatsapp,
)

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


async def _mapa_canales() -> dict:
    """Nombre + color de cada canal de WhatsApp, indexado por phone_number_id
    — para pintar el badge de canal en leads/conversaciones sin repetir la
    consulta en cada fila."""
    canales = await listar_canales_whatsapp()
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
from agent.campanas import resolver_promo, generar_link_whatsapp
from agent.brain import cargar_system_prompt
from agent.tools import obtener_producto_por_codigo, buscar_productos
from agent.notificaciones import notificar_solicitud_reseteo, notificar_lead_derivado
from agent.asignacion import asignar_lead_pendiente_a_asesor, UMBRAL_SENIOR_DEFAULT, UMBRAL_INTERMEDIO_DEFAULT
from agent.providers import obtener_proveedor

logger = logging.getLogger("agentkit")

router = APIRouter(prefix="/dashboard")

# Carpeta donde viven los archivos adjuntos (proformas/catálogos) enviados
# por los asesores. En Railway apunta a un Volume persistente (el disco del
# contenedor es efímero — se pierde en cada redeploy); en local, una carpeta
# normal alcanza. Ver ArchivoAdjunto en agent/memory.py para los metadatos.
ARCHIVOS_DIR = os.getenv("ARCHIVOS_DIR", "data/archivos")
EXTENSIONES_ARCHIVO_PERMITIDAS = {".pdf", ".jpg", ".jpeg", ".png"}
TAMANO_MAXIMO_ARCHIVO_MB = 20  # margen conservador bajo los límites de Meta (100MB doc / 5MB imagen)

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
    "servicio_postventa", "cartera_fnb",
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
    "servicio_postventa": "Servicio Postventa",
    "cartera_fnb": "Cartera FNB",
}
MODALIDADES_PAGO = ["financiado", "contado"]
CUOTAS_DISPONIBLES = ["12", "24", "36"]
MEDIO_PAGO_FINANCIADO = "Recibo de gas"
MEDIOS_PAGO_CONTADO = ["QR", "Link de pago", "Abono a cuenta corriente", "Otro"]
ROLES_CON_VISION_TOTAL = ("admin", "supervisor")

COLOR_RESULTADO = {
    "agendado": "#2563eb",
    "vendido": "#16a34a",
    "no_interesado": "#ef4444",
    "no_califica": "#e11d48",
    "no_es_cliente_calidda": "#b91c1c",
    "producto_sin_stock": "#f97316",
    "otro": "#6b7280",
    "consulta_atc": "#7c3aed",
    "sin_saldo": "#d97706",
    "servicio_postventa": "#0d9488",
    "cartera_fnb": "#4f46e5",
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


class NoAutenticado(Exception):
    """Se lanza cuando no hay una sesión válida; el handler redirige al login."""
    pass


async def _usuario_actual(request: Request) -> dict:
    username = request.session.get("username")
    if not username:
        raise NoAutenticado()
    usuario = await obtener_usuario(username)
    if usuario is None:
        raise NoAutenticado()
    return usuario


def _verificar_acceso_lead(usuario: dict, lead: dict):
    """Un asesor solo puede ver/editar sus propios leads asignados."""
    if usuario["rol"] in ROLES_CON_VISION_TOTAL:
        return
    if lead.get("asesor_asignado") != usuario["username"]:
        raise HTTPException(status_code=403, detail="No tienes acceso a este lead")


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

  .avatar {
    display: inline-flex; align-items: center; justify-content: center;
    border-radius: 50%; font-weight: 700; color: white; flex-shrink: 0;
    background: linear-gradient(135deg, var(--gaso-azul), var(--gaso-secundario));
  }

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
  .badge-agendados { display: inline-flex; align-items: center; gap: 5px; background: #e6f1fb; color: #0c447c; padding: 3px 10px; border-radius: 999px; font-size: .76rem; }
  .badge-agendados strong { color: #0c447c; font-size: .78rem; }
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
       Maçllec AI") no entra en el navbar angosto de mobile sin romper el
       alto fijo de 58px que asume .rail-estados más abajo — se oculta y
       queda solo "Gaso+", igual que antes del rebrand. */
    .brand-subtitulo { display: none; }

    /* Con un chat abierto: solo el chat se ve, a pantalla completa */
    body.pagina-chat .rail-estados,
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
        f"{total:.0f}" if todos_numericos
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


async def _adjuntar_resumen_ventas(leads: list[dict]) -> list[dict]:
    """Sobreescribe producto_vendido/marca_venta/proveedor_venta/precio_venta
    de cada lead con el resumen de sus líneas de venta (una consulta para
    todos los leads, no una por fila) — para que la tabla/exportación, que
    ya leen esos 4 campos, muestren el cierre real sin cambiar su código."""
    telefonos = [l["telefono"] for l in leads]
    lineas_por_lead = await listar_lineas_venta_de_muchos(telefonos)
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
    if usuario:
        disp_html = ""
        if usuario["rol"] == "asesor":
            en_linea = usuario.get("disponible", True)
            disp_html = (
                '<form method="post" action="/dashboard/disponibilidad" class="d-inline m-0">'
                f'<button type="submit" class="link-btn badge '
                f'{"text-bg-success" if en_linea else "text-bg-secondary"}">'
                f'{"🟢 Disponible" if en_linea else "⚪ No disponible"}</button></form>'
            )
        gestion_html = ""
        if usuario["rol"] in ROLES_CON_VISION_TOTAL:
            gestion_html = (
                '<a href="/dashboard/metricas" data-ajax="1" class="link-light small text-decoration-none"><i class="bi bi-graph-up-arrow"></i> Métricas</a>'
                '<a href="/dashboard/asesores" data-ajax="1" class="link-light small text-decoration-none"><i class="bi bi-people-fill"></i> Gestionar asesores</a>'
            )
        if usuario["rol"] == "admin":
            gestion_html += '<a href="/dashboard/campanas" data-ajax="1" class="link-light small text-decoration-none"><i class="bi bi-megaphone-fill"></i> Campañas</a>'
            gestion_html += '<a href="/dashboard/catalogos" data-ajax="1" class="link-light small text-decoration-none"><i class="bi bi-folder-fill"></i> Catálogos</a>'
            gestion_html += '<a href="/dashboard/canales-whatsapp" data-ajax="1" class="link-light small text-decoration-none"><i class="bi bi-whatsapp"></i> Canales de WhatsApp</a>'
        topbar = f"""
        <nav class="navbar navbar-gaso navbar-dark px-3 py-2">
            <a class="navbar-brand mb-0 d-flex align-items-center gap-2" href="/dashboard" data-ajax="1">
                <i class="bi bi-droplet-fill" style="color:var(--gaso-secundario)"></i>
                <span class="d-flex flex-column lh-1">
                    <span>Gaso<span class="plus">+</span></span>
                    <span class="fw-normal opacity-75 brand-subtitulo" style="font-size:.62rem;letter-spacing:.02em">Commercial Operating System <span class="opacity-50">&middot; Powered by Maçllec <span style="font-weight:300">AI</span></span></span>
                </span>
            </a>
            <div class="d-flex align-items-center gap-3 text-white-50 small">
                <a href="/dashboard/perfil" data-ajax="1" class="text-white d-flex align-items-center gap-2 text-decoration-none">
                    {_avatar(usuario['nombre'], 30, 'avatar-sm')}
                    {html.escape(usuario['nombre'])} &middot; {html.escape(usuario['rol'])}
                </a>
                {disp_html}
                {gestion_html}
                <form method="post" action="/dashboard/logout" class="d-inline m-0">
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
    return f"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(titulo)} — Gaso+ Panel</title>
{BOOTSTRAP_CSS}
{BOOTSTRAP_ICONS}
{FUENTE_INTER}
<style>{ESTILOS_PROPIOS}</style>
</head>
<body class="{'pagina-chat' if es_chat else ''}">
<div id="barra-carga"></div>
{topbar}
{boton_filtros_movil}
<div id="contenido-app">{cuerpo}</div>
{BOOTSTRAP_JS}
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

    function navegarAjax(url, agregarHistorial) {{
        iniciar();
        fetch(url, {{ headers: {{ 'X-Panel-Fragment': '1' }} }})
            .then(function(r) {{
                if (!r.ok) throw new Error('HTTP ' + r.status);
                var titulo = r.headers.get('X-Page-Title');
                var esChat = r.headers.get('X-Page-Chat') === '1';
                return r.text().then(function(html) {{ return {{ html: html, titulo: titulo, esChat: esChat }}; }});
            }})
            .then(function(datos) {{
                contenedor.innerHTML = datos.html;
                ejecutarScripts(contenedor);
                if (datos.titulo) document.title = datos.titulo + ' — Gaso+ Panel';
                document.body.classList.toggle('pagina-chat', datos.esChat);
                if (agregarHistorial) history.pushState({{ ajax: true }}, '', url);
                window.scrollTo(0, 0);
                terminar();
            }})
            .catch(function() {{
                // Si algo falla (red, error del servidor), no te deja colgado:
                // navega normal como si nunca hubiera intentado ir por AJAX.
                window.location.href = url;
            }});
    }}

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
    leads_todos = await listar_leads(asesor_asignado=None if vision_total else usuario["username"])
    mapa_canales = await _mapa_canales()
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

    if estado_filtro == "con_gabi":
        leads_filtrados = leads_con_gabi
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
        "mapa_canales": mapa_canales,
        "canal_filtro": canal_filtro,
    }


async def _renderizar_rail_estados(usuario: dict, datos: dict, estado_filtro: str, asesor_filtro: str, canal_filtro: str = "") -> str:
    vision_total = datos["vision_total"]
    conteos = datos["conteos"]

    nav_estados = "".join(
        _item_nav_estado(ETIQUETAS_ESTADO[e], ICONO_ESTADO[e][0], conteos[e], e, estado_filtro == e and not asesor_filtro)
        for e in ESTADOS_DERIVADO
    )
    item_todos = _item_nav_estado(
        "Todos", "bi-collection-fill", len(datos["leads_derivados"]), "todos", estado_filtro == "todos" and not asesor_filtro
    )
    # Solo admin/supervisor lo ven — para un asesor normal esto siempre daría
    # 0 (listar_leads ya solo le trae SUS leads asignados, y un lead que
    # Gabi todavía atiende sola no tiene asesor asignado), así que mostrarlo
    # solo agregaría ruido sin ningún caso real detrás.
    item_con_gabi = ""
    if vision_total:
        item_con_gabi = _item_nav_estado(
            "Con Gabi", "bi-robot", len(datos["leads_con_gabi"]), "con_gabi", estado_filtro == "con_gabi" and not asesor_filtro
        )

    equipo_html = ""
    if vision_total:
        asesores = await listar_asesores()
        filas_equipo = []
        if estado_filtro == "todos":
            # Sin filtro de estado: se muestra la carga activa total de cada asesor.
            for a in asesores:
                carga = await contar_leads_activos(a["username"])
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
        <div class="sidebar-subtitulo">EQUIPO</div>
        {''.join(filas_equipo) or '<p class="px-3 text-muted small">Ningún asesor tiene leads en este estado.</p>'}
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

    return f"""
    <div class="rail-estados border-end d-flex flex-column" id="rail-estados">
        <div class="sidebar-subtitulo d-flex justify-content-between align-items-center pe-2 d-md-none">
            <span>&nbsp;</span>
            <button type="button" class="btn-close" style="font-size:.65rem" onclick="document.getElementById('rail-estados').classList.remove('abierto')"></button>
        </div>
        {canales_html}
        {_subtitulo_contraible("CONVERSACIONES", "conversaciones-contenido")}
        <div id="conversaciones-contenido">
            <div class="estado-nav pb-2">
                {item_todos}
                {nav_estados}
                {item_con_gabi}
            </div>
            {equipo_html}
        </div>
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

    items = []
    for lead in leads_filtrados:
        ultimo = await obtener_ultimo_mensaje(lead["telefono"])
        preview = (ultimo["content"][:60] + "…") if ultimo and len(ultimo["content"]) > 60 else (ultimo["content"] if ultimo else "")
        hora = lead["actualizado"].strftime("%d/%m %H:%M")
        activo = " activo" if lead["telefono"] == telefono_activo else ""
        es_nuevo = (not vision_total) and not lead.get("visto_asesor", True)
        badge_nuevo = ' <span class="badge text-bg-warning">Nuevo</span>' if es_nuevo else ""
        badge_canal = _badge_canal(lead.get("numero_whatsapp_id"), mapa_canales, compacto=True)
        nombre_lead = lead.get("nombre") or lead["telefono"]
        items.append(f"""
        <a class="list-group-item list-group-item-action convo-item d-flex gap-2 py-1{activo}" href="/dashboard/lead/{html.escape(lead['telefono'])}{query}" data-ajax="1">
            {_avatar(nombre_lead, 30)}
            <div class="flex-grow-1 overflow-hidden">
                <div class="d-flex justify-content-between align-items-center">
                    <span class="fw-semibold" style="font-size:13.5px">{html.escape(nombre_lead)}{badge_nuevo}</span>
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


def _barra_resumen(datos: dict, asesores: list[dict]) -> str:
    """Franja fija y delgada debajo del navbar con el avance de Gabi y del
    equipo humano de un vistazo — visible siempre, sin ocupar espacio de
    las columnas de la bandeja."""
    leads_todos = datos["leads_todos"]
    con_gabi = sum(1 for l in leads_todos if _estado_conversacion(l) in ESTADOS_GABI)
    conteos = datos["conteos"]
    disponibles = sum(1 for a in asesores if a.get("disponible"))
    # Los "agendados" son casos sensibles al tiempo (hay una cita con el
    # cliente) — se resaltan con su propio contador en vez de mezclarse
    # dentro de "En atención", para que un supervisor los vea de un vistazo.
    agendados = sum(1 for l in leads_todos if l.get("resultado") == "agendado")

    pares = [
        ("Con Gabi", con_gabi),
        ("Pendiente asignar", conteos.get("pendiente_asignar", 0)),
        ("Asignados", conteos.get("asignado", 0)),
        ("En atención", conteos.get("en_atencion", 0)),
        ("Resueltos", conteos.get("resuelto", 0)),
        ("Asesores disponibles", f"{disponibles}/{len(asesores)}"),
    ]
    items = "".join(f'<span>{html.escape(etq)}: <strong>{val}</strong></span>' for etq, val in pares)
    agendados_html = (
        '<span class="badge-agendados">'
        '<i class="bi bi-calendar-event"></i> Agendados: '
        f'<strong>{agendados}</strong></span>'
    )
    return f'<div class="barra-resumen">{items}{agendados_html}</div>'


# ── Login / Logout ────────────────────────────────────────────────────

@router.get("/login", response_class=HTMLResponse)
async def login_form(error: str = ""):
    mensaje_error = f'<div class="alert alert-danger py-2 small">{html.escape(error)}</div>' if error else ""
    cuerpo = f"""
    <div class="login-shell d-flex align-items-center justify-content-center">
        <div class="card login-card shadow p-4" style="width:380px;">
            <div class="text-center mb-3">
                <div class="avatar mx-auto mb-2" style="width:56px;height:56px;font-size:24px"><i class="bi bi-droplet-fill"></i></div>
                <h4 class="mb-0">Gaso<span style="color:var(--gaso-secundario)">+</span></h4>
                <div class="text-muted small">Commercial Operating System</div>
                <div class="text-muted" style="font-size:.68rem;opacity:.7">Powered by Maçllec <span style="font-weight:300">AI</span></div>
            </div>
            {mensaje_error}
            <form method="post" action="/dashboard/login">
                <div class="mb-3">
                    <label class="form-label small text-muted">Usuario</label>
                    <input type="text" name="username" class="form-control" required autofocus>
                </div>
                <div class="mb-3">
                    <label class="form-label small text-muted">Contraseña</label>
                    <input type="password" name="password" class="form-control" required>
                </div>
                <button type="submit" class="btn btn-primary w-100">Ingresar</button>
            </form>
            <div class="text-center mt-3">
                <a href="/dashboard/recuperar" class="small text-muted text-decoration-none">¿Olvidaste tu contraseña?</a>
            </div>
        </div>
    </div>
    """
    return _pagina("Ingresar", None, cuerpo)


@router.get("/recuperar", response_class=HTMLResponse)
async def recuperar_form(enviado: str = ""):
    if enviado:
        cuerpo_mensaje = (
            '<div class="alert alert-success py-2 small">'
            'Si el usuario existe, ya avisamos a un administrador para que te ayude a restablecer tu contraseña.'
            '</div>'
        )
        formulario = '<a href="/dashboard/login" class="btn btn-outline-secondary w-100">Volver a ingresar</a>'
    else:
        cuerpo_mensaje = '<p class="text-muted small">Escribe tu usuario del panel — le avisamos a un administrador para que te genere una contraseña nueva.</p>'
        formulario = """
            <form method="post" action="/dashboard/recuperar">
                <div class="mb-3">
                    <label class="form-label small text-muted">Usuario</label>
                    <input type="text" name="username" class="form-control" required autofocus>
                </div>
                <button type="submit" class="btn btn-primary w-100">Avisar a un administrador</button>
            </form>
            """
    cuerpo = f"""
    <div class="login-shell d-flex align-items-center justify-content-center">
        <div class="card login-card shadow p-4" style="width:380px;">
            <div class="text-center mb-3">
                <div class="avatar mx-auto mb-2" style="width:56px;height:56px;font-size:24px"><i class="bi bi-key-fill"></i></div>
                <h4 class="mb-0">Recuperar acceso</h4>
            </div>
            {cuerpo_mensaje}
            {formulario}
            <div class="text-center mt-3">
                <a href="/dashboard/login" class="small text-muted text-decoration-none">Volver a ingresar</a>
            </div>
        </div>
    </div>
    """
    return _pagina("Recuperar contraseña", None, cuerpo)


@router.post("/recuperar")
async def recuperar_submit(username: str = Form(...)):
    usuario = await obtener_usuario(username.strip())
    if usuario is not None:
        await notificar_solicitud_reseteo(usuario["username"])
    # Mismo mensaje exista o no el usuario, para no revelar qué usuarios son válidos.
    return RedirectResponse(url="/dashboard/recuperar?enviado=1", status_code=303)


@router.post("/login")
async def login_submit(request: Request, username: str = Form(...), password: str = Form(...)):
    usuario = await obtener_usuario(username)
    credenciales_validas = usuario is not None and bcrypt.checkpw(
        password.encode(), usuario["password_hash"].encode()
    )
    if not credenciales_validas:
        return RedirectResponse(url="/dashboard/login?error=Usuario+o+contraseña+incorrectos", status_code=303)
    request.session["username"] = usuario["username"]
    return RedirectResponse(url="/dashboard", status_code=303)


@router.post("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/dashboard/login", status_code=303)


# ── Bandeja principal (sin conversación seleccionada) ─────────────────

async def _contenido_metricas(leads: list[dict]) -> str:
    """Embudo + tabla completa de leads + exportar — página separada de Métricas
    (admin/supervisor), fuera de la bandeja operativa de 3 columnas."""
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

    return f"""
    <div class="d-flex justify-content-between align-items-center mb-3">
        {_titulo_seccion('bi-graph-up-arrow', 'Métricas')}
        <div class="d-flex gap-2">
            <a href="/dashboard/metricas/exportar.csv" class="btn btn-sm btn-outline-primary"><i class="bi bi-download"></i> CSV</a>
            <a href="/dashboard/metricas/exportar.xlsx" class="btn btn-sm btn-outline-primary"><i class="bi bi-file-earmark-excel"></i> Excel</a>
        </div>
    </div>

    {_titulo_seccion('bi-funnel-fill', 'Embudo de ventas (con Gabi)')}
    <div class="row row-cols-2 row-cols-md-3 row-cols-lg-5 g-2 mb-3">{tarjetas}</div>

    {_titulo_seccion('bi-person-check-fill', 'Estado con asesor humano (derivados)')}
    <div class="row row-cols-2 row-cols-md-4 g-2 mb-3">{tarjetas_derivado}</div>

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
async def metricas(request: Request, usuario: dict = Depends(_usuario_actual)):
    if usuario["rol"] not in ROLES_CON_VISION_TOTAL:
        raise HTTPException(status_code=403, detail="Solo un supervisor puede ver las métricas")
    sidebar = await _renderizar_sidebar(usuario, telefono_activo=None)
    leads = await _adjuntar_resumen_ventas(await listar_leads())
    panel = await _contenido_metricas(leads)
    cuerpo = f"""<div class="shell d-flex">{sidebar}<div class="main-pane flex-grow-1 p-4">{panel}</div></div>"""
    return _pagina("Métricas", usuario, cuerpo, request=request)


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


@router.get("/metricas/exportar.csv")
async def exportar_metricas_csv(usuario: dict = Depends(_usuario_actual)):
    if usuario["rol"] not in ROLES_CON_VISION_TOTAL:
        raise HTTPException(status_code=403, detail="Solo un supervisor puede exportar las métricas")
    import csv
    import io

    leads = await _adjuntar_resumen_ventas(await listar_leads())
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
async def exportar_metricas_xlsx(usuario: dict = Depends(_usuario_actual)):
    if usuario["rol"] not in ROLES_CON_VISION_TOTAL:
        raise HTTPException(status_code=403, detail="Solo un supervisor puede exportar las métricas")
    import io
    from openpyxl import Workbook
    from openpyxl.styles import Font

    leads = await _adjuntar_resumen_ventas(await listar_leads())
    filas = _filas_exportacion(leads)
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


@router.get("", response_class=HTMLResponse)
async def panel_principal(
    request: Request, usuario: dict = Depends(_usuario_actual), estado: str = "todos", asesor: str = "", canal: str = "",
):
    datos = await _datos_bandeja(usuario, estado, asesor, canal)
    rail = await _renderizar_rail_estados(usuario, datos, estado, asesor, canal)

    asesores = await listar_asesores() if datos["vision_total"] else []
    resumen = _barra_resumen(datos, asesores) if datos["vision_total"] else ""

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
        panel = _tabla_todos_los_leads(leads_tabla, datos["mapa_canales"])
        columnas = rail

    # Aviso de "Próximas citas" en la vista principal — sin correo/dominio
    # configurado todavía, esta es la notificación real: lo primero que ve
    # el asesor (o el supervisor, con las de todo el equipo) al entrar.
    aviso_citas = ""
    if estado == "todos" and not asesor:
        agendados = await listar_leads_agendados(
            asesor_asignado=None if datos["vision_total"] else usuario["username"]
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
    catalogos = await listar_archivos_reutilizables()
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

        // Este chat puede quedar reemplazado por una navegación AJAX (tabla
        // -> detalle -> chat) sin que la página se recargue — el intervalo y
        // el listener se auto-desactivan apenas su chatDiv ya no está en el
        // documento, para no seguir pidiendo mensajes de un chat que ya no
        // se ve (y no acumular listeners cada vez que se vuelve a entrar).
        const intervalo = setInterval(function() {{
            if (!document.body.contains(chatDiv)) {{ clearInterval(intervalo); return; }}
            actualizar();
        }}, 1500);
        function alCambiarVisibilidad() {{
            if (!document.body.contains(chatDiv)) {{
                document.removeEventListener('visibilitychange', alCambiarVisibilidad);
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
        if (input) {
            input.addEventListener('input', ajustarInputMensaje);
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
                    headers: {'Content-Type': 'application/x-www-form-urlencoded'},
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
                    method: 'POST'
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


async def _bloque_gestion_lead(telefono: str, lead: dict, usuario: dict) -> str:
    """Formularios de Asignación / Resultado / Cierre de venta — se muestran
    siempre junto al resumen del cliente (columna del lead), así que el POST
    siempre vuelve a la misma página del lead."""
    opciones_resultado = '<option value="">Selecciona...</option>' + "".join(
        f'<option value="{r}" {"selected" if lead.get("resultado") == r else ""}>{html.escape(ETIQUETAS_RESULTADO[r])}</option>'
        for r in RESULTADOS
    )

    bloque_asignacion = ""
    if usuario["rol"] in ROLES_CON_VISION_TOTAL:
        asesores = await listar_asesores()
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
    opciones_cuotas = "".join(
        f'<option value="{c}" {"selected" if lead.get("cuotas") == c else ""}>{c} meses</option>'
        for c in CUOTAS_DISPONIBLES
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
    {bloque_asignacion}
    <div class="card leads-card shadow-sm mb-2">
        <div class="barra-acento"></div>
        <div class="card-body p-3">
            <h6 class="text-uppercase text-muted small fw-bold mb-2">Resultado tras derivación a asesor</h6>
            <form method="post" action="/dashboard/lead/{html.escape(telefono)}/resultado" id="form-resultado">
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
                    <label class="form-label small text-muted mb-0">Cuotas</label>
                    <select name="cuotas" id="venta-cuotas" class="form-select form-select-sm">
                        <option value="">Selecciona...</option>
                        {opciones_cuotas}
                    </select>
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


async def _bloque_resumen_cliente(telefono: str, lead: dict, usuario: dict) -> str:
    """Resumen del cliente con el mismo lenguaje visual 'ejecutivo' de la
    tabla de leads (card con barra de acento, badge suave, tipografía
    compacta) — seguido de los formularios de gestión, todo en una sola
    columna que se muestra siempre junto al chat."""
    nombre_mostrado = lead.get("nombre") or "(sin nombre)"
    badge_canal = _badge_canal(lead.get("numero_whatsapp_id"), await _mapa_canales())

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
    {await _bloque_gestion_lead(telefono, lead, usuario)}
    """


@router.get("/lead/{telefono}", response_class=HTMLResponse)
async def detalle_lead(
    telefono: str, request: Request, usuario: dict = Depends(_usuario_actual), estado: str = "todos", asesor: str = "",
):
    """Vista de un lead: resumen del cliente (datos + formularios de gestión)
    y la conversación completa visibles a la vez, sin tener que saltar entre
    dos páginas distintas."""
    lead = await obtener_lead(telefono)
    if lead is None:
        raise HTTPException(status_code=404, detail="Lead no encontrado")
    _verificar_acceso_lead(usuario, lead)

    if usuario["rol"] == "asesor" and not lead.get("visto_asesor", True):
        await marcar_lead_visto(telefono)
        lead["visto_asesor"] = True

    datos = await _datos_bandeja(usuario, estado, asesor)
    rail = await _renderizar_rail_estados(usuario, datos, estado, asesor)
    asesores_equipo = await listar_asesores() if datos["vision_total"] else []
    resumen_barra = _barra_resumen(datos, asesores_equipo) if datos["vision_total"] else ""

    # La lista de conversaciones solo se muestra si se llegó filtrando por un
    # asesor del equipo (se abrió desde su bandeja de chats) — así se puede
    # seguir eligiendo otra conversación sin volver atrás. Si se entró desde
    # la tabla de "Todos los leads", no hace falta y solo quita espacio.
    lista = await _renderizar_lista_conversaciones(usuario, datos, telefono_activo=telefono, asesor_filtro=asesor) if asesor else ""

    nombre_mostrado = lead.get("nombre") or "(sin nombre)"
    resumen_cliente_html = await _bloque_resumen_cliente(telefono, lead, usuario)
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


@router.get("/lead/{telefono}/mensajes.json")
async def mensajes_json(telefono: str, usuario: dict = Depends(_usuario_actual)):
    """Endpoint liviano para que el chat se actualice solo, sin recargar la página."""
    lead = await obtener_lead(telefono)
    if lead is None:
        raise HTTPException(status_code=404, detail="Lead no encontrado")
    _verificar_acceso_lead(usuario, lead)
    historial = await obtener_historial(telefono, limite=200)
    return JSONResponse(historial)


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

    leads = await listar_leads(asesor_asignado=username)
    leads_nuevos = [
        {"telefono": l["telefono"], "nombre": l["nombre"] or l["telefono"]}
        for l in leads if not l["visto_asesor"]
    ]

    agendados = await listar_leads_agendados(asesor_asignado=username)
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


@router.post("/lead/{telefono}/responder")
async def responder_cliente(
    telefono: str,
    mensaje: str = Form(...),
    usuario: dict = Depends(_usuario_actual),
):
    """El asesor humano responde al cliente por el mismo número de WhatsApp
    (Gabi ya está pausada para este lead porque tiene asesor_asignado)."""
    lead = await obtener_lead(telefono)
    if lead is None:
        raise HTTPException(status_code=404, detail="Lead no encontrado")
    _verificar_acceso_lead(usuario, lead)
    if not lead.get("asesor_asignado"):
        raise HTTPException(status_code=400, detail="Este lead aún no está asignado a un asesor")

    mensaje = mensaje.strip()
    if not mensaje:
        raise HTTPException(status_code=400, detail="El mensaje no puede estar vacío")

    proveedor = obtener_proveedor()
    canal = await proveedor.resolver_canal(lead.get("numero_whatsapp_id"))
    enviado = await proveedor.enviar_mensaje(telefono, mensaje, canal=canal)
    if not enviado:
        raise HTTPException(status_code=502, detail="No se pudo enviar el mensaje por WhatsApp")

    await guardar_mensaje(telefono, "asesor", mensaje)
    return JSONResponse({"status": "ok"})


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


async def _subir_y_enviar_media(telefono: str, nombre_archivo: str, content_type: str, contenido: bytes, caption: str, canal: dict | None = None) -> bool:
    """Sube el archivo a WhatsApp y lo envía como imagen o documento según
    su tipo — común entre el envío de una proforma nueva y el reenvío de un
    catálogo ya guardado."""
    proveedor = obtener_proveedor()
    media_id = await proveedor.subir_media(contenido, nombre_archivo, content_type, canal=canal)
    if not media_id:
        raise HTTPException(status_code=502, detail="No se pudo subir el archivo a WhatsApp")
    es_imagen = content_type.startswith("image/")
    enviado = (
        await proveedor.enviar_imagen(telefono, media_id, caption, canal=canal)
        if es_imagen else
        await proveedor.enviar_documento(telefono, media_id, nombre_archivo, caption, canal=canal)
    )
    if not enviado:
        raise HTTPException(status_code=502, detail="No se pudo enviar el archivo por WhatsApp")
    return True


@router.post("/lead/{telefono}/enviar-archivo")
async def enviar_archivo_chat(
    telefono: str,
    archivo: UploadFile = File(...),
    caption: str = Form(""),
    usuario: dict = Depends(_usuario_actual),
):
    """El asesor sube una proforma/imagen puntual y se la manda al cliente
    de una — se guarda en ARCHIVOS_DIR (persistente) para poder reabrirla
    después desde el historial del chat."""
    lead = await obtener_lead(telefono)
    if lead is None:
        raise HTTPException(status_code=404, detail="Lead no encontrado")
    _verificar_acceso_lead(usuario, lead)
    if not lead.get("asesor_asignado"):
        raise HTTPException(status_code=400, detail="Este lead aún no está asignado a un asesor")

    extension = os.path.splitext(archivo.filename or "")[1].lower()
    if extension not in EXTENSIONES_ARCHIVO_PERMITIDAS:
        raise HTTPException(status_code=400, detail="Solo se aceptan PDF, JPG o PNG")

    contenido = await archivo.read()
    if len(contenido) > TAMANO_MAXIMO_ARCHIVO_MB * 1024 * 1024:
        raise HTTPException(status_code=400, detail=f"El archivo supera los {TAMANO_MAXIMO_ARCHIVO_MB}MB permitidos")

    content_type = archivo.content_type or "application/octet-stream"
    canal = await obtener_proveedor().resolver_canal(lead.get("numero_whatsapp_id"))
    await _subir_y_enviar_media(telefono, archivo.filename, content_type, contenido, caption.strip(), canal=canal)

    ruta_disco = _guardar_archivo_en_disco(archivo.filename, contenido)
    archivo_guardado = await crear_archivo_adjunto(
        nombre_original=archivo.filename, ruta_disco=ruta_disco, content_type=content_type,
        tamano_bytes=len(contenido), subido_por=usuario["username"], reutilizable=False,
    )
    await guardar_mensaje(telefono, "asesor", caption.strip() or archivo.filename, archivo_id=archivo_guardado["id"])
    return JSONResponse({"status": "ok"})


@router.post("/lead/{telefono}/enviar-audio")
async def enviar_audio_chat(
    telefono: str,
    audio: UploadFile = File(...),
    usuario: dict = Depends(_usuario_actual),
):
    """El asesor graba una nota de voz en el navegador (WebM/Opus) — se
    convierte a OGG/Opus (único formato de audio que acepta WhatsApp) antes
    de subirla y enviarla, y se guarda ya convertida para poder reabrirla."""
    lead = await obtener_lead(telefono)
    if lead is None:
        raise HTTPException(status_code=404, detail="Lead no encontrado")
    _verificar_acceso_lead(usuario, lead)
    if not lead.get("asesor_asignado"):
        raise HTTPException(status_code=400, detail="Este lead aún no está asignado a un asesor")

    contenido_webm = await audio.read()
    if len(contenido_webm) > TAMANO_MAXIMO_ARCHIVO_MB * 1024 * 1024:
        raise HTTPException(status_code=400, detail=f"El audio supera los {TAMANO_MAXIMO_ARCHIVO_MB}MB permitidos")
    if not contenido_webm:
        raise HTTPException(status_code=400, detail="No se recibió audio")

    contenido_ogg = _convertir_a_ogg_opus(contenido_webm)

    proveedor = obtener_proveedor()
    canal = await proveedor.resolver_canal(lead.get("numero_whatsapp_id"))
    media_id = await proveedor.subir_media(contenido_ogg, "nota_de_voz.ogg", "audio/ogg", canal=canal)
    if not media_id:
        raise HTTPException(status_code=502, detail="No se pudo subir el audio a WhatsApp")
    if not await proveedor.enviar_audio(telefono, media_id, canal=canal):
        raise HTTPException(status_code=502, detail="No se pudo enviar el audio por WhatsApp")

    ruta_disco = _guardar_archivo_en_disco("nota_de_voz.ogg", contenido_ogg)
    archivo_guardado = await crear_archivo_adjunto(
        nombre_original="nota_de_voz.ogg", ruta_disco=ruta_disco, content_type="audio/ogg",
        tamano_bytes=len(contenido_ogg), subido_por=usuario["username"], reutilizable=False,
    )
    await guardar_mensaje(telefono, "asesor", "Nota de voz", archivo_id=archivo_guardado["id"])
    return JSONResponse({"status": "ok"})


@router.post("/lead/{telefono}/enviar-catalogo/{archivo_id}")
async def enviar_catalogo_chat(telefono: str, archivo_id: int, usuario: dict = Depends(_usuario_actual)):
    """Reenvía un archivo de la librería de catálogos reutilizables — se
    vuelve a subir a WhatsApp desde nuestra copia en disco (el media_id de
    Meta es de un solo uso/temporal, no se reutiliza entre conversaciones)."""
    lead = await obtener_lead(telefono)
    if lead is None:
        raise HTTPException(status_code=404, detail="Lead no encontrado")
    _verificar_acceso_lead(usuario, lead)
    if not lead.get("asesor_asignado"):
        raise HTTPException(status_code=400, detail="Este lead aún no está asignado a un asesor")

    archivo = await obtener_archivo_adjunto(archivo_id)
    if archivo is None or not archivo["reutilizable"]:
        raise HTTPException(status_code=404, detail="Catálogo no encontrado")

    with open(archivo["ruta_disco"], "rb") as f:
        contenido = f.read()
    canal = await obtener_proveedor().resolver_canal(lead.get("numero_whatsapp_id"))
    await _subir_y_enviar_media(telefono, archivo["nombre_original"], archivo["content_type"], contenido, "", canal=canal)

    await guardar_mensaje(telefono, "asesor", archivo["nombre_original"], archivo_id=archivo["id"])
    return JSONResponse({"status": "ok"})


@router.get("/archivo/{archivo_id}")
async def descargar_archivo(archivo_id: int, usuario: dict = Depends(_usuario_actual)):
    """Sirve un archivo adjunto ya enviado — si es una proforma puntual (no
    reutilizable), verifica que el usuario tenga acceso al lead al que se le
    mandó, igual que para ver la conversación misma."""
    archivo = await obtener_archivo_adjunto(archivo_id)
    if archivo is None:
        raise HTTPException(status_code=404, detail="Archivo no encontrado")
    if not archivo["reutilizable"]:
        telefono_lead = await obtener_telefono_de_archivo(archivo_id)
        if telefono_lead:
            lead = await obtener_lead(telefono_lead)
            if lead:
                _verificar_acceso_lead(usuario, lead)
    if not os.path.exists(archivo["ruta_disco"]):
        raise HTTPException(status_code=404, detail="El archivo ya no está disponible")
    return FileResponse(archivo["ruta_disco"], filename=archivo["nombre_original"], media_type=archivo["content_type"])


@router.get("/catalogos", response_class=HTMLResponse)
async def gestionar_catalogos(request: Request, usuario: dict = Depends(_usuario_actual), subido: str = ""):
    """Librería de catálogos reutilizables — subir una vez, cualquier asesor
    los puede mandar en cualquier conversación sin volver a subirlos."""
    if usuario["rol"] != "admin":
        raise HTTPException(status_code=403, detail="Solo un administrador puede gestionar catálogos")

    sidebar = await _renderizar_sidebar(usuario, telefono_activo=None)
    archivos = await listar_archivos_reutilizables()

    mensaje_html = ""
    if subido:
        mensaje_html = '<div class="alert alert-success py-2 px-3 mb-3"><i class="bi bi-check-circle-fill"></i> Catálogo subido.</div>'

    filas = "".join(
        f"""<tr>
            <td class="ps-3">
                <div class="fw-semibold">{html.escape(a['etiqueta'] or a['nombre_original'])}</div>
                <div class="text-muted" style="font-size:.75rem">{html.escape(a['nombre_original'])} &middot; {round(a['tamano_bytes'] / 1024)} KB</div>
            </td>
            <td class="text-muted">{html.escape(a['subido_por'])}</td>
            <td><a href="/dashboard/archivo/{a['id']}" target="_blank" class="btn btn-sm btn-outline-secondary"><i class="bi bi-download"></i> Ver</a></td>
            <td class="pe-3">
                <form method="post" action="/dashboard/catalogos/{a['id']}/eliminar" onsubmit="return confirm('¿Quitar este catálogo de la librería? Ya no se podrá elegir para enviar en nuevas conversaciones.')">
                    <button type="submit" class="btn btn-sm btn-outline-danger"><i class="bi bi-trash"></i></button>
                </form>
            </td>
        </tr>"""
        for a in archivos
    )

    panel = f"""
    {_titulo_seccion('bi-folder-fill', 'Librería de catálogos')}
    <p class="text-muted small mb-3">
        Sube catálogos, listas de precios en PDF o imágenes de referencia una sola vez — cualquier
        asesor los va a poder elegir y enviar desde el chat sin tener que subirlos de nuevo cada vez.
    </p>
    {mensaje_html}
    <div class="card leads-card shadow-sm mb-4">
        <div class="barra-acento"></div>
        <div class="table-responsive">
            <table class="table table-hover align-middle mb-0 tabla-ejecutiva">
                <thead><tr><th class="ps-3">Catálogo</th><th>Subido por</th><th></th><th class="pe-3"></th></tr></thead>
                <tbody>{filas or '<tr><td colspan="4" class="text-center text-muted py-4">Aún no hay catálogos.</td></tr>'}</tbody>
            </table>
        </div>
    </div>

    {_titulo_seccion('bi-plus-circle-fill', 'Subir catálogo nuevo')}
    <div class="card leads-card shadow-sm">
        <div class="barra-acento"></div>
        <div class="card-body">
            <form method="post" action="/dashboard/catalogos/nuevo" enctype="multipart/form-data" class="row g-2">
                <div class="col-md-4">
                    <label class="form-label small text-muted mb-0">Nombre para identificarlo</label>
                    <input type="text" name="etiqueta" class="form-control form-control-sm" required placeholder="Ej: Catálogo general 2026">
                </div>
                <div class="col-md-6">
                    <label class="form-label small text-muted mb-0">Archivo (PDF, JPG o PNG, máx. {TAMANO_MAXIMO_ARCHIVO_MB}MB)</label>
                    <input type="file" name="archivo" class="form-control form-control-sm" accept=".pdf,.jpg,.jpeg,.png" required>
                </div>
                <div class="col-md-2 d-flex align-items-end">
                    <button type="submit" class="btn btn-sm btn-primary w-100">Subir</button>
                </div>
            </form>
        </div>
    </div>
    """
    cuerpo = f"""<div class="shell d-flex">{sidebar}<div class="main-pane flex-grow-1 p-4">{panel}</div></div>"""
    return _pagina("Librería de catálogos", usuario, cuerpo, request=request)


@router.post("/catalogos/nuevo")
async def subir_catalogo(
    etiqueta: str = Form(...),
    archivo: UploadFile = File(...),
    usuario: dict = Depends(_usuario_actual),
):
    if usuario["rol"] != "admin":
        raise HTTPException(status_code=403, detail="Solo un administrador puede gestionar catálogos")

    extension = os.path.splitext(archivo.filename or "")[1].lower()
    if extension not in EXTENSIONES_ARCHIVO_PERMITIDAS:
        raise HTTPException(status_code=400, detail="Solo se aceptan PDF, JPG o PNG")

    contenido = await archivo.read()
    if len(contenido) > TAMANO_MAXIMO_ARCHIVO_MB * 1024 * 1024:
        raise HTTPException(status_code=400, detail=f"El archivo supera los {TAMANO_MAXIMO_ARCHIVO_MB}MB permitidos")

    ruta_disco = _guardar_archivo_en_disco(archivo.filename, contenido)
    await crear_archivo_adjunto(
        nombre_original=archivo.filename, ruta_disco=ruta_disco,
        content_type=archivo.content_type or "application/octet-stream",
        tamano_bytes=len(contenido), subido_por=usuario["username"],
        reutilizable=True, etiqueta=etiqueta.strip(),
    )
    return RedirectResponse(url="/dashboard/catalogos?subido=1", status_code=303)


@router.post("/catalogos/{archivo_id}/eliminar")
async def quitar_catalogo(archivo_id: int, usuario: dict = Depends(_usuario_actual)):
    if usuario["rol"] != "admin":
        raise HTTPException(status_code=403, detail="Solo un administrador puede gestionar catálogos")
    await eliminar_archivo_reutilizable(archivo_id)
    return RedirectResponse(url="/dashboard/catalogos", status_code=303)


@router.post("/lead/{telefono}/resultado")
async def actualizar_resultado(
    telefono: str,
    resultado: str = Form(...),
    fecha_agendada: str = Form(""),
    usuario: dict = Depends(_usuario_actual),
):
    lead = await obtener_lead(telefono)
    if lead is None:
        raise HTTPException(status_code=404, detail="Lead no encontrado")
    _verificar_acceso_lead(usuario, lead)
    if resultado and resultado not in RESULTADOS:
        raise HTTPException(status_code=400, detail="Resultado inválido")

    fecha_agendada_dt = None
    if resultado == "agendado" and fecha_agendada:
        try:
            fecha_agendada_dt = datetime.fromisoformat(fecha_agendada)
        except ValueError:
            raise HTTPException(status_code=400, detail="Fecha de la cita inválida")

    await actualizar_lead(telefono, resultado=resultado, fecha_agendada=fecha_agendada_dt)
    return RedirectResponse(url=f"/dashboard/lead/{telefono}", status_code=303)


@router.get("/lead/{telefono}/buscar-producto")
async def buscar_producto_venta(telefono: str, q: str = "", usuario: dict = Depends(_usuario_actual)):
    """Autocompletar del catálogo real (lista de precios) para el formulario
    de Cierre de venta — el mismo buscador que ya usa Gabi por chat, para que
    el producto/marca/precio/proveedor de la venta salgan siempre de la lista
    de precios vigente en vez de que el asesor los tipee a mano."""
    if len(q.strip()) < 2:
        return JSONResponse([])
    productos = buscar_productos(q, limite=8)
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


@router.post("/lead/{telefono}/venta")
async def registrar_venta(
    telefono: str,
    lineas_venta: str = Form("[]"),
    modalidad_pago: str = Form(""),
    cuotas: str = Form(""),
    medio_pago: str = Form(""),
    usuario: dict = Depends(_usuario_actual),
):
    lead = await obtener_lead(telefono)
    if lead is None:
        raise HTTPException(status_code=404, detail="Lead no encontrado")
    _verificar_acceso_lead(usuario, lead)
    if modalidad_pago and modalidad_pago not in MODALIDADES_PAGO:
        raise HTTPException(status_code=400, detail="Modalidad de pago inválida")
    # Cuotas solo aplica a financiado — el campo queda oculto/deshabilitado
    # en el form cuando es contado, así que si llega igual, se ignora.
    if modalidad_pago != "financiado":
        cuotas = ""
    elif cuotas and cuotas not in CUOTAS_DISPONIBLES:
        raise HTTPException(status_code=400, detail="Cuotas inválidas")
    if modalidad_pago == "financiado":
        medio_pago = MEDIO_PAGO_FINANCIADO
    elif medio_pago and medio_pago not in MEDIOS_PAGO_CONTADO:
        raise HTTPException(status_code=400, detail="Medio de pago inválido")

    try:
        lineas_crudas = json.loads(lineas_venta)
    except (json.JSONDecodeError, TypeError):
        lineas_crudas = []
    # El carrito del formulario manda el estado completo (lo que quedó tras
    # agregar/quitar productos) — se valida/recorta acá, nunca se confía en
    # el JSON que mandó el navegador tal cual.
    lineas = [
        {
            "producto": str(l["producto"]).strip()[:300],
            "precio": str(l.get("precio") or "").strip()[:30],
            "marca": str(l.get("marca") or "").strip()[:100],
            "proveedor": str(l.get("proveedor") or "").strip()[:150],
        }
        for l in lineas_crudas
        if isinstance(l, dict) and str(l.get("producto") or "").strip()
    ]
    # Si hay productos, la forma de pago es obligatoria (según corresponda) —
    # ya se valida en el navegador, esto es el respaldo del lado servidor.
    if lineas:
        if not modalidad_pago:
            raise HTTPException(status_code=400, detail="Selecciona la modalidad de pago")
        if modalidad_pago == "financiado" and not cuotas:
            raise HTTPException(status_code=400, detail="Selecciona las cuotas")
        if modalidad_pago == "contado" and not medio_pago:
            raise HTTPException(status_code=400, detail="Selecciona el medio de pago")

    await guardar_lineas_venta(telefono, lineas)

    campos = {"modalidad_pago": modalidad_pago, "cuotas": cuotas, "medio_pago": medio_pago}
    # Si se registró al menos un producto, el resultado pasa a "vendido" automáticamente
    if lineas:
        campos["resultado"] = "vendido"

    await actualizar_lead(telefono, **campos)
    return RedirectResponse(url=f"/dashboard/lead/{telefono}", status_code=303)


@router.post("/lead/{telefono}/asignar")
async def asignar_lead(
    telefono: str,
    asesor_asignado: str = Form(""),
    usuario: dict = Depends(_usuario_actual),
):
    if usuario["rol"] not in ROLES_CON_VISION_TOTAL:
        raise HTTPException(status_code=403, detail="Solo un supervisor puede asignar leads")
    lead = await obtener_lead(telefono)
    if lead is None:
        raise HTTPException(status_code=404, detail="Lead no encontrado")
    if asesor_asignado:
        await asignar_asesor_a_lead(telefono, asesor_asignado)
    return RedirectResponse(url=f"/dashboard/lead/{telefono}", status_code=303)


@router.post("/disponibilidad")
async def toggle_disponibilidad(usuario: dict = Depends(_usuario_actual)):
    """El asesor togglea si está disponible para recibir leads nuevos automáticamente."""
    if usuario["rol"] != "asesor":
        raise HTTPException(status_code=403, detail="Solo un asesor tiene disponibilidad")
    ahora_disponible = not usuario.get("disponible", True)
    await actualizar_disponibilidad(usuario["username"], ahora_disponible)

    # Si se acaba de poner disponible, revisa si hay algún lead que se quedó
    # esperando (derivado a un asesor, pero sin nadie disponible en su
    # momento) y le asigna SOLO EL MÁS ANTIGUO — así no queda huérfano, pero
    # tampoco se le dumpea toda la cola acumulada a quien se conecta primero;
    # si hay más pendientes, se reparten con el siguiente asesor que conecte.
    if ahora_disponible:
        telefono_asignado = await asignar_lead_pendiente_a_asesor(usuario["username"], usuario.get("nivel"))
        if telefono_asignado:
            lead_asignado = await obtener_lead(telefono_asignado)
            await notificar_lead_derivado(
                telefono_asignado, lead_asignado or {},
                "[Asignado automáticamente al ponerse disponible el asesor — estaba en espera]",
            )

    return RedirectResponse(url="/dashboard", status_code=303)


async def _pagina_gestionar_asesores(usuario: dict, mensaje_html: str = "") -> str:
    sidebar = await _renderizar_sidebar(usuario, telefono_activo=None)
    asesores = await listar_asesores()
    umbral_senior = await obtener_configuracion("umbral_senior", str(UMBRAL_SENIOR_DEFAULT))
    umbral_intermedio = await obtener_configuracion("umbral_intermedio", str(UMBRAL_INTERMEDIO_DEFAULT))

    filas = "".join(
        f"""<tr>
            <td class="ps-3">
                <div class="d-flex align-items-center gap-2">
                    {_avatar(a['nombre'], 30)}
                    <span class="fw-semibold">{html.escape(a['nombre'])}</span>
                </div>
            </td>
            <td>{'<span class="badge rounded-pill text-bg-success">Disponible</span>' if a.get('disponible') else '<span class="badge rounded-pill text-bg-secondary">No disponible</span>'}</td>
            <td>
                <form method="post" action="/dashboard/asesores/{html.escape(a['username'])}/nivel" class="d-flex gap-2">
                    <select name="nivel" class="form-select form-select-sm" style="width:auto">
                        {''.join(f'<option value="{n}" {"selected" if a.get("nivel") == n else ""}>{n.capitalize()}</option>' for n in NIVELES_ASESOR)}
                    </select>
                    <button type="submit" class="btn btn-sm btn-outline-primary">Guardar</button>
                </form>
            </td>
            <td class="pe-3">
                <form method="post" action="/dashboard/asesores/{html.escape(a['username'])}/resetear" onsubmit="return confirm('¿Generar una contraseña nueva para {html.escape(a['nombre'])}? La contraseña actual dejará de funcionar.')">
                    <button type="submit" class="btn btn-sm btn-outline-secondary">Resetear contraseña</button>
                </form>
            </td>
        </tr>"""
        for a in asesores
    )

    panel = f"""
    {_titulo_seccion('bi-people-fill', 'Gestionar asesores')}
    <p class="text-muted small mb-3">El nivel se usa para la asignación automática de leads según el valor del producto de interés. La disponibilidad la controla cada asesor desde su propia sesión.</p>
    {mensaje_html}
    <div class="card leads-card shadow-sm mb-3" style="max-width:480px">
        <div class="barra-acento"></div>
        <div class="card-body p-3">
            <h6 class="text-uppercase text-muted small fw-bold mb-1">Umbrales de asignación automática</h6>
            <p class="text-muted small mb-2">Monto mínimo del producto de interés para requerir cada nivel de asesor.</p>
            <form method="post" action="/dashboard/asesores/umbrales" class="d-flex align-items-end gap-2">
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
async def gestionar_asesores(request: Request, usuario: dict = Depends(_usuario_actual)):
    if usuario["rol"] not in ROLES_CON_VISION_TOTAL:
        raise HTTPException(status_code=403, detail="Solo un supervisor puede gestionar asesores")
    cuerpo = await _pagina_gestionar_asesores(usuario)
    return _pagina("Gestionar asesores", usuario, cuerpo, request=request)


@router.post("/asesores/{username}/resetear", response_class=HTMLResponse)
async def resetear_password_asesor(username: str, usuario: dict = Depends(_usuario_actual)):
    """Genera una contraseña temporal nueva para un asesor — para cuando pide
    recuperar acceso. Se muestra una sola vez aquí; el admin debe pasársela
    por su canal habitual, y el asesor puede cambiarla luego desde su perfil."""
    if usuario["rol"] not in ROLES_CON_VISION_TOTAL:
        raise HTTPException(status_code=403, detail="Solo un supervisor puede resetear contraseñas")
    objetivo = await obtener_usuario(username)
    if objetivo is None:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")

    nueva_password = secrets.token_urlsafe(9)
    await cambiar_password(username, nueva_password)

    mensaje_html = (
        '<div class="alert alert-success py-2 small">'
        f'Nueva contraseña para <strong>{html.escape(objetivo["nombre"])}</strong> ({html.escape(username)}): '
        f'<code>{html.escape(nueva_password)}</code> — pásasela por tu canal habitual, no se volverá a mostrar.'
        '</div>'
    )
    cuerpo = await _pagina_gestionar_asesores(usuario, mensaje_html)
    return _pagina("Gestionar asesores", usuario, cuerpo)


@router.post("/asesores/{username}/nivel")
async def actualizar_nivel(
    username: str,
    nivel: str = Form(...),
    usuario: dict = Depends(_usuario_actual),
):
    if usuario["rol"] not in ROLES_CON_VISION_TOTAL:
        raise HTTPException(status_code=403, detail="Solo un supervisor puede editar el nivel de un asesor")
    if nivel not in NIVELES_ASESOR:
        raise HTTPException(status_code=400, detail="Nivel inválido")
    await actualizar_nivel_asesor(username, nivel)
    return RedirectResponse(url="/dashboard/asesores", status_code=303)


@router.post("/asesores/umbrales")
async def actualizar_umbrales_asignacion(
    umbral_intermedio: str = Form(...),
    umbral_senior: str = Form(...),
    usuario: dict = Depends(_usuario_actual),
):
    if usuario["rol"] not in ROLES_CON_VISION_TOTAL:
        raise HTTPException(status_code=403, detail="Solo un supervisor puede editar los umbrales de asignación")
    try:
        valor_intermedio = float(umbral_intermedio)
        valor_senior = float(umbral_senior)
    except ValueError:
        raise HTTPException(status_code=400, detail="Los umbrales deben ser números")
    if valor_intermedio < 0 or valor_senior < 0:
        raise HTTPException(status_code=400, detail="Los umbrales no pueden ser negativos")
    if valor_senior < valor_intermedio:
        raise HTTPException(status_code=400, detail="El umbral Senior no puede ser menor que el de Intermedio")

    await guardar_configuracion("umbral_intermedio", str(valor_intermedio))
    await guardar_configuracion("umbral_senior", str(valor_senior))
    return RedirectResponse(url="/dashboard/asesores", status_code=303)


# ── Gestión de campañas ────────────────────────────────────────────────

TIPOS_DETECCION = {
    "texto_saludo": "Texto del saludo (wa.link)",
    "referral_meta": "Anuncio de Meta (referral)",
    "leadgen_meta": "Formulario de Meta (Lead Ads)",
}


@router.get("/campanas", response_class=HTMLResponse)
async def gestionar_campanas(request: Request, usuario: dict = Depends(_usuario_actual), creada: int | None = None):
    if usuario["rol"] != "admin":
        raise HTTPException(status_code=403, detail="Solo un administrador puede gestionar campañas")

    sidebar = await _renderizar_sidebar(usuario, telefono_activo=None)
    campanas = await listar_campanas()
    conteos = {c["campana"]: c for c in await contar_leads_por_campana()}

    banner_html = ""
    if creada:
        campana_nueva = next((c for c in campanas if c["id"] == creada), None)
        if campana_nueva:
            if campana_nueva.get("texto_saludo"):
                link_nueva = generar_link_whatsapp(campana_nueva["texto_saludo"])
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
        promo = resolver_promo(c)
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
            link = generar_link_whatsapp(c["texto_saludo"])
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
        if conteos.get(c["nombre"], {}).get("total", 0) == 0:
            nombre_js = html.escape(c["nombre"]).replace("'", "\\'")
            boton_eliminar_campana = (
                f'<form method="post" action="/dashboard/campanas/{c["id"]}/eliminar" '
                f"onsubmit=\"return confirm('¿Eliminar la campaña {nombre_js}? Esta acción no se puede deshacer.');\">"
                f'<button type="submit" class="btn btn-sm btn-outline-danger" title="Eliminar (sin leads asociados)">'
                f'<i class="bi bi-trash"></i></button></form>'
            )

        # Modo manual arranca activo solo si ya tiene promo manual guardada y
        # ningún código de catálogo — igual que en Cierre de venta, los dos
        # bloques son mutuamente excluyentes (inputs disabled en el que no
        # está activo, para que el POST solo mande uno de los dos).
        rowid = str(c["id"])
        manual_activo = bool(c.get("producto_promocional")) and not c.get("codigo_material")

        filas.append(f"""<tr>
            <td class="ps-3">
                <div class="fw-semibold">{html.escape(c['nombre'])}</div>
                <div class="text-muted" style="font-size:.75rem">{html.escape(TIPOS_DETECCION.get(c['tipo_deteccion'], c['tipo_deteccion']))} &middot; patrón: &ldquo;{html.escape(c['patron'])}&rdquo;</div>
                {link_html}
            </td>
            <td class="text-muted">{conteos.get(c['nombre'], {}).get('total', 0)} leads / {conteos.get(c['nombre'], {}).get('vendidos', 0)} vendidos</td>
            <td>
                {promo_html}
                <form method="post" action="/dashboard/campanas/{c['id']}/editar" class="d-flex flex-column gap-1 mt-2" style="min-width:240px">
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
                </form>
            </td>
            <td class="pe-3">
                <div class="d-flex gap-1">
                    <form method="post" action="/dashboard/campanas/{c['id']}/toggle">
                        <button type="submit" class="btn btn-sm {'btn-success' if c['activa'] else 'btn-outline-secondary'}">
                            {'Activa' if c['activa'] else 'Inactiva'}
                        </button>
                    </form>
                    {boton_eliminar_campana}
                </div>
            </td>
        </tr>""")

    opciones_tipo = "".join(f'<option value="{v}">{html.escape(t)}</option>' for v, t in TIPOS_DETECCION.items())
    ids_filas_js = "".join(f"inicializarBuscadorCampana('{c['id']}');\n        " for c in campanas)

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
    cuerpo = f"""<div class="shell d-flex">{sidebar}<div class="main-pane flex-grow-1 p-4">{panel}</div></div>"""
    return _pagina("Gestionar campañas", usuario, cuerpo, request=request)


@router.get("/campanas/buscar-producto")
async def buscar_producto_campana(q: str = "", usuario: dict = Depends(_usuario_actual)):
    """Autocompletar del catálogo real para el producto de una campaña — mismo
    buscador que ya usa Gabi por chat y el Cierre de venta, para que la promo
    siempre salga de la lista de precios vigente en vez de tipearla a mano."""
    if usuario["rol"] != "admin":
        raise HTTPException(status_code=403, detail="Solo un administrador puede gestionar campañas")
    if len(q.strip()) < 2:
        return JSONResponse([])
    productos = buscar_productos(q, limite=8)
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
    usuario: dict = Depends(_usuario_actual),
):
    if usuario["rol"] != "admin":
        raise HTTPException(status_code=403, detail="Solo un administrador puede crear campañas")
    if tipo_deteccion not in TIPOS_DETECCION:
        raise HTTPException(status_code=400, detail="Tipo de detección inválido")
    codigo_material = codigo_material.strip()
    if codigo_material and obtener_producto_por_codigo(codigo_material) is None:
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
    campana_creada = await crear_campana(
        nombre=nombre.strip(), tipo_deteccion=tipo_deteccion, patron=patron.strip().lower(),
        texto_saludo=texto_saludo.strip(), codigo_material=codigo_material,
        producto_promocional=producto_promocional.strip(), precio_promocional=precio_promocional.strip(),
    )
    return RedirectResponse(url=f"/dashboard/campanas?creada={campana_creada['id']}", status_code=303)


@router.post("/campanas/{campana_id}/editar")
async def editar_promo_campana(
    campana_id: int,
    codigo_material: str = Form(""),
    producto_promocional: str = Form(""),
    precio_promocional: str = Form(""),
    usuario: dict = Depends(_usuario_actual),
):
    if usuario["rol"] != "admin":
        raise HTTPException(status_code=403, detail="Solo un administrador puede editar campañas")
    codigo_material = codigo_material.strip()
    if codigo_material and obtener_producto_por_codigo(codigo_material) is None:
        raise HTTPException(status_code=400, detail=f"El código de material '{codigo_material}' no existe en la lista de precios vigente")
    await actualizar_campana(
        campana_id,
        codigo_material=codigo_material or None,
        producto_promocional=producto_promocional.strip(),
        precio_promocional=precio_promocional.strip(),
    )
    return RedirectResponse(url="/dashboard/campanas", status_code=303)


@router.post("/campanas/{campana_id}/toggle")
async def toggle_campana(campana_id: int, usuario: dict = Depends(_usuario_actual)):
    if usuario["rol"] != "admin":
        raise HTTPException(status_code=403, detail="Solo un administrador puede activar/desactivar campañas")
    campanas = await listar_campanas()
    actual = next((c for c in campanas if c["id"] == campana_id), None)
    if actual is None:
        raise HTTPException(status_code=404, detail="Campaña no encontrada")
    await actualizar_campana(campana_id, activa=not actual["activa"])
    return RedirectResponse(url="/dashboard/campanas", status_code=303)


@router.post("/campanas/{campana_id}/eliminar")
async def eliminar_campana_ruta(campana_id: int, usuario: dict = Depends(_usuario_actual)):
    if usuario["rol"] != "admin":
        raise HTTPException(status_code=403, detail="Solo un administrador puede eliminar campañas")
    borrada = await eliminar_campana(campana_id)
    if not borrada:
        raise HTTPException(
            status_code=400,
            detail="Esta campaña ya tiene leads asociados — no se puede eliminar, desactívala en su lugar.",
        )
    return RedirectResponse(url="/dashboard/campanas", status_code=303)


# ── Canales de WhatsApp (admin) ─────────────────────────────────────

def _enmascarar_token(token: str | None) -> str:
    """Nunca se muestra un token completo en la pantalla — solo alcanza para
    reconocer cuál es cuál (ej. al confirmar que se pegó el correcto)."""
    if not token:
        return "—"
    if len(token) <= 8:
        return "••••" + token[-2:]
    return "••••" + token[-6:]


async def _bloque_promover_prompt() -> str:
    """Compara el prompt del archivo (config/prompts.yaml, lo que ya corre en
    los canales de prueba) contra el promovido a producción, y ofrece el
    botón para igualarlos — así no hace falta un deploy para que producción
    reciba un cambio ya probado."""
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
                <button type="submit" class="btn btn-sm btn-warning">
                    <i class="bi bi-rocket-takeoff-fill"></i> Promover a producción
                </button>
            </form>
        </div>
    </div>
    """


@router.get("/canales-whatsapp", response_class=HTMLResponse)
async def gestionar_canales_whatsapp(request: Request, usuario: dict = Depends(_usuario_actual)):
    if usuario["rol"] != "admin":
        raise HTTPException(status_code=403, detail="Solo un administrador puede gestionar los canales de WhatsApp")

    sidebar = await _renderizar_sidebar(usuario, telefono_activo=None)
    canales = await listar_canales_whatsapp()

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
            </td>
            <td>
                <form method="post" action="/dashboard/canales-whatsapp/{c['id']}/modo">
                    <button type="submit" class="btn btn-sm {'btn-outline-primary' if es_produccion else 'btn-outline-warning'}"
                        title="Click para cambiar a {'pruebas' if es_produccion else 'producción'}">
                        {'🟢 Producción' if es_produccion else '🧪 Pruebas'}
                    </button>
                </form>
            </td>
            <td class="pe-3">
                <form method="post" action="/dashboard/canales-whatsapp/{c['id']}/toggle">
                    <button type="submit" class="btn btn-sm {'btn-success' if c['activo'] else 'btn-outline-secondary'}">
                        {'Activo' if c['activo'] else 'Inactivo'}
                    </button>
                </form>
            </td>
        </tr>""")

    panel = f"""
    {_titulo_seccion('bi-whatsapp', 'Canales de WhatsApp')}
    <p class="text-muted small mb-3">
        Cada canal es un número de WhatsApp que Gabi puede usar para recibir y responder mensajes.
        Se puede tener más de uno activo a la vez (ej. un número de pruebas y el de producción) —
        cada mensaje se identifica y se responde siempre por el mismo número por el que entró.
        Los tokens se guardan cifrados en la base de datos.
    </p>

    <div class="card leads-card shadow-sm mb-4">
        <div class="barra-acento"></div>
        <div class="table-responsive">
            <table class="table table-hover align-middle mb-0 tabla-ejecutiva">
                <thead>
                    <tr><th class="ps-3">Canal</th><th>Credenciales</th><th>Modo</th><th class="pe-3">Estado</th></tr>
                </thead>
                <tbody>{''.join(filas) or '<tr><td colspan="4" class="text-center text-muted py-4">Aún no hay canales configurados.</td></tr>'}</tbody>
            </table>
        </div>
    </div>

    {_titulo_seccion('bi-plus-circle-fill', 'Nuevo canal')}
    <p class="text-muted small mb-2">
        Estos datos se obtienen desde Meta for Developers → tu app → WhatsApp → Configuración de la API.
    </p>
    <div class="card leads-card shadow-sm">
        <div class="barra-acento"></div>
        <div class="card-body">
            <form method="post" action="/dashboard/canales-whatsapp/nuevo" class="row g-2">
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

    {_titulo_seccion('bi-chat-square-text-fill', 'Prompt de Gabi')}
    <p class="text-muted small mb-2">
        El prompt recién desplegado corre de inmediato en los canales marcados "Pruebas". Los
        canales en "Producción" usan la última versión promovida acá — no cambia sola con un deploy.
    </p>
    {await _bloque_promover_prompt()}
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
    usuario: dict = Depends(_usuario_actual),
):
    if usuario["rol"] != "admin":
        raise HTTPException(status_code=403, detail="Solo un administrador puede gestionar los canales de WhatsApp")
    await crear_canal_whatsapp(
        nombre=nombre.strip(), phone_number_id=phone_number_id.strip(),
        access_token=access_token.strip(), app_secret=app_secret.strip(),
        page_access_token=page_access_token.strip(), modo=modo,
    )
    return RedirectResponse(url="/dashboard/canales-whatsapp", status_code=303)


@router.post("/canales-whatsapp/{canal_id}/toggle")
async def toggle_canal_whatsapp(canal_id: int, usuario: dict = Depends(_usuario_actual)):
    if usuario["rol"] != "admin":
        raise HTTPException(status_code=403, detail="Solo un administrador puede gestionar los canales de WhatsApp")
    canales = await listar_canales_whatsapp()
    actual = next((c for c in canales if c["id"] == canal_id), None)
    if actual is None:
        raise HTTPException(status_code=404, detail="Canal no encontrado")
    await actualizar_canal_whatsapp(canal_id, activo=not actual["activo"])
    return RedirectResponse(url="/dashboard/canales-whatsapp", status_code=303)


@router.post("/canales-whatsapp/{canal_id}/modo")
async def toggle_modo_canal_whatsapp(canal_id: int, usuario: dict = Depends(_usuario_actual)):
    if usuario["rol"] != "admin":
        raise HTTPException(status_code=403, detail="Solo un administrador puede gestionar los canales de WhatsApp")
    canales = await listar_canales_whatsapp()
    actual = next((c for c in canales if c["id"] == canal_id), None)
    if actual is None:
        raise HTTPException(status_code=404, detail="Canal no encontrado")
    nuevo_modo = "pruebas" if actual.get("modo", "produccion") == "produccion" else "produccion"
    await actualizar_canal_whatsapp(canal_id, modo=nuevo_modo)
    return RedirectResponse(url="/dashboard/canales-whatsapp", status_code=303)


@router.post("/canales-whatsapp/promover-prompt")
async def promover_prompt_produccion_route(usuario: dict = Depends(_usuario_actual)):
    """Copia el prompt recién desplegado (config/prompts.yaml) hacia la
    versión que usan los canales de producción — sin necesitar un deploy
    para que el cambio ya probado en el número de pruebas llegue allá."""
    if usuario["rol"] != "admin":
        raise HTTPException(status_code=403, detail="Solo un administrador puede promover el prompt de Gabi")
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
                <div class="mb-2">
                    <label class="form-label small text-muted mb-0">Contraseña actual</label>
                    <input type="password" name="password_actual" class="form-control form-control-sm" required>
                </div>
                <div class="mb-2">
                    <label class="form-label small text-muted mb-0">Contraseña nueva</label>
                    <input type="password" name="password_nueva" class="form-control form-control-sm" required minlength="8">
                </div>
                <div class="mb-3">
                    <label class="form-label small text-muted mb-0">Repetir contraseña nueva</label>
                    <input type="password" name="password_nueva_repetir" class="form-control form-control-sm" required minlength="8">
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
):
    if not bcrypt.checkpw(password_actual.encode(), usuario["password_hash"].encode()):
        return RedirectResponse(url="/dashboard/perfil?error=La+contraseña+actual+no+es+correcta", status_code=303)
    if len(password_nueva) < 8:
        return RedirectResponse(url="/dashboard/perfil?error=La+contraseña+nueva+debe+tener+al+menos+8+caracteres", status_code=303)
    if password_nueva != password_nueva_repetir:
        return RedirectResponse(url="/dashboard/perfil?error=Las+contraseñas+nuevas+no+coinciden", status_code=303)

    await cambiar_password(usuario["username"], password_nueva)
    return RedirectResponse(url="/dashboard/perfil?ok=Contraseña+actualizada+correctamente", status_code=303)
