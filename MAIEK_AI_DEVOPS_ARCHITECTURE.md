# Maiek AI — DevOps Architecture

**Versión 1.0 · Estado: Approved**

| | |
|---|---|
| Documento | DevOps Architecture |
| Proyecto | Maiek AI |
| Versión | 1.0 |
| Estado | **Approved** |
| Fecha de creación | 2026-07-28 |
| Autor | Claude, a pedido de Jesús Millones |
| Fecha de aprobación | 2026-07-28 |
| Última actualización | 2026-07-28 |

## Dependencias

- `MAIEK_AI_SYSTEM_ARCHITECTURE.md` (MSA) Capítulo 14 (Infraestructura/Despliegue), Capítulo 15 — resuelve las brechas que el MSA ya declaró explícitamente para este documento: ambiente de staging, pipeline de CI formal, políticas de rollback.
- `MAIEK_AI_DEVOPS_CURRENT_STATE_ASSESSMENT.md` (CSA-DevOps) — diagnóstico del que este documento parte directamente.
- `MAIEK_AI_SECURITY_ARCHITECTURE.md` — brechas ya derivadas explícitamente hacia DevOps: rotación calendarizada de credenciales, escaneo de vulnerabilidades/SBOM, ejecución operativa del rate limiting — **este documento las resuelve, no las redefine**.
- `MAIEK_AI_API_ARCHITECTURE.md` — uso operativo real de `request_id` — **se implementa acá, no se redefine**.
- `MAIEK_AI_AI_ARCHITECTURE.md` — costo/eficiencia de inferencia como preocupación operativa — **se cita, no se redefine**.
- `MAIEK_AI_DATA_ARCHITECTURE.md` — modelo de datos y `negocio_id` (Fase 3) — contexto para la sección de preparación Multi-Tenant.
- `MAIEK_AI_ARCHITECTURE_DOCUMENT_STANDARD.md` (ADS) v1.3.

## Consumido por

Frontend Architecture, Operations Architecture (futuros) — en particular, Operations Architecture hereda directamente el principio de alertamiento (sección 7) y las Architecture Success Criteria de este documento como base de sus runbooks.

## Control de versiones

| Versión | Fecha | Autor | Descripción |
|---|---|---|---|
| 1.0 (borrador) | 2026-07-28 | Claude | Primera versión — arquitectura objetivo de DevOps, construida sobre el CSA-DevOps aprobado. Resuelve las brechas ya delegadas explícitamente por el MSA, Security, API y AI Architecture. No incorpora todavía Infrastructure as Code ni Objetivos operativos (SLO/SLA/RPO/RTO) — quedan registrados como mejora futura del CSA, no como parte de este documento, en línea con Evidence over Opinion: no se fijan objetivos operativos que el CSA todavía no estableció. Pendiente de revisión y aprobación. |
| 1.0 | 2026-07-28 | Claude | Aprobado sin reapertura del contenido. El usuario registró 3 mejoras futuras no bloqueantes, a incorporar en una versión posterior: (1) principio arquitectónico de **Deployment Strategy** (promoción de versiones y estrategia de despliegue), independiente de herramientas concretas; (2) declarar explícitamente que los **backups deben validarse mediante restauraciones periódicas**, no solo existir — hoy la sección 5 y el Architecture Success Criterion #2 solo exigen que el backup exista y sea restaurable, no que se restaure periódicamente como práctica continua; (3) ampliar el principio de observabilidad (sección 6) para indicar que la plataforma debe producir **logs, métricas y health checks como señales complementarias**, sin decidir aún las herramientas específicas — hoy la sección 6 solo cubre logs estructurados. |

## Alcance y regla de no-duplicación

Define **cómo debe operarse** el sistema para cerrar las brechas que Data, Backend, API, AI y Security Architecture ya le dejaron explícitamente asignadas — despliegue, CI/CD, configuración, backups, observabilidad, alertamiento, recuperación ante fallos, cadena de suministro y automatización operativa. **No redefine** el modelo de datos, el protocolo de confianza del AI Engine, el contrato de API, ni ninguna decisión de seguridad ya tomada — cita esos documentos y resuelve exclusivamente la ejecución operativa de lo que le delegaron (ADS §10).

---

## 1. Arquitectura de despliegue y entornos objetivo

