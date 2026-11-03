# tests/test_politica_password.py — política de contraseñas (2026-11-03): 12 caracteres, sin reglas de composición,
# sin claves comunes ni datos de la cuenta. Datos sintéticos únicamente.

import secrets
from urllib.parse import unquote_plus

import bcrypt
import pytest

from agent import dashboard, memory as mem
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


async def _admin(codigo):
    n = await mem.crear_negocio(f"Negocio {codigo}", codigo)
    await mem.crear_usuario(f"user_{codigo}", "ClaveActual-123456", "Usuario Prueba", "admin", n["id"])
    return await mem.obtener_usuario(f"user_{codigo}", negocio_id=n["id"])


async def _cambiar(usuario, nueva, repetir=None):
    return await dashboard.cambiar_password_propia(
        password_actual="ClaveActual-123456", password_nueva=nueva,
        password_nueva_repetir=nueva if repetir is None else repetir, usuario=usuario, _csrf=None,
    )


async def test_perfil_rechaza_clave_corta_y_no_la_guarda():
    u = await _admin("pw-1")
    r = await _cambiar(u, "corta123")
    assert "error=" in r.headers["location"] and "12" in unquote_plus(r.headers["location"])
    u2 = await mem.obtener_usuario(u["username"], negocio_id=u["negocio_id"])
    assert bcrypt.checkpw(b"ClaveActual-123456", u2["password_hash"].encode())


async def test_perfil_acepta_frase_larga_y_la_guarda():
    u = await _admin("pw-2")
    r = await _cambiar(u, "tortuga azul bicicleta roja")
    assert "ok=" in r.headers["location"]
    u2 = await mem.obtener_usuario(u["username"], negocio_id=u["negocio_id"])
    assert bcrypt.checkpw("tortuga azul bicicleta roja".encode(), u2["password_hash"].encode())


async def test_perfil_rechaza_si_no_coinciden_y_si_contiene_el_usuario():
    u = await _admin("pw-3")
    assert "coinciden" in unquote_plus((await _cambiar(u, "tortuga azul bicicleta", "otra distinta larga")).headers["location"])
    r = await _cambiar(u, "mi user_pw-3 secreta larga")
    assert "usuario" in unquote_plus(r.headers["location"])
