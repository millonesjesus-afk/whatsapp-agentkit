# agent/calificacion_guiada.py — Calificación guiada con botones (2026-10-23, apagada por defecto).
#
# La auditoría de 674 chats (docs/auditoria_chats_gabi_2026-10-18.md) mostró que la mayor fuga está en el primer paso: Gabi pide
# el nombre antes de dar valor y el cliente no vuelve. Este módulo reemplaza ese paso por preguntas de TOQUE (botones o lista) que
# avanzan el flujo de venta sin que el cliente tenga que escribir. Orden:
#
#   0. primer mensaje FIJO (sin IA, sin producto, sin precio) si el cliente solo mandó el texto prellenado del anuncio o un saludo;
#      si no se sabe qué producto es (ni por la campaña, ni por el anuncio, ni por lo que escribió) antes sale la lista de producto.
#   1. gas      «¿Tu casa ya tiene gas natural de Cálidda?»   Sí / No tengo aún / No estoy seguro
#   2. equipo   terma: lista con punto de gas y ductería (UN mensaje); secadora y centro de lavado: solo el punto de gas; cocina: no.
#   3. titular  «¿El suministro está a tu nombre?»              Soy el titular / Familiar / Otra persona
#   4. tamaño   terma: ¿cuántos baños? · secadora/centro de lavado: ¿hasta 4 personas o 5 o más? · cocina: tipo (de pie o
#               empotrable/encimera) y, si es empotrable, qué le suma (campana, horno empotrable).
#   5. etapa consultiva (IA, UN mensaje): confirma que el producto le sirve según sus respuestas, da el precio SOLO si el cliente lo
#               pidió, pide el nombre (si falta) y el DNI del titular o el número de suministro, y deriva.
#
# Camino «sin gas» (la venta del suministro es de OTRA subunidad de Cálidda Hogar: Nuevos suministros):
#   · «Contratar el gas»     → se le da el teléfono de esa subunidad y el caso se cierra como «Solicita suministro de gas».
#   · «Comprar el equipo»    → sigue la asesoría con otros medios de pago (sin financiamiento de Cálidda).
#
# El texto de los pasos 0 a 4 es FIJO (cero tokens). Claude solo interviene en la respuesta libre del cliente y en la etapa
# consultiva; el sistema le dice qué se preguntó y qué respondió el cliente (bloque de contexto) para que no lo repita. Si el
# cliente escribe en vez de tocar, Claude le contesta y el sistema retoma el paso pendiente (hasta 2 veces).
# El estado vive en eventos del Timeline (`calificacion_pregunta` interno, `calificacion_respuesta` visible), sin migración.
#
# Interruptor por negocio: `calificacion_guiada_modo` = apagado (por defecto) | activo. Al activarse se guarda la hora en
# `calificacion_guiada_activa_desde` (scripts/configurar_calificacion_guiada.py) para comparar antes y después.

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
CLAVE_ACTIVA_DESDE = "calificacion_guiada_activa_desde"
MODO_APAGADO = "apagado"
MODO_ACTIVO = "activo"
CLAVE_TELEFONO_SUMINISTROS = "calificacion_telefono_suministros"
TELEFONO_SUMINISTROS_POR_DEFECTO = "614 9000, opción 5"
ORIGEN_ENVIO = "gabi_calificacion"

PREFIJO = "cal:"
PASO_PRODUCTO, PASO_GAS, PASO_EQUIPO, PASO_TITULAR, PASO_TAMANO = "producto", "gas", "equipo", "titular", "tamano"
PASO_COCINA, PASO_COMPLEMENTO, PASO_SINGAS = "cocina", "complemento", "singas"
PASOS_CON_BOTONES = (PASO_PRODUCTO, PASO_GAS, PASO_EQUIPO, PASO_TITULAR, PASO_TAMANO, PASO_COCINA, PASO_COMPLEMENTO, PASO_SINGAS)

# Cuántas veces se retoma un paso pendiente después de que el cliente escribió a mano (además de la pregunta original).
MAXIMO_REINTENTOS = 2
# La primera pregunta de gas solo se hace en los primeros mensajes (después la conversación ya avanzó sola).
MAXIMO_MENSAJES_CLIENTE_PRIMERA_PREGUNTA = 3

