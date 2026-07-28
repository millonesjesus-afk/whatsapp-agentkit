# Maiek AI — Product Experience (MPX)

**Versión 1.0 · Estado: Approved — completo (Partes I, II y III)**

| | |
|---|---|
| Documento | Maiek Product Experience (MPX) |
| Proyecto | Maiek AI |
| Versión | 1.0 |
| Estado | **Approved** — Parte I, Parte II y Parte III completas |
| Fecha de creación | 2026-07-26 |
| Autor | Claude, a pedido de Jesús Millones |
| Fecha de aprobación (v1.0 completo) | 2026-07-28 |
| Última actualización | 2026-07-28 |

## Dependencias

- `MAIEK_AI_FRAMEWORK.md` — identidad, principios y comunicación de marca.
- `MAIEK_AI_DESIGN_SYSTEM.md` (MDL) — filosofía y personalidad ya aprobadas (Capítulos 0 y 2);
  el MPX las opera, no las repite.
- `MAIEK_AI_COMPONENT_SYSTEM.md` (CDS) — componentes cuyo comportamiento este documento
  gobierna (AI Suggestion Card, Confirm Dialog, Toast, Empty State, entre otros).
- `MAIEK_AI_PRODUCT_ARCHITECTURE.md` (MPA) — módulos y capacidades exclusivas de IA (sección 7)
  que el Capítulo 2 y 3 de este documento convierten en protocolo operable.

## Consumido por

- Especificaciones de patrones de producto futuras (chat, dashboard, copiloto de IA) — todavía
  no construidas.
- *Frontend Architecture* / *Backend Architecture* (futuros) — el comportamiento de IA y de
  interacción definido acá condiciona decisiones técnicas de esos documentos.

## Control de versiones

| Versión | Fecha | Autor | Descripción |
|---|---|---|---|
| 1.0 (Parte I, borrador) | 2026-07-26 | Claude | Parte I — Fundamentos de la Experiencia: Capítulos 0 (Marco de experiencia), 1 (Interaction Model), 2 (Protocolo de interacción con IA) y 3 (Decision Experience). Partes II (Experiencia del Usuario) y III (Calidad y Evolución) pendientes de desarrollo y aprobación por separado. |
| 1.0 (Parte I, Approved) | 2026-07-26 | Claude | Revisión de arquitectura de contenido de la Parte I: se agregan 3 principios nuevos (Explainability First, Memory Experience, Progressive Intelligence) declarados en el Capítulo 0 y operados en los Capítulos 2-3; "Confianza media" renombrada a "Requiere validación" (Capítulo 2); se retira el valor fijo de 400ms del Capítulo 1, reemplazado por referencia al umbral del Design System. Parte I congelada como **Approved**. |
| 1.0 (Parte II, borrador) | 2026-07-28 | Claude | Parte II — Experiencia del Usuario: Capítulos 4 (Voz y contenido), 5 (Feedback y estados del sistema), 6 (Onboarding y primeras impresiones) y 7 (Notificaciones e interrupciones). Estructura revisada y aprobada por partes antes de redactar el contenido (índice, luego 6 principios adicionales integrados: Emotional Feedback, Empty State Intelligence, Building Trust, Delight, Cross-channel Experience, Every Screen Teaches). Regla editorial nueva aplicada en toda la Parte: todo principio importante incluye ejemplo concreto y, cuando aporta valor, contraejemplo de qué no hacer. Pendiente de revisión y aprobación. |
| 1.0 (Parte II, Approved) | 2026-07-28 | Claude | Revisión final de la Parte II: se agrega un séptimo principio adicional, **Predictable Interaction** (la interacción debe ser anticipable; la sorpresa positiva pertenece al valor entregado, nunca al comportamiento de la interfaz), operado en el límite de Delight (Capítulo 5) y en "Consistencia antes que variedad" de Building Trust (Capítulo 6); se agrega en el Capítulo 6 la definición explícita "el onboarding termina cuando el usuario alcanza autonomía, no cuando termina el tutorial". Parte II congelada como **Approved**. |
| 1.0 (Parte III, borrador) | 2026-07-28 | Claude | Parte III — Calidad y Evolución: Capítulos 8 (Personalización y continuidad), 9 (Manejo de errores y casos límite), 10 (Medición de experiencia) y 11 (Product Experience Governance). Arquitectura revisada y aprobada por partes antes de redactar contenido (índice detallado por 7 dimensiones, luego 3 ajustes incorporados: principio **Evidence over Opinion** complementario a Stable by Default; **Experience Review Checklist** operativo en el Capítulo 11; distinción explícita de tres tipos de memoria — persistente, conversacional, contexto temporal — en el Capítulo 8). QA arquitectónico aplicado: sin contradicciones ni duplicación de reglas de Parte I/II detectadas. Pendiente de revisión y aprobación final del usuario. |
| 1.0 (completo, Approved) | 2026-07-28 | Claude | Cierre del MPX v1.0: se agregan las secciones finales **Jerarquía documental** (orden de precedencia Framework → MPA → MDL → CDS → MPX → especificaciones derivadas, con regla de resolución de conflictos) y **Estado del documento** (Approved, versión 1.0, congelado, regla de próxima revisión atada exclusivamente al proceso de los Capítulos 10-11). Con esto, las Partes I, II y III quedan Approved — el MPX v1.0 se congela como documento completo. |

Este documento se construye y aprueba **por partes**, a pedido explícito del usuario — cada
parte se revisa antes de continuar con la siguiente. La tabla de arriba se actualiza al cerrar
cada parte, no solo al final del documento completo.

---

# Índice del documento completo

*(referencia — las tres Partes están desarrolladas en este archivo; ver estructura aprobada)*

**Parte I — Fundamentos de la Experiencia** · "¿Cómo piensa y toma decisiones Maiek AI?"
- Capítulo 0 — Marco de experiencia
- Capítulo 1 — Interaction Model
- Capítulo 2 — Protocolo de interacción con IA
- Capítulo 3 — Decision Experience

**Parte II — Experiencia del Usuario** *(Approved)* · "¿Cómo vive el usuario la filosofía definida en la Parte I?"
- Capítulo 4 — Voz y contenido
- Capítulo 5 — Feedback y estados del sistema
- Capítulo 6 — Onboarding y primeras impresiones
- Capítulo 7 — Notificaciones e interrupciones

**Parte III — Calidad y Evolución** *(Approved)* · "¿Cómo garantizamos que la experiencia se mantenga consistente y evolucione con el tiempo?"
- Capítulo 8 — Personalización y continuidad
- Capítulo 9 — Manejo de errores y casos límite
- Capítulo 10 — Medición de experiencia
- Capítulo 11 — Product Experience Governance

---

# PARTE I — Fundamentos de la Experiencia

*Esta parte responde una sola pregunta: ¿cómo piensa y toma decisiones Maiek AI? Todo lo que
seguirá en las Partes II y III son consecuencias aplicadas de lo que se define acá — ninguna
regla de las partes siguientes puede contradecir un principio establecido en esta.*

# Capítulo 0 — Marco de experiencia

## Qué gobierna el MPX y qué no

El MDL ya estableció, en su Capítulo 0, la filosofía y los 10 principios de experiencia de
Maiek AI — propósito, visión, emociones a transmitir, y la narrativa de "un día completo con
Maiek". Ese trabajo no se repite acá. El MPX parte de esos principios como axiomas ya
aprobados y responde la pregunta que el MDL deliberadamente no respondía: **¿qué hace
exactamente el sistema, momento a momento, para que esos principios se cumplan?**

La diferencia es de nivel, no de contenido. Donde el MDL dice *"la IA nunca interrumpe,
aparece solo cuando agrega valor"* (principio), el MPX dice *"una sugerencia con menos de
X% de confianza no se muestra; una sugerencia ignorada dos veces seguidas deja de aparecer
para ese contexto durante N días"* (regla operable). Un principio orienta; una regla se puede
seguir o violar de forma verificable.

## Relación con MDL, CDS y MPA

- El **MDL** define cómo se ve y qué principios rigen la marca — el MPX nunca contradice su
  Capítulo 0 ni redefine su personalidad (Capítulo 2).
- El **CDS** define de qué piezas visuales dispone el sistema (Toast, Confirm Dialog, AI
  Suggestion Card) — el MPX define **cuándo y por qué** se usa una en vez de otra.
- El **MPA** define los módulos y, en su sección 7, ya distinguió capacidades exclusivas de IA
  de las que requieren intervención humana — el MPX convierte esa distinción en protocolo
  operable (Capítulos 2 y 3).

## Principios adicionales de esta Parte

