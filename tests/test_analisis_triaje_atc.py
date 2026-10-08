# tests/test_analisis_triaje_atc.py — scripts/analisis_triaje_atc.py (2026-10-08): análisis de SOLO LECTURA del triaje
# ATC. Datos sintéticos en SQLite: recall, precisión, falsos positivos, regla de tres, conteo por categoría y guarda,
# la salida no contiene PII (teléfonos, nombres, texto, ids), n<10 no muestra porcentajes, y la lectura es pura.

import importlib.util
import re
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import func, select

from agent import memory as mem


def _cargar_script():
    ruta = Path(__file__).resolve().parent.parent / "scripts" / "analisis_triaje_atc.py"
    spec = importlib.util.spec_from_file_location("analisis_triaje_atc", ruta)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


at = _cargar_script()

AHORA = datetime(2026, 10, 20, 12, 0)   # UTC naive
INICIO = datetime(2026, 10, 9, 14, 0)    # primer evento de sombra
NOMBRE_SECRETO = "NombreSecretoDeCliente"
TEXTO_SECRETO = "SECRETO-TEXTO-DE-MENSAJE"
TELEFONOS: list[str] = []


def _payload(categoria="recibo", accion="cerrar", bloqueos=(), modo="sombra"):
    return {
        "capa": "reglas", "categoria": categoria, "accion_propuesta": accion, "confianza": 0.8,
        "señales": ["recibo_palabra"], "n_msgs_cliente": 3, "n_msgs_gabi_previos": 2, "paso_flujo": None,
        "tiene_campana": False, "modo": modo, "guardas_que_bloquearon": list(bloqueos),
    }


class Sembrador:
    def __init__(self):
        self.negocio_id = self.canal_id = None
        self.n = 0
        self.convs: dict[str, str] = {}

    async def iniciar(self):
        async with mem.async_session() as s:
            neg = mem.Negocio(nombre="Negocio de prueba", codigo="t-triaje")
            s.add(neg)
            await s.flush()
            canal = mem.CanalWhatsApp(nombre="Canal", phone_number_id="999222", negocio_id=neg.id)
            s.add(canal)
            await s.commit()
            self.negocio_id, self.canal_id = neg.id, canal.id

    async def conv(
        self, creado: datetime, resultado=None, producto=None, asesor=None, paso=None, decisiones=(), cerrada_por_triaje=False,
        eventos_extra=(), contacto: str | None = None, estado: str = "activa",
    ) -> str:
        """decisiones: lista de (minutos tras `creado`, payload) → eventos `triaje_atc_sombra`."""
        self.n += 1
        telefono = contacto or f"5196{self.n:07d}"
        TELEFONOS.append(telefono)
        async with mem.async_session() as s:
            c = (await s.execute(select(mem.Contact).where(mem.Contact.telefono == telefono))).scalar_one_or_none()
            if c is None:
                c = mem.Contact(negocio_id=self.negocio_id, telefono=telefono, nombre=NOMBRE_SECRETO)
                s.add(c)
                await s.flush()
            conv = mem.Conversation(
                negocio_id=self.negocio_id, contact_id=c.id, canal_id=self.canal_id, creado=creado,
                asesor_asignado_id=asesor, paso_flujo=paso, estado=estado,
            )
            s.add(conv)
            await s.flush()
            s.add(mem.Opportunity(
                negocio_id=self.negocio_id, conversation_id=conv.id, contact_id=c.id, resultado=resultado, producto_tipo=producto,
                creado=creado,
            ))
            s.add(mem.Mensaje(
                telefono=telefono, role="user", content=TEXTO_SECRETO, negocio_id=self.negocio_id, conversation_id=conv.id, timestamp=creado,
            ))
            for minutos, payload in decisiones:
                s.add(mem.EventoLead(
                    negocio_id=self.negocio_id, conversation_id=conv.id, tipo=mem.EVENTO_TRIAJE_ATC_SOMBRA,
                    descripcion=f"x {TEXTO_SECRETO}", payload=payload, creado=creado + timedelta(minutes=minutos),
                ))
            if cerrada_por_triaje:
                s.add(mem.EventoLead(
                    negocio_id=self.negocio_id, conversation_id=conv.id, tipo=mem.EVENTO_TRIAJE_ATC_CERRADO,
                    descripcion="x", payload={"categoria": "recibo"}, creado=creado + timedelta(minutes=5),
                ))
            for tipo, minutos, payload in eventos_extra:
                s.add(mem.EventoLead(
                    negocio_id=self.negocio_id, conversation_id=conv.id, tipo=tipo, descripcion="x", payload=payload,
                    creado=creado + timedelta(minutes=minutos),
                ))
            await s.commit()
            self.convs[telefono] = conv.id
            return conv.id


