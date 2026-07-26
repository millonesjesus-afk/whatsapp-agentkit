# Maiek AI — Design Language (MDL) v1.0

> Depende de [`MAIEK_AI_FRAMEWORK.md`](MAIEK_AI_FRAMEWORK.md) y
> [`MAIEK_AI_PLATFORM_ARCHITECTURE.md`](MAIEK_AI_PLATFORM_ARCHITECTURE.md).
>
> **Fase 1 — Foundations.** Este documento define los cimientos del lenguaje visual: filosofía,
> layout, elevación, movimiento, color y tipografía. Deliberadamente NO incluye componentes
> (botones, inputs, tablas, cards) — eso es la Fase 2, todavía no construida.
>
> **Estado: guardado solo como referencia.** Todavía NO está aplicado al panel de Gaso+ — el
> panel actual sigue usando su paleta propia (`#00A1DE` navbar/primario, `#075E85` oscuro,
> `#3CCBDA` secundario). No aplicar estos valores al CSS real hasta que se confirme
> explícitamente.

## Filosofía de diseño

Maiek AI no diseña pantallas de software — diseña el espacio donde una conversación se
convierte en un acuerdo. Cada decisión visual se subordina a esa función: nada compite con la
conversación, todo la sostiene.

El lenguaje visual toma como referencia funcional (nunca como plantilla a copiar) a Apple,
Linear, Notion, Arc Browser, Raycast, Vercel y Stripe Dashboard — productos que comparten un
mismo instinto: quitar antes que agregar, confiar en el espacio en blanco, dejar que la
tipografía y la jerarquía hagan el trabajo que otros productos delegan en color y decoración.

Se rechaza explícitamente el vocabulario visual de Material Design, HubSpot, Salesforce y Zoho
— chrome denso, sombras pesadas sobre cada tarjeta, paletas de badges saturadas, iconografía
inconsistente, exceso de líneas divisorias. Un producto de Maiek AI se reconoce por lo que NO
tiene tanto como por lo que tiene.

## Principios del lenguaje visual

- **Silencio antes que ruido.** Cada elemento adicional en pantalla tiene que ganarse su lugar;
  el estado por defecto de cualquier decisión de diseño es no agregar nada.
- **Precisión antes que decoración.** Un borde de 0.5px comunica más orden que una sombra de
  8px. La geometría es exacta, no aproximada.
- **Una sola voz de acento.** El color de marca aparece donde el usuario debe actuar — nunca
  como fondo decorativo ni para llenar espacio vacío.
- **Profundidad con propósito.** La elevación (sombra, blur, superposición) existe solo para
  comunicar orden de interacción (qué está por encima de qué), nunca como estilo.
- **Movimiento con intención.** Ninguna animación es gratuita; cada una explica una relación
  causa-efecto entre la acción del usuario y el cambio en pantalla.
- **Consistencia sobre novedad.** Un patrón ya resuelto en una pantalla se reutiliza tal cual
  en la siguiente — la familiaridad es una característica, no una limitación creativa.

## Valores de la interfaz

| Valor | Cómo se traduce en la interfaz |
|---|---|
| Inteligencia | La interfaz anticipa, resume, prioriza — nunca obliga al usuario a hacer el trabajo que un sistema inteligente puede hacer por él. |
| Confianza | Estados predecibles, feedback inmediato, cero sorpresas — el usuario siempre sabe qué va a pasar antes de que pase. |
| Precisión | Alineación exacta a la grilla, tipografía tabular en números, cero elementos "a ojo". |
| Simplicidad | La opción por defecto siempre es la más simple de las alternativas válidas. |
| Tecnología premium | Detalles ejecutados con exactitud (blur correcto, timing correcto, contraste correcto) — la calidad se siente antes de poder nombrarse. |
| Cercanía humana | El tono nunca es frío ni corporativo; la precisión no está reñida con la calidez — ver Microcopy en `MAIEK_AI_FRAMEWORK.md`. |

## Personalidad de Maiek AI

La identidad se organiza alrededor del claim oficial — **"Conecta. Comprende. Cierra."** —
como tres modos de personalidad de la interfaz, no como tres pantallas distintas:

