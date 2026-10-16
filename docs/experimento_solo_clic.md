# Experimento «solo clic» — protocolo (Fases A y B)

Versión 2026-10-16 · Código: `agent/solo_clic.py` · Scripts: `scripts/configurar_solo_clic.py`, `scripts/medir_candidatos_llamada.py --solo-clic`, `scripts/analizar_solo_clic.py` · Diseño aprobado por el dueño el 2026-10-16 (informe D9).

Estado de esta entrega: **medición, definición, exclusión y SOMBRA**. Nada se envía y a nadie se llama. Todo viene **apagado**.

## 1. Qué problema resuelve

El cliente que toca un anuncio de Click-to-WhatsApp (o un enlace `wa.me`) abre el chat con un texto prellenado, lo envía sin escribir nada propio, Gabi le responde (p50 ≈ 7 s) y **no vuelve a decir nada**. Es el grupo más grande de leads callados y el menos entendido. Hoy solo recibe el reenganche genérico a las 2 h y el cierre «sin_respuesta» a las 15 h. El experimento compara tres tratamientos contra ese control para saber cuál recupera más contactos efectivos con el menor riesgo.

## 2. Definición de «solo clic» (`es_solo_clic`, función pura)

Una conversación es «solo clic» cuando se cumplen **todas**:

| | Regla |
|---|---|
| (a) | **Origen con texto prellenado**: `AttributionEvent` de tipo `meta_ads`, `meta_ads_no_resuelto` o `wa_link` de la conversación, o `Lead.campana_origen` (o la campaña de la Conversation). Un orgánico que escribe «hola» a mano queda fuera. |
| (b) | **Primer turno** del cliente = todo mensaje suyo **anterior** al primer mensaje **entregado** de Gabi. Debe ser exactamente **un** mensaje de **texto** igual a un «prellenado conocido» o a un saludo trivial («hola», «buenas», «buenos días», «hola buenas tardes»…, hasta 4 palabras de saludo). |
| | **Prellenado conocido** = texto normalizado (minúsculas, sin tildes, espacios colapsados) que aparece en **≥ 5 conversaciones distintas** (con origen prellenado, solo su primer mensaje) en **30 días**, **o** coincide con `Campana.texto_saludo`, **o** con el `body`/`headline` del referral de **esa** conversación. |
| (c) | **Gabi sí le escribió**: ≥ 1 mensaje de Gabi entregado (`estado_envio` ni `fallido` ni `incierto`), sin falla de IA (texto de error técnico) ni envío caído (un primer intento fallido hace la conversación no comparable). Un reenganche automático como «primer» mensaje no cuenta. |
| (d) | **Cero eventos del cliente** después del primer mensaje de Gabi, **de cualquier tipo**: texto, audio, imagen, sticker y reacción cuentan como interacción. |
| (e) | **Exclusiones previas al tratamiento, idénticas en todos los brazos**: triaje ATC cerrado, con asesor / pausado / escalado / derivado, mensaje humano (`role` asesor, o `assistant` con `via_app`), `Contact.no_llamar_en`, teléfono no peruano o BSUID, conversación cerrada o **ciclo reabierto** (el contacto ya tenía una conversación anterior), números internos o de prueba (`triaje_atc_telefonos_excluidos` y canales en modo `pruebas`), caso con resultado (salvo `sin_respuesta`: el cierre automático de 15 h no saca a nadie) y origen `formulario_meta`. |

**La cohorte se define «como estaba a T+20 min»** (T = primer mensaje entregado de Gabi): lo que el cliente haga **después** de T+20 no cambia si entra a la cohorte, así el resultado no depende de cuándo corrió el Cron. Los cierres definitivos posteriores tampoco descalifican. (Los flags de estado actual —asesor, pausa, resultado— se leen tal cual están: ver §9, límites.)

### Hallazgo del código que esto corrige (sin tocar el puntaje de «Para llamar»)

