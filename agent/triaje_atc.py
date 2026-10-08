# agent/triaje_atc.py — Triaje de temas NO comerciales → Consulta ATC (2026-10-08, diseño D2 aprobado por el dueño)
#
# Problema: ~6 % de las conversaciones (27 de ~460) son consultas de atención al cliente de Cálidda —el recibo, el
# número de cliente, dónde pagar— que no tienen nada de compra. Gabi gasta 3-4 turnos, un asesor interviene igual y
# después una persona etiqueta `consulta_atc` a mano. Este módulo las detecta con REGLAS DETERMINISTAS (costo 0, sin
# IA) ANTES de llamar a Claude, redirige al cliente a la línea de atención y cierra el caso.
#
# ENTREGADO APAGADO. `triaje_atc_modo` (por negocio) = apagado (default) | sombra | activo:
#   · apagado: el camino de Gabi es IDÉNTICO al de siempre (solo se lee esa clave de configuración).
#   · sombra:  se evalúa en cada turno y se deja UNA línea INFO `triaje_atc {json}` (sin teléfono, nombre ni texto) más,
#              si hubo un candidato, un evento interno `triaje_atc_sombra` para medir recall/precisión en SQL
#              (scripts/analisis_triaje_atc.py). Gabi responde normal.
#   · activo:  lo mismo, y si la decisión es cerrar se envía UN texto fijo (origen `triaje_atc`), se guarda como mensaje
#              de Gabi y se cierra el caso (`memory.cerrar_por_triaje`). `activo` sin `triaje_atc_linea_texto` se
#              degrada a sombra: nunca se redirige a un cliente sin decirle a dónde llamar.
#
# QUÉ SE DETECTA. El TEMA es la señal, NUNCA la frase "ya tengo gas natural" (clientes con gas que sí quieren un horno).
# Se evalúan los ÚLTIMOS 2 mensajes del cliente contra el léxico de cada categoría; el bloqueo comercial mira TODA la
# conversación: una sola palabra de producto/precio/cuota/compra del cliente (salvo el saludo preestablecido de una
# campaña) impide cerrar. Ante la duda NO se cierra. Las guardas (ver `clasificar`) cubren asesor/pausa, caso ya cerrado,
# flujo de financiamiento, DNI/suministro pedidos por Gabi, números largos, fotos, más de N mensajes, un triaje por ciclo.
#
# FASE 1 — categorías con regla: recibo, numero_cliente, pago_deuda. La emergencia de gas (olor, fuga) se clasifica como
# `emergencia_gas` con acción `alerta_emergencia` pero SOLO queda en el log y en el evento: no se envía nada (queda
# documentado para la fase siguiente; nunca debe terminar en un cierre silencioso).
#
# DEUDA MULTI-NEGOCIO. Gabi pasará de Gaso+ a "Cálidda Hogar", una unidad grande con varios negocios asociados. Hoy el
# léxico (`REGLAS_ATC`, `BLOQUEOS_COMERCIALES`) y las categorías son los de Cálidda/Gaso+ y viven en ESTE módulo, no en
# la base: el mapa categoría → qué se hace (cerrar, derivar a otra unidad…) y las palabras deberán pasar a configuración
# por negocio cuando exista la entidad. Lo que SÍ es por negocio desde ya: el modo, las categorías activas, las plantillas
# (general y por categoría), las líneas de atención/emergencia/ventas y el NOMBRE del negocio en el texto
# (`triaje_atc_nombre_negocio`; sin él, el fallback documentado es `NOMBRE_NEGOCIO_POR_DEFECTO`).
#
# El texto por defecto está escrito para que el cierre de cortesía (memory.evaluar_cierre_cortesia) absorba un "gracias" o
# un "ok" posterior: termina en afirmación SIN "?" y evita las palabras de las condiciones C2/C3 (llam*, necesit*, envi*,
# avis*, cuent*, dni, días de la semana, horas). Si se personaliza, mantener esas dos propiedades.
#
# Todo lo que toca la base o el proveedor es seguro: `evaluar` y `procesar` no lanzan nunca.

import json
import logging
import re
import unicodedata
from dataclasses import dataclass

from sqlalchemy import func, select

from agent import envios
from agent.memory import (
    EVENTO_TRIAJE_ATC_CERRADO, EVENTO_TRIAJE_ATC_FALLIDO, EVENTO_TRIAJE_ATC_SOMBRA, PREFIJO_REACCION,
    EventoLead, Mensaje, _obtener_contact, _obtener_conversation_activa, async_session, cerrar_por_triaje,
    listar_campanas, obtener_configuracion, registrar_evento_lead,
)
from agent.services.servicio_conversacion import servicio_conversacion
from agent.tiempo_real import gestor_conexiones

logger = logging.getLogger("agentkit")

