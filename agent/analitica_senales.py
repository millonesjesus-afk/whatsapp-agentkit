# agent/analitica_senales.py — Señales de Analítica (Etapa 4, 2026-10-26).
#
# Reglas FIJAS con prueba estadística y un mínimo de datos: nada lo escribe un modelo de IA, así que la pantalla las
# llama «Señal» y no «IA». Cada señal explica qué se vio, por qué aparece ahora y qué se sugiere hacer; si no alcanza el
# umbral NO se muestra (nunca atenuada). Máximo 3 a la vez, por prioridad: datos incompletos, operación, comparativas
# y, al final, tendencia. Todas las funciones son puras (sin base de datos): reciben los números ya calculados.
#
# Umbrales aprobados por el dueño (2026-10-26): confianza media con p < 0,05 y alta con p < 0,01; mínimo 20 clientes
# por lado y 5 ventas en total; casos sin asesor desde 10 % y 20 casos; cambios frente al período anterior solo con
# base completa.

from __future__ import annotations

import math
from datetime import date, timedelta

# Primer día con operación real del piloto (Cálidda Hogar). Un período anterior que empieza antes incluye días sin
# operación y exagera cualquier comparación: R4 y R6 no se evalúan. Mismo valor que `PRIMER_DIA_OPERACION` del frontend.
PRIMER_DIA_OPERACION = "2026-09-16"

P_ALTA = 0.01
P_MEDIA = 0.05
P_ANUNCIO = 0.01  # R2 compara muchos anuncios a la vez: umbral más estricto contra falsos positivos.
MIN_CLIENTES_POR_LADO = 20
MIN_VENTAS_TOTALES = 5
MIN_DIAS_COMPARACION = 14
MIN_EVENTOS_COMPARACION = 20
SIN_ASESOR_MIN_PORCENTAJE = 0.10
SIN_ASESOR_MIN_CASOS = 20
PUNTOS_MIN_SIN_RESPUESTA = 10
SIN_ORIGEN_MAX_PORCENTAJE = 0.25
SIN_ORIGEN_MIN_VENTAS = 5
MAX_SENALES = 3

PRIORIDAD_DATOS = 1
PRIORIDAD_OPERACION = 2
PRIORIDAD_COMPARATIVA = 3
PRIORIDAD_TENDENCIA = 4


# ── Estadística ───────────────────────────────────────────────────────────────

def fisher_dos_colas(a: int, b: int, c: int, d: int) -> float:
    """Prueba exacta de Fisher (dos colas) de una tabla 2×2 `[[a, b], [c, d]]`: p-valor de que dos proporciones, a/(a+b)
    y c/(c+d), sean distintas por azar. Con una fila o columna vacía no hay nada que comparar: devuelve 1."""
    n = a + b + c + d
    fila1, col1 = a + b, a + c
    if min(a + b, c + d, a + c, b + d) <= 0:
        return 1.0

    def prob(x: int) -> float:
        return math.comb(fila1, x) * math.comb(n - fila1, col1 - x) / math.comb(n, col1)

    observada = prob(a)
    minimo, maximo = max(0, col1 - (n - fila1)), min(fila1, col1)
    return min(1.0, sum(p for p in (prob(x) for x in range(minimo, maximo + 1)) if p <= observada * (1 + 1e-9)))


def binomial_mitad_dos_colas(x: int, n: int) -> float:
    """p-valor exacto (dos colas) de observar `x` éxitos en `n` si la probabilidad real fuera 1/2: sirve para comparar
    dos conteos de períodos de igual duración (¿es el mismo ritmo?)."""
    if n <= 0:
        return 1.0

    def prob(k: int) -> float:
        return math.comb(n, k) / 2**n

    observada = prob(x)
    return min(1.0, sum(p for p in (prob(k) for k in range(n + 1)) if p <= observada * (1 + 1e-9)))


def confianza_de(p: float, limite_media: float = P_MEDIA) -> str | None:
    """«alta» con p < 0,01, «media» con p < 0,05 (o el límite dado); `None` si no alcanza: la señal no se muestra."""
    if p < P_ALTA:
        return "alta"
    if p < limite_media:
        return "media"
    return None