Se preserva Railway + Docker como decisión Activa — proporcional al tamaño actual del proyecto, ya funcional. Se agrega un **ambiente de staging**, resolviendo la brecha que el propio MSA ya había declarado (MSA:323): todo cambio se despliega primero a staging, se verifica, y solo entonces se promueve a producción. Se fija la imagen base del `Dockerfile` a una versión exacta (no un tag flotante) — bajo costo, elimina una fuente de variabilidad no controlada entre builds.

## 2. CI/CD y estrategia de releases objetivo

**Se introduce un gate de pruebas automatizado, bloqueante, antes de cualquier despliegue a producción** — la decisión de mayor prioridad de todo el documento (P1 del CSA). El principio: ningún cambio llega a producción sin pasar primero por un paso de verificación automatizada que pueda rechazarlo. Este documento fija el principio arquitectónico, no la herramienta de CI concreta ni el framework de pruebas — esa es una decisión de implementación, proporcional a cuándo el equipo defina qué se prueba primero.

## 3. Gestión de configuración y variables de entorno objetivo

Se generaliza el patrón de *fail-fast* que hoy solo cubre `WHATSAPP_PROVIDER` y (parcialmente) `SESSION_SECRET_KEY`: **toda variable de entorno cuya ausencia causaría un comportamiento silenciosamente incorrecto debe hacer fallar el arranque del proceso**, no fallar en su primer uso ni degradarse en silencio. Esto no es una decisión de seguridad (ya resuelta en Security Architecture) sino de operación: un proceso que arranca "aparentemente bien" con una dependencia crítica ausente es un incidente que se descubre tarde.

## 4. Gestión de secretos objetivo (operativa)

Se hereda, sin redefinir, la decisión de Security Architecture de que toda credencial debe poder rotarse. Este documento resuelve el **cómo operativo**: las credenciales no destructivas (`ANTHROPIC_API_KEY`, credenciales de Meta, `RESEND_API_KEY`, `DATABASE_URL`) se rotan actualizando la variable en Railway sin downtime — ya cierto hoy por diseño, se formaliza como decisión Activa. `CANAL_ENCRYPTION_KEY`, cuya rotación es destructiva por naturaleza (invalida los canales ya cifrados), queda como brecha conocida — su resolución (ej. un mecanismo de re-cifrado) no es una decisión operativa pura, involucra a Data y Security Architecture en conjunto.

## 5. Base de datos, migraciones y backups objetivo

**Backups automatizados de la base de datos de producción** — P1 del CSA, decisión objetivo, verificable independientemente de lo que el plan contratado de Railway ofrezca por defecto (Architectural Constraint, sección más abajo). **Migraciones versionadas** (ej. Alembic) reemplazan `Base.metadata.create_all` para cualquier cambio que altere una columna ya existente — `create_all` se conserva solo para la creación inicial de tablas nuevas, no para evolucionarlas. Se fija *connection pooling* explícito en el motor de base de datos, en vez de depender de los valores por defecto de SQLAlchemy.

## 6. Observabilidad objetivo

El logging pasa a formato estructurado (JSON), sin lo cual ningún alertamiento ni correlación de eventos es viable en la práctica. El principio central: **los logs de un mismo `request_id`** (ya definido como identificador técnico de correlación en API Architecture) **deben ser rastreables de punta a punta** — desde que entra una solicitud hasta que se resuelve, incluyendo cualquier llamada externa que dispare. Este documento no elige un proveedor de métricas/trazas específico (Prometheus, OpenTelemetry, Sentry, etc.) — es una decisión de implementación proporcional al volumen real, no una decisión arquitectónica de esta versión.

## 7. Monitoreo y alertamiento objetivo

**Todo error no manejado — en el webhook, en una tarea de arranque, o en una llamada externa fallida tras agotar sus reintentos — debe generar una alerta operativa, no solo quedar en un log.** Es el principio central de esta sección (P2 del CSA); la herramienta concreta (email, Slack, u otra) es una decisión de implementación, no arquitectónica. El *health check* (`GET /`) se extiende para verificar también la conectividad a la base de datos, no solo que el proceso esté vivo.

## 8. Recuperación ante fallos y rollback objetivo

