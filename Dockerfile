FROM python:3.11-slim
WORKDIR /app
# ffmpeg: convierte las notas de voz grabadas en el navegador (WebM/Opus,
# lo único que produce MediaRecorder de forma confiable) a OGG/Opus, el
# único formato de audio que acepta la API de WhatsApp para notas de voz.
# postgresql-client-18: da los binarios pg_dump/pg_restore que usa scripts/backup_postgres.py
# (ADR-0001) — misma imagen se reutiliza para el servicio de Cron Schedule de Railway que corre
# ese script, no solo para el proceso web. Se instala desde el repositorio oficial de Postgres
# (PGDG) porque la base de Railway es la versión 18 (imagen postgres-ssl:18) y pg_dump se niega
# a respaldar un servidor MÁS NUEVO que él ("server version mismatch"): el cliente de Debian es
# más viejo. Un pg_dump 18 sí respalda servidores anteriores. Si algún día cambia la versión de
# la base, cambia el número aquí (docs/respaldos_postgres.md).
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg curl ca-certificates     && install -d /usr/share/postgresql-common/pgdg     && curl -fsSL -o /usr/share/postgresql-common/pgdg/apt.postgresql.org.asc https://www.postgresql.org/media/keys/ACCC4CF8.asc     && . /etc/os-release     && echo "deb [signed-by=/usr/share/postgresql-common/pgdg/apt.postgresql.org.asc] https://apt.postgresql.org/pub/repos/apt ${VERSION_CODENAME}-pgdg main" > /etc/apt/sources.list.d/pgdg.list     && apt-get update && apt-get install -y --no-install-recommends postgresql-client-18     && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
EXPOSE 8000
CMD uvicorn agent.main:app --host 0.0.0.0 --port ${PORT:-8000}
