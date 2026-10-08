# Dossier para consulta legal: llamadas telefónicas del estado "Para llamar" (Gaso+ / Maiek AI)

Preparado el 8 de octubre de 2026 para ser llevado a un abogado.
Este documento NO es asesoría legal ni afirma que la práctica sea legal o ilegal. Es una recopilación de normas y fuentes con una lista de preguntas. Todo lo que aquí se dice debe ser contrastado por un abogado peruano especializado en protección de datos y derecho del consumidor.

---

## 0. Resumen ejecutivo (10 líneas)

1. Se evalúa que un asesor humano LLAME por teléfono (celular normal, máx. 3 intentos, 8:00-19:00 lun-sáb) a clientes que escribieron primero a Gabi por WhatsApp pidiendo financiamiento de un gasodoméstico y luego se quedaron en silencio.
2. La norma más relevante es la Ley 32323 (9-may-2025), que modifica el art. 58.1.e del Código del Consumidor: prohíbe call centers, "sistemas de llamado telefónico", mensajes masivos y telemercadeo para promover productos, salvo que el consumidor, "por iniciativa propia", contacte al proveedor y manifieste consentimiento "libre, previo, informado, expreso e inequívoco" de ser contactado por teléfono u otro medio. Se revoca con efecto inmediato y sin expresión de causa. Infracción muy grave, hasta 450 UIT (texto de la ley y nota oficial de Indecopi leídos).
3. Lo que NO queda claro en los textos: (a) si el primer mensaje del cliente ("quiero información") ya equivale al consentimiento "de ser contactado por teléfono" o si hace falta una aceptación específica de la llamada; (b) si una llamada hecha a mano por un asesor es un "sistema de llamado telefónico/telemercadeo"; (c) si una llamada de seguimiento a quien pidió información es "comunicación comercial" (el MTC define "información con fines comerciales" de forma muy amplia, incluyendo "captar consumidores").
4. El Reglamento de la Ley 29733 (DS 016-2024-JUS) exige consentimiento directo para publicidad/prospección (art. 26.1), carga de la prueba en quien trata los datos (art. 9), y revocación atendida en máx. 10 días (arts. 10.2 y 26.5). Su figura del "primer contacto" (art. 26.2) está en duda tras la Ley 32323: Indecopi la considera tácitamente derogada; no encontré un pronunciamiento posterior de la ANPD.
5. Nuevo: el DS 018-2026-MTC (El Peruano, 15-sep-2026) crea la serie de numeración "500" exclusiva para llamadas y SMS comerciales/publicitarios, con 180 días de adecuación para los operadores. Falta que el abogado confirme si afecta a las llamadas de asesores de Gaso+/Cálidda y desde qué fecha.
6. La política de WhatsApp Business (actualizada 23-sep-2026) exige opt-in para "mensajes o llamadas", recomienda un opt-in SEPARADO para iniciar una llamada, obliga a respetar los rechazos "dentro o fuera de WhatsApp" y permite limitar o cerrar cuentas por feedback negativo (relevante por el antecedente de baneo en Whapi).
7. Por defecto, la evidencia más sólida sería: llamar SOLO a quien acepte expresamente la oferta de Gabi (no a quien guarda silencio), conservar la evidencia del consentimiento y marcar "no_llamar" de forma inmediata ante cualquier rechazo.
8. La política de privacidad del repo (22-jul-2026) NO menciona llamadas telefónicas, dice que el servicio lo opera Cálidda (titularidad por confirmar), no nombra a todos los proveedores ni las transferencias al extranjero, y tiene dos placeholders sin completar ("[correo de contacto de Cálidda]").
9. Multas informadas (dato secundario): Código del Consumidor hasta 450 UIT; Ley 29733 hasta 100 UIT (tope 10 % de ingresos brutos anuales); caso reciente: Interbank 74,88 UIT en primera instancia (18-ago-2026) por no acreditar consentimiento.
10. Se incluye un cuestionario de 15 preguntas (sección 8), una opción conservadora por defecto (sección 9) y los textos propuestos de la oferta de Gabi y de la nota de privacidad (anexos A y B).

---

## 1. Cómo leer este dossier: qué es "texto oficial leído" y qué no

Etiquetas usadas en todo el documento:
- [OFICIAL-LEÍDO]: texto o comunicado de una entidad del Estado que abrí y leí.
- [TRANSCRIPCIÓN-LEÍDA]: texto de una norma transcrito por un portal jurídico privado (no el diario oficial directamente). Lo cotejé con citas de otras normas oficiales cuando fue posible.
- [SECUNDARIA]: nota de prensa, estudio de abogados u opinión. Sirve de orientación, no de autoridad.
- [NO ABIERTA]: apareció en resultados de búsqueda pero no pude abrir la página o el documento; no lo cito como verificado.

Fecha de consulta de todas las fuentes: 8 de octubre de 2026.

### 1.1 Tabla de fuentes

