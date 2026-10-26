# tests/test_formato_whatsapp.py — Mejoras de Gabi, Fase 1 (2026-10-07): limpieza determinista del markdown
# que Claude mete en los mensajes de Gabi y que WhatsApp muestra crudo (`**negrita**`, `#`, tablas, `-`).
# Auditoría de 399 chats: 41 % de los mensajes de Gabi traían `**` visibles.
#
# Se prueba: cada regla del limpiador, su idempotencia, la aplicación en origen (brain, ambos canales), el
# historial limpio EN MEMORIA, la red de seguridad de la capa de envíos (solo orígenes de Gabi, nunca el
# asesor) y el interruptor `gabi_limpieza_formato_activo`.

import asyncio
import logging
import os
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")
os.environ.setdefault("WHATSAPP_PROVIDER", "meta")

import pytest

from agent import brain, envios, formato_whatsapp
from agent import memory as mem
from agent.formato_whatsapp import formatear_para_whatsapp as f


@pytest.fixture(autouse=True)
def _cache_limpia():
    formato_whatsapp.limpiar_cache()
    yield
    formato_whatsapp.limpiar_cache()


# ── Reglas del limpiador ─────────────────────────────────────────────────────

def test_negrita_doble_pasa_a_un_solo_asterisco():
    assert f("Hola **Ana**, cuesta **S/ 419.90** 😊") == "Hola *Ana*, cuesta *S/ 419.90* 😊"


def test_doble_asterisco_huerfano_se_quita():
    assert f("Precio: S/ 419.90** (promo)") == "Precio: S/ 419.90 (promo)"
    assert f("**Importante: revisa tu DNI") == "Importante: revisa tu DNI"


def test_multiplicacion_y_potencias_no_se_tocan():
    assert f("3 * 4 = 12 y 2**3") == "3 * 4 = 12 y 2**3"


def test_negrita_de_whatsapp_queda_igual():
    assert f("*Hola*") == "*Hola*"


def test_el_pipe_de_las_cuotas_de_formatear_producto_no_es_una_tabla():
    texto = "Cuotas: 12 meses: S/ 45.30 | 24 meses: S/ 28.10"
    assert f(texto) == texto


def test_encabezado_y_lista_con_negrita():
    assert f("## Opciones\n- **Rheem**: S/ 419") == "*Opciones*\n• *Rheem*: S/ 419"


def test_encabezado_con_asteriscos_y_cierre_de_almohadillas():
    assert f("### **Beneficios** ###") == "*Beneficios*"


def test_listas_con_guion_asterisco_y_mas_pasan_a_vineta_y_conservan_sangria():
    assert f("- uno\n* dos\n+ tres\n  - sub") == "• uno\n• dos\n• tres\n  • sub"


def test_lista_numerada_y_numero_negativo_no_se_tocan():
    assert f("1. uno\n2. dos\n-5 grados") == "1. uno\n2. dos\n-5 grados"


def test_cursiva_con_guion_bajo_doble_y_tachado():
    assert f("__importante__ y ~~viejo~~") == "*importante* y ~viejo~"
    assert f("mi_variable__interna y snake__case") == "mi_variable__interna y snake__case"


def test_enlace_markdown_pasa_a_texto_y_url():
    assert f("Mira [el catálogo](https://ejemplo.pe/cat) hoy") == "Mira el catálogo: https://ejemplo.pe/cat hoy"


def test_regla_horizontal_se_elimina():
    assert f("Arriba\n---\nAbajo") == "Arriba\nAbajo"
    assert f("Arriba\n***\nAbajo") == "Arriba\nAbajo"


def test_tabla_markdown_pasa_a_lineas_con_separador():
    tabla = "| Marca | Precio |\n|---|---|\n| Rheem | S/ 419 |\n| Sole | S/ 389 |"
    assert f(tabla) == "Marca · Precio\nRheem · S/ 419\nSole · S/ 389"


def test_tres_o_mas_saltos_de_linea_se_reducen_a_dos():
    assert f("a\n\n\n\nb") == "a\n\nb"


def test_bloque_de_codigo_queda_intacto_y_lo_de_afuera_se_limpia():
    assert f("```**x**```") == "```**x**```"
    assert f("**antes** ```\n**x**\n- y\n``` **después**") == "*antes* ```\n**x**\n- y\n``` *después*"


def test_none_vacio_y_no_texto():
    assert f(None) is None
    assert f("") == ""
    assert f(123) == 123


