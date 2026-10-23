# Mejoras de Gabi: largo del mensaje y A/B del primer mensaje — BORRADOR para aprobar

Versión 2026-10-18 · Estado: **borrador, nada construido ni desplegado.** Punto 33 de la matriz de pendientes.

## 1. Qué dicen los datos (log `gabi_calidad`, 11–18 oct, 112 respuestas; descriptivo, no causal)

| Medida | Auditoría 5-oct | Hoy |
|---|---|---|
| `**` en lo que escribe Claude | 41 % | 32 % (ya se limpia antes de enviar) |
| Sin pregunta ni llamado a la acción (sin derivaciones ni agradecimientos) | 19 % | 2,6 % (2 de 77) |
| Largo mediano | 271 | 254 caracteres |
| Más de 350 caracteres | — | 30 % |
| Más de 500 caracteres | — | 6 % |

Conclusión: la limpieza de `**` y la pregunta final **ya están resueltas**; no se construye salvaguarda de código para eso. Quedan dos palancas: el largo y el primer mensaje de los leads de anuncio (52 % de los leads termina en `sin_respuesta`; 84 % de ellos empezó con el texto prellenado del anuncio).

## 2. Cambio 1 — apuntar a 350 caracteres o menos (sin truncar)

**Dónde va:** un bloque más en `_armar_bloques_contexto` (`agent/brain.py`), dentro de `<contexto_negocio>`. NO se edita el prompt de la base de datos (`IdentidadAgente`) ni `config/prompts.yaml`, así que el system prompt cacheado no cambia.

**Interruptor:** clave de configuración `gabi_largo_objetivo_activo` (apagada por defecto), editable sin desplegar.

**Texto propuesto del bloque (para que lo apruebes o corrijas):**

> Largo de tu respuesta: apunta a 350 caracteres o menos (unas 3 o 4 líneas de WhatsApp). Dale al cliente solo lo que necesita para dar el siguiente paso; el resto lo cuentas en el siguiente mensaje. Si el cliente pidió un detalle concreto (precio, cuotas, requisitos), respóndelo completo aunque pase de 350. Termina siempre con una sola pregunta.

**Qué se mide:** el mismo log `gabi_calidad` (porcentaje sobre 350 y sobre 500) y la tasa de respuesta del cliente en 24 h, antes y después. Se enciende, se espera una semana de tráfico y se compara.

**Riesgo:** que Gabi omita datos que el cliente sí necesitaba. Por eso la excepción para consultas concretas y la revisión de una muestra de chats a mano antes de dar el cambio por bueno.

## 3. Cambio 2 — A/B del primer mensaje en leads de anuncio

**Pregunta que responde:** ¿la tasa de continuación sube si la primera respuesta da valor primero (precio o financiamiento más una pregunta) en vez de pedir el nombre primero? En la auditoría, tras «pedir nombre primero» el cliente seguía 76 % contra 75 % cuando se daba valor primero (n = 44): no hay evidencia, por eso se mide.

**Quién entra:** conversaciones nuevas cuyo primer mensaje es el texto prellenado de un anuncio o enlace `wa.me` (misma regla de origen que `es_solo_clic`, `docs/experimento_solo_clic.md` §2 (a)–(b)), sin asesor, sin pausa, sin triaje ATC cerrado, ciclo no reabierto.

**Brazos (reparto 50/50 por hash determinista de `conversation_id` con sal propia `exp_primer_mensaje_<época>`):**

| Brazo | Instrucción añadida al contexto del primer turno |
|---|---|
| A — control | Ninguna (lo de hoy: saluda y pide el nombre). |
| B — valor primero | «Es el primer mensaje de un cliente que llegó por un anuncio. Antes de pedir su nombre, responde lo que el anuncio promete: el producto y su precio de contado, o si preguntó por pagos, cómo funciona el financiamiento en una frase. Cierra con UNA pregunta que lo haga avanzar (por ejemplo para qué lo necesita). Pide el nombre en el siguiente mensaje.» |

Solo cambia el primer turno de Gabi; del segundo en adelante ambos brazos usan el mismo prompt.

**Interruptores:** `ab_primer_mensaje_modo` con valores `apagado` (por defecto), `sombra` (solo registra a qué brazo habría ido cada conversación, todos se comportan como A) y `activo`. Apagarlo devuelve todo a A al instante. Cambiar `ab_primer_mensaje_epoca` abre una cohorte nueva.

**Métrica primaria:** el cliente envía al menos un mensaje propio distinto del prellenado en las 24 h siguientes a la primera respuesta de Gabi.
**Secundarias:** llegada a derivación, agendado, vendido, mensajes del cliente por conversación, largo de la primera respuesta. **Freno de seguridad:** si el brazo B queda más de 10 puntos por debajo de A con al menos 100 conversaciones por brazo, se apaga solo y se avisa.

**Tamaño de muestra (estimación mía, validar con el volumen real de leads de anuncio):** para detectar una diferencia de 10 puntos (por ejemplo 60 % contra 70 %) con 80 % de potencia y 95 % de confianza hacen falta unas 360 conversaciones por brazo, 720 en total. Para detectar 5 puntos, unas 1 400 por brazo. Hay que medir cuántos leads de anuncio entran por semana para saber cuánto dura; si son pocos, solo se podrán detectar diferencias grandes.

**Choque con el experimento «solo clic»:** ambos actúan sobre los mismos leads. El A/B cambia el primer mensaje de Gabi, y la definición de «solo clic» parte del primer mensaje de Gabi. Hay que (1) mantener las dos asignaciones independientes (sales distintas) y (2) analizar «solo clic» separando por brazo del A/B. Mientras «solo clic» siga en sombra no hay conflicto de comportamiento, solo de análisis.

## 4. Decisiones que necesito de ti

1. ¿Apruebas el texto del Cambio 1, o lo cambias?
2. ¿Apruebas el brazo B tal como está redactado, o prefieres otro enfoque (por ejemplo ofrecer botones de producto)?
3. ¿Empezamos el A/B en `sombra` unos días para medir cuántos leads de anuncio entran por semana, antes de activarlo? (Lo recomiendo.)
4. Confirmar el freno de seguridad de 10 puntos con 100 por brazo.

## 5. Plan de construcción (tras tu aprobación, ciclo del Roadmap §2.1)

1. `agent/ab_primer_mensaje.py`: función pura de elegibilidad y asignación, más lectura de las claves de configuración.
2. Bloques nuevos en `_armar_bloques_contexto` (largo y brazo B), ambos con interruptor.
3. Registro del brazo en el log y en un evento del lead (sin migración si cabe en `eventos_lead.tipo`; el tipo debe caber en 30 caracteres).
4. Script de solo lectura `scripts/analizar_ab_primer_mensaje.py`.
5. Pruebas, suite completa, commit local y, solo con tu autorización expresa, deploy.

## 6. Corrección del 2026-10-19

El **Cambio 1 (≤350 caracteres) queda EN ESPERA**: el análisis del 8-oct mostró que los mensajes largos se responden más, así que no hay respaldo para acortarlos. Solo el Cambio 2 (A/B del primer mensaje) sigue vigente, ahora acompañado por M1 (contexto del anuncio) y M3 (nombre del perfil de WhatsApp) de `auditoria_chats_gabi_2026-10-18.md`.
