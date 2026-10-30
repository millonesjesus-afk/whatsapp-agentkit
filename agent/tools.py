# agent/tools.py — Herramientas del agente
# Generado por AgentKit

"""
Herramientas específicas del negocio Gaso+: búsqueda en el catálogo de
productos (termas, cocinas, secadoras, servicios) y en la base de
conocimiento del programa, para dar contexto real a las respuestas de Gabi.
"""

import os
import re
import glob
import itertools
import logging
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from agent import calendario_negocio as cal_negocio
from agent.memory import (
    listar_productos_activos, obtener_producto_por_codigo_hana, obtener_calendario_negocio,
    obtener_configuracion,
)

logger = logging.getLogger("agentkit")

TZ_LIMA = ZoneInfo("America/Lima")
DIAS_ES = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]

KNOWLEDGE_DIR = "knowledge"
PLAZOS_A_MOSTRAR = ("12", "24", "36", "60")      # 60 = plazo máximo que financia Cálidda (CUOTAS_MAX)

# Gate 2026-09-23 (pedido explícito del usuario, tras compartir la plantilla
# real de cálculo) — la cuota YA NO viene de 9 columnas fijas y
# pre-calculadas del catálogo (3/6/9/12/18/24/36/48/60 meses; cualquier otro
# número, ej. 15, sencillamente no tenía ninguna respuesta posible). Se
# calcula EN VIVO con una tasa configurable POR NEGOCIO (nunca hardcodeada —
# "la tasa puede variar en el tiempo", pedido explícito), usando el mismo
# sistema francés de amortización + IGV sobre el interés que ya usaba la
# plantilla Excel del negocio — verificado cifra por cifra contra varios
# productos reales del catálogo antes de construir esto (ver conversación).
CUOTAS_MIN = 1
CUOTAS_MAX = 60
CLAVE_CONFIG_TEA = "tea_financiamiento"
CLAVE_CONFIG_IGV = "igv_financiamiento"
# Defaults = los valores reales de la plantilla del usuario al momento de
# este Gate — nunca se inventan, son el punto de partida real del negocio
# hasta que un admin los cambie desde Configuración.
TEA_POR_DEFECTO = "0.40"
IGV_POR_DEFECTO = "0.18"


def _calcular_amortizacion(monto: float, tea: float, igv: float, num_cuotas: int) -> dict:
    """Sistema francés de amortización (cuota base CONSTANTE en capital+interés)
    + IGV aplicado solo sobre el interés de cada periodo, nunca sobre el
    capital — mismo criterio que la plantilla de cálculo real del negocio.

    `cuota_inicial` (el importe del PRIMER periodo) es el número que ya se
    usaba como "la cuota" en las columnas fijas del catálogo — es el periodo
    de mayor interés (saldo completo) y por lo tanto el de mayor IGV, así
    que es también el importe más alto de todo el cronograma. Se replica
    ese mismo criterio a propósito, no uno nuevo — confirmado cifra por
    cifra contra el catálogo real (ver tests).

    `num_cuotas=1` es un caso aparte: no hay periodos intermedios que
    amortizar, un solo pago con un mes de interés sobre el monto completo."""
    if monto <= 0 or num_cuotas < 1:
        return {"cuota_inicial": 0.0, "total_a_pagar": 0.0, "total_intereses": 0.0}

    tem = (1 + tea) ** (1 / 12) - 1

    if num_cuotas == 1:
        interes = monto * tem
        cuota = monto + interes * (1 + igv)
        return {
            "cuota_inicial": round(cuota, 2),
            "total_a_pagar": round(cuota, 2),
            "total_intereses": round(interes, 2),
        }

    cuota_base = monto * tem / (1 - (1 + tem) ** -num_cuotas)
    saldo = monto
    total_a_pagar = 0.0
    total_intereses = 0.0
    cuota_inicial = None
    for _ in range(num_cuotas):
        interes = saldo * tem
        capital = cuota_base - interes
        cuota_total = capital + interes * (1 + igv)
        if cuota_inicial is None:
            cuota_inicial = cuota_total
        total_a_pagar += cuota_total
        total_intereses += interes
        saldo -= capital

    return {
        "cuota_inicial": round(cuota_inicial, 2),
        "total_a_pagar": round(total_a_pagar, 2),
        "total_intereses": round(total_intereses, 2),
    }


async def obtener_tasas_financiamiento(negocio_id: str) -> tuple[float, float]:
    """TEA/IGV configurados para ESTE negocio (tabla `configuracion`, ver
    agent/memory.py — mismo patrón ya usado para los umbrales de asignación
    automática, sin migración nueva). Nunca None: sin una tasa real no hay
    ninguna cuota que mostrar con sentido — cae al default documentado
    arriba (los valores reales de la plantilla del usuario) hasta que un
    admin configure los suyos."""
    tea = await obtener_configuracion(CLAVE_CONFIG_TEA, TEA_POR_DEFECTO, negocio_id=negocio_id)
    igv = await obtener_configuracion(CLAVE_CONFIG_IGV, IGV_POR_DEFECTO, negocio_id=negocio_id)
    return float(tea), float(igv)


