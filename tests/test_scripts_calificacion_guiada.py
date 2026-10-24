# tests/test_scripts_calificacion_guiada.py — activar con marca de hora y medir antes/después (solo lectura, solo agregados).
import json
from datetime import datetime, timedelta

from agent import calificacion_guiada as cg, memory as mem
from scripts import configurar_calificacion_guiada as conf, medir_calificacion_guiada as med


def test_resumir_una_cohorte():
    filas = [
        {"n_cliente": 1, "derivado": False, "resultado": None, "tiene_producto": True, "tiene_nombre": False, "titular_respondido": False},
        {"n_cliente": 4, "derivado": True, "resultado": "agendado", "tiene_producto": True, "tiene_nombre": True, "titular_respondido": True},
        {"n_cliente": 6, "derivado": True, "resultado": "vendido", "tiene_producto": True, "tiene_nombre": False, "titular_respondido": False},
        {"n_cliente": 2, "derivado": False, "resultado": "sin_respuesta", "tiene_producto": False, "tiene_nombre": False, "titular_respondido": False},
    ]
    r = med.resumir(filas)
    assert r["conversaciones"] == 4 and r["pct_2_mas_mensajes"] == 75.0 and r["mensajes_cliente_promedio"] == 3.25
    assert r["pct_derivadas"] == 50.0 and r["pct_agendado"] == 25.0 and r["pct_vendido"] == 25.0
    assert r["derivadas"] == 2 and r["pct_derivadas_con_producto_y_nombre"] == 50.0 and r["pct_derivadas_con_titular"] == 50.0


def test_resumir_sin_datos_no_divide_por_cero():
    r = med.resumir([])
    assert r["conversaciones"] == 0 and r["pct_derivadas"] is None and r["mensajes_cliente_promedio"] is None


async def test_activar_guarda_la_marca_y_no_la_mueve_al_reactivar():
    negocio = await mem.crear_negocio("Negocio sc-1", "sc-1")
    base = ["--negocio-id", negocio["id"]]
    mostrado = await conf.main(base)
    assert mostrado["modo"] == "apagado" and mostrado["activa_desde"] is None and mostrado["cambios"] == []
    activo = await conf.main(base + ["--activar"])
    assert activo["modo"] == "activo" and activo["activa_desde"].endswith("Z")
    corte = activo["activa_desde"]
    await conf.main(base + ["--desactivar"])
    reactivado = await conf.main(base + ["--activar"])
    assert reactivado["modo"] == "activo" and reactivado["activa_desde"] == corte          # el corte no se mueve
    assert (await conf.main(base + ["--activar", "--nuevo-corte"]))["activa_desde"] >= corte
    assert (await conf.main(base + ["--telefono", "  614 9000,   opción 5 "]))["telefono_suministros"] == "614 9000, opción 5"
    assert await cg.obtener_modo(negocio["id"]) == "activo"


async def test_medir_compara_antes_y_despues_sin_datos_personales(capsys):
    negocio = await mem.crear_negocio("Negocio sc-2", "sc-2")
    canal = await mem.crear_canal_whatsapp(nombre="Canal sc-2", phone_number_id="40990002", negocio_id=negocio["id"])
    ahora = datetime.utcnow()
    for i, (tel, dias) in enumerate((("51960000001", 3), ("51960000002", 2), ("51960000003", 0.5))):
        await mem.actualizar_lead(tel, negocio_id=negocio["id"], numero_whatsapp_id="x", nombre=f"Cliente {i}", interes="terma")
        conv, _ = await mem.resolver_conversation_activa(tel, negocio["id"], canal["id"])
        async with mem.async_session() as s:
            c = await s.get(mem.Conversation, conv.id)
            c.creado = ahora - timedelta(days=dias)
            await s.commit()
        for _ in range(i + 1):
            await mem.guardar_mensaje(tel, "user", "hola", negocio_id=negocio["id"])
    corte = (ahora - timedelta(days=1)).replace(microsecond=0).isoformat() + "Z"
    salida = await med.main(["--negocio-id", negocio["id"], "--dias", "10", "--corte", corte])
    assert salida["antes"]["conversaciones"] == 2 and salida["despues"]["conversaciones"] == 1
    assert salida["por_producto"]["terma"]["antes"]["conversaciones"] == 2
    texto = capsys.readouterr().out
    assert "ANTES" in texto and "DESPUÉS" in texto and "5196000" not in texto and "Cliente" not in texto
    json.dumps(salida)


async def test_medir_sin_corte_avisa_y_no_falla(capsys):
    negocio = await mem.crear_negocio("Negocio sc-3", "sc-3")
    assert await med.main(["--negocio-id", negocio["id"]]) == {}
    assert "No hay corte" in capsys.readouterr().out
