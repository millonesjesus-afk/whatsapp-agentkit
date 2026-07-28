# Maiek AI — Security Architecture

**Versión 1.0 · Estado: Approved**

| | |
|---|---|
| Documento | Security Architecture |
| Proyecto | Maiek AI |
| Versión | 1.0 |
| Estado | **Approved** |
| Fecha de creación | 2026-07-28 |
| Autor | Claude, a pedido de Jesús Millones |
| Fecha de aprobación | 2026-07-28 |
| Última actualización | 2026-07-28 |

## Dependencias

- `MAIEK_AI_SYSTEM_ARCHITECTURE.md` (MSA) Capítulo 11 (Architectural Constraints), Capítulo 13 (Seguridad — alto nivel).
- `MAIEK_AI_SECURITY_CURRENT_STATE_ASSESSMENT.md` (CSA-Security) — diagnóstico, Threat Landscape y Trust Boundaries de los que este documento parte directamente.
- `MAIEK_AI_DATA_ARCHITECTURE.md` — `RegistroAuditoria`, `negocio_id` (Multi-Tenant Fase 3) — **decisiones heredadas, no redefinidas acá**.
- `MAIEK_AI_BACKEND_ARCHITECTURE.md` — capas y servicios de dominio, patrón de autorización ya implementado en el panel.
- `MAIEK_AI_API_ARCHITECTURE.md` — brechas ya derivadas explícitamente hacia Security Architecture: emisión/rotación de API keys, rate limiting, restricción de `/docs` y `/openapi.json` — **este documento las resuelve, no las redefine**.
- `MAIEK_AI_AI_ARCHITECTURE.md` — brechas ya derivadas explícitamente hacia Security Architecture: emisión/rotación de credenciales del proveedor de IA, rate limiting sobre la llamada de IA, gate de aprobación para exponer herramientas al modelo — **este documento las resuelve, no las redefine**.
- `MAIEK_AI_ARCHITECTURE_DOCUMENT_STANDARD.md` (ADS) v1.3.

## Consumido por

Frontend Architecture, DevOps Architecture, Operations Architecture (futuros) — en particular, la rotación calendarizada de credenciales y el escaneo de vulnerabilidades quedan como brechas explícitas hacia DevOps Architecture (sección "Brechas conocidas").

## Control de versiones

| Versión | Fecha | Autor | Descripción |
|---|---|---|---|
| 1.0 (borrador) | 2026-07-28 | Claude | Primera versión — arquitectura objetivo de Security, construida sobre el CSA-Security aprobado (Threat Landscape y Trust Boundaries como insumo directo). Decide explícitamente las dos observaciones registradas en el CSA: separa protección de PII de política de retención, y fija la decisión de no cifrar campos de `Lead`/`Mensaje` por ahora (en vez de dejarla abierta). Pendiente de revisión y aprobación. |
| 1.0 | 2026-07-28 | Claude | Aprobado sin reapertura del contenido. El usuario registró 2 mejoras futuras no bloqueantes, a incorporar en una versión posterior: (1) agregar una sección breve de **Security Principles** (Defense in Depth, Least Privilege, Secure by Default, Fail Secure, Auditability) como fundamento conceptual explícito del resto de las decisiones del documento; (2) desacoplar las referencias específicas a Railway (hoy presentes en Architectural Constraints y en las Brechas conocidas) para mantener la arquitectura lo más independiente posible de la plataforma de despliegue concreta. |

## Alcance y regla de no-duplicación

Define **cómo debe protegerse** el sistema frente a los actores ya identificados en el Threat Landscape del CSA-Security, y qué debe cumplirse en cada frontera ya mapeada en Trust Boundaries. **No redefine** el modelo de datos de `RegistroAuditoria`/`negocio_id` (Data Architecture), ni el protocolo de confianza o la delimitación estructural del AI Engine (AI Architecture), ni el contrato interno/externo de la API (API Architecture) — resuelve las brechas que esos documentos ya le dejaron explícitamente asignadas, y cita el resto sin copiarlo (ADS §10).

---

## 1. Identidad, autenticación y autorización objetivo

Se preserva el patrón ya correcto (bcrypt + sesión firmada + `Depends(_usuario_actual)` consistente) como decisión Activa. Se agregan tres controles nuevos, todos mitigación directa de riesgos de severidad Alta o brechas ya señaladas en el CSA:

- **Límite de intentos de login**: tras un número de intentos fallidos consecutivos para un mismo usuario, la cuenta queda temporalmente bloqueada — mitiga la fuerza bruta identificada como riesgo Alta.
- **Expiración de sesión explícita**: se fija un tiempo de vida máximo de la cookie de sesión (hoy implícito en el default de Starlette).
- **Ruta formal de alta de usuarios en el panel**, protegida por rol `admin` — reemplaza el único camino actual (script directo a la base de datos).

MFA queda deliberadamente fuera de esta versión — se declara como brecha abierta (sección "Brechas conocidas"), no como decisión, porque no hay evidencia hoy de que el volumen o la sensibilidad del panel lo justifiquen (Evidence over Opinion).

## 2. Gestión de secretos y credenciales objetivo

Se preserva el patrón ya correcto: la mayoría de credenciales solo en variables de entorno, con la excepción deliberada de las credenciales de canal (cifradas con Fernet) — decisión Activa. Se fija el principio de que **toda credencial del proyecto debe poder rotarse sin downtime** — este documento fija el principio; la frecuencia operativa y el mecanismo de ejecución quedan como brecha hacia DevOps/Operations Architecture (no son decisiones de seguridad, son decisiones operativas).

## 3. Seguridad de APIs y Webhooks objetivo

**Se elimina el fail-open de la verificación de firma del webhook** — si ningún canal activo tiene `app_secret` configurado, la solicitud debe **rechazarse**, nunca aceptarse por default. Esta es la decisión de mayor prioridad de todo el documento (P1 del CSA).

**Rate limiting en `/login` y `/webhook`**, como mínimo — implementa directamente la brecha ya declarada tanto en API Architecture como en AI Architecture (que pedían rate limiting sobre la API externa y sobre la llamada de IA respectivamente); acá se resuelve en el punto de entrada común a ambas, antes de que el tráfico llegue a esas capas.

**Token CSRF explícito** en todo formulario de estado del panel — cierra la dependencia implícita en el comportamiento por defecto de `SameSite`.

Cuando la API externa versionada (`/api/v1/...`, ya diseñada en API Architecture) se implemente, hereda de este documento: las API keys se emiten con expiración y se rotan sin interrumpir al consumidor (mismo principio de la sección 2); `/docs` y `/openapi.json` permanecen restringidos hasta una decisión explícita de publicarlos — ninguna de estas dos decisiones se redefine acá, solo se confirma que Security Architecture ya las resolvió cuando API Architecture las declaró como brecha.

## 4. Seguridad del AI Engine objetivo

Se hereda, sin redefinir, la delimitación estructural entre contexto de confianza y mensaje del cliente ya decidida en AI Architecture. Se formaliza acá, desde el lado de Security, el gate que AI Architecture ya se auto-impuso: **cualquier exposición futura de tool-calling real al modelo requiere aprobación explícita de Security Architecture antes de implementarse** — no es una decisión nueva, es la contraparte de seguridad de una decisión que AI Architecture ya tomó sobre sí misma.

Sobre `ANTHROPIC_API_KEY` sin scopes granulares: se declara como Architectural Constraint (hecho del proveedor, no decisión de este proyecto) — Anthropic no ofrece hoy API keys con permisos acotados por función a nivel público, así que no hay una decisión de seguridad pendiente ahí, solo una limitación externa a documentar.

## 5. Protección de datos y privacidad objetivo

Se separan, como pidió el usuario, dos decisiones que el CSA dejaba juntas en un mismo ítem:

**Protección de PII (confidencialidad):** se decide **no** cifrar los campos de `Lead`/`Mensaje` a nivel de aplicación por ahora. Justificación: el cifrado de campo rompe la búsqueda y el filtrado que el panel ya usa extensivamente sobre esos mismos campos (tabla de leads, búsqueda por nombre/teléfono), y el control de acceso ya existente (autenticación + autorización por rol, sección 1) es la mitigación primaria hoy. Es una decisión **Activa**, no una brecha — con un criterio de revisión explícito: si aparece un requisito regulatorio concreto, un incidente real, o un tercero que necesite acceso a la base de datos sin pasar por la aplicación.

**Política de retención (minimización/disponibilidad):** queda como **brecha abierta**, con dueño fuera de este documento — el plazo y el alcance de qué se purga y cuándo es una decisión de producto/negocio, no arquitectónica. Este documento solo deja establecido el **principio**: la plataforma debe poder purgar datos de un lead o conversación cuando esa política exista, sin que el modelo de datos actual lo impida.

