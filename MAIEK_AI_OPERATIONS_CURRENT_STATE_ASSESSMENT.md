# Maiek AI — Current State Assessment: Operations Architecture

**Versión 1.0 · Estado: Approved**

| | |
|---|---|
| Documento | Current State Assessment – Operations Architecture |
| Proyecto | Maiek AI |
| Versión | 1.0 |
| Estado | **Approved** |
| Fecha de creación | 2026-07-28 |
| Autor | Claude, a pedido de Jesús Millones |
| Fecha de aprobación | 2026-07-28 |
| Última actualización | 2026-07-28 |

## Dependencias

- `MAIEK_AI_SYSTEM_ARCHITECTURE.md` (MSA) Capítulo 15 (Observabilidad), Capítulo 16 (Escalabilidad) — ya delega explícitamente a Operations Architecture "la elección de herramientas y dashboards" (MSA:341) y declara la relación con el futuro **Operations Runbook** (documento hijo, procedimental, no arquitectónico — MSA:379).
- `MAIEK_AI_DEVOPS_ARCHITECTURE.md` — mecanismo técnico de despliegue, CI, backups, retries, observabilidad estructurada — **este CSA no re-analiza infraestructura ni desarrollo, solo cita el mecanismo ya resuelto y audita el proceso operativo alrededor de él**.
- `MAIEK_AI_SECURITY_ARCHITECTURE.md` — hallazgos ya identificados (fail-open del webhook, ausencia de rate limiting) que necesitan un proceso operativo que reaccione ante ellos.
- `MAIEK_AI_BACKEND_ARCHITECTURE.md`, `MAIEK_AI_AI_ARCHITECTURE.md` — mecanismo técnico de escalamiento a un asesor humano (ya decidido, no redefinido acá).
- `MAIEK_AI_PRODUCT_ARCHITECTURE.md` (MPA) — roles de alto nivel (Administrador/Supervisor/Vendedor-Asesor), de los que este CSA distingue explícitamente la responsabilidad **operativa** (quién monitorea, quién responde) de la autorización técnica ya resuelta en Security Architecture.
- `MAIEK_AI_ARCHITECTURE_DOCUMENT_STANDARD.md` (ADS) v1.3.

## Consumido por

`MAIEK_AI_OPERATIONS_ARCHITECTURE.md` (Operations Architecture, todavía no construida); indirectamente, el futuro `Operations Runbook` (roadmap de `DOCUMENTATION_INDEX.md`, no un documento oficial todavía).

## Control de versiones

| Versión | Fecha | Autor | Descripción |
|---|---|---|---|
| 1.0 (borrador) | 2026-07-28 | Claude | Primera versión — auditoría objetiva del estado real de la operación diaria de la plataforma (`agent/dashboard.py`, `agent/asignacion.py`, `agent/notificaciones.py`, `agent/main.py`, `agent/memory.py`, documentación de roadmap), sobre las 12 dimensiones pedidas por el usuario. Explícitamente NO cubre infraestructura ni desarrollo (ya resuelto en DevOps Architecture). Sin propuestas de solución. Pendiente de revisión y aprobación. |
| 1.0 | 2026-07-28 | Claude | Aprobado sin reapertura del contenido. El usuario registró 2 mejoras futuras no bloqueantes, a incorporar en una versión posterior de este CSA: (1) **Gestión del conocimiento operativo** — auditar el estado actual de documentación operativa, base de conocimiento interna, SOPs o mecanismos equivalentes para preservar el conocimiento del equipo (hoy: ninguno confirmado más allá del conocimiento informal ya señalado en este CSA); (2) **Auditoría operativa** — registrar si existen procesos periódicos para revisar cumplimiento de procedimientos, calidad de la operación, o evolución de los KPIs operativos a lo largo del tiempo (hoy: ninguno confirmado). |

## Alcance

Auditoría objetiva del estado real de la **operación diaria** de la plataforma — monitoreo operativo, gestión de incidentes, runbooks, gestión de cambios/releases (proceso, no mecanismo técnico), soporte y escalamiento, KPIs, dashboards operativos, gestión de capacidad, continuidad operacional, mantenimiento, operación Multi-Tenant y roles/responsabilidades operativas — con evidencia de código y documentación citada por archivo y línea. Excluye deliberadamente infraestructura, despliegue y desarrollo (dominio ya cerrado por DevOps Architecture) y el modelo de autorización técnica (ya cerrado por Security Architecture) — ambos se citan como contexto, no se re-analizan.

