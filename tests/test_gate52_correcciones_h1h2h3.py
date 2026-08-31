# tests/test_gate52_correcciones_h1h2h3.py — Gate 5.2: corrección de los 3
# hallazgos bloqueantes 🔴 de la auditoría adversarial (guardar_mensaje,
# creación de Lead, creación de Usuario/Canal/Campaña sin negocio_id).
#
# Cubre §12 de la instrucción de corrección: para Lead, Mensaje, Usuario,
# Canal y Campaña — crear con Negocio A, crear con Negocio B, aislamiento
# entre ambos, y fail-closed cuando no hay contexto suficiente. Ninguna
# prueba usa un negocio_id hardcodeado como "el correcto" — cada Negocio se
# crea sintéticamente en el propio test (§17 de la instrucción original:
# datos sintéticos, nunca un Tenant 002 real).

import pytest
from sqlalchemy.exc import IntegrityError

from agent import memory as mem
from agent.providers.meta import ProveedorMeta


async def _dos_negocios():
    negocio_a = await mem.crear_negocio("Negocio A", "negocio-a")
    negocio_b = await mem.crear_negocio("Negocio B", "negocio-b")
    return negocio_a, negocio_b


# ---------------------------------------------------------------------------
# H2 — Lead
# ---------------------------------------------------------------------------

async def test_lead_creado_con_negocio_a_queda_scoped_a_negocio_a():
    negocio_a, negocio_b = await _dos_negocios()
    await mem.actualizar_lead("51900000001", nombre="Cliente A", negocio_id=negocio_a["id"])
    lead = await mem.obtener_lead("51900000001")
    assert lead["telefono"] == "51900000001"
    async with mem.async_session() as session:
        fila = await session.get(mem.Lead, "51900000001")
        assert fila.negocio_id == negocio_a["id"]
        assert fila.negocio_id != negocio_b["id"]


async def test_lead_creado_con_negocio_b_queda_scoped_a_negocio_b():
    negocio_a, negocio_b = await _dos_negocios()
    await mem.actualizar_lead("51900000002", nombre="Cliente B", negocio_id=negocio_b["id"])
    async with mem.async_session() as session:
        fila = await session.get(mem.Lead, "51900000002")
        assert fila.negocio_id == negocio_b["id"]


async def test_actualizar_lead_nunca_usa_un_negocio_por_defecto():
    """No hay NINGÚN Negocio "de más confianza" — crear sin negocio_id falla
    cerrado incluso si en el sistema ya existe exactamente un Negocio (a
    diferencia de resolver_canal, que sí resuelve en ese caso: la fuente
    legítima de negocio_id para un Lead es el Canal de entrada, nunca "el
    único Negocio que hay" — actualizar_lead no adivina)."""
    await mem.crear_negocio("Único Negocio", "unico")
    with pytest.raises(ValueError, match="negocio_id"):
        await mem.actualizar_lead("51900000003", nombre="Sin negocio_id")


async def test_actualizar_lead_lead_existente_no_requiere_negocio_id_de_nuevo():
    """El Negocio de un Lead se fija una sola vez, en su creación — una
    actualización posterior (ej. Gabi completando datos) no necesita volver
    a pasar negocio_id."""
    negocio_a, _ = await _dos_negocios()
    await mem.actualizar_lead("51900000004", nombre="Cliente", negocio_id=negocio_a["id"])
    await mem.actualizar_lead("51900000004", interes="terma")  # sin negocio_id, lead ya existe
    lead = await mem.obtener_lead("51900000004")
    assert lead["interes"] == "terma"
    async with mem.async_session() as session:
        fila = await session.get(mem.Lead, "51900000004")
        assert fila.negocio_id == negocio_a["id"]  # no se perdió ni cambió


