"""Análisis de conversión — SOLO LECTURA (2026-10-07).

Responde con DATOS a la pregunta "¿cuál es la segunda palanca de conversión,
además de la redacción de Gabi?". Imprime tablas de texto en español, solo
agregados: nunca teléfonos, nombres de clientes, texto de mensajes ni ids de
conversación (los únicos nombres propios que salen son los usernames del
personal en la sección 6, de uso interno del dueño).

Lectura pura: solo SELECT. En Postgres la transacción se abre como
`READ ONLY`, así que la base misma rechazaría cualquier escritura.

NO es un Cron (no usa `ejecutar_cron`): se corre a mano, una vez, contra la
base de producción de Railway a través de un servicio temporal.

Uso:
    python scripts/analisis_conversion.py
    python scripts/analisis_conversion.py --desde 2026-09-15 --hasta 2026-10-06
    python scripts/analisis_conversion.py --solo embudo velocidad resumen

Secciones (--solo, acepta nombre o número, separado por espacios o comas):
    1 embudo | 2 origen | 3 velocidad | 4 reenganche | 5 gabi | 6 asesores |
    7 cierres | 8 resumen

Definiciones:
  · Ciclo = una Conversation (activa o cerrada). Lead único = un teléfono, con
    su ciclo MÁS RECIENTE dentro del período. Las secciones 4 (reenganche),
    5 (mensajes de Gabi) y 7 (reaperturas) usan todos los ciclos.
  · Todas las horas se muestran en America/Lima. Los instantes de la base son
    UTC naive.
  · Un grupo con n<10 muestra "n<10" en vez de porcentajes o percentiles.
  · Éxito = resultado agendado o vendido.
"""
import argparse
import asyncio
import re
import sys
import unicodedata
from bisect import bisect_right
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import func, select, text

from agent.memory import (
    AttributionEvent, Contact, Conversation, EnvioMeta, EventoLead, Lead, Mensaje, Opportunity, Usuario,
    async_session, engine, es_texto_de_error_tecnico, es_texto_de_reenganche_automatico, esperar_base_de_datos,
    textos_de_error_tecnico_conocidos,
)

try:
    from zoneinfo import ZoneInfo
    LIMA = ZoneInfo("America/Lima")
except Exception:  # noqa: BLE001 — sin base de zonas horarias (Windows sin tzdata): Lima es UTC-5 fijo, sin horario de verano
    LIMA = timezone(timedelta(hours=-5))

LIMITE_N = 10
DESDE_POR_DEFECTO = "2026-09-15"
EXITO = ("agendado", "vendido")
HORAS_VENTANA = 24
HORAS_SILENCIO_REENGANCHE = 2.0
ORIGENES_DERIVACION_ENVIO = ("gabi_aviso_derivacion", "gabi_respaldo_sin_ia")
EVENTOS_DERIVACION_AUTOMATICA = ("asignado_automatico", "derivado_sin_ia")
EVENTOS_QUE_IMPLICAN_DERIVACION = (
    "asignado", "asignado_automatico", "derivado_sin_ia", "rotado_automatico_sin_respuesta", "desasignado_automatico",
)
TIPOS_EVENTO_CON_PAYLOAD = ("reabierto_por_cliente", "cerrado_definitivamente", "cerrado_definitivamente_automatico", "desasignado_automatico")
SECCIONES = ("embudo", "origen", "velocidad", "reenganche", "gabi", "asesores", "cierres", "resumen")
DIAS = ("Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo")
FRANJAS = ("Mañana (8-13)", "Tarde (13-19)", "Noche (19-24)", "Madrugada (0-8)")
BUCKETS_ESPERA = ("<15 min", "15-60 min", "1-4 h", "4-12 h", ">12 h", "nunca")


# ── Utilidades de tiempo y formato ──────────────────────────────────────────────────────────────

def a_lima(dt_utc: datetime) -> datetime:
    return dt_utc.replace(tzinfo=timezone.utc).astimezone(LIMA)


def lima_a_utc(dt_lima_naive: datetime) -> datetime:
    return dt_lima_naive.replace(tzinfo=LIMA).astimezone(timezone.utc).replace(tzinfo=None)


def franja_de(dt_utc: datetime) -> str:
    h = a_lima(dt_utc).hour
    if 8 <= h < 13:
        return FRANJAS[0]
    if 13 <= h < 19:
        return FRANJAS[1]
    if h >= 19:
        return FRANJAS[2]
    return FRANJAS[3]


def pct(num: int, den: int) -> str:
    """Porcentaje en español; con menos de LIMITE_N en la base no se calcula."""
    if den < LIMITE_N:
        return "n<10"
    return f"{100 * num / den:.1f}".replace(".", ",") + "%"


def num_es(valor: float, decimales: int = 1) -> str:
    return f"{valor:.{decimales}f}".replace(".", ",")


def fmt_dur(seg: float | None) -> str:
    if seg is None:
        return "—"
    if seg < 60:
        return f"{seg:.0f} s"
    if seg < 3600:
        return f"{num_es(seg / 60, 0)} min"
    if seg < 86400:
        return f"{num_es(seg / 3600)} h"
    return f"{num_es(seg / 86400)} d"


def percentil(valores_ordenados: list[float], p: float) -> float:
    if not valores_ordenados:
        raise ValueError("lista vacía")
    k = (len(valores_ordenados) - 1) * p
    inferior = int(k)
    superior = min(inferior + 1, len(valores_ordenados) - 1)
    return valores_ordenados[inferior] + (valores_ordenados[superior] - valores_ordenados[inferior]) * (k - inferior)


def fila_percentiles(nombre: str, valores: list[float]) -> list:
    n = len(valores)
    if n < LIMITE_N:
        return [nombre, n, "n<10", "n<10", "n<10"]
    v = sorted(valores)
    return [nombre, n, fmt_dur(percentil(v, 0.5)), fmt_dur(percentil(v, 0.75)), fmt_dur(percentil(v, 0.9))]


def tabla(encabezados: list[str], filas: list[list]) -> list[str]:
    filas = [[str(c) for c in f] for f in filas]
    columnas = list(zip(encabezados, *filas)) if filas else [(h,) for h in encabezados]
    anchos = [max(len(x) for x in col) for col in columnas]

    def linea(fila):
        return "  " + "  ".join(
            c.ljust(a) if i == 0 else c.rjust(a) for i, (c, a) in enumerate(zip(fila, anchos))
        ).rstrip()

    return [linea(encabezados), "  " + "  ".join("-" * a for a in anchos)] + [linea(f) for f in filas]


def titulo(numero: int, nombre: str) -> list[str]:
    return ["", "=" * 100, f"{numero}. {nombre}", "=" * 100]


def _norm(t: str | None) -> str:
    n = unicodedata.normalize("NFKD", (t or "").lower())
    return "".join(c for c in n if not unicodedata.combining(c))


# ── Rasgos del texto de un mensaje (el texto se descarta; solo quedan banderas) ─────────────────

_RE_PRECIO = re.compile(r"s/\.?\s*\d|\bsoles\b|\d\s*soles")
_RE_DNI = re.compile(r"\bdni\b|documento de identidad")
_FRASES_NOMBRE = ("tu nombre", "como te llamas", "como te llamo", "con quien tengo el gusto", "a nombre de quien", "tus nombres")


def rasgos_texto(contenido: str | None) -> dict:
    c = contenido or ""
    n = _norm(c)
    return {
        "largo": len(c),
        "negrita": "**" in c,
        "pregunta": "?" in c[-80:],
        "precio": bool(_RE_PRECIO.search(n)),
        "dni": bool(_RE_DNI.search(n)),
        "financ": "financ" in n or "cuota" in n or "recibo de gas" in n,
        "nombre": any(f in n for f in _FRASES_NOMBRE),
    }


@dataclass(slots=True)
class Msg:
    ts: datetime
    tipo: str  # c cliente | cr reacción del cliente | g Gabi | h humano (asesor o echo del celular) | r reenganche automático | e aviso de error técnico
    largo: int = 0
    negrita: bool = False
    pregunta: bool = False
    precio: bool = False
    dni: bool = False
    financ: bool = False
    nombre: bool = False
    via_app: bool = False


def clasificar_mensaje(role: str, via_app: bool, estado_envio: str | None, contenido: str | None, conocidos: frozenset) -> str | None:
    if role == "user":
        return "cr" if _norm(contenido).startswith("reacciono con") else "c"
    if (estado_envio or "") == "fallido":
        return None  # nunca llegó: no cuenta como respuesta de nadie
    if role == "asesor" or (role == "assistant" and via_app):
        return "h"
    if role == "assistant":
        if es_texto_de_reenganche_automatico(contenido):
            return "r"
        if es_texto_de_error_tecnico(contenido, conocidos):
            return "e"
        return "g"
    return None


