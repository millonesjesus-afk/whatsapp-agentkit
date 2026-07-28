# Maiek AI — Current State Assessment: Data Architecture

**Versión 1.0 · Estado: Approved**

| | |
|---|---|
| Documento | Current State Assessment – Data Architecture |
| Proyecto | Maiek AI |
| Versión | 1.0 |
| Estado | **Approved** |
| Fecha de creación | 2026-07-28 |
| Autor | Claude, a pedido de Jesús Millones |
| Fecha de aprobación | 2026-07-28 |
| Última actualización | 2026-07-28 |

## Dependencias

- `MAIEK_AI_SYSTEM_ARCHITECTURE.md` (MSA) Capítulo 8 (Arquitectura de datos, alto nivel) y Capítulo 12 (estrategia Multi-Tenant) — este documento verifica, contra el código real, qué tan cerca o lejos está la implementación de lo que el MSA describe como objetivo.
- Código fuente real del repo: `agent/memory.py`, `agent/dashboard.py`, `agent/main.py`, `agent/campanas.py`, `scripts/migrar_usuarios_a_railway.py`, `requirements.txt`, `.env.example` — fuente primaria de todo lo descrito acá.

## Consumido por

`MAIEK_AI_DATA_ARCHITECTURE.md` (Data Architecture, todavía no construida) — la arquitectura objetivo se diseña como evolución desde este estado real, no desde cero ni de forma desconectada de la implementación.

## Control de versiones

| Versión | Fecha | Autor | Descripción |
|---|---|---|---|
| 1.0 (borrador) | 2026-07-28 | Claude | Primera versión — Fase 1 de Descubrimiento, inventario fiel del modelo de datos real implementado en `agent/memory.py` y archivos relacionados. Sin propuestas de cambio. Pendiente de revisión y aprobación. |
| 1.0 (Approved) | 2026-07-28 | Claude | Revisión final: la sección "Deuda técnica" se separa en **Decisiones heredadas del MVP** (tradeoffs razonables para la etapa, a reevaluar) y **Deuda Técnica** (inconsistencias sin justificación de etapa); se agrega **Architectural Readiness** (matriz de madurez de 9 dimensiones + conclusión de preparación para MVP/Crecimiento/SaaS multiempresa); se agrega **Priorización de remediación** (P1/P2/P3) como entrada directa para Data Architecture. Documento congelado como **Approved** — línea base técnica oficial del estado actual del modelo de datos. |

## Alcance

Este documento contiene **exclusivamente** el estado actual de la implementación del modelo de datos — no propone arquitectura objetivo, no recomienda cambios, no compara alternativas. Es el insumo de entrada para `MAIEK_AI_DATA_ARCHITECTURE.md`, que se construirá después de tu aprobación, siguiendo el ADS y el MSA.

---

## 1. Esquema actual de la base de datos

**8 tablas**, todas definidas en `agent/memory.py` con SQLAlchemy 2.0 estilo declarativo tipado (`Mapped[...]` + `mapped_column(...)`, `class Base(DeclarativeBase)`). Ningún otro archivo del repo define modelos ni SQL crudo — confirmado por búsqueda exhaustiva sobre `dashboard.py` y el resto de `agent/`.

## 2. Entidades existentes

| Entidad | Tabla | PK | Estrategia de PK |
|---|---|---|---|
| `Mensaje` | `mensajes` | `id` | Autoincrement |
| `ArchivoAdjunto` | `archivos_adjuntos` | `id` | Autoincrement |
| `Lead` | `leads` | `telefono` | **Clave natural** (no `id` numérico) |
| `LineaVenta` | `lineas_venta` | `id` | Autoincrement |
| `Campana` | `campanas` | `id` | Autoincrement |
| `CanalWhatsApp` | `canales_whatsapp` | `id` | Autoincrement |
| `Usuario` | `usuarios` | `username` | **Clave natural** |
| `Configuracion` | `configuracion` | `clave` | **Clave natural** (patrón clave/valor genérico) |

No hay un criterio documentado en el código de cuándo usar clave autoincremental vs. clave natural — conviven ambas estrategias sin regla explícita.

## 3. Relaciones

**No existe ningún `relationship()` de SQLAlchemy ni una sola `ForeignKey()` real en todo el proyecto.** Todas las relaciones son convenciones de aplicación mantenidas a mano en Python, sin integridad referencial garantizada por la base de datos:

```
Usuario.username        ←── Lead.asesor_asignado        (String suelto)
Usuario.username        ←── ArchivoAdjunto.subido_por    (String suelto)
Lead.telefono           ←── Mensaje.telefono              (String suelto)
Lead.telefono           ←── LineaVenta.telefono            (String suelto)
ArchivoAdjunto.id       ←── Mensaje.archivo_id             (sin FK)
Campana.nombre          ←── Lead.campana_origen            (String suelto, no vía id)
CanalWhatsApp.phone_number_id ←── Lead.numero_whatsapp_id  (String suelto)
```

`Configuracion` es la única tabla sin relación alguna con el resto del esquema.

## 4. Convenciones de nombres

- **100% español** en tablas, clases y campos, salvo `Mensaje.role`, `content`, `timestamp` — remanente en inglés del template original de AgentKit.
- `snake_case` consistente en tablas (plural) y campos, sin mezcla de mayúsculas ni camelCase.
- Sin convención única para "está activo/disponible": `CanalWhatsApp.activo`, `Campana.activa`, `Usuario.disponible` — tres campos, tres nombres, mismo concepto.
- `Mensaje.role` acepta en la práctica un tercer valor (`"asesor"`, asignado en `dashboard.py`) no documentado en el comentario del modelo (que solo menciona `"user"`/`"assistant"`) — requiere un mapeo manual en `brain.py` antes de llamar a la API de Anthropic, que no acepta ese rol.

## 5. Restricciones

Solo dos constraints reales a nivel de base de datos en todo el esquema:

- `CanalWhatsApp.phone_number_id` — `unique=True, index=True`.
- Las 8 primary keys (una por tabla).

Ningún `CheckConstraint`, ningún `UniqueConstraint` compuesto. Varios campos con un conjunto cerrado de valores lógicos (`Lead.paso_flujo`, `Lead.resultado`, `Usuario.rol`, `Campana.tipo_deteccion`, `CanalWhatsApp.modo`) no tienen ninguna restricción a nivel de BD que lo garantice — la validación, si existe, vive solo en Python.

`Campana.nombre` no tiene `unique=True` a pesar de usarse como clave de búsqueda de facto (`obtener_campana_por_nombre`) — el propio código asume y tolera duplicados (usa `.limit(1)`).

## 6. Campos de auditoría

Sin convención uniforme:

| Tabla | Creado | Actualizado |
|---|---|---|
| `Mensaje` | `timestamp` (nombre distinto, mismo propósito) | No tiene |
| `ArchivoAdjunto` | `creado` | No tiene |
| `Lead` | `creado` | `actualizado` (con `onupdate`) |
| `LineaVenta` | `creado` | No tiene |
| `Campana` | `creado` | No tiene |
| `CanalWhatsApp` | `creado` | `actualizado` (con `onupdate`) |
| `Usuario` | No tiene | No tiene |
| `Configuracion` | No tiene | No tiene |

Solo `Lead` y `CanalWhatsApp` tienen ambos timestamps completos. No hay forma de saber, hoy, cuándo se creó una cuenta de asesor o cuándo cambió un valor de `Configuracion`.

## 7. Soft Delete

**No existe un campo de soft delete genérico** (`eliminado`, `deleted_at`) en ningún modelo. El comportamiento real es distinto por tabla:

- `Mensaje` — DELETE físico fila por fila (`limpiar_historial`).
- `LineaVenta` — DELETE físico masivo + reinserción total (reemplazo, no delta).
- `Campana` — DELETE físico, pero **solo si no tiene leads atribuidos**; si los tiene, el flujo recomendado es desactivar (`activa=False`) — un soft-delete de facto, acotado a ese caso de uso.
- `ArchivoAdjunto` — nunca se borra la fila; `eliminar_archivo_reutilizable()` solo cambia `reutilizable=False` — otro soft-delete de facto, distinto del anterior.
- `Lead`, `Usuario`, `CanalWhatsApp`, `Configuracion` — no existe ninguna función de borrado en el código para estas 4 tablas.

## 8. Multi-Tenant real

**No existe ningún campo `negocio_id`, `tenant_id`, `empresa_id` ni equivalente en ninguna de las 8 tablas.** El esquema es de un solo tenant implícito — confirmado por búsqueda exhaustiva, cero coincidencias. Multi-canal de WhatsApp (`CanalWhatsApp`) existe, pero es multi-*canal dentro de un solo negocio*, no multi-tenant: todas las tablas son compartidas globalmente, sin partición ni filtro por cliente en ninguna de las funciones de consulta de `memory.py`.

