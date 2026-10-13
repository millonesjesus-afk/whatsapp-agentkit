# Contrato del calendario para el supervisor (permisos, historial, horario de solo lectura) — para el frontend

Versión 2026-10-12 · Backend: `agent/dashboard.py` (rutas, guardas, límite, aviso), `agent/memory.py` (auditoría, historial,
conteo de escrituras). Complementa `docs/contrato_calendario_negocio.md` (que sigue vigente: el GET/POST/DELETE de
`/dashboard/configuracion/dias-especiales.json` **no cambia de forma**; solo ganó las guardas y el límite de las secciones 3 y 4).

Decisiones del dueño que implementa (2026-10-12): D1 el supervisor gestiona el calendario (lee siempre, escribe hacia adelante) ·
D2 enmienda al MPA §8/§9 · D3 uso/costos de Meta solo admin · D4 sin editar días pasados · D5 sin cargar feriados de años no
verificados · D6 exportación de leads auditada · D7 aviso al admin + límite de 20 escrituras por hora · D8 la medición de llamadas
la ve el supervisor.

## 1. Qué ve y qué puede cada rol

| | admin | supervisor | asesor |
|---|---|---|---|
| Capacidades en `GET /dashboard/sesion` | `calendario:ver`, `calendario:editar`, `configuracion:ver`, … | `calendario:ver`, `calendario:editar` (**sin** `configuracion:ver`) | ninguna de las dos |
| Leer días especiales, estado y cobertura (`GET …/dias-especiales.json`) | sí | sí | 403 |
| Leer el horario semanal (`GET /dashboard/calendario/horario.json`, solo lectura) | sí | sí | 403 |
| Leer el historial del calendario (`GET …/dias-especiales/historial.json`) | sí | sí | 403 |
| Crear / cambiar / quitar un día **de hoy o futuro** | sí | sí | 403 |
| Cambiar / quitar un día **pasado** (hasta 7 días, con motivo) | sí | **403** | 403 |
| «Marcar mañana como no laborable» | sí | sí | 403 |
| «Cargar feriados de Perú {año}» con año **verificado** (2026) | sí | sí | 403 |
| «Cargar feriados de Perú {año}» con año **no verificado** (2027) | sí | **403** | 403 |
| Cambiar el horario semanal (`POST /dashboard/configuracion/horario`) | sí | **403** | 403 |
| Configuración (`configuracion.json`, financiamiento, Gabi, canales, Equipo, Asesores…) | sí | **403** | 403 |
| Uso y costos de Meta (`uso-mensajes.json`, `uso-mensajes/envios.json`) | sí | **403** (antes sí) | 403 |
| Historial de Configuración (`uso-mensajes/historial-cambios.json`) | sí (ahora incluye el calendario) | 403 | 403 |
| Aviso «el supervisor cambió el calendario» en `inicio.json` | sí | no | no |
| `medicion` en `GET /dashboard/llamadas.json` (D8) | sí | sí | no (clave ausente) |

Todo es del **negocio de la sesión**: un `negocio_id` en el cuerpo o en la query se ignora. El control de acceso es `requiere_rol`
en cada ruta; las capacidades de `/dashboard/sesion` solo sirven para pintar u ocultar (un cliente que mienta igual recibe 403).
Los `POST`/`DELETE` exigen el header `X-CSRF-Token` (sin token o con token inválido: `403`).

## 2. Los dos endpoints nuevos

### 2.1 `GET /dashboard/calendario/horario.json` — horario semanal, solo lectura (admin y supervisor)

Sin parámetros. No escribe nada; la escritura sigue siendo `POST /dashboard/configuracion/horario` (solo admin).

```jsonc
{
  "hoy": "2026-10-12",                // día de Lima
  "solo_lectura": true,               // siempre true: el cliente puede usarlo para deshabilitar controles
  "dias": [                           // SIEMPRE 7 entradas, lunes (0) a domingo (6)
    { "dia_semana": 0, "nombre": "lunes", "habilitado": true,
      "hora_apertura": "08:00", "hora_cierre": "19:00",     // "HH:MM" o null si no atiende ese día
      "es_por_defecto": false }                              // true = el negocio nunca configuró ese día; rige lunes a sábado 8:00-19:00
    // …
  ],
  "estado_actual": {                  // mismo objeto que `estado_actual` de dias-especiales.json (feriados y días especiales incluidos)
    "abierto": false, "motivo": "feriado",   // null si abierto; "fuera_de_horario" | "feriado" | "no_laborable" | "puente" | "dia_sin_atencion" | "cierre_propio"
    "nombre": "Combate de Angamos",          // nombre del día especial de hoy, o null
    "proxima_apertura": "2026-10-09T13:00:00Z",        // ISO UTC o null
    "proxima_apertura_texto": "mañana a las 8:00 a. m." // ya redactado; "" si no hay
  }
}
```

Errores: `403` (asesor).

