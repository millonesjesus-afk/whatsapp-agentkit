# tests/test_perfil_password_sesiones.py — Mi perfil: cambio de la propia contraseña y seguridad de sesiones (2026-11-11).
#
# Decisiones del dueño S1 a S5:
#   S1 cambiar la contraseña (propia o por reset del admin) cierra las demás sesiones; la que la cambió sigue abierta.
#   S2 5 intentos con la contraseña actual equivocada bloquean 15 minutos.
#   S3 el cambio queda en la auditoría, sin la contraseña.
#   S4 una cuenta desactivada pierde el acceso en su siguiente pedido.
#   S5 desplegar no saca a nadie: una sesión sin huella la recibe en su primer pedido.
# Además: bcrypt 5 rechaza más de 72 bytes; ni el login ni el cambio deben romperse con eso.
# Las rutas se llaman directo, como en el resto del repo. Datos sintéticos únicamente.

import json
import os

os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")  # agent.main las exige al importarse (prueba del 401)
os.environ.setdefault("WHATSAPP_PROVIDER", "meta")

import bcrypt
import pytest
from fastapi import HTTPException
from sqlalchemy import select
from starlette.requests import Request

from agent import dashboard, memory as mem
from agent.politica_password import BYTES_MAXIMO, password_coincide, validar_password
from agent.services.servicio_identidad import (
    CLAVE_HUELLA_SESION, CLAVE_MOTIVO_CIERRE, NoAutenticado, huella_password, servicio_identidad,
)

ACTUAL = "ClaveActual-123456"
NUEVA = "tortuga azul bicicleta roja"


def _request(cuerpo=None, sesion=None, crudo: bytes | None = None) -> Request:
    datos = crudo if crudo is not None else json.dumps(cuerpo or {}).encode()
    enviado = False

    async def recibir():
        nonlocal enviado
        if enviado:
            return {"type": "http.disconnect"}
        enviado = True
        return {"type": "http.request", "body": datos, "more_body": False}

    return Request(
        scope={
            "type": "http", "method": "POST", "path": "/dashboard/perfil/password.json",
            "headers": [(b"content-type", b"application/json")],
            "session": sesion if sesion is not None else {},
        },
        receive=recibir,
    )


async def _cuenta(codigo: str, rol: str = "asesor"):
    n = await mem.crear_negocio(f"Negocio {codigo}", codigo)
    await mem.crear_usuario(f"user_{codigo}", ACTUAL, "Usuario Prueba", rol, n["id"])
    return await mem.obtener_usuario(f"user_{codigo}", negocio_id=n["id"])


async def _cambiar(usuario, actual=ACTUAL, nueva=NUEVA, repetir=None, sesion=None):
    sesion = sesion if sesion is not None else {}
    cuerpo = {"password_actual": actual, "password_nueva": nueva, "password_nueva_repetir": nueva if repetir is None else repetir}
    return await dashboard.cambiar_password_propia(request=_request(cuerpo, sesion), usuario=usuario, _csrf=None)


async def _hash_actual(usuario) -> str:
    return (await mem.obtener_usuario(usuario["username"], negocio_id=usuario["negocio_id"]))["password_hash"]


async def _auditoria(negocio_id: str, accion: str) -> list:
    async with mem.async_session() as session:
        q = select(mem.RegistroAuditoria).where(
            mem.RegistroAuditoria.negocio_id == negocio_id, mem.RegistroAuditoria.accion == accion,
        )
        return list((await session.execute(q)).scalars().all())


def _request_sesion(sesion: dict) -> Request:
    return Request(scope={"type": "http", "method": "GET", "path": "/dashboard/sesion", "headers": [], "session": sesion})


# ── Cambio feliz + S3 ──────────────────────────────────────────────────────

async def test_cambia_la_contrasena_actualiza_la_huella_de_esta_sesion_y_audita_sin_la_clave():
    u = await _cuenta("pp-1")
    sesion = {"username": u["username"], CLAVE_HUELLA_SESION: huella_password(u["password_hash"])}
    r = await _cambiar(u, sesion=sesion)
    assert json.loads(r.body) == {"ok": True}

    nuevo_hash = await _hash_actual(u)
    assert bcrypt.checkpw(NUEVA.encode(), nuevo_hash.encode())
    assert sesion[CLAVE_HUELLA_SESION] == huella_password(nuevo_hash)

    filas = await _auditoria(u["negocio_id"], "password_cambiada")
    assert len(filas) == 1
    assert filas[0].actor == u["username"] and filas[0].entidad_id == u["username"]
    texto = json.dumps(filas[0].payload or {})
    assert NUEVA not in texto and ACTUAL not in texto and nuevo_hash not in texto


