"""Configura (o muestra) el experimento «solo clic» — 2026-10-16 (Fases A y B: medición y SOMBRA).

El experimento (agent/solo_clic.py) viene APAGADO. Este script fija sus claves de configuración por negocio, con validación,
sin tocar código ni desplegar. No envía mensajes, no llama a nadie y no es un Cron (la sombra corre dentro del Cron ya
existente `crear_tareas_llamada`, cada 15 min).

Uso (la base sale de DATABASE_URL; sin ninguna opción solo MUESTRA lo configurado):
    python scripts/configurar_solo_clic.py --negocio-id <id>
    # ENCENDER LA SOMBRA (registra brazo y acción hipotética; NO envía ni llama a nadie; con ella encendida «Para llamar» deja
    # de crear tareas para los leads de «solo clic»):
    python scripts/configurar_solo_clic.py --negocio-id <id> --modo sombra
    # Apagar (vuelve a TODO como antes):
    python scripts/configurar_solo_clic.py --negocio-id <id> --modo apagado

`--modo activo` está RESERVADO (no existe la Fase C, el envío real): se acepta pero opera como sombra y el log lo avisa.

Otras opciones: --epoca v1 · --pct-c 40 --pct-t1 20 --pct-t2 40 (deben sumar 100) · --cohorte-min 20 · --toque-min 20 ·
--oferta-min 60 · --ventana-max-horas 22 · --max-intentos 2 (solo la usará la Fase C).
`--pct-t3` NO existe: la llamada directa (T3) está BLOQUEADA hasta después de las pruebas y de una aprobación legal.
"""
import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent import solo_clic
from agent.memory import esperar_base_de_datos, listar_negocios
from scripts.configurar_triaje_atc import resolver_negocio_id


def _argumentos(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Configura el experimento «solo clic» (sombra).")
    p.add_argument("--negocio-id", default=None, help="Id del negocio. Si se omite y hay un solo negocio activo, se usa ese.")
    p.add_argument("--modo", choices=solo_clic.MODOS_VALIDOS, default=None, help="apagado (default) | sombra | activo (reservado: opera como sombra).")
    p.add_argument("--epoca", default=None)
    p.add_argument("--pct-c", type=float, default=None)
    p.add_argument("--pct-t1", type=float, default=None)
    p.add_argument("--pct-t2", type=float, default=None)
    p.add_argument("--cohorte-min", type=int, default=None)
    p.add_argument("--toque-min", type=int, default=None)
    p.add_argument("--oferta-min", type=int, default=None)
    p.add_argument("--ventana-max-horas", type=float, default=None)
    p.add_argument("--max-intentos", type=int, default=None)
    return p.parse_args(argv)


def cuerpo_desde(args) -> dict:
    cuerpo: dict = {}
    for campo, valor in (
        ("modo", args.modo), ("epoca", args.epoca), ("pct_c", args.pct_c), ("pct_t1", args.pct_t1), ("pct_t2", args.pct_t2),
        ("cohorte_min", args.cohorte_min), ("toque_min", args.toque_min), ("oferta_min", args.oferta_min),
        ("ventana_max_horas", args.ventana_max_horas), ("max_intentos", args.max_intentos),
    ):
        if valor is not None:
            cuerpo[campo] = valor
    return cuerpo


async def main(argv: list[str] | None = None) -> dict:
    args = _argumentos(argv)
    cuerpo = cuerpo_desde(args)
    await esperar_base_de_datos()
    negocio_id = resolver_negocio_id(args.negocio_id, await listar_negocios())
    # `guardar_cambios` valida TODO antes de escribir nada (todo o nada); los porcentajes se validan contra lo ya guardado.
    estado = await (solo_clic.guardar_cambios(negocio_id, cuerpo) if cuerpo else solo_clic.estado_configuracion(negocio_id))
    print(json.dumps({"negocio_id": negocio_id, **estado}, ensure_ascii=False, indent=2))
    if estado["modo"] == solo_clic.MODO_ACTIVO:
        print("\nOjo: `activo` está RESERVADO (no existe la Fase C): el experimento opera como SOMBRA. No se envía ni se llama a nadie.")
    return estado


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
        print(f"ERROR: no se pudo configurar «solo clic» — {e}", file=sys.stderr)
        sys.exit(1)
