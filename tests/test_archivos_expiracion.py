# tests/test_archivos_expiracion.py — Cron de expiración de adjuntos
# (2026-09-16, pedido explícito del usuario, retención acordada: 90 días).
#
# `listar_archivos_no_reutilizables_antes_de` es la única pieza con lógica
# real (el borrado físico vive en scripts/purgar_archivos_expirados.py, un
# simple os.remove por cada fila que devuelva esto — sin lógica propia que
# testear ahí, mismo criterio que scripts/liberar_leads_inactivos.py, cuyo
# test solo cubre la función de memory.py que lo alimenta).
#
# El caso que más importa: un catálogo REUTILIZABLE nunca debe aparecer acá
# aunque sea viejo — se referencia desde muchos leads a la vez, expirarlo
# rompería el historial de todos ellos, no solo uno.

from datetime import datetime, timedelta

from sqlalchemy import select

from agent import memory as mem


async def _archivo(nombre: str, reutilizable: bool, hace_dias: float, negocio_id: str | None = None):
    creado = await mem.crear_archivo_adjunto(
        nombre, f"/tmp/{nombre}", "application/pdf", 1024,
        subido_por="asesor_test", reutilizable=reutilizable, negocio_id=negocio_id,
    )
    async with mem.async_session() as session:
        fila = await session.get(mem.ArchivoAdjunto, creado["id"])
        fila.creado = datetime.utcnow() - timedelta(days=hace_dias)
        await session.commit()
    return creado["id"]


async def test_incluye_proforma_vieja_no_reutilizable():
    corte = datetime.utcnow() - timedelta(days=90)
    id_viejo = await _archivo("proforma_vieja.pdf", reutilizable=False, hace_dias=120)

    candidatos = await mem.listar_archivos_no_reutilizables_antes_de(corte)
    assert id_viejo in {a["id"] for a in candidatos}


async def test_excluye_proforma_reciente():
    corte = datetime.utcnow() - timedelta(days=90)
    id_reciente = await _archivo("proforma_reciente.pdf", reutilizable=False, hace_dias=5)

    candidatos = await mem.listar_archivos_no_reutilizables_antes_de(corte)
    assert id_reciente not in {a["id"] for a in candidatos}


async def test_nunca_incluye_catalogo_reutilizable_aunque_sea_viejo():
    """El caso que importa de verdad: un catálogo reutilizable de hace 200
    días NO debe expirarse — puede estar referenciado en el historial de
    varios leads distintos ahora mismo."""
    negocio = await mem.crear_negocio("Negocio Expiracion", "exp-cat-1")
    corte = datetime.utcnow() - timedelta(days=90)
    id_catalogo = await _archivo(
        "catalogo_reutilizable.pdf", reutilizable=True, hace_dias=200, negocio_id=negocio["id"],
    )

    candidatos = await mem.listar_archivos_no_reutilizables_antes_de(corte)
    assert id_catalogo not in {a["id"] for a in candidatos}


async def test_nota_de_voz_vieja_tambien_expira():
    """Las notas de voz usan el mismo mecanismo (reutilizable=False) que
    las proformas — deben expirar igual, sin tratamiento especial."""
    corte = datetime.utcnow() - timedelta(days=90)
    id_nota = await _archivo("nota_de_voz.ogg", reutilizable=False, hace_dias=100)

    candidatos = await mem.listar_archivos_no_reutilizables_antes_de(corte)
    assert id_nota in {a["id"] for a in candidatos}


async def test_no_modifica_ni_borra_ninguna_fila():
    """Esta función es de solo lectura — nunca toca el disco ni la base de
    datos (eso lo hace el script que llama esto, con os.remove real)."""
    id_viejo = await _archivo("proforma_solo_lectura.pdf", reutilizable=False, hace_dias=120)
    corte = datetime.utcnow() - timedelta(days=90)

    await mem.listar_archivos_no_reutilizables_antes_de(corte)

    async with mem.async_session() as session:
        result = await session.execute(select(mem.ArchivoAdjunto).where(mem.ArchivoAdjunto.id == id_viejo))
        fila = result.scalar_one()
        assert fila is not None
        assert fila.reutilizable is False
