# Prueba de botones interactivos en coexistencia (Fase 0)

Fecha: 2026-10-08. Estado: lista para ejecutar. Aprobada por el dueño como "Fase 0" del proyecto de botones guiados.

## Para qué es

La documentación de Meta no aclara cómo se comportan los mensajes **interactivos** (botones de respuesta y listas) enviados por la Cloud API desde el
número de producción cuando está en **coexistencia** (app WhatsApp Business en el celular + Cloud API a la vez). Esta prueba, de medio día y con un
celular real, lo averigua. **Si falla, el proyecto de botones se detiene.**

Hay dos piezas:

- `scripts/probar_botones_interactivos.py`: arma y envía UN mensaje de prueba (rotulado `[PRUEBA]`) y, aparte, lee de la base lo que el webhook ya
  registró (`--reporte`, solo lectura).
- Este guion: qué hacer con el celular, qué mirar y anotar, y cómo decidir.

Quién hace qué: el **dueño** pone el celular de prueba, toca los botones y mira las pantallas. El **orquestador** corre el script en Railway y consulta
los logs.

## Reglas del script (ya cumplidas en el código)

- **No envía nada por defecto.** Sin `--enviar` solo imprime el payload exacto (dry-run).
- Envía **solo** al teléfono dado con `--telefono`, y solo si ese número **tiene un lead en la base y su último mensaje entrante tiene menos de 24 h**
  (ventana abierta). Si no, se niega (código de salida 2).
- **Doble confirmación:** `--enviar` exige además `--confirmar-telefono` con el **mismo** valor que `--telefono`. Antes de enviar imprime el resumen del
  lead (nombre, resultado, asesor, campaña) para que se vea que es el número de prueba y no un cliente real.
- **El teléfono de prueba lo da el dueño.** No hay ningún teléfono por defecto ni en el código; no lo adivines ni lo agregues al repositorio.
- **No pasa por la capa de envíos de producción ni por la política de tope** (`agent/envios.py`): es una prueba puntual y manual. Hace un solo POST, sin
  reintentos (Meta no tiene idempotencia: reintentar duplicaría el mensaje).
- **Nunca imprime el token.** Todo texto que sale pasa por una limpieza que lo oculta.

## 1. Preparación

### 1.1 Qué número usar

- El **número de producción** (el que está en coexistencia). Es la única forma de probar lo que importa.
- El celular de prueba lo elige el dueño. **Debe ser un número que le escriba al de producción** (eso crea el lead y abre la ventana). Idealmente uno con
  dos opciones de cliente: un celular **Android** y un **iPhone**; si solo hay uno, se hace con ese y se anota qué sistema es.
- Alguien debe tener a mano la **app WhatsApp Business del número de producción** (el celular del asesor) para mirar el punto (b).
- Para el punto (d) hace falta que el WhatsApp del celular de prueba esté vinculado a **WhatsApp Web o escritorio**.

### 1.2 Qué pasa con Gabi mientras pruebas (importante)

El celular de prueba es, para el sistema, un lead más: Gabi puede contestarle el primer "hola" y **cada toque de botón le llega como un texto normal**
(el título), así que Gabi puede responder a cada toque. No rompe la prueba, pero ensucia la lectura. Decide con el orquestador antes de empezar:

- si ese lead ya tiene asesor asignado o Gabi pausada, Gabi no contesta (es lo más limpio);
- si no, acepta que Gabi conteste y anótalo; esas respuestas aparecen en el reporte como "Gabi / panel".
- El lead de prueba contará en las métricas del panel. Se puede dejar así o limpiarlo después; este script no toca nada de eso.

### 1.3 Abrir la ventana

1. Desde el celular de prueba, escribe un texto (por ejemplo "prueba botones") al número de producción. Anota la hora.
2. Tienes 24 h desde ese mensaje. Para toda la prueba salvo (e), alcanza de sobra.

### 1.4 Cómo correrlo en Railway (servicio temporal)

Se corre igual que `scripts/analisis_conversion.py` y `scripts/probar_restauracion_respaldo.py` (ver `docs/respaldos_postgres.md`, "Paso 5"): la base solo se
alcanza por la red privada de Railway, así que se usa un **servicio temporal** creado desde el **mismo repositorio** (misma imagen que el servicio web).
No es un Cron: no se le pone *Cron Schedule*.

