# Maiek AI — Current State Assessment: DevOps Architecture

**Versión 1.0 · Estado: Approved**

| | |
|---|---|
| Documento | Current State Assessment – DevOps Architecture |
| Proyecto | Maiek AI |
| Versión | 1.0 |
| Estado | **Approved** |
| Fecha de creación | 2026-07-28 |
| Autor | Claude, a pedido de Jesús Millones |
| Fecha de aprobación | 2026-07-28 |
| Última actualización | 2026-07-28 |

## Dependencias

- `MAIEK_AI_SYSTEM_ARCHITECTURE.md` (MSA) Capítulo 14 (Infraestructura/Despliegue), Capítulo 15 — ya declara explícitamente como brechas propias de este documento: ambiente de staging (MSA:323), pipeline de CI formal (MSA:325), y "el detalle operativo completo (pipelines exactos, scripts, políticas de rollback)" (MSA:329).
- `MAIEK_AI_SECURITY_ARCHITECTURE.md` — brechas ya derivadas explícitamente hacia DevOps: rotación calendarizada de credenciales, escaneo de vulnerabilidades/SBOM, ejecución operativa del rate limiting.
- `MAIEK_AI_API_ARCHITECTURE.md` — brecha ya derivada: uso operativo real de `request_id` (dashboards, alertas).
- `MAIEK_AI_AI_ARCHITECTURE.md` — brecha ya derivada: costo/eficiencia de inferencia como preocupación operativa (prompt caching, límite de contexto).
- `MAIEK_AI_DATA_ARCHITECTURE.md` — modelo de datos y `RegistroAuditoria`, contexto de lo que este CSA audita desde el ángulo de persistencia/backups.
- `MAIEK_AI_ARCHITECTURE_DOCUMENT_STANDARD.md` (ADS) v1.3.

## Consumido por

`MAIEK_AI_DEVOPS_ARCHITECTURE.md` (DevOps Architecture, todavía no construida).

## Control de versiones

| Versión | Fecha | Autor | Descripción |
|---|---|---|---|
| 1.0 (borrador) | 2026-07-28 | Claude | Primera versión — auditoría objetiva del estado real de operaciones (`Dockerfile`, `docker-compose.yml`, `agent/main.py`, `agent/memory.py`, `agent/notificaciones.py`, `agent/campanas.py`, `scripts/`, `requirements.txt`, `.env.example`), sobre las 12 dimensiones pedidas por el usuario. Sin propuestas de solución. Pendiente de revisión y aprobación. |
| 1.0 | 2026-07-28 | Claude | Aprobado sin reapertura del contenido. El usuario registró 2 mejoras futuras no bloqueantes, a incorporar en una versión posterior de este CSA: (1) **Infrastructure as Code** — declarar explícitamente el estado actual (hoy: no existe ningún mecanismo de IaC — sin Terraform, sin Railway como código, sin configuración declarativa más allá del `Dockerfile`/`docker-compose.yml`); (2) **Objetivos operativos** — registrar el estado actual de SLO, SLA, RPO y RTO (hoy: ninguno de los cuatro está definido en ningún documento o código del proyecto). |

## Alcance

Auditoría objetiva del estado real de operaciones — despliegue, CI/CD, configuración, secretos (ángulo operativo), base de datos/migraciones/backups, observabilidad, monitoreo/alertamiento, recuperación ante fallos, cadena de suministro, costos/escalabilidad, automatización y preparación SaaS Multi-Tenant — con evidencia de código citada por archivo y línea. No repite el análisis ya hecho en los CSA de Data, Backend, API, AI y Security: los cita como contexto ya establecido (gestión de secretos a nivel de código, `negocio_id`/`RegistroAuditoria` no implementados, brechas ya delegadas a DevOps) en vez de re-derivarlos.

---

## 1. Arquitectura de despliegue y entornos

El despliegue corre sobre un único `Dockerfile` (`Dockerfile:1-11`): imagen base `python:3.11-slim` (tag flotante, no fijado a una versión exacta ni a un digest), instala `ffmpeg` para la transcodificación de notas de voz, y arranca con `uvicorn agent.main:app --host 0.0.0.0 --port ${PORT:-8000}`. `docker-compose.yml` (12 líneas) define un único servicio (`agent`), sin límites de CPU/memoria ni configuración de réplicas.

