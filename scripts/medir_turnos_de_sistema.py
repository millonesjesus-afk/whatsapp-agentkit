"""Mide cuántas respuestas de IA podrían ser texto fijo del sistema (sin modelo) — 2026-11-11.

Toma los eventos `mix_haiku` ya guardados (cada uno es un turno que respondió el modelo principal) y clasifica el ÚLTIMO mensaje del cliente en tipos
cerrados: cortesía ("ok", "gracias"), no interesado, retiro de datos / "no me escriban", saludo, u otro. Calcula qué porcentaje de las respuestas
cae en cada tipo y cuánto se ahorraría si fueran texto fijo. Solo lectura, sin IA, costo cero.

Privacidad: se imprimen conteos y, como ejemplos, mensajes cortos con números largos y correos tapados (igual que mix_haiku_muestra.py). Nunca
teléfonos, conversaciones ni nombres de contacto.

Uso (la base sale de DATABASE_URL):
    python scripts/medir_turnos_de_sistema.py                    # conteos por tipo y ahorro estimado
    python scripts/medir_turnos_de_sistema.py --ejemplos 3       # además, hasta 3 ejemplos por tipo (cliente y respuesta de Gabi)
    python scripts/medir_turnos_de_sistema.py --frecuentes 15    # los mensajes cortos más repetidos que quedaron en «otro» (para descubrir tipos)
    python scripts/medir_turnos_de_sistema.py --desde 2026-11-04
    añadir --negocio-id <id> si hay más de un negocio activo.
"""
import argparse
import asyncio
import re
import sys
import unicodedata
from collections import Counter
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent.memory import esperar_base_de_datos, listar_negocios
from scripts.configurar_plantilla_retomar import resolver_negocio_id
from scripts.mix_haiku_muestra import cargar, enmascarar

# Costo medido por respuesta de Sonnet 5.5 en la sombra (2-nov): referencia del ahorro si ese turno pasa a ser texto fijo.
COSTO_SONNET_55_USD = 0.01046
CONVERSACIONES_PROYECTADAS = 2000
RESPUESTAS_POR_CONVERSACION = 3.3        # 0.0375 USD por conversación / 0.0114 USD por respuesta (auditoría 26-oct)

_ACUSE = {
    "ok", "okey", "oka", "okay", "okk", "listo", "lista", "vale", "perfecto", "perfecta", "gracias", "graciass", "muchas", "ya", "entendido", "entendi",
    "bien", "dale", "genial", "excelente", "bueno", "buenisimo", "claro", "esta", "de", "acuerdo", "mil", "por", "todo", "su", "tu", "atencion", "amable",
    "saludos", "un", "buen", "dia", "tarde", "noche", "igualmente", "igual", "hasta", "luego", "pronto", "estare", "atento", "atenta", "espero", "aguardo",
    "la", "el", "informacion", "ayuda", "respuesta", "tiempo", "muy", "buena", "buenas", "okis", "okok",
}
_SALUDO = {"hola", "holaa", "holi", "buenas", "buenos", "dias", "tardes", "noches", "buen", "dia", "tarde", "noche", "hello", "hi", "que", "tal", "como", "estas", "esta"}
_RE_NO_INTERESADO = re.compile(
    r"\bno (?:me )?interes\w*|\bno estoy interesad\w+|\bya no (?:quiero|necesito|me interesa|estoy interesad\w+)|\bno (?:quiero|necesito)\b|"
    r"\bno gracias\b|\bya (?:compre|adquiri|tengo uno)\b"
)
_RE_RETIRO_DATOS = re.compile(
    r"\b(?:quit\w+|borr\w+|elimin\w+|retir\w+|saqu\w+) (?:mi|mis|mi numero|mis datos|mi contacto|el numero)\b|"
    r"\bno me (?:escriban|escribas|molesten|molestes|llamen|llames|contacten|contactes|sigan|siga)\b|\bdej\w+ de (?:escribir|molestar|contactar|llamar|enviar)\w*|"
    r"\bbase de datos\b|\bspam\b|\bmis datos\b|\bdatos personales\b"
)


def normalizar(texto: str | None) -> str:
    sin_tildes = "".join(c for c in unicodedata.normalize("NFD", (texto or "").lower()) if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9ñ ]+", " ", sin_tildes)).strip()


