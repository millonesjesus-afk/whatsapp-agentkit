# tests/test_calificacion_guiada.py — Calificación guiada con botones (2026-10-23): gas → punto/ductería (UN mensaje) → titular →
# nombre y DNI; camino «sin gas» (Solicita suministro de gas). Apagada por defecto; textos fijos (cero tokens).
import os

os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")
os.environ.setdefault("WHATSAPP_PROVIDER", "meta")
os.environ["DEBOUNCE_RESPUESTA_SEGUNDOS"] = "0"

import pytest

from agent import brain, calificacion_guiada as cg, memory as mem
from tests.test_cierre_cortesia import _correr, _mensajes, _msg, _preparar_webhook
from tests.test_triaje_atc_flujo import _filas, _hablar


# ── Funciones puras ─────────────────────────────────────────────────────────

@pytest.mark.parametrize("textos,esperado", [
    (["Estoy interesado en financiar una Terma"], "terma"), (["quiero un calentador de agua"], "terma"),
    (["Secadora a gas Rinnai"], "secadora"), (["centro de lavado"], "lavado"), (["una lavadora"], "lavado"),
    (["cocina empotrada"], "cocina"), (["Renueva tu cocina ahora"], "cocina"), (["hola"], "otro"), ([None, ""], "otro"),
    (["terma", "secadora"], "terma"),
])
def test_tipo_de_producto(textos, esperado):
    assert cg.tipo_de_producto(*textos) == esperado


@pytest.mark.parametrize("paso", ["gas", "equipo", "titular", "singas"])
@pytest.mark.parametrize("producto", ["terma", "secadora", "lavado", "cocina", "otro"])
def test_todas_las_preguntas_respetan_los_limites_de_whatsapp(paso, producto):
    p = cg.pregunta(paso, producto)
    if p is None:
        assert paso == "equipo" and producto in ("cocina", "otro")
        return
    assert cg.validar_pregunta(p) == []
    assert all(cg.parsear_id(o["id"]) == (paso, o["id"].split(":")[2]) for o in p["opciones"])


def test_punto_y_ducteria_van_en_un_solo_mensaje_de_lista_para_la_terma():
    p = cg.pregunta("equipo", "terma")
    assert p["tipo"] == "lista" and len(p["opciones"]) == 5
    titulos = [o["titulo"] for o in p["opciones"]]
    assert "Punto de gas y ductería" in titulos and "Solo punto de gas" in titulos and "Solo ductería" in titulos
    interactivo = cg.interactivo_de(p)
    assert interactivo["type"] == "list" and len(interactivo["action"]["sections"][0]["rows"]) == 5
    assert cg.pregunta("equipo", "secadora")["tipo"] == "botones" and "secadora" in cg.pregunta("equipo", "secadora")["cuerpo"]
    assert "centro de lavado" in cg.pregunta("equipo", "lavado")["cuerpo"]


def test_el_interactivo_de_botones_tiene_el_formato_de_la_api():
    i = cg.interactivo_de(cg.pregunta("gas"))
    assert i["type"] == "button" and i["body"]["text"] == "¿Tu casa ya tiene gas natural de Cálidda?"
    assert [b["reply"]["id"] for b in i["action"]["buttons"]] == ["cal:gas:si", "cal:gas:no", "cal:gas:ns"]


@pytest.mark.parametrize("valor", ["cal:gas", "gas:si", "cal::si", "cal:gas:", "cal:gas:si:x", "", None])
def test_ids_ajenos_no_se_interpretan(valor):
    assert cg.parsear_id(valor) is None


def test_transiciones():
    def s(paso, valor, prod="terma", nombre=None):
        return cg.siguiente(paso, valor, prod, nombre, "614 9000, opción 5")

    assert s("gas", "si")["pregunta"]["paso"] == "equipo"
    assert s("gas", "si", "cocina")["pregunta"]["paso"] == "titular"
    assert s("gas", "no")["pregunta"]["paso"] == "singas"
    assert "recibo de Cálidda" in s("gas", "ns")["texto"]
    assert s("equipo", "ambos")["pregunta"]["paso"] == "titular"
    t = s("titular", "si")
    assert t["paso_datos"] and "nombre y el DNI del titular" in t["texto"] and "no son una aprobación" in t["texto"]
    conocido = s("titular", "familiar", nombre="carlos ríos")["texto"]
    assert "Perfecto, Carlos" in conocido and "tu nombre" not in conocido
    assert "autorice" in s("titular", "otro")["texto"]
    c = s("singas", "contratar")
    assert c["cerrar_sin_gas"] and "614 9000, opción 5" in c["texto"] and "terma" in c["texto"]
    e = s("singas", "equipo")
    assert not e["cerrar_sin_gas"] and "otros medios de pago" in e["texto"]
    assert s("gas", "otra_cosa") == {"pregunta": None, "texto": None, "paso_datos": False, "cerrar_sin_gas": False}


