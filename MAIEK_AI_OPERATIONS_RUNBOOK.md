# Maiek AI — Operations Runbook

**Versión 1.0 · Estado: Approved**

| | |
|---|---|
| Documento | Operations Runbook |
| Proyecto | Maiek AI |
| Versión | 1.0 |
| Estado | **Approved** |
| Fecha de creación | 2026-07-29 |
| Autor | Claude, a pedido de Jesús Millones |
| Fecha de aprobación | 2026-07-29 |
| Última actualización | 2026-07-30 |

## Dependencias

`MAIEK_AI_OPERATIONS_ARCHITECTURE.md` (define el marco de categorías y severidad que este
documento llena con procedimientos concretos — sección 3 de ese documento ya declara que el
detalle paso a paso vive acá); `MAIEK_AI_DATA_ARCHITECTURE.md` (Fase 1, origen del Escenario 1);
`agent/migraciones.py` (implementación real del Escenario 1).

## Consumido por

Quien despliegue el proyecto — hoy, exclusivamente Jesús Millones y Claude en sesiones de
implementación; no hay un equipo de guardia todavía (Operations Architecture, brecha conocida).

## Control de versiones

| Versión | Fecha | Autor | Descripción |
|---|---|---|---|
| 1.0 | 2026-07-29 | Claude | Primera versión — documento hijo de Operations Architecture, declarado desde el Implementation Roadmap como "todavía no construido". Empieza a poblarse (tal como el Roadmap ya preveía, sección 5: *"empieza a poblarse en la Fase 0 con los escenarios ya identificados... se completa en la Fase 4"*) con el primer escenario real encontrado durante la implementación: el riesgo de `alembic stamp head` sobre la Postgres de producción, identificado al adoptar Data Architecture Fase 1. |
| 1.1 | 2026-07-30 | Claude | Corrección del Escenario 1 a partir de evidencia real del primer despliegue de v0.2.0: `alembic stamp head` directo resultó incorrecto porque `head` ya incluía migraciones incrementales posteriores al baseline sin aplicar contra la base real — rompió el panel de leads en producción (`500`, corregido sin pérdida de datos). Se corrige la secuencia (pasos 3-5), se agrega la explicación de la causa raíz y la sección "Lecciones aprendidas del primer despliegue". |

## Alcance y desviación declarada del ADS

Este documento es **procedimental, no arquitectónico** — es una secuencia de pasos a seguir ante
un escenario operativo concreto, no una decisión de diseño. Por eso se aparta deliberadamente de
la plantilla estándar de `MAIEK_AI_ARCHITECTURE_DOCUMENT_STANDARD.md` (Architectural Constraints,
Decisiones locales, Architecture Success Criteria no aplican a un runbook) — desviación ya prevista
y autorizada explícitamente por el ADS §2: *"una desviación es válida cuando la naturaleza del
documento lo justifica (ej. un documento más procedimental que arquitectónico, como el futuro
Operations Runbook)"*.

Cada escenario nuevo se agrega como una sección numerada independiente, siguiendo el marco de
categorías y severidad ya fijado en `MAIEK_AI_OPERATIONS_ARCHITECTURE.md` §2-3.

---

## Escenario 1 — Migraciones iniciales: `alembic stamp head` sobre una base existente

**Severidad**: Alta si se omite — un despliegue sin este paso previo **falla el arranque**
(confirmado, ver Data Architecture Fase 1, Implementation Review). No afecta la atención en vivo
mientras el despliegue anterior siga corriendo (Railway no reemplaza el proceso activo hasta que
el nuevo arranca con éxito), pero bloquea por completo cualquier cambio nuevo hasta resolverse.

**Contexto**: desde que `agent/migraciones.py` existe, `agent/main.py` corre `alembic upgrade
head` en cada arranque, en vez de `Base.metadata.create_all()`. Alembic necesita saber en qué
versión de esquema está la base — lo registra en una tabla propia, `alembic_version`. Una base que
ya tenía el esquema actual **antes** de que este mecanismo existiera (como la Postgres de
producción de Gaso+ hoy) no tiene esa tabla — hay que decirle a Alembic "ya estás en la versión
baseline" sin volver a crear las tablas.

