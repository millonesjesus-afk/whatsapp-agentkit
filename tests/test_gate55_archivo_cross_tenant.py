# tests/test_gate55_archivo_cross_tenant.py — corrección residual de Gate
# 5.4 (hallazgo Alta severidad, checkpoint de investigación de Gate 5.5):
# GET /dashboard/archivo/{archivo_id} servía el archivo sin candado cuando
# el lead dueño pertenecía a otro Negocio (obtener_lead devolvía None y el
# chequeo `if lead:` se saltaba en silencio). Datos sintéticos únicamente.

import pytest
from fastapi import HTTPException

from agent import memory as mem
from agent.dashboard import _verificar_acceso_archivo


async def _negocio(codigo: str):
    return await mem.crear_negocio(f"Negocio {codigo}", codigo)


async def test_archivo_de_otro_negocio_deniega_acceso_403():
    negocio_a = await _negocio("arch-a")
    negocio_b = await _negocio("arch-b")
    telefono_a = "51900500001"
    await mem.actualizar_lead(telefono_a, negocio_id=negocio_a["id"], nombre="Cliente A")

    archivo = await mem.crear_archivo_adjunto(
        "proforma.pdf", "/tmp/proforma.pdf", "application/pdf", 1024,
        subido_por="admin_a", reutilizable=False,
    )
    await mem.guardar_mensaje(telefono_a, "assistant", "Proforma adjunta", negocio_id=negocio_a["id"], archivo_id=archivo["id"])

    admin_b = {"username": "admin_b", "rol": "admin", "negocio_id": negocio_b["id"]}

    with pytest.raises(HTTPException) as exc:
        await _verificar_acceso_archivo(archivo["id"], admin_b)
    assert exc.value.status_code == 403


async def test_archivo_del_propio_negocio_respeta_el_criterio_de_rol():
    negocio_a = await _negocio("arch-c")
    telefono_a = "51900500002"
    await mem.actualizar_lead(telefono_a, negocio_id=negocio_a["id"], nombre="Cliente A")

    archivo = await mem.crear_archivo_adjunto(
        "proforma.pdf", "/tmp/proforma.pdf", "application/pdf", 1024,
        subido_por="admin_a", reutilizable=False,
    )
    await mem.guardar_mensaje(telefono_a, "assistant", "Proforma adjunta", negocio_id=negocio_a["id"], archivo_id=archivo["id"])

    admin_a = {"username": "admin_a", "rol": "admin", "negocio_id": negocio_a["id"]}
    await _verificar_acceso_archivo(archivo["id"], admin_a)  # no debe lanzar — mismo Negocio, rol admin


async def test_archivo_reutilizable_sin_lead_asociado_no_requiere_candado():
    negocio_a = await _negocio("arch-d")
    # negocio_id ahora es obligatorio para reutilizable=True (Gate de
    # aislamiento multi-tenant de ArchivoAdjunto) — se agrega acá solo para
    # respetar el nuevo esquema, sin cambiar lo que este test verifica:
    # `_verificar_acceso_archivo` (el candado de Lead) sigue sin aplicar a
    # reutilizables, aunque ahora exista un candado DISTINTO de negocio_id
    # (ver test_gate_archivo_reutilizable_aislamiento.py) para ese mismo caso.
    archivo = await mem.crear_archivo_adjunto(
        "catalogo.pdf", "/tmp/catalogo.pdf", "application/pdf", 2048,
        subido_por="admin_a", reutilizable=True, negocio_id=negocio_a["id"],
    )
    admin_otro = {"username": "admin_x", "rol": "admin", "negocio_id": negocio_a["id"]}
    # Sin mensaje que lo referencie, obtener_telefono_de_archivo devuelve
    # None — no hay lead que verificar, la función retorna sin lanzar.
    await _verificar_acceso_archivo(archivo["id"], admin_otro)
