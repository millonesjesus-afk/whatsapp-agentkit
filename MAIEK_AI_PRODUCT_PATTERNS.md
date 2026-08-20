# Maiek AI — Product Patterns

**Versión 1.0 · Estado: Approved**

| | |
|---|---|
| Documento | Maiek Product Patterns |
| Proyecto | Maiek AI |
| Versión | 1.0 |
| Estado | **Approved** |
| Fecha de creación | 2026-07-30 |
| Autor | Claude, a pedido de Jesús Millones |
| Fecha de aprobación | 2026-07-30 |
| Última actualización | 2026-08-08 (Capítulo 6 — herencia de atribución de campaña, ver Control de versiones) |

## Dependencias

- `MAIEK_AI_FRAMEWORK.md` — identidad y voz de marca aplicada al contenido de ejemplo de cada
  patrón.
- `MAIEK_AI_PRODUCT_ARCHITECTURE.md` (MPA) — cada patrón se traza a un módulo funcional ya
  definido; este documento no introduce ningún módulo nuevo.
- `MAIEK_AI_DESIGN_SYSTEM.md` (MDL v1.1) — cada patrón usa exclusivamente tokens ya definidos
  (espaciado, color, tipografía, radio, elevación, motion).
- `MAIEK_AI_COMPONENT_SYSTEM.md` (CDS v1.0) — cada patrón se construye ensamblando componentes
  ya catalogados; ninguno se redefine acá.
- `MAIEK_AI_PRODUCT_EXPERIENCE.md` (MPX v1.0) — cada patrón aplica reglas de comportamiento,
  voz e interacción con IA ya definidas.
- `MAIEK_AI_FRONTEND_ARCHITECTURE.md` — decisiones ya `Activas` sobre organización de la
  interfaz (envoltura única, navegación por fragmento, ocultar-no-vaciar) que este documento
  respeta sin redefinir.

## Consumido por

- Cualquier implementación futura del frontend de Maiek AI — este documento es la referencia
  canónica obligatoria a partir de su aprobación (ver principio 1, Capítulo 0).
- La próxima revisión de `MAIEK_AI_FRONTEND_ARCHITECTURE.md`, que hoy no tiene ningún patrón
  visual concreto del cual partir.

## Alcance y ubicación en la jerarquía documental

Especificación derivada — nivel 6 de la Jerarquía documental ya declarada por
`MAIEK_AI_PRODUCT_EXPERIENCE.md` (Framework → MPA → MDL → CDS → MPX → Especificaciones
derivadas), **hermana de `MAIEK_AI_FRONTEND_ARCHITECTURE.md`, no superior a ella**. No redefine
tokens (MDL), no redefine componentes (CDS), no redefine comportamiento ni voz (MPX), no
introduce módulos funcionales (MPA), no prescribe framework, librería ni código.

## Control de versiones

| Versión | Fecha | Autor | Descripción |
|---|---|---|---|
| 0.1 (borrador, inicio) | 2026-07-30 | Claude | Primera versión — Capítulo 0 (Propósito) y Capítulo 1 (Patrón: Shell de Navegación). Redacción incremental, capítulo por capítulo, a pedido explícito del usuario. |
| 0.1 (borrador, completo) | 2026-07-30 | Claude | Redacción incremental completada, capítulo por capítulo, cada uno revisado y ajustado por el usuario antes de continuar con el siguiente: Capítulo 2 (Bandeja de Conversaciones), Capítulo 3 (Inicio), Capítulo 4 (Analítica), Capítulo 5 (Copiloto IA), Capítulo 6 (CRM/Pipeline), Capítulo 7 (Catálogo, Campañas, Equipo) y Capítulo 8 (Principios Transversales de Producto, consolidando Plataforma primero, Capacidad vs. alcance, Acción antes que observación, Human Decision Gate, Única fuente de verdad, y La IA asiste-nunca reemplaza). |
| 1.0 (Approved) | 2026-07-30 | Claude | Precisión final incorporada a Plataforma primero (especializar un patrón vía configuración/permisos/parametrización es válido; modificar el patrón canónico no lo es). Auditoría documental completa de calidad y consistencia: referencias cruzadas, numeración, trazabilidad, terminología y citas a MPA/MDL/MPX verificadas contra el contenido real de esos documentos. 5 inconsistencias editoriales menores corregidas (3 referencias residuales a "zona de foco" tras el renombre a "Zona de acción" en Capítulo 3; 1 referencia obsoleta a "futuro patrón de Catálogo"; 1 cita mal atribuida — "la IA se ve, no se anuncia" corresponde al MDL Capítulo 1, no al Capítulo 6). Sin observaciones de fondo. Aprobado por el usuario — congelado como v1.0. |
| 1.0 | 2026-08-08 | Claude | **Capítulo 6 (CRM/Pipeline) — herencia de la atribución de campaña, 3 ediciones mínimas.** Resuelve la Brecha A identificada durante el Gap Analysis del recorrido #5 de Product Design (Campaña → Lead atribuido → Pipeline): MPA §4 y §6 ya declaraban la relación Campañas → CRM/Pipeline con atribución persistente, pero este capítulo no la reflejaba. (1) §2 Trazabilidad — se agrega la relación con Campañas (MPA §4) a la lista ya existente de relaciones declaradas (Conversaciones, Catálogo, Equipo). (2) §8 Relación con otros patrones — se declara a Campañas como fuente entrante de atribución, corrigiendo la asimetría con el Capítulo 7.B §8 (que ya declaraba alimentar a este patrón, sin que este lo recibiera de vuelta). (3) §3 Composición, Vista de detalle — se agrega la atribución de origen como dato presente, no opcional: MPA §3 exige que permanezca "visible en todo el ciclo de vida posterior del lead", por lo que este capítulo declara únicamente que el dato debe estar presente y visible — dónde se ubica, cómo se presenta y su comportamiento sin atribución quedan explícitamente diferidos a Product Design (Screen Contract en adelante). No se modificó ningún otro capítulo, ni MPX, ni MPA, ni AI Architecture, ni SCR-03 ni ningún artefacto de Product Design. Con esto, la Brecha A queda **RESUELTA** — junto con la Brecha B (resuelta el mismo día en MPA y AI Architecture), el bloqueo de corpus del recorrido #5 queda levantado. |
| 1.0 | 2026-08-10 | Claude | **Capítulo 8 (Notificaciones) agregado — patrón nuevo.** Redactado tras un ciclo de Gate 1 (recuperación de evidencia: MPA §3/4/6/9, MPX Capítulo 7, Capítulo 1 de este documento, código real de `agent/dashboard.py` y `agent/notificaciones.py`) y Gate 2 (reconciliación de contradicciones/vacíos entre esas fuentes) previos a la redacción, seguidos de cuatro decisiones de producto aprobadas explícitamente por el usuario (DEC-01 canal, DEC-02 eventos del Badge, DEC-03 estados, DEC-04 clasificación de `agent/notificaciones.py`) — detalle completo del proceso en `MAIEK_AI_EXPERIENCE_FLOWS.md`. Cambio de numeración documental asociado, no de producto: el antiguo Capítulo 8 ("Principios Transversales de Producto") pasa a ser Capítulo 9 sin alteración de su contenido conceptual — solo se actualizaron sus referencias internas a "Capítulos 1 a 7" → "Capítulos 1 a 8" y dos referencias cruzadas residuales en Capítulo 6 y Capítulo 7 que apuntaban al antiguo número, más el bloque de cierre del documento. Sin observaciones de fondo. |

---

# Capítulo 0 — Propósito y cómo leer este documento

## Qué es este documento

`MAIEK_AI_DESIGN_SYSTEM.md` (MDL) define el lenguaje visual. `MAIEK_AI_COMPONENT_SYSTEM.md`
(CDS) cataloga las piezas sueltas construidas con ese lenguaje. `MAIEK_AI_PRODUCT_EXPERIENCE.md`
(MPX) define cómo se comporta el producto. Ninguno de los tres muestra una pantalla completa,
ensamblada, funcionando como un todo — y esa ausencia es, según la auditoría documental que
precede a este documento, la principal deuda real del proyecto (no de arquitectura, de
materialización).

Este documento existe para cerrar exactamente esa brecha: **composiciones completas y
canónicas** de las pantallas y patrones recurrentes de Maiek AI, construidas ensamblando
componentes ya catalogados en el CDS, bajo las reglas ya definidas en el MPX, usando solo
tokens ya definidos en el MDL.

## Qué es un "patrón" acá, a diferencia de un "componente" en el CDS

Un componente del CDS (Button, Card, Sidebar) es una pieza atómica o casi atómica, reutilizable
en muchos contextos distintos, documentada en abstracto. Un **patrón** de este documento es una
**composición completa con propósito propio** — varios componentes organizados juntos para
resolver una tarea real de principio a fin (la bandeja de conversaciones, el dashboard de un
supervisor, el shell de navegación completo). Un patrón cita los componentes que usa; nunca
inventa uno nuevo. Si un patrón necesita algo que el CDS no tiene, eso es una solicitud de
extensión al CDS — nunca una improvisación dentro de este documento.

## Cuatro principios de diseño que gobiernan todo el documento

Fijados explícitamente por el usuario antes y durante la redacción — rigen cada patrón, sin
excepción, desde el primero:

**1. Cada patrón es una implementación canónica, no un ejemplo ni un mockup.** No se documenta
acá "una forma posible" de resolver algo — se documenta *la* forma oficial. A partir de la
aprobación de cada patrón, cualquier implementación futura del frontend de Maiek AI debe
tomarlo como referencia obligatoria, de la misma manera que ya nadie puede inventar un botón
fuera de la especificación del CDS. Esto tiene una consecuencia editorial directa: cada patrón
se redacta con el mismo nivel de precisión y decisión que un componente del CDS — no hay
espacio para "podría ser así o asá" dentro de una entrada ya aprobada.

**2. Cada patrón lleva trazabilidad explícita y completa al resto del corpus.** Ninguna entrada
de este documento queda sin declarar, de forma explícita:
- qué módulo de la MPA materializa;
- qué componentes del CDS utiliza;
- qué principios del MDL aplica (tokens específicos, no solo "usa el sistema de color");
- qué reglas de comportamiento del MPX implementa (capítulo y regla concreta, no una referencia
  genérica).

Esta trazabilidad no es decorativa: es lo que permite que, si alguna vez un patrón parece
contradecir otro documento, se pueda verificar en segundos contra qué fuente exacta se
contradice — mismo principio de "nunca contradice sin ADR" que rige el resto del corpus desde
el Implementation Roadmap.

