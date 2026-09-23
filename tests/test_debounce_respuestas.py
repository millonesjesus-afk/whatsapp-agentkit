# tests/test_debounce_respuestas.py — Gate 2026-09-23 (fix #3 del bloque de
# 3 correcciones consolidadas): mensajes rápidos del mismo cliente se
# agrupan en UNA sola llamada a Claude en vez de una por mensaje — mismo
# patrón de "message buffering" que ManyChat/Chatwoot/n8n. Dos niveles de
# prueba: el mecanismo en sí (GestorDebounceRespuestas, sin webhook de por
# medio) y la integración end-to-end vía webhook_handler.

import asyncio
import os

os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")
os.environ.setdefault("WHATSAPP_PROVIDER", "meta")

from sqlalchemy import select
from starlette.requests import Request

from agent import main as app_main
from agent import memory as mem
from agent.debounce import GestorDebounceRespuestas
from agent.providers.base import MensajeEntrante


async def _registrar(lista: list, valor) -> None:
    lista.append(valor)


# ── GestorDebounceRespuestas — mecanismo puro, sin webhook ───────────────

async def test_cancela_la_espera_anterior_si_llega_un_mensaje_nuevo():
    gestor = GestorDebounceRespuestas(ventana_segundos=0.05)
    ejecuciones: list[str] = []

    gestor.reprogramar("k1", lambda: _registrar(ejecuciones, "primero"))
    await asyncio.sleep(0.02)  # todavía dentro de la ventana del primero
    gestor.reprogramar("k1", lambda: _registrar(ejecuciones, "segundo"))
    await asyncio.sleep(0.1)  # deja pasar la ventana del segundo

    assert ejecuciones == ["segundo"]  # el primero se canceló, nunca corrió


async def test_ejecuta_una_sola_vez_tras_la_ventana_sin_mensajes_nuevos():
    gestor = GestorDebounceRespuestas(ventana_segundos=0.03)
    ejecuciones: list[str] = []

    gestor.reprogramar("k2", lambda: _registrar(ejecuciones, "unico"))
    await asyncio.sleep(0.08)

    assert ejecuciones == ["unico"]


async def test_no_cancela_trabajo_que_ya_empezo_a_ejecutar():
    """El caso que justifica el diseño entero: si el mensaje nuevo llega
    DESPUÉS de que la ventana anterior ya venció y la llamada a Claude ya
    está en curso, esa llamada NUNCA se aborta (perdería la respuesta sin
    avisarle a nadie) — el mensaje nuevo simplemente abre su propia ventana
    independiente."""
    gestor = GestorDebounceRespuestas(ventana_segundos=0.02)
    ejecuciones: list[str] = []
    empezo = asyncio.Event()

    async def _trabajo_lento():
        empezo.set()
        await asyncio.sleep(0.08)  # simula la llamada real a Claude
        ejecuciones.append("primero_termino")

    gestor.reprogramar("k3", _trabajo_lento)
    await empezo.wait()  # esperar a que el trabajo YA haya arrancado

    gestor.reprogramar("k3", lambda: _registrar(ejecuciones, "segundo"))

    await gestor.esperar_pendientes()

    assert "primero_termino" in ejecuciones
    assert "segundo" in ejecuciones
    assert len(ejecuciones) == 2  # ambos corrieron, ninguno se perdió


async def test_claves_distintas_no_se_interfieren():
    gestor = GestorDebounceRespuestas(ventana_segundos=0.03)
    ejecuciones: list[str] = []

    gestor.reprogramar("cliente-a", lambda: _registrar(ejecuciones, "a"))
    gestor.reprogramar("cliente-b", lambda: _registrar(ejecuciones, "b"))
    await asyncio.sleep(0.08)

    assert sorted(ejecuciones) == ["a", "b"]


async def test_un_fallo_en_la_ejecucion_no_rompe_al_gestor():
    gestor = GestorDebounceRespuestas(ventana_segundos=0.02)

    async def _revienta():
        raise RuntimeError("boom")

    gestor.reprogramar("k4", _revienta)
    await gestor.esperar_pendientes()  # no debe propagar la excepción