PRODUCTO_TERMA, PRODUCTO_SECADORA, PRODUCTO_LAVADO, PRODUCTO_COCINA, PRODUCTO_OTRO = "terma", "secadora", "lavado", "cocina", "otro"
_NOMBRE_PRODUCTO = {
    PRODUCTO_TERMA: "terma", PRODUCTO_SECADORA: "secadora", PRODUCTO_LAVADO: "centro de lavado",
    PRODUCTO_COCINA: "cocina", PRODUCTO_OTRO: "gasodoméstico",
}
# Los que necesitan punto de gas (la terma, además, ductería): lo dijo el dueño (2026-10-23). La cocina no pregunta ninguno de los dos.
_NECESITAN_PUNTO = (PRODUCTO_TERMA, PRODUCTO_SECADORA, PRODUCTO_LAVADO)
_PRODUCTOS_ELEGIBLES = (PRODUCTO_TERMA, PRODUCTO_COCINA, PRODUCTO_SECADORA, PRODUCTO_LAVADO)

# Límites de WhatsApp: hasta 3 botones y títulos de 20; hasta 10 filas de lista y títulos de 24.
LIMITE_TITULO_BOTON = 20
LIMITE_TITULO_FILA = 24


def _sin_tildes(texto: str | None) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", (texto or "").lower()) if unicodedata.category(c) != "Mn")


def tipo_de_producto(*textos: str | None) -> str:
    """Terma, secadora, centro de lavado, cocina u otro, según las palabras que aparezcan en el interés del lead, la campaña, el
    anuncio o lo que escribió el cliente. Una lavadora sola NO es un producto de gas (no pregunta por el punto de gas)."""
    junto = _sin_tildes(" ".join(t for t in textos if t))
    if re.search(r"\bterma|calentador|\bfaucet", junto):
        return PRODUCTO_TERMA
    if "secadora" in junto and "lavaseca" not in junto:
        return PRODUCTO_SECADORA
    if re.search(r"centro de lavado|lavaseca|lavasecadora", junto):
        return PRODUCTO_LAVADO
    if re.search(r"cocina|encimera|\bhorno", junto):
        return PRODUCTO_COCINA
    return PRODUCTO_OTRO


def nombre_producto(tipo: str) -> str:
    return _NOMBRE_PRODUCTO.get(tipo, "gasodoméstico")


_PRELLENADOS = (
    re.compile(r"estoy interesad[oa] en (financiar|comprar|adquirir|conocer|saber)"),
    re.compile(r"cuanto cuesta y como lo pago"),
    re.compile(r"quiero (mas )?informacion"),
)
_PIDE_PRECIO = re.compile(r"cuanto (cuesta|sale|esta|es|vale|pago|seria|me sale|quedar)|precio|costo|cuota|a cuanto|como lo pago|cuanto pagar")


def es_prellenado_o_saludo(texto: str | None) -> bool:
    """El cliente solo mandó el texto prellenado del anuncio («Estoy interesado en financiar una Terma», «¿Cuánto cuesta y cómo lo
    pago?») o un saludo suelto: no hizo una pregunta propia."""
    from agent.solo_clic import es_saludo_trivial
    plano = re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]+", " ", _sin_tildes(texto))).strip()
    if es_saludo_trivial(texto):
        return True
    if not plano or len(plano) > 90:
        return False
    return any(p.search(plano) for p in _PRELLENADOS)


