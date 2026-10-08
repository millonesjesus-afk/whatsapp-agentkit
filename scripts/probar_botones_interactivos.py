"""Prueba manual de mensajes INTERACTIVOS de WhatsApp en COEXISTENCIA — "Fase 0" del proyecto de botones
guiados (aprobada por el dueño el 2026-10-08).

Para qué sirve: la documentación de Meta no aclara cómo se comportan los mensajes interactivos (botones de
respuesta y listas) enviados por la Cloud API desde un número que está en COEXISTENCIA (app WhatsApp Business +
Cloud API a la vez). Este script manda UN mensaje de prueba, claramente rotulado "[PRUEBA]", a un celular real
del dueño, y después (con --reporte) lee de la base lo que el webhook ya registró. Si la prueba falla, el
proyecto de botones se detiene. Guion completo: docs/prueba_botones_coexistencia.md.

Reglas de seguridad (todas se hacen cumplir en el código y están cubiertas por tests):
  · SIN ENVÍO POR DEFECTO: sin --enviar solo imprime el payload exacto (dry-run implícito).
  · NO pasa por la capa de producción de envíos ni por la política de tope (agent/envios.py): es una prueba
    puntual, a mano, de un solo mensaje. Hace UN solo POST, sin reintentos (Meta no tiene idempotencia: un
    reintento sería un mensaje duplicado).
  · Solo envía al teléfono dado EXPLÍCITAMENTE con --telefono, y solo si en la base ese número tiene un lead y
    su último mensaje ENTRANTE tiene menos de 24 h (ventana de servicio abierta). Si no, se niega.
  · Doble confirmación: --enviar exige además --confirmar-telefono con el MISMO valor que --telefono. Antes de
    enviar se imprime el resumen del lead al que corresponde el número.
  · El teléfono de prueba lo da el dueño: no existe ningún teléfono por defecto ni en el código.
  · Nunca imprime el token de acceso (ni parte de él): todo texto que sale pasa por una limpieza que lo oculta.
  · Con --reporte solo LEE (en Postgres la transacción se abre READ ONLY).

Variables de entorno: DATABASE_URL (la base de producción, por la red privada de Railway) y
CANAL_ENCRYPTION_KEY (para descifrar el token del canal; solo hace falta con --enviar).

Uso (python scripts/probar_botones_interactivos.py ...):
    # 1) Ver el payload sin enviar nada
    --telefono 519XXXXXXXX --caso botones
    # 2) Enviar de verdad (doble confirmación)
    --telefono 519XXXXXXXX --confirmar-telefono 519XXXXXXXX --caso botones --enviar
    # 3) Leer lo que registró el webhook (solo lectura)
    --telefono 519XXXXXXXX --reporte [--horas 6] [--wamid wamid.XXX ...]

Casos (--caso): botones | botones_emoji | lista | texto_ref   (--cuerpo-largo: cuerpo de 300 caracteres)
"""
import argparse
import asyncio
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
from sqlalchemy import func, or_, select, text

# Permite correr este script directo (python scripts/archivo.py) — mismo patrón que los demás scripts.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent.memory import (  # noqa: E402
    CanalWhatsApp, Lead, Mensaje, UsoMensajeMeta, async_session, engine, esperar_base_de_datos,
    listar_canales_whatsapp, obtener_estado_ventana,
)
from agent.providers.meta import ProveedorMeta, _destinatario  # noqa: E402

try:
    from zoneinfo import ZoneInfo
    LIMA = ZoneInfo("America/Lima")
except Exception:  # noqa: BLE001 — sin base de zonas horarias (Windows sin tzdata): Lima es UTC-5 fijo
    LIMA = timezone(timedelta(hours=-5))

CASOS = ("botones", "botones_emoji", "lista", "texto_ref")
ROTULO = "[PRUEBA]"

# Límites de Meta para mensajes interactivos (Cloud API).
MAX_BOTONES = 3
MAX_TITULO_BOTON = 20
MAX_ID_BOTON = 256
MAX_CUERPO_INTERACTIVO = 1024
MAX_CUERPO_TEXTO = 4096
MAX_FILAS_LISTA = 10
MAX_TITULO_FILA = 24
MAX_DESCRIPCION_FILA = 72
MAX_ID_FILA = 200
MAX_TITULO_SECCION = 24
MAX_ETIQUETA_LISTA = 20
# Límite del DISEÑO de botones guiados para el cuerpo (más estricto que el de Meta).
MAX_CUERPO_DISENO = 300

MARGEN_AVISO_VENTANA_MIN = 30   # se avisa (no se niega) si a la ventana le quedan menos de estos minutos
HORAS_REPORTE_POR_DEFECTO = 6
CODIGOS_DE_INTERES = {
    131000: "error genérico de Meta ('algo salió mal')",
    131009: "valor de parámetro inválido (revisa límites de cuerpo/títulos/ids)",
    131026: "mensaje no entregable (sin WhatsApp o versión que no lo soporta)",
    131047: "ventana de 24 h cerrada según Meta (solo plantillas)",
    131051: "tipo de mensaje no soportado",
}
# Contenidos que main.py guarda cuando el mensaje entrante no es texto (f"[{tipo}]"); los de media no son
# "no soportados" (se descargan y se guardan como adjunto).
TIPOS_MEDIA = {"image", "document", "audio", "sticker", "video"}
PATRON_TIPO_ENTRANTE = re.compile(r"^\[([a-z_]+)\]$")

