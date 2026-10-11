# Contrato de "Para llamar" (tareas de llamada) — para el frontend

Versión 2026-10-11 · Backend: `agent/llamadas.py`, rutas en `agent/dashboard.py` · Diseño D3 aprobado por el dueño (2026-10-08).

Cambios de la versión 2026-10-11 (todos ADITIVOS salvo el efecto de «agendado»): Gabi entiende la respuesta del cliente a la oferta de llamada (sección 7), la `Tarea` trae `aceptada_por_cliente`, la configuración trae `respuesta_haiku`, hay dos eventos nuevos del Timeline (sección 5) y `contesto_agendado` ahora también asigna el lead (sección 2.1).

Este documento basta para implementar el frontend sin leer el código del backend. Todo el módulo viene **APAGADO**: con la
configuración por defecto, `GET /dashboard/llamadas.json` devuelve `tareas: []` y no cambia nada de lo que ya existe.

## 0. Conceptos

- Una **tarea de llamada** es una tarea *superpuesta* a la conversación de un lead callado que mostró interés. **No** es una
  etapa del Pipeline, ni un resultado, ni un estado de Gabi: Gabi sigue activa mientras la tarea está abierta. El asesor vive
  en la **tarea** (`asesor`), no en el lead: asignar la tarea no pausa a Gabi ni cambia `asesor_asignado` del lead.
- Modos efectivos (`modo`): `apagado` (módulo apagado) · `sombra` (se registran tareas para medir; nadie las ve) · `activo`
  (tareas visibles y repartidas). **El frontend solo ve tareas cuando `modo == "activo"`**. `activo` exige además la
  **aceptación de responsabilidad vigente** (sección 4); sin ella el modo efectivo es `sombra` aunque se haya configurado `activo`.
- Las tareas del **grupo de control** (holdout) y las de **sombra** existen en la base pero **nunca** salen por ninguna ruta de
  este documento (ni en el listado, ni en Inicio, ni se pueden operar).
- Todas las fechas/horas son instantes UTC serializados ISO 8601 con sufijo `Z` (`"2026-10-09T15:30:00.123456Z"`), salvo la
  `hora` que el frontend **envía** en `contesto_llamar_luego` (ver 2.1). Mostrar siempre en America/Lima (UTC-5, sin horario de verano).
- Auth: sesión del panel (cookie). Todo `POST` exige el token CSRF (header `X-CSRF-Token`, mismo mecanismo que el resto del panel)
  y cuerpo `application/json`. Los textos de error vienen en español en `detail`.

### Estados de la tarea (`estado`)

| estado | significado |
|---|---|
| `programada` | aún no accionable: se creó fuera del horario de atención (`programada_para` = próxima apertura) o es una llamada reprogramada (`programada_para` = hora acordada / próximo intento). Pasa sola a `pendiente` cuando llega su hora y el negocio está abierto. |
| `pendiente` | accionable ahora. Con `asesor` (asignada) o `asesor: null` (esperando que haya un asesor disponible). |
| `cumplida` | la llamada conectó y se resolvió (`motivo_cierre` = el resultado: `contesto_sigo_yo`, `contesto_agendado`, `contesto_no_interesado`, `numero_errado`, `no_llamar`). |
| `agotada` | se alcanzaron `max_intentos` llamadas sin contacto (`motivo_cierre: "sin_contacto"`); el lead se cerró como `sin_respuesta`. |
| `cancelada` | dejó de corresponder. `motivo_cierre`: `respondio_cliente` (el cliente volvió a escribir), `paso_a_humano` (una persona tomó el caso), `lead_cerrado` (ya tiene resultado o está cerrado), `conversacion_cerrada`, `no_llamar` (la persona pidió que no la llamen, p. ej. respondiendo a la oferta), `compuerta_cerrada` (se apagó el módulo / se revocó la aceptación), `descartada_supervisor`. **Excepción**: una tarea con `aceptada_por_cliente: true` NO se cancela por `respondio_cliente` (ver sección 7). |
| `expirada` | superó `llamadas_vida_max_dias` (`motivo_cierre: "vida_maxima"`). |

