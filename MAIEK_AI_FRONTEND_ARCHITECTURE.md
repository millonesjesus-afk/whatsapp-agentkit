# Maiek AI — Frontend Architecture

**Versión 1.0 · Estado: Approved**

| | |
|---|---|
| Documento | Frontend Architecture |
| Proyecto | Maiek AI |
| Versión | 1.0 |
| Estado | **Approved** |
| Fecha de creación | 2026-07-28 |
| Autor | Claude, a pedido de Jesús Millones |
| Fecha de aprobación | 2026-07-28 |
| Última actualización | 2026-07-28 |

## Dependencias

- `MAIEK_AI_SYSTEM_ARCHITECTURE.md` (MSA) Capítulo 4-5.
- `MAIEK_AI_FRONTEND_CURRENT_STATE_ASSESSMENT.md` (CSA-Frontend) — diagnóstico del que este documento parte directamente.
- `MAIEK_AI_DESIGN_SYSTEM.md` (MDL v1.1), `MAIEK_AI_COMPONENT_SYSTEM.md` (CDS v1.0), `MAIEK_AI_PRODUCT_EXPERIENCE.md` (MPX) — sistema de diseño y principios de experiencia ya Approved — **este documento no los redefine, resuelve su aplicación real al panel**.
- `MAIEK_AI_SECURITY_ARCHITECTURE.md` — modelo de autenticación/autorización — **se representa visualmente, no se redefine**.
- `MAIEK_AI_AI_ARCHITECTURE.md` — protocolo de confianza, Explainability First — **se cita como dependencia futura de contenido, no se construye la UI antes de que el dato exista**.
- `MAIEK_AI_OPERATIONS_ARCHITECTURE.md` — marco de gestión de incidentes — **mismo criterio: se cita, no se anticipa la UI**.
- `MAIEK_AI_DATA_ARCHITECTURE.md` — `negocio_id` (Multi-Tenant Fase 3).
- `MAIEK_AI_ARCHITECTURE_DOCUMENT_STANDARD.md` (ADS) v1.3.

## Consumido por

Ninguno todavía — es el octavo y último documento técnico derivado del MSA. Cierra el corpus arquitectónico principal de Maiek AI.

## Control de versiones

| Versión | Fecha | Autor | Descripción |
|---|---|---|---|
| 1.0 (borrador) | 2026-07-28 | Claude | Primera versión — arquitectura objetivo de Frontend, construida sobre el CSA-Frontend aprobado. Resuelve la unificación del manejo de errores y la pantalla de error propia (P1 del CSA) sin construir todavía la representación de IA ni de estado operativo — ambas quedan como principio dependiente de que AI Architecture y Operations Architecture entreguen el dato real primero. No incorpora accesibilidad ni consistencia de interacción — registradas como mejora futura del CSA, no de este documento. Pendiente de revisión y aprobación. |
| 1.0 | 2026-07-28 | Claude | Aprobado sin reapertura del contenido. Con esta aprobación se cierra el corpus arquitectónico principal de Maiek AI (8 dominios técnicos derivados del MSA). El usuario registró 2 mejoras futuras no bloqueantes, a incorporar en una versión posterior: (1) principio de **descubribilidad** — toda nueva funcionalidad debe ser accesible desde la navegación existente, sin depender de accesos ocultos como mecanismo principal de uso; (2) declarar explícitamente que la **consistencia visual global prevalece sobre preferencias particulares de cada módulo**, reforzando el rol de MDL como fuente única de identidad visual — refuerza la sección 10, que hoy establece la adopción incremental pero no declara esta jerarquía de forma explícita. |

## Alcance y regla de no-duplicación

Define **cómo debe organizarse y comportarse la experiencia de usuario** de la plataforma — sobre el sistema de diseño ya decidido en MDL/CDS/MPX y los mecanismos ya decididos en Security, AI, Operations y Data Architecture. **No redefine** ningún token de color/tipografía de MDL, ningún componente de CDS, ningún principio de MPX, el modelo de autenticación, el protocolo de confianza del AI Engine, ni el marco de incidentes — los consume y resuelve su representación visual. Entendida como arquitectura de experiencia, no de implementación: no prescribe frameworks, librerías ni convenciones de código (ADS §10).

