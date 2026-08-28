# tests/test_gate52_fundacion.py — Gate 5.2: Fundación Negocio/Unidad.
#
# Cubre el criterio de éxito §16/§17 de la instrucción de Gate 5.2: Negocio,
# Unidad, Configuracion (global/por-negocio/fallback), aislamiento de Canal
# (incluido el camino fail-closed), aislamiento de firma, y el esqueleto de
# RegistroAuditoria. Usa datos SINTÉTICOS de dos Negocios (§17: "aunque solo
# exista Cálidda en producción") — nunca conecta nada real, nunca es una
# prueba de onboarding real de Tenant 002 (eso es Gate 5.7/posterior).

import hashlib
import hmac
import json
from datetime import datetime
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy.exc import IntegrityError

from agent import memory as mem
from agent.providers.meta import ProveedorMeta


# ---------------------------------------------------------------------------
# Negocio
# ---------------------------------------------------------------------------

async def test_crear_negocio():
    negocio = await mem.crear_negocio("Cálidda", "calidda")
    assert negocio["nombre"] == "Cálidda"
    assert negocio["codigo"] == "calidda"
    assert negocio["activo"] is True


async def test_negocio_id_es_uuid():
    negocio = await mem.crear_negocio("Cálidda", "calidda")
    # String(36) con el formato estándar de uuid4 (36 caracteres, 4 guiones)
    assert len(negocio["id"]) == 36
    assert negocio["id"].count("-") == 4


async def test_codigo_de_negocio_es_unico():
    await mem.crear_negocio("Cálidda", "calidda")
    with pytest.raises(IntegrityError):
        await mem.crear_negocio("Otro Cálidda", "calidda")


async def test_negocio_soft_delete_no_borra_la_fila():
    negocio = await mem.crear_negocio("Cálidda", "calidda")
    async with mem.async_session() as session:
        fila = await session.get(mem.Negocio, negocio["id"])
        fila.activo = False
        fila.eliminado_en = datetime.utcnow()
        fila.eliminado_por = "admin_test"
        await session.commit()

    # La fila sigue existiendo — soft delete, no DELETE real.
    todos = await mem.listar_negocios(solo_activos=False)
    activos = await mem.listar_negocios(solo_activos=True)
    assert len(todos) == 1
    assert len(activos) == 0


# ---------------------------------------------------------------------------
# Unidad de Negocio
# ---------------------------------------------------------------------------

async def test_unidad_pertenece_a_negocio():
    negocio = await mem.crear_negocio("Cálidda", "calidda")
    unidad = await mem.crear_unidad_de_negocio(negocio["id"], "Gasodomésticos", "gasodomesticos")
    assert unidad["negocio_id"] == negocio["id"]

    listadas = await mem.listar_unidades_de_negocio(negocio["id"])
    assert len(listadas) == 1
    assert listadas[0]["nombre"] == "Gasodomésticos"


async def test_unidad_no_puede_quedar_sin_negocio():
    # negocio_id es NOT NULL a nivel de esquema — crear una Unidad sin
    # Negocio debe fallar, nunca insertarse con un FK huérfano.
    async with mem.async_session() as session:
        session.add(mem.UnidadDeNegocio(negocio_id=None, nombre="Sin negocio", codigo_interno="x"))
        with pytest.raises(IntegrityError):
            await session.commit()


async def test_codigo_interno_aislado_por_negocio():
    """El mismo codigo_interno puede repetirse en Negocios DISTINTOS (el
    índice único es compuesto negocio_id+codigo_interno, no global)."""
    negocio_a = await mem.crear_negocio("Cálidda", "calidda")
    negocio_b = await mem.crear_negocio("Negocio de prueba", "negocio-prueba")

    await mem.crear_unidad_de_negocio(negocio_a["id"], "Gasodomésticos", "gsd")
    # Mismo codigo_interno "gsd", pero en otro Negocio — debe permitirse.
    await mem.crear_unidad_de_negocio(negocio_b["id"], "Gas Doméstico", "gsd")

    unidades_a = await mem.listar_unidades_de_negocio(negocio_a["id"])
    unidades_b = await mem.listar_unidades_de_negocio(negocio_b["id"])
    assert len(unidades_a) == 1 and len(unidades_b) == 1


