"""Estado de cada número de WhatsApp para el panel Canales (mejora #2, 2026-11-05).

Hoy el panel solo muestra nombre, modo, activo y la edad del token; no dice a qué número corresponde cada
canal, si Meta lo ve conectado, su calidad, a qué unidad pertenece ni cuándo llegó el último mensaje. Aquí se
junta todo en una sola respuesta para el admin:

- Datos que vienen de Meta (consulta en vivo `GET /{phone_number_id}` con el token del canal): número visible,
  nombre verificado, estado, calidad y límite de mensajes. Si Meta falla o el token no sirve, ese canal sale con
  `meta.ok = False` y un motivo corto; el resto del estado igual se muestra.
- Datos propios: unidad de negocio y fecha del último mensaje recibido (de clientes) por ese número.

Nunca se devuelve ni se registra el token. Cada consulta a Meta se guarda 60 s en memoria para que abrir y
cerrar el panel no multiplique llamadas."""
from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta

logger = logging.getLogger("agentkit")

API_VERSION = "v21.0"
CAMPOS_META = "display_phone_number,verified_name,quality_rating,status,name_status,messaging_limit_tier,platform_type"
CACHE_SEGUNDOS = 60
VENTANA_ULTIMO_MENSAJE_DIAS = 60

_cache: dict[str, tuple[float, dict]] = {}


def _motivo_corto(r) -> str:
    """Solo el código y el mensaje documentados del error de Meta, truncados. Nunca el cuerpo completo."""
    try:
        err = (r.json() or {}).get("error") or {}
    except Exception:
        err = {}
    codigo = err.get("code")
    msg = str(err.get("message") or "").strip()[:140]
    if codigo in (190, 102):
        return "El token del canal venció o fue revocado. Renuévalo en «Editar canal»."
    if codigo in (10, 200, 100) and not msg:
        return "Meta negó el acceso a este número (permisos)."
    return f"Meta respondió {r.status_code}" + (f" (código {codigo}: {msg})" if codigo else "")


async def consultar_meta(canal: dict, *, usar_cache: bool = True) -> dict:
    """Estado del número según Meta. Nunca lanza."""
    clave = str(canal["id"])
    ahora = time.monotonic()
    if usar_cache and clave in _cache and ahora - _cache[clave][0] < CACHE_SEGUNDOS:
        return _cache[clave][1]
    if not canal.get("access_token"):
        resultado = {"ok": False, "motivo": "El canal no tiene token guardado."}
    else:
        try:
            from agent.http_utils import get_con_reintentos
            r = await get_con_reintentos(
                f"https://graph.facebook.com/{API_VERSION}/{canal['phone_number_id']}",
                params={"fields": CAMPOS_META}, headers={"Authorization": f"Bearer {canal['access_token']}"},
            )
            if r.status_code != 200:
                resultado = {"ok": False, "motivo": _motivo_corto(r)}
            else:
                d = r.json() or {}
                resultado = {
                    "ok": True,
                    "numero": d.get("display_phone_number"),
                    "nombre_verificado": d.get("verified_name"),
                    "estado": d.get("status"),
                    "estado_nombre": d.get("name_status"),
                    "calidad": d.get("quality_rating"),
                    "limite": d.get("messaging_limit_tier"),
                    "plataforma": d.get("platform_type"),
                }
        except Exception as e:
            logger.warning("Estado de canal %s: no se pudo consultar a Meta (%s)", clave, type(e).__name__)
            resultado = {"ok": False, "motivo": "No se pudo contactar a Meta."}
    _cache[clave] = (ahora, resultado)
    return resultado


async def ultimos_mensajes_por_numero(negocio_id: str, ahora: datetime | None = None) -> dict[str, datetime]:
    """`{phone_number_id: momento del último mensaje de un cliente}` de los últimos 60 días. El número por el que
    habla cada cliente es `Lead.numero_whatsapp_id`; un cliente que cambió de número cuenta en el actual."""
    from sqlalchemy import func, select
    from agent import memory as mem

    desde = (ahora or datetime.utcnow()) - timedelta(days=VENTANA_ULTIMO_MENSAJE_DIAS)
    async with mem.async_session() as session:
        filas = (await session.execute(
            select(mem.Lead.numero_whatsapp_id, func.max(mem.Mensaje.timestamp))
            .join(mem.Lead, mem.Lead.telefono == mem.Mensaje.telefono)
            .where(
                mem.Lead.negocio_id == negocio_id, mem.Mensaje.negocio_id == negocio_id, mem.Lead.numero_whatsapp_id.is_not(None),
                mem.Mensaje.role == "user", mem.Mensaje.timestamp >= desde,
            )
            .group_by(mem.Lead.numero_whatsapp_id)
        )).all()
    return {numero: momento for numero, momento in filas}


def armar_canal(canal: dict, meta: dict, unidades: dict[str, str], ultimos: dict[str, datetime], iso) -> dict:
    ultimo = ultimos.get(canal["phone_number_id"])
    return {
        "id": canal["id"], "nombre": canal["nombre"], "activo": canal["activo"], "modo": canal.get("modo", "produccion"),
        "unidad": unidades.get(canal.get("unidad_id") or "") or None,
        "ultimo_mensaje_recibido": iso(ultimo) if ultimo else None,
        "meta": meta,
    }


async def estado(negocio_id: str, iso, *, usar_cache: bool = True) -> list[dict]:
    import asyncio
    from agent import memory as mem

    canales = await mem.listar_canales_whatsapp(negocio_id=negocio_id)
    unidades = {u["id"]: u["nombre"] for u in await mem.listar_unidades_de_negocio(negocio_id)}
    ultimos = await ultimos_mensajes_por_numero(negocio_id)
    metas = await asyncio.gather(*(consultar_meta(c, usar_cache=usar_cache) for c in canales))
    return [armar_canal(c, m, unidades, ultimos, iso) for c, m in zip(canales, metas)]
