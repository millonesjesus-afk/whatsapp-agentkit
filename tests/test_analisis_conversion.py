# tests/test_analisis_conversion.py — scripts/analisis_conversion.py (2026-10-07): análisis de solo lectura.
# Datos sintéticos en SQLite: cada sección imprime con base vacía y con datos, la salida no contiene PII
# (teléfonos, nombres, texto de mensajes, ids de conversación), n<10 no muestra porcentajes, la lectura es
# pura (mismas filas antes y después) y los argumentos de fecha filtran como se espera.

import importlib.util
import re
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import func, select

from agent import memory as mem


def _cargar_script():
    ruta = Path(__file__).resolve().parent.parent / "scripts" / "analisis_conversion.py"
    spec = importlib.util.spec_from_file_location("analisis_conversion", ruta)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


ac = _cargar_script()

AHORA = datetime(2026, 10, 6, 12, 0)  # UTC naive
BASE = datetime(2026, 9, 20, 14, 0)  # domingo 09:00 Lima
TEXTO_SECRETO = "SECRETO-TEXTO-DE-MENSAJE"
NOMBRE_SECRETO = "NombreSecretoDeCliente"
TEXTO_LARGO = TEXTO_SECRETO + " " + ("x" * 260) + " ¿te parece?"
TEXTO_PRECIO = TEXTO_SECRETO + " El precio es S/ 1,299 en total."
TEXTO_NEGRITA = TEXTO_SECRETO + " **oferta** disponible."

TELEFONOS: list[str] = []


class Sembrador:
    def __init__(self):
        self.negocio_id = None
        self.canal_id = None
        self.contactos: dict[str, str] = {}
        self.conversaciones: list[str] = []
        self.leads: dict[str, dict] = {}

    async def iniciar(self):
        async with mem.async_session() as s:
            n = mem.Negocio(nombre="Negocio de prueba", codigo="t-analisis")
            s.add(n)
            await s.flush()
            canal = mem.CanalWhatsApp(nombre="Canal", phone_number_id="999111", negocio_id=n.id)
            s.add(canal)
            s.add(mem.Usuario(username="ana", password_hash="x", nombre="Ana Asesora", rol="asesor", nivel="senior", negocio_id=n.id))
            s.add(mem.Usuario(username="beto", password_hash="x", nombre="Beto Asesor", rol="asesor", nivel="junior", negocio_id=n.id))
            await s.commit()
            self.negocio_id, self.canal_id = n.id, canal.id

    async def ciclo(
        self, tel: str, inicio: datetime, msgs=(), resultado=None, derivado=False, asesor=None, eventos=(), atrib=None,
        envios=(), interes=None, tipo_producto=None, estado="activa", origen_contacto=None, con_conv_id=True,
        cerrado_def=None,
    ):
        """msgs: (minutos, tipo, texto); tipo: c cliente | g Gabi | h asesor | happ echo del celular | r reenganche | cr reacción."""
        TELEFONOS.append(tel)
        async with mem.async_session() as s:
            if tel not in self.contactos:
                contacto = mem.Contact(negocio_id=self.negocio_id, telefono=tel, nombre=NOMBRE_SECRETO)
                s.add(contacto)
                await s.flush()
                self.contactos[tel] = contacto.id
            conv = mem.Conversation(
                negocio_id=self.negocio_id, contact_id=self.contactos[tel], canal_id=self.canal_id, estado=estado,
                paso_flujo="derivado_asesor" if derivado else None, asesor_asignado_id=asesor, creado=inicio,
                origen_contacto=origen_contacto, cerrado_definitivamente_en=cerrado_def,
            )
            s.add(conv)
            await s.flush()
            self.conversaciones.append(conv.id)
            s.add(mem.Opportunity(
                negocio_id=self.negocio_id, conversation_id=conv.id, contact_id=self.contactos[tel], resultado=resultado,
                interes=interes, producto_tipo=tipo_producto, creado=inicio,
            ))
            for minutos, tipo, texto in msgs:
                role, via_app = {
                    "c": ("user", False), "cr": ("user", False), "g": ("assistant", False), "h": ("asesor", False),
                    "happ": ("assistant", True), "r": ("assistant", False),
                }[tipo]
                if tipo == "cr":
                    texto = "Reaccionó con 👍"
                if tipo == "r":
                    texto = "¡Hola de nuevo! 👋 Sigo por aquí si tienes alguna otra pregunta o quieres retomar donde quedamos."
                s.add(mem.Mensaje(
                    telefono=tel, role=role, content=texto, via_app=via_app, negocio_id=self.negocio_id,
                    timestamp=inicio + timedelta(minutes=minutos), conversation_id=conv.id if con_conv_id else None,
                ))
            for tipo, minutos, payload in eventos:
                s.add(mem.EventoLead(
                    negocio_id=self.negocio_id, conversation_id=conv.id, tipo=tipo, descripcion=f"{tipo} {TEXTO_SECRETO}",
                    payload=payload, creado=inicio + timedelta(minutes=minutos),
                ))
            if atrib:
                s.add(mem.AttributionEvent(
                    negocio_id=self.negocio_id, conversation_id=conv.id, lead_telefono=tel, tipo_origen=atrib,
                    referral_raw={"x": 1}, creado=inicio,
                ))
            for origen, decision, minutos, tipo, asesor_usuario in envios:
                s.add(mem.EnvioMeta(
                    negocio_id=self.negocio_id, origen=origen, telefono=tel, tipo=tipo, decision=decision,
                    creado=inicio + timedelta(minutes=minutos), asesor_usuario=asesor_usuario,
                ))
            # Lead: refleja el ciclo más reciente del teléfono
            lead = await s.get(mem.Lead, tel)
            if lead is None:
                lead = mem.Lead(telefono=tel, negocio_id=self.negocio_id, nombre=NOMBRE_SECRETO, creado=inicio)
                s.add(lead)
            lead.resultado = resultado
            lead.paso_flujo = "derivado_asesor" if derivado else None
            lead.asesor_asignado = asesor
            lead.interes = interes
            lead.producto_tipo = tipo_producto
            lead.origen_contacto = origen_contacto
            await s.commit()


