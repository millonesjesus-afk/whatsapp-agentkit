"""Análisis de la SOMBRA del experimento «solo clic» — SOLO LECTURA (2026-10-16, Fase B; ver docs/experimento_solo_clic.md).

Lee los eventos internos `exp_solo_clic_sombra` (a qué brazo iría cada conversación y qué habría hecho el sistema) y mide, desde
los mensajes reales, qué pasó de forma NATURAL: en sombra nadie recibe nada nuevo, así que TODOS los brazos se comportan como
control y la «línea base» p0 de cada brazo debería coincidir (si no, el reparto está sesgado o la muestra es chica).

Entrega, solo con AGREGADOS (nunca teléfonos, nombres, ids de conversación ni texto de mensajes):
  · tamaño de la cohorte por brazo y semana;
  · línea base p0 de respuesta del cliente a 24 h y 72 h desde T+20, por brazo, con intervalo de Wilson al 95 %
    (solo cuentan los casos cuyo horizonte ya se cumplió);
  · % alcanzable a T+60 (dentro del horario de atención con la ventana abierta) y % ofertable (incluye diferir a la apertura);
  · efecto mínimo detectable (dos proporciones, α = 0,05, potencia 80 %) con el n disponible por brazo y los días estimados
    para juntar 90 casos por brazo al ritmo actual;
  · el aviso «muestra insuficiente» cuando una celda tiene menos de 10 casos.

Lectura pura: solo SELECT (en Postgres la transacción se abre como READ ONLY). No es un Cron: se corre a mano.

Uso (la base sale de DATABASE_URL):
    python scripts/analizar_solo_clic.py --negocio-id <id>
    python scripts/analizar_solo_clic.py --negocio-id <id> --epoca v1 --dias 30
"""
import argparse
import asyncio
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select, text

from agent import solo_clic
from agent.memory import EVENTO_EXP_SOLO_CLIC_SOMBRA, Contact, Conversation, EventoLead, async_session, engine, esperar_base_de_datos, listar_negocios
from scripts.configurar_triaje_atc import resolver_negocio_id

MINIMO_PARA_MOSTRAR = 10
CASOS_OBJETIVO_POR_BRAZO = 90
ALFA, POTENCIA = 0.05, 0.80


