# Maiek AI — Operations Architecture

**Versión 1.0 · Estado: Approved**

| | |
|---|---|
| Documento | Operations Architecture |
| Proyecto | Maiek AI |
| Versión | 1.0 |
| Estado | **Approved** |
| Fecha de creación | 2026-07-28 |
| Autor | Claude, a pedido de Jesús Millones |
| Fecha de aprobación | 2026-07-28 |
| Última actualización | 2026-07-28 |

## Dependencias

- `MAIEK_AI_SYSTEM_ARCHITECTURE.md` (MSA) Capítulo 15 (Observabilidad), Capítulo 16 (Escalabilidad).
- `MAIEK_AI_OPERATIONS_CURRENT_STATE_ASSESSMENT.md` (CSA-Operations) — diagnóstico del que este documento parte directamente.
- `MAIEK_AI_DEVOPS_ARCHITECTURE.md` — mecanismo técnico de despliegue, backups, alertamiento — **este documento no lo redefine, solo define el proceso humano alrededor de él**.
- `MAIEK_AI_SECURITY_ARCHITECTURE.md` — modelo de roles de autorización (`admin`/`supervisor`/`asesor`) — **se cita, la responsabilidad operativa se nombra sobre esos mismos roles, no se crean roles nuevos**.
- `MAIEK_AI_BACKEND_ARCHITECTURE.md`, `MAIEK_AI_AI_ARCHITECTURE.md` — mecanismo técnico de escalamiento y `SugerenciaIA` (registro de inferencias) — **se cita, no se redefine**.
- `MAIEK_AI_ARCHITECTURE_DOCUMENT_STANDARD.md` (ADS) v1.3.

## Consumido por

`Operations Runbook` (roadmap de `DOCUMENTATION_INDEX.md`, documento hijo, procedimental — todavía no construido); Frontend Architecture (futuro), en lo relativo a cómo el panel debe exponer los indicadores que este documento define.

## Control de versiones

| Versión | Fecha | Autor | Descripción |
|---|---|---|---|
| 1.0 (borrador) | 2026-07-28 | Claude | Primera versión — arquitectura objetivo de Operations, construida sobre el CSA-Operations aprobado. Resuelve el marco de gestión de incidentes y el proceso de escalamiento (P1 del CSA) sin fijar números de SLA ni construir el Operations Runbook — ambos quedan como brechas explícitas, consistente con la disciplina de Evidence over Opinion ya aplicada en DevOps Architecture. Pendiente de revisión y aprobación. |
| 1.0 | 2026-07-28 | Claude | Aprobado sin reapertura del contenido. El usuario registró 2 recomendaciones futuras no bloqueantes, a incorporar en una versión posterior: (1) principio de que cada proceso operativo tenga un **único responsable primario** claramente identificado (hoy la sección 12 nombra roles sin exigir explícitamente unicidad de responsable por proceso); (2) declarar explícitamente que **ningún escenario crítico identificado por Security o DevOps puede quedar sin un propietario operativo asignado** — extiende el principio ya presente en la sección 9 (continuidad operacional) a una regla general y obligatoria, no solo a los dos escenarios citados como ejemplo. |

## Alcance y regla de no-duplicación

Define el **marco operativo diario** — gestión de incidentes, escalamiento, KPIs, capacidad, roles y responsabilidades — sobre los mecanismos técnicos ya decididos en DevOps, Security, Backend y AI Architecture. **No redefine** el despliegue, los backups, el modelo de autorización, ni el protocolo de confianza del AI Engine — los cita y opera sobre ellos. **No es el Operations Runbook**: define el marco y las categorías; el detalle procedimental paso a paso vive en ese documento hijo, todavía no construido (ADS §10).

---

## 1. Monitoreo operativo objetivo

Se extiende la pantalla de Métricas ya existente (no se construye un sistema nuevo) con un indicador que responda directamente "¿hoy es un día normal o no?", sin que un operador tenga que interpretar la tabla completa — un resumen, no un dashboard adicional. Este documento fija el principio; la métrica exacta que compone ese resumen depende de qué indicadores existan (sección 6).

## 2. Gestión de incidentes objetivo

**Se define un marco mínimo de severidad**: al menos dos niveles (ej. incidente que afecta la atención al cliente en vivo vs. uno que no), cada uno con un responsable claro de reaccionar y un criterio explícito de cuándo escalar de un nivel al siguiente. Es la decisión de mayor prioridad del documento (P1 del CSA). Este marco no incluye el paso a paso de qué hacer ante cada escenario — eso es contenido del futuro Operations Runbook (sección 3); acá se fija la estructura que ese Runbook deberá llenar.

## 3. Runbooks objetivo

