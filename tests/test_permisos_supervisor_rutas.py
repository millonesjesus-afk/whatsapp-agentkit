# tests/test_permisos_supervisor_rutas.py — Lo que el supervisor (y el asesor) NO puede hacer (2026-10-12, Fase 0):
#  · 403 por rol en Configuración, horario semanal, financiamiento, Gabi, canales, Equipo, Asesores y Uso/costos de Meta
#    (D3: `uso-mensajes.json` y `uso-mensajes/envios.json` pasan a SOLO admin);
#  · el admin sigue entrando a todo lo anterior;
#  · cada exportación de leads (CSV y Excel) queda en `RegistroAuditoria` con actor, actor_rol, formato, filas y filtros, sin PII;
#  · `actor_rol` en la auditoría de "Para llamar" (aceptar/revocar la responsabilidad);
#  · D8: el GET de `llamadas.json` entrega la `medicion` al supervisor (y no al asesor).
# Las pruebas llaman por HTTP al router real (tests/_cliente_http.py): la dependencia de rol y la de CSRF son las de producción.

import os

os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")
os.environ.setdefault("WHATSAPP_PROVIDER", "meta")

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from agent import dashboard
from agent import llamadas
from agent import memory as mem
from tests._cliente_http import ClienteHttp

# (método, ruta): rutas que NO son del supervisor ni del asesor. Los cuerpos vacíos dan igual: el 403 de rol se resuelve antes.
RUTAS_SOLO_ADMIN = [
    ("GET", "/dashboard/configuracion.json"),
    ("POST", "/dashboard/configuracion/negocio"),
    ("POST", "/dashboard/configuracion/horario"),
    ("POST", "/dashboard/configuracion/financiamiento"),
    ("POST", "/dashboard/configuracion/gabi"),
    ("GET", "/dashboard/configuracion/metricas.json"),
    ("POST", "/dashboard/configuracion/metricas.json"),
    ("GET", "/dashboard/configuracion/derivacion-automatica.json"),
    ("POST", "/dashboard/configuracion/derivacion-automatica.json"),
    ("GET", "/dashboard/configuracion/llamadas.json"),
    ("POST", "/dashboard/configuracion/llamadas.json"),
    ("POST", "/dashboard/canales-whatsapp/embedded-signup/callback"),     # lo que usa «Conectar WhatsApp» de la Nueva Experiencia
    ("POST", "/dashboard/canales-whatsapp/nuevo"),
    ("POST", "/dashboard/canales-whatsapp/registrar"),
    ("POST", "/dashboard/canales-whatsapp/1/editar"),
    ("POST", "/dashboard/canales-whatsapp/1/toggle"),
    ("POST", "/dashboard/canales-whatsapp/1/modo"),
    ("POST", "/dashboard/canales-whatsapp/promover-prompt"),
    ("POST", "/dashboard/equipo/alguien/resetear"),
    ("POST", "/dashboard/equipo/alguien/toggle"),
    ("POST", "/dashboard/equipo/alguien/eliminar"),
    ("POST", "/dashboard/asesores/alguien/resetear"),
    ("POST", "/dashboard/asesores/nuevo"),
    ("POST", "/dashboard/asesores/alguien/nivel"),
    ("POST", "/dashboard/asesores/umbrales"),
    ("GET", "/dashboard/uso-mensajes.json"),
    ("GET", "/dashboard/uso-mensajes/envios.json"),
    ("GET", "/dashboard/uso-mensajes/conciliacion.json"),
    ("GET", "/dashboard/uso-mensajes/estimacion-previa.json"),
    ("GET", "/dashboard/uso-mensajes/configuracion.json"),
    ("GET", "/dashboard/uso-mensajes/historial-cambios.json"),
    ("POST", "/dashboard/uso-mensajes/configuracion.json"),
    ("POST", "/dashboard/uso-mensajes/detectar-zona.json"),
]


@pytest.fixture
async def cliente():
    c = ClienteHttp()
    yield c
    await c.cerrar()


def _usuario(negocio, username, rol):
    return {"negocio_id": negocio["id"], "username": username, "rol": rol}


async def _llamar(cliente, metodo, ruta):
    return await (cliente.get(ruta) if metodo == "GET" else cliente.post(ruta, {}))


