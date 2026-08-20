# MAIEK AI — Experience Flows (Repositorio de Product Design)

> **Qué es este documento.** Repositorio de trabajo **durable** de la fase de Product Design:
> Journey Maestro, Inventario Maestro de recorridos, y las tablas de Experience Flow (EXP),
> User Flow (UF) y Screen Contract (SCR) de cada recorrido, con IDs permanentes y trazables.
>
> **Qué NO es este documento.** No es un documento de gobernanza ni reemplaza a ningún Approved
> existente (`MAIEK_AI_PRODUCT_PATTERNS.md`, `MAIEK_AI_PRODUCT_ARCHITECTURE.md`,
> `MAIEK_AI_PRODUCT_EXPERIENCE.md`, `MAIEK_AI_UX_BLUEPRINT.md`, `MAIEK_AI_IMPLEMENTATION_ROADMAP.md`).
> Es un artefacto funcional de Product Design, del mismo tipo que ya existía como propuesta desde
> el propio historial recuperado (ver nota de origen abajo) — nunca se había persistido a archivo.
>
> **Por qué existe recién ahora (2026-08-09).** Todo el contenido de este documento vivió
> exclusivamente en el historial de conversación de una sesión anterior. Cuando esa sesión fue
> comprimida (context compaction), el contenido dejó de estar disponible en el contexto activo y,
> como nunca se había guardado en un archivo, pareció "perdido". Se recuperó leyendo el transcript
> crudo de la sesión original (`7684292f-...jsonl`) línea por línea — un recurso que no se había
> consultado hasta que el usuario preguntó explícitamente si existía acceso al "historial completo
> de conversaciones anteriores", distinto de memoria persistida o de archivos. Ver
> `project_ux_blueprint_completado_fase_product_design.md` (memoria) para el proceso de
> remediación acordado: de ahora en adelante, todo artefacto con IDs permanentes se persiste a
> archivo apenas se aprueba, sin esperar a un "segundo o tercer" caso de uso.
>
> **Convención de IDs** (`MAIEK_AI_IMPLEMENTATION_ROADMAP.md` §2.2): `EXP-NN`, `UF-NN`, `SCR-NN`
> son globales y consecutivos entre todos los recorridos — nunca se reinician, nunca se
> renumeran. Un recorrido que reutiliza pantallas ya construidas cita los IDs existentes en vez
> de crear nuevos.
>
> **Numeración doble — leer antes de usar este documento.** Este documento distingue dos
> numeraciones que **no coinciden entre sí**: la numeración **histórica** (#1-9, ver Sección A,
> asignada en la sesión original) y la numeración **post-compactación** (#1-7, la que se ha
> usado en las sesiones recientes: #1 Lead→Close Won, #2 Conversación→Lead, #3 Inicio→Acción
> priorizada, #5 Campaña→Lead→Pipeline, #6 CRM/Pipeline→Analítica, #7 Conversaciones→Catálogo).
> La Sección D (Reconciliación) documenta esto sin resolverlo.

---

## A. Inventario Maestro Histórico (recuperado literalmente)

Recuperado del transcript crudo, línea 35249 (tabla base) y línea 35270 (reclasificación
Tipo/Nivel), sesión `7684292f-47eb-4a30-a90c-09f7cc5785e9`. Cita literal, sin reconstrucción.

> **Corrección de precisión.** El Inventario Maestro original contempla **9 recorridos**, no 10.
> La referencia previa a "los 10 recorridos originales" (usada en un mensaje del usuario antes de
> esta recuperación) fue una imprecisión de memoria — la evidencia literal recuperada del
> transcript muestra 9 filas, sin ningún indicio de una décima.

### A.1 — Tabla base

| # | Recorrido | Módulos que atraviesa | Disparador | Resultado | Evidencia en el corpus |
|---|---|---|---|---|---|
| 1 | **Lead → Close Won** | Conversaciones/Campañas → Agentes IA (Copiloto) → CRM/Pipeline → Catálogo & Comercial | Un contacto entrante o un lead de campaña | Lead en estado "ganado" | Product Patterns Cap. 2 §8, Cap. 5 §8, Cap. 6 §8 ("escriben contra el mismo modelo de Lead"), Cap. 6 §1 ("hasta que se convierte en un resultado: ganado, perdido, en curso") |
| 2 | Conversación → Lead generado | Conversaciones → CRM/Pipeline | Un mensaje entrante revela intención de compra | Lead creado o actualizado | Product Patterns Cap. 2 §8 ("alimenta al patrón de CRM/Pipeline... cuando una conversación genera o actualiza un lead") |
| 3 | Inicio → Acción priorizada (Asesor) | Inicio → Conversaciones o CRM/Pipeline | Login o retorno a la plataforma | Conversación o Lead atendido | Product Patterns Cap. 3 §8; UX Blueprint Cap. 2 §2.4 |
| 4 | Inicio → Analítica (Admin/Supervisor) | Inicio → Analítica | Login o retorno a la plataforma | Pregunta de negocio resuelta | Product Patterns Cap. 3 §8, Cap. 4 §8 |
| 5 | Campaña → Lead atribuido → Pipeline | Campañas → CRM/Pipeline → Analítica | Un lead ingresa desde una campaña activa | Lead con origen atribuido, campaña medible | Product Patterns Cap. 7.B §8 ("alimenta a CRM/Pipeline con la atribución de origen... consultado por Analítica") |
| 6 | Reasignación de Lead | Equipo & Organización → CRM/Pipeline | Un supervisor reasigna carga de trabajo | Lead con nuevo asesor, historial intacto | Product Patterns Cap. 7.C §8; UX Blueprint Cap. 2 §2.4 |
| 7 | Cotización dentro de una conversación o Lead | Catálogo & Comercial → Conversaciones / CRM/Pipeline | Un cliente pregunta por precio o condición | Ficha de producto compartida o adjunta | Product Patterns Cap. 7.A §8 |
| 8 | Notificación → Acción específica | Notificaciones → CRM/Pipeline | Una alerta de Lead de alto valor sin respuesta | Lead atendido a tiempo | UX Blueprint Cap. 2 §2.4 (patrón de Notificaciones todavía no existe) |
| 9 | Autenticación → Inicio | Autenticación → Inicio | Apertura de sesión | Usuario en su Inicio, según rol | UX Blueprint Cap. 10 (área sin patrón todavía, pero primer recorrido cronológico de cualquier sesión) |

**Nota de honestidad metodológica (literal del historial):** *"no existe telemetría real de uso
todavía (`MAIEK_AI_OPERATIONS_ARCHITECTURE.md` ya registró esta brecha: 'sin métrica de calidad
de atención'). La frecuencia que uso [para priorizar] es una inferencia razonada, no una
medición — basada en cuántos otros patrones dependen de cada recorrido (densidad de conexión,
evidencia real) y en la narrativa operativa ya aprobada en MDL Cap. 0 ('Un día completo con
Maiek'), no en datos de producción."*

### A.2 — Priorización (recuperada, parcial — top 4 completos, resto no localizado en la ventana consultada)

| Prioridad | Recorrido | Por qué |
|---|---|---|
| **1** | Lead → Close Won (#1) | "Es el único recorrido al que confluyen directamente 6 de los otros 8 (Conversaciones, Copiloto, Campañas, Catálogo, Equipo, Analítica) — máxima densidad de conexión de todo el mapa. Es también el resultado de negocio explícito que ya declaramos en la corrección del UX Blueprint Cap. 2 ('todo recorrido debe acercar al usuario al objetivo principal de la tarea'). Materializa 'Conecta → Comprende → Cierra' de punta a punta." |
| 2 | Conversación → Lead generado (#2) | "Es el primer tramo de #1 — se puede construir como su propio User Flow o como la primera etapa del flujo #1. Decisión a tomar al hacer el Gap Analysis de #1." |
| 3 | Inicio → Acción priorizada (#3) | "Recorrido diario de mayor frecuencia estimada (es literalmente el punto de entrada de cada sesión para el rol Asesor), pero de impacto de negocio indirecto — orienta hacia #1, no lo reemplaza." |
| 4 | Campaña → Lead atribuido (#5) | *(texto cortado en la ventana de extracción consultada — `NO RECUPERADO — NO ENCONTRADO EN LA FUENTE CONSULTADA` para el resto de esta fila y las prioridades 5-9)* |

### A.3 — Reclasificación Tipo / Nivel (línea 35270, literal)

| # | Recorrido | Tipo de User Flow | Nivel |
|---|---|---|---|
| 1 | Lead → Close Won | **Business Journey** | **Journey** |
| 2 | Conversación → Lead generado | Task Flow | Flow |
| 3 | Inicio → Acción priorizada (Asesor) | Navigation Flow | Flow |
| 4 | Inicio → Analítica (Admin/Supervisor) | Navigation Flow | Flow |
| 5 | Campaña → Lead atribuido → Pipeline | Business Journey | Flow |
| 6 | Reasignación de Lead | Task Flow | Task |
| 7 | Cotización dentro de conversación/Lead | Task Flow | Task |
| 8 | Notificación → Acción específica | Event Flow | Flow |
| 9 | Autenticación → Inicio | Navigation Flow | Flow |

**Nota de coherencia con el UX Blueprint (literal):** *"El Capítulo 2 define 'recorrido' como algo
que siempre cruza módulos — eso sigue siendo válido para todos los ítems de Nivel Flow o
superior. Los dos ítems de Nivel Task (#6, #7) también cruzan módulos técnicamente, pero son lo
bastante acotados y atómicos como para no requerir el aparato completo de un Flow (matriz de
continuidad, checklist del Cap. 11) — igual quedan sujetos al presupuesto cognitivo (Cap. 4-5) y
a la co-localización (Cap. 3), solo que a una escala menor. Esta distinción de Nivel no
contradice el Cap. 2 — lo afina. Solo el #1 es, en sentido estricto, un Journey: los demás son
Flows o Tasks que ocurren dentro de él o en su periferia."*

---

## B. Journey Maestro de Maiek AI

Recuperado literalmente en dos versiones consecutivas de la misma sesión: un borrador (v1, línea
35270) y la versión refinada y **aprobada** (v2, línea 35283) que se usó para lanzar el Gap
Analysis del recorrido #1. No hay una tercera versión "construida posteriormente" — ambas son
históricas, dentro de la misma sesión original.

### B.1 — v1 (borrador, línea 35270)

**Definición y alcance.** *"El recorrido íntegro que atraviesa una oportunidad comercial desde
que un cliente potencial hace primer contacto hasta que esa oportunidad se resuelve — ganada o
perdida. Es el único Journey de nivel más alto del inventario; todo lo demás son Flows o Tasks
que viven dentro de él o lo asisten desde afuera."*

**Actores** (literal):
- **Cliente** — externo, nunca opera la plataforma directamente; interactúa vía canal de mensajería.
- **Asesor** — humano, responsable de avanzar el Lead.
- **Supervisor** — reasigna, monitorea el conjunto.
- **Copiloto IA** — agente con capacidad de acción acotada por Human Decision Gate (Product Patterns Cap. 8); nunca reemplaza al Asesor (Concepto 6, UX Blueprint Cap. 1).
- **Administrador** — configura el entorno, no participa activamente del Journey salvo en Equipo & Organización o Canales.

**Etapas (v1, 5 etapas):**

| Etapa | Qué ocurre | Módulos involucrados | Principio Framework |
|---|---|---|---|
| 1. Primer Contacto | El cliente escribe o completa un formulario de campaña | Conversaciones, Campañas | **Conecta** |
| 2. Comprensión | El sistema entiende la intención, resume, prioriza | Conversaciones, Agentes IA (Copiloto) | **Comprende** |
| 3. Conexión con un Asesor | Se crea o actualiza el Lead; un humano se involucra | CRM/Pipeline | **Conecta** |
| 4. Avance | El Lead se trabaja: se cotiza, se reasigna si hace falta, la conversación continúa | Catálogo & Comercial, Equipo & Organización, Conversaciones | **Comprende** (continua) |
| 5. Cierre | El Lead llega a un resultado | CRM/Pipeline | **Cierra** |

**Mapa del inventario dentro del Journey (v1, literal):**

| Etapa | Recorridos del inventario que la componen |
|---|---|
| 1 | Tramo inicial de #1; #5 (Campaña → Lead atribuido) |
| 2 | #2 (Conversación → Lead generado) |
| 3 | #3 (Inicio → Acción priorizada, Asesor) |
| 4 | #6 (Reasignación), #7 (Cotización) |
| 5 | Tramo final de #1 |
| Periferia de soporte (no secuenciales, observan/reaccionan al Journey) | #4 (Inicio → Analítica), #8 (Notificación → Acción), #9 (Autenticación → Inicio) |

**Qué no gobierna este Journey Maestro (literal, parcial):** *"No redefine los estados técnicos
del Lead — sigue siendo dominio exclusivo de Product Patterns Cap. 6..."* — el resto de esta
lista quedó `NO RECUPERADO — NO ENCONTRADO EN LA FUENTE CONSULTADA` en la ventana de extracción
usada.

### B.2 — v2, refinada y APROBADA (línea 35283) — versión vigente

Cambios respecto a v1 (literal): *"Etapa 3 (antes 'Conexión con un Asesor') → 'Inicio de
Gestión'. Descarté 'Asignación Inteligente': implicaría una capacidad de IA de ruteo automático
que no encontré declarada en MPA §7 (capacidades exclusivas de IA) — no quiero nombrar una etapa
con una capacidad que el corpus todavía no confirma que existe."* / *"Etapa 4 (antes 'Avance') →
ajusté tu sugerencia 'Desarrollo del Lead' a 'Desarrollo de la Oportunidad', para quedar
consistente con el reencuadre... ya no es un Lead lo que se desarrolla, es la oportunidad."*
Se agrega una sexta etapa, Aprendizaje (Learning Loop), justificada así: *"tiene anclaje real...
`MAIEK_AI_PRODUCT_EXPERIENCE.md` Cap. 10 (Medición de experiencia) y Cap. 11 (Product Experience
Governance) ya definen exactamente este mecanismo — evidencia que alimenta gobernanza, nunca un
gatillo automático... La etapa de Aprendizaje no inventa un mecanismo nuevo — es la aplicación de
ese mecanismo ya existente al cierre de cada oportunidad."* Nota explícita: *"esta etapa no es
parte de la experiencia del cliente (el cliente ya no está presente) — es la etapa donde Asesor,
Supervisor y la plataforma capitalizan el resultado."*

**Journey Maestro de Maiek AI — versión refinada (6 etapas, aprobada):**

| # | Etapa | Objetivo de la etapa | Módulos | Framework |
|---|---|---|---|---|
| 1 | Primer Contacto | Capturar la intención del cliente en el primer punto de entrada, sin fricción | Conversaciones, Campañas | **Conecta** |
| 2 | Comprensión | Convertir una señal de intención dispersa en entendimiento accionable — qué quiere el cliente y qué tan listo está | Conversaciones, Agentes IA (Copiloto) | **Comprende** |
| 3 | Inicio de Gestión | Formalizar la intención comprendida como oportunidad de negocio real, con un responsable humano asignado | CRM/Pipeline | **Conecta** |
| 4 | Desarrollo de la Oportunidad | Avanzar la oportunidad hacia una decisión, resolviendo lo que el cliente necesita para decidir | Catálogo & Comercial, Equipo & Organización, Conversaciones | **Comprende** (continua) |
| 5 | Cierre | Convertir la oportunidad trabajada en un resultado de negocio explícito, sin ambigüedad | CRM/Pipeline | **Cierra** |
| 6 | Aprendizaje (Learning Loop) | Capitalizar cada resultado, ganado o perdido, como evidencia que mejora la comprensión de la intención en el próximo Primer Contacto | Analítica, Agentes IA | *(cierra el ciclo hacia Conecta)* |

**Hallazgo honesto registrado en el propio historial, sin resolver:** *"ninguno de los 9
recorridos del inventario cubre la Etapa 6. No propongo agregar uno ahora — la Etapa 6 recién va
a tener evidencia real una vez que el Flow #1 esté construido y en uso (mismo criterio Evidence
over Opinion). Queda anotado para revisar el inventario después."* Este documento no resuelve
ese pendiente — se traslada tal cual a la Sección D.

---

## C. Experience Flow / User Flow / Screen Contract recuperados por recorrido

### C.1 — Recorrido histórico #1 — "Lead → Close Won" (EXP-01→EXP-05, UF-01→UF-05+UF-04b, SCR-01→SCR-05+SCR-04b)

Recuperación **completa** para EXP y UF; **completa en campos 1-9** para todos los SCR, y
**parcial en campos 10-14** (ver nota al final de C.1).

**Principio rector del Experience Flow (literal, línea 35319):**
> *"Cada paso debe reducir la incertidumbre del usuario y aumentar progresivamente su claridad y
> confianza hasta llegar a una decisión."*
> Síntesis observable de Explainability First (MPX Cap. 2), Comprensión Previa (UX Blueprint Cap.
> 1), Building Trust (MPX Cap. 6) y La Siguiente Mejor Decisión (UX Blueprint Cap. 3) — no
> introduce autoridad nueva, se apoya en la ya existente.

**Experience Flow — Lead → Close Won (v3, cerrado):**

| ID | Paso | Actor principal / soporte | Sentir | Comprender | Necesidad Cognitiva | Lograr | Riesgo UX | Criterio de éxito |
|---|---|---|---|---|---|---|---|---|
| **EXP-01** | Primer Contacto | Cliente / Gabi | Escuchado de inmediato, sin fricción | Que su mensaje fue recibido y alguien va a ocuparse | Certeza de que el contacto quedó registrado | Sentir que la entrada fue simple y humana | Silencio percibido | En prueba de usabilidad, el cliente simulado confirma sin que se le pregunte que sintió una señal de recepción en los primeros segundos |
| **EXP-02** | Comprensión | Asesor / Copiloto IA | Calma y confianza, no parte de cero | Qué quiere el cliente y por qué merece atención ahora | Certeza suficiente para reconocer una oportunidad real sin releer todo el historial | Pasar de incertidumbre a claridad para actuar con confianza | Resumen que no genera confianza real | El Asesor decide sin abrir el historial completo, y al preguntársele "por qué", repite la razón que el sistema le mostró |
| **EXP-03** | Inicio de Gestión | Asesor / Sistema | Tomar el caso es simple, no una carga | Qué ya se sabe del cliente | Sentirse al día con el caso sin vacíos que reconstruir | Sentido de propiedad claro | Heredar un caso a ciegas, repetir preguntas ya hechas | El Asesor puede nombrar de memoria los datos clave del cliente sin habérselos vuelto a preguntar |
| **EXP-04** | Desarrollo de la Oportunidad | Asesor / Copiloto, Catálogo, Equipo | Control sobre el avance | Qué le falta al cliente para decidir | Claridad sobre el único obstáculo activo ahora | Progreso tangible, no "dar vueltas" | Múltiples frentes abiertos sin prioridad clara | En cualquier momento del caso, el Asesor señala sin dudar cuál es la única acción pendiente más importante |
| **EXP-05** | Cierre | Asesor / Sistema | Cierre limpio, sin ansiedad residual | Que el resultado queda registrado sin fricción | Certeza total de que no queda nada pendiente | Sensación de cierre real | Cierre accidental sin corrección fácil | Tras cerrar, el Asesor no reabre el caso en la misma sesión para verificar que "quedó bien" |

**User Flow — Lead → Close Won:**

| ID | Pantalla / Patrón usado | Disparador | Qué ve el usuario | EXP que satisface |
|---|---|---|---|---|
| **UF-01** | Bandeja de Conversaciones (Product Patterns Cap. 2, §3) | Mensaje entrante de un cliente | La conversación aparece en la lista central; Gabi ya respondió según el Protocolo de interacción con IA (MPX Cap. 2), en estado optimista "enviando" antes de confirmación del servidor | EXP-01 |
| **UF-02** | Copiloto IA sobre la conversación (Cap. 5, §3) | Asesor abre la conversación desde la Bandeja | Panel colapsado por defecto; al expandirlo, Zona de sugerencias primero (`AI Suggestion Card`: "Convertir en oportunidad" + motivo), luego Zona de contexto (`AI Summary`) | EXP-02 |
| **UF-03** | CRM/Pipeline, vista de detalle (Cap. 6, §3) | Asesor confirma la sugerencia del Copiloto (o crea manualmente) | Conversation Timeline (eventos de negocio, no la conversación palabra por palabra), datos de contacto ya conocidos, estado "en curso", asesor asignado | EXP-03 |
| **UF-04** | Catálogo & Comercial (Cap. 7.A) — bifurcación opcional | Cliente pregunta precio/condición, o Asesor decide cotizar | Ficha de producto consultada desde el detalle del Lead; si se comparte, se adjunta como `Attachment` en la Bandeja (Cap. 7.A, §8) | EXP-04 |
| **UF-04b** | Equipo & Organización (Cap. 7.C) — bifurcación opcional | Asesor o Supervisor decide reasignar | Consulta de disponibilidad del equipo (Cap. 7.C, §8); vuelve al mismo punto del flow con otro asesor asignado | EXP-04 |
| **UF-05** | CRM/Pipeline, cambio de estado (Cap. 6, §4) | Cliente confirma o rechaza | Acción "cambiar estado" a `ganado` o `perdido`, disponible según rol | EXP-05 |

```
UF-01 (Bandeja) ──► UF-02 (Copiloto) ──► UF-03 (CRM/Pipeline: detalle)
                                                │
                                    ┌───────────┼───────────┐
                                    ▼                       ▼
                          UF-04 (Catálogo,          UF-04b (Equipo,
                           cotizar — opcional)        reasignar — opcional)
                                    │                       │
                                    └───────────┬───────────┘
                                                ▼
                                    UF-05 (CRM/Pipeline: Cierre)
```

**Screen Contract — Inventario de Pantallas (Lead → Close Won)** — campos 1-9, literal:

> **SCR-01 — Bandeja de Conversaciones (vista completa)**
> 1. **Objetivo:** que el Asesor vea la conversación entrante disponible para atender, con la primera respuesta de Gabi ya entregada.
> 2. **Disparador de entrada:** mensaje entrante de un cliente (nuevo o existente); o el Asesor abre el módulo Conversaciones.
> 3. **Información que recibe:** lista de conversaciones dentro de su alcance de rol; estado leída/no leída; `AI Summary` si el historial es extenso.
> 4. **Información que entrega:** selección de una conversación → abre su panel de chat.
> 5. **Acciones principales:** seleccionar conversación; responder; usar Quick Actions.
> 6. **Patrón consumido:** Bandeja de Conversaciones (Product Patterns Cap. 2, §3).
> 7. **Experience Flow que satisface:** EXP-01 (ya resuelto por Gabi antes de esta pantalla), EXP-02 (al abrirla).
> 8. **Riesgo UX:** silencio percibido — el cliente escribe sin señal de recepción.
> 9. **Criterio de éxito:** el cliente simulado confirma, sin que se le pregunte, que sintió una señal de recepción en los primeros segundos.

> **SCR-02 — Copiloto IA (panel contextual)**
> 1. **Objetivo:** que el Asesor reconozca si la conversación amerita convertirse en oportunidad, con la justificación a la vista.
> 2. **Disparador de entrada:** Asesor expande el panel del Copiloto desde la conversación abierta (SCR-01).
> 3. **Información que recibe:** historial de la conversación actual; señales de intención ya detectadas.
> 4. **Información que entrega:** sugerencia de conversión con motivo → confirmación o descarte del Asesor.
> 5. **Acciones principales:** expandir/colapsar; confirmar sugerencia; descartar.
> 6. **Patrón consumido:** Copiloto IA (Product Patterns Cap. 5, §3).
> 7. **Experience Flow que satisface:** EXP-02.
> 8. **Riesgo UX:** el resumen no genera confianza real, el Asesor igual relee todo.
> 9. **Criterio de éxito:** el Asesor decide sin abrir el historial completo, y puede repetir la razón que el sistema le mostró.

> **SCR-03 — CRM/Pipeline (detalle de oportunidad)**
> 1. **Objetivo:** formalizar la intención comprendida como oportunidad de negocio con dueño claro.
> 2. **Disparador de entrada:** Asesor confirma la sugerencia del Copiloto (SCR-02), o crea manualmente desde CRM/Pipeline.
> 3. **Información que recibe:** datos de contacto ya conocidos; Conversation Timeline; estado actual; asesor asignado.
> 4. **Información que entrega:** Lead creado/actualizado contra la única fuente de verdad, disponible para el resto del flow.
> 5. **Acciones principales:** ver Timeline; editar datos; cambiar estado; reasignar (según rol); consultar catálogo.
> 6. **Patrón consumido:** CRM/Pipeline (Product Patterns Cap. 6, §3).
> 7. **Experience Flow que satisface:** EXP-03.
> 8. **Riesgo UX:** heredar un caso a ciegas — repetir preguntas ya respondidas por el cliente.
> 9. **Criterio de éxito:** el Asesor nombra de memoria los datos clave del cliente sin habérselos vuelto a preguntar.

> **SCR-04 — Catálogo & Comercial (bifurcación opcional)**
> 1. **Objetivo:** resolver lo que el cliente necesita para decidir — precio, condición, disponibilidad.
> 2. **Disparador de entrada:** desde SCR-03, el Asesor decide cotizar (a pedido del cliente o proactivo).
> 3. **Información que recibe:** producto o servicio de interés, tomado del Lead o la conversación.
> 4. **Información que entrega:** ficha/cotización → puede adjuntarse como `Attachment` en SCR-01.
> 5. **Acciones principales:** buscar producto; ver ficha; adjuntar a la conversación.
> 6. **Patrón consumido:** Catálogo & Comercial (Product Patterns Cap. 7.A).
> 7. **Experience Flow que satisface:** EXP-04.
> 8. **Riesgo UX:** múltiples frentes abiertos sin prioridad clara.
> 9. **Criterio de éxito:** en cualquier momento del caso, el Asesor señala sin dudar cuál es la única acción pendiente más importante.

> **SCR-04b — Equipo & Organización (bifurcación opcional)**
> 1. **Objetivo:** encontrar el asesor correcto disponible para continuar la oportunidad.
> 2. **Disparador de entrada:** desde SCR-03, el Asesor o el Supervisor deciden reasignar.
> 3. **Información que recibe:** disponibilidad/carga del equipo.
> 4. **Información que entrega:** nuevo asesor asignado → vuelve a SCR-03 con el Lead actualizado.
> 5. **Acciones principales:** consultar disponibilidad; reasignar.
> 6. **Patrón consumido:** Equipo & Organización (Product Patterns Cap. 7.C).
> 7. **Experience Flow que satisface:** EXP-04 (mismo paso, distinto obstáculo que SCR-04).
> 8. **Riesgo UX:** múltiples frentes abiertos sin prioridad clara.
> 9. **Criterio de éxito:** igual a SCR-04 — una única acción pendiente identificable en todo momento.

> **SCR-05 — CRM/Pipeline (Cierre)**
> 1. **Objetivo:** convertir la oportunidad trabajada en un resultado de negocio explícito.
> 2. **Disparador de entrada:** el cliente confirma o rechaza.
> 3. **Información que recibe:** estado actual del Lead, contexto acumulado de la oportunidad.
> 4. **Información que entrega:** resultado final (`ganado`/`perdido`) → alimenta Analítica y el Learning Loop (UF-06, no es pantalla).
> 5. **Acciones principales:** cambiar estado — acción sujeta a la decisión pendiente sobre Human Decision Gate (Product Patterns Cap. 8, todavía no resuelta).
> 6. **Patrón consumido:** CRM/Pipeline (Product Patterns Cap. 6, §4).
> 7. **Experience Flow que satisface:** EXP-05.
> 8. **Riesgo UX:** cierre accidental sin corrección fácil.
> 9. **Criterio de éxito:** tras cerrar, el Asesor no reabre el caso en la misma sesión para verificar que "quedó bien".

**Cobertura verificada (literal):** *"6 pantallas (5 en el camino principal + 1 bifurcación), las
5 satisfacen la totalidad de EXP-01 a EXP-05, y ningún patrón fue inventado — los 5 patrones
consumidos (Bandeja, Copiloto, CRM/Pipeline, Catálogo, Equipo) ya son Product Patterns
Approved."*

**Campos 10-14 (Precondiciones, Postcondiciones, Estado esperado al abandonar, Dependencias,
Errores de experiencia previstos):** recuperados literalmente para **SCR-01, SCR-02, SCR-03** y
el inicio de **SCR-04** (línea 35423 del transcript, encabezado explícito: *"(campos 1-9 sin
cambios respecto a la versión anterior)"*). **NO RECUPERADO — NO ENCONTRADO EN LA FUENTE
CONSULTADA** para los campos 10-14 completos de SCR-04b y SCR-05 dentro de la ventana de
búsqueda realizada esta sesión — existe evidencia indirecta de que un borrador más completo
existe en algún punto anterior a la línea 35423 del transcript, no localizado todavía.

### C.2 — Recorrido histórico #3 — "Inicio → Acción priorizada" (EXP-06, EXP-07, UF-06, SCR-06)

**Experience Flow — Inicio → Acción priorizada (línea 35799, literal):**

> *"El hilo conductor que pediste, explícito antes de la tabla: EXP-01 a EXP-05 describen la
> evolución de un único caso a través del tiempo. EXP-06 y EXP-07 describen algo distinto — la
> reducción progresiva de N señales candidatas a una sola decisión, no el avance de un caso ya
> elegido. El punto donde termina esta reducción (EXP-07, 'Lograr') es exactamente el equivalente
> de La Siguiente Mejor Decisión aplicado a un momento de triage, no de profundización."*

| ID | Paso | Actor principal / soporte | Sentir | Comprender | Necesidad Cognitiva | Lograr | Riesgo UX | Criterio de éxito |
|---|---|---|---|---|---|---|---|---|
| **EXP-06** | Llegada y reconocimiento del panorama | Asesor / Sistema (Zona de indicadores) | Control desde el primer segundo — nunca "¿por dónde empiezo?" | Cuántas cosas requieren su atención hoy, en términos generales | Pasar de no saber qué hay a saber cuántas señales compiten por su atención — sin elegir todavía | Una fotografía completa del día en un solo vistazo, sin haber tenido que buscarla | Que el panorama se sienta como una lista más para revisar, no como algo ya resuelto | El Asesor dice, sin pensarlo, cuántas cosas tiene pendientes apenas mira la pantalla |
| **EXP-07** | Priorización: de varias señales a una sola decisión | Asesor / Copiloto IA (la señal que ordena) | Certeza de que la primera de la lista realmente es la más importante — sin tener que verificarlo él mismo | Por qué esa señal específica quedó primera y no otra | Colapsar N señales candidatas en una sola acción siguiente, sin comparar cada una mentalmente | Pasar de "tengo varias cosas pendientes" a "esto es lo primero que hago" | Que dos señales se sientan igual de urgentes y el Asesor tenga que decidir él mismo cuál va primero | Al preguntarle "¿qué harás primero?", el Asesor señala el primer ítem sin dudar ni comparar con los demás |

**Entrega (handoff) explícita, no un paso nuevo (literal):** *"cuando el Asesor hace clic en el
ítem priorizado de EXP-07, entra directo a EXP-02 (Comprensión), ya construido para el recorrido
#1 — no se repite ni se reconstruye. Este es el punto exacto donde recorrido #3 se conecta con
el trabajo ya congelado, sin duplicarlo."*

**Screen Contract — SCR-06: Inicio (Asesor)** (único contrato nuevo del recorrido #3; campos
1-13 recuperados, campo 14 no localizado en la ventana de extracción):

> 1. **Objetivo:** ayudar al Asesor a comprender su contexto, priorizar su trabajo y ejecutar la siguiente mejor acción desde el primer segundo de la sesión — nunca mostrar indicadores como fin en sí mismo (Product Patterns Cap. 3, §1).
> 2. **Disparador de entrada:** login exitoso del Asesor — primer patrón que se monta tras autenticarse, sin excepción (Cap. 3, §8).
> 3. **Información que recibe:** conversaciones/oportunidades propias que requieren atención (con motivo breve de por qué), la señal de mayor valor del momento si supera el umbral de confianza, e indicadores personales (conversaciones activas, leads asignados).
> 4. **Información que entrega:** la selección de un ítem de la Zona de acción.
> 5. **Acciones principales:** seleccionar el ítem priorizado — única acción principal de la pantalla. La Zona de indicadores no tiene acción propia, es apoyo (Cap. 3, §3).
> 6. **Patrón consumido:** Inicio (Product Patterns Cap. 3, completo — §3 Composición, §4 Roles, variante Asesor). No se redefine nada del patrón.
> 7. **Experience Flow que satisface:** EXP-06, EXP-07.
> 8. **Riesgo UX:** que el panorama se sienta como una lista más para revisar (EXP-06); que dos señales compitan sin que el sistema haya priorizado ya (EXP-07).
> 9. **Criterio de éxito:** el Asesor dice cuántas cosas tiene pendientes sin pensarlo (EXP-06); señala el primer ítem sin dudar ni comparar con los demás (EXP-07).
> 10. **Precondiciones:** Asesor autenticado; puede o no haber señales que superen el umbral de confianza (Cap. 3, §5) — ambos casos son válidos, no hay un caso "de error".
> 11. **Postcondiciones:** al seleccionar un ítem, transición a SCR-01 (Bandeja de Conversaciones), ya construido, con esa conversación específica abierta — reutiliza la Postcondición ya definida de SCR-01, no se redefine acá.
> 12. **Estado esperado al abandonar:** ninguno que preservar — a diferencia de SCR-01/03, Inicio no sostiene una tarea en curso; es un punto de tránsito que se recalcula desde cero en cada visita, reflejando el estado real del momento, nunca un snapshot viejo.
> 13. **Dependencias:** consume la misma señal de intención/prioridad que alimenta a CRM/Pipeline — Product Patterns Cap. 6, §8, ya lo declara *(texto cortado en la ventana de extracción — cita continúa más allá de lo recuperado)*.
> 14. *(campo "Errores de experiencia previstos" — NO RECUPERADO — NO ENCONTRADO EN LA FUENTE CONSULTADA)*

**UF-06 — declarado y corregido durante la Auditoría Transversal post-#3 (literal, línea
36033):** *"UF-06 (Inicio) entrega a UF-01 (Bandeja/SCR-01), no a UF-02 como había quedado
escrito por error al cerrar el recorrido #3 — verificado contra la Postcondición literal de
SCR-06."* Contexto del hallazgo: durante esa misma auditoría se encontró que *"creé EXP-06,
EXP-07 y SCR-06 para el recorrido #3, pero nunca declaré explícitamente 'UF-06' como el ID del
flujo de usuario correspondiente"* — inconsistencia real detectada y corregida sin construir
nada nuevo, solo mediante declaración formal. La convención `UF-NN` global (misma que `EXP-NN` y
`SCR-NN`) fue, en ese mismo momento, dejada explícita por primera vez en
`MAIEK_AI_IMPLEMENTATION_ROADMAP.md` §2.2. No se localizó una tabla UF-06 completa con las
columnas "Pantalla/Patrón", "Disparador", "Qué ve el usuario" en el formato de las demás filas UF
— **NO RECUPERADO** ese formato de fila específico; solo el hecho declarativo de la entrega
(handoff) citado arriba.

### C.3 — Recorrido histórico #2 — "Conversación → Lead generado"

**No existe una tabla EXP/UF/SCR propia para este recorrido.** Esto no es una laguna de
búsqueda — es un hallazgo verificado por el propio historial, encontrado por una búsqueda
exhaustiva hecha en su momento (antes del descubrimiento del transcript como recurso), y descrito
así (línea 36390, literal):

> *"No existe evidencia persistida suficiente para verificar EXP/UF literalmente. Las tablas
> completas nunca se guardaron en ningún archivo... Vivieron solo en el historial de
> conversación, y esa parte ya fue comprimida."*

Pero esa misma búsqueda encontró, ya verificado en memoria (no reconstrucción), el hecho
puntual que explica por qué: *"Recorrido #2 fortaleció este mismo Screen Contract, SCR-03, con 2
de 14 campos"* — es decir, el recorrido histórico #2 no creó pantallas nuevas: **reutilizó el
tramo ya construido en el recorrido #1** (Bandeja → Copiloto → CRM/Pipeline, SCR-01/SCR-02/SCR-03)
y fortaleció puntualmente SCR-03, sin generar IDs EXP/UF/SCR propios. Coincide con el patrón
"¿existe? → ¿se fortalece? → ¿se extiende? → recién crear" ya institucionalizado.

### C.4 — Recorridos post-compactación #5, #6, #7 (numeración actual — ya disponibles en el corpus, sin necesidad de arqueología de transcript)

Estos tres recorridos fueron construidos en las sesiones más recientes (ya reflejados en
`MAIEK_AI_IMPLEMENTATION_ROADMAP.md`, Control de versiones, y en memoria persistida) y **no
requirieron recuperación desde el transcript** — su contenido completo ya vive en el contexto de
trabajo activo:

- **Recorrido #5 — Campaña → Lead atribuido → Pipeline.** EXP-01→EXP-07/UF-01→UF-06 reutilizados
  sin cambios (por precedente documentado del recorrido #2); SCR-03 fortalecido en 1 solo campo
  ("Información que recibe": agrega atribución de origen). Ningún EXP-08/UF-07 creado. Detalle
  completo en [[project_recorrido5_bloqueo_corpus_pendiente]].
- **Recorrido #6 — CRM/Pipeline → Analítica.** EXP-08→EXP-12, UF-07→UF-11, SCR-07 (Analítica,
  contrato completo de 14 campos) construidos. Prototipo extendido con `#screen-analitica`
  (`.kpi-grid-analitica`, `.suggestion-card` con demo toggle, `.statistic-grid`/`.statistic-card`
  con deltas Unicode ↑/↓). 3 defectos reales encontrados y corregidos en Auditoría (responsive,
  demostración funcional de ausencia de sugerencia, renderizado de íconos de delta).
- **Recorrido #7 — Conversaciones → Catálogo & Comercial.** EXP-13/EXP-14, UF-12/UF-13,
  fortalecimiento de SCR-01 (propuesta funcional, no diff literal — status propio ya establecido)
  + drawer interno (no pantalla nueva), tras auditoría de referentes UX (Kommo, WhatsApp
  Business, respond.io; Treble.ai insuficientemente documentado, marcado explícitamente). 1
  defecto Obligatorio real encontrado y corregido (Copiloto/Catálogo podían coexistir abiertos
  simultáneamente — corregido llamando `toggleCopilot(false)` dentro de `openCatalogo()`).

No se transcribe aquí el contenido completo de estos tres recorridos para no duplicar
`MAIEK_AI_IMPLEMENTATION_ROADMAP.md`; este documento los referencia para que la Sección D
(Reconciliación) y la Matriz de trazabilidad (Sección E) puedan citarlos junto a sus
contrapartes históricas. **Excepción: SCR-07**, cuyo texto literal nunca había sido persistido
en ningún archivo (recuperado del transcript recién en esta sesión) y que recibió un
fortalecimiento puntual real — se transcribe completo en C.4.1, siguiendo el mismo criterio ya
usado en la Sección C.1 para SCR-01→SCR-06.

### C.4.1 — SCR-07 (Analítica), recuperado y fortalecido (2026-08-09)

Recuperado literalmente del transcript (no reconstruido). Fortalecido en los campos 2, 3, 10, 13
y 14 para declarar la segunda vía de entrada (contextual, desde CRM/Pipeline vía UF-08), como
parte de la resolución de la dependencia "Vista principal de Pipeline sin Screen Contract" y de
la decisión de diseño sobre la naturaleza del contexto (criterio/señal/segmento, no una lista de
IDs de Leads). Campos 1, 4, 5, 6, 7, 8, 9, 11 y 12 permanecen sin cambios respecto a la versión
original recuperada.

> **1. Objetivo:** comprender un patrón o tendencia entre múltiples Leads que un caso individual
> no puede explicar — el nivel de profundidad que Inicio deliberadamente no ofrece (Cap. 4 §1).
>
> **2. Disparador de entrada:** dos vías, verificadas por separado — Acceso directo desde el
> Sidebar (ya existente, Shell Cap. 1 / MPA §10) — sin cambios. Transición desde CRM/Pipeline
> (Vista principal, Screen Contract propio ya construido), con el criterio/señal/segmento que
> originó la consulta, entregado según la Postcondición de esa Vista (UF-08) — el mecanismo
> concreto de representación visual del filtro sigue sin definir, corresponde a Wireframe.
>
> **3. Información que recibe:** si llega desde Pipeline, el criterio/señal/segmento que originó
> la consulta, tal como lo entrega la Vista principal de Pipeline (Screen Contract propio,
> Postcondición) — no una lista de IDs de Leads seleccionados (decisión de diseño ya aprobada).
> La forma exacta en que ese criterio se estructura sigue sin definir. Datos ya agregados de
> Conversaciones, CRM/Pipeline, Campañas y Equipo & Organización, en el sentido de solo lectura ya
> declarado en MPA §12.
>
> **4. Información que entrega:** ninguna escritura a otros módulos — Analítica "nunca genera
> datos propios, siempre reinterpreta los de otros" (MPA §3). Lo que entrega es comprensión, no un
> dato persistido.
>
> **5. Acciones principales:** observar (`KPI Card`), explorar/comparar por dimensión (`Statistic
> Card`), ver una sugerencia condicional ya explicada (`AI Suggestion Card`) — ninguna acción de
> escritura ni decisión ejecutable.
>
> **6. Patrón consumido:** Product Patterns Cap. 4 (Analítica).
>
> **7. Experience Flow que satisface:** EXP-10, EXP-11, EXP-12 — los pasos que ocurren dentro de
> esta pantalla. EXP-08 y EXP-09 preceden la llegada (ocurren en Pipeline y en la transición), no
> son satisfechos por este contrato.
>
> **8. Riesgo UX:** mostrar comparativos sin indicar la dimensión relevante para el rol (Cap. 4
> §9); mostrar más de 8 `KPI Card` (Cap. 4 §9); mostrar una sugerencia sin justificación o por
> debajo del umbral de confianza (Cap. 4 §6); convertir la sugerencia en una obligación implícita
> de decidir (ajuste ya fijado en EXP-12).
>
> **9. Criterio de éxito:** el usuario puede decir, en una frase, si el patrón es real y qué
> dimensión lo explica; si aparece sugerencia, puede explicar su fundamento sin haber decidido ni
> ejecutado nada.
>
> **10. Precondiciones:** actividad suficiente para generar tendencias (si no, aplica el Estado
> Vacío ya definido en Cap. 4 §5); alcance de rol suficiente (Cap. 4 §4: Administrador global,
> Supervisor su equipo, Asesor exclusivamente personal); si llega desde Pipeline, el
> criterio/señal/segmento debe haberse reconocido ahí, según la responsabilidad ya declarada en el
> Screen Contract de la Vista principal de Pipeline — resuelto tanto en responsabilidad funcional
> como en mecanismo visual concreto (Wireframe, Mockup e implementación en el Prototipo, ver
> C.4.3), pendiente únicamente de validación visual/interactiva externa.
>
> **11. Postcondiciones:** ninguna — Analítica es de solo lectura (MPA §3/§12); no persiste ningún
> estado nuevo del sistema.
>
> **12. Estado esperado al abandonar:** sin tarea inconclusa que recuperar — a diferencia de
> Pipeline, no es una tarea de varios pasos con estado propio; al volver, simplemente se ven los
> datos actualizados.
>
> **13. Dependencias:** Conversaciones, CRM/Pipeline, Campañas, Equipo & Organización (MPA §12,
> solo lectura). De las dos decisiones que este contrato dejaba explícitamente pendientes: **(a)
> la Vista principal de Pipeline sin Screen Contract — RESUELTA**, Screen Contract propio ya
> construido. **(b) el mecanismo concreto de representación visual** del criterio/segmento en la
> transición Pipeline → Analítica (UF-08) — **RESUELTO** mediante Wireframe, Mockup e
> implementación en el Prototipo (ver C.4.3), incluida la corrección de correspondencia "Requiere
> atención" → KPI "Estancados +5 días"; pendiente únicamente de validación visual/interactiva
> externa.
>
> **14. Errores de experiencia previstos:** Vacío (Cap. 4 §5); Cargando (`Skeleton`); llegar desde
> Pipeline sin el criterio/segmento correctamente preservado — rompería la continuidad de
> propósito (UX Blueprint §2.3); riesgo mitigado por la representación ya implementada (ver
> C.4.3), pendiente de confirmarse mediante validación visual/interactiva externa.

### C.4.2 — EXP-08→EXP-12 (CRM/Pipeline → Analítica), recuperado literalmente del transcript

Recuperado literalmente (transcript, sesión `7684292f-...`, misma línea que SCR-07). Ningún campo
reconstruido. Donde el fragmento recuperado quedó incompleto, se marca explícitamente en vez de
completarlo por inferencia.

**Principio rector (cita literal):** *"EXP-08 y EXP-09 describen algo distinto — la reducción
progresiva de N señales candidatas a una sola decisión, no el avance de un caso ya elegido"* —
extendido acá para el patrón agregado: EXP-08→EXP-12 completo trata de *"comprender un patrón
agregado"*, una Necesidad Cognitiva sin equivalente en EXP-01→EXP-07 (verificado explícitamente
en la Auditoría del propio Experience Flow, citada más abajo).

| ID | Paso | Actor principal / soporte | Sentir | Comprender | Necesidad Cognitiva | Lograr | Riesgo UX | Criterio de éxito |
|---|---|---|---|---|---|---|---|---|
| **EXP-08** | Detecta una posible señal sistémica mientras trabaja en Pipeline (no un Lead aislado) | Supervisor / — | Incertidumbre — "¿esto es normal o es un problema más grande?" | Que un solo Lead no puede confirmar ni descartar un patrón | Necesita evidencia agregada, no un caso más | Decide que amerita mirar más allá del Lead individual | Ignorar la señal por no tener a mano una vía rápida de verificarla | El Supervisor articula qué le hizo sospechar un patrón (no solo "algo se ve raro") |
| **EXP-09** | Transiciona a Analítica, ya filtrada por el segmento que originó la pregunta | Supervisor / Sistema (preserva contexto) | Continuidad — el sistema no le pide reformular lo que ya sabía | Que llegó a la vista correcta sin perder el hilo de su pregunta original | Confirmar que el sistema entendió el motivo real de la visita | Confía en que lo que ve a continuación responde su pregunta, no una genérica | Que el filtro no se preserve y tenga que reconstruir manualmente el segmento — rompe continuidad de propósito (UX Blueprint §2.3) | El segmento/filtro llega ya aplicado, verificable a simple vista |
| **EXP-10** | Observa la franja de KPI Cards | Supervisor / — | Orientación rápida | Si los números agregados confirman o contradicen su sospecha inicial | Verificar la magnitud del patrón antes de profundizar | Tiene una primera confirmación cuantitativa | Sobrecarga si hay más de 8 KPI Cards (Cap. 4 §9, regla ya fijada) | Puede decir, en una frase, si el patrón es real a nivel agregado |
| **EXP-11** | Explora la Zona de detalle comparativo (`Statistic Card` por dimensión) | Supervisor / — | Curiosidad dirigida, no exploración libre | Cuál dimensión (equipo, canal, campaña, período) explica el patrón — la transformación cognitiva central de este Experience Flow, ausente en Inicio/Bandeja/Pipeline | Aislar la variable que explica lo observado | Identifica qué dimensión concentra el problema | **NO RECUPERADO — NO ENCONTRADO EN LA FUENTE CONSULTADA** (el fragmento se cortó en la ventana de extracción) | **NO RECUPERADO — NO ENCONTRADO EN LA FUENTE CONSULTADA** |
| **EXP-12** | *(condicional — solo si supera el umbral de confianza)* Ve una sugerencia de siguiente mejor acción, con su explicación | Supervisor / Agentes IA | Alivio dirigido, nunca sorpresa — la sugerencia ya trae su razón | Por qué / por qué ahora / por qué a él — Explainability First (MPX Cap. 3, Cap. 4 §6) | Evaluar si la sugerencia es procesable o requiere más contexto | Tiene una hipótesis concreta y explicada sobre qué hacer con el patrón | Mostrar la sugerencia sin justificación, o por debajo del umbral de confianza (Cap. 4 §6: si no puede explicarse, no se muestra) | Puede repetir, con sus palabras, el "por qué" de la sugerencia sin releerla |

**Nota de distinción dato vs. inferencia (cita literal):** *"EXP-10 y EXP-11 trabajan con datos
agregados/factuales (`KPI Card`, `Statistic Card`) — Cap. 4 no los atribuye a una inferencia de
IA con nivel de confianza. Solo EXP-12 es una inferencia de IA con Explainability First
aplicado."*

**Handoff/outcome fuera de alcance (cita literal):** *"El recorrido termina en EXP-11
(comprensión) o EXP-12 (sugerencia explicada, si aplica). Cualquier acción posterior — reasignar
Leads del segmento, cambiar estados, cotizar, cerrar oportunidades, ejecutar acciones masivas —
queda registrada como: de existir una acción derivada del patrón comprendido, esa acción se
ejecutaría de vuelta en CRM/Pipeline (SCR-03, ya congelado) — no se diseña acá, ni se asume que
deba existir un mecanismo nuevo de 'acción masiva' sin evidencia de que el corpus lo respalde."*
Esta cita es la base contractual de que **EXP-08→EXP-12 no requieren modificación** por el
fortalecimiento de UF-08/SCR-07/Vista principal de Pipeline documentado en C.4.1 y C.4.3 — el
alcance de este Experience Flow siempre terminó en la comprensión del patrón, nunca en una acción.

**Auditoría del propio Experience Flow (tabla literal, parcial — se citan las filas
recuperadas):**

| Pregunta | Resultado |
|---|---|
| ¿Cada paso representa una transformación cognitiva? | Sí — EXP-10 (confirmación agregada) y EXP-11 (atribución dimensional) son transformaciones distintas, no la misma mirada repetida |
| ¿Existe una Necesidad Cognitiva nueva real? | Sí — "aislar la dimensión que explica un patrón" no tiene equivalente en EXP-01→EXP-07 |
| ¿Estamos duplicando algún EXP existente? | No |
| ¿Estamos diseñando una pantalla prematuramente? | No — ningún paso define layout ni componente concreto más allá de los ya nombrados por Cap. 4 |
| ¿Estamos introduciendo una decisión que el corpus no respalda? | No — sin Human Decision Gate ni acción irreversible en ningún paso |
| ¿Se mantiene el alcance hasta comprensión del patrón? | Sí — EXP-12 es el último paso, cualquier acción queda registrada como handoff fuera de alcance |

### C.4.3 — Vista principal de Pipeline (Screen Contract nuevo) y UF-08 completado (esta sesión, 2026-08-09/10)

**Distinto de C.4.1/C.4.2: esto no es recuperación del transcript — es trabajo de Product Design
construido y aprobado íntegramente en esta sesión**, como fortalecimiento del recorrido
CRM/Pipeline → Analítica. Cierra la dependencia "Vista principal de Pipeline sin Screen Contract"
que quedaba pendiente en la Sección F.3 (ahora resuelta, ver corrección en F.3/F.4 más abajo) y
completa UF-08 dentro del rango UF-07→UF-11 ya asignado — **no se creó ningún UF nuevo, ningún
EXP nuevo, ni SCR-08.**

**Decisión central de UF-08 (aprobada):** UF-08 representa la transición contextual
Pipeline → Analítica. El contexto que se transporta es **el criterio/señal/segmento que originó
la consulta** — no una lista de IDs de Leads, no una multiselección obligatoria, no una selección
individual de Leads.

**Screen Contract — Vista principal de Pipeline:**

> 1. **Objetivo:** que el usuario (Asesor/Supervisor/Admin, según su alcance de rol) vea el
> conjunto de oportunidades dentro de su alcance y pueda identificar cuáles requieren atención; y,
> como responsabilidad nueva para soportar UF-08, pueda reunir/expresar un criterio relevante
> como base de una consulta contextual hacia Analítica.
> 2. **Disparador de entrada:** usuario abre el módulo CRM/Pipeline desde el Sidebar (Cap. 1) —
> mismo mecanismo ya usado por cualquier destino de la Navegación principal.
> 3. **Información que recibe:** lista de Leads dentro del alcance de rol del usuario (Cap. 1 §4);
> estado de cada Lead; señal de "requiere atención" ya existente (Cap. 6 §6, compartida con la
> Zona de acción de Inicio); atribución de campaña cuando aplica (Cap. 6 §8).
> 4. **Información que entrega:** al seleccionar un Lead individual, abre su vista de detalle
> (SCR-03, ya congelado). La pantalla entrega, hacia una consulta contextual, **el
> criterio/señal/segmento que originó la pregunta del Supervisor** — no necesariamente una lista
> de IDs de Leads seleccionados.
> 5. **Acciones principales:** buscar/filtrar/ordenar (Cap. 6 §3); seleccionar un Lead → ver
> detalle; alguna acción que permite al Supervisor iniciar la consulta contextual a partir del
> criterio/señal que está observando, sin que reunir/marcar Leads individualmente sea un paso
> obligatorio — el mecanismo visual concreto de esa acción corresponde a Wireframe/Mockup, no se
> redefine acá.
> 6. **Patrón consumido:** CRM/Pipeline (Product Patterns Cap. 6, completo — §3 Composición
> "Vista principal", §4 Roles vía Cap. 1, §6 Comportamiento MPX).
> 7. **Experience Flow que satisface:** sostiene indirectamente EXP-03 (vía selección individual
> → SCR-03) y EXP-08 ("detecta una posible señal sistémica mientras trabaja en Pipeline, no un
> Lead aislado").
> 8. **Riesgo UX:** que el criterio/segmento que originó la pregunta no quede claramente
> identificado o expresado para el sistema, y por lo tanto no pueda transportarse.
> 9. **Criterio de éxito:** el criterio de EXP-08 — "El Supervisor articula qué le hizo sospechar
> un patrón (no solo 'algo se ve raro')."
> 10. **Precondiciones:** usuario autenticado con acceso al módulo (Cap. 1 §4); puede o no haber
> Leads con la señal de atención — ambos casos válidos, mismo criterio que SCR-06.
> 11. **Postcondiciones:** al seleccionar un Lead individual, transición a SCR-03 (ya congelado).
> Al expresar el criterio/señal que originó la pregunta, se inicia una transición hacia Analítica
> (SCR-07) vía UF-08 — no condicionada a haber reunido un conjunto explícito de Leads.
> 12. **Estado esperado al abandonar:** el criterio de orden/filtro activo se mantiene coordinado
> y sobrevive a un cambio de página (Cap. 6 §6, ya declarado). **Si también sobrevive a un cambio
> de módulo (ida y vuelta a Analítica) no está resuelto ni exigido** — la única decisión aprobada
> es que Pipeline no debe sentirse como una pantalla reiniciada; la preservación exacta del
> filtro/conjunto al volver queda como comportamiento deseable, no como requisito contractual.
> 13. **Dependencias:** consume la misma señal de "requiere atención" que alimenta a Inicio (Cap.
> 6 §6); alimenta la Zona de detalle comparativo de Analítica "con el mismo dato de embudo, sin
> duplicar su cálculo" (Cap. 6 §8).
> 14. **Errores de experiencia previstos:** ninguno propiamente dicho — reutiliza los dos Estados
> Vacíos ya definidos en Cap. 6 §5 ("primer uso" y "sin resultados de filtro").

**Wireframe UF-08 (funcional, sin diseño visual) — resumen de la solución aprobada:**

- **Pipeline:** reutiliza Filtros ya existentes (Cap. 6 §3) y la señal "requiere atención" (Cap.
  6 §6); el filtro activo *es* el criterio — no se exige selección individual de Leads; existe un
  punto de activación (forma visual no decidida en el Wireframe) que dispara la consulta cuando
  hay un criterio activo.
- **Transición:** reutiliza el Shell de Navegación y el estado de carga (`Skeleton`/pantalla de
  carga) ya existente entre pantallas — sin navegación técnica nueva.
- **Analítica:** misma pantalla de SCR-07 (sin pantalla nueva); un encabezado se vuelve
  condicional para mostrar el criterio recibido; la aplicación del criterio se resuelve mediante
  priorización/resalte de un elemento ya existente de la composición (reutilizando Priorización,
  Cap. 4 §6) cuando existe una correspondencia clara — sin forzar una correspondencia que no
  exista; composición base (KPI Grid, Statistic Grid, `AI Suggestion Card`) sin rediseño.
- **Retorno:** solo el nivel mínimo — Pipeline no se siente reiniciado. Sin breadcrumb, historial
  ni deep link nuevos.

**Mockup UF-08 (tokens/componentes reales) — resumen de la solución aprobada, incluida la
corrección posterior:**

- **Pipeline:** filtros reutilizando el patrón de botón ya usado para demostraciones (`.proto-btn`);
  toast ya existente (mismo usado en el recorrido #7) para confirmar el inicio de la consulta.
- **Transición:** pantalla de carga ya existente entre Bandeja→Pipeline, reutilizada sin cambios.
- **Analítica:** `eyebrow-lg` condicional (mismo componente, texto distinto según origen); `.sub`
  para mostrar el criterio recibido (mismo patrón ya usado para la atribución de campaña en
  Pipeline); resalte mediante el mismo token ya usado en `.catalog-pick.selected`
  (`var(--accent)`/`var(--info-bg)`) — ningún token ni componente nuevo.
- **Corrección posterior aprobada — correspondencia por criterio:** para el criterio "Canal:
  Campañas" (dimensión existente), se resalta la `Statistic Card` "CAMPAÑAS". Para el criterio
  "Requiere atención" (sin dimensión de canal/equipo/campaña/período propia), se identificó como
  correspondencia válida y sustentada por el corpus (Product Patterns Cap. 6 §6: "un lead que
  requiere atención prioritaria, ej. sin respuesta hace tiempo") el KPI ya existente "Estancados
  +5 días" — se resalta ese KPI en vez de forzar una correspondencia inexistente en la Statistic
  Grid. Ningún criterio sin correspondencia clara recibe un resalte inventado.

**Prototipo — estado de implementación (registro documental, no nueva implementación):**

Implementado sobre el Artifact único ya publicado (`prototipo_lead_close_won.html`): nueva
pantalla `screen-pipeline-lista` (Vista principal, reutilizando `.priority-item`, `.eyebrow-lg`,
`.proto-btn`, `.rail`/`.item` ya existentes); ítem de navegación `.nav-pipeline` agregado al rail
de Inicio y de Analítica (reutilizando el patrón de rail ya existente); transición contextual
completa (Pipeline → carga → Analítica con criterio aplicado); resalte condicional de
`#stat-campanas` o `#kpi-estancados` según el criterio, sin recálculo de ningún valor mostrado;
reseteo incondicional del contexto al entrar por el Sidebar directo (`railAnalitica`). Verificado
por trazado estático del código y por sintaxis JavaScript real (`node -c`, sin errores, balance
de llaves confirmado) — **no fue posible ejecutar validación visual/interactiva real, por
limitación del entorno (Artifact fuera del proyecto, renderizado como snapshot estático)**, misma
limitación ya documentada para el resto del Prototipo.

**Estado final:** `UF-08 — IMPLEMENTADO, FUNCIONALMENTE CONSISTENTE, VALIDACIÓN
VISUAL/INTERACTIVA EXTERNA PENDIENTE.`

**Actualización (2026-08-10) — Pipeline Data Grid completo, implementado contra este mismo
Screen Contract, sin crear artefactos de Product Design nuevos.** El subconjunto ilustrativo de
3 Leads estáticos se reemplazó por un dataset de demostración de 12 Leads, renderizado
dinámicamente, con Filtros, Ordenamiento y Paginación reales — cumpliendo el campo 5 ("Acciones
principales: buscar/filtrar/ordenar") y la composición "Vista principal" de Product Patterns
Cap. 6 §3 (Tabla/Data Grid con Filtros, Ordenamiento y Paginación; columnas ya cubiertas por el
formato de lista existente, sin exceder ~7 atributos por fila). Reutiliza literalmente
`.priority-item`/`.priority-item.top` (Cap. 3, ya usado para el ítem urgente de Inicio),
`.proto-btn`/`.proto-controls` (ya usado para Filtro y para la demo de notificaciones) — ningún
componente ni token nuevo. Los botones `Requiere atención`/`Canal: Campañas` ya existentes para
UF-08 ahora, además de activar la consulta contextual, filtran genuinamente la lista — el propio
Wireframe de UF-08 ya declaraba que "el filtro activo *es* el criterio", así que esto completa
una responsabilidad ya implícita, no la redefine. Selección de Lead → detalle: solo Marcela Rojas
navega a SCR-03 (único Lead con Vista de detalle construida en el Prototipo); el resto de los
Leads del dataset de demostración no son clicables — no se fabricó un detalle que no existe
`[PEND]`. "Buscar" (texto libre) queda `[PEND]`: el campo 5 del Screen Contract lo cita, pero
ni Cap. 6 §3 ni el Prototipo ya construido tienen un patrón visual de referencia para reutilizar
— no se inventó uno. **Validado interactivamente en el Browser pane** (a diferencia de UF-08/
UF-15, esta vez con éxito): navegación Inicio → Pipeline lista, Ordenamiento (ambos criterios,
verificado por lectura real del DOM tras cada clic), Paginación (3 páginas/12 resultados,
avance, estados deshabilitados en los extremos), Filtro (`Requiere atención` → 5/5 resultados,
1 página), y selección de Marcela Rojas → SCR-03 (composición intacta, sin residuo de motivo de
notificación). No se probó interactivamente el filtro `Canal: Campañas` ni el estado vacío (0
resultados) — mismo mecanismo ya validado para el otro filtro, no se declaran como validados sin
evidencia directa.

### C.5 — Recorridos históricos #4, #6, #7, #8, #9 — no construidos post-compactación bajo esos números, ni localizada tabla EXP/UF/SCR propia en el transcript

No se encontró, dentro de la ventana de búsqueda de esta sesión, contenido EXP/UF/SCR asociado
directamente a los recorridos históricos #4 (Inicio → Analítica), #8 (Notificación → Acción) o
#9 (Autenticación → Inicio) — consistente con que ninguno de los tres fue construido bajo ningún
número, histórico o actual (#8 y #9 aparecen en Sección E como "Bloqueado" y "Sin
correspondencia" respectivamente). Para #6 (Reasignación de Lead) y #7 (Cotización), ver la nota
de conflicto/relación parcial en la Sección E — no se buscó una tabla EXP/UF/SCR histórica
separada para ellos porque la propia Sección E ya documenta que la relación con lo construido
post-compactación es un conflicto o relación parcial pendiente de decisión del usuario, no un
vacío de búsqueda.

**Nota (2026-08-10): #8 deja de estar cubierto por esta sección** — ver C.6, construido después de
que el bloqueo original ("BLOQUEADO POR PRODUCT PATTERNS") se levantara con la persistencia de
`MAIEK_AI_PRODUCT_PATTERNS.md` Capítulo 8. Este párrafo permanece sin editar como registro de lo
que era cierto al momento de escribirse — la Sección F.1 es la vigente para el estado actual de #8.

---

### C.6 — Recorrido histórico #8 — "Notificación → Acción específica" (EXP-15, UF-15, fortalecimiento de SCR-03)

Construido el 2026-08-10, íntegramente en esta sesión (no recuperado de ningún transcript
anterior), mediante el ciclo completo ya institucionalizado: Gap Analysis → Gate de decisiones de
Experience Design (DEC-1 a DEC-4 de esta ronda, distintas de las DEC-01 a DEC-04 de Product
Patterns Cap. 8) → Experience Flow → User Flow → verificación de reutilización de Screen Contract
→ sincronización documental. El bloqueo original ("BLOQUEADO POR PRODUCT PATTERNS", Sección E) se
levanta con esta entrada, tras la persistencia de `MAIEK_AI_PRODUCT_PATTERNS.md` Capítulo 8 —
Notificaciones (2026-08-10).

**Decisiones de Experience Design aprobadas (base de EXP-15/UF-15):**
1. "Mensaje sin responder" es un disparador general; "Lead de alto valor" es un atributo de
   prioridad dentro de él, no un tercer disparador ni condición obligatoria.
2. El destino de ambos disparadores (nueva asignación, mensaje sin responder) es el Lead exacto en
   CRM/Pipeline — nunca una bandeja general; no se extiende a otros módulos sin evidencia.
3. Aplica la Regla de Prioridad Única Activa (UX Blueprint §7.2): una notificación no desplaza una
   tarea activa; permanece como estímulo secundario hasta que el usuario decide atenderla, salvo
   Bloqueo explícito (que una notificación ordinaria no alcanza).
4. Misma experiencia cognitiva para Asesor y Supervisor — cambia únicamente el alcance de Leads
   (propios vs. equipo); no se abre un recorrido separado para Supervisor.

**EXP-15 — Notificación → Acción específica:**

| Campo | Contenido |
|---|---|
| 1. ID | EXP-15 |
| 2. Situación / Disparador | Nueva asignación de un Lead al Asesor; o un Lead con mensaje sin responder ("alto valor" como atributo de prioridad, no disparador distinto). |
| 3. Necesidad cognitiva | Comprender qué Lead requiere su atención y por qué, para decidir si actuar ahora o continuar con la tarea en curso. |
| 4. Qué hace el usuario | Recibe la señal; evalúa su prioridad frente a lo que está haciendo; decide atender ahora o continuar; si atiende, se dirige al Lead señalado. |
| 5. Qué necesita comprender | Qué Lead es, por qué se le señala, y si eso amerita interrumpir lo que está haciendo. |
| 6. Qué responde el sistema | Preserva el motivo de la alerta de forma comprensible al llegar al Lead; si hay tarea activa, la señal permanece como estímulo secundario sin desplazarla; si el usuario decide atender, lo lleva al Lead exacto, nunca a una bandeja general. |
| 7. Criterio de éxito | El usuario entiende, sin indagar por separado, qué Lead requiere atención y por qué; si atiende, llega al Lead correcto con el motivo visible; si continúa, su tarea no se interrumpe ni pierde estado. |
| 8. Riesgo UX | Que la señal se sienta intrusiva si desplaza una tarea activa; que el motivo no viaje con la transición; que eventos de baja urgencia lleguen sin agrupar y generen fatiga (MPX Cap. 7, principio sin mecanismo resuelto). |
| 9. Continuidad | Contexto: obligatoria (el motivo viaja con la transición). Propósito: no exigida. Retorno: solo el baseline arquitectónico. Atención (regla de coexistencia, no una cuarta propiedad): no interrumpe tarea activa salvo Bloqueo explícito. |
| 10. Variaciones por rol/canal | Rol: Asesor (Leads propios) / Supervisor (alcance de equipo) — misma experiencia cognitiva. Canal: cualquiera de los tres ya aprobados en Cap. 8; asignación evento↔canal fuera de alcance. |
| 11. Alcance / fuera de alcance | Dentro: recibir la señal, comprenderla, decidir, llegar al Lead con el motivo preservado. Fuera: mecanismo visual/técnico del canal, agrupación/batching, fatiga, historial, modelo de datos, conexión real del Badge. |
| 12. Handoff / outcome | Si atiende: el control pasa al recorrido ya existente de gestión del Lead (Product Patterns Cap. 6, recorrido #1). Si no atiende: su tarea activa continúa sin interrupción (Blueprint Cap. 6/§7.2). |

**UF-15 — Notificación → Acción específica (origen: EXP-15):**

| Campo | Contenido |
|---|---|
| 1. ID del UF | UF-15 |
| 2. EXP de origen | EXP-15 |
| 3. Actor | Asesor (Leads propios); Supervisor (alcance de equipo) |
| 4. Precondición | Lead con evento notificable ya ocurrido; usuario con sesión activa en el panel (Shell, Cap. 1) |
| 5. Disparador | Nueva asignación, o mensaje sin responder (alto valor = atributo, no disparador distinto) |
| 6. Secuencia paso a paso | (1) Ocurre el evento. (2) El sistema entrega la señal por un canal aprobado (Cap. 8). (3) El usuario percibe la señal con el motivo accesible. (4) Evalúa si tiene tarea activa. (5) Decide: atender o continuar. (6) Rama A: llega al Lead exacto, motivo visible, entra al recorrido de gestión existente. (7) Rama B: la tarea activa no se interrumpe; la señal sigue disponible. |
| 7. Puntos de decisión | (a) ¿Hay tarea activa? (b) ¿Atiende ahora o continúa? |
| 8. Rama "atender" | Activa la señal → navega al Lead exacto en CRM/Pipeline → motivo visible → handoff a la gestión de Lead ya existente |
| 9. Rama "continuar tarea" | La tarea activa no se interrumpe ni pierde estado; la señal permanece disponible |
| 10. Contexto que debe viajar | El motivo de la alerta (Lead + por qué — nueva asignación / mensaje sin responder, con alto valor si aplica) |
| 11. Destino | El Lead exacto en CRM/Pipeline — nunca una bandeja general |
| 12. Handoff al recorrido existente | Gestión de Lead ya cubierta por Product Patterns Cap. 6 y por el recorrido #1 (Lead → Close Won) — UF-15 no la rediseña |
| 13. Resultado esperado | Usuario comprendió qué Lead y por qué; si atendió, llegó al Lead correcto sin reconstruir el motivo; si continuó, su tarea siguió intacta |
| 14. Variaciones por rol | Asesor: origen = Leads propios. Supervisor: origen = alcance de equipo. Mismo recorrido, mismos pasos |
| 15. Estados excepcionales | Doble evento simultáneo sobre el mismo Lead; reasignación del Lead entre que se genera la señal y se atiende — sin evidencia de resolución, no bloqueante, mismo tipo de vacío ya documentado y sin resolver para histórico #6 (Sección D) |

**Reutilización primero — SCR-03, versión sincronizada (2026-08-10):**

No se crea Screen Contract nuevo. `MAIEK_AI_EXPERIENCE_FLOWS.md` mantiene el bloque histórico de
recuperación literal de SCR-03 en la Sección C.1 (campos 1-9, versión de la sesión original,
anterior a los fortalecimientos de los recorridos #2 y #5) intacto y sin editar, por la misma
regla de nunca alterar una recuperación literal ya persistida — esta tabla es la versión **vigente**:

| Campo | Contenido vigente | Origen |
|---|---|---|
| 1. Objetivo | Formalizar una oportunidad sobre la única fuente de verdad — sea que se cree por primera vez o que ya exista. | Recorrido #2 (recuperado literalmente en esta sesión) |
| 2. Disparador de entrada | Asesor confirma la sugerencia del Copiloto (SCR-02), o crea manualmente desde CRM/Pipeline, o el usuario atiende una notificación de Lead (nueva asignación o mensaje sin responder) y accede directamente a este Lead (UF-15). | Original + fortalecimiento UF-15 |
| 3. Información que recibe | Datos de contacto ya conocidos; Conversation Timeline; estado actual; asesor asignado; atribución de origen, cuando el Lead proviene de una campaña; cuando la entrada proviene de una notificación, el motivo de la alerta que originó la transición (evento: nueva asignación o mensaje sin responder; atributo de alto valor cuando corresponda) — mecanismo de presentación diferido a Wireframe/Mockup. | Original + Recorrido #5 + fortalecimiento UF-15 |
| 4. Información que entrega | Lead creado/actualizado contra la única fuente de verdad, disponible para el resto del flow. | Sin cambios |
| 5. Acciones principales | Ver Timeline; editar datos; cambiar estado; reasignar (según rol); consultar catálogo. | Sin cambios |
| 6. Patrón consumido | CRM/Pipeline (Product Patterns Cap. 6, §3). | Sin cambios |
| 7. Experience Flow que satisface | EXP-03; y, cuando la entrada proviene de una notificación, EXP-15 (tramo de llegada — el resto de EXP-15 se resuelve antes de esta pantalla). | Original + fortalecimiento UF-15 |
| 8. Riesgo UX | Heredar un caso a ciegas — repetir preguntas ya respondidas por el cliente. | Sin cambios |
| 9. Criterio de éxito | El Asesor nombra de memoria los datos clave del cliente sin habérselos vuelto a preguntar. | Sin cambios |
| 10. Precondiciones | Existe una intención confirmada. La oportunidad puede no existir aún (creación) o existir previamente (actualización), convergiendo siempre sobre la misma fuente de verdad definida por CRM/Pipeline (Product Patterns Cap. 6, §1). Alcance de rol suficiente sobre esa oportunidad (MPA §9). | Recorrido #2 (recuperado literalmente en esta sesión) |
| 11. Postcondiciones | El Lead queda persistido contra la única fuente de verdad, estado "en curso", asesor asignado. | Recuperado literalmente en esta sesión |
| 12. Estado esperado al abandonar | Si había edición de datos sin guardar, no se pierde; si vuelve más tarde, el Lead sigue en el mismo estado en que lo dejó. | Recuperado literalmente en esta sesión |
| 13. Dependencias | Consume datos de contacto ya conocidos y el estado del Lead. Habilita las tres bifurcaciones siguientes — SCR-04, SCR-04b y SCR-05 — es el nodo central del que dependen todas. | Recuperado literalmente en esta sesión |
| 14. Errores de experiencia previstos | Conflicto de edición — si otro canal o persona actualiza el mismo Lead casi a la vez, la segunda escritura se informa del conflicto antes de aplicarse, nunca sobrescritura silenciosa (Cap. 6, §5; MPX Cap. 9); vista vacía si es un Lead recién creado sin historial todavía. | Recuperado literalmente en esta sesión |

Verificado: campos 11-14 no contradicen los fortalecimientos de campos 2, 3 y 7; ninguno de los
campos 4, 5, 6, 8, 9 fue tocado; el destino permanece el Lead exacto; el motivo de la notificación
queda declarado como contexto recibido, sin definir su mecanismo visual.

**Estado final (actualizado 2026-08-10): `EXP-15 — PERSISTIDO Y CERRADO. UF-15 — IMPLEMENTADO Y
VERIFICADO POR TRAZADO ESTÁTICO + VALIDACIÓN INTERACTIVA PARCIAL. SCR-03 — SINCRONIZADO Y
FORTALECIDO PARA UF-15. WIREFRAME UF-15 — APROBADO. MOCKUP UF-15 — APROBADO. PROTOTIPO — 
IMPLEMENTADO.`** Ciclo completo recorrido: EXP → UF → SCR (reutilizado) → Wireframe → Mockup →
Prototipo → validación interactiva. La validación interactiva se completó solo para el escenario
de entrada normal (evidencia real, captura de pantalla) y para la integridad de la composición
existente de SCR-03; el resto de los escenarios (Asignación nueva, Mensaje sin responder, Alto
valor, coexistencia con atribución de campaña, reset del contexto) quedaron **NO VERIFICABLES por
limitación del entorno** (sin ruta de navegación de regreso desde SCR-03 hacia la lista de
Pipeline dentro del propio Prototipo, y sin mecanismo de recarga/pestaña nueva funcional en este
entorno) — nunca se declaró PASA por inferencia de trazado estático o lógica JS. No se modificó
ningún otro Screen Contract.

---

## D. Reconciliación histórica pendiente

Esta sección **documenta la discrepancia entre numeración histórica y post-compactación sin
resolverla** — ninguna decisión de renumeración, fusión o absorción se toma en este documento.

- No se resuelve si el recorrido post-compactación "CRM/Pipeline → Analítica" (#6 actual) es o
  no el mismo recorrido que el histórico #4 "Inicio → Analítica" — comparten módulo destino
  (Analítica) pero no el mismo disparador/módulo origen declarado (Inicio vs. CRM/Pipeline).
- No se resuelve si la "Reasignación de Lead" (histórico #6, Task Flow, UF-04b ya construido
  dentro del recorrido #1) queda completamente cubierta por UF-04b, o si la reevaluación
  posterior del candidato "Equipo & Organización → CRM/Pipeline" (rechazado como "no genera
  recorrido nuevo", ver `project_ux_blueprint_completado_fase_product_design.md`) contradice o
  reafirma esa cobertura. Se documenta como **conflicto histórico**, no como error a corregir
  aquí.
- No se resuelve si el recorrido #7 actual ("Conversaciones → Catálogo & Comercial") cubre
  íntegramente al histórico #7 ("Cotización dentro de una conversación o Lead") — el histórico
  #7 vive también, parcialmente, dentro de UF-04 del recorrido #1 (bifurcación de cotización).
  Se documenta como **relación parcial**, no como equivalencia.
- El hallazgo de la Sección B.2 (ninguno de los 9 recorridos históricos cubre la Etapa 6 —
  Aprendizaje/Learning Loop) permanece sin resolver; no se propone aquí ningún recorrido nuevo
  para cubrirla.
- La Etapa 6 del Journey Maestro v2 tampoco tiene, todavía, ningún EXP/UF/SCR propio en ninguna
  numeración — ni histórica ni post-compactación.

---

## E. Matriz de trazabilidad

| ID histórico | Recorrido histórico | Artefacto construido posteriormente | Relación | Estado |
|---|---|---|---|---|
| #1 | Lead → Close Won | #1 | Coincidente | Congelado |
| #2 | Conversación → Lead | #2 | Coincidente | Congelado |
| #3 | Inicio → Acción priorizada | #3 | Coincidente | Congelado |
| #4 | Inicio → Analítica | CRM/Pipeline → Analítica | Pendiente de reconciliación | No resolver |
| #5 | Campaña → Lead → Pipeline | #5 | Coincidente | Congelado |
| #6 | Reasignación | Reevaluación posterior de Equipo | Conflicto histórico | No resolver |
| #7 | Cotización conversación/Lead | #7 + funcionalidad de #1 | Parcialmente relacionado | No resolver |
| #8 | Notificación → Acción | Candidato Notificaciones | Coincidente | Bloqueado |
| #9 | Autenticación → Inicio | No construido | Sin correspondencia | Pendiente/bloqueado |

---

## F. Auditoría de Estado Consolidado (Fase 4, aprobada 2026-08-09)

Fotografía única y definitiva del estado de Product Design tras la reconciliación de las Fases 1-4
(recuperación del Inventario Maestro, cierre de discrepancias históricas, clasificación de
pendientes por capa). **Esta sección actualiza el estado de los ítems #4, #6, #7, #8, #9 de la
Matriz de trazabilidad de la Sección E** — la Sección E no se modifica, queda como registro del
momento de creación del documento; esta sección F es la vigente para el estado actual.

### F.1 — Inventario histórico #1→#9, estado actual

| # | Recorrido histórico | Estado actual | Evidencia | Observación |
|---|---|---|---|---|
| 1 | Lead → Close Won | CONGELADO | Sección C.1 (EXP-01→05, UF-01→05+04b, SCR-01→05+04b) | Coincide por identidad, no solo por cobertura |
| 2 | Conversación → Lead generado | CONGELADO | Sección C.3 — mismo nombre, SCR-03 fortalecido 2/14 campos en ambas instancias | Reserva: identidad exacta de los 2 campos históricos no verificada campo a campo |
| 3 | Inicio → Acción priorizada (Asesor) | CONGELADO | Sección C.2 (EXP-06/07, SCR-06, UF-06 recuperados literalmente) | Coincide por identidad |
| 4 | Inicio → Analítica (Admin/Supervisor) | RESUELTO FUERA DE PRODUCT DESIGN | `MAIEK_AI_PRODUCT_PATTERNS.md` Cap. 1 §3/§4/§8; Roadmap, entrada 2026-08-09 | Cubierto por el Shell de Navegación, no por ningún Screen Contract — sin modificar SCR-06 ni SCR-07 |
| 5 | Campaña → Lead atribuido → Pipeline | CONGELADO | Roadmap, entrada 2026-08-08 (SCR-03 fortalecido 1/14 campo) | Coincide por identidad |
| 6 | Reasignación de Lead | EN ESPERA DE EVIDENCIA | Sección C.1 (UF-04b/SCR-04b) | No construido como recorrido propio — cubierto incidentalmente dentro de #1; disparador agregado ("Equipo → Pipeline") no cubierto; discrepancia de Actor (SCR-04b vs. Prototipo) sin resolver |
| 7 | Cotización dentro de conversación/Lead | PRODUCT DESIGN CUBIERTO / IMPLEMENTACIÓN REALIZADA — PARCIALMENTE VERIFICADA INTERACTIVAMENTE | Sección C.1 (UF-04/SCR-04) + Roadmap, recorrido #7 (EXP-13/14) + Roadmap, entrada 2026-08-09 (implementación) + entrada 2026-08-10 (PEND-#7-03 resuelto) | Diseño completo; botón "Adjuntar a conversación" implementado reutilizando el patrón de `#btn-compartir-catalogo` — agrega el contenido comercial a `#messages` y muestra el `#toast` de confirmación. PEND-#7-03 (scroll automático al volver a Bandeja) — **RESUELTO (2026-08-10)**: el tramo "adjuntar" verificado interactivamente con evidencia real; el tramo "scroll al llegar a Bandeja" verificado solo por trazado estático — SCR-03 no tiene, por diseño ya existente y ajeno a este ajuste, ninguna ruta de navegación de regreso a Bandeja dentro del Prototipo, así que el round-trip completo no pudo ejercitarse con clics reales. |
| 8 | Notificación → Acción específica | EN IMPLEMENTACIÓN — VALIDACIÓN INTERACTIVA PARCIAL (limitación del entorno) | Sección C.6 (EXP-15, UF-15, SCR-03 sincronizado, Wireframe, Mockup, Prototipo implementado); `MAIEK_AI_PRODUCT_PATTERNS.md` Cap. 8 (Notificaciones, persistido 2026-08-10) | Bloqueo original levantado con la persistencia de Cap. 8. Destino: Lead exacto en CRM/Pipeline, vía SCR-03 fortalecido (sin SCR nuevo). Ciclo EXP→UF→SCR→Wireframe→Mockup→Prototipo completo. Entrada normal e integridad de SCR-03 verificadas interactivamente; resto de escenarios no verificable por limitación del entorno (sin ruta de regreso desde SCR-03 a la lista de Pipeline). Pendiente no bloqueante: asignación evento↔canal, historial, validación interactiva completa |
| 9 | Autenticación → Inicio | BLOQUEADO POR ARQUITECTURA | `MAIEK_AI_PRODUCT_ARCHITECTURE.md` §2 — "Autenticación" no es uno de los 9 módulos del Mapa completo | Vacío más profundo que #8: falta reconocimiento a nivel MPA, no solo capítulo de patrón |

### F.2 — Reconciliación con los recorridos construidos posteriormente

- Histórico #1 ↔ construido #1: identidad.
- Histórico #2 ↔ construido #2: coincidente por nombre, target (SCR-03) y magnitud, con reserva.
- Histórico #3 ↔ construido #3: identidad.
- Histórico #4 vs. construido "CRM/Pipeline → Analítica": **sin correspondencia deliberada** — el
  comportamiento demostrado (Sidebar desde Inicio, vista de equipo Admin/Supervisor) satisface la
  necesidad del histórico #4; el nombre del recorrido construido y su pendiente (UF-08) apuntan a
  una necesidad distinta, sin resolver.
- Histórico #5 ↔ construido #5: identidad.
- Histórico #6 vs. Reasignación construida: no existe recorrido "#6" propio — mecanismo cubierto
  como bifurcación dentro de #1 (UF-04b/SCR-04b). Diferencia real sin resolver: disparador desde
  una vista de carga agregada (Equipo & Organización) no construido; discrepancia de Actor.
- Histórico #7 vs. "Conversaciones → Catálogo & Comercial" + Cotizar de #1: territorio dividido —
  mitad "adjunta" (UF-04/SCR-04, contrato correcto, sin implementación funcional) + mitad
  "compartida" (construido #7, funcional). Deuda de implementación, ya clasificada.
- Histórico #8 (2026-08-10): **correspondencia directa** — EXP-15/UF-15 construidos, SCR-03
  fortalecido por reutilización, Wireframe y Mockup aprobados, Prototipo implementado (ver C.6).
  Ya no es "sin correspondencia".
- Histórico #9: sin ninguna correspondencia — no construido bajo ningún nombre o número.

### F.3 — Pendientes separados por capa

- **Implementación**: PEND-#7-03 (scroll automático al regresar a Bandeja tras adjuntar) — **RESUELTO (2026-08-10)**, ver F.1 fila 7. Queda como deuda separada, no bloqueante: verificación interactiva del tramo "llegar a Bandeja con el scroll ya aplicado", imposibilitada por la ausencia de navegación de SCR-03 a Bandeja en el Prototipo (gap pre-existente, fuera de alcance de este ajuste).
- **Documentación**: discrepancia de Actor entre SCR-04b y el Prototipo (#6) — sin resolver.
- **Arquitectura**: pertenencia de Autenticación (#9) al corpus.
- **Product Patterns**: capítulo de Notificaciones (#8) — **RESUELTO (2026-08-10)**, ver Cap. 8 de `MAIEK_AI_PRODUCT_PATTERNS.md` y Sección C.6.
- **Gobernanza**: Learning Loop — resuelto, vive en MPX Cap. 11, no en Product Design.
- **Evidencia pendiente**: gestión agregada de carga (#6); validación visual/interactiva externa del Prototipo (todo el recorrido, no solo UF-08); validación interactiva completa de UF-15 (Asignación nueva, Mensaje sin responder, Alto valor, coexistencia con campaña, reset del contexto — no verificables por limitación del entorno, ver C.6). Tabla/Data Grid completa de la Vista principal de Pipeline — **RESUELTA (2026-08-10)**, ver C.4.3: Filtros/Ordenamiento/Paginación reales implementados y validados interactivamente contra el Screen Contract, sin crear artefactos de Product Design nuevos. Queda `[PEND]` únicamente "buscar" (búsqueda de texto libre) — citado en el campo 5 del Screen Contract pero sin patrón visual ya establecido en el Prototipo ni definido con precisión en Cap. 6 §3; no se inventó un mecanismo para cubrirlo.
- **Product Design (#8)**: asignación evento↔canal concreto; historial de notificaciones — ninguno bloqueante. Wireframe/Mockup/Prototipo ya no son pendientes: completados (ver C.6).

**Vista principal de Pipeline sin Screen Contract — RESUELTA (2026-08-09/10).** Ya no es un
pendiente de diseño: Screen Contract propio construido y aprobado (ver C.4.3). Lo que permanece
abierto, y en una categoría distinta, es la implementación completa de su Tabla/Data Grid (hoy
solo el subconjunto ilustrativo necesario para demostrar UF-08) — deuda de implementación, no de
Product Design.

### F.4 — UF-08 (Pipeline → Analítica contextual) — COMPLETADO (2026-08-09/10)

Entidad independiente, tratada por separado del histórico #4.

**UF-08 ya forma parte del rango UF-07→UF-11 correspondiente al recorrido CRM/Pipeline →
Analítica** — no fue un ID "reservado" ni inexistente. Su necesidad cognitiva quedó confirmada
como **ya cubierta por EXP-08→EXP-12** (ver C.4.2) — no se creó ningún EXP nuevo. Su mecanismo
concreto de transición quedó completado mediante Gap Analysis → Screen Contract de la Vista
principal de Pipeline → Wireframe → Mockup → Prototipo (ver C.4.3, con el detalle completo). El
contexto transportado quedó definido como **el criterio/señal/segmento que originó la
consulta** — nunca una lista de IDs de Leads ni una selección múltiple obligatoria.

**Estado final: `UF-08 — IMPLEMENTADO, FUNCIONALMENTE CONSISTENTE, VALIDACIÓN
VISUAL/INTERACTIVA EXTERNA PENDIENTE.`** No se crea ningún User Flow nuevo, ni UF-14. Único punto
que permanece abierto, y de forma explícita como no obligatorio: si la preservación exacta del
filtro/conjunto al retornar a Pipeline debe elevarse de comportamiento deseable a requisito
contractual — ver C.4.3, campo 12 del Screen Contract de la Vista principal.

### F.5 — Learning Loop (Etapa 6, Journey Maestro v2)

Cerrado como **no pendiente de Product Design**: *"El Journey Maestro v2 no implica que una
pantalla de Analítica deba ejecutar el cierre completo del Learning Loop. La evidencia de MPX
Cap. 11 indica que la retroalimentación hacia gobernanza ocurre como proceso humano, no como
gatillo automático de interfaz."* No se creó recorrido ni se modificó SCR-07.

### F.6 — Conclusión

**Con la evidencia disponible al 2026-08-09, ningún territorio amerita abrir un nuevo ciclo de
Product Design.** Los seis recorridos con necesidad cognitiva demostrable (#1, #2, #3, #4, #5, y
el mecanismo de #6/#7) ya están congelados, cubiertos fuera de Product Design, o cubiertos con
implementación pendiente. Los cuatro restantes (#6 agregado, #7 implementación, #8, #9, UF-08)
requieren trabajo de otra capa antes de calificar como candidatos a un nuevo recorrido.

**Actualización (2026-08-10):** #8 sale de esa lista — ver F.7. Quedan tres pendientes de otra capa
(#6 agregado, #7 implementación, #9) más UF-08 (validación visual/interactiva externa) y UF-15
(validación interactiva completa, no verificable por limitación del entorno — ciclo de diseño e
implementación ya completo).

### F.7 — Histórico #8 (Notificación → Acción específica) — EN IMPLEMENTACIÓN, VALIDACIÓN INTERACTIVA PARCIAL (actualizado 2026-08-10)

Entidad construida íntegramente en esta sesión, sin recuperación de transcript — distinto del
resto de esta Sección F, que reconcilia hallazgos de recuperación histórica. El bloqueo original
("BLOQUEADO POR PRODUCT PATTERNS") se resolvió en dos pasos: (1) persistencia de
`MAIEK_AI_PRODUCT_PATTERNS.md` Capítulo 8 — Notificaciones; (2) ciclo completo de Product Design —
Gap Analysis → Gate de decisiones de Experience Design → EXP-15 → UF-15 → verificación de
reutilización de SCR-03 (sin Screen Contract nuevo) → sincronización documental de SCR-03 (ver
C.6, incluida la corrección de una desactualización encontrada en los campos 1 y 3 de SCR-03,
independiente de este recorrido) → Wireframe → Mockup → Prototipo implementado → validación
interactiva.

El ciclo completo de Product Design y Product Patterns para este recorrido ya está recorrido de
punta a punta: EXP → UF → SCR (reutilizado) → Wireframe → Mockup → Prototipo. Lo único que
permanece abierto es la validación interactiva completa — se intentó de buena fe (archivo movido
dentro del proyecto para habilitarla, múltiples intentos de interacción real) y se obtuvo
evidencia real para el escenario de entrada normal y para la integridad de la composición de
SCR-03; el resto de los escenarios de notificación (Asignación nueva, Mensaje sin responder, Alto
valor, coexistencia con atribución de campaña, reset del contexto) no pudo verificarse por una
limitación del entorno — SCR-03 no tiene, por diseño ya existente y fuera de alcance de UF-15,
ninguna ruta de navegación de regreso hacia la lista de Pipeline, y el entorno no permitió recargar
la página ni abrir una pestaña nueva funcional para retomar desde ahí. No se agregó navegación
auxiliar para sortear esto — decisión explícita del usuario, para no modificar la interfaz
únicamente para facilitar una validación.

**Estado final: `EXP-15 — PERSISTIDO Y CERRADO. UF-15 — IMPLEMENTADO Y VERIFICADO POR TRAZADO
ESTÁTICO + VALIDACIÓN INTERACTIVA PARCIAL. SCR-03 — SINCRONIZADO Y FORTALECIDO PARA UF-15.
WIREFRAME UF-15 — APROBADO. MOCKUP UF-15 — APROBADO. PROTOTIPO — IMPLEMENTADO.`** No declarado en
ningún punto como validación visual/interactiva completa. No bloqueante: asignación evento↔canal
concreto, historial de notificaciones — ambos ya declarados fuera de alcance de UF-15 (ver C.6).

---

## Cierre

Este documento **no reemplaza ningún Approved existente** — es el repositorio durable de Product
Design y Journey Design de Maiek AI: el lugar donde viven, con IDs permanentes y trazables, el
Journey Maestro y las tablas EXP/UF/SCR de cada recorrido, para que futuras sesiones puedan
citarlas sin depender de que el historial de conversación siga disponible. Cambios futuros a este
documento deben seguir el mismo estándar de evidencia usado para construirlo: cita literal de la
fuente, o marca explícita de lo no recuperado — nunca reconstrucción por inferencia.

## Control de versiones

| Versión | Fecha | Cambio |
|---|---|---|
| 1.0 | 2026-08-09 | Creación del documento. Recuperación documental desde el transcript crudo de la sesión `7684292f-47eb-4a30-a90c-09f7cc5785e9` tras la pérdida por compactación de contexto de: Inventario Maestro Histórico (9 recorridos), Journey Maestro (v1 y v2/aprobada), EXP-01→07, UF-01→06 (parcial), SCR-01→06 (campos 1-9 completos, 10-14 parciales). Ningún documento Approved, Product Patterns, MPA, MPX, UX Blueprint, AI Architecture, SCR congelado ni el Prototipo fue modificado en este proceso. Ningún recorrido nuevo fue iniciado. |
| 1.1 | 2026-08-09 | **Agrega la Sección F (Auditoría de Estado Consolidado, Fase 4).** Persiste, sin reconstruir ni alterar ningún dato, la auditoría ya aprobada por el usuario: estado actual de los 9 recorridos históricos, reconciliación con los recorridos construidos posteriormente, pendientes separados por capa (implementación/documentación/arquitectura/Product Patterns/gobernanza/evidencia), caracterización de UF-08 como entidad independiente sin EXP/UF/SCR propio, cierre del Learning Loop fuera de Product Design, y la conclusión de que ningún territorio actual tiene una necesidad cognitiva nueva demostrada para abrir otro recorrido. La Sección F actualiza el estado de los ítems #4/#6/#7/#8/#9 de la Matriz de trazabilidad (Sección E), que no fue modificada — queda como registro histórico del momento de creación del documento. Ningún documento Approved, artefacto congelado ni el Prototipo fue modificado. |
| 1.2 | 2026-08-09 | **Reconciliación documental post-Auditoría de Estado Maestro.** Corrige 3 hallazgos verificados por lectura directa contra el Roadmap y la memoria: (1) F.1/F.3 — estado del histórico #7 actualizado de "IMPLEMENTACIÓN PENDIENTE" a "IMPLEMENTACIÓN REALIZADA — VERIFICADA POR TRAZADO ESTÁTICO", ahora consistente con `MAIEK_AI_IMPLEMENTATION_ROADMAP.md`; se registra PEND-#7-03 (scroll automático post-adjunto, no bloqueante). (2) F.4 — corrige la descripción de UF-08: no es un ID "reservado ni inexistente", cae dentro del rango UF-07→UF-11 ya asignado al recorrido CRM/Pipeline → Analítica; lo pendiente es su mecanismo, no su creación. (3) F.3 — se agrega "Vista principal de Pipeline sin Screen Contract" a los pendientes por capa (Product Design, condicionado a evidencia), recuperada de `project_pipeline_vista_principal_sin_screen_contract_pendiente.md` (memoria), ausente hasta ahora de la Sección F. No se creó EXP, UF ni SCR nuevo. No se modificó ningún documento Approved, artefacto congelado ni el Prototipo. No se abrió ningún recorrido. |
| 1.3 | 2026-08-09 | **SCR-07 (Analítica) recuperado literalmente del transcript y fortalecido puntualmente** (Sección C.4.1, nueva), como cierre de la dependencia "Vista principal de Pipeline sin Screen Contract" y de la decisión de diseño sobre la naturaleza del contexto de UF-08 (criterio/señal/segmento, no una lista de IDs de Leads). Campos modificados: 2 (Disparador de entrada — declara la segunda vía, contextual desde Pipeline), 3 (Información que recibe — precisa que el contexto es un criterio, no un conjunto de Leads), 10 (Precondiciones — cita la responsabilidad ya declarada en el Screen Contract de la Vista principal), 13 (Dependencias — cierra el punto (a), Vista principal ya resuelta; mantiene abierto el punto (b), mecanismo visual), 14 (Errores de experiencia previstos — ajuste terminológico "preservación"→"representación"). Campos 1, 4, 5, 6, 7, 8, 9, 11 y 12 permanecen sin cambios. No se modificó EXP-08→EXP-12 ni UF-07→UF-11. No se creó Wireframe, Mockup ni Prototipo. |
| 1.4 | 2026-08-10 | **Persistencia documental de trabajo ya aprobado — sin rediseño.** Agrega Secciones C.4.2 (EXP-08→EXP-12 literal, recuperado del transcript — tabla completa, con EXP-11 marcado `NO RECUPERADO — NO ENCONTRADO EN LA FUENTE CONSULTADA` en Riesgo UX y Criterio de éxito, únicos campos no recuperados de toda la tabla) y C.4.3 (Screen Contract de la Vista principal de Pipeline completo — 14 campos, construido y aprobado en esta sesión, no recuperado del transcript; resumen del Wireframe y Mockup de UF-08 ya aprobados, incluida la corrección de correspondencia "Requiere atención" → KPI "Estancados +5 días"; registro documental del estado de implementación del Prototipo). Corrige F.3 (elimina "Vista principal de Pipeline sin Screen Contract" de los pendientes — resuelta; deja como pendiente distinto la Tabla/Data Grid completa, de implementación) y F.4 (UF-08 pasa de "pendiente su mecanismo" a completado — estado final `IMPLEMENTADO, FUNCIONALMENTE CONSISTENTE, VALIDACIÓN VISUAL/INTERACTIVA EXTERNA PENDIENTE`). Ninguna decisión fue reabierta ni reinterpretada — se persiste exactamente lo ya aprobado en las rondas anteriores de esta sesión. No se creó EXP, UF ni SCR nuevo. No se modificó SCR-07 (ya correctamente persistida en 1.3, verificado antes de esta entrada). No se modificó el Prototipo. |
| 1.5 | 2026-08-10 | **Corrección de estado documental — SCR-07, campos 10, 13 y 14 (Sección C.4.1).** El Gate de Estabilización de UF-08 encontró que estos tres campos seguían declarando "pendiente" el mecanismo de representación visual del criterio/segmento, pese a que ya había sido resuelto mediante Wireframe, Mockup e implementación del Prototipo, persistidos en la Sección C.4.3 (v1.4) — desactualización de estado, no contradicción de decisión. Corregido para reflejar: representación visual resuelta (Wireframe/Mockup/Prototipo, ver C.4.3), incluida la corrección de correspondencia "Requiere atención" → KPI "Estancados +5 días"; pendiente únicamente de validación visual/interactiva externa — no se declara esa validación como completada. No se modificó ningún otro campo de SCR-07, ni su composición base, ni EXP-08→EXP-12, ni UF-08, ni el Screen Contract de Pipeline, ni Wireframe, ni Mockup, ni el Prototipo. No se tomó ninguna decisión de producto nueva. |
| 1.6 | 2026-08-10 | **Histórico #8 (Notificación → Acción específica) — EXP-15, UF-15 y fortalecimiento de SCR-03 (Sección C.6, nueva).** Tras la persistencia de `MAIEK_AI_PRODUCT_PATTERNS.md` Capítulo 8 (Notificaciones), se ejecutó el ciclo completo de Product Design: Gap Analysis → Gate de decisiones de Experience Design → EXP-15 → UF-15 → verificación de reutilización de SCR-03 (sin Screen Contract nuevo). Durante la verificación se recuperaron literalmente, desde el transcript de la sesión original, los campos 11-14 de SCR-03 (Postcondiciones, Estado esperado al abandonar, Dependencias, Errores de experiencia previstos), nunca antes transcritos a este documento pese a que ya se afirmaba haberlos recuperado — y se encontró, además, que los campos 1 (Objetivo) y 3 (Información que recibe) persistidos en la Sección C.1 mostraban la versión anterior a los fortalecimientos ya aprobados de los recorridos #2 y #5, respectivamente. La Sección C.6 persiste la versión sincronizada y vigente de los 14 campos de SCR-03, con procedencia declarada campo por campo, sin alterar el bloque de recuperación literal original en la Sección C.1 (queda como registro histórico). Se actualiza el estado de #8 en F.1, F.2, F.3 y F.6, y se agrega F.7. Ninguna decisión de EXP-15/UF-15 fue reabierta ni reevaluada en esta ronda — se persiste exactamente lo ya aprobado. No se creó Wireframe, Mockup, Prototipo ni código. No se modificó SCR-07 ni ningún otro Screen Contract. |
| 1.7 | 2026-08-10 | **Sincronización documental — Histórico #8/EXP-15/UF-15 pasan de "LISTO PARA WIREFRAME" al estado real alcanzado.** Entre la persistencia v1.6 y esta entrada se completaron, en la misma sesión, Wireframe UF-15 (aprobado), Mockup UF-15 (aprobado), implementación en el Prototipo, y un intento de buena fe de validación interactiva real (archivo movido de scratchpad a `whatsapp-agentkit/prototipos/` para habilitarla) — nada de esto había sido persistido todavía, mismo tipo de brecha ya identificado antes para UF-08. Esta entrada sincroniza únicamente el estado documental: Sección C.6 (bloque "Estado final"), F.1 (fila 8), F.2 (línea histórico #8), F.3 (pendientes), F.6 (nota de actualización) y F.7 (reescrita para reflejar el ciclo completo) — todas actualizadas para reflejar: EXP-15 persistido y cerrado; UF-15 implementado y verificado por trazado estático + validación interactiva parcial; SCR-03 sincronizado y fortalecido; Wireframe y Mockup aprobados; Prototipo implementado. La validación interactiva se completó solo para "entrada normal" e "integridad de SCR-03" (evidencia real); el resto de los escenarios de notificación quedan explícitamente **NO VERIFICABLES por limitación del entorno** — SCR-03 no tiene ruta de navegación de regreso a la lista de Pipeline (comportamiento ya existente, fuera de alcance de UF-15, no modificado) y el entorno no permitió recargar la página ni abrir pestañas nuevas funcionales. No se declaró en ningún punto validación completa. No se modificó EXP-15, UF-15, SCR-03, Wireframe, Mockup, Product Patterns, UX Blueprint, ningún otro EXP/UF/SCR, ni el Prototipo. No se creó navegación auxiliar ni botones de testing — decisión explícita del usuario. No se reinterpretó ninguna decisión histórica ni se reescribió ninguna entrada previa de este Control de versiones. |
| 1.8 | 2026-08-10 | **Pipeline Data Grid — implementado contra el Screen Contract ya persistido en C.4.3, sin crear artefactos de Product Design nuevos.** No se reabrió EXP-08→EXP-15, ningún UF/SCR existente, Wireframe, Mockup, Product Patterns, UX Blueprint ni arquitectura. Se reemplazó el subconjunto ilustrativo de 3 Leads estáticos por un dataset de demostración de 12 Leads con Filtros, Ordenamiento y Paginación reales, reutilizando literalmente `.priority-item`/`.priority-item.top`, `.proto-btn`/`.proto-controls` — ningún componente ni token nuevo (ver nota de actualización en C.4.3). Los filtros ya existentes de UF-08 (`Requiere atención`/`Canal: Campañas`) ahora también filtran genuinamente la lista, completando una responsabilidad que el propio Wireframe de UF-08 ya declaraba ("el filtro activo es el criterio"), sin redefinirla. Un elemento no cubierto por el Screen Contract con patrón visual existente — "buscar" (texto libre) — se registra `[PEND]`, no se inventó. Verificado por trazado estático + sintaxis JS real (`node -c`, sin errores, balance de llaves 110/110) y, por primera vez en esta sesión, **validación interactiva real y completa de lo probado** en el Browser pane (tras mover el Prototipo a `whatsapp-agentkit/prototipos/`, dentro del proyecto): navegación, Ordenamiento (2 criterios, confirmado por lectura del DOM), Paginación (3 páginas/12 resultados, avance, deshabilitado en extremos), Filtro `Requiere atención` (5/5 resultados) y selección de Marcela Rojas → SCR-03 (composición intacta). No probado interactivamente: filtro `Canal: Campañas`, estado vacío (0 resultados) — no declarados como validados. Se actualiza F.3 (Tabla/Data Grid ya no pendiente) y C.4.3 (nota de actualización, sin alterar el Screen Contract ni el resto de esa sección). No se modificó ningún otro documento. |
| 1.9 | 2026-08-10 | **PEND-#7-03 — scroll automático al volver a Bandeja tras adjuntar una cotización — resuelto, sin reabrir UF-07, EXP-13/14, SCR-04 ni ningún artefacto de Product Design.** Se agregó una bandera de estado (`pendingScrollBandeja`) que el handler de `#btn-adjuntar` activa al agregar el ítem a `#messages` (reutilizando exactamente el mismo patrón ya usado por `#btn-compartir-catalogo` para el contenido agregado); `showScreen()` la consume — cuando el destino es `bandeja` y la bandera está activa, aplica `scrollTop = scrollHeight` sobre `#messages` y la limpia. No se creó navegación nueva ni botón de regreso — se reutilizó `showScreen`, la función central ya existente, sin alterar su firma ni las demás llamadas. Verificado por trazado estático y sintaxis JS real (`node -c`, sin errores, balance de llaves 111/111). **Validación interactiva parcial, con evidencia real**: el tramo "Cotizar → Adjuntar a conversación" se ejecutó con clics reales en el Browser pane y se confirmó, leyendo el DOM, que el ítem de cotización se agrega efectivamente a `#messages` (mismo mecanismo que activa la bandera). El tramo "llegar a Bandeja con el scroll ya aplicado" **no pudo ejercitarse con clics reales**: se descubrió que SCR-03 (`#screen-pipeline`) no tiene, por diseño ya existente y ajeno a este ajuste, ninguna ruta de navegación de regreso a Bandeja dentro del Prototipo — mismo tipo de gap ya identificado antes para UF-15. No se agregó navegación para sortearlo, seguiendo la regla explícita de esta ronda. Ese tramo queda verificado únicamente por trazado estático (lectura directa de `showScreen()`, lógica simple y sin ambigüedad). Se actualiza F.1 (fila 7) y F.3 (PEND-#7-03 resuelto, con la salvedad anotada). No se modificó ningún otro documento ni artefacto de Product Design. |