async def _sembrar_escenario() -> Sembrador:
    sem = Sembrador()
    await sem.iniciar()
    # A) 14 derivados atendidos rápido (7 min desde el último mensaje del cliente); mitad anuncio
    for i in range(14):
        inicio = BASE + timedelta(days=i % 5, hours=(i * 3) % 14)
        await sem.ciclo(
            f"5199900{i:04d}", inicio,
            msgs=[(0, "c", NOMBRE_SECRETO + " hola"), (1, "g", TEXTO_LARGO), (3, "c", "ok"), (4, "g", TEXTO_SECRETO + " te contactará un asesor"),
                  (10, "h", TEXTO_SECRETO + " asesor")],
            resultado=["agendado", "vendido", "no_interesado"][i % 3], derivado=True, asesor="ana" if i % 2 else "beto",
            eventos=[("asignado_automatico", 5, {"campo": "asesor_asignado", "anterior": None, "nuevo": "ana"})],
            atrib="meta_ads" if i % 2 else None, interes="terma a gas" if i % 3 == 0 else "secadora", con_conv_id=bool(i % 2),
            envios=[("gabi_aviso_derivacion", "enviado", 4, "texto", None), ("asesor_texto", "enviado", 10, "texto", "ana"),
                    ("asesor_plantilla", "enviado", 11, "plantilla", "beto")],
        )
    # B) 8 derivados que nunca tuvieron mensaje humano
    for i in range(8):
        await sem.ciclo(
            f"5199910{i:04d}", BASE + timedelta(days=1, hours=i),
            msgs=[(0, "c", "hola"), (1, "g", TEXTO_PRECIO), (3, "c", "ok"), (4, "g", TEXTO_SECRETO + " asesor")],
            resultado="sin_respuesta" if i % 2 else None, derivado=True, tipo_producto="cocina",
        )
    # C) 6 derivados con respuesta humana tardía (30 h): la ventana de 24 h cerró
    for i in range(6):
        await sem.ciclo(
            f"5199920{i:04d}", BASE + timedelta(days=2, hours=i),
            msgs=[(0, "c", "hola"), (1, "g", TEXTO_SECRETO + " dni"), (3, "c", "ok"), (4, "g", TEXTO_SECRETO + " asesor"), (30 * 60, "happ", TEXTO_SECRETO + " tarde")],
            resultado="agendado" if i == 0 else None, derivado=True, asesor="ana", interes="lavadora",
        )
    # D) 12 silenciosos: 6 con reenganche (3 respondieron), 6 control sin reenganche que volvieron a las 3 h
    for i in range(12):
        tel = f"5199930{i:04d}"
        inicio = BASE + timedelta(days=i % 4, hours=i)
        if i < 6:
            msgs = [(0, "c", "hola"), (1, "g", TEXTO_NEGRITA), (130, "r", None)]
            if i < 3:
                msgs.append((300, "c", "sí, sigo"))
            await sem.ciclo(
                tel, inicio, msgs=msgs, resultado="sin_respuesta" if i >= 3 else None,
                envios=[("reenganche_inactividad", "enviado", 130, "texto", None)],
            )
        else:
            await sem.ciclo(
                tel, inicio, msgs=[(0, "c", "hola"), (1, "g", TEXTO_NEGRITA), (200, "c", "ya vi"), (201, "g", TEXTO_LARGO)],
                resultado="sin_respuesta" if i % 2 else None,
            )
    # E) 3 con el reenganche bloqueado por la política (control A, n<10)
    for i in range(3):
        await sem.ciclo(
            f"5199940{i:04d}", BASE + timedelta(days=3, hours=i),
            msgs=[(0, "c", "hola"), (1, "g", TEXTO_SECRETO + " ¿cuál es tu nombre?")], resultado="sin_respuesta",
            envios=[("reenganche_inactividad", "bloqueado", 125, "texto", None)],
        )
    # F) reapertura: ciclo viejo cerrado definitivamente + ciclo nuevo con evento
    tel = "51999500001"
    await sem.ciclo(
        tel, BASE - timedelta(days=2), msgs=[(0, "c", "hola"), (1, "g", TEXTO_SECRETO)], resultado="sin_respuesta", estado="cerrada",
        eventos=[("cerrado_definitivamente_automatico", 60, {"resultado": "sin_respuesta"})], cerrado_def=BASE - timedelta(days=1),
    )
    await sem.ciclo(
        tel, BASE + timedelta(days=4), msgs=[(0, "c", "volví"), (1, "g", TEXTO_SECRETO)], resultado="agendado", derivado=True, asesor="ana",
        eventos=[("reabierto_por_cliente", 0, {"resultado_anterior": "sin_respuesta", "asesor_anterior": "ana"})],
    )
    # G) postventa y formulario
    await sem.ciclo(
        "51999600001", BASE, msgs=[(0, "c", "hola"), (5, "h", TEXTO_SECRETO)], resultado="postventa", derivado=True, asesor="ana",
        eventos=[("asignado_automatico_postventa", 1, {})],
    )
    await sem.ciclo(
        "51999600002", BASE, msgs=[(0, "g", TEXTO_SECRETO), (50, "cr", None)], origen_contacto="formulario_meta", resultado=None,
    )
    # H) fuera del período (antes del 15 de septiembre)
    await sem.ciclo("51999700001", datetime(2026, 9, 10, 15, 0), msgs=[(0, "c", "hola"), (1, "g", TEXTO_SECRETO)], resultado="vendido")
    return sem