---

## 1. Monitoreo operativo

El único monitoreo operativo real hoy vive como una pantalla de "Métricas" dentro del panel (`agent/dashboard.py`), no como un subsistema separado: `ETAPAS_FUNNEL` (`dashboard.py:108`, 4 etapas pre-venta) y `ETIQUETAS_FUNNEL` (`dashboard.py:109-115`, incluye `"vendido"`) alimentan `_calcular_embudo(leads)` (`dashboard.py:214-240`), que se renderiza junto con la lista completa de leads en `_contenido_metricas(leads)` (`dashboard.py:1687-1816`), servido en `GET /dashboard/metricas` (`dashboard.py:1818`).

No existe ninguna pantalla distinta de "¿el negocio está bien hoy?" más allá de este embudo y la lista de leads — sin alertas de anomalías, sin comparación día a día, sin ningún indicador que resuma la salud operativa sin que un humano interprete la tabla completa.

## 2. Gestión de incidentes

Ausente, confirmado por búsqueda exhaustiva: no hay niveles de severidad, estado de incidente, ni proceso de postmortem implementados en código ni documentados. El único concepto de "incidente" que existe en todo el proyecto son referencias futuras en el roadmap — el propio `DOCUMENTATION_INDEX.md` (sección 9) y el MSA ya anticipan que el **Operations Runbook** cubrirá "procedimientos operativos (incidentes, rollback, monitoreo)" — todavía no construido.

## 3. Runbooks

No existe ningún archivo ni sección de procedimientos operativos paso a paso. El propio MSA ya distingue esto explícitamente como un documento aparte: *"Operations Runbook queda como documento aparte, más operativo/procedimental (pasos concretos ante un incidente), hijo de Operations Architecture"* (`MAIEK_AI_SYSTEM_ARCHITECTURE.md:379`). Este CSA lo cita como brecha ya reconocida por el propio corpus, no como un hallazgo nuevo — el marco que Operations Architecture debe definir es distinto del detalle procedimental que irá en el Runbook.

## 4. Gestión de cambios y releases (proceso, no mecanismo técnico)

El mecanismo técnico (CI, staging, política de rollback) ya fue resuelto en DevOps Architecture — se cita, no se re-analiza. Desde el ángulo de **proceso** falta todo lo demás: no existe `CHANGELOG`, no existe un ADR Index, y no hay ningún proceso documentado de quién aprueba un release o cómo se comunica al equipo comercial que algo cambió — ambos ya registrados como roadmap futuro, no construido (`DOCUMENTATION_INDEX.md` sección 9).

## 5. Soporte y escalamiento

Se cita, sin re-analizar el mecanismo técnico ya establecido en Backend/AI Architecture: escalamiento automático tras 2 fallas técnicas consecutivas de la IA (`agent/main.py:233-262`), y derivación conversacional a un asesor vía `elegir_asesor_automatico` (`agent/asignacion.py:58-85`) cuando el flujo llega a `derivado_asesor` (`agent/main.py:274-287`).

Lo que este CSA agrega, desde el ángulo de proceso: la notificación por correo al derivar (`agent/notificaciones.py:26-61`) describe, en su propio docstring, que automatiza únicamente **el primer paso** de un proceso que hoy sigue siendo mayormente manual — *"mientras la derivación a Genesys Cloud no está lista... automatiza el primer paso del proceso actual (supervisor de ventas deriva manualmente al asesor por WhatsApp)"*. No existe ningún nivel de soporte definido (L1/L2/L3) ni un tiempo de respuesta esperado documentado en ningún punto del proyecto.

## 6. KPIs operativos

Lo que efectivamente se calcula hoy: conteo acumulado y porcentaje por etapa del embudo (`_calcular_embudo`, sección 1); conteo de leads activos por asesor (`contar_leads_activos_por_asesor`, `agent/memory.py:797`); un mini-embudo de navegación de 7 estados (`_mini_embudo_unificado`, `dashboard.py:1163-1185`) que el propio código aclara explícitamente que **no** es un KPI de resumen, sino solo un filtro de navegación (comentario en `dashboard.py:1578`).

