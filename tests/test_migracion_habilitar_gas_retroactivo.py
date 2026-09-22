# tests/test_migracion_habilitar_gas_retroactivo.py — el patrón corregido de
# "SMS Clientes próximos a habilitar gas" (2026-09-21) no reprocesa mensajes
# viejos; esta migración de datos asigna retroactivamente las conversaciones
# anteriores con ese saludo exacto que quedaron sin campaña.

import importlib.util
from pathlib import Path

from sqlalchemy import text

from agent import memory as mem

RAIZ = Path(__file__).resolve().parent.parent
_RUTA_MIGRACION = RAIZ / "migrations/versions/f10c9d0f9996_asignar_retroactivamente_saludo_habilitar_gas.py"


def _cargar_migracion():
    spec = importlib.util.spec_from_file_location("mig_habilitar_gas_retroactivo", _RUTA_MIGRACION)
    migracion = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migracion)
    return migracion


async def _correr_migracion():
    migracion = _cargar_migracion()
    async with mem.async_session() as session:
        await session.execute(text(migracion.SQL_ASIGNAR_CONVERSATIONS))
        await session.execute(text(migracion.SQL_ASIGNAR_LEADS))
        await session.commit()


async def _conversacion_sin_campana(negocio, canal, telefono: str, saludo: str):
    """Simula el estado previo al fix: llega un mensaje que hoy SÍ matchea el
    patrón corregido, pero la conversation quedó sin campana_origen_id —
    porque la detección no reprocesa historial, solo corre al llegar el
    mensaje (y acá se guarda el mensaje sin pasar por esa detección, tal
    como quedaron las conversaciones reales anteriores al fix)."""
    await mem.actualizar_lead(telefono, negocio_id=negocio["id"], numero_whatsapp_id="x")
    conversation, _ = await mem.resolver_conversation_activa(telefono, negocio["id"], canal["id"])
    await mem.guardar_mensaje(telefono, "user", saludo, negocio_id=negocio["id"])
    return conversation


async def _escenario(codigo: str):
    negocio = await mem.crear_negocio(f"Negocio {codigo}", codigo)
    canal = await mem.crear_canal_whatsapp(
        nombre=f"Canal {codigo}", phone_number_id=f"4092000{codigo[-2:]}", negocio_id=negocio["id"],
    )
    await mem.crear_campana(
        "SMS Clientes próximos a habilitar gas", "texto_saludo",
        "pronto habilitarán mi servicio de gas natural", negocio_id=negocio["id"],
    )
    return negocio, canal


async def test_asigna_la_conversation_cuyo_saludo_coincide_con_el_patron_corregido():
    negocio, canal = await _escenario("g-mig-01")
    saludo = "¡Hola! 👋\nPronto habilitarán mi servicio de gas natural 🔥 y quisiera conocer las promociones"
    conversation = await _conversacion_sin_campana(negocio, canal, "51904000001", saludo)
    assert conversation.campana_origen_id is None  # estado previo, confirmado

    await _correr_migracion()

    campanas = {f["campana"]: f for f in await mem.contar_opportunities_por_campana(negocio["id"])}
    assert campanas["SMS Clientes próximos a habilitar gas"]["total"] == 1
    lead = await mem.obtener_lead("51904000001", negocio["id"])
    assert lead["campana_origen"] == "SMS Clientes próximos a habilitar gas"


async def test_no_toca_conversaciones_sin_ese_saludo():
    negocio, canal = await _escenario("g-mig-02")
    await _conversacion_sin_campana(negocio, canal, "51904000002", "Hola, buenas tardes")

    await _correr_migracion()

    campanas = {f["campana"]: f for f in await mem.contar_opportunities_por_campana(negocio["id"])}
    assert campanas["SMS Clientes próximos a habilitar gas"]["total"] == 0
    lead = await mem.obtener_lead("51904000002", negocio["id"])
    assert lead["campana_origen"] is None


async def test_nunca_pisa_una_campana_ya_asignada():
    negocio, canal = await _escenario("g-mig-03")
    await mem.crear_campana("Meta Terma Julio", "referral_meta", "terma", negocio_id=negocio["id"])
    saludo = "Pronto habilitarán mi servicio de gas natural, gracias"
    await _conversacion_sin_campana(negocio, canal, "51904000003", saludo)
    await mem.asignar_campana_origen("51904000003", "Meta Terma Julio")

    await _correr_migracion()

    campanas = {f["campana"]: f for f in await mem.contar_opportunities_por_campana(negocio["id"])}
    assert campanas["Meta Terma Julio"]["total"] == 1
    assert campanas["SMS Clientes próximos a habilitar gas"]["total"] == 0