def pidio_precio(*textos: str | None) -> bool:
    """¿El cliente pidió el precio o las cuotas en alguno de sus mensajes (incluido «¿Cuánto cuesta y cómo lo pago?»)?"""
    return bool(_PIDE_PRECIO.search(re.sub(r"[^a-z0-9 ]+", " ", _sin_tildes(" ".join(t for t in textos if t)))))


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
    """La pregunta de un paso: `{paso, tipo: "botones"|"lista", cuerpo, opciones: [{id, titulo}], boton}`. None si no aplica."""
    def _op(valor: str, titulo: str) -> dict:
        return {"id": id_boton(paso, valor), "titulo": titulo}

    producto = nombre_producto(tipo_producto)
    if paso == PASO_PRODUCTO:
        return {
            "paso": paso, "tipo": "lista", "boton": "Elegir una opción", "cuerpo": "¿Qué gasodoméstico te interesa?",
            "opciones": [
                _op("terma", "Terma a gas"), _op("cocina", "Cocina o encimera"), _op("secadora", "Secadora a gas"),
                _op("lavado", "Centro de lavado"), _op("otro", "Otro"),
            ],
        }
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
                "paso": paso, "tipo": "botones", "cuerpo": f"Una consulta más: ¿ya tienes el punto de gas para conectar tu {producto}?",
                "opciones": [_op("punto", "Sí, ya tengo punto"), _op("ninguno", "No tengo punto"), _op("ns", "No lo sé")],
            }
        return None
    if paso == PASO_TITULAR:
        return {"paso": paso, "tipo": "botones", "cuerpo": "¿El suministro de gas de esa casa está a tu nombre?", "opciones": [
            _op("si", "Sí, soy el titular"), _op("familiar", "Es de un familiar"), _op("otro", "Es de otra persona"),
        ]}
    if paso == PASO_TAMANO:
        if tipo_producto == PRODUCTO_TERMA:
            return {"paso": paso, "tipo": "botones", "cuerpo": "Para recomendarte la terma correcta: ¿cuántos baños tiene la casa?", "opciones": [
                _op("1", "1 baño"), _op("2", "2 baños"), _op("3", "3 o más baños"),
            ]}
        if tipo_producto in (PRODUCTO_SECADORA, PRODUCTO_LAVADO):
            return {"paso": paso, "tipo": "botones", "cuerpo": f"Para recomendarte el tamaño correcto: ¿cuántas personas usarán la {producto}?", "opciones": [
                _op("pequena", "Hasta 4 personas"), _op("grande", "5 o más personas"), _op("ns", "No estoy seguro"),
            ]}
        return None
    if paso == PASO_COCINA:
        return {"paso": paso, "tipo": "botones", "cuerpo": "¿Qué tipo de cocina buscas?", "opciones": [
            _op("pie", "De pie (con horno)"), _op("empotrable", "Empotrable/encimera"),
        ]}
    if paso == PASO_COMPLEMENTO:
        return {
            "paso": paso, "tipo": "lista", "boton": "Elegir una opción", "cuerpo": "¿Quieres sumarle algo a tu encimera?",
            "opciones": [
                _op("solo", "Solo la encimera"), _op("campana", "Con campana"), _op("horno", "Con horno empotrable"),
                _op("ambos", "Horno y campana"),
            ],
        }
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


def con_saludo(p: dict, saludo: str) -> dict:
    """La misma pregunta con el saludo delante (primer mensaje fijo: una sola burbuja)."""
    return {**p, "cuerpo": f"{saludo}\n\n{p['cuerpo']}"}


SALUDO_PRIMER_MENSAJE = "Hola 👋 Soy Gabi, asesora virtual de Cálidda Hogar. Gracias por escribirnos."
AVISO_PRECIO_DESPUES = "El precio te lo cuento en un momento; primero unas consultas rápidas para orientarte mejor."


def saludo_para(texto_del_cliente: str | None) -> str:
    """Saludo del primer mensaje fijo: si el cliente preguntó por el precio, se le promete."""
    if pidio_precio(texto_del_cliente):
        return f"{SALUDO_PRIMER_MENSAJE} {AVISO_PRECIO_DESPUES}"
    return SALUDO_PRIMER_MENSAJE


# ── Los textos fijos ────────────────────────────────────────────────────────

def texto_producto_otro() -> str:
    return "Cuéntame qué gasodoméstico buscas y te oriento."


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

def lead_elegible(lead: dict | None, derivado: bool = False) -> bool:
    """Sin asesor, pausa, supervisión, resultado, cierre ni derivación en curso."""
    if not lead or derivado:
        return False
    if lead.get("asesor_asignado") or lead.get("pausado_manual") or lead.get("escalado_supervision_en"):
        return False
    if lead.get("resultado") or lead.get("cerrado_definitivamente_en") is not None or lead.get("paso_flujo") == "derivado_asesor":
        return False
    return True


