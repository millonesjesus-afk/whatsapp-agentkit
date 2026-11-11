# tests/test_politica_password.py — política de contraseñas (2026-11-03): 12 caracteres, sin reglas de composición,
# sin claves comunes ni datos de la cuenta. Datos sintéticos únicamente.

import secrets

import pytest

from agent.politica_password import LARGO_MAXIMO, LARGO_MINIMO, validar_password


@pytest.mark.parametrize("clave", [
    "una frase larga y facil de recordar",
    "tortuga-azul-bicicleta",
    "solo minusculas pero largas",
    "x" * 11 + "y",                 # 12 caracteres, no es un solo carácter repetido
    "a" * 0 + "Zq7!mK2$vN9#",       # compleja
])
def test_acepta_claves_largas_sin_exigir_composicion(clave):
    assert validar_password(clave, username="ana", nombre="Ana Perez") is None


@pytest.mark.parametrize("clave,fragmento", [
    ("corta123", "al menos 12"),
    ("a" * (LARGO_MINIMO - 1), "al menos 12"),
    ("a" * (LARGO_MAXIMO + 1), "superar"),
    ("aaaaaaaaaaaa", "muy común"),
    ("abcdefghijkl", "muy común"),
    ("123456789012", "muy común"),
    ("Contraseña 123", "muy común"),      # con mayúsculas, tilde y espacio sigue siendo común
    ("mi-Maiek-secreta-77", "producto"),
    ("pepito1234567890", "usuario"),
    ("clave de Ana Perez!!", "nombre"),
])
def test_rechaza_con_motivo_claro(clave, fragmento):
    motivo = validar_password(clave, username="pepito", nombre="Ana Perez")
    assert motivo is not None and fragmento in motivo


def test_datos_cortos_de_la_cuenta_no_bloquean_por_error():
    # Un usuario de 2 letras no puede prohibir toda clave que lo contenga.
    assert validar_password("tortuga-azul-bicicleta", username="al", nombre="Jo") is None


def test_las_contrasenas_que_genera_el_sistema_cumplen_la_politica():
    for _ in range(200):
        assert validar_password(secrets.token_urlsafe(9)) is None


# Las pruebas de la ruta de Mi perfil (antes el formulario `/perfil/password` del panel viejo) viven en
# tests/test_perfil_password_sesiones.py desde 2026-11-11: misma intención, ruta JSON nueva.
