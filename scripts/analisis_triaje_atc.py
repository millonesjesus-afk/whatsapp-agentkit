"""Análisis del triaje de temas no comerciales → Consulta ATC — SOLO LECTURA (2026-10-08).

Responde con DATOS, antes de encender el modo activo, a dos preguntas:
  · RECALL: de las conversaciones que una persona etiquetó `consulta_atc`, ¿en cuántas el triaje habría decidido cerrar?
  · PRECISIÓN: de las decisiones de cerrar, ¿cuántas terminaron en algo comercial (agendado, vendido, producto cargado,
    derivada por Gabi con intención de compra)? Esos son los falsos positivos que costarían una venta.
Además cuenta por categoría y por guarda/bloqueo (qué impidió cerrar un candidato) y, con la regla de tres, el límite
superior del error cuando no se observó ningún falso positivo (con 0 fallos en n casos, la tasa real de error es < 3/n con
95 % de confianza).

Fuente: los eventos internos `triaje_atc_sombra` (una decisión por candidato, en modo sombra o activo) y
`triaje_atc_cerrado`, cruzados con el resultado final de cada conversación. Un candidato es una conversación donde el
triaje detectó un tema (recibo, número de cliente, pago…) aunque lo bloqueara una guarda. Las conversaciones SIN ningún
tema detectado no dejan evento (la línea INFO `triaje_atc` del log sí cubre todas las evaluaciones).

EMERGENCIA DE GAS (2026-10-09, `triaje_atc_emergencia_modo`): las decisiones y los cierres de la categoría `emergencia_gas`
NO entran en las métricas de recibo/pago de arriba (no son consultas de atención al cliente ni cuentan para el recall);
tienen su sección 5: emergencias detectadas, avisadas (evento `emergencia_gas_derivada`), cerradas como consulta_atc y
las avisadas SIN cerrar (lead con asesor/pausa o con resultado), por modo y por guarda. Solo conteos.

Solo agregados: nunca teléfonos, nombres, texto de mensajes ni ids de conversación. Un grupo con n<10 muestra "n<10" en
vez de porcentajes. Lectura pura: solo SELECT; en Postgres la transacción se abre como READ ONLY. NO es un Cron.

Uso:
    python scripts/analisis_triaje_atc.py
    python scripts/analisis_triaje_atc.py --desde 2026-10-09 --hasta 2026-10-20

Definiciones:
  · Decisión «cerrar» = algún evento de la conversación con accion_propuesta=cerrar (o el triaje la cerró en modo activo).
  · Resultado final: `consulta_atc` = confirmada · agendado/vendido, producto cargado o derivada = comercial (falso positivo)
    · otro resultado cerrado = otro tema no comercial · sin resultado ni señal comercial = sin resolver.
    La etiqueta humana `consulta_atc` gana sobre cualquier señal comercial. El período es por fecha del evento; el recall
    solo mira conversaciones creadas desde el primer evento de sombra (antes no había forma de detectar nada).
"""
import argparse
import asyncio
import math
import sys
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import func, select, text

from agent.memory import (
    EVENTO_EMERGENCIA_GAS_DERIVADA, EVENTO_TRIAJE_ATC_CERRADO, EVENTO_TRIAJE_ATC_SOMBRA, Conversation, EventoLead, Lead, Contact, Opportunity,
    async_session, engine, esperar_base_de_datos,
)

LIMITE_N = 10
CATEGORIA_EMERGENCIA = "emergencia_gas"
RESULTADOS_COMERCIALES = ("agendado", "vendido")
EVENTOS_DERIVACION = ("asignado", "asignado_automatico", "derivado_sin_ia", "rotado_automatico_sin_respuesta")
DESDE_POR_DEFECTO = "2026-10-08"

try:
    from zoneinfo import ZoneInfo
    LIMA = ZoneInfo("America/Lima")
