# tests/test_vista_inicio_bandeja.py — 2026-10-06 (P2).
#
# "Ver los N en Conversaciones" de Inicio lleva a `GET /dashboard/conversaciones
# ?vista=<grupo>`: una lista donde están EXACTAMENTE los casos del bloque de
# Inicio. El criterio no se reimplementa (se invocan las mismas funciones que
# `inicio_json`), así que acá se prueba la PARIDAD: total de la vista == total
# del bloque en Inicio, y los mismos casos, por rol.
#
# Datos sintéticos únicamente.

import json
from datetime import datetime, timedelta
from types import SimpleNamespace

from sqlalchemy import event, update

from agent import dashboard, memory as mem


# ── Helpers ──────────────────────────────────────────────────────────────

async def _negocio_con_canal(codigo: str, telefono_canal: str):
    negocio = await mem.crear_negocio(f"Negocio {codigo}", codigo)
    canal = await mem.crear_canal_whatsapp(
        nombre=f"Canal {codigo}", phone_number_id=telefono_canal, negocio_id=negocio["id"],
    )
    return negocio, canal


async def _lead(
    negocio, canal, telefono: str, *, asesor: str | None = None, pausado: bool = False,
    escalado: bool = False, resultado: str | None = None, paso_flujo: str | None = None,
    fecha_agendada: datetime | None = None,
):
    await mem.resolver_conversation_activa(telefono, negocio["id"], canal["id"])
    await mem.actualizar_lead(telefono, nombre=f"Cliente {telefono[-4:]}", negocio_id=negocio["id"])
    async with mem.async_session() as session:
        lead = await session.get(mem.Lead, telefono)
        lead.asesor_asignado = asesor
        lead.pausado_manual = pausado
        lead.resultado = resultado
        lead.paso_flujo = paso_flujo
        lead.fecha_agendada = fecha_agendada
        if escalado:
            lead.escalado_supervision_en = datetime.utcnow()
        await session.commit()


async def _mensaje(negocio, telefono: str, role: str, contenido: str, horas: float):
    m = await mem.guardar_mensaje(telefono, role, contenido, negocio["id"])
    async with mem.async_session() as session:
        await session.execute(
            update(mem.Mensaje).where(mem.Mensaje.id == m["id"]).values(
                timestamp=datetime.utcnow() - timedelta(hours=horas)
            )
        )
        await session.commit()


async def _usuario(negocio, username: str, rol: str):
    await mem.crear_usuario(username, "pw12345", username.title(), rol, negocio["id"])
    return await mem.obtener_usuario(username, negocio_id=negocio["id"])


def _request(**query):
    return SimpleNamespace(query_params=query)


async def _bandeja(usuario: dict, **kw) -> dict:
    por_pagina = kw.pop("por_pagina", None)
    args = dict(
        request=_request(**({"por_pagina": por_pagina} if por_pagina else {})), usuario=usuario, q="", asesor="",
        alcance="", resultado="", orden="actividad", dir="desc", pagina=1,
        por_pagina=por_pagina or dashboard.POR_PAGINA_PIPELINE,
    )
    args.update(kw)
    return json.loads((await dashboard.bandeja_conversaciones(**args)).body)


async def _inicio(usuario: dict) -> dict:
    return json.loads((await dashboard.inicio_json(usuario=usuario)).body)