Tres principios nuevos, específicos del MPX, que complementan (sin reemplazar) los 10 ya
establecidos en el MDL — el mismo criterio de "principio orienta, regla operable se sigue o se
viola" aplica también a estos tres:

- **Explainability First.** Toda recomendación debe poder responder, de forma simple, tres
  preguntas: ¿por qué?, ¿por qué ahora?, ¿por qué yo? Si no puede responder las tres, no se
  muestra. Regla operable completa en el Capítulo 3, "Explicación de sugerencias".
- **Memory Experience.** El sistema recuerda el contexto que ya conoce y nunca vuelve a
  pedirlo — un usuario que ya contó algo no debería tener que repetirlo. El mecanismo completo
  (qué se recuerda, por cuánto tiempo, entre qué sesiones) se define en el Capítulo 8, Parte
  III; queda declarado acá como principio rector desde el inicio, para que ninguna regla de
  las Partes II y III lo contradiga por omisión.
- **Progressive Intelligence.** La IA revela sus capacidades de forma gradual, nunca todas a la
  vez desde el primer uso, para no sobrecargar con funcionalidad que el usuario todavía no
  necesita. Regla operable completa en el Capítulo 2, "Revelación progresiva de capacidades".

## Cómo leer este documento

Cada regla de este documento debe poder aplicarse a una pantalla concreta sin ambigüedad. Si
dos personas del equipo, leyendo la misma regla, tomarían decisiones distintas ante el mismo
caso, la regla está mal escrita — no es responsabilidad de quien la aplica, es responsabilidad
de este documento. Ese es el estándar de calidad que gobierna toda la Parte I.

---

# Capítulo 1 — Interaction Model

## Modelo de respuesta del sistema

Toda acción del usuario produce una de tres formas de respuesta, nunca una cuarta improvisada:

1. **Instantánea** (sin espera perceptible, `motion-instant` del MDL) — cambios de estado
   locales sin necesidad de confirmación del servidor (expandir una sección, marcar como leído).
2. **Optimista** (el sistema asume éxito y revierte solo si falla) — acciones de alta
   probabilidad de éxito y bajo costo de error (enviar un mensaje de chat, guardar un campo de
   texto). La interfaz se actualiza de inmediato; si el servidor rechaza la operación, el
   cambio se revierte con una señal clara de qué pasó, nunca en silencio.
3. **Confirmada** (el sistema espera respuesta del servidor antes de actualizar la interfaz) —
   acciones donde una reversión visible sería confusa o costosa (crear un registro que otros
   verán, ejecutar una cotización).

La elección entre las tres no es estética — depende exclusivamente de dos preguntas: ¿qué tan
probable es que falle? ¿qué tan costoso es mostrar algo que después hay que deshacer
visualmente? Alta probabilidad de éxito + bajo costo de revertir → optimista. Cualquier otra
combinación → confirmada.

## Reversibilidad como eje central

Toda acción del sistema se clasifica, antes de construirse, en una de dos categorías:

- **Reversible** — se ejecuta al instante, sin fricción de confirmación. Si el usuario se
  arrepiente, un Toast con acción "Deshacer" (CDS) es la única red de seguridad necesaria.
- **Irreversible** — exige Confirm Dialog (CDS) antes de ejecutarse, sin excepción, sin
  importar cuán frecuente sea la acción.

Ninguna acción vive en un punto intermedio. Si una acción parece "irreversible pero
frecuente" (ej. cerrar una conversación), la respuesta correcta no es relajar la regla — es
rediseñar la acción para que sea genuinamente reversible (ej. "cerrar" pasa a estado archivado,
no a eliminado).

## Optimismo del sistema, no del usuario

El optimismo de una respuesta optimista es del *sistema*, nunca se traslada como incertidumbre
al *usuario* — mientras una acción optimista está pendiente de confirmar en segundo plano, la
interfaz no muestra ningún indicador de duda (ni un ícono de "sincronizando", ni una opacidad
reducida) salvo que la espera supere el umbral de Loading ya definido en el Design System — el
valor exacto vive ahí, no acá, para que este documento no quede acoplado a un número técnico
que puede cambiar. Un sistema optimista que se ve dudoso deja de cumplir su propósito.

## Divulgación progresiva

Ninguna pantalla muestra toda la información disponible por defecto — se muestra lo necesario
para la decisión inmediata, con el detalle completo siempre a un clic, nunca a cero ni a más
de uno. Regla práctica: si un usuario nuevo entiende la pantalla sin necesitar el detalle
expandido, y un usuario experto puede llegar al detalle en un solo paso adicional, el nivel de
divulgación está bien calibrado.

## Modelo de deshacer

Deshacer (Toast con acción) reemplaza a confirmar (Confirm Dialog) exactamente cuando la
acción es reversible y de bajo costo de exposición — nunca ambos mecanismos a la vez sobre la
misma acción. Pedir confirmación Y ofrecer deshacer después es la señal más clara de que la
clasificación de reversibilidad de esa acción está mal hecha.

## Consistencia entre pantallas

La misma clase de acción produce la misma forma de respuesta en cualquier pantalla del
producto, sin excepción por contexto. Si "guardar" es optimista en un formulario, es optimista
en todos — un usuario no debería tener que reaprender el modelo de interacción pantalla por
pantalla.

---

# Capítulo 2 — Protocolo de interacción con IA

## Niveles de intervención

Toda capacidad de IA opera en uno de tres niveles, y el nivel se decide en el diseño, nunca se
improvisa en tiempo de ejecución:

1. **Silenciosa** — la IA trabaja en segundo plano sin manifestarse (ej. calcular un score que
   se muestra solo si el usuario abre ese lead). No hay interacción que gobernar; el resultado
   simplemente está listo cuando se necesita.
2. **Sugerente** — la IA se muestra de forma visible pero no bloqueante (AI Suggestion Card, AI
   Insight) — el usuario puede ignorarla por completo sin que eso afecte su flujo.
3. **Interruptiva** — no existe como nivel permitido. Ninguna capacidad de IA de Maiek
   interrumpe una tarea en curso del usuario con un modal, un sonido o un cambio de foco no
   solicitado. Es la traducción operativa directa del principio del MDL "la IA nunca
   interrumpe" — acá se convierte en una prohibición de diseño, no en una aspiración.

## Revelación progresiva de capacidades (Progressive Intelligence)