@pytest.mark.parametrize("funcion_defensiva", [
    "asignar_asesor_a_lead", "pausar_gabi_manual", "registrar_fallo_tecnico", "asignar_campana_origen",
])
async def test_funciones_defensivas_de_lead_fallan_cerrado_sin_lead_existente(funcion_defensiva):
    """Las 5 funciones que antes creaban un Lead "vacío" silenciosamente
    (guardar_venta, asignar_asesor_a_lead, pausar_gabi_manual,
    registrar_fallo_tecnico, asignar_campana_origen) ahora exigen que el
    Lead ya exista — nunca inventan su pertenencia a un Negocio."""
    telefono = "51900000005"
    with pytest.raises(ValueError, match="no existe un Lead"):
        if funcion_defensiva == "asignar_asesor_a_lead":
            await mem.asignar_asesor_a_lead(telefono, "asesor1")
        elif funcion_defensiva == "pausar_gabi_manual":
            await mem.pausar_gabi_manual(telefono)
        elif funcion_defensiva == "registrar_fallo_tecnico":
            await mem.registrar_fallo_tecnico(telefono)
        elif funcion_defensiva == "asignar_campana_origen":
            await mem.asignar_campana_origen(telefono, "Campaña X")


async def test_funciones_defensivas_de_lead_funcionan_con_lead_ya_existente():
    negocio_a, _ = await _dos_negocios()
    telefono = "51900000006"
    await mem.actualizar_lead(telefono, nombre="Cliente", negocio_id=negocio_a["id"])
    # Ninguna de estas debe fallar ahora que el Lead ya existe.
    await mem.asignar_asesor_a_lead(telefono, "asesor1")
    await mem.pausar_gabi_manual(telefono)
    total = await mem.registrar_fallo_tecnico(telefono)
    assert total == 1
    await mem.asignar_campana_origen(telefono, "Campaña X")
    lead = await mem.obtener_lead(telefono)
    assert lead["campana_origen"] == "Campaña X"


# ---------------------------------------------------------------------------
# H1 — Mensaje
# ---------------------------------------------------------------------------

async def test_mensaje_persistido_para_negocio_a_queda_scoped_correctamente():
    negocio_a, negocio_b = await _dos_negocios()
    await mem.actualizar_lead("51900000010", nombre="Cliente A", negocio_id=negocio_a["id"])
    mensaje = await mem.guardar_mensaje("51900000010", "user", "hola desde negocio A")
    assert mensaje["telefono"] == "51900000010"
    async with mem.async_session() as session:
        fila = await session.get(mem.Mensaje, mensaje["id"])
        assert fila.negocio_id == negocio_a["id"]
        assert fila.negocio_id != negocio_b["id"]


async def test_mensaje_persistido_para_negocio_b_queda_scoped_correctamente():
    negocio_a, negocio_b = await _dos_negocios()
    await mem.actualizar_lead("51900000011", nombre="Cliente B", negocio_id=negocio_b["id"])
    mensaje = await mem.guardar_mensaje("51900000011", "user", "hola desde negocio B")
    async with mem.async_session() as session:
        fila = await session.get(mem.Mensaje, mensaje["id"])
        assert fila.negocio_id == negocio_b["id"]


async def test_mensaje_negocio_id_viene_del_lead_no_de_un_parametro_manipulable():
    """El negocio_id de un Mensaje SIEMPRE se resuelve del Lead — no existe
    ningún parámetro que un llamador pueda usar para "cruzar" el mensaje
    hacia otro Negocio distinto del que realmente tiene el Lead."""
    negocio_a, negocio_b = await _dos_negocios()
    await mem.actualizar_lead("51900000012", nombre="Cliente A", negocio_id=negocio_a["id"])
    import inspect
    firma = inspect.signature(mem.guardar_mensaje)
    assert "negocio_id" not in firma.parameters


async def test_guardar_mensaje_falla_cerrado_sin_lead_existente():
    """`Mensaje.negocio_id` es NOT NULL a nivel de columna (corrección
    post-auditoría) — ya no es posible que un Lead exista sin negocio_id,
    así que el único camino real de fail-closed es "el Lead no existe
    todavía"."""
    with pytest.raises(ValueError, match="negocio_id"):
        await mem.guardar_mensaje("51900000099", "user", "no debería guardarse nunca")


