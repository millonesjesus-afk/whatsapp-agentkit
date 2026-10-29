# agent/origen_conversacion.py — De dónde vino cada conversación y con qué oferta.
#
# El asesor que abre un chat necesita saber, sin salir de él, por qué el cliente
# escribió: qué anuncio vio, con qué campaña quedó y qué producto/precio se le
# prometió. Este módulo SOLO LEE y compone: no decide asignaciones ni escribe.
#
# Reglas que ya existen y que aquí se respetan (no se reinventan):
#   · La campaña de una conversación es la VIGENTE: `Conversation.campana_origen_id`
#     (la que cuenta la Analítica y la que cambia "Anuncios detectados" al asignar
#     un anuncio a mano o al migrar campañas comodín). Si la conversación aún no la
#     tiene, se cae a `Lead.campana_origen` (nombre histórico, first-touch).
#   · La evidencia del anuncio sale del PRIMER `AttributionEvent` (first-touch) de
#     la conversación; si esa conversación no tiene eventos propios (p. ej. el
#     cliente volvió tras un cierre definitivo) se usa el primero del teléfono.
#   · El precio de la oferta es el mismo que ve Gabi: `campanas.resolver_promo`
#     (catálogo en vivo por `codigo_material`, o el texto manual de la campaña).
#
# Sin PII adicional: nunca se devuelve el teléfono, el `ctwa_clid` ni el
# `referral_raw` completo. Toda consulta va acotada por `negocio_id`.

from __future__ import annotations

import logging
import time
from urllib.parse import urlparse

from agent import memory as mem
from agent.campanas import resolver_promo

logger = logging.getLogger("agentkit")

TIPOS_ANUNCIO = ("meta_ads", "meta_ads_no_resuelto")
LARGO_MAXIMO_CUERPO = 200
LARGO_MAXIMO_TITULO = 150
LARGO_MAXIMO_URL = 1000

# El precio del catálogo cambia rara vez; un minuto de caché evita una consulta
# por campaña en cada refresco de la bandeja. La clave incluye los campos de la
# campaña que definen la oferta, así que editar la campaña invalida sola.
_TTL_OFERTA_SEGUNDOS = 60
_cache_ofertas: dict[tuple, tuple[float, dict | None]] = {}


def limpiar_cache_ofertas() -> None:
    _cache_ofertas.clear()


# ── Piezas puras (probadas sin base de datos) ───────────────────────────────

def validar_url_anuncio(url) -> str | None:
    """Solo http/https con host, sin credenciales ni caracteres de control. Cualquier otra cosa
    (`javascript:`, `data:`, relativas, vacías) se descarta: la URL termina en un `href`."""
    if not isinstance(url, str):
        return None
    limpia = url.strip()
    if not limpia or len(limpia) > LARGO_MAXIMO_URL:
        return None
    if any(ord(c) < 32 or c in " \\<>\"'" for c in limpia):
        return None
    try:
        partes = urlparse(limpia)
    except ValueError:
        return None
    if partes.scheme.lower() not in ("http", "https"):
        return None
    if not partes.hostname or partes.username or partes.password:
        return None
    return limpia


def _recortar(texto, largo: int) -> str | None:
    if not isinstance(texto, str):
        return None
    limpio = " ".join(texto.split())
    if not limpio:
        return None
    return limpio if len(limpio) <= largo else limpio[: largo - 1].rstrip() + "…"


def _normalizar_precio(precio) -> str | None:
    texto = str(precio or "").strip()
    if not texto or texto.lower() in ("s/", "s/ "):
        return None
    return f"S/ {texto}" if texto[0].isdigit() else texto


def _limpiar_producto(producto) -> str | None:
    texto = " ".join(str(producto or "").replace(" — ", " ").split())
    return texto or None


def armar_oferta(promo: dict | None) -> dict | None:
    """`{producto, precio_promocional, texto}` a partir de lo que devuelve `resolver_promo`."""
    if not promo:
        return None
    producto = _limpiar_producto(promo.get("producto"))
    if not producto:
        return None
    precio = _normalizar_precio(promo.get("precio"))
    return {
        "producto": producto,
        "precio_promocional": precio,
        "texto": f"{producto} · {precio}" if precio else producto,
    }


def _tipo_de(conv: dict, lead: dict | None, primero: dict | None, campana: dict | None) -> str:
    if conv.get("origen_contacto") == "formulario_meta" or (lead or {}).get("origen_contacto") == "formulario_meta":
        return "formulario_meta"
    if primero is not None:
        if primero["tipo_origen"] in TIPOS_ANUNCIO:
            return "anuncio_meta" if campana else "anuncio_sin_campana"
        if primero["tipo_origen"] == "wa_link":
            return "enlace_wa"
    if campana:
        # Sin evidencia (conversaciones anteriores a Attribution V2): la forma de detección de la
        # campaña dice cómo llegó.
        return "enlace_wa" if campana.get("tipo_deteccion") in ("texto_saludo", "codigo_envio") else "anuncio_meta"
    return "organico"


