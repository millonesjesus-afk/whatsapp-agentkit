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
  - "codigo_envio" (2026-10-29): igual que "texto_saludo", pero cada envío
    de SMS lleva un código único al final del saludo, p. ej.
    "(Cód. SMS-TER-29OCT)" — patron guarda el código. Distingue envíos que
    comparten el mismo saludo y sigue funcionando si el cliente cambia el
    resto del texto. Se busca ANTES que la frase: si el cliente borra el
    código, la frase de la campaña general (texto_saludo) sigue sirviendo.
  - "referral_meta": el cliente llega por un anuncio de Click-to-WhatsApp de
    Meta (Facebook/Instagram). Meta manda un objeto "referral" en el webhook
    con datos del anuncio (source_id, headline, etc.) — se compara patron
    contra esos datos.

Solo se evalúa en el PRIMER contacto del lead (cuando aún no tiene
campana_origen asignada) — la campaña de origen no cambia durante la
conversación. Excepción, igual que con los anuncios de Meta: un lead que ya
tenía campaña y vuelve con el código de un envío deja evidencia y su
conversación activa cuenta para ese envío (registrar_codigo_envio_entrante).
"""

import os
import logging
import re
import unicodedata
import urllib.parse

from agent import envios

from agent.memory import (
    listar_campanas, asignar_campana_origen, obtener_campana_por_nombre,
    obtener_lead, actualizar_lead, registrar_attribution_event,
    registrar_attribution_event_adicional, existe_attribution_event_reciente, obtener_reglas_anuncio,
    asignar_campana_a_conversation_activa, existe_attribution_event_de_campana_en_conversacion_activa,
)
from agent.tools import obtener_producto_por_codigo, obtener_familia_producto, formatear_producto

logger = logging.getLogger("agentkit")

# Número público al que apuntan los wa.link/SMS de campañas (el mismo al que
# llegan hoy los leads). Solo se usa para generar el enlace de WhatsApp desde
# el panel — no afecta el envío/recepción de mensajes del bot.
WHATSAPP_NUMERO_PUBLICO = os.getenv("WHATSAPP_NUMERO_PUBLICO", "51998317970")


def _normalizar(texto: str) -> str:
    return (texto or "").strip().lower()


# ── Código por envío (tipo "codigo_envio") ──────────────────────────────────

TIPO_CODIGO_ENVIO = "codigo_envio"
PREFIJO_CODIGO_ENVIO = "Cód."
LARGO_MINIMO_CODIGO = 4   # sin guiones ni espacios, p. ej. TER29
LARGO_MAXIMO_CODIGO = 24
_FORMATO_CODIGO = re.compile(r"^[A-Z0-9]+(?:-[A-Z0-9]+)*$")
# Un lead que YA tiene campaña solo se revisa si su mensaje menciona un código: evita leer las campañas en cada mensaje.
_MENCIONA_CODIGO = re.compile(r"\b(?:c[oó]d(?:igo)?|ref)\b", re.IGNORECASE)
ALCANCES_ENVIO = ("negocio", "producto")
NIVELES_PRODUCTO = ("tipo", "subtipo", "producto")


def _sin_tildes(texto: str | None) -> str:
    return unicodedata.normalize("NFKD", texto or "").encode("ascii", "ignore").decode("ascii")


def normalizar_codigo(texto: str | None) -> str:
    """Mayúsculas, sin tildes y solo letras y números: "Cód. sms-ter 29oct" y "SMS-TER-29OCT" quedan iguales."""
    return re.sub(r"[^A-Z0-9]", "", _sin_tildes(texto).upper())


def _palabras(texto: str | None) -> str:
    """" TER29 " / " SMS TER 29OCT ": el texto en mayúsculas, sin tildes, con cualquier signo convertido en un espacio y
    rodeado de espacios. Buscar el código así exige que aparezca como palabra suelta: un código corto como TER29 no se
    confunde con un pedazo de lo que escribe el cliente ("tengo 29 años" no contiene la palabra TER29)."""
    return f" {' '.join(re.sub(r'[^A-Z0-9]+', ' ', _sin_tildes(texto).upper()).split())} "


def codigos_se_cruzan(uno: str, otro: str) -> bool:
    """Dos códigos que el sistema no podría distinguir: iguales sin signos (TER-29 y TER29) o uno contiene al otro como
    palabras (TER 29OCT dentro de SMS TER 29OCT)."""
    a, b = _palabras(uno), _palabras(otro)
    return bool(a.strip() and b.strip()) and (normalizar_codigo(uno) == normalizar_codigo(otro) or a in b or b in a)


def validar_codigo_envio(codigo: str) -> str | None:
    """Mensaje de error, o None si el código sirve: letras, números y guiones, con al menos una letra y un número
    (así nunca coincide con una palabra o un número sueltos del cliente)."""
    limpio = (codigo or "").strip().upper()
    normalizado = normalizar_codigo(limpio)
    if not _FORMATO_CODIGO.match(limpio):
        return "El código solo puede tener letras, números y guiones (p. ej. TER29)."
    if not (LARGO_MINIMO_CODIGO <= len(normalizado) <= LARGO_MAXIMO_CODIGO):
        return f"El código debe tener entre {LARGO_MINIMO_CODIGO} y {LARGO_MAXIMO_CODIGO} letras o números."
    if not (re.search(r"[A-Z]", normalizado) and re.search(r"[0-9]", normalizado)):
        return "El código debe tener al menos una letra y un número (p. ej. TER29)."
    return None


def saludo_con_codigo(saludo: str, codigo: str) -> str:
    """El saludo que se pone en el enlace: el del usuario con "(Cód. XXX)" al final, salvo que ya lo traiga."""
    saludo = (saludo or "").strip()
    if _palabras(codigo).strip() and _palabras(codigo) in _palabras(saludo):
        return saludo
    return f"{saludo} ({PREFIJO_CODIGO_ENVIO} {codigo.strip().upper()})".strip()


def campana_por_codigo(campanas: list[dict], texto_mensaje: str) -> dict | None:
    """Campaña de envío cuyo código aparece en el mensaje como palabra suelta (sin importar mayúsculas, tildes ni
    signos: "cód. ter29", "(COD TER29)"). Si coinciden varias, gana la del código más largo."""
    texto = _palabras(texto_mensaje)
    if not texto.strip():
        return None
    candidatas = [
        (len(codigo), c) for c in campanas
        if c.get("tipo_deteccion") == TIPO_CODIGO_ENVIO
        and len(normalizar_codigo(c.get("patron"))) >= LARGO_MINIMO_CODIGO
        and (codigo := _palabras(c.get("patron"))) in texto
    ]
    return max(candidatas, key=lambda par: par[0])[1] if candidatas else None


def descripcion_del_grupo(campana: dict) -> str | None:
    """"Termas · Tiro natural" / "Termas" para un envío por tipo o subtipo de producto; None en cualquier otro caso."""
    if campana.get("alcance") != "producto" or campana.get("nivel_producto") not in ("tipo", "subtipo"):
        return None
    partes = [campana.get("tipo_producto")] + ([campana.get("subtipo_producto")] if campana.get("nivel_producto") == "subtipo" else [])
    partes = [p.strip() for p in partes if p and p.strip()]
    return " · ".join(partes) or None


async def resolver_promo(campana: dict, negocio_id: str | None) -> dict | None:
    """
    Resuelve el producto/precio efectivo de una campaña:
    - Si tiene codigo_material, lo busca EN VIVO en la lista de precios
      vigente — así el precio nunca queda desactualizado si el catálogo cambia.
    - Si no, usa el producto/precio de texto libre guardados en la campaña
      (para promociones fuera de catálogo).
    Retorna None si la campaña no tiene ninguna promo asociada.

    `negocio_id` (Gate 4.4): la campaña ya pertenece a un Negocio (su propio
    `negocio_id`), pero el catálogo se consulta por separado — se pasa
    explícitamente en vez de leerlo de `campana` para que quien llama nunca
    pueda resolver la promo de una campaña contra el catálogo de OTRO
    Negocio por error.
    """
    if campana.get("codigo_material"):
        producto = await obtener_producto_por_codigo(campana["codigo_material"], negocio_id)
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


async def obtener_codigos_promocionales_activos(negocio_id: str | None) -> set[str]:
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

    `negocio_id` (Gate 5.4, T2): esta función llama a listar_campanas(), que
    ahora exige negocio_id. Se llama desde el flujo de mensajes del webhook
    (ver brain.py, _armar_bloques_contexto), donde el Canal —y por lo tanto
    el Negocio— puede no haberse podido resolver todavía; con negocio_id=None
    se falla cerrado devolviendo un set vacío (ninguna exclusión) en vez de
    listar campañas de cualquier Negocio."""
    if negocio_id is None:
        return set()
    campanas = await listar_campanas(negocio_id, solo_activas=True)
    codigos = set()
    for c in campanas:
        # Un envío de SMS por producto usa el precio normal del catálogo, no uno reservado (2026-10-29): si lo
        # reservara, cada envío escondería ese producto a todos los demás clientes de Gabi.
        if not c.get("codigo_material") or c.get("tipo_deteccion") == TIPO_CODIGO_ENVIO:
            continue
        codigos.add(c["codigo_material"])
        familia = await obtener_familia_producto(c["codigo_material"], negocio_id)
        codigos.update(p.get("CODIGO HANA", "") for p in familia)
    codigos.discard("")
    return codigos


