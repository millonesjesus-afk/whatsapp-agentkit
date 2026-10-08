# tests/test_probar_botones_interactivos.py — scripts/probar_botones_interactivos.py (Fase 0, 2026-10-08).
# Sin red: el POST a Meta (`post_a_meta`) se sustituye siempre; la base es el SQLite de pruebas con datos sintéticos.

import argparse
import importlib.util
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import func, select

from agent import memory as mem

RAIZ = Path(__file__).resolve().parent.parent
TOKEN = "TOKEN-SECRETO-DE-PRUEBA-123"
TEL = "51999000111"
PHONE_NUMBER_ID = "888777666"
AHORA = datetime(2026, 10, 8, 15, 0)  # UTC naive


def _cargar():
    spec = importlib.util.spec_from_file_location("script_probar_botones", RAIZ / "scripts" / "probar_botones_interactivos.py")
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


pb = _cargar()


def _args(**kw):
    base = dict(
        telefono=TEL, confirmar_telefono=None, caso="botones", cuerpo_largo=False, enviar=False, dry_run=False,
        reporte=False, horas=6.0, wamid=None,
    )
    base.update(kw)
    return argparse.Namespace(**base)


class Salida:
    def __init__(self):
        self.lineas: list[str] = []

    def __call__(self, texto=""):
        self.lineas.append(str(texto))

    @property
    def texto(self):
        return "\n".join(self.lineas)


class Meta:
    """Sustituto de post_a_meta: registra las llamadas y devuelve lo configurado."""
    def __init__(self, respuesta=None, excepcion=None):
        self.llamadas = []
        self.respuesta = respuesta or (200, {"messages": [{"id": "wamid.PRUEBA1"}]})
        self.excepcion = excepcion

    async def __call__(self, url, token, payload, timeout=30.0):
        self.llamadas.append({"url": url, "token": token, "payload": payload})
        if self.excepcion:
            raise self.excepcion
        return self.respuesta


@pytest.fixture
def meta(monkeypatch):
    m = Meta()
    monkeypatch.setattr(pb, "post_a_meta", m)
    return m


async def _sembrar(minutos_desde_ultimo_cliente: float | None = 60, telefono=TEL, con_canal=True, canal_activo=True,
                   numero_id=PHONE_NUMBER_ID, mensajes=()):
    """Negocio + canal + lead + mensajes. `minutos_desde_ultimo_cliente`: hace cuánto escribió el cliente (None = nunca)."""
    async with mem.async_session() as s:
        n = mem.Negocio(nombre="Negocio de prueba", codigo="t-botones")
        s.add(n)
        await s.flush()
        if con_canal:
            s.add(mem.CanalWhatsApp(
                nombre="Canal de producción", phone_number_id=PHONE_NUMBER_ID, negocio_id=n.id,
                access_token_cifrado=mem._cifrar(TOKEN), activo=canal_activo,
            ))
        s.add(mem.Lead(telefono=telefono, negocio_id=n.id, nombre="Dueño (prueba)", numero_whatsapp_id=numero_id))
        if minutos_desde_ultimo_cliente is not None:
            s.add(mem.Mensaje(
                telefono=telefono, role="user", content="hola, soy yo", negocio_id=n.id,
                timestamp=AHORA - timedelta(minutes=minutos_desde_ultimo_cliente),
            ))
        for minutos, role, contenido, extra in mensajes:
            s.add(mem.Mensaje(
                telefono=telefono, role=role, content=contenido, negocio_id=n.id,
                timestamp=AHORA - timedelta(minutes=minutos), **extra,
            ))
        await s.commit()
        return n.id


# ── Payloads ────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("caso", pb.CASOS)
def test_todos_los_casos_son_validos_y_estan_rotulados(caso):
    payload = pb.construir_payload(caso, TEL)
    assert pb.validar_payload(payload) == []
    assert payload["to"] == TEL and payload["messaging_product"] == "whatsapp"
    cuerpo = payload["text"]["body"] if caso == "texto_ref" else payload["interactive"]["body"]["text"]
    assert cuerpo.startswith("[PRUEBA]")


