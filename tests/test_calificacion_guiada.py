# tests/test_calificacion_guiada.py — Calificación guiada con botones (2026-10-23): primer mensaje fijo, gas → punto/ductería →
# titular → tamaño (baños, personas, tipo de cocina) → etapa consultiva con IA; camino «sin gas» (Solicita suministro de gas).
# Apagada por defecto; los pasos son textos fijos (cero tokens).
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
    (["Secadora a gas Rinnai"], "secadora"), (["centro de lavado"], "lavado"), (["una lavasecadora"], "lavado"),
    (["una lavadora"], "otro"),                           # una lavadora sola no es de gas
    (["cocina empotrable"], "cocina"), (["Renueva tu cocina ahora"], "cocina"), (["hola"], "otro"), ([None, ""], "otro"),
    (["terma", "secadora"], "terma"),
])
def test_tipo_de_producto(textos, esperado):
    assert cg.tipo_de_producto(*textos) == esperado


@pytest.mark.parametrize("texto,esperado", [
    ("Estoy interesado en financiar una Terma", True), ("¡Hola! Estoy interesado en financiar una Secadora", True),
    ("¿Cuánto cuesta y cómo lo pago?", True), ("hola", True), ("Buenas tardes", True), ("holaaa", True),
    ("Hola, quiero financiar una terma de 10 litros para mi casa de dos baños", False),
    ("¿Cuánto demora la instalación?", False), ("Me puede informar respecto a secadora?", False), ("", False), (None, False),
])
def test_es_prellenado_o_saludo(texto, esperado):
    assert cg.es_prellenado_o_saludo(texto) is esperado


@pytest.mark.parametrize("texto,esperado", [
    ("¿Cuánto cuesta y cómo lo pago?", True), ("cual es el precio", True), ("en cuántas cuotas", True), ("cuánto sale la terma", True),
    ("Estoy interesado en financiar una Terma", False), ("hola", False), ("y la instalación?", False),
])
def test_pidio_precio(texto, esperado):
    assert cg.pidio_precio(texto) is esperado


@pytest.mark.parametrize("paso", ["producto", "gas", "equipo", "titular", "tamano", "cocina", "complemento", "singas"])
@pytest.mark.parametrize("producto", ["terma", "secadora", "lavado", "cocina", "otro"])
def test_todas_las_preguntas_respetan_los_limites_de_whatsapp(paso, producto):
    p = cg.pregunta(paso, producto)
    if p is None:
        assert (paso == "equipo" and producto in ("cocina", "otro")) or (paso == "tamano" and producto in ("cocina", "otro"))
        return
    assert cg.validar_pregunta(p) == []
    assert all(cg.parsear_id(o["id"]) == (paso, o["id"].split(":")[2]) for o in p["opciones"])


def test_punto_y_ducteria_van_en_un_solo_mensaje_de_lista_para_la_terma():
    p = cg.pregunta("equipo", "terma")
    assert p["tipo"] == "lista" and len(p["opciones"]) == 5
    titulos = [o["titulo"] for o in p["opciones"]]
    assert "Punto de gas y ductería" in titulos and "Solo punto de gas" in titulos and "Solo ductería" in titulos
    assert cg.interactivo_de(p)["type"] == "list"
    assert cg.pregunta("equipo", "secadora")["tipo"] == "botones" and "secadora" in cg.pregunta("equipo", "secadora")["cuerpo"]
    assert "centro de lavado" in cg.pregunta("equipo", "lavado")["cuerpo"]
    assert cg.pregunta("equipo", "cocina") is None                       # la cocina no pregunta punto ni ductería


def test_tamano_por_producto():
    assert [o["titulo"] for o in cg.pregunta("tamano", "terma")["opciones"]] == ["1 baño", "2 baños", "3 o más baños"]
    assert [o["titulo"] for o in cg.pregunta("tamano", "secadora")["opciones"]] == ["Hasta 4 personas", "5 o más personas", "No estoy seguro"]
    assert [o["titulo"] for o in cg.pregunta("cocina")["opciones"]] == ["De pie (con horno)", "Empotrable/encimera"]
    horno = cg.pregunta("complemento")
    assert horno["tipo"] == "lista" and "Con horno empotrable" in [o["titulo"] for o in horno["opciones"]]


