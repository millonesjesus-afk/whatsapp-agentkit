# tests/test_configuracion_derivacion_automatica.py — 2026-10-11, decisión del dueño: una sección «Derivación automática» en
# el panel para configurar el triaje de temas no comerciales (recibo, número de cliente, pago/deuda y emergencia de gas)
# sin pasar por el script. GET/POST /dashboard/configuracion/derivacion-automatica.json: solo Admin, CSRF, del negocio de
# la sesión, todo o nada, mismas validaciones que scripts/configurar_triaje_atc.py, con auditoría (Historial de
# configuración). Además: el resultado de cierre es configurable por negocio (`triaje_atc_resultado`).

import json
from datetime import datetime, timedelta

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from agent import dashboard
from agent import derivacion_automatica as da
from agent import memory as mem
from agent import triaje_atc as t

_n = {"i": 0}


async def _negocio(codigo: str):
    negocio = await mem.crear_negocio(f"Negocio {codigo}", codigo)
    _n["i"] += 1
    canal = await mem.crear_canal_whatsapp(nombre="C", phone_number_id=f"4112{_n['i']:06d}", negocio_id=negocio["id"])
    return negocio, canal


def _admin(negocio, username="admin1"):
    return {"username": username, "nombre": "Admin", "negocio_id": negocio["id"], "rol": "admin"}


class _Peticion:
    def __init__(self, cuerpo):
        self._cuerpo = cuerpo

    async def json(self):
        if isinstance(self._cuerpo, Exception):
            raise self._cuerpo
        return self._cuerpo


async def _post(negocio, cuerpo, username="admin1"):
    r = await dashboard.actualizar_configuracion_derivacion_automatica_json(_Peticion(cuerpo), usuario=_admin(negocio, username), _csrf=None)
    return json.loads(r.body)


async def _get(negocio):
    return json.loads((await dashboard.configuracion_derivacion_automatica_json(usuario=_admin(negocio))).body)


async def _auditorias(negocio):
    async with mem.async_session() as s:
        return (await s.execute(
            select(mem.RegistroAuditoria).where(
                mem.RegistroAuditoria.negocio_id == negocio["id"], mem.RegistroAuditoria.accion == da.ACCION_AUDITORIA,
            ).order_by(mem.RegistroAuditoria.creado)
        )).scalars().all()


async def _valor(negocio, clave, defecto="(sin fijar)"):
    return await mem.obtener_configuracion(clave, defecto, negocio_id=negocio["id"])


def _estado(r, categoria):
    return next(c for c in r["categorias"] if c["id"] == categoria)["estado_efectivo"]


# ── GET: todo apagado por defecto ────────────────────────────────────────────

async def test_get_por_defecto_todo_apagado_y_no_escribe_nada():
    negocio, _ = await _negocio("da-a")
    r = await _get(negocio)
    assert (r["modo"], r["modo_efectivo"], r["emergencia_modo"], r["emergencia_modo_efectivo"]) == ("apagado",) * 4
    assert [c["id"] for c in r["categorias"]] == ["recibo", "numero_cliente", "pago_deuda", "reclamo", "emergencia_gas"]
    assert all(c["estado_efectivo"] == "apagado" for c in r["categorias"])
    assert r["categorias_incluidas"] == ["recibo", "numero_cliente", "pago_deuda", "reclamo"]
    assert r["lineas"] == {"atencion": "", "emergencia": "", "ventas": ""}
    assert r["resultado"] == "consulta_atc" and r["resultado_por_defecto"] == "consulta_atc"
    assert r["textos_originales"] == {"general": t.TEXTO_POR_DEFECTO, "emergencia": t.TEXTO_EMERGENCIA_POR_DEFECTO}
    assert r["texto_general"] == "" and r["texto_emergencia"] == "" and set(r["textos_categoria"]) == set(t.CATEGORIAS_ATC)
    assert {v["nombre"] for v in r["variables"]} == {"{nombre}", "{linea_atc}", "{negocio}", "{linea_emergencia}", "{linea_ventas}"}
    assert r["limites"]["texto"] == 600 and r["nunca_se_cierra"]
    assert [x["valor"] for x in r["resultados_permitidos"]][0] == "consulta_atc"
    assert r["actividad_30_dias"]["dias"] == 30 and all(c["registradas"] == 0 for c in r["actividad_30_dias"]["por_categoria"])
    assert await _valor(negocio, t.CLAVE_MODO) == "(sin fijar)" and await _auditorias(negocio) == []


