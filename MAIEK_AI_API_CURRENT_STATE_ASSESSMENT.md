# Maiek AI — Current State Assessment: API Architecture

**Versión 1.0 · Estado: Approved**

| | |
|---|---|
| Documento | Current State Assessment – API Architecture |
| Proyecto | Maiek AI |
| Versión | 1.0 |
| Estado | **Approved** |
| Fecha de creación | 2026-07-28 |
| Autor | Claude, a pedido de Jesús Millones |
| Fecha de aprobación | 2026-07-28 |
| Última actualización | 2026-07-28 |

## Dependencias

- `MAIEK_AI_SYSTEM_ARCHITECTURE.md` (MSA) Capítulo 9 (Integraciones), Capítulo 10 (Runtime Architecture), Capítulo 12 (API First).
- `MAIEK_AI_BACKEND_CURRENT_STATE_ASSESSMENT.md` y `MAIEK_AI_BACKEND_ARCHITECTURE.md` — este documento **no repite** el inventario de rutas, el análisis de manejo de errores por capa, ni el modelo de autenticación ya diagnosticados/decididos ahí; los cita y se enfoca en lo específico de contrato de API que esos documentos no cubrieron.
- `MAIEK_AI_ARCHITECTURE_DOCUMENT_STANDARD.md` (ADS) v1.3.

## Consumido por

`MAIEK_AI_API_ARCHITECTURE.md` (API Architecture, todavía no construida).

## Control de versiones

| Versión | Fecha | Autor | Descripción |
|---|---|---|---|
| 1.0 (borrador) | 2026-07-28 | Claude | Primera versión — Fase 1 de Descubrimiento, análisis de la superficie de API real (`agent/main.py`, rutas JSON de `agent/dashboard.py`, ausencia de versionado/CORS/idempotencia). Sin propuestas de cambio. Pendiente de revisión y aprobación. |
| 1.0 (Approved) | 2026-07-28 | Claude | Se agrega **Clasificación de consumidores por tipo** (sección 2 — integración externa entrante, Frontend interno, AI Architecture, automatización/script, integración externa saliente); se refuerza **Idempotencia** (sección 5) como propiedad inherente del contrato de API para cualquier consumidor, no como requisito puntual de Meta — el webhook queda como la evidencia disponible hoy, no la única justificación; se agregan **Architectural Readiness** (matriz de 9 dimensiones, con la conclusión de que "Crecimiento" no tiene punto intermedio para API, a diferencia de Data/Backend) y **Priorización de remediación P1/P2/P3** (omitidas por error en el borrador, corregidas para mantener consistencia con el estándar ya validado). Documento congelado como **Approved**. |

## Alcance

Análisis de la superficie de contrato externo del sistema — qué expone hoy como interfaz consumible (por Meta, por el propio panel, o por cualquier consumidor futuro), no de la organización interna del backend (ya cubierta en el CSA-Backend, no se repite acá).

---

## 1. Superficie de API real hoy

No existe una "API" diseñada como tal — existen **tres superficies distintas**, sin unificar bajo ningún contrato común:

| Superficie | Ejemplos | Naturaleza |
|---|---|---|
| **Webhook entrante** (Meta → sistema) | `GET/POST /webhook` (`main.py:100,109`) | Contrato impuesto por Meta, no diseñado por el proyecto — ya analizado en profundidad en CSA-Backend §2 |
| **Endpoints JSON internos** (panel → su propio JS) | `GET /dashboard/lead/{telefono}/mensajes.json` (`dashboard.py:3213`), `GET /dashboard/notificaciones.json` (`dashboard.py:3224`), `GET /dashboard/lead/{telefono}/buscar-producto` (`dashboard.py:3611`), `GET /dashboard/campanas/buscar-producto` (`dashboard.py:4205`) | 4 endpoints livianos, pensados exclusivamente para que el propio HTML/JS del panel se autoactualice — nunca diseñados para un consumidor externo |
| **HTML server-side** (el resto: 42 de 46 rutas) | Bandeja de leads, chat, campañas, canales, etc. | No es una API en ningún sentido — devuelve HTML directo (ya diagnosticado en CSA-Backend §1, "fat controller") |