@pytest.mark.parametrize("caso", ["botones", "botones_emoji"])
def test_botones_maximo_3_titulos_20_ids_unicos_y_cuerpo_300(caso):
    payload = pb.construir_payload(caso, TEL)
    botones = payload["interactive"]["action"]["buttons"]
    assert payload["interactive"]["type"] == "button"
    assert len(botones) == 3
    assert all(len(b["reply"]["title"]) <= 20 for b in botones)
    ids = [b["reply"]["id"] for b in botones]
    assert len(set(ids)) == 3 and all(i.startswith("prueba_") for i in ids)
    assert len(payload["interactive"]["body"]["text"]) <= 300


def test_botones_del_diseno():
    titulos = pb.textos_visibles(pb.construir_payload("botones", TEL))
    assert titulos == ["Ver detalles", "Pagar en cuotas", "Ver otros modelos"]
    ids = [b["reply"]["id"] for b in pb.construir_payload("botones", TEL)["interactive"]["action"]["buttons"]]
    assert ids == ["prueba_ver_detalles", "prueba_pagar_cuotas", "prueba_otros_modelos"]


def test_botones_emoji_llevan_emoji_y_miden_distinto_en_utf16_y_bytes():
    titulos = pb.textos_visibles(pb.construir_payload("botones_emoji", TEL))
    assert all(any(ord(c) > 0x2000 for c in t) for t in titulos)
    caracteres, utf16, bytes_utf8 = pb.medidas_titulo(titulos[2])
    assert caracteres <= 20 < bytes_utf8 and utf16 >= caracteres


def test_lista_cuatro_filas_con_limites():
    payload = pb.construir_payload("lista", TEL)
    filas = payload["interactive"]["action"]["sections"][0]["rows"]
    assert payload["interactive"]["type"] == "list" and len(filas) == 4
    assert all(len(f["title"]) <= 24 and len(f["description"]) <= 72 for f in filas)
    assert len({f["id"] for f in filas}) == 4
    assert len(payload["interactive"]["action"]["button"]) <= 20


def test_texto_ref_es_texto_plano():
    payload = pb.construir_payload("texto_ref", TEL)
    assert payload["type"] == "text" and "interactive" not in payload


def test_cuerpo_largo_es_exactamente_300_y_valido():
    for caso in ("botones", "lista"):
        payload = pb.construir_payload(caso, TEL, cuerpo_largo=True)
        assert len(payload["interactive"]["body"]["text"]) == 300
        assert pb.validar_payload(payload) == []


def test_bsuid_usa_recipient_y_no_to():
    payload = pb.construir_payload("botones", "US.13491208655302741918")
    assert payload["recipient"] == "US.13491208655302741918" and "to" not in payload
    assert pb.validar_payload(payload) == []


def test_caso_desconocido_falla():
    with pytest.raises(ValueError):
        pb.construir_payload("carrusel", TEL)


def test_validador_rechaza_mas_de_3_botones():
    payload = pb.construir_payload("botones", TEL)
    payload["interactive"]["action"]["buttons"].append({"type": "reply", "reply": {"id": "prueba_x", "title": "Otro"}})
    assert any("entre 1 y 3 botones" in e for e in pb.validar_payload(payload))


def test_validador_rechaza_titulo_de_21_caracteres():
    payload = pb.construir_payload("botones", TEL)
    payload["interactive"]["action"]["buttons"][0]["reply"]["title"] = "x" * 21
    assert any("1 y 20 caracteres" in e for e in pb.validar_payload(payload))


def test_validador_rechaza_ids_y_titulos_repetidos():
    payload = pb.construir_payload("botones", TEL)
    botones = payload["interactive"]["action"]["buttons"]
    botones[1]["reply"]["id"] = botones[0]["reply"]["id"]
    botones[2]["reply"]["title"] = botones[0]["reply"]["title"]
    errores = pb.validar_payload(payload)
    assert any("ids de los botones" in e for e in errores) and any("títulos de los botones" in e for e in errores)


def test_validador_rechaza_cuerpo_de_1025():
    payload = pb.construir_payload("botones", TEL)
    payload["interactive"]["body"]["text"] = "[PRUEBA] " + "x" * (1025 - 9)
    assert any("1024" in e for e in pb.validar_payload(payload))
    payload["interactive"]["body"]["text"] = "[PRUEBA] " + "x" * (1024 - 9)
    assert pb.validar_payload(payload) == []