# ── Integración vía webhook_handler — el caso real ────────────────────────

def _request() -> Request:
    cuerpo = b'{"object": "whatsapp_business_account"}'
    entregado = False

    async def recibir():
        nonlocal entregado
        if entregado:
            return {"type": "http.disconnect"}
        entregado = True
        return {"type": "http.request", "body": cuerpo, "more_body": False}

    return Request({
        "type": "http", "method": "POST", "path": "/webhook", "headers": [], "query_string": b"",
        "client": ("203.0.113.9", 1234),
    }, recibir)


class _ProveedorFalso:
    """A diferencia de otros dobles de prueba de este proyecto, este permite
    cambiar el mensaje que devuelve `parsear_webhook` entre llamadas —
    necesario para simular 2 webhooks de Meta seguidos (2 mensajes reales
    separados), no 2 mensajes dentro del mismo payload."""

    def __init__(self, canal: dict):
        self._canal = canal
        self._siguiente: MensajeEntrante | None = None
        self.enviados: list[str] = []

    def siguiente(self, mensaje: MensajeEntrante) -> None:
        self._siguiente = mensaje

    async def verificar_firma(self, request, cuerpo):
        return True

    async def parsear_webhook(self, request):
        return [self._siguiente]

    async def resolver_canal(self, numero_whatsapp_id, negocio_id=None):
        return self._canal

    async def marcar_leido_y_escribiendo(self, mensaje_id, canal=None):
        return True

    async def enviar_mensaje(self, telefono, mensaje, canal=None, mensaje_id_citado=None):
        self.enviados.append(mensaje)
        return True, "wamid.OK"


async def _armar(monkeypatch, codigo: str, telefono: str, ventana_seg: str = "0.3"):
    negocio = await mem.crear_negocio(f"Negocio {codigo}", codigo)
    canal_db = await mem.crear_canal_whatsapp(
        nombre=f"Canal {codigo}", phone_number_id=f"4099{codigo[-6:]}", negocio_id=negocio["id"],
    )
    canal = {
        "id": canal_db["id"], "negocio_id": negocio["id"], "unidad_id": None,
        "phone_number_id": canal_db["phone_number_id"], "modo": "produccion",
    }
    proveedor = _ProveedorFalso(canal)
    monkeypatch.setattr(app_main, "proveedor", proveedor)
    monkeypatch.setenv("DEBOUNCE_RESPUESTA_SEGUNDOS", ventana_seg)

    llamadas: list[dict] = []

    async def respuesta_de_gabi(mensaje, historial, lead, modo="produccion", negocio_id=None):
        llamadas.append({"mensaje": mensaje, "historial": list(historial)})
        return "¡Hola! Cuéntame más", False, None, None

    async def sin_datos(*args, **kwargs):
        return {}

    monkeypatch.setattr(app_main.servicio_inteligencia, "generar_respuesta", respuesta_de_gabi)
    monkeypatch.setattr(app_main.servicio_inteligencia, "extraer_datos_lead", sin_datos)

    return negocio, canal, proveedor, llamadas


def _mensaje(telefono: str, texto: str, mensaje_id: str, canal: dict) -> MensajeEntrante:
    return MensajeEntrante(
        telefono=telefono, texto=texto, mensaje_id=mensaje_id, es_propio=False, tipo="text",
        numero_whatsapp_id=canal["phone_number_id"],
    )


async def _mensajes_de_rol(negocio_id: str, telefono: str, role: str) -> list:
    async with mem.async_session() as session:
        resultado = await session.execute(
            select(mem.Mensaje).where(
                mem.Mensaje.negocio_id == negocio_id, mem.Mensaje.telefono == telefono, mem.Mensaje.role == role,
            ).order_by(mem.Mensaje.id)
        )
        return resultado.scalars().all()