Esto es consistente con lo que el propio MSA ya reconoce en su Capítulo 8 y Capítulo 11 (Constraints) — "esquema real de un solo tenant" — pero la brecha real es mayor de lo que una lectura rápida del MSA sugiere: no hay ni siquiera un campo preparatorio o un valor hardcodeado de tenant en ningún lado; es ausencia total, no una implementación parcial.

## 9. Migraciones existentes

**No existe Alembic ni ninguna carpeta `migrations/`** — confirmado, no está en `requirements.txt` ni en el repo. El esquema se crea así:

```python
async def inicializar_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
```

`create_all` **solo crea tablas que no existen** — no aplica `ALTER TABLE` a una tabla ya desplegada. Agregar un campo nuevo a un modelo existente hoy no se propaga solo a producción; no hay evidencia de ningún mecanismo (manual o automático) que lo haga.

El único mecanismo de migración de *datos* (no de esquema) encontrado es `scripts/migrar_usuarios_a_railway.py` — un script suelto, standalone, sin versionado ni registro de ejecución, que copia usuarios de SQLite local a Postgres a mano. No existe un script equivalente para ninguna otra tabla.

## 10. ORM utilizado

SQLAlchemy **>=2.0.0** (sin techo de versión fijado en `requirements.txt`), estilo declarativo tipado moderno (`Mapped`/`mapped_column`), **100% asíncrono** (`create_async_engine`, `AsyncSession`, `async_sessionmaker`). Patrón de acceso: cada función abre su propia sesión (`async with async_session() as session:`) — no hay un patrón de repositorio ni inyección de sesión centralizada vía `Depends` de FastAPI.

## 11. Base de datos utilizada

- **Local/desarrollo:** SQLite vía `aiosqlite`.
- **Producción (Railway):** PostgreSQL vía `asyncpg`.
- Conversión de URL: el código tolera que Railway entregue `postgresql://` (formato estándar) y la reescribe a `postgresql+asyncpg://` — esta misma lógica de reescritura está **duplicada** (una copia en `memory.py`, otra casi idéntica en `scripts/migrar_usuarios_a_railway.py`), no centralizada en una función compartida.
- Motor creado sin configuración de pool (`pool_size`, `max_overflow`, `pool_pre_ping`) — valores por defecto de SQLAlchemy.

---

## 12. Fortalezas de la implementación

- Convención de nombres en español consistente y disciplinada en 8 tablas, sin mezcla salvo el remanente conocido del template original.
- Estilo SQLAlchemy 2.0 tipado moderno, no el patrón legacy — buena base para evolucionar.
- Asíncrono de punta a punta, coherente con FastAPI.
- Manejo dual SQLite/Postgres ya resuelto y probado en producción real.
- Cifrado de credenciales de canal (Fernet) ya implementado y acotado correctamente — no sobre-cifra datos que no lo necesitan.
- Índices ya presentes exactamente en los campos de mayor uso en queries reales (`asesor_asignado`, `actualizado`, `telefono`).
- Campos legacy (`Lead.producto_vendido`, `precio_venta`, etc.) están **comentados explícitamente como no usados** en vez de dejarse ambiguos — buena disciplina de documentación en código, aunque el campo siga ahí.

## 13. Decisiones heredadas del MVP

Limitaciones actuales que no se clasifican como deuda porque fueron tradeoffs razonables para la etapa inicial del producto — decisiones conscientes de velocidad, no descuidos. Se listan acá porque su vigencia debe **reevaluarse**, no porque estén mal hechas:

- **Ausencia de `ForeignKey` reales** — priorizar velocidad de iteración de esquema en una fase de cambios frecuentes es razonable para un solo desarrollador y un solo producto; el costo (integridad referencial débil) recién se vuelve significativo al escalar equipo o volumen.
- **Ausencia de convención uniforme de auditoría** — se agregó `creado`/`actualizado` solo donde el negocio lo necesitaba de forma directa (`Lead`, para ordenar/priorizar; `CanalWhatsApp`, para diagnóstico), no como práctica sistemática — razonable cuando el volumen de tablas era menor.
- **Ausencia de Alembic / migraciones formales** — `create_all` es suficiente para una sola instancia con despliegue simple y un solo desarrollador aplicando cambios; el costo aparece recién cuando el esquema cambia con más frecuencia o hay más de una persona tocando el modelo.
- **Ausencia de `CheckConstraint`** — validar en la capa de aplicación en vez de en la base de datos permite iterar más rápido sobre los valores lógicos permitidos (`paso_flujo`, `resultado`) sin migraciones — razonable mientras esos valores todavía cambiaban con frecuencia.
- **Ausencia de configuración de pool de conexiones** — el volumen de tráfico actual (un solo negocio, un panel interno) no lo exige todavía.
- **Esquema de un solo tenant** — construir multi-tenant desde el primer día, para un piloto de un solo cliente (Gaso+), habría sido trabajo prematuro sin caso de uso real que lo validara.

