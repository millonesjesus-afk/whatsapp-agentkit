"""Repasa con la revisión del mix (agent/mix_haiku.py::revisar) las respuestas YA guardadas de la sombra, sin llamar a ninguna IA — 2026-11-03.

Sirve para calibrar la revisión antes de activar el mix: de las respuestas que Haiku 5.5 escribió en la sombra (y las de Sonnet 5.5 y las
reales de Sonnet 4.6 como referencia) cuántas aprobaría la revisión y por qué rechaza el resto. Si rechaza muchas de las reales, es demasiado
estricta (falsos rechazos); si aprueba una respuesta mala de Haiku, hay que afinarla. Solo lectura, costo cero.

Para cada respuesta se reconstruye lo que el cliente había escrito hasta ese momento (mensajes de su conversación anteriores al evento).
No se revisa la comprobación de capacidades (kg / litros) porque el catálogo que vio el modelo no se guarda. Imprime solo texto de Gabi, nunca
mensajes ni datos del cliente.

Uso (la base sale de DATABASE_URL):
    python scripts/mix_haiku_repasar.py                 # resumen por modelo
    python scripts/mix_haiku_repasar.py --ejemplos 6    # además, hasta 6 respuestas de Haiku rechazadas (texto de Gabi)
    python scripts/mix_haiku_repasar.py --desde 2026-10-27
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

from agent import calificacion_guiada as cg
from agent import memory as mem
from agent import mix_haiku
from agent.memory import esperar_base_de_datos, listar_negocios
from scripts.configurar_plantilla_retomar import resolver_negocio_id


def evaluar(texto: str | None, mensajes_cliente: list[str], stop_reason: str | None = "end_turn") -> list[str]:
    """Motivos de rechazo de una respuesta guardada, dado lo que el cliente había escrito (el último al final). PURA."""
    ultimo = mensajes_cliente[-1] if mensajes_cliente else ""
    return mix_haiku.revisar(
        texto, mensajes_cliente=mensajes_cliente, pidio_precio=cg.pidio_precio(ultimo, *mensajes_cliente[:-1]),
        tipo_producto=mix_haiku.tipo_de_producto_del_turno(None, mensajes_cliente), contexto="", stop_reason=stop_reason,
    )


def resumir(resultados: list[list[str]]) -> dict:
    n = len(resultados)
    if not n:
        return {"respuestas": 0}
    aprobadas = sum(1 for m in resultados if not m)
    motivos = Counter(m for ms in resultados for m in ms)
    return {"respuestas": n, "aprobadas": aprobadas, "aprobadas_pct": round(100 * aprobadas / n, 1), "motivos": dict(motivos.most_common())}


async def cargar(negocio_id: str, desde: datetime | None) -> list[dict]:
    """Los eventos de sombra con lo que el cliente había escrito antes de cada uno (sin teléfonos ni nombres)."""
    async with mem.async_session() as session:
        q = select(mem.EventoLead.payload, mem.EventoLead.creado, mem.EventoLead.conversation_id).where(
            mem.EventoLead.negocio_id == negocio_id, mem.EventoLead.tipo == mem.EVENTO_SOMBRA_MODELO,
        ).order_by(mem.EventoLead.creado)
        if desde is not None:
            q = q.where(mem.EventoLead.creado >= desde)
        eventos = (await session.execute(q)).all()
        salida = []
        previos: dict[str, list[tuple[datetime, str]]] = {}
        for payload, creado, conversation_id in eventos:
            if conversation_id not in previos:
                filas = (await session.execute(
                    select(mem.Mensaje.timestamp, mem.Mensaje.content).where(
                        mem.Mensaje.conversation_id == conversation_id, mem.Mensaje.role == "user",
                    ).order_by(mem.Mensaje.timestamp)
                )).all()
                previos[conversation_id] = [(t, c or "") for t, c in filas]
            cliente = [c for t, c in previos[conversation_id] if t <= creado]
            salida.append({"payload": payload or {}, "mensajes_cliente": cliente})
        return salida


async def main(argv=None) -> dict:
    p = argparse.ArgumentParser(description="Repasa con la revisión del mix las respuestas ya guardadas de la sombra.")
    p.add_argument("--negocio-id", default=None)
    p.add_argument("--desde", default=None, help="Fecha ISO desde la que repasar (UTC).")
    p.add_argument("--ejemplos", type=int, default=0, help="Imprime hasta N respuestas de Haiku rechazadas (solo texto de Gabi).")
    args = p.parse_args(argv)
    await esperar_base_de_datos()
    negocio_id = resolver_negocio_id(args.negocio_id, await listar_negocios())
    desde = datetime.fromisoformat(args.desde.replace("Z", "+00:00")).replace(tzinfo=None) if args.desde else None
    filas = await cargar(negocio_id, desde)
    por_modelo: dict[str, list[list[str]]] = {}
    rechazadas_haiku: list[tuple[str, list[str]]] = []
    reales: list[list[str]] = []
    vistos_reales: set[str] = set()
    for fila in filas:
        pl, cliente = fila["payload"], fila["mensajes_cliente"]
        modelo = pl.get("modelo") or "?"
        motivos = evaluar(pl.get("respuesta_sombra"), cliente, pl.get("stop_reason"))
        por_modelo.setdefault(modelo, []).append(motivos)
        if motivos and modelo == mix_haiku.MODELO_BARATO:
            rechazadas_haiku.append((pl.get("respuesta_sombra") or "", motivos))
        real = pl.get("respuesta_real") or ""
        if real and (real, len(cliente)) not in vistos_reales:        # la real aparece una vez por cada modelo en sombra: contarla una sola
            vistos_reales.add((real, len(cliente)))
            reales.append(evaluar(real, cliente))
    resumen = {f"sombra {m}": resumir(r) for m, r in sorted(por_modelo.items())}
    resumen["real (Sonnet 4.6)"] = resumir(reales)
    for nombre, r in resumen.items():
        print(f"{nombre}: " + ", ".join(f"{k}={v}" for k, v in r.items()))
    for texto, motivos in rechazadas_haiku[: args.ejemplos]:
        print(f"\n--- HAIKU RECHAZADA ({', '.join(motivos)}) ---\n{texto}")
    return resumen


if __name__ == "__main__":
    asyncio.run(main())
