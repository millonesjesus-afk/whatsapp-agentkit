# Implementation Review — Fase 0 (Estabilización)

**Fecha:** 2026-07-28 · **Rango revisado:** commits `c063091`..`b64ac9d` en `deploy-main` · **Estado:** cerrada, lista para push/merge

## 1. Archivos modificados (17)

| Archivo | Tipo de cambio |
|---|---|
| `agent/providers/meta.py` | Fail-closed en `verificar_firma()`; llamadas a Meta migradas a `http_utils` |
| `agent/http_utils.py` (nuevo) | Timeout + reintentos con backoff, compartido |
| `agent/notificaciones.py` | Llamadas a Resend migradas a `http_utils` |
| `agent/brain.py` | `AsyncAnthropic` con `timeout`/`max_retries` explícitos |
| `agent/main.py` | Fail-fast de env vars críticas; rate limit en `/webhook` |
| `agent/dashboard.py` | Rate limit + bloqueo por intentos en `/login` |
| `agent/rate_limit.py` (nuevo) | `LimitadorTasa` y `BloqueoPorIntentos`, en memoria |
| `.github/workflows/ci.yml` (nuevo) | Gate de CI: deps, sintaxis, import, arranque, smoke test |
| `scripts/backup_postgres.py` (nuevo) | `pg_dump` + subida a almacenamiento S3-compatible |
| `Dockerfile` | + `postgresql-client` (da el binario `pg_dump`) |
| `requirements.txt` | + `boto3` |
| `.env.example` | Documenta variables `S3_*` y `BACKUP_RETENCION_DIAS` |
| `MAIEK_AI_ADR_INDEX.md` (nuevo) | Estructura, numeración, plantilla, flujo, registro |
| `adr/0000-template.md` (nuevo) | Plantilla de ADR |
| `adr/0001-backup-postgres-pg-dump-s3.md` (nuevo) | Decisión de mecanismo de backup |
| `adr/0002-independencia-proveedor-backups.md` (nuevo) | Precisión del motivo principal |
| `DOCUMENTATION_INDEX.md` | Alta del ADR Index en §7 |

## 2. Origen arquitectónico de cada cambio

| Cambio | Documento / ADR de origen |
|---|---|
| Fail-closed del webhook | `MAIEK_AI_SECURITY_ARCHITECTURE.md` — Decisión local (P1) |
| Timeout/reintentos en llamadas externas | `MAIEK_AI_DEVOPS_ARCHITECTURE.md` — Decisión local (P1) |
| Fail-fast de variables críticas | `MAIEK_AI_DEVOPS_ARCHITECTURE.md` — Decisión local |
| Rate limiting `/login` + `/webhook` | `MAIEK_AI_SECURITY_ARCHITECTURE.md` — Decisión local (P1) |
| Bloqueo por intentos fallidos de login | `MAIEK_AI_SECURITY_ARCHITECTURE.md` — Decisión local (P1) |
| Gate de CI | `MAIEK_AI_DEVOPS_ARCHITECTURE.md` — Decisión local (P1) |
| Backup pg_dump + S3-compatible | ADR-0001, ADR-0002 (implementan la Decisión local de DevOps Architecture, mecanismo que la propia Decisión dejó pendiente de confirmar) |
| ADR Index | `MAIEK_AI_IMPLEMENTATION_ROADMAP.md` — sección 10 (primer documento derivado a construir) |

Ningún cambio de esta fase carece de un origen arquitectónico trazable — no se implementó nada por fuera del corpus.

## 3. Architecture Success Criteria cumplidos

**Security Architecture:**
- ✅ #1 (fail-closed del webhook) — cumplido, verificado.
- ⚠️ #2 (rate limit verificable) — cumplido en `/webhook` (429 literal); en `/login` se implementó como redirect con mensaje explicativo en vez de un 429 directo, para mantener el patrón de error ya usado en el resto del flujo de login del panel — funcionalmente equivalente, verificado con tests, pero vale la pena dejarlo explícito.
- ✅ #3 (bloqueo tras N fallos) — cumplido, verificado.
- ❌ #4, #5, #6 — fuera de alcance de Fase 0 (CSRF y alta de usuarios son Fase 4; `RegistroAuditoria` depende de Data Architecture Fase 3).

**DevOps Architecture:**
- ⚠️ #1 (CI bloqueante) — el pipeline existe y es capaz de bloquear, pero no bloquea todavía en la práctica: falta activar "Require status checks" en GitHub (pendiente externo, sección 4).
- ⏸️ #2 (backup restaurable y verificado) — mecanismo construido, no verificado contra infraestructura real todavía (pendiente externo, sección 4).
- ✅ #3 (timeout/reintentos) — cumplido, verificado.
- ✅ #4 (fail-fast) — cumplido, verificado.
- ❌ #5, #6 — fuera de alcance de Fase 0 (`request_id`/logging estructurado y separación de siembra son Fase 1/4).

## 4. Pendiente por infraestructura externa

- **Railway**: crear el bucket S3-compatible, cargar sus credenciales como variables, crear el segundo servicio con Cron Schedule apuntando a `scripts/backup_postgres.py`, y verificar al menos una restauración de prueba.
- **GitHub**: activar "Require status checks to pass" en la protección de la rama `deploy-main` para que el CI bloquee mergues de verdad, no solo reporte.
- Ninguno de estos dos pendientes depende de más código — son configuración de plataforma, fuera de este repositorio.

## 5. Desviaciones respecto al corpus arquitectónico Approved

**Ninguna.** Cada cambio se trazó a una Decisión local ya `Objetivo` o a un ADR que implementa —sin contradecir— una Decisión existente (ver sección 2). No se redefinió ningún Architectural Constraint, ningún Decisión ya `Activa`, ni ningún documento Approved.

## 6. Deuda técnica deliberada, identificada

| Ítem | Por qué es aceptable ahora | Criterio de revisión |
|---|---|---|
| `rate_limit.py` en memoria de proceso, no en almacén compartido | Despliegue de una sola instancia hoy (confirmado en DevOps CSA) | Si el despliegue pasa a múltiples instancias |
| CI gate sin suite de pruebas real, solo smoke test | El propio Roadmap ya planificó Testing Strategy para más adelante en esta misma fase/Fase 1 | Cuando se construya Testing Strategy |
| `postgresql-client` sin pin de versión exacta en el Dockerfile | Sin evidencia hoy de incompatibilidad con la versión de Postgres de Railway | Si una restauración de prueba falla por incompatibilidad de versión |

Ninguna deuda de esta lista es oculta — las tres ya estaban anticipadas en el corpus (CSA-DevOps, Implementation Roadmap) o quedan documentadas acá por primera vez con su propio criterio de revisión.

## 7. Recomendación

**Lista para push y merge.** No hay desviaciones arquitectónicas, la deuda técnica introducida está identificada y tiene criterio de revisión, y los Architecture Success Criteria de alcance de Fase 0 están cumplidos o correctamente marcados como pendientes de configuración externa (no de código). Los dos pendientes de infraestructura (backup verificado, branch protection) no bloquean el push — son follow-ups operativos que no requieren código adicional.

---

*Cierra oficialmente la Fase 0 del `MAIEK_AI_IMPLEMENTATION_ROADMAP.md`. Siguiente: Fase 1 — Núcleo técnico (Backend/AI/API).*