async def calcular_cuota_producto(monto: float, negocio_id: str, num_cuotas: int) -> dict | None:
    """Punto de entrada público — resuelve la tasa configurada de ESTE
    negocio y calcula. `None` si `num_cuotas` cae fuera del rango real (1 a
    60) en vez de calcular algo sin sentido de negocio."""
    if not (CUOTAS_MIN <= num_cuotas <= CUOTAS_MAX):
        return None
    tea, igv = await obtener_tasas_financiamiento(negocio_id)
    return _calcular_amortizacion(monto, tea, igv, num_cuotas)


_PATRON_CUOTAS_PEDIDAS = re.compile(r"\b(\d{1,2})\s*(?:cuotas?|meses)\b", re.IGNORECASE)


def _cuotas_pedidas_en_mensaje(mensaje: str) -> int | None:
    """Detecta si el cliente pidió un número PUNTUAL de cuotas/meses (ej.
    "en 15 cuotas", "a 24 meses") — para poder calcularle esa cuota exacta
    aunque no sea uno de los plazos que ya se muestran de entrada
    (`PLAZOS_A_MOSTRAR`). `None` si no hay un pedido reconocible, o si el
    número está fuera del rango real (1 a 60) — nunca se inventa un cálculo
    fuera de lo que el negocio realmente financia."""
    m = _PATRON_CUOTAS_PEDIDAS.search(mensaje)
    if not m:
        return None
    n = int(m.group(1))
    return n if CUOTAS_MIN <= n <= CUOTAS_MAX else None

# El catálogo de productos vive en Postgres (tabla `productos`, ver
# agent/memory.py) desde el bloque "Catálogo editable — sub-bloque a"
# (2026-08-16) — antes se cargaba una sola vez a una variable de módulo
# desde knowledge/lista_precios_canales_propios.csv, sin invalidación. El
# CSV se conserva en el repo como respaldo y como mecanismo de
# reimportación masiva (memory.importar_catalogo_desde_csv), no se vuelve
# a leer en tiempo de ejecución.


def _precio_float(producto: dict) -> float:
    """Convierte el precio del producto a float para poder ordenar; los que
    no tengan un precio válido quedan al final."""
    try:
        return float(producto.get("PRECIO", ""))
    except (TypeError, ValueError):
        return float("inf")


# Gate 2026-09-23 (hallazgo real: Gabi solo ofrecía termas de 5.5L aunque el
# cliente necesitaba más capacidad) — la capacidad (litros/min) NUNCA vive en
# TIPO/SUB TIPO/MARCA (los únicos campos que puntuaba `buscar_productos`),
# solo aparece en el texto libre de DESCRIPCIÓN (ej. "TERMA SOLE 5.5 LT -
# BASIC"). Sin este patrón, ninguna búsqueda distinguía productos por
# capacidad — ni para priorizar un pedido explícito ("terma de 12 litros")
# ni para variar qué capacidades le llegan a Gabi cuando el cliente solo dice
# "terma" en general.
_PATRON_CAPACIDAD = re.compile(r"(\d+(?:[.,]\d+)?)\s*(?:LTS?|LITROS?|L\s*/\s*M[IÍ]N)\b")


def _capacidad_de(producto: dict) -> float | None:
    """Extrae la capacidad (litros/min) de la DESCRIPCIÓN del producto, si
    tiene una. `None` para productos sin capacidad detectable (accesorios,
    servicios, combos sin ese dato) — se tratan como su propio grupo, nunca
    se descartan."""
    descripcion = (producto.get("DESCRIPCIÓN") or "").upper()
    m = _PATRON_CAPACIDAD.search(descripcion)
    return float(m.group(1).replace(",", ".")) if m else None


def _capacidad_pedida_en_mensaje(mensaje: str) -> float | None:
    """Misma extracción que `_capacidad_de`, pero sobre lo que escribió el
    cliente — exige la unidad (LT/LITROS/L POR MIN) pegada al número a
    propósito: un mensaje como "somos 5 personas" no debe confundirse con
    "quiero 5 litros". Sin la unidad explícita, no hay pedido de capacidad
    que priorizar — se deja que la diversidad de `_seleccionar_diversos_
    por_capacidad` haga su trabajo en vez de adivinar."""
    m = _PATRON_CAPACIDAD.search(mensaje.upper())
    return float(m.group(1).replace(",", ".")) if m else None


