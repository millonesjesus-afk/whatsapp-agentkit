"""Convierte la lista de precios mensual en Excel (LP ... ALOC ... LIMPIO.xlsx) al CSV que importa el catálogo — 2026-10-24.

El Excel trae: N°, PROVEEDOR, MARCA, TIPO, SUB TIPO, INCLUYE CONEXIÓN, CODIGO HANA, Producto principal calculado, Combo calculado,
COMENTARIOS, FEE CLDA, FEE PRV, PRECIO. La importación (agent/memory.py::importar_catalogo_desde_csv, o el botón «Importar» del
Catálogo) espera el formato CSV de siempre: CANAL, DESCRIPCIÓN, COMBO y las cuotas por plazo. Este script arma esas columnas:

  · CANAL        = el que se indique (por defecto ALOC, el del catálogo de producción).
  · DESCRIPCIÓN  = «Producto principal calculado».   · COMBO = «Combo calculado» (vacío si no hay).
  · Cuotas 3/6/9/12/18/24/36/48/60 = las MISMAS que calcula Gabi en vivo (agent/tools.py::_calcular_amortizacion, TEA 40 % y
    IGV 18 % por defecto) para que lo guardado coincida con lo que se le dice al cliente.

Por seguridad NO escribe en ninguna base: solo genera el CSV y un resumen. Las filas sin código, sin precio o con un CODIGO HANA
repetido se listan como advertencia (el importador degrada un código repetido a alta/baja).

Uso:
    python scripts/convertir_lista_precios_xlsx.py "LP_OCTUBRE ALOC 2026 - LIMPIO.xlsx" salida.csv
    python scripts/convertir_lista_precios_xlsx.py lista.xlsx salida.csv --canal ALOC --tea 0.40 --igv 0.18
"""
import argparse
import csv
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent.tools import _calcular_amortizacion

ENCABEZADO = [
    "N°", "CANAL", "PROVEEDOR", "MARCA", "TIPO", "SUB TIPO", "CODIGO HANA", "DESCRIPCIÓN", "COMBO", "INCLUYE CONEXIÓN", "COMENTARIOS",
    "FEE PRV", "FEE CLDA", "PRECIO", "3", "6", "9", "12", "18", "24", "36", "48", "60",
]
PLAZOS = (3, 6, 9, 12, 18, 24, 36, 48, 60)
COLUMNAS_EXCEL = ("PROVEEDOR", "MARCA", "TIPO", "SUB TIPO", "CODIGO HANA", "PRECIO")


def _texto(valor) -> str:
    if valor is None:
        return ""
    if isinstance(valor, float) and valor.is_integer():
        valor = int(valor)
    return str(valor).strip()


def _indice_de_columnas(encabezado: tuple) -> dict:
    """Ubica cada columna por su nombre (sin importar tildes ni el signo raro de «N°»/«CONEXIÓN»)."""
    def clave(t):
        return "".join(c for c in _texto(t).upper() if c.isalnum() or c == " ").replace("  ", " ").strip()
    por_clave = {clave(t): i for i, t in enumerate(encabezado) if _texto(t)}
    def buscar(*nombres):
        for n in nombres:
            for k, i in por_clave.items():
                if k.startswith(n):
                    return i
        return None
    indices = {
        "PROVEEDOR": buscar("PROVEEDOR"), "MARCA": buscar("MARCA"), "TIPO": buscar("TIPO"), "SUB TIPO": buscar("SUB TIPO"),
        "CONEXION": buscar("INCLUYE CONEXI"), "CODIGO": buscar("CODIGO HANA"), "PRINCIPAL": buscar("PRODUCTO PRINCIPAL", "DESCRIPCI"),
        "COMBO": buscar("COMBO"), "COMENTARIOS": buscar("COMENTARIOS"), "FEE CLDA": buscar("FEE CLDA"), "FEE PRV": buscar("FEE PRV"),
        "PRECIO": buscar("PRECIO"),
    }
    faltan = [n for n in ("PROVEEDOR", "MARCA", "TIPO", "CODIGO", "PRINCIPAL", "PRECIO") if indices[n] is None]
    if faltan:
        raise ValueError(f"Faltan columnas en el Excel: {', '.join(faltan)}")
    return indices


def convertir(filas_excel: list[tuple], canal: str = "ALOC", tea: float = 0.40, igv: float = 0.18) -> tuple[list[list[str]], dict]:
    """Devuelve (filas CSV sin encabezado, resumen con advertencias). `filas_excel[0]` es el encabezado."""
    idx = _indice_de_columnas(filas_excel[0])
    salida: list[list[str]] = []
    advertencias: list[str] = []
    codigos: Counter = Counter()
    for numero, fila in enumerate(filas_excel[1:], start=2):
        def v(nombre):
            i = idx.get(nombre)
            return _texto(fila[i]) if i is not None and i < len(fila) else ""
        if not any(_texto(c) for c in fila[:14]):
            continue
        codigo, precio = v("CODIGO"), v("PRECIO")
        if not codigo:
            advertencias.append(f"fila {numero}: sin CODIGO HANA")
        try:
            monto = float(precio)
        except ValueError:
            advertencias.append(f"fila {numero}: precio no numérico ({precio!r})")
            continue
        codigos[codigo] += 1
        cuotas = [f"{_calcular_amortizacion(monto, tea, igv, p)['cuota_inicial']:.2f}" for p in PLAZOS]
        salida.append([
            str(len(salida) + 1), canal, v("PROVEEDOR"), v("MARCA"), v("TIPO"), v("SUB TIPO"), codigo, v("PRINCIPAL"), v("COMBO"),
            v("CONEXION"), v("COMENTARIOS"), v("FEE PRV"), v("FEE CLDA"), precio, *cuotas,
        ])
    repetidos = sorted(c for c, n in codigos.items() if n > 1 and c)
    for c in repetidos:
        advertencias.append(f"CODIGO HANA repetido ({codigos[c]} filas): {c}")
    resumen = {"filas": len(salida), "codigos_unicos": len([c for c in codigos if c]), "advertencias": advertencias}
    return salida, resumen


def main(argv=None) -> dict:
    p = argparse.ArgumentParser(description="Convierte la lista de precios .xlsx al CSV del importador.")
    p.add_argument("xlsx")
    p.add_argument("salida")
    p.add_argument("--canal", default="ALOC")
    p.add_argument("--tea", type=float, default=0.40)
    p.add_argument("--igv", type=float, default=0.18)
    args = p.parse_args(argv)
    import openpyxl
    hoja = openpyxl.load_workbook(args.xlsx, data_only=True).worksheets[0]
    filas, resumen = convertir([tuple(f) for f in hoja.iter_rows(values_only=True)], args.canal, args.tea, args.igv)
    with open(args.salida, "w", encoding="utf-8-sig", newline="") as f:
        escritor = csv.writer(f)
        escritor.writerow(ENCABEZADO)
        escritor.writerows(filas)
    print(resumen)
    return resumen


if __name__ == "__main__":
    main()