async def test_los_resultados_permitidos_no_incluyen_comerciales():
    negocio, _ = await _negocio("da-b")
    valores = {x["valor"] for x in (await _get(negocio))["resultados_permitidos"]}
    assert "consulta_atc" in valores
    assert not valores & {"vendido", "agendado", "postventa", "no_interesado", "no_califica", "sin_respuesta", "sin_saldo", "producto_sin_stock"}
    assert valores <= set(mem.RESULTADOS_CERRADOS)


# ── POST: guardar sin cambiar nada no activa ni escribe nada ────────────────

async def test_guardar_sin_cambiar_nada_no_escribe_ni_audita():
    negocio, _ = await _negocio("da-c")
    r = await _post(negocio, {})
    assert r["ok"] is True and r["modificadas"] == []
    r = await _post(negocio, {
        "modo": "apagado", "emergencia_modo": "apagado", "categorias": ["recibo", "numero_cliente", "pago_deuda", "reclamo"],
        "lineas": {"atencion": "", "emergencia": "", "ventas": ""}, "texto_general": "", "texto_emergencia": "", "resultado": "consulta_atc",
        "textos_categoria": {"recibo": "", "pago_deuda": ""}, "nombre_negocio": "",
    })
    assert r["modificadas"] == []
    assert await _valor(negocio, t.CLAVE_MODO) == "(sin fijar)" and await _valor(negocio, t.CLAVE_CATEGORIAS) == "(sin fijar)"
    assert await _auditorias(negocio) == []
    assert (await _get(negocio))["modo"] == "apagado"


async def test_guardar_lo_mismo_dos_veces_audita_solo_el_primer_cambio():
    negocio, _ = await _negocio("da-d")
    primero = await _post(negocio, {"modo": "sombra"})
    assert primero["modificadas"] == [t.CLAVE_MODO]
    segundo = await _post(negocio, {"modo": "sombra"})
    assert segundo["modificadas"] == []
    assert len(await _auditorias(negocio)) == 1


# ── POST: modos, líneas y estado efectivo ─────────────────────────────────────

async def test_el_paso_a_paso_de_la_activacion_y_el_estado_efectivo():
    negocio, _ = await _negocio("da-e")
    r = await _post(negocio, {"lineas": {"atencion": "614900, opción 5", "emergencia": "1808 (Emergencias 24/7)", "ventas": "614-9002"}})
    assert r["lineas"]["atencion"] == "614900, opción 5" and r["modo"] == "apagado" and r["emergencia_modo"] == "apagado"   # las líneas no encienden nada
    r = await _post(negocio, {"modo": "sombra"})
    assert (r["modo"], r["modo_efectivo"], _estado(r, "recibo"), _estado(r, "emergencia_gas")) == ("sombra", "sombra", "sombra", "apagado")
    r = await _post(negocio, {"modo": "activo"})
    assert (r["modo_efectivo"], _estado(r, "pago_deuda"), _estado(r, "emergencia_gas")) == ("activo", "activo", "apagado")   # interruptor de emergencia independiente
    r = await _post(negocio, {"emergencia_modo": "activo"})
    assert (r["emergencia_modo_efectivo"], _estado(r, "emergencia_gas"), _estado(r, "recibo")) == ("activo", "activo", "activo")
    r = await _post(negocio, {"modo": "apagado"})
    assert (_estado(r, "recibo"), _estado(r, "emergencia_gas")) == ("apagado", "activo")
    assert await _valor(negocio, t.CLAVE_EMERGENCIA_MODO) == "activo"


