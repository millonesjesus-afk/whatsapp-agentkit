"""Muestra de calidad del mix Haiku (scripts/mix_haiku_muestra.py) — datos sintéticos únicamente."""
from scripts import mix_haiku_muestra as m


def _evento(i, aprobada=True, delicado=False, motivos=None, ultimo="hola"):
    return {
        "payload": {
            "aprobada": aprobada, "delicado": delicado, "motivos": motivos or [],
            "respuesta_real": f"real {i}", "respuesta_haiku": f"haiku {i}",
        },
        "ultimo_cliente": ultimo,
    }


def test_enmascara_numeros_largos_y_correos():
    t = "mi dni es 45 678 912 y mi cel 987654321, correo ana@correo.com gracias"
    r = m.enmascarar(t)
    assert "45 678 912" not in r and "987654321" not in r and "ana@correo.com" not in r
    assert "[número]" in r and "[correo]" in r and r.endswith("gracias")


def test_no_toca_numeros_cortos_y_recorta():
    assert m.enmascarar("quiero 2 hornos de 30 litros") == "quiero 2 hornos de 30 litros"
    largo = m.enmascarar("palabra " * 100)
    assert len(largo) == m.LARGO_MENSAJE_CLIENTE and largo.endswith("…")
    assert m.enmascarar(None) == ""


def test_solo_elige_turnos_no_delicados_y_segun_aprobacion():
    eventos = [_evento(1), _evento(2, delicado=True), _evento(3, aprobada=False, motivos=["muy_larga"]), _evento(4)]
    aprobadas = m.elegir(eventos, n=10)
    assert [e["payload"]["respuesta_real"] for e in aprobadas] == ["real 1", "real 4"]
    rechazadas = m.elegir(eventos, n=10, solo="rechazadas")
    assert [e["payload"]["respuesta_real"] for e in rechazadas] == ["real 3"]


def test_reparte_la_muestra_en_todo_el_periodo_y_el_salto_no_repite():
    eventos = [_evento(i) for i in range(300)]
    primeras = m.elegir(eventos, n=10)
    siguientes = m.elegir(eventos, n=10, salto=10)
    assert len(primeras) == 10 and len(siguientes) == 10
    ids = lambda lista: [e["payload"]["respuesta_real"] for e in lista]
    assert not set(ids(primeras)) & set(ids(siguientes))
    assert ids(primeras)[0] == "real 0" and int(ids(siguientes)[-1].split()[1]) > int(ids(primeras)[-1].split()[1])
    todas = m.elegir(eventos, n=1000)
    assert len(todas) == m.MUESTRA_TOTAL and int(ids(todas)[-1].split()[1]) >= 290      # recorre todo el periodo, no solo el inicio


def test_sin_candidatos_no_falla():
    assert m.elegir([], n=5) == []
    assert m.elegir([_evento(1, delicado=True)], n=5) == []


def test_formato_no_incluye_datos_del_cliente_y_muestra_motivos():
    e = _evento(7, aprobada=False, motivos=["muy_larga"], ultimo="mi dni 12345678")
    s = m.formatear(3, e)
    assert "[3] RECHAZADA: muy_larga" in s and "12345678" not in s and "[número]" in s
    assert "SONNET : real 7" in s and "HAIKU  : haiku 7" in s