async def test_dos_mensajes_rapidos_disparan_una_sola_llamada_a_claude(monkeypatch):
    telefono = "51905000001"
    negocio, canal, proveedor, llamadas = await _armar(monkeypatch, "g-deb-01", telefono)

    proveedor.siguiente(_mensaje(telefono, "Hola", "wamid.g-deb-01a", canal))
    await app_main.webhook_handler(_request())

    proveedor.siguiente(_mensaje(telefono, "quiero una terma de 5.5L", "wamid.g-deb-01b", canal))
    await app_main.webhook_handler(_request())

    await app_main.gestor_debounce_respuestas.esperar_pendientes()

    assert len(llamadas) == 1  # UNA sola llamada a Claude, no dos
    assert llamadas[0]["mensaje"] == "quiero una terma de 5.5L"
    assert [m["content"] for m in llamadas[0]["historial"]] == ["Hola"]
    assert proveedor.enviados == ["¡Hola! Cuéntame más"]  # una sola respuesta enviada

    mensajes_usuario = await _mensajes_de_rol(negocio["id"], telefono, "user")
    assert [m.content for m in mensajes_usuario] == ["Hola", "quiero una terma de 5.5L"]
    mensajes_gabi = await _mensajes_de_rol(negocio["id"], telefono, "assistant")
    assert len(mensajes_gabi) == 1


async def test_mensaje_del_cliente_se_guarda_de_inmediato_sin_esperar_la_respuesta(monkeypatch):
    telefono = "51905000002"
    negocio, canal, proveedor, llamadas = await _armar(monkeypatch, "g-deb-02", telefono)

    proveedor.siguiente(_mensaje(telefono, "Hola", "wamid.g-deb-02a", canal))
    await app_main.webhook_handler(_request())

    # Sin esperar el debounce todavía — el mensaje del cliente ya debe estar
    # en la base (aparece en el panel en tiempo real de inmediato).
    assert [m.content for m in await _mensajes_de_rol(negocio["id"], telefono, "user")] == ["Hola"]
    assert await _mensajes_de_rol(negocio["id"], telefono, "assistant") == []

    await app_main.gestor_debounce_respuestas.esperar_pendientes()

    assert len(await _mensajes_de_rol(negocio["id"], telefono, "assistant")) == 1


async def test_no_responde_si_un_asesor_toma_el_caso_durante_la_espera(monkeypatch):
    """Re-chequeo de seguridad de `_generar_y_enviar_respuesta_ia`: si en el
    rato que el mensaje esperó en la ventana de debounce un asesor humano
    se asignó el caso (desde el panel), Gabi NO debe pisarle la respuesta
    cuando la ventana termine."""
    telefono = "51905000003"
    negocio, canal, proveedor, llamadas = await _armar(monkeypatch, "g-deb-03", telefono)

    proveedor.siguiente(_mensaje(telefono, "Hola", "wamid.g-deb-03a", canal))
    await app_main.webhook_handler(_request())

    await mem.actualizar_lead(telefono, negocio_id=negocio["id"], numero_whatsapp_id="x")
    await mem.asignar_asesor_a_lead(telefono, "asesor1")

    await app_main.gestor_debounce_respuestas.esperar_pendientes()

    assert llamadas == []  # nunca se llamó a Claude
    assert proveedor.enviados == []


async def test_dos_telefonos_distintos_no_se_agrupan_entre_si(monkeypatch):
    negocio, canal, proveedor, llamadas = await _armar(monkeypatch, "g-deb-04", "51905000004")

    proveedor.siguiente(_mensaje("51905000004", "Hola desde A", "wamid.g-deb-04a", canal))
    await app_main.webhook_handler(_request())
    proveedor.siguiente(_mensaje("51905000005", "Hola desde B", "wamid.g-deb-04b", canal))
    await app_main.webhook_handler(_request())

    await app_main.gestor_debounce_respuestas.esperar_pendientes()

    assert len(llamadas) == 2  # cada teléfono dispara su propia llamada
    assert {c["mensaje"] for c in llamadas} == {"Hola desde A", "Hola desde B"}
