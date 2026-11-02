# agent/derivacion_automatica.py — Configuración de la «Derivación automática» desde el panel (2026-10-11).
#
# Decisión del dueño: esta línea de WhatsApp es COMERCIAL. Los casos SIN posibilidad de venta (recibo, número de cliente,
# pago/deuda y EMERGENCIA de gas) se derivan al canal correcto y se tipifican y cierran solos, sin asesor y sin gastar
# tokens (agent/triaje_atc.py). Hasta hoy sus claves de configuración solo se cambiaban con
# scripts/configurar_triaje_atc.py; este módulo es la capa común que usan el script Y las rutas
# GET/POST /dashboard/configuracion/derivacion-automatica.json:
#   · las validaciones de texto (antes dentro del script: `validar_texto`, `validar_texto_emergencia`);
#   · el estado EFECTIVO (qué hace de verdad cada categoría; p. ej. «activo» sin línea degrada a sombra);
#   · el guardado todo-o-nada con auditoría (`RegistroAuditoria`, entidad «configuracion»: sale en el Historial);
#   · un resumen de actividad de los últimos 30 días, sin datos personales.
#
# NO cambia la semántica del triaje. Hay DOS interruptores independientes (`triaje_atc_modo` para recibo, número de
# cliente y pago/deuda; `triaje_atc_emergencia_modo` para la emergencia de gas). Cada categoría general se «incluye»
# o no (`triaje_atc_categorias_activas`): una no incluida no se deriva ni se cierra. Todo viene APAGADO por defecto y
# guardar sin cambiar nada no escribe ni activa nada.

import re
from datetime import datetime, timedelta

from sqlalchemy import select

from agent import memory as mem
from agent import triaje_atc as t

TEXTO_MAXIMO = 600
LINEA_MAXIMA = 120
NOMBRE_NEGOCIO_MAXIMO = 120
ACCION_AUDITORIA = "derivacion_automatica_config"
DIAS_ACTIVIDAD = 30
MAX_EVENTOS_ACTIVIDAD = 20000

CATEGORIA_EMERGENCIA = t.CATEGORIA_EMERGENCIA
ETIQUETAS_CATEGORIA = {
    "recibo": "Recibo", "numero_cliente": "Número de cliente", "pago_deuda": "Pago o deuda", "reclamo": "Reclamo o trámite",
    CATEGORIA_EMERGENCIA: "Emergencia de gas",
}

# Variables que reconoce `triaje_atc.texto_para` y su ejemplo para la vista previa.
VARIABLES = (
    {"nombre": "{nombre}", "descripcion": "Primer nombre del cliente, con su espacio delante («¡Hola{nombre}!»); queda vacío si no hay uno presentable.", "ejemplo": " Yasmin"},
    {"nombre": "{linea_atc}", "descripcion": "Línea de atención al cliente configurada abajo.", "ejemplo": "6149000, opción 5"},
    {"nombre": "{negocio}", "descripcion": "Nombre del negocio que sale en el texto.", "ejemplo": t.NOMBRE_NEGOCIO_POR_DEFECTO},
    {"nombre": "{linea_emergencia}", "descripcion": "Línea de emergencias configurada abajo.", "ejemplo": "1808 (Emergencias 24/7)"},
    {"nombre": "{linea_ventas}", "descripcion": "Línea de ventas configurada abajo.", "ejemplo": "614-9002"},
)
NOMBRES_VARIABLES = frozenset(v["nombre"] for v in VARIABLES)

# Lo que NUNCA se cierra solo (guardas fijas de `triaje_atc.clasificar`; no se configuran desde el panel).
NUNCA_SE_CIERRA = (
    "Casos con un asesor asignado, con Gabi pausada o en supervisión.",
    "Casos que ya tienen un resultado (vendido, agendado…) o que ya están cerrados.",
    "Conversaciones donde el cliente habló de comprar: producto, precio, cuotas, financiamiento, cotización.",
    "Casos donde una persona del equipo ya escribió, o donde Gabi ya pidió DNI, suministro o titular, o ya dio un precio.",
    "Si el cliente mandó fotos, audios, documentos o un número largo (DNI o suministro).",
    "Si el cliente ya escribió más mensajes que el máximo permitido para derivar.",
    "Chats de un canal de pruebas y números del equipo.",
    "Una emergencia de gas con asesor, pausa o resultado SÍ recibe el aviso, pero el caso no se cierra.",
)

