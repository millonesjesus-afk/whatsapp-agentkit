# Maiek AI — Phase 1 Execution Plan

**Versión 1.1 · Estado: Approved**

| | |
|---|---|
| Documento | Phase 1 Execution Plan |
| Proyecto | Maiek AI |
| Versión | 1.1 |
| Estado | **Approved** |
| Fecha de creación | 2026-07-29 |
| Autor | Claude, a pedido de Jesús Millones |
| Fecha de aprobación | 2026-07-29 |
| Última actualización | 2026-07-29 |

## Dependencias

`MAIEK_AI_IMPLEMENTATION_ROADMAP.md` (Fase 1, ya secuenciada, con Data Architecture Fase 1 incorporada como pista transversal); `MAIEK_AI_BACKEND_ARCHITECTURE.md`, `MAIEK_AI_AI_ARCHITECTURE.md`, `MAIEK_AI_API_ARCHITECTURE.md` (Decisiones locales `Objetivo` que esta fase implementa); `MAIEK_AI_DATA_ARCHITECTURE.md` (su Fase 1 — baseline de migraciones — y su Fase 2 — integridad y entidades de IA, incluida `SugerenciaIA` — condicionan qué entregables de este plan pueden tocar esquema, y en qué medida cada uno); `IMPLEMENTATION_REVIEW_FASE_0.md` (base ya verificada en producción sobre la que se construye).

## Consumido por

El trabajo real de implementación de la Fase 1; el ADR Index, si algo revela una desviación durante la ejecución.

## Control de versiones

| Versión | Fecha | Autor | Descripción |
|---|---|---|---|
| 1.0 (borrador) | 2026-07-29 | Claude | Primera versión — plan ejecutivo de la Fase 1, sin código ni redefinición de arquitectura. Pendiente de aprobación. |
| 1.1 (borrador) | 2026-07-29 | Claude | Revisado tras auditoría independiente (Opus, como Principal Architect/CTO externo) contra el corpus Approved. 6 hallazgos verificados contra los documentos y el código reales; los 6 se incorporaron con ajustes de alcance, orden y criterios (ver resumen de la revisión al final del documento). Ningún hallazgo requirió redefinir arquitectura. |
| 1.1 | 2026-07-29 | Claude | **Aprobado.** Precisadas las secciones 2, 3, 5, 6, 7 y 8 distinguiendo los dos entregables diferidos por dependencia real: idempotencia general depende solo de Data Architecture Fase 1; persistencia de `SugerenciaIA` depende de Fase 1 **y** Fase 2. Refleja que `MAIEK_AI_IMPLEMENTATION_ROADMAP.md` ya incorpora Data Architecture Fase 1 como pista transversal de su Fase 1, tras la recomendación aceptada por el usuario. Con esta aprobación se cierra la planificación de la Fase 1 y comienza su implementación en el orden ya definido. |

## Alcance

Documento ejecutivo, no técnico ni arquitectónico — traduce la Fase 1 ya secuenciada en el Roadmap en un plan de ejecución. No redefine ninguna Decisión local de Backend, AI o API Architecture; no contiene tareas técnicas detalladas.

---

## 1. Objetivo de la Fase 1

Implementar, sobre el negocio único actual, las Decisiones `Objetivo` acopladas de Backend, AI y API Architecture: cierra la brecha central del corpus — hoy la IA solo devuelve texto libre, sin señal de confianza estructurada, y `brain.py` se llama por import directo, sin un contrato formal. No toca Multi-Tenant ni el modelo de negocio.

## 2. Alcance

**Incluye**, alineado con el alcance completo que el Roadmap ya fijó para esta fase (no un subconjunto propio):

- Backend: las 4 capas y **los 5 servicios de dominio** (`ServicioInteligencia`, `ServicioComercial`, `ServicioConversacion`, `ServicioCanales`, `ServicioIdentidad` con `requiere_rol` centralizado) — no solo `ServicioInteligencia`.
- Retiro del branch roto de `twilio` en el factory de proveedores (falla de arranque real hoy si se selecciona ese proveedor) y restricción de `/docs`/`/openapi.json` — ambos ya Objetivo en Backend/API Architecture, de bajo costo, sin excusa para diferirlos.
- AI Orchestrator (5 responsabilidades), protocolo de confianza con **salida estructurada forzada** (tool-calling o JSON Schema — no texto libre a parsear, ver sección 6), delimitación estructural anti-prompt-injection, prompt caching activo.
- `request_id` y modelo uniforme de errores para el contrato interno.
- Reemplazo del disparador de escalamiento actual (conteo de fallas técnicas) por la señal de confianza real — es el único consumidor real de esa señal en esta fase.

