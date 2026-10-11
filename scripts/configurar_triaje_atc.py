"""Configura (o muestra) el triaje de temas no comerciales → Consulta ATC y la métrica del embudo — 2026-10-08.

El triaje (agent/triaje_atc.py) viene APAGADO. Este script fija sus claves de configuración por negocio, con
validación, sin tocar código ni desplegar. Tampoco manda ningún mensaje ni es un Cron.

Uso (la base sale de DATABASE_URL, como en los demás scripts; sin ninguna opción solo MUESTRA lo configurado):
    python scripts/configurar_triaje_atc.py --negocio-id <id>
    # 1) Líneas (sin ellas el modo activo se degrada a sombra):
    python scripts/configurar_triaje_atc.py --negocio-id <id> --linea "614900, opción 5" \
        --linea-emergencia "1808 (Emergencias 24/7)" --linea-ventas "614-9002"
    # 2) MODO SOMBRA: solo log + evento interno, Gabi responde igual que siempre:
    python scripts/configurar_triaje_atc.py --negocio-id <id> --modo sombra
    # 3) Más adelante, ya medido (scripts/analisis_triaje_atc.py): activar o volver a apagar:
    python scripts/configurar_triaje_atc.py --negocio-id <id> --modo activo
    python scripts/configurar_triaje_atc.py --negocio-id <id> --modo apagado
    # EMERGENCIA DE GAS (interruptor PROPIO, independiente de --modo; default apagado). Aviso fijo y sin IA hacia
    # Emergencias de Cálidda + cierre como consulta_atc. Necesita --linea-emergencia (o un texto propio con el número):
    python scripts/configurar_triaje_atc.py --negocio-id <id> --emergencia-modo sombra   # solo log + evento interno
    python scripts/configurar_triaje_atc.py --negocio-id <id> --emergencia-modo activo   # envía el aviso y cierra
    python scripts/configurar_triaje_atc.py --negocio-id <id> --emergencia-modo apagado
    # Métrica del embudo: excluir las consultas ATC del denominador comercial (desde una fecha opcional):
    python scripts/configurar_triaje_atc.py --negocio-id <id> --excluir-consulta-atc 1 --excluir-desde 2026-10-09

Otras opciones: --categorias recibo,numero_cliente,pago_deuda · --texto "…{nombre}…{linea_atc}…{negocio}" ·
--texto-categoria recibo="…" (repetible) · --max-mensajes 4 · --nombre-negocio "Gaso+" ·
--telefonos-excluidos 51999…,51988… (equipo/pruebas) · --permitir-canal-pruebas 1 · "" en un valor texto lo borra.
--emergencia-texto "…{linea_emergencia}…" (debe llevar {linea_emergencia}, sin «?» ni «¿»; vacío = texto por defecto del módulo).
"""
import argparse
import asyncio
import json
import re
import sys
from datetime import datetime
from pathlib import Path

# Permite correr este script directo (python scripts/archivo.py) — mismo patrón que los demás scripts.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent import memory as mem
from agent import triaje_atc as t
# Las validaciones de texto viven en un módulo común: las usan este script y el panel «Derivación automática»
# (GET/POST /dashboard/configuracion/derivacion-automatica.json). Se reexportan aquí con los mismos nombres.
from agent.derivacion_automatica import (  # noqa: F401
    LINEA_MAXIMA, TEXTO_MAXIMO, validar_texto, validar_texto_emergencia,
)

MAX_MENSAJES_RANGO = (1, 20)