def _seleccionar_diversos_por_capacidad(candidatos: list[dict], limite: int) -> list[dict]:
    """Reparte la selección entre las distintas capacidades presentes en
    `candidatos` (una por una, la más barata de cada capacidad primero, en
    vueltas) en vez de tomar sencillamente las `limite` más baratas — así una
    capacidad con muchas variantes de precio (ej. 22 termas de 5.5L) no tapa
    a las de mayor capacidad, que son más caras y quedarían siempre afuera
    del corte. Termina reordenando el resultado por precio ascendente, para
    mantener el contrato ya documentado en `buscar_productos` ("opción 1 = la
    más barata [de las que se muestran]").

    Si `candidatos` ya entra dentro de `limite`, el resultado es exactamente
    el mismo conjunto (solo reordenado) — esta función nunca agrega ni quita
    productos, solo decide CUÁLES quedan cuando hay que recortar."""
    if len(candidatos) <= limite:
        return sorted(candidatos, key=_precio_float)

    grupos: dict[float | None, list[dict]] = {}
    for producto in candidatos:
        grupos.setdefault(_capacidad_de(producto), []).append(producto)
    for lista in grupos.values():
        lista.sort(key=_precio_float)

    # None (sin capacidad detectada) al final — las capacidades reales son
    # la señal más útil para diversificar; lo sin-capacidad se completa al
    # final si todavía sobra espacio.
    claves_ordenadas = sorted(grupos.keys(), key=lambda c: (c is None, c))
    indices = dict.fromkeys(claves_ordenadas, 0)
    seleccionados: list[dict] = []
    while len(seleccionados) < limite:
        avanzo = False
        for clave in claves_ordenadas:
            i = indices[clave]
            if i < len(grupos[clave]):
                seleccionados.append(grupos[clave][i])
                indices[clave] += 1
                avanzo = True
                if len(seleccionados) >= limite:
                    break
        if not avanzo:
            break

    seleccionados.sort(key=_precio_float)
    return seleccionados


# Cómo llama el cliente a un producto que en el catálogo se llama distinto (2026-10-30, auditoría de chats): pedían «lavadora» o
# «lavaseca» y Gabi decía que no había, cuando el catálogo tiene el CENTRO DE LAVADO (lava y seca en un solo equipo, a gas).
_SINONIMOS_DE_BUSQUEDA = (
    (re.compile(r"lavadora|lavaseca|lavasecadora|lava\s*(y|-)?\s*seca|lavander[ií]a"), "centro de lavado"),
)


def con_sinonimos(mensaje: str) -> str:
    """El mensaje del cliente más el nombre que el catálogo le da a lo que pidió («lavadora» → «centro de lavado»)."""
    extra = [nombre for patron, nombre in _SINONIMOS_DE_BUSQUEDA if patron.search(mensaje) and nombre not in mensaje]
    return f"{mensaje} {' '.join(extra)}" if extra else mensaje


async def buscar_productos(
    mensaje: str, negocio_id: str | None, limite: int = 8, excluir_codigos: set[str] | None = None,
) -> list[dict]:
    """
    Busca productos del catálogo DE UN NEGOCIO cuyo tipo, sub tipo o marca
    aparezcan mencionados en el mensaje del cliente. Prioriza coincidencias
    de marca (señal más específica) por sobre coincidencias genéricas de
    tipo, para que mencionar una marca puntual (ej. "Rheem") no quede
    opacado por productos de otras marcas que solo comparten el tipo (ej.
    "terma"). Dentro de un mismo nivel de relevancia, ordena de menor a
    mayor precio, para que preguntas como "la más barata" o "la segunda más
    barata" se puedan responder de forma consistente por posición.

    Args:
        mensaje: mensaje del cliente (ej: "quiero una terma a gas Rheem")
        negocio_id: Negocio cuyo catálogo se busca (Gate 4.4). `None` —
            Negocio no resuelto todavía— falla cerrado devolviendo lista
            vacía, mismo criterio que `obtener_codigos_promocionales_activos`/
            `elegir_asesor_automatico`: nunca se cae a buscar en el
            catálogo de cualquier Negocio.
        limite: máximo de resultados a retornar
        excluir_codigos: códigos de material (CODIGO HANA) a excluir de la
            búsqueda general — se usa para que un precio promocional
            reservado a una campaña específica (ej. la Terma a S/419.90 de
            "SMS Terma a gas") no aparezca como oferta general a cualquier
            cliente que mencione "terma" sin venir de esa campaña.

    Returns:
        Lista de productos coincidentes con sus datos de precio y cuotas,
        ordenados de mayor a menor relevancia y, dentro de eso, de menor a
        mayor precio — salvo que haya que recortar por `limite`: ver
        `_seleccionar_diversos_por_capacidad` para cómo se decide QUIÉNES
        quedan cuando sobran candidatos con la misma relevancia (nunca
        "las más baratas y ya", eso escondía las de mayor capacidad).
    """
    if negocio_id is None:
        return []
    mensaje = con_sinonimos(mensaje.lower())
    excluir_codigos = excluir_codigos or set()
    # Gate 2026-09-23 — hallazgo real: un cliente que necesitaba una terma de
    # mayor capacidad (varios baños/personas) solo recibía opciones de 5.5L,
    # la capacidad más barata — nunca porque el cliente la haya pedido, sino
    # porque nada acá distinguía productos por capacidad. Ver el bloque de
    # abajo y `_seleccionar_diversos_por_capacidad`.
    capacidad_pedida = _capacidad_pedida_en_mensaje(mensaje)
    candidatos = []
    for producto in await listar_productos_activos(negocio_id):
        if producto.get("CODIGO HANA", "") in excluir_codigos:
            continue

        tipo = producto.get("TIPO", "").lower()
        sub_tipo = producto.get("SUB TIPO", "").lower()
        marca = producto.get("MARCA", "").lower()

        score = 0
        if marca and marca in mensaje:
            score += 2
        if sub_tipo and sub_tipo in mensaje:
            score += 1
        if tipo and tipo in mensaje:
            score += 1
        # Un pedido de capacidad explícito ("terma de 12 litros") es la señal
        # más específica que un cliente puede dar — se premia por encima de
        # marca, para que no quede opacada por productos de otra capacidad
        # que solo comparten tipo/marca. Solo aplica sobre candidatos que ya
        # matchearon algo (score > 0): nunca mete un producto de otra
        # categoría solo porque su capacidad coincide por casualidad.
        if score > 0 and capacidad_pedida is not None and _capacidad_de(producto) == capacidad_pedida:
            score += 3

        if score > 0:
            candidatos.append((score, producto))

    candidatos.sort(key=lambda item: -item[0])
    resultado: list[dict] = []
    for _, grupo in itertools.groupby(candidatos, key=lambda item: item[0]):
        faltan = limite - len(resultado)
        if faltan <= 0:
            break
        productos_del_grupo = [producto for _, producto in grupo]
        resultado.extend(_seleccionar_diversos_por_capacidad(productos_del_grupo, faltan))
    return resultado


