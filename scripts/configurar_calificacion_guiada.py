"""Enciende, apaga o muestra la calificación guiada con botones — 2026-10-24.

Al ACTIVAR guarda la hora exacta (UTC) en `calificacion_guiada_activa_desde`: es el corte para comparar «antes» y «después»
(scripts/medir_calificacion_guiada.py). Reactivar después de apagar NO mueve el corte salvo que se pase `--nuevo-corte`.

Uso (la base sale de DATABASE_URL, como en los demás scripts):
    python scripts/configurar_calificacion_guiada.py                      # solo muestra lo configurado
    python scripts/configurar_calificacion_guiada.py --activar            # modo activo + marca de hora (si no había)
    python scripts/configurar_calificacion_guiada.py --activar --nuevo-corte
    python scripts/configurar_calificacion_guiada.py --desactivar         # vuelve a Gabi como siempre (interruptor de emergencia)
    python scripts/configurar_calificacion_guiada.py --telefono "614 9000, opción 5"
    añadir --negocio-id <id> si hay más de un negocio activo.
"""
import argparse
import asyncio
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent import calificacion_guiada as cg
from agent import memory as mem
from agent.memory import esperar_base_de_datos, listar_negocios
from scripts.configurar_plantilla_retomar import resolver_negocio_id


def _argumentos(argv=None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Configura la calificación guiada con botones.")
    p.add_argument("--negocio-id", default=None)
    grupo = p.add_mutually_exclusive_group()
    grupo.add_argument("--activar", action="store_true")
    grupo.add_argument("--desactivar", action="store_true")
    p.add_argument("--nuevo-corte", action="store_true", help="Con --activar, mueve la marca de hora a ahora.")
    p.add_argument("--telefono", default=None, help="Teléfono de la subunidad de Nuevos suministros que se le da al cliente sin gas.")
    return p.parse_args(argv)


async def main(argv=None) -> dict:
    args = _argumentos(argv)
    await esperar_base_de_datos()
    negocio_id = resolver_negocio_id(args.negocio_id, await listar_negocios())
    cambios: dict[str, str] = {}
    desde = (await mem.obtener_configuracion(cg.CLAVE_ACTIVA_DESDE, "", negocio_id=negocio_id) or "").strip()
    if args.activar:
        cambios[cg.CLAVE_MODO] = cg.MODO_ACTIVO
        if args.nuevo_corte or not desde:
            desde = datetime.utcnow().replace(microsecond=0).isoformat() + "Z"
            cambios[cg.CLAVE_ACTIVA_DESDE] = desde
    if args.desactivar:
        cambios[cg.CLAVE_MODO] = cg.MODO_APAGADO
    if args.telefono is not None:
        cambios[cg.CLAVE_TELEFONO_SUMINISTROS] = " ".join(args.telefono.split())
    for clave, valor in cambios.items():
        await mem.guardar_configuracion(clave, valor, negocio_id=negocio_id)
    estado = {
        "modo": await cg.obtener_modo(negocio_id),
        "activa_desde": desde or None,
        "telefono_suministros": await cg._telefono_suministros(negocio_id),
        "cambios": sorted(cambios),
    }
    print(estado)
    return estado


if __name__ == "__main__":
    asyncio.run(main())
