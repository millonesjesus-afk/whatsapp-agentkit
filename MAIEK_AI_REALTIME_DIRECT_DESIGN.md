# Tiempo real directo (Fase 2) — Diseño técnico

> Estado: **Propuesto, pendiente de aprobación** (2026-09-25). No hay código escrito.
> Origen: incidente del 2026-09-25 (ver "Evidencia"). Sigue el ciclo del Roadmap §2.1
> (Diseño técnico → Revisión y aprobación → Implementación → Validación).

## 1. Problema

Hoy el navegador abre su WebSocket contra una función de Vercel
(`/api/conversaciones/stream`), que abre otro WebSocket hacia Railway y reenvía lo que llega
(el "relay"). Esa función usa `experimental_upgradeWebSocket`, una API **beta** de Vercel.

Evidencia del 2026-09-25 (leída en Vercel y Railway, sin cambios hechos):

- `/api/conversaciones/stream` devolvió error 500 de forma continua: 98 errores en 30 min,
  "`experimental_upgradeWebSocket` no está disponible en el entorno de ejecución actual".
- En Railway, las conexiones a `/dashboard/ws` pasaron de una cada ~80 s a varias por minuto desde
  ~08:01 (abren y se caen).
- Cuota de Vercel Hobby (últimos 30 días): Memoria de Fluid aprovisionada 471 de 360 GB-h (131%);
  CPU activa 3 h 51 min de 4 h (96%). Los WebSockets de Vercel viven sobre Fluid y mantienen una
  función abierta todo el tiempo que la pestaña esté abierta.
- No hubo despliegues en Vercel (último: hace 16 h) ni reinicios en Railway.
- No está probado que la cuota sea la causa exacta del fallo; sí que el relay es frágil y caro.

## 2. Decisión propuesta

El navegador se conecta **directo** al WebSocket de Railway (`wss://<dominio-railway>/dashboard/ws`).
Vercel deja de participar en la conexión persistente y solo emite un **ticket** de un solo uso
(una llamada HTTP corta) para autenticarla.

Por qué hace falta un ticket: la sesión es una cookie firmada (`gaso_panel_sesion`) que el BFF copia
al dominio de Vercel. Un navegador **no envía** esa cookie a otro dominio (Railway). El panel legacy
no tiene este problema porque lo sirve el propio Railway (mismo origen); por eso ahí ya conecta directo.

## 3. Flujo

```
1. Navegador → POST /api/conversaciones/ticket        (Vercel, ~100 ms, con la cookie de sesión)
2. Vercel    → POST /dashboard/ws-ticket              (Railway; valida la sesión y el CSRF)
3. Railway   → { ticket, expira_en }                  (firmado, vence en 30 s, un solo uso)
4. Navegador → wss://railway/dashboard/ws             (Origin = dominio de Vercel)
5. Navegador → {"tipo":"auth","ticket":"..."}         (PRIMER mensaje; 5 s de plazo)
6. Railway   valida ticket + Origin → usuario/rol/negocio desde la base (igual que hoy) → conecta
7. Servidor  envía {"tipo":"latido"} cada 20 s; los eventos siguen igual (mensaje_nuevo, etc.)
8. Si se cae: pedir ticket nuevo y reconectar con backoff (lo que el hook ya hace)
```

## 4. Cambios por componente

**Backend (`agent/dashboard.py`, `agent/tiempo_real.py`)**
- `POST /dashboard/ws-ticket` (con sesión + CSRF, como el resto de POST del BFF): emite un ticket con
  `itsdangerous.URLSafeTimedSerializer` (ya es dependencia de Starlette), sal propia `ws-ticket`,
  payload `{username, jti}`. Vencimiento 30 s. `jti` de un solo uso (diccionario en memoria con
  limpieza; válido mientras haya **una** réplica).
- `websocket_panel`: aceptar dos formas de autenticarse — cookie de sesión (legacy, sin cambios) o
  primer mensaje `auth` con ticket (nuevo). Con ticket, exigir `Origin` presente y dentro de
  `FRONTEND_ORIGINS_PERMITIDOS`. Rol y negocio se leen SIEMPRE de la base por `username`, nunca del
  ticket. Sin `auth` en 5 s o ticket inválido → cerrar con 4401.
- Latido de aplicación cada 20 s a todas las conexiones (el navegador no ve los ping de protocolo).
  Se puede montar sobre el barrido periódico que ya existe (`_barrer_conexiones_ws_inactivas`).
