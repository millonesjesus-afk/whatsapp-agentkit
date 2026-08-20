# Maiek AI — AI Architecture

**Versión 1.0 · Estado: Approved**

| | |
|---|---|
| Documento | AI Architecture |
| Proyecto | Maiek AI |
| Versión | 1.0 |
| Estado | **Approved** |
| Fecha de creación | 2026-07-28 |
| Autor | Claude, a pedido de Jesús Millones |
| Fecha de aprobación | 2026-07-28 |
| Última actualización | 2026-08-08 (sección 2 — contexto de campaña como extensión de Conocimiento transaccional, ver Control de versiones) |

## Dependencias

- `MAIEK_AI_SYSTEM_ARCHITECTURE.md` (MSA) Capítulo 6 (AI Engine como Platform Engine), Capítulo 7 (Arquitectura de IA — alto nivel), Capítulo 11 (Constraints).
- `MAIEK_AI_BACKEND_ARCHITECTURE.md` — protocolo de confianza `{respuesta, confianza, razon}` y `ServicioInteligencia` como punto de integración — **decisiones heredadas, no redefinidas acá**.
- `MAIEK_AI_API_ARCHITECTURE.md` — AI Architecture es un Platform Engine consumido vía contrato interno de plataforma, nunca vía `/api/v1/` externo — **decisión heredada, no redefinida acá**.
- `MAIEK_AI_DATA_ARCHITECTURE.md` — `MemoriaPersistente`, `SugerenciaIA` — este documento especifica **cómo el AI Engine las alimenta y consume**, no su modelo de datos, que pertenece a Data Architecture.
- `MAIEK_AI_PRODUCT_EXPERIENCE.md` (MPX) Capítulo 2 (Protocolo de interacción con IA), Capítulo 3 (Explainability First), Capítulo 8 (tres tipos de memoria), Capítulo 10 (Experience Metrics).
- `MAIEK_AI_AI_CURRENT_STATE_ASSESSMENT.md` (CSA-AI) — diagnóstico del que este documento parte.
- `MAIEK_AI_ARCHITECTURE_DOCUMENT_STANDARD.md` (ADS) v1.3.

## Consumido por

Frontend Architecture, Security Architecture, DevOps/Operations Architecture (futuros) — en particular, la delimitación estructural del contexto (sección 3) es insumo directo de Security Architecture, y el registro de inferencias (sección 9) es insumo directo de DevOps/Operations Architecture.

## Control de versiones