def lleva_pregunta_de_gas(
    lead: dict | None, estado: dict, mensajes_cliente: int, modo: str, derivado: bool = False,
) -> bool:
    """¿Corresponde hacer ahora la primera pregunta (gas natural)? Solo en modo activo, en los primeros mensajes, una sola vez y con
    el lead elegible."""
    if modo != MODO_ACTIVO or not lead_elegible(lead, derivado):
        return False
    if PASO_GAS in estado.get("preguntas", []) or PASO_GAS in estado.get("respuestas", {}):
        return False
    if PASO_PRODUCTO in estado.get("preguntas", []) and PASO_PRODUCTO not in estado.get("respuestas", {}):
        return False       # se está esperando que elija el producto
    return mensajes_cliente <= MAXIMO_MENSAJES_CLIENTE_PRIMERA_PREGUNTA


def pasos_requeridos(tipo: str, respuestas: dict) -> list[str]:
    """Los pasos que debe contestar el cliente antes de la etapa consultiva (camino «con gas»)."""
    if tipo in _NECESITAN_PUNTO:
        return [PASO_GAS, PASO_EQUIPO, PASO_TITULAR, PASO_TAMANO]
    if tipo == PRODUCTO_COCINA:
        pasos = [PASO_GAS, PASO_TITULAR, PASO_COCINA]
        if respuestas.get(PASO_COCINA) == "empotrable":
            pasos.append(PASO_COMPLEMENTO)
        return pasos
    return [PASO_GAS, PASO_TITULAR]


def etapa_consultiva(estado: dict, tipo: str) -> bool:
    """¿El cliente ya contestó todo lo de la calificación y gas = sí? Entonces sigue la IA, en UN mensaje."""
    respuestas = estado.get("respuestas", {})
    if respuestas.get(PASO_GAS) != "si":
        return False
    return all(p in respuestas for p in pasos_requeridos(tipo, respuestas))


def pendiente(estado: dict) -> str | None:
    """El último paso de botones que se preguntó y el cliente aún no respondió (None si no hay)."""
    respuestas = estado.get("respuestas", {})
    for paso in reversed(estado.get("preguntas", [])):
        if paso in PASOS_CON_BOTONES:
            return None if paso in respuestas else paso
    return None


def puede_retomar(estado: dict) -> str | None:
    """El paso pendiente, solo si todavía no se agotaron los reintentos (la pregunta original cuenta como 1)."""
    paso = pendiente(estado)
    if paso is None:
        return None
    return paso if estado.get("conteo", {}).get(paso, 1) <= MAXIMO_REINTENTOS else None


def siguiente(paso: str, valor: str, tipo_producto: str, nombre: str | None, telefono_suministros: str) -> dict:
    """Qué hace el sistema tras la respuesta del cliente. Devuelve `{"pregunta": dict|None, "texto": str|None, "cerrar_sin_gas":
    bool, "revisar_etapa": bool}`. `revisar_etapa`: el paso no genera mensaje fijo propio; el turno sigue con Claude (etapa
    consultiva). Todo vacío si el par paso/valor no existe."""
    vacio = {"pregunta": None, "texto": None, "cerrar_sin_gas": False, "revisar_etapa": False}
    if paso == PASO_PRODUCTO:
        if valor == "otro":
            return {**vacio, "texto": texto_producto_otro()}
        if valor in _PRODUCTOS_ELEGIBLES:
            return {**vacio, "pregunta": pregunta(PASO_GAS)}
    elif paso == PASO_GAS:
        if valor == "si":
            return {**vacio, "pregunta": pregunta(PASO_EQUIPO, tipo_producto) if tipo_producto in _NECESITAN_PUNTO else pregunta(PASO_TITULAR)}
        if valor == "no":
            return {**vacio, "pregunta": pregunta(PASO_SINGAS)}
        if valor == "ns":
            return {**vacio, "texto": texto_no_sabe_si_tiene_gas()}
    elif paso == PASO_EQUIPO and valor in ("ambos", "punto", "ducteria", "ninguno", "ns"):
        return {**vacio, "pregunta": pregunta(PASO_TITULAR)}
    elif paso == PASO_TITULAR and valor in ("si", "familiar", "otro"):
        if tipo_producto in _NECESITAN_PUNTO:
            return {**vacio, "pregunta": pregunta(PASO_TAMANO, tipo_producto)}
        if tipo_producto == PRODUCTO_COCINA:
            return {**vacio, "pregunta": pregunta(PASO_COCINA)}
        return {**vacio, "revisar_etapa": True}
    elif paso == PASO_TAMANO and valor in ("1", "2", "3", "pequena", "grande", "ns"):
        return {**vacio, "revisar_etapa": True}
    elif paso == PASO_COCINA:
        if valor == "empotrable":
            return {**vacio, "pregunta": pregunta(PASO_COMPLEMENTO)}
        if valor == "pie":
            return {**vacio, "revisar_etapa": True}
    elif paso == PASO_COMPLEMENTO and valor in ("solo", "campana", "horno", "ambos"):
        return {**vacio, "revisar_etapa": True}
    elif paso == PASO_SINGAS:
        if valor == "contratar":
            return {**vacio, "texto": texto_contratar_gas(telefono_suministros, tipo_producto), "cerrar_sin_gas": True}
        if valor == "equipo":
            return {**vacio, "texto": texto_comprar_equipo_igual(tipo_producto)}
    return vacio


