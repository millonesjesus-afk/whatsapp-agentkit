# Maiek AI — Current State Assessment: AI Architecture

**Versión 1.0 · Estado: Approved**

| | |
|---|---|
| Documento | Current State Assessment – AI Architecture |
| Proyecto | Maiek AI |
| Versión | 1.0 |
| Estado | **Approved** |
| Fecha de creación | 2026-07-28 |
| Autor | Claude, a pedido de Jesús Millones |
| Fecha de aprobación | 2026-07-28 |
| Última actualización | 2026-07-28 |

## Dependencias

- `MAIEK_AI_SYSTEM_ARCHITECTURE.md` (MSA) Capítulo 6 (AI Engine, Platform Engine), Capítulo 7 (Arquitectura de IA), Capítulo 11 (Constraints — ventana de contexto, costo por llamada).
- `MAIEK_AI_BACKEND_ARCHITECTURE.md` — protocolo de confianza ya decidido (`{respuesta, confianza, razon}`, emitido solo por el AI Engine); este CSA verifica cuánto de eso existe hoy en el código real.
- `MAIEK_AI_API_ARCHITECTURE.md` — contrato interno de plataforma para AI Architecture (Platform Engine, nunca consumidor externo).
- `MAIEK_AI_DATA_ARCHITECTURE.md` — `MemoriaPersistente`, `SugerenciaIA` (entidades objetivo, no implementadas todavía).
- `MAIEK_AI_PRODUCT_EXPERIENCE.md` (MPX) Capítulo 2 (Protocolo de interacción con IA), Capítulo 8 (tres tipos de memoria).
- `MAIEK_AI_ARCHITECTURE_DOCUMENT_STANDARD.md` (ADS) v1.3.

## Consumido por

`MAIEK_AI_AI_ARCHITECTURE.md` (AI Architecture, todavía no construida).

## Control de versiones

| Versión | Fecha | Autor | Descripción |
|---|---|---|---|
| 1.0 (borrador) | 2026-07-28 | Claude | Primera versión — auditoría del comportamiento cognitivo real del agente (`agent/brain.py`, `agent/tools.py`, `config/prompts.yaml`), no solo de su estructura de código. Sin propuestas de cambio. Pendiente de revisión y aprobación. |
| 1.0 | 2026-07-28 | Claude | Aprobado sin reapertura del contenido. El usuario registró 4 observaciones para la evolución del modelo, a incorporar en `MAIEK_AI_AI_ARCHITECTURE.md` (no modifican este CSA): (1) clasificar explícitamente las fuentes de conocimiento del AI Engine (estático, operacional, transaccional, memoria conversacional, contexto temporal, configuración del negocio) — relevante para Multi-Tenant; (2) dejar explícito que el comportamiento actual es una única inferencia enriquecida por recuperación previa, sin planificación iterativa ni ciclos de razonamiento con herramientas; (3) distinguir trazabilidad de prompts vs. trazabilidad de decisiones del AI Engine en Observabilidad; (4) referirse a la segunda llamada como una inferencia especializada en extracción estructurada, no como "un clasificador", para mantener el documento independiente de la implementación concreta. |

## Alcance

Auditoría objetiva de **cómo piensa y decide el agente hoy** — construcción de contexto, prompts, uso de herramientas, frontera entre IA y lógica de negocio, incertidumbre, costo, seguridad y observabilidad — no un inventario de archivos. No repite el análisis estructural ya hecho en el CSA-Backend (flujo del webhook, manejo de errores por capa, autenticación); lo cita donde aplica.

---

## 1. Arquitectura cognitiva actual

**No es un agente con bucle de herramientas — es un pipeline de generación aumentada por recuperación determinística (RAG-lite), de una sola pasada, más una segunda llamada de extracción estructurada.** Claude nunca decide qué información recuperar; el pipeline en Python decide eso antes de invocarlo y se lo entrega ya armado como texto.