def test_el_interactivo_de_botones_tiene_el_formato_de_la_api():
    i = cg.interactivo_de(cg.pregunta("gas"))
    assert i["type"] == "button" and i["body"]["text"] == "¿Tu casa ya tiene gas natural de Cálidda?"
    assert [b["reply"]["id"] for b in i["action"]["buttons"]] == ["cal:gas:si", "cal:gas:no", "cal:gas:ns"]


@pytest.mark.parametrize("valor", ["cal:gas", "gas:si", "cal::si", "cal:gas:", "cal:gas:si:x", "", None])
def test_ids_ajenos_no_se_interpretan(valor):
    assert cg.parsear_id(valor) is None


def test_el_primer_mensaje_fijo_no_habla_de_producto_ni_de_precio():
    p = cg.con_saludo(cg.pregunta("gas"), cg.saludo_para("Estoy interesado en financiar una Terma"))
    assert p["cuerpo"].startswith("Hola 👋 Soy Gabi, asesora virtual de Cálidda Hogar.") and "gas natural de Cálidda" in p["cuerpo"]
    assert "precio" not in p["cuerpo"].lower() and "S/" not in p["cuerpo"] and "terma" not in p["cuerpo"].lower()
    con_precio = cg.con_saludo(cg.pregunta("gas"), cg.saludo_para("¿Cuánto cuesta y cómo lo pago?"))
    assert "El precio te lo cuento en un momento" in con_precio["cuerpo"] and cg.validar_pregunta(con_precio) == []


def test_transiciones():
    def s(paso, valor, prod="terma", nombre=None):
        return cg.siguiente(paso, valor, prod, nombre, "614 9000, opción 5")

    assert s("producto", "terma")["pregunta"]["paso"] == "gas"
    assert "Cuéntame qué gasodoméstico" in s("producto", "otro")["texto"]
    assert s("gas", "si")["pregunta"]["paso"] == "equipo"
    assert s("gas", "si", "cocina")["pregunta"]["paso"] == "titular"
    assert s("gas", "no")["pregunta"]["paso"] == "singas"
    assert "recibo de Cálidda" in s("gas", "ns")["texto"]
    assert s("equipo", "ambos")["pregunta"]["paso"] == "titular"
    assert s("titular", "si")["pregunta"]["paso"] == "tamano" and "baños" in s("titular", "si")["pregunta"]["cuerpo"]
    assert "personas" in s("titular", "familiar", "secadora")["pregunta"]["cuerpo"]
    assert s("titular", "otro", "cocina")["pregunta"]["paso"] == "cocina"
    assert s("titular", "si", "otro")["pregunta"]["paso"] == "dato"
    assert s("tamano", "2")["pregunta"]["paso"] == "dato" and s("tamano", "grande", "secadora")["pregunta"]["paso"] == "dato"
    assert s("cocina", "pie", "cocina")["pregunta"]["paso"] == "dato"
    assert s("cocina", "empotrable", "cocina")["pregunta"]["paso"] == "complemento"
    assert s("complemento", "ambos", "cocina")["pregunta"]["paso"] == "dato"
    # elegir el dato cierra la calificación: sigue la IA
    assert all(s("dato", v)["revisar_etapa"] for v in ("dni", "cliente", "luego")) and not s("dato", "otro")["revisar_etapa"]
    c = s("singas", "contratar")
    assert c["cerrar_sin_gas"] and "614 9000, opción 5" in c["texto"] and "terma" in c["texto"]
    e = s("singas", "equipo")
    assert not e["cerrar_sin_gas"] and "otros medios de pago" in e["texto"]
    vacio = {"pregunta": None, "texto": None, "cerrar_sin_gas": False, "revisar_etapa": False}
    assert s("gas", "otra_cosa") == vacio and s("tamano", "9") == vacio


def test_la_guia_de_tamano_sigue_los_kilos_del_catalogo():
    assert "10 kg" in cg.regla_de_producto("secadora", {}) and "22 a 24 kg" in cg.regla_de_producto("secadora", {})
    lavado = cg.regla_de_producto("lavado", {})
    assert "lavadora con secadora a gas" in lavado and "20 kg" in lavado and "24 kg" in lavado
    assert "17 l/min" in cg.regla_de_producto("terma", {})
    assert "horno empotrable solo va con" in cg.regla_de_producto("cocina", {"cocina": "empotrable"})
    assert "horno empotrable" not in cg.regla_de_producto("cocina", {"cocina": "pie"})


