# Maiek AI — UX Blueprint

**Versión Draft v1.0**

| | |
|---|---|
| Documento | Maiek AI UX Blueprint |
| Proyecto | Maiek AI |
| Versión | Draft v1.0 |
| Estado | **Draft** — en construcción incremental, capítulo por capítulo |
| Fecha de creación | 2026-08-08 |
| Autor | Claude, a pedido de Jesús Millones |
| Última actualización | 2026-08-08 — Auditoría Integral completada y correcciones aplicadas; Draft en congelamiento funcional |

## Control de versiones

| Versión | Fecha | Autor | Descripción |
|---|---|---|---|
| Draft v1.0 (borrador inicial) | 2026-08-08 | Claude, a pedido de Jesús Millones | Redacción incremental de Capítulos 0 y 1 (Propósito, alcance, jerarquía; Principio Central y matriz de trazabilidad de los 6 conceptos). |
| Draft v1.0 (continuación) | 2026-08-08 | Claude, a pedido de Jesús Millones | Capítulos 2 (Arquitectura del Recorrido) y 3 (La Siguiente Mejor Decisión, con resolución formal de "Acción antes que observación" vs. "Comprensión precede a la acción" y ejemplo aplicado). |
| Draft v1.0 (corrección de gobernanza) | 2026-08-08 | Claude, a pedido de Jesús Millones | Dos correcciones por decisión explícita del usuario, ninguna retroactiva ni silenciosa: (1) el Principio Central del Capítulo 1 ("Maiek AI no es un espectador del flujo de trabajo...") queda confirmado como la única versión vigente, reemplaza en definitiva a la formulación previa de apertura de fase. (2) La jerarquía documental del §0.1 queda corregida — el UX Blueprint se reclasifica como especificación derivada al mismo nivel que `MAIEK_AI_PRODUCT_PATTERNS.md` (hermano, no superior ni subordinado), respetando la cadena `Framework → MPA → MDL → CDS → MPX → Especificaciones derivadas` ya *Approved* en MPX, e inmediatamente antes de User Flows en el orden de consumo. |
| Draft v1.0 (confirmación de alcance + Capítulo 4) | 2026-08-08 | Claude, a pedido de Jesús Millones | El usuario aclaró que una observación recibida sobre "identidad emocional" provino de una prueba no oficial con otro modelo (Gemini) y no debía tratarse como instrucción — no se aplicó ningún cambio en esa dirección. Tras análisis conjunto, se confirmó que el UX Blueprint se mantiene como especificación derivada (no como manifiesto de marca/identidad, territorio ya cubierto por Framework y MDL Cap. 0/2) y que su valor diferencial es la arquitectura de la experiencia. Se reorganizaron los Capítulos 4 a 8 en torno a ese eje (Arquitectura Cognitiva, Carga Cognitiva y Contexto, Continuidad de Tarea, Atención/Prioridad/Ritmo, Consistencia de los Recorridos) y se redactó el Capítulo 4 (marco de los tres recursos finitos: atención, memoria de trabajo, contexto, y la Regla del Presupuesto Cognitivo). |
| Draft v1.0 (Capítulos 5 a 12, redacción completa) | 2026-08-08 | Claude, a pedido de Jesús Millones | Por pedido explícito del usuario de no interrumpir la construcción hasta completar el documento (mismo criterio que Product Patterns: construir todo, luego auditoría integral), se redactaron en una sola tanda: Cap. 5 (Gestión de la Carga Cognitiva y el Contexto), Cap. 6 (Continuidad de Tarea: Interrupción y Recuperación de Estado), Cap. 7 (Atención, Prioridad y Ritmo de Interacción), Cap. 8 (Consistencia de los Recorridos — cierre del bloque de Arquitectura Cognitiva iniciado en el Cap. 4), Cap. 9 (El Rol de la IA en la Experiencia), Cap. 10 (Casos sin Patrón Todavía, usando la Auditoría Funcional como insumo diagnóstico no normativo), Cap. 11 (Prueba de Identidad: Checklist de Experiencia, hermano funcional del Experience Review Checklist de MPX Cap. 11) y Cap. 12 (Gobernanza y Evolución). Documento completo Capítulos 0-12, Draft v1.0, pendiente de la revisión integral acordada antes de pasar a Approved. |
| Draft v1.0 (Auditoría Integral y correcciones, cierre) | 2026-08-08 | Claude, a pedido de Jesús Millones | Auditoría Integral en 5 entregables (Arquitectura del Documento, Coherencia con el Corpus, Cobertura Funcional, Identidad y Filosofía de Maiek AI con el criterio transversal de 8 conclusiones observables, Calidad como Documento Rector de UX), cada uno revisado y ajustado por el usuario antes de continuar con el siguiente — mismo método que Product Patterns y la Auditoría Funcional. **Conclusión de la auditoría: sin contradicciones arquitectónicas relevantes con el resto del corpus; todos los hallazgos fueron de consistencia, trazabilidad, verificabilidad o claridad editorial.** Correcciones aplicadas en una sola pasada, priorizadas por el usuario en 3 niveles: **Obligatorias** — cita del Concepto 5 corregida (Cap. 1, §1.2: Framework/Simplicidad, no la sección inexistente "User-Centric Design"), Dependencias actualizadas con MPA y MDL (§0.2), dos preguntas nuevas en el Checklist (Cap. 11, §11.2: co-localización y control/foco/continuidad), regla "colapsar, no eliminar" explícita (Cap. 5, §5.4), regla de prioridad velocidad-subordinada-a-control (Cap. 7, §7.3), regla general de orientación de todo recorrido al objetivo de la tarea (Cap. 2, §2.2). **Recomendadas** — frase de derivación exclusiva del corpus (Cap. 1, §1.3), mapa de los 4 bloques del documento (Cap. 0, §0.1bis), señalamiento cruzado Cap. 3 ↔ Cap. 5, "Consecuencia para el diseño de flujos" agregada a Cap. 9 y Cap. 10, "Qué no gobierna" agregado a Cap. 12, relación entre gates por capítulo y Checklist consolidado aclarada (Cap. 11, §11.2bis). **Opcionales, aplicadas** — recorrido de ejemplo para Equipo & Organización (Cap. 2, §2.4), título del Cap. 5 ajustado de "Carga Cognitiva" a "Presupuesto de Atención y Contexto" para consistencia con el cuerpo del capítulo. Estado del documento (§12.4) actualizado a **Draft — congelamiento funcional**, explícitamente distinto de *Approved*, porque falta la fase de User Flows, Wireframes, Mockups y su validación visual. |

Cualquier modificación futura de fondo suma una fila nueva a esta tabla — este documento no se
edita en silencio, mismo criterio que el resto del corpus desde el MDL v1.1.

> Depende de [`MAIEK_AI_FRAMEWORK.md`](MAIEK_AI_FRAMEWORK.md),
> [`MAIEK_AI_PRODUCT_ARCHITECTURE.md`](MAIEK_AI_PRODUCT_ARCHITECTURE.md) (MPA),
> [`MAIEK_AI_PRODUCT_EXPERIENCE.md`](MAIEK_AI_PRODUCT_EXPERIENCE.md) (MPX),
> [`MAIEK_AI_DESIGN_SYSTEM.md`](MAIEK_AI_DESIGN_SYSTEM.md) (MDL) y
> [`MAIEK_AI_PRODUCT_PATTERNS.md`](MAIEK_AI_PRODUCT_PATTERNS.md). No redefine ninguno de ellos —
> especializa únicamente aquello relacionado con la experiencia de usuario a nivel de identidad
> percibida y de recorrido entre módulos.

## Nota de gobernanza (resuelta por decisión explícita del usuario, 2026-08-08)