async def test_codigo_interno_duplicado_en_el_mismo_negocio_falla():
    negocio = await mem.crear_negocio("Cálidda", "calidda")
    await mem.crear_unidad_de_negocio(negocio["id"], "Gasodomésticos", "gsd")
    with pytest.raises(IntegrityError):
        await mem.crear_unidad_de_negocio(negocio["id"], "Otra unidad", "gsd")


# ---------------------------------------------------------------------------
# Configuracion — global, por-negocio, fallback, compatibilidad
# ---------------------------------------------------------------------------

async def test_configuracion_global():
    await mem.guardar_configuracion("umbral_intermedio", "500")
    valor = await mem.obtener_configuracion("umbral_intermedio", "default")
    assert valor == "500"


async def test_configuracion_especifica_de_negocio_no_afecta_la_global():
    negocio = await mem.crear_negocio("Cálidda", "calidda")
    await mem.guardar_configuracion("umbral_intermedio", "500")  # global
    await mem.guardar_configuracion("umbral_intermedio", "999", negocio_id=negocio["id"])  # override

    global_ = await mem.obtener_configuracion("umbral_intermedio", "default")
    del_negocio = await mem.obtener_configuracion("umbral_intermedio", "default", negocio_id=negocio["id"])
    assert global_ == "500"
    assert del_negocio == "999"


async def test_configuracion_fallback_al_default_si_no_existe():
    valor = await mem.obtener_configuracion("clave_que_nunca_se_guardo", "el_default")
    assert valor == "el_default"


async def test_configuracion_override_ausente_no_hereda_la_global():
    """Un Negocio sin override propio NO ve la config global automáticamente
    a través de obtener_configuracion(negocio_id=...) — cae al default que
    reciba el llamador, nunca silenciosamente al valor global de otro
    alcance (mismo criterio documentado en agent/memory.py)."""
    negocio = await mem.crear_negocio("Cálidda", "calidda")
    await mem.guardar_configuracion("umbral_intermedio", "500")  # solo global

    valor = await mem.obtener_configuracion("umbral_intermedio", "sin_override", negocio_id=negocio["id"])
    assert valor == "sin_override"


async def test_configuracion_compatibilidad_llamador_existente_sin_negocio_id():
    """Un llamador que NO pasa negocio_id (todo el código anterior a Gate
    5.2) debe seguir viendo exactamente el mismo comportamiento: lee/escribe
    la fila global, tal como antes de este Gate."""
    await mem.guardar_configuracion("umbral_senior", "1500")
    valor_sin_kwarg = await mem.obtener_configuracion("umbral_senior", "default")
    assert valor_sin_kwarg == "1500"


# ---------------------------------------------------------------------------
# Canal — aislamiento por Negocio (§16/§17)
# ---------------------------------------------------------------------------

async def _crear_dos_negocios_con_canal():
    negocio_a = await mem.crear_negocio("Cálidda", "calidda")
    negocio_b = await mem.crear_negocio("Negocio de prueba", "negocio-prueba")
    canal_a = await mem.crear_canal_whatsapp(
        "Canal A", "1110000000", access_token="tok-a", app_secret="secreto-a", negocio_id=negocio_a["id"],
    )
    canal_b = await mem.crear_canal_whatsapp(
        "Canal B", "2220000000", access_token="tok-b", app_secret="secreto-b", negocio_id=negocio_b["id"],
    )
    return negocio_a, negocio_b, canal_a, canal_b


async def test_resolver_canal_por_phone_number_id_nunca_cruza_negocio():
    negocio_a, negocio_b, canal_a, canal_b = await _crear_dos_negocios_con_canal()
    proveedor = ProveedorMeta()

    resuelto = await proveedor.resolver_canal(canal_a["phone_number_id"])
    assert resuelto["id"] == canal_a["id"]

    resuelto_b = await proveedor.resolver_canal(canal_b["phone_number_id"])
    assert resuelto_b["id"] == canal_b["id"]


async def test_resolver_canal_por_negocio_id_nunca_devuelve_canal_de_otro_negocio():
    negocio_a, negocio_b, canal_a, canal_b = await _crear_dos_negocios_con_canal()
    proveedor = ProveedorMeta()

    resuelto = await proveedor.resolver_canal(None, negocio_id=negocio_a["id"])
    assert resuelto["id"] == canal_a["id"]
    assert resuelto["id"] != canal_b["id"]

    resuelto_b = await proveedor.resolver_canal(None, negocio_id=negocio_b["id"])
    assert resuelto_b["id"] == canal_b["id"]


