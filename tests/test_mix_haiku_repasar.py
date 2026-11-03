# tests/test_mix_haiku_repasar.py — Repaso offline de la sombra con la revisión del mix (scripts/mix_haiku_repasar.py).
import os

os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")
os.environ.setdefault("WHATSAPP_PROVIDER", "meta")

from scripts import mix_haiku_repasar as rep


def test_las_respuestas_de_haiku_de_la_auditoria_se_rechazan_por_lo_que_corresponde():
    # Los 3 errores reales de la muestra del 2-nov (el cliente no había escrito DNI ni pedido precio).
    cliente = ["Estoy interesado en financiar una secadora", "somos 5 personas"]
    assert "afirma_dato_que_no_llego" in rep.evaluar("Gracias. Ya tengo tu DNI. Un asesor continuará mañana.", cliente)
    assert "precio_que_nadie_pidio" in rep.evaluar("La secadora de 22 kg (MABE, S/ 2,999) es la que mejor se adapta.", cliente)
    assert "ducteria_sin_terma" in rep.evaluar("Puedes solicitar un punto adicional o una ductería como servicio aparte.", cliente)


def test_las_respuestas_buenas_pasan_y_el_precio_pedido_no_se_rechaza():
    cliente = ["Quiero una terma", "¿cuánto cuesta?", "dos baños"]
    assert rep.evaluar("Con 2 baños te sirve la terma de 14 a 17 l/min. El asesor te confirma la cuota exacta.", cliente) == []
    assert rep.evaluar("La terma cuesta S/ 1,299.", cliente) == []                       # el cliente sí pidió el precio
    assert rep.evaluar("Gracias. Ya tengo tu DNI.", ["terma", "mi dni es 45781236"]) == []


def test_el_resumen_cuenta_aprobadas_y_motivos():
    r = rep.resumir([[], [], ["precio_que_nadie_pidio"], ["muy_larga", "precio_que_nadie_pidio"]])
    assert r == {"respuestas": 4, "aprobadas": 2, "aprobadas_pct": 50.0, "motivos": {"precio_que_nadie_pidio": 2, "muy_larga": 1}}
    assert rep.resumir([]) == {"respuestas": 0}