# ── Configuración (todas por negocio, tabla `configuracion`) ─────────────────────────────────────────────
CLAVE_MODO = "triaje_atc_modo"                              # apagado (default) | sombra | activo
CLAVE_LINEA = "triaje_atc_linea_texto"                      # SIN default: "614900, opción 5"
CLAVE_LINEA_EMERGENCIA = "triaje_atc_linea_emergencia_texto"  # SIN default: "1808 (Emergencias 24/7)"
CLAVE_LINEA_VENTAS = "triaje_atc_linea_ventas_texto"        # SIN default: "614-9002" (informativa)
CLAVE_CATEGORIAS = "triaje_atc_categorias_activas"          # lista separada por comas
CLAVE_TEXTO = "triaje_atc_texto"                            # plantilla general; {nombre} {linea_atc} {negocio} …
CLAVE_TEXTO_CATEGORIA = "triaje_atc_texto_"                 # + categoría: plantilla propia de esa categoría
CLAVE_MAX_MENSAJES = "triaje_atc_max_mensajes_cliente"      # default 4
CLAVE_NOMBRE_NEGOCIO = "triaje_atc_nombre_negocio"          # nombre que sale en el texto (fallback abajo)
CLAVE_TELEFONOS_EXCLUIDOS = "triaje_atc_telefonos_excluidos"  # números del equipo / de pruebas, separados por comas
CLAVE_PERMITIR_CANAL_PRUEBAS = "triaje_atc_permitir_canal_pruebas"  # "1" deja cerrar también en un canal de pruebas

MODO_APAGADO, MODO_SOMBRA, MODO_ACTIVO = "apagado", "sombra", "activo"
MODOS = (MODO_APAGADO, MODO_SOMBRA, MODO_ACTIVO)

CATEGORIA_NINGUNA = "ninguna"
CATEGORIA_EMERGENCIA = "emergencia_gas"
CATEGORIAS_FASE_1 = ("recibo", "numero_cliente", "pago_deuda")
CATEGORIAS_ATC = CATEGORIAS_FASE_1  # las que cierran; cuando existan más (fase 2) se suman acá
ACCION_NINGUNA, ACCION_CERRAR, ACCION_ALERTA_EMERGENCIA = "ninguna", "cerrar", "alerta_emergencia"

MAX_MENSAJES_CLIENTE_POR_DEFECTO = 4
UMBRAL_CIERRE = 0.75  # confianza mínima para proponer el cierre
UMBRAL_CANDIDATO = 0.60  # por debajo, la señal es demasiado débil (p. ej. solo "cómo pago"): ni se registra como candidato
# Fallback DOCUMENTADO del nombre del negocio en el texto (deuda multi-negocio, ver la cabecera).
NOMBRE_NEGOCIO_POR_DEFECTO = "Gaso+"

TEXTO_POR_DEFECTO = (
    "¡Hola{nombre}! 😊 Para consultas de tu recibo, número de cliente, pagos o el servicio de gas, la atención la da "
    "directamente Cálidda en su línea {linea_atc}. Aquí en {negocio} te ayudamos con la compra y el financiamiento de "
    "gasodomésticos. Si más adelante te interesa una cocina, terma, horno u otro, escríbenos por aquí y con gusto te asesoro."
)


# ── Normalización y léxico ────────────────────────────────────────────────────────────────────────────────

def normalizar(texto: str | None) -> str:
    """Minúsculas, sin tildes, sin signos ni emojis y con las letras repetidas colapsadas ("resibooo" → "resibo",
    "llega" → "lega"): el mismo criterio de `memory._normalizar_cortesia`. El léxico de este módulo se compila con la
    MISMA función, así que se escribe con la ortografía normal."""
    t = unicodedata.normalize("NFKD", (texto or "").lower())
    t = "".join(c for c in t if not unicodedata.combining(c))
    t = re.sub(r"[^a-z0-9\s]", " ", t)
    t = re.sub(r"([a-z])\1+", r"\1", t)
    return re.sub(r"\s+", " ", t).strip()


def _compilar_terminos(terminos: tuple[str, ...]) -> "re.Pattern[str]":
    """Cada término es una palabra o una frase ya con ortografía normal; un `*` al final de una palabra la deja como
    prefijo ("financ*" → financiar, financiamiento…). Las frases deben aparecer seguidas."""
    alternativas = []
    for termino in terminos:
        piezas = []
        for palabra in termino.split():
            prefijo = palabra.endswith("*")
            base = re.escape(normalizar(palabra.rstrip("*")))
            piezas.append(rf"\b{base}\w*" if prefijo else rf"\b{base}\b")
        alternativas.append(r"\s+".join(piezas))
    return re.compile("|".join(alternativas))


@dataclass(frozen=True)
class Regla:
    id: str
    categoria: str
    peso: float  # confianza de la regla sola; las reglas coincidentes de una categoría suman un poco más
    patron: "re.Pattern[str]"


def _regla(id: str, categoria: str, peso: float, terminos: tuple[str, ...] = (), regex: str | None = None) -> Regla:
    patron = re.compile(regex) if regex is not None else _compilar_terminos(terminos)
    return Regla(id, categoria, peso, patron)


