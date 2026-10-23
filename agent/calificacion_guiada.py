# agent/calificacion_guiada.py — Calificación guiada con botones (2026-10-23, apagada por defecto).
#
# La auditoría de 674 chats (docs/auditoria_chats_gabi_2026-10-18.md) mostró que la mayor fuga está en el primer paso: Gabi pide
# el nombre antes de dar valor y el cliente no vuelve. Este módulo reemplaza ese paso por preguntas de TOQUE (botones o lista) que
# avanzan el flujo de venta sin que el cliente tenga que escribir:
#
#   1. gas      «¿Tu casa ya tiene gas natural de Cálidda?»   Sí / No tengo aún / No estoy seguro        (botones)
#   2. equipo   «¿Qué tienes ya en casa para instalar…?»      terma: lista (punto y ductería, en UN mensaje);
#                                                              secadora/centro de lavado: ¿ya tienes el punto de gas?
#   3. titular  «¿El suministro está a tu nombre?»              Soy el titular / Familiar / Otra persona    (botones)
#   4. datos    (texto) nombre (si no lo tenemos) y DNI del titular o número de suministro, para que el asesor inicie la evaluación.
#
# Camino «sin gas» (la venta del suministro es de OTRA subunidad de Cálidda Hogar: Nuevos suministros):
#   · «Contratar el gas»     → se le da el teléfono de esa subunidad y el caso se cierra como «Solicita suministro de gas».
#   · «Comprar el equipo»    → sigue la asesoría con otros medios de pago (sin financiamiento de Cálidda).
#
# El texto de cada paso es FIJO (cero tokens). Claude solo escribe la respuesta libre del primer mensaje y todo lo que el cliente
# escriba a mano; el sistema le dice qué se preguntó y qué respondió el cliente (bloque de contexto) para que no lo repita.
# El estado vive en eventos del Timeline (`calificacion_pregunta` interno, `calificacion_respuesta` visible), sin migración.
#
# Interruptor por negocio: `calificacion_guiada_modo` = apagado (por defecto) | activo.

import json
import logging
import re
import unicodedata

from agent import envios
from agent import memory as mem
from agent.services.servicio_conversacion import servicio_conversacion
from agent.tiempo_real import gestor_conexiones

logger = logging.getLogger("agentkit")

CLAVE_MODO = "calificacion_guiada_modo"
MODO_APAGADO = "apagado"
MODO_ACTIVO = "activo"
CLAVE_TELEFONO_SUMINISTROS = "calificacion_telefono_suministros"
TELEFONO_SUMINISTROS_POR_DEFECTO = "614 9000, opción 5"
ORIGEN_ENVIO = "gabi_calificacion"

PREFIJO = "cal:"
PASO_GAS, PASO_EQUIPO, PASO_TITULAR, PASO_SINGAS, PASO_DATOS = "gas", "equipo", "titular", "singas", "datos"

# Solo se hace la primera pregunta en los primeros mensajes del cliente (después la conversación ya avanzó sola).
MAXIMO_MENSAJES_CLIENTE_PRIMERA_PREGUNTA = 3

PRODUCTO_TERMA, PRODUCTO_SECADORA, PRODUCTO_LAVADO, PRODUCTO_COCINA, PRODUCTO_OTRO = "terma", "secadora", "lavado", "cocina", "otro"
_NOMBRE_PRODUCTO = {
    PRODUCTO_TERMA: "terma", PRODUCTO_SECADORA: "secadora", PRODUCTO_LAVADO: "centro de lavado",
    PRODUCTO_COCINA: "cocina", PRODUCTO_OTRO: "gasodoméstico",
}
# Los productos que necesitan punto de gas (y la terma, además, ductería): lo dijo el dueño (2026-10-23).
_NECESITAN_PUNTO = (PRODUCTO_TERMA, PRODUCTO_SECADORA, PRODUCTO_LAVADO)

# Ya son definitivas: ningún paso del flujo pasa de 3 botones ni de 10 filas de lista (límites de WhatsApp).
LIMITE_TITULO_BOTON = 20
LIMITE_TITULO_FILA = 24


def _sin_tildes(texto: str | None) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", (texto or "").lower()) if unicodedata.category(c) != "Mn")


