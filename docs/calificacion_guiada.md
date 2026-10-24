# Calificación guiada con botones — protocolo

Versión 2026-10-24 · Código: `agent/calificacion_guiada.py` · Scripts: `scripts/configurar_calificacion_guiada.py`, `scripts/medir_calificacion_guiada.py` · Estado: **construida y probada en local, apagada** (`calificacion_guiada_modo` = apagado por defecto).

## Para qué

La auditoría de 674 chats (`docs/auditoria_chats_gabi_2026-10-18.md`) mostró que la mayor fuga era pedir el nombre antes de dar valor. La calificación guiada reemplaza ese paso por preguntas de toque (botones o lista) que avanzan el flujo de venta, y deja la IA para lo consultivo.

## Flujo

| Etapa | Qué hace | IA |
|---|---|---|
| 0. Primer mensaje | Si el cliente solo mandó el texto prellenado del anuncio o un saludo: mensaje FIJO («Hola, soy Gabi, asesora virtual de Cálidda Hogar…») con la pregunta de gas en la misma burbuja. Sin producto ni precio. Si pidió precio, se le promete («te lo cuento en un momento»). Si no se sabe qué producto es (campaña, anuncio o mensaje), antes sale la lista de producto. Si escribió una pregunta propia, responde la IA (sin nombre ni precio, salvo que lo pidiera) y después viene la pregunta de gas. | No |
| 1. Gas | ¿Tu casa ya tiene gas natural de Cálidda? Sí / No tengo aún / No estoy seguro | No |
| 2. Equipo | Terma: lista con punto de gas y ductería (un mensaje). Secadora y centro de lavado: solo punto de gas. Cocina: ninguno. | No |
| 3. Titular | Soy el titular / Es de un familiar / Es de otra persona | No |
| 4. Tamaño | Terma: 1, 2 o 3+ baños. Secadora y centro de lavado: hasta 4 o 5+ personas. Cocina: de pie, o empotrable/encimera y qué le suma (solo encimera, campana, horno empotrable, horno y campana). | No |
| 5. Etapa consultiva | Un solo mensaje de Claude: confirma que el producto le sirve (solo si no alcanza propone UNA alternativa), da el precio solo si el cliente lo pidió, pide nombre (si falta) y DNI del titular o número de suministro (no es una aprobación) y deriva. | Sí |

## Sin gas

«Contratar el gas» → se le da el teléfono de Nuevos suministros (`614 9000, opción 5`, configurable con `calificacion_telefono_suministros`) y el caso se cierra con el resultado **Solicita suministro de gas**. «Comprar el equipo» → sigue con otros medios de pago, sin financiamiento de Cálidda. «No estoy seguro» → se le indica que mire su recibo.

## Reglas

- Si el cliente escribe en vez de tocar un botón, la IA responde y el sistema retoma el paso pendiente (la pregunta original y hasta 2 retomos).
- El precio solo se menciona si el cliente lo pidió (incluido el prellenado «¿Cuánto cuesta y cómo lo pago?»), y solo en la etapa consultiva, si el catálogo lo respalda; si no, el asesor lo confirma.
- Una lavadora sola no es producto de gas: no pregunta por el punto de gas.
- Las dimensiones de la terma (1 baño → 5.5 a 10 l/min, 2 baños → 14 a 17, 3+ → 17 o más) y de la secadora (hasta 4 personas → 10 kg, 5+ → 22 kg) son orientativas; hay que confirmarlas con el proveedor.
- Estado en eventos del Timeline: `calificacion_pregunta` (interno) y `calificacion_respuesta` (visible para el asesor). Sin migración.
- Todos los pasos fijos usan el origen de envío `gabi_calificacion` (esencial, dentro de la ventana de 24 h).

## Activación y medición

1. `python scripts/configurar_calificacion_guiada.py --activar` guarda `calificacion_guiada_modo=activo` y la hora de corte (`calificacion_guiada_activa_desde`). `--desactivar` es el interruptor de emergencia.
2. `python scripts/medir_calificacion_guiada.py` compara los N días anteriores contra los posteriores al corte (por producto): continuación de la conversación, mensajes del cliente, derivación, agendado, vendido y ficha mínima de los derivados. No hay grupo de control en paralelo: se compara por producto y la cohorte «después» madura con los días.
3. Punto de partida previo: auditoría del 18-oct (63 % sin respuesta; 8,2 % agendado o vendido).