**Todo despliegue debe ser reversible a la versión anterior sin pérdida de datos** — resuelve la brecha que el MSA ya había declarado explícitamente (MSA:329). **Toda llamada a Anthropic, Meta o Resend debe tener un timeout explícito y al menos un reintento con backoff** — P1 del CSA, cierra la omisión de robustez más transversal identificada. Un *circuit breaker* completo queda como brecha, no como decisión — no hay evidencia hoy de que el volumen de fallos lo justifique (Evidence over Opinion); se revisará si los reintentos con backoff resultan insuficientes en la práctica.

## 9. Gestión de dependencias y cadena de suministro objetivo

Se fija un archivo de bloqueo de dependencias (lockfile) y se fija la imagen base del `Dockerfile` a una versión exacta — P3 del CSA, pero de bajo costo, se decide igual. El **escaneo de vulnerabilidades** (brecha ya delegada por Security Architecture) se resuelve como un paso más del pipeline de CI (sección 2) — no una herramienta separada a mantener, sino parte del mismo gate que ya bloquea despliegues.

## 10. Costos operativos y escalabilidad objetivo

Se fijan límites explícitos de recursos (CPU/memoria) en la configuración de despliegue — P3 del CSA. El ajuste de *connection pooling* para un escenario de múltiples instancias queda como brecha condicional: no se diseña hasta que exista evidencia real de necesidad de escalar horizontalmente. La revisión de costos por proveedor (Railway, Anthropic, Meta, Resend) ya está registrada como pendiente en memoria del proyecto — es una revisión contable, no arquitectónica, y no se resuelve en este documento.

## 11. Automatización operativa objetivo

**Las tareas de siembra y corrección de datos se separan del ciclo de arranque del servidor de aplicación** — pasan de vivir dentro de `lifespan()` a ser un paso de *release* independiente, ejecutado antes de que el servidor reciba tráfico, no en cada reinicio del proceso. En particular, cualquier tarea de corrección de datos debe ser idempotente **con una guarda explícita** que impida repetirla sobre datos ya corregidos — cierra la deuda técnica señalada en el CSA. La migración manual de usuarios (`scripts/migrar_usuarios_a_railway.py`) se mantiene como decisión Activa, manual — proporcional a su frecuencia de uso real (un evento raro, no un proceso recurrente).

## 12. Preparación para operación SaaS Multi-Tenant

Se hereda, sin diseñar el mecanismo, el mismo principio ya declarado por Data, AI y Security Architecture: el aislamiento de recursos por `negocio_id` es una decisión que se toma junto con Data Architecture Fase 3, no antes. Este documento solo deja establecido qué deberá extenderse cuando eso ocurra: los logs estructurados (sección 6) y las alertas (sección 7) deberán poder filtrarse por negocio, no solo por proceso — sin que eso implique diseñarlo ahora.

---

## Architectural Constraints

| Restricción | Naturaleza | Impacto en el diseño |
|---|---|---|
| Railway no expone un pipeline de CI nativo integrado | Hecho de la plataforma actual | Cualquier gate de pruebas (sección 2) requiere un servicio externo (ej. GitHub Actions) que se ejecute antes del deploy |
| El mecanismo de despliegue de Railway (a partir de push a la rama conectada) no tiene, desde este repositorio, control nativo documentado de estrategia blue-green/rolling | Hecho de la plataforma actual, no verificado en código | La política de rollback (sección 8) debe apoyarse en un mecanismo propio, no asumir capacidades de la plataforma sin confirmarlas |
| Si el plan de Railway contratado incluye backups automáticos de Postgres es un hecho externo no confirmado desde este repositorio | Hecho a verificar, no una decisión de este documento | La decisión de backups (sección 5) se declara verificable independientemente de lo que el plan ofrezca — no se asume que ya está resuelto |
| El costo de inferencia de IA es proporcional a tokens de entrada/salida | Hecho del proveedor, heredado de AI Architecture | No se redefine acá; solo se cita como contexto de la sección 10 |

## Decisiones locales