async def obtener_producto_por_codigo(codigo: str, negocio_id: str | None) -> dict | None:
    """
    Busca un producto del catálogo DE UN NEGOCIO por su código único de
    material (CODIGO HANA), la lista de precios oficial. Se usa para que
    las campañas (agent/campanas.py) referencien un producto real por
    código en vez de texto libre — así el precio de la promo nunca queda
    desincronizado de la lista de precios vigente. `negocio_id=None`
    (Gate 4.4) falla cerrado devolviendo None, mismo criterio que
    buscar_productos.
    """
    codigo = (codigo or "").strip()
    if not codigo or negocio_id is None:
        return None
    return await obtener_producto_por_codigo_hana(codigo, negocio_id)


_PATRON_SUFIJOS_COMBO = re.compile(
    r"\s*\+\s*(CONEXI[ÓO]N|COMBO|DUCTER[ÍI]A[^+]*|PUNTO ADICIONAL[^+]*|RACK|KIT DE INSTALACI[ÓO]N)",
    re.IGNORECASE,
)


def _modelo_base(descripcion: str) -> str:
    """Quita sufijos de instalación/combo/accesorios (+CONEXIÓN, +COMBO,
    +DUCTERÍA, +PUNTO ADICIONAL, +RACK...) para comparar el modelo base del
    producto, independientemente de qué combinación de instalación incluya."""
    sin_sufijos = _PATRON_SUFIJOS_COMBO.sub("", descripcion.strip().upper())
    return re.sub(r"\s+", " ", sin_sufijos).strip()


async def obtener_familia_producto(codigo_material: str, negocio_id: str | None) -> list[dict]:
    """
    Dado el código de un producto DE UN NEGOCIO, retorna todas las variantes
    de combo/instalación del MISMO modelo base (misma marca, mismo
    proveedor, misma descripción sin contar +CONEXIÓN/+COMBO/+DUCTERÍA/etc.)
    Y el mismo nivel de fee (FEE PRV/FEE CLDA), ordenadas de menor a mayor
    precio, incluyendo el producto original. `negocio_id=None` (Gate 4.4)
    falla cerrado devolviendo lista vacía.

    El filtro por fee es clave: en varios modelos (ej. Secadora Rinnai 10Kg)
    el catálogo trae DOS listas de precio paralelas para las mismas
    combinaciones de instalación — una con fee más bajo (la promocional) y
    otra con fee estándar (la regular, más cara). No son duplicados: son dos
    estructuras de precio distintas. Si no se filtrara por fee, la familia
    promocional se mezclaría con la regular y ambas quedarían ocultas para
    el cliente equivocado.

    Se usa para que una campaña vinculada a un código específico (ej. la
    Secadora Rinnai 10Kg + Combo a S/3299) también reconozca como parte de
    su promoción las demás combinaciones de instalación del mismo modelo Y
    mismo nivel de fee (sin combo, +conexión, +conexión+combo, etc.), y así
    Gabi pueda cotizar bien si el cliente de esa campaña pide una variante
    distinta — sin tocar la línea de precio regular, que queda visible para
    el resto de clientes.
    """
    ancla = await obtener_producto_por_codigo(codigo_material, negocio_id)
    if ancla is None:
        return []

    marca = ancla.get("MARCA", "").strip().upper()
    proveedor = ancla.get("PROVEEDOR", "").strip().upper()
    base = _modelo_base(ancla.get("DESCRIPCIÓN", ""))
    fee_prv = ancla.get("FEE PRV", "").strip()
    fee_clda = ancla.get("FEE CLDA", "").strip()

    familia = [
        p for p in await listar_productos_activos(negocio_id)
        if p.get("MARCA", "").strip().upper() == marca
        and p.get("PROVEEDOR", "").strip().upper() == proveedor
        and _modelo_base(p.get("DESCRIPCIÓN", "")) == base
        and p.get("FEE PRV", "").strip() == fee_prv
        and p.get("FEE CLDA", "").strip() == fee_clda
    ]
    familia.sort(key=_precio_float)
    return familia


