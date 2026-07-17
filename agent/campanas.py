# agent/campanas.py — Detección de campaña de origen del lead

"""
Detecta de qué campaña de marketing viene un lead nuevo, para poder:
  1. Medir conversión por campaña en el panel.
  2. Ofrecer el producto/precio en promoción correcto según por dónde llegó.

Dos mecanismos de detección, según cómo esté configurada la campaña en la
tabla `campanas` (administrable desde el panel):

  - "texto_saludo": el cliente llega por un wa.link con un mensaje de saludo
    pre-armado (SMS, catálogo web, CrediChat, etc.). Se compara el primer
    mensaje del cliente contra un fragmento distintivo (patron) de ese saludo.
  - "referral_meta": el cliente llega por un anuncio de Click-to-WhatsApp de
    Meta (Facebook/Instagram). Meta manda un objeto "referral" en el webhook
    con datos del anuncio (source_id, headline, etc.) — se compara patron
    contra esos datos.

Solo se evalúa en el PRIMER contacto del lead (cuando aún no tiene
campana_origen asignada) — la campaña de origen no cambia durante la
conversación.
"""

import os
import logging
import urllib.parse

from agent.memory import listar_campanas, asignar_campana_origen, obtener_campana_por_nombre
from agent.tools import obtener_producto_por_codigo, obtener_familia_producto, formatear_producto

logger = logging.getLogger("agentkit")

# Número público al que apuntan los wa.link/SMS de campañas (el mismo al que
# llegan hoy los leads). Solo se usa para generar el enlace de WhatsApp desde
# el panel — no afecta el envío/recepción de mensajes del bot.
WHATSAPP_NUMERO_PUBLICO = os.getenv("WHATSAPP_NUMERO_PUBLICO", "51998317970")


def _normalizar(texto: str) -> str:
    return (texto or "").strip().lower()


def resolver_promo(campana: dict) -> dict | None:
    """
    Resuelve el producto/precio efectivo de una campaña:
    - Si tiene codigo_material, lo busca EN VIVO en la lista de precios
      vigente — así el precio nunca queda desactualizado si el catálogo cambia.
    - Si no, usa el producto/precio de texto libre guardados en la campaña
      (para promociones fuera de catálogo).
    Retorna None si la campaña no tiene ninguna promo asociada.
    """
    if campana.get("codigo_material"):
        producto = obtener_producto_por_codigo(campana["codigo_material"])
        if producto:
            return {
                "producto": f"{producto.get('MARCA', '')} — {producto.get('DESCRIPCIÓN', '')}".strip(" —"),
                "precio": f"S/ {producto.get('PRECIO', '')}",
                "fuente": "catalogo",
            }
        logger.warning(
            f"Campaña '{campana['nombre']}' referencia codigo_material "
            f"'{campana['codigo_material']}' que ya no existe en el catálogo"
        )

    if campana.get("producto_promocional"):
        return {
            "producto": campana["producto_promocional"],
            "precio": campana.get("precio_promocional") or "",
            "fuente": "manual",
        }

    return None


async def obtener_codigos_promocionales_activos() -> set[str]:
    """
    Códigos de material (CODIGO HANA) reservados a alguna campaña activa —
    se usa para excluirlos de la búsqueda general del catálogo, así un precio
    promocional (ej. la Terma a S/419.90 de "SMS Terma a gas") no se le
    ofrece a cualquier cliente que mencione el producto sin venir de esa
    campaña específica. Si la campaña se desactiva, el código vuelve a
    aparecer en la búsqueda regular.

    No es solo el código exacto de la campaña: se incluye TODA su familia de
    combos (mismo modelo base con/sin conexión, combo, ductería, etc.) — así
    un cliente sin esa campaña tampoco ve, por ejemplo, la Secadora Rinnai
    10Kg + Conexión + Combo a un precio que en realidad es parte de la misma
    promoción, solo que en otra variante de instalación.
    """
    campanas = await listar_campanas(solo_activas=True)
    codigos = set()
    for c in campanas:
        if not c.get("codigo_material"):
            continue
        codigos.add(c["codigo_material"])
        familia = obtener_familia_producto(c["codigo_material"])
        codigos.update(p.get("CODIGO HANA", "") for p in familia)
    codigos.discard("")
    return codigos


