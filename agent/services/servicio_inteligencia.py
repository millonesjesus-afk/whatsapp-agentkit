# agent/services/servicio_inteligencia.py — ServicioInteligencia (fachada)
# Generado por AgentKit

"""
Único punto de integración entre el Dominio y el AI Engine (agent/brain.py)
— Backend Architecture, componente `ServicioInteligencia`.

Fase 1 del Implementation Roadmap: por ahora es una fachada pura sobre la
implementación actual de brain.py, sin reescribir su comportamiento — el
resto de Backend deja de importar brain.py directamente y pasa a usar esta
clase. El protocolo de confianza estructurado (`{respuesta, confianza,
razon}`) y la escritura en `SugerenciaIA` (Data Architecture) son el
siguiente paso de esta misma fase, no de este cambio — `SugerenciaIA`
además depende de Data Architecture Fase 2, todavía no ejecutada
(MAIEK_AI_PHASE_1_EXECUTION_PLAN.md, sección 2).
"""

from agent import brain


class ServicioInteligencia:
    """Fachada sobre agent/brain.py — ningún otro módulo de Backend importa
    brain.py directamente, todos pasan por acá."""

    async def generar_respuesta(
        self, mensaje: str, historial: list[dict], lead: dict | None = None, modo: str = "produccion",
    ) -> tuple[str, bool]:
        return await brain.generar_respuesta(mensaje, historial, lead, modo=modo)

    async def extraer_datos_lead(self, mensaje_cliente: str, respuesta_gabi: str, lead_actual: dict | None) -> dict:
        return await brain.extraer_datos_lead(mensaje_cliente, respuesta_gabi, lead_actual)

    def obtener_mensaje_no_soportado(self) -> str:
        return brain.obtener_mensaje_no_soportado()

    def obtener_mensaje_error_escalado(self) -> str:
        return brain.obtener_mensaje_error_escalado()


# Instancia compartida por todo el proceso — sin estado propio todavía (pura
# delegación), pero mantiene el mismo patrón de acceso que ya usa el resto
# del proyecto (ej. agent/rate_limit.py).
servicio_inteligencia = ServicioInteligencia()
