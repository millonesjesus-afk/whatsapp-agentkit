"""Enciende, apaga y compara la respuesta de Gabi «en sombra» con otros modelos (agent/sombra_modelo.py) — 2026-10-26.

Con la sombra encendida, cada respuesta real de Gabi se genera también con el modelo indicado (mismas instrucciones,
historial y contexto) y se guarda como evento interno `sombra_modelo`: NUNCA se envía al cliente. Cuesta poco (con
Haiku 5.5, del orden de US$ 0,001 por respuesta) pero es gasto real: dejarla encendida solo el tiempo de la prueba.

Comparar muestra solo agregados (cantidad, largo, tokens, costo estimado por modelo, cortes y rechazos) y, con
--muestra N, N pares de respuestas (la real y la de sombra; solo texto de Gabi, sin teléfonos ni mensajes del cliente)
para revisarlos a ojo.

Uso (la base sale de DATABASE_URL, como en los demás scripts):
    python scripts/sombra_modelo.py                          # estado + comparación de lo acumulado
    python scripts/sombra_modelo.py --activar claude-haiku-5-5,claude-sonnet-5-5   # uno o varios, separados por coma
    python scripts/sombra_modelo.py --apagar
    python scripts/sombra_modelo.py --muestra 20 --desde 2026-10-27
    añadir --negocio-id <id> si hay más de un negocio activo.
"""
import argparse
import asyncio
import statistics
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select

from agent import memory as mem
from agent import sombra_modelo as sm
from agent.memory import esperar_base_de_datos, listar_negocios
from scripts.configurar_plantilla_retomar import resolver_negocio_id

# US$ por millón de tokens: entrada, salida, lectura de caché, escritura de caché de 1 h (2× la entrada).
PRECIOS = {
    "claude-sonnet-4-6": (3.00, 15.00, 0.30, 6.00),
    "claude-sonnet-5-5": (2.00, 10.00, 0.20, 4.00),
    "claude-haiku-5-5": (0.10, 0.50, 0.01, 0.20),
}


def costo_estimado(modelo: str, p: dict) -> float | None:
    precio = PRECIOS.get(modelo)
    if precio is None:
        return None
    entrada, salida, lectura, escritura = precio
    return (
        (p.get("tokens_in") or 0) * entrada + (p.get("tokens_out") or 0) * salida
        + (p.get("cache_read") or 0) * lectura + (p.get("cache_write") or 0) * escritura
    ) / 1_000_000


def resumir(payloads: list[dict]) -> dict:
    """Agregados de los eventos de sombra. El costo de la respuesta real no se guarda: se estima con los tokens de sombra
    (mismo pedido) solo como referencia; el costo real está en los logs «Respuesta generada»."""
    n = len(payloads)
    if not n:
        return {"respuestas": 0}
    largo_real = [len(p.get("respuesta_real") or "") for p in payloads]
    largo_sombra = [len(p.get("respuesta_sombra") or "") for p in payloads]
    costos = [c for c in (costo_estimado(p.get("modelo", ""), p) for p in payloads) if c is not None]
    vacias = sum(1 for p in payloads if not (p.get("respuesta_sombra") or "").strip())
    return {
        "respuestas": n,
        "modelo_sombra": sorted({p.get("modelo") for p in payloads}),
        "largo_real_mediana": statistics.median(largo_real),
        "largo_sombra_mediana": statistics.median(largo_sombra),
        "sombra_vacias_o_rechazadas": vacias,
        "stop_reasons": {r: sum(1 for p in payloads if p.get("stop_reason") == r) for r in {p.get("stop_reason") for p in payloads}},
        "latencia_sombra_ms_mediana": statistics.median([p.get("latencia_ms") or 0 for p in payloads]),
        "costo_sombra_promedio_usd": round(sum(costos) / len(costos), 5) if costos else None,
    }


async def cargar(negocio_id: str, desde: datetime | None) -> list[dict]:
    async with mem.async_session() as session:
        q = select(mem.EventoLead.payload, mem.EventoLead.creado).where(
            mem.EventoLead.negocio_id == negocio_id, mem.EventoLead.tipo == sm.EVENTO_SOMBRA_MODELO,
        ).order_by(mem.EventoLead.creado)
        if desde is not None:
            q = q.where(mem.EventoLead.creado >= desde)
        return [p or {} for p, _ in (await session.execute(q)).all()]


async def main(argv=None) -> dict:
    p = argparse.ArgumentParser(description="Respuesta de Gabi en sombra con otro modelo.")
    p.add_argument("--negocio-id", default=None)
    grupo = p.add_mutually_exclusive_group()
    grupo.add_argument("--activar", metavar="MODELO", default=None)
    grupo.add_argument("--apagar", action="store_true")
    p.add_argument("--desde", default=None, help="Fecha ISO desde la que comparar (UTC).")
    p.add_argument("--muestra", type=int, default=0, help="Imprime N pares (real / sombra) para revisarlos a ojo.")
    args = p.parse_args(argv)
    await esperar_base_de_datos()
    negocio_id = resolver_negocio_id(args.negocio_id, await listar_negocios())
    if args.activar is not None:
        await mem.guardar_configuracion(sm.CLAVE_MODELO_SOMBRA, args.activar.strip(), negocio_id=negocio_id)
    elif args.apagar:
        await mem.guardar_configuracion(sm.CLAVE_MODELO_SOMBRA, "", negocio_id=negocio_id)
    modelos = await sm.modelos_configurados(negocio_id)
    print(f"Sombra: {'encendida con ' + ', '.join(modelos) if modelos else 'apagada'}")
    desde = datetime.fromisoformat(args.desde.replace("Z", "+00:00")).replace(tzinfo=None) if args.desde else None
    payloads = await cargar(negocio_id, desde)
    por_modelo: dict[str, list[dict]] = {}
    for par in payloads:
        por_modelo.setdefault(par.get("modelo") or "?", []).append(par)
    resumenes = {m: resumir(ps) for m, ps in sorted(por_modelo.items())}
    if not resumenes:
        print("Comparación: respuestas=0")
    for m, r in resumenes.items():
        print(f"Comparación {m}: " + ", ".join(f"{k}={v}" for k, v in r.items()))
    for par in payloads[-args.muestra:] if args.muestra else []:
        print(f"\n--- REAL ---\n{par.get('respuesta_real') or ''}\n--- SOMBRA {par.get('modelo')} ---\n{par.get('respuesta_sombra') or ''}")
    return {"modelos": modelos, "resumen": resumenes}


if __name__ == "__main__":
    asyncio.run(main())
