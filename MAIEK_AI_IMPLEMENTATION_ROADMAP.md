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
| Última actualización | 2026-09-12 (ADR-0003 — retiro de "identidad de marca resoluble por negocio" del alcance de Fase 3, ver Control de versiones) |

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
| 1.0 | 2026-08-08 | Claude | Aprobado sin reapertura del contenido existente. **Agrega la sección 2.2 (Metodología de Product Design)**: especializa el paso 2 (Diseño técnico) de la sección 2.1 para la fase de Product Design, iniciada tras el congelamiento funcional de `MAIEK_AI_UX_BLUEPRINT.md`. Fija la cadena Journey Maestro → Experience Flow → User Flow → Wireframes → Mockups → Prototipo, y dentro del User Flow, Pantalla → Patrón → Componente. Validada empíricamente en la construcción del primer Journey (Lead → Close Won) y confirmada explícitamente por el usuario como metodología a conservar para todos los recorridos futuros. |
| 1.0 | 2026-08-08 | Claude | **Aclaración documental — convención de IDs `UF-NN` y `SCR-NN`.** La auditoría transversal de los recorridos #1-#3 encontró que solo `EXP-NN` tenía explícita su convención de ID global y consecutiva entre Journeys; `UF-NN` y `SCR-NN` se venían usando así en la práctica (sin huecos ni colisiones en 6 pantallas y 7 pasos de User Flow across 3 recorridos) pero sin que la sección 2.2 lo declarara por escrito. No se inventó una convención nueva — se formalizó por escrito la que ya estaba en uso, mismo criterio que `EXP-NN`. Corregida además la referencia de UF-06 (Inicio, recorrido #3): entrega a **UF-01** (SCR-01, Bandeja de Conversaciones) — no a UF-02 como se había citado por error en el cierre del recorrido #3 — porque la Postcondición de SCR-06 declara la transición a SCR-01 específicamente, no al panel del Copiloto. |
| 1.0 | 2026-08-08 | Claude | **Recorrido #3 (Inicio → Acción priorizada, Asesor) declarado en Congelamiento de Product Design**, ciclo completo sin pausas entre etapas (Wireframes → Mockups → Prototipo → Auditoría Horizontal Integral), tal como pidió el usuario. Único hallazgo obligatorio: interactividad de la Zona de acción restringida al ítem priorizado (los otros dos son panorama no interactivo, EXP-06), corregido. Con esto, 3 de 3 recorridos construidos (#1, #2, #3) quedan en Congelamiento de Product Design — próximo paso: auditoría transversal de los tres antes de continuar con #5. |
| 1.0 | 2026-08-08 | Claude | **Sección 2.2 ampliada — Pregunta cognitiva de cada Experience Flow.** Todo Experience Flow declara, antes de su tabla de pasos, la incertidumbre concreta que existe para resolver (ej. "¿Cuál es la única acción que merece mi atención primero?") — surgió al construir el Experience Flow del recorrido #3 (Inicio → Acción priorizada), el primero centrado en priorizar entre múltiples casos en vez de profundizar uno solo (EXP-06, EXP-07). Se confirma además que los IDs `EXP-NN` son compartidos y consecutivos entre todos los Journeys, no reiniciados por recorrido — un Experience Flow puede entregar (handoff) directo a un paso ya existente de otro recorrido (EXP-07 → EXP-02) sin duplicarlo, evidencia directa de que el sistema de Experience Flows ya se comporta como piezas reutilizables. |
| 1.0 | 2026-08-08 | Claude | **Sección 2.2 ampliada — Principio de reutilización primero.** Orden de evaluación institucionalizado para toda necesidad nueva de Product Design (¿ya existe? → ¿se fortalece? → ¿se extiende? → recién crear) y la Matriz de Reutilización como entregable formal del Gap Analysis, no solo prosa. Validado en el recorrido #2 (Conversación → Lead generado): 9/9 artefactos reutilizables, 1 fortalecido (Screen Contract SCR-03, 2 de 14 campos), 0 artefactos nuevos. **Recorrido #2 declarado en Congelamiento de Product Design sin reconstruir Wireframes, Mockups ni Prototipo** — el fortalecimiento del contrato no cambió comportamiento observable de la interfaz. |
| 1.0 | 2026-08-08 | Claude | **Sección 2.2 ampliada, cierre del primer recorrido completo.** Cadena actualizada a Journey Maestro → Experience Flow → User Flow → Screen Contract → Wireframes → Mockups de Alta Fidelidad → Prototipo Navegable → Validación con usuarios (Screen Contract y Validación con usuarios quedan explícitos como capas propias). Se institucionaliza el patrón "única superficie dominante por pantalla" y la "Regla de sincronización entre capas" (una capa superior que descubre un error objetivo en una capa inferior la corrige, sin reabrir el congelamiento, siempre que no implique una decisión de diseño nueva — surgida al corregir una dirección de burbuja de chat invertida, descubierta durante la construcción del Prototipo y propagada al Mockup y al Wireframe conceptual de SCR-01). Se fija el "Ciclo por recorrido" completo (Gap Analysis → ... → Prototipo → Auditoría Horizontal Integral → ajustes → Congelamiento de Product Design), validado de punta a punta con el recorrido Lead → Close Won, declarado en Congelamiento de Product Design en esta misma fecha. |
| 1.0 | 2026-08-08 | Claude | **Gap Analysis del recorrido #5 (Campaña → Lead atribuido → Pipeline) aprobado con bloqueo de corpus.** El recorrido no requiere pantalla nueva — reutiliza el tramo Conversación → Lead → Pipeline ya construido (SCR-01, SCR-02, UF-01→UF-03), con SCR-03 como único candidato a fortalecimiento. Ese fortalecimiento queda **bloqueado** por dos brechas elevadas, no resueltas en esta capa: **(A)** `MAIEK_AI_PRODUCT_PATTERNS.md` Cap. 6 (CRM/Pipeline) no refleja todavía la relación Campañas → CRM/Pipeline con atribución de origen que `MAIEK_AI_PRODUCT_ARCHITECTURE.md` §4 y §6 ya declaran explícitamente — brecha de herencia MPA → Product Patterns, a resolver en Cap. 6 de Product Patterns; **(B)** el código actual (`agent/brain.py`, `agent/campanas.py`) hace que Gabi use el producto/precio promocional de la campaña de origen dentro de la conversación, capacidad que no aparece declarada en ningún patrón canónico (Cap. 2, Cap. 5, Cap. 7.A, Cap. 7.B) — divergencia entre implementación existente y corpus canónico, con una decisión pendiente del usuario (formalizar como comportamiento canónico o descartarla del alcance) antes de que corresponda a ningún documento resolverla. Ninguna de las dos brechas se resolvió localmente ni generó diseño visual o de componente. **El recorrido #5 queda pausado en la capa de Gap Analysis** (Matriz de Reutilización) — no avanza a Experience Flow hasta que ambas queden resueltas; al retomar, se revalúa primero si el tramo reutilizable ya cubre el recorrido antes de crear cualquier `EXP-NN` nuevo (Principio de reutilización primero). |
| 1.0 | 2026-08-08 | Claude | **Brecha B del recorrido #5 resuelta como decisión de producto** (no como validación retroactiva de toda la implementación actual): Maiek AI puede usar contexto de campaña como contexto conversacional configurable, sujeto a reglas de negocio — no queda establecido que deba mencionar automáticamente promociones o precios. Formalizada en el corpus, aplicando solo lo estrictamente necesario: `MAIEK_AI_PRODUCT_ARCHITECTURE.md` §4 y §12 (nueva relación Campañas → Agentes IA, capacidad disponible/configurable, no obligación universal) y `MAIEK_AI_AI_ARCHITECTURE.md` §2 (el contexto de campaña se declara extensión de la fuente de conocimiento ya existente "Conocimiento transaccional", no una fuente nueva). Deliberadamente **no** se tocó Product Patterns ni MPX en este paso — quedan pendientes para cuando exista evidencia y necesidad de definir reglas detalladas de cuándo/cómo se usa ese contexto. **La Brecha A permanece abierta y sin relación con esta resolución** — sigue pendiente en `MAIEK_AI_PRODUCT_PATTERNS.md` Cap. 6 (atribución del Lead en CRM/Pipeline). El recorrido #5 sigue pausado: no se construyó Experience Flow, User Flow, Screen Contract, Wireframe, Mockup ni Prototipo. |
| 1.0 | 2026-08-08 | Claude | **Brecha A del recorrido #5 RESUELTA.** `MAIEK_AI_PRODUCT_PATTERNS.md` Cap. 6 actualizado con 3 ediciones mínimas (§2 Trazabilidad, §8 Relación con otros patrones, §3 Composición/Vista de detalle) reflejando la relación Campañas → CRM/Pipeline con atribución persistente ya declarada en MPA §3/§4/§6 — ver Control de versiones de Product Patterns para el detalle completo. La atribución queda declarada como dato que **debe** estar presente y visible (no opcional/configurable, a diferencia de la Brecha B) — solo su tratamiento visual queda diferido a Product Design. **Con esto, Brecha A y Brecha B quedan ambas resueltas — el bloqueo de corpus del recorrido #5 queda levantado.** El recorrido **no** salta a Wireframes/Mockups: se retoma exactamente desde la Matriz de Reutilización, reevaluando SCR-01, SCR-02, SCR-03, EXP-01→EXP-07 y UF-01→UF-06 contra la nueva declaración de Cap. 6, aplicando de nuevo ¿existe? → ¿se fortalece? → ¿se extiende? → recién crear, sin asumir todavía que se necesita un Experience Flow o pantalla nueva. |
| 1.0 | 2026-08-08 | Claude | **Gap Analysis del recorrido #5 CERRADO — Matriz de Reutilización final.** Búsqueda exhaustiva confirmó que las tablas literales de EXP-01→EXP-07 y UF-01→UF-06 nunca se persistieron en ningún archivo (decisión ya vigente de no crear `MAIEK_AI_EXPERIENCE_FLOWS.md` hasta el 2do/3er Experience Flow). Conclusión final, con precisión metodológica explícita del usuario: **SCR-01 y SCR-02 reutilización sin cambios** (verificado literalmente contra Cap. 2 y Cap. 5); **SCR-03 fortalecimiento puntual** (verificado contra Cap. 6 §3); **EXP-01→EXP-07 y UF-01→UF-06 reutilización sin cambios por precedente documentado del recorrido #2 — no presentada como verificación textual**, ya que ese precedente registra que el mismo tipo de cambio (fortalecimiento de campo en SCR-03) no requirió modificar ningún EXP/UF. Ningún EXP-08 ni UF-07 creado. Con esto el recorrido #5 avanza a la capa de Experience Flow. |
| 1.0 | 2026-08-09 | Claude | **Recorrido #6 (CRM/Pipeline → Analítica) declarado en Congelamiento de Product Design.** Sexto recorrido evaluado del inventario candidato (identificado por búsqueda exhaustiva en UX Blueprint §2.4, "Matriz de Recorridos Canónicos" — el Inventario Maestro original de 10 recorridos no está persistido de forma recuperable, confirmado por dos búsquedas exhaustivas). Ciclo completo sin brecha de corpus: Experience Flow nuevo (EXP-08→EXP-12, primera vez que se toca la etapa "Aprendizaje" del Journey Maestro), User Flow nuevo (UF-07→UF-11), Screen Contract nuevo (SCR-07), Wireframe, Mockup (reutiliza `KPI Card`/`AI Suggestion Card`/`Statistic Card` ya catalogados en Cap. 4 §2, sin componente inventado) y Prototipo extendido sobre el mismo Artifact único. Auditoría Horizontal Integral con una segunda vuelta de correcciones reales (no solo documentadas): responsive real implementado (`@media max-width:767px`, acotado a SCR-07), condición de ausencia de `AI Suggestion Card` demostrada funcionalmente (toggle explícito, sin inventar umbral), íconos de delta reemplazados por caracteres Unicode renderizables (los `ti ti-*` del resto del Prototipo no tienen fuente de íconos cargada — limitación preexistente, no introducida por este recorrido). **Dos decisiones quedan explícitamente pendientes, no resueltas:** la Vista principal de Pipeline sin Screen Contract, y el mecanismo concreto de activación/preservación de contexto en la transición Pipeline→Analítica (UF-08). Con esto, 5 de 6 recorridos (#1, #2, #3, #5, #6) quedan en Congelamiento de Product Design. |
| 1.0 | 2026-08-09 | Claude | **Recorrido #7 (Conversaciones → Catálogo & Comercial) declarado en Congelamiento de Product Design.** Cadena completa sin brecha de corpus bloqueante: Gap Analysis (con dirección UX validada por una auditoría de referentes externos — Kommo, WhatsApp Business, respond.io; Treble.ai insuficientemente documentado públicamente) → EXP-13/EXP-14 (nuevo, "consultar con exactitud" / "compartir sin salir de la conversación") → UF-12/UF-13 (SCR-01 como única superficie, sin pantalla de Catálogo independiente) → fortalecimiento funcional de SCR-01 (3 campos: Información que recibe, Acciones principales, Experience Flow que satisface — SCR-01 no está persistido literalmente en el corpus, por lo que el fortalecimiento se registró como propuesta funcional, no como diff textual verificado) → Wireframe → Mockup (superficie resuelta como `drawer`, mismo patrón ya usado 3 veces en SCR-03, reutilizando `catalog-item` sin modificar su definición) → Prototipo (extendido sobre el mismo Artifact único). Auditoría Horizontal Integral encontró y corrigió 1 obligatorio real: el drawer de Catálogo y el panel de Copiloto podían coexistir abiertos en la misma región de SCR-01 — corregido cerrando el Copiloto al abrir Catálogo, registrado como evidencia del principio ya institucionalizado de "única superficie dominante", no como regla nueva. Auditoría Transversal Post-#7: 0 obligatorios, 2 pendientes no bloqueantes — **PEND-#7-01** (asimetría documental: Cap. 7.A §8 declara la relación con Bandeja vía `Attachment`, Cap. 2 §8 todavía no la refleja como relación entrante — recomendado, documental, no bloqueante, mismo tipo de hallazgo ya resuelto una vez como Brecha A) y **PEND-#7-02** (comportamiento de la superficie de Catálogo sin productos disponibles, no definido — observación pendiente, extensión de la observación transversal de Empty States, no bloqueante). Con esto, 6 de 7 recorridos evaluados (#1, #2, #3, #5, #6, #7) quedan en Congelamiento de Product Design — recorrido #4 nunca identificado (Inventario Maestro original no recuperable). No se inicia el recorrido #8 en este cierre. |
| 1.0 | 2026-08-08 | Claude | **Recorrido #5 (Campaña → Lead atribuido → Pipeline) declarado en Congelamiento de Product Design.** Ciclo completo tras la resolución de ambas brechas de corpus: Experience Flow (EXP-02 reutilizado sin cambios, sin EXP-08), User Flow (UF-01→UF-03 reutilizados sin cambios, sin UF-07), Screen Contract (SCR-03 fortalecido en 1 de 14 campos — "Información que recibe" — con texto exacto aprobado, sin crear SCR-07), Wireframe (línea de atribución dentro de la cabecera de identidad ya existente, sin componente nuevo), Mockup de alta fidelidad (reutiliza `.pipeline-head .sub` ya tokenizado, sin token/color/badge nuevo), Prototipo Navegable (extendido sobre el mismo Artifact único ya publicado, sin crear uno nuevo). Auditoría Horizontal Integral: **0 hallazgos obligatorios** — 2 hallazgos Recomendados registrados sin corrección requerida (ausencia de truncado para nombres de campaña largos, verificación por lectura de código en vez de captura visual en vivo por límite de entorno ya conocido). Con esto, 4 de 4 recorridos construidos hasta ahora (#1, #2, #3, #5) quedan en Congelamiento de Product Design. |
| 1.0 | 2026-08-09 | Claude | **Histórico #4 (Inicio → Analítica) reconciliado:** su acceso está cubierto por el Shell de Navegación, conforme a Product Patterns Cap. 1 §3/§4. No requiere modificación de SCR-06 ni SCR-07. UF-08 (Pipeline → Analítica) permanece como asunto independiente y pendiente. |
| 1.0 | 2026-08-09 | Claude | **Deuda de implementación del recorrido #7 ("Adjuntar a conversación") IMPLEMENTADA / VERIFICADA POR TRAZADO ESTÁTICO.** `#btn-adjuntar` (drawer Cotizar, SCR-03/SCR-04, Prototipo) reemplazado para reutilizar el patrón ya existente de `#btn-compartir-catalogo` (recorrido #7): agrega el `.catalog-item` de la ficha al final de `#messages` como `.msg.out`, muestra confirmación con el `#toast` ya existente ("Cotización adjuntada a la conversación", mismo componente y timing que el toast de Cierre), y cierra el drawer con `closeDrawers()` sin modificarlo. Sin navegación automática a Bandeja, sin componente nuevo, sin tocar `toggleCopilot` ni ningún otro handler compartido. **Limitación explícita:** no fue posible realizar verificación visual/interactiva del Artifact en vivo por la limitación de entorno ya documentada (Artifact fuera del proyecto, renderizado como snapshot estático) — la validación realizada corresponde a inspección y trazado estático del código, no a una prueba visual en vivo. Regresión trazada sin hallazgos sobre SCR-02, SCR-03 (resto del contrato), SCR-06 y SCR-07. **PEND-#7-03 — Visibilidad posterior del adjunto:** al regresar a Bandeja después de adjuntar una cotización desde Pipeline, no está definido si la conversación debe posicionarse automáticamente sobre el nuevo contenido — el mensaje se agrega correctamente al final de `#messages`, pero sin `scrollIntoView` ni comportamiento de scroll automático. Clasificado como mejora/decisión UX futura, no bloqueante — no corregido en esta implementación, mismo tratamiento que PEND-#7-01 y PEND-#7-02. |
| 1.0 | 2026-08-09 | Claude | **Corrección de trazabilidad — Inventario Maestro histórico recuperado.** La entrada de este mismo Control de versiones para el recorrido #6 (arriba, 2026-08-09) afirmó que "el Inventario Maestro original de 10 recorridos no está persistido de forma recuperable, confirmado por dos búsquedas exhaustivas" — correcto en el momento en que se escribió, dado el alcance de esa búsqueda (archivos + memoria). Búsquedas posteriores contra el transcript crudo de la sesión original localizaron y recuperaron ese inventario: **contiene 9 recorridos, no 10.** Persistido íntegramente, con Journey Maestro y las tablas EXP/UF/SCR recuperadas, en `MAIEK_AI_EXPERIENCE_FLOWS.md`. Esta entrada no borra ni reescribe la anterior — queda como registro de lo que se sabía en ese momento; esta es la corrección posterior. |
| 1.0 | 2026-08-10 | Claude | **UF-08 (fortalecimiento de CRM/Pipeline → Analítica) completado y persistido — cierra la dependencia "Vista principal de Pipeline sin Screen Contract" registrada en la entrada del recorrido #6 (2026-08-09, arriba).** Ciclo completo Gap Analysis → Experience Flow (confirmado ya cubierto por EXP-08→EXP-12, sin EXP nuevo) → User Flow (UF-08, dentro del rango UF-07→UF-11 ya asignado, sin UF nuevo) → Screen Contract nuevo de la Vista principal de Pipeline (14 campos) → fortalecimiento puntual de SCR-07 (ya persistido en `MAIEK_AI_EXPERIENCE_FLOWS.md` v1.3) → Wireframe → Mockup → Prototipo, extendido sobre el mismo Artifact único (`prototipo_lead_close_won.html`): nueva pantalla `screen-pipeline-lista`, ítem de navegación `.nav-pipeline`, transición contextual completa, y corrección de correspondencia visual (criterio "Requiere atención" → resalte del KPI "Estancados +5 días", en vez de forzar una correspondencia inexistente en la Statistic Grid). Contenido literal completo (EXP-08→EXP-12, Screen Contract de la Vista principal, resumen de Wireframe/Mockup) persistido en `MAIEK_AI_EXPERIENCE_FLOWS.md` v1.4, Secciones C.4.2/C.4.3 — no se duplica acá. Verificación por trazado estático y sintaxis JavaScript real (`node -c`, sin errores); **validación visual/interactiva real no pudo ejecutarse por limitación del entorno** (Artifact fuera del proyecto, renderizado como snapshot estático) — misma limitación ya documentada para el resto del Prototipo, no exclusiva de UF-08. **Estado final: UF-08 — IMPLEMENTADO, FUNCIONALMENTE CONSISTENTE, VALIDACIÓN VISUAL/INTERACTIVA EXTERNA PENDIENTE.** No se creó EXP, UF ni SCR nuevo. No se modificó Product Patterns, UX Blueprint ni arquitectura. Pendiente real, no bloqueante: implementación completa de la Tabla/Data Grid de la Vista principal de Pipeline (Filtros/Ordenamiento/Paginación reales, más allá del subconjunto mínimo ya implementado). |
| 1.0 | 2026-09-12 | Claude | **[ADR-0003](adr/0003-identidad-marca-unica-plataforma.md) — retiro de "identidad de marca resoluble por negocio (Frontend)" del alcance de Fase 3** (sección 4, párrafo de Fase 3, y fila correspondiente de la Matriz de trazabilidad, sección 8). Decisión de producto confirmada por el usuario: Maiek AI mantiene identidad única de plataforma, independiente de `negocio_id` — no white-label, sin branding dinámico por tenant. `MAIEK_AI_FRONTEND_ARCHITECTURE.md` se actualiza en el mismo cambio, marcando su Decisión local original como `Superseded`, conservada por trazabilidad. Ningún otro ítem de Fase 3 (Security, AI, DevOps, Operations) se modifica. |

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