**Excluye deliberadamente:** `negocio_id`/Multi-Tenant (Fase 2 del Roadmap); tool-calling *agéntico* (decisión ya `Activa` de mantener RAG-lite — distinto de exigir salida estructurada para el campo de confianza, ver sección 6); separar el AI Engine a un servicio propio; la API externa versionada (`/api/v1/`); la representación visual de confianza/explicación en el panel (Frontend Architecture ya decidió no construirla hasta que el dato exista).

**Diferido — no incluido en esta fase, con dos profundidades de dependencia distintas** (precisado tras incorporar Data Architecture Fase 1 al Roadmap como pista transversal, ver sección 6):
- **Idempotencia general con respaldo en base de datos** — depende únicamente de Data Architecture **Fase 1** (Alembic): con el baseline de migraciones activo, ya se puede agregar de forma segura una tabla simple de deduplicación.
- **Persistencia formal de `SugerenciaIA`** — depende de Data Architecture **Fase 1 y Fase 2**: `SugerenciaIA` es una entidad que Data Architecture crea explícitamente en su Fase 2 (integridad y entidades de IA), no en su Fase 1 (que solo da la herramienta de migración). No alcanza con que exista Alembic.

`BackgroundTasks` para las tareas no críticas queda incluido pero marcado explícitamente como mecanismo transitorio, no como estado final (ya así en Backend Architecture).

## 3. Entregables esperados

- Los 5 servicios de dominio de Backend, extraídos de `dashboard.py`/`main.py`, con `requiere_rol` reemplazando los ~26 checks de rol duplicados.
- `ServicioInteligencia` extraído **primero dentro del bloque de Backend** — no porque sea la prioridad general de Backend (que Backend Architecture fija en `ServicioComercial`, mayor concentración de reglas de negocio hoy), sino porque es la única pieza que bloquea a AI; el resto de los servicios sigue el orden de prioridad ya fijado en Backend Architecture, dentro de esta misma fase.
- Retiro del branch `twilio` roto; `/docs` y `/openapi.json` restringidos.
- AI Orchestrator explícito en el código; protocolo de confianza con salida estructurada forzada; delimitación estructural del contexto en el turno `user`; prompt caching activo.
- `request_id` generado en el borde de cada solicitud y propagado a logs; modelo uniforme de errores para el contrato interno.
- Reemplazo del disparador de escalamiento por la señal de confianza real, **y** el umbral de negocio que separa `Alta`/`Requiere validación`/`Baja` definido explícitamente antes de activar esto en producción (brecha que AI Architecture ya marcó como "a definir junto con Backend Architecture al implementar" — es este momento).
- Registro de cada inferencia como **log estructurado de aplicación** (no una tabla nueva todavía) — evidencia suficiente para verificar Explainability First manualmente en esta fase; la persistencia formal como `SugerenciaIA` queda para cuando Data Architecture **Fase 1 y Fase 2** existan (la entidad en sí se crea en Fase 2, no en Fase 1).

## 4. Orden recomendado y justificación

**Backend → AI → API**, en ese orden, porque cada uno depende de que el anterior tenga una forma estable:

1. **Backend primero** — dentro de Backend, `ServicioInteligencia` se extrae antes que el resto (justificación de la sección 3) porque es la única pieza que bloquea a AI; el resto de los 5 servicios avanza en el orden de prioridad que Backend Architecture ya fijó, dentro de la misma sub-etapa.
2. **AI segundo** — una vez la interfaz de `ServicioInteligencia` existe, se implementa el Orchestrator y el protocolo de confianza sobre ella.
3. **API tercero** — formalizar el contrato interno solo tiene sentido una vez Backend y AI tienen una forma estable que documentar.

## 5. Paralelización

| Puede avanzar en paralelo | No puede |
|---|---|
| `request_id` y modelo uniforme de errores (API) — no dependen del protocolo de confianza | La formalización final del contrato interno de API — necesita que Backend y AI tengan una forma estable primero |
| El resto de los servicios de dominio de Backend (`ServicioComercial`, `ServicioConversacion`, `ServicioCanales`, `ServicioIdentidad`) y el trabajo interno del AI Orchestrator (delimitación estructural, prompt caching) — una vez la interfaz de `ServicioInteligencia` está acordada | El protocolo de confianza de AI — necesita que `ServicioInteligencia` exista primero, aunque sea mínima |
| Retiro del branch `twilio`, restricción de `/docs` — sin dependencia de nada de lo anterior, pueden hacerse el primer día | La idempotencia general con respaldo en base de datos — diferida hasta Data Architecture Fase 1 (sección 2); la persistencia de `SugerenciaIA` — diferida hasta Data Architecture Fase 1 **y** Fase 2 (sección 2) |

## 6. Riesgos técnicos

