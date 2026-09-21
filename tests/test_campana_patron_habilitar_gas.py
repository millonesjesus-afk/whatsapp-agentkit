# tests/test_campana_patron_habilitar_gas.py — el saludo real de la campaña SMS
# "Clientes próximos a habilitar gas" no coincidía con su patrón y esos leads
# quedaban sin campaña (2026-09-21). El arranque corrige el patrón viejo.

from agent import memory as mem
from agent.campanas import corregir_patrones_desalineados, detectar_y_asignar_campana

SALUDO_REAL = (
    "¡Hola! 👋\nPronto habilitarán mi servicio de gas natural 🔥 y quisiera conocer las "
    "promociones disponibles en cocinas, termas y secadoras 😊"
)
NOMBRE = "SMS Clientes próximos a habilitar gas"


async def test_el_saludo_real_se_reconoce_tras_corregir_el_patron_viejo():
    negocio = await mem.crear_negocio("Negocio g-hab-01", "g-hab-01")
    canal = await mem.crear_canal_whatsapp(nombre="Canal", phone_number_id="40700000001", negocio_id=negocio["id"])
    await mem.crear_campana(NOMBRE, "texto_saludo", "tu gas natural ya está por llegar", negocio_id=negocio["id"])
    telefono = "51901000001"
    await mem.actualizar_lead(telefono, negocio_id=negocio["id"], numero_whatsapp_id="x")
    await mem.resolver_conversation_activa(telefono, negocio["id"], canal["id"])

    assert await detectar_y_asignar_campana(telefono, SALUDO_REAL, None, negocio["id"]) is None

    await corregir_patrones_desalineados(negocio["id"])

    campana = await detectar_y_asignar_campana(telefono, SALUDO_REAL, None, negocio["id"])
    assert campana is not None and campana["nombre"] == NOMBRE
    filas = await mem.contar_opportunities_por_campana(negocio["id"])
    assert {f["campana"]: f["total"] for f in filas}[NOMBRE] == 1