async def resolver_familia_promo(campana: dict, negocio_id: str | None) -> list[dict]:
    """
    Retorna todas las variantes de combo/instalación del producto de una
    campaña (ej. Secadora Rinnai 10Kg: sin combo, +conexión, +combo,
    +conexión+combo), para que Gabi pueda cotizar bien si el cliente de esa
    campaña pide una variante distinta a la anunciada en el SMS/anuncio.
    Vacío si la campaña no tiene código de material. `negocio_id`, mismo
    criterio que resolver_promo (Gate 4.4)."""
    if not campana.get("codigo_material"):
        return []
    return await obtener_familia_producto(campana["codigo_material"], negocio_id)


def generar_link_whatsapp(texto_saludo: str) -> str:
    """Arma el enlace directo de WhatsApp (wa.me) con el saludo pre-cargado,
    listo para usar en SMS/anuncios o para acortar en wa.link.com."""
    texto_codificado = urllib.parse.quote(texto_saludo or "")
    return f"https://wa.me/{WHATSAPP_NUMERO_PUBLICO}?text={texto_codificado}"


async def resolver_campana_por_referral(campanas: list[dict], referral: dict, negocio_id: str) -> dict | None:
    """Campaña de un referral de Meta: SOLO por la regla anuncio→campaña
    (`anuncio_campana`, escrita al asignar el anuncio desde "Anuncios
    detectados" o al crear la campaña con el ID del anuncio). Ya no se infiere
    por palabras del título o del texto (2026-10-16): un anuncio sin regla, o
    cuya campaña está inactiva, queda sin campaña hasta que se asigne. Una
    falla leyendo las reglas nunca impide atender al lead: se registra y el
    anuncio queda sin resolver (la evidencia de Meta se guarda igual)."""
    source_id = str((referral or {}).get("source_id") or "").strip()
    if not source_id:
        return None
    try:
        campana_id = (await obtener_reglas_anuncio(negocio_id)).get(source_id)
    except Exception:  # noqa: BLE001 — el lead se atiende igual
        logger.exception("No se pudieron leer las reglas anuncio→campaña; el anuncio queda sin resolver")
        return None
    if campana_id is None:
        return None
    return next((c for c in campanas if c["id"] == campana_id), None)