**Sobre el Principio Central.** El texto *"Maiek AI no es un espectador del flujo de trabajo,
sino el tejido conectivo que anticipa, simplifica y eleva cada decisión humana, transformando la
complejidad técnica en un recorrido natural, invisible y empoderador."* es la evolución oficial y
unificada del Principio Central, y **reemplaza de forma definitiva** a la formulación previa
("Cada interacción debe aportar claridad, reducir la complejidad y guiar al usuario hacia la
siguiente mejor decisión..."). Ambas formulaciones no coexisten — la anterior queda sin vigencia
a partir de esta versión; ninguna sección posterior de este documento ni de sus derivados debe
citarla.

**Sobre la Jerarquía Documental.** Queda corregido: el UX Blueprint se ubica como una
**especificación derivada**, al **mismo nivel que `MAIEK_AI_PRODUCT_PATTERNS.md`** (hermana de
Product Patterns, no superior ni subordinada a ella), respetando sin excepción la cadena oficial
ya *Approved* en `MAIEK_AI_PRODUCT_EXPERIENCE.md`: `Framework → MPA → MDL → CDS → MPX →
Especificaciones derivadas`. Dentro de ese último nivel, el UX Blueprint se sitúa **inmediatamente
antes de los User Flows** en el orden de consumo — es decir, Product Patterns y UX Blueprint son
ambos insumo directo de User Flows, no un documento insumo del otro. El diagrama y el texto del
§0.1 quedan corregidos abajo para reflejar esto.

---

# Capítulo 0 — Propósito, alcance y ubicación en la jerarquía

## 0.1 Objetivo y Naturaleza

Este documento establece el marco de identidad percibida y la lógica de transición UX para el
ecosistema Maiek AI. Su propósito no es dictar componentes visuales ni reglas operativas de
interacción, sino garantizar que la experiencia del usuario mantenga un hilo conductor coherente,
intuitivo y unificado a través de todos los módulos de la plataforma.

```
                    [ MAIEK AI FRAMEWORK ] (Filosofía Fundamental)
                              │
                              ▼
                        [ MAIEK_AI_MPA ]
                       (Arquitectura funcional)
                              │
                              ▼
                        [ MAIEK_AI_MDL ]
                        (Lenguaje visual)
                              │
                              ▼
                        [ MAIEK_AI_CDS ]
                    (Sistema de componentes)
                              │
                              ▼
                        [ MAIEK_AI_MPX ]
                    (Experiencia de producto)
                              │
                              ▼
                 ── Especificaciones derivadas ──
                 │                              │
                 ▼                              ▼
   [ MAIEK_AI_PRODUCT_PATTERNS ]    [ MAIEK_AI_UX_BLUEPRINT ]
   (Patrones por módulo)            (Identidad de experiencia
                 │                   y recorrido — este documento;
                 │                   hermano de Product Patterns,
                 │                   no superior ni subordinado)
                 └──────────────┬───────────────┘
                                ▼
                          [ USER FLOWS ]
                                │
                                ▼
                     [ WIREFRAMES & MOCKUPS ]
                                │
                                ▼
                           [ FRONTEND ]
```

## 0.1bis Cómo está organizado este documento

Los 13 capítulos de este documento se agrupan en 4 bloques. Un lector nuevo puede usar esta tabla
como mapa antes de entrar al detalle capítulo por capítulo:

| Bloque | Capítulos | Función |
|---|---|---|
| Fundamentos | 0-1 | Propósito, jerarquía documental, Principio Central y los 6 conceptos que lo derivan |
| Recorrido y Decisión | 2-3 | Continuidad al cruzar módulos; decisión y justificación dentro de una pantalla |
| Arquitectura Cognitiva | 4-8 | Modelo de tres recursos finitos (atención, memoria de trabajo, contexto) y sus 4 especializaciones |
| Cierre | 9-12 | Rol de la IA, áreas sin patrón todavía, checklist de verificación, gobernanza del documento |

## 0.2 Alcance y Gobernanza

- **Dependencias:** este documento hereda de forma directa los principios de
  `MAIEK_AI_FRAMEWORK.md`, `MAIEK_AI_PRODUCT_ARCHITECTURE.md` (MPA — los 9 módulos y el flujo de
  información entre ellos, base del Capítulo 2), `MAIEK_AI_DESIGN_SYSTEM.md` (MDL — principios de
  experiencia y lenguaje visual citados en los Capítulos 1, 2, 5 y 7),
  `MAIEK_AI_PRODUCT_EXPERIENCE.md` (MPX) y `MAIEK_AI_PRODUCT_PATTERNS.md`.
- **Consumido por:** diseñadores de flujos (User Flows), arquitectos de información, diseñadores
  de interfaces (Wireframes / Mockups) y desarrolladores Frontend como criterio de aceptación
  cualitativo.
- **Control de Versiones:** Draft v1.0 (Agosto 2026). Su evolución se gestiona de forma paralela
  a `MAIEK_AI_PRODUCT_PATTERNS.md` sin superponerse a su autoridad normativa.

## 0.3 Resolución de Solapamientos con el Corpus

Para asegurar la consistencia y evitar la redundancia, este Blueprint adopta de forma explícita
las siguientes soluciones de diseño:

1. **Herencia de Filosofía.** El principio *"La IA acompaña, nunca reemplaza"* se asume como
   premisa consolidada en el Framework y MPX. Este documento se limita a operativizar su impacto
   en la secuencia de los flujos.
2. **Síntesis de Carga Cognitiva.** Las directrices sobre claridad informativa se extraen de los
   principios 1, 4 y 10 de MDL Capítulo 0. El Blueprint las unifica bajo una restricción de flujo
   multi-pantalla.
3. **Delimitación Espacio-Temporal.** Se resuelve la aparente contradicción entre *"Acción antes
   que observación"* y *"La comprensión precede a la acción"*. El primero gobierna la disposición
   visual en pantalla; el segundo rige la secuencia del entendimiento del usuario. (Desarrollado
   en profundidad, con ejemplo aplicado, en el Capítulo 3 de este documento.)
4. **Diferenciación Léxica.** Se introduce el término *"La plataforma al servicio de las
   personas"* para evitar colisiones con el principio corporativo de *"Plataforma primero"*
   definido en Product Patterns Capítulo 8.

---

# Capítulo 1 — El Principio Central y los seis conceptos que lo derivan

## 1.1 El Principio Central

**"Maiek AI no es un espectador del flujo de trabajo, sino el tejido conectivo que anticipa,
simplifica y eleva cada decisión humana, transformando la complejidad técnica en un recorrido
natural, invisible y empoderador."**

## 1.2 Matriz de Trazabilidad Conceptual

La siguiente matriz vincula de forma explícita los seis conceptos derivados del Principio Central
con sus respectivos orígenes normativos dentro del corpus aprobado:

| # | Concepto Blueprint | Descripción UX | Documento origen | Módulo / sección de origen |
|---|---|---|---|---|
| 1 | **Continuidad Transversal** | Identidad y contexto intactos al cruzar módulos. | `MAIEK_AI_PRODUCT_EXPERIENCE.md` | Cap. 8: Cross-channel Experience |
| 2 | **La Siguiente Mejor Decisión** | Cada pantalla orienta de forma unívoca el siguiente paso. | `MAIEK_AI_PRODUCT_EXPERIENCE.md` | Cap. 3: Decision Experience |
| 3 | **Comprensión Previa** | El usuario entiende el porqué antes de actuar. | `MAIEK_AI_PRODUCT_EXPERIENCE.md` | Cap. 2: Explainability First |
| 4 | **Eficiencia Cognitiva** | Reducción drástica de elementos por pantalla. | `MAIEK_AI_DESIGN_SYSTEM.md` | Cap. 0: Principios 1, 4 y 10 |
| 5 | **Plataforma al Servicio de la Persona** | Adaptabilidad del sistema a la dinámica del usuario. | `MAIEK_AI_FRAMEWORK.md` | Principio **Simplicidad** ("la complejidad técnica nunca se traslada al usuario; la mejor solución es la más simple") |
| 6 | **Acompañamiento No Invasivo** | La IA sugiere y asiste sin arrebatar el control. | `MAIEK_AI_PRODUCT_PATTERNS.md` | Cap. 8: Principios Transversales |

Ningún concepto de esta matriz introduce una regla nueva de comportamiento, visual o de patrón —
cada uno es la especialización, al nivel de identidad de experiencia, de un principio que ya
existe en el corpus con autoridad propia. Este documento no puede citarse para justificar una
regla que no exista ya en el documento de origen señalado en la columna derecha.

## 1.3 Origen Exclusivo de las Decisiones de Experiencia

Toda decisión de experiencia de este documento deriva exclusivamente de los principios ya
definidos por este corpus documental (Framework, MPA, MDL, CDS, MPX, Product Patterns) — nunca de
convenciones de categoría, de productos externos ni de referencias fuera de este corpus. La
identidad de Maiek AI que gobierna este Blueprint es la que resulta de aplicar consistentemente
esos principios, no una comparación con ninguna otra plataforma.

---

# Capítulo 2 — Arquitectura del Recorrido

## 2.1 Propósito del Capítulo

Ni `MAIEK_AI_PRODUCT_EXPERIENCE.md` (que opera al nivel de una interacción o una pantalla) ni
`MAIEK_AI_PRODUCT_PATTERNS.md` (que opera al nivel de un patrón dentro de un módulo) definen de
forma explícita qué ocurre con la experiencia del usuario **cuando cruza de un módulo a otro**.
Este capítulo cierra esa brecha: define el recorrido (*journey*) como objeto de diseño propio,
distinto de un flujo dentro de un único módulo.

**Qué no gobierna este capítulo:** no redefine componentes (CDS), no redefine memoria técnica ni
persistencia de datos (Data Architecture), no crea módulos funcionales nuevos (MPA) y no
introduce patrones visuales nuevos — un recorrido siempre se compone de patrones y componentes
ya existentes, nunca inventa uno para resolver una transición.

## 2.2 El Recorrido como Objeto de Diseño

Un recorrido es la secuencia de pantallas, decisiones y transiciones que atraviesa un usuario
para completar una tarea que **no cabe dentro de un único módulo** de MPA (los nueve módulos:
Conversaciones, Agentes IA, CRM/Pipeline, Campañas, Catálogo & Comercial, Equipo & Organización,
Analítica, Canales & Configuración, Notificaciones). Un patrón de Product Patterns resuelve una
tarea completa **dentro** de un módulo; un recorrido de este capítulo resuelve una tarea completa
**a través de** varios módulos.

**Regla de orientación.** Todo recorrido debe acercar al usuario al objetivo principal de la
tarea que está realizando — nunca a un objetivo genérico de "explorar el sistema". Esta regla es
deliberadamente general: aplica igual a un recorrido de CRM/Pipeline (cuyo objetivo es avanzar un
Lead), uno de Analítica (cuyo objetivo es responder una pregunta concreta) o uno de Canales &
Configuración (cuyo objetivo es dejar un canal operativo) — el objetivo específico de cada tarea
lo define el módulo correspondiente (MPA, Product Patterns); este Blueprint solo exige que el
recorrido nunca se aleje de él.

Todo recorrido debe preservar tres propiedades al cruzar de un módulo a otro. La ausencia de
cualquiera de las tres constituye, por definición, una ruptura de Continuidad Transversal
(Capítulo 1, concepto 1):

1. **Continuidad de Contexto.** La información ya conocida por el sistema sobre el usuario, el
   cliente o el caso no se vuelve a pedir ni se vuelve a explicar solo porque cambió el módulo.
   Especializa Memory Experience y Cross-channel Experience (MPX Cap. 8).
2. **Continuidad de Propósito.** La razón por la que el usuario llegó a un módulo nuevo —qué
   decisión estaba tomando, qué pregunta estaba resolviendo— viaja con él; el módulo de destino
   no lo recibe como si fuera una visita genérica. Especializa Decision Experience (MPX Cap. 3) y
   el flujo de información entre módulos ya declarado en MPA §5.
3. **Continuidad Visual.** La transición entre módulos no debe sentirse como entrar a otra
   aplicación. Especializa "Consistencia sobre novedad" (MDL Cap. 1) y se apoya en el Shell de
   Navegación (Product Patterns Cap. 1) como el elemento que nunca se reinicia entre módulos.

## 2.3 Anatomía de una Transición entre Módulos

Toda transición documentada como recorrido canónico se describe en tres partes:

- **Origen.** Qué disparó la transición — nunca "el usuario hizo clic en el menú" como única
  causa válida de un recorrido canónico; el origen real suele ser una decisión, una alerta, o una
  sugerencia del Copiloto IA que apunta a otro módulo.
- **Destino.** Qué debe estar ya resuelto en la pantalla de llegada sin que el usuario tenga que
  reconstruirlo — si el recorrido se originó en un Lead específico, el módulo de destino no
  aterriza en su vista general, aterriza ya filtrado o enfocado en ese mismo Lead.
- **Retorno.** Cómo se preserva el camino de vuelta al punto de origen, para que cruzar de módulo
  nunca se sienta como perder el lugar donde se estaba.

## 2.4 Matriz de Recorridos Canónicos

Ejemplos de recorridos que cruzan más de un módulo de MPA y que cualquier User Flow futuro debe
tomar como referencia de continuidad, no como lista cerrada:

| Recorrido | Origen | Destino | Continuidad exigida |
|---|---|---|---|
| Notificaciones → CRM/Pipeline | Una alerta señala un Lead de alto valor sin respuesta. | El Lead exacto, no la bandeja general. | De contexto (el motivo de la alerta viaja con la transición) |
| Inicio → Agentes IA (Copiloto) → CRM/Pipeline | La Zona de acción de Inicio prioriza un Lead. | El Copiloto ofrece un resumen ya generado sobre ese Lead antes de que el asesor lo pida. | De propósito (la decisión que originó la visita a Inicio no se pierde al pasar por el Copiloto) |
| Conversaciones → Catálogo & Comercial | Un cliente pregunta por un producto dentro de una conversación activa. | El Catálogo se abre en el contexto de esa conversación, no como búsqueda desde cero. | De contexto y de retorno (la conversación sigue activa al volver) |
| CRM/Pipeline → Analítica | Un supervisor quiere entender el patrón detrás de varios Leads estancados. | Analítica ya filtrada por el segmento que originó la pregunta. | De propósito (la pregunta que motivó la visita queda expresada como filtro, no se reformula) |
| Equipo & Organización → CRM/Pipeline | Un supervisor reasigna un Lead de un asesor a otro. | El Lead reasignado, ya visible en el Pipeline del nuevo asesor, con el historial completo. | De contexto (la reasignación no reinicia el Lead como si fuera nuevo) |

## 2.5 Consecuencia para el diseño de flujos

Ningún User Flow que cruce de un módulo a otro se considera completo si no declara, explícitamente,
sus tres propiedades de continuidad (§2.2). Un User Flow que resuelve una transición mostrando al
usuario una pantalla de destino "genérica" — sin el contexto, sin el propósito o sin camino de
retorno — no es un error de implementación menor: es una ruptura del Principio Central en el nivel
de recorrido, y debe registrarse como excepción justificada (mismo criterio de Experience Debt de
MPX Cap. 11) antes de avanzar a Wireframes.

---

# Capítulo 3 — La Siguiente Mejor Decisión

## 3.1 Propósito del Capítulo

Convertir "guiar al usuario hacia la siguiente mejor decisión" (Capítulo 1, concepto 2) en un
criterio único y verificable, aplicable a cualquier pantalla futura de Maiek AI. Este capítulo
resuelve, de forma definitiva y con un ejemplo aplicado, la aparente tensión entre dos reglas ya
existentes en el corpus: **"Acción antes que observación"** (Product Patterns Cap. 8) y
**"La comprensión precede a la acción"** (Capítulo 1, concepto 3, especialización de
Explainability First — MPX Cap. 2).

**Qué no gobierna este capítulo:** no redefine el patrón "Acción antes que observación" ni
Explainability First — ambos siguen teniendo autoridad exclusivamente en sus documentos de
origen. Este capítulo solo declara la regla de coexistencia entre los dos.

## 3.2 Dos Ejes, No Una Contradicción

Las dos reglas no compiten porque no operan sobre el mismo eje:

- **Eje espacial — "Acción antes que observación".** Gobierna qué se dispone primero en el
  espacio de la pantalla: lo accionable aparece antes que lo puramente analítico o descriptivo,
  en cualquier breakpoint. Es una regla de **composición**.
- **Eje cognitivo — "La comprensión precede a la acción".** Gobierna qué debe ser cierto en el
  entendimiento del usuario antes de que se le pida decidir: el usuario debe poder justificar por
  qué se le muestra esa acción, en el mismo instante en que la ve. Es una regla de **secuencia
  mental**, no de orden de renderizado.

La comprensión no antecede a la acción en el tiempo de navegación (no exige una pantalla previa
de "contexto" antes de llegar a la pantalla con el botón) — antecede a la acción en el tiempo de
decisión (exige que, en el mismo golpe de vista donde aparece la acción, esté también disponible
la razón). Un elemento accionable puede — y debe, por "Acción antes que observación" — presentarse
primero en el espacio. Pero ningún elemento accionable se considera completo en su diseño si el
usuario no puede comprender, sin navegar a ninguna otra parte, por qué se le presenta esa acción.

## 3.3 Regla de Coexistencia: Co-localización

**Toda acción propuesta al usuario debe llevar su justificación en la misma unidad visual que la
contiene — nunca en una pantalla, panel o paso separado.** Esta es la regla que hace compatibles
los dos ejes: el orden espacial se resuelve a nivel de pantalla completa (la acción va primero
que el bloque analítico); la comprensión se resuelve a nivel de la unidad mínima que contiene la
acción (el motivo vive junto al botón, no en otro lugar del layout).

## 3.4 Ejemplo práctico paso a paso

Escenario: un asesor abre el módulo Inicio. El sistema identificó que un cliente lleva varios
días sin respuesta y muestra una intención de compra alta.

**Paso 1 — Disposición espacial (satisface "Acción antes que observación").**
Lo primero que el asesor ve al abrir la pantalla, antes que cualquier gráfico o indicador
general, es una tarjeta de decisión:

> **Llamar a [Cliente] → Llamar ahora**

Ningún KPI, gráfico o listado general aparece por encima de esta tarjeta. Hasta aquí, la regla
espacial queda satisfecha — pero, por sí sola, todavía no satisface la regla cognitiva.

**Paso 2 — Comprensión co-localizada (satisface "La comprensión precede a la acción").**
La misma tarjeta, en el mismo golpe de vista, sin que el asesor tenga que hacer clic, expandir ni
navegar a otra pantalla, muestra el motivo:

> Lleva 3 días sin respuesta. Intención de compra alta.

El motivo no vive en un panel aparte, ni en un tooltip que exige hover, ni en una segunda pantalla
de "detalle" — vive dentro de la misma tarjeta que contiene el botón. Esto es la co-localización
exigida por §3.3.

**Paso 3 — Secuencia real de decisión.**
El asesor percibe la tarjeta completa (acción + motivo) en un único acto de lectura. La
comprensión ("por qué llamar a este cliente ahora") ocurre en la mente del asesor *antes* del
clic, aunque el botón haya aparecido primero en el orden de renderizado de la pantalla. El orden
espacial (Paso 1) y el orden cognitivo (Paso 2-3) conviven porque operan en ejes distintos: uno es
sobre el layout, el otro es sobre qué información ya se posee al momento de decidir.

**Paso 4 — Contraejemplo: cómo se rompe la regla incluso cumpliendo "Acción antes que
observación".**
Si la misma tarjeta mostrara únicamente el botón "Llamar ahora", y el motivo ("3 días sin
respuesta, intención alta") solo estuviera disponible haciendo clic en un enlace "Ver detalle"
que abre otra pantalla, la regla espacial seguiría técnicamente cumplida (la acción sigue
apareciendo antes que cualquier bloque analítico) — pero la regla cognitiva quedaría rota: se le
pide al asesor actuar antes de poder comprender por qué, contradiciendo directamente
Explainability First (MPX Cap. 2) y el concepto de Comprensión Previa (Capítulo 1). Este
contraejemplo es la evidencia de que ambas reglas son necesarias y no intercambiables entre sí.

## 3.5 Consecuencia para el diseño de flujos

Cualquier User Flow o Wireframe futuro que presente una acción sin su justificación co-localizada
en la misma unidad visual —incluso si técnicamente respeta el orden espacial de "Acción antes que
observación"— se considera incompleto bajo este Blueprint. Debe registrarse como excepción
justificada, con razón de negocio explícita y alcance acotado (mismo criterio de Experience Debt
de MPX Cap. 11), antes de avanzar de Wireframe a Mockup.

**Relación con el Capítulo 5.** Este capítulo resuelve *cómo* se ordena una acción y su
justificación dentro de una pantalla de decisión única; el Capítulo 5 resuelve *cuánto* puede
pedir esa misma pantalla sin exceder el presupuesto de atención y contexto del usuario. Ambos
capítulos gobiernan la misma unidad de diseño — una pantalla con una decisión primaria— desde dos
ejes distintos y se aplican en conjunto, nunca por separado.

---

# Capítulo 4 — Arquitectura Cognitiva de la Experiencia

## 4.1 Propósito del Capítulo

Este capítulo fija el marco general que los Capítulos 5 a 8 especializan: un modelo operativo,
no psicológico ni académico, de los recursos finitos que un usuario trae a cualquier sesión de
trabajo con Maiek AI. Ninguna pantalla, patrón o recorrido puede diseñarse asumiendo que la
atención, la memoria de trabajo o el contexto del usuario son ilimitados — esa suposición,
implícita en cualquier pantalla que "agrega solo un dato más" sin costo, es precisamente lo que
Eficiencia Cognitiva (Capítulo 1, concepto 4) prohíbe en la práctica.

**Qué no gobierna este capítulo:** no es un tratado de psicología cognitiva ni de neurociencia —
no cita teoría académica externa ni la necesita. Es un modelo mínimo, deliberadamente simple,
suficiente para tomar y verificar decisiones de diseño de flujo. No redefine Memory Experience
(memoria persistente que el *sistema* mantiene sobre el usuario — MPX Cap. 8), que es un
mecanismo distinto: este capítulo gobierna lo que el *usuario* sostiene activamente en su propia
mente mientras opera, no lo que la plataforma recuerda por él.

## 4.2 El Modelo: Tres Recursos Finitos

Toda decisión de este capítulo y de los Capítulos 5 a 8 se apoya en la misma distinción entre
tres recursos que una pantalla o un flujo consume, y que nunca deben tratarse como
intercambiables entre sí:

| Recurso | Qué es | Qué NO es |
|---|---|---|
| **Atención** | Lo que el usuario puede procesar activamente en un instante dado. Se agota con cada elemento que compite por ella; no se expande agregando más pantalla. | No es memoria — un elemento puede estar "a la vista" sin estar realmente atendido. |
| **Memoria de trabajo** | El estado mental que el usuario debe sostener mientras completa una tarea (qué llevaba hecho, qué decisión estaba tomando, dónde estaba parado). | No es lo que el sistema recuerda del usuario — eso es Memory Experience (MPX Cap. 8), un mecanismo de la plataforma, no de la mente del usuario. |
| **Contexto** | Información ya conocida por el sistema que el usuario no debería tener que volver a explicar o buscar. | No es memoria de trabajo — el contexto es un dato ya dado; la memoria de trabajo es el esfuerzo activo de sostenerlo mientras se actúa. |

Esta distinción de tres recursos, y no uno solo genérico ("carga cognitiva" a secas), es lo que
permite que los capítulos siguientes den reglas verificables en vez de una directiva vaga: cada
uno gobierna un recurso o una combinación específica, nunca los tres a la vez de forma difusa.

## 4.3 La Regla del Presupuesto Cognitivo

Toda pantalla, paso de un flujo o composición completa tiene un **presupuesto finito** de los tres
recursos del §4.2. Ninguna decisión de diseño puede exceder ese presupuesto sin registrar
Experience Debt (MPX Cap. 11) de forma explícita, con razón de negocio y alcance acotado — nunca
de forma implícita "porque la pantalla ya estaba cargada de todos modos".

**Ejemplo de aplicación ya vigente en el corpus:** la Zona de acción del patrón Inicio
(`MAIEK_AI_PRODUCT_PATTERNS.md` Cap. 3) prioriza una única decisión primaria por vez — esa regla,
ya aprobada, es una instancia concreta del presupuesto de atención de este capítulo, no una
coincidencia de diseño. Este Blueprint no la redefine; la reconoce como evidencia de que el
principio ya se aplica correctamente donde existe.

**Señal de que un diseño excede el presupuesto:** cuando responder "¿qué se supone que haga
ahora en esta pantalla?" exige que el usuario sostenga mentalmente más de una decisión pendiente,
o reconstruya un dato que el sistema ya tenía, o reparta su atención entre dos elementos que
compiten por prioridad sin que ninguno la tenga declarada.

## 4.4 Cómo se distribuye este capítulo en los siguientes

Los tres recursos del §4.2 no se gestionan todos con la misma regla ni en el mismo momento de la
experiencia — cada capítulo siguiente toma una porción específica del modelo:

| Capítulo | Recurso(s) que gestiona | Momento de la experiencia |
|---|---|---|
| Cap. 5 — Gestión del Presupuesto de Atención y Contexto | Atención + Contexto | Dentro de una pantalla o paso individual |
| Cap. 6 — Continuidad de Tarea | Memoria de trabajo | Cuando una tarea se interrumpe y se retoma |
| Cap. 7 — Atención, Prioridad y Ritmo de Interacción | Atención | A lo largo del tiempo, dentro de una tarea activa (distinto de MPX Cap. 7, que gobierna notificaciones fuera de la tarea activa) |
| Cap. 8 — Consistencia de los Recorridos | Los tres, en conjunto | A través de repeticiones del mismo recorrido (Cap. 2) |

## 4.5 Consecuencia para el diseño de flujos

A partir de este capítulo, todo User Flow debe poder declarar, para cada pantalla o paso, qué
consume de cada uno de los tres recursos del §4.2 — no como documentación exhaustiva de cada
pantalla, sino como criterio de revisión: si nadie puede responder esa pregunta para un paso de un
flujo, es señal de que el paso no fue diseñado con presupuesto cognitivo consciente, y debe
revisarse antes de avanzar a Wireframes.

---

# Capítulo 5 — Gestión del Presupuesto de Atención y Contexto

## 5.1 Propósito del Capítulo

Especializa el presupuesto de Atención y Contexto (Capítulo 4, §4.2) al nivel de una sola
pantalla o un solo paso de un flujo — el nivel más pequeño en el que una decisión de diseño puede
excederlo.

**Relación con el Capítulo 3.** El Capítulo 3 resuelve cómo se ordena una acción y su
justificación dentro de esta misma pantalla; este capítulo resuelve cuánto puede pedir esa
pantalla en total. Ambos gobiernan la misma unidad de diseño desde dos ejes distintos y se
aplican en conjunto.

## 5.2 El Presupuesto de Atención por Pantalla

**Regla:** ninguna pantalla o paso presenta más de una decisión primaria a la vez. Indicadores,
alertas y datos secundarios pueden coexistir, pero solo si no compiten en jerarquía visual con la
decisión primaria — deben leerse claramente como apoyo, nunca como una segunda decisión igual de
prioritaria. Especializa Zona de acción (Product Patterns Cap. 3) y "Acción antes que
observación" (Product Patterns Cap. 8) al nivel de presupuesto cognitivo: esas reglas ya dictan
*qué* va primero en el espacio; esta regla dicta *cuánto* puede pedir la pantalla sin romper el
presupuesto de atención.

**Señal de exceso:** si dos elementos de una misma pantalla requieren, cada uno, una decisión
independiente del usuario, la pantalla no tiene una decisión primaria — tiene dos pantallas
comprimidas en una.

## 5.3 El Presupuesto de Contexto

**Regla:** ninguna pantalla pide al usuario un dato, una confirmación o una aclaración que el
sistema ya tiene disponible. Especializa Continuidad de Contexto (Capítulo 2, §2.2) al nivel de
una sola pantalla — Continuidad de Contexto gobierna que el dato viaje *entre módulos*; esta regla
gobierna que, una vez que el dato llegó, la pantalla efectivamente lo *use* en vez de volver a
pedirlo. No redefine Memory Experience (MPX Cap. 8), que es el mecanismo por el cual el sistema
retiene el dato — este capítulo asume que el dato ya está retenido y regula su uso en pantalla.

**Señal de exceso:** un campo de formulario vacío que pide un dato que ya existe en otro lugar del
sistema para ese mismo usuario o cliente.

## 5.4 Jerarquía de Reducción ante Conflicto

Cuando mostrar más información entra en conflicto con el presupuesto de atención, la reducción
sigue este orden, del primero que se sacrifica al último:

1. Datos analíticos o de contexto secundario no ligados a la decisión primaria.
2. Confirmaciones o pasos intermedios que no protegen una acción irreversible (ver Human Decision
   Gate, Product Patterns Cap. 8 — solo lo irreversible conserva su confirmación).
3. Variantes visuales decorativas sin función (ya cubiertas por "silencio antes que ruido", MDL
   Cap. 1).

**Regla de reducción: colapsar, no eliminar.** Todo lo que se sacrifica por presupuesto de
atención se **colapsa o se vuelve secundario — nunca se elimina ni se vuelve inaccesible**. El
usuario mantiene el foco en la decisión primaria sin perder la información que quedó fuera de la
vista inicial; reducir presupuesto de atención nunca es equivalente a reducir el dato disponible.

Lo que nunca se sacrifica: la justificación de la decisión primaria (Explainability First, MPX
Cap. 2) — reducir presupuesto de atención no autoriza a ocultar el porqué de una acción, esa
regla es superior y no se negocia contra esta.

## 5.5 Ejemplo aplicado

Una pantalla de detalle de Lead necesita mostrar: la acción sugerida (llamar ahora), su motivo,
el historial completo de la conversación, y datos de contacto. Bajo la regla de este capítulo: la
acción sugerida y su motivo ocupan la posición primaria (presupuesto de atención respetado, un
solo llamado a decidir); el historial se colapsa por defecto, expandible bajo demanda (reduce
presupuesto de atención sin eliminar el dato); los datos de contacto, ya conocidos por el sistema
para ese Lead, no se piden de nuevo en ningún campo de esa pantalla (presupuesto de contexto
respetado).

## 5.6 Qué no gobierna este capítulo

No redefine qué componente visual se usa para colapsar información (CDS), no redefine qué dato
específico persiste el sistema (Data Architecture), no redefine Explainability First (MPX Cap. 2)
— solo declara que ese principio no se sacrifica ante presión de presupuesto.

## 5.7 Consecuencia para el diseño de flujos

Todo Wireframe debe poder señalar, para cada pantalla, cuál es su única decisión primaria y qué
dato ya conocido no vuelve a pedirse. Una pantalla que no puede señalar una única decisión primaria
no está lista para Wireframe — debe volver a User Flows para resolverse.

---

# Capítulo 6 — Continuidad de Tarea: Interrupción y Recuperación de Estado

## 6.1 Propósito del Capítulo

Gobierna el recurso de Memoria de trabajo (Capítulo 4, §4.2): qué debe preservar el sistema
cuando una tarea en curso se interrumpe — deliberada o involuntariamente— y el usuario la retoma,
para que no tenga que reconstruir mentalmente lo que ya había avanzado.

**Distinto de Continuidad entre Módulos (Capítulo 2).** El Capítulo 2 gobierna cruzar de un
módulo a otro dentro de un mismo propósito continuo, sin pausa. Este capítulo gobierna pausar —
con o sin cruce de módulo— y retomar más tarde, con una ausencia real de por medio.

**Distinto de Memory Experience (MPX Cap. 8).** Memory Experience persiste hechos de largo plazo
sobre un usuario o un cliente (preferencias, historial), vigentes exista o no una tarea activa.
Este capítulo persiste el estado de una tarea puntual en curso — deja de ser relevante en cuanto
la tarea termina, mientras que Memory Experience no tiene ese límite.

## 6.2 Los Tres Momentos de una Interrupción

1. **Pausa** — el instante en que la tarea deja de tener la atención activa del usuario, sea
   porque decidió hacer otra cosa (deliberada) o porque algo externo lo desvió: una notificación,
   una pérdida de conexión, un error, un cierre accidental (involuntaria).
2. **Ausencia** — el tiempo en que la tarea queda sin actividad, de cualquier duración.
3. **Retorno** — el instante en que el usuario vuelve a la tarea, desde cualquier punto de
   entrada (el mismo dispositivo, otro dispositivo, otro canal).

## 6.3 Regla de Recuperación de Estado

**Al retorno, el sistema responde sin que el usuario tenga que preguntarlo:** ¿dónde estaba?,
¿qué ya había avanzado?, ¿qué falta? La tarea nunca se reinicia desde cero por defecto — solo si
el propio usuario lo pide de forma explícita. El costo de reconstruir mentalmente el avance
perdido es exactamente el tipo de carga que la Regla del Presupuesto Cognitivo (Capítulo 4, §4.3)
prohíbe imponer sin necesidad.

## 6.4 Matriz de aplicación por tipo de tarea

| Tipo de tarea | Qué preserva el retorno |
|---|---|
| Formulario largo (ej. alta de un registro con varios campos) | El borrador con los datos ya ingresados, no un formulario en blanco. |
| Conversación con el Copiloto IA | El contexto de la conversación en curso, no una sesión nueva sin memoria de lo ya preguntado. |
| Flujo de varios pasos (asistente/wizard) | El paso exacto donde se quedó, marcado visualmente, no el primer paso. |
| Revisión de un listado con filtros aplicados | Los filtros y el orden ya elegidos, no el listado por defecto. |

## 6.5 Ejemplo aplicado

Un asesor está completando el registro de un nuevo Lead — lleva tres de cinco campos— y una
notificación lo desvía a otro módulo. Bajo la regla de este capítulo: al volver, ya sea
navegando de vuelta o desde el mismo punto de entrada, el formulario muestra los tres campos ya
completados y el foco en el cuarto, no un formulario vacío. Si la interrupción implicó pérdida de
conexión, la regla no cambia — el sistema no traslada al usuario el costo de un fallo técnico
propio.

## 6.6 Qué no gobierna este capítulo

No define el mecanismo técnico de persistencia (guardado automático, borrador en servidor,
almacenamiento local) — eso es decisión de Backend/Frontend Architecture. No redefine Memory
Experience (MPX Cap. 8) ni la resolución de ediciones concurrentes entre dos personas (MPX Cap.
9) — ese es un conflicto entre usuarios distintos, no la interrupción de un mismo usuario consigo
mismo.

## 6.7 Consecuencia para el diseño de flujos

Todo User Flow de una tarea de más de un paso debe declarar explícitamente qué estado se preserva
si la tarea se interrumpe antes de completarse. Un flujo que no lo declara se asume, por defecto,
como si debiera preservar todo el avance — la ausencia de la declaración nunca se interpreta como
autorización a reiniciar desde cero.

---

# Capítulo 7 — Atención, Prioridad y Ritmo de Interacción

## 7.1 Propósito del Capítulo

Gobierna el recurso de Atención (Capítulo 4, §4.2) a lo largo del tiempo, dentro de una tarea ya
activa: qué ocurre cuando más de un estímulo compite por la atención del usuario mientras está
concentrado haciendo algo, y con qué cadencia el sistema debe responder a sus acciones.

**Distinto de Notificaciones (MPX Cap. 7).** MPX Cap. 7 gobierna qué canal usa un aviso y cómo se
degrada por fatiga cuando el usuario está *fuera* de una tarea activa o cuando el aviso llega de
forma asíncrona. Este capítulo gobierna qué compite por la atención *mientras* el usuario ya está
inmerso en una tarea — un problema de coexistencia dentro de la misma pantalla, no de selección de
canal.

## 7.2 Regla de Prioridad Única Activa

En cualquier instante, un solo elemento puede sostener la prioridad de atención activa dentro de
una tarea en curso. Cualquier otro estímulo que aparezca mientras tanto —una alerta, una
sugerencia del Copiloto, un dato actualizado— se degrada automáticamente a un estado de espera
visible pero no intrusivo (mismo criterio de Degradación visible con alternativa, MPX Cap. 9) hasta
que el usuario libera la prioridad activa (completa el paso, o la abandona deliberadamente).

**Excepción:** solo un Bloqueo explícito (MPX Cap. 9, nivel 3 — riesgo real de datos o dinero)
puede interrumpir la prioridad activa sin esperar. Ninguna sugerencia, por relevante que sea,
alcanza ese umbral por definición (Human Decision Gate, Product Patterns Cap. 8, ya distingue
irreversible de no irreversible con el mismo criterio de excepcionalidad).

## 7.3 Ritmo de Interacción

**Regla:** la cadencia entre una acción del usuario y la respuesta visible del sistema debe ser
predecible y proporcional al esfuerzo percibido de la acción — ni instantánea al punto de ocultar
que algo ocurrió, ni tan lenta que obligue a preguntarse si el sistema respondió. Especializa el
umbral de Loading (MPX Cap. 1) y el modelo de respuesta optimista, llevados al nivel de secuencia
completa de una tarea, no de una sola interacción aislada: una tarea de varios pasos con ritmo
irregular (un paso instantáneo, el siguiente con demora sin explicación) rompe Predictable
Interaction (MPX, preámbulo Parte II) tanto como un componente individual que se comporta distinto
de una pantalla a otra.

**Regla de prioridad: velocidad subordinada a claridad y control.** Ante un conflicto entre
responder más rápido y preservar la predictibilidad del ritmo o el control del usuario sobre la
tarea en curso, se sacrifica primero la velocidad — nunca al revés. Una respuesta más rápida que
deja al usuario sin saber qué pasó, o que le quita la posibilidad de seguir el avance de su propia
tarea, no es una mejora de experiencia aunque reduzca el tiempo total.

## 7.4 Ejemplo aplicado

Un asesor está completando el registro de un Lead cuando el Copiloto IA detecta que ese mismo
cliente ya escribió antes por otro canal. Bajo la regla de prioridad única: la sugerencia del
Copiloto no interrumpe el formulario en curso — aparece en un estado de espera visible (por
ejemplo, un indicador junto al Copiloto) hasta que el asesor termina o abandona el registro. Solo
si esa coincidencia implicara un riesgo real (ej. estar por duplicar un Lead ya existente con datos
de pago asociados) alcanzaría el umbral de Bloqueo explícito y podría interrumpir de inmediato.

## 7.5 Qué no gobierna este capítulo

No redefine timing de motion ni curvas de animación (MDL Cap. 7) — este capítulo gobierna la
cadencia percibida de la experiencia completa, no la duración en milisegundos de una transición
visual. No redefine los tres niveles de degradación de fallas (MPX Cap. 9) — los reutiliza como
mecanismo ya existente para resolver la excepción del §7.2.

## 7.6 Consecuencia para el diseño de flujos

Todo User Flow debe declarar, para cada punto donde pueda aparecer un estímulo secundario durante
una tarea activa, si ese estímulo espera o interrumpe — y si interrumpe, debe justificar por qué
alcanza el umbral de Bloqueo explícito. Un flujo que no lo declara se asume, por defecto, en modo
espera — igual que en el Capítulo 6, el silencio nunca se interpreta como autorización a
interrumpir.

---

# Capítulo 8 — Consistencia de los Recorridos

## 8.1 Propósito del Capítulo

Cierra el bloque de Arquitectura Cognitiva (Capítulos 4 a 8) con un criterio de calidad
transversal: que un recorrido ya definido en el Capítulo 2 se comporte de forma idéntica cada vez
que un User Flow lo instancia, sin importar desde qué módulo se origine ni quién lo implemente.

**Distinto de "Cómo se usa este capítulo" (Product Patterns Cap. 8).** Ese capítulo verifica que
un *patrón nuevo* no contradiga los seis principios transversales de producto al momento de
escribirse. Este capítulo verifica que un *recorrido ya definido* (Capítulo 2 de este documento)
se ejecute de manera idéntica cada vez que se repite en la práctica — el objeto verificado es
distinto: una definición de patrón en un caso, una instancia repetida de un recorrido en el otro.

## 8.2 Regla de Consistencia

Dos instancias del mismo recorrido canónico (Capítulo 2, §2.4) deben preservar exactamente las
mismas tres propiedades de continuidad (§2.2: contexto, propósito, visual) y el mismo presupuesto
cognitivo (Capítulos 4 a 7), sin importar el punto de origen específico. Un recorrido
"Notificaciones → CRM/Pipeline" debe comportarse igual sin importar qué tipo de alerta lo
originó — variar el contenido de la alerta es válido; variar si el destino preserva contexto o no
según el tipo de alerta, no lo es.

## 8.3 Checklist de Verificación

Antes de aprobar un User Flow que instancia un recorrido ya definido en el Capítulo 2:

1. ¿Preserva las mismas tres propiedades de continuidad que la entrada correspondiente de la
   Matriz de Recorridos Canónicos (§2.4)?
2. ¿Respeta el mismo presupuesto de atención y contexto (Capítulo 5) que otras instancias del
   mismo recorrido ya aprobadas?
3. ¿La recuperación de estado (Capítulo 6), si el recorrido incluye una tarea de varios pasos, es
   la misma que en otras instancias?
4. Si el recorrido puede repetirse desde distintos orígenes (§2.4), ¿el comportamiento en el
   destino es indistinguible entre esos orígenes, salvo por el contenido específico que lo
   originó?

Cualquier "No" sin una excepción registrada (mismo criterio de Experience Debt, MPX Cap. 11)
bloquea la aprobación del User Flow.

## 8.4 Qué no gobierna este capítulo

No define nuevos recorridos — solo verifica consistencia entre instancias de los ya definidos en
el Capítulo 2. Si un caso nuevo no encaja en ningún recorrido ya definido, la respuesta no es
forzarlo aquí — es volver al Capítulo 2 y evaluar si corresponde una nueva entrada en la Matriz de
Recorridos Canónicos.

## 8.5 Consecuencia para el diseño de flujos

Este checklist se aplica como gate final antes de que un User Flow que instancia un recorrido
existente avance a Wireframe — mismo punto de control que ya usan los Capítulos 2, 3, 5, 6 y 7 en
su respectiva "Consecuencia para el diseño de flujos", ahora consolidado en un solo lugar para los
recorridos que se repiten.

---

# Capítulo 9 — El Rol de la IA en la Experiencia

## 9.1 Propósito del Capítulo

Declara, sin redefinir, que "la IA acompaña, nunca reemplaza el criterio humano" — el principio
más antiguo del corpus, ya establecido en `MAIEK_AI_FRAMEWORK.md` y especializado en Product
Patterns Cap. 8 (Explainability First + Human Decision Gate) y en MPX (Cap. 2-3) — y fija su
consecuencia específica para el diseño de recorridos y presupuesto cognitivo definidos en los
Capítulos 2 a 8.

## 9.2 La IA como Reductor de Carga, Nunca como Fuente Adicional

**Regla:** toda intervención de la IA dentro de un recorrido o una pantalla debe reducir el
presupuesto cognitivo que esa pantalla exige (Capítulo 4, §4.3) — nunca aumentarlo. Una sugerencia
que obliga al usuario a evaluar una opción adicional sin eliminar una decisión o una búsqueda que
antes le correspondía a él mismo no cumple su función: se volvió un elemento más que compite por
atención, no una ayuda.

**Consecuencia directa sobre el §7.2 (Prioridad Única Activa):** una sugerencia de IA que aparece
durante una tarea activa se degrada a estado de espera igual que cualquier otro estímulo
secundario — la IA no tiene, por ser IA, un privilegio de interrupción que otro estímulo no
tendría. El corolario ya fijado en Product Patterns Cap. 8 ("el Copiloto no compite por el control
de la interfaz") se aplica acá de forma literal.

## 9.3 Ningún Flujo Asume Disponibilidad Garantizada de la IA

Todo recorrido o pantalla diseñado bajo este Blueprint debe seguir siendo completable si la IA no
está disponible — degradación a Nivel 2 (Degradación visible con alternativa, MPX Cap. 9), nunca
Nivel 3. Ningún Capítulo de este documento (2 a 8) puede aplicarse asumiendo que un paso de
recuperación de estado, de gestión de contexto o de prioridad depende exclusivamente de una
capacidad de IA sin ruta manual equivalente.

## 9.4 Ejemplo aplicado

En el recorrido "Inicio → Copiloto IA → CRM/Pipeline" (§2.4), el resumen que el Copiloto entrega
reduce el presupuesto de contexto (§5.3): el asesor no reconstruye el historial de la conversación
leyéndolo completo. Si el servicio de IA no está disponible, el mismo recorrido sigue siendo
completable — el asesor entra al Lead y accede al historial completo manualmente, con más costo
cognitivo pero sin bloqueo (Nivel 2 de degradación, nunca Nivel 3).

## 9.5 Qué no gobierna este capítulo

No redefine ninguna regla de comportamiento de IA — todas viven en Framework, Product Patterns
Cap. 8 y MPX Cap. 2-3. Este capítulo solo declara la consecuencia de esas reglas ya existentes
sobre el modelo de recursos cognitivos de este documento (Capítulos 4 a 8).

## 9.6 Consecuencia para el diseño de flujos

Todo User Flow que incorpore una intervención de IA debe declarar qué presupuesto cognitivo
reduce (Capítulo 4, §4.3) y cuál es su ruta manual equivalente si la IA no está disponible. Un
flujo que depende de la IA sin ruta manual declarada no está completo — debe resolverse antes de
avanzar a Wireframe, con el mismo criterio de gate que ya aplican los Capítulos 2 a 8.

---

# Capítulo 10 — Casos sin Patrón Todavía

## 10.1 Propósito del Capítulo

`MAIEK_AI_FUNCTIONAL_AUDIT_2026-07-31.md` identificó tres áreas del producto sin ningún patrón
propio en `MAIEK_AI_PRODUCT_PATTERNS.md`: Notificaciones, Canales & Configuración y Autenticación.
Este capítulo no construye esos patrones — eso sigue siendo tarea futura de Product Patterns— pero
fija qué principios de este Blueprint deben respetarse igual cuando esos patrones se escriban,
para que la identidad de experiencia no dependa de que exista o no un patrón formal todavía.

**Nota de alcance de la fuente citada:** la Auditoría Funcional es un documento histórico, sin
autoridad normativa (ver su propia sección "Naturaleza del documento"). Se usa acá únicamente
como insumo diagnóstico para identificar dónde aplicar este capítulo, no como fuente de reglas.

## 10.2 Regla General para Áreas sin Patrón

Cualquier pantalla o flujo de un área sin patrón propio debe, como mínimo, poder responder las
mismas preguntas de verificación que ya aplican a las áreas con patrón: cuál es su única decisión
primaria (§5.2), qué contexto no debe volver a pedir (§5.3), qué preserva si se interrumpe (Cap.
6), y si compite o no por prioridad de atención (Cap. 7). La ausencia de un patrón formal no exime
del presupuesto cognitivo — solo significa que la composición concreta todavía no está congelada
como referencia canónica.

## 10.3 Consideraciones específicas por área identificada

- **Notificaciones.** Al escribirse su patrón, deberá conciliar explícitamente MPX Cap. 7 (canal y
  fatiga) con la Regla de Prioridad Única Activa (§7.2) de este documento — hoy ninguno de los dos
  documentos declara esa relación de forma explícita porque el patrón no existe todavía.
- **Canales & Configuración.** Al ser un módulo de administración de baja frecuencia de uso, el
  presupuesto de atención (§5.2) tiende a ser menos crítico que en módulos operativos diarios —
  pero el presupuesto de contexto (§5.3) es especialmente relevante: configuraciones ya definidas
  en un canal no deben volver a pedirse al configurar otro similar.
- **Autenticación.** Es, por definición, el primer recorrido de cualquier sesión — la Continuidad
  de Tarea (Cap. 6) aplica con particular fuerza: una interrupción durante el inicio de sesión
  (ej. verificación en dos pasos) nunca debe forzar a reingresar credenciales ya validadas.

## 10.4 Qué no gobierna este capítulo

No define composición, componentes ni estados de estas tres áreas — eso corresponde
exclusivamente a una futura extensión de `MAIEK_AI_PRODUCT_PATTERNS.md`. Este capítulo se vuelve
obsoleto para un área específica en cuanto esa área obtiene su propio patrón formal — en ese
momento, la relación se documenta en el patrón nuevo (que deberá citar este capítulo, no al
revés).

## 10.5 Consecuencia para el diseño de flujos

Todo User Flow de Notificaciones, Canales & Configuración o Autenticación debe pasar por la Regla
General de §10.2 como gate mínimo, con el mismo criterio de bloqueo que ya aplican los Capítulos
2 a 9 — la ausencia de un patrón formal en Product Patterns no exime de este gate, solo cambia
contra qué composición concreta se verifica.

---

# Capítulo 11 — Prueba de Identidad: Checklist de Experiencia

## 11.1 Propósito del Capítulo

Da un checklist breve, aplicable por cualquier autor de User Flow, Wireframe o Mockup, derivado
directamente de los Capítulos 1 a 10 de este documento — equivalente funcional al Experience
Review Checklist de MPX Cap. 11, pero enfocado en arquitectura de la experiencia (recorrido y
recursos cognitivos), no en reglas de comportamiento, voz o interacción con IA, que siguen siendo
terreno exclusivo de MPX.

## 11.2 Checklist

Cada pregunta se responde Sí/No; cualquier "No" sin una excepción registrada (Experience Debt,
MPX Cap. 11) bloquea el avance a la siguiente etapa (Wireframe o Mockup):

1. **¿El recorrido declara sus tres propiedades de continuidad?** (Capítulo 2, §2.2)
2. **¿Cada pantalla tiene una única decisión primaria identificable?** (Capítulo 5, §5.2)
3. **¿Ningún campo pide un dato que el sistema ya tiene?** (Capítulo 5, §5.3)
4. **¿Está declarado qué se preserva si la tarea se interrumpe?** (Capítulo 6, §6.3)
5. **¿Está declarado si cada estímulo secundario espera o interrumpe, y por qué?** (Capítulo 7,
   §7.2)
6. **¿El ritmo de respuesta es predecible a lo largo de toda la tarea, no solo en un paso
   aislado?** (Capítulo 7, §7.3)
7. **¿Una instancia repetida de este recorrido se comporta igual que otras ya aprobadas?**
   (Capítulo 8, §8.3)
8. **¿Toda intervención de IA en este flujo reduce presupuesto cognitivo en vez de agregarlo, y el
   flujo sigue siendo completable sin ella?** (Capítulo 9, §9.2-9.3)
9. **¿Toda acción propuesta lleva su justificación co-localizada en la misma unidad visual, sin
   necesidad de navegar a otra pantalla o panel?** (Capítulo 3, §3.3)
10. **¿El recorrido transmite sensación de control, foco y continuidad — con el contexto ya
    conocido sin repetirse (Capítulo 5, §5.3), el avance de la tarea preservado ante una
    interrupción (Capítulo 6, §6.3) y la IA reduciendo carga en vez de agregarla (Capítulo 9,
    §9.2)?** (Concepto 5, Capítulo 1)

## 11.2bis Relación con las secciones "Consecuencia para el diseño de flujos"

Cada capítulo (2 a 10) cierra con su propia sección "Consecuencia para el diseño de flujos" — esa
sección es la regla de diseño a aplicar mientras se construye un User Flow, capítulo por capítulo.
Este Checklist es el **gate único y consolidado** que se aplica una sola vez, al momento de pasar
de User Flow a Wireframe — no es una verificación adicional y separada de cada una de esas
secciones, es su síntesis operativa. Pasar este Checklist equivale a haber satisfecho las
secciones "Consecuencia para el diseño de flujos" de todos los capítulos que le dieron origen a
sus preguntas.

## 11.3 Relación con el Experience Review Checklist de MPX

Este checklist es hermano funcional del Experience Review Checklist (MPX Cap. 11), no un
reemplazo ni una versión resumida de él. Un User Flow debe pasar ambos, en cualquier orden: el de
MPX verifica reglas de comportamiento, voz e interacción con IA a nivel de una interacción o
pantalla; el de este capítulo verifica arquitectura de recorrido y recursos cognitivos a nivel de
tarea completa. Pasar uno no exime de pasar el otro.

## 11.4 Qué no gobierna este capítulo

No gobierna cambios de contenido de este documento — eso es el Capítulo 12. No repite ninguna
pregunta ya cubierta por el Experience Review Checklist de MPX.

---

# Capítulo 12 — Gobernanza y Evolución del UX Blueprint

## 12.1 Propósito del Capítulo

Fija cómo cambia este documento en el futuro — instancia específica, para el UX Blueprint, del
mismo proceso general que ya rige la evolución de MPX (Cap. 11) y de `DOCUMENTATION_INDEX.md`
(§8). No repite ese proceso general, lo aplica al contenido de este documento en particular.

## 12.2 Proceso de Evolución

Un cambio de fondo en cualquier capítulo de este documento sigue esta secuencia, nunca una
edición directa sobre un capítulo ya revisado:

1. Evidencia — un caso real de un User Flow, Wireframe o recorrido que no puede resolverse dentro
   de las reglas ya definidas, o una Experience Debt recurrente que revela un patrón (mismo
   criterio Evidence over Opinion, MPX Cap. 10-11).
2. Propuesta de cambio explícita, con qué capítulo y qué regla exacta cambia y por qué.
3. Revisión — nunca aprobado de forma unilateral, mismo criterio de gobernanza documental del
   resto del corpus.
4. Nueva fila en el Control de versiones de este documento, nunca edición silenciosa.

## 12.2bis Qué no gobierna este capítulo

No gobierna la evolución del resto del corpus — eso ya lo cubre MPX Cap. 11 (para contenido de
experiencia) y `DOCUMENTATION_INDEX.md` §8 (para gobernanza documental general). Este capítulo es
la instancia específica de esos dos procesos aplicada únicamente al contenido de este documento;
no crea un tercer proceso paralelo ni tiene autoridad sobre ningún otro documento del corpus.

## 12.3 Jerarquía Documental (confirmación)

Este documento es una especificación derivada, al mismo nivel que `MAIEK_AI_PRODUCT_PATTERNS.md`
(hermano, no superior ni subordinado), dentro de la cadena ya *Approved* en
`MAIEK_AI_PRODUCT_EXPERIENCE.md`: `Framework → MPA → MDL → CDS → MPX → Especificaciones
derivadas`. Ninguna regla de este documento puede contradecir a Framework, MPA, MDL, CDS, MPX o
Product Patterns — ante una contradicción aparente, prevalece siempre el documento de mayor
jerarquía, y este documento se corrige.

## 12.4 Estado del Documento

| | |
|---|---|
| Estado | **Draft — congelamiento funcional.** Capítulos 0 a 12 redactados y corregidos tras la Auditoría Integral (5 entregables: Arquitectura del Documento, Coherencia con el Corpus, Cobertura Funcional, Identidad y Filosofía, Calidad como Documento Rector). No se declara *Approved* todavía: falta toda la fase de diseño visual (User Flows, Wireframes, Mockups y su validación), y ese trabajo puede requerir evidencia que ajuste este documento antes del cierre definitivo. |
| Versión | Draft v1.0 |
| Conclusión de la Auditoría Integral | No se encontraron contradicciones arquitectónicas relevantes entre este documento y el resto del corpus (Framework, MPA, MDL, CDS, MPX, Product Patterns, arquitecturas técnicas). Todos los hallazgos correspondieron a mejoras de consistencia, trazabilidad, verificabilidad o claridad editorial — ninguno requirió un cambio de dirección conceptual ni replantear la arquitectura de experiencia definida en los Capítulos 1 a 12. |
| Congelado | No — congelamiento funcional, no *Approved*. Puede seguir alimentando User Flows y Wireframes en este estado; el cierre definitivo queda condicionado a la validación visual todavía pendiente. |
| Próximo paso | Construcción de User Flows y Wireframes tomando este documento como referencia obligatoria, junto con `MAIEK_AI_PRODUCT_PATTERNS.md`. Cualquier ajuste que la validación visual revele se incorpora por el proceso de Evolución (§12.2), nunca por edición silenciosa. |

---

*Fin de `MAIEK_AI_UX_BLUEPRINT.md` — Capítulos 0 a 12 completos, Draft v1.0 en congelamiento
funcional. Auditoría Integral cerrada sin contradicciones arquitectónicas relevantes con el
resto del corpus. Próximo paso: User Flows y Wireframes tomando este documento y
`MAIEK_AI_PRODUCT_PATTERNS.md` como referencia obligatoria; el cierre definitivo a *Approved*
queda condicionado a la validación visual todavía pendiente.*