1. En el proyecto de Railway, crea un servicio nuevo desde el mismo repositorio.
2. Variables (cópialas del servicio web; no las escribas a mano):
   - `DATABASE_URL`: la URL de la base **por la red privada**.
   - `CANAL_ENCRYPTION_KEY`: la misma del servicio web (solo hace falta para `--enviar`: descifra el token del canal).
3. *Custom Start Command*: el comando del paso que toque (ver 2). Tras cada ejecución, **cambia el comando y vuelve a desplegar** para la siguiente.
4. Mira la salida en los **Logs de ese servicio temporal**.
5. Al terminar la prueba, **borra el servicio**.

Dos cuidados:

- **Un redeploy o reinicio del servicio vuelve a ejecutar el comando.** Si el comando tiene `--enviar`, vuelve a enviar. Después de cada envío, cambia
  de inmediato el comando a uno **sin** `--enviar` (por ejemplo el `--reporte`). Revisa en los ajustes de despliegue del servicio la política de
  reinicio y, si existe la opción de no reiniciar nunca, úsala (si el script termina con error, un reinicio automático lo reintentaría).
- **Dry-run antes de enviar, siempre.** El dry-run no cuesta nada y muestra el resumen del lead: confirma ahí que es el número de prueba.

Comandos (reemplaza `519XXXXXXXX` por el teléfono de prueba que da el dueño; no lo copies de este documento):

```bash
# Dry-run (no envía): muestra el payload exacto y el resumen del lead
python scripts/probar_botones_interactivos.py --telefono 519XXXXXXXX --caso botones

# Enviar de verdad (doble confirmación)
python scripts/probar_botones_interactivos.py --telefono 519XXXXXXXX --confirmar-telefono 519XXXXXXXX --caso botones --enviar

# Leer lo que registró el webhook (solo lectura); --wamid es el que imprimió el envío (se puede repetir)
python scripts/probar_botones_interactivos.py --telefono 519XXXXXXXX --reporte --horas 6 --wamid wamid.XXXX
```

Casos (`--caso`): `botones`, `botones_emoji`, `lista`, `texto_ref`. Con `--cuerpo-largo` el cuerpo mide 300 caracteres (el máximo del diseño).

| Caso | Qué manda |
| --- | --- |
| `texto_ref` | Texto plano `[PRUEBA]`, de control: para comparar estado y precio. |
| `botones` | Reply buttons: "Ver detalles", "Pagar en cuotas", "Ver otros modelos" (ids `prueba_ver_detalles`, `prueba_pagar_cuotas`, `prueba_otros_modelos`). |
| `botones_emoji` | Los mismos tres con un emoji delante. El tercero ("📋 Ver otros modelos") mide 19 caracteres, 20 unidades UTF-16 y 22 bytes: si Meta lo rechaza con 131009 sabremos que cuenta bytes y no caracteres. |
| `lista` | List message con 4 filas (la cuarta con emoji en el título). |

El script imprime, junto al payload, una tabla con la longitud de cada título en caracteres, UTF-16 y bytes.

## 2. Secuencia de la prueba

Haz las pruebas en este orden. Tras cada envío anota el `wamid` que imprime el script y la hora.

| Paso | Qué se hace | Quién |
| --- | --- | --- |
| 0 | El dueño escribe "prueba botones" al número de producción. Se corre el dry-run y se confirma que el resumen del lead es el del número de prueba. | dueño + orquestador |
| 1 | Enviar `texto_ref` (control). Mirar el celular. | orquestador, dueño |
| 2 | Enviar `botones`. Mirar el celular de prueba (a) y la app Business del asesor (b). **No tocar nada todavía** hasta anotar (a) y (b). | ambos |
| 3 | Tocar un botón **en el celular** (c). Correr `--reporte`. | dueño, orquestador |
| 4 | Enviar `botones` otra vez. Tocar un botón **desde WhatsApp Web / escritorio** (d). Correr `--reporte`. | ambos |
| 5 | Correr `--reporte` con `--wamid` del texto de control y de los botones y comparar estados y `pricing` (f). | orquestador |
| 6 | Enviar `botones_emoji` y luego `lista` (g). Mirar cómo se ve cada uno y tocar una opción. | ambos |
| 7 | Si hay un celular con WhatsApp desactualizado, repetir `botones` ahí (h). | dueño |
| 8 | Prueba diferida (e): ver el apartado de la ventana de 24 h. | ambos |