# Ventana en la que el MISMO referral (mismo anuncio y mismo clic) no vuelve a
# registrarse: cubre los reintentos de Meta de un mismo mensaje.
VENTANA_DEDUPE_REFERRAL_MINUTOS = 30


async def registrar_referral_entrante(
    telefono: str, texto_mensaje: str, referral: dict | None, negocio_id: str | None,
) -> dict | None:
    """Atribución de un mensaje entrante que trae `referral` de un anuncio de
    Click-to-WhatsApp, sea cual sea su tipo (foto, audio, documento, texto…).
    `texto_mensaje` es el pie de foto o cadena vacía; solo sirve para el saludo
    de wa.link, igual que en `detectar_y_asignar_campana`.

      · Lead sin campaña de origen: se delega en `detectar_y_asignar_campana`
        (evento 'meta_ads' / 'meta_ads_no_resuelto' y campaña si se resuelve).
      · Lead que YA tenía campaña (first-touch): NO se cambia `campana_origen`;
        el referral nuevo queda como evento con first_touch=False.
      · El mismo referral recibido hace poco (reintento de Meta) no se duplica.

    Sin referral o sin negocio resuelto no hace nada. Retorna la campaña
    detectada, solo cuando se asignó una ahora."""
    if not referral or negocio_id is None:
        return None
    if await existe_attribution_event_reciente(telefono, negocio_id, referral, VENTANA_DEDUPE_REFERRAL_MINUTOS):
        logger.info(f"Referral de {telefono} ya registrado hace poco — no se duplica el evento de atribución")
        return None
    lead = await obtener_lead(telefono, negocio_id=negocio_id)
    if not (lead and lead.get("campana_origen")):
        return await detectar_y_asignar_campana(telefono, texto_mensaje, referral, negocio_id)
    # Ya tenía campaña: solo queda evidencia, sin tocar el first-touch.
    campana = await resolver_campana_por_referral(await listar_campanas(negocio_id, solo_activas=True), referral, negocio_id)
    if campana:
        await registrar_attribution_event_adicional(telefono, "meta_ads", referral=referral, campana_nombre=campana["nombre"])
        # El lead conserva su campaña de primer contacto; esta conversación cuenta para la campaña por la que entró ahora.
        await asignar_campana_a_conversation_activa(telefono, campana["id"])
    else:
        await registrar_attribution_event_adicional(telefono, "meta_ads_no_resuelto", referral=referral)
    return None


