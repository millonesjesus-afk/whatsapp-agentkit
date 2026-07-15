# Cliente: Cálidda — Client Framework

> Depende de [`CONVERTIA_FRAMEWORK.md`](CONVERTIA_FRAMEWORK.md),
> [`CONVERTIA_PLATFORM_ARCHITECTURE.md`](CONVERTIA_PLATFORM_ARCHITECTURE.md),
> [`CONVERTIA_DESIGN_SYSTEM.md`](CONVERTIA_DESIGN_SYSTEM.md) y
> [`GASOPLUS_PRODUCT_FRAMEWORK.md`](GASOPLUS_PRODUCT_FRAMEWORK.md).
> Versión condensada del original — mismos principios, sin el formato de una idea por línea.
>
> **Guardado solo como referencia — nada de este documento se agrega a Gabi** (ni a `/knowledge`
> ni a `config/prompts.yaml`). Es conocimiento de configuración del panel/CRM interno, no
> contenido para conversaciones de WhatsApp con clientes.

## Propósito

Define el conocimiento específico del negocio de Cálidda necesario para configurar Gaso+ — nunca modifica el producto, solo lo adapta. Ante conflicto con los Frameworks superiores de ConvertIA, estos prevalecen siempre. Las reglas específicas de Cálidda nunca deben incorporarse directamente al producto ni a ConvertIA Platform — quedan documentadas solo aquí.

## Cliente

Cálidda — distribución de Gas Natural — Lima Metropolitana y Callao. Implementación enfocada en la unidad de Gasodomésticos: gestionar integralmente la comercialización de productos y servicios asociados al gas natural, para aumentar productividad, trazabilidad, automatización y toma de decisiones.

## Categorías de producto

Agua caliente (termas), cocina (encimeras, cocinas, hornos, campanas), lavado (secadoras), servicios (punto de gas, ducterías), combos y promociones. El catálogo debe ser completamente parametrizable.

## Modalidades comerciales

El negocio opera bajo distintas modalidades: **GSD**, **FNB**, **CrediCálidda** — cada una con políticas/reglas propias, que deben ser parametrizables, nunca código fijo.

**Pendiente:** el documento original no define qué es cada modalidad (GSD/FNB/CrediCálidda) — quedó pendiente que el usuario las explique antes de evaluar si aplica agregar algo al prompt de Gabi (hoy Gabi solo maneja financiado 40% TEA vs. contado).

## Canales

Alo Cálidda, instaladores aliados, tiendas, call center, WhatsApp, Meta, SMS, landing pages, campañas, referidos — nuevos canales podrán incorporarse después.

**Nota de estado:** hoy el código solo tiene el canal WhatsApp (vía Meta Cloud API) — el resto (Alo Cálidda, tiendas, call center como canal de entrada, landing pages) es visión, no algo construido.

## Perfiles de usuario

Ejecutivos comerciales, supervisores, marketing, administradores, back office, instaladores, proveedores, gerencias — cada uno ve solo la información necesaria para su función.

**Nota de estado:** el código hoy solo tiene roles admin/supervisor/asesor.

## Clientes (entidad)

Toda la información del cliente debe centralizarse como una entidad única: datos personales, historial, productos, conversaciones, pedidos, cotizaciones, seguimientos, campañas, financiamiento, documentos, interacciones.

## Proceso comercial

Debe cubrir todo el ciclo, trazable de punta a punta: captación, calificación, contacto, seguimiento, cotización, venta, programación, entrega, instalación, validación, postventa, fidelización.

**Nota de estado:** hoy el sistema cubre bien captación → calificación → contacto → seguimiento → venta (registro manual). Programación, entrega, instalación, validación y postventa como etapas propias no existen todavía — hoy la venta se registra y ahí termina el flujo en el panel.

## Pedidos

Deben administrar estado, productos, servicios, proveedor, instalador, documentos, observaciones, historial, alertas — toda modificación queda registrada.

## Instaladores y proveedores

Instaladores: gestión de aliados, asignaciones, productividad, pedidos, indicadores, campañas, comisiones, documentación, cobertura. Proveedores: catálogo, disponibilidad, pedidos, entregas, estados, cumplimientos, indicadores, incidencias.

**Nota de estado:** ninguna de las dos existe como entidad propia en el código hoy — "proveedor" solo aparece como un campo de texto dentro de la venta (`proveedor_venta`, ligado al catálogo de precios), no como un módulo de gestión.

## Marketing

Soporta campañas desde Meta, SMS, WhatsApp, landing pages, call center — cada lead conserva su origen.

**Nota de estado:** hoy existen campañas por texto de saludo (wa.link) y por referral de Meta Ads — SMS y landing pages como origen de campaña no están implementados.

## CRM

Toda interacción comercial se registra automáticamente: llamadas, WhatsApp, SMS, correos, notas, visitas, seguimientos — nunca información dispersa.

**Nota de estado:** hoy solo WhatsApp se registra automáticamente (mensajes de Gabi y del asesor); llamadas, SMS, correos, notas y visitas no tienen registro en el sistema.

## Dashboard

Indicadores relevantes por perfil: ventas, conversión, campañas, productividad, pedidos, instaladores, proveedores, embudo, forecast, objetivos — todo configurable.

## IA Comercial

Apoya análisis de conversaciones, resúmenes, clasificación de leads, priorización, recomendaciones, generación de mensajes, asistencia al asesor, predicciones — nunca reemplaza al usuario, siempre potencia su trabajo.

## Automatizaciones e integraciones

Automatizables y configurables: recordatorios, seguimientos, asignaciones, estados, notificaciones, mensajes, alertas, procesos. Integraciones previstas (vía servicios desacoplados): ERP, SAP, Power BI, WhatsApp, Meta, correo, SMS, APIs.

## Parametrización

Toda regla específica de Cálidda se configura por parámetros, nunca se codifica directo: productos, estados, canales, campañas, usuarios, permisos, catálogo, indicadores, financiamiento, proveedores, instaladores, mensajes.

## Conocimiento del negocio — límites

El conocimiento acumulado del proyecto sirve para entender el contexto comercial de Cálidda, pero nunca debe asumirse que esas reglas aplican a otros clientes — todo conocimiento específico de Cálidda vive únicamente en este documento.

## Rol de Claude en esta implementación

Consultor Funcional, Business Analyst, Arquitecto de Soluciones, Product Manager, UX Lead, Especialista Comercial — la responsabilidad es adaptar Gaso+ al negocio de Cálidda respetando siempre la arquitectura de ConvertIA.

## Regla principal

Nunca modificar el producto para resolver una necesidad exclusiva de Cálidda sin antes evaluar si esa capacidad puede incorporarse al núcleo de Gaso+ o a ConvertIA Platform — el objetivo es implementar un producto, no desarrollar software exclusivo para un solo cliente.