_CLAVES_CUERPO = (
    "modo", "emergencia_modo", "categorias", "lineas", "nombre_negocio", "texto_general", "textos_categoria",
    "texto_emergencia", "resultado",
)
_CLAVES_LINEAS = ("atencion", "emergencia", "ventas")


# ── Validaciones de texto (compartidas con scripts/configurar_triaje_atc.py) ──────────────────────────────

def validar_texto(texto: str, etiqueta: str) -> str:
    """El texto no puede dejar nada pendiente para el cierre de cortesía: sin «?» ni compromisos/peticiones; si no,
    un «ok» o «gracias» posterior del cliente reabriría el caso en vez de absorberse."""
    texto = texto.strip()
    if not texto:
        return ""
    if len(texto) > TEXTO_MAXIMO:
        raise ValueError(f"{etiqueta}: máximo {TEXTO_MAXIMO} caracteres.")
    if "?" in texto or "¿" in texto:
        raise ValueError(f"{etiqueta}: no puede llevar «?» ni «¿» (un «ok» del cliente reabriría el caso).")
    if mem.saliente_deja_algo_pendiente(texto.replace("{nombre}", "").replace("{linea_atc}", "6149000")):
        raise ValueError(
            f"{etiqueta}: contiene una palabra que el cierre de cortesía lee como compromiso o petición pendiente "
            "(llamar, necesitar, enviar, avisar, contar, DNI, días de la semana, horas…). Reescríbelo con otras palabras.",
        )
    return texto


def validar_texto_emergencia(texto: str, etiqueta: str = "--emergencia-texto", linea: str | None = None) -> tuple[str, list[str]]:
    """Valida el texto del aviso de emergencia. ERRORES: más de TEXTO_MAXIMO caracteres, «?»/«¿», o que no lleve la línea de
    emergencia (el marcador {linea_emergencia} o, si se indica `linea`, ese mismo texto). ADVERTENCIA (no bloquea): si el texto
    deja algo pendiente para el cierre de cortesía (p. ej. «llama…»), un «ok» posterior del cliente reabriría el caso y Gabi
    respondería. NO se aplica la regla de palabras prohibidas de los demás textos: esta se escribe para que un «gracias»
    siempre se absorba, pero quien lo personalice puede usar «llama»."""
    texto = texto.strip()
    if not texto:
        return "", []
    if len(texto) > TEXTO_MAXIMO:
        raise ValueError(f"{etiqueta}: máximo {TEXTO_MAXIMO} caracteres.")
    if "?" in texto or "¿" in texto:
        raise ValueError(f"{etiqueta}: no puede llevar «?» ni «¿» (es una instrucción de seguridad, no una pregunta).")
    if "{linea_emergencia}" not in texto and not ((linea or "").strip() and linea.strip() in texto):
        raise ValueError(
            f"{etiqueta}: debe llevar la línea de emergencia: usa el marcador {{linea_emergencia}} (se rellena con "
            "la línea de emergencia configurada, p. ej. \"1808 (Emergencias 24/7)\")."
        )
    avisos = []
    if mem.saliente_deja_algo_pendiente(texto.replace("{nombre}", "").replace("{linea_emergencia}", "1808 (Emergencias 24/7)")):
        avisos.append(
            f"AVISO {etiqueta}: el texto tiene una palabra que el cierre de cortesía lee como compromiso o petición pendiente "
            "(llamar, enviar, avisar, necesitar, días, horas…): un «ok» del cliente reabriría el caso y Gabi respondería. "
            "Un «gracias» sí se absorbe. El texto por defecto usa «Comunícate ya con…» para evitarlo."
        )
    return texto, avisos


def variables_desconocidas(texto: str) -> list[str]:
    """Marcadores `{algo}` que `texto_para` NO reconoce (saldrían tal cual al cliente: casi siempre un error de tipeo)."""
    return sorted({m for m in re.findall(r"\{[^{}]*\}", texto or "") if m not in NOMBRES_VARIABLES})