def formatear_producto(producto: dict, tea: float, igv: float, con_cuotas: bool = True) -> str:
    """Da formato legible a un producto del catálogo.

    Combo/Incluye conexión (2026-09-16, pedido explícito: "cuando a Gabi le
    preguntan por un producto no identifica si viene en combo o con
    conexión y no sabe explicar la diferencia en precio") — antes esta
    función no los incluía en absoluto, aunque el dato ya existe en el
    catálogo (ver Producto.combo/incluye_conexion en agent/memory.py): Gabi
    literalmente no tenía cómo saberlo, porque nunca llegaba a este texto.
    Es justo la explicación más común de por qué dos filas del mismo modelo
    tienen precios distintos — sin esto Gabi no podía dar esa razón.

    Gate 2026-09-23 — las cuotas ya NO se leen de las columnas fijas del
    catálogo (3/6/9/12/18/24/36/48/60), se calculan EN VIVO con la tasa
    (`tea`/`igv`) que ya resolvió quien llama (ver `obtener_tasas_
    financiamiento`) — una sola vez por negocio, no una consulta por
    producto. Ver `_calcular_amortizacion` para la fórmula."""
    marca = producto.get("MARCA", "")
    descripcion = producto.get("DESCRIPCIÓN", "")
    precio = producto.get("PRECIO", "")
    canal = producto.get("CANAL", "")
    combo = producto.get("COMBO", "")
    incluye_conexion = producto.get("INCLUYE CONEXIÓN", "")

    monto = _precio_float(producto)
    cuotas = [
        f"{plazo} meses{' (plazo máximo)' if int(plazo) == CUOTAS_MAX else ''}: "
        f"S/ {_calcular_amortizacion(monto, tea, igv, int(plazo))['cuota_inicial']:.2f}"
        for plazo in PLAZOS_A_MOSTRAR
    ] if monto != float("inf") else []

    tipo = (producto.get("TIPO") or "").strip()
    sub_tipo = (producto.get("SUB TIPO") or "").strip()
    comentarios = (producto.get("COMENTARIOS") or "").strip()

    lineas = [f"{marca} — {descripcion}", f"Precio: S/ {precio}", f"Canal: {canal}"]
    # TIPO/SUB TIPO solo si aportan algo distinto de lo que ya dice la descripción; los FEE nunca salen (solo admin).
    categoria = " / ".join(dict.fromkeys(t for t in (tipo, sub_tipo) if t))
    if categoria and categoria.lower() not in descripcion.lower():
        lineas.append(f"Categoría: {categoria}")
    if comentarios:
        lineas.append(f"Comentarios del producto: {comentarios}")
    if combo:
        lineas.append(f"Combo: incluye {combo}")
    if incluye_conexion:
        # «Con conexión» = el equipo viene con su conexión (elastómero) al punto de gas que el cliente YA tiene.
        # NO es un punto de gas nuevo: el punto adicional es un servicio aparte (o un combo que lo diga).
        if incluye_conexion.strip().upper() in ("SI", "SÍ"):
            lineas.append("Incluye la conexión del equipo al punto de gas existente (con elastómero): SÍ — no incluye punto de gas nuevo")
        else:
            lineas.append(f"Incluye la conexión del equipo al punto de gas existente: {incluye_conexion}")
    # `con_cuotas=False` (2026-10-26, auditoría de tokens): la tabla de cuotas solo cuando el cliente habló de precio o de
    # pagos; si no, Gabi no las menciona y eran ~30 tokens por producto en cada turno.
    if cuotas and con_cuotas:
        lineas.append("Cuotas: " + " | ".join(cuotas))
    return "\n".join(lineas)


def _dividir_en_parrafos(contenido: str, min_len: int = 20) -> list[str]:
    """Divide un documento en párrafos/líneas para poder buscar con precisión
    dentro de documentos largos (como el contrato), en vez de truncar todo
    el documento a sus primeros caracteres."""
    return [linea.strip() for linea in contenido.split("\n") if len(linea.strip()) >= min_len]


ARCHIVO_REGLAS_DEL_NEGOCIO = "_reglas_de_gabi.md"


