# tests/test_triaje_atc_configuracion.py — scripts/configurar_triaje_atc.py (2026-10-08): fija las claves de
# configuración del triaje ATC y de la métrica del embudo, por negocio, con validación; sin opciones solo muestra.

import importlib.util
from pathlib import Path

import pytest

from agent import memory as mem
from agent import triaje_atc as t


def _cargar_script():
    ruta = Path(__file__).resolve().parent.parent / "scripts" / "configurar_triaje_atc.py"
    spec = importlib.util.spec_from_file_location("configurar_triaje_atc", ruta)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


ct = _cargar_script()


def _cambios(*argv):
    return ct._cambios_desde(ct._argumentos(list(argv)))


async def _negocio(codigo):
    return (await mem.crear_negocio(f"Negocio {codigo}", codigo))["id"]


async def test_sin_opciones_solo_muestra_y_no_escribe_nada(capsys):
    nid = await _negocio("cfg-a")
    r = await ct.main(["--negocio-id", nid])
    assert r["modo_configurado"] == "apagado" and r["modo_efectivo"] == "apagado"
    assert r[t.CLAVE_LINEA] is None and r[t.CLAVE_CATEGORIAS] == "recibo,numero_cliente,pago_deuda" and r[t.CLAVE_MAX_MENSAJES] == "4"
    assert r["metricas_excluir_consulta_atc"] is False
    assert "<FALTA --linea>" in r["vista_previa_texto"]
    assert "negocio_id" in capsys.readouterr().out
    assert await mem.obtener_configuracion(t.CLAVE_MODO, "sin-fijar", negocio_id=nid) == "sin-fijar"


async def test_el_paso_a_paso_de_la_activacion():
    nid = await _negocio("cfg-b")
    # 1) líneas
    r = await ct.main([
        "--negocio-id", nid, "--linea", "614900, opción 5", "--linea-emergencia", "1808 (Emergencias 24/7)", "--linea-ventas", "614-9002",
    ])
    assert r[t.CLAVE_LINEA] == "614900, opción 5" and r[t.CLAVE_LINEA_EMERGENCIA] == "1808 (Emergencias 24/7)" and r[t.CLAVE_LINEA_VENTAS] == "614-9002"
    assert r["modo_configurado"] == "apagado"                      # fijar líneas NO enciende nada
    assert r["vista_previa_texto"].startswith("¡Hola Yasmin! 😊") and "614900, opción 5" in r["vista_previa_texto"]
    # 2) sombra
    r = await ct.main(["--negocio-id", nid, "--modo", "sombra"])
    assert (r["modo_configurado"], r["modo_efectivo"]) == ("sombra", "sombra")
    assert await mem.obtener_configuracion(t.CLAVE_MODO, "", negocio_id=nid) == "sombra"
    # 3) activo y vuelta a apagado
    r = await ct.main(["--negocio-id", nid, "--modo", "activo"])
    assert (r["modo_configurado"], r["modo_efectivo"]) == ("activo", "activo")
    r = await ct.main(["--negocio-id", nid, "--modo", "apagado"])
    assert r["modo_efectivo"] == "apagado"


async def test_no_se_puede_activar_sin_la_linea_de_atencion():
    nid = await _negocio("cfg-c")
    with pytest.raises(ValueError, match="línea de atención"):
        await ct.main(["--negocio-id", nid, "--modo", "activo"])
    assert await mem.obtener_configuracion(t.CLAVE_MODO, "sin-fijar", negocio_id=nid) == "sin-fijar"
    # activar y poner la línea en el mismo comando sí
    r = await ct.main(["--negocio-id", nid, "--modo", "activo", "--linea", "614900, opción 5"])
    assert r["modo_efectivo"] == "activo"


async def test_las_claves_se_guardan_por_negocio():
    a, b = await _negocio("cfg-d1"), await _negocio("cfg-d2")
    await ct.main(["--negocio-id", a, "--modo", "sombra", "--max-mensajes", "6", "--nombre-negocio", "Cálidda Hogar"])
    ra, rb = await ct.estado(a), await ct.estado(b)
    assert ra["modo_configurado"] == "sombra" and ra[t.CLAVE_MAX_MENSAJES] == "6" and ra[t.CLAVE_NOMBRE_NEGOCIO] == "Cálidda Hogar"
    assert rb["modo_configurado"] == "apagado" and rb[t.CLAVE_MAX_MENSAJES] == "4" and "fallback" in rb[t.CLAVE_NOMBRE_NEGOCIO]