### 2.2 `GET /dashboard/configuracion/dias-especiales/historial.json` — historial legible (admin y supervisor)

Query (opcional): `limite` (1-200, por defecto 100; fuera de rango → `400` «`limite` debe estar entre 1 y 200.»), `antes_de` (el
`fecha_hora` del último ítem recibido, para pedir la página siguiente; fecha ISO 8601 inválida → `400`).

```jsonc
{
  "items": [                          // más reciente primero
    {
      "fecha_hora": "2026-10-12T15:04:05.123456Z",   // instante UTC (mostrar en hora de Lima)
      "actor": "ana",                                  // username de quien lo hizo (null si fue un proceso sin usuario)
      "actor_rol": "supervisor",                       // "admin" | "supervisor" | null (filas anteriores al 2026-10-12, o scripts)
      "accion": "dia_especial_modificado",             // ver la tabla de acciones
      "fecha_dia": "2026-11-20",                       // el día del calendario afectado; null en feriados_cargados y habil_desde
      "antes":  { "fecha": "2026-11-20", "tipo": "no_laborable", "nombre": "…", "atiende": true,  "hora_apertura": null, "hora_cierre": null },
      "despues":{ "fecha": "2026-11-20", "tipo": "no_laborable", "nombre": "…", "atiende": false, "hora_apertura": null, "hora_cierre": null },
      "motivo": "Lo declararon tarde"                  // texto o null
    }
  ],
  "hay_mas": false                    // true si hay filas anteriores: repetir con antes_de = items[-1].fecha_hora
}
```

| `accion` | `antes` | `despues` | `fecha_dia` |
|---|---|---|---|
| `dia_especial_creado` | `null` | resumen del día | la fecha del día |
| `dia_especial_modificado` | resumen anterior | resumen nuevo | la fecha del día |
| `dia_especial_eliminado` | resumen del día quitado | `null` | la fecha del día |
| `calendario_feriados_cargados` | `null` | `{ "anio": 2026, "insertados": ["2026-11-01", …], "verificado": true }` | `null` |
| `calendario_habil_desde` | fecha anterior (texto `"AAAA-MM-DD"`) o `null` | fecha nueva (texto) o `null` | `null` |

«Resumen del día» = `{ fecha, tipo, nombre, atiende, hora_apertura, hora_cierre }`. Solo filas del negocio de la sesión.
El historial se lee de la auditoría (`RegistroAuditoria`, append-only): no hay tabla nueva. Errores: `400` (parámetros), `403` (asesor).

### 2.3 El historial de Configuración del admin ahora incluye el calendario

`GET /dashboard/uso-mensajes/historial-cambios.json` (solo admin) devuelve, además de lo de siempre, las mismas filas del
calendario en la forma que ya consume `lib/uso-formato.ts`: `cambios: { "<accion>": { "antes": "<texto>", "despues": "<texto>" } }`
con `antes`/`despues` como **texto JSON** del resumen y el `motivo` **dentro** de ese JSON (`dia_especial_creado` y
`dia_especial_modificado` lo llevan en `despues`; `dia_especial_eliminado`, en `antes`). Las acciones son exactamente
`dia_especial_creado`, `dia_especial_modificado`, `dia_especial_eliminado`, `calendario_feriados_cargados` (`despues` =
`{"anio":…,"insertados":[…],"verificado":…}`) y `calendario_habil_desde` (`antes`/`despues` = la fecha como texto, no JSON). Las
filas de configuración de siempre no cambian.

## 3. Guardas y errores nuevos de `POST`/`DELETE …/dias-especiales.json`

Todos con `{"detail": "<mensaje en español>"}`. Las guardas aplican a quien **no es admin** (hoy, el supervisor) y se evalúan
después de validar que el cuerpo es un objeto y que `operacion` existe, y **antes** del resto de validaciones y del límite.

| status | cuándo | `detail` |
|---|---|---|
| `403` | `guardar` o `DELETE` sobre una fecha **anterior a hoy** (día de Lima), con o sin `motivo`, sea cual sea su antigüedad | `Solo un administrador puede cambiar o quitar un día que ya pasó.` |
| `403` | `cargar_feriados_peru` de un año de `anios_precargables` con `verificado: false` (hoy 2027) | `Los feriados de 2027 todavía no están verificados con la fuente oficial. Solo un administrador puede cargarlos.` |
| `429` | el usuario ya hizo el máximo de escrituras en la última hora (sección 4) | `Hiciste 20 cambios al calendario en la última hora, que es el máximo permitido. Podrás hacer otro en 12 min.` (+ header `Retry-After: <segundos>`) |

Una fecha mal escrita, un año sin lista (2040) o un `anio` que no es entero **no** dan 403: siguen dando el `400` de siempre.
El admin no recibe ninguna de las dos guardas (conserva la regla de hasta 7 días con motivo del contrato anterior).