No existe ningún endpoint pensado para ser consumido por un cliente externo al propio panel (ni por Frontend Architecture futuro como SPA separado, ni por AI Architecture, ni por integraciones de terceros).

## 2. Clasificación de consumidores por tipo

No existe hoy una clasificación explícita — cada endpoint se construyó para su caso puntual, sin pensar en "quién más podría llamar esto". Referencia para API, Security y Frontend Architecture, con el estado real de cada tipo:

| Tipo de consumidor | Ejemplo hoy | Ejemplo futuro | Necesidad de contrato no resuelta hoy |
|---|---|---|---|
| **Integración externa entrante** (nos llama) | Webhook de Meta | Posibles ERP/SAP/Power BI (visión ya declarada en Cálidda Client Framework) | Verificación de firma ya existe (por proveedor); idempotencia no |
| **Frontend interno** (mismo origen, primera parte) | Los 4 endpoints JSON + todo el HTML de `dashboard.py` | El mismo panel, si Frontend Architecture lo separa en una SPA | Deja de ser "mismo origen" el día que se separe — hoy nada lo anticipa (CORS, versionado) |
| **AI Architecture** (servicio a servicio, interno) | No existe como consumidor — `brain.py` vive en el mismo proceso que lo llama | Si AI Architecture se separa en su propio servicio/módulo con contrato propio | Ninguna autenticación de servicio a servicio existe para ese caso |
| **Automatización/script interno** (fuera de HTTP) | `scripts/migrar_usuarios_a_railway.py` — accede directo a la BD, no pasa por ningún endpoint | Scripts de mantenimiento futuros | No es tráfico de API en absoluto — vale la pena que API Architecture declare explícitamente que este tipo de acceso queda fuera de su alcance, no que lo ignore por omisión |
| **Integración externa saliente** (nosotros llamamos) | Meta Graph API, Anthropic, Resend | — | No es un "consumidor de nuestra API" — es nuestro propio backend actuando de cliente; ya cubierto en CSA-Backend §8, se menciona acá solo para no confundirlo con las categorías de arriba |

## 3. Convenciones de diseño de endpoints

- **Sin prefijo de versión** — ninguna ruta lleva `/v1/` ni equivalente; `app = FastAPI(title="Gaso+ — Agente Gabi", version="1.0.0", ...)` (`main.py:74-78`) declara una versión en los metadatos de OpenAPI, pero esa versión no se refleja en ningún path ni se usa para nada operativo.
- **Sin prefijo `/api/`** — el webhook vive en la raíz (`/webhook`); las rutas del panel viven bajo `/dashboard` (prefijo de router, no de API).
- **Convención de nombres inconsistente**: los 4 endpoints JSON mezclan `.json` como sufijo literal en dos casos (`mensajes.json`, `notificaciones.json`) y ninguna extensión en los otros dos (`buscar-producto`) — no hay una regla única de cómo se distingue un endpoint JSON de uno que devuelve HTML dentro del mismo router.
- **Sin modelos Pydantic de entrada ni de salida** en ningún endpoint (confirmado en CSA-Backend §9) — los 4 endpoints JSON devuelven listas/diccionarios crudos (`JSONResponse(historial)`, `JSONResponse([])`) sin un esquema declarado, por lo que la documentación automática de FastAPI (`/docs`, ver §6) no describe la forma real de la respuesta.

## 4. Modelo de errores

No hay un modelo uniforme — mismo patrón ya diagnosticado en CSA-Backend §6, instanciado acá para la superficie de API: `raise HTTPException(status_code=..., detail="texto en español libre")`, sin código de error propio, sin estructura consistente entre endpoints (`{"detail": "Lead no encontrado"}` en un caso, un 403 con un mensaje distinto en otro). Ningún endpoint JSON declara un `response_model` de error. No hay distinción entre error de validación, error de autorización y error de negocio más allá del `status_code` HTTP elegido caso por caso.

## 5. Idempotencia

