# tests/test_asignacion_automatica.py — elegir_asesor_automatico (Gabi)
# nunca debe elegir un asesor desactivado.
#
# Hallazgo del usuario (2026-09-17): "gabi asigna a un asesor a pesar que
# este inactivo, solo debe asignar a los activos". `elegir_asesor_automatico`
# ya filtraba por `disponible`, pero `listar_asesores()` (de quien depende)
# nunca excluía `activo=False` — y `toggle_usuario_activo` (Equipo) jamás
# toca `disponible`, así que una cuenta desactivada con `disponible=True`
# seguía siendo candidata para siempre (sin forma de corregirlo ella misma,
# porque `activo=False` le bloquea el login). Fix: agent/memory.py::
# listar_asesores ahora también exige `activo.is_(True)`.

from agent import asignacion, memory as mem


async def test_no_elige_asesor_desactivado_aunque_siga_disponible():
    negocio = await mem.crear_negocio("Negocio Asignacion", "asig-1")
    await mem.crear_usuario("ase_activo_asig1", "pw12345", "Asesor Activo", "asesor", negocio["id"])
    await mem.crear_usuario("ase_inactivo_asig1", "pw12345", "Asesor Inactivo", "asesor", negocio["id"])
    # Se desactiva la cuenta (Equipo) SIN tocar `disponible` — reproduce
    # exactamente el estado real: `toggle_usuario_activo` nunca lo hace.
    nuevo_estado = await mem.toggle_usuario_activo("ase_inactivo_asig1", negocio["id"])
    assert nuevo_estado is False
    asesores = await mem.listar_asesores(negocio["id"])
    assert "ase_inactivo_asig1" not in {a["username"] for a in asesores}

    # Con el único asesor "activo" real cargado al máximo (mismo criterio de
    # balanceo por carga que ya usa la función), igual debe elegirlo a él —
    # nunca al desactivado, aunque su `disponible` siga en True.
    elegido = await asignacion.elegir_asesor_automatico("", negocio["id"])
    assert elegido == "ase_activo_asig1"


async def test_no_hay_candidatos_si_el_unico_disponible_esta_desactivado():
    negocio = await mem.crear_negocio("Negocio Asignacion Solo", "asig-2")
    await mem.crear_usuario("ase_unico_asig2", "pw12345", "Asesor Único", "asesor", negocio["id"])
    await mem.toggle_usuario_activo("ase_unico_asig2", negocio["id"])

    elegido = await asignacion.elegir_asesor_automatico("", negocio["id"])
    assert elegido is None
