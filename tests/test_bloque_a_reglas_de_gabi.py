# tests/test_bloque_a_reglas_de_gabi.py — Bloque A de la auditoría de chats del flujo guiado (2026-10-30).
#
# Qué cambia para el cliente:
#   · «lavadora», «lavaseca» y «lava y seca» encuentran el CENTRO DE LAVADO del catálogo (antes Gabi decía que no había).
#   · Cada negocio puede tener reglas SIEMPRE activas en el system prompt (`knowledge/<codigo>/_reglas_de_gabi.md`): para Cálidda,
#     quién es Cálidda Hogar, a dónde van los trámites del gas, los medios de pago y el centro de lavado. Nunca las de otro negocio.
#   · La guía de forma pide tuteo peruano, atender lo que el cliente pide, no hablar del «catálogo» y no responder el precio con otra pregunta.
#   · La base de conocimiento ya no dice «sin tarjeta»: se paga financiado en el recibo o con cualquier medio de pago.

import os
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from agent import brain, memory as mem, tools


def _respuesta_falsa(texto: str = "Respuesta de prueba"):
    uso = SimpleNamespace(input_tokens=100, output_tokens=20, cache_read_input_tokens=0, cache_creation_input_tokens=100)
    return SimpleNamespace(content=[SimpleNamespace(text=texto)], usage=uso)


async def _negocio_con_catalogo(codigo: str):
    negocio = await mem.crear_negocio(f"Negocio {codigo}", codigo)
    for datos in (
        {"codigo_hana": "CL-1", "descripcion": "CENTRO DE LAVADO MABE 20 KG DIAMOND GRAY", "marca": "MABE", "tipo": "EQUIPO", "sub_tipo": "CENTRO DE LAVADO", "precio": "5699"},
        {"codigo_hana": "CL-2", "descripcion": "CENTRO DE LAVADO MABE DE 24 KG GAS BLANCO", "marca": "MABE", "tipo": "EQUIPO", "sub_tipo": "CENTRO DE LAVADO", "precio": "5499"},
        {"codigo_hana": "SE-1", "descripcion": "SECADORA RINNAI 10 KG", "marca": "RINNAI", "tipo": "SECADORA", "sub_tipo": "SECADORA", "precio": "2999"},
    ):
        await mem.crear_producto(datos, "test", negocio["id"])
    return negocio


# ── Lavadora → centro de lavado ──────────────────────────────────────────────

@pytest.mark.parametrize("texto", [
    "Necesito lavadora", "quiero una lavaseca a gas", "busco una lavasecadora", "una lava y seca", "lava-seca", "una lavadora porfa",
])
def test_los_sinonimos_agregan_el_nombre_del_catalogo(texto):
    assert "centro de lavado" in tools.con_sinonimos(texto.lower())


def test_lo_que_no_es_lavado_no_cambia_y_no_se_duplica():
    assert tools.con_sinonimos("quiero una terma") == "quiero una terma"
    assert tools.con_sinonimos("quiero un centro de lavado") == "quiero un centro de lavado"
    assert tools.con_sinonimos("lavadora y centro de lavado") == "lavadora y centro de lavado"


async def test_pedir_lavadora_trae_los_centros_de_lavado_y_no_las_secadoras():
    negocio = await _negocio_con_catalogo("ba-lav")
    productos = await tools.buscar_productos("Necesito lavadora", negocio["id"])
    assert {p["CODIGO HANA"] for p in productos} == {"CL-1", "CL-2"}
    contexto = await tools.obtener_contexto_relevante("necesito una lavaseca", negocio["id"], None)
    assert "CENTRO DE LAVADO MABE" in contexto


# ── Reglas siempre activas de cada negocio ───────────────────────────────────

def test_las_reglas_de_calidda_estan_y_dicen_lo_acordado():
    reglas = tools.reglas_del_negocio("calidda")
    assert "línea comercial de Cálidda de productos y servicios para el hogar" in reglas
    assert "Nunca «Cálidda (la distribuidora)»" in reglas and "nuestros canales" in reglas
    assert "614-9000, opción 5" in reglas and "NO lo derives a un asesor comercial" in reglas
    assert "tarjeta de débito o crédito, QR o transferencia" in reglas and "Nunca digas «sin tarjeta»" in reglas
    assert "CENTROS DE LAVADO" in reglas and "nunca digas que no tenemos lavadoras sin ofrecérselo" in reglas
    # es contexto de Gabi: no se le recita al cliente
    assert "NO se lo repitas al cliente" in reglas


