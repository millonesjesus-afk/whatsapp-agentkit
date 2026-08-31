# tests/test_gate54_usuario_multi_tenant.py — Gate 5.4, T3: Usuario migrado
# de PK global (username) a PK UUID, único por (negocio_id, username).
# Datos sintéticos únicamente, mismo criterio que el resto del Gate 5.3/5.4
# — ningún Tenant 002 real, ningún negocio hardcodeado como "el correcto".

import pytest

from agent import memory as mem


async def _negocio(codigo: str):
    return await mem.crear_negocio(f"Negocio {codigo}", codigo)


# ---------------------------------------------------------------------------
# El hallazgo central (H1 / T3): mismo username en dos Negocios
# ---------------------------------------------------------------------------

async def test_dos_usuarios_mismo_username_en_negocios_distintos_pueden_existir():
    negocio_a = await _negocio("usr1a")
    negocio_b = await _negocio("usr1b")

    await mem.crear_usuario("admin", "passwordA123", "Admin de A", "admin", negocio_id=negocio_a["id"])
    await mem.crear_usuario("admin", "passwordB123", "Admin de B", "admin", negocio_id=negocio_b["id"])

    usuario_a = await mem.obtener_usuario("admin", negocio_id=negocio_a["id"])
    usuario_b = await mem.obtener_usuario("admin", negocio_id=negocio_b["id"])

    assert usuario_a is not None and usuario_b is not None
    assert usuario_a["nombre"] == "Admin de A"
    assert usuario_b["nombre"] == "Admin de B"
    assert usuario_a["negocio_id"] == negocio_a["id"]
    assert usuario_b["negocio_id"] == negocio_b["id"]


async def test_crear_usuario_en_negocio_b_no_pisa_al_de_negocio_a():
    """El hallazgo H1 original: antes, crear un 'admin' en Negocio B
    sobreescribía silenciosamente password/rol/nombre del 'admin' de
    Negocio A porque username era PK global. Ahora son filas distintas."""
    negocio_a = await _negocio("usr2a")
    negocio_b = await _negocio("usr2b")

    await mem.crear_usuario("admin", "passwordOriginal1", "Original A", "admin", negocio_id=negocio_a["id"])
    await mem.crear_usuario("admin", "passwordNueva1", "Nuevo B", "supervisor", negocio_id=negocio_b["id"])

    usuario_a = await mem.obtener_usuario("admin", negocio_id=negocio_a["id"])
    assert usuario_a["nombre"] == "Original A"  # intacto
    assert usuario_a["rol"] == "admin"

    import bcrypt
    assert bcrypt.checkpw(b"passwordOriginal1", usuario_a["password_hash"].encode())


async def test_cambiar_password_en_a_no_afecta_a_b():
    negocio_a = await _negocio("usr3a")
    negocio_b = await _negocio("usr3b")
    await mem.crear_usuario("asesor1", "viejaA12345", "Asesor A", "asesor", negocio_id=negocio_a["id"])
    await mem.crear_usuario("asesor1", "viejaB12345", "Asesor B", "asesor", negocio_id=negocio_b["id"])

    await mem.cambiar_password("asesor1", negocio_a["id"], "nuevaPasswordA1")

    import bcrypt
    usuario_a = await mem.obtener_usuario("asesor1", negocio_id=negocio_a["id"])
    usuario_b = await mem.obtener_usuario("asesor1", negocio_id=negocio_b["id"])
    assert bcrypt.checkpw(b"nuevaPasswordA1", usuario_a["password_hash"].encode())
    assert bcrypt.checkpw(b"viejaB12345", usuario_b["password_hash"].encode())  # intacta


async def test_cambiar_password_con_negocio_id_equivocado_no_hace_nada():
    """El hallazgo de seguridad: reset de password ya no puede alcanzar la
    cuenta de otro Negocio ni con el username correcto."""
    negocio_a = await _negocio("usr4a")
    negocio_b = await _negocio("usr4b")
    await mem.crear_usuario("asesor1", "original12345", "Asesor A", "asesor", negocio_id=negocio_a["id"])

    await mem.cambiar_password("asesor1", negocio_b["id"], "intentoDeAtaqueX1")

    import bcrypt
    usuario_a = await mem.obtener_usuario("asesor1", negocio_id=negocio_a["id"])
    assert bcrypt.checkpw(b"original12345", usuario_a["password_hash"].encode())  # sin cambios
    assert await mem.obtener_usuario("asesor1", negocio_id=negocio_b["id"]) is None  # no existe ahí


async def test_actualizar_nivel_asesor_scoped_por_negocio():
    negocio_a = await _negocio("usr5a")
    negocio_b = await _negocio("usr5b")
    await mem.crear_usuario("asesor1", "passw0rd12345", "Asesor A", "asesor", negocio_id=negocio_a["id"], nivel="junior")
    await mem.crear_usuario("asesor1", "passw0rd67890", "Asesor B", "asesor", negocio_id=negocio_b["id"], nivel="junior")

    await mem.actualizar_nivel_asesor("asesor1", negocio_a["id"], "senior")

    usuario_a = await mem.obtener_usuario("asesor1", negocio_id=negocio_a["id"])
    usuario_b = await mem.obtener_usuario("asesor1", negocio_id=negocio_b["id"])
    assert usuario_a["nivel"] == "senior"
    assert usuario_b["nivel"] == "junior"  # intacto


