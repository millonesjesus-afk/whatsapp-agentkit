# Maiek AI — Product Experience (MPX)

**Versión 1.0 · Estado: Parte I Approved (Partes II y III pendientes)**

| | |
|---|---|
| Documento | Maiek Product Experience (MPX) |
| Proyecto | Maiek AI |
| Versión | 1.0 (en construcción por partes) |
| Estado | **Parte I: Approved** · Partes II-III: no iniciadas |
| Fecha de creación | 2026-07-26 |
| Autor | Claude, a pedido de Jesús Millones |
| Última actualización | 2026-07-26 |

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

Este documento se construye y aprueba **por partes**, a pedido explícito del usuario — cada
parte se revisa antes de continuar con la siguiente. La tabla de arriba se actualiza al cerrar
cada parte, no solo al final del documento completo.

---

# Índice del documento completo

*(referencia — solo la Parte I está desarrollada en este archivo; ver estructura aprobada)*

**Parte I — Fundamentos de la Experiencia** · "¿Cómo piensa y toma decisiones Maiek AI?"
- Capítulo 0 — Marco de experiencia
- Capítulo 1 — Interaction Model
- Capítulo 2 — Protocolo de interacción con IA
- Capítulo 3 — Decision Experience

**Parte II — Experiencia del Usuario** *(pendiente)* · "¿Cómo vive el usuario la filosofía definida en la Parte I?"
- Capítulo 4 — Voz y contenido
- Capítulo 5 — Feedback y estados del sistema
- Capítulo 6 — Onboarding y primeras impresiones
- Capítulo 7 — Notificaciones e interrupciones

**Parte III — Calidad y Evolución** *(pendiente)* · "¿Cómo garantizamos que la experiencia se mantenga consistente y evolucione con el tiempo?"
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