async def _contar_filas() -> dict[str, int]:
    cuentas = {}
    async with mem.async_session() as s:
        for tabla in mem.Base.metadata.sorted_tables:
            cuentas[tabla.name] = (await s.execute(select(func.count()).select_from(tabla))).scalar_one()
    return cuentas


def _sin_pii(salida: str, sem: Sembrador | None = None):
    assert NOMBRE_SECRETO not in salida
    assert TEXTO_SECRETO not in salida
    assert "volví" not in salida
    for tel in TELEFONOS:
        assert tel not in salida, "aparece un teléfono"
    if sem is not None:
        for conv_id in sem.conversaciones:
            assert conv_id not in salida, "aparece un id de conversación"
    assert not re.search(r"\b519\d{8}\b", salida)


@pytest.fixture(autouse=True)
def _limpiar_telefonos():
    TELEFONOS.clear()
    yield
    TELEFONOS.clear()


# ── Base vacía ───────────────────────────────────────────────────────────────

@pytest.mark.parametrize("seccion", ac.SECCIONES)
async def test_cada_seccion_imprime_con_base_vacia(seccion):
    lineas = await ac.generar_informe(solo=[seccion], ahora=AHORA)
    salida = "\n".join(lineas)
    assert salida.strip()
    indice = ac.SECCIONES.index(seccion) + 1
    assert re.search(rf"^{indice}\. ", salida, re.M)