def test_idempotencia_en_todos_los_casos():
    casos = [
        "Hola **Ana**, cuesta **S/ 419.90** 😊", "Precio: S/ 419.90** (promo)", "3 * 4 = 12 y 2**3", "*Hola*",
        "Cuotas: 12 meses: S/ 45.30 | 24 meses: S/ 28.10", "## Opciones\n- **Rheem**: S/ 419", "```**x**```",
        "| a | b |\n|---|---|\n| 1 | 2 |", "---\nhola\n***", "[ver](https://x.com/a)", "~~x~~ __y__ a__b",
        "* **Rheem** uno\n* dos", "- item\n\n\n\nfin", "**Total:** S/ 5", "***negrita cursiva***", "**a** **b** ** c",
        "# 1", "texto\n\n\n", "  - sub\n    - sub2",
    ]
    for c in casos:
        una = f(c)
        assert f(una) == una, c


def test_una_respuesta_real_de_formatear_producto_queda_intacta():
    from agent.tools import formatear_producto
    producto = {"MARCA": "Rheem", "DESCRIPCIÓN": "Terma a gas 10 L", "PRECIO": "419.90", "CANAL": "Cálidda",
                "COMBO": "", "INCLUYE CONEXIÓN": "Sí"}
    texto = formatear_producto(producto, 0.40, 0.18)
    assert "|" in texto and "Cuotas:" in texto
    assert f(texto) == texto
    # Y metido en una respuesta de Claude con negrita, solo cambia la negrita.
    assert f(f"**Te recomiendo esta:**\n{texto}") == f"*Te recomiendo esta:*\n{texto}"


def test_los_textos_fijos_del_sistema_no_cambian():
    """Si alguno cambiara, la red de seguridad de envios.py avisaría con un warning en cada envío."""
    config = brain.cargar_config_prompts()
    fijos = [v for k, v in config.items() if isinstance(v, str) and "message" in k]
    fijos += [
        brain.obtener_mensaje_error(), brain.obtener_mensaje_fallback(), brain.obtener_mensaje_no_soportado(),
        brain.obtener_mensaje_no_soportado("image"), brain.obtener_mensaje_escalado_por_confianza(),
        brain.obtener_mensaje_derivacion(True), brain.obtener_mensaje_derivacion(False),
        mem.AGRADECIMIENTO_CIERRE_TEXTO_POR_DEFECTO,
    ]
    assert fijos
    for t in fijos:
        assert f(t) == t.strip(), t


# ── brain.generar_respuesta: ambos caminos y el historial ───────────────────

SUCIO = "**Hola Ana**, la terma cuesta **S/ 419.90** 😊\n- **Rheem**: lista\n¿Qué uso le darás?"
LIMPIO = "*Hola Ana*, la terma cuesta *S/ 419.90* 😊\n• *Rheem*: lista\n¿Qué uso le darás?"


def _respuesta_produccion(texto):
    uso = SimpleNamespace(input_tokens=1, output_tokens=1, cache_read_input_tokens=0, cache_creation_input_tokens=0)
    return SimpleNamespace(content=[SimpleNamespace(text=texto)], usage=uso)


def _respuesta_pruebas(texto):
    uso = SimpleNamespace(input_tokens=1, output_tokens=1, cache_read_input_tokens=0)
    bloque = SimpleNamespace(type="tool_use", input={"respuesta": texto, "confianza": "Alta", "razon": "ok"})
    return SimpleNamespace(content=[bloque], usage=uso)


async def test_produccion_devuelve_el_texto_sin_doble_asterisco():
    with patch.object(brain.client.messages, "create", new=AsyncMock(return_value=_respuesta_produccion(SUCIO))):
        texto, error, confianza, _ = await brain.generar_respuesta("Hola", historial=[], modo="produccion")
    assert (texto, error, confianza) == (LIMPIO, False, None)
    assert "**" not in texto
    assert formato_whatsapp.ORIGINAL_ANTES_DE_LIMPIAR.get() == SUCIO   # para las métricas en modo sombra


async def test_pruebas_devuelve_el_texto_sin_doble_asterisco():
    with patch.object(brain.client.messages, "create", new=AsyncMock(return_value=_respuesta_pruebas(SUCIO))):
        texto, error, confianza, razon = await brain.generar_respuesta("Hola", historial=[], modo="pruebas")
    assert (texto, error, confianza, razon) == (LIMPIO, False, "Alta", "ok")


