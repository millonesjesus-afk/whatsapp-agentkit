# Contrato del calendario de negocio (feriados y días especiales) — para el frontend

Versión 2026-10-12 · Fase 1 · Backend: `agent/calendario_negocio.py` (lógica pura), `agent/calendario_peru.py` (feriados de Perú),
`agent/memory.py` (tabla `dias_especiales`, CRUD, siembra), rutas en `agent/dashboard.py`.

Este documento basta para implementar la pantalla de calendario y los cambios en Inicio/campana sin leer el código del backend.
Todo lo de Inicio es **ADITIVO**: ninguna clave existente de `inicio.json` ni de `configuracion.json` cambia de nombre, tipo ni
significado. Los endpoints de horario semanal (`GET /dashboard/configuracion.json` → `horarios`, `POST /dashboard/configuracion/horario`)
**no cambian**.

## 0. Conceptos

- El horario de atención era solo semanal (`horarios`, una fila por día de la semana). Ahora el negocio puede tener **días
  especiales**: excepciones a ese horario para una fecha concreta. Una excepción **manda sobre el horario semanal**.
- Un **día** siempre es un día de Lima (America/Lima, UTC-5 fijo, sin horario de verano). `fecha` viaja como `"AAAA-MM-DD"`.
  Las demás marcas de tiempo son instantes UTC ISO 8601 con sufijo `Z` (`"2026-10-09T13:00:00.123456Z"`): mostrarlas en hora de Lima.
- Tipos (`tipo`): `feriado` · `no_laborable` · `puente` · `atencion_especial` · `cierre_propio`.
- `atiende` (bool): `false` = **cerrado todo el día**; `true` + `hora_apertura`/`hora_cierre` = **horario especial** (reducido o
  extendido; puede abrir incluso un domingo); `true` sin horas = el horario normal de ese día de la semana (solo sirve para dejar
  constancia de un día no laborable «voluntario» en el que el negocio sí atiende).
- Valor por defecto de `atiende` cuando el cuerpo no lo trae (`tipos[].atiende_por_defecto` del GET):
  `feriado` → `false` · `cierre_propio` → `false` · `no_laborable` → `true` · `puente` → `true` · `atencion_especial` → `true`.
  Razón: para el sector privado el día no laborable y el puente son **voluntarios**; el negocio solo cierra si el admin lo marca.
- **Qué hace un día cerrado**: el negocio cuenta como «fuera de horario» todo ese día. Gabi sabe el motivo y cuándo vuelven los
  asesores; la asignación automática no asigna (el lead queda derivado, sin asesor y con Gabi activa); el reloj de rotación 30+30
  no avanza; las demoras de atención (atrasada/urgente) no suman; Inicio muestra una **pausa** (sección 3).
- **Qué NO se pausa jamás**: la ventana de 24 h de WhatsApp (y su cuenta regresiva / «última llamada») y los relojes del cliente
  (reenganche de 2 h, cierre de 15 h, cierres de 5 y 7 días).
- Auth: sesión del panel (cookie). **Solo `admin` y `supervisor`** (GET, POST y DELETE); un `asesor` recibe `403`. `POST` y `DELETE`
  exigen el token CSRF en el header `X-CSRF-Token` (mismo mecanismo que el resto del panel). El negocio es **siempre el de la
  sesión**: cualquier `negocio_id` en el cuerpo se ignora. Los errores vienen en español en `detail` (`{"detail": "..."}`).
- Auditoría: toda alta, cambio, baja y carga de feriados queda en el historial de cambios (quién, con qué rol, cuándo, antes y después,
  motivo). Se lee en `GET /dashboard/configuracion/dias-especiales/historial.json`.
- Permisos del supervisor (2026-10-12): el supervisor escribe solo hacia adelante (403 en días pasados y en años no verificados) y
  tiene un límite de escrituras por hora (429). Ver `docs/contrato_calendario_supervisor.md`, que prevalece sobre esta sección en
  permisos, guardas, historial, horario de solo lectura y límite.

## 1. `GET /dashboard/configuracion/dias-especiales.json`

Query (opcional): `desde`, `hasta` (`AAAA-MM-DD`, inclusive). Por defecto desde hace 7 días hasta dentro de 365 días. `hasta` anterior
a `desde` o un rango de más de 800 días → `400`. Fecha mal escrita → `400`.

