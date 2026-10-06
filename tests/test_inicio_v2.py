# tests/test_inicio_v2.py — Inicio verdadero (paquete B, 2026-10-05):
# contrato ADITIVO de `GET /dashboard/inicio.json`.
#
#   - "Clientes esperando" (último mensaje real del cliente sin respuesta, con
#     un humano de por medio) en vez de `pausado_manual`.
#   - Ventana de 24 h de Meta (`ventana_vence_en` / `ventana_abierta`).
#   - `categoria` por ítem, `zona_accion.totales`, citas próximas/vencidas.
#   - Indicadores sin el duplicado de antes.
#   - `avisos` de uso de WhatsApp (solo rol admin; nunca rompe Inicio).
#
# Datos sintéticos únicamente.

import json
from datetime import datetime, timedelta

from sqlalchemy import update

from agent import dashboard, memory as mem


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _negocio_con_canal(codigo: str, telefono_canal: str):
    negocio = await mem.crear_negocio(f"Negocio {codigo}", codigo)
    canal = await mem.crear_canal_whatsapp(
        nombre=f"Canal {codigo}", phone_number_id=telefono_canal, negocio_id=negocio["id"],
    )
    return negocio, canal


async def _lead(
    negocio, canal, telefono: str, *, asesor: str | None = None, pausado: bool = False,
    escalado: bool = False, resultado: str | None = None, nombre: str | None = None,
    paso_flujo: str | None = None, fecha_agendada: datetime | None = None,
):
    """Lead + Contact + Conversation activa, con los campos de interés."""
    await mem.resolver_conversation_activa(telefono, negocio["id"], canal["id"])
    await mem.actualizar_lead(telefono, nombre=nombre or f"Cliente {telefono[-4:]}", negocio_id=negocio["id"])
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


async def _mensaje(negocio, telefono: str, role: str, contenido: str, hace: timedelta):
    """Guarda un mensaje y lo lleva a `ahora - hace` (para controlar el orden
    y la ventana de 24 h sin esperar)."""
    m = await mem.guardar_mensaje(telefono, role, contenido, negocio["id"])
    async with mem.async_session() as session:
        await session.execute(
            update(mem.Mensaje).where(mem.Mensaje.id == m["id"]).values(timestamp=datetime.utcnow() - hace)
        )
        await session.commit()


def _h(horas: float) -> timedelta:
    return timedelta(hours=horas)


async def _esperando(negocio, **kw):
    return await mem.listar_clientes_esperando(negocio["id"], **kw)


async def _usuario(negocio, username: str, rol: str):
    await mem.crear_usuario(username, "pw12345", username.title(), rol, negocio["id"])
    return await mem.obtener_usuario(username, negocio_id=negocio["id"])


async def _inicio(usuario: dict) -> dict:
    return json.loads((await dashboard.inicio_json(usuario=usuario)).body)


async def _estado_lead(telefono: str):
    async with mem.async_session() as session:
        lead = await session.get(mem.Lead, telefono)
        return (lead.resultado, lead.asesor_asignado, lead.paso_flujo, lead.pausado_manual, lead.fecha_agendada)


# ---------------------------------------------------------------------------
# es_probable_cierre
# ---------------------------------------------------------------------------

def test_probable_cierre_reconoce_agradecimientos_y_cierres_cortos():
    for texto in ("gracias", "Muchas gracias", "ok", "Okay!", "listo", "Vale", "Perfecto 👍", "dale",
                  "entendido", "Genial", "Excelente", "👍", "🙏", "ok gracias", "Muchas gracias!!"):
        assert mem.es_probable_cierre(texto), texto


def test_probable_cierre_no_marca_preguntas_ni_mensajes_con_contenido_ni_largos():
    for texto in ("gracias, ¿y la proforma?", "ok gracias?", "ok, envíame el precio", "no gracias",
                  "listo, te espero mañana", "", None, "hola", "gracias " * 6):
        assert not mem.es_probable_cierre(texto), texto


# ---------------------------------------------------------------------------
# listar_clientes_esperando — criterio
# ---------------------------------------------------------------------------

