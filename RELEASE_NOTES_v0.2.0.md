# Release Notes — v0.2.0 (Fase 1: Núcleo técnico)

**Fecha:** 2026-07-29 · **Estado:** Code Freeze — lista para el primer despliegue controlado
· **Rango:** commits `9029542`..`896447c` en `deploy-main` (24 commits) sobre el cierre de Fase 0

## Resumen ejecutivo

Esta versión cierra la Fase 1 del `MAIEK_AI_IMPLEMENTATION_ROADMAP.md`: el núcleo técnico de Maiek AI
sobre Gaso+. Refactoriza Backend en servicios de dominio explícitos, introduce el protocolo de
confianza de la IA (activado de forma gradual, sin afectar todavía el comportamiento en producción),
adopta migraciones de base de datos versionadas, y formaliza el contrato interno de la plataforma.
Es la primera versión que implementa decisiones reales del corpus arquitectónico Maiek AI aprobado —
Fase 0 fue estabilización de lo ya existente, sin cambios de arquitectura.

## Principales funcionalidades incorporadas

- **Protocolo de confianza de IA** — Gabi ahora puede emitir, junto con cada respuesta, un nivel de
  confianza (`Alta` / `Requiere validación` / `Baja`) y la razón de esa evaluación. Según el nivel:
  responde normal (`Alta`), responde y marca la conversación para revisión prioritaria de un asesor
  (`Requiere validación`), o escala automáticamente a un asesor humano (`Baja`). **Activado solo en
  canales `modo="pruebas"` — el comportamiento en producción no cambia con esta versión.**
- **Marcador de "revisión prioritaria"** en el panel — badge visible en la lista de conversaciones
  cuando la IA pide revisión humana; se limpia automáticamente al abrir el lead.
- **`request_id` en cada solicitud** — todo request al servidor recibe un identificador único
  (header `X-Request-Id`, propagado si el cliente ya trae uno), que aparece también en los logs y en
  cualquier respuesta de error — permite correlacionar un problema reportado con lo que realmente pasó.
- **El webhook ya no reprocesa mensajes duplicados** — si Meta reentrega el mismo mensaje (reintento de
  entrega), el sistema lo detecta y lo ignora en vez de generar una respuesta duplicada.

## Cambios internos relevantes

- Backend dividido en 5 servicios de dominio (`ServicioInteligencia`, `ServicioComercial`,
  `ServicioIdentidad`, `ServicioCanales`, `ServicioConversacion`) — antes, la lógica vivía dispersa e
  importada directamente entre `main.py`/`dashboard.py`/módulos sueltos.
- Autorización centralizada (`requiere_rol`) — reemplaza los checks de rol duplicados inline que había
  en cada ruta administrativa.
- Cliente HTTP compartido para Meta/Resend, con timeout explícito (antes se creaba uno nuevo por
  llamada).
- Retirado el branch roto del proveedor `twilio` (nunca se implementó, causaba una falla de arranque
  real si alguien lo seleccionaba); `/docs` y `/openapi.json` restringidos.
- Modelo uniforme de errores internos: `{código, mensaje, detalle, request_id}`.

## Migraciones incluidas

Se adoptó Alembic — a partir de esta versión, los cambios de esquema quedan versionados; `Base.
metadata.create_all()` deja de usarse en producción. Tres migraciones, en orden:

1. **`8bf43ecd3785`** (baseline) — replica el esquema actual exactamente, sin ningún cambio de negocio.
2. **`124cb805569e`** — agrega `leads.revision_prioritaria` (booleano, `server_default=false`).
3. **`925ec2d81736`** — agrega la tabla `mensajes_procesados` (idempotencia general del webhook).

**Acción operativa obligatoria antes de esta versión**: `alembic stamp head` contra la Postgres de
producción (ver `DEPLOYMENT_CHECKLIST_v0.2.0.md` y `MAIEK_AI_OPERATIONS_RUNBOOK.md`, Escenario 1) — la
base ya tiene el esquema baseline con datos reales, y necesita marcarse como tal antes de que el
código nuevo intente aplicar migraciones.

## Riesgos conocidos

- El camino de `modo="producción"` ahora pasa por 5 fachadas de servicio nuevas en vez de imports
  directos — validado exhaustivamente en local (incluyendo un flujo autenticado real de punta a
  punta), pero sin tráfico de producción real todavía sobre este código exacto.
- Sin `alembic stamp head` previo, el próximo arranque en producción falla (detectado y con mensaje
  explícito, no un error genérico — ver `MAIEK_AI_OPERATIONS_RUNBOOK.md`).
- El protocolo de confianza de IA no tiene todavía validación con tráfico conversacional real (el
  `MAIEK_AI_CONVERSATIONAL_VALIDATION_PLAN.md` define cómo se hace esa validación, pendiente de
  ejecutarse) — mitigado porque permanece inactivo en producción en esta versión.

## Limitaciones conocidas

- `dashboard.py` sigue siendo un router grande — la separación de capas Presentación/Aplicación de
  Backend Architecture quedó parcial (Dominio sí se extrajo).
- Las 6 fuentes de conocimiento que AI Architecture clasifica no están etiquetadas como taxonomía
  explícita en el código todavía.
- `BackgroundTasks` para notificaciones/eventos WS no implementado (Backend Architecture lo marca como
  mejora transitoria, no bloqueante).
- La señal de error explícita cuando falla `extraer_datos_lead` sigue sin implementarse (falla en
  silencio, como antes).
- Los errores internos usan un código genérico derivado del status HTTP (`HTTP_404`, etc.) — códigos
  semánticos específicos (`LEAD_NO_ENCONTRADO`, etc.) quedan como mejora incremental futura.
- Persistencia formal de `SugerenciaIA` sigue sin existir — el registro de inferencias de IA vive hoy
  solo como log estructurado, no en una tabla propia (depende de Data Architecture Fase 2).

## Próximos pasos (Fase 2)

Según `MAIEK_AI_IMPLEMENTATION_ROADMAP.md`:

1. **Validación conversacional real** del protocolo de confianza en un canal de pruebas, siguiendo
   `MAIEK_AI_CONVERSATIONAL_VALIDATION_PLAN.md`, antes de promover cualquier canal a producción.
2. **Data Architecture Fase 2** — integridad referencial (FKs), migración de precios a `Numeric`,
   entidades `MemoriaPersistente`/`SugerenciaIA`/`RegistroAuditoria`.
3. **Data Architecture Fase 3** (`negocio_id`, Multi-Tenant) — el bloqueante transversal ya identificado
   en los 8 CSAs del corpus, condicionado a que la Fase 2 esté activa.
4. Trabajo diferido de esta fase, sin fecha fija todavía: `BackgroundTasks`, señal de error de
   `extraer_datos_lead`, códigos de error semánticos, la API externa versionada (`/api/v1/`).

---

*Ver `IMPLEMENTATION_REVIEW_FASE_1.md` para el detalle técnico completo (archivos modificados, origen
arquitectónico de cada cambio, Architecture Success Criteria, validaciones ejecutadas).*
