# agent/politica_envios.py — Fase B de la capa central de envíos (2026-10-04)
#
# Decide, ANTES de que un mensaje salga, si conviene enviarlo según lo que
# cuesta: interruptor por origen (siempre | solo_gratis | nunca) y tope mensual
# en USD. La estimación NO usa reglas fijas de Meta: se apoya en lo que Meta
# ya informó mensaje a mensaje (tabla uso_mensajes_meta) y en la configuración
# (cuota, tarifas, categoría de las plantillas, duración de la ventana de
# anuncios), porque esas reglas cambian por fecha, país y categoría.
#
# Principio (Opción A, aprobada): los envíos ESENCIALES —lo que el cliente
# espera: la respuesta de Gabi, el aviso de derivación, lo que escribe el
# asesor— no se bloquean nunca por costo. Solo se puede frenar lo no esencial,
# salvo que se active `envios_tope_bloquea_esenciales` (Opción B). Excepción a la
# excepción: un origen marcado `exento_tope` (el aviso del modo sin IA) no se frena
# NI con la Opción B.

import asyncio
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import func, select

from agent.memory import (
    AttributionEvent, Mensaje, UsoMensajeMeta, async_session, obtener_configuracion, resumen_uso_mensual, _a_numero,
)

logger = logging.getLogger("agentkit")

MODOS = ("siempre", "solo_gratis", "nunca")
TIEMPO_MAXIMO_ESTIMACION_S = 1.5
CACHE_SEGUNDOS = 60

_cache_resumen: dict[str, tuple[float, dict]] = {}


@dataclass
class Estimacion:
    categoria: str
    gratis: bool
    razon: str                 # ventana_anuncio | cuota | cobrable
    costo_usd: float | None    # 0 si es gratis; None si cobra pero no hay tarifa configurada


@dataclass
class Decision:
    bloquear: bool
    motivo: str | None
    estimacion: Estimacion | None


async def _resumen_del_mes(negocio_id: str | None) -> dict | None:
    """Resumen de uso del mes en curso, con caché corta: se consulta en el camino
    de envío y la cuota/gasto no cambian de forma relevante en un minuto."""
    if not negocio_id:
        return None
    ahora = time.monotonic()
    guardado = _cache_resumen.get(negocio_id)
    if guardado and ahora - guardado[0] < CACHE_SEGUNDOS:
        return guardado[1]
    resumen = await resumen_uso_mensual(negocio_id)
    _cache_resumen[negocio_id] = (ahora, resumen)
    return resumen


def limpiar_cache() -> None:
    _cache_resumen.clear()


async def modo_del_origen(origen: str, negocio_id: str | None, politica: dict) -> str:
    """El interruptor vigente. Un origen esencial es siempre "siempre": no se
    puede dejar al cliente sin respuesta por una decisión de costo."""
    if politica.get("esencial"):
        return "siempre"
    valor = await obtener_configuracion(f"envios_modo_{origen}", politica.get("modo", "siempre"), negocio_id=negocio_id)
    return valor if valor in MODOS else politica.get("modo", "siempre")


async def _ventana_de_anuncio_abierta(negocio_id: str | None, telefono: str) -> bool:
    """¿El próximo mensaje a este cliente caería en el intervalo gratuito de un
    anuncio? Dos señales: (1) Meta ya marcó como `free_entry_point` un mensaje
    reciente a este cliente (la duración se configura: `meta_fep_horas`, 72 por
    defecto, el valor prudente mientras la documentación de Meta no coincide
    entre páginas); (2) el cliente llegó por anuncio hace menos de 24 h y nadie
    le ha respondido todavía — esa primera respuesta abre el intervalo y no se
    cobra."""
    horas = _a_numero(await obtener_configuracion("meta_fep_horas", "72", negocio_id=negocio_id), 72) or 72
    ahora = datetime.utcnow()
    async with async_session() as session:
        visto = (await session.execute(
            select(UsoMensajeMeta.wamid).where(
                UsoMensajeMeta.negocio_id == negocio_id, UsoMensajeMeta.destinatario == telefono,
                UsoMensajeMeta.pricing_type == "free_entry_point",
                func.coalesce(UsoMensajeMeta.entregado_en, UsoMensajeMeta.enviado_en) >= ahora - timedelta(hours=horas),
            ).limit(1)
        )).scalar_one_or_none()
        if visto is not None:
            return True
        clic = (await session.execute(
            select(func.max(AttributionEvent.creado)).where(
                AttributionEvent.negocio_id == negocio_id, AttributionEvent.lead_telefono == telefono,
                AttributionEvent.tipo_origen.in_(("meta_ads", "meta_ads_no_resuelto")),
                AttributionEvent.creado >= ahora - timedelta(hours=24),
            )
        )).scalar_one_or_none()
        if clic is None:
            return False
        respondido = (await session.execute(
            select(Mensaje.id).where(
                Mensaje.negocio_id == negocio_id, Mensaje.telefono == telefono, Mensaje.timestamp >= clic,
                Mensaje.role.in_(("assistant", "asesor")), Mensaje.via_app.is_(False),
            ).limit(1)
        )).scalar_one_or_none()
        return respondido is None