No existe ningún archivo de configuración específico de Railway (`railway.json`, `railway.toml`, `nixpacks.toml`, `Procfile`) — Railway detecta y usa el `Dockerfile` directamente.

Existen hoy exactamente dos ambientes reales: local (SQLite, servidor con `--reload`) y producción (PostgreSQL, Railway) — `ENVIRONMENT` (`agent/main.py:39`) solo toma los valores `"development"` o `"production"` en todo el código; no hay ningún ambiente de staging. Esto ya está reconocido explícitamente en el propio MSA (`MAIEK_AI_SYSTEM_ARCHITECTURE.md:323`): *"un ambiente de staging queda como brecha explícita, no resuelta hoy, señalada para DevOps Architecture"* — se cita como brecha ya delegada, no se re-analiza.

## 2. CI/CD y estrategia de releases

No existe ningún pipeline de CI — se confirmó la ausencia de `.github/workflows/` (no existe siquiera el directorio `.github`) y de cualquier configuración equivalente (`gitlab-ci.yml`, etc.). El patrón real de release es: integrar a la rama principal → Railway despliega automáticamente desde GitHub — ya reconocido explícitamente en el MSA (`MAIEK_AI_SYSTEM_ARCHITECTURE.md:325`): *"despliegue continuo... sin un pipeline de CI formal (pruebas automáticas antes de desplegar) documentado todavía"*.

No hay ningún framework de pruebas automatizadas en `requirements.txt` (sin `pytest` ni equivalente). `tests/test_local.py` es un script de chat interactivo manual (sin *assertions*, se ejecuta a mano y se evalúa a ojo) — no es una suite de pruebas automatizada, y no forma parte de ningún gate antes de desplegar.

## 3. Gestión de configuración y variables de entorno

Todas las variables de entorno leídas en el código (`os.getenv`, confirmadas por archivo): `ENVIRONMENT`, `SESSION_SECRET_KEY`, `PORT` (`agent/main.py:39,48,58`); `CANAL_ENCRYPTION_KEY`, `DATABASE_URL` (`agent/memory.py:33,55`); `META_CANAL_{i}_*`, `META_ACCESS_TOKEN`/`META_PHONE_NUMBER_ID`/`META_APP_SECRET`/`META_PAGE_ACCESS_TOKEN` (`agent/memory.py:409-430`); `RESEND_API_KEY`, `NOTIFICACION_REMITENTE`, `NOTIFICACION_DESTINATARIOS` (`agent/notificaciones.py:17-21`); `WHATSAPP_NUMERO_PUBLICO`, `META_LEADGEN_TEMPLATE_NAME`/`_LANG` (`agent/campanas.py:39,189-190`); `ANTHROPIC_API_KEY` (`agent/brain.py:25`); `META_VERIFY_TOKEN` (`agent/providers/meta.py:24`); `WHATSAPP_PROVIDER` (`agent/providers/__init__.py:14`); `ARCHIVOS_DIR` (`agent/dashboard.py:103`).

La validación de arranque es inconsistente: `WHATSAPP_PROVIDER` sí falla al cargar el módulo si falta o tiene un valor no soportado (`agent/providers/__init__.py:14-24`, efectivamente fail-fast). `SESSION_SECRET_KEY` solo se exige si `ENVIRONMENT == "production"` (`agent/main.py:49-53`). `CANAL_ENCRYPTION_KEY` falla, pero de forma perezosa — recién en el primer uso real de un canal, no al arrancar (`agent/memory.py:33-38`). El resto (`ANTHROPIC_API_KEY`, `RESEND_API_KEY`, `DATABASE_URL`, credenciales de Meta) **no tiene ninguna validación de existencia** — fallan en silencio o en su primer uso, sin bloquear el arranque del proceso.

El `lifespan()` de `agent/main.py:61-71` (que llama `inicializar_db`, `sembrar_canales_desde_env`, `sembrar_campanas_iniciales`, `corregir_patrones_desalineados`) no tiene manejo de excepciones propio alrededor de esas llamadas.

## 4. Gestión de secretos (perspectiva operativa)

No existe documentación ni script de rotación de secretos. El único mecanismo real para fijar un secreto es la entrada manual en la pestaña "Variables" del dashboard de Railway (referenciado en `README.md:116` y en el docstring de `scripts/migrar_usuarios_a_railway.py:5-6`). Rotar `CANAL_ENCRYPTION_KEY` está documentado como una operación destructiva, no como un procedimiento soportado (`.env.example:49-50`: *"si se pierde/cambia, los canales ya guardados quedan ilegibles"*).