async def test_no_se_puede_activar_sin_la_linea_de_atencion_ni_la_de_emergencia():
    negocio, _ = await _negocio("da-f")
    with pytest.raises(HTTPException) as e:
        await _post(negocio, {"modo": "activo"})
    assert e.value.status_code == 400 and "línea de atención" in e.value.detail
    with pytest.raises(HTTPException) as e:
        await _post(negocio, {"emergencia_modo": "activo"})
    assert e.value.status_code == 400 and "línea de emergencias" in e.value.detail
    assert await _valor(negocio, t.CLAVE_MODO) == "(sin fijar)" and await _valor(negocio, t.CLAVE_EMERGENCIA_MODO) == "(sin fijar)"
    # activar y poner la línea en el mismo guardado sí
    r = await _post(negocio, {"modo": "activo", "emergencia_modo": "activo", "lineas": {"atencion": "614900", "emergencia": "1808"}})
    assert (r["modo_efectivo"], r["emergencia_modo_efectivo"]) == ("activo", "activo")
    # sombra no exige nada
    otro, _ = await _negocio("da-f2")
    assert (await _post(otro, {"modo": "sombra", "emergencia_modo": "sombra"}))["emergencia_modo_efectivo"] == "sombra"


async def test_activo_sin_linea_se_muestra_degradado_a_sombra_con_su_motivo():
    negocio, _ = await _negocio("da-g")
    # estado heredado inconsistente (p. ej. fijado a mano en la base): el panel lo muestra tal como lo trata el triaje
    await mem.guardar_configuracion(t.CLAVE_MODO, "activo", negocio_id=negocio["id"])
    await mem.guardar_configuracion(t.CLAVE_EMERGENCIA_MODO, "activo", negocio_id=negocio["id"])
    r = await _get(negocio)
    assert (r["modo"], r["modo_efectivo"], r["modo_degradado_motivo"]) == ("activo", "sombra", "sin_linea_atencion")
    assert (r["emergencia_modo"], r["emergencia_modo_efectivo"], r["emergencia_degradado_motivo"]) == ("activo", "sombra", "sin_linea_emergencia")
    recibo = next(c for c in r["categorias"] if c["id"] == "recibo")
    assert recibo["estado_efectivo"] == "sombra" and recibo["motivo_degradado"] == "sin_linea_atencion"
    # el estado efectivo coincide con lo que decide el triaje de verdad
    assert await t._emergencia_lista(negocio["id"]) is False
    # guardar otra cosa no queda bloqueado por el estado heredado
    assert (await _post(negocio, {"nombre_negocio": "Gaso+"}))["nombre_negocio"] == "Gaso+"
    # un texto propio de emergencia que ya trae el número no exige la línea
    otro, _ = await _negocio("da-g2")
    r = await _post(otro, {"emergencia_modo": "activo", "texto_emergencia": "Sal ya de la casa y comunícate con Cálidda al 1808.", "lineas": {"emergencia": "1808"}})
    assert r["emergencia_modo_efectivo"] == "activo"


async def test_quitar_la_linea_con_el_modo_activo_se_rechaza():
    negocio, _ = await _negocio("da-h")
    await _post(negocio, {"modo": "activo", "lineas": {"atencion": "614900"}})
    with pytest.raises(HTTPException) as e:
        await _post(negocio, {"lineas": {"atencion": ""}})
    assert e.value.status_code == 400
    assert (await _get(negocio))["lineas"]["atencion"] == "614900"


