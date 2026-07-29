# Maiek AI — Current State Assessment: Frontend Architecture

**Versión 1.0 · Estado: Approved**

| | |
|---|---|
| Documento | Current State Assessment – Frontend Architecture |
| Proyecto | Maiek AI |
| Versión | 1.0 |
| Estado | **Approved** |
| Fecha de creación | 2026-07-28 |
| Autor | Claude, a pedido de Jesús Millones |
| Fecha de aprobación | 2026-07-28 |
| Última actualización | 2026-07-28 |

## Dependencias

- `MAIEK_AI_SYSTEM_ARCHITECTURE.md` (MSA) Capítulo 4-5 — cómo se implementan MDL/CDS/MPX en código real.
- `MAIEK_AI_DESIGN_SYSTEM.md` (MDL v1.1) y `MAIEK_AI_COMPONENT_SYSTEM.md` (CDS v1.0) — ambos Approved, ya reconocidos en `CLAUDE.md` como "guardados solo como referencia, todavía NO aplicados al panel de Gaso+" — este CSA verifica exactamente cuánto de eso es cierto en el código real.
- `MAIEK_AI_PRODUCT_EXPERIENCE.md` (MPX) — Explainability First, protocolo de interacción con IA, manejo de errores y feedback como principios de experiencia ya decididos.
- `MAIEK_AI_SECURITY_ARCHITECTURE.md` — modelo de autenticación/autorización — este CSA audita solo su **representación visual**, no redefine el mecanismo.
- `MAIEK_AI_AI_ARCHITECTURE.md` — protocolo de confianza, Explainability First implementado — este CSA confirma que la UI no tiene representación para esto, sin redefinir cuándo o cómo debería implementarse en el backend.
- `MAIEK_AI_OPERATIONS_ARCHITECTURE.md` — marco de gestión de incidentes — este CSA confirma que la UI no tiene representación operativa, sin redefinir ese marco.
- `MAIEK_AI_DATA_ARCHITECTURE.md` — `negocio_id` (Multi-Tenant Fase 3) — contexto para la sección de escalabilidad de interfaz.
- `MAIEK_AI_ARCHITECTURE_DOCUMENT_STANDARD.md` (ADS) v1.3.

## Consumido por

`MAIEK_AI_FRONTEND_ARCHITECTURE.md` (Frontend Architecture, todavía no construida) — con este par de documentos se cierra el corpus arquitectónico principal de Maiek AI.

## Control de versiones

| Versión | Fecha | Autor | Descripción |
|---|---|---|---|
| 1.0 (borrador) | 2026-07-28 | Claude | Primera versión — auditoría objetiva del estado real de la experiencia de usuario e interfaz existente (`agent/dashboard.py`, `agent/main.py`), sobre las 12 dimensiones pedidas por el usuario, entendidas como arquitectura de experiencia, no como detalle de implementación (sin referencias a frameworks, librerías o convenciones de código). Explícitamente NO cubre backend, API, seguridad, despliegue ni operación. Sin propuestas de solución. Pendiente de revisión y aprobación. |
| 1.0 | 2026-07-28 | Claude | Aprobado sin reapertura del contenido. El usuario registró 2 mejoras futuras no bloqueantes, a incorporar en una versión posterior: (1) **Accesibilidad de la interfaz** — navegación por teclado, contraste, foco y principios generales, aunque el resultado sea confirmar que hoy no existe una estrategia definida; (2) **Consistencia de interacción** — auditar si formularios, acciones, modales, filtros y patrones de interacción siguen principios comunes o evolucionaron de forma independiente entre sí. |

## Alcance

Auditoría objetiva del estado real de la **experiencia de usuario y la interfaz** de la plataforma — organización de la interfaz, navegación, experiencia por rol, flujo entre módulos, consumo de datos y representación de estados, manejo visual de errores, representación de permisos/autenticación, representación de IA y de estado operativo, consistencia visual, escalabilidad Multi-Tenant y principios de extensión — con evidencia citada por archivo y línea. Excluye deliberadamente lógica de negocio, contratos de API, mecanismos de seguridad, infraestructura y procesos operativos (los seis dominios ya cerrados) — se citan como contexto, nunca se re-analizan.