La gestión de secretos a nivel de código (cifrado Fernet, separación env vars vs. BD) ya fue auditada en el CSA-Security y resuelta en Security Architecture — se cita, no se re-analiza acá. Este CSA solo confirma que, desde el ángulo operativo, no existe ningún proceso de rotación real más allá de cambiar el valor a mano en Railway.

## 5. Base de datos, migraciones y backups

No hay ninguna herramienta de migraciones — `alembic` no está en `requirements.txt`, no existe `alembic.ini` ni ningún directorio `migrations/`. El único mecanismo de esquema es `Base.metadata.create_all` (`agent/memory.py:438-441`, `inicializar_db`), invocado en cada arranque desde `lifespan()` (`agent/main.py:64`) — este mecanismo **solo crea tablas que no existen**, nunca altera columnas de tablas ya existentes. Cualquier cambio de columna en una tabla ya desplegada requiere intervención manual, no versionada. `scripts/migrar_usuarios_a_railway.py:46-48` invoca el mismo `create_all` de forma independiente antes de copiar usuarios — mecanismo ad-hoc, específico de ese script.

No se encontró ningún script de backup, cron job, ni estrategia documentada para la base de datos Postgres en Railway, en ningún punto del repositorio.

El motor de base de datos se crea sin ninguna configuración explícita de *connection pooling* (`agent/memory.py:61`: `create_async_engine(DATABASE_URL, echo=False)`, sin `pool_size`, `max_overflow`, `pool_recycle` ni `pool_pre_ping`) — usa los valores por defecto de SQLAlchemy.

## 6. Observabilidad

El logging se configura en un único punto (`agent/main.py:39-42`): `logging.basicConfig(level=...)`, `DEBUG` en desarrollo / `INFO` en producción, texto plano (sin formato JSON ni estructurado), usando el *handler* por defecto de `basicConfig`. Cada módulo obtiene su logger vía `logging.getLogger("agentkit")` (mismo *namespace* raíz en `dashboard.py`, `memory.py`, `brain.py`, `campanas.py`, `notificaciones.py`, `tools.py`, `tiempo_real.py`, `providers/meta.py`, `asignacion.py`).

No se encontró ninguna librería de métricas o trazas (`sentry`, `prometheus`, `opentelemetry`, `datadog`, `statsd`) ni en el código ni en `requirements.txt` — confirmado ausente. No hay tracing distribuido de ningún tipo.

## 7. Monitoreo y alertamiento

Resend se usa exclusivamente para notificaciones de negocio — asignación de lead (`agent/notificaciones.py:26-80`) y solicitud de reseteo de contraseña (`agent/notificaciones.py:83-118`) — nunca para alertas de sistema. El manejador de excepción de nivel superior del webhook (`agent/main.py:294-296`) solo registra el error en el log y retorna un 500; no dispara ninguna notificación.

No se encontró integración con Slack, PagerDuty, ni ninguna herramienta de *uptime monitoring* en el repositorio. El único *health check* es `GET /` (`agent/main.py:94-97`, retorna `{"status": "ok", "service": "agentkit"}`) — nada dentro de este repositorio lo consulta activamente (si Railway lo hace a nivel de plataforma, no es visible desde el código). El `setInterval` de 30 segundos en `agent/dashboard.py:762` es una función del lado del navegador para recordatorios de citas dentro del panel — no debe confundirse con monitoreo de infraestructura.

## 8. Recuperación ante fallos y rollback

No existe ningún procedimiento de rollback documentado ni scripteado — el propio MSA ya lo declara explícitamente como responsabilidad pendiente de este documento (`MAIEK_AI_SYSTEM_ARCHITECTURE.md:329`). No hay configuración de estrategia de despliegue (blue-green/rolling) porque no existe ningún archivo de configuración de Railway en el repositorio.

No se encontró ningún mecanismo de *retry*, *backoff* ni *timeout* explícito en llamadas a servicios externos: las instancias de `httpx.AsyncClient()` en `agent/notificaciones.py:74,112` y `agent/providers/meta.py:145,168,187,214,240,264,280,331` no reciben un `timeout` explícito; `AsyncAnthropic(api_key=...)` en `agent/brain.py:25` tampoco recibe `timeout`/`max_retries` explícitos — ambos dependen de los valores por defecto de cada SDK. El único `timeout=` encontrado en todo `agent/*.py` es el de un `subprocess.run` de `ffmpeg` (`agent/dashboard.py:3307`, 30 segundos), no relacionado con llamadas de red externas.