async def test_modos_y_categorias_invalidos_se_rechazan():
    negocio, _ = await _negocio("da-i")
    for cuerpo in (
        {"modo": "encendido"}, {"modo": None}, {"emergencia_modo": 1}, {"categorias": []}, {"categorias": ["recibo", "inventada"]},
        {"categorias": "recibo"}, {"categorias": ["emergencia_gas"]}, {"campo_raro": 1}, {"lineas": {"otra": "x"}}, {"lineas": "x"},
        {"textos_categoria": {"emergencia_gas": "Hola {linea_atc}"}}, {"textos_categoria": ["x"]}, {"resultado": 5},
    ):
        with pytest.raises(HTTPException) as e:
            await _post(negocio, cuerpo)
        assert e.value.status_code == 400, cuerpo
    assert await _auditorias(negocio) == []


async def test_las_categorias_se_incluyen_en_orden_y_una_no_incluida_queda_apagada():
    negocio, _ = await _negocio("da-j")
    r = await _post(negocio, {"modo": "sombra", "categorias": ["pago_deuda", "Recibo", "recibo"]})
    assert r["categorias_incluidas"] == ["recibo", "pago_deuda"]
    assert await _valor(negocio, t.CLAVE_CATEGORIAS) == "recibo,pago_deuda"
    assert (_estado(r, "recibo"), _estado(r, "numero_cliente"), _estado(r, "pago_deuda")) == ("sombra", "apagado", "sombra")
    assert next(c for c in r["categorias"] if c["id"] == "numero_cliente")["incluida"] is False


async def test_las_lineas_y_el_nombre_no_aceptan_marcadores_ni_preguntas():
    negocio, _ = await _negocio("da-k")
    for cuerpo in (
        {"lineas": {"atencion": "x" * 130}}, {"lineas": {"atencion": "¿cuál?"}}, {"lineas": {"emergencia": "{linea_atc}"}},
        {"lineas": {"ventas": "614\n9002"}}, {"nombre_negocio": "y" * 130}, {"nombre_negocio": "Gaso{"}, {"lineas": {"atencion": 614900}},
    ):
        with pytest.raises(HTTPException):
            await _post(negocio, cuerpo)
    assert await _auditorias(negocio) == []


# ── POST: textos ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize("texto", [
    "¡Hola! ¿Necesitas algo más?",
    "Llámanos a la línea {linea_atc} y te atendemos.",
    "Envíanos tu DNI a la línea {linea_atc}.",
    "Te avisamos cuando tengamos novedades en {linea_atc}.",
    "Atendemos de lunes a viernes en la línea {linea_atc}.",
    "Atendemos a las 9 en la línea {linea_atc}.",
    "x" * 700,
    "Hola{nombre}, la línea {linea} resuelve tu recibo.",          # variable desconocida
])
async def test_un_texto_invalido_se_rechaza_con_las_mismas_reglas_del_script(texto):
    negocio, _ = await _negocio("da-l")
    with pytest.raises(HTTPException) as e:
        await _post(negocio, {"texto_general": texto})
    assert e.value.status_code == 400 and e.value.detail
    with pytest.raises(HTTPException):
        await _post(negocio, {"textos_categoria": {"recibo": texto}})
    assert await _valor(negocio, t.CLAVE_TEXTO) == "(sin fijar)"


async def test_los_validadores_del_script_y_del_panel_son_los_mismos():
    import importlib.util
    from pathlib import Path
    ruta = Path(__file__).resolve().parent.parent / "scripts" / "configurar_triaje_atc.py"
    spec = importlib.util.spec_from_file_location("configurar_triaje_atc_da", ruta)
    ct = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ct)
    assert ct.validar_texto is da.validar_texto and ct.validar_texto_emergencia is da.validar_texto_emergencia
    assert ct.TEXTO_MAXIMO == da.TEXTO_MAXIMO == 600