def resolver_familia_promo(campana: dict) -> list[dict]:
    """
    Retorna todas las variantes de combo/instalación del producto de una
    campaña (ej. Secadora Rinnai 10Kg: sin combo, +conexión, +combo,
    +conexión+combo), para que Gabi pueda cotizar bien si el cliente de esa
    campaña pide una variante distinta a la anunciada en el SMS/anuncio.
    Vacío si la campaña no tiene código de material.
    """
    if not campana.get("codigo_material"):
        return []
    return obtener_familia_producto(campana["codigo_material"])


def generar_link_whatsapp(texto_saludo: str) -> str:
    """Arma el enlace directo de WhatsApp (wa.me) con el saludo pre-cargado,
    listo para usar en SMS/anuncios o para acortar en wa.link.com."""
    texto_codificado = urllib.parse.quote(texto_saludo or "")
    return f"https://wa.me/{WHATSAPP_NUMERO_PUBLICO}?text={texto_codificado}"


async def detectar_y_asignar_campana(telefono: str, texto_mensaje: str, referral: dict | None) -> dict | None:
    """
    Si el lead aún no tiene campaña de origen, intenta detectarla a partir del
    primer mensaje (texto del saludo) o del objeto referral de Meta Ads.
    Si la detecta, la persiste (una sola vez) y la retorna.
    """
    campanas = await listar_campanas(solo_activas=True)
    if not campanas:
        return None

    texto_normalizado = _normalizar(texto_mensaje)

    # 1. Anuncios de Meta (Click-to-WhatsApp) — más específico y confiable
    if referral:
        fuente_meta = _normalizar(
            f"{referral.get('source_id', '')} {referral.get('headline', '')} {referral.get('body', '')}"
        )
        for campana in campanas:
            if campana["tipo_deteccion"] == "referral_meta" and _normalizar(campana["patron"]) in fuente_meta:
                await asignar_campana_origen(telefono, campana["nombre"])
                logger.info(f"Campaña detectada (Meta Ads) para {telefono}: {campana['nombre']}")
                return campana

    # 2. Saludo pre-armado de wa.link (SMS, catálogo web, CrediChat, etc.)
    if texto_normalizado:
        for campana in campanas:
            if campana["tipo_deteccion"] == "texto_saludo" and _normalizar(campana["patron"]) in texto_normalizado:
                await asignar_campana_origen(telefono, campana["nombre"])
                logger.info(f"Campaña detectada (saludo) para {telefono}: {campana['nombre']}")
                return campana

    return None


