# Maiek AI — Current State Assessment: Backend Architecture

**Versión 1.0 · Estado: Approved**

| | |
|---|---|
| Documento | Current State Assessment – Backend Architecture |
| Proyecto | Maiek AI |
| Versión | 1.0 |
| Estado | **Approved** |
| Fecha de creación | 2026-07-28 |
| Autor | Claude, a pedido de Jesús Millones |
| Fecha de aprobación | 2026-07-28 |
| Última actualización | 2026-07-28 |

## Dependencias

- `MAIEK_AI_SYSTEM_ARCHITECTURE.md` (MSA) Capítulo 4-6 (Capas, Componentes, Platform Engines), Capítulo 9 (Integraciones), Capítulo 10 (Runtime Architecture), Capítulo 12 (Architectural Decisions) — puntos de comparación de esta revisión.
- `MAIEK_AI_DATA_ARCHITECTURE.md` — decisiones ya Approved (Multi-Tenant, FKs, soft delete, UUID) que el backend real todavía no implementa; este documento distingue "no implementado todavía" de "desviación real".
- `MAIEK_AI_ARCHITECTURE_DOCUMENT_STANDARD.md` (ADS) v1.1 — estructura y Regla de herencia arquitectónica.

## Consumido por

`MAIEK_AI_BACKEND_ARCHITECTURE.md` (Backend Architecture, todavía no construida) — la arquitectura objetivo se diseña como evolución desde este estado real.

## Control de versiones

| Versión | Fecha | Autor | Descripción |
|---|---|---|---|
| 1.0 (borrador) | 2026-07-28 | Claude | Primera versión — Fase 1 de Descubrimiento, análisis arquitectónico del backend real (`agent/main.py`, `brain.py`, `dashboard.py`, `campanas.py`, `asignacion.py`, `notificaciones.py`, `tiempo_real.py`, `tools.py`, `providers/`). Sin propuestas de cambio. Pendiente de revisión y aprobación. |
| 1.0 (Approved) | 2026-07-28 | Claude | Se agregan **Architectural Decision Impact** (qué arquitecturas derivadas afecta cada hallazgo) y **Strategic Recommendations** (ejes temáticos, no soluciones, para la arquitectura objetivo) — mejora metodológica que se incorpora desde ahora como cierre estándar de todo Current State Assessment futuro. Documento congelado como **Approved** — línea base técnica del backend. |

## Alcance

Análisis arquitectónico, no inventario de archivos — cómo fluye una petición, cómo se acoplan los módulos, qué patrones existen realmente, y cómo se compara eso contra las decisiones ya fijadas en MSA y Data Architecture. Sin propuestas de arquitectura objetivo — eso es `MAIEK_AI_BACKEND_ARCHITECTURE.md`, después de tu aprobación.

---

## 1. Estructura de módulos y responsabilidades

| Módulo | Líneas | Responsabilidad real |
|---|---|---|
| `agent/main.py` | 296 | Servidor FastAPI, webhook de WhatsApp, orquestación del flujo de mensaje, lifespan |
| `agent/brain.py` | 291 | Único punto de acceso a la API de Anthropic — genera respuesta y extrae datos del lead |
| `agent/dashboard.py` | 4601 | Panel administrativo completo: 46 rutas cubriendo 9 áreas funcionales distintas (auth, WebSocket, métricas, bandeja de leads, chat operativo, asesores, campañas, canales, perfil) |
| `agent/campanas.py` | 366 | Detección de campaña, resolución de promociones, Lead Ads de Meta |
| `agent/asignacion.py` | 120 | Asignación automática de leads a asesores por nivel y carga |
| `agent/notificaciones.py` | 118 | Aviso por correo (Resend) — puente manual, no integración real con un sistema de derivación |
| `agent/tiempo_real.py` | 64 | Registro de conexiones WebSocket en memoria de proceso (pub/sub simplificado) |
| `agent/tools.py` | 306 | Catálogo de productos, horario de atención, búsqueda de contexto |
| `agent/providers/` | 471 | Adaptador de proveedor de WhatsApp (interfaz + implementación Meta) |