---

## 1. Organización general de la interfaz objetivo

Se preserva el patrón de envoltura única con un punto de montaje central para el contenido — decisión **Activa**, ya validada. Se formaliza como principio explícito: cualquier variante estructural nueva (como la ya existente para el chat en mobile) debe expresarse como una variante de esa misma envoltura, no como una pantalla con su propio marco independiente.

## 2. Navegación y arquitectura de información objetivo

La arquitectura de información actual se preserva como decisión **Activa** — ya fue validada con iteraciones reales de simplificación (CSA, sección 2). Principio nuevo: cualquier módulo nuevo debe **extender** la estructura de navegación ya existente (barra superior + rail + barra de resumen), no crear un sistema de navegación paralelo.

## 3. Experiencia del usuario según rol objetivo

Se formalizan como principios explícitos los dos patrones ya implementados informalmente: **ocultar, no vaciar** — un elemento de interfaz que siempre estaría vacío o irrelevante para un rol se oculta, no se muestra en cero; y **estado vacío específico** — cuando una pantalla podría razonablemente parecer rota para un rol (ej. una bandeja vacía), debe tener una explicación propia, no el vacío genérico.

Se cierra la brecha identificada en el CSA: toda ruta restringida por rol debe tener una representación visual coherente de "no tienes permiso" — no la respuesta genérica del servidor. Esta decisión se resuelve junto con la sección 6 (mismo mecanismo de error unificado).

## 4. Flujo entre módulos objetivo

Se formaliza como principio escrito lo que hoy es una convención implícita: **la navegación entre módulos usa el sistema de intercambio por fragmento por defecto**, con las mismas exclusiones ya documentadas y deliberadas (login/logout, descargas) — decisión **Activa**. Cualquier enlace nuevo entre pantallas sigue este patrón salvo que tenga una razón explícita para no hacerlo (ej. una descarga de archivo).

## 5. Consumo de APIs y representación de estados objetivo

Se preserva el indicador universal de carga (barra de progreso) y el indicador de "escribiendo…" como decisiones **Activas** — ya cumplen su propósito. No se agrega un estado de carga tipo *skeleton* en esta versión — no hay evidencia en el CSA de que el "Cargando…" actual esté generando fricción real (Evidence over Opinion); queda como posible mejora futura, no como decisión de esta versión.

## 6. Gestión visual de errores y estados de carga objetivo

**Se unifican los tres patrones de error identificados en el CSA en un solo mecanismo de mensaje de error, reutilizado consistentemente** en formularios, subida de archivos y validaciones — la decisión de mayor prioridad de este documento (P1 del CSA).

**Se define una pantalla de error con identidad visual del panel** para fallos HTTP (403/404/500) — distingue explícitamente dos categorías: error de permiso (el usuario no puede hacer esto) y error de sistema (algo falló y no es culpa del usuario). Ningún fallo debe mostrar la respuesta técnica cruda del servidor — es el principio que cierra el riesgo de mayor severidad identificado en el CSA.

## 7. Representación de permisos y autenticación objetivo

**Al expirar la sesión, el usuario ve un mensaje que explica por qué fue redirigido al login** — reemplaza la redirección silenciosa actual (P2 del CSA). El resto del comportamiento visual (tarjeta de login, mensaje genérico de recuperación de contraseña) se preserva como decisión **Activa** — ya es coherente con el modelo ya decidido en Security Architecture, que este documento no redefine.

## 8. Representación de explicaciones, confianza y sugerencias del AI Engine objetivo

**No se construye esta representación en esta versión** — es una decisión deliberada, no una omisión: AI Architecture todavía no implementa el protocolo de confianza ni `SugerenciaIA`, y construir la interfaz antes que el dato real existiría sobre una suposición, no sobre evidencia.

