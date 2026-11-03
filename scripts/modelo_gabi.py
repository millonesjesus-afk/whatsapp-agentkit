"""Modelo con que responde Gabi y mix Haiku → modelo principal (agent/mix_haiku.py) — 2026-11-03.

Qué maneja (sin desplegar código; son configuraciones por negocio):
  · el modelo principal: claude-sonnet-5-5 (por defecto desde el 2026-11-03) o claude-sonnet-4-6 (el anterior, para volver atrás);
  · el mix: apagado (por defecto) | observacion (responde el principal y se mide qué habría pasado con Haiku) | activo
    (Haiku responde primero; solo se envía si una revisión sin IA lo aprueba, si no responde el principal).

Uso (la base sale de DATABASE_URL, como en los demás scripts):
    python scripts/modelo_gabi.py                                # estado actual
    python scripts/modelo_gabi.py --principal claude-sonnet-4-6  # volver al modelo anterior
    python scripts/modelo_gabi.py --mix observacion              # empezar a medir (cuesta ~US$ 0,0005 por respuesta)
    python scripts/modelo_gabi.py --mix activo                   # Haiku primero con revisión
    python scripts/modelo_gabi.py --mix apagado
    python scripts/modelo_gabi.py --resumen [--desde 2026-11-03] # qué porcentaje habría aprobado la revisión y cuánto se ahorra
    añadir --negocio-id <id> si hay más de un negocio activo.
"""
import argparse
import asyncio
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select

from agent import brain, mix_haiku
from agent import memory as mem
from agent.memory import esperar_base_de_datos, listar_negocios
from scripts.configurar_plantilla_retomar import resolver_negocio_id
from scripts.sombra_modelo import costo_estimado

# Costo medido por respuesta del modelo principal anterior (logs «Respuesta generada», 27-oct a 2-nov): referencia para el ahorro.
COSTO_PRINCIPAL_REFERENCIA_USD = 0.0114


def resumir_mix(payloads: list[dict], costo_principal: float = COSTO_PRINCIPAL_REFERENCIA_USD) -> dict:
    """Agregados de los eventos `mix_haiku`: porcentaje aprobado, motivos de rechazo y el costo/ahorro estimado del mix activo
    (Haiku siempre + el principal solo en lo rechazado)."""
    n = len(payloads)
    if not n:
        return {"respuestas": 0}
    aprobadas = sum(1 for p in payloads if p.get("aprobada"))
    motivos = Counter("capacidad_sin_respaldo" if m.startswith("capacidad_sin_respaldo_") else m for p in payloads for m in (p.get("motivos") or []))
    costos = [c for c in (costo_estimado(p.get("modelo", mix_haiku.MODELO_BARATO), p) for p in payloads) if c is not None]
    haiku = sum(costos) / len(costos) if costos else 0.0
    tasa = aprobadas / n
    mix = haiku + (1 - tasa) * costo_principal
    return {
        "respuestas": n, "aprobadas": aprobadas, "aprobadas_pct": round(100 * tasa, 1),
        "motivos_de_rechazo": dict(motivos.most_common()),
        "costo_haiku_promedio_usd": round(haiku, 5), "costo_principal_referencia_usd": costo_principal,
        "costo_mix_estimado_usd": round(mix, 5), "ahorro_estimado_pct": round(100 * (1 - mix / costo_principal), 1) if costo_principal else None,
    }


async def cargar(negocio_id: str, desde: datetime | None) -> list[dict]:
    async with mem.async_session() as session:
        q = select(mem.EventoLead.payload).where(
            mem.EventoLead.negocio_id == negocio_id, mem.EventoLead.tipo == mem.EVENTO_MIX_HAIKU,
        ).order_by(mem.EventoLead.creado)
        if desde is not None:
            q = q.where(mem.EventoLead.creado >= desde)
        return [p or {} for (p,) in (await session.execute(q)).all()]


async def main(argv=None) -> dict:
    p = argparse.ArgumentParser(description="Modelo de Gabi y mix Haiku → principal.")
    p.add_argument("--negocio-id", default=None)
    p.add_argument("--principal", metavar="MODELO", default=None, help=" / ".join(brain.MODELOS_PRINCIPALES_VALIDOS))
    p.add_argument("--mix", choices=mix_haiku.MODOS, default=None)
    p.add_argument("--resumen", action="store_true")
    p.add_argument("--desde", default=None, help="Fecha ISO desde la que resumir (UTC).")
    args = p.parse_args(argv)
    await esperar_base_de_datos()
    negocio_id = resolver_negocio_id(args.negocio_id, await listar_negocios())
    if args.principal is not None:
        if args.principal not in brain.MODELOS_PRINCIPALES_VALIDOS:
            raise SystemExit(f"Modelo no válido: {args.principal}. Usa uno de: {', '.join(brain.MODELOS_PRINCIPALES_VALIDOS)}")
        await mem.guardar_configuracion(brain.CLAVE_MODELO_PRINCIPAL, args.principal, negocio_id=negocio_id)
    if args.mix is not None:
        await mem.guardar_configuracion(mix_haiku.CLAVE_MODO, args.mix, negocio_id=negocio_id)
    principal = await brain.modelo_principal(negocio_id)
    modo = await mix_haiku.modo(negocio_id)
    print(f"Modelo principal: {principal}")
    print(f"Mix Haiku: {modo}")
    resumen = None
    if args.resumen:
        desde = datetime.fromisoformat(args.desde.replace("Z", "+00:00")).replace(tzinfo=None) if args.desde else None
        resumen = resumir_mix(await cargar(negocio_id, desde))
        print("Resumen del mix: " + ", ".join(f"{k}={v}" for k, v in resumen.items()))
    return {"principal": principal, "mix": modo, "resumen": resumen}


if __name__ == "__main__":
    asyncio.run(main())
