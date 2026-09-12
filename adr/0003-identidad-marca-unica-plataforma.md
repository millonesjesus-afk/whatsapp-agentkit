# ADR-0003: Identidad de marca única de plataforma MAIEK, independiente de negocio_id

| | |
|---|---|
| Estado | Propuesta |
| Fecha | 2026-09-12 |
| Documento de arquitectura afectado | `MAIEK_AI_FRONTEND_ARCHITECTURE.md` — Decisión local "Identidad de marca resoluble por negocio, no hardcodeada" (tabla Decisiones locales) y su definición en §11 |
| Fase del roadmap | Fase 3 — Extensión Multi-Tenant a los demás dominios (retira el ítem de Frontend de su alcance) |

## Contexto

`MAIEK_AI_FRONTEND_ARCHITECTURE.md` §11 declara: "cuando `negocio_id` exista (Data
Architecture Fase 3), la identidad de marca (nombre, colores) debe poder resolverse
por negocio, no quedar fija en el código como ocurre hoy." Esta Decisión local hereda
de un diagnóstico de `MAIEK_AI_FRONTEND_CURRENT_STATE_ASSESSMENT.md` §11 (identidad
hardcodeada a "Gaso+", incluso las variables de color incorporan el nombre del
negocio).

Esa Decisión asumía implícitamente un supuesto de producto: que Maiek operaría como
plataforma white-label, con cada tenant reemplazando el branding visual de la
plataforma por el suyo propio. El usuario confirmó explícitamente en esta sesión
(2026-09-12) que ese supuesto no representa la decisión de producto vigente: Maiek AI
mantiene una identidad de plataforma propia, independiente de qué tenant la use.
Cálidda es un cliente/tenant de Maiek, no una marca que sustituye a Maiek dentro de la
plataforma.

Auditoría de código realizada en esta sesión confirma que, hasta hoy, ningún elemento
visual (logo, wordmark, colores, favicon, título de página) varía por `negocio_id` en
ningún repositorio — el 100% del branding sigue siendo literales hardcodeados ("Maiek
AI" en `maiek-frontend`, "Gaso+ Panel" en el panel legacy). No hay ninguna
implementación de branding-por-tenant que revertir.

## Problema

La Decisión local Approved de Frontend Architecture describe un requisito (identidad
de marca resoluble por negocio) que contradice directamente la decisión de producto
vigente. Sin un ADR, un futuro agente o desarrollador podría leer esa Decisión local
—marcada "Objetivo, dependiente de Data Architecture Fase 3", dependencia ya
sustancialmente satisfecha— y concluir erróneamente que corresponde implementarla.

## Decisión

Maiek AI mantiene una **identidad única de plataforma**, la misma para todos los
tenants:

- Logo/wordmark: Maiek AI, sin variación por tenant.
- Colores principales: los tokens de MDL ya definidos, sin variación por tenant.
- Lenguaje visual y experiencia UX: unificados, sin variación por tenant.
- `negocio_id` **nunca** determina el branding principal del frontend.
- Ningún tenant reemplaza la identidad visual de Maiek — Maiek no es, y no será bajo
  esta decisión, una plataforma white-label.

Esto **no** afecta lo que ya es correctamente tenant-scoped y sigue siéndolo sin
cambio: `Negocio.nombre` (dato textual del negocio, no branding de la plataforma),
`IdentidadAgente`/Gabi (nombre/tono/prompt del agente, configurable por negocio),
productos, campañas, canales, permisos, y el resto del aislamiento Multi-Tenant por
`negocio_id` ya construido (Gates 5.2-5.6).

## Consecuencias

- La Decisión local "Identidad de marca resoluble por negocio, no hardcodeada" de
  `MAIEK_AI_FRONTEND_ARCHITECTURE.md` queda **Superseded** por este ADR — se conserva
  en el documento por trazabilidad histórica, marcada explícitamente como
  reemplazada, nunca borrada.
- `MAIEK_AI_IMPLEMENTATION_ROADMAP.md` deja de listar "identidad de marca resoluble
  por negocio (Frontend)" como un entregable pendiente de Fase 3 (§4) ni como fila
  pendiente de la Matriz de trazabilidad (§8) — se marca como retirada, citando este
  ADR.
- Ninguna futura personalización visual por tenant puede reactivar esta Decisión
  retroactivamente — requeriría una decisión de producto nueva y su propio ADR.
- Cero impacto en código: no existía ninguna implementación de branding-por-tenant
  que revertir.
- El aislamiento Multi-Tenant de datos/configuración (`negocio_id`) permanece
  completamente intacto — esta decisión opera en una capa distinta (identidad visual
  de plataforma, no aislamiento de datos).

## Reconciliación con el corpus

- [ ] Menor / local
- [x] Sustancial — cambia una Decisión local de un documento Approved
  (`MAIEK_AI_FRONTEND_ARCHITECTURE.md`) y algo que otro documento
  (`MAIEK_AI_IMPLEMENTATION_ROADMAP.md`, §4 y §8) ya cita como dependencia. Ambos
  documentos se actualizan en el mismo cambio, citando este ADR.

Si es sustancial: fecha en que se actualizó el documento de origen — 2026-09-12 (mismo
cambio que crea este ADR).
