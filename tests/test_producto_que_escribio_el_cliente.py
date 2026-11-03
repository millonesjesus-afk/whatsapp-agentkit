# tests/test_producto_que_escribio_el_cliente.py — Lo que el cliente ESCRIBE pesa más que el anuncio por el que llegó (2026-11-03).
#
# Caso real (chat ff3ad16c): llegó por el anuncio «Estratek - Reel Secadora», escribió «Buen día cuentan con cocina» y «Para cocina», y
# el flujo guiado siguió preguntando «¿ya tienes el punto de gas para conectar tu secadora?», porque juntaba el anuncio y sus palabras
# en un solo texto y «secadora» ganaba por orden de prioridad.
import pytest

from agent import calificacion_guiada as cg

ANUNCIO_SECADORA = ["Estratek - Reel Secadora", "Se paga en tu recibo Cálidda", "La secadora la dejaste para «cuando se pueda»"]


def test_el_caso_real_pide_cocina_y_el_anuncio_era_de_secadora():
    assert cg.tipo_con_prioridad_al_cliente(ANUNCIO_SECADORA, ["Buen día cuentan con cocina", "Sí, ya tengo", "Para cocina"]) == "cocina"


@pytest.mark.parametrize("del_cliente", [
    ["Hola"], ["Sí, ya tengo"], ["Buen día", "Sí, ya tengo", "No tengo punto"], [],
])
def test_si_sus_palabras_no_nombran_un_producto_vale_el_anuncio(del_cliente):
    assert cg.tipo_con_prioridad_al_cliente(ANUNCIO_SECADORA, del_cliente) == "secadora"


def test_si_escribe_lo_mismo_que_el_anuncio_no_cambia_nada():
    assert cg.tipo_con_prioridad_al_cliente(ANUNCIO_SECADORA, ["Estoy interesado en financiar una Secadora"]) == "secadora"


def test_el_producto_del_cliente_gana_aunque_el_anuncio_sea_de_terma():
    assert cg.tipo_con_prioridad_al_cliente(["Reel Terma", "calentador de agua"], ["quiero un centro de lavado"]) == "lavado"


def test_sin_anuncio_ni_palabras_es_otro():
    assert cg.tipo_con_prioridad_al_cliente([], ["Hola buenas"]) == "otro"
