# tests/test_meta_webhook_sin_telefono.py — un mensaje de Meta sin `from` es un
# BSUID (Business-Scoped User ID, cliente con Usernames de WhatsApp activado,
# ver docs de Meta) — no se descarta, y ahora se usa `from_user_id` como
# identificador de enrutamiento en vez de dejar el teléfono vacío (visto en
# producción real el 2026-09-22).

import logging

from agent.providers import meta as meta_provider
from agent.providers.meta import ProveedorMeta, _destinatario, _es_bsuid


class _RespuestaFalsa:
    status_code = 200

    def json(self):
        return {"messages": [{"id": "wamid.RESPUESTA"}]}


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


async def test_mensaje_sin_from_usa_from_user_id_como_telefono(caplog):
    cuerpo = _webhook(
        {"id": "wamid.X", "type": "text", "text": {"body": "Estoy interesado en una Terma"},
         "from_user_id": "US.13491208655302741918"},
        [{"user_id": "US.13491208655302741918", "profile": {"name": "Nombre Privado"}}],
    )

    with caplog.at_level(logging.INFO, logger="agentkit"):
        mensajes = await ProveedorMeta().parsear_webhook(_RequestFalso(cuerpo))

    assert len(mensajes) == 1 and mensajes[0].telefono == "US.13491208655302741918"
    aviso = next(r.getMessage() for r in caplog.records if "BSUID" in r.getMessage())
    assert "wamid.X" in aviso
    # Nunca se loguea el valor del BSUID ni el nombre — mismo criterio de
    # privacidad que el resto de estos avisos (solo nombres de campo).
    assert "US.13491208655302741918" not in aviso and "Nombre Privado" not in aviso


async def test_mensaje_sin_from_ni_from_user_id_avisa_y_deja_telefono_vacio(caplog):
    """El caso genuinamente sin nada — ni teléfono ni BSUID — sigue avisando
    con WARNING (no INFO): acá sí no hay ningún identificador utilizable."""
    cuerpo = _webhook(
        {"id": "wamid.Z", "type": "text", "text": {"body": "Hola"}},
        [{"profile": {"name": "Alguien"}}],
    )

    with caplog.at_level(logging.WARNING, logger="agentkit"):
        mensajes = await ProveedorMeta().parsear_webhook(_RequestFalso(cuerpo))

    assert mensajes[0].telefono == ""
    aviso = next(r.getMessage() for r in caplog.records if "sin teléfono" in r.getMessage())
    assert "wamid.Z" in aviso and "from_user_id" in aviso


async def test_mensaje_con_from_no_genera_ningun_aviso(caplog):
    cuerpo = _webhook(
        {"id": "wamid.Y", "type": "text", "text": {"body": "Hola"}, "from": "51900000000"},
        [{"wa_id": "51900000000"}],
    )

    with caplog.at_level(logging.INFO, logger="agentkit"):
        mensajes = await ProveedorMeta().parsear_webhook(_RequestFalso(cuerpo))

    assert mensajes[0].telefono == "51900000000"
    assert not [r for r in caplog.records if "teléfono" in r.getMessage() or "BSUID" in r.getMessage()]


def test_es_bsuid_distingue_telefono_real_de_bsuid():
    assert _es_bsuid("US.13491208655302741918") is True
    assert _es_bsuid("51987654321") is False
    assert _es_bsuid("+51987654321") is False  # el + es el único símbolo que un teléfono real puede traer


def test_destinatario_usa_recipient_para_bsuid_y_to_para_telefono_real():
    assert _destinatario("US.13491208655302741918") == {"recipient": "US.13491208655302741918"}
    assert _destinatario("51987654321") == {"to": "51987654321"}


async def test_enviar_mensaje_manda_recipient_en_vez_de_to_para_un_bsuid(monkeypatch):
    """Extremo a extremo (Gate del 2026-09-22): responderle a un BSUID con
    `to` lo rechaza la API de Meta — el payload real que sale por HTTP tiene
    que traer `recipient`, no `to`."""
    payloads_enviados = []

    async def post_falso(url, json=None, headers=None):
        payloads_enviados.append(json)
        return _RespuestaFalsa()

    monkeypatch.setattr(meta_provider, "post_sin_duplicar", post_falso)   # los envíos ya no usan post_con_reintentos
    canal = {"access_token": "token-falso", "phone_number_id": "123"}

    enviado, wamid = await ProveedorMeta().enviar_mensaje(
        "US.13491208655302741918", "Hola, ¿en qué te ayudo?", canal=canal,
    )

    assert enviado is True and wamid == "wamid.RESPUESTA"
    assert payloads_enviados[0]["recipient"] == "US.13491208655302741918"
    assert "to" not in payloads_enviados[0]


async def test_enviar_mensaje_sigue_mandando_to_para_un_telefono_real(monkeypatch):
    payloads_enviados = []

    async def post_falso(url, json=None, headers=None):
        payloads_enviados.append(json)
        return _RespuestaFalsa()

    monkeypatch.setattr(meta_provider, "post_sin_duplicar", post_falso)
    canal = {"access_token": "token-falso", "phone_number_id": "123"}

    await ProveedorMeta().enviar_mensaje("51987654321", "Hola", canal=canal)

    assert payloads_enviados[0]["to"] == "51987654321"
    assert "recipient" not in payloads_enviados[0]