@pytest.mark.parametrize("codigo", [None, "", "otro-negocio-sin-carpeta", "../calidda"])
def test_sin_negocio_o_sin_carpeta_no_hay_reglas(codigo):
    assert tools.reglas_del_negocio(codigo) == ""


def test_el_archivo_de_reglas_no_se_busca_como_conocimiento():
    """Va siempre en el prompt; si además saliera como «fragmento parecido», se repetiría y gastaría tokens."""
    encontrado = tools.buscar_en_knowledge("Cálidda Hogar línea comercial productos servicios hogar distribuidora canales", "calidda", limite=50)
    assert "_reglas_de_gabi.md" not in encontrado


async def test_el_system_prompt_de_calidda_lleva_sus_reglas_al_final():
    negocio = await mem.crear_negocio("Cálidda de prueba", "calidda")
    with patch.object(brain.client.messages, "create", new=AsyncMock(return_value=_respuesta_falsa())) as mock_create:
        await brain.generar_respuesta("Hola", historial=[], modo="produccion", negocio_id=negocio["id"])
    system = mock_create.await_args.kwargs["system"][0]["text"]
    assert "## Forma de los mensajes" in system and "## Reglas de este negocio" in system
    assert system.index("## Forma de los mensajes") < system.index("## Reglas de este negocio")
    assert system.endswith(tools.reglas_del_negocio("calidda"))


async def test_otro_negocio_no_recibe_las_reglas_de_calidda():
    negocio = await mem.crear_negocio("Muebles Sol", "muebles-sol")
    with patch.object(brain.client.messages, "create", new=AsyncMock(return_value=_respuesta_falsa())) as mock_create:
        await brain.generar_respuesta("Hola", historial=[], modo="produccion", negocio_id=negocio["id"])
    system = mock_create.await_args.kwargs["system"][0]["text"]
    assert "Reglas de este negocio" not in system and "Cálidda Hogar" not in system.split("## Forma de los mensajes")[1]
    assert system.endswith(brain.REGLA_FORMA_DEL_MENSAJE)


# ── Guía de forma (para todos los negocios) ──────────────────────────────────

def test_la_guia_de_forma_pide_tuteo_peruano_y_nada_de_catalogo_interno():
    regla = brain.REGLA_FORMA_DEL_MENSAJE
    assert "NUNCA voseo" in regla and "dejás" in regla
    assert "no insistas con el del anuncio" in regla
    assert "Nunca hables de lo que tienes o no cargado" in regla and "«catálogo disponible ahora»" in regla
    assert "nunca respondas «¿cuánto cuesta?» con otra pregunta" in regla


# ── Base de conocimiento ─────────────────────────────────────────────────────

def _leer(nombre: str) -> str:
    with open(os.path.join("knowledge", "calidda", nombre), encoding="utf-8") as f:
        return f.read()


def test_la_base_de_conocimiento_habla_de_medios_de_pago_y_centros_de_lavado():
    politica = _leer("politica_comercial_modalidades_compra.md")
    assert "con cualquier medio de pago: tarjeta de débito o crédito, QR o transferencia" in politica
    assert "nunca debe decir que el pago es «sin tarjeta»" in politica
    base = _leer("base_conocimiento_gasodomesticos.md")
    assert "Centros de lavado a gas: lavan y secan en un mismo equipo" in base and "lavaseca" in base
    assert "Es una sola empresa: Cálidda" in base


def test_ningun_documento_dice_que_se_paga_sin_tarjeta():
    for nombre in os.listdir(os.path.join("knowledge", "calidda")):
        if nombre.endswith((".md", ".txt")) and nombre != "_reglas_de_gabi.md":
            texto = _leer(nombre).lower()
            assert "sin banco ni tarjeta" not in texto and "sin tarjeta de crédito" not in texto, nombre