## 9. Gestión de dependencias y cadena de suministro

Ya diagnosticado desde el ángulo de código en el CSA-Security (`requirements.txt` sin techos de versión, sin Dependabot) — se cita, se agrega acá el ángulo operativo: no existe ningún archivo de bloqueo de versiones (`poetry.lock`, `Pipfile.lock`, `requirements-lock.txt`) — cada `docker build` puede resolver versiones distintas de dependencias transitivas según el momento, sin reproducibilidad garantizada entre builds. La imagen base del `Dockerfile` (`python:3.11-slim`) tampoco está fijada a una versión exacta ni a un *digest*.

## 10. Costos operativos y escalabilidad

`docker-compose.yml` no define límites de CPU/memoria ni número de réplicas — un solo contenedor, un solo proceso. No existe archivo de configuración de Railway que defina límites de recursos o escalado horizontal. El *connection pooling* de base de datos (sección 5) no está ajustado para ningún escenario de múltiples instancias.

Ya existe una memoria de proyecto pendiente sobre "revisión de costos" (Railway, Anthropic, Meta, Resend) — se cita como contexto ya reconocido por el usuario; el detalle de cifras es una revisión contable, no arquitectónica, y queda fuera del alcance de este CSA.

## 11. Automatización operativa

El directorio `scripts/` contiene un único archivo: `scripts/migrar_usuarios_a_railway.py` (69 líneas) — copia usuarios reales (excluyendo cuentas demo/debug, línea 26) desde SQLite local hacia Postgres en Railway, preservando el hash de contraseña. Es idempotente por usuario (`session.get(Usuario, username)`, líneas 50-62) y de invocación manual, documentada en su propio docstring — no está integrado a ningún proceso automatizado.

Tres funciones de siembra/corrección corren automáticamente en cada arranque del proceso, dentro de `lifespan()` (`agent/main.py:64-67`): `sembrar_canales_desde_env` (`agent/memory.py:395-435`, solo si la tabla de canales está vacía), `sembrar_campanas_iniciales` (`agent/campanas.py:328-338`, solo si la tabla de campañas está vacía), y `corregir_patrones_desalineados` (`agent/campanas.py:355-367`, **sin ninguna guarda de "ya se ejecutó"** — corrige datos en cada arranque, incluso en bases ya corregidas). Las tres corren automáticamente en cada *deploy* o reinicio, mezcladas con el ciclo de vida normal del servidor de aplicación, no como un paso de *release* separado.

## 12. Preparación para operación SaaS Multi-Tenant

Confirmado a nivel de infraestructura (consistente con la ausencia de `negocio_id` ya establecida en Data/AI/Security Architecture): una sola `DATABASE_URL`, un solo contenedor, un solo servicio en `docker-compose.yml` — sin ningún aislamiento de recursos por negocio. El mecanismo multi-canal (`META_CANAL_{i}_*`) sirve para que **múltiples números de WhatsApp del mismo negocio** compartan un despliegue y una base de datos (documentado explícitamente para "pruebas + producción", `.env.example:30-31`) — no debe confundirse con aislamiento multi-tenant. No existe ningún concepto de "un proyecto de Railway por tenant" ni "un ambiente por tenant" en ningún archivo de configuración del repositorio.

---

## Fortalezas

- Despliegue continuo simple y funcional (`git push` → Railway) — proporcional al tamaño actual del equipo.
- Siembra idempotente de datos iniciales (canales, campañas), con guardas de "tabla vacía" que evitan duplicados en reinicios.
- `WHATSAPP_PROVIDER` sí falla rápido y claro si falta o es inválido — de los pocos controles de arranque reales que existen.
- Separación de logger por módulo bajo un mismo *namespace* (`"agentkit"`) — facilita filtrar, aunque no haya nada más sofisticado detrás.
- Dependencia de sistema (`ffmpeg`) declarada explícitamente en el `Dockerfile`, no asumida implícitamente.

## Decisiones heredadas del MVP (razonables para la etapa, a reevaluar)