| Decisión | Estado | Justificación | Criterio de revisión |
|---|---|---|---|
| Ambiente de staging | Objetivo | Resuelve brecha ya declarada en el MSA | Si el volumen de cambios no justifica el costo de mantenerlo |
| Gate de CI con pruebas automatizadas, bloqueante antes de deploy | Objetivo | P1 del CSA | — |
| Fail-fast consistente para toda variable de entorno crítica | Objetivo | Cierra comportamiento silenciosamente incorrecto en el arranque | — |
| Backups automatizados de Postgres, verificados independientemente del plan de Railway | Objetivo | P1 del CSA | Cuando se confirme qué ofrece el plan contratado (Architectural Constraint) — ajusta el mecanismo, no elimina la decisión |
| Migraciones versionadas reemplazando `create_all` para cambios de columna | Objetivo | P2 del CSA | — |
| Retries con backoff y timeout explícito en llamadas a Anthropic/Meta/Resend | Objetivo | P1 del CSA | — |
| Logging estructurado (JSON), correlacionable por `request_id` | Objetivo | Base de observabilidad; sin esto ningún alertamiento es viable | — |
| Todo error no manejado genera una alerta operativa, no solo un log | Objetivo | P2 del CSA | — |
| Separar siembra/corrección de datos del ciclo de arranque del servidor | Objetivo | Cierra deuda técnica ya señalada en el CSA | — |
| Migración manual de usuarios sigue siendo manual | **Activa** | Proporcional a su frecuencia de uso real | Si se vuelve un proceso recurrente |
| Lockfile de dependencias + imagen base fijada | Objetivo | P3 del CSA, bajo costo | — |
| Escaneo de vulnerabilidades como paso del pipeline de CI | Objetivo | Resuelve brecha ya delegada por Security Architecture | — |

## Brechas conocidas

- **Mecanismo de re-cifrado tras rotar `CANAL_ENCRYPTION_KEY`** → sin dueño único; involucra a Data y Security Architecture en conjunto.
- **Herramienta específica de alertamiento** (email, Slack, u otra) → decisión de implementación, no arquitectónica.
- **Confirmación de qué backups ofrece el plan de Railway contratado** → verificación externa pendiente, fuera del alcance de este repositorio.
- **Aislamiento de infraestructura Multi-Tenant** → depende de Data Architecture Fase 3.
- **SLO/SLA/RPO/RTO** → explícitamente fuera de este documento; el usuario los registró como mejora futura del CSA-DevOps, no como parte de esta versión — no se fijan objetivos operativos que el CSA todavía no estableció.
- **Infrastructure as Code** → mismo criterio: registrado como mejora futura del CSA, no incorporado acá.

## Architecture Success Criteria

1. Ningún despliegue a producción ocurre sin pasar antes por un paso de pruebas automatizadas capaz de bloquearlo. Verificable revisando la configuración del pipeline de CI.
2. Existe un backup de la base de datos de producción, restaurable y verificado, independientemente de lo que el plan de Railway ofrezca por defecto. Verificable restaurando un backup de prueba.
3. Toda llamada a Anthropic, Meta o Resend tiene un timeout explícito y al menos un reintento con backoff. Verificable inspeccionando el código de cada cliente HTTP/SDK.
4. Toda variable de entorno cuya ausencia causaría un comportamiento silenciosamente incorrecto hace fallar el arranque del proceso. Verificable removiendo cada variable crítica y confirmando que el proceso no arranca.
5. Los logs de un mismo `request_id` son rastreables de punta a punta. Verificable siguiendo un `request_id` a través de las distintas líneas de log que genera un mismo evento.
6. Las tareas de siembra/corrección de datos pueden ejecutarse independientemente del arranque del servidor de aplicación. Verificable ejecutándolas como paso separado, sin iniciar `uvicorn`.

## QA arquitectónico

Este documento fue verificado contra el checklist de 11 preguntas del ADS §11 antes de presentarse — en particular, se confirmó que las Architectural Constraints listadas son hechos de la plataforma o pendientes de verificación externa (no decisiones disfrazadas), y que ninguna de las 6 Architecture Success Criteria depende de una herramienta específica todavía no decidida (todas son verificables independientemente de qué CI/alertamiento/migración concreta se elija).

## Cierre

Este documento cierra el diseño objetivo del dominio de DevOps, construido sobre el CSA-DevOps ya aprobado y sin redefinir ninguna decisión ya tomada en Data, Backend, API, AI o Security Architecture — solo resuelve las brechas que esos documentos ya le dejaron explícitamente asignadas. **Approved** el 2026-07-28.

---

*Fin del documento.*
