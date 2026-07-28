# Maiek AI — Architecture Document Standard (ADS)

**Versión 1.2 · Estado: Approved**

| | |
|---|---|
| Documento | Maiek Architecture Document Standard (ADS) |
| Proyecto | Maiek AI |
| Versión | 1.2 |
| Estado | **Approved** |
| Fecha de creación | 2026-07-28 |
| Autor | Claude, a pedido de Jesús Millones |
| Fecha de aprobación | 2026-07-28 |
| Última actualización | 2026-07-28 |

## Dependencias

- `MAIEK_AI_SYSTEM_ARCHITECTURE.md` (MSA) — de donde se extraen los patrones ya validados que este estándar formaliza: regla maestra de no-duplicación, formato de Architectural Decisions, declaración explícita de brechas, nota de QA arquitectónico.
- `DOCUMENTATION_INDEX.md` — reglas de gobernanza documental general (sección 8), de las que este documento es una instancia especializada para documentos técnicos de arquitectura.
- `MAIEK_AI_ARCHITECTURE_BASELINE_V1.md` — riesgo de "terminología sin fuente única" (CDS vs. MPX) usado acá como caso de qué evitar.

## Consumido por

Data, Backend, AI, API, Frontend, Security, DevOps y Operations Architecture — los 8 documentos técnicos derivados del MSA, ninguno construido todavía. Este documento es su estándar de referencia — ver sección 1 para el criterio de desviación justificada.

## Control de versiones

| Versión | Fecha | Autor | Descripción |
|---|---|---|---|
| 1.0 (borrador) | 2026-07-28 | Claude | Primera versión — plantilla oficial para los 8 documentos técnicos derivados del MSA, extraída de los patrones ya validados en MSA y en el resto del corpus. |
| 1.0 (Approved) | 2026-07-28 | Claude | Revisión final: "plantilla obligatoria" pasa a **"estándar de referencia"**, con desviaciones justificadas permitidas cuando el tipo de documento lo requiera (sección 1); se agrega la sección **12, Ciclo de estados de un documento de arquitectura** (Draft → Architecture Review → Approved → Frozen), mapeada explícitamente sobre el ciclo de 6 estados ya fijado en `DOCUMENTATION_INDEX.md` — Frozen no es un séptimo estado nuevo, es un punto dentro de Approved; se agrega una novena pregunta al checklist de QA ("¿aporta conocimiento nuevo o duplica información ya existente?"). **Decisión de dominio:** se evaluó si este documento pertenece a un dominio de "Documentación/Gobernanza" distinto de los 5 dominios de contenido (Foundation/Engineering/Product/Design/Business) — se concluye que sí: el ADS no describe identidad, producto, diseño ni arquitectura de la plataforma, describe cómo se documenta la arquitectura. Se crea el dominio **Documentación** en `DOCUMENTATION_INDEX.md` sección 5 para este documento, sin mover retroactivamente `MAIEK_AI_ARCHITECTURE_BASELINE_V1.md` (conceptualmente similar, pero no fue pedido). El documento **permanece registrado en el corpus oficial** (tabla de la sección 7) por su relación directa y vinculante con las 8 arquitecturas derivadas — un dominio distinto no significa quedar fuera del índice. Documento congelado como **Approved**. |
| 1.1 (Approved) | 2026-07-28 | Claude | Se agrega la **Regla de herencia arquitectónica** (sección 7) tras la aprobación de Data Architecture: toda decisión de un documento superior es un contrato — un derivado solo puede implementarla, especializarla, o declarar una incompatibilidad justificada; cualquier cambio de fondo requiere reabrir el documento propietario, nunca modificarse implícitamente desde un derivado. |
| 1.2 (Approved) | 2026-07-28 | Claude | Se agrega la sección **13, Forma de documentar Architecture Success Criteria**, tras la aprobación del Current State Assessment de Backend: todo documento de arquitectura *objetivo* (no los Current State Assessment) cierra con una sección `## Architecture Success Criteria` — condiciones de éxito verificables sobre el sistema real, nunca tareas ni roadmap — justo antes de la nota de QA arquitectónico. Con esta incorporación, el usuario da por cerrada la metodología de documentación: el esfuerzo se concentra de acá en más en el contenido técnico de cada arquitectura derivada, no en ajustes adicionales al estándar. |