Este documento **no construye el Operations Runbook** — ya está declarado como documento hijo, separado, en el MSA. Lo que sí define es el marco de categorías que ese Runbook deberá cubrir, para que su construcción futura no empiece desde cero: un escenario por cada hallazgo ya identificado en los CSAs de Security y DevOps (ej. canal sin `app_secret`, fallas técnicas repetidas de la IA, ausencia de backup verificado), clasificado por la severidad ya definida en la sección 2.

## 4. Gestión de cambios y releases (proceso) objetivo

**Todo cambio que afecte el comportamiento de Gabi o el flujo de venta se comunica al equipo comercial antes de llegar a producción** — cierra la brecha de proceso identificada en el CSA, sin redefinir el mecanismo técnico de despliegue (ya resuelto en DevOps Architecture). No se construye un `CHANGELOG` formal en esta versión — es una brecha ya registrada en el roadmap general, no bloqueante para este principio.

## 5. Soporte y escalamiento objetivo

Se definen niveles de soporte simples, alineados a lo que ya existe técnicamente: Gabi (primer contacto) → asesor asignado → supervisor. Cada nivel tiene una **expectativa de tiempo de respuesta declarada explícitamente** — este documento fija que debe existir y ser visible al equipo, pero **no fija el número**: es una decisión de negocio pendiente (brecha), consistente con la misma disciplina que ya difirió SLO/SLA/RPO/RTO en DevOps Architecture. El escalamiento deja de depender únicamente de "que alguien sepa qué hacer" — el marco de incidentes (sección 2) es lo que lo reemplaza como mecanismo formal.

## 6. KPIs operativos objetivo

Se agrega la **tasa de conversión por campaña** como KPI calculado — cruce de `campana_origen` y `resultado`, datos que ya existen en el modelo (Data Architecture), sin necesidad de recolectar nada nuevo. La **métrica de calidad de atención** queda como decisión **dependiente de `SugerenciaIA`** (AI Architecture, todavía no implementada) — este documento no inventa un mecanismo de cálculo propio y paralelo; cuando esa entidad exista, la calidad de atención se deriva de ahí, no de una solución ad-hoc de Operations.

## 7. Dashboards operativos objetivo

Los nuevos KPIs (sección 6) se agregan al panel ya existente — no se construye un sistema de *dashboards* separado. Principio: cualquier indicador operativo nuevo vive donde el equipo comercial ya mira, no en una herramienta adicional que compita por atención.

## 8. Gestión de capacidad objetivo

Se preserva el balanceo en tiempo real (nivel de asesor, carga activa, cola de espera repartida) como decisión **Activa** — ya está bien resuelto. Se agrega el principio de una **revisión periódica de capacidad** (¿el equipo de asesores alcanza para el volumen actual?) — sin fijar la cadencia exacta, que es una decisión operativa de negocio, no arquitectónica.

## 9. Continuidad operacional objetivo

Para los escenarios ya identificados como riesgo en los CSAs de Security y DevOps (fail-open del webhook, ausencia de backup verificado), debe existir un rol designado que sepa qué hacer si ocurren — este documento no construye un plan de continuidad de negocio completo, solo asegura que cada riesgo ya conocido tiene un responsable nombrado (sección 12), no queda huérfano.

## 10. Procesos de mantenimiento objetivo

Si se necesita una ventana de mantenimiento, se comunica con anticipación al equipo comercial — Gabi es la cara del negocio ante el cliente, y el equipo necesita saber si va a estar degradada. El mecanismo técnico de un modo de mantenimiento en sí (si se decide construir) es una decisión de DevOps Architecture, no de este documento.

## 11. Preparación para operación SaaS Multi-Tenant

Se reafirma, sin diseñar el mecanismo, el mismo principio ya declarado en los seis documentos anteriores: cuando `negocio_id` exista (Data Architecture Fase 3), los procesos operativos definidos acá — incidentes, escalamiento, KPIs, capacidad — deben poder segmentarse por negocio. No se resuelve el mecanismo técnico acá.

## 12. Roles y responsabilidades operativas objetivo

**Se nombran explícitamente los roles operativos** sobre los mismos roles de autorización ya definidos en Security Architecture (`admin`/`supervisor`/`asesor`) — no se crean roles nuevos, se asigna responsabilidad operativa sobre los que ya existen: quién es responsable de monitorear la pantalla de Métricas, quién responde ante una escalación de incidente, quién es el punto de contacto para decisiones de negocio (ej. ajustar un umbral de asignación). **No se define una rotación de guardia/on-call formal** — decisión explícita, no una omisión: no hay evidencia hoy de que el volumen lo justifique (Evidence over Opinion).

---

## Architectural Constraints

