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
from agent.memory import guardar_venta, ids_de_productos_existentes

MODALIDADES_PAGO = ["financiado", "contado"]
CUOTAS_DISPONIBLES = ["12", "24", "36"]
MEDIO_PAGO_FINANCIADO = "Recibo de gas"
MEDIOS_PAGO_CONTADO = ["QR", "Link de pago", "Abono a cuenta corriente", "Otro"]


def _id_producto(valor) -> int | None:
    """Normaliza el `producto_id` que llega del formulario: entero válido, o
    None si no vino (venta manual) o si vino basura. No decide si el producto
    existe — eso lo hace validar_productos_de_venta contra la base."""
    try:
        numero = int(str(valor).strip())
    except (TypeError, ValueError):
        return None
    return numero if numero > 0 else None


class ServicioComercial:
    """Fachada sobre agent/asignacion.py y sobre la regla de negocio de
    líneas de venta — ningún otro módulo de Backend implementa esta lógica
    por su cuenta, todos pasan por acá."""

    async def elegir_asesor_automatico(self, interes: str) -> str | None:
        return await asignacion.elegir_asesor_automatico(interes)

    async def asignar_lead_pendiente_a_asesor(self, username: str, nivel_asesor: str | None) -> str | None:
        return await asignacion.asignar_lead_pendiente_a_asesor(username, nivel_asesor)

    def validar_venta(
        self, lineas_venta_json: str, modalidad_pago: str, cuotas: str, medio_pago: str,
    ) -> dict:
        """Valida y normaliza los datos de entrada de un cierre de venta SIN
        escribir nada. Retorna la venta ya normalizada
        (`lineas`/`modalidad_pago`/`cuotas`/`medio_pago`) o lanza `ValueError`.

        Está separada de la persistencia a propósito: quien llama tiene que
        poder rechazar una entrada inválida ANTES de tocar el estado del lead
        —en particular antes de consumir la versión de concurrencia optimista—,
        para que un 400 de validación nunca provoque un conflicto de edición
        falso contra otra sesión que tenía el mismo lead abierto."""
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
                # `producto_id`: el id real del producto del catálogo que se
                # eligió al armar el carrito. Opcional a propósito — el cierre
                # de venta sigue teniendo el modo manual ("¿No está en la
                # lista? Agregar manualmente"), donde no hay producto de
                # catálogo detrás y la línea se guarda con producto_id = None.
                # Acá solo se normaliza la FORMA (entero o nada); que el id
                # exista de verdad se comprueba en validar_productos_de_venta,
                # que necesita consultar la base.
                "producto_id": _id_producto(l.get("producto_id")),
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

        return {
            "lineas": lineas,
            "modalidad_pago": modalidad_pago,
            "cuotas": cuotas,
            "medio_pago": medio_pago,
        }

    async def validar_productos_de_venta(self, venta: dict) -> None:
        """Comprueba contra el catálogo real que cada `producto_id` de la venta
        exista. Lanza `ValueError` si alguno no existe.

        Está separada de `validar_venta` porque necesita consultar la base y
        aquella es deliberadamente sincronizada y sin efectos. Quien llama debe
        ejecutarla en el mismo tramo "antes de tocar la versión": un id
        inválido es un 400, y un 400 no debe consumir la versión de
        concurrencia optimista del lead (ver el comentario de validar_venta).

        Las líneas sin `producto_id` (venta manual) se ignoran acá: no tienen
        nada que validar contra el catálogo."""
        ids = {l["producto_id"] for l in venta["lineas"] if l.get("producto_id")}
        if not ids:
            return
        existentes = await ids_de_productos_existentes(ids)
        faltantes = sorted(ids - existentes)
        if faltantes:
            raise ValueError(
                f"El producto seleccionado ya no existe en el catálogo (id {faltantes[0]})"
            )

    async def persistir_venta(self, telefono: str, venta: dict) -> None:
        """Escribe una venta YA validada por `validar_venta`. No valida nada:
        recibir datos crudos acá es un error de programación, no una entrada
        de usuario.

        Líneas y campos del lead van en UNA sola transacción (guardar_venta):
        antes eran dos escrituras con dos commits, y una falla en el medio
        dejaba estado parcial (líneas nuevas con forma de pago vieja, o lead
        "vendido" sin líneas)."""
        lineas = venta["lineas"]

        campos = {
            "modalidad_pago": venta["modalidad_pago"],
            "cuotas": venta["cuotas"],
            "medio_pago": venta["medio_pago"],
        }
        # Si se registró al menos un producto, el resultado pasa a "vendido"
        # automáticamente. La simetría —vaciar el carrito le quita el
        # "vendido"— la resuelve guardar_venta con
        # revertir_resultado_al_vaciar, porque para decidirlo hay que leer el
        # estado anterior del lead DENTRO de la misma transacción.
        if lineas:
            campos["resultado"] = "vendido"

        # `cuotas` va como campo explícito: al pasar de financiado a contado,
        # validar_venta() lo normaliza a "" ("las cuotas ya no aplican"), y sin
        # esto el filtro de valores vacíos de actualizar_lead lo descartaría —
        # dejando en la fila las cuotas viejas de una venta financiada que ya
        # no existe. Es exactamente la misma decisión que fecha_agendada cuando
        # el resultado deja de ser "agendado" (ver dashboard.py, actualizar_resultado):
        # el vacío viene de una regla de negocio, no de "no sé".
        await guardar_venta(
            telefono, lineas, campos,
            campos_explicitos=("cuotas",),
            revertir_resultado_al_vaciar=True,
        )

    async def registrar_venta(
        self, telefono: str, lineas_venta_json: str, modalidad_pago: str, cuotas: str, medio_pago: str,
    ) -> None:
        """Valida y persiste las líneas de venta de un lead, en un solo paso.
        Conveniencia para quien no necesita separar las dos fases; el handler
        de ruta sí las separa (ver validar_venta)."""
        venta = self.validar_venta(lineas_venta_json, modalidad_pago, cuotas, medio_pago)
        await self.validar_productos_de_venta(venta)
        await self.persistir_venta(telefono, venta)


# Instancia compartida por todo el proceso — mismo patrón que
# servicio_inteligencia.
servicio_comercial = ServicioComercial()
