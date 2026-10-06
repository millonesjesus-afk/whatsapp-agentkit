# tests/test_atribucion_asesor_envios.py — 2026-10-05, Ola 2 (agente A), decisión D5:
# cada envío del asesor desde el panel queda atribuido a su username en
# envios_meta.asesor_usuario, y el resumen por origen suma `por_asesor` (sin dinero).
# Los envíos de Gabi y de los scripts quedan en None. El kwarg `asesor` NO llega al proveedor.

import os
from pathlib import Path

os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")
os.environ.setdefault("WHATSAPP_PROVIDER", "meta")

import pytest
from sqlalchemy import select
from starlette.datastructures import UploadFile
import io

from agent import dashboard, envios
from agent import memory as mem

TEL = "51911112222"


class _Proveedor:
    """Proveedor falso con las firmas ESTRICTAS de siempre: si `asesor` le llegara, fallaría."""

    def __init__(self):
        self.llamadas = []
        self.canal = {"phone_number_id": "111"}

    async def resolver_canal(self, numero_whatsapp_id, negocio_id=None):
        return self.canal

    async def subir_media(self, contenido, nombre, content_type, canal=None):
        return "media-1"

    async def enviar_mensaje(self, telefono, mensaje, canal=None, mensaje_id_citado=None):
        self.llamadas.append("texto")
        return True, "wamid.t"

    async def enviar_imagen(self, telefono, media_id, caption="", canal=None):
        self.llamadas.append("imagen")
        return True, "wamid.i"

    async def enviar_documento(self, telefono, media_id, nombre_archivo, caption="", canal=None):
        self.llamadas.append("documento")
        return True, "wamid.d"

    async def enviar_audio(self, telefono, media_id, canal=None):
        self.llamadas.append("audio")
        return True, "wamid.a"


async def _negocio(codigo):
    n = await mem.crear_negocio(f"Negocio {codigo}", codigo)
    return n["id"], {"negocio_id": n["id"], "phone_number_id": "111"}


async def _filas(nid):
    async with mem.async_session() as s:
        return (await s.execute(select(mem.EnvioMeta).where(mem.EnvioMeta.negocio_id == nid).order_by(mem.EnvioMeta.id))).scalars().all()


async def test_los_cuatro_envios_guardan_el_asesor_y_no_se_lo_pasan_al_proveedor():
    nid, canal = await _negocio("atr-1")
    p = _Proveedor()
    await envios.enviar_texto(p, TEL, "hola", origen="asesor_texto", canal=canal, asesor="lelespuru", mensaje_id_citado="wamid.c")
    await envios.enviar_imagen(p, TEL, "m", "pie", origen="asesor_archivo", canal=canal, asesor="lelespuru")
    await envios.enviar_documento(p, TEL, "m", "a.pdf", "pie", origen="asesor_archivo", canal=canal, asesor="lelespuru")
    await envios.enviar_audio(p, TEL, "m", origen="asesor_audio", canal=canal, asesor="lelespuru")
    assert p.llamadas == ["texto", "imagen", "documento", "audio"]
    assert [(f.tipo, f.asesor_usuario) for f in await _filas(nid)] == [
        ("texto", "lelespuru"), ("imagen", "lelespuru"), ("documento", "lelespuru"), ("audio", "lelespuru"),
    ]


async def test_los_envios_de_gabi_y_de_scripts_quedan_sin_asesor():
    nid, canal = await _negocio("atr-2")
    p = _Proveedor()
    await envios.enviar_texto(p, TEL, "hola", origen="gabi_respuesta", canal=canal)
    await envios.enviar_texto(p, TEL, "ya vuelve", origen="reenganche_inactividad", canal=canal)
    assert [f.asesor_usuario for f in await _filas(nid)] == [None, None]