# ── Validaciones: 400 actual, 422 nueva ────────────────────────────────────

async def test_actual_incorrecta_da_400_y_no_cambia_nada():
    u = await _cuenta("pp-2")
    with pytest.raises(HTTPException) as exc:
        await _cambiar(u, actual="otra-clave-equivocada")
    assert exc.value.status_code == 400
    assert "actual" in exc.value.detail
    assert bcrypt.checkpw(ACTUAL.encode(), (await _hash_actual(u)).encode())


@pytest.mark.parametrize("nueva, repetir, fragmento", [
    (NUEVA, "otra frase distinta larga", "no coinciden"),
    (ACTUAL, None, "distinta de la actual"),
    ("corta123", None, "al menos 12"),
    ("mi user_pp-3 secreta larga", None, "usuario"),
    ("ñ" * 40, None, "tilde"),
])
async def test_nueva_invalida_da_422_con_motivo_y_no_se_guarda(nueva, repetir, fragmento):
    u = await _cuenta("pp-3")
    with pytest.raises(HTTPException) as exc:
        await _cambiar(u, nueva=nueva, repetir=repetir)
    assert exc.value.status_code == 422
    assert fragmento in exc.value.detail
    assert bcrypt.checkpw(ACTUAL.encode(), (await _hash_actual(u)).encode())


@pytest.mark.parametrize("crudo", [b"no es json", b"[1,2]", json.dumps({"password_actual": ACTUAL}).encode()])
async def test_cuerpo_incompleto_da_422(crudo):
    u = await _cuenta("pp-4")
    with pytest.raises(HTTPException) as exc:
        await dashboard.cambiar_password_propia(request=_request(crudo=crudo), usuario=u, _csrf=None)
    assert exc.value.status_code == 422


# ── S2: bloqueo por intentos ───────────────────────────────────────────────

async def test_cinco_fallos_bloquean_quince_minutos_aunque_luego_acierte():
    u = await _cuenta("pp-5")
    for _ in range(4):
        with pytest.raises(HTTPException) as exc:
            await _cambiar(u, actual="equivocada-000000")
        assert exc.value.status_code == 400
    with pytest.raises(HTTPException) as exc:
        await _cambiar(u, actual="equivocada-000000")
    assert exc.value.status_code == 429
    assert int(exc.value.headers["Retry-After"]) > 14 * 60
    assert "15 minuto" in exc.value.detail

    with pytest.raises(HTTPException) as exc:
        await _cambiar(u)  # contraseña correcta, pero sigue bloqueado
    assert exc.value.status_code == 429
    assert bcrypt.checkpw(ACTUAL.encode(), (await _hash_actual(u)).encode())


async def test_un_acierto_reinicia_el_conteo_de_fallos():
    u = await _cuenta("pp-6")
    for _ in range(4):
        with pytest.raises(HTTPException):
            await _cambiar(u, actual="equivocada-000000")
    with pytest.raises(HTTPException) as exc:
        await _cambiar(u, nueva="corta123")  # actual correcta: reinicia; falla por la nueva
    assert exc.value.status_code == 422
    for _ in range(4):
        with pytest.raises(HTTPException) as exc:
            await _cambiar(u, actual="equivocada-000000")
        assert exc.value.status_code == 400


async def test_el_bloqueo_es_por_cuenta():
    a = await _cuenta("pp-7a")
    b = await _cuenta("pp-7b")
    for _ in range(5):
        with pytest.raises(HTTPException):
            await _cambiar(a, actual="equivocada-000000")
    assert json.loads((await _cambiar(b)).body) == {"ok": True}


# ── S1, S4 y S5: vigencia de la sesión ─────────────────────────────────────

async def test_s5_una_sesion_sin_huella_la_recibe_y_sigue_abierta():
    u = await _cuenta("pp-8")
    sesion = {"username": u["username"]}
    resuelto = await servicio_identidad.usuario_actual(_request_sesion(sesion))
    assert resuelto["username"] == u["username"]
    assert sesion[CLAVE_HUELLA_SESION] == huella_password(u["password_hash"])


