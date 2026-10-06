# tests/test_filtro_sin_resultado_lista_chats.py — 2026-10-06.
#
# Pedido del equipo: el filtro por resultado de la lista de chats no ofrecía
# "Sin resultado" y no había forma de encontrar los chats a los que todavía
# hay que asignarles un resultado. El filtro (punto 4, 2026-09-28) solo
# aceptaba los valores de RESULTADOS; un valor desconocido se ignoraba y se
# listaba todo. No había un motivo escrito para dejarlo fuera: simplemente se
# reusó el catálogo de la Ficha, que solo tiene resultados guardados.
#
# Definición usada: `resultado=sin_resultado` = Conversations ACTIVAS cuya
# Opportunity vigente tiene resultado NULL o "" (o que no tiene Opportunity),
# SIN importar si ya hubo gestión (asesor asignado / mensajes de asesor): es
# exactamente el conjunto de filas que la lista pinta con el badge "Sin
# resultado". NO incluye resultados guardados como `sin_respuesta`.

import os

os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")
os.environ.setdefault("WHATSAPP_PROVIDER", "meta")

from sqlalchemy import delete

from agent import dashboard
from agent import memory as mem


async def _negocio_con_canal(codigo: str, telefono_canal: str):
    negocio = await mem.crear_negocio(f"Negocio {codigo}", codigo)
    canal = await mem.crear_canal_whatsapp(
        nombre=f"Canal {codigo}", phone_number_id=telefono_canal, negocio_id=negocio["id"],
    )
    return negocio, canal


async def _abrir(negocio: dict, canal: dict, telefono: str, resultado: str | None = None):
    conversation, opportunity = await mem.resolver_conversation_activa(
        telefono, negocio["id"], canal["id"], unidad_id=canal.get("unidad_id"),
    )
    if resultado is not None:
        async with mem.async_session() as session:
            o = await session.get(mem.Opportunity, opportunity.id)
            o.resultado = resultado
            await session.commit()
    return conversation, opportunity


async def _telefonos(negocio_id: str, **kwargs) -> set[str]:
    filas, _ = await mem.listar_conversaciones_activas(negocio_id=negocio_id, por_pagina=200, **kwargs)
    return {f["telefono"] for f in filas}


async def _escenario(codigo: str, telefono_canal: str, base: int):
    """Un negocio con una conversación por cada situación relevante."""
    negocio, canal = await _negocio_con_canal(codigo, telefono_canal)
    tel = {n: f"519{base + i:08d}" for i, n in enumerate(
        ["nuevo", "vacio", "agendado", "sin_respuesta", "vendido", "con_gestion", "sin_opp", "cerrada"]
    )}
    await _abrir(negocio, canal, tel["nuevo"])                       # resultado NULL
    await _abrir(negocio, canal, tel["vacio"], resultado="")        # "" (quitado a mano)
    await _abrir(negocio, canal, tel["agendado"], resultado="agendado")
    await _abrir(negocio, canal, tel["sin_respuesta"], resultado="sin_respuesta")
    await _abrir(negocio, canal, tel["vendido"], resultado="vendido")
    conv_gestion, _ = await _abrir(negocio, canal, tel["con_gestion"])
    conv_sin_opp, _ = await _abrir(negocio, canal, tel["sin_opp"])
    conv_cerrada, _ = await _abrir(negocio, canal, tel["cerrada"])
    async with mem.async_session() as session:
        c = await session.get(mem.Conversation, conv_gestion.id)
        c.asesor_asignado_id = "asesor1"          # gestión: ya tiene asesor
        f = await session.get(mem.Conversation, conv_cerrada.id)
        f.estado = "cerrada"                      # una conversación cerrada no es de la bandeja
        await session.execute(delete(mem.Opportunity).where(mem.Opportunity.conversation_id == conv_sin_opp.id))
        await session.commit()
    return negocio, tel


async def test_sin_resultado_devuelve_solo_los_chats_activos_sin_resultado():
    negocio, tel = await _escenario("fsr1", "10000000501", 1000)

    sin_resultado = await _telefonos(negocio["id"], resultado="sin_resultado")

    # NULL, "", ya atendido por un asesor y sin Opportunity: todos se pintan "Sin resultado".
    assert sin_resultado == {tel["nuevo"], tel["vacio"], tel["con_gestion"], tel["sin_opp"]}
    # Con resultado (aunque sea "sin_respuesta", que es un resultado CERRADO guardado) no.
    for con_resultado in ("agendado", "sin_respuesta", "vendido"):
        assert tel[con_resultado] not in sin_resultado
    # Una conversación cerrada nunca está en la bandeja.
    assert tel["cerrada"] not in sin_resultado