async def test_un_sustituto_de_reservar_con_la_firma_anterior_sigue_funcionando(monkeypatch):
    nid, canal = await _negocio("atr-3")
    vistos = []

    async def reservar_viejo(negocio_id, origen, telefono, tipo, agrupar_minutos=0, estimacion=None):
        vistos.append(origen)
        return None, None

    monkeypatch.setattr(envios, "reservar_envio_meta", reservar_viejo)
    r = await envios.enviar_texto(_Proveedor(), TEL, "x", origen="gabi_respuesta", canal=canal)   # sin asesor
    assert r.enviado and vistos == ["gabi_respuesta"]


async def test_por_asesor_cuenta_mensajes_archivos_y_bloqueados_ordenado_y_sin_dinero():
    nid, canal = await _negocio("atr-4")
    otro, canal_otro = await _negocio("atr-4b")
    p = _Proveedor()
    for _ in range(3):
        await envios.enviar_texto(p, TEL, "t", origen="asesor_texto", canal=canal, asesor="ana")
    await envios.enviar_imagen(p, TEL, "m", "", origen="asesor_archivo", canal=canal, asesor="ana")
    await envios.enviar_documento(p, TEL, "m", "a.pdf", "", origen="asesor_archivo", canal=canal, asesor="ana")
    await envios.enviar_audio(p, TEL, "m", origen="asesor_audio", canal=canal, asesor="ana")
    for _ in range(5):
        await envios.enviar_texto(p, TEL, "t", origen="asesor_texto", canal=canal, asesor="beto")
    await envios.enviar_texto(p, TEL, "gabi", origen="gabi_respuesta", canal=canal)                          # sin asesor: no cuenta
    await envios.enviar_texto(p, TEL, "otro negocio", origen="asesor_texto", canal=canal_otro, asesor="ana")   # otro negocio: no cuenta
    await mem.registrar_envio_bloqueado(nid, "asesor_texto", TEL, "texto", "motivo de prueba", asesor="ana")

    class Falla(_Proveedor):
        async def enviar_mensaje(self, *a, **k):
            return False, None

    await envios.enviar_texto(Falla(), TEL, "fallido", origen="asesor_texto", canal=canal, asesor="beto")   # fallido: no cuenta

    r = await mem.resumen_envios_por_origen(nid)
    assert r["por_asesor"] == [
        {"asesor": "beto", "mensajes": 5, "archivos": 0, "bloqueados": 0},
        {"asesor": "ana", "mensajes": 3, "archivos": 3, "bloqueados": 1},
    ]
    assert all(set(a) == {"asesor", "mensajes", "archivos", "bloqueados"} for a in r["por_asesor"])
    assert {"mes", "zona_horaria", "origenes"} <= set(r)        # el resto del contrato sigue igual


async def test_sin_envios_de_asesores_por_asesor_es_lista_vacia():
    nid, _ = await _negocio("atr-5")
    assert (await mem.resumen_envios_por_origen(nid))["por_asesor"] == []


# ── Los 4 endpoints del panel pasan usuario['username'] ─────────────────────

@pytest.fixture
def panel(monkeypatch, tmp_path):
    visto = {}

    async def lead(telefono, negocio_id=None):
        return {"telefono": telefono, "numero_whatsapp_id": "111"}

    async def ventana(telefono):
        return None

    async def guardar_mensaje(telefono, role, contenido, **kw):
        return {"id": 9, "conversation_id": "c-1"}

    async def crear_adjunto(**kw):
        return {"id": 4}

    async def emitir(_):
        return None

    p = _Proveedor()
    monkeypatch.setattr(dashboard, "obtener_lead", lead)
    monkeypatch.setattr(dashboard, "_verificar_acceso_lead", lambda usuario, lead: None)
    monkeypatch.setattr(dashboard, "_verificar_ventana_atencion", ventana)
    monkeypatch.setattr(dashboard, "obtener_proveedor", lambda: p)
    monkeypatch.setattr(dashboard.servicio_conversacion, "guardar_mensaje", guardar_mensaje)
    monkeypatch.setattr(dashboard.servicio_conversacion, "crear_archivo_adjunto", crear_adjunto)
    monkeypatch.setattr(dashboard.gestor_conexiones, "emitir_mensaje_nuevo", emitir)
    monkeypatch.setattr(dashboard, "_guardar_archivo_en_disco", lambda nombre, contenido: str(tmp_path / "f"))
    monkeypatch.setattr(dashboard, "_convertir_a_ogg_opus", lambda contenido: b"ogg")

    for nombre in ("enviar_texto", "enviar_imagen", "enviar_documento", "enviar_audio"):
        original = getattr(envios, nombre)

        def espia(*a, _original=original, _nombre=nombre, **k):
            visto.setdefault(_nombre, []).append(k.get("asesor"))
            return _original(*a, **k)

        monkeypatch.setattr(dashboard.envios, nombre, espia)
    return visto, p