# La regex cruda se escribe sobre texto YA normalizado (ver `normalizar`).
REGLAS_ATC: tuple[Regla, ...] = (
    # — recibo —
    _regla("recibo_palabra", "recibo", 0.80, ("recibo", "recibos", "resibo", "resibos", "resivo", "recivo", "factura*", "boleta*", "facturacion")),
    _regla("recibo_ultimo_duplicado", "recibo", 0.90, (
        "ultimo recibo", "ultima factura", "duplicado", "copia del recibo", "copia de mi recibo", "copia de la factura",
    )),
    _regla("recibo_no_llega", "recibo", 0.50, (
        "no me llega*", "no llega*", "no me llego", "no llego", "no me ha llegado", "no he recibido", "no recibi",
    )),
    _regla("recibo_consumo", "recibo", 0.70, ("consumo*", "consumi*", "lectura*", "venci*", "vence")),
    # — número de cliente —
    _regla(
        "numero_cliente_frase", "numero_cliente", 0.90,
        regex=r"\b(?:numero|nro|num|codigo|cod)\s+(?:de\s+|del\s+|mi\s+|tu\s+)?(?:cliente|suministro|cuenta|contrato)\b|\bn\s+de\s+(?:cliente|suministro)\b",
    ),
    _regla("cuenta_contrato", "numero_cliente", 0.90, ("cuenta contrato", "cuenta de contrato", "contrato de suministro")),
    _regla(
        "donde_ver_suministro", "numero_cliente", 0.60,
        regex=r"\b(?:cual es|donde (?:veo|encuentro|sale|esta|consigo|averiguo)|como (?:veo|saber|obtengo|consigo))\b.{0,25}\b(?:suministro|cliente)\b",
    ),
    # — pago / deuda —
    _regla("pago_deuda_palabra", "pago_deuda", 0.85, ("deuda*", "mora", "moroso*", "adeud*", "fraccionamiento*", "fraccionar*", "cuanto debo")),
    _regla("pago_agentes", "pago_deuda", 0.90, (
        "agente de pago", "agentes de pago", "agentes autorizados", "puntos de pago", "centros de pago", "lugares de pago",
    )),
    _regla("pago_corte_reconexion", "pago_deuda", 0.85, (
        "corte de gas", "corte del gas", "corte del servicio", "cortaron*", "cortado", "suspension del servicio",
        "suspendieron", "reconexion*", "reconectar*", "reconect*", "falta de pago", "van a cortar", "me van a cortar",
    )),
    _regla("pago_ya_pague", "pago_deuda", 0.60, ("ya pague", "ya lo pague", "ya cancele", "pague mi recibo", "pague el recibo", "ya hice el pago")),
    _regla(
        "pago_donde_como", "pago_deuda", 0.55,
        regex=r"\b(?:donde|como|en que lugar|lugares|forma de|formas de|medios de)\b.{0,30}\bpag(?:o|ar|are|ue|a|an)\b",
    ),
)

# Emergencia de gas: SOLO se registra (log + evento). Se mira en TODOS los mensajes del cliente.
REGLAS_EMERGENCIA: tuple[Regla, ...] = (
    _regla("emergencia_olor_fuga", CATEGORIA_EMERGENCIA, 0.95, (
        "huele a gas", "huelo a gas", "huele gas", "huelo gas", "olor a gas", "olor de gas", "fuga de gas", "fugas de gas",
        "escape de gas", "escapa el gas", "se escapa el gas", "explosion*", "explot*",
    )),
    _regla("emergencia_fuga_gas", CATEGORIA_EMERGENCIA, 0.90, regex=r"\bfuga\b.{0,20}\bgas\b|\bgas\b.{0,20}\b(?:fuga|escapa\w*|se sale)\b"),
)

# Bloqueo comercial: UNA sola coincidencia en cualquier mensaje del cliente impide cerrar. Deliberadamente amplio: perder un
# cierre cuesta un mensaje de Gabi; cerrar mal le cuesta una venta al negocio.
BLOQUEOS_COMERCIALES: tuple[Regla, ...] = (
    _regla("comercial_producto", "bloqueo", 1.0, (
        "gasodomestico*", "cocina*", "horno*", "terma*", "calentador*", "secadora*", "estufa*", "encimera*", "hornilla*",
        "parrilla*", "campana*", "lavadora*", "refrigerador*", "artefacto*", "electrodomestico*", "chimenea*", "caldera*",
        "producto*", "equipo*", "catalogo*", "modelo*", "marca*", "combo*",
    )),
    _regla("comercial_precio", "bloqueo", 1.0, (
        "precio*", "costo*", "cuesta*", "cuanto sale", "cuanto vale", "cotiz*", "presupuesto*", "oferta*", "promo*", "descuento*",
    )),
    _regla("comercial_cuota", "bloqueo", 1.0, (
        "cuota*", "financ*", "credito*", "plazo*", "tea", "interes*", "fnb", "a cuotas",
    )),
    _regla("comercial_compra", "bloqueo", 1.0, (
        "compra", "compras", "comprar*", "compro", "compre", "comprado", "comprando", "adquir*", "adquisicion",
        "vender*", "vendedor*", "venta*", "pedido*",
    )),
    _regla("comercial_instalacion", "bloqueo", 1.0, (
        "instal*", "conexion*", "habilit*", "tendido", "ducteria", "punto de gas", "puntos de gas",
    )),
    _regla("comercial_servicio", "bloqueo", 1.0, (
        "mantenimiento*", "manguera*", "revision*", "tecnic*", "repar*", "gasfiter*",
    )),
    _regla("comercial_asesor", "bloqueo", 1.0, ("asesor*", "ejecutiv*")),
)