`segmento`: `"A"` (puntaje ≥ 6), `"B"` (≥ puntaje mínimo), `"exploracion"` (muestra pequeña de puntaje 2-3; apagada por defecto).

## 1. `GET /dashboard/llamadas.json`

Roles: cualquier usuario con sesión. **Asesor**: solo las tareas donde `asesor == su username`. **Admin / supervisor**: todas, más el
bloque `medicion`.

Query: `estado` = `abiertas` (default: `programada` + `pendiente`) · `cerradas` (cumplida/agotada/cancelada/expirada de los últimos 7 días, máx. 100) · `todas`. Otro valor → `400`.

El listado **revalida** las tareas abiertas: si el lead dejó de ser elegible (el cliente escribió, pasó a una persona…) la tarea se cancela y ya no aparece.

Respuesta `200`:

```jsonc
{
  "modo": "apagado" | "sombra" | "activo",   // modo efectivo
  "activo": false,                           // true solo si modo == "activo"
  "tareas": [ Tarea, ... ],                  // [] si activo == false. Orden: pendientes primero, luego programadas; dentro, mayor puntaje primero
  "kpi": {
    "pendientes": 0,        // int, tareas abiertas con estado "pendiente" (del usuario si es asesor; del negocio si admin/supervisor)
    "programadas": 0,       // int
    "sin_asignar": 0,       // int, abiertas con asesor null
    "vencidas": 0,          // int, abiertas asignadas que superaron el SLA (llamadas_sla_horas_habiles hábiles) o están "sin hacer"
    "sin_hacer": 0,         // int, abiertas escaladas al supervisor (ya se reasignó una vez y siguen sin hacerse)
    "llamadas_registradas": 0,   // int, tareas de los últimos 30 días con un resultado de llamada registrado
    "contactos": 0,         // int, de esas, las que contestaron (todo resultado salvo no_contesto y numero_errado)
    "tasa_contacto": null,  // number 0..1 con 3 decimales, o null si no hay llamadas registradas
    "ventana_dias": 30
  },
  "medicion": {             // SOLO admin/supervisor y solo con modo "activo"
    "dias": 30, "tareas": 0,
    "por_modo": {"sombra": 0, "activo": 0}, "por_grupo": {"llamar": 0, "control": 0},
    "por_segmento": {"A": 0, "B": 0}, "por_estado": {"pendiente": 0}   // solo claves con valor > 0
  }
}
```

### `Tarea`

```jsonc
{
  "id": "uuid", "conversation_id": "uuid", "telefono": "51987654321",
  "nombre": "Ana" | null,                 // null si no se conoce
  "producto": "terma de 80 litros" | null,
  "estado": "pendiente",                  // ver tabla
  "motivo_cierre": null,                  // string si estado es cumplida/agotada/cancelada/expirada
  "segmento": "A", "puntaje": 12,         // int 0..12
  "senales": {                            // por qué puntuó (sin texto de mensajes). Solo para mostrar chips.
    "mensajes_cliente": 2, "prellenado": false, "silencio_horas": 6.0,
    "pidio_dni_o_financiamiento": true, "dio_precio": true, "producto_conocido": true, "nombre_conocido": true,
    "paso_flujo": "comparando_producto" | null,
    "puntos": {"mensajes_cliente": 3, "datos_o_financiamiento": 3, "precio": 2, "producto": 2, "nombre": 1, "paso": 1}
  },
  "asesor": "ana" | null,                 // username
  "asesor_nombre": "Ana" | null,
  "asignada_en": "…Z" | null,
  "programada_para": "…Z" | null,         // cuándo se vuelve accionable (programada)
  "intentos": 0,                          // llamadas que NO conectaron (no_contesto)
  "max_intentos": 3,
  "ultimo_intento_en": "…Z" | null,
  "proximo_intento_en": "…Z" | null,      // en reintentos y "llamar luego"
  "resultado_llamada": null,              // último resultado registrado (ver 2.1)
  "nota": null,                           // string (≤ 500) o null
  "vencida": false,                       // abierta, asignada y pasó el SLA, o sin_hacer
  "sin_hacer": false,                     // escalada al supervisor
  "reasignaciones": 0,                    // 0 o 1 (la reasignación automática por SLA)
  "creada_en": "…Z", "cerrada_en": null, "vence_en": "…Z",
  "aceptada_por_cliente": false           // true si el cliente aceptó la llamada (o pidió una hora) respondiendo a la oferta de Gabi; ver 7
}
```