# ── Modelo de análisis ──────────────────────────────────────────────────────────────────────────

@dataclass
class Ciclo:
    id: str
    telefono: str
    negocio_id: str
    creado: datetime
    estado: str
    paso_flujo: str | None
    asesor_conv: str | None
    origen_contacto: str | None
    cerrado_def_en: datetime | None
    en_rango: bool = False
    es_ultimo: bool = False
    resultado: str | None = None
    interes_txt: str | None = None
    tipo_producto: str | None = None
    lead_origen_contacto: str | None = None
    lead_paso_flujo: str | None = None
    lead_asesor: str | None = None
    msgs: list = field(default_factory=list)
    eventos: list = field(default_factory=list)  # (tipo, creado, payload|None)
    envios: list = field(default_factory=list)  # (origen, decision, creado, tipo, asesor)
    atribuciones: list = field(default_factory=list)  # tipo_origen
    # ── calculado en finalizar() ──
    primer_msg: datetime | None = None
    primer_cliente: datetime | None = None
    primer_gabi: datetime | None = None
    respondio: bool = False
    humano: bool = False
    primer_humano: datetime | None = None
    ultimo_cliente_previo_al_humano: datetime | None = None
    espera_humana: float | None = None  # último mensaje del cliente previo → 1.ª respuesta humana (s)
    derivado: bool = False
    derivacion_ts: datetime | None = None
    espera_desde_derivacion: float | None = None
    postventa: bool = False
    exito: bool = False
    origen: str = "Orgánico/otro"
    interes: str = "Sin dato"
    asesor: str | None = None
    reenganche_ts: datetime | None = None
    reenganche_bloqueado_ts: datetime | None = None

    def clientes(self) -> list[datetime]:
        return [m.ts for m in self.msgs if m.tipo == "c"]

    def finalizar(self) -> None:
        msgs = self.msgs
        self.primer_msg = next((m.ts for m in msgs if m.tipo in ("c", "g", "h")), None)
        self.primer_cliente = next((m.ts for m in msgs if m.tipo == "c"), None)
        self.primer_gabi = next((m.ts for m in msgs if m.tipo == "g"), None)
        if self.primer_gabi is not None:
            self.respondio = any(m.tipo == "c" and m.ts > self.primer_gabi for m in msgs)
        humanos = [m for m in msgs if m.tipo == "h"]
        self.humano = bool(humanos)
        self.primer_humano = humanos[0].ts if humanos else None
        if self.primer_humano is not None:
            previos = [m.ts for m in msgs if m.tipo == "c" and m.ts < self.primer_humano]
            if previos:
                self.ultimo_cliente_previo_al_humano = previos[-1]
                self.espera_humana = (self.primer_humano - previos[-1]).total_seconds()

        tipos_evento = {e[0] for e in self.eventos}
        self.postventa = (
            "asignado_automatico_postventa" in tipos_evento or (self.resultado or "") in ("postventa", "servicio_postventa")
        )
        marcas = [e[1] for e in self.eventos if e[0] in EVENTOS_DERIVACION_AUTOMATICA]
        marcas += [
            e[1] for e in self.eventos
            if e[0] == "desasignado_automatico" and (e[2] or {}).get("destino") == "supervision"
        ]
        marcas += [en[2] for en in self.envios if en[0] in ORIGENES_DERIVACION_ENVIO and en[1] == "enviado"]
        self.derivacion_ts = min(marcas) if marcas else None
        self.derivado = bool(
            self.paso_flujo == "derivado_asesor" or self.asesor_conv or self.derivacion_ts
            or tipos_evento.intersection(EVENTOS_QUE_IMPLICAN_DERIVACION)
            or (self.es_ultimo and (self.lead_paso_flujo == "derivado_asesor" or self.lead_asesor))
        )
        if self.derivacion_ts is not None and self.primer_humano is not None:
            self.espera_desde_derivacion = max(0.0, (self.primer_humano - self.derivacion_ts).total_seconds())

        self.exito = (self.resultado or "") in EXITO
        self.asesor = self.asesor_conv or (self.lead_asesor if self.es_ultimo else None)
        if not self.asesor:
            for tipo, _, payload in reversed(self.eventos):
                if tipo in ("asignado", "asignado_automatico") and (payload or {}).get("nuevo"):
                    self.asesor = payload["nuevo"]
                    break

        # Origen
        formulario = "formulario" in (self.origen_contacto or "") or "formulario" in (self.lead_origen_contacto or "")
        if formulario:
            self.origen = "Formulario"
        elif any(a in ("meta_ads", "meta_ads_no_resuelto") for a in self.atribuciones):
            self.origen = "Anuncio CTWA"
        elif "wa_link" in self.atribuciones:
            self.origen = "Enlace wa.link"
        else:
            self.origen = "Orgánico/otro"
        self.interes = agrupar_interes(self.tipo_producto, self.interes_txt)

        # Reenganche automático (mensaje guardado o envío registrado)
        candidatos = [m.ts for m in msgs if m.tipo == "r"]
        candidatos += [en[2] for en in self.envios if en[0] == "reenganche_inactividad" and en[1] == "enviado"]
        self.reenganche_ts = min(candidatos) if candidatos else None
        bloqueos = [en[2] for en in self.envios if en[0] == "reenganche_inactividad" and en[1] == "bloqueado"]
        self.reenganche_bloqueado_ts = min(bloqueos) if bloqueos and self.reenganche_ts is None else None

    def ultimo_cliente(self) -> datetime | None:
        c = self.clientes()
        return c[-1] if c else None

    def inicio_espera(self) -> datetime | None:
        """Mensaje del cliente que quedó esperando: el previo a la 1.ª respuesta humana, o el último si nadie respondió."""
        if self.primer_humano is not None:
            return self.ultimo_cliente_previo_al_humano
        return self.ultimo_cliente()

    def bucket_espera(self, seg: float | None) -> str:
        if not self.humano:
            return "nunca"
        return bucket_de(seg)


def bucket_de(seg: float | None) -> str:
    if seg is None:
        return "sin dato"
    if seg < 15 * 60:
        return BUCKETS_ESPERA[0]
    if seg < 3600:
        return BUCKETS_ESPERA[1]
    if seg < 4 * 3600:
        return BUCKETS_ESPERA[2]
    if seg < 12 * 3600:
        return BUCKETS_ESPERA[3]
    return BUCKETS_ESPERA[4]


def agrupar_interes(tipo: str | None, interes: str | None) -> str:
    texto = _norm(f"{tipo or ''} {interes or ''}")
    if not texto.strip():
        return "Sin dato"
    if "terma" in texto or "calentador" in texto:
        return "Terma"
    if "secadora" in texto:
        return "Secadora"
    if "cocina" in texto or "horno" in texto or "encimera" in texto:
        return "Cocina"
    return "Otros"


@dataclass
class Datos:
    ciclos: list  # todos los ciclos de los contactos tocados (con en_rango marcado)
    envios_panel: list  # (asesor_usuario, tipo, decision, cantidad)
    usuarios: dict  # username -> (rol, nivel)
    ahora: datetime
    desde: datetime
    hasta: datetime

    @property
    def en_rango(self) -> list[Ciclo]:
        return [c for c in self.ciclos if c.en_rango]

    @property
    def leads(self) -> list[Ciclo]:
        """Un lead por teléfono: su ciclo más reciente dentro del período."""
        por_tel: dict[tuple, Ciclo] = {}
        for c in sorted(self.en_rango, key=lambda x: x.creado):
            por_tel[(c.negocio_id, c.telefono)] = c
        return list(por_tel.values())

    def primer_ciclo_en_rango(self) -> dict[tuple, Ciclo]:
        primero: dict[tuple, Ciclo] = {}
        for c in sorted(self.en_rango, key=lambda x: x.creado):
            primero.setdefault((c.negocio_id, c.telefono), c)
        return primero


# ── Carga (solo SELECT) ─────────────────────────────────────────────────────────────────────────

def _lotes(items, tamano: int = 400):
    items = list(items)
    for i in range(0, len(items), tamano):
        yield items[i:i + tamano]


async def _opcional(session, consulta, nombre: str) -> list:
    """Ejecuta un SELECT sobre una tabla que puede no existir en una base vieja: si falla (dentro de un savepoint, para no
    abortar la transacción) avisa por stderr y sigue sin esos datos."""
    try:
        async with session.begin_nested():
            return (await session.execute(consulta)).all()
    except Exception as e:  # noqa: BLE001
        print(f"AVISO: no se pudo leer {nombre} ({type(e).__name__}); se sigue sin esos datos.", file=sys.stderr)
        return []