async def _escenario_sombra(sem: Sembrador):
    await sem.iniciar()
    cerrar = [(5, _payload())]
    # 12 decisiones de cerrar: 10 confirmadas por una persona, 1 falso positivo (agendado), 1 sin resolver
    for i in range(10):
        await sem.conv(INICIO + timedelta(hours=i), resultado="consulta_atc", decisiones=cerrar)
    await sem.conv(INICIO + timedelta(hours=11), resultado="agendado", decisiones=cerrar)
    await sem.conv(INICIO + timedelta(hours=12), decisiones=cerrar)
    # 4 candidatas bloqueadas (no cerrar)
    for i in range(2):
        await sem.conv(INICIO + timedelta(hours=13 + i), resultado="no_califica", decisiones=[(5, _payload(accion="ninguna", bloqueos=["comercial_cuota"]))])
    await sem.conv(INICIO + timedelta(hours=15), decisiones=[(5, _payload("numero_cliente", "ninguna", ["canal_de_pruebas"]))])
    await sem.conv(INICIO + timedelta(hours=16), resultado="consulta_atc", decisiones=[(5, _payload("pago_deuda", "ninguna", ["confianza_baja"]))])
    # 3 consultas ATC que el triaje no vio nunca (sin evento): recall perdido
    for i in range(3):
        await sem.conv(INICIO + timedelta(hours=17 + i), resultado="consulta_atc")
    # una consulta ATC anterior al inicio de la medición: no entra al recall
    await sem.conv(INICIO - timedelta(days=3), resultado="consulta_atc")


# ── limite_superior_error ───────────────────────────────────────────────────────────────────────

def test_regla_de_tres():
    assert at.limite_superior_error(0, 30) == pytest.approx(0.10)
    assert at.limite_superior_error(0, 12) == pytest.approx(0.25)
    assert at.limite_superior_error(0, 2) == 1.0            # nunca más de 100 %
    assert at.limite_superior_error(0, 0) is None and at.limite_superior_error(3, 0) is None


def test_con_fallos_el_limite_es_mayor_que_la_tasa_observada_y_menor_que_uno():
    for fallos, n in ((1, 20), (2, 50), (5, 100)):
        limite = at.limite_superior_error(fallos, n)
        assert fallos / n < limite < 1
    assert at.limite_superior_error(2, 50) > at.limite_superior_error(2, 500)       # más casos, más certeza
    assert at.limite_superior_error(1, 30) > at.limite_superior_error(0, 30)        # un fallo sube el techo


def test_pct_con_menos_de_10_no_da_porcentaje():
    assert at.pct(3, 9) == "n<10" and at.pct(5, 10) == "50,0%"


# ── Resumen ─────────────────────────────────────────────────────────────────────────────────────

