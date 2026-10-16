# tests/test_solo_clic_definicion.py — Experimento «solo clic» (2026-10-16, agent/solo_clic.py), parte PURA: la definición
# `es_solo_clic`, el saludo trivial, el hash de brazos, el plan de acción de la sombra y la estadística del análisis.
# Sin base de datos. Datos sintéticos únicamente.

import math
import os
import subprocess
import sys
import uuid
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path

os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")
os.environ.setdefault("WHATSAPP_PROVIDER", "meta")

import pytest

from agent import llamadas
from agent import solo_clic as sc
from agent.solo_clic import DatosSC, MensajeSC

T0 = datetime(2026, 10, 14, 15, 0, 0)      # miércoles 10:00 en Lima
TEL = "51987000001"
PRELLENADO = "Hola, quiero más información de este producto"
CONOCIDOS = frozenset({sc.normalizar_texto(PRELLENADO)})
ERRORES = frozenset({"uy estoy teniendo un problema tecnico intenta de nuevo en unos minutos"})
RAIZ = Path(__file__).resolve().parent.parent


def u(texto, seg=0, **kw):
    return MensajeSC("user", texto, T0 + timedelta(seconds=seg), **kw)


def g(texto="Hola, soy Gabi. ¿En qué te ayudo?", seg=7, **kw):
    return MensajeSC("assistant", texto, T0 + timedelta(seconds=seg), **kw)


def datos(mensajes, **kw):
    base = dict(origen_prellenado=True, textos_conocidos=CONOCIDOS, telefono=TEL, errores_conocidos=ERRORES)
    base.update(kw)
    return DatosSC(mensajes=mensajes, **base)


def veredicto(mensajes, **kw):
    return sc.es_solo_clic(datos(mensajes, **kw))


# ── Lo positivo ──────────────────────────────────────────────────────────────────────────────────────────

def test_prellenado_conocido_y_gabi_respondio_y_silencio_es_solo_clic():
    v = veredicto([u(PRELLENADO), g()])
    assert v.es_solo_clic and v.motivo is None and v.tipo_primer_turno == "prellenado_conocido"
    assert v.primer_gabi_en == T0 + timedelta(seconds=7) and v.ultimo_cliente_en == T0


def test_el_prellenado_se_compara_normalizado():
    assert veredicto([u("  HOLA,  quiero más   información de ESTE producto "), g()]).es_solo_clic
    assert veredicto([u("hola, quiero mas informacion de este producto"), g()]).es_solo_clic


@pytest.mark.parametrize("saludo", ["hola", "Hola", "HOLA!", "buenas", "Buenos días", "buenas tardes", "Hola buenas noches", "holaaa 👋", "hola, buen día", "Hola a todos"])
def test_un_saludo_trivial_es_primer_turno_valido(saludo):
    v = veredicto([u(saludo), g()])
    assert v.es_solo_clic and v.tipo_primer_turno in ("saludo", "prellenado_conocido")


def test_reenganche_de_gabi_despues_no_quita_el_solo_clic():
    reenganche = "¡Hola de nuevo! 👋 Sigo por aquí si tienes alguna otra pregunta o quieres retomar donde quedamos. Cuéntame en qué te puedo ayudar 😊"
    assert veredicto([u("hola"), g(), g(reenganche, seg=7200)]).es_solo_clic


def test_un_segundo_mensaje_de_gabi_fallido_despues_del_primero_no_descalifica():
    assert veredicto([u("hola"), g(), g("otro", seg=60, estado_envio="fallido")]).es_solo_clic


def test_el_orden_de_la_lista_no_importa_se_ordena_por_hora():
    assert veredicto([g(), u("hola")]).es_solo_clic


# ── (a) origen ───────────────────────────────────────────────────────────────────────────────────────────

def test_el_organico_que_escribe_hola_a_mano_queda_fuera():
    v = veredicto([u("hola"), g()], origen_prellenado=False)
    assert not v.es_solo_clic and v.motivo == "sin_origen_prellenado"


# ── (b) primer turno ─────────────────────────────────────────────────────────────────────────────────────

