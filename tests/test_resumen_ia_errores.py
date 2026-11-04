# tests/test_resumen_ia_errores.py — El resumen del Copiloto distingue «sin saldo» y «falló» de un resumen real (2026-11-04).
#
# Antes, cuando la IA fallaba, el endpoint devolvía 200 con el texto del fallo en `resumen` y la pestaña Copiloto lo
# mostraba como si fuera el resumen del caso. Ahora el texto fijo se reconoce y viaja `error`.
import os

os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")

from types import SimpleNamespace

import pytest

from agent import brain

HISTORIAL = [{"role": "user", "content": "Hola, quiero la terma"}, {"role": "assistant", "content": "¿Ya tienes gas natural?"}]


class _ErrorApi(Exception):
    def __init__(self, status_code, mensaje, body=None):
        super().__init__(mensaje)
        self.status_code, self.message, self.body = status_code, mensaje, body


@pytest.fixture(autouse=True)
def _circuito_sin_efectos(monkeypatch):
    async def _nada(*args, **kwargs):
        return None

    monkeypatch.setattr(brain.circuito_ia, "registrar_error", _nada)


def _modelo(monkeypatch, *, respuesta=None, error=None):
    async def _crear(**kwargs):
        if error:
            raise error
        return SimpleNamespace(
            content=[SimpleNamespace(type="text", text=respuesta)],
            usage=SimpleNamespace(input_tokens=500, output_tokens=120),
        )

    monkeypatch.setattr(brain, "crear_con_modelo_economico", _crear)


async def test_un_resumen_real_vuelve_tal_cual(monkeypatch):
    _modelo(monkeypatch, respuesta="Quiere la terma. Falta confirmar el gas.")
    assert await brain.generar_resumen_conversacion(HISTORIAL) == "Quiere la terma. Falta confirmar el gas."


async def test_sin_saldo_devuelve_el_aviso_de_saldo(monkeypatch):
    _modelo(monkeypatch, error=_ErrorApi(400, "Your credit balance is too low to access the Anthropic API."))
    assert await brain.generar_resumen_conversacion(HISTORIAL) == brain.RESUMEN_SIN_SALDO


async def test_cualquier_otro_fallo_devuelve_el_aviso_generico(monkeypatch):
    _modelo(monkeypatch, error=_ErrorApi(529, "Overloaded"))
    assert await brain.generar_resumen_conversacion(HISTORIAL) == brain.RESUMEN_FALLIDO


@pytest.mark.parametrize("texto,esperado", [
    (brain.RESUMEN_SIN_SALDO, "sin_saldo"),
    (brain.RESUMEN_FALLIDO, "fallo"),
    ("Quiere la terma.", None),
])
async def test_el_endpoint_marca_el_error(monkeypatch, texto, esperado):
    from agent import dashboard

    async def _lead(telefono, negocio_id=None):
        return {"telefono": telefono, "asesor_asignado": None}

    async def _historial(telefono, limite=200):
        return HISTORIAL

    async def _resumen(historial):
        return texto

    monkeypatch.setattr(dashboard, "obtener_lead", _lead)
    monkeypatch.setattr(dashboard, "_verificar_acceso_lead", lambda usuario, lead: None)
    monkeypatch.setattr(dashboard.servicio_conversacion, "obtener_historial", _historial)
    monkeypatch.setattr(dashboard, "generar_resumen_conversacion", _resumen)

    respuesta = await dashboard.generar_resumen_ia("51987654214", usuario={"negocio_id": "n1", "username": "admin"}, _csrf=None)
    import json

    cuerpo = json.loads(respuesta.body)
    assert cuerpo == {"resumen": texto, "error": esperado}