async def _escenario(codigo: str, canal_tel: str, base: int):
    """Un negocio con un caso de cada grupo de Inicio, más ruido que NO debe entrar."""
    negocio, canal = await _negocio_con_canal(codigo, canal_tel)
    t = {n: f"519{base + i:08d}" for i, n in enumerate(
        ["escalado", "sin_asesor", "esp_a1", "esp_a2", "esp_cerrada", "respondido", "gabi_sola", "cita", "vencida"]
    )}
    ahora_lima = datetime.utcnow() - timedelta(hours=5)
    await _lead(negocio, canal, t["escalado"], escalado=True, paso_flujo="derivado_asesor")
    await _lead(negocio, canal, t["sin_asesor"], paso_flujo="derivado_asesor")
    await _lead(negocio, canal, t["esp_a1"], asesor="asesor1")
    await _lead(negocio, canal, t["esp_a2"], asesor="asesor2", resultado="vendido")
    await _lead(negocio, canal, t["esp_cerrada"], asesor="asesor1")
    await _lead(negocio, canal, t["respondido"], asesor="asesor1")
    await _lead(negocio, canal, t["gabi_sola"])
    await _lead(negocio, canal, t["cita"], asesor="asesor1", resultado="agendado",
                fecha_agendada=ahora_lima + timedelta(days=1))
    await _lead(negocio, canal, t["vencida"], asesor="asesor2", resultado="agendado",
                fecha_agendada=ahora_lima - timedelta(days=1))
    await _mensaje(negocio, t["escalado"], "user", "Necesito ayuda", 3)
    await _mensaje(negocio, t["esp_a1"], "user", "Quiero una cocina", 2)           # vence antes
    await _mensaje(negocio, t["esp_a2"], "user", "Se dañó la hornilla", 1)
    await _mensaje(negocio, t["esp_cerrada"], "user", "Hola", 30)                  # ventana cerrada
    await _mensaje(negocio, t["respondido"], "user", "Precio?", 3)
    await _mensaje(negocio, t["respondido"], "asesor", "Te lo paso", 2)
    await _mensaje(negocio, t["gabi_sola"], "user", "Buenas", 1)
    # `resultado` de la Bandeja sale de la Opportunity vigente (no del Lead).
    conv_a2 = (await mem.resolver_conversation_ids_por_telefono(negocio["id"], [t["esp_a2"]]))[t["esp_a2"]]
    async with mem.async_session() as session:
        await session.execute(
            update(mem.Opportunity).values(resultado="vendido").where(mem.Opportunity.conversation_id == conv_a2)
        )
        await session.commit()
    await _usuario(negocio, "admin1", "admin")
    await _usuario(negocio, "asesor1", "asesor")
    await _usuario(negocio, "asesor2", "asesor")
    return negocio, t


def _telefonos(cuerpo: dict) -> list[str]:
    return [f["telefono"] for f in cuerpo["conversaciones"]]


# ── Paridad con Inicio ───────────────────────────────────────────────────

async def test_responde_ahora_coincide_con_el_bloque_de_inicio_para_admin():
    negocio, t = await _escenario("vib1", "40200000001", 1000)
    admin = await mem.obtener_usuario("admin1", negocio_id=negocio["id"])

    inicio = await _inicio(admin)
    cuerpo = await _bandeja(admin, vista="responde_ahora")

    # R4 (2026-10-07): "Responde ahora" = escalados + sin asesor + esperando con la ventana ABIERTA; los de
    # ventana cerrada tienen su propia vista (`ventana_cerrada`). `ahora_total` conserva su significado de
    # siempre (incluye los cerrados); el total del bloque es `responde_ahora_total`.
    totales = inicio["zona_accion"]["totales"]
    assert cuerpo["total"] == totales["responde_ahora_total"] == len(cuerpo["conversaciones"]) == 4
    assert totales["ahora_total"] == 5
    # Orden: escalado, sin asesor, esperando con ventana abierta (vence antes primero).
    assert _telefonos(cuerpo) == [t["escalado"], t["sin_asesor"], t["esp_a1"], t["esp_a2"]]
    cats = [f["inicio"]["categoria"] for f in cuerpo["conversaciones"]]
    assert cats == ["escalado", "sin_asesor", "cliente_esperando", "cliente_esperando"]
    # Los ítems de Inicio del grupo "Responde ahora" están en la lista; los de ventana cerrada, en su vista.
    items_inicio = {
        i["conversation_id"] for i in inicio["zona_accion"]["items"]
        if i["categoria"] in ("escalado", "sin_asesor") or i.get("grupo") == "responde_ahora"
    }
    assert items_inicio == {f["id"] for f in cuerpo["conversaciones"]}
    cerradas = await _bandeja(admin, vista="ventana_cerrada")
    assert _telefonos(cerradas) == [t["esp_cerrada"]] and cerradas["total"] == totales["esperando_ventana_cerrada"] == 1


async def test_cada_vista_tiene_el_mismo_total_que_su_bloque_en_inicio():
    negocio, t = await _escenario("vib2", "40200000002", 2000)
    admin = await mem.obtener_usuario("admin1", negocio_id=negocio["id"])
    totales = (await _inicio(admin))["zona_accion"]["totales"]

    esperados = {
        "sin_asesor": totales["sin_asesor"], "escalados": totales["escalados"],
        "esperando": totales["cliente_esperando"], "citas": totales["citas_proximas"],
        "citas_vencidas": totales["citas_vencidas"], "responde_ahora": totales["responde_ahora_total"],
        "ventana_cerrada": totales["esperando_ventana_cerrada"],
    }
    for vista, total in esperados.items():
        cuerpo = await _bandeja(admin, vista=vista)
        assert cuerpo["total"] == total, vista
        assert cuerpo["vista"] == vista
    assert _telefonos(await _bandeja(admin, vista="sin_asesor")) == [t["sin_asesor"]]
    assert _telefonos(await _bandeja(admin, vista="escalados")) == [t["escalado"]]
    assert _telefonos(await _bandeja(admin, vista="citas")) == [t["cita"]]
    assert _telefonos(await _bandeja(admin, vista="citas_vencidas")) == [t["vencida"]]
    # esperando incluye también al escalado (su último mensaje es del cliente), igual que `totales`.
    assert set(_telefonos(await _bandeja(admin, vista="esperando"))) == {
        t["escalado"], t["esp_a1"], t["esp_a2"], t["esp_cerrada"],
    }