| Restricción | Naturaleza | Impacto en el diseño |
|---|---|---|
| El equipo operativo actual es pequeño (1-2 personas cubren roles de supervisión/administración) | Hecho de la situación actual del negocio, no una elección arquitectónica | Justifica no definir una rotación de guardia formal (sección 12) ni una cadencia fija de revisión de capacidad (sección 8) |
| Ningún proveedor de gestión de incidentes (PagerDuty, Opsgenie, etc.) está integrado hoy | Hecho ya confirmado en el CSA-DevOps | El marco de incidentes (sección 2) se define independiente de herramienta, para no bloquearse en una decisión de tooling |
| La métrica de calidad de atención depende de que `SugerenciaIA` exista (AI Architecture) | Constraint de secuencia entre documentos, no una elección de este documento | La sección 6 declara esa dependencia explícitamente en vez de inventar un mecanismo paralelo |

## Decisiones locales

| Decisión | Estado | Justificación | Criterio de revisión |
|---|---|---|---|
| Marco mínimo de gestión de incidentes (severidad, responsable, cuándo escalar) | Objetivo | P1 del CSA | — |
| Framework de categorías para el futuro Operations Runbook (no el Runbook en sí) | Objetivo | Evita que su construcción futura empiece desde cero | — |
| Todo cambio que afecte a Gabi o al flujo de venta se comunica al equipo antes de producción | Objetivo | Cierra brecha de proceso del CSA | — |
| Niveles de soporte (Gabi → asesor → supervisor) con expectativa de tiempo de respuesta declarada, sin fijar el número | Objetivo | P1 del CSA; el número es decisión de negocio pendiente | Cuando el negocio defina un SLA real |
| Tasa de conversión por campaña como KPI calculado | Objetivo | Datos ya existentes, sin recolección nueva | — |
| Métrica de calidad de atención dependiente de `SugerenciaIA` | Objetivo, dependiente de AI Architecture | Evita un mecanismo paralelo al ya decidido en AI Architecture | Cuando `SugerenciaIA` se implemente |
| Revisión periódica de capacidad, sin cadencia fija | Objetivo | Principio sí, número no — decisión operativa de negocio | Cuando exista evidencia de sobrecarga real |
| Roles operativos nombrados explícitamente sobre los roles de autorización ya existentes | Objetivo | P1/P2 del CSA | — |
| Sin rotación de guardia/on-call formal | **Activa** (exclusión deliberada) | Sin evidencia de que el volumen actual lo justifique | Si el equipo o el volumen de incidentes crece |
| Comunicación anticipada de ventanas de mantenimiento al equipo comercial | Objetivo | Bajo costo, cierra brecha de proceso | — |

## Brechas conocidas

- **Número exacto de tiempo de respuesta esperado (SLA)** → decisión de negocio, explícitamente diferida (mismo criterio que SLO/SLA/RPO/RTO en DevOps Architecture).
- **Contenido detallado del Operations Runbook** → documento aparte, hijo de este, todavía no construido.
- **Mecanismo técnico de modo de mantenimiento** → DevOps Architecture, si se decide construir.
- **Segmentación Multi-Tenant de procesos operativos** → Data Architecture Fase 3.
- **Gestión del conocimiento operativo (SOPs) y auditoría operativa periódica** → registradas como mejora futura del CSA-Operations, no incorporadas en esta versión del documento objetivo.

## Architecture Success Criteria

1. Existe un registro que define al menos 2 niveles de severidad de incidente y quién responde a cada uno. Verificable revisando ese registro.
2. Todo cambio que afecte el comportamiento de Gabi o el flujo de venta tiene un registro de comunicación al equipo comercial antes de llegar a producción. Verificable comparando el historial de comunicaciones contra el historial de despliegues.
3. La tasa de conversión por campaña es consultable en el panel sin cruzar datos manualmente. Verificable navegando a la pantalla de campañas/métricas.
4. Existe un documento que nombra explícitamente quién es responsable de monitorear la pantalla de Métricas y quién responde ante una escalación. Verificable revisando ese documento.
5. Cuando `SugerenciaIA` exista, la calidad de atención es consultable como un indicador calculado, no solo mediante lectura manual de transcripciones. Verificable una vez esa dependencia esté resuelta — criterio explícitamente condicional.

## QA arquitectónico

Este documento fue verificado contra el checklist de 11 preguntas del ADS §11 antes de presentarse — en particular, se confirmó que ninguna Decisión local fija un número que el CSA no respaldó con evidencia (el tiempo de respuesta y la cadencia de revisión de capacidad quedan explícitamente como brechas, no como decisiones inventadas), y que las 5 Architecture Success Criteria son verificables, incluyendo el criterio #5 marcado explícitamente como condicional a una dependencia externa.

## Cierre

Este documento cierra el diseño objetivo del dominio de Operations, construido sobre el CSA-Operations ya aprobado y sin redefinir ninguna decisión ya tomada en Data, Backend, API, AI, Security o DevOps Architecture — solo define el marco operativo humano que opera sobre esos mecanismos ya decididos. **Approved** el 2026-07-28.

---

*Fin del documento.*