def _validar_variables(texto: str, etiqueta: str) -> None:
    desconocidas = variables_desconocidas(texto)
    if desconocidas:
        validas = ", ".join(sorted(NOMBRES_VARIABLES))
        raise ValueError(f"{etiqueta}: {', '.join(desconocidas)} no es una variable válida. Las válidas son {validas}.")


def validar_linea(valor: str, etiqueta: str, maximo: int = LINEA_MAXIMA) -> str:
    """Una línea (o el nombre del negocio) que se inserta dentro de los textos: corta, de una sola línea, sin «?»/«¿»
    ni llaves (rompería la regla de los textos o los marcadores)."""
    texto = valor.strip()
    if len(texto) > maximo:
        raise ValueError(f"{etiqueta}: máximo {maximo} caracteres.")
    if "?" in texto or "¿" in texto:
        raise ValueError(f"{etiqueta}: no puede llevar «?» ni «¿».")
    if "{" in texto or "}" in texto:
        raise ValueError(f"{etiqueta}: no puede llevar llaves.")
    if re.search(r"[\x00-\x1f\x7f]", texto):
        raise ValueError(f"{etiqueta}: debe ir en una sola línea.")
    return texto


# ── Lectura: estado efectivo ──────────────────────────────────────────────────────────────────────────

_CLAVES_LECTURA = (
    t.CLAVE_MODO, t.CLAVE_EMERGENCIA_MODO, t.CLAVE_CATEGORIAS, t.CLAVE_LINEA, t.CLAVE_LINEA_EMERGENCIA, t.CLAVE_LINEA_VENTAS,
    t.CLAVE_NOMBRE_NEGOCIO, t.CLAVE_TEXTO, t.CLAVE_EMERGENCIA_TEXTO, mem.CLAVE_TRIAJE_RESULTADO,
) + tuple(t.CLAVE_TEXTO_CATEGORIA + c for c in t.CATEGORIAS_ATC)


async def _leer_claves(negocio_id: str) -> dict[str, str]:
    async with mem.async_session() as session:
        filas = (await session.execute(
            select(mem.Configuracion.clave, mem.Configuracion.valor).where(
                mem.Configuracion.negocio_id == negocio_id, mem.Configuracion.clave.in_(_CLAVES_LECTURA),
            )
        )).all()
    return {clave: (valor or "") for clave, valor in filas}


def _categorias_incluidas(valor: str | None) -> tuple[str, ...]:
    """Mismo criterio que `triaje_atc._armar_contexto`: lista vacía = las tres. Se devuelven en orden canónico y
    solo las que existen."""
    elegidas = set(t._parsear_lista(valor)) or set(t.CATEGORIAS_ATC)
    return tuple(c for c in t.CATEGORIAS_ATC if c in elegidas)


