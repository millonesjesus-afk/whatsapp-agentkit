# agent/services/servicio_identidad.py — ServicioIdentidad
# Generado por AgentKit

"""
Usuarios, autenticación, autorización centralizada — Backend Architecture,
componente `ServicioIdentidad` ("Nuevo — hoy no existe como servicio, es
lógica repetida inline").

Backend Architecture §3 fija `requiere_rol(*roles)` como la única
dependencia de FastAPI para autorización, viviendo en `ServicioIdentidad`,
para reemplazar los ~26 checks de rol duplicados inline (CSA-Backend).

Fase 1 del Execution Plan (v1.2): esta sub-etapa aplica `requiere_rol`
primero a las rutas administrativas más críticas (canales, asesores),
exactamente como lo fija la Fase 1 de Backend Architecture §5 — no a los
~26 checks completos, eso queda para el segundo tramo de Backend, después
del protocolo de confianza de IA (Backend Architecture Fase 2).

`usuario_actual` y `NoAutenticado` se trasladan tal cual desde
agent/dashboard.py (antes `_usuario_actual`) — es la misma lógica de
resolución de sesión, ahora en el servicio al que Backend Architecture
dice que pertenece. `agent/dashboard.py` mantiene `_usuario_actual` como
alias del método de esta clase, así que ningún otro call site existente
cambia.
"""

import hashlib
import hmac
import secrets
import time

from fastapi import Depends, HTTPException, Request

from agent.memory import obtener_usuario


class NoAutenticado(Exception):
    """Se lanza cuando no hay una sesión válida; el handler en main.py redirige al login (o responde 401 en JSON).

    `motivo` (2026-11-11): si la sesión se cerró a propósito, por qué — "sesion_cerrada" (la contraseña cambió) o
    "cuenta_desactivada". El panel nuevo lo muestra en la pantalla de ingreso."""

    def __init__(self, motivo: str | None = None):
        super().__init__(motivo or "")
        self.motivo = motivo


# Clave de la sesión donde vive la huella de la contraseña con la que se inició sesión.
CLAVE_HUELLA_SESION = "huella_pw"
# Cuando una sesión se cierra a propósito, la cookie queda SOLO con el motivo (sin usuario) hasta el siguiente ingreso:
# así la pantalla de ingreso puede explicarlo aunque el primer rechazo haya llegado en otra pantalla.
CLAVE_MOTIVO_CIERRE = "cierre_motivo"
MOTIVO_SESION_CERRADA = "sesion_cerrada"
MOTIVO_CUENTA_DESACTIVADA = "cuenta_desactivada"


def huella_password(password_hash: str) -> str:
    """Huella corta del hash guardado (no de la contraseña): cambia cada vez que cambia la contraseña, porque bcrypt
    usa una sal nueva en cada cambio. La cookie de sesión está firmada pero NO cifrada (se puede leer); una huella del
    hash bcrypt no permite recuperar ni probar la contraseña."""
    return hashlib.sha256(password_hash.encode()).hexdigest()[:32]


# Gracia tras cambiar la propia contraseña. Mientras se guarda, el mismo navegador puede tener otro pedido en vuelo
# con la cookie anterior (la bandeja se refresca sola). Si ese pedido llega al servidor justo después del cambio,
# sin gracia se tomaría por «otra sesión»: se cerraría y su respuesta pisaría la cookie nueva, sacando a la persona
# que acaba de cambiarla. Por eso, durante GRACIA_CAMBIO_PASSWORD_SEGUNDOS, la huella ANTERIOR de esa cuenta todavía
# vale (sin reescribir la cookie). Pasado ese tiempo, cualquier sesión con la huella vieja se cierra (S1).
# Vive en memoria del proceso, igual que los bloqueos de rate_limit.py (una sola instancia; ver esa nota).
GRACIA_CAMBIO_PASSWORD_SEGUNDOS = 15
_cambios_recientes: dict[str, tuple[str, float]] = {}


def registrar_cambio_propio(username: str, password_hash_anterior: str) -> None:
    """La sesión de `username` cambió su propia contraseña: abre la gracia para su huella anterior."""
    _cambios_recientes[username] = (huella_password(password_hash_anterior), time.monotonic())