## 6. Multi-Tenant y aislamiento objetivo

Se hereda, sin redefinir, `negocio_id` como mecanismo de Data Architecture Fase 3. Este documento fija el **principio de seguridad** que debe respetarse cuando se implemente: toda consulta a datos de negocio debe filtrar por `negocio_id`, y ningún rol de "visión total" (hoy `admin`/`supervisor`) debe poder cruzar negocios distintos sin una decisión explícita de producto que lo autorice. No se diseña el mecanismo técnico — eso pertenece a Data Architecture.

## 7. Auditoría y trazabilidad objetivo

Se hereda `RegistroAuditoria` (Data Architecture) sin redefinir su modelo de datos. Este documento especifica qué eventos de seguridad debe registrar, como mínimo: login fallido, cambio de rol de un usuario, creación o cambio de una credencial de canal, y acceso denegado por autorización (403 de `_verificar_acceso_lead` o equivalente). Esta lista es el contenido de seguridad que `RegistroAuditoria` debe soportar — no una tabla nueva.

## 8. Dependencias externas y cadena de confianza objetivo

El Threat Landscape y los Trust Boundaries del CSA-Security quedan adoptados como el mapa formal de referencia de este documento — cualquier superficie nueva (ej. la API externa cuando se implemente) se agrega a ese mismo mapa, no se crea uno paralelo.

Se fija Subresource Integrity (`integrity`/`crossorigin`) en el CDN de Bootstrap/iconos — bajo costo, sin justificación de etapa para omitirlo. Fijar límites superiores de versión en `requirements.txt` y el escaneo de vulnerabilidades quedan como brecha hacia DevOps Architecture (son decisiones de proceso de CI, no de arquitectura de seguridad en sí).

## 9. Riesgos priorizados — estado tras este documento

De los 3 riesgos de severidad Alta identificados en el CSA (fuerza bruta en login, fail-open del webhook, ausencia de rate limiting), los 3 quedan resueltos como Decisiones locales de este documento (secciones 1 y 3). De los 4 de severidad Media, 2 quedan resueltos acá (CSRF, alta formal de usuarios) y 2 quedan explícitamente decididos y no resueltos (PII sin cifrado de campo — decisión Activa justificada en la sección 5; rotación de credenciales — principio fijado, ejecución delegada a DevOps).

## 10. Preparación para los siguientes documentos

Frontend Architecture hereda: el requisito de CSRF token si el panel se separa a una SPA con llamadas a una API distinta. DevOps Architecture hereda: rotación calendarizada de credenciales, escaneo de vulnerabilidades/SBOM, ejecución operativa del rate limiting. Operations Architecture hereda: monitoreo de los eventos de `RegistroAuditoria` en producción.

---

## Architectural Constraints

| Restricción | Naturaleza | Impacto en el diseño |
|---|---|---|
| Anthropic no ofrece hoy API keys con scopes granulares a nivel público | Hecho del proveedor | No hay decisión de seguridad pendiente sobre scopes de `ANTHROPIC_API_KEY`, solo una limitación externa a documentar |
| Meta exige verificación de firma vía `X-Hub-Signature-256` como único mecanismo soportado | Hecho del proveedor | Define el único punto de verificación posible para el webhook — no hay alternativa de diseño |
| Railway no ofrece un gestor de secretos dedicado nativo, solo variables de entorno | Hecho de la plataforma de despliegue actual | Toda credencial fuera de las cifradas en BD depende de la seguridad de las variables de entorno de Railway |
| El cifrado de campo en una base de datos relacional rompe búsqueda/filtrado por igualdad indexada, salvo mecanismos adicionales (cifrado determinístico, tokenización) | Hecho técnico general, no específico de este proyecto | Justifica la decisión de la sección 5 de no cifrar `Lead`/`Mensaje` sin rediseñar antes cómo se buscan |
| `SameSite=Lax` es el comportamiento por defecto de `SessionMiddleware` de Starlette | Hecho de la librería usada | Da una mitigación parcial de CSRF sin configuración adicional, pero no reemplaza un token CSRF explícito |

## Decisiones locales

