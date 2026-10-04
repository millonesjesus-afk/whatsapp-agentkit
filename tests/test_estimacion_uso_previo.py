# tests/test_estimacion_uso_previo.py — 2026-10-04: estimar cuántos mensajes de
# servicio gratis (cuota de 1000) se consumieron antes de que el registro de
# estados de Meta empezara a medir, con los mensajes y referrals guardados.
#
# Reglas que se protegen: cuentan los envíos por API (Gabi y asesores del
# panel), no los de la app de WhatsApp Business ni los fallidos; los que caen
# en el intervalo gratuito de un anuncio no consumen cuota; una respuesta libre
# dentro de 24 h del cliente sí; sin mensaje del cliente en 24 h es plantilla.

import json
import os
from datetime import datetime, timedelta

os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")
os.environ.setdefault("WHATSAPP_PROVIDER", "meta")

import pytest
from fastapi import HTTPException

from agent import dashboard
from agent import memory as mem

T0 = datetime(2026, 10, 1, 12, 0, 0)
DESDE, HASTA = datetime(2026, 10, 1), datetime(2026, 10, 5)
H = lambda n: timedelta(hours=n)


async def _negocio(codigo: str):
    return await mem.crear_negocio(f"Negocio {codigo}", codigo)


async def _msg(negocio_id, telefono, role, ts, via_app=False, estado=None):
    async with mem.async_session() as s:
        s.add(mem.Mensaje(
            telefono=telefono, role=role, content="x", timestamp=ts, via_app=via_app,
            estado_envio=estado, negocio_id=negocio_id,
        ))
        await s.commit()


async def _anuncio(negocio_id, telefono, ts, tipo="meta_ads"):
    async with mem.async_session() as s:
        s.add(mem.AttributionEvent(
            negocio_id=negocio_id, conversation_id="c-" + telefono, lead_telefono=telefono,
            tipo_origen=tipo, creado=ts,
        ))
        await s.commit()


async def test_un_envio_dentro_de_24h_del_cliente_sin_anuncio_consume_la_cuota():
    n = await _negocio("est-1")
    await _msg(n["id"], "51900000001", "user", T0)
    await _msg(n["id"], "51900000001", "assistant", T0 + H(1))
    await _msg(n["id"], "51900000001", "asesor", T0 + H(2))      # el asesor del panel también va por la API
    r = await mem.estimar_uso_previo_servicio(n["id"], DESDE, HASTA)
    assert r["salientes_api"] == 2
    assert r["por_duracion_ventana_horas"]["72"] == {"ventana_anuncio": 0, "servicio": 2, "fuera_de_ventana_24h": 0}
    assert r["consumo_cuota_estimado"] == {"minimo": 2, "maximo": 2}


async def test_no_cuentan_los_de_la_app_los_fallidos_ni_los_de_fuera_del_periodo():
    n = await _negocio("est-2")
    await _msg(n["id"], "51900000002", "user", T0)
    await _msg(n["id"], "51900000002", "assistant", T0 + H(1), via_app=True)         # coexistencia
    await _msg(n["id"], "51900000002", "assistant", T0 + H(2), estado="fallido")
    await _msg(n["id"], "51900000002", "assistant", DESDE - H(1))                      # antes del periodo
    await _msg(n["id"], "51900000002", "assistant", HASTA + H(1))                      # después del periodo
    await _msg(n["id"], "51900000002", "assistant", T0 + H(3))                         # el único válido
    r = await mem.estimar_uso_previo_servicio(n["id"], DESDE, HASTA)
    assert r["salientes_api"] == 1


async def test_sin_mensaje_del_cliente_en_24h_es_plantilla_y_no_consume_cuota_de_servicio():
    n = await _negocio("est-3")
    await _msg(n["id"], "51900000003", "user", T0)
    await _msg(n["id"], "51900000003", "assistant", T0 + H(30))
    r = await mem.estimar_uso_previo_servicio(n["id"], DESDE, HASTA)
    assert r["por_duracion_ventana_horas"]["72"] == {"ventana_anuncio": 0, "servicio": 0, "fuera_de_ventana_24h": 1}