async def detectar_y_asignar_campana(
    telefono: str, texto_mensaje: str, referral: dict | None, negocio_id: str | None,
) -> dict | None:
    """
    Si el lead aún no tiene campaña de origen, intenta detectarla a partir del
    primer mensaje (texto del saludo) o del objeto referral de Meta Ads.
    Si la detecta, la persiste (una sola vez) y la retorna.

    `negocio_id` (Gate 5.4, T2): mismo motivo que
    obtener_codigos_promocionales_activos — se resuelve del Canal identificado
    por el webhook (main.py). Si no pudo resolverse (canal=None), no hay
    ningún Negocio legítimo contra el cual buscar campañas: se falla cerrado
    devolviendo None (no se detecta campaña) en vez de listar campañas de
    cualquier Negocio."""
    if negocio_id is None:
        return None
    campanas = await listar_campanas(negocio_id, solo_activas=True)
    if not campanas:
        # Attribution V2 — Fase 1: aunque no haya campañas configuradas
        # todavía, si Meta mandó evidencia de un anuncio no se descarta en
        # silencio — se persiste como "no resuelta" (nunca como orgánica).
        if referral:
            await registrar_attribution_event(telefono, "meta_ads_no_resuelto", referral=referral)
        return None

    texto_normalizado = _normalizar(texto_mensaje)
    # Attribution V2 — Fase 1 (aprobación Opción B): si hubo referral de Meta
    # Ads sin resolver, ya se registró UN evento de evidencia abajo — el
    # bloque de texto_saludo puede seguir asignando campana_origen (esa
    # lógica no cambia), pero no debe generar un SEGUNDO AttributionEvent
    # mezclando la evidencia cruda de Meta con una interpretación de texto.
    referral_sin_resolver = False

    # 1. Anuncios de Meta (Click-to-WhatsApp) — más específico y confiable
    if referral:
        campana = await resolver_campana_por_referral(campanas, referral, negocio_id)
        if campana:
            await asignar_campana_origen(telefono, campana["nombre"])
            logger.info(f"Campaña detectada (Meta Ads) para {telefono}: {campana['nombre']}")
            # Attribution V2 — Fase 1: evidencia adicional, no reemplaza
            # la asignación de campana_origen de la línea de arriba.
            await registrar_attribution_event(telefono, "meta_ads", referral=referral, campana_nombre=campana["nombre"])
            return campana
        # Hubo referral de Meta Ads pero ninguna campaña configurada lo
        # resolvió — regla crítica de Attribution V2: NUNCA se descarta como
        # orgánico, queda registrada como evidencia sin resolver. Un solo
        # evento por mensaje: sin nombre de campaña textual (AttributionEvent
        # = evidencia recibida, Lead.campana_origen = lógica comercial).
        await registrar_attribution_event(telefono, "meta_ads_no_resuelto", referral=referral)
        referral_sin_resolver = True

    # 2. Código de un envío de SMS — más específico que la frase: si el
    # cliente lo dejó, se sabe el envío exacto aunque haya cambiado el resto.
    if texto_normalizado:
        campana = campana_por_codigo(campanas, texto_mensaje)
        if campana:
            await asignar_campana_origen(telefono, campana["nombre"])
            logger.info(f"Campaña detectada (código de envío) para {telefono}: {campana['nombre']}")
            if not referral_sin_resolver:
                await registrar_attribution_event(telefono, "wa_link", campana_nombre=campana["nombre"])
            return campana

    # 3. Saludo pre-armado de wa.link (SMS, catálogo web, CrediChat, etc.) —
    # Lead.campana_origen sigue funcionando exactamente igual que antes de
    # Attribution V2, incluso si ya hubo un referral sin resolver arriba.
    if texto_normalizado:
        for campana in campanas:
            if campana["tipo_deteccion"] == "texto_saludo" and _normalizar(campana["patron"]) in texto_normalizado:
                await asignar_campana_origen(telefono, campana["nombre"])
                logger.info(f"Campaña detectada (saludo) para {telefono}: {campana['nombre']}")
                if not referral_sin_resolver:
                    await registrar_attribution_event(telefono, "wa_link", campana_nombre=campana["nombre"])
                return campana

    return None


