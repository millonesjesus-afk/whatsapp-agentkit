# tests/test_plantilla_zona_muerta.py — plantilla automática de la "zona muerta" (2026-10-07, Q2).
#
# `atencion_atrasada.candidatos_zona_muerta` elige a quién y `scripts/plantilla_zona_muerta.py` la manda por la
# capa central de envíos (origen `plantilla_automatica`). APAGADA por defecto (`plantilla_auto_zona_muerta`).
#
# Datos sintéticos únicamente. Proveedor falso: no se llama a Meta.

import importlib.util
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import select, update

from agent import atencion_atrasada as aa
from agent import envios, plantilla_retomar, politica_envios
from agent import memory as mem
from agent.http_utils import EnvioIncierto

NUMERO = "555000222"


def lima(dia: int, hora: int, minuto: int = 0) -> datetime:
    """Instante UTC naive de una hora de Lima de octubre de 2026 (10 = sábado, 11 = domingo, 12 = lunes)."""
    return datetime(2026, 10, dia, hora, minuto) + timedelta(hours=5)


# Domingo 10:00 de Lima: el negocio está cerrado y abre el lunes a las 8:00.
DOMINGO_10 = lima(11, 10)


@pytest.fixture(autouse=True)
def _cache_limpia():
    politica_envios.limpiar_cache()
    yield
    politica_envios.limpiar_cache()


def _cargar_script():
    ruta = Path(__file__).resolve().parent.parent / "scripts" / "plantilla_zona_muerta.py"
    spec = importlib.util.spec_from_file_location("plantilla_zona_muerta", ruta)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


class _Proveedor:
    def __init__(self, nid, resultado=(True, "wamid.auto")):
        self.nid, self.resultado, self.plantillas = nid, resultado, []

    async def resolver_canal(self, numero_whatsapp_id, negocio_id=None):
        return {"negocio_id": self.nid, "phone_number_id": NUMERO}

    async def enviar_plantilla(self, telefono, nombre, parametros, idioma="es", canal=None):
        self.plantillas.append((telefono, nombre, list(parametros), idioma))
        if isinstance(self.resultado, Exception):
            raise self.resultado
        return self.resultado


async def _negocio(codigo: str):
    negocio = await mem.crear_negocio(f"Negocio {codigo}", codigo)
    canal = await mem.crear_canal_whatsapp(nombre=f"Canal {codigo}", phone_number_id=NUMERO, negocio_id=negocio["id"])
    for dia in range(7):   # lunes a sábado 8:00-19:00
        await mem.guardar_horario_atencion(negocio["id"], dia, dia <= 5, "08:00", "19:00")
    return negocio, canal


async def _lead(
    negocio, canal, telefono: str, *, asesor: str | None = "asesor1", resultado: str | None = None,
    cerrado: bool = False, nombre: str = "María Pérez", interes: str = "cocina empotrada",
):
    await mem.resolver_conversation_activa(telefono, negocio["id"], canal["id"])
    await mem.actualizar_lead(telefono, nombre=nombre, interes=interes, negocio_id=negocio["id"], numero_whatsapp_id=NUMERO)
    async with mem.async_session() as session:
        lead = await session.get(mem.Lead, telefono)
        lead.asesor_asignado = asesor
        lead.resultado = resultado
        lead.paso_flujo = "derivado_asesor"
        if cerrado:
            lead.cerrado_definitivamente_en = lima(10, 16)   # después de su último mensaje (sábado 14:00)
        await session.commit()


async def _mensaje(negocio, telefono: str, role: str, contenido: str, instante: datetime):
    m = await mem.guardar_mensaje(telefono, role, contenido, negocio["id"])
    async with mem.async_session() as session:
        await session.execute(update(mem.Mensaje).where(mem.Mensaje.id == m["id"]).values(timestamp=instante))
        await session.commit()


async def _candidatos(negocio, ahora=DOMINGO_10, **kw):
    return {c["telefono"] for c in await aa.candidatos_zona_muerta(negocio["id"], ahora, **kw)}


