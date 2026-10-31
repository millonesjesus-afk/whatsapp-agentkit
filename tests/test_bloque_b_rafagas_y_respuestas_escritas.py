# tests/test_bloque_b_rafagas_y_respuestas_escritas.py — Bloque B de la auditoría del flujo guiado (2026-10-30).
#
# Casos reales (cohorte desde el 25-oct): el cliente toca dos botones seguidos y recibe dos respuestas; toca «Número de cliente» y
# enseguida «Más tarde» y Gabi igual le pide el número; escribe «a nombre de mi esposo» y Gabi le repite la misma pregunta con la
# muletilla «Te hago una consulta rápida». Ahora: una ráfaga recibe UNA respuesta según el estado final, un segundo toque en la misma
# pregunta dentro de unos segundos es una corrección, y las respuestas escritas claras se entienden sin IA.
import os

os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")
os.environ.setdefault("WHATSAPP_PROVIDER", "meta")
os.environ["DEBOUNCE_RESPUESTA_SEGUNDOS"] = "0"

import pytest

from agent import brain, calificacion_guiada as cg, memory as mem
from tests.test_calificacion_guiada import _cuerpo, _escenario, _hablar, _tel, _tocar
from tests.test_cierre_cortesia import _correr, _msg

_n = {"w": 0}


async def _rafaga(monkeypatch, proveedor, canal, telefono, *partes):
    """Varios mensajes del cliente en UN mismo envío del webhook, con la ventana de espera real (no 0): toques `(id, título)` o textos."""
    monkeypatch.setenv("DEBOUNCE_RESPUESTA_SEGUNDOS", "0.5")
    mensajes = []
    for parte in partes:
        _n["w"] += 1
        if isinstance(parte, tuple):
            mensajes.append(_msg(telefono, canal, parte[1], f"wamid.bb{_n['w']}", interactivo_id=parte[0]))
        else:
            mensajes.append(_msg(telefono, canal, parte, f"wamid.bb{_n['w']}"))
    await _correr(proveedor, mensajes)
    monkeypatch.setenv("DEBOUNCE_RESPUESTA_SEGUNDOS", "0")


async def _respuestas_en_timeline(tel: str) -> list[dict]:
    return [e for e in await mem.listar_eventos_lead(tel) if e["tipo"] == "calificacion_respuesta"]


async def _hasta_el_dato(monkeypatch, n: int):
    negocio, canal, canal_dict, proveedor, gabi = await _escenario(monkeypatch, "activo")
    tel = _tel(n)
    await _hablar(proveedor, canal, tel, "Estoy interesado en financiar una Cocina")
    await _tocar(proveedor, canal, tel, "cal:gas:si", "Sí, ya tengo")
    await _tocar(proveedor, canal, tel, "cal:titular:si", "Sí, soy el titular")
    await _tocar(proveedor, canal, tel, "cal:cocina:pie", "De pie (con horno)")
    assert "un dato del titular" in _cuerpo(proveedor) and gabi.llamadas == 0
    return negocio, canal, proveedor, gabi, tel


# ── Ráfagas de toques ───────────────────────────────────────────────────────

async def test_dos_toques_seguidos_reciben_una_sola_respuesta_segun_el_ultimo(monkeypatch):
    negocio, canal, canal_dict, proveedor, gabi = await _escenario(monkeypatch, "activo")
    tel = _tel(60)
    await _hablar(proveedor, canal, tel, "¿Cuánto cuesta y cómo lo pago?")
    assert proveedor.interactivos[-1]["type"] == "list"                       # la lista de producto
    antes = len(proveedor.interactivos)
    await _rafaga(monkeypatch, proveedor, canal, tel, ("cal:producto:terma", "Terma a gas"), ("cal:producto:cocina", "Cocina o encimera"))
    assert len(proveedor.interactivos) == antes + 1 and gabi.llamadas == 0    # UNA sola pregunta, sin IA
    assert _cuerpo(proveedor) == "¿Tu casa ya tiene gas natural de Cálidda?"
    assert (await mem.obtener_estado_calificacion(tel))["respuestas"] == {"producto": "cocina"}   # ganó el último toque
    assert (await mem.obtener_lead(tel, negocio_id=negocio["id"]))["interes"] == "cocina"