_RE_GABI_PIDIO_DATOS = re.compile(r"\b(?:dni|suministro|titular\w*|documento de identidad|nombre del titular)\b")
_RE_GABI_DIO_PRECIO = re.compile(r"\bs\s*\d")  # "S/ 1,299" normaliza a "s 1 299": precio dado por Gabi
_RE_MENSAJE_DE_PRUEBA = re.compile(r"^(?:prueba|probando|test)\b")
_RE_PLACEHOLDER_MEDIA = re.compile(r"^\[([a-z_]+)\]$")
_TIPOS_MEDIA = ("image", "document", "audio", "sticker", "video")


# ── Decisión ─────────────────────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Decision:
    categoria: str = CATEGORIA_NINGUNA
    accion: str = ACCION_NINGUNA          # ninguna | cerrar | alerta_emergencia
    confianza: float = 0.0
    senales: tuple[str, ...] = ()         # ids de las reglas que coincidieron
    bloqueos: tuple[str, ...] = ()        # guardas y bloqueos comerciales que impidieron cerrar
    capa: str = "reglas"                  # fase 3: "haiku" para las dudas

    @property
    def hay_candidato(self) -> bool:
        return self.categoria != CATEGORIA_NINGUNA


@dataclass
class Contexto:
    """Todo lo que `clasificar` necesita saber del caso, ya leído de la base (así `clasificar` es PURA)."""
    categorias_activas: tuple[str, ...] = CATEGORIAS_FASE_1
    max_mensajes_cliente: int = MAX_MENSAJES_CLIENTE_POR_DEFECTO
    n_msgs_cliente: int | None = None      # None → los mensajes recibidos
    n_msgs_gabi: int = 0
    ultimo_gabi: str = ""                  # texto del último mensaje de Gabi
    gabi_dio_precio: bool = False
    hay_media: bool = False                # el cliente mandó foto / audio / documento / sticker / video
    hay_humano: bool = False               # un asesor o el celular de coexistencia ya escribió en este ciclo
    con_asesor_o_pausa: bool = False       # asesor asignado, Gabi pausada o en cola de supervisión
    cerrado: bool = False                  # cerrado definitivamente
    resultado: str | None = None
    paso_flujo: str | None = None
    triaje_previo: bool = False            # ya hubo un triaje (o un intento) en este ciclo
    canal_pruebas: bool = False
    telefono_excluido: bool = False
    tiene_campana: bool = False
    patrones_saludo: tuple[str, ...] = ()  # saludos preestablecidos de las campañas del negocio (ya normalizados)
    conversation_id: str | None = None


def _hay_numero_largo(mensajes: list[str]) -> bool:
    """DNI, suministro o teléfono: 8 o más dígitos, aunque vengan separados por espacios, puntos o guiones."""
    for texto in mensajes:
        pegado = re.sub(r"(?<=\d)[\s.\-](?=\d)", "", texto or "")
        if re.search(r"\d{8,}", pegado):
            return True
    return False


def _es_saludo_de_campana(mensaje_normalizado: str, patrones: tuple[str, ...]) -> bool:
    return any(len(p) >= 8 and p in mensaje_normalizado for p in patrones)


def _guardas(mensajes: list[str], ctx: Contexto) -> list[str]:
    n = ctx.n_msgs_cliente if ctx.n_msgs_cliente is not None else len(mensajes)
    g: list[str] = []
    if ctx.con_asesor_o_pausa:
        g.append("asesor_o_pausa")
    if ctx.hay_humano:
        g.append("humano_escribio")
    if ctx.cerrado:
        g.append("caso_cerrado")
    if ctx.resultado:
        g.append("ya_tiene_resultado")
    if ctx.paso_flujo in ("evaluando_financiamiento", "derivado_asesor"):
        g.append(f"paso_flujo_{ctx.paso_flujo}")
    if ctx.triaje_previo:
        g.append("triaje_previo_en_el_ciclo")
    if ctx.ultimo_gabi and _RE_GABI_PIDIO_DATOS.search(normalizar(ctx.ultimo_gabi)):
        g.append("gabi_pidio_dni_suministro_titular")
    if ctx.gabi_dio_precio:
        g.append("gabi_dio_precio")
    if _hay_numero_largo(mensajes):
        g.append("numero_largo_o_dni")
    if ctx.hay_media:
        g.append("cliente_envio_media")
    if n > ctx.max_mensajes_cliente:
        g.append("demasiados_mensajes_del_cliente")
    if ctx.canal_pruebas:
        g.append("canal_de_pruebas")
    if ctx.telefono_excluido or any(_RE_MENSAJE_DE_PRUEBA.search(normalizar(m)) for m in mensajes):
        g.append("equipo_o_prueba")
    return g