**Flujo completo, mensaje real:**
1. Mensaje llega al webhook, se resuelve canal y se recupera historial (`obtener_historial`, hasta 20 mensajes) — ya documentado en CSA-Backend.
2. `generar_respuesta(mensaje, historial, lead, modo)` (`brain.py:181-233`):
   - Si el mensaje está vacío, responde con fallback fijo — **sin tocar el modelo**.
   - Resuelve el system prompt según el modo del canal (sección 3).
   - `_armar_bloques_contexto()` (`brain.py:103-178`) construye el contexto dinámico, en este orden fijo: hora/horario de atención → datos ya conocidos del lead → si hay campaña de origen, promoción prioritaria + variantes de combo → exclusión de códigos promocionales de otras campañas → últimos 2 mensajes del cliente + `interes` del lead + mensaje actual, usados como query de búsqueda en catálogo/base de conocimiento.
   - Los bloques de contexto se anteponen al mensaje del turno, **siempre en el mensaje `user`, nunca en el `system`** — decisión ya deliberada para no romper el prompt caching futuro (no implementado hoy, sección 7).
   - Se llama a Claude (`MODELO_PRINCIPAL`, `max_tokens=1024`, **sin `tools=`, sin `temperature`, sin streaming**) con el historial completo + el mensaje con contexto.
   - Retorna el texto crudo de la respuesta, sin ninguna estructura adicional.
3. Si la llamada fue exitosa, **segunda llamada** — `extraer_datos_lead()` (`brain.py:236-291`), modelo económico, sin contexto de catálogo, pide un JSON de 6 campos a partir del último intercambio. El parseo es manual (`removeprefix("\`\`\`json")`), con `try/except` que retorna `{}` en silencio ante cualquier falla.
4. El resultado de la extracción actualiza el `Lead` — es la única vía por la que la conversación en lenguaje natural se convierte en datos estructurados que gobiernan el panel.

## 2. Gestión del contexto

- **Memoria de conversación**: el historial ya guardado (`memory.py`, límite de 20 mensajes por consulta) — se pasa **completo** a Claude en cada llamada, sin truncamiento adicional propio de `brain.py` más allá de ese límite ya fijado en la capa de datos.
- **Memoria persistente**: no existe como concepto separado — vive **mezclada dentro de 3 campos del propio `Lead`** (`nombre`, `interes`, `paso_flujo`), actualizados por la segunda llamada de extracción. No hay ninguna entidad `MemoriaPersistente` (Data Architecture la define como objetivo, no implementada).
- **Contexto dinámico**: recalculado en cada turno desde cero (hora, promoción, catálogo relevante) — nada se cachea entre turnos salvo el catálogo completo en memoria de proceso (`_catalogo_cache`, `tools.py:30`).
- **Recuperación de información**: **keyword/substring matching simple, sin embeddings ni búsqueda semántica**. `buscar_productos()` puntúa por coincidencia literal de marca/sub-tipo/tipo dentro del mensaje (`tools.py:76-124`); `buscar_en_knowledge()` cuenta palabras compartidas de 4+ letras por párrafo (`tools.py:230-258`). Ningún vector store, ningún modelo de embeddings en el proyecto.

## 3. Construcción de prompts

- **System Prompt**: ~140 líneas (`config/prompts.yaml`), **completamente estático** entre llamadas — identidad de Gabi, contexto de negocio (Gaso+/Cálidda), objetivo comercial, flujo de atención en 8 pasos, presentación progresiva de precio/financiamiento, checklist de validación de 2 puntos, reglas de estilo, cuándo derivar a un asesor, una sección explícita de **restricciones** ("Restricciones — NUNCA hagas esto", 8 ítems), uso del contexto inyectado, filosofía comercial. Dos versiones resueltas por modo de canal: "pruebas" (siempre el archivo) y "producción" (lo promovido a la tabla `Configuracion`, con fallback al archivo si nunca se promovió nada).
- **Contexto inyectado**: siempre en el mensaje `user`, concatenado como texto plano antes del mensaje real del cliente, con un prefijo literal `"Mensaje del cliente: "`.
- **Instrucciones**: viven como prosa natural dentro del system prompt — no hay ninguna regla estructurada/machine-readable; el modelo debe seguirlas por instrucción, no por restricción técnica.
- **Restricciones**: declaradas explícitamente en el prompt (ej. "Nunca digas que un cliente 'califica'", "Nunca apruebes o rechaces financiamiento") — pero son restricciones de **comportamiento esperado**, sin ninguna validación posterior de que la respuesta generada las respetó.
- **Variables dinámicas**: solo en los bloques de contexto (sección 2) — el system prompt en sí no tiene placeholders ni variables, es texto fijo.

## 4. Uso de herramientas

**No hay tool-calling de la API de Claude** (confirmado: sin parámetro `tools=` en ninguna llamada) — las "herramientas" son funciones Python que el pipeline ejecuta **siempre**, antes de invocar al modelo, decididas por lógica determinística, no por el modelo:

| Herramienta | Qué aporta | Limitación real |
|---|---|---|
| `buscar_productos` / `obtener_contexto_relevante` | Productos del catálogo (CSV) relacionados al mensaje | Matching por substring — sin sinónimos ni tolerancia a variaciones de escritura |
| `buscar_en_knowledge` | Fragmentos de políticas/contrato/speech relacionados | Igual — coincidencia de palabras, no comprensión semántica |
| `obtener_estado_horario_atencion` | Hora real de Lima, si hay asesores disponibles ahora | Ninguna relevante — es determinístico y correcto |
| `resolver_promo` / `resolver_familia_promo` / `obtener_codigos_promocionales_activos` (`campanas.py`) | Promoción vigente si el lead viene de una campaña, y exclusión de precios reservados a otras campañas | Depende de que la campaña ya esté correctamente asociada al lead antes de este punto |

Claude nunca "elige" invocar una herramienta — todo el contexto ya viene resuelto en el mensaje que recibe. No hay ninguna herramienta expuesta directamente al modelo.

## 5. Modelo de razonamiento — frontera entre IA y lógica de negocio

**La IA principal solo genera texto conversacional — nunca produce estructura, nunca decide un flujo, nunca ejecuta una acción.** Todo lo estructural lo decide Python determinista o la segunda llamada de extracción (un clasificador, no un tomador de decisiones):

| Decisión | Quién la toma realmente |
|---|---|
| Qué decir, cómo fraseear, cuándo preguntar el nombre | La IA principal (texto libre, sin garantía técnica) |
| Si Gabi responde o el mensaje se ignora (gate de asesor asignado) | Backend, Python determinista — la IA ni siquiera es invocada |
| Escalamiento a humano por fallas técnicas | Backend, contador hardcodeado — no involucra juicio de la IA |
| Asignación automática de un lead a un asesor | Backend (`asignacion.py`), reglas de nivel/carga — no la IA |
| Detección de campaña de origen | Backend (`campanas.py`), matching de patrones — no la IA |
| `paso_flujo` que gobierna el panel y la asignación | La segunda llamada de IA (extracción) — pero es un **clasificador que interpreta lo ya dicho**, no un razonador que decide el siguiente paso |

La frontera es clara en el código, pero **no está formalizada como contrato ni verificada técnicamente** — se sostiene porque el pipeline está escrito así, no porque exista una barrera que impida que la IA "decida" algo fuera de su rol.

## 6. Gestión de incertidumbre

- **Estado actual del mecanismo de confianza**: **no existe.** Ningún score de confianza, ninguna salida estructurada — la primera llamada retorna únicamente texto libre.
- **Limitaciones**: el modelo puede sonar igual de seguro respondiendo algo que sí está en el contexto que algo que no — no hay forma de distinguirlo desde el sistema.
- **Handoff a humano**: dos mecanismos reales, **ninguno basado en incertidumbre del modelo**: (1) el gate ya existente si hay un asesor asignado, (2) el escalamiento por fallas *técnicas* repetidas. El propio system prompt **instruye** a Gabi a derivar en casos de negocio (DNI ya dado, cotización personalizada, reclamo, etc.) — pero es una instrucción de texto, sin verificación técnica de que se cumplió.
- **Casos ambiguos**: el prompt tiene instrucciones extensas y cuidadas para casos de negocio ambiguos (cliente no titular, cliente sin DNI a la mano) — pero, igual que las restricciones, dependen enteramente de que el modelo las siga bien, sin ningún mecanismo de verificación posterior.

## 7. Costo y eficiencia

- **Llamadas al modelo**: 2 por mensaje procesado normalmente (respuesta + extracción). Mensajes "echo", no soportados, o bloqueados por el gate de asesor **no** llaman a ningún modelo.
- **Tamaño de contexto**: el system prompt completo (~9KB) se reenvía en **cada** llamada — sin prompt caching activo pese a estar diseñado explícitamente para permitirlo (comentario propio en `brain.py:53-55`). El historial (hasta 20 mensajes) se envía completo, sin límite de tokens propio dentro de `brain.py`.
- **Oportunidades de caching**: la más clara y ya autodocumentada en el propio código — el system prompt estático es un candidato directo a *prompt caching* de Anthropic, no implementado.
- **Costos de inferencia**: ya hay una decisión consciente de costo diferenciada — `MODELO_PRINCIPAL` (Sonnet, más caro) solo para la respuesta al cliente; `MODELO_EXTRACCION` (Haiku, económico) para la extracción — fortaleza real, no una omisión.