async def test_base_vacia_informe_completo():
    salida = "\n".join(await ac.generar_informe(ahora=AHORA))
    for n in range(1, 9):
        assert re.search(rf"^{n}\. ", salida, re.M)
    assert "Sin leads en el período" in salida


# ── Con datos ────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("seccion", ac.SECCIONES)
async def test_cada_seccion_imprime_con_datos_y_sin_pii(seccion):
    sem = await _sembrar_escenario()
    salida = "\n".join(await ac.generar_informe(solo=[seccion], ahora=AHORA))
    indice = ac.SECCIONES.index(seccion) + 1
    assert re.search(rf"^{indice}\. ", salida, re.M)
    _sin_pii(salida, sem)


async def test_informe_completo_con_datos_sin_pii_y_con_contenido():
    sem = await _sembrar_escenario()
    salida = "\n".join(await ac.generar_informe(ahora=AHORA))
    _sin_pii(salida, sem)
    # Los usernames del personal sí aparecen (sección 6), marcados como uso interno
    assert "USO INTERNO DEL DUEÑO" in salida
    assert re.search(r"^\s*ana\s", salida, re.M) and re.search(r"^\s*beto\s", salida, re.M)
    # Hay porcentajes reales en grupos con n>=10
    assert re.search(r"\d+,\d%", salida)
    # Resumen ejecutivo: de 5 a 8 líneas de contenido con palancas numeradas
    resumen = salida.split("8. RESUMEN EJECUTIVO")[1].strip().splitlines()
    cuerpo = [l for l in resumen if l.strip() and not l.startswith("=")]
    assert 5 <= len(cuerpo) <= 8
    assert any(l.startswith("Palanca 1.") for l in cuerpo)