async def cargar_datos(session, desde: datetime, hasta: datetime, ahora: datetime) -> Datos:
    """`desde`/`hasta` en UTC naive (límite superior exclusivo)."""
    if engine.dialect.name == "postgresql":
        try:
            await session.execute(text("SET TRANSACTION READ ONLY"))  # la base misma rechaza cualquier escritura
        except Exception as e:  # noqa: BLE001 — defensa extra: si no se puede fijar, el script igual solo hace SELECT
            await session.rollback()
            print(f"AVISO: no se pudo abrir la transacción como READ ONLY ({type(e).__name__}); el script solo ejecuta SELECT.", file=sys.stderr)

    en_rango = (await session.execute(
        select(Conversation.contact_id).where(Conversation.creado >= desde, Conversation.creado < hasta)
    )).scalars().all()
    contact_ids = sorted(set(en_rango))

    contactos: dict[str, tuple[str, str]] = {}
    for lote in _lotes(contact_ids):
        for fila in (await session.execute(
            select(Contact.id, Contact.negocio_id, Contact.telefono).where(Contact.id.in_(lote))
        )).all():
            contactos[fila.id] = (fila.negocio_id, fila.telefono)

    ciclos: list[Ciclo] = []
    por_id: dict[str, Ciclo] = {}
    for lote in _lotes(contact_ids):
        for conv in (await session.execute(
            select(
                Conversation.id, Conversation.negocio_id, Conversation.contact_id, Conversation.estado, Conversation.paso_flujo,
                Conversation.asesor_asignado_id, Conversation.origen_contacto, Conversation.cerrado_definitivamente_en,
                Conversation.creado,
            ).where(Conversation.contact_id.in_(lote)).order_by(Conversation.creado, Conversation.id)
        )).all():
            if conv.contact_id not in contactos:
                continue
            neg, tel = contactos[conv.contact_id]
            c = Ciclo(
                id=conv.id, telefono=tel, negocio_id=neg or conv.negocio_id, creado=conv.creado, estado=conv.estado,
                paso_flujo=conv.paso_flujo, asesor_conv=conv.asesor_asignado_id, origen_contacto=conv.origen_contacto,
                cerrado_def_en=conv.cerrado_definitivamente_en, en_rango=desde <= conv.creado < hasta,
            )
            ciclos.append(c)
            por_id[c.id] = c

    por_contacto: dict[tuple, list[Ciclo]] = defaultdict(list)
    for c in ciclos:
        por_contacto[(c.negocio_id, c.telefono)].append(c)
    for lista in por_contacto.values():
        lista.sort(key=lambda x: x.creado)
        lista[-1].es_ultimo = True
    creados = {k: [c.creado for c in lista] for k, lista in por_contacto.items()}
    claves_por_telefono: dict[str, list[tuple]] = defaultdict(list)
    for k in por_contacto:
        claves_por_telefono[k[1]].append(k)

    def ciclo_de(neg: str, tel: str, ts: datetime, conv_id: str | None) -> Ciclo | None:
        if conv_id and conv_id in por_id:
            return por_id[conv_id]
        lista = por_contacto.get((neg, tel))
        if not lista:
            return None
        return lista[max(bisect_right(creados[(neg, tel)], ts) - 1, 0)]

    # Oportunidades (resultado vigente = la más reciente de cada conversación)
    ids = [c.id for c in ciclos]
    for lote in _lotes(ids):
        for o in (await session.execute(
            select(Opportunity.conversation_id, Opportunity.resultado, Opportunity.interes, Opportunity.producto_tipo)
            .where(Opportunity.conversation_id.in_(lote)).order_by(Opportunity.creado, Opportunity.id)
        )).all():
            c = por_id.get(o.conversation_id)
            if c is not None:
                c.resultado, c.interes_txt, c.tipo_producto = o.resultado, o.interes, o.producto_tipo

    # Lead (solo informa al ciclo más reciente de cada teléfono)
    telefonos = sorted({c.telefono for c in ciclos})
    for lote in _lotes(telefonos):
        for ld in (await session.execute(
            select(
                Lead.telefono, Lead.resultado, Lead.paso_flujo, Lead.interes, Lead.producto_tipo, Lead.origen_contacto,
                Lead.asesor_asignado,
            ).where(Lead.telefono.in_(lote))
        )).all():
            for clave in claves_por_telefono.get(ld.telefono, []):
                ultimo = por_contacto[clave][-1]
                ultimo.lead_paso_flujo, ultimo.lead_asesor, ultimo.lead_origen_contacto = ld.paso_flujo, ld.asesor_asignado, ld.origen_contacto
                if ultimo.resultado is None:
                    ultimo.resultado = ld.resultado
                if not ultimo.interes_txt:
                    ultimo.interes_txt = ld.interes
                if not ultimo.tipo_producto:
                    ultimo.tipo_producto = ld.producto_tipo

    # Eventos de la línea de tiempo y evidencia de atribución
    for lote in _lotes(ids):
        for e in await _opcional(
            session,
            select(EventoLead.conversation_id, EventoLead.tipo, EventoLead.creado, EventoLead.payload)
            .where(EventoLead.conversation_id.in_(lote)).order_by(EventoLead.creado, EventoLead.id),
            "eventos_lead",
        ):
            c = por_id.get(e.conversation_id)
            if c is not None:
                c.eventos.append((e.tipo, e.creado, e.payload if e.tipo in TIPOS_EVENTO_CON_PAYLOAD or e.tipo.startswith("asignado") else None))
        for a in await _opcional(
            session,
            select(AttributionEvent.conversation_id, AttributionEvent.tipo_origen).where(AttributionEvent.conversation_id.in_(lote)),
            "attribution_events",
        ):
            c = por_id.get(a.conversation_id)
            if c is not None:
                c.atribuciones.append(a.tipo_origen)

    # Mensajes: se traen en lotes y el texto se reduce a banderas de inmediato
    try:
        conocidos = textos_de_error_tecnico_conocidos()
    except Exception:  # noqa: BLE001 — sin el YAML de prompts igual sirven los históricos y la heurística
        conocidos = frozenset()
    for lote in _lotes(telefonos):
        for m in (await session.execute(
            select(
                Mensaje.telefono, Mensaje.negocio_id, Mensaje.role, Mensaje.via_app, Mensaje.estado_envio, Mensaje.timestamp,
                Mensaje.conversation_id, Mensaje.content,
            ).where(Mensaje.telefono.in_(lote)).order_by(Mensaje.timestamp, Mensaje.id)
        )).all():
            tipo = clasificar_mensaje(m.role, bool(m.via_app), m.estado_envio, m.content, conocidos)
            if tipo is None:
                continue
            c = ciclo_de(m.negocio_id, m.telefono, m.timestamp, m.conversation_id)
            if c is None:
                continue
            rasgos = rasgos_texto(m.content) if tipo in ("g", "r", "e") else {}
            c.msgs.append(Msg(ts=m.timestamp, tipo=tipo, via_app=bool(m.via_app), **rasgos))

    # Envíos registrados por la capa central (origen, decisión)
    for lote in _lotes(telefonos):
        for en in await _opcional(
            session,
            select(
                EnvioMeta.telefono, EnvioMeta.negocio_id, EnvioMeta.origen, EnvioMeta.decision, EnvioMeta.creado,
                EnvioMeta.tipo, EnvioMeta.asesor_usuario,
            ).where(EnvioMeta.telefono.in_(lote)).order_by(EnvioMeta.creado, EnvioMeta.id),
            "envios_meta",
        ):
            neg = en.negocio_id
            if neg is None:
                candidatos = claves_por_telefono.get(en.telefono, [])
                neg = candidatos[0][0] if candidatos else None
            if neg is None:
                continue
            c = ciclo_de(neg, en.telefono, en.creado, None)
            if c is not None:
                c.envios.append((en.origen, en.decision, en.creado, en.tipo, en.asesor_usuario))

    for c in ciclos:
        c.finalizar()

    # Mensajes enviados desde el panel por cada asesor (agregado en SQL, sin teléfonos)
    envios_panel = [
        (f.asesor_usuario, f.tipo, f.decision, f.n)
        for f in await _opcional(
            session,
            select(EnvioMeta.asesor_usuario, EnvioMeta.tipo, EnvioMeta.decision, func.count(EnvioMeta.id).label("n"))
            .where(EnvioMeta.asesor_usuario.is_not(None), EnvioMeta.creado >= desde, EnvioMeta.creado < hasta)
            .group_by(EnvioMeta.asesor_usuario, EnvioMeta.tipo, EnvioMeta.decision),
            "envios_meta (por asesor)",
        )
    ]
    usuarios = {
        u.username: (u.rol, u.nivel)
        for u in await _opcional(session, select(Usuario.username, Usuario.rol, Usuario.nivel), "usuarios")
    }
    return Datos(ciclos=ciclos, envios_panel=envios_panel, usuarios=usuarios, ahora=ahora, desde=desde, hasta=hasta)


