# Auditoría de chats de Gabi — 2026-10-18 (segunda auditoría)

Fuente: panel de producción con la sesión del dueño, solo lectura (`/api/conversaciones` y `/api/conversation/{id}/mensajes`). Se leyó todo en memoria del navegador; **no se guardó ningún chat, teléfono ni nombre**: este documento solo trae conteos y frases genéricas.
Muestra: **674 conversaciones activas** (creadas del 15-jul al 18-oct, casi todas desde el 15-sep), 3 047 mensajes de Gabi, 3 693 del cliente, 1 410 de asesores.
Límites: solo conversaciones activas (sesgo de supervivencia); las clasificaciones de mensajes son por palabras clave, no lectura humana de cada chat; comparaciones descriptivas, no causales; varias muestras son pequeñas (se indica la n).

## 1. Qué funcionó respecto a la auditoría del 5-oct

| Problema del 5-oct | Hoy |
|---|---|
| `**` crudo en el 41 % de los mensajes | Resuelto: la limpieza automática lo elimina antes de enviar (el log muestra que Claude aún lo escribe en 32 %, pero no llega al cliente). |
| Mensajes sin pregunta final (58 % vs 93 % de respuesta) | Casi resuelto: 2,6 % sin pregunta ni llamado a la acción. |
| Gabi aprueba o descalifica al cliente | Sin casos: solo 1 mensaje en 3 047 toca el tema, y es una aclaración correcta de que Gabi no evalúa. |
| Mensajes largos | Parcial: 8 % pasa de 500 caracteres (242 mensajes); 30 % pasa de 350. |
| Reglas del prompt | Se incumple «una sola pregunta por mensaje»: 165 mensajes (5,4 %) traen 2 o más signos de pregunta. |

## 2. Dónde se pierde la venta

Resultado final de las 674: sin_respuesta 422 (63 %), no_interesado 64, sin resultado 36, agendado 33, consulta_atc 35, no_califica 26, vendido 22, cartera_fnb 14. Agendado + vendido = 55 (8,2 %).
Los que terminan agendados o vendidos escriben una mediana de **9 mensajes**; los que se pierden, **3**. Cada mensaje de más del cliente importa: el trabajo de Gabi es que el cliente siga escribiendo y llegue a un asesor con los datos.

Último mensaje real de Gabi (sin contar reenganches automáticos) en las 422 conversaciones sin respuesta:

| Dónde quedó | Conv. | Lectura |
|---|---|---|
| Gabi pidió el **nombre** y el cliente no contestó | **109** (87 sin ningún humano) | Es la mayor fuga única (26 %). 66 de ellas son clientes que tocaron el anuncio, mandaron solo el texto prellenado «Estoy interesado en financiar…» y recibieron «¿me dices tu nombre?». |
| Gabi hizo otra pregunta (qué producto, cuántas personas, etc.) | 94 | Gabi pregunta antes de dar valor. |
| Derivación a asesor y el cliente se enfrió | 111 (85 con mensaje humano) | Se pierde después de entregarlo; ver §5. |
| Gabi dio precio y no hubo respuesta | 53 | Falta empujar al siguiente paso. |
| Pidió DNI o suministro | 17 | Fuga pequeña. |
| Último mensaje sin pregunta | 29 | Pocos. |

## 3. Respuestas de Gabi que retienen información o no resuelven

1. **Pide el nombre antes de responder.** En 125 conversaciones (19 %) Gabi pidió el nombre al menos dos veces. En 67 preguntas directas del cliente (precio, marcas, capacidad, trámite) la respuesta fue pedir el nombre sin dar ningún dato: «Antes de contarte sobre las opciones, ¿me dices tu nombre?». Después de esa respuesta el cliente siguió escribiendo en 81 % de los casos, contra 86 % cuando Gabi sí respondió (n = 67 y 273; agendado + vendido 9 % contra 13,5 %). La diferencia es modesta y con muestra chica: no prueba daño, pero tampoco hay ganancia en retener el dato.
2. **Pregunta qué producto quiere aunque ya viene de un anuncio.** Cuando el cliente manda «¿Cuánto cuesta y cómo lo pago?» con una campaña identificada, Gabi respondió con precio en 101 casos (agendado + vendido 7,9 %), pero en **43 casos pidió «¿qué producto te interesa?»** (**0 % agendado + vendido**, n = 43) y en otros 14 dio una respuesta distinta (solo 29 % volvió, n = 14). La campaña ya dice qué se anuncia, así que la pregunta es innecesaria.
3. **Perdió el hilo con respuestas cortas.** Entre las ~40 veces que Gabi dijo «no tengo esa información», varias fueron ante respuestas del cliente a una pregunta suya: «Sí», «Ok», «Tres personas», «De 10», «Ducha solamente», «Para 1». Gabi no ligó la respuesta con su propia pregunta anterior. Es un fallo de contexto, no de falta de datos.
4. **Datos que Gabi no tiene** (40 mensajes en 39 conversaciones, 6 %). Temas repetidos: si hay tienda física; garantía e instalación gratis; dimensiones y características técnicas; diferencia entre las opciones 1 y 4 de un listado; «otras marcas de menor precio»; costo de un punto adicional; opciones de combo; encendido (si usa pila tipo D). Falta contenido en la base de conocimiento, no solo ajustar el tono.
5. **Fallas técnicas visibles:** 12 conversaciones con mensaje de error técnico; 38 con el texto automático «Te transferí con un asesor y te atenderá…» (modo sin IA o fuera de horario). De esas 38, 23 siguen sin resultado, 10 quedaron sin respuesta, 3 agendadas y 1 vendida.

## 4. Lo que sí funciona (no tocar)

