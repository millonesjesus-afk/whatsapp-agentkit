# agent/plantilla_retomar.py — Plantilla "retomar consulta" que un asesor manda a mano (2026-10-06, P3)
#
# Cuando la ventana de servicio de 24 h de WhatsApp ya cerró, Meta no deja mandar texto libre: solo una
# plantilla aprobada. Esta plantilla es el puente para retomar la conversación; cuando el cliente toca un
# botón (o escribe), entra como mensaje del cliente y abre una ventana nueva de 24 h.
#
# La plantilla vive en Meta (WhatsApp Manager → Plantillas). Acá solo se guarda, por negocio y como
# configuración, el NOMBRE con el que Meta la aprobó, su idioma y el texto del cuerpo (para mostrar la
# vista previa). Sin nombre configurado no se puede enviar: la ruta responde un 409 claro.
#
# Funciones puras (variables, vista previa, validación) + lectura/escritura de configuración.

import re

from agent.memory import guardar_configuracion, obtener_configuracion

CLAVE_NOMBRE = "plantilla_retomar_nombre"
CLAVE_IDIOMA = "plantilla_retomar_idioma"
CLAVE_CUERPO = "plantilla_retomar_cuerpo"

NOMBRE_SUGERIDO = "retomar_consulta"
IDIOMA_POR_DEFECTO = "es"
CUERPO_POR_DEFECTO = (
    "Hola {{1}}, soy {{2}} de Gaso+. Vi que consultaste por {{3}} y quiero ayudarte a continuar. ¿Seguimos por aquí?"
)
# Botones de respuesta rápida de la plantilla propuesta. Son parte de la plantilla aprobada en Meta, no
# llevan parámetros: no se mandan en el envío.
BOTONES = ("Sí, continuemos", "Prefiero que me llamen")
# Qué es cada variable, en orden ({{1}}, {{2}}, {{3}}).
VARIABLES = ("nombre del cliente", "nombre del asesor", "interés del cliente")
MAXIMO_VARIABLES = len(VARIABLES)

_NOMBRE_VALIDO = re.compile(r"[a-z0-9_]{1,512}")
_IDIOMA_VALIDO = re.compile(r"[a-z]{2,3}(_[A-Z]{2})?")
_PLACEHOLDER = re.compile(r"\{\{(\d+)\}\}")

_FALLBACK_CLIENTE = "cliente"
_FALLBACK_INTERES = "nuestros servicios"
_LARGO_MAXIMO_VARIABLE = 60


def _una_linea(texto: str | None) -> str:
    """Meta rechaza variables con saltos de línea, tabulaciones o 4+ espacios seguidos."""
    return " ".join((texto or "").split())


def _recortar(texto: str, largo: int = _LARGO_MAXIMO_VARIABLE) -> str:
    return texto if len(texto) <= largo else texto[: largo - 1].rstrip() + "…"


def variables_de_plantilla(nombre_cliente: str | None, nombre_asesor: str | None, interes: str | None) -> list[str]:
    """Valores de {{1}} (cliente), {{2}} (asesor) y {{3}} (interés). Nunca vacíos —Meta exige texto— ni con
    saltos de línea. El cliente va por su primer nombre; si no tiene nombre real (vacío o solo dígitos, como
    un teléfono) se usa un genérico."""
    primero = _una_linea(nombre_cliente).split(" ")[0] if _una_linea(nombre_cliente) else ""
    if not primero or primero.replace("+", "").isdigit():
        primero = _FALLBACK_CLIENTE
    else:
        primero = primero[:1].upper() + primero[1:].lower()
    asesor = _recortar(_una_linea(nombre_asesor)) or "tu asesor"
    interes_limpio = _recortar(_una_linea(interes)) or _FALLBACK_INTERES
    return [_recortar(primero), asesor, interes_limpio]


def cantidad_de_variables(cuerpo: str) -> int:
    """Cuántos {{n}} distintos tiene el cuerpo (los parámetros que hay que mandar a Meta)."""
    return len({int(n) for n in _PLACEHOLDER.findall(cuerpo)})


