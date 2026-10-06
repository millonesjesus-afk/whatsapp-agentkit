"""Backup de la base de datos de producción vía pg_dump, subido a
almacenamiento S3-compatible — implementa ADR-0001: el plan de Railway
contratado no incluye backups nativos ni Point-in-Time Recovery
("Backups and point-in-time recovery (PITR) are only available for
customers on the Pro plan", confirmado en el dashboard 2026-07-28).

Pensado para correr como un Cron Schedule de Railway, en un servicio
aparte del proceso web principal (mismo repo/imagen, comando de arranque
distinto) — no dentro de main.py.

Variables de entorno requeridas:
    DATABASE_URL        — el mismo connection string que usa la app (debe
                           ser Postgres; el script se niega a correr sobre
                           SQLite, que no tiene sentido respaldar así)
    S3_ENDPOINT_URL      — endpoint del proveedor S3-compatible (AWS S3,
                           Cloudflare R2, Backblaze B2, etc.)
    S3_BUCKET            — bucket destino
    S3_ACCESS_KEY_ID     — credencial de acceso
    S3_SECRET_ACCESS_KEY — credencial secreta
    S3_REGION            — opcional, algunos proveedores la ignoran

Variables opcionales:
    BACKUP_RETENCION_DIAS — cuántos días de backups conservar en el bucket
                             antes de purgar los más viejos (default: 30)
    BACKUP_PREFIJO         — prefijo/carpeta dentro del bucket (default: "backups/")

Endurecido el 2026-10-05:
  - La contraseña de Postgres viaja a pg_dump por la variable de entorno PGPASSWORD, no dentro
    del argumento (los argumentos se ven en la lista de procesos y en los mensajes de error).
  - El volcado se verifica con `pg_restore --list` ANTES de subirlo: si está vacío o corrupto el
    script falla con un mensaje claro y NO sube nada.
  - Si pg_dump falla por "server version mismatch" (el cliente de Postgres de la imagen es más
    viejo que el servidor) el mensaje explica qué hacer; ver docs/respaldos_postgres.md.
  - La purga de respaldos viejos solo corre si en el bucket hay al menos un respaldo bueno de las
    últimas 48 horas: un bucket con respaldos viejos y ninguno nuevo nunca se vacía.
  - Imprime un resumen con el tamaño y la duración.
  - Deja latido en `cron_ejecuciones` (ver scripts/_cron.py) para que Inicio avise si falla.

Guía para el usuario (bucket, credenciales, Cron, restauración de prueba):
    docs/respaldos_postgres.md

Uso local (prueba manual, no corre en Railway automáticamente):
    python scripts/backup_postgres.py
"""
import asyncio
import os
import re
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote, unquote, urlparse, urlunparse

import boto3
from botocore.client import Config as BotoConfig

# Permite correr este script directo (python scripts/archivo.py) sin que Python se queje de no
# encontrar los paquetes `agent` y `scripts` — mismo patrón que los demás scripts.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts._cron import ejecutar_cron  # latido: ver scripts/_cron.py

BACKUP_RETENCION_DIAS = int(os.environ.get("BACKUP_RETENCION_DIAS", "30"))
BACKUP_PREFIJO = os.environ.get("BACKUP_PREFIJO", "backups/")
INTENTOS_CONEXION = 10
PAUSA_CONEXION_SEG = 2
# Un respaldo "bueno reciente": subido y verificado en las últimas 48 h. Solo con uno así en el
# bucket se permite purgar los viejos; y nunca se purga nada más nuevo que esto.
HORAS_RESPALDO_RECIENTE = 48

MENSAJE_VERSION_DISTINTA = (
    "pg_dump falló porque la versión del cliente de Postgres de esta imagen es MÁS VIEJA que la del servidor "
    "(\"server version mismatch\"). Hay que alinear la versión: instalar en la imagen un postgresql-client de la "
    "misma versión mayor que tu base (o mayor). El Dockerfile instala `postgresql-client` sin fijar versión, "
    "así que trae la que da Debian por defecto. Qué hacer, paso a paso: docs/respaldos_postgres.md, sección "
    "\"Si falla por versión distinta\". Detalle de pg_dump: {detalle}"
)