# Cadenas que el orquestador puede buscar en los logs de Railway del servicio WEB (filtro de texto) para lo
# que el webhook actual NO guarda en la base. Salen de agent/main.py y agent/providers/meta.py.
CADENAS_LOGS = (
    ("Mensaje de {tel}:", "un toque de botón/fila llega como texto con el TÍTULO (idéntico a que el cliente lo escriba)"),
    ("Mensaje no soportado (", "el webhook trajo un tipo que el sistema no entiende (p. ej. 'unsupported' o 'interactive' sin "
                               "button_reply/list_reply): típico de un toque que WhatsApp Web/escritorio no pudo resolver"),
    ("Echo de app registrado para {tel}", "eco de coexistencia: Meta avisó que un mensaje salió desde la app Business"),
    ("No se pudo registrar un estado de mensaje de Meta", "falla al guardar un estado sent/delivered/read/failed"),
    ("ya procesado antes", "Meta reentregó un mensaje (idempotencia)"),
)


# ── Telefonos ───────────────────────────────────────────────────────────────────────────────────

def normalizar_telefono(valor: str | None) -> str:
    """Quita espacios, guiones, paréntesis y el '+' inicial de un teléfono. Un BSUID (no son solo dígitos)
    se deja tal cual, solo sin espacios."""
    limpio = re.sub(r"[\s\-()]", "", valor or "")
    sin_mas = limpio.lstrip("+")
    return sin_mas if sin_mas.isdigit() else limpio


def variantes_telefono(valor: str) -> set[str]:
    n = normalizar_telefono(valor)
    return {n, "+" + n} if n.isdigit() else {n}


# ── Payloads ────────────────────────────────────────────────────────────────────────────────────

BOTONES = (
    ("prueba_ver_detalles", "Ver detalles"),
    ("prueba_pagar_cuotas", "Pagar en cuotas"),
    ("prueba_otros_modelos", "Ver otros modelos"),
)
# Con emoji, a propósito en el borde: "📋 Ver otros modelos" mide 19 caracteres (Python), 20 unidades UTF-16 y 22
# bytes UTF-8. Si Meta lo rechaza (131009) sabremos que NO cuenta por caracteres sino por bytes.
BOTONES_EMOJI = (
    ("prueba_emoji_ver_detalles", "\U0001F50E Ver detalles"),
    ("prueba_emoji_pagar_cuotas", "\U0001F4B3 Pagar en cuotas"),
    ("prueba_emoji_otros_modelos", "\U0001F4CB Ver otros modelos"),
)
FILAS_LISTA = (
    ("prueba_fila_1", "Ver detalles", "Fila de prueba 1"),
    ("prueba_fila_2", "Pagar en cuotas", "Fila de prueba 2"),
    ("prueba_fila_3", "Ver otros modelos", "Fila de prueba 3"),
    ("prueba_fila_4", "\U0001F4CB Fila con emoji", "Fila de prueba 4, con emoji en el título"),
)
ETIQUETA_LISTA = "Ver opciones"
TITULO_SECCION = "Modelos de prueba"

CUERPO_BOTONES = (
    f"{ROTULO} Esto es una prueba técnica de botones, NO es un mensaje real. "
    "Toca uno de los botones y anota qué ves. No necesitas escribir nada más."
)
CUERPO_LISTA = f"{ROTULO} Prueba de lista de opciones, NO es un mensaje real. Toca «{ETIQUETA_LISTA}» y elige una fila."
CUERPO_TEXTO = (
    f"{ROTULO} Texto plano de control. Si ves este mensaje, el envío normal funciona. "
    "Compara su estado y su precio con los de los mensajes con botones."
)


def _cuerpo_largo() -> str:
    """Cuerpo de EXACTAMENTE MAX_CUERPO_DISENO caracteres: el máximo que permite el diseño de botones guiados."""
    relleno = " Texto de relleno para medir cómo se ve un cuerpo largo en el celular y en la app Business."
    base = f"{ROTULO} Prueba de cuerpo largo, NO es un mensaje real."
    texto = base
    while len(texto) < MAX_CUERPO_DISENO:
        texto += relleno
    return texto[:MAX_CUERPO_DISENO]


def construir_payload(caso: str, telefono: str, cuerpo_largo: bool = False) -> dict:
    """Payload EXACTO que se enviaría a POST /{phone_number_id}/messages para el caso pedido."""
    if caso not in CASOS:
        raise ValueError(f"caso desconocido: {caso!r} (usa: {', '.join(CASOS)})")
    payload: dict = {"messaging_product": "whatsapp", **_destinatario(telefono)}
    if caso == "texto_ref":
        payload["type"] = "text"
        payload["text"] = {"body": CUERPO_TEXTO}
        return payload
    payload["type"] = "interactive"
    if caso in ("botones", "botones_emoji"):
        botones = BOTONES if caso == "botones" else BOTONES_EMOJI
        payload["interactive"] = {
            "type": "button",
            "body": {"text": _cuerpo_largo() if cuerpo_largo else CUERPO_BOTONES},
            "action": {"buttons": [{"type": "reply", "reply": {"id": i, "title": t}} for i, t in botones]},
        }
        return payload
    payload["interactive"] = {
        "type": "list",
        "body": {"text": _cuerpo_largo() if cuerpo_largo else CUERPO_LISTA},
        "action": {
            "button": ETIQUETA_LISTA,
            "sections": [{
                "title": TITULO_SECCION,
                "rows": [{"id": i, "title": t, "description": d} for i, t, d in FILAS_LISTA],
            }],
        },
    }
    return payload