async def test_el_total_es_coherente_con_las_filas_y_con_el_paginado():
    negocio, _ = await _escenario("fsr2", "10000000502", 2000)

    filas, total = await mem.listar_conversaciones_activas(negocio["id"], resultado="sin_resultado", por_pagina=200)
    assert total == len(filas) == 4

    pagina1, total1 = await mem.listar_conversaciones_activas(negocio["id"], resultado="sin_resultado", por_pagina=3)
    pagina2, total2 = await mem.listar_conversaciones_activas(
        negocio["id"], resultado="sin_resultado", por_pagina=3, pagina=2,
    )
    assert total1 == total2 == 4
    assert len(pagina1) == 3 and len(pagina2) == 1
    assert {f["id"] for f in pagina1}.isdisjoint({f["id"] for f in pagina2})
    # Cada fila devuelta muestra efectivamente "sin resultado" (coherente con el badge).
    assert all(not f["resultado"] for f in pagina1 + pagina2)


async def test_sin_resultado_se_combina_con_la_busqueda_y_con_el_orden():
    negocio, tel = await _escenario("fsr3", "10000000503", 3000)
    await mem.guardar_mensaje(tel["nuevo"], "user", "quiero una terma a gas", negocio_id=negocio["id"])
    await mem.guardar_mensaje(tel["agendado"], "user", "quiero una terma a gas", negocio_id=negocio["id"])

    encontrados = await _telefonos(negocio["id"], resultado="sin_resultado", busqueda="terma")
    assert encontrados == {tel["nuevo"]}  # el agendado también dice "terma", pero tiene resultado

    asc, _ = await mem.listar_conversaciones_activas(
        negocio["id"], resultado="sin_resultado", orden="actividad", direccion="asc", por_pagina=200,
    )
    desc, _ = await mem.listar_conversaciones_activas(
        negocio["id"], resultado="sin_resultado", orden="actividad", direccion="desc", por_pagina=200,
    )
    assert [f["id"] for f in asc] == [f["id"] for f in reversed(desc)]


async def test_los_filtros_de_siempre_no_cambian():
    negocio, tel = await _escenario("fsr4", "10000000504", 4000)
    assert await _telefonos(negocio["id"], resultado="agendado") == {tel["agendado"]}
    assert await _telefonos(negocio["id"], resultado="sin_respuesta") == {tel["sin_respuesta"]}
    # Sin filtro: las 7 activas (la cerrada no cuenta).
    assert len(await _telefonos(negocio["id"])) == 7


async def test_sin_resultado_no_cruza_negocios():
    negocio_a, tel_a = await _escenario("fsr5a", "10000000505", 5000)
    negocio_b, tel_b = await _escenario("fsr5b", "10000000506", 6000)
    solo_a = await _telefonos(negocio_a["id"], resultado="sin_resultado")
    assert solo_a == {tel_a["nuevo"], tel_a["vacio"], tel_a["con_gestion"], tel_a["sin_opp"]}
    assert solo_a.isdisjoint(tel_b.values())


def _usuario(rol: str, username: str, negocio_id: str) -> dict:
    return {"rol": rol, "username": username, "negocio_id": negocio_id, "nombre": username}


async def _llamar_endpoint(usuario: dict, resultado: str = "", **kwargs) -> dict:
    import json

    respuesta = await dashboard.bandeja_conversaciones(
        request=None, usuario=usuario, q=kwargs.get("q", ""), asesor="", alcance="todos",
        resultado=resultado, orden="actividad", dir="desc", pagina=1, por_pagina=50,
    )
    return json.loads(respuesta.body)


async def test_endpoint_acepta_sin_resultado_y_lo_aplica():
    negocio, tel = await _escenario("fsr6", "10000000507", 7000)
    cuerpo = await _llamar_endpoint(_usuario("admin", "jefe", negocio["id"]), resultado="sin_resultado")
    assert cuerpo["total"] == 4
    assert {c["telefono"] for c in cuerpo["conversaciones"]} == {
        tel["nuevo"], tel["vacio"], tel["con_gestion"], tel["sin_opp"],
    }
    assert all(not c["resultado"] for c in cuerpo["conversaciones"])


async def test_endpoint_sigue_ignorando_valores_desconocidos_y_acepta_los_del_catalogo():
    negocio, tel = await _escenario("fsr7", "10000000508", 8000)
    admin = _usuario("admin", "jefe", negocio["id"])
    # Valor inventado: se ignora (comportamiento de siempre) y se lista todo.
    assert (await _llamar_endpoint(admin, resultado="inventado"))["total"] == 7
    cuerpo = await _llamar_endpoint(admin, resultado="vendido")
    assert [c["telefono"] for c in cuerpo["conversaciones"]] == [tel["vendido"]]


async def test_un_asesor_solo_ve_sus_chats_sin_resultado():
    negocio, tel = await _escenario("fsr8", "10000000509", 9000)
    # `asesor1` solo tiene asignado "con_gestion" (ver `_escenario`).
    cuerpo = await _llamar_endpoint(_usuario("asesor", "asesor1", negocio["id"]), resultado="sin_resultado")
    assert [c["telefono"] for c in cuerpo["conversaciones"]] == [tel["con_gestion"]]
    assert cuerpo["total"] == 1
    otro = await _llamar_endpoint(_usuario("asesor", "asesor2", negocio["id"]), resultado="sin_resultado")
    assert otro["total"] == 0