- **Conecta** → la interfaz se siente integradora: canales, personas y datos conviven sin
  fricción visual entre ellos (mismo lenguaje de avatar, badge y estado en todas partes).
- **Comprende** → la interfaz se siente atenta: prioriza, resume, resalta lo que importa antes
  de que el usuario tenga que buscarlo.
- **Cierra** → la interfaz se siente decisiva: la acción principal de cada pantalla es siempre
  inequívoca, con un solo camino evidente hacia adelante.

Inspirada en la greca escalonada Muchik del isotipo: geometría exacta, repetición ordenada,
sin curvas arbitrarias. Esa misma disciplina geométrica gobierna la grilla y el radio de
bordes de todo el sistema.

## Grid

Unidad atómica: **8px**. Todo margen, padding, alto de fila o tamaño de ícono es múltiplo de
8px (con 4px como sub-unidad permitida para ajustes finos de texto/ícono). Nunca valores
arbitrarios como 15px o 22px.

Layout de escritorio: grilla fluida de **12 columnas**, gutter de 24px, ancho máximo de
contenido **1440px** centrado — más allá de eso, el exceso de espacio se reparte como margen
lateral, nunca estirando componentes de contenido (tablas, cards) a un ancho incómodo de leer.

## Sistema de espaciados

Escala de 4px con 12 pasos, con nombre semántico para uso consistente en código:

| Token | Valor | Uso típico |
|---|---|---|
| `space-1` | 4px | separación entre ícono y texto en línea |
| `space-2` | 8px | padding interno de controles pequeños |
| `space-3` | 12px | padding interno de controles estándar |
| `space-4` | 16px | separación entre elementos relacionados |
| `space-5` | 20px | padding interno de cards |
| `space-6` | 24px | separación entre grupos dentro de una sección |
| `space-7` | 32px | separación entre secciones |
| `space-8` | 40px | padding de contenedores principales |
| `space-9` | 48px | separación entre bloques mayores de página |
| `space-10` | 64px | márgenes de layout en desktop |
| `space-11` | 96px | separación editorial (landing, onboarding) |
| `space-12` | 128px | aire alrededor de estados vacíos / momentos hero |

## Sistema de columnas

Desktop: 12 columnas fluidas, gutter 24px. Tablet: 8 columnas, gutter 20px. Mobile: 4
columnas, gutter 16px. Ningún layout fuerza un componente a ocupar una fracción de columna
que no sea un múltiplo entero (nunca "2.5 columnas") — si no calza, se rediseña el bloque, no
se fuerza la grilla.

## Breakpoints

| Nombre | Ancho | Contexto |
|---|---|---|
| `xs` | 480px | mobile |
| `sm` | 768px | tablet vertical |
| `md` | 1024px | tablet horizontal / laptop chico |
| `lg` | 1280px | desktop estándar |
| `xl` | 1536px | desktop ancho |

Desktop-first en la filosofía (ver Responsive Philosophy), pero cada breakpoint es un punto de
verificación real, no un recorte improvisado del layout de escritorio.

## Sistema de elevaciones

Cinco niveles, cada uno con un trabajo específico — nunca elevación "porque sí":

| Nivel | Nombre | Uso |
|---|---|---|
| 0 | Base | superficie de página y de card en reposo — sin sombra |
| 1 | Hover | tarjeta o fila al pasar el mouse — sombra apenas perceptible |
| 2 | Flotante | dropdown, popover, menú contextual |
| 3 | Superpuesto | modal, panel lateral, diálogo |
| 4 | Crítico | toast, notificación, alerta que exige atención inmediata |

Regla dura: nunca más de **dos** niveles de elevación flotante activos a la vez en pantalla —
un tercer elemento flotante significa que el flujo está mal diseñado, no que hace falta un
nivel más.

## Sistema de sombras

Sombras siempre neutras (nunca de color), de doble capa (contacto + difusa), muy sutiles —
el objetivo es separar planos, no decorar:

| Nivel | `box-shadow` |
|---|---|
| 1 | `0 1px 2px rgba(11,29,58,0.06)` |
| 2 | `0 4px 12px rgba(11,29,58,0.08), 0 1px 3px rgba(11,29,58,0.06)` |
| 3 | `0 12px 32px rgba(11,29,58,0.12), 0 2px 6px rgba(11,29,58,0.08)` |
| 4 | `0 20px 48px rgba(11,29,58,0.16), 0 4px 10px rgba(11,29,58,0.10)` |