except Exception:  # noqa: BLE001 — sin tzdata (Windows): Lima es UTC-5 fijo
    LIMA = timezone(timedelta(hours=-5))


# ── Utilidades de formato (mismo estilo que scripts/analisis_conversion.py) ───────────────────────────────

def pct(num: int, den: int) -> str:
    if den < LIMITE_N:
        return "n<10"
    return f"{100 * num / den:.1f}".replace(".", ",") + "%"


def tabla(encabezados: list[str], filas: list[list]) -> list[str]:
    filas = [[str(c) for c in f] for f in filas]
    columnas = list(zip(encabezados, *filas)) if filas else [(h,) for h in encabezados]
    anchos = [max(len(x) for x in col) for col in columnas]

    def linea(fila):
        return "  " + "  ".join(c.ljust(a) if i == 0 else c.rjust(a) for i, (c, a) in enumerate(zip(fila, anchos))).rstrip()

    return [linea(encabezados), "  " + "  ".join("-" * a for a in anchos)] + [linea(f) for f in filas]


def es_emergencia(payload) -> bool:
    """¿El payload de un evento del triaje es de la categoría emergencia_gas? (no entra en las métricas ATC)."""
    return isinstance(payload, dict) and payload.get("categoria") == CATEGORIA_EMERGENCIA


def limite_superior_error(fallos: int, n: int) -> float | None:
    """Límite superior (95 %) de la tasa de error. Con 0 fallos: regla de tres, 3/n. Con fallos: límite superior de
    Wilson. None si no hay casos."""
    if n <= 0:
        return None
    if fallos <= 0:
        return min(1.0, 3 / n)
    z = 1.959964
    p = fallos / n
    centro = p + z * z / (2 * n)
    margen = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return min(1.0, (centro + margen) / (1 + z * z / n))


def pct_float(x: float | None) -> str:
    return "—" if x is None else f"{100 * x:.1f}".replace(".", ",") + "%"


# ── Modelo ────────────────────────────────────────────────────────────────────────────────────────────────

@dataclass
class Conv:
    id: str
    creado: datetime | None = None
    resultado: str | None = None
    producto: bool = False             # Opportunity o Lead con producto_tipo cargado
    derivada: bool = False             # asesor asignado, paso derivado_asesor o evento de derivación
    cerrada_por_triaje: bool = False
    decisiones: list = field(default_factory=list)   # payloads de `triaje_atc_sombra`, en orden
    reabierta: bool = False
    reabierta_comercial: bool = False

    @property
    def decidio_cerrar(self) -> bool:
        return self.cerrada_por_triaje or any(d.get("accion_propuesta") == "cerrar" for d in self.decisiones)

    @property
    def etiqueta_humana_atc(self) -> bool:
        return self.resultado == "consulta_atc" and not self.cerrada_por_triaje

    @property
    def ultima(self) -> dict:
        return self.decisiones[-1] if self.decisiones else {}

    def desenlace(self) -> str:
        """confirmada | comercial | otro_no_comercial | sin_resolver — la etiqueta humana consulta_atc manda."""
        if self.resultado == "consulta_atc":
            return "confirmada"
        if self.resultado in RESULTADOS_COMERCIALES or self.producto or self.derivada:
            return "comercial"
        if self.resultado:
            return "otro_no_comercial"
        return "sin_resolver"


@dataclass
class Datos:
    convs: dict                        # id → Conv: las que tienen eventos del triaje en el período
    universo_recall: list              # Conv de TODAS las consultas_atc creadas en el período (desde la medición)
    inicio_medicion: datetime | None
    desde: datetime
    hasta: datetime
    emergencias: dict = field(default_factory=dict)   # conversation_id → {"decision": payload|None, "avisada": bool, "cerrada": bool, "motivo": str|None}


# ── Carga (solo SELECT) ───────────────────────────────────────────────────────────────────────────────────

def _lotes(items, tamano: int = 400):
    items = list(items)
    for i in range(0, len(items), tamano):
        yield items[i:i + tamano]