async def test_el_historial_de_gabi_se_limpia_en_memoria_sin_alterar_el_original():
    historial = [
        {"role": "user", "content": "Hola **quiero** una terma"},   # el cliente: no se toca
        {"role": "assistant", "content": SUCIO},
        {"role": "asesor", "content": "Soy **Luis**, te ayudo"},    # el asesor humano: no se toca
        {"role": "assistant", "content": "Listo **gracias**"},
    ]
    copia = [dict(m) for m in historial]
    for modo, fabrica in (("produccion", _respuesta_produccion), ("pruebas", _respuesta_pruebas)):
        with patch.object(brain.client.messages, "create", new=AsyncMock(return_value=fabrica("ok"))) as mock_create:
            await brain.generar_respuesta("Dime", historial=historial, modo=modo)
        enviados = mock_create.await_args.kwargs["messages"]
        assert enviados[0]["content"] == "Hola **quiero** una terma"
        assert enviados[1]["content"] == LIMPIO
        assert enviados[2]["content"] == "Soy **Luis**, te ayudo"
        ultimo = enviados[3]["content"]   # lleva cache_control: es una lista de bloques
        assert ultimo[0]["text"] == "Listo *gracias*"
        assert historial == copia, "la lista original (lo que está en la base) no se debe alterar"


async def test_interruptor_apagado_no_limpia_ni_el_texto_ni_el_historial():
    await mem.guardar_configuracion(formato_whatsapp.CLAVE_INTERRUPTOR, "0")
    historial = [{"role": "assistant", "content": SUCIO}]
    with patch.object(brain.client.messages, "create", new=AsyncMock(return_value=_respuesta_produccion(SUCIO))) as mock_create:
        texto, *_ = await brain.generar_respuesta("Hola", historial=historial, modo="produccion")
    assert texto == SUCIO
    assert mock_create.await_args.kwargs["messages"][0]["content"][0]["text"] == SUCIO


async def test_si_el_limpiador_falla_se_devuelve_el_texto_original():
    with patch.object(formato_whatsapp, "formatear_para_whatsapp", side_effect=RuntimeError("boom")):
        assert await formato_whatsapp.limpiar_salida_gabi(SUCIO) == SUCIO
    with patch.object(formato_whatsapp, "_limpiar", side_effect=RuntimeError("boom")):
        assert f(SUCIO) == SUCIO


async def test_una_respuesta_que_quedaria_vacia_no_se_vacia():
    assert await formato_whatsapp.limpiar_salida_gabi("---") == "---"


# ── Interruptor y caché ──────────────────────────────────────────────────────

async def test_interruptor_por_defecto_encendido_y_cacheado():
    assert await formato_whatsapp.limpieza_activa() is True
    await mem.guardar_configuracion(formato_whatsapp.CLAVE_INTERRUPTOR, "0")
    assert await formato_whatsapp.limpieza_activa() is True    # sigue el valor cacheado (~60 s)
    formato_whatsapp.limpiar_cache()
    assert await formato_whatsapp.limpieza_activa() is False
    await mem.guardar_configuracion(formato_whatsapp.CLAVE_INTERRUPTOR, "1")
    formato_whatsapp.limpiar_cache()
    assert await formato_whatsapp.limpieza_activa() is True


async def test_el_interruptor_no_consulta_la_base_en_cada_mensaje():
    with patch.object(mem, "obtener_configuracion", new=AsyncMock(return_value="1")) as leer:
        for _ in range(5):
            assert await formato_whatsapp.limpieza_activa() is True
    assert leer.await_count == 1


async def test_si_la_base_falla_la_limpieza_queda_encendida():
    with patch.object(mem, "obtener_configuracion", new=AsyncMock(side_effect=RuntimeError("db"))):
        assert await formato_whatsapp.limpieza_activa() is True


# ── Red de seguridad en la capa de envíos ───────────────────────────────────

class _Proveedor:
    def __init__(self):
        self.llamadas = []

    async def enviar_mensaje(self, telefono, mensaje, canal=None, mensaje_id_citado=None):
        self.llamadas.append(("mensaje", mensaje))
        await asyncio.sleep(0)
        return True, "wamid.ok"

    async def enviar_imagen(self, telefono, media_id, caption="", canal=None):
        self.llamadas.append(("imagen", caption))
        return True, "wamid.img"

    async def enviar_documento(self, telefono, media_id, nombre_archivo, caption="", canal=None):
        self.llamadas.append(("documento", caption))
        return True, "wamid.doc"

    async def enviar_audio(self, telefono, media_id, canal=None):
        self.llamadas.append(("audio", media_id))
        return True, "wamid.aud"

    async def enviar_plantilla(self, telefono, nombre, parametros, idioma="es", canal=None):
        self.llamadas.append(("plantilla", parametros))
        return True


