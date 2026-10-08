# tests/test_triaje_atc_reglas.py — Triaje de temas NO comerciales → Consulta ATC (2026-10-08, diseño D2):
# FUNCIONES PURAS de agent/triaje_atc.py (normalizar, clasificar, texto_para). Los casos "genuinos" salen de
# las conversaciones reales de producción etiquetadas `consulta_atc` por una persona (anonimizadas); los
# falsos positivos, de los que NO deben cerrarse nunca (compra con gas natural, cuotas en el recibo, etc.).

import pytest

from agent import memory as mem
from agent import triaje_atc as t
from agent.triaje_atc import Contexto, clasificar


def _c(*mensajes, **ctx) -> t.Decision:
    return clasificar(list(mensajes), Contexto(**ctx))


# ── normalizar ───────────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("entrada, esperado", [
    ("Último RECIBO!!!", "ultimo recibo"),
    ("resibooo", "resibo"),
    ("¿Cómo puedo pagar?", "como puedo pagar"),
    ("Señorita", "senorita"),
    ("llega", "lega"),            # letras repetidas colapsadas, igual que memory._normalizar_cortesia
    ("  a   b  ", "a b"),
    ("", ""), (None, ""),
    ("🔥 recibo 🏠", "recibo"),
])
def test_normalizar(entrada, esperado):
    assert t.normalizar(entrada) == esperado


# ── Los 6 genuinos del archivo de ejemplos (y el turno 3) ─────────────────────────────────────────

GENUINOS = [
    ["Holq", "Yasmin", "Quisiera obtener mi último recibo"],
    ["Buenas tardes", "Diana", "Señorita necesito un recibo"],
    ["Buenos días", "Mucho gusto Gaby soy Soledad", "Quiero saber un número de cliente"],
    ["Buenas tardes", "Dori", "Mi recibo"],
    ["Hola", "Marco", "Necesito recibo"],
]


@pytest.mark.parametrize("mensajes", GENUINOS)
def test_los_genuinos_se_cierran(mensajes):
    d = clasificar(mensajes, Contexto(n_msgs_gabi=3))
    assert d.accion == "cerrar" and d.bloqueos == () and d.categoria in ("recibo", "numero_cliente")
    assert d.confianza >= t.UMBRAL_CIERRE and d.senales


def test_el_genuino_del_saludo_de_campana_cierra_si_el_saludo_esta_en_los_patrones():
    saludo = "¡Hola! 👋 Ya cuento con gas natural en casa 🔥🏠 y quisiera información para complementar mi instalación con termas"
    mensajes = [saludo, "María martinez", "Ya tengo el gas pero no llega resibo como puedo pagar"]
    # Sin conocer la campaña, "instalación" es una palabra de compra y NO se cierra (ante la duda, no).
    sin_campana = clasificar(mensajes, Contexto())
    assert sin_campana.accion == "ninguna" and "comercial_instalacion" in sin_campana.bloqueos
    # Con el saludo preestablecido de la campaña, ese primer mensaje queda fuera del bloqueo comercial.
    con_campana = clasificar(mensajes, Contexto(patrones_saludo=(t.normalizar("Ya cuento con gas natural en casa"),), tiene_campana=True))
    assert con_campana.accion == "cerrar" and con_campana.categoria == "recibo"
    assert set(con_campana.senales) == {"recibo_palabra", "recibo_no_llega"}


def test_el_saludo_de_campana_solo_se_exime_si_es_el_primer_mensaje():
    patron = (t.normalizar("Ya cuento con gas natural en casa"),)
    d = clasificar(["Hola", "Ya cuento con gas natural en casa y quiero un horno", "mi recibo"], Contexto(patrones_saludo=patron))
    assert d.accion == "ninguna" and "comercial_producto" in d.bloqueos


def test_un_patron_muy_corto_de_campana_no_exime_nada():
    d = clasificar(["terma", "mi recibo"], Contexto(patrones_saludo=("terma",)))
    assert d.accion == "ninguna" and "comercial_producto" in d.bloqueos