Para abrir el chat del lead usa `conversation_id` (misma navegación que Inicio).

## 2. Acciones sobre una tarea

Errores comunes: `400` dato inválido · `403` no es tu tarea (asesor sobre tarea ajena) · `404` la tarea no existe, es de otro
negocio, es de sombra o de control · `409` la tarea ya está cerrada, o el módulo no está en modo `activo`.
El `detail` es un texto en español para mostrar tal cual.

### 2.1 `POST /dashboard/llamadas/{tarea_id}/resultado`

Roles: el **asesor dueño** de la tarea, o supervisor/admin sobre cualquiera.

```jsonc
// request
{ "resultado": "no_contesto",     // obligatorio, uno de los 7 de la tabla
  "nota": "Sonó apagado",         // opcional, ≤ 500 caracteres
  "hora": "2026-10-10T15:30" }    // SOLO y obligatorio con "contesto_llamar_luego"
// response 200
{ "ok": true,
  "tarea": Tarea,                 // ya actualizada
  "accion": "ninguna" | "abrir_agendar",
  "conversation_id": "uuid" }
```

`hora` es **hora de Lima** sin zona (`AAAA-MM-DDTHH:MM`, como el campo de cita); si lleva `Z` u offset (`+hh:mm`) se convierte. Debe ser futura y no superar `vence_en` de la tarea (si no → `400`).

| `resultado` | efecto en la tarea | efecto en el lead |
|---|---|---|
| `contesto_sigo_yo` | `cumplida` | se asigna el lead al asesor de la tarea (o a quien registra, si la tarea no tiene asesor) → **Gabi se pausa**; queda el evento `asignado`. |
| `contesto_agendado` | `cumplida`; `accion: "abrir_agendar"` | **se asigna el lead al asesor de la tarea** (o a quien registra, si la tarea no tiene asesor) → **Gabi se pausa**, igual que `contesto_sigo_yo`; queda el evento `asignado` (`payload.origen == "llamada"`). Además **el frontend debe abrir el formulario de agendar existente** de la conversación (`conversation_id`). Así, si el asesor cierra el formulario sin guardar, Gabi no sigue conversando con quien ya acordó una cita. (Cambio 2026-10-11: antes no asignaba.) |
| `contesto_no_interesado` | `cumplida` | resultado `no_interesado`. |
| `contesto_llamar_luego` | `programada` para `hora`; **no** suma intento | ninguno. |
| `no_contesto` | `intentos + 1`; si llega a `max_intentos` → `agotada`; si no → `programada` en **otra franja** (mañana/tarde) y ≥ 3 h después, dentro del horario | al agotarse: resultado `sin_respuesta` (cierre silencioso de siempre). |
| `numero_errado` | `cumplida` | resultado `otro`. |
| `no_llamar` | `cumplida` | marca al contacto "no llamar" (nunca más se le crea una tarea) y resultado `no_interesado`. |

Si el contacto pidió "no llamar" antes de registrar, la tarea se cancela y responde `409` ("Esta persona pidió que no la llamen").

### 2.2 `POST /dashboard/llamadas/{tarea_id}/reasignar`