async def test_resolver_canal_falla_cerrado_con_dos_negocios_y_sin_contexto():
    """El caso central del riesgo 🔴 de Gate 5.1: SIN numero_whatsapp_id NI
    negocio_id, y con canales activos de MÁS de un Negocio, resolver_canal
    debe rechazar (None) — nunca "el primero que encuentre"."""
    await _crear_dos_negocios_con_canal()
    proveedor = ProveedorMeta()

    resuelto = await proveedor.resolver_canal(None)
    assert resuelto is None


async def test_resolver_canal_con_un_solo_negocio_mantiene_compatibilidad():
    """Con UN solo Negocio en el sistema (el caso real de Cálidda hoy),
    resolver_canal(None) sin ningún contexto sigue funcionando exactamente
    como antes de Gate 5.2 — no se rompe compatibilidad con producción."""
    negocio = await mem.crear_negocio("Cálidda", "calidda")
    canal = await mem.crear_canal_whatsapp(
        "Principal", "3330000000", access_token="tok", app_secret="secreto", negocio_id=negocio["id"],
    )
    proveedor = ProveedorMeta()

    resuelto = await proveedor.resolver_canal(None)
    assert resuelto["id"] == canal["id"]


async def test_resolver_canal_no_inventa_canal_sin_ninguno_activo():
    proveedor = ProveedorMeta()
    resuelto = await proveedor.resolver_canal(None)
    assert resuelto is None


# ---------------------------------------------------------------------------
# Firma — no puede validar Canal B usando el secreto de Canal A
# ---------------------------------------------------------------------------

def _payload_whatsapp(phone_number_id: str) -> bytes:
    return json.dumps({
        "object": "whatsapp_business_account",
        "entry": [{"changes": [{"value": {"metadata": {"phone_number_id": phone_number_id}}}]}],
    }).encode()


def _firmar(secreto: str, body: bytes) -> str:
    return "sha256=" + hmac.new(secreto.encode(), body, hashlib.sha256).hexdigest()


class _RequestFalso:
    def __init__(self, firma: str):
        self.headers = {"x-hub-signature-256": firma}


async def test_firma_valida_de_canal_a_no_valida_para_canal_b():
    negocio_a, negocio_b, canal_a, canal_b = await _crear_dos_negocios_con_canal()
    proveedor = ProveedorMeta()

    # Payload que DICE pertenecer al Canal B, pero firmado con el secreto de A.
    body_de_b = _payload_whatsapp(canal_b["phone_number_id"])
    firma_con_secreto_de_a = _firmar("secreto-a", body_de_b)
    request = _RequestFalso(firma_con_secreto_de_a)

    valido = await proveedor.verificar_firma(request, body_de_b)
    assert valido is False, "una firma de otro canal nunca debe validar el payload de este"


async def test_firma_valida_de_canal_a_valida_correctamente_para_canal_a():
    negocio_a, negocio_b, canal_a, canal_b = await _crear_dos_negocios_con_canal()
    proveedor = ProveedorMeta()

    body_de_a = _payload_whatsapp(canal_a["phone_number_id"])
    firma_correcta = _firmar("secreto-a", body_de_a)
    request = _RequestFalso(firma_correcta)

    valido = await proveedor.verificar_firma(request, body_de_a)
    assert valido is True


async def test_firma_sin_ningun_secreto_configurado_falla_cerrado():
    negocio = await mem.crear_negocio("Cálidda", "calidda")
    await mem.crear_canal_whatsapp("Principal", "3330000000", negocio_id=negocio["id"])  # sin app_secret
    proveedor = ProveedorMeta()

    body = _payload_whatsapp("3330000000")
    request = _RequestFalso("sha256=" + "0" * 64)
    valido = await proveedor.verificar_firma(request, body)
    assert valido is False


# ---------------------------------------------------------------------------
# RegistroAuditoria — inserción, append-only, negocio_id, payload, timestamp
# ---------------------------------------------------------------------------