def _en_gracia(username: str | None, huella_guardada: str) -> bool:
    if not username:
        return False
    reciente = _cambios_recientes.get(username)
    if reciente is None:
        return False
    huella_anterior, cuando = reciente
    if time.monotonic() - cuando > GRACIA_CAMBIO_PASSWORD_SEGUNDOS:
        _cambios_recientes.pop(username, None)
        return False
    return hmac.compare_digest(huella_guardada, huella_anterior)


def fijar_huella(sesion, password_hash: str) -> None:
    """Al iniciar sesión o al cambiar la propia contraseña: esta sesión queda atada a la contraseña vigente."""
    sesion[CLAVE_HUELLA_SESION] = huella_password(password_hash)


def motivo_cierre_sesion(sesion, usuario: dict) -> str | None:
    """None si la sesión sigue vigente; si no, por qué se cierra (ver `sesion_vigente`)."""
    if not usuario.get("activo", True):
        return MOTIVO_CUENTA_DESACTIVADA
    actual = huella_password(usuario["password_hash"])
    guardada = sesion.get(CLAVE_HUELLA_SESION)
    if guardada is None:
        sesion[CLAVE_HUELLA_SESION] = actual
        return None
    if hmac.compare_digest(str(guardada), actual):
        return None
    if _en_gracia(usuario.get("username"), str(guardada)):
        return None
    return MOTIVO_SESION_CERRADA


def cerrar_sesion_por(sesion, motivo: str) -> None:
    """Vacía la sesión y deja solo el motivo: la cookie se reescribe al responder."""
    sesion.clear()
    sesion[CLAVE_MOTIVO_CIERRE] = motivo


def sesion_vigente(sesion, usuario: dict) -> bool:
    """Seguridad S1, S4 y S5 (2026-11-11).

    - S4: una cuenta desactivada (`activo=False`) pierde el acceso en su siguiente pedido, aunque su cookie siga viva
      (antes conservaba el acceso hasta que vencía la cookie, 14 días).
    - S1: si la contraseña cambió (la propia, desde otro equipo, o un reset del administrador), la huella guardada ya
      no coincide y esa sesión se cierra. La sesión que hizo el cambio actualiza su huella y sigue abierta.
    - S5: una sesión abierta antes de este cambio no tiene huella: se le pone la de la contraseña vigente en su primer
      pedido, así desplegar no saca a nadie.
    """
    return motivo_cierre_sesion(sesion, usuario) is None


class ServicioIdentidad:
    """Resolución de usuario autenticado + autorización por rol,
    centralizada — ningún otro módulo de Backend implementa su propio
    check de rol inline para las rutas ya migradas."""

    async def usuario_actual(self, request: Request) -> dict:
        username = request.session.get("username")
        if not username:
            motivo = request.session.get(CLAVE_MOTIVO_CIERRE)
            raise NoAutenticado(motivo if motivo in (MOTIVO_SESION_CERRADA, MOTIVO_CUENTA_DESACTIVADA) else None)
        usuario = await obtener_usuario(username)
        if usuario is None:
            raise NoAutenticado()
        motivo = motivo_cierre_sesion(request.session, usuario)
        if motivo is not None:
            # Cuenta desactivada o contraseña cambiada desde que se abrió esta sesión: se cierra (la cookie se
            # reescribe al responder, sin usuario) y el motivo viaja en el 401.
            cerrar_sesion_por(request.session, motivo)
            raise NoAutenticado(motivo)
        # Token CSRF por sesión (Bloque CSRF explícito) — generado una sola
        # vez, lazy: cubre tanto logins nuevos como sesiones que ya estaban
        # abiertas antes de este deploy, sin forzar un logout global. No
        # rota mientras la sesión siga activa (dashboard.py lo inyecta como
        # <meta> una sola vez en la carga completa de página).
        request.session.setdefault("csrf_token", secrets.token_urlsafe(32))
        return usuario

    def requiere_rol(self, *roles: str):
        """Devuelve una dependencia de FastAPI: exige que el usuario
        autenticado tenga uno de los `roles` dados, o responde 403."""
        async def _verificar(usuario: dict = Depends(self.usuario_actual)) -> dict:
            if usuario["rol"] not in roles:
                raise HTTPException(status_code=403, detail="No tienes permiso para acceder a esta sección")
            return usuario
        return _verificar


# Instancia compartida por todo el proceso — mismo patrón que
# servicio_inteligencia y servicio_comercial.
servicio_identidad = ServicioIdentidad()