def validar_payload(payload: dict) -> list[str]:
    """Problemas del payload frente a los límites de Meta y del diseño. Lista vacía = válido."""
    errores: list[str] = []
    if payload.get("messaging_product") != "whatsapp":
        errores.append("messaging_product debe ser 'whatsapp'")
    if ("to" in payload) == ("recipient" in payload):
        errores.append("debe traer exactamente uno de 'to' (teléfono) o 'recipient' (BSUID)")
    tipo = payload.get("type")
    if tipo == "text":
        cuerpo = (payload.get("text") or {}).get("body") or ""
        if not cuerpo or len(cuerpo) > MAX_CUERPO_TEXTO:
            errores.append(f"el texto debe tener entre 1 y {MAX_CUERPO_TEXTO} caracteres")
        if not cuerpo.startswith(ROTULO):
            errores.append(f"el cuerpo de prueba debe empezar con {ROTULO}")
        return errores
    if tipo != "interactive":
        return errores + [f"type no soportado por este script: {tipo!r}"]

    inter = payload.get("interactive") or {}
    cuerpo = (inter.get("body") or {}).get("text") or ""
    if not cuerpo or len(cuerpo) > MAX_CUERPO_INTERACTIVO:
        errores.append(f"el cuerpo debe tener entre 1 y {MAX_CUERPO_INTERACTIVO} caracteres (Meta)")
    if not cuerpo.startswith(ROTULO):
        errores.append(f"el cuerpo de prueba debe empezar con {ROTULO}")
    accion = inter.get("action") or {}
    if inter.get("type") == "button":
        botones = accion.get("buttons") or []
        if not 1 <= len(botones) <= MAX_BOTONES:
            errores.append(f"debe haber entre 1 y {MAX_BOTONES} botones (hay {len(botones)})")
        ids, titulos = [], []
        for b in botones:
            reply = b.get("reply") or {}
            ident, titulo = reply.get("id") or "", reply.get("title") or ""
            if b.get("type") != "reply":
                errores.append("cada botón debe ser type='reply'")
            if not ident or len(ident) > MAX_ID_BOTON:
                errores.append(f"id de botón vacío o de más de {MAX_ID_BOTON} caracteres: {ident!r}")
            if not titulo or len(titulo) > MAX_TITULO_BOTON:
                errores.append(f"el título {titulo!r} debe tener entre 1 y {MAX_TITULO_BOTON} caracteres (tiene {len(titulo)})")
            ids.append(ident)
            titulos.append(titulo)
        if len(set(ids)) != len(ids):
            errores.append("los ids de los botones deben ser únicos")
        if len(set(titulos)) != len(titulos):
            errores.append("los títulos de los botones deben ser únicos")
    elif inter.get("type") == "list":
        etiqueta = accion.get("button") or ""
        if not etiqueta or len(etiqueta) > MAX_ETIQUETA_LISTA:
            errores.append(f"el botón de la lista debe tener entre 1 y {MAX_ETIQUETA_LISTA} caracteres")
        secciones = accion.get("sections") or []
        if not 1 <= len(secciones) <= 10:
            errores.append("la lista debe tener entre 1 y 10 secciones")
        filas = [f for s in secciones for f in (s.get("rows") or [])]
        if not 1 <= len(filas) <= MAX_FILAS_LISTA:
            errores.append(f"la lista debe tener entre 1 y {MAX_FILAS_LISTA} filas en total (hay {len(filas)})")
        for s in secciones:
            if len(s.get("title") or "") > MAX_TITULO_SECCION:
                errores.append(f"el título de sección supera {MAX_TITULO_SECCION} caracteres")
        ids = [f.get("id") or "" for f in filas]
        for f in filas:
            ident, titulo, desc = f.get("id") or "", f.get("title") or "", f.get("description") or ""
            if not ident or len(ident) > MAX_ID_FILA:
                errores.append(f"id de fila vacío o de más de {MAX_ID_FILA} caracteres: {ident!r}")
            if not titulo or len(titulo) > MAX_TITULO_FILA:
                errores.append(f"el título de fila {titulo!r} debe tener entre 1 y {MAX_TITULO_FILA} caracteres")
            if len(desc) > MAX_DESCRIPCION_FILA:
                errores.append(f"la descripción de fila supera {MAX_DESCRIPCION_FILA} caracteres")
        if len(set(ids)) != len(ids):
            errores.append("los ids de las filas deben ser únicos")
    else:
        errores.append(f"interactive.type no soportado por este script: {inter.get('type')!r}")
    return errores


