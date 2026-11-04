# agent/mix_haiku.py — Mix de modelos: Haiku escribe, una revisión sin IA decide, el modelo principal respalda (2026-11-03).
#
# Auditoría de la sombra (2-nov, 147 respuestas): Haiku 5.5 sale ~22 veces más barato que el modelo principal pero en una muestra
# de 6 situaciones cometió 3 errores que una regla simple detecta: «Ya tengo tu DNI» sin que el cliente lo hubiera escrito, un
# precio que nadie pidió y ductería ofrecida para una secadora. Este módulo hace de portero:
#
#   · `gabi_mix_haiku_modo` = apagado (por defecto) | observacion | activo
#   · observacion: responde el modelo principal (como siempre) y, en segundo plano, Haiku genera su versión y la revisión la juzga;
#     se guarda el evento interno `mix_haiku` (aprobada o no y por qué) para medir cuántas habría aprobado. No cambia nada al cliente.
#   · activo: Haiku responde primero; si la revisión lo aprueba, esa es la respuesta; si no, se regenera con el modelo principal
#     (el cliente solo nota ~1-2 s más). Cualquier fallo de Haiku también cae al principal.
#
# La revisión (`revisar`) es PURA y no usa IA: un falso rechazo solo cuesta una llamada al modelo principal; un falso aprobado sería
# un mensaje malo al cliente, por eso las reglas son estrictas.

import asyncio
import logging
import re
import time

from agent import calificacion_guiada as cg
from agent import triaje_atc
from agent.memory import EVENTO_MIX_HAIKU

logger = logging.getLogger("agentkit")

CLAVE_MODO = "gabi_mix_haiku_modo"
MODO_APAGADO, MODO_OBSERVACION, MODO_ACTIVO = "apagado", "observacion", "activo"
MODOS = (MODO_APAGADO, MODO_OBSERVACION, MODO_ACTIVO)
MODELO_BARATO = "claude-haiku-5-5"
RAZONAMIENTO_BARATO = {"type": "disabled"}   # Haiku 5.5 acepta «disabled» (Sonnet 5.5 no)
LARGO_MAXIMO = 450                            # caracteres; la mediana real es ~210 y la auditoría dice que lo largo rinde menos
MENSAJES_RECIENTES_DEL_CLIENTE = 4            # cuántos mensajes del cliente se miran para decir «el cliente ya dio su DNI»

_tareas: set[asyncio.Task] = set()

_RE_AFIRMA_DATO = re.compile(
    r"\b(?:ya\s+(?:tengo|recib\w+|cuento\s+con)|recib\w+|gracias\s+por\s+(?:tu|el)|con\s+tu)\b[^.\n!?]{0,40}\b(?:dni|documento|numero\s+de\s+cliente|suministro)\b"
)
_RE_PRECIO = re.compile(r"\bs\s*/\s*\d|\b\d[\d.,]*\s*soles\b", re.IGNORECASE)
_RE_CAPACIDAD = re.compile(r"(\d{1,2}(?:[.,]\d)?)\s?(?:kg|kilos?|l/min|litros)\b", re.IGNORECASE)
_RE_NUMERO_DNI = re.compile(r"(?<!\d)\d{8}(?!\d)")
_MULETILLA = "te hago una consulta rapida"


def _plano(texto: str | None) -> str:
    return re.sub(r"\s+", " ", cg._sin_tildes(texto)).strip()


def revisar(
    texto: str | None, *, mensajes_cliente: list[str], pidio_precio: bool, tipo_producto: str, contexto: str = "", stop_reason: str | None = "end_turn",
) -> list[str]:
    """Motivos por los que la respuesta NO debe enviarse tal cual (lista vacía = aprobada). PURA, sin IA.
    `mensajes_cliente`: lo que escribió el cliente en esta conversación (el más reciente al final). `contexto`: el texto que vio el
    modelo (catálogo, reglas), para comprobar que las capacidades que menciona existen ahí."""
    motivos: list[str] = []
    crudo = (texto or "").strip()
    if not crudo:
        return ["vacia"]
    if stop_reason not in (None, "end_turn"):
        motivos.append(f"corte_{stop_reason}")
    plano = _plano(crudo)
    recientes = " ".join(mensajes_cliente[-MENSAJES_RECIENTES_DEL_CLIENTE:])

    if _RE_AFIRMA_DATO.search(plano) and not _RE_NUMERO_DNI.search(re.sub(r"[\s.-]", "", recientes) if recientes else ""):
        # «Ya tengo tu DNI» sin un número de 8 dígitos en lo que el cliente escribió: promete algo que no pasó.
        motivos.append("afirma_dato_que_no_llego")
    if _RE_PRECIO.search(crudo) and not pidio_precio:
        motivos.append("precio_que_nadie_pidio")
    if re.search(r"\bducteria\b", plano) and tipo_producto not in (cg.PRODUCTO_TERMA, cg.PRODUCTO_OTRO):
        motivos.append("ducteria_sin_terma")
    if len(crudo) > LARGO_MAXIMO:
        motivos.append("muy_larga")
    if _MULETILLA in plano:
        motivos.append("anuncia_pregunta")          # esa frase la pone el sistema junto con la pregunta
    if contexto:
        base = contexto.replace(",", ".")
        for numero in {m.group(1).replace(",", ".") for m in _RE_CAPACIDAD.finditer(crudo)}:
            if not re.search(rf"(?<![\d.]){re.escape(numero)}(?!\d)", base):
                motivos.append(f"capacidad_sin_respaldo_{numero}")
    return motivos


