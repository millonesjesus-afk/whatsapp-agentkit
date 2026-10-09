# tests/test_configuracion_metricas.py — 2026-10-09, decisión del dueño: "debe haber alguna parte de configuración de
# métricas". El cliente decide desde el panel si las consultas de atención al cliente (`consulta_atc`) cuentan en el
# denominador de la tasa de cierre. GET/POST /dashboard/configuracion/metricas.json: solo Admin, CSRF, del negocio de la
# sesión, validación estricta, todo o nada, con historial de cambios. Además: el aviso "sin oportunidades" de Analítica
# no engaña cuando la exclusión deja la cifra comercial en 0 habiendo solo consultas.

import json
from datetime import datetime, timedelta

import pytest
from fastapi import HTTPException

from agent import dashboard
from agent import memory as mem

_n = {"i": 0}


async def _negocio(codigo: str):
    negocio = await mem.crear_negocio(f"Negocio {codigo}", codigo)
    _n["i"] += 1
    canal = await mem.crear_canal_whatsapp(nombre="C", phone_number_id=f"4088{_n['i']:06d}", negocio_id=negocio["id"])
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
    r = await dashboard.actualizar_configuracion_metricas_json(_Peticion(cuerpo), usuario=_admin(negocio, username), _csrf=None)
    return json.loads(r.body)


async def _get(negocio):
    return json.loads((await dashboard.configuracion_metricas_json(usuario=_admin(negocio))).body)


async def _consulta(negocio, canal, telefono, resultado="consulta_atc", creado=None):
    conv, opp = await mem.resolver_conversation_activa(telefono, negocio["id"], canal["id"])
    async with mem.async_session() as s:
        o = await s.get(mem.Opportunity, opp.id)
        o.resultado = resultado
        if creado is not None:
            o.creado = creado
        await s.commit()
    return opp


# ── GET ──────────────────────────────────────────────────────────────────

async def test_get_por_defecto_esta_apagado_sin_fecha_y_trae_contexto():
    negocio, canal = await _negocio("cm-a")
    estado = await _get(negocio)
    assert estado["excluir_consulta_atc"] is False and estado["excluir_desde"] is None
    assert estado["consultas_atc_ultimos_30_dias"] == {"dias": 30, "consultas": 0, "oportunidades": 0, "porcentaje": None}


async def test_get_cuenta_las_consultas_de_los_ultimos_30_dias_aunque_la_exclusion_este_apagada():
    negocio, canal = await _negocio("cm-b")
    await _consulta(negocio, canal, "51940000001")
    await _consulta(negocio, canal, "51940000002")
    await _consulta(negocio, canal, "51940000003", resultado=None)
    await _consulta(negocio, canal, "51940000004", creado=datetime.utcnow() - timedelta(days=45))   # fuera de la ventana
    await _consulta(negocio, canal, "51940000005", resultado=None, creado=datetime.utcnow() - timedelta(days=45))
    estado = await _get(negocio)
    assert estado["excluir_consulta_atc"] is False
    assert estado["consultas_atc_ultimos_30_dias"] == {"dias": 30, "consultas": 2, "oportunidades": 3, "porcentaje": 66.7}


async def test_get_es_del_negocio_de_la_sesion():
    a, canal_a = await _negocio("cm-c1")
    b, _ = await _negocio("cm-c2")
    await _consulta(a, canal_a, "51940000011")
    await _post(a, {"excluir_consulta_atc": True, "excluir_desde": "2026-10-09"})
    estado_b = await _get(b)
    assert estado_b["excluir_consulta_atc"] is False and estado_b["excluir_desde"] is None
    assert estado_b["consultas_atc_ultimos_30_dias"]["consultas"] == 0


async def test_get_ignora_un_corte_guardado_que_no_es_fecha_valida():
    negocio, _ = await _negocio("cm-d")
    await mem.guardar_configuracion(mem.CLAVE_METRICAS_EXCLUIR_ATC_DESDE, "no-es-fecha", negocio_id=negocio["id"])
    assert (await _get(negocio))["excluir_desde"] is None