async def test_clasificacion_de_ciclos_y_tiempos():
    sem = await _sembrar_escenario()
    ini, fin = ac.rango_utc("2026-09-15", None, AHORA)
    async with mem.async_session() as s:
        datos = await ac.cargar_datos(s, ini, fin, AHORA)
    leads = datos.leads
    # 14 + 8 + 6 + 12 + 3 + (1 reapertura) + postventa + formulario; el de antes del 15/9 queda fuera
    assert len(leads) == 14 + 8 + 6 + 12 + 3 + 1 + 1 + 1
    assert len(datos.en_rango) == len(leads) + 1  # el ciclo viejo cerrado del teléfono reabierto cae dentro del período
    rapidos = [c for c in leads if c.espera_humana is not None and c.espera_humana == 7 * 60]
    assert len(rapidos) == 14
    assert all(c.derivado and c.humano and c.derivacion_ts is not None for c in rapidos)
    assert all(abs(c.espera_desde_derivacion - 6 * 60) < 1 for c in rapidos)  # derivación al min 4 (aviso) o 5 (evento): usa el mínimo
    nunca = [c for c in leads if c.derivado and not c.humano and not c.postventa]
    assert len(nunca) == 9  # los 8 de B + el ciclo reabierto, derivado sin mensaje humano
    tardios = [c for c in leads if c.espera_humana is not None and c.espera_humana > 24 * 3600]
    assert len(tardios) == 6  # el echo del celular cuenta como respuesta humana
    assert sum(1 for c in datos.en_rango if c.reenganche_ts is not None) == 6
    assert sum(1 for c in datos.en_rango if c.reenganche_bloqueado_ts is not None) == 3
    assert sum(1 for c in leads if c.origen == "Formulario") == 1
    assert sum(1 for c in leads if c.origen == "Anuncio CTWA") == 7
    assert sum(1 for c in leads if c.postventa) == 1
    # la reacción del cliente no cuenta como respuesta
    formulario = next(c for c in leads if c.origen == "Formulario")
    assert formulario.primer_gabi is not None and formulario.respondio is False
    # interés agrupado
    assert {c.interes for c in leads} >= {"Terma", "Secadora", "Cocina", "Otros", "Sin dato"}


async def test_reenganche_y_control_con_numeros_esperados():
    await _sembrar_escenario()
    ini, fin = ac.rango_utc("2026-09-15", None, AHORA)
    async with mem.async_session() as s:
        datos = await ac.cargar_datos(s, ini, fin, AHORA)
    _, m = ac.seccion_reenganche(datos)
    n, n24, r24, n72, r72, _exito = m["Con reenganche enviado"]
    assert (n, n24, r24, n72, r72) == (6, 6, 3, 6, 3)
    # Control A tiene 3 casos: no se calculan porcentajes
    lineas, _ = ac.seccion_reenganche(datos)
    fila_a = next(l for l in lineas if l.strip().startswith("Control A"))
    assert "n<10" in fila_a


async def test_n_menor_a_10_no_muestra_porcentajes():
    sem = Sembrador()
    await sem.iniciar()
    for i in range(3):
        await sem.ciclo(
            f"5199980{i:04d}", BASE + timedelta(hours=i),
            msgs=[(0, "c", "hola"), (1, "g", TEXTO_SECRETO), (2, "c", "ok"), (3, "h", TEXTO_SECRETO)], resultado="agendado", derivado=True, asesor="ana",
        )
    salida = "\n".join(await ac.generar_informe(ahora=AHORA))
    assert "n<10" in salida
    assert not re.search(r"\d+,\d%", salida), "con n<10 no debe haber porcentajes"
    _sin_pii(salida, sem)
    assert ac.pct(9, 9) == "n<10" and ac.pct(5, 10) == "50,0%"


async def test_lectura_pura_no_cambia_ninguna_tabla():
    await _sembrar_escenario()
    antes = await _contar_filas()
    await ac.generar_informe(ahora=AHORA)
    await ac.generar_informe(desde="2026-09-01", hasta="2026-09-30", solo=["velocidad", "resumen"], ahora=AHORA)
    despues = await _contar_filas()
    assert antes == despues
    assert antes["mensajes"] > 0 and antes["leads"] > 0


async def test_argumentos_de_fecha_filtran_ciclos():
    sem = Sembrador()
    await sem.iniciar()
    await sem.ciclo("51999800001", datetime(2026, 9, 10, 15, 0), msgs=[(0, "c", "hola"), (1, "g", "a")])
    await sem.ciclo("51999800002", datetime(2026, 9, 20, 15, 0), msgs=[(0, "c", "hola"), (1, "g", "a")])
    await sem.ciclo("51999800003", datetime(2026, 9, 25, 15, 0), msgs=[(0, "c", "hola"), (1, "g", "a")])

    async def n_leads(**kw):
        salida = "\n".join(await ac.generar_informe(ahora=AHORA, **kw))
        return int(re.search(r"leads únicos: (\d+)", salida).group(1))

    assert await n_leads() == 2  # default: desde 2026-09-15
    assert await n_leads(desde="2026-09-01") == 3
    assert await n_leads(desde="2026-09-15", hasta="2026-09-22") == 1
    assert await n_leads(desde="2026-09-20", hasta="2026-09-20") == 1
    assert await n_leads(desde="2026-09-26") == 0