- Refactorizar Backend en producción real — riesgo de regresión en flujos ya funcionando (login, chat en vivo, asignación) si no se hace incrementalmente.
- **El protocolo de confianza exige salida estructurada forzada (tool-calling o JSON Schema) — no es una elección abierta de esta fase, ya lo fija Backend Architecture.** El riesgo real no es *si* se fuerza el formato, sino la fiabilidad de forzarlo de forma consistente con el proveedor actual — un síntoma similar ya se vio en `extraer_datos_lead`, que hoy parsea texto libre sin formato forzado.
- **Dos entregables originalmente considerados para esta fase tocan esquema de base de datos, con distinta profundidad de dependencia** (precisado tras incorporar Data Architecture Fase 1 al Roadmap como pista transversal — sección 2): la idempotencia general depende solo de que exista el baseline de migraciones (Fase 1 de Data Architecture); la persistencia de `SugerenciaIA` depende, además, de que Data Architecture Fase 2 haya creado esa entidad — Fase 1 sola no alcanza. Crear cualquiera de las dos ahora, sin ese baseline, repetiría el mismo patrón que Data Architecture ya identificó como riesgo (cambios de esquema sin control de versiones). Por eso ambas quedan diferidas (sección 2), no implementadas con un atajo.
- No existe hoy ningún mecanismo real de activación gradual para el refactor transversal de Backend (login, chat, asignación) — `CanalWhatsApp.modo` solo determina qué *system prompt* se carga, no gatea ningún camino de código; Feature Flags (MSA Cap. 12) es una decisión ya `Objetivo` pero sin mecanismo formal construido todavía. La mitigación real en esta fase es la misma que ya funcionó en Fase 0: commits pequeños, gate de CI, y validación con tráfico real antes de cada cierre — no un gating técnico que hoy no existe. Para las piezas específicas de AI (protocolo de confianza, delimitación estructural), `modo` sí se extiende para activarlas primero en canales de prueba, porque esa lógica ya vive detrás de la carga de prompt.
- La delimitación estructural cambia el formato exacto que ve el modelo — riesgo real de que la calidad conversacional de Gabi cambie; necesita validación conversacional real, no solo pruebas técnicas.
- Prompt caching exige que el system prompt sea 100% estático byte a byte (Constraint ya conocida) — cualquier dinamismo oculto lo rompe en silencio.

## 7. Dependencias externas

Ninguna nueva de infraestructura (a diferencia de Fase 0). Depende de que la API de Anthropic siga soportando de forma confiable la salida estructurada que el protocolo de confianza necesita (Constraint ya reconocida en AI Architecture) — un cambio de comportamiento del proveedor afecta directamente esta fase. Depende también, indirectamente, de que Data Architecture Fase 1 (y, para uno de los dos entregables diferidos, también Fase 2) se ejecuten en algún momento — ambas corren como pista transversal del Roadmap, sin bloquear el inicio de esta fase, pero condicionan el cierre de esos dos puntos específicos (sección 2).

## 8. Criterios de aceptación

Subconjunto curado de los Architecture Success Criteria ya definidos en Backend/AI/API Architecture, ajustado al alcance real de esta fase — no se inventan criterios nuevos, pero tampoco se debilita ninguno para que "pase":