`llamadas.evaluar_lead` resta 1 mensaje real si hay `campana_origen`/`AttributionEvent` **sin comprobar que ese mensaje sea el prellenado**: un cliente que edita el prellenado y escribe algo real, o que manda solo un audio, se cuenta mal. Además el puntaje de un solo clic puede llegar a 4 **solo por lo que dijo Gabi** (precio + financiamiento + DNI), y con puntaje ≥ 4 el módulo habría llamado a quien nunca dijo nada. El puntaje **no se cambió**; se añadió una **exclusión explícita**: con el experimento encendido (`sc_exp_modo` ≠ apagado), `llamadas.crear_tareas` no crea tarea para un «solo clic» (motivo `solo_clic_en_experimento`). Si la comprobación falla con el experimento encendido, el lead **se omite** (falla cerrado, motivo `solo_clic_error`). Con `sc_exp_modo` apagado el módulo de llamadas es **idéntico** al anterior (hay prueba explícita).

## 3. Brazos

Asignación por **hash determinista** de `conversation_id` con sal propia `exp_solo_clic_<época>` (`sha256`, estable entre procesos y reinicios; distinta de la sal del holdout de «Para llamar» y de la de exploración: se probó que no hay correlación). Reparto por defecto: **C 40 % · T2 40 % · T1 20 %** (`sc_exp_pct_*`, se normaliza a 100). Cambiar `sc_exp_epoca` re-asigna y abre una cohorte nueva.

| Brazo | Qué haría | En esta entrega |
|---|---|---|
| **C — control** | Lo de hoy: reenganche genérico a 2 h y cierre `sin_respuesta` a 15 h. | `accion_habria = control_2h` |
| **T1 — toque** | UN toque genérico (el mismo texto de reenganche actual) a ~T+20…35 min, aislando el efecto del **tiempo**. | `toque_20` |
| **T2 — oferta** | Oferta de llamada con **SÍ explícito** a T+60 min **dentro del horario de atención**; fuera de horario se difiere a la próxima apertura (calendario de negocio, con feriados). No se envía si la apertura cae después de `sc_ventana_max_horas` = 22 h desde el último mensaje del cliente (margen sobre las 24 h de WhatsApp). | `oferta_60` / `omitida_ventana` / `omitida_fuera_de_horario` |
| **T3 — llamada directa** | **NO EXISTE.** El dueño la deja fuera de plan hasta después de las pruebas; luego habrá un botón de aprobación legal versionada. `sc_exp_pct_t3` es una clave **bloqueada** (siempre 0; se ignora aunque alguien la guarde; el configurador la rechaza). | — |

Todo esto en esta entrega **solo se registra**. Las acciones reales (Fase C) no están construidas.

## 4. Fases

1. **Medición (2-3 días)**: `python scripts/medir_candidatos_llamada.py --solo-clic --negocio-id <id> --dias 14`. Solo lectura. Decide si el segmento es lo bastante grande y qué % es alcanzable a T+60.
2. **Sombra (14 días)** — **aprobada por el dueño**: se enciende `sc_exp_modo=sombra`. Cada conversación «solo clic» recibe su brazo y se registra qué habría hecho; después se registra el desenlace natural a 24 h y 72 h. En sombra **todos los brazos se comportan como control**: sirve para medir la línea base p0 y el tamaño de muestra, y para validar que el reparto no esté sesgado.
3. **Piloto 20 % × 7 días** (Fase C, **no construida**): solo T1/T2 contra C, con las reglas de parada del §6.
4. **Ampliación** si la regla de decisión del §7 lo respalda.

Decisiones del dueño ya tomadas (para no reabrirlas):
- Sombra de 14 días: aprobada.
- **Texto de la oferta SIN enlace de privacidad por ahora.** Falta la política de privacidad y el correo de contacto: la oferta se enviará sin ese dato y queda **pendiente** agregarlo.
- Llamada directa (H3/T3): **fuera de plan** hasta después de las pruebas; luego, botón/aprobación legal versionada.
- 2 intentos de llamada con ≥ 3 h de separación (`sc_max_intentos` = 2; solo lo usará la Fase C).
- Llamadas de lunes a viernes, 9-18, durante las primeras 4 semanas.

## 5. Métricas

