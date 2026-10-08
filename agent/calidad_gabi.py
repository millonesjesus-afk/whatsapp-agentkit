# agent/calidad_gabi.py — Métricas de calidad de la respuesta de Gabi, en MODO SOMBRA
# (Mejoras de Gabi, Fase 1, 2026-10-07).
#
# Módulo PURO: no toca la base, la red ni la configuración. Mide cada respuesta (largo, si cierra con una
# pregunta o llamado a la acción, si traía `**`) para que agent/main.py deje UNA línea de log `gabi_calidad`
# por respuesta enviada. NO cambia lo que ve el cliente ni reintenta nada: solo observa. Con esos datos se
# decide después (Fase 2) si conviene corregir las respuestas que no cierran con una pregunta.
# Auditoría de 399 chats: los mensajes largos y sin pregunta final convierten menos.

import re

VENTANA_PREGUNTA = 120   # caracteres finales donde se busca un "?"
VENTANA_CTA = 200        # caracteres finales donde se busca un llamado verbal

# Llamados verbales a la acción ("cuéntame…", "dime…"), con o sin tilde.
_CTA_VERBAL = re.compile(
    r"\b(cu[eé]ntame|dime|escr[ií]beme|env[ií]ame|comp[aá]rteme|ind[ií]came|av[ií]same|d[eé]jame|m[aá]ndame)\b",
    re.IGNORECASE,
)

# Derivación a una persona: el prompt prohíbe preguntar ahí, así que no se exige pregunta.
_MENCIONA_PERSONA = re.compile(r"asesor|especialista|ejecutiv", re.IGNORECASE)


def tiene_pregunta(texto: str | None) -> bool:
    """¿Hay un "?" en los últimos 120 caracteres?"""
    return "?" in (texto or "").strip()[-VENTANA_PREGUNTA:]


def termina_en_pregunta_o_cta(texto: str | None) -> bool:
    """Pregunta en los últimos 120 caracteres, o llamado verbal (cuéntame, dime, escríbeme…) en los últimos 200."""
    t = (texto or "").strip()
    return tiene_pregunta(t) or bool(_CTA_VERBAL.search(t[-VENTANA_CTA:]))


def es_exento(texto: str | None, cliente_dijo_gracias: bool = False) -> bool:
    """Respuestas a las que NO se les exige pregunta final: la derivación a un asesor/especialista/ejecutivo y la
    respuesta a un agradecimiento o cierre de cortesía del cliente (`cliente_dijo_gracias`, que calcula quien
    llama con agent.memory.es_cierre_cortesia sobre el último mensaje del cliente)."""
    return bool(cliente_dijo_gracias) or bool(_MENCIONA_PERSONA.search(texto or ""))


def medir_calidad(texto_original: str | None, texto_limpio: str | None, cliente_dijo_gracias: bool = False) -> dict:
    """Métricas de una respuesta de Gabi. `texto_original` es lo que devolvió Claude (antes de limpiar) y
    `texto_limpio` lo que se envió. Sin texto ni teléfonos: solo números y banderas."""
    limpio = texto_limpio if texto_limpio is not None else (texto_original or "")
    return {
        "largo": len(limpio),
        "tiene_pregunta": tiene_pregunta(limpio),
        "cumple_cta": termina_en_pregunta_o_cta(limpio),
        "exento": es_exento(limpio, cliente_dijo_gracias),
        "tenia_doble_asterisco": "**" in (texto_original or ""),
    }