---

## 1. Organización general de la interfaz

Toda pantalla se renderiza a través de una única envoltura (`agent/dashboard.py:867-1073`) que define las regiones estructurales fijas: barra de carga, barra superior, botón flotante de filtros en mobile, y un único punto de montaje del contenido principal (`#contenido-app`) donde la navegación intercambia lo que se muestra. Esta envoltura tiene una variante estructural explícita para el chat: en mobile, oculta el rail y la lista de conversaciones y muestra la conversación a pantalla completa, en vez del layout de 3 columnas normal — un layout adaptativo declarado a propósito, no un efecto secundario.

El shell de 3 columnas (rail de estados / lista de conversaciones / chat o detalle) no vive en una sola función — se compone por ruta antes de pasarse a la envoltura común, lo que significa que cada pantalla decide su propia composición dentro del mismo marco.

## 2. Navegación y arquitectura de información

La barra superior expone enlaces de "gestión" condicionados por rol (detalle en sección 3). El rail izquierdo ya pasó por al menos dos simplificaciones reales, documentadas en el propio código: lo que antes eran dos secciones desconectadas ("con Gabi" y "Conversaciones", con vocabularios sin relación visual entre sí) hoy es una lista única de 7 etapas; y una barra de resumen fusiona datos que antes estaban duplicados entre el embudo y el rail. El bloque de "Canales" se reordenó explícitamente para aparecer antes que "Conversaciones", y un acceso directo a "Agendados" se colocó por encima de todo lo demás, como prioridad de uso.

Esto es evidencia de una arquitectura de información que ya se refinó con uso real, no una estructura fija desde el diseño original.

## 3. Experiencia del usuario según rol

Las diferencias de experiencia por rol van más allá de ocultar botones — hay decisiones reales de UX detrás:

- El badge de disponibilidad (🟢/⚪) solo existe para el rol `asesor`; los enlaces de "Métricas" y "Gestionar asesores" solo para roles con visión total; "Campañas", "Catálogos" y "Canales de WhatsApp" solo para `admin`.
- El rail de estados **oculta** las 3 etapas "con Gabi" para un asesor (siempre estarían en cero, porque solo ve sus propios leads asignados) en vez de mostrarlas vacías — decisión deliberada, documentada como tal en el propio código, no un descuido.
- La sección "Equipo" del rail (carga de trabajo del equipo) solo se construye para roles con visión total — un asesor nunca ve el roster de su equipo.
- Existe un **estado vacío específico por rol**: un asesor sin leads asignados ve una explicación dedicada, en vez de una bandeja vacía que "parece un error" (razón explícita en el propio código) — y ese mensaje cambia según si el asesor está disponible o no.

Brecha real identificada: para varias rutas exclusivas de administrador (editar campaña, activar/desactivar un canal, resetear la contraseña de un asesor), el enlace del menú se oculta según el rol, pero la ruta en sí no tiene una pantalla propia de "no tienes permiso" — cae al error genérico del servidor (sección 6).

## 4. Flujo entre módulos

La navegación entre pantallas (Métricas, Asesores, Campañas, Canales, lista de leads, chat) ocurre mayormente por intercambio de fragmento, no por recarga completa: un clic en un enlace marcado intercepta la navegación, pide solo el contenido nuevo, reemplaza el área principal, actualiza el título de la página y el historial del navegador — con una salvedad explícita: si esa petición falla, cae a una navegación de página completa como respaldo.

El propio código documenta una exclusión deliberada: el login/logout y la descarga de reportes en CSV quedan **fuera a propósito** de este sistema de navegación por fragmento. Fuera de esa excepción documentada, no existe una regla escrita de cuándo un enlace nuevo debe sumarse a este patrón o no — la práctica real ya es "por defecto sí", pero como convención, no como principio documentado.

## 5. Consumo de APIs y representación de estados