async def test_actualizar_disponibilidad_scoped_por_negocio():
    negocio_a = await _negocio("usr6a")
    negocio_b = await _negocio("usr6b")
    await mem.crear_usuario("asesor1", "passw0rd12345", "Asesor A", "asesor", negocio_id=negocio_a["id"])
    await mem.crear_usuario("asesor1", "passw0rd67890", "Asesor B", "asesor", negocio_id=negocio_b["id"])

    await mem.actualizar_disponibilidad("asesor1", negocio_a["id"], False)

    usuario_a = await mem.obtener_usuario("asesor1", negocio_id=negocio_a["id"])
    usuario_b = await mem.obtener_usuario("asesor1", negocio_id=negocio_b["id"])
    assert usuario_a["disponible"] is False
    assert usuario_b["disponible"] is True  # default, intacto


# ---------------------------------------------------------------------------
# obtener_usuario sin negocio_id (login / resumen de sesión)
# ---------------------------------------------------------------------------

async def test_obtener_usuario_sin_negocio_id_resuelve_username_unico():
    """Caso normal (hoy, con un solo Negocio real): sin colisión, el login
    por username puro sigue funcionando exactamente igual que antes."""
    negocio = await _negocio("usr7")
    await mem.crear_usuario("unico_global", "passw0rd12345", "Único", "admin", negocio_id=negocio["id"])

    usuario = await mem.obtener_usuario("unico_global")
    assert usuario is not None
    assert usuario["negocio_id"] == negocio["id"]


async def test_obtener_usuario_sin_negocio_id_falla_cerrado_ante_colision():
    """Caso nuevo, solo posible con más de un Negocio real: dos Negocios con
    el mismo username hacen que el login por username puro sea ambiguo — se
    falla cerrado (None) en vez de adivinar cuál de las dos cuentas es,
    limitación conocida y documentada, no un bug."""
    negocio_a = await _negocio("usr8a")
    negocio_b = await _negocio("usr8b")
    await mem.crear_usuario("colisionado", "passw0rd12345", "De A", "admin", negocio_id=negocio_a["id"])
    await mem.crear_usuario("colisionado", "passw0rd67890", "De B", "admin", negocio_id=negocio_b["id"])

    assert await mem.obtener_usuario("colisionado") is None
    # Pero SÍ se puede resolver cada uno con negocio_id explícito.
    assert await mem.obtener_usuario("colisionado", negocio_id=negocio_a["id"]) is not None
    assert await mem.obtener_usuario("colisionado", negocio_id=negocio_b["id"]) is not None


async def test_obtener_usuario_username_inexistente_devuelve_none():
    assert await mem.obtener_usuario("no_existe_este_username") is None


# ---------------------------------------------------------------------------
# Tenant 001/002 — mismo teléfono Y mismo username, sin cruce en absoluto
# ---------------------------------------------------------------------------

async def test_tenant_002_usuario_y_lead_mismo_identificador_sin_cruce():
    """Caso obligatorio del Gate: mismo username Y mismo teléfono en dos
    Negocios distintos — ningún dato debe cruzarse."""
    negocio_a = await _negocio("usr9a")
    negocio_b = await _negocio("usr9b")
    canal_a = await mem.crear_canal_whatsapp(nombre="Canal A", phone_number_id="30000000001", negocio_id=negocio_a["id"])
    canal_b = await mem.crear_canal_whatsapp(nombre="Canal B", phone_number_id="30000000002", negocio_id=negocio_b["id"])
    telefono = "51900300001"

    await mem.crear_usuario("admin", "passw0rd12345", "Admin A", "admin", negocio_id=negocio_a["id"])
    await mem.crear_usuario("admin", "passw0rd67890", "Admin B", "admin", negocio_id=negocio_b["id"])
    await mem.resolver_conversation_activa(telefono, negocio_a["id"], canal_a["id"])
    await mem.resolver_conversation_activa(telefono, negocio_b["id"], canal_b["id"])
    await mem.actualizar_lead(telefono, negocio_id=negocio_a["id"], nombre="Cliente A")

    usuario_a = await mem.obtener_usuario("admin", negocio_id=negocio_a["id"])
    usuario_b = await mem.obtener_usuario("admin", negocio_id=negocio_b["id"])
    lead_a = await mem.obtener_lead(telefono, negocio_id=negocio_a["id"])
    lead_b = await mem.obtener_lead(telefono, negocio_id=negocio_b["id"])

    assert usuario_a["nombre"] == "Admin A" and usuario_b["nombre"] == "Admin B"
    assert lead_a is not None and lead_a["nombre"] == "Cliente A"
    assert lead_b is None  # el Lead (PK global telefono) pertenece a Negocio A únicamente
