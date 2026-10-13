# ADR-0005: Shell de sidebar de alto completo (Z), Tira de acción en Inicio (A) y Pulso de hoy (C) por fases

| | |
|---|---|
| Estado | Aceptada (Approved) |
| Fecha | 2026-10-12 |
| Origen | Decisión del dueño (Jesús Millones, 2026-10-12), tomada sobre la maqueta comparativa de Shell (actual / X / Y / Z) e Indicadores (actual / A / B / C) |
| Documento de arquitectura afectado | `MAIEK_AI_PRODUCT_PATTERNS.md` — Cap. 1 §3 (Composición), §5, §6, §7 y §9 (Shell de Navegación) y Cap. 3 (Inicio: Zona de indicadores → Tira de acción; Pulso de hoy) y Cap. 9 (Acción antes que observación); `MAIEK_AI_COMPONENT_SYSTEM.md` — Sidebar, Top Navigation y KPI Card |
| Fase del roadmap | Fase de Implementación — evolución de producto del frontend (`maiek-frontend`); no corresponde a una fase numerada de `MAIEK_AI_IMPLEMENTATION_ROADMAP.md` |

## Contexto

### Estado actual (verificado en `maiek-frontend`, solo lectura, 2026-10-12)

- **Shell.** `app/(shell)/layout.tsx` monta una columna: «Saltar al contenido», luego `TopNav` por encima de todo y, debajo, `Sidebar` + `ContentArea`. Es la composición literal de `MAIEK_AI_PRODUCT_PATTERNS.md` Cap. 1 §3 («Top Navigation por encima de todo»).
- **Top Navigation** (`components/shell/top-nav.tsx`): `<header>` sticky de 64 px (`h-16`) con hamburguesa (solo bajo `sm`), wordmark, buscador (campo de 256 px desde `sm`, ícono en móvil), campana (`CampanaNotificaciones`), ayuda (popover) y avatar (`MenuUsuario`). Es decir, cuatro elementos a la derecha, tal como fija el CDS.
- **Sidebar** (`components/shell/sidebar.tsx`): `<aside>` Navy (`bg-navy-900`) de 280 px expandido / 64 px colapsado, **sin marca** (el wordmark solo aparece en el overlay móvil). Entre 768 px y 1023,98 px el colapso es forzado (`enZonaEstrecha` en `proveedor-shell.tsx`); por debajo de 768 px es un `Sheet` a pantalla completa.
- **Wordmark** (`components/shell/wordmark.tsx`): isotipo real (`public/logo-mark.png`) dentro de un tile blanco de 28 px, más el texto «Maiek AI» en Poppins. El comentario del componente registra el pedido explícito del dueño del 2026-09-15: «el logo de maiek siempre debe ir en fondo blanco».
- **Breakpoints** (`tailwind.config.ts`, MDL Cap. 3): `xs` 480, **`sm` 768**, **`md` 1024**, `lg` 1280, `xl` 1536 (la escala por defecto de Tailwind está reemplazada).
- **Inicio** (`components/inicio/inicio-nuevo.tsx`, `mi-cola.tsx`, `zona-indicadores.tsx`): «Tu siguiente mejor acción» y «Mi cola» en la columna principal; en el rail derecho (desde `lg`) «Mi día» y el cuadro **«Indicadores»** (3 cifras sin acción asociada, tomadas de `zona_indicadores`); sobre la cola, **chips** Todo / Responder / Llamar / Citas con sus conteos. Las mismas cantidades se muestran, por lo tanto, en dos lugares con presentación distinta y ninguna de las cifras de «Indicadores» es clicable. *(Nota 2026-10-13: «Mi día» se retiró del rail; ver «Enmienda 2026-10-13».)*

### Qué no cuadra

1. La barra superior consume 64 px de alto en todas las pantallas del producto para alojar cuatro accesos transversales y una marca, mientras el contenido (Conversaciones, Pipeline, Inicio) compite por alto vertical. El Sidebar, en cambio, carece de marca y de cuenta: la identidad y las funciones transversales quedan separadas de la navegación.
2. En Inicio, el cuadro «Indicadores» expone cifras sin verbo de acción (`MAIEK_AI_PRODUCT_EXPERIENCE.md` Cap. 3: «un número sin verbo de acción alrededor es información») y duplica los conteos de los chips de la cola, contra el principio **Única fuente de verdad** (`MAIEK_AI_PRODUCT_PATTERNS.md` Cap. 9).
3. La supervisión (Supervisor, Administrador) carece de una lectura de desempeño del día; hoy solo ve cifras de volumen.