Existe un único indicador universal de "algo está cargando": una barra de progreso fija en la parte superior de la página, que se activa tanto en la navegación por fragmento como en cualquier clic o envío de formulario que no usa ese sistema, y también al recuperar la página desde el caché de retroceso del navegador. El propio código explica por qué existe: sin ningún framework de interfaz de por medio, cada clic necesitaba alguna confirmación visual inmediata de que se había registrado.

El indicador de "escribiendo…" en el chat en vivo (vía conexión en tiempo real) es el otro mecanismo real de representación de estado — aparece bajo la conversación y se autooculta tras un tiempo.

No existe ningún estado de carga tipo *skeleton* en ningún punto del panel — el único marcador de espera mientras el chat carga es un texto plano ("Cargando…"). No existe tampoco ningún patrón visible de reintento automático si una carga de datos falla.

## 6. Gestión visual de errores y estados de carga

Existen **tres patrones distintos** de mostrar un error al usuario, sin que haya una razón funcional para que difieran: una caja de alerta reutilizada en varias pantallas (login, perfil), un texto oculto que se revela mediante interacción del usuario (formulario de registro de venta), y una tercera variante de texto plano de estado para fallos de subida de archivo/audio/catálogo. Los tres cumplen el mismo propósito con implementaciones distintas.

Los errores de servidor en rutas de subida o validación (ej. archivo demasiado grande, formato no soportado) llegan como la respuesta cruda por defecto del servidor — **no existe ninguna pantalla de error con la identidad visual del panel** para los casos 403/404/500; el usuario ve una respuesta técnica genérica si el fallo ocurre en una navegación de página completa.

Los estados vacíos ("Aún no hay leads", "Aún no hay canales configurados", "No hay conversaciones en este estado") son mensajes ad-hoc por pantalla, con el mismo propósito, sin un componente reutilizable — con la única excepción ya construida deliberadamente para el asesor sin leads (sección 3).

## 7. Representación de permisos y autenticación

Se audita solo la representación visual — el mecanismo de autenticación en sí ya está resuelto en Security Architecture y no se redefine acá. La pantalla de login usa una tarjeta centrada, el mismo patrón de estructura que reutiliza la pantalla de recuperación de contraseña. Esa recuperación muestra el mismo mensaje de confirmación exista o no la cuenta — decisión ya conocida de Security Architecture, coherente con lo que se ve en pantalla.

La redirección cuando no hay sesión válida es **silenciosa**: el usuario simplemente aparece en el login, sin ningún mensaje que explique por qué (por ejemplo, si su sesión expiró a mitad de una tarea). El único indicador persistente de "quién soy, qué rol tengo" es el nombre y el rol como texto plano en la barra superior y en la pantalla de perfil — no hay ningún otro indicador visual de sesión o permisos en el resto del panel, y no existe ninguna advertencia visual antes de que una sesión expire.

## 8. Representación de explicaciones, confianza y sugerencias del AI Engine

Los mensajes de Gabi se renderizan con la **misma burbuja de chat** que los mensajes del cliente y del asesor humano — solo cambia la etiqueta ("Gabi") y la inicial del avatar; misma clase visual, mismo tratamiento, sin ninguna distinción.

No existe ningún indicador de confianza, insignia de "sugerencia", ni ningún elemento que permita explorar el porqué de una respuesta — en ningún punto del panel. Esto es coherente con lo ya establecido en AI Architecture: el protocolo de confianza y `SugerenciaIA` son decisiones objetivo, no implementadas todavía. Este CSA confirma, además, que **no existe siquiera un elemento de interfaz reservado o deshabilitado** a la espera de ese dato — la ausencia es total, no parcialmente preparada. Las únicas menciones de "Gabi"/"Maiek AI" en el panel son cosméticas (texto de marca en la barra superior y en el login), no funcionales.

## 9. Representación de incidentes, mantenimiento y estado operativo

No existe ningún banner, indicador o pantalla de salud del sistema, incidente o modo de mantenimiento visible en el panel — coherente con lo ya establecido en el CSA-Operations (sin concepto de incidente implementado en ningún punto del backend). El único elemento "de sistema" real en toda la interfaz es un aviso de permiso de notificaciones del navegador, sin relación con la salud del backend. El endpoint de salud del servidor es una respuesta técnica plana que nunca se muestra dentro del panel.