def clasificar(texto: str | None) -> str:
    """Tipo del mensaje del cliente: `retiro_datos`, `no_interesado`, `cortesia`, `saludo` u `otro`. PURA. El orden importa: lo más sensible primero."""
    n = normalizar(texto)
    if not n:
        return "vacio"
    if _RE_RETIRO_DATOS.search(n):
        return "retiro_datos"
    palabras = n.split()
    if len(palabras) <= 12 and _RE_NO_INTERESADO.search(n):
        return "no_interesado"
    if len(palabras) <= 6 and all(p in _ACUSE for p in palabras) and any(p in _ACUSE - _SALUDO or p in {"ok", "gracias"} for p in palabras):
        return "cortesia"
    if len(palabras) <= 4 and all(p in _SALUDO for p in palabras):
        return "saludo"
    return "otro"


def resumir(eventos: list[dict]) -> dict:
    """Conteos por tipo (todos los turnos y solo los no delicados) y ahorro estimado si cada tipo fuera texto fijo. PURA."""
    total = len(eventos)
    por_tipo: Counter = Counter()
    no_delicados: Counter = Counter()
    for e in eventos:
        tipo = clasificar(e.get("ultimo_cliente"))
        por_tipo[tipo] += 1
        if not (e["payload"].get("delicado")):
            no_delicados[tipo] += 1
    respuestas_mes = CONVERSACIONES_PROYECTADAS * RESPUESTAS_POR_CONVERSACION
    salida = {"respuestas": total, "tipos": {}}
    for tipo, n in por_tipo.most_common():
        fraccion = n / total if total else 0.0
        salida["tipos"][tipo] = {
            "n": n, "pct": round(100 * fraccion, 1), "de_ellos_no_delicados": no_delicados[tipo],
            "ahorro_mensual_usd": round(fraccion * respuestas_mes * COSTO_SONNET_55_USD, 1) if tipo != "otro" and tipo != "vacio" else 0.0,
        }
    return salida


async def main(argv=None) -> dict:
    p = argparse.ArgumentParser(description="Mide cuántas respuestas de IA podrían ser texto fijo del sistema.")
    p.add_argument("--negocio-id", default=None)
    p.add_argument("--desde", default=None, help="Fecha ISO desde la que medir (UTC).")
    p.add_argument("--ejemplos", type=int, default=0)
    p.add_argument("--frecuentes", type=int, default=0)
    args = p.parse_args(argv)
    await esperar_base_de_datos()
    negocio_id = resolver_negocio_id(args.negocio_id, await listar_negocios())
    desde = datetime.fromisoformat(args.desde.replace("Z", "+00:00")).replace(tzinfo=None) if args.desde else None
    eventos = await cargar(negocio_id, desde)
    resumen = resumir(eventos)
    print(f"Respuestas medidas: {resumen['respuestas']}")
    for tipo, d in resumen["tipos"].items():
        print(f"  {tipo:<14} {d['n']:>4}  ({d['pct']:>5}%)  no delicados: {d['de_ellos_no_delicados']:>3}  ahorro/mes si fuera texto fijo: US$ {d['ahorro_mensual_usd']}")
    if args.ejemplos:
        for tipo in resumen["tipos"]:
            if tipo in ("otro", "vacio"):
                continue
            mostrados = 0
            for e in eventos:
                if mostrados >= args.ejemplos:
                    break
                if clasificar(e.get("ultimo_cliente")) == tipo:
                    mostrados += 1
                    print(f"\n[{tipo}] CLIENTE: {enmascarar(e.get('ultimo_cliente'))}\n[{tipo}] GABI   : {(e['payload'].get('respuesta_real') or '').strip()[:300]}")
    if args.frecuentes:
        cortos = Counter(
            normalizar(enmascarar(e.get("ultimo_cliente"))) for e in eventos
            if clasificar(e.get("ultimo_cliente")) == "otro" and len(normalizar(e.get("ultimo_cliente")).split()) <= 4
        )
        print("\nMensajes cortos más repetidos en «otro»:")
        for texto, n in cortos.most_common(args.frecuentes):
            print(f"  {n:>3}  {texto}")
    return resumen


if __name__ == "__main__":
    asyncio.run(main())
