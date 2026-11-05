"""Aviso «los anuncios dejaron de traer clientes» (agent/alertas_anuncios.py)."""
from datetime import datetime, timedelta

import pytest

from agent import alertas_anuncios as aa
from agent import dashboard

AHORA = datetime(2026, 11, 5, 12, 0, 0)
_n = 0


def _ev(horas_atras: float, source_id: str = "AD1", headline: str | None = "Secadora a gas"):
    global _n
    _n += 1
    return {"conversation_id": f"c{_n}", "source_id": source_id, "headline": headline,
            "creado": AHORA - timedelta(hours=horas_atras)}


def _historia_normal(por_dia_en_franja: int = 5, source_id: str = "AD1"):
    """`por_dia_en_franja` clientes en la franja de las 6 h previas a «ahora», cada uno de los 7 días anteriores."""
    return [_ev(24 * d + 1 + i * 0.5, source_id) for d in range(1, 8) for i in range(por_dia_en_franja)]


def test_global_sin_clientes_en_la_franja_y_con_historia_avisa_error():
    aviso = aa.evaluar_silencio_global(_historia_normal(), AHORA)
    assert aviso["id"] == "anuncios_sin_clientes" and aviso["nivel"] == "error"
    assert "6 h" in aviso["titulo"] and "unos 5" in aviso["detalle"]


def test_global_con_un_cliente_reciente_no_avisa():
    assert aa.evaluar_silencio_global(_historia_normal() + [_ev(2)], AHORA) is None


def test_global_noche_tranquila_no_avisa_porque_se_compara_la_misma_franja():
    # mucho tráfico de día, pero en la franja de ahora (la madrugada) solo 1 por día
    eventos = [_ev(24 * d + 8 + i * 0.3) for d in range(1, 8) for i in range(20)] + [_ev(24 * d + 1) for d in range(1, 8)]
    assert aa.evaluar_silencio_global(eventos, AHORA) is None


def test_global_sin_historia_suficiente_no_avisa():
    assert aa.evaluar_silencio_global(_historia_normal(por_dia_en_franja=2), AHORA) is None


def test_global_cuenta_conversaciones_distintas_no_eventos():
    eventos = _historia_normal(por_dia_en_franja=1)
    for e in list(eventos):
        eventos.append(dict(e))  # mismo conversation_id repetido (reingreso): no suma
    assert aa.evaluar_silencio_global(eventos, AHORA) is None


def test_anuncio_callado_avisa_warning_con_titulo_y_cantidad():
    eventos = [_ev(30 + i * 5, "AD1") for i in range(12)] + [_ev(2, "AD2")]
    aviso = aa.evaluar_anuncios_callados(eventos, AHORA)
    assert aviso["nivel"] == "warning" and aviso["id"] == "anuncios_callados"
    assert "1 anuncio que traía" in aviso["titulo"]
    assert "Secadora a gas" in aviso["detalle"] and "12 en 7 días" in aviso["detalle"]
    assert "pausó a propósito" in aviso["detalle"]


def test_anuncio_con_clientes_en_24h_no_avisa():
    eventos = [_ev(30 + i * 5, "AD1") for i in range(12)] + [_ev(3, "AD1")]
    assert aa.evaluar_anuncios_callados(eventos, AHORA) is None


def test_anuncio_con_pocos_previos_no_avisa():
    assert aa.evaluar_anuncios_callados([_ev(30 + i, "AD1") for i in range(9)], AHORA) is None


def test_anuncio_sin_trafico_hace_mas_de_8_dias_sale_solo():
    assert aa.evaluar_anuncios_callados([_ev(24 * 9 + i, "AD1") for i in range(15)], AHORA) is None


def test_lista_solo_tres_ordenados_por_volumen_y_cuenta_el_resto():
    eventos = []
    for k, n in enumerate((20, 15, 12, 11, 10)):
        eventos += [_ev(30 + i * 3, f"AD{k}", f"Anuncio {k}") for i in range(n)]
    aviso = aa.evaluar_anuncios_callados(eventos, AHORA)
    assert aviso["titulo"].startswith("5 anuncios que traían")
    assert aviso["detalle"].index("Anuncio 0") < aviso["detalle"].index("Anuncio 1") < aviso["detalle"].index("Anuncio 2")
    assert "Anuncio 3" not in aviso["detalle"] and "y 2 más" in aviso["detalle"]


async def test_avisos_sin_eventos_no_vigila_nada(monkeypatch):
    async def vacio(*_a, **_k):
        return []
    monkeypatch.setattr(aa, "leer_eventos", vacio)
    assert await aa.avisos("n1", AHORA) == []


async def test_avisos_junta_ambas_senales(monkeypatch):
    eventos = _historia_normal() + [_ev(30 + i * 5, "AD9", "Otro") for i in range(12)]

    async def leer(*_a, **_k):
        return eventos
    monkeypatch.setattr(aa, "leer_eventos", leer)
    ids = [a["id"] for a in await aa.avisos("n1", AHORA)]
    assert ids == ["anuncios_sin_clientes", "anuncios_callados"]


async def test_un_fallo_no_rompe_inicio(monkeypatch):
    async def boom(*_a, **_k):
        raise RuntimeError("bd caída")
    monkeypatch.setattr(aa, "leer_eventos", boom)
    assert await dashboard._avisos_anuncios_sin_clientes("n1") == []


async def test_solo_el_admin_recibe_el_aviso(monkeypatch):
    async def avisos(_n):
        return [{"id": "anuncios_sin_clientes", "nivel": "error", "titulo": "x", "detalle": "y", "enlace": None}]
    monkeypatch.setattr(dashboard, "_avisos_anuncios_sin_clientes", avisos)
    for nombre in ("_avisos_circuito_ia", "_avisos_procesos_programados", "_avisos_uso_inicio", "_avisos_llamadas",
                   "_avisos_cambios_calendario_supervisor", "_avisos_campanas_sin_material"):
        async def vacio(*_a, **_k):
            return []
        monkeypatch.setattr(dashboard, nombre, vacio)
    admin = await dashboard._avisos_inicio({"rol": "admin", "negocio_id": "n1"})
    sup = await dashboard._avisos_inicio({"rol": "supervisor", "negocio_id": "n1"})
    assert [a["id"] for a in admin] == ["anuncios_sin_clientes"] and sup == []


async def test_lectura_real_filtra_por_negocio_y_tipo_de_origen():
    from agent import memory as mem
    from sqlalchemy import insert
    import uuid
    n1, n2 = str(uuid.uuid4()), str(uuid.uuid4())
    async with mem.async_session() as s:
        for nid in (n1, n2):
            await s.execute(insert(mem.Negocio).values(id=nid, codigo=f"T{nid[:6]}", nombre=f"N{nid[:4]}"))
        await s.commit()
        filas = [
            (n1, "meta_ads", "A1", AHORA - timedelta(hours=1)),
            (n1, "wa_link", "A2", AHORA - timedelta(hours=1)),                 # no es anuncio
            (n1, "meta_ads", "A3", AHORA - timedelta(days=9)),                 # fuera de ventana
            (n2, "meta_ads", "A4", AHORA - timedelta(hours=1)),                # otro negocio
        ]
        for nid, tipo, sid, t in filas:
            await s.execute(insert(mem.AttributionEvent).values(
                negocio_id=nid, conversation_id=str(uuid.uuid4()), lead_telefono="51900000000", tipo_origen=tipo,
                source_id=sid, creado=t, first_touch=False))
        await s.commit()
    assert [e["source_id"] for e in await aa.leer_eventos(n1, AHORA)] == ["A1"]