## 10. Consistencia visual entre todos los módulos

Existe una base real de variables de color reutilizables, definidas una sola vez y usadas en decenas de puntos del panel — no es un caos total de estilos sueltos. Pero esa base convive con un uso extenso (86 ocurrencias confirmadas) de ajustes de estilo puntuales directamente en el marcado, para casos que ya tienen una variable equivalente disponible — dos patrones mezclados, sin una regla clara de cuándo usar cada uno.

**Hallazgo central de esta sección**: esta paleta es propia y separada — el panel real **no aplica los tokens de color de `MAIEK_AI_DESIGN_SYSTEM.md`** (MDL v1.1, ya Approved), que define un sistema de color distinto. La única coincidencia real entre ambos sistemas es tipográfica: el panel ya usa la fuente Inter, que es exactamente la decisión que MDL tomó para producto — es la única superposición confirmada entre el sistema de diseño aprobado y lo que existe hoy; el resto (color, componentes, espaciado) es independiente.

Todo el estilo del panel vive centralizado en un único bloque, inyectado una vez en la envoltura común — coherente con la organización general (sección 1), pero significa que cualquier cambio visual pasa por ese mismo punto único, sin ningún aislamiento por pantalla.

## 11. Escalabilidad de la interfaz para operación SaaS Multi-Tenant

No existe ninguna referencia a `negocio_id` ni a ningún concepto de tenant en toda la capa de interfaz — coherente con el mismo hallazgo ya confirmado en los siete documentos anteriores. La identidad visual está **hardcodeada a un solo negocio**: el nombre "Gaso+" aparece como texto literal en la envoltura común (barra superior, login, título de página), no como un valor configurable por tenant. Incluso el nombre de las variables de color reutilizables incorpora el nombre del negocio directamente — un acoplamiento adicional que ni siquiera separa "identidad de marca" de "negocio actual" a nivel de nomenclatura.

## 12. Principios para incorporación de nuevos módulos

No existe ningún principio documentado de cómo debe agregarse una pantalla nueva sin romper la experiencia existente. La única estructura real es una secuencia de comentarios de sección dentro del mismo archivo, marcando los límites de cada pantalla — aplicada de forma inconsistente (algunas pantallas tienen ese comentario, otras se identifican únicamente por el nombre de su función). La convención de nombrar las funciones según la pantalla que representan es lo más cercano a una regla de organización que existe hoy — es una convención implícita, nunca escrita como principio.

---

## Fortalezas

- El sistema de navegación por fragmento ya es funcional y está bien pensado — con una salvedad de respaldo documentada (recarga completa si falla) y exclusiones deliberadas y explicadas (login/logout, exportaciones), no es un parche improvisado.
- Ya existe una base real de tokens de color reutilizables — no es un punto de partida desde cero para cualquier trabajo futuro de consistencia visual.
- La arquitectura de información ya pasó por iteraciones reales de simplificación basadas en uso (fusión de secciones redundantes, reordenamiento por prioridad) — documentado en el propio código, señal de mejora continua real, no solo aspiracional.
- Las diferencias de experiencia por rol están genuinamente bien pensadas — el estado vacío específico para un asesor sin leads, y el ocultamiento inteligente de secciones que siempre estarían en cero, muestran consideración real de a quién se le muestra qué.
- El indicador de "escribiendo…" y la barra de progreso dan retroalimentación en tiempo real exactamente donde más importa: el chat en vivo y la navegación.

## Decisiones heredadas del MVP (razonables para la etapa, a reevaluar)

- Un único archivo sin separación por pantalla/módulo — proporcional a un equipo de desarrollo pequeño y un panel que creció orgánicamente desde una necesidad real, no desde un diseño previo.
- Paleta de color propia en vez de aplicar MDL/CDS desde el inicio — ambos se aprobaron **después** de que el panel ya existiera y funcionara; migrar tiene un costo real, no es negligencia.
- Sin páginas de error personalizadas — proporcional a un panel interno usado por el propio equipo, no por clientes externos.
- Patrones de manejo de error inconsistentes entre sí — cada uno se agregó cuando se necesitó, sin una revisión retroactiva que los unificara, razonable en una primera etapa de crecimiento.

