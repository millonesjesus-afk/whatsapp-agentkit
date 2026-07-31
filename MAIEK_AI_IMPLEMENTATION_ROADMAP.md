# Maiek AI — Implementation Roadmap

**Versión 1.0 · Estado: Approved**

| | |
|---|---|
| Documento | Implementation Roadmap |
| Proyecto | Maiek AI |
| Versión | 1.0 |
| Estado | **Approved** |
| Fecha de creación | 2026-07-28 |
| Autor | Claude, a pedido de Jesús Millones |
| Fecha de aprobación | 2026-07-28 |
| Última actualización | 2026-07-30 (sección 2.1 nueva — Ciclo de trabajo por incremento, institucionalizado, ver Control de versiones) |

## Dependencias

Los ocho documentos técnicos del corpus arquitectónico principal, todos Approved — este roadmap no decide nada que no esté ya decidido ahí, solo secuencia y prioriza:

- `MAIEK_AI_DATA_ARCHITECTURE.md` — en particular, Fase 3 (`negocio_id`, Multi-Tenant), el bloqueante transversal que este roadmap prioriza explícitamente; y su Fase 1 (baseline de migraciones con Alembic — *"sin esta fase, ninguna de las siguientes puede desplegarse con seguridad"*), incorporada como pista transversal dentro de la Fase 1 de este roadmap (sección 4) tras una revisión independiente del `MAIEK_AI_PHASE_1_EXECUTION_PLAN.md`.
- `MAIEK_AI_BACKEND_ARCHITECTURE.md`, `MAIEK_AI_API_ARCHITECTURE.md`, `MAIEK_AI_AI_ARCHITECTURE.md` — núcleo técnico objetivo (`ServicioInteligencia`, contrato interno, AI Orchestrator, protocolo de confianza).
- `MAIEK_AI_SECURITY_ARCHITECTURE.md`, `MAIEK_AI_DEVOPS_ARCHITECTURE.md` — Decisiones locales P1 (fail-open del webhook, rate limiting, backups, gate de CI, retries).
- `MAIEK_AI_OPERATIONS_ARCHITECTURE.md`, `MAIEK_AI_FRONTEND_ARCHITECTURE.md` — marco de incidentes, manejo de errores, adopción de MDL.
- `MAIEK_AI_SYSTEM_ARCHITECTURE.md` (MSA) — documento padre, orden de dependencia entre dominios ya declarado en su Capítulo 17.
- `MAIEK_AI_ARCHITECTURE_DOCUMENT_STANDARD.md` (ADS) v1.3 — vocabulario de Estado (`Activa`/`Objetivo`) que este roadmap reutiliza en su estrategia de sincronización (sección 9), sin redefinirlo.
- `DOCUMENTATION_INDEX.md` — roadmap documental (sección 9) del que provienen los cinco documentos derivados futuros (sección 10 de este documento).

## Consumido por

Todo trabajo de implementación futuro sobre el repositorio; los cinco documentos derivados todavía no construidos (QA Strategy, Testing Strategy, Operations Runbook, ADR Index, CHANGELOG), cuyo momento de construcción este roadmap fija explícitamente (sección 10).

## Control de versiones

