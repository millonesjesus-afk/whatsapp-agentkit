# Maiek AI — Phase 2 Strategic Plan

**Versión 0.1 (borrador) · Estado: Draft — para revisión, no Approved**

| | |
|---|---|
| Documento | Phase 2 Strategic Plan |
| Proyecto | Maiek AI |
| Versión | 0.1 (borrador) |
| Estado | **Draft** |
| Fecha de creación | 2026-07-30 |
| Autor | Claude, actuando como CTO/Principal Architect a pedido de Jesús Millones |
| Fecha de aprobación | Pendiente |
| Última actualización | 2026-07-30 |

## Dependencias

`IMPLEMENTATION_REVIEW_FASE_1.md`, `RELEASE_NOTES_v0.2.0.md`, `DEPLOYMENT_CHECKLIST_v0.2.0.md`,
`MAIEK_AI_OPERATIONS_RUNBOOK.md` v1.1 (evidencia real del primer despliegue — base del postmortem,
sección 1); `MAIEK_AI_IMPLEMENTATION_ROADMAP.md` v1.0 (roadmap ejecutivo ya aprobado — este
documento no lo reemplaza, lo extiende y resuelve una ambigüedad de nomenclatura que introdujo, ver
sección 0); los 8 documentos de arquitectura técnica del corpus principal (Data, Backend, API, AI,
Security, DevOps, Operations, Frontend) y sus Current State Assessments — origen de toda brecha
citada en la sección 3; `DOCUMENTATION_INDEX.md` (gobernanza documental — este documento sigue su
regla de que todo documento nuevo se registra antes de escribirse, con la salvedad explícita de que
**no se registra en la tabla de estado (sección 7 del índice) hasta ser Approved**, para no
declarar como oficial algo que todavía es un borrador de planificación).

## Consumido por

Decisión del usuario sobre cómo secuenciar el trabajo posterior a la Fase 1. Si se aprueba, sus
recomendaciones se traducen en actualizaciones formales a `MAIEK_AI_IMPLEMENTATION_ROADMAP.md`
(nueva versión) y, donde corresponda, en nuevos ADRs o revisiones de arquitectura puntuales — este
documento no es en sí mismo un documento de arquitectura ni redefine ninguna Decisión local ya
`Objetivo` de los 8 documentos técnicos.

## Alcance y naturaleza de este documento

Documento estratégico de planificación, no de arquitectura ni de implementación. No sigue la
plantilla del ADS (no tiene Architectural Constraints ni Architecture Success Criteria propios en
el sentido que el ADS define) — es, en espíritu, más cercano al `MAIEK_AI_IMPLEMENTATION_ROADMAP.md`
que a un documento de arquitectura: seguido de la misma desviación ya prevista y autorizada por el
ADS §2 para documentos procedimentales/ejecutivos. Preparado bajo instrucción explícita del usuario:
sin código, sin commits, sin modificar ningún documento `Approved` existente. Queda como archivo
local sin commitear hasta que el usuario lo revise y decida su destino.

---

## 0. Nota de alcance — el nombre "Fase 2" ya está sobrecargado, y hay que resolverlo antes de seguir

Antes de entrar en el contenido: el pedido de este documento usa "Fase 2" para referirse al
**próximo gran período de trabajo del proyecto**. Pero "Fase 2" ya tiene **tres significados
distintos y ya aprobados** dentro del corpus existente, y no son lo mismo:

| Dónde aparece "Fase 2" | Qué significa ahí |
|---|---|
| `MAIEK_AI_DATA_ARCHITECTURE.md`, roadmap interno de 3 fases | Integridad referencial (FKs), migración de precios a `Numeric`, entidades nuevas (`MemoriaPersistente`, `SugerenciaIA`, `RegistroAuditoria`) — **no** incluye `negocio_id` |
| `MAIEK_AI_IMPLEMENTATION_ROADMAP.md`, sección 4 | Exclusivamente Data Architecture **Fase 3** (`negocio_id`, Multi-Tenant) — el roadmap saltea la Fase 2 de Data Architecture y no le asigna ninguna fase propia |
| Este pedido de hoy | Todo el próximo período de trabajo del producto: Multi-Tenant, Data Architecture Fase 2, Knowledge Base/RAG, CRM, Observabilidad, Analítica, Automatizaciones — una superficie mucho más amplia que cualquiera de las dos anteriores |

Esto no es un detalle cosmético: si se sigue usando "Fase 2" para las tres cosas, cualquier
conversación futura (humana o con otro agente de IA) va a interpretar mal a cuál se refiere. Y hay
un vacío real detrás del nombre: **el Roadmap nunca le asignó una fase propia a Data Architecture
Fase 2** (integridad/`Numeric`/entidades) — la saltea directamente de Fase 1 (Alembic) a lo que el
Roadmap llama "Fase 2" pero que en realidad es Data Architecture Fase 3 (`negocio_id`). Y Data
Architecture ya declara explícitamente que `negocio_id` depende de que **su propia Fase 2 esté
activa** — es decir, el propio corpus ya exige un paso que el Roadmap nunca calendarizó
explícitamente como propio.