def reglas_del_negocio(negocio_codigo: str | None) -> str:
    """Las reglas de Gabi propias de UN negocio (`knowledge/<codigo>/_reglas_de_gabi.md`): quién es, cómo habla de su empresa, qué
    medios de pago existen, a dónde manda un trámite. Van SIEMPRE en el system prompt (el archivo es corto), a diferencia de la base
    de conocimiento, que solo trae los párrafos parecidos a lo que dijo el cliente. Sin negocio, sin carpeta o sin archivo: vacío
    (nunca se cae a las reglas de otro negocio)."""
    if not negocio_codigo:
        return ""
    ruta = os.path.join(KNOWLEDGE_DIR, negocio_codigo, ARCHIVO_REGLAS_DEL_NEGOCIO)
    try:
        with open(ruta, "r", encoding="utf-8") as f:
            return f.read().strip()
    except (UnicodeDecodeError, OSError):
        return ""


def buscar_en_knowledge(mensaje: str, negocio_codigo: str | None, limite: int = 7) -> str:
    """
    Busca, a nivel de párrafo, los fragmentos de /knowledge/<negocio_codigo>
    (base de conocimiento, contrato, speech, resumen del programa) que
    compartan más palabras clave con el mensaje del cliente. Trabajar por
    párrafo evita que la cláusula relevante de un documento largo (ej. el
    contrato de financiamiento) quede fuera por estar más allá de los
    primeros caracteres.

    Auditoría puntual (post Gate 4.3, hallazgo de la validación de
    activación de Gabi): antes de esto, `/knowledge/` era UNA carpeta
    compartida por todo el proceso, sin relación con `negocio_id` — un
    segundo Negocio real habría recibido, sin darse cuenta, contexto de la
    base de conocimiento de Cálidda (contratos, políticas comerciales,
    speech de televentas) en sus propias conversaciones. Ahora cada
    Negocio tiene su propia subcarpeta (`knowledge/<codigo>/`, ej.
    `knowledge/calidda/`) — se usa `codigo` (el slug estable, "calidda"),
    no `negocio_id` (un UUID generado por entorno, distinto en cada base
    de datos) para que el nombre de carpeta sea portable entre dev/prod.

    Fail-safe a propósito, mismo criterio que ya usa `_armar_bloques_contexto`
    para campañas ("nunca se listan campañas de cualquier Negocio"):
    `negocio_codigo=None` o una carpeta que no existe → sin contexto, NUNCA
    se cae a buscar en la raíz de /knowledge/ ni en la carpeta de otro
    Negocio.
    """
    if not negocio_codigo:
        return ""
    directorio = os.path.join(KNOWLEDGE_DIR, negocio_codigo)
    if not os.path.isdir(directorio):
        return ""

    palabras = {p for p in re.findall(r"\w+", mensaje.lower()) if len(p) >= 4}
    if not palabras:
        return ""

    candidatos = []
    for patron in ("*.md", "*.txt"):
        for ruta in glob.glob(os.path.join(directorio, patron)):
            try:
                with open(ruta, "r", encoding="utf-8") as f:
                    contenido = f.read()
            except (UnicodeDecodeError, IOError):
                continue
            nombre = os.path.basename(ruta)
            if nombre.startswith("_"):
                continue   # reglas siempre activas (reglas_del_negocio): no se buscan por palabras
            for parrafo in _dividir_en_parrafos(contenido):
                score = sum(1 for palabra in palabras if palabra in parrafo.lower())
                if score > 0:
                    candidatos.append((score, nombre, parrafo))

    candidatos.sort(key=lambda item: item[0], reverse=True)
    secciones = [f"[{nombre}] {parrafo}" for _, nombre, parrafo in candidatos[:limite]]
    return "\n---\n".join(secciones)


# ── Horario de atención y calendario de negocio ──────────────────────────────────────────────────────────
#
# Gate 4.2 (Decisión 5, Gate 4.1) movió el horario de un rango hardcodeado a `HorarioAtencion` por negocio. Desde
# 2026-10-12 (calendario de negocio, Fase 1) TODA la lógica de «¿atiende ahora?», «¿cuándo abre?» y «¿cuánto tiempo
# hábil pasó?» vive en UN solo lugar, el módulo puro `agent/calendario_negocio.py`, y conoce además los feriados y días
# especiales (`DiaEspecial`). Las funciones de acá conservan su firma pública (y aceptan un `ahora` opcional para
# poder probarlas con una hora fija); el fallback sin filas (lunes a sábado 8:00-19:00) también vive en ese módulo.

def _a_utc_naive(ahora: datetime | None) -> datetime:
    """`ahora` como UTC naive (la convención del repo). Sin valor: la hora real. Un datetime con zona (p. ej. el de
    Lima) se convierte; uno naive se toma como UTC."""
    ahora = ahora or datetime.now(TZ_LIMA)
    if ahora.tzinfo is not None:
        return ahora.astimezone(timezone.utc).replace(tzinfo=None)
    return ahora


