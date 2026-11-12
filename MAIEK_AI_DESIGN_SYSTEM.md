# Maiek AI — Design Language (MDL)

**Versión 1.4 · Official Design Standard**

| | |
|---|---|
| Documento | Maiek Design Language (MDL) |
| Proyecto | Maiek AI |
| Versión | 1.4 (borrador — decisiones D1 a D19 aprobadas; falta el commit de la v1.4) |
| Estado | **Approved** hasta v1.2; la Revisión v1.3 distingue decisiones «Aprobadas» de «Propuestas» |
| Fecha de creación | 2026-07-26 |
| Autor | Claude, a pedido de Jesús Millones |
| Última actualización | 2026-11-12 |

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
| 1.3 | 2026-11-12 | Claude, a pedido de Jesús Millones | **Consolidación y dirección visual «E»** (ver «Revisión v1.3» abajo): una sola paleta vigente verificada con una matriz de contraste de 72 pares (claro y oscuro), registro de las decisiones del producto que el código ya aplicaba y el MDL no documentaba (tipografía, escala de texto, tamaño mínimo), y diecisiete decisiones aprobadas el 2026-11-12, D1 a D17 (tinta Navy, menú claro y desplegable, radios «Moderada», etiquetas y avatares, movimiento, enlaces, gris único, indicadores de estado, pila tipográfica, escala de texto, selector de densidad, táctil por puntero, base oscura «tinta neutra» y colores de etapa). Solo queda como «Propuesta» la definición de las escalas de 7 pasos de la paleta v1.2. **La aplicación a `tailwind.config.ts`/`globals.css` de `maiek-frontend` queda fuera de esta revisión documental** — paso posterior con su propia aprobación. |
| 1.4 | 2026-11-12 | Claude, a pedido de Jesús Millones | **Tipografía de producto.** El dueño revisó la v1.3 aplicada en su entorno con datos reales y reabrió la tipografía: tras comparar 14 candidatas en su pantalla (ancho, cifras tabulares, tildes y pesos medidos en vivo), se adopta **Nunito Sans** en todos los sistemas (D18, reemplaza a D12) y el cuerpo de las tablas al **90 % de ancho** con el eje `wdth` de la misma familia (D19). No cambia nada más de la v1.3. |

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

# Revisión v1.3 — Consolidación y dirección visual «E»

*Fecha: 2026-11-12. Origen: auditoría de UX de `maiek-frontend`, matriz de contraste de los tokens
reales y cuatro rondas de maquetas aprobadas por el dueño.*

La arquitectura de tres capas (identidad / semántica / superficie) y los roles de token **no
cambian**. Esta revisión hace tres cosas: (1) deja **una sola fuente de verdad** donde v1.1 y
v1.2 se contradecían, (2) **registra** decisiones que el producto ya aplicaba y el documento no
decía, y (3) **suma** la dirección visual «E» (calma, tinta oscura única, color solo en los
datos). Las secciones antiguas no se borran: llevan una nota «v1.3» que apunta aquí.

## Estado de cada decisión

| Estado | Significado |
|---|---|
| **Aprobada** | Elegida por el dueño el 2026-11-12 sobre maqueta. Norma de este documento. |
| **Registrada** | Ya vigente en el código; se documenta sin cambiarla. |
| **Propuesta** | Presentada con evidencia, **sin aprobar**. No es norma hasta que el dueño la apruebe. |

## Decisiones aprobadas (2026-11-12)