async def test_ultimo_mensaje_del_cliente_sin_respuesta_aparece():
    negocio, canal = await _negocio_con_canal("iv2-a", "40100000001")
    await _lead(negocio, canal, "51910000001", asesor="asesor1", nombre="Ana", resultado="interesado")
    await _mensaje(negocio, "51910000001", "assistant", "Hola, soy Gabi", _h(5))
    await _mensaje(negocio, "51910000001", "user", "Quiero una cocina", _h(2))

    lista = await _esperando(negocio)
    assert len(lista) == 1
    c = lista[0]
    assert c["telefono"] == "51910000001" and c["nombre"] == "Ana"
    assert c["asesor_asignado"] == "asesor1" and c["resultado"] == "interesado"
    assert c["escalado"] is False and c["probable_cierre"] is False
    assert c["conversation_id"]
    # El último mensaje fue hace ~2 h: la ventana vence ~22 h después.
    assert abs((c["ultimo_mensaje_cliente_en"] - (datetime.utcnow() - _h(2))).total_seconds()) < 30
    assert c["ventana_vence_en"] == c["ultimo_mensaje_cliente_en"] + _h(24)
    assert c["ventana_abierta"] is True


async def test_si_el_asesor_respondio_despues_no_aparece():
    negocio, canal = await _negocio_con_canal("iv2-b", "40100000002")
    await _lead(negocio, canal, "51910000002", asesor="asesor1")
    await _mensaje(negocio, "51910000002", "user", "Quiero una cocina", _h(3))
    await _mensaje(negocio, "51910000002", "asesor", "Te la cotizo ahora", _h(2))
    assert await _esperando(negocio) == []


async def test_una_reaccion_del_cliente_posterior_no_cuenta_como_mensaje():
    negocio, canal = await _negocio_con_canal("iv2-c", "40100000003")
    await _lead(negocio, canal, "51910000003", asesor="asesor1")
    await _mensaje(negocio, "51910000003", "user", "Quiero una cocina", _h(4))
    await _mensaje(negocio, "51910000003", "asesor", "Te la cotizo ahora", _h(3))
    await _mensaje(negocio, "51910000003", "user", "Reaccionó con 👍", _h(1))
    # El último mensaje REAL es el del asesor: el 👍 del cliente no lo "reabre".
    assert await _esperando(negocio) == []


async def test_una_reaccion_posterior_tampoco_cuenta_como_respuesta():
    negocio, canal = await _negocio_con_canal("iv2-d", "40100000004")
    await _lead(negocio, canal, "51910000004", asesor="asesor1")
    await _mensaje(negocio, "51910000004", "user", "Necesito ayuda con mi pedido", _h(3))
    await _mensaje(negocio, "51910000004", "assistant", "Reaccionó con 👍", _h(1))
    lista = await _esperando(negocio)
    assert [c["telefono"] for c in lista] == ["51910000004"]
    assert abs((lista[0]["ultimo_mensaje_cliente_en"] - (datetime.utcnow() - _h(3))).total_seconds()) < 30


async def test_vendido_y_agendado_siempre_aparecen_y_no_se_modifican():
    """Regla crítica: un cliente ya vendido o agendado que escribe SÍ espera."""
    negocio, canal = await _negocio_con_canal("iv2-e", "40100000005")
    cita = datetime.utcnow() - timedelta(hours=5) + timedelta(days=2)
    await _lead(negocio, canal, "51910000005", asesor="asesor1", resultado="vendido")
    await _lead(negocio, canal, "51910000006", asesor="asesor1", resultado="agendado", fecha_agendada=cita)
    await _mensaje(negocio, "51910000005", "user", "Se me dañó la hornilla", _h(2))
    await _mensaje(negocio, "51910000006", "user", "¿A qué hora era mi cita?", _h(1))
    antes = [await _estado_lead("51910000005"), await _estado_lead("51910000006")]

    lista = await _esperando(negocio)
    assert {c["telefono"]: c["resultado"] for c in lista} == {"51910000005": "vendido", "51910000006": "agendado"}

    cuerpo = await _inicio(await _usuario(negocio, "admin1", "admin"))
    telefonos = [i["telefono"] for i in cuerpo["zona_accion"]["items"] if i["categoria"] == "cliente_esperando"]
    assert set(telefonos) == {"51910000005", "51910000006"}
    # Nada de esto toca el estado de los leads.
    assert [await _estado_lead("51910000005"), await _estado_lead("51910000006")] == antes

    # Matiz (2026-10-06, por timestamp): si el caso se cerró definitivamente DESPUÉS del
    # último mensaje del cliente, ya no espera; si el cliente escribe después del cierre, sí.
    async with mem.async_session() as session:
        await session.execute(
            update(mem.Lead).where(mem.Lead.telefono == "51910000005")
            .values(cerrado_definitivamente_en=datetime.utcnow() - _h(1))
        )
        await session.commit()
    assert {c["telefono"] for c in await _esperando(negocio)} == {"51910000006"}
    await _mensaje(negocio, "51910000005", "user", "Sigue fallando", _h(0.5))
    assert {c["telefono"] for c in await _esperando(negocio)} == {"51910000005", "51910000006"}


