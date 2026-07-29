# Implementation Review — Fase 1 (Núcleo técnico: Data Architecture Fase 1 + Backend + AI + API)

**Fecha:** 2026-07-29 · **Rango revisado:** commits `9029542`..`b350ad1` en `deploy-main` (22 commits)
· **Estado:** implementación completa, validada localmente, **0 commits desplegados** — este documento
cierra la implementación y da paso al Code Freeze acordado; el despliegue real es el paso siguiente,
no parte de este review.

## 0. Alcance de este cierre

Cierra la Fase 1 completa del `MAIEK_AI_IMPLEMENTATION_ROADMAP.md`: Backend, AI y API (núcleo técnico
original) más Data Architecture Fase 1 (baseline de Alembic), ejecutada fuera de secuencia como
capacidad habilitadora — ver `MAIEK_AI_IMPLEMENTATION_ROADMAP.md`, Control de versiones. Secuencia real
de implementación, distinta de la planificada original por la corrección de v1.2 del Execution Plan:
**Backend (parcial) → Data Architecture Fase 1 → AI → Backend (resto) → API.**

No incluye: `negocio_id`/Multi-Tenant, Data Architecture Fase 2/3, la API externa versionada
(`/api/v1/`), `BackgroundTasks`, ni la ejecución del Plan de Validación Conversacional — todos
diferidos por diseño, no por descuido, cada uno con su razón ya documentada en su sub-etapa.

## 1. Archivos modificados (22 archivos de código + 22 commits)

| Módulo | Cambio |
|---|---|
| `agent/services/servicio_inteligencia.py` (nuevo) | Fachada sobre `brain.py`; `resolver_accion_confianza` |
| `agent/services/servicio_comercial.py` (nuevo) | Fachada sobre `asignacion.py` + líneas de venta extraídas de `dashboard.py` |
| `agent/services/servicio_identidad.py` (nuevo) | `usuario_actual`, `NoAutenticado`, `requiere_rol(*roles)` |
| `agent/services/servicio_canales.py` (nuevo) | Fachada sobre `campanas.py` |
| `agent/services/servicio_conversacion.py` (nuevo) | Fachada sobre mensajes/adjuntos/memoria de `memory.py` |
| `agent/providers/__init__.py` | Retirado el branch roto de `twilio` |
| `agent/http_utils.py` | Cliente `httpx.AsyncClient` compartido (antes uno nuevo por llamada) |
| `agent/brain.py` | Protocolo de confianza (salida forzada, delimitación estructural, prompt caching, registro de inferencias) — activo solo en `modo="pruebas"` |
| `agent/migraciones.py` (nuevo) | `aplicar_migraciones()` + detección de baseline no registrado |
| `agent/api_contrato.py` (nuevo) | `request_id`, modelo uniforme de errores |
| `agent/memory.py` | `revision_prioritaria`, `MensajeProcesado`/idempotencia general, `Base.metadata.create_all()` reemplazado por Alembic |
| `agent/main.py` | Todos los servicios conectados; protocolo de confianza consumido; idempotencia en el webhook; contrato interno registrado |
| `agent/dashboard.py` | 13 checks de rol → `requiere_rol`; servicios conectados; badge de revisión prioritaria |
| `alembic.ini`, `migrations/` (nuevo) | Scaffold async + 3 migraciones (baseline, `revision_prioritaria`, `mensajes_procesados`) |
| `requirements.txt` | + `alembic` |

Más 3 documentos de gobernanza (`MAIEK_AI_OPERATIONS_RUNBOOK.md`, `MAIEK_AI_CONVERSATIONAL_VALIDATION_PLAN.md`,
`IMPLEMENTATION_REVIEW_PRE_DEPLOYMENT_FASE_1.md`) y las correcciones ya registradas al Execution Plan
(v1.2) y al Roadmap.

## 2. Origen arquitectónico de cada cambio

| Cambio | Documento de origen |
|---|---|
| 5 servicios de dominio | `MAIEK_AI_BACKEND_ARCHITECTURE.md` §1, Decisión "Extracción de `dashboard.py`" |
| `requiere_rol` centralizado | `MAIEK_AI_BACKEND_ARCHITECTURE.md` §3, Decisión "Autorización centralizada" |
| Cliente HTTP compartido | `MAIEK_AI_BACKEND_ARCHITECTURE.md` §3, Decisión "Cliente HTTP compartido" |
| Retiro de `twilio` | `MAIEK_AI_BACKEND_ARCHITECTURE.md` §3, Decisión "Retiro del proveedor `twilio` roto" |
| Baseline de Alembic | `MAIEK_AI_DATA_ARCHITECTURE.md` §6, Fase 1 |
| Protocolo de confianza, delimitación, caching, registro de inferencias | `MAIEK_AI_AI_ARCHITECTURE.md` §1, §3, §6, §7, §9 |
| Regla de negocio Alta/Requiere validación/Baja | Definida explícitamente por el usuario — brecha que `AI Architecture` §6 dejaba abierta a propósito |
| `request_id`, modelo uniforme de errores | `MAIEK_AI_API_ARCHITECTURE.md` §3, Decisión "Modelo uniforme de errores" |
| Idempotencia general | `MAIEK_AI_API_ARCHITECTURE.md` §4, ASC ya fijado; desbloqueada por Data Architecture Fase 1 |

