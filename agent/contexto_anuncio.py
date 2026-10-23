# agent/contexto_anuncio.py — Que Gabi sepa por qué anuncio entró el cliente (mejora M1, 2026-10-23).
#
# La auditoría de 674 chats (docs/auditoria_chats_gabi_2026-10-18.md) mostró 43 conversaciones de clientes que
# llegaron por una campaña conocida y a los que Gabi igual les preguntó «¿qué producto te interesa?» (0 % agendado
# o vendido). Hasta hoy Gabi solo recibía la promoción cuando la campaña tenía producto/precio; con un anuncio
# «Sin campaña» no sabía qué se anunciaba.
#
# Este módulo es PURO (no toca base ni red): arma, a partir del objeto `origen` de la conversación
# (agent/origen_conversacion.py), el bloque de contexto que va en <contexto_negocio>. Quien lo llama (brain.py)
# decide el modo (apagado / sombra / activo) y si ya hubo promoción de campaña.
#
# Reglas que impone al modelo:
#   · responder sobre lo que se anunció y NO preguntar el producto si el anuncio lo indica;
#   · nunca citar precios, descuentos ni promociones que no estén en el contexto/catálogo (el texto del anuncio puede
#     prometer algo que ya no esté vigente: Gabi no lo confirma, lo deriva al asesor);
#   · si la campaña apunta a un material que ya no está en el catálogo, no dar precio.

MODO_APAGADO = "apagado"
MODO_SOMBRA = "sombra"      # solo registra qué bloque habría usado; no cambia lo que ve Gabi
MODO_ACTIVO = "activo"
MODOS = (MODO_APAGADO, MODO_SOMBRA, MODO_ACTIVO)
MODO_POR_DEFECTO = MODO_SOMBRA
CLAVE_MODO = "gabi_contexto_anuncio_modo"

# Solo en los primeros turnos del cliente: después la conversación ya trae el producto en el historial.
MAXIMO_MENSAJES_CLIENTE = 4

TIPOS_CON_ANUNCIO = ("anuncio_meta", "anuncio_sin_campana")


def normalizar_modo(valor: str | None) -> str:
    valor = (valor or "").strip().lower()
    return valor if valor in MODOS else MODO_POR_DEFECTO


def _una_linea(texto: str | None, largo: int) -> str:
    """Una sola línea, sin comillas angulares, etiquetas ni saltos: el texto del anuncio va dentro de un bloque de contexto."""
    limpio = " ".join((texto or "").replace("«", "").replace("»", "").replace('"', "'").replace("<", "").replace(">", "").split())
    return limpio if len(limpio) <= largo else limpio[: largo - 1].rstrip() + "…"


def hay_anuncio(origen: dict | None) -> bool:
    return bool(origen) and origen.get("tipo") in TIPOS_CON_ANUNCIO and bool(origen.get("anuncio"))


def bloque_anuncio(origen: dict | None, *, hay_promo_de_campana: bool) -> str | None:
    """Texto para <contexto_negocio>, o None si el cliente no vino de un anuncio con datos."""
    if not hay_anuncio(origen):
        return None
    anuncio = origen["anuncio"]
    titulo = _una_linea(anuncio.get("titulo"), 150)
    cuerpo = _una_linea(anuncio.get("cuerpo"), 200)
    if not (titulo or cuerpo):
        return None
    partes = ["El cliente llegó desde un anuncio de Meta"]
    if titulo:
        partes.append(f"titulado «{titulo}»")
    if cuerpo:
        partes.append(f"con el texto «{cuerpo}»")
    texto = " ".join(partes) + "."
    texto += (
        " Ya sabes qué se anunció: responde sobre ESO y no le preguntes qué producto le interesa si el anuncio lo indica"
        " (pregúntalo solo si el anuncio no deja claro el producto y el cliente tampoco lo dijo)."
    )
    if not hay_promo_de_campana:
        texto += (
            " Este anuncio no tiene un precio vigente asociado en tu información: no cites precios, descuentos ni"
            " promociones que no estén en el contexto o en el catálogo; si el anuncio los menciona, no los confirmes y"
            " di que el asesor te confirma el dato."
        )
    return texto


def bloque_precio_no_disponible(nombre_campana: str | None) -> str:
    """La campaña apunta a un material que ya no está en el catálogo y no tiene precio manual."""
    nombre = _una_linea(nombre_campana, 100)
    cuando = f" «{nombre}»" if nombre else ""
    return (
        f"Para la campaña{cuando} no tienes un precio vigente en tu información: no menciones ningún precio ni"
        " promoción de esa campaña. Ayuda con el producto y di que el asesor le confirma el precio."
    )


def resumen_sombra(origen: dict | None, *, hay_promo_de_campana: bool, precio_no_disponible: bool) -> dict:
    """Métricas del log `contexto_anuncio` del modo sombra. Sin texto del anuncio ni teléfonos."""
    return {
        "tiene_anuncio": hay_anuncio(origen),
        "tipo": (origen or {}).get("tipo"),
        "hay_promo": bool(hay_promo_de_campana),
        "precio_no_disponible": bool(precio_no_disponible),
        "habria_bloque": bool(bloque_anuncio(origen, hay_promo_de_campana=hay_promo_de_campana)),
    }