# ── Sección 1: embudo ───────────────────────────────────────────────────────────────────────────

ENCABEZADO_EMBUDO = ["Grupo", "n", "% respondió", "% derivado", "% msg humano", "% agend+vend", "n deriv.", "% agend+vend s/deriv."]


def fila_embudo(etiqueta: str, cs: list[Ciclo]) -> list:
    n = len(cs)
    con_gabi = [c for c in cs if c.primer_gabi is not None]
    der = [c for c in cs if c.derivado]
    return [
        etiqueta, n,
        pct(sum(c.respondio for c in con_gabi), len(con_gabi)),
        pct(len(der), n),
        pct(sum(c.humano for c in cs), n),
        pct(sum(c.exito for c in cs), n),
        len(der),
        pct(sum(c.exito for c in der), len(der)),
    ]


def seccion_embudo(d: Datos) -> tuple[list[str], dict]:
    leads = d.leads
    primero = d.primer_ciclo_en_rango()
    L = titulo(1, "EMBUDO")
    L.append(f"Unidad: lead único por teléfono, ciclo más reciente del período. Leads: {len(leads)}; ciclos (conversaciones) en el período: {len(d.en_rango)}.")
    L.append("Lectura: dónde se cae el volumen entre el primer mensaje de Gabi, la derivación, la atención humana y el resultado.")
    L.append("")
    if not leads:
        L.append("  Sin leads en el período.")
        return L, {"n": 0}

    L.append("Leads creados por semana (lunes, hora Lima; semana del primer ciclo del teléfono dentro del período):")
    semanas: dict[str, list[Ciclo]] = defaultdict(list)
    por_tel = {(c.negocio_id, c.telefono): c for c in leads}
    for clave, c0 in primero.items():
        lunes = a_lima(c0.creado).date()
        lunes = lunes - timedelta(days=lunes.weekday())
        semanas[lunes.isoformat()].append(por_tel[clave])
    L += tabla(ENCABEZADO_EMBUDO, [fila_embudo(s, semanas[s]) for s in sorted(semanas)] + [fila_embudo("TOTAL", leads)])
    sin_gabi = sum(1 for c in leads if c.primer_gabi is None)
    L.append(f"  % respondió = al menos un mensaje del cliente después del primer mensaje de Gabi (base: leads con mensaje de Gabi; {sin_gabi} sin ninguno).")
    L.append("  % derivado = paso derivado_asesor, asesor asignado, evento de derivación o aviso de derivación. % msg humano = asesor (panel) o echo del celular.")

    L.append("")
    L.append("Distribución del resultado final:")
    cuenta = Counter((c.resultado or "sin resultado") for c in leads)
    L += tabla(["Resultado", "n", "% de leads"], [[r, k, pct(k, len(leads))] for r, k in cuenta.most_common()])

    der = [c for c in leads if c.derivado]
    exito = sum(c.exito for c in leads)
    exito_der = sum(c.exito for c in der)
    L.append("")
    L.append("Conversión (agendado + vendido):")
    L += tabla(
        ["Base", "n", "agendado+vendido", "%"],
        [["Sobre leads totales", len(leads), exito, pct(exito, len(leads))],
         ["Sobre leads derivados", len(der), exito_der, pct(exito_der, len(der))]],
    )
    pv = sum(1 for c in leads if c.postventa)
    if pv:
        L.append(f"  Nota: {pv} lead(s) son ciclos de postventa (cliente ya vendido que vuelve a escribir); se incluyen aquí y se excluyen de las secciones 3 a 6.")
    return L, {"n": len(leads), "derivados": len(der), "exito": exito, "exito_der": exito_der, "pct_resp": (sum(c.respondio for c in leads if c.primer_gabi), sum(1 for c in leads if c.primer_gabi))}


# ── Sección 2: origen, interés, día y franja ────────────────────────────────────────────────────

def seccion_origen(d: Datos) -> tuple[list[str], dict]:
    leads = d.leads
    L = titulo(2, "ORIGEN, INTERÉS, DÍA Y FRANJA HORARIA")
    L.append("Lectura: dónde convierten mejor (y peor) los leads según cómo llegaron, qué buscaban y cuándo escribieron por primera vez.")
    if not leads:
        L.append("  Sin leads en el período.")
        return L, {}

    def bloque(nombre: str, claves: list[str], clave_de) -> None:
        grupos: dict[str, list[Ciclo]] = defaultdict(list)
        for c in leads:
            k = clave_de(c)
            if k is not None:
                grupos[k].append(c)
        L.append("")
        L.append(nombre + ":")
        etiqueta = [k for k in claves if k in grupos] + sorted(k for k in grupos if k not in claves)
        L.extend(tabla(ENCABEZADO_EMBUDO, [fila_embudo(k, grupos[k]) for k in etiqueta]))

    bloque("Por origen (anuncio CTWA = evidencia de referral de Meta; formulario = Lead Ad)", ["Anuncio CTWA", "Formulario", "Enlace wa.link", "Orgánico/otro"], lambda c: c.origen)
    bloque("Por interés (Opportunity/Lead: producto_tipo e interés, agrupado)", ["Terma", "Secadora", "Cocina", "Otros", "Sin dato"], lambda c: c.interes)
    bloque("Por día de la semana del primer mensaje (Lima)", list(DIAS), lambda c: DIAS[a_lima(c.primer_msg).weekday()] if c.primer_msg else None)
    bloque("Por franja horaria del primer mensaje (Lima)", list(FRANJAS), lambda c: franja_de(c.primer_msg) if c.primer_msg else None)
    return L, {}


# ── Sección 3: velocidad ────────────────────────────────────────────────────────────────────────