| # | Fuente | URL | Fecha | Etiqueta |
|---|---|---|---|---|
| F1 | DS 016-2024-JUS, Reglamento de la Ley 29733 (El Peruano, edición del sábado 30-nov-2024), PDF en gob.pe | https://cdn.www.gob.pe/uploads/document/file/7568330/6426760-decreto-supremo-n-016-2024-jus-reglamento-de-la-ley-n-29733-ley-de-proteccion-de-datos-personales-publicado-nov-2024.pdf | 30-nov-2024 | OFICIAL-LEÍDO (extraje el texto del PDF; la extracción tiene errores menores de formato) |
| F2 | Ley 29733, copia alojada por MINSA (texto con concordancias al reglamento anterior DS 003-2013-JUS) | https://www.minsa.gob.pe/Recursos/OGTI/SINADEF/Ley-29733.pdf | s/f | OFICIAL-LEÍDO con reserva: no verifiqué si incorpora modificaciones posteriores |
| F3 | Ley 32323 (modifica el art. 58 de la Ley 29571), transcripción de LP Derecho | https://lpderecho.pe/prohiben-spam-llamadas-mensajes-correos/ | 9-may-2025 | TRANSCRIPCIÓN-LEÍDA. No abrí la edición del diario El Peruano. El párrafo 58.3 y la disposición complementaria final coinciden literalmente con lo citado en los considerandos del DS 018-2026-MTC (F4) |
| F4 | DS 018-2026-MTC, norma sobre la numeración (serie 500) para llamadas y SMS comerciales o publicitarios. Páginas 27-32 de El Peruano del 15-sep-2026, copia PDF alojada por LP Derecho | https://img.lpderecho.pe/wp-content/uploads/2026/09/Decreto-Supremo-018-2026-MTC-LPDerecho.pdf | 15-sep-2026 | OFICIAL-LEÍDO (reproducción de las páginas del diario oficial) |
| F5 | Indecopi, nota de prensa "Indecopi exhorta a las empresas a cumplir con nueva ley que prohíbe llamadas spam..." | https://www.gob.pe/institucion/indecopi/noticias/1168482-indecopi-exhorta-a-las-empresas-a-cumplir-con-nueva-ley-que-prohibe-llamadas-spam-y-anuncia-drasticas-acciones-por-incumplimiento | 16-may-2025 | OFICIAL-LEÍDO |
| F6 | Indecopi, comunicado sobre llamadas no deseadas | https://www.gob.pe/institucion/indecopi/noticias/1173297-comunicado | 22-may-2025 | OFICIAL-LEÍDO |
| F7 | Indecopi / Consejo Nacional de Protección del Consumidor, guía "Llamadas telefónicas no deseadas (llamadas spam)" | https://consumidor.gob.pe/2025/06/20/llamadas-telefonicas-no-deseadas-llamadas-spam/ | 20-jun-2025 | OFICIAL-LEÍDO |
| F8 | MINJUSDH, nota "Autoridad de Protección de Datos Personales opina sobre modificación del Código... métodos comerciales agresivos" | https://www.gob.pe/institucion/minjus/noticias/18893-autoridad-de-proteccion-de-datos-personales-opina-sobre-modificacion-del-codigo-de-proteccion-del-consumidor-en-relacion-a-metodos-comerciales-agresivos | 12-sep-2018 | OFICIAL-LEÍDO, pero ANTERIOR a la Ley 32323 y al reglamento vigente: solo contexto histórico |
| F9 | WhatsApp Business Messaging Policy | https://www.whatsapp.com/legal/business-policy (la URL business.whatsapp.com/policy redirige a whatsappbusiness.com/es-la/policy/) | "Last updated: September 23, 2026" | OFICIAL (de Meta) LEÍDO |
| F10 | Meta for Developers, "Getting opt-in" | https://developers.facebook.com/docs/whatsapp/overview/getting-opt-in | sin fecha visible (alude a la política de nov-2024) | OFICIAL (de Meta), leído vía resumen de la herramienta |
| F11 | Meta for Developers, Click to WhatsApp (Marketing API) | https://developers.facebook.com/documentation/ads-commerce/marketing-api/ad-creative/messaging-ads/click-to-whatsapp | sin fecha visible | OFICIAL (de Meta). No contiene nada sobre opt-in ni sobre uso del número fuera de WhatsApp |
| F12 | Gestión, "Los dos cambios que trae la ley contra las llamadas spam y la fiscalización del Indecopi" | https://gestion.pe/peru/los-dos-cambios-que-trae-la-ley-contra-las-llamadas-spam-y-la-fiscalizacion-del-indecopi-noticia/ | 22-may-2025 | SECUNDARIA (cita a la directora de fiscalización de Indecopi) |
| F13 | El Peruano (suplemento Jurídica), "Protege tus datos: Ley N.º 32323 prohíbe publicidad sin tu consentimiento expreso" (opinión de una autora) | https://elperuano.pe/noticia/273332-protege-tus-datos-ley-no-32323-prohibe-publicidad-sin-tu-consentimiento-expreso | 25-jun-2025 | SECUNDARIA (opinión) |
| F14 | CMS Grau, "Promulgan Ley contra llamadas y mensajes SPAM" | https://cms.law/en/per/publication/promulgan-ley-contra-llamadas-y-mensajes-spam | may-2025 (la nota tiene una inconsistencia de fecha interna) | SECUNDARIA |
| F15 | Garrigues, "Perú: Congreso prohíbe primer contacto..." | https://www.garrigues.com/es_ES/noticia/peru-congreso-prohibe-primer-contacto-empresas-ofrecer-productos-o-servicios-consumidores | 7-may-2025 | SECUNDARIA |
| F16 | Lawbox, "Ley N.º 32323: el fin del telemarketing no autorizado..." | https://lawbox.pe/ley-n-o-32323-el-fin-del-telemarketing-no-autorizado-y-el-spam-telefonico-en-peru/ | 1-jul-2025 | SECUNDARIA |
| F17 | IusLatin, nota sobre entrada en vigencia del reglamento y art. 26 | https://iuslatin.pe/proteccion-de-datos-personales-entra-en-vigencia-nueva-regulacion-sobre-consentimiento-expreso-de-las-personas-para-recibir-llamadas/ | 31-mar-2025 | SECUNDARIA |
| F18 | Forbes Perú, "Indecopi dispuso sancionar a Interbank por realizar llamadas spam" | https://forbes.pe/negocios/2026-08-18/indecopi-dispuso-sancionar-a-interbank-por-realizar-llamadas-spam/ | 18-ago-2026 | SECUNDARIA |
| F19 | DPL News, sobre la RM 196-2026-MTC (proyecto de la norma de numeración, prepublicación) | https://dplnews.com/peru-disponen-publicacion-norma-numeracion-identificacion-llamadas-sms-spam/ | 17-abr-2026 | SECUNDARIA |
| F20 | Política de privacidad del repo | C:\Users\user\Documents\Jesús Millones\Claude\Agente Whatsapp\whatsapp-agentkit\docs\politica-privacidad.html | "Última actualización: 22 de julio de 2026" | DOCUMENTO PROPIO (leído completo) |

### 1.2 Lo que NO pude abrir o verificar (declarado expresamente)

- NO leí la Ley 32323 directamente en el diario oficial El Peruano ni en el sitio del Congreso (esas URL dieron 404 o no estaban disponibles). Leí una transcripción (F3) y la cotejé con F4.
- NO pude abrir la exposición de Indecopi ante el Congreso del 1-jul-2025 (URL del Congreso devolvió 404) ni la nota del Congreso con el articulado.
- NO abrí la página de Indecopi sobre el registro "Gracias… No insista". Un resultado de búsqueda atribuido a Indecopi indica que ese registro perdió efecto desde la modificación del art. 58 del Código en 2018; otra página privada (modelo.pe) lo presenta como operativo. No pude resolver la contradicción con fuente oficial. Ver 2.7.
- NO encontré ningún pronunciamiento de la ANPD (Autoridad Nacional de Protección de Datos Personales) posterior a mayo de 2025 que resuelva la tensión entre el art. 26 del reglamento y la Ley 32323. Esto no prueba que no exista: solo que no lo encontré.
- NO leí las "WhatsApp Business Solution Terms" (la página cargaba con JavaScript y no obtuve el texto) ni las condiciones específicas de Click-to-WhatsApp más allá de F11.
- NO abrí las resoluciones de Indecopi: las sanciones a Pacífico Seguros y BBVA solo las vi mencionadas en resultados de búsqueda.
- NO verifiqué qué países declaró la ANPD con "nivel adecuado de protección" para flujo transfronterizo (relevante para EE.UU.).
- NO leí el Decreto Legislativo 1723 (numeración y trazabilidad de llamadas y SMS); solo lo veo citado en los considerandos de F4.
- NO verifiqué si el DS 018-2026-MTC fija una fecha especial de entrada en vigencia; el texto leído solo habla de 180 días calendario "desde la entrada en vigencia" para que los operadores se adecúen.

---

## 2. Marco aplicable en Perú

### 2.1 Ley 32323 (modifica el art. 58 del Código de Protección y Defensa del Consumidor, Ley 29571)

Publicada en El Peruano el 9-may-2025 (F3, F5). Texto del literal e) del párrafo 58.1 según la transcripción (F3):

> "Emplear centros de llamada (call centers), sistemas de llamado telefónico, envío de mensajes de texto a celular o de mensajes electrónicos masivos para promover productos y servicios, así como prestar el servicio de telemercadeo a consumidor alguno, con la única excepción del envío de comunicación comercial o publicitaria a aquel consumidor que, por iniciativa propia, se contacte directamente con el proveedor y manifieste su consentimiento libre, previo, informado, expreso e inequívoco de ser contactado a través de un número telefónico, dirección electrónica o cualquier otro medio análogo de comunicación. Este consentimiento puede ser revocado, con efecto inmediato y sin expresión de causa, en cualquier momento y conforme a la normativa que rige la protección de datos personales. La vulneración a esta prohibición o a su revocatoria es considerada infracción muy grave."

Se incorpora además el párrafo 58.3 (el Estado establece reglas para el uso adecuado de mensajes y llamadas en redes de telecomunicaciones) y una disposición complementaria final que ordena al Ejecutivo emitir en 60 días la normativa de numeración especial. Ambos fragmentos aparecen citados en los considerandos del DS 018-2026-MTC (F4, oficial).