Lo que este documento sí fija es el **principio** que deberá seguir esa representación cuando el dato exista: la señal de confianza debe ser visualmente distinguible usando el mismo vocabulario ya fijado en MPX (`Alta`/`Requiere validación`/`Baja`) — no un vocabulario nuevo inventado por Frontend — y debe dar acceso a la razón detrás de la respuesta (Explainability First, MPX Cap. 3), no solo mostrar el nivel de confianza de forma aislada.

## 9. Representación de incidentes, mantenimiento y estado operativo objetivo

Mismo criterio que la sección 8: **no se construye esta representación en esta versión**, porque Operations Architecture define el marco de incidentes pero el mecanismo técnico para producirlos no existe todavía. El principio que queda fijado: cuando ese marco se implemente, el panel debe exponer una señal visible de estado operativo — sin anticipar su forma exacta.

## 10. Consistencia visual entre todos los módulos objetivo

**Se adoptan los tokens de MDL de forma incremental, no de una sola vez** — empezando por lo que ya coincide parcialmente (la tipografía Inter, ya en uso) y extendiéndose gradualmente a color y espaciado. El mecanismo técnico de esa migración no es una decisión de este documento (implementación); el principio sí lo es: **ningún token nuevo se define fuera de MDL** — si un color o espaciado no existe en MDL, se solicita su incorporación ahí, no se inventa una variable local nueva como ya ocurrió con la paleta actual.

Se reduce, de forma progresiva, el uso de ajustes de estilo puntuales a favor de las variables y clases ya existentes — P3 del CSA, sin fecha límite fija.

## 11. Escalabilidad de la interfaz para operación SaaS Multi-Tenant

Se hereda, sin diseñar el mecanismo, el mismo principio ya declarado en los siete documentos anteriores: cuando `negocio_id` exista (Data Architecture Fase 3), la identidad de marca (nombre, colores) debe poder resolverse por negocio, no quedar fija en el código como ocurre hoy. Este documento no resuelve el mecanismo técnico — solo dejaría, en una futura revisión, de nombrar variables de color con el nombre del negocio actual, para no seguir acoplando ambas cosas innecesariamente.

## 12. Principios para incorporación de nuevos módulos objetivo

**Se documenta como regla explícita la convención ya usada informalmente**: el nombre de la función que renderiza una pantalla coincide con el nombre de esa pantalla, y cada pantalla nueva se marca con un comentario de sección — sin excepciones, a diferencia de la aplicación inconsistente de hoy (CSA, sección 12). No se reestructura el archivo único en esta versión — es una decisión de implementación proporcional al tamaño actual del equipo, no una decisión de esta arquitectura.

---

## Architectural Constraints

| Restricción | Naturaleza | Impacto en el diseño |
|---|---|---|
| MDL ya define sus tokens de color y tipografía como variables CSS reutilizables | Hecho ya establecido en un documento Approved anterior, no una elección de este documento | Determina el mecanismo que la migración de la sección 10 debe usar — no se inventa un mecanismo de tokens distinto |
| El panel se consume desde escritorio y mobile con una única fuente de interfaz, sin apps nativas separadas | Hecho del alcance actual del proyecto | Cualquier decisión de este documento debe funcionar en ambos contextos sin bifurcar la experiencia |
| Ningún proveedor de IA expone hoy la señal de confianza (AI Architecture ya lo declaró como target, no implementado) | Constraint de secuencia entre documentos, no una elección de este documento | Impide construir la representación de la sección 8 antes de que ese dato exista — de ahí que quede como principio, no como decisión implementada |

## Decisiones locales

