# tests/test_reabrir_caso.py — Q3 (2026-10-07): botón "Reabrir caso". Deshace un
# cierre definitivo hecho por error (caso real Mercy 51939567302: cerrado como
# "no interesado" aunque la clienta sí quería). Limpia el cierre en Lead y
# Conversation, CONSERVA asesor, resultado y mensajes, deja a Gabi como esté y
# registra el evento `cierre_deshecho`. 409 si el cliente ya reabrió el caso.

import json
import os

os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")
os.environ.setdefault("WHATSAPP_PROVIDER", "meta")
os.environ["DEBOUNCE_RESPUESTA_SEGUNDOS"] = "0"

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from agent import dashboard
from agent import memory as mem


async def _caso_cerrado(codigo: str, telefono: str, resultado: str = "no_interesado", asesor: str = "rvilchez"):
    negocio = await mem.crear_negocio(f"Negocio {codigo}", codigo)
    canal = await mem.crear_canal_whatsapp(
        nombre=f"Canal {codigo}", phone_number_id=f"4096100{codigo[-2:]}", negocio_id=negocio["id"],
    )
    await mem.actualizar_lead(telefono, negocio_id=negocio["id"], numero_whatsapp_id="x")
    conversation, _ = await mem.resolver_conversation_activa(telefono, negocio["id"], canal["id"])
    await mem.asignar_asesor_a_lead(telefono, asesor)
    await mem.actualizar_lead(telefono, campos_explicitos=("resultado",), resultado=resultado)
    await mem.guardar_mensaje(telefono, "user", "Sí estamos interesados", negocio_id=negocio["id"])
    await mem.guardar_mensaje(telefono, "asesor", "Perfecto, te coordino", negocio_id=negocio["id"])
    assert await mem.cerrar_lead_definitivamente(telefono, negocio["id"], "angie") is True
    return negocio, canal, conversation


def _usuario(negocio, username="angie", rol="admin"):
    return {"username": username, "nombre": username, "rol": rol, "negocio_id": negocio["id"]}


async def _eventos(telefono: str, tipo: str) -> list[dict]:
    return [e for e in await mem.listar_eventos_lead(telefono) if e["tipo"] == tipo]


async def test_reabrir_limpia_el_cierre_y_conserva_asesor_resultado_y_mensajes():
    telefono = "51939567401"
    negocio, canal, conv = await _caso_cerrado("g-rc-01", telefono)
    # un "ok" absorbido tras el cierre: se conserva en la conversación
    await mem.guardar_mensaje(telefono, "user", "Oh ya ok", negocio_id=negocio["id"])

    respuesta = await dashboard.conversation_reabrir(conv.id, usuario=_usuario(negocio), _csrf=None)

    cuerpo = json.loads(respuesta.body)
    assert cuerpo["ok"] is True and cuerpo["lead"]["cerrado_definitivamente_en"] is None
    assert cuerpo["lead"]["asesor_asignado"] == "rvilchez" and cuerpo["lead"]["resultado"] == "no_interesado"
    lead = await mem.obtener_lead(telefono, negocio_id=negocio["id"])
    assert lead["cerrado_definitivamente_en"] is None
    assert lead["asesor_asignado"] == "rvilchez" and lead["resultado"] == "no_interesado"
    async with mem.async_session() as session:
        c = await session.get(mem.Conversation, conv.id)
        assert c.cerrado_definitivamente_en is None and c.estado == "activa" and c.asesor_asignado_id == "rvilchez"
        textos = [m.content for m in (await session.execute(
            select(mem.Mensaje).where(mem.Mensaje.conversation_id == conv.id).order_by(mem.Mensaje.id)
        )).scalars().all()]
    assert textos == ["Sí estamos interesados", "Perfecto, te coordino", "Oh ya ok"]
    eventos = await _eventos(telefono, "cierre_deshecho")
    assert len(eventos) == 1
    assert eventos[0]["autor"] == "angie" and eventos[0]["conversation_id"] == conv.id
    assert eventos[0]["payload"]["resultado"] == "no_interesado"
    assert eventos[0]["payload"]["asesor"] == "rvilchez"
    assert eventos[0]["payload"]["mensajes_tras_cierre"] == 1 and eventos[0]["payload"]["cierre_en"]


async def test_reabrir_deja_a_gabi_como_estaba():
    telefono = "51939567402"
    negocio, canal, conv = await _caso_cerrado("g-rc-02", telefono)
    antes = await mem.obtener_lead(telefono, negocio_id=negocio["id"])

    await dashboard.conversation_reabrir(conv.id, usuario=_usuario(negocio), _csrf=None)

    despues = await mem.obtener_lead(telefono, negocio_id=negocio["id"])
    assert despues["pausado_manual"] == antes["pausado_manual"]
    assert despues["asesor_asignado"] == antes["asesor_asignado"]
    assert await _eventos(telefono, "desasignado") == [] and await _eventos(telefono, "desasignado_automatico") == []