async def _rellenar(session, convs: dict[str, Conv], desde: datetime) -> None:
    """Resultado final, producto y derivación de cada conversación; reaperturas del cierre del triaje."""
    ids = list(convs)
    for lote in _lotes(ids):
        for conv in (await session.execute(
            select(Conversation.id, Conversation.creado, Conversation.asesor_asignado_id, Conversation.paso_flujo, Conversation.contact_id)
            .where(Conversation.id.in_(lote))
        )).all():
            c = convs[conv.id]
            c.creado = conv.creado
            c.derivada = bool(conv.asesor_asignado_id) or conv.paso_flujo == "derivado_asesor"
        for o in (await session.execute(
            select(Opportunity.conversation_id, Opportunity.resultado, Opportunity.producto_tipo)
            .where(Opportunity.conversation_id.in_(lote)).order_by(Opportunity.creado, Opportunity.id)
        )).all():
            c = convs[o.conversation_id]
            c.resultado = o.resultado
            c.producto = bool(o.producto_tipo)
        for e in (await session.execute(
            select(EventoLead.conversation_id, EventoLead.tipo, EventoLead.payload).where(
                EventoLead.conversation_id.in_(lote), EventoLead.tipo.in_(EVENTOS_DERIVACION + (EVENTO_TRIAJE_ATC_CERRADO,)),
            )
        )).all():
            c = convs[e.conversation_id]
            if e.tipo == EVENTO_TRIAJE_ATC_CERRADO:
                if not es_emergencia(e.payload):
                    c.cerrada_por_triaje = True
            else:
                c.derivada = True
    # Producto cargado en el Lead de la conversación MÁS RECIENTE del contacto (el Lead refleja el último ciclo).
    for lote in _lotes(ids):
        filas = (await session.execute(
            select(Conversation.id, Lead.producto_tipo)
            .join(Contact, Contact.id == Conversation.contact_id)
            .join(Lead, (Lead.telefono == Contact.telefono) & (Lead.negocio_id == Conversation.negocio_id))
            .where(Conversation.id.in_(lote), Conversation.estado == "activa")
        )).all()
        for conv_id, producto in filas:
            if producto:
                convs[conv_id].producto = True
    # Reaperturas: el cliente volvió a escribir tras el cierre del triaje.
    cerradas = [i for i, c in convs.items() if c.cerrada_por_triaje]
    if cerradas:
        reaperturas: dict[str, str] = {}
        for e in (await session.execute(
            select(EventoLead.conversation_id, EventoLead.payload).where(EventoLead.tipo == "reabierto_por_cliente", EventoLead.creado >= desde)
        )).all():
            anterior = (e.payload or {}).get("conversation_anterior_id") if isinstance(e.payload, dict) else None
            if anterior in cerradas:
                reaperturas[anterior] = e.conversation_id
        if reaperturas:
            nuevas = {nuevo: Conv(nuevo) for nuevo in set(reaperturas.values())}
            for lote in _lotes(list(nuevas)):
                for o in (await session.execute(
                    select(Opportunity.conversation_id, Opportunity.resultado, Opportunity.producto_tipo)
                    .where(Opportunity.conversation_id.in_(lote)).order_by(Opportunity.creado, Opportunity.id)
                )).all():
                    nuevas[o.conversation_id].resultado, nuevas[o.conversation_id].producto = o.resultado, bool(o.producto_tipo)
            for anterior, nuevo in reaperturas.items():
                convs[anterior].reabierta = True
                n = nuevas[nuevo]
                convs[anterior].reabierta_comercial = n.resultado in RESULTADOS_COMERCIALES or n.producto


