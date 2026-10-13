"""Siembra los feriados nacionales de Perú en el calendario de negocio y fija la vigencia de las métricas hábiles — 2026-10-12.

Calendario de negocio, Fase 1 (ver docs/contrato_calendario_negocio.md y agent/calendario_negocio.py). Un feriado
sembrado hace que el sistema CIERRE ese día: la asignación automática no asigna, el reloj de rotación 30+30 no avanza,
la atención no se vuelve atrasada y Gabi avisa cuándo vuelven los asesores. Solo siembra FERIADOS (nunca días no
laborables ni puentes: esos los decide el administrador en el panel).

Sin opciones solo MUESTRA qué insertaría (no escribe nada). Con --aplicar escribe. Es idempotente: una fecha que ya
tiene un día especial no se toca, y un feriado que el administrador quitó antes no se vuelve a crear (--restaurar lo
vuelve a crear). No es un Cron: no se envuelve con `ejecutar_cron`.

Uso (la base sale de DATABASE_URL, como en los demás scripts):
    python scripts/sembrar_calendario.py                                   # muestra qué insertaría (todos los años disponibles)
    python scripts/sembrar_calendario.py --anio 2026 --aplicar             # siembra 2026
    python scripts/sembrar_calendario.py --anio 2027 --aplicar             # 2027: lista CALCULADA, no verificada; revisar contra El Peruano
    python scripts/sembrar_calendario.py --negocio-id <id> --anio 2026 --aplicar
    python scripts/sembrar_calendario.py --fijar-habil-desde hoy           # métricas hábiles rigen desde hoy (día de Lima)
    python scripts/sembrar_calendario.py --fijar-habil-desde 2026-10-13
    python scripts/sembrar_calendario.py --fijar-habil-desde borrar        # vuelve a los umbrales de siempre

Sin --negocio-id se usa el ÚNICO negocio activo (con varios negocios, hay que indicarlo). `--fijar-habil-desde` guarda
la clave `calendario_habil_desde` del negocio: desde esa fecha (y solo desde entonces) «atrasada» = 2 h hábiles y
«urgente» = 4 h hábiles en vez de las reglas de siempre (urgente = 8 h de reloj). Sin la clave nada de eso cambia.
"""
import argparse
import asyncio
import sys
from pathlib import Path

# Permite correr este script directo (python scripts/archivo.py) — mismo patrón que los demás scripts.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent import calendario_peru
from agent.memory import (
    esperar_base_de_datos, fijar_calendario_habil_desde, hoy_en_lima, listar_negocios, obtener_calendario_habil_desde,
    sembrar_calendario,
)

AUTOR = "script:sembrar_calendario"


def _argumentos(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Siembra los feriados de Perú y fija la vigencia de las métricas hábiles.")
    parser.add_argument("--negocio-id", default=None, help="Id del negocio. Si se omite y existe un solo negocio activo, se usa ese.")
    parser.add_argument("--anio", type=int, default=None, help=f"Año a sembrar ({', '.join(str(a) for a in calendario_peru.ANIOS_DISPONIBLES)}). Sin él, todos.")
    parser.add_argument("--aplicar", action="store_true", help="Escribe de verdad. Sin esto solo muestra qué insertaría.")
    parser.add_argument("--restaurar", action="store_true", help="También vuelve a crear los feriados que el administrador quitó.")
    parser.add_argument("--fijar-habil-desde", default=None, metavar="AAAA-MM-DD|hoy|borrar",
                        help="Fija (o borra) la fecha desde la que rigen las métricas hábiles de atención atrasada/urgente.")
    return parser.parse_args(argv)


def resolver_negocio_id(negocio_id: str | None, negocios: list[dict]) -> str:
    """El id indicado, o el del ÚNICO negocio activo si no se indicó. Con varios negocios exige --negocio-id."""
    if negocio_id:
        return negocio_id
    activos = [n for n in negocios if n.get("activo", True)]
    if len(activos) == 1:
        return activos[0]["id"]
    disponibles = ", ".join(f"{n.get('id')} ({n.get('nombre') or n.get('codigo') or '?'})" for n in activos) or "ninguno"
    raise ValueError(f"Hay {len(activos)} negocios activos: indica --negocio-id. Disponibles: {disponibles}.")


def _fecha_habil_desde(valor: str):
    if valor.strip().lower() == "borrar":
        return None
    if valor.strip().lower() == "hoy":
        return hoy_en_lima()
    from datetime import date
    try:
        return date.fromisoformat(valor.strip())
    except ValueError:
        raise ValueError("--fijar-habil-desde debe ser AAAA-MM-DD, «hoy» o «borrar».")


async def main(argv: list[str] | None = None) -> dict:
    args = _argumentos(argv)
    await esperar_base_de_datos()
    negocio_id = resolver_negocio_id(args.negocio_id, await listar_negocios())
    anios = [args.anio] if args.anio is not None else list(calendario_peru.ANIOS_DISPONIBLES)
    resultado: dict = {"negocio_id": negocio_id, "aplicado": args.aplicar, "anios": {}}

    # 1) Feriados. Sin --aplicar solo se simula. (Con --fijar-habil-desde y sin --anio solo se toca esa clave.)
    if args.fijar_habil_desde is None or args.anio is not None:
        for anio in anios:
            r = await sembrar_calendario(
                negocio_id, anio, autor=AUTOR, restaurar_eliminados=args.restaurar, simular=not args.aplicar,
            )
            resultado["anios"][anio] = r
            verbo = "insertó" if args.aplicar else "insertaría"
            print(f"{anio}: {verbo} {len(r['insertados'])} feriado(s); ya existían {len(r['ya_existian'])}; "
                  f"omitidos por haberlos quitado el administrador: {len(r['omitidos_por_eliminados'])}.")
            for fecha in r["insertados"]:
                print(f"    + {fecha.isoformat()}")
            if r["nota"]:
                print(f"    OJO: {r['nota']}")
        if not args.aplicar:
            print("\n(Simulación: no se escribió nada. Agrega --aplicar para sembrar.)")

    # 2) Vigencia de las métricas hábiles.
    if args.fijar_habil_desde is not None:
        fecha = _fecha_habil_desde(args.fijar_habil_desde)
        cambio = await fijar_calendario_habil_desde(negocio_id, fecha, autor=AUTOR)   # una opción explícita: escribe siempre
        resultado["calendario_habil_desde"] = cambio
        print(f"calendario_habil_desde: {cambio['antes']} -> {cambio['despues']}")
    else:
        vigente = await obtener_calendario_habil_desde(negocio_id)
        resultado["calendario_habil_desde"] = {"vigente": vigente.isoformat() if vigente else None}
        print(f"calendario_habil_desde vigente: {vigente.isoformat() if vigente else 'no fijada (se usan los umbrales de siempre)'}")
    return resultado


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except ValueError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(2)
    except Exception as e:
        print(f"ERROR: no se pudo sembrar el calendario — {e}", file=sys.stderr)
        sys.exit(1)