---

## 1. Propósito del ADS

Asegurar que los 8 documentos técnicos derivados compartan estructura, rigor y disciplina de no-duplicación, sin que cada uno la reinvente ni la calibre distinto. No es arquitectura de producto — es la forma en que se escribe arquitectura de producto en Maiek AI a partir de ahora.

Es un **estándar de referencia**, no una plantilla obligatoria sin excepción: una desviación es válida cuando la naturaleza del documento lo justifica (ej. un documento más procedimental que arquitectónico, como el futuro Operations Runbook) — se declara explícitamente en la sección de alcance del documento derivado, con una frase breve de por qué se aparta. Una desviación no declarada no es una excepción válida, es un incumplimiento del estándar.

## 2. Estructura estándar del documento

Todo documento derivado sigue este esqueleto, en este orden:

1. Portada (tabla de metadatos)
2. `## Dependencias`
3. `## Consumido por`
4. `## Control de versiones`
5. Alcance y regla de no-duplicación — qué cubre este documento, qué no, y a qué documento remite lo que no cubre
6. Cuerpo — capítulos/secciones específicas del dominio técnico
7. Decisiones locales (si el dominio toma alguna — sección 8, abajo)
8. Brechas conocidas (sección 9, abajo)
9. `## Architecture Success Criteria` — solo en documentos de arquitectura *objetivo* (Data, Backend, AI, API, Frontend, Security, DevOps, Operations Architecture), nunca en un Current State Assessment (sección 13, abajo)
10. Nota de QA arquitectónico (autorevisión, checklist de la sección 11)
11. Cierre / Estado del documento

## 3. Encabezados obligatorios

- Primera línea: `**Versión X.Y · Estado: ...**`
- Tabla de metadatos completa (Documento, Proyecto, Versión, Estado, Fecha de creación, Autor, Fecha de aprobación, Última actualización)
- `## Dependencias`, `## Consumido por`, `## Control de versiones`
- Una sección explícita de alcance ("qué cubre / qué no")
- Nota de QA arquitectónico antes del cierre

## 4. Secciones opcionales

- Constraints propias del dominio — solo si existen restricciones no cubiertas ya por MSA Cap. 11 (Architectural Constraints).
- Glosario — solo si el dominio introduce vocabulario técnico no usado en el resto del corpus.
- Diagramas Mermaid — cuando un flujo o una relación se entiende mejor visual que en prosa (mismo criterio ya usado en MSA Cap. 10 y MPA).

## 5. Convenciones de redacción

- Alto nivel, no implementación completa — un fragmento de código o un nombre de interfaz real (ej. `ProveedorWhatsApp`) puede ilustrar una decisión ya tomada, nunca reemplaza la especificación con código exhaustivo.
- Español, mismo registro que el resto del corpus: directo, sin relleno, sin adjetivos que no aporten información.
- Toda regla debe ser verificable, no solo aspiracional — mismo estándar ya fijado en MPX Cap. 0: si dos personas leyendo la misma regla tomarían decisiones distintas ante el mismo caso, la regla está mal escrita.
- Preferir tablas sobre prosa para: componentes, capas, decisiones, brechas, criterios de verificación — mismo patrón ya usado en MSA.

## 6. Reglas de dependencias

- Todo documento derivado declara MSA como dependencia obligatoria, citando los capítulos exactos de los que hereda (ya mapeados en MSA Cap. 17).
- Puede declarar dependencia de otro documento derivado ya construido (ej. Backend Architecture depende de Data Architecture) — nunca de uno que todavía no existe.
- Ninguna dependencia circular — se verifica contra el mapa Mermaid de `DOCUMENTATION_INDEX.md` sección 6 antes de aprobar, y ese mapa se actualiza al aprobarse el documento nuevo.

## 7. Reglas de no duplicación