## Deuda de UX técnica (sin justificación de etapa)

- **Tres patrones distintos para mostrar un error** sin ninguna razón funcional para que difieran entre sí — mismo problema, tres soluciones no coordinadas.
- **Ausencia total de una pantalla de error con la identidad del panel** — el momento de mayor fricción para el usuario (algo ya salió mal) es también el único momento en que la experiencia visual se rompe por completo.
- **Uso inconsistente de ajustes de estilo puntuales frente a las variables reutilizables ya existentes** — no es una decisión, es acumulación sin limpieza posterior.
- **Redirección silenciosa al expirar la sesión**, sin ningún mensaje explicativo — un usuario a mitad de una tarea pierde contexto sin ninguna pista de qué ocurrió.

## Desviaciones respecto al MSA, MDL, CDS, MPX y documentos derivados ya Approved

- **MDL v1.1 y CDS v1.0 (Approved) no están aplicados al panel real** — no es una desviación en el sentido de "se decidió algo distinto", es sincronización pendiente, ya reconocida explícitamente en `CLAUDE.md` del propio proyecto antes de este CSA. Se confirma con evidencia de código, no se trata como hallazgo nuevo.
- **MPX (Explainability First, protocolo de interacción con IA)** — sin representación en la interfaz, consistente con que el mecanismo de backend correspondiente tampoco existe todavía (AI Architecture ya lo declaró como target) — sincronización pendiente, no desviación.
- **Único punto de coincidencia parcial confirmado**: la tipografía Inter, alineada con MDL.
- No se identificó ninguna decisión ya tomada en un documento Approved que la interfaz actual contradiga activamente — todo lo que falta es ausencia de implementación, no contradicción.

## Riesgos detectados

1. **Alto** — sin pantalla de error con identidad del panel: cualquier fallo de backend ya identificado en CSAs previos (ej. el fail-open del webhook, la ausencia de backups) que llegue a manifestarse visible al usuario del panel se vería como una respuesta técnica cruda, rompiendo la confianza justo cuando más se necesita.
2. **Medio** — redirección silenciosa al expirar sesión: pérdida de contexto o trabajo en curso sin ninguna explicación.
3. **Medio** — tres patrones de error distintos sin razón funcional: dificulta mantener y extender el panel de forma predecible.
4. **Medio** — MDL/CDS no aplicados: cuanto más crece el panel sin ellos, más costoso será migrar más adelante.
5. **Bajo hoy / bloqueante futuro** — identidad visual hardcodeada a un solo negocio.

## Architectural Readiness

| Dimensión | Madurez actual | Nota |
|---|---|---|
| Organización general de la interfaz | **Sólida** | Envoltura única, bien estructurada, con variante adaptativa deliberada |
| Navegación / arquitectura de información | **Sólida** | Ya iterada y simplificada con uso real |
| Experiencia por rol | **Sólida** | Diferenciación real, no solo ocultamiento de botones |
| Flujo entre módulos | **Sólido** | Navegación por fragmento funcional, con respaldo documentado |
| Consumo de datos / representación de estados | **Básico** | Feedback universal sí; sin skeleton, sin reintento visible |
| Gestión visual de errores | **Débil** | 3 patrones sin unificar; sin pantalla de error propia |
| Representación de permisos/autenticación | **Parcial** | Indicador de sesión sí; expiración silenciosa |
| Representación de IA (confianza/explicación) | **Ausente** | Coherente con el backend; sin ni siquiera un placeholder |
| Representación operativa (incidentes/mantenimiento) | **Ausente** | Coherente con el backend |
| Consistencia visual | **Parcial** | Tokens reales, pero MDL/CDS sin aplicar + estilos inline mezclados |
| Escalabilidad Multi-Tenant | **Ausente** | Identidad hardcodeada a un solo negocio |
| Principios de extensión de módulos | **Ausente** | Convención informal, nunca documentada |

**Conclusión de preparación:**

