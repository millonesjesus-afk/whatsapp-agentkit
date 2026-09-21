# tests/test_campana_en_conversation.py — la Analítica cuenta campañas por
# Conversation.campana_origen_id; la detección solo guardaba Lead.campana_origen
# y toda campaña salía en 0 / 0 (2026-09-21).

import importlib.util
from pathlib import Path

from sqlalchemy import text

from agent import memory as mem

RAIZ = Path(__file__).resolve().parent.parent


async def _escenario(codigo: str, telefono: str):
    negocio = await mem.crear_negocio(f"Negocio {codigo}", codigo)
    canal = await mem.crear_canal_whatsapp(
        nombre=f"Canal {codigo}", phone_number_id=f"4060000{codigo[-2:]}", negocio_id=negocio["id"],
    )
    campana = await mem.crear_campana(
        "Meta Terma Julio", "referral_meta", "terma", negocio_id=negocio["id"],
    )
    await mem.actualizar_lead(telefono, negocio_id=negocio["id"], numero_whatsapp_id="x")
    await mem.resolver_conversation_activa(telefono, negocio["id"], canal["id"])
    return negocio, canal, campana


async def _totales(negocio_id: str) -> dict:
    filas = await mem.contar_opportunities_por_campana(negocio_id)
    return {f["campana"]: f["total"] for f in filas}


async def test_campana_detectada_se_cuenta_en_la_analitica():
    negocio, _, _ = await _escenario("g-cam-01", "51900900001")
    assert (await _totales(negocio["id"]))["Meta Terma Julio"] == 0

    await mem.asignar_campana_origen("51900900001", "Meta Terma Julio")

    assert (await _totales(negocio["id"]))["Meta Terma Julio"] == 1


async def test_no_pisa_una_campana_ya_asignada_a_la_conversation():
    negocio, _, _ = await _escenario("g-cam-02", "51900900002")
    await mem.crear_campana("Catálogo web", "texto_saludo", "catalogo", negocio_id=negocio["id"])
    await mem.asignar_campana_origen("51900900002", "Meta Terma Julio")

    await mem.asignar_campana_origen("51900900002", "Catálogo web")

    totales = await _totales(negocio["id"])
    assert totales["Meta Terma Julio"] == 1 and totales["Catálogo web"] == 0


async def test_migracion_rellena_campana_solo_donde_falta():
    negocio, canal, _ = await _escenario("g-cam-03", "51900900003")
    # Estado previo al arreglo: el lead tiene el nombre, la conversation no.
    await mem.actualizar_lead("51900900003", campana_origen="Meta Terma Julio")
    await mem.actualizar_lead("51900900004", negocio_id=negocio["id"], campana_origen="Meta Terma Julio")
    await mem.resolver_conversation_activa("51900900004", negocio["id"], canal["id"])
    assert (await _totales(negocio["id"]))["Meta Terma Julio"] == 0

    ruta = RAIZ / "migrations/versions/c9f1a3d7e526_rellenar_campana_de_conversations_desde_leads.py"
    spec = importlib.util.spec_from_file_location("mig_rellenar_campanas", ruta)
    migracion = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migracion)
    async with mem.async_session() as session:
        await session.execute(text(migracion.SQL_RELLENAR_CAMPANAS))
        await session.commit()

    assert (await _totales(negocio["id"]))["Meta Terma Julio"] == 2