async def test_un_texto_valido_se_guarda_se_audita_y_vacio_vuelve_al_original():
    negocio, _ = await _negocio("da-m")
    propio = "Hola{nombre}, en {negocio} la línea {linea_atc} resuelve tu recibo."
    r = await _post(negocio, {"texto_general": propio, "textos_categoria": {"recibo": "El recibo lo resuelve la línea {linea_atc}."}})
    assert r["texto_general"] == propio and r["textos_categoria"]["recibo"].startswith("El recibo")
    assert sorted(r["modificadas"]) == sorted([t.CLAVE_TEXTO, t.CLAVE_TEXTO_CATEGORIA + "recibo"])
    assert next(c for c in r["categorias"] if c["id"] == "recibo")["texto_origen"] == "propio"
    assert next(c for c in r["categorias"] if c["id"] == "pago_deuda")["texto_origen"] == "general"
    r = await _post(negocio, {"texto_general": "", "textos_categoria": {"recibo": ""}})
    assert r["texto_general"] == "" and r["textos_categoria"]["recibo"] == ""
    assert next(c for c in r["categorias"] if c["id"] == "recibo")["texto_origen"] == "original"
    assert await _valor(negocio, t.CLAVE_TEXTO) == ""
    # el texto por defecto del módulo también es válido
    assert da.validar_texto(t.TEXTO_POR_DEFECTO, "defecto") == t.TEXTO_POR_DEFECTO


async def test_texto_sin_la_linea_de_atencion_avisa_pero_guarda():
    negocio, _ = await _negocio("da-n")
    r = await _post(negocio, {"texto_general": "En {negocio} te ayudamos con la compra de gasodomésticos."})
    assert r["modificadas"] == [t.CLAVE_TEXTO] and any("línea de atención" in a for a in r["avisos"])


async def test_texto_de_emergencia_reglas_y_avisos():
    negocio, _ = await _negocio("da-o")
    for texto in ("Sal de la casa. ¿Necesitas ayuda?", "Sal de la casa y llama a Emergencias.", "x" * 700 + " {linea_emergencia}"):
        with pytest.raises(HTTPException):
            await _post(negocio, {"texto_emergencia": texto})
    assert da.validar_texto_emergencia(t.TEXTO_EMERGENCIA_POR_DEFECTO) == (t.TEXTO_EMERGENCIA_POR_DEFECTO, [])
    r = await _post(negocio, {"texto_emergencia": "Llama ya a Emergencias: {linea_emergencia}."})
    assert r["texto_emergencia"].startswith("Llama") and len(r["avisos"]) == 1 and "ok" in r["avisos"][0]
    r = await _post(negocio, {"texto_emergencia": ""})
    assert r["texto_emergencia"] == "" and r["textos_originales"]["emergencia"] == t.TEXTO_EMERGENCIA_POR_DEFECTO


async def test_todo_o_nada_un_dato_invalido_no_deja_nada_guardado():
    negocio, _ = await _negocio("da-p")
    with pytest.raises(HTTPException):
        await _post(negocio, {"modo": "sombra", "lineas": {"atencion": "614900"}, "texto_general": "¿Necesitas algo?"})
    assert await _valor(negocio, t.CLAVE_MODO) == "(sin fijar)" and await _valor(negocio, t.CLAVE_LINEA) == "(sin fijar)"
    assert await _auditorias(negocio) == []


# ── POST: resultado configurable ──────────────────────────────────────────────

async def test_el_resultado_se_valida_y_se_audita():
    negocio, _ = await _negocio("da-q")
    for malo in ("vendido", "agendado", "postventa", "no_interesado", "sin_respuesta", "inventado", ""):
        with pytest.raises(HTTPException) as e:
            await _post(negocio, {"resultado": malo})
        assert e.value.status_code == 400, malo
    assert await _valor(negocio, mem.CLAVE_TRIAJE_RESULTADO) == "(sin fijar)"
    r = await _post(negocio, {"resultado": "otro"})
    assert r["resultado"] == "otro" and r["modificadas"] == [mem.CLAVE_TRIAJE_RESULTADO] and any("Consulta ATC" in a for a in r["avisos"])
    assert await mem.obtener_resultado_triaje(negocio["id"]) == "otro"
    r = await _post(negocio, {"resultado": "consulta_atc"})
    assert r["resultado"] == "consulta_atc" and r["avisos"] == []