**`dashboard.py` concentra el 59% de las líneas de código del backend** (4601 de 7833 líneas totales, excluyendo `memory.py`) en un único archivo — es, con diferencia, el módulo con menos separación de responsabilidades del sistema. Es un patrón de **"fat controller"**: cada handler de ruta mezcla validación, lógica de negocio, y generación de HTML server-side (f-strings de Python, sin motor de templates) en la misma función. Ejemplo concreto: `registrar_venta` contiene, en una sola función, parseo de JSON del carrito, saneamiento manual de campos, reglas de negocio de forma de pago, y una regla de negocio implícita ("si hay productos, el resultado pasa a 'vendido' automáticamente") — nada de esto vive en un módulo de dominio separado.

## 2. Flujo completo de una petición (entrada → lógica → persistencia → respuesta)

Punto de entrada único: `POST /webhook`. **Todo el flujo corre síncronamente dentro del propio request handler** — no hay cola, ni `BackgroundTasks`, ni tarea async separada.

1. **Verificación de firma** (HMAC-SHA256 contra `X-Hub-Signature-256`, delegada al proveedor).
2. **Bifurcación**: si es un webhook de Lead Ads (formulario), se delega completo y se retorna — nunca toca el resto del flujo.
3. **Parseo normalizado** — el proveedor traduce el payload de Meta a `MensajeEntrante`.
4. **Loop secuencial** por cada mensaje del batch (sin paralelismo — cero `asyncio.gather`):
   - Se ignoran mensajes propios.
   - Se resuelve el canal (multi-número).
   - **Camino "echo"** (asesor respondió desde WhatsApp Business directo): solo se guarda, nunca pasa por la IA.
   - Tipos no soportados (audio/imagen/documento): respuesta fija, sin llamar a Claude.
   - Detección de campaña (solo si el lead no tiene una asignada).
   - **Gate de asesor humano**: si hay alguien asignado y el caso sigue abierto, Gabi nunca responde — solo se persiste el mensaje.
   - Se recupera historial (antes de guardar el mensaje actual, para evitar duplicados) y se marca "escribiendo".
   - **Generación de respuesta IA** — única llamada al AI Engine (`brain.py`).
   - **Manejo de fallas**: contador de fallos consecutivos por lead; a la 2ª falla consecutiva, se reemplaza la respuesta por un mensaje de escalamiento y se asigna un asesor automáticamente.
   - Persistencia del mensaje del usuario y la respuesta, envío por WhatsApp, emisión de evento en tiempo real.
   - **Extracción de datos estructurados** (segunda llamada a Claude, modelo económico) — solo si no hubo error.
   - Derivación automática a asesor si el paso de flujo cambió a "derivado".
5. **Manejo de excepción a nivel webhook**: un catch-all envuelve todo el for-loop — una excepción en el mensaje 3 de un batch de 5 aborta el procesamiento de los mensajes 4 y 5, sin reintento ni cola de reproceso propia.

Este flujo real coincide, en su secuencia lógica, con los 9 pasos ya definidos en MSA Cap. 10 (Runtime Architecture) — la correspondencia es alta. La diferencia real está en el **paso 6 (Evaluación de decisión)**: MSA Cap. 7 y MPX Cap. 2 definen ese paso como una evaluación de **nivel de confianza de la IA**; en el código real, el disparador de handoff a humano es un **contador de fallas técnicas consecutivas**, no una señal de incertidumbre del modelo — Claude no emite ningún nivel de confianza explícito hoy. Ver sección 8 (Desviaciones).

## 3. Dependencias entre módulos y nivel de acoplamiento

```
main.py       → brain, memory, providers, dashboard, tiempo_real, notificaciones, asignacion, campanas
brain.py      → tools, memory, campanas
campanas.py   → memory, tools
asignacion.py → tools, memory
notificaciones.py, tiempo_real.py, tools.py → sin dependencias internas del proyecto (hojas)
providers/meta.py → providers.base, memory
```

**Sin dependencias circulares** entre los 7 módulos del agente conversacional. `tools.py` y `tiempo_real.py` son hojas puras.