def test_el_cliente_que_edita_el_prellenado_y_escribe_algo_real_no_es_solo_clic():
    v = veredicto([u("Hola, quiero más información de este producto, ¿cuánto cuesta la terma de 80 litros?"), g()])
    assert not v.es_solo_clic and v.motivo == "primer_turno_no_prellenado"


@pytest.mark.parametrize("texto", ["Quiero una cocina", "precio?", "hola quiero una terma", "buenas, me interesa el horno", "gracias"])
def test_un_texto_que_no_es_prellenado_ni_saludo_no_es_solo_clic(texto):
    assert veredicto([u(texto), g()]).motivo == "primer_turno_no_prellenado"


@pytest.mark.parametrize("contenido,extra", [
    ("[audio]", {}), ("[image]", {}), ("[sticker]", {}), ("[video]", {}), ("[document]", {}),
    ("Reaccionó con 👍", {}), ("foto de mi recibo", {"archivo_id": 5}),
])
def test_un_primer_turno_sin_texto_no_es_solo_clic(contenido, extra):
    v = veredicto([u(contenido, **extra), g()])
    assert not v.es_solo_clic and v.motivo == "primer_turno_no_texto"


def test_dos_mensajes_antes_de_la_respuesta_de_gabi_no_es_un_solo_clic():
    v = veredicto([u("hola", 0), u("hola", 2), g(seg=7)])
    assert not v.es_solo_clic and v.motivo == "primer_turno_multiple"


def test_gabi_escribio_primero_sin_primer_turno_del_cliente():
    v = veredicto([g(seg=0)])
    assert not v.es_solo_clic and v.motivo == "sin_primer_turno"


def test_saludo_trivial_exige_al_menos_una_palabra_de_saludo_y_pocas_palabras():
    assert sc.es_saludo_trivial("buenos dias")
    assert not sc.es_saludo_trivial("dias")
    assert not sc.es_saludo_trivial("que tal")
    assert not sc.es_saludo_trivial("hola buenas tardes a todos los amigos")
    assert not sc.es_saludo_trivial("")
    assert not sc.es_saludo_trivial(None)
    assert not sc.es_saludo_trivial("👋")
    assert not sc.es_saludo_trivial("hola quiero info")


# ── (c) Gabi sí le escribió ──────────────────────────────────────────────────────────────────────────────

def test_sin_mensajes_de_gabi_no_es_solo_clic():
    v = veredicto([u("hola")])
    assert not v.es_solo_clic and v.motivo == "gabi_no_escribio"


def test_si_el_unico_mensaje_de_gabi_no_se_entrego_no_es_solo_clic():
    for estado in ("fallido", "incierto"):
        v = veredicto([u("hola"), g(estado_envio=estado)])
        assert not v.es_solo_clic and v.motivo == "envio_caido"


def test_si_el_primer_intento_de_gabi_se_cayo_y_el_segundo_llego_no_es_comparable():
    v = veredicto([u("hola"), g(estado_envio="fallido", seg=5), g(seg=300)])
    assert not v.es_solo_clic and v.motivo == "envio_caido"


def test_el_texto_de_error_tecnico_de_gabi_es_falla_de_ia():
    v = veredicto([u("hola"), g("Uy, estoy teniendo un problema técnico. Intenta de nuevo en unos minutos.")])
    assert not v.es_solo_clic and v.motivo == "falla_ia"


def test_un_reenganche_como_primer_mensaje_no_cuenta_como_que_gabi_respondio():
    reenganche = "¡Hola de nuevo! 👋 Sigo por aquí si tienes alguna otra pregunta o quieres retomar donde quedamos. Cuéntame en qué te puedo ayudar 😊"
    v = veredicto([u("hola"), g(reenganche)])
    assert not v.es_solo_clic and v.motivo == "gabi_no_escribio"


# ── (d) cero eventos del cliente después ─────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("contenido,extra", [
    ("gracias", {}), ("quiero precio", {}), ("[audio]", {}), ("[image]", {}), ("[sticker]", {}), ("Reaccionó con ❤️", {}),
    ("recibo", {"archivo_id": 9}), ("ok", {}),
])
def test_cualquier_evento_del_cliente_despues_del_primer_mensaje_de_gabi_lo_descalifica(contenido, extra):
    v = veredicto([u("hola"), g(), u(contenido, 120, **extra)])
    assert not v.es_solo_clic and v.motivo == "cliente_interactuo"