# ---------------------------------------------------------------------------
# H3 — Usuario
# ---------------------------------------------------------------------------

async def test_usuario_creado_con_negocio_a_queda_aislado():
    negocio_a, negocio_b = await _dos_negocios()
    await mem.crear_usuario("usuario_a", "clave", "Usuario A", "asesor", negocio_id=negocio_a["id"])
    usuario = await mem.obtener_usuario("usuario_a")
    assert usuario["negocio_id"] == negocio_a["id"]
    assert usuario["negocio_id"] != negocio_b["id"]


async def test_usuario_creado_con_negocio_b_queda_aislado():
    negocio_a, negocio_b = await _dos_negocios()
    await mem.crear_usuario("usuario_b", "clave", "Usuario B", "asesor", negocio_id=negocio_b["id"])
    usuario = await mem.obtener_usuario("usuario_b")
    assert usuario["negocio_id"] == negocio_b["id"]


async def test_crear_usuario_nunca_usa_default_silencioso_a_ningun_negocio():
    """Desde Gate 5.4 (T3): negocio_id pasó de opcional-con-ValueError a
    obligatorio en la firma — Python mismo lo exige (TypeError), ninguna
    llamada puede omitirlo ni caer en un default silencioso."""
    await mem.crear_negocio("Único Negocio", "unico")
    with pytest.raises(TypeError):
        await mem.crear_usuario("usuario_sin_negocio", "clave", "X", "asesor")


async def test_cambiar_password_de_usuario_existente_exige_negocio_id_correcto():
    """Desde Gate 5.4 (T3): username ya no es PK global (puede repetirse
    entre Negocios), así que "actualizar por username solo" dejó de ser una
    operación válida — reemplaza a la vieja
    test_cambiar_password_de_usuario_existente_no_exige_negocio_id.
    Actualizar SIEMPRE exige negocio_id, y solo actualiza la fila de ESE
    Negocio (nunca crea una fila duplicada ni pisa la de otro)."""
    negocio_a, negocio_b = await _dos_negocios()
    await mem.crear_usuario("usuario_a", "clave", "Usuario A", "asesor", negocio_id=negocio_a["id"])

    with pytest.raises(TypeError):
        await mem.crear_usuario("usuario_a", "clave-nueva", "Usuario A Renombrado", "asesor")

    await mem.crear_usuario("usuario_a", "clave-nueva", "Usuario A Renombrado", "asesor", negocio_id=negocio_a["id"])
    usuario = await mem.obtener_usuario("usuario_a", negocio_id=negocio_a["id"])
    assert usuario["negocio_id"] == negocio_a["id"]
    assert usuario["nombre"] == "Usuario A Renombrado"
    assert await mem.obtener_usuario("usuario_a", negocio_id=negocio_b["id"]) is None


# ---------------------------------------------------------------------------
# H3 — Canal
# ---------------------------------------------------------------------------

async def test_canal_creado_con_negocio_a_queda_aislado():
    negocio_a, negocio_b = await _dos_negocios()
    canal = await mem.crear_canal_whatsapp("Canal A", "1112223333", negocio_id=negocio_a["id"])
    assert canal["negocio_id"] == negocio_a["id"]
    assert canal["negocio_id"] != negocio_b["id"]


async def test_crear_canal_whatsapp_falla_cerrado_sin_negocio_id():
    await mem.crear_negocio("Único Negocio", "unico")
    with pytest.raises(ValueError, match="negocio_id"):
        await mem.crear_canal_whatsapp("Canal sin negocio", "4445556666")


async def test_resolver_canal_entre_negocio_a_y_b_nunca_cruza():
    negocio_a, negocio_b = await _dos_negocios()
    canal_a = await mem.crear_canal_whatsapp("Canal A", "1112223333", negocio_id=negocio_a["id"])
    canal_b = await mem.crear_canal_whatsapp("Canal B", "4445556666", negocio_id=negocio_b["id"])
    proveedor = ProveedorMeta()
    resuelto_a = await proveedor.resolver_canal(None, negocio_id=negocio_a["id"])
    resuelto_b = await proveedor.resolver_canal(None, negocio_id=negocio_b["id"])
    assert resuelto_a["id"] == canal_a["id"]
    assert resuelto_b["id"] == canal_b["id"]