def periodo_anterior(desde: str, hasta: str) -> dict | None:
    """El período anterior de igual longitud (extremos inclusivos), `None` si las fechas no son válidas. `base_corta`
    es True si empieza antes del primer día con operación."""
    try:
        d0, d1 = date.fromisoformat(desde), date.fromisoformat(hasta)
    except ValueError:
        return None
    if d1 < d0:
        return None
    dias = (d1 - d0).days + 1
    fin = d0 - timedelta(days=1)
    inicio = fin - timedelta(days=dias - 1)
    return {
        "desde": inicio.isoformat(), "hasta": fin.isoformat(), "dias": dias,
        "base_corta": inicio.isoformat() < PRIMER_DIA_OPERACION,
    }


# ── Texto ─────────────────────────────────────────────────────────────────────

def _dec(x: float, decimales: int = 1) -> str:
    return f"{x:.{decimales}f}".replace(".", ",")


def _p(p: float) -> str:
    return "menos de 0,001" if p < 0.001 else _dec(p, 3)


def _por_100(ventas: int, clientes: int) -> str:
    return _dec(ventas * 100 / clientes) if clientes else "0,0"


def _senal(tipo: str, prioridad: int, texto: str, que_vi: str, por_que_ahora: str, que_hacer: str, confianza: str,
           p: float | None = None) -> dict:
    return {
        "tipo": tipo, "prioridad": prioridad, "texto": texto, "que_vi": que_vi, "por_que_ahora": por_que_ahora,
        "que_hacer": que_hacer, "confianza": confianza, "p": None if p is None else round(p, 4),
    }


# Nombre con artículo para la frase del título («La imagen cierra…»); lo que no está aquí se nombra tal cual.
ARTICULOS = {"imagen": "la imagen", "video": "el video"}


# ── Reglas ────────────────────────────────────────────────────────────────────

def _acumular(grupos: list[dict], clave: str) -> dict[str, list[int]]:
    acum: dict[str, list[int]] = {}
    for g in grupos:
        k = g.get(clave)
        if not k:
            continue
        a = acum.setdefault(k, [0, 0])
        a[0] += int(g.get("leads") or 0)
        a[1] += int(g.get("ventas") or 0)
    return acum


def _comparar_dos(tipo: str, etiquetas: dict[str, str], acum: dict[str, list[int]], dimension: str, que_hacer: str) -> dict | None:
    """R1 y R3: dos lados de una misma dimensión (formato o empresa) con suficientes clientes y ventas."""
    lados = sorted(
        ((k, v) for k, v in acum.items() if v[0] >= MIN_CLIENTES_POR_LADO), key=lambda kv: kv[1][0], reverse=True,
    )[:2]
    if len(lados) < 2:
        return None
    (ka, (la, va)), (kb, (lb, vb)) = lados
    if va + vb < MIN_VENTAS_TOTALES:
        return None
    p = fisher_dos_colas(va, la - va, vb, lb - vb)
    conf = confianza_de(p)
    if conf is None:
        return None
    ta, tb = va / la, vb / lb
    (mk, mv, ml, mt), (pk, pv, pl, pt) = ((ka, va, la, ta), (kb, vb, lb, tb)) if ta >= tb else ((kb, vb, lb, tb), (ka, va, la, ta))
    nm, npeor = etiquetas.get(mk, mk), etiquetas.get(pk, pk)
    sujeto, objeto = ARTICULOS.get(mk, nm), ARTICULOS.get(pk, npeor)
    sujeto = sujeto[0].upper() + sujeto[1:]
    titulo = (
        f"{sujeto} cierra {_dec(mt / pt)} veces más que {objeto}" if pt > 0 else f"{sujeto} cierra ventas y {objeto} ninguna"
    )
    return _senal(
        tipo, PRIORIDAD_COMPARATIVA, titulo,
        f"{nm}: {mv} ventas de {ml} clientes ({_por_100(mv, ml)} por 100). {npeor}: {pv} de {pl} ({_por_100(pv, pl)} por 100).",
        f"Es la diferencia de {dimension} de este período y es poco probable que sea casualidad (p = {_p(p)}).",
        que_hacer.format(mejor=nm, peor=npeor, mejor_l=nm.lower(), peor_l=npeor.lower()), conf, p,
    )