async def test_mas_tarde_tocado_enseguida_gana_y_la_ia_no_pide_el_dato(monkeypatch):
    negocio, canal, proveedor, gabi, tel = await _hasta_el_dato(monkeypatch, 61)
    await _rafaga(monkeypatch, proveedor, canal, tel, ("cal:dato:cliente", "Número de cliente"), ("cal:dato:luego", "Más tarde"))
    assert gabi.llamadas == 1                                                 # una sola respuesta de la IA, no dos
    estado = await mem.obtener_estado_calificacion(tel)
    assert estado["respuestas"]["dato"] == "luego"
    lead = await mem.obtener_lead(tel, negocio_id=negocio["id"])
    bloques = await brain._armar_bloques_contexto("Más tarde", [], lead, negocio["id"])
    final = [b for b in bloques if "ETAPA FINAL" in b][0]
    assert "NO se lo vuelvas a pedir" in final and "pídele ese número" not in final


async def test_mas_tarde_unos_segundos_despues_tambien_corrige(monkeypatch):
    negocio, canal, proveedor, gabi, tel = await _hasta_el_dato(monkeypatch, 62)
    await _tocar(proveedor, canal, tel, "cal:dato:cliente", "Número de cliente")
    assert gabi.llamadas == 1
    await _tocar(proveedor, canal, tel, "cal:dato:luego", "Más tarde")       # dentro de la ventana de corrección
    assert (await mem.obtener_estado_calificacion(tel))["respuestas"]["dato"] == "luego"
    eventos = await _respuestas_en_timeline(tel)
    assert eventos[0]["payload"]["valor"] == "luego" and eventos[0]["payload"].get("correccion") is True


async def test_el_mismo_boton_dos_veces_no_duplica_nada(monkeypatch):
    negocio, canal, canal_dict, proveedor, gabi = await _escenario(monkeypatch, "activo")
    tel = _tel(63)
    await _hablar(proveedor, canal, tel, "Estoy interesado en financiar una Terma")
    antes = len(proveedor.interactivos)
    await _rafaga(monkeypatch, proveedor, canal, tel, ("cal:gas:si", "Sí, ya tengo"), ("cal:gas:si", "Sí, ya tengo"))
    assert len(proveedor.interactivos) == antes + 1 and gabi.llamadas == 0
    assert len(await _respuestas_en_timeline(tel)) == 1
    await _tocar(proveedor, canal, tel, "cal:gas:si", "Sí, ya tengo")        # y un tercer toque igual, aparte: tampoco
    assert len(proveedor.interactivos) == antes + 1 and gabi.llamadas == 0


async def test_una_correccion_que_lleva_a_la_pregunta_ya_enviada_no_la_repite(monkeypatch):
    negocio, canal, canal_dict, proveedor, gabi = await _escenario(monkeypatch, "activo")
    tel = _tel(64)
    await _hablar(proveedor, canal, tel, "Estoy interesado en financiar una Terma")
    await _tocar(proveedor, canal, tel, "cal:gas:si", "Sí, ya tengo")
    await _tocar(proveedor, canal, tel, "cal:equipo:ambos", "Punto de gas y ductería")
    await _tocar(proveedor, canal, tel, "cal:titular:si", "Sí, soy el titular")
    antes = len(proveedor.interactivos)
    await _tocar(proveedor, canal, tel, "cal:titular:familiar", "Es de un familiar")   # corrige: la pregunta de baños ya está a la vista
    assert len(proveedor.interactivos) == antes and gabi.llamadas == 0
    assert (await mem.obtener_estado_calificacion(tel))["respuestas"]["titular"] == "familiar"


async def test_toque_y_pregunta_escrita_en_la_misma_rafaga(monkeypatch):
    negocio, canal, canal_dict, proveedor, gabi = await _escenario(monkeypatch, "activo")
    tel = _tel(65)
    await _hablar(proveedor, canal, tel, "Estoy interesado en financiar una Terma")
    antes = len(proveedor.interactivos)
    await _rafaga(monkeypatch, proveedor, canal, tel, ("cal:gas:si", "Sí, ya tengo"), "¿cuánto demora la instalación?")
    assert gabi.llamadas == 1                                                 # Gabi contesta la pregunta escrita, una vez
    assert len(proveedor.interactivos) == antes + 1 and "terma" in _cuerpo(proveedor)   # y después sigue el flujo, una vez
    assert (await mem.obtener_estado_calificacion(tel))["conteo"] == {"gas": 1, "equipo": 1}


