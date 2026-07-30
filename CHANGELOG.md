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

### Changed
- La barra superior (Top Navigation) deja de tener enlaces de navegación de producto (Métricas,
  Campañas, Catálogos, etc.) — se movieron al nuevo Sidebar; la barra superior queda solo con
  identidad y accesos de cuenta (perfil, disponibilidad, salir).

### Known limitations (deuda técnica aceptada)
- Tras un conflicto de edición, el reintento es manual — el sistema no pre-carga el intento
  anterior del usuario, salvo en el formulario de resultado/asignación, donde alcanza con volver a
  guardar (la versión ya quedó actualizada).
- Un conflicto en el formulario de Cierre de venta descarta el carrito armado; hay que rearmarlo.

## [0.2.0] - 2026-07-29

Primera versión que implementa decisiones reales del corpus arquitectónico Maiek AI — protocolo de
confianza de IA, migraciones versionadas (Alembic), `request_id`, idempotencia del webhook. Detalle
completo en `RELEASE_NOTES_v0.2.0.md`.
