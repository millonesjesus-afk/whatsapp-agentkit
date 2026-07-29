# agent/services/servicio_canales.py — ServicioCanales (fachada)
# Generado por AgentKit

"""
Punto de integración del Dominio con la lógica de campañas — Backend
Architecture, componente `ServicioCanales` ("canales de WhatsApp,
campañas. Formaliza campanas.py y la gestión de canales de dashboard.py").

Fase 2 de Backend Architecture (segundo tramo, tras el protocolo de
confianza de IA — MAIEK_AI_PHASE_1_EXECUTION_PLAN.md v1.2, sección 4):
fachada pura sobre agent/campanas.py, sin reescribir su comportamiento.
`agent/main.py` y `agent/dashboard.py` dejan de importar campanas.py
directamente y pasan a usar esta clase.

La gestión de canales de WhatsApp en sí (`CanalWhatsApp` — listar/crear/
actualizar) sigue con acceso directo a agent/memory.py desde dashboard.py,
igual que sigue hoy la mayoría del acceso a datos de Lead — es CRUD
simple sin regla de negocio embebida (a diferencia de "líneas de venta",
que sí se extrajo por tener lógica real atrapada en el router). Extraer
esa capa de acceso a datos por completo es un cambio más amplio, fuera
del alcance proporcional de esta sub-etapa.

`agent/brain.py` (dominio de AI) sigue importando `resolver_promo`,
`resolver_familia_promo` y `obtener_codigos_promocionales_activos`
directamente desde campanas.py — no a través de esta fachada. AI
Architecture Sec.1 asigna al propio AI Orchestrator la resolución de las
seis fuentes de conocimiento; ServicioInteligencia envuelve a brain.py,
pero brain.py resuelve su propio contexto igual que ya resolvía datos de
memory.py directamente, sin pasar por un servicio de Backend.
"""

from agent import campanas


class ServicioCanales:
    """Fachada sobre agent/campanas.py — main.py y dashboard.py no llaman
    a su lógica de campañas directamente, pasan por acá."""

    async def detectar_y_asignar_campana(self, telefono: str, texto_mensaje: str, referral: dict | None) -> dict | None:
        return await campanas.detectar_y_asignar_campana(telefono, texto_mensaje, referral)

    async def sembrar_campanas_iniciales(self):
        return await campanas.sembrar_campanas_iniciales()

    async def corregir_patrones_desalineados(self):
        return await campanas.corregir_patrones_desalineados()

    async def procesar_leads_formulario(self, body: dict, proveedor) -> None:
        return await campanas.procesar_leads_formulario(body, proveedor)

    def resolver_promo(self, campana: dict) -> dict | None:
        return campanas.resolver_promo(campana)

    def generar_link_whatsapp(self, texto_saludo: str) -> str:
        return campanas.generar_link_whatsapp(texto_saludo)


# Instancia compartida por todo el proceso — mismo patrón que
# servicio_inteligencia y servicio_comercial.
servicio_canales = ServicioCanales()