| ID | Decisión | Detalle |
|---|---|---|
| D1 | Dirección «E» | Superficies casi blancas separadas por borde de 1 px; **sin sombra en reposo** (elevación 0 del Capítulo 3; hoy el código usa `elevation-card`, que se alinea al aplicar); una sola tinta de acción; color reservado a los datos; panel de contexto a la derecha con pestañas en cápsula. |
| D2 | Tinta = **Navy `#102A56`** | Botón primario, ítem activo del menú, burbuja enviada y botón Enviar. Blanco sobre Navy = 14.12:1. En modo oscuro la tinta es `#E4ECFA` con texto `#0E1623` (15.27:1, ver D16). Azul Primary/Strong se conservan para enlaces, foco e indicadores; el rol `primary-solid` pasa a significar la tinta. |
| D3 | Menú lateral **claro** | Fondo `surface-1`, borde derecho de 1 px, ítem activo en píldora de tinta. Reemplaza al Sidebar Navy. |
| D4 | Menú **desplegable** | Barra de íconos de 48 px; un panel de casos (≈184 px, múltiplo de 8, a fijar al implementar) entra **por encima** del contenido, sin reacomodarlo: `translateX(-8px → 0)` y opacidad en `motion-base`, `ease-out-expo`. |
| D5 | Radios «**Moderada**» | `radius-md` 10 → **8 px** (botones, campos, pestaña interna, ítems); `radius-lg` 14 → **12 px** (tarjetas, compositor, burbujas, pista de pestañas, popovers); `radius-sm` 6 px (etiquetas); `radius-xl` 20 px sin cambio (modales y hojas, no evaluados en maqueta); `radius-full` solo para avatares, interruptores, contadores y acciones rápidas. Las maquetas usaron 10/7 en las pestañas: se normalizan a 12/8 para no salir de la escala. |
| D6 | Etiquetas **rectangulares** | `radius-sm` (6 px), fondo tinte suave + texto de la misma familia (pares verificados en la matriz). La píldora completa se reserva a contadores y acciones rápidas. |
| D7 | Avatar **círculo** | `radius-full`, iniciales sobre tinte suave (mismos pares que las etiquetas). |
| D8 | Reglas de **movimiento** | (a) Entrada escalonada solo en pantallas ocasionales (Copiloto, estados vacíos): `translateY(8px → 0)` + opacidad, `motion-base`, `ease-out-expo`, 70 ms entre elementos, máximo ~10. (b) Regla de frecuencia: lo que se usa decenas de veces al día (menú, lista de chats, filas de tabla) no se anima o dura como máximo `motion-instant`. (c) Botones: estado presionado `scale(0.97)` en `motion-instant`, solo `transform`. (d) `prefers-reduced-motion` desactiva a), b) y c). Las maquetas usaron 240/120 ms: se normalizan a los tokens 220/100 ms. |
| D9 | **Enlaces** (antes P1, aprobada el 2026-11-12 sobre maqueta en contexto) | Rol nuevo `primary-text`: `#0057D9` en claro y `#7DB1FF` en oscuro. `#0072FF` queda para foco, relleno e íconos, donde no hay texto encima. Enlace hoy 4.33 sobre tarjeta, 3.59 sobre hover y 3.87 sobre fila activa; con D9: 6.24 / 5.17 / 5.57. En oscuro: 4.24 y 3.51 → 5.72 y 4.73. |
| D10 | **Un solo gris de apoyo** (antes P2, aprobada el 2026-11-12 sobre maqueta en contexto) | El texto secundario y el atenuado se fusionan: `#5B6578` en claro y `#C3CCDA` en oscuro. La jerarquía la dan el tamaño y el peso (12 px frente a 13 px), no un gris más pálido. Claro: sobre hover 4.13 → 4.87 y sobre fila activa 4.44 → 5.24. Oscuro: el atenuado `#9AA3B2` daba 4.07 sobre la fila activa; `#C3CCDA` pasa en todos los fondos. |
| D11 | **Indicadores de estado** (antes P3, ampliada y aprobada el 2026-11-12 sobre maqueta en contexto) | Todo indicador de estado lleva **ícono y palabra** además del color (el Capítulo 3 ya prohibía comunicar un estado solo por color). En modo claro los colores pasan a verde `#00853D`, ámbar `#9A6B00` y rojo `#D73939` (3.8 a 4.7 sobre tarjeta, hover y fila activa; umbral 3:1). Los puntos de hoy daban 1.84 (ámbar sobre blanco), 1.52 (ámbar sobre hover) y 2.75 (verde sobre hover). El modo oscuro no cambia (5.0 a 8.2). Frescura del Pipeline: ✓ «Al día», reloj «Atención», ⚠ «Atrasado». |
| D12 | **Pila tipográfica** (antes P4, aprobada el 2026-11-12 sobre muestra comparativa; **reemplazada el mismo día por D18**) | Se documenta la pila que el código aplica desde el 2026-10-31: `"Segoe UI Variable Text"`, `"Segoe UI"`, Inter (cargada con `next/font`), `-apple-system`, Arial. En Windows se ve Segoe UI, más definida a 12–14 px por su ajuste fino (comprobado en la laptop del dueño); en los demás sistemas, Inter. Poppins solo en la marca, nunca en tablas ni párrafos. Reemplaza la frase «Producto: Inter» del Capítulo 5. |
| D13 | **Escala de texto** (antes P5, aprobada el 2026-11-12 sobre ficha comparativa) | `text-caption` pasa de 11 a **12 px** (el código ya lo aplica). Roles: **12 px** metadato suelto (hora, etiqueta, chip, rótulo de campo); **13 px** frase que se lee (avisos, instrucciones, descripciones, filas densas de tabla); **14 px** cuerpo (mensajes, nombres, texto principal); 16 px formularios y cuerpo destacado; 18 a 28 px títulos, sin cambio. Un aviso de 12 px junto a burbujas de 14 se ve fuera de escala (hallazgo del 2026-11-02). **Prohibidos los tamaños sueltos** (`text-[Npx]`; hoy hay 0 en los componentes). Pesos sin cambio: 400, 500, 600 (700 solo en displays). Reemplaza el «mínimo de fuente 11px sin excepción» del Capítulo 3. |
| D14 | **Selector de densidad** (antes P6, aprobada el 2026-11-12 sobre simulador) | Selector por usuario con tres opciones: **Automática** (por defecto; se comporta como la variante `corto:` de hoy: compacta con ventana de menos de 700 px de alto y puntero fino, nunca en pantalla táctil), **Cómoda** (fuerza filas amplias) y **Compacta** (fuerza filas apretadas). La compacta solo ajusta tamaños y espacios; nunca oculta ni reordena contenido; conserva el piso de 13 px en frases y 32 px de alto en controles con mouse. Las alturas de fila se miden en las pantallas reales antes de fijarlas. Implementación: se redefine la variante `corto:` para que responda también a un atributo del usuario, sin tocar sus usos actuales; dónde se guarda la preferencia (navegador o cuenta) se decide al implementar. Complementa las «dos densidades» del Capítulo 3: la elección deja de ser solo por contexto y pasa también al usuario. |
| D15 | **Tamaño táctil por tipo de puntero** (antes P7, aprobada el 2026-11-12 sobre simulador de cinco dispositivos) | La decisión deja de depender del ancho de pantalla: **44 px con `pointer: coarse`** (táctil) en cualquier ancho y **32 px con `pointer: fine`** (mouse o touchpad). Piso absoluto de **24 px** con separación entre objetivos (WCAG 2.2, criterio 2.5.8), también en densidad Compacta. Los íconos pequeños (por ejemplo ⋯) conservan su dibujo, con un área de toque invisible de 44 px. Con pantalla táctil mandan los 44 px aunque la densidad sea Compacta. Antes: 44 px por debajo de 768 px y 32 px desde 768 px, de modo que una tablet horizontal táctil recibía 32 px y una ventana angosta con mouse recibía 44 px. Reemplaza «Área mínima de toque: 32px en desktop, 44px en mobile» del Capítulo 3. |
| D16 | **Base del modo oscuro: «tinta neutra»** (antes parte de P8, aprobada el 2026-11-12 sobre tres opciones; se eligió la C) | Las superficies oscuras dejan la paleta v1.1 (azul profundo `#0B1D3A`) y pasan a un casi negro azulado: **página `#0E1623`, tarjeta `#141F31`, popover y hover `#1C2A41`, fila activa `#1D3557`**; divisor `#273650`; borde de control `#6A83A8` (4.69 / 4.27 / 3.72 sobre página / tarjeta / popover). El Navy de marca `#102A56` queda como acento (tinta y logo), no como superficie. El texto sobre la tinta clara `#E4ECFA` pasa a `#0E1623` (15.27:1). Todo el texto aprobado (texto `#F2F4F7`, gris `#C3CCDA`, enlace `#7DB1FF`) pasa 4.5:1 sobre las cuatro superficies; la separación visual entre tarjeta y página es baja (1.10:1) y se compensa con el borde fino. Reemplaza las tablas de superficies y de Dark Mode de la v1.1 en lo que toca a los fondos. |
| D17 | **Colores de etapa del Pipeline** (antes P9, aprobada el 2026-11-12 sobre maqueta en claro y oscuro) | Las etapas se muestran como etiquetas rectangulares (D6), con fondo suave y texto de la misma familia, y siempre con su palabra: **Con Gabi** = Cian (el color reservado a la IA), **Con asesora** = Azul, **Agendado** = Navy, **Vendido** = Éxito, **Cerrado** = Neutro; **Sin asignar** o atrasado = Advertencia. La barra de proporción y la leyenda del Pipeline usan los mismos colores. Todos los pares pasan 4.5:1: claro 5.24 · 5.57 · 11.04 · 5.59 · 5.63 · 5.33; oscuro 6.94 · 5.78 · 7.74 · 4.61 · 7.56 · 7.41. Los colores de los roles de Equipo (Administrador, Supervisor, Asesor) no se definen en esta revisión. |
| D18 | **Tipografía de producto: Nunito Sans** (v1.4, aprobada el 2026-11-12 tras ver 14 candidatas en su pantalla y el producto real; **reemplaza a D12**) | Toda la interfaz de trabajo usa **Nunito Sans**, en todos los sistemas, como fuente variable cargada con `next/font`; Poppins sigue solo en la marca. Pila: `var(--font-nunito)`, `system-ui`, `-apple-system`, `"Segoe UI"`, Arial. Motivos medidos en la pantalla del dueño (13 px, Segoe UI como referencia): +2.1 % de ancho en peso normal y −0.4 % en negrita, con tildes completas y **cifras tabulares por defecto**; carácter redondeado y cercano, como las apps de mensajería. Descartadas: **DM Sans** (sin cifras tabulares), Geist, Figtree, Plus Jakarta Sans e Inter (más anchas) y la mezcla con una segunda familia para tablas (el MDL prohíbe una tercera familia). Reabre y reemplaza la decisión del 2026-10-31 (Segoe UI + Inter). Riesgo conocido: trazos finos a 12–13 px en peso normal; se vigila en las tablas. |
| D19 | **Tablas densas al 90 % de ancho** (v1.4, aprobada el 2026-11-12) | Dentro de la misma familia, el cuerpo de las tablas usa el eje de ancho de Nunito Sans al **90 %** (`font-stretch: 90%`): −6.4 % de ancho de texto medido (95 % da −3.2 %, 85 % da −9.5 %; no se baja de 85 % por legibilidad a 12–13 px). Los encabezados se quedan al 100 %. Aplica al componente `Table` (Pipeline, Equipo, Productos, Analítica, Historial, Campañas, Uso); el resto de la interfaz va al 100 %. Es la misma familia, no una tercera. |

