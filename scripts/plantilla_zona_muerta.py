"""Plantilla automática para la "zona muerta" — 2026-10-07 (Q2). APAGADA por defecto.

El negocio cierra el sábado a las 19:00 y abre el lunes a las 8:00 (61 h): un cliente derivado que escribe
entre el sábado 19:00 y el domingo 8:00 ve cerrarse su ventana de 24 h de WhatsApp antes de que alguien pueda
atenderlo, y después solo se le puede escribir con una plantilla aprobada. Este Cron manda UNA plantilla
(la misma "retomar consulta" que los asesores mandan a mano, ver agent/plantilla_retomar.py) a esos clientes
mientras todavía tienen la ventana abierta —o la cerraron hace poco—, para que al tocar un botón abran una
ventana nueva con alguien ya disponible.

Solo corre para un negocio si su clave de configuración `plantilla_auto_zona_muerta` vale "1" (ausente = apagado)
y tiene una plantilla configurada (scripts/configurar_plantilla_retomar.py). Sin eso solo imprime que está
apagado y no toca nada.

Quién recibe (ver agent/atencion_atrasada.py::candidatos_zona_muerta): clientes ESPERANDO una respuesta de una
persona (último mensaje real del cliente, con asesor / pausa manual / escalado de por medio, sin respuesta
saliente desde entonces) cuyo resultado no está cerrado y que no fueron cerrados definitivamente, con el negocio
CERRADO ahora y su próxima apertura posterior al cierre de la ventana. Ventana por vencer: menos de
`plantilla_auto_horas_antes` (6) horas; ventana ya cerrada: hace menos de `plantilla_auto_horas_despues` (12).
Más allá de eso lo retoma una persona con la plantilla manual.

Una sola por espera: tras enviarla (o dejarla en estado incierto) se anota un EventoLead `plantilla_auto_enviada`
y no se vuelve a mandar mientras exista uno posterior al inicio de la espera actual; el origen de envío
`plantilla_automatica` además no repite al mismo cliente en 12 h. Sale por la capa central (agent/envios.py),
así que respeta el interruptor del origen (`envios_modo_plantilla_automatica`), la categoría supuesta y el tope
mensual de gasto; un envío frenado por costo no se anota y se reintenta en la próxima corrida. El circuito de la
IA no aplica: no es una respuesta de Gabi.

El mensaje NO se guarda en el chat a propósito: un mensaje saliente sacaría al cliente de "esperando" en Inicio
y nadie lo habría atendido de verdad. Queda constancia en el Timeline del lead (EventoLead con el texto enviado).

Recomendado cuando se cree el Cron en Railway: cada 30 min. No está en CRONES_ESPERADOS (agent/memory.py):
súmalo ahí cuando el Cron exista.

Uso local:
    python scripts/plantilla_zona_muerta.py
"""
import asyncio
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts._cron import ejecutar_cron  # latido: ver scripts/_cron.py

from agent import atencion_atrasada, envios, plantilla_retomar
from agent.memory import (
    esperar_base_de_datos, listar_negocios, obtener_configuracion, obtener_lead, obtener_usuario, registrar_evento_lead,
)
from agent.providers import obtener_proveedor

NOMBRE_CRON = "plantilla_zona_muerta"
INTERVALO_MIN = 30


def _horas(valor: str, por_defecto: float) -> float:
    try:
        n = float(str(valor).replace(",", "."))
    except (TypeError, ValueError):
        return por_defecto
    return n if n > 0 else por_defecto