async def cargar_datos(session, desde: datetime, hasta: datetime) -> Datos:
    """`desde`/`hasta` en UTC naive (límite superior exclusivo)."""
    if engine.dialect.name == "postgresql":
        try:
            await session.execute(text("SET TRANSACTION READ ONLY"))
        except Exception as e:  # noqa: BLE001
            await session.rollback()
            print(f"AVISO: no se pudo abrir la transacción como READ ONLY ({type(e).__name__}); el script solo ejecuta SELECT.", file=sys.stderr)

    inicio_medicion = (await session.execute(
        select(func.min(EventoLead.creado)).where(EventoLead.tipo.in_((EVENTO_TRIAJE_ATC_SOMBRA, EVENTO_TRIAJE_ATC_CERRADO)))
    )).scalar_one_or_none()

    convs: dict[str, Conv] = {}
    emergencias: dict[str, dict] = {}
    for e in (await session.execute(
        select(EventoLead.conversation_id, EventoLead.tipo, EventoLead.payload)
        .where(
            EventoLead.tipo.in_((EVENTO_TRIAJE_ATC_SOMBRA, EVENTO_TRIAJE_ATC_CERRADO, EVENTO_EMERGENCIA_GAS_DERIVADA)),
            EventoLead.creado >= desde, EventoLead.creado < hasta,
        )
        .order_by(EventoLead.creado, EventoLead.id)
    )).all():
        if e.tipo == EVENTO_EMERGENCIA_GAS_DERIVADA or es_emergencia(e.payload):
            em = emergencias.setdefault(e.conversation_id, {"decision": None, "avisada": False, "cerrada": False, "motivo": None})
            if e.tipo == EVENTO_TRIAJE_ATC_SOMBRA:
                em["decision"] = e.payload
            elif e.tipo == EVENTO_TRIAJE_ATC_CERRADO:
                em["cerrada"] = True
            else:
                em["avisada"] = True
                em["motivo"] = (e.payload or {}).get("motivo_sin_cierre") if isinstance(e.payload, dict) else None
            continue
        c = convs.setdefault(e.conversation_id, Conv(e.conversation_id))
        if e.tipo == EVENTO_TRIAJE_ATC_SOMBRA and isinstance(e.payload, dict):
            c.decisiones.append(e.payload)
        elif e.tipo == EVENTO_TRIAJE_ATC_CERRADO:
            c.cerrada_por_triaje = True
    await _rellenar(session, convs, desde)

    universo: list[Conv] = []
    if inicio_medicion is not None:
        ini = max(desde, inicio_medicion - timedelta(hours=1))  # holgura: la conversación nace antes de su primer evento
        ids = (await session.execute(
            select(Opportunity.conversation_id)
            .join(Conversation, Conversation.id == Opportunity.conversation_id)
            .where(Opportunity.resultado == "consulta_atc", Conversation.creado >= ini, Conversation.creado < hasta)
        )).scalars().all()
        # Las consultas_atc que cerró el aviso de emergencia no son consultas de atención al cliente: fuera del recall.
        por_emergencia = {
            e.conversation_id for e in (await session.execute(
                select(EventoLead.conversation_id, EventoLead.payload).where(EventoLead.tipo == EVENTO_TRIAJE_ATC_CERRADO)
            )).all() if es_emergencia(e.payload)
        }
        ids = [i for i in ids if i not in por_emergencia]
        propias = {i: convs.get(i) or Conv(i) for i in set(ids)}
        faltan = {i: c for i, c in propias.items() if i not in convs}
        await _rellenar(session, faltan, desde)
        universo = list(propias.values())
    return Datos(convs, universo, inicio_medicion, desde, hasta, emergencias)


# ── Resumen (PURO) ────────────────────────────────────────────────────────────────────────────────────────

