# tests/test_gate_archivo_reutilizable_aislamiento.py — cierra el hallazgo
# de la Auditoría Maestra: archivos_adjuntos reutilizables no tenían NINGÚN
# aislamiento de negocio_id (listar/descargar/enviar/eliminar devolvían o
# aceptaban el catálogo de CUALQUIER negocio a CUALQUIER usuario
# autenticado, con solo conocer/adivinar un id secuencial). Datos
# sintéticos únicamente.

import pytest
from fastapi import HTTPException

from agent import memory as mem
from agent.dashboard import _verificar_acceso_archivo_reutilizable


async def _negocio(codigo: str):
    return await mem.crear_negocio(f"Negocio {codigo}", codigo)


# ── Tenant A: operaciones propias, deben funcionar ──────────────────────

async def test_tenant_a_crea_y_lista_su_propio_reutilizable():
    negocio_a = await _negocio("arch-iso-a1")
    archivo = await mem.crear_archivo_adjunto(
        "catalogo_a.pdf", "/tmp/catalogo_a.pdf", "application/pdf", 2048,
        subido_por="admin_a", reutilizable=True, negocio_id=negocio_a["id"],
    )
    listado = await mem.listar_archivos_reutilizables(negocio_a["id"])
    assert [a["id"] for a in listado] == [archivo["id"]]


async def test_tenant_a_puede_descargar_su_propio_reutilizable():
    negocio_a = await _negocio("arch-iso-a2")
    archivo = await mem.crear_archivo_adjunto(
        "catalogo_a.pdf", "/tmp/catalogo_a.pdf", "application/pdf", 2048,
        subido_por="admin_a", reutilizable=True, negocio_id=negocio_a["id"],
    )
    admin_a = {"username": "admin_a", "rol": "admin", "negocio_id": negocio_a["id"]}
    _verificar_acceso_archivo_reutilizable(archivo, admin_a)  # no debe lanzar


async def test_tenant_a_puede_enviar_su_propio_reutilizable():
    # El envío real (enviar_catalogo_chat) pasa por WhatsApp + disco; el
    # candado que decide si se envía o no es exactamente esta función —
    # mismo camino que protege la descarga.
    negocio_a = await _negocio("arch-iso-a3")
    archivo = await mem.crear_archivo_adjunto(
        "catalogo_a.pdf", "/tmp/catalogo_a.pdf", "application/pdf", 2048,
        subido_por="admin_a", reutilizable=True, negocio_id=negocio_a["id"],
    )
    asesor_a = {"username": "asesor_a", "rol": "asesor", "negocio_id": negocio_a["id"]}
    _verificar_acceso_archivo_reutilizable(archivo, asesor_a)  # no debe lanzar


async def test_tenant_a_puede_eliminar_su_propio_reutilizable():
    negocio_a = await _negocio("arch-iso-a4")
    archivo = await mem.crear_archivo_adjunto(
        "catalogo_a.pdf", "/tmp/catalogo_a.pdf", "application/pdf", 2048,
        subido_por="admin_a", reutilizable=True, negocio_id=negocio_a["id"],
    )
    eliminado = await mem.eliminar_archivo_reutilizable(archivo["id"], negocio_a["id"])
    assert eliminado is True
    archivo_actualizado = await mem.obtener_archivo_adjunto(archivo["id"])
    assert archivo_actualizado["reutilizable"] is False


# ── Tenant B: no puede tocar los reutilizables de A ─────────────────────

async def test_tenant_b_no_ve_el_reutilizable_de_a_en_el_listado():
    negocio_a = await _negocio("arch-iso-b1a")
    negocio_b = await _negocio("arch-iso-b1b")
    await mem.crear_archivo_adjunto(
        "catalogo_a.pdf", "/tmp/catalogo_a.pdf", "application/pdf", 2048,
        subido_por="admin_a", reutilizable=True, negocio_id=negocio_a["id"],
    )
    listado_b = await mem.listar_archivos_reutilizables(negocio_b["id"])
    assert listado_b == []