def test_el_recibo_que_llega_en_el_turno_3_tras_saludo_y_nombre_cierra():
    d = clasificar(["Hola buenas tardes", "Me llamo Rosa", "Hola, quiero mi recibo de gas por favor"], Contexto(n_msgs_gabi=2))
    assert d.accion == "cerrar" and d.categoria == "recibo"


def test_solo_cuentan_los_ultimos_2_mensajes_para_el_tema():
    d = clasificar(["necesito mi recibo", "hola", "buenas"], Contexto())
    assert d.categoria == "ninguna"          # el tema quedó 3 mensajes atrás


# ── Categorías ───────────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("texto, categoria", [
    ("necesito una copia de mi factura", "recibo"),
    ("dónde puedo ver mi número de suministro", "numero_cliente"),
    ("cuál es mi número de cliente", "numero_cliente"),
    ("necesito mi código de cliente", "numero_cliente"),
    ("quiero mi cuenta contrato", "numero_cliente"),
    ("tengo una deuda con Cálidda", "pago_deuda"),
    ("quiero el fraccionamiento de mi deuda", "pago_deuda"),
    ("me cortaron el gas por falta de pago", "pago_deuda"),
    ("necesito la reconexión del servicio", "pago_deuda"),
    ("cuáles son los agentes de pago", "pago_deuda"),
    ("ya pagué mi recibo pero me sigue saliendo", "recibo"),
])
def test_cada_categoria_se_reconoce_por_su_tema(texto, categoria):
    d = _c(texto)
    assert d.categoria == categoria and d.accion == "cerrar", d


@pytest.mark.parametrize("texto", [
    "donde pago", "como pago", "no me llega",           # señales demasiado débiles solas: ni candidato
    "hola", "gracias", "ok", "buenas tardes", "quiero información",
])
def test_las_senales_debiles_solas_no_son_ni_candidato(texto):
    d = _c(texto)
    assert d.categoria == "ninguna" and d.accion == "ninguna"


def test_ya_pague_solo_es_candidato_sin_confianza_para_cerrar():
    d = _c("ya pagué")
    assert d.categoria == "pago_deuda" and d.accion == "ninguna" and "confianza_baja" in d.bloqueos


def test_consumo_solo_no_alcanza_para_cerrar():
    d = _c("quiero saber mi consumo")
    assert d.categoria == "recibo" and d.accion == "ninguna" and "confianza_baja" in d.bloqueos
    assert _c("quiero saber mi consumo y vencimiento del recibo").accion == "cerrar"


def test_una_categoria_no_activa_no_cierra():
    d = _c("mi recibo", categorias_activas=("numero_cliente",))
    assert d.categoria == "recibo" and d.accion == "ninguna" and "categoria_inactiva" in d.bloqueos


# ── Falsos positivos: NO deben cerrar ────────────────────────────────────────────────────────────

FALSOS_POSITIVOS = [
    ["Ya cuento con gas natural y quiero un horno"],
    ["Buen día", "Pienso comprar un horno a gas natural Cuanto costara el punto?", "Ya cuento con gas natural"],
    ["¿Cuánto cuesta y cómo lo pago?"],
    ["¿Las cuotas salen en el recibo?"],
    ["¿Hola! Estoy interesado en financiar una Secadora", "Precio de los hilos"],
    ["buenas", "cambio de manguera en la cocina de mi casa"],
    ["Buenos días algún número para el servicio de mantenimiento", "Es gas domestico"],
    ["Hace mantenimiento?", "Número del asesor de cálida", "Tiene?"],
    ["No tengo gas natural ¿pueden instalarme?"],
    ["Buenas tardes deseo que instalen una cocina", "(titular)", "Ya tengo la cocina, es de 2 hornillas"],
    ["¡Hola! Estoy interesado en revisión técnica de una Terma", "(nombre)", "Para usarla debo abrir el caño"],
]


@pytest.mark.parametrize("mensajes", FALSOS_POSITIVOS)
def test_los_falsos_positivos_no_cierran(mensajes):
    assert clasificar(mensajes, Contexto()).accion == "ninguna"


