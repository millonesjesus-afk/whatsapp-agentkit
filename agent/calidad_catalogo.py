"""Avisos de calidad del catálogo al importar un CSV.

Gabi solo conoce de un producto lo que dice su fila: si a una terma, secadora o centro de lavado le falta la
capacidad, o a una fila le falta el precio, Gabi se queda sin dato y termina suponiéndolo (así salió «Mabe 10 kg»).
Estos avisos NO bloquean la importación: le dicen al admin qué filas corregir y por qué, para que las arregle
en el CSV o en el panel.

Función pura, sin base de datos: recibe las filas ya normalizadas por `_fila_csv_a_datos`.
"""

import re

# Qué productos exigen capacidad y en qué unidad. Se detectan por tipo, subtipo o descripción, sin importar mayúsculas.
_TIPOS_CON_CAPACIDAD = (
    ("terma", re.compile(r"terma|termotanque|calentador", re.I),
     re.compile(r"\d+(?:[.,]\d+)?\s*(?:l/min|lpm|lts?|litros?|l|gal(?:ones)?)(?![a-z])", re.I),
     "litros (por ejemplo «10 LT» o «5.5 L»)"),
    ("secadora", re.compile(r"secadora", re.I),
     re.compile(r"\d+(?:[.,]\d+)?\s*(?:kgs?|kilos?)(?![a-z])", re.I), "kilos (por ejemplo «22 KG»)"),
    ("centro de lavado", re.compile(r"lavadora|lavaseca|lavasecadora|centro de lavado", re.I),
     re.compile(r"\d+(?:[.,]\d+)?\s*(?:kgs?|kilos?)(?![a-z])", re.I), "kilos (por ejemplo «20 KG»)"),
)
_CON_CONEXION = ("terma", "secadora", "centro de lavado", "cocina")
_TIPOS_QUE_EL_FLUJO_OFRECE = ("terma", "secadora", "cocina")
_COCINA = re.compile(r"cocina|encimera", re.I)
_TRABAJO = re.compile(r"trabajos?|punto adicional|ducter[ií]a|instalaci[oó]n", re.I)


def _categoria(datos: dict) -> str | None:
    texto = " ".join(datos.get(c) or "" for c in ("tipo", "sub_tipo", "descripcion"))
    if _TRABAJO.search(datos.get("tipo") or "") or _TRABAJO.search(datos.get("sub_tipo") or ""):
        return None  # los servicios (punto adicional, ductería) no son equipos
    for nombre, patron, _capacidad, _unidad in _TIPOS_CON_CAPACIDAD:
        if patron.search(texto):
            return nombre
    if _COCINA.search(texto):
        return "cocina"
    return None


def _precio_valido(valor) -> bool:
    limpio = re.sub(r"[^\d.,]", "", str(valor or ""))
    if not limpio:
        return False
    try:
        return float(limpio.replace(",", "")) > 0
    except ValueError:
        return False


def avisos_de_calidad_catalogo(filas: list[dict], excluidas: set[tuple[str, str]] | None = None) -> dict:
    """Devuelve {"total": n, "por_tipo": {tipo: n}, "avisos": [{tipo, codigo, descripcion, mensaje}]}.

    `excluidas`: pares (proveedor, descripción) que la importación deja inactivos (no se avisa por ellos)."""
    excluidas = excluidas or set()
    avisos: list[dict] = []
    con_precio_por_categoria: dict[str, int] = {}

    def avisar(tipo: str, datos: dict, mensaje: str):
        avisos.append({
            "tipo": tipo, "codigo": datos.get("codigo_hana") or "", "descripcion": datos.get("descripcion") or "",
            "mensaje": mensaje,
        })

    for datos in filas:
        if ((datos.get("proveedor") or ""), (datos.get("descripcion") or "")) in excluidas:
            continue
        descripcion = datos.get("descripcion") or ""
        categoria = _categoria(datos)
        precio_ok = _precio_valido(datos.get("precio"))

        if not descripcion:
            avisar("sin_descripcion", datos, "No tiene descripción: Gabi no sabría cómo nombrar el producto.")
        if not precio_ok:
            avisar("sin_precio", datos, "El precio está vacío o no es un número: Gabi no puede cotizarlo ni calcular cuotas.")
        elif categoria:
            con_precio_por_categoria[categoria] = con_precio_por_categoria.get(categoria, 0) + 1
        if not (datos.get("marca") or "").strip():
            avisar("sin_marca", datos, "No tiene marca: Gabi no podrá ofrecerlo por marca.")
        if not (datos.get("tipo") or "").strip() and not (datos.get("sub_tipo") or "").strip():
            avisar("sin_tipo", datos, "No tiene tipo ni subtipo: Gabi tiene más difícil encontrarlo cuando el cliente pide esa categoría.")

        for nombre, _patron_tipo, patron_capacidad, unidad in _TIPOS_CON_CAPACIDAD:
            if categoria == nombre and not patron_capacidad.search(descripcion):
                avisar(
                    "sin_capacidad", datos,
                    f"Es {nombre} y la descripción no indica la capacidad en {unidad}. "
                    "Sin ese dato Gabi puede inventarla; agrégala a la descripción.",
                )
        if categoria in _CON_CONEXION and not (datos.get("incluye_conexion") or "").strip():
            avisar("sin_conexion", datos, "No indica si incluye conexión (SI/NO): Gabi no sabría explicar qué trae el precio.")

    # Categorías que el flujo guiado ofrece y quedarían sin un solo producto con precio: Gabi se queda sin piso.
    for categoria in _TIPOS_QUE_EL_FLUJO_OFRECE:
        if con_precio_por_categoria.get(categoria, 0) == 0:
            avisos.append({
                "tipo": "categoria_vacia", "codigo": "", "descripcion": categoria,
                "mensaje": f"Ninguna fila de «{categoria}» tiene precio válido: Gabi no tendría qué ofrecer cuando el cliente pida ese equipo.",
            })

    por_tipo: dict[str, int] = {}
    for a in avisos:
        por_tipo[a["tipo"]] = por_tipo.get(a["tipo"], 0) + 1
    return {"total": len(avisos), "por_tipo": por_tipo, "avisos": avisos}