async def procesar_negocio(negocio: dict, proveedor, ahora: datetime) -> dict:
    """Corre el barrido de un negocio y devuelve los contadores. Un fallo con un lead no frena a los demás."""
    negocio_id = negocio["id"]
    cuenta = {
        "estado": "apagada", "candidatos": 0, "enviadas": 0, "ya_enviadas": 0, "bloqueadas": 0, "inciertas": 0,
        "fallidas": 0, "errores": 0,
    }
    if (await obtener_configuracion(atencion_atrasada.CLAVE_AUTO_ZONA_MUERTA, "", negocio_id=negocio_id)).strip() != "1":
        return cuenta
    plantilla = await plantilla_retomar.obtener_plantilla(negocio_id)
    if not plantilla["disponible"]:
        cuenta["estado"] = "sin_plantilla"
        return cuenta
    cuenta["estado"] = "encendida"

    horas_antes = _horas(
        await obtener_configuracion(atencion_atrasada.CLAVE_AUTO_HORAS_ANTES, "", negocio_id=negocio_id),
        atencion_atrasada.AUTO_HORAS_ANTES_POR_DEFECTO,
    )
    horas_despues = _horas(
        await obtener_configuracion(atencion_atrasada.CLAVE_AUTO_HORAS_DESPUES, "", negocio_id=negocio_id),
        atencion_atrasada.AUTO_HORAS_DESPUES_POR_DEFECTO,
    )
    candidatos = await atencion_atrasada.candidatos_zona_muerta(negocio_id, ahora, horas_antes, horas_despues)
    cuenta["candidatos"] = len(candidatos)

    for c in candidatos:
        telefono = c["telefono"]
        try:
            if not telefono.isdigit():
                cuenta["errores"] += 1   # un BSUID u otro identificador que no es un teléfono no recibe plantilla
                continue
            if await atencion_atrasada.ya_se_envio_plantilla_automatica(c["conversation_id"], c["esperando_desde"]):
                cuenta["ya_enviadas"] += 1
                continue
            lead = await obtener_lead(telefono, negocio_id=negocio_id)
            if lead is None:
                cuenta["errores"] += 1
                continue
            nombre_asesor = None
            if lead.get("asesor_asignado"):
                usuario = await obtener_usuario(lead["asesor_asignado"], negocio_id=negocio_id)
                nombre_asesor = (usuario or {}).get("nombre")   # sin nombre real, la plantilla dice "tu asesor"
            variables = plantilla_retomar.variables_de_plantilla(lead.get("nombre"), nombre_asesor, lead.get("interes"))
            parametros = plantilla_retomar.parametros_para_envio(plantilla["cuerpo"], variables)
            texto = plantilla_retomar.renderizar(plantilla["cuerpo"], variables)

            canal = await proveedor.resolver_canal(lead.get("numero_whatsapp_id"), negocio_id=negocio_id)
            if not canal:
                raise RuntimeError("no se pudo resolver el canal de WhatsApp del lead")
            resultado = await envios.enviar_plantilla(
                proveedor, telefono, plantilla["nombre"], parametros, plantilla["idioma"], origen="plantilla_automatica", canal=canal,
            )
            if resultado.bloqueado:
                cuenta["bloqueadas"] += 1   # política de costo o agrupación: no se anota, se reintenta
                continue
            if not resultado.enviado and not resultado.incierto:
                cuenta["fallidas"] += 1
                continue
            # Enviada (o incierta: pudo haber salido, nunca se reenvía a ciegas): una sola por espera.
            await registrar_evento_lead(
                telefono, atencion_atrasada.TIPO_EVENTO_PLANTILLA_AUTO,
                f"Plantilla automática enviada (zona muerta): {texto}"[:300], None,
                {
                    "plantilla": plantilla["nombre"], "idioma": plantilla["idioma"], "texto": texto,
                    "wamid": resultado.wamid, "incierto": bool(resultado.incierto),
                    "esperando_desde": c["esperando_desde"].isoformat(), "ventana_vence_en": c["ventana_vence_en"].isoformat(),
                },
            )
            cuenta["inciertas" if resultado.incierto else "enviadas"] += 1
        except Exception as e:  # noqa: BLE001 — un lead con problemas no frena a los demás; se reintenta
            cuenta["errores"] += 1
            print(f"ERROR enviando la plantilla de zona muerta a {telefono}: {type(e).__name__}: {e}", file=sys.stderr)
    return cuenta


async def main(ahora: datetime | None = None, proveedor=None) -> list[dict]:
    await esperar_base_de_datos()
    ahora = ahora or datetime.utcnow()
    proveedor = proveedor or obtener_proveedor()
    resumenes = []
    for negocio in await listar_negocios(solo_activos=True):
        cuenta = await procesar_negocio(negocio, proveedor, ahora)
        resumenes.append({**cuenta, "negocio_id": negocio["id"]})
        if cuenta["estado"] == "apagada":
            print(f"Plantilla zona muerta [{negocio['nombre']}]: apagada (plantilla_auto_zona_muerta != 1). No se envía nada.")
        elif cuenta["estado"] == "sin_plantilla":
            print(f"Plantilla zona muerta [{negocio['nombre']}]: encendida pero sin plantilla configurada. No se envía nada.")
        else:
            print(
                f"Plantilla zona muerta [{negocio['nombre']}]: {cuenta['candidatos']} candidato(s), "
                f"{cuenta['enviadas']} enviada(s), {cuenta['inciertas']} sin confirmar, {cuenta['ya_enviadas']} ya enviada(s) antes, "
                f"{cuenta['bloqueadas']} frenada(s) por la política de costo, {cuenta['fallidas']} fallo(s) de envío, "
                f"{cuenta['errores']} error(es)."
            )
    return resumenes


if __name__ == "__main__":
    try:
        asyncio.run(ejecutar_cron(NOMBRE_CRON, main, INTERVALO_MIN))
    except Exception as e:
        print(f"ERROR: la plantilla de zona muerta falló — {e}", file=sys.stderr)
        sys.exit(1)
