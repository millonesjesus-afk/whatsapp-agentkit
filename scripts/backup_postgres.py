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

Uso local (prueba manual, no corre en Railway automáticamente):
    python scripts/backup_postgres.py
"""
import os
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse

import boto3
from botocore.client import Config as BotoConfig

BACKUP_RETENCION_DIAS = int(os.environ.get("BACKUP_RETENCION_DIAS", "30"))
BACKUP_PREFIJO = os.environ.get("BACKUP_PREFIJO", "backups/")
INTENTOS_CONEXION = 10
PAUSA_CONEXION_SEG = 2


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


def _ejecutar_pg_dump(database_url: str, destino: Path) -> None:
    # --format=custom: comprimido y restaurable con pg_restore (soporta
    # restauración parcial/paralela) — más flexible que un dump plano.
    # Reintenta si la conexión aún no está lista: en un contenedor recién
    # arrancado la red PRIVADA de Railway tarda un instante y pg_dump falla
    # con "Connection refused" (2026-09-24, mismo problema que los otros Cron).
    for intento in range(1, INTENTOS_CONEXION + 1):
        resultado = subprocess.run(
            ["pg_dump", database_url, "--format=custom", "--file", str(destino)],
            capture_output=True, text=True, timeout=600,
        )
        if resultado.returncode == 0:
            return
        sin_conexion = "could not connect" in resultado.stderr or "Connection refused" in resultado.stderr
        if not sin_conexion or intento == INTENTOS_CONEXION:
            raise RuntimeError(f"pg_dump falló (código {resultado.returncode}): {resultado.stderr}")
        time.sleep(PAUSA_CONEXION_SEG)


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


def _purgar_antiguos(cliente, bucket: str, retencion_dias: int) -> int:
    """Borra del bucket los backups (bajo BACKUP_PREFIJO) más viejos que
    retencion_dias. Retorna cuántos se borraron."""
    limite = datetime.now(timezone.utc) - timedelta(days=retencion_dias)
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

    with tempfile.TemporaryDirectory() as tmp:
        ruta_local = Path(tmp) / "backup.dump"
        print(f"Ejecutando pg_dump hacia {ruta_local}...")
        _ejecutar_pg_dump(config["database_url"], ruta_local)
        tamano_mb = ruta_local.stat().st_size / (1024 * 1024)
        print(f"Dump generado: {tamano_mb:.1f} MB")

        cliente = _cliente_s3(config)
        print(f"Subiendo a s3://{config['bucket']}/{clave_remota}...")
        _subir(cliente, config["bucket"], ruta_local, clave_remota)
        print("Subida OK.")

        borrados = _purgar_antiguos(cliente, config["bucket"], BACKUP_RETENCION_DIAS)
        if borrados:
            print(f"Purgados {borrados} backup(s) con más de {BACKUP_RETENCION_DIAS} días.")

    print("Backup completado correctamente.")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"ERROR: backup falló — {e}", file=sys.stderr)
        sys.exit(1)
