"""Cambia el nombre «Gaso+» por «Cálidda Hogar» en el texto de IDENTIDAD del prompt de Gabi (base de datos) — 2026-10-23.

El prompt real de Gabi vive en `IdentidadAgente.configuracion_negocio` (no en config/prompts.yaml, que es solo
respaldo). Este script reemplaza ÚNICAMENTE las frases de identidad (quién es Gabi y a quién representa) y deja
INTACTO el bloque «Uso del contexto…de Gaso+», porque `brain._reducir_texto_legacy_calidda` lo busca por su texto
exacto con «Gaso+» y falla si cambia (ver agent/brain.py). Por defecto NO escribe: muestra qué cambiaría.

Uso (la base sale de DATABASE_URL, como en los demás scripts):
    python scripts/actualizar_identidad_gabi.py                       # simulacro: muestra las frases a cambiar
    python scripts/actualizar_identidad_gabi.py --aplicar             # escribe y deja una fila de auditoría
    python scripts/actualizar_identidad_gabi.py --aplicar --revertir  # deshace el cambio (cambio inverso)
    añadir --negocio-id <id> si hay más de un negocio activo.

Cada frase se busca EXACTA y debe aparecer una sola vez; si alguna no está, no se escribe nada (todo o nada).
"""
import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent import memory as mem
from agent.memory import esperar_base_de_datos, listar_negocios
from scripts.configurar_plantilla_retomar import resolver_negocio_id

ACCION_AUDITORIA = "identidad_gabi_marca"

# (frase actual, frase nueva). Solo identidad; NO incluye «base de conocimiento de Gaso+» (bloque «Uso del contexto»).
REEMPLAZOS = (
    (
        "Eres Gabi, la asesora virtual del programa Gaso+ de Cálidda (Gas Natural de Lima y Callao).",
        "Eres Gabi, la asesora virtual de Cálidda Hogar (Gas Natural de Lima y Callao).",
    ),
    (
        "- Representas a Gaso+, el programa de financiamiento de gasodomésticos de Cálidda.",
        "- Representas a Cálidda Hogar, que ofrece gasodomésticos con financiamiento en el recibo de gas de Cálidda.",
    ),
    (
        "Gaso+ permite a clientes de Cálidda",     # en la base va SIN la sangría que tiene config/prompts.yaml
        "Cálidda Hogar permite a clientes de Cálidda",
    ),
)


def aplicar_reemplazos(texto: str, revertir: bool = False) -> tuple[str, list[str]]:
    """Devuelve (texto nuevo, problemas). Si hay problemas, el texto vuelve SIN cambios."""
    problemas = []
    nuevo = texto
    for actual, propuesta in REEMPLAZOS:
        origen, destino = (propuesta, actual) if revertir else (actual, propuesta)
        veces = nuevo.count(origen)
        if veces != 1:
            problemas.append(f"La frase aparece {veces} veces (se esperaba 1): {origen[:70]}…")
            continue
        nuevo = nuevo.replace(origen, destino)
    return (texto, problemas) if problemas else (nuevo, [])


def _argumentos(argv=None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Cambia «Gaso+» por «Cálidda Hogar» en la identidad de Gabi.")
    p.add_argument("--negocio-id", default=None)
    p.add_argument("--aplicar", action="store_true", help="Escribe el cambio (sin esto solo es simulacro).")
    p.add_argument("--revertir", action="store_true", help="Aplica el cambio inverso.")
    return p.parse_args(argv)


async def main(argv=None) -> dict:
    args = _argumentos(argv)
    await esperar_base_de_datos()
    negocio_id = resolver_negocio_id(args.negocio_id, await listar_negocios())
    identidad = await mem.obtener_identidad_agente(negocio_id)
    if identidad is None:
        print("Este negocio no tiene identidad de Gabi configurada.")
        return {"cambio": False, "motivo": "sin_identidad"}
    texto = identidad["configuracion_negocio"]
    nuevo, problemas = aplicar_reemplazos(texto, args.revertir)
    resultado = {"negocio_id": negocio_id, "revertir": args.revertir, "problemas": problemas, "cambio": False}
    for actual, propuesta in REEMPLAZOS:
        origen, destino = (propuesta, actual) if args.revertir else (actual, propuesta)
        print(f"- {origen.strip()}\n  → {destino.strip()}")
    if problemas:
        print("NO se escribió nada:\n  " + "\n  ".join(problemas))
        return resultado
    if not args.aplicar:
        print("Simulacro: no se escribió nada. Añade --aplicar para guardar.")
        return resultado
    await mem.crear_o_actualizar_identidad_agente(negocio_id, identidad["nombre"], identidad["tono"], nuevo)
    async with mem.async_session() as session:
        session.add(mem.RegistroAuditoria(
            accion=ACCION_AUDITORIA, actor="script", negocio_id=negocio_id, entidad_tipo="configuracion",
            payload={"revertir": args.revertir, "frases": [list(r) for r in REEMPLAZOS]},
        ))
        await session.commit()
    resultado["cambio"] = True
    print("Listo: identidad actualizada.")
    return resultado


if __name__ == "__main__":
    asyncio.run(main())
