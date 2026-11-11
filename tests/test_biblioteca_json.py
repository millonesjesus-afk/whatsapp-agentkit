# tests/test_biblioteca_json.py — Biblioteca de archivos (API JSON del panel nuevo, Configuración v2).
#
# Las rutas se llaman directo (ningún test de este repo usa TestClient con sesión), igual que
# test_gate_equipo.py. Datos sintéticos únicamente.

import inspect
import io
import json
import os

import pytest
from fastapi import HTTPException
from starlette.datastructures import UploadFile

from agent import dashboard, memory as mem


@pytest.fixture(autouse=True)
def _archivos_en_carpeta_temporal(tmp_path, monkeypatch):
    monkeypatch.setattr(dashboard, "ARCHIVOS_DIR", str(tmp_path))


async def _negocio(codigo: str):
    return await mem.crear_negocio(f"Negocio {codigo}", codigo)


def _usuario(negocio, rol="admin", username="admin1"):
    return {"username": username, "rol": rol, "negocio_id": negocio["id"], "nombre": "Prueba"}


def _subida(nombre="catalogo.pdf", contenido=b"%PDF-1.4 prueba"):
    return UploadFile(file=io.BytesIO(contenido), filename=nombre)


def _json(respuesta):
    return json.loads(respuesta.body)


async def _subir(usuario, etiqueta="Catálogo 2026", archivo=None):
    return await dashboard.subir_a_biblioteca(
        etiqueta=etiqueta, archivo=archivo or _subida(), usuario=usuario, _csrf=None,
    )


# ── Listado ────────────────────────────────────────────────────────────────

async def test_listado_vacio_y_permiso_por_rol():
    negocio = await _negocio("bib-1")
    for rol, puede in (("admin", True), ("supervisor", False), ("asesor", False)):
        cuerpo = _json(await dashboard.listar_biblioteca(usuario=_usuario(negocio, rol, f"u_{rol}")))
        assert cuerpo["archivos"] == []
        assert cuerpo["puede_gestionar"] is puede
        assert ".pdf" in cuerpo["extensiones"]
        assert cuerpo["tamano_maximo_mb"] == dashboard.TAMANO_MAXIMO_ARCHIVO_MB


async def test_subir_y_listar_devuelve_los_campos_y_nunca_la_ruta_en_disco():
    negocio = await _negocio("bib-2")
    admin = _usuario(negocio)
    respuesta = await _subir(admin)
    assert respuesta.status_code == 201
    creado = _json(respuesta)["archivo"]
    assert creado["etiqueta"] == "Catálogo 2026"
    assert creado["nombre_original"] == "catalogo.pdf"
    assert creado["content_type"] == "application/pdf"
    assert creado["tamano_bytes"] == len(b"%PDF-1.4 prueba")
    assert creado["subido_por"] == "admin1"
    assert creado["creado"]

    # El asesor ve el archivo en el listado, sin datos internos.
    cuerpo = _json(await dashboard.listar_biblioteca(usuario=_usuario(negocio, "asesor", "ase1")))
    assert [a["id"] for a in cuerpo["archivos"]] == [creado["id"]]
    assert "ruta_disco" not in cuerpo["archivos"][0]
    assert "negocio_id" not in cuerpo["archivos"][0]


async def test_el_archivo_queda_guardado_en_disco_y_el_tipo_sale_de_la_extension():
    negocio = await _negocio("bib-3")
    creado = _json(await _subir(_usuario(negocio), archivo=_subida("foto.PNG", b"\x89PNG prueba")))["archivo"]
    guardado = await mem.obtener_archivo_adjunto(creado["id"])
    assert guardado["reutilizable"] is True
    assert guardado["negocio_id"] == negocio["id"]
    assert guardado["content_type"] == "image/png"
    assert os.path.exists(guardado["ruta_disco"])


# ── Validaciones de la subida ──────────────────────────────────────────────