def test_validador_rechaza_lista_de_11_filas_y_acepta_10():
    payload = pb.construir_payload("lista", TEL)
    filas = payload["interactive"]["action"]["sections"][0]["rows"]
    while len(filas) < 10:
        filas.append({"id": f"prueba_fila_{len(filas) + 1}", "title": f"Fila {len(filas) + 1}"})
    assert pb.validar_payload(payload) == []
    filas.append({"id": "prueba_fila_11", "title": "Fila 11"})
    assert any("10 filas" in e for e in pb.validar_payload(payload))


def test_validador_exige_el_rotulo_de_prueba():
    payload = pb.construir_payload("texto_ref", TEL)
    payload["text"]["body"] = "Hola cliente, esto parece un mensaje real"
    assert any("[PRUEBA]" in e for e in pb.validar_payload(payload))


def test_titulos_de_prueba_incluye_botones_emoji_y_filas():
    titulos = pb.titulos_de_prueba()
    assert {"Ver detalles", "Pagar en cuotas", "Ver otros modelos"} <= titulos
    assert any("\U0001F4CB" in t for t in titulos)


# ── Argumentos y modo por defecto ───────────────────────────────────────────

def test_el_telefono_es_obligatorio_y_no_hay_valor_por_defecto():
    with pytest.raises(SystemExit):
        pb.construir_parser().parse_args(["--caso", "botones"])
    fuente = (RAIZ / "scripts" / "probar_botones_interactivos.py").read_text(encoding="utf-8")
    assert "519" not in fuente.replace("519XXXXXXXX", "")  # ningún teléfono real o ficticio embebido en el código


def test_sin_enviar_es_dry_run_por_defecto():
    assert pb.construir_parser().parse_args(["--telefono", TEL]).enviar is False


def test_validar_argumentos_incompatibles():
    assert pb.validar_argumentos(_args(enviar=True, dry_run=True))
    assert pb.validar_argumentos(_args(reporte=True, enviar=True))
    assert pb.validar_argumentos(_args(horas=0))
    assert pb.validar_argumentos(_args()) is None


def test_el_script_no_usa_la_capa_de_produccion_de_envios():
    fuente = (RAIZ / "scripts" / "probar_botones_interactivos.py").read_text(encoding="utf-8")
    codigo = "\n".join(l for l in fuente.splitlines() if l.startswith(("import ", "from ")))
    assert "agent.envios" not in codigo and "politica_envios" not in codigo


async def test_dry_run_no_envia_nada_aunque_todo_este_en_regla(meta):
    await _sembrar(60)
    sal = Salida()
    codigo = await pb.ejecutar_envio(_args(confirmar_telefono=TEL), AHORA, sal)
    assert codigo == 0 and meta.llamadas == []
    assert "DRY-RUN" in sal.texto and '"type": "interactive"' in sal.texto and "prueba_ver_detalles" in sal.texto


async def test_dry_run_avisa_si_el_envio_real_se_rechazaria(meta):
    await _sembrar(60 * 30)
    sal = Salida()
    assert await pb.ejecutar_envio(_args(), AHORA, sal) == 0
    assert meta.llamadas == [] and "SE RECHAZARÍA" in sal.texto and "CERRADA" in sal.texto


# ── Ventana y doble confirmación ────────────────────────────────────────────

async def test_se_niega_si_la_ventana_esta_cerrada(meta):
    await _sembrar(60 * 25)  # último mensaje del cliente hace 25 h
    sal = Salida()
    codigo = await pb.ejecutar_envio(_args(enviar=True, confirmar_telefono=TEL), AHORA, sal)
    assert codigo == 2 and meta.llamadas == []
    assert "NO SE ENVÍA" in sal.texto and "CERRADA" in sal.texto


async def test_se_niega_si_el_cliente_nunca_escribio(meta):
    await _sembrar(None)
    assert await pb.ejecutar_envio(_args(enviar=True, confirmar_telefono=TEL), AHORA, Salida()) == 2
    assert meta.llamadas == []


async def test_se_niega_a_enviar_a_un_telefono_sin_lead(meta):
    await _sembrar(60)
    sal = Salida()
    codigo = await pb.ejecutar_envio(_args(telefono="51888000222", enviar=True, confirmar_telefono="51888000222"), AHORA, sal)
    assert codigo == 2 and meta.llamadas == [] and "no tiene ningún lead" in sal.texto