Roles: **supervisor, admin**. `{ "asesor": "beto" | null }` — `null` devuelve la tarea al reparto automático. El asesor debe existir y estar activo (si no → `400`). Respuesta `200`: `{ "ok": true, "tarea": Tarea }`. Quita la marca "sin hacer".

### 2.3 `POST /dashboard/llamadas/{tarea_id}/descartar`

Roles: **supervisor, admin**. `{ "nota": "…" }` opcional (≤ 500). La tarea pasa a `cancelada` (`motivo_cierre: "descartada_supervisor"`); no toca el lead. Respuesta `200`: `{ "ok": true, "tarea": Tarea }`.

## 3. Inicio — `GET /dashboard/inicio.json` (contrato ADITIVO)

Nada de lo existente cambia. Se agregan:

- `zona_accion.items[]`: ítems con `categoria: "llamar"` (máx. **5**, vencidas primero, luego mayor puntaje). Solo tareas `pendiente` del usuario (asesor) o de todo el negocio (admin/supervisor). Campos: los de siempre (`telefono`, `conversation_id`, `nombre`, `motivo`, `categoria`) más
  `tarea_id` (string), `segmento` (`"A"|"B"|"exploracion"`), `vencida` (bool), `asesor` (string|null), `programada_para` (string|null).
  `motivo` = `"Para llamar"` o `"Para llamar — sin hacer a tiempo"` (si `vencida`).
- `zona_accion.totales.llamadas_pendientes` (int) y `zona_accion.totales.llamadas_vencidas` (int): **siempre presentes**, valen `0` con el módulo apagado/sombra.
- `avisos[]`: para **supervisor y admin**, y solo si hay llamadas vencidas, un aviso
  `{ "id": "llamadas-vencidas", "nivel": "warning", "titulo": "N llamada(s) sin hacer a tiempo", "detalle": "…", "enlace": null }`. Los asesores nunca lo ven. (Los avisos de admin existentes —IA, procesos, uso— siguen igual; este va al final.)

`zona_accion.vacio` es `false` si solo hay ítems `llamar`.

## 4. Configuración — `GET|POST /dashboard/configuracion/llamadas.json`

Solo **admin**. Siempre del negocio de la sesión.

### GET → `200`

```jsonc
{
  "gabi_activo": false,                // llamadas_gabi_activo
  "modo": "sombra",                    // configurado: "sombra" | "activo"
  "modo_efectivo": "apagado",          // "apagado" | "sombra" | "activo"
  "motivo_degradado": null,            // "sin_aceptacion_de_responsabilidad" si modo=activo pero no hay aceptación vigente
  "horas_silencio": 4.0, "puntaje_minimo": 4, "exploracion_pct": 0.0, "holdout_pct": 30.0,
  "max_intentos": 3, "sla_horas_habiles": 2.0, "vida_max_dias": 3.0,
  "oferta_activa": false,
  "oferta_texto": null,                // null = usa el texto por defecto
  "oferta_texto_por_defecto": "Hola {nombre}, soy Gabi. …",
  "respuesta_haiku": false,            // llamadas_respuesta_haiku: un clasificador barato (Haiku) interpreta las respuestas AMBIGUAS a la oferta
  "responsabilidad": {
    "texto": "Declaro que la empresa cuenta con la base legal …",   // mostrar TAL CUAL al pedir la aceptación
    "version_texto": "v1",
    "aceptada_vigente": false,         // aceptación hecha sobre la versión actual del texto
    "aceptada_por": null, "aceptada_en": null, "version_aceptada": null,
    "revocada_por": null, "revocada_en": null
  },
  "advertencias": []                   // strings; p. ej. si horas_silencio >= 15
}
```

### POST

Cuerpo JSON con **cualquier subconjunto** de los campos; **todo o nada** (un campo inválido o desconocido → `400` y no se guarda nada). Respuesta `200`: `{ "ok": true, …mismo objeto del GET }`.

