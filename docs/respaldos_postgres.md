# Respaldos de Postgres (Gaso+ / Maiek AI)

Guía para dejar funcionando el respaldo diario de la base de datos de producción. El script ya existe
(`scripts/backup_postgres.py`, ADR-0001); lo que falta son cosas que solo puedes hacer tú: crear el
bucket, crear el servicio Cron en Railway y probar una restauración.

Estado a 2026-10-05: **el respaldo no está programado**. Hasta que completes los pasos 1 a 4 no hay
ninguna copia de la base fuera de Railway.

## Qué hace el script

1. Hace `pg_dump` (formato custom, comprimido) de la base indicada en `DATABASE_URL`. La contraseña viaja por la
   variable `PGPASSWORD`, no dentro de los argumentos del comando.
2. **Verifica el volcado** con `pg_restore --list`. Si está vacío o corrupto, falla con un mensaje claro y no sube nada.
3. Lo sube al bucket como `backups/agentkit-AAAAMMDD-HHMMSS.dump`.
4. Borra los respaldos con más de `BACKUP_RETENCION_DIAS` días (30 por defecto), **pero solo si el bucket tiene al menos un
   respaldo bueno de las últimas 48 horas**. Nunca borra un respaldo de las últimas 48 horas, aunque pongas una retención de 0.
5. Imprime un resumen con el tamaño y la duración, y deja un latido en la tabla `cron_ejecuciones` (ver "Cómo te enteras si falla").

## Paso 1. Crear el bucket y las credenciales

Sirve cualquier almacenamiento compatible con S3. Dos opciones baratas:

**Cloudflare R2** (recomendada)
1. Cloudflare → R2 → *Create bucket* (por ejemplo `gasoplus-respaldos`). Región automática.
2. R2 → *Manage R2 API Tokens* → *Create API token* con permiso **Object Read & Write** limitado a ese bucket.
3. Anota: *Access Key ID*, *Secret Access Key* y el endpoint, que tiene la forma `https://<ID_DE_CUENTA>.r2.cloudflarestorage.com`.

**Backblaze B2**
1. Backblaze → *Buckets* → *Create a Bucket* (privado, sin cifrado extra ni *object lock*, para poder purgar los viejos).
2. *Application Keys* → *Add a New Application Key* limitada a ese bucket, con lectura y escritura.
3. Anota el *keyID*, la *applicationKey* y el endpoint S3 del bucket (aparece en la ficha del bucket, con la forma `https://s3.<región>.backblazeb2.com`).

Guarda las credenciales en tu gestor de contraseñas. No las pegues en chats ni en el repositorio.

## Paso 2. Variables de entorno

Se definen en el **servicio Cron** de Railway (no en el servicio web):

| Variable | Valor |
| --- | --- |
| `DATABASE_URL` | La misma URL de Postgres que usa la app. Mejor la de la **red privada** (`...railway.internal`); si el proxy público se va a quitar (ver paso 6), esta es la única que va a seguir funcionando. |
| `S3_ENDPOINT_URL` | El endpoint del paso 1. |
| `S3_BUCKET` | El nombre del bucket. |
| `S3_ACCESS_KEY_ID` | La credencial de acceso. |
| `S3_SECRET_ACCESS_KEY` | La credencial secreta. |
| `S3_REGION` | Opcional. Para R2 déjala vacía (el script usa `auto`). |
| `BACKUP_RETENCION_DIAS` | Opcional, 30 por defecto. |
| `BACKUP_PREFIJO` | Opcional, `backups/` por defecto. |
| `HEALTHCHECK_URL_BACKUP_POSTGRES` | Opcional. URL de un servicio de monitoreo externo (healthchecks.io, Better Stack...). Ver más abajo. |

## Paso 3. Crear el servicio Cron en Railway

1. En el proyecto de Railway, crea un servicio nuevo desde **el mismo repositorio** (misma imagen que el servicio web).
2. Comando de inicio (*Custom Start Command*): `python scripts/backup_postgres.py`
3. *Cron Schedule*: una vez al día, por ejemplo `0 8 * * *` (08:00 UTC = 03:00 en Lima, de madrugada). Railway usa UTC.
4. Agrega las variables del paso 2.
5. Despliega y fuerza una primera corrida a mano para no esperar hasta mañana.

La imagen ya incluye `pg_dump` y `pg_restore` (el `Dockerfile` instala `postgresql-client`).

## Paso 4. Comprobar que funcionó

- En los logs de la corrida debe aparecer algo como: `Dump generado y verificado: 12.3 MB, 215 objeto(s) en el índice.`, `Subida OK.` y
  `Backup completado correctamente: ... pg_dump 4 s, subida 2 s, total 7 s.`
- En el bucket debe verse el archivo `backups/agentkit-....dump`.
- En Inicio (solo admin) **no** debe aparecer el aviso "El proceso programado "Respaldo de la base de datos" falló".

### Si falla por versión distinta