## Decisión

El dueño aprobó, el 2026-10-12, tres decisiones de producto relacionadas. Las dos primeras se implementan primero; la tercera queda aprobada y se construye por fases posteriores.

### A. Shell Z — sidebar de alto completo con las funciones transversales adentro

1. **Escritorio y tablet (desde `sm`, 768 px): no hay barra superior.** El Sidebar ocupa todo el alto de la ventana y contiene, de arriba hacia abajo: (a) la **marca** — wordmark «Maiek AI» sobre tile blanco, aplicando el uso del logo ya vigente en el producto (el logo siempre sobre fondo blanco); (b) el **buscador** (`Cmd/Ctrl+K`) y la **campana con contador**; (c) la **navegación principal** (MPA §10, filtrada por rol sin cambios); (d) abajo, la **tarjeta de cuenta** con nombre y rol, que abre el menú de cuenta.
2. **«Ayuda» pasa al menú de cuenta en todos los tamaños** (escritorio y móvil). Deja de ser un icono suelto.
3. **Móvil (por debajo de `sm`, 768 px): se mantiene la barra superior**, ahora de **56 px**, con hamburguesa, marca, búsqueda, campana y avatar; la navegación sigue en el drawer. Sin cambios en el modelo de navegación móvil (no se agrega barra inferior).
4. **Sin selector de negocio** hasta que exista un segundo negocio real (consistente con ADR-0003 y con la entidad Negocio diferida).
5. **Modo colapsado a iconos (64 px):** isotipo, búsqueda, campana, navegación y avatar apilados verticalmente, con tooltip y etiqueta accesible. **A 768 px (y hasta 1023,98 px) el Sidebar se fuerza colapsado**, igual que hoy; la preferencia manual del usuario se conserva y se retoma desde `md` (1024 px).
6. **Accesibilidad de landmarks y foco.** En escritorio **no existe landmark `banner`** (no hay cabecera de página): se documenta su ausencia deliberada; los landmarks son `navigation` («Navegación principal», dentro de un `aside` «Navegación y cuenta») y `main`. En móvil, la barra de 56 px es el `banner`. «Saltar al contenido» sigue siendo el primer elemento enfocable. Orden de tabulación en escritorio: **Saltar al contenido → marca → búsqueda → campana → navegación → cuenta → contenido**.

> Nota de lectura sobre el umbral. El pedido original habló de «escritorio (≥ md)» sin barra superior y, a la vez, de un Sidebar forzado a 64 px **a 768 px** con búsqueda, campana y avatar apilados dentro. Como en este producto `md` = 1024 px y `sm` = 768 px, la única lectura coherente es que la barra superior desaparece desde `sm`; así lo muestra también la maqueta de referencia (la barra solo existe en el ancho móvil). Esta decisión adopta esa lectura.

### B. Tira de acción en Inicio (propuesta A)

1. Una **tira de celdas** al inicio de Inicio **reemplaza tanto al cuadro «Indicadores» del rail derecho como a los chips de «Mi cola»**: queda una sola fuente de verdad para esos conteos.
2. **Asesor — 4 celdas:** *Responder*, *Llamar*, *Citas de hoy* y *Mis casos activos* (esta última es un **enlace tranquilo** a Conversaciones —borde punteado, sin relleno—, no un KPI ni un filtro).
3. **Supervisión (Supervisor y Administrador) — 5 celdas:** *Responder*, *Llamar*, *Citas*, *Reasignar* (escalados + sin asesor) y *Asesores disponibles* (enlace tranquilo a Equipo).
4. Las celdas *Responder*, *Llamar*, *Citas* y *Reasignar* son **filtros clicables de «Mi cola»** (`aria-pressed`; pulsar de nuevo quita el filtro, y el filtro activo se muestra con una píldora «Filtro: … ✕» en la cabecera de la cola).
5. **Reglas de cada celda:** lleva **verbo y destino** (el verbo es la etiqueta: Responder, Llamar, Reasignar…; el destino es la cola filtrada o la pantalla enlazada); lleva un **subtexto accionable** (p. ej. «N cierran en menos de 6 h», «N sin hacer a tiempo», «Nadie sin dueño»); **nunca más de 5 celdas**; **ninguna cifra sin verbo**.
6. **Pausa por feriado:** el reloj de atención se pausa (no se acumula atraso), de modo que los subtextos no hablan de atraso; la ventana de 24 h de WhatsApp **sí** sigue corriendo y la celda *Responder* lo dice («la ventana no se pausa»). Se mantiene el aviso de feriado ya existente sobre la tira.
7. **«Todo al día»:** una celda en 0 se atenúa y dice «Nada pendiente» / «Sin citas» / «Nadie sin dueño»; si no hay ningún ítem, Inicio muestra su estado vacío «Estás al día» / «El equipo está al día».
8. **Punto abierto.** *Reasignar* agrupa escalados y sin asesor. Si el dueño decide separarlos en dos celdas, el tope de 5 obliga a que *Asesores disponibles* salga de la tira (o a conservar una sola celda con ambos conteos en el subtexto). Esta decisión queda pendiente y no bloquea F1.
9. **Sin datos nuevos de backend** (contrato actual): la tira sale de los conteos que la cola ya calcula.