## 2.2 Metodología de Product Design (especialización del paso 2, Diseño técnico)

A partir de la fase de Product Design (2026-08-08, posterior al congelamiento funcional de
`MAIEK_AI_UX_BLUEPRINT.md`), el paso 2 ("Diseño técnico") del ciclo de la sección 2.1 se especializa
para todo recorrido de producto (Journey) en la siguiente cadena de trazabilidad, en este orden, sin
saltar capas:

```
Journey Maestro → Experience Flow → User Flow → Screen Contract → Wireframes →
Mockups de Alta Fidelidad → Prototipo Navegable → Validación con usuarios
```

- **Journey Maestro** — el recorrido de negocio completo (ej. Primer Contacto → Close Won →
  Aprendizaje), con sus etapas y el objetivo de cada una. Vive en el inventario maestro de User
  Flows de la fase de Product Design.
- **Experience Flow** — puente entre el Journey y el User Flow. Empieza siempre declarando su
  **Pregunta cognitiva** — la incertidumbre concreta que ese Experience Flow existe para resolver,
  en una sola oración (ej. *"¿Cuál es la única acción que merece mi atención primero?"*). No es un
  principio nuevo ni un objetivo funcional — es la formulación explícita de lo que ya estaba
  implícito en cada paso, y es lo que distingue de un vistazo un Experience Flow que reduce
  incertidumbre entre varias opciones (triage) de uno que profundiza un único caso ya elegido.
  Luego define qué necesita **sentir**, **comprender** y qué **necesidad cognitiva** debe resolver
  el usuario en cada paso, más el **riesgo UX** a evitar y el **criterio de éxito** observable —
  nunca describe pantallas ni componentes. Cada paso tiene un ID permanente (`EXP-NN`) citable
  desde las capas siguientes, **compartido y consecutivo entre todos los Journeys** (no se reinicia
  por recorrido) — un Experience Flow puede terminar entregando (handoff) directo a un paso ya
  existente de otro recorrido, sin duplicarlo.