# ---------------------------------------------------------------------------
# H3 — Campaña
# ---------------------------------------------------------------------------

async def test_campana_creada_con_negocio_a_queda_aislada():
    negocio_a, negocio_b = await _dos_negocios()
    campana = await mem.crear_campana("Campaña A", "texto_saludo", "hola-a", negocio_id=negocio_a["id"])
    assert campana["negocio_id"] == negocio_a["id"]
    assert campana["negocio_id"] != negocio_b["id"]


async def test_crear_campana_falla_cerrado_sin_negocio_id():
    await mem.crear_negocio("Único Negocio", "unico")
    with pytest.raises(ValueError, match="negocio_id"):
        await mem.crear_campana("Campaña sin negocio", "texto_saludo", "hola-x")


async def test_campana_unidad_id_puede_quedar_null_sin_inventar_unidad():
    """Excepción temporal de migración (Arquitectura Contractual §5):
    unidad_id sigue sin exigirse — nunca se inventa una Unidad solo para
    llenar la FK."""
    negocio_a, _ = await _dos_negocios()
    campana = await mem.crear_campana("Campaña A", "texto_saludo", "hola-a", negocio_id=negocio_a["id"])
    assert campana["unidad_id"] is None


# ---------------------------------------------------------------------------
# sembrar_canales_desde_env — bootstrap con negocio_id EXPLÍCITO (corrección
# arquitectónica final: ya no busca "el único Negocio", nunca hardcodea
# Cálidda ni ningún código fijo — negocio_id es responsabilidad exclusiva
# de quien llama, ver Caso A-D de la instrucción de corrección).
# ---------------------------------------------------------------------------

async def test_sembrar_canales_desde_env_caso_a_negocio_id_de_a():
    """Caso A: existen Negocio A y B; se pasa negocio_id=A → todos los
    canales creados pertenecen a A."""
    negocio_a, negocio_b = await _dos_negocios()
    import os
    os.environ["META_PHONE_NUMBER_ID"] = "9998887777"
    os.environ["META_ACCESS_TOKEN"] = "tok"
    os.environ["META_APP_SECRET"] = "secreto"
    try:
        await mem.sembrar_canales_desde_env(negocio_a["id"])
    finally:
        for var in ("META_PHONE_NUMBER_ID", "META_ACCESS_TOKEN", "META_APP_SECRET"):
            os.environ.pop(var, None)
    canales = await mem.listar_canales_whatsapp()
    assert len(canales) == 1
    assert canales[0]["negocio_id"] == negocio_a["id"]
    assert canales[0]["negocio_id"] != negocio_b["id"]


async def test_sembrar_canales_desde_env_caso_b_negocio_id_de_b():
    """Caso B: mismos dos Negocios; se pasa negocio_id=B → todos los
    canales creados pertenecen a B."""
    negocio_a, negocio_b = await _dos_negocios()
    import os
    os.environ["META_PHONE_NUMBER_ID"] = "9998887777"
    os.environ["META_ACCESS_TOKEN"] = "tok"
    os.environ["META_APP_SECRET"] = "secreto"
    try:
        await mem.sembrar_canales_desde_env(negocio_b["id"])
    finally:
        for var in ("META_PHONE_NUMBER_ID", "META_ACCESS_TOKEN", "META_APP_SECRET"):
            os.environ.pop(var, None)
    canales = await mem.listar_canales_whatsapp()
    assert len(canales) == 1
    assert canales[0]["negocio_id"] == negocio_b["id"]