**Acoplamiento con `dashboard.py`**: es unidireccional pero fuerte — `dashboard.py` importa activamente `tiempo_real`, `memory`, `campanas`, `brain`, `tools`, `notificaciones`, `asignacion` y `providers`. Ninguno de los 7 módulos del agente importa `dashboard.py` de vuelta (sin ciclo), pero el panel depende directamente de la lógica de negocio del agente conversacional en vez de comunicarse a través de una interfaz o capa de servicio separada — el mismo `dashboard.py` que genera HTML también reimplementa lógica de negocio (ver sección 1) en paralelo a la que ya vive en `campanas.py`/`asignacion.py`.

**Hallazgo de código roto**: `providers/__init__.py` referencia `agent.providers.twilio`, pero ese archivo **no existe en el repo**. Si `WHATSAPP_PROVIDER=twilio`, la aplicación falla al arrancar con `ModuleNotFoundError`.

## 4. Patrones arquitectónicos utilizados

- **Factory + Strategy/Template Method**: `obtener_proveedor()` selecciona la implementación según configuración; `ProveedorWhatsApp(ABC)` define la interfaz con métodos "hook" no-op por defecto — un proveedor nuevo solo sobreescribe lo que soporta. Coincide exactamente con el patrón de adaptador ya declarado en MSA Cap. 9.
- **Singleton implícito a nivel de módulo** (no inyección de dependencias): el cliente de Anthropic, el proveedor activo, y el gestor de conexiones WebSocket se instancian una sola vez al importar el módulo y se reusan como variables globales.
- **Observer/Pub-Sub simplificado, en memoria de proceso**: `GestorConexiones` — explícitamente documentado en el propio código como no apto para múltiples instancias sin migrar a un pub/sub externo.
- **Configuración dirigida por datos** en `campanas.py`: el tipo de detección de campaña se lee de una columna de BD y decide el comportamiento, en vez de código nuevo por campaña — coincide con el espíritu de Configuration over Code (MSA Cap. 12).
- **"Fat controller"** en `dashboard.py` — patrón dominante ahí, ya descrito en la sección 1. No hay capa de servicio, repositorio ni controlador separados en ningún módulo del backend.

## 5. Gestión de configuración

No hay objeto de configuración centralizado ni tipado — `os.getenv()` disperso, cada módulo lee lo que necesita, con manejo de ausencia inconsistente:
- Algunas variables **rompen el arranque** si faltan (`SESSION_SECRET_KEY` en producción).
- Otras **degradan silenciosamente** con solo un warning (`RESEND_API_KEY` ausente → notificaciones no salen, sin excepción; canal de Meta sin `app_secret` → verificación de firma **desactivada por defecto**, ver Riesgos).
- Algunos valores de negocio son configurables desde el panel vía la tabla `Configuracion` (umbrales de asignación, prompt de producción, modo por canal) — coincide con Configuration over Code.
- La mayoría de constantes de negocio (roles, resultados, extensiones permitidas, tamaño máximo de archivo, campañas iniciales) están hardcodeadas como constantes de módulo en Python, no en configuración ni en base de datos.

## 6. Manejo de errores

**No existe circuit breaker, no existe retry con backoff en ningún punto del sistema** (ni en el SDK de Anthropic, ni en las llamadas HTTP a Meta/Resend — sin `tenacity`/`backoff` en `requirements.txt`).

- **Fallo de Claude (respuesta al cliente)**: capturado con `except Exception` genérico; activa un contador de fallas consecutivas por lead con un umbral hardcodeado (2) que dispara escalamiento a un asesor humano — es una degradación real con alternativa, pero implementada como lógica de negocio puntual en el webhook, no como patrón de resiliencia reutilizable.
- **Fallo de extracción de datos del lead**: capturado, se loggea como `warning`, y retorna silenciosamente un diccionario vacío — **no hay ninguna señal que suba** hacia el flujo principal; el lead simplemente no se actualiza ese turno, sin aviso a nadie.
- **Fallo de red hacia Meta o Resend**: ninguno de los métodos HTTP tiene `try/except` propio alrededor de la llamada — una excepción de transporte (timeout, conexión rechazada) se propaga sin capturar hasta el catch-all genérico del webhook, que responde 500 sin ninguna cola de reintento propia (depende del reintento externo de Meta, no controlado por este código).
- **Ningún cliente HTTP tiene `timeout=` configurado explícitamente** — ni el cliente de Anthropic, ni los `httpx.AsyncClient()` de Meta/Resend (todos usan defaults del SDK/librería).

