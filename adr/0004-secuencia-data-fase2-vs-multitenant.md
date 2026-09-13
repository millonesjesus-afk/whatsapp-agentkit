# ADR-0004: Secuencia real de Data Architecture Fase 2 vs. Fase 3 (Multi-Tenant)

| | |
|---|---|
| Estado | Aceptada |
| Fecha | 2026-09-12 |
| Documento de arquitectura afectado | `MAIEK_AI_DATA_ARCHITECTURE.md` §6 (Roadmap de evolución, dependencia "Fase 3 depende de Fase 1 y Fase 2"); `MAIEK_AI_IMPLEMENTATION_ROADMAP.md` §3 punto 3, §4 Fase 2, §8 (Matriz de trazabilidad); `MAIEK_AI_BACKEND_ARCHITECTURE.md` (nota sobre activación de escritura en `SugerenciaIA`/`MemoriaPersistente`) |
| Fase del roadmap | Fase 2 — Data Architecture Fase 3 (el bloqueante transversal) / Hito H3 |

## Contexto

`MAIEK_AI_DATA_ARCHITECTURE.md` §6 declara que la Fase 3 (Multi-Tenant, `negocio_id`)
depende de que la Fase 1 y la Fase 2 de ese mismo roadmap de datos ya estén activas.
Data Architecture Fase 2 contempla, entre otras cosas, tres entidades nuevas:
`MemoriaPersistente`, `SugerenciaIA` y `RegistroAuditoria`.

La implementación real avanzó de otra forma: el trabajo de aislamiento por
`negocio_id` (Multi-Tenant) ya avanzó a producción — incluyendo correcciones
recientes de aislamiento cruzado entre negocios (`ArchivoAdjunto` reutilizable,
umbrales de asignación en `Configuracion`) — antes de que el resto de Data
Architecture Fase 2 estuviera completo. Ese avance no fue una decisión de
conveniencia: respondió a riesgos reales de seguridad y separación de datos ya
identificados y confirmados durante la auditoría de Multi-Tenant de esta misma
sesión (2026-09-12), que exigían corrección inmediata.

Un diagnóstico posterior, dedicado exclusivamente a esta divergencia, confirmó que
no existe ningún ADR aprobado que documente esta secuencia real — la única
referencia sigue siendo la dependencia original de `MAIEK_AI_DATA_ARCHITECTURE.md`
§6, sin reconciliar con lo efectivamente implementado.

## Evidencia

- No existe dependencia técnica entre `negocio_id`/aislamiento Multi-Tenant y
  `MemoriaPersistente`: son entidades nuevas e independientes, sin relación de
  Foreign Key ni de lectura/escritura compartida con el trabajo de aislamiento ya
  implementado.
- No existe dependencia técnica entre `negocio_id`/aislamiento Multi-Tenant y
  `SugerenciaIA`: el único punto de escritura designado para esa entidad
  (`ServicioInteligencia`, según `MAIEK_AI_BACKEND_ARCHITECTURE.md`) mantiene esa
  escritura explícitamente diferida en el código actual — no depende de, ni bloquea,
  el trabajo de `negocio_id`.
- `RegistroAuditoria`, la tercera entidad de Data Architecture Fase 2, **ya existe**
  en el modelo de datos, es append-only tal como exige la arquitectura, y ya admite
  `negocio_id` (nullable, para eventos de plataforma sin negocio asociado).
- `MemoriaPersistente` y `SugerenciaIA` permanecen diferidas — no implementadas, sin
  fecha asignada, sin que esta decisión las incorpore ni las descarte.
- Las implementaciones recientes de aislamiento (`ArchivoAdjunto`, `Configuracion.
  umbral_intermedio`/`umbral_senior`) fueron necesarias por brechas reales de
  seguridad ya confirmadas — no por anticipación ni por conveniencia de secuencia.

## Decisión

Se formaliza la secuencia real:

> **Multi-Tenant (`negocio_id`) → resto pendiente de Data Architecture Fase 2**

en vez de la secuencia originalmente declarada. El trabajo de aislamiento por
`negocio_id` puede continuar y cerrarse por sus propios criterios técnicos, sin
esperar a que `MemoriaPersistente` ni `SugerenciaIA` existan.