**Propuesta de resolución (a confirmar por el usuario, no asumida silenciosamente):**

- Mantener "Fase 0" y "Fase 1" del Roadmap tal cual están (ya cerradas, ya evidenciadas en
  producción — no se tocan).
- Llamar a partir de acá al período que este documento planifica **"Fase 2 del Roadmap de
  Producto"** o simplemente **"Ciclo 2"**, para distinguirlo de las fases internas de Data
  Architecture — y usar siempre "Data Architecture Fase 2" / "Fase 3" con el nombre completo
  cuando se hable de esas específicamente, nunca solo "Fase 2" a secas.
- Dentro de este Ciclo 2, el trabajo no es una sola secuencia lineal como fueron Fase 0 y Fase 1 —
  es **multi-track** (sección 4): hay iniciativas que no comparten dependencias entre sí y no
  deberían forzarse a una sola línea de tiempo. Esto en sí mismo es una diferencia estructural
  respecto a cómo se ejecutaron las fases anteriores, y se argumenta en la sección 1.4.

El resto de este documento usa esta nomenclatura. Si el usuario prefiere otro esquema de nombres,
es un cambio de forma, no de contenido — no afecta la evaluación de prioridades ni el roadmap
propuesto.

---

## 1. Postmortem de la Fase 1

### 1.1 Qué salió especialmente bien

**El enfoque "arquitectura primero" se pagó solo, de forma medible.** Los 22 commits de código de
la Fase 1 se trazan, sin excepción, a una Decisión local ya `Objetivo` de un documento Approved
(`IMPLEMENTATION_REVIEW_FASE_1.md`, sección 2) — cero trabajo especulativo, cero refactor sin
justificación documentada. Eso no es burocracia: es lo que permitió que, cuando apareció el
incidente del despliegue (sección 1.2), la causa raíz se pudiera diagnosticar en minutos en vez de
horas — porque cada pieza del sistema ya tenía un porqué escrito en algún lado.

**"Evidence over Opinion" funcionó cuando importó de verdad.** Data Architecture Fase 1 (el
baseline de Alembic) no estaba planificada para ejecutarse cuando se ejecutó — se adelantó porque
apareció como bloqueo real durante el trabajo de AI (la columna `revision_prioritaria` no podía
agregarse con `create_all()`). El equipo (en este caso, un humano y un agente de IA) pausó el
trabajo en curso para resolver la causa raíz en vez de parchear alrededor. Ese mismo principio es
el que después permitió corregir el incidente del stamp en el momento, en vez de documentarlo como
"pendiente" y seguir adelante.

**La validación fue real, no solo simulada — y aun así no fue suficiente (ver 1.2).** Antes del
despliegue: 3 llamadas reales a la API de Anthropic (no mocks), un flujo autenticado de punta a
punta real, envío duplicado real de un payload de webhook para probar idempotencia. Eso dio
confianza genuina — y es precisamente por eso que vale la pena documentar con la misma honestidad
que, aun con toda esa validación real, la producción encontró algo que ninguna de esas pruebas
tocó (sección 1.2). Ambas cosas son ciertas a la vez: la validación previa fue rigurosa, y no
alcanzó. Esa es la lección más valiosa de esta fase, no una contradicción a resolver.

**El Deployment Checklist hizo exactamente lo que tenía que hacer.** El incidente se detectó porque
el checklist exigía probar una ruta real logueada como parte de la validación de `request_id` — no
porque hubiera monitoreo activo (no lo hay, ver 1.2) ni por casualidad. Un checklist que en un
punto arbitrario obliga a "usar el producto de verdad" antes de dar el despliegue por bueno
demostró su valor en el primer uso real.

**Cuando algo salió mal, el proceso de corrección fue disciplinado, no improvisado.** Diagnóstico
con evidencia (logs reales, no suposición), verificación del contenido exacto de las migraciones
antes de tocar producción de nuevo, corrección mínima y aditiva (sin pérdida de datos), y
documentación de la causa raíz el mismo día — no como una nota mental para "documentar después".

### 1.2 Qué problemas encontramos

**El incidente central: `alembic stamp head` directo rompió el panel de leads en producción durante
~6 minutos.** Causa raíz completa, con la secuencia exacta de eventos, ya documentada en
`MAIEK_AI_OPERATIONS_RUNBOOK.md` v1.1 ("Lecciones aprendidas del primer despliegue") — no se repite
acá en detalle. Lo relevante para este postmortem es el **patrón de falla**, porque es el tipo de
cosa que puede volver a pasar de otra forma si no se generaliza la lección:

