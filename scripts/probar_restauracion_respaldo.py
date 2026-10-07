"""Prueba de restauración del respaldo de Postgres: demuestra que el último dump del bucket SE
RESTAURA y trae datos coherentes. Un respaldo que nunca se restauró no es un respaldo.

Qué hace, en orden:
  1. Elige el respaldo MÁS RECIENTE bajo BACKUP_PREFIJO del bucket (o el indicado con --clave), lo
     descarga a un directorio temporal y comprueba que no esté vacío y que `pg_restore --list` lo lea.
  2. Crea una base TEMPORAL nueva en el MISMO servidor Postgres, llamada
     `restauracion_prueba_<AAAAMMDDHHMMSS>`. NUNCA toca la base viva: aborta si el nombre coincidiera.
  3. Restaura el dump ahí con `pg_restore --no-owner --no-privileges --exit-on-error`.
  4. Compara los conteos de las tablas clave entre la restauración y la base viva (la viva se abre en
     SOLO LECTURA) y comprueba que el último mensaje restaurado tenga menos de 36 h.
  5. SIEMPRE (incluso si algo falla) elimina la base temporal y los archivos temporales.
  6. Imprime un resumen en español y sale con código 1 si hay ALERTA o error.

Qué NO hace: no escribe en la base viva (conexión con default_transaction_read_only=on, solo SELECT),
no borra nada del bucket, no registra latido en `cron_ejecuciones` y no está en CRONES_ESPERADOS
(no es un Cron programado hoy; se corre a mano o como Cron mensual si algún día se decide).

Variables de entorno: las mismas que scripts/backup_postgres.py (DATABASE_URL, S3_ENDPOINT_URL,
S3_BUCKET, S3_ACCESS_KEY_ID, S3_SECRET_ACCESS_KEY, S3_REGION, BACKUP_PREFIJO). El usuario de
DATABASE_URL debe poder crear bases (CREATEDB); en Railway es el superusuario `postgres`.

Uso:
    python scripts/probar_restauracion_respaldo.py                  # prueba completa
    python scripts/probar_restauracion_respaldo.py --dry-run        # solo descarga y verifica el dump
    python scripts/probar_restauracion_respaldo.py --solo-listar    # muestra los respaldos disponibles
    python scripts/probar_restauracion_respaldo.py --clave backups/agentkit-20261007-080000.dump

Guía: docs/respaldos_postgres.md, sección "Prueba de restauración".
"""
import argparse
import asyncio
import os
import re
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import unquote, urlparse

import asyncpg

# Permite correr este script directo (python scripts/archivo.py) — mismo patrón que los demás scripts.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.backup_postgres import _cliente_s3, _sin_secretos, _verificar_volcado  # noqa: E402

PREFIJO_BASE_TEMPORAL = "restauracion_prueba_"
PATRON_BASE_TEMPORAL = re.compile(r"^restauracion_prueba_\d{14}$")
# Tablas que se comparan. Las "principales" exigen que lo restaurado sea >= 90 % de lo vivo; todas
# las que existan exigen no estar vacías si la viva no lo está.
TABLAS_PRINCIPALES = ["leads", "mensajes", "conversations", "opportunities", "eventos_lead"]
TABLAS_SECUNDARIAS = ["usuarios", "configuracion", "uso_mensajes_meta", "envios_meta"]
PORCENTAJE_MINIMO = 0.90
HORAS_MAX_ULTIMO_MENSAJE = 36
BASES_ADMIN = ["postgres", "template1"]
TIMEOUT_RESTAURACION_SEG = 1800


# ── Configuración ───────────────────────────────────────────────────────────