Se mantiene sin excepción el principio ya fijado en `MAIEK_AI_DATA_ARCHITECTURE.md`
§2 ("Multi-Tenant by Design"): cuando `MemoriaPersistente` y `SugerenciaIA` se
construyan, deberán nacer con `negocio_id` desde su creación, nunca como un campo
agregado después.

Esta decisión **no** implica: cerrar el Hito H3; declarar completa Data Architecture
Fase 2; declarar implementadas `MemoriaPersistente` o `SugerenciaIA`; ni eliminarlas
del diseño objetivo — ambas permanecen vigentes como arquitectura futura de Data
Architecture, sin fecha atada al trabajo de Multi-Tenant.

## Consecuencias

**Positivas:**
- La documentación queda alineada con la secuencia real ya ejecutada, en vez de
  quedar desalineada en silencio.
- No obliga a construir `MemoriaPersistente`/`SugerenciaIA` sin un consumidor real
  que las necesite hoy, solo para satisfacer un orden documental.
- Permite continuar cerrando el trabajo de aislamiento Multi-Tenant pendiente sin
  bloqueo artificial.
- Los futuros modelos de IA (`MemoriaPersistente`, `SugerenciaIA`) podrán nacer
  multi-tenant desde el inicio, sin necesidad de backfill retroactivo.

**Negativas:**
- Requiere reconciliar documentos Approved existentes (`MAIEK_AI_DATA_ARCHITECTURE.
  md`, `MAIEK_AI_IMPLEMENTATION_ROADMAP.md`, `MAIEK_AI_BACKEND_ARCHITECTURE.md`) que
  hoy siguen describiendo la secuencia original.
- El Hito H3 continúa pendiente hasta que se evalúen y resuelvan, de forma
  independiente, sus propios criterios técnicos aún no satisfechos.
- Data Architecture Fase 2 queda formalmente como workstream independiente, sin
  fecha ni orden atado al avance de Multi-Tenant.

## H3

Este ADR **no cierra** el Hito H3 ("`negocio_id` implementado", Roadmap §5). H3
requiere una evaluación independiente, todavía pendiente, de los modelos legacy que
hoy solo tienen aislamiento indirecto (vía relación con un modelo padre, no
`negocio_id` propio) — identificados durante el diagnóstico previo como `Mensaje`,
`Lead` y `HistorialPrecioProducto` — y de cualquier otro criterio que
`MAIEK_AI_IMPLEMENTATION_ROADMAP.md` defina para considerar cerrada esa fase. Esta
decisión resuelve únicamente la secuencia respecto a Data Architecture Fase 2; no se
pronuncia sobre si esos modelos legacy requieren corrección antes de declarar H3
cumplido.

## Documentación afectada (a reconciliar en un cambio futuro, no en este)

- `MAIEK_AI_DATA_ARCHITECTURE.md` — §6, nota aclaratoria en la dependencia de Fase 3.
- `MAIEK_AI_IMPLEMENTATION_ROADMAP.md` — §3 punto 3, §4 Fase 2, §8 Matriz de
  trazabilidad, citando este ADR.
- `MAIEK_AI_BACKEND_ARCHITECTURE.md` — precisar que la activación de escritura en
  `SugerenciaIA`/`MemoriaPersistente` depende de que esas dos entidades existan, no
  de que "Data Architecture Fase 2" esté activa como bloque completo.
- `MAIEK_AI_ADR_INDEX.md` — nueva fila registrando este ADR.

Ninguno de estos documentos se modifica en este cambio.

## Reconciliación con el corpus

- [ ] Menor / local
- [x] Sustancial — cambia una dependencia ya declarada en un documento Approved
  (`MAIEK_AI_DATA_ARCHITECTURE.md` §6) y algo que otro documento
  (`MAIEK_AI_IMPLEMENTATION_ROADMAP.md`, §3/§4/§8) ya cita como dependencia.

Si es sustancial: fecha en que se actualizó el documento de origen — **2026-09-12**
(`MAIEK_AI_DATA_ARCHITECTURE.md`, `MAIEK_AI_IMPLEMENTATION_ROADMAP.md` y
`MAIEK_AI_BACKEND_ARCHITECTURE.md` reconciliados en un Gate documental posterior y
separado a la aceptación de este ADR; `MAIEK_AI_ADR_INDEX.md` actualizado en el mismo
cambio).
