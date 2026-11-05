# agent/pipeline_etapas.py — Etapa derivada de cada caso del Pipeline (2026-11-05).
#
# Los 13 «resultados» del Pipeline no son etapas: «Vendido», «No interesado» o «Consulta ATC» dicen cómo TERMINÓ un caso, no dónde
# está. La Nueva Experiencia muestra una etapa que se CALCULA con tres datos que ya existen en el lead (resultado, asesora asignada y
# `paso_flujo == "derivado_asesor"`). No se guarda nada nuevo: filtrar, contar y mostrar usan la misma regla.
#
#   gabi      Lo atiende Gabi: no se derivó a una persona y no tiene resultado final.
#   asesora   Derivado a una persona: con asesora asignada o esperando que se la asignen, sin cita, venta ni cierre.
#   agendado  Resultado «agendado».
#   vendido   Resultado «vendido» o «postventa» (el cliente que volvió tras una venta).
#   cerrado   Cualquier otro resultado final (no interesado, no califica, sin respuesta, consulta ATC, solicita suministro…).

from sqlalchemy import and_, func, or_, select

from agent.memory import Lead, RESULTADOS_CERRADOS, async_session

ETAPAS = ("gabi", "asesora", "agendado", "vendido", "cerrado")

RESULTADOS_VENDIDO = ("vendido", "postventa")
RESULTADO_AGENDADO = "agendado"
RESULTADOS_CERRADO = tuple(r for r in RESULTADOS_CERRADOS if r not in RESULTADOS_VENDIDO)
_RESULTADOS_CON_ETAPA_PROPIA = RESULTADOS_VENDIDO + (RESULTADO_AGENDADO,) + RESULTADOS_CERRADO

PASO_DERIVADO = "derivado_asesor"


def etapa_de(resultado: str | None, asesor_asignado: str | None, paso_flujo: str | None) -> str:
    """La etapa de un caso. Misma regla que `condicion_etapa` (que filtra en SQL): si una cambia, cambia la otra."""
    if resultado in RESULTADOS_VENDIDO:
        return "vendido"
    if resultado == RESULTADO_AGENDADO:
        return "agendado"
    if resultado in RESULTADOS_CERRADO:
        return "cerrado"
    return "asesora" if (asesor_asignado or paso_flujo == PASO_DERIVADO) else "gabi"


def _sin_etapa_propia():
    # `NOT IN` deja afuera los NULL en SQL, y la mayoría de los casos abiertos tiene resultado NULL: se piden aparte.
    return or_(Lead.resultado.is_(None), Lead.resultado.not_in(_RESULTADOS_CON_ETAPA_PROPIA))


def _con_persona():
    return or_(and_(Lead.asesor_asignado.is_not(None), Lead.asesor_asignado != ""), Lead.paso_flujo == PASO_DERIVADO)


def _sin_persona():
    # NO es `~_con_persona()`: con asesora o `paso_flujo` NULL, `NOT (NULL OR NULL)` da NULL y la fila se pierde (justo los casos
    # nuevos de Gabi, que no tienen ninguno de los dos). Se escribe la negación a mano, tratando el NULL de forma explícita.
    return and_(
        or_(Lead.asesor_asignado.is_(None), Lead.asesor_asignado == ""),
        or_(Lead.paso_flujo.is_(None), Lead.paso_flujo != PASO_DERIVADO),
    )


def condicion_etapa(etapa: str):
    """Condición SQL sobre `Lead` para una etapa, o `None` si el nombre no es una etapa (se ignora, igual que un `resultado` raro)."""
    if etapa == "vendido":
        return Lead.resultado.in_(RESULTADOS_VENDIDO)
    if etapa == "agendado":
        return Lead.resultado == RESULTADO_AGENDADO
    if etapa == "cerrado":
        return Lead.resultado.in_(RESULTADOS_CERRADO)
    if etapa == "asesora":
        return and_(_sin_etapa_propia(), _con_persona())
    if etapa == "gabi":
        return and_(_sin_etapa_propia(), _sin_persona())
    return None


async def contar_por_etapa(negocio_id: str, asesor_asignado: str | None = None) -> dict[str, int]:
    """Cuántos casos hay en cada etapa. `asesor_asignado` acota a la cartera de una persona (el alcance de un Asesor)."""
    conteos = {e: 0 for e in ETAPAS}
    async with async_session() as session:
        for etapa in ETAPAS:
            consulta = select(func.count()).select_from(Lead).where(Lead.negocio_id == negocio_id, condicion_etapa(etapa))
            if asesor_asignado:
                consulta = consulta.where(Lead.asesor_asignado == asesor_asignado)
            conteos[etapa] = (await session.execute(consulta)).scalar_one()
    return conteos


async def contar_asignados_a(negocio_id: str, asesor_asignado: str) -> int:
    """Casos con esta persona asignada, en cualquier etapa (la vista «Míos»)."""
    async with async_session() as session:
        return (await session.execute(
            select(func.count()).select_from(Lead).where(Lead.negocio_id == negocio_id, Lead.asesor_asignado == asesor_asignado)
        )).scalar_one()
