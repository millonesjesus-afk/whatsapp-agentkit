# agent/plantillas_sms.py — Plantillas de SMS propias de cada negocio (2026-10-29, parte 2 del envío de SMS con código).
#
# Cada negocio puede tener sus plantillas para el texto del SMS de un envío (Campañas → «Envío SMS»), además de las
# iniciales de Maiek (que viven en el panel, son neutrales y no se guardan). Sin IA: una plantilla es un texto con
# variables que el panel rellena con lo que el usuario eligió.
#
# Variables:  {negocio} {rubro} {producto} {precio}   ·   [[ ... ]] = trozo que solo sale si hay precio   ·   [enlace]
#
# Se guardan UNA POR CLAVE (`sms_plantilla:<id>`) en `Configuracion`: su valor admite 1000 caracteres, una lista entera
# no cabría. La opción «el remitente de nuestros SMS ya muestra el nombre del negocio» es otra clave del negocio: con
# ella activa, las plantillas iniciales salen sin {negocio} (el SMS de Cálidda sale de «CALIDDA»).
# Las reglas de `validar_plantilla` están duplicadas en el panel (lib/plantillas-sms.ts); el backend es quien decide.

import json
import re
import uuid
from datetime import datetime

from agent import memory as mem

PREFIJO_CLAVE = "sms_plantilla:"
CLAVE_REMITENTE = "sms_remitente_muestra_negocio"
ALCANCES = ("producto", "negocio")
VARIABLES = ("negocio", "rubro", "producto", "precio")
MARCA_ENLACE = "[enlace]"
MAXIMO_PLANTILLAS = 30
LARGO_MINIMO = 10
LARGO_MAXIMO = 300

_VARIABLE = re.compile(r"\{([^{}]*)\}")
_OPCIONAL = re.compile(r"\[\[(.*?)\]\]", re.DOTALL)


def validar_plantilla(alcance: str, texto: str) -> str | None:
    """Mensaje de error en español claro, o None si la plantilla sirve."""
    if alcance not in ALCANCES:
        return "Elige para qué envíos es la plantilla: producto o negocio."
    texto = texto or ""
    if len(texto.strip()) < LARGO_MINIMO:
        return f"Escribe el texto de la plantilla (al menos {LARGO_MINIMO} caracteres)."
    if len(texto) > LARGO_MAXIMO:
        return f"La plantilla admite hasta {LARGO_MAXIMO} caracteres."
    usadas = _VARIABLE.findall(texto)
    for nombre in usadas:
        if nombre not in VARIABLES:
            validas = ", ".join("{" + v + "}" for v in VARIABLES)
            return f"La variable {{{nombre}}} no existe. Usa {validas}."
    sin_variables = _VARIABLE.sub("", texto)
    if "{" in sin_variables or "}" in sin_variables:
        return "Hay una llave { o } sin cerrar."
    sin_opcionales = _OPCIONAL.sub("", texto)
    if "[[" in sin_opcionales or "]]" in sin_opcionales:
        return "Los trozos opcionales se escriben así: [[ desde {precio}]]. Falta cerrar o abrir uno."
    if texto.count(MARCA_ENLACE) != 1:
        return f"La plantilla debe llevar {MARCA_ENLACE} una sola vez, donde va el enlace de WhatsApp."
    if alcance == "producto" and "producto" not in usadas:
        return "Una plantilla de producto debe incluir {producto}."
    if alcance == "negocio" and ("producto" in usadas or "precio" in usadas):
        return "Una plantilla de negocio no puede usar {producto} ni {precio}: ese SMS no promociona un producto."
    return None


def _a_dict(id_: str, valor: str) -> dict | None:
    try:
        datos = json.loads(valor)
    except ValueError:
        return None
    if not isinstance(datos, dict) or datos.get("alcance") not in ALCANCES or not isinstance(datos.get("texto"), str):
        return None
    return {
        "id": id_, "alcance": datos["alcance"], "texto": datos["texto"],
        "creado_por": datos.get("creado_por"), "creado": datos.get("creado"), "actualizado": datos.get("actualizado"),
    }


