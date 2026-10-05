# tests/test_capa_central_de_envios.py — 2026-10-04, Fase A de la capa central de
# envíos: todo mensaje a un cliente pasa por agent/envios.py con la etiqueta de su
# ORIGEN, queda registrado, y los avisos de adjuntos ilegibles se agrupan
# (1 por cliente cada 10 min). No decide costos ni bloquea por gasto (Fase B).

import asyncio
import os
import re
from datetime import datetime, timedelta
from pathlib import Path

os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")
os.environ.setdefault("WHATSAPP_PROVIDER", "meta")

import pytest
from sqlalchemy import select

from agent import envios
from agent import memory as mem

RAIZ = Path(__file__).resolve().parent.parent


class _Proveedor:
    """Proveedor falso: registra cada llamada con los argumentos recibidos."""

    def __init__(self, enviado=True):
        self.llamadas, self.enviado = [], enviado

    async def enviar_mensaje(self, telefono, mensaje, canal=None, mensaje_id_citado=None):
        self.llamadas.append(("mensaje", telefono, mensaje, canal, mensaje_id_citado))
        await asyncio.sleep(0)
        return self.enviado, ("wamid.ok" if self.enviado else None)

    async def enviar_imagen(self, telefono, media_id, caption="", canal=None):
        self.llamadas.append(("imagen", telefono, media_id, caption, canal))
        return True, "wamid.img"

    async def enviar_documento(self, telefono, media_id, nombre_archivo, caption="", canal=None):
        self.llamadas.append(("documento", telefono, media_id, nombre_archivo, caption, canal))
        return True, "wamid.doc"

    async def enviar_audio(self, telefono, media_id, canal=None):
        self.llamadas.append(("audio", telefono, media_id, canal))
        return True, "wamid.aud"

    async def enviar_plantilla(self, telefono, nombre, parametros, idioma="es", canal=None):
        self.llamadas.append(("plantilla", telefono, nombre, parametros, idioma, canal))
        return True   # el proveedor real devuelve un booleano, no una tupla


async def _filas(negocio_id):
    async with mem.async_session() as s:
        return (await s.execute(select(mem.EnvioMeta).where(mem.EnvioMeta.negocio_id == negocio_id).order_by(mem.EnvioMeta.id))).scalars().all()


async def _negocio(codigo):
    n = await mem.crear_negocio(f"Negocio {codigo}", codigo)
    return n["id"], {"negocio_id": n["id"], "phone_number_id": "111"}


async def test_el_envio_llega_al_proveedor_con_los_mismos_argumentos_y_queda_registrado():
    nid, canal = await _negocio("env-1")
    p = _Proveedor()
    r = await envios.enviar_texto(p, "51911111111", "hola", origen="gabi_respuesta", canal=canal)
    assert p.llamadas == [("mensaje", "51911111111", "hola", canal, None)]
    enviado, wamid = r                      # se desempaqueta como antes
    assert (enviado, wamid, bool(r), r.bloqueado) == (True, "wamid.ok", True, False)
    [fila] = await _filas(nid)
    assert (fila.origen, fila.tipo, fila.decision, fila.wamid, fila.telefono) == ("gabi_respuesta", "texto", "enviado", "wamid.ok", "51911111111")


async def test_los_argumentos_extra_se_reenvian_y_cada_tipo_queda_con_su_tipo():
    nid, canal = await _negocio("env-2")
    p = _Proveedor()
    await envios.enviar_texto(p, "51911111112", "x", origen="asesor_texto", canal=canal, mensaje_id_citado="wamid.cita")
    await envios.enviar_imagen(p, "51911111112", "m1", "pie", origen="asesor_archivo", canal=canal)
    await envios.enviar_documento(p, "51911111112", "m2", "a.pdf", "pie", origen="asesor_archivo", canal=canal)
    await envios.enviar_audio(p, "51911111112", "m3", origen="asesor_audio", canal=canal)
    r = await envios.enviar_plantilla(p, "51911111112", "bienvenida", ["Ana"], "es", origen="plantilla_formulario", canal=canal)
    assert p.llamadas[0][4] == "wamid.cita"
    assert [x[0] for x in p.llamadas] == ["mensaje", "imagen", "documento", "audio", "plantilla"]
    assert bool(r) is True and r.wamid is None          # plantilla: el proveedor solo informa éxito
    assert [f.tipo for f in await _filas(nid)] == ["texto", "imagen", "documento", "audio", "plantilla"]


async def test_un_envio_fallido_se_registra_como_fallido_y_no_cuenta_para_agrupar():
    nid, canal = await _negocio("env-3")
    malo = _Proveedor(enviado=False)
    r = await envios.enviar_texto(malo, "51911111113", "aviso", origen="gabi_aviso_no_legible", canal=canal)
    assert (r.enviado, r.bloqueado) == (False, False)
    # el aviso fallido no impide reintentar enseguida
    bueno = _Proveedor()
    r2 = await envios.enviar_texto(bueno, "51911111113", "aviso", origen="gabi_aviso_no_legible", canal=canal)
    assert r2.enviado and not r2.bloqueado
    assert [f.decision for f in await _filas(nid)] == ["fallido", "enviado"]


async def test_si_el_proveedor_lanza_una_excepcion_se_propaga_y_la_reserva_queda_fallida():
    nid, canal = await _negocio("env-4")

    class Roto(_Proveedor):
        async def enviar_mensaje(self, *a, **k):
            raise RuntimeError("red caída")

    with pytest.raises(RuntimeError):
        await envios.enviar_texto(Roto(), "51911111114", "x", origen="gabi_respuesta", canal=canal)
    assert [f.decision for f in await _filas(nid)] == ["fallido"]