async def registrar_codigo_envio_entrante(telefono: str, texto_mensaje: str, negocio_id: str | None) -> dict | None:
    """Lead que YA tenía campaña y escribe con el código de un envío de SMS
    (vuelve por otro SMS): mismo trato que un referral nuevo de Meta en
    `registrar_referral_entrante` — `Lead.campana_origen` (first-touch) no se
    toca; queda evidencia con first_touch=False y la conversación activa
    cuenta para ese envío si aún no tenía campaña. Una sola vez por
    conversación: el cliente puede repetir el código sin duplicar nada.
    Retorna la campaña cuando deja evidencia nueva."""
    if negocio_id is None or not texto_mensaje or not _MENCIONA_CODIGO.search(texto_mensaje):
        return None
    campana = campana_por_codigo(await listar_campanas(negocio_id, solo_activas=True), texto_mensaje)
    if campana is None:
        return None
    if await existe_attribution_event_de_campana_en_conversacion_activa(telefono, negocio_id, campana["nombre"]):
        return None
    await registrar_attribution_event_adicional(telefono, "wa_link", campana_nombre=campana["nombre"])
    await asignar_campana_a_conversation_activa(telefono, campana["id"])
    logger.info(f"Código de envío de un lead con campaña previa ({telefono}): {campana['nombre']}")
    return campana


def _normalizar_telefono(telefono: str) -> str:
    """Meta manda el teléfono del formulario con un '+' adelante (ej.
    '+51987654321') — el resto del sistema guarda el teléfono sin él (igual
    que llega el campo 'from' de un mensaje de WhatsApp), así que hay que
    homologarlo para que sea el MISMO lead si el cliente también escribe."""
    return (telefono or "").strip().lstrip("+").replace(" ", "").replace("-", "")


async def detectar_campana_por_formulario(form_id: str, ad_id: str, negocio_id: str) -> dict | None:
    """Busca una campaña de tipo 'leadgen_meta' cuyo patrón coincida con el
    formulario o el anuncio de origen de un lead de Meta Lead Ads.

    `negocio_id` (Gate 5.4, T2) obligatorio — a diferencia de
    detectar_y_asignar_campana, quien llama (procesar_leads_formulario) solo
    invoca esta función cuando `canal` ya se resolvió (ver más abajo), así
    que acá sí hay un Negocio legítimo garantizado."""
    campanas = await listar_campanas(negocio_id, solo_activas=True)
    form_norm = _normalizar(form_id)
    ad_norm = _normalizar(ad_id)
    for campana in campanas:
        if campana["tipo_deteccion"] != "leadgen_meta":
            continue
        patron = _normalizar(campana["patron"])
        if patron and (patron == form_norm or patron == ad_norm):
            return campana
    return None


