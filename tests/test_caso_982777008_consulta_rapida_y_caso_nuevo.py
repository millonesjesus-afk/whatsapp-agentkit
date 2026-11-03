# tests/test_caso_982777008_consulta_rapida_y_caso_nuevo.py — Dos errores del caso real +51 982 777 008 (2026-11-02).
#
# 1. Gabi terminó su respuesta con «Te hago una consulta rápida para orientarte mejor.» y la pregunta nunca llegó (el caso quedó derivado):
#    la promesa quedó en el aire. Ahora la frase la pone el SISTEMA, pegada a la pregunta: si la pregunta no sale, la frase tampoco.
# 2. El cliente volvió con un caso nuevo («cobro excesivo de recibo») tras un cierre definitivo, pero el lead arrastraba `derivado_asesor`
#    del caso anterior: el triaje ATC lo bloqueó (`paso_flujo_derivado_asesor`) y el caso nuevo no se cerró como consulta ATC.
import os

os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")
os.environ.setdefault("WHATSAPP_PROVIDER", "meta")
os.environ["DEBOUNCE_RESPUESTA_SEGUNDOS"] = "0"

from agent import calificacion_guiada as cg, memory as mem, triaje_atc as t
from tests.test_calificacion_guiada import _cuerpo, _escenario, _hablar, _tel
from tests.test_cierre_cortesia import _caso_cerrado, _correr, _eventos, _msg, _preparar_webhook


async def test_la_frase_de_consulta_rapida_sale_junto_con_la_pregunta_y_no_en_el_texto_de_la_ia(monkeypatch):
    negocio, canal, canal_dict, proveedor, gabi = await _escenario(monkeypatch, "activo")
    tel = _tel(70)
    await _hablar(proveedor, canal, tel, "A donde puedo llamar")
    assert gabi.llamadas == 1
    assert "consulta rápida" not in proveedor.enviados[-1].lower()                 # la IA ya no anuncia nada
    assert _cuerpo(proveedor).startswith(cg.FRASE_CONSULTA_RAPIDA) and _cuerpo(proveedor).endswith("¿Qué gasodoméstico te interesa?")   # sin producto conocido sale la lista


async def test_si_el_caso_ya_esta_derivado_no_hay_ni_pregunta_ni_frase_colgada(monkeypatch):
    negocio, canal, canal_dict, proveedor, gabi = await _escenario(monkeypatch, "activo")
    tel = _tel(71)
    await mem.actualizar_lead(tel, negocio_id=negocio["id"], numero_whatsapp_id=canal["phone_number_id"], paso_flujo="derivado_asesor")
    await _hablar(proveedor, canal, tel, "A donde puedo llamar")
    assert proveedor.interactivos == []
    assert not any("consulta rápida" in texto.lower() for texto in proveedor.enviados)


async def test_el_reintento_no_repite_la_frase(monkeypatch):
    negocio, canal, canal_dict, proveedor, gabi = await _escenario(monkeypatch, "activo")
    tel = _tel(72)
    await _hablar(proveedor, canal, tel, "Estoy interesado en financiar una Terma")
    await _hablar(proveedor, canal, tel, "cuánto demora la instalación?")
    assert len(proveedor.interactivos) == 2 and _cuerpo(proveedor) == "¿Tu casa ya tiene gas natural de Cálidda?"


async def test_un_caso_nuevo_tras_un_cierre_definitivo_no_hereda_derivado_asesor_y_el_triaje_lo_cierra(monkeypatch):
    telefono = "51982777008"
    negocio, canal, canal_dict, conv = await _caso_cerrado("g-982", telefono, resultado="sin_respuesta")
    await mem.actualizar_lead(telefono, negocio_id=negocio["id"], paso_flujo="derivado_asesor")
    await mem.guardar_configuracion(t.CLAVE_MODO, "activo", negocio_id=negocio["id"])
    await mem.guardar_configuracion(t.CLAVE_LINEA, "614-9000 opción 5", negocio_id=negocio["id"])
    proveedor, gabi = _preparar_webhook(monkeypatch, canal_dict, canal, [])

    await _correr(proveedor, [_msg(telefono, canal, "Buenas ya tengo mi solicitud por cobro excesivo de recibo", "wamid.g982-1")])

    [reabierto] = await _eventos(telefono, "reabierto_por_cliente")
    assert reabierto["payload"]["paso_flujo_anterior"] == "derivado_asesor"
    assert gabi.llamadas == 0 and "614-9000 opción 5" in proveedor.enviados[-1]    # lo atendió el triaje, sin IA
    lead = await mem.obtener_lead(telefono, negocio_id=negocio["id"])
    assert lead["resultado"] == "consulta_atc" and lead["cerrado_definitivamente_en"] is not None
    assert lead["paso_flujo"] != "derivado_asesor" and lead["asesor_asignado"] is None