| campo | tipo | validación | default | clave en `configuracion` |
|---|---|---|---|---|
| `gabi_activo` | boolean | exacto `true`/`false` | `false` | `llamadas_gabi_activo` (`"1"`/`"0"`) |
| `modo` | string | `"sombra"` o `"activo"` | `"sombra"` | `llamadas_modo` |
| `horas_silencio` | number | 1 – 72 | 4 | `llamadas_horas_silencio` |
| `puntaje_minimo` | integer | 1 – 12 | 4 | `llamadas_puntaje_minimo` |
| `exploracion_pct` | number | 0 – 100 | 0 | `llamadas_exploracion_pct` |
| `holdout_pct` | number | 0 – 100 | 30 | `llamadas_holdout_pct` |
| `max_intentos` | integer | 1 – 10 | 3 | `llamadas_max_intentos` |
| `sla_horas_habiles` | number | 0.5 – 24 | 2 | `llamadas_sla_horas_habiles` |
| `vida_max_dias` | number | 1 – 14 | 3 | `llamadas_vida_max_dias` |
| `oferta_activa` | boolean | | `false` | `llamadas_oferta_activa` |
| `respuesta_haiku` | boolean | exacto `true`/`false` | `false` | `llamadas_respuesta_haiku` (`"1"`/`"0"`) |
| `oferta_texto` | string \| null | ≤ 600 caracteres; debe mencionar la llamada **y** cómo no recibirla ("si prefieres que no te llamemos…"); `""`/`null` vuelve al texto por defecto. Variables `{nombre}`, `{producto}` | null | `llamadas_oferta_texto` |
| `aceptar_responsabilidad` | boolean | si es `true` exige `version_texto` igual a la versión vigente (`400` si no) | — | `llamadas_responsabilidad_aceptada` |
| `version_texto` | string | solo junto a `aceptar_responsabilidad` | — | |
| `revocar_responsabilidad` | boolean | no puede ir junto con `aceptar_responsabilidad: true` | — | |

Notas:
- **Compuerta de responsabilidad**: el texto (`responsabilidad.texto`, versión `v1`) lo acepta un admin con `{ "aceptar_responsabilidad": true, "version_texto": "v1" }`; queda registrado con usuario y fecha (también en la auditoría). Mientras no haya aceptación vigente, `modo: "activo"` se guarda pero el módulo funciona como `sombra` (`modo_efectivo`, `motivo_degradado`). Si el texto cambia de versión, la aceptación anterior deja de ser vigente.
- `{ "revocar_responsabilidad": true }` apaga el modo activo (`modo` vuelve a `"sombra"`) y **cancela al instante** las tareas abiertas. Pasar `gabi_activo: false` o `modo: "sombra"` también cancela las tareas abiertas de modo activo.
- Un `horas_silencio` ≥ 15 casi no producirá tareas (el cierre automático de 15 h cierra el lead antes): el GET lo avisa en `advertencias`.
- El texto de la oferta solo se envía con `modo_efectivo == "activo"` **y** `oferta_activa == true`, y solo a segmentos A/B con la ventana de 24 h de WhatsApp abierta. Desde 2026-10-11 Gabi **sí** interpreta la primera respuesta del cliente a la oferta ("sí", una hora, "no me llamen"): ver la sección 7. Si la respuesta es otra cosa, la tarea se cancela por respuesta y sigue Gabi, como antes.
- `respuesta_haiku` solo afecta a las respuestas que las reglas no logran clasificar (ni pregunta, ni número de teléfono, ni negación): una llamada a Haiku con timeout de 4 s, del orden de US$ 0.0004. Cualquier fallo se trata como «otro». Viene apagado.

## 5. Eventos del Timeline

Se guardan en la conversación (tabla `eventos_lead`); `GET` del detalle/Timeline entrega solo los **visibles**:

| `tipo` | visible en el Timeline | cuándo | `payload` |
|---|---|---|---|
| `llamada_registrada` | sí | cada resultado registrado | `{tarea_id, resultado, nota, intento?}` |
| `llamada_reprogramada` | sí | `contesto_llamar_luego` / `no_contesto` con reintentos | `{tarea_id, resultado, nota, nueva_hora}` |
| `llamada_agotada_sin_contacto` | sí | se agotaron los intentos | `{tarea_id, resultado, nota, intento, intentos}` |
| `llamada_oferta_enviada` | sí | Gabi ofreció la llamada (evidencia) | `{segmento, puntaje, texto}` |
| `llamada_aceptada_por_cliente` | sí | el cliente aceptó o pidió una hora respondiendo a la oferta (evidencia del consentimiento). `descripcion`: «El cliente aceptó la llamada» | `{tarea_id, intencion: "acepta"\|"hora", texto (literal del cliente, ≤ 300), mensaje_id, capa: "reglas"\|"haiku", programada_para (ISO Z\|null), cuando (texto mostrado al cliente), oferta_evento_id}` |
| `llamada_rechazada_por_cliente` | sí | el cliente pidió que no lo llamen (evidencia). `descripcion`: «El cliente pidió que no lo llamen» | `{texto (literal), mensaje_id, capa, primera_respuesta: bool, confirmar: bool, tarea_id\|null, oferta_evento_id\|null}` |
| `llamada_pendiente_creada` | no (interno) | se creó la tarea | `{tarea_id, segmento, puntaje, grupo, modo}` |
| `llamada_asignada` | no | reparto, reasignación (SLA o manual) | `{tarea_id, anterior, nuevo, motivo: "reparto"\|"sla"\|"manual"}` |
| `llamada_cancelada_por_respuesta` | no | cualquier cancelación | `{tarea_id, motivo, …}` |
| `llamada_expirada` | no | venció la vida máxima | `{tarea_id}` |
| `llamada_escalada_supervision` | no | quedó "sin hacer" | `{tarea_id, asesor, reasignaciones}` |

Los resultados que cambian el caso dejan además los eventos de siempre (`asignado`, `resultado_cambiado`, con `payload.origen == "llamada"`).
Para el frontend, los tipos `llamada_*` visibles pueden mostrarse con un ícono de teléfono; `descripcion` ya viene redactada en español.

## 6. Comportamiento que el frontend debe conocer

- Las tareas se crean con un Cron cada 15 min; una tarea nueva puede tardar hasta 15 min en aparecer. Conviene refrescar el listado al abrir la pantalla y periódicamente (o al recibir el aviso en tiempo real de la bandeja).
- Una tarea desaparece de `abiertas` (pasa a `cancelada`) cuando el cliente vuelve a escribir: mostrar la tarea como "ya respondió" si el usuario la tenía abierta y el `POST resultado` devuelve `409`.
- Fuera del horario de atención no hay tareas `pendiente` nuevas: aparecen `programada` (con `programada_para`) y se activan solas al abrir.
- Cada lead tiene a lo sumo **una** tarea por ciclo de conversación (si ya la hubo, aunque esté cerrada, no se crea otra).
- Una tarea con `aceptada_por_cliente: true` sigue abierta aunque el cliente siga escribiendo (el webhook y la revalidación no la cancelan por `respondio_cliente`); solo se cancela si una persona toma el caso, el lead se cierra, o el cliente pide no ser llamado.
- Nunca mostrar `senales` como texto del cliente: son banderas/cifras (sin PII adicional al teléfono y nombre).

## 7. Respuesta del cliente a la oferta de llamada (2026-10-11)

Solo ocurre si la oferta de Gabi salió (`llamadas_oferta_activa` + modo efectivo `activo`). El frontend **no llama a nada nuevo**: lo único visible
es la tarea (con `aceptada_por_cliente`), los dos eventos del Timeline y los textos de Gabi en el chat.