def regla_formato(grupos: list[dict]) -> dict | None:
    acum = {k: v for k, v in _acumular(grupos, "formato").items() if k in ("video", "imagen")}
    return _comparar_dos(
        "formato_rinde_distinto", {"video": "Video", "imagen": "Imagen"}, acum, "formato",
        "Prueba más anuncios en formato {mejor_l} para los productos que hoy usan formato {peor_l}.",
    )


def regla_empresa(grupos: list[dict]) -> dict | None:
    acum = _acumular(grupos, "empresa")
    return _comparar_dos(
        "empresa_rinde_distinto", {}, acum, "empresa",
        "Revisa qué hacen distinto los anuncios de {mejor} frente a los de {peor}.",
    )


def regla_anuncio(grupos: list[dict]) -> dict | None:
    """R2: un grupo de anuncios con ≥ 20 clientes rinde distinto al resto (el más claro, uno solo)."""
    tot_l = sum(int(g.get("leads") or 0) for g in grupos)
    tot_v = sum(int(g.get("ventas") or 0) for g in grupos)
    if tot_v < MIN_VENTAS_TOTALES:
        return None
    mejor: tuple[float, dict] | None = None
    for g in grupos:
        lg, vg = int(g.get("leads") or 0), int(g.get("ventas") or 0)
        lr, vr = tot_l - lg, tot_v - vg
        if lg < MIN_CLIENTES_POR_LADO or lr < MIN_CLIENTES_POR_LADO:
            continue
        p = fisher_dos_colas(vg, lg - vg, vr, lr - vr)
        if p < P_ANUNCIO and (mejor is None or p < mejor[0]):
            mejor = (p, {**g, "_lr": lr, "_vr": vr})
    if mejor is None:
        return None
    p, g = mejor
    lg, vg, lr, vr = int(g["leads"]), int(g["ventas"]), g["_lr"], g["_vr"]
    mas = vg / lg > vr / lr
    titulo_anuncio = (g.get("titulo") or "este anuncio")[:60]
    return _senal(
        "anuncio_rinde_distinto", PRIORIDAD_COMPARATIVA,
        f"«{titulo_anuncio}» cierra {'más' if mas else 'menos'} que el resto de los anuncios",
        f"Ese grupo: {vg} ventas de {lg} clientes ({_por_100(vg, lg)} por 100). El resto: {vr} de {lr} ({_por_100(vr, lr)} por 100).",
        f"Con tantos anuncios en comparación se exige una diferencia muy clara, y esta lo es (p = {_p(p)}).",
        "Escala este anuncio y revisa qué lo hace distinto." if mas else "Revisa su mensaje, su público o pausa el gasto en él.",
        "alta", p,
    )


def regla_cambio_frente_al_anterior(flujo: dict, anterior_flujo: dict, rotulo: str) -> dict | None:
    """R4: clientes nuevos o ventas cambiaron mucho frente al período anterior de igual longitud (el cambio más claro)."""
    candidato: tuple[float, str, int, int] | None = None
    for clave, nombre in (("leads", "clientes nuevos"), ("ventas", "ventas")):
        x1, x2 = int(flujo.get(clave) or 0), int(anterior_flujo.get(clave) or 0)
        if x1 + x2 < MIN_EVENTOS_COMPARACION or x2 == 0:
            continue
        p = binomial_mitad_dos_colas(x1, x1 + x2)
        if confianza_de(p) and (candidato is None or p < candidato[0]):
            candidato = (p, nombre, x1, x2)
    if candidato is None:
        return None
    p, nombre, x1, x2 = candidato
    sube = x1 > x2
    pct = round(abs(x1 - x2) * 100 / x2)
    return _senal(
        "cambio_frente_al_anterior", PRIORIDAD_TENDENCIA,
        f"Los {nombre} {'subieron' if sube else 'bajaron'} {pct}% frente al período anterior" if nombre != "ventas"
        else f"Las ventas {'subieron' if sube else 'bajaron'} {pct}% frente al período anterior",
        f"{x1} contra {x2} en el {rotulo}.",
        f"Es un cambio mayor de lo que se espera por azar (p = {_p(p)}) y el período anterior tenía operación completa.",
        "Identifica qué lo explica para sostenerlo." if sube else "Revisa qué cambió: anuncios activos, presupuesto o atención.",
        confianza_de(p) or "media", p,
    )