### C. Pulso de hoy (propuesta C) — Aceptada, por fases

> Actualización del dueño, 2026-10-12 (posterior a la redacción inicial): el Pulso deja de ser «Propuesta/Diferida» y queda **Aceptado**, para construirse por fases **después** de la Tira de acción (F1) y del Shell Z (F2).

1. **Qué es.** Una banda **plegable** «Pulso de hoy», para **supervisión** (Supervisor y Administrador), con indicadores de desempeño y comparación frente a ayer. No existe para el rol Asesor.
2. **Reglas que se conservan** (invariantes, valen para todas las fases):
   - **Nunca por encima de la cola de acción.** Va después de «Mi cola» en el orden de lectura y en el DOM (principio **Acción antes que observación**, Patterns Cap. 9). La maqueta de referencia la mostraba arriba de la pantalla; esa colocación **queda descartada** por esta regla.
   - **Sin cifras sin verbo:** cada indicador lleva su acción posible o su destino (MPX Cap. 3).
   - **Sin vigilancia individual:** el Pulso describe al equipo; no ordena ni expone a asesores por nombre como ranking de desempeño.
   - **Semáforos que no castigan feriado ni fuera de horario:** las mediciones de espera se hacen en horas hábiles y se muestran «En pausa» cuando el reloj está pausado.
   - Plegable (`aria-expanded`), cerrada por defecto en pantallas angostas.
3. **Fases:** **F3 = Pulso C0** (con las cifras que ya existen, solo supervisión); **F4 = cifras nuevas de backend (C1)**; **F5 = comparaciones y tendencias (C2)**.
4. **Detalle de indicadores y contrato:** lo define la propuesta de diseño en curso (**D7**), referenciada aquí como **«Propuesta A+C, a incorporar al ADR por enmienda»**. Este ADR **no fija** la lista final de indicadores ni sus fórmulas. El dueño citó, como candidatos de trabajo, las cifras *respondidas hoy*, *tiempo mediano de derivación a primera respuesta humana (horas hábiles)*, *espera más larga (horas hábiles)* y *ventanas perdidas*; son insumo para D7, no una definición.

## Alternativas consideradas

### Para el Shell

- **X — Sidebar de alto completo + barra de utilidades delgada (48 px).** La marca sube al Sidebar, pero el buscador, la campana, la ayuda y el avatar quedan en una barra delgada sobre el contenido. **Descartada** porque conserva un cromo superior en todas las pantallas (48 px de alto perdido) y divide las funciones transversales en dos sitios (marca y navegación a la izquierda, cuenta y avisos arriba), que es justamente la fragmentación que se quiere eliminar.
- **Y — Rail de iconos de 64 px (estilo Kommo)** que se expande al pasar el mouse o con el foco, con barra de navegación inferior en móvil. **Descartada** porque la expansión por hover no tiene equivalente táctil, deja a los asesores sin etiquetas de navegación a la vista y obliga a cambiar la navegación móvil (barra inferior), cosa que se pidió explícitamente no hacer.
- **Actual (barra superior de 64 px).** Se conserva únicamente en móvil, ya reducida a 56 px.

### Para los Indicadores

- **B — Cifras dentro del saludo** (la frase de bienvenida trae los números como enlaces). **Descartada** porque no escala a 5 elementos, pierde el estado «seleccionado» de un filtro y mezcla prosa con navegación; sirve como complemento del saludo, no como fuente de verdad de los conteos.
- **C — Pulso de hoy como reemplazo del cuadro Indicadores.** **No se adopta como reemplazo** de los Indicadores (eso lo cubre la Tira A), pero sí se **acepta como banda adicional de supervisión** y por fases (decisión C), porque exige cifras que el backend aún no entrega.
- **Actual (cuadro «Indicadores» + chips).** **Descartada**: duplica conteos y muestra cifras sin verbo.