- Un procedimiento operativo (`MAIEK_AI_OPERATIONS_RUNBOOK.md`, Escenario 1) se escribió cuando
  una condición del sistema era cierta (`head` == baseline, porque solo existía una migración) y
  **quedó escrito en piedra** (con un revision ID literal en el comando) aunque esa condición dejó
  de ser cierta poco después (se agregaron dos migraciones más durante el resto de la misma Fase
  1). Nada forzó una re-verificación del procedimiento antes de usarlo contra producción real.
- El fallo no fue un error de arranque (que se habría visto de inmediato) — fue un éxito de
  arranque con un esquema incompleto. Ese tipo de falla silenciosa es estructuralmente más
  peligrosa que un crash, porque no hay ninguna señal automática de que algo salió mal.
- Se detectó por una prueba manual puntual, no por monitoreo. Si esa prueba manual no hubiera sido
  parte del checklist, el `500` habría quedado ahí hasta que un usuario real del panel lo
  reportara.

**Brecha de observabilidad, ya conocida pero ahora con evidencia concreta de su costo.**
`MAIEK_AI_DEVOPS_ARCHITECTURE.md` ya señalaba "logs + métricas + health checks" como mejora futura
no bloqueante. Después de este incidente, ya no es una mejora teórica: es la diferencia entre
detectar un `500` en producción en segundos (con alertamiento) vs. depender de que alguien
pruebe la ruta correcta a mano en la ventana de tiempo correcta.

**Ausencia de ambiente de staging — riesgo ya identificado en el propio Roadmap (sección 6, "Alto")
y todavía no resuelto.** Todo el trabajo de Fase 1 se validó en local + producción directamente. No
hubo ningún entorno intermedio donde este incidente pudiera haberse detectado sin tocar datos
reales.

**Ausencia de un gate automatizado que verifique el esquema real contra lo que el código espera.**
El mecanismo de defensa que sí existe (`agent/migraciones.py`,
`_diagnosticar_baseline_no_registrado`) detecta un caso específico (tablas del esquema actual sin
`alembic_version`) — pero no detecta el caso que realmente ocurrió (`alembic_version` presente,
pero apuntando a una revisión que miente sobre el estado real del esquema). Es una brecha de
diseño del propio mecanismo de defensa, no solo del procedimiento humano.

**Riesgo de exposición de credenciales en flujos operativos manuales.** Durante la ejecución del
backup manual, la `DATABASE_URL` real de producción (con contraseña en texto plano) terminó
visible en la conversación de todos modos, pese a haberse diseñado el procedimiento explícitamente
para evitarlo (pedirle al usuario que la seteara como variable de entorno en su propia terminal, no
que la pegara en el chat) — porque el usuario compartió una captura de pantalla de su propia
terminal. El diseño del procedimiento fue correcto; el canal de comunicación (captura de pantalla)
lo esquivó de una forma que no se había anticipado. Sigue pendiente rotar esa contraseña en
Railway.

### 1.3 Qué aprendimos durante el primer despliegue

**"El arranque terminó sin errores" no es lo mismo que "el sistema está correcto".** Con
migraciones basadas en un registro de estado propio (`alembic_version`) que no se auto-verifica
contra la realidad, un arranque limpio certifica que el código y el registro de Alembic están de
acuerdo entre sí — no que ese acuerdo sea correcto. Cualquier procedimiento futuro que dependa de
un mecanismo similar (registro de estado separado de la realidad que describe) necesita una
verificación activa de esa realidad, no solo de la consistencia interna del registro.

