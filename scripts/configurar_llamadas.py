"""Configura (o muestra) el estado "Para llamar" — 2026-10-09.

El módulo (agent/llamadas.py) viene APAGADO. Este script fija sus claves de configuración por negocio, con la misma
validación que el panel, sin tocar código ni desplegar. No manda mensajes ni es un Cron.

Uso (la base sale de DATABASE_URL; sin ninguna opción solo MUESTRA lo configurado):
    python scripts/configurar_llamadas.py --negocio-id <id>
    # MODO SOMBRA (solo registra tareas para medir; nadie las ve ni se llama; nada cambia en la operación):
    python scripts/configurar_llamadas.py --negocio-id <id> --activo 1 --modo sombra
    # Apagar todo:
    python scripts/configurar_llamadas.py --negocio-id <id> --activo 0
    # Modo activo: exige la aceptación de responsabilidad (sin ella funciona como sombra). La aceptación queda con el
    # usuario que se indica en --como y en el registro de auditoría:
    python scripts/configurar_llamadas.py --negocio-id <id> --modo activo --aceptar-responsabilidad v1 --como admin
    python scripts/configurar_llamadas.py --negocio-id <id> --revocar-responsabilidad --como admin

Otras opciones: --horas-silencio 4 · --puntaje-minimo 4 · --exploracion-pct 0 · --holdout-pct 30 · --max-intentos 3 ·
--sla-horas 2 · --vida-max-dias 3 · --oferta-activa 0|1 · --respuesta-haiku 0|1 · --oferta-texto "…{nombre}…{producto}…" ("" vuelve al texto por defecto).
"""
import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent import llamadas
from agent.memory import esperar_base_de_datos, listar_negocios
from scripts.configurar_triaje_atc import resolver_negocio_id


def _argumentos(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Configura el estado «Para llamar» (tareas de llamada).")
    p.add_argument("--negocio-id", default=None, help="Id del negocio. Si se omite y hay un solo negocio activo, se usa ese.")
    p.add_argument("--activo", choices=("0", "1"), default=None, help="1 enciende el módulo (llamadas_gabi_activo); 0 lo apaga.")
    p.add_argument("--modo", choices=llamadas.MODOS_CONFIGURABLES, default=None, help="sombra (default) | activo.")
    p.add_argument("--horas-silencio", type=float, default=None)
    p.add_argument("--puntaje-minimo", type=int, default=None)
    p.add_argument("--exploracion-pct", type=float, default=None)
    p.add_argument("--holdout-pct", type=float, default=None)
    p.add_argument("--max-intentos", type=int, default=None)
    p.add_argument("--sla-horas", type=float, default=None, help="llamadas_sla_horas_habiles")
    p.add_argument("--vida-max-dias", type=float, default=None)
    p.add_argument("--oferta-activa", choices=("0", "1"), default=None)
    p.add_argument("--oferta-texto", default=None)
    p.add_argument("--respuesta-haiku", choices=("0", "1"), default=None, help="1 deja que Haiku interprete las respuestas AMBIGUAS a la oferta (llamadas_respuesta_haiku).")
    p.add_argument("--aceptar-responsabilidad", metavar="VERSION_TEXTO", default=None, help=f"Acepta el texto de responsabilidad (versión actual: {llamadas.VERSION_TEXTO_RESPONSABILIDAD}).")
    p.add_argument("--revocar-responsabilidad", action="store_true", help="Revoca la aceptación: apaga el modo activo y cancela las tareas abiertas.")
    p.add_argument("--como", default=None, help="Usuario que figura en la aceptación/revocación (obligatorio con ellas).")
    return p.parse_args(argv)


def cuerpo_desde(args) -> dict:
    """Los argumentos como el cuerpo del POST de /dashboard/configuracion/llamadas.json (así la validación es UNA sola)."""
    cuerpo: dict = {}
    if args.activo is not None:
        cuerpo["gabi_activo"] = args.activo == "1"
    if args.oferta_activa is not None:
        cuerpo["oferta_activa"] = args.oferta_activa == "1"
    if args.respuesta_haiku is not None:
        cuerpo["respuesta_haiku"] = args.respuesta_haiku == "1"
    if args.modo is not None:
        cuerpo["modo"] = args.modo
    for campo, valor in (
        ("horas_silencio", args.horas_silencio), ("puntaje_minimo", args.puntaje_minimo), ("exploracion_pct", args.exploracion_pct),
        ("holdout_pct", args.holdout_pct), ("max_intentos", args.max_intentos), ("sla_horas_habiles", args.sla_horas),
        ("vida_max_dias", args.vida_max_dias),
    ):
        if valor is not None:
            cuerpo[campo] = valor
    if args.oferta_texto is not None:
        cuerpo["oferta_texto"] = args.oferta_texto
    if args.aceptar_responsabilidad is not None:
        cuerpo["aceptar_responsabilidad"] = True
        cuerpo["version_texto"] = args.aceptar_responsabilidad
    if args.revocar_responsabilidad:
        cuerpo["revocar_responsabilidad"] = True
    if (args.aceptar_responsabilidad is not None or args.revocar_responsabilidad) and not (args.como or "").strip():
        raise ValueError("Para aceptar o revocar la responsabilidad indica quién lo hace con --como <usuario>.")
    return cuerpo


async def main(argv: list[str] | None = None) -> dict:
    args = _argumentos(argv)
    cuerpo = cuerpo_desde(args)
    llamadas.validar_cambios(cuerpo)      # falla ANTES de tocar la base si algo es inválido
    await esperar_base_de_datos()
    negocio_id = resolver_negocio_id(args.negocio_id, await listar_negocios())
    if cuerpo:
        estado = await llamadas.guardar_cambios(negocio_id, (args.como or "script").strip(), cuerpo)
    else:
        estado = await llamadas.estado_configuracion(negocio_id)
    print(json.dumps({"negocio_id": negocio_id, **estado}, ensure_ascii=False, indent=2))
    if estado["modo"] == llamadas.MODO_ACTIVO and estado["modo_efectivo"] != llamadas.MODO_ACTIVO:
        print("\nOjo: el modo activo sin la aceptación de responsabilidad vigente (o con el módulo apagado) NO está en juego.")
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
        print(f"ERROR: no se pudo configurar «Para llamar» — {e}", file=sys.stderr)
        sys.exit(1)