async def test_el_toque_cuenta_como_mensaje_del_cliente_para_la_ventana(meta):
    # El cliente escribió hace 30 h pero tocó un botón hace 1 h: nuestro cálculo mantiene la ventana abierta.
    await _sembrar(60 * 30, mensajes=[(60, "user", "Ver detalles", {})])
    assert await pb.ejecutar_envio(_args(enviar=True, confirmar_telefono=TEL), AHORA, Salida()) == 0
    assert len(meta.llamadas) == 1


@pytest.mark.parametrize("confirmar", [None, "", "51999000112", "51888000222"])
async def test_sin_doble_confirmacion_o_con_otro_valor_no_envia(meta, confirmar):
    await _sembrar(60)
    sal = Salida()
    codigo = await pb.ejecutar_envio(_args(enviar=True, confirmar_telefono=confirmar), AHORA, sal)
    assert codigo == 2 and meta.llamadas == []
    assert "doble confirmación" in sal.texto


async def test_la_confirmacion_ignora_mas_y_espacios(meta):
    await _sembrar(60)
    codigo = await pb.ejecutar_envio(_args(enviar=True, telefono="+51 999 000 111", confirmar_telefono="51999000111"), AHORA, Salida())
    assert codigo == 0 and len(meta.llamadas) == 1
    assert meta.llamadas[0]["payload"]["to"] == TEL


@pytest.mark.parametrize("kw,texto", [
    ({"con_canal": False}, "no existe el canal"),
    ({"canal_activo": False}, "inactivo"),
    ({"numero_id": None}, "numero_whatsapp_id"),
])
async def test_se_niega_sin_canal_utilizable(meta, kw, texto):
    await _sembrar(60, **kw)
    sal = Salida()
    assert await pb.ejecutar_envio(_args(enviar=True, confirmar_telefono=TEL), AHORA, sal) == 2
    assert meta.llamadas == [] and texto in sal.texto


# ── Envío real (simulado) ───────────────────────────────────────────────────

async def test_envio_correcto_hace_un_solo_post_y_muestra_el_wamid(meta):
    await _sembrar(60)
    sal = Salida()
    codigo = await pb.ejecutar_envio(_args(enviar=True, confirmar_telefono=TEL, caso="lista"), AHORA, sal)
    assert codigo == 0 and len(meta.llamadas) == 1
    llamada = meta.llamadas[0]
    assert llamada["url"] == f"https://graph.facebook.com/v21.0/{PHONE_NUMBER_ID}/messages"
    assert llamada["payload"]["interactive"]["type"] == "list" and llamada["payload"]["to"] == TEL
    assert "wamid.PRUEBA1" in sal.texto and "--reporte --wamid wamid.PRUEBA1" in sal.texto


async def test_el_token_nunca_se_imprime(meta):
    await _sembrar(60)
    sal = Salida()
    await pb.ejecutar_envio(_args(enviar=True, confirmar_telefono=TEL), AHORA, sal)
    assert meta.llamadas[0]["token"] == TOKEN  # sí se usó para enviar...
    assert TOKEN not in sal.texto and "Bearer" not in sal.texto  # ...pero jamás se muestra


async def test_el_token_se_oculta_aunque_meta_lo_devuelva_en_el_error(meta):
    await _sembrar(60)
    meta.respuesta = (400, {"error": {"code": 131009, "message": f"Invalid token {TOKEN} / Bearer {TOKEN}", "error_data": {"details": TOKEN}}})
    sal = Salida()
    codigo = await pb.ejecutar_envio(_args(enviar=True, confirmar_telefono=TEL), AHORA, sal)
    assert codigo == 1
    assert TOKEN not in sal.texto and "131009" in sal.texto and "RECHAZÓ" in sal.texto


async def test_el_token_se_oculta_si_falla_la_red(meta):
    await _sembrar(60)
    meta.excepcion = RuntimeError(f"fallo con Authorization: Bearer {TOKEN}")
    sal = Salida()
    assert await pb.ejecutar_envio(_args(enviar=True, confirmar_telefono=TEL), AHORA, sal) == 1
    assert TOKEN not in sal.texto and "INCIERTO" in sal.texto and len(meta.llamadas) == 1  # un solo intento, sin reintento


def test_ocultar_secretos():
    assert TOKEN not in pb.ocultar_secretos(f"x {TOKEN} y", TOKEN)
    assert "abc.def" not in pb.ocultar_secretos("Authorization: Bearer abc.def")