Qué dice Indecopi (oficial):
- "Las empresas solo pueden realizar llamadas con fines comerciales o publicitarios si el consumidor ha otorgado su consentimiento previo, expreso y por iniciativa propia" y ese consentimiento "pudo haber sido otorgado al momento de adquirir un bien o servicio" (F6, 22-may-2025).
- El incumplimiento es infracción muy grave, multa de hasta 450 UIT y medidas correctivas (F5, F6).
- La reglamentación de numeración "no condiciona el cumplimiento de la norma por parte de los proveedores" (F6): es decir, la prohibición y la excepción ya rigen desde mayo de 2025.
- La guía al consumidor (F7) describe como práctica prohibida, entre otras, "llamadas de agentes o asesores ofreciendo créditos rápidos, tarjetas de crédito o refinanciamientos sin que el consumidor las haya solicitado" y "llamadas de ejecutivos de ventas en horarios no laborales o fines de semana y pese a la petición del cliente de no seguir siendo contactado". También señala que son indebidas las comunicaciones "persistentes o impertinentes, es decir, en una cantidad no razonable de veces dentro de un periodo de tiempo o en horarios no oportunos", y que las empresas "deben respetar las peticiones del consumidor para que cesen estas comunicaciones".
- La misma guía (F7) ofrece como ejemplo de consentimiento válido entregar información personal "al solicitar más información sobre un producto o servicio... y aceptar que lo contacten" (observación: el ejemplo incluye "aceptar que lo contacten").

### 2.2 Reglamento de la Ley 29733 (DS 016-2024-JUS)

Publicado el 30-nov-2024; entra en vigencia a los 120 días calendario de su publicación (disposición complementaria final Primera, F1). Una fuente secundaria (F17) sitúa el inicio efectivo alrededor del 31-mar-2025. Contenido relevante leído en F1:

- Art. 2: el consentimiento válido es libre, previo, expreso e inequívoco e informado.
- Art. 5.1: es "expreso" si se exterioriza por una acción que demuestre aceptación concreta, directa y explícita; incluye "hacer clic" y medios digitales; art. 5.3: la sola expresión de voluntad no exime de los demás requisitos.
- Art. 6.1: contenido mínimo de la información al titular (identidad y domicilio del responsable, finalidades, destinatarios, banco de datos, carácter obligatorio o facultativo, transferencias nacionales e internacionales, existencia de decisiones automatizadas incluida la elaboración de perfiles, plazo de conservación, mecanismos para ejercer derechos).
- Art. 7: publicar una política de privacidad no exonera de obtener el consentimiento.
- Art. 9: la carga de la prueba del consentimiento recae siempre en el titular del banco de datos o responsable del tratamiento.
- Art. 10: revocación en cualquier momento, sin justificación; mecanismos "fácilmente accesibles e incondicionales, sencillos, rápidos y gratuitos"; adecuar los tratamientos a la revocatoria en un plazo diligente "que no puede ser mayor a diez (10) días".
- Art. 26 (publicidad y prospección comercial), resumen fiel del texto leído:
  - 26.1: el tratamiento para publicidad y prospección comercial de productos y servicios "es lícito cuando se obtiene el consentimiento de forma directa por parte del titular".
  - 26.2: es posible obtener el consentimiento mediante un primer contacto; si no se obtiene, no es lícito un nuevo contacto o tratamiento.
  - 26.4: se presume que la responsabilidad del tratamiento para publicidad y prospección es "de aquel en cuyo interés se realiza tal tratamiento, salvo prueba en contrario".
  - 26.5: el titular puede negarse, revocar u oponerse; el responsable debe dar un medio "sencillo y gratuito", atender dentro de máx. diez (10) días, y negarse "no debe tener mayor complejidad que la empleada para otorgar el consentimiento".
  - 26.6: las solicitudes presentadas ante un encargado deben llegar al responsable.
  - 26.7: la ANPD puede emitir disposiciones sobre el artículo.
- Art. 86.4: "Salvo que exista relación contractual previa que sustente dicho tratamiento", en publicidad/prospección (incluido perfilamiento) el titular puede ejercer oposición en cualquier momento.
- Arts. 69.3: rectificación, cancelación y oposición se responden en máx. 10 días.

### 2.3 Tensión entre el art. 26.2 del reglamento ("primer contacto") y la Ley 32323

- Indecopi (voz de su directora de fiscalización, según F12): la ley "deja sin efecto" el primer contacto del reglamento; "la empresa no me debe buscar para darle el consentimiento"; lo califica de derogación tácita. [SECUNDARIA, cita a funcionaria].
- Otras fuentes secundarias (F13, F14, F15, F16) coinciden en que la Ley 32323 no admite un primer contacto no solicitado, y F13 pide un pronunciamiento técnico de la ANPD para dar seguridad jurídica.
- Este caso NO es un "primer contacto" en frío: el cliente escribió primero. Pero el problema de fondo (¿ese escribir primero basta para que la empresa lo llame?) queda sin resolver por los textos leídos. Ver 3.

### 2.4 Qué cuenta como comunicación publicitaria o de prospección frente a seguimiento de quien pidió información

Lo que dicen los textos:
- El art. 58.1.e habla de "promover productos y servicios" y de "comunicación comercial o publicitaria". No define esos términos en el fragmento leído.
- El reglamento habla de "publicidad y prospección comercial de productos y servicios" (art. 26) sin una definición en el artículo.
- El MTC (F4, art. 3 e) define, solo para su norma de numeración, "información con fines comerciales y/o publicitarios" como toda comunicación por llamadas o mensajes de texto, hecha por el proveedor o por terceros que actúan por su cuenta, encargo o interés, que tenga por objeto o efecto, directo o indirecto, "promover, ofrecer, publicitar, posicionar, colocar o facilitar bienes, servicios... así como captar consumidores y generar o desarrollar una relación de consumo". Es una definición amplia que, de aplicarse por analogía, alcanzaría una llamada para concretar un financiamiento.
- Indecopi (F7) distingue las llamadas "solicitadas expresamente" de las no solicitadas, y da como ejemplo de consentimiento solicitar información y "aceptar que lo contacten".

Lo que NO queda claro (ninguna fuente leída lo resuelve):
1. Si la llamada de seguimiento a quien pidió información por WhatsApp es "comunicación comercial o publicitaria" (sujeta a la excepción con consentimiento) o es atención de una solicitud ya en curso (fuera del supuesto prohibido).
2. Si el primer mensaje del cliente es el "contacto por iniciativa propia" y, a la vez, "manifestación de consentimiento de ser contactado a través de un número telefónico". El texto exige que el consumidor manifieste consentimiento "de ser contactado a través de un número telefónico... o cualquier otro medio análogo": preguntar por un producto no dice, por sí mismo, "llámenme".
3. Si una llamada realizada manualmente por un asesor desde un celular es un "sistema de llamado telefónico" o "telemercadeo". La ley nombra expresamente "call centers" y "sistemas de llamado telefónico".
4. Durante cuánto tiempo sigue vigente la "iniciativa propia" del cliente (¿horas, días, semanas?) cuando se queda en silencio.
5. Si la relación previa (haber conversado con Gabi, haber dado datos) cambia el análisis: Indecopi menciona que el consentimiento pudo darse "al adquirir un bien o servicio" (F6); aquí NO hay compra, solo consulta.
6. Si es Cálidda o Gaso+/Maiek quien califica como "proveedor" para efectos del Código.
7. No encontré en los textos leídos una norma que fije horarios o un número máximo de intentos; solo el criterio de Indecopi de "cantidad no razonable" y "horarios no oportunos" (F7), que incluye mencionar fines de semana. Los límites del diseño (3 intentos, 8:00-19:00, lun-sáb) son una decisión propia, no una exigencia legal verificada.