async def _encender(negocio, *, tope=5):
    await mem.guardar_configuracion(aa.CLAVE_AUTO_ZONA_MUERTA, "1", negocio_id=negocio["id"])
    await plantilla_retomar.configurar_plantilla(negocio["id"], "retomar_consulta", "es")
    # sin tarifa conocida la política de costo no puede estimar y frena (a propósito): se configura una
    await mem.guardar_configuracion("meta_tarifa_usd_marketing", "0.0703", negocio_id=negocio["id"])
    if tope is not None:
        await mem.guardar_configuracion_uso_meta(negocio["id"], {"envios": {"tope_mensual_usd": tope}})


async def _eventos(telefono: str):
    return [e for e in await mem.listar_eventos_lead(telefono) if e["tipo"] == aa.TIPO_EVENTO_PLANTILLA_AUTO]


async def _correr(negocio, proveedor, ahora=DOMINGO_10):
    script = _cargar_script()

    async def sin_espera():
        return None

    script.esperar_base_de_datos = sin_espera
    resumenes = await script.main(ahora=ahora, proveedor=proveedor)
    # El reloj de la prueba es simulado (`ahora`) pero el evento se escribe con la hora real: se lleva al
    # instante simulado, como pasaría en producción donde ambos relojes coinciden.
    async with mem.async_session() as session:
        await session.execute(update(mem.EventoLead).where(
            mem.EventoLead.tipo == aa.TIPO_EVENTO_PLANTILLA_AUTO, mem.EventoLead.creado < ahora,
        ).values(creado=ahora))
        await session.commit()
    return next(r for r in resumenes if r["negocio_id"] == negocio["id"])


# ── Origen de envío ─────────────────────────────────────────────────────────

def test_el_origen_automatico_existe_no_es_esencial_y_el_tipo_de_evento_cabe_en_30_caracteres():
    assert envios.ORIGENES["plantilla_automatica"] == {
        "esencial": False, "modo": "siempre", "categoria_plantilla": "marketing", "agrupar_minutos": 720,
    }
    assert len(aa.TIPO_EVENTO_PLANTILLA_AUTO) <= 30


# ── A quién ─────────────────────────────────────────────────────────────────

async def test_candidato_con_la_ventana_por_vencer_y_el_negocio_cerrado_hasta_despues():
    negocio, canal = await _negocio("zm-1")
    # sábado 14:00 → vence el domingo 14:00: a las 10:00 le quedan 4 h y el negocio abre el lunes
    await _lead(negocio, canal, "51910000001")
    await _mensaje(negocio, "51910000001", "user", "necesito una cocina", lima(10, 14))
    # sábado 17:00 → le quedan 7 h: todavía no
    await _lead(negocio, canal, "51910000002")
    await _mensaje(negocio, "51910000002", "user", "hola", lima(10, 17))
    assert await _candidatos(negocio) == {"51910000001"}


async def test_candidato_con_la_ventana_recien_cerrada_pero_no_con_una_cerrada_hace_mas_de_12_horas():
    negocio, canal = await _negocio("zm-2")
    await _lead(negocio, canal, "51910000011")   # sábado 8:00 → cerró el domingo 8:00 (hace 2 h)
    await _mensaje(negocio, "51910000011", "user", "hola", lima(10, 8))
    await _lead(negocio, canal, "51910000012")   # viernes 19:00 → cerró el sábado 19:00 (hace 15 h)
    await _mensaje(negocio, "51910000012", "user", "hola", lima(9, 19))
    assert await _candidatos(negocio) == {"51910000011"}
    assert await _candidatos(negocio, horas_despues=20) == {"51910000011", "51910000012"}


async def test_no_hay_candidatos_con_el_negocio_abierto_ni_si_alguien_abre_antes_de_que_cierre_la_ventana():
    negocio, canal = await _negocio("zm-3")
    await _lead(negocio, canal, "51910000021")
    await _mensaje(negocio, "51910000021", "user", "hola", lima(9, 17))      # sábado 12:00: aún hay quien conteste
    assert await _candidatos(negocio, ahora=lima(10, 12)) == set()

    await _lead(negocio, canal, "51910000022")
    await _mensaje(negocio, "51910000022", "user", "hola", lima(11, 10))     # vence el lunes 10:00; abren a las 8:00
    await _lead(negocio, canal, "51910000023")
    await _mensaje(negocio, "51910000023", "user", "hola", lima(11, 7))      # vence el lunes 7:00, antes de abrir
    assert await _candidatos(negocio, ahora=lima(12, 6)) == {"51910000023"}