def _estado_desde_claves(v: dict[str, str]) -> dict:
    g = lambda clave: (v.get(clave) or "").strip()  # noqa: E731
    modo = t._parsear_modo(g(t.CLAVE_MODO))
    emergencia = t._parsear_modo(g(t.CLAVE_EMERGENCIA_MODO))
    linea, linea_em, linea_ventas = g(t.CLAVE_LINEA), g(t.CLAVE_LINEA_EMERGENCIA), g(t.CLAVE_LINEA_VENTAS)
    texto_emergencia = g(t.CLAVE_EMERGENCIA_TEXTO)
    plantilla_emergencia = texto_emergencia or t.TEXTO_EMERGENCIA_POR_DEFECTO
    emergencia_enviable = not ("{linea_emergencia}" in plantilla_emergencia and not linea_em)
    incluidas = _categorias_incluidas(g(t.CLAVE_CATEGORIAS))

    # Mismas degradaciones que `triaje_atc.evaluar`: activo sin línea → sombra.
    modo_efectivo = t.MODO_SOMBRA if (modo == t.MODO_ACTIVO and not linea) else modo
    motivo_general = "sin_linea_atencion" if modo_efectivo != modo else None
    emergencia_efectiva = t.MODO_SOMBRA if (emergencia == t.MODO_ACTIVO and not emergencia_enviable) else emergencia
    motivo_emergencia = "sin_linea_emergencia" if emergencia_efectiva != emergencia else None

    textos_categoria = {c: g(t.CLAVE_TEXTO_CATEGORIA + c) for c in t.CATEGORIAS_ATC}
    texto_general = g(t.CLAVE_TEXTO)
    categorias = []
    for c in t.CATEGORIAS_ATC:
        incluida = c in incluidas
        categorias.append({
            "id": c, "etiqueta": ETIQUETAS_CATEGORIA[c], "incluida": incluida,
            "modo_configurado": modo if incluida else t.MODO_APAGADO,
            "estado_efectivo": modo_efectivo if incluida else t.MODO_APAGADO,
            "motivo_degradado": motivo_general if incluida else None,
            "texto_origen": "propio" if textos_categoria[c] else ("general" if texto_general else "original"),
        })
    categorias.append({
        "id": CATEGORIA_EMERGENCIA, "etiqueta": ETIQUETAS_CATEGORIA[CATEGORIA_EMERGENCIA], "incluida": emergencia != t.MODO_APAGADO,
        "modo_configurado": emergencia, "estado_efectivo": emergencia_efectiva, "motivo_degradado": motivo_emergencia,
        "texto_origen": "propio" if texto_emergencia else "original",
    })

    resultado = g(mem.CLAVE_TRIAJE_RESULTADO)
    resultado = resultado if mem.resultado_triaje_valido(resultado) else mem.RESULTADO_TRIAJE_POR_DEFECTO
    return {
        "modo": modo, "modo_efectivo": modo_efectivo, "modo_degradado_motivo": motivo_general,
        "emergencia_modo": emergencia, "emergencia_modo_efectivo": emergencia_efectiva, "emergencia_degradado_motivo": motivo_emergencia,
        "categorias_incluidas": list(incluidas),
        "categorias": categorias,
        "lineas": {"atencion": linea, "emergencia": linea_em, "ventas": linea_ventas},
        "nombre_negocio": g(t.CLAVE_NOMBRE_NEGOCIO),
        "nombre_negocio_por_defecto": t.NOMBRE_NEGOCIO_POR_DEFECTO,
        "texto_general": texto_general,
        "textos_categoria": textos_categoria,
        "texto_emergencia": texto_emergencia,
        "textos_originales": {"general": t.TEXTO_POR_DEFECTO, "emergencia": t.TEXTO_EMERGENCIA_POR_DEFECTO},
        "resultado": resultado,
        "resultado_por_defecto": mem.RESULTADO_TRIAJE_POR_DEFECTO,
        "resultados_permitidos": [{"valor": r, "etiqueta": mem.etiqueta_resultado(r)} for r in mem.RESULTADOS_TRIAJE_PERMITIDOS],
        "variables": [dict(x) for x in VARIABLES],
        "limites": {"texto": TEXTO_MAXIMO, "linea": LINEA_MAXIMA, "nombre_negocio": NOMBRE_NEGOCIO_MAXIMO},
        "nunca_se_cierra": list(NUNCA_SE_CIERRA),
    }


async def actividad_reciente(negocio_id: str, dias: int = DIAS_ACTIVIDAD, ahora: datetime | None = None) -> dict:
    """Cuántas decisiones/cierres hubo por categoría en los últimos `dias` días, a partir de los eventos internos del
    triaje (sin teléfonos, nombres ni textos: solo conteos). `{dias, truncado, por_categoria: [{categoria, etiqueta,
    registradas, propuestas_cierre, cerradas, avisos, fallidas}]}`."""
    ahora = ahora or datetime.utcnow()
    desde = ahora - timedelta(days=dias)
    tipos = (
        mem.EVENTO_TRIAJE_ATC_SOMBRA, mem.EVENTO_TRIAJE_ATC_CERRADO, mem.EVENTO_TRIAJE_ATC_FALLIDO, mem.EVENTO_EMERGENCIA_GAS_DERIVADA,
    )
    async with mem.async_session() as session:
        filas = (await session.execute(
            select(mem.EventoLead.tipo, mem.EventoLead.payload).where(
                mem.EventoLead.negocio_id == negocio_id, mem.EventoLead.creado >= desde, mem.EventoLead.tipo.in_(tipos),
            ).order_by(mem.EventoLead.id.desc()).limit(MAX_EVENTOS_ACTIVIDAD + 1)
        )).all()
    truncado = len(filas) > MAX_EVENTOS_ACTIVIDAD
    cuentas = {
        c: {"categoria": c, "etiqueta": ETIQUETAS_CATEGORIA[c], "registradas": 0, "propuestas_cierre": 0, "cerradas": 0, "avisos": 0, "fallidas": 0}
        for c in (*t.CATEGORIAS_ATC, CATEGORIA_EMERGENCIA)
    }
    for tipo, payload in filas[:MAX_EVENTOS_ACTIVIDAD]:
        p = payload if isinstance(payload, dict) else {}
        c = cuentas.get(p.get("categoria"))
        if c is None:
            continue
        if tipo == mem.EVENTO_TRIAJE_ATC_SOMBRA:
            c["registradas"] += 1
            if p.get("accion_propuesta") in (t.ACCION_CERRAR, t.ACCION_DERIVAR_EMERGENCIA):
                c["propuestas_cierre"] += 1
        elif tipo == mem.EVENTO_TRIAJE_ATC_CERRADO:
            c["cerradas"] += 1
        elif tipo == mem.EVENTO_TRIAJE_ATC_FALLIDO:
            c["fallidas"] += 1
        elif tipo == mem.EVENTO_EMERGENCIA_GAS_DERIVADA:
            c["avisos"] += 1
    return {"dias": dias, "truncado": truncado, "por_categoria": list(cuentas.values())}