def _validar_config() -> dict:
    requeridas = [
        "DATABASE_URL", "S3_ENDPOINT_URL", "S3_BUCKET",
        "S3_ACCESS_KEY_ID", "S3_SECRET_ACCESS_KEY",
    ]
    faltantes = [v for v in requeridas if not os.environ.get(v)]
    if faltantes:
        raise SystemExit(f"Faltan variables de entorno: {', '.join(faltantes)}")

    database_url = os.environ["DATABASE_URL"]
    if not database_url.startswith(("postgresql://", "postgresql+asyncpg://", "postgres://")):
        raise SystemExit(
            "DATABASE_URL no es Postgres — este script solo respalda Postgres, "
            "no tiene sentido correrlo contra SQLite local."
        )
    return {
        "database_url": database_url.replace("postgresql+asyncpg://", "postgresql://", 1),
        "endpoint_url": os.environ["S3_ENDPOINT_URL"],
        "bucket": os.environ["S3_BUCKET"],
        "access_key": os.environ["S3_ACCESS_KEY_ID"],
        "secret_key": os.environ["S3_SECRET_ACCESS_KEY"],
        "region": os.environ.get("S3_REGION", "auto"),
    }


def _nombre_archivo() -> str:
    ahora = datetime.now(timezone.utc)
    return f"{BACKUP_PREFIJO}agentkit-{ahora.strftime('%Y%m%d-%H%M%S')}.dump"


def _separar_clave(database_url: str) -> tuple[str, str | None]:
    """Devuelve (la URL sin la contraseña, la contraseña ya decodificada o None). La contraseña se
    le pasa a pg_dump por PGPASSWORD; así no aparece en los argumentos del proceso."""
    partes = urlparse(database_url)
    if partes.password is None:
        return database_url, None
    host = partes.hostname or ""
    if ":" in host:   # IPv6
        host = f"[{host}]"
    netloc = host + (f":{partes.port}" if partes.port else "")
    if partes.username:
        netloc = f"{quote(unquote(partes.username), safe='')}@{netloc}"
    return urlunparse(partes._replace(netloc=netloc)), unquote(partes.password)


def _sin_secretos(texto: str, clave: str | None = None) -> str:
    """Quita del texto la contraseña de la base (y cualquier clave embebida en una URL)."""
    if clave and len(clave) >= 4:
        texto = texto.replace(clave, "***")
    return re.sub(r"([A-Za-z][A-Za-z0-9+.\-]*://)[^\s/@:]+:[^\s/@]+@", r"\1***@", texto)


def _ejecutar_pg_dump(database_url: str, destino: Path) -> None:
    # --format=custom: comprimido y restaurable con pg_restore (soporta
    # restauración parcial/paralela) — más flexible que un dump plano.
    # Reintenta si la conexión aún no está lista: en un contenedor recién
    # arrancado la red PRIVADA de Railway tarda un instante y pg_dump falla
    # con "Connection refused" (2026-09-24, mismo problema que los otros Cron).
    url_sin_clave, clave = _separar_clave(database_url)
    entorno = dict(os.environ)
    if clave is not None:
        entorno["PGPASSWORD"] = clave
    for intento in range(1, INTENTOS_CONEXION + 1):
        resultado = subprocess.run(
            ["pg_dump", url_sin_clave, "--format=custom", "--file", str(destino)],
            capture_output=True, text=True, timeout=600, env=entorno,
        )
        if resultado.returncode == 0:
            return
        detalle = _sin_secretos((resultado.stderr or "").strip(), clave)
        if "server version mismatch" in detalle:
            raise RuntimeError(MENSAJE_VERSION_DISTINTA.format(detalle=" ".join(detalle.split())[:400]))
        sin_conexion = "could not connect" in detalle or "Connection refused" in detalle
        if not sin_conexion or intento == INTENTOS_CONEXION:
            raise RuntimeError(f"pg_dump falló (código {resultado.returncode}): {detalle}")
        time.sleep(PAUSA_CONEXION_SEG)


def _verificar_volcado(ruta: Path) -> int:
    """Comprueba que el volcado sirve ANTES de subirlo: no está vacío y `pg_restore --list` lo lee y
    encuentra objetos dentro. Devuelve cuántos objetos tiene; lanza RuntimeError si no sirve."""
    if not ruta.exists() or ruta.stat().st_size == 0:
        raise RuntimeError("El volcado quedó vacío (0 bytes): no se sube nada. Revisa los permisos y la conexión a la base.")
    try:
        resultado = subprocess.run(
            ["pg_restore", "--list", str(ruta)], capture_output=True, text=True, timeout=300,
        )
    except FileNotFoundError:
        raise RuntimeError(
            "No se encontró `pg_restore` en la imagen: no se puede verificar el volcado, así que no se sube. "
            "Instala postgresql-client."
        )
    if resultado.returncode != 0:
        raise RuntimeError(
            "El volcado está corrupto o incompleto (pg_restore --list no pudo leerlo): no se sube nada. "
            f"Detalle: {' '.join((resultado.stderr or '').split())[:300]}"
        )
    objetos = [linea for linea in resultado.stdout.splitlines() if linea.strip() and not linea.lstrip().startswith(";")]
    if not objetos:
        raise RuntimeError("El volcado no contiene ningún objeto (ni tablas ni datos): no se sube nada.")
    return len(objetos)