- **MVP (uso actual, un solo negocio):** **Listo**, y en varios puntos por encima de lo esperado — la navegación, la arquitectura de información y la experiencia por rol ya reflejan decisiones de UX genuinas, no solo lo mínimo funcional.
- **Crecimiento (más volumen, mismo negocio):** **Parcialmente listo.** La deuda de manejo de errores y la ausencia de principios de extensión de módulos se sienten en cuanto el panel o el equipo de desarrollo crezcan — hoy funcionan porque el conocimiento vive en las personas, igual que ya se identificó en el dominio de Operations.
- **SaaS multiempresa:** **No listo.** La identidad visual y la estructura están completamente acopladas a un solo negocio — mismo bloqueante transversal confirmado en los siete documentos anteriores, ahora también desde el ángulo de experiencia de usuario.

## Priorización de remediación

| Prioridad | Ítem | Por qué |
|---|---|---|
| **P1** | Pantalla de error con identidad del panel para fallos 403/404/500 | Rompe la experiencia justo en el momento de mayor fricción para el usuario |
| **P1** | Unificar los tres patrones de error en uno solo | Inconsistencia sin justificación funcional |
| **P2** | Mensaje explicativo al expirar la sesión, en vez de redirección silenciosa | Pérdida de contexto evitable |
| **P2** | Aplicar los tokens de MDL al panel real, empezando por lo ya parcialmente alineado (tipografía) | Migración incremental, no de una sola vez |
| **P3** | Documentar el principio de organización/extensión de módulos, aunque sea informalmente | Bajo costo, cierra una brecha real de mantenibilidad |
| **P3** | Reducir el uso de estilos puntuales a favor de las variables ya existentes | Bajo riesgo actual, mejora de higiene visual |

## Architectural Decision Impact

| Hallazgo | Arquitecturas afectadas | Por qué |
|---|---|---|
| Sin pantalla de error propia | Frontend, Security, DevOps, Operations | Cualquier hallazgo ya identificado en esos CSAs que se manifieste como error hoy rompe la experiencia visual |
| MDL/CDS no aplicados | Frontend, Design | Deuda de implementación pura sobre un sistema de diseño ya Approved |
| Sin representación de IA (confianza/explicación) | Frontend, AI | Frontend deberá diseñar cómo se muestra una vez AI Architecture implemente el protocolo de confianza — no antes |
| Sin representación operativa | Frontend, Operations | Operations Architecture ya definió el marco de incidentes; Frontend deberá decidir cómo se hace visible, no antes |
| Identidad hardcodeada a un negocio | Frontend, Data | Mismo bloqueante transversal ya señalado en los siete documentos anteriores |

## Strategic Recommendations

1. **La unificación del manejo de errores es la decisión de mayor apalancamiento de este documento** — es lo único que hoy rompe visualmente la experiencia, justo en el momento de mayor fricción para el usuario.
2. **La aplicación de MDL/CDS al panel real puede ser incremental**, empezando por lo que ya coincide parcialmente (tipografía) — no exige un rediseño completo de una sola vez.
3. **La representación de IA y de estado operativo no deberían diseñarse todavía** — Frontend Architecture debe dejar establecido el principio de cómo se representarán, no construir la interfaz antes de que exista el dato real que la alimente (AI Architecture y Operations Architecture ya definieron esos mecanismos como objetivo, no implementados).
4. **La identidad hardcodeada a un negocio es, otra vez, el mismo bloqueante transversal** — este es el octavo documento consecutivo en señalarlo; ya no es una curiosidad aislada, es el hallazgo que más veces aparece en todo el corpus.
5. **Documentar el principio de extensión de módulos no exige reestructurar el archivo único hoy** — alcanza con declarar como regla explícita la convención ya usada informalmente (nombre de función = nombre de pantalla).

---

*Fin del documento. Approved el 2026-07-28. Siguiente paso: construir `MAIEK_AI_FRONTEND_ARCHITECTURE.md` (arquitectura objetivo) como evolución explícita desde este estado real, siguiendo el ADS, el MSA, MDL, CDS, MPX, y el contexto ya establecido por Data, Backend, API, AI, Security, DevOps y Operations Architecture — cerrando el corpus arquitectónico principal de Maiek AI.*