def test_etapa_consultiva_segun_el_producto():
    base = {"gas": "si", "titular": "si", "dato": "dni"}
    assert not cg.etapa_consultiva({"respuestas": base}, "terma")
    assert cg.etapa_consultiva({"respuestas": {**base, "equipo": "ambos", "tamano": "2"}}, "terma")
    assert cg.etapa_consultiva({"respuestas": {**base, "equipo": "punto", "tamano": "pequena"}}, "secadora")
    assert not cg.etapa_consultiva({"respuestas": {**base, "cocina": "empotrable"}}, "cocina")
    assert cg.etapa_consultiva({"respuestas": {**base, "cocina": "empotrable", "complemento": "horno"}}, "cocina")
    assert cg.etapa_consultiva({"respuestas": {**base, "cocina": "pie"}}, "cocina")
    assert cg.etapa_consultiva({"respuestas": base}, "otro")
    assert not cg.etapa_consultiva({"respuestas": {"gas": "no", "titular": "si", "dato": "dni"}}, "otro")
    # sin haber elegido el dato todavía no es la etapa final
    sin_dato = {k: v for k, v in {**base, "equipo": "ambos", "tamano": "2"}.items() if k != "dato"}
    assert not cg.etapa_consultiva({"respuestas": sin_dato}, "terma")


def test_paso_pendiente_y_reintentos():
    estado = {"preguntas": ["gas", "equipo"], "conteo": {"gas": 1, "equipo": 1}, "respuestas": {"gas": "si"}}
    assert cg.pendiente(estado) == "equipo" and cg.puede_retomar(estado) == "equipo"
    estado["conteo"]["equipo"] = 3
    assert cg.pendiente(estado) == "equipo" and cg.puede_retomar(estado) is None      # pregunta original + 2 retomos
    assert cg.pendiente({"preguntas": ["gas"], "conteo": {"gas": 1}, "respuestas": {"gas": "no"}}) is None


def test_primera_pregunta_solo_en_los_primeros_mensajes_una_vez_y_sin_dueno():
    lead = {"asesor_asignado": None, "resultado": None, "paso_flujo": None, "cerrado_definitivamente_en": None}
    sin = {"preguntas": [], "respuestas": {}}
    assert cg.lleva_pregunta_de_gas(lead, sin, 1, "activo")
    assert not cg.lleva_pregunta_de_gas(lead, sin, 1, "apagado")
    assert not cg.lleva_pregunta_de_gas(lead, sin, 4, "activo")
    assert not cg.lleva_pregunta_de_gas(lead, {"preguntas": ["gas"], "respuestas": {}}, 1, "activo")
    assert not cg.lleva_pregunta_de_gas(lead, {"preguntas": ["producto"], "respuestas": {}}, 1, "activo")   # espera la lista de producto
    assert not cg.lleva_pregunta_de_gas({**lead, "asesor_asignado": "x"}, sin, 1, "activo")
    assert not cg.lleva_pregunta_de_gas({**lead, "resultado": "vendido"}, sin, 1, "activo")
    assert not cg.lleva_pregunta_de_gas({**lead, "paso_flujo": "derivado_asesor"}, sin, 1, "activo")
    assert not cg.lleva_pregunta_de_gas(lead, sin, 1, "activo", derivado=True)
    assert not cg.lleva_pregunta_de_gas(None, sin, 1, "activo")


def test_bloque_de_contexto_para_claude():
    vacio = {"preguntas": [], "conteo": {}, "respuestas": {}}
    assert cg.bloque_contexto(vacio, va_la_primera_pregunta=False) is None
    antes = cg.bloque_contexto(vacio, va_la_primera_pregunta=True)
    assert "NO hagas ninguna pregunta" in antes and "No menciones precios" in antes
    con_precio = cg.bloque_contexto(vacio, va_la_primera_pregunta=True, pidio_el_precio=True)
    assert "No menciones precios" not in con_precio
    final = {
        "preguntas": ["gas", "equipo", "titular", "tamano", "dato"], "conteo": {},
        "respuestas": {"gas": "si", "equipo": "ambos", "titular": "si", "tamano": "2", "dato": "dni"},
    }
    sin_precio = cg.bloque_contexto(final, va_la_primera_pregunta=False, tipo_producto="terma")
    assert "ETAPA FINAL" in sin_precio and "2 baños" in sin_precio and "UNA alternativa" in sin_precio
    assert "No menciones precios ni cuotas: el cliente no los pidió" in sin_precio and "pídele ese DNI" in sin_precio
    assert "servicio aparte" not in sin_precio.lower()                      # tiene punto y ductería: nada que ofrecer aparte
    con = cg.bloque_contexto(final, va_la_primera_pregunta=False, tipo_producto="terma", pidio_el_precio=True)
    assert "El cliente pidió el precio: dáselo ahora" in con and "60 cuotas" in con and "36" in con
    assert cg.bloque_contexto(final, va_la_primera_pregunta=False, tipo_producto="terma", derivado=True) is None


