# agent/analitica_metas.py — metas mensuales de Analítica (Etapa 3 del refinamiento, 2026-10-27).
#
# Funciones puras (sin base de datos): qué mes corresponde a un período, cuántos días lleva y el avance de una meta
# (ritmo diario, proyección lineal al cierre del mes y estado). La meta es del MES COMPLETO, en días de Lima.

from __future__ import annotations

import calendar
import re
from datetime import date

MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre", "noviembre",
         "diciembre"]
TIPOS_META = ("ventas", "valor")

_RE_MES = re.compile(r"^(\d{4})-(\d{2})$")


def validar_mes(mes: str) -> str:
    """`AAAA-MM` válido o `ValueError`."""
    m = _RE_MES.match(mes or "")
    if not m or not 1 <= int(m.group(2)) <= 12:
        raise ValueError("Mes inválido (se espera AAAA-MM).")
    return mes


def mes_de(dia: str) -> str:
    """`2026-10-25` → `2026-10`."""
    return validar_mes((dia or "")[:7])


def rango_del_mes(mes: str) -> tuple[str, str]:
    """Primer y último día del mes (AAAA-MM-DD, inclusivos)."""
    validar_mes(mes)
    anio, num = int(mes[:4]), int(mes[5:])
    return f"{mes}-01", f"{mes}-{calendar.monthrange(anio, num)[1]:02d}"


def nombre_mes(mes: str) -> str:
    validar_mes(mes)
    return MESES[int(mes[5:]) - 1]


def avance(objetivo: float, logrado: float, mes: str, hoy: str) -> dict:
    """Avance de una meta del mes `mes` vista el día `hoy` (AAAA-MM-DD, Lima).

    - Mes en curso: ritmo = logrado / días transcurridos (hoy incluido); proyección = ritmo × días del mes.
    - Mes ya cerrado: la proyección es lo logrado (no queda nada por proyectar).
    - Mes futuro: sin ritmo ni proyección.
    Estado: «cumplida» si ya se alcanzó, «en_ritmo» si la proyección llega, «por_debajo» si no, `None` en un mes futuro.
    """
    desde, hasta = rango_del_mes(mes)
    d_hoy, d_desde, d_hasta = date.fromisoformat(hoy), date.fromisoformat(desde), date.fromisoformat(hasta)
    dias_mes = (d_hasta - d_desde).days + 1
    if d_hoy < d_desde:
        transcurridos = 0
    elif d_hoy > d_hasta:
        transcurridos = dias_mes
    else:
        transcurridos = (d_hoy - d_desde).days + 1
    restantes = dias_mes - transcurridos

    if transcurridos == 0:
        ritmo, proyeccion = None, None
    elif restantes == 0:
        ritmo, proyeccion = logrado / dias_mes, float(logrado)
    else:
        ritmo = logrado / transcurridos
        proyeccion = ritmo * dias_mes

    faltan = max(0.0, objetivo - logrado)
    if logrado >= objetivo > 0:
        estado = "cumplida"
    elif proyeccion is None:
        estado = None
    elif proyeccion >= objetivo:
        estado = "en_ritmo"
    else:
        estado = "por_debajo"
    return {
        "objetivo": objetivo, "logrado": logrado, "faltan": faltan,
        "ritmo_diario": None if ritmo is None else round(ritmo, 3),
        "proyeccion": None if proyeccion is None else round(proyeccion, 1),
        "dias_mes": dias_mes, "dias_transcurridos": transcurridos, "dias_restantes": restantes,
        "necesario_por_dia": round(faltan / restantes, 3) if restantes > 0 and faltan > 0 else None,
        "estado": estado,
    }
