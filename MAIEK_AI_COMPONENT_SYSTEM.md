# Maiek AI — Component Design System (CDS)

**Versión 1.0 · Estado: Approved — Referencia oficial**

| | |
|---|---|
| Documento | Maiek Component Design System (CDS) |
| Proyecto | Maiek AI |
| Versión | 1.0 |
| Estado | **Approved** |
| Fecha de creación | 2026-07-26 |
| Autor | Claude, a pedido de Jesús Millones |
| Última actualización | 2026-07-26 |

> Depende de [`MAIEK_AI_DESIGN_SYSTEM.md`](MAIEK_AI_DESIGN_SYSTEM.md) (Design Language v1.1,
> Approved) — todo componente de este catálogo se construye exclusivamente con los tokens
> definidos ahí (espaciado, radio, color, tipografía, motion). Ningún componente introduce un
> valor fuera de esas escalas.
>
> **Alcance:** catálogo de especificación de componentes — objetivo, uso, variantes, estados,
> accesibilidad, responsive, buenas prácticas, errores comunes y relaciones. **No incluye
> código**, ni diseño de pantallas completas, ni funcionalidad nueva de producto. Cada
> componente respeta el MDL aprobado sin excepción.

## Control de versiones

| Versión | Fecha | Autor | Descripción |
|---|---|---|---|
| 1.0 | 2026-07-26 | Claude | Primera versión — catálogo completo de ~48 componentes en 8 categorías (Navegación, Botones, Formularios, Información, Datos, Feedback, IA, Conversación), matriz de principios y orden recomendado de implementación. Congelado como referencia oficial. |

A partir de esta versión, cualquier componente nuevo o modificación de uno existente debe
respetar este catálogo y mantener consistencia con el MDL — este documento no se edita en
silencio; todo cambio de fondo suma una fila nueva a esta tabla, igual que el MDL.

**Pendiente de implementación real** — ver "Componentes recomendados para implementar
primero" al final del documento.

## Cómo leer este catálogo

**Reglas heredadas, no repetidas.** Salvo que se indique lo contrario, todo componente hereda
sin excepción: anillo de foco de 2px en el color primario del modo activo, contraste mínimo AA,
área mínima de toque (32px desktop / 44px mobile), y los 5 estados base del Capítulo 3 del MDL
(reposo, hover, focus, activo, deshabilitado). La sección "Accesibilidad" y "Responsive" de
cada componente solo documenta lo que se **agrega o se aparta** de esa regla general — repetir
lo ya establecido en cada una de las 48 entradas de este catálogo no aportaría valor, iría
contra el principio "silencio antes que ruido" del propio MDL.

**Consolidación deliberada.** El pedido original lista "Primary / Secondary / Ghost" como tres
componentes de botón — en la práctica de un design system real son **variantes de un mismo
componente Button**, no tres componentes distintos con anatomía propia (mismo alto, mismo
radio, mismo padding, mismo comportamiento de foco; solo cambia color de relleno/borde). Se
documentan así, como variantes dentro de una sola entrada, siguiendo "Reutilización primero"
(`MAIEK_AI_PLATFORM_ARCHITECTURE.md`). Mismo criterio para **Tabla** y **Data Grid** — Data
Grid es Tabla en su modo de mayor densidad (filtros, orden y paginación activados a la vez),
no un componente con anatomía distinta.

**Profundidad calibrada, no pareja.** Los componentes que aparecen en más pantallas y que
otros componentes heredan o componen (Button, Text Input, Card, Tabla, Modal, Chat) tienen
tratamiento completo en las 10 dimensiones pedidas. Los componentes más simples o derivados
(Tag, Breadcrumb, Progress) se documentan igual de completos pero de forma más breve, citando
al componente del que heredan en vez de repetir la misma regla.

---

# Navegación

## Sidebar

**Objetivo.** Navegación persistente de primer nivel — responde "¿en qué parte de Maiek estoy
y a dónde más puedo ir?" en todo momento, sin ocupar más espacio del necesario.

**Cuándo utilizarlo.** En cualquier pantalla de trabajo autenticada, como contenedor único de
navegación entre secciones (rail de filtros, equipo, canales — ver el rail ya construido en
Gaso+ como precedente directo).

**Cuándo NO utilizarlo.** En pantallas de login/onboarding (sin contexto de navegación
todavía), ni como contenedor de acciones de una sola pantalla (eso es un panel lateral
contextual, no el Sidebar).

**Variantes.** Expandido (default, `280px` de ancho — ver `space-*` del MDL para el ancho
exacto según densidad de contenido) y colapsado (solo íconos, `64px`) para pantallas `md` e
inferiores.

**Estados.** Ítem: reposo, hover, activo (fondo `primary-50` claro / `primary-900` oscuro +
texto `primary-600`/`400`), deshabilitado (rol sin permiso, oculto — no deshabilitado
visible, ver Buenas prácticas). Sección: expandida/colapsada (ver `_subtitulo_contraible` de
Gaso+ como precedente de interacción).

**Accesibilidad.** Navegable con teclado en orden lógico de arriba a abajo; el ítem activo se
anuncia con `aria-current="page"`, no solo con color.

**Responsive.** Por debajo de `sm` se convierte en overlay a pantalla completa activado por un
botón — nunca se comprime a un ancho intermedio ilegible.

**Buenas prácticas.** Un rol sin permiso sobre una sección nunca ve esa sección deshabilitada
en gris — directamente no aparece (evita comunicar "esto existe pero no es para ti", más
cercano al principio de calma del Capítulo 0).

**Errores comunes.** Anidar más de 2 niveles de jerarquía dentro del Sidebar — si hace falta
un tercer nivel, esa sección necesita su propia pantalla, no más anidamiento.

**Relación con otros componentes.** Contiene ítems de navegación (no un componente aparte, ver
Menús) y Badge (contador, ej. conversaciones sin leer).

## Top Navigation

**Objetivo.** Identidad de marca + accesos globales (perfil, búsqueda, notificaciones) —
siempre visible, nunca compite con el Sidebar por la misma información.

**Cuándo utilizarlo.** Una sola vez por sesión, como shell fijo de toda la aplicación
autenticada.

**Cuándo NO utilizarlo.** Nunca duplicar navegación de secciones acá si ya vive en el
Sidebar — la Top Navigation es para lo transversal (cuenta, notificaciones), no para
navegación de producto.

**Variantes.** Con buscador global expandido / con buscador como ícono que expande al
enfocarse (`sm` e inferiores).

**Estados.** Los de sus componentes hijos (Avatar, Badge de notificaciones, Icon Button) — la
barra en sí no tiene estado propio.

**Accesibilidad.** El buscador global es alcanzable por atajo de teclado (`Cmd/Ctrl+K`) desde
cualquier pantalla.

**Responsive.** En mobile, colapsa a: logo + acceso a perfil + menú — el buscador se mueve
detrás de un ícono.

**Buenas prácticas.** Máximo 4 elementos interactivos en la barra (buscador, notificaciones,
ayuda, perfil) — cualquier acceso adicional va dentro del menú de perfil, no suelto en la barra.

**Errores comunes.** Agregar accesos de producto sueltos (ej. un botón "Nueva campaña") acá en
vez de en la pantalla correspondiente — la Top Navigation es cuenta, no producto.

**Relación con otros componentes.** Compone Avatar, Badge, Icon Button, Search Box (modo
compacto).

## Breadcrumb

**Objetivo.** Mostrar la ruta jerárquica hasta la pantalla actual cuando esa jerarquía tiene
más de 2 niveles y no es evidente por el Sidebar solo.

**Cuándo utilizarlo.** Pantallas de detalle anidadas (ej. Cliente → Conversación → Detalle de
cotización).

**Cuándo NO utilizarlo.** Si la jerarquía tiene 1-2 niveles ya claros por el Sidebar — un
Breadcrumb redundante es ruido, no orientación (Capítulo 1, "silencio antes que ruido").

**Variantes.** Con íconos por nivel / solo texto (default).

**Estados.** Hereda los de un enlace de texto (reposo, hover, focus); el último nivel (página
actual) no es clicable y se muestra en `text-secondary`, nunca en el color primario.

**Accesibilidad.** Marcado semántico de lista ordenada con `aria-label="Breadcrumb"`.

**Responsive.** Por debajo de `sm`, colapsa a solo el nivel anterior + actual (`... / Nivel
actual`), nunca la ruta completa truncada carácter por carácter.

**Buenas prácticas.** Máximo 4 niveles visibles — más que eso es señal de que la arquitectura
de información necesita revisión, no de que el Breadcrumb necesita más espacio.

**Errores comunes.** Usarlo como navegación principal — el Breadcrumb es orientación, no
reemplaza al Sidebar ni a los Tabs.

**Relación con otros componentes.** Convive con Tabs cuando una pantalla de detalle tiene
además sub-secciones propias.

## Tabs

**Objetivo.** Alternar entre vistas relacionadas del mismo objeto sin cambiar de pantalla ni
perder contexto.

**Cuándo utilizarlo.** Cuando 2 a 5 vistas comparten el mismo sujeto (ej. un cliente: Resumen /
Conversación / Historial / Documentos).

**Cuándo NO utilizarlo.** Más de 5 secciones (usar navegación de Sidebar en su lugar), o
cuando las vistas no comparten sujeto (eso son pantallas distintas, no tabs de una misma).

**Variantes.** Subrayado (default, para contenido) / segmentado tipo píldora (para alternar
modos de una misma vista, ej. Tabla/Kanban).

**Estados.** Reposo, hover, activo (subrayado en color primario + `text-primary`), con
contador (Badge inline, ej. "Documentos (3)").

**Accesibilidad.** Navegación con flechas izquierda/derecha una vez el foco está dentro del
grupo de tabs (patrón ARIA `tablist`/`tab`/`tabpanel`).

**Responsive.** Con más tabs de los que entran en el ancho disponible: scroll horizontal
dentro del grupo de tabs, nunca truncar etiquetas ni ocultarlas en un menú "más" por defecto.

**Buenas prácticas.** El orden de los tabs refleja frecuencia de uso real, no orden alfabético.

**Errores comunes.** Cambiar el contenido de un tab sin actualizar la URL — cada tab debe ser
enlazable y recargable directamente.

**Relación con otros componentes.** El contenido de cada tab es libre (Tabla, Card, Chat) — el
Tabs solo controla cuál se muestra.

## Menús