async def test_lo_que_atiende_gabi_sin_asesor_no_aparece_pero_pausado_o_escalado_si():
    negocio, canal = await _negocio_con_canal("iv2-f", "40100000006")
    await _lead(negocio, canal, "51910000007")                                  # solo Gabi
    await _lead(negocio, canal, "51910000008", pausado=True)                    # coexistencia (sin asesor)
    await _lead(negocio, canal, "51910000009", escalado=True, paso_flujo="derivado_asesor")
    for tel in ("51910000007", "51910000008", "51910000009"):
        await _mensaje(negocio, tel, "user", "Buenas, necesito información", _h(1))

    lista = await _esperando(negocio)
    assert {c["telefono"] for c in lista} == {"51910000008", "51910000009"}
    assert {c["telefono"]: c["escalado"] for c in lista} == {"51910000008": False, "51910000009": True}


async def test_conversacion_cerrada_no_aparece():
    negocio, canal = await _negocio_con_canal("iv2-g", "40100000007")
    await _lead(negocio, canal, "51910000010", asesor="asesor1")
    await _mensaje(negocio, "51910000010", "user", "Hola", _h(1))
    async with mem.async_session() as session:
        await session.execute(update(mem.Conversation).values(estado="cerrada"))
        await session.commit()
    assert await _esperando(negocio) == []


async def test_probable_cierre_etiqueta_pero_no_oculta_ni_cambia_el_lead():
    negocio, canal = await _negocio_con_canal("iv2-h", "40100000008")
    await _lead(negocio, canal, "51910000011", asesor="asesor1", resultado="vendido")
    await _mensaje(negocio, "51910000011", "user", "Muchas gracias", _h(1))
    antes = await _estado_lead("51910000011")

    lista = await _esperando(negocio)
    assert len(lista) == 1 and lista[0]["probable_cierre"] is True
    assert await _estado_lead("51910000011") == antes  # nunca cierra ni cambia nada


async def test_multi_tenant_no_mezcla_negocios():
    negocio_a, canal_a = await _negocio_con_canal("iv2-i", "40100000009")
    negocio_b, canal_b = await _negocio_con_canal("iv2-j", "40100000010")
    await _lead(negocio_a, canal_a, "51910000012", asesor="asesor1")
    await _mensaje(negocio_a, "51910000012", "user", "Hola", _h(1))
    assert await _esperando(negocio_b) == []
    assert len(await _esperando(negocio_a)) == 1


# ---------------------------------------------------------------------------
# Ventana de Meta y orden
# ---------------------------------------------------------------------------

async def test_la_ventana_se_cierra_a_las_24_horas():
    negocio, canal = await _negocio_con_canal("iv2-k", "40100000011")
    await _lead(negocio, canal, "51910000013", asesor="asesor1")
    await _lead(negocio, canal, "51910000014", asesor="asesor1")
    await _mensaje(negocio, "51910000013", "user", "Hola", _h(23))
    await _mensaje(negocio, "51910000014", "user", "Hola", _h(25))

    por_tel = {c["telefono"]: c for c in await _esperando(negocio)}
    assert por_tel["51910000013"]["ventana_abierta"] is True
    assert por_tel["51910000014"]["ventana_abierta"] is False


