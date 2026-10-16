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

MODO `--solo-clic` (2026-10-16, Fase A del experimento «solo clic», agent/solo_clic.py): en vez de los candidatos a «Para
llamar», mide el segmento «solo clic» con la regla aprobada, SOLO LECTURA y solo agregados (sin teléfonos, nombres, ids ni
texto de mensajes): conteo semanal, distribución por hora de Lima y día de la semana, % que cae dentro del horario de atención
a T+60 min (con feriados), % con la ventana de 24 h cerrada al abrir el negocio, cuántos pasarían el puntaje mínimo del
módulo actual (el atajo de puntaje), motivos de descarte por regla y los 20 textos prellenados más frecuentes (solo texto
repetido en >= 5 conversaciones, con su conteo). Sirve para decidir ANTES de encender la sombra.
    python scripts/medir_candidatos_llamada.py --solo-clic --negocio-id <id> --dias 14
"""
import argparse
import asyncio
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select, text

from agent import atencion_atrasada, llamadas, solo_clic
from agent.memory import Contact, Conversation, Lead, async_session, engine, esperar_base_de_datos, listar_negocios
from agent.tools import _rangos_de_atencion_por_dia
from scripts.configurar_triaje_atc import resolver_negocio_id

OFFSET_LIMA = timedelta(hours=5)
MINIMO_PARA_MOSTRAR = 10


def _argumentos(argv=None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Cuenta candidatos a «Para llamar» por semana y segmento (solo lectura).")
    p.add_argument("--negocio-id", default=None, help="Id del negocio. Si se omite y hay un solo negocio activo, se usa ese.")
    p.add_argument("--dias", type=int, default=28, help="Cuántos días hacia atrás mirar (default 28).")
    p.add_argument("--horas-silencio", type=float, default=llamadas.LIMITES[llamadas.CLAVE_HORAS_SILENCIO][2], help="Silencio mínimo (default 4).")
    p.add_argument("--puntaje-minimo", type=int, default=llamadas.LIMITES[llamadas.CLAVE_PUNTAJE_MINIMO][2], help="Puntaje mínimo (default 4).")
    p.add_argument("--holdout-pct", type=float, default=llamadas.LIMITES[llamadas.CLAVE_HOLDOUT_PCT][2], help="%% del grupo de control (default 30).")
    p.add_argument("--solo-clic", action="store_true", help="Mide el segmento «solo clic» (experimento) en vez de los candidatos a «Para llamar».")
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


DIAS_SEMANA_ES = ("lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo")
_RE_NUMEROS_LARGOS = re.compile(r"\d{6,}")


def _texto_seguro(texto: str) -> str:
    """Un texto prellenado para mostrar: sin números largos (por si alguien pegó un dato) y recortado."""
    return _RE_NUMEROS_LARGOS.sub("#", texto)[:80]


async def _solo_lectura(session) -> None:
    if engine.dialect.name == "postgresql":
        try:
            await session.execute(text("SET TRANSACTION READ ONLY"))
        except Exception as e:  # noqa: BLE001
            await session.rollback()
            print(f"AVISO: no se pudo abrir la transacción como READ ONLY ({type(e).__name__}); el script solo ejecuta SELECT.", file=sys.stderr)


async def medir_solo_clic(negocio_id: str, dias: int, horas_silencio: float, puntaje_minimo: int, ahora: datetime | None = None) -> dict:
    """Mide el segmento «solo clic» de las conversaciones creadas en los últimos `dias`. Solo agregados; solo SELECT."""
    ahora = ahora or datetime.utcnow()
    desde = ahora - timedelta(days=dias)
    config = await solo_clic.leer_config(negocio_id, avisar=False)
    ctx = await solo_clic.contexto_de_negocio(negocio_id, ahora)
    conteo = await solo_clic.conteo_prellenados(negocio_id, ahora)
    rangos = await _rangos_de_atencion_por_dia(negocio_id)
    semanas: Counter = Counter()
    por_hora: Counter = Counter()
    por_dia: Counter = Counter()
    motivos: Counter = Counter()
    r: Counter = Counter()
    async with async_session() as session:
        await _solo_lectura(session)
        conversaciones = (await session.execute(
            select(Conversation).where(Conversation.negocio_id == negocio_id, Conversation.creado >= desde)
        )).scalars().all()
        for conversation in conversaciones:
            r["evaluadas"] += 1
            veredicto = await solo_clic.evaluar_conversacion(session, conversation, ctx, cohorte_min=config.cohorte_min)
            if not veredicto.es_solo_clic:
                motivos[veredicto.motivo] += 1
                continue
            ancla = veredicto.primer_gabi_en + timedelta(minutes=config.cohorte_min)
            if ancla > ahora:
                motivos["aun_no_cumple_la_cohorte"] += 1       # todavía no pasó T+20: su silencio aún no está decidido
                continue
            r["solo_clic"] += 1
            lima = veredicto.primer_gabi_en - OFFSET_LIMA
            semanas[solo_clic.lunes_de_la_semana_lima(veredicto.primer_gabi_en)] += 1
            por_hora[lima.hour] += 1
            por_dia[lima.weekday()] += 1
            plan = solo_clic.plan_de_accion(
                solo_clic.BRAZO_T2, primer_gabi_en=veredicto.primer_gabi_en, ultimo_cliente_en=veredicto.ultimo_cliente_en,
                abierto=lambda t: atencion_atrasada.esta_abierto(rangos, t),
                proxima_apertura=lambda t: atencion_atrasada.proxima_apertura(rangos, t),
                toque_min=config.toque_min, oferta_min=config.oferta_min, ventana_max_horas=config.ventana_max_horas,
            )
            if plan["cayo_en_horario_a_T60"]:
                r["en_horario_t60"] += 1
            else:
                r["fuera_de_horario_t60"] += 1
                if plan["ventana_cierra_antes_de_apertura"]:
                    r["ventana_cerrada_al_abrir"] += 1
            estado = plan["oferta_hipotetica"]["estado"]
            if estado == solo_clic.ACCION_OFERTA:
                r["ofertable"] += 1
                if plan["oferta_hipotetica"]["diferida"]:
                    r["ofertable_diferida"] += 1
            # ¿Pasaría el puntaje mínimo del módulo ACTUAL (el atajo)? Solo si es la conversación vigente del lead.
            contact = await session.get(Contact, conversation.contact_id)
            lead = await session.get(Lead, contact.telefono) if contact else None
            if lead is not None and lead.negocio_id == negocio_id:
                ev = await llamadas.evaluar_lead(session, lead, ahora, horas_silencio, medicion=True)
                if ev.elegible and ev.conversation_id == conversation.id:
                    r["puntaje_evaluable"] += 1
                    if ev.puntaje >= puntaje_minimo:
                        r["puntaje_pasa"] += 1
    frecuentes = [(t, n) for t, n in conteo.most_common() if n >= solo_clic.MINIMO_CONVERSACIONES_PRELLENADO][:20]
    return {
        "evaluadas": r["evaluadas"], "solo_clic": r["solo_clic"], "cohorte_min": config.cohorte_min, "oferta_min": config.oferta_min,
        "semanas": dict(sorted(semanas.items())), "por_hora_lima": {h: por_hora[h] for h in range(24)},
        "por_dia_semana": {d: por_dia[d] for d in range(7)},
        "en_horario_t60": r["en_horario_t60"], "fuera_de_horario_t60": r["fuera_de_horario_t60"],
        "ventana_cerrada_al_abrir": r["ventana_cerrada_al_abrir"], "ofertable": r["ofertable"], "ofertable_diferida": r["ofertable_diferida"],
        "puntaje_evaluable": r["puntaje_evaluable"], "puntaje_pasa": r["puntaje_pasa"], "puntaje_minimo": puntaje_minimo,
        "descartes": dict(motivos.most_common()),
        "prellenados_frecuentes": [(_texto_seguro(t), n) for t, n in frecuentes],
        "prellenados_otros_distintos": sum(1 for _, n in conteo.items() if n < solo_clic.MINIMO_CONVERSACIONES_PRELLENADO),
    }


def _pct(parte: int, total: int) -> str:
    return f"{100 * parte / total:.0f} %" if total else "—"


def formatear_solo_clic(r: dict) -> str:
    total = r["solo_clic"]
    L = [f"Conversaciones evaluadas: {r['evaluadas']} · «solo clic» (silencio hasta T+{r['cohorte_min']} min): {total}", ""]
    L.append("Por semana (lunes, hora de Lima del primer mensaje de Gabi):")
    L += [f"  {lunes:<12}{n:>6}" for lunes, n in r["semanas"].items()] or ["  (ninguna)"]
    L += ["", "Por hora de Lima (primer mensaje de Gabi):"]
    L.append("  " + (" ".join(f"{h:02d}h:{n}" for h, n in r["por_hora_lima"].items() if n) or "(ninguna)"))
    L += ["", "Por día de la semana:"]
    L.append("  " + " · ".join(f"{DIAS_SEMANA_ES[d]} {n}" for d, n in r["por_dia_semana"].items()))
    L += ["", f"Alcanzabilidad de la oferta a T+{r['oferta_min']} min:"]
    L.append(f"  dentro del horario de atención (con feriados): {r['en_horario_t60']} ({_pct(r['en_horario_t60'], total)})")
    L.append(f"  fuera de horario: {r['fuera_de_horario_t60']} ({_pct(r['fuera_de_horario_t60'], total)})")
    L.append(f"  con la ventana de 24 h cerrada al abrir el negocio: {r['ventana_cerrada_al_abrir']} ({_pct(r['ventana_cerrada_al_abrir'], total)})")
    L.append(
        f"  ofertables (a T+{r['oferta_min']} o diferidas a la apertura, con margen de ventana): "
        f"{r['ofertable']} ({_pct(r['ofertable'], total)}), de ellas diferidas: {r['ofertable_diferida']}"
    )
    L += ["", f"Atajo de puntaje del módulo actual (≥ {r['puntaje_minimo']}):"]
    L.append(f"  pasarían: {r['puntaje_pasa']} de {r['puntaje_evaluable']} evaluables ({_pct(r['puntaje_pasa'], r['puntaje_evaluable'])})")
    L.append("  (con el experimento encendido NO se crea tarea para ellos: motivo solo_clic_en_experimento)")
    L += ["", "Motivos de descarte por regla:"]
    L += [f"  {m:<30}{n:>6}" for m, n in r["descartes"].items()] or ["  (ninguno)"]
    L += ["", f"Textos prellenados más frecuentes (≥ {solo_clic.MINIMO_CONVERSACIONES_PRELLENADO} conversaciones en {solo_clic.DIAS_PRELLENADOS} días), solo conteo:"]
    L += [f"  {n:>5}  {t}" for t, n in r["prellenados_frecuentes"]] or ["  (ninguno)"]
    L.append(f"  (más {r['prellenados_otros_distintos']} texto(s) distintos con menos repeticiones: no se muestran)")
    if total < 10:
        L += ["", "AVISO: muestra insuficiente (menos de 10 casos): no saques conclusiones."]
    return "\n".join(L)


async def main(argv=None) -> dict:
    args = _argumentos(argv)
    await esperar_base_de_datos()
    negocio_id = resolver_negocio_id(args.negocio_id, await listar_negocios())
    if args.solo_clic:
        resultado = await medir_solo_clic(negocio_id, args.dias, args.horas_silencio, args.puntaje_minimo)
        print(formatear_solo_clic(resultado))
        return resultado
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