async def test_s1_cambiar_la_contrasena_cierra_las_otras_sesiones_y_no_la_propia(monkeypatch):
    from agent.services import servicio_identidad as identidad

    u = await _cuenta("pp-9")
    huella = huella_password(u["password_hash"])
    otra = {"username": u["username"], CLAVE_HUELLA_SESION: huella}
    propia = {"username": u["username"], CLAVE_HUELLA_SESION: huella}

    await _cambiar(u, sesion=propia)

    assert (await servicio_identidad.usuario_actual(_request_sesion(propia)))["username"] == u["username"]
    # Pasada la gracia de los pedidos en vuelo (ver el test siguiente), la otra sesión se cierra.
    reloj = identidad.time.monotonic() + identidad.GRACIA_CAMBIO_PASSWORD_SEGUNDOS + 1
    monkeypatch.setattr(identidad.time, "monotonic", lambda: reloj)
    with pytest.raises(NoAutenticado) as exc:
        await servicio_identidad.usuario_actual(_request_sesion(otra))
    assert exc.value.motivo == "sesion_cerrada"
    # la sesión vieja quedó sin usuario, solo con el motivo (la cookie se reescribe al responder)
    assert otra == {CLAVE_MOTIVO_CIERRE: "sesion_cerrada"}
    # y el siguiente pedido con esa cookie sigue diciendo por qué
    with pytest.raises(NoAutenticado) as exc:
        await servicio_identidad.usuario_actual(_request_sesion(otra))
    assert exc.value.motivo == "sesion_cerrada"


async def test_s1_un_pedido_en_vuelo_del_mismo_navegador_no_saca_a_quien_cambio_la_contrasena(monkeypatch):
    from agent.services import servicio_identidad as identidad

    u = await _cuenta("pp-9b")
    huella_vieja = huella_password(u["password_hash"])
    propia = {"username": u["username"], CLAVE_HUELLA_SESION: huella_vieja}
    en_vuelo = dict(propia)  # mismo navegador: un pedido salió con la cookie anterior antes de que llegara la nueva

    await _cambiar(u, sesion=propia)

    # Dentro de la gracia: el pedido en vuelo pasa y no se le reescribe la cookie.
    assert (await servicio_identidad.usuario_actual(_request_sesion(en_vuelo)))["username"] == u["username"]
    assert en_vuelo[CLAVE_HUELLA_SESION] == huella_vieja

    # Pasada la gracia: la huella vieja ya no vale (S1).
    reloj = identidad.time.monotonic() + identidad.GRACIA_CAMBIO_PASSWORD_SEGUNDOS + 1
    monkeypatch.setattr(identidad.time, "monotonic", lambda: reloj)
    with pytest.raises(NoAutenticado):
        await servicio_identidad.usuario_actual(_request_sesion(en_vuelo))


async def test_s1_el_reset_del_administrador_no_tiene_gracia():
    u = await _cuenta("pp-9c")
    sesion = {"username": u["username"], CLAVE_HUELLA_SESION: huella_password(u["password_hash"])}
    await mem.cambiar_password(u["username"], u["negocio_id"], "otra-temporal-xyz12")
    with pytest.raises(NoAutenticado):
        await servicio_identidad.usuario_actual(_request_sesion(sesion))


async def test_s1_el_reset_del_administrador_tambien_cierra_las_sesiones_de_la_cuenta():
    u = await _cuenta("pp-10")
    sesion = {"username": u["username"], CLAVE_HUELLA_SESION: huella_password(u["password_hash"])}
    await mem.cambiar_password(u["username"], u["negocio_id"], "otra-temporal-xyz12")
    with pytest.raises(NoAutenticado):
        await servicio_identidad.usuario_actual(_request_sesion(sesion))


async def test_s4_una_cuenta_desactivada_pierde_la_sesion_abierta():
    u = await _cuenta("pp-11")
    sesion = {"username": u["username"], CLAVE_HUELLA_SESION: huella_password(u["password_hash"])}
    assert (await servicio_identidad.usuario_actual(_request_sesion(sesion)))["username"] == u["username"]

    assert await mem.toggle_usuario_activo(u["username"], u["negocio_id"]) is False
    with pytest.raises(NoAutenticado) as exc:
        await servicio_identidad.usuario_actual(_request_sesion(sesion))
    assert exc.value.motivo == "cuenta_desactivada"
    assert sesion == {CLAVE_MOTIVO_CIERRE: "cuenta_desactivada"}