## 14. Deuda Técnica

Limitaciones que no se explican por la etapa del producto — inconsistencias o vacíos que convendría corregir independientemente del tamaño o momento del proyecto:

- **Tres patrones distintos de soft-delete** (`activa`/`reutilizable`/DELETE físico) — no es una decisión deliberada de simplicidad, es inconsistencia acumulada al resolver cada caso por separado.
- **Precios almacenados como `String`** (`Lead.precio_venta`, `LineaVenta.precio`, `Campana.precio_promocional`) en vez de tipo numérico — sin capacidad de operar aritméticamente sin conversión, riesgo de datos mal formados desde el día uno, sin beneficio claro de velocidad a cambio.
- **`Mensaje.role` con valor no documentado** (`"asesor"`) que requiere traducción manual antes de llamar a la API de Anthropic — el comentario del modelo quedó desactualizado respecto al comportamiento real.
- **Lógica de reescritura de `DATABASE_URL` duplicada** en dos archivos — sin beneficio de velocidad, solo falta de una función compartida.
- **`Campana.nombre` sin `unique=True`** pese a usarse como clave de búsqueda de facto — el propio código ya tiene que tolerar y trabajar alrededor de la ambigüedad que esto genera.

## 15. Desviaciones respecto al MSA

- **Multi-Tenant (MSA Cap. 8/12):** el MSA ya reconoce el esquema actual como single-tenant, pero la desviación real es más profunda de lo declarado — no hay ni un campo preparatorio; la estrategia de aislamiento a nivel de fila (row-level) que el MSA fija como decisión objetivo (Cap. 12) requiere trabajo desde cero en las 8 tablas, no una extensión incremental.
- **Migraciones formales:** el MSA no aborda explícitamente la ausencia de Alembic como brecha propia (sí menciona "sin CI documentado" en Cap. 14, un tema relacionado pero distinto) — esta es una brecha nueva, descubierta en esta fase, no anticipada en el MSA.
- **Integridad referencial:** el MSA no especifica un requisito de `ForeignKey` real, pero el patrón de "referencia suelta" generalizado en las 8 tablas contradice el espíritu de Reutilizable/Desacoplada (MSA Cap. 2) al depender de disciplina manual en vez de garantías del motor de base de datos.
- **Cifrado (MSA Cap. 13):** consistente — el MSA describe exactamente el alcance real (Fernet, solo credenciales de `CanalWhatsApp`), sin desviación.
- **Roles (MPA sección 9, vía MSA Cap. 13):** consistente — `Usuario.rol` (`admin`/`supervisor`/`asesor`) coincide con los roles ya declarados en el MPA.

## 16. Riesgos detectados

1. **Drift de esquema en producción** — `create_all` no altera tablas existentes; cualquier campo nuevo requiere intervención manual no documentada hoy.
2. **Ausencia total de tenant** — cualquier expansión a un segundo negocio (ya anticipada como visión en Cálidda Client Framework y en el MSA) parte de cero en el modelo de datos, no de una extensión.
3. **Integridad referencial dependiente de disciplina de aplicación** — filas huérfanas son posibles hoy sin que la base de datos lo impida.
4. **Precios como texto** — riesgo de datos mal formados o inconsistentes que solo se detectan en tiempo de uso, no de escritura.
5. **Sin trazabilidad de auditoría en `Usuario`/`Configuracion`** — no se puede reconstruir cuándo se creó una cuenta o cuándo cambió un valor crítico de configuración (ej. `system_prompt_produccion`).
6. **Migración de datos no reproducible** — el único script de migración existente es manual, específico de una tabla, sin versionado; no escala a un modelo de datos que va a crecer con Data Architecture.

## 17. Architectural Readiness

Matriz ejecutiva de madurez — no mide si el código "está bien o mal", mide si cada dimensión sostiene el próximo nivel de exigencia:

| Dimensión | Madurez actual | Nota |
|---|---|---|
| Modelo de entidades | **Sólido** | 8 tablas bien delimitadas, dominio claro, naming consistente en español |
| Integridad referencial | **Ausente** | Sin `ForeignKey` reales — todo por convención de aplicación |
| Multi-tenant | **Ausente** | Cero campos de tenant en las 8 tablas |
| Auditoría | **Parcial** | Solo 2 de 8 tablas con `creado`+`actualizado` completos |
| Migraciones de esquema | **Ausente** | Sin Alembic; `create_all` no altera tablas existentes |
| Seguridad de datos en reposo | **Sólido (acotado)** | Fernet correctamente aplicado donde corresponde, sin sobre-cifrado |
| Escalabilidad (índices/pool) | **Parcial** | Índices bien puestos en los hot paths reales; sin configuración de pool |
| Consistencia de convenciones | **Parcial** | Naming disciplinado; soft-delete, auditoría y booleanos de estado inconsistentes entre tablas |
| Gestión de borrado (soft delete) | **Ausente / inconsistente** | Tres patrones ad-hoc distintos, sin convención genérica |

**Conclusión de preparación:**

- **MVP (uso actual, Gaso+ single-tenant):** **Listo.** El modelo sostiene la operación real en producción hoy sin bloqueos — las decisiones de la sección 13 fueron tradeoffs correctos para este nivel de exigencia.
- **Crecimiento (más volumen de leads/asesores/campañas dentro del mismo tenant):** **Parcialmente listo.** Sostiene crecimiento moderado sin cambios; migraciones formales y auditoría uniforme deberían resolverse antes de un crecimiento significativo para evitar fricción operativa creciente.
- **SaaS multiempresa:** **No listo.** Requiere trabajo fundacional — multi-tenant en las 8 tablas, integridad referencial real, migraciones formales — antes de ser viable. Es exactamente el vacío que `MAIEK_AI_DATA_ARCHITECTURE.md` debe cerrar.

## 18. Priorización de remediación

Entrada directa para la construcción de `MAIEK_AI_DATA_ARCHITECTURE.md` — no se ejecuta nada de esto todavía, es la base de priorización:

| Prioridad | Ítem | Por qué |
|---|---|---|
| **P1** | Multi-tenant (campo de tenant en las 8 tablas) | Bloqueante absoluto para SaaS multiempresa — nada más en esta tabla importa si esto no se resuelve primero |
| **P1** | Integridad referencial real (`ForeignKey`) | Alto riesgo de datos huérfanos a medida que crece el volumen y el número de personas tocando el esquema |
| **P1** | Precios como tipo numérico | Riesgo de datos mal formados ya presente hoy, sin relación con el tamaño del proyecto |
| **P1** | Migraciones formales (Alembic o equivalente) | Sin esto, cualquier cambio de esquema de Data Architecture es manual y de alto riesgo de drift |
| **P2** | Convención uniforme de soft-delete | Necesario antes de que el número de tablas con borrado siga creciendo de forma ad-hoc |
| **P2** | Convención uniforme de auditoría (`creado`/`actualizado` en las 8 tablas) | Importante para trazabilidad, no bloquea el arranque de Data Architecture |
| **P2** | `CheckConstraint` en valores lógicos cerrados | Refuerza integridad sin ser urgente mientras la validación de aplicación siga funcionando |
| **P2** | Documentar/corregir `Mensaje.role` (tercer valor) | Inconsistencia conocida y ya mitigada en código; corregir de raíz durante Data Architecture |
| **P2** | `Campana.nombre` con `unique=True` | Elimina una ambigüedad ya tolerada por el código |
| **P3** | Configuración de pool de conexiones | Deferible hasta que el volumen real lo exija |
| **P3** | Centralizar lógica de reescritura de `DATABASE_URL` | Mejora de mantenibilidad, sin riesgo asociado |
| **P3** | Unificar nombres de booleanos de estado (`activo`/`activa`/`disponible`) | Cosmético, cero riesgo funcional |

---

*Fin del documento — Approved. Línea base técnica oficial del estado actual del modelo de datos. Comienza `MAIEK_AI_DATA_ARCHITECTURE.md` (arquitectura objetivo) como evolución explícita desde este estado real, siguiendo el ADS y el MSA, usando la tabla de priorización (sección 18) como punto de partida.*