@pytest.mark.parametrize("etiqueta, archivo, fragmento", [
    ("   ", lambda: _subida(), "nombre"),
    ("x" * 151, lambda: _subida(), "150"),
    ("Ok", lambda: _subida("virus.exe"), "Solo se aceptan"),
    ("Ok", lambda: _subida("sin_extension"), "Solo se aceptan"),
    ("Ok", lambda: _subida("vacio.pdf", b""), "vacío"),
    ("Ok", lambda: _subida(("a" * 300) + ".pdf"), "demasiado largo"),
])
async def test_subida_invalida_da_400_con_motivo(etiqueta, archivo, fragmento):
    negocio = await _negocio("bib-4")
    with pytest.raises(HTTPException) as exc:
        await _subir(_usuario(negocio), etiqueta=etiqueta, archivo=archivo())
    assert exc.value.status_code == 400
    assert fragmento in exc.value.detail
    assert await mem.listar_archivos_reutilizables(negocio["id"]) == []


async def test_archivo_mas_grande_que_el_tope_se_rechaza(monkeypatch):
    monkeypatch.setattr(dashboard, "TAMANO_MAXIMO_ARCHIVO_MB", 1)
    negocio = await _negocio("bib-5")
    with pytest.raises(HTTPException) as exc:
        await _subir(_usuario(negocio), archivo=_subida("grande.pdf", b"x" * (1024 * 1024 + 1)))
    assert exc.value.status_code == 400
    assert "1MB" in exc.value.detail


async def test_nombre_con_ruta_se_reduce_al_nombre_del_archivo():
    negocio = await _negocio("bib-6")
    creado = _json(await _subir(_usuario(negocio), archivo=_subida("..\\..\\carpeta/secreto.pdf")))["archivo"]
    assert creado["nombre_original"] == "secreto.pdf"


# ── Quitar ─────────────────────────────────────────────────────────────────

async def test_quitar_lo_saca_del_listado_pero_no_borra_el_archivo_del_disco():
    negocio = await _negocio("bib-7")
    admin = _usuario(negocio)
    creado = _json(await _subir(admin))["archivo"]
    ruta = (await mem.obtener_archivo_adjunto(creado["id"]))["ruta_disco"]

    respuesta = await dashboard.quitar_de_biblioteca(archivo_id=creado["id"], usuario=admin, _csrf=None)
    assert _json(respuesta) == {"ok": True}
    assert _json(await dashboard.listar_biblioteca(usuario=admin))["archivos"] == []
    assert os.path.exists(ruta)


async def test_quitar_un_id_inexistente_da_404():
    negocio = await _negocio("bib-8")
    with pytest.raises(HTTPException) as exc:
        await dashboard.quitar_de_biblioteca(archivo_id=999999, usuario=_usuario(negocio), _csrf=None)
    assert exc.value.status_code == 404


# ── Aislamiento entre negocios ─────────────────────────────────────────────

async def test_otro_negocio_no_ve_ni_puede_quitar_el_archivo():
    negocio_a = await _negocio("bib-9a")
    negocio_b = await _negocio("bib-9b")
    creado = _json(await _subir(_usuario(negocio_a)))["archivo"]

    assert _json(await dashboard.listar_biblioteca(usuario=_usuario(negocio_b, "admin", "admin_b")))["archivos"] == []
    with pytest.raises(HTTPException) as exc:
        await dashboard.quitar_de_biblioteca(
            archivo_id=creado["id"], usuario=_usuario(negocio_b, "admin", "admin_b"), _csrf=None,
        )
    assert exc.value.status_code == 404
    assert len(_json(await dashboard.listar_biblioteca(usuario=_usuario(negocio_a)))["archivos"]) == 1


# ── Permisos: subir y quitar son solo del administrador ────────────────────

@pytest.mark.parametrize("ruta", [dashboard.subir_a_biblioteca, dashboard.quitar_de_biblioteca])
@pytest.mark.parametrize("rol", ["supervisor", "asesor"])
async def test_solo_el_admin_sube_y_quita(ruta, rol):
    dependencia = inspect.signature(ruta).parameters["usuario"].default.dependency
    with pytest.raises(HTTPException) as exc:
        await dependencia(usuario={"username": "x", "rol": rol, "negocio_id": "neg-1"})
    assert exc.value.status_code == 403