## 8. Seguridad del agente

- **Riesgo de prompt injection**: **presente y no mitigado estructuralmente.** El mensaje del cliente se concatena como texto plano junto con el contexto (catálogo, promoción) en el mismo bloque del turno `user`, sin ningún delimitador estructurado. La única defensa es la instrucción del propio prompt ("nunca digas que el cliente califica") — no hay separación técnica que impida que un mensaje del cliente intente alterar el comportamiento.
- **Separación entre instrucciones y datos**: parcial. El system prompt SÍ está técnicamente separado del mensaje `user` (dos campos distintos de la API) — buena base. Pero **dentro** del mensaje `user`, contexto de confianza (catálogo, promoción) e input no confiable (el mensaje real del cliente) conviven en el mismo texto plano, sin aislamiento.
- **Protección del contexto**: los datos del lead (`nombre`, `interes`) se reinyectan en turnos futuros sin ninguna sanitización — si un campo llegara a contener texto adversarial de un turno anterior, se reintroduciría sin filtrar.
- **Exposición de herramientas**: no aplica como superficie de ataque hoy — precisamente porque no hay tool-calling real, no existe una herramienta que un prompt injection pudiera intentar invocar directamente.

## 9. Observabilidad

- **Qué métricas existen hoy**: casi ninguna estructurada — solo un log de tokens de entrada/salida por respuesta exitosa (`brain.py:228`) y errores/warnings dispersos, mismo patrón disperso ya diagnosticado en CSA-Backend.
- **Qué decisiones pueden auditarse**: ninguna de forma sistemática. No queda registro de qué contexto exacto recibió el modelo en un turno dado, ni de si mencionó una promoción, ni del resultado crudo de una extracción — solo el estado final en el `Lead`. Es imposible reconstruir "por qué Gabi dijo X" después del hecho.
- **Qué información falta**: exactamente lo que Data Architecture ya anticipó — `SugerenciaIA` (registro de sugerencias/decisiones con contexto y resultado), un nivel de confianza explícito, costo agregado por conversación (hoy solo por llamada individual en el log).

## 10. Preparación para la arquitectura objetivo (MSA, Backend, API)

| Decisión ya objetivo | Estado real hoy |
|---|---|
| Nivel de confianza explícito (MSA Cap. 7, Backend Architecture) | Ausente — solo texto libre, sin `tools=` ni JSON Schema forzado en la llamada principal |
| `ServicioInteligencia` como único punto de acceso (Backend Architecture) | De facto cumplido — `brain.py` ya es el único módulo que llama a Claude — falta formalizarlo como interfaz, no como comportamiento |
| Contrato interno de plataforma (API Architecture) | No existe ni siquiera como interfaz explícita — `brain.py` se importa directo desde `main.py`, sin ninguna capa intermedia |
| `MemoriaPersistente` / `SugerenciaIA` (Data Architecture) | No implementadas — memoria persistente vive mezclada en `Lead` |
| Límite de llamadas de IA por mensaje (Constraint, MSA Cap. 11 / Backend / API) | Ya en 2 hoy — la futura señal de confianza debe venir en la misma llamada de respuesta, nunca una tercera |

---

## Fortalezas

- Separación limpia entre `system` (estático) y `user` (dinámico) — decisión ya correcta y explícitamente pensada para habilitar prompt caching futuro.
- Costo diferenciado por tarea: modelo completo solo para la respuesta al cliente, modelo económico para la extracción.
- Frontera real y consistente entre lo que decide la IA (texto) y lo que decide el backend (flujo, asignación, escalamiento) — aunque no esté formalizada, el código la respeta en la práctica.
- `obtener_estado_horario_atencion` resuelve correctamente un problema real (el modelo no tiene reloj propio) de forma simple y determinística.
- El system prompt es explícito, cuidado y con restricciones de negocio bien pensadas (financiamiento, honestidad, no presión) — la calidad del contenido del prompt es alta, el problema es la ausencia de verificación técnica de que se cumple.

## Decisiones heredadas del MVP (razonables para la etapa, a reevaluar)