**Corrección importante (evidencia real, 2026-07-30)**: la versión original de este escenario
decía que eso se logra con `alembic stamp head`. Eso es correcto **únicamente si `head` coincide
con el baseline** — que era el caso cuando este documento se escribió (una sola migración
existente). En cuanto se agregan migraciones incrementales posteriores al baseline (como
sucedió durante el resto de la Fase 1: `124cb805569e`, `925ec2d81736`), `head` deja de ser el
baseline, y `alembic stamp head` deja de ser el comando correcto — ver la explicación completa más
abajo y "Lecciones aprendidas del primer despliegue" al final de este escenario.

### 1. Cuándo debe ejecutarse

Una sola vez, **antes** del primer deploy que incluya el commit que introduce
`agent/migraciones.py` (Data Architecture Fase 1) en cada entorno que tenga una base de datos
preexistente con el esquema actual. No se vuelve a ejecutar en deploys posteriores — es un paso de
adopción única, no parte del flujo normal de deploy.

### 2. En qué entornos aplica

| Entorno | ¿Aplica? | Por qué |
|---|---|---|
| Postgres de producción (Railway) | **Sí — obligatorio** | Ya tiene el esquema actual con datos reales; sin stamp, el próximo arranque falla |
| SQLite local de desarrollo (`agentkit.db`), si ya existe con datos de antes de este cambio | Sí, si querés conservarlo | Mismo riesgo que producción, a menor escala — o más simple: borrar el archivo y dejar que `alembic upgrade head` lo cree desde cero |
| Cualquier base nueva, vacía (entorno de pruebas, CI, un `agentkit.db` recién borrado) | No | `alembic upgrade head` la crea correctamente desde la migración baseline, sin intervención |

### 3. Qué verificar antes de ejecutarlo

- **Confirmar que `DATABASE_URL` apunta al entorno correcto** — este es el paso donde un error
  tiene más consecuencia (marcar la base equivocada como "ya migrada" deja esa base realmente sin
  las tablas que debería tener). Verificar contra el panel de Railway (Variables del servicio
  Postgres) antes de correr nada.
- Confirmar que la base tiene efectivamente el esquema actual y nada más — no debería haber
  columnas o tablas que la migración baseline no conozca. Con acceso a `psql`:
  ```sql
  SELECT table_name FROM information_schema.tables WHERE table_schema = 'public' ORDER BY 1;
  ```
  Debe listar exactamente: `archivos_adjuntos`, `campanas`, `canales_whatsapp`, `configuracion`,
  `leads`, `lineas_venta`, `mensajes`, `usuarios` (y ninguna `alembic_version` todavía).
- **Confirmar cuál es el `head` real del código en ese momento y compararlo contra el esquema real
  de la base** — si el código ya tiene migraciones incrementales posteriores al baseline
  (`migrations/versions/`, cualquier archivo cuyo `down_revision` no sea `None`) que la base
  todavía no tiene aplicadas, el baseline y `head` **no son lo mismo**. En ese caso no corresponde
  stampear a `head` — ver el procedimiento corregido abajo.
- Tener un backup reciente confirmado (Fase 0, `scripts/backup_postgres.py`) — el `stamp` en sí no
  toca datos ni estructura, pero es la disciplina general antes de cualquier operación sobre la
  base de producción.

### 4. Procedimiento

Desde una máquina con acceso a la `DATABASE_URL` real de producción (Railway → servicio Postgres →
Variables → `DATABASE_URL`, o `DATABASE_PUBLIC_URL` si se corre fuera de la red interna de
Railway). No hace falta reescribir el driver a `asyncpg` a mano — `migrations/env.py` ya hace esa
conversión internamente.

**Secuencia correcta (corregida el 2026-07-30 a partir del hallazgo real del primer despliegue —
la versión anterior indicaba `alembic stamp head` directo, ver la explicación de por qué eso es
incorrecto más abajo):**

