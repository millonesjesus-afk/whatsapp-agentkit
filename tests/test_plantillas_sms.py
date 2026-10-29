# tests/test_plantillas_sms.py — Plantillas de SMS propias de cada negocio (2026-10-29, parte 2).
#
# Una plantilla es un texto con variables ({negocio} {rubro} {producto} {precio}, [[ trozo opcional ]] y [enlace]).
# Se guardan una por clave (el valor de Configuracion admite 1000 caracteres), aisladas por negocio, y solo las edita el
# Admin. La opción «el remitente ya muestra el nombre del negocio» es por negocio.

import inspect
import json

import pytest
from fastapi import HTTPException

from agent import dashboard, memory as mem, plantillas_sms as ps

OK_PRODUCTO = "{producto}[[ desde {precio}]], financiado y sin inicial. Escribenos aqui: [enlace]"
OK_NEGOCIO = "Encuentra {rubro} en cuotas. Escribenos aqui: [enlace]"


class _RequestFalso:
    def __init__(self, payload):
        self._payload = payload

    async def json(self):
        return self._payload


def _cuerpo(respuesta) -> dict:
    return json.loads(respuesta.body)


def _dependencia_usuario(func):
    return inspect.signature(func).parameters["usuario"].default.dependency


# ── Validación ───────────────────────────────────────────────────────────────

@pytest.mark.parametrize("alcance,texto", [("producto", OK_PRODUCTO), ("negocio", OK_NEGOCIO), ("producto", "Hola {producto}. Aqui: [enlace]")])
def test_plantillas_validas(alcance, texto):
    assert ps.validar_plantilla(alcance, texto) is None


@pytest.mark.parametrize("alcance,texto,pista", [
    ("otro", OK_PRODUCTO, "para qué envíos"),
    ("producto", "corto", "al menos"),
    ("producto", "x" * 301 + " {producto} [enlace]", "hasta 300"),
    ("producto", "Mira {produto}. Escribenos aqui: [enlace]", "{produto}"),
    ("producto", "Mira {producto. Escribenos aqui: [enlace]", "llave"),
    ("producto", "Mira {producto}[[ desde {precio}. Escribenos aqui: [enlace]", "opcionales"),
    ("producto", "Mira {producto}. Escribenos aqui", "[enlace]"),
    ("producto", "Mira {producto}. Aqui: [enlace] o aqui: [enlace]", "[enlace]"),
    ("producto", "Encuentra {rubro} en cuotas. Aqui: [enlace]", "{producto}"),
    ("negocio", "Mira {producto} desde {precio}. Aqui: [enlace]", "no puede usar"),
])
def test_plantillas_invalidas_dicen_por_que(alcance, texto, pista):
    error = ps.validar_plantilla(alcance, texto)
    assert error and pista in error


# ── Guardar, editar, eliminar ────────────────────────────────────────────────

async def test_se_crea_edita_y_elimina_una_plantilla_y_queda_auditada():
    negocio = await mem.crear_negocio("Negocio ps-crud", "ps-crud")
    creada = await ps.guardar(negocio["id"], "admin", "producto", OK_PRODUCTO)
    assert creada["alcance"] == "producto" and creada["creado_por"] == "admin"
    assert [p["id"] for p in await ps.listar(negocio["id"])] == [creada["id"]]

    editada = await ps.guardar(negocio["id"], "admin", "producto", "{producto} a {precio}. Mas info: [enlace]", creada["id"])
    assert editada["id"] == creada["id"] and editada["creado"] == creada["creado"]
    lista = await ps.listar(negocio["id"])
    assert len(lista) == 1 and lista[0]["texto"] == "{producto} a {precio}. Mas info: [enlace]"

    await ps.eliminar(negocio["id"], "admin", creada["id"])
    assert await ps.listar(negocio["id"]) == []
    with pytest.raises(LookupError):
        await ps.eliminar(negocio["id"], "admin", creada["id"])