async def estimar_envio(origen: str, tipo: str, telefono: str, canal: dict | None, negocio_id: str | None, politica: dict) -> Estimacion:
    if tipo == "plantilla":
        categoria = await obtener_configuracion(f"envios_categoria_{origen}", politica.get("categoria_plantilla", "marketing"), negocio_id=negocio_id)
    else:
        categoria = "service"   # texto libre, imagen, documento o audio dentro de la ventana de 24 h

    if await _ventana_de_anuncio_abierta(negocio_id, telefono):
        return Estimacion(categoria, True, "ventana_anuncio", 0.0)

    if categoria == "service":
        resumen = await _resumen_del_mes(negocio_id)
        numero = (canal or {}).get("phone_number_id")
        if resumen is not None and numero is not None:
            datos = next((n for n in resumen["numeros"] if n["phone_number_id"] == numero), None)
            usados = datos["servicio_gratis_total"] if datos else 0
            if usados < resumen["cuota_gratis_servicio"] and not (datos and datos["servicio_cobrables"]):
                return Estimacion(categoria, True, "cuota", 0.0)

    tarifa = _a_numero(await obtener_configuracion(f"meta_tarifa_usd_{categoria}", "", negocio_id=negocio_id))
    return Estimacion(categoria, False, "cobrable", tarifa)


async def _autorecarga(negocio_id: str | None) -> bool:
    return (await obtener_configuracion("envios_tope_modo", "tope", negocio_id=negocio_id)) == "autorecarga"


async def _gasto_del_mes(negocio_id: str | None) -> float:
    resumen = await _resumen_del_mes(negocio_id)
    if not resumen:
        return 0.0
    return sum(n.get("costo_estimado_usd") or 0.0 for n in resumen["numeros"])


async def decidir(origen: str, tipo: str, telefono: str, canal: dict | None, politica: dict) -> Decision:
    """Nunca lanza: ante cualquier falla de estimación, lo esencial se envía y
    lo no esencial con interruptor de costo se frena (no se arriesga gasto
    sin poder medirlo)."""
    negocio_id = (canal or {}).get("negocio_id")
    esencial = bool(politica.get("esencial"))
    modo = politica.get("modo", "siempre")
    try:
        modo = await modo_del_origen(origen, negocio_id, politica)
        if modo == "nunca":
            return Decision(True, "interruptor del origen en 'nunca'", None)

        try:
            estimacion = await asyncio.wait_for(
                estimar_envio(origen, tipo, telefono, canal, negocio_id, politica), TIEMPO_MAXIMO_ESTIMACION_S,
            )
        except Exception:
            logger.exception(f"No se pudo estimar el costo del envío {origen} a {telefono}")
            estimacion = None

        if not esencial and modo == "solo_gratis":
            if estimacion is None:
                return Decision(True, "solo_gratis: no se pudo estimar el costo", None)
            if not estimacion.gratis:
                return Decision(True, "solo_gratis: este envío se cobraría", estimacion)

        # Tope mensual. Sin monto elegido el tope es USD 0 (no se paga nada no
        # esencial); el usuario fija un monto o elige "autorecarga" (sin tope: se
        # sigue pagando lo que cueste, con el saldo recargándose solo).
        # Un origen con `exento_tope` queda fuera del tope INCLUSO con la Opción B activa
        # (ver agent/envios.py::ORIGENES): es el aviso del modo sin IA, que no puede callarse.
        if not politica.get("exento_tope") and not await _autorecarga(negocio_id):
            tope = _a_numero(await obtener_configuracion("envios_tope_mensual_usd", "", negocio_id=negocio_id), 0) or 0
            bloquea_esenciales = (await obtener_configuracion("envios_tope_bloquea_esenciales", "false", negocio_id=negocio_id)).lower() == "true"
            if not esencial or bloquea_esenciales:
                if estimacion is None:
                    if not esencial:
                        return Decision(True, "tope mensual: no se pudo estimar el costo", None)
                elif not estimacion.gratis:
                    gasto = await _gasto_del_mes(negocio_id)
                    if estimacion.costo_usd is None or gasto + estimacion.costo_usd > tope:
                        return Decision(True, f"tope mensual de USD {tope:g} alcanzado (gasto estimado USD {gasto:.2f})", estimacion)
        return Decision(False, None, estimacion)
    except Exception:
        logger.exception(f"Falló la política de envío de {origen} a {telefono}")
        if esencial or modo == "siempre":
            return Decision(False, None, None)
        return Decision(True, "no se pudo evaluar la política de envío", None)