async def test_orden_abiertas_por_menor_tiempo_restante_luego_cerradas_recientes_primero_y_cierres_al_final():
    negocio, canal = await _negocio_con_canal("iv2-l", "40100000012")
    casos = {  # telefono -> (texto, hace cuánto escribió)
        "51910000020": ("Quiero precio", _h(2)),    # A: abierta, vence en 22 h
        "51910000021": ("Quiero precio", _h(20)),   # B: abierta, vence en 4 h (la más urgente)
        "51910000022": ("Quiero precio", _h(30)),   # C: cerrada, más reciente
        "51910000023": ("Quiero precio", _h(40)),   # D: cerrada, más vieja
        "51910000024": ("ok gracias", _h(1)),       # E: abierta pero probable cierre -> al final de las abiertas
        "51910000025": ("gracias", _h(26)),         # F: cerrada y probable cierre -> al final de todo
    }
    for tel, (texto, hace) in casos.items():
        await _lead(negocio, canal, tel, asesor="asesor1")
        await _mensaje(negocio, tel, "user", texto, hace)

    orden = [c["telefono"] for c in await _esperando(negocio)]
    assert orden == ["51910000021", "51910000020", "51910000024", "51910000022", "51910000023", "51910000025"]
    assert [c["telefono"] for c in await _esperando(negocio, limite=2)] == orden[:2]


async def test_asesor_ve_solo_los_suyos_en_la_consulta():
    negocio, canal = await _negocio_con_canal("iv2-m", "40100000013")
    await _lead(negocio, canal, "51910000030", asesor="asesor1")
    await _lead(negocio, canal, "51910000031", asesor="asesor2")
    for tel in ("51910000030", "51910000031"):
        await _mensaje(negocio, tel, "user", "Hola", _h(1))
    assert [c["telefono"] for c in await _esperando(negocio, asesor="asesor1")] == ["51910000030"]
    assert len(await _esperando(negocio)) == 2


# ---------------------------------------------------------------------------
# inicio.json — zona de acción, totales, categorías
# ---------------------------------------------------------------------------

async def test_inicio_asesor_ve_solo_lo_suyo_con_categoria_y_datos_de_ventana():
    negocio, canal = await _negocio_con_canal("iv2-n", "40100000014")
    asesor = await _usuario(negocio, "asesor1", "asesor")
    await _lead(negocio, canal, "51910000040", asesor="asesor1", nombre="Mío", resultado="vendido")
    await _lead(negocio, canal, "51910000041", asesor="otro_asesor", nombre="Ajeno")
    await _mensaje(negocio, "51910000040", "user", "Hola, una consulta", _h(2))
    await _mensaje(negocio, "51910000041", "user", "Hola", _h(2))

    cuerpo = await _inicio(asesor)
    assert cuerpo["vision_total"] is False
    items = cuerpo["zona_accion"]["items"]
    assert [i["telefono"] for i in items] == ["51910000040"]
    i = items[0]
    assert i["categoria"] == "cliente_esperando" and i["motivo"] == "Esperando tu respuesta"
    assert i["nombre"] == "Mío" and i["conversation_id"]
    assert i["resultado"] == "vendido" and i["probable_cierre"] is False and i["ventana_abierta"] is True
    assert i["ultimo_mensaje_cliente_en"].endswith("Z") and i["ventana_vence_en"].endswith("Z")
    assert "asesor" not in i  # el campo `asesor` es solo de la vista admin
    assert cuerpo["zona_accion"]["vacio"] is False and cuerpo["avisos"] == []
    t = cuerpo["zona_accion"]["totales"]
    assert (t["cliente_esperando"], t["ventana_abierta"], t["escalados"], t["sin_asesor"]) == (1, 1, 0, 0)


