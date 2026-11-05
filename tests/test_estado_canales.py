"""Estado de los canales de WhatsApp para el panel (agent/estado_canales.py)."""
import uuid
from datetime import datetime, timedelta

import pytest

from agent import estado_canales as ec
from agent import memory as mem

pytestmark = pytest.mark.asyncio


class _Resp:
    def __init__(self, status, cuerpo):
        self.status_code, self._c = status, cuerpo

    def json(self):
        return self._c


@pytest.fixture(autouse=True)
def _sin_cache():
    ec._cache.clear()
    yield
    ec._cache.clear()


def _canal(token="TOKEN-SECRETO"):
    return {"id": 7, "nombre": "Cálidda Hogar", "phone_number_id": "1209916508873858", "access_token": token}


def _parchar_http(monkeypatch, respuesta=None, error=None):
    llamadas = []

    async def falso(url, **kw):
        llamadas.append((url, kw))
        if error:
            raise error
        return respuesta
    import agent.http_utils as hu
    monkeypatch.setattr(hu, "get_con_reintentos", falso)
    return llamadas


async def test_meta_ok_devuelve_numero_calidad_y_estado(monkeypatch):
    llamadas = _parchar_http(monkeypatch, _Resp(200, {
        "display_phone_number": "+51 998 317 970", "verified_name": "Cálidda Hogar", "status": "CONNECTED",
        "quality_rating": "GREEN", "messaging_limit_tier": "TIER_1K", "platform_type": "CLOUD_API"}))
    r = await ec.consultar_meta(_canal())
    assert r["ok"] and r["numero"] == "+51 998 317 970" and r["calidad"] == "GREEN" and r["estado"] == "CONNECTED"
    url, kw = llamadas[0]
    assert url.endswith("/1209916508873858") and kw["headers"]["Authorization"] == "Bearer TOKEN-SECRETO"
    assert "TOKEN-SECRETO" not in str(r)


async def test_token_vencido_da_motivo_en_castellano_sin_cuerpo_de_meta(monkeypatch):
    _parchar_http(monkeypatch, _Resp(400, {"error": {"code": 190, "message": "Error validating access token: TOKEN-SECRETO"}}))
    r = await ec.consultar_meta(_canal())
    assert r == {"ok": False, "motivo": "El token del canal venció o fue revocado. Renuévalo en «Editar canal»."}


async def test_error_generico_trunca_el_mensaje(monkeypatch):
    _parchar_http(monkeypatch, _Resp(500, {"error": {"code": 1, "message": "x" * 500}}))
    r = await ec.consultar_meta(_canal())
    assert not r["ok"] and len(r["motivo"]) < 200


async def test_sin_token_no_llama_a_meta(monkeypatch):
    llamadas = _parchar_http(monkeypatch, _Resp(200, {}))
    r = await ec.consultar_meta(_canal(token=None))
    assert r["ok"] is False and llamadas == []


async def test_una_excepcion_de_red_no_rompe(monkeypatch):
    _parchar_http(monkeypatch, error=RuntimeError("boom TOKEN-SECRETO"))
    r = await ec.consultar_meta(_canal())
    assert r == {"ok": False, "motivo": "No se pudo contactar a Meta."}


async def test_cache_de_60_segundos_y_refrescar_la_salta(monkeypatch):
    llamadas = _parchar_http(monkeypatch, _Resp(200, {"status": "CONNECTED"}))
    await ec.consultar_meta(_canal())
    await ec.consultar_meta(_canal())
    assert len(llamadas) == 1
    await ec.consultar_meta(_canal(), usar_cache=False)
    assert len(llamadas) == 2


async def test_estado_completo_une_unidad_y_ultimo_mensaje_por_numero_y_negocio(monkeypatch):
    _parchar_http(monkeypatch, _Resp(200, {"status": "CONNECTED", "quality_rating": "GREEN"}))
    nid, otro = str(uuid.uuid4()), str(uuid.uuid4())
    from sqlalchemy import insert
    async with mem.async_session() as s:
        for n in (nid, otro):
            await s.execute(insert(mem.Negocio).values(id=n, codigo=f"T{n[:6]}", nombre=f"N{n[:4]}"))
        await s.commit()
    unidad = await mem.crear_unidad_de_negocio(nid, "Hogar", "HOG")
    await mem.crear_canal_whatsapp(nombre="Hogar", phone_number_id="PN1", negocio_id=nid, access_token="t", unidad_id=unidad["id"])
    await mem.crear_canal_whatsapp(nombre="Sin mensajes", phone_number_id="PN2", negocio_id=nid, access_token="t")
    await mem.crear_canal_whatsapp(nombre="De otro", phone_number_id="PN3", negocio_id=otro, access_token="t")
    await mem.actualizar_lead("51911110001", negocio_id=nid, numero_whatsapp_id="PN1", nombre="A")
    ahora = datetime.utcnow()
    async with mem.async_session() as s:
        for tel, rol, t in (("51911110001", "user", ahora - timedelta(hours=5)), ("51911110001", "user", ahora - timedelta(hours=2)),
                            ("51911110001", "assistant", ahora - timedelta(minutes=1))):
            s.add(mem.Mensaje(telefono=tel, role=rol, content="x", timestamp=t, negocio_id=nid))
        await s.commit()
    canales = await ec.estado(nid, mem.iso_utc)
    por_nombre = {c["nombre"]: c for c in canales}
    assert set(por_nombre) == {"Hogar", "Sin mensajes"}            # no aparece el canal de otro negocio
    assert por_nombre["Hogar"]["ultimo_mensaje_recibido"] is not None   # el último de CLIENTE, no el de Gabi
    ultimo = datetime.fromisoformat(por_nombre["Hogar"]["ultimo_mensaje_recibido"].replace("Z", "+00:00")).replace(tzinfo=None)
    assert abs((ultimo - (ahora - timedelta(hours=2))).total_seconds()) < 2
    assert por_nombre["Sin mensajes"]["ultimo_mensaje_recibido"] is None
    assert por_nombre["Hogar"]["unidad"] == "Hogar" and por_nombre["Sin mensajes"]["unidad"] is None
    assert por_nombre["Hogar"]["meta"]["calidad"] == "GREEN"
    assert "access_token" not in str(canales) and "'t'" not in str(canales)
