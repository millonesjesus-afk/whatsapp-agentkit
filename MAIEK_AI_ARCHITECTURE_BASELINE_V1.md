# Maiek AI — Architecture Baseline v1

**Versión 1.0 · Estado: Approved**

| | |
|---|---|
| Documento | Maiek AI Architecture Baseline v1 |
| Proyecto | Maiek AI |
| Versión | 1.0 |
| Estado | **Approved** |
| Fecha de creación | 2026-07-28 |
| Autor | Claude, a pedido de Jesús Millones |
| Fecha de aprobación | 2026-07-28 |
| Última actualización | 2026-07-28 |

## Dependencias

- `MAIEK_AI_FRAMEWORK.md`, `MAIEK_AI_PRODUCT_ARCHITECTURE.md` (MPA), `MAIEK_AI_DESIGN_SYSTEM.md` (MDL), `MAIEK_AI_COMPONENT_SYSTEM.md` (CDS), `MAIEK_AI_PRODUCT_EXPERIENCE.md` (MPX), `MAIEK_AI_SYSTEM_ARCHITECTURE.md` (MSA), `DOCUMENTATION_INDEX.md` — el corpus completo que este documento certifica, formalizando el Architecture Review v1.0 ya revisado y aprobado.

## Consumido por

- Los 8 documentos técnicos derivados (Data, Backend, AI, API, Frontend, Security, DevOps, Operations Architecture) y QA Strategy / Testing Strategy — heredan los riesgos y vacíos aceptados acá como contexto conocido, no como algo a redescubrir.
- `DOCUMENTATION_INDEX.md`, que registra este documento como la **Baseline oficial del proyecto**.

## Control de versiones

| Versión | Fecha | Autor | Descripción |
|---|---|---|---|
| 1.0 | 2026-07-28 | Claude | Primera versión — formaliza el Architecture Review v1.0 (ya ejecutado y aprobado en revisión) como línea base oficial de la plataforma. Decisión: **Ready for Technical Expansion**. |

---

## 1. Objetivo de la Baseline

Certificar, en un solo documento breve, que la fase de **definición** de Maiek AI (identidad, producto, diseño, componentes, experiencia y arquitectura técnica de alto nivel) está completa, es internamente consistente, y constituye una base válida para iniciar la fase de **construcción técnica** (las 8 arquitecturas derivadas del MSA). No repite el contenido de ningún documento del corpus ni redesarrolla el Architecture Review — lo formaliza como hito oficial y punto de no retorno hacia la siguiente fase.

## 2. Corpus documental aprobado

Framework, MPA, MDL, CDS, MPX, MSA, `DOCUMENTATION_INDEX.md` — los 7 documentos revisados en el Architecture Review v1.0.

## 3. Estado de cada documento

| Documento | Código | Versión | Estado |
|---|---|---|---|
| `MAIEK_AI_FRAMEWORK.md` | Framework | — (Legacy) | Approved |
| `MAIEK_AI_PRODUCT_ARCHITECTURE.md` | MPA | 1.0 | Approved |
| `MAIEK_AI_DESIGN_SYSTEM.md` | MDL | 1.1 | Approved |
| `MAIEK_AI_COMPONENT_SYSTEM.md` | CDS | 1.0 | Approved |
| `MAIEK_AI_PRODUCT_EXPERIENCE.md` | MPX | 1.0 (completo) | Approved — Partes I, II y III |
| `MAIEK_AI_SYSTEM_ARCHITECTURE.md` | MSA | 1.0 | Approved |
| `DOCUMENTATION_INDEX.md` | — | 1.0 | Approved |

*(`MAIEK_AI_PLATFORM_ARCHITECTURE.md` queda fuera de este corpus — Superseded por MSA, fuera del alcance de esta Baseline por no ser ya documentación vigente.)*

## 4. Riesgos aceptados

No bloquean la expansión técnica — cada uno tiene dueño futuro asignado:

1. **Terminología de confianza sin fuente única (CDS "Alta/Media/Baja" vs. MPX "Requiere validación")** — dueño: CDS v1.1, antes de construir Frontend Architecture.
2. **Asimetría de formato entre MDL/CDS y el resto del corpus** (sin encabezados formales de Dependencias/Consumido por) — dueño: pasada de formato opcional, baja prioridad.
3. **CDS no declara su propio "Consumido por"** (MPX y MSA sí lo citan como dependencia, la relación no es recíproca en el archivo fuente) — mismo dueño que el riesgo 2.
4. **Peso del proceso de gobernanza de 7 pasos** aplicado sin calibrar podría volverse cuello de botella en 8+ documentos derivados — dueño: calibrar rigor caso a caso al construir cada uno.

## 5. Vacíos aceptados

Corresponden a las arquitecturas derivadas, no a esta fase de definición:

1. **Testing Strategy sin padre arquitectónico declarado** — dueño: agregarlo como heredero de MSA Cap. 10, mismo tratamiento que QA Strategy.
2. **Cumplimiento normativo / retención de datos de clientes** — dueño: Security Architecture.
3. **Backup / disaster recovery** — dueño: Data Architecture / DevOps Architecture.
4. **Mecanismo concreto de autenticación al panel** — dueño: Security Architecture.
5. **Estrategia de versionado de API** — dueño: API Architecture.
6. **Gobernanza de costo del AI Engine en producción** — dueño: DevOps Architecture / Operations Architecture.

## 6. Decisión oficial

# Ready for Technical Expansion

El corpus documental de Maiek AI es consistente, trazable de extremo a extremo (Framework → MSA), sin duplicación real de responsabilidades y sin fuente de verdad en disputa que bloquee construir sobre él. Los riesgos y vacíos de las secciones 4-5 quedan formalmente aceptados, con dueño asignado, no pendientes de resolución previa.

## 7. Próxima fase de construcción

Orden de construcción de las arquitecturas técnicas derivadas del MSA:

**Data → Backend → AI → API → Frontend → Security → DevOps → Operations**

Consistente con el orden de dependencia ya declarado en MSA Capítulo 17 (Data Architecture como único ítem de prioridad 1º; Backend y AI en 2º; API, Frontend y Security en 3º; DevOps y Operations en 4º).

---

*Con la aprobación y commit de este documento, la fase de definición de Maiek AI queda oficialmente cerrada. Comienza Data Architecture como primer documento derivado del MSA.*