- Soportar `{"tipo":"escribiendo"}` que ya existe; el navegador lo manda por su propio socket.

**BFF (`maiek-frontend/app/api`)**
- Nueva ruta `POST /api/conversaciones/ticket` (usa el `escribir()` existente: CSRF + cookie).
- Se retiran, en una segunda etapa, `stream/route.ts` (relay) y `escribiendo/route.ts`.

**Frontend (`hooks/use-conversacion-realtime.ts`)**
- Modo controlado por `NEXT_PUBLIC_REALTIME_MODE`: `directo` | `relay` | `off` (por defecto `relay`
  hasta validar; es también el interruptor de retroceso).
- En `directo`: pedir ticket → abrir `NEXT_PUBLIC_REALTIME_WS_URL` → enviar `auth` → mismo manejo de
  eventos, latido, backoff y `desplazada`/`sesion` que hoy.
- El sondeo de respaldo (15 s / 5 s sin tiempo real) **no cambia**: si el directo falla, el panel
  sigue funcionando como hoy.

## 5. Seguridad

- El ticket vive 30 s, es de un solo uso y no lleva rol ni negocio: robarlo no da más que abrir UNA
  conexión durante esa ventana, y solo desde un Origin permitido.
- Viaja en el primer mensaje, **no** en la URL, para no quedar en logs de proxies.
- `Origin` obligatorio y en lista blanca para el modo directo (el navegador no puede falsearlo desde
  una página ajena).
- Las reglas de acceso a conversaciones (`tiene_acceso_a_lead`, `negocio_id` de la sesión) no cambian.
- Se pierde la capa de firewall/DDoS de Vercel delante de este WebSocket; Railway ya expone
  públicamente el webhook y el panel legacy, así que no es una superficie nueva. Mitigación: ticket +
  Origin + límite de conexiones por usuario (ya existe: 3 por conversación).

## 6. Qué se pierde y qué se gana

Se pierde: un paso de autenticación extra por conexión; el firewall de Vercel sobre esa ruta; una
variable nueva en Vercel y mantener `FRONTEND_ORIGINS_PERMITIDOS`; y código nuevo que probar.

Se gana: sale de la cuota de Vercel el mayor consumidor (memoria/CPU de Fluid); desaparece la
dependencia de una API beta; la conexión deja de cortarse cada ~60–80 s; menos latencia (el navegador
va directo a Railway US West en vez de pasar por Vercel iad1); menos invocaciones (sin reintentos ni
ruta `escribiendo`).

## 7. Riesgos y supuestos (sin verificar)

- Que `FRONTEND_ORIGINS_PERMITIDOS` ya incluya el dominio de Vercel: **verificar** antes de codificar.
- Comportamiento del proxy de Railway con WebSockets inactivos: uvicorn envía ping cada 20 s por
  defecto; el latido de aplicación lo cubre. **Probar** con una conexión de 30+ min.
- Ticket de un solo uso en memoria: correcto con UNA réplica. Con más réplicas hay que moverlo a la
  base de datos.
- Un redeploy de Railway corta todas las conexiones a la vez (igual que hoy); el backoff las recupera.

## 8. Pruebas

Backend: ticket válido / vencido / reutilizado / con firma alterada; `auth` faltante en 5 s; Origin
ajeno; que el rol salga de la base y no del ticket; latido; compatibilidad con la cookie legacy.
Frontend: hook en modo `directo` (ticket, auth, reconexión con ticket nuevo, 401 → sesión expirada).
Manual: dos dispositivos, cerrar/abrir tapas, redeploy de Railway, 30 min de conexión.

## 9. Despliegue por etapas

1. Backend con ticket (compatible con lo actual) → suite → deploy.
2. Frontend con `NEXT_PUBLIC_REALTIME_MODE=relay` (sin cambio visible) → deploy.
3. Cambiar la variable a `directo` en Vercel → probar con tu usuario.
4. Si va bien 3–7 días: retirar el relay y la ruta `escribiendo`.
   Retroceso en cualquier momento: variable de vuelta a `relay` (o `off`).

## 10. Criterios de aceptación

Conexión estable > 30 min sin reconectar; mensaje nuevo visible en < 1 s; cero errores 500 en
`/api/conversaciones/*` por el tiempo real; consumo de Fluid de Vercel a la baja; un usuario sin
sesión válida no puede abrir la conexión.