async def obtener_estado_horario_atencion(negocio_id: str | None, ahora: datetime | None = None, fresco: bool = False) -> dict:
    """
    Calcula si AHORA MISMO (hora real de Lima) se está dentro del horario de
    atención de los asesores humanos DE ESTE NEGOCIO, contando feriados y días
    especiales. Un modelo de lenguaje no tiene reloj propio — sin esto, no hay
    forma de que Gabi sepa si un asesor está disponible en este momento o no.

    Devuelve `dentro_de_horario` y `fecha_hora_lima` (como siempre) más, ADITIVOS:
    `motivo` (None con el negocio abierto; fuera_de_horario | feriado | no_laborable
    | puente | dia_sin_atencion | cierre_propio), `nombre` (el del día especial de
    hoy, si lo hay), `proxima_apertura` (UTC naive o None) y
    `proxima_apertura_texto` ("mañana a las 8:00 a. m."). `ahora` (aware o UTC
    naive) solo existe para probarlo con una hora fija; `fresco=True` salta la
    caché de 60 s de los días especiales (lo usan los Cron).
    """
    cal = await obtener_calendario_negocio(negocio_id, fresco=fresco)
    ahora_utc = _a_utc_naive(ahora)
    est = cal_negocio.estado(ahora_utc, cal)
    lima = cal_negocio.a_lima(ahora_utc)
    return {
        "dentro_de_horario": est["abierto"],
        "fecha_hora_lima": f"{DIAS_ES[lima.weekday()]} {lima.strftime('%d/%m/%Y')}, {lima.strftime('%H:%M')} (hora de Lima)",
        "motivo": est["motivo"], "nombre": est["nombre"], "proxima_apertura": est["proxima_apertura"],
        "proxima_apertura_texto": cal_negocio.describir_proxima_apertura(est["proxima_apertura"], ahora_utc),
    }


def _hora_legible(hhmm: str) -> str:
    """"08:00" -> "8:00 a. m."; "19:00" -> "7:00 p. m." — como se escribe en Perú."""
    return cal_negocio.hora_legible(hhmm)


class RangosDeAtencion(dict):
    """`{dia 0=lunes: (apertura, cierre) | None}` — el horario SEMANAL de siempre — con el `Calendario` completo
    (feriados y días especiales incluidos) adjunto en `.calendario`. Las funciones de `atencion_atrasada` que reciben
    `rangos` usan ese calendario si está, así los llamadores viejos (p. ej. `llamadas.py`) conocen los feriados sin
    cambiar su firma."""
    calendario: "cal_negocio.Calendario | None" = None


async def _rangos_de_atencion_por_dia(negocio_id: str | None, fresco: bool = False) -> RangosDeAtencion:
    """Para cada día de la semana (0=lunes), `(apertura, cierre)` o None si ese día no se atiende — el horario
    semanal; el `HorarioAtencion` del negocio manda y un día sin fila usa el de siempre (lunes a sábado, 8:00 a
    19:00). El calendario completo (con excepciones) va en `.calendario`."""
    cal = await obtener_calendario_negocio(negocio_id, fresco=fresco)
    rangos = RangosDeAtencion(cal_negocio.rangos_de_semana(cal))
    rangos.calendario = cal
    return rangos


async def describir_horario_atencion(negocio_id: str | None) -> str:
    """El horario real del negocio en una frase, para el cliente: "lunes a sábado, de
    8:00 a. m. a 7:00 p. m.". Agrupa los días CONSECUTIVOS con el mismo rango."""
    rangos = await _rangos_de_atencion_por_dia(negocio_id)
    grupos: list[tuple[int, int, tuple[str, str]]] = []
    for dia in range(7):
        rango = rangos[dia]
        if rango is None:
            continue
        if grupos and grupos[-1][1] == dia - 1 and grupos[-1][2] == rango:
            grupos[-1] = (grupos[-1][0], dia, rango)
        else:
            grupos.append((dia, dia, rango))
    if not grupos:
        return "nuestro horario de atención"
    partes = []
    for inicio, fin, (apertura, cierre) in grupos:
        dias = DIAS_ES[inicio] if inicio == fin else f"{DIAS_ES[inicio]} a {DIAS_ES[fin]}"
        partes.append(f"{dias}, de {_hora_legible(apertura)} a {_hora_legible(cierre)}")
    return "; ".join(partes)


