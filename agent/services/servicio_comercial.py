# agent/services/servicio_comercial.py — ServicioComercial (fachada)
# Generado por AgentKit

"""
Punto de integración del Dominio con la lógica de asignación automática de
leads a asesores — Backend Architecture, componente `ServicioComercial`
("leads, líneas de venta, asignación").

Fase 1 del Implementation Roadmap: por ahora es una fachada pura sobre
agent/asignacion.py, sin reescribir su comportamiento — el resto de
Backend deja de importar asignacion.py directamente y pasa a usar esta
clase. La lógica de "líneas de venta" (hoy en el handler de ruta
`registrar_venta` de agent/dashboard.py) queda fuera de este cambio: está
entremezclada con parsing de formulario y respuestas HTTP, y separarla
requiere su propia sub-etapa (MAIEK_AI_PHASE_1_EXECUTION_PLAN.md,
sección 3).
"""

from agent import asignacion


class ServicioComercial:
    """Fachada sobre agent/asignacion.py — ningún otro módulo de Backend
    llama a su lógica de asignación directamente, todos pasan por acá.
    Las constantes de configuración (UMBRAL_SENIOR_DEFAULT,
    UMBRAL_INTERMEDIO_DEFAULT) siguen importándose directo de
    asignacion.py — no son comportamiento a delegar, son valores."""

    async def elegir_asesor_automatico(self, interes: str) -> str | None:
        return await asignacion.elegir_asesor_automatico(interes)

    async def asignar_lead_pendiente_a_asesor(self, username: str, nivel_asesor: str | None) -> str | None:
        return await asignacion.asignar_lead_pendiente_a_asesor(username, nivel_asesor)


# Instancia compartida por todo el proceso — mismo patrón que
# servicio_inteligencia.
servicio_comercial = ServicioComercial()
