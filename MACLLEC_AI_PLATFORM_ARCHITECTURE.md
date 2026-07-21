# Maçllec AI Platform — Arquitectura Oficial

> Depende de [`MACLLEC_AI_FRAMEWORK.md`](MACLLEC_AI_FRAMEWORK.md) (Master Framework).
> Versión condensada del original — mismos principios, sin el formato de una idea por línea.

## Propósito

Maçllec AI Platform es la base tecnológica sobre la que se construyen todos los productos de Maçllec AI. Ningún producto se desarrolla desde cero — todos reutilizan los servicios, componentes y módulos definidos por la Platform. La plataforma es el núcleo tecnológico de la empresa; los productos solo agregan conocimiento específico del negocio.

## Visión

Evolucionar hasta ser un **Enterprise Operating Platform** capaz de soportar múltiples productos, industrias y clientes sin modificar su núcleo. Toda decisión técnica debe acercar la plataforma a esa visión.

## Principios de arquitectura

- **Modular** — cada funcionalidad existe como módulo independiente, activable/desactivable sin afectar el resto del sistema.
- **Escalable** — soporta el crecimiento de usuarios, empresas y productos; nunca se diseña pensando solo en el cliente actual.
- **Reutilizable** — todo componente debe poder usarse en varios productos; si sirve para más de uno, va dentro de Maçllec AI Platform.
- **Desacoplada** — los productos nunca dependen directamente entre sí, todos consumen los servicios comunes de la plataforma.
- **Extensible** — permite agregar módulos nuevos sin modificar la arquitectura existente.

## Arquitectura general

```
Maçllec AI → Maçllec AI Platform → Servicios Compartidos → Productos → Clientes
```

La plataforma es el corazón, los productos son implementaciones, los clientes son configuraciones.

## Las 5 capas de la plataforma

1. **Core Platform** — autenticación, usuarios, roles, permisos, empresas, configuraciones, sesiones, seguridad, auditoría, logs.
2. **Business Services** — CRM, clientes, leads, ventas, pedidos, cotizaciones, catálogo, inventario, financiamiento, reportes, campañas, automatizaciones, agenda, documentos.
3. **AI Services** (Maçllec AI Intelligence) — agentes IA (Claude, GPT), predicciones, recomendaciones, copilot, respuestas automáticas, clasificación, análisis, resúmenes, generación de contenido, análisis documental, búsquedas inteligentes.
4. **Communication Services** — WhatsApp, correo, SMS, llamadas, notificaciones, push, chat, Meta, integraciones, webhooks.
5. **Analytics** — dashboard, KPIs, Power BI, indicadores, embudos, conversiones, forecast, análisis comercial, machine learning.

## Productos y clientes

Los productos nunca desarrollan funcionalidades comunes, solo agregan conocimiento específico. Ejemplo: Gaso+ utiliza CRM, Dashboard, IA, Usuarios, Catálogo, Permisos, Notificaciones y Reportes — todo proveniente de Maçllec AI Platform.

Cada cliente solo personaliza branding, catálogo, procesos, usuarios, permisos, integraciones, reglas y campañas — nunca modifica el núcleo.

## Dónde va cada funcionalidad nueva (Product Thinking)

Antes de implementar algo, clasificarlo en uno de 3 niveles:
- **Nivel 1 — Plataforma**: capacidad reutilizable para cualquier producto.
- **Nivel 2 — Producto**: capacidad exclusiva de un producto (ej. Gaso+).
- **Nivel 3 — Cliente**: configuración, branding o reglas específicas de una empresa.

Nunca implementar directamente una solución de Nivel 3 sin evaluar antes si puede convertirse en una capacidad de Nivel 2 o Nivel 1. Siempre proponer la alternativa más escalable cuando sea posible — el objetivo es construir productos, no proyectos personalizados.

**Reutilización primero:** antes de construir un componente, verificar si ya existe uno similar — si existe, reutilizarlo; si no, desarrollarlo pensando en futuros productos.

## Componentes UI

Todos los componentes visuales (botones, cards, inputs, selects, badges, modales, sidebars, navbar, widgets de dashboard, charts, tablas, calendarios, filtros, stepper, wizard) deben pertenecer a una biblioteca común y ser reutilizables — ningún componente nuevo se construye pensando solo en una pantalla puntual.

## Base de datos

Diseñada para soportar múltiples empresas — nunca asumir un único cliente. La arquitectura debe ser **Multi Tenant Ready** aunque inicialmente exista un solo cliente.

**Nota de estado (no parte del documento original):** el esquema actual de Gaso+ (`agent/memory.py`) es de un solo tenant — no existe concepto de "empresa" en las tablas de leads, usuarios ni campañas. Esto es una diferencia real con el documento, no algo ya resuelto; no toco la base de datos para esto salvo que se pida explícitamente empezar esa migración.

## Seguridad

Toda funcionalidad respeta roles, permisos, autenticación, auditoría, registro de acciones, control de acceso y trazabilidad.

## API

Enfoque **API First** — toda funcionalidad debe poder exponerse por API, y toda integración futura debe consumir los mismos servicios.

## Inteligencia artificial

La IA nunca es un módulo aislado, es una capacidad transversal de toda la plataforma — puede intervenir en CRM, ventas, campañas, dashboard, catálogo, clientes, WhatsApp, leads, reportes, automatizaciones, documentos, búsquedas y predicciones.

## Experiencia de usuario

Consistente entre todos los productos — alguien que ya conoce Gaso+ debe sentirse cómodo usando cualquier otro producto de Maçllec AI.

## Roadmap por fases

1. Base tecnológica
2. CRM
3. Automatizaciones
4. IA Comercial
5. Analytics
6. Marketplace de módulos
7. SDK para terceros

## Regla principal

Nunca desarrollar pensando únicamente en el presente — toda decisión técnica debe fortalecer Maçllec AI Platform y facilitar la creación de futuros productos y clientes. Cada línea de código debe incrementar el valor de la plataforma.
