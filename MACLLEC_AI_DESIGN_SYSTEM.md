# Maçllec AI — Design System

> Depende de [`MACLLEC_AI_FRAMEWORK.md`](MACLLEC_AI_FRAMEWORK.md) y
> [`MACLLEC_AI_PLATFORM_ARCHITECTURE.md`](MACLLEC_AI_PLATFORM_ARCHITECTURE.md).
> Versión condensada del original — mismos principios y valores exactos, sin el formato de una idea por línea.
>
> **Estado: guardado solo como referencia.** Todavía NO está aplicado al panel de Gaso+ — el
> panel actual usa otra paleta (`#0e7490` navbar, `#f97316` acento). No aplicar estos valores al
> CSS real hasta que se confirme explícitamente.

## Propósito y filosofía

Define identidad visual, UX y principios de diseño/interacción de todos los productos Maçllec AI — prevalece sobre cualquier diseño puntual que lo contradiga. Maçllec AI hace software empresarial que nunca debe sentirse como un ERP antiguo: cada pantalla debe transmitir tecnología, innovación, inteligencia, rapidez, claridad, elegancia, confianza, productividad, automatización y simplicidad. Ligero, natural, moderno.

**Referencias de inspiración** (nunca copiar, solo inspirarse — construir identidad propia): Microsoft/Azure Portal, HubSpot, Salesforce, Linear, Notion, ClickUp, Stripe Dashboard, Supabase, Vercel, Figma.

## Design DNA

Toda pantalla debe cumplir:
1. El usuario la entiende en menos de 5 segundos.
2. La acción principal siempre es evidente.
3. Nunca mostrar información que no aporte valor.
4. Los datos importantes se destacan visualmente.
5. Las acciones frecuentes requieren el menor número de clics posible.
6. Toda interacción da una respuesta inmediata.
7. La plataforma debe sentirse más rápida de lo que realmente es.
8. La IA complementa el trabajo del usuario, nunca lo interrumpe.
9. Todo componente debe poder reutilizarse en cualquier producto de Maçllec AI.
10. Si un diseño no mejora la productividad del usuario, se replantea.

## Identidad visual

Maçllec AI es la empresa; cada producto tiene identidad propia bajo el paraguas de la marca: `Maçllec AI → Gaso+ → "Powered by Maçllec AI"`. El usuario siempre debe poder reconocer que usa una plataforma de Maçllec AI. Maçllec AI nunca compite visualmente con el producto — es un sello de calidad, no un logo protagonista.

## Paleta de colores

| Uso | Hex | Nombre |
|---|---|---|
| Primario | `#00A1DE` | Celeste institucional |
| Secundario | `#3CCBDA` | Aquamarina |
| Éxito | `#00A34B` | Verde |
| Advertencia | `#FAB200` | Amarillo |
| Error | `#EF4444` | Rojo |
| Texto principal | `#1F2937` | — |
| Texto secundario | `#6B7280` | — |
| Fondo | `#F8FAFC` | — |
| Cards | `#FFFFFF` | — |
| Bordes | `#E5E7EB` | — |

## Tipografía

Principal: **Inter**. Secundaria: **Isidora Sans**. Fallback: Segoe UI, Arial. Debe transmitir modernidad y excelente legibilidad.

## Principios UX

Menos clics, más productividad. Más información, menos ruido. Más claridad, menos aprendizaje. Más intuición. El usuario debe sentir la plataforma rápida, inteligente, organizada, moderna, consistente y profesional.

## Escala de espaciados

`4px · 8px · 12px · 16px · 24px · 32px · 48px · 64px` — nunca espaciados aleatorios fuera de esta escala.

## Bordes y sombras

Radio pequeño `8px`, estándar `12px`, grande `16px` — nunca bordes agresivos. Sombras suaves, nunca exageradas: el objetivo es separar elementos, no decorar.

## Componentes

- **Botones** — Primario: celeste, texto blanco, hover más oscuro, radio 12px, padding amplio. Secundario: blanco, borde celeste, texto azul. Terciario: solo texto, hover gris. Consistencia entre todos.
- **Inputs** — minimalistas, placeholder gris, focus azul, íconos internos, padding amplio, validaciones claras, errores discretos.
- **Cards** — componente principal de la plataforma: fondo blanco, mucho padding, sombra ligera, bordes suaves, header limpio, acciones discretas, microanimaciones. Nunca cajas pesadas.
- **Tablas** — modernas: hover suave, filas aireadas, badges, acciones con íconos, filtros rápidos, paginación elegante, búsqueda integrada.
- **Dashboard** — se siente como un SaaS: widgets independientes, KPIs grandes, gráficos limpios, mucho espacio, filtros superiores, resumen ejecutivo, sin saturar información.
- **Sidebar** — colapsable, minimalista, iconografía consistente, accesos rápidos, favoritos, estados activos claramente visibles.
- **Header** — muy limpio: buscador global, perfil, notificaciones, breadcrumb, acciones rápidas.
- **Iconografía** — Lucide Icons, estilo outline, consistente — nunca mezclar librerías.
- **Badges** — colores consistentes por estado: Activo=verde, Pendiente=amarillo, Error=rojo, Información=celeste. Nunca colores arbitrarios.
- **Modales** — pequeños, enfocados, no abusar de ellos; siempre mostrar clara la acción principal.
- **Formularios** — máximo una columna cuando sea posible, agrupar información relacionada, reducir esfuerzo visual, mostrar ayuda contextual.
- **Animaciones** — muy sutiles (fade, scale, hover, skeleton loading) — nada exagerado, nunca distraer.

## Responsive y accesibilidad

Desktop primero, tablet optimizado, mobile funcional — nunca sacrificar productividad por estética. Contrastes adecuados, tamaño mínimo de fuentes, estados visibles, navegación por teclado cuando sea posible, mensajes claros.

## Branding por producto

Cada producto tiene su propia identidad (ej. "Gaso+ — Commercial Operating System — Powered by Maçllec AI").

## Microcopy

Textos cortos, claros, profesionales, positivos, orientados a la acción — evitar lenguaje técnico innecesario.

## Funcionalidades de IA

Deben diferenciarse visualmente (brillos suaves, iconografía específica, indicadores de procesamiento, estados de generación) pero sin parecer un chatbot genérico — la IA debe sentirse integrada en el producto, no como un widget aparte.

## Design thinking — antes de diseñar cualquier pantalla

¿Cuál es el objetivo del usuario? ¿Qué necesita hacer? ¿Cuántos clics requiere? ¿Puede simplificarse? ¿Existe ya un componente reutilizable? ¿Respeta este Design System?

## Regla final

Diseñar productos que un usuario quiera usar todos los días. Cada pantalla debe transmitir confianza, inteligencia y simplicidad. No diseñar solo interfaces — diseñar experiencias.
