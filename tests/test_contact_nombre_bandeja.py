# tests/test_contact_nombre_bandeja.py — el nombre que Gabi/el panel guardan en
# Lead.nombre tiene que verse en la Bandeja, que lee Contact.nombre
# (2026-09-21: la lista mostraba solo teléfonos aunque Gabi ya sabía el nombre).

import importlib.util
from pathlib import Path

import pytest
from sqlalchemy import text

from agent import memory as mem

RAIZ = Path(__file__).resolve().parent.parent


async def _negocio_con_canal(codigo: str, telefono_canal: str):
    negocio = await mem.crear_negocio(f"Negocio {codigo}", codigo)
    canal = await mem.crear_canal_whatsapp(
        nombre=f"Canal {codigo}", phone_number_id=telefono_canal, negocio_id=negocio["id"],
    )
    return negocio, canal


def _cargar(ruta_relativa: str, nombre: str):
    spec = importlib.util.spec_from_file_location(nombre, RAIZ / ruta_relativa)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


async def _nombre_en_bandeja(negocio_id: str, telefono: str):
    filas, _ = await mem.listar_conversaciones_activas(negocio_id)
    return next(f["nombre"] for f in filas if f["telefono"] == telefono)


async def test_nombre_extraido_por_gabi_aparece_en_la_bandeja():
    negocio, canal = await _negocio_con_canal("g-nom-1", "40300000001")
    telefono = "51900700001"
    await mem.resolver_conversation_activa(telefono, negocio["id"], canal["id"])
    assert await _nombre_en_bandeja(negocio["id"], telefono) is None

    await mem.actualizar_lead(telefono, nombre="Alicia", negocio_id=negocio["id"])

    assert await _nombre_en_bandeja(negocio["id"], telefono) == "Alicia"


async def test_el_buscador_de_la_bandeja_encuentra_por_nombre():
    negocio, canal = await _negocio_con_canal("g-nom-2", "40300000002")
    telefono = "51900700002"
    await mem.resolver_conversation_activa(telefono, negocio["id"], canal["id"])
    await mem.actualizar_lead(telefono, nombre="Rosario", negocio_id=negocio["id"])

    filas, total = await mem.listar_conversaciones_activas(negocio["id"], busqueda="Rosar")

    assert total == 1 and filas[0]["telefono"] == telefono


async def test_nombre_vacio_de_gabi_no_borra_el_nombre_del_contacto():
    negocio, canal = await _negocio_con_canal("g-nom-3", "40300000003")
    telefono = "51900700003"
    await mem.resolver_conversation_activa(telefono, negocio["id"], canal["id"])
    await mem.actualizar_lead(telefono, nombre="Carmen", negocio_id=negocio["id"])

    await mem.actualizar_lead(telefono, nombre=None, interes="terma")

    assert await _nombre_en_bandeja(negocio["id"], telefono) == "Carmen"


async def test_migracion_rellena_nombre_solo_donde_falta():
    negocio, canal = await _negocio_con_canal("g-nom-4", "40300000004")
    sin_nombre, con_nombre = "51900700004", "51900700005"
    for tel in (sin_nombre, con_nombre):
        await mem.resolver_conversation_activa(tel, negocio["id"], canal["id"])
    await mem.actualizar_lead(sin_nombre, nombre="Del lead", negocio_id=negocio["id"])
    await mem.actualizar_lead(con_nombre, nombre="Otro del lead", negocio_id=negocio["id"])
    # Estado previo al arreglo: el contacto quedó sin nombre (o con uno propio).
    async with mem.async_session() as session:
        await session.execute(text("UPDATE contacts SET nombre = NULL WHERE telefono = :t"), {"t": sin_nombre})
        await session.execute(
            text("UPDATE contacts SET nombre = 'Ya existente' WHERE telefono = :t"), {"t": con_nombre}
        )
        await session.commit()

    migracion = _cargar(
        "migrations/versions/a7d3b91c5e42_rellenar_nombre_de_contacts_desde_leads.py", "mig_rellenar_nombres",
    )
    async with mem.async_session() as session:
        await session.execute(text(migracion.SQL_RELLENAR_NOMBRES))
        await session.commit()

    assert await _nombre_en_bandeja(negocio["id"], sin_nombre) == "Del lead"
    assert await _nombre_en_bandeja(negocio["id"], con_nombre) == "Ya existente"


async def test_cron_de_inactividad_omite_telefonos_invalidos_y_los_nombra(monkeypatch, capsys):
    script = _cargar("scripts/procesar_inactividad_clientes.py", "script_inactividad")
    enviados = []

    class ProveedorFalso:
        async def resolver_canal(self, numero_whatsapp_id, negocio_id=None):
            return {"phone_number_id": "x"}

        async def enviar_mensaje(self, telefono, mensaje, canal=None):
            enviados.append(telefono)
            return True, "wamid.1"

    async def candidatos(horas_reenganche, horas_cierre):
        fila = {"negocio_id": "n", "numero_whatsapp_id": "x"}
        return [{**fila, "telefono": ""}, {**fila, "telefono": "51900700009"}], []

    async def guardar(*args, **kwargs):
        return {"conversation_id": None}

    async def emitir(_):
        return None

    monkeypatch.setattr(script, "listar_leads_inactividad_cliente", candidatos)
    monkeypatch.setattr(script, "obtener_proveedor", lambda: ProveedorFalso())
    monkeypatch.setattr(script, "guardar_mensaje", guardar)
    monkeypatch.setattr(script.gestor_conexiones, "emitir_mensaje_nuevo", emitir)

    await script.main()

    assert enviados == ["51900700009"]
    salida = capsys.readouterr().out
    assert "1 reenganchado(s)" in salida
    assert "Omitidos por teléfono inválido: ''" in salida