async def test_get_sigue_funcionando_si_el_conteo_de_contexto_falla(monkeypatch):
    negocio, _ = await _negocio("cm-e")

    async def explota(*a, **k):
        raise RuntimeError("base lenta")

    monkeypatch.setattr(mem, "contar_consultas_atc_recientes", explota)
    estado = await _get(negocio)
    assert estado["excluir_consulta_atc"] is False and estado["consultas_atc_ultimos_30_dias"] is None


# ── POST: guarda y se refleja en el cálculo real ─────────────────────────

async def test_post_guarda_y_el_embudo_lo_usa_enseguida():
    negocio, canal = await _negocio("cm-f")
    await _consulta(negocio, canal, "51940000021")
    await _consulta(negocio, canal, "51940000022", resultado=None)
    dia = (datetime.utcnow() - timedelta(hours=5)).strftime("%Y-%m-%d")
    inicio, fin = mem.rango_periodo_utc(dia, dia)
    assert (await mem.calcular_embudo_comercial(negocio["id"], inicio, fin))["oportunidades"] == 2

    cuerpo = await _post(negocio, {"excluir_consulta_atc": True, "excluir_desde": "2026-10-01"})
    assert cuerpo["ok"] is True and cuerpo["excluir_consulta_atc"] is True and cuerpo["excluir_desde"] == "2026-10-01"
    assert cuerpo["modificadas"] == [mem.CLAVE_METRICAS_EXCLUIR_ATC, mem.CLAVE_METRICAS_EXCLUIR_ATC_DESDE]
    assert (await _get(negocio))["excluir_desde"] == "2026-10-01"

    embudo = await mem.calcular_embudo_comercial(negocio["id"], inicio, fin)
    assert embudo["oportunidades"] == 1 and embudo["oportunidades_brutas"] == 2 and embudo["excluye_consulta_atc"] is True

    cuerpo = await _post(negocio, {"excluir_consulta_atc": False, "excluir_desde": None})
    assert cuerpo["excluir_consulta_atc"] is False and cuerpo["excluir_desde"] is None
    assert await mem.calcular_embudo_comercial(negocio["id"], inicio, fin) == {"oportunidades": 2, "ventas": 0, "tasa_cierre": 0.0}


async def test_sin_excluir_desde_en_el_cuerpo_se_deja_la_fecha_que_habia():
    negocio, _ = await _negocio("cm-g")
    await _post(negocio, {"excluir_consulta_atc": True, "excluir_desde": "2026-10-05"})
    cuerpo = await _post(negocio, {"excluir_consulta_atc": False})
    assert cuerpo["excluir_consulta_atc"] is False and cuerpo["excluir_desde"] == "2026-10-05"
    assert cuerpo["modificadas"] == [mem.CLAVE_METRICAS_EXCLUIR_ATC]
    assert (await _post(negocio, {"excluir_consulta_atc": False, "excluir_desde": ""}))["excluir_desde"] is None


async def test_guardar_lo_mismo_no_cambia_nada_ni_ensucia_el_historial():
    negocio, _ = await _negocio("cm-h")
    assert (await _post(negocio, {"excluir_consulta_atc": False}))["modificadas"] == []       # ya era el valor por defecto
    await _post(negocio, {"excluir_consulta_atc": True})
    assert (await _post(negocio, {"excluir_consulta_atc": True}))["modificadas"] == []
    assert len(await mem.listar_cambios_configuracion(negocio["id"])) == 1


async def test_el_cambio_queda_en_el_historial_con_quien_antes_y_despues():
    negocio, _ = await _negocio("cm-i")
    await _post(negocio, {"excluir_consulta_atc": True, "excluir_desde": "2026-10-09"}, username="lucia")
    await _post(negocio, {"excluir_consulta_atc": False}, username="mario")
    cambios = await mem.listar_cambios_configuracion(negocio["id"])
    assert [c["actor"] for c in cambios] == ["mario", "lucia"]
    assert all(c["accion"] == "metricas_configuracion" for c in cambios)
    assert cambios[0]["cambios"] == {mem.CLAVE_METRICAS_EXCLUIR_ATC: {"antes": "1", "despues": "0"}}
    assert cambios[1]["cambios"] == {
        mem.CLAVE_METRICAS_EXCLUIR_ATC: {"antes": None, "despues": "1"},
        mem.CLAVE_METRICAS_EXCLUIR_ATC_DESDE: {"antes": None, "despues": "2026-10-09"},
    }