| Versión | Fecha | Autor | Descripción |
|---|---|---|---|
| 1.0 (borrador) | 2026-07-28 | Claude | Primera versión — plan maestro de ejecución, puente entre el corpus arquitectónico aprobado y el inicio de la implementación. Prioriza explícitamente Data Architecture Fase 3 (`negocio_id`) como el bloqueante transversal identificado en los 8 CSAs. No es un documento de arquitectura ni contiene tareas técnicas o historias de usuario. Pendiente de revisión y aprobación. |
| 1.0 | 2026-07-28 | Claude | Aprobado sin reapertura del contenido. Marca oficialmente el inicio de la Fase de Implementación de Maiek AI. El usuario registró 2 mejoras futuras no bloqueantes, a incorporar en una versión posterior: (1) **métricas ejecutivas de avance** del roadmap (porcentaje de decisiones `Objetivo`→`Activa`, brechas cerradas, fases completadas); (2) **criterios explícitos para declarar cerrada la Fase de Implementación** y dar inicio a una fase de operación y evolución continua — hoy el documento define criterios de cierre por fase (sección 7) pero no un criterio de cierre de la fase completa. |
| 1.0 | 2026-07-29 | Claude | **Fase 0 (Estabilización) declarada oficialmente cerrada** — 32 commits desplegados a producción y verificados con tráfico real (ver `IMPLEMENTATION_REVIEW_FASE_0.md`): rama remota sincronizada, deploy de Railway `Active`/`Deployment successful`, arranque limpio, health check OK, `POST /webhook` → `200 OK` con mensajes reales, sin errores relevantes posteriores al despliegue. Sin desviaciones respecto al corpus arquitectónico. **Fase 1 (Núcleo técnico — Backend/AI/API) queda iniciada.** |
| 1.0 | 2026-07-29 | Claude | **Incorporada Data Architecture Fase 1 (baseline de Alembic) como pista transversal dentro de la Fase 1** (secciones 1, 3, 4, 8), sin bloquear el inicio de Backend/AI/API. Surgió de una revisión independiente (Opus, Principal Architect/CTO externo) del `MAIEK_AI_PHASE_1_EXECUTION_PLAN.md`, que identificó que Data Architecture ya declara su propia Fase 1 como prerrequisito de "todas las siguientes" — incluida la Fase 2 de este roadmap (`negocio_id`), que ahora declara depender también de Data Architecture Fase 1 y Fase 2, no solo del núcleo técnico. No redefine ninguna decisión ya tomada — corrige una secuenciación no declarada explícitamente hasta ahora. |
| 1.0 | 2026-07-29 | Claude | **Data Architecture Fase 1 (baseline de Alembic) implementada en código**, adelantada respecto al resto del núcleo técnico: surgió como bloqueo real durante la sub-etapa de AI (el marcador de "revisión prioritaria" del protocolo de confianza necesitaba una columna nueva en `leads`, que `create_all()` no puede agregar a una tabla ya existente en producción). El trabajo de AI se pausó explícitamente para resolver esta capacidad habilitadora antes de seguir acumulando entregables diferidos por la misma causa (Evidence over Opinion) — ver Implementation Review de esta sub-etapa. Pendiente de acción manual del usuario antes del próximo deploy: `alembic stamp head` contra la Postgres de producción. |
| 1.0 | 2026-07-30 | Claude | Aprobado sin reapertura del contenido existente. **Agrega la sección 2.1 (Ciclo de trabajo por incremento)**: institucionaliza el proceso de 8 pasos (Gap Analysis → Diseño técnico → Revisión y aprobación → Implementación → Validación → Documentación → Commit → Push y Deploy) ya aplicado y validado empíricamente en los Sprints 1-3 y la preparación del Sprint de Validación del Copiloto. Pedido explícito del usuario: que el proceso "quede definido por el proyecto y no por el contexto de una conversación" — deja de depender de la memoria de sesión. |

## Alcance

Documento puente entre la Fase de Arquitectura (cerrada con la aprobación de Frontend Architecture) y la Fase de Implementación de Maiek AI. Traduce las Decisiones locales ya `Objetivo` de los 8 documentos técnicos en un orden de ejecución basado en las dependencias que esos mismos documentos ya declararon — no introduce decisiones de diseño nuevas. No contiene tareas técnicas detalladas ni historias de usuario: es un roadmap ejecutivo y arquitectónico, a nivel de fase e hito. No es gobernado por el ADS (no es un documento de arquitectura) — sigue la gobernanza general de `DOCUMENTATION_INDEX.md` §8.

---

## 1. Objetivo de la fase de implementación

Traducir las decisiones ya `Objetivo` de los ocho dominios arquitectónicos en trabajo real, ejecutado en un orden que respete las dependencias ya declaradas entre ellos, priorizando el hallazgo que se repitió sin excepción en los 8 CSAs: la ausencia de `negocio_id` y, con ella, de cualquier aislamiento Multi-Tenant real.

Este documento no toma decisiones de diseño nuevas. Cuando la implementación revele una necesidad que el corpus no cubre, esa necesidad se resuelve como una decisión de arquitectura (reabriendo el documento correspondiente o vía ADR, sección 2) — nunca editando este roadmap para llenar el vacío.

## 2. Principios de implementación