El color base de la sombra usa el navy de marca (`#0B1D3A`) a baja opacidad en vez de negro
puro — una sombra tibia en vez de una sombra gris genérica.

## Border radius

Escala corta, deliberadamente contenida — geometría exacta, nunca "burbujeante":

| Token | Valor | Uso |
|---|---|---|
| `radius-sm` | 6px | controles pequeños, chips |
| `radius-md` | 10px | controles estándar (default) |
| `radius-lg` | 14px | cards |
| `radius-xl` | 20px | superficies grandes, modales |
| `radius-full` | 999px | avatares, pills, badges |

Nunca radios intermedios fuera de esta escala, y nunca radio en un solo lado sin justificar
por qué (un borde con un solo lado redondeado casi siempre es un error de composición).

## Motion — filosofía, timing y curvas

**Filosofía:** el movimiento explica, nunca decora. Toda animación responde a una de estas
preguntas: ¿de dónde vino este elemento? ¿a dónde va? ¿qué relación tiene con lo que el
usuario acaba de hacer? Si una animación no responde ninguna, se elimina.

**Timing:**

| Token | Duración | Uso |
|---|---|---|
| `motion-instant` | 100ms | hover, focus, cambios de color |
| `motion-fast` | 150ms | toggles, checkboxes, micro-interacciones |
| `motion-base` | 220ms | transiciones estándar (aparecer/desaparecer, expandir) |
| `motion-slow` | 350ms | paneles, modales, cambios de vista completos |

Nunca superar 400ms en una interacción funcional — por encima de eso, el usuario percibe
lentitud, no elegancia. Duraciones mayores solo se permiten en momentos editoriales puntuales
(onboarding, celebración de un cierre de venta), nunca en el uso diario.

**Curvas:**

| Token | `cubic-bezier` | Uso |
|---|---|---|
| `ease-out-expo` | `(0.16, 1, 0.3, 1)` | entradas — el elemento llega con energía y frena suave |
| `ease-in-out-soft` | `(0.65, 0, 0.35, 1)` | transiciones simétricas (cambios de estado, cross-fade) |
| `ease-spring` | `(0.34, 1.56, 0.64, 1)` | momentos de confirmación puntuales (con overshoot) — uso escaso, nunca en navegación rutinaria |

## Blur y transparencias

El blur se reserva para **overlays**, nunca para contenido primario — un panel de comando
(estilo Raycast/Arc) o un scrim detrás de un modal, no una card de datos.

| Contexto | Blur | Opacidad de scrim |
|---|---|---|
| Popover sobre contenido denso | 8px | — |
| Command palette / búsqueda global | 16px | fondo a 45% |
| Modal sobre la app completa | 24px | fondo a 55% |

Transparencias de superficie (glass) solo en overlays temporales — ningún panel permanente de
la interfaz (sidebar, header, tabla) usa transparencia; deben leerse sólidos y estables.

## Jerarquía visual y contraste

La jerarquía se construye en este orden de prioridad — tamaño y peso tipográfico primero,
color después, y borde/sombra en último lugar:

1. Tamaño y peso de fuente.
2. Posición y proximidad (lo relacionado está cerca).
3. Color (acento reservado solo para lo accionable).
4. Contorno o fondo (el último recurso, no el primero).

Contraste mínimo AA (4.5:1 para texto de cuerpo, 3:1 para texto grande/UI) en ambos modos,
claro y oscuro — ver Accesibilidad.

## White space

El espacio en blanco es un componente, no un residuo. Regla práctica: si una pantalla se
siente "vacía" al 70% de densidad de información real, está bien — la alternativa (llenar el
espacio con relleno visual) siempre es peor que dejarlo respirar. El espacio en blanco es lo
que permite que la única acción importante de la pantalla se note sin competencia.

## Uso del color

