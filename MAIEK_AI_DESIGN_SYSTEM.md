# Maiek AI — Design Language (MDL)

**Versión 1.2 · Official Design Standard**

| | |
|---|---|
| Documento | Maiek Design Language (MDL) |
| Proyecto | Maiek AI |
| Versión | 1.2 |
| Estado | **Approved** |
| Fecha de creación | 2026-07-26 |
| Autor | Claude, a pedido de Jesús Millones |
| Última actualización | 2026-09-14 |

> Depende de [`MAIEK_AI_FRAMEWORK.md`](MAIEK_AI_FRAMEWORK.md) y
> [`MAIEK_AI_PLATFORM_ARCHITECTURE.md`](MAIEK_AI_PLATFORM_ARCHITECTURE.md).
>
> Se relaciona con [`adr/0003-identidad-marca-unica-plataforma.md`](adr/0003-identidad-marca-unica-plataforma.md):
> ese ADR fija que los colores de marca de Maiek son "los tokens de MDL ya definidos", sin
> variación por tenant. La revisión v1.2 de este documento **actualiza cuáles son esos
> tokens** — no crea una excepción a esa decisión ni la reabre.

## Control de versiones

| Versión | Fecha | Autor | Descripción |
|---|---|---|---|
| 1.0 | 2026-07-26 | Claude | Primera versión — Capítulos 0 a 7 (Filosofía, Personalidad, Foundations, Color System, Typography System, Iconography System, Motion Language). |
| 1.1 | 2026-07-26 | Claude | Profesionalización documental (portada, control de versiones, objetivo, alcance, cómo utilizar el documento, glosario, convenciones, referencias, apéndices) + revisión técnica del Typography System. El contenido de los Capítulos 0–7 se mantiene intacto salvo la actualización puntual del Typography System (ver Revisión técnica más abajo). |
| 1.2 | 2026-09-14 | Claude, a pedido de Jesús Millones | Revisión cromática **"MAIEK Flow Intelligence"** (Capítulo 4 — Color System): nueva paleta principal (Cyan Flow, Azul Primary, Azul Strong, Navy, Dorado Acento) con verificación de contraste WCAG AA, reemplazando los hex de "Colores principales"/"Colores secundarios"/escalas tonales de la v1.1 (que se conservan en el documento marcados como Superseded, por trazabilidad histórica — nunca se borran). La arquitectura de 3 capas (identidad/semántica/superficie) y los roles de token (primario/primario-sólido/secundario/semánticos) NO cambian, solo sus valores hex. Decidido en el marco del Gate UX-03 (auditoría + plan de Conversaciones/CRM-Pipeline/Lead Detail); **la aplicación real de estos valores a `tailwind.config.ts`/`globals.css` de `maiek-frontend` queda fuera de esta revisión documental** — es un paso de implementación posterior, sujeto a su propia aprobación. |

Cualquier modificación futura de fondo debe sumar una fila nueva a esta tabla — este documento
no se edita en silencio.

## Objetivo del documento

**Para qué existe.** Este documento fija el lenguaje visual común de Maiek AI: los principios,
tokens y reglas que cualquier pantalla, presente o futura, debe respetar. No es una colección
de sugerencias — es el estándar contra el que se valida cada decisión visual del producto.

**Qué problemas resuelve.** Sin un documento así, cada pantalla nueva reinventa su propio
espaciado, su propia paleta, su propio tono — y el producto se fragmenta visualmente a medida
que el equipo crece. El MDL existe para que esa fragmentación nunca ocurra: un mismo lenguaje
visual, sostenido durante años y cientos de pantallas, sin depender de que la misma persona
diseñe todas.

**Quién debe utilizarlo.** Diseñadores, desarrolladores frontend, arquitectos de software y
equipos de producto — cualquier persona que tome una decisión visual sobre cualquier producto
de Maiek AI, no solo sobre Gaso+.

**Cuándo debe consultarse.** Antes de diseñar o construir cualquier pantalla nueva; antes de
introducir un valor de espaciado, color, tipografía o timing que no esté ya definido acá; y
como referencia de arbitraje cuando dos decisiones visuales entran en conflicto.

## Alcance

**Qué cubre este documento:** filosofía de producto, personalidad de marca, fundamentos de
grid/layout/espaciado/elevación/motion, sistema de color (con dark mode), sistema tipográfico,
sistema de iconografía y lenguaje de movimiento.

**Qué NO cubre este documento:**
- No define componentes (botones, inputs, tablas, cards, modales, formularios, chat, sidebar,
  dashboards) — eso es la Fase 2, ver "Próximo Entregable" al final.
- No define arquitectura de software ni de datos (ver `MAIEK_AI_PLATFORM_ARCHITECTURE.md`).
- No define lógica de negocio.
- No define experiencia conversacional — cómo responde Gabi o cualquier agente de IA en una
  conversación vive en `MAIEK_AI_FRAMEWORK.md` y en la configuración de producto, no acá.
- No define comportamiento funcional (qué hace un control al activarse, reglas de validación,
  flujos de navegación).

**Estado de aplicación (corregido 2026-09-14 — Gate UX-03B, corrección documental puntual, sin
cambio de código):** esta nota describía el estado de 2026-07-26, ya desactualizado. El MDL
(v1.1, valores hex de esa versión) **sí está aplicado**, con rigor, en la Nueva Experiencia
(`maiek-frontend`, Next.js/Vercel) — tokens de color/tipografía/espaciado/radio/elevación en
`tailwind.config.ts` y `app/globals.css`, con auditoría de contraste AA documentada en el
propio código, confirmado por auditoría independiente en la Fase 0 de UX-03. La revisión
cromática v1.2 de este capítulo (arriba) todavía NO está aplicada a esos archivos — sigue
pendiente de su propio Gate de implementación, ver la nota de alcance de la sección v1.2.

El panel Legacy de Gaso+ (`agent/dashboard.py`, HTML server-rendered) es un sistema aparte:
sigue con su paleta propia (`#00A1DE` navbar/primario, `#075E85` oscuro, `#3CCBDA` secundario)
y no tiene planeada, por ahora, una migración al MDL.

**Nota sobre arquitectura (no parte del documento original):** este documento define lenguaje
visual, no arquitectura. Multi-tenant, modelo multiempresa e integraciones ya están
documentados como visión aprobada en `MAIEK_AI_PLATFORM_ARCHITECTURE.md` — ese estado no
cambia acá. El código actual de Gaso+ sigue siendo de un solo tenant (ver nota de estado en
ese documento); este archivo no construye ni modifica arquitectura.

## Cómo utilizar este documento

**Durante el desarrollo.** Antes de introducir cualquier valor visual nuevo, se busca acá
primero. Si el valor que se necesita no existe en una escala ya definida (espaciado, radio,
tipografía, timing), la escala se extiende — nunca se improvisa un valor suelto fuera de ella
(ver Capítulo 3 y Convenciones).

**Qué documentos lo complementarán.** El Sistema de Componentes (Fase 2 — botones, inputs,
tablas, cards, badges, modales), especificaciones de patrones de producto (chat, dashboard,
sidebar, copiloto de IA) y guías de implementación técnica (tokens de este documento
convertidos en variables de código). Ver "Próximo Entregable" para el primero de estos.

**Cómo se mantiene actualizado.** Por control de versiones, nunca por edición silenciosa —
todo cambio de fondo suma una fila nueva a la tabla de arriba, con fecha, autor y descripción
del cambio. Un documento "Approved" puede seguir evolucionando; lo que no puede es cambiar sin
que quede registrado por qué.

---

# Capítulo 0 — Filosofía Maiek

## Propósito

