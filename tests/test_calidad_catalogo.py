"""Avisos de calidad al importar el catálogo: no bloquean, pero señalan lo que dejaría a Gabi sin dato."""
from agent.calidad_catalogo import avisos_de_calidad_catalogo as avisar


def fila(descripcion, tipo="TERMA", precio="1000", marca="SOLE", conexion="SI", **extra):
    return {"descripcion": descripcion, "tipo": tipo, "sub_tipo": tipo, "precio": precio, "marca": marca,
            "incluye_conexion": conexion, "codigo_hana": "4500001", "proveedor": "P", **extra}


def tipos(filas, **kw):
    return sorted(a["tipo"] for a in avisar(filas, **kw)["avisos"] if a["tipo"] != "categoria_vacia")


def base():
    """Una fila buena de cada categoría que el flujo ofrece: así no se activa el aviso de categoría vacía."""
    return [fila("TERMA SOLE 10 LT", "TERMA"), fila("SECADORA MABE 22 KG", "SECADORA"),
            fila("COCINA MABE 4 H", "COCINA")]


def test_filas_completas_no_generan_avisos():
    assert avisar(base())["total"] == 0


def test_terma_sin_litros_avisa_y_con_litros_no():
    for bueno in ("TERMA SOLE 10 LT - TIRO FORZADO", "Terma 5.5L", "TERMA RHEEM 8 LTS TN", "TERMA 14 L/MIN", "TERMOTANQUE SOLE 110 LT"):
        assert tipos(base() + [fila(bueno)]) == [], bueno
    assert tipos(base() + [fila("TERMA SOLE TERMO DIG 14 TIRO FORZADO")]) == ["sin_capacidad"]  # 14 sin unidad


def test_secadora_y_centro_de_lavado_exigen_kilos():
    assert tipos(base() + [fila("SECADORA MABE SMG47N8MSBB0", "SECADORA")]) == ["sin_capacidad"]
    assert tipos(base() + [fila("SECADORA MABE 24KG NEGRO", "SECADORA")]) == []
    assert tipos(base() + [fila("LAVADORA LG WT16 NEGRO", "LAVADORA")]) == ["sin_capacidad"]
    assert tipos(base() + [fila("LAVASECADORA LG 20 KG", "LAVADORA")]) == []


def test_el_aviso_de_capacidad_dice_que_unidad_falta():
    a = avisar(base() + [fila("SECADORA MABE X", "SECADORA")])["avisos"][0]
    assert "kilos" in a["mensaje"] and a["codigo"] == "4500001" and a["descripcion"] == "SECADORA MABE X"


def test_precio_vacio_o_no_numerico_avisa():
    for malo in ("", None, "consultar", "0"):
        assert "sin_precio" in tipos(base() + [fila("TERMA SOLE 10 LT", precio=malo)]), malo
    for bueno in ("1709", "S/ 1,709.00", "1709.5"):
        assert tipos(base() + [fila("TERMA SOLE 10 LT", precio=bueno)]) == [], bueno


def test_sin_marca_tipo_o_conexion_avisa():
    assert tipos(base() + [fila("TERMA SOLE 10 LT", marca="")]) == ["sin_marca"]
    assert "sin_tipo" in tipos(base() + [{**fila("TERMA SOLE 10 LT"), "tipo": "", "sub_tipo": ""}])
    assert tipos(base() + [fila("TERMA SOLE 10 LT", conexion="")]) == ["sin_conexion"]


def test_los_servicios_no_se_tratan_como_equipos():
    punto = {"descripcion": "PUNTO ADICIONAL", "tipo": "TRABAJOS", "sub_tipo": "PUNTO ADICIONAL", "precio": "300",
             "marca": "CALIDDA", "incluye_conexion": "", "codigo_hana": "1", "proveedor": "P"}
    assert tipos(base() + [punto]) == []


def test_categoria_sin_ningun_producto_con_precio_deja_a_gabi_sin_piso():
    r = avisar([fila("TERMA SOLE 10 LT", "TERMA"), fila("COCINA MABE 4 H", "COCINA")])
    vacias = [a["descripcion"] for a in r["avisos"] if a["tipo"] == "categoria_vacia"]
    assert vacias == ["secadora"]
    sin_precio = avisar([fila("TERMA SOLE 10 LT", precio=""), *base()[1:]])
    assert [a["descripcion"] for a in sin_precio["avisos"] if a["tipo"] == "categoria_vacia"] == ["terma"]


def test_las_filas_excluidas_no_avisan_y_el_resumen_cuenta_por_tipo():
    excluida = fila("LAVADORA SIN KG", "LAVADORA", proveedor="GRUPO")
    assert tipos(base() + [excluida], excluidas={("GRUPO", "LAVADORA SIN KG")}) == []
    r = avisar(base() + [fila("SECADORA A", "SECADORA"), fila("SECADORA B", "SECADORA")])
    assert r["por_tipo"] == {"sin_capacidad": 2} and r["total"] == 2


async def test_la_ruta_de_importar_devuelve_los_avisos_sin_bloquear():
    import io
    import json
    from starlette.datastructures import UploadFile
    from agent import dashboard, memory as mem

    negocio = await mem.crear_negocio("Negocio Calidad", "calidad1")
    csv_texto = (
        "N°,CANAL,PROVEEDOR,MARCA,TIPO,SUB TIPO,CODIGO HANA,DESCRIPCIÓN,COMBO,COMENTARIOS,FEE PRV,FEE CLDA,PRECIO,INCLUYE CONEXIÓN\n"
        "1,ALOC,P,MABE,SECADORA,SECADORA,4506068,SECADORA MABE SMG47N8MSBB0,,,0.1,0.1,2999,SI\n"
        "2,ALOC,P,SOLE,TERMA,TERMA,4500001,TERMA SOLE 10 LT,,,0.1,0.1,699,SI\n"
        "3,ALOC,P,MABE,COCINA,COCINA,4500002,COCINA MABE 4 H,,,0.1,0.1,899,SI\n"
    )
    archivo = UploadFile(filename="lista.csv", file=io.BytesIO(csv_texto.encode("utf-8")))
    r = await dashboard.importar_productos_ruta(
        archivo, {"rol": "admin", "negocio_id": negocio["id"], "nombre": "t", "username": "t"}, None,
    )
    cuerpo = json.loads(r.body)
    assert cuerpo["ok"] and cuerpo["resumen"]["nuevos"] == 3                    # se importó todo: los avisos no bloquean
    assert cuerpo["calidad"]["por_tipo"] == {"sin_capacidad": 1}
    assert cuerpo["calidad"]["avisos"][0]["codigo"] == "4506068"