Lo que no se calcula, pese a que el panel se presenta explícitamente como una herramienta para "revisar la calidad de atención de Gabi" (docstring, `dashboard.py:4-8`): no hay tasa de conversión por campaña (solo conteo crudo del lead ya asociado a `campana_origen`), no hay métrica de tiempo de respuesta, y no hay ningún indicador calculado de calidad de atención — la revisión de calidad hoy es 100% manual, leyendo la transcripción completa.

## 7. Dashboards operativos

Rutas confirmadas: `GET /dashboard/metricas` (embudo + tabla completa de leads), `GET /dashboard/metricas/exportar.csv` y `.xlsx` (`dashboard.py:1855,1876`), `GET /dashboard` (bandeja principal, incluye un panel de carga de equipo solo si el usuario tiene visión total — `dashboard.py:1232-1260`), `GET /dashboard/asesores` (gestión de equipo), `GET /dashboard/campanas` (conteo crudo por campaña, sin métrica de conversión dedicada).

No existe ningún dashboard de "desempeño de equipo" dedicado más allá del panel de carga embebido en la bandeja principal.

## 8. Gestión de capacidad

El balanceo de capacidad en tiempo de ejecución está más elaborado de lo esperado: `disponible` (`agent/memory.py:287`, toggle manual del propio asesor) filtra candidatos; `NIVELES`/`UMBRAL_SENIOR_DEFAULT`/`UMBRAL_INTERMEDIO_DEFAULT` (`agent/asignacion.py:20-25`, configurables desde el panel) exigen un nivel de asesor según el valor estimado del producto de interés; `elegir_asesor_automatico` (`asignacion.py:58-85`) balancea por carga activa (menor carga primero); y `asignar_lead_pendiente_a_asesor` (`asignacion.py:88-120`) reparte la cola de espera de a uno por asesor que se conecta, explícitamente para no volcar todo el backlog acumulado sobre el primero disponible (docstring, líneas 89-101).

Lo que no existe: ningún proceso de planificación de capacidad — cuántos leads o mensajes por día soporta el equipo, techo de conversaciones concurrentes — solo balanceo reactivo en tiempo de ejecución, sin ninguna documentación de planificación hacia adelante.

## 9. Continuidad operacional

Ausente. No hay plan de continuidad de negocio ni documentación de "qué hacer si X crítico cae" desde un ángulo de proceso (distinto de los backups/rollback técnicos ya resueltos en DevOps Architecture). La palabra "continuidad" aparece en MPX, pero referida a continuidad de la **sesión del usuario** (personalización y continuidad, un concepto de experiencia de producto) — no debe confundirse con continuidad operacional del negocio, que no tiene ninguna cobertura documental hoy.

## 10. Procesos de mantenimiento

Ausente. No existe un modo de mantenimiento, ninguna ventana de mantenimiento programada, ni ningún camino de código que degrade el servicio deliberadamente para una tarea de mantenimiento — confirmado por búsqueda exhaustiva en código y documentación.

## 11. Operación SaaS Multi-Tenant

Confirmado, consistente con los seis documentos anteriores: ninguna segmentación operativa por negocio en dashboards, métricas, cola de soporte o balanceo de capacidad — todo opera sobre una única tabla plana de `Lead`/`Usuario`, sin ningún filtro de `negocio_id` (que, como ya se estableció en Data/AI/Security/DevOps Architecture, no existe en código).

## 12. Roles y responsabilidades operativas

Se cita, sin redefinir, el modelo de autorización ya resuelto en Security Architecture (`admin`/`supervisor`/`asesor`, `ROLES_CON_VISION_TOTAL`). El propio MSA ya aclara la distinción que este CSA confirma: *"este capítulo no crea roles nuevos, define cómo se verifican técnicamente los ya existentes"* (`MAIEK_AI_SYSTEM_ARCHITECTURE.md:307`) — son roles de **autorización**, no de responsabilidad operativa.