La IA nunca muestra todo lo que puede hacer desde el primer uso. Las capacidades se revelan en
función del contexto real del usuario, no de una lista completa de funciones disponibles: un
usuario nuevo ve solo lo que su situación actual amerita; capacidades más avanzadas (ej.
Copiloto completo, recomendaciones cruzadas de portafolio) aparecen cuando el contexto las
vuelve relevantes, no antes. Esto no es progresión artificial (nunca "desbloquear" funciones
por gamificación) — es evitar el costo cognitivo de mostrar herramientas que todavía no
resuelven nada para esa persona en ese momento (ver Capítulo 3, "Reducción de carga
cognitiva"). El detalle de cómo se comporta esto en un primer uso real se define en el
Capítulo 6, Parte III.

## Cuándo la IA habla sin que se le pida

Solo cuando se cumplen las tres condiciones a la vez: (1) el hallazgo es accionable, no solo
informativo; (2) el costo de no decirlo ahora es mayor que el costo de interrumpir el flujo
visual con una Card nueva; (3) existe una razón que se puede explicar en una línea (ver
Capítulo 3). Si falta cualquiera de las tres, la IA espera a ser consultada en vez de
iniciar.

## Cómo se retira una sugerencia ignorada

Una sugerencia (nivel sugerente) que el usuario no ejecuta ni descarta explícitamente después
de dos exposiciones deja de mostrarse para ese caso específico — la IA no insiste. Reaparece
solo si el contexto cambió de forma sustancial (nueva información en la conversación), nunca
por el simple paso del tiempo.

## Protocolo de incertidumbre

Tres franjas de confianza, cada una con un comportamiento distinto — nunca una sola frontera
binaria de "se muestra / no se muestra":

- **Alta confianza** — se muestra con normalidad, sin calificativos ("Llama primero a
  VAINSA").
- **Requiere validación** (antes "confianza media") — se muestra, pero enmarcada
  explícitamente como posibilidad, no como hecho ("Podría interesarle este producto, según
  conversaciones similares") — la etiqueta nombra la acción que le toca al humano, no solo
  describe un nivel numérico.
- **Baja confianza** — no se muestra. El umbral exacto es una decisión de producto por
  capacidad específica (documentada donde se implemente), no un número fijo en este
  documento — lo que sí es fijo es la regla: por debajo del umbral, silencio es siempre mejor
  que una sugerencia débil (ver MDL, "una sugerencia de baja confianza casi nunca agrega
  valor").

## Cuando la IA no sabe algo

Nunca inventa una respuesta plausible. El comportamiento correcto, en orden de preferencia: (1)
decirlo directamente y ofrecer la alternativa humana disponible; (2) si hay una fuente
verificable pero no consultada todavía, decir que se está verificando en vez de responder sin
verificar; (3) nunca un tercer camino que implique construir una respuesta razonable pero no
confirmada.

## Protocolo de entrega a un humano (handoff)

Toda derivación de la IA a una persona entrega, junto con la conversación, el contexto ya
procesado (resumen, si existe; motivo de la derivación) — nunca una derivación "en blanco" que
obligue a la persona a reconstruir el contexto desde cero. La derivación es explícita para
ambas partes: el cliente puede notar que ahora habla con una persona (ver Message Bubble, CDS,
distinción visual ya definida), y el asesor ve por qué le llegó ese caso.

## Voz de la IA según el contexto

Gabi (cara al cliente) habla en primera persona como representante del negocio, siguiendo las
reglas de personalidad ya definidas en el MDL (Capítulo 2). El Copiloto interno (cara al
equipo) habla como asistente, nunca como el sistema mismo emitiendo un aviso — la diferencia
es sutil pero deliberada: Gabi *es* una voz del negocio; el Copiloto *asiste* a una persona que
sigue siendo la que decide.

---

# Capítulo 3 — Decision Experience

*Este capítulo formaliza como estándar operable lo que el MDL declaró como principio central:
"Maiek no muestra información, ayuda a tomar decisiones". Cada regla de acá debajo existe para
que ese principio se pueda verificar en una pantalla concreta, no solo citarse.*

## Priorización

Lo primero que se muestra en cualquier vista es siempre lo de mayor impacto o urgencia real —
nunca lo más reciente por defecto, salvo que "más reciente" sea, en ese contexto específico,
también lo más urgente (ej. un mensaje que acaba de llegar sí es urgente por definición). El
orden cronológico es un caso particular del orden por prioridad, no la regla general.

## Reducción de carga cognitiva

Tres mecanismos, en este orden de preferencia antes de agregar cualquier otro:

1. **Pirámide invertida** — la conclusión primero, el razonamiento y el detalle después, bajo
   demanda (ver Divulgación progresiva, Capítulo 1).
2. **Límite numérico explícito** — nunca más de las opciones que una persona puede sostener en
   la cabeza a la vez sin escribirlas (referencia práctica ya usada en el CDS: máximo 4-5
   Quick Actions, máximo 7 ítems de Menú) — el mismo criterio aplica a cualquier lista de
   decisiones nueva, no solo a las ya especificadas.
3. **Un solo eje de comparación a la vez** — cuando se presentan alternativas, todas se
   describen con los mismos atributos en el mismo orden; mezclar formatos entre opciones
   comparables obliga al usuario a hacer el trabajo de normalización que el sistema debería
   haber hecho por él.

## Presentación de información orientada a decisión

Ningún dato se muestra sin que quede claro qué decisión ayuda a tomar. Un número sin verbo de
acción alrededor ("87%") es información; el mismo número con una acción posible al lado ("87%
· Muy alto · Llamar ahora") es ayuda a decidir. Todo bloque de datos en una pantalla de trabajo
debe poder responder "¿y ahora qué hago con esto?" sin que el usuario tenga que inferirlo.

## Recomendaciones

Toda recomendación de IA es siempre accionable de un clic o casi — nunca puramente descriptiva
(ver AI Suggestion Card, CDS, "cuándo NO utilizarlo": para datos objetivos sin interpretación).
Cuando existen varias alternativas válidas, se presentan en orden real de probabilidad de
éxito, nunca en orden alfabético ni de catálogo — y nunca como una única opción sin dejar
visible que existen otras.

## Explicación de sugerencias (Explainability First)

Regla dura, sin excepciones: ninguna recomendación de IA se muestra a menos que pueda
responder, de forma simple y visible, estas tres preguntas —

1. **¿Por qué?** — la razón de negocio detrás de la sugerencia.
2. **¿Por qué ahora?** — qué cambió o qué urgencia hace que esto importe en este momento y no
   en cualquier otro.
3. **¿Por qué yo?** — por qué esta persona específica es quien debe actuar, no otra.

— en una línea, en el mismo bloque, nunca detrás de un clic adicional para "ver por qué". Las
tres respuestas se escriben en el lenguaje del negocio ("porque lleva 3 días sin respuesta y es
tu cliente asignado"), nunca en el lenguaje del sistema ("score_confianza > 0.8"). Si una
recomendación no puede responder las tres con una frase simple, no se publica, sin importar
cuán preciso sea el modelo detrás — la explicabilidad es una condición de publicación, no un
adorno posterior.

## Confianza

La confianza no es un adorno visual — determina si algo se muestra (Capítulo 2) y cómo se
redacta (franjas de alta/media confianza, arriba). Nunca se presenta un nivel de confianza sin
que el usuario pueda entender, aunque sea de forma aproximada, qué tan seguro puede estar de
actuar en base a eso — un número de confianza sin contexto ("87%") es tan poco útil como no
mostrar confianza en absoluto si no viene acompañado de qué significa ese número en la práctica
(ver AI Confidence Indicator, CDS).

## Intervención humana

El límite exacto, heredado y formalizado de la sección 7 del MPA, se aplica en este documento
como regla de producto — no como observación:

- La IA **nunca** ejecuta sola una acción marcada como irreversible (Capítulo 1) sobre datos
  de un cliente real.
- La IA **nunca** cierra sola una negociación de precio o condición comercial especial.
- La IA **nunca** es la única vía para completar una acción — toda capacidad asistida por IA
  tiene una ruta manual equivalente disponible (ver AI Action Panel, CDS, "errores comunes").
- Cuando una decisión cruza este límite, el rol de la IA cambia de "decide" a "prepara la
  decisión para que una persona la tome más rápido" — nunca desaparece del todo, pero cambia
  de función.

---

*Fin de la Parte I — Approved. Partes II (Experiencia del Usuario) y III (Calidad y Evolución)
pendientes de desarrollo, siguiendo el mismo proceso: construir, revisar, aprobar por partes.*

---

# PARTE II — Experiencia del Usuario

*Esta parte responde una sola pregunta: ¿cómo vive el usuario, momento a momento, la
inteligencia que la Parte I ya definió? Ningún capítulo de esta Parte redefine un principio ya
establecido en la Parte I — toma sus reglas como entrada y define su forma perceptible: qué se
ve, qué se lee, qué se siente.*

*Regla editorial de esta Parte: todo principio importante incluye un ejemplo concreto de
aplicación y, cuando aporta valor, un contraejemplo de qué no hacer — breves, prácticos y
suficientes para que diseño, desarrollo y producto interpreten la regla de la misma manera.*

## Principios adicionales de esta Parte

Tres principios nuevos, transversales a los cuatro capítulos de esta Parte — se declaran una vez
acá y se operan en cada capítulo, con el mismo criterio ya usado en el Capítulo 0: un principio
orienta, una regla operable se sigue o se viola de forma verificable.

- **Predictable Interaction.** El usuario puede anticipar razonablemente el resultado de una
  acción antes de ejecutarla. Acciones similares producen consecuencias similares en cualquier
  parte del producto — la confianza nace tanto de la capacidad del sistema como de su
  previsibilidad. La sorpresa positiva pertenece siempre al *valor* que el sistema entrega,
  nunca al *comportamiento* de la interfaz: el usuario puede sorprenderse gratamente con lo que
  Maiek AI logra, pero nunca con cómo se comporta un control que ya conoce. Extiende, sin
  contradecir, la "Consistencia entre pantallas" ya definida en el Capítulo 1 de la Parte I (que
  fija la *forma* de respuesta — instantánea/optimista/confirmada); este principio cubre el
  criterio más amplio de que toda la interacción, no solo la forma de respuesta, sea anticipable.
  **Ejemplo:** un botón "Eliminar" se comporta igual —mismo ícono de advertencia, mismo tipo de
  confirmación— en Leads, Campañas y Canales; un usuario que aprendió el patrón en un módulo no
  tiene que reaprenderlo en otro.
  **Qué no hacer:** que el mismo ícono de "editar" abra un modal en un módulo y navegue a una
  página completa en otro — la inconsistencia obliga al usuario a probar antes de confiar,
  exactamente lo opuesto a lo que este principio busca.
- **Cross-channel Experience.** Las reglas de esta Parte no son específicas de un canal —
  aplican igual en Web, WhatsApp, Email, SMS o cualquier canal futuro. Un canal puede limitar el
  *formato* de una regla, nunca su *criterio*.
  **Ejemplo:** un estado de "solicitud procesada con éxito" transmite la misma sensación de
  cierre y control tanto en un Toast de la Web como en un mensaje de WhatsApp de texto plano —
  cambia el contenedor, no la emoción que produce.
  **Qué no hacer:** escribir un mensaje de confirmación cálido y completo para Web, y en
  WhatsApp enviar solo "OK" porque "es un canal más informal" — el usuario de WhatsApp merece el
  mismo nivel de claridad y cuidado, no una versión degradada.
- **Every Screen Teaches.** Ninguna superficie es "solo informativa" — un tooltip, un estado
  vacío o un mensaje de error dejan al usuario con más comprensión del producto de la que tenía
  antes de verlo.
  **Ejemplo:** un estado vacío de "Campañas" no dice solo "No tienes campañas" — dice "No tienes
  campañas activas. Una campaña te permite enviar una plantilla aprobada a un grupo de leads a
  la vez — crea la primera" (enseña qué es una campaña mientras informa que no hay ninguna).
  **Qué no hacer:** un tooltip que repite el nombre del botón que ya etiqueta ("Botón de
  Exportar" sobre un botón que dice "Exportar") — ocupa espacio de pantalla sin dejar
  aprendizaje.

---

# Capítulo 4 — Voz y contenido

## De la personalidad de marca a la voz de producto

El MDL (Capítulo 2) ya definió la personalidad de Maiek AI como marca — este capítulo no la
repite, la traduce a reglas de escritura verificables para cualquier texto de interfaz, sea o no
generado por la IA. Donde el Capítulo 2 de la Parte I definió cuándo y cómo habla la IA
(Gabi/Copiloto), este capítulo cubre el resto de la superficie escrita: botones, labels, errores
de validación, confirmaciones de sistema, estados vacíos.

## Tono según tipo de mensaje

No existe un tono único de producto — existen cuatro registros, cada uno con una función
distinta:

1. **Informativo** — neutro, sin adjetivos innecesarios ("Tu plan incluye 3 canales de
   WhatsApp").
2. **De error** — directo sobre qué pasó y qué hacer, nunca sobre quién tuvo la culpa ("No
   pudimos guardar el cambio. Verifica tu conexión e intenta de nuevo" — nunca "Error de
   validación en el campo X").
3. **De éxito** — breve, sin celebración excesiva ("Guardado" — no "¡Genial! Guardado con
   éxito").
4. **Conversacional** — el único registro donde cabe la voz de Gabi/Copiloto tal como la definió
   el Capítulo 2 de la Parte I; el resto de la interfaz no imita este registro.

**Qué no hacer:** usar tono conversacional en un mensaje de error del sistema ("¡Ups! Algo salió
mal 😅") — mezcla el registro de la IA conversacional con el de infraestructura, y le resta
seriedad a un momento donde el usuario necesita información clara, no simpatía.

## Microcopy: longitud, estructura, vocabulario

- **Botones** — verbo + objeto, nunca solo el verbo cuando hay ambigüedad ("Crear campaña", no
  solo "Crear" si la pantalla tiene más de una cosa que crear).
- **Labels de formulario** — sustantivo simple, sin instrucciones dentro del label ("Teléfono",
  nunca "Escribe el teléfono del cliente aquí" — esa instrucción, si hace falta, va en el
  placeholder o en un texto de ayuda debajo).
- **Tooltips** — una sola oración, nunca un párrafo — si necesita más de una oración, no es un
  tooltip, es contenido que merece su propio espacio en pantalla.

## Consistencia terminológica

Un mismo concepto se nombra exactamente igual en toda la interfaz, en el CDS, en el MPA y en las
conversaciones de Gabi. Existe una lista viva de términos canónicos (a mantenerse fuera de este
documento, en un glosario de producto) — este documento solo fija la regla, no la lista.

**Ejemplo:** si el MPA llama "Lead" a un contacto en el embudo comercial, ningún botón,
notificación o mensaje de Gabi lo llama "Cliente potencial" o "Prospecto" en su lugar.
**Qué no hacer:** que el módulo de Conversaciones diga "Contacto" y el módulo de Pipeline diga
"Lead" para referirse exactamente al mismo registro — obliga al usuario a aprender dos
vocabularios para un mismo concepto.

## Every Screen Teaches aplicado a microcopy

Antes de publicar cualquier texto breve nuevo, la pregunta de control es: *si un usuario nuevo
lee solo esto, ¿sabe algo más del producto que antes no sabía?* Un texto que solo repite lo que
ya es visible (el nombre de un botón, un ícono ya claro) falla esta prueba y debe reescribirse o
eliminarse.

## Cross-channel Experience aplicado a voz

El mismo vocabulario y actitud de este capítulo se sostienen en WhatsApp y Email — lo que cambia
por canal es exclusivamente extensión (WhatsApp favorece mensajes más cortos) y formalidad de
apertura (un Email puede abrir con saludo explícito; un mensaje de WhatsApp entra directo al
punto porque la conversación ya está en curso). El vocabulario canónico y el tono nunca cambian
entre canales.

---

# Capítulo 5 — Feedback y estados del sistema

## Vocabulario visual de estados

Toda pantalla o componente que espera datos pasa, en algún momento, por uno de cinco estados:
cargando, vacío, con datos, con error, éxito. Ningún estado se omite ni se combina con otro —
una pantalla nunca muestra "cargando" y "vacío" a la vez, por ejemplo.

## Emotional Feedback

Cada uno de los cinco estados tiene, además de su forma visual (ya definida en el CDS), una
emoción objetivo — la reacción que el usuario debería sentir al verlo, usada como criterio de
diseño antes de que exista una sola línea de copy o color:

| Estado | Emoción objetivo | Qué la sostiene |
|---|---|---|
| Cargando | Tranquilidad (no ansiedad de espera) | Skeleton que anticipa la forma del contenido, nunca una pantalla en blanco |
| Vacío | Claridad + control (sé qué hacer ahora) | Ver Empty State Intelligence, abajo |
| Con datos | Confianza (la información es correcta y está completa) | Sin indicadores de duda sobre datos ya cargados |
| Error | Calma + control (sé qué pasó y qué puedo hacer) | Mensaje que explica y ofrece una acción, nunca solo un símbolo rojo |
| Éxito | Progreso (avancé, puedo seguir) | Confirmación breve, sin fricción para continuar a lo siguiente |

**Ejemplo:** un error de envío de mensaje en el chat de WhatsApp no solo cambia el ícono a rojo
— agrega el texto "No se pudo enviar. Toca para reintentar", sosteniendo la emoción de calma y
control en vez de dejar al usuario adivinando.
**Qué no hacer:** un estado de error que solo muestra un ícono sin texto — técnicamente informa
que algo falló, pero no sostiene ninguna emoción objetivo: el usuario queda con ansiedad, no con
calma.

## Cuándo usar skeleton, spinner o progress bar

El CDS ya cataloga los tres componentes — este capítulo define el criterio de elección:

- **Skeleton** — cuando se conoce la forma aproximada del contenido que va a aparecer (una
  lista, una tarjeta) y la espera es breve. Sostiene mejor la emoción de tranquilidad porque
  anticipa la forma final.
- **Spinner** — cuando no se conoce la forma del resultado o la acción es puntual y sin
  estructura visual asociada (procesar un archivo).
- **Progress bar** — solo cuando existe un progreso real y medible (subir un archivo grande) —
  nunca como sustituto decorativo de un spinner cuando no hay un porcentaje real que mostrar.

**Qué no hacer:** una progress bar que avanza de forma simulada sin relación con el progreso
real de la operación — rompe la confianza que Emotional Feedback busca construir, porque el
usuario aprende que la barra miente.

## Comunicación de errores (Explainability First aplicado al error)

Todo mensaje de error responde, en un máximo de dos oraciones, las mismas preguntas que
Explainability First exige para una recomendación (Capítulo 3, Parte I), adaptadas al error: qué
pasó, y qué puede hacer el usuario ahora.

**Ejemplo:** "No pudimos enviar tu mensaje porque perdiste la conexión. Reintentar" (qué pasó +
acción concreta, con el botón de acción visible junto al texto).
**Qué no hacer:** "Error 500" o "Algo salió mal" sin acción disponible — dos formas comunes de
fallar la misma prueba: la primera es lenguaje de sistema, no de negocio (ver Capítulo 3, Parte
I); la segunda no deja ninguna acción clara.

## Empty State Intelligence

Regla dura, sin excepciones: ningún estado vacío se limita a comunicar ausencia — siempre
orienta a la siguiente acción concreta y ejecutable desde esa misma pantalla.

**Ejemplo:** el módulo de Campañas, sin campañas creadas, muestra: "No tienes campañas activas.
Crea la primera para enviar una plantilla aprobada a un grupo de leads" + botón "Crear campaña"
en la misma vista.
**Qué no hacer:** "No hay campañas" sin ninguna acción visible — dos formas distintas de fallar
la regla: una que dice qué falta pero no qué hacer (parcialmente correcta), y otra que ni
siquiera dice qué falta ("Sin resultados") — ambas incumplen la regla dura.

Distinto del vacío de primer uso: este cubre los vacíos **recurrentes** — una bandeja filtrada
sin resultados, un módulo sin actividad reciente. El vacío de la primera vez que el usuario abre
el producto tiene reglas propias, ver Capítulo 6.

## Delight, acotado por Quiet Confidence

El MDL define "Quiet Confidence" como principio de marca — nunca ruidoso, nunca a costa de
claridad o velocidad. Delight en esta Parte se limita a momentos de feedback donde un matiz
humano no añade fricción ni retraso — y respeta siempre Predictable Interaction: el matiz puede
sorprender gratamente por el *valor* que agrega (una frase que reconoce el logro), nunca por
cambiar el *comportamiento esperado* del componente (un botón que de pronto se mueve o tarda más
de lo normal "para lucirse" nunca es delight, es una ruptura de previsibilidad):

**Ejemplo permitido:** un mensaje de éxito tras completar un flujo largo (ej. terminar la
configuración de un canal de WhatsApp) que además del "Listo" funcional agrega una frase breve
de reconocimiento del logro ("Tu canal ya está activo. Los próximos mensajes ya llegarán acá") —
información útil con un matiz cálido, sin animación adicional ni retraso.
**Qué no hacer:** una animación de confeti o un sonido en cada guardado exitoso de un formulario
— rompe Quiet Confidence al introducir ruido en una acción rutinaria y frecuente; el delight se
reserva para logros poco frecuentes, nunca para acciones cotidianas.

---

# Capítulo 6 — Onboarding y primeras impresiones

## Cuándo termina el onboarding

El onboarding no es un tutorial con un número fijo de pasos — termina cuando el usuario alcanza
autonomía real para operar el producto sin necesitar guía adicional, no cuando se completa una
secuencia de pantallas de bienvenida. Un usuario puede terminar el tutorial y seguir sin saber
usar el producto; ese caso sigue siendo onboarding sin resolver, sin importar que la secuencia
guiada ya haya terminado.

**Ejemplo:** un asesor completó las 4 pantallas de bienvenida del panel, pero todavía no logra
crear una campaña sin ayuda — el onboarding de ese flujo específico sigue activo (Progressive
Intelligence sigue revelando ayuda contextual ahí) hasta que lo logre sin asistencia, sin
importar que el tutorial general ya haya terminado.
**Qué no hacer:** dar por completado el onboarding en el sistema (dejar de mostrar ayuda
contextual) solo porque el usuario cerró o saltó el tutorial — confunde "vio la introducción"
con "ya sabe operar el producto", que es la señal real que debería usarse. Cómo medir esa
autonomía de forma concreta es una definición que corresponde a la Parte III (Medición de
experiencia) — acá queda fijado el criterio, no la métrica.

## La primera sesión es un estado distinto del vacío recurrente

La primera vez que un usuario abre Maiek AI, cada pantalla vacía no es un "sin datos todavía" —
es una introducción a lo que esa pantalla hará cuando tenga datos. El texto y la acción sugerida
son más explicativos que los de un vacío recurrente (Capítulo 5), porque el usuario todavía no
sabe qué esperar de esa pantalla en absoluto.

**Ejemplo:** el primer vacío del Pipeline no dice "No tienes leads" (eso asume que el usuario ya
sabe qué es el Pipeline) — dice "Acá verás a tus clientes potenciales organizados por etapa,
desde el primer contacto hasta el cierre. Cuando Gabi reciba el primer mensaje, aparecerá acá
automáticamente."

## Progressive Intelligence aplicado al día 1

El Capítulo 2 de la Parte I ya declaró que la IA revela capacidades gradualmente — este capítulo
define qué se revela específicamente en el primer uso: solo la capacidad directamente
relacionada con la primera acción que el usuario necesita completar. Todo lo demás (Copiloto
avanzado, recomendaciones cruzadas) permanece invisible hasta que el contexto lo amerite,
siguiendo exactamente el mismo criterio ya definido, sin una lista nueva de reglas.

**Qué no hacer:** un tour guiado de bienvenida que presenta las 9 capacidades del producto antes
de que el usuario haya completado su primera acción real — contradice directamente Progressive
Intelligence, que exige mostrar solo lo relevante al momento, no un catálogo completo por
adelantado.

## Building Trust

La confianza en los primeros días no se declara, se demuestra — este capítulo define cómo:

- **Primera sugerencia de IA verificable.** La primera vez que Gabi o el Copiloto hacen una
  sugerencia, esa sugerencia debe ser de las más fáciles de verificar como correcta (alta
  confianza, Capítulo 2 Parte I) — no la más impresionante. Ganar una primera verificación
  simple construye más confianza que arriesgar una sugerencia ambiciosa que podría fallar.
- **Consistencia antes que variedad.** En la primera semana, el sistema prioriza comportarse de
  forma predecible (mismo tipo de sugerencia ante situaciones similares) sobre mostrar la
  diversidad completa de lo que puede hacer — la variedad se introduce después, cuando ya hay
  una base de confianza. Es Predictable Interaction aplicado al momento donde más pesa: antes de
  que exista historial, la previsibilidad es la única señal de confianza disponible.
- **Nunca prometer lo que todavía no se cumplió.** Ningún texto de onboarding usa lenguaje de
  capacidad futura como si ya estuviera disponible ("Gabi aprenderá tu negocio automáticamente"
  antes de que eso realmente haya ocurrido) — se describe lo que el sistema ya hace hoy, no su
  visión a futuro.

**Ejemplo:** un mensaje de bienvenida que dice "Gabi ya puede responder preguntas frecuentes
sobre tu catálogo" (verificable de inmediato) construye más confianza que "Gabi entenderá cada
vez mejor a tus clientes" (promesa sin nada que el usuario pueda comprobar en ese momento).
**Qué no hacer:** un banner de bienvenida que enumera funciones que el usuario todavía no puede
usar porque dependen de configuración pendiente (ej. mencionar campañas masivas antes de que el
usuario tenga una plantilla aprobada) — genera expectativa sin poder cumplirla de inmediato.

## Delight en el primer uso, mismo límite que el Capítulo 5

**Ejemplo permitido:** al completar la entrevista inicial de configuración del negocio, un
mensaje breve reconoce el paso completado sin exagerar ("Tu negocio ya está configurado. Gabi ya
puede empezar a conversar") — informa y reconoce sin ceremonia adicional.
**Qué no hacer:** una pantalla de celebración a pantalla completa con animación al terminar el
onboarding — rompe Quiet Confidence exactamente igual que en el Capítulo 5, con el agravante de
que retrasa al usuario justo en el momento en que más quiere empezar a usar el producto.

## Cross-channel Experience aplicado a onboarding

Si el primer contacto de un usuario con Maiek AI ocurre por WhatsApp (ej. un cliente final que
escribe por primera vez a un negocio que ya usa Gabi) en vez de por la Web (un asesor
configurando el panel), el nivel de confianza transmitido debe ser equivalente aunque la
mecánica sea distinta — un primer mensaje de Gabi bien enmarcado en WhatsApp construye la misma
confianza inicial que un buen primer vacío guiado en el panel Web.

---

# Capítulo 7 — Notificaciones e interrupciones

## Canales de notificación disponibles

Toda notificación se entrega por uno de estos canales, elegido según la urgencia real (nunca por
defecto ni por preferencia técnica de implementación):

- **In-app silenciosa** (contador, punto en el ítem del menú) — para información que el usuario
  verá la próxima vez que visite esa sección, sin urgencia de notificarlo activamente.
- **Banner in-app** — para algo relevante mientras el usuario ya está usando el producto, sin
  sacarlo de la pantalla actual.
- **Push / externo (WhatsApp, Email — futuro)** — reservado para lo que requiere atención fuera
  de una sesión activa del producto.

**Qué no hacer:** usar push para algo que podría esperar a un badge silencioso (ej. "un lead
cambió de nombre") — degrada la utilidad del canal más intrusivo, entrenando al usuario a
ignorar todas las notificaciones push, incluidas las que sí importan.

## Agrupación y batching

Eventos de baja urgencia individual que ocurren en ráfaga se agrupan en una sola notificación en
vez de una por evento.

**Ejemplo:** "3 leads nuevos en la última hora" en vez de tres notificaciones separadas, una por
cada lead — mismo criterio que la Reducción de carga cognitiva de la Parte I (Capítulo 3)
aplicado a interrupciones en vez de a pantallas.
**Qué no hacer:** siete notificaciones separadas en la barra en menos de un minuto porque siete
eventos ocurrieron casi al mismo tiempo — el volumen, no la urgencia real de cada una, es lo que
termina generando la sensación de saturación.

## Jerarquía visual: notificación de sistema vs. sugerencia de IA

No toda interrupción viene de la IA — un evento de sistema (ej. "nuevo lead asignado") es
distinto de una sugerencia de IA (ej. "este lead lleva 3 días sin respuesta, considera
llamarlo"), y deben verse distinto para que el usuario entienda de inmediato si está ante un
hecho o ante una recomendación.

**Ejemplo:** una notificación de sistema usa un ícono neutro y lenguaje descriptivo ("Nuevo lead
asignado: Juan Pérez"); una sugerencia de IA usa el mismo lenguaje visual que la AI Suggestion
Card del CDS, para que el usuario reconozca de inmediato "esto es una recomendación, no un
hecho".
**Qué no hacer:** que ambas usen el mismo componente visual genérico de notificación — obliga al
usuario a leer el texto completo cada vez para distinguir un hecho de una opinión del sistema,
en vez de reconocerlo de un vistazo.

## Degradación por fatiga

El mismo criterio del Capítulo 2 de la Parte I ("cómo se retira una sugerencia ignorada") se
extiende a notificaciones repetidas del mismo tipo: si un tipo específico de notificación se
ignora de forma consistente, su frecuencia se reduce automáticamente (nunca se apaga por
completo sin acción explícita del usuario) — el sistema aprende que ese tipo de aviso no le
aporta valor a esa persona en particular.

## Cross-channel Experience aplicado a notificaciones

El criterio de agrupación, jerarquía y degradación por fatiga es el mismo sin importar si la
notificación llega dentro del producto o por un canal externo (WhatsApp, Email) — lo que cambia
es únicamente el formato de entrega, nunca el criterio de cuándo y cuánto notificar.

---

*Fin de la Parte II — Approved. Parte III (Calidad y Evolución) pendiente de desarrollo,
siguiendo el mismo proceso: construir, revisar, aprobar por partes.*

---

# PARTE III — Calidad y Evolución

*Esta parte responde una sola pregunta: ¿cómo garantizamos que la experiencia de Maiek AI siga
siendo consistente, medible y evolucione correctamente con el tiempo? Ningún capítulo de esta
Parte define una regla nueva de interacción, protocolo de IA, feedback, onboarding o
notificación — todas esas ya están cerradas en las Partes I y II. Esta Parte mide, gobierna y
preserva lo ya definido, y define el proceso por el cual eso puede cambiar sin dejar de ser
Maiek AI.*

*Regla editorial heredada de la Parte II: todo principio o regla importante incluye un ejemplo
concreto de aplicación y, cuando aporta valor, un contraejemplo de qué no hacer.*

## Principios adicionales de esta Parte

Dos principios nuevos, ambos de gobernanza — se declaran una vez acá y se operan
fundamentalmente en los Capítulos 10 y 11. Son complementarios, no redundantes: uno protege, el
otro justifica.

- **Stable by Default.** Las reglas del MPX cambian por evidencia y revisión de gobernanza —
  nunca por preferencia individual, presión de una sola persona o urgencia de una funcionalidad
  puntual. Protege la estabilidad del sistema completo frente al cambio casual.
  **Ejemplo:** una funcionalidad que necesita romper la regla de reversibilidad (Capítulo 1)
  para un caso de negocio específico no cambia la regla — se registra como Experience Debt
  (Capítulo 11) hasta que exista evidencia suficiente para evaluar un cambio real.
  **Qué no hacer:** cambiar el umbral de confianza del protocolo de incertidumbre (Capítulo 2)
  porque un asesor senior lo pidió en una reunión — sin datos de Medición de experiencia
  (Capítulo 10) que respalden que el umbral actual está mal calibrado, ese cambio no tiene base.
- **Evidence over Opinion.** Toda modificación relevante del MPX se sustenta en evidencia
  objetiva — principalmente las métricas del Capítulo 10 — nunca únicamente en opiniones,
  preferencias individuales o jerarquía dentro del equipo. Responde *qué cuenta como
  justificación válida* para una evolución; Stable by Default responde *qué tan fácil debe ser
  cambiar algo* (difícil, por diseño). Uno protege, el otro define cómo se gana el derecho a
  cambiar.
  **Ejemplo:** una propuesta de cambiar el modelo de respuesta optimista (Capítulo 1) a
  confirmada en un flujo específico se acompaña de la tasa de deshacer real de ese flujo
  (Capítulo 10) como evidencia — no solo de la percepción de que "se siente arriesgado".
  **Qué no hacer:** aprobar un cambio de regla de experiencia porque lo pide la persona con más
  antigüedad o mayor cargo, sin que exista evidencia del Capítulo 10 detrás — Evidence over
  Opinion existe exactamente para prevenir ese patrón, sin importar quién lo proponga.

---

# Capítulo 8 — Personalización y continuidad

## Qué gobierna este capítulo y qué no

Este capítulo opera el mecanismo completo de **Memory Experience**, principio declarado en el
Capítulo 0 (Parte I) y explícitamente diferido hasta acá. No redefine Progressive Intelligence
(Capítulo 2) — ese capítulo ya cubre qué se revela **dentro** de una interacción según el
contexto inmediato; este cubre la continuidad **a través del tiempo**: entre sesiones, entre
días, entre canales.

## Tres tipos de memoria, límites explícitos

Antes de cualquier regla de personalización, es necesario distinguir tres conceptos que suelen
confundirse porque los tres "recuerdan algo" — pero cada uno tiene un alcance, una duración y un
propósito distintos:

1. **Memoria persistente del usuario** — información que sobrevive entre sesiones, días y
   canales: preferencias ya expresadas, decisiones tomadas, hechos ya contados por el usuario.
   Es la que opera Memory Experience en su forma más literal ("un usuario que ya contó algo no
   debería tener que repetirlo"). Vive fuera de una conversación específica — un asesor que
   configuró su horario de atención una vez no debería tener que repetirlo en cada sesión nueva.
   **Ejemplo:** un cliente que ya indicó que prefiere ser contactado por la tarde — esa
   preferencia se aplica en la próxima campaña, semanas después, sin que nadie se lo repita a
   Gabi.
2. **Memoria conversacional** — el historial de una conversación específica en curso (el mismo
   historial que ya usa el sistema para dar contexto a Gabi dentro de un hilo con un número de
   teléfono). Vive mientras la conversación sigue activa o reciente; no es necesariamente
   persistente a largo plazo salvo que algo de ahí se promueva explícitamente a memoria
   persistente.
   **Ejemplo:** un cliente que dijo "quiero 3 balones de gas" hace dos mensajes — Gabi no le
   pregunta de nuevo la cantidad en el mismo hilo. Si la conversación se cierra y el cliente
   vuelve en un mes con un pedido distinto, ese detalle puntual no persiste necesariamente (a
   menos que sea información de perfil, no de un pedido puntual).
3. **Contexto temporal de una interacción** — información relevante solo para la acción
   inmediata en curso, que se descarta al terminar: qué campo tiene foco, qué filtro está activo
   en una tabla, qué paso de un formulario multi-paso se está completando. Nunca se persiste ni
   se recuerda entre sesiones — no es memoria en el sentido de Memory Experience, es estado de
   interacción momentáneo ya cubierto por el Modelo de respuesta (Capítulo 1).

**Regla de límite:** algo solo se promueve de contexto temporal a memoria conversacional, y de
memoria conversacional a memoria persistente, cuando tiene valor fuera del momento en que
ocurrió — nunca por defecto. Guardar todo "por si acaso" viola tanto Predictable Interaction
como la relación de confianza con el dato del usuario.

**Qué no hacer:** tratar un filtro de tabla que el usuario activó una vez como si fuera una
preferencia persistente y reaplicarlo automáticamente en su próxima visita sin que lo haya
pedido — confunde contexto temporal con memoria persistente y produce un comportamiento que el
usuario no puede anticipar (rompe Predictable Interaction).

## Vigencia y decaimiento de la memoria persistente

No toda memoria persistente vive para siempre de la misma forma — se distinguen dos categorías
según su naturaleza:

- **Memoria estructural** — datos de perfil y configuración explícitos (horario, preferencias
  declaradas, datos de contacto) — permanece vigente hasta que el usuario la cambie
  explícitamente, sin fecha de expiración.
- **Memoria inferida** — patrones que el sistema dedujo del comportamiento (ej. "este cliente
  suele comprar los viernes") — tiene una vigencia limitada y se revalida contra comportamiento
  reciente; un patrón que dejó de repetirse deja de usarse como base de sugerencias, sin que
  nadie tenga que borrarlo manualmente.

**Ejemplo:** una preferencia de horario de contacto declarada explícitamente por el cliente se
mantiene indefinidamente; un patrón inferido de "compra los viernes" que no se repitió en las
últimas semanas deja de influir en las sugerencias de Gabi, sin necesidad de intervención
humana.
**Qué no hacer:** tratar un patrón inferido con la misma permanencia que un dato declarado
explícitamente — un comportamiento que cambió (el cliente ahora compra los martes) seguiría
generando sugerencias basadas en un patrón obsoleto, contradiciendo la confianza que Building
Trust (Capítulo 6) busca sostener.

## Continuidad entre canales

Cross-channel Experience (preámbulo Parte II) aplicado a memoria: la memoria persistente de un
usuario no está atada a un canal — si un cliente escribió por WhatsApp y luego un asesor lo
contacta por Email, la información ya conocida no se vuelve a pedir solo porque cambió el canal.

**Ejemplo:** un cliente que ya indicó su dirección de entrega por WhatsApp no tiene que
repetirla si el flujo continúa por otro canal.
**Qué no hacer:** que cada canal mantenga su propia memoria aislada del mismo usuario — obliga
al cliente a "reintroducirse" cada vez que cambia de canal, lo opuesto exacto de Memory
Experience.

## Límite entre personalizar y volverse impredecible

La personalización cambia *qué* se sugiere o se prioriza (contenido) — nunca *cómo* se comporta
un control o una pantalla (estructura), que es terreno de Predictable Interaction (preámbulo
Parte II).

**Ejemplo:** para un cliente frecuente, Gabi prioriza mostrar primero los productos que suele
pedir — pero el flujo de pedido, los botones y la estructura de la conversación son idénticos a
los de un cliente nuevo.
**Qué no hacer:** cambiar la disposición o el comportamiento de la interfaz según el perfil del
usuario (ej. ocultar pasos del flujo para "usuarios expertos" de forma automática sin que lo
pidan) — eso no es personalización de contenido, es una ruptura de Predictable Interaction que
hace que dos usuarios no puedan ayudarse mutuamente porque ven productos distintos del sistema.

---

# Capítulo 9 — Manejo de errores y casos límite

## Qué gobierna este capítulo y qué no

El Capítulo 5 (Parte II) ya definió cómo se ve y se redacta un error puntual — este capítulo
define algo distinto: el árbol de decisión de cuándo se activa cada nivel de degradación, y qué
ocurre en los casos que ningún flujo normal cubre: fallas en cascada, IA no disponible, timeouts
prolongados, datos en conflicto.

## Jerarquía de degradación

Toda falla del sistema se resuelve en uno de tres niveles, evaluados en este orden:

1. **Reintento silencioso** — para fallas transitorias de baja severidad (ej. una llamada de red
   que falla una vez); el sistema reintenta automáticamente sin involucrar al usuario, respetando
   el umbral de Loading ya definido (Capítulo 1) antes de escalar al siguiente nivel.
2. **Degradación visible con alternativa** — cuando el reintento silencioso no resuelve la
   falla, el sistema comunica el error (Capítulo 5) y ofrece una alternativa funcional, aunque
   sea limitada (ej. IA no disponible → el asesor puede seguir escribiendo manualmente, sin
   sugerencias).
3. **Bloqueo explícito** — reservado exclusivamente para los casos donde continuar sin resolver
   la falla arriesgaría datos o dinero de un cliente real (ej. no se puede confirmar si un pago
   se procesó) — nunca se usa por comodidad de implementación.

**Ejemplo:** si el servicio de IA no responde, el Copiloto se oculta y el asesor sigue operando
manualmente con toda la funcionalidad no asistida disponible — nivel 2, nunca nivel 3, porque
el negocio puede seguir operando sin la IA.
**Qué no hacer:** bloquear toda la pantalla con un modal de error cada vez que la IA tarda en
responder — convierte una falla de un componente opcional (Capítulo 2: la IA nunca es la única
vía para completar una acción) en un bloqueo total, violando esa regla ya establecida en la
Parte I.

## Cuándo el protocolo de IA no puede seguirse

El Capítulo 2 (Parte I) ya define el protocolo de entrega a un humano para cuando la IA llega al
límite de su conocimiento — este capítulo extiende el mismo patrón al caso en que la IA no está
disponible en absoluto (no es que no sepa, es que no responde): el sistema degrada al mismo
patrón de "ruta manual equivalente disponible" (Capítulo 3, Intervención humana) ya declarado,
sin inventar un comportamiento nuevo.

## Ediciones concurrentes y datos en conflicto

Cuando dos personas modifican el mismo registro casi al mismo tiempo, la resolución sigue el
mismo criterio de Reversibilidad (Capítulo 1): se prioriza la versión más reciente, se notifica
a quien perdió su cambio, y se ofrece deshacer o reaplicar — nunca una fusión automática
silenciosa de ambos cambios, que rompería Predictable Interaction al producir un resultado que
ninguna de las dos personas escribió.

**Ejemplo:** dos asesores editan el mismo lead — el segundo en guardar ve "Este lead fue
actualizado por [nombre] mientras editabas. Tu cambio no se guardó — revisar y reintentar" en
vez de que su cambio se pierda en silencio.
**Qué no hacer:** que el sistema combine automáticamente ambos cambios sin decírselo a nadie —
ni predecible ni seguro, y contradice directamente el modelo de deshacer (Capítulo 1), que exige
que toda pérdida de un cambio del usuario sea visible y accionable.

## Timeouts más allá del umbral esperado

Cuando una espera supera el umbral de Loading (Capítulo 1) y el reintento silencioso (arriba)
también falla, la interfaz deja de mostrar un estado de "cargando" indefinido y pasa a un estado
de error explícito con acción — nunca una rueda de carga girando sin límite de tiempo, que viola
Emotional Feedback (Capítulo 5): una espera sin fin no sostiene tranquilidad, sostiene ansiedad
creciente.

---

# Capítulo 10 — Medición de experiencia

## Qué gobierna este capítulo y qué no

Este capítulo no define comportamiento — verifica si los 20 principios de las Partes I y II se
sostienen en el producto real. Cada métrica existe porque verifica un principio específico, no
como indicador genérico de producto.

## Tabla de métricas núcleo

| Métrica | Principio que verifica | Qué significa un valor fuera de rango |
|---|---|---|
| Tiempo hasta autonomía | "El onboarding termina cuando el usuario alcanza autonomía" (Capítulo 6) | El onboarding declarado completo no lo está realmente — señal de revisar el flujo, no de bajar el estándar de "autonomía" |
| Tiempo hasta primer valor | Building Trust (Capítulo 6) | La primera sugerencia verificable tarda demasiado en llegar — la confianza inicial no se está construyendo a tiempo |
| Tasa de aceptación de sugerencias | Protocolo de incertidumbre + Explainability First (Capítulos 2-3) | Aceptación baja en "alta confianza" sugiere umbrales mal calibrados; aceptación alta en "requiere validación" sugiere que la etiqueta ya no comunica la incertidumbre real |
| Tasa de deshacer | Reversibilidad, modelo de respuesta optimista (Capítulo 1) | Tasa alta en una acción marcada optimista es evidencia de que esa clasificación de reversibilidad fue un error de diseño |
| Frecuencia de degradación a manual | Manejo de errores (Capítulo 9) | Frecuencia alta indica que la IA no está disponible con la confiabilidad que el protocolo asume |
| Tasa de notificaciones ignoradas por tipo | Degradación por fatiga (Capítulo 7) | Tasa alta y sostenida en un tipo específico es evidencia de que ese tipo de notificación no aporta valor real, más allá de lo que la degradación automática ya corrige |

**Ejemplo:** si la tasa de deshacer de "enviar mensaje" (clasificada como optimista) se mantiene
consistentemente alta, esa métrica es la evidencia que Evidence over Opinion exige antes de
considerar reclasificar esa acción como confirmada — no una opinión de que "se siente
arriesgado".
**Qué no hacer:** medir una métrica de vanidad no atada a ningún principio (ej. "tiempo total en
la app") como si fuera evidencia de salud de experiencia — si no verifica un principio
específico del MPX, no pertenece a este capítulo, aunque sea un dato interesante para otro
propósito de negocio.

## Regla de uso: evidencia, no gatillo automático

Ninguna métrica de esta tabla dispara un cambio de regla por sí sola — alimenta al Capítulo 11
como evidencia (Evidence over Opinion) para una revisión de gobernanza, nunca actúa de forma
automática. Esto es lo que sostiene Stable by Default: un valor fuera de rango es una señal de
revisar, no una orden de cambiar.

---

# Capítulo 11 — Product Experience Governance

## Qué gobierna este capítulo y qué no

Este capítulo no define ninguna regla de experiencia — define el proceso por el cual las reglas
ya existentes se verifican en funcionalidad nueva, se excepcionan con trazabilidad cuando hace
falta, y eventualmente cambian con evidencia. Gobierna los 11 capítulos anteriores del MPX.

## Experience Review Checklist

Checklist breve, aplicado antes de aprobar cualquier funcionalidad nueva — convierte el MPX en
una herramienta operativa de revisión, no solo en documentación de referencia. Cada pregunta se
responde Sí/No; cualquier "No" sin una Experience Debt registrada (abajo) bloquea la aprobación:

1. **¿La forma de respuesta es una de las tres definidas y está clasificada de reversibilidad
   correctamente?** (Capítulo 1)
2. **¿Ninguna capacidad de IA interrumpe sin poder ignorarse?** (Capítulo 2)
3. **¿Toda recomendación de IA responde por qué / por qué ahora / por qué yo?** (Capítulo 3)
4. **¿El texto de interfaz usa el registro correcto y el vocabulario canónico existente?**
   (Capítulo 4)
5. **¿Cada estado (cargando/vacío/error/éxito) tiene su emoción objetivo sostenida, y ningún
   estado vacío se limita a comunicar ausencia?** (Capítulo 5)
6. **¿La primera experiencia construye confianza con resultados verificables, no promesas?**
   (Capítulo 6)
7. **¿Las notificaciones usan el canal correcto según urgencia real y se degradan por fatiga?**
   (Capítulo 7)
8. **¿Lo que se recuerda respeta los tres límites de memoria y no se persiste "por si acaso"?**
   (Capítulo 8)
9. **¿Existe una ruta de degradación definida si algo falla, sin bloquear el flujo completo por
   defecto?** (Capítulo 9)
10. **¿La funcionalidad es igual de predecible y consistente en todos los canales donde va a
    vivir?** (Cross-channel Experience, Predictable Interaction)

**Ejemplo:** una funcionalidad nueva de "recordatorios automáticos" pasa el checklist: usa Toast
con deshacer (reversible, ítem 1), no interrumpe el flujo activo (ítem 2), y se degrada a
recordatorio manual si el servicio de programación falla (ítem 9).
**Qué no hacer:** aprobar una funcionalidad que falla dos ítems del checklist "porque el plazo
de entrega es esta semana" sin registrar Experience Debt — es exactamente el patrón que Stable
by Default existe para prevenir; el plazo no es evidencia.

## Experience Debt

Cuando una funcionalidad necesita apartarse del MPX por una razón de negocio real, esa
desviación se registra — nunca se shippea en silencio. Un registro de Experience Debt contiene,
como mínimo:

- **Qué principio o regla se viola** — referencia directa al capítulo/sección del MPX.
- **Por qué** — la razón de negocio concreta, no una preferencia.
- **Alcance** — qué funcionalidad exacta, no "todo el módulo".
- **Temporal o permanente** — si es temporal, fecha de revisión obligatoria; si se propone
  permanente, pasa a evaluarse como una propuesta de cambio real del MPX (ver Evolución
  controlada, abajo), no queda como deuda indefinida.

**Ejemplo:** una integración con un proveedor externo de pagos que solo permite confirmación
diferida (rompe el modelo de respuesta optimista, Capítulo 1) se registra como Experience Debt
temporal, con revisión programada para cuando el proveedor ofrezca confirmación inmediata.
**Qué no hacer:** una Experience Debt sin fecha de revisión ni alcance definido ("vamos a romper
la regla de reversibilidad en Pagos por ahora") — eso no es una excepción gobernada, es la regla
rompiéndose sin que nadie lo audite después.

## Evolución controlada del MPX

Este documento se versiona igual que cualquier documento oficial de Maiek AI
(`DOCUMENTATION_INDEX.md`, sección 8, gobierna el proceso general de todo documento — este
apartado no lo repite, define la instancia específica para cambios de contenido de experiencia).
Un cambio de regla de experiencia sigue esta secuencia, nunca una edición directa sobre una
Parte ya Approved:

1. Evidencia del Capítulo 10 (o una Experience Debt recurrente que revela un patrón, no un caso
   aislado) — Evidence over Opinion.
2. Propuesta de cambio explícita, con qué principio o regla exacta cambia y por qué.
3. Revisión de gobernanza — nunca aprobado por una sola persona sin registro.
4. Nueva entrada en Control de versiones del MPX, nunca edición silenciosa de una Parte Approved.

**Qué no hacer:** que un ajuste de experiencia se implemente directo en código sin pasar por
esta secuencia, dejando el MPX desactualizado respecto al comportamiento real del producto — el
documento deja de ser confiable como referencia en el momento en que el producto real se aparta
de él sin que el documento lo sepa.

---

*Fin de la Parte III — Approved. Con esto, el MAIEK PRODUCT EXPERIENCE (MPX) v1.0 queda completo
y congelado — Partes I, II y III, sus 22 principios (13 + 7 + 2) y sus 12 capítulos (0 a 11).*

### Nota de QA arquitectónico (autorevisión antes de tu revisión)

Verificación de que ningún capítulo de la Parte III reintrodujo una regla ya definida en Parte
I/II:

- Capítulo 8 no redefine Progressive Intelligence (Capítulo 2) — solo lo distingue y opera la
  dimensión temporal que ese capítulo dejó fuera a propósito.
- Capítulo 9 no redefine el vocabulario visual de error (Capítulo 5) — opera únicamente el árbol
  de decisión de cuándo se activa cada nivel.
- Capítulo 10 no define comportamiento — cada fila de la tabla de métricas apunta a un principio
  ya existente, ninguna introduce una regla nueva.
- Capítulo 11 no redefine ninguna regla de experiencia — el Experience Review Checklist es una
  síntesis operativa de reglas ya existentes, citadas por capítulo, no una reformulación.
- Ninguna referencia cruzada a `DOCUMENTATION_INDEX.md` duplica sus reglas de gobernanza
  documental general — el Capítulo 11 declara explícitamente que es una instancia específica de
  ese marco para cambios de contenido de experiencia, no un proceso paralelo.

No se detectaron contradicciones con las Partes I o II, ni con MDL, CDS o MPA.

---

## Jerarquía documental

Orden de precedencia entre los documentos que fundamentan el MPX y las especificaciones que él
mismo fundamenta — relevante quien decide cuál documento prevalece ante un conflicto aparente:

1. **Framework** — identidad, principios y forma de razonar de Maiek AI. Autoridad máxima; ningún
   documento posterior puede contradecirlo.
2. **MPA** (Product Architecture) — qué existe en el producto y cómo se organiza funcionalmente.
3. **MDL** (Design Language) — cómo se ve y qué principios visuales/de marca rigen.
4. **CDS** (Component Design System) — de qué piezas concretas dispone el sistema, construido
   sobre los tokens y principios del MDL.
5. **MPX** (este documento) — cómo se comporta y se siente el producto, construido sobre los
   cuatro anteriores; ninguna regla del MPX puede contradecir al Framework, al MPA, al MDL o al
   CDS.
6. **Especificaciones derivadas** (futuras: Frontend Architecture, Backend Architecture, patrones
   de producto específicos) — construidas sobre los cinco documentos anteriores, incluido el MPX.

**Regla de conflicto:** ante una contradicción aparente entre dos documentos, prevalece el de
mayor jerarquía (más cercano al Framework) — el de menor jerarquía se corrige, nunca al revés,
salvo que el cambio siga el proceso de Evolución controlada ya definido (Capítulo 11) y quede
reflejado en el Control de versiones del documento correspondiente. Una especificación derivada
futura que contradiga una regla ya Approved del MPX se ajusta a la especificación, no al MPX.

---

## Estado del documento

| | |
|---|---|
| Estado | **Approved** |
| Versión | 1.0 |
| Congelado | Sí — Partes I, II y III completas y Approved |
| Última revisión arquitectónica | 2026-07-28 (QA arquitectónico de la Parte III, sin contradicciones detectadas con Parte I/II, MDL, CDS o MPA) |
| Regla de próxima revisión | Únicamente mediante el proceso ya definido en los Capítulos 10 (Medición de experiencia) y 11 (Product Experience Governance) — evidencia primero (Evidence over Opinion), revisión de gobernanza, nueva entrada en Control de versiones. Nunca edición directa sobre una Parte ya Approved. |