def textos_visibles(payload: dict) -> list[str]:
    """Títulos de botones/filas del payload (lo que WhatsApp devolverá como texto al tocarlos)."""
    inter = payload.get("interactive") or {}
    accion = inter.get("action") or {}
    if inter.get("type") == "button":
        return [(b.get("reply") or {}).get("title", "") for b in accion.get("buttons", [])]
    if inter.get("type") == "list":
        return [f.get("title", "") for s in accion.get("sections", []) for f in s.get("rows", [])]
    return []


def titulos_de_prueba() -> set[str]:
    """Todos los títulos que este script puede mandar (para reconocer un toque en el historial)."""
    titulos: set[str] = set()
    for caso in CASOS:
        titulos.update(t for t in textos_visibles(construir_payload(caso, "0")) if t)
    return titulos


def medidas_titulo(titulo: str) -> tuple[int, int, int]:
    """(caracteres, unidades UTF-16, bytes UTF-8): Meta no documenta cuál cuenta para el límite de 20."""
    return len(titulo), len(titulo.encode("utf-16-le")) // 2, len(titulo.encode("utf-8"))


def formatear_payload(payload: dict) -> list[str]:
    import json
    lineas = ["Payload EXACTO (POST /{phone_number_id}/messages):", json.dumps(payload, ensure_ascii=False, indent=2)]
    titulos = [t for t in textos_visibles(payload) if t]
    if titulos:
        lineas.append("")
        lineas.append(f"{'Título':<26} {'caract.':>7} {'UTF-16':>7} {'bytes':>6}   (límite de Meta: {MAX_TITULO_BOTON} botones / {MAX_TITULO_FILA} filas)")
        for t in titulos:
            c, u, b = medidas_titulo(t)
            lineas.append(f"{t:<26} {c:>7} {u:>7} {b:>6}")
    cuerpo = (payload.get("interactive") or {}).get("body", {}).get("text") or (payload.get("text") or {}).get("body", "")
    lineas.append(f"Cuerpo: {len(cuerpo)} caracteres (diseño ≤{MAX_CUERPO_DISENO}, Meta ≤{MAX_CUERPO_INTERACTIVO}).")
    return lineas


# ── Seguridad: token y envío ────────────────────────────────────────────────────────────────────

def ocultar_secretos(texto: object, *secretos: str | None) -> str:
    """Quita del texto cualquier secreto dado (el token del canal) y cualquier 'Bearer ...'. Todo lo que el
    script imprima desde una respuesta o un error pasa por aquí."""
    resultado = str(texto)
    for secreto in secretos:
        if secreto:
            resultado = resultado.replace(secreto, "***")
    return re.sub(r"(?i)bearer\s+[A-Za-z0-9._\-]+", "Bearer ***", resultado)


