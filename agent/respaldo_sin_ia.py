# agent/respaldo_sin_ia.py — Derivación de un cliente cuando la IA no está disponible (Fase 1)
#
# Cuando el circuito de la IA está abierto (agent/circuito_ia.py), o una llamada a Claude falla de
# forma que ya no tiene sentido reintentar, Gabi NO llama a Claude y NO manda un texto técnico:
# responde UN mensaje automático (sin tokens) que saluda y dice que un asesor lo atenderá, y deja el
# caso en manos de una persona. `derivar_por_falla_ia` hace todo eso, siempre en este orden:
#
#   1. elegir asesor y asignarlo (`asignar_asesor_a_lead(automatico=True)`, que arma el reloj de
#      rotación a 30 min), o, si no hay ninguno, enviar el caso a la cola de supervisión;
#   2. fijar `paso_flujo = "derivado_asesor"` (sin eso el lead queda invisible en Inicio);
#   3. dejar el evento `derivado_sin_ia` en el Timeline;
#   4. enviar el texto fijo (origen `gabi_respaldo_sin_ia`) y guardarlo como mensaje de Gabi;
#   5. avisar al panel en tiempo real.
#
# Elección del asesor (distinta a la del flujo normal, que NO se toca): fuera de horario ningún
# asesor tiene el interruptor `disponible` encendido y aun así el caso no puede quedar sin dueño.
# Primero se intenta con los asesores activos y `disponible` (mismo criterio de nivel y carga de
# `asignacion.elegir_asesor_automatico`); si no hay ninguno, se asigna al asesor ACTIVO (no
# eliminado) con menos carga aunque no esté disponible, para que el caso ya sea suyo cuando empiece
# su turno — la rotación por Cron cuenta solo minutos EN turno (negocio abierto + asesor
# disponible), así que no lo rotará antes. La cola de supervisión es solo para cuando no existe
# ningún asesor activo.
#
# VENTANA DE 24 h DE WHATSAPP: solo la abre el último mensaje del CLIENTE. El mensaje automático NO
# la renueva ni la extiende. Por eso, si el último mensaje del cliente tiene más de 24 h, no se manda
# texto libre (Meta lo rechazaría) y el caso va a la cola de supervisión para que una persona decida
# cómo retomarlo (p. ej. con una plantilla).
#
# Regla crítica: nunca se toca un lead con resultado cerrado ni vendido/agendado/postventa, ni uno que
# ya tiene asesor, está pausado o está en la cola: no se cambia su estado, no se le asigna nada y no se
# le vuelve a mandar el texto (idempotente; el origen además agrupa 60 min como cinturón).
#
# No manda correo por lead: durante una caída serían decenas. El equipo ve los casos en la cola de
# supervisión / en su bandeja, y el dueño de la plataforma recibe UN resumen (agent/notificaciones.py).

import logging
from datetime import datetime, timedelta

from agent import envios
from agent.asignacion import elegir_asesor_automatico
from agent.memory import (
    RESULTADOS_QUE_EL_BARRIDO_NO_TOCA, TIPO_EVENTO_DERIVADO_SIN_IA, actualizar_lead, asignar_asesor_a_lead,
    contar_leads_activos, enviar_a_cola_de_supervision, listar_asesores, obtener_lead,
    obtener_timestamp_ultimo_mensaje_usuario, registrar_evento_lead,
)
from agent.services.servicio_conversacion import servicio_conversacion
from agent.services.servicio_inteligencia import servicio_inteligencia
from agent.tiempo_real import gestor_conexiones
from agent.tools import describir_horario_atencion, obtener_estado_horario_atencion, obtener_proxima_apertura

logger = logging.getLogger("agentkit")

VENTANA_SERVICIO = timedelta(hours=24)


def _lead_fuera_de_alcance(lead: dict) -> bool:
    """Un lead que una persona ya cerró o trabajó: este módulo nunca lo toca."""
    return (
        (lead.get("resultado") or "") in RESULTADOS_QUE_EL_BARRIDO_NO_TOCA
        or lead.get("cerrado_definitivamente_en") is not None
    )


def _lead_ya_derivado(lead: dict) -> bool:
    return bool(lead.get("asesor_asignado") or lead.get("pausado_manual") or lead.get("escalado_supervision_en"))


async def elegir_asesor_para_modo_sin_ia(negocio_id: str | None, interes: str | None) -> str | None:
    """El asesor al que va el caso en modo sin IA, o None si no existe ningún asesor activo."""
    if negocio_id is None:
        return None
    asesores = await listar_asesores(negocio_id)  # solo activos y no eliminados
    if not asesores:
        return None
    if any(a.get("disponible") for a in asesores):
        elegido = await elegir_asesor_automatico(interes or "", negocio_id)
        if elegido:
            return elegido
    cargas = [(await contar_leads_activos(a["username"]), a.get("nombre") or "", a["username"]) for a in asesores]
    return min(cargas)[2]


async def _texto_para_el_cliente(negocio_id: str | None, nombre: str | None) -> str:
    """El texto fijo que corresponde AHORA: dentro del horario; fuera pero el negocio abre hoy o
    mañana (se cita el horario); o un día de descanso / 2 días o más sin atención (se cita cuándo abre)."""
    estado = await obtener_estado_horario_atencion(negocio_id)
    if estado["dentro_de_horario"]:
        return servicio_inteligencia.obtener_mensaje_sin_ia("dentro_horario", nombre)
    proxima = await obtener_proxima_apertura(negocio_id)
    if proxima is not None and (not proxima["hoy_es_dia_de_atencion"] or proxima["dias_de_diferencia"] >= 2):
        return servicio_inteligencia.obtener_mensaje_sin_ia(
            "fin_de_semana", nombre, dia=proxima["dia"], hora=proxima["hora"],
        )
    return servicio_inteligencia.obtener_mensaje_sin_ia(
        "fuera_horario", nombre, horario=await describir_horario_atencion(negocio_id),
    )