def regla_sin_respuesta(distribucion: list[dict], anterior_distribucion: list[dict], excluir_atc: bool, rotulo: str) -> dict | None:
    """R6: el peso de «Sin respuesta» entre los casos cambió ≥ 10 puntos frente al período anterior."""
    def peso(dist: list[dict]) -> tuple[int, int]:
        filas = [f for f in dist if not (excluir_atc and f.get("resultado") == "consulta_atc")]
        total = sum(int(f.get("total") or 0) for f in filas)
        sr = sum(int(f.get("total") or 0) for f in filas if f.get("resultado") == "sin_respuesta")
        return sr, total

    sr1, n1 = peso(distribucion)
    sr0, n0 = peso(anterior_distribucion)
    if n1 < MIN_CLIENTES_POR_LADO or n0 < MIN_CLIENTES_POR_LADO:
        return None
    diff = (sr1 / n1 - sr0 / n0) * 100
    if abs(diff) < PUNTOS_MIN_SIN_RESPUESTA:
        return None
    p = fisher_dos_colas(sr1, n1 - sr1, sr0, n0 - sr0)
    conf = confianza_de(p)
    if conf is None:
        return None
    mas = diff > 0
    return _senal(
        "sin_respuesta_cambia", PRIORIDAD_TENDENCIA,
        f"«Sin respuesta» pesa {_dec(abs(diff), 0)} puntos {'más' if mas else 'menos'} que en el período anterior",
        f"{_dec(sr1 * 100 / n1, 0)}% de los casos ({sr1} de {n1}) frente a {_dec(sr0 * 100 / n0, 0)}% ({sr0} de {n0}) en el {rotulo}.",
        f"La diferencia es mayor de lo que se espera por azar (p = {_p(p)}). Los casos recientes aún pueden cambiar de resultado.",
        "Revisa el primer mensaje y el momento del reenganche." if mas else "Mantén lo que cambió en el primer contacto.",
        conf, p,
    )


def regla_sin_asesor(casos_sin_asesor: dict | None, casos_total: int) -> dict | None:
    """R5: casos del período sin asesor asignado (10 % o más y al menos 20)."""
    if not casos_sin_asesor or casos_total <= 0:
        return None
    n = int(casos_sin_asesor.get("oportunidades") or 0)
    if n < SIN_ASESOR_MIN_CASOS or n / casos_total < SIN_ASESOR_MIN_PORCENTAJE:
        return None
    ventas = int(casos_sin_asesor.get("ventas") or 0)
    return _senal(
        "casos_sin_asesor", PRIORIDAD_OPERACION,
        f"{n} casos ({_dec(n * 100 / casos_total, 0)}%) no tienen asesor asignado",
        f"{n} de {casos_total} casos comerciales del período no tienen asesor y registran {ventas} venta{'' if ventas == 1 else 's'}.",
        f"Es más del {_dec(SIN_ASESOR_MIN_PORCENTAJE * 100, 0)}% de los casos del período. Sin asesor no hay una persona "
        "responsable de darles seguimiento (pueden estar con Gabi o sin derivar todavía).",
        "Revisa cuáles siguen con Gabi y cuáles hay que derivar a un asesor, y el reparto automático.", "alta",
    )