- Ningún router contiene reglas de negocio; toda lógica vive en un servicio de dominio (Backend ASC).
- Toda autorización pasa por `requiere_rol` — cero checks de rol duplicados inline (Backend ASC).
- Toda respuesta de IA expone confianza explícita, con salida estructurada forzada, emitida únicamente por el AI Engine (Backend ASC, AI ASC #1).
- Máximo 2 llamadas de IA por mensaje procesado (AI ASC #2).
- El mensaje del cliente y el contexto de confianza están delimitados de forma distinguible en el turno `user` (AI ASC #3).
- **Criterio parcial en esta fase**: para cualquier conversación, se puede reconstruir qué contexto vio el modelo y qué decidió, consultando el log estructurado de inferencias (AI ASC #4/#6, Explainability First) — la verificación completa vía `SugerenciaIA` persistida queda condicionada a Data Architecture Fase 1 **y** Fase 2 (sección 2), no se declara cumplida antes de eso.
- El webhook de Meta no reprocesa un mensaje ya visto usando `mensaje_id` (API ASC) — verificable ya en esta fase, sin necesitar el respaldo general en base de datos.
- AI Architecture consume exclusivamente vía el contrato interno, nunca como un consumidor externo (API ASC).
- Todo error del contrato interno responde con un formato uniforme (código, mensaje, detalle, `request_id`), y ese `request_id` aparece en los logs — criterio propio de esta fase, distinto del ASC de errores de la API *externa* (`/api/v1/`), que no se construye todavía.

## 9. Estrategia de integración incremental

- `ServicioInteligencia` se introduce como fachada delante del código actual, no como una reescritura — el resto de Backend sigue funcionando mientras se migra pieza por pieza, servicio por servicio.
- El protocolo de confianza y la delimitación estructural se activan primero en el canal de "pruebas" ya existente (`CanalWhatsApp.modo`, extendido para este propósito), y se promueven a producción solo después de validarse ahí.
- Para el refactor transversal de Backend (sin gating técnico disponible, sección 6): commits pequeños y frecuentes, cada uno cerrado con el mismo rigor que Fase 0 (gate de CI + logs de Railway + al menos un caso real) antes de continuar con el siguiente.
- Retiro del branch `twilio` y restricción de `/docs` se hacen primero, el primer día — sin dependencias, riesgo mínimo, valor inmediato.
- Ningún cambio se promueve a producción sin pasar por el gate de CI construido en Fase 0.

## 10. Recomendación final

Ejecutar Backend → AI → API como sub-etapas, cada una probada antes de promoverse — no de una sola vez. Dentro de Backend, empezar por lo trivial y sin riesgo (retiro de `twilio`, restricción de `/docs`), seguir por `ServicioInteligencia` (desbloquea a AI), y completar el resto de los servicios de dominio en paralelo con el trabajo de AI. El punto de mayor riesgo real sigue siendo el cambio de comportamiento conversacional de Gabi (delimitación estructural + protocolo de confianza) — trátese como su propio hito dentro de la sub-etapa de AI. Los dos entregables que tocan esquema quedan fuera de esta fase por diseño, no por descuido: evita fabricar en Fase 1 el mismo riesgo de esquema sin control de versiones que Data Architecture ya identificó como el más grave de toda la implementación.

---

## Resumen de la revisión independiente (Opus, Principal Architect/CTO externo)

Se solicitó una auditoría puntual del borrador v1.0 contra el corpus Approved, antes de aprobar. Los 6 hallazgos se verificaron uno por uno contra el texto exacto de los documentos y el código real antes de decidir — ninguno se aceptó ni se descartó sin esa verificación.

| # | Hallazgo | Decisión | Dónde se incorporó |
|---|---|---|---|
| 1 | El plan trataba la salida estructurada del protocolo de confianza como un riesgo abierto, cuando Backend Architecture ya la exige (tool-calling forzado o JSON Schema) | **Aceptado** | Secciones 2, 3, 6, 8 |
| 2 | Dos entregables (registro de `SugerenciaIA`, idempotencia general) tocan esquema sin que exista Data Architecture Fase 1 (Alembic) | **Aceptado** | Secciones 2, 3, 6, 7, 8, 10 |
| 3 | Los criterios de aceptación debilitaban un ASC, omitían otro (Explainability First), y les faltaba el de idempotencia | **Aceptado** | Sección 8 |
| 4 | La estrategia de integración se apoyaba en `CanalWhatsApp.modo` como si gatease código — solo gatea el prompt | **Aceptado** | Secciones 6, 9 |
| 5 | El alcance cubría solo 1 de los 5 servicios de dominio que el Roadmap ya fijó para esta fase, sin declarar la reducción | **Aceptado** | Secciones 2, 3, 4, 5 |
| 6 | La señal de confianza no tenía consumidor nombrado en la fase, y el umbral de negocio no se marcaba como decisión a tomar ahora | **Aceptado** | Sección 3 |

**Los 6 hallazgos se aceptaron.** Ninguno proponía rediseñar arquitectura — los seis identificaban que el plan de ejecución no reflejaba con fidelidad decisiones ya Approved, o dejaba un vacío de secuenciación real. Sobre ese último punto (Data Architecture Fase 1 sin ubicación explícita en el Roadmap): se recomendó actualizar el Roadmap en vez de solo documentar la condición acá, porque la misma evidencia (Data Architecture: *"sin esta fase, ninguna de las siguientes puede desplegarse con seguridad"*) también bloquea la Fase 2 del Roadmap (`negocio_id`), no solo estos dos entregables. **El usuario aprobó esa recomendación** — `MAIEK_AI_IMPLEMENTATION_ROADMAP.md` ya incorpora Data Architecture Fase 1 como pista transversal de su Fase 1 (sin bloquear el inicio de Backend/AI/API), y este documento distingue con precisión, en cada sección relevante, qué entregable depende solo de Fase 1 de Data Architecture y cuál depende además de su Fase 2 (`SugerenciaIA` se crea en Fase 2, no en Fase 1). No se abrió un ADR — ninguno de los 6 hallazgos contradice una Decisión ya Approved; todos son correcciones de fidelidad de este plan y del Roadmap hacia el corpus que ya existía.

---

*Fin del documento. Approved el 2026-07-29. Comienza la implementación de la Fase 1 en el orden ya definido: Backend → AI → API, con Data Architecture Fase 1 corriendo en paralelo desde el día uno.*