def test_evaluar_como_estaba_a_cierta_hora_ignora_lo_posterior():
    mensajes = [u("hola"), g(), u("quiero precio", 25 * 60)]
    corte = T0 + timedelta(minutes=20, seconds=7)
    assert veredicto(mensajes, hasta=corte).es_solo_clic          # respondió a los 25 min: la cohorte T+20 ya estaba decidida
    assert not veredicto(mensajes, hasta=T0 + timedelta(minutes=30)).es_solo_clic
    assert not veredicto(mensajes).es_solo_clic


# ── (e) exclusiones ──────────────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("campo,motivo", [
    ("numero_interno", "numero_interno"), ("no_llamar", "no_llamar"), ("triaje_atc_cerrado", "triaje_atc"),
    ("con_asesor", "asesor"), ("pausado", "pausa"), ("escalado", "escalado"), ("derivado", "derivado"),
    ("cerrado", "conversacion_cerrada"), ("ciclo_reabierto", "ciclo_reabierto"), ("con_resultado", "con_resultado"),
    ("origen_formulario", "origen_formulario"),
])
def test_cada_exclusion_previa_saca_la_conversacion(campo, motivo):
    v = veredicto([u("hola"), g()], **{campo: True})
    assert not v.es_solo_clic and v.motivo == motivo


@pytest.mark.parametrize("telefono", [None, "", "987000001", "5198700000", "519870000012", "1555123456", "abc123xyz", "51987abc001", "wa_bsuid_US.1234567890"])
def test_telefono_no_peruano_o_bsuid_queda_fuera(telefono):
    v = veredicto([u("hola"), g()], telefono=telefono)
    assert not v.es_solo_clic and v.motivo == "telefono_no_peruano"


def test_mensaje_humano_saca_la_conversacion():
    assert veredicto([u("hola"), MensajeSC("asesor", "Hola, soy un asesor", T0 + timedelta(seconds=5)), g()]).motivo == "humano"
    assert veredicto([u("hola"), g(via_app=True)]).motivo == "humano"


def test_un_humano_posterior_al_corte_no_cuenta():
    mensajes = [u("hola"), g(), MensajeSC("asesor", "Hola", T0 + timedelta(hours=5))]
    assert veredicto(mensajes, hasta=T0 + timedelta(minutes=20)).es_solo_clic
    assert veredicto(mensajes).motivo == "humano"


def test_las_exclusiones_se_evaluan_antes_que_la_definicion():
    v = veredicto([u("hola")], origen_prellenado=False, con_asesor=True)
    assert v.motivo == "asesor"


def test_todos_los_motivos_posibles_estan_catalogados():
    visto = {sc.es_solo_clic(datos(m, **kw)).motivo for m, kw in [
        ([u("hola"), g()], {"numero_interno": True}), ([u("hola"), g()], {"origen_prellenado": False}), ([], {}),
        ([u("x"), g()], {}), ([u("hola")], {}),
    ]}
    assert visto <= set(sc.MOTIVOS)


# ── Brazos: hash determinista ────────────────────────────────────────────────────────────────────────────

def test_el_brazo_es_determinista_y_solo_c_t1_t2():
    for i in range(200):
        cid = f"conv-{i}"
        assert sc.brazo_de(cid, "v1") == sc.brazo_de(cid, "v1")
        assert sc.brazo_de(cid, "v1") in ("C", "T1", "T2")
    assert "T3" not in sc.BRAZOS and sc.PCT_T3 == 0.0


def test_el_brazo_coincide_con_el_hash_documentado():
    # Valida la receta exacta (sha256 de «sal:id», 8 hex, mod 10000): si alguien la cambia, se rompe la reproducibilidad.
    import hashlib
    cid = "9f1c2d3e-0000-4000-8000-123456789abc"
    pos = int(hashlib.sha256(f"exp_solo_clic_v1:{cid}".encode()).hexdigest()[:8], 16) % 10000 / 100.0
    esperado = "C" if pos < 40 else ("T2" if pos < 80 else "T1")
    assert sc.brazo_de(cid, "v1") == esperado


