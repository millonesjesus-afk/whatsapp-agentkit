# Deployment Checklist — v0.2.0 (Fase 1: Núcleo técnico)

**Uso:** seguir en orden, de arriba hacia abajo, sin saltar pasos. Cada casilla sin marcar es un
bloqueo para continuar a la siguiente — no un recordatorio opcional. Referencia operativa completa
del punto de mayor riesgo (Alembic): `MAIEK_AI_OPERATIONS_RUNBOOK.md`, Escenario 1.

---

## 1. Backup de la base de datos

- [ ] Confirmar que `scripts/backup_postgres.py` corrió recientemente (revisar el almacenamiento
      S3-compatible configurado — último backup no debería tener más de 24h).
- [ ] Si no hay un backup reciente, ejecutarlo manualmente antes de continuar.
- [ ] Confirmar que el backup es restaurable (no solo que el archivo existe) — si nunca se probó una
      restauración real, este es el momento de decidir si vale la pena hacerlo antes de continuar.

## 2. Ejecución de `alembic stamp head`

- [ ] Confirmar la `DATABASE_URL` real de producción (Railway → servicio Postgres → Variables) — este
      es el paso de mayor riesgo real: aplicar el stamp contra la base equivocada.
- [ ] Ejecutar:
      ```
      DATABASE_URL="<DATABASE_URL real de Railway>" python -m alembic stamp head
      ```
- [ ] El comando no debería imprimir nada si sale bien (comportamiento normal de Alembic).

## 3. Verificación de migraciones

- [ ] `DATABASE_URL="<misma URL>" python -m alembic current` debe mostrar `925ec2d81736 (head)`.
- [ ] Verificación directa en la base (`psql`): `SELECT * FROM alembic_version;` debe retornar
      exactamente una fila, con `version_num = '925ec2d81736'`.
- [ ] Si cualquiera de las dos verificaciones falla, **no continuar** — repetir el paso 2, no el
      despliegue.

## 4. Push

- [ ] Confirmar que no hay cambios de código sin commitear ni sin revisar desde
      `IMPLEMENTATION_REVIEW_FASE_1.md` (Code Freeze vigente).
- [ ] `git push` de `deploy-main` a `deploy/main`.

## 5. Deploy

- [ ] Confirmar en el dashboard de Railway que el deploy queda `Active` / `Deployment successful`.
- [ ] Si el arranque falla con un `RuntimeError` de "base de datos ya tiene tablas... pero no está
      registrada en Alembic" — el paso 2 no se completó correctamente. No reintentar el deploy sin
      resolver el stamp primero (`MAIEK_AI_OPERATIONS_RUNBOOK.md`, Escenario 1, punto 8).

## 6. Smoke Tests

- [ ] `GET /` responde `200 {"status": "ok", "service": "agentkit"}`.
- [ ] `GET /docs` responde `404` (restringido, sin cambios respecto a antes).
- [ ] `GET /dashboard/login` carga el HTML de login normalmente.
- [ ] Un login real con un usuario existente funciona y lleva al dashboard.

## 7. Validación de logs

- [ ] En los logs de Railway aparece `Migraciones aplicadas (alembic upgrade head, rc=0)` **antes**
      de `Base de datos inicializada`.
- [ ] Sin `RuntimeError` ni traceback en el arranque.
- [ ] El formato de cada línea de log incluye `[request_id]` (confirma que el filtro de correlación
      está activo, aunque la mayoría de las líneas de arranque muestren `[-]` por no pertenecer a
      ninguna solicitud HTTP todavía).

## 8. Validación de `request_id`

- [ ] Cualquier respuesta (ej. `curl -I https://<dominio>/`) incluye el header `X-Request-Id`.
- [ ] Provocar un error real conocido (ej. una ruta del panel con un `telefono` inexistente) y
      confirmar que la respuesta JSON tiene la forma `{"codigo", "mensaje", "detalle", "request_id"}`.
- [ ] Ese mismo `request_id` aparece en los logs de Railway correlacionado con esa solicitud.

## 9. Validación de idempotencia

- [ ] Enviar un mensaje de prueba real por WhatsApp al número de producción y confirmar en logs que
      se procesó exactamente una vez.