async def test_recall_precision_falsos_positivos_y_conteos():
    sem = Sembrador()
    await _escenario_sombra(sem)
    ini = datetime(2026, 10, 9, 0, 0)
    fin = datetime(2026, 10, 21, 0, 0)
    async with mem.async_session() as s:
        datos = await at.cargar_datos(s, ini, fin)
        await s.rollback()
    r = at.resumir(datos)

    assert r["candidatas"] == 16 and r["decision_cerrar"] == 12 and r["bloqueadas"] == 4
    assert r["desenlaces"] == {"confirmada": 10, "comercial": 1, "sin_resolver": 1}
    assert r["resueltas"] == 11 and r["falsos_positivos"] == 1
    assert r["precision"] == pytest.approx(10 / 11) and r["precision_conservadora"] == pytest.approx(10 / 12)
    assert r["error_superior"] == pytest.approx(at.limite_superior_error(1, 11))
    # recall: 10 + 1 (bloqueada por confianza) + 3 sin ver = 14 consultas ATC desde la medición; el triaje decidió cerrar en 10
    assert r["universo_recall"] == 14 and r["detectadas"] == 10 and r["recall"] == pytest.approx(10 / 14)
    assert r["por_categoria"] == {"recibo": 14, "numero_cliente": 1, "pago_deuda": 1}
    assert r["por_guarda"] == {"comercial_cuota": 2, "canal_de_pruebas": 1, "confianza_baja": 1}
    assert r["por_modo"] == {"sombra": 16}


async def test_sin_ningun_falso_positivo_se_reporta_la_regla_de_tres():
    sem = Sembrador()
    await sem.iniciar()
    for i in range(12):
        await sem.conv(INICIO + timedelta(hours=i), resultado="consulta_atc", decisiones=[(5, _payload())])
    lineas = await _informe(desde="2026-10-09", hasta="2026-10-20")
    texto = "\n".join(lineas)
    assert "Falsos positivos observados: 0 de 12 resueltas" in texto
    assert "límite superior del error (95 %): 25,0%" in texto and "regla de tres" in texto


async def test_la_etiqueta_humana_gana_sobre_las_senales_comerciales_y_cada_senal_comercial_cuenta():
    sem = Sembrador()
    await sem.iniciar()
    cerrar = [(5, _payload())]
    await sem.conv(INICIO, resultado="consulta_atc", producto="cocina", asesor="ana", decisiones=cerrar)       # humano: confirmada
    await sem.conv(INICIO + timedelta(hours=1), producto="terma", decisiones=cerrar)                           # producto cargado
    await sem.conv(INICIO + timedelta(hours=2), asesor="ana", decisiones=cerrar)                               # derivada
    await sem.conv(INICIO + timedelta(hours=3), paso="derivado_asesor", decisiones=cerrar)                     # derivada por paso
    await sem.conv(INICIO + timedelta(hours=4), resultado="vendido", decisiones=cerrar)
    await sem.conv(INICIO + timedelta(hours=5), decisiones=cerrar, eventos_extra=[("asignado_automatico", 6, {})])
    await sem.conv(INICIO + timedelta(hours=6), resultado="cartera_fnb", decisiones=cerrar)                    # otro no comercial
    async with mem.async_session() as s:
        r = at.resumir(await at.cargar_datos(s, datetime(2026, 10, 9), datetime(2026, 10, 21)))
        await s.rollback()
    assert r["desenlaces"] == {"confirmada": 1, "comercial": 5, "otro_no_comercial": 1}


async def test_varias_decisiones_de_una_conversacion_cuentan_una_vez_y_cerrar_en_cualquiera_basta():
    sem = Sembrador()
    await sem.iniciar()
    await sem.conv(INICIO, resultado="consulta_atc", decisiones=[(5, _payload(accion="ninguna", bloqueos=["comercial_cuota"])), (9, _payload())])
    async with mem.async_session() as s:
        r = at.resumir(await at.cargar_datos(s, datetime(2026, 10, 9), datetime(2026, 10, 21)))
        await s.rollback()
    assert r["candidatas"] == 1 and r["decision_cerrar"] == 1 and r["por_guarda"] == {}      # la última decisión no tenía guardas