def test_el_brazo_es_estable_entre_procesos():
    codigo = (
        "import os;os.environ.setdefault('ANTHROPIC_API_KEY','x');os.environ.setdefault('WHATSAPP_PROVIDER','meta');"
        "from agent import solo_clic as s;print(','.join(s.brazo_de(f'c-{i}','v1') for i in range(60)))"
    )
    salidas = set()
    for semilla in ("0", "1", "random"):
        r = subprocess.run([sys.executable, "-c", codigo], capture_output=True, text=True, cwd=RAIZ, env={**os.environ, "PYTHONHASHSEED": semilla})
        assert r.returncode == 0, r.stderr
        salidas.add(r.stdout.strip())
    assert len(salidas) == 1
    assert salidas.pop() == ",".join(sc.brazo_de(f"c-{i}", "v1") for i in range(60))


def test_reparto_balanceado_con_n_grande():
    n = 30000
    cuentas = Counter(sc.brazo_de(str(uuid.UUID(int=i * 7919 + 12345)), "v1") for i in range(n))
    for brazo, esperado in (("C", 0.40), ("T2", 0.40), ("T1", 0.20)):
        proporcion = cuentas[brazo] / n
        sigma = math.sqrt(esperado * (1 - esperado) / n)
        assert abs(proporcion - esperado) < 4 * sigma, (brazo, proporcion)


def test_reparto_con_uuid_aleatorios_tambien_balanceado():
    n = 20000
    cuentas = Counter(sc.brazo_de(str(uuid.uuid4()), "v1") for _ in range(n))
    assert abs(cuentas["C"] / n - 0.40) < 0.02 and abs(cuentas["T2"] / n - 0.40) < 0.02 and abs(cuentas["T1"] / n - 0.20) < 0.02


def test_la_sal_es_distinta_de_la_del_holdout_y_no_se_correlaciona():
    n = 20000
    ids = [str(uuid.UUID(int=i * 104729 + 7)) for i in range(n)]
    # Tabla de contingencia holdout (control/llamar) x brazo: con independencia, cada celda ≈ producto de marginales.
    celdas = Counter((llamadas.grupo_de(i, 30.0), sc.brazo_de(i, "v1")) for i in ids)
    for grupo, p_g in (("control", 0.30), ("llamar", 0.70)):
        for brazo, p_b in (("C", 0.40), ("T2", 0.40), ("T1", 0.20)):
            esperado = p_g * p_b
            assert abs(celdas[(grupo, brazo)] / n - esperado) < 0.015, (grupo, brazo)
    # y las posiciones continuas no están correlacionadas
    xs = [llamadas._percentil_de(i, "holdout") for i in ids]
    ys = [llamadas._percentil_de(i, "exp_solo_clic_v1") for i in ids]
    mx, my = sum(xs) / n, sum(ys) / n
    cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / n
    corr = cov / (math.sqrt(sum((x - mx) ** 2 for x in xs) / n) * math.sqrt(sum((y - my) ** 2 for y in ys) / n))
    assert abs(corr) < 0.03
    assert llamadas._percentil_de(ids[0], "holdout") != llamadas._percentil_de(ids[0], "exp_solo_clic_v1")


def test_cambiar_la_epoca_reasigna_los_brazos():
    ids = [f"c-{i}" for i in range(3000)]
    iguales = sum(sc.brazo_de(i, "v1") == sc.brazo_de(i, "v2") for i in ids)
    assert 0.25 < iguales / len(ids) < 0.50      # con 3 brazos independientes coincidirían ≈ 0,40²+0,40²+0,20² = 0,36


def test_los_porcentajes_se_normalizan_y_los_extremos_funcionan():
    ids = [f"c-{i}" for i in range(500)]
    assert {sc.brazo_de(i, "v1", 100, 0, 0) for i in ids} == {"C"}
    assert {sc.brazo_de(i, "v1", 0, 100, 0) for i in ids} == {"T1"}
    assert {sc.brazo_de(i, "v1", 0, 0, 100) for i in ids} == {"T2"}
    assert {sc.brazo_de(i, "v1", 0, 0, 0) for i in ids} == {"C"}                # sin reparto: todo control
    assert [sc.brazo_de(i, "v1", 2, 1, 2) for i in ids] == [sc.brazo_de(i, "v1", 40, 20, 40) for i in ids]


