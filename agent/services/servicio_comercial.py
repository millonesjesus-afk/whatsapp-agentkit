# agent/services/servicio_comercial.py — ServicioComercial (fachada)
# Generado por AgentKit

"""
Punto de integración del Dominio con la lógica comercial — Backend
Architecture, componente `ServicioComercial` ("leads, líneas de venta,
asignación").

Fase 1 del Implementation Roadmap: fachada pura sobre agent/asignacion.py
y sobre la lógica de líneas de venta que antes vivía inline en el handler
de ruta `registrar_venta` de agent/dashboard.py — sin reescribir su
comportamiento. El resto de Backend deja de importar asignacion.py o de
tener la regla de negocio de venta en el router, y pasa a usar esta clase.

Las validaciones de esta clase señalan error con `ValueError` (no
`HTTPException` — eso es una decisión de Presentación, no de Dominio); el
router traduce el `ValueError` a la respuesta HTTP, igual que antes.
"""

import json

from agent import asignacion
from agent.memory import guardar_lineas_venta, actualizar_lead

MODALIDADES_PAGO = ["financiado", "contado"]
CUOTAS_DISPONIBLES = ["12", "24", "36"]
MEDIO_PAGO_FINANCIADO = "Recibo de gas"
MEDIOS_PAGO_CONTADO = ["QR", "Link de pago", "Abono a cuenta corriente", "Otro"]


class ServicioComercial:
    """Fachada sobre agent/asignacion.py y sobre la regla de negocio de
    líneas de venta — ningún otro módulo de Backend implementa esta lógica
    por su cuenta, todos pasan por acá."""

    async def elegir_asesor_automatico(self, interes: str) -> str | None:
        return await asignacion.elegir_asesor_automatico(interes)

    async def asignar_lead_pendiente_a_asesor(self, username: str, nivel_asesor: str | None) -> str | None:
        return await asignacion.asignar_lead_pendiente_a_asesor(username, nivel_asesor)

    async def registrar_venta(
        self, telefono: str, lineas_venta_json: str, modalidad_pago: str, cuotas: str, medio_pago: str,
    ) -> None:
        """Valida y persiste las líneas de venta de un lead — misma lógica
        que antes vivía en el handler de ruta, trasladada tal cual."""
        if modalidad_pago and modalidad_pago not in MODALIDADES_PAGO:
            raise ValueError("Modalidad de pago inválida")
        # Cuotas solo aplica a financiado — el campo queda oculto/deshabilitado
        # en el form cuando es contado, así que si llega igual, se ignora.
        if modalidad_pago != "financiado":
            cuotas = ""
        elif cuotas and cuotas not in CUOTAS_DISPONIBLES:
            raise ValueError("Cuotas inválidas")
        if modalidad_pago == "financiado":
            medio_pago = MEDIO_PAGO_FINANCIADO
        elif medio_pago and medio_pago not in MEDIOS_PAGO_CONTADO:
            raise ValueError("Medio de pago inválido")

        try:
            lineas_crudas = json.loads(lineas_venta_json)
        except (json.JSONDecodeError, TypeError):
            lineas_crudas = []
        # El carrito del formulario manda el estado completo (lo que quedó tras
        # agregar/quitar productos) — se valida/recorta acá, nunca se confía en
        # el JSON que mandó el navegador tal cual.
        lineas = [
            {
                "producto": str(l["producto"]).strip()[:300],
                "precio": str(l.get("precio") or "").strip()[:30],
                "marca": str(l.get("marca") or "").strip()[:100],
                "proveedor": str(l.get("proveedor") or "").strip()[:150],
            }
            for l in lineas_crudas
            if isinstance(l, dict) and str(l.get("producto") or "").strip()
        ]
        # Si hay productos, la forma de pago es obligatoria (según corresponda) —
        # ya se valida en el navegador, esto es el respaldo del lado servidor.
        if lineas:
            if not modalidad_pago:
                raise ValueError("Selecciona la modalidad de pago")
            if modalidad_pago == "financiado" and not cuotas:
                raise ValueError("Selecciona las cuotas")
            if modalidad_pago == "contado" and not medio_pago:
                raise ValueError("Selecciona el medio de pago")

        await guardar_lineas_venta(telefono, lineas)

        campos = {"modalidad_pago": modalidad_pago, "cuotas": cuotas, "medio_pago": medio_pago}
        # Si se registró al menos un producto, el resultado pasa a "vendido" automáticamente
        if lineas:
            campos["resultado"] = "vendido"

        await actualizar_lead(telefono, **campos)


# Instancia compartida por todo el proceso — mismo patrón que
# servicio_inteligencia.
servicio_comercial = ServicioComercial()
