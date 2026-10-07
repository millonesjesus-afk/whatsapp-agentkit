# Respaldos de Postgres (Gaso+ / Maiek AI)

Guía para dejar funcionando el respaldo diario de la base de datos de producción. El script ya existe
(`scripts/backup_postgres.py`, ADR-0001); lo que falta son cosas que solo puedes hacer tú: crear el
bucket, crear el servicio Cron en Railway y probar una restauración.

Estado a 2026-10-07: **verificado** que el respaldo sube bien con `pg_dump` 18 (la imagen ya instala `postgresql-client-18`, igual a la
versión de la base de Railway): un dump de 1.1 MB, verificado con `pg_restore --list` y subido al bucket. Lo que sigue dependiendo de ti es
que el servicio Cron esté programado en Railway (paso 3) y correr la **prueba de restauración** (paso 5) al menos una vez: hasta entonces
el respaldo está probado para subir, no para restaurar.

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

La imagen ya incluye `pg_dump` y `pg_restore` (el `Dockerfile` instala `postgresql-client-18` desde el repositorio oficial de Postgres).

## Paso 4. Comprobar que funcionó

- En los logs de la corrida debe aparecer algo como: `Dump generado y verificado: 12.3 MB, 215 objeto(s) en el índice.`, `Subida OK.` y
  `Backup completado correctamente: ... pg_dump 4 s, subida 2 s, total 7 s.`
- En el bucket debe verse el archivo `backups/agentkit-....dump`.
- En Inicio (solo admin) **no** debe aparecer el aviso "El proceso programado "Respaldo de la base de datos" falló".

### Si falla por versión distinta

Si el log dice `server version mismatch`, el `pg_dump` de la imagen es más viejo que tu Postgres de Railway. **Hoy esto ya está resuelto**: el
`Dockerfile` instala `postgresql-client-18` desde el repositorio oficial de Postgres (PGDG), porque la base de Railway es la versión 18
(imagen `postgres-ssl:18`), y el respaldo del 2026-10-07 subió bien con ese cliente. Si algún día Railway sube la base a otra versión mayor:

1. Mira la versión de tu base: en la consola de Postgres de Railway, `SELECT version();`.
2. Mira la del cliente de la imagen: en un servicio con esa imagen, `pg_dump --version`.
3. Si el cliente es menor, cambia el número en la línea `postgresql-client-18` del `Dockerfile` por la versión mayor de tu base (o una mayor)
   y vuelve a desplegar. Esa línea toca la misma imagen que usa el servicio web: pruébala primero en un despliegue de prueba.

## Paso 5. Probar una restauración

Un respaldo que nunca se restauró no es un respaldo. Para eso existe `scripts/probar_restauracion_respaldo.py`: descarga el último respaldo,
lo restaura en una base **temporal** y compara los datos con la base viva. Está pensado para producción: no escribe en la base viva.

### Cómo correrla

- **En Railway, como servicio temporal o Cron** (recomendado, porque la base solo se alcanza por la red privada): crea un servicio desde
  el mismo repositorio, con las mismas variables que el Cron de respaldo (`DATABASE_URL` por red privada y las `S3_*`), y como comando de inicio:

  ```bash
  python scripts/probar_restauracion_respaldo.py
  ```

  Si lo dejas como Cron, una vez al mes alcanza (por ejemplo `0 9 1 * *`). Hoy **no** es un Cron programado ni está vigilado por el panel:
  si falla, solo lo ves en los logs del servicio (el código de salida es 1). Bórralo cuando termines si lo usaste como servicio temporal.
- **Desde tu computador:** posible solo si tienes `pg_restore` (cliente 18) y alcanzas la base (proxy público). No es lo recomendado.

Opciones:

| Comando | Qué hace |
| --- | --- |
| `python scripts/probar_restauracion_respaldo.py --solo-listar` | Muestra los respaldos del bucket con tamaño y fecha. No toca ninguna base. |
| `python scripts/probar_restauracion_respaldo.py --dry-run` | Descarga el último y lo verifica con `pg_restore --list`. No crea ninguna base. Úsalo primero. |
| `python scripts/probar_restauracion_respaldo.py --clave backups/agentkit-AAAAMMDD-HHMMSS.dump` | Prueba ese respaldo en vez del más reciente. |
| `python scripts/probar_restauracion_respaldo.py --base-admin NOMBRE` | Base a la que conectarse para crear/eliminar la temporal (por defecto `postgres`, luego `template1`). |

El usuario de `DATABASE_URL` debe poder crear bases (en Railway es el superusuario `postgres`, así que sirve).

### Qué hace, paso a paso

1. Toma el respaldo más reciente bajo `BACKUP_PREFIJO` (o el de `--clave`), lo descarga a un directorio temporal y verifica que no esté vacío
   y que `pg_restore --list` lo lea. Si el más reciente está vacío, falla: no salta al anterior.
2. Crea en el **mismo servidor** una base nueva llamada `restauracion_prueba_<AAAAMMDDHHMMSS>`. La conexión administrativa va a la base
   `postgres`, nunca a la viva. Si el nombre temporal coincidiera con el de la base viva, o no tuviera esa forma, aborta antes de crear nada.
3. Restaura con `pg_restore --no-owner --no-privileges --exit-on-error` dentro de la base temporal.
4. Cuenta las filas de las tablas clave en la restauración y en la base viva (abierta con `default_transaction_read_only=on`, solo `SELECT`) y
   mira la fecha del último mensaje restaurado.
5. **Siempre**, incluso si algo falló: elimina la base temporal (`DROP DATABASE ... WITH (FORCE)`, solo sobre esa base) y los archivos temporales,
   y lo confirma por pantalla.
6. Imprime el resumen (respaldo usado, tamaño, tiempos, conteos, veredicto) y sale con código 1 si hay ALERTA o error.

### Qué NO toca

- No escribe nada en la base viva (solo lectura, y la propia conexión lo impide).
- No borra ni modifica nada del bucket.
- No registra latido en `cron_ejecuciones` y no aparece en los avisos de Inicio.
- No imprime la contraseña: viaja por `PGPASSWORD`, nunca en los argumentos ni en la URL.

### Cómo leer la tabla

```
Tabla                    Restaurado    Base viva  Estado
leads                         1,000        1,040  OK
mensajes                     19,800       20,500  OK
...
```

- El respaldo tiene hasta ~24 h de antigüedad, así que es normal que la base viva tenga **más** filas que la restauración.
- `leads`, `mensajes`, `conversations`, `opportunities` y `eventos_lead` exigen que lo restaurado sea al menos el 90 % de la base viva.
- Todas las tablas (también `usuarios`, `configuracion`, `uso_mensajes_meta` y `envios_meta`) exigen no estar vacías si la viva no lo está.
  Una tabla que no existe en ninguna de las dos se muestra como "no existe" y se ignora.
- El último mensaje restaurado debe tener menos de 36 horas.
- **OK** en todo: el respaldo se restaura y es coherente. **ALERTA**: lee los motivos debajo del veredicto; lo más probable es que el respaldo
  sea viejo, incompleto o que el Cron de respaldo esté fallando. Corre `--solo-listar` para ver las fechas.
- Si aparece "No se pudo eliminar la base temporal", bórrala a mano (`DROP DATABASE restauracion_prueba_...;`) para no dejar basura en el servidor.

### Restauración manual (si necesitas recuperar datos de verdad)

Solo si el script no basta. Siempre contra una base temporal, nunca sobre producción:

```bash
createdb -h HOST -U USUARIO BASE_TEMPORAL
pg_restore --no-owner --no-privileges --exit-on-error -h HOST -U USUARIO -d BASE_TEMPORAL archivo.dump
```

(la contraseña va en la variable de entorno `PGPASSWORD`). Después comprueba con `SELECT count(*) FROM leads;` y bórrala.

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