async def test_inicio_admin_ve_todo_con_asesor_y_sin_duplicar_escalados():
    negocio, canal = await _negocio_con_canal("iv2-o", "40100000015")
    admin = await _usuario(negocio, "admin1", "admin")
    await _lead(negocio, canal, "51910000050", asesor="asesor_x")
    await _lead(negocio, canal, "51910000051", paso_flujo="derivado_asesor")                  # sin asesor
    await _lead(negocio, canal, "51910000052", paso_flujo="derivado_asesor", escalado=True)    # escalado
    await _mensaje(negocio, "51910000050", "user", "Hola", _h(2))
    await _mensaje(negocio, "51910000052", "user", "¿Me atienden?", _h(1))

    cuerpo = await _inicio(admin)
    assert cuerpo["vision_total"] is True
    por_cat = {}
    for i in cuerpo["zona_accion"]["items"]:
        por_cat.setdefault(i["categoria"], []).append(i)
    assert [i["telefono"] for i in por_cat["escalado"]] == ["51910000052"]
    assert por_cat["escalado"][0]["motivo"] == "Escalado a supervisión — ningún asesor respondió"
    assert [i["telefono"] for i in por_cat["sin_asesor"]] == ["51910000051"]
    assert por_cat["sin_asesor"][0]["motivo"] == "Sin asesor asignado"
    esp = por_cat["cliente_esperando"]
    assert [i["telefono"] for i in esp] == ["51910000050"]  # el escalado no se repite como "esperando"
    assert esp[0]["motivo"] == "Esperando respuesta — asesor_x" and esp[0]["asesor"] == "asesor_x"
    # Orden de categorías: escalados, sin asesor, esperando.
    assert [i["categoria"] for i in cuerpo["zona_accion"]["items"]] == ["escalado", "sin_asesor", "cliente_esperando"]
    t = cuerpo["zona_accion"]["totales"]
    assert (t["escalados"], t["sin_asesor"], t["cliente_esperando"]) == (1, 1, 2)  # totales reales
    # Casos DISTINTOS de "Responde ahora": el escalado también es cliente esperando y no se cuenta dos veces
    # (la suma de los tres totales daría 4).
    assert t["ahora_total"] == 3


async def test_totales_son_reales_aunque_los_items_tengan_tope():
    negocio, canal = await _negocio_con_canal("iv2-p", "40100000016")
    asesor = await _usuario(negocio, "asesor1", "asesor")
    for n in range(10):
        tel = f"519100001{n:02d}"
        await _lead(negocio, canal, tel, asesor="asesor1")
        await _mensaje(negocio, tel, "user", "Hola", _h(1 + n * 0.1))
    ahora_lima = datetime.utcnow() - timedelta(hours=5)
    for n in range(5):
        await _lead(negocio, canal, f"519100002{n:02d}", asesor="asesor1", resultado="agendado",
                    fecha_agendada=ahora_lima + timedelta(days=1 + n))
    for n in range(4):
        await _lead(negocio, canal, f"519100003{n:02d}", asesor="asesor1", resultado="agendado",
                    fecha_agendada=ahora_lima - timedelta(days=1 + n))

    z = (await _inicio(asesor))["zona_accion"]
    cuenta = {}
    for i in z["items"]:
        cuenta[i["categoria"]] = cuenta.get(i["categoria"], 0) + 1
    assert cuenta == {"cliente_esperando": 8, "cita": 3, "cita_vencida": 3}
    t = z["totales"]
    assert (t["cliente_esperando"], t["ventana_abierta"], t["citas_proximas"], t["citas_vencidas"]) == (10, 10, 5, 4)


async def test_ventana_por_vencer_cuenta_las_abiertas_con_menos_de_4_horas():
    negocio, canal = await _negocio_con_canal("iv2-q", "40100000017")
    asesor = await _usuario(negocio, "asesor1", "asesor")
    for tel, hace in (("51910000060", _h(21)), ("51910000061", _h(10)), ("51910000062", _h(30))):
        await _lead(negocio, canal, tel, asesor="asesor1")
        await _mensaje(negocio, tel, "user", "Hola", hace)
    t = (await _inicio(asesor))["zona_accion"]["totales"]
    assert (t["cliente_esperando"], t["ventana_abierta"], t["ventana_por_vencer"]) == (3, 2, 1)