def test_la_ia_no_inventa_capacidades_y_el_servicio_que_falta_se_ofrece_aparte():
    estado = {"preguntas": [], "conteo": {}, "respuestas": {"gas": "si", "equipo": "ninguno", "titular": "si", "tamano": "pequena", "dato": "cliente"}}
    b = cg.bloque_contexto(estado, va_la_primera_pregunta=False, tipo_producto="secadora")
    assert "si una descripción no trae la capacidad, no la menciones ni la supongas" in b
    assert "NO cuenta con: punto de gas adicional" in b and "SERVICIO APARTE" in b
    assert "NO des el precio de ese servicio" in b and "salvo que el cliente lo pida explícitamente" in b
    assert "NO es un punto de gas nuevo" in b                               # la «conexión» no resuelve la falta de punto
    assert "número de cliente" in b


def test_servicios_faltantes_por_producto():
    f = cg.servicios_faltantes
    assert f("terma", {"equipo": "ambos"}) == [] and f("terma", {"equipo": "punto"}) == ["ductería"]
    assert f("terma", {"equipo": "ducteria"}) == ["punto de gas adicional"]
    assert f("terma", {"equipo": "ninguno"}) == ["punto de gas adicional", "ductería"]
    assert "a confirmar con el asesor" in f("terma", {"equipo": "ns"})[0]
    assert f("secadora", {"equipo": "punto"}) == [] and f("secadora", {"equipo": "ninguno"}) == ["punto de gas adicional"]
    assert f("lavado", {"equipo": "ninguno"}) == ["punto de gas adicional"]
    assert f("cocina", {"equipo": "ninguno"}) == [] and f("otro", {}) == []         # la cocina no pregunta punto ni ductería


def test_el_dato_que_se_pide_es_el_que_eligio_el_cliente():
    assert "DNI" in cg.regla_del_dato("dni") and "número de cliente" in cg.regla_del_dato("cliente")
    assert "NO se lo vuelvas a pedir" in cg.regla_del_dato("luego")
    assert [o["titulo"] for o in cg.pregunta("dato")["opciones"]] == ["DNI del titular", "Número de cliente", "Más tarde"]
    assert cg.validar_pregunta(cg.pregunta("dato")) == []


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


def _cuerpo(proveedor) -> str:
    return proveedor.interactivos[-1]["body"]["text"]


async def test_apagada_por_defecto_gabi_responde_igual_y_no_manda_botones(monkeypatch):
    negocio, canal, canal_dict, proveedor, gabi = await _escenario(monkeypatch, None)
    await _hablar(proveedor, canal, _tel(1), "Estoy interesado en financiar una Terma")
    assert gabi.llamadas == 1 and proveedor.interactivos == []
    assert [e for e in await _filas(_tel(1)) if e.tipo.startswith("calificacion")] == []


async def test_texto_prellenado_recibe_el_primer_mensaje_fijo_sin_ia_ni_producto_ni_precio(monkeypatch):
    negocio, canal, canal_dict, proveedor, gabi = await _escenario(monkeypatch, "activo")
    tel = _tel(2)
    await _hablar(proveedor, canal, tel, "Estoy interesado en financiar una Terma")
    assert gabi.llamadas == 0 and proveedor.enviados == []             # ni IA ni texto suelto: UNA sola burbuja con botones
    assert len(proveedor.interactivos) == 1 and proveedor.interactivos[0]["type"] == "button"
    cuerpo = _cuerpo(proveedor)
    assert cuerpo.startswith("Hola 👋 Soy Gabi") and cuerpo.endswith("¿Tu casa ya tiene gas natural de Cálidda?")
    assert "terma" not in cuerpo.lower() and "S/" not in cuerpo
    guardados = [m.content for m in await _mensajes(tel, "assistant")]
    assert len(guardados) == 1 and "Opciones:" in guardados[0]
    lead = await mem.obtener_lead(tel, negocio_id=negocio["id"])
    assert lead["interes"] == "terma"                                  # el asesor y el reparto ya saben el producto
    estado = await mem.obtener_estado_calificacion(tel)
    assert estado["preguntas"] == ["gas"] and estado["conteo"] == {"gas": 1}


