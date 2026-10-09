"""Cuántos candidatos a "Para llamar" habría por semana y segmento — SOLO LECTURA (2026-10-09).

Aplica las reglas E1-E4 y el puntaje de agent/llamadas.py a los leads de los últimos N días y cuenta, por semana (lunes, hora
de Lima de su último mensaje del cliente) y por segmento (A, B, exploración), cuántas tareas se habrían creado, más cuántos
leads se descartaron y por qué regla. Sirve para decidir el tamaño del equipo y los umbrales ANTES de encender el módulo.

Solo agregados: nunca teléfonos, nombres, ids de conversación ni texto de mensajes. Lectura pura: solo SELECT (en Postgres la
transacción se abre como READ ONLY). NO es un Cron: se corre a mano.

Para estimar el pasado, un lead que el cierre automático de 15 h ya dejó como `sin_respuesta` cuenta como si siguiera abierto
(es justo el universo que las llamadas quieren rescatar); el resto de las reglas se aplican como en producción.

Uso (la base sale de DATABASE_URL, como en los demás scripts):
    python scripts/medir_candidatos_llamada.py
    python scripts/medir_candidatos_llamada.py --negocio-id <id> --dias 28 --horas-silencio 4 --puntaje-minimo 4
"""
import argparse
import asyncio
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select, text

from agent import llamadas
from agent.memory import Lead, async_session, engine, esperar_base_de_datos, listar_negocios
from scripts.configurar_triaje_atc import resolver_negocio_id

OFFSET_LIMA = timedelta(hours=5)
MINIMO_PARA_MOSTRAR = 10


def _argumentos(argv=None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Cuenta candidatos a «Para llamar» por semana y segmento (solo lectura).")
    p.add_argument("--negocio-id", default=None, help="Id del negocio. Si se omite y hay un solo negocio activo, se usa ese.")
    p.add_argument("--dias", type=int, default=28, help="Cuántos días hacia atrás mirar (default 28).")
    p.add_argument("--horas-silencio", type=float, default=llamadas.LIMITES[llamadas.CLAVE_HORAS_SILENCIO][2], help="Silencio mínimo (default 4).")
    p.add_argument("--puntaje-minimo", type=int, default=llamadas.LIMITES[llamadas.CLAVE_PUNTAJE_MINIMO][2], help="Puntaje mínimo (default 4).")
    p.add_argument("--holdout-pct", type=float, default=llamadas.LIMITES[llamadas.CLAVE_HOLDOUT_PCT][2], help="% del grupo de control (default 30).")
    return p.parse_args(argv)


def _lunes_de_la_semana(instante_utc: datetime) -> str:
    lima = instante_utc - OFFSET_LIMA
    return (lima - timedelta(days=lima.weekday())).strftime("%Y-%m-%d")


async def medir(negocio_id: str, dias: int, horas_silencio: float, puntaje_minimo: int, holdout_pct: float, ahora: datetime | None = None) -> dict:
    """Devuelve {"semanas": {lunes: {A, B, exploracion, control, total}}, "descartados": {motivo: n}, "evaluados": n}."""
    ahora = ahora or datetime.utcnow()
    semanas: dict[str, Counter] = defaultdict(Counter)
    descartados: Counter = Counter()
    evaluados = 0
    async with async_session() as session:
        if engine.dialect.name == "postgresql":
            try:
                await session.execute(text("SET TRANSACTION READ ONLY"))
            except Exception as e:  # noqa: BLE001
                await session.rollback()
                print(f"AVISO: no se pudo abrir la transacción como READ ONLY ({type(e).__name__}); el script solo ejecuta SELECT.", file=sys.stderr)
        leads = (await session.execute(
            select(Lead).where(Lead.negocio_id == negocio_id, Lead.actualizado >= ahora - timedelta(days=dias))
        )).scalars().all()
        for lead in leads:
            evaluados += 1
            ev = await llamadas.evaluar_lead(session, lead, ahora, horas_silencio, medicion=True)
            if not ev.elegible:
                descartados[ev.motivo] += 1
                continue
            segmento = llamadas.segmento_de(ev.puntaje, puntaje_minimo)
            if segmento is None:
                descartados["puntaje_bajo"] += 1
                continue
            semana = semanas[_lunes_de_la_semana(ev.ultimo_cliente_en)]
            semana[segmento] += 1
            semana["total"] += 1
            if llamadas.grupo_de(ev.conversation_id, holdout_pct) == llamadas.GRUPO_CONTROL:
                semana["control"] += 1
    return {
        "evaluados": evaluados,
        "semanas": {lunes: {k: c[k] for k in ("A", "B", "total", "control")} for lunes, c in sorted(semanas.items())},
        "descartados": dict(descartados.most_common()),
    }


def formatear(resultado: dict, holdout_pct: float) -> str:
    lineas = [f"Leads evaluados: {resultado['evaluados']}", "", "Candidatos por semana (lunes) y segmento:"]
    lineas.append(f"  {'semana':<12}{'A':>6}{'B':>6}{'total':>8}{'a llamar':>10}{'control':>9}")
    for lunes, c in resultado["semanas"].items():
        lineas.append(f"  {lunes:<12}{c['A']:>6}{c['B']:>6}{c['total']:>8}{c['total'] - c['control']:>10}{c['control']:>9}")
    if not resultado["semanas"]:
        lineas.append("  (ninguno)")
    lineas += ["", f"(control = holdout de {holdout_pct:g} %: se registran pero no se llaman)", "", "Descartados por regla:"]
    for motivo, n in resultado["descartados"].items():
        lineas.append(f"  {motivo:<26}{n:>6}")
    if not resultado["descartados"]:
        lineas.append("  (ninguno)")
    return "\n".join(lineas)


async def main(argv=None) -> dict:
    args = _argumentos(argv)
    await esperar_base_de_datos()
    negocio_id = resolver_negocio_id(args.negocio_id, await listar_negocios())
    resultado = await medir(negocio_id, args.dias, args.horas_silencio, args.puntaje_minimo, args.holdout_pct)
    print(formatear(resultado, args.holdout_pct))
    return resultado


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass
    try:
        asyncio.run(main())
    except ValueError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(2)