async def test_el_intervalo_del_anuncio_se_abre_con_la_primera_respuesta_y_dura_lo_que_se_prueba():
    n = await _negocio("est-4")
    tel = "51900000004"
    await _anuncio(n["id"], tel, T0)
    await _msg(n["id"], tel, "user", T0)
    await _msg(n["id"], tel, "assistant", T0 + H(1))        # abre el intervalo
    await _msg(n["id"], tel, "assistant", T0 + H(30))       # dentro de 72 h
    # El cliente vuelve a escribir a las 95 h: el envío siguiente cae fuera de 72 h pero dentro de 7 días.
    await _msg(n["id"], tel, "user", T0 + H(95))
    await _msg(n["id"], tel, "assistant", T0 + H(96))
    r = await mem.estimar_uso_previo_servicio(n["id"], DESDE, HASTA + H(24))
    assert r["por_duracion_ventana_horas"]["72"] == {"ventana_anuncio": 2, "servicio": 1, "fuera_de_ventana_24h": 0}
    assert r["por_duracion_ventana_horas"]["168"] == {"ventana_anuncio": 3, "servicio": 0, "fuera_de_ventana_24h": 0}
    assert r["consumo_cuota_estimado"] == {"minimo": 0, "maximo": 1}
    assert r["conversaciones_con_anuncio"] == 1


async def test_el_anuncio_sin_respuesta_en_24h_no_abre_intervalo():
    n = await _negocio("est-5")
    tel = "51900000005"
    await _anuncio(n["id"], tel, T0)
    await _msg(n["id"], tel, "user", T0)
    await _msg(n["id"], tel, "user", T0 + H(26))
    await _msg(n["id"], tel, "assistant", T0 + H(27))       # primera respuesta, pero pasadas las 24 h del anuncio
    r = await mem.estimar_uso_previo_servicio(n["id"], DESDE, HASTA)
    assert r["por_duracion_ventana_horas"]["72"] == {"ventana_anuncio": 0, "servicio": 1, "fuera_de_ventana_24h": 0}


async def test_el_referral_no_resuelto_tambien_abre_intervalo_y_otro_negocio_no_se_mezcla():
    a, b = await _negocio("est-6a"), await _negocio("est-6b")
    tel = "51900000006"
    await _anuncio(a["id"], tel, T0, tipo="meta_ads_no_resuelto")
    await _msg(a["id"], tel, "user", T0)
    await _msg(a["id"], tel, "assistant", T0 + H(1))
    await _msg(b["id"], "51900000099", "user", T0)
    await _msg(b["id"], "51900000099", "assistant", T0 + H(1))
    r = await mem.estimar_uso_previo_servicio(a["id"], DESDE, HASTA)
    assert r["salientes_api"] == 1 and r["por_duracion_ventana_horas"]["72"]["ventana_anuncio"] == 1


async def test_un_negocio_sin_mensajes_devuelve_ceros():
    n = await _negocio("est-7")
    r = await mem.estimar_uso_previo_servicio(n["id"], DESDE, HASTA)
    assert r["salientes_api"] == 0 and r["consumo_cuota_estimado"] == {"minimo": 0, "maximo": 0}


async def test_la_ruta_valida_las_fechas_y_por_defecto_llega_hasta_el_primer_estado_registrado():
    n = await _negocio("est-8")
    admin = {"negocio_id": n["id"], "rol": "admin"}
    await _msg(n["id"], "51900000008", "user", datetime(2026, 10, 2, 10))
    await _msg(n["id"], "51900000008", "assistant", datetime(2026, 10, 2, 11))
    assert await mem.registrar_estado_mensaje_meta({
        "wamid": "wamid.est8", "estado": "delivered", "momento": datetime(2026, 10, 3, 12), "phone_number_id": "1",
        "destinatario": "x", "pricing": None, "negocio_id": n["id"],
    })
    # sin 'desde': inicio del mes; sin 'hasta': primer estado registrado (creado = ahora → incluye todo)
    datos = json.loads((await dashboard.uso_mensajes_estimacion_previa_json(desde="2026-10-01T00:00", usuario=admin)).body)
    assert datos["salientes_api"] == 1
    for malo in ("ayer", "2026-13-01"):
        with pytest.raises(HTTPException) as e:
            await dashboard.uso_mensajes_estimacion_previa_json(desde=malo, usuario=admin)
        assert e.value.status_code == 400
    with pytest.raises(HTTPException) as e:
        await dashboard.uso_mensajes_estimacion_previa_json(desde="2026-10-05T00:00", hasta="2026-10-04T00:00", usuario=admin)
    assert e.value.status_code == 400