def tipo_de_producto(*textos: str | None) -> str:
    """Terma, secadora, centro de lavado, cocina u otro, según las palabras que aparezcan en el interés del lead, la campaña, el
    anuncio o lo que escribió el cliente. Las primeras que aparezcan (en ese orden de prioridad) deciden."""
    junto = _sin_tildes(" ".join(t for t in textos if t))
    if re.search(r"\bterma|calentador|\bfaucet", junto):
        return PRODUCTO_TERMA
    if "secadora" in junto:
        return PRODUCTO_SECADORA
    if re.search(r"centro de lavado|lavadora|lavasecadora", junto):
        return PRODUCTO_LAVADO
    if re.search(r"cocina|encimera|\bhorno", junto):
        return PRODUCTO_COCINA
    return PRODUCTO_OTRO


def nombre_producto(tipo: str) -> str:
    return _NOMBRE_PRODUCTO.get(tipo, "gasodoméstico")


# ── Las preguntas ───────────────────────────────────────────────────────────

def id_boton(paso: str, valor: str) -> str:
    return f"{PREFIJO}{paso}:{valor}"


def parsear_id(interactivo_id: str | None) -> tuple[str, str] | None:
    """`cal:gas:si` → ("gas", "si"); None si no es un id de esta calificación."""
    partes = (interactivo_id or "").split(":")
    if len(partes) != 3 or partes[0] + ":" != PREFIJO or not partes[1] or not partes[2]:
        return None
    return partes[1], partes[2]


def pregunta(paso: str, tipo_producto: str = PRODUCTO_OTRO) -> dict | None:
    """La pregunta de un paso: `{paso, tipo: "botones"|"lista", cuerpo, opciones: [{id, titulo}], boton}`. None si no existe."""
    def _op(valor: str, titulo: str) -> dict:
        return {"id": id_boton(paso, valor), "titulo": titulo}

    if paso == PASO_GAS:
        return {"paso": paso, "tipo": "botones", "cuerpo": "¿Tu casa ya tiene gas natural de Cálidda?", "opciones": [
            _op("si", "Sí, ya tengo"), _op("no", "No tengo aún"), _op("ns", "No estoy seguro"),
        ]}
    if paso == PASO_EQUIPO:
        if tipo_producto == PRODUCTO_TERMA:
            return {
                "paso": paso, "tipo": "lista", "boton": "Elegir una opción",
                "cuerpo": "Una consulta más para armarte la mejor opción: ¿qué tienes ya en casa para instalar la terma?",
                "opciones": [
                    _op("ambos", "Punto de gas y ductería"), _op("punto", "Solo punto de gas"), _op("ducteria", "Solo ductería"),
                    _op("ninguno", "Ninguno de los dos"), _op("ns", "No lo sé"),
                ],
            }
        if tipo_producto in (PRODUCTO_SECADORA, PRODUCTO_LAVADO):
            return {
                "paso": paso, "tipo": "botones",
                "cuerpo": f"Una consulta más: ¿ya tienes el punto de gas para conectar tu {nombre_producto(tipo_producto)}?",
                "opciones": [_op("punto", "Sí, ya tengo punto"), _op("ninguno", "No tengo punto"), _op("ns", "No lo sé")],
            }
        return None
    if paso == PASO_TITULAR:
        return {"paso": paso, "tipo": "botones", "cuerpo": "¿El suministro de gas de esa casa está a tu nombre?", "opciones": [
            _op("si", "Sí, soy el titular"), _op("familiar", "Es de un familiar"), _op("otro", "Es de otra persona"),
        ]}
    if paso == PASO_SINGAS:
        return {"paso": paso, "tipo": "botones", "cuerpo": "Gracias por contarme. ¿Qué prefieres?", "opciones": [
            _op("contratar", "Contratar el gas"), _op("equipo", "Comprar el equipo"),
        ]}
    return None


def validar_pregunta(p: dict) -> list[str]:
    """Problemas de la pregunta frente a los límites de WhatsApp (vacío = válida). Lo usan las pruebas."""
    problemas = []
    ops = p["opciones"]
    if p["tipo"] == "botones":
        if not 1 <= len(ops) <= 3:
            problemas.append("botones: de 1 a 3")
        problemas += [f"título de botón largo: {o['titulo']}" for o in ops if len(o["titulo"]) > LIMITE_TITULO_BOTON]
    else:
        if not 1 <= len(ops) <= 10:
            problemas.append("lista: de 1 a 10 filas")
        problemas += [f"título de fila largo: {o['titulo']}" for o in ops if len(o["titulo"]) > LIMITE_TITULO_FILA]
        if len(p.get("boton", "")) > LIMITE_TITULO_BOTON:
            problemas.append("botón de lista largo")
    if len(p["cuerpo"]) > 1024:
        problemas.append("cuerpo largo")
    return problemas