def test_primera_pregunta_solo_en_los_primeros_mensajes_una_vez_y_sin_dueno():
    lead = {"asesor_asignado": None, "resultado": None, "paso_flujo": None, "cerrado_definitivamente_en": None}
    sin = {"preguntas": [], "respuestas": {}}
    assert cg.lleva_pregunta_de_gas(lead, sin, 1, "activo")
    assert not cg.lleva_pregunta_de_gas(lead, sin, 1, "apagado")
    assert not cg.lleva_pregunta_de_gas(lead, sin, 4, "activo")
    assert not cg.lleva_pregunta_de_gas(lead, {"preguntas": ["gas"], "respuestas": {}}, 1, "activo")
    assert not cg.lleva_pregunta_de_gas({**lead, "asesor_asignado": "x"}, sin, 1, "activo")
    assert not cg.lleva_pregunta_de_gas({**lead, "resultado": "vendido"}, sin, 1, "activo")
    assert not cg.lleva_pregunta_de_gas({**lead, "paso_flujo": "derivado_asesor"}, sin, 1, "activo")
    assert not cg.lleva_pregunta_de_gas(lead, sin, 1, "activo", derivado=True)
    assert not cg.lleva_pregunta_de_gas(None, sin, 1, "activo")


def test_bloque_de_contexto_para_claude():
    assert cg.bloque_contexto({"preguntas": [], "respuestas": {}}, va_la_primera_pregunta=False) is None
    antes = cg.bloque_contexto({"preguntas": [], "respuestas": {}}, va_la_primera_pregunta=True)
    assert "NO hagas ninguna pregunta" in antes and "nombre" in antes
    despues = cg.bloque_contexto(
        {"preguntas": ["gas", "equipo", "titular", "datos"], "respuestas": {"gas": "si", "titular": "si"}}, va_la_primera_pregunta=False,
    )
    assert "sí tiene" in despues and "es el titular" in despues and "No repitas" in despues and "derívalo" in despues


# ── De punta a punta por el webhook ─────────────────────────────────────────

_n = {"c": 0, "w": 0}


async def _escenario(monkeypatch, modo):
    _n["c"] += 1
    codigo = f"cg-{_n['c']}"
    negocio = await mem.crear_negocio(f"Negocio {codigo}", codigo)
    canal = await mem.crear_canal_whatsapp(nombre=f"Canal {codigo}", phone_number_id=f"4098{_n['c']:06d}", negocio_id=negocio["id"])
    if modo is not None:
        await mem.guardar_configuracion(cg.CLAVE_MODO, modo, negocio_id=negocio["id"])
    canal_dict = {"id": canal["id"], "negocio_id": negocio["id"], "unidad_id": None, "phone_number_id": canal["phone_number_id"], "modo": "produccion"}
    proveedor, gabi = _preparar_webhook(monkeypatch, canal_dict, canal, [])
    proveedor.interactivos = []

    async def enviar_interactivo(telefono, interactivo, canal=None):
        proveedor.interactivos.append(interactivo)
        return True, f"wamid.INT{len(proveedor.interactivos)}"
    proveedor.enviar_interactivo = enviar_interactivo
    return negocio, canal, canal_dict, proveedor, gabi


def _tel(n: int) -> str:
    return f"519420{n:05d}"


async def _tocar(proveedor, canal, telefono, id_boton, titulo):
    _n["w"] += 1
    await _correr(proveedor, [_msg(telefono, canal, titulo, f"wamid.cg{_n['w']}", interactivo_id=id_boton)])


async def test_apagada_por_defecto_gabi_responde_igual_y_no_manda_botones(monkeypatch):
    negocio, canal, canal_dict, proveedor, gabi = await _escenario(monkeypatch, None)
    await _hablar(proveedor, canal, _tel(1), "Hola, quiero una terma")
    assert gabi.llamadas == 1 and proveedor.interactivos == []
    assert [e for e in await _filas(_tel(1)) if e.tipo.startswith("calificacion")] == []


async def test_activa_tras_la_respuesta_de_gabi_manda_la_pregunta_de_gas_con_botones(monkeypatch):
    negocio, canal, canal_dict, proveedor, gabi = await _escenario(monkeypatch, "activo")
    await _hablar(proveedor, canal, _tel(2), "Hola, quiero financiar una terma")
    assert gabi.llamadas == 1
    assert len(proveedor.interactivos) == 1 and proveedor.interactivos[0]["type"] == "button"
    assert proveedor.interactivos[0]["body"]["text"] == "¿Tu casa ya tiene gas natural de Cálidda?"
    guardados = [m.content for m in await _mensajes(_tel(2), "assistant")]
    assert guardados[-1].startswith("¿Tu casa ya tiene gas natural de Cálidda?") and "Opciones:" in guardados[-1]
    estado = await mem.obtener_estado_calificacion(_tel(2))
    assert estado["preguntas"] == ["gas"] and estado["respuestas"] == {}
    assert [e for e in await mem.listar_eventos_lead(_tel(2)) if e["tipo"] == "calificacion_pregunta"] == []
    await _hablar(proveedor, canal, _tel(2), "cuánto cuesta?")
    assert len(proveedor.interactivos) == 1


