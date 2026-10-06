"""Backfill del evento `reabierto_por_cliente` (P4, 2026-10-06).

Desde el 2026-10-06 el webhook deja el evento "Reabierto por el cliente — antes:
<resultado> (gestionado por <asesor>)" en la conversación NUEVA que DR-4 abre
cuando un cliente vuelve a escribir tras un cierre definitivo. Las reaperturas
anteriores a ese cambio (p. ej. Mario 51962726506) no tienen el evento: este
script lo escribe retroactivamente.

Qué considera una reapertura sin evento: una Conversation ACTIVA cuya
Conversation inmediatamente anterior (mismo Contact, por fecha de creación)
está cerrada, y que todavía no tiene ningún evento `reabierto_por_cliente`.
Se omiten las anteriores con resultado "vendido": ese flujo es la posventa
(`asignado_automatico_postventa`) y deja su propio evento.

Qué datos usa: el resultado original sale de la Opportunity vigente de la
conversación cerrada; si esa no tiene resultado, del último `resultado_cambiado`
de su Timeline. El asesor sale de `asesor_asignado_id` de la conversación
cerrada (respaldo: el último evento de asignación). El evento queda fechado en
el instante en que se abrió la conversación nueva.

Qué NO hace: no toca `Lead.resultado` ni ningún otro dato de los ciclos
nuevos (esos ya evolucionaron; restaurarlos sería inventar). Solo inserta
eventos (append-only) y es idempotente: correrlo dos veces no duplica nada.

Uso (dry-run por defecto: solo imprime qué haría, no escribe nada):
    python scripts/backfill_reaperturas.py
    python scripts/backfill_reaperturas.py --aplicar

La base sale de DATABASE_URL (como el resto de los scripts); el script imprime
a cuál apunta antes de hacer nada. NO ejecutarlo contra producción sin revisar
antes la salida del dry-run.
"""
import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select

from agent.memory import (
    Contact, Conversation, EventoLead, Opportunity,
    async_session, descripcion_reapertura, engine, esperar_base_de_datos,
)

TIPO_EVENTO = "reabierto_por_cliente"


async def _resultado_original(session, conversation_anterior: Conversation) -> str | None:
    opportunity = (await session.execute(
        select(Opportunity)
        .where(Opportunity.conversation_id == conversation_anterior.id)
        .order_by(Opportunity.creado.desc())
        .limit(1)
    )).scalar_one_or_none()
    if opportunity is not None and opportunity.resultado:
        return opportunity.resultado
    cambios = (await session.execute(
        select(EventoLead)
        .where(EventoLead.conversation_id == conversation_anterior.id, EventoLead.tipo == "resultado_cambiado")
        .order_by(EventoLead.creado.desc(), EventoLead.id.desc())
    )).scalars().all()
    for evento in cambios:
        nuevo = (evento.payload or {}).get("nuevo")
        if nuevo:
            return nuevo
    return None


async def _asesor_original(session, conversation_anterior: Conversation) -> str | None:
    if conversation_anterior.asesor_asignado_id:
        return conversation_anterior.asesor_asignado_id
    asignaciones = (await session.execute(
        select(EventoLead)
        .where(
            EventoLead.conversation_id == conversation_anterior.id,
            EventoLead.tipo.in_(["asignado", "asignado_automatico"]),
        )
        .order_by(EventoLead.creado.desc(), EventoLead.id.desc())
    )).scalars().all()
    for evento in asignaciones:
        payload = evento.payload or {}
        asesor = payload.get("nuevo") or payload.get("asesor")
        if asesor:
            return asesor
    return None