async def test_precio_prellenado_promete_el_precio_despues_de_las_consultas(monkeypatch):
    negocio, canal, canal_dict, proveedor, gabi = await _escenario(monkeypatch, "activo")
    tel = _tel(3)
    await _hablar(proveedor, canal, tel, "Estoy interesado en financiar una Secadora")
    assert gabi.llamadas == 0 and "precio" not in _cuerpo(proveedor).lower()
    tel2 = _tel(33)
    await _hablar(proveedor, canal, tel2, "¿Cuánto cuesta y cómo lo pago?")
    # sin campaña ni anuncio ni producto en el mensaje → antes sale la lista de producto, con la promesa del precio
    assert proveedor.interactivos[-1]["type"] == "list" and "El precio te lo cuento en un momento" in _cuerpo(proveedor)
    assert _cuerpo(proveedor).endswith("¿Qué gasodoméstico te interesa?") and gabi.llamadas == 0
    await _tocar(proveedor, canal, tel2, "cal:producto:terma", "Terma a gas")
    assert _cuerpo(proveedor) == "¿Tu casa ya tiene gas natural de Cálidda?"
    assert (await mem.obtener_lead(tel2, negocio_id=negocio["id"]))["interes"] == "terma"
    assert gabi.llamadas == 0


async def test_una_pregunta_real_la_responde_la_ia_y_despues_viene_la_pregunta_de_gas(monkeypatch):
    negocio, canal, canal_dict, proveedor, gabi = await _escenario(monkeypatch, "activo")
    tel = _tel(4)
    await _hablar(proveedor, canal, tel, "Hola, quiero financiar una terma para mi casa de dos baños")
    assert gabi.llamadas == 1
    assert len(proveedor.interactivos) == 1 and _cuerpo(proveedor) == "¿Tu casa ya tiene gas natural de Cálidda?"
    # la pregunta es interna: no sale en el Timeline
    assert [e for e in await mem.listar_eventos_lead(tel) if e["tipo"] == "calificacion_pregunta"] == []


async def test_si_el_cliente_escribe_en_vez_de_tocar_la_ia_responde_y_se_retoma_hasta_2_veces(monkeypatch):
    negocio, canal, canal_dict, proveedor, gabi = await _escenario(monkeypatch, "activo")
    tel = _tel(5)
    await _hablar(proveedor, canal, tel, "Estoy interesado en financiar una Terma")
    assert len(proveedor.interactivos) == 1
    await _hablar(proveedor, canal, tel, "cuánto demora la instalación?")
    assert gabi.llamadas == 1 and len(proveedor.interactivos) == 2         # Claude contestó y se retomó la pregunta
    await _hablar(proveedor, canal, tel, "y la garantía?")
    assert gabi.llamadas == 2 and len(proveedor.interactivos) == 3
    await _hablar(proveedor, canal, tel, "y si no tengo el recibo?")
    assert gabi.llamadas == 3 and len(proveedor.interactivos) == 3         # ya no insiste: pregunta original + 2 retomos
    assert (await mem.obtener_estado_calificacion(tel))["conteo"] == {"gas": 3}