async def estado_configuracion(negocio_id: str) -> dict:
    """Lo que devuelve `GET /dashboard/configuracion/derivacion-automatica.json`. La actividad es contexto opcional: si
    falla, la configuración se sigue pudiendo ver y cambiar (`actividad_30_dias: null`)."""
    estado = _estado_desde_claves(await _leer_claves(negocio_id))
    try:
        estado["actividad_30_dias"] = await actividad_reciente(negocio_id)
    except Exception:
        t.logger.warning("No se pudo calcular la actividad reciente de la derivación automática", exc_info=True)
        estado["actividad_30_dias"] = None
    return estado


# ── Escritura: validación todo-o-nada + auditoría ─────────────────────────────────────────────────────

def _texto(valor, etiqueta: str) -> str:
    if not isinstance(valor, str):
        raise ValueError(f"{etiqueta}: debe ser un texto.")
    return valor


def _modo(valor, etiqueta: str) -> str:
    if not isinstance(valor, str) or valor.strip().lower() not in t.MODOS:
        raise ValueError(f"{etiqueta}: debe ser apagado, sombra o activo.")
    return valor.strip().lower()


def _sin_linea_en_texto(texto: str, linea: str, marcador: str) -> bool:
    return marcador not in texto and not (linea and linea in texto)