- **User Flow** — la secuencia concreta pantalla por pantalla que satisface al Experience Flow,
  resolviendo los puntos de decisión que el Gap Analysis previo dejó identificados. Dentro del User
  Flow, cada paso se descompone en:

  ```
  Pantalla → Patrón (MAIEK_AI_PRODUCT_PATTERNS.md) → Componente (MAIEK_AI_COMPONENT_SYSTEM.md)
  ```

  Un User Flow nunca inventa una pantalla nueva — compone patrones ya aprobados (mismo principio ya
  fijado en `MAIEK_AI_UX_BLUEPRINT.md` Cap. 2, §2.1). Si un paso del Experience Flow no tiene patrón
  del que partir, eso es una brecha de Product Patterns, no algo que el User Flow deba resolver
  inventando composición nueva. Cada paso tiene un ID permanente (`UF-NN`), **compartido y
  consecutivo entre todos los Journeys, mismo criterio que `EXP-NN`** — un recorrido que reutiliza
  pantallas ya construidas cita los `UF-NN` existentes en vez de renumerarlos, y un User Flow nuevo
  puede entregar (handoff) directo a un paso ya existente de otro recorrido, sin duplicarlo.
- **Screen Contract** — el contrato funcional completo de cada pantalla del User Flow (objetivo,
  disparador, información que recibe/entrega, acciones, patrón consumido, EXP que satisface, riesgo
  UX, criterio de éxito, precondiciones, postcondiciones, estado al abandonar, dependencias, errores
  de experiencia previstos) — sin hablar todavía de layout ni componentes. Cada pantalla tiene un ID
  permanente (`SCR-NN`), **compartido y consecutivo entre todos los Journeys, mismo criterio que
  `EXP-NN` y `UF-NN`** — una pantalla reutilizada conserva su ID original, nunca se renumera al
  citarse desde un recorrido distinto al que la creó.