## 7. Gestión de sesiones y ciclo de vida

**Sesión del panel**: cookie firmada (`SessionMiddleware` de Starlette), autenticación resuelta por una dependencia de FastAPI (`_usuario_actual`) que lee la sesión y valida contra la tabla `Usuario`. El error de "no autenticado" se propaga hasta un exception handler global que redirige a login.

**Autorización**: no hay sistema de roles declarativo — el rol vive como string plano, y la verificación `if usuario["rol"] != "admin": raise HTTPException(403)` está **duplicada manualmente unas 26 veces** a lo largo de `dashboard.py`, sin decorador ni dependencia reutilizable (a diferencia de la autenticación, que sí está centralizada). La única regla de autorización factorizada en una función compartida es "un asesor solo ve sus propios leads".

**WebSocket**: no puede usar `Depends()`, así que repite manualmente la misma lógica de autenticación que la dependencia HTTP — duplicación funcional entre ambos caminos, aunque con el mismo resultado semántico.

**Ciclo de vida del proceso** (`lifespan` de FastAPI): inicializa la base de datos, siembra canales desde variables de entorno (solo si la tabla está vacía), siembra campañas iniciales hardcodeadas (solo si no hay ninguna), y corrige patrones de campaña desalineados en **cada arranque** (fix idempotente para una migración de datos que corrió mal originalmente). No hay cleanup explícito al apagar (nada después del `yield`), no hay warm-up ni pre-carga de modelos, no hay scheduler.

## 8. Integración con IA y servicios externos

**IA (Anthropic)**: cliente instanciado una sola vez a nivel de módulo, dos modelos (uno principal para responder, uno económico para extraer datos). El system prompt se resuelve por modo de canal (pruebas/producción, este último configurable desde el panel) y se mantiene deliberadamente estático entre llamadas para dejar la puerta abierta a *prompt caching* (no implementado hoy). El contexto dinámico del turno (hora, datos del lead, promoción vigente, catálogo relevante) se inyecta como texto en el mensaje `user`, nunca en el `system`. **No usa tool-calling de Claude** — todo el contexto es texto plano concatenado, no function calling estructurado. **No hay nivel de confianza explícito en la salida del modelo** — ver Desviaciones, sección 9.

**Meta (WhatsApp)**: credenciales leídas dinámicamente de la base de datos en cada llamada (nunca cacheadas al arrancar), lo que permite agregar/editar canales desde el panel sin reiniciar el proceso — buen patrón. Verificación de firma con comparación en tiempo constante (`hmac.compare_digest`) — correcta contra timing attacks, **pero con un fallback inseguro**: si ningún canal tiene `app_secret` configurado, la verificación se desactiva silenciosamente (ver Riesgos). Cada llamada a la Graph API abre su propio cliente HTTP (sin reuso/pooling), sin timeout explícito, sin try/except local.

**Resend (notificaciones)**: integración mínima, sin persistencia ni cola — si falla, se pierde el correo, sin reintento. El propio código documenta que es un puente provisional mientras no exista integración real con un sistema de derivación (Genesys Cloud, mencionado en el comentario).

## 9. Riesgos arquitectónicos y deuda técnica

### Fortalezas

- Patrón de adaptador de proveedor de WhatsApp limpio y correctamente aislado — coincide exactamente con MSA Cap. 9.
- Único punto de acceso a Claude (`brain.py`) — coincide con el AI Engine de MSA Cap. 6-7.
- `dashboard.py` nunca accede a la base de datos directamente — todo pasa por `memory.py`, sin una sola consulta SQL fuera de la capa de datos.
- Detección de campaña dirigida por datos, no por código nuevo por campaña.
- Comparación de firma en tiempo constante donde la verificación sí está activa.
- Mecanismo de escalamiento automático a humano ante fallas repetidas de IA — funciona hoy, en producción real.
- Corrección idempotente de datos mal migrados en cada arranque — señal de atención operativa real.

### Decisiones heredadas del MVP (razonables para la etapa, a reevaluar)