async def test_se_excluyen_cerrados_vendidos_atendidos_y_los_que_nadie_tiene_asignado():
    negocio, canal = await _negocio("zm-4")
    hace = lima(10, 14)
    await _lead(negocio, canal, "51910000031", resultado="vendido")
    await _lead(negocio, canal, "51910000032", resultado="no_interesado")
    await _lead(negocio, canal, "51910000033", cerrado=True)
    await _lead(negocio, canal, "51910000034")                                 # un asesor ya le respondió
    await _lead(negocio, canal, "51910000035", asesor=None)                    # lo atiende Gabi sola: no espera a una persona
    await _lead(negocio, canal, "51910000036", resultado="interesado")         # este sí
    for tel in ("51910000031", "51910000032", "51910000033", "51910000034", "51910000035", "51910000036"):
        await _mensaje(negocio, tel, "user", "hola", hace)
    await _mensaje(negocio, "51910000034", "asesor", "te respondo", hace + timedelta(minutes=30))
    assert await _candidatos(negocio) == {"51910000036"}


# ── El script ───────────────────────────────────────────────────────────────

async def _escenario_basico(codigo: str):
    negocio, canal = await _negocio(codigo)
    await _lead(negocio, canal, "51920000001", asesor="lelespuru")
    await mem.crear_usuario("lelespuru", "pw12345", "Lelespuru Díaz", "asesor", negocio["id"])
    await _mensaje(negocio, "51920000001", "user", "necesito una cocina", lima(10, 14))
    return negocio, canal


async def test_apagada_por_defecto_no_envia_nada(capsys):
    negocio, _ = await _escenario_basico("zm-5")
    await plantilla_retomar.configurar_plantilla(negocio["id"], "retomar_consulta", "es")
    proveedor = _Proveedor(negocio["id"])
    r = await _correr(negocio, proveedor)
    assert r["estado"] == "apagada" and proveedor.plantillas == [] and await _eventos("51920000001") == []
    assert "apagada" in capsys.readouterr().out

    await mem.guardar_configuracion(aa.CLAVE_AUTO_ZONA_MUERTA, "0", negocio_id=negocio["id"])
    assert (await _correr(negocio, proveedor))["estado"] == "apagada" and proveedor.plantillas == []


async def test_encendida_sin_plantilla_configurada_no_envia_nada():
    negocio, _ = await _escenario_basico("zm-6")
    await mem.guardar_configuracion(aa.CLAVE_AUTO_ZONA_MUERTA, "1", negocio_id=negocio["id"])
    proveedor = _Proveedor(negocio["id"])
    assert (await _correr(negocio, proveedor))["estado"] == "sin_plantilla" and proveedor.plantillas == []


async def test_envia_una_sola_plantilla_la_anota_y_no_saca_al_cliente_de_esperando(capsys):
    negocio, _ = await _escenario_basico("zm-7")
    await _encender(negocio)
    proveedor = _Proveedor(negocio["id"])

    r = await _correr(negocio, proveedor)
    assert r["candidatos"] == 1 and r["enviadas"] == 1
    assert proveedor.plantillas == [("51920000001", "retomar_consulta", ["María", "Lelespuru Díaz", "cocina empotrada"], "es")]
    eventos = await _eventos("51920000001")
    assert len(eventos) == 1 and "Plantilla automática" in eventos[0]["descripcion"]
    assert eventos[0]["payload"]["wamid"] == "wamid.auto" and "María" in eventos[0]["payload"]["texto"]
    assert "1 enviada(s)" in capsys.readouterr().out

    # el chat no recibe el mensaje: el cliente sigue "esperando" (nadie lo atendió de verdad)
    assert {c["telefono"] for c in await mem.listar_clientes_esperando(negocio["id"], ahora=DOMINGO_10)} == {"51920000001"}

    # segunda corrida: idempotente
    r2 = await _correr(negocio, proveedor)
    assert r2["enviadas"] == 0 and r2["ya_enviadas"] == 1 and len(proveedor.plantillas) == 1