No existe ninguna matriz RACI, rotación de guardia/on-call, ni documentación de "quién es responsable de monitorear o responder" distinta del modelo de autorización técnica — confirmado por búsqueda exhaustiva en el propio código y en MPA/MSA.

---

## Fortalezas

- El balanceo de capacidad en tiempo de ejecución (nivel de asesor vs. valor de producto, reparto de cola de a uno) está genuinamente bien pensado — no es una implementación trivial.
- El escalamiento automático por fallas técnicas ya funciona de punta a punta (detección → asignación → notificación).
- La pantalla de métricas/embudo ya existe y está en uso activo por el equipo comercial.
- El propio corpus ya anticipó, desde el MSA, la separación entre "Operations Architecture" (el marco) y "Operations Runbook" (el detalle procedimental) — no hay que inventar esa distinción ahora, ya está declarada.

## Decisiones heredadas del MVP (razonables para la etapa, a reevaluar)

- Sin gestión formal de incidentes ni runbooks — proporcional a un equipo pequeño donde hoy todos saben qué hacer informalmente.
- Escalamiento mayormente manual (el propio código lo documenta como "el primer paso" de un proceso humano) — razonable mientras el volumen de derivaciones sea bajo.
- Sin capacity planning formal, solo balanceo en tiempo de ejecución — suficiente al tamaño actual del equipo de asesores.
- Sin modo de mantenimiento — proporcional a un sistema que no ha necesitado coordinar ventanas de mantenimiento todavía.

## Deuda de proceso (sin justificación de etapa)

- **Ninguna métrica de calidad de atención**, pese a que el propio panel se presenta explícitamente como una herramienta para revisarla — hoy es 100% lectura manual de transcripciones.
- **Sin tasa de conversión por campaña** — el dato (`campana_origen` + `resultado`) ya existe en el modelo, solo falta cruzarlo.
- **Sin ninguna definición de tiempo de respuesta esperado**, ni para Gabi ni para un asesor humano — ni siquiera como objetivo aspiracional documentado.

## Desviaciones respecto al MSA y documentos derivados ya Approved

- **MSA Cap. 15-16 y el Operations Runbook** — no son desviaciones, son la sincronización pendiente que este CSA y el documento objetivo que sigue deben resolver; el propio MSA ya los declaró como responsabilidad de este dominio.
- No se identificó ninguna decisión ya tomada en un documento Approved que el estado actual contradiga activamente.

## Riesgos detectados

1. **Alto** — sin gestión de incidentes ni runbooks: ante un fallo real, la respuesta depende enteramente de que alguien del equipo sepa qué hacer de memoria.
2. **Medio** — escalamiento mayormente manual: un supervisor ausente u ocupado es un punto único de falla del proceso de derivación.
3. **Medio** — sin métrica de calidad de atención pese a presentarse como un objetivo del panel — brecha entre lo que el panel dice que hace y lo que realmente mide.
4. **Medio** — sin capacity planning formal: el balanceo en tiempo de ejecución distribuye la carga entre los disponibles, pero no previene una sobrecarga sistémica de todo el equipo.
5. **Bajo hoy / bloqueante futuro** — sin ningún concepto de operación segmentada por negocio.

## Architectural Readiness

| Dimensión | Madurez actual | Nota |
|---|---|---|
| Monitoreo operativo | **Parcial** | Embudo y lista de leads sí; salud de negocio en tiempo real, no |
| Gestión de incidentes | **Ausente** | Sin severidad, estado ni postmortem |
| Runbooks | **Ausente** | Documento hijo ya anticipado, no construido |
| Gestión de cambios/releases (proceso) | **Ausente** | Sin CHANGELOG, sin proceso de aprobación/comunicación |
| Soporte y escalamiento | **Parcial** | Primer paso automatizado, el resto manual |
| KPIs operativos | **Básico** | Embudo y carga; sin conversión, calidad ni tiempo de respuesta |
| Dashboards operativos | **Parcial** | Existen; sin panel de desempeño de equipo dedicado |
| Gestión de capacidad | **Parcial** | Balanceo en tiempo real bien pensado; sin planificación hacia adelante |
| Continuidad operacional | **Ausente** | Sin plan de continuidad de negocio |
| Procesos de mantenimiento | **Ausente** | Sin modo ni ventana de mantenimiento |
| Multi-Tenant (operación) | **Ausente** | Sin segmentación por negocio en ningún proceso operativo |
| Roles y responsabilidades operativas | **Parcial** | Autorización técnica sí; responsabilidad operativa (RACI/on-call), no |