def validar_cambios(cuerpo: dict, actuales: dict[str, str]) -> tuple[dict[str, str], list[str]]:
    """Valida el cuerpo completo (todo o nada) y devuelve `({clave de configuración: valor}, avisos)`. `actuales` son los
    valores guardados hoy (sirven para validar el estado FINAL: p. ej. activar con una línea ya guardada). Lanza
    ValueError en español con el primer problema. No toca la base."""
    if not isinstance(cuerpo, dict):
        raise ValueError("El cuerpo debe ser un objeto JSON.")
    desconocidos = sorted(k for k in cuerpo if k not in _CLAVES_CUERPO)
    if desconocidos:
        raise ValueError(f"Campo no reconocido: {', '.join(desconocidos)}.")
    cambios: dict[str, str] = {}
    avisos: list[str] = []

    if "modo" in cuerpo:
        cambios[t.CLAVE_MODO] = _modo(cuerpo["modo"], "El modo de la derivación automática")
    if "emergencia_modo" in cuerpo:
        cambios[t.CLAVE_EMERGENCIA_MODO] = _modo(cuerpo["emergencia_modo"], "El modo de emergencia de gas")

    if "categorias" in cuerpo:
        cats = cuerpo["categorias"]
        if not isinstance(cats, list) or not all(isinstance(c, str) for c in cats):
            raise ValueError("Las categorías deben ser una lista de textos.")
        elegidas = {c.strip().lower() for c in cats}
        invalidas = sorted(c for c in elegidas if c not in t.CATEGORIAS_ATC)
        if invalidas or not elegidas:
            raise ValueError(
                f"Elige al menos una categoría válida ({', '.join(t.CATEGORIAS_ATC)}). Para apagarlas todas, usa el modo «apagado»."
            )
        cambios[t.CLAVE_CATEGORIAS] = ",".join(c for c in t.CATEGORIAS_ATC if c in elegidas)

    if "lineas" in cuerpo:
        lineas = cuerpo["lineas"]
        if not isinstance(lineas, dict):
            raise ValueError("Las líneas deben ser un objeto con atencion, emergencia y/o ventas.")
        extra = sorted(k for k in lineas if k not in _CLAVES_LINEAS)
        if extra:
            raise ValueError(f"Línea no reconocida: {', '.join(extra)}.")
        for campo, clave, etiqueta in (
            ("atencion", t.CLAVE_LINEA, "La línea de atención al cliente"),
            ("emergencia", t.CLAVE_LINEA_EMERGENCIA, "La línea de emergencias"),
            ("ventas", t.CLAVE_LINEA_VENTAS, "La línea de ventas"),
        ):
            if campo in lineas:
                cambios[clave] = validar_linea(_texto(lineas[campo], etiqueta), etiqueta)

    if "nombre_negocio" in cuerpo:
        cambios[t.CLAVE_NOMBRE_NEGOCIO] = validar_linea(
            _texto(cuerpo["nombre_negocio"], "El nombre del negocio"), "El nombre del negocio", NOMBRE_NEGOCIO_MAXIMO,
        )

    def final(clave: str) -> str:
        return (cambios[clave] if clave in cambios else actuales.get(clave, "")).strip()

    linea_atencion, linea_emergencia = final(t.CLAVE_LINEA), final(t.CLAVE_LINEA_EMERGENCIA)

    if "texto_general" in cuerpo:
        etiqueta = "El texto general"
        texto = validar_texto(_texto(cuerpo["texto_general"], etiqueta), etiqueta)
        _validar_variables(texto, etiqueta)
        cambios[t.CLAVE_TEXTO] = texto
        if texto and _sin_linea_en_texto(texto, linea_atencion, "{linea_atc}"):
            avisos.append(f"AVISO {etiqueta}: no menciona la línea de atención ({{linea_atc}}); el cliente no sabrá a dónde acudir.")
    if "textos_categoria" in cuerpo:
        por_categoria = cuerpo["textos_categoria"]
        if not isinstance(por_categoria, dict):
            raise ValueError("Los textos por categoría deben ser un objeto {categoría: texto}.")
        for categoria, valor in por_categoria.items():
            if categoria not in t.CATEGORIAS_ATC:
                raise ValueError(f"Categoría no reconocida para un texto propio: {categoria}. Válidas: {', '.join(t.CATEGORIAS_ATC)}.")
            etiqueta = f"El texto de {ETIQUETAS_CATEGORIA[categoria].lower()}"
            texto = validar_texto(_texto(valor, etiqueta), etiqueta)
            _validar_variables(texto, etiqueta)
            cambios[t.CLAVE_TEXTO_CATEGORIA + categoria] = texto
            if texto and _sin_linea_en_texto(texto, linea_atencion, "{linea_atc}"):
                avisos.append(f"AVISO {etiqueta}: no menciona la línea de atención ({{linea_atc}}); el cliente no sabrá a dónde acudir.")
    if "texto_emergencia" in cuerpo:
        etiqueta = "El texto de emergencia"
        texto, avisos_texto = validar_texto_emergencia(_texto(cuerpo["texto_emergencia"], etiqueta), etiqueta, linea=linea_emergencia)
        _validar_variables(texto, etiqueta)
        cambios[t.CLAVE_EMERGENCIA_TEXTO] = texto
        avisos.extend(avisos_texto)

    if "resultado" in cuerpo:
        valor = cuerpo["resultado"]
        if not isinstance(valor, str) or not mem.resultado_triaje_valido(valor):
            opciones = ", ".join(f"«{mem.etiqueta_resultado(r)}»" for r in mem.RESULTADOS_TRIAJE_PERMITIDOS)
            raise ValueError(
                f"El resultado con que se cierran estos casos debe ser uno que cierre y no sea comercial: {opciones}."
            )
        cambios[mem.CLAVE_TRIAJE_RESULTADO] = valor.strip()
        if valor.strip() != mem.RESULTADO_TRIAJE_POR_DEFECTO:
            avisos.append(
                "AVISO El resultado elegido no es «Consulta ATC»: la exclusión de consultas de atención al cliente en las "
                "métricas solo reconoce «Consulta ATC», así que estos casos contarán como oportunidades en la tasa de cierre."
            )

    # Estado FINAL: no se puede dejar «activo» algo que no podría enviarse. Solo se exige cuando el pedido toca lo que lo afecta
    # (así un estado heredado inconsistente no impide guardar otra cosa).
    modo_final = cambios.get(t.CLAVE_MODO, t._parsear_modo(actuales.get(t.CLAVE_MODO)))
    if modo_final == t.MODO_ACTIVO and (t.CLAVE_MODO in cambios or t.CLAVE_LINEA in cambios) and not linea_atencion:
        raise ValueError(
            "No se puede activar la derivación sin la línea de atención al cliente: escríbela primero (p. ej. «614900, opción 5»)."
        )
    emergencia_final = cambios.get(
        t.CLAVE_EMERGENCIA_MODO, t._parsear_modo(actuales.get(t.CLAVE_EMERGENCIA_MODO)),
    )
    toca_emergencia = any(k in cambios for k in (t.CLAVE_EMERGENCIA_MODO, t.CLAVE_LINEA_EMERGENCIA, t.CLAVE_EMERGENCIA_TEXTO))
    if emergencia_final == t.MODO_ACTIVO and toca_emergencia:
        plantilla = final(t.CLAVE_EMERGENCIA_TEXTO) or t.TEXTO_EMERGENCIA_POR_DEFECTO
        if "{linea_emergencia}" in plantilla and not linea_emergencia:
            raise ValueError(
                "No se puede activar la emergencia de gas sin la línea de emergencias: escríbela primero "
                "(p. ej. «1808 (Emergencias 24/7)»)."
            )
    return cambios, avisos