def _cliente_s3(config: dict):
    return boto3.client(
        "s3",
        endpoint_url=config["endpoint_url"],
        aws_access_key_id=config["access_key"],
        aws_secret_access_key=config["secret_key"],
        region_name=config["region"],
        config=BotoConfig(signature_version="s3v4"),
    )


def _subir(cliente, bucket: str, ruta_local: Path, clave_remota: str) -> None:
    cliente.upload_file(str(ruta_local), bucket, clave_remota)


def _hay_respaldo_reciente(cliente, bucket: str) -> bool:
    """True si el bucket (bajo BACKUP_PREFIJO) tiene al menos un respaldo no vacío de las últimas
    HORAS_RESPALDO_RECIENTE horas."""
    limite = datetime.now(timezone.utc) - timedelta(hours=HORAS_RESPALDO_RECIENTE)
    paginador = cliente.get_paginator("list_objects_v2")
    for pagina in paginador.paginate(Bucket=bucket, Prefix=BACKUP_PREFIJO):
        for obj in pagina.get("Contents", []):
            if obj["LastModified"] >= limite and obj.get("Size", 1) > 0:
                return True
    return False


def _purgar_antiguos(cliente, bucket: str, retencion_dias: int) -> int:
    """Borra del bucket los backups (bajo BACKUP_PREFIJO) más viejos que
    retencion_dias (mínimo 2: nunca se borra un respaldo de las últimas 48 h).
    Retorna cuántos se borraron."""
    limite = datetime.now(timezone.utc) - timedelta(days=max(retencion_dias, 2))
    paginador = cliente.get_paginator("list_objects_v2")
    a_borrar = []
    for pagina in paginador.paginate(Bucket=bucket, Prefix=BACKUP_PREFIJO):
        for obj in pagina.get("Contents", []):
            if obj["LastModified"] < limite:
                a_borrar.append({"Key": obj["Key"]})
    if a_borrar:
        # delete_objects acepta hasta 1000 claves por llamada
        for i in range(0, len(a_borrar), 1000):
            cliente.delete_objects(Bucket=bucket, Delete={"Objects": a_borrar[i:i + 1000]})
    return len(a_borrar)


def main() -> None:
    config = _validar_config()
    clave_remota = _nombre_archivo()
    t0 = time.monotonic()

    with tempfile.TemporaryDirectory() as tmp:
        ruta_local = Path(tmp) / "backup.dump"
        print(f"Ejecutando pg_dump hacia {ruta_local}...")
        _ejecutar_pg_dump(config["database_url"], ruta_local)
        t_dump = time.monotonic()
        objetos = _verificar_volcado(ruta_local)
        tamano_mb = ruta_local.stat().st_size / (1024 * 1024)
        print(f"Dump generado y verificado: {tamano_mb:.1f} MB, {objetos} objeto(s) en el índice.")

        cliente = _cliente_s3(config)
        print(f"Subiendo a s3://{config['bucket']}/{clave_remota}...")
        _subir(cliente, config["bucket"], ruta_local, clave_remota)
        t_subida = time.monotonic()
        print("Subida OK.")

        if _hay_respaldo_reciente(cliente, config["bucket"]):
            borrados = _purgar_antiguos(cliente, config["bucket"], BACKUP_RETENCION_DIAS)
            if borrados:
                print(f"Purgados {borrados} backup(s) con más de {BACKUP_RETENCION_DIAS} días.")
        else:
            print(
                f"AVISO: no se purgó nada — el bucket no muestra ningún respaldo de las últimas {HORAS_RESPALDO_RECIENTE} h "
                "(ni el que se acaba de subir). Revisa el bucket antes de que se acumulen respaldos viejos."
            )

    total = time.monotonic() - t0
    print(
        f"Backup completado correctamente: {clave_remota} — {tamano_mb:.1f} MB, "
        f"pg_dump {t_dump - t0:.0f} s, subida {t_subida - t_dump:.0f} s, total {total:.0f} s."
    )


if __name__ == "__main__":
    try:
        asyncio.run(ejecutar_cron("backup_postgres", main, 1440))
    except KeyboardInterrupt:
        raise
    except BaseException as e:
        # SystemExit trae el mensaje en `code` (p. ej. "Faltan variables de entorno: ..."): se muestra
        # igual que antes y el exit sigue siendo 1.
        detalle = e.code if isinstance(e, SystemExit) else e
        print(f"ERROR: backup falló — {detalle}", file=sys.stderr)
        sys.exit(1)