# Campañas activas según el correo de Jesús Millones del 15/05/2026
# ("RE: BASE OUT Y SMS ALO CALIDDA GSD") — se usan para sembrar la tabla
# `campanas` en el primer arranque, y quedan editables desde el panel.
CAMPANAS_INICIALES = [
    {
        "nombre": "SMS Secadora a gas",
        "tipo_deteccion": "texto_saludo",
        # El patrón tiene que ser un fragmento REAL de texto_saludo — es lo
        # que el cliente manda tal cual al tocar el wa.link, no un resumen
        # de la campaña. (Bug encontrado: el patrón original no aparecía
        # en el texto real, así que esta campaña nunca se detectaba).
        "patron": "secadora a gas rinnai 10kg",
        # Código HANA 4504653 — "SECADORA 10 KG RINNAI + COMBO + RACK" a S/3299,
        # coincide exacto con el precio del SMS del correo del 15/05/2026.
        "codigo_material": "4504653",
        "texto_saludo": (
            "¡Olvídate de tender ropa! Lleva tu secadora a gas Rinnai 10Kg desde "
            "S/ 3299, financiada y sin inicial. Más ahorro y comodidad"
        ),
    },
    {
        "nombre": "SMS Terma a gas",
        "tipo_deteccion": "texto_saludo",
        "patron": "terma rheem 8l",
        # Código HANA 4508841 — "TERMA RHEEM 8 LT TIRO NATURAL + CONEXIÓN" a
        # S/419.90, marcada "PROMOCIONAL MES" en la lista de precios vigente.
        "codigo_material": "4508841",
        "texto_saludo": (
            "Disfruta agua caliente al instante con tu terma Rheem 8L desde "
            "S/ 419.90, financiada y sin inicial. Solicítala aquí"
        ),
    },
    {
        "nombre": "SMS Clientes próximos a habilitar gas",
        "tipo_deteccion": "texto_saludo",
        "patron": "tu gas natural ya está por llegar",
        "texto_saludo": (
            "¡Tu gas natural ya está por llegar! Equipa tu hogar con termas, cocinas, "
            "secadoras y más, financiado y sin inicial"
        ),
    },
    {
        "nombre": "SMS Clientes que ya tienen gas",
        "tipo_deteccion": "texto_saludo",
        "patron": "ya tienes gas natural",
        "texto_saludo": (
            "Ya tienes gas natural, ahora aprovéchalo más. Lleva termas, secadoras o "
            "un nuevo punto de gas financiado y sin inicial"
        ),
    },
    {
        "nombre": "Catálogo web",
        "tipo_deteccion": "texto_saludo",
        "patron": "vi el catálogo web",
        "texto_saludo": (
            "¡Hola! 👋 Vi el catálogo web 🏠🔥 y quisiera más información sobre precios, "
            "cuotas y promociones disponibles en gasodomésticos 😊"
        ),
    },
    {
        "nombre": "CrediChat",
        "tipo_deteccion": "texto_saludo",
        "patron": "vengo de credichat",
        "texto_saludo": (
            "¡Hola! 👋 Vengo de Credichat 📲 y quisiera información sobre financiamiento "
            "disponible con GSD para equipar mi hogar con gasodomésticos 🔥😊"
        ),
    },
    {
        "nombre": "Web Credicálidda",
        "tipo_deteccion": "texto_saludo",
        "patron": "opciones de financiamiento en la web de credicálidda",
        "texto_saludo": (
            "¡Hola! 👋 Vi las opciones de financiamiento en la web de Credicálidda 🔥 y "
            "quisiera conocer las alternativas disponibles con GSD para termas, "
            "secadoras y otros gasodomésticos 😊"
        ),
    },
]


async def sembrar_campanas_iniciales():
    """Crea las campañas conocidas si la tabla está vacía (solo primer arranque).
    No pisa nada si el equipo ya las administró desde el panel."""
    from agent.memory import crear_campana

    existentes = await listar_campanas()
    if existentes:
        return
    for datos in CAMPANAS_INICIALES:
        await crear_campana(**datos)
    logger.info(f"Sembradas {len(CAMPANAS_INICIALES)} campañas iniciales")


# Nombre -> patrón correcto, para las 4 campañas que se sembraron con un
# patrón que no era un fragmento real de su texto_saludo (por eso nunca se
# detectaban — ver CAMPANAS_INICIALES arriba). Corre en cada arranque y no
# hace nada si el patrón ya quedó bien (por este fix o porque alguien lo
# corrigió a mano desde el panel) — no pisa ningún otro campo ni campañas
# creadas después.
PATRONES_CORREGIDOS = {
    "SMS Secadora a gas": "secadora a gas rinnai 10kg",
    "SMS Terma a gas": "terma rheem 8l",
    "SMS Clientes próximos a habilitar gas": "tu gas natural ya está por llegar",
    "SMS Clientes que ya tienen gas": "ya tienes gas natural",
}


async def corregir_patrones_desalineados():
    """Arregla, en la tabla ya sembrada, el patrón de las campañas listadas
    en PATRONES_CORREGIDOS si no coincide con el valor correcto — para que
    el fix también aplique a una base de datos que ya tenía estas campañas
    creadas con el patrón viejo (no solo a una instalación nueva)."""
    from agent.memory import actualizar_campana

    for nombre, patron_correcto in PATRONES_CORREGIDOS.items():
        campana = await obtener_campana_por_nombre(nombre)
        if campana and campana.get("patron") != patron_correcto:
            await actualizar_campana(campana["id"], patron=patron_correcto)
            logger.info(f"Patrón corregido para la campaña '{nombre}'")