### 2.5 Norma del MTC sobre numeración (DS 018-2026-MTC, 15-sep-2026) [OFICIAL-LEÍDO]

- Atribuye la serie no geográfica "500" "como rango exclusivo para originar llamadas y/o mensajes de texto que brinden información comercial y/o publicitaria" (art. 5.1). Formato 500 XXX XXX.
- Ámbito: "aplicable a los operadores, a nivel nacional" (art. 4). El operador destina la serie 500 como número de abonado "a los proveedores que requieran exclusivamente brindar información con fines comerciales y/o publicitarios, quedando prohibida la asignación de cualquier otra numeración para dichos fines" (art. 10.1).
- Plazo de adecuación: no mayor de 180 días calendario desde la entrada en vigencia, para que el operador se adecúe (Primera disposición complementaria final). Difusión a la ciudadanía en el trimestre siguiente.
- Fiscalización y sanciones del MTC recaen sobre el operador (arts. 13-14, y nueva infracción muy grave en el art. 258 del TUO del Reglamento General de la Ley de Telecomunicaciones). El MTC e Indecopi comparten facultades según los considerandos.
- Preguntas abiertas: si un asesor de Gaso+/Cálidda que llama a un cliente que lo solicitó debe usar numeración 500; si el diseño actual (celular normal del asesor) quedaría fuera del uso permitido una vez vencido el plazo; y desde qué fecha exacta corre el plazo de 180 días (el cálculo "a partir del 15-sep-2026" no está verificado en el texto leído).
- Un proyecto previo (RM 196-2026-MTC, 15-abr-2026) fue publicado para comentarios (F19, secundaria).

### 2.6 OSIPTEL

No encontré en las fuentes leídas una norma de OSIPTEL que regule directamente las llamadas comerciales de un proveedor de bienes o servicios. OSIPTEL aparece solo de forma indirecta (una resolución suya sobre causales de suspensión y baja se cita en los anexos del DS 018-2026-MTC). La obligación de numeración recae en las empresas operadoras. Pregunta al abogado si algún aspecto de OSIPTEL aplica.

### 2.7 Registro "Gracias… No insista"

Estado NO verificado con fuente oficial abierta. Un resultado de búsqueda atribuido a la propia web de Indecopi indica que perdió efecto tras la modificación del art. 58 del Código en septiembre de 2018 (ya no hace falta inscribirse para no recibir publicidad no autorizada). Una página de plantillas (modelo.pe, privada) lo describe como vigente, pero sin citar norma. Por prudencia, la pregunta 14 pide al abogado confirmar si hay algún registro de exclusión que deba consultarse antes de llamar.

### 2.8 Directivas recientes de la ANPD

No encontré directivas ni opiniones consultivas de la ANPD posteriores a mayo de 2025 sobre llamadas comerciales. Existe una Opinión Consultiva N° 01-2022-JUS/DGTAIPD sobre el alcance del "primer contacto" [NO ABIERTA; es anterior al reglamento vigente y a la Ley 32323]. La nota de 2018 (F8, oficial) muestra que la ANPD entonces consideraba admisible el primer contacto y reprochaba el "acoso" (no aceptar un no, no respetar franjas horarias, no tener sistema para rechazar); es histórica y está superada en el punto del primer contacto, pero sigue siendo ilustrativa del criterio de "no acoso".

---

## 3. ¿Cambia el análisis que el cliente haya escrito primero?

Lo que sí sostienen las fuentes:
- La ley contempla una excepción justamente para el consumidor que "por iniciativa propia" contacta al proveedor (F3). El cliente que escribe a Gabi por un anuncio o enlace parece cumplir ese primer elemento (la iniciativa). Esto es lectura mía; el texto no menciona WhatsApp ni anuncios.
- Indecopi dice que el usuario debe iniciar el contacto (llamar, ir al local, enviar un correo) y que la empresa "no me debe buscar para darle el consentimiento" (F12, secundaria).

Lo que NO queda claro:
- El segundo elemento (consentimiento específico "de ser contactado a través de un número telefónico") no se desprende automáticamente de haber hecho una consulta.
- En un anuncio de Click-to-WhatsApp o un enlace wa.me, el cliente abre el chat con un texto prellenado; no queda claro si ese acto equivale a aceptar una llamada telefónica posterior.
- Tampoco hay criterio sobre el silencio posterior: el silencio no es un consentimiento "expreso e inequívoco" (art. 5 del reglamento exige acción que demuestre aceptación concreta, directa y explícita).

Conclusión de trabajo (no jurídica): la lectura más prudente sería que la iniciativa del cliente es un elemento favorable, pero que la llamada debería apoyarse en una aceptación expresa de la llamada (por ejemplo, responder a la oferta de Gabi), no solo en el hecho de haber escrito primero.

---

## 4. Bases de legitimación posibles y cómo acreditarlas

Se comparan tres opciones. Ninguna está validada por un abogado.

| Base | Qué dicen los textos | Debilidades / dudas |
|---|---|---|
| Consentimiento (arts. 2, 5, 9 y 26.1 del reglamento; art. 58.1.e del Código) | Es la vía que el reglamento fija para publicidad y prospección y la que usa la excepción de la Ley 32323. El clic o el mensaje digital pueden ser medios válidos (art. 5.1). | Debe ser libre, previo, expreso, inequívoco e informado. Debe poder probarse; la carga es de quien trata los datos (art. 9). La oferta de Gabi como está redactada pide "a qué hora" en lugar de pedir un "sí" explícito (ver Anexo A). |
| Ejecución de relación contractual / precontractual por solicitud del titular | Ley 29733 art. 14.5: no se requiere consentimiento cuando los datos "sean necesarios para la ejecución de una relación contractual en la que el titular de datos personales sea parte". Reglamento art. 86.4 hace una salvedad para la oposición cuando "exista relación contractual previa". | El texto literal habla de "relación contractual", no de fase precontractual ni de simple consulta. No sé si la ANPD o los tribunales extienden esta base a "solicitud de información previa a contratar". Además, el art. 58.1.e del Código (norma de consumidor, con sanción propia de Indecopi) exige consentimiento aunque la base de datos personales fuera otra. Es decir, aun si la Ley 29733 no exigiera consentimiento, el Código podría exigirlo para la llamada. |
| Interés legítimo | Ley 29733 art. 14.9 menciona "intereses legítimos del titular de datos personales por parte del titular de datos personales o por el encargado" (redacción confusa en la copia leída). | No hay una base general de "interés legítimo del responsable" en el texto leído de la ley. No la considero una vía sólida; pregunta al abogado. |

Evidencia que convendría conservar (para cada lead que reciba una llamada), como propuesta técnica de buenas prácticas, no como exigencia verificada:
1. Origen del contacto: texto y capturas del anuncio (con fecha y versión) o del enlace/QR; identificador del anuncio y datos de referencia que entrega Meta en el webhook del primer mensaje (si están disponibles).
2. El primer mensaje del cliente, con marca de tiempo e identificador del mensaje (wamid).
3. El mensaje de oferta de Gabi (versión exacta del texto y fecha de envío).
4. La respuesta del cliente que acepta (o su ausencia), con marca de tiempo.
5. Registro de cada llamada: fecha, hora, número de intento, asesor, resultado.
6. Registro de cualquier rechazo (`no_llamar`) con fecha, hora, canal y frase exacta.
7. Versión de la política de privacidad vigente al momento y si el enlace fue entregado.
8. Plazo de conservación definido por el responsable (a decidir con el abogado).