_ETIQUETAS_PASO = {
    PASO_PRODUCTO: "producto", PASO_GAS: "gas natural de Cálidda", PASO_EQUIPO: "punto de gas y ductería",
    PASO_TITULAR: "titular del suministro", PASO_TAMANO: "tamaño (baños o personas)", PASO_COCINA: "tipo de cocina",
    PASO_COMPLEMENTO: "complemento de la encimera", PASO_SINGAS: "sin gas: qué prefiere",
}
_ETIQUETAS_VALOR = {
    (PASO_PRODUCTO, "terma"): "terma", (PASO_PRODUCTO, "cocina"): "cocina o encimera", (PASO_PRODUCTO, "secadora"): "secadora",
    (PASO_PRODUCTO, "lavado"): "centro de lavado", (PASO_PRODUCTO, "otro"): "otro",
    (PASO_GAS, "si"): "sí tiene", (PASO_GAS, "no"): "no tiene aún", (PASO_GAS, "ns"): "no está seguro",
    (PASO_EQUIPO, "ambos"): "tiene punto de gas y ductería", (PASO_EQUIPO, "punto"): "tiene el punto de gas",
    (PASO_EQUIPO, "ducteria"): "solo tiene ductería", (PASO_EQUIPO, "ninguno"): "no tiene punto",
    (PASO_EQUIPO, "ns"): "no sabe",
    (PASO_TITULAR, "si"): "es el titular", (PASO_TITULAR, "familiar"): "es de un familiar", (PASO_TITULAR, "otro"): "es de otra persona",
    (PASO_TAMANO, "1"): "1 baño", (PASO_TAMANO, "2"): "2 baños", (PASO_TAMANO, "3"): "3 o más baños",
    (PASO_TAMANO, "pequena"): "hasta 4 personas", (PASO_TAMANO, "grande"): "5 o más personas", (PASO_TAMANO, "ns"): "no está seguro",
    (PASO_COCINA, "pie"): "cocina de pie (con horno)", (PASO_COCINA, "empotrable"): "empotrable/encimera",
    (PASO_COMPLEMENTO, "solo"): "solo la encimera", (PASO_COMPLEMENTO, "campana"): "con campana",
    (PASO_COMPLEMENTO, "horno"): "con horno empotrable", (PASO_COMPLEMENTO, "ambos"): "con horno y campana",
    (PASO_SINGAS, "contratar"): "quiere contratar el gas", (PASO_SINGAS, "equipo"): "comprará el equipo igual",
}


def descripcion_respuesta(paso: str, valor: str) -> str:
    return f"Calificación: {_ETIQUETAS_PASO.get(paso, paso)} → {_ETIQUETAS_VALOR.get((paso, valor), valor)}"


def regla_de_producto(tipo: str, respuestas: dict) -> str:
    """Guía orientativa (knowledge/calidda/guia_dimensionamiento_termas_cocinas.md y fuentes de mercado) para que Claude confirme que el
    producto le sirve al cliente según lo que respondió. Es orientativa: se confirma con el proveedor y el asesor."""
    if tipo == PRODUCTO_TERMA:
        return (
            "Guía orientativa por baños: 1 baño → terma de 5.5 a 10 litros por minuto; 2 baños → de 14 a 17 l/min; 3 o más baños → "
            "17 l/min o más. Es orientativa: no la presentes como norma."
        )
    if tipo == PRODUCTO_SECADORA:
        return "Guía orientativa: hasta 4 personas → secadora de 10 kg; 5 o más personas → de 22 a 24 kg (los tamaños del catálogo)."
    if tipo == PRODUCTO_LAVADO:
        return (
            "Un centro de lavado es una lavadora con secadora a gas. Guía orientativa: hasta 4 personas → de 20 kg; 5 o más personas → "
            "de 24 kg (los tamaños del catálogo)."
        )
    if tipo == PRODUCTO_COCINA:
        extra = ""
        if respuestas.get(PASO_COCINA) == "empotrable":
            extra = " El horno empotrable solo va con una encimera o cocina empotrable; ofrece horno y campana solo si están en el catálogo."
        return "Respeta el tipo de cocina que eligió; las medidas del mueble las ve el asesor." + extra
    return ""