Respuesta `200`:

```jsonc
{
  "hoy": "2026-10-12",                 // día de Lima según el servidor
  "desde": "2026-10-05", "hasta": "2027-10-12",
  "dias": [ DiaEspecial, ... ],        // vivos (no eliminados), por fecha ascendente
  "estado_actual": {                   // cómo está el negocio AHORA
    "abierto": false,
    "motivo": "feriado",               // null si abierto; "fuera_de_horario" | "feriado" | "no_laborable" | "puente" | "dia_sin_atencion" | "cierre_propio"
    "nombre": "Combate de Angamos",    // nombre del día especial de hoy, o null
    "proxima_apertura": "2026-10-09T13:00:00Z",       // ISO UTC o null (no abre en las próximas 3 semanas)
    "proxima_apertura_texto": "mañana a las 8:00 a. m." // ya redactado: «hoy a las…», «mañana a las…», «el viernes 9 a las…», «el lunes 19 de octubre a las…»; "" si no hay
  },
  "cobertura": {                       // cuánto calendario hay cargado (último FERIADO cargado)
    "ultima_fecha_cargada": "2026-12-25",   // o null si no hay ningún feriado
    "dias_restantes": 74,                    // o null
    "aviso": false,                          // true si no hay feriados o faltan MENOS de 60 días → mostrar el aviso
    "mensaje": null                          // texto listo para mostrar cuando aviso == true
  },
  "anios_precargables": [              // para el botón «Cargar feriados de Perú {año}»
    { "anio": 2026, "verificado": true,  "nota": null, "total": 16, "cargados": 16 },
    { "anio": 2027, "verificado": false, "nota": "2027 no verificado: fechas calculadas, revisar cada año contra El Peruano.", "total": 16, "cargados": 0 }
  ],
  "tipos": [                           // para el selector de tipo
    { "valor": "feriado", "etiqueta": "Feriado", "atiende_por_defecto": false },
    { "valor": "no_laborable", "etiqueta": "Día no laborable", "atiende_por_defecto": true },
    { "valor": "puente", "etiqueta": "Puente", "atiende_por_defecto": true },
    { "valor": "atencion_especial", "etiqueta": "Atención especial", "atiende_por_defecto": true },
    { "valor": "cierre_propio", "etiqueta": "Cierre propio", "atiende_por_defecto": false }
  ],
  "dias_edicion_retroactiva": 7
}
```

`DiaEspecial`:

```jsonc
{
  "id": "uuid", "fecha": "2026-10-08", "dia_semana": "jueves",
  "tipo": "feriado", "nombre": "Combate de Angamos",
  "atiende": false, "hora_apertura": null, "hora_cierre": null,        // "HH:MM" o null
  "origen": "precargado_pe",          // "precargado_pe" (siembra de feriados nacionales) | "manual"
  "fuente_url": "https://www.elperuano.pe",   // o null (manual)
  "verificado": true,                 // solo origen precargado_pe: false para años sin fuente oficial verificada (2027); null en los manuales
  "pasado": false,                    // la fecha es anterior a hoy
  "requiere_motivo": false,           // true si es un día pasado de hace ≤ 7 días: cambiarlo o quitarlo exige `motivo`
  "editable": true,                   // false si pasó hace MÁS de 7 días (no se puede tocar)
  "creado": "…Z", "creado_por": "admin1", "actualizado": "…Z"
}
```

Sugerencia de UI: mostrar un chip «Sin verificar» cuando `verificado === false`; deshabilitar editar/quitar cuando `editable === false`;
pedir un campo «Motivo del cambio» (obligatorio) cuando `requiere_motivo === true`; mostrar `cobertura.mensaje` como aviso cuando
`cobertura.aviso === true`.

## 2. `POST /dashboard/configuracion/dias-especiales.json`

Cuerpo JSON (objeto). Campo `operacion` (opcional, por defecto `"guardar"`):

### 2.1 `guardar` — alta o cambio del día especial de una fecha