def _igual(clave: str, antes: str | None, despues: str) -> bool:
    """¿`despues` equivale a lo que ya rige (guardado o valor por defecto)? Así guardar sin cambiar nada no escribe."""
    if clave in (t.CLAVE_MODO, t.CLAVE_EMERGENCIA_MODO):
        return t._parsear_modo(antes) == despues
    if clave == t.CLAVE_CATEGORIAS:
        return set(_categorias_incluidas(antes)) == set(t._parsear_lista(despues))
    if clave == mem.CLAVE_TRIAJE_RESULTADO:
        return ((antes or "").strip() if mem.resultado_triaje_valido(antes) else mem.RESULTADO_TRIAJE_POR_DEFECTO) == despues
    return (antes or "").strip() == despues


async def guardar_cambios(negocio_id: str, autor: str | None, cuerpo: dict) -> dict:
    """Valida y guarda cualquier subconjunto de campos (todo o nada) y devuelve `{"modificadas": [claves], "avisos":
    [...], **estado}`. Solo se escribe lo que realmente cambia; los valores y la fila de auditoría (quién, cuándo, antes
    y después) van en UNA transacción y salen en el Historial de configuración. Lanza ValueError con el motivo."""
    actuales = await _leer_claves(negocio_id)
    cambios, avisos = validar_cambios(cuerpo, actuales)
    registro: dict[str, dict] = {}
    if cambios:
        async with mem.async_session() as session:
            filas = {
                c.clave: c for c in (await session.execute(
                    select(mem.Configuracion).where(mem.Configuracion.negocio_id == negocio_id, mem.Configuracion.clave.in_(list(cambios)))
                )).scalars().all()
            }
            for clave, valor in cambios.items():
                existente = filas.get(clave)
                antes = existente.valor if existente else None
                if _igual(clave, antes, valor):
                    continue
                if existente is None:
                    session.add(mem.Configuracion(clave=clave, negocio_id=negocio_id, valor=valor))
                else:
                    existente.valor = valor
                registro[clave] = {"antes": antes, "despues": valor}
            if registro:
                session.add(mem.RegistroAuditoria(
                    accion=ACCION_AUDITORIA, actor=autor, negocio_id=negocio_id, entidad_tipo="configuracion",
                    payload={"cambios": registro, "riesgo_confirmado": False},
                ))
            await session.commit()
    return {"modificadas": sorted(registro), "avisos": avisos, **await estado_configuracion(negocio_id)}