async def derivar_por_falla_ia(telefono: str, canal: dict | None, motivo: str, *, proveedor=None) -> dict:
    """Ver el comentario de cabecera. `motivo` solo queda en el evento del Timeline (credito,
    tope_gasto, auth, transitorio, circuito_abierto, falla_tecnica_repetida, adjunto…). `proveedor`
    es el de WhatsApp (main.py y los scripts lo pasan; sin él se crea el configurado por entorno).

    Devuelve {"accion": ..., "asesor": ..., "texto_enviado": bool}; `accion` es "derivado_asesor",
    "cola_supervision", "ya_derivado", "no_aplica" (lead cerrado/vendido/agendado/postventa) o
    "sin_lead". Idempotente."""
    negocio_id = (canal or {}).get("negocio_id")
    lead = await obtener_lead(telefono, negocio_id=negocio_id)
    if lead is None:
        logger.warning(f"Modo sin IA: {telefono} no tiene lead — no se deriva")
        return {"accion": "sin_lead", "asesor": None, "texto_enviado": False}
    if _lead_fuera_de_alcance(lead):
        logger.info(f"Modo sin IA: {telefono} está cerrado/vendido/agendado/postventa — no se toca")
        return {"accion": "no_aplica", "asesor": None, "texto_enviado": False}
    if _lead_ya_derivado(lead):
        logger.info(f"Modo sin IA: {telefono} ya está con un asesor, pausado o en la cola — no se repite nada")
        return {"accion": "ya_derivado", "asesor": lead.get("asesor_asignado"), "texto_enviado": False}

    # La ventana de 24 h la abre el último mensaje del cliente; este aviso no la extiende.
    ultimo_del_cliente = await obtener_timestamp_ultimo_mensaje_usuario(telefono)
    ventana_abierta = ultimo_del_cliente is not None and datetime.utcnow() - ultimo_del_cliente <= VENTANA_SERVICIO

    # 1. Asesor (o cola de supervisión).
    asesor = None
    if ventana_abierta:
        try:
            asesor = await elegir_asesor_para_modo_sin_ia(negocio_id, lead.get("interes"))
            if asesor:
                await asignar_asesor_a_lead(telefono, asesor, automatico=True)
        except Exception:
            logger.exception(f"Modo sin IA: no se pudo asignar a {telefono} — pasa a la cola de supervisión")
            asesor = None
    if asesor:
        destino = "asesor"
    else:
        destino = "supervision"
        await enviar_a_cola_de_supervision(telefono, motivo="sin_ia_sin_asesor" if ventana_abierta else "sin_ia_ventana_cerrada")

    # 2. paso_flujo — sin él el lead queda invisible en Inicio.
    await actualizar_lead(telefono, paso_flujo="derivado_asesor")

    # 3. Evento en el Timeline.
    descripcion = (
        f"La IA no estaba disponible — el caso se asignó automáticamente a {asesor} y el cliente recibió un aviso automático"
        if asesor else
        "La IA no estaba disponible y no hay asesor al que asignarlo"
        + (" — el caso pasó a la cola de supervisión" if ventana_abierta
           else " (la ventana de 24 h de WhatsApp ya cerró) — el caso pasó a la cola de supervisión sin enviar texto")
    )
    try:
        await registrar_evento_lead(
            telefono, tipo=TIPO_EVENTO_DERIVADO_SIN_IA, descripcion=descripcion, autor=None,
            payload={"motivo": motivo, "destino": destino, "asesor": asesor, "ventana_abierta": ventana_abierta},
        )
    except Exception:
        logger.exception(f"Modo sin IA: no se pudo registrar el evento de {telefono}")

    # 4. Texto fijo al cliente (solo si la ventana de 24 h está abierta).
    texto_enviado = False
    if ventana_abierta:
        if proveedor is None:
            from agent.providers import obtener_proveedor
            proveedor = obtener_proveedor()
        texto = await _texto_para_el_cliente(negocio_id, lead.get("nombre"))
        # El origen va literal (no como constante): tests/test_capa_central_de_envios.py comprueba por
        # texto que todo envío del código usa un origen registrado en envios.ORIGENES.
        resultado = await envios.enviar_texto(proveedor, telefono, texto, origen="gabi_respaldo_sin_ia", canal=canal)
        if not resultado.bloqueado:
            _enviado, wamid = resultado
            guardado = await servicio_conversacion.guardar_mensaje(
                telefono, "assistant", texto, negocio_id=negocio_id,
                mensaje_id_meta=wamid, estado_envio=resultado.estado_envio,
            )
            texto_enviado = bool(resultado.enviado)
            # 5. Panel en tiempo real — cosmético: nunca puede deshacer lo anterior.
            try:
                await gestor_conexiones.emitir_mensaje_nuevo(guardado["conversation_id"])
            except Exception:
                logger.exception(f"Modo sin IA: no se pudo avisar al panel del mensaje de {telefono}")

    logger.warning(
        f"Modo sin IA: {telefono} derivado a {asesor or 'la cola de supervisión'} "
        f"(motivo={motivo}, texto_enviado={texto_enviado})"
    )
    return {"accion": "derivado_asesor" if asesor else "cola_supervision", "asesor": asesor, "texto_enviado": texto_enviado}