def _coincidencias(reglas: tuple[Regla, ...], mensajes_normalizados: list[str]) -> dict[str, Regla]:
    hallazgos: dict[str, Regla] = {}
    for texto in mensajes_normalizados:
        for regla in reglas:
            if regla.id not in hallazgos and regla.patron.search(texto):
                hallazgos[regla.id] = regla
    return hallazgos


def clasificar(mensajes_cliente: list[str], ctx: Contexto | None = None) -> Decision:
    """PURA. `mensajes_cliente`: los mensajes de texto del cliente en el ciclo actual, en orden. Devuelve la
    `Decision`; solo propone `cerrar` si hay una categoría activa con confianza suficiente y NINGÚN bloqueo."""
    ctx = ctx or Contexto()
    mensajes = [m for m in (mensajes_cliente or []) if (m or "").strip()]
    todos = [normalizar(m) for m in mensajes]

    # 1) Emergencia de gas: en cualquier mensaje; nunca cierra y se evalúa antes que todo lo demás.
    emergencia = _coincidencias(REGLAS_EMERGENCIA, todos)
    if emergencia:
        return Decision(
            CATEGORIA_EMERGENCIA, ACCION_ALERTA_EMERGENCIA, max(r.peso for r in emergencia.values()), tuple(emergencia),
        )

    # 2) Señales del tema en los ÚLTIMOS 2 mensajes del cliente.
    hallazgos = _coincidencias(REGLAS_ATC, todos[-2:])
    por_categoria: dict[str, list[Regla]] = {}
    for regla in hallazgos.values():
        por_categoria.setdefault(regla.categoria, []).append(regla)
    if not por_categoria:
        return Decision()

    def _confianza(reglas: list[Regla]) -> float:
        return min(0.99, max(r.peso for r in reglas) + 0.05 * (len(reglas) - 1))

    prioridad = {"pago_deuda": 0, "numero_cliente": 1, "recibo": 2}
    categoria = max(por_categoria, key=lambda c: (_confianza(por_categoria[c]), -prioridad.get(c, 9)))
    confianza = round(_confianza(por_categoria[categoria]), 2)
    if confianza < UMBRAL_CANDIDATO:
        return Decision()
    ids = tuple(r.id for r in por_categoria[categoria])

    # 3) Guardas y bloqueo comercial (todo el ciclo, salvo el saludo preestablecido de una campaña).
    bloqueos = _guardas(mensajes, ctx)
    comerciales = _coincidencias(
        BLOQUEOS_COMERCIALES,
        [t for i, t in enumerate(todos) if not (i == 0 and _es_saludo_de_campana(t, ctx.patrones_saludo))],
    )
    bloqueos += list(comerciales)
    if categoria not in ctx.categorias_activas:
        bloqueos.append("categoria_inactiva")
    if confianza < UMBRAL_CIERRE:
        bloqueos.append("confianza_baja")

    return Decision(
        categoria, ACCION_CERRAR if not bloqueos else ACCION_NINGUNA, confianza, ids, tuple(bloqueos),
    )


# ── Texto al cliente ─────────────────────────────────────────────────────────────────────────────────────