Sugerencia de UI para el supervisor: en la lista de días, deshabilitar editar/quitar cuando `pasado === true`; deshabilitar o avisar
«Cargar feriados» cuando `anios_precargables[i].verificado === false`; mostrar el `detail` del 403/429 tal cual.

## 4. Límite de frecuencia

- Máximo `calendario_max_escrituras_hora` (por defecto **20**) escrituras por usuario por hora, **ventana deslizante** de 60 minutos.
- El **admin también cuenta**, con un tope propio más alto: `calendario_max_escrituras_hora_admin` (por defecto **100**), para que cargar
  a mano un año de puentes y cierres no lo bloquee. Ambas claves son opcionales, por negocio (tabla `configuracion`, valor entero ≥ 1;
  un valor ausente o inválido usa el defecto). No hay pantalla para cambiarlas.
- Una «escritura» es un cambio efectivo: alta, cambio, baja, «marcar mañana» o una carga de feriados que insertó algo. Un `sin_cambios`,
  un `400`, un `404` y toda lectura **no** cuentan. El límite es por usuario y por negocio.
- Dónde se guarda: se cuenta contra la tabla de auditoría en la base (filas `entidad_tipo = "dia_especial"` del usuario en la última
  hora), **no** en memoria del proceso: vale igual con varias réplicas y sobrevive a reinicios, sin tabla ni migración nuevas.
  Es una guarda de uso, no una barrera atómica: dos peticiones simultáneas pueden pasar juntas el límite por una escritura.

## 5. Auditoría

Toda alta, cambio, baja y carga de feriados (y la fecha `calendario_habil_desde`) deja una fila en `RegistroAuditoria` con
`actor` (username) y, desde hoy, **`payload.actor_rol`** (`"admin"` | `"supervisor"`), `antes`/`despues` y `motivo`. Lo mismo para
aceptar/revocar la responsabilidad legal de «Para llamar» (`llamadas_responsabilidad_aceptada` / `_revocada`). Las filas anteriores
no tienen `actor_rol` (se listan con `null`). El campo es aditivo: ningún lector existente cambia.

**Exportación de leads** (`GET /dashboard/metricas/exportar.csv` y `.xlsx`, admin y supervisor): cada descarga deja una fila
`accion = "leads_exportados"`, `entidad_tipo = "exportacion"`, `actor` = username y
`payload = { "actor_rol", "formato": "csv" | "xlsx", "filas": <int>, "filtros": { "alcance": "todos_los_leads_del_negocio" } }`
(la exportación no admite filtros). Sin PII: ni teléfonos ni nombres. Si no se puede registrar, la descarga **no se entrega** (500).
No hay botón nuevo ni endpoint nuevo: el cambio es solo en el servidor.

## 6. Aviso al admin en Inicio (`GET /dashboard/inicio.json`, aditivo)

Solo para `admin`: si en las últimas **24 h** usuarios con rol `supervisor` (según `actor_rol` de la auditoría) hicieron cambios al
calendario del negocio, `avisos[]` trae **una** entrada más (al final de los avisos del admin):

```jsonc
{ "id": "calendario_cambios_supervisor", "nivel": "info",
  "titulo": "El supervisor ana cambió el calendario: 3 cambios en 24 h",      // 1 supervisor: «El supervisor ana cambió…»; varios: «Los supervisores ana y beto cambiaron…»; «1 cambio» en singular
  "detalle": "Revisa en el historial del calendario qué días se agregaron, cambiaron o quitaron.",
  "enlace": "/calendario#historial" }      // ruta propuesta del frontend: la pantalla del calendario, sección historial
```

Cuenta cada fila de auditoría del calendario de un supervisor (una carga de feriados cuenta 1). No cuenta los cambios del admin, los de
filas sin `actor_rol` ni los de otro negocio. Sin cambios de supervisores en la ventana no hay aviso. Supervisor y asesor **nunca** lo
reciben. El resto de `inicio.json` no cambia.

Nota para el frontend: `lib/avisos.ts::categoriaAviso` clasifica los avisos por `id`; un id desconocido cae en `sistema` (el Alert
grande de Inicio). Para este aviso es aceptable; si se prefiere franja informativa, agregar `calendario_cambios_supervisor` a la lista
de ids «operativos» (o una categoría propia).

## 7. D8 — medición de llamadas para el supervisor

`GET /dashboard/llamadas.json` ya entrega la clave `medicion` (conteos de 30 días por modo/grupo/segmento, incluido el grupo de control)
a **admin y supervisor**, y no la incluye para el asesor. No cambió: la UI del supervisor puede mostrarla en solo lectura.

## 8. Claves de configuración nuevas (por negocio, tabla `configuracion`; sin pantalla)

| clave | por defecto | efecto |
|---|---|---|
| `calendario_max_escrituras_hora` | `20` | tope de escrituras al calendario por usuario no-admin y hora (sección 4) |
| `calendario_max_escrituras_hora_admin` | `100` | tope del admin |