- **Primaria P1**: *contacto efectivo a 72 h desde T+20*. En sombra se mide como «el cliente volvió a escribir (cualquier evento, como en la definición (d)) dentro de 72 h desde T+20». En el piloto será «respondió, aceptó la oferta o contestó la llamada».
- Secundarias: respuesta a 24 h, `respondio_real` (excluye reacciones), horas hasta la respuesta, % alcanzable a T+60 (dentro de horario con ventana abierta), % ofertable (incluye diferir a la apertura), % con la ventana de 24 h cerrada al abrir el negocio, reenganche enviado, cierre `sin_respuesta`.
- Guardarraíles (piloto): rechazos explícitos, quejas, calidad del número en Meta, SLA de llamadas.

## 6. Reglas de parada propuestas (para el piloto)

Se detiene el brazo T1/T2 (o el piloto entero) si ocurre cualquiera:
- **Una queja ante Indecopi o una denuncia** vinculada al experimento.
- **Rechazo > 25 %** con **≥ 25 ofertas** enviadas (rechazo = «no», «no me llamen», bloqueo…).
- **Deterioro de la calidad del número en Meta** (cambio a calidad media/baja o aumento de bloqueos/reportes).
- **SLA vencido > 50 %** de las tareas de llamada del piloto.

## 7. Regla de decisión (propuesta)

Un tratamiento se adopta si: efecto observado en P1 **≥ +8 puntos** frente a C **y** probabilidad posterior de que sea mejor que C **≥ 90 %** (modelo Beta-binomial con prior uniforme) **y** guardarraíles limpios. Si el resultado es inconcluso, se decide por **costo y riesgo** (T1 no cuesta llamadas ni expone a riesgo legal; T2 sí). Con el n actual de la sombra el script `analizar_solo_clic.py` calcula el **efecto mínimo detectable** (dos proporciones, α 0,05, potencia 80 %) y los días estimados para **90 casos por brazo**; con n < 10 por celda imprime «muestra insuficiente».

## 8. Orden secuencial con otros experimentos

Mientras la sombra y el piloto corren, el segmento «solo clic» **no debe recibir otros cambios** que alteren su línea base: no se modifica el primer mensaje de Gabi ni el reenganche de 2 h/15 h para ese grupo, y «Para llamar» no le crea tareas (lo garantiza la exclusión). El A/B del primer mensaje (hallazgo de la auditoría de 399 chats) y cualquier cambio del texto de Gabi **esperan** a que termine el piloto o se hacen como **época nueva** (`sc_exp_epoca`). Orden: medición → sombra → (A/B del primer mensaje, si el dueño lo prioriza, sin solaparse) → piloto → ampliación. El triaje ATC y «Para llamar» siguen su propio camino: sus exclusiones ya están dentro de la definición (e).

## 9. Operación

```
# Ver la configuración (sin opciones solo MUESTRA):
python scripts/configurar_solo_clic.py --negocio-id <id>
# Encender la SOMBRA (no envía ni llama a nadie; «Para llamar» deja de crear tareas para los «solo clic»):
python scripts/configurar_solo_clic.py --negocio-id <id> --modo sombra
# Apagar (todo vuelve a como estaba):
python scripts/configurar_solo_clic.py --negocio-id <id> --modo apagado
# Medición previa y análisis (solo lectura, solo agregados, sin PII):
python scripts/medir_candidatos_llamada.py --solo-clic --negocio-id <id> --dias 14
python scripts/analizar_solo_clic.py --negocio-id <id> --dias 30
```

Claves por negocio (tabla `configuracion`):

| Clave | Default | Validación |
|---|---|---|
| `sc_exp_modo` | `apagado` | `apagado` \| `sombra` \| `activo`; otro valor = apagado. **`activo` está RESERVADO**: se degrada a `sombra` con un aviso en el log (la Fase C no existe). |
| `sc_exp_epoca` | `v1` | 1-20 caracteres `[A-Za-z0-9._-]` |
| `sc_exp_pct_c` / `_t1` / `_t2` | 40 / 20 / 40 | 0-100; los tres suman 100 (se valida al guardar; al leer se normaliza) |
| `sc_exp_pct_t3` | 0 | **BLOQUEADA** (se ignora; el configurador la rechaza) |
| `sc_cohorte_min` | 20 | 5-120 |
| `sc_toque_min` | 20 | 5-240 |
| `sc_oferta_min` | 60 | 10-360 (nunca menor que la cohorte) |
| `sc_ventana_max_horas` | 22 | 1-23,5 |
| `sc_max_intentos` | 2 | 1-5 (solo la usará la Fase C) |