**Encuadre arquitectónico, no un caso puntual de un proveedor:** todo contrato de API debe asumir que **cualquier consumidor puede reenviar la misma solicitud** — por timeout del lado del cliente, por un reintento de infraestructura (balanceador, proxy), o por lógica de reintento propia del consumidor. Es una propiedad que el contrato debe declarar explícitamente para todo endpoint que no sea naturalmente idempotente (una escritura, una creación, un envío), no una particularidad de un proveedor específico.

**No existe ningún mecanismo de idempotencia en el sistema hoy** — confirmado por búsqueda exhaustiva, cero referencias a idempotencia o claves de idempotencia en el código. El caso ya observable en producción es el webhook de Meta, que reenvía el mismo evento más de una vez ante un timeout o una respuesta no-200 (comportamiento estándar de ese proveedor) — pero es solo la **evidencia disponible hoy** de un problema general, no la única superficie donde aplica: cualquier endpoint de escritura que API Architecture diseñe (para Frontend, para AI Architecture, para una integración futura) hereda el mismo riesgo si no se decide una estrategia de idempotencia a nivel de contrato. El único control tangencial que existe hoy es que `guardar_mensaje` inserta una fila nueva cada vez, sin verificar `mensaje_id` contra duplicados ya vistos — no es una protección real, es la ausencia de una.

## 6. Documentación de API expuesta

FastAPI genera documentación interactiva por defecto (`/docs`, `/redoc`, `/openapi.json`) porque `docs_url`/`openapi_url` **no están sobreescritos** en la instanciación de `FastAPI()` (`main.py:74-78`) — quedan en sus valores por defecto, **públicamente accesibles sin autenticación** (el `SessionMiddleware` protege las rutas del panel vía la dependencia `_usuario_actual`, no protege `/docs` ni `/openapi.json`, que no pasan por esa dependencia). Como no hay modelos Pydantic declarados, lo que esa documentación expone hoy es limitado (nombres de ruta y parámetros simples, no estructura real de payloads) — pero el propio hecho de que quede pública sin decisión explícita es relevante para Security Architecture.

## 7. CORS

**No hay `CORSMiddleware` configurado** — confirmado, cero referencias. Hoy no es un problema porque el único consumidor es el propio panel server-rendered (mismo origen) — pero es una brecha real si Frontend Architecture (futuro) se construye como una aplicación separada que consuma esta API desde otro origen.

## 8. Autenticación pensada para consumidores externos

No existe — la única autenticación real es la cookie de sesión del panel (ya diagnosticada en CSA-Backend §7) y la verificación de firma HMAC del webhook de Meta (CSA-Backend §8). **No hay ningún mecanismo de API key, OAuth, ni token pensado para un consumidor programático** (otro servicio, AI Architecture, un cliente móvil futuro). Confirmado por búsqueda — sin `APIKeyHeader`, sin librería de rate limiting (`slowapi` u otra) en `requirements.txt`.

## 9. Webhooks vs. APIs síncronas

Hoy solo existe el primero: el webhook de Meta es la única superficie que recibe eventos de un sistema externo. No hay ninguna API síncrona expuesta hacia afuera (todo lo que existe hacia afuera es *saliente*: llamadas del backend hacia Meta, Anthropic, Resend, ya cubiertas en CSA-Backend §8). La pregunta "webhooks vs. APIs síncronas" que API Architecture debe resolver hoy no tiene ningún precedente real en código más allá del webhook entrante ya existente — es terreno nuevo, no una decisión que ya esté tomada de facto.

## 10. Preparación para Multi-Tenant en el contrato

Ninguno de los 4 endpoints JSON ni el webhook tienen noción de `negocio_id` — coherente con que Data Architecture (Fase 3) todavía no se ejecutó en código (mismo criterio de "sincronización pendiente, no desviación" ya establecido en CSA-Backend). Ningún endpoint recibe ni devuelve un identificador de tenant hoy.

---

## Fortalezas

- El webhook de Meta ya está correctamente aislado detrás del patrón de adaptador (MSA Cap. 9) — cualquier contrato de API futuro puede apoyarse en esa misma abstracción sin tocarla.
- Los 4 endpoints JSON existentes son simples y de responsabilidad única — buena base literal para migrarlos a un contrato versionado sin rediseño conceptual.
- `FastAPI` genera OpenAPI automáticamente — una vez existan modelos Pydantic, la documentación real llega casi gratis.