async def test_citas_muestra_las_proximas_no_las_viejas_y_las_vencidas_aparte():
    negocio, canal = await _negocio_con_canal("iv2-r", "40100000018")
    asesor = await _usuario(negocio, "asesor1", "asesor")
    ahora_lima = datetime.utcnow() - timedelta(hours=5)  # fecha_agendada es hora local de Lima, sin zona
    await _lead(negocio, canal, "51910000070", asesor="asesor1", nombre="Vieja1", resultado="agendado",
                fecha_agendada=ahora_lima - timedelta(days=10))
    await _lead(negocio, canal, "51910000071", asesor="asesor1", nombre="Vieja2", resultado="agendado",
                fecha_agendada=ahora_lima - timedelta(days=2))
    # "Hoy más tarde" en hora de Lima: ya pasó respecto a UTC-naive pero NO respecto a Lima.
    futuras = {"51910000072": 1, "51910000073": 3, "51910000074": 5, "51910000075": 20}
    for tel, horas in futuras.items():
        await _lead(negocio, canal, tel, asesor="asesor1", resultado="agendado",
                    fecha_agendada=ahora_lima + timedelta(hours=horas))
    await _lead(negocio, canal, "51910000076", asesor="otro", resultado="agendado",
                fecha_agendada=ahora_lima + timedelta(hours=2))  # de otro asesor

    z = (await _inicio(asesor))["zona_accion"]
    proximas = [i for i in z["items"] if i["categoria"] == "cita"]
    vencidas = [i for i in z["items"] if i["categoria"] == "cita_vencida"]
    assert [i["telefono"] for i in proximas] == ["51910000072", "51910000073", "51910000074"]  # ascendente, top 3
    assert all(i["motivo"].startswith("Cita agendada — ") for i in proximas)
    # 2026-10-06: la de hace 10 días ya no se lista (solo vencidas de los últimos 7 días);
    # se cuenta aparte en `citas_vencidas_antiguas`.
    assert [i["telefono"] for i in vencidas] == ["51910000071"]
    expected = (ahora_lima - timedelta(days=2)).strftime("%d/%m %H:%M")
    assert vencidas[0]["motivo"] == f"Cita vencida sin cerrar — {expected}"
    assert (z["totales"]["citas_proximas"], z["totales"]["citas_vencidas"]) == (4, 1)
    assert z["totales"]["citas_vencidas_antiguas"] == 1


async def test_admin_ve_las_citas_de_todos():
    negocio, canal = await _negocio_con_canal("iv2-s", "40100000019")
    admin = await _usuario(negocio, "admin1", "admin")
    ahora_lima = datetime.utcnow() - timedelta(hours=5)
    await _lead(negocio, canal, "51910000080", asesor="a1", resultado="agendado", fecha_agendada=ahora_lima + timedelta(hours=3))
    await _lead(negocio, canal, "51910000081", asesor="a2", resultado="agendado", fecha_agendada=ahora_lima + timedelta(hours=4))
    z = (await _inicio(admin))["zona_accion"]
    assert [i["telefono"] for i in z["items"] if i["categoria"] == "cita"] == ["51910000080", "51910000081"]


async def test_zona_vacia_conserva_mensajes_en_tuteo_y_trae_totales():
    negocio, _ = await _negocio_con_canal("iv2-t", "40100000020")
    asesor = await _usuario(negocio, "asesor1", "asesor")
    admin = await _usuario(negocio, "admin1", "admin")
    za = (await _inicio(asesor))["zona_accion"]
    assert za["vacio"] is True and za["items"] == []
    assert za["mensaje_vacio"] == "No tienes conversaciones que requieran tu atención ahora mismo."
    assert za["totales"]["cliente_esperando"] == 0
    zd = (await _inicio(admin))["zona_accion"]
    assert zd["mensaje_vacio"] == "El equipo no tiene conversaciones que requieran tu intervención ahora mismo."
    assert set(zd["totales"]) >= {
        "cliente_esperando", "ventana_abierta", "ventana_por_vencer", "escalados", "sin_asesor",
        "citas_proximas", "citas_vencidas",
    }


async def test_el_html_legacy_tambien_usa_tuteo():
    negocio, _ = await _negocio_con_canal("iv2-u", "40100000021")
    usuario = {"username": "asesor1", "negocio_id": negocio["id"]}
    html_legacy = await dashboard._zona_accion_asesor(usuario, {"leads_todos": []})
    assert "No tienes conversaciones" in html_legacy and "tenés" not in html_legacy


# ---------------------------------------------------------------------------
# Indicadores
# ---------------------------------------------------------------------------