def _validar_config(solo_listar: bool) -> dict:
    requeridas = ["S3_ENDPOINT_URL", "S3_BUCKET", "S3_ACCESS_KEY_ID", "S3_SECRET_ACCESS_KEY"]
    if not solo_listar:
        requeridas.insert(0, "DATABASE_URL")
    faltantes = [v for v in requeridas if not os.environ.get(v)]
    if faltantes:
        raise SystemExit(f"Faltan variables de entorno: {', '.join(faltantes)}")
    config = {
        "endpoint_url": os.environ["S3_ENDPOINT_URL"],
        "bucket": os.environ["S3_BUCKET"],
        "access_key": os.environ["S3_ACCESS_KEY_ID"],
        "secret_key": os.environ["S3_SECRET_ACCESS_KEY"],
        "region": os.environ.get("S3_REGION", "auto"),
        "prefijo": os.environ.get("BACKUP_PREFIJO", "backups/"),
        "db": None,
    }
    if not solo_listar:
        url = os.environ["DATABASE_URL"]
        if not url.startswith(("postgresql://", "postgresql+asyncpg://", "postgres://")):
            raise SystemExit("DATABASE_URL no es Postgres: esta prueba solo funciona contra Postgres.")
        config["db"] = _parsear_url(url)
    return config


def _parsear_url(url: str) -> dict:
    """Separa la URL en partes sueltas: así host/usuario/base viajan como argumentos y la contraseña
    por PGPASSWORD (o por parámetro de asyncpg); la URL completa nunca se imprime ni se pasa a un comando."""
    p = urlparse(url.replace("postgresql+asyncpg://", "postgresql://", 1))
    base = unquote((p.path or "").lstrip("/"))
    if not p.hostname or not base:
        raise SystemExit("DATABASE_URL no trae host o nombre de base: no se puede continuar.")
    return {
        "host": p.hostname, "puerto": p.port or 5432,
        "usuario": unquote(p.username) if p.username else None,
        "clave": unquote(p.password) if p.password else None,
        "base": base,
    }


def _entorno_pg(db: dict) -> dict:
    entorno = dict(os.environ)
    if db["clave"] is not None:
        entorno["PGPASSWORD"] = db["clave"]
    return entorno


# ── Bucket ──────────────────────────────────────────────────────────────────

def _listar_respaldos(cliente, bucket: str, prefijo: str) -> list[dict]:
    """Respaldos `.dump` bajo el prefijo, del más reciente al más antiguo."""
    encontrados = []
    for pagina in cliente.get_paginator("list_objects_v2").paginate(Bucket=bucket, Prefix=prefijo):
        for obj in pagina.get("Contents", []):
            if obj["Key"].endswith(".dump"):
                encontrados.append({"clave": obj["Key"], "fecha": obj["LastModified"], "tamano": obj.get("Size", 0)})
    encontrados.sort(key=lambda o: (o["fecha"], o["clave"]), reverse=True)
    return encontrados


def _elegir_respaldo(respaldos: list[dict], clave: str | None) -> dict:
    if clave:
        for r in respaldos:
            if r["clave"] == clave:
                return r
        raise RuntimeError(f"No existe el respaldo indicado en el bucket: {clave}")
    if not respaldos:
        raise RuntimeError("El bucket no tiene ningún respaldo (.dump) bajo el prefijo configurado.")
    # Si el más reciente está vacío NO se salta al anterior: eso es justo lo que hay que avisar.
    return respaldos[0]


def _fmt_tamano(n: int) -> str:
    return f"{n / (1024 * 1024):.1f} MB" if n >= 1024 * 1024 else f"{n / 1024:.1f} KB"


def _imprimir_listado(respaldos: list[dict]) -> None:
    if not respaldos:
        print("No hay respaldos (.dump) bajo el prefijo configurado.")
        return
    print(f"{'Fecha (UTC)':<20} {'Tamaño':>10}  Clave")
    for r in respaldos:
        print(f"{r['fecha'].astimezone(timezone.utc).strftime('%Y-%m-%d %H:%M:%S'):<20} {_fmt_tamano(r['tamano']):>10}  {r['clave']}")


# ── Base temporal ───────────────────────────────────────────────────────────

def _nombre_temporal() -> str:
    return f"{PREFIJO_BASE_TEMPORAL}{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"


def _validar_nombre_temporal(nombre: str, base_viva: str) -> None:
    """Defensa doble contra tocar la base viva: el nombre debe tener la forma de la temporal Y no
    coincidir con la viva. Se llama antes de CREATE y antes de DROP."""
    if nombre.lower() == base_viva.lower():
        raise RuntimeError(f"ABORTADO: el nombre de la base temporal ({nombre}) coincide con la base viva. No se toca nada.")
    if not PATRON_BASE_TEMPORAL.match(nombre):
        raise RuntimeError(f"ABORTADO: '{nombre}' no tiene la forma de una base temporal de prueba. No se toca nada.")