- Sin tool-calling / function calling real — retrieval determinístico en Python es más simple y barato de construir para un catálogo de un solo negocio.
- Sin prompt caching implementado pese a estar preparado — el ahorro no justificaba la complejidad a bajo volumen.
- Keyword/substring matching en vez de embeddings — catálogo pequeño y acotado, suficiente hasta ahora.
- Sin `SugerenciaIA` ni auditoría formal de decisiones de IA — no había necesidad real de auditoría en la etapa de un solo negocio y equipo pequeño.
- Extracción sin JSON Schema forzado, solo instrucción de texto — más rápido de construir, funciona la mayoría de las veces.

## Deuda técnica (sin justificación de etapa)

- **Ninguna separación estructural entre contexto de confianza y mensaje del cliente** dentro del bloque `user` — el costo de delimitar ambos con una estructura mínima es bajo, y el riesgo (negocio de financiamiento) es real.
- **Ninguna validación posterior de que la respuesta respeta las restricciones críticas del prompt** — no es solo deuda técnica, es un riesgo de negocio/compliance concreto (financiamiento, aprobación).
- **Sin límite explícito de tamaño de contexto ensamblado** antes de enviarlo al modelo — omisión de robustez, no una decisión de simplicidad.
- **Fallo de extracción completamente silencioso**, sin ningún registro auditable de qué se intentó y por qué falló — ya señalado en CSA-Backend, reconfirmado acá desde el ángulo cognitivo (el `paso_flujo` que gobierna el panel puede quedar obsoleto sin que nadie lo note).

## Desviaciones respecto al MSA, Backend, API y Data Architecture

- **Protocolo de confianza estructurado (MSA Cap. 7, Backend Architecture)** — es la desviación central: no hay tool-calling ni JSON Schema forzado en la llamada principal, solo texto libre. Confirma con detalle técnico el hallazgo ya anticipado en el CSA-Backend.
- **`ServicioInteligencia` / contrato interno de plataforma (Backend, API Architecture)** — no son desviaciones, son **sincronización pendiente**: ambos son arquitectura objetivo todavía no implementada en código, mismo criterio ya aplicado en los CSA anteriores.
- **`MemoriaPersistente` / `SugerenciaIA` (Data Architecture)** — mismo criterio: objetivo aprobado, no implementado; la memoria persistente real hoy vive mezclada en `Lead`, sin separación de los tres tipos de memoria de MPX Cap. 8 (el contexto temporal de una interacción sí está correctamente implementado de forma implícita en `_armar_bloques_contexto`, sin persistirse).

## Riesgos detectados

1. Prompt injection sin mitigación estructural — riesgo real en un negocio que maneja financiamiento.
2. Ninguna verificación de que las restricciones críticas del prompt (nunca aprobar, nunca decir "calificas") se cumplen en la práctica — riesgo de negocio, no solo técnico.
3. Costo de contexto creciente sin control — system prompt completo reenviado sin caching en cada llamada.
4. Historial completo sin límite de tokens propio en `brain.py` — riesgo de exceder la ventana de contexto en conversaciones largas.
5. Extracción silenciosa — el dato que gobierna el panel y la asignación puede quedar desactualizado sin ninguna alerta.
6. Catálogo cacheado en memoria de proceso sin invalidación — un cambio al CSV no se refleja sin reiniciar el proceso.

## Architectural Readiness

| Dimensión | Madurez actual | Nota |
|---|---|---|
| Protocolo de confianza | **Ausente** | Sin score estructurado en la salida del modelo |
| Separación instrucciones/datos | **Débil** | Contexto y mensaje del cliente conviven sin delimitador dentro del turno `user` |
| Tool-calling / function calling | **Ausente (por diseño)** | Patrón RAG-lite determinístico, no agéntico |
| Auditabilidad de decisiones de IA | **Ausente** | Ningún registro de qué contexto vio el modelo ni qué decidió, más allá del resultado final |
| Eficiencia de contexto (caching) | **Ausente, pese a estar preparado** | System prompt estático listo para *prompt caching*, sin activar |
| Recuperación de información | **Básica, funcional** | Keyword matching, sin embeddings — suficiente al catálogo actual |
| Frontera IA / lógica de negocio | **Sólida en la práctica, no formalizada** | El código la respeta, pero no hay contrato ni verificación técnica |
| Seguridad ante prompt injection | **Débil** | Sin mitigación estructural más allá de la instrucción del prompt |
| Costo diferenciado por tarea | **Sólido** | Modelo económico para extracción, completo solo para respuesta |

**Conclusión de preparación:**