## 3. Qué mirar y anotar

Para cada punto: anota **qué viste**, la **hora** y, si puedes, una **captura**.

### (a) Cómo se ve el mensaje en el celular del cliente (Android / iPhone)

- ¿Aparecen los 3 botones debajo del cuerpo? ¿Se leen completos los títulos?
- ¿Se ve el cuerpo completo (y con `--cuerpo-largo`, los 300 caracteres)? ¿Aparece `[PRUEBA]`?
- ¿Llegó con un solo tick, doble tick o azul? Anota Android o iPhone y la versión de WhatsApp.

### (b) Cómo lo ve el asesor en la app WhatsApp Business del número de producción

Es **la pregunta clave de la coexistencia** que Meta no aclara. Abre la conversación con el número de prueba en la app Business:

- ¿Aparece el mensaje **con botones**, **como texto plano** (solo el cuerpo), como un mensaje vacío / "no disponible", o **no aparece**?
- ¿Aparece en el orden correcto de la conversación? ¿Aparece el texto de control del paso 1?
- Ojo: si el mensaje de la API se espeja a la app como un "eco", el reporte lo mostrará como **"ECO de coexistencia con el wamid de la PRUEBA"** (y el
  sistema lo guardaría como un mensaje del asesor desde el celular; es información útil para el diseño).

### (c) Toque en el celular: qué llega al webhook

- En el chat (reporte, sección 3) debe aparecer una línea de tipo **TOQUE** con el **título** del botón. Anota la hora y si Gabi contestó algo.
- Hoy el webhook trata el toque como si el cliente hubiera escrito el título (`agent/providers/meta.py`, `parsear_webhook`). **El `interactivo_id` y el
  `contexto_id` no se guardan** (ver "Lo que el script no puede verificar"): no se puede confirmar desde la base que el id es `prueba_ver_detalles`.

### (d) Toque desde WhatsApp Web / escritorio

- ¿El toque llega como un **TOQUE** (igual que en el celular), o aparece una línea **"TIPO NO SOPORTADO"** (`[unsupported]` / `[interactive]`), o no llega nada?
- ¿WhatsApp Web muestra los botones? ¿Muestra algún aviso de "abre en tu celular" al tocar?
- Si el toque no se resuelve, Meta suele mandar un error de tipo no soportado (131051) o genérico (131000) en el mensaje entrante. **Ese código no queda
  registrado** (ver más abajo): lo que sí queda es el tipo en el chat y la línea de log `Mensaje no soportado (`.

### (e) ¿El toque renueva la ventana de 24 h?

Es una prueba diferida. La ventana la abre un mensaje **del cliente**; un toque es un mensaje del cliente, pero hay que comprobarlo con Meta:

1. El dueño escribe un **texto a mano** a la hora T0 (por ejemplo la del paso 0).
2. Entre T0 + 1 h y T0 + 23 h, el dueño **toca un botón** de un mensaje de prueba (puede ser el del paso 3). Anota la hora del toque (T1).
3. **Pasadas las 24 h de T0 (T0 + 24 h) pero antes de T1 + 24 h**, enviar `texto_ref`.
4. Si Meta lo acepta y llega: **el toque renueva la ventana**. Si Meta responde 131047 (fuera de ventana): **no la renueva**.
- Nuestro script calcula la ventana contando los toques como mensajes del cliente (como hace el sistema en producción); por eso en el paso 3 el script
  **sí** dejará enviar, y el veredicto lo da Meta.
- Mientras tanto el reporte muestra "último mensaje del cliente" con la marca TOQUE: sirve para ver desde cuándo cuenta nuestro cálculo.

### (f) Estados y `pricing.type` del interactivo frente a un texto

Corre `--reporte` con los `--wamid` del texto de control y de los interactivos (aparecen marcados con `*`). Para cada uno anota:
`estado` (sent / delivered / read / failed), `pricing.type` (`regular`, `free_customer_service`, `free_entry_point`), `category` (service, utility, marketing…),
`billable` y cualquier error.