- Regla maestra heredada del MSA: ningún documento derivado redefine qué hace el producto (MPA), cómo se ve (MDL/CDS), cómo se comporta (MPX), ni cómo está organizada la plataforma a alto nivel (MSA) — cada uno profundiza exclusivamente el capítulo del MSA que le corresponde.
- Si dos documentos derivados necesitan el mismo concepto técnico, uno lo declara como fuente única y el otro lo cita — nunca ambos lo definen por separado. Ver la Architecture Baseline v1 (riesgo de terminología CDS/MPX) como ejemplo concreto de qué evitar.
- Toda cita a otro documento nombra el capítulo o sección exacta — nunca "ver el documento X" sin más precisión.

**Regla de herencia arquitectónica.** Toda decisión arquitectónica aprobada en un documento superior (Framework, MPA, MDL, CDS, MPX, MSA, o cualquier documento derivado ya Approved, ej. Data Architecture para Backend Architecture) es un **contrato**. Un documento derivado no puede modificarla ni reinterpretarla — solo puede:
- **Implementarla** — ejecutar la decisión tal como está.
- **Especializarla** — aplicarla al dominio propio sin cambiar su sentido (ej. Backend Architecture especializa la estrategia UUID de Data Architecture a la forma concreta en que el ORM la genera, sin redecidir si se usa UUID).
- **Declarar una incompatibilidad técnica**, debidamente justificada y explícita — nunca una desviación silenciosa (mismo criterio que Brechas, sección 9).

Si una decisión necesita cambiar de fondo, se abre una revisión del documento **propietario** de esa decisión — nunca se modifica implícitamente desde un documento derivado. Un documento derivado que "ajusta" una decisión ya fijada sin pasar por esa revisión no está especializando, está violando el contrato.

## 8. Forma de documentar decisiones

Mismo patrón ya validado en MSA Cap. 12: prosa breve por decisión + tabla resumen con columnas **Decisión / Estado / Justificación / Criterio de revisión**.

- **Estado** usa vocabulario fijo: **Activa** (ya implementada) / **Objetivo** (decisión tomada, implementación parcial o pendiente) — no se inventan estados nuevos por documento.
- Una decisión cambia solo con evidencia + revisión de gobernanza (mismo criterio de Evidence over Opinion, MPX Cap. 11) — nunca por preferencia individual ni urgencia puntual.
- Decisiones ya fijadas en MSA Cap. 12 (API First, Event-Driven, Configuration over Code, Multi-Tenant por fila, Feature Flags) se citan, nunca se repiten ni se redeciden en un documento derivado.

## 9. Forma de documentar brechas

- Toda brecha conocida se declara explícitamente donde aparece, con el mismo patrón ya usado en MSA: *"brecha identificada, no resuelta todavía, señalada para [documento/dueño]"* — nunca se deja en silencio esperando que alguien la note.
- Una brecha sin dueño no se documenta como brecha — se documenta como pregunta abierta, y se resuelve antes de marcar el documento como Approved, no después.
- Una brecha lo bastante relevante para el corpus completo (no solo para ese documento) se anota también como candidata a una futura revisión de `MAIEK_AI_ARCHITECTURE_BASELINE_V1.md`.

## 10. Forma de documentar referencias cruzadas

- Formato fijo: `Documento Cap./Sección N` (ej. "MPX Cap. 2", "MPA sección 9", "MSA Cap. 8") — nunca solo el nombre del documento.
- Una referencia cruzada **cita, nunca copia** — si hace falta repetir una regla para que el texto se entienda, es señal de que la referencia está mal ubicada, no de que haga falta copiar el contenido.
- Todo documento nuevo actualiza el mapa Mermaid y la tabla de estado de `DOCUMENTATION_INDEX.md` sección 6-7 al aprobarse — ningún documento derivado queda como nodo huérfano.

## 11. Checklist de QA para arquitecturas técnicas

Checklist fijo que la nota de QA arquitectónico de cada documento derivado debe recorrer antes de pasar a revisión del usuario:

1. ¿Declara Dependencias y Consumido por, citando capítulos exactos del MSA?
2. ¿Ninguna sección redefine contenido ya cerrado en Framework, MPA, MDL, CDS, MPX o MSA?
3. ¿Toda decisión propia sigue el formato Decisión / Estado / Justificación / Criterio de revisión?
4. ¿Toda brecha conocida está declarada explícitamente, con dueño, o marcada como pregunta abierta sin resolver?
5. ¿Toda referencia cruzada cita capítulo/sección exacta, nunca solo el nombre del documento?
6. ¿Actualiza el mapa Mermaid y la tabla de estado de `DOCUMENTATION_INDEX.md`?
7. ¿El nivel de detalle es alto nivel, consistente con el resto del corpus, sin caer en implementación completa salvo para ilustrar una decisión ya tomada?
8. ¿Una persona nueva en el equipo, leyendo solo este documento y el MSA, entendería el dominio sin necesitar preguntar?
9. ¿Este documento aporta conocimiento nuevo o está duplicando información ya existente?
10. *(Solo en documentos de arquitectura objetivo)* ¿Cada Architecture Success Criteria es una condición verificable sobre el sistema real, y no una tarea, un roadmap ni una intención?

## 12. Ciclo de estados de un documento de arquitectura

Todo documento derivado atraviesa 4 momentos, en este orden — lectura específica del ciclo de vida general de 6 estados ya fijado en `DOCUMENTATION_INDEX.md` sección 3, no un ciclo nuevo ni paralelo:

1. **Draft** — igual al `Draft` general: contenido en construcción activa, no citable todavía.
2. **Architecture Review** — corresponde al `In Review` general, con nombre propio en este dominio porque su revisión específica es la nota de QA arquitectónico (sección 11) — nunca una revisión editorial genérica.
3. **Approved** — igual al `Approved` general: congelado como referencia oficial; cualquier cambio de fondo requiere una nueva entrada en Control de versiones.
4. **Frozen** — no es un séptimo estado del ciclo general (`DOCUMENTATION_INDEX.md` mantiene sus 6 estados sin excepción, decisión ya tomada y no reabierta acá) — es el punto **dentro de** Approved en que código real ya depende del documento. A partir de ahí, un cambio no es solo una edición de documentación: puede romper una implementación existente, y se evalúa con ese costo adicional antes de aprobarse (mismo criterio de evolución controlada ya definido en MSA Cap. 12 y MPX Cap. 11).

## 13. Forma de documentar Architecture Success Criteria

Todo documento de arquitectura **objetivo** (Data, Backend, AI, API, Frontend, Security, DevOps, Operations Architecture) cierra con una sección `## Architecture Success Criteria`, justo antes de la nota de QA arquitectónico. Un Current State Assessment **nunca** lleva esta sección — no propone una arquitectura sobre la que "tener éxito" todavía.

- Son **condiciones de éxito verificables**, no tareas ni roadmap. La pregunta que cada criterio responde es *"¿cómo sabemos que esto ya se logró?"*, nunca *"¿qué hay que hacer?"*.
- Cada criterio se redacta como una afirmación evaluable como verdadera o falsa sobre el sistema real — nunca como intención ("se buscará minimizar…") ni como tarea ("implementar X").
- Se listan como lista simple, sin tabla de Estado/Justificación — eso es para Decisiones (sección 8). Un criterio de éxito no tiene "estado": se cumple o no se cumple.
- Ejemplo válido: *"Ningún controlador contiene reglas de negocio"* — verificable inspeccionando el código. Ejemplo inválido: *"Reducir el acoplamiento del backend"* — no es medible sin más contexto.
- El roadmap (sección de Roadmap de evolución del documento) dice *cómo* se llega; Architecture Success Criteria dice *cómo se sabe que se llegó* — no son la misma sección ni se fusionan.

## Estado del documento

**Approved.** Estándar de referencia para Data Architecture (ya Approved) y los 7 documentos técnicos derivados restantes — con desviaciones justificadas permitidas según la sección 1, nunca silenciosas.