async def test_un_valor_invalido_guardado_a_mano_cae_a_consulta_atc():
    negocio, _ = await _negocio("da-r")
    await mem.guardar_configuracion(mem.CLAVE_TRIAJE_RESULTADO, "vendido", negocio_id=negocio["id"])
    assert await mem.obtener_resultado_triaje(negocio["id"]) == "consulta_atc"
    assert (await _get(negocio))["resultado"] == "consulta_atc"


async def _caso_abierto(codigo, telefono):
    negocio, canal = await _negocio(codigo)
    await mem.actualizar_lead(telefono, negocio_id=negocio["id"], numero_whatsapp_id="x")
    conv, opp = await mem.resolver_conversation_activa(telefono, negocio["id"], canal["id"])
    return negocio, conv, opp


async def _evento_resultado(conv_id):
    async with mem.async_session() as s:
        return (await s.execute(
            select(mem.EventoLead).where(mem.EventoLead.conversation_id == conv_id, mem.EventoLead.tipo == "resultado_cambiado")
        )).scalars().one()


async def test_cerrar_por_triaje_usa_consulta_atc_por_defecto():
    negocio, conv, opp = await _caso_abierto("da-s1", "51940002001")
    r = await mem.cerrar_por_triaje("51940002001", negocio["id"], "recibo")
    assert r is not None
    lead = await mem.obtener_lead("51940002001", negocio_id=negocio["id"])
    assert lead["resultado"] == "consulta_atc"
    ev = await _evento_resultado(conv.id)
    assert ev.payload["nuevo"] == "consulta_atc" and "Consulta ATC" in ev.descripcion


async def test_cerrar_por_triaje_usa_el_resultado_configurado_del_negocio():
    negocio, conv, opp = await _caso_abierto("da-s2", "51940002002")
    await _post(negocio, {"resultado": "otro"})
    assert await mem.cerrar_por_triaje("51940002002", negocio["id"], "pago_deuda") is not None
    lead = await mem.obtener_lead("51940002002", negocio_id=negocio["id"])
    assert lead["resultado"] == "otro" and lead["cerrado_definitivamente_en"] is not None
    async with mem.async_session() as s:
        assert (await s.get(mem.Opportunity, opp.id)).resultado == "otro"
    ev = await _evento_resultado(conv.id)
    assert ev.payload["nuevo"] == "otro" and "«Otro»" in ev.descripcion
    async with mem.async_session() as s:
        cierre = (await s.execute(select(mem.EventoLead).where(mem.EventoLead.tipo == mem.EVENTO_TRIAJE_ATC_CERRADO, mem.EventoLead.conversation_id == conv.id))).scalars().one()
    assert cierre.payload["resultado"] == "otro" and cierre.payload["categoria"] == "pago_deuda"


async def test_cerrar_por_triaje_la_emergencia_tambien_usa_el_resultado_configurado():
    negocio, conv, opp = await _caso_abierto("da-s3", "51940002003")
    await _post(negocio, {"resultado": "no_es_cliente_calidda"})
    assert await mem.cerrar_por_triaje("51940002003", negocio["id"], "emergencia_gas") is not None
    assert (await mem.obtener_lead("51940002003", negocio_id=negocio["id"]))["resultado"] == "no_es_cliente_calidda"


async def test_el_resultado_de_un_negocio_no_afecta_a_otro():
    a, _, _ = await _caso_abierto("da-s4a", "51940002004")
    b, _, _ = await _caso_abierto("da-s4b", "51940002005")
    await _post(a, {"resultado": "otro"})
    await mem.cerrar_por_triaje("51940002005", b["id"], "recibo")
    assert (await mem.obtener_lead("51940002005", negocio_id=b["id"]))["resultado"] == "consulta_atc"