```jsonc
{
  "operacion": "guardar",             // opcional
  "fecha": "2026-11-20",              // obligatorio, AAAA-MM-DD, años 2020-2100
  "tipo": "no_laborable",             // obligatorio, uno de los 5
  "nombre": "Día no laborable",       // obligatorio, 1-100 caracteres
  "atiende": false,                   // opcional bool (ver defaults en la sección 0); cualquier otro tipo → 400
  "hora_apertura": "10:00", "hora_cierre": "14:00",   // opcionales "HH:MM"; solo valen con atiende == true; ambas o ninguna; apertura < cierre
  "motivo": "…"                       // texto ≤ 300; OBLIGATORIO si la fecha ya pasó (hasta 7 días atrás)
}
```

Hay **una sola fila viva por fecha**: si la fecha ya tenía un día especial, se **cambia** (no se duplica). `atencion_especial` exige
`atiende: true` con las dos horas. Con `atiende: false` las horas se ignoran.

Respuesta `200`:

```jsonc
{ "ok": true, "operacion": "guardar", "resultado": "creado" | "modificado" | "sin_cambios", "dia": DiaEspecial }
```

### 2.2 `marcar_manana_no_laborable` — atajo «Marcar mañana como no laborable»

```jsonc
{ "operacion": "marcar_manana_no_laborable", "nombre": "Paro de transporte" }   // nombre opcional (por defecto «Día no laborable»)
```

Mañana (día de Lima) queda **cerrado**. Rige en cuanto responde la petición en el proceso que la atendió y en **≤ 60 s** en el resto
(caché de 60 s). Si mañana ya tenía un día especial se conservan su tipo y su nombre y solo pasa a no atender. Respuesta igual a 2.1
(`operacion: "marcar_manana_no_laborable"`; `resultado`: `creado` | `modificado` | `sin_cambios` si ya estaba cerrado).

### 2.3 `cargar_feriados_peru` — botón «Cargar feriados de Perú {año}»

```jsonc
{ "operacion": "cargar_feriados_peru", "anio": 2026 }     // anio: entero; años disponibles en `anios_precargables`
```

Siembra los feriados nacionales del año (solo `feriado`, `atiende: false`; **nunca** días no laborables ni puentes). Es **idempotente**:
no toca una fecha que ya tenga un día especial y **vuelve a crear** los feriados que el admin había quitado (es una acción explícita).
Respuesta `200`:

```jsonc
{ "ok": true, "operacion": "cargar_feriados_peru", "anio": 2026, "verificado": true, "nota": null,
  "insertados": ["2026-11-01", "…"], "ya_existian": ["2026-01-01", "…"] }
```

`verificado: false` + `nota` (2027): lista calculada, sin fuente oficial → mostrar la nota y pedir revisarla contra El Peruano.
Un año sin lista → `400` («No hay feriados precargados para 2040. Años disponibles: 2026, 2027.»).

### Errores del POST

| status | cuándo |
|---|---|
| `400` | cuerpo que no es un objeto JSON; `operacion` desconocida; fecha/tipo/nombre/horas inválidos; `atiende` no booleano; día pasado sin `motivo`; día de hace **más de 7 días** («No se puede modificar un día de hace más de 7 días.»); año sin lista. Todo o nada: ante un `400` no se guarda nada. |
| `403` | rol `asesor`; token CSRF ausente o inválido. |
| `401/redirect` | sin sesión (igual que el resto del panel). |

## 3. `DELETE /dashboard/configuracion/dias-especiales.json?fecha=AAAA-MM-DD[&motivo=…]`

Quita (borrado lógico) el día especial de esa fecha. Sin cuerpo; `fecha` y `motivo` van en la query. Un día pasado exige `motivo` y solo
hasta 7 días atrás (mismas reglas que el POST). Un feriado precargado que se quita **no** se vuelve a crear solo (la siembra respeta lo
que el admin quitó); vuelve únicamente con `cargar_feriados_peru`.

Respuesta `200`: `{ "ok": true, "eliminado": DiaEspecial }`. Errores: `400` (sin `fecha`, fecha inválida, falta `motivo`, más de 7 días),
`403`, `404` («Esa fecha no tiene un día especial cargado.»).

## 4. Inicio: `GET /dashboard/inicio.json` (aditivo)