Maiek AI no es otro CRM con un asistente de IA pegado encima. Es una **plataforma de
inteligencia conversacional**: la IA no vive en un módulo aparte que el usuario visita — vive
disuelta en cada pantalla, cada lista, cada conversación. El propósito de la interfaz es hacer
esa inteligencia invisible como infraestructura y visible solo como resultado: menos pantallas
que mirar, mejores decisiones que tomar.

**Maiek no muestra información. Maiek ayuda a tomar decisiones.** Esa distinción gobierna cada
decisión de este documento — una tabla con 40 columnas muestra información; una tarjeta que
dice "llama primero a este cliente, aquí está por qué" ayuda a decidir. El segundo es el
producto; el primero es lo que Maiek reemplaza.

## Visión del producto

Ser la plataforma de inteligencia conversacional más intuitiva, elegante y escalable del
mercado — no medida por cuántas funciones tiene, sino por cuánto menos esfuerzo mental necesita
un equipo comercial para cerrar una venta bien. Un producto que un vendedor prefiere abrir
antes que su propio WhatsApp personal, porque ahí está todo resuelto, no todo acumulado.

## Principios de experiencia

1. **Maiek no muestra información. Maiek ayuda a tomar decisiones** — cada pantalla se
   justifica por la decisión que permite tomar, no por los datos que despliega.
2. **La IA nunca interrumpe. Aparece únicamente cuando agrega valor** — sin popups
   proactivos, sin "¿te ayudo con algo?" genérico; la IA habla cuando tiene algo que decir.
3. **Cada pantalla responde una sola pregunta: ¿cuál es la siguiente mejor acción?** — si una
   pantalla no puede responder eso en un vistazo, está mal diseñada.
4. **Menos elementos, más claridad** — la reducción es la herramienta de diseño por defecto,
   no el último recurso.
5. **El espacio vacío también comunica** — silencio visual alrededor de lo importante es
   información, no un vacío a rellenar.
6. **Todo debe sentirse construido, nunca decorado** — cada sombra, curva o color tiene una
   función que se puede explicar en una frase; si no la tiene, se elimina.
7. **La experiencia transmite tranquilidad, nunca ansiedad** — sin contadores rojos
   agresivos, sin urgencia fabricada, sin parpadeos; la prioridad se comunica con jerarquía,
   no con alarma.
8. **La simplicidad siempre gana** — ante dos soluciones igual de correctas, se elige la más
   simple, aunque la otra sea más "impresionante".
9. **La consistencia es más importante que la creatividad** — un patrón nuevo por pantalla es
   una pantalla que el usuario tiene que reaprender.
10. **Cada interacción reduce el esfuerzo mental del usuario** — si una interacción nueva no
    reduce carga cognitiva respecto a la alternativa anterior, no se agrega.

## Emociones que debe transmitir

Claridad, calma, inteligencia, confianza, precisión, tecnología premium, simplicidad extrema y
cercanía humana. Ninguna de estas emociones se logra agregando elementos — todas se logran
quitando: menos ruido produce más claridad, menos urgencia produce más calma, menos fricción
produce más confianza.

## Un día completo con Maiek

**Mañana.** El vendedor abre el panel. No ve una tabla — ve, de un vistazo, a quién debería
llamar primero y por qué. No tiene que ordenar, filtrar ni pensar por dónde empezar; Maiek ya
lo pensó.

**Media mañana.** Entra una conversación nueva por WhatsApp. La IA ya la resumió, ya detectó
intención de compra, ya sugirió el producto correcto — el vendedor entra a la conversación y
en tres segundos entiende dónde está el cliente en su decisión, sin releer el historial
completo.

**Mediodía.** El supervisor abre su vista. No revisa conversación por conversación — ve el
pulso del equipo en números grandes y claros, y la IA le señala la única cosa que necesita su
atención hoy (una campaña bajando de rendimiento, un cliente de alto valor sin respuesta hace
horas).

**Tarde.** Un cliente pregunta por financiamiento. El vendedor no busca en una carpeta ni
calcula a mano — pide una cotización y la tiene lista para enviar en segundos.

**Cierre del día.** Nada quedó en el aire porque nada quedó invisible: lo pendiente estaba
siempre a la vista, priorizado, sin que el usuario tuviera que ir a buscarlo. El día terminó
con menos pantallas abiertas, no con más pestañas sin cerrar.

Esa sensación — llegar, saber inmediatamente qué hacer, hacerlo sin fricción, irse sin cabos
sueltos — es el estándar contra el que se mide cada pantalla nueva de Maiek AI.

---

# Capítulo 1 — Principios del lenguaje visual

Reglas que nunca se rompen, sin excepción de pantalla ni de plazo de entrega:

- **Silencio antes que ruido.** Cada elemento adicional tiene que ganarse su lugar; el estado
  por defecto de cualquier decisión de diseño es no agregar nada.
- **Precisión antes que decoración.** Un borde de 0.5px comunica más orden que una sombra de
  8px. La geometría es exacta, nunca aproximada.
- **Una sola voz de acento.** El color de marca aparece donde el usuario debe actuar — nunca
  como fondo decorativo ni para llenar espacio vacío.
- **Profundidad con propósito.** La elevación (sombra, blur, superposición) existe solo para
  comunicar orden de interacción, nunca como estilo.
- **Movimiento con intención.** Ninguna animación es gratuita; cada una explica una relación
  causa-efecto entre la acción del usuario y el cambio en pantalla.
- **Consistencia sobre novedad.** Un patrón ya resuelto en una pantalla se reutiliza tal cual
  en la siguiente.
- **La IA se ve, no se anuncia.** Un contenido generado por IA se distingue por un detalle
  visual sutil (ver Capítulo 6), nunca por una etiqueta ansiosa tipo "¡Generado por IA!".
- **Ninguna pantalla obliga a pensar dónde mirar primero.** La jerarquía visual siempre
  resuelve esa pregunta antes de que el usuario tenga que hacérsela.

---

# Capítulo 2 — Personalidad del producto

Si Maiek fuera una persona en el equipo, sería la persona más preparada de la sala que nunca
necesita levantar la voz para que la escuchen.

**Cómo habla.** Directo, en frases cortas. Dice "María está lista para comprar" en vez de "Se
ha detectado una alta probabilidad de conversión en la conversación con la usuaria María".
Nunca usa jerga técnica de sistema hacia el usuario final (nunca dice "webhook", "payload" ni
"sincronizando"). Habla en el idioma del negocio: leads, ventas, clientes — no en el idioma de
la base de datos.

**Cómo responde.** Con lo que se le pidió, y nada más. Si el usuario pide un resumen, da un
resumen — no un resumen más tres sugerencias no solicitadas. Cuando no sabe algo, lo dice sin
rodeos ("no tengo esa información") en vez de inventar una respuesta plausible.

