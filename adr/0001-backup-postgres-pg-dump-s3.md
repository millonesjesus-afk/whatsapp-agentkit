# ADR-0001: Backups de Postgres vía pg_dump + almacenamiento S3-compatible, no vía Railway nativo

| | |
|---|---|
| Estado | Aceptada |
| Fecha | 2026-07-28 |
| Documento de arquitectura afectado | `MAIEK_AI_DEVOPS_ARCHITECTURE.md` — Decisión local "Backups automatizados de Postgres, verificados independientemente del plan de Railway"; Architectural Constraint "Si el plan de Railway contratado incluye backups automáticos de Postgres es un hecho externo no confirmado" |
| Fase del roadmap | Fase 0 — Estabilización |
| Relación | Complementado por [ADR-0002](0002-independencia-proveedor-backups.md) — precisa que el motivo principal es independencia de proveedor, no solo la ausencia actual de la función nativa |

## Contexto

DevOps Architecture ya dejaba esto como Constraint explícitamente no verificado: "si el plan de Railway contratado incluye backups automáticos de Postgres es un hecho externo no confirmado desde este repositorio." El usuario confirmó el estado real navegando la pestaña "Backups" del servicio Postgres en Railway (captura de pantalla, 2026-07-28): *"Backups and point-in-time recovery (PITR) are only available for customers on the Pro plan"* y *"No Backups — This service's volume does not have any backups."* — el plan actual no incluye ningún mecanismo nativo de backup, ni Volume Backups ni PITR.

## Decisión

Se implementa un mecanismo propio: `scripts/backup_postgres.py` ejecuta `pg_dump` contra `DATABASE_URL` y sube el dump a almacenamiento S3-compatible (configurable por variables de entorno — `S3_ENDPOINT_URL`, `S3_BUCKET`, credenciales — funciona con AWS S3, Cloudflare R2, Backblaze B2 u otro proveedor S3-compatible sin cambiar código), con purga de backups más antiguos que la retención configurada. Se ejecuta como un Cron Schedule de Railway, en un segundo servicio del mismo proyecto (mismo repo/imagen, comando de arranque distinto), no dentro del proceso web principal.

Esto no contradice la Decisión ya `Objetivo` de DevOps Architecture — la implementa, usando exactamente el mecanismo que esa misma Decisión ya anticipaba como fallback ("verificados independientemente del plan de Railway").

## Consecuencias

- Requiere una cuenta y credenciales de almacenamiento S3-compatible — decisión de proveedor específico y su configuración en Railway quedan fuera de este ADR (no arquitectónicas, operativas).
- Se agrega `boto3` como dependencia nueva (`requirements.txt`) y `postgresql-client` a la imagen Docker (para tener el binario `pg_dump`).
- El backup deja de depender de que Railway cambie de plan — es portable a cualquier otro proveedor de hosting que exponga `DATABASE_URL` de Postgres.
- La Decisión local de DevOps Architecture pasa de `Objetivo` a `Activa` recién cuando el Cron Schedule esté corriendo en Railway y se haya verificado al menos una restauración de prueba (Architecture Success Criterion #2 de DevOps Architecture) — no con solo el código escrito.

## Reconciliación con el corpus

- [ ] Menor / local
- [x] Sustancial — `MAIEK_AI_DEVOPS_ARCHITECTURE.md` se actualiza (nueva fila en su Control de versiones, citando ADR-0001) cuando el mecanismo esté corriendo en Railway y verificado — no todavía, mientras falta la configuración manual en el dashboard.

Si es sustancial: fecha en que se actualizó el documento de origen — _pendiente, una vez verificado en Railway_.