_RE_PRECIO_O_CUOTAS = re.compile(r"\b(?:cuotas?|plazos?|tea|tcea|interes(?:es)?|cuanto (?:cuesta|sale|pago|seria)|precio\w*|costo\w*)\b")


def turno_delicado(*, mensajes_cliente: list[str], pidio_precio: bool = False, contexto: str = "", **_) -> list[str]:
    """Motivos por los que este turno NO se le deja a Haiku y responde siempre el modelo principal (lista vacía = Haiku puede intentarlo).
    Son los turnos donde un error cuesta más: la etapa final de la calificación (recomendación del producto y datos del titular), cuando el
    cliente ya pidió precio o cuotas, y los temas de atención al cliente o seguridad (reclamos, recibo, pagos, deuda, cambio de titular,
    olor o fuga de gas). Haiku queda para lo simple: pedir nombre o DNI, cortesías y respuestas cortas. PURA, sin IA."""
    motivos: list[str] = []
    if "ETAPA FINAL" in (contexto or ""):
        motivos.append("etapa_final")
    if pidio_precio:
        motivos.append("pidio_precio")
    recientes = mensajes_cliente[-2:]
    normalizados = [triaje_atc.normalizar(m) for m in recientes]
    if triaje_atc.detectar_emergencia(recientes):
        motivos.append("emergencia_de_gas")
    if triaje_atc._coincidencias(triaje_atc.REGLAS_ATC, normalizados):
        motivos.append("atencion_al_cliente")
    if any(_RE_PRECIO_O_CUOTAS.search(n) for n in normalizados) and "pidio_precio" not in motivos:
        motivos.append("precio_o_cuotas")
    return motivos


def tipo_de_producto_del_turno(lead: dict | None, mensajes_cliente: list[str]) -> str:
    return cg.tipo_de_producto((lead or {}).get("interes"), (lead or {}).get("producto_tipo"), *mensajes_cliente[:3])


async def modo(negocio_id: str | None) -> str:
    from agent.memory import obtener_configuracion

    try:
        valor = (await obtener_configuracion(CLAVE_MODO, MODO_APAGADO, negocio_id=negocio_id) or "").strip().lower()
    except Exception:
        return MODO_APAGADO
    return valor if valor in MODOS else MODO_APAGADO


async def _llamar_haiku(system_prompt: str, mensajes: list[dict]):
    from agent import brain

    return await brain.client.messages.create(
        model=MODELO_BARATO, max_tokens=1024, thinking=RAZONAMIENTO_BARATO,
        system=[{"type": "text", "text": system_prompt, "cache_control": brain.CACHE_INSTRUCCIONES}], messages=mensajes,
    )


async def intentar(system_prompt: str, mensajes: list[dict], contexto_revision: dict):
    """Modo activo: la respuesta de Haiku y los motivos de rechazo. `(response, [])` si la revisión la aprobó; `(None, motivos)` si no
    (o si Haiku falló): quien llama regenera con el modelo principal. Nunca lanza."""
    from agent import brain

    delicado = turno_delicado(**contexto_revision)
    if delicado:
        return None, [f"turno_delicado_{m}" for m in delicado]       # ni se llama a Haiku: responde el principal
    try:
        response = await _llamar_haiku(system_prompt, mensajes)
    except Exception as e:  # noqa: BLE001 — cualquier fallo cae al principal
        logger.warning(f"mix_haiku: Haiku falló ({type(e).__name__}) — responde el modelo principal")
        return None, ["haiku_fallo"]
    motivos = revisar(brain.texto_de_respuesta(response), stop_reason=getattr(response, "stop_reason", None), **contexto_revision)
    return (response if not motivos else None), motivos


def lanzar_observacion(
    system_prompt: str, mensajes: list[dict], respuesta_real: str, modelo_real: str, lead: dict | None, contexto_revision: dict,
) -> None:
    """Modo observación: agenda en segundo plano lo que habría hecho el mix, sin esperarlo ni afectar la respuesta real."""
    if not lead or not lead.get("telefono"):
        return
    try:
        tarea = asyncio.get_running_loop().create_task(
            _observar(system_prompt, mensajes, respuesta_real, modelo_real, lead["telefono"], contexto_revision)
        )
    except RuntimeError:
        return
    _tareas.add(tarea)
    tarea.add_done_callback(_tareas.discard)


async def _observar(system_prompt, mensajes, respuesta_real, modelo_real, telefono, contexto_revision) -> None:
    from agent import brain
    from agent.memory import registrar_evento_lead

    try:
        inicio = time.monotonic()
        response = await _llamar_haiku(system_prompt, mensajes)
        texto = brain.texto_de_respuesta(response)
        motivos = revisar(texto, stop_reason=getattr(response, "stop_reason", None), **contexto_revision)
        uso = response.usage
        await registrar_evento_lead(
            telefono, tipo=EVENTO_MIX_HAIKU,
            descripcion=f"Mix Haiku (observación): {'aprobada' if not motivos else 'rechazada: ' + ', '.join(motivos)}"[:300], autor=None,
            payload={
                "aprobada": not motivos, "motivos": motivos, "delicado": turno_delicado(**contexto_revision),
                "modelo": MODELO_BARATO, "modelo_real": modelo_real,
                "respuesta_real": respuesta_real, "respuesta_haiku": texto, "latencia_ms": round((time.monotonic() - inicio) * 1000),
                "tokens_in": uso.input_tokens, "tokens_out": uso.output_tokens,
                "cache_read": getattr(uso, "cache_read_input_tokens", None), "cache_write": getattr(uso, "cache_creation_input_tokens", None),
            },
        )
    except Exception:
        logger.exception("mix_haiku: no se pudo generar o guardar la observación (la respuesta real no se ve afectada)")