### Dónde corre la sombra

Dentro del Cron **ya existente** `scripts/crear_tareas_llamada.py` (`*/15`, servicio sunny-embrace), en un bloque **aislado** con `try/except` que corre **después** de la creación de tareas y nunca la rompe (ni cambia su código de salida). No hay Cron nuevo ni entrada nueva en `CRONES_ESPERADOS`. Con `sc_exp_modo` apagado el bloque solo lee esa clave por negocio. Con el circuito de la IA abierto (modo sin IA) no corre. Cada corrida a los `*/15` evalúa a las conversaciones cuyo primer mensaje de Gabi cayó entre T+`sc_cohorte_min` y T+`sc_cohorte_min`+60 min (retraso máximo tolerado; pasado eso ya no se registra, porque el momento del tratamiento dejaría de ser comparable).

### Eventos (`EventoLead`, internos: no salen en el Timeline; tipo ≤ 60 caracteres)

- **`exp_solo_clic_sombra`** (uno por conversación y época; **idempotente**): `{epoca, brazo, accion_habria, hora_real_evaluacion, cayo_en_horario_a_T60, ventana_cierra_antes_de_apertura, minutos_desde_gabi, primer_gabi_en, ancla_en, tipo_primer_turno, oferta_hipotetica{estado,en,diferida}, toque_en, ventana_cierra_en, pct, cohorte_min, toque_min, oferta_min, ventana_max_horas, modo, version}`. Sin teléfono, nombre ni texto del cliente.
- **`exp_solo_clic_resultado`** (uno por conversación, época y horizonte 24 h / 72 h; idempotente): `{epoca, brazo, ancla_en, horizonte_h, respondio, respondio_real, horas_hasta_respuesta, reenganche_enviado, intervencion_humana, cerrado_sin_respuesta, observado_en}`.

**Decisión: dos eventos y no un registro actualizable.** `EventoLead` es **append-only** por diseño (nunca se actualiza ni se borra una fila); actualizar el evento de sombra rompería esa garantía y la auditoría. Por eso el desenlace es un evento aparte por horizonte, congelado en el momento de cumplirse. El script de análisis **no depende** de ellos: recalcula el desenlace desde los mensajes reales (más robusto si el Cron tuvo huecos); los eventos sirven para auditar y consultar con SQL.

### Qué cambia en producción al desplegar

**Nada visible.** Con todo apagado: solo se lee la clave `sc_exp_modo` por negocio en cada corrida del Cron (y una vez por `crear_tareas` con candidatos), no hay escrituras, `llamadas.crear_tareas` solo lee `sc_exp_modo` (y solo si hay candidatos), el Timeline no cambia (los dos tipos nuevos son internos) y no hay migración de base.

### Límites conocidos (honestidad metodológica)

- Los flags de **estado actual** (asesor, pausa, escalado, resultado, `no_llamar`) se leen tal cual están al evaluar. En vivo es lo correcto; en la **medición histórica** un cambio posterior podría sacar a alguien del universo. Los cierres definitivos sí se evalúan «como estaban a T+20».
- La idempotencia de los eventos es por consulta previa (no hay índice único sobre el JSON): dos corridas simultáneas del mismo Cron podrían duplicar un evento; Railway no solapa corridas del mismo servicio y los scripts de análisis cuentan por conversación.
- `Lead.campana_origen` es un dato del lead (no del ciclo); por eso el «ciclo reabierto» se excluye aparte.
- El texto prellenado de un anuncio que nadie repitió 5 veces en 30 días y que no coincide con una campaña ni con el referral **no** se reconoce (el cliente cuenta como «escribió algo suyo»). Es conservador a propósito: ante la duda, no es solo clic.
