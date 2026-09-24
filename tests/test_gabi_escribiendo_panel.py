# El panel muestra los tres puntos de "Gabi está escribiendo…" mientras ella
# prepara su respuesta (2026-09-24). Es un aviso efímero y solo visual:
# respeta el mismo filtro de acceso que `mensaje_nuevo` y, si falla, nunca
# puede impedir ni retrasar la respuesta al cliente. Datos sintéticos.

from agent import main as app_main
from agent import memory as mem
from agent.tiempo_real import GestorConexiones


class _WSFalso:
    def __init__(self):
        self.eventos_recibidos: list[dict] = []

    async def accept(self):
        pass

    async def send_json(self, evento: dict):
        self.eventos_recibidos.append(evento)

    async def close(self, code: int | None = None):
        pass


async def _negocio_con_conversacion(codigo: str, telefono_canal: str, telefono: str):
    negocio = await mem.crear_negocio(f"Negocio {codigo}", codigo)
    canal = await mem.crear_canal_whatsapp(nombre=f"Canal {codigo}", phone_number_id=telefono_canal, negocio_id=negocio["id"])
    conversation, _ = await mem.resolver_conversation_activa(telefono, negocio["id"], canal["id"])
    return negocio, canal, conversation


async def test_gabi_escribiendo_llega_solo_al_negocio_y_a_quien_puede_verla():
    negocio, _, conversation = await _negocio_con_conversacion("ge1", "40000000101", "51900500001")
    otro_negocio = await mem.crear_negocio("Otro negocio ge1", "ge1b")
    assert await mem.intentar_asignar_conversation(conversation.id, conversation.version, "asesor_dueno")

    gestor = GestorConexiones()
    ws_dueno, ws_otro_asesor, ws_admin, ws_admin_ajeno = _WSFalso(), _WSFalso(), _WSFalso(), _WSFalso()
    await gestor.conectar(ws_dueno, "asesor_dueno", "asesor", negocio["id"])
    await gestor.conectar(ws_otro_asesor, "otro_asesor", "asesor", negocio["id"])
    await gestor.conectar(ws_admin, "admin1", "admin", negocio["id"])
    await gestor.conectar(ws_admin_ajeno, "admin_ajeno", "admin", otro_negocio["id"])

    await gestor.emitir_gabi_escribiendo(conversation.id)

    for ws in (ws_dueno, ws_admin):
        assert [e["tipo"] for e in ws.eventos_recibidos] == ["gabi_escribiendo"]
        assert ws.eventos_recibidos[0]["telefono"] == "51900500001"
        assert ws.eventos_recibidos[0]["conversation_id"] == conversation.id
    assert ws_otro_asesor.eventos_recibidos == []  # asesor sin acceso a ESTA conversación
    assert ws_admin_ajeno.eventos_recibidos == []  # admin de OTRO negocio


async def test_gabi_escribiendo_sin_conversacion_no_emite_ni_falla():
    gestor = GestorConexiones()
    ws = _WSFalso()
    await gestor.conectar(ws, "admin1", "admin", "cualquiera")
    await gestor.emitir_gabi_escribiendo(None)
    await gestor.emitir_gabi_escribiendo("id-que-no-existe")
    assert ws.eventos_recibidos == []


async def test_el_aviso_desde_el_webhook_usa_la_conversacion_activa_del_telefono(monkeypatch):
    negocio, canal, conversation = await _negocio_con_conversacion("ge2", "40000000102", "51900500002")
    gestor = GestorConexiones()
    ws = _WSFalso()
    await gestor.conectar(ws, "admin1", "admin", negocio["id"])
    monkeypatch.setattr(app_main, "gestor_conexiones", gestor)

    await app_main._avisar_que_gabi_escribe("51900500002", {"negocio_id": negocio["id"]})

    assert [e["conversation_id"] for e in ws.eventos_recibidos] == [conversation.id]


async def test_si_el_aviso_falla_no_rompe_la_respuesta_al_cliente(monkeypatch):
    async def _falla(*_a, **_k):
        raise RuntimeError("panel caído")

    monkeypatch.setattr(app_main, "obtener_conversation_activa_de_telefono", _falla)
    # No debe lanzar: el aviso es solo visual.
    await app_main._avisar_que_gabi_escribe("51900500003", {"negocio_id": "n1"})


async def test_sin_canal_no_hay_a_quien_avisar_ni_error():
    await app_main._avisar_que_gabi_escribe("51900500004", None)
    await app_main._avisar_que_gabi_escribe("51900500004", {})
