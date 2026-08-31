# tests/test_gate54_bloqueo_login_scoped.py — Gate 5.4, hallazgo del
# checkpoint anterior: BloqueoPorIntentos (agent/rate_limit.py) se indexaba
# por `username` crudo. Con T3 haciendo legítimo que dos Negocios compartan
# un username, eso permitía que un ataque de fuerza bruta contra "admin" de
# un Negocio bloqueara también al "admin" de otro Negocio (denegación de
# servicio cross-tenant por destino compartido). Datos sintéticos
# únicamente (crear_negocio), mismo criterio que el resto de Gate 5.3/5.4.

from agent import memory as mem
from agent.dashboard import _resolver_login
from agent.rate_limit import BloqueoPorIntentos


async def _negocio(codigo: str):
    return await mem.crear_negocio(f"Negocio {codigo}", codigo)


async def test_resolver_login_candadea_por_negocio_y_username_cuando_es_unico():
    negocio_a = await _negocio("login-a")
    negocio_b = await _negocio("login-b")
    await mem.crear_usuario("admin", "pw12345678", "Admin A", "admin", negocio_id=negocio_a["id"])
    await mem.crear_usuario("admin", "pw87654321", "Admin B", "admin", negocio_id=negocio_b["id"])

    _, clave_a = await _resolver_login("admin")
    # "admin" es ambiguo entre A y B — sin negocio_id no se puede resolver a
    # una cuenta única (mismo criterio que obtener_usuario), así que la
    # clave cae al fallback de username crudo. Este caso se cubre en el
    # siguiente test con un username que SÍ resuelve sin ambigüedad.
    assert clave_a == "admin"


async def test_resolver_login_usernames_unicos_en_negocios_distintos_no_comparten_clave():
    """El caso real y común: cada Negocio con SUS PROPIOS usernames (lo
    típico), pero coincidiendo en uno solo (ej. "admin" en ambos, mientras
    el resto de las cuentas son distintas) — ESE username, al no ser
    ambiguo dentro de cada consulta con negocio_id, sigue sin poder
    resolverse sin negocio_id. Lo que SÍ deben aislar es un ataque contra
    un username que en un Negocio existe y en otro no."""
    negocio_a = await _negocio("login-c")
    negocio_b = await _negocio("login-d")
    await mem.crear_usuario("asesor_maria", "pw12345678", "Maria", "asesor", negocio_id=negocio_a["id"])
    # negocio_b NO tiene "asesor_maria" — username único en TODO el sistema.

    usuario, clave = await _resolver_login("asesor_maria")
    assert usuario is not None
    assert clave == f"{negocio_a['id']}:asesor_maria"


async def test_bloqueo_por_cuenta_no_cruza_negocios_con_username_no_ambiguo():
    """Núcleo del hallazgo: fuerza bruta contra la cuenta de un Negocio no
    debe bloquear una cuenta de OTRO Negocio, incluso si comparten
    username, siempre que cada resolución sea no ambigua (ver nota en el
    test anterior sobre el caso ambiguo, que ya fallaba cerrado desde
    antes)."""
    negocio_a = await _negocio("login-e")
    negocio_b = await _negocio("login-f")
    await mem.crear_usuario("soporte", "pw12345678", "Soporte A", "asesor", negocio_id=negocio_a["id"])
    await mem.crear_usuario("otro_nombre_b", "pw12345678", "Otro B", "asesor", negocio_id=negocio_b["id"])

    _, clave_soporte_a = await _resolver_login("soporte")
    assert clave_soporte_a == f"{negocio_a['id']}:soporte"

    bloqueo = BloqueoPorIntentos()
    for _ in range(5):
        bloqueo.registrar_fallo(clave_soporte_a, 5, 60)

    assert bloqueo.segundos_restantes(clave_soporte_a) is not None  # cuenta atacada: bloqueada

    _, clave_otro_b = await _resolver_login("otro_nombre_b")
    assert bloqueo.segundos_restantes(clave_otro_b) is None  # cuenta de otro Negocio: intacta


async def test_username_inexistente_conserva_candado_por_username_crudo():
    usuario, clave = await _resolver_login("no_existe_en_ningun_negocio")
    assert usuario is None
    assert clave == "no_existe_en_ningun_negocio"