# ── Plan de acción (sombra) ──────────────────────────────────────────────────────────────────────────────

def _calendario(abierto_desde=9, abierto_hasta=18):
    """Lunes a viernes 9-18 hora de Lima; devuelve (abierto, proxima_apertura) sobre UTC naive."""
    def lima(t):
        return t - timedelta(hours=5)

    def abierto(t):
        l = lima(t)
        return l.weekday() < 5 and abierto_desde <= l.hour + l.minute / 60 < abierto_hasta

    def proxima(t):
        cursor = t
        for _ in range(60 * 24 * 10):
            cursor += timedelta(minutes=1)
            if abierto(cursor) and not abierto(cursor - timedelta(minutes=1)):
                return cursor
        return None
    return abierto, proxima


def _plan(brazo, hora_lima, dia="miercoles", **kw):
    base = {"miercoles": datetime(2026, 10, 14), "viernes": datetime(2026, 10, 16), "sabado": datetime(2026, 10, 17)}[dia]
    gabi = base + timedelta(hours=hora_lima + 5, seconds=7)
    abierto, proxima = _calendario()
    return sc.plan_de_accion(brazo, primer_gabi_en=gabi, ultimo_cliente_en=gabi - timedelta(seconds=7), abierto=abierto, proxima_apertura=proxima, **kw), gabi


def test_control_y_toque_no_dependen_del_horario():
    assert _plan("C", 11)[0]["accion_habria"] == "control_2h"
    assert _plan("T1", 23)[0]["accion_habria"] == "toque_20"


def test_oferta_en_horario_se_hace_a_t60():
    plan, gabi = _plan("T2", 11)
    assert plan["accion_habria"] == "oferta_60" and plan["cayo_en_horario_a_T60"] is True
    assert plan["oferta_hipotetica"] == {"estado": "oferta_60", "en": sc.iso_utc(gabi + timedelta(minutes=60)), "diferida": False}
    assert plan["ventana_cierra_antes_de_apertura"] is False


def test_oferta_fuera_de_horario_se_difiere_a_la_proxima_apertura_si_la_ventana_alcanza():
    plan, gabi = _plan("T2", 19)            # miércoles 19:00: cerrado; abre jueves 9:00 (14 h después, dentro de 22 h)
    assert plan["cayo_en_horario_a_T60"] is False
    assert plan["accion_habria"] == "oferta_60" and plan["oferta_hipotetica"]["diferida"] is True
    assert plan["ventana_cierra_antes_de_apertura"] is False


def test_oferta_se_omite_si_la_ventana_se_cierra_antes_de_la_apertura():
    plan, gabi = _plan("T2", 18.5, dia="viernes")      # viernes 18:30: abre lunes 9:00 (≈ 62 h): la ventana de 24 h ya cerró
    assert plan["accion_habria"] == "omitida_ventana"
    assert plan["ventana_cierra_antes_de_apertura"] is True and plan["oferta_hipotetica"]["en"] is None


def test_la_ventana_de_22_horas_deja_margen_antes_de_las_24():
    # Miércoles 20:00 → abre jueves 9:00 = 13 h: cabe. Con un margen de 12 h ya no.
    plan, _ = _plan("T2", 20, ventana_max_horas=12)
    assert plan["accion_habria"] == "omitida_ventana" and plan["ventana_cierra_antes_de_apertura"] is False   # cierra 24 h, abre a las 13 h
    plan, _ = _plan("T2", 20)
    assert plan["accion_habria"] == "oferta_60"


def test_sin_apertura_proxima_se_omite_por_fuera_de_horario():
    plan = sc.plan_de_accion(
        "T2", primer_gabi_en=T0, ultimo_cliente_en=T0, abierto=lambda t: False, proxima_apertura=lambda t: None,
    )
    assert plan["accion_habria"] == "omitida_fuera_de_horario" and plan["oferta_hipotetica"]["estado"] == "omitida_fuera_de_horario"


def test_la_oferta_hipotetica_se_describe_para_cualquier_brazo():
    plan, gabi = _plan("C", 11)
    assert plan["accion_habria"] == "control_2h" and plan["oferta_hipotetica"]["estado"] == "oferta_60"