def _ident(nombre: str) -> str:
    return '"' + nombre.replace('"', '""') + '"'


async def _conectar(db: dict, base: str, solo_lectura: bool = False):
    opciones = {"server_settings": {"default_transaction_read_only": "on"}} if solo_lectura else {}
    return await asyncpg.connect(
        host=db["host"], port=db["puerto"], user=db["usuario"], password=db["clave"],
        database=base, timeout=30, **opciones,
    )


async def _conectar_admin(db: dict, base_admin: str | None):
    """Conexión para CREATE/DROP DATABASE: a `postgres` (o `template1`, o la indicada), NUNCA a la viva."""
    candidatas = [base_admin] if base_admin else BASES_ADMIN
    ultimo_error = None
    for base in candidatas:
        if base.lower() == db["base"].lower():
            continue
        try:
            return await _conectar(db, base)
        except Exception as e:  # noqa: BLE001
            ultimo_error = _sin_secretos(str(e), db["clave"])
    raise RuntimeError(f"No se pudo abrir una conexión administrativa ({', '.join(candidatas)}): {ultimo_error}")


async def _crear_base(conn, nombre: str, base_viva: str) -> None:
    _validar_nombre_temporal(nombre, base_viva)
    await conn.execute(f"CREATE DATABASE {_ident(nombre)}")


async def _eliminar_base(conn, nombre: str, base_viva: str) -> None:
    _validar_nombre_temporal(nombre, base_viva)
    await conn.execute(f"DROP DATABASE IF EXISTS {_ident(nombre)} WITH (FORCE)")


def _restaurar(ruta: Path, db: dict, base_temporal: str) -> None:
    cmd = [
        "pg_restore", "--no-owner", "--no-privileges", "--exit-on-error",
        "-h", db["host"], "-p", str(db["puerto"]),
        *(["-U", db["usuario"]] if db["usuario"] else []),
        "-d", base_temporal, str(ruta),
    ]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=TIMEOUT_RESTAURACION_SEG, env=_entorno_pg(db))
    except FileNotFoundError:
        raise RuntimeError("No se encontró `pg_restore` en esta máquina/imagen. Instala postgresql-client.")
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"pg_restore superó {TIMEOUT_RESTAURACION_SEG // 60} min y se cortó.")
    if r.returncode != 0:
        detalle = " ".join(_sin_secretos((r.stderr or "").strip(), db["clave"]).split())[:500]
        raise RuntimeError(f"pg_restore falló (código {r.returncode}): {detalle}")


# ── Comparación (solo lectura sobre la viva) ───────────────────────────────

async def _contar(conn, tablas: list[str]) -> dict[str, int | None]:
    """Conteo por tabla; None si la tabla no existe. Solo SELECT. Los nombres vienen de listas fijas."""
    conteos = {}
    for t in tablas:
        existe = await conn.fetchval("SELECT to_regclass($1)", f"public.{t}")
        conteos[t] = None if existe is None else int(await conn.fetchval(f"SELECT count(*) FROM public.{_ident(t)}"))
    return conteos


async def _ultimo_mensaje(conn) -> datetime | None:
    existe = await conn.fetchval("SELECT to_regclass('public.mensajes')")
    if existe is None:
        return None
    return await conn.fetchval("SELECT max(timestamp) FROM public.mensajes")