async def test_espacios_de_mas_se_limpian_y_no_se_repite_una_plantilla_igual():
    negocio = await mem.crear_negocio("Negocio ps-dup", "ps-dup")
    await ps.guardar(negocio["id"], "admin", "negocio", "  Encuentra   {rubro}  en cuotas.   Aqui: [enlace] ")
    assert (await ps.listar(negocio["id"]))[0]["texto"] == "Encuentra {rubro} en cuotas. Aqui: [enlace]"
    with pytest.raises(ValueError, match="igual"):
        await ps.guardar(negocio["id"], "admin", "negocio", "Encuentra {rubro} en cuotas. Aqui: [enlace]")


async def test_una_plantilla_invalida_no_se_guarda():
    negocio = await mem.crear_negocio("Negocio ps-inv", "ps-inv")
    with pytest.raises(ValueError, match=r"\[enlace\]"):
        await ps.guardar(negocio["id"], "admin", "producto", "Mira {producto} sin enlace aqui")
    assert await ps.listar(negocio["id"]) == []


async def test_el_maximo_de_plantillas_por_negocio():
    negocio = await mem.crear_negocio("Negocio ps-max", "ps-max")
    for n in range(ps.MAXIMO_PLANTILLAS):
        await ps.guardar(negocio["id"], "admin", "producto", f"Oferta {n} de {{producto}}. Aqui: [enlace]")
    with pytest.raises(ValueError, match="Elimina alguna"):
        await ps.guardar(negocio["id"], "admin", "producto", "Una mas {producto}. Aqui: [enlace]")


async def test_una_plantilla_del_largo_maximo_cabe_en_el_valor_de_configuracion():
    """Configuracion.valor admite 1000 caracteres: la plantilla más larga, con su metadato, tiene que caber."""
    negocio = await mem.crear_negocio("Negocio ps-largo", "ps-largo")
    texto = ("a" * (ps.LARGO_MAXIMO - len(" {producto} [enlace]"))) + " {producto} [enlace]"
    assert len(texto) == ps.LARGO_MAXIMO
    creada = await ps.guardar(negocio["id"], "x" * 50, "producto", texto)
    valor = (await mem.listar_configuracion_por_prefijo(ps.PREFIJO_CLAVE, negocio["id"]))[ps.PREFIJO_CLAVE + creada["id"]]
    assert len(valor) < 1000


async def test_las_plantillas_estan_aisladas_por_negocio():
    uno = await mem.crear_negocio("Negocio ps-a", "ps-a")
    otro = await mem.crear_negocio("Negocio ps-b", "ps-b")
    creada = await ps.guardar(uno["id"], "admin", "negocio", OK_NEGOCIO)
    assert await ps.listar(otro["id"]) == []
    with pytest.raises(LookupError):
        await ps.eliminar(otro["id"], "admin", creada["id"])
    with pytest.raises(LookupError):
        await ps.guardar(otro["id"], "admin", "negocio", OK_NEGOCIO, creada["id"])
    assert len(await ps.listar(uno["id"])) == 1


async def test_una_fila_danada_se_ignora_sin_romper_la_lista():
    negocio = await mem.crear_negocio("Negocio ps-mala", "ps-mala")
    await ps.guardar(negocio["id"], "admin", "negocio", OK_NEGOCIO)
    await mem.guardar_configuracion(ps.PREFIJO_CLAVE + "rota", "esto no es json", negocio_id=negocio["id"])
    await mem.guardar_configuracion(ps.PREFIJO_CLAVE + "rara", json.dumps({"alcance": "x", "texto": 3}), negocio_id=negocio["id"])
    assert len(await ps.listar(negocio["id"])) == 1


# ── Remitente ────────────────────────────────────────────────────────────────

async def test_el_remitente_es_por_negocio_y_el_cambio_se_audita_una_sola_vez():
    uno = await mem.crear_negocio("Negocio ps-rem-a", "ps-rem-a")
    otro = await mem.crear_negocio("Negocio ps-rem-b", "ps-rem-b")
    assert await ps.remitente_muestra_negocio(uno["id"]) is False
    assert await ps.fijar_remitente(uno["id"], "admin", True) is True
    assert await ps.fijar_remitente(uno["id"], "admin", True) is False   # ya estaba así
    assert await ps.remitente_muestra_negocio(uno["id"]) is True
    assert await ps.remitente_muestra_negocio(otro["id"]) is False
    assert (await ps.estado(uno["id"]))["remitente_muestra_negocio"] is True