async def test_indicadores_asesor_sin_duplicado():
    negocio, canal = await _negocio_con_canal("iv2-v", "40100000022")
    asesor = await _usuario(negocio, "asesor1", "asesor")
    ahora_lima = datetime.utcnow() - timedelta(hours=5)
    await _lead(negocio, canal, "51910000090", asesor="asesor1")                            # activo
    await _lead(negocio, canal, "51910000091", asesor="asesor1", resultado="vendido")        # cerrado: no cuenta
    await _lead(negocio, canal, "51910000092", asesor="asesor1", resultado="agendado",
                fecha_agendada=ahora_lima + timedelta(days=3))                               # activo + cita en 7 d
    await _lead(negocio, canal, "51910000093", asesor="asesor1", resultado="agendado",
                fecha_agendada=ahora_lima + timedelta(days=15))                              # activo, fuera de 7 d
    await _lead(negocio, canal, "51910000094", asesor="otro")                                # ajeno
    await _mensaje(negocio, "51910000090", "user", "Hola", _h(1))

    ind = (await _inicio(asesor))["zona_indicadores"]
    assert ind == [
        {"valor": 3, "etiqueta": "Mis casos activos"},
        {"valor": 1, "etiqueta": "Esperando respuesta"},
        {"valor": 1, "etiqueta": "Citas próximas (7 días)"},
    ]
    etiquetas = [i["etiqueta"] for i in ind]
    assert "Conversaciones activas" not in etiquetas and "Leads asignados" not in etiquetas


async def test_indicadores_admin_sin_duplicado():
    negocio, canal = await _negocio_con_canal("iv2-w", "40100000023")
    admin = await _usuario(negocio, "admin1", "admin")
    await _usuario(negocio, "asesor1", "asesor")
    await _lead(negocio, canal, "51910000095", asesor="asesor1")
    await _lead(negocio, canal, "51910000096")                                   # con Gabi, activo
    await _lead(negocio, canal, "51910000097", asesor="asesor1", resultado="vendido")
    await _mensaje(negocio, "51910000095", "user", "Hola", _h(1))

    ind = (await _inicio(admin))["zona_indicadores"]
    assert [i["etiqueta"] for i in ind] == ["Casos activos", "Esperando respuesta", "Asesores disponibles"]
    assert ind[0]["valor"] == 2 and ind[1]["valor"] == 1
    assert isinstance(ind[2]["valor"], str) and "/" in ind[2]["valor"]


# ---------------------------------------------------------------------------
# Avisos (solo admin)
# ---------------------------------------------------------------------------

GRATIS = {"billable": False, "pricing_model": "PMP", "type": "free_customer_service", "category": "service"}
COBRABLE = {"billable": True, "pricing_model": "PMP", "type": "regular", "category": "service"}


async def _uso(negocio_id: str, prefijo: str, n: int, pricing: dict, phone: str = "100200300"):
    for i in range(n):
        assert await mem.registrar_estado_mensaje_meta({
            "wamid": f"wamid.{prefijo}.{i}", "estado": "delivered", "momento": datetime.utcnow(),
            "phone_number_id": phone, "destinatario": "51999000111", "pricing": pricing, "negocio_id": negocio_id,
        })


async def test_avisos_solo_para_admin_y_con_la_cuota_agotada():
    negocio, _ = await _negocio_con_canal("iv2-x", "40100000024")
    await mem.guardar_configuracion("meta_cuota_gratis_servicio", "5", negocio_id=negocio["id"])
    await _uso(negocio["id"], "cuota", 5, GRATIS)
    admin = await _usuario(negocio, "admin1", "admin")
    supervisor = await _usuario(negocio, "super1", "supervisor")
    asesor = await _usuario(negocio, "asesor1", "asesor")

    avisos = (await _inicio(admin))["avisos"]
    assert len(avisos) == 1
    a = avisos[0]
    assert a["nivel"] == "error" and a["titulo"] == "Se acabaron los mensajes gratis de WhatsApp este mes"
    assert a["enlace"] == "/configuracion/uso" and a["id"] and "5 de 5" in a["detalle"]
    assert set(a) == {"id", "nivel", "titulo", "detalle", "enlace"}
    assert (await _inicio(supervisor))["avisos"] == []
    assert (await _inicio(asesor))["avisos"] == []