async def test_camino_con_gas_terma_lista_titular_y_pedido_de_datos_sin_llamar_a_claude(monkeypatch):
    negocio, canal, canal_dict, proveedor, gabi = await _escenario(monkeypatch, "activo")
    tel = _tel(3)
    await _hablar(proveedor, canal, tel, "Hola, quiero financiar una terma")
    llamadas = gabi.llamadas

    await _tocar(proveedor, canal, tel, "cal:gas:si", "Sí, ya tengo")
    assert proveedor.interactivos[-1]["type"] == "list" and "terma" in proveedor.interactivos[-1]["body"]["text"]
    await _tocar(proveedor, canal, tel, "cal:equipo:ambos", "Punto de gas y ductería")
    assert proveedor.interactivos[-1]["body"]["text"] == "¿El suministro de gas de esa casa está a tu nombre?"
    await _tocar(proveedor, canal, tel, "cal:titular:si", "Sí, soy el titular")
    pedido = proveedor.enviados[-1]
    assert "nombre y el DNI del titular" in pedido and "no son una aprobación" in pedido

    assert gabi.llamadas == llamadas
    estado = await mem.obtener_estado_calificacion(tel)
    assert estado["respuestas"] == {"gas": "si", "equipo": "ambos", "titular": "si"}
    assert estado["preguntas"] == ["gas", "equipo", "titular", "datos"]
    visibles = [e["descripcion"] for e in await mem.listar_eventos_lead(tel) if e["tipo"] == "calificacion_respuesta"]
    assert any("titular" in d and "es el titular" in d for d in visibles) and len(visibles) == 3
    lead = await mem.obtener_lead(tel, negocio_id=negocio["id"])
    bloques = await brain._armar_bloques_contexto("mi dni es 12345678", [], lead, negocio["id"])
    assert any("sí tiene" in b and "No repitas" in b and "derívalo" in b for b in bloques)


async def test_sin_gas_contratar_da_el_telefono_y_cierra_como_solicita_suministro(monkeypatch):
    negocio, canal, canal_dict, proveedor, gabi = await _escenario(monkeypatch, "activo")
    tel = _tel(4)
    await _hablar(proveedor, canal, tel, "Hola, quiero una terma")
    await _tocar(proveedor, canal, tel, "cal:gas:no", "No tengo aún")
    assert proveedor.interactivos[-1]["body"]["text"] == "Gracias por contarme. ¿Qué prefieres?"
    await _tocar(proveedor, canal, tel, "cal:singas:contratar", "Contratar el gas")
    assert "614 9000, opción 5" in proveedor.enviados[-1]
    lead = await mem.obtener_lead(tel, negocio_id=negocio["id"])
    assert lead["resultado"] == "solicita_suministro_gas" and lead["cerrado_definitivamente_en"] is not None
    assert lead["asesor_asignado"] is None
    cierres = [e for e in await _filas(tel) if e.tipo == "triaje_atc_cerrado"]
    assert len(cierres) == 1 and "Nuevos suministros" in cierres[0].descripcion


async def test_sin_gas_comprar_el_equipo_igual_sigue_sin_cerrar(monkeypatch):
    negocio, canal, canal_dict, proveedor, gabi = await _escenario(monkeypatch, "activo")
    tel = _tel(5)
    await _hablar(proveedor, canal, tel, "Hola, quiero una secadora")
    await _tocar(proveedor, canal, tel, "cal:gas:no", "No tengo aún")
    await _tocar(proveedor, canal, tel, "cal:singas:equipo", "Comprar el equipo")
    assert "otros medios de pago" in proveedor.enviados[-1] and "secadora" in proveedor.enviados[-1]
    lead = await mem.obtener_lead(tel, negocio_id=negocio["id"])
    assert lead["resultado"] is None and lead["cerrado_definitivamente_en"] is None


async def test_apagada_el_toque_de_un_boton_sigue_con_gabi_como_texto(monkeypatch):
    negocio, canal, canal_dict, proveedor, gabi = await _escenario(monkeypatch, "apagado")
    tel = _tel(6)
    await _hablar(proveedor, canal, tel, "Hola")
    llamadas = gabi.llamadas
    await _tocar(proveedor, canal, tel, "cal:gas:si", "Sí, ya tengo")
    assert gabi.llamadas == llamadas + 1 and proveedor.interactivos == []


async def test_si_el_envio_interactivo_falla_no_se_pierde_al_cliente(monkeypatch):
    negocio, canal, canal_dict, proveedor, gabi = await _escenario(monkeypatch, "activo")

    async def falla(telefono, interactivo, canal=None):
        return False, None
    proveedor.enviar_interactivo = falla
    tel = _tel(7)
    await _hablar(proveedor, canal, tel, "Hola, quiero una terma")
    assert gabi.llamadas == 1
    assert (await mem.obtener_estado_calificacion(tel))["preguntas"] == []


def test_el_resultado_nuevo_no_se_puede_elegir_como_resultado_del_triaje():
    assert mem.RESULTADO_SOLICITA_SUMINISTRO in mem.RESULTADOS_CERRADOS
    assert mem.RESULTADO_SOLICITA_SUMINISTRO not in mem.RESULTADOS_TRIAJE_PERMITIDOS