# ── Respuestas escritas ─────────────────────────────────────────────────────

async def test_a_nombre_de_mi_esposo_se_entiende_como_familiar_y_sigue_sin_ia(monkeypatch):
    negocio, canal, canal_dict, proveedor, gabi = await _escenario(monkeypatch, "activo")
    tel = _tel(66)
    await _hablar(proveedor, canal, tel, "Estoy interesado en financiar una Terma")
    await _tocar(proveedor, canal, tel, "cal:gas:si", "Sí, ya tengo")
    await _tocar(proveedor, canal, tel, "cal:equipo:ambos", "Punto de gas y ductería")
    await _hablar(proveedor, canal, tel, "está a nombre de mi esposo")
    assert gabi.llamadas == 0 and "cuántos baños" in _cuerpo(proveedor)
    estado = await mem.obtener_estado_calificacion(tel)
    assert estado["respuestas"]["titular"] == "familiar" and estado["conteo"]["titular"] == 1     # no se repitió la pregunta
    ultimo = (await _respuestas_en_timeline(tel))[0]
    assert ultimo["payload"]["origen"] == "texto" and "es de un familiar" in ultimo["descripcion"]


async def test_dos_banos_escrito_y_despues_te_lo_paso_llegan_a_la_etapa_final(monkeypatch):
    negocio, canal, canal_dict, proveedor, gabi = await _escenario(monkeypatch, "activo")
    tel = _tel(67)
    await _hablar(proveedor, canal, tel, "Estoy interesado en financiar una Terma")
    for id_boton, titulo in (("cal:gas:si", "Sí, ya tengo"), ("cal:equipo:ambos", "Punto de gas y ductería"), ("cal:titular:si", "Sí, soy el titular")):
        await _tocar(proveedor, canal, tel, id_boton, titulo)
    await _hablar(proveedor, canal, tel, "2 baños")
    assert gabi.llamadas == 0 and "un dato del titular" in _cuerpo(proveedor)
    await _hablar(proveedor, canal, tel, "después te lo paso")
    assert gabi.llamadas == 1                                                 # la etapa final la escribe Claude
    assert (await mem.obtener_estado_calificacion(tel))["respuestas"]["dato"] == "luego"


async def test_respuesta_escrita_dudosa_sigue_como_antes(monkeypatch):
    negocio, canal, canal_dict, proveedor, gabi = await _escenario(monkeypatch, "activo")
    tel = _tel(68)
    await _hablar(proveedor, canal, tel, "Estoy interesado en financiar una Cocina")
    await _tocar(proveedor, canal, tel, "cal:gas:si", "Sí, ya tengo")
    await _hablar(proveedor, canal, tel, "no sé si mi esposo es el titular")
    assert gabi.llamadas == 1                                                 # no adivina: contesta Gabi y se retoma la pregunta
    estado = await mem.obtener_estado_calificacion(tel)
    assert "titular" not in estado["respuestas"] and estado["conteo"]["titular"] == 2


async def test_la_muletilla_solo_va_en_la_primera_consulta():
    vacio = {"preguntas": [], "conteo": {}, "respuestas": {}}
    primera = cg.bloque_contexto(vacio, va_la_primera_pregunta=True)
    assert "Te hago una consulta rápida" in primera
    retomo = cg.bloque_contexto({"preguntas": ["gas"], "conteo": {"gas": 1}, "respuestas": {}}, va_la_primera_pregunta=False)
    assert "NO anuncies la consulta" in retomo and "NO hagas ninguna pregunta" in retomo
    assert "por ejemplo: «Te hago una consulta rápida" not in retomo
    tras_toque = cg.bloque_contexto({"preguntas": ["gas"], "conteo": {"gas": 1}, "respuestas": {"gas": "si"}}, va_la_primera_pregunta=False, tipo_producto="terma")
    assert "NO anuncies la consulta" in tras_toque                            # la pregunta de equipo aún no salió: va después