**Qué se interpreta.** La PRIMERA respuesta de texto del cliente tras la oferta (reacciones y adjuntos no cuentan; el eco desde el celular tampoco),
dentro de las **24 h** posteriores a la oferta y **una sola vez por oferta**. Reglas deterministas; Haiku solo si `respuesta_haiku` y la respuesta es ambigua.

| La respuesta es… | Ejemplos | Efecto |
|---|---|---|
| **acepta** | «sí», «claro», «ok», «dale», «por favor», «está bien», «ahora», «cuando puedan» | La tarea queda `pendiente` (lo antes posible) o `programada` (si el negocio está cerrado: la próxima apertura). |
| **da una hora** | «a las 3», «3pm», «después de las 5», «mañana», «en la tarde/noche/mañana», «hoy», «en 2 horas» | La tarea queda `programada` para esa hora **dentro de `HorarioAtencion`** (si pidió fuera de horario → próxima apertura; si la hora ya pasó hoy → mañana). |
| **rechaza** | «no me llamen», «no quiero llamadas», «prefiero por escrito/por aquí», «no gracias», «no me interesa», «no» | `Contact.no_llamar_en` = ahora (nunca más se le crea tarea ni oferta), tarea cancelada (`motivo_cierre: "no_llamar"`). |
| **otro** | «sí, ¿cuánto cuesta?», «gracias», cualquier pregunta, un teléfono distinto | Nada nuevo: la tarea se cancela por respuesta y sigue Gabi (comportamiento anterior). |

**Efectos al aceptar o dar hora.** Se toma la tarea abierta del lead (si el Cron aún no la había creado, se **crea** en ese momento, ya en modo `activo`, grupo `llamar`
y con el segmento/puntaje de la oferta), se le pone `aceptada_por_cliente: true` en `senales` y se deja el evento visible `llamada_aceptada_por_cliente` con el texto
literal del cliente. La asigna el reparto normal (Cron de 15 min). El SLA corre desde que el cliente la pidió. Gabi responde **un texto fijo** (sin IA, origen de envío
`gabi_confirma_llamada`, esencial) y **no conversa encima** en ese turno:
`Perfecto, {nombre}. Un asesor te llamará {cuando}. Si cambias de idea, avísame por aquí.` con `{cuando}` = «en breve» · «hoy alrededor de las 3 p. m.» ·
«mañana a partir de las 9 a. m.» · «el lunes a partir de las 9 a. m.». Si el texto no sale (Meta lo rechaza o la política lo frena), el turno sigue con Gabi como siempre,
pero la tarea ya quedó programada.

**Efectos al rechazar.** `no_llamar_en`, tareas abiertas canceladas, evento visible `llamada_rechazada_por_cliente` y, si el mensaje es solo el rechazo, el texto fijo
`Listo, {nombre}, no te llamaremos. Seguimos por aquí por WhatsApp si lo necesitas.`; los siguientes mensajes los atiende Gabi con normalidad. Si el mensaje trae
además otra cosa (p. ej. una pregunta) el rechazo se registra igual pero no se manda el texto fijo: contesta Gabi.

**Compuerta.** Aceptar o dar una hora exige el modo efectivo `activo` (aceptación legal vigente); sin ella no se programa nada. **El rechazo se registra siempre**,
aunque el módulo esté en sombra o apagado. Un rechazo en un mensaje POSTERIOR al primero también marca `no_llamar_en` mientras haya una tarea abierta (la aceptada por
el cliente) o antes de que exista la tarea (oferta enviada, sin tarea aún); un «no me llamen» explícito marca al contacto aunque no haya habido oferta si el módulo está encendido.

**Idempotencia.** Por `mensaje_id`: un reintento del mismo mensaje no repite el efecto (se vuelve a mandar la misma confirmación). Una segunda respuesta («mejor a las 4») ya no se interpreta:
el asesor la ve en el chat.
