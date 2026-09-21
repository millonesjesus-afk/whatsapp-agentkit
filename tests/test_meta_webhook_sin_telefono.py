# tests/test_meta_webhook_sin_telefono.py — un mensaje de Meta sin `from` (visto en
# producción el 2026-09-17 y 2026-09-20, ambos leads reales) no se descarta, pero
# deja un aviso con los NOMBRES de campo que sí llegaron para poder diagnosticarlo.

import logging

from agent.providers.meta import ProveedorMeta


class _RequestFalso:
    def __init__(self, cuerpo: dict):
        self._cuerpo = cuerpo

    async def json(self):
        return self._cuerpo


def _webhook(mensaje: dict, contactos: list[dict]) -> dict:
    return {"entry": [{"changes": [{"value": {
        "metadata": {"phone_number_id": "123"},
        "contacts": contactos,
        "messages": [mensaje],
    }}]}]}


async def test_mensaje_sin_from_no_se_descarta_y_avisa_los_campos(caplog):
    cuerpo = _webhook(
        {"id": "wamid.X", "type": "text", "text": {"body": "Estoy interesado en una Terma"},
         "from_user_id": "BSUID-SECRETO"},
        [{"user_id": "BSUID-SECRETO", "profile": {"name": "Nombre Privado"}}],
    )

    with caplog.at_level(logging.WARNING, logger="agentkit"):
        mensajes = await ProveedorMeta().parsear_webhook(_RequestFalso(cuerpo))

    assert len(mensajes) == 1 and mensajes[0].telefono == ""
    aviso = next(r.getMessage() for r in caplog.records if "sin teléfono" in r.getMessage())
    assert "wamid.X" in aviso and "from_user_id" in aviso and "user_id" in aviso
    assert "BSUID-SECRETO" not in aviso and "Nombre Privado" not in aviso


async def test_mensaje_con_from_no_genera_aviso(caplog):
    cuerpo = _webhook(
        {"id": "wamid.Y", "type": "text", "text": {"body": "Hola"}, "from": "51900000000"},
        [{"wa_id": "51900000000"}],
    )

    with caplog.at_level(logging.WARNING, logger="agentkit"):
        mensajes = await ProveedorMeta().parsear_webhook(_RequestFalso(cuerpo))

    assert mensajes[0].telefono == "51900000000"
    assert not [r for r in caplog.records if "sin teléfono" in r.getMessage()]