async def test_s4_sin_huella_y_desactivada_tampoco_entra():
    u = await _cuenta("pp-12")
    await mem.toggle_usuario_activo(u["username"], u["negocio_id"])
    with pytest.raises(NoAutenticado):
        await servicio_identidad.usuario_actual(_request_sesion({"username": u["username"]}))


# ── Login: huella y contraseñas largas ─────────────────────────────────────

def _request_login(sesion: dict) -> Request:
    return Request(scope={
        "type": "http", "method": "POST", "path": "/dashboard/login",
        "headers": [], "session": sesion, "client": ("10.0.0.1", 1234),
    })


async def test_una_sesion_vencida_sin_motivo_no_inventa_uno():
    with pytest.raises(NoAutenticado) as exc:
        await servicio_identidad.usuario_actual(_request_sesion({}))
    assert exc.value.motivo is None
    with pytest.raises(NoAutenticado) as exc:
        await servicio_identidad.usuario_actual(_request_sesion({CLAVE_MOTIVO_CIERRE: "<script>"}))
    assert exc.value.motivo is None


async def test_el_login_ata_la_sesion_a_la_contrasena_vigente_y_borra_el_motivo_anterior():
    u = await _cuenta("pp-13")
    sesion: dict = {CLAVE_MOTIVO_CIERRE: "sesion_cerrada"}
    r = await dashboard.login_submit(_request_login(sesion), username=u["username"], password=ACTUAL)
    assert "/dashboard/login" not in r.headers["location"]
    assert sesion["username"] == u["username"]
    assert sesion[CLAVE_HUELLA_SESION] == huella_password(u["password_hash"])
    assert CLAVE_MOTIVO_CIERRE not in sesion


async def test_el_401_en_json_lleva_el_motivo():
    from agent.main import no_autenticado_handler

    request = Request(scope={
        "type": "http", "method": "GET", "path": "/dashboard/sesion",
        "headers": [(b"accept", b"application/json")], "session": {},
    })
    r = await no_autenticado_handler(request, NoAutenticado("cuenta_desactivada"))
    assert r.status_code == 401
    assert json.loads(r.body)["motivo"] == "cuenta_desactivada"
    r = await no_autenticado_handler(request, NoAutenticado())
    assert json.loads(r.body)["motivo"] is None


async def test_el_login_con_una_clave_de_mas_de_72_bytes_no_rompe():
    u = await _cuenta("pp-14")
    sesion: dict = {}
    r = await dashboard.login_submit(_request_login(sesion), username=u["username"], password="x" * 100)
    assert "error=" in r.headers["location"]
    assert "username" not in sesion


def test_password_coincide_no_rompe_con_entradas_raras():
    h = bcrypt.hashpw(b"una-clave-cualquiera", bcrypt.gensalt()).decode()
    assert password_coincide("una-clave-cualquiera", h) is True
    assert password_coincide("y" * (BYTES_MAXIMO + 1), h) is False
    assert password_coincide("", h) is False
    assert password_coincide("una-clave-cualquiera", "no-es-un-hash") is False


def test_la_politica_acepta_hasta_72_bytes_y_explica_las_tildes():
    assert validar_password("a" * 72) is None or "común" in validar_password("a" * 72)
    assert validar_password("tortuga-azul " * 5 + "fin!xx") is None  # 71 caracteres
    assert "superar" in validar_password("tortuga azul bicicleta " * 4)  # 92 caracteres
    assert "tilde" in validar_password("ñandú camión avión " * 3 + "más")  # menos de 72 caracteres, más de 72 bytes


# ── La ruta vieja del formulario ya no existe ──────────────────────────────

def test_el_formulario_viejo_de_contrasena_ya_no_tiene_ruta():
    rutas = {(r.path, m) for r in dashboard.router.routes for m in getattr(r, "methods", set()) or set()}
    assert ("/dashboard/perfil/password", "POST") not in rutas and ("/perfil/password", "POST") not in rutas
    assert any(p.endswith("/perfil/password.json") and m == "POST" for p, m in rutas)
