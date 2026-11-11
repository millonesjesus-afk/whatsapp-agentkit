"""Muestra para revisar la CALIDAD del mix Haiku: lo que escribió el cliente, lo que respondió el modelo principal y lo que habría respondido Haiku — 2026-11-11.

`modelo_gabi.py --resumen` dice cuántas respuestas de Haiku aprueba la revisión automática, pero no si son BUENAS. Este script saca una muestra de los
eventos `mix_haiku` (turnos no delicados) para leerla lado a lado. Solo lectura, sin llamar a ninguna IA, costo cero.

Privacidad: del cliente solo se imprime su ÚLTIMO mensaje, recortado, con los números largos (DNI, teléfonos, suministros) y los correos tapados.
No se imprime teléfono, conversación ni nombre del contacto.

Uso (la base sale de DATABASE_URL):
    python scripts/mix_haiku_muestra.py                       # 12 aprobadas repartidas en todo el periodo
    python scripts/mix_haiku_muestra.py --n 12 --salto 12     # las 12 siguientes
    python scripts/mix_haiku_muestra.py --solo rechazadas     # las que la revisión rechazó (con sus motivos)
    python scripts/mix_haiku_muestra.py --desde 2026-11-04
    añadir --negocio-id <id> si hay más de un negocio activo.
"""
import argparse
import asyncio
import re
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select

from agent import memory as mem
from agent.memory import esperar_base_de_datos, listar_negocios
from scripts.configurar_plantilla_retomar import resolver_negocio_id

LARGO_MENSAJE_CLIENTE = 160
MUESTRA_TOTAL = 100          # tamaño fijo de la muestra: así `--salto` recorre siempre la misma lista, sin repetir
_RE_NUMERO_LARGO = re.compile(r"\d[\d\s.-]{3,}\d")
_RE_CORREO = re.compile(r"\S+@\S+")


def enmascarar(texto: str | None, largo: int = LARGO_MENSAJE_CLIENTE) -> str:
    """Quita datos personales de un mensaje del cliente: números de 5+ dígitos (DNI, teléfono, suministro) y correos; lo recorta. PURA."""
    limpio = re.sub(r"\s+", " ", texto or "").strip()
    limpio = _RE_CORREO.sub("[correo]", limpio)
    limpio = _RE_NUMERO_LARGO.sub("[número]", limpio)
    return limpio if len(limpio) <= largo else limpio[: largo - 1] + "…"


def elegir(eventos: list[dict], *, n: int, salto: int = 0, solo: str = "aprobadas") -> list[dict]:
    """Eventos no delicados (aprobados o rechazados según `solo`) repartidos de forma pareja en el periodo: se toman `n` a partir de la posición
    `salto` de una muestra fija de hasta MUESTRA_TOTAL. Determinista, para que `--salto` pase a las siguientes sin repetir. PURA."""
    quiere_aprobadas = solo != "rechazadas"
    candidatos = [e for e in eventos if not e["payload"].get("delicado") and bool(e["payload"].get("aprobada")) == quiere_aprobadas]
    if not candidatos:
        return []
    paso = max(1, len(candidatos) // MUESTRA_TOTAL)
    repartidos = candidatos[::paso][:MUESTRA_TOTAL]
    return repartidos[salto: salto + n]


def formatear(k: int, evento: dict) -> str:
    p = evento["payload"]
    motivos = p.get("motivos") or []
    cabecera = f"[{k}]" + (f" RECHAZADA: {', '.join(motivos)}" if motivos else "")
    return (
        f"{cabecera}\nCLIENTE: {enmascarar(evento.get('ultimo_cliente'))}\n"
        f"SONNET : {(p.get('respuesta_real') or '').strip()}\nHAIKU  : {(p.get('respuesta_haiku') or '').strip()}\n"
    )


async def cargar(negocio_id: str, desde: datetime | None) -> list[dict]:
    async with mem.async_session() as session:
        q = select(mem.EventoLead.payload, mem.EventoLead.creado, mem.EventoLead.conversation_id).where(
            mem.EventoLead.negocio_id == negocio_id, mem.EventoLead.tipo == mem.EVENTO_MIX_HAIKU,
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
            anteriores = [c for t, c in previos[conversation_id] if t <= creado]
            salida.append({"payload": payload or {}, "ultimo_cliente": anteriores[-1] if anteriores else ""})
        return salida


async def main(argv=None) -> list[dict]:
    p = argparse.ArgumentParser(description="Muestra de respuestas del mix Haiku para revisar su calidad.")
    p.add_argument("--negocio-id", default=None)
    p.add_argument("--desde", default=None, help="Fecha ISO desde la que muestrear (UTC).")
    p.add_argument("--n", type=int, default=12)
    p.add_argument("--salto", type=int, default=0)
    p.add_argument("--solo", choices=("aprobadas", "rechazadas"), default="aprobadas")
    args = p.parse_args(argv)
    await esperar_base_de_datos()
    negocio_id = resolver_negocio_id(args.negocio_id, await listar_negocios())
    desde = datetime.fromisoformat(args.desde.replace("Z", "+00:00")).replace(tzinfo=None) if args.desde else None
    elegidos = elegir(await cargar(negocio_id, desde), n=args.n, salto=args.salto, solo=args.solo)
    for k, evento in enumerate(elegidos, start=args.salto + 1):
        print(formatear(k, evento))
    print(f"({len(elegidos)} mostradas)")
    return elegidos


if __name__ == "__main__":
    asyncio.run(main())
