# agent/tools.py — Herramientas del agente
# Generado por AgentKit

"""
Herramientas específicas del negocio Gaso+: búsqueda en el catálogo de
productos (termas, cocinas, secadoras, servicios) y en la base de
conocimiento del programa, para dar contexto real a las respuestas de Gabi.
"""

import os
import re
import csv
import glob
import logging

logger = logging.getLogger("agentkit")

KNOWLEDGE_DIR = "knowledge"
# Este proyecto usa únicamente el canal propio (no nuevos suministros)
ARCHIVOS_CATALOGO = [
    "lista_precios_canales_propios.csv",
]
PLAZOS_A_MOSTRAR = ("12", "24", "36")

_catalogo_cache: list[dict] | None = None


def _cargar_catalogo() -> list[dict]:
    """Carga y cachea en memoria el catálogo de productos desde los CSV de /knowledge."""
    global _catalogo_cache
    if _catalogo_cache is not None:
        return _catalogo_cache

    productos = []
    for nombre_archivo in ARCHIVOS_CATALOGO:
        ruta = os.path.join(KNOWLEDGE_DIR, nombre_archivo)
        if not os.path.exists(ruta):
            continue
        with open(ruta, "r", encoding="utf-8") as f:
            productos.extend(csv.DictReader(f))

    _catalogo_cache = productos
    return productos


def buscar_productos(mensaje: str, limite: int = 5) -> list[dict]:
    """
    Busca productos del catálogo cuyo tipo, sub tipo o marca aparezcan
    mencionados en el mensaje del cliente. Prioriza coincidencias de marca
    (señal más específica) por sobre coincidencias genéricas de tipo, para
    que mencionar una marca puntual (ej. "Rheem") no quede opacado por
    productos de otras marcas que solo comparten el tipo (ej. "terma").

    Args:
        mensaje: mensaje del cliente (ej: "quiero una terma a gas Rheem")
        limite: máximo de resultados a retornar

    Returns:
        Lista de productos coincidentes con sus datos de precio y cuotas,
        ordenados de mayor a menor relevancia.
    """
    mensaje = mensaje.lower()
    candidatos = []
    for producto in _cargar_catalogo():
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

    candidatos.sort(key=lambda item: item[0], reverse=True)
    return [producto for _, producto in candidatos[:limite]]


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


def buscar_en_knowledge(mensaje: str, limite: int = 4) -> str:
    """
    Busca, a nivel de párrafo, los fragmentos de /knowledge (base de
    conocimiento, contrato, speech, resumen del programa) que compartan más
    palabras clave con el mensaje del cliente. Trabajar por párrafo evita
    que la cláusula relevante de un documento largo (ej. el contrato de
    financiamiento) quede fuera por estar más allá de los primeros caracteres.
    """
    palabras = {p for p in re.findall(r"\w+", mensaje.lower()) if len(p) >= 4}
    if not palabras:
        return ""

    candidatos = []
    for patron in ("*.md", "*.txt"):
        for ruta in glob.glob(os.path.join(KNOWLEDGE_DIR, patron)):
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


def obtener_horario_derivacion() -> dict:
    """Retorna el horario de atención de los asesores humanos para derivación."""
    return {
        "lunes_a_viernes": "8:00am - 7:00pm",
        "sabados": "8:00am - 6:00pm",
        "domingos": "sin atención de asesores",
    }


def obtener_contexto_relevante(mensaje: str) -> str:
    """
    Punto de entrada usado por brain.py: combina resultados del catálogo de
    productos y de la base de conocimiento relacionados al mensaje del cliente.
    """
    secciones = []

    productos = buscar_productos(mensaje)
    if productos:
        productos_texto = "\n\n".join(formatear_producto(p) for p in productos)
        secciones.append(f"Productos del catálogo relacionados:\n{productos_texto}")

    conocimiento = buscar_en_knowledge(mensaje)
    if conocimiento:
        secciones.append(f"Información de la base de conocimiento:\n{conocimiento}")

    return "\n\n".join(secciones)
