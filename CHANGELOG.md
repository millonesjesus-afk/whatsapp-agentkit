# Changelog

Historial de cambios de producto de cara afuera — distinto del control de versiones interno de
cada documento (ver `DOCUMENTATION_INDEX.md` para eso). Formato inspirado en
[Keep a Changelog](https://keepachangelog.com/), adaptado al ritmo real del proyecto.

## [Unreleased]

Trabajo local sobre `deploy-main`, todavía no desplegado — Track Product, guiado por
`MAIEK_AI_PRODUCT_PATTERNS.md` v1.0.

### Added — Sprint 1 (Inicio, Cap. 3)
- Pantalla de Inicio, única para los 3 roles (Administrador/Supervisor/Asesor): Zona de acción
  determinística (sin depender del Copiloto IA) + Zona de indicadores. Aterrizaje por defecto al
  entrar al panel sin filtros; con cualquier filtro explícito, la Bandeja de conversaciones sigue
  funcionando exactamente igual que antes.

### Added — Sprint 2 (Sidebar + CRM/Pipeline, Cap. 1 y 6)
- Sidebar de navegación (implementación incremental del Shell de Navegación) con los destinos de
  `MAIEK_AI_PRODUCT_ARCHITECTURE.md` §10, filtrados por rol.
- Nuevo destino **CRM / Pipeline** (`/dashboard/pipeline`): tabla de leads con búsqueda, filtro por
  resultado/asesor, orden por columna y paginación, todo persistido en la URL; alcance por rol
  (un Asesor ve solo sus propios leads).
- **Conversation Timeline** en la vista de detalle de un lead: historial de eventos de negocio
  (cambio de resultado, asignación, venta registrada), con autor y momento de cada uno.
- **Conflicto de edición**: si dos personas editan el mismo lead casi al mismo tiempo, la segunda
  escritura ya no sobrescribe en silencio — se avisa explícitamente quién cambió qué y cuándo antes
  de dejar decidir cómo seguir.

### Added — Sprint 3 (Copiloto IA, Cap. 5 — primera implementación)
- Panel "Copiloto IA" en la vista de detalle de un lead, colapsado por defecto. Primera capacidad
  activa: **Resumen de la conversación bajo demanda** — condensa el historial en 3-5 líneas,
  independiente del protocolo de confianza (sin tools, sin acciones, sin persistencia propia).
  Marca el resumen como desactualizado si llega un mensaje nuevo mientras está en pantalla.
- Estructura pensada para crecer: las próximas capacidades (Sugerencias IA, Indicador de confianza,
  Acciones IA) se incorporan sobre el mismo contenedor, sin rediseñar la interfaz — deliberadamente
  no activadas todavía porque dependen de dos decisiones no tomadas (persistencia de decisiones de
  IA, y una definición de seguridad sobre qué puede ejecutar la IA por sí misma).

### Changed
- La barra superior (Top Navigation) deja de tener enlaces de navegación de producto (Métricas,
  Campañas, Catálogos, etc.) — se movieron al nuevo Sidebar; la barra superior queda solo con
  identidad y accesos de cuenta (perfil, disponibilidad, salir).

### Added — Preparación del Sprint de Validación del Copiloto
- Logging estructurado (`resumen_ia`) para el Resumen IA: latencia, cantidad de mensajes de
  entrada, preview del resultado, manejo explícito de historial vacío — sin esto no había forma de
  medir calidad ni latencia con evidencia real.
- `MAIEK_AI_CONVERSATIONAL_VALIDATION_PLAN.md` evoluciona a v1.1: nueva sección 6 con criterios
  objetivos para validar el Resumen IA (fidelidad, cobertura, claridad/utilidad, latencia, manejo
  de conversaciones vacías o con poco contexto) y sus propios criterios de avance hacia
  Sugerencias/Indicador de confianza/Acciones IA.

### Known limitations (deuda técnica aceptada)
- Tras un conflicto de edición, el reintento es manual — el sistema no pre-carga el intento
  anterior del usuario, salvo en el formulario de resultado/asignación, donde alcanza con volver a
  guardar (la versión ya quedó actualizada).
- Un conflicto en el formulario de Cierre de venta descarta el carrito armado; hay que rearmarlo.
- El indicador de "resumen desactualizado" del Copiloto no fue validado de punta a punta con
  tráfico real de WhatsApp — reutiliza el mismo mecanismo de tiempo real ya probado por el chat, así
  que el riesgo se considera bajo, pero la validación definitiva queda para el Sprint de Validación
  del Copiloto (próximo).

## [0.2.0] - 2026-07-29

Primera versión que implementa decisiones reales del corpus arquitectónico Maiek AI — protocolo de
confianza de IA, migraciones versionadas (Alembic), `request_id`, idempotencia del webhook. Detalle
completo en `RELEASE_NOTES_v0.2.0.md`.