async def test_payload_invalido_no_se_envia(meta, monkeypatch):
    await _sembrar(60)
    monkeypatch.setattr(pb, "CUERPO_BOTONES", "[PRUEBA] " + "x" * 1100)
    sal = Salida()
    assert await pb.ejecutar_envio(_args(enviar=True, confirmar_telefono=TEL), AHORA, sal) == 1
    assert meta.llamadas == [] and "no cumple los límites" in sal.texto


# ── Reporte (solo lectura) ──────────────────────────────────────────────────

async def _sembrar_estados(negocio_id):
    async with mem.async_session() as s:
        s.add(mem.UsoMensajeMeta(
            wamid="wamid.PRUEBA1", phone_number_id=PHONE_NUMBER_ID, negocio_id=negocio_id, destinatario=TEL, estado="read",
            enviado_en=AHORA - timedelta(minutes=50), entregado_en=AHORA - timedelta(minutes=49), leido_en=AHORA - timedelta(minutes=48),
            pricing_type="free_customer_service", pricing_categoria="service", pricing_model="PMP", pricing_billable=False,
        ))
        s.add(mem.UsoMensajeMeta(
            wamid="wamid.CONTROL", phone_number_id=PHONE_NUMBER_ID, negocio_id=negocio_id, destinatario=TEL, estado="failed",
            enviado_en=AHORA - timedelta(minutes=30), fallido_en=AHORA - timedelta(minutes=30), error_codigo=131051,
            error_titulo="Unsupported message type",
        ))
        await s.commit()


async def test_reporte_muestra_estados_pricing_toques_y_errores():
    negocio = await _sembrar(120, mensajes=[
        (47, "user", "Ver detalles", {"mensaje_id_meta": "wamid.TOQUE"}),
        (46, "assistant", "Claro, te cuento los detalles...", {}),
        (20, "user", "[unsupported]", {}),
        (10, "assistant", "[interactive]", {"via_app": True, "mensaje_id_meta": "wamid.PRUEBA1"}),
    ])
    await _sembrar_estados(negocio)
    sal = Salida()
    assert await pb.ejecutar_reporte(_args(reporte=True, wamid=["wamid.PRUEBA1"]), AHORA, sal) == 0
    t = sal.texto
    assert "free_customer_service" in t and "category=service" in t
    assert "* wamid.PRUEBA1" in t
    assert "ERROR 131051" in t and "no soportado" in t
    assert "TOQUE" in t and "TIPO NO SOPORTADO 'unsupported'" in t
    assert "ECO de coexistencia con el wamid de la PRUEBA" in t
    assert "interactivo_id y contexto_id" in t and "Mensaje no soportado (" in t and f"Mensaje de {TEL}:" in t
    assert TOKEN not in t


async def test_reporte_es_de_solo_lectura():
    negocio = await _sembrar(60, mensajes=[(5, "user", "Ver detalles", {})])
    await _sembrar_estados(negocio)

    async def conteos():
        async with mem.async_session() as s:
            return tuple([
                (await s.execute(select(func.count()).select_from(t))).scalar_one()
                for t in (mem.Mensaje, mem.UsoMensajeMeta, mem.Lead, mem.EnvioMeta, mem.EventoLead, mem.CanalWhatsApp)
            ])
    antes = await conteos()
    await pb.ejecutar_reporte(_args(reporte=True), AHORA, Salida())
    assert await conteos() == antes


async def test_reporte_de_telefono_sin_lead_ni_datos():
    sal = Salida()
    assert await pb.ejecutar_reporte(_args(reporte=True, telefono="51000000000"), AHORA, sal) == 0
    assert "no tiene lead" in sal.texto and "ninguno todavía" in sal.texto


async def test_reporte_incluye_un_wamid_pedido_aunque_este_fuera_del_periodo():
    negocio = await _sembrar(60)
    async with mem.async_session() as s:
        s.add(mem.UsoMensajeMeta(
            wamid="wamid.VIEJO", phone_number_id=PHONE_NUMBER_ID, negocio_id=negocio, destinatario=TEL, estado="sent",
            enviado_en=AHORA - timedelta(hours=40),
        ))
        await s.commit()
    sal = Salida()
    await pb.ejecutar_reporte(_args(reporte=True, wamid=["wamid.VIEJO"], horas=2), AHORA, sal)
    assert "* wamid.VIEJO" in sal.texto