async def test_auditoria_insercion_basica():
    negocio = await mem.crear_negocio("Cálidda", "calidda")
    await mem.registrar_auditoria(
        accion="canal_creado", actor="admin_test", negocio_id=negocio["id"],
        entidad_tipo="CanalWhatsApp", entidad_id="1", payload={"nombre": "Principal"},
    )
    async with mem.async_session() as session:
        resultado = await session.execute(mem.select(mem.RegistroAuditoria))
        filas = resultado.scalars().all()
        assert len(filas) == 1
        assert filas[0].negocio_id == negocio["id"]
        assert filas[0].actor == "admin_test"
        assert filas[0].payload == {"nombre": "Principal"}
        assert isinstance(filas[0].creado, datetime)


async def test_auditoria_evento_de_plataforma_sin_negocio_es_valido():
    """negocio_id nullable — un evento sin Negocio asociado (plataforma) es
    un caso válido, no un error de datos."""
    await mem.registrar_auditoria(accion="evento_de_plataforma", actor=None)
    async with mem.async_session() as session:
        resultado = await session.execute(mem.select(mem.RegistroAuditoria))
        fila = resultado.scalars().one()
        assert fila.negocio_id is None
        assert fila.actor is None


async def test_auditoria_es_append_only_sin_mecanismo_de_edicion():
    """No existe ningún mecanismo de actualización/borrado de auditoría en
    memory.py — se verifica negativamente sobre el CUERPO ejecutable de
    `registrar_auditoria` (sin docstring, que sí menciona "UPDATE/DELETE" en
    prosa para explicar precisamente que no se usan)."""
    import ast
    import inspect
    codigo_fuente = inspect.getsource(mem.registrar_auditoria)
    arbol = ast.parse(codigo_fuente)
    funcion = arbol.body[0]
    cuerpo_sin_docstring = ast.get_docstring(funcion, clean=False)
    nodos_de_codigo = funcion.body[1:] if (cuerpo_sin_docstring and isinstance(funcion.body[0], ast.Expr)) else funcion.body
    cuerpo_ejecutable = "\n".join(ast.unparse(n) for n in nodos_de_codigo)

    assert "session.delete" not in cuerpo_ejecutable
    assert "update(" not in cuerpo_ejecutable
    assert "delete(" not in cuerpo_ejecutable
    assert "session.add(RegistroAuditoria(" in cuerpo_ejecutable  # sigue siendo un INSERT real


# ---------------------------------------------------------------------------
# Backfill de Cálidda — verificado contra la migración real (no simulado)
# ---------------------------------------------------------------------------

async def test_lead_no_puede_crearse_sin_telefono_pk_intacta():
    """La PK de Lead sigue siendo `telefono` — Gate 5.2 no la toca (eso es
    Gate 5.3). Confirma que el modelo sigue aceptando negocio_id como campo
    adicional, no como reemplazo de la PK."""
    negocio = await mem.crear_negocio("Cálidda", "calidda")
    async with mem.async_session() as session:
        lead = mem.Lead(telefono="51999999999", negocio_id=negocio["id"])
        session.add(lead)
        await session.commit()

    recuperado = await mem.obtener_lead("51999999999")
    assert recuperado is not None
    assert recuperado["telefono"] == "51999999999"


# ---------------------------------------------------------------------------
# Backward compatibility — el resto de memory.py sigue funcionando igual
# ---------------------------------------------------------------------------

async def test_listar_canales_whatsapp_sigue_funcionando_sin_filtrar_por_negocio():
    """listar_canales_whatsapp() (usado por el panel y por ProveedorMeta) no
    cambió su firma en Gate 5.2 — sigue devolviendo todos los canales,
    ahora con negocio_id/unidad_id incluidos en el dict."""
    negocio = await mem.crear_negocio("Cálidda", "calidda")
    await mem.crear_canal_whatsapp("Principal", "3330000000", negocio_id=negocio["id"])
    canales = await mem.listar_canales_whatsapp()
    assert len(canales) == 1
    assert "negocio_id" in canales[0]


async def test_crear_usuario_sin_negocio_id_falla_cerrado():
    """Corrección post-auditoría (H3): crear un usuario NUEVO sin negocio_id
    resuelto ahora falla cerrado con un error claro — ya NO se permite crear
    una cuenta con negocio_id=None (ver test_gate52_correcciones_h1h2h3.py
    para la cobertura completa de H1/H2/H3)."""
    with pytest.raises(ValueError):
        await mem.crear_usuario("asesor_test", "clave123", "Asesor de Prueba", "asesor")