# ── POST: validación, todo o nada ────────────────────────────────────────

@pytest.mark.parametrize("cuerpo", [
    {}, {"excluir_consulta_atc": "1"}, {"excluir_consulta_atc": 1}, {"excluir_consulta_atc": None},
    {"excluir_consulta_atc": True, "excluir_desde": "09/10/2026"},
    {"excluir_consulta_atc": True, "excluir_desde": "2026-13-45"},
    {"excluir_consulta_atc": True, "excluir_desde": "2026-10-09T10:00"},
    {"excluir_consulta_atc": True, "excluir_desde": "1999-01-01"},
    {"excluir_consulta_atc": True, "excluir_desde": 20261009},
    ["no", "es", "objeto"], "texto",
])
async def test_post_rechaza_lo_invalido_y_no_guarda_nada(cuerpo):
    negocio, _ = await _negocio("cm-j")
    with pytest.raises(HTTPException) as e:
        await _post(negocio, cuerpo)
    assert e.value.status_code == 400
    estado = await _get(negocio)
    assert estado["excluir_consulta_atc"] is False and estado["excluir_desde"] is None
    assert await mem.listar_cambios_configuracion(negocio["id"]) == []


async def test_post_con_cuerpo_que_no_es_json_responde_400():
    negocio, _ = await _negocio("cm-k")
    with pytest.raises(HTTPException) as e:
        await _post(negocio, ValueError("no json"))
    assert e.value.status_code == 400


async def test_un_dato_invalido_en_la_fecha_no_deja_guardado_el_interruptor():
    negocio, _ = await _negocio("cm-l")
    with pytest.raises(HTTPException):
        await _post(negocio, {"excluir_consulta_atc": True, "excluir_desde": "mañana"})
    assert (await _get(negocio))["excluir_consulta_atc"] is False


async def test_el_negocio_sale_de_la_sesion_no_del_cuerpo():
    a, _ = await _negocio("cm-m1")
    b, _ = await _negocio("cm-m2")
    await _post(a, {"excluir_consulta_atc": True, "negocio_id": b["id"]})
    assert (await _get(a))["excluir_consulta_atc"] is True
    assert (await _get(b))["excluir_consulta_atc"] is False


# ── Rutas: solo Admin, CSRF en el POST ───────────────────────────────────

def _ruta(metodo):
    return next(r for r in dashboard.router.routes if getattr(r, "path", "").endswith("/configuracion/metricas.json") and metodo in r.methods)


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


# ── Aviso de Analítica con la exclusión activa ───────────────────────────

_VALOR = {"monto": "0", "ventas_excluidas": 0}


def test_senal_sin_oportunidades_clasica_no_cambia():
    senales = dashboard._senales_analitica_p0({"leads": 0, "conversaciones": 0, "oportunidades": 0, "ventas": 0}, _VALOR)
    assert senales == [{"tipo": "sin_oportunidades", "texto": "No se registraron oportunidades en este período."}]


@pytest.mark.parametrize("consultas, frase", [
    (1, "el único contacto fue una consulta de atención al cliente"),
    (3, "los 3 contactos fueron consultas de atención al cliente"),
])
def test_senal_cuando_la_exclusion_deja_la_cifra_comercial_en_cero_habiendo_solo_consultas(consultas, frase):
    flujo = {
        "leads": consultas, "conversaciones": consultas, "oportunidades": 0, "ventas": 0, "oportunidades_brutas": consultas,
        "consultas_no_comerciales": {"cantidad": consultas, "porcentaje_de_contactos": 100.0, "excluidas_desde": None},
    }
    [senal] = dashboard._senales_analitica_p0(flujo, _VALOR)
    assert senal["tipo"] == "sin_oportunidades"
    assert senal["texto"].startswith("No se registraron oportunidades comerciales en este período")
    assert frase in senal["texto"]


def test_senal_no_aparece_si_hay_oportunidades_comerciales():
    flujo = {
        "leads": 5, "conversaciones": 5, "oportunidades": 2, "ventas": 0, "oportunidades_brutas": 5,
        "consultas_no_comerciales": {"cantidad": 3, "porcentaje_de_contactos": 60.0, "excluidas_desde": None},
    }
    assert dashboard._senales_analitica_p0(flujo, _VALOR) == []