- Sin CI formal ni ambiente de staging — proporcional a un equipo pequeño y bajo volumen de cambios.
- `create_all` en vez de migraciones versionadas — suficiente mientras el esquema no requiera alterar columnas existentes con frecuencia.
- `docker-compose` de un solo servicio sin límites de recursos — adecuado a un solo contenedor de bajo tráfico.
- Sin *connection pooling* ajustado — el valor por defecto de SQLAlchemy alcanza al volumen actual.

## Deuda técnica (sin justificación de etapa)

- **Ausencia total de *retries*/*timeout* explícitos** en llamadas a Anthropic, Meta y Resend — no es una decisión de simplicidad, es una omisión de robustez independiente del tamaño del proyecto.
- **Sin archivo de bloqueo de dependencias** — la reproducibilidad de build es una práctica básica, no depende de la etapa del proyecto.
- **`corregir_patrones_desalineados()` corre en cada arranque sin ninguna guarda** — funciona, pero mezcla una corrección de datos puntual con el ciclo de vida normal del servidor, sin mecanismo de "ya se aplicó, no repetir".
- **Ningún backup de base de datos confirmado** — omisión de robustez, no una decisión consciente documentada en el repositorio.
- **Ningún alertamiento de errores de sistema** (solo logs) — el costo de agregar una alerta es bajo comparado con el valor de saber que algo falló en producción sin depender de que alguien revise logs manualmente.

## Desviaciones respecto al MSA y documentos derivados ya Approved

- **MSA Cap. 14-15 (staging, CI formal, políticas de rollback)** — no son desviaciones, son las brechas que el propio MSA ya declaró explícitamente como responsabilidad de este documento (`MSA:323,325,329`) — es, literalmente, para lo que este CSA existe.
- **Security Architecture (rotación calendarizada, escaneo de vulnerabilidades/SBOM, ejecución operativa del rate limiting)** — mismo criterio: brechas ya delegadas, sincronización pendiente, no desviación.
- **API/AI Architecture (uso operativo de `request_id`, costo/eficiencia de inferencia)** — mismo criterio.
- No se identificó ninguna decisión ya tomada en un documento Approved que el estado actual contradiga activamente.

## Riesgos detectados

1. **Alto** — despliegue automático a producción en cada `push` a `main`, sin ningún gate de pruebas automatizado.
2. **Alto** — sin backups de base de datos confirmados: pérdida de datos potencialmente irrecuperable ante un incidente de Postgres.
3. **Medio** — sin *retries*/*timeout* en llamadas externas: un proveedor lento o caído puede colgar solicitudes por un tiempo no verificado como seguro.
4. **Medio** — sin alertamiento de errores de sistema: un fallo sistemático puede pasar desapercibido hasta que un humano lo note manualmente.
5. **Medio** — `create_all` no soporta cambios de columna: un cambio de esquema real requiere intervención manual no versionada.
6. **Bajo** — sin archivo de bloqueo de dependencias: reproducibilidad de build no garantizada.
7. **Bajo hoy / bloqueante futuro** — sin aislamiento de recursos por tenant a nivel de infraestructura.

## Architectural Readiness

| Dimensión | Madurez actual | Nota |
|---|---|---|
| Despliegue | **Parcial** | Funcional y simple, sin ambiente de staging |
| CI/CD | **Ausente** | Sin pipeline, sin gate de pruebas antes de desplegar |
| Gestión de configuración | **Parcial** | Algunos fail-fast reales, la mayoría sin validar |
| Gestión de secretos (operativa) | **Débil** | Sin rotación, solo entrada manual en Railway |
| Migraciones / backups | **Débil** | Sin migraciones versionadas, sin backups confirmados |
| Observabilidad | **Ausente** | Solo logs de texto plano, sin métricas ni trazas |
| Monitoreo / alertamiento | **Ausente** | Sin alertas de sistema, health check sin consumidor visible |
| Recuperación ante fallos | **Débil** | Sin rollback, sin retries/timeout |
| Cadena de suministro | **Débil** | Sin lockfile, sin escaneo de vulnerabilidades |
| Costos / escalabilidad | **Básico** | Un solo contenedor, sin límites de recursos |
| Automatización operativa | **Parcial** | Siembra idempotente sí, mezclada con el arranque del servidor |
| Multi-Tenant (infraestructura) | **Ausente** | Sin aislamiento de recursos por negocio |

