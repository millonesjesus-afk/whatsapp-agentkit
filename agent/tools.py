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
import logging
from datetime import datetime, time
from zoneinfo import ZoneInfo

from agent.memory import listar_productos_activos, obtener_producto_por_codigo_hana, listar_horarios_atencion

logger = logging.getLogger("agentkit")

TZ_LIMA = ZoneInfo("America/Lima")
DIAS_ES = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]

KNOWLEDGE_DIR = "knowledge"
PLAZOS_A_MOSTRAR = ("12", "24", "36")

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


async def buscar_productos(mensaje: str, limite: int = 8, excluir_codigos: set[str] | None = None) -> list[dict]:
    """
    Busca productos del catálogo cuyo tipo, sub tipo o marca aparezcan
    mencionados en el mensaje del cliente. Prioriza coincidencias de marca
    (señal más específica) por sobre coincidencias genéricas de tipo, para
    que mencionar una marca puntual (ej. "Rheem") no quede opacado por
    productos de otras marcas que solo comparten el tipo (ej. "terma").
    Dentro de un mismo nivel de relevancia, ordena de menor a mayor precio,
    para que preguntas como "la más barata" o "la segunda más barata" se
    puedan responder de forma consistente por posición.

    Args:
        mensaje: mensaje del cliente (ej: "quiero una terma a gas Rheem")
        limite: máximo de resultados a retornar
        excluir_codigos: códigos de material (CODIGO HANA) a excluir de la
            búsqueda general — se usa para que un precio promocional
            reservado a una campaña específica (ej. la Terma a S/419.90 de
            "SMS Terma a gas") no aparezca como oferta general a cualquier
            cliente que mencione "terma" sin venir de esa campaña.

    Returns:
        Lista de productos coincidentes con sus datos de precio y cuotas,
        ordenados de mayor a menor relevancia y, dentro de eso, de menor a
        mayor precio.
    """
    mensaje = mensaje.lower()
    excluir_codigos = excluir_codigos or set()
    candidatos = []
    for producto in await listar_productos_activos():
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

        if score > 0:
            candidatos.append((score, producto))

    candidatos.sort(key=lambda item: (-item[0], _precio_float(item[1])))
    return [producto for _, producto in candidatos[:limite]]


async def obtener_producto_por_codigo(codigo: str) -> dict | None:
    """
    Busca un producto del catálogo por su código único de material (CODIGO
    HANA), la lista de precios oficial. Se usa para que las campañas
    (agent/campanas.py) referencien un producto real por código en vez de
    texto libre — así el precio de la promo nunca queda desincronizado de
    la lista de precios vigente.
    """
    codigo = (codigo or "").strip()
    if not codigo:
        return None
    return await obtener_producto_por_codigo_hana(codigo)


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