def test_una_sola_palabra_de_compra_en_cualquier_mensaje_bloquea_aunque_el_tema_sea_el_recibo():
    d = clasificar(["Quiero comprar una cocina", "Pedro", "pero antes mi recibo"], Contexto())
    assert d.categoria == "recibo" and d.accion == "ninguna"
    assert {"comercial_compra", "comercial_producto"} <= set(d.bloqueos)


@pytest.mark.parametrize("texto, bloqueo", [
    ("mi recibo y el precio de una terma", "comercial_precio"),
    ("mi recibo, puedo pagar en cuotas", "comercial_cuota"),
    ("mi recibo del horno financiado", "comercial_cuota"),
    ("mi recibo, quiero una instalación", "comercial_instalacion"),
    ("mi recibo, necesito mantenimiento", "comercial_servicio"),
    ("mi recibo, quiero hablar con un asesor", "comercial_asesor"),
])
def test_cada_familia_comercial_bloquea(texto, bloqueo):
    d = _c(texto)
    assert d.accion == "ninguna" and bloqueo in d.bloqueos


# ── Guardas ──────────────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("ctx, guarda", [
    ({"con_asesor_o_pausa": True}, "asesor_o_pausa"),
    ({"hay_humano": True}, "humano_escribio"),
    ({"cerrado": True}, "caso_cerrado"),
    ({"resultado": "agendado"}, "ya_tiene_resultado"),
    ({"paso_flujo": "evaluando_financiamiento"}, "paso_flujo_evaluando_financiamiento"),
    ({"paso_flujo": "derivado_asesor"}, "paso_flujo_derivado_asesor"),
    ({"triaje_previo": True}, "triaje_previo_en_el_ciclo"),
    ({"ultimo_gabi": "Perfecto. ¿Me compartes tu DNI para validar?"}, "gabi_pidio_dni_suministro_titular"),
    ({"ultimo_gabi": "¿Cuál es el número de suministro del recibo?"}, "gabi_pidio_dni_suministro_titular"),
    ({"ultimo_gabi": "¿Eres el titular del servicio?"}, "gabi_pidio_dni_suministro_titular"),
    ({"gabi_dio_precio": True}, "gabi_dio_precio"),
    ({"hay_media": True}, "cliente_envio_media"),
    ({"n_msgs_cliente": 5}, "demasiados_mensajes_del_cliente"),
    ({"canal_pruebas": True}, "canal_de_pruebas"),
    ({"telefono_excluido": True}, "equipo_o_prueba"),
])
def test_cada_guarda_impide_cerrar(ctx, guarda):
    d = clasificar(["Dori", "Mi recibo"], Contexto(**ctx))
    assert d.categoria == "recibo" and d.accion == "ninguna" and guarda in d.bloqueos


def test_el_limite_de_mensajes_es_configurable_y_cuatro_todavia_cierra():
    ms = ["hola", "Rosa", "ok", "mi recibo"]
    assert clasificar(ms, Contexto(n_msgs_cliente=4)).accion == "cerrar"
    assert clasificar(ms, Contexto(n_msgs_cliente=5)).accion == "ninguna"
    assert clasificar(ms, Contexto(n_msgs_cliente=5, max_mensajes_cliente=6)).accion == "cerrar"
    assert clasificar(ms, Contexto(n_msgs_cliente=3, max_mensajes_cliente=2)).accion == "ninguna"


@pytest.mark.parametrize("numero", ["12345678", "999 888 777", "999-888-777", "51999888777", "123456789012", "20.123.456"])
def test_un_numero_largo_o_dni_en_cualquier_mensaje_impide_cerrar(numero):
    d = clasificar(["Mi recibo", f"mi dato es {numero}"], Contexto())
    assert "numero_largo_o_dni" in d.bloqueos and d.accion == "ninguna"


@pytest.mark.parametrize("numero", ["1234567", "614900", "opción 5"])
def test_los_numeros_cortos_no_cuentan_como_dni(numero):
    assert "numero_largo_o_dni" not in clasificar(["Mi recibo", f"vi el {numero}"], Contexto()).bloqueos