- **Wireframes** — estructura y comportamiento de baja fidelidad que satisface al Screen Contract.
- **Mockups de Alta Fidelidad** — diseño visual completo (tokens de `MAIEK_AI_DESIGN_SYSTEM.md` y
  `MAIEK_AI_COMPONENT_SYSTEM.md`) sobre wireframes ya congelados — no modifica objetivos,
  comportamiento, navegación ni responsabilidades; solo resuelve jerarquía visual, sistema visual,
  espaciado, tipografía, color, iconografía, estados visuales, microinteracciones, motion,
  accesibilidad y responsive.
- **Prototipo Navegable** — el recorrido completo interactivo sobre los Mockups ya congelados: estados
  interactivos, transiciones, animaciones, microinteracciones, feedback, estados de carga/vacío/error,
  confirmaciones, navegación real entre pantallas. El objetivo deja de ser "que se vea bien" y pasa a
  ser validar la experiencia completa.
- **Validación con usuarios** — última capa, fuera del alcance de esta sección (se especializa cuando
  se construya).

**Patrón institucionalizado — única superficie dominante.** Cada pantalla tiene una única superficie
dominante para su acción principal; toda acción secundaria permanece visualmente subordinada. Aplica
a todo recorrido futuro salvo razón excepcional declarada explícitamente.