async def test_los_avisos_ilegibles_se_agrupan_un_aviso_por_cliente_cada_10_minutos():
    nid, canal = await _negocio("env-5")
    p = _Proveedor()
    r1 = await envios.enviar_texto(p, "51911111115", "no leo fotos", origen="gabi_aviso_no_legible", canal=canal)
    r2 = await envios.enviar_texto(p, "51911111115", "no leo fotos", origen="gabi_aviso_no_legible", canal=canal)
    otro = await envios.enviar_texto(p, "51911111116", "no leo fotos", origen="gabi_aviso_no_legible", canal=canal)
    assert (r1.enviado, r2.enviado, r2.bloqueado, otro.enviado) == (True, False, True, True)
    assert "agrupado" in r2.motivo and len(p.llamadas) == 2
    assert [f.decision for f in await _filas(nid)] == ["enviado", "bloqueado", "enviado"]

    # Pasados los 10 minutos vuelve a avisar.
    async with mem.async_session() as s:
        fila = (await s.execute(select(mem.EnvioMeta).where(mem.EnvioMeta.telefono == "51911111115", mem.EnvioMeta.decision == "enviado"))).scalar_one()
        fila.creado = datetime.utcnow() - timedelta(minutes=11)
        await s.commit()
    r3 = await envios.enviar_texto(p, "51911111115", "no leo fotos", origen="gabi_aviso_no_legible", canal=canal)
    assert r3.enviado


async def test_tres_adjuntos_simultaneos_producen_un_solo_aviso():
    nid, canal = await _negocio("env-6")
    p = _Proveedor()
    rs = await asyncio.gather(*[
        envios.enviar_texto(p, "51911111117", "no leo fotos", origen="gabi_aviso_no_legible", canal=canal) for _ in range(3)
    ])
    assert sorted(r.enviado for r in rs) == [False, False, True]
    assert len(p.llamadas) == 1


async def test_la_ventana_de_agrupacion_es_configurable_y_0_la_desactiva():
    nid, canal = await _negocio("env-7")
    await mem.guardar_configuracion("envios_agrupar_minutos_gabi_aviso_no_legible", "0", negocio_id=nid)
    p = _Proveedor()
    for _ in range(2):
        assert (await envios.enviar_texto(p, "51911111118", "x", origen="gabi_aviso_no_legible", canal=canal)).enviado
    assert len(p.llamadas) == 2


async def test_los_demas_origenes_nunca_se_agrupan():
    nid, canal = await _negocio("env-8")
    p = _Proveedor()
    for _ in range(3):
        assert (await envios.enviar_texto(p, "51911111119", "x", origen="gabi_respuesta", canal=canal)).enviado
    assert len(p.llamadas) == 3


async def test_un_origen_desconocido_se_rechaza_para_que_no_haya_envios_sin_etiqueta():
    with pytest.raises(ValueError):
        await envios.enviar_texto(_Proveedor(), "51911111120", "x", origen="inventado")


async def test_si_el_registro_falla_el_mensaje_se_envia_igual(monkeypatch):
    nid, canal = await _negocio("env-9")

    async def explota(*a, **k):
        raise RuntimeError("base caída")

    monkeypatch.setattr(envios, "reservar_envio_meta", explota)
    p = _Proveedor()
    r = await envios.enviar_texto(p, "51911111121", "x", origen="gabi_aviso_no_legible", canal=canal)
    assert r.enviado and len(p.llamadas) == 1


async def test_sin_canal_registra_sin_negocio_y_envia():
    p = _Proveedor()
    r = await envios.enviar_texto(p, "51911111122", "x", origen="gabi_respuesta", canal=None)
    assert r.enviado


def test_el_resultado_se_comporta_como_la_tupla_o_el_booleano_de_antes():
    ok, bloqueado = envios.ResultadoEnvio(True, "w"), envios.ResultadoEnvio(False, None, True, "m")
    assert tuple(ok) == (True, "w") and bool(ok) and not bool(bloqueado)


def test_ningun_codigo_manda_mensajes_al_cliente_saltandose_la_capa():
    """Cada envío debe llevar su origen: quien llame al proveedor directo
    (proveedor.enviar_mensaje/imagen/documento/audio/plantilla) fuera de
    agent/envios.py y de los proveedores se salta el registro y los interruptores."""
    patron = re.compile(r"\bproveedor\.enviar_(mensaje|imagen|documento|audio|plantilla)\(")
    culpables = []
    for ruta in list((RAIZ / "agent").rglob("*.py")) + list((RAIZ / "scripts").rglob("*.py")):
        if ruta.name == "envios.py" or "providers" in ruta.parts:
            continue
        for n, linea in enumerate(ruta.read_text(encoding="utf-8").splitlines(), 1):
            if patron.search(linea) and not linea.lstrip().startswith("#"):
                culpables.append(f"{ruta.relative_to(RAIZ)}:{n}")
    assert culpables == []


def test_todo_origen_usado_en_el_codigo_esta_registrado():
    usados = set()
    for ruta in list((RAIZ / "agent").rglob("*.py")) + list((RAIZ / "scripts").rglob("*.py")):
        if ruta.name == "envios.py":
            continue
        texto = ruta.read_text(encoding="utf-8")
        for llamada in re.finditer(r"envios\.enviar_\w+\(", texto):
            origen = re.search(r'origen="([a-z_]+)"', texto[llamada.end():llamada.end() + 400])
            assert origen, f"envío sin origen en {ruta.name}: {texto[llamada.start():llamada.start() + 80]!r}"
            usados.add(origen.group(1))
    assert usados and usados <= set(envios.ORIGENES)