- **Ninguna implementación puede contradecir una arquitectura Approved sin un ADR explícito** — que documente la excepción, su razón, y qué documento queda temporalmente desalineado hasta reconciliarse. El ADR Index (sección 10) es el mecanismo formal para esto, activo desde el inicio de esta fase.
- **Toda tarea de implementación debe trazarse a al menos una Decisión local ya `Objetivo`** de un documento Approved (matriz de trazabilidad, sección 8). Si un trabajo propuesto no tiene de dónde derivar, no es implementación — es una decisión de arquitectura pendiente, y vuelve al corpus antes de ejecutarse.
- **Evidence over Opinion se mantiene**: el orden y las fases de este roadmap (sección 3-4) se basan en las dependencias ya declaradas explícitamente en cada documento (Brechas conocidas, Decisiones locales "dependiente de X", Architectural Decision Impact) — no en preferencias nuevas de secuenciación.
- **Separación de responsabilidades se mantiene**: este documento prioriza y secuencia a nivel de fase; no re-especifica cómo se implementa cada decisión — ese detalle vive fuera de este roadmap, en el trabajo técnico real de cada fase.
- **Toda decisión heredada de un documento Approved rige sin excepción** — en particular, el principio ya fijado en Operations Architecture de que todo cambio que afecte a Gabi o al flujo de venta se comunica al equipo comercial antes de producción, se hereda sin repetirse.

## 2.1 Ciclo de trabajo por incremento (Sprint)

Todo incremento de implementación — cada Sprint, cada patrón de `MAIEK_AI_PRODUCT_PATTERNS.md` que
se materializa, cada decisión `Objetivo`→`Activa` de cualquiera de los 8 dominios técnicos — sigue
este ciclo, en este orden, sin saltar ni fusionar pasos:

1. **Gap Analysis** — revisar el código real (con evidencia verificable, no asumir) y compararlo
   contra el corpus documental que corresponda (Framework/MPA/MDL/CDS/MPX/Product Patterns, y/o las
   arquitecturas técnicas derivadas). Identificar qué ya existe y qué falta realmente.
2. **Diseño técnico** — propuesta corta y concreta (estructura de datos, impacto en el modelo,
   cambios mínimos necesarios, estrategia de migración si aplica) antes de escribir código.
3. **Revisión y aprobación** — el Responsable (sección "Convenciones" de `DOCUMENTATION_INDEX.md`)
   aprueba el diseño explícitamente. Sin aprobación, no hay paso 4.
4. **Implementación** — solo después de la aprobación del paso 3, nunca antes ni en paralelo.
5. **Validación** — probar de verdad (local primero; con tráfico/datos reales cuando corresponda,
   ver sección 6 de `MAIEK_AI_CONVERSATIONAL_VALIDATION_PLAN.md` como ejemplo ya vigente). No se da
   por terminado un incremento sin evidencia de que funciona.
6. **Documentación** — sincronizar `DOCUMENTATION_INDEX.md`, `CHANGELOG.md`, y cualquier documento
   del corpus que la implementación real justifique actualizar — nunca por anticipación (Principio
   "Evidence over Opinion" de la sección 2).
7. **Commit** — captura el estado ya validado y documentado.
8. **Push y Deploy** (cuando corresponda) — **decisión operativa separada de las anteriores, nunca
   implícita**. En la infraestructura actual del proyecto, Push a `deploy-main` y Deploy en Railway
   ocurren de forma acoplada (deuda de infraestructura registrada en
   `MAIEK_AI_DEVOPS_ARCHITECTURE.md`, Control de versiones, 2026-07-30) — hasta que se separen
   (ambiente de staging, todavía `Objetivo`), autorizar el paso 8 equivale a autorizar el despliegue
   a producción, y se trata como tal.

Validado empíricamente en los Sprints 1-3 (Inicio, Sidebar + CRM/Pipeline, primera implementación
del Copiloto IA) y en la preparación del Sprint de Validación del Copiloto — confirmado
explícitamente por el usuario el 2026-07-30 como el proceso a mantener, sin excepciones, en toda
fase futura del proyecto.

## 3. Orden recomendado de implementación basado en dependencias arquitectónicas

El orden no sigue la secuencia en que los documentos se aprobaron — sigue las dependencias técnicas reales que esos mismos documentos ya declararon entre sí:

1. **Estabilización** (DevOps + Security P1) no depende de ningún otro trabajo — es la base de seguridad para construir encima.
2. **Núcleo técnico objetivo** (Backend, AI, API) depende de que el sistema esté estabilizado, pero **no depende de `negocio_id`** — el protocolo de confianza, el AI Orchestrator y el contrato interno pueden implementarse en el modelo actual de un solo negocio. **Data Architecture Fase 1** (baseline de migraciones con Alembic) corre en paralelo desde el inicio de esta fase — no bloquea el arranque de Backend/AI/API, pero condiciona los entregables de esta fase que tocan esquema (sección 4).
3. **Data Architecture Fase 3** (`negocio_id`) depende de que el núcleo técnico ya esté implementado, y **de que Data Architecture Fase 1 y Fase 2 ya estén activas** (Data Architecture lo declara explícitamente: *"depende de Fase 1 y Fase 2"*) — tocar el modelo de datos para Multi-Tenant no es seguro sin ese baseline de migraciones e integridad ya resuelto. Es, a su vez, la dependencia declarada explícitamente por Security, AI, DevOps, Operations y Frontend para su propio trabajo Multi-Tenant.
4. **Extensión Multi-Tenant** a los demás dominios depende directamente de que `negocio_id` ya exista — no puede empezar antes.
5. **Observabilidad y calidad operativa** puede avanzar en paralelo a partir de la Fase 1, sin bloquear ni ser bloqueada por el trabajo Multi-Tenant.

## 4. Fases de implementación

### Fase 0 — Estabilización · ✅ Cerrada (verificada en producción, 2026-07-29)
Cierra los P1 de DevOps y Security sobre el sistema actual, sin tocar el modelo de negocio: backups automatizados, gate de CI, retries/timeout en llamadas externas (DevOps); eliminar el fail-open de verificación de firma del webhook, rate limiting en `/login` y `/webhook` (Security); marco mínimo de gestión de incidentes y roles operativos nombrados (Operations).

Cerrada con `IMPLEMENTATION_REVIEW_FASE_0.md`: 32 commits desplegados a producción (`deploy/main`), sin desviaciones respecto al corpus, deuda técnica identificada y con criterio de revisión, validación end-to-end con tráfico real de WhatsApp (`POST /webhook` → `200 OK`). Pendientes operativos que no bloquearon el cierre: configuración de Railway para el backup (bucket S3 + Cron Schedule) y activar "Require status checks to pass" en GitHub.

### Fase 1 — Núcleo técnico objetivo · 🔵 En curso
Implementa, sobre un solo negocio, las decisiones `Objetivo` de Backend (las 4 capas, `ServicioInteligencia`, los 5 servicios de dominio), AI (AI Orchestrator explícito, protocolo de confianza `{respuesta, confianza, razon}`, delimitación estructural anti-prompt-injection, prompt caching) y API (contrato interno de plataforma formalizado, idempotencia, `request_id`, modelo uniforme de errores). Los tres se implementan juntos porque están acoplados: la señal de confianza de AI fluye a través de `ServicioInteligencia`, expuesto vía el contrato interno de API.

**Pista transversal — Data Architecture Fase 1 (baseline de migraciones con Alembic).** Corre en paralelo desde el inicio de esta fase, sin bloquear el arranque de Backend/AI/API — la mayoría del trabajo del núcleo técnico no la necesita. Sí condiciona dos entregables que tocan esquema y que por eso quedan diferidos hasta que esté activa (detalle exacto en `MAIEK_AI_PHASE_1_EXECUTION_PLAN.md`, incorporado tras una revisión independiente del plan: uno depende solo de esta pista, el otro depende además de Data Architecture Fase 2). Incorporada explícitamente al roadmap porque Data Architecture ya declara que es prerrequisito no solo de estos dos entregables, sino de la Fase 2 completa (`negocio_id`) — ver punto 3 de la sección 3.

### Fase 2 — Data Architecture Fase 3 (el bloqueante transversal)
Implementa `negocio_id`, el diseño de aislamiento de datos ya definido en Data Architecture, y migra el modelo actual a una base Multi-Tenant-ready — aunque en producción siga operando un solo negocio real durante esta fase. Depende de que Data Architecture Fase 1 y Fase 2 ya estén activas (sección 3, punto 3) — no solo de que el núcleo técnico de la Fase 1 de este roadmap esté listo. Es el punto de inflexión que el usuario priorizó explícitamente: resuelve el hallazgo repetido en los 8 CSAs.

### Fase 3 — Extensión Multi-Tenant a los demás dominios
Solo puede empezar cuando la Fase 2 esté completa. Extiende `negocio_id` a: autorización/visión total (Security), prompt y configuración por negocio (AI), principio de aislamiento de recursos si se decide (DevOps), segmentación de procesos operativos (Operations), identidad de marca resoluble por negocio (Frontend).

### Fase 4 — Observabilidad y calidad operativa
Puede avanzar en paralelo desde la Fase 1. Cierra los P2 restantes: logging estructurado y alertamiento, migraciones versionadas, ambiente de staging (DevOps); KPIs de conversión y calidad de atención dependiente de `SugerenciaIA`, contenido inicial del Operations Runbook (Operations); manejo de errores unificado, adopción incremental de tokens de MDL (Frontend).