---

## 5. Política de WhatsApp Business / Meta (lo que dicen las páginas oficiales)

Fuente principal: WhatsApp Business Messaging Policy, "Last updated: September 23, 2026" (F9), https://www.whatsapp.com/legal/business-policy.

- Sección 1, "Create a Quality Experience": solo se puede contactar a personas en WhatsApp si (a) entregaron su número móvil o nombre de usuario y (b) se recibió "opt-in permission from the recipient confirming that they wish to receive subsequent messages or calls from you" (opt-in que cubre mensajes o llamadas).
- Misma sección: el negocio es "solely responsible" por determinar el método de opt-in y por obtenerlo "in a manner that complies with laws applicable to your communications".
- Misma sección: se deben respetar todas las solicitudes, "either on or off WhatsApp", de bloquear, interrumpir o darse de baja, "including removing that person from your contacts list"; no "spam" ni "sorprender" a las personas.
- Sección "Best Practices for Opt-In": recomienda "Obtaining a separate opt-in to initiate a call to a user" y dar instrucciones claras para rechazar categorías de mensajes o llamadas y respetarlas.
- Sección 2: solo se pueden iniciar conversaciones con plantillas aprobadas (Message Templates); se puede responder sin plantilla dentro de la ventana de atención al cliente de 24 horas que se reinicia con cada mensaje del usuario. Consecuencia práctica a revisar: la oferta de Gabi enviada a alguien que lleva más de 24 horas en silencio requeriría una plantilla aprobada. Además, la automatización debe tener vías de escalamiento claras (agente humano en el chat, teléfono, etc.).
- Sección 3: se debe tener política de privacidad publicada y obtener los permisos legales; "Don't use any data obtained from us about a person you message within WhatsApp, other than the content of message threads, for any purpose other than as reasonably necessary to support messaging with that person." Esta frase es la que más importa para la pregunta de usar el número obtenido en WhatsApp para llamar por teléfono: no es evidente si "los datos que Meta nos entrega sobre la persona" incluye el número de teléfono con el que escribió (el propio cliente nos lo comunica al escribir) o si la restricción solo cubre datos adicionales de perfil. Es una duda de interpretación; no encontré una página de Meta que la resuelva.
- Sección 7, "Enforcement": Meta puede "limit or remove your access" si hay "significant amounts of negative feedback"; los usuarios pueden bloquear o reportar; los sistemas "may limit the amount of messages a business can send or calls a business can initiate"; operar un servicio que mensajea "at scale in an unauthorized manner" da derecho a limitar o quitar el acceso; en caso de cierre, Meta puede prohibir a la organización todo uso futuro. Hay vía de apelación (sección "Steps to Take if Your Account is Suspended").
- Sectores regulados: la política prohíbe, entre otros, préstamos de día de pago, adelantos de sueldo, préstamos entre particulares y cobranza de deuda. Financiar un gasodoméstico no encaja literalmente en esa lista, pero conviene que el abogado o Meta confirmen que no se clasifica en una vertical restringida.
- Getting opt-in (F10): el permiso debe indicar claramente que la persona se suscribe y el nombre del negocio; ejemplos de métodos: SMS, sitio web, llamada con flujo IVR, en persona o papel. La página no dice si un mensaje iniciado por el usuario o un anuncio Click-to-WhatsApp cuenta como opt-in válido. Fuentes de terceros (proveedores BSP como Infobip) afirman que sí lo cuentan [SECUNDARIA, no verificada con Meta].
- Click to WhatsApp (F11): la página técnica no trata consentimiento ni uso del número fuera de WhatsApp.
- Sobre "llamadas": la política habla de "calls" en el contexto del producto WhatsApp; no encontré texto que regule expresamente la llamada celular tradicional hecha al número de un usuario de WhatsApp. Lo más cercano es la regla de opt-in para "mensajes o llamadas" y la recomendación del opt-in separado.

Riesgo operativo: el antecedente de baneo en Whapi (campañas masivas) debe tenerse presente; en la API oficial de Meta la señal que más importa es el bloqueo y reporte por parte de los usuarios (sección 7).

---

## 6. Responsabilidades: preguntas, sin asumir respuestas

El reglamento (F1) distingue al titular del banco de datos o responsable del tratamiento, al encargado y al subcontratado:
- Art. 26.4: para publicidad y prospección, se presume responsable "aquel en cuyo interés se realiza tal tratamiento, salvo prueba en contrario".
- Art. 31-33: el encargado no puede transferir a terceros sin autorización; conservación máxima de 2 años desde el fin del último encargo salvo excepciones; el subcontratista asume las obligaciones del titular si usa los datos para otra finalidad o transfiere incumpliendo instrucciones. Art. 32.2: la subcontratación requiere autorización previa del responsable (o prevista en el contrato).
- Art. 17: las transferencias nacionales se formalizan con mecanismos que permitan demostrar que se comunicaron al receptor las condiciones del consentimiento.
- Arts. 18-21: flujo transfronterizo solo a países con nivel adecuado, o con garantías (por ejemplo cláusulas contractuales modelo); además "debe ponerse en conocimiento" de la autoridad y se inscribe en el Registro Nacional de Protección de Datos Personales (art. 21.2).
- Arts. 42-43 (y art. 34 de la Ley): los bancos de datos de administración privada se inscriben en el Registro Nacional; la omisión de inscribir o actualizar es infracción leve (art. 132.4) y grave si ya fue requerida (art. 133.13); no comunicar el flujo transfronterizo también es leve (art. 132.8).

Preguntas (todas abiertas):
1. ¿Quién es el titular del banco de datos de los leads de Gaso+: Cálidda, Gaso+/Maiek AI, o ambos con roles distintos? Hoy la titularidad "está por confirmar con Cálidda".
2. ¿Maiek AI actúa como encargado de Cálidda (con contrato de encargo) o como responsable propio o corresponsable? ¿Qué cambia respecto a las llamadas, que son un uso comercial en interés de Cálidda (venta de financiamiento) y quizá también de Maiek?
3. ¿Hay un contrato Cálidda-Maiek que autorice expresamente el uso de los datos del lead para llamadas telefónicas salientes? ¿Qué cláusulas mínimas debería tener (finalidad, subencargados, devolución o supresión, plazos, auditoría, atención de derechos, notificación de incidentes)?
4. ¿Los proveedores tecnológicos (Anthropic, Railway, Meta, Resend, Vercel) son encargados, subcontratados o responsables independientes? ¿Qué contratos o cláusulas modelo hacen falta con cada uno, y qué información debe darse al titular?
5. ¿Qué proveedores reciben datos personales del lead realmente? (Mapa a validar con el equipo técnico: Meta/WhatsApp por la mensajería; Anthropic por el contenido de mensajes que se envía al modelo; Railway por alojamiento y base de datos; Vercel por el panel; Resend por correos al equipo. Debe confirmarse qué datos van a cada uno.)
6. ¿El flujo a esos proveedores (en su mayoría fuera de Perú) requiere comunicación a la ANPD y registro del flujo transfronterizo? ¿Qué países tienen nivel adecuado declarado?
7. ¿Hay banco de datos inscrito en el Registro Nacional de Protección de Datos Personales que cubra estos leads y la finalidad de llamada? ¿A nombre de quién?

---

## 7. Derechos del titular: revocación inmediata ("no me llamen")

