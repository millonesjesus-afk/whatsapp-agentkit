# ADR-0002: Independencia de proveedor como motivo principal de la estrategia de backups

| | |
|---|---|
| Estado | Aceptada |
| Fecha | 2026-07-28 |
| Documento de arquitectura afectado | `MAIEK_AI_DEVOPS_ARCHITECTURE.md` — misma Decisión local que ADR-0001 |
| Fase del roadmap | Fase 0 — Estabilización |
| Relación | Complementa a [ADR-0001](0001-backup-postgres-pg-dump-s3.md) — no lo reemplaza; precisa su motivo principal |

## Contexto

ADR-0001 documentó que el plan de Railway contratado no ofrece backups nativos ni PITR, y que por eso se implementó `pg_dump` + almacenamiento S3-compatible. El usuario precisó explícitamente que el motivo **principal** de esa elección no es solo la ausencia actual de la función en el plan contratado — es una decisión deliberada de **independencia de proveedor durante esta etapa del proyecto**, y que no se migrará a Railway Pro únicamente para obtener backups nativos.

## Decisión

Se reafirma el mecanismo ya implementado en `scripts/backup_postgres.py`, sin cambios de código — `pg_dump` + almacenamiento S3-compatible con destino configurable por variables de entorno (`S3_ENDPOINT_URL`, `S3_BUCKET`, credenciales), de forma que funcione con AWS S3, Cloudflare R2, Backblaze B2 o cualquier proveedor equivalente sin acoplarse a Railway. Se documenta explícitamente que el motivo principal es la **independencia de proveedor en esta etapa del proyecto** — la ausencia actual de la función nativa en el plan contratado es la evidencia que lo hizo evidente (ADR-0001), no la única razón para mantenerlo.

## Consecuencias

Ninguna consecuencia técnica nueva — el mecanismo ya estaba implementado exactamente así. Se fija un criterio de revisión explícito, distinto y más específico que el de ADR-0001: **si en el futuro el proyecto migra a Railway Pro, se reevalúa en ese momento** si el mecanismo propio se reemplaza por el nativo, se complementa con él (ej. usar ambos como capas redundantes), o se mantiene igual — decisión a tomar cuando ocurra, no una consecuencia automática de migrar de plan.

## Reconciliación con el corpus

- [x] Menor / local — no agrega nada que `MAIEK_AI_DEVOPS_ARCHITECTURE.md` no supiera ya vía ADR-0001; la actualización de ese documento (cuando el mecanismo esté verificado corriendo en Railway) cita ambos ADRs.
- [ ] Sustancial

Si es sustancial: fecha en que se actualizó el documento de origen — no aplica.