def resumir(datos: Datos) -> dict:
    convs = list(datos.convs.values())
    cerrar = [c for c in convs if c.decidio_cerrar]
    desenlaces = Counter(c.desenlace() for c in cerrar)
    resueltas = desenlaces["confirmada"] + desenlaces["comercial"]
    universo = datos.universo_recall
    detectadas = [c for c in universo if c.decidio_cerrar]
    por_categoria = Counter(c.ultima.get("categoria") or ("(cerrada)" if c.cerrada_por_triaje else "?") for c in convs)
    por_guarda: Counter = Counter()
    for c in convs:
        for g in dict.fromkeys(c.ultima.get("guardas_que_bloquearon") or []):
            por_guarda[g] += 1
    por_modo = Counter(c.ultima.get("modo") or "?" for c in convs if c.decisiones)
    cerradas = [c for c in convs if c.cerrada_por_triaje]
    em = list(datos.emergencias.values())
    emergencia = {
        "detectadas": len(em), "avisadas": sum(e["avisada"] for e in em), "cerradas": sum(e["cerrada"] for e in em),
        "avisadas_sin_cierre": sum(e["avisada"] and not e["cerrada"] for e in em),
        "por_motivo_sin_cierre": dict(Counter(e["motivo"] or "?" for e in em if e["avisada"] and not e["cerrada"])),
        "por_modo": dict(Counter((e["decision"] or {}).get("modo") or "?" for e in em if e["decision"])),
        "por_guarda": dict(Counter(g for e in em for g in dict.fromkeys((e["decision"] or {}).get("guardas_que_bloquearon") or []))),
    }
    return {
        "emergencia": emergencia,
        "candidatas": len(convs), "decision_cerrar": len(cerrar), "bloqueadas": len(convs) - len(cerrar),
        "desenlaces": dict(desenlaces), "resueltas": resueltas, "falsos_positivos": desenlaces["comercial"],
        "precision": (desenlaces["confirmada"] / resueltas) if resueltas else None,
        "precision_conservadora": (desenlaces["confirmada"] / len(cerrar)) if cerrar else None,
        "error_superior": limite_superior_error(desenlaces["comercial"], resueltas),
        "universo_recall": len(universo), "detectadas": len(detectadas),
        "recall": (len(detectadas) / len(universo)) if universo else None,
        "por_categoria": dict(por_categoria), "por_guarda": dict(por_guarda), "por_modo": dict(por_modo),
        "cerradas_por_triaje": len(cerradas), "reabiertas": sum(c.reabierta for c in cerradas),
        "reabiertas_comerciales": sum(c.reabierta_comercial for c in cerradas),
    }


def _lineas_emergencia(e: dict) -> list[str]:
    L = ["", "=" * 100, "5. EMERGENCIA DE GAS (triaje_atc_emergencia_modo; fuera de las métricas de recibo/pago)", "=" * 100]
    L += tabla(["Concepto", "n"], [
        ["Conversaciones con una emergencia detectada", e["detectadas"]],
        ["  con aviso enviado a Emergencias de Cálidda (evento emergencia_gas_derivada)", e["avisadas"]],
        ["    cerradas como consulta_atc", e["cerradas"]],
        ["    avisadas SIN cerrar (asesor/pausa, resultado o cierre no posible)", e["avisadas_sin_cierre"]],
        ["  sin aviso (modo sombra o apagado, guardas, envío fallido)", e["detectadas"] - e["avisadas"]],
    ])
    if e["por_motivo_sin_cierre"]:
        L.append("")
        L.append("Avisadas sin cerrar, por motivo:")
        L += tabla(["Motivo", "n"], [[k, v] for k, v in sorted(e["por_motivo_sin_cierre"].items(), key=lambda kv: -kv[1])])
    if e["por_modo"]:
        L.append("")
        L.append("Modo de la última decisión de cada emergencia:")
        L += tabla(["Modo", "n"], [[k, v] for k, v in sorted(e["por_modo"].items())])
    if e["por_guarda"]:
        L.append("")
        L.append("Guardas que impidieron avisar (una conversación cuenta una vez por cada una):")
        L += tabla(["Guarda", "n"], [[k, v] for k, v in sorted(e["por_guarda"].items(), key=lambda kv: -kv[1])])
    L.append("  Tasa de reapertura y revisión de falsos positivos: lee el chat de esas conversaciones en el panel (el informe no muestra texto).")
    return L