Lo que dicen los textos:
- Código del Consumidor (Ley 32323): el consentimiento se revoca "con efecto inmediato y sin expresión de causa, en cualquier momento"; no atender la revocación también es infracción muy grave (F3, F14).
- Reglamento (F1): revocación sin justificación; mecanismos sencillos, rápidos y gratuitos (art. 10.4); adecuar tratamientos en un plazo diligente que no exceda 10 días (art. 10.2); para publicidad y prospección, solicitud atendida dentro de máx. 10 días y con complejidad no mayor que la de otorgar el consentimiento (art. 26.5); oposición, rectificación y cancelación: 10 días (art. 69.3); acceso: 20 días (art. 69.2); información: 8 días (art. 69.1). Las solicitudes dirigidas al encargado deben trasladarse al responsable (art. 26.6; art. 66.4 fija un plazo de 3 días para trasladar).
- Indecopi (F7): la revocación puede hacerse por el mismo medio por el que se dio el consentimiento y la empresa debe responder en máx. 10 días.
- WhatsApp (F9): respetar los rechazos "on or off WhatsApp" y quitar a la persona de los contactos.

Cómo se reflejaría técnicamente (propuesta de diseño, a validar):
- Campo `no_llamar` (hoy NO existe en el repo: la búsqueda en whatsapp-agentkit no encontró coincidencias) con fecha, hora, canal y frase exacta de quien rechazó.
- Verificación del campo inmediatamente antes de cada intento de llamada (no solo al armar la cola).
- Aplicación del bloqueo por número normalizado (no solo por lead), para que otro lead, producto o campaña del mismo número no vuelva a activar llamadas.
- Aviso al asesor si el cliente dice "no me llamen" por cualquier vía (WhatsApp, durante la llamada, correo ARCO).
- Respuesta de confirmación al cliente (por ejemplo, "Listo, no te llamaremos").
- Preguntar al abogado el alcance: ¿el "no me llamen" solo bloquea llamadas, o todo contacto comercial (incluidos mensajes de WhatsApp de seguimiento)?

---

## 8. CUESTIONARIO PARA EL ABOGADO (15 preguntas, para responder sí / no / condiciones)

Las preguntas 1, 2, 5, 7 y 9 son las más críticas (ver al final).

Consentimiento y alcance de la ley
1. Un cliente escribe primero a Gabi por WhatsApp (anuncio Click-to-WhatsApp, enlace wa.me/wa.link, QR o mensaje directo) pidiendo información sobre financiamiento de un gasodoméstico. ¿Ese solo hecho constituye "iniciativa propia" y "consentimiento libre, previo, informado, expreso e inequívoco de ser contactado a través de un número telefónico" conforme al art. 58.1.e del Código (Ley 32323)? Si la respuesta es "no" o "depende", ¿qué elemento adicional mínimo se necesita?
2. Si Gabi ofrece la llamada y el cliente acepta con un mensaje del tipo "sí, llámenme" o indicando una hora, ¿eso basta como consentimiento específico para la llamada? ¿Y si el cliente no responde (silencio)? ¿Podemos llamar a quien NO contestó la oferta?
3. ¿La propia oferta de Gabi (un mensaje de WhatsApp ofreciendo una llamada tras el silencio del cliente) es una "comunicación comercial o publicitaria" que ya requiere consentimiento, o es seguimiento de la solicitud en curso? ¿Hasta cuándo (horas, días, semanas) se considera vigente la solicitud original del cliente para esta oferta?
4. ¿Una llamada hecha manualmente por un asesor desde un teléfono celular o fijo, a un cliente que lo pidió, califica como "call center", "sistema de llamado telefónico" o "servicio de telemercadeo" para efectos del art. 58.1.e? ¿Cambia la respuesta si se usa un marcador automático, un botón click-to-call, un CRM que dispara las llamadas o más de cierto número de asesores?

Base legal de protección de datos
5. Con la Ley 32323, ¿sigue vigente el "primer contacto" del art. 26.2 del DS 016-2024-JUS? ¿La ANPD o Indecopi emitieron algún criterio posterior (2025-2026) sobre su aplicación o sobre la coexistencia con el art. 58.1.e?
6. ¿Puede apoyarse esta llamada en el art. 14.5 de la Ley 29733 (relación contractual) como excepción al consentimiento, entendiendo la solicitud del cliente como etapa precontractual? ¿O para fines de publicidad y prospección el art. 26.1 del reglamento exige consentimiento en todos los casos? ¿Cambia algo que sea una llamada de seguimiento y no una oferta de otros productos?

Responsable, contratos y registros
7. ¿Quién debe ser considerado responsable del tratamiento y "proveedor" frente al consumidor: Cálidda, Maiek AI/Gaso+, o ambos? ¿Qué contrato (encargo, corresponsabilidad u otro) necesitamos con Cálidda y con cada proveedor tecnológico (Anthropic, Railway, Meta, Resend, Vercel), y qué cláusulas mínimas deben incluir?
8. ¿Debe comunicarse y registrarse ante la ANPD el flujo transfronterizo a esos proveedores y debe inscribirse el banco de datos (a nombre de quién), incluyendo la finalidad de llamadas telefónicas? ¿Basta con la política de privacidad o se requiere además consentimiento específico para la transferencia?

Numeración (MTC)
9. Con el DS 018-2026-MTC (serie 500; 180 días de adecuación), ¿las llamadas salientes de asesores a clientes que las solicitaron deben originarse desde numeración 500? ¿A partir de qué fecha exacta? ¿Se aplica a un "proveedor" que no es operador o solo a los operadores? ¿Qué hacemos con los celulares personales de los asesores?

Revocación, horarios y frecuencia
10. ¿El "no me llamen" escrito por WhatsApp en texto libre (detectado por Gabi o por un asesor) es una revocación válida? ¿Qué plazo aplica a nuestro caso: el "efecto inmediato" del Código o los 10 días del reglamento? ¿La revocación debe extenderse a todo contacto comercial por cualquier canal y a cualquier otro lead que comparta el mismo número?
11. ¿Los límites de nuestro diseño (máx. 3 intentos, 8:00-19:00 de lunes a sábado) son razonables frente al criterio de Indecopi sobre llamadas "persistentes o impertinentes" y "horarios no oportunos" (la guía menciona fines de semana)? ¿Recomienda excluir sábados, reducir intentos, fijar intervalos mínimos entre llamadas o un plazo máximo desde el consentimiento?

Información, privacidad y evidencia
12. ¿La política de privacidad actual (22-jul-2026) y la nota breve propuesta (Anexo B) cumplen el deber de informar (art. 18 de la Ley; art. 6 del reglamento), incluyendo finalidad de llamada, transferencias internacionales, perfilamiento o decisiones automatizadas (Gabi califica el interés del lead), plazo de conservación y mecanismos ARCO? ¿Debe enlazarse en el primer mensaje de Gabi?
13. ¿La evidencia descrita en la sección 4 (captura del anuncio, mensaje del cliente, oferta de Gabi, respuesta, registro de llamadas y de rechazos) es suficiente para acreditar el consentimiento ante Indecopi y la ANPD? ¿Cuánto tiempo debemos conservarla y se puede conservar si el cliente revoca?

Otros
14. ¿Existe algún registro de exclusión (por ejemplo, el antiguo "Gracias… No insista") u otro mecanismo oficial que debamos consultar antes de llamar? ¿Y rigen para estas llamadas reglas adicionales por tratarse de financiamiento (por ejemplo, de la SBS u otras normas de transparencia de condiciones) o por el uso de IA para generar la oferta?
15. Si los asesores graban las llamadas, o si en el futuro se transcriben con IA, ¿qué deben informar y de qué forma, y se necesita consentimiento adicional?