- Lo esperable dentro de la ventana es que el interactivo tenga el **mismo** `type` y `category` que el texto. Si el interactivo sale con otra categoría o
  como cobrable (`regular`) cuando el texto sale gratis, **es un hallazgo de costo** y pesa en la decisión.
- Los estados llegan segundos o minutos después; si el reporte aún no los muestra, vuelve a correrlo.

### (g) Lista y emoji en títulos

- `botones_emoji`: ¿Meta aceptó los tres títulos? Si responde 131009 (parámetro inválido), el envío entero falla: anota el código y el mensaje (el script
  los imprime) y qué título lo causó (la tabla UTF-16/bytes ayuda). ¿Se ven bien los emoji en Android, iPhone y Web?
- `lista`: ¿se ve el botón "Ver opciones"? ¿Se abre la lista con las 4 filas y sus descripciones? ¿Se ve igual en la app Business del asesor (b)? ¿El toque
  de una fila llega como TOQUE (título de la fila)?

### (h) Versión vieja de WhatsApp (si hay un celular)

- ¿Muestra los botones, o un mensaje de "no compatible", o el texto sin botones? Anota el modelo y la versión.

## 4. Tabla de resultados (para llenar)

| # | Prueba | Qué se espera | Resultado real | Evidencia (captura / wamid / log) | ¿OK? |
| --- | --- | --- | --- | --- | --- |
| 1 | Envío `texto_ref` (control) | HTTP 200, llega, estados sent/delivered | | | |
| 2 | Envío `botones` | HTTP 200, `wamid` devuelto | | | |
| 3a | Se ve en el celular — Android | 3 botones, títulos completos | | | |
| 3b | Se ve en el celular — iPhone | 3 botones, títulos completos | | | |
| 4 | App Business del asesor (b) | Se ve (con botones o al menos el texto) | | | |
| 5 | Toque en celular (c) | Línea TOQUE con el título; Gabi lo procesa | | | |
| 6 | Toque desde WhatsApp Web (d) | Igual que en celular | | | |
| 7 | Renueva ventana (e) | `texto_ref` aceptado pasadas las 24 h del texto | | | |
| 8 | Estados y `pricing` del interactivo (f) | Igual al texto de control | | | |
| 9 | Emoji en títulos (g) | Aceptados y bien vistos | | | |
| 10 | Lista (g) | Se abre, 4 filas, toque llega | | | |
| 11 | WhatsApp viejo (h) | Muestra botones o degrada a texto legible | | | |
| 12 | Costo | Sin cargo distinto al del texto | | | |

## 5. Criterios de decisión

Decide el dueño, con esta guía. Las condiciones de **DETENER** son suficientes por sí solas; las de **CONTINUAR** deben cumplirse todas.

### CONTINUAR (con botones en todos los clientes)

- El envío de `botones` y `lista` funciona (HTTP 200, entregado y leído) sin errores 131xxx.
- Se ven bien en Android **y** iPhone (a).
- El asesor en la app Business **ve** el mensaje (con botones o, como mínimo, el texto del cuerpo) y no queda un hueco incomprensible en la conversación (b).
- El toque en el celular llega al webhook como TOQUE (c) **y** el toque desde WhatsApp Web / escritorio también (d).
- `pricing` y `category` del interactivo iguales a los del texto (f).

### CONTINUAR SOLO EN MÓVIL (con diseño degradable)

Todo lo anterior se cumple **salvo** (d) o (h): desde WhatsApp Web / escritorio (o con versiones viejas) el toque no se resuelve (llega "tipo no soportado" o
no llega), pero en el celular todo funciona. Entonces los botones solo valen si **el mensaje se entiende y se puede contestar escribiendo** (cada opción
debe poder escribirse a mano y Gabi debe entenderla) y se acepta que parte de los clientes no pueda usar el toque. Si (e) resulta que el toque **no**
renueva la ventana, esto también se anota como condición del diseño (no bloquea por sí solo).

### DETENER el proyecto de botones

Cualquiera de estas:

- Meta rechaza de forma persistente los interactivos desde el número en coexistencia (errores 131xxx en `botones` o `lista`), o no llegan al cliente.
- En el celular, el toque **no llega** al webhook o llega vacío (c).
- El asesor **no ve** el mensaje en la app Business, o lo ve roto (b), y el dueño no acepta ese efecto sobre la atención.
- El interactivo se cobra distinto o más que un texto dentro de la ventana (f), sin que el dueño lo acepte.