def formatear(datos: Datos, r: dict, desde_txt: str, hasta_txt: str) -> list[str]:
    L = [
        "ANÁLISIS DEL TRIAJE ATC — solo lectura",
        f"Período (Lima): {desde_txt} a {hasta_txt}  |  n<10 = muestra muy chica, sin porcentaje.",
        "Medición desde: " + (datos.inicio_medicion.isoformat(timespec="minutes") + " UTC" if datos.inicio_medicion else "sin eventos del triaje todavía"),
        "",
    ]
    if not r["candidatas"] and not r["universo_recall"]:
        L.append("  Sin eventos del triaje en el período: ¿está encendido el modo sombra (triaje_atc_modo)?")
        if r["emergencia"]["detectadas"]:
            L += _lineas_emergencia(r["emergencia"])
        return L

    L += ["=" * 100, "1. CANDIDATAS Y DECISIONES", "=" * 100]
    L += tabla(["Concepto", "n"], [
        ["Conversaciones con un tema detectado (candidatas)", r["candidatas"]],
        ["  con decisión de cerrar", r["decision_cerrar"]],
        ["  bloqueadas por una guarda, un bloqueo comercial o baja confianza", r["bloqueadas"]],
        ["Cerradas de verdad por el triaje (modo activo)", r["cerradas_por_triaje"]],
    ])

    L += ["", "=" * 100, "2. PRECISIÓN de las decisiones de cerrar", "=" * 100]
    d = r["desenlaces"]
    L += tabla(["Desenlace final de la conversación", "n", "%"], [
        ["Confirmada consulta_atc (etiqueta humana o cierre del triaje)", d.get("confirmada", 0), pct(d.get("confirmada", 0), r["decision_cerrar"])],
        ["Comercial (agendado, vendido, producto cargado o derivada) = FALSO POSITIVO", d.get("comercial", 0), pct(d.get("comercial", 0), r["decision_cerrar"])],
        ["Otro resultado no comercial", d.get("otro_no_comercial", 0), pct(d.get("otro_no_comercial", 0), r["decision_cerrar"])],
        ["Sin resolver (sin resultado ni señal comercial todavía)", d.get("sin_resolver", 0), pct(d.get("sin_resolver", 0), r["decision_cerrar"])],
    ])
    L.append("")
    L.append(f"  Precisión sobre las resueltas (confirmada / (confirmada + comercial)), n={r['resueltas']}: "
             f"{pct(d.get('confirmada', 0), r['resueltas'])}")
    L.append(f"  Precisión conservadora (confirmada / todas las decisiones de cerrar), n={r['decision_cerrar']}: "
             f"{pct(d.get('confirmada', 0), r['decision_cerrar'])}")
    L.append(f"  Falsos positivos observados: {r['falsos_positivos']} de {r['resueltas']} resueltas  |  "
             f"límite superior del error (95 %): {pct_float(r['error_superior'])}"
             + ("  ← regla de tres: 3/n" if r["falsos_positivos"] == 0 and r["resueltas"] else ""))
    if r["cerradas_por_triaje"]:
        L.append(f"  Modo activo: de {r['cerradas_por_triaje']} cerradas por el triaje, {r['reabiertas']} fueron reabiertas por el cliente "
                 f"y {r['reabiertas_comerciales']} de ellas terminaron en algo comercial (el falso positivo más caro).")

    L += ["", "=" * 100, "3. RECALL sobre las consultas_atc del período", "=" * 100]
    L += tabla(["Concepto", "n", "%"], [
        ["Conversaciones con resultado consulta_atc (creadas desde el inicio de la medición)", r["universo_recall"], ""],
        ["  en las que el triaje decidió cerrar", r["detectadas"], pct(r["detectadas"], r["universo_recall"])],
        ["  que el triaje no habría cerrado", r["universo_recall"] - r["detectadas"], pct(r["universo_recall"] - r["detectadas"], r["universo_recall"])],
    ])
    L.append("  Las no cerradas muestran qué palabras o guardas faltan: revisa 'por guarda' y las frases reales en el panel.")

    L += ["", "=" * 100, "4. POR CATEGORÍA Y POR GUARDA", "=" * 100]
    L.append("Candidatas por categoría (última decisión de cada conversación):")
    L += tabla(["Categoría", "n"], [[k, v] for k, v in sorted(r["por_categoria"].items(), key=lambda kv: -kv[1])])
    L.append("")
    L.append("Guardas / bloqueos que impidieron cerrar (una conversación cuenta una vez por cada uno):")
    L += tabla(["Guarda o bloqueo", "n"], [[k, v] for k, v in sorted(r["por_guarda"].items(), key=lambda kv: -kv[1])] or [["(ninguno)", 0]])
    L.append("")
    L.append("Modo en el que se tomó la última decisión:")
    L += tabla(["Modo", "n"], [[k, v] for k, v in sorted(r["por_modo"].items())] or [["(ninguno)", 0]])
    L += _lineas_emergencia(r["emergencia"])
    return L