@pytest.mark.parametrize("rol", ["supervisor", "asesor"])
@pytest.mark.parametrize("metodo,ruta", RUTAS_SOLO_ADMIN)
async def test_supervisor_y_asesor_reciben_403(cliente, rol, metodo, ruta):
    n = await mem.crear_negocio("Negocio permisos", "perm-1")
    r = await _llamar(cliente.con(_usuario(n, "u1", rol)), metodo, ruta)
    assert r.status_code == 403, (rol, metodo, ruta, r.status_code, r.text[:200])
    assert "permiso" in r.json()["detail"]


def _candado_de_rol(metodo: str, ruta: str):
    """La dependencia de rol (`requiere_rol`) de la ruta REAL del router que atiende `metodo ruta`."""
    for r in dashboard.router.routes:
        if getattr(r, "path_regex", None) is not None and r.path_regex.match(ruta) and metodo in r.methods:
            return next(d.call for d in r.dependant.dependencies if getattr(d.call, "__name__", "") == "_verificar")
    raise AssertionError(f"No hay ruta {metodo} {ruta}")


@pytest.mark.parametrize("metodo,ruta", RUTAS_SOLO_ADMIN)
async def test_el_admin_pasa_el_candado_de_rol_y_los_demas_no(metodo, ruta):
    """Sin ejecutar la ruta (varias llaman a Meta o cambian configuración): solo el candado de rol de cada una."""
    candado = _candado_de_rol(metodo, ruta)
    assert (await candado(usuario={"rol": "admin", "username": "a", "negocio_id": "n"}))["rol"] == "admin"
    for rol in ("supervisor", "asesor"):
        with pytest.raises(HTTPException) as e:
            await candado(usuario={"rol": rol, "username": "u", "negocio_id": "n"})
        assert e.value.status_code == 403


async def test_uso_mensajes_cerrado_al_supervisor_pero_abierto_al_admin(cliente):
    n = await mem.crear_negocio("Negocio uso", "perm-3")
    for ruta in ("/dashboard/uso-mensajes.json", "/dashboard/uso-mensajes/envios.json"):
        assert (await cliente.con(_usuario(n, "sup1", "supervisor")).get(ruta)).status_code == 403
        assert (await cliente.con(_usuario(n, "ase1", "asesor")).get(ruta)).status_code == 403
        r = await cliente.con(_usuario(n, "adm1", "admin")).get(ruta)
        assert r.status_code == 200, ruta
    assert (await cliente.con(_usuario(n, "adm1", "admin")).get("/dashboard/uso-mensajes.json", mes="2026-13")).status_code == 400


async def test_post_de_configuracion_sin_token_csrf_da_403_aun_para_el_admin(cliente):
    n = await mem.crear_negocio("Negocio csrf", "perm-4")
    admin = cliente.con(_usuario(n, "adm1", "admin"))
    assert (await admin.post("/dashboard/configuracion/horario", {}, token=None)).status_code == 403
    assert (await admin.post("/dashboard/equipo/alguien/toggle", {}, token="otro")).status_code == 403


# ── Exportación de leads auditada (D6) ──────────────────────────────────────

async def _negocio_con_leads(codigo: str, cantidad: int):
    negocio = await mem.crear_negocio(f"Negocio {codigo}", codigo)
    canal = await mem.crear_canal_whatsapp(nombre=f"Canal {codigo}", phone_number_id=f"pid-{codigo}", negocio_id=negocio["id"])
    for i in range(cantidad):
        telefono = f"51999{codigo[-1]}{i:05d}"
        await mem.resolver_conversation_activa(telefono, negocio["id"], canal["id"])
        await mem.actualizar_lead(telefono, nombre=f"Cliente {i}", negocio_id=negocio["id"])
    return negocio


async def _auditoria_exportaciones(negocio_id):
    async with mem.async_session() as session:
        return list((await session.execute(
            select(mem.RegistroAuditoria).where(
                mem.RegistroAuditoria.negocio_id == negocio_id, mem.RegistroAuditoria.accion == "leads_exportados",
            ).order_by(mem.RegistroAuditoria.creado.asc())
        )).scalars().all())