| Versión | Fecha | Autor | Descripción |
|---|---|---|---|
| 1.0 (borrador) | 2026-07-28 | Claude | Primera versión — arquitectura objetivo de AI, construida sobre el CSA-AI aprobado. Incorpora las 4 observaciones del usuario sobre clasificación de fuentes de conocimiento, caracterización de inferencia única, trazabilidad de prompts vs. decisiones, y terminología independiente de la implementación. Pendiente de revisión y aprobación. |
| 1.0 | 2026-07-28 | Claude | Aprobado. Se incorporaron 2 mejoras conceptuales antes de la aprobación: (1) el **AI Orchestrator**, modelado explícitamente como componente responsable de recuperación de contexto, construcción del prompt, invocación del modelo, emisión de confianza y registro de inferencias — el AI Engine deja de leerse como sinónimo de "el modelo" (sección 1); (2) el principio **Explainability First** (MPX Cap. 3), incorporado como sección propia dentro de Gestión de incertidumbre (sección 6), con su propio Architecture Success Criterion (#6). Se corrigieron además varias referencias cruzadas a secciones no numeradas del documento. El usuario registró 3 recomendaciones menores para futuras versiones, sin incorporar ahora: (a) expresar el constraint de prompt caching de forma independiente del proveedor, señalando a Anthropic como implementación concreta; (b) agregar como criterio verificable que `razon` nunca sea vacío cuando se emite confianza; (c) reforzar el principio de independencia de proveedor de modelos, documentando que el AI Engine no depende de capacidades exclusivas de un LLM salvo cuando se indique explícitamente. |
| 1.0 | 2026-08-08 | Claude | **Sección 2 — el contexto de campaña se declara extensión de Conocimiento transaccional, no una fuente nueva.** Formaliza, en la capa de AI Architecture, la decisión de producto que resolvió la Brecha B del recorrido #5 de Product Design: el contexto promocional de una campaña de origen (`resolver_promo`/`agent/campanas.py`) puede incorporarse al turno conversacional, condicionado a que la capacidad esté habilitada y a las reglas de negocio aplicables (MPA §4, relación Campañas → Agentes IA, agregada en la misma fecha) — nunca automático u obligatorio. No se definen todavía las reglas de cuándo/cómo se usa ese contexto, ni si el Copiloto IA lo comparte — quedan pendientes de Product Patterns y MPX. |

## Alcance y regla de no-duplicación

Define **cómo debe comportarse y estructurarse** el AI Engine para servir el protocolo de confianza ya decidido en Backend Architecture, el contrato interno ya decidido en API Architecture, y las entidades de memoria ya decididas en Data Architecture. **No redefine** el schema `{respuesta, confianza, razon}`, ni el mecanismo de acceso interno, ni el modelo de datos de `MemoriaPersistente`/`SugerenciaIA` — eso pertenece a los documentos owner respectivos y se cita, nunca se copia (ADS §10). Este documento resuelve exclusivamente el dominio de AI: construcción cognitiva, prompts, recuperación de contexto, incertidumbre, costo y seguridad del propio AI Engine.

---

## 1. Arquitectura cognitiva objetivo

El AI Engine mantiene, como decisión deliberada y no como carencia, el patrón ya identificado en el CSA: **una única inferencia enriquecida por recuperación previa (retrieval-then-generate)**, sin planificación iterativa ni ciclos de razonamiento con herramientas. No es un rediseño hacia un agente con tool-calling — es la confirmación explícita de que ese patrón es el correcto para el volumen y la complejidad actuales, con un criterio de revisión declarado (Decisiones locales).

La única extensión sobre el flujo ya descrito en el CSA-AI (sección 1) es la incorporación del protocolo de confianza: la llamada principal debe retornar, en la misma inferencia, el texto de respuesta **y** la señal de confianza — nunca una llamada adicional (Architectural Constraints).

### El AI Orchestrator

**El AI Engine no es únicamente el modelo de lenguaje — es el conjunto de componentes que implementan el comportamiento cognitivo descrito en este documento.** Se modela explícitamente un componente, el **AI Orchestrator**, responsable de coordinar cinco responsabilidades distintas:

| Responsabilidad | Qué hace |
|---|---|
| Recuperación de contexto | Resuelve las seis fuentes de conocimiento (sección 2) relevantes para el turno actual |
| Construcción del prompt | Ensambla el `system` estático y el `user` dinámico, con la delimitación estructural exigida en la sección 3 |
| Invocación del modelo | Realiza la llamada de inferencia, respetando el máximo de llamadas por mensaje (Constraint, Architectural Constraints) |
| Emisión de confianza | Extrae y valida la señal `{respuesta, confianza, razon}` (sección 6) de la salida del modelo antes de retornarla |
| Registro de inferencias | Persiste el contexto usado y la decisión emitida, alimentando `SugerenciaIA` (sección 9) |

El AI Orchestrator es **interno al dominio de AI Architecture** — es lo que hay del lado del AI Engine cuando `ServicioInteligencia` (Backend Architecture) lo invoca a través del contrato interno de plataforma (API Architecture). Ninguno de esos dos documentos se redefine acá: el AI Orchestrator es la implementación concreta de la responsabilidad que ambos ya le asignan al AI Engine, no un componente nuevo que compita con ellos.

Nombrar el AI Orchestrator evita que "AI Engine" se lea como sinónimo de "el modelo" en el resto de este documento y en los que lo consuman — el modelo de lenguaje es reemplazable (Architectural Constraints, independencia de proveedor); el AI Orchestrator, con sus cinco responsabilidades, es la parte estable del diseño.

## 2. Clasificación de fuentes de conocimiento

El AI Engine consume seis fuentes de conocimiento distintas, hoy mezcladas sin distinción formal en el código (CSA-AI, sección 2-4). Esta clasificación es la base para decidir qué se cachea, qué se audita y qué se aísla por negocio en Multi-Tenant:

| Fuente | Naturaleza | Ejemplo actual | Implicación arquitectónica |
|---|---|---|---|
| **Conocimiento estático** | No cambia entre turnos ni conversaciones; propio del negocio | System prompt, base de conocimiento (`knowledge/*.md`) | Candidato a *prompt caching*; debe parametrizarse por `negocio_id` |
| **Conocimiento operacional** | Cambia con baja frecuencia, gobierna reglas de atención | Horario de atención, políticas comerciales | Se recalcula por turno, pero es determinístico y barato |
| **Conocimiento transaccional** | Cambia con frecuencia media, específico del catálogo/oferta vigente | Catálogo de precios, promociones activas (incluida la promoción de la campaña de origen del lead, cuando esa capacidad está habilitada — MPA §4) | Requiere invalidación de caché al cambiar (brecha ya señalada en el CSA) |
| **Memoria conversacional** | Específica de la conversación en curso | Historial de mensajes | Ya implementada (`Mensaje`); límite de 20 mensajes ya fijado en Data Architecture |
| **Contexto temporal** | Se construye y se descarta en cada turno | Bloques armados por `_armar_bloques_contexto` | No persiste — por diseño |
| **Configuración del negocio** | Específica del tenant, gobierna cómo se comporta el AI Engine | Modo (pruebas/producción), tono, restricciones | Debe resolverse por `negocio_id`, no solo por canal (brecha Multi-Tenant, CSA-AI §10) |

Esta clasificación no introduce una nueva entidad de datos — es un criterio de diseño que Data Architecture y Security Architecture deben poder referenciar al decidir aislamiento y caching por tenant.

El contexto de campaña (MPA §4, relación Campañas → Agentes IA) no constituye una séptima fuente de conocimiento — es una extensión de **Conocimiento transaccional**, ya existente, sujeta a la misma implicación arquitectónica de esa fila (invalidación de caché al cambiar). Su incorporación al turno conversacional queda condicionada a que la capacidad esté habilitada y a las reglas de negocio aplicables — nunca un comportamiento automático obligatorio. Este documento no define esas reglas (cuándo, con qué prioridad, ni si el Copiloto IA las comparte) — quedan pendientes de Product Patterns y MPX cuando corresponda.

## 3. Construcción de prompts objetivo

Se preserva la separación ya correcta entre `system` (estático) y `user` (dinámico) — confirmada como fortaleza en el CSA. Se agrega una exigencia estructural nueva: **el contexto de confianza (catálogo, promoción, configuración del negocio) y el mensaje del cliente deben ser distinguibles entre sí dentro del turno `user`**, mediante un formato de delimitación explícito (p. ej. bloques marcados), en vez de la concatenación de texto plano actual.

Esto no es una recomendación de seguridad genérica — es la mitigación directa al riesgo de prompt injection identificado en el CSA-AI §8, y una condición verificable (Architecture Success Criteria).

Las restricciones de comportamiento (sección "Restricciones — NUNCA hagas esto" del prompt) siguen siendo, por naturaleza, instrucciones a nivel de modelo — ningún proveedor de LLM ofrece hoy una forma de forzarlas técnicamente (Architectural Constraints). Lo que sí cambia es que dejan de ser la única defensa: el protocolo de confianza (sección 6) y el registro de inferencias (sección 9) dan, por primera vez, una forma de detectar cuándo una restricción no se respetó, después del hecho.

## 4. Uso de herramientas objetivo

Se mantiene el patrón de recuperación determinística en Python (no tool-calling de la API del modelo) como **decisión activa**, no como una brecha a cerrar — ver Decisiones locales. El modelo de lenguaje sigue sin decidir qué recuperar; el AI Orchestrator (sección 1) decide antes de invocarlo.

## 5. Modelo de razonamiento objetivo

La frontera ya observada en el CSA-AI §5 (la IA genera texto; el backend decide flujo, asignación y escalamiento) se formaliza como **contrato explícito del AI Engine**, no solo como una convención de código: el AI Engine nunca debe retornar ni implicar una acción de negocio (asignar, escalar, aprobar) — solo texto de respuesta y la señal de confianza del protocolo ya decidido en Backend Architecture. Toda acción de negocio sigue siendo responsabilidad exclusiva de `ServicioInteligencia` y las capas que lo consumen (Backend Architecture).

## 6. Gestión de incertidumbre objetivo

Se implementa acá, sin redefinirlo, el protocolo de confianza ya decidido en Backend Architecture: la llamada principal del AI Engine retorna `{respuesta, confianza, razon}` en una única inferencia — `confianza` usa el vocabulario ya fijado en MPX Cap. 2 (`Alta`/`Requiere validación`/`Baja`), `razon` es una justificación breve en lenguaje natural, no una estructura adicional.

El AI Engine es responsable de **emitir** la señal; no le corresponde decidir qué hacer con una confianza baja (eso es Backend, vía el protocolo ya decidido). El umbral de negocio que separa cada nivel de confianza queda como brecha abierta (Brechas conocidas) — es una decisión de producto, no arquitectónica.

### Explainability First

Más allá de emitir un nivel de confianza, el AI Engine debe respetar el principio de **Explainability First** ya establecido en MPX Cap. 3: toda respuesta generada debe poder reconstruirse a partir del contexto que la originó — qué fuentes de conocimiento (sección 2) vio el modelo, qué prompt exacto recibió, y qué llevó a la señal de confianza emitida. Este documento no redefine el principio, ya decidido en MPX — lo implementa en el dominio de AI.

La `razon` del protocolo de confianza es la primera pieza de esa reconstrucción, pero no la única — por sí sola no basta para responder "¿por qué esta respuesta?" en el sentido que exige MPX Cap. 3 (¿por qué?/¿por qué ahora?/¿por qué yo?). Es el registro de inferencias del AI Orchestrator (sección 9) el que hace posible la reconstrucción completa, correlacionando el contexto exacto usado con la respuesta emitida — sin ese registro, Explainability First queda como principio aspiracional, no como propiedad verificable del sistema.

## 7. Costo y eficiencia objetivo

- **Máximo 2 llamadas de IA por mensaje se mantiene como constraint** (Architectural Constraints) — la señal de confianza viaja en la misma llamada de respuesta, nunca en una tercera.
- **Prompt caching del contenido estático** (system prompt, base de conocimiento) se activa — ya preparado en el código, ahora se convierte en requisito arquitectónico, no una optimización opcional.
- **Límite explícito de tamaño de contexto ensamblado** antes de cada llamada — evita el crecimiento sin control ya señalado en el CSA.
- El costo diferenciado por tarea (modelo económico para extracción, modelo completo para respuesta) se preserva sin cambios — ya es correcto.

## 8. Seguridad del agente objetivo

La delimitación estructural de la sección 3 es la decisión central de esta sección. Además:

- Los campos de un lead que se reinyectan en turnos futuros (`nombre`, `interes`) deben tratarse como **contenido no confiable**, igual que el mensaje del cliente — no como configuración del negocio.
- La ausencia de tool-calling se mantiene como una superficie de ataque que **no existe hoy** — cualquier decisión futura de exponer herramientas reales a la API del modelo (más allá de la recuperación determinística ya descrita) requiere pasar primero por una decisión explícita de Security Architecture, no una adopción incidental.

## 9. Observabilidad objetivo

Se distinguen dos capas de trazabilidad, hoy confundidas en una sola ausencia total (CSA-AI §9):

- **Trazabilidad de prompts**: registro de qué contexto exacto (system + bloques dinámicos + mensaje) se envió al modelo en un turno dado. Responde "¿qué vio el modelo?".
- **Trazabilidad de decisiones del AI Engine**: registro de qué retornó el modelo — respuesta, confianza, razón, y el resultado de la inferencia especializada en extracción estructurada — junto con el estado del `Lead` antes y después. Responde "¿qué decidió y con qué base?".

Ambas capas alimentan `SugerenciaIA` (Data Architecture) como su mecanismo de persistencia — este documento no redefine esa entidad, solo especifica que el AI Engine debe producir la información necesaria para llenarla en ambas dimensiones, no solo una. Producir ese registro es, específicamente, la responsabilidad de "registro de inferencias" del AI Orchestrator (sección 1) — sin ella, Explainability First (sección 6) no es verificable.

## 10. Preparación para Multi-Tenant

El prompt del AI Engine y la clasificación de fuentes de conocimiento (sección 2) deben poder resolverse por `negocio_id`, no solo por canal como hoy. Este documento no diseña el mecanismo de aislamiento entre negocios — eso depende del diseño de aislamiento de datos que Data Architecture Fase 3 todavía no resuelve (brecha ya registrada en memoria del proyecto) — solo deja establecido que el AI Engine debe estar preparado para consumirlo una vez exista.

---

## Architectural Constraints

| Restricción | Naturaleza | Impacto en el diseño |
|---|---|---|
| La ventana de contexto del modelo es finita | Hecho del proveedor (Anthropic/Claude) | Obliga a un límite explícito de tamaño de contexto ensamblado (sección 7) |
| El costo de inferencia es proporcional a tokens de entrada y salida | Hecho del proveedor | Justifica priorizar prompt caching sobre otras optimizaciones |
| El seguimiento de instrucciones de un LLM es probabilístico, no garantizado técnicamente | Hecho de cómo funcionan los modelos de lenguaje, no una limitación de este proyecto | Ninguna restricción del prompt puede depender solo de la instrucción — de ahí el registro de inferencias (sección 9) como mecanismo de verificación posterior |
| El *prompt caching* de Anthropic requiere que el prefijo cacheado sea idéntico byte a byte y esté marcado explícitamente | Hecho del mecanismo del proveedor | Restringe qué contenido puede ir en el `system` (debe ser 100% estático) vs. el `user` |
| Máximo de llamadas de IA por mensaje = 2 | Constraint ya fijada en Backend Architecture y API Architecture, heredada acá sin redefinirse | La señal de confianza debe viajar en la llamada de respuesta, nunca en una tercera |

## Decisiones locales

| Decisión | Estado | Justificación | Criterio de revisión |
|---|---|---|---|
| Adoptar `{respuesta, confianza, razon}` en la llamada principal | Objetivo | Cierra la brecha central del CSA-AI; hereda Backend Architecture | Si el proveedor de IA deja de soportar salida estructurada confiable |
| Clasificar las fuentes de conocimiento en 6 categorías (sección 2) | Objetivo | Necesaria para razonar sobre caching, auditoría y Multi-Tenant | Si aparece una fuente que no encaja en ninguna categoría |
| Delimitar estructuralmente contexto de confianza vs. mensaje del cliente en el turno `user` | Objetivo | Mitigación directa de prompt injection (CSA-AI §8) | Si el proveedor ofrece un mecanismo nativo mejor para esa separación |
| Mantener recuperación determinística en Python, sin tool-calling agéntico | **Activa** | Proporcional al volumen y complejidad actuales (Evidence over Opinion) | Si el catálogo o las reglas de negocio crecen a un punto donde el keyword matching muestre una tasa de fallo de recuperación evidenciable |
| Activar prompt caching del contenido estático | Objetivo | Ahorro de costo directo; ya preparado en el código | — |
| Registrar cada inferencia (prompt enviado + salida + confianza) como base de `SugerenciaIA` | Objetivo | Cierra la falta de auditabilidad del CSA-AI §9 | Si el volumen de almacenamiento crece desproporcionadamente al valor de la auditoría |
| Parametrizar el prompt del AI Engine por `negocio_id`, no solo por canal | Objetivo, dependiente de Data Architecture Fase 3 | Brecha Multi-Tenant identificada en el CSA-AI §10 | Cuando exista un segundo negocio real (condición ya registrada en memoria del proyecto) |
| Preservar el modelo cognitivo de inferencia única + recuperación previa, sin bucle agéntico | **Activa** | Observación explícita del usuario: evitar cualquier lectura de "agente" en sentido moderno sin evidencia de necesidad | Si una tarea requiere pasos de razonamiento dependientes entre sí que una sola inferencia no puede resolver |
| Modelar el AI Orchestrator como componente arquitectónico explícito, distinto del modelo de lenguaje | Objetivo | Evita que "AI Engine" se lea como sinónimo de "el modelo"; hoy vive implícito en `brain.py` sin frontera ni nombre propio | Si el AI Orchestrator crece lo suficiente como para justificar dividirse en sub-componentes |
| Adoptar Explainability First (MPX Cap. 3) como principio rector del AI Engine, implementado vía el registro de inferencias del AI Orchestrator | Objetivo | Hereda MPX; cierra la brecha de "por qué" más allá del score de confianza | Si el registro de inferencias no permite reconstruir en la práctica la base de una respuesta dada |

## Brechas conocidas

- **Emisión y rotación de credenciales del proveedor de IA** → Security Architecture.
- **Rate limiting / control de abuso sobre la llamada de IA** → Security/DevOps Architecture (ya señalada en API Architecture).
- **Estrategia de versionado del system prompt** (cómo se audita un cambio de contenido) → sin dueño asignado todavía; queda como pregunta abierta.
- **Umbral exacto que separa `Alta`/`Requiere validación`/`Baja`** → decisión de producto, no arquitectónica; a definir junto con Backend Architecture al implementar.
- **Mecanismo de aislamiento de fuentes de conocimiento por tenant** → depende del diseño de aislamiento de datos de Data Architecture Fase 3, no resuelto acá.

## Architecture Success Criteria

1. Toda llamada de generación de respuesta del AI Engine retorna un campo de confianza estructurado (`Alta`/`Requiere validación`/`Baja`) en la misma inferencia — verificable inspeccionando la respuesta cruda de la API.
2. El número de llamadas de IA por mensaje procesado nunca excede 2 — verificable contando invocaciones por mensaje en los logs.
3. El mensaje del cliente y el contexto de confianza están delimitados de forma distinguible dentro del turno `user` — verificable inspeccionando el payload enviado al modelo.
4. Para cualquier conversación dada, se puede reconstruir qué contexto vio el modelo y qué decidió, sin depender solo del resultado final en el `Lead` — verificable consultando el registro de `SugerenciaIA`.
5. El system prompt puede resolverse por `negocio_id`, no solo por canal — verificable con al menos dos negocios activos usando prompts distintos simultáneamente.
6. Para cualquier respuesta generada, es posible reconstruir qué fuentes de conocimiento y qué prompt exacto la originaron, no solo su nivel de confianza (Explainability First) — verificable tomando una respuesta al azar del registro de inferencias y confirmando que el contexto asociado explica su contenido.

## QA arquitectónico

Este documento fue verificado contra el checklist de 11 preguntas del ADS §11 antes de presentarse — en particular, se confirmó que ninguna Architectural Constraint listada es en realidad una decisión (todas son hechos del proveedor o del entorno) y que las 6 Architecture Success Criteria son condiciones verificables, no tareas de roadmap.

## Cierre

Este documento cierra el diseño objetivo del dominio de AI, construido sobre el CSA-AI ya aprobado y sin redefinir ninguna decisión ya tomada en Backend, API o Data Architecture. **Approved** el 2026-07-28.

---

*Fin del documento.*