- Con el nombre pedido primero, el 73 % de los que tocan el anuncio con «financiar» vuelve a escribir y el 58 % llega a 3 o más mensajes; da 8,4 % de agendado + vendido (n = 249). El primer mensaje con precio (cuando la campaña tiene producto) da 67 % de regreso y 7,9 % (n = 101). **No hay diferencia concluyente entre «nombre primero» y «valor primero»: se mantiene el A/B en lugar de asumir.**
- Textos propios del cliente (no prellenados) responden mejor: 82–89 % vuelve; agendado + vendido hasta 10,5 % (n = 57 con nombre primero).
- Gabi no descalifica ni aprueba financiamiento (cumple las restricciones del prompt).
- Preguntas finales y largo mediano (254) están bien.

## 5. Después de Gabi: el empalme con el asesor (condiciona el valor de todo lo anterior)

De las 422 sin respuesta, **171 tuvieron un mensaje humano** (40 %). 354 de las 674 conversaciones recibieron mensaje de un asesor.
- **108 de esas 354 (30 %) llegaron al asesor sin nombre** guardado y **30 (8 %) sin interés/producto**. Un asesor que recibe un lead sin nombre ni producto tiene menos que decir.
- Hallazgo importante: **el sistema no captura el nombre del perfil de WhatsApp** (Meta lo envía en cada mensaje entrante como `contacts[].profile.name`; el código no lo lee). Hoy Gabi lo pide, y es la mayor fuga.
- Hay que cerrar el flujo con una derivación con datos mínimos: producto de interés, nombre (aunque sea el del perfil), si es titular y lo que ya preguntó el cliente.

## 6. Mejoras propuestas, ordenadas por impacto esperado y riesgo

Todas con interruptor de apagado y sin tocar el prompt de la base de datos hasta aprobar. Las que dicen «A/B» se validan con grupo de control.

| # | Mejora | Qué ataca | Esfuerzo | Validación |
|---|---|---|---|---|
| M1 | **Contexto del anuncio para Gabi**: pasar título y texto del anuncio (y producto de la campaña) al contexto del turno, y regla «si ya sabes qué anuncio es, no preguntes qué producto». | 43 casos con 0 % de conversión; 94 fugas por «otra pregunta» | Bajo | A/B o antes/después sobre `prellenado_precio` |
| M2 | **Responder primero, pedir el nombre después** (nunca bloquear una pregunta directa). Es el brazo B del A/B del primer mensaje. | 109 fugas en el nombre; 67 respuestas que retienen | Bajo-medio | A/B 50/50, sombra primero |
| M3 | **Usar el nombre del perfil de WhatsApp** (guardar `profile.name`, saludar por él y confirmarlo de pasada), en vez de preguntarlo. Reduce la fricción y mejora el dato que llega al asesor. | 108 derivaciones sin nombre + la fuga del nombre | Medio (webhook + guardar); decidir si el nombre del perfil es confiable (apodos, emojis) | Medir % con nombre y continuación |
| M4 | **Ligar respuestas cortas a la pregunta anterior** («sí», «ok», «tres personas»): regla de contexto y, si hace falta, un bloque con «tu última pregunta fue: …». | Respuestas «no tengo esa información» tras un «sí» | Bajo-medio | Revisar muestra a mano; conteo de `noinfo` |
| M5 | **Base de conocimiento**: tienda física, garantía, instalación incluida o no, dimensiones por modelo, diferencias entre opciones, punto adicional, encendido, combos. Requiere que el dueño o Cálidda den los datos. | 40 casos de «no tengo la información» | Contenido, no código | Conteo de `noinfo` |
| M6 | **Largo ≤ 350 y una sola pregunta por mensaje**: instrucción de contexto (ya redactada en `mejoras_gabi_largo_y_ab_primer_mensaje.md`). | 8 % sobre 500; 5,4 % con 2 preguntas | Bajo | Log `gabi_calidad` |
| M7 | **Empujar el paso siguiente tras dar precio** («¿lo quieres con financiamiento o contado?» / pasar a titular) | 53 fugas tras precio | Bajo | Antes/después |
| M8 | **Derivación con ficha mínima** (producto, nombre, titular sí/no, tema) y resumen para el asesor. | 30 % sin nombre; 85 enfriadas tras derivar | Medio | % de leads con ficha completa |

Orden recomendado: **M1 → M2/M3 (juntas) → M4 → M6 → M7 → M5/M8** (estas últimas dependen de contenido o de decisiones tuyas).

## 7. Decisiones y datos que se necesitan

1. Aprobar M1 (contexto del anuncio): es la de mejor relación impacto/riesgo.
2. Decidir M2 y M3: ¿usar el nombre del perfil de WhatsApp aunque sea un apodo, y responder antes de pedir el nombre?
3. Datos de contenido para M5: ¿hay tienda física?, ¿garantía por producto?, ¿instalación incluida?, ¿dimensiones? (Cálidda o el catálogo).
4. Confirmar que el 85 % de enfriamientos después de la derivación se revisan aparte con los asesores (fuera del alcance de Gabi).

## 8. Corrección del 2026-10-19 (cruce con el análisis del 8-oct)

El análisis de conversión del 8-oct (`analisis_conversion_2026-10-08.txt`) midió que los turnos largos se responden **más** (≤200 caracteres 80,4 %; 351–500 89,3 %; >500 86,6 %). Por eso **M6 («≤350 caracteres») queda EN ESPERA**: no tiene respaldo y no se activa sin experimento. Se conserva solo la parte de «una sola pregunta por mensaje» (5,4 % la incumple), que además está en el prompt. Los pendientes quedaron registrados como ids 60–67 en la matriz maestra.