def seccion_velocidad(d: Datos) -> tuple[list[str], dict]:
    leads = [c for c in d.leads if not c.postventa]
    der = [c for c in leads if c.derivado]
    L = titulo(3, "VELOCIDAD")
    L.append("Lectura: cuánto tarda cada paso y si la rapidez de la primera respuesta humana acompaña (sin afirmar causa) a más agendados y ventas.")
    L.append(f"Base: {len(leads)} leads (sin postventa); {len(der)} derivados.")
    m: dict = {"n_der": len(der)}
    if not leads:
        return L, m

    gabi = []
    for c in leads:
        if c.primer_cliente is not None:
            g = next((x.ts for x in c.msgs if x.tipo == "g" and x.ts >= c.primer_cliente), None)
            if g is not None:
                gabi.append((g - c.primer_cliente).total_seconds())
    a_deriv = [
        (c.derivacion_ts - c.primer_cliente).total_seconds() for c in der
        if c.derivacion_ts is not None and c.primer_cliente is not None and c.derivacion_ts >= c.primer_cliente
    ]
    humana = [c.espera_humana for c in der if c.espera_humana is not None]
    desde_deriv = [c.espera_desde_derivacion for c in der if c.espera_desde_derivacion is not None]
    L.append("")
    L.append("Percentiles de tiempo:")
    L += tabla(["Medida", "n", "p50", "p75", "p90"], [
        fila_percentiles("Primer mensaje del cliente → 1.ª respuesta de Gabi", gabi),
        fila_percentiles("Primer mensaje del cliente → derivación", a_deriv),
        fila_percentiles("Último mensaje del cliente previo → 1.ª respuesta humana (derivados)", humana),
        fila_percentiles("Derivación → 1.ª respuesta humana (derivados con hora de derivación)", desde_deriv),
    ])
    L.append("  La hora de derivación sale del evento de asignación automática, del aviso de derivación o del aviso sin IA; los casos viejos sin esos rastros no entran en las filas que la usan.")

    def tabla_buckets(nombre: str, tiempo_de) -> dict:
        grupos: dict[str, list[Ciclo]] = defaultdict(list)
        sin_dato = 0
        for c in der:
            if not c.humano:
                grupos["nunca"].append(c)
                continue
            t = tiempo_de(c)
            if t is None:
                sin_dato += 1
                continue
            grupos[bucket_de(t)].append(c)
        L.append("")
        L.append(nombre)
        filas = []
        for b in BUCKETS_ESPERA:
            cs = grupos.get(b, [])
            filas.append([b, len(cs), pct(sum(c.exito for c in cs), len(cs)), pct(sum(c.resultado == "vendido" for c in cs), len(cs)),
                          pct(sum(c.resultado == "sin_respuesta" for c in cs), len(cs))])
        L.extend(tabla(["1.ª respuesta humana", "n", "% agend+vend", "% vendido", "% sin_respuesta"], filas))
        if sin_dato:
            L.append(f"  {sin_dato} derivados con mensaje humano quedan fuera por no tener la referencia de tiempo.")
        return {b: grupos.get(b, []) for b in BUCKETS_ESPERA}

    por_espera = tabla_buckets("Tasa de resultado según el tiempo desde el último mensaje del cliente hasta la 1.ª respuesta humana (derivados):", lambda c: c.espera_humana)
    tabla_buckets("Mismo cuadro medido desde la hora de derivación (solo derivados con hora conocida; 'nunca' incluye a todos los sin mensaje humano):", lambda c: c.espera_desde_derivacion)
    L.append("  'nunca' = ningún mensaje humano registrado: puede haber atención por llamada fuera del sistema (esos casos igual figuran con resultado si el asesor lo marcó).")

    # Ventana de 24 h
    tarde = 0
    sin_nunca_cerrada = 0
    sin_nunca_abierta = 0
    base = 0
    for c in der:
        if c.humano:
            if c.espera_humana is None:
                continue
            base += 1
            if c.espera_humana > HORAS_VENTANA * 3600:
                tarde += 1
        else:
            ult = c.ultimo_cliente()
            if ult is None:
                continue
            base += 1
            if (d.ahora - ult).total_seconds() > HORAS_VENTANA * 3600:
                sin_nunca_cerrada += 1
            else:
                sin_nunca_abierta += 1
    cerro = tarde + sin_nunca_cerrada
    L.append("")
    L.append("Ventana de 24 h de WhatsApp (derivados con referencia de tiempo):")
    L += tabla(["Situación", "n", "% de derivados"], [
        ["Primera respuesta humana llegó con la ventana ya cerrada (>24 h)", tarde, pct(tarde, base)],
        ["Sin respuesta humana y la ventana ya cerró", sin_nunca_cerrada, pct(sin_nunca_cerrada, base)],
        ["Ventana cerró antes de la 1.ª respuesta humana (suma)", cerro, pct(cerro, base)],
        ["Sin respuesta humana pero la ventana sigue abierta", sin_nunca_abierta, pct(sin_nunca_abierta, base)],
    ])

    # Por franja del mensaje que quedó esperando
    grupos: dict[str, list[Ciclo]] = defaultdict(list)
    for c in der:
        ref = c.inicio_espera()
        if ref is not None:
            grupos[franja_de(ref)].append(c)
    L.append("")
    L.append("Derivados por franja horaria (Lima) del mensaje del cliente que quedó esperando:")
    filas = []
    franja_stats = {}
    for f in FRANJAS:
        cs = grupos.get(f, [])
        rapido = sum(1 for c in cs if c.humano and c.espera_humana is not None and c.espera_humana < 3600)
        lento = sum(1 for c in cs if (not c.humano) or (c.espera_humana is not None and c.espera_humana >= 12 * 3600))
        franja_stats[f] = (len(cs), rapido, lento)
        filas.append([f, len(cs), pct(rapido, len(cs)), pct(lento, len(cs)), pct(sum(c.exito for c in cs), len(cs))])
    L += tabla(["Franja", "n", "% atendido <1 h", "% nunca o >12 h", "% agend+vend"], filas)

    m.update({
        "buckets": {b: (len(cs), sum(c.exito for c in cs)) for b, cs in por_espera.items()},
        "ventana": {"cerro": cerro, "base": base, "tarde": tarde, "nunca_cerrada": sin_nunca_cerrada},
        "franja": franja_stats,
    })
    return L, m


# ── Sección 4: reenganche y silencio ────────────────────────────────────────────────────────────

def _respuestas(c: Ciclo, desde_ts: datetime) -> list[datetime]:
    return [t for t in c.clientes() if t > desde_ts]


def _primer_silencio_sin_reenganche(c: Ciclo) -> datetime | None:
    """Fin hipotético del silencio de control: el primer hueco >= 2 h del cliente, ya respondido por Gabi, sin
    humano de por medio y antes de cualquier derivación. Devuelve el instante en que habría salido el reenganche."""
    clientes = c.clientes()
    umbral = timedelta(hours=HORAS_SILENCIO_REENGANCHE)
    for i, t in enumerate(clientes):
        siguiente = clientes[i + 1] if i + 1 < len(clientes) else None
        if siguiente is not None and siguiente - t < umbral:
            continue
        if not any(m.tipo == "g" and m.ts > t for m in c.msgs):
            continue
        if c.primer_humano is not None and c.primer_humano < t + umbral:
            continue
        if c.derivacion_ts is not None and c.derivacion_ts < t + umbral:
            continue
        if c.derivacion_ts is None and c.derivado:
            continue  # derivado sin hora conocida: no se puede asegurar que estuviera sin derivar
        return t + umbral
    return None


def _etapa_sin_respuesta(c: Ciclo) -> str:
    gabis = [m for m in c.msgs if m.tipo == "g"]
    if not gabis:
        return "Sin ningún mensaje de Gabi"
    ultimo = gabis[-1]
    if ultimo.dni or (ultimo.financ and ultimo.pregunta):
        return "Tras pedir DNI / preguntar financiamiento"
    if ultimo.precio:
        return "Tras dar precio"
    if len(gabis) == 1:
        return "Después del primer saludo"
    if ultimo.nombre:
        return "Tras pedir el nombre"
    return "Tras otra respuesta de Gabi"


def seccion_reenganche(d: Datos) -> tuple[list[str], dict]:
    ciclos = [c for c in d.en_rango if not c.postventa]
    L = titulo(4, "REENGANCHE Y SILENCIO")
    L.append("Lectura: si el mensaje automático \"Hola de nuevo\" recupera conversaciones frente a casos comparables sin él, y en qué etapa se enfría el 'sin_respuesta'.")
    m: dict = {}
    if not ciclos:
        L.append("  Sin ciclos en el período.")
        return L, m

    tratados = [c for c in ciclos if c.reenganche_ts is not None]
    bloqueados = [c for c in ciclos if c.reenganche_bloqueado_ts is not None]
    controles = []
    for c in ciclos:
        if c.reenganche_ts is not None or c.reenganche_bloqueado_ts is not None:
            continue
        t = _primer_silencio_sin_reenganche(c)
        if t is not None:
            controles.append((c, t))
    grupos = [
        ("Con reenganche enviado", [(c, c.reenganche_ts) for c in tratados]),
        ("Control A: reenganche bloqueado por la política", [(c, c.reenganche_bloqueado_ts) for c in bloqueados]),
        ("Control B: silencio >=2 h sin reenganche", controles),
    ]
    filas = []
    for etiqueta, pares in grupos:
        el24 = [(c, t) for c, t in pares if t + timedelta(hours=24) <= d.ahora]
        el72 = [(c, t) for c, t in pares if t + timedelta(hours=72) <= d.ahora]
        r24 = sum(1 for c, t in el24 if any(x <= t + timedelta(hours=24) for x in _respuestas(c, t)))
        r72 = sum(1 for c, t in el72 if any(x <= t + timedelta(hours=72) for x in _respuestas(c, t)))
        cs = [c for c, _ in pares]
        filas.append([
            etiqueta, len(pares), len(el24), pct(r24, len(el24)), len(el72), pct(r72, len(el72)),
            pct(sum(c.exito for c in cs), len(cs)), pct(sum(c.resultado == "sin_respuesta" for c in cs), len(cs)),
        ])
        m[etiqueta] = (len(pares), len(el24), r24, len(el72), r72, sum(c.exito for c in cs))
    L.append("")
    L.append("Respuesta del cliente tras el reenganche (o tras el instante en que se habría enviado, en los controles):")
    L += tabla(["Grupo", "n", "n 24h", "% resp. 24 h", "n 72h", "% resp. 72 h", "% agend+vend final", "% sin_resp. final"], filas)
    L.append("  Solo cuentan los casos con la ventana de medición completa (24 h / 72 h ya transcurridas). Un 'respondió' es cualquier mensaje del cliente que no sea una reacción.")
    L.append("  Los controles no son aleatorios: Control A (política de costo lo frenó) es el más comparable; Control B incluye casos anteriores al Cron o fuera de su alcance.")

    # Etapa en que se queda 'sin_respuesta'
    sr = [c for c in ciclos if c.resultado == "sin_respuesta"]
    L.append("")
    L.append(f"Etapa en que queda el 'sin_respuesta' (n={len(sr)}; por reglas sobre el último mensaje de Gabi, sin imprimirlo):")
    etapas = Counter(_etapa_sin_respuesta(c) for c in sr)
    L += tabla(["Etapa", "n", "% de sin_respuesta"], [[e, k, pct(k, len(sr))] for e, k in etapas.most_common()])
    L.append("  Criterio: DNI o pregunta de financiamiento > precio (S/) > primer saludo (1 solo mensaje de Gabi) > pedir nombre > otra respuesta.")
    nunca = sum(1 for c in sr if not c.respondio)
    L.append("")
    L += tabla(["Cliente en los sin_respuesta", "n", "%"], [
        ["Nunca respondió después del primer mensaje de Gabi", nunca, pct(nunca, len(sr))],
        ["Respondió al menos una vez y luego se enfrió", len(sr) - nunca, pct(len(sr) - nunca, len(sr))],
    ])
    pasos = Counter((c.paso_flujo or (c.lead_paso_flujo if c.es_ultimo else None) or "sin paso") for c in sr)
    L.append("")
    L.append("Paso del flujo en que quedó (paso_flujo):")
    L += tabla(["Paso", "n", "% de sin_respuesta"], [[p, k, pct(k, len(sr))] for p, k in pasos.most_common()])
    m["sin_resp"] = {"n": len(sr), "etapas": dict(etapas), "nunca": nunca, "total_ciclos": len(ciclos), "derivados": sum(1 for c in sr if c.derivado)}
    return L, m