## Decisiones heredadas del MVP (razonables para la etapa, a reevaluar)

- Sin versionado de API — razonable cuando el único consumidor es el propio panel en el mismo repo, desplegado siempre junto con el backend.
- Sin CORS — no hace falta mientras no exista un consumidor de otro origen.
- Sin autenticación de API key/token — no hace falta mientras no exista un consumidor externo real.
- Documentación de FastAPI expuesta sin restringir — bajo riesgo real hoy porque no hay modelos Pydantic que revelen estructura de datos sensible.

## Deuda técnica (sin justificación de etapa)

- **Sin protección de idempotencia en el webhook** — Meta reintenta por diseño; procesar un mensaje duplicado no es un caso hipotético, es un comportamiento esperado del proveedor que el sistema no maneja.
- **Modelo de errores sin estructura consistente** — mismo costo de implementación que el actual, sin beneficio de velocidad por dejarlo disperso.
- **Convención de nombres de endpoint inconsistente** (`.json` como sufijo en unos, ausente en otros) — sin justificación, cuesta lo mismo ser consistente.

## Desviaciones respecto al MSA y a Backend Architecture

- **API First (MSA Cap. 12, ya operacionalizado como decisión en Backend Architecture Cap. 3)** sigue sin superficie real más allá de 4 endpoints JSON incidentales — Backend Architecture ya decidió la separación de capas que lo habilita; falta el contrato explícito, que es exactamente el objeto de este documento.
- Ningún hallazgo de este CSA contradice una decisión ya fijada — es, en su mayoría, territorio no cubierto todavía por ningún documento del corpus.

## Riesgos detectados

1. Documentación interactiva de API pública sin restricción — bajo impacto hoy, crece si se agregan modelos Pydantic sin decidir explícitamente si `/docs` sigue público.
2. Reprocesamiento de solicitudes duplicadas por ausencia de idempotencia — el webhook de Meta ya lo evidencia hoy; cualquier endpoint de escritura nuevo hereda el mismo riesgo sin una estrategia de contrato.
3. Sin CORS ni auth de API, cualquier futuro Frontend Architecture como SPA separada requiere resolver ambos desde cero, sin nada reutilizable hoy.

## Architectural Readiness

Matriz ejecutiva de madurez del contrato de API:

| Dimensión | Madurez actual | Nota |
|---|---|---|
| Versionado | **Ausente** | Ninguna ruta ni contrato lleva versión operativa — solo un campo de metadatos sin uso real |
| Modelos de contrato (Pydantic) | **Ausente** | Ningún endpoint declara `response_model` ni modelo de entrada estructurado |
| Idempotencia | **Ausente** | Ningún mecanismo, ni siquiera para el único caso ya evidenciado en producción (reintentos de Meta) |
| Autenticación de servicio a servicio | **Ausente** | Solo existe sesión-cookie humana y verificación de firma específica del webhook |
| Documentación (OpenAPI) | **Parcial, mal calibrada** | Se genera automáticamente pero queda pública sin restricción y sin describir la forma real de las respuestas |
| Consistencia de convenciones | **Débil** | Nombres de endpoint, sufijos, y estructura de error varían caso por caso |
| Compatibilidad hacia atrás | **No aplica todavía** | No hay ninguna versión publicada que romper — la disciplina debe empezar desde el primer contrato real, no retrofitearse después |
| CORS | **Ausente** | No configurado; irrelevante mientras el único consumidor sea el mismo origen |
| Preparación Multi-Tenant en el contrato | **Ausente** | Coherente con que Data Architecture Fase 3 no está en código todavía |

**Conclusión de preparación:**

- **MVP (uso actual, panel como único consumidor, mismo origen):** **Listo.** Ninguna de estas ausencias bloquea el funcionamiento real hoy porque no existe un segundo consumidor que las necesite.
- **Crecimiento (agregar un segundo consumidor real, mismo tenant):** **No listo** — a diferencia de Data y Backend, donde el crecimiento degrada gradualmente, acá el primer consumidor nuevo (una SPA de Frontend Architecture, o AI Architecture como servicio separado) choca de inmediato contra la ausencia total de versionado, contratos tipados e idempotencia — no hay un punto intermedio "parcialmente listo".
- **SaaS multiempresa:** **No listo.** Cero preparación de tenant en el contrato, sobre una base que tampoco está lista para un segundo consumidor de ningún tipo.