async def test_la_metrica_del_embudo_se_configura_con_el_mismo_script():
    nid = await _negocio("cfg-e")
    r = await ct.main(["--negocio-id", nid, "--excluir-consulta-atc", "1", "--excluir-desde", "2026-10-09"])
    assert r["metricas_excluir_consulta_atc"] is True and r["metricas_excluir_consulta_atc_desde"] == "2026-10-09"
    assert (await mem.obtener_politica_metricas(nid))["desde"] is not None
    r = await ct.main(["--negocio-id", nid, "--excluir-consulta-atc", "0", "--excluir-desde", ""])
    assert r["metricas_excluir_consulta_atc"] is False and r["metricas_excluir_consulta_atc_desde"] is None


@pytest.mark.parametrize("argv, mensaje", [
    (["--categorias", "recibo,inventada"], "--categorias"),
    (["--categorias", ""], "--categorias"),
    (["--max-mensajes", "0"], "--max-mensajes"),
    (["--max-mensajes", "99"], "--max-mensajes"),
    (["--excluir-desde", "09/10/2026"], "--excluir-desde"),
    (["--telefonos-excluidos", "123"], "--telefonos-excluidos"),
    (["--linea", "x" * 200], "--linea"),
    (["--texto-categoria", "recibo sin igual"], "--texto-categoria"),
    (["--texto-categoria", "emergencia_gas=Hola {linea_atc}"], "--texto-categoria"),
])
def test_valores_invalidos_se_rechazan(argv, mensaje):
    with pytest.raises(ValueError, match=mensaje):
        _cambios(*argv)


@pytest.mark.parametrize("texto", [
    "¡Hola! ¿Necesitas algo más?",                                  # lleva «?»
    "Llámanos a la línea {linea_atc} y te atendemos.",              # «llam…»
    "Envíanos tu DNI a la línea {linea_atc}.",                      # envi… + dni
    "Te avisamos cuando tengamos novedades en {linea_atc}.",        # avis…
    "Atendemos de lunes a viernes en la línea {linea_atc}.",        # día de la semana
    "Atendemos a las 9 en la línea {linea_atc}.",                   # hora
    "x" * 700,
])
def test_un_texto_que_dejaria_algo_pendiente_o_es_largo_se_rechaza(texto):
    with pytest.raises(ValueError):
        _cambios("--texto", texto)


def test_un_texto_valido_se_acepta_y_el_por_defecto_tambien_lo_es():
    assert _cambios("--texto", "Hola{nombre}, en {negocio} la línea {linea_atc} resuelve tu recibo.") == {
        t.CLAVE_TEXTO: "Hola{nombre}, en {negocio} la línea {linea_atc} resuelve tu recibo.",
    }
    assert ct.validar_texto(t.TEXTO_POR_DEFECTO, "defecto") == t.TEXTO_POR_DEFECTO
    assert _cambios("--texto", "") == {t.CLAVE_TEXTO: ""}                 # vacío = volver al texto por defecto


def test_categorias_telefonos_y_textos_por_categoria():
    c = _cambios(
        "--categorias", "Recibo, pago_deuda, recibo", "--telefonos-excluidos", "+51 999 888 777; 51988777666",
        "--texto-categoria", "recibo=En {negocio}, el recibo lo resuelve la línea {linea_atc}.", "--permitir-canal-pruebas", "1",
    )
    assert c[t.CLAVE_CATEGORIAS] == "recibo,pago_deuda"
    assert c[t.CLAVE_TELEFONOS_EXCLUIDOS] == "51999888777,51988777666"
    assert c[t.CLAVE_TEXTO_CATEGORIA + "recibo"].startswith("En {negocio}")
    assert c[t.CLAVE_PERMITIR_CANAL_PRUEBAS] == "1"


def test_resolver_negocio_id():
    uno = [{"id": "a", "nombre": "A", "activo": True}]
    dos = uno + [{"id": "b", "nombre": "B", "activo": True}]
    assert ct.resolver_negocio_id(None, uno) == "a" and ct.resolver_negocio_id("z", dos) == "z"
    with pytest.raises(ValueError, match="--negocio-id"):
        ct.resolver_negocio_id(None, dos)