def interactivo_de(p: dict) -> dict:
    """El objeto `interactive` de la API de WhatsApp para esta pregunta."""
    if p["tipo"] == "botones":
        return {
            "type": "button", "body": {"text": p["cuerpo"]},
            "action": {"buttons": [{"type": "reply", "reply": {"id": o["id"], "title": o["titulo"]}} for o in p["opciones"]]},
        }
    return {
        "type": "list", "body": {"text": p["cuerpo"]},
        "action": {"button": p["boton"], "sections": [{"title": "Opciones", "rows": [{"id": o["id"], "title": o["titulo"]} for o in p["opciones"]]}]},
    }


def texto_visible(p: dict) -> str:
    """Cómo se guarda la pregunta en el chat (y en el historial de Claude): el cuerpo y las opciones."""
    return f"{p['cuerpo']}\n(Opciones: {' · '.join(o['titulo'] for o in p['opciones'])})"


# ── Los textos fijos ────────────────────────────────────────────────────────

def _nombre_conocido(nombre: str | None) -> str | None:
    nombre = " ".join((nombre or "").split())
    if not nombre or nombre.replace("+", "").isdigit():
        return None
    return nombre.split(" ")[0].capitalize()


def texto_pedir_datos(titular: str, nombre: str | None) -> str:
    """Después de «titular»: nombre (si no lo tenemos) y DNI del titular o número de suministro. Una sola petición."""
    conocido = _nombre_conocido(nombre)
    solo_uno = " Ese dato solo sirve para iniciar la evaluación comercial; no es una aprobación."
    varios = " Esos datos solo sirven para iniciar la evaluación comercial; no son una aprobación."
    if titular == "otro":
        if conocido:
            return (
                "Sin problema: también podemos evaluar con los datos del titular, siempre que nos autorice. "
                "¿Me compartes su DNI o su número de suministro de Cálidda?" + solo_uno
            )
        return (
            "Sin problema: también podemos evaluar con los datos del titular, siempre que nos autorice. "
            "¿Me compartes tu nombre y su DNI o su número de suministro de Cálidda?" + varios
        )
    if conocido:
        return (
            f"Perfecto, {conocido}. Para que un asesor inicie tu evaluación, ¿me compartes el DNI del titular del suministro "
            f"o su número de suministro de Cálidda?" + solo_uno
        )
    return (
        "Perfecto. Para que un asesor inicie tu evaluación, ¿me compartes tu nombre y el DNI del titular del suministro "
        "(o su número de suministro de Cálidda)?" + varios
    )


def texto_no_sabe_si_tiene_gas() -> str:
    return (
        "Lo puedes ver en tu recibo de Cálidda: ahí aparece tu número de suministro. Si lo tienes a la mano, escríbemelo; "
        "si no, cuéntame y seguimos igual."
    )


def texto_contratar_gas(telefono: str, tipo_producto: str) -> str:
    producto = f"tu {nombre_producto(tipo_producto)}" if tipo_producto != PRODUCTO_OTRO else "tu gasodoméstico"
    return (
        f"Para contratar el suministro de gas te atiende otra área de Cálidda Hogar: llama al {telefono}. "
        f"Cuando tengas el gas, aquí te ayudo con {producto}."
    )


def texto_comprar_equipo_igual(tipo_producto: str) -> str:
    producto = f"tu {nombre_producto(tipo_producto)}" if tipo_producto != PRODUCTO_OTRO else "tu gasodoméstico"
    return (
        f"Claro, también puedes comprar {producto} con otros medios de pago. Cuéntame cuál te interesa y te explico las "
        f"opciones; un asesor te acompaña con la compra."
    )


# ── Decisiones (puras) ──────────────────────────────────────────────────────