- **MVP (uso actual, un solo negocio):** **Listo.** El pipeline sostiene la operación real hoy — las decisiones de la sección anterior fueron tradeoffs correctos para esta etapa.
- **Crecimiento (más volumen, mismo negocio):** **Parcialmente listo.** El costo de contexto sin caching y la ausencia de límite de tokens se vuelven relevantes antes que cualquier otra cosa — no hay un colapso repentino, pero sí una curva de costo que crece sin control.
- **SaaS multiempresa:** **No listo.** El system prompt es enteramente específico de un negocio (Gaso+/Cálidda), hardcodeado como texto fijo — no hay ninguna noción de "un prompt por tenant" ni de aislamiento de conocimiento entre negocios.

## Priorización de remediación

| Prioridad | Ítem | Por qué |
|---|---|---|
| **P1** | Protocolo de confianza estructurado | Bloqueante ya declarado en Backend/API Architecture; sin esto, Explainability First (MPX) sigue siendo aspiracional |
| **P1** | Separación estructural entre contexto de confianza y mensaje del cliente | Mitiga prompt injection en un negocio con financiamiento — riesgo real, no hipotético |
| **P1** | Verificación/auditoría de que las restricciones críticas del prompt se cumplen | Riesgo de negocio/compliance, no solo técnico |
| **P2** | Activar prompt caching | Ya preparado en el código, solo falta implementarlo — ahorro de costo directo |
| **P2** | Registro auditable de extracciones (equivalente a `SugerenciaIA`) | Cierra la falta de trazabilidad ya señalada |
| **P2** | Límite explícito de tamaño de contexto ensamblado | Evita exceder la ventana de contexto en conversaciones largas |
| **P3** | Evaluar búsqueda semántica/embeddings | Sin evidencia hoy de que el keyword matching sea insuficiente |
| **P3** | Invalidación de caché de catálogo | Bajo impacto real al volumen actual |
| **P3** | Tool-calling formal | Solo si el catálogo/las reglas crecen en complejidad, con evidencia |

## Architectural Decision Impact

| Hallazgo | Arquitecturas afectadas | Por qué |
|---|---|---|
| Sin protocolo de confianza estructurado | AI, Backend, API | AI Architecture define cómo se emite; Backend la consume (ya decidido); API define el contrato interno que la transporta |
| Prompt injection sin mitigación | AI, Security | Security Architecture define la política; AI Architecture implementa la separación estructural |
| Sin auditoría de decisiones de IA | AI, Data, DevOps/Operations | Data Architecture ya definió `SugerenciaIA`; DevOps/Operations necesitan esa trazabilidad para observabilidad real |
| Sin prompt caching activo | AI, DevOps | Impacto directo de costo — DevOps Architecture es quien mediría y alertaría sobre ese costo |
| System prompt hardcodeado de un solo negocio | AI, Data | Bloqueante para Multi-Tenant — Data Architecture ya definió `negocio_id`, AI Architecture debe decidir cómo el prompt se vuelve específico por tenant |

## Strategic Recommendations

1. **El protocolo de confianza estructurado es la decisión de mayor apalancamiento de este documento.** Sin él, ninguna de las decisiones ya tomadas en Backend y API Architecture sobre cómo consumir esa señal tiene de dónde salir.
2. **La seguridad del prompt (injection, separación instrucciones/datos) merece tratamiento arquitectónico explícito, no un parche.** El negocio actual (financiamiento) ya tiene exposición real, no hipotética.
3. **La auditabilidad de decisiones de IA y el prompt caching pueden resolverse juntos** — ambos requieren capturar de forma estructurada qué se le envió al modelo y qué respondió, con distinto propósito (trazabilidad vs. costo) pero la misma captura de datos como base.
4. **La multiplicación de llamadas de IA está bien gobernada hoy (2 por mensaje, con costo diferenciado) — la arquitectura objetivo debe preservar esa disciplina**, no agregar una tercera llamada solo para transportar el nivel de confianza.
5. **El system prompt hardcodeado a un solo negocio es una brecha real hacia Multi-Tenant** que ningún documento anterior había hecho explícita con este nivel de detalle — vale la pena que AI Architecture la resuelva desde el diseño, no como un parche posterior.

---

*Fin del documento — borrador completo, pendiente de tu revisión y aprobación. Una vez aprobado, se construye `MAIEK_AI_AI_ARCHITECTURE.md` (arquitectura objetivo) como evolución explícita desde este estado real, siguiendo el ADS, el MSA, Backend Architecture y API Architecture.*