async def test_cerrar_por_triaje_rechaza_un_resultado_explicito_no_permitido():
    negocio, conv, opp = await _caso_abierto("da-s5", "51940002006")
    with pytest.raises(ValueError):
        await mem.cerrar_por_triaje("51940002006", negocio["id"], "recibo", resultado="vendido")
    assert (await mem.obtener_lead("51940002006", negocio_id=negocio["id"]))["resultado"] is None


# ── Auditoría e Historial ─────────────────────────────────────────────────────

async def test_el_cambio_queda_en_el_historial_de_configuracion_con_quien_y_antes_despues():
    negocio, _ = await _negocio("da-t")
    await _post(negocio, {"modo": "sombra", "lineas": {"atencion": "614900"}}, username="angie")
    await _post(negocio, {"modo": "activo"}, username="rvilchez")
    filas = await _auditorias(negocio)
    assert len(filas) == 2 and filas[0].actor == "angie" and filas[1].actor == "rvilchez"
    assert filas[0].entidad_tipo == "configuracion" and filas[0].payload["riesgo_confirmado"] is False
    assert filas[0].payload["cambios"][t.CLAVE_MODO] == {"antes": None, "despues": "sombra"}
    assert filas[1].payload["cambios"] == {t.CLAVE_MODO: {"antes": "sombra", "despues": "activo"}}
    historial = await mem.listar_cambios_configuracion(negocio["id"])
    assert [h["accion"] for h in historial] == [da.ACCION_AUDITORIA] * 2 and historial[0]["actor"] == "rvilchez"


async def test_el_negocio_sale_de_la_sesion_no_del_cuerpo():
    a, _ = await _negocio("da-u1")
    b, _ = await _negocio("da-u2")
    with pytest.raises(HTTPException):
        await _post(a, {"modo": "sombra", "negocio_id": b["id"]})      # campo no reconocido: nunca se acepta un negocio del cuerpo
    await _post(a, {"modo": "sombra"})
    assert (await _get(a))["modo"] == "sombra" and (await _get(b))["modo"] == "apagado"


# ── Actividad de los últimos 30 días ──────────────────────────────────────────

async def test_la_actividad_cuenta_por_categoria_y_no_trae_datos_personales():
    negocio, conv, opp = await _caso_abierto("da-v", "51940003001")
    ahora = datetime.utcnow()
    async with mem.async_session() as s:
        def ev(tipo, payload, dias=1):
            s.add(mem.EventoLead(
                conversation_id=conv.id, negocio_id=negocio["id"], opportunity_id=opp.id, tipo=tipo, descripcion="x",
                payload=payload, creado=ahora - timedelta(days=dias),
            ))
        ev(mem.EVENTO_TRIAJE_ATC_SOMBRA, {"categoria": "recibo", "accion_propuesta": "cerrar"})
        ev(mem.EVENTO_TRIAJE_ATC_SOMBRA, {"categoria": "recibo", "accion_propuesta": "ninguna"})
        ev(mem.EVENTO_TRIAJE_ATC_SOMBRA, {"categoria": "pago_deuda", "accion_propuesta": "cerrar"})
        ev(mem.EVENTO_TRIAJE_ATC_SOMBRA, {"categoria": "emergencia_gas", "accion_propuesta": "derivar_emergencia"})
        ev(mem.EVENTO_TRIAJE_ATC_SOMBRA, {"categoria": "recibo", "accion_propuesta": "cerrar"}, dias=45)   # fuera de los 30 días
        ev(mem.EVENTO_TRIAJE_ATC_CERRADO, {"categoria": "recibo"})
        ev(mem.EVENTO_TRIAJE_ATC_CERRADO, {"categoria": "emergencia_gas"})
        ev(mem.EVENTO_TRIAJE_ATC_FALLIDO, {"categoria": "pago_deuda"})
        ev(mem.EVENTO_EMERGENCIA_GAS_DERIVADA, {"categoria": "emergencia_gas"})
        ev(mem.EVENTO_TRIAJE_ATC_SOMBRA, None)
        ev(mem.EVENTO_TRIAJE_ATC_SOMBRA, {"categoria": "otra"})
        await s.commit()
    otro, _ = await _negocio("da-v2")
    act = (await _get(negocio))["actividad_30_dias"]
    por = {c["categoria"]: c for c in act["por_categoria"]}
    assert (por["recibo"]["registradas"], por["recibo"]["propuestas_cierre"], por["recibo"]["cerradas"]) == (2, 1, 1)
    assert (por["pago_deuda"]["registradas"], por["pago_deuda"]["fallidas"], por["numero_cliente"]["registradas"]) == (1, 1, 0)
    assert (por["emergencia_gas"]["registradas"], por["emergencia_gas"]["cerradas"], por["emergencia_gas"]["avisos"]) == (1, 1, 1)
    assert act["truncado"] is False and "51940003001" not in json.dumps(act)
    assert all(c["registradas"] == 0 for c in (await _get(otro))["actividad_30_dias"]["por_categoria"])