async def test_tenant_b_no_puede_descargar_el_reutilizable_de_a():
    negocio_a = await _negocio("arch-iso-b2a")
    negocio_b = await _negocio("arch-iso-b2b")
    archivo = await mem.crear_archivo_adjunto(
        "catalogo_a.pdf", "/tmp/catalogo_a.pdf", "application/pdf", 2048,
        subido_por="admin_a", reutilizable=True, negocio_id=negocio_a["id"],
    )
    admin_b = {"username": "admin_b", "rol": "admin", "negocio_id": negocio_b["id"]}
    with pytest.raises(HTTPException) as exc:
        _verificar_acceso_archivo_reutilizable(archivo, admin_b)
    assert exc.value.status_code == 403


async def test_tenant_b_no_puede_enviar_el_reutilizable_de_a():
    negocio_a = await _negocio("arch-iso-b3a")
    negocio_b = await _negocio("arch-iso-b3b")
    archivo = await mem.crear_archivo_adjunto(
        "catalogo_a.pdf", "/tmp/catalogo_a.pdf", "application/pdf", 2048,
        subido_por="admin_a", reutilizable=True, negocio_id=negocio_a["id"],
    )
    asesor_b = {"username": "asesor_b", "rol": "asesor", "negocio_id": negocio_b["id"]}
    with pytest.raises(HTTPException) as exc:
        _verificar_acceso_archivo_reutilizable(archivo, asesor_b)
    assert exc.value.status_code == 403


async def test_tenant_b_no_puede_eliminar_el_reutilizable_de_a():
    negocio_a = await _negocio("arch-iso-b4a")
    negocio_b = await _negocio("arch-iso-b4b")
    archivo = await mem.crear_archivo_adjunto(
        "catalogo_a.pdf", "/tmp/catalogo_a.pdf", "application/pdf", 2048,
        subido_por="admin_a", reutilizable=True, negocio_id=negocio_a["id"],
    )
    eliminado = await mem.eliminar_archivo_reutilizable(archivo["id"], negocio_b["id"])
    assert eliminado is False
    # Confirma que ademas no quedo desactivado por el intento fallido.
    archivo_actual = await mem.obtener_archivo_adjunto(archivo["id"])
    assert archivo_actual["reutilizable"] is True


# ── Manipulación de archivo_id (mismo id, sesión ajena) ─────────────────

async def test_manipular_archivo_id_de_a_desde_sesion_b_no_da_acceso():
    negocio_a = await _negocio("arch-iso-m1a")
    negocio_b = await _negocio("arch-iso-m1b")
    archivo = await mem.crear_archivo_adjunto(
        "catalogo_a.pdf", "/tmp/catalogo_a.pdf", "application/pdf", 2048,
        subido_por="admin_a", reutilizable=True, negocio_id=negocio_a["id"],
    )
    admin_b = {"username": "admin_b", "rol": "admin", "negocio_id": negocio_b["id"]}
    # El archivo_id de A es conocido/adivinado por B (ej. incrementando un
    # id secuencial) — igual se rechaza, el candado no depende de que el
    # id sea "difícil de encontrar".
    archivo_visto_por_b = await mem.obtener_archivo_adjunto(archivo["id"])
    with pytest.raises(HTTPException) as exc:
        _verificar_acceso_archivo_reutilizable(archivo_visto_por_b, admin_b)
    assert exc.value.status_code == 403


# ── negocio_id enviado por el cliente: debe ignorarse ───────────────────