| Decisión | Estado | Justificación | Criterio de revisión |
|---|---|---|---|
| Eliminar el fail-open de verificación de firma del webhook | Objetivo | P1 del CSA — protección central contra webhooks falsificados | Si Meta cambia su mecanismo de firma |
| Rate limiting en `/login` y `/webhook` | Objetivo | P1 del CSA; resuelve brecha ya declarada en API y AI Architecture | Si el límite elegido afecta tráfico legítimo real |
| Límite de intentos de login con bloqueo temporal | Objetivo | Mitiga fuerza bruta (riesgo Alta del CSA) | Si genera fricción real a usuarios legítimos |
| Token CSRF explícito en formularios de estado | Objetivo | P2 del CSA | — |
| No cifrar PII de `Lead`/`Mensaje` a nivel de campo por ahora | **Activa** | Rompería búsqueda/filtrado ya en uso; control de acceso es la mitigación primaria hoy | Requisito regulatorio explícito, incidente real, o acceso de un tercero a la BD sin pasar por la aplicación |
| Ruta formal de alta de usuarios en el panel | Objetivo | Cierra brecha ya registrada en memoria del proyecto | — |
| `RegistroAuditoria` debe registrar login fallido, cambio de rol, cambio de credencial de canal y acceso denegado | Objetivo, dependiente de Data Architecture | Contenido mínimo de seguridad que la tabla ya definida debe soportar | Si el volumen de eventos crece desproporcionadamente al valor de auditarlos |
| Toda consulta a datos de negocio debe filtrar por `negocio_id` una vez exista | Objetivo, dependiente de Data Architecture Fase 3 | Principio de aislamiento Multi-Tenant desde el lado de seguridad | Cuando exista un segundo negocio real |
| Exponer tool-calling real al AI Engine requiere aprobación explícita de Security Architecture | **Activa** | Formaliza desde Security el gate que AI Architecture ya se impuso a sí misma | Si AI Architecture evidencia una necesidad real de tool-calling |

## Brechas conocidas

- **Política de retención de datos** (plazo, alcance de qué se purga) → dueño de producto/negocio, no arquitectónica; este documento solo deja el principio de que debe ser purgable.
- **Rotación calendarizada de credenciales** (frecuencia, ejecución) → DevOps/Operations Architecture.
- **Escaneo de vulnerabilidades / SBOM de dependencias** → DevOps Architecture (integración en CI).
- **MFA** → sin dueño asignado; se revisará si el volumen o la sensibilidad del panel lo justifican.
- **Mecanismo técnico exacto de `negocio_id` en cada consulta** → Data Architecture Fase 3.

## Architecture Success Criteria

1. La verificación de firma del webhook rechaza toda solicitud cuando ningún canal tiene `app_secret` configurado — nunca retorna válido por default. Verificable configurando un canal sin `app_secret` y confirmando que el webhook responde 403.
2. `/login` y `/webhook` responden con un límite de tasa verificable (ej. 429 tras N solicitudes en una ventana de tiempo). Verificable con una prueba de carga simple contra cada endpoint.
3. Tras N intentos fallidos consecutivos de login para un mismo usuario, la cuenta queda temporalmente bloqueada. Verificable intentando iniciar sesión N+1 veces con credenciales incorrectas.
4. Todo formulario de estado del panel incluye y valida un token CSRF. Verificable inspeccionando el HTML de cada formulario y probando un POST sin el token.
5. `RegistroAuditoria` contiene al menos un evento por cada login fallido, cambio de rol, cambio de credencial de canal y acceso denegado por autorización ocurridos en el sistema. Verificable generando cada tipo de evento y consultando el registro.
6. Existe una ruta del panel, protegida por rol `admin`, para dar de alta un usuario — no solo un script externo. Verificable navegando el panel con una cuenta `admin`.

## QA arquitectónico

Este documento fue verificado contra el checklist de 11 preguntas del ADS §11 antes de presentarse — en particular, se confirmó que la decisión de no cifrar PII (sección 5) está correctamente clasificada como Decisión local (elegida, con criterio de revisión) y no como Architectural Constraint (que son hechos, no elecciones), y que las 6 Architecture Success Criteria son condiciones verificables, no tareas de roadmap.

## Cierre

Este documento cierra el diseño objetivo del dominio de Security, construido sobre el CSA-Security ya aprobado (Threat Landscape y Trust Boundaries como insumo directo) y sin redefinir ninguna decisión ya tomada en Data, Backend, API o AI Architecture — solo resuelve las brechas que esos documentos ya le dejaron explícitamente asignadas. **Approved** el 2026-07-28.

---

*Fin del documento.*