## Consecuencias

- La Top Navigation deja de ser «por encima de todo»: solo existe en móvil. La jerarquía visual de Patterns Cap. 1 §3 pasa a «Sidebar de alto completo; contenido a su derecha» en escritorio y tablet.
- El Sidebar gana responsabilidades (marca, búsqueda, campana, cuenta): el componente `TopNav` y el `Sidebar` actuales se reorganizan; `CampanaNotificaciones`, `MenuUsuario` y el diálogo de búsqueda se reutilizan sin cambios de comportamiento.
- «Ayuda» deja de ser un acceso suelto; el límite del CDS («máximo 4 elementos interactivos en la barra») se reformula para móvil (búsqueda, campana, cuenta + control de menú).
- Inicio pierde el cuadro «Indicadores» y los chips; `zona_indicadores` del contrato deja de renderizarse (el campo puede mantenerse en el contrato hasta que se decida su retiro; no se elimina en este ADR).
- El mantenimiento de la regla «el logo siempre sobre fondo blanco» queda trasladado a un shell Navy: el tile blanco es obligatorio también en el Sidebar.
- No cambia ningún permiso ni capacidad (MPA §9), ni el conjunto de módulos de navegación (MPA §10); este ADR no toca la arquitectura funcional.
- El Pulso agrega, en F4, cifras nuevas de backend; requerirá un contrato aditivo y, de afectar `MAIEK_AI_API_ARCHITECTURE.md`, su propio registro.
- **(Enmienda 2026-10-13)** «Mi día» queda **retirado** del rail derecho: Inicio ya no tiene tarjeta de agenda, y sin otro contenido el rail no se pinta (la cola ocupa todo el ancho). El rail queda reservado para el Pulso.

## Enmienda 2026-10-13 — «Mi día» retirado y citas como llamada programada

*Enmendado por decisión del dueño, 2026-10-13* (sobre la maqueta «Mi día» de las opciones A/B/C; se aprobó la B). Dato de negocio que fija el alcance: **una cita es una LLAMADA PROGRAMADA con el cliente** (no una visita técnica ni presencial), así que no lleva dirección, zona ni tipo de visita.

1. **Se retira la tarjeta «Mi día»** del rail derecho de Inicio. Sin otro contenido, el rail no se renderiza (nunca vacío) y «Mi cola» ocupa todo el ancho desde `lg`. El Pulso (F3 en adelante) volverá a usar ese rail.
2. **Las citas de HOY no cuentan para el tope de 6 filas de «Mi cola»:** están «pineadas» (siempre visibles, aunque pasen de 6); las demás filas respetan el tope y el «y N más». Las citas de otros días van al pliegue **«Citas de otros días»** (plegado por defecto).
3. **Tira de acción — celda de citas.** Asesor: **«Citas de hoy»**; supervisor y administrador: **«Citas»**. La cifra = filas del filtro = **citas de hoy + citas vencidas sin cerrar de días anteriores** (ventana de 7 días); una cita de hoy que ya pasó cuenta una sola vez, en «hoy». El subtexto desglosa («2 hoy · 1 vencida sin cerrar», en ámbar solo la parte vencida) y al asesor le suma la próxima («Próxima 4:30 p. m. · Marcos»). Las vencidas de **más de 7 días** quedan fuera de la cifra y salen en una línea discreta bajo la cola («N citas vencidas hace más de 7 días sin cerrar · Ver») que lleva a Conversaciones con la vista `citas_vencidas_antiguas`. Esto cumple el criterio 3 (cifra = conteo de «Mi cola» filtrada) también para citas.
4. **Celda «Llamar»:** se muestra siempre cuando el módulo está encendido y en modo efectivo `activo` (`totales.llamadas_activo`, aditivo), con «Nada pendiente» si hay 0; con el módulo en sombra, apagado o ausente el campo, se oculta.
5. **Fila de cita (llamada programada):** acción primaria **«Llamar»** (`tel:`), «Copiar número» y «Abrir chat» en el menú; el texto dice «Llamada programada a las 4:30 p. m.». El supervisor ve el asesor de la cita y todos ven el producto (`producto`, `asesor`: campos aditivos de `_item_cita`). Una cita **vencida** suma la acción visible **«Cerrar o reprogramar»** (lleva al panel «Estado comercial» del lead; no hay reprogramador nuevo) y la explicación «La llamada programada pasó sin cerrarse: regístrala o reprográmala».
6. **Recordatorio en la campana (fase 2, aprobada):** cuando faltan menos de 60 minutos (el mismo umbral de `cita_inminente`) para una o más citas, **una entrada agrupada**: «Cita en N min · Nombre» o «N citas en los próximos 60 min». Se calcula en el navegador con `cita_en`, sin endpoint nuevo; categoría `operativo`. Esto **enmienda la exclusión de «cita próxima»** como evento-fuente de la campana (Patterns Cap. 8 §3, DEC-02).
7. **Disparador para volver a evaluar una tarjeta de agenda:** si, tras **medir dos semanas de citas reales**, una persona tiene **más de 3 citas por día de forma sostenida durante una semana**, se reabre la evaluación de una tarjeta o vista de agenda. Mientras tanto, la agenda de mes/semana sigue siendo el pendiente «calendario de agendados» y no se construye aquí.