**Conclusión de preparación:**

- **MVP (uso actual, un solo negocio):** **Listo.** El equipo pequeño compensa informalmente lo que falta — el conocimiento operativo vive en las personas, no en procesos documentados, pero alcanza para operar hoy.
- **Crecimiento (más volumen, mismo negocio):** **No listo.** La ausencia de gestión de incidentes, runbooks y un proceso de escalamiento más allá del primer paso automatizado se vuelve insostenible en cuanto el equipo o el volumen crezcan lo suficiente para que el conocimiento informal deje de alcanzar.
- **SaaS multiempresa:** **No listo.** Sin ningún concepto de operación segmentada por negocio — mismo bloqueante transversal ya señalado en los seis documentos anteriores, ahora confirmado también desde el ángulo de operación diaria.

## Priorización de remediación

| Prioridad | Ítem | Por qué |
|---|---|---|
| **P1** | Marco mínimo de gestión de incidentes (severidad, quién responde, cuándo escalar) | Es la brecha de mayor riesgo identificada en este CSA |
| **P1** | Definir el proceso de escalamiento como algo más que "primer paso automatizado, resto manual" | Punto único de falla del proceso de derivación hoy |
| **P2** | Runbook inicial para los escenarios ya conocidos (fallas técnicas repetidas, canal sin `app_secret`, etc.) | Los escenarios ya están identificados en CSAs previos — no hace falta descubrirlos, solo documentarlos |
| **P2** | Métrica real de calidad de atención y de conversión por campaña | Los datos ya existen en el modelo; falta la capa de cálculo |
| **P3** | Capacity planning formal, roles operativos (RACI/on-call), modo de mantenimiento, continuidad operacional documentada | Bajo riesgo actual, pero sin justificación de etapa para omitirlos indefinidamente |

## Architectural Decision Impact

| Hallazgo | Arquitecturas afectadas | Por qué |
|---|---|---|
| Sin gestión de incidentes ni runbooks | Operations, DevOps, Security | Los hallazgos técnicos ya identificados en esos CSAs (fail-open del webhook, sin backups) necesitan un proceso humano que reaccione cuando ocurran en la práctica |
| Escalamiento mayormente manual | Operations, Backend, AI | El mecanismo técnico ya existe; falta el proceso que lo rodea |
| Sin métricas de calidad/conversión | Operations, Data | Los datos ya existen en el modelo de Data Architecture; falta la capa de métricas |
| Sin operación Multi-Tenant | Operations, Data, AI, Security, DevOps | Mismo bloqueante transversal ya señalado en los cinco documentos anteriores |

## Strategic Recommendations

1. **El marco de gestión de incidentes es la decisión de mayor apalancamiento de este documento** — sin él, cada hallazgo técnico ya identificado en Security y DevOps Architecture no tiene un proceso humano que reaccione cuando ocurra en producción.
2. **El futuro Operations Runbook debería nutrirse directamente de los hallazgos ya identificados en los CSAs de Security y DevOps** — los escenarios ya están documentados, no hace falta inventarlos.
3. **Las métricas de calidad de atención y conversión por campaña pueden resolverse con datos que ya existen** (`campana_origen`, `resultado`, mensajes) — es una capa de cálculo, no una recolección de datos nueva.
4. **El escalamiento manual no es urgente de automatizar del todo, pero sí de documentar como proceso explícito** — hoy depende enteramente de que alguien "sepa qué hacer".
5. **La operación Multi-Tenant no es urgente, pero este es el sexto documento consecutivo en señalar el mismo bloqueante** — una señal fuerte de prioridad real, no solo teórica, para cuando se retome ese trabajo.

---

*Fin del documento. Approved el 2026-07-28. Siguiente paso: construir `MAIEK_AI_OPERATIONS_ARCHITECTURE.md` (arquitectura objetivo) como evolución explícita desde este estado real, siguiendo el ADS, el MSA, y el contexto ya establecido por Data, Backend, API, AI, Security y DevOps Architecture.*