# ── Sección 5: mensajes de Gabi y respuesta del cliente ─────────────────────────────────────────

def turnos_de_gabi(c: Ciclo, ahora: datetime) -> list[dict]:
    """Un 'turno' = bloque de mensajes seguidos de Gabi. Devuelve los que se pueden evaluar: largo total, ** en cualquiera,
    pregunta en el último mensaje, número de turno y si el cliente respondió en las 24 h siguientes."""
    relevantes = [m for m in c.msgs if m.tipo in ("c", "g", "h")]  # reacciones, errores y reenganches no cuentan
    turnos: list[dict] = []
    i = 0
    numero = 0
    while i < len(relevantes):
        m = relevantes[i]
        if m.tipo == "h":
            break  # Gabi queda en pausa: lo que sigue ya no es de Gabi
        if m.tipo != "g":
            i += 1
            continue
        j = i
        while j + 1 < len(relevantes) and relevantes[j + 1].tipo == "g":
            j += 1
        bloque = relevantes[i:j + 1]
        siguiente = relevantes[j + 1] if j + 1 < len(relevantes) else None
        numero += 1
        ultimo = bloque[-1]
        incluir = True
        if siguiente is not None and siguiente.tipo == "h":
            incluir = False
        if siguiente is None and (ahora - ultimo.ts).total_seconds() < 24 * 3600:
            incluir = False  # todavía puede responder
        # Último turno de Gabi de un caso derivado = aviso de derivación (con o sin respuesta del cliente)
        es_final_de_derivado = c.derivado and not any(x.tipo == "g" for x in relevantes[j + 1:])
        if es_final_de_derivado or (c.derivacion_ts is not None and ultimo.ts >= c.derivacion_ts - timedelta(seconds=120)):
            incluir = False  # aviso de derivación: su "respuesta" no mide el texto
        if incluir:
            respondio = siguiente is not None and siguiente.tipo == "c" and (siguiente.ts - ultimo.ts).total_seconds() <= 24 * 3600
            turnos.append({
                "largo": sum(x.largo for x in bloque), "negrita": any(x.negrita for x in bloque), "pregunta": ultimo.pregunta,
                "turno": numero, "anuncio": c.origen == "Anuncio CTWA", "respondio": respondio,
            })
        i = j + 1
    return turnos


def _rango_largo(n: int) -> str:
    if n <= 200:
        return "<=200"
    if n <= 350:
        return "201-350"
    if n <= 500:
        return "351-500"
    return ">500"


RANGOS_LARGO = ("<=200", "201-350", "351-500", ">500")


def seccion_gabi(d: Datos) -> tuple[list[str], dict]:
    L = titulo(5, "GABI Y RESPUESTA DEL CLIENTE")
    L.append("Lectura: tasa de respuesta del cliente en las 24 h siguientes a un turno de Gabi, por forma del mensaje; la tabla cruzada separa longitud de pregunta.")
    turnos = []
    for c in d.en_rango:
        if not c.postventa:
            turnos += turnos_de_gabi(c, d.ahora)
    L.append(f"Base: {len(turnos)} turnos de Gabi evaluables (todos los ciclos). Turno = mensajes seguidos de Gabi; se excluyen avisos de derivación, turnos tras tomar un humano y turnos con <24 h sin respuesta.")
    if not turnos:
        L.append("  Sin turnos evaluables.")
        return L, {}

    def celda(ts: list[dict]) -> str:
        return pct(sum(t["respondio"] for t in ts), len(ts))

    def bloque(nombre: str, orden: list[str], clave) -> None:
        g: dict[str, list[dict]] = defaultdict(list)
        for t in turnos:
            g[clave(t)].append(t)
        L.append("")
        L.append(nombre + ":")
        L.extend(tabla(["Grupo", "n", "% respondió"], [[k, len(g[k]), celda(g[k])] for k in orden if k in g]))

    bloque("Por longitud del turno (caracteres)", list(RANGOS_LARGO), lambda t: _rango_largo(t["largo"]))
    bloque("Contiene ** (formato crudo)", ["Con **", "Sin **"], lambda t: "Con **" if t["negrita"] else "Sin **")
    bloque("Termina en pregunta (? en los últimos 80 caracteres)", ["Con pregunta", "Sin pregunta"], lambda t: "Con pregunta" if t["pregunta"] else "Sin pregunta")
    bloque("Número de turno de Gabi", ["1.º", "2.º", "3.º o más"], lambda t: "1.º" if t["turno"] == 1 else ("2.º" if t["turno"] == 2 else "3.º o más"))
    bloque(
        "Primer mensaje de Gabi según el origen del lead", ["A lead de anuncio", "A otro lead"],
        lambda t: None if t["turno"] != 1 else ("A lead de anuncio" if t["anuncio"] else "A otro lead"),
    ) if any(t["turno"] == 1 for t in turnos) else None

    # Cruzada longitud x pregunta
    L.append("")
    L.append("Tabla cruzada longitud × pregunta final (cada celda: % respondió con n):")
    filas = []
    for r in RANGOS_LARGO:
        fila = [r]
        for q in (True, False):
            ts = [t for t in turnos if _rango_largo(t["largo"]) == r and t["pregunta"] == q]
            fila.append(f"{celda(ts)} (n={len(ts)})")
        filas.append(fila)
    L += tabla(["Longitud", "Con pregunta", "Sin pregunta"], filas)
    L.append("")
    L.append("Tabla cruzada ** × pregunta final:")
    filas = []
    for etiqueta, neg in (("Con **", True), ("Sin **", False)):
        fila = [etiqueta]
        for q in (True, False):
            ts = [t for t in turnos if t["negrita"] == neg and t["pregunta"] == q]
            fila.append(f"{celda(ts)} (n={len(ts)})")
        filas.append(fila)
    L += tabla(["Formato", "Con pregunta", "Sin pregunta"], filas)
    con_q = [t for t in turnos if t["pregunta"]]
    sin_q = [t for t in turnos if not t["pregunta"]]
    return L, {"con_q": (sum(t["respondio"] for t in con_q), len(con_q)), "sin_q": (sum(t["respondio"] for t in sin_q), len(sin_q))}


# ── Sección 6: asesores ─────────────────────────────────────────────────────────────────────────