def _anuncio_de(eventos: list[dict], primero: dict) -> dict | None:
    """Datos del anuncio del primer evento; lo que falte se completa con otros eventos del MISMO
    anuncio (a veces el título llega en un segundo mensaje)."""
    mismos = [e for e in eventos if e["tipo_origen"] in TIPOS_ANUNCIO and e["source_id"] == primero["source_id"]]
    candidatos = [primero] + [e for e in mismos if e is not primero]

    def primero_con(clave):
        return next((e[clave] for e in candidatos if e.get(clave)), None)

    titulo = _recortar(primero_con("headline"), LARGO_MAXIMO_TITULO)
    cuerpo = _recortar(primero_con("body"), LARGO_MAXIMO_CUERPO)
    url = validar_url_anuncio(primero_con("source_url"))
    source_id = primero.get("source_id") or None
    if not (titulo or cuerpo or url or source_id):
        return None
    return {
        "titulo": titulo, "cuerpo": cuerpo, "url": url, "source_id": source_id,
        "red": mem._red_de_referral(primero.get("referral_raw")),
    }


def construir_origen(
    *, conv: dict, lead: dict | None, campana: dict | None, eventos_telefono: list[dict], oferta: dict | None,
) -> dict:
    """El objeto `origen` de una conversación. `eventos_telefono` viene del más antiguo al más
    nuevo. Ver el contrato en `docs`/la entrega: tipo, campana, anuncio, oferta, primer_contacto_en."""
    propios = [e for e in eventos_telefono if e["conversation_id"] == conv["id"]]
    eventos = propios or eventos_telefono
    primero = eventos[0] if eventos else None
    nombre_lead = (lead or {}).get("campana_origen")
    tipo = _tipo_de(conv, lead, primero, campana)
    campana_dto = None
    if campana:
        campana_dto = {"id": campana["id"], "nombre": campana["nombre"]}
    elif nombre_lead and tipo != "anuncio_sin_campana":
        # La campaña se borró pero el lead conserva el nombre histórico.
        campana_dto = {"id": None, "nombre": nombre_lead}
    anuncio = _anuncio_de(eventos, primero) if primero is not None and primero["tipo_origen"] in TIPOS_ANUNCIO else None
    instante = primero["creado"] if primero is not None else conv.get("creado")
    return {
        "tipo": tipo,
        "campana": campana_dto,
        "anuncio": anuncio,
        "oferta": oferta if campana_dto else None,
        "primer_contacto_en": mem.iso_utc(instante),
    }


# ── Orquestación con base de datos ──────────────────────────────────────────

async def _oferta_de_campana(campana: dict, negocio_id: str) -> dict | None:
    clave = (
        negocio_id, campana["id"], campana.get("codigo_material"),
        campana.get("producto_promocional"), campana.get("precio_promocional"),
    )
    ahora = time.monotonic()
    guardado = _cache_ofertas.get(clave)
    if guardado and guardado[0] > ahora:
        return guardado[1]
    try:
        oferta = armar_oferta(await resolver_promo(campana, negocio_id))
    except Exception:  # noqa: BLE001 — el origen nunca debe romper la bandeja
        logger.exception("No se pudo resolver la oferta de la campaña %s", campana.get("id"))
        oferta = None
    _cache_ofertas[clave] = (ahora + _TTL_OFERTA_SEGUNDOS, oferta)
    return oferta


async def origenes_de_conversaciones(negocio_id: str, conversation_ids: list[str]) -> dict[str, dict]:
    """`{conversation_id: origen}` en lote: 4 consultas fijas más, como mucho, una por campaña
    distinta con código de catálogo (en caché). Un id de otro Negocio no aparece en el resultado."""
    datos = await mem.cargar_datos_origen_conversaciones(negocio_id, conversation_ids)
    campanas = datos["campanas"]
    por_nombre = {c["nombre"]: c for c in campanas.values()}
    ofertas: dict[int, dict | None] = {}
    resultado: dict[str, dict] = {}
    for conv_id, conv in datos["conversaciones"].items():
        lead = datos["leads"].get(conv["telefono"])
        campana = campanas.get(conv["campana_origen_id"]) if conv["campana_origen_id"] is not None else None
        if campana is None and lead and lead.get("campana_origen"):
            campana = por_nombre.get(lead["campana_origen"])
        oferta = None
        if campana is not None:
            if campana["id"] not in ofertas:
                ofertas[campana["id"]] = await _oferta_de_campana(campana, negocio_id)
            oferta = ofertas[campana["id"]]
        resultado[conv_id] = construir_origen(
            conv=conv, lead=lead, campana=campana,
            eventos_telefono=datos["eventos"].get(conv["telefono"], []), oferta=oferta,
        )
    return resultado


async def origen_de_conversacion(negocio_id: str, conversation_id: str) -> dict | None:
    """El `origen` de una sola conversación; `None` si no existe en este Negocio o si falla
    (nunca propaga: el origen es informativo)."""
    try:
        return (await origenes_de_conversaciones(negocio_id, [conversation_id])).get(conversation_id)
    except Exception:  # noqa: BLE001
        logger.exception("No se pudo calcular el origen de la conversación %s", conversation_id)
        return None