Si el log dice `server version mismatch`, el `pg_dump` de la imagen es más viejo que tu Postgres de Railway. El `Dockerfile` instala
`postgresql-client` **sin fijar versión**, así que trae la que ofrece Debian por defecto, y Railway puede tener una base de una versión mayor.
Esto **no se ha cambiado** en el repositorio: es una decisión tuya.

1. Mira la versión de tu base: en la consola de Postgres de Railway, `SELECT version();`.
2. Mira la del cliente de la imagen: en un servicio con esa imagen, `pg_dump --version`.
3. Si el cliente es menor, hay que instalar uno de la misma versión mayor que el servidor (o mayor). La forma habitual es agregar el repositorio
   oficial de Postgres (PGDG) en el `Dockerfile` y pedir `postgresql-client-<N>` (`N` = la versión mayor de tu base). Esquema, **sin probar**:

   ```dockerfile
   RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates curl gnupg lsb-release ffmpeg \
    && install -d /usr/share/postgresql-common/pgdg \
    && curl -fsSL -o /usr/share/postgresql-common/pgdg/apt.postgresql.org.asc https://www.postgresql.org/media/keys/ACCC4CF8.asc \
    && echo "deb [signed-by=/usr/share/postgresql-common/pgdg/apt.postgresql.org.asc] https://apt.postgresql.org/pub/repos/apt $(lsb_release -cs)-pgdg main" > /etc/apt/sources.list.d/pgdg.list \
    && apt-get update && apt-get install -y --no-install-recommends postgresql-client-17 \
    && rm -rf /var/lib/apt/lists/*
   ```

   Cambia `17` por la versión de tu base. Pruébalo primero en un despliegue de prueba: toca la misma imagen que usa el servicio web.

## Paso 5. Probar una restauración (hazlo UNA vez, de verdad)

Un respaldo que nunca se restauró no es un respaldo. Restaura a una base **temporal**, nunca sobre la de producción.

1. Baja un archivo `.dump` del bucket (desde el panel de R2/B2).
2. Crea una base vacía temporal: un servicio Postgres nuevo en Railway (bórralo después), o un Postgres local.
3. Restaura:

   ```bash
   pg_restore --no-owner --no-privileges --dbname "postgresql://USUARIO:CLAVE@HOST:PUERTO/BASE_TEMPORAL" archivo.dump
   ```

   Pueden salir avisos por roles o extensiones que no existen en la base temporal; lo que importa es que no haya errores en las tablas de datos.
4. Comprueba que hay datos: por ejemplo, `SELECT count(*) FROM leads;` y `SELECT count(*) FROM mensajes;` y compáralos con producción.
5. Borra la base temporal.

Para restaurar desde tu computador necesitas un Postgres con `pg_restore` instalado y, si la base temporal está en Railway, su URL pública.

## Costo esperado

Casi cero. Un respaldo comprimido de esta base pesa pocos MB; con 30 días de retención son unos cientos de MB. Tanto Cloudflare R2 como
Backblaze B2 dan un espacio gratuito mensual de varios GB (verifica las cifras vigentes en sus páginas de precios) y, en R2, no cobran la
descarga al restaurar. El servicio Cron de Railway solo consume unos segundos de cómputo al día.

## Paso 6. Rotar la contraseña de Postgres y quitar el proxy público (DESPUÉS de tener respaldo)

La contraseña de Postgres se filtró (ver nota del 2026-09-24). **No la rotes todavía**: primero ten un respaldo verificado y una restauración
de prueba hecha. El orden importa:

1. Pasos 1 a 5 terminados (respaldo corriendo y restauración probada).
2. Si aún usas el proxy público para algo (por ejemplo, restaurar desde tu computador), termina de usarlo antes del paso 4.
3. Rota la contraseña en el servicio de Postgres de Railway. Después, actualiza `DATABASE_URL` en **todos** los servicios que la tengan pegada
   a mano: el servicio web **y cada Cron** (incluido el de respaldo). Si algún servicio la toma por referencia a las variables del servicio
   de Postgres, se actualiza solo; revisa cada uno.
4. Quita el proxy público (TCP proxy) del servicio de Postgres, para que la base solo sea alcanzable por la red privada.
5. Comprueba: Inicio carga, llega un mensaje de prueba por WhatsApp, y fuerza una corrida del Cron de respaldo.

Si algo falla en el paso 3, la base no se pierde: solo hay que corregir la `DATABASE_URL` del servicio que quedó con la clave vieja.

## Cómo te enteras si falla

- **Dentro del panel:** cada corrida deja un latido en la tabla `cron_ejecuciones`. En Inicio, el admin ve un aviso rojo si la última corrida falló
  y uno amarillo si la última corrida buena fue hace más del doble del intervalo esperado (48 h para el respaldo). Un proceso que nunca corrió no avisa.
- **Fuera del panel (opcional):** si defines `HEALTHCHECK_URL_BACKUP_POSTGRES`, el script hace un GET a esa URL cuando termina bien y a
  `<URL>/fail` cuando falla (timeout de 5 s, nunca rompe el respaldo). En un servicio como healthchecks.io configuras que te escriba si pasa un día sin
  señal, y así te enteras incluso si Railway o la base están caídas y el aviso del panel no puede dispararse.