async def calcular_reaperturas(session) -> list[dict]:
    """Lista, sin escribir nada, las reaperturas que les falta el evento."""
    filas = (await session.execute(
        select(Conversation, Contact.telefono)
        .join(Contact, Contact.id == Conversation.contact_id)
        .order_by(Conversation.contact_id, Conversation.creado.asc(), Conversation.id.asc())
    )).all()
    por_contact: dict[str, list[tuple[Conversation, str]]] = {}
    for conversation, telefono in filas:
        por_contact.setdefault(conversation.contact_id, []).append((conversation, telefono))

    plan: list[dict] = []
    for conversaciones in por_contact.values():
        for (anterior, _), (nueva, telefono) in zip(conversaciones, conversaciones[1:]):
            if nueva.estado != "activa" or anterior.estado != "cerrada" or anterior.negocio_id != nueva.negocio_id:
                continue
            ya_tiene = (await session.execute(
                select(EventoLead.id).where(EventoLead.conversation_id == nueva.id, EventoLead.tipo == TIPO_EVENTO).limit(1)
            )).first()
            if ya_tiene:
                continue
            resultado = await _resultado_original(session, anterior)
            if resultado == "vendido":
                continue  # posventa: ya tiene su propio evento, no se reinicia
            opportunity_nueva = (await session.execute(
                select(Opportunity)
                .where(Opportunity.conversation_id == nueva.id)
                .order_by(Opportunity.creado.desc())
                .limit(1)
            )).scalar_one_or_none()
            asesor = await _asesor_original(session, anterior)
            plan.append({
                "telefono": telefono, "negocio_id": nueva.negocio_id,
                "conversation_nueva_id": nueva.id, "conversation_anterior_id": anterior.id,
                "opportunity_nueva_id": opportunity_nueva.id if opportunity_nueva else None,
                "resultado_anterior": resultado, "asesor_anterior": asesor,
                "cerrado_en": anterior.cerrado_definitivamente_en,
                "creado": nueva.creado,
            })
    return plan


async def aplicar_reaperturas(session, plan: list[dict]) -> int:
    """Inserta los eventos del plan. Vuelve a verificar cada fila justo antes
    de escribirla, por si otra corrida (o el webhook) ya la cubrió."""
    escritos = 0
    for fila in plan:
        ya_tiene = (await session.execute(
            select(EventoLead.id).where(
                EventoLead.conversation_id == fila["conversation_nueva_id"], EventoLead.tipo == TIPO_EVENTO,
            ).limit(1)
        )).first()
        if ya_tiene:
            continue
        session.add(EventoLead(
            conversation_id=fila["conversation_nueva_id"], negocio_id=fila["negocio_id"],
            opportunity_id=fila["opportunity_nueva_id"],
            tipo="reabierto_por_cliente",
            descripcion=descripcion_reapertura(fila["resultado_anterior"], fila["asesor_anterior"]),
            autor=None,
            payload={
                "resultado_anterior": fila["resultado_anterior"],
                "asesor_anterior": fila["asesor_anterior"],
                "conversation_anterior_id": fila["conversation_anterior_id"],
                "cerrado_en": fila["cerrado_en"].isoformat() if fila["cerrado_en"] else None,
                "backfill": True,
            },
            creado=fila["creado"],
        ))
        escritos += 1
    await session.commit()
    return escritos


async def main(aplicar: bool) -> None:
    await esperar_base_de_datos()
    print(f"Base de datos: {engine.url.render_as_string(hide_password=True)}")
    async with async_session() as session:
        plan = await calcular_reaperturas(session)
        if not plan:
            print("Ninguna reapertura sin evento. Nada que hacer.")
            return
        for f in plan:
            print(
                f"- {f['telefono']}: conversación {f['conversation_nueva_id']} (abierta {f['creado']}) reabre a "
                f"{f['conversation_anterior_id']} — antes: {f['resultado_anterior'] or 'sin resultado'}, "
                f"asesor: {f['asesor_anterior'] or 'ninguno'}"
            )
        if not aplicar:
            print(f"\nDRY-RUN: se escribiría {len(plan)} evento(s) `{TIPO_EVENTO}`. No se escribió nada. Usa --aplicar para escribirlos.")
            return
        escritos = await aplicar_reaperturas(session, plan)
        print(f"\nEscritos {escritos} evento(s) `{TIPO_EVENTO}`.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Backfill del evento reabierto_por_cliente (dry-run por defecto).")
    parser.add_argument("--aplicar", action="store_true", help="Escribe los eventos (sin esto solo imprime).")
    argumentos = parser.parse_args()
    try:
        asyncio.run(main(argumentos.aplicar))
    except Exception as e:
        print(f"ERROR: backfill de reaperturas falló — {e}", file=sys.stderr)
        sys.exit(1)