| Decisión | Estado | Justificación | Criterio de revisión |
|---|---|---|---|
| Navegación por fragmento por defecto, con las exclusiones ya documentadas | **Activa** | Ya validado, funcional | — |
| Ocultar (no vaciar) elementos irrelevantes por rol; estado vacío específico donde aplique | **Activa** | Formaliza un patrón ya implementado y bien pensado | — |
| Unificar los 3 patrones de error en un solo mecanismo reutilizable | Objetivo | P1 del CSA | — |
| Pantalla de error con identidad del panel para 403/404/500, distinguiendo permiso de sistema | Objetivo | P1 del CSA — cierra el riesgo de mayor severidad | — |
| Mensaje explicativo al expirar sesión | Objetivo | P2 del CSA | — |
| Adopción incremental de tokens de MDL, empezando por tipografía | Objetivo | P2 del CSA; evita una migración de una sola vez | — |
| Ningún token visual nuevo se define fuera de MDL | Objetivo | Evita repetir el acoplamiento actual a una paleta propia | Si MDL no cubre una necesidad real y se justifica una extensión |
| Reducir estilos puntuales a favor de variables/clases existentes | Objetivo | P3 del CSA | — |
| Documentar la convención de nombres/organización de pantallas como regla explícita | Objetivo | P3 del CSA | — |
| Principio de representación de confianza/explicación (vocabulario de MPX, Explainability First) | Objetivo, dependiente de AI Architecture | Evita construir la UI antes de que el dato exista | Cuando AI Architecture implemente el protocolo de confianza |
| Principio de señal visible de estado operativo | Objetivo, dependiente de Operations Architecture | Mismo criterio que la decisión anterior | Cuando el marco de incidentes se implemente |
| Identidad de marca resoluble por negocio, no hardcodeada | Objetivo, dependiente de Data Architecture Fase 3 | Cierra el bloqueante transversal ya señalado en los 7 documentos anteriores | Cuando exista un segundo negocio real |

## Brechas conocidas

- **Accesibilidad de la interfaz** (navegación por teclado, contraste, foco) → registrada como mejora futura del CSA-Frontend, no incorporada en esta versión.
- **Consistencia de interacción** (formularios, modales, filtros) → registrada como mejora futura del CSA-Frontend, no incorporada en esta versión.
- **Mecanismo técnico exacto de la migración a tokens de MDL** → decisión de implementación, no arquitectónica en este nivel.
- **Contenido visual exacto de la representación de IA y de estado operativo** → depende de que AI Architecture y Operations Architecture entreguen el dato real primero.

## Architecture Success Criteria

1. Todo error 403/404/500 se muestra dentro de una pantalla que conserva la identidad visual del panel, distinguiendo error de permiso de error de sistema. Verificable provocando cada tipo de error y confirmando que no aparece una respuesta técnica cruda.
2. Existe un único mecanismo reutilizable de mensaje de error, usado consistentemente en formularios, subida de archivos y validaciones. Verificable revisando que las distintas pantallas usan el mismo patrón.
3. Al expirar la sesión, el usuario ve un mensaje que explica por qué fue redirigido al login. Verificable dejando expirar una sesión y observando la redirección.
4. Al menos un token de MDL más allá de la tipografía está aplicado de forma verificable en el panel real. Verificable inspeccionando el CSS del panel contra el documento MDL.
5. Existe un documento que describe la convención de nombres/organización para agregar una pantalla nueva. Verificable revisando ese documento.

## QA arquitectónico

Este documento fue verificado contra el checklist de 11 preguntas del ADS §11 antes de presentarse — en particular, se confirmó que las secciones 8 y 9 declaran explícitamente principios dependientes, no decisiones implementadas prematuramente sin el dato real que las sustente, y que las 5 Architecture Success Criteria son verificables sin depender de una herramienta o framework específico.

## Cierre

Este documento cierra el diseño objetivo del dominio de Frontend, construido sobre el CSA-Frontend ya aprobado y sin redefinir ninguna decisión ya tomada en MDL, CDS, MPX, Security, AI, Operations o Data Architecture — solo resuelve cómo se organiza y comporta la experiencia de usuario sobre esas decisiones. **Con su aprobación, se cierra el corpus arquitectónico principal de Maiek AI**: ocho dominios técnicos derivados del MSA (Data, Backend, API, AI, Security, DevOps, Operations, Frontend), cada uno con su Current State Assessment y su arquitectura objetivo. **Approved** el 2026-07-28.

---

*Fin del documento.*