async def test_negocio_id_real_sale_de_la_sesion_no_de_otro_campo():
    """El tenant real SIEMPRE sale de usuario['negocio_id'] (resuelto por
    la sesión autenticada vía _usuario_actual), nunca de un valor que el
    cliente controle en el body/query. El test de tenant_b de arriba ya
    prueba que un negocio_id de sesión distinto se rechaza pase lo que
    pase en cualquier otro campo del payload — acá se confirma el caso
    positivo simétrico: cuando negocio_id de sesión sí coincide, pasa."""
    negocio_a = await _negocio("arch-iso-f1a")
    archivo = await mem.crear_archivo_adjunto(
        "catalogo_a.pdf", "/tmp/catalogo_a.pdf", "application/pdf", 2048,
        subido_por="admin_a", reutilizable=True, negocio_id=negocio_a["id"],
    )
    admin_a = {"username": "admin_a", "rol": "admin", "negocio_id": negocio_a["id"]}
    _verificar_acceso_archivo_reutilizable(archivo, admin_a)  # no debe lanzar


async def test_negocio_id_ausente_en_sesion_nunca_pasa_por_coincidencia_none():
    """None == None nunca debe interpretarse como acceso válido — un
    usuario['negocio_id'] vacío/None debe rechazarse siempre, incluso si
    el archivo (por algún dato huérfano no resuelto) también tuviera
    negocio_id None."""
    sin_negocio = {"username": "raro", "rol": "admin", "negocio_id": None}
    archivo_sin_negocio = {"id": 999, "reutilizable": True, "negocio_id": None}
    with pytest.raises(HTTPException) as exc:
        _verificar_acceso_archivo_reutilizable(archivo_sin_negocio, sin_negocio)
    assert exc.value.status_code == 403


# ── subido_por no es el mecanismo de aislamiento ────────────────────────

async def test_subido_por_no_es_mecanismo_de_aislamiento():
    """Dos negocios distintos pueden compartir el mismo username en
    subido_por (Usuario.username solo es único por (negocio_id, username),
    Gate 5.4) — el aislamiento nunca debe depender de ese campo."""
    negocio_a = await _negocio("arch-iso-s1a")
    negocio_b = await _negocio("arch-iso-s1b")
    archivo_a = await mem.crear_archivo_adjunto(
        "catalogo.pdf", "/tmp/catalogo.pdf", "application/pdf", 2048,
        subido_por="admin", reutilizable=True, negocio_id=negocio_a["id"],
    )
    archivo_b = await mem.crear_archivo_adjunto(
        "catalogo.pdf", "/tmp/catalogo.pdf", "application/pdf", 2048,
        subido_por="admin", reutilizable=True, negocio_id=negocio_b["id"],
    )
    admin_de_b = {"username": "admin", "rol": "admin", "negocio_id": negocio_b["id"]}
    # Mismo subido_por en ambos archivos — si el aislamiento dependiera de
    # ese campo, admin_de_b ("admin") accedería al de A. No debe.
    with pytest.raises(HTTPException):
        _verificar_acceso_archivo_reutilizable(archivo_a, admin_de_b)
    _verificar_acceso_archivo_reutilizable(archivo_b, admin_de_b)  # el suyo sí


# ── Creación sin negocio_id: falla explícitamente, no crea huérfanos ────

async def test_crear_reutilizable_sin_negocio_id_falla():
    with pytest.raises(ValueError):
        await mem.crear_archivo_adjunto(
            "catalogo.pdf", "/tmp/catalogo.pdf", "application/pdf", 2048,
            subido_por="admin_a", reutilizable=True,
        )


# ── Proformas: el candado de negocio_id no las afecta ───────────────────

async def test_proforma_no_requiere_negocio_id():
    """Las proformas (reutilizable=False) siguen sin necesitar negocio_id
    directo — su aislamiento sigue siendo el indirecto vía Lead, sin
    cambio (ver test_gate55_archivo_cross_tenant.py)."""
    archivo = await mem.crear_archivo_adjunto(
        "proforma.pdf", "/tmp/proforma.pdf", "application/pdf", 1024,
        subido_por="admin_a", reutilizable=False,
    )
    assert archivo["negocio_id"] is None