**Conclusión de preparación:**

- **MVP (uso actual, un solo negocio):** **Listo.** El sistema opera hoy de forma simple y funcional — los riesgos identificados no son hipotéticos, pero tampoco han impedido la operación real hasta ahora.
- **Crecimiento (más volumen, mismo negocio):** **No listo.** La ausencia de CI, backups, alertamiento y *retries* se vuelve crítica antes que cualquier otra brecha — cada una de ellas es, individualmente, suficiente para un incidente real a mayor escala.
- **SaaS multiempresa:** **No listo.** No existe ningún aislamiento de recursos por tenant a nivel de infraestructura — coherente con la misma conclusión ya alcanzada en Data, AI y Security Architecture, ahora confirmada también desde el ángulo operativo.

## Priorización de remediación

| Prioridad | Ítem | Por qué |
|---|---|---|
| **P1** | Backups automatizados de la base de datos Postgres | Mitiga el riesgo de pérdida de datos irrecuperable |
| **P1** | Gate de pruebas automatizado antes de desplegar (CI mínimo) | Mitiga el riesgo de que cualquier commit llegue a producción sin fricción |
| **P1** | *Retries*/*timeout* explícitos en llamadas a Anthropic, Meta y Resend | Cierra la omisión de robustez más transversal del CSA |
| **P2** | Alertamiento de errores de sistema (no solo logs) | Cierra la brecha de monitoreo más señalada |
| **P2** | Migraciones versionadas (ej. Alembic) en vez de `create_all` | Antes de que un cambio de columna real se vuelva urgente |
| **P2** | Ambiente de staging | Ya declarado como brecha explícita en el MSA |
| **P3** | Archivo de bloqueo de dependencias | Reproducibilidad de build, bajo riesgo actual |
| **P3** | Límites de recursos en `docker-compose`/Railway | Proporcional a cuando el tráfico lo amerite |
| **P3** | Separar `corregir_patrones_desalineados()` del ciclo de arranque normal | Bajo riesgo actual, mejora de higiene operativa |

## Architectural Decision Impact

| Hallazgo | Arquitecturas afectadas | Por qué |
|---|---|---|
| Sin CI/gate de pruebas | DevOps, Backend | Backend Architecture define la lógica que llega a producción sin ninguna verificación automatizada previa |
| Sin backups | DevOps, Data | Data Architecture define el modelo; DevOps debe garantizar que sea recuperable |
| Sin *retries*/*timeout* | DevOps, AI, API | Llamadas a Anthropic y Meta ya identificadas en AI/API Architecture; DevOps es quien opera la resiliencia real |
| Sin alertamiento | DevOps, Security | `RegistroAuditoria` (Security Architecture) necesita un consumidor operativo que reaccione, no solo un almacén pasivo |
| Sin aislamiento de recursos multi-tenant | DevOps, Data, AI, Security | Todos ya señalaron `negocio_id` como bloqueante; DevOps confirma que tampoco existe aislamiento a nivel de infraestructura |

## Strategic Recommendations

1. **El gate de pruebas antes de desplegar es la decisión de mayor apalancamiento de este documento** — hoy cualquier commit a `main` es indistinguible de un despliegue a producción.
2. **Backups y *retries*/*timeout* pueden resolverse en paralelo** — son independientes entre sí y ambos son P1.
3. **El alertamiento de errores y el consumo de `RegistroAuditoria`** pueden diseñarse juntos — ambos requieren decidir qué evento amerita que un humano se entere ahora, no después.
4. **Migrar de `create_all` a migraciones versionadas es más urgente cuanto antes se planee alterar una columna existente** — hoy no es bloqueante porque el esquema no lo ha necesitado, pero el costo de migrar tarde crece con cada tabla nueva.
5. **El aislamiento de recursos multi-tenant no es urgente hoy, pero DevOps Architecture es el lugar natural para dejar declarado el principio** — igual que ya lo hizo Security Architecture desde su ángulo — para que Data Architecture Fase 3 no tenga que resolverlo sin ningún punto de partida operativo.

---

*Fin del documento. Approved el 2026-07-28. Siguiente paso: construir `MAIEK_AI_DEVOPS_ARCHITECTURE.md` (arquitectura objetivo) como evolución explícita desde este estado real, siguiendo el ADS, el MSA, y las brechas ya declaradas por Data, Backend, API, AI y Security Architecture.*