async def test_si_la_actividad_falla_la_configuracion_se_sigue_pudiendo_ver(monkeypatch):
    negocio, _ = await _negocio("da-w")

    async def explota(*a, **k):
        raise RuntimeError("falla")

    monkeypatch.setattr(da, "actividad_reciente", explota)
    r = await _get(negocio)
    assert r["actividad_30_dias"] is None and r["modo"] == "apagado"


# ── Rutas: solo Admin, CSRF en el POST ────────────────────────────────────────

def _ruta(metodo):
    return next(r for r in dashboard.router.routes if getattr(r, "path", "").endswith("/configuracion/derivacion-automatica.json") and metodo in r.methods)


@pytest.mark.parametrize("metodo", ["GET", "POST"])
async def test_las_rutas_exigen_rol_admin(metodo):
    ruta = _ruta(metodo)
    candado = next(d.call for d in ruta.dependant.dependencies if d.call.__name__ == "_verificar")
    for rol in ("supervisor", "asesor"):
        with pytest.raises(HTTPException) as e:
            await candado(usuario={"username": "x", "rol": rol, "negocio_id": "n"})
        assert e.value.status_code == 403
    assert (await candado(usuario={"username": "x", "rol": "admin", "negocio_id": "n"}))["rol"] == "admin"


def test_el_post_exige_csrf_y_el_get_no_escribe():
    assert "verificar_csrf" in {d.call.__name__ for d in _ruta("POST").dependant.dependencies}
    assert _ruta("GET").methods == {"GET"} and _ruta("POST").methods == {"POST"}


@pytest.mark.parametrize("cuerpo", [Exception("no es json"), ["lista"], "texto", 5])
async def test_el_cuerpo_debe_ser_un_objeto_json(cuerpo):
    negocio, _ = await _negocio("da-x")
    with pytest.raises(HTTPException) as e:
        await _post(negocio, cuerpo)
    assert e.value.status_code == 400


async def test_el_script_tambien_configura_el_resultado_con_la_misma_validacion():
    import importlib.util
    from pathlib import Path
    ruta = Path(__file__).resolve().parent.parent / "scripts" / "configurar_triaje_atc.py"
    spec = importlib.util.spec_from_file_location("configurar_triaje_atc_res", ruta)
    ct = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ct)
    assert ct._cambios_desde(ct._argumentos(["--resultado", "otro"])) == {mem.CLAVE_TRIAJE_RESULTADO: "otro"}
    with pytest.raises(ValueError, match="--resultado"):
        ct._cambios_desde(ct._argumentos(["--resultado", "vendido"]))
    negocio, _ = await _negocio("da-y")
    r = await ct.main(["--negocio-id", negocio["id"]])
    assert r[mem.CLAVE_TRIAJE_RESULTADO] == "consulta_atc"
    r = await ct.main(["--negocio-id", negocio["id"], "--resultado", "otro"])
    assert r[mem.CLAVE_TRIAJE_RESULTADO] == "otro" and (await _get(negocio))["resultado"] == "otro"