async def obtener_proxima_apertura(negocio_id: str | None, ahora: datetime | None = None) -> dict | None:
    """La próxima vez que este negocio abre (hora de Lima), según los `HorarioAtencion`
    reales (con el mismo fallback) Y los feriados/días especiales: un cierre largo
    (hasta 3 semanas) se resuelve igual. Siempre es una apertura FUTURA: con el negocio
    abierto ahora mismo, es la del siguiente rango. `ahora` solo existe para poder
    probarlo con una hora fija.

    Devuelve `{"inicio": datetime (Lima), "dia": "lunes", "hora": "8:00 a. m.",
    "dias_de_diferencia": int, "hoy_es_dia_de_atencion": bool}` más, ADITIVOS, `fecha`
    (date de Lima), `texto` ("el viernes 9 a las 8:00 a. m.") y `motivo_hoy`/`nombre_hoy`;
    o None si no hay ninguna apertura en las próximas 3 semanas.
    `hoy_es_dia_de_atencion` es False si HOY está cerrado todo el día (domingo, feriado,
    día no laborable marcado como cerrado…)."""
    cal = await obtener_calendario_negocio(negocio_id)
    ahora_utc = _a_utc_naive(ahora)
    apertura_utc = cal_negocio.proxima_apertura(ahora_utc, cal)
    if apertura_utc is None:
        return None
    apertura = cal_negocio.a_lima(apertura_utc)
    hoy = cal_negocio.a_lima(ahora_utc).date()
    est = cal_negocio.estado(ahora_utc, cal)
    return {
        "inicio": apertura.replace(tzinfo=TZ_LIMA), "dia": DIAS_ES[apertura.weekday()],
        "hora": _hora_legible(apertura.time()), "dias_de_diferencia": (apertura.date() - hoy).days,
        "hoy_es_dia_de_atencion": not cal_negocio.cerrado_todo_el_dia(hoy, cal),
        "fecha": apertura.date(), "texto": cal_negocio.describir_proxima_apertura(apertura_utc, ahora_utc),
        "motivo_hoy": est["motivo"], "nombre_hoy": est["nombre"],
    }


async def obtener_contexto_relevante(
    mensaje: str, negocio_id: str | None = None, negocio_codigo: str | None = None,
    excluir_codigos: set[str] | None = None, con_cuotas: bool = True, limite_conocimiento: int = 7,
) -> str:
    """
    Punto de entrada usado por brain.py: combina resultados del catálogo de
    productos y de la base de conocimiento relacionados al mensaje del cliente.

    `negocio_codigo` (el slug estable, ej. "calidda") se propaga hacia
    `buscar_en_knowledge`, que aísla por carpeta (`knowledge/<codigo>/`).
    `negocio_id` (el FK real, Gate 4.4) se propaga hacia `buscar_productos`,
    que aísla por columna. Son dos identificadores distintos del MISMO
    Negocio porque cada aislamiento se resolvió en su propio Gate contra un
    mecanismo distinto (carpetas vs. filas de base de datos) — ambos
    `None` cuando el Canal no resolvió Negocio todavía, y ambos fallan
    cerrado (sin contexto/catálogo) en vez de adivinar."""
    secciones = []

    # limite=5 (2026-09-17, pedido explícito del usuario, revisando su
    # consumo de la API): el default de buscar_productos (8) es más de lo
    # que Gabi necesita para orientar a un cliente — 5 opciones ya cubren
    # el caso real sin inflar el contexto dinámico (no cacheable) que se le
    # manda en cada turno. Los otros llamadores de buscar_productos (el
    # buscador del panel, dashboard.py) siguen en 8 — ese límite es propio
    # de este contexto, no un cambio al default de la función.
    productos = await buscar_productos(mensaje, negocio_id, limite=5, excluir_codigos=excluir_codigos)
    if productos:
        # negocio_id no puede ser None acá — buscar_productos ya devuelve []
        # en ese caso (falla cerrado), así que si `productos` no está vacío
        # es porque negocio_id era real.
        tea, igv = await obtener_tasas_financiamiento(negocio_id)
        productos_texto = "\n\n".join(
            f"{i}. {formatear_producto(p, tea, igv, con_cuotas=con_cuotas)}" for i, p in enumerate(productos, 1)
        )
        secciones.append(
            "Productos del catálogo relacionados (numerados y ordenados de menor a "
            "mayor precio dentro de cada nivel de relevancia; usa esta numeración "
            "para responder de forma consistente a preguntas como \"la más barata\" "
            f"[opción 1] o \"la segunda más barata\" [opción 2]):\n{productos_texto}"
        )

        # Gate 2026-09-23 — el cliente pidió un número PUNTUAL de cuotas que
        # no es uno de los plazos que ya se muestran arriba (ej. "¿y en 15
        # cuotas?") — se calcula aparte, solo para el producto más relevante
        # (el primero de la lista), para no inflar el contexto repitiéndolo
        # por cada producto mostrado.
        cuotas_pedidas = _cuotas_pedidas_en_mensaje(mensaje)
        if cuotas_pedidas is not None and str(cuotas_pedidas) not in PLAZOS_A_MOSTRAR:
            monto_principal = _precio_float(productos[0])
            if monto_principal != float("inf"):
                calculo = _calcular_amortizacion(monto_principal, tea, igv, cuotas_pedidas)
                secciones.append(
                    f"El cliente preguntó puntualmente por {cuotas_pedidas} cuotas/meses — "
                    f"para la opción 1 ({productos[0].get('DESCRIPCIÓN', '')}) esa cuota "
                    f"sería S/ {calculo['cuota_inicial']:.2f} al mes."
                )

    conocimiento = buscar_en_knowledge(mensaje, negocio_codigo, limite=limite_conocimiento)
    if conocimiento:
        secciones.append(f"Información de la base de conocimiento:\n{conocimiento}")

    return "\n\n".join(secciones)