## Decisiones propuestas (pendientes de aprobación)

| ID | Propuesta | Evidencia |
|---|---|---|
| P8 | Escalas de 7 pasos de Azul Primary, Azul Strong, Cian, Navy y Dorado Acento (quedaron pendientes en v1.2). | No bloquea nada; se definen al aplicar, con verificación de contraste. |

## Registrado: lo que el código ya aplicaba

| Tema | Valor vigente en el código | Dónde |
|---|---|---|
| Texto atenuado | `#5B6578` (antes neutral 600 `#626C7E`) | `globals.css` |
| Borde de controles (WCAG 1.4.11, 3:1) | `#858FA1` claro, `#5A7FB5` oscuro; los divisores `#E1E5EB` quedan decorativos | `globals.css` |
| Fondo del botón destructivo | `#D73939` (blanco encima 4.63:1) | `globals.css` |
| Cian como texto | `#07708F` claro, `#62D0FA` oscuro | `globals.css` |
| Semánticos en oscuro | texto de Éxito `#00AC4F`, Error `#F57474`, Información `#4D96FF` | `globals.css` |
| Tamaño mínimo de texto | 12 px (`text-caption` pasó de 11 a 12) | `tailwind.config.ts` |
| Frases que se leen | 13 px mínimo; 12 px solo para metadatos sueltos | `CLAUDE.md` de `maiek-frontend` |
| Foco, movimiento reducido, alto contraste, impresión | `:focus-visible` de 2 px, `prefers-reduced-motion`, `forced-colors`, `@media print` | `globals.css` |