**Regla de sincronización entre capas.** Si una capa superior (Prototipo, implementación o
validación) descubre un error objetivo en una capa inferior (Mockup, Wireframe o Screen Contract), la
capa inferior se corrige para mantener el corpus consistente — **siempre que la corrección no
implique una nueva decisión de diseño ni contradiga el comportamiento ya congelado**. Una corrección
de fidelidad entre representaciones (ej. una dirección de burbuja de chat invertida) no reabre el
congelamiento de la capa; una decisión de diseño nueva sí lo reabre y sigue el ciclo completo de
revisión.

**Principio de reutilización primero.** Ante una nueva necesidad de Product Design, el orden de
evaluación es siempre: (1) ¿ya existe un artefacto que cubra este comportamiento? (2) ¿puede
fortalecerse ese artefacto (generalizar su Objetivo/Precondiciones sin cambiar su comportamiento
observable)? (3) ¿puede extenderse (agregar un estado o rama nueva sin crear un artefacto
paralelo)? (4) solo si ninguna de las tres alcanza, crear un artefacto nuevo. La reutilización es
la regla; la creación de un artefacto nuevo es la excepción, sustentada por evidencia — nunca el
punto de partida por defecto. Todo Gap Analysis de un recorrido nuevo debe incluir una **Matriz de
Reutilización** (artefacto / estado — Reutilizable, Reutilizable con ajuste, Nuevo / acción) como
entregable explícito, no solo como descripción en prosa — permite medir, recorrido a recorrido,
cuánto del Product Design efectivamente se reutiliza. Validado empíricamente en el recorrido #2
(Conversación → Lead generado, 2026-08-08): 9 de 9 artefactos reutilizables, 1 fortalecido (2 de 14
campos de un Screen Contract), 0 artefactos nuevos, 0 pantallas nuevas.