async def obtener_familia_producto(codigo_material: str) -> list[dict]:
    """
    Dado el código de un producto, retorna todas las variantes de combo/
    instalación del MISMO modelo base (misma marca, mismo proveedor, misma
    descripción sin contar +CONEXIÓN/+COMBO/+DUCTERÍA/etc.) Y el mismo nivel
    de fee (FEE PRV/FEE CLDA), ordenadas de menor a mayor precio, incluyendo
    el producto original.

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
    ancla = await obtener_producto_por_codigo(codigo_material)
    if ancla is None:
        return []

    marca = ancla.get("MARCA", "").strip().upper()
    proveedor = ancla.get("PROVEEDOR", "").strip().upper()
    base = _modelo_base(ancla.get("DESCRIPCIÓN", ""))
    fee_prv = ancla.get("FEE PRV", "").strip()
    fee_clda = ancla.get("FEE CLDA", "").strip()

    familia = [
        p for p in await listar_productos_activos()
        if p.get("MARCA", "").strip().upper() == marca
        and p.get("PROVEEDOR", "").strip().upper() == proveedor
        and _modelo_base(p.get("DESCRIPCIÓN", "")) == base
        and p.get("FEE PRV", "").strip() == fee_prv
        and p.get("FEE CLDA", "").strip() == fee_clda
    ]
    familia.sort(key=_precio_float)
    return familia


def formatear_producto(producto: dict) -> str:
    """Da formato legible a un producto del catálogo."""
    marca = producto.get("MARCA", "")
    descripcion = producto.get("DESCRIPCIÓN", "")
    precio = producto.get("PRECIO", "")
    canal = producto.get("CANAL", "")

    cuotas = [
        f"{plazo} meses: S/ {producto[plazo]}"
        for plazo in PLAZOS_A_MOSTRAR
        if producto.get(plazo)
    ]

    lineas = [f"{marca} — {descripcion}", f"Precio: S/ {precio}", f"Canal: {canal}"]
    if cuotas:
        lineas.append("Cuotas: " + " | ".join(cuotas))
    return "\n".join(lineas)


def _dividir_en_parrafos(contenido: str, min_len: int = 20) -> list[str]:
    """Divide un documento en párrafos/líneas para poder buscar con precisión
    dentro de documentos largos (como el contrato), en vez de truncar todo
    el documento a sus primeros caracteres."""
    return [linea.strip() for linea in contenido.split("\n") if len(linea.strip()) >= min_len]


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
            for parrafo in _dividir_en_parrafos(contenido):
                score = sum(1 for palabra in palabras if palabra in parrafo.lower())
                if score > 0:
                    candidatos.append((score, nombre, parrafo))

    candidatos.sort(key=lambda item: item[0], reverse=True)
    secciones = [f"[{nombre}] {parrafo}" for _, nombre, parrafo in candidatos[:limite]]
    return "\n---\n".join(secciones)


# Gate 4.2 (Decisión 5, Gate 4.1) — rango que corría hardcodeado acá mismo
# antes de este Gate, sin relación con negocio_id. Se conserva SOLO como
# fallback para un negocio_id que todavía no tiene HorarioAtencion
# backfilleado (nunca debería pasar para un Negocio real, ver migración de
# backfill) — nunca como la fuente de verdad.
_FALLBACK_DIAS_HABILITADOS = range(0, 6)  # lunes a sábado
_FALLBACK_HORA_APERTURA = time(8, 0)
_FALLBACK_HORA_CIERRE = time(19, 0)


async def obtener_estado_horario_atencion(negocio_id: str | None) -> dict:
    """
    Calcula si AHORA MISMO (hora real de Lima) se está dentro del horario de
    atención de los asesores humanos DE ESTE NEGOCIO. Un modelo de lenguaje
    no tiene reloj propio — sin esto, no hay forma de que Gabi sepa si un
    asesor está disponible en este momento o no.

    Gate 4.2 — antes de este Gate, el rango estaba hardcodeado acá mismo
    (lunes a sábado, 8:00-19:00) sin relación con `negocio_id`: un segundo
    Negocio con otro horario recibía la respuesta de Cálidda. Ahora resuelve
    `HorarioAtencion` por `negocio_id`; si el Negocio no tiene fila para el
    día de hoy (no backfilleado todavía), cae al mismo rango que estaba
    hardcodeado — comportamiento sin cambios para quien no fue migrado.
    """
    ahora = datetime.now(TZ_LIMA)
    dia_semana = ahora.weekday()  # 0=lunes … 6=domingo
    hora_actual = ahora.time()

    horario_hoy = None
    if negocio_id is not None:
        horarios = await listar_horarios_atencion(negocio_id)
        horario_hoy = next((h for h in horarios if h["dia_semana"] == dia_semana), None)

    if horario_hoy is not None:
        dentro = (
            horario_hoy["habilitado"]
            and horario_hoy["hora_apertura"] is not None
            and horario_hoy["hora_cierre"] is not None
            and time.fromisoformat(horario_hoy["hora_apertura"]) <= hora_actual < time.fromisoformat(horario_hoy["hora_cierre"])
        )
    else:
        dentro = dia_semana in _FALLBACK_DIAS_HABILITADOS and _FALLBACK_HORA_APERTURA <= hora_actual < _FALLBACK_HORA_CIERRE

    return {
        "dentro_de_horario": dentro,
        "fecha_hora_lima": f"{DIAS_ES[dia_semana]} {ahora.strftime('%d/%m/%Y')}, {ahora.strftime('%H:%M')} (hora de Lima)",
    }


async def obtener_contexto_relevante(
    mensaje: str, negocio_codigo: str | None = None, excluir_codigos: set[str] | None = None,
) -> str:
    """
    Punto de entrada usado por brain.py: combina resultados del catálogo de
    productos y de la base de conocimiento relacionados al mensaje del cliente.

    `negocio_codigo` solo se propaga hacia `buscar_en_knowledge` — el
    catálogo de productos (`buscar_productos`) NO tiene todavía aislamiento
    por Negocio (`Producto` no tiene columna `negocio_id`, es deuda
    arquitectónica real pero de un alcance mucho mayor: migración de
    esquema + backfill + todas las rutas del panel de Catálogo — queda
    documentada como Gate propio, deliberadamente fuera de esta corrección
    puntual). Hoy Cálidda es el único Negocio con productos reales, así
    que esto no contamina ninguna conversación real todavía — ver el
    análisis dedicado en el informe de este Gate."""
    secciones = []

    productos = await buscar_productos(mensaje, excluir_codigos=excluir_codigos)
    if productos:
        productos_texto = "\n\n".join(
            f"{i}. {formatear_producto(p)}" for i, p in enumerate(productos, 1)
        )
        secciones.append(
            "Productos del catálogo relacionados (numerados y ordenados de menor a "
            "mayor precio dentro de cada nivel de relevancia; usa esta numeración "
            "para responder de forma consistente a preguntas como \"la más barata\" "
            f"[opción 1] o \"la segunda más barata\" [opción 2]):\n{productos_texto}"
        )

    conocimiento = buscar_en_knowledge(mensaje, negocio_codigo)
    if conocimiento:
        secciones.append(f"Información de la base de conocimiento:\n{conocimiento}")

    return "\n\n".join(secciones)