async def test_camino_con_gas_terma_hasta_la_etapa_consultiva(monkeypatch):
    negocio, canal, canal_dict, proveedor, gabi = await _escenario(monkeypatch, "activo")
    tel = _tel(6)
    await _hablar(proveedor, canal, tel, "Estoy interesado en financiar una Terma")
    assert gabi.llamadas == 0

    await _tocar(proveedor, canal, tel, "cal:gas:si", "Sí, ya tengo")
    assert proveedor.interactivos[-1]["type"] == "list" and "terma" in _cuerpo(proveedor)
    await _tocar(proveedor, canal, tel, "cal:equipo:ambos", "Punto de gas y ductería")
    assert _cuerpo(proveedor) == "¿El suministro de gas de esa casa está a tu nombre?"
    await _tocar(proveedor, canal, tel, "cal:titular:si", "Sí, soy el titular")
    assert "cuántos baños" in _cuerpo(proveedor) and gabi.llamadas == 0     # hasta acá ningún paso llamó a Claude: cero tokens

    await _tocar(proveedor, canal, tel, "cal:tamano:2", "2 baños")
    assert "un dato del titular" in _cuerpo(proveedor) and gabi.llamadas == 0   # el cliente elige qué dato pasa
    await _tocar(proveedor, canal, tel, "cal:dato:dni", "DNI del titular")     # la última respuesta completa la calificación
    assert gabi.llamadas == 1                                               # recién ahora habla la IA (etapa consultiva)
    estado = await mem.obtener_estado_calificacion(tel)
    assert estado["respuestas"] == {"gas": "si", "equipo": "ambos", "titular": "si", "tamano": "2", "dato": "dni"}
    visibles = [e["descripcion"] for e in await mem.listar_eventos_lead(tel) if e["tipo"] == "calificacion_respuesta"]
    assert len(visibles) == 5 and any("2 baños" in d for d in visibles)

    lead = await mem.obtener_lead(tel, negocio_id=negocio["id"])
    historial = [{"role": "user", "content": "Estoy interesado en financiar una Terma"}]
    bloques = await brain._armar_bloques_contexto("2 baños", historial, lead, negocio["id"])
    final = [b for b in bloques if "ETAPA FINAL" in b]
    assert final and "No menciones precios ni cuotas: el cliente no los pidió" in final[0] and "2 baños" in final[0]
    # cliente que SÍ pidió el precio (aunque sea con el texto prellenado): la IA se lo da en esta etapa
    # (el contexto lee los mensajes guardados de ESTA conversación, no el historial que se le pase)
    await mem.guardar_mensaje(tel, "user", "¿Cuánto cuesta y cómo lo pago?", negocio_id=negocio["id"])
    await mem.guardar_mensaje(tel, "user", "2 baños", negocio_id=negocio["id"])
    bloques = await brain._armar_bloques_contexto("2 baños", [], lead, negocio["id"])
    assert any("El cliente pidió el precio: dáselo ahora" in b for b in bloques)


async def test_secadora_pregunta_solo_el_punto_y_el_tamano_por_personas(monkeypatch):
    negocio, canal, canal_dict, proveedor, gabi = await _escenario(monkeypatch, "activo")
    tel = _tel(7)
    await _hablar(proveedor, canal, tel, "Estoy interesado en financiar una Secadora")
    await _tocar(proveedor, canal, tel, "cal:gas:si", "Sí, ya tengo")
    assert "punto de gas" in _cuerpo(proveedor) and "secadora" in _cuerpo(proveedor)
    await _tocar(proveedor, canal, tel, "cal:equipo:punto", "Sí, ya tengo punto")
    await _tocar(proveedor, canal, tel, "cal:titular:familiar", "Es de un familiar")
    assert "cuántas personas" in _cuerpo(proveedor)
    await _tocar(proveedor, canal, tel, "cal:tamano:grande", "5 o más personas")
    assert gabi.llamadas == 0
    await _tocar(proveedor, canal, tel, "cal:dato:cliente", "Número de cliente")
    assert gabi.llamadas == 1


async def test_cocina_no_pregunta_punto_y_pide_tipo_y_complemento(monkeypatch):
    negocio, canal, canal_dict, proveedor, gabi = await _escenario(monkeypatch, "activo")
    tel = _tel(8)
    await _hablar(proveedor, canal, tel, "Estoy interesado en financiar una Cocina")
    await _tocar(proveedor, canal, tel, "cal:gas:si", "Sí, ya tengo")
    assert _cuerpo(proveedor) == "¿El suministro de gas de esa casa está a tu nombre?"        # sin punto ni ductería
    await _tocar(proveedor, canal, tel, "cal:titular:si", "Sí, soy el titular")
    assert _cuerpo(proveedor) == "¿Qué tipo de cocina buscas?"
    await _tocar(proveedor, canal, tel, "cal:cocina:empotrable", "Empotrable/encimera")
    assert proveedor.interactivos[-1]["type"] == "list" and "encimera" in _cuerpo(proveedor)
    assert gabi.llamadas == 0
    await _tocar(proveedor, canal, tel, "cal:complemento:horno", "Con horno empotrable")
    assert gabi.llamadas == 0
    await _tocar(proveedor, canal, tel, "cal:dato:luego", "Más tarde")
    assert gabi.llamadas == 1