def _evaluar(restaurado: dict, vivo: dict, ultimo_mensaje: datetime | None, ahora: datetime | None = None) -> tuple[list[dict], list[str]]:
    """Devuelve (filas de la tabla, motivos de ALERTA). Sin motivos = OK."""
    ahora = ahora or datetime.now(timezone.utc).replace(tzinfo=None)  # UTC sin zona, como guarda `mensajes.timestamp`
    filas, alertas = [], []
    for t in TABLAS_PRINCIPALES + TABLAS_SECUNDARIAS:
        r, v = restaurado.get(t), vivo.get(t)
        if r is None and v is None:
            estado = "no existe"
        elif r is None:
            estado = "ALERTA"
            alertas.append(f"{t}: la tabla existe en la base viva pero NO en la restauración.")
        elif v is None:
            estado = "OK (solo en el respaldo)"
        elif v > 0 and r == 0:
            estado = "ALERTA"
            alertas.append(f"{t}: la restauración está vacía pero la base viva tiene {v} filas.")
        elif t in TABLAS_PRINCIPALES and v > 0 and r < v * PORCENTAJE_MINIMO:
            estado = "ALERTA"
            alertas.append(f"{t}: la restauración tiene {r} filas, menos del {PORCENTAJE_MINIMO:.0%} de las {v} de la base viva.")
        else:
            estado = "OK"
        filas.append({"tabla": t, "restaurado": r, "vivo": v, "estado": estado})
    if ultimo_mensaje is None:
        if (vivo.get("mensajes") or 0) > 0:
            alertas.append("mensajes: no hay ningún mensaje restaurado, así que no se puede comprobar la antigüedad.")
    else:
        edad = ahora - ultimo_mensaje.replace(tzinfo=None)
        if edad > timedelta(hours=HORAS_MAX_ULTIMO_MENSAJE):
            alertas.append(
                f"El último mensaje restaurado tiene {edad.total_seconds() / 3600:.0f} h de antigüedad (máximo {HORAS_MAX_ULTIMO_MENSAJE} h): "
                "el respaldo parece desactualizado."
            )
    return filas, alertas


def _imprimir_tabla(filas: list[dict]) -> None:
    f = lambda n: "—" if n is None else f"{n:,}"  # noqa: E731
    print(f"{'Tabla':<22} {'Restaurado':>12} {'Base viva':>12}  Estado")
    for x in filas:
        print(f"{x['tabla']:<22} {f(x['restaurado']):>12} {f(x['vivo']):>12}  {x['estado']}")


# ── Flujo principal ─────────────────────────────────────────────────────────