El color de marca (azul tecnológico) se reserva para **lo accionable**: el control primario de
cada pantalla, el estado activo de navegación, los enlaces. Nunca se usa como fondo decorativo
de secciones enteras. El dorado (isotipo) es un acento de marca, no un color funcional — no se
usa en botones, badges de estado ni gráficos de datos.

Los colores semánticos (éxito, advertencia, error, información) son un sistema aparte del
color de marca — nunca se reutiliza el azul de marca para "información" ni el dorado para
"advertencia": mezclar identidad con semántica es la fuente más común de inconsistencia en
sistemas de diseño grandes.

## Paleta oficial

Colores de identidad, definidos por el moodboard de marca:

| Uso | Hex | Nombre |
|---|---|---|
| Primario (interactivo) | `#1677FF` | Azul tecnológico |
| Secundario | `#38BDF8` | Celeste |
| Texto / superficie oscura de marca | `#0B1D3A` | Azul navy |
| Acento de marca (isotipo, uso escaso) | `#C6A66B` | Dorado |
| Fondo | `#F2F4F7` | Gris claro |

## Escalas tonales

Cada color de marca se expande en una escala de 7 pasos (50 = tinte más claro, 900 = sombra
más oscura) para poder construir estados (hover, fondos suaves, texto sobre color) sin salirse
de la paleta. Valores indicativos — a afinar con herramienta de color en la implementación:

**Azul tecnológico** (primario)
`50` `#E9F1FF` · `100` `#CCE1FF` · `200` `#99C2FF` · `400` `#4D96FF` · `600` `#1677FF` · `800` `#0F56BF` · `900` `#0A3D87`

**Celeste** (secundario)
`50` `#EDFAFF` · `100` `#D3F3FE` · `200` `#A6E7FD` · `400` `#62D0FA` · `600` `#38BDF8` · `800` `#1B8FC2` · `900` `#146A92`

**Navy** (texto de marca)
`50` `#EBEFF5` · `100` `#D3DCE9` · `200` `#A8BAD4` · `400` `#375D93` · `600` `#16345C` · `800` `#0F2647` · `900` `#0B1D3A`

**Dorado** (acento)
`50` `#FBF6EE` · `100` `#F3E7D2` · `200` `#E6CFA5` · `400` `#D4B888` · `600` `#C6A66B` · `800` `#9C7F4C` · `900` `#6E5A34`

**Neutral** (fondo, texto secundario, bordes — anclado en el mismo matiz navy para no leerse gris genérico)
`0` `#FFFFFF` · `50` `#F2F4F7` · `100` `#E7EAEF` · `200` `#D2D7E0` · `400` `#9AA3B2` · `600` `#626C7E` · `800` `#384152` · `900` `#1B222E`

**Semánticos** (bg suave / sólido / texto — sistema aparte de la identidad, ver Uso del color)

| Rol | Fondo suave | Sólido | Texto sobre fondo suave |
|---|---|---|---|
| Éxito | `#E3F5EA` | `#00A34B` | `#0F6E3B` |
| Advertencia | `#FEF3DC` | `#FAB200` | `#8A5B00` |
| Error | `#FCEAEA` | `#EF4444` | `#9E1F1F` |
| Información | `#E9F1FF` | `#1677FF` | `#0F56BF` |

## Tipografía

Principal (títulos y marca): **Poppins**. Cuerpo de texto e interfaz: **Nunito Sans**.
Fallback del sistema: `-apple-system, "Segoe UI", Arial, sans-serif`. La combinación busca un
punto medio deliberado entre la geometría firme de Poppins (que hace de ancla de marca en
títulos y momentos clave) y la calidez legible de Nunito Sans (que sostiene el uso prolongado
en pantallas densas de trabajo).

Números siempre con `font-variant-numeric: tabular-nums` en tablas, KPIs y cualquier contexto
donde varias cifras se lean en columna.

## Escala tipográfica

Escala práctica (no estrictamente modular), pensada para legibilidad en pantallas de trabajo
antes que para efecto editorial:

| Token | Tamaño | Peso | Uso |
|---|---|---|---|
| `text-caption` | 11px | 500 | metadatos, etiquetas auxiliares |
| `text-footnote` | 12px | 400 | ayuda contextual, timestamps |
| `text-body-sm` | 13px | 400 | texto denso (tablas, listas) |
| `text-body` | 14px | 400 | cuerpo estándar de interfaz |
| `text-body-lg` | 16px | 400 | cuerpo destacado, formularios |
| `text-subtitle` | 18px | 500 | subtítulos de sección |
| `text-title-sm` | 20px | 600 | títulos de card / bloque |
| `text-title` | 24px | 600 | títulos de página |
| `text-title-lg` | 28px | 600 | encabezados principales |
| `text-display` | 36px | 700 | momentos hero, KPIs grandes |
| `text-display-lg` | 48px | 700 | pantallas de login / onboarding |

Nunca más de 3 tamaños distintos visibles en una misma vista de trabajo (tabla, panel,
formulario) — la variedad tipográfica se reserva para pantallas editoriales puntuales.

## Iconografía

Un único set, estilo **outline**, peso de trazo consistente (1.5–1.75px a 24px), esquinas
redondeadas suaves acordes al `radius-sm`. Nunca mezclar librerías ni mezclar estilo outline
con estilo relleno (filled) en la misma vista — la única excepción es un ícono relleno para
indicar estado "activo" de forma deliberada (ej. una campana de notificaciones con contenido
nuevo). El ícono hereda el color del texto que acompaña; nunca lleva un color propio fuera de
la paleta semántica.

## Densidad de información

Dos densidades, elegidas por contexto, nunca mezcladas dentro de una misma vista:

- **Cómoda** (`space-4`–`space-5` de padding interno) — vistas de trabajo diario: bandeja,
  chat, formularios.
- **Compacta** (`space-2`–`space-3` de padding interno) — tablas de datos densos, paneles de
  configuración avanzada.

La densidad compacta nunca sacrifica el tamaño mínimo de tipografía (`text-body-sm`, 13px) ni
el área mínima de toque de un control (32px de alto).

## Estados visuales

Todo elemento interactivo define explícitamente sus 5 estados — ninguno se deja "por defecto
del navegador":

`reposo` → `hover` → `focus` (anillo de foco visible, nunca solo cambio de color) → `activo/presionado`
→ `deshabilitado` (opacidad reducida + cursor not-allowed, nunca solo un color más pálido sin
otra señal).

Los estados de carga (skeleton, spinner) usan el mismo tono neutral en ambas escalas de color
(claro/oscuro) — nunca el color de marca, que queda reservado para lo accionable.

## Accesibilidad

Contraste mínimo AA en todo el sistema (4.5:1 texto de cuerpo, 3:1 texto grande y elementos de
UI) en modo claro y oscuro. Foco de teclado siempre visible con anillo de 2px en el color
primario. Ningún estado se comunica solo por color — siempre acompañado de ícono, texto o
forma (ver Badges semánticos en el sistema de componentes, cuando se construya la Fase 2).
Tamaño mínimo de fuente 11px en toda la interfaz, sin excepción. Área mínima de toque de 32px
en desktop, 44px en mobile.

## Responsive philosophy

Desktop-first en la filosofía de diseño (Maiek AI es una herramienta de trabajo, no un sitio
de consumo mobile-first), pero **mobile-complete** en la ejecución — ninguna funcionalidad
queda exclusivamente en desktop sin una ruta equivalente en mobile, aunque la composición
visual cambie. La productividad nunca se sacrifica por estética en ningún breakpoint.

## Reglas para futuras pantallas

Antes de diseñar cualquier pantalla nueva, verificar contra este documento:

1. ¿Toda medida (espacio, radio, tamaño de fuente) sale de una escala ya definida acá? Si no
   existe el valor que necesitás, primero se extiende la escala — nunca se improvisa un valor
   suelto.
2. ¿El color de marca aparece solo donde hay una acción? ¿El dorado se usa con moderación,
   nunca como color funcional?
3. ¿La jerarquía se resuelve con tamaño/peso/posición antes que con color o borde?
4. ¿Cada animación tiene una razón (causa → efecto) y no supera 400ms?
5. ¿La pantalla se entiende en menos de 5 segundos, con una sola acción principal evidente?

Cualquier pantalla que no pase estas 5 preguntas se rediseña antes de construirse — este
documento prevalece sobre cualquier decisión visual puntual que lo contradiga.
