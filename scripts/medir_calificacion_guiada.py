"""Mide la calificación guiada ANTES y DESPUÉS de activarla — SOLO LECTURA, solo agregados (2026-10-24).

Compara las conversaciones creadas en los N días anteriores al corte (`calificacion_guiada_activa_desde`) con las creadas desde el
corte, en total y por producto. Sin teléfonos, nombres, ids ni texto de mensajes. Solo SELECT.

Métricas por cohorte: conversaciones, % con 2 o más mensajes del cliente (siguió la conversación), mensajes del cliente por
conversación, % derivadas al asesor, % agendado, % vendido, y entre las derivadas: % con producto y nombre (ficha mínima) y % con
el titular respondido (solo existe en la cohorte «después»).

LÍMITE: no hay grupo de control en paralelo. Una campaña nueva, un feriado o un fin de semana largo pueden mover los números;
por eso se compara por producto y se entregan las dos ventanas con sus fechas. La cohorte «después» madura: el resultado final
(agendado, vendido) tarda días en conocerse.

Uso (la base sale de DATABASE_URL, como en los demás scripts):
    python scripts/medir_calificacion_guiada.py
    python scripts/medir_calificacion_guiada.py --negocio-id <id> --dias 14 --corte 2026-10-25T15:00:00Z
"""
import argparse
import asyncio
import sys
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import func, select

from agent import calificacion_guiada as cg
from agent import memory as mem
from agent.memory import esperar_base_de_datos, listar_negocios
from scripts.configurar_plantilla_retomar import resolver_negocio_id

RESULTADOS_VENTA = ("vendido",)
RESULTADOS_AGENDA = ("agendado",)


def _pct(parte: int, total: int) -> float | None:
    return round(100.0 * parte / total, 1) if total else None


def resumir(filas: list[dict]) -> dict:
    """Agregados de una cohorte. Cada fila: `{n_cliente, derivado, resultado, tiene_producto, tiene_nombre, titular_respondido}`."""
    n = len(filas)
    derivadas = [f for f in filas if f["derivado"]]
    return {
        "conversaciones": n,
        "pct_2_mas_mensajes": _pct(sum(1 for f in filas if f["n_cliente"] >= 2), n),
        "mensajes_cliente_promedio": round(sum(f["n_cliente"] for f in filas) / n, 2) if n else None,
        "pct_derivadas": _pct(len(derivadas), n),
        "pct_agendado": _pct(sum(1 for f in filas if f["resultado"] in RESULTADOS_AGENDA), n),
        "pct_vendido": _pct(sum(1 for f in filas if f["resultado"] in RESULTADOS_VENTA), n),
        "derivadas": len(derivadas),
        "pct_derivadas_con_producto_y_nombre": _pct(sum(1 for f in derivadas if f["tiene_producto"] and f["tiene_nombre"]), len(derivadas)),
        "pct_derivadas_con_titular": _pct(sum(1 for f in derivadas if f["titular_respondido"]), len(derivadas)),
    }


def producto_de(interes: str | None) -> str:
    return cg.tipo_de_producto(interes)