- Procesamiento 100% síncrono del webhook, sin cola — razonable al volumen actual; MSA Cap. 16 ya lo señaló como brecha a resolver con evidencia, no antes.
- Sin retry/backoff en ninguna llamada externa — added complexity no justificada todavía al volumen real.
- Sin suite de tests automatizados (solo un simulador manual de chat) — tradeoff común de velocidad en etapa temprana.
- Registro de WebSockets en memoria de proceso, no distribuido — documentado explícitamente en el propio código como simplificación intencional para una sola instancia.
- Sin configuración centralizada/tipada — manejable con el número actual de variables de entorno.
- Sin cliente HTTP compartido con pooling — impacto despreciable al tráfico actual.

### Deuda técnica (sin justificación de etapa)

- **Verificación de firma de webhook falla abierta** (`fail-open`) — si un canal no tiene `app_secret`, se acepta cualquier payload como legítimo, con solo un warning en el log. No hay tradeoff de velocidad que lo justifique; es un riesgo de seguridad real.
- **Sin timeout explícito** en ningún cliente HTTP (Anthropic, Meta, Resend) — costo de agregarlo es mínimo, sin justificación para omitirlo.
- **Sin `try/except` local** alrededor de las llamadas HTTP a Meta/Resend — una excepción de red se propaga sin control hasta el catch-all genérico.
- **Fallo silencioso y total de la extracción de datos del lead** — sin ninguna señal hacia arriba, el dato simplemente no se actualiza, sin registro visible del problema.
- **Referencia rota a `agent/providers/twilio.py`** — archivo inexistente, branch del factory que rompe la aplicación si se selecciona.
- **Autorización duplicada ~26 veces** en vez de una dependencia/decorador reutilizable — mismo costo de implementación que la duplicación, sin beneficio de velocidad.
- **`dashboard.py` de 4601 líneas, 9 áreas funcionales sin separación** — riesgo real de colisión y regresión a medida que crece, y bloqueo directo para que Frontend Architecture (futuro) tenga una API limpia de la cual consumir en vez de HTML server-side.

## Desviaciones respecto al MSA y Data Architecture

- **Sin nivel de confianza explícito de la IA (MSA Cap. 7, MPX Cap. 2)**: el protocolo de incertidumbre (Alta / Requiere validación / Baja) no existe en el código real — el AI Engine no emite ningún score de confianza; el disparador real de handoff a humano es un contador de fallas técnicas, no una señal de certeza del modelo. Es la desviación más significativa encontrada — el mecanismo técnico que MSA Cap. 7 exige ("un nivel de confianza como salida explícita del modelo") todavía no existe.
- **API First (MSA Cap. 12) no implementado**: no existe una capa de API limpia — `dashboard.py` genera HTML server-side directamente, sin una interfaz que Frontend Architecture (o cualquier cliente externo) pueda consumir. Toda funcionalidad del panel es indisociable de su renderizado.
- **Event-Driven (MSA Cap. 12) no aplicado**: el procesamiento es 100% síncrono; el patrón "notificación + analítica + observabilidad en paralelo sin bloquear la respuesta" que MSA Cap. 10/12 describe no existe hoy — todo ocurre secuencialmente dentro del mismo request.
- **Data Architecture** (Multi-Tenant, Foreign Keys, soft delete `eliminado_en`/`eliminado_por`, UUID, `RegistroAuditoria`): el backend real no implementa ninguna de estas decisiones todavía — **no es una desviación en el sentido de contradicción**, es sincronización pendiente: Data Architecture fue aprobada como objetivo, su roadmap (Fases 1-3) todavía no se ejecutó en código. Backend Architecture debe partir de este hecho, no ignorarlo.
- **"Business Rules Engine" (MSA Cap. 6)** existe solo como lógica Python específica (`asignacion.py`), no como un motor genérico y configurable — simplificación razonable hoy, brecha real si se necesita agregar reglas de negocio nuevas sin tocar código.

## Architectural Readiness