*Alternativas descartadas en esta enmienda:* conservar «Mi día» como tarjeta (duplicaba la cola y la tira: las citas ya se veían en tres lugares) y añadir un reprogramador propio (la ficha del lead ya cambia resultado y fecha).

**Observación de producto (no se unifica ahora):** una *cita* (Lead `agendado` con `fecha_agendada`) y una tarea de «Para llamar» programada (`tareas_llamada.programada_para`) son dos modelos de «llamada a una hora». Propuesta para una decisión futura: tratar la cita como una tarea de llamada de origen «agenda» para tener un solo reloj, un solo registro de resultado y un solo recordatorio.

## Documentos enmendados (2026-10-12)

| Documento | Versión | Qué cambia |
|---|---|---|
| `MAIEK_AI_PRODUCT_PATTERNS.md` | 1.0 (nueva fila fechada 2026-10-12; otra fila 2026-10-13: Cap. 3 «Citas en Inicio» y Cap. 8 §3, §6 y errores a evitar, DEC-02) | Cap. 1 §3, §5, §6, §7 y §9 (Shell: barra superior solo en móvil; Sidebar de alto completo); Cap. 3 §2–§5, §7 y §9 (Zona de indicadores → Tira de acción; Pulso de hoy aceptado por fases); Cap. 9, «Acción antes que observación» (corolario del Pulso) |
| `MAIEK_AI_COMPONENT_SYSTEM.md` | 1.0.2 | Sidebar (variante de alto completo), Top Navigation (solo móvil, 56 px, sin Ayuda suelta), KPI Card (variante «Celda de acción») |
| `MAIEK_AI_ADR_INDEX.md` | 1.0 (sin fila nueva de versión: solo la tabla de registro, según su propia regla de cierre) | Fila 0005 |
| `DOCUMENTATION_INDEX.md` | 1.0 | «Última actualización» y párrafo de narrativa |

**No se enmienda** `MAIEK_AI_DESIGN_SYSTEM.md` (MDL) ni `MAIEK_AI_PRODUCT_ARCHITECTURE.md` (MPA): el MPA §10 define la navegación «independiente de cómo se vea» y no fija la ubicación de la Top Navigation; el MDL define tokens y no la composición del Shell. Pendiente, sin bloquear nada: la regla «el logo siempre sobre fondo blanco» **no está escrita en el MDL** (solo en el comentario de `wordmark.tsx`); conviene incorporarla en su próxima revisión.

## Criterios de aceptación (medibles)

**Tira de acción (F1)**

1. La tira tiene 4 celdas para Asesor y 5 para Supervisor/Administrador; **nunca más de 5** (prueba automatizada por rol).
2. Cada celda expone en su nombre accesible verbo + cifra + subtexto + destino («Responder: 7. 2 cierran en menos de 6 h. Filtra tu cola.»). Cero cifras sin verbo.
3. **Una sola fuente de verdad:** para cada filtro, la cifra de la celda es igual al conteo de ítems de «Mi cola» filtrada (diferencia = 0 en la suite de pruebas); en el DOM de Inicio ya **no existen** el cuadro «Indicadores» ni los chips de la cola.
4. **Siguiente mejor acción ≤ 200 px** desde el borde superior de la ventana hasta el borde superior de la tarjeta «Tu siguiente mejor acción», a 1440 × 900, con la tira presente y Shell Z (medición a verificar en F1; si no se cumple, se reordena la cabecera de Inicio, no se retira la tira).
5. **Sin scroll horizontal de página a 375 px** (`scrollWidth ≤ clientWidth` del documento). En móvil la tira puede desplazarse horizontalmente **dentro de su propio contenedor**, con indicio visible de que hay más celdas.
6. **Objetivos táctiles ≥ 44 px** de alto en móvil (≥ 32 px en escritorio, regla heredada del CDS) para cada celda, enlace y control del Shell.
7. Feriado: ningún subtexto habla de atraso; *Responder* indica que la ventana de 24 h no se pausa. Todo al día: celdas en 0 atenuadas con subtexto «Nada pendiente»; estado vacío de Inicio visible.
8. Contraste AA (4,5:1 texto, 3:1 elementos) en claro y oscuro, incluida la celda activa.

