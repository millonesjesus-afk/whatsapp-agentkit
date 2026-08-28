"""gate 5.3 backfill contact conversation opportunity

Revision ID: 6834f5dd636d
Revises: e4d943403e19
Create Date: 2026-08-28 11:58:32.172317

Gate 5.3 — BACKFILL + VALIDATE (M3). Por cada `Lead` existente crea
exactamente 1 `Contact` + 1 `Conversation` + 1 `Opportunity` (Diseño Técnico
Gate 5.3 §11, "1:1:1 literal, sin ambigüedad porque hoy solo sobrevive un
ciclo comercial por Lead"), y resuelve `mensajes.conversation_id`,
`eventos_lead.negocio_id/conversation_id/opportunity_id`,
`lineas_venta.opportunity_id/negocio_id` con el doble candado
(negocio_id + telefono, nunca telefono solo).

`Conversation.canal_id` es NOT NULL — si el `numero_whatsapp_id` de un Lead
no resuelve contra un `CanalWhatsApp` real de su mismo Negocio, NO se
inventa ningún canal: la migración FALLA explícito (RuntimeError) en vez de
crear una Conversation con un canal falso, mismo criterio ya usado en
`a46a93329345` para huérfanos de `mensajes.negocio_id`. Igual criterio para
`campana_origen`/`numero_whatsapp_id` que no resuelven: se registra la
pérdida vía `RegistroAuditoria` (ya existe desde Gate 5.2, append-only) en
vez de perderse en silencio, y el campo queda NULL — nunca se inventa.

Esta migración se ejecuta en Python (no SQL puro) porque necesita generar
UUIDs consistentes entre las 3 tablas relacionadas para cada Lead — no hay
forma portable SQLite/Postgres de correlacionar `gen_random_uuid()` entre
INSERTs sin round-trip a la aplicación.
"""
from typing import Sequence, Union
import uuid
from datetime import datetime

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '6834f5dd636d'
down_revision: Union[str, Sequence[str], None] = 'e4d943403e19'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema + data."""
    bind = op.get_bind()

    leads = bind.execute(sa.text(
        "SELECT telefono, negocio_id, nombre, interes, producto_tipo, producto_marca, "
        "producto_modalidad, paso_flujo, resultado, fecha_agendada, fecha_cierre, "
        "asesor_asignado, modalidad_pago, cuotas, medio_pago, visto_asesor, "
        "fallos_tecnicos, campana_origen, origen_contacto, numero_whatsapp_id, "
        "pausado_manual, revision_prioritaria, actualizado, creado "
        "FROM leads"
    )).mappings().all()

    canales = bind.execute(sa.text(
        "SELECT id, phone_number_id, negocio_id, unidad_id FROM canales_whatsapp"
    )).mappings().all()
    canal_por_negocio_numero = {(c["negocio_id"], c["phone_number_id"]): c for c in canales}

    campanas = bind.execute(sa.text("SELECT id, nombre, negocio_id FROM campanas")).mappings().all()
    campana_por_negocio_nombre = {(c["negocio_id"], c["nombre"]): c["id"] for c in campanas}

    huerfanos_canal: list[str] = []
    mapa_contact: dict[str, str] = {}       # telefono -> contact_id
    mapa_conversation: dict[str, str] = {}  # telefono -> conversation_id
    mapa_opportunity: dict[str, str] = {}   # telefono -> opportunity_id

    for lead in leads:
        telefono = lead["telefono"]
        negocio_id = lead["negocio_id"]
        canal = canal_por_negocio_numero.get((negocio_id, lead["numero_whatsapp_id"]))
        if canal is None:
            huerfanos_canal.append(telefono)
            continue

        contact_id = str(uuid.uuid4())
        conversation_id = str(uuid.uuid4())
        opportunity_id = str(uuid.uuid4())
        ahora = lead["actualizado"] or datetime.utcnow()
        creado = lead["creado"] or ahora

        bind.execute(sa.text(
            "INSERT INTO contacts (id, negocio_id, telefono, nombre, creado, actualizado) "
            "VALUES (:id, :negocio_id, :telefono, :nombre, :creado, :actualizado)"
        ), {
            "id": contact_id, "negocio_id": negocio_id, "telefono": telefono,
            "nombre": lead["nombre"], "creado": creado, "actualizado": ahora,
        })

        campana_origen_id = campana_por_negocio_nombre.get((negocio_id, lead["campana_origen"])) if lead["campana_origen"] else None
        bind.execute(sa.text(
            "INSERT INTO conversations (id, negocio_id, unidad_id, contact_id, canal_id, "
            "campana_origen_id, estado, asesor_asignado_id, paso_flujo, origen_contacto, "
            "visto_asesor, fallos_tecnicos, pausado_manual, revision_prioritaria, version, "
            "creado, actualizado) VALUES (:id, :negocio_id, :unidad_id, :contact_id, :canal_id, "
            ":campana_origen_id, 'activa', :asesor_asignado_id, :paso_flujo, :origen_contacto, "
            ":visto_asesor, :fallos_tecnicos, :pausado_manual, :revision_prioritaria, 0, "
            ":creado, :actualizado)"
        ), {
            "id": conversation_id, "negocio_id": negocio_id, "unidad_id": canal["unidad_id"],
            "contact_id": contact_id, "canal_id": canal["id"], "campana_origen_id": campana_origen_id,
            "asesor_asignado_id": lead["asesor_asignado"], "paso_flujo": lead["paso_flujo"],
            "origen_contacto": lead["origen_contacto"], "visto_asesor": lead["visto_asesor"],
            "fallos_tecnicos": lead["fallos_tecnicos"] or 0, "pausado_manual": lead["pausado_manual"],
            "revision_prioritaria": lead["revision_prioritaria"], "creado": creado, "actualizado": ahora,
        })

        bind.execute(sa.text(
            "INSERT INTO opportunities (id, negocio_id, unidad_id, conversation_id, contact_id, "
            "interes, producto_tipo, producto_marca, producto_modalidad, resultado, "
            "fecha_agendada, fecha_cierre, modalidad_pago, cuotas, medio_pago, version, "
            "creado, actualizado) VALUES (:id, :negocio_id, :unidad_id, :conversation_id, "
            ":contact_id, :interes, :producto_tipo, :producto_marca, :producto_modalidad, "
            ":resultado, :fecha_agendada, :fecha_cierre, :modalidad_pago, :cuotas, :medio_pago, "
            "0, :creado, :actualizado)"
        ), {
            "id": opportunity_id, "negocio_id": negocio_id, "unidad_id": canal["unidad_id"],
            "conversation_id": conversation_id, "contact_id": contact_id,
            "interes": lead["interes"], "producto_tipo": lead["producto_tipo"],
            "producto_marca": lead["producto_marca"], "producto_modalidad": lead["producto_modalidad"],
            "resultado": lead["resultado"], "fecha_agendada": lead["fecha_agendada"],
            "fecha_cierre": lead["fecha_cierre"], "modalidad_pago": lead["modalidad_pago"],
            "cuotas": lead["cuotas"], "medio_pago": lead["medio_pago"],
            "creado": creado, "actualizado": ahora,
        })

        mapa_contact[telefono] = contact_id
        mapa_conversation[telefono] = conversation_id
        mapa_opportunity[telefono] = opportunity_id

    # VALIDATE — cero Lead sin Canal resoluble. No se inventa ningún canal;
    # si hay huérfanos, se registran vía RegistroAuditoria (para no perder el
    # dato crudo en silencio) y la migración FALLA explícito — mismo
    # criterio que a46a93329345 con mensajes.negocio_id.
    if huerfanos_canal:
        for telefono in huerfanos_canal:
            bind.execute(sa.text(
                "INSERT INTO registro_auditoria (id, negocio_id, actor, accion, entidad_tipo, "
                "entidad_id, payload, creado) VALUES (:id, NULL, NULL, "
                "'migracion_gate53_canal_no_resuelto', 'lead', :telefono, :payload, :creado)"
            ), {
                "id": str(uuid.uuid4()), "telefono": telefono,
                "payload": '{"motivo": "numero_whatsapp_id no resuelve a ningun CanalWhatsApp del mismo Negocio"}',
                "creado": datetime.utcnow(),
            })
        raise RuntimeError(
            f"{len(huerfanos_canal)} Lead(s) sin Canal resoluble (numero_whatsapp_id no "
            f"coincide con ningún CanalWhatsApp de su Negocio): {huerfanos_canal}. No se "
            f"inventa ningún canal — registrados en RegistroAuditoria para revisión manual; "
            f"reintentar esta migración después de resolverlos (Gate 5.3, regla: no inventar "
            f"pertenencia)."
        )

    # Backfill de mensajes.conversation_id — doble candado negocio_id +
    # telefono (nunca telefono solo), subquery correlacionada portable
    # SQLite/Postgres, mismo patrón que a46a93329345 usó para mensajes.negocio_id.
    bind.execute(sa.text(
        "UPDATE mensajes SET conversation_id = ("
        "  SELECT c.id FROM conversations c "
        "  JOIN contacts ct ON ct.id = c.contact_id "
        "  WHERE ct.negocio_id = mensajes.negocio_id AND ct.telefono = mensajes.telefono"
        ") WHERE conversation_id IS NULL"
    ))

    # Backfill de eventos_lead — opportunity_id solo para los 2 tipos que ya
    # pertenecían a Opportunity (Diseño Técnico Gate 5.3 §8); NULL para
    # 'asignado'/'desasignado*' (pertenecen a Conversation).
    bind.execute(sa.text(
        "UPDATE eventos_lead SET "
        "negocio_id = (SELECT ct.negocio_id FROM contacts ct WHERE ct.telefono = eventos_lead.telefono LIMIT 1), "
        "conversation_id = ("
        "  SELECT c.id FROM conversations c JOIN contacts ct ON ct.id = c.contact_id "
        "  WHERE ct.telefono = eventos_lead.telefono LIMIT 1"
        ") "
        "WHERE conversation_id IS NULL"
    ))
    bind.execute(sa.text(
        "UPDATE eventos_lead SET opportunity_id = ("
        "  SELECT o.id FROM opportunities o WHERE o.conversation_id = eventos_lead.conversation_id LIMIT 1"
        ") WHERE opportunity_id IS NULL AND tipo IN ('resultado_cambiado', 'venta_registrada') "
        "AND conversation_id IS NOT NULL"
    ))

    huerfanos_eventos = bind.execute(sa.text(
        "SELECT COUNT(*) FROM eventos_lead WHERE conversation_id IS NULL"
    )).scalar()
    if huerfanos_eventos:
        raise RuntimeError(
            f"{huerfanos_eventos} evento(s) de eventos_lead sin Conversation resoluble "
            f"(telefono no corresponde a ningún Contact backfilleado) — no se fuerza NOT "
            f"NULL; revisar manualmente antes de reintentar (Gate 5.3, regla: no inventar "
            f"pertenencia)."
        )

    # Backfill de lineas_venta — doble candado opportunity_id + negocio_id
    # (la línea vigente de cada teléfono migra a la única Opportunity creada
    # para ese Lead, sin ambigüedad).
    bind.execute(sa.text(
        "UPDATE lineas_venta SET "
        "opportunity_id = ("
        "  SELECT o.id FROM opportunities o JOIN contacts ct ON ct.id = o.contact_id "
        "  WHERE ct.telefono = lineas_venta.telefono LIMIT 1"
        "), "
        "negocio_id = ("
        "  SELECT ct.negocio_id FROM contacts ct WHERE ct.telefono = lineas_venta.telefono LIMIT 1"
        ") "
        "WHERE opportunity_id IS NULL"
    ))

    huerfanos_lineas = bind.execute(sa.text(
        "SELECT COUNT(*) FROM lineas_venta WHERE opportunity_id IS NULL"
    )).scalar()
    if huerfanos_lineas:
        raise RuntimeError(
            f"{huerfanos_lineas} línea(s) de venta sin Opportunity resoluble — no se fuerza "
            f"NOT NULL; revisar manualmente antes de reintentar (Gate 5.3, regla: no "
            f"inventar pertenencia)."
        )

    # VALIDATE final — cardinalidad 1:1:1.
    total_leads = bind.execute(sa.text("SELECT COUNT(*) FROM leads")).scalar()
    total_contacts = bind.execute(sa.text("SELECT COUNT(*) FROM contacts")).scalar()
    total_conversations = bind.execute(sa.text("SELECT COUNT(*) FROM conversations")).scalar()
    total_opportunities = bind.execute(sa.text("SELECT COUNT(*) FROM opportunities")).scalar()
    if not (total_leads == total_contacts == total_conversations == total_opportunities):
        raise RuntimeError(
            f"Cardinalidad 1:1:1 rota tras el backfill — leads={total_leads}, "
            f"contacts={total_contacts}, conversations={total_conversations}, "
            f"opportunities={total_opportunities}. No se aplica CONTRACT sobre un estado "
            f"inconsistente."
        )

    # CONTRACT — solo tras validar arriba. lineas_venta.opportunity_id/
    # negocio_id ya no tienen huérfanos (verificado arriba): se endurecen a
    # NOT NULL, cerrando la ventana en la que un INSERT nuevo podría dejar
    # una línea sin la clave fuerte (regla crítica de LineaVenta).
    # eventos_lead.negocio_id/conversation_id igual. mensajes.conversation_id
    # se deja NULLABLE a propósito — un mensaje sin Conversation resoluble
    # (dato histórico previo a numero_whatsapp_id, caso borde real) no debe
    # bloquear el arranque; el código de aplicación ya tolera None ahí.
    with op.batch_alter_table('lineas_venta') as batch_op:
        batch_op.alter_column('opportunity_id', existing_type=sa.String(length=36), nullable=False)
        batch_op.alter_column('negocio_id', existing_type=sa.String(length=36), nullable=False)
    with op.batch_alter_table('eventos_lead') as batch_op:
        batch_op.alter_column('negocio_id', existing_type=sa.String(length=36), nullable=False)
        batch_op.alter_column('conversation_id', existing_type=sa.String(length=36), nullable=False)


def downgrade() -> None:
    """Downgrade schema + data. Revierte CONTRACT, luego borra únicamente
    las filas de contacts/conversations/opportunities creadas por esta
    migración (identificables: son TODAS las que existen, ya que M1 las creó
    vacías) y limpia las columnas de mensajes/eventos_lead/lineas_venta que
    esta migración pobló."""
    with op.batch_alter_table('eventos_lead') as batch_op:
        batch_op.alter_column('conversation_id', existing_type=sa.String(length=36), nullable=True)
        batch_op.alter_column('negocio_id', existing_type=sa.String(length=36), nullable=True)
    with op.batch_alter_table('lineas_venta') as batch_op:
        batch_op.alter_column('negocio_id', existing_type=sa.String(length=36), nullable=True)
        batch_op.alter_column('opportunity_id', existing_type=sa.String(length=36), nullable=True)

    bind = op.get_bind()
    bind.execute(sa.text("UPDATE lineas_venta SET opportunity_id = NULL, negocio_id = NULL"))
    bind.execute(sa.text("UPDATE eventos_lead SET negocio_id = NULL, conversation_id = NULL, opportunity_id = NULL"))
    bind.execute(sa.text("UPDATE mensajes SET conversation_id = NULL"))
    bind.execute(sa.text("DELETE FROM opportunities"))
    bind.execute(sa.text("DELETE FROM conversations"))
    bind.execute(sa.text("DELETE FROM contacts"))