## Matriz de contraste verificada (2026-11-12)

Fórmula WCAG 2.x sobre sRGB, valores exactos. Umbrales: 4.5:1 texto de cuerpo, 3:1 elementos
de interfaz. «✗» = bajo el umbral. Se evaluaron 72 pares de los tokens reales; 20 quedan bajo
el umbral: 7 son divisores decorativos (exentos), 2 son el borde de control sobre fondos de
hover y de fila activa (2.70 y 2.91; candidato `#7A8498`, 3.12 sobre hover) y 11 se corrigen
con D9–D11 (algunos pares comparten fondo y se cuentan dos veces en el oscuro).

| Modo | Par | Hoy | v1.3 |
|---|---|---|---|
| Claro | Texto principal `#141A26` / página | 16.66 | sin cambio |
| Claro | Texto secundario / tarjeta · hover · fila activa | 4.97 · **4.13 ✗** · **4.44 ✗** | D10: 5.87 · 4.87 · 5.24 |
| Claro | Enlace / tarjeta · hover · fila activa | **4.33 ✗** · **3.59 ✗** · **3.87 ✗** | D9: 6.24 · 5.17 · 5.57 |
| Claro | Blanco / Azul Strong · Navy (tinta) | 6.24 · 14.12 | sin cambio |
| Claro | Borde de control / página · tarjeta · hover · fila activa | 3.12 · 3.26 · **2.70 ✗** · **2.91 ✗** | páginas y tarjetas sin cambio; hover y fila activa por definir (`#7A8498`: 3.12 sobre hover) |
| Claro | Indicador de advertencia / tarjeta | **1.84 ✗** | D11: 4.69 (`#9A6B00`; verde `#00853D` 4.75 y rojo `#D73939` 4.63 sobre tarjeta) |
| Claro | Etiquetas (texto / fondo): Con Gabi · Con asesora · Agendado · Vendido · Cerrado · Advertencia | — | 5.24 · 5.57 · 11.04 · 5.59 · 5.63 · 5.33 |
| Oscuro | Enlace / tarjeta · popover · fila activa (hoy: base v1.1) | 5.13 · **4.24 ✗** · **3.51 ✗** | D9 sobre la base D16: 7.56 · 6.59 · 5.65 |
| Oscuro | Texto atenuado `#9AA3B2` / fila activa (hoy: base v1.1) | **4.07 ✗** | D10, gris único `#C3CCDA` sobre la base D16: página 11.20 · tarjeta 10.21 · popover 8.90 · fila activa 7.63 |
| Oscuro | Tinta `#E4ECFA` / página · tarjeta (base D16) | — | 15.27 · 13.92 |
| Oscuro | Borde de control / página · tarjeta · popover | 4.11 · 3.70 · 3.06 | D16 `#6A83A8`: 4.69 · 4.27 · 3.72 |
| Oscuro | Etiquetas: Con Gabi · Con asesora · Agendado · Vendido · Cerrado · Advertencia | — | 6.94 · 5.78 · 7.74 · 4.61 · 7.56 · 7.41 |