## Priorización de remediación

| Prioridad | Ítem | Por qué |
|---|---|---|
| **P1** | Estrategia de idempotencia a nivel de contrato | Riesgo activo hoy (reintentos reales de Meta), no hipotético |
| **P1** | Modelo de errores uniforme | Barato de resolver ahora; el costo crece con cada endpoint nuevo que se agregue sin él |
| **P1** | Decisión de versionado | Debe fijarse antes de publicar el primer contrato real — cambiarla después de que haya consumidores es mucho más costoso |
| **P2** | Modelos Pydantic de entrada/salida para los 4 endpoints existentes | Habilita documentación real y valida el patrón antes de escalarlo a endpoints nuevos |
| **P2** | Decisión explícita sobre exposición de `/docs` | Relevante para Security Architecture, bajo riesgo real hoy pero sin decisión consciente |
| **P2** | Clasificación de consumidores reflejada en el contrato (auth diferenciada por tipo) | Antes de que exista un segundo tipo de consumidor real |
| **P3** | CORS | Diferible hasta que exista un consumidor de otro origen |
| **P3** | Autenticación de servicio a servicio completa | Diferible hasta que AI o Frontend Architecture la necesiten realmente |
| **P3** | Multi-tenant en el contrato | Depende de Data Architecture Fase 3, no bloqueante hoy |

## Architectural Decision Impact

| Hallazgo | Arquitecturas afectadas | Por qué |
|---|---|---|
| Sin versionado de API | API, Frontend, AI | Cualquier consumidor futuro (Frontend, AI Architecture) necesita un contrato estable — el versionado se decide una sola vez, acá |
| Sin idempotencia en el webhook | API, Backend | API Architecture define la estrategia; Backend Architecture ya tiene el punto de entrada (`ProcesarMensajeEntrante`) donde se aplicaría |
| Documentación de FastAPI pública sin restricción | API, Security | Security Architecture decide la política de exposición; API Architecture implementa el contrato que esa documentación describe |
| Sin CORS | API, Frontend | Frontend Architecture es el consumidor directamente afectado si se convierte en una aplicación de otro origen |
| Sin autenticación de API para consumidores externos | API, Security, AI | AI Architecture y cualquier integración futura necesitan un mecanismo de autenticación de servicio a servicio, no solo la cookie de sesión humana |

## Strategic Recommendations

1. **El versionado de API es la decisión de mayor apalancamiento de este documento.** Se toma una sola vez, antes de que exista un solo consumidor externo real — cambiarla después de que Frontend o AI Architecture ya integraron es mucho más costoso.
2. **La idempotencia del webhook no es opcional, es un requisito del propio proveedor (Meta reintenta por diseño).** Debe resolverse en la primera fase del roadmap, no diferirse.
3. **El modelo de errores necesita definirse antes que los endpoints, no junto con cada uno.** Un modelo uniforme aplicado desde el primer endpoint nuevo cuesta lo mismo que definirlo después de tener diez inconsistentes.
4. **CORS y autenticación de servicio a servicio pueden diferirse técnicamente, pero deben quedar diseñados ahora** — Frontend y AI Architecture ya están en el horizonte inmediato del roadmap de MSA Cap. 17, no son hipotéticos lejanos.
5. **Los 4 endpoints JSON existentes son el mejor punto de partida real** para validar el contrato nuevo — migrarlos primero, antes de diseñar endpoints que todavía no existen en ninguna forma.

---

*Fin del documento — Approved. Línea base técnica del contrato de API de Maiek AI. Comienza `MAIEK_AI_API_ARCHITECTURE.md` (arquitectura objetivo) como evolución explícita desde este estado real, siguiendo el ADS, el MSA y Backend Architecture, usando la tabla de priorización (P1/P2/P3) como punto de partida.*
