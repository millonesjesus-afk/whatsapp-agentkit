# tests/test_retiro_datos.py — Pedido de retiro de datos / «no me escriban más» (2026-11-11, agent/retiro_datos.py): texto fijo sin IA y el caso pasa a
# supervisión. Apagado por defecto (camino de Gabi IDÉNTICO), sombra (solo evento interno), activo (envía, pausa a Gabi, deja el evento visible).
# Precisión > recall: «no me llamen» y las negaciones NO disparan. Datos sintéticos únicamente.

import os

os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")
os.environ.setdefault("WHATSAPP_PROVIDER", "meta")
os.environ["DEBOUNCE_RESPUESTA_SEGUNDOS"] = "0"

import pytest

from agent import envios
from agent import memory as mem
from agent import retiro_datos as r
from tests.test_triaje_atc_flujo import _escenario, _filas, _hablar

TEXTO = r.TEXTO_POR_DEFECTO
ACTIVO = {r.CLAVE_MODO: "activo"}


# ── Detección ────────────────────────────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("texto", [
    "Entonces puedes quitar mi número de su base de datos, para que no me escriban por favor",
    "quita mi número", "Quiten mi número por favor", "borren mis datos", "elimina mi contacto", "retiren mi número de su lista",
    "no me escriban más", "no me escribas más", "No me molesten", "no me contacten", "dejen de escribirme", "deja de molestar",
    "sáquenme de su base de datos", "no quiero recibir más mensajes", "no quiero que me escriban", "no quiero publicidad",
])
def test_pedidos_de_retiro_se_detectan(texto):
    assert r.detectar([texto]), texto


@pytest.mark.parametrize("texto", [
    "hola", "quiero una terma a gas", "cuánto cuesta?", "no me llamen, escríbanme por aquí", "prefiero que no me llamen",
    "no quiero que me quiten mis datos", "no me quiten mi número", "mi número es 987654321", "gracias, ok", "no me interesa",
    "no me llegó el mensaje", "puedo cambiar mi número de contacto?", "¿necesitan mis datos?", "quiero que me escriban mañana",
])
def test_lo_demas_no_dispara(texto):
    assert not r.detectar([texto]), texto


def test_mira_cada_mensaje_y_no_mezcla():
    assert r.detectar(["Hola", "no me escriban más", "gracias"])
    assert not r.detectar(["Hola", "gracias", "ok"]) and not r.detectar([])


def test_el_texto_no_promete_lo_que_no_existe():
    t = TEXTO.lower()
    assert "no te escribiremos" not in t and "asesor" in t and "614" not in t       # sin teléfonos inventados, sin promesas vacías


# ── Camino de punta a punta por el webhook ─────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("modo", [None, "apagado", "xyz", ""])
async def test_apagado_o_invalido_el_camino_de_gabi_es_identico(monkeypatch, modo):
    telefono = f"519430{len(str(modo)):05d}"
    extra = {r.CLAVE_MODO: modo} if modo is not None else None
    negocio, canal, canal_dict, proveedor, gabi = await _escenario(monkeypatch, None, extra=extra)
    await _hablar(proveedor, canal, telefono, "Hola", "quita mi número de su base de datos")
    assert gabi.llamadas == 2 and TEXTO not in proveedor.enviados
    assert await _filas(telefono, mem.EVENTO_RETIRO_DATOS) == [] and await _filas(telefono, mem.EVENTO_RETIRO_DATOS_SOMBRA) == []


async def test_activo_envia_el_texto_fijo_sin_ia_y_pasa_a_supervision(monkeypatch):
    telefono = "51943100001"
    negocio, canal, canal_dict, proveedor, gabi = await _escenario(monkeypatch, None, extra=ACTIVO)
    await _hablar(proveedor, canal, telefono, "Hola")
    assert gabi.llamadas == 1
    await _hablar(proveedor, canal, telefono, "Entonces puedes quitar mi número de su base de datos, para que no me escriban")
    assert gabi.llamadas == 1                                      # este turno NO llamó a la IA
    assert proveedor.enviados[-1] == TEXTO
    lead = await mem.obtener_lead(telefono, negocio_id=negocio["id"])
    assert lead["pausado_manual"] and lead["escalado_supervision_en"] is not None   # Gabi pausada y a la cola de supervisión
    eventos = await _filas(telefono, mem.EVENTO_RETIRO_DATOS)
    assert len(eventos) == 1 and eventos[0].payload["escalado"] is True
    assert mem.EVENTO_RETIRO_DATOS not in mem.TIPOS_EVENTO_INTERNOS             # visible en el Timeline