async def test_cocina_de_pie_pasa_directo_a_la_etapa_consultiva(monkeypatch):
    negocio, canal, canal_dict, proveedor, gabi = await _escenario(monkeypatch, "activo")
    tel = _tel(9)
    await _hablar(proveedor, canal, tel, "Estoy interesado en financiar una Cocina")
    await _tocar(proveedor, canal, tel, "cal:gas:si", "Sí, ya tengo")
    await _tocar(proveedor, canal, tel, "cal:titular:si", "Sí, soy el titular")
    await _tocar(proveedor, canal, tel, "cal:cocina:pie", "De pie (con horno)")
    assert gabi.llamadas == 0
    await _tocar(proveedor, canal, tel, "cal:dato:dni", "DNI del titular")
    assert gabi.llamadas == 1


async def test_sin_gas_contratar_da_el_telefono_y_cierra_como_solicita_suministro(monkeypatch):
    negocio, canal, canal_dict, proveedor, gabi = await _escenario(monkeypatch, "activo")
    tel = _tel(10)
    await _hablar(proveedor, canal, tel, "Estoy interesado en financiar una Terma")
    await _tocar(proveedor, canal, tel, "cal:gas:no", "No tengo aún")
    assert _cuerpo(proveedor) == "Gracias por contarme. ¿Qué prefieres?"
    await _tocar(proveedor, canal, tel, "cal:singas:contratar", "Contratar el gas")
    assert "614 9000, opción 5" in proveedor.enviados[-1]
    lead = await mem.obtener_lead(tel, negocio_id=negocio["id"])
    assert lead["resultado"] == "solicita_suministro_gas" and lead["cerrado_definitivamente_en"] is not None
    assert lead["asesor_asignado"] is None and gabi.llamadas == 0
    cierres = [e for e in await _filas(tel) if e.tipo == "triaje_atc_cerrado"]
    assert len(cierres) == 1 and "Nuevos suministros" in cierres[0].descripcion


async def test_sin_gas_comprar_el_equipo_igual_sigue_sin_cerrar(monkeypatch):
    negocio, canal, canal_dict, proveedor, gabi = await _escenario(monkeypatch, "activo")
    tel = _tel(11)
    await _hablar(proveedor, canal, tel, "Estoy interesado en financiar una Secadora")
    await _tocar(proveedor, canal, tel, "cal:gas:no", "No tengo aún")
    await _tocar(proveedor, canal, tel, "cal:singas:equipo", "Comprar el equipo")
    assert "otros medios de pago" in proveedor.enviados[-1] and "secadora" in proveedor.enviados[-1]
    lead = await mem.obtener_lead(tel, negocio_id=negocio["id"])
    assert lead["resultado"] is None and lead["cerrado_definitivamente_en"] is None


async def test_apagada_el_toque_de_un_boton_sigue_con_gabi_como_texto(monkeypatch):
    negocio, canal, canal_dict, proveedor, gabi = await _escenario(monkeypatch, "apagado")
    tel = _tel(12)
    await _hablar(proveedor, canal, tel, "Hola")
    llamadas = gabi.llamadas
    await _tocar(proveedor, canal, tel, "cal:gas:si", "Sí, ya tengo")
    assert gabi.llamadas == llamadas + 1 and proveedor.interactivos == []


async def test_si_el_envio_interactivo_falla_no_se_pierde_al_cliente(monkeypatch):
    negocio, canal, canal_dict, proveedor, gabi = await _escenario(monkeypatch, "activo")

    async def falla(telefono, interactivo, canal=None):
        return False, None
    proveedor.enviar_interactivo = falla
    tel = _tel(13)
    await _hablar(proveedor, canal, tel, "Estoy interesado en financiar una Terma")
    assert gabi.llamadas == 1                                           # el primer mensaje fijo no salió: responde Gabi
    assert (await mem.obtener_estado_calificacion(tel))["preguntas"] == []


async def test_con_asesor_asignado_no_se_manda_nada_fijo(monkeypatch):
    negocio, canal, canal_dict, proveedor, gabi = await _escenario(monkeypatch, "activo")
    tel = _tel(14)
    await _hablar(proveedor, canal, tel, "Hola, tengo una duda sobre mi terma")
    interactivos = len(proveedor.interactivos)
    await mem.actualizar_lead(tel, asesor_asignado=None, pausado_manual=True)
    await _tocar(proveedor, canal, tel, "cal:gas:si", "Sí, ya tengo")
    assert len(proveedor.interactivos) == interactivos