@pytest.mark.parametrize("rol", ["admin", "supervisor"])
async def test_cada_exportacion_de_leads_deja_auditoria(cliente, rol):
    n = await _negocio_con_leads("exp1", 3)
    c = cliente.con(_usuario(n, "u1", rol))
    assert (await c.get("/dashboard/metricas/exportar.csv")).status_code == 200
    assert (await c.get("/dashboard/metricas/exportar.xlsx")).status_code == 200
    filas = await _auditoria_exportaciones(n["id"])
    assert [f.payload["formato"] for f in filas] == ["csv", "xlsx"]
    for f in filas:
        assert f.actor == "u1" and f.entidad_tipo == "exportacion"
        assert f.payload["actor_rol"] == rol and f.payload["filas"] == 3
        assert f.payload["filtros"] == {"alcance": "todos_los_leads_del_negocio"}
        assert set(f.payload) == {"actor_rol", "formato", "filas", "filtros"}
        texto = str(f.payload)
        assert "51999" not in texto and "Cliente" not in texto               # sin PII: ni teléfonos ni nombres


async def test_el_asesor_no_exporta_y_no_deja_auditoria(cliente):
    n = await _negocio_con_leads("exp2", 1)
    c = cliente.con(_usuario(n, "ase1", "asesor"))
    assert (await c.get("/dashboard/metricas/exportar.csv")).status_code == 403
    assert (await c.get("/dashboard/metricas/exportar.xlsx")).status_code == 403
    assert await _auditoria_exportaciones(n["id"]) == []


async def test_la_exportacion_se_audita_en_el_negocio_de_quien_la_pide(cliente):
    a, b = await _negocio_con_leads("exp3", 2), await _negocio_con_leads("exp4", 5)
    await cliente.con(_usuario(a, "sup_a", "supervisor")).get("/dashboard/metricas/exportar.csv")
    assert len(await _auditoria_exportaciones(a["id"])) == 1 and await _auditoria_exportaciones(b["id"]) == []
    assert (await _auditoria_exportaciones(a["id"]))[0].payload["filas"] == 2           # solo los leads de SU negocio


async def test_si_no_se_puede_auditar_la_exportacion_no_se_entrega(cliente, monkeypatch):
    n = await _negocio_con_leads("exp5", 1)

    async def _falla(*a, **k):
        raise RuntimeError("base caída")

    monkeypatch.setattr(mem, "registrar_auditoria", _falla)
    c = cliente.con(_usuario(n, "adm1", "admin"))
    with pytest.raises(RuntimeError):
        await c.get("/dashboard/metricas/exportar.csv")


# ── actor_rol en "Para llamar" ──────────────────────────────────────────────

async def test_aceptar_y_revocar_la_responsabilidad_dejan_actor_rol(cliente):
    n = await mem.crear_negocio("Negocio llamadas", "perm-ll")
    admin = cliente.con(_usuario(n, "adm1", "admin"))
    r = await admin.post("/dashboard/configuracion/llamadas.json", {"aceptar_responsabilidad": True, "version_texto": llamadas.VERSION_TEXTO_RESPONSABILIDAD})
    assert r.status_code == 200, r.text
    r = await admin.post("/dashboard/configuracion/llamadas.json", {"revocar_responsabilidad": True})
    assert r.status_code == 200, r.text
    async with mem.async_session() as session:
        filas = list((await session.execute(
            select(mem.RegistroAuditoria).where(mem.RegistroAuditoria.negocio_id == n["id"]).order_by(mem.RegistroAuditoria.creado.asc())
        )).scalars().all())
    assert [f.accion for f in filas] == ["llamadas_responsabilidad_aceptada", "llamadas_responsabilidad_revocada"]
    assert all(f.actor == "adm1" and f.payload["actor_rol"] == "admin" for f in filas)


# ── D8: la medición de llamadas llega al supervisor ─────────────────────────

async def test_llamadas_json_entrega_la_medicion_al_supervisor_y_al_admin_pero_no_al_asesor(cliente, monkeypatch):
    n = await mem.crear_negocio("Negocio medicion", "perm-me")

    async def _modo(negocio_id):
        return llamadas.MODO_ACTIVO

    monkeypatch.setattr(llamadas, "modo_efectivo", _modo)
    for rol, esperada in (("admin", True), ("supervisor", True), ("asesor", False)):
        r = await cliente.con(_usuario(n, f"{rol}1", rol)).get("/dashboard/llamadas.json")
        assert r.status_code == 200, (rol, r.text)
        assert ("medicion" in r.json()) is esperada, rol