async def post_a_meta(url: str, token: str, payload: dict, timeout: float = 30.0) -> tuple[int, object]:
    """UN solo POST, sin reintentos (un reintento duplicaría el mensaje). Devuelve (status, cuerpo JSON o texto).
    Aislada en una función para sustituirla en los tests: las pruebas no usan red."""
    async with httpx.AsyncClient(timeout=timeout) as cliente:
        r = await cliente.post(url, json=payload, headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
    try:
        return r.status_code, r.json()
    except ValueError:
        return r.status_code, r.text


def extraer_wamid(cuerpo: object) -> str | None:
    try:
        return (cuerpo.get("messages") or [])[0].get("id") or None  # type: ignore[union-attr]
    except (AttributeError, IndexError, TypeError):
        return None


def extraer_error(cuerpo: object) -> dict:
    error = cuerpo.get("error") if isinstance(cuerpo, dict) else None
    return error if isinstance(error, dict) else {}


# ── Destino: lead, canal y ventana (solo lectura) ───────────────────────────────────────────────

async def resolver_destino(telefono: str, ahora: datetime | None = None) -> dict:
    """Busca el lead del teléfono, su canal y el estado de la ventana de 24 h, solo con SELECT.
    {"lead": dict | None, "canal": dict | None, "ventana": dict | None}. No descifra ningún token."""
    ahora = ahora or datetime.utcnow()
    variantes = variantes_telefono(telefono)
    async with async_session() as session:
        if engine.dialect.name == "postgresql":
            await session.execute(text("SET TRANSACTION READ ONLY"))
        fila = (await session.execute(select(Lead).where(Lead.telefono.in_(variantes)).limit(1))).scalars().first()
        if fila is None:
            return {"lead": None, "canal": None, "ventana": None}
        lead = {
            "telefono": fila.telefono, "negocio_id": fila.negocio_id, "nombre": fila.nombre, "resultado": fila.resultado,
            "asesor_asignado": fila.asesor_asignado, "paso_flujo": fila.paso_flujo, "campana_origen": fila.campana_origen,
            "origen_contacto": fila.origen_contacto, "numero_whatsapp_id": fila.numero_whatsapp_id,
            "pausado_manual": bool(fila.pausado_manual),
        }
        lead["mensajes_cliente"] = (await session.execute(
            select(func.count()).select_from(Mensaje).where(Mensaje.telefono == fila.telefono, Mensaje.role == "user")
        )).scalar_one()
        canal = None
        if fila.numero_whatsapp_id:
            c = (await session.execute(
                select(CanalWhatsApp).where(
                    CanalWhatsApp.phone_number_id == fila.numero_whatsapp_id, CanalWhatsApp.negocio_id == fila.negocio_id,
                )
            )).scalars().first()
            if c is not None:
                canal = {"id": c.id, "nombre": c.nombre, "phone_number_id": c.phone_number_id, "activo": bool(c.activo),
                         "tiene_token": bool(c.access_token_cifrado)}
    ventana = await obtener_estado_ventana(lead["telefono"], lead["negocio_id"], ahora=ahora, con_fep=False)
    return {"lead": lead, "canal": canal, "ventana": ventana}


def evaluar_envio(destino: dict, telefono: str, confirmar: str | None, ahora: datetime) -> tuple[list[str], list[str]]:
    """(motivos de rechazo, avisos). Sin motivos de rechazo el envío está permitido."""
    rechazos: list[str] = []
    avisos: list[str] = []
    lead, canal, ventana = destino.get("lead"), destino.get("canal"), destino.get("ventana")
    if lead is None:
        rechazos.append(
            "ese teléfono no tiene ningún lead en la base: el número de prueba debe haberle escrito al número de producción "
            "(el webhook crea el lead) y estar dentro de las 24 h. No se envía a números desconocidos."
        )
    else:
        if not ventana or not ventana.get("ventana_24h_abierta"):
            ultimo = (ventana or {}).get("ultimo_mensaje_cliente_en")
            rechazos.append(
                "la ventana de 24 h está CERRADA: " + (
                    f"el último mensaje del cliente fue el {fmt_lima(ultimo)} (Lima)." if ultimo else "el cliente no tiene ningún mensaje entrante."
                ) + " Pídele al dueño que escriba otra vez al número de producción y reintenta."
            )
        else:
            restante = (ventana["vence_en"] - ahora).total_seconds() / 60
            if restante < MARGEN_AVISO_VENTANA_MIN:
                avisos.append(f"a la ventana le quedan solo {restante:.0f} min: conviene que el cliente escriba de nuevo antes de la prueba.")
        if not lead.get("numero_whatsapp_id"):
            rechazos.append("el lead no tiene numero_whatsapp_id: no se sabe por cuál canal contestarle.")
        elif canal is None:
            rechazos.append("no existe el canal del número por el que escribió el cliente.")
        else:
            if not canal.get("activo"):
                rechazos.append(f"el canal «{canal['nombre']}» está inactivo.")
            if not canal.get("tiene_token"):
                rechazos.append(f"el canal «{canal['nombre']}» no tiene access_token guardado.")
    if not confirmar or normalizar_telefono(confirmar) != normalizar_telefono(telefono):
        rechazos.append(
            "falta la doble confirmación: --confirmar-telefono debe ser IGUAL a --telefono "
            f"(recibido: {confirmar!r}). Esto evita mandarle una prueba a un número equivocado o a un cliente real."
        )
    return rechazos, avisos


def resumen_lead(lead: dict | None, canal: dict | None, ventana: dict | None) -> list[str]:
    if lead is None:
        return ["Lead: NO EXISTE en la base."]
    lineas = [
        "Lead al que corresponde este número (confirma que es TU número de prueba y no un cliente real):",
        f"  nombre={lead.get('nombre')!r} resultado={lead.get('resultado')!r} asesor={lead.get('asesor_asignado')!r} "
        f"paso_flujo={lead.get('paso_flujo')!r}",
        f"  campaña={lead.get('campana_origen')!r} origen_contacto={lead.get('origen_contacto')!r} "
        f"Gabi_pausada={lead.get('pausado_manual')} mensajes_del_cliente={lead.get('mensajes_cliente')}",
    ]
    if canal:
        lineas.append(f"  canal: «{canal['nombre']}» phone_number_id={canal['phone_number_id']} activo={canal['activo']}")
    if ventana:
        if ventana.get("ventana_24h_abierta"):
            lineas.append(f"  ventana de 24 h: ABIERTA hasta {fmt_lima(ventana['vence_en'])} (Lima); último mensaje del cliente {fmt_lima(ventana['ultimo_mensaje_cliente_en'])}")
        else:
            lineas.append("  ventana de 24 h: CERRADA")
    return lineas


# ── Envío ───────────────────────────────────────────────────────────────────────────────────────

async def obtener_credenciales(negocio_id: str, phone_number_id: str) -> tuple[str, str]:
    """(token, versión de la API) del canal. El token solo vive en memoria; nunca se imprime."""
    canales = await listar_canales_whatsapp(negocio_id=negocio_id, solo_activos=True)
    canal = next((c for c in canales if c["phone_number_id"] == phone_number_id), None)
    if not canal or not canal.get("access_token"):
        raise RuntimeError("no se pudo leer el token del canal (¿CANAL_ENCRYPTION_KEY correcta?).")
    return canal["access_token"], ProveedorMeta().api_version


async def ejecutar_envio(args, ahora: datetime | None = None, imprimir=print) -> int:
    """Códigos de salida: 0 enviado (o dry-run), 1 error de Meta/técnico, 2 el script se NEGÓ a enviar."""
    ahora = ahora or datetime.utcnow()
    telefono = normalizar_telefono(args.telefono)
    payload = construir_payload(args.caso, telefono, cuerpo_largo=args.cuerpo_largo)
    problemas = validar_payload(payload)
    if problemas:
        imprimir("ERROR: el payload no cumple los límites; no se envía:")
        for p in problemas:
            imprimir(f"  - {p}")
        return 1

    destino = {"lead": None, "canal": None, "ventana": None}
    try:
        destino = await resolver_destino(telefono, ahora)
    except Exception as e:  # noqa: BLE001 — en dry-run la base puede no estar disponible; con --enviar se rechaza más abajo
        imprimir(f"AVISO: no se pudo consultar la base ({type(e).__name__}: {ocultar_secretos(e)}).")
    rechazos, avisos = evaluar_envio(destino, telefono, args.confirmar_telefono, ahora)
    for linea in resumen_lead(destino["lead"], destino["canal"], destino["ventana"]):
        imprimir(linea)
    for a in avisos:
        imprimir(f"AVISO: {a}")
    imprimir("")
    for linea in formatear_payload(payload):
        imprimir(linea)
    imprimir("")

    if not args.enviar:
        imprimir("DRY-RUN: no se envió nada. Para enviar de verdad agrega --enviar y --confirmar-telefono "
                 f"{telefono}.")
        if rechazos:
            imprimir("Con lo que hay hoy, el envío real SE RECHAZARÍA por:")
            for r in rechazos:
                imprimir(f"  - {r}")
        return 0

    if rechazos:
        imprimir("NO SE ENVÍA. Motivos:")
        for r in rechazos:
            imprimir(f"  - {r}")
        return 2

    token = None
    try:
        token, version = await obtener_credenciales(destino["lead"]["negocio_id"], destino["canal"]["phone_number_id"])
        url = f"https://graph.facebook.com/{version}/{destino['canal']['phone_number_id']}/messages"
        status, cuerpo = await post_a_meta(url, token, payload)
    except Exception as e:  # noqa: BLE001
        imprimir(f"ERROR al enviar: {type(e).__name__}: {ocultar_secretos(e, token)}")
        imprimir("El resultado es INCIERTO si fue un corte de red: revisa con --reporte antes de reintentar (un reintento puede duplicarlo).")
        return 1

    wamid = extraer_wamid(cuerpo)
    if status == 200 and wamid:
        imprimir(f"ENVIADO. caso={args.caso} wamid={wamid}")
        imprimir("El wamid queda guardado por el propio webhook de estados (uso_mensajes_meta) cuando Meta avise 'sent'.")
        imprimir("Siguiente paso, tras mirar el celular y tocar los botones:")
        imprimir(f"  python scripts/probar_botones_interactivos.py --telefono {telefono} --reporte --wamid {wamid}")
        return 0
    error = extraer_error(cuerpo)
    codigo = error.get("code")
    imprimir(f"Meta RECHAZÓ el envío: HTTP {status}, código={codigo}, mensaje={ocultar_secretos(error.get('message') or cuerpo, token)}")
    detalle = error.get("error_data")
    if detalle:
        imprimir(f"  detalle: {ocultar_secretos(detalle, token)}")
    if isinstance(codigo, int) and codigo in CODIGOS_DE_INTERES:
        imprimir(f"  {codigo}: {CODIGOS_DE_INTERES[codigo]}")
    imprimir("ANOTA este resultado en la tabla del guion: un rechazo de Meta ES un dato de la prueba.")
    return 1


# ── Reporte (solo lectura) ──────────────────────────────────────────────────────────────────────

def fmt_lima(dt: datetime | None) -> str:
    if dt is None:
        return "—"
    return dt.replace(tzinfo=timezone.utc).astimezone(LIMA).strftime("%Y-%m-%d %H:%M:%S")


async def cargar_datos_reporte(telefono: str, horas: float, wamids: list[str], ahora: datetime) -> dict:
    desde = ahora - timedelta(hours=horas)
    variantes = variantes_telefono(telefono)
    momento = func.coalesce(UsoMensajeMeta.enviado_en, UsoMensajeMeta.creado)
    async with async_session() as session:
        if engine.dialect.name == "postgresql":
            await session.execute(text("SET TRANSACTION READ ONLY"))
        en_periodo = UsoMensajeMeta.destinatario.in_(variantes) & (momento >= desde)
        filtro = or_(en_periodo, UsoMensajeMeta.wamid.in_(wamids)) if wamids else en_periodo
        estados = (await session.execute(select(UsoMensajeMeta).where(filtro).order_by(momento))).scalars().all()
        mensajes = (await session.execute(
            select(Mensaje).where(Mensaje.telefono.in_(variantes), Mensaje.timestamp >= desde).order_by(Mensaje.timestamp).limit(300)
        )).scalars().all()
        estados_d = [
            {"wamid": e.wamid, "estado": e.estado, "enviado_en": e.enviado_en, "entregado_en": e.entregado_en, "leido_en": e.leido_en,
             "fallido_en": e.fallido_en, "error_codigo": e.error_codigo, "error_titulo": e.error_titulo,
             "pricing_type": e.pricing_type, "pricing_categoria": e.pricing_categoria, "pricing_model": e.pricing_model,
             "pricing_billable": e.pricing_billable, "momento": e.enviado_en or e.creado}
            for e in estados
        ]
        mensajes_d = [
            {"id": m.id, "timestamp": m.timestamp, "role": m.role, "via_app": bool(m.via_app), "content": m.content or "",
             "mensaje_id_meta": m.mensaje_id_meta, "estado_envio": m.estado_envio}
            for m in mensajes
        ]
    lead_info = await resolver_destino(telefono, ahora)
    return {"desde": desde, "ahora": ahora, "estados": estados_d, "mensajes": mensajes_d, **lead_info}


def clasificar_mensaje(m: dict, titulos: set[str], wamids: set[str]) -> str:
    contenido = m["content"].strip()
    if m["role"] == "user":
        if contenido in titulos:
            return "TOQUE (el texto coincide con un botón/fila de prueba)"
        coincide = PATRON_TIPO_ENTRANTE.match(contenido)
        if coincide and coincide.group(1) not in TIPOS_MEDIA:
            return f"TIPO NO SOPORTADO '{coincide.group(1)}' (¿toque que no se pudo resolver?)"
        return "texto del cliente"
    if m["via_app"]:
        if m["mensaje_id_meta"] and m["mensaje_id_meta"] in wamids:
            return "ECO de coexistencia con el wamid de la PRUEBA"
        return "eco de la app Business (asesor)"
    return "Gabi / panel"


def formatear_reporte(datos: dict, telefono: str, horas: float, wamids: list[str]) -> list[str]:
    titulos = titulos_de_prueba()
    conjunto_wamids = set(wamids)
    out = [
        f"=== REPORTE (solo lectura) — {telefono} — últimas {horas:g} h, desde {fmt_lima(datos['desde'])} (Lima) ===",
        "",
        "1. Ventana de 24 h (según NUESTRO cálculo: último mensaje del cliente, toques incluidos)",
    ]
    ventana = datos.get("ventana")
    if datos.get("lead") is None:
        out.append("   Ese teléfono no tiene lead en la base.")
    elif ventana:
        out.append(f"   último mensaje del cliente: {fmt_lima(ventana.get('ultimo_mensaje_cliente_en'))} (Lima)")
        out.append(f"   ventana abierta: {'SÍ' if ventana.get('ventana_24h_abierta') else 'NO'}"
                   + (f", vence {fmt_lima(ventana['vence_en'])}" if ventana.get("vence_en") else ""))

    out += ["", "2. Estados de Meta de los mensajes SALIENTES (tabla uso_mensajes_meta)  [* = wamid indicado con --wamid]"]
    if not datos["estados"]:
        out.append("   (ninguno todavía: los estados llegan segundos o minutos después; vuelve a correr el reporte)")
    for e in datos["estados"]:
        marca = "*" if e["wamid"] in conjunto_wamids else " "
        pricing = (f"type={e['pricing_type']} category={e['pricing_categoria']} model={e['pricing_model']} billable={e['pricing_billable']}"
                   if e["pricing_type"] or e["pricing_categoria"] else "sin pricing registrado")
        out.append(f" {marca} {e['wamid']}")
        out.append(f"       estado={e['estado']}  enviado={fmt_lima(e['enviado_en'])}  entregado={fmt_lima(e['entregado_en'])}  leído={fmt_lima(e['leido_en'])}")
        out.append(f"       pricing: {pricing}")
        if e["error_codigo"] is not None:
            nota = CODIGOS_DE_INTERES.get(e["error_codigo"], "")
            out.append(f"       ERROR {e['error_codigo']}: {e['error_titulo'] or ''}" + (f"  <- {nota}" if nota else ""))
    for w in wamids:
        if not any(e["wamid"] == w for e in datos["estados"]):
            out.append(f" * {w}\n       sin estados registrados todavía para este wamid")

    out += ["", "3. Chat del teléfono (tabla mensajes)  — lo que guardó el webhook"]
    if not datos["mensajes"]:
        out.append("   (sin mensajes en el período)")
    ultimo_cliente = None
    for m in datos["mensajes"]:
        clase = clasificar_mensaje(m, titulos, conjunto_wamids)
        contenido = m["content"].replace("\n", " ")
        contenido = contenido[:70] + ("…" if len(contenido) > 70 else "")
        out.append(f"   {fmt_lima(m['timestamp'])}  {m['role']:<9} {clase}")
        out.append(f"       «{contenido}»  wamid={m['mensaje_id_meta'] or '—'}")
        if m["role"] == "user" and not m["content"].startswith("Reaccionó con"):
            ultimo_cliente = (m["timestamp"], clase)

    toques = [m for m in datos["mensajes"] if clasificar_mensaje(m, titulos, conjunto_wamids).startswith("TOQUE")]
    no_soportados = [m for m in datos["mensajes"] if clasificar_mensaje(m, titulos, conjunto_wamids).startswith("TIPO NO SOPORTADO")]
    ecos = [m for m in datos["mensajes"] if m["role"] != "user" and m["via_app"]]
    errores = [e for e in datos["estados"] if e["error_codigo"] is not None]

    out += ["", "4. Lectura rápida"]
    out.append(f"   · Toques recibidos como texto con título de prueba: {len(toques)}"
               + ("" if not toques else "  (llegó algo que parece un button_reply/list_reply; ver nota 5 sobre el id)"))
    out.append(f"   · Entrantes de tipo no soportado/desconocido: {len(no_soportados)}"
               + ("" if not no_soportados else "  <- candidato a toque desde WhatsApp Web/escritorio que no se resolvió"))
    out.append(f"   · Ecos de la app Business en el período: {len(ecos)}"
               + ("" if not ecos else "  (si alguno trae el wamid de la prueba, la coexistencia ESPEJA los mensajes enviados por la API)"))
    out.append(f"   · Estados con error: {len(errores)}" + "".join(f"  [{e['error_codigo']}]" for e in errores))
    if ultimo_cliente:
        out.append(f"   · Último mensaje del cliente: {fmt_lima(ultimo_cliente[0])} — {ultimo_cliente[1]}"
                   + ("\n     → si es un TOQUE, nuestro cálculo cuenta la ventana desde el toque; si Meta la renueva de verdad se "
                      "comprueba con la prueba (e) del guion." if ultimo_cliente[1].startswith("TOQUE") else ""))

    out += [
        "",
        "5. LO QUE EL WEBHOOK ACTUAL NO GUARDA (hay que mirarlo en los logs de Railway del servicio WEB, filtro de texto)",
        "   · interactivo_id y contexto_id del toque: se leen en el parser pero NO se guardan ni se registran en el log.",
        "     En la base solo queda el TÍTULO como texto: un toque es indistinguible de que el cliente lo escriba a mano.",
        "   · El arreglo `errors` de un mensaje ENTRANTE (p. ej. 131051 en un toque no soportado) tampoco se guarda ni se loguea;",
        "     de ese caso solo queda el tipo ('[unsupported]'/'[interactive]') y la línea de log 'Mensaje no soportado (...)'.",
        "   · Sí se guardan: estados y pricing (sección 2) y los errores de ESTADOS failed (sección 2).",
        "   Cadenas para buscar en los logs del servicio web (Railway → servicio web → Logs → filtro):",
    ]
    for cadena, nota in CADENAS_LOGS:
        out.append(f"     «{cadena.format(tel=telefono)}»  → {nota}")
    out.append(f"     «{telefono}»  → todo lo que el servicio hizo con ese número")
    return out


async def ejecutar_reporte(args, ahora: datetime | None = None, imprimir=print) -> int:
    ahora = ahora or datetime.utcnow()
    telefono = normalizar_telefono(args.telefono)
    datos = await cargar_datos_reporte(telefono, args.horas, args.wamid or [], ahora)
    for linea in formatear_reporte(datos, telefono, args.horas, args.wamid or []):
        imprimir(linea)
    return 0


# ── CLI ─────────────────────────────────────────────────────────────────────────────────────────

def construir_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Prueba manual de mensajes interactivos (botones/lista) en coexistencia. SIN ENVÍO por defecto.",
    )
    p.add_argument("--telefono", required=True, help="Teléfono de PRUEBA del dueño (solo dígitos con código de país). Obligatorio: no hay valor por defecto.")
    p.add_argument("--confirmar-telefono", default=None, help="Debe ser IGUAL a --telefono para poder enviar (doble confirmación).")
    p.add_argument("--caso", choices=CASOS, default="botones", help="Qué mensaje de prueba armar. Default: botones.")
    p.add_argument("--cuerpo-largo", action="store_true", help=f"Usa un cuerpo de {MAX_CUERPO_DISENO} caracteres (el máximo del diseño).")
    p.add_argument("--enviar", action="store_true", help="Envía de verdad. Sin este flag solo imprime el payload (dry-run).")
    p.add_argument("--dry-run", action="store_true", help="Explícito; es el comportamiento por defecto. No combina con --enviar.")
    p.add_argument("--reporte", action="store_true", help="Solo lectura: muestra lo que el webhook registró para ese teléfono.")
    p.add_argument("--horas", type=float, default=HORAS_REPORTE_POR_DEFECTO, help=f"Con --reporte: cuántas horas atrás mirar. Default {HORAS_REPORTE_POR_DEFECTO}.")
    p.add_argument("--wamid", action="append", default=None, help="Con --reporte: wamid de un envío de la prueba (repetible); se marca con *.")
    return p


def validar_argumentos(args) -> str | None:
    if args.enviar and args.dry_run:
        return "--enviar y --dry-run son incompatibles."
    if args.reporte and (args.enviar or args.dry_run):
        return "--reporte es de solo lectura: no se combina con --enviar ni --dry-run."
    if args.horas <= 0:
        return "--horas debe ser mayor que 0."
    if not normalizar_telefono(args.telefono):
        return "--telefono está vacío."
    return None


async def main_async(args) -> int:
    await esperar_base_de_datos()
    print(f"Base de datos: {engine.url.get_backend_name()} / {engine.url.database}")
    if args.reporte:
        return await ejecutar_reporte(args)
    return await ejecutar_envio(args)


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass
    argumentos = construir_parser().parse_args()
    error_args = validar_argumentos(argumentos)
    if error_args:
        print(f"ERROR: {error_args}", file=sys.stderr)
        sys.exit(2)
    try:
        sys.exit(asyncio.run(main_async(argumentos)))
    except Exception as e:  # noqa: BLE001
        print(f"ERROR: la prueba de botones falló — {ocultar_secretos(e)}", file=sys.stderr)
        sys.exit(1)