def test_el_resultado_nuevo_no_se_puede_elegir_como_resultado_del_triaje():
    assert mem.RESULTADO_SOLICITA_SUMINISTRO in mem.RESULTADOS_CERRADOS
    assert mem.RESULTADO_SOLICITA_SUMINISTRO not in mem.RESULTADOS_TRIAJE_PERMITIDOS


# ── El primer mensaje lee la campaña y el anuncio (no solo el saludo) ───────

def _referral(source_id: str, titulo: str, cuerpo: str = "Escríbenos y te contamos") -> dict:
    return {"source_id": source_id, "headline": titulo, "body": cuerpo, "source_url": "https://fb.me/x", "source_type": "ad"}


async def _entrar(monkeypatch, tel, texto, referral, campana=None):
    negocio, canal, canal_dict, proveedor, gabi = await _escenario(monkeypatch, "activo")
    if campana:
        await mem.crear_campana_de_anuncio(campana["nombre"], referral["source_id"], negocio["id"], **campana.get("extra", {}))
    _n["w"] += 1
    await _correr(proveedor, [_msg(tel, canal, texto, f"wamid.cgr{_n['w']}", referral=referral)])
    return negocio, proveedor, gabi


async def test_campana_generica_por_tipo_sin_producto_ni_precio_salta_la_lista_de_producto(monkeypatch):
    # el cliente solo dice «Hola»: el tipo (terma) sale del nombre de la campaña, aunque no traiga producto ni precio
    negocio, proveedor, gabi = await _entrar(
        monkeypatch, _tel(20), "Hola", _referral("AD-CG1", "Mejora tu baño"), campana={"nombre": "Meta Terma Octubre"},
    )
    assert gabi.llamadas == 0 and _cuerpo(proveedor).endswith("¿Tu casa ya tiene gas natural de Cálidda?")
    assert (await mem.obtener_lead(_tel(20), negocio_id=negocio["id"]))["interes"] == "terma"


async def test_campana_con_producto_y_precio_tampoco_los_menciona_en_el_primer_mensaje(monkeypatch):
    negocio, proveedor, gabi = await _entrar(
        monkeypatch, _tel(21), "Estoy interesado en financiar", _referral("AD-CG2", "Llévate la tuya"),
        campana={"nombre": "Oferta del mes", "extra": {"producto_promocional": "Secadora a gas Rinnai 10 Kg", "precio_promocional": "2999"}},
    )
    assert gabi.llamadas == 0
    cuerpo = _cuerpo(proveedor)
    assert cuerpo.endswith("¿Tu casa ya tiene gas natural de Cálidda?") and "2999" not in cuerpo and "Rinnai" not in cuerpo
    assert (await mem.obtener_lead(_tel(21), negocio_id=negocio["id"]))["interes"] == "secadora"
    # y al llegar a la etapa de equipo sabe que es una secadora (solo punto de gas, sin ductería)
    await _tocar(proveedor, proveedor_canal(proveedor), _tel(21), "cal:gas:si", "Sí, ya tengo")
    assert "secadora" in _cuerpo(proveedor) and "ductería" not in _cuerpo(proveedor)


def proveedor_canal(proveedor):
    return proveedor._canal


async def test_anuncio_sin_campana_se_entiende_por_su_titulo(monkeypatch):
    negocio, proveedor, gabi = await _entrar(monkeypatch, _tel(22), "Buenas tardes", _referral("AD-CG3", "Renueva tu cocina ahora"))
    assert gabi.llamadas == 0 and _cuerpo(proveedor).endswith("¿Tu casa ya tiene gas natural de Cálidda?")
    assert (await mem.obtener_lead(_tel(22), negocio_id=negocio["id"]))["interes"] == "cocina"


async def test_anuncio_sin_pistas_ni_campana_pregunta_el_producto_con_la_lista(monkeypatch):
    negocio, proveedor, gabi = await _entrar(monkeypatch, _tel(23), "Hola", _referral("AD-CG4", "Financia tu artefacto"))
    assert gabi.llamadas == 0 and proveedor.interactivos[-1]["type"] == "list"
    assert _cuerpo(proveedor).endswith("¿Qué gasodoméstico te interesa?")