**Objetivo.** Lista de acciones u opciones que aparece bajo demanda (clic, no siempre visible)
— la forma compacta de ofrecer varias acciones sin ocupar espacio permanente.

**Cuándo utilizarlo.** Acciones secundarias sobre un ítem (ej. "más opciones" en una fila de
tabla), o navegación de perfil/cuenta.

**Cuándo NO utilizarlo.** Para la acción principal de una pantalla — esa siempre es un Button
visible, nunca escondida detrás de un menú.

**Variantes.** Menú simple (lista de acciones) / menú con selección (checkbox o radio inline,
ej. filtro rápido).

**Estados.** Cerrado/abierto, ítem en reposo/hover/focus/deshabilitado, ítem destructivo
(texto en color de error — ver Capítulo 4 del MDL, nunca solo un ícono rojo sin texto).

**Accesibilidad.** Se abre y navega completo por teclado (flechas arriba/abajo, `Enter` para
seleccionar, `Esc` para cerrar); el foco vuelve al elemento que abrió el menú al cerrarlo.

**Responsive.** En mobile se presenta como hoja inferior (bottom sheet) en vez de popover
flotante — más fácil de alcanzar con el pulgar.

**Buenas prácticas.** Máximo 7 ítems por menú — más que eso necesita agrupación con
separadores o submenús, nunca una lista larga sin estructura.

**Errores comunes.** Poner una acción destructiva (eliminar, cerrar sesión) como primer o
último ítem sin separador — debe llevar un separador visual antes, para evitar clics
accidentales.

**Relación con otros componentes.** Se activa desde un Icon Button o desde un ítem de Avatar
(menú de perfil); puede contener Badge para indicar estado de cada opción.

---

# Botones

## Button

**Objetivo.** La acción explícita más común de toda interfaz — comunica de forma inequívoca
qué va a pasar al presionarlo.

**Cuándo utilizarlo.** Toda acción que el usuario inicia deliberadamente y que tiene un
resultado claro (guardar, enviar, confirmar, cancelar).

**Cuándo NO utilizarlo.** Para navegación entre pantallas (usar un enlace de texto o un ítem
de Sidebar/Tabs) — un Button que en realidad navega confunde el modelo mental del usuario
sobre qué es una acción y qué es un destino.

**Variantes.**
- **Primary** — una sola por vista, la acción principal de la pantalla (fondo `primary-600`,
  texto blanco).
- **Secondary** — acciones alternativas válidas (borde `border-strong`, fondo transparente,
  texto `text-primary`).
- **Ghost** — acciones terciarias, de menor peso visual (sin borde ni fondo, solo texto,
  hover con fondo `neutral-100`/`neutral-800`).

**Estados.** Reposo, hover (`motion-instant`, oscurece 1 paso en la escala tonal), focus
(anillo 2px), activo/presionado (oscurece 1 paso más), deshabilitado (opacidad 40% + cursor
`not-allowed`), loading (el texto se reemplaza por un spinner de 16px del mismo color que el
texto original, el ancho del botón no cambia — evita que el layout salte).

**Accesibilidad.** `aria-busy="true"` durante loading; nunca deshabilitar un botón sin
explicar por qué en un `aria-describedby` o tooltip cercano si la razón no es obvia por
contexto.

**Responsive.** Área de toque mínima de 44px de alto en mobile aunque el texto visual sea más
compacto en desktop (32px).

**Buenas prácticas.** Nunca más de un botón Primary visible a la vez en la misma vista — si
hay dos acciones igual de importantes, ninguna es realmente "la principal" y la jerarquía
necesita revisarse, no el componente.

**Errores comunes.** Texto genérico ("Enviar", "Guardar") cuando el contexto lo permite
específico ("Enviar cotización", "Guardar cambios") — ver Microcopy en
`MAIEK_AI_FRAMEWORK.md`. Iconos sin texto en acciones no universalmente reconocibles.

**Relación con otros componentes.** Icon Button y Floating Action Button son variantes de
anatomía distinta del mismo sistema de estados — no reemplazos entre sí.

## Icon Button

**Objetivo.** Acción compacta cuando el ícono es universalmente reconocible y el espacio es
limitado (fila de tabla, barra de herramientas de chat).

**Cuándo utilizarlo.** Cerrar, más opciones, adjuntar, buscar — acciones cuyo ícono no
necesita texto para entenderse.

**Cuándo NO utilizarlo.** Cualquier acción cuyo ícono no sea inequívoco sin texto — en ese
caso, Button con ícono + texto.

**Variantes.** Solo (sin fondo, hover con círculo `neutral-100`/`neutral-800`) / con contador
(Badge superpuesto, ej. notificaciones).

**Estados.** Iguales a Button, adaptados a forma circular/cuadrada de `radius-md`.

**Accesibilidad.** `aria-label` obligatorio siempre — nunca opcional, porque no hay texto
visible que lo supla.

**Responsive.** Tamaño mínimo de toque 44px en mobile, aunque el ícono visual sea de 20px
(`icon-md`) — el área de toque es más grande que el ícono mismo, no del mismo tamaño.

**Buenas prácticas.** El tooltip (ver Tooltip) aparece siempre en hover para reforzar el
`aria-label` visualmente, con `motion-instant` de retardo.

**Errores comunes.** Usar un Icon Button para la acción principal de una pantalla — esa
siempre necesita el peso visual y la claridad de un Button con texto.

**Relación con otros componentes.** Se combina con Tooltip y Badge; vive frecuentemente dentro
de Tabla (acciones de fila) y Top Navigation.

## Floating Action Button

**Objetivo.** Acceso directo a la acción más frecuente de una pantalla mobile, siempre
alcanzable sin desplazarse — mismo rol que el botón circular de filtros ya construido en el
Gaso+ actual.

**Cuándo utilizarlo.** Exclusivamente en mobile, y exclusivamente para una única acción de
altísima frecuencia (ej. abrir filtros, nueva conversación).

**Cuándo NO utilizarlo.** En desktop — en desktop esa misma acción va como Button Primary en
su lugar natural del layout, nunca flotando.

**Variantes.** Solo ícono (default, 56px) / extendido con etiqueta corta (para la primera vez
que aparece, luego colapsa a solo ícono).

**Estados.** Iguales a Button; su sombra es siempre nivel 3 (Capítulo 3 del MDL) porque flota
por encima de todo el contenido.

**Accesibilidad.** Nunca debe superponerse permanentemente sobre contenido interactivo — se
oculta o se atenúa si el usuario está escribiendo (ej. dentro de un campo de texto activo).

**Responsive.** Por definición, solo existe por debajo del breakpoint `sm` (ver Cuándo NO
utilizarlo).

**Buenas prácticas.** Posición fija en la misma esquina en todas las pantallas donde aparece
— cambiar de esquina entre pantallas rompe el hábito muscular que el componente busca crear.

**Errores comunes.** Usar más de un FAB a la vez en la misma pantalla — anula el propósito de
"la acción más frecuente".

**Relación con otros componentes.** Puede abrir un Menú, un Modal, o navegar directo — nunca
contiene una acción destructiva sin confirmación.

---

# Formularios

## Text Input

**Objetivo.** Captura de un dato de texto corto — el componente de formulario más usado, base
de la que heredan Text Area y Search Box.

**Cuándo utilizarlo.** Cualquier dato de una sola línea (nombre, teléfono, monto).

**Cuándo NO utilizarlo.** Texto de más de una línea esperada (usar Text Area) ni selección
entre opciones predefinidas (usar Select).

**Variantes.** Con ícono inicial (ej. buscar), con acción final (ej. mostrar/ocultar
contraseña), con prefijo/sufijo fijo (ej. "S/" para montos en soles).

**Estados.** Reposo, hover (borde `border-strong`), focus (anillo 2px + borde primario),
relleno con valor, error (borde y texto de ayuda en color de error), éxito (borde en color de
éxito, uso puntual — ej. verificación en tiempo real), deshabilitado, solo lectura (fondo
`neutral-50`/`neutral-800`, sin borde de foco porque no es editable).

**Accesibilidad.** `<label>` siempre visible y asociado (nunca solo placeholder como label —
el placeholder desaparece al escribir y el usuario pierde el contexto del campo).

**Responsive.** Ancho fluido al 100% del contenedor en mobile; en desktop, ancho fijo según el
dato esperado (un campo de código postal no ocupa el mismo ancho que uno de dirección).

**Buenas prácticas.** El mensaje de error explica qué corregir, nunca solo que algo está mal
("Ingresa un teléfono de 9 dígitos", no "Campo inválido").

**Errores comunes.** Validar en cada tecla presionada para campos donde eso genera ruido (ej.
email) — validar al perder el foco (`blur`) salvo que la validación en vivo agregue valor real
(ej. medidor de fuerza de contraseña).

**Relación con otros componentes.** Text Area, Search Box y Date Picker heredan su sistema de
estados; se agrupa con Card en un Form.

## Text Area

**Objetivo.** Captura de texto de varias líneas — mensajes, notas, descripciones.

**Cuándo utilizarlo.** Cualquier campo donde se espera más de una línea de texto.

**Cuándo NO utilizarlo.** Datos de una sola línea, aunque sean largos (usar Text Input con
ancho completo en su lugar).

**Variantes.** Altura fija / auto-expansión hasta un máximo de líneas (recomendado para el
campo de respuesta del Chat).

**Estados.** Los mismos de Text Input.

**Accesibilidad.** Contador de caracteres (si existe límite) anunciado a lectores de pantalla
cuando se acerca al límite, no solo visualmente.

**Responsive.** Altura mínima de 3 líneas en cualquier breakpoint — nunca colapsar a 1 línea
en mobile, eso convierte el componente en un Text Input de facto.

**Buenas prácticas.** Auto-expansión con un tope claro (ej. 8 líneas) y scroll interno después
de eso — nunca crecimiento infinito que empuje el resto del layout.

**Errores comunes.** Deshabilitar el salto de línea (`Enter`) en un campo que lo necesita — el
error clásico es reservar `Enter` para "enviar" sin dar una alternativa (`Shift+Enter`) para
salto de línea real.

**Relación con otros componentes.** Hereda de Text Input; es el campo base del compositor de
Chat.

## Select

**Objetivo.** Elegir una opción entre una lista predefinida y acotada.

**Cuándo utilizarlo.** Entre 4 y ~15 opciones conocidas de antemano.

**Cuándo NO utilizarlo.** Menos de 4 opciones (usar Radio, todas visibles de una vez es más
rápido de leer) o más de ~15 (usar Search Box con resultados, o Multi Select con búsqueda
interna).

