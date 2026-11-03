"""Política de contraseñas del panel (2026-11-03), basada en NIST SP 800-63B y OWASP ASVS: pesa el LARGO, no las
reglas de composición («una mayúscula y un símbolo» empuja a `Clave123!`, que es peor que una frase larga).

Reglas: mínimo `LARGO_MINIMO` y máximo `LARGO_MAXIMO` caracteres; sin lista de claves comunes; sin contener el usuario,
el nombre ni el nombre de la marca; sin ser un solo carácter repetido ni una secuencia obvia. NO exige letra, número ni
símbolo y NO caduca.

Se aplica donde una PERSONA elige su contraseña (`/perfil/password`). Las que genera el sistema (alta de cuenta y reset
de un admin: `secrets.token_urlsafe(9)`, 12 caracteres aleatorios) ya la cumplen. Las contraseñas ya guardadas están
cifradas y no se pueden evaluar: no se tocan; la regla vale al crear o cambiar una."""

import unicodedata

LARGO_MINIMO = 12
LARGO_MAXIMO = 128

# Las más usadas en español e inglés, ya con 12 o más caracteres (las más cortas las frena el largo mínimo) más
# variantes típicas. Se compara sin mayúsculas, espacios, guiones ni puntos.
_COMUNES = frozenset({
    "123456789012", "1234567890123", "123456789123", "contrasena123", "contrasena1234", "contrasenasegura",
    "passw0rd1234", "password1234", "password12345", "passwordpassword", "qwertyuiop12", "qwertyuiopas",
    "qwertyuiop123", "iloveyou1234", "administrador", "administrator", "administrador1", "administrador123",
    "bienvenido123", "bienvenida123", "welcome12345", "letmein12345", "mipassword123", "micontrasena",
    "micontrasena1", "micontrasena123", "peru123456789", "peru2026peru", "lima123456789", "abcdefghijkl",
    "abcdefghijkl1", "asdfghjklasdf", "asdfghjkl123", "zxcvbnm12345", "1q2w3e4r5t6y", "1qaz2wsx3edc",
    "123qweasdzxc", "qazwsxedcrfv", "gasoplus12345", "maiekmaiek12", "maiek1234567", "calidda123456",
})

_MARCAS = ("maiek", "gasoplus", "calidda")


def _normalizar(texto: str) -> str:
    """Minúsculas, sin acentos (ñ→n) y solo letras y números: «Contraseña 123» y «contrasena123» son la misma clave."""
    sin_acentos = "".join(c for c in unicodedata.normalize("NFKD", texto.lower()) if not unicodedata.combining(c))
    return "".join(c for c in sin_acentos if c.isalnum())


def _es_secuencia(normalizada: str) -> bool:
    """Un solo carácter repetido («aaaaaaaaaaaa») o una secuencia simple («abcdefghijkl», «123456789012»)."""
    if len(set(normalizada)) == 1:
        return True
    pasos = {ord(b) - ord(a) for a, b in zip(normalizada, normalizada[1:])}
    return pasos <= {1} or pasos <= {-1}


def validar_password(password: str, *, username: str | None = None, nombre: str | None = None) -> str | None:
    """None si la contraseña cumple; si no, el motivo en una frase lista para mostrar al usuario."""
    if len(password) < LARGO_MINIMO:
        return f"La contraseña nueva debe tener al menos {LARGO_MINIMO} caracteres. Una frase larga sirve."
    if len(password) > LARGO_MAXIMO:
        return f"La contraseña nueva no puede superar los {LARGO_MAXIMO} caracteres."
    normalizada = _normalizar(password)
    if normalizada in _COMUNES or _es_secuencia(normalizada):
        return "Esa contraseña es muy común o muy fácil de adivinar. Elige otra."
    if any(marca in normalizada for marca in _MARCAS):
        return "La contraseña no puede contener el nombre del producto o de la empresa."
    for dato in (username, nombre):
        parte = _normalizar(dato or "")
        if len(parte) >= 3 and parte in normalizada:
            return "La contraseña no puede contener tu usuario ni tu nombre."
    return None