# ── Orquestación ──────────────────────────────────────────────────────────────────────────────────────────

def a_lima(dt_utc: datetime) -> datetime:
    return dt_utc.replace(tzinfo=timezone.utc).astimezone(LIMA)


def lima_a_utc(dt_lima_naive: datetime) -> datetime:
    return dt_lima_naive.replace(tzinfo=LIMA).astimezone(timezone.utc).replace(tzinfo=None)


def rango_utc(desde: str, hasta: str | None, ahora: datetime) -> tuple[datetime, datetime]:
    """`desde`/`hasta`: fechas AAAA-MM-DD de Lima, ambas inclusivas. Devuelve [desde, hasta) en UTC naive."""
    d = datetime.strptime(desde, "%Y-%m-%d")
    h = datetime.strptime(hasta, "%Y-%m-%d") if hasta else datetime.combine(a_lima(ahora).date(), datetime.min.time())
    if h < d:
        raise ValueError("--hasta no puede ser anterior a --desde")
    return lima_a_utc(d), lima_a_utc(h + timedelta(days=1))


async def generar_informe(desde: str = DESDE_POR_DEFECTO, hasta: str | None = None, ahora: datetime | None = None) -> list[str]:
    ahora = ahora or datetime.now(timezone.utc).replace(tzinfo=None)
    ini, fin = rango_utc(desde, hasta, ahora)
    async with async_session() as session:
        datos = await cargar_datos(session, ini, fin)
        await session.rollback()  # lectura pura: nada que confirmar
    return formatear(datos, resumir(datos), desde, hasta or a_lima(ahora).date().isoformat())


async def main_async(args) -> None:
    await esperar_base_de_datos()
    print(f"Base de datos: {engine.url.get_backend_name()} / {engine.url.database}")
    for linea in await generar_informe(args.desde, args.hasta):
        print(linea)


def _fecha(valor: str) -> str:
    try:
        datetime.strptime(valor, "%Y-%m-%d")
    except ValueError:
        raise argparse.ArgumentTypeError(f"fecha inválida {valor!r}: usa AAAA-MM-DD")
    return valor


def construir_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Análisis del triaje ATC (solo lectura).")
    p.add_argument("--desde", type=_fecha, default=DESDE_POR_DEFECTO, help=f"Primer día (Lima, inclusive). Default {DESDE_POR_DEFECTO}.")
    p.add_argument("--hasta", type=_fecha, default=None, help="Último día (Lima, inclusive). Default: hoy.")
    return p


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass
    argumentos = construir_parser().parse_args()
    try:
        asyncio.run(main_async(argumentos))
    except Exception as e:
        print(f"ERROR: análisis del triaje falló — {e}", file=sys.stderr)
        sys.exit(1)
