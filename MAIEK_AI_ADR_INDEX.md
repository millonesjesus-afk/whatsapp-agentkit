# Maiek AI — ADR Index

**Versión 1.0 · Estado: Approved**

| | |
|---|---|
| Documento | ADR Index |
| Proyecto | Maiek AI |
| Versión | 1.0 |
| Estado | **Approved** |
| Fecha de creación | 2026-07-28 |
| Autor | Claude, a pedido de Jesús Millones |
| Fecha de aprobación | 2026-07-28 |
| Última actualización | 2026-07-28 |

## Dependencias

`MAIEK_AI_IMPLEMENTATION_ROADMAP.md` — sección 2 (Principios de implementación: "ninguna implementación puede contradecir una arquitectura Approved sin un ADR explícito") y sección 10 (fija que este documento se construye al inicio de la Fase 0, antes de cualquier cambio técnico).

## Consumido por

Toda la Fase de Implementación — cualquier persona (humana o agente de IA) que toque código durante esta fase consulta este índice antes de desviarse de una decisión ya Approved.

## Control de versiones

| Versión | Fecha | Autor | Descripción |
|---|---|---|---|
| 1.0 | 2026-07-28 | Claude | Primera versión — estructura, numeración, plantilla y flujo mínimos para registrar decisiones de implementación que se desvían del corpus arquitectónico Approved. Sin ADRs registrados todavía. |

## Alcance

Documento mínimo, no gobernado por el ADS (no es arquitectura) — define únicamente cómo se registra una desviación real entre el corpus arquitectónico Approved y lo que la implementación termina necesitando. No es un mecanismo para tomar decisiones de arquitectura nuevas desde cero: si algo no tiene ninguna decisión previa de la que partir, es una brecha de arquitectura (vuelve al corpus correspondiente), no un ADR.

---

## Estructura

Cada ADR es un archivo propio en `adr/`, numerado secuencialmente: `adr/0001-<slug-corto>.md`, `adr/0002-<slug-corto>.md`, etc. El número `0000` (`adr/0000-template.md`) está reservado para la plantilla — nunca es un ADR real.

Este archivo (`MAIEK_AI_ADR_INDEX.md`) es el índice: una tabla con todos los ADRs registrados, su estado y a qué documento de arquitectura afectan. El detalle completo de cada decisión vive en su propio archivo, no acá — igual que `DOCUMENTATION_INDEX.md` cataloga sin repetir el contenido de cada documento.

## Numeración

Secuencial, sin huecos, nunca reutilizada — un ADR reemplazado conserva su número; el que lo reemplaza recibe uno nuevo y enlaza al anterior. El próximo número a usar es siempre `len(ADRs registrados) + 1`, consultando la tabla de abajo.

## Plantilla

`adr/0000-template.md` — copiar como punto de partida para cualquier ADR nuevo. Campos: Estado, Fecha, Documento de arquitectura afectado, Fase del roadmap, Contexto, Decisión, Consecuencias, Reconciliación con el corpus (menor/local vs. sustancial — ver Flujo).

## Flujo

1. **Durante la implementación**, si algo hace evidente que una decisión ya Approved no se puede seguir tal cual está escrita — se crea un ADR nuevo: copiar la plantilla, numerar secuencial, completar Contexto/Decisión/Consecuencias con evidencia real (Evidence over Opinion, mismo principio que rige todo el corpus).
2. **El ADR se referencia en el commit** que introduce el cambio técnico correspondiente.
3. **Este índice se actualiza** con una fila nueva en la tabla de abajo, en el mismo commit.
4. **Se decide la reconciliación**: si la desviación es menor o local, el ADR es el único registro necesario. Si es sustancial — cambia una Decisión local, un Architectural Constraint, o algo que otro documento ya cita como dependencia — el documento de arquitectura de origen se actualiza también (nueva fila en su propio Control de versiones, citando el número de ADR), para que el corpus nunca quede desalineado con la realidad implementada en silencio.
5. **Estados de un ADR**: `Propuesta` (en discusión, todavía no rige) → `Aceptada` (rige) → `Reemplazada` (por un ADR posterior, que se referencia). Un ADR `Aceptada` nunca se edita retroactivamente — si algo cambia, se crea un ADR nuevo que la reemplaza y ambos quedan enlazados. Mismo principio de "nunca edición silenciosa" ya vigente en todo el corpus desde el MDL v1.1.

## Registro de ADRs

| # | Título | Estado | Fecha | Documento de arquitectura afectado | Fase |
|---|---|---|---|---|---|
| [0001](adr/0001-backup-postgres-pg-dump-s3.md) | Backups de Postgres vía pg_dump + almacenamiento S3-compatible, no vía Railway nativo | Aceptada | 2026-07-28 | DevOps Architecture | Fase 0 |
| [0002](adr/0002-independencia-proveedor-backups.md) | Independencia de proveedor como motivo principal de la estrategia de backups | Aceptada — complementa a 0001 | 2026-07-28 | DevOps Architecture | Fase 0 |
| [0003](adr/0003-identidad-marca-unica-plataforma.md) | Identidad de marca única de plataforma MAIEK, independiente de `negocio_id` | Propuesta | 2026-09-12 | Frontend Architecture | Fase 3 |
| [0004](adr/0004-secuencia-data-fase2-vs-multitenant.md) | Secuencia real de Data Architecture Fase 2 vs. Fase 3 (Multi-Tenant) | Aceptada | 2026-09-12 | Data Architecture, Implementation Roadmap, Backend Architecture | Fase 2 — Data Architecture Fase 3 (el bloqueante transversal) / Hito H3 |
| [0005](adr/0005-shell-sidebar-alto-completo-y-tira-de-accion-en-inicio.md) | Shell de sidebar de alto completo (Z), Tira de acción en Inicio (A) y Pulso de hoy (C) por fases | Aceptada (Approved, decisión del dueño) | 2026-10-12 | Product Patterns (Cap. 1 §3, Cap. 3, Cap. 9), Component System (Sidebar, Top Navigation, KPI Card) | Evolución de producto del frontend — F0 documentos, F1 Tira, F2 Shell Z, F3-F5 Pulso |

---

## Cierre

Este documento queda activo desde el inicio de la Fase 0 (Estabilización) del `MAIEK_AI_IMPLEMENTATION_ROADMAP.md`. No requiere una nueva versión por cada ADR agregado — la tabla de arriba se actualiza en el mismo commit que crea el ADR, sin que eso constituya un cambio de fondo a este documento (no dispara una nueva fila en el Control de versiones salvo que cambie el flujo, la numeración o la plantilla en sí).

---

*Fin del documento.*