**Shell Z (F2)**

9. Desde 768 px **no hay `<header>` de página** ni barra superior; por debajo de 768 px la barra mide **56 px** y contiene exactamente: hamburguesa, marca, búsqueda, campana, avatar.
10. Sidebar de **280 px** expandido / **64 px** colapsado; a **768 px** y hasta 1023,98 px está colapsado aunque la preferencia guardada sea «expandido»; a 768 px el contenido útil mide **≥ 704 px**.
11. En el Sidebar, de arriba hacia abajo: marca sobre tile blanco, buscador, campana con contador, navegación, tarjeta de cuenta (nombre + rol); en colapsado: isotipo, búsqueda, campana, navegación, avatar.
12. «Ayuda» solo existe dentro del menú de cuenta, en todos los tamaños; no hay selector de negocio.
13. Orden de tabulación verificado: Saltar al contenido → marca → búsqueda → campana → navegación → cuenta → contenido; `Cmd/Ctrl+K` abre el buscador desde cualquier pantalla; el foco vuelve al disparador al cerrar cualquier diálogo o menú.
14. Landmarks: en escritorio, `navigation` + `main` sin `banner`; en móvil, `banner` + `main`.
15. Ninguna regresión de navegación AJAX/fragmento: el Shell no se reconstruye al navegar (Patterns Cap. 1 §6).

**Pulso (F3 en adelante)**

16. En el orden del DOM, el Pulso aparece **después** de «Mi cola»; no existe para el rol Asesor; es plegable con `aria-expanded`; ningún indicador muestra un ranking nominal de asesores.
17. En feriado o fuera de horario hábil, los indicadores de espera muestran «En pausa» y no cambian de color a estado de alerta.

## Plan por fases

| Fase | Contenido | Entrada | Salida |
|---|---|---|---|
| **F0 — Documentos** | Este ADR y las enmiendas a Patterns y CDS (2026-10-12) | Decisión del dueño | Corpus alineado antes de tocar código |
| **F1 — Tira de acción (A)** | Tira por rol, filtros de la cola, retiro de «Indicadores» y de los chips, feriado y «todo al día». Sin dato nuevo de backend | F0 | Criterios 1–8 |
| **F2 — Shell Z** | Sidebar de alto completo con marca, búsqueda, campana y cuenta; barra de 56 px solo en móvil; «Ayuda» al menú de cuenta | F1 | Criterios 9–15 |
| **F3 — Pulso C0** | Banda plegable para supervisión con las cifras que ya existen | F1 y F2 | Criterios 16–17 |
| **F4 — Pulso C1** | Cifras nuevas de backend (contrato aditivo), según D7 | F3 y D7 | Enmienda a este ADR con la lista de indicadores |
| **F5 — Pulso C2** | Comparaciones frente a ayer y tendencias | F4 | Enmienda a este ADR |

Cada fase sigue el ciclo de `MAIEK_AI_IMPLEMENTATION_ROADMAP.md` §2.1 y se referencia este ADR en su commit. Push y deploy requieren autorización explícita y separada del dueño.

## Reconciliación con el corpus

- [ ] Menor / local
- [x] Sustancial — cambia la composición del Shell fijada por `MAIEK_AI_PRODUCT_PATTERNS.md` Cap. 1 §3 y la Zona de indicadores de Cap. 3, y la especificación de componentes de `MAIEK_AI_COMPONENT_SYSTEM.md` (Sidebar, Top Navigation, KPI Card). Ambos documentos se actualizan en el mismo cambio, citando este ADR.

Fecha en que se actualizaron los documentos de origen — 2026-10-12 (mismo cambio que crea este ADR).