**Ciclo por recorrido:** Gap Analysis → Journey Maestro → Experience Flow → User Flow → Screen
Contract → Wireframes (con revisión horizontal propia) → Mockups (con revisión horizontal propia) →
Prototipo Navegable → **Auditoría Horizontal Integral del Prototipo** (recorrido completo como una
sola experiencia, no pantalla por pantalla) → ajustes → **Congelamiento de Product Design** del
recorrido. No se avanza al siguiente Journey/User Flow hasta cerrar este ciclo completo.

**Gap Analysis previo (sección 2.1, paso 1) aplicado a un Journey:** identifica qué recorridos, patrones
y decisiones ya existen en el corpus (Product Patterns, UX Blueprint) contra lo que un User Flow
concreto necesita — mismo criterio de evidencia que el resto del ciclo, nunca asumir.

**Validado empíricamente** en la construcción del primer Journey de la fase (Lead → Close Won,
2026-08-08 — ciclo completo cerrado hasta Congelamiento de Product Design) — confirmado explícitamente
por el usuario como la metodología a conservar para todos los recorridos futuros del producto.

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
Solo puede empezar cuando la Fase 2 esté completa. Extiende `negocio_id` a: autorización/visión total (Security), prompt y configuración por negocio (AI), principio de aislamiento de recursos si se decide (DevOps), segmentación de procesos operativos (Operations). *(La identidad de marca por negocio (Frontend) fue retirada del alcance de esta Fase — [ADR-0003](adr/0003-identidad-marca-unica-plataforma.md), 2026-09-12: Maiek mantiene identidad única de plataforma, independiente de `negocio_id`, no white-label.)*

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
| ~~Frontend Architecture — identidad de marca resoluble por negocio~~ | — | **Retirada — [ADR-0003](adr/0003-identidad-marca-unica-plataforma.md)** | — |
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