def parametros_para_envio(cuerpo: str, variables: list[str]) -> list[str]:
    """Los parámetros del cuerpo para Meta: tantos como {{n}} tenga el cuerpo aprobado."""
    return variables[: cantidad_de_variables(cuerpo)]


def renderizar(cuerpo: str, variables: list[str]) -> str:
    """El texto tal como lo recibe el cliente: cada {{n}} sustituido por su variable."""
    def _sustituir(m: re.Match) -> str:
        i = int(m.group(1)) - 1
        return variables[i] if 0 <= i < len(variables) else m.group(0)
    return _PLACEHOLDER.sub(_sustituir, cuerpo)


def validar_cuerpo(cuerpo: str) -> None:
    """El cuerpo debe usar {{1}}…{{n}} correlativos (n ≤ 3, sin saltarse ninguno): son los parámetros que
    se mandan, y Meta rechaza el envío si no coinciden con la plantilla aprobada."""
    numeros = sorted({int(n) for n in _PLACEHOLDER.findall(cuerpo)})
    if numeros != list(range(1, len(numeros) + 1)) or len(numeros) > MAXIMO_VARIABLES:
        raise ValueError(
            f"El cuerpo solo puede usar {{{{1}}}} a {{{{{MAXIMO_VARIABLES}}}}} sin saltarse ninguno "
            "(1 = cliente, 2 = asesor, 3 = interés)."
        )


async def obtener_plantilla(negocio_id: str | None) -> dict:
    """Plantilla configurada del negocio. `disponible` es verdadero solo si hay un nombre válido: sin él no
    se puede enviar nada. El cuerpo es el configurado o, por defecto, el de la plantilla propuesta."""
    nombre = (await obtener_configuracion(CLAVE_NOMBRE, "", negocio_id=negocio_id) or "").strip()
    idioma = (await obtener_configuracion(CLAVE_IDIOMA, IDIOMA_POR_DEFECTO, negocio_id=negocio_id) or "").strip() or IDIOMA_POR_DEFECTO
    cuerpo = (await obtener_configuracion(CLAVE_CUERPO, "", negocio_id=negocio_id) or "").strip() or CUERPO_POR_DEFECTO
    disponible = bool(_NOMBRE_VALIDO.fullmatch(nombre)) and bool(_IDIOMA_VALIDO.fullmatch(idioma))
    return {
        "disponible": disponible,
        "nombre": nombre if disponible else None,
        "idioma": idioma,
        "cuerpo": cuerpo,
        "botones": list(BOTONES),
        "variables": list(VARIABLES),
    }


async def configurar_plantilla(
    negocio_id: str, nombre: str, idioma: str = IDIOMA_POR_DEFECTO, cuerpo: str | None = None,
) -> dict:
    """Guarda la plantilla aprobada en Meta. Todo o nada: valida antes de escribir. `nombre` vacío la
    desactiva (el panel vuelve a mostrar "todavía no hay una plantilla aprobada configurada")."""
    nombre = (nombre or "").strip()
    idioma = (idioma or IDIOMA_POR_DEFECTO).strip()
    if nombre and not _NOMBRE_VALIDO.fullmatch(nombre):
        raise ValueError("El nombre de la plantilla solo puede tener minúsculas, números y guion bajo (como lo muestra Meta).")
    if not _IDIOMA_VALIDO.fullmatch(idioma):
        raise ValueError("El idioma debe ser un código de Meta como es, es_PE o es_MX.")
    if cuerpo is not None and cuerpo.strip():
        validar_cuerpo(cuerpo.strip())
    await guardar_configuracion(CLAVE_NOMBRE, nombre, negocio_id=negocio_id)
    await guardar_configuracion(CLAVE_IDIOMA, idioma, negocio_id=negocio_id)
    if cuerpo is not None:
        await guardar_configuracion(CLAVE_CUERPO, cuerpo.strip(), negocio_id=negocio_id)
    return await obtener_plantilla(negocio_id)