1. **Verificar estado actual**:
   ```bash
   DATABASE_URL="<DATABASE_URL real>" python -m alembic current
   ```
   Sin salida = la base no está registrada en Alembic todavía (caso esperado de este escenario). Si
   ya muestra una revisión, ir directo al paso 6 de este escenario ("Qué ocurre si ya fue
   ejecutado previamente").

2. **Stamp al baseline correspondiente al esquema real de la base — nunca a `head` a ciegas**:
   ```bash
   DATABASE_URL="<misma DATABASE_URL>" python -m alembic stamp 8bf43ecd3785
   ```
   (`8bf43ecd3785` es el baseline vigente para Gaso+ hoy — confirmado en el paso 3 de arriba. Si en
   el futuro se agrega un baseline nuevo, usar ese revision id, no este literal.) El comando no
   imprime nada si sale bien.

3. **Upgrade a `head`** — este es el paso que ejecuta de verdad el DDL de cualquier migración
   incremental pendiente entre el baseline y `head`:
   ```bash
   DATABASE_URL="<misma DATABASE_URL>" python -m alembic upgrade head
   ```
   A diferencia del `stamp`, cada migración aplicada se imprime en pantalla (`Running upgrade
   <revisión_a> -> <revisión_b>, <mensaje>`). Si no imprime ninguna línea `Running upgrade`, no
   había nada pendiente — también es un resultado válido.

4. **Verificar versión final** — ver paso 5 más abajo.

### 5. Qué verificar después de ejecutarlo

```bash
DATABASE_URL="<misma DATABASE_URL>" python -m alembic current
```

Debe imprimir el revision id del **`head` real del código en ese momento** seguido de `(head)` —
no asumir que es `8bf43ecd3785`: si existen migraciones incrementales posteriores al baseline, el
id correcto es el de la última de ellas (hoy, `925ec2d81736`). Si el resultado no termina en
`(head)`, algo quedó a mitad de camino — repetir el paso 4 desde el punto 3, no continuar al
deploy.

Verificación adicional directa en la base (`psql`):
```sql
SELECT * FROM alembic_version;
```
Debe retornar exactamente una fila, con `version_num` igual al `head` real del código en ese
momento.

### 6. Qué ocurre si ya fue ejecutado previamente

`alembic stamp <revisión>` es **idempotente** — volver a correrlo no rompe nada, simplemente
vuelve a escribir el mismo revision id en `alembic_version`. Si no estás seguro de si ya se
ejecutó, corré primero `alembic current` (paso 5): si ya muestra el `head` real esperado, no hace
falta repetir nada — podés continuar directo al deploy. Si muestra una revisión intermedia (ni
vacío ni `head`), corré directamente el punto 3 del paso 4 (`alembic upgrade head`) para completar
lo que falta — no repitas el `stamp`.

### 7. Cómo validar que la base quedó correctamente sincronizada

Antes de considerar el punto cerrado:
1. `alembic current` (paso 5) muestra el `head` real esperado.
2. Deployá el commit y observá el arranque en los logs de Railway — debe verse una línea
   `agentkit: Migraciones aplicadas (alembic upgrade head, rc=0)` sin ningún `RuntimeError` ni
   traceback, antes de `agentkit: Base de datos inicializada`.
3. El health check (`GET /`) responde `200 {"status": "ok", ...}`.
4. **Además del arranque limpio, probar activamente al menos una ruta real que dependa de las
   columnas/tablas más recientes** (ej. cargar el panel de leads logueado) — un arranque exitoso
   **no garantiza** que el esquema esté completo, solo que Alembic no encontró nada que aplicar
   según su propio registro (ver "Lecciones aprendidas" abajo: exactamente esto falló en el primer
   despliegue sin que el arranque lo mostrara).
5. Enviá un mensaje de prueba real por WhatsApp y confirmá que se guarda y responde con
   normalidad (mismo criterio de cierre ya usado en Fase 0).

### 8. Qué pasos seguir si el comando falla

- **`alembic stamp` falla con un error de conexión** — la `DATABASE_URL` está mal copiada, o
  la base no es accesible desde donde estás corriendo el comando (red interna de Railway vs.
  acceso público). Verificar con `psql "$DATABASE_URL" -c "SELECT 1;"` primero.
- **`alembic stamp` corre sin error, pero `alembic current` no muestra nada después** — poco
  probable (el comando no falla silenciosamente en la práctica), pero si pasa: revisar que
  `DATABASE_URL` fue exactamente la misma en ambos comandos — un typo entre uno y otro apunta a
  bases distintas.
- **El deploy sigue fallando (no arranca) después de confirmar el stamp** — leer el mensaje
  completo en los logs de Railway. Desde que existe la detección automática (`agent/migraciones.py`,
  `_diagnosticar_baseline_no_registrado`), si el fallo es por este mismo escenario el mensaje lo
  dice explícitamente, mencionando las tablas encontradas y remitiendo a este documento — no debería
  aparecer como un error genérico de Postgres/SQLAlchemy. Si aparece un error distinto (de
  conexión, de permisos, u otro), no es este escenario — diagnosticar aparte.
- **El deploy arranca sin errores, pero una ruta real falla con un error de columna/tabla
  inexistente** — este es el escenario descrito en "Lecciones aprendidas" abajo: `head` avanzó más
  allá del baseline sin que las migraciones intermedias se aplicaran de verdad. La corrección es
  la secuencia completa del paso 4 (verificar estado → stamp al baseline real → `upgrade head`),
  no reintentar el deploy sin más.
- **En cualquier caso, antes de intentar nada destructivo**: el `stamp` nunca modifica datos ni
  estructura, así que no hay nada que revertir por haberlo corrido — el riesgo real está solo en
  correrlo contra la base equivocada (paso 3), no en el comando en sí.

### ¿Por qué `alembic stamp head` no es correcto cuando hay migraciones incrementales posteriores al baseline?

`alembic stamp <revisión>` no ejecuta ningún DDL — solo escribe en `alembic_version` el revision id
indicado, sin verificar que el esquema real de la base coincida con eso. `alembic stamp head`
específicamente stampea el `head` **del código en ese momento**, sea cual sea.

Mientras el código tiene una sola migración (el baseline), `head` y baseline son la misma revisión
— por eso `stamp head` funcionaba bien cuando este documento se escribió originalmente. Pero en
cuanto se agregan migraciones incrementales nuevas (como pasó durante el resto de la Fase 1, con
`124cb805569e` y `925ec2d81736`), `head` pasa a ser la última de esas migraciones — no el baseline.
Si en ese momento se ejecuta `alembic stamp head` contra una base que todavía tiene solo el
esquema baseline, Alembic queda convencido de que la base ya está al día. En el siguiente arranque,
`alembic upgrade head` no aplica nada — según su propio registro, no hay diferencia entre el estado
actual y `head` — y las columnas/tablas de esas migraciones incrementales **nunca se crean**.

El resultado no es un fallo de arranque (que sí sería visible de inmediato): el arranque termina
"exitosamente", y el error solo aparece más tarde, en tiempo de ejecución, cuando algún código
intenta usar la columna o tabla que nunca se creó — como un `500` genérico de base de datos, no un
error de Alembic.

**La corrección estructural**: nunca asumir que `head` es igual al baseline. Siempre verificar el
esquema real de la base, stampear explícitamente al baseline que corresponde a ese esquema (nunca
a `head` directo), y dejar que `alembic upgrade head` sea el único mecanismo que efectivamente crea
el esquema nuevo — es el único paso de los dos que realmente ejecuta DDL.

### Lecciones aprendidas del primer despliegue (v0.2.0, 2026-07-30)

**Qué pasó**: siguiendo la versión original de este runbook y de `DEPLOYMENT_CHECKLIST_v0.2.0.md`,
se ejecutó `alembic stamp head` contra la Postgres de producción. En ese momento `head` ya incluía
las dos migraciones incrementales (`124cb805569e`, `925ec2d81736`) agregadas después de que este
documento se escribiera originalmente, pero la base real todavía tenía solo el esquema baseline. El
deploy arrancó sin errores. El panel de leads devolvió `500` en el primer uso real:
`column leads.revision_prioritaria does not exist`.

**Impacto real**: panel de leads inaccesible (`500`) entre el deploy (06:53 UTC) y la corrección
(06:59 UTC) — aproximadamente 6 minutos. El webhook de WhatsApp no se vio afectado (no depende de
esa columna). Sin pérdida de datos: la corrección fue puramente aditiva (agregar una columna con
`server_default` y crear una tabla nueva).

**Cómo se detectó**: como parte de la validación de `request_id` del `DEPLOYMENT_CHECKLIST_v0.2.0.md`
(probar una ruta real del panel ya logueado) — no por monitoreo activo ni alertamiento, que todavía
no existen (brecha ya conocida de `MAIEK_AI_DEVOPS_ARCHITECTURE.md`).

**Cómo se corrigió**: `alembic stamp 8bf43ecd3785` (revertir el stamp incorrecto al baseline real),
seguido de `alembic upgrade head` (esta vez ejecutando de verdad el DDL de las dos migraciones
pendientes). Verificado con `psql` que la columna y la tabla existen, y que el panel carga
correctamente.

**Qué cambia a partir de esta evidencia**:
1. Este escenario (pasos 3 a 5 de arriba) ya no asume que `head` es igual al baseline — se
   reescribió para verificar el esquema real y stampear explícitamente al baseline correspondiente
   antes de cualquier `upgrade head`.
2. `DEPLOYMENT_CHECKLIST_v0.2.0.md`, secciones 2 y 3, corregidas con la misma secuencia.
3. El paso 7 de este escenario ahora exige probar activamente una ruta real, no solo observar un
   arranque limpio — un arranque exitoso no garantiza que el esquema esté completo.

### Detección automática en el arranque (no reemplaza este procedimiento)

`agent/migraciones.py` verifica, antes de intentar `alembic upgrade head`, si la base tiene tablas
del esquema actual pero no tiene `alembic_version` — el escenario exacto de este runbook. Si lo
detecta, el arranque falla con un mensaje explícito (lista las tablas encontradas y remite a este
documento) en vez del error genérico del motor de base de datos ("la tabla ya existe"). Esto es
**solo diagnóstico** — el sistema nunca ejecuta `alembic stamp head` por sí mismo, porque es una
decisión administrativa sobre una base ya existente que requiere confirmación humana (así lo pidió
explícitamente el usuario). El mensaje exacto que vas a ver en los logs si este escenario ocurre:

> La base de datos ya tiene tablas del esquema actual (archivos_adjuntos, campanas,
> canales_whatsapp, configuracion, leads, lineas_venta, mensajes, usuarios) pero no está
> registrada en Alembic (no existe la tabla 'alembic_version'). Esto es esperado la primera vez
> que este código corre contra una base que ya tenía datos de antes de adoptar Alembic (Data
> Architecture Fase 1) — NO es un error de la aplicación. Se requiere una acción manual,
> administrativa, una sola vez: correr 'alembic stamp head' contra esta base ANTES de reintentar
> el arranque. Procedimiento completo: MAIEK_AI_OPERATIONS_RUNBOOK.md, Escenario 1. El arranque se
> detiene acá a propósito — NO se ejecuta el stamp automáticamente, es una decisión sobre una base
> ya existente que requiere confirmación humana.

---

*Próximos escenarios a agregar (marco ya definido en Operations Architecture §3, sin construir
todavía): canal de WhatsApp sin `app_secret` configurado, fallas técnicas repetidas de la IA,
ausencia de backup verificado — se completan en la Fase 4 del Implementation Roadmap, o antes si
la evidencia real lo justifica (Evidence over Opinion).*