**Variantes.** Nativo simple / con búsqueda interna (para listas más largas dentro del rango
soportado).

**Estados.** Los de Text Input + estado "abierto" (panel de opciones visible, elevación nivel
2).

**Accesibilidad.** Patrón ARIA `listbox`; navegable completo por teclado, con salto a la
opción que empieza con la letra presionada.

**Responsive.** En mobile, el panel de opciones se presenta como hoja inferior a pantalla
completa en vez de popover angosto.

**Buenas prácticas.** La opción seleccionada siempre visible en el campo cerrado, nunca un
placeholder genérico cuando ya hay un valor elegido.

**Errores comunes.** Usar Select para una sola opción booleana — eso es un Switch o Checkbox.

**Relación con otros componentes.** Multi Select es su variante para más de una selección;
comparte panel flotante con Menús.

## Multi Select

**Objetivo.** Elegir varias opciones de una lista — filtros combinables, etiquetado múltiple.

**Cuándo utilizarlo.** Cuando el usuario necesita 0 a N opciones a la vez de una lista
conocida (ej. filtrar por varios canales).

**Cuándo NO utilizarlo.** Si en la práctica el usuario casi siempre elige exactamente una
opción — ahí Select es más simple y más rápido de usar.

**Variantes.** Con Tag por cada selección dentro del campo / con solo un contador ("3
seleccionados") cuando el espacio es limitado.

**Estados.** Los de Select, más el estado de cada opción individual (marcada/no marcada
dentro del panel).

**Accesibilidad.** Cada opción es un `checkbox` accesible dentro del `listbox`; el total
seleccionado se anuncia al cerrar el panel.

**Responsive.** Mismo criterio de hoja inferior que Select en mobile.

**Buenas prácticas.** Una acción "limpiar todo" siempre visible cuando hay al menos una
selección — no obligar a deseleccionar una por una.

**Errores comunes.** No mostrar el conteo de resultados que produce la combinación de filtros
activa — el usuario multi-selecciona sin saber si eso lo deja con 3 resultados o con 3,000.

**Relación con otros componentes.** Usa Tag y Checkbox internamente; alimenta a Filtros dentro
de Tabla/Data Grid.

## Checkbox

**Objetivo.** Selección binaria independiente — puede haber varios activos a la vez sin
relación entre sí.

**Cuándo utilizarlo.** Aceptar términos, seleccionar varias filas de una tabla, activar
opciones independientes entre sí.

**Cuándo NO utilizarlo.** Cuando las opciones son mutuamente excluyentes (usar Radio) o
cuando es una sola opción de encendido/apagado inmediato (usar Switch).

**Variantes.** Simple / indeterminado (selección parcial, ej. "algunas filas de este grupo
están seleccionadas").

**Estados.** Reposo, hover, focus, marcado, indeterminado, deshabilitado (en cualquier
combinación con marcado/no marcado).

**Accesibilidad.** El área de clic incluye la etiqueta de texto completa, no solo el cuadro de
16px.

**Responsive.** Mismo tamaño visual en todos los breakpoints; solo cambia el área de toque
alrededor.

**Buenas prácticas.** La etiqueta siempre a la derecha del cuadro, nunca arriba ni abajo —
rompe el escaneo vertical de una lista de opciones.

**Errores comunes.** Usar el estado indeterminado como si fuera un tercer valor seleccionable
por el usuario — es solo de lectura, refleja el estado de un grupo, nunca se hace clic
directamente sobre él para llegar ahí.

**Relación con otros componentes.** Selecciona filas en Tabla/Data Grid; compone Multi Select.

## Radio

**Objetivo.** Selección única entre opciones mutuamente excluyentes, todas visibles a la vez.

**Cuándo utilizarlo.** 2 a 5 opciones donde ver todas de una vez ayuda a decidir (ej. tipo de
pago: contado / financiado).

**Cuándo NO utilizarlo.** Más de 5 opciones (usar Select) o una sola opción binaria (usar
Switch).

**Variantes.** Lista vertical (default) / en fila horizontal cuando las etiquetas son cortas.

**Estados.** Reposo, hover, focus, seleccionado, deshabilitado.

**Accesibilidad.** Agrupado en un `fieldset`/`radiogroup` con un `legend` que describe la
pregunta que responde el grupo completo.

**Responsive.** Igual que Checkbox.

**Buenas prácticas.** Siempre una opción seleccionada por defecto cuando existe una opción más
común/recomendada — nunca dejar el grupo vacío si eso obliga a un paso extra sin necesidad.

**Errores comunes.** Permitir que el grupo quede sin ninguna opción seleccionada cuando el
formulario sí requiere una — genera un estado de error evitable.

**Relación con otros componentes.** Mismo sistema de estados que Checkbox, distinto
comportamiento de grupo.

## Switch

**Objetivo.** Encendido/apagado inmediato de una sola configuración — el cambio de estado se
aplica al instante, sin necesitar un botón "Guardar" aparte.

**Cuándo utilizarlo.** Configuraciones binarias de efecto inmediato (ej. el toggle de
"Disponible" ya construido en Gaso+).

**Cuándo NO utilizarlo.** Dentro de un formulario que se guarda como conjunto (ahí, Checkbox
es más correcto semánticamente — "acepto" no es lo mismo que "encendido ahora mismo").

**Variantes.** Con etiqueta de texto a la izquierda (default) / solo el control, cuando el
contexto ya es evidente.

**Estados.** Reposo, hover, focus, activado (fondo `primary-600`), desactivado, deshabilitado,
transicionando (`motion-fast`, 150ms, el círculo se desliza).

**Accesibilidad.** `role="switch"` con `aria-checked`; el estado se anuncia inmediatamente al
cambiar, no solo visualmente.

**Responsive.** Igual en todos los breakpoints — el Switch nunca cambia de tamaño, solo de
contexto de uso.

**Buenas prácticas.** El cambio de estado se refleja de inmediato en el sistema (sin loading
salvo que la operación de fondo realmente lo requiera) — si necesita loading, usar el patrón
de Loading de Feedback, nunca dejar el Switch "a medio camino" visualmente.

**Errores comunes.** Usar un Switch para una acción que en realidad requiere confirmación
(ej. una que no se puede deshacer) — eso necesita Confirm Dialog antes del cambio, no un
Switch directo.

**Relación con otros componentes.** Puede disparar un Toast de confirmación tras el cambio.

## Date Picker

**Objetivo.** Selección precisa de una fecha (y opcionalmente hora) sin depender de que el
usuario escriba el formato correcto a mano.

**Cuándo utilizarlo.** Agendar una cita, filtrar por rango de fechas, fecha de vencimiento.

**Cuándo NO utilizarlo.** Cuando el dato es relativo ("hace 3 días") — eso se calcula y
muestra, no se captura con Date Picker.

**Variantes.** Fecha única / rango de fechas / con selector de hora combinado.

**Estados.** Los de Text Input (el campo que dispara el calendario) + estados del calendario
(día en reposo/hover/seleccionado/fuera de rango/deshabilitado — ej. fechas pasadas en un
selector de citas futuras).

**Accesibilidad.** El calendario es completamente navegable por teclado (flechas para moverse
entre días, `Enter` para seleccionar); el mes/año actual se anuncia al abrir.

**Responsive.** En mobile, el calendario se presenta a pantalla completa, con los días en
tamaño de toque suficiente (mínimo 44px), nunca comprimido al ancho de un popover de desktop.

**Buenas prácticas.** El formato de fecha mostrado siempre es local (DD/MM/AAAA para Perú),
nunca el formato de la librería por defecto sin adaptar.

**Errores comunes.** Permitir seleccionar fechas fuera del rango lógico (ej. agendar una cita
en el pasado) sin deshabilitar visualmente esos días.

**Relación con otros componentes.** El campo visible es un Text Input especializado; el
calendario flotante tiene la misma elevación que un Select.

## Search Box

**Objetivo.** Encontrar un ítem específico dentro de un conjunto grande sin navegar
manualmente.

**Cuándo utilizarlo.** Buscador global de la Top Navigation, búsqueda dentro de una Tabla
larga, búsqueda dentro de un Select/Multi Select con muchas opciones.

**Cuándo NO utilizarlo.** Listas de menos de ~15 ítems — ahí buscar es más lento que escanear
visualmente.

**Variantes.** Expandida siempre visible / colapsada a ícono que expande al enfocar (mismo
patrón que Top Navigation en mobile).

**Estados.** Los de Text Input + estado "buscando" (procesando, ver Loading) + estado "sin
resultados" (ver Empty State, versión compacta inline).

**Accesibilidad.** Resultados anunciados por cantidad al actualizarse ("12 resultados"), no
solo mostrados visualmente.

**Responsive.** En mobile, al enfocar el buscador global se expande a pantalla completa con
resultados debajo, en vez de un dropdown angosto.

**Buenas prácticas.** Debounce de 250-300ms antes de disparar la búsqueda mientras el usuario
escribe — nunca una consulta por cada tecla presionada.

**Errores comunes.** Buscar solo dentro del filtro activo sin avisarlo (ver el hallazgo ya
documentado en la auditoría UX de Gaso+: "la búsqueda no cruza los filtros de estado" — el
placeholder debe decir explícitamente el alcance de la búsqueda si está acotada).

**Relación con otros componentes.** Hereda de Text Input; dispara Empty State cuando no hay
resultados.

---

# Información

## Card

**Objetivo.** Agrupar contenido relacionado en una unidad visual con límites claros — el
componente contenedor más usado del sistema, base de KPI Card y Statistic Card.

**Cuándo utilizarlo.** Cualquier bloque de contenido que se entiende como una unidad (un
lead, un resumen, una conversación en una lista).

**Cuándo NO utilizarlo.** Como contenedor de toda una pantalla — una Card dentro de otra Card
del mismo tamaño es ruido visual, no jerarquía.

**Variantes.** Con acción (clicable completa, ej. abre detalle) / de solo lectura / con header
propio (título + acciones alineadas a la derecha).

**Estados.** Reposo (elevación 0), hover (elevación 1, solo si la Card completa es clicable),
focus (si es clicable), seleccionada (borde en color primario, ej. una Card de plan elegido).

**Accesibilidad.** Si la Card completa es clicable, es un solo elemento enfocable (`role`
apropiado), no múltiples elementos clicables superpuestos sin jerarquía clara.

**Responsive.** En grid, pasa de varias columnas en desktop a una sola columna en mobile —
nunca texto comprimido para mantener columnas que ya no entran.

**Buenas prácticas.** Máximo un CTA (Button) por Card — si necesita dos acciones, una es
Primary y la otra Ghost, nunca dos Primary compitiendo.

**Errores comunes.** Sombra de elevación 2 o 3 en una Card en reposo — eso se reserva para
elementos flotantes (ver Capítulo 3 del MDL), una Card en reposo va en elevación 0 o 1 como
máximo.

**Relación con otros componentes.** Contiene Badge, Avatar, Button; KPI Card y Statistic Card
son variantes especializadas.

## KPI Card

**Objetivo.** Comunicar un número importante de un vistazo, con su tendencia — el bloque base
del futuro dashboard de supervisor (ver mockup de "Bandeja directa"/Dashboard ya discutido).

**Cuándo utilizarlo.** Métricas ejecutivas de alto nivel (conversaciones activas, leads
ganados) en la parte superior de un dashboard.

**Cuándo NO utilizarlo.** Datos que necesitan comparación entre varios ítems — eso es una
Tabla o un gráfico, no una serie de KPI Cards.

**Variantes.** Con delta (`+12% vs ayer`, en color de éxito/error según dirección) / sin delta
(métrica sin comparación temporal, ej. un total acumulado) / con acción ("Ver campañas →").

**Estados.** Reposo, hover (solo si tiene acción asociada), loading (Skeleton con la misma
geometría del número final).

**Accesibilidad.** El delta comunica dirección con ícono (flecha arriba/abajo) además de
color — nunca solo verde/rojo para indicar mejora/caída.

**Responsive.** En mobile, grid de 2 columnas en vez de 4-6 en desktop — nunca una sola
columna que obligue a scroll largo para ver el resumen completo.

**Buenas prácticas.** El número es siempre `text-display` o `text-title-lg` con
`tabular-nums` — el número es el protagonista de la Card, todo lo demás es contexto.

**Errores comunes.** Mostrar más de 6-8 KPI Cards en una sola fila — eso deja de ser "resumen
de un vistazo" y vuelve a ser una tabla disfrazada.

**Relación con otros componentes.** Es una Card especializada; puede incluir un ícono de AI
Confidence Indicator cuando el número proviene de una predicción, no de un conteo exacto.

## Statistic Card

**Objetivo.** Igual que KPI Card, pero para métricas de detalle dentro de un bloque (no en la
franja superior ejecutiva) — ej. dentro de un panel de Copiloto IA ("Lead Score: 87%").

**Cuándo utilizarlo.** Métricas secundarias, agrupadas dentro de otro contenedor (un panel, un
detalle de cliente).

**Cuándo NO utilizarlo.** Como sustituto de KPI Card en la franja principal de un dashboard —
Statistic Card es de menor jerarquía visual por diseño.

**Variantes.** Con barra de progreso inline (ej. "Intención de compra: Alta") / solo número +
etiqueta.

**Estados.** Los de KPI Card, en escala menor (`text-title-sm` en vez de `text-display`).

**Accesibilidad.** Igual que KPI Card.

**Responsive.** Se apila verticalmente dentro de su contenedor padre en mobile.

**Buenas prácticas.** Nunca más de 3 Statistic Cards seguidas sin un separador visual o
subtítulo — de lo contrario se leen como una lista plana, no como datos individuales.

**Errores comunes.** Confundir su jerarquía con la de KPI Card usando el mismo tamaño de
número — la diferencia de escala es lo que comunica "esto es de detalle, no ejecutivo".

**Relación con otros componentes.** Card especializada, hermana de KPI Card; vive
frecuentemente dentro de AI Insight y AI Summary.

## Badge

**Objetivo.** Indicador compacto de estado o conteo — ya construido y en uso en Gaso+
(`badge-count`, badges de estado de conversación).

**Cuándo utilizarlo.** Estado de un ítem (Pendiente, Resuelto), conteo (mensajes sin leer,
notificaciones).

**Cuándo NO utilizarlo.** Texto largo o descriptivo — eso es Tag, no Badge.

**Variantes.** Con punto de color (mínimo, solo indica presencia de estado) / con número
(conteo) / con texto corto (nombre del estado, fondo suave semántico).

**Estados.** No tiene estados propios interactivos (no es clicable) — solo representa datos.

**Accesibilidad.** El color nunca es la única señal — siempre acompañado de texto o forma (ver
Capítulo 3 del MDL, "ningún estado se comunica solo por color").

**Responsive.** Tamaño fijo en todos los breakpoints.

**Buenas prácticas.** Un conteo mayor a 99 se muestra como "99+", nunca el número exacto sin
límite de ancho.

**Errores comunes.** Usar más de un color semántico distinto por fila de Tabla — un exceso de
Badges de colores distintos en la misma fila vuelve a la tabla ilegible (relacionado con el
hallazgo ya identificado en la auditoría UX de Gaso+ sobre densidad de columnas).

**Relación con otros componentes.** Se superpone sobre Icon Button y Avatar (conteo de
notificaciones); usa la paleta semántica del Capítulo 4 del MDL.

## Tag

**Objetivo.** Etiqueta removible o descriptiva asociada a un ítem — a diferencia de Badge, sí
puede ser interactiva (removible, clicable como filtro).

**Cuándo utilizarlo.** Categorías, resultados de Multi Select, palabras clave asociadas a un
lead.

**Cuándo NO utilizarlo.** Indicar el estado de un proceso — eso es Badge.

**Variantes.** Solo lectura / removible (con ícono "x") / clicable (actúa como filtro rápido).

**Estados.** Reposo, hover, focus (si es interactiva), removiéndose (fade-out `motion-fast`
antes de desaparecer, nunca un salto instantáneo).

**Accesibilidad.** El ícono de remover tiene `aria-label="Quitar {nombre del tag}"`, nunca
genérico.

**Responsive.** Se envuelve en múltiples líneas (`flex-wrap`) en vez de truncar o generar
scroll horizontal.

**Buenas prácticas.** Color neutral por defecto — un Tag de color solo cuando el color
comunica una categoría real del negocio (ver Uso del color, Capítulo 4 del MDL).

**Errores comunes.** Usar Tag donde corresponde Badge (para representar estado de proceso) —
la diferencia no es solo visual, es de significado.

**Relación con otros componentes.** Resultado visual de Multi Select; hermano de Badge con
distinta semántica.

## Avatar

**Objetivo.** Representación visual de una persona o entidad — ya construido en Gaso+ (círculo
con iniciales, gradiente de marca).

**Cuándo utilizarlo.** Identificar un usuario, cliente o asesor en cualquier lista o
encabezado.

**Cuándo NO utilizarlo.** Representar un objeto sin identidad de persona (un canal, una
campaña) — eso usa un ícono, no un Avatar.

**Variantes.** Iniciales (default, sin foto disponible) / foto / con indicador de estado
(punto de disponibilidad, ver el patrón de "🟢 Disponible" ya construido).

**Estados.** No es interactivo por sí mismo salvo que actúe como disparador de un Menú (avatar
de perfil en Top Navigation).

**Accesibilidad.** `alt` con el nombre completo de la persona, nunca "avatar" genérico.

**Responsive.** Tres tamaños fijos (`24px` inline, `32px` estándar, `48px` encabezado de
perfil) — nunca un tamaño intermedio arbitrario.

**Buenas prácticas.** El color de fondo (cuando son iniciales) es determinístico por
persona (mismo algoritmo siempre da el mismo color a la misma persona), no aleatorio en cada
render.

**Errores comunes.** Indicador de estado (punto verde/gris) sin contraste suficiente contra el
color de fondo del Avatar — necesita un borde de 2px del color de superficie detrás para
separarse visualmente.

**Relación con otros componentes.** Compone Card, Top Navigation, listas de conversación
(Chat).

## Tooltip

**Objetivo.** Aclaración breve bajo demanda — nunca información esencial, siempre
complementaria.

**Cuándo utilizarlo.** Explicar un ícono sin texto (ver Icon Button), mostrar el valor
completo de un texto truncado.

**Cuándo NO utilizarlo.** Información que el usuario necesita para completar una tarea — eso
va en el propio formulario (texto de ayuda visible), nunca escondido en un Tooltip que
requiere hover.

**Variantes.** Solo texto / con atajo de teclado indicado (ej. "Buscar (⌘K)").

**Estados.** Oculto/visible, con `motion-instant` de retardo antes de aparecer (evita
parpadeo en hovers de paso).

**Accesibilidad.** Aparece también con foco de teclado, no solo con hover del mouse — de lo
contrario, la información es inalcanzable sin mouse.

**Responsive.** No existe hover real en touch — en mobile, se sustituye por mantener
presionado (`long press`) o se omite si la información no es crítica.

**Buenas prácticas.** Nunca más de una línea de texto — si necesita más, no es un Tooltip, es
contenido que merece su propio espacio visible.

**Errores comunes.** Tooltip sobre un elemento que ya tiene texto visible explicando lo mismo
— información duplicada sin necesidad.

**Relación con otros componentes.** Se activa sobre Icon Button, Avatar, texto truncado en
Tabla.

---

# Datos

## Tabla / Data Grid

**Objetivo.** Comparar muchos ítems del mismo tipo con los mismos atributos — el componente de
mayor densidad de información del sistema, y el que más disciplina de Capítulo 3
("Densidad de información") necesita.

**Cuándo utilizarlo.** Listas de más de ~10 ítems con atributos comparables entre sí (leads,
campañas, usuarios).

**Cuándo NO utilizarlo.** Menos de 10 ítems (una lista de Cards es más legible) o datos sin
estructura tabular real (eso es Conversation Timeline o una lista simple).

**Variantes.** **Tabla** — modo estándar, columnas fijas, sin control de usuario sobre
densidad. **Data Grid** — Tabla con Filtros, Ordenamiento y Paginación activados a la vez, para
conjuntos grandes que el usuario necesita explorar, no solo leer (ver el hallazgo ya
documentado sobre las 18 columnas de Métricas en Gaso+ — ese es exactamente el caso que un
Data Grid con columnas configurables resuelve).

**Estados.** Fila: reposo, hover, seleccionada (si hay Checkbox de selección), fila con
acción destacada (ej. lead urgente). Tabla completa: cargando (Skeleton con la misma cantidad
de filas visibles), vacía (Empty State inline), con error de carga (Alert inline).

**Accesibilidad.** Encabezados de columna correctamente asociados (`scope="col"`); orden de
lectura por lector de pantalla es fila por fila, no columna por columna.

**Responsive.** Por debajo de `sm`, la Tabla se transforma en una lista de Cards (una Card por
fila, con las columnas como pares etiqueta/valor apilados) — nunca scroll horizontal como
única solución mobile.

**Buenas prácticas.** Un set de columnas por defecto reducido, con el resto detrás de un
toggle "Mostrar todo" cuando hay más de ~7 columnas — mismo criterio ya identificado como
pendiente en la auditoría UX de Gaso+ (Métricas).

**Errores comunes.** Ordenar por una columna sin indicar visualmente cuál ni en qué dirección;
paginar sin mostrar el total real de resultados ("Página 2" sin decir "de cuántas").

**Relación con otros componentes.** Compone Badge, Avatar, Icon Button (acciones de fila),
Checkbox (selección), Paginación, Filtros, Ordenamiento, Empty State, Skeleton.

## Paginación

**Objetivo.** Dividir un conjunto grande de resultados en páginas navegables sin cargar todo
de una vez.

**Cuándo utilizarlo.** Resultados de Tabla/Data Grid que superan lo razonable de cargar y
renderizar de una vez (regla práctica: más de ~50-100 filas).

**Cuándo NO utilizarlo.** Conjuntos chicos donde cargar todo de una vez es más simple y no
afecta el rendimiento — paginar sin necesidad agrega un paso extra sin beneficio real.

**Variantes.** Numerada (con números de página, para conjuntos donde "saltar a la página 8" es
útil) / solo anterior/siguiente (para listas exploradas de forma secuencial, ej. una bandeja).

**Estados.** Página actual (resaltada, no clicable), páginas disponibles, deshabilitado en los
extremos (sin "anterior" en la página 1).

**Accesibilidad.** `aria-current="page"` en la página activa; anunciar el cambio de página a
lectores de pantalla.

**Responsive.** En mobile, versión compacta ("Página 2 de 14" + flechas), nunca todos los
números de página listados.

**Buenas prácticas.** Mantener el scroll en la parte superior de la lista al cambiar de
página, nunca dejar al usuario en la misma posición de scroll de la página anterior.

**Errores comunes.** Resetear filtros activos al cambiar de página — un cambio de página nunca
debe perder el contexto de filtrado/ordenamiento ya aplicado.

**Relación con otros componentes.** Vive dentro de Tabla/Data Grid, coordinada con Filtros y
Ordenamiento (los tres comparten el mismo estado de consulta).

## Filtros

**Objetivo.** Acotar un conjunto de datos a lo relevante para la tarea actual del usuario.

**Cuándo utilizarlo.** Cualquier Data Grid con más de una dimensión posible de segmentación
(estado, asesor, canal, fecha — igual que el rail de estados ya construido en Gaso+).

**Cuándo NO utilizarlo.** Conjuntos de datos ya acotados por naturaleza (ej. una lista que
solo puede tener 3 valores posibles no necesita un panel de filtros, alcanza con Tabs).

**Variantes.** Filtros rápidos inline (chips clicables arriba de la tabla) / panel de filtros
avanzados (Multi Select combinables, para más de 2-3 dimensiones a la vez).

**Estados.** Sin filtros activos / con N filtros activos (indicado con un contador), filtro
individual activo (resaltado).

**Accesibilidad.** El total de resultados tras aplicar filtros se anuncia, no solo se
actualiza visualmente.

**Responsive.** En mobile, los filtros avanzados se abren en overlay a pantalla completa —
mismo patrón que el botón flotante de filtros ya construido en Gaso+.

**Buenas prácticas.** Una acción "limpiar todos los filtros" siempre visible cuando hay al
menos uno activo.

**Errores comunes.** Combinaciones de filtros que producen 0 resultados sin explicar cuál de
los filtros activos es el responsable — el Empty State resultante debe sugerir qué filtro
aflojar.

**Relación con otros componentes.** Usa Select, Multi Select, Date Picker, Tag (chips de
filtro activo); coordinado con Paginación y Ordenamiento.

## Ordenamiento

**Objetivo.** Reorganizar un conjunto de datos según el atributo más relevante para la tarea
actual.

**Cuándo utilizarlo.** Cualquier Data Grid donde más de un criterio de orden tiene sentido
(fecha, prioridad, nombre).

**Cuándo NO utilizarlo.** Datos con un único orden lógico posible (ej. una línea de tiempo
estrictamente cronológica) — ahí el ordenamiento es fijo, no una opción del usuario.

**Variantes.** Por clic en encabezado de columna (Tabla/Data Grid) / por selector explícito
("Ordenar por: Más reciente") cuando no hay columnas visibles (ej. una lista de Cards).

**Estados.** Sin ordenar (orden por defecto del sistema), ascendente, descendente — indicado
siempre con una flecha visible, nunca solo un cambio de orden sin señal.

**Accesibilidad.** El criterio de orden activo se anuncia al cambiar ("Ordenado por fecha,
descendente").

**Responsive.** Igual comportamiento en todos los breakpoints — el ordenamiento no cambia de
mecánica entre desktop y mobile, solo su disparador visual (encabezado clicable vs. selector
explícito en la versión de Cards).

**Buenas prácticas.** El orden por defecto siempre es el más útil para la tarea principal de
esa vista (ej. leads: más reciente primero; equipo: mayor carga primero) — nunca alfabético
por defecto salvo que el alfabeto sea genuinamente lo más útil.

**Errores comunes.** Perder el criterio de orden al aplicar un nuevo filtro — deben coexistir,
no resetearse entre sí.

**Relación con otros componentes.** Vive dentro de Tabla/Data Grid, coordinado con Filtros y
Paginación.

---

# Feedback

## Alert

**Objetivo.** Comunicar información importante, persistente y contextual dentro del flujo de
la pantalla — a diferencia de Toast, no desaparece sola.

**Cuándo utilizarlo.** Advertencias o información que el usuario debe ver antes de continuar
(ej. "Este lead no tiene asesor asignado").

**Cuándo NO utilizarlo.** Confirmaciones de una acción que el usuario acaba de completar — eso
es Toast, no Alert.

**Variantes.** Informativo, éxito, advertencia, error (los 4 roles semánticos del Capítulo 4
del MDL) — cada uno con su ícono correspondiente, nunca solo color.

**Estados.** Visible / descartado (si es descartable) — nunca loading, un Alert es siempre
contenido estático.

**Accesibilidad.** `role="alert"` para los de tipo error/advertencia (anuncio inmediato al
lector de pantalla); los informativos usan `role="status"` (anuncio no interruptivo).

**Responsive.** Ancho completo del contenedor en cualquier breakpoint.

**Buenas prácticas.** Texto accionable cuando aplica ("Asigna un asesor" con enlace directo),
nunca solo la descripción del problema sin un siguiente paso.

**Errores comunes.** Apilar más de un Alert a la vez en la misma vista — si hay varios
problemas, se agrupan en uno solo con una lista, nunca varios bloques de Alert compitiendo.

**Relación con otros componentes.** Usa la paleta semántica e iconografía del MDL; puede
contener un Button de acción inline.

## Toast

**Objetivo.** Confirmación breve y no intrusiva de que una acción se completó — aparece,
comunica, desaparece sola.

**Cuándo utilizarlo.** Tras completar una acción que no necesita quedar documentada en
pantalla ("Guardado", "Cotización enviada").

**Cuándo NO utilizarlo.** Errores que requieren acción del usuario para resolverse — eso
necesita Alert o Modal, algo que no desaparezca solo antes de que el usuario pueda reaccionar.

**Variantes.** Simple (texto + ícono) / con acción rápida ("Deshacer").

**Estados.** Apareciendo (`motion-base`, entra desde el borde donde vive — normalmente
inferior derecha en desktop), visible, desapareciendo.

**Accesibilidad.** `role="status"`, `aria-live="polite"` — se anuncia sin interrumpir lo que
el lector de pantalla esté leyendo en ese momento.

**Responsive.** En mobile, aparece desde abajo, a ancho casi completo — nunca en una esquina
donde compite con el pulgar del usuario.

**Buenas prácticas.** Se mantiene visible el tiempo suficiente para leerse dos veces (mínimo
4 segundos), pausa su temporizador si el usuario pasa el mouse/toca sobre él.

**Errores comunes.** Múltiples Toasts apilados sin límite — máximo 3 visibles a la vez, el
resto entra en cola.

**Relación con otros componentes.** Nivel de elevación 4 (crítico) del Capítulo 3 del MDL.

## Modal

**Objetivo.** Interrumpir el flujo actual para una tarea acotada que requiere atención
completa antes de continuar.

**Cuándo utilizarlo.** Formularios cortos que no ameritan una pantalla propia, decisiones que
necesitan foco total (ver también Confirm Dialog para el caso específico de confirmación).

**Cuándo NO utilizarlo.** Tareas largas o de varios pasos — eso merece su propia pantalla, un
Modal nunca debe contener scroll interno extenso ni múltiples secciones colapsables.

**Variantes.** Centrado (default) / panel lateral deslizante (para tareas con más contexto
relacionado a la pantalla de fondo, ej. editar un lead sin perder de vista la lista).

**Estados.** Abriendo (`motion-slow`, con scrim de fondo), abierto, cerrando.

**Accesibilidad.** Atrapa el foco de teclado dentro del Modal mientras está abierto (`focus
trap`); `Esc` lo cierra salvo que haya cambios sin guardar (ahí dispara Confirm Dialog antes).

**Responsive.** En mobile, ocupa la pantalla completa en vez de flotar centrado con márgenes.

**Buenas prácticas.** Nunca más de un Modal abierto a la vez (ver regla de elevación del
Capítulo 3 del MDL — máximo dos niveles flotantes, y un segundo Modal sobre otro ya rompe esa
regla).

**Errores comunes.** Cerrar el Modal al hacer clic fuera cuando el usuario tiene cambios sin
guardar — necesita Confirm Dialog antes de descartar.

**Relación con otros componentes.** Puede contener cualquier componente de Formularios;
dispara o es disparado por Confirm Dialog.

## Confirm Dialog

**Objetivo.** Confirmar una acción irreversible o de alto impacto antes de ejecutarla — un
Modal especializado, deliberadamente mínimo.

**Cuándo utilizarlo.** Eliminar, cerrar sesión, cualquier acción que no se puede deshacer con
un simple "Deshacer" de Toast.

**Cuándo NO utilizarlo.** Acciones reversibles (esas no necesitan confirmación — agregarla sin
necesidad va contra "cada interacción reduce el esfuerzo mental", Capítulo 0 del MDL).

**Variantes.** Estándar (título + descripción + 2 botones) / con confirmación tipeada (para la
acción más destructiva del sistema — ej. escribir el nombre exacto antes de habilitar el
botón de eliminar).

**Estados.** Los de Modal; el botón de confirmación en color de error si la acción es
destructiva, primario si es neutra (ej. "cerrar sesión" no es lo mismo que "eliminar").

**Accesibilidad.** El foco inicial nunca está en el botón destructivo — arranca en "Cancelar"
o en el propio diálogo, para que confirmar por error (doble `Enter`) sea imposible.

**Responsive.** Igual que Modal.

**Buenas prácticas.** El texto del botón repite la acción exacta ("Eliminar lead", no
"Confirmar") — el usuario nunca debe adivinar qué va a pasar al presionar.

**Errores comunes.** Usarlo para acciones de bajo impacto solo "por si acaso" — el exceso de
confirmaciones enseña al usuario a hacer clic sin leer, que es exactamente lo que este
componente existe para evitar.

**Relación con otros componentes.** Variante especializada de Modal.

## Empty State

**Objetivo.** Explicar por qué una pantalla no tiene contenido y qué hacer al respecto — ya
construido en Gaso+ para el caso de un asesor sin leads asignados (ver auditoría UX, punto 4).

**Cuándo utilizarlo.** Cualquier lista, tabla o bandeja sin resultados — ya sea por falta de
datos reales o por un filtro sin coincidencias.

**Cuándo NO utilizarlo.** Errores de carga (eso es Alert) ni loading en curso (eso es Loading
o Skeleton).

**Variantes.** Primer uso (explica el mecanismo, ej. "los leads se asignan automáticamente") /
sin resultados de filtro (explica que es el filtro, no la ausencia total de datos, con acción
para limpiarlo).

**Estados.** No tiene estados propios — es contenido estático que reemplaza a la lista vacía.

**Accesibilidad.** El mensaje se anuncia al lector de pantalla igual que cualquier contenido
cargado — nunca un contenedor vacío silencioso.

**Responsive.** El ícono/ilustración se reduce o se omite en mobile si el espacio vertical es
limitado — el texto siempre se mantiene completo.

**Buenas prácticas.** Nunca solo "No hay datos." — siempre explica el mecanismo (por qué está
vacío) y, cuando aplica, ofrece una acción concreta (ver microcopy: "an invitation, not an
apology").

**Errores comunes.** Usar el mismo Empty State genérico para "sin datos todavía" y "sin
resultados de este filtro" — son situaciones distintas que necesitan mensajes distintos (ver
el propio caso ya resuelto en Gaso+, que distingue exactamente estos dos casos).

**Relación con otros componentes.** Vive dentro de Tabla/Data Grid, Chat (bandeja vacía),
Search Box (sin resultados).

## Loading

**Objetivo.** Comunicar que el sistema está procesando algo sin forma conocida de antemano
(una acción puntual, no una lista completa).

**Cuándo utilizarlo.** Acciones que tardan más de 400ms sin un layout de contenido que
anticipar (ver Capítulo 7 del MDL) — guardar, enviar, procesar.

**Cuándo NO utilizarlo.** Cargar contenido con forma conocida (una lista, una card) — eso usa
Skeleton, que además comunica mejor cuánto contenido está por llegar.

**Variantes.** Spinner inline (dentro de un Button, ver su estado loading) / spinner de
pantalla completa (solo para cargas iniciales de toda la vista, uso excepcional).

**Estados.** Visible mientras dura el proceso — sin estados propios adicionales.

**Accesibilidad.** `aria-busy="true"` en el contenedor que está cargando; el spinner lleva
`aria-label="Cargando"` o equivalente contextual.

**Responsive.** Mismo tamaño relativo en todos los breakpoints.

**Buenas prácticas.** Nunca girar a más de 1 vuelta por segundo (Capítulo 7 del MDL) — más
rápido comunica error, no velocidad.

**Errores comunes.** Mostrar un spinner para procesos de menos de 400ms — genera más ansiedad
que esperar en silencio (regla explícita del Capítulo 7 del MDL).

**Relación con otros componentes.** Estado de Button; alternativa a Skeleton según el
contexto.

## Skeleton

**Objetivo.** Anticipar la forma exacta del contenido que está por cargar, reduciendo la
sensación de espera — ver especificación completa en el Capítulo 7 del MDL.

**Cuándo utilizarlo.** Carga de contenido con forma conocida de antemano: una lista de Cards,
una Tabla, un Chat.

**Cuándo NO utilizarlo.** Acciones puntuales sin layout propio — eso es Loading (spinner).

**Variantes.** Tantas como formas de contenido existan — cada Skeleton replica exactamente la
geometría (alto de línea, radio) del contenido real que reemplaza, nunca un placeholder
genérico.

**Estados.** Animándose (barrido de brillo, loop de 1.5s) → desapareciendo (`cross-fade`,
`motion-base`) hacia el contenido real.

**Accesibilidad.** El contenedor lleva `aria-busy="true"` mientras el Skeleton está visible;
nunca leído carácter por carácter por un lector de pantalla (es decorativo, `aria-hidden` en
sus bloques internos).

**Responsive.** Replica el layout responsive del contenido real en cada breakpoint — un
Skeleton de Tabla en mobile debe anticipar ya el layout de Cards apiladas, no el de columnas
de desktop.

**Buenas prácticas.** Cantidad de bloques Skeleton igual a la cantidad de ítems esperada
(ej. si la página muestra 10 filas, el Skeleton muestra 10 bloques, no 3 ni 20).

**Errores comunes.** Dejar el Skeleton visible más de lo necesario "por consistencia" cuando
el contenido real ya está listo — el cross-fade debe dispararse en cuanto el dato llega, sin
demora artificial.

**Relación con otros componentes.** Reemplaza temporalmente a Tabla, Card, Chat, KPI Card
mientras cargan.

## Progress

**Objetivo.** Comunicar avance medible de un proceso de duración conocida — a diferencia de
Loading, sí sabe cuánto falta.

**Cuándo utilizarlo.** Subida de un archivo adjunto, progreso de una importación de datos.

**Cuándo NO utilizarlo.** Procesos de duración desconocida — eso es Loading, un Progress sin
avance real que se mueve solo para "parecer que algo pasa" es engañoso.

**Variantes.** Barra lineal (default) / circular (para espacios compactos, ej. junto a un
Attachment subiéndose).

**Estados.** 0-100%, completado (transición breve a un ícono de check antes de desaparecer),
con error (se detiene, cambia a color de error).

**Accesibilidad.** `role="progressbar"` con `aria-valuenow`/`aria-valuemax` actualizados en
tiempo real.

**Responsive.** Ancho fluido al contenedor en todos los breakpoints.

**Buenas prácticas.** El porcentaje numérico se muestra junto a la barra cuando el proceso
dura más de unos segundos — la barra sola no comunica "cuánto falta" con precisión suficiente.

**Errores comunes.** Barra que salta de forma no lineal (ej. queda en 90% mucho tiempo) sin
explicación — si el último tramo es más lento por naturaleza (procesamiento final), un texto
lo aclara ("Procesando...").

**Relación con otros componentes.** Vive dentro de Attachment durante la subida de un archivo.

---

# IA

*Principio rector de toda esta categoría: "la IA se ve, no se anuncia" (Capítulo 1 del MDL).
Ningún componente de esta sección grita "¡esto lo hizo la inteligencia artificial!" — todos
comparten el mismo ícono de marca sutil (chispa/destello, ver Capítulo 6 del MDL) como única
señal consistente, y ninguno interrumpe una tarea en curso del usuario (Capítulo 0, principio
2).*

## AI Suggestion Card

**Objetivo.** Presentar una sugerencia puntual de la IA como una acción concreta a tomar, no
como información a leer — la aplicación directa del principio "Maiek no muestra información,
ayuda a tomar decisiones".

**Cuándo utilizarlo.** Cuando la IA identifica una acción de alto valor y baja certeza
requerida (ej. "Llama primero a VAINSA" del mockup ya discutido).

**Cuándo NO utilizarlo.** Para mostrar datos objetivos sin interpretación — eso es Statistic
Card o KPI Card, no necesita el marco de "sugerencia".

**Variantes.** Con acción de un clic (ejecuta directo, ej. "Agendar llamada") / con acción que
abre un flujo (ej. "Generar cotización" abre un Modal).

**Estados.** Reposo, hover, descartada (el usuario la ignora — se retira sin fricción, nunca
insiste), ejecutada (transición breve a confirmación).

**Accesibilidad.** El origen de la sugerencia (que viene de IA, no de una regla fija del
sistema) se comunica en texto para lectores de pantalla, no solo con el ícono visual.

**Responsive.** Se apila como cualquier Card en mobile; nunca se oculta detrás de una
interacción adicional solo por ser de IA.

**Buenas prácticas.** Siempre acompañada de una razón visible en una línea ("porque lleva 3
días sin respuesta") — nunca una recomendación sin justificación, ver Capítulo 2 del MDL
("cómo toma decisiones").

**Errores comunes.** Mostrar más de 1-2 AI Suggestion Cards a la vez en la misma vista — el
exceso de sugerencias simultáneas es exactamente la ansiedad que el Capítulo 0 del MDL pide
evitar.

**Relación con otros componentes.** Es una Card especializada; puede incluir AI Confidence
Indicator y dispara Button/Modal al ejecutarse.

## AI Insight

**Objetivo.** Comunicar un patrón o hallazgo que el usuario no pidió explícitamente pero que
le conviene saber — más pasivo que AI Suggestion Card (no pide una acción, informa).

**Cuándo utilizarlo.** Observaciones de contexto ("Este cliente ya preguntó por este producto
hace 2 semanas") dentro de una vista de detalle.

**Cuándo NO utilizarlo.** Cuando el hallazgo sí requiere una decisión clara del usuario — en
ese caso es AI Suggestion Card, con una acción, no solo un dato.

**Variantes.** Inline (una línea dentro de otro componente, ej. dentro de Message Bubble) /
en bloque propio (dentro de un panel dedicado, ej. Copiloto IA).

**Estados.** Visible / descartado (algunos insights son descartables si dejan de ser
relevantes).

**Accesibilidad.** Mismo criterio que AI Suggestion Card — el origen IA se comunica en texto.

**Responsive.** Igual que cualquier bloque de texto corto — se apila normalmente.

**Buenas prácticas.** Un AI Insight nunca interrumpe (no es un modal ni un toast) — vive
integrado en el flujo normal de lectura de la pantalla.

**Errores comunes.** Presentar un Insight de baja confianza con el mismo peso visual que uno
de alta confianza — ver AI Confidence Indicator, la certeza debe ser visible cuando no es
alta.

**Relación con otros componentes.** Vive dentro de AI Summary, Conversation Timeline, Card de
detalle de cliente.

## AI Recommendation

**Objetivo.** Sugerir el producto, mensaje o siguiente paso más probable de generar un buen
resultado — la especialización de AI Suggestion Card para recomendaciones de venta/producto.

**Cuándo utilizarlo.** Sugerir un producto a ofrecer, una plantilla de mensaje, un momento
óptimo de contacto.

**Cuándo NO utilizarlo.** Decisiones que dependen de criterio humano no delegable (ej. cerrar
una negociación de precio) — la IA puede informar, nunca decide sola sobre eso (Capítulo 0,
"la IA asiste, nunca reemplaza el criterio").

**Variantes.** Recomendación única (una sola opción clara) / lista corta (2-3 opciones
rankeadas, cuando no hay una única respuesta obvia).

**Estados.** Los de AI Suggestion Card.

**Accesibilidad.** Igual que AI Suggestion Card.

**Responsive.** Igual que AI Suggestion Card.

**Buenas prácticas.** Cuando hay varias opciones, el orden refleja probabilidad real, no
orden alfabético ni de catálogo.

**Errores comunes.** Presentar una recomendación como si fuera la única opción posible sin
dejar una vía clara para que el usuario elija otra cosa — la IA sugiere, no decide por el
usuario.

**Relación con otros componentes.** Especialización de AI Suggestion Card.

## AI Summary

**Objetivo.** Condensar una conversación o historial largo en lo esencial — para que el
usuario entienda el contexto en segundos, no releyendo todo (ver "media mañana" del Capítulo 0
del MDL).

**Cuándo utilizarlo.** Al abrir una conversación con historial extenso, al ver el detalle de
un cliente con actividad acumulada.

**Cuándo NO utilizarlo.** Conversaciones cortas donde leer el historial completo ya toma
segundos — un resumen ahí agrega un paso sin necesidad.

**Variantes.** Compacto (2-3 líneas, siempre visible) / expandible (con detalle adicional bajo
demanda).

**Estados.** Generando (Loading o Skeleton según duración esperada), generado, desactualizado
(si hay mensajes nuevos desde que se generó — se marca visualmente, nunca se muestra un
resumen obsoleto como si fuera actual).

**Accesibilidad.** Se anuncia como resumen generado, distinguible del contenido original de la
conversación.

**Responsive.** Se mantiene visible y legible incluso en mobile — es, junto con Message
Bubble, de los contenidos más consultados en pantallas chicas.

**Buenas prácticas.** Siempre fechado/marcado con el momento hasta el cual resume — el usuario
necesita saber si el resumen incluye el último mensaje o no.

**Errores comunes.** Resumir con lenguaje técnico de sistema en vez del lenguaje de negocio
del usuario (ver Capítulo 2 del MDL, "cómo habla").

**Relación con otros componentes.** Vive en el encabezado de Chat/Conversation Timeline; puede
contener AI Insight.

## AI Confidence Indicator

**Objetivo.** Comunicar cuánta certeza tiene la IA sobre un dato o sugerencia — necesario para
que el usuario calibre cuánto confiar antes de actuar, sin tener que preguntarlo.

**Cuándo utilizarlo.** Junto a cualquier predicción, score o recomendación cuya certeza no sea
obviamente alta (Lead Score, intención de compra).

**Cuándo NO utilizarlo.** Datos objetivos y verificados (un conteo real, una fecha) — ahí no
hay "confianza", hay un hecho.

**Variantes.** Barra o porcentaje (para scores numéricos, ej. "87% · Muy alto") / etiqueta
categórica (Alta/Media/Baja, cuando el número exacto no aporta más que la categoría).

**Estados.** No tiene estados interactivos — es siempre de solo lectura.

**Accesibilidad.** El nivel de confianza se lee en texto, nunca solo por el largo de una
barra de color.

**Responsive.** Mismo tamaño relativo en todos los breakpoints.

**Buenas prácticas.** Un umbral mínimo de confianza por debajo del cual la IA directamente no
muestra la sugerencia en vez de mostrarla con baja confianza — ver Capítulo 0, "la IA nunca
interrumpe, aparece solo cuando agrega valor" (una sugerencia de baja confianza casi nunca
agrega valor).

**Errores comunes.** Usar los mismos colores del sistema semántico (éxito/error) para
confianza — confianza no es lo mismo que éxito/fracaso, necesita su propia escala neutra
(ver escala tonal de un solo color en vez de la paleta semántica completa).

**Relación con otros componentes.** Acompaña a KPI Card, Statistic Card, AI Recommendation.

## AI Action Panel

**Objetivo.** Agrupar las acciones asistidas por IA disponibles para el contexto actual — el
componente contenedor de más alto nivel de esta categoría, equivalente al "Copiloto IA" del
mockup ya discutido.

**Cuándo utilizarlo.** Como panel lateral dentro de una vista de detalle (conversación,
cliente) donde varias capacidades de IA aplican a la vez.

**Cuándo NO utilizarlo.** Cuando solo hay una sugerencia puntual — ahí alcanza con AI
Suggestion Card sola, un panel completo sería sobredimensionado.

**Variantes.** Expandido (panel lateral completo) / colapsado (solo el ícono de marca IA, se
expande bajo demanda — nunca ocupa espacio permanente si el usuario no lo está usando).

**Estados.** Colapsado/expandido, generando contenido (Skeleton por sección), con acciones
listas.

**Accesibilidad.** Colapsable y expandible completamente por teclado; su estado (colapsado/
expandido) se anuncia.

**Responsive.** En mobile, se convierte en una hoja inferior accesible bajo demanda, nunca un
panel fijo que reduce el espacio de trabajo principal (chat) en una pantalla ya angosta.

**Buenas prácticas.** El panel nunca se auto-expande sin que el usuario lo pida — mismo
principio de "la IA nunca interrumpe" aplicado a nivel de layout completo, no solo de
contenido.

**Errores comunes.** Convertir el panel en la única forma de acceder a una acción — toda
acción disponible ahí (agendar, cotizar) también debe ser alcanzable por el flujo manual
normal, la IA acelera, nunca bloquea.

**Relación con otros componentes.** Contenedor de AI Suggestion Card, AI Recommendation, AI
Summary, Statistic Card, Quick Actions.

---

# Conversación

## Chat

**Objetivo.** El espacio central de trabajo de Maiek AI — donde una conversación se convierte
en un acuerdo (Capítulo 0 del MDL). Ya construido en Gaso+ (WebSocket en vivo, indicador de
escribiendo, adjuntos, catálogos) — este componente documenta el patrón, no reemplaza esa
implementación.

**Cuándo utilizarlo.** Cualquier intercambio de mensajes entre el cliente y Maiek AI (Gabi o
un asesor humano).

**Cuándo NO utilizarlo.** Notas internas del equipo sin cliente involucrado — eso necesita su
propio patrón (fuera de alcance de este catálogo), no el mismo componente de Chat orientado a
cliente.

**Variantes.** Vista completa (lista de conversaciones + chat abierto, ver mockup de "Bandeja
directa") / vista de detalle (chat solo, dentro de otra pantalla con más contexto alrededor,
ej. junto al resumen de cliente).

**Estados.** Cargando historial (Skeleton), con mensajes, escribiendo (Typing Indicator),
enviando (el mensaje propio aparece optimista, con un estado sutil de "enviando" hasta
confirmarse), error de envío (reintento inline, nunca el mensaje desaparece silenciosamente).

**Accesibilidad.** Los mensajes nuevos se anuncian sin robar el foco de lo que el usuario esté
haciendo (campo de respuesta); orden de lectura cronológico.

**Responsive.** En mobile, pantalla completa dedicada al chat (patrón ya construido en
Gaso+ — lista y rail se ocultan al abrir una conversación).

**Buenas prácticas.** El scroll se mantiene al final al recibir un mensaje nuevo SOLO si el
usuario ya estaba mirando el final — si había subido a leer historial, un mensaje nuevo no
lo interrumpe arrastrándolo de vuelta abajo (se muestra un indicador discreto de "nuevo
mensaje" en su lugar).

**Errores comunes.** Recargar toda la conversación ante cada mensaje nuevo en vez de solo
agregar el mensaje entrante — mismo tipo de problema ya diagnosticado y corregido este año en
Gaso+ (el bug del self-refresh-loop).

**Relación con otros componentes.** Compone Message Bubble, Typing Indicator, Attachment,
Quick Actions, Text Area (campo de respuesta), AI Summary (resumen de la conversación).

## Conversation Timeline

**Objetivo.** Vista cronológica de eventos relacionados a un cliente que van más allá de
mensajes de chat — cambios de estado, citas agendadas, cotizaciones enviadas.

**Cuándo utilizarlo.** Historial completo de interacción con un cliente, para contexto de
supervisor o de un asesor retomando un caso.

**Cuándo NO utilizarlo.** Para los mensajes de chat en sí — eso vive en Chat/Message Bubble;
Timeline es para eventos de negocio, no para la conversación palabra por palabra.

**Variantes.** Completo (todos los tipos de evento) / filtrado por tipo (solo cambios de
estado, por ejemplo).

**Estados.** Cargando (Skeleton), con eventos, vacío (Empty State — cliente nuevo sin
historial de eventos aún).

**Accesibilidad.** Marcado como lista temporal, con la fecha de cada evento asociada
explícitamente al evento (no solo agrupada visualmente).

**Responsive.** Se mantiene como línea vertical con eventos en mobile, solo se reduce el
padding — nunca se convierte en una tabla horizontal ilegible.

**Buenas prácticas.** Eventos generados por IA (ver AI Insight) se distinguen visualmente de
eventos generados por acción humana directa, con el mismo ícono de marca sutil ya establecido.

**Errores comunes.** Mezclar eventos de negocio y mensajes de chat en la misma línea temporal
sin distinción visual clara — son dos tipos de contenido distintos aunque compartan orden
cronológico.

**Relación con otros componentes.** Puede contener AI Insight; convive con Chat en una vista
de detalle de cliente (ver Capítulo de Layout en el "Próximo Entregable" — patrones de
producto, todavía no construidos).

## Message Bubble

**Objetivo.** Unidad visual de un mensaje individual — el átomo del Chat, ya construido en
Gaso+ con 3 roles distintos (cliente, Gabi, asesor).

**Cuándo utilizarlo.** Cada mensaje individual dentro de Chat.

**Cuándo NO utilizarlo.** Contenido que no es un mensaje conversacional (un evento de
Timeline, un resumen de AI Summary) — esos tienen su propio componente, aunque compartan la
línea de tiempo visual.

**Variantes.** Cliente (fondo neutro, alineado a la izquierda), Gabi/IA (fondo con matiz de
marca sutil, alineado a la derecha), Asesor humano (fondo distinto al de Gabi — la distinción
entre "respondió la IA" y "respondió una persona" debe seguir siendo visible, mismo criterio
ya implementado en Gaso+), con adjunto (contiene Attachment en vez de o además de texto).

**Estados.** Enviado, entregado, leído (cuando exista la migración de recibos de lectura ya
identificada como pendiente en Gaso+), fallido (con reintento).

**Accesibilidad.** El remitente de cada mensaje se anuncia (no solo se infiere por la
alineación visual, que un lector de pantalla no percibe).

**Responsive.** Ancho máximo del 72% del contenedor en desktop, hasta 85% en mobile (más
espacio relativo disponible para el texto en pantallas angostas).

**Buenas prácticas.** Mensajes consecutivos del mismo remitente en un lapso corto se agrupan
visualmente (menos separación entre ellos, un solo avatar para el grupo) — evita ruido
repetitivo.

**Errores comunes.** Perder la distinción visual entre remitente humano y remitente IA cuando
ambos "asesor" y "Gabi" comparten alineación — esa distinción es explícitamente un principio
de marca (Capítulo 1, "la IA se ve, no se anuncia" — se ve, pero se distingue).

**Relación con otros componentes.** Átomo de Chat; puede contener Attachment, AI Insight
inline.

## Typing Indicator

**Objetivo.** Comunicar que la otra parte está escribiendo en este momento — ya construido en
Gaso+ vía WebSocket, tanto para el cliente (WhatsApp) como entre miembros del equipo.

**Cuándo utilizarlo.** Dentro de Chat, cuando el sistema tiene la señal en tiempo real de que
alguien está componiendo una respuesta.

**Cuándo NO utilizarlo.** Como sustituto de Loading para procesos que no son de escritura
humana real (ej. la IA "pensando" antes de responder usa su propio patrón, no este).

**Variantes.** Del cliente hacia el sistema / de un asesor hacia otro (uso interno, ya
construido) — visualmente iguales, distinto contexto de aparición.

**Estados.** Visible mientras dura la señal (con timeout de unos segundos si la señal deja de
recibirse sin un evento explícito de "dejó de escribir").

**Accesibilidad.** Anunciado como cambio de estado ("María está escribiendo"), no solo con la
animación de puntos.

**Responsive.** Igual en todos los breakpoints — vive dentro de Chat, que ya es responsive
por sí mismo.

**Buenas prácticas.** Se retira automáticamente en cuanto llega el mensaje real — nunca
convive con el mensaje ya recibido ni un instante de más.

**Errores comunes.** Dejarlo visible indefinidamente si la conexión en tiempo real se pierde
sin avisar — necesita un timeout razonable (unos segundos) para autolimpiarse.

**Relación con otros componentes.** Vive dentro de Chat, justo antes de donde aparecerá el
próximo Message Bubble.

## Attachment

**Objetivo.** Representar un archivo adjunto (imagen, documento, audio) dentro de una
conversación — ya construido en Gaso+ para catálogos, imágenes y notas de voz.

**Cuándo utilizarlo.** Cualquier archivo enviado o recibido dentro de Chat.

**Cuándo NO utilizarlo.** Enlaces de texto simples sin archivo real asociado — eso es solo
texto con un enlace, no necesita el tratamiento visual de Attachment.

**Variantes.** Imagen (miniatura expandible), documento (ícono + nombre + tamaño), audio
(reproductor inline, ya construido con barra de progreso), en proceso de subida (con
Progress).

**Estados.** Subiendo (Progress), listo, error de subida (con reintento), descargando (si
aplica).

**Accesibilidad.** Nombre de archivo y tipo siempre legibles por lector de pantalla, no solo
representados por un ícono.

**Responsive.** Las miniaturas de imagen se ajustan a un tamaño máximo fijo en cualquier
breakpoint — nunca ocupan el ancho completo del chat en mobile, mismo criterio de "no competir
con el texto" que rige toda la interfaz.

**Buenas prácticas.** El peso del archivo se muestra siempre para documentos (ayuda a decidir
si descargar en una conexión limitada) — no así para imágenes chicas, donde no aporta.

**Errores comunes.** No mostrar el estado de error de forma clara cuando una subida falla —
un adjunto que "desaparece" silenciosamente ante un error de red es la peor experiencia
posible para este componente.

**Relación con otros componentes.** Vive dentro de Message Bubble; usa Progress durante la
subida.

## Quick Actions

**Objetivo.** Ofrecer las acciones más probables dentro del contexto actual de una
conversación sin que el usuario tenga que salir del chat a buscarlas — ver el patrón "Cotizar
producto / Enviar catálogo / Agendar llamada" del mockup ya discutido, y el selector de
catálogos ya construido en Gaso+.

**Cuándo utilizarlo.** Barra de acciones contextuales sobre el campo de respuesta del Chat.

**Cuándo NO utilizarlo.** Acciones que no son específicas de una conversación (esas van en
navegación normal, no como Quick Action).

**Variantes.** Fijas (siempre las mismas, ej. adjuntar/catálogo) / sugeridas por IA (cambian
según el contexto de la conversación, ej. "Agendar llamada" aparece solo cuando la
conversación lo amerita).

**Estados.** Reposo, hover, activa/ejecutándose, deshabilitada (ej. "Generar cotización" sin
producto identificado todavía en la conversación).

**Accesibilidad.** Cada acción tiene `aria-label` claro; alcanzable por teclado en la barra
antes de llegar al campo de texto.

**Responsive.** En mobile, se comprimen a solo íconos con Tooltip (mantener presionado para
ver la etiqueta), en vez de texto + ícono como en desktop.

**Buenas prácticas.** Máximo 4-5 acciones visibles a la vez — el resto, si existe, va detrás
de un Menú de "más acciones", nunca una barra que crece sin límite.

**Errores comunes.** Mezclar Quick Actions fijas y sugeridas por IA sin distinción visual —
una acción que "aparece de la nada" sugerida por IA debe notarse distinta de una que siempre
estuvo ahí (mismo ícono de marca sutil del Capítulo 6 del MDL).

**Relación con otros componentes.** Vive dentro de Chat, junto al campo de Text Area de
respuesta; puede disparar AI Suggestion Card, Modal (cotización), Attachment (catálogo).

---

# Matriz de principios

En vez de una grilla de 48 componentes × 10 principios (ilegible en la práctica), esta matriz
va en el sentido inverso: por cada principio del Capítulo 0 del MDL, qué componentes lo
expresan de forma más directa — la lectura más útil para quien esté diseñando y necesite
recordar "¿qué principio debería estar gobernando esta decisión ahora mismo?".

| Principio (Capítulo 0 del MDL) | Componentes donde se expresa más directamente |
|---|---|
| 1. Maiek ayuda a decidir, no solo muestra | AI Suggestion Card, AI Recommendation, KPI Card |
| 2. La IA nunca interrumpe | AI Action Panel, AI Insight, Toast (nunca Modal para IA no solicitada) |
| 3. Una sola pregunta: siguiente mejor acción | AI Suggestion Card, Empty State, Button (Primary único) |
| 4. Menos elementos, más claridad | Card, Tabla/Data Grid (columnas por defecto), Menús (máx. 7 ítems) |
| 5. El espacio vacío también comunica | Empty State, Card, KPI Card |
| 6. Construido, nunca decorado | Todos — especialmente Alert, Badge, Tag (sin color sin significado) |
| 7. Tranquilidad, nunca ansiedad | Badge (nunca contadores agresivos), Toast, AI Confidence Indicator |
| 8. La simplicidad siempre gana | Switch vs. formulario, Confirm Dialog (uso mínimo), Select vs. Multi Select |
| 9. Consistencia sobre novedad | Button (variantes, no componentes distintos), Tabla/Data Grid |
| 10. Reduce el esfuerzo mental | Search Box (debounce), Paginación (mantiene contexto), Quick Actions |

---

# Componentes recomendados para implementar primero

Orden pensado para el refactor real del frontend de Gaso+ — no por categoría del catálogo,
sino por dependencia real: los primeros son los que **todos los demás componentes necesitan**
para existir; los últimos son los que **dependen de que los anteriores ya estén listos**.

**Nivel 0 — Fundamento absoluto (nada más se puede construir sin esto).**
1. Button
2. Text Input
3. Card
4. Badge
5. Avatar

**Nivel 1 — Estructura de cualquier pantalla de trabajo.**
6. Tabla / Data Grid
7. Empty State
8. Loading
9. Skeleton
10. Modal
11. Toast

**Nivel 2 — Identidad central del producto (el Chat es, literalmente, lo que Gaso+ ya es hoy —
refactor de lo existente sobre los nuevos tokens, no construcción desde cero).**
12. Message Bubble
13. Chat
14. Typing Indicator
15. Attachment
16. Quick Actions

**Nivel 3 — Lo que habilita el dashboard nuevo (KPIs + Copiloto IA) ya discutido.**
17. KPI Card
18. Statistic Card
19. AI Suggestion Card
20. AI Confidence Indicator
21. AI Summary
22. AI Insight
23. AI Recommendation
24. AI Action Panel

**Nivel 4 — Shell de navegación (se refactoriza una vez el contenido interno ya usa los
componentes nuevos, para no reconstruir dos veces).**
25. Sidebar
26. Top Navigation
27. Tabs
28. Breadcrumb
29. Menús

**Nivel 5 — Resto de formularios y controles de datos, según necesidad puntual de cada
pantalla (sin orden de dependencia fuerte entre ellos).**
30. Select, Multi Select, Checkbox, Radio, Switch, Date Picker, Search Box, Text Area
31. Filtros, Ordenamiento, Paginación
32. Tag, Tooltip
33. Alert, Confirm Dialog, Progress
34. Icon Button, Floating Action Button
35. Conversation Timeline