**3. Cálidda es la primera implementación de Maiek AI, no al revés (Plataforma primero).** Ante
cualquier diferencia entre una necesidad específica de una implementación (como Cálidda) y un
patrón reutilizable de plataforma, el patrón se diseña primero desde la perspectiva de Maiek AI
como producto SaaS — nunca desde la necesidad puntual de un cliente. Esa necesidad específica se
resuelve mediante configuración, permisos, parametrización o especialización del mismo patrón —
**nunca modificando el patrón base, y nunca creando un patrón distinto para ese cliente**. Aplica
el mismo criterio ya fijado en `MAIEK_AI_FRAMEWORK.md` ("evitar soluciones únicas para un solo
cliente cuando puedan ser capacidades reutilizables") y en MPA §14 ("si es exclusivo de un
cliente, es una capacidad de Nivel 2 o 3, no un módulo de plataforma"), llevado al momento
concreto de diseñar un patrón: si una necesidad no puede resolverse ajustando el patrón existente
por rol, configuración o alcance, la pregunta correcta no es "¿cómo lo hacemos para este
cliente?", es "¿qué parámetro o variación le falta a este patrón para servir a cualquier
negocio?".

**4. Un patrón es su definición canónica, no la evidencia que la motivó.** Referencias al código
actual, a bugs ya corregidos o a estados existentes del sistema pueden usarse, en la
conversación de diseño, para justificar por qué se tomó una decisión — pero **nunca se
convierten en parte de la definición del patrón en sí**. Un patrón debe seguir siendo válido y
completo aunque la implementación actual cambie por completo: describe el comportamiento
canónico esperado del producto, no una fotografía del código de hoy. Consecuencia editorial
directa: ninguna sección de "Estados", "Responsive" o "Errores comunes" de un patrón se apoya en
frases como "ya construido en producción" o "bug ya corregido" para justificarse — si una regla
es correcta, tiene que poder sostenerse por su propia lógica (qué principio del MDL/MPX aplica,
qué problema real evita), sin necesitar el estado actual del código como muleta.

## Estructura fija de cada entrada de patrón

Para que la lectura sea predecible entre capítulos (mismo criterio de consistencia que ya exige
el CDS de sí mismo), toda entrada de patrón de este documento sigue el mismo orden de secciones:

1. **Objetivo** — qué tarea completa resuelve, en una frase.
2. **Trazabilidad** — módulo de MPA, componentes de CDS, tokens de MDL, reglas de MPX.
3. **Composición** — cómo se organizan los componentes entre sí (jerarquía, regiones, layout).
4. **Roles y variaciones** — quién lo ve y qué cambia según el rol (MPA, tabla de permisos).
5. **Estados de la composición completa** — vacío / cargando / con datos / error, a nivel de la
   pantalla entera, no de un componente aislado.
6. **Comportamiento aplicado del MPX** — reglas de interacción, voz o protocolo de IA
   específicas de este patrón.
7. **Responsive** — cómo se reorganiza la composición completa en mobile/tablet.
8. **Relación con otros patrones** — qué patrón lo precede o sucede en el flujo real de trabajo.
9. **Errores comunes** — qué NO hacer al implementar este patrón.

## Cómo se relaciona con el resto del corpus

- **Framework**: la voz y personalidad de marca gobiernan cualquier texto de ejemplo dentro de
  un patrón (microcopy real, nunca genérico) — este documento no la redefine.
- **MPA**: cada patrón instancia uno o más módulos ya definidos; este documento nunca declara un
  módulo funcional nuevo — si un patrón pareciera necesitar uno, es señal de que la conversación
  pertenece a la MPA, no acá.
- **MDL**: fuente única de todo valor visual usado en una composición — ningún patrón introduce
  un color, espaciado, radio o timing fuera de las escalas ya definidas.
- **CDS**: fuente única de las piezas que se ensamblan — ningún patrón redefine el
  comportamiento de un componente ya catalogado, solo lo compone.
- **MPX**: fuente única de las reglas de comportamiento, voz e interacción con IA que un patrón
  debe cumplir — este documento nunca inventa una regla de comportamiento nueva.
- **`MAIEK_AI_FRONTEND_ARCHITECTURE.md`**: documento hermano (mismo nivel de la jerarquía), no
  subordinado ni superior. Este documento respeta sin redefinir las decisiones ya `Activas` de
  Frontend Architecture sobre organización general de la interfaz (envoltura única, navegación
  por fragmento, ocultar-no-vaciar) — las cita como restricción de composición, no las repite en
  detalle.

---

# Capítulo 1 — Patrón: Shell de Navegación

## 1. Objetivo

El armazón persistente que envuelve toda la aplicación autenticada — responde, en todo
momento y sin que el usuario tenga que pensarlo, "¿en qué parte de Maiek estoy, qué rol tengo, y
a dónde más puedo ir?". Es el primer patrón de este documento porque todos los demás patrones
viven *dentro* de él — ningún otro patrón se diseña sin asumir que este ya existe alrededor.

## 2. Trazabilidad

- **MPA**: no instancia un módulo de negocio propio — es la infraestructura que expone la
  **Navegación principal** ya definida en MPA §10 (Inicio, Conversaciones, CRM/Pipeline,
  Campañas, Catálogo, Equipo, Analítica, Configuración) y respeta la tabla de **Permisos de
  alto nivel** de MPA §9 para decidir qué ítems muestra a cada rol.
- **CDS**: `Top Navigation`, `Sidebar`, `Avatar`, `Badge`, `Icon Button`, `Menús` (menú de
  perfil, disparado desde el Avatar).
- **MDL**: sistema de color completo (Capítulo 4 — identidad, semántica, superficie, incluido
  dark mode), tipografía Inter para todo el shell (Capítulo 5), elevación 0 para el shell en
  reposo y elevación 2 para cualquier panel flotante que dispare (Capítulo 3), motion tokens
  `motion-instant` y `motion-fast` para hover/toggle (Capítulo 7), grid de 8px para todo
  espaciado interno (Capítulo 3).
- **MPX**: **Consistencia entre pantallas** (Capítulo 1) — el shell nunca varía su estructura
  entre módulos, solo el contenido montado dentro; **Jerarquía visual: notificación de sistema
  vs. sugerencia de IA** (Capítulo 7) — gobierna cómo se distingue un badge de notificación
  operativa de una señal relacionada con IA, si ambas conviven en el shell.

## 3. Composición

Tres regiones fijas, en este orden de jerarquía visual (Top Navigation por encima de todo,
Sidebar y contenido comparten el nivel siguiente):

**Top Navigation** (`Top Navigation` del CDS) — franja superior, altura fija, siempre visible.
Contiene, de izquierda a derecha: wordmark de marca (`space-4` de margen izquierdo), y a la
derecha (máximo 4 elementos interactivos, por regla del propio componente): buscador global
(`Cmd/Ctrl+K`), notificaciones (`Icon Button` con `Badge` de contador), ayuda, y `Avatar` del
usuario actual (dispara `Menús` de perfil al hacer clic — incluye nombre, rol, y la acción de
cerrar sesión).

**Sidebar** (`Sidebar` del CDS) — rail izquierdo, `280px` expandido / `64px` colapsado
(breakpoints `md` e inferiores). Cada ítem de la Navegación principal de MPA §10 se renderiza
como un ítem de `Sidebar`, con `Badge` de conteo donde corresponda (ej. conversaciones sin
leer). El ítem correspondiente a la sección activa usa el estado `activo` ya definido en el CDS
(fondo `primary-50`/`primary-900`, texto `primary-600`/`400`).

**Punto de montaje de contenido** — el área restante, donde cada patrón de los capítulos
siguientes de este documento se renderiza. Esta región es la única que cambia entre módulos; el
Shell nunca se reconstruye al navegar entre ellos — principio ya `Activo` de
`MAIEK_AI_FRONTEND_ARCHITECTURE.md` §1 (envoltura única, punto de montaje central), que este
patrón hereda sin redefinir.

## 4. Roles y variaciones

Aplicando la tabla de permisos de MPA §9 y el principio **ocultar, no vaciar** ya `Activo` en
`MAIEK_AI_FRONTEND_ARCHITECTURE.md` §3 — con una distinción explícita que la versión anterior de
esta tabla no aplicaba de forma consistente: **capacidad (el patrón existe para ese rol) es
distinto de alcance (cuánto de ese patrón ve o puede hacer ese rol)**. Un patrón solo se oculta
del Sidebar cuando MPA §9 dice literalmente "Sin acceso" — no cuando dice un acceso acotado
("Solo sus leads", "Solo su propia disponibilidad"), que en cambio implica un mismo patrón
reutilizable con un alcance distinto (detalle de esa variación de alcance, en el capítulo
correspondiente a cada patrón — Cap. 6 para CRM/Pipeline y Equipo):

| Ítem del Sidebar | Administrador | Supervisor | Vendedor/Asesor |
|---|---|---|---|
| Inicio | Visible | Visible | Visible |
| Conversaciones | Visible | Visible (equipo) | Visible (alcance: solo las propias) |
| CRM / Pipeline | Visible (alcance: total) | Visible (alcance: total + reasignación) | Visible (alcance: solo sus leads, sin capacidades administrativas) |
| Campañas | Visible | Visible (alcance: solo lectura) | **Oculto** (MPA §9: Sin acceso) |
| Catálogo | Visible | Visible | Visible |
| Equipo | Visible (alcance: alta/edición/permisos) | Visible (alcance: solo lectura de carga/disponibilidad del equipo) | Visible (alcance: solo su propia disponibilidad) |
| Analítica | Visible (alcance: global, configuración, KPIs y reportes completos) | Visible (alcance: equipo y comparativos, sin capacidades de administración) | Visible (alcance: exclusivamente personal — sus propios indicadores, actividades y desempeño, sin ver información de otros usuarios ni capacidades de configuración) |
| Configuración | Visible | **Oculto** (MPA §9: Sin acceso) | **Oculto** (MPA §9: Sin acceso) |

Ítems verdaderamente ocultos por rol no se muestran deshabilitados o en gris — directamente no
existen en el DOM para ese rol, consistente con "ocultar, no vaciar". Esa regla se reserva ahora,
correctamente, solo para los casos de "Sin acceso" real (Campañas y Configuración para Asesor,
Configuración para Supervisor) — nunca para un acceso acotado, que sigue siendo el mismo patrón
con un alcance distinto, no su ausencia.

**Criterio confirmado por el usuario, aplicado de forma consistente en todo este documento**:
primero se define la capacidad del producto, después se restringe su alcance mediante permisos y
contexto — nunca se elimina una capacidad completa para un rol cuando existe una variación de
alcance razonable. Analítica queda resuelta con el mismo criterio que CRM/Pipeline y Equipo — el
detalle de qué ve exactamente cada alcance (qué indicadores, qué comparativos) se especifica en
el capítulo dedicado a Analítica.

## 5. Estados de la composición completa

- **Reposo** — shell completo, Sidebar en el estado (expandido/colapsado) que el usuario dejó en
  su sesión anterior, persistido entre sesiones.
- **Colapsando/expandiendo** — transición `motion-fast` (150ms) del ancho del Sidebar; el
  contenido del punto de montaje se reacomoda sin recargarse.
- **Con notificación nueva** — el `Badge` de la campana en Top Navigation actualiza su conteo en
  tiempo real (mismo mecanismo ya activo de indicadores en vivo del panel); no dispara ningún
  sonido ni animación más allá del cambio de número, consistente con "tranquilidad, nunca
  ansiedad" (MDL Capítulo 0).
- **Sesión expirando** — no es un estado visual del Shell en sí; se resuelve en el patrón de
  Autenticación (fuera del alcance del Capítulo 1, pendiente en un capítulo futuro), citado acá
  solo para dejar constancia de que el Shell no es responsable de esa señal.

## 6. Comportamiento aplicado del MPX

- El Shell nunca desaparece ni se reconstruye al navegar — aplica **Consistencia entre
  pantallas** (MPX Capítulo 1) de forma literal: el usuario nunca pierde su orientación espacial
  al moverse entre módulos.
- El buscador global (`Cmd/Ctrl+K`) es una **divulgación progresiva** (MPX Capítulo 1): no ocupa
  espacio permanente en pantallas angostas, aparece bajo demanda.
- Si en el futuro conviven, en la campana de notificaciones, una alerta operativa (ej. un
  incidente) y una sugerencia generada por IA, deben distinguirse visualmente entre sí — regla
  directa de MPX Capítulo 7, "Jerarquía visual: notificación de sistema vs. sugerencia de IA".
  Hoy el Shell no tiene todavía ninguna señal de IA real que mostrar (`MAIEK_AI_FRONTEND_ARCHITECTURE.md`
  §8-9 ya establecen que esa representación queda pendiente de que el dato exista) — esta regla
  queda declarada acá como principio a cumplir cuando corresponda, no como algo implementado hoy.

## 7. Responsive

Por debajo del breakpoint `sm`, el Sidebar deja de convivir con el contenido — se convierte en
overlay a pantalla completa, activado por un ícono en la Top Navigation (nunca se comprime a un
ancho intermedio ilegible, regla ya fijada por el propio componente `Sidebar` del CDS). La Top
Navigation en mobile colapsa a: wordmark + acceso a perfil + ícono de menú; el buscador se mueve
detrás de un ícono (mismo patrón ya definido en el CDS para `Top Navigation` y `Search Box` en
mobile).

## 8. Relación con otros patrones

Es el patrón contenedor de todos los demás — cada capítulo siguiente de este documento (Bandeja/
Chat, Dashboard, Copiloto IA, CRM/Pipeline, etc.) describe qué se monta *dentro* del punto de
montaje de este Shell, nunca una estructura de página independiente.

## 9. Errores comunes

- Reconstruir el Shell completo (o parpadear la Top Navigation/Sidebar) al navegar entre
  módulos — rompe directamente "Consistencia entre pantallas" del MPX y el principio ya
  `Activo` de envoltura única de Frontend Architecture.
- Agregar accesos de producto sueltos a la Top Navigation (ej. un botón de una función
  específica de un módulo) — la Top Navigation es identidad + accesos transversales de cuenta,
  nunca navegación de producto (regla ya fijada por el propio componente `Top Navigation` del
  CDS).
- Mostrar un ítem del Sidebar deshabilitado en gris para un rol sin permiso, en vez de
  ocultarlo directamente — contradice el principio "ocultar, no vaciar" ya `Activo`.

---

# Capítulo 2 — Patrón: Bandeja de Conversaciones

## 1. Objetivo

El espacio central de trabajo de Maiek AI — donde una conversación real se convierte en una
oportunidad de negocio. Es el patrón de mayor frecuencia de uso diario de toda la plataforma y,
para el rol Asesor, la pantalla de aterrizaje por defecto (MPA §10: "Inicio — resumen ejecutivo o
bandeja operativa, según el rol").

## 2. Trazabilidad

- **MPA**: instancia el módulo **Conversaciones** (MPA §3) como núcleo, en relación bidireccional
  constante con **Agentes IA** (MPA §4: "cada mensaje nuevo pasa por la IA... cada respuesta de la
  IA vuelve a Conversaciones"), y alimenta a **CRM/Pipeline** (MPA §4: "una conversación con
  intención de negocio real se convierte en un lead").
- **CDS**: `Chat`, `Message Bubble`, `Typing Indicator`, `Attachment`, `Quick Actions`, `Avatar`,
  `Badge`, `Search Box`, `AI Summary`, `Text Area` (campo de respuesta), `Empty State`, `Skeleton`.
- **MDL**: sistema de color para distinguir remitente (Capítulo 4 — cliente/Gabi/asesor, tres
  tratamientos visuales distintos, nunca solo texto), densidad **cómoda** (`space-4`–`space-5`,
  Capítulo 3 — es una vista de trabajo diario, no una tabla densa), motion tokens `motion-fast`
  para microinteracciones de mensaje nuevo y `ease-out-expo` para su entrada (Capítulo 7).
- **MPX**: **Optimismo del sistema, no del usuario** (Capítulo 1 — un mensaje propio aparece de
  inmediato con estado "enviando", nunca esperando confirmación del servidor para mostrarse);
  **Protocolo de interacción con IA**, niveles de intervención y **protocolo de entrega a un
  humano** (Capítulo 2); **Cuándo usar skeleton, spinner o progress bar** (Capítulo 5); **Voz de
  la IA según el contexto** (Capítulo 2, gobierna el contenido real de los mensajes de Gabi
  dentro de este patrón).

## 3. Composición

**Vista completa** (variante por defecto al entrar al módulo) — tres columnas dentro del punto de
montaje del Shell (Capítulo 1): rail de estados heredado del Shell a la izquierda, **lista de
conversaciones** al centro (con `Search Box` en el encabezado — alcance de la búsqueda siempre
explícito en el placeholder, nunca ambiguo respecto al filtro activo) y **panel de chat** a la
derecha, con la conversación más reciente o más urgente ya abierta por defecto — nunca una
bandeja vacía a la espera de que el usuario elija.

El panel de chat se compone de: encabezado (`Avatar` + nombre + teléfono + `AI Summary` cuando la
conversación tiene historial extenso), área de mensajes (`Message Bubble` en orden cronológico,
con `Typing Indicator` cuando corresponde), y zona de respuesta (`Text Area` con auto-expansión +
`Quick Actions` + acción de adjuntar).

**Vista de detalle** (variante dentro de otra pantalla, ej. dentro de un futuro patrón de detalle
de cliente) — el mismo `Chat`, sin la columna de lista, con más contexto alrededor. No es un
componente distinto, es el mismo patrón con una columna menos.

## 4. Roles y variaciones

| | Administrador | Supervisor | Vendedor/Asesor |
|---|---|---|---|
| Alcance de la bandeja | Todas las conversaciones | Todas las del equipo | Solo las propias (MPA §9) |
| Capacidad de responder | Sí, cualquier conversación | Sí, cualquier conversación de su equipo | Sí, solo las propias |
| Copiloto IA sobre la conversación | Sí | Sí | Sí, sobre sus propias conversaciones |

Mismo criterio ya fijado en el Capítulo 1: la capacidad (tener una Bandeja de Conversaciones)
existe para los tres roles sin excepción — lo único que cambia es el alcance de qué conversaciones
entran en ella.

## 5. Estados de la composición completa

- **Vacío** — sin conversaciones asignadas. Usa `Empty State`, nunca un genérico "no hay datos":
  variante "primer uso" (explica el mecanismo de asignación) cuando el rol simplemente no tiene
  actividad todavía, distinta de la variante "sin resultados de filtro" cuando sí hay
  conversaciones pero el filtro activo no las muestra — mismas dos variantes ya definidas por el
  componente `Empty State` del CDS, nunca el mismo mensaje genérico para ambos casos.
- **Cargando** — `Skeleton` con la misma cantidad de filas esperada en la lista, y `Skeleton` del
  panel de chat con la geometría de `Message Bubble`.
- **Con datos** — estado normal descrito en la sección 3.
- **Mensaje nuevo mientras el usuario lee historial** — si el usuario había subido a leer mensajes
  anteriores, un mensaje nuevo no lo arrastra de vuelta al final automáticamente; aparece un
  indicador discreto de "nuevo mensaje" en su lugar (ya construido en el CDS como comportamiento
  esperado del componente `Chat`).
- **Error de envío** — el mensaje fallido permanece visible con opción de reintento inline, nunca
  desaparece en silencio.

## 6. Comportamiento aplicado del MPX

- El mensaje propio se muestra de inmediato en estado "enviando" antes de la confirmación del
  servidor — aplicación directa de **Optimismo del sistema, no del usuario** (MPX Capítulo 1).
- La IA (Gabi) responde según el **Protocolo de interacción con IA** (MPX Capítulo 2): interviene
  cuando puede resolver la consulta, deriva a un asesor humano siguiendo el **protocolo de
  entrega** definido ahí — este patrón no decide esa lógica, solo la representa visualmente
  (`Message Bubble` con tratamiento distinto para Gabi vs. asesor humano).
- El indicador de "escribiendo…" respeta el **vocabulario visual de estados** ya fijado en MPX
  Capítulo 5 — se autolimpia con timeout, nunca queda visible indefinidamente si se pierde la
  señal en tiempo real.
- El contenido de los mensajes de Gabi sigue la **voz de la IA según el contexto** (MPX Capítulo
  2) — nunca jerga técnica de sistema hacia el cliente, mismo principio ya fijado en
  `MAIEK_AI_DESIGN_SYSTEM.md` Capítulo 2 ("cómo habla").

## 7. Responsive

Por debajo del breakpoint `sm`, la vista completa deja de mostrar las tres columnas a la vez: rail
y lista de conversaciones se ocultan, y la conversación abierta ocupa la pantalla completa —
aplicación directa del criterio ya fijado por el componente `Chat` del CDS ("en mobile, pantalla
completa dedicada al chat"). Volver a la lista es una acción explícita (botón de retroceso), nunca
un gesto implícito sin affordance visible.

## 8. Relación con otros patrones

Vive dentro del punto de montaje del Shell (Capítulo 1). Es también el destino natural al que
lleva un ítem de la Zona de acción del patrón de Inicio (Capítulo 3) para el rol Asesor —
Inicio muestra un adelanto priorizado, este patrón es la bandeja completa. Alimenta al patrón
de CRM/Pipeline (Capítulo 6) cuando una conversación genera o actualiza un lead. Comparte
el componente `AI Summary` con el patrón de Copiloto IA (Capítulo 5) — mismo componente,
dos contextos de uso.

## 9. Errores comunes

- Recargar la conversación completa ante cada mensaje nuevo en vez de solo agregar el mensaje
  entrante — rompe el optimismo del sistema (sección 6) y descarta sin necesidad el trabajo de
  renderizado ya hecho; el comportamiento correcto es agregar únicamente el mensaje nuevo al final
  de la lista ya renderizada.
- Perder la distinción visual entre remitente humano (asesor) y remitente IA (Gabi) cuando ambos
  comparten alineación de burbuja — viola un principio de marca explícito ("la IA se ve, no se
  anuncia", MDL Capítulo 1), no es un detalle menor de estilo.
- Forzar el scroll al final del chat cuando el usuario está leyendo historial arriba — interrumpe
  una tarea en curso, contra el principio "la IA nunca interrumpe" y el criterio general de calma
  del MDL Capítulo 0.

---

# Capítulo 3 — Patrón: Inicio

## 1. Objetivo

La primera pantalla que ve cualquier usuario autenticado, sin excepción de rol — responde de
inmediato "¿qué necesito saber y hacer hoy?", con un enfoque que se adapta al contexto y las
responsabilidades de cada rol. Un único patrón para los tres roles: lo que varía es el contenido
que compone cada zona, nunca la existencia de la pantalla en sí ni su estructura general.

**Inicio es una pantalla orientada a la acción, no a la observación.** Su objetivo principal no
es mostrar indicadores — es ayudar al usuario a comprender su contexto, priorizar su trabajo y
ejecutar la siguiente mejor acción. Indicadores, alertas y resúmenes existen únicamente en la
medida en que facilitan esa decisión; nunca son el elemento principal de la composición. La
analítica de profundidad pertenece exclusivamente al patrón de Analítica (Capítulo 4) — si Inicio
empieza a acumular detalle exploratorio, deja de cumplir su objetivo.

## 2. Trazabilidad

- **MPA**: instancia la **Navegación principal** §10, ítem 1 ("Inicio"). MPA §10 describe este
  ítem como "resumen ejecutivo o bandeja operativa, según el rol" — una descripción a nivel de
  navegación, no de pantalla (MPA declara explícitamente que "no diseña pantallas"). Este patrón
  resuelve esa descripción de forma más precisa: un único patrón de Inicio para todos los roles,
  cuyo *contenido* se inclina hacia lo ejecutivo o lo operativo según el rol — no una bifurcación
  entre "pantalla de resumen" y "la bandeja de conversaciones directamente". Esta es una
  especialización a nivel de pantalla, permitida porque MPA no fija ese detalle; no una
  contradicción de MPA.
- **MDL**: el Capítulo 0 ya narra, palabra por palabra, ambos modos de este patrón antes de que
  este documento existiera — "Un día completo con Maiek": *"Mañana. El vendedor abre el panel. No
  ve una tabla — ve, de un vistazo, a quién debería llamar primero y por qué"* (modo operativo,
  Asesor) y *"Mediodía. El supervisor abre su vista. No revisa conversación por conversación — ve
  el pulso del equipo en números grandes y claros, y la IA le señala la única cosa que necesita
  su atención hoy"* (modo ejecutivo, Supervisor/Administrador). Este patrón es la materialización
  compositiva de ese texto, no una idea nueva.
- **CDS**: `KPI Card`, `AI Suggestion Card`, `AI Insight`, `Card`, `Avatar`, `Badge`, `Skeleton`.
- **MPX**: **Decision Experience** completo (Capítulo 3) — priorización, reducción de carga
  cognitiva, presentación orientada a decisión, Explainability First, Confianza; **divulgación
  progresiva** (Capítulo 1) para cualquier detalle que no sea parte del resumen inicial.

## 3. Composición

Dos zonas fijas, presentes para los tres roles, en un **orden de prioridad deliberado — acción
antes que observación** — lo que cambia entre roles es qué compone cada una, nunca su existencia
ni su jerarquía relativa:

**Zona de acción** (primera, la más prominente de la pantalla) — combina la sugerencia de mayor
valor del momento (`AI Suggestion Card`, cuando exista una que supere el umbral de confianza de
MPX Capítulo 3) con el foco específico de cada rol:
- Asesor: lista priorizada de sus propias conversaciones y oportunidades que requieren atención
  ahora — cada ítem (`Avatar` + nombre + motivo breve de por qué requiere atención) lleva directo
  a esa conversación específica dentro del patrón de Bandeja de Conversaciones (Capítulo 2). Es
  un adelanto priorizado — nunca la lista exhaustiva ni el chat abierto, que viven solo en
  Capítulo 2.
- Administrador/Supervisor: **la única cosa que necesita su atención hoy**, no un resumen pasivo
  del equipo — ej. una campaña bajando de rendimiento, un cliente de alto valor sin respuesta
  hace horas (misma señal ya narrada en el MDL, Capítulo 0). Cada señal lleva directo al patrón
  de Analítica (Capítulo 4) o al lugar exacto donde se resuelve, nunca a un resumen genérico de
  "cómo va el equipo".

Ausente por completo, sin dejar un espacio vacío, cuando no hay ninguna señal que supere el
umbral de confianza — silencio de la sección, no una sección vacía (mismo criterio del Capítulo
0 de este documento).

**Zona de indicadores** (segunda, de apoyo — nunca la protagonista) — franja compacta de `KPI
Card` (nunca más de 8, regla ya fijada por el propio componente), exclusivamente como contexto
que respalda las decisiones ya priorizadas en la Zona de acción. Para Administrador/Supervisor:
indicadores ejecutivos (ej. conversaciones activas, leads en curso, tendencia). Para Asesor:
indicadores personales (ej. sus conversaciones activas hoy, sus leads asignados). Esta zona
responde "¿cómo estoy?" en apoyo de lo que la Zona de acción ya respondió sobre "¿qué hago
ahora?" — nunca al revés.

## 4. Roles y variaciones

| Zona | Administrador | Supervisor | Vendedor/Asesor |
|---|---|---|---|
| Zona de acción (primera, prominente) | Qué necesita su intervención hoy, alcance global — remite a Analítica o al punto exacto de resolución | Qué necesita su intervención hoy, alcance de equipo — remite a Analítica o al punto exacto de resolución | Conversaciones/oportunidades propias que requieren atención — remite a Bandeja |
| Zona de indicadores (segunda, de apoyo) | KPIs ejecutivos, alcance global | KPIs ejecutivos, alcance de equipo | KPIs personales |

Mismo criterio ya establecido en los capítulos anteriores: la pantalla existe, con su misma
estructura y el mismo orden de prioridad, para los tres roles — el contenido de cada zona es lo
único que cambia.

## 5. Estados de la composición completa

- **Vacío (usuario o cuenta nueva, sin actividad todavía)** — cada zona usa su propio `Empty
  State` explicando el mecanismo (ej. la Zona de acción de un Asesor recién asignado explica que
  ahí aparecerán sus conversaciones en cuanto se le asigne la primera), nunca una pantalla vacía
  genérica.
- **Cargando** — `Skeleton` con la geometría exacta de cada zona.
- **Con datos, sin ninguna señal que supere el umbral de confianza** — la Zona de acción no se
  renderiza (ver sección 3); la Zona de indicadores se muestra igual, ya que no depende de esa
  señal.

## 6. Comportamiento aplicado del MPX

- Cada señal de la Zona de acción responde por qué / por qué ahora / por qué yo — Explainability
  First (MPX Capítulo 3); si no puede, no se muestra.
- El orden de los ítems dentro de la Zona de acción (para cualquier rol) sigue **Priorización** y
  **Reducción de carga cognitiva** (MPX Capítulo 3) — nunca cronológico ni alfabético por
  defecto, responde a qué necesita atención primero.
- Ningún elemento de esta pantalla se actualiza con una animación que reclame atención activa —
  coherente con "tranquilidad, nunca ansiedad" (MDL Capítulo 0).

## 7. Responsive

Las dos zonas se apilan verticalmente en mobile, **manteniendo el mismo orden de prioridad que en
desktop — Zona de acción primero, Zona de indicadores después** (comprimida a 2 columnas, regla
ya fijada por `KPI Card`). El orden nunca se invierte entre breakpoints; invertirlo pondría la
observación por encima de la acción exactamente en el contexto — mobile, uso interrumpido, de pie
— donde priorizar la acción importa más, no menos.

## 8. Relación con otros patrones

Vive dentro del punto de montaje del Shell (Capítulo 1) y es, para los tres roles, el primer
patrón que se monta ahí tras el login — ningún rol aterriza directamente en otro patrón. Para
Asesor, es el paso previo obligatorio hacia la Bandeja de Conversaciones (Capítulo 2): la Zona de
acción lleva a una conversación específica dentro de ese patrón, nunca reemplaza su lista
completa. Para Administrador/Supervisor, la Zona de acción remite al patrón de Analítica
(Capítulo 4) o al punto exacto de resolución — Inicio señala qué requiere atención, Analítica es
el destino de profundidad para explorarlo.

## 9. Errores comunes

- Hacer que cualquier rol aterrice directamente en otro patrón (Bandeja, Analítica) sin pasar por
  Inicio — contradice la decisión de producto de esta versión: Inicio es siempre el primer paso.
- Que la Zona de acción del Asesor muestre la lista completa de conversaciones en vez de un
  adelanto priorizado — duplicaría el patrón de Bandeja de Conversaciones dentro de Inicio, en
  vez de remitir a él.
- Que la Zona de acción de Administrador/Supervisor se convierta en un resumen pasivo de
  indicadores de equipo en vez de señalar qué requiere intervención — repetiría el propósito de
  la Zona de indicadores y perdería la orientación a la acción que define este patrón.
- **Anteponer la Zona de indicadores a la Zona de acción, en cualquier breakpoint** — invierte el
  principio central de este patrón (acción antes que observación) y contradice directamente la
  narrativa del MDL Capítulo 0 que lo fundamenta.
- Dejar crecer la Zona de indicadores más allá de una franja compacta de apoyo — cualquier
  necesidad de explorar tendencias o comparativos pertenece al patrón de Analítica (Capítulo 4),
  nunca a Inicio.

---

# Capítulo 4 — Patrón: Analítica

## 1. Objetivo

El destino de profundidad para explorar tendencias, comparativos y desempeño con el detalle que
el resumen de Inicio (Capítulo 3) deliberadamente no muestra — accesible desde el ítem
"Analítica" del Sidebar (Capítulo 1).

## 2. Trazabilidad

- **MPA**: instancia el módulo **Analítica** (MPA §3, §6 — "embudo de conversión, métricas por
  asesor/canal/campaña, tendencias en el tiempo"). Consume, en el sentido de solo lectura ya
  declarado en MPA §12, datos de Conversaciones, CRM/Pipeline, Campañas y Equipo & Organización —
  nunca escribe de vuelta en ellos. Expone también la capacidad exclusiva de IA ya declarada en
  MPA §7: "detectar patrones a través de todo el portafolio de conversaciones a la vez...
  invisible para cualquier persona mirando una conversación a la vez".
- **CDS**: `KPI Card`, `Statistic Card`, `Card`, `AI Suggestion Card`, `AI Insight`, `AI
  Confidence Indicator`, `Badge`, `Skeleton`.
- **MDL**: densidad **cómoda** para la franja de KPIs (Capítulo 3), grid de 12 columnas
  (Capítulo 3), tipografía `text-display`/`text-title-lg` con `tabular-nums` para cifras
  comparables (Capítulo 5), color semántico para deltas (Capítulo 4 — nunca solo color, siempre
  con ícono de dirección).
- **MPX**: **Decision Experience** completo (Capítulo 3) — mismas reglas que Inicio (Explainability
  First, umbral de confianza, priorización), aplicadas acá con más profundidad de detalle.

## 3. Composición

**Franja de KPI Cards** — igual mecanismo que en Inicio, pero con más tarjetas y mayor detalle
por tarjeta (hasta 8, regla ya fijada por el componente).

**Zona de siguiente mejor acción** — igual que en Inicio, mismo mecanismo de ausencia cuando no
hay sugerencia que supere el umbral de confianza.

**Zona de detalle comparativo** — la que distingue a este patrón de Inicio: `Statistic Card`
agrupadas por dimensión relevante al rol (equipo, canal, campaña, período), con capacidad de
explorar tendencias en el tiempo — el nivel de detalle que Inicio nunca muestra.

**Zona de configuración** (solo Administrador) — qué métricas se muestran y a quién, dentro de
este mismo patrón, no como pantalla separada.

## 4. Roles y variaciones

| | Administrador | Supervisor | Vendedor/Asesor |
|---|---|---|---|
| Alcance de KPIs y comparativos | Global, toda la organización | Su equipo y comparativos entre miembros | Exclusivamente personal |
| Configuración de métricas mostradas | Sí | No | No |
| Visión de otros usuarios | Sí | Solo su equipo | **No** — nunca ve indicadores de otro asesor |

Mismo criterio ya fijado en los capítulos anteriores: la capacidad existe para los tres roles — un
Asesor tiene Analítica propia, exclusivamente personal, nunca oculta (consistente con la fila de
Analítica ya definida en el Capítulo 1, sección 4).

## 5. Estados de la composición completa

- **Vacío (sin actividad suficiente para generar tendencias)** — `Empty State` explicando qué
  generará datos acá.
- **Cargando** — `Skeleton` con la geometría exacta de cada `KPI Card`/`Statistic Card` esperada.
- **Con datos, sin sugerencias de IA disponibles** — zona de siguiente mejor acción ausente (ver
  sección 3 de este capítulo), el resto de la composición completa.
- **Actualizando** — los valores visibles permanecen legibles con una transición suave hacia el
  valor nuevo, nunca un parpadeo a blanco.

## 6. Comportamiento aplicado del MPX

- Cada `AI Suggestion Card` responde por qué / por qué ahora / por qué yo — Explainability First
  (MPX Capítulo 3); si no puede, no se muestra.
- Una sugerencia por debajo del umbral mínimo de confianza no aparece — nunca se muestra atenuada
  como alternativa a ocultarla.
- La priorización de qué comparativo aparece primero sigue el mismo criterio de **Priorización**
  (MPX Capítulo 3) que en Inicio, no un orden arbitrario.

## 7. Responsive

La franja de KPI Cards pasa a 2 columnas en mobile (regla ya fijada por el componente). La zona
de detalle comparativo se apila verticalmente, un `Statistic Card` a la vez, manteniendo el orden
de prioridad de desktop.

## 8. Relación con otros patrones

Vive dentro del punto de montaje del Shell (Capítulo 1). Es el destino de profundidad al que
remite la Zona de acción de Inicio (Capítulo 3) para Administrador/Supervisor — mismos componentes
base (`KPI Card`, `AI Suggestion Card`) que Inicio, con una zona de detalle comparativo que
Inicio nunca incluye.

## 9. Errores comunes

- Mostrar más de 8 `KPI Card` en la franja superior — deja de ser un resumen de un vistazo (regla
  ya fijada por el propio componente).
- Mezclar densidad cómoda y compacta dentro de la misma vista.
- Que un Asesor pueda, por cualquier ruta de la interfaz, llegar a ver un indicador de desempeño
  de otro asesor — viola directamente el alcance ya fijado en la sección 4.
- Duplicar en este patrón el mismo resumen ya mostrado en Inicio sin agregar el detalle
  comparativo que es la razón de ser de este patrón — si Analítica no ofrece más profundidad que
  Inicio, no cumple su objetivo.

---

# Capítulo 5 — Patrón: Copiloto IA

## 1. Objetivo

El panel contextual que asiste al usuario sobre lo que está trabajando en ese momento — una
conversación, un lead — condensando en un solo lugar lo que la IA puede ofrecer ahí: qué sugiere,
qué resume, qué observa. Es la materialización del límite ya declarado en MPA §7 entre lo que la
IA hace sola y lo que solo asiste, nunca decide.

**El Copiloto no compite con el usuario por el control de la interfaz.** Su función es comprender
el contexto, priorizar opciones, justificar recomendaciones y acelerar decisiones — nunca
reemplazar el flujo de trabajo del usuario ni interrumpirlo innecesariamente. Un Copiloto que se
impone sobre la tarea que el usuario ya está haciendo deja de potenciarla y empieza a competir con
ella, que es exactamente lo que este patrón existe para evitar.

**Human Decision Gate.** Ninguna acción irreversible **o de impacto significativo** se ejecuta
sin una decisión explícita del usuario — este es el principio invariante, distinto del mecanismo
concreto que lo materializa hoy (`Confirm Dialog` del CDS). El criterio no es confirmar toda
acción — eso generaría la misma fricción que `Confirm Dialog` ya advierte evitar en el CDS — es
proteger específicamente las que son irreversibles o de impacto significativo. El mecanismo puede
evolucionar con el producto; el principio, no (consistente con el Principio 4 del Capítulo 0 — un
patrón es su definición canónica, no la implementación de turno).

## 2. Trazabilidad

- **MPA**: instancia la capacidad de **Agentes IA** en su rol de asistencia al equipo interno
  (MPA §3: "asiste al equipo interno (Copiloto)"; MPA §6: "copiloto interno" entre las
  capacidades del módulo). Materializa directamente la distinción de MPA §7 entre capacidades
  **exclusivas de la IA** (ej. leer y resumir una conversación larga en segundos) y capacidades
  **asistidas por IA con decisión humana final** (ej. negociación de precio, cualquier acción
  irreversible) — este patrón nunca ejecuta por sí solo lo segundo.
- **CDS**: `AI Action Panel` (contenedor de más alto nivel de la categoría IA), que a su vez
  compone `AI Suggestion Card`, `AI Recommendation`, `AI Summary`, `AI Insight`, `AI Confidence
  Indicator`, `Statistic Card`.
- **MDL**: ícono de marca sutil (chispa/destello) como única señal de contenido generado por IA
  — principio "la IA se ve, no se anuncia" (Capítulo 1), mecanismo del ícono definido en el
  Capítulo 6 —, elevación 0/1 como panel acoplado al layout (no flotante, ver sección 3), motion
  `motion-instant` para el pulso de "generando" (Capítulo 7).
- **MPX**: **Niveles de intervención** y **Protocolo de incertidumbre** (Capítulo 2 — qué hace la
  IA cuando no sabe algo); **Explainability First** y **Confianza** (Capítulo 3); **Intervención
  humana** (Capítulo 3) — el límite exacto que gobierna cuándo este patrón puede ejecutar una
  acción directamente y cuándo debe pasar por confirmación humana.

## 3. Composición

Panel acoplado al layout junto al patrón que se esté usando (típicamente la Bandeja de
Conversaciones, Capítulo 2), no un overlay flotante — expandido (panel completo) o colapsado
(solo el ícono de marca IA, sin ocupar espacio del área de trabajo principal). Tres zonas, en
orden de prioridad **acción antes que observación** (mismo criterio ya establecido en el
Capítulo 3):

**Zona de sugerencias** (primera) — `AI Suggestion Card` / `AI Recommendation` con la acción de
mayor valor sobre el contexto actual. Ausente por completo cuando ninguna supera el umbral de
confianza (MPX Capítulo 3) — nunca una sección vacía.

**Zona de contexto** (segunda) — `AI Summary` del historial actual y `AI Insight` puntuales (ej.
un patrón detectado en esta conversación). Responde "¿qué necesito entender de esto?", en apoyo
de la decisión que la Zona de sugerencias ya planteó.

**Zona de métricas de apoyo** (tercera, opcional) — `Statistic Card` (ej. un score de intención),
solo cuando aporta directamente a la decisión — nunca una cifra sin relación con la Zona de
sugerencias.

## 4. Roles y variaciones

| | Administrador | Supervisor | Vendedor/Asesor |
|---|---|---|---|
| Alcance del Copiloto | Sobre cualquier conversación | Sobre cualquier conversación de su equipo | Sobre sus propias conversaciones (MPA §9) |
| Capacidad de ejecutar la acción sugerida | Sí | Sí | Sí, dentro de su alcance |

Mismo criterio ya fijado en los capítulos anteriores: el Copiloto existe para los tres roles sin
excepción — el alcance de sobre qué conversaciones opera es lo único que cambia.

## 5. Estados de la composición completa

- **Colapsado** — solo el ícono de marca IA, sin ocupar espacio del área de trabajo principal;
  estado por defecto cuando el usuario no lo pidió activamente.
- **Expandido, generando** — `Skeleton` por sección (sugerencias, contexto, métricas se generan
  de forma independiente, no bloqueadas entre sí).
- **Expandido, con contenido** — composición descrita en la sección 3.
- **Expandido, sin nada que ofrecer** — ninguna sección se fuerza a mostrar contenido vacío;
  si ninguna de las tres zonas tiene algo que superar su propio umbral de relevancia, el panel
  puede quedar reducido a un estado mínimo que lo indique sin ambigüedad, nunca simulando
  actividad que no existe.

## 6. Comportamiento aplicado del MPX

- El panel **nunca se auto-expande** sin que el usuario lo pida — mismo principio de "la IA
  nunca interrumpe" aplicado a nivel de layout completo, no solo de contenido puntual.
- Cada sugerencia responde por qué / por qué ahora / por qué yo — Explainability First (MPX
  Capítulo 3).
- Ninguna acción marcada como irreversible se ejecuta directamente desde este panel sin pasar por
  el **Human Decision Gate** — hoy materializado mediante `Confirm Dialog` del CDS, aplicación
  literal del límite de **Intervención humana** (MPX Capítulo 3) y de la distinción ya fijada en
  MPA §7 entre lo exclusivo de la IA y lo asistido con decisión humana final.
- Cuando la IA no tiene información suficiente para una zona, lo declara explícitamente en vez de
  omitir la zona sin explicación — **Protocolo de incertidumbre** (MPX Capítulo 2).
- El panel nunca toma el foco de teclado ni interrumpe una tarea en curso del usuario (ej. mientras
  escribe una respuesta) para mostrar contenido nuevo que puede esperar — aplicación directa de
  "el Copiloto no compite por el control de la interfaz" (sección 1).

## 7. Responsive

En mobile, se convierte en una hoja inferior accesible bajo demanda — regla ya fijada por el
propio componente `AI Action Panel` del CDS — nunca un panel fijo que reduce el espacio del área
de trabajo principal en una pantalla ya angosta.

## 8. Relación con otros patrones

Vive junto al patrón de Bandeja de Conversaciones (Capítulo 2) como panel contextual sobre la
conversación abierta — comparte el componente `AI Summary` con ese patrón (mismo componente, dos
contextos de uso, ya declarado en el Capítulo 2). La Zona de sugerencias comparte también su
fuente de datos con la Zona de acción de Inicio (Capítulo 3): es la misma capacidad de IA
consumida en dos contextos — uno general (Inicio, sobre todo el trabajo del usuario), uno
específico (Copiloto, sobre la conversación actual).

## 9. Errores comunes

- Auto-expandir el panel sin que el usuario lo pida — contradice directamente la sección 6.
- Convertir una acción del Copiloto en la única vía de acceso a esa acción — toda acción
  disponible ahí (agendar, cotizar) también debe ser alcanzable por el flujo manual normal del
  patrón sobre el que opera; el Copiloto acelera, nunca bloquea.
- Ejecutar una acción irreversible directamente desde una `AI Suggestion Card` sin pasar por el
  Human Decision Gate — viola el límite de Intervención humana de la sección 6, sin importar qué
  mecanismo concreto lo implemente.
- Mostrar una sugerencia por debajo del umbral mínimo de confianza en vez de omitirla — mismo
  error ya señalado en el Capítulo 4 para Analítica, aplica igual acá.
- Que el Copiloto tome el foco o interrumpa una tarea en curso del usuario para mostrar contenido
  que puede esperar — viola directamente "el Copiloto no compite por el control de la interfaz"
  (sección 1); un panel que se impone deja de potenciar el trabajo del usuario.

---

# Capítulo 6 — Patrón: CRM / Pipeline

## 1. Objetivo

El ciclo de vida completo de una oportunidad de negocio — desde que una conversación revela
intención real hasta que se convierte en un resultado (ganado, perdido, en curso). Es donde el
trabajo comercial se organiza más allá del flujo conversacional del día a día, y donde
Administrador y Supervisor intervienen directamente sobre el trabajo del equipo.

**El Lead tiene una única fuente de verdad** (instancia de un principio ya generalizado a toda
entidad de negocio del producto en el Capítulo 9). Independientemente del canal desde el que se
origine una acción sobre un Lead — este patrón (CRM/Pipeline), una conversación (Capítulo 2), una
acción asistida por el Copiloto (Capítulo 5), o una futura automatización o integración — el
estado converge siempre sobre el mismo modelo de dominio. Ningún canal mantiene su propia copia
del estado de un Lead; todos leen y escriben contra la misma fuente. Es la extensión directa de
que MPA §3 declare a este módulo "dueño" del concepto de lead, y de que MPA §12 declare a los
demás módulos como consumidores de este, nunca titulares de su propia copia.

## 2. Trazabilidad

- **MPA**: instancia el módulo **CRM / Pipeline** (MPA §3: "dueño del concepto de 'lead' y su
  ciclo de vida completo: creación, estado, asignación, resultado"). Relación declarada con
  **Conversaciones** (MPA §4: una conversación con intención real crea o actualiza un lead), con
  **Catálogo & Comercial** (MPA §4: "el pipeline consulta el catálogo para cotizar; una venta
  cerrada actualiza qué se vendió realmente"), con **Equipo & Organización** (MPA §4: "el
  pipeline pregunta quién está disponible para asignar") y con **Campañas** (MPA §4: "los leads
  originados en una campaña llegan con su atribución ya adjunta").
- **CDS**: `Tabla / Data Grid` (con `Filtros`, `Ordenamiento`, `Paginación`), `Card`, `Badge`,
  `Avatar`, `Modal` (panel lateral de edición/detalle), `Select`, `Empty State`, `Skeleton`,
  `Conversation Timeline`.
- **MDL**: densidad **compacta** para la tabla (Capítulo 3 — es exploración de datos, no una
  vista de trabajo diario como Inicio o Bandeja), color semántico para `Badge` de estado
  (Capítulo 4).
- **MPX**: **Ediciones concurrentes y datos en conflicto** (Capítulo 9 — relevante porque más de
  una persona del equipo puede ver o intervenir sobre el mismo lead); **Feedback y estados del
  sistema** (Capítulo 5); **Priorización** (Capítulo 3) para el orden por defecto de la lista.

## 3. Composición

**Rail de filtro por etapa** — reutiliza el mecanismo de filtrado del Sidebar/rail ya definido en
el Shell (Capítulo 1), consistente con la decisión ya `Activa` de `MAIEK_AI_FRONTEND_ARCHITECTURE.md`
§2 sobre preservar la arquitectura de información existente — no introduce un segundo sistema de
filtrado paralelo.

**Vista principal** — `Tabla / Data Grid` con `Filtros`, `Ordenamiento` y `Paginación`. Set de
columnas por defecto reducido, con el resto detrás de un toggle "Mostrar todo" cuando hay más de
~7 columnas — regla ya fijada por el propio componente `Tabla / Data Grid` del CDS, no una
decisión nueva de este patrón. Orden por defecto: el más útil para la tarea principal de esta
vista (más reciente o de mayor prioridad primero), nunca alfabético — misma regla ya fijada por
el componente `Ordenamiento` del CDS.

**Vista de detalle** — al seleccionar un lead: panel lateral o vista de detalle con `Conversation
Timeline` (historial de eventos de negocio, no la conversación palabra por palabra — eso vive en
Bandeja de Conversaciones, Capítulo 2), datos de contacto, estado actual, asesor asignado,
atribución de origen cuando el lead proviene de una campaña (MPA §3: debe permanecer **visible
en todo el ciclo de vida posterior del lead**, no es un dato opcional — Capítulo 7.B), y acciones
disponibles según rol (sección 4). Este capítulo declara únicamente que el dato debe estar
presente y visible; dónde se ubica, cómo se presenta y su comportamiento cuando el lead no tiene
atribución quedan definidos en la capa de Product Design (Screen Contract en adelante), no acá.

## 4. Roles y variaciones

| | Administrador | Supervisor | Vendedor/Asesor |
|---|---|---|---|
| Alcance de leads visibles | Todos | Todos los del equipo | Solo los propios (MPA §9) |
| Cambiar estado de un lead | Sí, cualquiera | Sí, cualquiera de su equipo | Sí, solo los propios |
| Reasignar un lead a otro asesor | Sí | Sí | **No** — sin capacidades administrativas |
| Crear/editar un lead manualmente | Sí | Sí | Solo los propios |

Mismo criterio ya fijado desde el Capítulo 1: la capacidad existe para los tres roles — el
alcance y las acciones administrativas (reasignación) son lo que distingue a Administrador y
Supervisor de Asesor, no la existencia del patrón.

## 5. Estados de la composición completa

- **Vacío** — mismas dos variantes ya establecidas en el Capítulo 2: "primer uso" (rol sin leads
  todavía) y "sin resultados de filtro" (hay leads, el filtro activo no los muestra), usando
  `Empty State` del CDS en ambos casos, nunca el mismo mensaje genérico.
- **Cargando** — `Skeleton` con la misma cantidad de filas esperada.
- **Con datos** — composición descrita en la sección 3.
- **Conflicto de edición** — si dos personas, o dos canales distintos (ej. una actualización
  manual en este patrón y una automática disparada desde una conversación), intentan actualizar
  el mismo lead casi a la vez, se resuelve según **Ediciones concurrentes y datos en conflicto**
  (MPX Capítulo 9): la segunda escritura se informa explícitamente del conflicto antes de
  aplicarse, nunca una sobrescritura silenciosa — mismo mecanismo, sea el origen una persona o un
  canal distinto, consistente con la única fuente de verdad ya declarada en la sección 1.

## 6. Comportamiento aplicado del MPX

- El criterio de orden y los filtros activos se mantienen coordinados entre sí y sobreviven a un
  cambio de página — regla ya fijada por los propios componentes `Paginación`/`Filtros`/
  `Ordenamiento` del CDS, nunca se resetean entre sí.
- Un lead que requiere atención prioritaria (ej. sin respuesta hace tiempo) sigue el mismo
  criterio de **Priorización** (MPX Capítulo 3) que ya rige la Zona de acción de Inicio (Capítulo
  3) — de hecho, es la misma señal la que puede alimentar esa zona, no una lógica distinta.
- Ante un conflicto de edición, el sistema comunica qué cambió y quién lo cambió antes de pedir
  al usuario que decida cómo proceder — nunca fuerza una resolución automática silenciosa.

## 7. Responsive

Por debajo del breakpoint `sm`, la `Tabla / Data Grid` se transforma en una lista de `Card` — una
por lead, con las columnas como pares etiqueta/valor apilados — regla ya fijada por el propio
componente, nunca scroll horizontal como única solución mobile. El rail de filtro por etapa sigue
el mismo comportamiento responsive ya definido para el Sidebar en el Capítulo 1.

## 8. Relación con otros patrones

Vive dentro del punto de montaje del Shell (Capítulo 1). Recibe nuevos leads o actualizaciones
desde la Bandeja de Conversaciones (Capítulo 2, sección 8) y desde acciones ejecutadas vía el
Copiloto IA (Capítulo 5, tras pasar por el Human Decision Gate cuando la acción es irreversible)
cuando alguno de esos canales revela intención real o resuelve una acción — ambos escriben contra
el mismo modelo de Lead que este patrón posee, nunca sobre una copia propia (sección 1). Recibe
también, ya adjunta desde el origen (MPA §4; evidencia complementaria en Capítulo 7.B, sección 8),
la atribución de campaña de los leads que se originaron en una campaña activa. Alimenta la Zona
de acción de Inicio (Capítulo 3) y la zona de detalle comparativo de Analítica (Capítulo 4) con el
mismo dato de embudo, sin duplicar su cálculo. Consulta al patrón de Catálogo (Capítulo 7.A) para
cotizar dentro de la vista de detalle.

## 9. Errores comunes

- Permitir que un Asesor reasigne un lead a otro asesor — viola directamente el alcance ya
  fijado en la sección 4, no es un detalle menor de permisos.
- Mezclar densidad cómoda y compacta dentro de la misma vista — esta vista es exploración de
  datos, mantiene densidad compacta de forma consistente, a diferencia de Inicio o Bandeja.
- Que un canal (ej. Bandeja de Conversaciones, Copiloto, una futura automatización) mantenga su
  propia copia del estado de un Lead en vez de leer y escribir contra la única fuente de verdad
  ya declarada en la sección 1 — genera divergencia entre canales, exactamente lo que ese
  principio existe para evitar.
- Resolver un conflicto de edición sobrescribiendo en silencio el cambio de otra persona — viola
  directamente la sección 5 y 6.
- No mostrar visualmente cuál es el criterio de orden activo ni en qué dirección — regla ya
  fijada por el componente `Ordenamiento` del CDS.

---

# Capítulo 7 — Patrones administrativos: Catálogo, Campañas y Equipo

Los tres módulos de soporte al flujo principal (MPA §11: "módulos que el flujo principal consulta
o recibe, pero que tienen su propio ciclo de gestión independiente"). Comparten forma —
`Tabla / Data Grid` de gestión con vista de detalle — por lo que se agrupan en un solo capítulo,
cada uno como una entrada completa e independiente entre sí (MPA §12: ningún módulo de soporte
depende de otro módulo de soporte).

## 7.A — Patrón: Catálogo & Comercial

### 1. Objetivo

Fuente única de verdad de qué se vende, a qué precio y bajo qué condiciones — lo que un asesor o
Gabi necesitan citar con exactitud durante una conversación real.

### 2. Trazabilidad

- **MPA**: instancia **Catálogo & Comercial** (MPA §3, §6: "gestión de productos y precios, envío
  de fichas/catálogo dentro de la conversación, cálculo de financiamiento").
- **CDS**: `Tabla / Data Grid`, `Card`, `Search Box`, `Modal` (alta/edición de producto), `Empty
  State`, `Skeleton`.
- **MDL**: densidad **compacta** para la tabla, densidad **cómoda** para la ficha de detalle de
  un producto (Capítulo 3).
- **MPX**: mismo principio de voz ya fijado en `MAIEK_AI_FRAMEWORK.md` ("nunca inventa
  información que no te hayan proporcionado") aplicado acá de forma literal: ningún precio o
  condición que Gabi o un asesor citan puede diferir del contenido de este patrón.

### 3. Composición

**Vista principal** — `Tabla / Data Grid` con `Search Box`, columnas de producto/precio/
condiciones. **Vista de ficha** — `Card` de detalle de un producto, el mismo contenido que se
adjunta como `Attachment` dentro de una conversación (Capítulo 2) cuando se envía un catálogo o
ficha — mismo dato, dos superficies de presentación, nunca copias que puedan divergir (misma
única fuente de verdad ya establecida para Lead en el Capítulo 6, generalizada a toda entidad de
negocio en el Capítulo 9, aplicada acá al producto).

### 4. Roles y variaciones

| | Administrador | Supervisor | Vendedor/Asesor |
|---|---|---|---|
| Alcance | Crear, editar | Solo lectura | Solo lectura, para citar en conversación (MPA §9) |

Mismo criterio ya fijado en capítulos anteriores: el patrón existe para los tres roles, la
capacidad de edición es lo único exclusivo de Administrador.

### 5. Estados de la composición completa

Mismas variantes ya establecidas en capítulos anteriores: vacío ("primer uso" / "sin resultados
de filtro"), cargando (`Skeleton`), con datos.

### 6. Comportamiento aplicado del MPX

Cualquier cambio de precio o condición se refleja de inmediato en cualquier superficie que lo
cite (conversación, cotización, vista de ficha) — nunca una versión cacheada que pueda divergir
del catálogo vigente.

### 7. Responsive

`Tabla / Data Grid` se transforma en lista de `Card` en mobile — misma regla ya fijada por el
componente.

### 8. Relación con otros patrones

Consultado por CRM/Pipeline (Capítulo 6) para cotizar dentro de la vista de detalle de un lead.
Su contenido se adjunta como `Attachment` dentro de la Bandeja de Conversaciones (Capítulo 2).

### 9. Errores comunes

- Permitir que un Asesor edite un precio o condición — viola el alcance de la sección 4.
- Que la ficha adjuntada en una conversación muestre un precio distinto al de la vista principal
  del catálogo — viola la única fuente de verdad de la sección 3.

---

## 7.B — Patrón: Campañas

### 1. Objetivo

Responsable de la adquisición — de dónde vienen los leads nuevos y de mantener la atribución de
origen visible en todo el ciclo de vida posterior del lead.

### 2. Trazabilidad

- **MPA**: instancia **Campañas** (MPA §3, §6: "detección de origen, atribución persistente,
  activación/desactivación de campañas").
- **CDS**: `Tabla / Data Grid`, `Badge` (estado activa/inactiva), `Switch`, `Modal` (alta/edición
  de campaña), `Empty State`, `Skeleton`.
- **MDL**: densidad **compacta**.
- **MPX**: el cambio de estado de una campaña (`Switch`) se refleja de inmediato en el sistema —
  mismo criterio ya fijado por el propio componente `Switch` del CDS, sin necesitar el Human
  Decision Gate del Capítulo 5 (activar/desactivar una campaña es reversible, no es una acción
  irreversible).

### 3. Composición

`Tabla / Data Grid` de campañas, con `Badge` de estado y `Switch` de activación por fila. Vista
de detalle: qué leads se originaron en esa campaña (enlace directo a la vista filtrada de
CRM/Pipeline, Capítulo 6, no una copia de esos datos).

### 4. Roles y variaciones

| | Administrador | Supervisor | Vendedor/Asesor |
|---|---|---|---|
| Alcance | Crear, editar, desactivar | Solo lectura | **Sin acceso** (MPA §9) |

Único patrón de este capítulo, y de los tres administrativos, donde el rol Asesor no tiene
capacidad — MPA §9 lo declara "Sin acceso" de forma literal, a diferencia de CRM/Pipeline o
Analítica, donde el mismo rol tiene alcance acotado pero visible.

### 5. Estados de la composición completa

Mismas variantes ya establecidas: vacío, cargando, con datos.

### 6. Comportamiento aplicado del MPX

El `Switch` de activación no requiere confirmación adicional — es reversible, coherente con "cada
interacción reduce el esfuerzo mental del usuario" (MDL Capítulo 0): agregar una confirmación a
una acción reversible sería fricción sin necesidad.

### 7. Responsive

`Tabla / Data Grid` se transforma en lista de `Card` en mobile.

### 8. Relación con otros patrones

Alimenta a CRM/Pipeline (Capítulo 6) con la atribución de origen de cada lead nuevo. Consultado
por Analítica (Capítulo 4) para medir rendimiento por campaña.

### 9. Errores comunes

- Mostrar el ítem de Campañas a un Asesor, aunque sea deshabilitado — viola "ocultar, no vaciar"
  ya establecido desde el Capítulo 1; acá corresponde ocultarlo por completo, no atenuarlo.
- Duplicar el detalle de leads de una campaña en vez de enlazar a la vista ya filtrada de
  CRM/Pipeline.

---

## 7.C — Patrón: Equipo & Organización

### 1. Objetivo

Dueño de usuarios, roles, disponibilidad y reglas de asignación — responde "quién puede ver esto"
y "a quién le toca este lead" para el resto del producto.

### 2. Trazabilidad

- **MPA**: instancia **Equipo & Organización** (MPA §3, §6: "alta de usuarios, roles,
  disponibilidad en tiempo real, balance de carga entre asesores").
- **CDS**: `Tabla / Data Grid`, `Avatar`, `Badge` (disponibilidad), `Switch` (disponible/no
  disponible), `Modal` (alta/edición de usuario).
- **MDL**: densidad **compacta**.
- **MPX**: mismo criterio de `Switch` inmediato ya establecido en 7.B para el toggle de
  disponibilidad.

### 3. Composición

`Tabla / Data Grid` de miembros del equipo, con `Avatar`, `Badge` de disponibilidad y carga
actual. Vista de detalle (Administrador): alta/edición de permisos y rol.

### 4. Roles y variaciones

| | Administrador | Supervisor | Vendedor/Asesor |
|---|---|---|---|
| Alcance | Alta, edición, permisos | Solo lectura de carga/disponibilidad del equipo | Solo su propia disponibilidad (MPA §9) |

Mismo criterio ya corregido desde el Capítulo 1: el Asesor no queda sin este patrón — su alcance
se acota a su propio estado, nunca al de otros.

### 5. Estados de la composición completa

Mismas variantes ya establecidas: vacío, cargando, con datos.

### 6. Comportamiento aplicado del MPX

El toggle de disponibilidad se refleja de inmediato, sin loading salvo que la operación de fondo
realmente lo requiera — regla ya fijada por el componente `Switch` del CDS.

### 7. Responsive

`Tabla / Data Grid` se transforma en lista de `Card` en mobile.

### 8. Relación con otros patrones

Consultado por CRM/Pipeline (Capítulo 6) para determinar quién está disponible al reasignar.
Alimenta un futuro patrón de Notificaciones con el estado de carga del equipo.

### 9. Errores comunes

- Que un Asesor pueda ver la disponibilidad o carga de otro asesor — viola directamente el
  alcance de la sección 4.
- Bloquear la actualización de la propia disponibilidad de un Asesor detrás de un permiso de
  administrador — esa acción es, por definición, siempre propia.

---

# Capítulo 8 — Patrón: Notificaciones

## 1. Objetivo

Cómo se entera cada persona de lo que necesita saber sin tener que ir a buscarlo. MPA §3 ya lo
declara como "capacidad transversal que decide qué, a quién y cuándo avisar". A diferencia de
Conversaciones o CRM/Pipeline, Notificaciones no es una superficie de producto autónoma: es un
servicio transversal que otros módulos consumen cuando ocurre un evento que requiere la atención
de una persona específica.

## 2. Trazabilidad

- **MPA**: capacidad transversal (§3); relación declarada — "CRM/Pipeline y Equipo & Organización
  → Notificaciones: cualquier evento que requiere la atención de una persona (nueva asignación,
  mensaje sin responder) dispara una notificación" (§4); tres capacidades — alertas en producto,
  badges de conteo, notificaciones de escritorio (§6); permisos — Admin=todas, Supervisor=equipo,
  Asesor=propias (§9).
- **CDS**: `Icon Button`, `Badge` — ya citados y reservados por Cap. 1 §3.
- **MPX**: Capítulo 7 completo — tres canales (in-app silenciosa, banner in-app, Push/externo),
  agrupación y batching, jerarquía visual sistema vs. sugerencia de IA, degradación por fatiga,
  cross-channel experience.
- **Este documento**: Cap. 1 §3 (Badge+Icon Button ya reservado en la Top Navigation); Cap. 1 §6
  (la jerarquía sistema-vs-IA ya se declaró ahí como "principio a cumplir cuando corresponda, no
  implementado hoy" — este capítulo hereda el mismo tratamiento); Cap. 7.C (Equipo &
  Organización) — "Alimenta un futuro patrón de Notificaciones con el estado de carga del
  equipo", relación entrante declarada, no consumida todavía por este capítulo (ver §8).
- **Decisiones de producto**: DEC-01 (canal), DEC-02 (Badge), DEC-03 (estados), DEC-04
  (clasificación de `agent/notificaciones.py`) — aprobadas por el usuario tras un ciclo de Gate 1
  (recuperación de evidencia) y Gate 2 (reconciliación) previos a esta redacción.

## 3. Composición

- Entrada declarada: `Icon Button`+`Badge` de la Top Navigation (Cap. 1 §3).
- Canales: in-app silenciosa (contador) y banner in-app — declarados, sin implementación
  evidenciada; Push/externo, con dos realizaciones actuales (Browser Notification API y correo
  vía Resend) y una posibilidad futura ya nombrada documentalmente (WhatsApp), sin evidencia de
  implementación (DEC-01).
- Eventos-fuente reconocidos por el patrón: nueva asignación, mensaje sin responder (MPA §4).
  "Cita próxima" existe en la implementación de escritorio actual, pero no tiene respaldo
  documental como evento-fuente del patrón — no se incorpora a esta lista (DEC-02).
- Relación evento → canal → estado → contador: un mismo evento puede tener más de una realización
  simultánea sin que eso sea una duplicación de diseño — ver §8, caso "nueva asignación".
- No se define acá layout del panel, drawer, página, posición, animaciones ni ningún componente
  visual nuevo — corresponde a Wireframe/Mockup de un futuro recorrido de Product Design.

## 4. Roles y variaciones

Tabla heredada de MPA §9: Administrador ve todas las notificaciones; Supervisor, las de su
equipo; Vendedor/Asesor, únicamente las propias. Esta tabla se declara como comportamiento
objetivo del patrón. Su cobertura real en la implementación actual queda marcada aparte: la
superficie de escritorio hoy construida filtra por `asesor_asignado=username`, verificada
únicamente para el rol Asesor — no hay evidencia de que Admin/Supervisor tengan hoy un
comportamiento equivalente implementado.

## 5. Estados

*(Habilitado por DEC-03.)*

- **Pendiente/no leída** — existe una notificación que la persona no atendió todavía.
- **Leída** — la persona la vio, en cualquier canal.
- **Atendida** — la persona actuó sobre el evento que la originó.
- **Sin notificaciones pendientes** — estado vacío del contador/Badge.

Estos cuatro estados son comportamiento objetivo del patrón por decisión de producto (DEC-03), no
una descripción de una estructura ya existente. La aproximación más cercana hoy es el flag
`visto_asesor` sobre el Lead, junto con la deduplicación vía `localStorage` en el navegador —
ninguno de los dos constituye un modelo formal de "Notificación" con estos cuatro estados
propios; se documentan como el punto de partida real, no como la estructura definitiva. Modelo de
datos, persistencia server-side y superficie de consulta de pendientes/anteriores quedan
explícitamente diferidos a una capa posterior (DEC-03).

## 6. Comportamiento aplicado del MPX

Ciclo: **evento relevante → evaluación del destinatario → elección de canal → entrega → estado →
posible atención/acción.**

- El Badge se alimenta de los eventos aprobados en DEC-02 (nueva asignación, mensaje sin
  responder).
- Push/externo, con las realizaciones ya reconocidas en §3.
- **[EO]** La implementación actual permite que, al hacer clic sobre una notificación relacionada
  con un Lead, se llegue directamente al contexto de ese Lead — comportamiento observado en
  `agent/dashboard.py`, no una regla ya declarada en MPA/MPX. **[PEND]** Generalizar esto a una
  regla normativa del patrón no tiene respaldo documental explícito en el corpus consultado (el
  candidato más cercano, "Acción antes que observación", trata orden de presentación dentro de
  una pantalla, no navegación desde una notificación); queda como comportamiento observado, no
  como requisito, hasta que exista evidencia o una decisión de producto adicional.
- Agrupación y batching (MPX Cap. 7): declarados como principio a cumplir cuando corresponda,
  mismo tratamiento ya usado en Cap. 1 §6 para la jerarquía sistema-vs-IA — ninguna regla de
  umbral, ventana temporal o algoritmo se define acá porque ninguna fuente la define.
- Degradación por fatiga (MPX Cap. 7): mismo tratamiento — principio declarado, sin mecanismo
  técnico definido. MPX es explícito en que nunca debe resolverse como un apagado silencioso sin
  acción explícita de la persona.
- Jerarquía visual sistema-vs-IA (MPX Cap. 7, ya citada en Cap. 1 §6): aplica igual acá — hoy
  ninguna notificación tiene contenido generado por IA; la regla queda declarada para cuando
  exista, mismo criterio ya usado en Cap. 1.

## 7. Responsive

Mismo criterio ya fijado en Cap. 1 §7 para la Top Navigation: por debajo del breakpoint `sm`, el
acceso a notificaciones se mantiene dentro del colapso general ya declarado (wordmark + perfil +
menú). No se define una experiencia móvil específica de Notificaciones porque no hay evidencia de
que deba diferir del comportamiento ya declarado del Shell.

## 8. Relación con otros patrones

- **Shell de Navegación (Cap. 1)**: aloja la entrada visual del patrón (Badge+Icon Button).
- **CRM/Pipeline (Cap. 6)** y **Equipo & Organización (Cap. 7.C)**: fuentes de eventos; Equipo &
  Organización ya declaraba esta relación de forma prospectiva en su propio capítulo.
- El evento "nueva asignación" tiene **dos realizaciones reconocidas, no una duplicación
  accidental**: (a) notificación al Asesor asignado, vía Badge/notificación de escritorio; y (b)
  `notificar_lead_derivado`, correo a la lista de distribución del equipo comercial — un mecanismo
  operativo paralelo relacionado con el mismo evento, con audiencia y canal distintos (DEC-04).
  Ambas realizaciones conviven; ninguna reemplaza a la otra.
- `notificar_solicitud_reseteo` queda **fuera de este patrón** — pertenece al territorio de
  Autenticación/operaciones administrativas (DEC-04).

## 9. Errores comunes

- Enviar una notificación por cada evento individual sin agrupar cuando la fuente lo amerita —
  contradice la agrupación/batching de MPX Cap. 7 (sin mecanismo definido todavía, ver §6).
- Degradar silenciosamente la frecuencia de notificaciones sin una acción explícita de la persona
  — MPX Cap. 7 lo prohíbe de forma literal.
- Mezclar una alerta operativa del sistema con una sugerencia de IA sin distinción visual, si en
  el futuro ambas conviven — mismo riesgo ya señalado en Cap. 1 §6.
- Alimentar el Badge del Shell con cualquier evento que hoy dispare una notificación de
  escritorio, sin verificar que tenga respaldo documental como evento-fuente — es exactamente el
  error que DEC-02 evita al excluir "cita próxima" por ahora.
- Tratar `agent/notificaciones.py` como parte de la experiencia principal del patrón solo por su
  ubicación en el código — DEC-04 ya estableció que la clasificación depende del destinatario y la
  relación con el usuario individual, no del archivo en el que vive.
- Convertir el comportamiento de navegación observado (§6) en un requisito normativo sin evidencia
  documental que lo respalde.

---

# Capítulo 9 — Principios Transversales de Producto

Este capítulo no define ningún patrón nuevo — consolida, en un solo lugar, la filosofía de
producto que ya quedó establecida a lo largo de los Capítulos 1 a 8. Nada acá es una decisión
nueva; cada principio cita el capítulo donde se estableció por primera vez y los capítulos donde
ya se aplica.

**Distinto del Capítulo 0.** El Capítulo 0 gobierna cómo se *escribe* este documento (qué es un
patrón, cómo se estructura, cómo se traza, cómo se distingue de la evidencia que lo motivó) — son
reglas editoriales. Este capítulo gobierna cómo se *comporta el producto* — son reglas de diseño
que cualquier patrón futuro, de este documento o de una extensión suya, debe cumplir. Un principio
puede vivir en ambos si tiene las dos caras, como Plataforma primero (sección siguiente).

## Plataforma primero

Ante una diferencia entre una necesidad específica de una implementación y un patrón reutilizable,
el patrón se diseña primero desde la perspectiva de Maiek AI como producto SaaS — la necesidad
específica se resuelve por configuración, permisos, parametrización o especialización, nunca
creando un patrón distinto ni modificando el patrón base. Establecido como Principio 3 del
Capítulo 0; aplicado de forma verificable en que ningún patrón de este documento (Capítulos 1 a 8)
nombra una implementación específica en su definición.

**Precisión de gobernanza**: configuración, permisos, parametrización o reglas de negocio pueden
**especializar** el comportamiento de un patrón — nunca **modificar** el patrón canónico en sí.
Especializar significa activar una variación ya prevista por el patrón (ej. el alcance por rol ya
definido en cada tabla de "Roles y variaciones"); modificar significa alterar su composición,
trazabilidad o estructura ya aprobada. Lo primero es el mecanismo normal de uso de este documento;
lo segundo requiere pasar por el proceso de evolución de la sección "Cómo se usa este capítulo" —
nunca ocurre de forma implícita dentro de una implementación. Este criterio de gobernanza se
preserva para toda futura implementación de Maiek AI, no solo para la instanciación actual.

## Capacidad vs. alcance

La capacidad de un patrón existe para todos los roles a los que MPA §9 no le niega acceso de
forma explícita ("Sin acceso"); lo que varía entre roles es el alcance de datos y acciones
disponibles, nunca la existencia del patrón. Un rol solo pierde un patrón por completo cuando MPA
§9 lo declara así de forma literal — nunca por inferencia o por conveniencia de diseño. Establecido
al corregirse en el Capítulo 1 (Shell); aplicado en Inicio (Capítulo 3), Analítica (Capítulo 4),
CRM/Pipeline (Capítulo 6) y Equipo (Capítulo 7.C). Único caso de ocultamiento total confirmado
hasta ahora: Campañas para el rol Asesor (Capítulo 7.B), porque MPA §9 lo declara "Sin acceso" de
forma literal — la excepción confirma la regla, no la contradice.

## Acción antes que observación

Cualquier patrón cuyo propósito sea ayudar a decidir presenta primero lo accionable y después lo
observacional — nunca al revés, en ningún breakpoint. Indicadores, alertas y resúmenes existen
solo en la medida en que facilitan una decisión ya priorizada; la analítica de profundidad vive en
un patrón dedicado (Analítica, Capítulo 4), nunca mezclada con un patrón de acción. Establecido en
Inicio (Capítulo 3), fundamentado directamente en la narrativa "Un día completo con Maiek" del MDL
Capítulo 0; aplicado también en la composición de Copiloto IA (Capítulo 5, sugerencias antes que
contexto).

## Human Decision Gate

Ninguna acción irreversible o de impacto significativo se ejecuta sin una decisión explícita del
usuario — el criterio no es confirmar toda acción (eso sería fricción sin necesidad), es proteger
específicamente las que cumplen ese umbral. El principio es invariante; el mecanismo que lo
materializa hoy (`Confirm Dialog` del CDS) puede evolucionar sin alterarlo. Establecido en
Copiloto IA (Capítulo 5), a partir del límite ya declarado en MPA §7 entre capacidades exclusivas
de la IA y capacidades asistidas con decisión humana final. No aplica a acciones reversibles (ver
Campañas, Capítulo 7.B, activar/desactivar no lo requiere).

## Única fuente de verdad

Toda entidad de negocio del producto — Lead, Catálogo, Usuario, Campaña, y cualquier otra que se
incorpore a futuro — converge sobre un único modelo de dominio, sin importar el canal desde el
que se origine una acción sobre ella (un patrón de gestión directo, una conversación, una acción
asistida por el Copiloto, o una futura automatización o integración). Ningún canal ni ninguna
superficie de presentación mantiene su propia copia. Establecido para Lead en CRM/Pipeline
(Capítulo 6), generalizado acá a toda entidad de negocio, ya aplicado también a Catálogo
(Capítulo 7.A).

## La IA asiste, nunca reemplaza el criterio humano

El principio más antiguo de los seis — ya establecido en `MAIEK_AI_FRAMEWORK.md` antes de que
existiera cualquier patrón de este documento. Se especializa en dos reglas operables ya aplicadas:
**Explainability First** (toda sugerencia responde por qué / por qué ahora / por qué yo, o no se
muestra — MPX Capítulo 3, aplicado en Inicio, Analítica y Copiloto) y **Human Decision Gate**
(sección anterior). Tiene además un corolario de interacción, establecido en Copiloto IA
(Capítulo 5): **el Copiloto no compite por el control de la interfaz** — comprende el contexto,
prioriza opciones, justifica recomendaciones y acelera decisiones, pero nunca reemplaza el flujo
de trabajo del usuario ni lo interrumpe innecesariamente.

## Cómo se usa este capítulo

Antes de escribir un patrón nuevo, en cualquier versión futura de este documento: verificar que su
diseño no contradiga ninguno de los seis principios de arriba. Si un patrón nuevo pareciera
necesitar contradecir uno, la contradicción no se resuelve en el patrón — se revisa acá primero,
con el mismo criterio de "nunca edición silenciosa" que rige el resto del corpus desde el MDL
v1.1: una nueva fila en el Control de versiones, con la razón explícita del cambio.

---

*Fin de `MAIEK_AI_PRODUCT_PATTERNS.md` — **Versión 1.0, Approved el 2026-07-30**; **Capítulo 8
(Notificaciones) agregado el 2026-08-10, ver Control de versiones**. Capítulos 0 a 9,
todos aprobados, cada uno revisado y ajustado por el usuario de forma incremental antes de
continuar con el siguiente. Auditoría documental final de calidad y consistencia realizada sin
observaciones de fondo. Alcance: Shell (Cap. 1), Bandeja de Conversaciones (Cap. 2),
Inicio (Cap. 3), Analítica (Cap. 4), Copiloto IA (Cap. 5), CRM/Pipeline (Cap. 6), Catálogo/
Campañas/Equipo (Cap. 7), Notificaciones (Cap. 8), Principios Transversales (Cap. 9). Diferido a v1.1, sin fecha fija:
Formularios/Modales dedicados, un capítulo de Estados transversales consolidado (hoy repetido
patrón por patrón) y Responsive por patrón consolidado — mismo criterio ya usado en todo el
corpus: solo se agregan ante necesidad real de uso, nunca de forma especulativa.*