async def test_modo_activo_cuenta_las_cerradas_por_el_triaje_y_las_reabiertas():
    sem = Sembrador()
    await sem.iniciar()
    # 3 cerradas por el triaje; una reabierta por el cliente y terminó vendiendo (el falso positivo caro)
    primera = await sem.conv(INICIO, resultado="consulta_atc", cerrada_por_triaje=True, estado="cerrada")
    await sem.conv(INICIO + timedelta(hours=1), resultado="consulta_atc", cerrada_por_triaje=True)
    await sem.conv(INICIO + timedelta(hours=2), resultado="consulta_atc", cerrada_por_triaje=True)
    telefono = next(t for t, c in sem.convs.items() if c == primera)
    await sem.conv(
        INICIO + timedelta(days=1), resultado="vendido", contacto=telefono,
        eventos_extra=[("reabierto_por_cliente", 0, {"conversation_anterior_id": primera, "resultado_anterior": "consulta_atc"})],
    )
    async with mem.async_session() as s:
        r = at.resumir(await at.cargar_datos(s, datetime(2026, 10, 9), datetime(2026, 10, 21)))
        await s.rollback()
    assert r["cerradas_por_triaje"] == 3 and r["reabiertas"] == 1 and r["reabiertas_comerciales"] == 1
    assert r["decision_cerrar"] == 3 and r["desenlaces"] == {"confirmada": 3}
    assert r["universo_recall"] == 3 and r["detectadas"] == 3


# ── Informe ─────────────────────────────────────────────────────────────────────────────────────

async def _informe(desde="2026-10-09", hasta="2026-10-20"):
    return await at.generar_informe(desde, hasta, ahora=AHORA)


async def test_la_base_vacia_avisa_que_no_hay_eventos_y_no_falla():
    lineas = await _informe()
    texto = "\n".join(lineas)
    assert "Sin eventos del triaje" in texto and "triaje_atc_modo" in texto


async def test_el_informe_completo_no_contiene_pii_ni_ids():
    sem = Sembrador()
    await _escenario_sombra(sem)
    texto = "\n".join(await _informe())
    for secreto in (NOMBRE_SECRETO, TEXTO_SECRETO, *TELEFONOS, *sem.convs.values(), sem.negocio_id):
        assert secreto not in texto
    assert not re.search(r"\b51\d{9}\b", texto)
    assert not re.search(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", texto)
    for esperado in ("PRECISIÓN", "RECALL", "POR CATEGORÍA Y POR GUARDA", "comercial_cuota", "canal_de_pruebas", "recibo", "pago_deuda"):
        assert esperado in texto


async def test_un_grupo_con_menos_de_diez_muestra_n_menor_a_10_y_no_porcentajes():
    sem = Sembrador()
    await sem.iniciar()
    for i in range(4):
        await sem.conv(INICIO + timedelta(hours=i), resultado="consulta_atc", decisiones=[(5, _payload())])
    texto = "\n".join(await _informe())
    assert "n<10" in texto and "100,0%" not in texto


async def test_la_lectura_es_pura_mismas_filas_antes_y_despues():
    sem = Sembrador()
    await _escenario_sombra(sem)

    async def cuentas():
        async with mem.async_session() as s:
            return [(await s.execute(select(func.count()).select_from(t))).scalar_one() for t in (
                mem.EventoLead, mem.Conversation, mem.Opportunity, mem.Mensaje, mem.Lead, mem.Contact)]

    antes = await cuentas()
    await _informe()
    assert await cuentas() == antes


async def test_el_rango_de_fechas_filtra_los_eventos():
    sem = Sembrador()
    await _escenario_sombra(sem)
    todo = "\n".join(await _informe("2026-10-09", "2026-10-20"))
    nada = "\n".join(await _informe("2026-10-18", "2026-10-20"))
    assert "Conversaciones con un tema detectado (candidatas)" in todo and "16" in todo
    assert "Sin eventos del triaje en el período" in nada
    with pytest.raises(ValueError):
        await _informe("2026-10-20", "2026-10-09")


def test_el_parser_valida_las_fechas():
    p = at.construir_parser()
    assert p.parse_args(["--desde", "2026-10-09"]).desde == "2026-10-09"
    with pytest.raises(SystemExit):
        p.parse_args(["--desde", "09/10/2026"])