**Cómo toma decisiones.** Basada en datos que puede mostrar, no en intuición que no puede
explicar. Cuando recomienda una acción, siempre puede justificarla en una línea ("porque lleva
3 días sin respuesta y su intención de compra es alta") — nunca una recomendación sin razón
visible.

**Qué evita.** Evita la urgencia artificial (nunca cuenta regresiva falsa, nunca "¡últimas
horas!"), evita el relleno conversacional ("¡Genial pregunta!", "¡Por supuesto que sí!"), evita
mostrar el mismo dato en dos formatos distintos en la misma pantalla, evita pedir confirmación
para acciones reversibles.

**Qué jamás haría.** Jamás interrumpe una tarea en curso del usuario para mostrar algo que
puede esperar. Jamás usa un tono de venta agresivo puertas adentro (Maiek ayuda a vender, no
vende de vuelta al equipo que ya la está usando). Jamás oculta por qué recomendó algo detrás
de un "confía en el algoritmo". Jamás sacrifica claridad por parecer más sofisticada.

---

# Capítulo 3 — Foundations

## Grid

Unidad atómica: **8px**. Todo margen, padding, alto de fila o tamaño de ícono es múltiplo de
8px (4px permitido como sub-unidad para ajustes finos de texto/ícono). Nunca valores
arbitrarios como 15px o 22px.

## Layout

Layout de escritorio: grilla fluida de **12 columnas**, gutter de 24px, ancho máximo de
contenido **1440px** centrado — más allá de eso, el exceso se reparte como margen lateral,
nunca estirando tablas o cards a un ancho incómodo de leer.

## Sistema de espaciados

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
columnas, gutter 16px. Ningún componente ocupa una fracción de columna no entera (nunca "2.5
columnas") — si no calza, se rediseña el bloque, no se fuerza la grilla.

## Breakpoints

| Nombre | Ancho | Contexto |
|---|---|---|
| `xs` | 480px | mobile |
| `sm` | 768px | tablet vertical |
| `md` | 1024px | tablet horizontal / laptop chico |
| `lg` | 1280px | desktop estándar |
| `xl` | 1536px | desktop ancho |

## White space

El espacio en blanco es un componente, no un residuo. Regla práctica: si una pantalla se
siente "vacía" al 70% de densidad de información real, está bien — la alternativa (rellenar
con relleno visual) siempre es peor que dejarla respirar. El espacio en blanco es lo que
permite que la única acción importante de la pantalla se note sin competencia.

## Border radius

| Token | Valor | Uso |
|---|---|---|
| `radius-sm` | 6px | controles pequeños, chips |
| `radius-md` | 10px | controles estándar (default) |
| `radius-lg` | 14px | cards |
| `radius-xl` | 20px | superficies grandes, modales |
| `radius-full` | 999px | avatares, pills, badges |

Nunca radios intermedios fuera de esta escala, y nunca radio en un solo lado sin justificar
por qué.

## Elevaciones

| Nivel | Nombre | Uso |
|---|---|---|
| 0 | Base | superficie de página y de card en reposo — sin sombra |
| 1 | Hover | tarjeta o fila al pasar el mouse — sombra apenas perceptible |
| 2 | Flotante | dropdown, popover, menú contextual |
| 3 | Superpuesto | modal, panel lateral, diálogo |
| 4 | Crítico | toast, notificación que exige atención inmediata |

Regla dura: nunca más de **dos** niveles de elevación flotante activos a la vez — un tercer
elemento flotante significa que el flujo está mal diseñado, no que hace falta un nivel más.

## Sombras

Siempre neutras (nunca de color), de doble capa (contacto + difusa), muy sutiles:

| Nivel | `box-shadow` (modo claro) |
|---|---|
| 1 | `0 1px 2px rgba(11,29,58,0.06)` |
| 2 | `0 4px 12px rgba(11,29,58,0.08), 0 1px 3px rgba(11,29,58,0.06)` |
| 3 | `0 12px 32px rgba(11,29,58,0.12), 0 2px 6px rgba(11,29,58,0.08)` |
| 4 | `0 20px 48px rgba(11,29,58,0.16), 0 4px 10px rgba(11,29,58,0.10)` |

El color base usa el navy de marca (`#0B1D3A`) a baja opacidad en vez de negro puro — una
sombra tibia, no una sombra gris genérica. En modo oscuro, la sombra se reemplaza por un borde
de 1px en `neutral-700` a baja opacidad (ver Capítulo 4, Dark Mode) — sobre fondos ya oscuros,
la sombra pierde legibilidad y el borde comunica mejor la separación de planos.

## Blur y transparencias

El blur se reserva para **overlays**, nunca para contenido primario:

| Contexto | Blur | Opacidad de scrim |
|---|---|---|
| Popover sobre contenido denso | 8px | — |
| Command palette / búsqueda global | 16px | fondo a 45% |
| Modal sobre la app completa | 24px | fondo a 55% |

Ningún panel permanente (sidebar, header, tabla) usa transparencia — deben leerse sólidos y
estables. El scrim en modo oscuro usa negro puro a la misma opacidad (el navy ya es
suficientemente oscuro como fondo propio).

## Responsive philosophy

Desktop-first en la filosofía (Maiek es una herramienta de trabajo, no un producto de consumo
mobile-first), pero **mobile-complete** en la ejecución — ninguna funcionalidad queda
exclusivamente en desktop sin una ruta equivalente en mobile, aunque la composición cambie. La
productividad nunca se sacrifica por estética en ningún breakpoint.

## Accesibilidad

Contraste mínimo AA (4.5:1 texto de cuerpo, 3:1 texto grande y elementos de UI) en ambos
modos. Foco de teclado siempre visible con anillo de 2px en el color primario del modo activo.
Ningún estado se comunica solo por color — siempre acompañado de ícono, texto o forma. Tamaño
mínimo de fuente 11px sin excepción. Área mínima de toque: 32px en desktop, 44px en mobile.

## Densidad de información

Dos densidades, elegidas por contexto, nunca mezcladas dentro de una misma vista:

- **Cómoda** (`space-4`–`space-5` de padding interno) — vistas de trabajo diario: bandeja,
  chat, formularios.
- **Compacta** (`space-2`–`space-3` de padding interno) — tablas de datos densos, paneles de
  configuración avanzada.

La densidad compacta nunca sacrifica el tamaño mínimo de tipografía (13px) ni el área mínima
de toque de un control (32px de alto).

## Jerarquía visual

Se construye en este orden de prioridad — nunca al revés:

1. Tamaño y peso de fuente.
2. Posición y proximidad (lo relacionado está cerca).
3. Color (acento reservado solo para lo accionable).
4. Contorno o fondo (el último recurso, no el primero).

---

# Capítulo 4 — Color System

No es una paleta — es un sistema de tres capas: **identidad** (quién es Maiek), **semántica**
(qué significa cada estado) y **superficie** (dónde vive cada cosa, en cada modo). Las tres
capas nunca se mezclan entre sí: el azul de marca no se reutiliza para "información", el
dorado no se usa para "advertencia", y ningún color de superficie carga significado semántico.
Esta arquitectura de 3 capas no cambia con la revisión v1.2 — solo cambian los valores hex de
la capa de identidad, documentados abajo.

## Revisión v1.2 — MAIEK Flow Intelligence

Paleta principal aprobada el 2026-09-14 en el marco del Gate UX-03, reemplazando los hex de
"Colores principales"/"Colores secundarios"/escalas tonales de la v1.1 (conservados más abajo,
marcados **Superseded**, por trazabilidad histórica). Es la **única** paleta principal vigente
— ver nota de la v1.1 para evitar leer dos "paletas oficiales" activas a la vez.

| Rol | Hex | Nombre | Semántica declarada |
|---|---|---|---|
| Interactivo (enlaces, foco, ítem activo) | `#0072FF` | Azul Primary | Conexión · acción |
| Fondo sólido bajo texto blanco (botones, badges) | `#0057D9` | Azul Strong | Conexión · acción |
| Superficie oscura / texto de marca | `#102A56` | Navy | Estructura · confianza · solidez |
| Acento excepcional (isotipo, momentos de valor) | `#D9A441` | Dorado Acento | Valor · sofisticación · momentos clave |
| Familia "información"/estados de IA | `#00C6FF` | Cyan Flow | Flujo · inteligencia · evolución |
| Fondo suave de identidad | `#E6F4FF` | Azul Soft | — |
| Fondo de página | `#F8FAFD` | Surface | Claridad · foco |
| Texto principal | `#141A26` | — | Claridad · foco |
| Texto secundario | `#667085` | — | Claridad · foco |
| Borde | `#E1E5EB` | — | Claridad · foco |

**Por qué Azul Primary y Azul Strong son dos colores, no uno:** mismo problema que ya resolvía
la v1.1 con `#1677FF` — blanco sobre `#0072FF` mide 4.33:1, por debajo del 4.5:1 que este
capítulo exige para texto de cuerpo. El sólido bajo texto blanco (botón primario, badge de
conteo) usa `#0057D9` (6.24:1); el rol interactivo puro (enlace, foco, ítem activo de
navegación, que nunca lleva texto blanco encima) usa `#0072FF`. Mismo patrón de dos roles que
ya describía la sección de Contraste más abajo, valores nuevos.

**Por qué Cyan Flow no reemplaza a "Secundario" en todos sus usos:** blanco sobre `#00C6FF`
mide 2.0:1 — falla AA de lejos como fondo sólido con texto blanco. Cyan solo funciona como
texto/ícono sobre Navy (8.76:1) o como fondo suave con texto oscuro encima (mismo patrón que
ya usaba "Secundario" en la v1.1, foreground oscuro, nunca blanco). Su semántica declarada
("flujo, inteligencia, evolución") lo asigna a la familia **Información**/estados de IA — no a
un reemplazo genérico de "Secundario" en cualquier contexto.

**Por qué Dorado Acento sigue sin fondo sólido:** blanco sobre `#D9A441` mide 2.25:1 — falla
AA. Mismo rol que el dorado de la v1.1: texto/acento sobre Navy (6.28:1), nunca fondo de
botón, navegación, selección, estado comercial, tabla o background general — la restricción
de uso excepcional del dorado (ver más abajo) no cambia con esta revisión.

**Verificación WCAG AA (2026-09-14, valores exactos, sin redondeo intermedio):**

| Par | Contraste | Resultado |
|---|---|---|
| Blanco sobre Azul Primary `#0072FF` | 4.33:1 | Falla AA texto — no usar como fondo sólido con texto blanco |
| Blanco sobre Azul Strong `#0057D9` | 6.24:1 | Pasa AA |
| Blanco sobre Navy `#102A56` | 14.1:1 | Pasa AA |
| Blanco sobre Cyan Flow `#00C6FF` | 2.0:1 | Falla AA — no usar como fondo sólido con texto blanco |
| Texto oscuro (`#141A26`) sobre Cyan Flow | 8.76:1 | Pasa AA |
| Dorado Acento `#D9A441` sobre Navy | 6.28:1 | Pasa AA (uso como texto/acento) |
| Blanco sobre Dorado Acento | 2.25:1 | Falla AA — no usar como fondo sólido con texto blanco |
| Texto secundario `#667085` sobre Surface `#F8FAFD` | 4.76:1 | Pasa AA (margen ajustado) |

**Mapeo de rol (v1.1 → v1.2), para quien porte esto a tokens de implementación:**

| Rol de token | v1.1 (Superseded) | v1.2 (vigente) |
|---|---|---|
| `primary` / interactivo | `#1677FF` (azul 600) | `#0072FF` (Azul Primary) |
| `primary-solid` / fondo sólido | `#0F56BF` (azul 800) | `#0057D9` (Azul Strong) |
| Superficie oscura / texto de marca | `#0B1D3A` (navy 900) | `#102A56` (Navy) |
| Acento de marca | `#C6A66B` (dorado 600) | `#D9A441` (Dorado Acento) |
| `primary-soft` | `#E9F1FF` | `#E6F4FF` (Azul Soft) |
| `surface-0` (claro) | `#F2F4F7` | `#F8FAFD` (Surface) |
| Texto secundario | `#384152` (neutral 800) | `#667085` |
| Borde | `#E7EAEF` | `#E1E5EB` |
| `info` / estados de IA | compartía valor con `primary-soft` (`#E9F1FF`) — colisión conocida | familia Cyan Flow, valor propio — resuelve la colisión |

**Nota de alcance:** esta sección formaliza la DECISIÓN y su verificación de contraste. No
implica que `tailwind.config.ts`/`globals.css` de `maiek-frontend` ya estén actualizados a
estos valores — esa aplicación es un paso posterior, con su propia aprobación.

---

## Colores principales (v1.1 — Superseded por la revisión v1.2 de arriba)

| Uso | Hex | Nombre |
|---|---|---|
| Primario (interactivo) | `#1677FF` | Azul tecnológico |
| Texto / superficie oscura de marca | `#0B1D3A` | Azul navy |

## Colores secundarios (v1.1 — Superseded por la revisión v1.2 de arriba)

| Uso | Hex | Nombre |
|---|---|---|
| Secundario | `#38BDF8` | Celeste |
| Acento de marca (isotipo, uso escaso) | `#C6A66B` | Dorado |
| Fondo | `#F2F4F7` | Gris claro |

El dorado es el color menos usado de todo el sistema a propósito — reservado al isotipo y a
momentos puntuales de reconocimiento de marca (splash, portada de login), nunca en un botón,
badge o gráfico de datos. Esta restricción de uso sigue vigente en v1.2 (ver arriba), solo
cambió el hex.

## Escalas tonales (v1.1 — Superseded por la revisión v1.2 de arriba)

Cada color de marca se expande en 7 pasos (50 = tinte más claro, 900 = sombra más oscura).
Valores indicativos, a afinar con herramienta de color en la implementación:

**Azul tecnológico** (primario)
`50` `#E9F1FF` · `100` `#CCE1FF` · `200` `#99C2FF` · `400` `#4D96FF` · `600` `#1677FF` · `800` `#0F56BF` · `900` `#0A3D87`

**Celeste** (secundario)
`50` `#EDFAFF` · `100` `#D3F3FE` · `200` `#A6E7FD` · `400` `#62D0FA` · `600` `#38BDF8` · `800` `#1B8FC2` · `900` `#146A92`

**Navy** (texto de marca / superficie dark)
`50` `#EBEFF5` · `100` `#D3DCE9` · `200` `#A8BAD4` · `400` `#375D93` · `600` `#16345C` · `800` `#0F2647` · `900` `#0B1D3A`

**Dorado** (acento)
`50` `#FBF6EE` · `100` `#F3E7D2` · `200` `#E6CFA5` · `400` `#D4B888` · `600` `#C6A66B` · `800` `#9C7F4C` · `900` `#6E5A34`

**Neutral** (fondo, texto secundario, bordes — anclado al matiz navy para no leerse gris
genérico)
`0` `#FFFFFF` · `50` `#F2F4F7` · `100` `#E7EAEF` · `200` `#D2D7E0` · `400` `#9AA3B2` · `600` `#626C7E` · `800` `#384152` · `900` `#1B222E`

**Nota:** las escalas tonales completas (7 pasos) de la paleta v1.2 no se redefinieron en esta
revisión — solo los 8 valores de rol de la tabla de mapeo de arriba. Extender Azul
Primary/Strong/Cyan Flow/Navy/Dorado Acento a una escala de 7 pasos cada uno queda pendiente
para cuando se apruebe la aplicación real a tokens de implementación.

## Estados y alertas

Sistema semántico, deliberadamente separado de la identidad — 3 columnas por rol (fondo suave
/ sólido / texto sobre fondo suave):

| Rol | Fondo suave | Sólido | Texto sobre fondo suave |
|---|---|---|---|
| Éxito | `#E3F5EA` | `#00A34B` | `#0F6E3B` |
| Advertencia | `#FEF3DC` | `#FAB200` | `#8A5B00` |
| Error | `#FCEAEA` | `#EF4444` | `#9E1F1F` |
| Información | `#E9F1FF` | `#1677FF` | `#0F56BF` |

El "sólido" se usa en indicadores puntuales (punto de estado, ícono); el "fondo suave" +
"texto" se usa en badges y banners — nunca texto oscuro genérico sobre un fondo de color,
siempre el texto de la misma familia tonal.

## Fondos y superficies (modo claro)

| Token | Hex | Uso |
|---|---|---|
| `surface-0` | `#F2F4F7` | fondo de página |
| `surface-1` | `#FFFFFF` | card, fila, panel en reposo |
| `surface-2` | `#FFFFFF` + sombra nivel 2 | popover, dropdown |
| `border` | `#E7EAEF` | línea divisoria por defecto |
| `border-strong` | `#D2D7E0` | borde de énfasis, foco de input |

## Contraste

Texto principal sobre `surface-0`/`surface-1`: navy `#0B1D3A` — contraste 15.8:1, muy por
encima del mínimo AA. Texto secundario: neutral `800` `#384152` — contraste 9.2:1. Texto sobre
el primario sólido (`#1677FF`): blanco `#FFFFFF` — contraste 4.6:1, cumple AA para texto de
controles. Ninguna combinación de texto/fondo del sistema baja de 4.5:1 en texto de cuerpo.

## Dark Mode

El modo oscuro no es el modo claro invertido — es su propio sistema de superficies, construido
sobre la misma escala tonal de navy (que ya es, por diseño, la base natural de un fondo
oscuro de marca).

| Token | Hex (dark) | Equivalente claro |
|---|---|---|
| `surface-0` (página) | `#0B1D3A` (navy 900) | `#F2F4F7` |
| `surface-1` (card) | `#0F2647` (navy 800) | `#FFFFFF` |
| `surface-2` (popover) | `#16345C` (navy 600) | `#FFFFFF` + sombra |
| `text-primary` | `#F2F4F7` (neutral 50) | `#0B1D3A` |
| `text-secondary` | `#D2D7E0` (neutral 200) | `#384152` |
| `text-muted` | `#9AA3B2` (neutral 400) | `#626C7E` |
| `border` | `#375D93` a 30% opacidad (navy 400) | `#E7EAEF` |
| `primario` (interactivo) | `#4D96FF` (azul 400) | `#1677FF` (azul 600) |
| `secundario` | `#62D0FA` (celeste 400) | `#38BDF8` (celeste 600) |

Regla general: en dark mode, los colores interactivos usan un paso **más claro** de la misma
escala tonal (400 en vez de 600) — el color base pierde contraste sobre un fondo oscuro, y
oscurecerlo más (en vez de aclararlo) sería el error más común al portar un sistema de modo
claro a oscuro.

**Fondos suaves semánticos en dark mode** (mismo sólido, fondo reformulado — nunca el mismo
tinte pastel de modo claro, que se ve sucio sobre fondo oscuro):

| Rol | Fondo suave (dark) | Sólido (igual en ambos modos) |
|---|---|---|
| Éxito | `#123322` | `#00A34B` |
| Advertencia | `#3A2C05` | `#FAB200` |
| Error | `#3A1414` | `#EF4444` |
| Información | `#12233F` | `#1677FF` |

El dorado de acento no cambia entre modos (`#C6A66B` funciona igual de bien sobre navy oscuro
que sobre blanco) — es, de hecho, el único color del sistema pensado desde el origen para
funcionar sin ajuste en ambos fondos.

---

# Capítulo 5 — Typography System

## Familia tipográfica

*Actualizado en v1.1 — ver "Revisión técnica: Typography System" al final del documento para
el análisis completo y las razones del cambio.*

Dos roles, deliberadamente distintos:

- **Marca** (logo, wordmark, portadas de login/onboarding, momentos editoriales puntuales):
  **Poppins**. Se conserva del moodboard original — su geometría distintiva es exactamente lo
  que un wordmark necesita, y no compite con la tipografía de producto porque casi nunca
  aparecen en la misma pantalla a la vez.
- **Producto** (toda la interfaz de trabajo: tablas, formularios, chat, dashboards, navegación):
  **Inter**, en reemplazo de Nunito Sans. Es una tipografía diseñada específicamente para
  pantallas de alta densidad — la revisión técnica de v1.1 encontró que resuelve mejor que
  Nunito Sans exactamente los contextos donde Maiek AI vive todo el día (tablas, chat, cifras
  tabulares).

Fallback del sistema en ambos roles: `-apple-system, "Segoe UI", Arial, sans-serif`. Nunca una
tercera familia en ninguna pantalla del producto, y nunca Poppins en párrafos largos o tablas
densas (ver Buenas prácticas y Errores comunes más abajo).

## Escala tipográfica

| Token | Tamaño | Peso | Interlineado | Uso |
|---|---|---|---|---|
| `text-caption` | 11px | 500 | 1.4 | metadatos, etiquetas auxiliares |
| `text-footnote` | 12px | 400 | 1.45 | ayuda contextual, timestamps |
| `text-body-sm` | 13px | 400 | 1.5 | texto denso (tablas, listas) |
| `text-body` | 14px | 400 | 1.55 | cuerpo estándar de interfaz |
| `text-body-lg` | 16px | 400 | 1.6 | cuerpo destacado, formularios |
| `text-subtitle` | 18px | 500 | 1.4 | subtítulos de sección |
| `text-title-sm` | 20px | 600 | 1.3 | títulos de card / bloque |
| `text-title` | 24px | 600 | 1.25 | títulos de página |
| `text-title-lg` | 28px | 600 | 1.2 | encabezados principales |
| `text-display` | 36px | 700 | 1.15 | momentos hero, KPIs grandes |
| `text-display-lg` | 48px | 700 | 1.1 | login, onboarding |

## Pesos

Solo tres pesos activos en todo el sistema: **400** (regular, texto de cuerpo), **500**
(medium, énfasis y subtítulos), **600–700** (semibold/bold, reservado a títulos y momentos
hero). Nunca usar 300 (se lee débil en pantalla a tamaños chicos) ni más de un peso bold
distinto en la misma vista.

## Espaciados (letter-spacing)

Texto de cuerpo: `0` (tracking natural de la fuente). Etiquetas en mayúscula pequeña
(`text-caption` usado como eyebrow/label): `+0.04em` — el único caso donde se abre tracking, y
solo en mayúsculas cortas (2-3 palabras), nunca en párrafos.

## Jerarquía

La jerarquía tipográfica se resuelve combinando tamaño + peso + color, en ese orden de fuerza.
Un título nunca compite en la misma vista con más de dos niveles subordinados directos (título
→ subtítulo → cuerpo es correcto; título → subtítulo → sub-subtítulo → cuerpo ya es
demasiado profundo para una pantalla de trabajo).

## Uso correcto

- Números que se comparan en columna (tablas, KPIs, montos) siempre con
  `font-variant-numeric: tabular-nums`.
- Un máximo de 3 tamaños tipográficos visibles en una misma vista de trabajo (tabla, panel,
  formulario) — la variedad se reserva para pantallas editoriales puntuales (login, onboarding).
- El peso comunica jerarquía antes que el tamaño — subir de 500 a 600 suele resolver un
  énfasis sin necesitar subir también el tamaño en px.

## Buenas prácticas

Longitud de línea de cuerpo entre 45 y 75 caracteres — por debajo se lee entrecortado, por
encima cansa. Interlineado nunca por debajo de 1.4 en texto de cuerpo, aunque el espacio
parezca "generoso" — la densidad se controla con `space-*`, no comprimiendo el interlineado.

## Errores comunes (a evitar)

- Usar `text-caption` (11px) para texto que el usuario necesita leer con atención — 11px es
  solo para metadatos que se escanean, no para contenido que se lee.
- Centrar párrafos de más de una línea — el texto centrado se justifica solo en títulos
  cortos o estados vacíos, nunca en cuerpo de texto.
- Aumentar el tamaño de fuente para dar énfasis en vez de subir el peso — infla la jerarquía
  sin necesidad y rompe la escala tipográfica definida arriba.
- Mezclar Poppins en cuerpo de texto extenso — Poppins es tipografía de título, no de lectura
  prolongada; usarla en párrafos largos cansa la vista.

---

# Capítulo 6 — Iconography System

## Estilo

Un único set, estilo **outline** (nunca relleno/filled, salvo la excepción explícita de abajo).
Esquinas redondeadas suaves, acordes al `radius-sm` del sistema — nunca esquinas agudas ni
sobre-redondeadas.

## Grosor

Peso de trazo consistente: **1.5–1.75px a 24px** de tamaño base. El grosor nunca varía entre
íconos de la misma vista, aunque vengan de contextos distintos (navegación, acciones, estados).

## Tamaños

| Token | Tamaño | Uso |
|---|---|---|
| `icon-sm` | 16px | dentro de texto en línea, badges |
| `icon-md` | 20px | controles estándar, ítems de lista |
| `icon-lg` | 24px | navegación principal, encabezados de sección |
| `icon-xl` | 32px | estados vacíos, momentos destacados |

## Consistencia

Una sola librería de íconos en todo el producto — nunca mezclar dos sets, aunque sea "solo por
un ícono que falta" en el set principal. Si un ícono no existe en la librería elegida, se
adapta al mismo estilo (outline, mismo grosor) antes que importarlo de otra fuente.

## Uso

El ícono hereda el color del texto que acompaña — nunca lleva un color propio fuera de la
paleta semántica (Capítulo 4). Un ícono nunca aparece solo sin una etiqueta de texto o un
`aria-label`, salvo en controles universalmente reconocibles (cerrar, buscar, más opciones).

**Excepción deliberada — relleno (filled):** un ícono relleno se permite únicamente para
marcar un estado "activo" de forma intencional (una campana de notificaciones con contenido
nuevo, un ítem de navegación seleccionado). Nunca como preferencia estética.

**Marca de contenido generado por IA:** un ícono específico y consistente (chispa/destello,
outline, del mismo set) acompaña cualquier contenido que la IA generó o sugirió — resumen,
recomendación, cotización sugerida. Aparece una sola vez por bloque de contenido, nunca
repetido en cada línea, siguiendo el principio "la IA se ve, no se anuncia" del Capítulo 1.

## Animaciones

Los íconos casi nunca se animan — la regla por defecto es estática. Las tres excepciones
permitidas:

- **Carga/procesamiento**: un ícono de estado (ej. el destello de IA) puede pulsar suavemente
  (opacidad 100%→60%→100%, 1.2s, loop) mientras el sistema está generando algo — nunca girar
  ni rebotar.
- **Confirmación puntual**: un ícono de check puede tener una micro-animación de trazo
  (stroke-draw, 250ms, `ease-out-expo`) al completarse una acción — una sola vez, nunca en
  loop.
- **Cambio de estado binario**: un chevron que rota 180° al expandir/contraer una sección
  (`motion-fast`, 150ms).

Ninguna otra animación de ícono está permitida por defecto — cualquier excepción nueva debe
justificarse contra el Capítulo 7.

## Reglas de implementación

Los íconos se implementan como fuente vectorial o SVG inline (nunca como imagen rasterizada) y
siempre heredan `currentColor` — ningún ícono lleva un hex hardcodeado en el archivo fuente.

---

# Capítulo 7 — Motion Language

## Filosofía de movimiento

El movimiento explica, nunca decora. Toda animación responde a una de estas preguntas: ¿de
dónde vino este elemento? ¿a dónde va? ¿qué relación tiene con lo que el usuario acaba de
hacer? Si una animación no responde ninguna, se elimina. Maiek se mueve como alguien que sabe
exactamente lo que está haciendo — sin dudar, sin rebotar de más, sin llamar la atención sobre
sí mismo.

## Timing

| Token | Duración | Uso |
|---|---|---|
| `motion-instant` | 100ms | hover, focus, cambios de color |
| `motion-fast` | 150ms | toggles, checkboxes, micro-interacciones |
| `motion-base` | 220ms | transiciones estándar (aparecer/desaparecer, expandir) |
| `motion-slow` | 350ms | paneles, modales, cambios de vista completos |

Nunca superar 400ms en una interacción funcional — por encima, el usuario percibe lentitud, no
elegancia. Duraciones mayores solo en momentos editoriales puntuales (onboarding, celebración
de un cierre de venta), nunca en el uso diario.

## Curvas

| Token | `cubic-bezier` | Uso |
|---|---|---|
| `ease-out-expo` | `(0.16, 1, 0.3, 1)` | entradas — el elemento llega con energía y frena suave |
| `ease-in-out-soft` | `(0.65, 0, 0.35, 1)` | transiciones simétricas (cambios de estado, cross-fade) |
| `ease-spring` | `(0.34, 1.56, 0.64, 1)` | confirmaciones puntuales (con overshoot) — uso escaso, nunca en navegación rutinaria |

## Hover

Cambio de color o fondo en `motion-instant` (100ms), `ease-in-out-soft`. Nunca escala
(`transform: scale()`) en filas de tabla o ítems de lista — el escalado se reserva para
elementos aislados (un botón grande, una card de selección), nunca para contenido denso donde
un cambio de tamaño desalinea visualmente la fila vecina.

## Focus

El anillo de foco (2px, color primario del modo activo) aparece en `motion-instant`, sin
transición de posición — el foco de teclado tiene que sentirse inmediato, nunca "deslizarse"
hacia su lugar.

## Loading

Dos patrones, según duración esperada:

- **Menos de 400ms esperados**: sin indicador — mostrar un spinner para algo casi instantáneo
  genera más ansiedad que esperar en silencio.
- **Más de 400ms esperados**: skeleton (ver abajo) para contenido que ya tiene una forma
  conocida (una lista, una card); spinner solo para acciones puntuales sin layout propio
  (guardar, enviar).

Un spinner nunca gira a más de 1 vuelta por segundo — más rápido lee como error, no como
carga.

## Skeleton

Bloques neutros (`neutral-100` en claro / `neutral-700` en oscuro) con la misma geometría
exacta del contenido real que van a reemplazar (mismo alto de línea, mismo radio) — nunca
placeholders genéricos que no anticipan la forma final. Animación: un barrido de brillo sutil
(`opacity` 100%→70%→100% del bloque, o un gradiente que se desplaza) en un loop de 1.5s,
`ease-in-out-soft`. El skeleton desaparece con un cross-fade de `motion-base` (220ms) hacia el
contenido real — nunca un salto brusco.

## Microinteracciones

Un checkbox, toggle o radio cambia de estado en `motion-fast` (150ms). Un badge nuevo que
aparece en una lista (ej. "Nuevo" en una conversación) entra con un fade + leve desplazamiento
vertical de 4px, `motion-base`, `ease-out-expo` — nunca un rebote llamativo.

## Transiciones

Cambios de vista completos (navegar entre secciones) usan `motion-slow` (350ms) con
`ease-out-expo`. Un panel lateral o modal entra deslizándose desde su borde de origen (nunca
apareciendo en el centro sin desplazamiento) — el movimiento comunica de dónde vino ese
contenido.

## Estados

Toda transición de estado visual (reposo → hover → focus → activo → deshabilitado) respeta la
tabla de timing de arriba — nunca una transición instantánea (0ms) salvo en el estado
deshabilitado, que cambia sin animación (deshabilitar es un corte, no una transición).

---

# Glosario

Definiciones de referencia para los términos usados en este documento y en los que lo
sucedan:

- **Design Language (Lenguaje de diseño).** El conjunto de principios, valores y reglas
  visuales que definen cómo se ve y se siente un producto — precede a cualquier componente
  concreto. Es lo que este documento define. Deliberadamente distinto de un *Design System*
  (ver abajo): un lenguaje se puede tener sin todavía tener componentes construidos; un
  sistema, no.
- **Design System (Sistema de diseño).** La implementación concreta de un Design Language —
  componentes reales (botones, inputs, tablas), documentados y reutilizables en código. Es lo
  que la Fase 2 va a construir sobre este documento.
- **Design Token (Token de diseño).** Un valor de diseño con nombre — un color, un espaciado,
  un radio, un timing — que reemplaza un valor suelto ("8px") por un nombre semántico
  (`space-2`) reutilizable en todo el sistema.
- **Component (Componente).** Una pieza de interfaz reutilizable con estados propios definidos
  (botón, input, card) — no forma parte de este documento (ver Alcance).
- **Pattern (Patrón).** Una composición de varios componentes que resuelve una tarea completa
  (un formulario de login, una fila de tabla con acciones) — un nivel por encima del
  componente individual.
- **Hierarchy (Jerarquía).** El orden en que un usuario percibe la importancia relativa de los
  elementos en pantalla — se construye con tamaño, peso, posición y color, en ese orden (ver
  Capítulo 3).
- **Spacing (Espaciado).** La distancia entre elementos, siempre expresada como un token de la
  escala de 4px (ver Capítulo 3) — nunca un valor arbitrario.
- **Grid (Grilla).** La estructura invisible de columnas y unidad atómica que alinea todo
  elemento en pantalla (ver Capítulo 3).
- **Elevation (Elevación).** El nivel de profundidad de un elemento respecto al plano base de
  la pantalla, comunicado con sombra — usado para expresar orden de interacción, no estilo
  (ver Capítulo 3).
- **Surface (Superficie).** Un plano de fondo con un rol definido (página, card, popover) — ver
  tabla de superficies en el Capítulo 4.
- **Motion (Movimiento).** El conjunto de reglas de animación y transición del sistema —
  timing, curvas y su aplicación a estados de interfaz (ver Capítulo 7).
- **Interaction (Interacción).** Cualquier punto de contacto entre el usuario y la interfaz que
  produce una respuesta del sistema — un clic, un hover, un envío de formulario.
- **Accessibility (Accesibilidad).** El grado en que la interfaz es usable por personas con
  distintas capacidades — contraste, navegación por teclado, tamaño de texto, lectores de
  pantalla (ver Capítulo 3 y Capítulo 4).
- **Responsive (Responsivo).** La capacidad de una interfaz de adaptarse correctamente a
  distintos anchos de pantalla sin perder funcionalidad (ver Responsive Philosophy, Capítulo
  3).
- **Dark Mode (Modo oscuro).** Un segundo conjunto completo de tokens de color pensado desde
  cero para fondos oscuros — no una inversión automática del modo claro (ver Capítulo 4).
- **Visual Language (Lenguaje visual).** Sinónimo funcional de Design Language en este
  documento — el vocabulario visual compartido de todo producto Maiek AI.
- **Experience (Experiencia).** El resultado percibido por el usuario tras usar el producto —
  lo que el Capítulo 0 describe como "un día completo con Maiek". Un buen lenguaje visual es
  condición necesaria pero no suficiente para una buena experiencia; también depende de
  arquitectura de información, lógica de producto y contenido (fuera del alcance de este
  documento).
- **Breakpoint.** Un ancho de pantalla específico en el que el layout cambia de composición
  (ver Capítulo 3).
- **Tonal Scale (Escala tonal).** Los pasos de claridad/oscuridad de un mismo color (50 a 900)
  que permiten construir estados y variantes sin salir de la paleta (ver Capítulo 4).
- **Semantic Color (Color semántico).** Un color cuyo significado es fijo y universal en el
  sistema (éxito, error, advertencia, información) — deliberadamente separado de los colores
  de identidad de marca (ver Capítulo 4).

# Convenciones

**Terminología.** La prosa de este documento y de los que lo complementan se escribe en
español; los términos técnicos ya establecidos en la industria del diseño de producto se
mantienen en inglés (token, component, pattern, breakpoint, hover, spring) porque traducirlos
generaría más confusión que claridad — son las palabras que va a buscar cualquier diseñador o
desarrollador que se una al equipo.

**Nomenclatura.** Todo token sigue el patrón `categoría-variante` en minúsculas con guiones
(`space-4`, `text-body`, `radius-lg`, `motion-fast`) — nunca camelCase ni nombres descriptivos
sin categoría (`azulBoton` en vez de `color-primary-600`).

**Buenas prácticas.** Ningún valor suelto fuera de una escala ya definida. Si hace falta un
valor que no existe, se extiende la escala correspondiente (y se documenta acá, sumando una
fila) — nunca se improvisa un valor de una sola vez para una sola pantalla.

**Reglas para futuros documentos** de esta familia (Fase 2 en adelante):
- Formato de capítulos numerados para contenido normativo (reglas que se deben seguir), con
  control de versiones obligatorio desde el primer borrador.
- Todo valor incluido debe venir acompañado de su razón de ser — una tabla de valores sin
  justificación no es un estándar, es una lista.
- Ningún documento nuevo contradice a este sin una revisión explícita y una entrada nueva en
  el control de versiones de ambos documentos.

# Referencias

Referencias conceptuales de calidad — nunca a copiar, solo a tomar como nivel de exigencia:

- Apple Human Interface Guidelines
- IBM Carbon
- Material Design (únicamente como referencia conceptual — ver Capítulo 0 sobre lo que
  deliberadamente se evita de su vocabulario visual)
- Linear
- Notion
- Stripe (Dashboard)
- Vercel
- Figma

# Apéndices

Sección reservada para futuras ampliaciones del MDL — anexos de casos de uso, ejemplos de
implementación, decisiones puntuales que no ameritan un capítulo propio. Vacía en v1.1.

---

# Revisión técnica: Typography System (v1.1)

Antes de congelar este documento como estándar oficial, se validó técnicamente la decisión
tipográfica de v1.0 (Poppins + Nunito Sans) contra cinco alternativas ampliamente usadas en
plataformas SaaS modernas: **Inter**, **Geist**, **IBM Plex Sans**, **SF Pro** (como
referencia conceptual — Apple restringe su licencia a plataformas propias, no es una opción
real para una web multiplataforma) y las dos ya elegidas.

## Contexto de evaluación

Maiek AI no es un sitio editorial ni una landing de marketing — es una herramienta de trabajo
de uso diario y prolongado: tablas de datos (Gaso+ ya tiene vistas de hasta 18 columnas),
formularios, un chat de mensajería, y dashboards con cifras que se comparan en columna. El
criterio de peso principal es **legibilidad en interfaz de alta densidad**, no personalidad de
marca — ese rol ya lo cumple el sistema de color y el isotipo.

## Comparación por candidato

**Poppins.** Tipografía geométrica (formas basadas en círculos, familia de Century
Gothic/Futura). Excelente para wordmarks y titulares cortos — es, de hecho, la tipografía del
propio logotipo "Maiek AI". Pero las geométricas tienen un problema documentado en diseño de
tipos: al normalizar las letras a formas circulares en vez de a su forma óptica natural,
pierden distinción entre caracteres a tamaños chicos (13-14px, exactamente el rango de una
tabla densa) — no fue diseñada como tipografía de interfaz, sino de titulares.

**Nunito Sans.** Humanista, cálida, buena legibilidad en cuerpo de texto general. Pero su
ancho de caracter es más generoso que el de una tipografía de interfaz pura, lo que consume
más espacio horizontal en tablas densas, y sus funciones OpenType para cifras tabulares no
están tan pulidas como las de las alternativas construidas específicamente para software.

**Inter.** Diseñada explícitamente para pantallas — x-height alto, espaciado ajustado pero
legible a tamaños chicos, cifras tabulares nativas, cero ambigüo (zero con barra), variable
font (todos los pesos en un solo archivo, mejor rendimiento web), cobertura de idiomas y
acentos madura (crítico para español con tildes y eñe). Es la tipografía que usan, en alguna
forma, la mayoría de los productos citados como referencia de calidad (Linear, gran parte del
ecosistema Vercel, incontables dashboards SaaS). Riesgo real: es tan usada que corre el riesgo
de sentirse "el default seguro" en vez de una elección con personalidad propia.

**Geist.** La tipografía propia de Vercel (2023), diseñada específicamente para dashboards y
herramientas — coincide de forma literal con uno de los productos de referencia citados.
Geometría precisa y neutra, con una mono complementaria (Geist Mono) útil para mostrar
teléfonos, precios y códigos con precisión — encaja bien con el valor de marca "Precisión"
(Capítulo 0). Riesgo real: mucho más nueva que Inter, con menos años de uso probado a escala y
menos historial público de rendimiento en producción fuera del ecosistema Vercel.

**IBM Plex Sans.** Humanista con más carácter que Inter, muy legible, familia completa
(sans/serif/mono/condensed) y excelente soporte multi-script (IBM invirtió fuerte en
cobertura de idiomas). Coincide con IBM Carbon, citado en las Referencias de este mismo
documento. Riesgo real: su asociación con "IBM/enterprise" puede leerse más corporativa y
menos cálida que el valor de marca "cercanía humana" (Capítulo 0), si no se equilibra bien
con el resto del sistema.

**SF Pro.** El estándar de legibilidad de Apple y la vara con la que se miden las demás — pero
no es una opción real: su licencia no permite uso general en la web fuera de plataformas
Apple. Se mantiene solo como referencia conceptual de calidad, tal como pide el objetivo del
documento.

## Conclusión y decisión

**Poppins se conserva, pero se re-enfoca**: queda reservada a marca (wordmark, portadas,
momentos editoriales) — el rol para el que sí es la elección correcta, y en el que ya está
validada por el moodboard de identidad aprobado.

**Nunito Sans se reemplaza por Inter** para toda la interfaz de producto. Razón técnica
central: Inter es la tipografía con más historial probado exactamente en el contexto donde
Maiek AI vive todos los días — tablas densas, formularios, chat, cifras comparadas en columna
— con el balance más maduro entre legibilidad, rendimiento web (variable font) y cobertura de
español. Geist e IBM Plex Sans quedan documentados como alternativas serias y válidas — Geist
en particular, por su ajuste conceptual con "Precisión" y su mono complementaria, es la
primera opción a reevaluar en 12–18 meses si gana más historial de producción a esa escala.
La decisión no se tomó por preferencia estética sino por el criterio de menor riesgo para una
pieza de infraestructura que va a sostener años de pantallas: entre una tipografía más nueva y
conceptualmente más afín (Geist) y una más probada a escala con el mismo nivel de calidad
técnica (Inter), se prioriza la que ya demostró sostener productos de este mismo perfil de
densidad durante más tiempo.

Este cambio ya está reflejado en el Capítulo 5 (Typography System) de este documento.

---

## Recomendaciones para la Fase 08

1. **Fase 2 — Sistema de componentes.** Botones, inputs, selects, tablas, cards, badges,
   modales, formularios, chips, tooltips — construidos sobre los tokens de este documento
   (espaciado, radio, color, motion), no reinventando valores nuevos por componente.
2. **Especificación de patrones de producto**, ya con componentes definidos: el chat, el
   sidebar de navegación, el dashboard de KPIs, el copiloto de IA — cada uno como una
   composición de componentes de la Fase 2, no como pantallas diseñadas de forma aislada.
3. **Validación de accesibilidad real**, no solo documentada: auditar contraste, navegación
   por teclado y lectores de pantalla sobre implementaciones concretas una vez exista Fase 2.
4. **Tokens como código**, no solo como documento — convertir las tablas de este archivo en
   variables reales (CSS custom properties o equivalente) consumibles por el panel, incluyendo
   el set completo de dark mode.
5. **Prueba de contraste en dark mode con usuarios reales** antes de darlo por definitivo — los
   valores de este capítulo son un punto de partida razonado, no una medición final.
6. **Biblioteca de iconografía oficial** — elegir y licenciar el set outline definitivo (hoy
   el Capítulo 6 define reglas, no una librería específica).
7. **Aplicar el MDL a Gaso+ como piloto**, una vez exista Fase 2 — es el primer producto real
   sobre el que validar que este sistema sostiene una plataforma en producción, no solo una
   maqueta.

---

## Estado del documento

Este documento queda oficialmente congelado como:

**MAIEK DESIGN LANGUAGE — Versión 1.1 — Approved**

Fase 1 (Foundations) completa: filosofía, personalidad, foundations de layout, sistema de
color con dark mode, sistema tipográfico (revisado técnicamente), sistema de iconografía y
lenguaje de movimiento. No incluye componentes ni patrones de producto — eso es la fase
siguiente.

Cualquier modificación futura de fondo se realiza mediante control de versiones (tabla al
inicio de este documento) — nunca por edición silenciosa. Una versión "Approved" no es
inmutable; es la base estable sobre la que se construye, con cambios siempre trazables.

## Próximo Entregable

**Maiek Component System — Fase 2.**

**Por qué es necesario.** El MDL v1.1 define el lenguaje — los tokens, las reglas, la
personalidad — pero ninguna pantalla real se construye con un lenguaje solo: se construye con
componentes. Hoy, cualquier equipo que quisiera construir una pantalla nueva de Maiek AI tiene
las reglas pero no las piezas — cada botón, cada input, cada fila de tabla tendría que
inventarse desde cero, con el riesgo de que dos desarrolladores distintos interpreten el mismo
token de forma distinta. La Fase 2 cierra esa brecha.

**Objetivos principales:**
1. Especificar cada componente base (botón, input, select, checkbox, radio, toggle, badge,
   card, tabla, modal, tooltip, chip, avatar) con sus 5 estados (Capítulo 3) y su composición
   exacta de tokens del MDL — ningún componente introduce un valor fuera de las escalas ya
   definidas.
2. Definir las variantes necesarias de cada componente (primario/secundario/terciario en
   botones; tamaños en inputs) sin multiplicar variantes que no respondan a un caso de uso
   real del producto.
3. Documentar el comportamiento de cada componente en ambos modos (claro/oscuro) usando los
   tokens de dark mode ya definidos en el Capítulo 4.
4. Producir una referencia viva (no solo documento estático) — un componente que se pueda ver
   y probar, no solo describir en prosa, para reducir el margen de interpretación entre
   diseño y desarrollo.
5. Servir de base directa para el piloto en Gaso+ (recomendación #7 de la Fase 08 de este
   documento).

No se desarrolla este documento todavía — queda descrito acá como el siguiente paso oficial
del roadmap de Maiek AI.