async def test_reabrir_un_vendido_cerrado_tambien_funciona():
    telefono = "51939567403"
    negocio, canal, conv = await _caso_cerrado("g-rc-03", telefono, resultado="vendido", asesor="sabarca")

    await dashboard.conversation_reabrir(conv.id, usuario=_usuario(negocio), _csrf=None)

    lead = await mem.obtener_lead(telefono, negocio_id=negocio["id"])
    assert lead["cerrado_definitivamente_en"] is None and lead["resultado"] == "vendido"


async def test_tras_reabrir_un_mensaje_del_cliente_ya_no_se_absorbe():
    telefono = "51939567404"
    negocio, canal, conv = await _caso_cerrado("g-rc-04", telefono)
    assert await mem.evaluar_cierre_cortesia(telefono, negocio["id"], "ok") is not None  # cerrado: se absorbería

    await dashboard.conversation_reabrir(conv.id, usuario=_usuario(negocio), _csrf=None)

    assert await mem.evaluar_cierre_cortesia(telefono, negocio["id"], "ok") is None  # abierto: es un mensaje normal


async def test_reabrir_409_si_el_cliente_ya_reabrio_el_caso_por_su_cuenta():
    telefono = "51939567405"
    negocio, canal, conv = await _caso_cerrado("g-rc-05", telefono)
    # DR-4: el cliente escribió algo real y se abrió una Conversation nueva; la vieja quedó cerrada
    nueva, _ = await mem.resolver_conversation_activa(telefono, negocio["id"], canal["id"])
    assert nueva.id != conv.id

    with pytest.raises(HTTPException) as exc:
        await dashboard.conversation_reabrir(conv.id, usuario=_usuario(negocio), _csrf=None)
    assert exc.value.status_code == 409
    assert "reabrió" in exc.value.detail
    assert await _eventos(telefono, "cierre_deshecho") == []


async def test_reabrir_409_si_el_caso_no_esta_cerrado():
    telefono = "51939567406"
    negocio, canal, conv = await _caso_cerrado("g-rc-06", telefono)
    await dashboard.conversation_reabrir(conv.id, usuario=_usuario(negocio), _csrf=None)

    with pytest.raises(HTTPException) as exc:
        await dashboard.conversation_reabrir(conv.id, usuario=_usuario(negocio), _csrf=None)  # doble clic
    assert exc.value.status_code == 409
    assert len(await _eventos(telefono, "cierre_deshecho")) == 1


async def test_reabrir_404_cross_tenant():
    negocio_a, _, conv = await _caso_cerrado("g-rc-07", "51939567407")
    negocio_b = await mem.crear_negocio("Negocio g-rc-07b", "g-rc-07b")

    with pytest.raises(HTTPException) as exc:
        await dashboard.conversation_reabrir(conv.id, usuario=_usuario(negocio_b, "admin_b"), _csrf=None)
    assert exc.value.status_code == 404
    lead = await mem.obtener_lead("51939567407", negocio_id=negocio_a["id"])
    assert lead["cerrado_definitivamente_en"] is not None


async def test_reabrir_404_si_no_existe():
    negocio = await mem.crear_negocio("Negocio g-rc-08", "g-rc-08")
    with pytest.raises(HTTPException) as exc:
        await dashboard.conversation_reabrir("no-existe", usuario=_usuario(negocio), _csrf=None)
    assert exc.value.status_code == 404


async def test_reabrir_403_asesor_ajeno_y_ok_para_el_asesor_dueno():
    telefono = "51939567409"
    negocio, canal, conv = await _caso_cerrado("g-rc-09", telefono)

    with pytest.raises(HTTPException) as exc:
        await dashboard.conversation_reabrir(conv.id, usuario=_usuario(negocio, "otro_asesor", "asesor"), _csrf=None)
    assert exc.value.status_code == 403
    assert (await mem.obtener_lead(telefono, negocio_id=negocio["id"]))["cerrado_definitivamente_en"] is not None

    respuesta = await dashboard.conversation_reabrir(conv.id, usuario=_usuario(negocio, "rvilchez", "asesor"), _csrf=None)
    assert json.loads(respuesta.body)["ok"] is True


def test_la_ruta_exige_sesion_y_csrf_igual_que_cerrar_definitivamente():
    def _dependencias(nombre: str) -> set[str]:
        ruta = next(r for r in dashboard.router.routes if getattr(r, "path", "").endswith(nombre))
        return {d.call.__name__ for d in ruta.dependant.dependencies}

    reabrir = _dependencias("/conversation/{conversation_id}/reabrir")
    cerrar = _dependencias("/conversation/{conversation_id}/cerrar-definitivamente")
    assert "verificar_csrf" in reabrir
    assert reabrir == cerrar


async def test_el_evento_de_reabrir_aparece_en_el_detalle_de_la_conversacion():
    telefono = "51939567410"
    negocio, canal, conv = await _caso_cerrado("g-rc-10", telefono)
    respuesta = await dashboard.conversation_reabrir(conv.id, usuario=_usuario(negocio), _csrf=None)
    tipos = [e["tipo"] for e in json.loads(respuesta.body)["lead"]["eventos"]]
    assert "cierre_deshecho" in tipos and "cerrado_definitivamente" in tipos
