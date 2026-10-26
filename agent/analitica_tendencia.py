# agent/analitica_tendencia.py — cómo se parte un período de Analítica para dibujar su tendencia.
#
# Función pura (sin base de datos): dado el período (días civiles AAAA-MM-DD, extremos inclusivos, hora de Lima) devuelve
# la granularidad y los tramos consecutivos que lo cubren SIN solaparse ni dejar huecos, de modo que la suma de lo que
# se cuente en cada tramo es exactamente lo que cuenta el período entero.

from __future__ import annotations

import calendar
from datetime import date, timedelta

# Hasta 14 días: un punto por día. Hasta 100 días: semanas de 7 días contadas desde el primer día del período (no
# semanas de calendario: así el primer tramo nunca queda a medias). Más: meses de calendario.
MAX_DIAS_POR_DIA = 14
MAX_DIAS_POR_SEMANA = 100
MAX_TRAMOS = 36


def _a_fecha(dia: str) -> date:
    return date.fromisoformat(dia)


def partir_periodo(desde: str, hasta: str) -> tuple[str, list[dict]]:
    """Devuelve `(granularidad, tramos)`. Cada tramo es `{desde, hasta, parcial}` (días AAAA-MM-DD inclusivos);
    `parcial` es True si el período lo recorta (menos de 7 días en una semana, o un mes que no está completo).

    Lanza `ValueError` si las fechas no son válidas, el rango está invertido o saldrían más de `MAX_TRAMOS` tramos."""
    d0, d1 = _a_fecha(desde), _a_fecha(hasta)
    if d1 < d0:
        raise ValueError("El período está invertido.")
    dias = (d1 - d0).days + 1

    tramos: list[dict] = []
    if dias <= MAX_DIAS_POR_DIA:
        granularidad = "dia"
        for i in range(dias):
            d = d0 + timedelta(days=i)
            tramos.append({"desde": d.isoformat(), "hasta": d.isoformat(), "parcial": False})
    elif dias <= MAX_DIAS_POR_SEMANA:
        granularidad = "semana"
        inicio = d0
        while inicio <= d1:
            fin = min(inicio + timedelta(days=6), d1)
            tramos.append({
                "desde": inicio.isoformat(), "hasta": fin.isoformat(), "parcial": (fin - inicio).days + 1 < 7,
            })
            inicio = fin + timedelta(days=1)
    else:
        granularidad = "mes"
        inicio = d0
        while inicio <= d1:
            ultimo_del_mes = date(inicio.year, inicio.month, calendar.monthrange(inicio.year, inicio.month)[1])
            fin = min(ultimo_del_mes, d1)
            completo = inicio.day == 1 and fin == ultimo_del_mes
            tramos.append({"desde": inicio.isoformat(), "hasta": fin.isoformat(), "parcial": not completo})
            inicio = fin + timedelta(days=1)

    if len(tramos) > MAX_TRAMOS:
        raise ValueError(f"El período abarca más de {MAX_TRAMOS} tramos; acórtalo.")
    return granularidad, tramos