# ── Emergencia de gas (2026-10-09): interruptor propio, texto y validaciones ─────────────────────

async def test_el_interruptor_de_emergencia_es_independiente_y_el_activo_exige_la_linea_de_emergencia():
    nid = await _negocio("cfg-em-a")
    r = await ct.main(["--negocio-id", nid])
    assert r["emergencia_modo_configurado"] == "apagado" and r["emergencia_modo_efectivo"] == "apagado"
    assert r[t.CLAVE_EMERGENCIA_TEXTO] == "(texto por defecto del módulo)"
    assert "<FALTA --linea-emergencia>" in r["vista_previa_emergencia"]
    with pytest.raises(ValueError, match="línea de emergencia"):
        await ct.main(["--negocio-id", nid, "--emergencia-modo", "activo"])
    assert await mem.obtener_configuracion(t.CLAVE_EMERGENCIA_MODO, "sin-fijar", negocio_id=nid) == "sin-fijar"
    # sombra no exige nada; activo + línea en el mismo comando sí se acepta; el modo general NO cambia
    r = await ct.main(["--negocio-id", nid, "--emergencia-modo", "sombra"])
    assert (r["emergencia_modo_configurado"], r["emergencia_modo_efectivo"], r["modo_configurado"]) == ("sombra", "sombra", "apagado")
    r = await ct.main(["--negocio-id", nid, "--emergencia-modo", "activo", "--linea-emergencia", "1808 (Emergencias 24/7)"])
    assert (r["emergencia_modo_configurado"], r["emergencia_modo_efectivo"], r["modo_configurado"]) == ("activo", "activo", "apagado")
    assert "1808 (Emergencias 24/7)" in r["vista_previa_emergencia"] and "{" not in r["vista_previa_emergencia"]
    assert (await ct.main(["--negocio-id", nid, "--emergencia-modo", "apagado"]))["emergencia_modo_efectivo"] == "apagado"


async def test_el_activo_con_un_texto_propio_que_ya_trae_el_numero_no_exige_la_clave_de_la_linea():
    nid = await _negocio("cfg-em-b")
    r = await ct.main([
        "--negocio-id", nid, "--emergencia-modo", "activo", "--emergencia-texto", "Sal ya y comunícate con Cálidda al 1808.",
        "--linea-emergencia", "1808",
    ])
    assert r["emergencia_modo_efectivo"] == "activo" and r[t.CLAVE_EMERGENCIA_TEXTO].startswith("Sal ya")


@pytest.mark.parametrize("texto", [
    "Sal de la casa. ¿Necesitas ayuda?",                   # «?»
    "Sal de la casa y llama a Emergencias.",               # sin la línea de emergencia
    "x" * 700 + " {linea_emergencia}",                      # largo
])
def test_un_texto_de_emergencia_invalido_se_rechaza(texto):
    with pytest.raises(ValueError, match="--emergencia-texto"):
        _cambios("--emergencia-texto", texto)


def test_el_texto_de_emergencia_por_defecto_y_los_propios_se_aceptan_y_llama_solo_advierte():
    avisos: list[str] = []
    c = ct._cambios_desde(ct._argumentos(["--emergencia-texto", t.TEXTO_EMERGENCIA_POR_DEFECTO]), avisos)
    assert c == {t.CLAVE_EMERGENCIA_TEXTO: t.TEXTO_EMERGENCIA_POR_DEFECTO} and avisos == []
    # «llama» no se rechaza (la regla de palabras prohibidas no aplica a este texto) pero avisa: un «ok» reabriría el caso
    c = ct._cambios_desde(ct._argumentos(["--emergencia-texto", "Llama ya a Emergencias: {linea_emergencia}."]), avisos)
    assert c[t.CLAVE_EMERGENCIA_TEXTO].startswith("Llama") and len(avisos) == 1 and "ok" in avisos[0]
    assert _cambios("--emergencia-texto", "") == {t.CLAVE_EMERGENCIA_TEXTO: ""}            # vacío = texto por defecto
    assert _cambios("--emergencia-modo", "sombra") == {t.CLAVE_EMERGENCIA_MODO: "sombra"}


def test_el_modo_de_emergencia_invalido_se_rechaza():
    with pytest.raises(SystemExit):
        _cambios("--emergencia-modo", "encendido")