def seccion_asesores(d: Datos) -> tuple[list[str], dict]:
    L = titulo(6, "ASESORES  —  USO INTERNO DEL DUEÑO (no compartir con el equipo)")
    L.append("Lectura: carga, rapidez y resultado por cuenta de personal; la atribución es al asesor que tiene el caso al final del ciclo.")
    leads = [c for c in d.leads if not c.postventa]
    por_asesor: dict[str, list[Ciclo]] = defaultdict(list)
    sin_asesor = 0
    for c in leads:
        if c.asesor:
            por_asesor[c.asesor].append(c)
        else:
            sin_asesor += 1
    L.append(f"Leads con asesor: {sum(len(v) for v in por_asesor.values())}; sin asesor al cierre del período: {sin_asesor}.")
    L.append("")
    filas = []
    for a in sorted(por_asesor, key=lambda x: -len(por_asesor[x])):
        cs = por_asesor[a]
        esperas = sorted(c.espera_humana for c in cs if c.espera_humana is not None)
        rol, nivel = d.usuarios.get(a, ("?", None))
        filas.append([
            a, rol + (f"/{nivel}" if nivel else ""), len(cs), pct(sum(c.humano for c in cs), len(cs)),
            fmt_dur(percentil(esperas, 0.5)) if len(esperas) >= LIMITE_N else "n<10",
            pct(sum(c.exito for c in cs), len(cs)), pct(sum(c.resultado == "sin_respuesta" for c in cs), len(cs)),
        ])
    if filas:
        L += tabla(["Asesor", "Rol/nivel", "Leads asignados", "% con resp. humana", "p50 1.ª resp.", "% agend+vend", "% sin_respuesta"], filas)
    else:
        L.append("  Sin leads asignados a un asesor en el período.")

    L.append("")
    L.append("Mensajes enviados desde el panel por asesor (capa de envíos; solo el período):")
    tipos = ["texto", "imagen", "documento", "audio", "plantilla"]
    acum: dict[str, Counter] = defaultdict(Counter)
    fallidos: Counter = Counter()
    for asesor, tipo, decision, n in d.envios_panel:
        if decision == "enviado":
            acum[asesor][tipo] += n
        else:
            fallidos[asesor] += n
    if acum or fallidos:
        filas = [
            [a] + [acum[a].get(t, 0) for t in tipos] + [sum(acum[a].values()), fallidos.get(a, 0)]
            for a in sorted(set(acum) | set(fallidos), key=lambda x: -sum(acum[x].values()))
        ]
        L += tabla(["Asesor"] + tipos + ["Total enviados", "No enviados"], filas)
    else:
        L.append("  Sin envíos atribuidos a un asesor en el período (la atribución existe desde 2026-10-05).")
    echos = sum(1 for c in d.en_rango for m in c.msgs if m.tipo == "h" and m.via_app)
    panel = sum(1 for c in d.en_rango for m in c.msgs if m.tipo == "h" and not m.via_app)
    L.append(f"  Mensajes humanos en los ciclos del período: {panel} desde el panel y {echos} desde el celular (coexistencia, sin atribución a una persona).")
    return L, {}


# ── Sección 7: cierres y reaperturas ────────────────────────────────────────────────────────────

def seccion_cierres(d: Datos) -> tuple[list[str], dict]:
    L = titulo(7, "CIERRES Y REAPERTURAS")
    L.append("Lectura: cuántos clientes vuelven tras un cierre, qué pasa en el ciclo reabierto y cómo se cierran los casos.")
    ciclos = d.en_rango
    if not ciclos:
        L.append("  Sin ciclos en el período.")
        return L, {}
    reabiertos = [c for c in ciclos if any(e[0] == "reabierto_por_cliente" for e in c.eventos)]
    por_cliente: Counter = Counter()
    for c in d.ciclos:  # todos los ciclos del contacto, aunque el evento sea anterior al período
        por_cliente[(c.negocio_id, c.telefono)] += sum(1 for e in c.eventos if e[0] == "reabierto_por_cliente")
    clientes_con = [k for k in {(c.negocio_id, c.telefono) for c in ciclos} if por_cliente[k] > 0]
    sucesivos = 0
    por_contacto: dict[tuple, list[Ciclo]] = defaultdict(list)
    for c in d.ciclos:
        por_contacto[(c.negocio_id, c.telefono)].append(c)
    for lista in por_contacto.values():
        lista.sort(key=lambda x: x.creado)
        sucesivos += sum(1 for c in lista[1:] if c.en_rango)
    L.append(f"Ciclos en el período: {len(ciclos)}; ciclos que son una nueva conversación de un cliente anterior: {sucesivos}; con evento de reapertura registrado: {len(reabiertos)}.")
    L.append("  El evento existe desde 2026-10-06 (y el backfill); los ciclos sucesivos sin evento son reaperturas anteriores o vueltas de ventas (postventa).")
    L.append("")
    L.append("Veces que un cliente fue reabierto por el cliente (clientes con ciclo en el período):")
    dist = Counter(min(por_cliente[k], 3) for k in clientes_con)
    L += tabla(["Reaperturas del cliente", "Clientes"], [["1", dist.get(1, 0)], ["2", dist.get(2, 0)], ["3 o más", dist.get(3, 0)]])

    L.append("")
    L.append("Resultado del ciclo reabierto según el resultado anterior:")
    grupos: dict[str, list[Ciclo]] = defaultdict(list)
    for c in reabiertos:
        ev = next(e for e in c.eventos if e[0] == "reabierto_por_cliente")
        grupos[(ev[2] or {}).get("resultado_anterior") or "sin resultado"].append(c)
    if grupos:
        filas = [[k, len(v), pct(sum(c.exito for c in v), len(v)), pct(sum(c.resultado == "sin_respuesta" for c in v), len(v)),
                  pct(sum(1 for c in v if c.humano), len(v))] for k, v in sorted(grupos.items(), key=lambda kv: -len(kv[1]))]
        filas.append(["TODOS los reabiertos", len(reabiertos), pct(sum(c.exito for c in reabiertos), len(reabiertos)),
                      pct(sum(c.resultado == "sin_respuesta" for c in reabiertos), len(reabiertos)),
                      pct(sum(1 for c in reabiertos if c.humano), len(reabiertos))])
        L += tabla(["Resultado anterior", "n", "% agend+vend", "% sin_respuesta", "% msg humano"], filas)
    else:
        L.append("  Ningún ciclo con evento de reapertura en el período.")
    primeros = [c for c in ciclos if not any(e[0] == "reabierto_por_cliente" for e in c.eventos)]
    L.append(f"  Referencia — ciclos sin reapertura: {len(primeros)}; % agend+vend {pct(sum(c.exito for c in primeros), len(primeros))}.")

    L.append("")
    L.append("Cierres definitivos de los ciclos del período:")
    manual = [e for c in ciclos for e in c.eventos if e[0] == "cerrado_definitivamente"]
    auto = [e for c in ciclos for e in c.eventos if e[0] == "cerrado_definitivamente_automatico"]
    con_evento = {c.id for c in ciclos if any(e[0].startswith("cerrado_definitivamente") for e in c.eventos)}
    sin_evento = sum(1 for c in ciclos if c.cerrado_def_en is not None and c.id not in con_evento)
    L += tabla(["Tipo", "n", "% de ciclos"], [
        ["Manual (botón de la ficha)", len(manual), pct(len(manual), len(ciclos))],
        ["Automático (Cron de 7 días)", len(auto), pct(len(auto), len(ciclos))],
        ["Cerrado definitivamente sin evento (datos viejos)", sin_evento, pct(sin_evento, len(ciclos))],
    ])
    res = Counter()
    for tipo, lista in (("manual", manual), ("automático", auto)):
        for e in lista:
            res[(tipo, (e[2] or {}).get("resultado") or "sin resultado")] += 1
    if res:
        L.append("")
        L += tabla(["Tipo de cierre", "Resultado al cerrar", "n"], [[t, r, k] for (t, r), k in sorted(res.items(), key=lambda kv: -kv[1])])
    return L, {"reabiertos": len(reabiertos)}


# ── Sección 8: resumen ejecutivo ────────────────────────────────────────────────────────────────