- [ ] Esta validación es principalmente **pasiva**: Meta reentrega mensajes solo bajo ciertas
      condiciones (timeout de nuestro `200 OK`, fallas de red) — no siempre es forzable a demanda.
      Monitorear los logs las primeras horas de tráfico real por la línea `"ya procesado antes —
      ignorado (idempotencia)"`; su ausencia no es un fallo, su presencia confirma el mecanismo
      funcionando ante una reentrega real.

## 10. Validación del protocolo de confianza

- [ ] **Confirmar que el canal de producción real sigue en `modo="producción"`** — el criterio de
      éxito acá es que el comportamiento visible para clientes reales **no cambie** con este
      despliegue.
- [ ] Si existe (o se crea deliberadamente) un canal en `modo="pruebas"`, enviar un mensaje ahí y
      confirmar en los logs una línea `inferencia_ia` con `confianza`/`razon` bien formados.
- [ ] No promover ningún canal a `modo="pruebas"` en producción como parte de este despliegue — eso
      requiere primero ejecutar `MAIEK_AI_CONVERSATIONAL_VALIDATION_PLAN.md`.

## 11. Validación de revisión prioritaria

- [ ] Depende de que el protocolo de confianza esté activo en algún canal (paso 10) — si no hay
      canal de pruebas todavía, esta validación queda diferida explícitamente, sin bloquear el
      cierre del despliegue (no afecta producción).
- [ ] Si hay canal de pruebas: provocar (o esperar) una respuesta con confianza `Requiere validación`
      y confirmar que el lead muestra el badge "Revisión prioritaria" en la lista de conversaciones
      del panel.
- [ ] Confirmar que el badge desaparece al abrir el detalle de ese lead.

## 12. Criterios para considerar exitoso el despliegue

Todos los siguientes deben cumplirse:

- [ ] Arranque limpio, sin errores, en los logs de Railway (secciones 5 y 7).
- [ ] Health check (`GET /`) responde `200` de forma sostenida (no solo en el primer chequeo).
- [ ] Al menos un mensaje real de WhatsApp en `modo="producción"` fue procesado y respondido con
      comportamiento **idéntico** al de antes del despliegue — mismo criterio de cierre que Fase 0.
- [ ] `request_id` presente y correlacionado en al menos una solicitud real verificada.
- [ ] Sin errores `500` inesperados durante los primeros 30-60 minutos de tráfico real.
- [ ] Ningún reporte de comportamiento distinto por parte de quien use el panel activamente durante
      ese período.

Si **todos** se cumplen: el despliegue queda cerrado, se actualiza `DOCUMENTATION_INDEX.md` con la
fecha real de despliegue, y recién ahí se levanta el Code Freeze para dar inicio a la Fase 2.

## 13. Procedimiento de rollback en caso de falla

- **Nivel de despliegue (código)**: usar el rollback nativo de Railway al deployment `Active` anterior
  — es seguro incluso con las migraciones de esta versión ya aplicadas: las columnas/tabla nuevas
  (`revision_prioritaria`, `mensajes_procesados`) son aditivas, el código anterior simplemente no las
  usa, no las rompe. **No es necesario revertir las migraciones de base de datos para hacer rollback
  de código.**
- **No usar** `git push --force` ni revertir commits del repositorio como parte de este
  procedimiento — el rollback es a nivel del deployment de Railway, no de la historia de git.
- Pasos:
  1. Revertir el deployment en Railway al anterior conocido como bueno.
  2. Confirmar arranque limpio del código anterior (repetir los pasos 6-7 contra esa versión).
  3. Investigar la causa de la falla localmente, sin presión de tiempo, antes de reintentar el
     despliegue de v0.2.0.
  4. Si la causa fue el propio `alembic stamp head` (ej. aplicado contra la base equivocada), consultar
     `MAIEK_AI_OPERATIONS_RUNBOOK.md`, sección "Qué pasos seguir si el comando falla" — el `stamp` en
     sí nunca modifica datos ni estructura, así que no hay nada que revertir por haberlo corrido, salvo
     volver a aplicarlo correctamente contra la base correcta.
  5. Solo reintentar el despliegue completo (desde el paso 1 de este checklist) una vez identificada
     y corregida la causa raíz — no repetir el push a ciegas.

---

*Checklist de despliegue para v0.2.0 — ver `RELEASE_NOTES_v0.2.0.md` para el resumen de la versión y
`IMPLEMENTATION_REVIEW_FASE_1.md` para el detalle técnico completo.*