async def test_el_asesor_solo_ve_lo_suyo_y_coincide_con_su_inicio():
    negocio, t = await _escenario("vib3", "40200000003", 3000)
    asesor = await mem.obtener_usuario("asesor1", negocio_id=negocio["id"])

    inicio = await _inicio(asesor)
    cuerpo = await _bandeja(asesor, vista="responde_ahora")
    totales = inicio["zona_accion"]["totales"]
    assert cuerpo["total"] == totales["responde_ahora_total"] == 1
    assert totales["ahora_total"] == 2                                    # significado de siempre: incluye la cerrada
    assert set(_telefonos(cuerpo)) == {t["esp_a1"]}                       # nada de asesor2 ni de supervisión
    cerrada = await _bandeja(asesor, vista="ventana_cerrada")
    assert _telefonos(cerrada) == [t["esp_cerrada"]] and cerrada["total"] == totales["esperando_ventana_cerrada"]

    # sin_asesor y escalados son solo de visión total: para un asesor, lista vacía (no su cartera).
    for vista in ("sin_asesor", "escalados"):
        vacio = await _bandeja(asesor, vista=vista)
        assert vacio["total"] == 0 and vacio["conversaciones"] == []
    # Intentar ampliar el alcance con alcance=todos / asesor=otro no sirve.
    ampliado = await _bandeja(asesor, vista="responde_ahora", alcance="todos", asesor="asesor2")
    assert set(_telefonos(ampliado)) == {t["esp_a1"]}
    ampliada = await _bandeja(asesor, vista="ventana_cerrada", alcance="todos", asesor="asesor2")
    assert set(_telefonos(ampliada)) == {t["esp_cerrada"]}
    assert _telefonos(await _bandeja(asesor, vista="citas")) == [t["cita"]]


# ── Contenido de cada fila ───────────────────────────────────────────────

async def test_cada_fila_trae_el_bloque_inicio_con_la_ventana_de_meta():
    negocio, t = await _escenario("vib4", "40200000004", 4000)
    admin = await mem.obtener_usuario("admin1", negocio_id=negocio["id"])
    cuerpo = await _bandeja(admin, vista="esperando")
    por_tel = {f["telefono"]: f for f in cuerpo["conversaciones"]}

    abierta = por_tel[t["esp_a1"]]["inicio"]
    assert set(abierta) == {"categoria", "ultimo_mensaje_cliente_en", "ventana_vence_en", "ventana_abierta"}
    assert abierta["ventana_abierta"] is True
    assert abierta["ultimo_mensaje_cliente_en"].endswith("Z") and abierta["ventana_vence_en"].endswith("Z")
    assert por_tel[t["esp_cerrada"]]["inicio"]["ventana_abierta"] is False
    # Se conserva el resto de la fila de la Bandeja (aditivo).
    assert {"id", "telefono", "nombre", "resultado", "ultimo_mensaje", "mensajes_pendientes"} <= set(por_tel[t["esp_a1"]])


async def test_sin_vista_la_fila_no_trae_inicio_ni_cambia_el_contrato():
    negocio, _ = await _escenario("vib5", "40200000005", 5000)
    admin = await mem.obtener_usuario("admin1", negocio_id=negocio["id"])
    cuerpo = await _bandeja(admin)
    assert "vista" not in cuerpo
    assert all("inicio" not in f for f in cuerpo["conversaciones"])
    assert cuerpo["total"] == 9


async def test_vista_invalida_se_ignora_como_resultado():
    negocio, _ = await _escenario("vib6", "40200000006", 6000)
    admin = await mem.obtener_usuario("admin1", negocio_id=negocio["id"])
    sin_vista = await _bandeja(admin)
    invalida = await _bandeja(admin, vista="no_existe")
    assert invalida["total"] == sin_vista["total"] == 9
    assert "vista" not in invalida and all("inicio" not in f for f in invalida["conversaciones"])


# ── Combinaciones, paginación y consultas ────────────────────────────────

async def test_la_vista_se_combina_con_la_busqueda_y_el_resultado():
    negocio, t = await _escenario("vib7", "40200000007", 7000)
    admin = await mem.obtener_usuario("admin1", negocio_id=negocio["id"])

    cocina = await _bandeja(admin, vista="responde_ahora", q="cocina")
    assert _telefonos(cocina) == [t["esp_a1"]] and cocina["total"] == 1

    vendidos = await _bandeja(admin, vista="responde_ahora", resultado="vendido")
    assert _telefonos(vendidos) == [t["esp_a2"]]