async def test_una_espera_nueva_puede_recibir_otra_plantilla():
    negocio, _ = await _escenario_basico("zm-8")
    await _encender(negocio)
    await _correr(negocio, _Proveedor(negocio["id"]))
    async with mem.async_session() as session:
        evento = (await session.execute(select(mem.EventoLead).where(mem.EventoLead.tipo == aa.TIPO_EVENTO_PLANTILLA_AUTO))).scalar_one()
        conversation_id = evento.conversation_id
        evento_creado = evento.creado
    # la espera actual empezó ANTES del evento: ya se mandó una
    assert await aa.ya_se_envio_plantilla_automatica(conversation_id, evento_creado - timedelta(hours=1))
    # el cliente volvió a escribir DESPUÉS del evento y quedó sin respuesta otra vez: es otra espera
    assert not await aa.ya_se_envio_plantilla_automatica(conversation_id, evento_creado + timedelta(hours=1))


async def test_respeta_el_tope_de_gasto_y_reintenta_cuando_se_levanta():
    negocio, _ = await _escenario_basico("zm-9")
    await _encender(negocio, tope=None)    # sin monto elegido el tope es USD 0
    proveedor = _Proveedor(negocio["id"])
    r = await _correr(negocio, proveedor)
    assert r["bloqueadas"] == 1 and r["enviadas"] == 0 and proveedor.plantillas == [] and await _eventos("51920000001") == []

    await mem.guardar_configuracion_uso_meta(negocio["id"], {"envios": {"tope_mensual_usd": 5}})
    politica_envios.limpiar_cache()
    r2 = await _correr(negocio, proveedor)
    assert r2["enviadas"] == 1 and len(await _eventos("51920000001")) == 1


async def test_el_interruptor_del_origen_en_nunca_la_frena():
    negocio, _ = await _escenario_basico("zm-10")
    await _encender(negocio)
    await mem.guardar_configuracion("envios_modo_plantilla_automatica", "nunca", negocio_id=negocio["id"])
    proveedor = _Proveedor(negocio["id"])
    r = await _correr(negocio, proveedor)
    assert r["bloqueadas"] == 1 and proveedor.plantillas == []


async def test_un_envio_fallido_no_se_anota_y_se_reintenta_pero_uno_incierto_no_se_repite():
    negocio, _ = await _escenario_basico("zm-11")
    await _encender(negocio)
    fallido = _Proveedor(negocio["id"], resultado=(False, None))
    r = await _correr(negocio, fallido)
    assert r["fallidas"] == 1 and r["enviadas"] == 0 and await _eventos("51920000001") == []

    incierto = _Proveedor(negocio["id"], resultado=EnvioIncierto("tiempo de espera agotado"))
    r2 = await _correr(negocio, incierto)
    assert r2["inciertas"] == 1 and len(await _eventos("51920000001")) == 1
    assert (await _eventos("51920000001"))[0]["payload"]["incierto"] is True

    otro = _Proveedor(negocio["id"])
    r3 = await _correr(negocio, otro)
    assert r3["ya_enviadas"] == 1 and otro.plantillas == []


async def test_con_varios_candidatos_se_envia_a_cada_uno():
    negocio, canal = await _escenario_basico("zm-12")
    await _lead(negocio, canal, "51920000002", asesor="sin_cuenta")
    await _mensaje(negocio, "51920000002", "user", "hola", lima(10, 14))
    await _encender(negocio)
    proveedor = _Proveedor(negocio["id"])
    r = await _correr(negocio, proveedor)
    assert r["candidatos"] == 2 and r["enviadas"] == 2
    assert {p[0] for p in proveedor.plantillas} == {"51920000001", "51920000002"}
    # el asesor de la segunda no tiene un nombre real en el sistema: la plantilla usa el genérico para {{2}}
    assert next(p for p in proveedor.plantillas if p[0] == "51920000002")[2][1] == "tu asesor"