### Las 5 preguntas más críticas
- Pregunta 1 (¿basta haber escrito primero?) y pregunta 2 (¿basta la aceptación expresa a la oferta de Gabi, y qué pasa con el silencio?): definen si el estado "Para llamar" puede aplicarse a quien guarda silencio.
- Pregunta 5 (vigencia del primer contacto y base legal): define si hay alguna vía distinta del consentimiento.
- Pregunta 7 (quién es el responsable y qué contrato hace falta): condiciona todo lo demás y sigue sin confirmarse con Cálidda.
- Pregunta 9 (serie 500 del MTC): podría obligar a cambiar el medio de llamada, con plazo ya corriendo.

---

## 9. Qué haríamos por defecto si el abogado no puede responder pronto

Opciones conservadoras, de menor a mayor impacto en el negocio. Son medidas de prudencia operativa, no una afirmación de que con ellas se cumpla la ley.

1. Llamar SOLO a quien acepte expresamente. Mantener el estado "Para llamar" únicamente para clientes que respondan con aceptación clara a la oferta de Gabi (por ejemplo "sí" o una hora). Los clientes que quedan en silencio NO pasan a "Para llamar": se quedan en seguimiento por WhatsApp dentro de la ventana de 24 horas y luego se cierran sin llamada.
2. Oferta con consentimiento explícito y rechazo fácil. Usar la variante B del Anexo A (pide un "sí" explícito y ofrece "no" o "no me llamen" con la misma facilidad). Una sola oferta por lead; si no responde, no insistir.
3. Apagado por defecto. Dejar la función de llamadas detrás de un interruptor (feature flag) desactivado hasta tener respuesta, o activarlo solo para leads con aceptación registrada.
4. Registro de evidencia desde el primer día. Guardar, por lead: origen (anuncio o enlace), primer mensaje, oferta enviada (versión), respuesta, aceptación, cada intento de llamada y resultado, y cualquier rechazo (sección 4).
5. `no_llamar` inmediato y a prueba de carreras. Crear el campo; revisarlo justo antes de cada llamada; aplicarlo por número normalizado; detectar frases como "no me llamen", "no quiero llamadas", "deja de escribirme" y marcar sin esperar; ante duda, no llamar.
6. Límites más estrictos hasta que haya criterio: máximo 2 intentos, separados al menos un día, de lunes a viernes, 9:00-18:00 (sin sábados mientras no se responda la pregunta 11), solo dentro de un plazo corto desde la aceptación.
7. Contenido acotado de la llamada. El asesor se identifica (nombre, Cálidda/Gaso+), recuerda que el cliente pidió la llamada, atiende solo el producto que consultó, pregunta si desea seguir y anota si no quiere más llamadas. Sin ofrecer otros productos.
8. Sin marcadores automáticos ni campañas masivas. Las llamadas las hace una persona, una por una, con el número corporativo identificable; preparar el cambio a numeración 500 cuando el abogado lo confirme.
9. No grabar llamadas ni analizarlas con IA hasta resolver la pregunta 15.
10. Completar la política de privacidad: correo ARCO real, razón social y domicilio del responsable (a confirmar con Cálidda), finalidad de "llamada telefónica a solicitud tuya", proveedores y países, plazo de conservación y mecanismo de rechazo; publicar y enlazar en el primer mensaje.
11. Cuidar la señal con Meta. Monitorear bloqueos y reportes tras activar la oferta de llamada; si suben, pausar. Confirmar si la oferta fuera de las 24 horas debe ir como plantilla aprobada.
12. Confirmar con Cálidda por escrito: quién es el responsable del banco de datos, si autoriza las llamadas salientes y quién atiende los derechos ARCO.

---

## 10. Sanciones y riesgos señalados en las fuentes (dato informativo; secundario)

La advertencia principal es que los montos no determinan lo que debe hacerse; sirven solo para dimensionar el riesgo regulatorio.

| Régimen | Rango / dato | Fuente |
|---|---|---|
| Código del Consumidor (art. 58.1.e, Ley 32323): infracción "muy grave" | Hasta 450 UIT (Indecopi menciona S/ 2 407 500 a la fecha de su nota) y medidas correctivas a favor de los consumidores | F5, F6 (oficiales) |
| Ley 29733, art. 39 (ANPD) | Leves: 0,5 a 5 UIT; graves: más de 5 hasta 50 UIT; muy graves: más de 50 hasta 100 UIT. Tope: 10 % de los ingresos brutos anuales del año anterior | F2 (oficial) |
| Reglamento, infracciones relevantes | Grave: tratar datos sin el consentimiento libre, expreso, inequívoco, previo e informado cuando sea necesario (art. 133.3); grave: no atender o impedir el ejercicio de derechos (art. 133.1); grave: usar datos para finalidades distintas a las que motivaron su recopilación (133.7); leve: atender derechos fuera de plazo (132.7) | F1 (oficial) |
| Caso reciente | Interbank: 74,88 UIT (S/ 411 840) en primera instancia por no acreditar consentimiento; apelable | F18 (secundaria) |
| Otros casos mencionados en búsquedas | Pacífico Seguros (21,49 UIT, confirmada en segunda instancia) y BBVA (279,50 UIT, primera instancia) | NO ABIERTAS, no verificadas |
| Numeración del MTC | Sanciones a los operadores según la ley de telecomunicaciones y el reglamento de fiscalización del MTC; no se leyó un monto específico | F4 (oficial) |
| Plataforma | Meta puede limitar o cerrar el acceso a WhatsApp for Business y prohibir usos futuros | F9 (oficial de Meta) |

Notas: (1) Indecopi indica que usa transcripción de audios con inteligencia artificial para fiscalizar (F5, F12); (2) la carga de probar el consentimiento recae en la empresa (art. 9 del reglamento y el razonamiento del caso Interbank); (3) los montos en soles dependen del valor de la UIT vigente, que no verifiqué.

---

## 11. La política de privacidad del repo: qué dice y qué no dice

Archivo leído completo: C:\Users\user\Documents\Jesús Millones\Claude\Agente Whatsapp\whatsapp-agentkit\docs\politica-privacidad.html. Título: "Política de Privacidad — Gabi (Asistente virtual de Cálidda vía WhatsApp)". Última actualización: 22 de julio de 2026. Es la única política que encontré; no hay ninguna en el repo maiek-frontend (búsqueda sin resultados) y no encontré referencias a este archivo en el código Python/YAML del repo (por lo que no puedo afirmar dónde está publicada ni si Gabi la enlaza).

Qué dice:
- Sección 1: el servicio "es operado por Cálidda Gas Natural del Perú ... a través de Gabi", un asistente virtual con IA, "dentro de la plataforma Gaso+".
- Sección 2: recopila teléfono de WhatsApp, nombre (si lo da), contenido de mensajes, "información sobre tu interés comercial (ej. producto consultado, campaña de origen)" y archivos.
- Sección 3 (finalidades): responder consultas; "calificar tu interés y, si corresponde, conectarte con un asesor humano de Cálidda"; "ofrecerte información sobre productos, precios y promociones vigentes"; mejorar el servicio. Dice que no se usa la información para fines distintos ni se vende a terceros.
- Sección 4: comparte con Meta/WhatsApp, Anthropic ("encargados de tratamiento") y "proveedores de infraestructura tecnológica".
- Sección 5: conserva el historial "mientras exista una relación comercial activa o mientras sea necesario", sin plazo concreto.
- Sección 6: derechos ARCO conforme a la Ley 29733, a ejercer escribiendo a "[correo de contacto de Cálidda]".
- Sección 9: contacto, con el mismo marcador "[correo de contacto de Cálidda]".

