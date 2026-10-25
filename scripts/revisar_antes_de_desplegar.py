"""Revisa QUÉ se va a desplegar antes de hacer el push — SOLO LECTURA (2026-10-25).

Varias sesiones trabajan en la misma carpeta del repositorio y cambian de rama, así que antes de empujar a producción conviene ver, con
datos y no de memoria: qué commits salen (y de quién), si la rama está atrasada respecto de lo desplegado (el push sería rechazado), si
alguno trae una migración de base de datos, y si hay más de una cabeza de migraciones (eso rompe el arranque).

Uso (desde la carpeta del repositorio o de un worktree):
    python scripts/revisar_antes_de_desplegar.py                    # contra deploy/main (hace git fetch antes)
    python scripts/revisar_antes_de_desplegar.py --remoto origin/main --sin-fetch

Código de salida: 0 = nada que objetar; 1 = hay algo que mirar (atrasada, divergida o varias cabezas de migración).
"""
import argparse
import re
import subprocess
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
RUTA_MIGRACIONES = "migrations/versions/"


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=RAIZ, capture_output=True, text=True, encoding="utf-8", errors="replace").stdout.strip()


def commits_entre(base: str, cabeza: str = "HEAD") -> list[dict]:
    """Commits que están en `cabeza` y no en `base` (los que saldrían), del más viejo al más nuevo."""
    salida = _git("log", "--reverse", "--format=%h\t%an\t%ad\t%s", "--date=short", f"{base}..{cabeza}")
    filas = []
    for linea in salida.splitlines():
        partes = linea.split("\t", 3)
        if len(partes) == 4:
            filas.append({"sha": partes[0], "autor": partes[1], "fecha": partes[2], "mensaje": partes[3]})
    return filas


def migraciones_de(commits: list[dict]) -> list[dict]:
    """Archivos de migración añadidos o modificados por cada commit."""
    encontradas = []
    for c in commits:
        archivos = _git("show", "--name-status", "--format=", c["sha"]).splitlines()
        for linea in archivos:
            estado, _, ruta = linea.partition("\t")
            if ruta.startswith(RUTA_MIGRACIONES) and ruta.endswith(".py"):
                encontradas.append({"commit": c["sha"], "estado": estado, "archivo": ruta})
    return encontradas


def cabezas_de_migracion(carpeta: Path | None = None) -> list[str]:
    """Revisiones que nadie tiene como `down_revision` (las «cabezas»). Debe haber UNA."""
    carpeta = carpeta or RAIZ / RUTA_MIGRACIONES
    revisiones, hijas = set(), set()
    for archivo in carpeta.glob("*.py"):
        texto = archivo.read_text(encoding="utf-8", errors="replace")
        rev = re.search(r"^revision(?::\s*str)?\s*=\s*['\"]([0-9a-zA-Z_]+)['\"]", texto, re.M)
        if not rev:
            continue
        revisiones.add(rev.group(1))
        abajo = re.search(r"^down_revision[^=]*=\s*(.+)$", texto, re.M)
        if abajo:
            hijas.update(re.findall(r"['\"]([0-9a-zA-Z_]+)['\"]", abajo.group(1)))
    return sorted(revisiones - hijas)


def diagnostico(adelante: list[dict], atras: list[dict], migraciones: list[dict], cabezas: list[str]) -> list[str]:
    """Lo que hay que mirar antes de empujar (vacío = nada que objetar)."""
    avisos = []
    if atras:
        avisos.append(
            f"La rama está ATRASADA {len(atras)} commit(s) respecto de lo desplegado: el push sería rechazado. "
            "Arma la versión sobre el remoto (git worktree + cherry-pick) en vez de forzar."
        )
    if len(cabezas) != 1:
        avisos.append(f"Hay {len(cabezas)} cabezas de migración ({', '.join(cabezas) or 'ninguna'}): el arranque fallaría.")
    autores = {c["autor"] for c in adelante}
    if len(autores) > 1:
        avisos.append("Los commits que saldrían son de más de un autor: confirma que todos deben desplegarse.")
    return avisos


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Revisa qué se desplegaría (solo lectura).")
    p.add_argument("--remoto", default="deploy/main")
    p.add_argument("--sin-fetch", action="store_true")
    args = p.parse_args(argv)
    if not args.sin_fetch:
        _git("fetch", args.remoto.split("/")[0])
    adelante, atras = commits_entre(args.remoto), commits_entre("HEAD", args.remoto)
    migraciones, cabezas = migraciones_de(adelante), cabezas_de_migracion()
    print(f"Saldrían {len(adelante)} commit(s) a {args.remoto}:")
    for c in adelante:
        print(f"  {c['sha']} {c['fecha']} {c['autor']}: {c['mensaje'][:100]}")
    print(f"Migraciones nuevas entre ellos: {len(migraciones)}")
    for m in migraciones:
        print(f"  {m['estado']} {m['archivo']} (commit {m['commit']})")
    print(f"Cabeza(s) de migración actual(es): {', '.join(cabezas) or 'ninguna'}")
    avisos = diagnostico(adelante, atras, migraciones, cabezas)
    for a in avisos:
        print(f"AVISO: {a}")
    if not avisos:
        print("Nada que objetar.")
    return 1 if avisos else 0


if __name__ == "__main__":
    sys.exit(main())