async def _canal(codigo):
    n = await mem.crear_negocio(f"Negocio {codigo}", codigo)
    return {"negocio_id": n["id"], "phone_number_id": "111"}


@pytest.mark.parametrize("origen", sorted(envios.ORIGENES_CON_LIMPIEZA_DE_FORMATO))
async def test_los_origenes_de_gabi_se_limpian_y_avisan_con_warning(origen, caplog):
    canal = await _canal("fmt-" + origen[:8])
    await mem.guardar_configuracion_uso_meta(canal["negocio_id"], {"confirmar_riesgo": True, "envios": {"autorecarga": True}})
    p = _Proveedor()
    with caplog.at_level(logging.WARNING, logger="agentkit"):
        await envios.enviar_texto(p, "51911111111", "Hola **Ana**", origen=origen, canal=canal)
    assert p.llamadas == [("mensaje", "Hola *Ana*")]
    assert any("sin limpiar" in r.getMessage() and origen in r.getMessage() for r in caplog.records)


async def test_texto_ya_limpio_pasa_sin_warning(caplog):
    canal = await _canal("fmt-limpio")
    p = _Proveedor()
    with caplog.at_level(logging.WARNING, logger="agentkit"):
        await envios.enviar_texto(p, "51911111112", LIMPIO, origen="gabi_respuesta", canal=canal)
    assert p.llamadas == [("mensaje", LIMPIO)]
    assert not [r for r in caplog.records if "sin limpiar" in r.getMessage()]


async def test_los_mensajes_del_asesor_y_las_plantillas_no_se_tocan_jamas():
    canal = await _canal("fmt-asesor")
    await mem.guardar_configuracion_uso_meta(canal["negocio_id"], {"confirmar_riesgo": True, "envios": {"autorecarga": True}})
    p = _Proveedor()
    await envios.enviar_texto(p, "51911111113", SUCIO, origen="asesor_texto", canal=canal)
    await envios.enviar_imagen(p, "51911111113", "m1", "Pie **negrita**", origen="asesor_archivo", canal=canal)
    await envios.enviar_documento(p, "51911111113", "m2", "a.pdf", "Pie **doc**", origen="asesor_archivo", canal=canal)
    await envios.enviar_audio(p, "51911111113", "m3", origen="asesor_audio", canal=canal)
    await envios.enviar_plantilla(p, "51911111113", "plantilla", ["**Ana**"], origen="asesor_plantilla", canal=canal)
    assert p.llamadas == [
        ("mensaje", SUCIO), ("imagen", "Pie **negrita**"), ("documento", "Pie **doc**"), ("audio", "m3"),
        ("plantilla", ["**Ana**"]),
    ]


def test_ningun_origen_del_asesor_ni_de_plantillas_esta_en_la_lista_de_limpieza():
    en_lista = envios.ORIGENES_CON_LIMPIEZA_DE_FORMATO
    assert en_lista == {
        "gabi_respuesta", "gabi_aviso_derivacion", "gabi_aviso_no_legible", "gabi_respaldo_sin_ia",
        "reenganche_inactividad", "agradecimiento_cierre", "triaje_atc", "gabi_oferta_llamada", "triaje_emergencia_gas",
        "gabi_confirma_llamada", "gabi_calificacion", "gabi_adjunto_derivado",
    }
    assert not [o for o in en_lista if o.startswith("asesor_") or o.startswith("plantilla_")]
    assert en_lista <= set(envios.ORIGENES)


async def test_con_el_interruptor_apagado_la_red_de_seguridad_tampoco_limpia(caplog):
    await mem.guardar_configuracion(formato_whatsapp.CLAVE_INTERRUPTOR, "0")
    canal = await _canal("fmt-off")
    p = _Proveedor()
    with caplog.at_level(logging.WARNING, logger="agentkit"):
        await envios.enviar_texto(p, "51911111114", "Hola **Ana**", origen="gabi_respuesta", canal=canal)
    assert p.llamadas == [("mensaje", "Hola **Ana**")]
    assert not [r for r in caplog.records if "sin limpiar" in r.getMessage()]


async def test_si_la_red_de_seguridad_falla_se_envia_el_texto_original():
    canal = await _canal("fmt-falla")
    p = _Proveedor()
    with patch.object(formato_whatsapp, "formatear_para_whatsapp", side_effect=RuntimeError("boom")):
        await envios.enviar_texto(p, "51911111115", "Hola **Ana**", origen="gabi_respuesta", canal=canal)
    assert p.llamadas == [("mensaje", "Hola **Ana**")]