Qué NO dice o deja pendiente:
1. No menciona llamadas telefónicas. El único vínculo es "conectarte con un asesor humano", que no dice que el contacto será una llamada celular al número de WhatsApp.
2. No distingue la finalidad publicitaria/comercial de la de atención, ni ofrece un mecanismo específico de rechazo de llamadas o de publicidad (el art. 26.5 del reglamento lo exige para publicidad y prospección). Menciona "promociones", lo que apunta a una finalidad comercial.
3. Afirma que lo opera Cálidda, mientras que la titularidad del banco de datos y el rol de Maiek/Gaso+ están por confirmar. Si Maiek es responsable o corresponsable, la política no lo refleja.
4. Los dos correos están sin completar: el titular no tiene hoy un canal real publicado para ejercer derechos.
5. No incluye domicilio o dirección del responsable (art. 6.1.1 del reglamento) ni identificación del banco de datos y su inscripción (art. 6.1.4).
6. No nombra a Railway, Vercel ni Resend (solo habla de "proveedores de infraestructura tecnológica") ni informa de transferencias internacionales (art. 6.1.7).
7. No informa sobre decisiones automatizadas o perfilamiento (art. 6.1.8), aunque "calificar tu interés" podría considerarse perfilamiento (pregunta al abogado).
8. No fija plazo de conservación (art. 6.1.9) ni el plazo de 10 días para atender derechos.
9. No menciona el origen del dato en anuncios de Meta (aunque cita "campaña de origen") ni el uso de datos de referencia del anuncio.
10. Recordatorio normativo: la política no sustituye el consentimiento (art. 7 del reglamento).

---

## Anexo A. Texto propuesto de la oferta de Gabi (para que lo evalúe el abogado)

### A.1 Texto del diseño actual (literal, sin modificar)

> Hola {nombre}, soy Gabi. Vi que quedó pendiente tu consulta de {producto}. Si te parece, un asesor puede llamarte hoy para resolver tus dudas y ayudarte con el financiamiento. ¿A qué hora te viene mejor? Si prefieres que no te llamemos, avísame y no lo hacemos.

Observaciones para el abogado sobre A.1 (mías, no jurídicas):
- Está formulado como oferta con opción de rechazo ("opt-out"). Si el cliente no responde, no hay aceptación. Si responde con una hora, parece aceptación; si responde otra cosa (por ejemplo "después te escribo"), no está claro.
- No identifica al responsable (Cálidda / Maiek), ni dice que la llamada será al número de WhatsApp, ni cuántos intentos ni en qué horario.
- No enlaza la política de privacidad.
- "hoy" sugiere inmediatez que quizá no sea compatible con la plantilla o la ventana de 24 horas de Meta.
- "¿A qué hora te viene mejor?" asume el sí. Una alternativa es pedir primero la aceptación.

### A.2 Variante B (más conservadora, propuesta para evaluación; no sustituye la A.1 hasta decisión)

> Hola {nombre}, soy Gabi, asistente virtual de Cálidda en Gaso+. Quedó pendiente tu consulta de {producto}. ¿Quieres que un asesor te llame por teléfono a este mismo número para ayudarte con el financiamiento? Responde "SÍ" y dime en qué horario prefieres (entre 8:00 y 19:00, de lunes a sábado); haremos hasta 3 intentos de llamada. Si no quieres llamadas, responde "NO" o "no me llamen" y no te llamaremos. Más información sobre el uso de tus datos: {enlace a la política de privacidad}.

Notas de la variante B:
- Pide un "sí" explícito y deja claro el medio (teléfono), el número, el horario y los intentos.
- El rechazo es igual de fácil que la aceptación (art. 26.5 del reglamento).
- Habría que ajustar "Cálidda en Gaso+" y la mención del responsable una vez confirmada la titularidad.
- Si el mensaje se envía fuera de la ventana de 24 horas, requeriría plantilla aprobada por Meta (F9, sección 2); el texto de la plantilla tendría que revisarse con Meta.
- Este texto no se enviaría hasta que el abogado lo apruebe.

### A.3 Respuestas de Gabi ante el rechazo o aceptación (borrador)

- Rechazo: "Listo, {nombre}. No te llamaremos. Si más adelante quieres retomar tu consulta, escríbeme y con gusto te ayudo por aquí."
- Aceptación: "Perfecto, {nombre}. Un asesor te llamará a este número en el horario que indicaste. Si cambias de opinión, escríbeme 'no me llamen' y no lo hacemos."

---

## Anexo B. Nota de privacidad breve propuesta (para el abogado)

Texto base (los campos entre corchetes están pendientes de confirmación con Cálidda y no deben inventarse):

> Aviso de privacidad. Tus datos (número de teléfono, nombre y producto de interés) son tratados por [razón social del responsable, RUC y domicilio] para atender tu consulta y, solo si tú lo aceptas, para que un asesor te llame por teléfono a este número (hasta 3 intentos, de 8:00 a 19:00 de lunes a sábado, hora de Lima). Para operar este servicio utilizamos proveedores tecnológicos que pueden ubicarse fuera del Perú: [lista de proveedores y países, por confirmar]. Conservamos tus datos por [plazo, por definir]. Puedes decir "no me llamen" en cualquier momento por este chat y dejaremos de llamarte de inmediato; también puedes ejercer tus derechos de acceso, rectificación, cancelación y oposición escribiendo a [correo ARCO, por completar]. Política completa: {enlace}.

Qué habría que decidir con el abogado antes de usarlo:
- Responsable y domicilio exactos.
- Si se informa de perfilamiento o decisiones automatizadas ("Gabi califica tu interés").
- Si incluye la inscripción del banco de datos.
- Si debe incluirse la mención de grabación de llamadas (hoy no se graban).
- Dónde se muestra (primer mensaje de Gabi, enlace en la oferta, o ambos).

---

## Anexo C. Mapa de qué sí y qué no se verificó

| Tema | Verificado con fuente oficial leída | Solo secundaria o no verificado |
|---|---|---|
| Texto del art. 58.1.e y 58.3 (Ley 32323) | Parcial: transcripción de LP Derecho cotejada con citas en el DS 018-2026-MTC | Texto del diario oficial no abierto |
| Art. 26 y 9, 10, 6 del reglamento | Sí (F1) | Fecha exacta de inicio de vigencia (solo "120 días calendario") |
| Derogación tácita del "primer contacto" | No: es opinión atribuida a Indecopi (F12) y comentaristas (F13-F16) | Falta pronunciamiento oficial de la ANPD (no encontrado) |
| Multa hasta 450 UIT | Sí (F5, F6) | Valor en soles según UIT vigente |
| Multas Ley 29733 | Sí (F2) | Posibles modificaciones posteriores a la copia leída |
| Serie 500 y plazo de 180 días | Sí (F4) | Fecha de entrada en vigencia, aplicación a asesores individuales |
| Política WhatsApp Business | Sí (F9, actualización 23-sep-2026) | Condiciones de la Business Solution; condiciones específicas de Click-to-WhatsApp; interpretación de "datos obtenidos de nosotros" respecto del número de teléfono |
| Registro "Gracias… No insista" | No | Contradicción entre fuentes; página oficial no abierta |
| Horarios y número de intentos legales | No hay norma numérica leída | Solo el criterio general de Indecopi (F7) |
| Sanciones concretas a Pacífico, BBVA | No abiertas | Solo menciones en búsquedas |