async def test_paginacion_sobre_los_ids_y_tamano_por_defecto_de_50():
    negocio, canal = await _negocio_con_canal("vib8", "40200000008")
    await _usuario(negocio, "admin1", "admin")
    admin = await mem.obtener_usuario("admin1", negocio_id=negocio["id"])
    telefonos = [f"519{8000 + i:08d}" for i in range(55)]
    for i, tel in enumerate(telefonos):
        await _lead(negocio, canal, tel, asesor="asesor1")
        await _mensaje(negocio, tel, "user", "Hola", 0.5 + i * 0.1)   # i=0 es el más reciente

    p1 = await _bandeja(admin, vista="esperando")
    assert p1["total"] == 55 and len(p1["conversaciones"]) == 50 and p1["por_pagina"] == 50
    p2 = await _bandeja(admin, vista="esperando", pagina=2)
    assert len(p2["conversaciones"]) == 5
    todas = _telefonos(p1) + _telefonos(p2)
    assert len(set(todas)) == 55
    # Orden de ventana abierta: la que vence antes (mensaje más viejo) primero.
    assert todas == list(reversed(telefonos))

    chica = await _bandeja(admin, vista="esperando", por_pagina=20, pagina=3)
    assert chica["por_pagina"] == 20 and len(chica["conversaciones"]) == 15


async def test_la_cantidad_de_consultas_no_crece_con_la_cantidad_de_casos():
    async def contar(n: int) -> int:
        codigo = f"vibq{n}"
        negocio, canal = await _negocio_con_canal(codigo, f"4030000{n:04d}")
        await _usuario(negocio, "admin1", "admin")
        admin = await mem.obtener_usuario("admin1", negocio_id=negocio["id"])
        for i in range(n):
            tel = f"519{n * 1000 + i:08d}"
            await _lead(negocio, canal, tel, asesor="asesor1")
            await _mensaje(negocio, tel, "user", "Hola", 1)
        consultas = []

        def _cuenta(conn, cursor, statement, parameters, context, executemany):
            consultas.append(statement)

        event.listen(mem.engine.sync_engine, "before_cursor_execute", _cuenta)
        try:
            cuerpo = await _bandeja(admin, vista="esperando")
        finally:
            event.remove(mem.engine.sync_engine, "before_cursor_execute", _cuenta)
        assert cuerpo["total"] == n
        return len(consultas)

    assert await contar(3) == await contar(25)


async def test_no_cruza_negocios():
    negocio_a, t_a = await _escenario("vibA", "40200000010", 9000)
    negocio_b, canal_b = await _negocio_con_canal("vibB", "40200000011")
    await _lead(negocio_b, canal_b, "51999000001", asesor="asesorB")
    await _mensaje(negocio_b, "51999000001", "user", "Hola", 1)
    await _usuario(negocio_b, "adminb", "admin")
    admin_b = await mem.obtener_usuario("adminb", negocio_id=negocio_b["id"])

    cuerpo = await _bandeja(admin_b, vista="responde_ahora")
    assert _telefonos(cuerpo) == ["51999000001"] and cuerpo["total"] == 1


# ── Función pura de composición ──────────────────────────────────────────

def test_componer_vista_no_repite_telefonos_y_respeta_supervision():
    ahora = datetime.utcnow()
    esperando = [{
        "telefono": "1", "conversation_id": "c1", "ultimo_mensaje_cliente_en": ahora,
        "ventana_vence_en": ahora + timedelta(hours=24), "ventana_abierta": True,
    }]
    asignar = [
        {"telefono": "1", "escalado_supervision_en": ahora},   # también está esperando
        {"telefono": "2", "escalado_supervision_en": None},
    ]
    vista = mem.componer_vista_inicio("responde_ahora", esperando, asignar, [], [], True)
    assert [(e["telefono"], e["categoria"]) for e in vista] == [("1", "escalado"), ("2", "sin_asesor")]
    # El escalado que también espera lleva su ventana; el otro no.
    assert vista[0]["ventana_abierta"] is True and vista[1]["ventana_abierta"] is None
    # Sin supervisión (asesor / acotado a un asesor) solo quedan los que esperan.
    assert [e["telefono"] for e in mem.componer_vista_inicio("responde_ahora", esperando, asignar, [], [], False)] == ["1"]
    assert mem.componer_vista_inicio("escalados", esperando, asignar, [], [], False) == []
    assert mem.componer_vista_inicio("desconocida", esperando, asignar, [], [], True) == []