async def procesar_leads_formulario(body: dict, proveedor) -> None:
    """Procesa el webhook de 'leadgen' de una Página de Meta (Lead Ads/
    Instant Forms) — a diferencia de un mensaje de WhatsApp, acá el cliente
    NUNCA escribió primero: solo llenó un formulario en Facebook/Instagram.
    Trae sus datos reales, crea el lead, y le manda la primera plantilla
    aprobada para poder iniciar la conversación (WhatsApp no deja mandar
    texto libre a alguien que nunca escribió)."""
    nombre_plantilla = os.getenv("META_LEADGEN_TEMPLATE_NAME")
    idioma_plantilla = os.getenv("META_LEADGEN_TEMPLATE_LANG", "es")
    # El webhook de leadgen (Página) no indica por cuál número de WhatsApp
    # contactar al cliente — a diferencia de un mensaje, no hay un
    # phone_number_id de destino. Mientras solo haya un caso de uso real
    # (Cálidda), se usa el canal por defecto (el primero configurado).
    canal = await proveedor.resolver_canal(None)

    for entry in body.get("entry", []):
        for change in entry.get("changes", []):
            if change.get("field") != "leadgen":
                continue
            leadgen_id = change.get("value", {}).get("leadgen_id")
            if not leadgen_id:
                continue

            datos = await proveedor.obtener_datos_leadgen(leadgen_id, canal=canal)
            if not datos or not datos.get("telefono"):
                logger.warning(f"No se pudieron traer datos del lead de formulario {leadgen_id}")
                continue

            telefono = _normalizar_telefono(datos["telefono"])
            if not telefono:
                logger.warning(f"Lead de formulario {leadgen_id} sin teléfono válido")
                continue

            # Ya es un lead conocido (llegó antes por WhatsApp u otro
            # formulario) — no se le manda otra plantilla de "primer
            # contacto", solo se completa el dato si faltaba. Gate 5.4 (T1):
            # si `canal` no se pudo resolver (ambiguo entre Negocios), no hay
            # negocio_id legítimo para este chequeo — se salta (cae al mismo
            # fail-closed que ya tiene actualizar_lead más abajo) en vez de
            # adivinar consultando sin candado.
            if canal and await obtener_lead(telefono, negocio_id=canal["negocio_id"]):
                logger.info(f"Lead de formulario {leadgen_id} ya existía como {telefono} — no se reenvía la plantilla")
                continue

            # Gate 5.4 (T2): mismo motivo que el chequeo de arriba — sin
            # `canal` resuelto no hay negocio_id legítimo contra el cual
            # buscar campañas (detectar_campana_por_formulario ahora lo
            # exige obligatorio), así que se salta la detección en vez de
            # adivinar un Negocio.
            campana = (
                await detectar_campana_por_formulario(datos.get("form_id", ""), datos.get("ad_id", ""), canal["negocio_id"])
                if canal else None
            )
            # Gate 5.2 (corrección H2): mismo principio que el webhook de
            # mensajes — negocio_id se resuelve del Canal ya identificado,
            # nunca un default global. Si `canal` es None (resolver_canal(None)
            # falló cerrado por ambigüedad entre Negocios, o no hay ningún
            # canal configurado), negocio_id queda None y actualizar_lead()
            # falla cerrado en vez de crear un Lead con Negocio desconocido.
            await actualizar_lead(
                telefono,
                nombre=datos.get("nombre") or "",
                origen_contacto="formulario_meta",
                campana_origen=campana["nombre"] if campana else "",
                numero_whatsapp_id=(canal or {}).get("phone_number_id") or "",
                negocio_id=(canal or {}).get("negocio_id"),
            )
            logger.info(f"Lead de formulario creado: {telefono} (leadgen_id {leadgen_id})")

            if not nombre_plantilla:
                logger.warning(
                    f"META_LEADGEN_TEMPLATE_NAME no configurado — el lead {telefono} quedó "
                    f"creado pero todavía nadie le escribió"
                )
                continue

            primer_nombre = (datos.get("nombre") or "").strip().split(" ")[0] or "🙂"
            enviado = await envios.enviar_plantilla(
                proveedor, telefono, nombre_plantilla, [primer_nombre], idioma_plantilla,
                origen="plantilla_formulario", canal=canal,
            )
            if enviado:
                logger.info(f"Plantilla '{nombre_plantilla}' enviada a {telefono} (lead de formulario)")
            elif getattr(enviado, "incierto", False):
                logger.warning(f"Plantilla '{nombre_plantilla}' a {telefono} sin confirmar: Meta pudo haberla aceptado; no se reenvía (revisar la conciliación)")
            elif getattr(enviado, "bloqueado", False):
                logger.warning(f"Plantilla '{nombre_plantilla}' a {telefono} frenada por la política de envíos: {enviado.motivo}")
            else:
                logger.error(f"No se pudo enviar la plantilla a {telefono} (lead de formulario)")


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
        "patron": "pronto habilitarán mi servicio de gas natural",
        "texto_saludo": (
            "¡Hola! 👋\nPronto habilitarán mi servicio de gas natural 🔥 y quisiera conocer las "
            "promociones disponibles en cocinas, termas y secadoras 😊"
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


async def sembrar_campanas_iniciales(negocio_id: str | None):
    """Crea las campañas conocidas si la tabla está vacía (solo primer arranque).
    No pisa nada si el equipo ya las administró desde el panel.

    `negocio_id` (Gate 5.4, T2): esta función llama a listar_campanas(), que
    ahora exige negocio_id — mismo patrón ya establecido por
    sembrar_canales_desde_env (Gate 5.2, corrección post-auditoría): quien
    llama (main.py, lifespan) lo resuelve EXPLÍCITAMENTE desde
    NEGOCIO_BOOTSTRAP_CODIGO, nunca se asume ningún Negocio por defecto. Con
    negocio_id=None (no configurado, o no corresponde a ningún Negocio real)
    falla cerrado: no siembra nada."""
    from agent.memory import crear_campana

    if negocio_id is None:
        logger.warning(
            "sembrar_campanas_iniciales(): negocio_id no resuelto — siembra de "
            "campañas iniciales deshabilitada (fail-closed)."
        )
        return
    existentes = await listar_campanas(negocio_id)
    if existentes:
        return
    for datos in CAMPANAS_INICIALES:
        await crear_campana(**datos, negocio_id=negocio_id)
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
    "SMS Clientes próximos a habilitar gas": "pronto habilitarán mi servicio de gas natural",
    "SMS Clientes que ya tienen gas": "ya tienes gas natural",
}