async def ejecutar(args: argparse.Namespace) -> int:
    """Devuelve el código de salida: 0 todo bien, 1 ALERTA o error."""
    t0 = time.monotonic()
    try:
        config = _validar_config(args.solo_listar)
        cliente = _cliente_s3(config)
        if args.solo_listar:
            _imprimir_listado(_listar_respaldos(cliente, config["bucket"], config["prefijo"]))
            return 0
        prefijo = args.clave or config["prefijo"]
        respaldo = _elegir_respaldo(_listar_respaldos(cliente, config["bucket"], prefijo), args.clave)
    except SystemExit as e:
        print(f"ERROR: {e.code}", file=sys.stderr)
        return 1
    except Exception as e:  # noqa: BLE001
        print(f"ERROR: {_sin_secretos(str(e))}", file=sys.stderr)
        return 1

    db = config["db"]
    base_temporal = _nombre_temporal()
    base_creada = False
    conn_admin = None
    veredicto_alertas: list[str] = []
    error: str | None = None
    tiempos: dict[str, float] = {}
    filas: list[dict] = []
    objetos = 0

    try:
        with tempfile.TemporaryDirectory(prefix="restauracion_prueba_") as tmp:
            try:
                ruta = Path(tmp) / "respaldo.dump"
                print(f"Respaldo elegido: {respaldo['clave']} ({_fmt_tamano(respaldo['tamano'])}, {respaldo['fecha'].astimezone(timezone.utc):%Y-%m-%d %H:%M} UTC)")
                if respaldo["tamano"] == 0:
                    raise RuntimeError("El respaldo más reciente está vacío (0 bytes): el Cron de respaldo está generando archivos inservibles.")
                t = time.monotonic()
                cliente.download_file(config["bucket"], respaldo["clave"], str(ruta))
                tiempos["descarga"] = time.monotonic() - t
                objetos = _verificar_volcado(ruta)
                print(f"Descargado y verificado con pg_restore --list: {objetos} objeto(s) en el índice.")

                if args.dry_run:
                    print("--dry-run: no se crea ninguna base ni se restaura nada.")
                else:
                    _validar_nombre_temporal(base_temporal, db["base"])
                    conn_admin = await _conectar_admin(db, args.base_admin)
                    base_creada = True   # antes del CREATE: si falla a medias, el finally igual intenta borrarla
                    await _crear_base(conn_admin, base_temporal, db["base"])
                    print(f"Base temporal creada: {base_temporal}")

                    t = time.monotonic()
                    _restaurar(ruta, db, base_temporal)
                    tiempos["restauración"] = time.monotonic() - t
                    print(f"Restauración terminada en {tiempos['restauración']:.0f} s.")

                    t = time.monotonic()
                    todas = TABLAS_PRINCIPALES + TABLAS_SECUNDARIAS
                    conn_r = await _conectar(db, base_temporal, solo_lectura=True)
                    try:
                        restaurado = await _contar(conn_r, todas)
                        ultimo = await _ultimo_mensaje(conn_r)
                    finally:
                        await conn_r.close()
                    conn_v = await _conectar(db, db["base"], solo_lectura=True)
                    try:
                        vivo = await _contar(conn_v, todas)
                    finally:
                        await conn_v.close()
                    tiempos["comparación"] = time.monotonic() - t
                    filas, veredicto_alertas = _evaluar(restaurado, vivo, ultimo)
                    print()
                    _imprimir_tabla(filas)
                    print(f"Último mensaje restaurado: {ultimo:%Y-%m-%d %H:%M} UTC" if ultimo else "Último mensaje restaurado: (ninguno)")
            except Exception as e:  # noqa: BLE001
                error = " ".join(_sin_secretos(str(e), db["clave"]).split())
    finally:
        # (e) Limpieza SIEMPRE: el directorio temporal ya se borró al salir del `with`; falta la base.
        try:
            if base_creada:
                if conn_admin is None:
                    conn_admin = await _conectar_admin(db, args.base_admin)
                await _eliminar_base(conn_admin, base_temporal, db["base"])
                print(f"Base temporal {base_temporal} eliminada.")
            print("Archivos temporales eliminados.")
        except Exception as e:  # noqa: BLE001
            detalle = " ".join(_sin_secretos(str(e), db["clave"]).split())
            print(f"AVISO: no se pudo eliminar la base temporal {base_temporal}: {detalle}. Elimínala a mano (DROP DATABASE).", file=sys.stderr)
            veredicto_alertas.append(f"No se pudo eliminar la base temporal {base_temporal}; hay que borrarla a mano.")
        finally:
            if conn_admin is not None:
                try:
                    await conn_admin.close()
                except Exception:  # noqa: BLE001
                    pass

    total = time.monotonic() - t0
    print()
    print("=== Resumen de la prueba de restauración ===")
    print(f"Respaldo: {respaldo['clave']} ({_fmt_tamano(respaldo['tamano'])})")
    print("Tiempos: " + ", ".join(f"{k} {v:.0f} s" for k, v in tiempos.items()) + (", " if tiempos else "") + f"total {total:.0f} s")
    if error:
        print(f"VEREDICTO: ERROR — {error}", file=sys.stderr)
        for a in veredicto_alertas:
            print(f"  - {a}", file=sys.stderr)
        return 1
    if args.dry_run:
        print(f"VEREDICTO: OK (dry-run) — el respaldo se descarga, no está vacío y su índice se lee ({objetos} objetos).")
        return 0
    if veredicto_alertas:
        print("VEREDICTO: ALERTA")
        for a in veredicto_alertas:
            print(f"  - {a}")
        return 1
    print("VEREDICTO: OK — el respaldo se restauró y sus datos son coherentes con la base viva.")
    return 0


def _parsear_args(argv: list[str] | None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Prueba de restauración del respaldo de Postgres (no destructiva).")
    p.add_argument("--clave", help="Clave del respaldo en el bucket (por defecto, el más reciente).")
    p.add_argument("--dry-run", action="store_true", help="Solo descarga y verifica con pg_restore --list; no crea ninguna base.")
    p.add_argument("--solo-listar", action="store_true", help="Muestra los respaldos disponibles con tamaño y fecha.")
    p.add_argument("--base-admin", help="Base a la que conectarse para crear/eliminar la temporal (por defecto postgres, luego template1).")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    return asyncio.run(ejecutar(_parsear_args(argv)))


if __name__ == "__main__":
    sys.exit(main())
