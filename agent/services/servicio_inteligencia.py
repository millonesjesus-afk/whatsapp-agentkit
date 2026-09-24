# agent/services/servicio_inteligencia.py — ServicioInteligencia (fachada)
# Generado por AgentKit

"""
Único punto de integración entre el Dominio y el AI Engine (agent/brain.py)
— Backend Architecture, componente `ServicioInteligencia`.

Además de envolver brain.py, resuelve qué acción de negocio corresponde a
cada nivel de confianza que el AI Engine emite — AI Architecture Sec.5:
"el AI Engine nunca debe retornar ni implicar una acción de negocio...
toda acción de negocio sigue siendo responsabilidad exclusiva de
ServicioInteligencia y las capas que lo consumen". El mapeo confianza→acción
es configurable (tabla Configuracion), no hardcodeado, tal como se pidió
explícitamente al definir esta lógica de negocio.

La escritura en `SugerenciaIA` (Data Architecture) sigue diferida — depende
de Data Architecture Fase 2, todavía no ejecutada.
"""

from agent import brain
from agent.memory import obtener_configuracion

# Acciones válidas — vocabulario cerrado, igual que el de confianza.
ACCION_NINGUNA = "ninguna"
ACCION_REVISION_PRIORITARIA = "revision_prioritaria"
ACCION_ESCALAR = "escalar"
ACCIONES_VALIDAS = (ACCION_NINGUNA, ACCION_REVISION_PRIORITARIA, ACCION_ESCALAR)

# Regla de negocio por defecto, definida explícitamente por el usuario al
# implementar el protocolo de confianza (AI Architecture Sec.6 la dejaba
# como brecha abierta, "a definir junto con Backend Architecture al
# implementar" — es este momento): Alta responde y no hace nada más;
# Requiere validación responde y marca revisión prioritaria, sin
# transferir la conversación; Baja escala automáticamente y la IA deja de
# decidir. Cada nivel es una clave independiente en Configuracion para
# poder cambiar el umbral/acción sin tocar código.
_ACCION_DEFAULT_POR_CONFIANZA = {
    brain.CONFIANZA_ALTA: ACCION_NINGUNA,
    brain.CONFIANZA_REQUIERE_VALIDACION: ACCION_REVISION_PRIORITARIA,
    brain.CONFIANZA_BAJA: ACCION_ESCALAR,
}
_SLUG_CONFIANZA = {
    brain.CONFIANZA_ALTA: "alta",
    brain.CONFIANZA_REQUIERE_VALIDACION: "requiere_validacion",
    brain.CONFIANZA_BAJA: "baja",
}


class ServicioInteligencia:
    """Fachada sobre agent/brain.py — ningún otro módulo de Backend importa
    brain.py directamente, todos pasan por acá."""

    async def generar_respuesta(
        self, mensaje: str, historial: list[dict], lead: dict | None = None, modo: str = "produccion",
        negocio_id: str | None = None,
    ) -> tuple[str, bool, str | None, str | None]:
        return await brain.generar_respuesta(mensaje, historial, lead, modo=modo, negocio_id=negocio_id)

    async def extraer_datos_lead(self, mensaje_cliente: str, respuesta_gabi: str, lead_actual: dict | None) -> dict:
        return await brain.extraer_datos_lead(mensaje_cliente, respuesta_gabi, lead_actual)

    def obtener_mensaje_no_soportado(self, tipo: str | None = None) -> str:
        return brain.obtener_mensaje_no_soportado(tipo)

    def obtener_mensaje_error_escalado(self) -> str:
        return brain.obtener_mensaje_error_escalado()

    def obtener_mensaje_escalado_por_confianza(self) -> str:
        return brain.obtener_mensaje_escalado_por_confianza()

    def obtener_mensaje_derivacion(self, dentro_de_horario: bool) -> str:
        return brain.obtener_mensaje_derivacion(dentro_de_horario)

    async def resolver_accion_confianza(self, confianza: str) -> str:
        """Traduce un nivel de confianza emitido por el AI Engine en la
        acción de negocio configurada para ese nivel — nunca al revés: el
        AI Engine no sabe ni decide qué acción corresponde."""
        slug = _SLUG_CONFIANZA.get(confianza)
        default = _ACCION_DEFAULT_POR_CONFIANZA.get(confianza, ACCION_ESCALAR)
        if slug is None:
            # Confianza fuera de vocabulario no debería llegar acá (brain.py
            # ya hace fail-safe a Baja), pero si pasara, fail-safe también
            # hacia la acción más conservadora: escalar a un humano.
            return ACCION_ESCALAR
        accion = await obtener_configuracion(f"confianza_accion_{slug}", default)
        return accion if accion in ACCIONES_VALIDAS else default


# Instancia compartida por todo el proceso — sin estado propio todavía (pura
# delegación), pero mantiene el mismo patrón de acceso que ya usa el resto
# del proyecto (ej. agent/rate_limit.py).
servicio_inteligencia = ServicioInteligencia()