def test_el_toque_registra_su_hora_nominal():
    plan, gabi = _plan("T1", 11, toque_min=25)
    assert plan["toque_en"] == sc.iso_utc(gabi + timedelta(minutes=25))


# ── Estadística ──────────────────────────────────────────────────────────────────────────────────────────

def test_wilson_valores_conocidos():
    bajo, alto = sc.intervalo_wilson(5, 10)
    assert bajo == pytest.approx(0.2366, abs=2e-3) and alto == pytest.approx(0.7634, abs=2e-3)
    bajo, alto = sc.intervalo_wilson(0, 10)
    assert bajo == 0.0 and alto == pytest.approx(0.2775, abs=2e-3)
    assert sc.intervalo_wilson(0, 0) == (None, None)
    bajo, alto = sc.intervalo_wilson(30, 100)
    assert bajo < 0.30 < alto and alto - bajo < 0.2


def test_tamano_de_muestra_dos_proporciones_valor_de_referencia():
    # 0,30 vs 0,40 con α 0,05 y potencia 80 % ≈ 354 por brazo (valor de manual).
    assert sc.n_por_brazo(0.30, 0.40) == pytest.approx(354, abs=6)
    assert sc.n_por_brazo(0.3, 0.3) == math.inf
    assert sc.n_por_brazo(0.30, 0.38) < sc.n_por_brazo(0.30, 0.35)


def test_efecto_minimo_detectable_es_coherente_con_el_tamano_de_muestra():
    for p0, n in ((0.3, 90), (0.2, 354), (0.5, 40)):
        mde = sc.efecto_minimo_detectable(p0, n)
        assert mde is not None and sc.n_por_brazo(p0, p0 + mde) == pytest.approx(n, rel=0.02)
    assert sc.efecto_minimo_detectable(0.3, 400) < sc.efecto_minimo_detectable(0.3, 90)
    assert sc.efecto_minimo_detectable(0.3, 0) is None
    assert sc.efecto_minimo_detectable(0.3, 2) is None            # con 2 casos ni un salto hasta 100 % se detecta


def test_lunes_de_la_semana_en_hora_de_lima():
    assert sc.lunes_de_la_semana_lima(datetime(2026, 10, 14, 15)) == "2026-10-12"
    assert sc.lunes_de_la_semana_lima(datetime(2026, 10, 12, 3, 0)) == "2026-10-05"      # lunes 3:00 UTC = domingo 22:00 en Lima
    assert sc.lunes_de_la_semana_lima(datetime(2026, 10, 12, 5, 0)) == "2026-10-12"


# ── Validación de la configuración (pura) ────────────────────────────────────────────────────────────────

def test_validar_cambios_acepta_lo_valido_y_rechaza_t3_y_desconocidos():
    assert sc.validar_cambios({"modo": "sombra", "epoca": "v2", "cohorte_min": 20, "ventana_max_horas": 22}) == {
        "sc_exp_modo": "sombra", "sc_exp_epoca": "v2", "sc_cohorte_min": "20", "sc_ventana_max_horas": "22",
    }
    with pytest.raises(ValueError, match="BLOQUEADA"):
        sc.validar_cambios({"pct_t3": 10})
    with pytest.raises(ValueError, match="desconocidos"):
        sc.validar_cambios({"nada": 1})
    for malo in ({"modo": "x"}, {"epoca": ""}, {"epoca": "a b"}, {"cohorte_min": 1}, {"cohorte_min": 20.5}, {"cohorte_min": True},
                 {"ventana_max_horas": 24}, {"oferta_min": 5}, {"max_intentos": 9}):
        with pytest.raises(ValueError):
            sc.validar_cambios(malo)


def test_los_porcentajes_deben_sumar_100():
    assert sc.validar_cambios({"pct_c": 50, "pct_t1": 25, "pct_t2": 25}) == {"sc_exp_pct_c": "50.0", "sc_exp_pct_t1": "25.0", "sc_exp_pct_t2": "25.0"}
    with pytest.raises(ValueError, match="sumar 100"):
        sc.validar_cambios({"pct_c": 50})                       # 50 + 20 + 40 con los defaults
    with pytest.raises(ValueError):
        sc.validar_cambios({"pct_c": 101, "pct_t1": 0, "pct_t2": 0})