async def corregir_patrones_desalineados(negocio_id: str | None):
    """Arregla, en la tabla ya sembrada, el patrón de las campañas listadas
    en PATRONES_CORREGIDOS si no coincide con el valor correcto — para que
    el fix también aplique a una base de datos que ya tenía estas campañas
    creadas con el patrón viejo (no solo a una instalación nueva).

    `negocio_id` (Gate 5.4): mismo criterio que `sembrar_campanas_iniciales`
    — viene del bootstrap de `main.py` (lifespan), fail-closed si no hay
    Negocio resuelto (no corrige nada en vez de adivinar uno)."""
    from agent.memory import actualizar_campana

    if negocio_id is None:
        return

    for nombre, patron_correcto in PATRONES_CORREGIDOS.items():
        campana = await obtener_campana_por_nombre(nombre, negocio_id)
        if not campana or campana.get("patron") == patron_correcto:
            continue
        # Si la campaña tiene su saludo guardado, ese saludo manda (2026-10-29): un patrón que ya aparece en él no se
        # toca, y el de este mapa solo se aplica si de verdad aparece. Antes el mapa pisaba en cada arranque la
        # corrección hecha a mano de «SMS Clientes que ya tienen gas», cuyo saludo real dice «cuento con gas natural».
        saludo = _normalizar(campana.get("texto_saludo"))
        if saludo and (_normalizar(campana.get("patron")) in saludo or _normalizar(patron_correcto) not in saludo):
            continue
        await actualizar_campana(campana["id"], patron=patron_correcto)
        logger.info(f"Patrón corregido para la campaña '{nombre}'")