def test_mi_recibo_justo_despues_de_que_gabi_pidio_dni_no_cierra():
    ctx = Contexto(ultimo_gabi="Para validar tu financiamiento necesito tu DNI y el número de suministro.")
    assert clasificar(["Dori", "mi recibo"], ctx).accion == "ninguna"


@pytest.mark.parametrize("texto", ["prueba flow", "Prueba", "probando", "test"])
def test_los_mensajes_de_prueba_del_equipo_no_cierran(texto):
    d = clasificar([texto, "mi recibo"], Contexto())
    assert "equipo_o_prueba" in d.bloqueos and d.accion == "ninguna"


def test_prueba_en_medio_de_una_frase_no_cuenta_como_mensaje_de_prueba():
    assert clasificar(["no tengo prueba de pago, quiero mi recibo"], Contexto()).accion == "cerrar"


# ── Emergencia de gas ────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("texto", [
    "huele a gas en mi casa", "Hay olor a gas!!", "creo que hay una fuga de gas", "se escapa el gas de la cocina",
    "huelo gas en la cocina", "hubo una explosión",
])
def test_la_emergencia_se_clasifica_con_accion_de_alerta_y_nunca_cierra(texto):
    d = _c(texto)
    assert d.categoria == "emergencia_gas" and d.accion == "alerta_emergencia" and d.senales


def test_la_emergencia_se_detecta_en_cualquier_mensaje_y_gana_al_recibo():
    d = clasificar(["huele a gas", "Rosa", "mi recibo"], Contexto())
    assert d.categoria == "emergencia_gas" and d.accion == "alerta_emergencia"


def test_fuga_de_agua_no_es_emergencia_de_gas():
    assert _c("tengo una fuga de agua").categoria == "ninguna"


# ── Texto al cliente ─────────────────────────────────────────────────────────────────────────────

def test_el_texto_por_defecto_lleva_nombre_linea_y_negocio():
    texto = t.texto_para(None, "yasmin perez", "614900, opción 5", "Gaso+")
    assert texto.startswith("¡Hola Yasmin! 😊")
    assert "614900, opción 5" in texto and "Aquí en Gaso+ te ayudamos" in texto
    assert "{" not in texto and "}" not in texto


def test_el_saludo_no_lleva_nombre_si_no_hay_uno_presentable():
    for nombre in (None, "", "   ", "12345", "Juan123", "x" * 40, "###"):
        assert t.texto_para(None, nombre, "614900").startswith("¡Hola! 😊")


def test_el_nombre_del_negocio_sale_del_parametro_y_el_texto_por_defecto_no_lo_hardcodea():
    assert "{negocio}" in t.TEXTO_POR_DEFECTO and "Gaso+" not in t.TEXTO_POR_DEFECTO
    assert "Cálidda Hogar" in t.texto_para(None, None, "614900", "Cálidda Hogar")
    assert f"Aquí en {t.NOMBRE_NEGOCIO_POR_DEFECTO} " in t.texto_para(None, None, "614900", "")   # fallback documentado


def test_las_plantillas_personalizadas_usan_reemplazo_literal_y_no_se_rompen_con_llaves():
    texto = t.texto_para("Hola{nombre} {x} {linea_atc} / {linea_emergencia} / {linea_ventas}", "Ana", "614900", "N", "1808", "614-9002")
    assert texto == "Hola Ana {x} 614900 / 1808 / 614-9002"


@pytest.mark.parametrize("linea", ["614900, opción 5", "614 9000 opción 5", "(01) 614-9000, opción 5", "0800 1 2345"])
def test_el_texto_por_defecto_no_deja_nada_pendiente_para_el_cierre_de_cortesia(linea):
    texto = t.texto_para(None, "Yasmin", linea)
    # Sin "?" ni compromiso/petición (C2/C3): así un "ok" posterior del cliente se absorbe en vez de reabrir el caso.
    assert "?" not in texto and "¿" not in texto
    assert mem.saliente_deja_algo_pendiente(texto) is False


def test_un_gracias_y_un_ok_posteriores_son_cierres_de_cortesia_absorbibles():
    assert mem.nivel_cierre_cortesia("gracias") == "A"
    assert mem.nivel_cierre_cortesia("ok") == "B"