Con el negocio **cerrado hoy por una excepción** (feriado, día no laborable, puente o cierre propio con `atiende: false`) hay **pausa**.
Un domingo normal o la noche de un día hábil **no** son pausa (nada de eso cambia).

Claves nuevas:

```jsonc
"zona_accion": {
  …,                                     // todo lo de siempre
  "pausa": null                          // sin pausa; con pausa:
  // "pausa": { "motivo": "feriado", "nombre": "Combate de Angamos",
  //            "reanuda_en": "2026-10-09T13:00:00Z",          // ISO UTC o null
  //            "reanuda_texto": "mañana a las 8:00 a. m." }   // ya redactado
  "totales": {
    …,                                   // todo lo de siempre
    "atencion_en_pausa": 0               // int. Con pausa: cuántos clientes de la campana esperan hasta que el negocio reabra; sin pausa: 0
  }
},
"avisos": [ …, { "id": "calendario_pausa", "nivel": "info", "titulo": "Hoy es feriado: Combate de Angamos",
                 "detalle": "3 clientes esperan; se atienden mañana a las 8:00 a. m.", "enlace": null } ]
```

Cambios de valor SOLO mientras `pausa != null` (la campana debe mostrar una única entrada informativa):

- `totales.esperando_campana` vale `0` (el badge no suma «clientes esperando»; el número real está en `atencion_en_pausa`).
- `totales.atencion_campana` y `totales.atencion_campana_urgentes` cuentan **solo** las «últimas llamadas» (la ventana de 24 h de Meta es
  un reloj real que no se pausa); no suman atrasadas ni urgentes.
- `avisos` trae la entrada `calendario_pausa` (nivel `info`, sin enlace) **primero, para todos los roles** (el resto de `avisos` sigue
  siendo solo para admin). Es la entrada informativa de la campana: «Hoy es feriado: Combate de Angamos» /
  «N clientes esperan; se atienden mañana a las 8:00 a. m.» (con 0: «No hay clientes esperando; la atención se retoma así: …»).
- Cada `items[].atencion` trae `"en_pausa": true` (clave que **no existe** sin pausa). Siguen mostrando su `nivel`, `edad_horas` y
  `ventana_restante_horas`; las demoras de un día cerrado simplemente no suman.

Sin pausa, `inicio.json` es idéntico al de antes salvo `zona_accion.pausa: null` y `totales.atencion_en_pausa: 0`.

## 5. Umbrales de atención atrasada en horas hábiles (sin cambios de API)

El tiempo «hábil» excluye noches, domingos, feriados y días especiales cerrados. `items[].atencion.nivel` (`atrasada` / `urgente` /
`ultima_llamada` / `ventana_cerrada`) y `edad_horas` siguen igual; solo cambia **cuándo** se alcanza cada nivel:

- Sin la clave `calendario_habil_desde` en la configuración del negocio: `atrasada` = 2 h hábiles; `urgente` = 8 h de reloj **y** atrasada
  (como siempre).
- Con `calendario_habil_desde` = `AAAA-MM-DD` (día de Lima) **ya llegado**: `atrasada` = 2 h hábiles (`atencion_atrasada_horas_habiles`) y
  `urgente` = **4 h hábiles** (`atencion_urgente_horas_habiles`). `ultima_llamada` y `ventana_restante_horas` siguen en reloj.

La clave se fija al desplegar con `python scripts/sembrar_calendario.py --fijar-habil-desde hoy` (no hay endpoint).

## 6. Claves de configuración nuevas (por negocio, tabla `configuracion`; sin pantalla en esta fase)

| clave | por defecto | efecto |
|---|---|---|
| `calendario_habil_desde` | ausente | fecha desde la que rigen los umbrales hábiles (sección 5) |
| `atencion_atrasada_horas_habiles` | `2` | horas hábiles para «atrasada» en modo hábil |
| `atencion_urgente_horas_habiles` | `4` | horas hábiles para «urgente» en modo hábil |
| `cola_apertura_max_activos_por_asesor` | `0` (sin límite) | al repartir la cola al abrir, un asesor con N o más casos activos no recibe más |
| `rotacion_reloj_max_casos_por_asesor` | `0` (comportamiento de siempre) | con N > 0, solo los N casos más antiguos de cada asesor corren el reloj de 30 min; los demás esperan «en fila» |