# ── El intérprete (puro) ────────────────────────────────────────────────────

@pytest.mark.parametrize("paso,texto,tipo,esperado", [
    ("gas", "sí", "terma", "si"), ("gas", "Si, ya tengo", "terma", "si"), ("gas", "claro", "terma", "si"),
    ("gas", "no", "terma", "no"), ("gas", "aún no tengo", "terma", "no"), ("gas", "todavía no", "terma", "no"),
    ("gas", "no sé", "terma", "ns"), ("gas", "no estoy segura", "terma", "ns"),
    ("titular", "a nombre de mi esposo", "terma", "familiar"), ("titular", "Sí, de mi mamá", "terma", "familiar"),
    ("titular", "es de mi suegra", "terma", "familiar"), ("titular", "es de un familiar", "terma", "familiar"),
    ("titular", "del propietario, vivo alquilado", "terma", "otro"), ("titular", "sí, soy el titular", "terma", "si"),
    ("titular", "a mi nombre", "terma", "si"), ("titular", "sí", "terma", "si"),
    ("tamano", "2 baños", "terma", "2"), ("tamano", "dos", "terma", "2"), ("tamano", "un baño", "terma", "1"),
    ("tamano", "tiene 4 baños", "terma", "3"), ("tamano", "somos 6", "secadora", "grande"),
    ("tamano", "3 personas", "lavado", "pequena"), ("tamano", "no sé", "secadora", "ns"),
    ("cocina", "empotrable", "cocina", "empotrable"), ("cocina", "una encimera", "cocina", "empotrable"),
    ("cocina", "de pie con horno", "cocina", "pie"),
    ("complemento", "con campana", "cocina", "campana"), ("complemento", "horno y campana", "cocina", "ambos"),
    ("complemento", "solo la encimera", "cocina", "solo"),
    ("equipo", "sí", "secadora", "punto"), ("equipo", "no tengo", "secadora", "ninguno"),
    ("equipo", "tengo los dos", "terma", "ambos"), ("equipo", "ninguno", "terma", "ninguno"), ("equipo", "no sé", "terma", "ns"),
    ("dato", "después te lo paso", "terma", "luego"), ("dato", "más tarde", "terma", "luego"),
    ("dato", "45781236", "terma", "dni"), ("dato", "el dni", "terma", "dni"), ("dato", "con el número de cliente", "terma", "cliente"),
    ("singas", "quiero contratar el gas", "terma", "contratar"), ("singas", "solo comprar la terma", "terma", "equipo"),
    ("producto", "una secadora", "otro", "secadora"),
])
def test_respuestas_escritas_claras(paso, texto, tipo, esperado):
    assert cg.interpretar_texto(paso, texto, tipo) == esperado


@pytest.mark.parametrize("paso,texto,tipo", [
    ("gas", "¿cómo sé si tengo gas?", "terma"),                 # pregunta: la atiende Gabi
    ("gas", "sí pero no", "terma"),                             # dos lecturas
    ("titular", "no sé si mi esposo es el titular", "terma"),
    ("titular", "no es de mi esposo", "terma"),
    ("titular", "no", "terma"),                                 # no dice de quién es
    ("titular", "de mi esposo o del propietario", "terma"),
    ("tamano", "no sé", "terma"),                               # la terma no tiene «no sé» en baños
    ("tamano", "2", "cocina"), ("tamano", "50 baños", "terma"),
    ("cocina", "una normal pero empotrable", "cocina"),
    ("complemento", "con horno pero sin campana", "cocina"),
    ("equipo", "sí", "terma"),                                  # ¿punto, ductería o ambos?
    ("equipo", "tengo punto pero no ductería", "terma"),
    ("dato", "123", "terma"), ("dato", "dni o número de cliente", "terma"),
    ("gas", "hola buenas tardes quisiera saber si ustedes instalan la terma y cuánto demora todo el proceso de evaluación", "terma"),
    ("producto", "hola", "otro"),
])
def test_respuestas_escritas_dudosas_no_se_adivinan(paso, texto, tipo):
    assert cg.interpretar_texto(paso, texto, tipo) is None