**Los procedimientos operativos con valores hardcodeados tienen fecha de vencimiento silenciosa.**
Un comando con un revision ID literal, una URL literal, o cualquier valor que pueda volverse
obsoleto sin que nada lo señale, necesita un disparador explícito de revisión ("revisar este paso
cada vez que se agregue una migración nueva"), no solo la expectativa de que alguien se acuerde de
actualizarlo. Ya se agregó ese disparador al Runbook corregido (v1.1) para este caso puntual — vale
la pena generalizarlo como práctica para cualquier procedimiento futuro similar.

**La validación real de producción encuentra cosas que ninguna combinación de validación local +
mocks puede encontrar** — porque el estado real de una base de datos con historia (creada antes de
que existiera cierto mecanismo, con datos reales, con una secuencia de cambios acumulada) no es
reproducible fielmente en local sin un esfuerzo deliberado de sincronizar ambos entornos (que hoy
no existe — ver staging, sección 1.2). Esto no invalida la disciplina de validar en local primero
— la valida como necesaria pero insuficiente, no como suficiente por sí sola.

**Un incidente bien documentado el mismo día vale más que diez líneas de "postmortem" escritas
semanas después.** La corrección de `MAIEK_AI_OPERATIONS_RUNBOOK.md` a v1.1 pudo incluir la
secuencia exacta de comandos, los timestamps reales de los logs y el impacto medido en minutos
precisamente porque se escribió mientras la evidencia todavía estaba completa y fresca. Vale la
pena mantener ese hábito como estándar, no como excepción para incidentes "grandes".

### 1.4 Qué deberíamos hacer diferente en las próximas fases

1. **Ningún cambio de esquema futuro se considera validado solo por un arranque limpio.** Todo
   despliegue que incluya una migración debe incluir, como parte del propio checklist (no como
   paso opcional), probar activamente al menos una ruta real que dependa de lo que esa migración
   cambia — ya incorporado al `MAIEK_AI_OPERATIONS_RUNBOOK.md` v1.1, pero vale la pena declararlo
   acá como principio general, no solo como corrección puntual de un escenario.
2. **Un ambiente de staging deja de ser "mejora futura no bloqueante" y pasa a ser un prerrequisito
   real antes de tocar el modelo de datos otra vez** — la migración a `negocio_id` (el trabajo más
   riesgoso que queda pendiente, según el propio Roadmap, sección 6) va a tocar el modelo de datos
   de un negocio real en producción. Repetir el patrón de "validar en local + desplegar directo a
   producción" en ese trabajo específico es un riesgo que ya no se puede justificar con "todavía no
   tuvimos un incidente" — ya lo tuvimos, a menor escala.
3. **Observabilidad mínima (alertamiento sobre errores 500 reales) antes de la próxima fase que
   toque datos, no en paralelo sin fecha como hasta ahora.** No hace falta el stack completo de
   observabilidad que `MAIEK_AI_DEVOPS_ARCHITECTURE.md` describe como objetivo final — hace falta
   la pieza mínima que hubiera detectado este incidente sin depender de una prueba manual.
4. **El trabajo posterior a la Fase 1 no debería planificarse como una sola secuencia lineal.** Fase
   0 y Fase 1 tenían sentido como secuencia única porque cada una era, genuinamente, prerrequisito
   de la siguiente. Lo que sigue no tiene esa forma: hay iniciativas de datos/Multi-Tenant, de
   observabilidad, de capacidad de producto (IA, CRM) y de crecimiento (campañas, Lead Ads) que no
   comparten dependencias entre sí. Forzarlas a una sola línea de tiempo generaría bloqueos
   artificiales. La sección 4 de este documento propone una estructura multi-track en lugar de una
   fase lineal más.
5. **Revisar la disciplina de "procedimiento con valores literales" en cualquier documento
   operativo nuevo** — preferir describir el procedimiento en términos de "el baseline vigente" /
   "el head actual" verificado en el momento, con el valor literal como ejemplo, no como verdad
   fija — ya aplicado en la corrección del Runbook v1.1, recomendado como estándar hacia adelante.

---

## 2. Estado actual del producto

### 2.1 Mapa de madurez por componente

| Componente | Estado | Madurez | Deuda técnica / riesgo conocido |
|---|---|---|---|
| Canal WhatsApp (Meta Cloud API, multi-canal) | Implementado, en producción | **Alta** | Ninguna crítica; cifrado de credenciales por canal ya activo |
| Motor de IA (Gabi) — protocolo de confianza | Implementado, activo solo en `modo="pruebas"` | **Media** | Sin validación con tráfico conversacional real todavía (`MAIEK_AI_CONVERSATIONAL_VALIDATION_PLAN.md` define cómo, no ejecutado); sin persistencia formal de `SugerenciaIA` (depende de Data Architecture Fase 2) |
| CRM / Pipeline de leads (embudo, estados, búsqueda/orden/paginación) | Implementado, en producción | **Alta** | Columnas de métricas (18 siempre visibles) sin resolver — decisión pendiente del usuario, no técnica |
| Multimedia (adjuntos, audio, catálogo estático) | Implementado, en producción | **Alta** | Catálogo vive en disco efímero de Railway + caché en memoria — no sobrevive un redeploy sin volumen persistente ya configurado |
| Panel / Dashboard | Implementado, en producción, responsive | **Media-Alta** | `dashboard.py` sigue siendo un router grande (Backend Architecture, brecha ya conocida) — Presentación/Aplicación sin separar del todo |
| Autenticación / Autorización | Implementado, `requiere_rol` centralizado | **Alta** | Ninguna crítica conocida |
| Contrato interno de API (`request_id`, errores uniformes, idempotencia) | Implementado, validado con tráfico real | **Alta** | Códigos de error semánticos (`LEAD_NO_ENCONTRADO`, etc.) siguen derivados genéricamente del status HTTP |
| Migraciones de esquema (Alembic) | Implementado, con el incidente ya corregido y documentado | **Media** — funcional, pero el primer uso real reveló una brecha de verificación automatizada | Sin gate automatizado que verifique esquema real vs. esperado (sección 1.2) |
| Multi-Tenant / `negocio_id` | **No implementado** | **Ninguna** | El hallazgo repetido sin excepción en los 8 CSAs del corpus — bloqueante transversal ya declarado por el propio Roadmap |
| Data Architecture Fase 2 (integridad referencial, `Numeric`, `RegistroAuditoria`/`SugerenciaIA`/`MemoriaPersistente`) | **No implementado** | **Ninguna** | Prerrequisito declarado por Data Architecture para `negocio_id` — sin fase propia asignada en el Roadmap actual (sección 0) |
| Knowledge Base / RAG | **No implementado** (solo búsqueda de substring en archivos planos, heredada del template original de AgentKit) | **Baja** | AI Architecture ya define 6 fuentes de conocimiento como taxonomía objetivo, sin implementar en código (brecha ya conocida, `IMPLEMENTATION_REVIEW_FASE_1.md`, riesgo #3) |
| Observabilidad (métricas, alertamiento, staging) | **No implementado** | **Ninguna** | DevOps Architecture ya lo señala como P2; este postmortem eleva su urgencia con evidencia real (sección 1) |
| Analítica de negocio | Parcial — datos existen (leads, mensajes, ventas), sin capa de análisis dedicada | **Baja** | MPX Cap. 10 ya define métricas de referencia; Operations Architecture liga KPIs de calidad a `SugerenciaIA`, que todavía no existe como entidad persistida |
| Automatizaciones (fuera del propio agente conversacional) | **No implementado, sin grounding arquitectónico todavía** | **Ninguna** | A diferencia de las demás iniciativas de esta lista, no se deriva de ninguna Decisión local `Objetivo` ya aprobada — ver nota en sección 3 |
| Campañas WhatsApp masivas + SMS | **No implementado** | **Ninguna** | Riesgo de baneo ya conocido (ocurrió antes con Whapi) — depende de plantilla de WhatsApp aprobada por Meta |
| Meta Lead Ads | Código implementado y desplegado, **inerte** | **Baja** (construido, no activo) | Bloqueado en decisión de negocio: pedir el permiso `leads_retrieval` a Meta sin arriesgar el `whatsapp_business_messaging` ya en producción |
| Catálogo de precios vía panel (CSV) | **No implementado** | **Ninguna** | Requiere migrar el catálogo a Postgres primero (hoy vive en disco efímero + caché en memoria) |
| Dominio propio | **No implementado** | **Ninguna** | Bloquea Resend (email) y un acortador de links propio — sin urgencia de negocio identificada todavía |
| Gestión de usuarios vía panel | Función interna existe (`crear_usuario()`), sin exponer en el panel | **Baja** | Trabajo de UI acotado, sin dependencias técnicas complejas |
| Panel de Análisis IA (admin-only) | **No implementado, deliberadamente diferido** | **Ninguna** | Depende de que `SugerenciaIA` exista como entidad persistida (Data Architecture Fase 2) |

### 2.2 Deuda técnica consolidada (fuera de lo ya listado por componente)

- `dashboard.py` como router grande (Backend Architecture, brecha ya conocida y aceptada con
  criterio de revisión).
- Códigos de error semánticos pendientes (mejora incremental, no bloqueante).
- `BackgroundTasks` para notificaciones/eventos WS no implementado (marcado como mejora
  transitoria, no bloqueante, desde Backend Architecture).
- Testing Strategy y QA Strategy — documentos que el propio Roadmap (sección 10) preveía construir
  "durante la Fase 0-1" y todavía no existen. Esto es, en sí mismo, deuda de gobernanza que la Fase
  2 debería resolver temprano, no al final — es exactamente el tipo de mecanismo que hubiera
  ayudado a prevenir el incidente de despliegue.
- Sin backups automatizados con S3 + Cron (Fase 0 dejó esto como pendiente operativo del usuario,
  hoy resuelto solo de forma manual/puntual).

### 2.3 Riesgos abiertos (más allá de lo ya cubierto en el postmortem)

- **Riesgo de negocio, no técnico**: revisión de costos del proyecto completo (Railway, Anthropic,
  Meta, Resend) todavía pendiente — sin visibilidad de costo total, cualquier decisión de escalar
  (más tráfico, más canales, un segundo negocio) se toma sin ese dato.
- **Riesgo de concentración**: toda la ejecución depende de una sola persona (el usuario) más un
  agente de IA — ya reconocido como Architectural Constraint en Operations Architecture. Cualquier
  plan de Fase 2 que asuma paralelismo agresivo entre tracks (sección 4) subestima este límite real
  de capacidad de ejecución si no se dimensiona con cuidado.
- **Riesgo regulatorio/reputacional latente**: PII sin cifrado de campo — decisión ya tomada
  conscientemente en Security Architecture ("Activa, con criterio de revisión"), no un descuido,
  pero sigue siendo una decisión que vale la pena revisar explícitamente si `negocio_id` amplía la
  superficie de datos gestionados (más negocios, potencialmente más jurisdicciones/reguladores).

---

## 3. Evaluación de prioridades

Cada iniciativa se evalúa en cinco ejes (Valor, Dependencias técnicas, Riesgo, Esfuerzo, Impacto en
plataforma), con foco en qué **no** puede empezar hasta que otra cosa exista — esa es la variable
que más determina el orden real, más que el valor de negocio aislado de cada una.

| Iniciativa | Valor de negocio | Dependencias técnicas | Riesgo | Esfuerzo | Impacto en plataforma |
|---|---|---|---|---|---|
| Data Architecture Fase 2 (integridad, `Numeric`, entidades) | Medio directo, **alto habilitante** (desbloquea 3 iniciativas más abajo) | Ninguna — depende solo de Fase 1, ya activa | Medio (toca esquema, pero sin cambio de modelo de negocio) | Medio | Alto — es la base de `negocio_id`, `SugerenciaIA` y auditoría |
| Observabilidad mínima (alertamiento + staging) | Indirecto (previene incidentes, no genera ingreso directo) | Ninguna | Bajo en sí misma | Medio | Alto — reduce el riesgo de todo lo demás que sigue |
| `negocio_id` / Multi-Tenant (Data Architecture Fase 3) | Alto estratégico (habilita crecer a más negocios), **bajo valor inmediato** con un solo negocio real hoy | Data Architecture Fase 2 + observabilidad mínima recomendada (sección 1.4) | **Alto** (toca datos de producción real) | Alto | Muy alto — es el bloqueante transversal de los 8 CSAs |
| Knowledge Base / RAG real | Alto directo (mejora la calidad de respuesta de Gabi, ya es una Decisión `Objetivo` sin implementar) | Ninguna dura — puede construirse sobre el modelo actual de un solo negocio | Bajo-Medio | Medio | Medio-Alto — mejora el producto ya en manos de clientes reales hoy |
| Plantilla de WhatsApp aprobada por Meta | Alto (desbloquea 3 iniciativas: Lead Ads, contacto de leads de llamada, campañas masivas) | Ninguna técnica — es un proceso externo con tiempo de espera propio | Bajo (proceso administrativo) | Bajo esfuerzo propio, **alto tiempo de espera externo** | Alto — un solo trámite desbloquea tres frentes |
| Activación de Meta Lead Ads | Medio-Alto (nuevo canal de adquisición) | Plantilla de WhatsApp aprobada; decisión de negocio sobre el permiso `leads_retrieval` | Medio (riesgo sobre el scope ya aprobado en producción) | Bajo (código ya existe) | Medio |
| Catálogo de precios vía panel | Medio (autonomía operativa, hoy depende de edición manual) | Migrar catálogo a Postgres | Bajo | Medio | Medio |
| Campañas masivas WhatsApp + SMS | Medio-Alto potencial, con riesgo real ya materializado antes (baneo con Whapi) | Plantilla de WhatsApp aprobada | **Alto** (riesgo de baneo del canal principal de atención) | Medio-Alto | Alto si sale bien, **muy alto si sale mal** (puede tumbar el canal de producción) |
| Analítica de negocio (dashboard dedicado) | Medio | `SugerenciaIA` persistida (Data Architecture Fase 2) para los KPIs de calidad; datos de leads/ventas ya existen para lo demás | Bajo | Medio | Medio |
| Panel de Análisis IA (admin-only) | Medio, específico para gestión interna | `SugerenciaIA` persistida (Data Architecture Fase 2) | Bajo | Medio | Bajo-Medio (uso interno, no de cara al cliente) |
| Columnas de métricas / calendario completo (pulido de CRM) | Bajo-Medio | Ninguna | Bajo | Bajo | Bajo |
| Gestión de usuarios vía panel | Bajo-Medio (comodidad operativa) | Ninguna | Bajo | Bajo | Bajo |
| Dominio propio | Bajo, sin driver de negocio identificado hoy | Ninguna | Bajo | Bajo | Bajo (desbloquea Resend/acortador, ninguno urgente) |
| Automatizaciones (workflow engine más allá del agente) | **Sin evaluar en serio todavía** — no tiene grounding arquitectónico | Depende de qué se defina que significa "automatización" — hoy es una categoría, no una decisión | Desconocido | Desconocido | Desconocido |

**Nota sobre "Automatizaciones"**: a diferencia de todas las demás filas de esta tabla, esta
iniciativa no se deriva de ninguna Decisión local ya `Objetivo` de los 8 documentos de arquitectura
— rompe el principio que el propio Roadmap fija en su sección 2 ("toda tarea de implementación debe
trazarse a al menos una Decisión local ya `Objetivo`... si no tiene de dónde derivar, no es
implementación, es una decisión de arquitectura pendiente"). Antes de estimarla en serio, necesita
una definición concreta de alcance (¿automatizar qué, para quién, con qué disparadores?) — este
documento no la incluye en el roadmap propuesto (sección 4) por esa razón, no por falta de valor
potencial.

---

## 4. Roadmap propuesto — estructura multi-track, no una fase lineal más

Como se argumenta en la sección 1.4, forzar todo esto a una sola secuencia (como Fase 0 → Fase 1)
introduciría bloqueos artificiales entre iniciativas que no comparten dependencias reales. Se
proponen **tres tracks**, con su propio orden interno, y una recomendación explícita sobre cuánto
paralelismo es realista dado el riesgo de concentración (sección 2.3).

### Track A — Fundación de datos (secuencial, es la columna vertebral)

1. **Data Architecture Fase 2** (integridad referencial, `Numeric`, `MemoriaPersistente`/
   `SugerenciaIA`/`RegistroAuditoria`) — primero, porque desbloquea todo lo demás de este track y
   dos iniciativas del Track C (Analítica, Panel de Análisis IA). Sin dependencias técnicas
   externas, puede empezar de inmediato.
2. **Observabilidad mínima** (alertamiento sobre errores reales + un ambiente de staging funcional)
   — en paralelo o inmediatamente después del punto 1, y **antes** del punto 3. Justificación
   directa: el punto 3 es el trabajo de mayor riesgo de todo el roadmap (toca datos de un negocio
   real en producción), y hacerlo sin la capacidad de detectar fallas automáticamente ni un entorno
   donde ensayarlo primero repetiría exactamente el patrón que causó el incidente de la Fase 1, a
   una escala potencialmente mayor.
3. **`negocio_id` / Multi-Tenant** (Data Architecture Fase 3) — el bloqueante transversal, una vez
   que 1 y 2 estén activos. Es el ítem de mayor impacto estructural de todo el roadmap, y también
   el de mayor riesgo — secuenciarlo al final de este track, no al principio, es una decisión
   deliberada informada directamente por el postmortem.

### Track B — Capacidad de producto (puede avanzar en paralelo al Track A desde el día uno)

1. **Knowledge Base / RAG real** — no depende de `negocio_id` para construirse sobre el modelo
   actual de un solo negocio, ya es una Decisión `Objetivo` pendiente de AI Architecture (no una
   idea nueva), y mejora directamente el producto que los clientes reales usan hoy. Único cuidado
   recomendado: diseñar el esquema/interfaces ya con `negocio_id` como campo presente (aunque no
   se use todavía), para no tener que retrabajar esa pieza cuando el Track A llegue a su punto 3 —
   es mucho más barato hacerlo ahora que migrar datos de conocimiento después.

### Track C — Crecimiento y operación (mayormente gestionado por procesos externos, bajo esfuerzo propio)

1. **Iniciar el trámite de plantilla de WhatsApp aprobada por Meta** — de inmediato, en paralelo a
   todo lo demás: es el ítem con menor esfuerzo propio y mayor apalancamiento de esta lista (un
   trámite desbloquea tres iniciativas), y tiene tiempo de espera externo que no se puede acelerar
   trabajando más — cuanto antes se inicie, antes deja de ser cuello de botella.
2. **Revisión de costos del proyecto** — de inmediato, independiente de todo lo demás: es
   información que ya debería existir para tomar cualquier otra decisión de esta lista con
   contexto real de negocio, no solo técnico.
3. **Decisión de negocio sobre Meta Lead Ads** (pedir `leads_retrieval` o no) — puede tomarse en
   paralelo, no depende técnicamente de nada más que la plantilla aprobada (punto 1).
4. **Catálogo de precios vía panel** — una vez que el Track A (punto 1, Data Architecture Fase 2)
   ya esté tocando la capa de datos, hay sinergia real en resolver la migración del catálogo a
   Postgres en la misma ventana de trabajo, en vez de abrir un frente de trabajo de datos separado
   más adelante.
5. **Campañas masivas WhatsApp + SMS** — deliberadamente al final de este track, después de la
   plantilla aprobada y, se recomienda, después de que `negocio_id` (Track A) esté activo — no por
   dependencia técnica estricta, sino porque el riesgo de baneo ya materializado antes hace
   prudente no lanzar esta iniciativa mientras el track de mayor riesgo técnico (Multi-Tenant)
   sigue en curso — concentrar dos iniciativas de riesgo alto en la misma ventana de tiempo va en
   contra del principio de capacidad de ejecución limitada (sección 2.3).
6. **Extensión Multi-Tenant a los demás dominios** (Security, AI, DevOps, Operations, Frontend —
   ya definida como Fase 3 del Roadmap actual) y **pulido de CRM** (columnas de métricas,
   calendario completo, gestión de usuarios vía panel) — al final, una vez que `negocio_id` exista;
   son extensiones o refinamientos, no fundación.

### Recomendación sobre paralelismo real

Dado el riesgo de concentración ya señalado (sección 2.3), la recomendación explícita es: **Track A
punto 1 y Track C puntos 1-3 pueden avanzar en paralelo desde ya** (bajo esfuerzo propio o
gestionados mayormente por procesos externos). El Track B (Knowledge Base/RAG) es razonable
sumarlo una vez que el Track A punto 1 esté encaminado, no necesariamente desde el primer día. El
punto de mayor disciplina de secuenciación es Track A punto 3 (`negocio_id`) — ese no debería
competir por atención con ninguna otra iniciativa de riesgo Alto o Medio-Alto en la misma ventana.

---

## 5. Success Criteria del Ciclo 2

Objetivos verificables, en el mismo espíritu que los hitos H1-H6 ya definidos en
`MAIEK_AI_IMPLEMENTATION_ROADMAP.md` (sección 5) — reutilizando su criterio donde ya existe, en vez
de redefinirlo:

1. **Data Architecture Fase 2 activa** — se cumplen los Architecture Success Criteria ya definidos
   en `MAIEK_AI_DATA_ARCHITECTURE.md` para su propia Fase 2 (integridad referencial, `Numeric`,
   las tres entidades nuevas) — este documento remite a ese, no lo repite.
2. **Observabilidad mínima operativa** — existe alertamiento automático capaz de detectar, sin
   intervención manual, el tipo de fallo silencioso descrito en la sección 1.2 (un endpoint real
   devolviendo `500` de forma sostenida); existe un ambiente de staging usado para al menos un
   despliegue real antes de tocar producción.
3. **`negocio_id` implementado** — mismo criterio ya fijado como H3 del Roadmap: el modelo de
   datos soporta más de un negocio de forma verificable, sin que la operación del negocio actual se
   haya interrumpido.
4. **Knowledge Base / RAG en producción real** — Gabi responde usando recuperación real de
   conocimiento (no solo coincidencia de substring), validado con al menos una consulta real de un
   cliente cuya respuesta dependía de contenido de `/knowledge`.
5. **Plantilla de WhatsApp aprobada por Meta** — trámite completado, habilitando explícitamente el
   inicio de al menos una de las tres iniciativas que bloqueaba (Lead Ads, contacto de leads de
   llamada, o campañas masivas).
6. **Ningún incidente de severidad Alta o superior queda sin alertamiento automático que lo hubiera
   detectado** — criterio directo derivado del postmortem (sección 1), verificable retroactivamente
   contra cualquier incidente real que ocurra durante este ciclo.
7. **Testing Strategy mínima en CI** — al menos las invariantes ya validadas manualmente en Fase 1
   (idempotencia del webhook, forma del protocolo de confianza, migraciones aplicándose
   correctamente contra un esquema con datos existentes) corren como pruebas automatizadas en el
   gate de CI, no solo como validación manual puntual antes de cada despliegue.

Este ciclo se considera cerrado cuando los 7 criterios se cumplen — no antes, y no se requiere que
cada track (sección 4) termine al mismo tiempo, dado que están deliberadamente desacoplados.

---

## 6. Preguntas abiertas para el usuario (antes de aprobar este documento)

1. ¿Se confirma la resolución de nomenclatura propuesta en la sección 0 ("Fase 2 del Roadmap de
   Producto" / "Ciclo 2"), o se prefiere otro esquema?
2. ¿Hay objeción a secuenciar `negocio_id` **después** de observabilidad mínima y Data Architecture
   Fase 2, en vez de empezarlo de inmediato? Es la recomendación de mayor impacto de este
   documento, y la que más se aparta de lo que el Roadmap actual sugiere implícitamente (que trata
   a `negocio_id` casi como el próximo paso directo tras la Fase 1).
3. ¿Confirmás que "Automatizaciones" queda fuera del roadmap propuesto hasta tener una definición
   de alcance concreta, o hay ya una idea específica en mente que este documento debería incorporar
   con más detalle?
4. ¿La revisión de costos (ya pendiente desde antes) se ejecuta ahora, en paralelo, como se
   recomienda en el Track C, o preferís posponerla?

Si el usuario aprueba el documento (con o sin ajustes a partir de estas preguntas), el siguiente
paso formal es traducir sus decisiones en una nueva versión de
`MAIEK_AI_IMPLEMENTATION_ROADMAP.md` y, recién ahí, empezar a planificar implementación técnica
concreta — consistente con la instrucción explícita de no escribir código todavía.

---

*Fin del documento. Draft — pendiente de revisión y aprobación del usuario. No commiteado.*
