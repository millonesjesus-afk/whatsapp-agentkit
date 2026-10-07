"""Configura (o muestra) la plantilla "retomar consulta" que los asesores mandan desde el chat — 2026-10-06.

Cuando la ventana de 24 h de WhatsApp cerró, Meta solo deja mandar una plantilla aprobada. La plantilla se
crea y se aprueba en Meta (WhatsApp Manager → Plantillas); este script le dice al sistema CÓMO se llama
allí, en qué idioma está y cuál es su texto (para la vista previa del panel). Ver agent/plantilla_retomar.py.

No manda ningún mensaje. No es un Cron: no se envuelve con `ejecutar_cron`.

Uso (la base sale de DATABASE_URL, como en los demás scripts):
    python scripts/configurar_plantilla_retomar.py --negocio-id <id>                      # solo muestra lo configurado
    python scripts/configurar_plantilla_retomar.py --negocio-id <id> --nombre retomar_consulta --idioma es
    python scripts/configurar_plantilla_retomar.py --negocio-id <id> --nombre retomar_consulta --idioma es \
        --cuerpo "Hola {{1}}, soy {{2}} de Gaso+. Vi que consultaste por {{3}} y quiero ayudarte a continuar. ¿Seguimos por aquí?"
    python scripts/configurar_plantilla_retomar.py --negocio-id <id> --desactivar          # el panel vuelve a avisar "sin plantilla"

El nombre y el idioma deben ser EXACTAMENTE los que Meta muestra como aprobados; si no coinciden, Meta
rechaza el envío. `--cuerpo` solo hace falta si el texto aprobado difiere del propuesto.
"""
import argparse
import asyncio
import json
import sys
from pathlib import Path

# Permite correr este script directo (python scripts/archivo.py) — mismo patrón que los demás scripts.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent import plantilla_retomar
from agent.memory import esperar_base_de_datos, listar_negocios


def _argumentos(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Configura la plantilla de 'retomar consulta' de los asesores.")
    parser.add_argument("--negocio-id", default=None, help="Id del negocio al que se aplica. Si se omite y existe un solo negocio activo, se usa ese.")
    parser.add_argument("--nombre", default=None, help="Nombre de la plantilla tal como la aprobó Meta (ej. retomar_consulta).")
    parser.add_argument("--idioma", default=plantilla_retomar.IDIOMA_POR_DEFECTO, help="Código de idioma aprobado en Meta (por defecto es).")
    parser.add_argument("--cuerpo", default=None, help="Texto aprobado del cuerpo, con {{1}} cliente, {{2}} asesor, {{3}} interés.")
    parser.add_argument("--desactivar", action="store_true", help="Quita el nombre: sin plantilla configurada no se puede enviar.")
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


async def main(argv: list[str] | None = None) -> dict:
    args = _argumentos(argv)
    await esperar_base_de_datos()
    args.negocio_id = resolver_negocio_id(args.negocio_id, await listar_negocios())
    if args.desactivar:
        resultado = await plantilla_retomar.configurar_plantilla(args.negocio_id, "", args.idioma, args.cuerpo)
    elif args.nombre is not None:
        resultado = await plantilla_retomar.configurar_plantilla(args.negocio_id, args.nombre, args.idioma, args.cuerpo)
    else:
        resultado = await plantilla_retomar.obtener_plantilla(args.negocio_id)
    print(json.dumps(resultado, ensure_ascii=False, indent=2))
    if not resultado["disponible"]:
        print("\nOjo: todavía NO hay una plantilla disponible; el panel no ofrecerá el envío.")
    return resultado


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except ValueError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(2)
    except Exception as e:
        print(f"ERROR: no se pudo configurar la plantilla — {e}", file=sys.stderr)
        sys.exit(1)