def _usuario(nid):
    return {"negocio_id": nid, "username": "lelespuru", "rol": "asesor"}


async def test_responder_cliente_atribuye_al_asesor(panel):
    visto, p = panel
    nid, p.canal = await _negocio("atr-6")
    r = await dashboard.responder_cliente(TEL, mensaje="hola", mensaje_id_citado=None, usuario=_usuario(nid), _csrf=None)
    assert r.status_code == 200
    assert visto["enviar_texto"] == ["lelespuru"] and p.llamadas == ["texto"]
    assert [(f.origen, f.asesor_usuario) for f in await _filas(nid)] == [("asesor_texto", "lelespuru")]


async def test_enviar_archivo_audio_y_catalogo_atribuyen_al_asesor(panel, tmp_path):
    visto, p = panel
    nid, p.canal = await _negocio("atr-7")
    usuario = _usuario(nid)

    imagen = UploadFile(io.BytesIO(b"\x89PNGdatos"), filename="foto.png", headers={"content-type": "image/png"})
    assert (await dashboard.enviar_archivo_chat(TEL, archivo=imagen, caption="pie", usuario=usuario, _csrf=None)).status_code == 200
    documento = UploadFile(io.BytesIO(b"%PDF-1"), filename="a.pdf", headers={"content-type": "application/pdf"})
    assert (await dashboard.enviar_archivo_chat(TEL, archivo=documento, caption="", usuario=usuario, _csrf=None)).status_code == 200
    audio = UploadFile(io.BytesIO(b"webm"), filename="a.webm", headers={"content-type": "audio/webm"})
    assert (await dashboard.enviar_audio_chat(TEL, audio=audio, usuario=usuario, _csrf=None)).status_code == 200

    catalogo = tmp_path / "catalogo.pdf"
    catalogo.write_bytes(b"%PDF-1")

    async def obtener_archivo(archivo_id):
        return {"id": archivo_id, "reutilizable": True, "ruta_disco": str(catalogo), "nombre_original": "catalogo.pdf", "content_type": "application/pdf"}

    dashboard.servicio_conversacion.obtener_archivo_adjunto, original = obtener_archivo, dashboard.servicio_conversacion.obtener_archivo_adjunto
    dashboard._verificar_acceso_archivo_reutilizable, original_acceso = (lambda archivo, usuario: None), dashboard._verificar_acceso_archivo_reutilizable
    try:
        assert (await dashboard.enviar_catalogo_chat(TEL, 7, usuario=usuario, _csrf=None)).status_code == 200
    finally:
        dashboard.servicio_conversacion.obtener_archivo_adjunto = original
        dashboard._verificar_acceso_archivo_reutilizable = original_acceso

    assert visto["enviar_imagen"] == ["lelespuru"]
    assert visto["enviar_documento"] == ["lelespuru", "lelespuru"]     # el PDF subido + el catálogo reenviado
    assert visto["enviar_audio"] == ["lelespuru"]
    assert p.llamadas == ["imagen", "documento", "audio", "documento"]
    assert [(f.tipo, f.asesor_usuario) for f in await _filas(nid)] == [
        ("imagen", "lelespuru"), ("documento", "lelespuru"), ("audio", "lelespuru"), ("documento", "lelespuru"),
    ]