def _argumentos(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Configura el triaje de temas no comerciales (Consulta ATC) y la métrica del embudo.")
    p.add_argument("--negocio-id", default=None, help="Id del negocio. Si se omite y existe un solo negocio activo, se usa ese.")
    p.add_argument("--modo", choices=t.MODOS, default=None, help="apagado (default del sistema) | sombra | activo.")
    p.add_argument("--linea", default=None, help='Línea de atención de Cálidda tal como se dice al cliente, p. ej. "614900, opción 5".')
    p.add_argument("--linea-emergencia", default=None, help='p. ej. "1808 (Emergencias 24/7)": la línea del aviso de emergencia de gas.')
    p.add_argument("--linea-ventas", default=None, help='p. ej. "614-9002" (ventas Cálidda Hogar; informativa).')
    p.add_argument("--emergencia-modo", choices=t.MODOS, default=None, help="Emergencia de gas (interruptor propio): apagado (default) | sombra | activo.")
    p.add_argument("--emergencia-texto", default=None, help="Plantilla del aviso de emergencia: debe llevar {linea_emergencia}; sin «?». Vacío = texto por defecto.")
    p.add_argument("--categorias", default=None, help=f"Categorías activas, separadas por comas (válidas: {', '.join(t.CATEGORIAS_ATC)}).")
    p.add_argument("--texto", default=None, help="Plantilla general con {nombre}, {linea_atc}, {negocio}, {linea_emergencia}, {linea_ventas}.")
    p.add_argument("--texto-categoria", action="append", default=[], metavar="CATEGORIA=TEXTO", help="Plantilla propia de una categoría (repetible).")
    p.add_argument("--resultado", default=None, help=f"Resultado con que se tipifica y cierra (default {mem.RESULTADO_TRIAJE_POR_DEFECTO}; válidos: {', '.join(mem.RESULTADOS_TRIAJE_PERMITIDOS)}).")
    p.add_argument("--max-mensajes", type=int, default=None, help="Máximo de mensajes del cliente para triar (default 4).")
    p.add_argument("--nombre-negocio", default=None, help="Nombre del negocio que sale en el texto (fallback: Gaso+).")
    p.add_argument("--telefonos-excluidos", default=None, help="Números del equipo/pruebas a los que nunca se triará, separados por comas.")
    p.add_argument("--permitir-canal-pruebas", choices=("0", "1"), default=None, help="1 deja cerrar también en un canal de pruebas.")
    p.add_argument("--excluir-consulta-atc", choices=("0", "1"), default=None, help="Métrica: 1 saca las consultas ATC del denominador comercial.")
    p.add_argument("--excluir-desde", default=None, help="Métrica: fecha AAAA-MM-DD (Lima) desde la que se excluyen; vacío = todo el período.")
    return p.parse_args(argv)


def resolver_negocio_id(negocio_id: str | None, negocios: list[dict]) -> str:
    """El id indicado, o el del ÚNICO negocio activo si no se indicó. Con varios negocios exige --negocio-id."""
    if negocio_id:
        return negocio_id
    activos = [n for n in negocios if n.get("activo", True)]
    if len(activos) == 1:
        return activos[0]["id"]
    disponibles = ", ".join(f"{n.get('id')} ({n.get('nombre') or n.get('codigo') or '?'})" for n in activos) or "ninguno"
    raise ValueError(f"Hay {len(activos)} negocios activos: indica --negocio-id. Disponibles: {disponibles}.")


def validar_fecha(valor: str) -> str:
    valor = valor.strip()
    if valor:
        try:
            datetime.strptime(valor, "%Y-%m-%d")
        except ValueError:
            raise ValueError("--excluir-desde debe ser AAAA-MM-DD (o vacío).")
    return valor


def _cambios_desde(args, avisos: list[str] | None = None) -> dict[str, str]:
    """Valida los argumentos y devuelve {clave de configuración: valor} (vacío = ningún cambio). Las advertencias no
    bloqueantes se agregan a `avisos` si se la pasa."""
    cambios: dict[str, str] = {}
    if args.modo is not None:
        cambios[t.CLAVE_MODO] = args.modo
    if args.emergencia_modo is not None:
        cambios[t.CLAVE_EMERGENCIA_MODO] = args.emergencia_modo
    if args.emergencia_texto is not None:
        texto_emergencia, avisos_texto = validar_texto_emergencia(args.emergencia_texto, linea=args.linea_emergencia)
        cambios[t.CLAVE_EMERGENCIA_TEXTO] = texto_emergencia
        if avisos is not None:
            avisos.extend(avisos_texto)
    for valor, clave, etiqueta in (
        (args.linea, t.CLAVE_LINEA, "--linea"), (args.linea_emergencia, t.CLAVE_LINEA_EMERGENCIA, "--linea-emergencia"),
        (args.linea_ventas, t.CLAVE_LINEA_VENTAS, "--linea-ventas"), (args.nombre_negocio, t.CLAVE_NOMBRE_NEGOCIO, "--nombre-negocio"),
    ):
        if valor is not None:
            if len(valor.strip()) > LINEA_MAXIMA:
                raise ValueError(f"{etiqueta}: máximo {LINEA_MAXIMA} caracteres.")
            cambios[clave] = valor.strip()
    if args.categorias is not None:
        cats = [c for c in t._parsear_lista(args.categorias)]
        invalidas = [c for c in cats if c not in t.CATEGORIAS_ATC]
        if invalidas or not cats:
            raise ValueError(f"--categorias: válidas {', '.join(t.CATEGORIAS_ATC)}; recibido {args.categorias!r}.")
        cambios[t.CLAVE_CATEGORIAS] = ",".join(dict.fromkeys(cats))
    if args.texto is not None:
        cambios[t.CLAVE_TEXTO] = validar_texto(args.texto, "--texto")
    for par in args.texto_categoria:
        categoria, separador, texto = par.partition("=")
        categoria = categoria.strip().lower()
        if not separador or categoria not in t.CATEGORIAS_ATC:
            raise ValueError(f"--texto-categoria espera CATEGORIA=TEXTO con una categoría de {', '.join(t.CATEGORIAS_ATC)}.")
        cambios[t.CLAVE_TEXTO_CATEGORIA + categoria] = validar_texto(texto, f"--texto-categoria {categoria}")
    if args.resultado is not None:
        if not mem.resultado_triaje_valido(args.resultado):
            raise ValueError(f"--resultado: válidos {', '.join(mem.RESULTADOS_TRIAJE_PERMITIDOS)}; recibido {args.resultado!r}.")
        cambios[mem.CLAVE_TRIAJE_RESULTADO] = args.resultado.strip()
    if args.max_mensajes is not None:
        bajo, alto = MAX_MENSAJES_RANGO
        if not bajo <= args.max_mensajes <= alto:
            raise ValueError(f"--max-mensajes debe estar entre {bajo} y {alto}.")
        cambios[t.CLAVE_MAX_MENSAJES] = str(args.max_mensajes)
    if args.telefonos_excluidos is not None:
        numeros = [re.sub(r"\D", "", x) for x in args.telefonos_excluidos.replace(";", ",").split(",") if x.strip()]
        if any(len(n) < 8 for n in numeros):
            raise ValueError("--telefonos-excluidos: cada número debe tener al menos 8 dígitos.")
        cambios[t.CLAVE_TELEFONOS_EXCLUIDOS] = ",".join(numeros)
    if args.permitir_canal_pruebas is not None:
        cambios[t.CLAVE_PERMITIR_CANAL_PRUEBAS] = args.permitir_canal_pruebas
    if args.excluir_consulta_atc is not None:
        cambios[mem.CLAVE_METRICAS_EXCLUIR_ATC] = args.excluir_consulta_atc
    if args.excluir_desde is not None:
        cambios[mem.CLAVE_METRICAS_EXCLUIR_ATC_DESDE] = validar_fecha(args.excluir_desde)
    return cambios


async def estado(negocio_id: str) -> dict:
    """Lo configurado hoy (valores efectivos) y una vista previa del texto que recibiría el cliente."""
    async def v(clave, defecto=""):
        return (await mem.obtener_configuracion(clave, defecto, negocio_id=negocio_id) or "").strip()

    modo = t._parsear_modo(await v(t.CLAVE_MODO, "apagado"))
    emergencia = t._parsear_modo(await v(t.CLAVE_EMERGENCIA_MODO, "apagado"))
    plantilla_emergencia = await v(t.CLAVE_EMERGENCIA_TEXTO) or t.TEXTO_EMERGENCIA_POR_DEFECTO
    linea_emergencia = await v(t.CLAVE_LINEA_EMERGENCIA)
    emergencia_lista = not ("{linea_emergencia}" in plantilla_emergencia and not linea_emergencia)
    linea = await v(t.CLAVE_LINEA)
    plantilla = await v(t.CLAVE_TEXTO) or t.TEXTO_POR_DEFECTO
    negocio = await v(t.CLAVE_NOMBRE_NEGOCIO) or t.NOMBRE_NEGOCIO_POR_DEFECTO
    politica = await mem.obtener_politica_metricas(negocio_id)
    return {
        "negocio_id": negocio_id,
        "modo_configurado": modo,
        "modo_efectivo": t.MODO_SOMBRA if (modo == t.MODO_ACTIVO and not linea) else modo,
        "emergencia_modo_configurado": emergencia,
        "emergencia_modo_efectivo": t.MODO_SOMBRA if (emergencia == t.MODO_ACTIVO and not emergencia_lista) else emergencia,
        t.CLAVE_EMERGENCIA_TEXTO: await v(t.CLAVE_EMERGENCIA_TEXTO) or "(texto por defecto del módulo)",
        t.CLAVE_LINEA: linea or None,
        t.CLAVE_LINEA_EMERGENCIA: await v(t.CLAVE_LINEA_EMERGENCIA) or None,
        t.CLAVE_LINEA_VENTAS: await v(t.CLAVE_LINEA_VENTAS) or None,
        t.CLAVE_CATEGORIAS: await v(t.CLAVE_CATEGORIAS) or ",".join(t.CATEGORIAS_FASE_1),
        mem.CLAVE_TRIAJE_RESULTADO: await mem.obtener_resultado_triaje(negocio_id),
        t.CLAVE_MAX_MENSAJES: await v(t.CLAVE_MAX_MENSAJES) or str(t.MAX_MENSAJES_CLIENTE_POR_DEFECTO),
        t.CLAVE_NOMBRE_NEGOCIO: await v(t.CLAVE_NOMBRE_NEGOCIO) or f"(fallback: {t.NOMBRE_NEGOCIO_POR_DEFECTO})",
        t.CLAVE_TELEFONOS_EXCLUIDOS: await v(t.CLAVE_TELEFONOS_EXCLUIDOS) or None,
        t.CLAVE_PERMITIR_CANAL_PRUEBAS: await v(t.CLAVE_PERMITIR_CANAL_PRUEBAS) or "0",
        "metricas_excluir_consulta_atc": politica["excluir_consulta_atc"],
        "metricas_excluir_consulta_atc_desde": await v(mem.CLAVE_METRICAS_EXCLUIR_ATC_DESDE) or None,
        "vista_previa_texto": t.texto_para(plantilla, "Yasmin", linea or "<FALTA --linea>", negocio),
        "vista_previa_emergencia": t.texto_para(
            plantilla_emergencia, "Yasmin", linea or "", negocio, linea_emergencia or "<FALTA --linea-emergencia>",
        ),
    }


async def aplicar(negocio_id: str, cambios: dict[str, str]) -> dict:
    """Guarda los cambios (ya validados) y devuelve el estado resultante. `activo` exige una línea configurada."""
    if cambios.get(t.CLAVE_MODO) == t.MODO_ACTIVO:
        linea = cambios.get(t.CLAVE_LINEA)
        if linea is None:
            linea = await mem.obtener_configuracion(t.CLAVE_LINEA, "", negocio_id=negocio_id)
        if not (linea or "").strip():
            raise ValueError("No se puede activar sin la línea de atención: configura --linea primero (p. ej. \"614900, opción 5\").")
    if cambios.get(t.CLAVE_EMERGENCIA_MODO) == t.MODO_ACTIVO:
        plantilla = cambios[t.CLAVE_EMERGENCIA_TEXTO] if t.CLAVE_EMERGENCIA_TEXTO in cambios else await mem.obtener_configuracion(
            t.CLAVE_EMERGENCIA_TEXTO, "", negocio_id=negocio_id)
        linea_emergencia = cambios[t.CLAVE_LINEA_EMERGENCIA] if t.CLAVE_LINEA_EMERGENCIA in cambios else await mem.obtener_configuracion(
            t.CLAVE_LINEA_EMERGENCIA, "", negocio_id=negocio_id)
        if "{linea_emergencia}" in ((plantilla or "").strip() or t.TEXTO_EMERGENCIA_POR_DEFECTO) and not (linea_emergencia or "").strip():
            raise ValueError(
                "No se puede activar la emergencia sin la línea de emergencia: configura --linea-emergencia primero "
                "(p. ej. \"1808 (Emergencias 24/7)\")."
            )
    for clave, valor in cambios.items():
        await mem.guardar_configuracion(clave, valor, negocio_id=negocio_id)
    return await estado(negocio_id)


async def main(argv: list[str] | None = None) -> dict:
    args = _argumentos(argv)
    avisos: list[str] = []
    cambios = _cambios_desde(args, avisos)
    for aviso in avisos:
        print(aviso, file=sys.stderr)
    await mem.esperar_base_de_datos()
    negocio_id = resolver_negocio_id(args.negocio_id, await mem.listar_negocios())
    resultado = await aplicar(negocio_id, cambios) if cambios else await estado(negocio_id)
    print(json.dumps(resultado, ensure_ascii=False, indent=2))
    if resultado["modo_configurado"] == t.MODO_ACTIVO and resultado["modo_efectivo"] != t.MODO_ACTIVO:
        print("\nOjo: el modo activo sin línea de atención funciona como sombra.")
    if resultado["emergencia_modo_configurado"] == t.MODO_ACTIVO and resultado["emergencia_modo_efectivo"] != t.MODO_ACTIVO:
        print("\nOjo: la emergencia en modo activo sin línea de emergencia funciona como sombra.")
    return resultado


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass
    try:
        asyncio.run(main())
    except ValueError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(2)
    except Exception as e:  # noqa: BLE001
        print(f"ERROR: no se pudo configurar el triaje — {e}", file=sys.stderr)
        sys.exit(1)