def lleva_pregunta_de_gas(
    lead: dict | None, estado: dict, mensajes_cliente: int, modo: str, derivado: bool = False,
) -> bool:
    """¿Corresponde hacer ahora la primera pregunta (gas natural)? Solo en modo activo, en los primeros mensajes, una sola vez, sin
    asesor ni pausa ni caso cerrado ni derivación en curso."""
    if modo != MODO_ACTIVO or not lead or derivado:
        return False
    if PASO_GAS in estado.get("preguntas", []) or PASO_GAS in estado.get("respuestas", {}):
        return False
    if mensajes_cliente > MAXIMO_MENSAJES_CLIENTE_PRIMERA_PREGUNTA:
        return False
    if lead.get("asesor_asignado") or lead.get("pausado_manual") or lead.get("escalado_supervision_en"):
        return False
    if lead.get("resultado") or lead.get("cerrado_definitivamente_en") is not None or lead.get("paso_flujo") == "derivado_asesor":
        return False
    return True


def siguiente(paso: str, valor: str, tipo_producto: str, nombre: str | None, telefono_suministros: str) -> dict:
    """Qué hace el sistema tras la respuesta del cliente. Devuelve `{"pregunta": dict|None, "texto": str|None, "paso_datos": bool,
    "cerrar_sin_gas": bool}`. Vacío (todo None/False) si el par paso/valor no existe."""
    vacio = {"pregunta": None, "texto": None, "paso_datos": False, "cerrar_sin_gas": False}
    if paso == PASO_GAS:
        if valor == "si":
            siguiente_pregunta = pregunta(PASO_EQUIPO, tipo_producto) if tipo_producto in _NECESITAN_PUNTO else pregunta(PASO_TITULAR)
            return {**vacio, "pregunta": siguiente_pregunta}
        if valor == "no":
            return {**vacio, "pregunta": pregunta(PASO_SINGAS)}
        if valor == "ns":
            return {**vacio, "texto": texto_no_sabe_si_tiene_gas()}
    elif paso == PASO_EQUIPO and valor in ("ambos", "punto", "ducteria", "ninguno", "ns"):
        return {**vacio, "pregunta": pregunta(PASO_TITULAR)}
    elif paso == PASO_TITULAR and valor in ("si", "familiar", "otro"):
        return {**vacio, "texto": texto_pedir_datos(valor, nombre), "paso_datos": True}
    elif paso == PASO_SINGAS:
        if valor == "contratar":
            return {**vacio, "texto": texto_contratar_gas(telefono_suministros, tipo_producto), "cerrar_sin_gas": True}
        if valor == "equipo":
            return {**vacio, "texto": texto_comprar_equipo_igual(tipo_producto)}
    return vacio


_ETIQUETAS_PASO = {PASO_GAS: "gas natural de Cálidda", PASO_EQUIPO: "punto de gas y ductería", PASO_TITULAR: "titular del suministro", PASO_SINGAS: "sin gas: qué prefiere"}
_ETIQUETAS_VALOR = {
    (PASO_GAS, "si"): "sí tiene", (PASO_GAS, "no"): "no tiene aún", (PASO_GAS, "ns"): "no está seguro",
    (PASO_EQUIPO, "ambos"): "tiene punto de gas y ductería", (PASO_EQUIPO, "punto"): "tiene el punto de gas",
    (PASO_EQUIPO, "ducteria"): "solo tiene ductería", (PASO_EQUIPO, "ninguno"): "no tiene punto",
    (PASO_EQUIPO, "ns"): "no sabe",
    (PASO_TITULAR, "si"): "es el titular", (PASO_TITULAR, "familiar"): "es de un familiar", (PASO_TITULAR, "otro"): "es de otra persona",
    (PASO_SINGAS, "contratar"): "quiere contratar el gas", (PASO_SINGAS, "equipo"): "comprará el equipo igual",
}


def descripcion_respuesta(paso: str, valor: str) -> str:
    return f"Calificación: {_ETIQUETAS_PASO.get(paso, paso)} → {_ETIQUETAS_VALOR.get((paso, valor), valor)}"