def _nombre_para_saludo(nombre: str | None) -> str:
    """" Yasmin" (con espacio delante) si hay un primer nombre presentable; "" si no. Un nombre con dígitos, símbolos
    o muy largo (el cliente escribió otra cosa) no se usa: mejor un saludo sin nombre que uno raro."""
    palabras = (nombre or "").strip().split()
    if not palabras:
        return ""
    primero = palabras[0].strip(".,;:!¡¿?")
    if not re.fullmatch(r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ'’-]{2,20}", primero):
        return ""
    return " " + primero[:1].upper() + primero[1:].lower()


def texto_para(
    plantilla: str | None, nombre: str | None, linea_atc: str, negocio: str = NOMBRE_NEGOCIO_POR_DEFECTO,
    linea_emergencia: str = "", linea_ventas: str = "",
) -> str:
    """Rellena la plantilla. Placeholders: {nombre} (con su espacio: "¡Hola{nombre}!"), {linea_atc}, {negocio},
    {linea_emergencia}, {linea_ventas}. Reemplazo literal (no `str.format`): una llave suelta en un texto
    personalizado no puede romper el envío."""
    texto = (plantilla or "").strip() or TEXTO_POR_DEFECTO
    for clave, valor in (
        ("{nombre}", _nombre_para_saludo(nombre)), ("{linea_atc}", (linea_atc or "").strip()),
        ("{negocio}", (negocio or "").strip() or NOMBRE_NEGOCIO_POR_DEFECTO),
        ("{linea_emergencia}", (linea_emergencia or "").strip()), ("{linea_ventas}", (linea_ventas or "").strip()),
    ):
        texto = texto.replace(clave, valor)
    return re.sub(r"[ \t]{2,}", " ", texto).strip()


# ── Lectura de configuración y del caso ──────────────────────────────────────────────────────────────────

def _parsear_modo(valor: str | None) -> str:
    modo = (valor or "").strip().lower()
    return modo if modo in MODOS else MODO_APAGADO


def _parsear_lista(valor: str | None) -> tuple[str, ...]:
    return tuple(x.strip().lower() for x in (valor or "").replace(";", ",").split(",") if x.strip())


def _parsear_entero(valor: str | None, por_defecto: int, minimo: int = 1, maximo: int = 50) -> int:
    try:
        return max(minimo, min(maximo, int(float(str(valor).strip().replace(",", ".")))))
    except (TypeError, ValueError):
        return por_defecto


def _solo_digitos(valor: str | None) -> str:
    return re.sub(r"\D", "", valor or "")


@dataclass
class Evaluacion:
    decision: Decision
    modo: str                               # el EFECTIVO (activo sin línea configurada → sombra)
    modo_configurado: str = MODO_APAGADO
    contexto: Contexto | None = None
    n_msgs_cliente: int = 0


async def _cfg(clave: str, negocio_id: str | None, por_defecto: str = "") -> str:
    return (await obtener_configuracion(clave, por_defecto, negocio_id=negocio_id) or "").strip()


async def _armar_contexto(telefono: str, canal: dict | None, lead: dict, negocio_id: str) -> tuple[Contexto, list[str]] | None:
    """Lee el ciclo ACTUAL (la Conversation activa) y la configuración. None si no hay conversación."""
    categorias = tuple(c for c in _parsear_lista(await _cfg(CLAVE_CATEGORIAS, negocio_id)) if c) or CATEGORIAS_FASE_1
    maximo = _parsear_entero(await _cfg(CLAVE_MAX_MENSAJES, negocio_id), MAX_MENSAJES_CLIENTE_POR_DEFECTO)
    permitir_pruebas = (await _cfg(CLAVE_PERMITIR_CANAL_PRUEBAS, negocio_id)).lower() in ("1", "true", "si", "sí")
    excluidos = {_solo_digitos(x) for x in _parsear_lista(await _cfg(CLAVE_TELEFONOS_EXCLUIDOS, negocio_id))}
    tiene_campana = bool(lead.get("campana_origen"))
    patrones: tuple[str, ...] = ()
    if tiene_campana:
        campanas = await listar_campanas(negocio_id, solo_activas=True)
        patrones = tuple(
            normalizar(c["patron"]) for c in campanas if c.get("tipo_deteccion") == "texto_saludo" and c.get("patron")
        )

    async with async_session() as session:
        contact = await _obtener_contact(session, negocio_id, telefono)
        conversation = await _obtener_conversation_activa(session, contact.id) if contact is not None else None
        if conversation is None or conversation.negocio_id != negocio_id:
            return None
        filas = (await session.execute(
            select(Mensaje.role, Mensaje.content, Mensaje.archivo_id, Mensaje.via_app, Mensaje.estado_envio)
            .where(Mensaje.conversation_id == conversation.id, Mensaje.negocio_id == negocio_id)
            .order_by(Mensaje.timestamp, Mensaje.id)
        )).all()
        previos = (await session.execute(
            select(func.count(EventoLead.id)).where(
                EventoLead.conversation_id == conversation.id,
                EventoLead.tipo.in_((EVENTO_TRIAJE_ATC_CERRADO, EVENTO_TRIAJE_ATC_FALLIDO)),
            )
        )).scalar_one()

    mensajes_cliente: list[str] = []
    n_cliente = n_gabi = 0
    ultimo_gabi = ""
    hay_media = hay_humano = gabi_dio_precio = False
    for role, contenido, archivo_id, via_app, estado_envio in filas:
        contenido = contenido or ""
        if role == "user":
            if contenido.startswith(PREFIJO_REACCION):
                continue
            n_cliente += 1
            placeholder = _RE_PLACEHOLDER_MEDIA.match(contenido.strip())
            if archivo_id or (placeholder and placeholder.group(1) in _TIPOS_MEDIA):
                hay_media = True
            if not placeholder:
                mensajes_cliente.append(contenido)
        elif role == "asesor" or (role == "assistant" and via_app):
            hay_humano = True
        elif role == "assistant" and (estado_envio or "") != "fallido":
            n_gabi += 1
            ultimo_gabi = contenido
            if _RE_GABI_DIO_PRECIO.search(normalizar(contenido)):
                gabi_dio_precio = True

    ctx = Contexto(
        categorias_activas=categorias, max_mensajes_cliente=maximo, n_msgs_cliente=n_cliente, n_msgs_gabi=n_gabi,
        ultimo_gabi=ultimo_gabi, gabi_dio_precio=gabi_dio_precio, hay_media=hay_media, hay_humano=hay_humano,
        con_asesor_o_pausa=bool(lead.get("asesor_asignado") or lead.get("pausado_manual") or lead.get("escalado_supervision_en")),
        cerrado=lead.get("cerrado_definitivamente_en") is not None or bool(conversation.cerrado_definitivamente_en),
        resultado=lead.get("resultado"), paso_flujo=lead.get("paso_flujo"), triaje_previo=previos > 0,
        canal_pruebas=((canal or {}).get("modo") == "pruebas") and not permitir_pruebas,
        telefono_excluido=_solo_digitos(telefono) in excluidos if excluidos else False,
        tiene_campana=tiene_campana, patrones_saludo=patrones, conversation_id=conversation.id,
    )
    return ctx, mensajes_cliente


async def evaluar(telefono: str, canal: dict | None, lead: dict | None) -> Evaluacion:
    """Lee la configuración, el ciclo actual y los eventos previos, y clasifica. NUNCA lanza: ante cualquier error
    devuelve una decisión "ninguna" con el modo "apagado" (el llamador no hace nada). Con el triaje apagado lo único
    que toca la base es la lectura de `triaje_atc_modo`."""
    try:
        negocio_id = (canal or {}).get("negocio_id")
        if not negocio_id or not lead:
            return Evaluacion(Decision(), MODO_APAGADO)
        configurado = _parsear_modo(await _cfg(CLAVE_MODO, negocio_id, MODO_APAGADO))
        if configurado == MODO_APAGADO:
            return Evaluacion(Decision(), MODO_APAGADO)
        armado = await _armar_contexto(telefono, canal, lead, negocio_id)
        if armado is None:
            return Evaluacion(Decision(), MODO_APAGADO, configurado)
        ctx, mensajes_cliente = armado
        # `activo` exige la línea de atención: sin ella no se redirige a nadie (se degrada a sombra).
        modo = configurado
        if configurado == MODO_ACTIVO and not await _cfg(CLAVE_LINEA, negocio_id):
            modo = MODO_SOMBRA
        return Evaluacion(clasificar(mensajes_cliente, ctx), modo, configurado, ctx, ctx.n_msgs_cliente or 0)
    except Exception:
        logger.exception("triaje_atc: no se pudo evaluar el caso — se sigue con Gabi")
        return Evaluacion(Decision(bloqueos=("error_interno",)), MODO_APAGADO)


# ── Registro (log + evento interno) ──────────────────────────────────────────────────────────────────────

def _resumen(ev: Evaluacion) -> dict:
    d, c = ev.decision, ev.contexto
    return {
        "capa": d.capa, "categoria": d.categoria, "accion_propuesta": d.accion, "confianza": d.confianza,
        "señales": list(d.senales), "n_msgs_cliente": ev.n_msgs_cliente,
        "n_msgs_gabi_previos": c.n_msgs_gabi if c else 0, "paso_flujo": c.paso_flujo if c else None,
        "tiene_campana": c.tiene_campana if c else False, "modo": ev.modo,
        "guardas_que_bloquearon": list(d.bloqueos),
    }


def _registrar_log(ev: Evaluacion) -> None:
    """UNA línea INFO por decisión: `triaje_atc {json}`. Sin teléfono, nombre ni texto de mensajes."""
    try:
        datos = {"conv": ev.contexto.conversation_id if ev.contexto else None, **_resumen(ev)}
        logger.info("triaje_atc " + json.dumps(datos, ensure_ascii=False))
        if ev.decision.categoria == CATEGORIA_EMERGENCIA:
            logger.warning(f"triaje_atc_emergencia_gas conv={datos['conv']} (solo registro en fase 1: Gabi sigue normal)")
    except Exception:
        logger.exception("triaje_atc: no se pudo escribir el log")


async def _decision_ya_registrada(conversation_id: str, resumen: dict) -> bool:
    """¿La última decisión registrada en este ciclo ya dijo exactamente lo mismo? Evita una fila por cada mensaje."""
    async with async_session() as session:
        ultimo = (await session.execute(
            select(EventoLead.payload).where(
                EventoLead.conversation_id == conversation_id, EventoLead.tipo == EVENTO_TRIAJE_ATC_SOMBRA,
            ).order_by(EventoLead.id.desc()).limit(1)
        )).scalar_one_or_none()
    if not isinstance(ultimo, dict):
        return False
    clave = ("categoria", "accion_propuesta", "señales", "guardas_que_bloquearon")
    return all(ultimo.get(k) == resumen.get(k) for k in clave)


async def _registrar_decision(telefono: str, ev: Evaluacion) -> None:
    """Evento interno `triaje_atc_sombra` cuando hubo un CANDIDATO (una categoría detectada, cierre propuesto o
    bloqueado). Permite medir recall y precisión con SQL; no se muestra en el Timeline. Nunca lanza."""
    if not ev.decision.hay_candidato or ev.contexto is None or not ev.contexto.conversation_id:
        return
    try:
        resumen = _resumen(ev)
        if await _decision_ya_registrada(ev.contexto.conversation_id, resumen):
            return
        await registrar_evento_lead(
            telefono, tipo=EVENTO_TRIAJE_ATC_SOMBRA,
            descripcion=f"Triaje ATC ({ev.modo}): {ev.decision.categoria} → {ev.decision.accion}"[:300],
            autor=None, payload=resumen,
        )
    except Exception:
        logger.exception("triaje_atc: no se pudo registrar el evento de la decisión")


# ── Ejecución (modo activo) ──────────────────────────────────────────────────────────────────────────────

async def _texto_final(negocio_id: str, categoria: str, lead: dict | None) -> str:
    plantilla = await _cfg(CLAVE_TEXTO_CATEGORIA + categoria, negocio_id) or await _cfg(CLAVE_TEXTO, negocio_id) or TEXTO_POR_DEFECTO
    texto = texto_para(
        plantilla, (lead or {}).get("nombre"), await _cfg(CLAVE_LINEA, negocio_id),
        await _cfg(CLAVE_NOMBRE_NEGOCIO, negocio_id) or NOMBRE_NEGOCIO_POR_DEFECTO,
        await _cfg(CLAVE_LINEA_EMERGENCIA, negocio_id), await _cfg(CLAVE_LINEA_VENTAS, negocio_id),
    )
    return texto or texto_para(None, (lead or {}).get("nombre"), await _cfg(CLAVE_LINEA, negocio_id))


async def _registrar_fallido(telefono: str, categoria: str, motivo: str | None, bloqueado: bool) -> None:
    try:
        await registrar_evento_lead(
            telefono, tipo=EVENTO_TRIAJE_ATC_FALLIDO,
            descripcion="Triaje automático: el texto no pudo enviarse — el caso sigue con Gabi",
            autor=None, payload={"categoria": categoria, "motivo": motivo or "no_enviado", "bloqueado": bloqueado},
        )
    except Exception:
        logger.exception("triaje_atc: no se pudo registrar el envío fallido")


async def ejecutar(ev: Evaluacion, telefono: str, canal: dict | None, lead: dict | None, proveedor) -> bool:
    """Envía el texto, lo guarda como mensaje de Gabi y cierra el caso. Devuelve True si el texto SALIÓ (o pudo
    salir: resultado incierto), es decir, si Gabi ya NO debe responder este turno. Si el envío no sale NO se cierra
    nada y devuelve False. Nunca lanza."""
    negocio_id = (canal or {}).get("negocio_id")
    categoria = ev.decision.categoria
    try:
        texto = await _texto_final(negocio_id, categoria, lead)
        resultado = await envios.enviar_texto(proveedor, telefono, texto, origen="triaje_atc", canal=canal)
    except Exception:
        logger.exception("triaje_atc: falló el envío — el caso sigue con Gabi")
        await _registrar_fallido(telefono, categoria, "excepcion_al_enviar", False)
        return False
    if not (resultado.enviado or resultado.incierto):
        logger.info(f"triaje_atc: el texto no salió ({resultado.motivo or 'envío fallido'}) — el caso sigue con Gabi")
        await _registrar_fallido(telefono, categoria, resultado.motivo, bool(resultado.bloqueado))
        return False

    # Desde acá el cliente ya recibió (o pudo recibir) el texto: Gabi NO responde este turno pase lo que pase.
    # El mensaje se guarda ANTES de cerrar: el cierre queda posterior a él y el "gracias"/"ok" se absorbe (C4).
    conversation_id = ev.contexto.conversation_id if ev.contexto else None
    try:
        guardado = await servicio_conversacion.guardar_mensaje(
            telefono, "assistant", texto, negocio_id=negocio_id,
            mensaje_id_meta=resultado.wamid, estado_envio=resultado.estado_envio,
        )
        conversation_id = guardado.get("conversation_id") or conversation_id
    except Exception:
        logger.exception("triaje_atc: el texto salió pero no se pudo guardar el mensaje — no se cierra el caso")
        return True
    try:
        cierre = await cerrar_por_triaje(telefono, negocio_id, categoria)
    except Exception:
        logger.exception("triaje_atc: el texto salió pero falló el cierre del caso")
        cierre = None
    if cierre is None:
        logger.warning("triaje_atc: el texto salió pero el caso no se pudo cerrar (alguien lo tomó o ya tenía resultado)")
    else:
        logger.info("triaje_atc_cerrado " + json.dumps({"conv": cierre["conversation_id"], "categoria": categoria}, ensure_ascii=False))
    try:
        await gestor_conexiones.emitir_mensaje_nuevo(conversation_id)
    except Exception:
        logger.exception("triaje_atc: no se pudo avisar al panel")
    return True


async def procesar(telefono: str, canal: dict | None, lead: dict | None, proveedor) -> bool:
    """Punto de entrada único desde `main._generar_y_enviar_respuesta_ia`. Devuelve True si el triaje atendió el
    turno (Gabi NO debe responder) y False en cualquier otro caso —apagado, sombra, sin candidato, con bloqueos, error
    o envío fallido—, es decir, que el camino de Gabi sigue exactamente como siempre."""
    try:
        ev = await evaluar(telefono, canal, lead)
        if ev.modo == MODO_APAGADO:
            return False
        _registrar_log(ev)
        await _registrar_decision(telefono, ev)
        if ev.modo != MODO_ACTIVO or ev.decision.accion != ACCION_CERRAR:
            return False
        return await ejecutar(ev, telefono, canal, lead, proveedor)
    except Exception:
        logger.exception("triaje_atc: error inesperado — se sigue con Gabi")
        return False