async def test_sembrar_canales_desde_env_caso_c_sin_contexto_falla_cerrado():
    """Caso C: existen múltiples Negocios y NO se proporciona negocio_id
    (None) — el bootstrap falla cerrado, no crea ningún canal. Ya no hay
    ninguna resolución automática por "el único"/"el primero"."""
    await _dos_negocios()
    import os
    os.environ["META_PHONE_NUMBER_ID"] = "9998887777"
    os.environ["META_ACCESS_TOKEN"] = "tok"
    os.environ["META_APP_SECRET"] = "secreto"
    try:
        await mem.sembrar_canales_desde_env(None)
    finally:
        for var in ("META_PHONE_NUMBER_ID", "META_ACCESS_TOKEN", "META_APP_SECRET"):
            os.environ.pop(var, None)
    canales = await mem.listar_canales_whatsapp()
    assert len(canales) == 0


async def test_sembrar_canales_desde_env_caso_d_calidda_sola_requiere_identificacion_explicita():
    """Caso D: existe únicamente Cálidda, pero el bootstrap solo funciona si
    se la identifica por el mecanismo explícito (negocio_id resuelto por su
    codigo) — NO por ser la única del sistema. Sin negocio_id (aunque haya
    un solo Negocio), sigue fallando cerrado."""
    await mem.crear_negocio("Cálidda", "calidda")
    import os
    os.environ["META_PHONE_NUMBER_ID"] = "9998887777"
    os.environ["META_ACCESS_TOKEN"] = "tok"
    os.environ["META_APP_SECRET"] = "secreto"
    try:
        await mem.sembrar_canales_desde_env(None)  # sin identificación explícita
    finally:
        for var in ("META_PHONE_NUMBER_ID", "META_ACCESS_TOKEN", "META_APP_SECRET"):
            os.environ.pop(var, None)
    canales = await mem.listar_canales_whatsapp()
    assert len(canales) == 0, "no debe sembrar solo porque Cálidda es la única — se exige identificación explícita"


async def test_sembrar_canales_desde_env_negocio_id_inexistente_falla_cerrado():
    """Defensa adicional dentro de la propia función: un negocio_id que NO
    corresponde a ningún Negocio real (ej. típo en NEGOCIO_BOOTSTRAP_CODIGO
    resuelto contra un Negocio que luego se borró) también falla cerrado —
    la función no confía ciegamente en lo que recibe."""
    import os
    os.environ["META_PHONE_NUMBER_ID"] = "9998887777"
    os.environ["META_ACCESS_TOKEN"] = "tok"
    os.environ["META_APP_SECRET"] = "secreto"
    try:
        await mem.sembrar_canales_desde_env("id-que-no-existe-en-ningun-lado")
    finally:
        for var in ("META_PHONE_NUMBER_ID", "META_ACCESS_TOKEN", "META_APP_SECRET"):
            os.environ.pop(var, None)
    canales = await mem.listar_canales_whatsapp()
    assert len(canales) == 0


async def test_sembrar_canales_desde_env_es_idempotente():
    """Ejecutar el bootstrap dos veces no duplica canales, ni los "mueve" a
    otro Negocio — la segunda corrida no toca nada porque ya hay canales."""
    negocio_a, negocio_b = await _dos_negocios()
    import os
    os.environ["META_PHONE_NUMBER_ID"] = "9998887777"
    os.environ["META_ACCESS_TOKEN"] = "tok"
    os.environ["META_APP_SECRET"] = "secreto"
    try:
        await mem.sembrar_canales_desde_env(negocio_a["id"])
        await mem.sembrar_canales_desde_env(negocio_b["id"])  # 2da corrida, incluso con OTRO negocio_id
    finally:
        for var in ("META_PHONE_NUMBER_ID", "META_ACCESS_TOKEN", "META_APP_SECRET"):
            os.environ.pop(var, None)
    canales = await mem.listar_canales_whatsapp()
    assert len(canales) == 1  # no se duplicó
    assert canales[0]["negocio_id"] == negocio_a["id"]  # y no "saltó" a B en la 2da corrida


async def test_sembrar_canales_desde_env_no_conoce_a_calidda():
    """Revisión adversarial: la función no contiene ningún literal 'calidda'
    ni 'Cálidda' en su código — ni como valor de comparación ni como
    default."""
    import inspect
    fuente = inspect.getsource(mem.sembrar_canales_desde_env)
    assert "calidda" not in fuente.lower()
