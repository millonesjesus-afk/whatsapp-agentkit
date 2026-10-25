"""Muestra o cambia el modo del contexto del anuncio de Gabi (mejora M1) — 2026-10-25.

Modos de `gabi_contexto_anuncio_modo`:
  · apagado  no hace nada.
  · sombra   (por defecto) calcula el bloque y deja el log `contexto_anuncio`, pero NO se lo entrega a Gabi.
  · activo   le entrega a Gabi el anuncio por el que entró el cliente y la regla de no citar precios sin respaldo del catálogo;
             sigue dejando el log `contexto_anuncio` para medir (tiene_anuncio, hay_promo, precio_no_disponible).
Solo actúa cuando Claude responde (con la IA caída no hay registros).

Uso (la base sale de DATABASE_URL, como en los demás scripts):
    python scripts/configurar_contexto_anuncio.py                  # solo muestra el modo
    python scripts/configurar_contexto_anuncio.py --modo activo
    python scripts/configurar_contexto_anuncio.py --modo sombra    # volver atrás
    añadir --negocio-id <id> si hay más de un negocio activo.
"""
import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent import contexto_anuncio as ca
from agent import memory as mem
from agent.memory import esperar_base_de_datos, listar_negocios
from scripts.configurar_plantilla_retomar import resolver_negocio_id


async def main(argv=None) -> dict:
    p = argparse.ArgumentParser(description="Modo del contexto del anuncio de Gabi.")
    p.add_argument("--negocio-id", default=None)
    p.add_argument("--modo", choices=ca.MODOS, default=None)
    args = p.parse_args(argv)
    await esperar_base_de_datos()
    negocio_id = resolver_negocio_id(args.negocio_id, await listar_negocios())
    anterior = ca.normalizar_modo(await mem.obtener_configuracion(ca.CLAVE_MODO, ca.MODO_POR_DEFECTO, negocio_id=negocio_id))
    if args.modo is not None:
        await mem.guardar_configuracion(ca.CLAVE_MODO, args.modo, negocio_id=negocio_id)
    ahora = ca.normalizar_modo(await mem.obtener_configuracion(ca.CLAVE_MODO, ca.MODO_POR_DEFECTO, negocio_id=negocio_id))
    estado = {"modo_anterior": anterior, "modo": ahora, "cambio": ahora != anterior}
    print(estado)
    return estado


if __name__ == "__main__":
    asyncio.run(main())
