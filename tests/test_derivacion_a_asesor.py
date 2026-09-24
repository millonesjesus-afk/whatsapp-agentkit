# tests/test_derivacion_a_asesor.py — hallazgo real de una demo (2026-09-23):
# un lead que YA había sido derivado antes, cuya asignación se liberó, volvía
# a pedir "pásame con un asesor" y Gabi no lo asignaba ni avisaba al equipo
# (la regla exigía que el lead "acabara de pasar" a derivado). Ahora decide
# por hechos: derivado + sin asesor -> se asigna. Además, si el sistema deriva
# y la respuesta de Gabi no lo dice, se le avisa al cliente.

import os

os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")
os.environ.setdefault("WHATSAPP_PROVIDER", "meta")

from sqlalchemy import select

from agent import brain
from agent import main as app_main
from agent import memory as mem


class _ProveedorFalso:
    def __init__(self):
        self.enviados: list[str] = []

    async def enviar_mensaje(self, telefono, mensaje, canal=None, mensaje_id_citado=None):
        self.enviados.append(mensaje)
        return True, "wamid.OK"


async def _armar(monkeypatch, codigo: str, telefono: str, respuesta: str, ya_derivado: bool, con_asesor_disponible=True):
    negocio = await mem.crear_negocio(f"Negocio {codigo}", codigo)
    canal_db = await mem.crear_canal_whatsapp(
        nombre=f"Canal {codigo}", phone_number_id=f"4098{codigo[-6:]}", negocio_id=negocio["id"],
    )
    canal = {"id": canal_db["id"], "negocio_id": negocio["id"], "unidad_id": None,
             "phone_number_id": canal_db["phone_number_id"], "modo": "produccion"}
    await mem.actualizar_lead(telefono, negocio_id=negocio["id"], numero_whatsapp_id="x")
    _, _ = await mem.resolver_conversation_activa(telefono, negocio["id"], canal_db["id"])
    if ya_derivado:
        # Derivado antes, asignación liberada después: el estado que dejó la demo.
        await mem.actualizar_lead(telefono, negocio_id=negocio["id"], paso_flujo="derivado_asesor")
    await mem.guardar_mensaje(telefono, "user", "pásame con un asesor", negocio_id=negocio["id"])

    proveedor = _ProveedorFalso()
    monkeypatch.setattr(app_main, "proveedor", proveedor)
    correos: list[str] = []

    async def gabi(mensaje, historial, lead, modo="produccion", negocio_id=None):
        return respuesta, False, None, None

    async def deriva(*a, **k):
        return {"paso_flujo": "derivado_asesor"}

    async def notificar(telefono, lead, texto):
        correos.append(telefono)

    async def asesor_auto(interes, negocio_id):
        return "asesorx" if con_asesor_disponible else None

    monkeypatch.setattr(app_main.servicio_inteligencia, "generar_respuesta", gabi)
    monkeypatch.setattr(app_main.servicio_inteligencia, "extraer_datos_lead", deriva)
    monkeypatch.setattr(app_main, "notificar_lead_derivado", notificar)
    monkeypatch.setattr(app_main.servicio_comercial, "elegir_asesor_automatico", asesor_auto)
    return negocio, canal, proveedor, correos


async def _lead(telefono):
    async with mem.async_session() as session:
        return await session.get(mem.Lead, telefono)


async def test_lead_ya_derivado_antes_vuelve_a_pedir_asesor_y_se_asigna(monkeypatch):
    negocio, canal, proveedor, correos = await _armar(
        monkeypatch, "g-der-01", "51930000001", "Te derivo con un asesor comercial 😊", ya_derivado=True,
    )
    await app_main._generar_y_enviar_respuesta_ia("51930000001", canal)
    assert (await _lead("51930000001")).asesor_asignado == "asesorx"
    assert correos == ["51930000001"]  # asignado ahora -> se avisa al equipo


async def test_primera_derivacion_sigue_asignando_y_avisando(monkeypatch):
    negocio, canal, proveedor, correos = await _armar(
        monkeypatch, "g-der-02", "51930000002", "Te derivo con un asesor comercial 😊", ya_derivado=False,
    )
    await app_main._generar_y_enviar_respuesta_ia("51930000002", canal)
    assert (await _lead("51930000002")).asesor_asignado == "asesorx"
    assert correos == ["51930000002"]


async def test_cliente_que_insiste_sin_asesor_disponible_no_dispara_otro_correo(monkeypatch):
    negocio, canal, proveedor, correos = await _armar(
        monkeypatch, "g-der-03", "51930000003", "Un asesor te contactará 😊", ya_derivado=True,
        con_asesor_disponible=False,
    )
    await app_main._generar_y_enviar_respuesta_ia("51930000003", canal)
    assert (await _lead("51930000003")).asesor_asignado is None
    assert correos == []  # ya se avisó en este ciclo y no se asignó a nadie


async def test_si_gabi_no_menciona_al_asesor_se_envia_el_aviso_de_respaldo(monkeypatch):
    negocio, canal, proveedor, correos = await _armar(
        monkeypatch, "g-der-04", "51930000004", "Claro, sigue con tu consulta 😊", ya_derivado=False,
    )
    await app_main._generar_y_enviar_respuesta_ia("51930000004", canal)
    assert len(proveedor.enviados) == 2
    assert "asesor" in proveedor.enviados[1].lower()
    assert "derivando" in proveedor.enviados[1].lower()


async def test_si_gabi_ya_lo_dijo_no_se_duplica_el_aviso(monkeypatch):
    negocio, canal, proveedor, correos = await _armar(
        monkeypatch, "g-der-05", "51930000005", "Te derivo con un asesor comercial 😊", ya_derivado=False,
    )
    await app_main._generar_y_enviar_respuesta_ia("51930000005", canal)
    assert len(proveedor.enviados) == 1


def test_el_aviso_de_respaldo_distingue_dentro_y_fuera_de_horario():
    dentro = brain.obtener_mensaje_derivacion(True)
    fuera = brain.obtener_mensaje_derivacion(False)
    assert dentro != fuera
    assert "horario" in fuera.lower()