def bloque_contexto(estado: dict, *, va_la_primera_pregunta: bool) -> str | None:
    """Texto para <contexto_negocio> de Claude: qué le preguntó el sistema con botones y qué respondió el cliente, para que no lo
    repita. Con `va_la_primera_pregunta` Claude NO pregunta ni pide datos en ese mensaje: el sistema hará la pregunta enseguida."""
    partes = []
    if va_la_primera_pregunta:
        partes.append(
            "Después de tu mensaje el sistema le hará al cliente, con botones, una consulta rápida sobre su gas natural. En ESTE mensaje "
            "responde lo que el cliente necesita, NO hagas ninguna pregunta ni pidas su nombre o su DNI todavía, y cierra con una frase "
            "breve sin signos de pregunta (por ejemplo: «Te hago una consulta rápida para orientarte mejor»)."
        )
    respuestas = estado.get("respuestas", {})
    if respuestas:
        dichas = "; ".join(f"{_ETIQUETAS_PASO.get(p, p)}: {_ETIQUETAS_VALOR.get((p, v), v)}" for p, v in respuestas.items())
        partes.append(f"Respuestas del cliente a preguntas con botones — {dichas}. No repitas esas preguntas ni las cambies de palabras.")
    if PASO_DATOS in estado.get("preguntas", []):
        partes.append(
            "Ya le pediste el nombre (si faltaba) y el DNI del titular o el número de suministro: espera su respuesta, no le preguntes "
            "otra cosa. En cuanto te los dé, derívalo al asesor sin pedirle permiso."
        )
    return "\n".join(partes) or None


# ── Con base de datos y envío ───────────────────────────────────────────────

async def obtener_modo(negocio_id: str | None) -> str:
    try:
        valor = (await mem.obtener_configuracion(CLAVE_MODO, MODO_APAGADO, negocio_id=negocio_id) or "").strip().lower()
    except Exception:
        return MODO_APAGADO
    return valor if valor in (MODO_APAGADO, MODO_ACTIVO) else MODO_APAGADO


async def _telefono_suministros(negocio_id: str | None) -> str:
    try:
        valor = " ".join((await mem.obtener_configuracion(CLAVE_TELEFONO_SUMINISTROS, "", negocio_id=negocio_id) or "").split())
    except Exception:
        valor = ""
    return valor or TELEFONO_SUMINISTROS_POR_DEFECTO


async def _guardar_mensaje_de_gabi(telefono: str, canal: dict | None, texto: str, resultado) -> None:
    guardado = await servicio_conversacion.guardar_mensaje(
        telefono, "assistant", texto, negocio_id=(canal or {}).get("negocio_id"),
        mensaje_id_meta=resultado.wamid, estado_envio=resultado.estado_envio,
    )
    try:
        await gestor_conexiones.emitir_mensaje_nuevo(guardado["conversation_id"])
    except Exception:
        logger.exception("calificación guiada: no se pudo avisar al panel")


async def enviar_pregunta(telefono: str, canal: dict | None, proveedor, p: dict) -> bool:
    """Envía la pregunta con botones/lista, la guarda en el chat y deja el evento interno. True si salió (o pudo salir)."""
    try:
        resultado = await envios.enviar_interactivo(proveedor, telefono, interactivo_de(p), origen="gabi_calificacion", canal=canal)
    except Exception:
        logger.exception("calificación guiada: falló el envío de la pregunta")
        return False
    if not (resultado.enviado or resultado.incierto):
        logger.info(f"calificación guiada: la pregunta {p['paso']} no salió ({resultado.motivo or 'envío fallido'})")
        return False
    try:
        await _guardar_mensaje_de_gabi(telefono, canal, texto_visible(p), resultado)
        await mem.registrar_evento_lead(
            telefono, mem.EVENTO_CALIFICACION_PREGUNTA, f"Pregunta con botones: {p['paso']}", None, {"paso": p["paso"]},
        )
    except Exception:
        logger.exception("calificación guiada: la pregunta salió pero no se pudo guardar")
    return True


async def enviar_texto_fijo(telefono: str, canal: dict | None, proveedor, texto: str) -> bool:
    try:
        resultado = await envios.enviar_texto(proveedor, telefono, texto, origen="gabi_calificacion", canal=canal)
    except Exception:
        logger.exception("calificación guiada: falló el envío del texto")
        return False
    if not (resultado.enviado or resultado.incierto):
        return False
    try:
        await _guardar_mensaje_de_gabi(telefono, canal, texto, resultado)
    except Exception:
        logger.exception("calificación guiada: el texto salió pero no se pudo guardar")
    return True