### Fase 5 — Refinamiento
Los P3 restantes de todos los dominios: lockfile de dependencias, Subresource Integrity en el CDN, documentación del principio de extensión de módulos, y el resto de las brechas de menor prioridad ya registradas en cada CSA.

## 5. Hitos principales

| Hito | Marca el fin de | Verificable cuando |
|---|---|---|
| **H1 — Sistema estabilizado** | Fase 0 | Los riesgos de severidad Alta de Security y DevOps ya no están presentes |
| **H2 — Núcleo técnico objetivo implementado** | Fase 1 | Las Decisiones locales de Backend/AI/API pasan de `Objetivo` a `Activa` en sus documentos de origen |
| **H3 — `negocio_id` implementado** | Fase 2 | El modelo de datos soporta más de un negocio, aunque solo uno esté en producción real |
| **H4 — Primera operación Multi-Tenant real** | Fase 3 | Un segundo negocio real opera sobre la plataforma, con aislamiento verificado |
| **H5 — Observabilidad y calidad operativa objetivo** | Fase 4 | Los Architecture Success Criteria de observabilidad de DevOps/Operations/Frontend se cumplen |
| **H6 — Corpus de documentos derivados completo** | Transversal, no atado a una fase única | QA Strategy, Testing Strategy, Operations Runbook, ADR Index y CHANGELOG existen y están en uso activo |

## 6. Riesgos de implementación

- **Alto** — la migración a `negocio_id` (Fase 2) toca el modelo de datos de un negocio real en producción (Gaso+/Cálidda) — cualquier error de migración tiene impacto directo en operación real, no en un entorno de prueba aislado.
- **Alto** — sin un ambiente de staging todavía implementado al momento de empezar (es brecha de la Fase 0/4), buena parte del trabajo temprano de esta fase corre un riesgo mayor del que correría si el staging ya existiera — refuerza por qué la Fase 0 va primero.
- **Medio** — el equipo de implementación es pequeño (mismo hecho ya reconocido como Architectural Constraint en Operations Architecture) — la ejecución secuencial de fases es más realista que el paralelismo agresivo, incluso donde este roadmap permite avanzar en paralelo (Fase 4).
- **Medio** — riesgo de que la implementación real diverja de lo que el corpus describe como objetivo, sin que quede registrado — mitigado por el principio de ADR obligatorio (sección 2) y el ADR Index activo desde el día uno.
- **Bajo** — riesgo de que este roadmap quede desactualizado si no se revisa al cerrar cada fase — mitigado por la estrategia de sincronización (sección 9).

## 7. Criterios para considerar terminada cada fase

