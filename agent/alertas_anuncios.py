"""Aviso «los anuncios dejaron de traer clientes» (mejora #1, 2026-11-05).

Motivo: el 4-nov el número de Cálidda se desconectó de los anuncios de la agencia (el WABA se quedó
con 0 socios) y nadie en Maiek se enteró hasta que lo notó el dueño. Los leads de anuncios llegan por
el webhook con `referral.source_id`; esa evidencia ya se guarda en `attribution_events`. Aquí solo se
LEE esa tabla (sin migración, sin llamadas a Meta) y se compara lo reciente con lo normal.

Dos señales, ambas solo para el admin (las muestra `dashboard._avisos_inicio`):

1. Global (nivel `error`): en las últimas `VENTANA_GLOBAL_H` horas no entró ni un cliente de anuncios
   y a esa misma hora de los 7 días anteriores entraban, en promedio, al menos `ESPERADO_MIN_GLOBAL`.
   Se compara la misma franja horaria de días anteriores para que la noche tranquila no dispare nada.
2. Por anuncio (nivel `warning`): anuncios que traían clientes (≥ `MIN_PREVIOS_ANUNCIO` en los 7 días
   previos a las últimas 24 h) y en las últimas 24 h no trajeron ninguno. Puede ser una pausa a
   propósito de la agencia: el texto lo dice. Dejan de salir solos cuando pasa una semana sin tráfico.

Funciones puras (`evaluar_*`) + una lectura (`leer_eventos`) para poder probarlas sin base de datos."""
from __future__ import annotations

from datetime import datetime, timedelta

VENTANA_GLOBAL_H = 6
ESPERADO_MIN_GLOBAL = 4.0      # con 4 esperados, P(0 por azar) ≈ 1.8 %
DIAS_BASE = 7
MIN_PREVIOS_ANUNCIO = 10
MAX_ANUNCIOS_LISTADOS = 3


def _duracion(delta: timedelta) -> str:
    minutos = max(0, int(delta.total_seconds() // 60))
    if minutos < 60:
        return f"{minutos} min"
    if minutos < 48 * 60:
        horas, resto = divmod(minutos, 60)
        return f"{horas} h {resto} min" if resto else f"{horas} h"
    return f"{minutos // (24 * 60)} días"


def evaluar_silencio_global(eventos: list[dict], ahora: datetime) -> dict | None:
    """`eventos`: dicts con `conversation_id` y `creado` (UTC naive) de los últimos ~8 días.
    Cuenta conversaciones distintas por franja, no eventos (un reingreso no suma dos veces)."""
    ventana = timedelta(hours=VENTANA_GLOBAL_H)
    actuales = {e["conversation_id"] for e in eventos if ahora - ventana <= e["creado"] <= ahora}
    if actuales:
        return None
    total_previos = 0
    for d in range(1, DIAS_BASE + 1):
        fin = ahora - timedelta(days=d)
        total_previos += len({e["conversation_id"] for e in eventos if fin - ventana <= e["creado"] <= fin})
    esperado = total_previos / DIAS_BASE
    if esperado < ESPERADO_MIN_GLOBAL:
        return None
    ultimo = max((e["creado"] for e in eventos if e["creado"] <= ahora), default=None)
    desde = f" El último llegó hace {_duracion(ahora - ultimo)}." if ultimo else ""
    return {
        "id": "anuncios_sin_clientes", "nivel": "error",
        "titulo": f"Ningún cliente de anuncios en las últimas {VENTANA_GLOBAL_H} h",
        "detalle": (
            f"A esta hora suelen entrar unos {round(esperado)} en {VENTANA_GLOBAL_H} h.{desde} "
            "Revisa en Meta que el número siga asignado a la agencia y que los anuncios estén activos."
        ),
        "enlace": "/campanas",
    }


def evaluar_anuncios_callados(eventos: list[dict], ahora: datetime) -> dict | None:
    corte = ahora - timedelta(hours=24)
    base_desde = corte - timedelta(days=DIAS_BASE)
    previos: dict[str, set] = {}
    recientes: set[str] = set()
    titulo: dict[str, str] = {}
    for e in eventos:
        sid = e.get("source_id")
        if not sid or e["creado"] > ahora:
            continue
        if e["creado"] > corte:
            recientes.add(sid)
        elif e["creado"] >= base_desde:
            previos.setdefault(sid, set()).add(e["conversation_id"])
        if e.get("headline"):
            titulo[sid] = e["headline"]
    callados = sorted(
        ((len(convs), sid) for sid, convs in previos.items() if sid not in recientes and len(convs) >= MIN_PREVIOS_ANUNCIO),
        reverse=True,
    )
    if not callados:
        return None
    nombres = []
    for n, sid in callados[:MAX_ANUNCIOS_LISTADOS]:
        t = (titulo.get(sid) or f"anuncio {sid[-6:]}").strip()
        nombres.append(f"«{t[:40]}» ({n} en 7 días)")
    extra = f" y {len(callados) - MAX_ANUNCIOS_LISTADOS} más" if len(callados) > MAX_ANUNCIOS_LISTADOS else ""
    plural = len(callados) != 1
    return {
        "id": "anuncios_callados", "nivel": "warning",
        "titulo": f"{len(callados)} anuncio{'s' if plural else ''} que traía{'n' if plural else ''} clientes no {'han' if plural else 'ha'} traído ninguno en 24 h",
        "detalle": (
            f"{', '.join(nombres)}{extra}. Si la agencia los pausó a propósito, ignora este aviso; "
            "si no, revisa que el anuncio siga activo y apuntando al número."
        ),
        "enlace": "/campanas",
    }


async def leer_eventos(negocio_id: str, ahora: datetime) -> list[dict]:
    """Eventos de anuncios de los últimos 8 días (solo lectura)."""
    from sqlalchemy import select
    from agent import memory as mem

    desde = ahora - timedelta(days=DIAS_BASE + 1)
    async with mem.async_session() as session:
        filas = (await session.execute(
            select(mem.AttributionEvent.conversation_id, mem.AttributionEvent.source_id,
                   mem.AttributionEvent.headline, mem.AttributionEvent.creado)
            .where(
                mem.AttributionEvent.negocio_id == negocio_id,
                mem.AttributionEvent.tipo_origen.in_(mem._TIPOS_ORIGEN_ANUNCIO),
                mem.AttributionEvent.creado >= desde,
            )
        )).all()
    return [{"conversation_id": c, "source_id": s, "headline": h, "creado": t} for c, s, h, t in filas]


async def avisos(negocio_id: str, ahora: datetime | None = None) -> list[dict]:
    ahora = ahora or datetime.utcnow()
    eventos = await leer_eventos(negocio_id, ahora)
    if not eventos:
        return []  # negocio sin anuncios: nada que vigilar
    return [a for a in (evaluar_silencio_global(eventos, ahora), evaluar_anuncios_callados(eventos, ahora)) if a]