def bloque_contexto(
    estado: dict, *, va_la_primera_pregunta: bool, tipo_producto: str = PRODUCTO_OTRO, pidio_el_precio: bool = False,
    derivado: bool = False,
) -> str | None:
    """Texto para <contexto_negocio> de Claude: qué preguntó el sistema con botones y qué respondió el cliente (para que no lo
    repita), la etapa final de la calificación y la regla del precio. En el turno anterior a una pregunta con botones (primera
    pregunta o paso retomado) Claude NO pregunta ni pide datos: el sistema lo hará enseguida."""
    if derivado:
        return None
    respuestas = estado.get("respuestas", {})
    partes = []
    if va_la_primera_pregunta or puede_retomar(estado):
        partes.append(
            "Después de tu mensaje el sistema le hará al cliente, con botones, una consulta rápida para orientarlo. En ESTE mensaje "
            "responde lo que el cliente necesita, NO hagas ninguna pregunta ni pidas su nombre o su DNI todavía, y cierra con una frase "
            "breve sin signos de pregunta (por ejemplo: «Te hago una consulta rápida para orientarte mejor»)."
        )
        if not pidio_el_precio:
            partes.append("No menciones precios ni cuotas: el cliente no los pidió.")
    if respuestas:
        dichas = "; ".join(f"{_ETIQUETAS_PASO.get(p, p)}: {_ETIQUETAS_VALOR.get((p, v), v)}" for p, v in respuestas.items())
        partes.append(f"Respuestas del cliente a preguntas con botones — {dichas}. No repitas esas preguntas ni las cambies de palabras.")
    if etapa_consultiva(estado, tipo_producto):
        precio = (
            "El cliente pidió el precio: dáselo ahora si está en el contexto o el catálogo (si no está, dile que el asesor se lo confirma)."
            if pidio_el_precio else "No menciones precios ni cuotas: el cliente no los pidió; de eso se encarga el asesor."
        )
        partes.append(
            "ETAPA FINAL de la calificación. En UN solo mensaje: "
            "(1) confirma en una frase que el producto que le interesó (el del anuncio o el que dijo) le sirve según sus respuestas; "
            "solo si no alcanza propón UNA alternativa del catálogo, nunca varias opciones. "
            + regla_de_producto(tipo_producto, respuestas) + " "
            f"(2) {precio} "
            "(3) Pide su nombre (solo si no figura en los datos ya conocidos) y el DNI del titular del suministro o su número de suministro "
            "de Cálidda, aclarando que ese dato solo sirve para que un asesor inicie la evaluación y no es una aprobación. "
            "(4) No hagas ninguna otra pregunta. En cuanto te dé esos datos, derívalo al asesor sin pedirle permiso."
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


async def historial_de_la_conversacion(telefono: str, negocio_id: str | None) -> list[dict] | None:
    """Los mensajes de la Conversation ACTIVA (no los del teléfono entero). Un cliente que vuelve tras un cierre abre una conversación
    NUEVA pero su teléfono arrastra los mensajes de las anteriores: contar o mirar ese historial hace creer que ya lo atendimos y
    el flujo guiado no arranca. None si no se pudo leer (quien llama decide el respaldo)."""
    try:
        conversation = await mem.obtener_conversation_activa_de_telefono(telefono, negocio_id) if negocio_id else None
        if not conversation:
            return None
        return await servicio_conversacion.obtener_historial_de_conversation(conversation["id"], negocio_id, limite=200)
    except Exception:
        logger.exception("calificación guiada: no se pudo leer el historial de la conversación")
        return None


async def _textos_del_producto(telefono: str, lead: dict | None, negocio_id: str | None) -> list[str]:
    """Lo que dice qué producto busca el cliente: interés, campaña (nombre y producto), anuncio y sus primeros mensajes."""
    textos = [(lead or {}).get("interes"), (lead or {}).get("producto_tipo"), (lead or {}).get("campana_origen")]
    try:
        from agent.origen_conversacion import origen_de_conversacion
        conversation = await mem.obtener_conversation_activa_de_telefono(telefono, negocio_id) if negocio_id else None
        origen = await origen_de_conversacion(negocio_id, conversation["id"]) if conversation else None
        anuncio = (origen or {}).get("anuncio") or {}
        oferta = (origen or {}).get("oferta") or {}
        textos += [anuncio.get("titulo"), anuncio.get("cuerpo"), oferta.get("producto")]
    except Exception:
        logger.exception("calificación guiada: no se pudo leer el anuncio")
    try:
        historial = await historial_de_la_conversacion(telefono, negocio_id)
        if historial is None:
            historial = await servicio_conversacion.obtener_historial(telefono)
        textos += [m["content"] for m in historial if m.get("role") == "user"][:3]
    except Exception:
        logger.exception("calificación guiada: no se pudo leer el historial")
    return [t for t in textos if t]


async def tipo_del_lead(telefono: str, lead: dict | None, negocio_id: str | None, estado: dict | None = None) -> str:
    """El producto: lo que el cliente eligió en la lista; si no, lo que dicen la campaña, el anuncio y sus mensajes."""
    elegido = ((estado or {}).get("respuestas") or {}).get(PASO_PRODUCTO)
    if elegido in _PRODUCTOS_ELEGIBLES:
        return elegido
    return tipo_de_producto(*await _textos_del_producto(telefono, lead, negocio_id))


async def _fijar_interes_si_falta(telefono: str, lead: dict | None, tipo: str) -> None:
    """El asesor y el reparto leen `Lead.interes`: si Claude aún no lo fijó, queda con el producto detectado."""
    try:
        if lead is not None and not lead.get("interes") and tipo != PRODUCTO_OTRO:
            await mem.actualizar_lead(telefono, interes=nombre_producto(tipo))
    except Exception:
        logger.exception("calificación guiada: no se pudo fijar el interés del lead")


async def primer_mensaje_fijo(telefono: str, canal: dict | None, lead: dict | None, proveedor, historial: list[dict]) -> bool:
    """Primer mensaje FIJO (sin IA, sin producto, sin precio) cuando el cliente solo mandó el texto prellenado del anuncio o un saludo y
    todavía nadie le respondió. Si no se sabe qué producto es (ni por campaña, anuncio o mensajes) sale antes la lista de producto.
    True si el sistema ya respondió este turno (Gabi no escribe). No lanza."""
    try:
        negocio_id = (canal or {}).get("negocio_id")
        if await obtener_modo(negocio_id) != MODO_ACTIVO or not lead_elegible(lead):
            return False
        # Solo cuenta lo que pasó en ESTA conversación: un cliente que vuelve tras un cierre es un primer mensaje de nuevo.
        en_conversacion = await historial_de_la_conversacion(telefono, negocio_id)
        if en_conversacion is not None:
            historial = en_conversacion
        if any(m.get("role") in ("assistant", "asesor") for m in historial):
            return False
        del_cliente = [m["content"] for m in historial if m.get("role") == "user"]
        if len(del_cliente) != 1 or not es_prellenado_o_saludo(del_cliente[0]):
            return False
        estado = await mem.obtener_estado_calificacion(telefono)
        if estado["preguntas"] or estado["respuestas"]:
            return False
        tipo = await tipo_del_lead(telefono, lead, negocio_id, estado)
        p = con_saludo(pregunta(PASO_GAS if tipo != PRODUCTO_OTRO else PASO_PRODUCTO), saludo_para(del_cliente[0]))
        salio = await enviar_pregunta(telefono, canal, proveedor, p)
        if salio:
            await _fijar_interes_si_falta(telefono, lead, tipo)
        return salio
    except Exception:
        logger.exception("calificación guiada: no se pudo mandar el primer mensaje fijo — sigue Gabi")
        return False


async def continuar_flujo(
    telefono: str, canal: dict | None, lead: dict | None, proveedor, mensajes_cliente: int, derivado: bool = False,
) -> bool:
    """Después de una respuesta libre de Claude: si falta la primera pregunta de gas la hace; si hay un paso pendiente (el cliente
    escribió en vez de tocar) lo retoma, hasta 2 veces. No lanza."""
    try:
        negocio_id = (canal or {}).get("negocio_id")
        modo = await obtener_modo(negocio_id)
        if modo != MODO_ACTIVO or not lead_elegible(lead, derivado):
            return False
        estado = await mem.obtener_estado_calificacion(telefono)
        en_conversacion = await historial_de_la_conversacion(telefono, negocio_id)
        if en_conversacion is not None:       # los mensajes de ESTA conversación, no los del teléfono entero
            mensajes_cliente = sum(1 for m in en_conversacion if m.get("role") == "user")
        if lleva_pregunta_de_gas(lead, estado, mensajes_cliente, modo, derivado):
            tipo = await tipo_del_lead(telefono, lead, negocio_id, estado)
            salio = await enviar_pregunta(telefono, canal, proveedor, pregunta(PASO_GAS if tipo != PRODUCTO_OTRO else PASO_PRODUCTO))
            if salio:
                await _fijar_interes_si_falta(telefono, lead, tipo)
            return salio
        paso = puede_retomar(estado)
        if paso is None:
            return False
        tipo = await tipo_del_lead(telefono, lead, negocio_id, estado)
        p = pregunta(paso, tipo)
        if p is None:
            return False
        return await enviar_pregunta(telefono, canal, proveedor, p)
    except Exception:
        logger.exception("calificación guiada: no se pudo continuar el flujo")
        return False


async def procesar_respuesta(telefono: str, canal: dict | None, lead: dict | None, interactivo_id: str | None, titulo: str, proveedor) -> bool:
    """El cliente tocó un botón o una fila de la calificación. Registra su respuesta (visible para el asesor), manda lo siguiente
    (pregunta o texto fijo) y devuelve True si el sistema ya respondió este turno (Gabi no escribe). Devuelve False —y el turno sigue con
    Claude— si no es de esta calificación, el modo está apagado, el lead ya tiene dueño, falló algo o, con esta respuesta, se completó
    la calificación (etapa consultiva). No lanza."""
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
        estado = await mem.obtener_estado_calificacion(telefono)
        if paso in estado.get("respuestas", {}):
            # Los botones de WhatsApp siguen tocables para siempre: un toque en una pregunta que ya respondió no repite el flujo
            # (no se vuelve a mandar la pregunta siguiente); el turno sigue con Gabi como un mensaje de texto.
            return False
        if paso == PASO_PRODUCTO and valor in _PRODUCTOS_ELEGIBLES:
            tipo = valor
        else:
            tipo = await tipo_del_lead(telefono, lead, negocio_id, estado)
        accion = siguiente(paso, valor, tipo, lead.get("nombre"), await _telefono_suministros(negocio_id))
        if not (accion["pregunta"] or accion["texto"] or accion["revisar_etapa"]):
            return False
        await mem.registrar_evento_lead(
            telefono, mem.EVENTO_CALIFICACION_RESPUESTA, descripcion_respuesta(paso, valor), None,
            {"paso": paso, "valor": valor, "titulo": (titulo or "")[:60]},
        )
        if paso == PASO_PRODUCTO:
            await _fijar_interes_si_falta(telefono, lead, tipo)
        if accion["revisar_etapa"]:
            return False      # etapa consultiva: el turno sigue con Claude, que recibe las respuestas como contexto
        if accion["pregunta"]:
            salio = await enviar_pregunta(telefono, canal, proveedor, accion["pregunta"])
        else:
            salio = await enviar_texto_fijo(telefono, canal, proveedor, accion["texto"])
        if not salio:
            return False
        if accion["cerrar_sin_gas"]:
            cierre = await mem.cerrar_por_triaje(telefono, negocio_id, "solicita_suministro", resultado=mem.RESULTADO_SOLICITA_SUMINISTRO)
            logger.info("calificacion_sin_gas " + json.dumps({"cerrado": cierre is not None}))
        return True
    except Exception:
        logger.exception("calificación guiada: no se pudo procesar la respuesta del cliente — sigue Gabi")
        return False