async def cargar_filas(negocio_id: str, desde: datetime, hasta: datetime) -> list[dict]:
    """Una fila por conversación creada en [desde, hasta). Solo lectura."""
    async with mem.async_session() as session:
        convs = (await session.execute(
            select(mem.Conversation.id, mem.Conversation.contact_id, mem.Conversation.paso_flujo).where(
                mem.Conversation.negocio_id == negocio_id, mem.Conversation.creado >= desde, mem.Conversation.creado < hasta,
            )
        )).all()
        ids = [c.id for c in convs]
        if not ids:
            return []
        n_cliente = dict((await session.execute(
            select(mem.Mensaje.conversation_id, func.count()).where(mem.Mensaje.conversation_id.in_(ids), mem.Mensaje.role == "user")
            .group_by(mem.Mensaje.conversation_id)
        )).all())
        opps = {
            o.conversation_id: o for o in (await session.execute(
                select(mem.Opportunity).where(mem.Opportunity.conversation_id.in_(ids)).order_by(mem.Opportunity.creado.asc())
            )).scalars().all()
        }
        titular = {
            c for (c,) in (await session.execute(
                select(mem.EventoLead.conversation_id).where(
                    mem.EventoLead.conversation_id.in_(ids), mem.EventoLead.tipo == mem.EVENTO_CALIFICACION_RESPUESTA,
                    mem.EventoLead.descripcion.like("Calificación: titular%"),
                ).distinct()
            )).all()
        }
        contactos = {c.contact_id for c in convs}
        telefonos = dict((await session.execute(
            select(mem.Contact.id, mem.Contact.telefono).where(mem.Contact.id.in_(contactos))
        )).all())
        leads = {
            l.telefono: l for l in (await session.execute(select(mem.Lead).where(mem.Lead.telefono.in_(list(telefonos.values()))))).scalars().all()
        }
    filas = []
    for c in convs:
        lead = leads.get(telefonos.get(c.contact_id))
        opp = opps.get(c.id)
        derivado = c.paso_flujo == "derivado_asesor" or (lead is not None and lead.paso_flujo == "derivado_asesor")
        interes = (opp.interes if opp else None) or (lead.interes if lead else None)
        filas.append({
            "n_cliente": int(n_cliente.get(c.id, 0)), "derivado": derivado, "resultado": opp.resultado if opp else None,
            "tiene_producto": bool(interes), "tiene_nombre": bool(lead and lead.nombre), "titular_respondido": c.id in titular,
            "producto": producto_de(interes),
        })
    return filas


def _imprimir(titulo: str, resumen: dict) -> None:
    print(f"  {titulo}: " + ", ".join(f"{k}={v}" for k, v in resumen.items()))


async def main(argv=None) -> dict:
    p = argparse.ArgumentParser(description="Mide la calificación guiada antes y después del corte (solo lectura).")
    p.add_argument("--negocio-id", default=None)
    p.add_argument("--dias", type=int, default=14)
    p.add_argument("--corte", default=None, help="Marca ISO (UTC) del corte; por defecto, calificacion_guiada_activa_desde.")
    args = p.parse_args(argv)
    await esperar_base_de_datos()
    negocio_id = resolver_negocio_id(args.negocio_id, await listar_negocios())
    corte_txt = args.corte or (await mem.obtener_configuracion(cg.CLAVE_ACTIVA_DESDE, "", negocio_id=negocio_id) or "").strip()
    if not corte_txt:
        print("No hay corte: activa la calificación (configurar_calificacion_guiada.py --activar) o pasa --corte.")
        return {}
    corte = datetime.fromisoformat(corte_txt.replace("Z", "+00:00")).replace(tzinfo=None)
    ahora = datetime.utcnow()
    antes = await cargar_filas(negocio_id, corte - timedelta(days=args.dias), corte)
    despues = await cargar_filas(negocio_id, corte, min(ahora, corte + timedelta(days=args.dias)))
    salida = {"corte": corte.isoformat() + "Z", "dias": args.dias, "antes": resumir(antes), "despues": resumir(despues), "por_producto": {}}
    print(f"Corte {salida['corte']} · ventana de {args.dias} días a cada lado (solo agregados)")
    _imprimir("ANTES  ", salida["antes"])
    _imprimir("DESPUÉS", salida["despues"])
    por_producto: dict[str, dict[str, list]] = defaultdict(lambda: {"antes": [], "despues": []})
    for f in antes:
        por_producto[f["producto"]]["antes"].append(f)
    for f in despues:
        por_producto[f["producto"]]["despues"].append(f)
    for producto, grupos in sorted(por_producto.items()):
        salida["por_producto"][producto] = {"antes": resumir(grupos["antes"]), "despues": resumir(grupos["despues"])}
        print(f"Producto {producto}:")
        _imprimir("antes  ", salida["por_producto"][producto]["antes"])
        _imprimir("después", salida["por_producto"][producto]["despues"])
    return salida


if __name__ == "__main__":
    asyncio.run(main())