async def test_avisos_80_por_ciento_de_la_cuota_es_warning():
    negocio, _ = await _negocio_con_canal("iv2-y", "40100000025")
    await mem.guardar_configuracion("meta_cuota_gratis_servicio", "10", negocio_id=negocio["id"])
    await _uso(negocio["id"], "c80", 8, GRATIS)
    admin = await _usuario(negocio, "admin1", "admin")
    avisos = (await _inicio(admin))["avisos"]
    assert [(a["nivel"], a["titulo"]) for a in avisos] == [("warning", "Usaste el 80 % de tus mensajes gratis de WhatsApp")]


async def test_avisos_95_por_ciento_de_la_cuota_es_warning():
    negocio, _ = await _negocio_con_canal("iv2-y2", "40100000026")
    await mem.guardar_configuracion("meta_cuota_gratis_servicio", "20", negocio_id=negocio["id"])
    await _uso(negocio["id"], "c95", 19, GRATIS)
    admin = await _usuario(negocio, "admin1", "admin")
    avisos = (await _inicio(admin))["avisos"]
    assert len(avisos) == 1 and avisos[0]["nivel"] == "warning" and "muy pocos" in avisos[0]["titulo"]


async def test_avisos_de_tope_tarifas_faltantes_y_tope_en_cero():
    negocio, _ = await _negocio_con_canal("iv2-z", "40100000027")
    await mem.guardar_configuracion("meta_cuota_gratis_servicio", "5", negocio_id=negocio["id"])
    await _uso(negocio["id"], "tf", 2, COBRABLE)   # cobrables sin tarifa configurada
    admin = await _usuario(negocio, "admin1", "admin")

    titulos = [a["titulo"] for a in (await _inicio(admin))["avisos"]]
    assert "Faltan tarifas: el costo y el tope no se pueden calcular" in titulos

    # Con tarifa y tope en 0 (sin autorecarga): gasto > 0 supera el tope.
    await mem.guardar_configuracion("meta_tarifa_usd_service", "0.03", negocio_id=negocio["id"])
    avisos = (await _inicio(admin))["avisos"]
    titulos = [a["titulo"] for a in avisos]
    assert "Faltan tarifas: el costo y el tope no se pueden calcular" not in titulos
    assert "Llegaste al tope de gasto mensual" in titulos
    assert "Tienes el tope en USD 0: los envíos no esenciales que se cobren se frenarán" in titulos
    assert avisos[0]["nivel"] == "error"  # los errores van primero
    assert all(a["enlace"] == "/configuracion/uso" for a in avisos)


async def test_avisos_tope_al_80_por_ciento():
    negocio, _ = await _negocio_con_canal("iv2-z2", "40100000028")
    await mem.guardar_configuracion("meta_cuota_gratis_servicio", "5", negocio_id=negocio["id"])
    await mem.guardar_configuracion("meta_tarifa_usd_service", "0.10", negocio_id=negocio["id"])
    await mem.guardar_configuracion("envios_tope_mensual_usd", "1", negocio_id=negocio["id"])
    await _uso(negocio["id"], "t80", 8, COBRABLE)   # 8 x 0.10 = USD 0.80 de 1 = 80 %
    admin = await _usuario(negocio, "admin1", "admin")
    titulos = {a["titulo"]: a["nivel"] for a in (await _inicio(admin))["avisos"]}
    assert titulos["Estás cerca del tope de gasto mensual (80 %)"] == "warning"
    assert "Llegaste al tope de gasto mensual" not in titulos


async def test_sin_alertas_no_hay_avisos():
    negocio, _ = await _negocio_con_canal("iv2-z3", "40100000029")
    admin = await _usuario(negocio, "admin1", "admin")
    assert (await _inicio(admin))["avisos"] == []


async def test_si_los_avisos_fallan_inicio_sigue_funcionando(monkeypatch):
    negocio, canal = await _negocio_con_canal("iv2-z4", "40100000030")
    admin = await _usuario(negocio, "admin1", "admin")
    await _lead(negocio, canal, "51910000099", asesor="asesor1")
    await _mensaje(negocio, "51910000099", "user", "Hola", _h(1))

    async def _falla(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(dashboard, "resumen_uso_mensual", _falla)
    cuerpo = await _inicio(admin)
    assert cuerpo["avisos"] == []
    assert [i["telefono"] for i in cuerpo["zona_accion"]["items"]] == ["51910000099"]
    assert len(cuerpo["zona_indicadores"]) == 3