Registra la decisión, la fecha y la tabla llena en el documento del proyecto.

## 6. Lo que el script NO puede verificar (y dónde mirarlo)

El webhook actual (`agent/main.py`, `agent/providers/meta.py`) **no guarda** lo siguiente. **No se cambió producción**: se documenta la alternativa.

| Qué falta | Por qué | Alternativa |
| --- | --- | --- |
| `interactivo_id` y `contexto_id` del toque | El parser los lee pero solo se usan en un camino de casos cerrados; no se guardan ni se loguean. En la base solo queda el título como texto del cliente. | Indirecta: el toque aparece como texto con el título exacto de un botón de prueba. Para ver el id y el contexto hay que cambiar código (ver abajo). |
| Código de error de un mensaje **entrante** (131051, 131000…) | El arreglo `errors` de un mensaje entrante no se guarda ni se loguea. | Queda el tipo `[unsupported]` / `[interactive]` en el chat y la línea de log `Mensaje no soportado (`. El código exacto no es recuperable sin cambio de código. |
| Cuerpo crudo del webhook | No se registra. | No existe en los logs. |
| Cómo se ve en pantallas (a, b, g, h) | Es visual. | Solo el dueño, con capturas. |
| Si Meta renueva la ventana con el toque (e) | Nuestro cálculo cuenta el toque; el veredicto es de Meta. | La prueba diferida (e). |

Sí queda registrado y el reporte lo muestra: estados `sent/delivered/read/failed`, `pricing.type`/`category`/`pricing_model`/`billable` y el error de los
estados `failed` (tabla `uso_mensajes_meta`), los mensajes del chat (tabla `mensajes`, incluidos los ecos de la app) y la ventana.

### Cadenas para buscar en los logs de Railway (servicio WEB, filtro de texto)

El orquestador las consulta a mano en los logs del servicio web (el script también las imprime al final de `--reporte`). Reemplaza `<tel>` por el teléfono de prueba:

| Cadena | Qué significa |
| --- | --- |
| `<tel>` | Todo lo que el servicio hizo con ese número. Empieza por aquí. |
| `Mensaje de <tel>:` | Llegó un mensaje de texto; si es un toque, el texto es el título del botón/fila. |
| `Mensaje no soportado (` | Llegó un tipo que el sistema no entiende (p. ej. `unsupported` o un `interactive` sin respuesta de botón/lista): típico de un toque que no se pudo resolver. |
| `Echo de app registrado para <tel>` | Eco de coexistencia: Meta avisó que un mensaje salió desde la app Business. |
| `No se pudo registrar un estado de mensaje de Meta` | Falló guardar un estado (sent/delivered/read/failed). |
| `ya procesado antes` | Meta reentregó un mensaje; el sistema lo ignoró (idempotencia). |

### Cambio opcional de código (NO aplicado; lo decide el orquestador/dueño)

Si se quiere ver el `interactivo_id`, el `contexto_id` y el código de error de un entrante sin esperar, bastaría una línea de log en
`ProveedorMeta.parsear_webhook`, por ejemplo al armar el `MensajeEntrante` de un toque:
`logger.info(f"Toque interactivo de {telefono}: id={interactivo_id} contexto={contexto_id}")`, y otra que registre `msg.get("errors")` cuando exista. Es un
cambio pequeño pero toca producción: pasaría por el ciclo normal (cambio, revisión, deploy) **antes** de la prueba, no durante.

## 7. Efectos secundarios de la prueba (para que no sorprendan)

- Los mensajes de prueba **no pasan por la capa de envíos**: no quedan en `envios_meta` ni en el chat del panel. Sus estados sí se guardan en
  `uso_mensajes_meta`, así que en el informe de conciliación de envíos aparecerán como mensajes sin reclamar ("huérfanos"). Es esperado.
- Cada mensaje dentro de la ventana de 24 h es de servicio; el costo esperado es el mismo que el de un texto, y justo eso se mide en (f).
- Si el celular de prueba es el del dueño, su lead cuenta en las métricas del panel hasta que se limpie.