Límites de esta matriz: usa los hex del código y de las maquetas, no mide píxeles renderizados;
la verificación final en navegador (axe) se hace al aplicar.

## Qué reemplaza esta revisión

| Sección antigua | Qué pasa con ella |
|---|---|
| Capítulo 3 · Border radius | Valores `md` y `lg` reemplazados por D5. |
| Capítulo 3 · Sombras | Tarjetas en reposo sin sombra (D1). Las sombras de nivel 2 a 4 siguen para elementos flotantes. |
| Capítulo 3 · Accesibilidad | «11 px sin excepción» reemplazado por D13 y «área de toque» por D15. |
| Capítulo 3 · Densidad de información | Complementada por D14 (selector por usuario). |
| Capítulo 4 · Contraste, Estados, Fondos, Dark Mode | Los valores v1.1 de esas tablas son históricos; vale la matriz de arriba y D16 para los fondos oscuros. La promesa «ninguna combinación baja de 4.5:1» se cumple con D9–D11. |
| Capítulo 5 · Familia y escala | Ver D18 (fuente), D19 (tablas) y D13 (escala). |

## Dependencias

Al aplicar esta revisión deben alinearse los documentos derivados, que solo especializan este
contrato: `MAIEK_AI_COMPONENT_SYSTEM.md` (Button, Badge/Tag, Avatar, Tabs, Sidebar, Card) y
`MAIEK_AI_PRODUCT_PATTERNS.md` (Shell y navegación). No se tocan hasta que el dueño apruebe la
aplicación.

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

> **v1.3 (D5):** `radius-md` pasa a 8 px y `radius-lg` a 12 px; las etiquetas son
> rectangulares (`radius-sm`) y `radius-full` queda para avatares, interruptores, contadores y
> acciones rápidas. Ver «Revisión v1.3».

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

> **v1.3 (D13 y D15, aprobadas el 2026-11-12):** mínimo de fuente 12 px (el código ya lo
> aplica) y área de toque según el tipo de puntero (44 px táctil, 32 px mouse, piso absoluto de
> 24 px). Reemplazan la frase anterior; ver «Revisión v1.3».

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

> **v1.3:** los valores de esta sección son los de v1.1 y la afirmación anterior no se cumplía
> con la paleta v1.2 (ver la matriz verificada en «Revisión v1.3»). Vale la matriz.

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

> **v1.4 (D18 y D19, aprobadas el 2026-11-12):** la fuente de producto es **Nunito Sans** en todos los
> sistemas (reemplaza a Segoe UI + Inter, D12), y el cuerpo de las tablas la usa al 90 % de ancho. Poppins
> sigue solo en la marca. Ver «Revisión v1.3».

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

> **v1.3 (D13, aprobada el 2026-11-12):** `text-caption` es de 12 px en el código desde que 11 px resultó
> ilegible en móvil. Frases que se leen: 13 px mínimo; 12 px solo para metadatos sueltos.

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