# ── Rutas del panel ──────────────────────────────────────────────────────────

async def test_las_rutas_son_solo_admin():
    for ruta in (dashboard.configuracion_sms_json, dashboard.actualizar_configuracion_sms_json):
        verificar = _dependencia_usuario(ruta)
        assert (await verificar(usuario={"rol": "admin"}))["rol"] == "admin"
        for rol in ("supervisor", "asesor"):
            with pytest.raises(HTTPException) as error:
                await verificar(usuario={"rol": rol})
            assert error.value.status_code in (401, 403)


async def test_la_ruta_guarda_edita_elimina_y_cambia_el_remitente():
    negocio = await mem.crear_negocio("Negocio ps-ruta", "ps-ruta")
    usuario = {"negocio_id": negocio["id"], "rol": "admin", "username": "jesus"}

    async def llamar(cuerpo):
        return _cuerpo(await dashboard.actualizar_configuracion_sms_json(_RequestFalso(cuerpo), usuario=usuario, _csrf=None))

    estado = await llamar({"accion": "guardar", "alcance": "negocio", "texto": OK_NEGOCIO})
    assert estado["negocio"] == "Negocio ps-ruta" and len(estado["plantillas"]) == 1
    plantilla_id = estado["plantillas"][0]["id"]
    assert estado["plantillas"][0]["creado_por"] == "jesus"

    estado = await llamar({"accion": "guardar", "id": plantilla_id, "alcance": "negocio", "texto": "Tenemos {rubro}. Aqui: [enlace]"})
    assert estado["plantillas"][0]["texto"] == "Tenemos {rubro}. Aqui: [enlace]"

    estado = await llamar({"accion": "remitente", "muestra_negocio": True})
    assert estado["remitente_muestra_negocio"] is True

    estado = await llamar({"accion": "rubro", "rubro": "  gasodomésticos "})
    assert estado["rubro"] == "gasodomésticos"

    estado = await llamar({"accion": "eliminar", "id": plantilla_id})
    assert estado["plantillas"] == []


@pytest.mark.parametrize("indice,cuerpo,codigo", [
    (0, {"accion": "guardar", "alcance": "producto", "texto": "sin enlace {producto}"}, 400),
    (1, {"accion": "eliminar", "id": "no-existe"}, 404),
    (2, {"accion": "remitente", "muestra_negocio": "si"}, 400),
    (3, {"accion": "rubro", "rubro": "x" * 61}, 400),
    (4, {"accion": "borrar-todo"}, 400),
    (5, {}, 400),
])
async def test_la_ruta_rechaza_lo_invalido(indice, cuerpo, codigo):
    negocio = await mem.crear_negocio(f"Negocio ps-rech-{indice}", f"ps-rech-{indice}")
    usuario = {"negocio_id": negocio["id"], "rol": "admin"}
    with pytest.raises(HTTPException) as error:
        await dashboard.actualizar_configuracion_sms_json(_RequestFalso(cuerpo), usuario=usuario, _csrf=None)
    assert error.value.status_code == codigo


async def test_el_listado_de_campanas_trae_las_plantillas_y_el_remitente_para_el_formulario():
    negocio = await mem.crear_negocio("Negocio ps-camp", "ps-camp")
    await ps.guardar(negocio["id"], "admin", "producto", OK_PRODUCTO)
    await ps.fijar_remitente(negocio["id"], "admin", True)
    usuario = {"negocio_id": negocio["id"], "rol": "supervisor"}
    sms = _cuerpo(await dashboard.campanas_json(usuario=usuario))["negocio"]["sms"]
    assert sms["remitente_muestra_negocio"] is True
    assert [p["texto"] for p in sms["plantillas"]] == [OK_PRODUCTO]