async def _textos_del_producto(telefono: str, lead: dict | None, negocio_id: str | None) -> list[str]:
    """Lo que dice qué producto busca el cliente: interés, campaña, anuncio y sus primeros mensajes."""
    textos = [(lead or {}).get("interes"), (lead or {}).get("producto_tipo"), (lead or {}).get("campana_origen")]
    try:
        from agent.origen_conversacion import origen_de_conversacion
        conversation = await mem.obtener_conversation_activa_de_telefono(telefono, negocio_id) if negocio_id else None
        origen = await origen_de_conversacion(negocio_id, conversation["id"]) if conversation else None
        anuncio = (origen or {}).get("anuncio") or {}
        textos += [anuncio.get("titulo"), anuncio.get("cuerpo")]
    except Exception:
        logger.exception("calificación guiada: no se pudo leer el anuncio")
    try:
        historial = await servicio_conversacion.obtener_historial(telefono)
        textos += [m["content"] for m in historial if m.get("role") == "user"][:3]
    except Exception:
        logger.exception("calificación guiada: no se pudo leer el historial")
    return [t for t in textos if t]


async def preguntar_gas_si_corresponde(
    telefono: str, canal: dict | None, lead: dict | None, proveedor, mensajes_cliente: int, derivado: bool = False,
) -> bool:
    """Después de la respuesta libre de Gabi: la primera pregunta (gas natural) con botones. No lanza."""
    try:
        negocio_id = (canal or {}).get("negocio_id")
        modo = await obtener_modo(negocio_id)
        if modo != MODO_ACTIVO:
            return False
        estado = await mem.obtener_estado_calificacion(telefono)
        if not lleva_pregunta_de_gas(lead, estado, mensajes_cliente, modo, derivado):
            return False
        return await enviar_pregunta(telefono, canal, proveedor, pregunta(PASO_GAS))
    except Exception:
        logger.exception("calificación guiada: no se pudo hacer la primera pregunta")
        return False


async def procesar_respuesta(telefono: str, canal: dict | None, lead: dict | None, interactivo_id: str | None, titulo: str, proveedor) -> bool:
    """El cliente tocó un botón o una fila de la calificación. Registra su respuesta (visible para el asesor), manda lo siguiente
    (pregunta o texto fijo) y devuelve True si el sistema ya respondió este turno (Gabi no escribe). False si no es de esta
    calificación, el modo está apagado, el lead ya tiene dueño o falló algo: entonces el turno sigue con Gabi. No lanza."""
    try:
        parseado = parsear_id(interactivo_id)
        negocio_id = (canal or {}).get("negocio_id")
        if parseado is None or not negocio_id or not lead:
            return False
        if await obtener_modo(negocio_id) != MODO_ACTIVO:
            return False
        if lead.get("asesor_asignado") or lead.get("pausado_manual") or lead.get("escalado_supervision_en"):
            return False
        paso, valor = parseado
        textos = await _textos_del_producto(telefono, lead, negocio_id)
        tipo = tipo_de_producto(*textos)
        accion = siguiente(paso, valor, tipo, lead.get("nombre"), await _telefono_suministros(negocio_id))
        if not (accion["pregunta"] or accion["texto"]):
            return False
        await mem.registrar_evento_lead(
            telefono, mem.EVENTO_CALIFICACION_RESPUESTA, descripcion_respuesta(paso, valor), None,
            {"paso": paso, "valor": valor, "titulo": (titulo or "")[:60]},
        )
        if accion["pregunta"]:
            salio = await enviar_pregunta(telefono, canal, proveedor, accion["pregunta"])
        else:
            salio = await enviar_texto_fijo(telefono, canal, proveedor, accion["texto"])
        if not salio:
            return False
        if accion["paso_datos"]:
            await mem.registrar_evento_lead(telefono, mem.EVENTO_CALIFICACION_PREGUNTA, "Se pidieron nombre y DNI o suministro", None, {"paso": PASO_DATOS})
        if accion["cerrar_sin_gas"]:
            cierre = await mem.cerrar_por_triaje(telefono, negocio_id, "solicita_suministro", resultado=mem.RESULTADO_SOLICITA_SUMINISTRO)
            logger.info("calificacion_sin_gas " + json.dumps({"cerrado": cierre is not None}))
        return True
    except Exception:
        logger.exception("calificación guiada: no se pudo procesar la respuesta del cliente — sigue Gabi")
        return False