def seccion_resumen(d: Datos, M: dict) -> list[str]:
    L = titulo(8, "RESUMEN EJECUTIVO")
    leads = d.leads
    if not leads:
        L.append("Sin leads en el período: no hay hechos que resumir.")
        return L
    vel = M.get("velocidad", {})
    emb = M.get("embudo", {})
    n, n_der = len(leads), emb.get("derivados", 0)
    L.append(
        f"Base: {n} leads del {a_lima(d.desde).date().isoformat()} al {a_lima(d.hasta - timedelta(seconds=1)).date().isoformat()}; "
        f"{n_der} derivados ({pct(n_der, n)}); agendado+vendido {emb.get('exito', 0)} ({pct(emb.get('exito', 0), n)} de los leads, {pct(emb.get('exito_der', 0), n_der)} de los derivados)."
    )
    candidatos: list[tuple[int, list[str]]] = []

    # 1. Atención humana tardía o inexistente
    b = vel.get("buckets", {})
    if b and vel.get("n_der", 0) > 0:
        nunca, nunca_ex = b.get("nunca", (0, 0))
        lento = sum(b.get(k, (0, 0))[0] for k in ("4-12 h", ">12 h"))
        lento_ex = sum(b.get(k, (0, 0))[1] for k in ("4-12 h", ">12 h"))
        rapido = sum(b.get(k, (0, 0))[0] for k in ("<15 min", "15-60 min"))
        rapido_ex = sum(b.get(k, (0, 0))[1] for k in ("<15 min", "15-60 min"))
        mal = nunca + lento
        mal_ex = nunca_ex + lento_ex
        candidatos.append((mal, [
            f"Atención humana: {nunca} de {vel['n_der']} derivados ({pct(nunca, vel['n_der'])}) no tienen ningún mensaje humano registrado y {lento} ({pct(lento, vel['n_der'])}) esperaron más de 4 h.",
            f"  Los atendidos en <1 h (n={rapido}) figuran con agendado+vendido {pct(rapido_ex, rapido)} vs {pct(mal_ex, mal)} en los de >4 h o nunca (n={mal}); descriptivo, sin causa probada.",
        ]))

    # 2. Ventana de 24 h
    v = vel.get("ventana")
    if v and v["base"] > 0:
        candidatos.append((v["cerro"], [
            f"Ventana de 24 h: en {v['cerro']} de {v['base']} derivados ({pct(v['cerro'], v['base'])}) la ventana cerró antes de la primera respuesta humana ({v['tarde']} respondidos tarde, {v['nunca_cerrada']} sin respuesta).",
            "  Quien llega con la ventana cerrada solo se puede contactar con plantilla (con costo) o por llamada.",
        ]))

    # 3. Silencio tras Gabi
    sr = M.get("reenganche", {}).get("sin_resp")
    if sr and sr["n"] > 0:
        etapa, k = max(sr["etapas"].items(), key=lambda kv: kv[1])
        candidatos.append((sr["n"], [
            f"Silencio: {sr['n']} ciclos ({pct(sr['n'], sr['total_ciclos'])}) terminaron en sin_respuesta; la etapa más frecuente es '{etapa}' ({k}, {pct(k, sr['n'])}) y {sr['nunca']} ({pct(sr['nunca'], sr['n'])}) nunca contestó tras el primer mensaje de Gabi.",
            f"  De esos, {sr['derivados']} ({pct(sr['derivados'], sr['n'])}) ya estaban derivados a un asesor; el resto se enfrió antes de llegar a una persona.",
        ]))

    # 4. Reenganche
    rg = M.get("reenganche", {})
    tr = rg.get("Con reenganche enviado")
    ca = rg.get("Control A: reenganche bloqueado por la política")
    cb = rg.get("Control B: silencio >=2 h sin reenganche")
    ctrl = ca if ca and ca[1] >= LIMITE_N else cb
    if tr and ctrl and tr[0] > 0:
        nombre_ctrl = "bloqueados por política" if ctrl is ca and ca and ca[1] >= LIMITE_N else "silencio >=2 h sin reenganche"
        candidatos.append((tr[0] + ctrl[0], [
            f"Reenganche: respondió en 24 h el {pct(tr[2], tr[1])} de los reenganchados (n={tr[1]}) vs {pct(ctrl[2], ctrl[1])} del control '{nombre_ctrl}' (n={ctrl[1]}).",
            "  Comparación observacional (controles no aleatorios).",
        ]))

    # 5. Franja horaria
    fr = vel.get("franja", {})
    peores = [(f, s) for f, s in fr.items() if s[0] >= LIMITE_N]
    if peores:
        f, s = min(peores, key=lambda x: x[1][1] / x[1][0])
        candidatos.append((s[0] - s[1], [
            f"Franja: los derivados cuyo mensaje quedó esperando en '{f}' se atienden en <1 h el {pct(s[1], s[0])} (n={s[0]}); {pct(s[2], s[0])} nunca o tras >12 h.",
            "  Mapa de dónde falta cobertura horaria.",
        ]))

    candidatos.sort(key=lambda x: -x[0])
    for i, (_, lineas) in enumerate(candidatos[:3], 1):
        L.append(f"Palanca {i}. " + lineas[0])
        L.append(lineas[1])
    if not candidatos:
        L.append("No hay datos suficientes (n<10) para identificar palancas.")
    L.append("Lectura: hechos descriptivos con su n; no demuestran causalidad (los leads que avanzan reciben más contacto humano por construcción).")
    return L


# ── Orquestación ────────────────────────────────────────────────────────────────────────────────

def normalizar_secciones(solo: list[str] | None) -> list[str]:
    if not solo:
        return list(SECCIONES)
    pedidas: list[str] = []
    for token in ",".join(solo).replace(" ", ",").split(","):
        token = token.strip().lower()
        if not token:
            continue
        if token.isdigit() and 1 <= int(token) <= len(SECCIONES):
            token = SECCIONES[int(token) - 1]
        if token not in SECCIONES:
            raise ValueError(f"Sección desconocida: {token!r}. Opciones: {', '.join(SECCIONES)}")
        if token not in pedidas:
            pedidas.append(token)
    return [s for s in SECCIONES if s in pedidas]


def rango_utc(desde: str, hasta: str | None, ahora: datetime) -> tuple[datetime, datetime]:
    """`desde`/`hasta`: fechas AAAA-MM-DD de Lima, ambas inclusivas. Devuelve [desde, hasta) en UTC naive."""
    d = datetime.strptime(desde, "%Y-%m-%d")
    h = datetime.strptime(hasta, "%Y-%m-%d") if hasta else datetime.combine(a_lima(ahora).date(), datetime.min.time())
    if h < d:
        raise ValueError("--hasta no puede ser anterior a --desde")
    return lima_a_utc(d), lima_a_utc(h + timedelta(days=1))


async def generar_informe(desde: str = DESDE_POR_DEFECTO, hasta: str | None = None, solo: list[str] | None = None, ahora: datetime | None = None) -> list[str]:
    ahora = ahora or datetime.now(timezone.utc).replace(tzinfo=None)
    secciones = normalizar_secciones(solo)
    ini, fin = rango_utc(desde, hasta, ahora)
    async with async_session() as session:
        datos = await cargar_datos(session, ini, fin, ahora)
        await session.rollback()  # lectura pura: nada que confirmar
    M: dict = {}
    bloques: dict[str, list[str]] = {}
    for nombre, f in (("embudo", seccion_embudo), ("origen", seccion_origen), ("velocidad", seccion_velocidad),
                      ("reenganche", seccion_reenganche), ("gabi", seccion_gabi), ("asesores", seccion_asesores), ("cierres", seccion_cierres)):
        if nombre not in secciones and "resumen" not in secciones:
            continue
        lineas, m = f(datos)
        bloques[nombre] = lineas
        M[nombre] = m
    cabecera = [
        "ANÁLISIS DE CONVERSIÓN — solo lectura",
        f"Período (Lima): {desde} a {hasta or a_lima(ahora).date().isoformat()}  |  generado {a_lima(ahora).strftime('%Y-%m-%d %H:%M')} (Lima)",
        f"Ciclos (conversaciones) en el período: {len(datos.en_rango)}  |  leads únicos: {len(datos.leads)}  |  n<10 = muestra muy chica, sin porcentaje.",
    ]
    salida = list(cabecera)
    for nombre in secciones:
        if nombre == "resumen":
            salida += seccion_resumen(datos, M)
        else:
            salida += bloques[nombre]
    return salida


async def main_async(args) -> None:
    await esperar_base_de_datos()
    print(f"Base de datos: {engine.url.get_backend_name()} / {engine.url.database}")
    for linea in await generar_informe(args.desde, args.hasta, args.solo):
        print(linea)


def _fecha(valor: str) -> str:
    try:
        datetime.strptime(valor, "%Y-%m-%d")
    except ValueError:
        raise argparse.ArgumentTypeError(f"fecha inválida {valor!r}: usa AAAA-MM-DD")
    return valor


def construir_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Análisis de conversión (solo lectura).")
    p.add_argument("--desde", type=_fecha, default=DESDE_POR_DEFECTO, help=f"Primer día (Lima, inclusive). Default {DESDE_POR_DEFECTO}.")
    p.add_argument("--hasta", type=_fecha, default=None, help="Último día (Lima, inclusive). Default: hoy.")
    p.add_argument("--solo", nargs="+", default=None, help=f"Secciones: {', '.join(SECCIONES)} (o 1-8).")
    return p


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass
    argumentos = construir_parser().parse_args()
    try:
        normalizar_secciones(argumentos.solo)
        asyncio.run(main_async(argumentos))
    except Exception as e:
        print(f"ERROR: análisis de conversión falló — {e}", file=sys.stderr)
        sys.exit(1)