| Dimensión | Madurez actual | Nota |
|---|---|---|
| Separación de capas (rutas/negocio/datos) | **Débil** | `dashboard.py` mezcla las tres; solo el acceso a datos está limpiamente aislado |
| Acoplamiento entre módulos | **Sólido** | Sin ciclos, jerarquía clara; acoplamiento fuerte pero unidireccional de `dashboard.py` hacia el agente |
| Resiliencia (retry, timeout, circuit breaker) | **Ausente** | Ningún mecanismo genérico; solo una degradación ad-hoc para fallas de IA |
| Seguridad del webhook | **Débil (fail-open)** | Verificación de firma puede quedar desactivada sin que nadie lo note |
| Autorización | **Parcial** | Funciona, pero duplicada, no factorizada, alto riesgo de inconsistencia futura |
| Observabilidad de errores | **Parcial** | Logging disperso, sin taxonomía de errores, fallos silenciosos en al menos un flujo crítico |
| Gestión de configuración | **Parcial** | Mezcla de env vars, constantes hardcodeadas, y configuración en BD, sin criterio único |
| Integración con IA (protocolo MPX) | **Ausente** | Sin nivel de confianza explícito; handoff basado en fallas técnicas, no en incertidumbre |
| Preparación Multi-Tenant | **Ausente** | Cero conciencia de tenant en sesión, auth o resolución de canal — coherente con que Data Architecture aún no se implementó |
| Escalabilidad (procesamiento) | **Parcial** | Síncrono, sin cola; funciona al volumen actual, brecha ya conocida para crecimiento |

**Conclusión de preparación:**

- **MVP (uso actual, Gaso+ single-tenant):** **Listo.** El backend sostiene la operación real en producción — las decisiones de la sección 9 (heredadas del MVP) fueron tradeoffs correctos para este nivel de exigencia.
- **Crecimiento (más volumen, mismo tenant):** **Parcialmente listo.** El procesamiento síncrono y la ausencia de retry/timeout se vuelven riesgos reales antes que el multi-tenant; requiere atención en la arquitectura objetivo.
- **SaaS multiempresa:** **No listo.** Ningún componente del backend (sesión, auth, resolución de canal, webhook) tiene noción de tenant — coherente con que Data Architecture (su prerrequisito) todavía no se implementó en código. Además, la ausencia de una capa de API limpia (`dashboard.py` genera HTML directo) bloquea cualquier futuro cliente que no sea ese mismo panel server-rendered.

## Priorización de remediación

Entrada directa para `MAIEK_AI_BACKEND_ARCHITECTURE.md`:

| Prioridad | Ítem | Por qué |
|---|---|---|
| **P1** | Corregir verificación de firma fail-open | Riesgo de seguridad activo hoy, no hipotético |
| **P1** | Timeouts explícitos en todos los clientes HTTP/Anthropic | Riesgo de solicitudes colgadas sin límite, ya presente |
| **P1** | Eliminar o implementar el branch roto de `twilio` | Falla de arranque real si se selecciona ese proveedor |
| **P1** | Separar capa de servicio/negocio de `dashboard.py` | Bloqueante para API First (MSA Cap. 12) y para escalar el equipo |
| **P2** | Centralizar autorización (dependencia/decorador reutilizable) | Alto riesgo de inconsistencia al agregar rutas nuevas |
| **P2** | `try/except` local en llamadas HTTP externas, con manejo explícito | Hoy las fallas de red se propagan sin control |
| **P2** | Señal de error visible cuando falla la extracción de datos del lead | Hoy es un fallo completamente silencioso |
| **P2** | Mecanismo de nivel de confianza explícito del AI Engine | Requisito ya fijado en MSA Cap. 7 y MPX Cap. 2, no implementado |
| **P2** | Cola/mecanismo asíncrono para desacoplar el webhook de la respuesta HTTP | Event-Driven ya decidido en MSA Cap. 12, pendiente de ejecución |
| **P3** | Retry/backoff (ej. `tenacity`) en llamadas externas | Mejora de resiliencia, sin evidencia de urgencia hoy |
| **P3** | Cliente HTTP compartido con pooling | Mejora de performance, impacto bajo al volumen actual |
| **P3** | Suite de tests automatizados | Mejora de calidad, deferible sin bloquear el roadmap |
| **P3** | Configuración centralizada y tipada | Mejora de mantenibilidad, no urgente al número actual de variables |

## Architectural Decision Impact

Qué arquitecturas derivadas se ven afectadas por cada hallazgo relevante — insumo para secuenciar el trabajo entre documentos, no para resolverlo acá:

| Hallazgo | Arquitecturas afectadas | Por qué |
|---|---|---|
| `dashboard.py` fat controller, sin capa de servicio | Backend, API, Frontend | Bloquea un contrato de API limpio (API First, MSA Cap. 12) del que Frontend Architecture pueda consumir sin acoplarse al HTML actual |
| Procesamiento 100% síncrono, sin cola | Backend, DevOps, Operations | Afecta directamente la capacidad de escalar carga y la definición de SLAs de extremo a extremo (MSA Cap. 10, 16) |
| Sin nivel de confianza explícito de la IA | Backend, AI | AI Architecture es quien debe definir cómo el modelo emite esa señal; Backend es quien debe consumirla en el flujo de decisión |
| Verificación de firma fail-open | Security, Backend | Es un hallazgo de seguridad primero — Security Architecture define la política, Backend la implementa |
| Sin timeout / sin retry / sin `try-except` local en llamadas externas | Backend, DevOps | Resiliencia de infraestructura — DevOps Architecture define SLAs y observabilidad, Backend implementa el manejo |
| Fallo silencioso de extracción de datos del lead | Backend, AI, Operations | Afecta calidad de datos que AI Architecture produce y que Operations necesitaría poder observar |
| Branch roto de `twilio` | Backend, DevOps | Configuración y despliegue — riesgo de falla de arranque en un ambiente mal configurado |
| Autorización duplicada ~26 veces | Backend, Security, API | Security define el modelo de autorización; API Architecture necesita un mecanismo centralizado para exponer contratos consistentes |
| Data Architecture no implementada aún en código | Backend, Data, Security, API | Backend debe secuenciar su propio roadmap contra las Fases 1-3 de Data Architecture; Security y API heredan las mismas implicancias de Multi-Tenant |
| "Business Rules Engine" no formalizado (solo `asignacion.py`) | Backend, AI | Backend Architecture decide si formaliza un motor genérico; AI Architecture es un consumidor natural si las reglas empiezan a cruzarse con decisiones de IA |
| Preparación Multi-Tenant ausente en sesión/auth | Backend, Security, API | Los tres deben resolver, cada uno en su capa, cómo se propaga la identidad del tenant una vez exista `Negocio` (Data Architecture) |

## Strategic Recommendations

Resumen ejecutivo de los temas donde `MAIEK_AI_BACKEND_ARCHITECTURE.md` debe concentrar el esfuerzo — no son soluciones, son los ejes que la arquitectura objetivo debe resolver:

1. **Separación de capas es el tema de mayor apalancamiento.** Extraer una capa de servicio/negocio de `dashboard.py` desbloquea, en cascada, API First, reduce el riesgo de regresión en el módulo más grande del sistema, y es prerrequisito práctico para que Frontend Architecture tenga algo limpio que consumir.
2. **Resiliencia ante fallas externas debe ser un eje central del diseño, no un detalle de implementación posterior.** Timeouts, manejo de errores local, y una política de degradación explícita (hoy solo existe para fallas de IA) necesitan tratamiento arquitectónico, no parches puntuales.
3. **El protocolo de decisión de IA sigue siendo aspiracional sin un puente técnico real.** La arquitectura objetivo debe definir cómo el AI Engine expone un nivel de confianza consumible, cerrando la brecha entre lo que MPX/MSA ya exigen y lo que el código hace hoy.
4. **La autorización necesita convertirse en mecanismo central antes de que la superficie de rutas siga creciendo.** Cuanto más tarde se resuelva, más caro será migrar los ~26 puntos ya duplicados.
5. **El camino hacia procesamiento desacoplado (Event-Driven) debe quedar preparado, aunque no se resuelva por completo en esta primera versión.** El diseño no debería requerir una reescritura mayor cuando llegue el momento de introducir una cola.
6. **La adopción de las decisiones de Data Architecture necesita secuenciarse explícitamente, no asumirse en paralelo.** Backend Architecture debe declarar en qué fase de su propio roadmap se sincroniza con cada una de las 3 fases ya aprobadas en Data Architecture.

---

*Fin del documento — Approved. Línea base técnica del backend de Maiek AI. Comienza `MAIEK_AI_BACKEND_ARCHITECTURE.md` (arquitectura objetivo) como evolución explícita desde este estado real, siguiendo el ADS, el MSA y Data Architecture — respetando la Regla de herencia arquitectónica (ADS v1.1) para toda decisión ya fijada en esos documentos.*