async def test_activo_no_repite_ni_vuelve_a_llamar_a_la_ia_porque_el_caso_ya_esta_pausado(monkeypatch):
    telefono = "51943100002"
    negocio, canal, canal_dict, proveedor, gabi = await _escenario(monkeypatch, None, extra=ACTIVO)
    await _hablar(proveedor, canal, telefono, "Hola", "no me escriban más", "por favor no me escriban")
    assert proveedor.enviados.count(TEXTO) == 1 and gabi.llamadas == 1
    assert len(await _filas(telefono, mem.EVENTO_RETIRO_DATOS)) == 1


async def test_activo_con_un_mensaje_normal_responde_gabi(monkeypatch):
    telefono = "51943100003"
    negocio, canal, canal_dict, proveedor, gabi = await _escenario(monkeypatch, None, extra=ACTIVO)
    await _hablar(proveedor, canal, telefono, "Hola", "no me llamen, escríbanme por aquí")
    assert gabi.llamadas == 2 and TEXTO not in proveedor.enviados
    assert await _filas(telefono, mem.EVENTO_RETIRO_DATOS) == []


async def test_sombra_solo_deja_un_evento_interno_y_gabi_responde(monkeypatch):
    telefono = "51943100004"
    negocio, canal, canal_dict, proveedor, gabi = await _escenario(monkeypatch, None, extra={r.CLAVE_MODO: "sombra"})
    await _hablar(proveedor, canal, telefono, "Hola", "quita mi número de su base de datos")
    assert gabi.llamadas == 2 and TEXTO not in proveedor.enviados
    assert len(await _filas(telefono, mem.EVENTO_RETIRO_DATOS_SOMBRA)) == 1 and await _filas(telefono, mem.EVENTO_RETIRO_DATOS) == []
    assert mem.EVENTO_RETIRO_DATOS_SOMBRA in mem.TIPOS_EVENTO_INTERNOS
    lead = await mem.obtener_lead(telefono, negocio_id=negocio["id"])
    assert not lead["pausado_manual"]


async def test_si_el_envio_falla_no_se_toca_nada_y_sigue_gabi(monkeypatch):
    telefono = "51943100005"
    negocio, canal, canal_dict, proveedor, gabi = await _escenario(monkeypatch, None, extra=ACTIVO)
    await _hablar(proveedor, canal, telefono, "Hola")
    original = envios.enviar_texto

    async def falla(prov, tel, texto, **kw):
        if kw.get("origen") == "retiro_datos":
            return envios.ResultadoEnvio(False, None, motivo="falla de prueba")
        return await original(prov, tel, texto, **kw)

    monkeypatch.setattr(envios, "enviar_texto", falla)
    await _hablar(proveedor, canal, telefono, "borren mis datos")
    assert gabi.llamadas == 2 and TEXTO not in proveedor.enviados
    lead = await mem.obtener_lead(telefono, negocio_id=negocio["id"])
    assert not lead["pausado_manual"] and await _filas(telefono, mem.EVENTO_RETIRO_DATOS) == []


async def test_un_lead_en_gestion_no_es_de_este_modulo(monkeypatch):
    telefono = "51943100006"
    negocio, canal, canal_dict, proveedor, gabi = await _escenario(monkeypatch, None, extra=ACTIVO)
    await _hablar(proveedor, canal, telefono, "Hola")
    for lead in ({"asesor_asignado": "ana"}, {"pausado_manual": True}, {"escalado_supervision_en": "2026-11-11"}, {"resultado": "agendado"}):
        assert await r.procesar(telefono, canal_dict, lead, proveedor) is False


async def test_texto_configurable_por_negocio(monkeypatch):
    telefono = "51943100007"
    propio = "Listo, un asesor se encarga de tu pedido."
    negocio, canal, canal_dict, proveedor, gabi = await _escenario(monkeypatch, None, extra={**ACTIVO, r.CLAVE_TEXTO: propio})
    await _hablar(proveedor, canal, telefono, "Hola", "no me escriban más")
    assert proveedor.enviados[-1] == propio


async def test_el_origen_esta_registrado_como_esencial():
    assert envios.ORIGENES["retiro_datos"]["esencial"] is True and "retiro_datos" in envios.ORIGENES_CON_LIMPIEZA_DE_FORMATO