async def test_dia_lima_cuenta_en_hora_de_lima():
    # 2026-09-21 03:00 UTC = domingo 20/09 22:00 en Lima: entra con --hasta 2026-09-20 y no con --desde 2026-09-21
    sem = Sembrador()
    await sem.iniciar()
    await sem.ciclo("51999810001", datetime(2026, 9, 21, 3, 0), msgs=[(0, "c", "hola"), (1, "g", "a")])
    salida = "\n".join(await ac.generar_informe(desde="2026-09-15", hasta="2026-09-20", ahora=AHORA))
    assert "leads únicos: 1" in salida
    salida = "\n".join(await ac.generar_informe(desde="2026-09-21", ahora=AHORA))
    assert "leads únicos: 0" in salida


def test_parser_y_secciones():
    p = ac.construir_parser()
    a = p.parse_args(["--desde", "2026-09-20", "--hasta", "2026-10-01", "--solo", "embudo,3", "resumen"])
    assert a.desde == "2026-09-20" and a.hasta == "2026-10-01"
    assert ac.normalizar_secciones(a.solo) == ["embudo", "velocidad", "resumen"]
    with pytest.raises(SystemExit):
        p.parse_args(["--desde", "20/09/2026"])
    with pytest.raises(ValueError):
        ac.normalizar_secciones(["inexistente"])
    assert ac.construir_parser().parse_args([]).desde == "2026-09-15"


async def test_hasta_anterior_a_desde_falla_claro():
    with pytest.raises(ValueError):
        await ac.generar_informe(desde="2026-09-20", hasta="2026-09-10", ahora=AHORA)


def test_percentiles_y_formato():
    assert ac.fmt_dur(None) == "—"
    assert ac.fmt_dur(30) == "30 s"
    assert ac.fmt_dur(600) == "10 min"
    assert ac.fmt_dur(7200) == "2,0 h"
    assert ac.percentil([1, 2, 3, 4, 5], 0.5) == 3
    assert ac.fila_percentiles("x", [1.0] * 9)[2] == "n<10"
    assert ac.fila_percentiles("x", [60.0] * 10)[2] == "1 min"
    assert ac.franja_de(datetime(2026, 9, 20, 14, 0)) == "Mañana (8-13)"  # 09:00 Lima
    assert ac.franja_de(datetime(2026, 9, 21, 3, 0)) == "Noche (19-24)"  # 22:00 Lima
    assert ac.franja_de(datetime(2026, 9, 20, 7, 0)) == "Madrugada (0-8)"  # 02:00 Lima


def test_rasgos_de_texto():
    r = ac.rasgos_texto("**Hola** el precio es S/ 899. ¿Me das tu nombre?")
    assert r["negrita"] and r["precio"] and r["pregunta"] and r["nombre"] and not r["dni"]
    r = ac.rasgos_texto("Necesito tu DNI para el financiamiento.")
    assert r["dni"] and r["financ"] and not r["pregunta"]
    assert ac.rasgos_texto("a" * 300)["largo"] == 300


def test_agrupar_interes():
    assert ac.agrupar_interes("terma", None) == "Terma"
    assert ac.agrupar_interes(None, "Calentador a gas") == "Terma"
    assert ac.agrupar_interes(None, "secadora de ropa") == "Secadora"
    assert ac.agrupar_interes("horno", None) == "Cocina"
    assert ac.agrupar_interes("lavadora", None) == "Otros"
    assert ac.agrupar_interes(None, "  ") == "Sin dato"