def reglas_datos_incompletos(
    valor_vendido: dict, grupos: list[dict] | None, ventas_total: int, ventas_sin_origen: int | None,
) -> list[dict]:
    """R7: lo que impide leer bien los números."""
    salida: list[dict] = []
    excluidas = int(valor_vendido.get("ventas_excluidas") or 0)
    if excluidas > 0:
        salida.append(_senal(
            "ventas_excluidas", PRIORIDAD_DATOS,
            f"{excluidas} venta(s) del período con un precio no numérico — excluidas del monto total.",
            f"{excluidas} venta{'' if excluidas == 1 else 's'} no se suman al valor vendido ni al ticket promedio.",
            "Mientras no tengan un precio numérico, el valor vendido de este período está incompleto.",
            "Corrige el precio de esas ventas en su ficha.", "alta",
        ))
    if grupos:
        sin_empresa = [g for g in grupos if not g.get("empresa") and int(g.get("leads") or 0) >= MIN_CLIENTES_POR_LADO]
        if sin_empresa:
            n = len(sin_empresa)
            salida.append(_senal(
                "grupos_sin_empresa", PRIORIDAD_DATOS,
                f"{n} grupo{'' if n == 1 else 's'} de anuncios con muchos clientes no tiene{'' if n == 1 else 'n'} empresa",
                f"{sum(int(g.get('leads') or 0) for g in sin_empresa)} clientes entraron por anuncios cuya empresa no está confirmada.",
                "Sin la empresa, los filtros y la comparación entre empresas dejan esos clientes fuera.",
                "Confirma la empresa de esos grupos en «Rendimiento por anuncio».", "alta",
            ))
    if ventas_sin_origen is not None and ventas_total >= SIN_ORIGEN_MIN_VENTAS and ventas_sin_origen / ventas_total > SIN_ORIGEN_MAX_PORCENTAJE:
        salida.append(_senal(
            "ventas_sin_origen", PRIORIDAD_DATOS,
            f"{ventas_sin_origen} de {ventas_total} ventas ({_dec(ventas_sin_origen * 100 / ventas_total, 0)}%) no tienen origen",
            f"No se sabe por qué anuncio o campaña llegaron {ventas_sin_origen} de las {ventas_total} ventas del período.",
            f"Pasa de {_dec(SIN_ORIGEN_MAX_PORCENTAJE * 100, 0)}% de las ventas: la comparación entre anuncios se apoya en menos ventas de las reales.",
            "Revisa de dónde entraron esos clientes (enlaces directos, SMS, WhatsApp sin anuncio).", "alta",
        ))
    return salida


def reglas_sin_oportunidades(flujo: dict) -> list[dict]:
    """La señal de siempre: no hubo casos comerciales en el período."""
    if flujo.get("oportunidades", 0) != 0:
        return []
    consultas = ((flujo.get("consultas_no_comerciales") or {}).get("cantidad")) or 0
    if consultas > 0:
        texto = "No se registraron oportunidades comerciales en este período: " + (
            "el único contacto fue una consulta de atención al cliente." if consultas == 1
            else f"los {consultas} contactos fueron consultas de atención al cliente."
        )
    else:
        texto = "No se registraron oportunidades en este período."
    return [_senal(
        "sin_oportunidades", PRIORIDAD_DATOS, texto, texto,
        "Sin casos en el período no hay nada que medir todavía.", "Revisa si el filtro elegido deja el período vacío.", "alta",
    )]


# ── Orquestador ───────────────────────────────────────────────────────────────

def evaluar_senales(
    *,
    flujo: dict,
    valor_vendido: dict,
    embudo: dict,
    distribucion: list[dict],
    grupos: list[dict] | None,
    ventas_total: int,
    ventas_sin_origen: int | None,
    casos_sin_asesor: dict | None,
    anterior: dict | None,
    rotulo_anterior: str = "",
    comparativas: bool = True,
) -> list[dict]:
    """Todas las reglas sobre números ya calculados, ordenadas por prioridad (y dentro de ella por p-valor más claro) y
    recortadas a `MAX_SENALES`. `anterior` es `{"flujo", "distribucion"}` del período anterior, o `None` cuando no
    aplica (base corta, período de menos de 14 días, rol sin vista total): entonces R4 y R6 no se evalúan.
    `comparativas=False` desactiva R1–R3 (p. ej. con un filtro de campaña, o para un Asesor)."""
    senales: list[dict] = []
    senales += reglas_sin_oportunidades(flujo)
    senales += reglas_datos_incompletos(valor_vendido, grupos, ventas_total, ventas_sin_origen)
    senales += [s for s in (regla_sin_asesor(casos_sin_asesor, int(flujo.get("oportunidades") or 0)),) if s]
    if comparativas and grupos:
        senales += [s for s in (regla_formato(grupos), regla_empresa(grupos), regla_anuncio(grupos)) if s]
    if anterior:
        excluir = embudo.get("excluye_consulta_atc") is True
        senales += [
            s for s in (
                regla_cambio_frente_al_anterior(flujo, anterior["flujo"], rotulo_anterior),
                regla_sin_respuesta(distribucion, anterior["distribucion"], excluir, rotulo_anterior),
            ) if s
        ]
    senales.sort(key=lambda s: (s["prioridad"], s["p"] if s["p"] is not None else 0.0))
    return senales[:MAX_SENALES]