async def listar(negocio_id: str) -> list[dict]:
    """Las plantillas del negocio, la más reciente primero. Una fila dañada se ignora (nunca rompe la pantalla)."""
    filas = await mem.listar_configuracion_por_prefijo(PREFIJO_CLAVE, negocio_id)
    plantillas = [p for clave, valor in filas.items() if (p := _a_dict(clave[len(PREFIJO_CLAVE):], valor))]
    return sorted(plantillas, key=lambda p: p.get("creado") or "", reverse=True)


async def remitente_muestra_negocio(negocio_id: str) -> bool:
    return (await mem.obtener_configuracion(CLAVE_REMITENTE, "0", negocio_id=negocio_id)) == "1"


async def estado(negocio_id: str) -> dict:
    """Lo que el panel necesita: las plantillas del negocio y si su remitente ya muestra el nombre."""
    return {"plantillas": await listar(negocio_id), "remitente_muestra_negocio": await remitente_muestra_negocio(negocio_id)}


async def guardar(negocio_id: str, autor: str | None, alcance: str, texto: str, plantilla_id: str | None = None) -> dict:
    """Crea una plantilla, o edita la `plantilla_id` si viene. ValueError con el motivo si no sirve."""
    texto = " ".join((texto or "").split())
    error = validar_plantilla(alcance, texto)
    if error:
        raise ValueError(error)
    existentes = await listar(negocio_id)
    ahora = datetime.utcnow().isoformat(timespec="seconds") + "Z"
    if plantilla_id:
        actual = next((p for p in existentes if p["id"] == plantilla_id), None)
        if actual is None:
            raise LookupError("Esa plantilla ya no existe.")
        datos = {**actual, "alcance": alcance, "texto": texto, "actualizado": ahora}
        accion = "sms_plantilla_editada"
    else:
        if len(existentes) >= MAXIMO_PLANTILLAS:
            raise ValueError(f"Ya tienes {MAXIMO_PLANTILLAS} plantillas. Elimina alguna antes de crear otra.")
        if any(p["alcance"] == alcance and p["texto"] == texto for p in existentes):
            raise ValueError("Ya tienes una plantilla igual.")
        plantilla_id = uuid.uuid4().hex[:12]
        datos = {"id": plantilla_id, "alcance": alcance, "texto": texto, "creado_por": autor, "creado": ahora, "actualizado": ahora}
        accion = "sms_plantilla_creada"
    guardado = {k: datos.get(k) for k in ("alcance", "texto", "creado_por", "creado", "actualizado")}
    await mem.guardar_configuracion(PREFIJO_CLAVE + plantilla_id, json.dumps(guardado, ensure_ascii=False), negocio_id=negocio_id)
    await mem.registrar_auditoria(
        accion, actor=autor, negocio_id=negocio_id, entidad_tipo="sms_plantilla", entidad_id=plantilla_id,
        payload={"alcance": alcance, "texto": texto},
    )
    return {"id": plantilla_id, **guardado}


async def eliminar(negocio_id: str, autor: str | None, plantilla_id: str) -> None:
    existentes = {p["id"]: p for p in await listar(negocio_id)}
    if plantilla_id not in existentes:
        raise LookupError("Esa plantilla ya no existe.")
    await mem.borrar_configuracion(PREFIJO_CLAVE + plantilla_id, negocio_id)
    await mem.registrar_auditoria(
        "sms_plantilla_eliminada", actor=autor, negocio_id=negocio_id, entidad_tipo="sms_plantilla", entidad_id=plantilla_id,
        payload={"alcance": existentes[plantilla_id]["alcance"], "texto": existentes[plantilla_id]["texto"]},
    )


async def fijar_remitente(negocio_id: str, autor: str | None, muestra_negocio: bool) -> bool:
    """Guarda si el remitente de los SMS del negocio ya muestra su nombre. Devuelve True si cambió algo."""
    antes = await remitente_muestra_negocio(negocio_id)
    if antes == bool(muestra_negocio):
        return False
    await mem.guardar_configuracion(CLAVE_REMITENTE, "1" if muestra_negocio else "0", negocio_id=negocio_id)
    await mem.registrar_auditoria(
        "sms_remitente_configurado", actor=autor, negocio_id=negocio_id, entidad_tipo="configuracion",
        payload={"antes": antes, "despues": bool(muestra_negocio)},
    )
    return True