Ningún cambio de esta fase carece de un origen arquitectónico trazable.

## 3. Architecture Success Criteria cumplidos

**Backend Architecture:**
- ✅ Toda autorización pasa por `requiere_rol` — verificado, cero checks de rol duplicados en gates de endpoint.
- ✅ Cliente HTTP compartido con timeout explícito (Meta/Resend/Anthropic).
- ✅ Factory de proveedores sin branches a módulos inexistentes.
- ⚠️ "Ningún router contiene reglas de negocio" — parcial: los 5 servicios de dominio están extraídos; `dashboard.py` sigue sin dividirse en routers por bounded context (ya señalado en el Pre-Deployment Review, sección 2).

**AI Architecture:**
- ✅ Toda respuesta expone confianza estructurada, emitida únicamente por el AI Engine — verificado con llamadas reales.
- ✅ Máximo 2 llamadas de IA por mensaje — sin cambios, se mantiene.
- ✅ Delimitación estructural del turno `user` — verificado.
- ⚠️ Explainability First — verificable vía log estructurado (cumplido); verificación completa vía `SugerenciaIA` persistida sigue condicionada a Data Architecture Fase 2 (no iniciada).

**Data Architecture (Fase 1):**
- ✅ Alembic adoptado, baseline generado y verificado equivalente a `create_all()`.
- ✅ `create_all()` retirado como mecanismo de cambio en producción.

**API Architecture:**
- ✅ AI Architecture consume exclusivamente vía el contrato interno, nunca como consumidor externo.
- ✅ Todo error del contrato interno responde `{código, mensaje, detalle, request_id}`, y ese `request_id` aparece en los logs — verificado con un error real y su log correlacionado.
- ✅ El webhook no reprocesa un mensaje ya visto usando `mensaje_id` — verificado enviando el mismo payload dos veces.

## 4. Validaciones ejecutadas (resumen — el detalle está en cada commit)

- Sintaxis e import completo en los 22 commits, sin excepción.
- Equivalencia funcional vía mocks para cada método de cada fachada.
- **3 llamadas reales a la API de Anthropic** confirmando salida estructurada forzada, `modo="producción"` sin cambios, y prompt caching activo (medido, no asumido).
- Migración baseline verificada equivalente a `create_all()`; migración incremental verificada contra una tabla con filas existentes (simulación de producción); escenario de producción sin `stamp` confirmado que **falla como se predijo**, y que `stamp`+`upgrade` es no-op correcto después.
- **Flujo autenticado real de punta a punta**: login real, asesor responde por el panel, mensaje persistido y confirmado legible.
- **Idempotencia general validada con el mismo payload de webhook enviado dos veces** — segundo envío no duplicó el mensaje.
- `request_id` confirmado presente y correlacionado con logs reales, en respuestas de éxito y de error; propagación del `request_id` del consumidor confirmada.
- Sin regresiones confirmadas explícitamente en: `/docs` restringido, `NoAutenticado` redirige, render HTML normal del login.

## 5. Riesgos y deuda técnica conocida (consolidado — ninguno nuevo respecto al Pre-Deployment Review)

1. **Crítico, acción pendiente del usuario**: `alembic stamp head` contra producción antes del deploy (`MAIEK_AI_OPERATIONS_RUNBOOK.md`).
2. Separación de capas Presentación/Aplicación en Backend — parcial, `dashboard.py` sigue siendo un router grande.
3. Clasificación de las 6 fuentes de conocimiento de AI Architecture §2 — no implementada como taxonomía explícita en código.
4. `BackgroundTasks` y señal de error explícita de `extraer_datos_lead` — pendientes, no bloqueantes.
5. Códigos de error semánticos (`LEAD_NO_ENCONTRADO`, etc.) — hoy derivados del status HTTP por defecto; agregarlos es trabajo incremental futuro, no bloqueante.
6. Protocolo de confianza sin validar con tráfico real todavía — el Plan de Validación Conversacional ya define cómo se hace, pendiente de ejecución antes de promover cualquier canal.
7. Gate de CI bloqueante en GitHub — pendiente de confirmar que sigue activo (heredado de Fase 0).

## 6. Code Freeze

**A partir de este documento, Fase 1 entra en Code Freeze**, según lo acordado: no se agregan
funcionalidades ni refactorizaciones nuevas — solo correcciones necesarias para resolver hallazgos
reales de validación o del despliegue controlado que sigue.

**Próximo paso, en orden:**
1. Ejecutar el procedimiento operativo ya aprobado (`MAIEK_AI_OPERATIONS_RUNBOOK.md`, Escenario 1 —
   `alembic stamp head` contra producción).
2. Primer despliegue controlado del conjunto completo de Fase 1.
3. Validar el comportamiento del sistema en producción (arranque limpio, health check, mensaje real de
   WhatsApp) — mismo criterio de cierre ya usado en Fase 0.
4. Solo después de esa validación, se inicia la siguiente fase del Roadmap.

---

*Fin del documento. Cierra la implementación de la Fase 1 — Code Freeze activo a partir de esta
aprobación.*