def _argumentos(argv=None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Analiza la sombra del experimento «solo clic» (solo lectura).")
    p.add_argument("--negocio-id", default=None, help="Id del negocio. Si se omite y hay un solo negocio activo, se usa ese.")
    p.add_argument("--epoca", default=None, help="Época del experimento (default: la configurada, «v1»).")
    p.add_argument("--dias", type=int, default=30, help="Cuántos días hacia atrás mirar (default 30).")
    return p.parse_args(argv)


def _de_iso(valor) -> datetime | None:
    if not isinstance(valor, str):
        return None
    try:
        return datetime.fromisoformat(valor.rstrip("Z"))
    except ValueError:
        return None


def _celda(k: int, n: int) -> dict:
    bajo, alto = solo_clic.intervalo_wilson(k, n)
    return {"k": k, "n": n, "p": (k / n) if n else None, "ic_bajo": bajo, "ic_alto": alto, "insuficiente": n < MINIMO_PARA_MOSTRAR}


async def analizar(negocio_id: str, epoca: str | None = None, dias: int = 30, ahora: datetime | None = None) -> dict:
    """Devuelve los agregados de la sombra. Solo SELECT."""
    ahora = ahora or datetime.utcnow()
    config = await solo_clic.leer_config(negocio_id, avisar=False)
    epoca = epoca or config.epoca
    total_pct = (config.pct_c + config.pct_t1 + config.pct_t2) or 100.0
    shares = {solo_clic.BRAZO_C: config.pct_c / total_pct, solo_clic.BRAZO_T1: config.pct_t1 / total_pct, solo_clic.BRAZO_T2: config.pct_t2 / total_pct}
    por_semana: dict[str, Counter] = defaultdict(Counter)
    cohorte: Counter = Counter()
    k24: Counter = Counter()
    n24: Counter = Counter()
    k72: Counter = Counter()
    n72: Counter = Counter()
    alcanzables: Counter = Counter()
    ofertables: Counter = Counter()
    creados: list[datetime] = []
    async with async_session() as session:
        if engine.dialect.name == "postgresql":
            try:
                await session.execute(text("SET TRANSACTION READ ONLY"))
            except Exception as e:  # noqa: BLE001
                await session.rollback()
                print(f"AVISO: no se pudo abrir la transacción como READ ONLY ({type(e).__name__}); el script solo ejecuta SELECT.", file=sys.stderr)
        sombras = (await session.execute(
            select(EventoLead.conversation_id, EventoLead.payload, EventoLead.creado).where(
                EventoLead.negocio_id == negocio_id, EventoLead.tipo == EVENTO_EXP_SOLO_CLIC_SOMBRA,
                EventoLead.creado >= ahora - timedelta(days=dias),
            )
        )).all()
        for conversation_id, payload, creado in sombras:
            if not isinstance(payload, dict) or payload.get("epoca") != epoca:
                continue
            brazo = payload.get("brazo")
            ancla = _de_iso(payload.get("ancla_en"))
            primer_gabi = _de_iso(payload.get("primer_gabi_en"))
            if brazo not in solo_clic.BRAZOS or ancla is None or primer_gabi is None:
                continue
            creados.append(creado)
            cohorte[brazo] += 1
            por_semana[solo_clic.lunes_de_la_semana_lima(primer_gabi)][brazo] += 1
            if payload.get("cayo_en_horario_a_T60") is True:
                alcanzables[brazo] += 1
            if (payload.get("oferta_hipotetica") or {}).get("estado") == solo_clic.ACCION_OFERTA:
                ofertables[brazo] += 1
            conversation = await session.get(Conversation, conversation_id)
            contact = await session.get(Contact, conversation.contact_id) if conversation else None
            if conversation is None or contact is None:
                continue
            for horizonte, n, k in ((24, n24, k24), (72, n72, k72)):
                if ahora < ancla + timedelta(hours=horizonte):
                    continue                                   # el horizonte aún no se cumple: no es observable
                resultado = await solo_clic.desenlace(session, conversation, contact.telefono, ancla, horizonte)
                n[brazo] += 1
                k[brazo] += bool(resultado["respondio"])

    total = sum(cohorte.values())
    brazos = {}
    for b in solo_clic.BRAZOS:
        brazos[b] = {
            "cohorte": cohorte[b], "p24": _celda(k24[b], n24[b]), "p72": _celda(k72[b], n72[b]),
            "alcanzable_t60": _celda(alcanzables[b], cohorte[b]), "ofertable": _celda(ofertables[b], cohorte[b]),
        }
    todos24 = _celda(sum(k24.values()), sum(n24.values()))
    todos72 = _celda(sum(k72.values()), sum(n72.values()))
    # Poder: todos los brazos son «control» en sombra, así que p0 = la tasa conjunta a 72 h (la métrica primaria P1).
    p0 = todos72["p"]
    mde = {}
    for b in (solo_clic.BRAZO_T1, solo_clic.BRAZO_T2):
        n_disponible = min(n72[solo_clic.BRAZO_C], n72[b])
        efecto = solo_clic.efecto_minimo_detectable(p0, n_disponible, ALFA, POTENCIA) if p0 is not None else None
        mde[b] = {"n_por_brazo": n_disponible, "efecto_minimo_detectable": efecto}
    dias_observados = max(1.0, (ahora - min(creados)).total_seconds() / 86400) if creados else None
    ritmo = (total / dias_observados) if dias_observados else None
    dias_para_90 = {
        b: (CASOS_OBJETIVO_POR_BRAZO / (ritmo * shares[b])) if ritmo and shares[b] > 0 else None for b in solo_clic.BRAZOS
    }
    return {
        "epoca": epoca, "dias": dias, "cohorte_total": total, "por_semana": {s: {b: c[b] for b in solo_clic.BRAZOS} for s, c in sorted(por_semana.items())},
        "brazos": brazos, "todos_p24": todos24, "todos_p72": todos72, "mde": mde, "ritmo_diario": ritmo,
        "dias_para_90_por_brazo": dias_para_90, "shares": shares,
    }


def _fmt_celda(c: dict) -> str:
    if not c["n"]:
        return "—"
    bajo, alto = c["ic_bajo"], c["ic_alto"]
    return f"{100 * c['p']:.0f} % ({c['k']}/{c['n']}; IC95 {100 * bajo:.0f}-{100 * alto:.0f} %)" + (" *" if c["insuficiente"] else "")


def formatear(r: dict) -> str:
    L = [f"Experimento «solo clic» — sombra, época {r['epoca']}, últimos {r['dias']} días. Cohorte total: {r['cohorte_total']}", ""]
    L.append("Cohorte por semana (lunes, hora de Lima) y brazo:")
    L.append(f"  {'semana':<12}{'C':>6}{'T1':>6}{'T2':>6}")
    for semana, c in r["por_semana"].items():
        L.append(f"  {semana:<12}{c['C']:>6}{c['T1']:>6}{c['T2']:>6}")
    if not r["por_semana"]:
        L.append("  (ninguna)")
    L += ["", "Línea base natural (el cliente volvió a escribir) desde T+20, por brazo [* = n < 10: muestra insuficiente]:"]
    for b, d in r["brazos"].items():
        L.append(f"  {b:<3} cohorte {d['cohorte']:>4} · 24 h: {_fmt_celda(d['p24'])} · 72 h: {_fmt_celda(d['p72'])}")
    L.append(f"  todos  · 24 h: {_fmt_celda(r['todos_p24'])} · 72 h: {_fmt_celda(r['todos_p72'])}")
    L += ["", "Alcanzable a T+60 (dentro del horario con la ventana abierta) y ofertable (incluye diferir a la apertura):"]
    for b, d in r["brazos"].items():
        L.append(f"  {b:<3} alcanzable {_fmt_celda(d['alcanzable_t60'])} · ofertable {_fmt_celda(d['ofertable'])}")
    L += ["", f"Poder (α {ALFA}, potencia {int(POTENCIA * 100)} %), p0 conjunta a 72 h:"]
    for b, d in r["mde"].items():
        e = d["efecto_minimo_detectable"]
        L.append(f"  {b} vs C: n por brazo {d['n_por_brazo']} → efecto mínimo detectable " + (f"{100 * e:.1f} puntos" if e is not None else "no calculable (n muy chico)"))
    if r["ritmo_diario"]:
        L.append(f"  Ritmo: {r['ritmo_diario']:.1f} conversaciones «solo clic» por día. Días para {CASOS_OBJETIVO_POR_BRAZO} casos por brazo: " + " · ".join(
            f"{b} {d:.0f}" if d else f"{b} —" for b, d in r["dias_para_90_por_brazo"].items()
        ))
    n_total = r["cohorte_total"]
    if n_total < MINIMO_PARA_MOSTRAR or any(d["cohorte"] < MINIMO_PARA_MOSTRAR for d in r["brazos"].values()):
        L += ["", "AVISO: muestra insuficiente (algún brazo tiene menos de 10 casos): no saques conclusiones todavía."]
    return "\n".join(L)


async def main(argv=None) -> dict:
    args = _argumentos(argv)
    await esperar_base_de_datos()
    negocio_id = resolver_negocio_id(args.negocio_id, await listar_negocios())
    resultado = await analizar(negocio_id, args.epoca, args.dias)
    print(formatear(resultado))
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