- **Fase 0**: los 3 riesgos de severidad Alta de Security y los 2 de DevOps (ya documentados en sus CSAs respectivos) dejan de estar presentes; existe un registro que define al menos 2 niveles de severidad de incidente con responsable asignado (Architecture Success Criterion #1 de Operations Architecture).
- **Fase 1**: se cumplen los Architecture Success Criteria ya definidos en Backend, AI y API Architecture para sus respectivas Decisiones locales `Objetivo` — este roadmap no los repite, remite a cada documento.
- **Fase 2**: se cumple el Architecture Success Criterion de Data Architecture correspondiente a `negocio_id` — el modelo de datos soporta más de un negocio de forma verificable, sin que la operación del negocio actual se haya interrumpido.
- **Fase 3**: se cumplen los Architecture Success Criteria de Multi-Tenant ya definidos en Security, AI, DevOps, Operations y Frontend Architecture — cada uno remite a su propio documento.
- **Fase 4**: se cumplen los Architecture Success Criteria de observabilidad/calidad restantes en DevOps, Operations y Frontend Architecture.
- **Fase 5**: no tiene un criterio único — se considera cerrada cuando las Brechas conocidas de prioridad P3 de los 8 documentos quedan resueltas o explícitamente re-priorizadas.

## 8. Matriz de trazabilidad

| Arquitectura origen | Componentes afectados | Prioridad | Dependencias |
|---|---|---|---|
| DevOps Architecture — backups, gate de CI, retries/timeout | Infraestructura, pipeline de despliegue | P1 (Fase 0) | Ninguna |
| Security Architecture — eliminar fail-open del webhook, rate limiting | Webhook, autenticación del panel | P1 (Fase 0) | Ninguna |
| Operations Architecture — marco mínimo de incidentes, roles operativos | Proceso operativo, no código | P1 (Fase 0) | Ninguna |
| Backend Architecture — 4 capas, `ServicioInteligencia`, 5 servicios de dominio | Backend completo | P1 (Fase 1) | Fase 0 completa |
| AI Architecture — AI Orchestrator, protocolo de confianza, delimitación estructural | AI Engine, prompts | P1 (Fase 1) | `ServicioInteligencia` (Backend, misma fase) |
| API Architecture — contrato interno, idempotencia, `request_id` | Capa de integración interna | P1 (Fase 1) | `ServicioInteligencia` (Backend, misma fase) |
| Data Architecture Fase 1 — baseline de migraciones (Alembic) | Infraestructura de datos, transversal | P1 (paralela a Fase 1, condiciona 2 entregables) | Ninguna — no bloquea el inicio de Backend/AI/API |
| Data Architecture Fase 3 — `negocio_id`, aislamiento de datos | Modelo de datos completo | **P1 — bloqueante transversal** (Fase 2) | Fase 1 completa + Data Architecture Fase 1 y Fase 2 |
| Security Architecture — aislamiento Multi-Tenant en autorización | Modelo de autorización | P2 (Fase 3) | Data Architecture Fase 3 |
| AI Architecture — prompt/configuración por `negocio_id` | AI Engine | P2 (Fase 3) | Data Architecture Fase 3 |
| Operations Architecture — segmentación de procesos por negocio | Dashboards, KPIs | P2 (Fase 3) | Data Architecture Fase 3 |
| Frontend Architecture — identidad de marca resoluble por negocio | Interfaz, capa visual | P2 (Fase 3) | Data Architecture Fase 3 |
| DevOps/Operations/Frontend — observabilidad, KPIs, manejo de errores | Transversal | P2 (Fase 4, paralelo a Fase 1+) | Fase 0 completa |
| Todos los dominios — brechas P3 restantes | Transversal | P3 (Fase 5) | Según cada brecha |

## 9. Estrategia para mantener sincronizados arquitectura e implementación

Cuando una Decisión local `Objetivo` de un documento Approved se implementa por completo, ese documento se actualiza con una nueva fila en su Control de versiones, cambiando el Estado de esa decisión de `Objetivo` a `Activa` — reutilizando el vocabulario ya fijado en el ADS, sin inventar un estado nuevo. Este roadmap no duplica ese detalle: su matriz de trazabilidad (sección 8) vive a nivel de fase, y remite a cada documento de origen para el estado exacto de cada decisión.

Si la implementación real diverge de lo que una arquitectura `Objetivo` describía, se documenta como ADR (sección 10) en vez de editar la Decisión local en silencio — mismo principio de "nunca edición silenciosa" que ya rige todo el corpus desde el MDL v1.1.

Este roadmap se actualiza al cerrar cada fase (sección 4), no en cada tarea individual — se mantiene como brújula ejecutiva, no como registro operativo del día a día.

## 10. Próximos documentos derivados

| Documento | Cuándo se construye | Por qué en ese momento |
|---|---|---|
| **ADR Index** | Al inicio de la Fase 0 | Es el mecanismo que sostiene el principio de la sección 2 — debe existir antes de que empiece cualquier implementación, no al final |
| **Testing Strategy** | Durante la Fase 0, junto con el gate de CI de DevOps | El gate de CI necesita saber qué probar antes de poder bloquear un despliegue |
| **QA Strategy** | Durante la Fase 0-1, antes de tocar el núcleo técnico | Define el enfoque de calidad antes de implementar Backend/AI/API, no después |
| **Operations Runbook** | Empieza a poblarse en la Fase 0 (con los escenarios ya identificados en los CSAs de Security y DevOps) y se completa en la Fase 4 | El marco ya existe (Operations Architecture Approved); no hace falta esperar a Fase 4 para empezar a llenarlo con lo ya conocido |
| **CHANGELOG** | Se activa con el primer despliegue real de una decisión `Objetivo` (Fase 0 o 1) | No tiene sentido antes de que exista un primer cambio real que registrar |

---

## Cierre

Este documento marca oficialmente el inicio de la Fase de Implementación de Maiek AI. No redefine ninguna decisión del corpus arquitectónico principal, ya congelado como referencia oficial — lo traduce en una secuencia de ejecución priorizada, con el bloqueante transversal Multi-Tenant (`negocio_id`, Data Architecture Fase 3) como el punto de inflexión central. **Approved** el 2026-07-28.

---

*Fin del documento.*
