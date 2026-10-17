# agent/memory.py — Memoria de conversaciones con SQLite
# Generado por AgentKit

"""
Sistema de memoria del agente. Guarda el historial de conversaciones
por número de teléfono usando SQLite (local) o PostgreSQL (producción).
"""

import os
import csv
import uuid
import logging
import asyncio
import re
import time
import unicodedata
from urllib.parse import urlparse
# `time` (el módulo, ya importado arriba para time.perf_counter) choca de
# nombre con datetime.time (la clase de hora del día) — se importa aparte
# con alias, mismo motivo que cualquier otro alias de este archivo.
from datetime import date, datetime, timedelta, time as hora_del_dia
from cryptography.fernet import Fernet
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, aliased
from sqlalchemy import (
    String, Text, DateTime, Date, select, Integer, Boolean, Float, func, case, delete, update, JSON,
    ForeignKey, Index, text, and_ as sa_and, or_ as sa_or, exists as sa_exists,
)
from sqlalchemy.exc import IntegrityError
from dotenv import load_dotenv

from agent import calendario_negocio as cal_negocio

load_dotenv()
logger = logging.getLogger("agentkit")

_fernet: Fernet | None = None


def _obtener_fernet() -> Fernet:
    """Carga (una sola vez) la clave de cifrado usada para access_token/app_secret
    de los canales de WhatsApp guardados en la base de datos — a diferencia del
    resto de credenciales del proyecto (que viven solo en variables de entorno
    de Railway), estos tokens SÍ quedan persistidos en la BD para que se
    administren desde el panel, así que se cifran en reposo por si alguien
    llegara a tener acceso a la base sin tener también esta clave."""
    global _fernet
    if _fernet is None:
        clave = os.getenv("CANAL_ENCRYPTION_KEY")
        if not clave:
            raise RuntimeError(
                "CANAL_ENCRYPTION_KEY no está configurado — es obligatorio para "
                "guardar/leer canales de WhatsApp desde el panel."
            )
        _fernet = Fernet(clave.encode())
    return _fernet


def _cifrar(texto: str | None) -> str | None:
    if not texto:
        return None
    return _obtener_fernet().encrypt(texto.encode()).decode()


def _descifrar(texto_cifrado: str | None) -> str | None:
    if not texto_cifrado:
        return None
    return _obtener_fernet().decrypt(texto_cifrado.encode()).decode()


def iso_utc(valor):
    """Serializa a ISO 8601 DECLARANDO la zona (sufijo `Z`) un instante real
    guardado con `datetime.utcnow()` (naive, ya en UTC). Sin el sufijo,
    `new Date()` en el navegador interpreta la cadena como hora LOCAL y un
    usuario en Lima ve todo ~5 h adelantado.

    Vive acá, en la capa que importan tanto dashboard.py como los
    serializadores de Productos de este mismo archivo, por el mismo motivo que
    RESULTADOS_CERRADOS: para no duplicar la regla ni arriesgar que se
    desincronicen (antes estaba copiada dentro de _dto_lead_pipeline y
    _dto_lead_detalle).

    OJO: aplicar SOLO a instantes reales. Un campo como `fecha_agendada` —la
    hora de una cita tal como la tipeó un humano en su propia zona, vía
    `<input type=datetime-local>`— NO es un instante en UTC y envolverlo en `Z`
    lo corrompería; ese caso usa `.isoformat()` pelado."""
    return valor.isoformat() + "Z" if isinstance(valor, datetime) else valor


# Configuración de base de datos
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./agentkit.db")

# Si es PostgreSQL en producción, ajustar el esquema de URL
if DATABASE_URL.startswith("postgresql://"):
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://", 1)

# Pool de conexiones (2026-09-24). Con el default de SQLAlchemy (5 conexiones
# retenidas + 10 de desborde) cada pedido concurrente por encima de 5 abre una
# conexión NUEVA y la cierra al terminar: medido en producción, un paso trivial
# como resolver el canal tardaba ~405 ms (constante) cuando la base estaba
# ocupada y 6-8 ms cuando no — el costo de abrir la conexión, no de la consulta
# (un viaje a una conexión abierta cuesta ~2 ms). Varias pantallas sondeando en
# el mismo segundo más los webhooks superan fácil las 5. Solo Postgres: SQLite
# (desarrollo y tests) usa otro pool y no admite estos parámetros.
def _argumentos_engine(url: str) -> dict:
    args: dict = {"echo": False}
    if url.startswith("postgresql"):
        # pool_pre_ping: si Postgres se reinicia (deploy, mantenimiento de
        # Railway), las conexiones que el pool guardaba quedan rotas; sin esto
        # los primeros pedidos fallan con "connection reset". Con la red
        # privada el chequeo previo cuesta ~1 ms.
        args.update(pool_size=10, max_overflow=20, pool_recycle=1800, pool_pre_ping=True)
    return args


engine = create_async_engine(DATABASE_URL, **_argumentos_engine(DATABASE_URL))
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

# Resultados que cierran un lead (ya no se le hace seguimiento) — se usa acá
# (no solo en dashboard.py) porque main.py también necesita saber cuándo un
# lead está cerrado, para decidir si Gabi retoma la conversación cuando el
# cliente vuelve a escribir. Vive en memory.py, la capa que ambos importan,
# para no duplicar la lista ni arriesgar que se desincronicen.
RESULTADOS_CERRADOS = (
    "vendido", "no_interesado", "no_califica", "no_es_cliente_calidda", "otro", "consulta_atc",
    "servicio_postventa", "cartera_fnb", "sin_respuesta",
)

# Roles con visión total del panel (ven/editan cualquier lead, no solo los
# suyos) — vive acá, no en dashboard.py, por el mismo motivo que
# RESULTADOS_CERRADOS: agent/tiempo_real.py (el WebSocket) necesita el
# MISMO criterio para filtrar a quién emitirle un evento (ver
# tiene_acceso_a_lead), y no puede importar dashboard.py sin crear un ciclo
# (dashboard.py ya importa tiempo_real.py para el gestor de conexiones).
# dashboard.py importa esta constante en vez de definir la suya — antes
# eran dos copias del mismo valor, con riesgo real de desincronizarse.
ROLES_CON_VISION_TOTAL = ("admin", "supervisor")


def tiene_acceso_a_lead(rol: str, username: str, asesor_asignado: str | None) -> bool:
    """Regla única de acceso a un lead: admin/supervisor ven todo, un
    asesor solo el suyo. Es la misma regla que ya aplicaban los endpoints
    de lectura del panel (antes inline como `_verificar_acceso_lead` en
    dashboard.py, ahora una llamada a esta función) — se extrae acá para
    que agent/tiempo_real.py pueda aplicarla también al decidir a qué
    conexiones WebSocket emitirles un evento de un lead (antes se emitía a
    TODAS las conexiones sin filtrar, exponiendo el teléfono de leads
    ajenos a cualquier miembro del equipo conectado al panel)."""
    return rol in ROLES_CON_VISION_TOTAL or asesor_asignado == username


class Base(DeclarativeBase):
    pass


def _generar_uuid() -> str:
    """UUID como String(36) — portable entre SQLite (dev) y Postgres (prod)
    sin depender del tipo UUID nativo de un dialecto (Gate 5.2, Arquitectura
    Contractual §3: nombre técnico de contrato `Negocio`/`negocio_id`, UUID
    como PK sustituta de toda entidad nueva)."""
    return str(uuid.uuid4())


class Negocio(Base):
    """Entidad fundacional de aislamiento Multi-Tenant (Gate 5.2 — Fundación
    Negocio/Unidad, Arquitectura Contractual §3/§22 Data Architecture v1).
    "Tenant" sigue siendo el concepto SaaS de producto; `Negocio`/`negocio_id`
    es el nombre técnico de contrato, sin excepción. Cálidda es el primer
    Negocio real (backfill, ver migración) — no hay nada en este modelo que
    lo trate como caso especial."""
    __tablename__ = "negocios"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_generar_uuid)
    nombre: Mapped[str] = mapped_column(String(150))
    codigo: Mapped[str] = mapped_column(String(30), unique=True, index=True)
    activo: Mapped[bool] = mapped_column(Boolean, default=True)
    eliminado_en: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    eliminado_por: Mapped[str | None] = mapped_column(String(50), nullable=True)
    creado: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    actualizado: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class UnidadDeNegocio(Base):
    """Dimensión de alcance bajo un Negocio (Gate 5.1, §4 — no es módulo de
    producto, no hay enumeración global). Los nombres reales de las Unidades
    de cada Negocio son dato de negocio, nunca hardcodeados acá. `codigo_interno`
    queda deliberadamente desacoplado del nombre visible (ver colisión "FNB"
    documentada en el Blueprint de Gate 5.0)."""
    __tablename__ = "unidades_de_negocio"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_generar_uuid)
    negocio_id: Mapped[str] = mapped_column(String(36), ForeignKey("negocios.id"), nullable=False, index=True)
    nombre: Mapped[str] = mapped_column(String(150))
    codigo_interno: Mapped[str] = mapped_column(String(30))
    activo: Mapped[bool] = mapped_column(Boolean, default=True)
    eliminado_en: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    eliminado_por: Mapped[str | None] = mapped_column(String(50), nullable=True)
    creado: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    actualizado: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        Index("ix_unidad_negocio_codigo", "negocio_id", "codigo_interno", unique=True),
    )


class RegistroAuditoria(Base):
    """Esqueleto append-only (Gate 5.2, alcance explícitamente limitado a la
    fundación — sin dashboard, sin alertas, sin análisis todavía, ver
    Arquitectura Contractual §8). Ningún código de esta capa ejecuta UPDATE
    ni DELETE sobre esta tabla: se agregan filas nuevas únicamente, nunca se
    modifican ni se borran (Data Architecture v1, decisión ya Approved)."""
    __tablename__ = "registro_auditoria"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_generar_uuid)
    # Nullable: un evento de plataforma (sin Negocio asociado) es válido —
    # ej. una acción de un futuro superadmin de Maiek AI, fuera del alcance
    # de este Gate pero contemplado por el propio contrato de Data Architecture.
    negocio_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("negocios.id"), nullable=True, index=True)
    # Username de Usuario (String suelto, sin FK — mismo criterio ya usado en
    # el resto del esquema para `asesor_asignado`/`autor`: el registro
    # histórico no debe cambiar si el actor se borra o se renombra después).
    # None si la acción fue automática (sistema/Gabi), no de un humano.
    actor: Mapped[str | None] = mapped_column(String(50), nullable=True)
    accion: Mapped[str] = mapped_column(String(50))
    entidad_tipo: Mapped[str | None] = mapped_column(String(50), nullable=True)
    entidad_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    creado: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)

    __table_args__ = (
        Index("ix_auditoria_negocio_entidad", "negocio_id", "entidad_tipo", "entidad_id"),
    )


async def registrar_auditoria(
    accion: str, actor: str | None = None, negocio_id: str | None = None,
    entidad_tipo: str | None = None, entidad_id: str | None = None, payload: dict | None = None,
) -> str:
    """Único punto de escritura de RegistroAuditoria — append-only, sin
    UPDATE/DELETE en ningún llamador (Gate 5.2, esqueleto base). Devuelve el id
    de la fila (los llamadores existentes lo ignoran)."""
    fila_id = _generar_uuid()
    async with async_session() as session:
        session.add(RegistroAuditoria(
            id=fila_id, accion=accion, actor=actor, negocio_id=negocio_id,
            entidad_tipo=entidad_tipo, entidad_id=entidad_id, payload=payload,
        ))
        await session.commit()
    return fila_id


def _negocio_a_dict(n: "Negocio") -> dict:
    return {
        "id": n.id, "nombre": n.nombre, "codigo": n.codigo, "activo": n.activo,
        "creado": n.creado, "actualizado": n.actualizado,
    }


async def crear_negocio(nombre: str, codigo: str) -> dict:
    """Crea un Negocio nuevo. `codigo` es el slug único (Arquitectura
    Contractual §3) — nunca se genera automáticamente a partir del nombre
    acá, para no inventar convenciones que el propietario del negocio no
    definió explícitamente."""
    async with async_session() as session:
        negocio = Negocio(nombre=nombre, codigo=codigo)
        session.add(negocio)
        await session.commit()
        await session.refresh(negocio)
        return _negocio_a_dict(negocio)


async def obtener_negocio(negocio_id: str) -> dict | None:
    async with async_session() as session:
        negocio = await session.get(Negocio, negocio_id)
        return _negocio_a_dict(negocio) if negocio else None


async def actualizar_negocio(negocio_id: str, nombre: str) -> dict | None:
    """Edición administrativa del Negocio — Gate 4.5. Solo `nombre`: `codigo`
    es el slug estable ya usado como identidad de aislamiento (ej.
    `knowledge/<codigo>/`) y no se expone como editable acá para no romper
    esas referencias; `activo` es administración de plataforma (alta/baja
    de un Negocio entero), no una preferencia de configuración del propio
    negocio. `None` si el Negocio no existe — no se crea uno a ciegas."""
    async with async_session() as session:
        negocio = await session.get(Negocio, negocio_id)
        if negocio is None:
            return None
        negocio.nombre = nombre
        negocio.actualizado = datetime.utcnow()
        await session.commit()
        await session.refresh(negocio)
        return _negocio_a_dict(negocio)


async def obtener_negocio_por_codigo(codigo: str) -> dict | None:
    async with async_session() as session:
        query = select(Negocio).where(Negocio.codigo == codigo)
        resultado = await session.execute(query)
        negocio = resultado.scalar_one_or_none()
        return _negocio_a_dict(negocio) if negocio else None


async def listar_negocios(solo_activos: bool = False) -> list[dict]:
    async with async_session() as session:
        query = select(Negocio).order_by(Negocio.creado.asc())
        if solo_activos:
            query = query.where(Negocio.activo.is_(True))
        resultado = await session.execute(query)
        return [_negocio_a_dict(n) for n in resultado.scalars().all()]


def _unidad_a_dict(u: "UnidadDeNegocio") -> dict:
    return {
        "id": u.id, "negocio_id": u.negocio_id, "nombre": u.nombre,
        "codigo_interno": u.codigo_interno, "activo": u.activo,
        "creado": u.creado, "actualizado": u.actualizado,
    }


async def crear_unidad_de_negocio(negocio_id: str, nombre: str, codigo_interno: str) -> dict:
    """Crea una Unidad de Negocio nueva bajo un Negocio. Los nombres reales
    de las Unidades son dato de negocio — esta función nunca decide qué
    Unidades crear, solo persiste las que el propietario del negocio ya
    definió."""
    async with async_session() as session:
        unidad = UnidadDeNegocio(negocio_id=negocio_id, nombre=nombre, codigo_interno=codigo_interno)
        session.add(unidad)
        await session.commit()
        await session.refresh(unidad)
        return _unidad_a_dict(unidad)


async def listar_unidades_de_negocio(negocio_id: str, solo_activas: bool = False) -> list[dict]:
    async with async_session() as session:
        query = select(UnidadDeNegocio).where(UnidadDeNegocio.negocio_id == negocio_id).order_by(UnidadDeNegocio.creado.asc())
        if solo_activas:
            query = query.where(UnidadDeNegocio.activo.is_(True))
        resultado = await session.execute(query)
        return [_unidad_a_dict(u) for u in resultado.scalars().all()]


class Mensaje(Base):
    """Modelo de mensaje en la base de datos."""
    __tablename__ = "mensajes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # 150, no 50 — un BSUID (Business-Scoped User ID de Meta, Gate 2026-09-22)
    # puede tener hasta 128 caracteres, más largo que un teléfono real.
    telefono: Mapped[str] = mapped_column(String(150), index=True)
    role: Mapped[str] = mapped_column(String(20))  # "user" o "assistant"
    content: Mapped[str] = mapped_column(Text)
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    # Si este mensaje fue un archivo adjunto (proforma o catálogo) enviado por
    # un asesor, referencia al registro en ArchivoAdjunto — content queda como
    # el caption/nombre visible igual. Sin ForeignKey estricta, mismo criterio
    # que asesor_asignado en Lead (String suelto en vez de FK).
    archivo_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # True si este mensaje llegó por el webhook smb_message_echoes de
    # coexistencia (un asesor lo mandó directo desde la app de WhatsApp
    # Business en el celular, no desde Gabi ni desde el panel). Meta no
    # informa QUÉ asesor lo escribió — solo que salió de la app — así que no
    # se puede atribuir a una persona específica, solo marcar el origen.
    via_app: Mapped[bool] = mapped_column(Boolean, default=False)
    # wamid real de WhatsApp (el "id" que Meta asigna a cada mensaje). Para
    # ENTRANTES se captura del webhook (MensajeEntrante.mensaje_id); para
    # SALIENTES, del campo `messages[0].id` que Meta devuelve en la
    # respuesta 200 del POST de envío (ver agent/providers/meta.py). Vive
    # acá — no en una tabla aparte — porque es un atributo del mensaje
    # mismo, con el mismo criterio que archivo_id/via_app. Nullable: el
    # historial anterior a este campo no lo tiene, y un envío que falló
    # tampoco genera uno. Habilita citar un mensaje (Reply/Quote, payload
    # saliente `"context": {"message_id": ...}`) — si el mensaje que se
    # quiere citar no tiene este campo, la cita se rechaza explícitamente
    # (ver responder_cliente en dashboard.py) en vez de mandarle a Meta un
    # context inválido.
    mensaje_id_meta: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)  # índice: se cruza con uso_mensajes_meta.wamid
    # "fallido" cuando un envío SALIENTE no se pudo confirmar con Meta
    # (status distinto de 200, o falla de red) — a diferencia del
    # comportamiento anterior (no guardar nada si el envío fallaba), el
    # mensaje se persiste igual con este estado para que el frontend lo
    # muestre con opción de reintento en vez de perderlo en silencio.
    # None/ausente = se envió con normalidad, o es un mensaje entrante
    # (este campo no aplica ahí). Deliberadamente el único estado que
    # existe hoy — este Gate no necesita distinguir más que "falló" del
    # resto.
    estado_envio: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # Id INTERNO (Mensaje.id, NO el wamid) del mensaje que ESTE mensaje citó
    # al enviarse (Reply/Quote) — se completa en responder_cliente cuando el
    # request trae mensaje_id_citado. Mismo criterio que mensaje_id_citado:
    # se guarda el id interno, nunca el wamid — el wamid se resuelve contra
    # este id solo cuando hace falta mandárselo a Meta. Sin ForeignKey
    # estricta, mismo criterio que archivo_id arriba (relación validada en
    # la capa de aplicación, no en la base). Nullable: la mayoría de los
    # mensajes no citan nada, y el historial anterior a este campo tampoco.
    respondido_a_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Gate 5.2 — aislamiento estructural: se resuelve por fila propia (vía
    # Lead.negocio_id al momento de guardar el mensaje, ver
    # guardar_mensaje/corrección H1), nunca por JOIN indirecto contra
    # `telefono` en cada query (Arquitectura Contractual §15: "ninguna
    # entidad de negocio se filtra por JOIN indirecto"). Sin FK estricta
    # hacia Negocio por el mismo motivo que archivo_id/respondido_a_id.
    # NOT NULL a nivel de BD tras el backfill (migración a46a93329345) — el
    # modelo debe reflejar eso mismo (corrección post-auditoría: antes decía
    # nullable=True, desalineado con la migración real, lo que dejaba que
    # los tests contra create_all() no detectaran la regresión de H1).
    negocio_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    # Gate 5.3 — EXPAND: nullable hasta que el backfill (M3) lo pueble para
    # todo el histórico; CONTRACT lo deja NOT NULL. Mensajes nuevos lo
    # resuelven en el punto de escritura (ver guardar_mensaje), nunca por
    # JOIN posterior. Sin ForeignKey estricta, mismo criterio ya vigente
    # para archivo_id/respondido_a_id en esta misma tabla.
    conversation_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)


class ArchivoAdjunto(Base):
    """Archivo subido por un asesor para enviar por WhatsApp — proforma
    puntual (reutilizable=False, ligada a un solo envío) o catálogo de la
    librería reutilizable (reutilizable=True, se puede mandar en cualquier
    conversación sin volver a subirlo). El contenido vive en el volumen
    persistente de Railway (ver ARCHIVOS_DIR en dashboard.py) — acá solo se
    guardan los metadatos y la ruta en disco.

    `negocio_id` es el dueño tenant de un catálogo reutilizable — nunca
    compartido entre negocios (hallazgo de aislamiento cerrado en este
    Gate). Nullable a nivel de tabla porque las proformas (reutilizable=
    False) siguen aisladas de forma indirecta vía
    Mensaje.archivo_id → Mensaje.telefono → Lead.negocio_id
    (test_gate55_archivo_cross_tenant.py) y no reciben negocio_id directo.
    La garantía real ("todo reutilizable tiene negocio_id") la impone el
    CHECK constraint `ck_archivos_adjuntos_reutilizable_negocio`, no un
    NOT NULL de columna completa. `subido_por` sigue siendo solo metadato
    de auditoría — nunca el mecanismo de aislamiento."""
    __tablename__ = "archivos_adjuntos"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    nombre_original: Mapped[str] = mapped_column(String(255))
    ruta_disco: Mapped[str] = mapped_column(String(500))
    content_type: Mapped[str] = mapped_column(String(100))
    tamano_bytes: Mapped[int] = mapped_column(Integer)
    reutilizable: Mapped[bool] = mapped_column(Boolean, default=False)
    # Nombre visible en la librería de catálogos — solo aplica si reutilizable
    etiqueta: Mapped[str | None] = mapped_column(String(150), nullable=True)
    subido_por: Mapped[str] = mapped_column(String(50))
    negocio_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("negocios.id"), nullable=True, index=True
    )
    creado: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Lead(Base):
    """Datos estructurados del cliente (nombre, interés, paso del flujo),
    independientes del historial crudo de mensajes. Así, aunque el historial
    se trunque o se pierda contexto entre turnos, estos datos clave persisten."""
    __tablename__ = "leads"

    # 150, no 50 — ver Mensaje.telefono (BSUID de Meta, Gate 2026-09-22).
    telefono: Mapped[str] = mapped_column(String(150), primary_key=True)
    nombre: Mapped[str | None] = mapped_column(String(100), nullable=True)
    interes: Mapped[str | None] = mapped_column(String(200), nullable=True)
    # Desglose estructurado del interés (además del texto libre de arriba,
    # que la IA sigue usando para buscar en el catálogo) — para poder
    # filtrar/reportar en el panel sin depender de texto libre.
    producto_tipo: Mapped[str | None] = mapped_column(String(50), nullable=True)
    producto_marca: Mapped[str | None] = mapped_column(String(50), nullable=True)
    producto_modalidad: Mapped[str | None] = mapped_column(String(20), nullable=True)  # combo | solo
    paso_flujo: Mapped[str | None] = mapped_column(String(50), nullable=True)
    # Resultado tras la derivación a un asesor humano — se llena manualmente
    # (equipo comercial) mientras no exista integración automática con Genesys.
    resultado: Mapped[str | None] = mapped_column(String(50), nullable=True)
    # Solo aplica si resultado == "agendado" — fecha/hora de la cita con el cliente
    fecha_agendada: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # Instante REAL (UTC) en que el lead pasó a "vendido" por primera vez —
    # se escribe una sola vez, en la transición (ver _es_transicion_a_vendido),
    # no en cada guardado de una venta que ya estaba vendida, para que la
    # métrica "cuándo se cerró" no se corra sola cada vez que alguien edita el
    # carrito. A diferencia de `fecha_agendada` (hora de una cita tal como la
    # tipeó un humano), esto SÍ es un instante y se serializa con iso_utc().
    # Nullable: los cierres anteriores a este campo no tienen el dato.
    fecha_cierre: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # Asesor al que el supervisor asignó este lead (username de Usuario) —
    # indexado: listar_leads, contar_leads_activos_por_asesor y
    # listar_leads_agendados filtran por esta columna en cada carga de
    # página, y sin índice eso se vuelve una revisión completa de la tabla
    # a medida que se acumulan leads reales.
    asesor_asignado: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)
    # Cierre de venta (si resultado == "vendido") — SUPERADOS por la tabla
    # LineaVenta (un lead puede vender varios artefactos o un mix de
    # artefacto + servicio, no solo uno). Se dejan sin usar en vez de
    # borrarse para no perder el histórico de ventas cerradas antes de
    # este cambio; el código nuevo lee/escribe siempre en LineaVenta.
    producto_vendido: Mapped[str | None] = mapped_column(String(300), nullable=True)
    precio_venta: Mapped[str | None] = mapped_column(String(30), nullable=True)
    marca_venta: Mapped[str | None] = mapped_column(String(100), nullable=True)
    proveedor_venta: Mapped[str | None] = mapped_column(String(150), nullable=True)
    modalidad_pago: Mapped[str | None] = mapped_column(String(30), nullable=True)  # financiado | contado
    # Solo aplica si modalidad_pago == "financiado" (plazo en meses: 12/24/36)
    cuotas: Mapped[str | None] = mapped_column(String(10), nullable=True)
    # Pacto de financiamiento CONGELADO al cerrar la venta (Gate 2026-09-23):
    # monto financiado, cuota mensual pactada y la TEA/IGV vigentes en ese
    # momento. Cambiar la tasa del negocio después NO los toca — solo aplica a
    # financiamientos nuevos. Ver ServicioComercial.calcular_pacto_financiamiento.
    monto_financiado: Mapped[str | None] = mapped_column(String(30), nullable=True)
    cuota_pactada: Mapped[str | None] = mapped_column(String(30), nullable=True)
    tea_pactada: Mapped[str | None] = mapped_column(String(10), nullable=True)
    igv_pactado: Mapped[str | None] = mapped_column(String(10), nullable=True)
    # Si financiado: siempre "Recibo de gas" (única opción). Si contado: el
    # canal que eligió el asesor (QR, Link de pago, Abono a cta cte, Otro).
    medio_pago: Mapped[str | None] = mapped_column(String(50), nullable=True)
    # False mientras el asesor asignado no haya abierto la conversación —
    # se usa para mostrar el indicador de "Nuevo" en su bandeja.
    visto_asesor: Mapped[bool] = mapped_column(Boolean, default=True)
    # Fallas técnicas consecutivas de Gabi (API caída, etc.) — a la segunda,
    # se escala automáticamente a un asesor en vez de seguir reintentando.
    fallos_tecnicos: Mapped[int] = mapped_column(Integer, default=0)
    # Campaña de origen (nombre de Campana) — se captura UNA sola vez, en el
    # primer contacto, y nunca se sobreescribe. Sirve para medir conversión
    # por campaña en el panel.
    campana_origen: Mapped[str | None] = mapped_column(String(100), nullable=True)
    # Cómo llegó este lead: None/"" = escribió por WhatsApp orgánicamente
    # (el caso de siempre). "formulario_meta" = llenó un Lead Ad/Instant
    # Form de Meta y nunca escribió — Gaso+ tuvo que iniciar la conversación
    # con una plantilla aprobada. Sirve para reportar y para no reenviar esa
    # plantilla si el mismo teléfono ya es un lead conocido.
    origen_contacto: Mapped[str | None] = mapped_column(String(30), nullable=True)
    # phone_number_id (de Meta) del número de WhatsApp del NEGOCIO por el que
    # entró/se atiende esta conversación — permite tener varios números
    # activos a la vez (ej. pruebas y producción) y responder siempre por el
    # mismo canal. Se actualiza con cada mensaje entrante (ver main.py), no
    # solo la primera vez, por si el cliente llegara a escribir a otro número.
    numero_whatsapp_id: Mapped[str | None] = mapped_column(String(50), nullable=True)
    # True si un asesor le respondió a este lead directo desde la app de
    # WhatsApp Business en el celular (coexistencia), SIN pasar por una
    # asignación formal en el panel — pausa a Gabi igual que asesor_asignado,
    # para que no choquen respuestas, aunque no sepamos qué asesor fue. Se
    # limpia junto con asesor_asignado al liberar la asignación (ver
    # liberar_asignacion). paso_flujo también se marca "derivado_asesor" al
    # activarse, así el caso aparece en listar_leads_esperando_asesor() para
    # que un supervisor lo reclame y lo asigne a una persona real.
    pausado_manual: Mapped[bool] = mapped_column(Boolean, default=False)
    # Instante (UTC) en que el caso quedó cerrado DE VERDAD — distinto de
    # `resultado` (que sigue siendo solo el dato de CRM/reporting). Mientras
    # esto sea None, un `resultado` cerrado NUNCA reactiva a Gabi por sí
    # solo (Gate 2026-09-23, hallazgo real: un asesor de OTRO tema le
    # escribía al cliente sobre un caso ya con resultado="consulta_atc", y
    # el siguiente mensaje del cliente reactivaba a Gabi sin que ese asesor
    # se enterara). Se setea de dos formas: manual (botón "Cerrar
    # definitivamente" en la Ficha del Lead — solo visible con resultado ya
    # cerrado) o automático (scripts/cerrar_leads_definitivamente.py, 7
    # días sin mensaje del cliente sobre un resultado cerrado). "vendido"
    # nunca lo setea (Close-Won es indefinido, mismo criterio que
    # pausado_manual de una venta). Se limpia junto con asesor_asignado y
    # pausado_manual al liberar la asignación (ver liberar_asignacion) — un
    # cierre ya consumido no debe seguir marcado.
    cerrado_definitivamente_en: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # Punto 2 (2026-09-29, rediseñado tras el incidente del mismo día —
    # ver `listar_leads_para_rotar_o_liberar`) — rotación por inactividad
    # del asesor. `derivado_en` es un timestamp de EVENTO, no de contenido:
    # se arma (pone la hora actual) SOLO cuando `asignar_asesor_a_lead`
    # asigna automáticamente (Gabi deriva, o la rotación pasa al segundo
    # asesor) y se desarma (vuelve a None) apenas el asesor responde
    # (`guardar_mensaje` con role="asesor" o el echo de coexistencia) o
    # apenas una persona reasigna a mano (`asignar_asesor_a_lead`,
    # automatico=False — "ya el lead es de esa persona", nunca se
    # segunda-adivina una decisión humana). Mientras esté en None, el cron
    # ni siquiera considera el lead — así un resultado que se reabre sobre
    # un mensaje viejo NUNCA vuelve a arrancar un conteo (el incidente real:
    # un asesor limpió un resultado de hace 10 días y el lead se rotó y
    # liberó solo, dos veces, sobre un mensaje que ya nadie iba a responder).
    minutos_espera_asesor: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    # 0 = todavía con el asesor original; 1 = ya rotó una vez (al segundo
    # asesor) — a los 30 min de turno SIN respuesta en ese estado, se libera
    # en vez de rotar de nuevo (ver diseño: 30 min + 30 min, no una cadena
    # infinita de asesores).
    veces_rotado_espera: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    derivado_en: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # 2026-10-04 — el lead pasó a la COLA DE SUPERVISIÓN: dos asesores seguidos
    # no respondieron en su turno (o no había otro asesor disponible). Gabi NO
    # lo retoma (`pausado_manual=True`, sin asesor) y tampoco se reasigna solo
    # al primer asesor que se ponga "disponible": lo trata un supervisor. Se
    # apaga al asignarlo a alguien o al devolverlo a Gabi a mano.
    escalado_supervision_en: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # True cuando la IA respondió con confianza "Requiere validación"
    # (protocolo de confianza, AI Architecture Sec.6) — no transfiere la
    # conversación, solo marca que un asesor debería revisarla con
    # prioridad. Se limpia cuando alguien del equipo abre el detalle del
    # lead (ver limpiar_revision_prioritaria).
    revision_prioritaria: Mapped[bool] = mapped_column(Boolean, default=False)
    # Concurrencia optimista (MAIEK_AI_PRODUCT_PATTERNS.md, Cap. 6 — conflicto
    # de edición): se incrementa SOLO en las 3 escrituras humanas del CRM
    # (resultado, venta, asignación), no en las automáticas de Gabi — a
    # propósito distinto de `actualizado` (que sí se pisa en cada mensaje
    # entrante y generaría conflictos falsos si se usara para esto). Ver
    # intentar_avanzar_version().
    version: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    # Indexado: listar_leads ordena por esta columna en CADA carga del
    # dashboard (la vista más visitada del panel) — sin índice, ordenar se
    # vuelve más lento a medida que se acumulan leads reales.
    actualizado: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, index=True)
    creado: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    # Gate 5.2 — Lead es HOY la entidad que contiene los datos reales de
    # Cálidda; la separación Contact/Conversation/Opportunity es Gate 5.3 y
    # NO se adelanta acá. PK de Lead (telefono) NO se modifica en este Gate.
    # NOT NULL a nivel de BD tras el backfill (migración a46a93329345, 100%
    # inequívoco contra la BD local) — el modelo debe reflejar eso mismo, no
    # `nullable=True` (corrección post-auditoría: el desfase entre modelo y
    # migración real era la causa raíz de que los tests con create_all() no
    # detectaran H2 — actualizar_lead() ahora exige negocio_id explícito
    # para crear un Lead nuevo, ver `_requiere_negocio_id_para_lead_nuevo`).
    negocio_id: Mapped[str] = mapped_column(String(36), ForeignKey("negocios.id"), nullable=False, index=True)


TIPO_EVENTO_LARGO_MAX = 60  # ver migración d4b7a1c93e52 (antes 30: dos tipos automáticos no cabían en Postgres)

# Triaje de temas no comerciales → Consulta ATC (2026-10-08, agent/triaje_atc.py).
#   · `triaje_atc_cerrado`: el triaje cerró el caso (visible en el Timeline: es una decisión de negocio).
#   · `triaje_atc_sombra`: la decisión que tomó el triaje cuando había un candidato (modo sombra o activo),
#     para medir recall/precisión en SQL (scripts/analisis_triaje_atc.py).
#   · `triaje_atc_fallido`: el triaje quiso cerrar pero el envío no salió (cuenta como el triaje del ciclo).
# Los dos últimos son INTERNOS: `listar_eventos_lead` no los entrega, así no aparecen como ruido en el
# Timeline del panel (ni cuentan como "último cambio" para el aviso de conflicto de edición).
EVENTO_TRIAJE_ATC_CERRADO = "triaje_atc_cerrado"
EVENTO_TRIAJE_ATC_SOMBRA = "triaje_atc_sombra"
EVENTO_TRIAJE_ATC_FALLIDO = "triaje_atc_fallido"
# Emergencia de gas (2026-10-09): el cliente reportó olor o fuga de gas y se le derivó a Emergencias de Cálidda.
# VISIBLE en el Timeline (deja al equipo enterado sin consumir asesor); también es la marca de "ya se avisó".
EVENTO_EMERGENCIA_GAS_DERIVADA = "emergencia_gas_derivada"
# "Para llamar" (2026-10-09, agent/llamadas.py): tarea de llamada para leads callados que mostraron interés.
# Los eventos de GESTIÓN REAL quedan visibles en el Timeline (la llamada registrada, la tarea agotada, la oferta
# de Gabi y la reprogramación que decidió una persona). Los de mecánica interna —crearla, asignarla, cancelarla
# porque el cliente escribió, expirarla, escalarla— son INTERNOS: existen para medir y auditar, no para el asesor.
EVENTO_LLAMADA_PENDIENTE_CREADA = "llamada_pendiente_creada"
EVENTO_LLAMADA_ASIGNADA = "llamada_asignada"
EVENTO_LLAMADA_REGISTRADA = "llamada_registrada"
EVENTO_LLAMADA_REPROGRAMADA = "llamada_reprogramada"
EVENTO_LLAMADA_CANCELADA_POR_RESPUESTA = "llamada_cancelada_por_respuesta"
EVENTO_LLAMADA_AGOTADA = "llamada_agotada_sin_contacto"
EVENTO_LLAMADA_EXPIRADA = "llamada_expirada"
EVENTO_LLAMADA_ESCALADA = "llamada_escalada_supervision"
EVENTO_LLAMADA_OFERTA_ENVIADA = "llamada_oferta_enviada"
# La respuesta del cliente a la oferta de llamada (2026-10-11): VISIBLES (son la evidencia del consentimiento o del
# rechazo, con el texto literal del cliente en el payload).
EVENTO_LLAMADA_ACEPTADA = "llamada_aceptada_por_cliente"
EVENTO_LLAMADA_RECHAZADA = "llamada_rechazada_por_cliente"
TIPOS_EVENTO_LLAMADA_INTERNOS = (
    EVENTO_LLAMADA_PENDIENTE_CREADA, EVENTO_LLAMADA_ASIGNADA, EVENTO_LLAMADA_CANCELADA_POR_RESPUESTA,
    EVENTO_LLAMADA_EXPIRADA, EVENTO_LLAMADA_ESCALADA,
)
# Experimento «solo clic» (2026-10-16, agent/solo_clic.py, Fases A-B): la SOMBRA registra a qué brazo iría cada conversación
# de «solo clic» y qué habría hecho el sistema (`exp_solo_clic_sombra`), y luego el desenlace natural observado a 24 h y 72 h
# (`exp_solo_clic_resultado`, uno por horizonte). Son INTERNOS (medición, no gestión): no salen en el Timeline. Los dos caben
# de sobra en eventos_lead.tipo (TIPO_EVENTO_LARGO_MAX).
EVENTO_EXP_SOLO_CLIC_SOMBRA = "exp_solo_clic_sombra"
EVENTO_EXP_SOLO_CLIC_RESULTADO = "exp_solo_clic_resultado"
TIPOS_EVENTO_EXP_SOLO_CLIC = (EVENTO_EXP_SOLO_CLIC_SOMBRA, EVENTO_EXP_SOLO_CLIC_RESULTADO)
TIPOS_EVENTO_INTERNOS = (EVENTO_TRIAJE_ATC_SOMBRA, EVENTO_TRIAJE_ATC_FALLIDO) + TIPOS_EVENTO_LLAMADA_INTERNOS + TIPOS_EVENTO_EXP_SOLO_CLIC


class EventoLead(Base):
    """Conversation Timeline (MAIEK_AI_PRODUCT_PATTERNS.md, Cap. 6) — eventos
    de NEGOCIO sobre un hilo (resultado cambiado, asignado, venta registrada),
    distintos de los mensajes de chat crudos. Append-only: nunca se actualiza
    ni se borra una fila existente. `payload` guarda valores estructurados
    (campo/anterior/nuevo, líneas de venta, etc.) — no solo el texto de
    `descripcion` — para que el evento sea una fuente de datos reutilizable
    por auditoría, analítica y el Copiloto IA más adelante, no únicamente
    una lista para mostrar en pantalla. `autor` guarda el nombre de quien
    hizo el cambio TAL COMO ERA en ese momento (no una referencia viva a
    Usuario) — práctica estándar de bitácora: el registro histórico no debe
    cambiar si alguien edita su nombre después. None si el cambio fue
    automático (Gabi).

    Gate 5.3 — hallazgo del bloque de Diseño Técnico (Agente B): este modelo
    tenía el MISMO patrón telefono-only que LineaVenta, en lectura Y
    escritura — y es exactamente lo que este mismo Gate expone como
    Conversation Timeline por API. `telefono` se elimina; toda lectura/
    escritura usa las claves fuertes `negocio_id`/`conversation_id`/
    `opportunity_id`, nunca telefono en solitario."""
    __tablename__ = "eventos_lead"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)  # D2 (política UUID retroactiva) sigue Pendiente — no se migra por anticipación
    negocio_id: Mapped[str] = mapped_column(String(36), ForeignKey("negocios.id"), nullable=False, index=True)
    conversation_id: Mapped[str] = mapped_column(String(36), ForeignKey("conversations.id"), nullable=False, index=True)
    # NULL para eventos de Conversation (asignado/desasignado); poblado para
    # eventos de Opportunity (resultado_cambiado, venta_registrada).
    opportunity_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("opportunities.id"), nullable=True, index=True)
    tipo: Mapped[str] = mapped_column(String(TIPO_EVENTO_LARGO_MAX))  # resultado_cambiado | asignado | venta_registrada
    descripcion: Mapped[str] = mapped_column(String(300))
    payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    autor: Mapped[str | None] = mapped_column(String(100), nullable=True)
    creado: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)

    __table_args__ = (
        Index("ix_evento_negocio_conversation_creado", "negocio_id", "conversation_id", "creado"),
    )


async def registrar_evento_lead(telefono: str, tipo: str, descripcion: str, autor: str | None, payload: dict | None = None):
    """Interfaz pública SIN CAMBIOS (sigue siendo telefono, como todos sus
    call sites existentes en dashboard.py/memory.py) — Gate 5.3 resuelve
    `negocio_id`/`conversation_id`/`opportunity_id` INTERNAMENTE, mismo
    patrón que `guardar_mensaje` ya usa para `negocio_id` desde Gate 5.2
    (H1): nunca se le pide al llamador que resuelva el contexto, y nunca se
    acepta un `conversation_id` externo que pudiera manipularse o duplicar
    la resolución. Falla cerrado si el Contact/Conversation no existen
    todavía (no se inventa ninguno acá — la creación es responsabilidad del
    flujo de entrada, ver `_resolver_conversation_activa` en el webhook)."""
    async with async_session() as session:
        conversation = await _obtener_conversation_activa_por_telefono(session, telefono)
        if conversation is None:
            raise ValueError(
                f"registrar_evento_lead(): no existe una Conversation activa para telefono={telefono} "
                f"— no se puede registrar el evento sin resolver el hilo. Verificar que la Conversation "
                f"ya fue creada para este teléfono (webhook o backfill)."
            )
        opportunity = await _obtener_opportunity_vigente(session, conversation.id)
        session.add(EventoLead(
            conversation_id=conversation.id, negocio_id=conversation.negocio_id,
            opportunity_id=opportunity.id if opportunity else None,
            tipo=tipo, descripcion=descripcion, autor=autor, payload=payload,
        ))
        await session.commit()


async def listar_eventos_lead(telefono: str, limite: int | None = None) -> list[dict]:
    """Del más reciente al más antiguo — para el Conversation Timeline y,
    tomando solo el primero, para el aviso de conflicto de edición (quién,
    cuándo, qué cambió). Interfaz pública sin cambios (telefono); internamente
    filtra por `conversation_id` + `negocio_id` (doble candado) — nunca por
    telefono contra la tabla `eventos_lead` (hallazgo GRAVE del bloque de
    Diseño Técnico, ver comentario de la clase EventoLead)."""
    async with async_session() as session:
        conversation = await _obtener_conversation_activa_por_telefono(session, telefono)
        if conversation is None:
            return []
        query = (
            select(EventoLead)
            .where(
                EventoLead.conversation_id == conversation.id, EventoLead.negocio_id == conversation.negocio_id,
                EventoLead.tipo.notin_(TIPOS_EVENTO_INTERNOS),
            )
            .order_by(EventoLead.creado.desc())
        )
        if limite:
            query = query.limit(limite)
        result = await session.execute(query)
        return [
            {
                # `id` viaja para que el Timeline tenga una clave estable por
                # evento (el frontend la usa como key de lista y para anclar
                # un evento puntual): la PK ya existía, solo no se exponía.
                "id": e.id,
                "conversation_id": e.conversation_id, "opportunity_id": e.opportunity_id,
                "tipo": e.tipo, "descripcion": e.descripcion, "payload": e.payload,
                "autor": e.autor, "creado": e.creado,
            }
            for e in result.scalars().all()
        ]


class AttributionEvent(Base):
    """Attribution V2 — Fase 1 (evidencia de atribución de campañas). Append-
    only, mismo criterio que EventoLead: nunca se actualiza ni se borra una
    fila existente. Conserva la evidencia CRUDA que Meta entrega en
    `messages[].referral` de un anuncio de Click-to-WhatsApp, incluso cuando
    no logra resolverse contra ninguna campaña configurada
    (`tipo_origen="meta_ads_no_resuelto"`) — la ausencia de resolución NUNCA
    debe convertirse en "orgánico", que era la limitación que esta fase vino
    a cerrar (ver memoria del proyecto, Attribution V2).

    NO reemplaza `Lead.campana_origen` — esa sigue siendo la fuente que usan
    Pipeline/Lead Detail/Ventas/CSV sin ningún cambio. Esta tabla es
    evidencia adicional, de solo lectura para el resto del sistema en esta
    fase (sin UI ni endpoints propios todavía)."""
    __tablename__ = "attribution_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    negocio_id: Mapped[str] = mapped_column(String(36), ForeignKey("negocios.id"), nullable=False, index=True)
    conversation_id: Mapped[str] = mapped_column(String(36), ForeignKey("conversations.id"), nullable=False, index=True)
    # 150, no 50 — ver Mensaje.telefono (BSUID de Meta, Gate 2026-09-22).
    lead_telefono: Mapped[str] = mapped_column(String(150), ForeignKey("leads.telefono"), nullable=False, index=True)
    # "meta_ads" | "meta_ads_no_resuelto" | "wa_link" | "organico" | "otro"
    tipo_origen: Mapped[str] = mapped_column(String(30))
    # Objeto `referral` tal cual lo entrega Meta, sin procesar — resiliencia
    # ante campos nuevos/distintos que hoy no sabemos si serán útiles.
    referral_raw: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    source_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    headline: Mapped[str | None] = mapped_column(Text, nullable=True)
    body: Mapped[str | None] = mapped_column(Text, nullable=True)
    # No confirmado que Meta lo entregue en este payload — se persiste si
    # aparece, nunca se asume su presencia (ver checkpoint de diseño).
    ctwa_clid: Mapped[str | None] = mapped_column(String(200), nullable=True)
    # Nombre de campaña ya resuelta (copia del match de
    # detectar_y_asignar_campana, si lo hubo) — evidencia de qué generó ese
    # match, no reemplaza Lead.campana_origen.
    campana_nombre: Mapped[str | None] = mapped_column(String(100), nullable=True)
    first_touch: Mapped[bool] = mapped_column(Boolean, default=False)
    creado: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)

    __table_args__ = (
        Index("ix_attribution_negocio_lead_creado", "negocio_id", "lead_telefono", "creado"),
        Index("ix_attribution_negocio_tipo", "negocio_id", "tipo_origen"),
    )


async def registrar_attribution_event(
    telefono: str, tipo_origen: str, referral: dict | None = None,
    campana_nombre: str | None = None,
) -> dict | None:
    """Attribution V2 — Fase 1. Persiste evidencia de atribución (append-only)
    para el hilo activo de `telefono`, sin tocar ni reemplazar
    `Lead.campana_origen`. Mismo patrón fail-closed que
    `registrar_evento_lead`: si todavía no existe una Conversation activa
    para este teléfono, no inventa ninguna — retorna None (en el webhook
    esto no debería pasar nunca, porque `resolver_conversation_activa` ya
    corrió antes de llegar al punto donde se llama a esta función).

    `first_touch` se calcula acá mismo, consultando si ya existe un evento
    previo para este lead — así la función queda correcta aunque en el
    futuro se la llame más de una vez para el mismo lead (multi-touch,
    fuera de alcance de esta fase, pero sin romper el contrato del campo)."""
    async with async_session() as session:
        conversation = await _obtener_conversation_activa_por_telefono(session, telefono)
        if conversation is None:
            logger.warning(
                f"registrar_attribution_event(): no existe una Conversation activa para "
                f"telefono={telefono} — evento de atribución descartado."
            )
            return None
        ya_existe = await session.execute(
            select(AttributionEvent.id)
            .where(AttributionEvent.negocio_id == conversation.negocio_id, AttributionEvent.lead_telefono == telefono)
            .limit(1)
        )
        es_first_touch = ya_existe.scalar_one_or_none() is None
        evento = AttributionEvent(
            negocio_id=conversation.negocio_id, conversation_id=conversation.id, lead_telefono=telefono,
            tipo_origen=tipo_origen,
            referral_raw=referral,
            source_id=(referral or {}).get("source_id"),
            headline=(referral or {}).get("headline"),
            body=(referral or {}).get("body"),
            ctwa_clid=(referral or {}).get("ctwa_clid"),
            campana_nombre=campana_nombre,
            first_touch=es_first_touch,
        )
        session.add(evento)
        await session.commit()
        return {
            "id": evento.id, "negocio_id": evento.negocio_id, "conversation_id": evento.conversation_id,
            "lead_telefono": evento.lead_telefono, "tipo_origen": evento.tipo_origen,
            "source_id": evento.source_id, "headline": evento.headline, "body": evento.body,
            "ctwa_clid": evento.ctwa_clid, "campana_nombre": evento.campana_nombre,
            "first_touch": evento.first_touch, "creado": evento.creado,
        }


async def listar_attribution_events(telefono: str, negocio_id: str | None = None) -> list[dict]:
    """Del más reciente al más antiguo. `negocio_id` opcional pero
    recomendado como candado explícito cuando quien llama ya lo tiene
    resuelto (mismo criterio de doble candado que `listar_eventos_lead`)."""
    async with async_session() as session:
        query = select(AttributionEvent).where(AttributionEvent.lead_telefono == telefono)
        if negocio_id:
            query = query.where(AttributionEvent.negocio_id == negocio_id)
        query = query.order_by(AttributionEvent.creado.desc())
        result = await session.execute(query)
        return [
            {
                "id": e.id, "negocio_id": e.negocio_id, "conversation_id": e.conversation_id,
                "lead_telefono": e.lead_telefono, "tipo_origen": e.tipo_origen,
                "referral_raw": e.referral_raw, "source_id": e.source_id, "headline": e.headline,
                "body": e.body, "ctwa_clid": e.ctwa_clid, "campana_nombre": e.campana_nombre,
                "first_touch": e.first_touch, "creado": e.creado,
            }
            for e in result.scalars().all()
        ]


async def registrar_attribution_event_adicional(
    telefono: str, tipo_origen: str, referral: dict | None = None,
    campana_nombre: str | None = None,
) -> dict | None:
    """Igual que `registrar_attribution_event`, pero SIEMPRE con
    `first_touch=False`: es evidencia de un referral que llega cuando el lead
    ya tenía campaña de origen (un segundo clic en otro anuncio). La campaña
    original no se toca; solo queda el rastro del clic nuevo. Mismo patrón
    fail-closed: sin Conversation activa no inventa nada y retorna None."""
    async with async_session() as session:
        conversation = await _obtener_conversation_activa_por_telefono(session, telefono)
        if conversation is None:
            logger.warning(
                f"registrar_attribution_event_adicional(): no existe una Conversation activa para "
                f"telefono={telefono} — evento de atribución descartado."
            )
            return None
        evento = AttributionEvent(
            negocio_id=conversation.negocio_id, conversation_id=conversation.id, lead_telefono=telefono,
            tipo_origen=tipo_origen,
            referral_raw=referral,
            source_id=(referral or {}).get("source_id"),
            headline=(referral or {}).get("headline"),
            body=(referral or {}).get("body"),
            ctwa_clid=(referral or {}).get("ctwa_clid"),
            campana_nombre=campana_nombre,
            first_touch=False,
        )
        session.add(evento)
        await session.commit()
        return {
            "id": evento.id, "negocio_id": evento.negocio_id, "conversation_id": evento.conversation_id,
            "lead_telefono": evento.lead_telefono, "tipo_origen": evento.tipo_origen,
            "source_id": evento.source_id, "headline": evento.headline, "body": evento.body,
            "ctwa_clid": evento.ctwa_clid, "campana_nombre": evento.campana_nombre,
            "first_touch": evento.first_touch, "creado": evento.creado,
        }


async def asignar_campana_a_conversation_activa(telefono: str, campana_id: int) -> bool:
    """Atribuye la campaña de un anuncio a la conversación ACTIVA del lead SOLO
    si esa conversación aún no tiene campaña. No toca `Lead.campana_origen`
    (primer contacto) ni pisa la campaña que la conversación ya traía. Sirve
    para un lead que vuelve por otro (o el mismo) anuncio: su conversación
    nueva cuenta para la campaña por la que entró ahora."""
    async with async_session() as session:
        conversation = await _obtener_conversation_activa_por_telefono(session, telefono)
        if conversation is None or conversation.campana_origen_id is not None:
            return False
        conversation.campana_origen_id = campana_id
        await session.commit()
        return True


async def existe_attribution_event_reciente(
    telefono: str, negocio_id: str, referral: dict | None, minutos: int = 30,
) -> bool:
    """¿Ya hay un evento de atribución de este mismo lead con el MISMO referral
    (source_id, ctwa_clid, headline y body iguales) creado en los últimos
    `minutos`? Sirve para que un reintento de Meta del mismo mensaje no duplique
    la evidencia. Un clic nuevo trae otro `ctwa_clid`, así que no se confunde."""
    referral = referral or {}
    condiciones = [
        AttributionEvent.negocio_id == negocio_id, AttributionEvent.lead_telefono == telefono,
        AttributionEvent.creado >= datetime.utcnow() - timedelta(minutes=minutos),
    ]
    for columna, clave in (
        (AttributionEvent.source_id, "source_id"), (AttributionEvent.ctwa_clid, "ctwa_clid"),
        (AttributionEvent.headline, "headline"), (AttributionEvent.body, "body"),
    ):
        valor = referral.get(clave)
        condiciones.append(columna.is_(None) if valor is None else columna == valor)
    async with async_session() as session:
        encontrado = await session.execute(select(AttributionEvent.id).where(*condiciones).limit(1))
        return encontrado.scalars().first() is not None


_TIPOS_ORIGEN_ANUNCIO = ("meta_ads", "meta_ads_no_resuelto")


def _red_de_referral(referral: dict | None) -> str:
    """Red social de un clic en anuncio: "facebook", "instagram" u "otra" (sin
    enlace o de otro dominio). Meta no manda un campo de plataforma; se
    deduce del dominio de `source_url`, así que es una señal, no un dato
    oficial — un anuncio con ubicaciones automáticas podría mostrar siempre
    el mismo enlace."""
    host = (urlparse((referral or {}).get("source_url") or "").hostname or "").lower()
    if host == "instagram.com" or host.endswith(".instagram.com"):
        return "instagram"
    if host in ("fb.me", "fb.com", "facebook.com") or host.endswith((".facebook.com", ".fb.com")):
        return "facebook"
    return "otra"


async def _red_por_conversation(session, negocio_id: str) -> dict[str, str]:
    """Red de cada conversación que llegó desde un anuncio de Meta, según su
    primer evento de atribución. Las conversaciones sin evento (SMS, wa.link,
    orgánicas) no aparecen: quien consulta las trata como "otra"."""
    eventos = (await session.execute(
        select(AttributionEvent.conversation_id, AttributionEvent.referral_raw)
        .where(AttributionEvent.negocio_id == negocio_id, AttributionEvent.tipo_origen.in_(_TIPOS_ORIGEN_ANUNCIO))
        .order_by(AttributionEvent.creado.asc(), AttributionEvent.id.asc())
    )).all()
    redes: dict[str, str] = {}
    for conversation_id, referral in eventos:
        redes.setdefault(conversation_id, _red_de_referral(referral))
    return redes


async def listar_anuncios_detectados(negocio_id: str) -> list[dict]:
    """Anuncios de Meta (Click-to-WhatsApp) que trajeron leads, agrupados por
    `source_id` (el ID del anuncio), a partir de la evidencia que ya guarda
    `registrar_attribution_event` — incluidos los que ninguna campaña
    reconoció. Por cada anuncio, a qué campaña pertenecen HOY sus
    conversaciones (la fuente que cuenta la Analítica), no la que quedó
    escrita en la evidencia original (append-only). Más reciente primero."""
    async with async_session() as session:
        eventos = (await session.execute(
            select(AttributionEvent)
            .where(
                AttributionEvent.negocio_id == negocio_id,
                AttributionEvent.tipo_origen.in_(_TIPOS_ORIGEN_ANUNCIO),
                AttributionEvent.source_id.is_not(None), AttributionEvent.source_id != "",
            )
            .order_by(AttributionEvent.creado.asc())
        )).scalars().all()
        if not eventos:
            return []
        campana_por_conversation = dict((await session.execute(
            select(Conversation.id, Campana.nombre)
            .outerjoin(Campana, Campana.id == Conversation.campana_origen_id)
            .where(Conversation.id.in_({e.conversation_id for e in eventos}))
        )).all())

    primer_anuncio: dict[str, str] = {}
    for e in eventos:  # ya vienen en orden cronológico
        primer_anuncio.setdefault(e.conversation_id, e.source_id)

    anuncios: dict[str, dict] = {}
    for e in eventos:
        a = anuncios.setdefault(e.source_id, {
            "source_id": e.source_id, "headline": None, "body": None, "url": None,
            "primero": e.creado, "ultimo": e.creado, "conversaciones": set(), "leads": set(), "campanas": {},
            "redes": {"facebook": 0, "instagram": 0, "otra": 0},
        })
        a["headline"] = e.headline or a["headline"]
        a["body"] = e.body or a["body"]
        a["url"] = (e.referral_raw or {}).get("source_url") or a["url"]
        a["ultimo"] = e.creado
        a["leads"].add(e.lead_telefono)
        if e.conversation_id not in a["conversaciones"]:
            a["conversaciones"].add(e.conversation_id)
            nombre = campana_por_conversation.get(e.conversation_id)
            a["campanas"][nombre] = a["campanas"].get(nombre, 0) + 1
            a["redes"][_red_de_referral(e.referral_raw)] += 1

    resultado = [
        {
            "source_id": a["source_id"], "headline": a["headline"], "body": (a["body"] or "")[:300] or None,
            "url": a["url"], "primero": a["primero"], "ultimo": a["ultimo"],
            "leads": len(a["leads"]), "conversaciones": len(a["conversaciones"]),
            "propias": sum(1 for c in a["conversaciones"] if primer_anuncio.get(c) == a["source_id"]),
            "sin_campana": a["campanas"].get(None, 0), "redes": a["redes"],
            "campanas": [
                {"campana": nombre, "conversaciones": n}
                for nombre, n in sorted(a["campanas"].items(), key=lambda kv: -kv[1]) if nombre is not None
            ],
        }
        for a in anuncios.values()
    ]
    return sorted(resultado, key=lambda a: a["ultimo"], reverse=True)


async def listar_atribucion_sin_campana_periodo(
    negocio_id: str, desde: datetime, hasta: datetime,
    unidad_id: str | None = None, asesor: str | None = None, red: str | None = None,
) -> dict:
    """Complementa `contar_opportunities_por_campana` (Gate Analítica P0 —
    tabla Campañas + Orgánicos): mismo universo y mismos filtros
    (`Conversation.creado` en `[desde, hasta)`, `unidad_id`/`asesor`
    opcionales), pero para las conversaciones que NO tienen
    `campana_origen_id` — las dos funciones juntas cubren el 100% de las
    conversaciones del período, sin solaparse.

    Esas conversaciones se separan en dos grupos:
    - `anuncios`: tienen evidencia de un anuncio de Meta (`AttributionEvent`
      con `tipo_origen` en `_TIPOS_ORIGEN_ANUNCIO`) que ninguna campaña
      resolvió todavía — agrupadas por `source_id`, mismo criterio que
      `listar_anuncios_detectados`. Nunca se cuentan como orgánicas: son
      leads de pauta pendientes de asignar, no espontáneos.
    - `organico`: sin ningún rastro de Meta Ads (WhatsApp directo, wa.link,
      SMS sin patrón reconocido). Siempre cae en la red "otra" — no hay
      enlace de anuncio del que deducir Facebook/Instagram.

    `red`, cuando viene informado, filtra cada grupo por SU PROPIA red (la
    del anuncio para `anuncios`, siempre "otra" para `organico`) — mismo
    significado que en `contar_opportunities_por_campana`."""
    async with async_session() as session:
        query = select(Conversation.id).where(
            Conversation.negocio_id == negocio_id,
            Conversation.campana_origen_id.is_(None),
            Conversation.creado >= desde, Conversation.creado < hasta,
        )
        if unidad_id is not None:
            query = query.where(Conversation.unidad_id == unidad_id)
        if asesor is not None:
            query = query.where(Conversation.asesor_asignado_id == asesor)
        ids_conversation = [row[0] for row in (await session.execute(query)).all()]

        vacio = {"anuncios": [], "organico": {"total": 0, "vendidos": 0, "redes": {"facebook": 0, "instagram": 0, "otra": 0}}}
        if not ids_conversation:
            return vacio

        eventos = (await session.execute(
            select(
                AttributionEvent.conversation_id, AttributionEvent.source_id,
                AttributionEvent.headline, AttributionEvent.body, AttributionEvent.referral_raw,
            )
            .where(
                AttributionEvent.negocio_id == negocio_id,
                AttributionEvent.conversation_id.in_(ids_conversation),
                AttributionEvent.tipo_origen.in_(_TIPOS_ORIGEN_ANUNCIO),
                AttributionEvent.source_id.is_not(None), AttributionEvent.source_id != "",
            )
            .order_by(AttributionEvent.creado.asc(), AttributionEvent.id.asc())
        )).all()
        # Primer evento de anuncio por conversación decide su anuncio y su
        # red — mismo criterio que `_red_por_conversation`.
        anuncio_por_conversation: dict[str, dict] = {}
        for conversation_id, source_id, headline, body, referral_raw in eventos:
            anuncio_por_conversation.setdefault(conversation_id, {
                "source_id": source_id, "headline": headline, "body": body,
                "red": _red_de_referral(referral_raw),
            })

        query_vendidos = (
            select(Conversation.id).select_from(Conversation)
            .join(Opportunity, Opportunity.conversation_id == Conversation.id)
            .where(Conversation.id.in_(ids_conversation), Opportunity.resultado == "vendido")
        )
        ids_vendidos = {row[0] for row in (await session.execute(query_vendidos)).all()}

    anuncios: dict[str, dict] = {}
    organico = {"total": 0, "vendidos": 0, "redes": {"facebook": 0, "instagram": 0, "otra": 0}}
    for conversation_id in ids_conversation:
        info = anuncio_por_conversation.get(conversation_id)
        vendido = conversation_id in ids_vendidos
        if info is None:
            if red is not None and red != "otra":
                continue
            organico["total"] += 1
            organico["redes"]["otra"] += 1
            if vendido:
                organico["vendidos"] += 1
        else:
            if red is not None and info["red"] != red:
                continue
            a = anuncios.setdefault(info["source_id"], {
                "source_id": info["source_id"], "headline": None, "body": None,
                "total": 0, "vendidos": 0, "redes": {"facebook": 0, "instagram": 0, "otra": 0},
            })
            a["headline"] = a["headline"] or info["headline"]
            a["body"] = a["body"] or info["body"]
            a["total"] += 1
            a["redes"][info["red"]] += 1
            if vendido:
                a["vendidos"] += 1

    return {
        "anuncios": sorted(anuncios.values(), key=lambda a: -a["total"]),
        "organico": organico,
    }


async def cargar_datos_origen_conversaciones(negocio_id: str, conversation_ids: list[str]) -> dict:
    """Solo lectura, EN LOTE (4 consultas fijas, sin importar cuántas
    conversaciones se pidan): la evidencia que `agent/origen_conversacion.py`
    necesita para decir de dónde vino cada conversación — la conversación, su
    lead (origen de contacto y campaña histórica por nombre), los eventos de
    atribución de esos teléfonos (del más antiguo al más nuevo) y las
    campañas involucradas. Todo filtrado por `negocio_id`: un id de otro
    Negocio simplemente no aparece. Sin teléfonos ni datos personales en la
    salida más allá de lo que el llamador ya tiene."""
    ids = list(dict.fromkeys(i for i in conversation_ids if i))
    if not ids:
        return {"conversaciones": {}, "leads": {}, "eventos": {}, "campanas": {}}
    async with async_session() as session:
        convs = (await session.execute(
            select(
                Conversation.id, Conversation.creado, Conversation.campana_origen_id,
                Conversation.origen_contacto, Contact.telefono,
            )
            .join(Contact, Contact.id == Conversation.contact_id)
            .where(Conversation.negocio_id == negocio_id, Conversation.id.in_(ids))
        )).all()
        conversaciones = {
            c.id: {
                "id": c.id, "creado": c.creado, "campana_origen_id": c.campana_origen_id,
                "origen_contacto": c.origen_contacto, "telefono": c.telefono,
            }
            for c in convs
        }
        telefonos = list({c["telefono"] for c in conversaciones.values() if c["telefono"]})
        leads: dict[str, dict] = {}
        eventos: dict[str, list[dict]] = {}
        if telefonos:
            for tel, campana_origen, origen_contacto in (await session.execute(
                select(Lead.telefono, Lead.campana_origen, Lead.origen_contacto)
                .where(Lead.negocio_id == negocio_id, Lead.telefono.in_(telefonos))
            )).all():
                leads[tel] = {"campana_origen": campana_origen, "origen_contacto": origen_contacto}
            for e in (await session.execute(
                select(AttributionEvent)
                .where(AttributionEvent.negocio_id == negocio_id, AttributionEvent.lead_telefono.in_(telefonos))
                .order_by(AttributionEvent.creado.asc(), AttributionEvent.id.asc())
            )).scalars().all():
                eventos.setdefault(e.lead_telefono, []).append({
                    "id": e.id, "conversation_id": e.conversation_id, "tipo_origen": e.tipo_origen,
                    "source_id": e.source_id, "headline": e.headline, "body": e.body,
                    "source_url": (e.referral_raw or {}).get("source_url") if isinstance(e.referral_raw, dict) else None,
                    "referral_raw": e.referral_raw if isinstance(e.referral_raw, dict) else None,
                    "campana_nombre": e.campana_nombre, "first_touch": bool(e.first_touch), "creado": e.creado,
                })
        ids_campana = {c["campana_origen_id"] for c in conversaciones.values() if c["campana_origen_id"] is not None}
        nombres_campana = {l["campana_origen"] for l in leads.values() if l["campana_origen"]}
        campanas: dict[int, dict] = {}
        condiciones = []
        if ids_campana:
            condiciones.append(Campana.id.in_(ids_campana))
        if nombres_campana:
            condiciones.append(Campana.nombre.in_(nombres_campana))
        if condiciones:
            for c in (await session.execute(
                select(Campana).where(Campana.negocio_id == negocio_id, sa_or(*condiciones))
            )).scalars().all():
                campanas[c.id] = _campana_a_dict(c)
    return {"conversaciones": conversaciones, "leads": leads, "eventos": eventos, "campanas": campanas}


async def obtener_reglas_anuncio(negocio_id: str) -> dict[str, int]:
    """`{source_id: campana_id}` de las reglas explícitas anuncio→campaña del Negocio."""
    async with async_session() as session:
        filas = (await session.execute(
            select(AnuncioCampana.source_id, AnuncioCampana.campana_id).where(AnuncioCampana.negocio_id == negocio_id)
        )).all()
    return {source_id: campana_id for source_id, campana_id in filas}


async def guardar_regla_anuncio(negocio_id: str, source_id: str, campana_id: int, autor: str | None = None) -> None:
    """Crea o actualiza la regla del anuncio (una campaña por anuncio). La
    campaña debe ser del mismo Negocio — `LookupError` si no."""
    async with async_session() as session:
        campana = await session.get(Campana, campana_id)
        if campana is None or campana.negocio_id != negocio_id:
            raise LookupError("La campaña no existe.")
        regla = (await session.execute(
            select(AnuncioCampana).where(AnuncioCampana.negocio_id == negocio_id, AnuncioCampana.source_id == source_id)
        )).scalars().first()
        if regla is None:
            session.add(AnuncioCampana(negocio_id=negocio_id, source_id=source_id, campana_id=campana_id, creado_por=autor))
        else:
            regla.campana_id = campana_id
            regla.creado_por = autor
        await session.commit()


async def diagnostico_anuncios_sin_campana(negocio_id: str) -> list[dict]:
    """Solo lectura. Por cada conversación que llegó de un anuncio de Meta y
    hoy NO tiene campaña: qué evidencia trajo (¿título/texto presentes?, ¿era
    primer contacto?, ¿qué campaña resolvió el evento?). Sirve para saber por
    qué un anuncio ya reconocido deja leads "Sin campaña". Teléfono enmascarado."""
    async with async_session() as session:
        filas = (await session.execute(
            select(AttributionEvent, Conversation.creado, Conversation.campana_origen_id)
            .join(Conversation, Conversation.id == AttributionEvent.conversation_id)
            .where(
                AttributionEvent.negocio_id == negocio_id,
                AttributionEvent.tipo_origen.in_(_TIPOS_ORIGEN_ANUNCIO),
                AttributionEvent.source_id.is_not(None), AttributionEvent.source_id != "",
                Conversation.campana_origen_id.is_(None),
            )
            .order_by(AttributionEvent.source_id, AttributionEvent.creado.asc())
        )).all()
    return [
        {
            "source_id": e.source_id, "evento_creado": e.creado, "conversacion_creada": conv_creada,
            "tipo_origen": e.tipo_origen, "first_touch": bool(e.first_touch),
            "tiene_headline": bool(e.headline), "tiene_body": bool(e.body),
            "campana_del_evento": e.campana_nombre,
            "telefono": "…" + (e.lead_telefono or "")[-4:],
        }
        for e, conv_creada, _ in filas
    ]


def _es_campana_comodin(c: dict) -> bool:
    """Campaña de Meta que detecta por una PALABRA clave ("secadora", "terma") en
    vez de por el ID de un anuncio: atribuye en silencio cualquier anuncio
    nuevo que mencione esa palabra. Las de ID exacto tienen patrón numérico."""
    return c["tipo_deteccion"] == "referral_meta" and not str(c["patron"]).strip().isdigit()


def _es_campana_por_id(c: dict) -> bool:
    """Campaña de Meta cuyo patrón es el ID numérico de UN anuncio (las de setiembre)."""
    return c["tipo_deteccion"] == "referral_meta" and str(c["patron"]).strip().isdigit()


async def plan_migrar_comodines(negocio_id: str, excluir: list[str] | None = None) -> dict:
    """Solo lectura. Qué haría `aplicar_migrar_comodines` para dejar TODAS las
    campañas de Meta con un único mecanismo, la regla anuncio→campaña
    (`por_anuncio`):
      · las campañas con ID de anuncio como patrón → una regla (ese ID → esa campaña);
      · las campañas comodín (palabra clave) → una regla por cada anuncio que hoy
        atribuyen (la campaña con más conversaciones, si es un comodín), salvo los
        `excluir`, que quedan sin regla (para asignarlos a mano).
    Las conversaciones ya atribuidas no cambian. Sin tocar nada."""
    campanas = await listar_campanas(negocio_id)
    comodines = {c["nombre"]: c for c in campanas if _es_campana_comodin(c)}
    por_id = [c for c in campanas if _es_campana_por_id(c)]
    reglas = dict(await obtener_reglas_anuncio(negocio_id))
    omitidos = set(excluir or [])
    nuevas = []
    for c in por_id:
        source_id = str(c["patron"]).strip()
        if source_id in reglas:
            continue  # ya tiene regla: no se pisa
        reglas[source_id] = c["id"]
        nuevas.append({
            "source_id": source_id, "headline": None, "campana": c["nombre"], "campana_id": c["id"],
            "conversaciones": 0, "sin_campana": 0, "origen": "id",
        })
    for a in await listar_anuncios_detectados(negocio_id):
        if a["source_id"] in reglas or a["source_id"] in omitidos or not a["campanas"]:
            continue
        mejor = a["campanas"][0]  # ya vienen ordenadas por conversaciones, de mayor a menor
        empate = len(a["campanas"]) > 1 and a["campanas"][1]["conversaciones"] == mejor["conversaciones"]
        if mejor["campana"] in comodines and not empate:
            nuevas.append({
                "source_id": a["source_id"], "headline": a["headline"], "campana": mejor["campana"],
                "campana_id": comodines[mejor["campana"]]["id"],
                "conversaciones": mejor["conversaciones"], "sin_campana": a["sin_campana"], "origen": "comodin",
            })
    return {
        "campanas_a_convertir": [
            {"id": c["id"], "nombre": c["nombre"], "patron": c["patron"], "tipo_anterior": c["tipo_deteccion"],
             "origen": "comodin" if _es_campana_comodin(c) else "id"}
            for c in campanas if _es_campana_comodin(c) or _es_campana_por_id(c)
        ],
        "reglas_a_crear": nuevas,
    }


async def aplicar_migrar_comodines(negocio_id: str, autor: str | None = None, excluir: list[str] | None = None) -> dict:
    """Aplica el plan: escribe las reglas y pasa las campañas de Meta a
    `por_anuncio`. Las conversaciones ya atribuidas NO se tocan (la Analítica no
    cambia); solo cambia cómo se reconocen los anuncios. Guarda en la auditoría lo
    necesario para deshacerlo (`historico_revertir`)."""
    plan = await plan_migrar_comodines(negocio_id, excluir=excluir)
    for r in plan["reglas_a_crear"]:
        await guardar_regla_anuncio(negocio_id, r["source_id"], r["campana_id"], autor=autor)
    async with async_session() as session:
        for c in plan["campanas_a_convertir"]:
            fila = await session.get(Campana, c["id"])
            if fila is not None and fila.negocio_id == negocio_id:
                fila.tipo_deteccion = "por_anuncio"
        await session.commit()
    auditoria_id = await registrar_auditoria(
        "campanas_comodin_migradas", actor=autor, negocio_id=negocio_id, entidad_tipo="campana", entidad_id="*",
        payload={
            "campanas": [{"id": c["id"], "tipo_anterior": c["tipo_anterior"]} for c in plan["campanas_a_convertir"]],
            "reglas": [r["source_id"] for r in plan["reglas_a_crear"]],
        },
    )
    return {
        "campanas": len(plan["campanas_a_convertir"]), "reglas": len(plan["reglas_a_crear"]), "auditoria_id": auditoria_id,
    }


async def _primer_anuncio_por_conversation(session, negocio_id: str) -> tuple[dict[str, tuple[str, str]], dict[str, str]]:
    """({conversation_id: (source_id, lead_telefono)} con el PRIMER anuncio de cada
    conversación, {lead_telefono: source_id} con el primer anuncio de cada lead)."""
    eventos = (await session.execute(
        select(AttributionEvent.conversation_id, AttributionEvent.source_id, AttributionEvent.lead_telefono)
        .where(
            AttributionEvent.negocio_id == negocio_id, AttributionEvent.tipo_origen.in_(_TIPOS_ORIGEN_ANUNCIO),
            AttributionEvent.source_id.is_not(None), AttributionEvent.source_id != "",
        )
        .order_by(AttributionEvent.creado.asc(), AttributionEvent.id.asc())
    )).all()
    por_conversation: dict[str, tuple[str, str]] = {}
    por_lead: dict[str, str] = {}
    for conversation_id, source_id, telefono in eventos:
        por_conversation.setdefault(conversation_id, (source_id, telefono))
        por_lead.setdefault(telefono, source_id)
    return por_conversation, por_lead


async def _conversaciones_con_varios_anuncios(session, negocio_id: str) -> list[dict]:
    """Conversaciones que recibieron eventos de 2 o más anuncios DISTINTOS, en orden
    cronológico, con su campaña actual y la regla vigente de su primer anuncio."""
    eventos = (await session.execute(
        select(
            AttributionEvent.conversation_id, AttributionEvent.source_id, AttributionEvent.lead_telefono,
            AttributionEvent.headline,
        )
        .where(
            AttributionEvent.negocio_id == negocio_id, AttributionEvent.tipo_origen.in_(_TIPOS_ORIGEN_ANUNCIO),
            AttributionEvent.source_id.is_not(None), AttributionEvent.source_id != "",
        )
        .order_by(AttributionEvent.creado.asc(), AttributionEvent.id.asc())
    )).all()
    por_conv: dict[str, dict] = {}
    for conversation_id, source_id, telefono, headline in eventos:
        c = por_conv.setdefault(conversation_id, {"telefono": telefono, "fuentes": [], "headline": headline})
        if source_id not in c["fuentes"]:
            c["fuentes"].append(source_id)
    varios = {cid: c for cid, c in por_conv.items() if len(c["fuentes"]) >= 2}
    if not varios:
        return []
    campanas = {c.id: c.nombre for c in (await session.execute(
        select(Campana).where(Campana.negocio_id == negocio_id)
    )).scalars().all()}
    reglas = (await session.execute(
        select(AnuncioCampana.source_id, AnuncioCampana.campana_id).where(AnuncioCampana.negocio_id == negocio_id)
    )).all()
    regla_de = {src: cid for src, cid in reglas}
    actuales = dict((await session.execute(
        select(Conversation.id, Conversation.campana_origen_id).where(Conversation.id.in_(list(varios)))
    )).all())
    return [
        {
            "conversation_id": cid, "telefono": c["telefono"], "primero": c["fuentes"][0], "otros": c["fuentes"][1:],
            "headline": c["headline"], "campana_actual_id": actuales.get(cid),
            "campana_actual": campanas.get(actuales.get(cid)),
            "regla_primero_id": regla_de.get(c["fuentes"][0]), "regla_primero": campanas.get(regla_de.get(c["fuentes"][0])),
        }
        for cid, c in varios.items()
    ]


async def auditoria_cierre_conversaciones_multiples(negocio_id: str, dias_silencio: int = 7) -> dict:
    """Solo lectura. Por cada conversación que recibió anuncios de 2 orígenes: ¿por qué no se
    cerró (y por eso no se abrió una conversación nueva para el segundo anuncio)? Compara su
    estado real contra las reglas de cierre definitivo (`cerrar_leads_definitivamente_inactivos`:
    asesor asignado + resultado cerrado distinto de vendido + `dias_silencio` sin respuesta del
    cliente). Teléfonos enmascarados."""
    ahora = datetime.utcnow()
    async with async_session() as session:
        filas = await _conversaciones_con_varios_anuncios(session, negocio_id)
        if not filas:
            return {"total": 0, "por_motivo": {}, "conversaciones": []}
        ids = [f["conversation_id"] for f in filas]
        eventos = (await session.execute(
            select(AttributionEvent.conversation_id, AttributionEvent.source_id, AttributionEvent.creado)
            .where(AttributionEvent.conversation_id.in_(ids), AttributionEvent.tipo_origen.in_(_TIPOS_ORIGEN_ANUNCIO))
            .order_by(AttributionEvent.creado.asc(), AttributionEvent.id.asc())
        )).all()
        por_conv: dict[str, list] = {}
        for conversation_id, source_id, creado in eventos:
            por_conv.setdefault(conversation_id, []).append((source_id, creado))
        conversaciones = {c.id: c for c in (await session.execute(
            select(Conversation).where(Conversation.id.in_(ids))
        )).scalars().all()}
        resultado_filas = []
        for f in filas:
            conv = conversaciones[f["conversation_id"]]
            lead = await session.get(Lead, f["telefono"])
            ultimo_cliente = (await session.execute(
                select(Mensaje.timestamp).where(Mensaje.telefono == f["telefono"], Mensaje.role == "user")
                .order_by(Mensaje.timestamp.desc()).limit(1)
            )).first()
            ultimo_cliente = ultimo_cliente[0] if ultimo_cliente else None
            evs = por_conv.get(f["conversation_id"], [])
            t1 = evs[0][1] if evs else None
            t2 = next((c for s_, c in evs if s_ != evs[0][0]), None)
            resultado = lead.resultado if lead else None
            asesor = (lead.asesor_asignado if lead else None) or conv.asesor_asignado_id
            cerrado_en = conv.cerrado_definitivamente_en or (lead.cerrado_definitivamente_en if lead else None)
            if cerrado_en is not None:
                motivo = "ya_cerrada_definitivamente"
            elif resultado == "vendido":
                motivo = "vendido_nunca_se_cierra_solo"
            elif resultado not in RESULTADOS_CERRADOS:
                motivo = "resultado_abierto_o_sin_resultado"
            elif not asesor:
                motivo = "cerrado_sin_asesor_la_regla_no_aplica"
            elif ultimo_cliente is None or ultimo_cliente >= ahora - timedelta(days=dias_silencio):
                motivo = "cliente_activo_menos_de_7_dias"
            else:
                motivo = "cumple_la_regla_pero_no_se_cerro"
            resultado_filas.append({
                "telefono": "…" + (f["telefono"] or "")[-4:], "primer_anuncio": f["primero"], "otros_anuncios": f["otros"],
                "conversacion_estado": conv.estado, "resultado": resultado, "tiene_asesor": bool(asesor),
                "primer_contacto": t1, "segundo_anuncio_en": t2,
                "dias_entre_anuncios": round((t2 - t1).total_seconds() / 86400, 1) if t1 and t2 else None,
                "ultimo_mensaje_cliente": ultimo_cliente,
                "dias_sin_responder_el_cliente": round((ahora - ultimo_cliente).total_seconds() / 86400, 1) if ultimo_cliente else None,
                "cerrada_definitivamente_en": cerrado_en, "motivo": motivo,
            })
    por_motivo: dict[str, int] = {}
    for r in resultado_filas:
        por_motivo[r["motivo"]] = por_motivo.get(r["motivo"], 0) + 1
    return {"total": len(resultado_filas), "por_motivo": por_motivo, "conversaciones": resultado_filas}


async def diagnostico_atribucion_multiple(negocio_id: str) -> dict:
    """Solo lectura. Conversaciones con anuncios de dos orígenes, agrupadas por primer
    anuncio y campaña actual, y cuántas NO coinciden con la regla de su primer anuncio."""
    async with async_session() as session:
        filas = await _conversaciones_con_varios_anuncios(session, negocio_id)
    grupos: dict[tuple, dict] = {}
    for f in filas:
        clave = (f["primero"], f["campana_actual"], f["regla_primero"])
        g = grupos.setdefault(clave, {
            "primer_anuncio": f["primero"], "headline": f["headline"], "campana_actual": f["campana_actual"],
            "campana_regla_del_primero": f["regla_primero"], "conversaciones": 0, "otros_anuncios": set(),
        })
        g["conversaciones"] += 1
        g["otros_anuncios"].update(f["otros"])
    no_coinciden = sum(
        1 for f in filas if f["regla_primero_id"] is not None and f["regla_primero_id"] != f["campana_actual_id"]
    )
    return {
        "conversaciones_con_varios_anuncios": len(filas), "no_coinciden_con_su_primer_anuncio": no_coinciden,
        "grupos": [{**g, "otros_anuncios": sorted(g["otros_anuncios"])[:6]} for g in grupos.values()],
    }


async def historico_recalcular_primer_anuncio(negocio_id: str, aplicar: bool, autor: str | None = None) -> dict:
    """Cada conversación con anuncios de dos orígenes vuelve a la campaña de la regla de su
    PRIMER anuncio (la regla de primer contacto). El lead se corrige solo si su campaña era
    la que tenía esa conversación y su primer anuncio es el de la conversación. No toca la
    evidencia. Con `aplicar=False` solo cuenta. Revertible con `historico_revertir`."""
    async with async_session() as session:
        filas = await _conversaciones_con_varios_anuncios(session, negocio_id)
        _, por_lead = await _primer_anuncio_por_conversation(session, negocio_id)
        campanas = {c.id: c.nombre for c in (await session.execute(
            select(Campana).where(Campana.negocio_id == negocio_id)
        )).scalars().all()}
        cambios_conv, cambios_lead = [], []
        for f in filas:
            nueva_id = f["regla_primero_id"]
            if nueva_id is None or nueva_id == f["campana_actual_id"]:
                continue
            cambios_conv.append({
                "conversation_id": f["conversation_id"], "campana_anterior_id": f["campana_actual_id"],
                "campana_nueva_id": nueva_id,
            })
            lead = await session.get(Lead, f["telefono"])
            anterior = campanas.get(f["campana_actual_id"])
            if (
                lead is not None and lead.negocio_id == negocio_id and anterior is not None
                and lead.campana_origen == anterior and por_lead.get(f["telefono"]) == f["primero"]
                and not any(x["lead_telefono"] == f["telefono"] for x in cambios_lead)
            ):
                cambios_lead.append({
                    "lead_telefono": f["telefono"], "campana_anterior": anterior, "campana_nueva": campanas[nueva_id],
                })
        por_campana: dict[str, int] = {}
        for c in cambios_conv:
            nombre = campanas[c["campana_nueva_id"]]
            por_campana[nombre] = por_campana.get(nombre, 0) + 1
        resumen = {"conversaciones": len(cambios_conv), "leads": len(cambios_lead), "por_campana": por_campana}
        if not aplicar or not cambios_conv:
            return {"aplicado": False, **resumen}
        for c in cambios_conv:
            conv = await session.get(Conversation, c["conversation_id"])
            conv.campana_origen_id = c["campana_nueva_id"]
        for c in cambios_lead:
            lead = await session.get(Lead, c["lead_telefono"])
            lead.campana_origen = c["campana_nueva"]
            lead.actualizado = datetime.utcnow()
        await session.commit()
    auditoria_id = await registrar_auditoria(
        "atribucion_historica_corregida", actor=autor, negocio_id=negocio_id, entidad_tipo="conversation", entidad_id="*",
        payload={"origen": "recalcular_primer_anuncio", "conversaciones": cambios_conv, "leads": cambios_lead},
    )
    return {"aplicado": True, "auditoria_id": auditoria_id, **resumen}


async def historico_rellenar_conversaciones(negocio_id: str, aplicar: bool, autor: str | None = None) -> dict:
    """Conversaciones SIN campaña cuyo evento de anuncio SÍ resolvió una (lead que
    volvió por un anuncio y su conversación nueva no la tomó): se les atribuye la
    campaña que el propio evento resolvió. Solo `Conversation.campana_origen_id`;
    nunca `Lead.campana_origen`. Con `aplicar=False` solo cuenta."""
    async with async_session() as session:
        campanas = {c.nombre: c.id for c in (await session.execute(
            select(Campana).where(Campana.negocio_id == negocio_id)
        )).scalars().all()}
        eventos = (await session.execute(
            select(AttributionEvent.conversation_id, AttributionEvent.campana_nombre, AttributionEvent.source_id)
            .join(Conversation, Conversation.id == AttributionEvent.conversation_id)
            .where(
                AttributionEvent.negocio_id == negocio_id, AttributionEvent.tipo_origen == "meta_ads",
                AttributionEvent.campana_nombre.is_not(None), Conversation.campana_origen_id.is_(None),
            )
            .order_by(AttributionEvent.creado.asc(), AttributionEvent.id.asc())
        )).all()
        # Solo si la regla ACTUAL del anuncio sigue siendo esa campaña: un anuncio sin regla (por
        # ejemplo uno corregido a "Sin campaña") o con otra campaña no se vuelve a rellenar con la
        # evidencia vieja del evento.
        reglas = await obtener_reglas_anuncio(negocio_id)
        elegido: dict[str, tuple[str, str]] = {}
        for conversation_id, nombre, source_id in eventos:
            if nombre in campanas and reglas.get(source_id) == campanas[nombre]:
                elegido.setdefault(conversation_id, (nombre, source_id))
        resumen: dict = {"conversaciones": len(elegido), "por_campana": {}}
        for nombre, _ in elegido.values():
            resumen["por_campana"][nombre] = resumen["por_campana"].get(nombre, 0) + 1
        if not aplicar or not elegido:
            return {"aplicado": False, **resumen}
        for conversation_id, (nombre, _) in elegido.items():
            conversation = await session.get(Conversation, conversation_id)
            conversation.campana_origen_id = campanas[nombre]
        await session.commit()
    auditoria_id = await registrar_auditoria(
        "atribucion_historica_rellenada", actor=autor, negocio_id=negocio_id, entidad_tipo="conversation", entidad_id="*",
        payload={"conversaciones": [
            {"conversation_id": c, "campana_anterior_id": None, "campana_nueva_id": campanas[n]} for c, (n, _) in elegido.items()
        ]},
    )
    return {"aplicado": True, "auditoria_id": auditoria_id, **resumen}


async def historico_corregir_anuncios(
    negocio_id: str, source_ids: list[str], campana_id: int | None, aplicar: bool, autor: str | None = None,
    desde_campana_ids: list[int] | None = None,
) -> dict:
    """Corrige la atribución HISTÓRICA de los anuncios dados: las conversaciones
    cuyo PRIMER anuncio es uno de ellos y hoy están en una de las campañas
    `desde_campana_ids` (las comodín que atribuyeron mal) pasan a
    `campana_id` (None = sin campaña). El lead (`Lead.campana_origen`) solo se
    corrige si su primer anuncio es uno de ellos y su campaña era la comodín de
    esa conversación. No toca la evidencia (AttributionEvent). Guarda en la
    auditoría el valor anterior de cada cambio para poder revertirlo."""
    if not source_ids:
        raise ValueError("Falta al menos un anuncio.")
    if not desde_campana_ids:
        raise ValueError("Indica de qué campañas se corrige (desde_campana_ids).")
    elegidos = set(source_ids)
    async with async_session() as session:
        campanas = {c.id: c for c in (await session.execute(
            select(Campana).where(Campana.negocio_id == negocio_id)
        )).scalars().all()}
        if campana_id is not None and campana_id not in campanas:
            raise LookupError("La campaña no existe.")
        comodin_ids = {i for i in desde_campana_ids if i in campanas}
        por_conversation, por_lead = await _primer_anuncio_por_conversation(session, negocio_id)
        objetivo = {cid: tel for cid, (src, tel) in por_conversation.items() if src in elegidos}
        conversaciones = (await session.execute(
            select(Conversation).where(
                Conversation.negocio_id == negocio_id, Conversation.id.in_(list(objetivo) or [""]),
                Conversation.campana_origen_id.in_(list(comodin_ids) or [-1]),
            )
        )).scalars().all()
        nueva = campanas[campana_id].nombre if campana_id is not None else None
        cambios_conv, cambios_lead = [], []
        for conv in conversaciones:
            telefono = objetivo[conv.id]
            cambios_conv.append({
                "conversation_id": conv.id, "campana_anterior_id": conv.campana_origen_id, "campana_nueva_id": campana_id,
            })
            lead = await session.get(Lead, telefono)
            nombre_anterior = campanas[conv.campana_origen_id].nombre
            if (
                lead is not None and lead.negocio_id == negocio_id and lead.campana_origen == nombre_anterior
                and por_lead.get(telefono) in elegidos
                and not any(x["lead_telefono"] == telefono for x in cambios_lead)
            ):
                cambios_lead.append({"lead_telefono": telefono, "campana_anterior": nombre_anterior, "campana_nueva": nueva})
        resumen = {"conversaciones": len(cambios_conv), "leads": len(cambios_lead), "campana_nueva": nueva}
        if not aplicar or not cambios_conv:
            return {"aplicado": False, **resumen}
        por_id = {c.id: c for c in conversaciones}
        for cambio in cambios_conv:
            por_id[cambio["conversation_id"]].campana_origen_id = campana_id
        for cambio in cambios_lead:
            lead = await session.get(Lead, cambio["lead_telefono"])
            lead.campana_origen = nueva
            lead.actualizado = datetime.utcnow()
        await session.commit()
    auditoria_id = await registrar_auditoria(
        "atribucion_historica_corregida", actor=autor, negocio_id=negocio_id, entidad_tipo="anuncio", entidad_id="*",
        payload={"source_ids": list(source_ids), "campana_id": campana_id, "conversaciones": cambios_conv, "leads": cambios_lead},
    )
    return {"aplicado": True, "auditoria_id": auditoria_id, **resumen}


async def historico_revertir(negocio_id: str, auditoria_id: str, autor: str | None = None) -> dict:
    """Deshace una corrección/relleno histórico: devuelve cada conversación y lead al valor
    anterior guardado en la auditoría. Solo si la fila es de este Negocio y de un tipo
    de corrección histórica."""
    async with async_session() as session:
        fila = await session.get(RegistroAuditoria, auditoria_id)
        if fila is None or fila.negocio_id != negocio_id or fila.accion not in (
            "atribucion_historica_corregida", "atribucion_historica_rellenada", "campanas_comodin_migradas",
        ):
            raise LookupError("No existe esa corrección.")
        payload = fila.payload or {}
        if fila.accion == "campanas_comodin_migradas":
            for c in payload.get("campanas", []):
                campana = await session.get(Campana, c["id"])
                if campana is not None and campana.negocio_id == negocio_id:
                    campana.tipo_deteccion = c["tipo_anterior"]
            await session.execute(delete(AnuncioCampana).where(
                AnuncioCampana.negocio_id == negocio_id, AnuncioCampana.source_id.in_(payload.get("reglas", []) or [""]),
            ))
            await session.commit()
            resumen = {"campanas": len(payload.get("campanas", [])), "reglas": len(payload.get("reglas", []))}
            await registrar_auditoria(
                "atribucion_historica_revertida", actor=autor, negocio_id=negocio_id, entidad_tipo="auditoria",
                entidad_id=auditoria_id, payload=resumen,
            )
            return resumen
        for cambio in payload.get("conversaciones", []):
            conv = await session.get(Conversation, cambio["conversation_id"])
            if conv is not None and conv.negocio_id == negocio_id:
                conv.campana_origen_id = cambio["campana_anterior_id"]
        for cambio in payload.get("leads", []):
            lead = await session.get(Lead, cambio["lead_telefono"])
            if lead is not None and lead.negocio_id == negocio_id:
                lead.campana_origen = cambio["campana_anterior"]
                lead.actualizado = datetime.utcnow()
        await session.commit()
        resumen = {"conversaciones": len(payload.get("conversaciones", [])), "leads": len(payload.get("leads", []))}
    await registrar_auditoria(
        "atribucion_historica_revertida", actor=autor, negocio_id=negocio_id, entidad_tipo="auditoria",
        entidad_id=auditoria_id, payload=resumen,
    )
    return resumen


async def crear_campana_de_anuncio(nombre: str, source_id: str, negocio_id: str, autor: str | None = None, **extra) -> dict:
    """Campaña de un anuncio de Meta: tipo `por_anuncio` + su regla anuncio→campaña
    (el ID del anuncio es el único dato que la reconoce)."""
    campana = await crear_campana(
        nombre=nombre, tipo_deteccion="por_anuncio", patron=source_id.lower(), negocio_id=negocio_id, **extra,
    )
    await guardar_regla_anuncio(negocio_id, source_id, campana["id"], autor=autor)
    return campana


async def asignar_anuncio_a_campana(negocio_id: str, source_id: str, campana_id: int, autor: str | None = None) -> dict:
    """Decisión humana: asigna a una campaña los leads y conversaciones que ENTRARON
    PRIMERO por este anuncio, reemplazando la que tuvieran (incluso "sin campaña").
    Lo que llegó antes por otro anuncio no se toca (regla de primer contacto). Escribe en los dos
    lugares que hoy leen las pantallas: `Conversation.campana_origen_id`
    (Analítica) y `Lead.campana_origen` (Pipeline/Ficha). La evidencia de
    atribución original no se toca (append-only). Todo scoped por Negocio.

    Levanta `LookupError` si la campaña o el anuncio no existen en el Negocio."""
    async with async_session() as session:
        campana = await session.get(Campana, campana_id)
        if campana is None or campana.negocio_id != negocio_id:
            raise LookupError("La campaña no existe.")
        eventos = (await session.execute(
            select(AttributionEvent).where(
                AttributionEvent.negocio_id == negocio_id, AttributionEvent.source_id == source_id,
                AttributionEvent.tipo_origen.in_(_TIPOS_ORIGEN_ANUNCIO),
            )
        )).scalars().all()
        if not eventos:
            raise LookupError("Ese anuncio no tiene leads registrados.")

        # Solo lo que ENTRÓ primero por este anuncio: una conversación (o un lead) que llegó por
        # otro anuncio y después vio éste conserva la campaña de su primer contacto.
        por_conversation, por_lead = await _primer_anuncio_por_conversation(session, negocio_id)
        propias = {cid for cid, (src, _) in por_conversation.items() if src == source_id}
        telefonos = {tel for tel, src in por_lead.items() if src == source_id}
        conversaciones = (await session.execute(
            select(Conversation).where(
                Conversation.negocio_id == negocio_id, Conversation.id.in_(propias or {""}),
            )
        )).scalars().all()
        for conversation in conversaciones:
            conversation.campana_origen_id = campana.id
        leads = (await session.execute(
            select(Lead).where(Lead.negocio_id == negocio_id, Lead.telefono.in_(telefonos or {""}))
        )).scalars().all()
        for lead in leads:
            lead.campana_origen = campana.nombre
            lead.actualizado = datetime.utcnow()
        await session.commit()

    # Los leads FUTUROS de este anuncio también caen en esta campaña (regla explícita).
    await guardar_regla_anuncio(negocio_id, source_id, campana_id, autor=autor)

    resumen = {"conversaciones": len(conversaciones), "leads": len(leads)}
    await registrar_auditoria(
        "anuncio_asignado_a_campana", actor=autor, negocio_id=negocio_id,
        entidad_tipo="campana", entidad_id=str(campana_id), payload={"source_id": source_id, **resumen},
    )
    return resumen


async def intentar_avanzar_version(telefono: str, version_esperada: int) -> bool:
    """Concurrencia optimista (MAIEK_AI_PRODUCT_PATTERNS.md, Cap. 6 —
    conflicto de edición): avanza la versión del lead en +1 SOLO si sigue en
    la versión esperada (la que tenía cuando el usuario abrió el formulario).
    True si se pudo (nadie más escribió antes) — en ese caso, quien llama
    debe aplicar su cambio a continuación. False si alguien más ya avanzó la
    versión — no se aplica nada, y quien llama debe mostrar el conflicto
    explícitamente en vez de sobrescribir en silencio (Human Decision Gate).

    El chequeo de versión NO alcanza con comparar en Python y después
    escribir (`session.get()` + comparar + `lead.version += 1` + commit):
    entre la comparación y el commit hay una ventana en la que otra escritura
    concurrente puede leer la misma versión, y las dos se dan por ganadoras
    — comprobado con dos escrituras realmente simultáneas (Gate 3.2): ambas
    devolvían True y el incremento se perdía. Mismo defecto y mismo arreglo
    que ya tenía Productos (ver editar_producto/toggle_producto): la
    condición de versión viaja DENTRO del propio UPDATE
    (`WHERE telefono = ... AND version = ...`), que la base evalúa de forma
    atómica — si otra escritura ya ganó, el UPDATE afecta 0 filas."""
    async with async_session() as session:
        resultado = await session.execute(
            update(Lead)
            .where(Lead.telefono == telefono, Lead.version == version_esperada)
            .values(version=version_esperada + 1)
        )
        if resultado.rowcount == 0:
            await session.rollback()
            return False
        await session.commit()
        return True


def _avanzar_version(lead: "Lead", es_nuevo: bool = False):
    """Incremento INCONDICIONAL de la versión del lead, para las escrituras
    AUTOMÁTICAS (reasignación de Gabi, liberación de un caso cerrado).

    No se puede reusar `intentar_avanzar_version` acá: esa función es
    condicional —solo avanza si el lead sigue en la versión esperada— y su
    valor de retorno significa "no apliques tu cambio". Un flujo automático
    no tiene una "versión esperada" (nadie abrió un formulario) y NUNCA debe
    quedar bloqueado por lo que esté haciendo un humano en el panel: la
    reasignación tiene que proceder igual. Lo que cambia al avanzar el
    contador acá es la otra mitad del problema: un cierre HUMANO que venía
    con la versión vieja ahora choca (409) en vez de sobrescribir en silencio
    un lead que ya cambió de dueño.

    Recibe el objeto Lead ya cargado en la sesión de quien llama, para que el
    incremento entre en el MISMO commit que el cambio que lo justifica (una
    sola escritura, no dos).

    `es_nuevo=True` es el único caso en que se lee/escribe en Python
    (`lead.version = 1`): un Lead recién construido en esta misma
    transacción (`Lead(telefono=...)`, todavía sin fila propia) no puede
    tener ninguna escritura concurrente real —nadie más puede estar
    actualizando una fila que todavía no existe—, así que no hay carrera que
    proteger. Para un lead EXISTENTE (el caso normal), `Lead.version + 1` es
    una expresión SQL, no un entero de Python: SQLAlchemy la evalúa en el
    propio UPDATE (`SET version = version + 1`) contra el valor que la base
    tiene en ese instante, no contra la copia en memoria de esta sesión —
    mismo motivo por el que `intentar_avanzar_version` dejó de leer-y-sumar
    en Python (Gate 3.2): dos incrementos automáticos concurrentes (o uno
    automático y uno humano) ya no pueden pisarse y perder una cuenta."""
    lead.version = 1 if es_nuevo else Lead.version + 1


def _es_transicion_a_vendido(lead: "Lead", campos: dict) -> bool:
    """True solo si esta escritura hace pasar el lead a "vendido" viniendo de
    otro estado — no si ya estaba vendido y solo se está reeditando la venta.
    Se evalúa ANTES de aplicar los campos (necesita el valor anterior)."""
    return campos.get("resultado") == "vendido" and lead.resultado != "vendido"


def _marcar_cierre_vendido(lead: "Lead"):
    """Efectos de la transición real a "vendido", en un solo lugar para que
    valgan por igual en las dos vías que la producen (guardar el carrito de
    Cierre de venta, y elegir "Vendido" en el selector de resultado):

    - `fecha_cierre`: instante real del cierre, una sola vez.
    - `pausado_manual = True`: el caso quedó cerrado, Gabi no debe seguir
      vendiéndole al cliente. Se reusa el campo que ya existe y que main.py
      ya consulta para pausar al bot, en vez de agregar un flag paralelo.
      OJO: esto aplica SOLO a "vendido", no a los otros 7 resultados
      cerrados (no_interesado, no_califica, …) — el alcance decidido es la
      venta cerrada, no cualquier cierre."""
    lead.fecha_cierre = datetime.utcnow()
    lead.pausado_manual = True


class Contact(Base):
    """Gate 5.3 — identidad del cliente, independiente del hilo conversacional
    (Conversation) y del ciclo comercial (Opportunity). Arquitectura
    Contractual §8: `telefono` deja de ser identidad global — el mismo número
    puede existir como Contact DISTINTO en dos Negocios (unique compuesto
    negocio_id+telefono, nunca telefono solo)."""
    __tablename__ = "contacts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_generar_uuid)
    negocio_id: Mapped[str] = mapped_column(String(36), ForeignKey("negocios.id"), nullable=False, index=True)
    # 150, no 50 — ver Mensaje.telefono (BSUID de Meta, Gate 2026-09-22).
    telefono: Mapped[str] = mapped_column(String(150), nullable=False)
    nombre: Mapped[str | None] = mapped_column(String(100), nullable=True)
    eliminado_en: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    eliminado_por: Mapped[str | None] = mapped_column(String(50), nullable=True)
    # "Para llamar" (2026-10-09): desde este instante (UTC) la persona pidió que NO se la llame. Se revisa antes de
    # crear cualquier tarea de llamada y antes de cada intento; nunca se borra solo.
    no_llamar_en: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    creado: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    actualizado: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, index=True)

    __table_args__ = (
        Index("ix_contact_negocio_telefono", "negocio_id", "telefono", unique=True),
    )


class Conversation(Base):
    """Gate 5.3 — hilo conversacional con un Contact (Arquitectura Contractual
    §9). Un Contact puede tener varias Conversation SUCESIVAS en el tiempo
    (DR-4, Resolución Arquitectónica Gate 5.3) — nunca simultáneas: solo una
    puede estar `estado == "activa"` a la vez para un mismo Contact."""
    __tablename__ = "conversations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_generar_uuid)
    negocio_id: Mapped[str] = mapped_column(String(36), ForeignKey("negocios.id"), nullable=False, index=True)
    # Heredado del Canal — nullable SOLO mientras CanalWhatsApp.unidad_id siga
    # nullable por la excepción de migración legada (Arquitectura Contractual
    # §6). Nunca se inventa un valor.
    unidad_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("unidades_de_negocio.id"), nullable=True, index=True)
    contact_id: Mapped[str] = mapped_column(String(36), ForeignKey("contacts.id"), nullable=False, index=True)
    # Integer real — CanalWhatsApp.id NO migra a UUID en este Gate (Data
    # Architecture v1 ya lo excluye explícitamente de migración retroactiva,
    # confirmado en Diseño Técnico Gate 5.3 §5).
    canal_id: Mapped[int] = mapped_column(Integer, ForeignKey("canales_whatsapp.id"), nullable=False, index=True)
    campana_origen_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("campanas.id", ondelete="SET NULL"), nullable=True)
    # "activa" | "cerrada" — se marca "cerrada" únicamente en el instante en
    # que DR-4 abre una Conversation nueva para el mismo Contact (efecto
    # automático, sin chequeo de version — mismo criterio que _avanzar_version).
    estado: Mapped[str] = mapped_column(String(20), nullable=False, default="activa", index=True)
    # String suelto sin FK, NO Usuario.username — mismo patrón que
    # Lead.asesor_asignado hoy (Usuario migra a PK UUID recién en Gate 5.4).
    asesor_asignado_id: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)
    paso_flujo: Mapped[str | None] = mapped_column(String(50), nullable=True)
    origen_contacto: Mapped[str | None] = mapped_column(String(30), nullable=True)
    visto_asesor: Mapped[bool] = mapped_column(Boolean, default=True)
    fallos_tecnicos: Mapped[int] = mapped_column(Integer, default=0)
    pausado_manual: Mapped[bool] = mapped_column(Boolean, default=False)
    # Mirror get-only de Lead.cerrado_definitivamente_en (Gate 2026-09-23,
    # mismo patrón que pausado_manual/asesor_asignado_id de arriba) — la
    # Nueva Experiencia (`_dto_conversation_detalle`, dashboard.py) lee
    # esto, nunca Lead directamente. agent/main.py (webhook) sigue
    # leyendo/escribiendo Lead como fuente real; acá solo se refleja.
    cerrado_definitivamente_en: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    revision_prioritaria: Mapped[bool] = mapped_column(Boolean, default=False)
    # Concurrencia optimista propia — separada de Opportunity.version (DR-1,
    # Resolución Arquitectónica Gate 5.3: partir Lead.version en las dos
    # entidades que hoy comparten un solo contador).
    version: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    creado: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    actualizado: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, index=True)
    # Hora del ÚLTIMO MENSAJE real (cliente, Gabi o asesor) — 2026-10-03.
    # `actualizado` mezclaba dos cosas: "hubo un mensaje" y "algo cambió"
    # (asignar, rotar, liberar, cierre automático), así que los Cron de
    # cierre subían al tope de la Bandeja 57 chats sin actividad real. La
    # Bandeja ordena y muestra esta columna; `actualizado` queda como "última
    # modificación". Solo la escribe `guardar_mensaje` (y nace con la fila).
    ultimo_mensaje_en: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, default=datetime.utcnow, index=True)

    __table_args__ = (
        Index("ix_conversation_negocio_unidad", "negocio_id", "unidad_id"),
        Index("ix_conversation_contact_creado", "contact_id", "creado"),
        Index("ix_conversation_negocio_asesor", "negocio_id", "asesor_asignado_id"),
        # Gate 5.6 — optimización recomendada (no bloqueante) para
        # contar_opportunities_por_campana(); ver migración 4642f3d55e15
        # para la nota completa sobre por qué es un índice simple, no el
        # compuesto (negocio_id, campana_origen_id) sugerido originalmente.
        Index("ix_conversation_campana_origen", "campana_origen_id"),
        # Gate 5.5 — hallazgo de concurrencia del checkpoint de investigación:
        # DR-4 ("nunca simultáneas") estaba declarada acá arriba pero no
        # forzada por la base — dos webhooks concurrentes para el mismo
        # Contact podían, bajo Postgres, crear dos Conversation con
        # estado="activa". SQLite serializa escrituras a nivel de archivo y
        # enmascaraba el riesgo en desarrollo local. Mismo patrón que
        # ix_config_global_unica/ix_config_por_negocio_unica (índice único
        # parcial, sqlite_where + postgresql_where) — resolver_conversation_
        # activa() atrapa el IntegrityError y relee la fila que ganó la
        # carrera en vez de fallar el request.
        Index(
            "ix_conversation_una_activa_por_contact", "contact_id", unique=True,
            sqlite_where=text("estado = 'activa'"),
            postgresql_where=text("estado = 'activa'"),
        ),
    )


class Opportunity(Base):
    """Gate 5.3 — ciclo comercial dentro de una Conversation (Arquitectura
    Contractual §10). 1 Conversation : 0..N Opportunity, secuencial en el
    tiempo (DR-3) — se crea única y exclusivamente en el mismo instante en
    que se crea una Conversation nueva, nunca dentro de una ya existente
    (sin evidencia de necesidad de Opportunities simultáneas, Diseño Técnico
    Gate 5.3 §6)."""
    __tablename__ = "opportunities"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_generar_uuid)
    negocio_id: Mapped[str] = mapped_column(String(36), ForeignKey("negocios.id"), nullable=False, index=True)
    unidad_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("unidades_de_negocio.id"), nullable=True, index=True)
    conversation_id: Mapped[str] = mapped_column(String(36), ForeignKey("conversations.id"), nullable=False, index=True)
    contact_id: Mapped[str] = mapped_column(String(36), ForeignKey("contacts.id"), nullable=False, index=True)  # denormalizado, Arquitectura Contractual §10
    interes: Mapped[str | None] = mapped_column(String(200), nullable=True)
    producto_tipo: Mapped[str | None] = mapped_column(String(50), nullable=True)
    producto_marca: Mapped[str | None] = mapped_column(String(50), nullable=True)
    producto_modalidad: Mapped[str | None] = mapped_column(String(20), nullable=True)
    resultado: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)
    fecha_agendada: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    fecha_cierre: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    modalidad_pago: Mapped[str | None] = mapped_column(String(30), nullable=True)
    cuotas: Mapped[str | None] = mapped_column(String(10), nullable=True)
    # Pacto congelado — mismo significado que en Lead (ver allá).
    monto_financiado: Mapped[str | None] = mapped_column(String(30), nullable=True)
    cuota_pactada: Mapped[str | None] = mapped_column(String(30), nullable=True)
    tea_pactada: Mapped[str | None] = mapped_column(String(10), nullable=True)
    igv_pactado: Mapped[str | None] = mapped_column(String(10), nullable=True)
    medio_pago: Mapped[str | None] = mapped_column(String(50), nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    creado: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    actualizado: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        Index("ix_opportunity_negocio_resultado", "negocio_id", "resultado"),
        Index("ix_opportunity_conversation_creado", "conversation_id", "creado"),
    )


class LineaVenta(Base):
    """Un producto o servicio dentro del cierre de venta de una Opportunity —
    un cliente puede comprar un artefacto, varios, un servicio, o un mix de
    ambos, así que la venta es una LISTA de líneas en vez de un solo
    producto. La forma de pago (modalidad_pago/cuotas/medio_pago) sigue
    siendo una sola para toda la venta y vive en Opportunity, no acá.

    Gate 5.3 — REGLA CRÍTICA: `telefono` se ELIMINA de esta tabla. Antes de
    este Gate, `registrar_venta_opportunity` (ex `guardar_venta`) hacía
    `DELETE ... WHERE telefono = :telefono` — seguro mientras `Lead.telefono`
    era PK global, pero un riesgo real de fuga/corrupción cross-negocio en
    cuanto `Contact.telefono` deja de ser único globalmente (dos Negocios
    pueden compartir número). Todo reemplazo de líneas filtra por
    `opportunity_id` (clave fuerte, única globalmente) + `negocio_id`
    redundante — doble candado, nunca telefono en solitario (hallazgo del
    bloque de Decisiones Arquitectónicas Gate 5.3, confirmado por 2 agentes
    de forma independiente)."""
    __tablename__ = "lineas_venta"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    opportunity_id: Mapped[str] = mapped_column(String(36), ForeignKey("opportunities.id"), nullable=False, index=True)
    negocio_id: Mapped[str] = mapped_column(String(36), ForeignKey("negocios.id"), nullable=False, index=True)
    # Producto real del catálogo que se eligió al armar el carrito
    # (Producto.id). Nullable a propósito por DOS motivos, no uno: (a) las
    # líneas históricas, guardadas antes de este campo, no lo tienen y no hay
    # forma segura de deducirlo (la descripción se copia como texto y CODIGO
    # HANA no es único); (b) el cierre de venta sigue admitiendo el modo
    # manual ("¿No está en la lista? Agregar manualmente"), donde por
    # definición no hay producto de catálogo detrás. Sin ForeignKey estricta,
    # mismo criterio que asesor_asignado/archivo_id.
    producto_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    producto: Mapped[str] = mapped_column(String(300))
    precio: Mapped[str | None] = mapped_column(String(30), nullable=True)
    marca: Mapped[str | None] = mapped_column(String(100), nullable=True)
    proveedor: Mapped[str | None] = mapped_column(String(150), nullable=True)
    creado: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        Index("ix_lineaventa_opportunity_negocio", "opportunity_id", "negocio_id"),
    )


class TareaLlamada(Base):
    """"Para llamar" (2026-10-09, diseño D3; lógica en agent/llamadas.py): tarea de llamada para un lead CALLADO que
    mostró interés. Es una tarea SUPERPUESTA a la conversación: no es una etapa del Pipeline, ni un resultado, ni un
    `paso_flujo`, y NO reutiliza `derivado_asesor` (eso pausaría a Gabi, mandaría correo, armaría el reloj de
    rotación 30+30 e inflaría el embudo). Gabi sigue activa mientras la tarea está abierta.

    `estado`: programada (aún no accionable: fuera de horario o con hora futura) | pendiente (accionable, con asesor
    o esperando uno) | cumplida | agotada | cancelada | expirada. `modo`: sombra (solo se registra para medir; nadie
    la ve ni se llama) | activo. `grupo`: llamar | control (holdout: se registra pero NUNCA se muestra ni se llama,
    para medir el efecto real de llamar). `segmento`: A | B | exploracion. `senales`: foto de por qué puntuó lo
    que puntuó (banderas y números, nunca texto de mensajes ni nombres). El asesor vive en la TAREA, no en
    `Lead.asesor_asignado`: asignar la tarea no pausa a Gabi.

    Un índice único parcial garantiza a lo sumo UNA tarea abierta por conversación (idempotencia ante dos corridas
    simultáneas del Cron)."""
    __tablename__ = "tareas_llamada"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_generar_uuid)
    negocio_id: Mapped[str] = mapped_column(String(36), ForeignKey("negocios.id"), nullable=False, index=True)
    conversation_id: Mapped[str] = mapped_column(String(36), ForeignKey("conversations.id"), nullable=False, index=True)
    contact_id: Mapped[str] = mapped_column(String(36), ForeignKey("contacts.id"), nullable=False, index=True)
    # Copia para mostrar (150, como Mensaje.telefono: un BSUID es más largo que un teléfono).
    telefono: Mapped[str] = mapped_column(String(150), nullable=False)
    estado: Mapped[str] = mapped_column(String(20), nullable=False, default="pendiente", index=True)
    motivo_cierre: Mapped[str | None] = mapped_column(String(40), nullable=True)
    segmento: Mapped[str] = mapped_column(String(20), nullable=False)
    puntaje: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    senales: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    grupo: Mapped[str] = mapped_column(String(10), nullable=False, default="llamar")
    modo: Mapped[str] = mapped_column(String(10), nullable=False, default="sombra")
    asesor_username: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)
    asignada_en: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    programada_para: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    intentos: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    ultimo_intento_en: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    proximo_intento_en: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    resultado_llamada: Mapped[str | None] = mapped_column(String(40), nullable=True)
    nota: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # Cuántas veces el SLA la reasignó a otro asesor (máx. 1) y cuándo pasó a "sin hacer" visible al supervisor.
    reasignaciones: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    escalada_en: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    creada_en: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow, index=True)
    cerrada_en: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    vence_en: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    __table_args__ = (
        Index("ix_tareas_llamada_negocio_estado", "negocio_id", "estado"),
        Index(
            "ix_tarea_llamada_una_abierta_por_conversation", "conversation_id", unique=True,
            sqlite_where=text("estado IN ('programada', 'pendiente')"),
            postgresql_where=text("estado IN ('programada', 'pendiente')"),
        ),
    )


# ── Gate 5.3 — Identidad técnica: Contact / Conversation / Opportunity ──
#
# Diseño Técnico Gate 5.3 §10. `negocio_id` siempre resuelto server-side
# (nunca del payload) — la única fuente legítima es CanalWhatsApp.negocio_id
# en el punto de entrada (webhook), o el Lead/Contact ya existente para
# escrituras posteriores sobre un hilo ya abierto.


async def _obtener_contact(session, negocio_id: str, telefono: str) -> "Contact | None":
    query = select(Contact).where(
        Contact.negocio_id == negocio_id, Contact.telefono == telefono, Contact.eliminado_en.is_(None),
    )
    return (await session.execute(query)).scalar_one_or_none()


async def obtener_o_crear_contact(session, negocio_id: str, telefono: str, nombre: str | None = None) -> "Contact":
    """Identidad del cliente — negocio_id SIEMPRE resuelto server-side por
    quien llama (Diseño Técnico Gate 5.3 §10). No crea un Contact "adivinado":
    si ya existe, lo retorna tal cual (no pisa `nombre` — mismo criterio que
    Lead: el nombre se actualiza aparte, explícitamente, no como efecto
    colateral de resolver identidad).

    Gate 5.5 — mismo hallazgo de concurrencia que `resolver_conversation_
    activa`, un nivel más abajo: `ix_contact_negocio_telefono` (único,
    Gate 5.3) ya candadeaba la fila, pero sin manejar la colisión — dos
    webhooks concurrentes para un Contact nuevo podían ambos ver "no existe"
    y ambos intentar insertarlo, tumbando al perdedor con un
    `IntegrityError` sin atrapar. Mismo patrón que el resto del Gate 5.5:
    insert + catch, releer al que ganó la carrera."""
    contact = await _obtener_contact(session, negocio_id, telefono)
    if contact is None:
        contact_nuevo = Contact(negocio_id=negocio_id, telefono=telefono, nombre=nombre)
        session.add(contact_nuevo)
        try:
            await session.flush()
        except IntegrityError:
            await session.rollback()
            contact = await _obtener_contact(session, negocio_id, telefono)
            if contact is None:
                raise
            return contact
        contact = contact_nuevo
    return contact


async def _obtener_conversation_activa(session, contact_id: str) -> "Conversation | None":
    """La Conversation con estado=='activa' de un Contact — a lo sumo una
    (DR-4: nunca simultáneas). Si por alguna razón hubiera más de una fila
    marcada activa (no debería ocurrir con el flujo normal), toma la más
    reciente — no falla el request por un estado inconsistente que además no
    puede repararse desde una lectura."""
    query = (
        select(Conversation)
        .where(Conversation.contact_id == contact_id, Conversation.estado == "activa")
        .order_by(Conversation.creado.desc())
        .limit(1)
    )
    return (await session.execute(query)).scalar_one_or_none()


async def _obtener_conversation_activa_por_telefono(session, telefono: str) -> "Conversation | None":
    """Puente telefono → Conversation activa, para las funciones de interfaz
    pública que todavía reciben `telefono` (registrar_evento_lead,
    listar_eventos_lead, guardar_venta, asignar_asesor_a_lead,
    liberar_asignacion) — mismo patrón que `guardar_mensaje` ya usa para
    resolver `negocio_id` desde el Lead (Gate 5.2, H1): nunca se le pide al
    llamador que resuelva el contexto, y `negocio_id` nunca llega como
    parámetro externo. Retorna None si el Lead o el Contact todavía no
    existen (nunca inventa ninguno)."""
    lead = await session.get(Lead, telefono)
    if lead is None or lead.negocio_id is None:
        return None
    contact = await _obtener_contact(session, lead.negocio_id, telefono)
    if contact is None:
        return None
    return await _obtener_conversation_activa(session, contact.id)


async def obtener_conversation_realtime(conversation_id: str, negocio_id: str | None = None) -> dict | None:
    """Datos mínimos de una Conversation para Realtime (Gate 5.5), más
    `telefono` (vía Contact) para que el panel legacy, que sigue filtrando
    eventos por teléfono, siga recibiéndolos sin cambios. NO usa el bridge
    legacy `Lead.telefono` — va directo por la PK de `Conversation`, que ya
    trae su propio `negocio_id` scoped desde su creación, así que no hay
    ambigüedad posible entre Negocios al resolver por este id (a diferencia
    de resolver por `telefono`, que si puede colisionar entre Negocios).

    `negocio_id` — mismo criterio dual que `obtener_lead()`/`obtener_usuario()`:
    si se pasa, es el candado real de ownership (404, no 403, si la
    Conversation es de otro Negocio). Si se omite, es descubrimiento de
    identidad puro (uso interno de `GestorConexiones.emitir_mensaje_nuevo`,
    que no verifica el acceso de un tercero — cada conexión aplica su propio
    filtro de `negocio_id` después). Nunca usar `negocio_id=None` desde un
    endpoint autenticado."""
    async with async_session() as session:
        conversation = await session.get(Conversation, conversation_id)
        if conversation is None:
            return None
        if negocio_id is not None and conversation.negocio_id != negocio_id:
            return None
        contact = await session.get(Contact, conversation.contact_id)
        return {
            "id": conversation.id,
            "negocio_id": conversation.negocio_id,
            "telefono": contact.telefono if contact else None,
            "estado": conversation.estado,
            "asesor_asignado_id": conversation.asesor_asignado_id,
        }


async def obtener_conversation_activa_de_telefono(telefono: str, negocio_id: str) -> dict | None:
    """Puente telefono → Conversation activa, con `negocio_id` explícito —
    reemplaza a `_obtener_conversation_activa_por_telefono` para los
    llamadores que SÍ conocen su Negocio de antemano (Gate 5.5, Realtime).

    A diferencia del bridge legacy (que resuelve `negocio_id` desde
    `Lead.telefono`, PK global — el hallazgo central del checkpoint de
    investigación de Gate 5.5: con el mismo teléfono en dos Negocios, el
    bridge solo puede resolver al que "ganó" la fila `Lead`), esta función
    va DIRECTO por `Contact.negocio_id` (columna propia, ya scoped desde su
    creación en Gate 5.3) — nunca pasa por `Lead`. Retorna `None` si el
    Contact o su Conversation activa no existen PARA ESE Negocio (nunca
    revela si existen para otro — mismo criterio 404-no-403 que el resto
    del Gate 5.4/5.5)."""
    async with async_session() as session:
        contact = await _obtener_contact(session, negocio_id, telefono)
        if contact is None:
            return None
        conversation = await _obtener_conversation_activa(session, contact.id)
        if conversation is None:
            return None
        return {
            "id": conversation.id,
            "negocio_id": conversation.negocio_id,
            "contact_id": conversation.contact_id,
            "estado": conversation.estado,
            "asesor_asignado_id": conversation.asesor_asignado_id,
        }


async def _obtener_opportunity_vigente(session, conversation_id: str) -> "Opportunity | None":
    """La Opportunity más reciente de una Conversation — DR-3: 1 Conversation
    : 0..N Opportunity secuenciales, la vigente es siempre la última creada."""
    query = (
        select(Opportunity)
        .where(Opportunity.conversation_id == conversation_id)
        .order_by(Opportunity.creado.desc())
        .limit(1)
    )
    return (await session.execute(query)).scalar_one_or_none()


def _debe_abrir_conversation_nueva(conversation: "Conversation | None") -> bool:
    """DR-4 (Resolución Arquitectónica Gate 5.3) — revisado en Gate 2026-09-23
    para usar la MISMA señal que reactiva a Gabi (`_gabi_debe_pausarse` en
    main.py): se abre una Conversation nueva únicamente cuando el caso quedó
    CERRADO DEFINITIVAMENTE (`cerrado_definitivamente_en`, manual desde la
    Ficha del Lead o automático tras 7 días de silencio del cliente sobre un
    resultado ya cerrado).

    ANTES el gatillo era "cualquier `resultado` en RESULTADOS_CERRADOS, !=
    vendido" — eso disparaba una Conversation nueva (vacía, sin asesor) con
    CUALQUIER cierre, por trivial que fuera, mientras el gate de main.py ya
    exigía el cierre EXPLÍCITO para reactivar a Gabi. Con las dos señales
    desalineadas, un mensaje del cliente podía caer en una Conversation
    huérfana (recién creada, sin asesor) sin que Gabi respondiera tampoco —
    el mensaje quedaba sin nadie atendiéndolo. `cerrado_definitivamente_en`
    ya implica "resultado cerrado y no vendido" (única forma de setearlo,
    ver `cerrar_lead_definitivamente`), así que alcanza con este solo
    chequeo — nunca se setea sin que haya habido asesor/pausa de por medio."""
    if conversation is None:
        return True
    return conversation.cerrado_definitivamente_en is not None


# ── Reapertura por el cliente tras un cierre definitivo (P4, 2026-10-06) ──
# Duplicado a propósito de dashboard.py::ETIQUETAS_RESULTADO (dashboard.py
# importa memory.py, no al revés): solo para redactar la `descripcion` del
# evento; el frontend arma su propia frase desde el payload.
_ETIQUETAS_RESULTADO_REAPERTURA = {
    "agendado": "Agendado", "vendido": "Vendido", "no_interesado": "No interesado",
    "no_califica": "No califica", "no_es_cliente_calidda": "No es cliente Calidda",
    "producto_sin_stock": "Producto sin stock", "otro": "Otro", "consulta_atc": "Consulta ATC",
    "sin_saldo": "Sin saldo", "servicio_postventa": "Servicio adicional Gas",
    "cartera_fnb": "Cartera FNB", "sin_respuesta": "Sin respuesta", "postventa": "Postventa",
}


def descripcion_reapertura(resultado_anterior: str | None, asesor_anterior: str | None) -> str:
    """Texto del evento `reabierto_por_cliente` (lo comparten el webhook y
    scripts/backfill_reaperturas.py para que digan exactamente lo mismo)."""
    etiqueta = (
        _ETIQUETAS_RESULTADO_REAPERTURA.get(resultado_anterior, resultado_anterior)
        if resultado_anterior else "Sin resultado"
    )
    descripcion = f"Reabierto por el cliente — antes: {etiqueta}"
    if asesor_anterior:
        descripcion += f" (gestionado por {asesor_anterior})"
    return descripcion[:300]


async def _registrar_reapertura_por_cliente(
    session, telefono: str, negocio_id: str,
    conversation_anterior: "Conversation | None", opportunity_anterior: "Opportunity | None",
    conversation_nueva: "Conversation", opportunity_nueva: "Opportunity",
) -> bool:
    """Se llama SOLO desde `resolver_conversation_activa`, en la misma
    transacción en que DR-4 cierra la Conversation vieja y abre la nueva (el
    cliente volvió a escribir tras un CIERRE DEFINITIVO). Hace dos cosas:

    1. Deja el evento `reabierto_por_cliente` en el Timeline de la
       Conversation NUEVA (payload: resultado_anterior, asesor_anterior,
       conversation_anterior_id, cerrado_en). Antes la conversación nueva
       arrancaba sin ninguna huella de lo anterior: el resultado y quién lo
       gestionó solo existían en la Conversation cerrada.
    2. R4: `Lead.resultado` vuelve a NULL (junto con la Opportunity nueva,
       que nace sin resultado). Antes el Lead conservaba el resultado viejo:
       el Pipeline (que lee Lead) lo mostraba y la Bandeja (que lee
       Opportunity) no — dos fuentes que divergían — y un resultado viejo
       sacaba al lead del ciclo de espera/rotación del asesor
       (`ejecutar_ciclo_de_espera` solo mira leads sin resultado). Se limpia
       también lo que dependía de ese resultado: `fecha_agendada` (la cita
       del ciclo anterior; la Opportunity nueva ya nace sin ella) y los
       contadores de espera/rotación del ciclo anterior.

    NO aplica a "vendido": un cliente con una venta cerrada que vuelve a
    escribir va por `enrutar_posventa_si_corresponde` (mismo asesor,
    resultado="postventa", Gabi nunca responde) — reiniciarlo acá le
    borraría el resultado a un flujo que además deja su propio evento.
    Tampoco si no había Conversation anterior (primer contacto).

    Retorna True si registró la reapertura."""
    if conversation_anterior is None:
        return False
    lead = await session.get(Lead, telefono)
    if lead is not None and lead.negocio_id not in (None, negocio_id):
        lead = None  # mismo teléfono en otro Negocio: nunca se toca el Lead ajeno
    resultado_anterior = opportunity_anterior.resultado if opportunity_anterior is not None else None
    if resultado_anterior is None and lead is not None:
        resultado_anterior = lead.resultado
    if resultado_anterior == "vendido" or (lead is not None and lead.resultado == "vendido"):
        return False

    asesor_anterior = conversation_anterior.asesor_asignado_id or (lead.asesor_asignado if lead else None)
    cerrado_en = conversation_anterior.cerrado_definitivamente_en
    payload = {
        "resultado_anterior": resultado_anterior,
        "asesor_anterior": asesor_anterior,
        "conversation_anterior_id": conversation_anterior.id,
        "cerrado_en": cerrado_en.isoformat() if cerrado_en else None,
    }

    if lead is not None:
        if lead.fecha_agendada is not None:
            payload["fecha_agendada_anterior"] = lead.fecha_agendada.isoformat()
        lead.resultado = None
        lead.fecha_agendada = None
        lead.derivado_en = None
        lead.minutos_espera_asesor = 0
        lead.veces_rotado_espera = 0
        # 2026-10-08 (triaje ATC): el cierre definitivo del Lead también se consume. Hasta hoy solo lo
        # limpiaba `liberar_asignacion`, que el webhook llama únicamente cuando el Lead conserva asesor o
        # pausa (`_cierre_definitivo_pendiente_de_liberar`). Un caso cerrado SIN asesor (el que deja el
        # triaje automático) conservaba un cierre viejo en el Lead: `respaldo_sin_ia._lead_fuera_de_alcance`
        # lo seguía tratando como cerrado y el modo sin IA ignoraba al cliente reabierto. Con asesor o
        # pausa NO se toca: el webhook necesita ese cierre para decidir que debe liberar al asesor anterior.
        if not (lead.asesor_asignado or lead.pausado_manual):
            lead.cerrado_definitivamente_en = None
        _avanzar_version(lead)
        lead.actualizado = datetime.utcnow()

    session.add(EventoLead(
        conversation_id=conversation_nueva.id, negocio_id=conversation_nueva.negocio_id,
        opportunity_id=opportunity_nueva.id,
        tipo="reabierto_por_cliente",
        descripcion=descripcion_reapertura(resultado_anterior, asesor_anterior), autor=None, payload=payload,
    ))
    return True


async def resolver_conversation_activa(
    telefono: str, negocio_id: str, canal_id: int, unidad_id: str | None = None,
    campana_origen_id: int | None = None, origen_contacto: str | None = None, nombre: str | None = None,
) -> tuple["Conversation", "Opportunity"]:
    """Punto de entrada único para el webhook (main.py): resuelve (o crea)
    Contact + Conversation activa + Opportunity vigente para un mensaje
    entrante, aplicando DR-4. `negocio_id`/`canal_id` deben venir YA
    resueltos por `resolver_canal()` — nunca se re-resuelven acá ni se
    aceptan de una fuente distinta al Canal de entrada.

    Gate 5.5 — candado de concurrencia real (hallazgo del checkpoint de
    investigación): la lectura-luego-escritura de acá abajo, por sí sola, no
    impedía que dos webhooks concurrentes para el mismo Contact ambos vieran
    "sin Conversation activa" y ambos intentaran crear una — violando DR-4
    bajo Postgres real (SQLite lo enmascara). `ix_conversation_una_activa_
    por_contact` (índice único parcial) es el candado real; acá solo se
    atrapa el `IntegrityError` cuando se pierde la carrera y se relee la fila
    que sí ganó — mismo patrón que `marcar_mensaje_procesado` (insert +
    catch, no check-then-insert)."""
    async with async_session() as session:
        contact = await obtener_o_crear_contact(session, negocio_id, telefono, nombre)
        conversation = await _obtener_conversation_activa(session, contact.id)
        opportunity = await _obtener_opportunity_vigente(session, conversation.id) if conversation else None

        if _debe_abrir_conversation_nueva(conversation):
            if conversation is not None:
                # Efecto automático — se cierra, no se borra ni se reescribe.
                # Sin chequeo de version (mismo criterio que _avanzar_version).
                conversation.estado = "cerrada"
                conversation.version = Conversation.version + 1
            conversation_nueva = Conversation(
                negocio_id=negocio_id, unidad_id=unidad_id, contact_id=contact.id,
                canal_id=canal_id, campana_origen_id=campana_origen_id,
                origen_contacto=origen_contacto, estado="activa",
            )
            session.add(conversation_nueva)
            try:
                await session.flush()
            except IntegrityError:
                # Otro proceso/corrutina ganó la carrera y ya insertó la
                # Conversation activa de este Contact — se descarta el
                # intento propio (incluido el cierre de la vieja, que
                # tampoco debe persistir: la ganadora ya resolvió esa
                # transición) y se relee la que quedó activa de verdad.
                await session.rollback()
                async with async_session() as session_relectura:
                    conversation = await _obtener_conversation_activa(session_relectura, contact.id)
                    opportunity = await _obtener_opportunity_vigente(session_relectura, conversation.id) if conversation else None
                    if conversation is None:
                        # No debería poder pasar (el IntegrityError implica que
                        # SÍ hay una fila activa) — pero no se inventa nada.
                        raise
                    return conversation, opportunity
            conversation_anterior, opportunity_anterior = conversation, opportunity
            conversation = conversation_nueva
            opportunity = Opportunity(
                negocio_id=negocio_id, unidad_id=unidad_id,
                conversation_id=conversation.id, contact_id=contact.id,
            )
            session.add(opportunity)
            await session.flush()
            # 2026-10-06 (P4) — el ciclo nuevo deja rastro de lo anterior y
            # el Lead (legacy) vuelve a "sin resultado" junto con la
            # Opportunity nueva. Misma transacción: o entra todo o nada, y
            # por eso un reintento del webhook no puede duplicar el evento
            # (la Conversation vieja ya quedó cerrada, DR-4 no vuelve a
            # dispararse).
            await _registrar_reapertura_por_cliente(
                session, telefono, negocio_id, conversation_anterior, opportunity_anterior,
                conversation, opportunity,
            )

        await session.commit()
        await session.refresh(conversation)
        await session.refresh(opportunity)
        return conversation, opportunity


async def intentar_avanzar_version_conversation(conversation_id: str, version_esperada: int) -> bool:
    """Concurrencia optimista de Conversation — mismo mecanismo atómico que
    `intentar_avanzar_version` (Lead), ver esa función para el detalle de por
    qué el chequeo viaja DENTRO del UPDATE."""
    async with async_session() as session:
        resultado = await session.execute(
            update(Conversation)
            .where(Conversation.id == conversation_id, Conversation.version == version_esperada)
            .values(version=version_esperada + 1)
        )
        if resultado.rowcount == 0:
            await session.rollback()
            return False
        await session.commit()
        return True


async def intentar_avanzar_version_opportunity(opportunity_id: str, version_esperada: int) -> bool:
    """Concurrencia optimista de Opportunity — separada de Conversation.version
    (DR-1: partir el contador único de Lead.version en las dos entidades que
    hoy lo comparten)."""
    async with async_session() as session:
        resultado = await session.execute(
            update(Opportunity)
            .where(Opportunity.id == opportunity_id, Opportunity.version == version_esperada)
            .values(version=version_esperada + 1)
        )
        if resultado.rowcount == 0:
            await session.rollback()
            return False
        await session.commit()
        return True


async def _lead_del_contact(session, conversation: "Conversation | None") -> "Lead | None":
    """Resuelve el Lead legacy de esta Conversation — SOLO si su negocio_id
    coincide (Gate 5.3 cutover real §1/§2): el mismo teléfono puede existir
    como Lead de OTRO Negocio, y sincronizar ahí sería exactamente el mismo
    hallazgo de LineaVenta/EventoLead pero en dirección inversa (Opportunity
    → Lead en vez de Lead → Opportunity). None si no hay Conversation, no hay
    Lead, o el Lead pertenece a otro Negocio — nunca se crea uno acá."""
    if conversation is None:
        return None
    contact = await session.get(Contact, conversation.contact_id)
    if contact is None:
        return None
    lead = await session.get(Lead, contact.telefono)
    if lead is None or lead.negocio_id != conversation.negocio_id:
        return None
    return lead


def _registrar_evento_en_sesion(session, conversation: "Conversation", opportunity_id: str | None, evento: dict | None):
    """Inserta un EventoLead DENTRO de la transacción que llama — Gate 5.3
    cutover real §12: si el cierre de una Opportunity falla, el evento que lo
    describe no puede quedar escrito sin la escritura que describe (o al
    revés). `evento` es `{"tipo", "descripcion", "autor", "payload"}`; None
    = no registrar nada (compatibilidad con llamadores que ya registran su
    propio evento por fuera, como los tests existentes)."""
    if evento is None:
        return
    session.add(EventoLead(
        conversation_id=conversation.id, negocio_id=conversation.negocio_id, opportunity_id=opportunity_id,
        tipo=evento["tipo"], descripcion=evento["descripcion"], autor=evento.get("autor"), payload=evento.get("payload"),
    ))


async def intentar_cambiar_resultado_opportunity(
    opportunity_id: str, version_esperada: int, campos: dict, evento: dict | None = None,
) -> bool:
    """Escritura humana de RESULTADO — Gate 5.3 cutover real §1/§4/§6:
    Opportunity es la fuente de verdad, no un espejo de Lead. Atómica: el
    chequeo de `version` y la escritura son el mismo commit (mismo criterio
    que `cerrar_opportunity_con_venta`).

    Sincroniza `Lead.version` INCONDICIONALMENTE al final (get-only, nunca
    crea nada) — no es "Lead como fuente de verdad", es mantener su version
    como gate de concurrencia válido para el endpoint legacy que todavía no
    conoce `opportunity_version` (cutover real §2): si esta escritura no
    avanzara Lead.version, un cliente legacy con una version vieja pero
    todavía "vigente" podría sobrescribir en silencio un cambio hecho acá.

    Punto 2 (2026-09-30) — desarma `Lead.derivado_en` cuando `campos` trae
    "resultado": el usuario fue explícito sobre esto tras el incidente —
    "la regla de los 30 minutos... es cuando el asesor no responde O no le
    da algún resultado (cualquiera que sea)" — así que dar CUALQUIER
    resultado (incluido volver a limpiarlo) cuenta como que el asesor ya
    actuó sobre el lead, igual que responder un mensaje. Cubre también,
    como efecto colateral necesario, el hueco más serio que esta misma
    pregunta destapó: hasta acá una venta cerrada (`resultado="vendido"`)
    no desarmaba nada por su cuenta — solo lo hacía si el asesor además
    mandaba un mensaje de chat — así que un "vendido" sin mensaje posterior
    quedaba con el reloj corriendo, en contra de "Close-Won es indefinido"
    (Human Decision Gate). Como TODO cambio de resultado pasa por acá o
    por `actualizar_lead` (ver ahí), no hace falta un chequeo aparte en
    `listar_leads_para_rotar_o_liberar`."""
    async with async_session() as session:
        async with session.begin():
            resultado_version = await session.execute(
                update(Opportunity)
                .where(Opportunity.id == opportunity_id, Opportunity.version == version_esperada)
                .values(version=version_esperada + 1)
            )
            if resultado_version.rowcount == 0:
                await session.rollback()
                return False

            opportunity = await session.get(Opportunity, opportunity_id)
            transicion_a_vendido = _es_transicion_a_vendido_opportunity(opportunity, campos)
            for campo, valor in campos.items():
                setattr(opportunity, campo, valor)
            opportunity.actualizado = datetime.utcnow()

            conversation = await session.get(Conversation, opportunity.conversation_id)
            if transicion_a_vendido and conversation is not None:
                opportunity.fecha_cierre = datetime.utcnow()
                conversation.pausado_manual = True
                conversation.version = Conversation.version + 1

            lead = await _lead_del_contact(session, conversation)
            if lead is not None:
                for campo, valor in campos.items():
                    if hasattr(Lead, campo):
                        setattr(lead, campo, valor)
                if transicion_a_vendido:
                    _marcar_cierre_vendido(lead)
                if "resultado" in campos:
                    lead.derivado_en = None
                _avanzar_version(lead)
                lead.actualizado = datetime.utcnow()

            if conversation is not None:
                _registrar_evento_en_sesion(session, conversation, opportunity_id, evento)
        return True


async def intentar_asignar_conversation(
    conversation_id: str, version_esperada: int, asesor_asignado: str | None, evento: dict | None = None,
) -> bool:
    """Escritura humana de ASIGNACIÓN — Gate 5.3 cutover real §1/§4/§6:
    `asesor_asignado_id` es un campo de Conversation, no de Opportunity (la
    identidad de "quién atiende" pertenece al hilo, no al ciclo comercial) —
    mismo criterio que ya fijaba el modelo. Atómica, mismo patrón que
    `intentar_cambiar_resultado_opportunity`: chequeo + escritura + sync de
    Lead.version en un solo commit.

    Punto 2 (2026-09-30) — ESTE es el camino REAL de reasignación manual en
    producción (`/conversation/{id}/asignar` y el legacy `/lead/{telefono}/
    asignar` una vez que ya existe Contact/Conversation/Opportunity, que es
    el caso normal): a diferencia de `asignar_asesor_a_lead(automatico=
    False)`, que solo cubre el fallback sin Conversation todavía, esta
    función escribía directo sobre `Lead.asesor_asignado` SIN pasar por ahí
    — así que nunca desarmaba `derivado_en`. Mismo hueco exacto que el
    incidente de Pedro Padilla Medrano (una reasignación manual que el cron
    deshacía), reubicado acá. Se desarma siempre, asigne o desasigne: las
    dos son una decisión humana explícita, igual que `automatico=False`."""
    async with async_session() as session:
        async with session.begin():
            resultado_version = await session.execute(
                update(Conversation)
                .where(Conversation.id == conversation_id, Conversation.version == version_esperada)
                .values(version=version_esperada + 1)
            )
            if resultado_version.rowcount == 0:
                await session.rollback()
                return False

            conversation = await session.get(Conversation, conversation_id)
            conversation.asesor_asignado_id = asesor_asignado
            conversation.visto_asesor = asesor_asignado is None
            conversation.actualizado = datetime.utcnow()

            lead = await _lead_del_contact(session, conversation)
            if lead is not None:
                lead.asesor_asignado = asesor_asignado
                lead.visto_asesor = asesor_asignado is None
                lead.derivado_en = None
                lead.escalado_supervision_en = None  # una persona decidió: ya no está en la cola de supervisión
                _avanzar_version(lead)
                lead.actualizado = datetime.utcnow()

            opportunity = await _obtener_opportunity_vigente(session, conversation.id)
            _registrar_evento_en_sesion(session, conversation, opportunity.id if opportunity else None, evento)
        return True


async def cerrar_opportunity_con_venta(
    opportunity_id: str, version_esperada: int, lineas: list[dict], campos: dict,
    revertir_resultado_al_vaciar: bool = False, evento: dict | None = None,
) -> bool:
    """Cierre de venta ATÓMICO — Opportunity + LineaVenta + (si corresponde)
    Conversation.pausado_manual + sincronización de Lead + evento del
    Timeline, en UN SOLO commit (Gate 5.3 cutover real §1/§6/§12: Opportunity
    es la fuente de verdad, Lead recibe sincronización mínima, no al revés).

    Corrección de un defecto preexistente en producción (encontrado en el
    bloque de Diseño Técnico Gate 5.3, no introducido por esta migración):
    `intentar_avanzar_version` y `guardar_venta` corrían en DOS transacciones
    separadas con DOS commits distintos — ventana real de inconsistencia
    entre el chequeo de versión y la escritura de la venta. Acá el chequeo de
    versión y la escritura son la MISMA transacción: si el chequeo falla
    (`rowcount == 0`), se hace rollback de todo y se retorna False (409) sin
    tocar LineaVenta, Conversation ni Lead.

    `revertir_resultado_al_vaciar`: mismo criterio que `guardar_venta` — si
    el carrito queda vacío y la Opportunity estaba "vendido" TENIENDO líneas,
    se le quita el resultado en vez de dejarla huérfana.

    Retorna False si la version de Opportunity no coincide (conflicto 409) —
    en ese caso NO se toca nada, ni Opportunity, ni LineaVenta, ni
    Conversation, ni Lead."""
    async with async_session() as session:
        async with session.begin():
            resultado_version = await session.execute(
                update(Opportunity)
                .where(Opportunity.id == opportunity_id, Opportunity.version == version_esperada)
                .values(version=version_esperada + 1)
            )
            if resultado_version.rowcount == 0:
                await session.rollback()
                return False

            opportunity = await session.get(Opportunity, opportunity_id)

            if not lineas and revertir_resultado_al_vaciar and opportunity.resultado == "vendido":
                habia_lineas = await session.scalar(
                    select(func.count()).select_from(LineaVenta).where(
                        LineaVenta.opportunity_id == opportunity_id, LineaVenta.negocio_id == opportunity.negocio_id,
                    )
                )
                if habia_lineas:
                    campos = {
                        **campos,
                        "resultado": None, "fecha_cierre": None,
                        "modalidad_pago": None, "medio_pago": None,
                    }

            transicion_a_vendido = _es_transicion_a_vendido_opportunity(opportunity, campos)
            for campo, valor in campos.items():
                setattr(opportunity, campo, valor)
            if transicion_a_vendido:
                opportunity.fecha_cierre = datetime.utcnow()
            opportunity.actualizado = datetime.utcnow()

            # Doble candado — nunca DELETE/SELECT solo por telefono (regla
            # crítica de LineaVenta, ver la clase).
            await session.execute(
                delete(LineaVenta).where(
                    LineaVenta.opportunity_id == opportunity_id,
                    LineaVenta.negocio_id == opportunity.negocio_id,
                )
            )
            for l in lineas:
                session.add(LineaVenta(
                    opportunity_id=opportunity_id, negocio_id=opportunity.negocio_id,
                    producto_id=l.get("producto_id"), producto=l["producto"],
                    precio=l.get("precio") or None, marca=l.get("marca") or None,
                    proveedor=l.get("proveedor") or None,
                ))

            conversation = await session.get(Conversation, opportunity.conversation_id)
            if transicion_a_vendido and conversation is not None:
                # Efecto automático — sin exigir la version vigente de
                # Conversation al formulario de venta (que solo conoce la
                # version de Opportunity). Mismo criterio que
                # _avanzar_version: nunca bloquear un efecto de sistema
                # por lo que esté haciendo un humano con otro formulario.
                conversation.pausado_manual = True
                conversation.version = Conversation.version + 1

            lead = await _lead_del_contact(session, conversation)
            if lead is not None:
                for campo, valor in campos.items():
                    if hasattr(Lead, campo):
                        setattr(lead, campo, valor)
                if transicion_a_vendido:
                    _marcar_cierre_vendido(lead)
                # Punto 2 (2026-09-30) — mismo desarme que `intentar_cambiar_
                # resultado_opportunity`: ESTE es el camino real de "vendido"
                # (Registrar venta), el más grave de los dos huecos que
                # destapó la pregunta del usuario — sin esto, una venta
                # cerrada sin mensaje de chat posterior podía quedar con el
                # reloj de rotación corriendo, violando "Close-Won es
                # indefinido".
                if "resultado" in campos:
                    lead.derivado_en = None
                _avanzar_version(lead)
                lead.actualizado = datetime.utcnow()

            if conversation is not None:
                _registrar_evento_en_sesion(session, conversation, opportunity_id, evento)
        # session.begin() ya hizo commit atómico al salir sin excepción.
        return True


def _es_transicion_a_vendido_opportunity(opportunity: "Opportunity", campos: dict) -> bool:
    """Mismo criterio que `_es_transicion_a_vendido` (Lead): True solo si
    ESTA escritura hace pasar la Opportunity a "vendido" viniendo de otro
    estado — no si ya estaba vendida y solo se reedita la venta."""
    return campos.get("resultado") == "vendido" and opportunity.resultado != "vendido"


async def listar_conversaciones_activas(
    negocio_id: str, asesor_asignado: str | None = None, busqueda: str = "",
    resultado: str = "", orden: str = "actividad", direccion: str = "desc",
    pagina: int = 1, por_pagina: int = 20, ids_ordenados: list[str] | None = None,
) -> tuple[list[dict], int]:
    """Bandeja de Conversaciones (Diseño Técnico Gate 5.3 §13/§18) — a
    diferencia de Pipeline (que lista Opportunity), esto lista `Conversation`
    con `estado == "activa"`: un Contact con Opportunities secuenciales (DR-3)
    aparece como UNA sola fila mientras su Conversation siga activa, nunca
    duplicado. Devuelve filas con el MISMO nombre de campo que
    `_dto_lead_pipeline` (id, telefono, version, resultado, ...) para que los
    componentes del frontend que ya consumen esa forma no necesiten tocarse
    — solo cambia la fuente (Conversation, no Opportunity)."""
    columnas_orden = {
        "nombre": Contact.nombre, "resultado": Opportunity.resultado,
        "asesor": Conversation.asesor_asignado_id, "actualizado": Conversation.actualizado,
        "creado": Conversation.creado,
        # 2026-10-03 — "actividad" = hora del último mensaje real; asignar,
        # rotar, liberar o un cierre automático NO la mueven (sí mueven
        # `actualizado`). El respaldo a `creado` cubre filas anteriores a la
        # columna que la migración no alcanzara a rellenar.
        "actividad": func.coalesce(Conversation.ultimo_mensaje_en, Conversation.creado),
    }
    columna = columnas_orden.get(orden, columnas_orden["actividad"])

    async with async_session() as session:
        # Opportunity vigente por Conversation — row_number() por
        # conversation_id, mismo patrón ya usado en obtener_ultimos_mensajes.
        fila = (
            func.row_number()
            .over(partition_by=Opportunity.conversation_id, order_by=Opportunity.creado.desc())
            .label("fila")
        )
        subconsulta_opp = (
            select(Opportunity).add_columns(fila).subquery()
        )
        opportunity_vigente = aliased(Opportunity, subconsulta_opp)

        query = (
            select(Conversation, Contact, opportunity_vigente)
            .join(Contact, Contact.id == Conversation.contact_id)
            .outerjoin(
                subconsulta_opp,
                sa_and(subconsulta_opp.c.conversation_id == Conversation.id, subconsulta_opp.c.fila == 1),
            )
            .where(Conversation.negocio_id == negocio_id, Conversation.estado == "activa")
        )
        if asesor_asignado and ids_ordenados is None:
            # Con `ids_ordenados` (vista de Inicio) el alcance por asesor ya lo
            # aplicaron las funciones que arman los ids (con el Lead, igual que
            # Inicio); repetirlo contra `Conversation.asesor_asignado_id` haria
            # que la lista pudiera perder un caso que Inicio si cuenta si ambas
            # columnas llegaran a diferir.
            query = query.where(Conversation.asesor_asignado_id == asesor_asignado)
        if resultado == "sin_resultado":
            # 2026-10-06 — filtro "Sin resultado" de la Bandeja: Conversations
            # ACTIVAS cuya Opportunity vigente no tiene resultado (NULL o
            # vacío), más las que todavía no tienen ninguna Opportunity (el
            # outerjoin deja `resultado` en NULL — la fila se pinta con el
            # mismo badge "Sin resultado"). NO es un resultado cerrado como
            # `sin_respuesta` (ese sí es un valor guardado, puesto por un
            # asesor o por un Cron). Es la ausencia de resultado: justo lo
            # que `ejecutar_ciclo_de_espera` considera "sin resolver", y lo
            # que el equipo necesita encontrar para asignarle uno. No se
            # restringe a "con gestión": toda fila de la Bandeja con este
            # badge debe aparecer al filtrar por él (ver el reporte del cambio).
            query = query.where(
                sa_or(opportunity_vigente.resultado.is_(None), opportunity_vigente.resultado == "")
            )
        elif resultado:
            query = query.where(opportunity_vigente.resultado == resultado)
        if busqueda:
            # Punto 4 (pedido explícito del usuario, 2026-09-28: "que el
            # buscador de chat busque por palabra asi como el de whatsapp"):
            # antes solo miraba nombre/teléfono del Contact — ahora también
            # el interés (ya visible en la fila) y el CONTENIDO de los
            # mensajes de esa Conversation, vía EXISTS (no trae los mensajes,
            # solo confirma que hay al menos uno que matchea — un JOIN normal
            # duplicaría filas de Conversation por cada mensaje que calce).
            patron = f"%{busqueda}%"
            existe_mensaje_con_texto = sa_exists(
                select(Mensaje.id).where(
                    Mensaje.conversation_id == Conversation.id,
                    Mensaje.content.ilike(patron),
                )
            )
            query = query.where(
                Contact.nombre.ilike(patron)
                | Contact.telefono.ilike(patron)
                | opportunity_vigente.interes.ilike(patron)
                | existe_mensaje_con_texto
            )

        if ids_ordenados is None:
            total = (await session.execute(select(func.count()).select_from(query.subquery()))).scalar_one()

            orden_columna = columna.asc() if direccion == "asc" else columna.desc()
            query = query.order_by(orden_columna).offset((pagina - 1) * por_pagina).limit(por_pagina)
            result = await session.execute(query)
            filas_crudas = result.all()
        else:
            # Vista de Inicio (2026-10-06): el conjunto y su ORDEN vienen de
            # `ids_ordenados` (ya priorizado por quien llama), no de una
            # columna. Sin q/resultado se pagina sobre los ids y se traen solo
            # las filas de esa página (una consulta); con q/resultado hay que
            # filtrar primero, así que se traen las coincidencias (acotadas por
            # el tamaño de la vista) y se pagina después. Siempre en lote.
            desde = (pagina - 1) * por_pagina
            posicion = {cid: i for i, cid in enumerate(ids_ordenados)}
            if not busqueda and not resultado:
                total = len(ids_ordenados)
                ids_pagina = ids_ordenados[desde:desde + por_pagina]
                crudas = (
                    (await session.execute(query.where(Conversation.id.in_(ids_pagina)))).all()
                    if ids_pagina else []
                )
                crudas.sort(key=lambda fila_: posicion[fila_[0].id])
                filas_crudas = crudas
            else:
                crudas = (
                    (await session.execute(query.where(Conversation.id.in_(ids_ordenados)))).all()
                    if ids_ordenados else []
                )
                crudas.sort(key=lambda fila_: posicion[fila_[0].id])
                total = len(crudas)
                filas_crudas = crudas[desde:desde + por_pagina]

        # Bandeja — "bolita" con pendientes + último mensaje (QA, 2026-09-15):
        # dos consultas EN LOTE (no una por fila — la página trae como mucho
        # `por_pagina` conversaciones, así que se resuelven las dos de una
        # sola vez para todo el lote, nunca N+1).
        ids_conversacion = [c.id for c, _, _ in filas_crudas]
        pendientes_por_conv: dict[str, int] = {}
        ultimo_mensaje_por_conv: dict[str, str] = {}
        if ids_conversacion:
            # "Pendiente" = mensaje del CLIENTE posterior al último mensaje
            # que NO es del cliente (Gabi o asesor) en esa Conversation — el
            # mismo criterio que usaría un humano leyendo el hilo: cuántos
            # mensajes seguidos mandó el cliente sin que nadie/nada le
            # respondiera todavía. Sin esto (agregado por Conversation, no
            # por Contact) no hay forma de distinguir "sin responder" de
            # "ya respondido hace rato" solo con `Mensaje.role`.
            ultimo_no_cliente = (
                select(
                    Mensaje.conversation_id.label("conversation_id"),
                    func.max(Mensaje.timestamp).label("ts"),
                )
                .where(Mensaje.conversation_id.in_(ids_conversacion), Mensaje.role != "user")
                .group_by(Mensaje.conversation_id)
                .subquery()
            )
            pendientes_query = (
                select(Mensaje.conversation_id, func.count().label("pendientes"))
                .outerjoin(ultimo_no_cliente, ultimo_no_cliente.c.conversation_id == Mensaje.conversation_id)
                .where(
                    Mensaje.conversation_id.in_(ids_conversacion),
                    Mensaje.role == "user",
                    sa_or(ultimo_no_cliente.c.ts.is_(None), Mensaje.timestamp > ultimo_no_cliente.c.ts),
                )
                .group_by(Mensaje.conversation_id)
            )
            for conv_id, pendientes in (await session.execute(pendientes_query)).all():
                pendientes_por_conv[conv_id] = pendientes

            # Último mensaje de cada Conversation (cualquier rol) — mismo
            # patrón row_number() ya usado arriba para Opportunity vigente.
            fila_msg = (
                func.row_number()
                .over(partition_by=Mensaje.conversation_id, order_by=Mensaje.timestamp.desc())
                .label("fila")
            )
            subconsulta_msg = (
                select(Mensaje.conversation_id, Mensaje.content, Mensaje.role)
                .where(Mensaje.conversation_id.in_(ids_conversacion))
                .add_columns(fila_msg)
                .subquery()
            )
            ultimos_result = await session.execute(
                select(subconsulta_msg.c.conversation_id, subconsulta_msg.c.content, subconsulta_msg.c.role)
                .where(subconsulta_msg.c.fila == 1)
            )
            for conv_id, content, role in ultimos_result.all():
                texto = (content or "").strip() or "Adjunto"
                prefijo = "Tú: " if role != "user" else ""
                ultimo_mensaje_por_conv[conv_id] = f"{prefijo}{texto}"[:140]

        # Q3 (2026-10-07) — lo que el cliente escribió DESPUÉS de un cierre
        # definitivo ("ok", "gracias", una reacción): se queda en la conversación
        # cerrada, NO cuenta como pendiente (no hay nada que contestar) y la fila
        # lo expone aparte (`respondio_tras_cierre_en`, `mensajes_tras_cierre`)
        # para el chip pasivo del frontend. Una consulta en lote, sin N+1.
        tras_cierre_por_conv = await _resumen_tras_cierre(session, {
            c.id: c.cerrado_definitivamente_en for c, _, _ in filas_crudas if c.cerrado_definitivamente_en is not None
        })

        # Lapso de gracia (2026-10-07): el chip "Respondió tras el cierre" solo vive dentro del
        # lapso (24 h por defecto). Pasado el lapso, lo que el cliente escriba queda como mensaje
        # suelto: sigue sin contar como pendiente (`descontar_pendientes`), pero sin chip.
        gracia_horas = await obtener_cierre_gracia_horas(negocio_id)
        ahora_lista = datetime.utcnow()

        filas = []
        for conversation, contact, opportunity in filas_crudas:
            tras_cierre = tras_cierre_por_conv.get(conversation.id)
            en_lapso = cierre_en_lapso_de_gracia(conversation.cerrado_definitivamente_en, ahora_lista, gracia_horas)
            if tras_cierre is not None and not en_lapso:
                visible_tras_cierre = None
            else:
                visible_tras_cierre = tras_cierre
            filas.append({
                "id": conversation.id, "telefono": contact.telefono,
                "version": conversation.version,
                "revision_prioritaria": conversation.revision_prioritaria,
                "pausado_manual": conversation.pausado_manual,
                "asesor_asignado": conversation.asesor_asignado_id,
                "nombre": contact.nombre,
                "interes": opportunity.interes if opportunity else None,
                "resultado": opportunity.resultado if opportunity else None,
                "actualizado": iso_utc(conversation.actualizado),
                "ultimo_mensaje_en": iso_utc(conversation.ultimo_mensaje_en or conversation.creado),
                "creado": iso_utc(conversation.creado),
                "fecha_agendada": opportunity.fecha_agendada.isoformat() if opportunity and opportunity.fecha_agendada else None,
                "visto_asesor": conversation.visto_asesor,
                "mensajes_pendientes": max(
                    0, pendientes_por_conv.get(conversation.id, 0) - (tras_cierre["descontar_pendientes"] if tras_cierre else 0),
                ),
                "ultimo_mensaje": ultimo_mensaje_por_conv.get(conversation.id),
                "cerrado_definitivamente_en": iso_utc(conversation.cerrado_definitivamente_en),
                "respondio_tras_cierre_en": iso_utc(visible_tras_cierre["ultimo_en"]) if visible_tras_cierre else None,
                "mensajes_tras_cierre": visible_tras_cierre["mensajes"] if visible_tras_cierre else 0,
                "cierre_gracia_horas": gracia_horas,
            })
        return filas, total


# ── Vistas de Inicio dentro de la Bandeja (2026-10-06, paquete P2) ──────
#
# "Ver los N en Conversaciones" de Inicio debe llevar a una lista donde estén
# EXACTAMENTE esos casos. El criterio de cada grupo NO se reimplementa acá:
# lo deciden `listar_clientes_esperando`, `listar_leads_esperando_asesor` y
# las citas de Inicio (`dashboard._citas_inicio`); quien llama (la ruta de la
# Bandeja) las invoca con los mismos argumentos que `inicio_json` y pasa los
# resultados a `componer_vista_inicio`, que solo los combina y ordena. Así
# cualquier corrección de esas funciones llega sola a la lista.

VISTAS_INICIO = (
    "responde_ahora", "ventana_cerrada", "sin_asesor", "escalados", "esperando", "citas", "citas_vencidas",
    "citas_vencidas_antiguas",
)


def componer_vista_inicio(
    vista: str, esperando: list[dict], esperando_asignar: list[dict],
    proximas: list[dict], vencidas: list[dict], incluir_supervision: bool,
) -> list[dict]:
    """Casos de una vista de Inicio, ya priorizados y sin repetir teléfono.

    Entradas = las mismas listas que usa Inicio. `incluir_supervision` es la
    visión total sin filtrar por asesor: solo ahí existen los grupos
    `sin_asesor` y `escalados` (un asesor no los ve). Cada entrada:
    `telefono`, `conversation_id` (None si todavía no se resolvió),
    `categoria` (mismos nombres que `zona_accion.items[].categoria`) y los
    datos de ventana de Meta cuando el cliente también está esperando.

    Orden de `responde_ahora`: escalados, sin asesor, y luego los clientes
    esperando CON LA VENTANA DE 24 H ABIERTA en el orden que ya trae
    `listar_clientes_esperando` (la que vence antes, primero). R4 (2026-10-07):
    `ventana_cerrada` = los clientes esperando con la ventana cerrada (hay que
    llamar o enviar plantilla), del más reciente al más antiguo; `esperando` sigue
    siendo todos."""
    por_telefono = {c["telefono"]: c for c in esperando}

    def _entrada(fuente: dict, categoria: str) -> dict:
        espera = por_telefono.get(fuente["telefono"])
        return {
            "telefono": fuente["telefono"],
            "conversation_id": fuente.get("conversation_id") or (espera or {}).get("conversation_id"),
            "categoria": categoria,
            "ultimo_mensaje_cliente_en": espera["ultimo_mensaje_cliente_en"] if espera else None,
            "ventana_vence_en": espera["ventana_vence_en"] if espera else None,
            "ventana_abierta": espera["ventana_abierta"] if espera else None,
        }

    escalados = [l for l in esperando_asignar if l.get("escalado_supervision_en")] if incluir_supervision else []
    sin_asesor = [l for l in esperando_asignar if not l.get("escalado_supervision_en")] if incluir_supervision else []

    entradas: list[dict] = []
    if vista == "escalados":
        entradas = [_entrada(l, "escalado") for l in escalados]
    elif vista == "sin_asesor":
        entradas = [_entrada(l, "sin_asesor") for l in sin_asesor]
    elif vista == "esperando":
        entradas = [_entrada(c, "cliente_esperando") for c in esperando]
    elif vista == "citas":
        entradas = [_entrada(l, "cita") for l in proximas]
    elif vista in ("citas_vencidas", "citas_vencidas_antiguas"):
        # `vencidas` ya llega acotada por quien llama: las de los últimos 7 días o, para `citas_vencidas_antiguas`
        # (2026-10-13), las de hace más de 7 días que Inicio solo cuenta en `totales.citas_vencidas_antiguas`.
        entradas = [_entrada(l, "cita_vencida") for l in vencidas]
    elif vista == "ventana_cerrada":
        entradas = [_entrada(c, "cliente_esperando") for c in esperando if not c["ventana_abierta"]]
    elif vista == "responde_ahora":
        entradas = (
            [_entrada(l, "escalado") for l in escalados]
            + [_entrada(l, "sin_asesor") for l in sin_asesor]
            + [_entrada(c, "cliente_esperando") for c in esperando if c["ventana_abierta"]]
        )
    vistos: set[str] = set()
    unicas = []
    for e in entradas:
        if e["telefono"] in vistos:
            continue
        vistos.add(e["telefono"])
        unicas.append(e)
    return unicas


async def resolver_entradas_vista_inicio(negocio_id: str, entradas: list[dict]) -> list[dict]:
    """Completa el `conversation_id` de las entradas que no lo traen (una sola
    consulta, no una por caso) y descarta las que no tienen Conversation
    activa — no hay chat al que llevarlas — y los `conversation_id`
    repetidos. Conserva el orden."""
    faltantes = [e["telefono"] for e in entradas if not e["conversation_id"]]
    resueltos = await resolver_conversation_ids_por_telefono(negocio_id, faltantes) if faltantes else {}
    resultado, vistos = [], set()
    for e in entradas:
        conversation_id = e["conversation_id"] or resueltos.get(e["telefono"])
        if not conversation_id or conversation_id in vistos:
            continue
        vistos.add(conversation_id)
        resultado.append({**e, "conversation_id": conversation_id})
    return resultado


def _dto_contact(contact: "Contact") -> dict:
    return {
        "id": contact.id, "telefono": contact.telefono, "nombre": contact.nombre,
        "creado": iso_utc(contact.creado), "actualizado": iso_utc(contact.actualizado),
    }


def _dto_conversation_resumen(conversation: "Conversation", opportunity: "Opportunity | None") -> dict:
    return {
        "id": conversation.id, "estado": conversation.estado,
        "asesor_asignado": conversation.asesor_asignado_id,
        "interes": opportunity.interes if opportunity else None,
        "resultado": opportunity.resultado if opportunity else None,
        "creado": iso_utc(conversation.creado), "actualizado": iso_utc(conversation.actualizado),
    }


async def obtener_contact_detalle(contact_id: str, negocio_id: str) -> dict | None:
    """Gate 5.3 §17 — historial estructural del Contact: la identidad del
    cliente más el resumen de TODAS sus Conversation (no solo la activa),
    cada una con su Opportunity vigente. Doble candado `id + negocio_id`
    (nunca un Contact de otro Negocio, aunque alguien adivine el UUID) —
    mismo criterio que `_verificar_ownership_campana`/`_verificar_ownership_canal`:
    404, no 403, para no confirmar la existencia del recurso a quien no
    tiene acceso. Solo estructura de datos — la UI del historial es de un
    Gate posterior (Diseño Técnico Gate 5.3 §17)."""
    async with async_session() as session:
        contact = await session.get(Contact, contact_id)
        if contact is None or contact.negocio_id != negocio_id or contact.eliminado_en is not None:
            return None
        dto = _dto_contact(contact)
        dto["conversaciones"] = await listar_conversaciones_de_contact(contact_id, negocio_id)
        return dto


async def obtener_conversation_detalle(conversation_id: str, negocio_id: str) -> dict | None:
    """Detalle de una Conversation puntual — Gate 5.3 cutover real §8/§13:
    REEMPLAZA la rama JSON de `/lead/{telefono}` para la Nueva Experiencia
    (antes solo traía un resumen liviano; ahora lleva todos los campos que
    `_dto_lead_detalle` armaba desde Lead, resueltos desde Opportunity/
    Conversation/Contact). Mismo doble candado `id + negocio_id` que
    `obtener_contact_detalle`. El router (`dashboard.py`) todavía envuelve
    esto con `listar_lineas_venta_por_opportunity` + `listar_eventos_de_
    conversation` para armar `venta`/`eventos` — mismo patrón que
    `_dto_lead_detalle` (memory.py trae los datos, dashboard.py arma el DTO
    final, ninguna de las dos capas duplica a la otra).

    `cierre_gracia_horas` (2026-10-07): lapso de gracia del cierre definitivo del negocio; el
    frontend decide con él si "Reabrir caso" pide motivo y si se muestra el banner."""
    gracia_horas = await obtener_cierre_gracia_horas(negocio_id)
    async with async_session() as session:
        conversation = await session.get(Conversation, conversation_id)
        if conversation is None or conversation.negocio_id != negocio_id:
            return None
        contact = await session.get(Contact, conversation.contact_id)
        opportunity = await _obtener_opportunity_vigente(session, conversation.id)
        return {
            "cierre_gracia_horas": gracia_horas,
            "id": conversation.id,
            "telefono": contact.telefono if contact else None,
            "nombre": contact.nombre if contact else None,
            "opportunity_id": opportunity.id if opportunity else None,
            "interes": opportunity.interes if opportunity else None,
            "resultado": opportunity.resultado if opportunity else None,
            "fecha_agendada": opportunity.fecha_agendada if opportunity else None,
            "fecha_cierre": opportunity.fecha_cierre if opportunity else None,
            "modalidad_pago": opportunity.modalidad_pago if opportunity else None,
            "cuotas": opportunity.cuotas if opportunity else None,
            "monto_financiado": opportunity.monto_financiado if opportunity else None,
            "cuota_pactada": opportunity.cuota_pactada if opportunity else None,
            "tea_pactada": opportunity.tea_pactada if opportunity else None,
            "igv_pactado": opportunity.igv_pactado if opportunity else None,
            "medio_pago": opportunity.medio_pago if opportunity else None,
            "asesor_asignado": conversation.asesor_asignado_id,
            "pausado_manual": conversation.pausado_manual,
            "cerrado_definitivamente_en": conversation.cerrado_definitivamente_en,
            "revision_prioritaria": conversation.revision_prioritaria,
            "conversation_version": conversation.version,
            "opportunity_version": opportunity.version if opportunity else None,
            "creado": conversation.creado,
            "actualizado": conversation.actualizado,
        }


async def listar_lineas_venta_por_opportunity(opportunity_id: str, negocio_id: str) -> list[dict]:
    """Igual que `listar_lineas_venta` pero indexado directo por
    `opportunity_id` (no por el puente telefono→Conversation activa) — para
    poder mostrar la venta de una Opportunity puntual, incluida una ya
    cerrada/histórica. Doble candado `opportunity_id + negocio_id`, mismo
    criterio que el resto de LineaVenta."""
    async with async_session() as session:
        query = (
            select(LineaVenta)
            .where(LineaVenta.opportunity_id == opportunity_id, LineaVenta.negocio_id == negocio_id)
            .order_by(LineaVenta.id.asc())
        )
        result = await session.execute(query)
        return [
            {
                "id": l.id, "producto_id": l.producto_id,
                "producto": l.producto, "precio": l.precio, "marca": l.marca, "proveedor": l.proveedor,
                "creado": l.creado,
            }
            for l in result.scalars().all()
        ]


async def resolver_ids_operables_por_telefono(telefono: str) -> dict | None:
    """Puente telefono → (conversation_id, opportunity_id) para que los
    endpoints LEGACY (`/lead/{telefono}/resultado|venta|asignar`, Gate 5.3
    cutover real §7) puedan delegar hacia las funciones atómicas nuevas sin
    que el cliente legacy conozca esos IDs. Mismo puente y misma limitación
    conocida que `_obtener_conversation_activa_por_telefono` (bridge por
    Lead.telefono, todavía PK global — ver test
    `test_limitacion_conocida_bridge_telefono_solo_sirve_al_negocio_del_lead`).
    None si todavía no hay Conversation/Opportunity para este teléfono (Lead
    pre-existente sin backfill, o entorno que no pasó por el webhook) — en
    ese caso el llamador no tiene nada que delegar y Lead sigue siendo la
    única fuente por ahora."""
    async with async_session() as session:
        conversation = await _obtener_conversation_activa_por_telefono(session, telefono)
        if conversation is None:
            return None
        opportunity = await _obtener_opportunity_vigente(session, conversation.id)
        if opportunity is None:
            return None
        return {
            "conversation_id": conversation.id, "conversation_version": conversation.version,
            "opportunity_id": opportunity.id, "opportunity_version": opportunity.version,
        }


async def resolver_opportunity_operable(opportunity_id: str, negocio_id: str) -> dict | None:
    """Gate 5.3 cutover real §9 — lo mínimo para AUTORIZAR y operar sobre una
    Opportunity antes de escribir: `negocio_id` (ownership, resuelto
    server-side, nunca del cliente) y el `asesor_asignado` de su Conversation
    (mismo criterio de rol que `_verificar_acceso_lead`). None si la
    Opportunity no existe o es de otro Negocio — el router responde 404 sin
    distinguir cuál de los dos casos fue (no confirma la existencia del
    recurso a quien no tiene acceso)."""
    async with async_session() as session:
        opportunity = await session.get(Opportunity, opportunity_id)
        if opportunity is None or opportunity.negocio_id != negocio_id:
            return None
        conversation = await session.get(Conversation, opportunity.conversation_id)
        return {
            "id": opportunity.id, "conversation_id": opportunity.conversation_id,
            "version": opportunity.version, "resultado": opportunity.resultado,
            "asesor_asignado": conversation.asesor_asignado_id if conversation else None,
            "cuotas": opportunity.cuotas, "monto_financiado": opportunity.monto_financiado,
            "cuota_pactada": opportunity.cuota_pactada, "tea_pactada": opportunity.tea_pactada,
            "igv_pactado": opportunity.igv_pactado,
        }


async def resolver_conversation_operable(conversation_id: str, negocio_id: str) -> dict | None:
    """Mismo criterio que `resolver_opportunity_operable`, para Conversation
    (asignación/liberación)."""
    async with async_session() as session:
        conversation = await session.get(Conversation, conversation_id)
        if conversation is None or conversation.negocio_id != negocio_id:
            return None
        return {"id": conversation.id, "version": conversation.version, "asesor_asignado": conversation.asesor_asignado_id}


async def listar_conversaciones_de_contact(contact_id: str, negocio_id: str) -> list[dict]:
    """Todas las Conversation de un Contact (activas Y cerradas), de la más
    reciente a la más antigua — el historial que DR-4 va acumulando cada vez
    que abre una Conversation nueva tras un cierre no-venta. Doble candado
    `contact_id + negocio_id`."""
    async with async_session() as session:
        query = (
            select(Conversation)
            .where(Conversation.contact_id == contact_id, Conversation.negocio_id == negocio_id)
            .order_by(Conversation.creado.desc())
        )
        conversaciones = (await session.execute(query)).scalars().all()
        resultado = []
        for conversation in conversaciones:
            opportunity = await _obtener_opportunity_vigente(session, conversation.id)
            resultado.append(_dto_conversation_resumen(conversation, opportunity))
        return resultado


async def listar_eventos_de_conversation(conversation_id: str, negocio_id: str) -> list[dict]:
    """Conversation Timeline de UNA Conversation puntual (a diferencia de
    `listar_eventos_lead`, que resuelve la Conversation ACTIVA vía el puente
    telefono → Lead) — para poder ver el timeline de una Conversation ya
    cerrada, no solo la vigente. Mismo doble candado `conversation_id +
    negocio_id` que el resto de la tabla (regla crítica de EventoLead, ver
    la clase)."""
    async with async_session() as session:
        query = (
            select(EventoLead)
            .where(EventoLead.conversation_id == conversation_id, EventoLead.negocio_id == negocio_id)
            .order_by(EventoLead.creado.desc())
        )
        return [
            {
                "id": e.id, "conversation_id": e.conversation_id, "opportunity_id": e.opportunity_id,
                "tipo": e.tipo, "descripcion": e.descripcion, "payload": e.payload,
                "autor": e.autor, "creado": iso_utc(e.creado),
            }
            for e in (await session.execute(query)).scalars().all()
        ]


class Campana(Base):
    """
    Campaña de marketing (SMS, wa.link, o anuncio de Meta) que trae leads al
    WhatsApp. Administrable desde el panel para que cambiar la promoción del
    mes no requiera tocar código.
    """
    __tablename__ = "campanas"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    nombre: Mapped[str] = mapped_column(String(100))
    # "texto_saludo": se detecta por una frase distintiva en el primer mensaje
    #   (ej. wa.link con saludo pre-armado, usado en SMS/web).
    # "referral_meta": se detecta por el ID del anuncio que Meta manda en el
    #   webhook cuando el lead viene de un anuncio de Facebook/Instagram.
    tipo_deteccion: Mapped[str] = mapped_column(String(20))
    patron: Mapped[str] = mapped_column(String(300))
    # Si se llena, el producto/precio de la promo se toman SIEMPRE en vivo de
    # la lista de precios vigente (por el código único de material) — así la
    # campaña nunca queda desactualizada si el precio cambia. producto_promocional
    # y precio_promocional (texto libre) quedan como respaldo manual para
    # promociones que no están en el catálogo o cuando no se indica código.
    codigo_material: Mapped[str | None] = mapped_column(String(30), nullable=True)
    producto_promocional: Mapped[str | None] = mapped_column(String(300), nullable=True)
    precio_promocional: Mapped[str | None] = mapped_column(String(30), nullable=True)
    # Texto de saludo completo (wa.link/SMS) que originó esta campaña — se
    # guarda para poder regenerar el enlace de WhatsApp si hace falta.
    texto_saludo: Mapped[str | None] = mapped_column(String(500), nullable=True)
    activa: Mapped[bool] = mapped_column(Boolean, default=True)
    creado: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    # Gate 5.2 — Master Data, aislamiento estructural directo en la fila.
    # NOT NULL a nivel de BD tras el backfill (corrección post-auditoría,
    # mismo motivo que Lead.negocio_id arriba).
    negocio_id: Mapped[str] = mapped_column(String(36), ForeignKey("negocios.id"), nullable=False, index=True)
    # Arquitectura Contractual §5: obligatoria (NOT NULL) para campañas
    # NUEVAS desde este Gate en adelante — a nivel de aplicación (ver
    # crear_campana). A nivel de columna queda nullable porque las Unidades
    # reales de Cálidda todavía no están definidas (dato pendiente, no se
    # inventa) — las campañas existentes no pueden backfillearse sin
    # inventar una Unidad, lo cual está expresamente prohibido.
    unidad_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("unidades_de_negocio.id"), nullable=True)


class AnuncioCampana(Base):
    """Regla explícita "este anuncio de Meta (source_id) pertenece a esta
    campaña" (2026-10-13). Es lo que reconoce a los leads FUTUROS de un
    anuncio sin depender de palabras clave: se escribe al asignar un anuncio
    a una campaña desde "Anuncios detectados". Una sola campaña por anuncio
    y Negocio. Gana siempre sobre la detección por patrón (ver
    campanas.resolver_campana_por_referral)."""
    __tablename__ = "anuncio_campana"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_generar_uuid)
    negocio_id: Mapped[str] = mapped_column(String(36), ForeignKey("negocios.id"), nullable=False, index=True)
    source_id: Mapped[str] = mapped_column(String(200))
    campana_id: Mapped[int] = mapped_column(Integer, ForeignKey("campanas.id"), nullable=False)
    creado: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    creado_por: Mapped[str | None] = mapped_column(String(50), nullable=True)

    __table_args__ = (
        Index("ix_anuncio_campana_negocio_source", "negocio_id", "source_id", unique=True),
    )


class CanalWhatsApp(Base):
    """Un número de WhatsApp (Meta Cloud API) que Gabi puede usar para recibir
    y responder mensajes. Permite tener varios números activos a la vez (ej.
    pruebas y producción) administrables desde el panel, en vez de fijos en
    variables de entorno. access_token/app_secret/page_access_token se
    guardan CIFRADOS (ver _cifrar/_descifrar) — a diferencia de las demás
    credenciales del proyecto, estas sí viven en la base de datos."""
    __tablename__ = "canales_whatsapp"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    nombre: Mapped[str] = mapped_column(String(100))
    phone_number_id: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    access_token_cifrado: Mapped[str | None] = mapped_column(Text, nullable=True)
    app_secret_cifrado: Mapped[str | None] = mapped_column(Text, nullable=True)
    page_access_token_cifrado: Mapped[str | None] = mapped_column(Text, nullable=True)
    # WhatsApp Business Account ID — solo lo devuelve Embedded Signup (Conectar
    # WhatsApp); un canal creado a mano con el formulario clásico se queda sin
    # esto, por eso es nullable. Necesario para suscribir la app a los webhooks
    # de esa WABA específica.
    waba_id: Mapped[str | None] = mapped_column(String(50), nullable=True)
    # Cuándo se guardó por última vez un access_token real (creación o
    # renovación vía "Editar canal") — nullable porque los canales creados
    # antes de este campo no tienen este dato hasta que se re-guarde el
    # token una vez. Solo tiene sentido calcular el vencimiento de 60 días
    # de Coexistencia cuando además hay waba_id (ver dashboard.py,
    # _estado_token_canal) — un canal manual puede tener un token
    # permanente sin ninguna caducidad conocida.
    token_renovado_en: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    activo: Mapped[bool] = mapped_column(Boolean, default=True)
    # "produccion" (usa el prompt promovido, guardado en Configuracion — no
    # cambia solo con un deploy) o "pruebas" (usa siempre config/prompts.yaml
    # tal cual está desplegado) — permite probar cambios de Gabi en un canal
    # antes de que lleguen al de producción. Default "produccion" para que un
    # canal ya existente (de antes de este campo) no cambie de comportamiento.
    modo: Mapped[str] = mapped_column(String(20), default="produccion")
    creado: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    actualizado: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    # Gate 5.2 — Master Data, aislamiento estructural. NOT NULL a nivel de
    # BD tras el backfill (todo canal existente hoy es de Cálidda, sin
    # ambigüedad — corrección post-auditoría, mismo motivo que Lead arriba).
    negocio_id: Mapped[str] = mapped_column(String(36), ForeignKey("negocios.id"), nullable=False, index=True)
    # Arquitectura Contractual §6: 1 Canal : 1 Unidad hacia adelante, con
    # excepción temporal de migración para el legado — nullable mientras las
    # Unidades reales de Cálidda no estén definidas (mismo motivo que
    # Campana.unidad_id arriba, no se inventa).
    unidad_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("unidades_de_negocio.id"), nullable=True)


class IdentidadAgente(Base):
    """Identidad y comportamiento de Gabi (u otro agente futuro) PARA UN
    NEGOCIO — GATE 4.2, cierre de la Decisión Pendiente 1 de Gate 4.1.

    Decisión (evidencia, no preferencia): tabla propia, NO claves
    namespaced en `Configuracion`. Tres motivos, todos verificados contra
    el código real:
    1. `Configuracion.valor` es `String(200)` — el system prompt real de
       Cálidda mide ~5.400 caracteres. Reusar `Configuracion` exigía
       ensanchar esa columna igual (mismo tipo de bug ya visto una vez:
       `fe7af0de58f1_ampliar_productos_combo_a_text.py`, "SQLite no aplica
       el límite de VARCHAR, Postgres sí, descubierto contra Postgres
       real") — a partir de ahí, las dos opciones requieren migración por
       igual, y deja de ser el criterio decisivo.
    2. Gabi es un módulo de producto de primera clase (MPA §7, "Agentes
       IA" es una fila propia del mapa de 9 módulos, separada de "Canales
       & Configuración") — no una "config puntual" como `umbral_senior`.
    3. Evolución a múltiples agentes por negocio (pedido explícito del
       Gate): con claves de texto (`gabi.tono`) un segundo agente exige
       inventar un prefijo dentro del string (`gabi_soporte.tono`),
       frágil y sin tipar. Acá alcanza con una fila más — `codigo`
       distingue agentes del mismo Negocio sin tocar el esquema.

    `configuracion_negocio` contiene, VERBATIM, el bloque de identidad +
    conocimiento propio del negocio (ver `agent/brain.py`,
    `obtener_system_prompt`) — hoy, para Cálidda, es exactamente el
    `system_prompt` completo de `config/prompts.yaml` al momento de este
    Gate, sin recortar ni reordenar ni una palabra (verificado con test de
    igualdad exacta, `tests/test_gate42_identidad_agente.py`). La
    separación real entre "patrón estructural" (reglas que hoy ya viven
    inline en ese mismo texto: uso del contexto, no inventar, idioma,
    tono de respuesta) y "configuración del negocio" queda documentada en
    el informe de este Gate, pero NO se ejecuta todavía como una edición
    quirúrgica del texto en producción — mover esas reglas fuera del
    bloque cambiaría lo que Gabi recibe hoy, y eso es exactamente el tipo
    de "comportamiento productivo sensible" que Gate 4.2 §11 pide
    detener y preguntar, no decidir en silencio con una reorganización de
    texto ya afinado en producción."""
    __tablename__ = "identidades_agente"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    negocio_id: Mapped[str] = mapped_column(String(36), ForeignKey("negocios.id"), nullable=False, index=True)
    # Dos agentes del mismo Negocio no pueden compartir código — hoy
    # siempre "gabi", pero la fila ya lo deja resuelto para cuando un
    # Negocio tenga más de un agente (soporte, cobranza, etc.).
    codigo: Mapped[str] = mapped_column(String(30), default="gabi")
    nombre: Mapped[str] = mapped_column(String(50))
    tono: Mapped[str] = mapped_column(String(200))
    configuracion_negocio: Mapped[str] = mapped_column(Text)
    # GATE 4.3 — activación controlada y reversible del ensamblador
    # (patrón estructural + configuración de negocio) en vez del texto
    # verbatim de `configuracion_negocio` tal cual. Default False a
    # propósito: ningún Negocio existente cambia de comportamiento solo
    # por agregarse esta columna — el fallback al texto verbatim es
    # automático mientras esto sea False. Ver
    # `agent/brain.py::obtener_system_prompt`.
    usa_patron_estructural: Mapped[bool] = mapped_column(Boolean, default=False)
    creado: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    actualizado: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        Index("ix_identidad_agente_negocio_codigo", "negocio_id", "codigo", unique=True),
    )


class HorarioAtencion(Base):
    """Horario de atención de asesores humanos, POR NEGOCIO — Gate 4.2,
    cierre de la Decisión Pendiente 5 de Gate 4.1.

    Hallazgo del propio Gate 4.2 (no identificado en Gate 4.1): el
    horario NO vivía solo como texto muerto en `business.yaml` — hay un
    cálculo real y activo en `agent/tools.py::obtener_estado_horario_atencion()`,
    llamado en cada turno desde `agent/brain.py::_armar_bloques_contexto`
    (`:186`), con el rango HARDCODEADO en Python (`time(8,0)`/`time(19,0)`,
    lunes a sábado) — cero relación con `negocio_id`. Esta tabla reemplaza
    esa constante; ver la migración de backfill para la carga de los 7
    días de Cálidda con el mismo rango que ya estaba hardcodeado (mismo
    resultado, ninguna diferencia de comportamiento para el negocio_id
    existente).

    Una fila por día de la semana por Negocio — no un intervalo libre: no
    hay evidencia hoy (ni en el texto de Cálidda ni en ningún otro lugar)
    de más de un rango por día, de días especiales ni de excepciones de
    fecha — construir eso ahora sería sobre-construir sin evidencia (Gate
    4.2 §5, explícito). `hora_apertura`/`hora_cierre` son `None` cuando
    `habilitado=False` (día cerrado, ej. domingo)."""
    __tablename__ = "horarios_atencion"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    negocio_id: Mapped[str] = mapped_column(String(36), ForeignKey("negocios.id"), nullable=False, index=True)
    # 0=lunes … 6=domingo — mismo criterio que datetime.weekday(), para no
    # traducir entre convenciones en cada lectura/escritura.
    dia_semana: Mapped[int] = mapped_column(Integer)
    habilitado: Mapped[bool] = mapped_column(Boolean, default=True)
    # "HH:MM", 24h — texto y no `Time` porque es exactamente el formato
    # que ya usa datetime.time(...).strftime, sin zona (la zona la aplica
    # quien consulta, ver obtener_estado_horario_atencion, siempre
    # America/Lima hoy — un negocio en otra zona horaria es un gap
    # explícitamente fuera del alcance de este Gate, sin evidencia de
    # necesitarse todavía).
    hora_apertura: Mapped[str | None] = mapped_column(String(5), nullable=True)
    hora_cierre: Mapped[str | None] = mapped_column(String(5), nullable=True)

    __table_args__ = (
        Index("ix_horario_negocio_dia", "negocio_id", "dia_semana", unique=True),
    )


class DiaEspecial(Base):
    """Excepción de fecha del horario de atención, POR NEGOCIO (2026-10-12, calendario de negocio Fase 1; lógica pura
    en `agent/calendario_negocio.py`). Una fila por día de Lima: feriado nacional, día no laborable, puente, día de
    atención especial (horario reducido o extendido) o cierre propio del negocio. Manda sobre `HorarioAtencion`.

    `atiende=False` = cerrado todo el día; `atiende=True` con `hora_apertura`/`hora_cierre` = ese horario especial.
    Borrado LÓGICO (`eliminado_en`): el índice único parcial permite una sola fila VIVA por (negocio, fecha) y
    conserva las eliminadas (así la siembra respeta lo que el administrador quitó). `origen`: precargado_pe (siembra
    de feriados nacionales) | manual."""
    __tablename__ = "dias_especiales"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_generar_uuid)
    negocio_id: Mapped[str] = mapped_column(String(36), ForeignKey("negocios.id"), nullable=False, index=True)
    fecha: Mapped[date] = mapped_column(Date, nullable=False)       # día de Lima
    tipo: Mapped[str] = mapped_column(String(20), nullable=False)    # feriado | no_laborable | puente | atencion_especial | cierre_propio
    nombre: Mapped[str] = mapped_column(String(100), nullable=False)
    atiende: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    hora_apertura: Mapped[str | None] = mapped_column(String(5), nullable=True)   # "HH:MM"
    hora_cierre: Mapped[str | None] = mapped_column(String(5), nullable=True)
    origen: Mapped[str] = mapped_column(String(20), nullable=False, default="manual")
    fuente_url: Mapped[str | None] = mapped_column(String(300), nullable=True)
    creado: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    creado_por: Mapped[str | None] = mapped_column(String(50), nullable=True)
    actualizado: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    eliminado_en: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    eliminado_por: Mapped[str | None] = mapped_column(String(50), nullable=True)

    __table_args__ = (
        Index("ix_dias_especiales_negocio_fecha", "negocio_id", "fecha"),
        # A lo sumo UNA fila viva por negocio y fecha; las eliminadas no cuentan (mismo patrón que
        # ix_conversation_una_activa_por_contact). Funciona igual en SQLite y en Postgres.
        Index(
            "ix_dia_especial_una_viva_por_fecha", "negocio_id", "fecha", unique=True,
            sqlite_where=text("eliminado_en IS NULL"),
            postgresql_where=text("eliminado_en IS NULL"),
        ),
    )


class Usuario(Base):
    """Cuenta de acceso al panel interno (/dashboard). Roles: admin, supervisor, asesor.

    Gate 5.4 (T3) — PK migrada de `username` (global) a `id` (UUID). Antes
    de este Gate, `username` como PK global implicaba que dos Negocios NO
    podían tener ambos, por ejemplo, un usuario "admin" — y `crear_usuario()`
    pisaba silenciosamente password/rol de la cuenta de OTRO Negocio si
    coincidía el username (hallazgo real, Arquitectura Integrada Gate 5.4,
    T3: no era solo sobre-escritura de metadata, permitía toma de cuenta
    cross-tenant vía reset de password). `username` sigue siendo el
    identificador de login — único ahora por `(negocio_id, username)`, no
    globalmente (mismo patrón que `Contact.negocio_id+telefono`, Gate 5.3:
    el precedente ya establecido en este repo para identificadores
    naturales en Multi-Tenant). Confirmado antes de este cambio: ningún FK
    real apunta a `Usuario.username` en todo el repo (`asesor_asignado`/
    `Conversation.asesor_asignado_id` son `String` sueltos por diseño) —
    la migración no tiene cascada que romper."""
    __tablename__ = "usuarios"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_generar_uuid)
    username: Mapped[str] = mapped_column(String(50))
    password_hash: Mapped[str] = mapped_column(String(200))
    nombre: Mapped[str] = mapped_column(String(100))
    rol: Mapped[str] = mapped_column(String(20))  # admin | supervisor | asesor
    # Solo aplica a asesores: nivel de experiencia (para la asignación
    # automática) y si está disponible para recibir leads nuevos ahora mismo.
    nivel: Mapped[str | None] = mapped_column(String(20), nullable=True)  # junior | intermedio | senior
    disponible: Mapped[bool] = mapped_column(Boolean, default=True)
    # Gate Equipo (toggle/eliminar, 2026-09-14) — apagar/prender una cuenta:
    # reversible, a diferencia de eliminado_en (abajo). Una cuenta inactiva
    # no puede iniciar sesión (ver login_submit en dashboard.py) pero sigue
    # existiendo tal cual — nunca se pierde su historial ni sus asignaciones.
    activo: Mapped[bool] = mapped_column(Boolean, default=True)
    # Gate 5.2 — Master Data. NOT NULL a nivel de BD tras el backfill (todo
    # usuario existente hoy pertenece a Cálidda, sin ambigüedad — corrección
    # post-auditoría). El RBAC real que CONSUME este campo (ServicioIdentidad,
    # tiene_acceso_a_lead) es Gate 5.4 — acá solo se agrega la columna, se
    # puebla, y se exige en la creación (crear_usuario, corrección H3), sin
    # tocar autorización.
    negocio_id: Mapped[str] = mapped_column(String(36), ForeignKey("negocios.id"), nullable=False, index=True)
    # Gate Equipo (toggle/eliminar, 2026-09-14) — soft delete, mismo patrón
    # que Contact/UnidadDeNegocio: NULL = nunca eliminada. `activo` (arriba)
    # es distinto y reversible (apagar/prender); esto es la eliminación,
    # nunca un DELETE real, para no romper referencias sueltas como
    # Conversation.asesor_asignado_id (String suelto, sin FK).
    eliminado_en: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    eliminado_por: Mapped[str | None] = mapped_column(String(50), nullable=True)

    __table_args__ = (
        Index("ix_usuario_negocio_username", "negocio_id", "username", unique=True),
    )


class Configuracion(Base):
    """Ajustes simples del panel (clave/valor) editables sin tocar código —
    hoy solo los umbrales de monto para la asignación automática por nivel,
    pero sirve para cualquier otro ajuste puntual que se agregue después.

    Gate 5.2 migra esta tabla al contrato de Arquitectura Contractual §7:
    clave compuesta (clave, negocio_id), con negocio_id = NULL como
    configuración GLOBAL de plataforma. `clave` deja de ser PK — Postgres (a
    diferencia de SQLite) no admite NULL dentro de una PRIMARY KEY, así que
    la unicidad real (negocio_id NULL o no-NULL, sin duplicados) se aplica
    con dos índices únicos parciales, no con la propia clave primaria (que
    pasa a ser un `id` autoincremental sin significado de negocio — esto es
    INFERENCIA de implementación a partir del contrato, no un cambio del
    contrato en sí, ver informe de cierre de Gate 5.2)."""
    __tablename__ = "configuracion"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # 50 → 100 (2026-10-05): `meta_uso_previo_servicio_AAAA-MM:<phone_number_id>` llegaba a 49.
    clave: Mapped[str] = mapped_column(String(100))
    negocio_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("negocios.id"), nullable=True)
    # 200 → 1000 (2026-10-09): el texto de la oferta de llamada y las plantillas configurables pasan de 200 (ver la
    # migración b8e2d4f6a1c3; SQLite no valida el largo, Postgres sí).
    valor: Mapped[str] = mapped_column(String(1000))

    __table_args__ = (
        # Único activo cuando negocio_id es NULL (config global de plataforma)
        Index(
            "ix_config_global_unica", "clave", unique=True,
            sqlite_where=text("negocio_id IS NULL"),
            postgresql_where=text("negocio_id IS NULL"),
        ),
        # Único activo cuando negocio_id NO es NULL (override por negocio)
        Index(
            "ix_config_por_negocio_unica", "clave", "negocio_id", unique=True,
            sqlite_where=text("negocio_id IS NOT NULL"),
            postgresql_where=text("negocio_id IS NOT NULL"),
        ),
    )


class MensajeProcesado(Base):
    """Idempotencia general del webhook (API Architecture, Decisión local
    ya `Objetivo`) — registra el `mensaje_id` de Meta de cada mensaje ya
    procesado, para no reprocesarlo si Meta lo reenvía (reintentos de
    entrega, entregas duplicadas). Tabla aditiva, sin dependencia de
    ninguna otra — solo necesitaba que existiera el baseline de Alembic
    (Data Architecture Fase 1) para poder agregarse con control de
    versiones. No tiene limpieza automática todavía (crecimiento sin
    límite) — proporcional al volumen actual, revisar si se vuelve un
    problema real (Evidence over Opinion)."""
    __tablename__ = "mensajes_procesados"

    mensaje_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    procesado_en: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class UsoMensajeMeta(Base):
    """Registro de uso y costo de cada mensaje SALIENTE, tal como lo informa
    Meta en los webhooks de estado (2026-10-04). Desde el 2026-10-01 los
    mensajes de servicio se cobran por mensaje tras una cuota gratuita por
    número, y hasta ahora el sistema ignoraba esos estados por completo: no
    había forma de saber qué mensaje se entregó ni cuál cobró Meta.

    Una fila por mensaje (clave = wamid). No calcula ni supone nada: guarda lo
    que Meta dice en `pricing` — `type` ∈ regular | free_customer_service |
    free_entry_point y `category` ∈ service | utility | marketing | ... —
    porque esas reglas cambian por fecha, país y categoría y no deben vivir
    como constantes en el código. Los estados llegan repetidos y fuera de
    orden (read antes que delivered): el registro es idempotente."""
    __tablename__ = "uso_mensajes_meta"

    wamid: Mapped[str] = mapped_column(String(100), primary_key=True)
    # phone_number_id de Meta del número del NEGOCIO (no del cliente): la
    # cuota gratuita es por business phone number.
    phone_number_id: Mapped[str] = mapped_column(String(50), nullable=False)
    negocio_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    destinatario: Mapped[str | None] = mapped_column(String(50), nullable=True)
    # sent | delivered | read | failed — el estado más avanzado visto
    # (failed solo si nunca se vio delivered/read).
    estado: Mapped[str] = mapped_column(String(20), nullable=False, default="sent")
    enviado_en: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    entregado_en: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    leido_en: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    fallido_en: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    error_codigo: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_titulo: Mapped[str | None] = mapped_column(String(200), nullable=True)
    pricing_billable: Mapped[bool | None] = mapped_column(Boolean, nullable=True)  # en desuso según Meta: usar pricing_type
    pricing_model: Mapped[str | None] = mapped_column(String(10), nullable=True)
    pricing_type: Mapped[str | None] = mapped_column(String(30), nullable=True)
    pricing_categoria: Mapped[str | None] = mapped_column(String(40), nullable=True)
    creado: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    actualizado: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        Index("ix_uso_mensajes_phone_entregado", "phone_number_id", "entregado_en"),
        Index("ix_uso_mensajes_negocio_entregado", "negocio_id", "entregado_en"),
    )


class EnvioMeta(Base):
    """Una fila por cada intento de enviar un mensaje de WhatsApp, con el ORIGEN
    que lo pidió (2026-10-04, Fase A de la capa central de envíos). Nace para
    poder responder "¿cuánto cuesta Gabi, el reenganche, las campañas?": cruzada
    por `wamid` con `uso_mensajes_meta` (lo que Meta cobró) da el costo por
    origen, y es la base de los interruptores pagar/no pagar de la Fase B.

    La fila se crea ANTES de enviar (decision="enviado", sin wamid) y se cierra
    después: así dos mensajes simultáneos del mismo cliente no pasan juntos el
    chequeo de agrupación. Si el envío falla pasa a "fallido" y deja de contar
    como enviado. "bloqueado" = la capa decidió no enviar (`motivo` lo dice)."""
    __tablename__ = "envios_meta"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    negocio_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    origen: Mapped[str] = mapped_column(String(40), nullable=False)
    # 150, como Mensaje.telefono (un BSUID de Meta puede ser más largo que un teléfono).
    telefono: Mapped[str] = mapped_column(String(150), nullable=False)
    tipo: Mapped[str] = mapped_column(String(20), nullable=False)  # texto | imagen | documento | audio | plantilla
    decision: Mapped[str] = mapped_column(String(20), nullable=False)  # enviado | fallido | bloqueado | incierto
    motivo: Mapped[str | None] = mapped_column(String(200), nullable=True)
    wamid: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    # Fase B: lo que la política estimó ANTES de enviar. `gratis_esperado` y
    # `costo_esperado_usd` quedan vacíos si no se pudo estimar; `categoria_esperada`
    # es la categoría de Meta que se supuso (service | marketing | utility...).
    categoria_esperada: Mapped[str | None] = mapped_column(String(30), nullable=True)
    gratis_esperado: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    costo_esperado_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Username del asesor que mandó el mensaje desde el panel (2026-10-05, decisión D5: atribuir
    # quién envía). NULL en los envíos de Gabi y de los scripts; los mensajes que el asesor manda
    # desde el celular (coexistencia) no pasan por esta capa y por eso no se atribuyen.
    asesor_usuario: Mapped[str | None] = mapped_column(String(50), nullable=True)
    creado: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        Index("ix_envios_meta_agrupacion", "negocio_id", "origen", "telefono", "creado"),
    )


class CronEjecucion(Base):
    """Latido de los procesos programados (Cron de Railway), 2026-10-05: una fila por corrida de
    cada script de `scripts/`, escrita por `scripts/_cron.py`. La fila se crea al EMPEZAR
    (`ok` NULL, `fin` NULL) y se cierra al terminar con `ok` y el `resumen` (lo que el script
    imprimió). Sirve para avisar en Inicio cuando un proceso falló en su última corrida o dejó de
    correr — hasta hoy un Cron caído pasaba inadvertido. Una corrida que arrancó y nunca cerró
    (el proceso murió) queda con `ok` NULL. No lleva `negocio_id`: los Cron son del sistema, no de
    un negocio."""
    __tablename__ = "cron_ejecuciones"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    script: Mapped[str] = mapped_column(String(60), nullable=False)
    inicio: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    fin: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    ok: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    resumen: Mapped[str | None] = mapped_column(String(300), nullable=True)

    __table_args__ = (
        Index("ix_cron_ejecuciones_script_inicio", "script", "inicio"),
    )

# Procesos programados que el panel vigila (aviso en Inicio, solo admin): nombre del script →
# (nombre legible, cada cuántos minutos debería correr). Si cambias un intervalo, cámbialo también
# en la llamada a `ejecutar_cron` del script (hay un test que verifica que coincidan).
CRONES_ESPERADOS: dict[str, tuple[str, int]] = {
    "liberar_leads_inactivos": ("Rotación de leads inactivos", 5),
    "procesar_inactividad_clientes": ("Reenganche y cierre de clientes sin respuesta", 30),
    "purgar_archivos_expirados": ("Purga de archivos expirados", 1440),
    "cerrar_leads_definitivamente": ("Cierre definitivo de leads", 1440),
    "cerrar_ventas_sin_seguimiento": ("Cierre de ventas sin seguimiento", 1440),
    "backup_postgres": ("Respaldo de la base de datos", 1440),
    "recuperar_mensajes_sin_respuesta": ("Recuperación de mensajes sin respuesta", 10),
    "plantilla_zona_muerta": ("Plantilla automática de fin de semana", 30),
    "crear_tareas_llamada": ("Tareas de llamada (Para llamar)", 15),
}
DIAS_RETENCION_CRON_EJECUCIONES = 30


async def registrar_inicio_cron(script: str, inicio: datetime | None = None) -> int:
    """Anota que `script` empezó a correr y devuelve el id de la fila. De paso borra las corridas
    de ese mismo script con más de `DIAS_RETENCION_CRON_EJECUCIONES` días (el de 5 min genera ~288
    filas al día; sin esto la tabla crecería sin límite)."""
    async with async_session() as session:
        await session.execute(
            delete(CronEjecucion).where(
                CronEjecucion.script == script[:60],
                CronEjecucion.inicio < datetime.utcnow() - timedelta(days=DIAS_RETENCION_CRON_EJECUCIONES),
            )
        )
        fila = CronEjecucion(script=script[:60], inicio=inicio or datetime.utcnow())
        session.add(fila)
        await session.commit()
        return fila.id


async def registrar_fin_cron(
    ejecucion_id: int | None, script: str, inicio: datetime, ok: bool, resumen: str | None = None,
) -> None:
    """Cierra la corrida `ejecucion_id` con su resultado. Si no hay id (no se pudo anotar el
    inicio: la base aún no contestaba) inserta la fila completa de una vez."""
    resumen = (resumen or "")[:300] or None
    async with async_session() as session:
        fila = await session.get(CronEjecucion, ejecucion_id) if ejecucion_id is not None else None
        if fila is None:
            fila = CronEjecucion(script=script[:60], inicio=inicio)
            session.add(fila)
        fila.fin, fila.ok, fila.resumen = datetime.utcnow(), ok, resumen
        await session.commit()


async def resumen_corridas_cron(scripts: list[str]) -> dict[str, dict]:
    """Última corrida de cada script de `scripts` que alguna vez corrió (los que nunca corrieron no
    aparecen). Por script: `ultima` {inicio, fin, ok, resumen} y `ultimo_ok_fin` (cuándo terminó
    la última corrida exitosa, o None). Dos consultas agrupadas, no una por script."""
    if not scripts:
        return {}
    async with async_session() as session:
        ultimos_inicios = (
            select(CronEjecucion.script.label("script"), func.max(CronEjecucion.inicio).label("inicio"))
            .where(CronEjecucion.script.in_(scripts)).group_by(CronEjecucion.script).subquery()
        )
        ultimas = (await session.execute(
            select(CronEjecucion).join(
                ultimos_inicios,
                sa_and(CronEjecucion.script == ultimos_inicios.c.script, CronEjecucion.inicio == ultimos_inicios.c.inicio),
            ).order_by(CronEjecucion.id)
        )).scalars().all()
        oks = dict((await session.execute(
            select(CronEjecucion.script, func.max(CronEjecucion.fin))
            .where(CronEjecucion.script.in_(scripts), CronEjecucion.ok.is_(True)).group_by(CronEjecucion.script)
        )).all())
    resultado: dict[str, dict] = {}
    for f in ultimas:   # si dos filas empatan en `inicio`, gana la de id mayor (orden ascendente)
        resultado[f.script] = {
            "ultima": {"inicio": f.inicio, "fin": f.fin, "ok": f.ok, "resumen": f.resumen},
            "ultimo_ok_fin": oks.get(f.script),
        }
    return resultado


def _campos_de_estimacion(estimacion) -> dict:
    if estimacion is None:
        return {}
    return {
        "categoria_esperada": estimacion.categoria, "gratis_esperado": estimacion.gratis,
        "costo_esperado_usd": estimacion.costo_usd,
    }


async def registrar_envio_bloqueado(
    negocio_id: str | None, origen: str, telefono: str, tipo: str, motivo: str, estimacion=None, asesor: str | None = None,
) -> None:
    """Deja constancia de un envío que la política decidió no hacer. Un mismo
    bloqueo (origen + cliente + motivo) se anota una vez por hora: un proceso
    que reintenta en cada corrida (el reenganche) no llena la tabla."""
    async with async_session() as session:
        repetido = (await session.execute(
            select(EnvioMeta.id).where(
                EnvioMeta.negocio_id == negocio_id, EnvioMeta.origen == origen, EnvioMeta.telefono == telefono,
                EnvioMeta.decision == "bloqueado", EnvioMeta.motivo == motivo[:200],
                EnvioMeta.creado >= datetime.utcnow() - timedelta(hours=1),
            ).limit(1)
        )).scalar_one_or_none()
        if repetido is not None:
            return
        session.add(EnvioMeta(
            negocio_id=negocio_id, origen=origen, telefono=telefono, tipo=tipo, decision="bloqueado",
            motivo=motivo[:200], asesor_usuario=(asesor[:50] if asesor else None), **_campos_de_estimacion(estimacion),
        ))
        await session.commit()


async def reservar_envio_meta(
    negocio_id: str | None, origen: str, telefono: str, tipo: str, agrupar_minutos: int = 0, estimacion=None,
    asesor: str | None = None,
) -> tuple[int | None, str | None]:
    """Registra el intento de envío. Con `agrupar_minutos` > 0, si ya hay un
    envío "enviado" del mismo origen al mismo cliente dentro de esa ventana no
    reserva nada: guarda un "bloqueado" y devuelve (None, motivo). Devuelve
    (id, None) si se puede enviar."""
    async with async_session() as session:
        if agrupar_minutos > 0:
            desde = datetime.utcnow() - timedelta(minutes=agrupar_minutos)
            previo = (await session.execute(
                select(EnvioMeta.id).where(
                    EnvioMeta.negocio_id == negocio_id, EnvioMeta.origen == origen,
                    EnvioMeta.telefono == telefono, EnvioMeta.decision == "enviado", EnvioMeta.creado >= desde,
                ).limit(1)
            )).scalar_one_or_none()
            if previo is not None:
                motivo = f"agrupado: ya se envió este aviso hace menos de {agrupar_minutos} min"
                session.add(EnvioMeta(
                    negocio_id=negocio_id, origen=origen, telefono=telefono, tipo=tipo, decision="bloqueado", motivo=motivo,
                    asesor_usuario=(asesor[:50] if asesor else None), **_campos_de_estimacion(estimacion),
                ))
                await session.commit()
                return None, motivo
        envio = EnvioMeta(
            negocio_id=negocio_id, origen=origen, telefono=telefono, tipo=tipo, decision="enviado",
            asesor_usuario=(asesor[:50] if asesor else None), **_campos_de_estimacion(estimacion),
        )
        session.add(envio)
        await session.commit()
        return envio.id, None


async def cerrar_envio_meta(envio_id: int, enviado: bool, wamid: str | None) -> None:
    """Cierra una reserva: guarda el wamid si Meta lo devolvió, o la marca
    "fallido" (deja de contar para la agrupación) si el envío no se confirmó."""
    async with async_session() as session:
        envio = await session.get(EnvioMeta, envio_id)
        if envio is None:
            return
        envio.decision = "enviado" if enviado else "fallido"
        envio.wamid = wamid if enviado else None
        await session.commit()


async def marcar_envio_incierto(envio_id: int, motivo: str) -> None:
    """Cierra una reserva cuyo resultado se desconoce (2026-10-05): el POST a
    Meta pudo haber llegado (ReadTimeout, 5xx...) pero no se supo si Meta
    creó el mensaje ni con qué wamid. Queda en "incierto", NO en "fallido":
    no se reenvía solo ni cuenta como enviado para la agrupación, y el informe
    de conciliación (`listar_envios_inciertos_o_huerfanos`) lo muestra."""
    async with async_session() as session:
        envio = await session.get(EnvioMeta, envio_id)
        if envio is None:
            return
        envio.decision = "incierto"
        envio.wamid = None
        envio.motivo = (motivo or "resultado desconocido")[:200]
        await session.commit()


async def buscar_wamid_huerfano(phone_number_id: str | None, telefono: str, desde: datetime, margen_segundos: int = 10) -> str | None:
    """Busca en `uso_mensajes_meta` un mensaje saliente al cliente `telefono`
    (desde el número `phone_number_id`, si se conoce) enviado desde `desde` −
    `margen_segundos` y que NADIE reclamó todavía: su wamid no está en
    `mensajes.mensaje_id_meta` ni en `envios_meta.wamid`. Sirve para resolver un
    envío incierto: si Meta aceptó el mensaje aunque la respuesta se perdió, su
    estado "sent" llega por webhook con ese wamid. Ignora los "failed" (no
    se entregó). Con varios candidatos devuelve el más antiguo. None si no hay."""
    desde_con_margen = desde - timedelta(seconds=margen_segundos)
    destinos = {telefono, telefono.lstrip("+"), "+" + telefono.lstrip("+")}
    consulta = (
        select(UsoMensajeMeta.wamid)
        .where(
            UsoMensajeMeta.destinatario.in_(destinos),
            UsoMensajeMeta.estado.in_(("sent", "delivered", "read")),
            sa_or(
                UsoMensajeMeta.enviado_en >= desde_con_margen,
                sa_and(UsoMensajeMeta.enviado_en.is_(None), UsoMensajeMeta.creado >= desde_con_margen),
            ),
            ~sa_exists().where(Mensaje.mensaje_id_meta == UsoMensajeMeta.wamid),
            ~sa_exists().where(EnvioMeta.wamid == UsoMensajeMeta.wamid),
        )
        .order_by(func.coalesce(UsoMensajeMeta.enviado_en, UsoMensajeMeta.creado))
        .limit(1)
    )
    if phone_number_id:
        consulta = consulta.where(UsoMensajeMeta.phone_number_id == phone_number_id)
    async with async_session() as session:
        return (await session.execute(consulta)).scalar_one_or_none()


async def listar_envios_inciertos_o_huerfanos(negocio_id: str, desde: datetime, minutos_sin_wamid: int = 5) -> dict:
    """Informe de conciliación entre lo que el sistema cree que envió y lo que
    Meta informó haber enviado (cobrado), desde `desde` (UTC naive):

    - `envios_inciertos`: filas de `envios_meta` en decision "incierto" (el
      POST pudo llegar a Meta y no se supo el resultado) o "enviado" SIN wamid
      con más de `minutos_sin_wamid` min (la fila quedó abierta o el
      proveedor no devolvió wamid — hoy no pasa con los envíos de texto).
    - `uso_sin_envio`: filas de `uso_mensajes_meta` cuyo wamid no está en
      `envios_meta.wamid` ni en `mensajes.mensaje_id_meta`: posibles copias
      duplicadas de un envío, o mensajes enviados fuera de la capa central
      (por ejemplo, el asesor desde la app de WhatsApp Business).
    Solo lectura."""
    limite_sin_wamid = datetime.utcnow() - timedelta(minutes=minutos_sin_wamid)
    async with async_session() as session:
        envios = (await session.execute(
            select(EnvioMeta).where(
                EnvioMeta.negocio_id == negocio_id, EnvioMeta.creado >= desde,
                sa_or(
                    EnvioMeta.decision == "incierto",
                    sa_and(EnvioMeta.decision == "enviado", EnvioMeta.wamid.is_(None), EnvioMeta.creado < limite_sin_wamid),
                ),
            ).order_by(EnvioMeta.creado.desc()).limit(500)
        )).scalars().all()
        huerfanos = (await session.execute(
            select(UsoMensajeMeta).where(
                UsoMensajeMeta.negocio_id == negocio_id,
                func.coalesce(UsoMensajeMeta.enviado_en, UsoMensajeMeta.creado) >= desde,
                ~sa_exists().where(EnvioMeta.wamid == UsoMensajeMeta.wamid),
                ~sa_exists().where(Mensaje.mensaje_id_meta == UsoMensajeMeta.wamid),
            ).order_by(func.coalesce(UsoMensajeMeta.enviado_en, UsoMensajeMeta.creado).desc()).limit(500)
        )).scalars().all()
    return {
        "desde": desde.isoformat(),
        "envios_inciertos": [
            {
                "id": e.id, "origen": e.origen, "telefono": e.telefono, "tipo": e.tipo, "decision": e.decision,
                "motivo": e.motivo, "wamid": e.wamid, "creado": e.creado.isoformat() + "Z",
            }
            for e in envios
        ],
        "uso_sin_envio": [
            {
                "wamid": u.wamid, "destinatario": u.destinatario, "phone_number_id": u.phone_number_id, "estado": u.estado,
                "enviado_en": u.enviado_en.isoformat() + "Z" if u.enviado_en else None,
                "pricing_type": u.pricing_type, "pricing_categoria": u.pricing_categoria,
            }
            for u in huerfanos
        ],
    }


class Producto(Base):
    """Catálogo de productos / lista de precios — fuente de verdad para
    Gabi (cotización en vivo), campañas, autocompletar de "Cierre de venta"
    y asignación automática por nivel. Antes vivía en
    knowledge/lista_precios_canales_propios.csv, cargado una sola vez a una
    variable de módulo sin invalidación (agent/tools.py). El CSV se
    conserva en el repo como respaldo y como mecanismo de importación
    masiva — ver importar_catalogo_desde_csv().

    `id` autoincremental es la clave primaria, NO `codigo_hana` — el
    catálogo real tiene productos "EN CREACIÓN" sin código HANA asignado
    todavía, así que ese campo no es único (confirmado en el CSV vigente).

    `negocio_id` (Gate 4.4): cada producto pertenece a un Negocio — antes
    de este Gate la tabla no tenía ningún concepto de tenant y todas las
    consultas mezclaban productos de cualquier origen (ver auditoría en
    tests/test_gate43_analisis_catalogo_riesgo.py). `codigo_hana` NO pasa a
    ser UNIQUE(negocio_id, codigo_hana) porque nunca fue único siquiera
    dentro de un solo negocio (ver arriba) — no hay ninguna restricción de
    unicidad que migrar."""
    __tablename__ = "productos"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    negocio_id: Mapped[str] = mapped_column(String(36), ForeignKey("negocios.id"), nullable=False, index=True)
    canal: Mapped[str | None] = mapped_column(String(100), nullable=True)
    proveedor: Mapped[str | None] = mapped_column(String(150), nullable=True)
    marca: Mapped[str | None] = mapped_column(String(100), nullable=True)
    tipo: Mapped[str | None] = mapped_column(String(50), nullable=True)
    sub_tipo: Mapped[str | None] = mapped_column(String(100), nullable=True)
    codigo_hana: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)
    descripcion: Mapped[str | None] = mapped_column(String(300), nullable=True)
    # Text, no String(100): un combo real del CSV mide 101 caracteres —
    # descubierto recién al importar contra Postgres real (2026-08-16),
    # SQLite no aplica el límite de VARCHAR y no lo había detectado antes.
    # Es contenido descriptivo, sin razón funcional para un tope artificial.
    combo: Mapped[str | None] = mapped_column(Text, nullable=True)
    # String, no Boolean (2026-09-15, pedido explícito: el asesor necesita
    # ver siempre si el producto incluye la conexión de gas o no, para no
    # guiarse solo por el precio) — mismo criterio que canal/tipo/marca:
    # texto libre que pasa gratis por el pipeline genérico de
    # CAMPOS_NEGOCIO_PRODUCTO (diff/auditoría/importación) sin ningún caso
    # especial. NULL = todavía no se sabe (dato no cargado), distinto de
    # "no incluye". Valores esperados: "Sí" / "No".
    incluye_conexion: Mapped[str | None] = mapped_column(String(20), nullable=True)
    comentarios: Mapped[str | None] = mapped_column(Text, nullable=True)
    fee_prv: Mapped[str | None] = mapped_column(String(30), nullable=True)
    fee_clda: Mapped[str | None] = mapped_column(String(30), nullable=True)
    precio: Mapped[str | None] = mapped_column(String(30), nullable=True)
    # Cuotas por plazo (3/6/9/12/18/24/36/48/60 meses) — un solo campo JSON
    # en vez de 9 columnas sueltas, mismo patrón ya usado en
    # EventoLead.payload. Reconstruido como claves top-level ("12", "24"...)
    # al armar el dict con forma de fila CSV, para no tocar la lógica de
    # negocio existente que ya lee producto["12"] etc.
    cuotas: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # Fila excluida por ser un duplicado real confirmado (antes vivía como
    # FILAS_DUPLICADAS_EXCLUIDAS hardcodeado en tools.py) — ahora es un dato,
    # no código. Nunca se borra una fila, solo se desactiva.
    activo: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    creado: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    actualizado: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    # Concurrencia optimista, mismo mecanismo y mismo criterio que Lead.version
    # (ver intentar_avanzar_version): se incrementa en cada escritura que
    # CAMBIA algo del producto — editar_producto, toggle_producto, y también
    # la importación masiva, pero SOLO sobre las filas que esa importación
    # modificó de verdad. Las filas que la importación deja idénticas no
    # avanzan versión, para no invalidar en bloque formularios abiertos sobre
    # productos que nadie tocó (mismo motivo por el que Lead no avanza versión
    # con los mensajes automáticos de Gabi: evitar conflictos falsos).
    version: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class HistorialPrecioProducto(Base):
    """Auditoría de cambios de precio de un producto — append-only, mismo
    patrón que EventoLead (Conversation Timeline). Todavía sin ningún punto
    de escritura real: la pantalla de edición de precios es un bloque
    futuro (sub-bloque UI del Gap Analysis de Catálogo editable) — la tabla
    y el helper de escritura existen desde ya para no requerir otra
    migración cuando esa UI se construya, igual que ya pasó con
    EventoLead/registrar_evento_lead en el Sprint 2."""
    __tablename__ = "historial_precio_producto"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    producto_id: Mapped[int] = mapped_column(Integer, index=True)
    campo: Mapped[str] = mapped_column(String(30))
    # Text, no String(50): la tabla nació pensando solo en precios y cuotas
    # (números cortos), pero la bitácora audita también descripcion/combo/
    # comentarios, que llegan a 300 caracteres. Se truncaba el valor guardado
    # para no romper el límite de Postgres; ahora se guarda completo — una
    # bitácora que muestra medio dato obliga a ir a buscar el otro medio a
    # otro lado, y el valor anterior ya no existe en ninguna parte. Mismo
    # motivo y mismo patrón que Producto.combo (ver fe7af0de58f1).
    valor_anterior: Mapped[str | None] = mapped_column(Text, nullable=True)
    valor_nuevo: Mapped[str | None] = mapped_column(Text, nullable=True)
    autor: Mapped[str | None] = mapped_column(String(100), nullable=True)
    creado: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)


async def obtener_configuracion(clave: str, valor_default: str, negocio_id: str | None = None) -> str:
    """Lee un valor de configuración. `negocio_id=None` (default, sin cambio
    de comportamiento para ningún llamador existente) lee la config GLOBAL de
    plataforma — exactamente el mismo dato que existía antes de Gate 5.2,
    ahora con negocio_id explícitamente NULL en vez de ausente por diseño de
    esquema. Con `negocio_id` explícito, lee el override de ESE negocio
    específico si existe; si no existe ninguna fila para ese negocio, cae al
    default recibido (no al valor global — un override ausente no es lo
    mismo que "usar el global", eso se resuelve en la capa que llama, mismo
    criterio que ya usaba `modo` en CanalWhatsApp para no cambiar
    comportamiento por accidente)."""
    async with async_session() as session:
        query = select(Configuracion).where(Configuracion.clave == clave, Configuracion.negocio_id == negocio_id)
        resultado = await session.execute(query)
        config = resultado.scalar_one_or_none()
        return config.valor if config else valor_default


async def guardar_configuracion(clave: str, valor: str, negocio_id: str | None = None):
    async with async_session() as session:
        query = select(Configuracion).where(Configuracion.clave == clave, Configuracion.negocio_id == negocio_id)
        resultado = await session.execute(query)
        config = resultado.scalar_one_or_none()
        if config is None:
            config = Configuracion(clave=clave, negocio_id=negocio_id)
            session.add(config)
        config.valor = valor
        await session.commit()


def _identidad_a_dict(identidad: "IdentidadAgente") -> dict:
    return {
        "id": identidad.id,
        "negocio_id": identidad.negocio_id,
        "codigo": identidad.codigo,
        "nombre": identidad.nombre,
        "tono": identidad.tono,
        "configuracion_negocio": identidad.configuracion_negocio,
        "usa_patron_estructural": identidad.usa_patron_estructural,
        "creado": identidad.creado,
        "actualizado": identidad.actualizado,
    }


async def obtener_identidad_agente(negocio_id: str, codigo: str = "gabi") -> dict | None:
    """Identidad del agente de ESTE Negocio — Gate 4.2. `None` si el
    Negocio todavía no tiene una migrada (mismo criterio fail-safe que el
    resto del sistema: quien llama decide el fallback, nunca se inventa
    acá)."""
    async with async_session() as session:
        query = select(IdentidadAgente).where(
            IdentidadAgente.negocio_id == negocio_id, IdentidadAgente.codigo == codigo,
        )
        identidad = (await session.execute(query)).scalar_one_or_none()
        return _identidad_a_dict(identidad) if identidad else None


async def crear_o_actualizar_identidad_agente(
    negocio_id: str, nombre: str, tono: str, configuracion_negocio: str, codigo: str = "gabi",
) -> dict:
    """Alta o edición de la identidad de un agente — Gate 4.2. Mismo
    criterio idempotente que `guardar_configuracion`: si ya existe una fila
    para (negocio_id, codigo), la actualiza; si no, la crea."""
    async with async_session() as session:
        query = select(IdentidadAgente).where(
            IdentidadAgente.negocio_id == negocio_id, IdentidadAgente.codigo == codigo,
        )
        identidad = (await session.execute(query)).scalar_one_or_none()
        if identidad is None:
            identidad = IdentidadAgente(negocio_id=negocio_id, codigo=codigo)
            session.add(identidad)
        identidad.nombre = nombre
        identidad.tono = tono
        identidad.configuracion_negocio = configuracion_negocio
        identidad.actualizado = datetime.utcnow()
        await session.commit()
        await session.refresh(identidad)
        return _identidad_a_dict(identidad)


async def activar_patron_estructural(negocio_id: str, activo: bool, codigo: str = "gabi") -> dict | None:
    """Prende/apaga el ensamblador (patrón estructural + configuración de
    negocio) para ESTE Negocio — Gate 4.3, activación controlada y
    reversible. Función de una sola responsabilidad, separada de
    `crear_o_actualizar_identidad_agente`, para que activar/revertir sea
    un solo campo tocado, auditable, sin tener que re-enviar
    nombre/tono/configuracion_negocio cada vez. `None` si el Negocio no
    tiene identidad migrada — no se crea una a ciegas."""
    async with async_session() as session:
        query = select(IdentidadAgente).where(
            IdentidadAgente.negocio_id == negocio_id, IdentidadAgente.codigo == codigo,
        )
        identidad = (await session.execute(query)).scalar_one_or_none()
        if identidad is None:
            return None
        identidad.usa_patron_estructural = activo
        identidad.actualizado = datetime.utcnow()
        await session.commit()
        await session.refresh(identidad)
        return _identidad_a_dict(identidad)


def _horario_a_dict(horario: "HorarioAtencion") -> dict:
    return {
        "id": horario.id,
        "negocio_id": horario.negocio_id,
        "dia_semana": horario.dia_semana,
        "habilitado": horario.habilitado,
        "hora_apertura": horario.hora_apertura,
        "hora_cierre": horario.hora_cierre,
    }


async def listar_horarios_atencion(negocio_id: str) -> list[dict]:
    """Los 7 días de la semana de ESTE Negocio (Gate 4.2) — puede devolver
    menos de 7 si el Negocio todavía no fue backfilleado; quien llama
    decide el fallback (mismo criterio que el resto del sistema)."""
    async with async_session() as session:
        query = (
            select(HorarioAtencion)
            .where(HorarioAtencion.negocio_id == negocio_id)
            .order_by(HorarioAtencion.dia_semana.asc())
        )
        resultado = await session.execute(query)
        return [_horario_a_dict(h) for h in resultado.scalars().all()]


async def guardar_horario_atencion(
    negocio_id: str, dia_semana: int, habilitado: bool,
    hora_apertura: str | None, hora_cierre: str | None,
) -> dict:
    """Alta o edición del horario de UN día de UN Negocio — Gate 4.2."""
    async with async_session() as session:
        query = select(HorarioAtencion).where(
            HorarioAtencion.negocio_id == negocio_id, HorarioAtencion.dia_semana == dia_semana,
        )
        horario = (await session.execute(query)).scalar_one_or_none()
        if horario is None:
            horario = HorarioAtencion(negocio_id=negocio_id, dia_semana=dia_semana)
            session.add(horario)
        horario.habilitado = habilitado
        horario.hora_apertura = hora_apertura if habilitado else None
        horario.hora_cierre = hora_cierre if habilitado else None
        await session.commit()
        await session.refresh(horario)
        return _horario_a_dict(horario)


# ── Calendario de negocio: días especiales (2026-10-12, Fase 1) ──────────────────────────────────────────
#
# La lógica de fechas vive en `agent/calendario_negocio.py` (pura). Acá: el modelo `DiaEspecial`, el cargador con
# caché de 60 s, el CRUD con auditoría y la siembra de los feriados nacionales de Perú (`agent/calendario_peru.py`).

CLAVE_CALENDARIO_HABIL_DESDE = "calendario_habil_desde"   # "AAAA-MM-DD" (día de Lima); ausente = métricas hábiles apagadas
ORIGEN_DIA_PRECARGADO_PE = "precargado_pe"
ORIGEN_DIA_MANUAL = "manual"
CALENDARIO_CACHE_SEGUNDOS = 60
DIAS_EDICION_RETROACTIVA = 7          # un día especial pasado solo se puede tocar hasta 7 días atrás, y con motivo
DIAS_AVISO_COBERTURA = 60             # aviso cuando faltan menos de estos días de calendario cargado
# Qué hace cada tipo cuando el admin no dice `atiende`: el feriado nacional y el cierre propio cierran; el día no
# laborable y el puente son VOLUNTARIOS para el sector privado, así que por defecto el negocio sigue atendiendo
# (el admin marca `atiende=false` solo si decide cerrar); la atención especial siempre atiende.
ATIENDE_POR_DEFECTO = {
    cal_negocio.TIPO_FERIADO: False, cal_negocio.TIPO_NO_LABORABLE: True, cal_negocio.TIPO_PUENTE: True,
    cal_negocio.TIPO_ATENCION_ESPECIAL: True, cal_negocio.TIPO_CIERRE_PROPIO: False,
}

# {negocio_id: (instante monotónico en que se leyó, {fecha: DiaEspecial puro})}
_cache_excepciones: dict[str, tuple[float, dict]] = {}


def _reloj_cache_calendario() -> float:
    return time.monotonic()


def invalidar_cache_calendario(negocio_id: str | None = None) -> None:
    """Descarta la caché de excepciones (de un negocio, o de todos). Se llama al guardar para que el cambio rija al
    instante en este proceso; los demás procesos (Cron, otras réplicas) lo ven en como máximo 60 s."""
    if negocio_id is None:
        _cache_excepciones.clear()
    else:
        _cache_excepciones.pop(negocio_id, None)


def hoy_en_lima() -> date:
    return (datetime.utcnow() - timedelta(hours=5)).date()


def _dia_especial_a_dict(d: "DiaEspecial") -> dict:
    return {
        "id": d.id, "negocio_id": d.negocio_id, "fecha": d.fecha, "tipo": d.tipo, "nombre": d.nombre,
        "atiende": bool(d.atiende), "hora_apertura": d.hora_apertura, "hora_cierre": d.hora_cierre,
        "origen": d.origen, "fuente_url": d.fuente_url, "creado": d.creado, "creado_por": d.creado_por,
        "actualizado": d.actualizado, "eliminado_en": d.eliminado_en,
    }


def _resumen_para_auditoria(d: dict) -> dict:
    return {
        "fecha": d["fecha"].isoformat(), "tipo": d["tipo"], "nombre": d["nombre"], "atiende": d["atiende"],
        "hora_apertura": d["hora_apertura"], "hora_cierre": d["hora_cierre"],
    }


async def _excepciones_del_negocio(negocio_id: str, fresco: bool = False) -> dict:
    """{fecha: DiaEspecial puro} de las filas VIVAS del negocio, con caché de 60 s (salvo `fresco=True`, que es lo
    que usan los Cron). Si la tabla no se pudo leer (p. ej. la migración todavía no corrió) devuelve {} y deja un
    aviso en el log: el sistema sigue con el horario semanal de siempre en vez de caerse."""
    ahora = _reloj_cache_calendario()
    if not fresco:
        entrada = _cache_excepciones.get(negocio_id)
        if entrada is not None and ahora - entrada[0] < CALENDARIO_CACHE_SEGUNDOS:
            return entrada[1]
    try:
        async with async_session() as session:
            filas = (await session.execute(
                select(DiaEspecial).where(DiaEspecial.negocio_id == negocio_id, DiaEspecial.eliminado_en.is_(None))
            )).scalars().all()
        excepciones = {
            f.fecha: cal_negocio.DiaEspecial(
                fecha=f.fecha, tipo=f.tipo, nombre=f.nombre, atiende=bool(f.atiende),
                hora_apertura=f.hora_apertura, hora_cierre=f.hora_cierre,
            )
            for f in filas
        }
    except Exception:
        logger.warning("Calendario: no se pudieron leer los días especiales — rige solo el horario semanal", exc_info=True)
        return {}
    _cache_excepciones[negocio_id] = (ahora, excepciones)
    return excepciones


async def obtener_calendario_negocio(negocio_id: str | None, fresco: bool = False) -> "cal_negocio.Calendario":
    """El calendario completo del negocio: horario semanal (`HorarioAtencion`, con el horario de siempre para un día sin
    fila: lunes a sábado 8:00-19:00) más sus días especiales. El horario semanal se lee siempre fresco; los días
    especiales vienen de una caché de 60 s que se invalida al guardar. `fresco=True` salta la caché (Cron).
    `negocio_id=None` → el horario por defecto sin excepciones (comportamiento histórico)."""
    if negocio_id is None:
        return cal_negocio.calendario_desde_filas([])
    filas = await listar_horarios_atencion(negocio_id)
    return cal_negocio.calendario_desde_filas(filas, await _excepciones_del_negocio(negocio_id, fresco))


async def obtener_calendario_habil_desde(negocio_id: str | None) -> date | None:
    """Fecha (día de Lima) desde la que rigen los umbrales HÁBILES de atención atrasada/urgente. None = no fijada:
    los consumidores usan los valores de siempre. Un valor inválido se trata como no fijado."""
    if negocio_id is None:
        return None
    valor = await obtener_configuracion(CLAVE_CALENDARIO_HABIL_DESDE, "", negocio_id=negocio_id)
    try:
        return date.fromisoformat(valor.strip()) if valor and valor.strip() else None
    except ValueError:
        return None


async def fijar_calendario_habil_desde(
    negocio_id: str, fecha: date | None, autor: str | None = None, autor_rol: str | None = None,
) -> dict:
    """Fija (o borra con None) la fecha de vigencia de las métricas hábiles. Deja la fila de auditoría en la misma
    transacción. Devuelve {"antes": "AAAA-MM-DD"|None, "despues": "AAAA-MM-DD"|None}."""
    nuevo = fecha.isoformat() if fecha else ""
    async with async_session() as session:
        existente = (await session.execute(
            select(Configuracion).where(Configuracion.clave == CLAVE_CALENDARIO_HABIL_DESDE, Configuracion.negocio_id == negocio_id)
        )).scalar_one_or_none()
        antes = existente.valor if existente is not None else ""
        if existente is None:
            session.add(Configuracion(clave=CLAVE_CALENDARIO_HABIL_DESDE, negocio_id=negocio_id, valor=nuevo))
        else:
            existente.valor = nuevo
        if antes != nuevo:
            session.add(RegistroAuditoria(
                accion="calendario_habil_desde", actor=autor, negocio_id=negocio_id, entidad_tipo="configuracion",
                payload={"antes": antes or None, "despues": nuevo or None, "actor_rol": autor_rol},
            ))
        await session.commit()
    return {"antes": antes or None, "despues": nuevo or None}


_HHMM = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


def _fecha_dia_especial(valor) -> date:
    if isinstance(valor, datetime):
        raise ValueError("La fecha debe ser un día (AAAA-MM-DD), sin hora.")
    if isinstance(valor, date):
        fecha = valor
    else:
        try:
            fecha = date.fromisoformat(str(valor or "").strip())
        except ValueError:
            raise ValueError("La fecha debe tener el formato AAAA-MM-DD y ser un día válido del calendario.")
    if not 2020 <= fecha.year <= 2100:
        raise ValueError("La fecha debe estar entre los años 2020 y 2100.")
    return fecha


def validar_dia_especial(
    fecha, tipo, nombre, atiende=None, hora_apertura=None, hora_cierre=None,
) -> dict:
    """Valida y normaliza un día especial. Devuelve {fecha, tipo, nombre, atiende, hora_apertura, hora_cierre}; lanza
    ValueError con el motivo en español. `atiende=None` usa el valor por defecto del tipo (ver ATIENDE_POR_DEFECTO)."""
    fecha = _fecha_dia_especial(fecha)
    if tipo not in cal_negocio.TIPOS_DIA_ESPECIAL:
        raise ValueError(f"El tipo debe ser uno de: {', '.join(cal_negocio.TIPOS_DIA_ESPECIAL)}.")
    if not isinstance(nombre, str) or not nombre.strip():
        raise ValueError("El nombre del día es obligatorio (por ejemplo: «Feriado por elecciones»).")
    nombre = " ".join(nombre.split())
    if len(nombre) > 100:
        raise ValueError("El nombre del día no puede pasar de 100 caracteres.")
    if atiende is None:
        atiende = ATIENDE_POR_DEFECTO[tipo]
    if not isinstance(atiende, bool):
        raise ValueError("`atiende` debe ser true o false.")
    apertura = (hora_apertura or "").strip() if isinstance(hora_apertura, str) else hora_apertura
    cierre = (hora_cierre or "").strip() if isinstance(hora_cierre, str) else hora_cierre
    if (apertura or cierre) and not atiende:
        apertura = cierre = None    # un día cerrado no lleva horario: se ignora en vez de rechazar
    if atiende and (apertura or cierre):
        if not apertura or not cierre:
            raise ValueError("Indica la hora de apertura y la de cierre, o ninguna de las dos.")
        for etiqueta, valor in (("La hora de apertura", apertura), ("La hora de cierre", cierre)):
            if not isinstance(valor, str) or not _HHMM.match(valor):
                raise ValueError(f"{etiqueta} debe tener el formato HH:MM (por ejemplo 08:00).")
        if apertura >= cierre:
            raise ValueError("La hora de apertura debe ser anterior a la de cierre.")
    if tipo == cal_negocio.TIPO_ATENCION_ESPECIAL and not (atiende and apertura and cierre):
        raise ValueError("Un día de atención especial necesita su hora de apertura y de cierre.")
    return {
        "fecha": fecha, "tipo": tipo, "nombre": nombre, "atiende": atiende,
        "hora_apertura": apertura or None, "hora_cierre": cierre or None,
    }


def _exigir_edicion_permitida(fecha: date, motivo, hoy: date) -> str | None:
    """Reglas de edición retroactiva: hasta 7 días atrás y con motivo obligatorio (un día pasado cambia cómo se
    midieron las demoras). Hoy y el futuro no piden motivo. Devuelve el motivo limpio (o None)."""
    motivo = " ".join(motivo.split()) if isinstance(motivo, str) else None
    if fecha < hoy:
        if (hoy - fecha).days > DIAS_EDICION_RETROACTIVA:
            raise ValueError(f"No se puede modificar un día de hace más de {DIAS_EDICION_RETROACTIVA} días.")
        if not motivo:
            raise ValueError("Para modificar un día que ya pasó indica el motivo del cambio.")
    if motivo and len(motivo) > 300:
        raise ValueError("El motivo no puede pasar de 300 caracteres.")
    return motivo or None


async def listar_dias_especiales(
    negocio_id: str, desde: date | None = None, hasta: date | None = None, incluir_eliminados: bool = False,
) -> list[dict]:
    """Los días especiales de ESTE negocio entre `desde` y `hasta` (ambos inclusive), por fecha."""
    async with async_session() as session:
        query = select(DiaEspecial).where(DiaEspecial.negocio_id == negocio_id)
        if not incluir_eliminados:
            query = query.where(DiaEspecial.eliminado_en.is_(None))
        if desde is not None:
            query = query.where(DiaEspecial.fecha >= desde)
        if hasta is not None:
            query = query.where(DiaEspecial.fecha <= hasta)
        filas = (await session.execute(query.order_by(DiaEspecial.fecha.asc(), DiaEspecial.creado.asc()))).scalars().all()
        return [_dia_especial_a_dict(f) for f in filas]


async def guardar_dia_especial(
    negocio_id: str, fecha, tipo, nombre, atiende=None, hora_apertura=None, hora_cierre=None,
    autor: str | None = None, motivo: str | None = None, origen: str = ORIGEN_DIA_MANUAL,
    fuente_url: str | None = None, hoy: date | None = None, autor_rol: str | None = None,
) -> dict:
    """Alta o cambio del día especial de UNA fecha del negocio (una fila viva por fecha). Devuelve
    `{"accion": "creado" | "modificado" | "sin_cambios", "dia": {...}}`. Lanza ValueError (400) si algo no es válido.
    Auditoría en la misma transacción: quién, con qué rol (`actor_rol`), cuándo, antes y después, y el motivo."""
    datos = validar_dia_especial(fecha, tipo, nombre, atiende, hora_apertura, hora_cierre)
    hoy = hoy or hoy_en_lima()
    motivo = _exigir_edicion_permitida(datos["fecha"], motivo, hoy)
    try:
        async with async_session() as session:
            actual = (await session.execute(
                select(DiaEspecial).where(
                    DiaEspecial.negocio_id == negocio_id, DiaEspecial.fecha == datos["fecha"], DiaEspecial.eliminado_en.is_(None),
                )
            )).scalar_one_or_none()
            if actual is None:
                fila = DiaEspecial(
                    negocio_id=negocio_id, origen=origen, fuente_url=fuente_url, creado_por=autor, **datos,
                )
                session.add(fila)
                await session.flush()
                session.add(RegistroAuditoria(
                    accion="dia_especial_creado", actor=autor, negocio_id=negocio_id, entidad_tipo="dia_especial",
                    entidad_id=fila.id, payload={
                        "despues": _resumen_para_auditoria(datos), "origen": origen, "motivo": motivo, "actor_rol": autor_rol,
                    },
                ))
                accion = "creado"
            else:
                antes = _resumen_para_auditoria(_dia_especial_a_dict(actual))
                despues = _resumen_para_auditoria(datos)
                if antes == despues:
                    return {"accion": "sin_cambios", "dia": _dia_especial_a_dict(actual)}
                for campo in ("tipo", "nombre", "atiende", "hora_apertura", "hora_cierre"):
                    setattr(actual, campo, datos[campo])
                actual.actualizado = datetime.utcnow()
                fila = actual
                session.add(RegistroAuditoria(
                    accion="dia_especial_modificado", actor=autor, negocio_id=negocio_id, entidad_tipo="dia_especial",
                    entidad_id=actual.id, payload={"antes": antes, "despues": despues, "motivo": motivo, "actor_rol": autor_rol},
                ))
                accion = "modificado"
            await session.commit()
            await session.refresh(fila)
            resultado = _dia_especial_a_dict(fila)
    except IntegrityError:
        raise ValueError("Ya existe un día especial en esa fecha. Recarga la lista e inténtalo de nuevo.")
    invalidar_cache_calendario(negocio_id)
    return {"accion": accion, "dia": resultado}


async def eliminar_dia_especial(
    negocio_id: str, fecha, autor: str | None = None, motivo: str | None = None, hoy: date | None = None,
    autor_rol: str | None = None,
) -> dict | None:
    """Quita (borrado lógico) el día especial de esa fecha. None si no hay ninguno vivo. Mismas reglas de edición
    retroactiva que `guardar_dia_especial`. Queda en la auditoría."""
    fecha = _fecha_dia_especial(fecha)
    hoy = hoy or hoy_en_lima()
    motivo = _exigir_edicion_permitida(fecha, motivo, hoy)
    async with async_session() as session:
        fila = (await session.execute(
            select(DiaEspecial).where(
                DiaEspecial.negocio_id == negocio_id, DiaEspecial.fecha == fecha, DiaEspecial.eliminado_en.is_(None),
            )
        )).scalar_one_or_none()
        if fila is None:
            return None
        antes = _resumen_para_auditoria(_dia_especial_a_dict(fila))
        fila.eliminado_en = datetime.utcnow()
        fila.eliminado_por = autor
        session.add(RegistroAuditoria(
            accion="dia_especial_eliminado", actor=autor, negocio_id=negocio_id, entidad_tipo="dia_especial",
            entidad_id=fila.id, payload={"antes": antes, "motivo": motivo, "actor_rol": autor_rol},
        ))
        await session.commit()
        resultado = _dia_especial_a_dict(fila)
    invalidar_cache_calendario(negocio_id)
    return resultado


async def marcar_manana_no_laborable(
    negocio_id: str, autor: str | None = None, nombre: str | None = None, hoy: date | None = None,
    autor_rol: str | None = None,
) -> dict:
    """Atajo del panel: mañana (día de Lima) queda CERRADO como día no laborable y rige en como máximo 60 s en cada
    proceso (en este, al instante). Si mañana ya tenía un día especial (p. ej. un feriado con horario especial) se
    conservan su tipo y su nombre y solo pasa a no atender; si ya estaba cerrado → `sin_cambios`."""
    hoy = hoy or hoy_en_lima()
    manana = hoy + timedelta(days=1)
    existente = next(iter(await listar_dias_especiales(negocio_id, manana, manana)), None)
    if existente is not None:
        return await guardar_dia_especial(
            negocio_id, manana, existente["tipo"], existente["nombre"], False, None, None, autor=autor, hoy=hoy,
            autor_rol=autor_rol,
        )
    return await guardar_dia_especial(
        negocio_id, manana, cal_negocio.TIPO_NO_LABORABLE, (nombre or "").strip() or "Día no laborable", False, None, None,
        autor=autor, hoy=hoy, autor_rol=autor_rol,
    )


async def sembrar_calendario(
    negocio_id: str, anio: int, autor: str | None = None, restaurar_eliminados: bool = False, simular: bool = False,
    autor_rol: str | None = None,
) -> dict:
    """Siembra los feriados nacionales de Perú de `anio` (ver `agent/calendario_peru.py`) para UN negocio. IDEMPOTENTE:
    una fecha que ya tiene un día especial vivo no se toca, y una fecha cuyo feriado el administrador quitó antes NO
    se vuelve a crear salvo `restaurar_eliminados=True` (la acción explícita «Cargar feriados» del panel). Solo
    feriados (atiende=False): nunca inserta días no laborables ni puentes. `simular=True` no escribe nada.

    Devuelve `{"anio", "verificado", "nota", "insertados": [fechas], "ya_existian": [fechas], "omitidos_por_eliminados":
    [fechas]}` (fechas como `date`)."""
    from agent import calendario_peru
    feriados = calendario_peru.feriados_de(anio)     # ValueError si el año no está disponible
    async with async_session() as session:
        filas = (await session.execute(
            select(DiaEspecial).where(
                DiaEspecial.negocio_id == negocio_id, DiaEspecial.fecha >= date(anio, 1, 1), DiaEspecial.fecha <= date(anio, 12, 31),
            )
        )).scalars().all()
        vivas = {f.fecha for f in filas if f.eliminado_en is None}
        eliminadas = {f.fecha for f in filas if f.eliminado_en is not None}
        insertados: list[date] = []
        ya_existian: list[date] = []
        omitidos: list[date] = []
        for f in feriados:
            if f["fecha"] in vivas:
                ya_existian.append(f["fecha"])
            elif f["fecha"] in eliminadas and not restaurar_eliminados:
                omitidos.append(f["fecha"])
            else:
                insertados.append(f["fecha"])
                if not simular:
                    session.add(DiaEspecial(
                        negocio_id=negocio_id, fecha=f["fecha"], tipo=cal_negocio.TIPO_FERIADO, nombre=f["nombre"],
                        atiende=False, origen=ORIGEN_DIA_PRECARGADO_PE, fuente_url=f["fuente_url"], creado_por=autor,
                    ))
        if insertados and not simular:
            session.add(RegistroAuditoria(
                accion="calendario_feriados_cargados", actor=autor, negocio_id=negocio_id, entidad_tipo="dia_especial",
                payload={
                    "anio": anio, "insertados": [d.isoformat() for d in insertados],
                    "verificado": calendario_peru.VERIFICADO_POR_ANIO.get(anio, False), "restaurar_eliminados": restaurar_eliminados,
                    "actor_rol": autor_rol,
                },
            ))
        if not simular:
            await session.commit()
    if insertados and not simular:
        invalidar_cache_calendario(negocio_id)
    return {
        "anio": anio, "verificado": calendario_peru.VERIFICADO_POR_ANIO.get(anio, False),
        "nota": calendario_peru.nota_del_anio(anio), "insertados": insertados, "ya_existian": ya_existian,
        "omitidos_por_eliminados": omitidos,
    }


async def resumen_cobertura_calendario(negocio_id: str, hoy: date | None = None) -> dict:
    """Cuánto calendario hay cargado: la última fecha de FERIADO cargada y los días que faltan hasta ella. `aviso` es
    True si no hay ningún feriado o faltan menos de 60 días. `{"ultima_fecha_cargada": date|None, "dias_restantes":
    int|None, "aviso": bool, "mensaje": str|None}`."""
    hoy = hoy or hoy_en_lima()
    async with async_session() as session:
        ultima = (await session.execute(
            select(func.max(DiaEspecial.fecha)).where(
                DiaEspecial.negocio_id == negocio_id, DiaEspecial.eliminado_en.is_(None), DiaEspecial.tipo == cal_negocio.TIPO_FERIADO,
            )
        )).scalar_one_or_none()
    if ultima is None:
        return {
            "ultima_fecha_cargada": None, "dias_restantes": None, "aviso": True,
            "mensaje": "No hay feriados cargados: el sistema atenderá todos los días hábiles de la semana, incluso en feriados.",
        }
    restantes = (ultima - hoy).days
    aviso = restantes < DIAS_AVISO_COBERTURA
    return {
        "ultima_fecha_cargada": ultima, "dias_restantes": restantes, "aviso": aviso,
        "mensaje": (
            f"El calendario cargado llega hasta el {ultima.day} de {cal_negocio.MESES_ES[ultima.month - 1]} de {ultima.year} "
            f"({max(restantes, 0)} días): carga los feriados del año siguiente."
        ) if aviso else None,
    }


# ── Calendario: historial legible, límite de frecuencia y aviso al admin (2026-10-12, permisos del supervisor) ──
#
# Todo sale de `RegistroAuditoria` (ya existente, append-only): no hay tabla nueva ni migración. Contratos en
# docs/contrato_calendario_supervisor.md.

ACCIONES_CALENDARIO_DIA = ("dia_especial_creado", "dia_especial_modificado", "dia_especial_eliminado")
ACCION_CALENDARIO_FERIADOS = "calendario_feriados_cargados"
ACCION_CALENDARIO_HABIL_DESDE = "calendario_habil_desde"
CLAVE_CALENDARIO_MAX_ESCRITURAS_HORA = "calendario_max_escrituras_hora"                 # tope por usuario y hora (no-admin)
CLAVE_CALENDARIO_MAX_ESCRITURAS_HORA_ADMIN = "calendario_max_escrituras_hora_admin"     # tope por usuario y hora (admin)
CALENDARIO_MAX_ESCRITURAS_HORA_POR_DEFECTO = 20
CALENDARIO_MAX_ESCRITURAS_HORA_ADMIN_POR_DEFECTO = 100
LIMITE_HISTORIAL_CALENDARIO = 100
MAX_HISTORIAL_CALENDARIO = 200


def _filtro_auditoria_calendario():
    """Filas de auditoría que forman el historial del calendario: los días especiales y la fecha de vigencia de la
    medición hábil (esta última se guarda como `entidad_tipo="configuracion"`)."""
    return sa_or(
        RegistroAuditoria.entidad_tipo == "dia_especial",
        sa_and(RegistroAuditoria.entidad_tipo == "configuracion", RegistroAuditoria.accion == ACCION_CALENDARIO_HABIL_DESDE),
    )


def _item_historial_calendario(f: "RegistroAuditoria") -> dict:
    """Una fila de auditoría del calendario en el contrato legible (`antes`/`despues` como objeto, el motivo aparte)."""
    p = f.payload or {}
    antes, despues = p.get("antes"), p.get("despues")
    if f.accion == ACCION_CALENDARIO_FERIADOS:
        antes = None
        despues = {"anio": p.get("anio"), "insertados": list(p.get("insertados") or []), "verificado": p.get("verificado")}
    fecha_dia = None
    if f.accion in ACCIONES_CALENDARIO_DIA:
        referencia = despues if isinstance(despues, dict) else antes
        fecha_dia = referencia.get("fecha") if isinstance(referencia, dict) else None
    return {
        "creado": f.creado, "actor": f.actor, "actor_rol": p.get("actor_rol"), "accion": f.accion, "fecha_dia": fecha_dia,
        "antes": antes, "despues": despues, "motivo": p.get("motivo"),
    }


async def listar_historial_calendario(
    negocio_id: str, limite: int = LIMITE_HISTORIAL_CALENDARIO, antes_de: datetime | None = None,
) -> dict:
    """Historial de cambios del calendario de ESTE negocio, más reciente primero: `{"items": [...], "hay_mas": bool}`.
    `antes_de` (UTC) pagina: solo filas anteriores a ese instante. `limite` se acota a 1..200."""
    limite = max(1, min(int(limite), MAX_HISTORIAL_CALENDARIO))
    async with async_session() as session:
        consulta = select(RegistroAuditoria).where(RegistroAuditoria.negocio_id == negocio_id, _filtro_auditoria_calendario())
        if antes_de is not None:
            consulta = consulta.where(RegistroAuditoria.creado < antes_de)
        filas = (await session.execute(consulta.order_by(RegistroAuditoria.creado.desc()).limit(limite + 1))).scalars().all()
    return {"items": [_item_historial_calendario(f) for f in filas[:limite]], "hay_mas": len(filas) > limite}


def _texto_json_auditoria(valor) -> str | None:
    """Valor de auditoría como texto: un objeto va como JSON, una cadena tal cual (la fecha de `calendario_habil_desde`)."""
    import json as _json
    if valor is None:
        return None
    return valor if isinstance(valor, str) else _json.dumps(valor, ensure_ascii=False, sort_keys=True)


def _cambios_de_auditoria_calendario(f: "RegistroAuditoria") -> dict:
    """Forma de `cambios` que ya consume el historial de Configuración: `{accion: {antes, despues}}` con textos JSON y
    el motivo DENTRO del JSON del día (así lo lee `describirCambioCalendario` del frontend)."""
    item = _item_historial_calendario(f)
    antes, despues, motivo = item["antes"], item["despues"], item["motivo"]
    if f.accion in ("dia_especial_creado", "dia_especial_modificado") and isinstance(despues, dict):
        despues = {**despues, "motivo": motivo}
    elif f.accion == "dia_especial_eliminado" and isinstance(antes, dict):
        antes = {**antes, "motivo": motivo}
    return {f.accion: {"antes": _texto_json_auditoria(antes), "despues": _texto_json_auditoria(despues)}}


async def contar_escrituras_calendario(negocio_id: str, actor: str | None, ahora: datetime | None = None) -> dict:
    """Cuántas escrituras EFECTIVAS al calendario hizo `actor` en este negocio en la última hora (una por fila de
    auditoría de días especiales: alta, cambio, baja o carga de feriados; un `sin_cambios` o un rechazo no escribe y no
    cuenta). Se lee de la base —no de memoria del proceso—, así que el límite vale igual con varias réplicas.
    `{"cantidad": int, "libera_en": datetime|None}` (`libera_en`: cuándo sale de la ventana la escritura más antigua)."""
    ahora = ahora or datetime.utcnow()
    desde = ahora - timedelta(hours=1)
    async with async_session() as session:
        creados = (await session.execute(
            select(RegistroAuditoria.creado).where(
                RegistroAuditoria.negocio_id == negocio_id, RegistroAuditoria.entidad_tipo == "dia_especial",
                RegistroAuditoria.actor == actor, RegistroAuditoria.creado >= desde,
            ).order_by(RegistroAuditoria.creado.asc())
        )).scalars().all()
    return {"cantidad": len(creados), "libera_en": (creados[0] + timedelta(hours=1)) if creados else None}


async def resumen_cambios_calendario_de_supervisores(negocio_id: str, desde: datetime) -> dict:
    """Cambios al calendario hechos por usuarios con rol `supervisor` desde `desde` (UTC), para el aviso del admin.
    El rol es el que quedó en la auditoría al momento del cambio (`actor_rol`), no el de hoy. `{"total": int,
    "supervisores": [usernames, el que más cambió primero], "ultimo": datetime|None}`."""
    async with async_session() as session:
        filas = (await session.execute(
            select(RegistroAuditoria).where(
                RegistroAuditoria.negocio_id == negocio_id, RegistroAuditoria.entidad_tipo == "dia_especial",
                RegistroAuditoria.creado >= desde,
            ).order_by(RegistroAuditoria.creado.desc())
        )).scalars().all()
    de_supervisores = [f for f in filas if (f.payload or {}).get("actor_rol") == "supervisor"]
    cuentas: dict[str, int] = {}
    for f in de_supervisores:
        cuentas[f.actor or "?"] = cuentas.get(f.actor or "?", 0) + 1
    return {
        "total": len(de_supervisores),
        "supervisores": [u for u, _ in sorted(cuentas.items(), key=lambda par: (-par[1], par[0]))],
        "ultimo": de_supervisores[0].creado if de_supervisores else None,
    }


async def marcar_mensaje_procesado(mensaje_id: str) -> bool:
    """Idempotencia general del webhook (API Architecture) — intenta
    registrar mensaje_id como ya procesado. Usa la restricción de clave
    primaria de la base como mecanismo de exclusión mutua (seguro ante
    entregas concurrentes duplicadas, no solo un "check-then-insert" con
    ventana de carrera).

    Retorna True si mensaje_id YA estaba registrado (no procesar de
    nuevo), False si es la primera vez que se ve (procesar normal)."""
    async with async_session() as session:
        try:
            session.add(MensajeProcesado(mensaje_id=mensaje_id))
            await session.commit()
            return False
        except IntegrityError:
            await session.rollback()
            return True


async def liberar_marca_mensaje_procesado(mensaje_id: str) -> bool:
    """Borra la marca de idempotencia de `mensaje_id` (2026-10-05, mensajes
    perdidos): el webhook la usa cuando el procesamiento de un mensaje falló
    ANTES de guardarlo, para que el reintento de Meta sí lo procese en vez de
    descartarlo como "ya procesado". Retorna True si había una marca y se
    borró. Idempotente: sin marca no hace nada."""
    async with async_session() as session:
        resultado = await session.execute(delete(MensajeProcesado).where(MensajeProcesado.mensaje_id == mensaje_id))
        await session.commit()
        return (resultado.rowcount or 0) > 0


async def existe_mensaje_con_id_meta(negocio_id: str, mensaje_id_meta: str) -> bool:
    """¿Ya hay un Mensaje guardado con este wamid en este Negocio? — el
    candado contra duplicados del webhook (no hay índice único sobre
    `mensaje_id_meta`, a propósito: el historial anterior no lo tiene y no se
    migra). Filtra por `negocio_id` (el mismo wamid nunca debería repetirse
    entre Negocios, pero el aislamiento no se negocia)."""
    if not negocio_id or not mensaje_id_meta:
        return False
    async with async_session() as session:
        fila = await session.execute(
            select(Mensaje.id).where(
                Mensaje.negocio_id == negocio_id, Mensaje.mensaje_id_meta == mensaje_id_meta,
            ).limit(1)
        )
        return fila.first() is not None


# Tipo del evento que deja cada reintento del barrido de mensajes sin
# respuesta (scripts/recuperar_mensajes_sin_respuesta.py) — 20 caracteres,
# cabe de sobra en eventos_lead.tipo (TIPO_EVENTO_LARGO_MAX).
TIPO_EVENTO_RESPUESTA_RECUPERADA = "respuesta_recuperada"

# Resultados con los que el barrido NUNCA toca un lead: los cerrados de
# siempre más "agendado" y "postventa", que no son "cerrados" para el resto del
# sistema pero sí están en manos de una persona (regla crítica: nunca se
# modifica un lead vendido/agendado/postventa desde un proceso automático).
RESULTADOS_QUE_EL_BARRIDO_NO_TOCA = RESULTADOS_CERRADOS + ("agendado", "postventa")

_PLACEHOLDER_ADJUNTO = re.compile(r"^\[[a-z_]+\]$")


# ── Falla transitoria de la IA con el cliente que no vuelve (2026-10-06) ─────────────────────────
# Caso real (Sandra, 04/10): Claude falló UNA vez (5xx/429/timeout) en el primer turno; el webhook
# guardó como respuesta de Gabi el texto técnico de `error_message` ("Uy, estoy teniendo un problema
# técnico…") y, como el cliente no volvió a escribir, el contador `fallos_tecnicos` nunca llegó a 2:
# nadie lo derivó, el Cron de inactividad le mandó "¡Hola de nuevo!" y a las 15 h lo cerró como
# `sin_respuesta`, y el barrido de mensajes sin respuesta no lo veía porque ese texto contaba como
# "respuesta de Gabi".
#
# Cómo se reconoce ese texto — decisión de diseño (sin migración):
#   · NO se reutiliza `Mensaje.estado_envio`: significa "cómo salió el ENVÍO" (None/incierto/fallido) y
#     el panel lo usa para ofrecer el reintento; mezclarle "es un error de IA" lo rompería.
#   · NO se agrega una columna/evento marcador: no cubriría el historial ya guardado (justo los casos
#     reales que hay que rescatar) y el evento ensuciaría el Timeline que ven los asesores.
#   · Se reconoce el TEXTO, normalizado (sin tildes, mayúsculas, emojis ni puntuación): el que está hoy en
#     config/prompts.yaml (`error_message`), los dos que ya existieron (variantes por defecto) y,
#     como red, cualquier texto corto que diga a la vez "problema(s) técnico(s)" e "intenta de nuevo"
#     —tolera que alguien retoque la redacción del YAML—. Un mensaje real de Gabi o de un asesor
#     nunca cumple las dos cosas con menos de 200 caracteres.
_TEXTOS_ERROR_TECNICO_HISTORICOS = (
    "Uy, estoy teniendo un problema técnico. Por favor intenta de nuevo en unos minutos 🙏",
    "Lo siento, estoy teniendo problemas técnicos. Por favor intenta de nuevo en unos minutos.",
)
_LARGO_MAXIMO_TEXTO_ERROR_TECNICO = 200
# Texto del reenganche automático de scripts/procesar_inactividad_clientes.py (MENSAJE_REENGANCHE).
_FRAGMENTOS_REENGANCHE_AUTOMATICO = ("hola de nuevo", "sigo por aqui")
_PREFIJO_REACCION = "Reaccionó con"


def _normalizar_para_comparar(texto: str | None) -> str:
    t = unicodedata.normalize("NFKD", (texto or "").lower())
    t = "".join(c for c in t if not unicodedata.combining(c))
    return " ".join(re.sub(r"[^a-z0-9]+", " ", t).split())


def textos_de_error_tecnico_conocidos() -> frozenset[str]:
    """Los textos de error técnico que Gabi guarda como respuesta cuando Claude falla, ya normalizados:
    los históricos más el que esté configurado AHORA en prompts.yaml (`error_message`). Léelo una vez por
    consulta y pásalo a `es_texto_de_error_tecnico` (leer el YAML por cada mensaje sería un desperdicio)."""
    textos = list(_TEXTOS_ERROR_TECNICO_HISTORICOS)
    try:
        from agent import brain  # import tardío: brain importa memory
        textos.append(brain.obtener_mensaje_error())
    except Exception:  # noqa: BLE001 — sin el YAML igual sirven los históricos y la heurística
        pass
    return frozenset(n for n in (_normalizar_para_comparar(t) for t in textos) if n)


def es_texto_de_error_tecnico(texto: str | None, conocidos: frozenset[str] | None = None) -> bool:
    """¿Este texto es el aviso técnico automático de Gabi (y no una respuesta real)? Ver el comentario
    de arriba. `conocidos` = `textos_de_error_tecnico_conocidos()` (se calcula si no se pasa)."""
    normalizado = _normalizar_para_comparar(texto)
    if not normalizado or len(normalizado) > _LARGO_MAXIMO_TEXTO_ERROR_TECNICO:
        return False
    if normalizado in (conocidos if conocidos is not None else textos_de_error_tecnico_conocidos()):
        return True
    return ("problema tecnico" in normalizado or "problemas tecnicos" in normalizado) and "intenta de nuevo" in normalizado


def es_texto_de_reenganche_automatico(texto: str | None) -> bool:
    """¿Es el mensaje "¡Hola de nuevo! Sigo por aquí…" que manda el Cron de inactividad?"""
    normalizado = _normalizar_para_comparar(texto)
    return bool(normalizado) and all(f in normalizado for f in _FRAGMENTOS_REENGANCHE_AUTOMATICO)


def _recorrer_cola_de_mensajes(recientes: list, conocidos: frozenset[str]) -> tuple["Mensaje | None", list]:
    """`recientes`: mensajes del más nuevo al más antiguo. Salta las reacciones, los textos de error
    técnico y el reenganche automático (ninguno es una respuesta real) y devuelve (el primer mensaje REAL,
    los textos de error saltados). Un mensaje real es del cliente, o de Gabi/un asesor con contenido de
    verdad (incluido el aviso del modo sin IA, que ya derivó el caso a una persona)."""
    errores: list = []
    for m in recientes:
        if m.role == "user" and (m.content or "").startswith(_PREFIJO_REACCION):
            continue
        if m.role == "assistant":
            if es_texto_de_error_tecnico(m.content, conocidos):
                errores.append(m)
                continue
            if es_texto_de_reenganche_automatico(m.content):
                continue
        return m, errores
    return None, errores


async def listar_leads_afectados_por_falla_ia(
    dias: float = 14, negocio_id: str | None = None, solo_ventana_abierta: bool = False, limite: int = 500,
) -> list[dict]:
    """DIAGNÓSTICO de solo lectura (2026-10-06): leads de los últimos `dias` días cuyo último intercambio
    REAL fue «el cliente escribió → Gabi contestó solo el texto de error técnico» y a quienes nadie
    respondió después (ningún asesor ni Gabi escribió algo real; el reenganche automático y las reacciones
    no cuentan). Es el rastro que dejó la falla transitoria única con el cliente que no volvió.

    No modifica nada. Cada fila: telefono, nombre, interes, resultado, negocio_id, numero_whatsapp_id,
    asesor_asignado, pausado_manual, escalado_supervision_en, ya_derivado (con asesor, pausado o en la
    cola de supervisión), ultimo_mensaje_cliente (extracto), ultimo_mensaje_cliente_en (UTC, ISO),
    ultimo_mensaje_cliente_lima (hora de Lima, `AAAA-MM-DD HH:MM`), error_en (UTC, ISO),
    ventana_24h_abierta, ventana_cierra_en_lima (None si ya cerró) y horas_desde_mensaje.
    Primero los de ventana abierta (todavía se les puede escribir libre), luego del más reciente al más
    antiguo. `solo_ventana_abierta=True` deja solo los primeros."""
    ahora = datetime.utcnow()
    corte = ahora - timedelta(days=dias)
    conocidos = textos_de_error_tecnico_conocidos()
    lima = timedelta(hours=-5)  # Perú no observa horario de verano: UTC-5 fijo
    filas: list[dict] = []

    async with async_session() as session:
        query = select(Mensaje.telefono, Mensaje.negocio_id, Mensaje.content).where(
            Mensaje.role == "assistant", Mensaje.timestamp >= corte,
            func.length(Mensaje.content) <= _LARGO_MAXIMO_TEXTO_ERROR_TECNICO * 2,
        )
        if negocio_id is not None:
            query = query.where(Mensaje.negocio_id == negocio_id)
        pares = {
            (neg, tel) for tel, neg, contenido in (await session.execute(query)).all()
            if es_texto_de_error_tecnico(contenido, conocidos)
        }

        for neg, telefono in sorted(pares):
            lead = await session.get(Lead, telefono)
            if lead is None or lead.negocio_id != neg:
                continue
            recientes = (await session.execute(
                select(Mensaje).where(Mensaje.telefono == telefono, Mensaje.negocio_id == neg)
                .order_by(Mensaje.timestamp.desc(), Mensaje.id.desc()).limit(25)
            )).scalars().all()
            ultimo, errores = _recorrer_cola_de_mensajes(recientes, conocidos)
            if ultimo is None or ultimo.role != "user" or not errores:
                continue
            texto_cliente = (ultimo.content or "")[:120]
            edad = ahora - ultimo.timestamp
            ventana_abierta = edad <= timedelta(hours=24)
            filas.append({
                "telefono": telefono, "nombre": lead.nombre, "interes": lead.interes, "resultado": lead.resultado,
                "negocio_id": neg, "numero_whatsapp_id": lead.numero_whatsapp_id,
                "asesor_asignado": lead.asesor_asignado, "pausado_manual": bool(lead.pausado_manual),
                "escalado_supervision_en": lead.escalado_supervision_en.isoformat() if lead.escalado_supervision_en else None,
                "ya_derivado": bool(lead.asesor_asignado or lead.pausado_manual or lead.escalado_supervision_en),
                "ultimo_mensaje_cliente": texto_cliente,
                "ultimo_mensaje_cliente_en": ultimo.timestamp.isoformat(),
                "ultimo_mensaje_cliente_lima": (ultimo.timestamp + lima).strftime("%Y-%m-%d %H:%M"),
                "error_en": errores[-1].timestamp.isoformat(),
                "ventana_24h_abierta": ventana_abierta,
                "ventana_cierra_en_lima": (ultimo.timestamp + timedelta(hours=24) + lima).strftime("%Y-%m-%d %H:%M") if ventana_abierta else None,
                "horas_desde_mensaje": round(edad.total_seconds() / 3600, 1),
            })

    if solo_ventana_abierta:
        filas = [f for f in filas if f["ventana_24h_abierta"]]
    filas.sort(key=lambda f: (not f["ventana_24h_abierta"], -datetime.fromisoformat(f["ultimo_mensaje_cliente_en"]).timestamp()))
    return filas[:limite]


async def listar_mensajes_sin_respuesta_de_gabi(
    negocio_id: str | None = None, min_minutos: float = 3, max_horas: float = 20, limite: int = 50,
    max_intentos: int | None = None,
) -> list[dict]:
    """Barrido de recuperación (2026-10-05, mensajes perdidos): leads que Gabi
    atiende SOLA —sin asesor, sin pausar, sin escalar a supervisión, sin
    cierre y con la conversación activa— cuyo ÚLTIMO mensaje real es del
    cliente (`role == "user"`) y lleva entre `min_minutos` y `max_horas` sin
    respuesta. Es lo que queda cuando la respuesta de Gabi se pierde después
    de guardar el mensaje (la tarea de debounce vive en memoria: un redeploy,
    un reinicio o una excepción la borran sin dejar rastro).

    Criterios, en orden:
      · Lead sin `asesor_asignado`, `pausado_manual` falso,
        `escalado_supervision_en` y `cerrado_definitivamente_en` vacíos, y
        `resultado` vacío o fuera de RESULTADOS_QUE_EL_BARRIDO_NO_TOCA (incluye
        vendido/agendado/postventa). Lo mismo se exige a la Conversation activa
        y a su Opportunity vigente (las dos fuentes, por si una quedó atrasada).
      · Las reacciones ("Reaccionó con …") se IGNORAN al buscar el último
        mensaje: nadie espera respuesta a un 👍, ni un 👍 tapa un mensaje real
        sin contestar.
      · Si el último mensaje real del cliente es un adjunto (`archivo_id`) o un
        placeholder "[audio]", "[image]"…, no se recupera: ese camino nunca
        pasa por Claude (se avisa al cliente que no se lee y que escriba), no
        hay una respuesta de IA que reconstruir.
      · `min_minutos` deja pasar a los mensajes recientes (el debounce normal,
        3 s, todavía puede estar trabajando); `max_horas` deja fuera a los muy
        viejos (contestarlos tarde confunde más de lo que ayuda; además de las
        20 h la ventana de servicio de 24 h de Meta ya está por cerrarse).
      · `max_intentos` (None = sin tope): excluye el mensaje que ya acumuló
        tantos eventos `respuesta_recuperada`.

    Falla transitoria de la IA (2026-10-06): el texto de error técnico de Gabi
    ("Uy, estoy teniendo un problema técnico…") y el reenganche automático que
    pudo seguirlo NO cuentan como respuesta: un mensaje del cliente seguido solo
    de eso se trata como sin respuesta (`tras_falla_ia` = True). Ver
    `es_texto_de_error_tecnico`.

    Cada fila: {telefono, negocio_id, numero_whatsapp_id, conversation_id,
    mensaje_id (Mensaje.id INTERNO del mensaje del cliente — es lo que lleva el
    payload de los eventos), mensaje_id_meta, ultimo_mensaje_en, intentos,
    tras_falla_ia}.
    Del más antiguo al más reciente; `limite` se aplica DESPUÉS de filtrar."""
    ahora = datetime.utcnow()
    corte_reciente = ahora - timedelta(minutes=min_minutos)
    corte_viejo = ahora - timedelta(hours=max_horas)
    filas: list[dict] = []
    conocidos_error = textos_de_error_tecnico_conocidos()

    async with async_session() as session:
        hay_mensaje_del_cliente_en_ventana = sa_exists().where(
            Mensaje.telefono == Lead.telefono, Mensaje.negocio_id == Lead.negocio_id,
            Mensaje.role == "user", Mensaje.timestamp >= corte_viejo, Mensaje.timestamp <= corte_reciente,
        )
        query = select(Lead).where(
            Lead.asesor_asignado.is_(None),
            Lead.pausado_manual.is_(False),
            Lead.escalado_supervision_en.is_(None),
            Lead.cerrado_definitivamente_en.is_(None),
            sa_or(Lead.resultado.is_(None), Lead.resultado.notin_(RESULTADOS_QUE_EL_BARRIDO_NO_TOCA)),
            hay_mensaje_del_cliente_en_ventana,
        )
        if negocio_id is not None:
            query = query.where(Lead.negocio_id == negocio_id)
        leads = (await session.execute(query)).scalars().all()

        for lead in leads:
            contact = await _obtener_contact(session, lead.negocio_id, lead.telefono)
            conversation = await _obtener_conversation_activa(session, contact.id) if contact else None
            if (
                conversation is None or conversation.asesor_asignado_id is not None
                or conversation.pausado_manual or conversation.cerrado_definitivamente_en is not None
            ):
                continue
            opportunity = await _obtener_opportunity_vigente(session, conversation.id)
            if opportunity is not None and opportunity.resultado in RESULTADOS_QUE_EL_BARRIDO_NO_TOCA:
                continue

            recientes = (await session.execute(
                select(Mensaje)
                .where(Mensaje.telefono == lead.telefono, Mensaje.negocio_id == lead.negocio_id)
                .order_by(Mensaje.timestamp.desc(), Mensaje.id.desc())
                .limit(15)
            )).scalars().all()
            ultimo = next(
                (m for m in recientes if not (m.role == "user" and (m.content or "").startswith(_PREFIJO_REACCION))),
                None,
            )
            if ultimo is None:
                continue
            tras_falla_ia = False
            if ultimo.role != "user":
                # Falla transitoria de la IA (2026-10-06): si lo único que sigue al último mensaje real del
                # cliente es el texto de error técnico (y/o el reenganche automático que lo siguió), Gabi
                # NUNCA le respondió de verdad — cuenta como sin respuesta, igual que un mensaje perdido.
                real, errores = _recorrer_cola_de_mensajes(recientes, conocidos_error)
                if real is None or real.role != "user" or not errores:
                    continue
                ultimo, tras_falla_ia = real, True
            if ultimo.archivo_id is not None or _PLACEHOLDER_ADJUNTO.match((ultimo.content or "").strip()):
                continue
            if not (corte_viejo <= ultimo.timestamp <= corte_reciente):
                continue

            eventos = (await session.execute(
                select(EventoLead.payload).where(
                    EventoLead.conversation_id == conversation.id, EventoLead.negocio_id == lead.negocio_id,
                    EventoLead.tipo == TIPO_EVENTO_RESPUESTA_RECUPERADA,
                )
            )).scalars().all()
            intentos = sum(1 for p in eventos if isinstance(p, dict) and p.get("mensaje_id") == ultimo.id)
            if max_intentos is not None and intentos >= max_intentos:
                continue

            filas.append({
                "telefono": lead.telefono, "negocio_id": lead.negocio_id,
                "numero_whatsapp_id": lead.numero_whatsapp_id, "conversation_id": conversation.id,
                "mensaje_id": ultimo.id, "mensaje_id_meta": ultimo.mensaje_id_meta,
                "ultimo_mensaje_en": ultimo.timestamp, "intentos": intentos, "tras_falla_ia": tras_falla_ia,
            })

    filas.sort(key=lambda f: f["ultimo_mensaje_en"])
    return filas[:limite]


_RANGO_ESTADO_MENSAJE = {"sent": 1, "delivered": 2, "read": 3}
_CAMPO_MOMENTO_POR_ESTADO = {
    "sent": "enviado_en", "delivered": "entregado_en", "read": "leido_en", "failed": "fallido_en",
}


async def registrar_estado_mensaje_meta(evento: dict) -> bool:
    """Registra (idempotente) un estado de entrega de Meta en `uso_mensajes_meta`.

    `evento` = lo que devuelve `ProveedorMeta.parsear_estados` (más
    `negocio_id` si se pudo resolver el canal). Meta reenvía estados y los
    manda fuera de orden, así que: la fila se crea o actualiza por `wamid`;
    el estado nunca retrocede (read > delivered > sent; failed solo si nunca
    se entregó); cada momento conserva el PRIMER valor visto; el `pricing` se
    guarda cuando aparece (viene en `sent` y en `delivered`/`read`) sin
    pisarlo con un estado que no lo trae. Dos webhooks simultáneos para el
    mismo wamid se resuelven con la clave primaria (se reintenta como
    actualización). Devuelve False solo si el evento es inválido."""
    wamid, estado, phone_number_id = evento.get("wamid"), evento.get("estado"), evento.get("phone_number_id")
    if not wamid or not phone_number_id or estado not in _CAMPO_MOMENTO_POR_ESTADO:
        return False
    momento = evento.get("momento") or datetime.utcnow()
    pricing = evento.get("pricing") or {}
    error = evento.get("error") or {}

    async with async_session() as session:
        for _ in range(2):
            fila = await session.get(UsoMensajeMeta, wamid)
            if fila is None:
                fila = UsoMensajeMeta(wamid=wamid, phone_number_id=phone_number_id, estado=estado)
                session.add(fila)
            if not fila.negocio_id and evento.get("negocio_id"):
                fila.negocio_id = evento["negocio_id"]
            if not fila.destinatario and evento.get("destinatario"):
                fila.destinatario = evento["destinatario"]

            campo = _CAMPO_MOMENTO_POR_ESTADO[estado]
            actual = getattr(fila, campo)
            if actual is None or momento < actual:
                setattr(fila, campo, momento)

            if estado == "failed":
                if fila.estado not in ("delivered", "read"):
                    fila.estado = "failed"
            elif _RANGO_ESTADO_MENSAJE[estado] > _RANGO_ESTADO_MENSAJE.get(fila.estado, 0):
                fila.estado = estado

            if pricing.get("type") is not None:
                fila.pricing_type = pricing.get("type")
            if pricing.get("category") is not None:
                fila.pricing_categoria = pricing.get("category")
            if pricing.get("pricing_model") is not None:
                fila.pricing_model = pricing.get("pricing_model")
            if pricing.get("billable") is not None:
                fila.pricing_billable = bool(pricing.get("billable"))
            if error.get("codigo") is not None and fila.error_codigo is None:
                fila.error_codigo = error.get("codigo")
                fila.error_titulo = error.get("titulo")
            try:
                await session.commit()
                return True
            except IntegrityError:
                await session.rollback()
        return False


def _a_numero(valor: str | None, por_defecto: float | None = None) -> float | None:
    try:
        return float(str(valor).strip())
    except (TypeError, ValueError):
        return por_defecto


def _limites_de_mes_utc(mes: str | None, zona: str) -> tuple[datetime, datetime, str]:
    """(inicio, fin, 'YYYY-MM') del mes pedido en UTC naive. El mes se mide en
    `zona`: Meta no documenta en qué zona horaria reinicia la cuota, así que
    es configurable (`meta_zona_horaria_mes`, UTC por defecto) y se calibra
    contra el primer mensaje que Meta marque `regular`."""
    from datetime import timezone
    from zoneinfo import ZoneInfo

    try:
        tz = ZoneInfo(zona)
    except Exception:  # zona desconocida o sin base de zonas en el sistema
        tz = timezone.utc
    if mes:
        anio, num = (int(p) for p in mes.split("-"))
    else:
        ahora = datetime.now(tz)
        anio, num = ahora.year, ahora.month
    inicio = datetime(anio, num, 1, tzinfo=tz)
    fin = datetime(anio + 1, 1, 1, tzinfo=tz) if num == 12 else datetime(anio, num + 1, 1, tzinfo=tz)
    como_utc = lambda d: d.astimezone(timezone.utc).replace(tzinfo=None)
    return como_utc(inicio), como_utc(fin), f"{anio:04d}-{num:02d}"


CLAVE_USO_PREVIO = "meta_uso_previo_servicio_"
_CATEGORIA_TARIFA = re.compile(r"[a-z_]{1,40}")


async def _usos_previos_del_mes(negocio_id: str, mes: str) -> dict[str, int]:
    """{phone_number_id: mensajes de servicio gratis ya consumidos antes de que
    el registro de estados empezara a medir}, de la configuración del negocio."""
    prefijo = f"{CLAVE_USO_PREVIO}{mes}:"
    async with async_session() as session:
        filas = (await session.execute(
            select(Configuracion.clave, Configuracion.valor)
            .where(Configuracion.negocio_id == negocio_id, Configuracion.clave.like(f"{prefijo}%"))
        )).all()
    previos: dict[str, int] = {}
    for clave, valor in filas:
        n = _a_numero(valor)
        if n is not None and n > 0:
            previos[clave[len(prefijo):]] = int(n)
    return previos


async def guardar_configuracion_uso_meta(negocio_id: str, datos: dict, autor: str | None = None) -> dict:
    """Valida y guarda la configuración del control de uso de mensajes de Meta
    (cuota gratis, zona horaria del mes, tarifas en USD por categoría y uso
    previo estimado por número y mes). Todo o nada: si algo no es válido no se
    guarda nada y se lanza ValueError con el motivo. Devuelve las claves
    guardadas."""
    cambios: dict[str, str] = {}
    monto_elegido = False

    if datos.get("cuota_gratis_servicio") is not None:
        cuota = datos["cuota_gratis_servicio"]
        if isinstance(cuota, bool) or not isinstance(cuota, int) or not 0 <= cuota <= 1_000_000:
            raise ValueError("La cuota gratis debe ser un entero entre 0 y 1 000 000.")
        cambios["meta_cuota_gratis_servicio"] = str(cuota)

    if datos.get("tipo_cambio_pen_por_usd") is not None:
        tc = datos["tipo_cambio_pen_por_usd"]
        if isinstance(tc, bool) or not isinstance(tc, (int, float)) or not 1 <= tc <= 10:
            raise ValueError("El tipo de cambio debe ser un número de soles por dólar entre 1 y 10.")
        cambios["meta_tipo_cambio_pen_por_usd"] = repr(float(tc))

    if datos.get("zona_horaria_mes") is not None:
        from zoneinfo import ZoneInfo

        zona = str(datos["zona_horaria_mes"]).strip()
        try:
            ZoneInfo(zona)
        except Exception:
            raise ValueError("La zona horaria no existe (ej.: America/Lima o UTC).")
        cambios["meta_zona_horaria_mes"] = zona

    tarifas = datos.get("tarifas_usd")
    if tarifas is not None:
        if not isinstance(tarifas, dict):
            raise ValueError("Las tarifas deben ir como {categoria: monto en USD}.")
        for categoria, monto in tarifas.items():
            if not _CATEGORIA_TARIFA.fullmatch(str(categoria)):
                raise ValueError(f"Categoría de tarifa no válida: {categoria!r}.")
            if isinstance(monto, bool) or not isinstance(monto, (int, float)) or not 0 <= monto <= 10:
                raise ValueError(f"La tarifa de {categoria} debe ser un monto en USD entre 0 y 10.")
            cambios[f"meta_tarifa_usd_{categoria}"] = repr(float(monto))

    previo = datos.get("uso_previo")
    if previo is not None:
        if not isinstance(previo, dict):
            raise ValueError("El uso previo debe ir como {mes, phone_number_id, valor}.")
        mes, numero, valor = str(previo.get("mes", "")), str(previo.get("phone_number_id", "")), previo.get("valor")
        if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", mes):
            raise ValueError("El mes del uso previo debe tener el formato AAAA-MM.")
        if not re.fullmatch(r"\d{5,30}", numero):
            raise ValueError("Falta el phone_number_id del número (solo dígitos).")
        if isinstance(valor, bool) or not isinstance(valor, int) or not 0 <= valor <= 1_000_000:
            raise ValueError("El uso previo debe ser un entero entre 0 y 1 000 000.")
        cambios[f"{CLAVE_USO_PREVIO}{mes}:{numero}"] = str(valor)

    envios = datos.get("envios")
    if envios is not None:
        from agent.envios import ORIGENES   # import tardío: envios importa este módulo

        if not isinstance(envios, dict):
            raise ValueError("La configuración de envíos debe ir como un objeto.")
        modos = envios.get("modos")
        if modos is not None:
            if not isinstance(modos, dict):
                raise ValueError("Los interruptores deben ir como {origen: modo}.")
            for origen, modo in modos.items():
                if origen not in ORIGENES:
                    raise ValueError(f"Origen de envío desconocido: {origen!r}.")
                if modo not in ("siempre", "solo_gratis", "nunca"):
                    raise ValueError(f"El modo de {origen} debe ser siempre, solo_gratis o nunca.")
                if ORIGENES[origen].get("esencial") and modo != "siempre":
                    raise ValueError(f"{origen} es un envío esencial (el cliente lo espera): no se puede frenar por costo.")
                cambios[f"envios_modo_{origen}"] = modo
        if "autorecarga" in envios:
            if not isinstance(envios["autorecarga"], bool):
                raise ValueError("autorecarga debe ser true o false.")
            cambios["envios_tope_modo"] = "autorecarga" if envios["autorecarga"] else "tope"
        if "tope_mensual_usd" in envios:
            tope = envios["tope_mensual_usd"]
            if tope is None:
                cambios["envios_tope_mensual_usd"] = ""       # sin monto elegido: vale USD 0
            elif isinstance(tope, bool) or not isinstance(tope, (int, float)) or not 0 <= tope <= 1_000_000:
                raise ValueError("El tope mensual debe ser un monto en USD entre 0 y 1 000 000 (o null para volver a USD 0).")
            else:
                cambios["envios_tope_mensual_usd"] = repr(float(tope))
                monto_elegido = True   # si venía en autorecarga, elegir un monto sale de ella (ver más abajo)
        if "tope_bloquea_esenciales" in envios:
            if not isinstance(envios["tope_bloquea_esenciales"], bool):
                raise ValueError("tope_bloquea_esenciales debe ser true o false.")
            cambios["envios_tope_bloquea_esenciales"] = "true" if envios["tope_bloquea_esenciales"] else "false"
        agrupar = envios.get("agrupar_minutos")
        if agrupar is not None:
            if not isinstance(agrupar, dict):
                raise ValueError("La agrupación debe ir como {origen: minutos}.")
            for origen, minutos in agrupar.items():
                if origen not in ORIGENES:
                    raise ValueError(f"Origen de envío desconocido: {origen!r}.")
                if isinstance(minutos, bool) or not isinstance(minutos, int) or not 0 <= minutos <= 1440:
                    raise ValueError(f"Los minutos de agrupación de {origen} deben ser un entero entre 0 y 1440.")
                cambios[f"envios_agrupar_minutos_{origen}"] = str(minutos)

    if not cambios:
        raise ValueError("No hay nada que guardar.")
    if monto_elegido and "envios_tope_modo" not in cambios and (await obtener_configuracion("envios_tope_modo", "tope", negocio_id=negocio_id)) == "autorecarga":
        cambios["envios_tope_modo"] = "tope"

    # Valores sensibles: debilitan la protección de costo o pueden dejar a Gabi
    # sin responder. Exigen `confirmar_riesgo: true` (la pantalla lo pide con un
    # diálogo) y la combinación peligrosa se rechaza siempre.
    confirmado = datos.get("confirmar_riesgo") is True or (
        isinstance(datos.get("envios"), dict) and datos["envios"].get("confirmar_riesgo") is True
    )
    modo_tope = cambios.get("envios_tope_modo") or await obtener_configuracion("envios_tope_modo", "tope", negocio_id=negocio_id)
    if "envios_tope_mensual_usd" in cambios:
        tope_texto = cambios["envios_tope_mensual_usd"]
    else:
        tope_texto = await obtener_configuracion("envios_tope_mensual_usd", "", negocio_id=negocio_id)
    tope_efectivo = 0 if modo_tope == "autorecarga" else (_a_numero(tope_texto, 0) or 0)
    riesgos: list[str] = []
    if cambios.get("envios_tope_bloquea_esenciales") == "true":
        if modo_tope != "autorecarga" and tope_efectivo == 0:
            raise ValueError(
                "No se puede hacer que el tope también frene lo esencial mientras el tope sea USD 0: "
                "Gabi dejaría de responder a tus clientes en cuanto se agote la cuota gratis. Fija primero un monto."
            )
        riesgos.append("que el tope también frene lo esencial (Gabi y los asesores)")
    if cambios.get("envios_tope_modo") == "autorecarga":
        riesgos.append("quitar el límite de gasto (Meta cobrará a tu método de pago sin tope)")
    if "meta_cuota_gratis_servicio" in cambios and int(cambios["meta_cuota_gratis_servicio"]) > 1000:
        riesgos.append("una cuota gratis mayor a 1000 (el sistema creerá que hay gratis cuando Meta ya cobra)")
    if riesgos and not confirmado:
        raise ValueError("Confirma el riesgo para guardar: " + "; ".join(riesgos) + ". Envía confirmar_riesgo: true.")

    # Todo en UNA transacción, junto con la fila de auditoría: si no se puede
    # dejar constancia de quién cambió qué, no se cambia nada.
    async with async_session() as session:
        actuales = {
            c.clave: c for c in (await session.execute(
                select(Configuracion).where(Configuracion.negocio_id == negocio_id, Configuracion.clave.in_(list(cambios)))
            )).scalars().all()
        }
        registro: dict[str, dict] = {}
        for clave, valor in cambios.items():
            existente = actuales.get(clave)
            antes = existente.valor if existente else None
            if antes == valor:
                continue
            if existente is None:
                session.add(Configuracion(clave=clave, negocio_id=negocio_id, valor=valor))
            else:
                existente.valor = valor
            registro[clave] = {"antes": antes, "despues": valor}
        if registro:
            session.add(RegistroAuditoria(
                accion="uso_meta_configuracion", actor=autor, negocio_id=negocio_id, entidad_tipo="configuracion",
                payload={"cambios": registro, "riesgo_confirmado": bool(riesgos)},
            ))
        await session.commit()
    return {"guardadas": sorted(cambios), "modificadas": sorted(registro)}


async def listar_cambios_configuracion(negocio_id: str, limite: int = 50) -> list[dict]:
    """Historial de cambios de la configuración de uso y envíos (más reciente
    primero): quién, cuándo, y el valor anterior y nuevo de cada clave. Desde
    2026-10-12 incluye también los cambios del calendario de negocio (días
    especiales, feriados cargados y fecha de la medición hábil), con la misma
    forma `cambios: {accion: {antes, despues}}` (textos JSON, motivo dentro)."""
    async with async_session() as session:
        filas = (await session.execute(
            select(RegistroAuditoria).where(
                RegistroAuditoria.negocio_id == negocio_id,
                sa_or(RegistroAuditoria.entidad_tipo == "configuracion", _filtro_auditoria_calendario()),
            ).order_by(RegistroAuditoria.creado.desc()).limit(max(1, min(limite, 200)))
        )).scalars().all()
    resultado = []
    for f in filas:
        if f.entidad_tipo == "dia_especial" or f.accion == ACCION_CALENDARIO_HABIL_DESDE:
            cambios, riesgo = _cambios_de_auditoria_calendario(f), False
        else:
            cambios, riesgo = (f.payload or {}).get("cambios", {}), bool((f.payload or {}).get("riesgo_confirmado"))
        resultado.append({"creado": f.creado, "actor": f.actor, "accion": f.accion, "cambios": cambios, "riesgo_confirmado": riesgo})
    return resultado


async def obtener_configuracion_envios(negocio_id: str) -> dict:
    """Configuración vigente de uso y envíos, lista para pintar la pantalla:
    interruptor de cada origen (con su valor por defecto y si es esencial),
    agrupación, tope, autorecarga y los demás ajustes. Solo lectura."""
    from agent.envios import ORIGENES   # import tardío: envios importa este módulo

    origenes = []
    for nombre, politica in ORIGENES.items():
        por_defecto = "siempre" if politica.get("esencial") else politica.get("modo", "siempre")
        modo = por_defecto if politica.get("esencial") else await obtener_configuracion(f"envios_modo_{nombre}", por_defecto, negocio_id=negocio_id)
        if modo not in ("siempre", "solo_gratis", "nunca"):
            modo = por_defecto
        agrupar = None
        if politica.get("agrupar_minutos"):
            valor = await obtener_configuracion(f"envios_agrupar_minutos_{nombre}", str(politica["agrupar_minutos"]), negocio_id=negocio_id)
            agrupar = int(_a_numero(valor, politica["agrupar_minutos"]) or 0)
        categoria = None
        if politica.get("categoria_plantilla"):
            categoria = await obtener_configuracion(f"envios_categoria_{nombre}", politica["categoria_plantilla"], negocio_id=negocio_id)
        origenes.append({
            "origen": nombre, "esencial": bool(politica.get("esencial")), "exento_tope": bool(politica.get("exento_tope")),
            "modo": modo, "modo_por_defecto": por_defecto,
            "agrupar_minutos": agrupar, "categoria_plantilla": categoria,
        })
    autorecarga = (await obtener_configuracion("envios_tope_modo", "tope", negocio_id=negocio_id)) == "autorecarga"
    tarifas = {}
    for categoria in ("service", "utility", "marketing", "authentication"):
        valor = _a_numero(await obtener_configuracion(f"meta_tarifa_usd_{categoria}", "", negocio_id=negocio_id))
        if valor is not None:
            tarifas[categoria] = valor
    tope = _a_numero(await obtener_configuracion("envios_tope_mensual_usd", "", negocio_id=negocio_id), 0) or 0
    return {
        "origenes": origenes, "autorecarga": autorecarga, "tope_mensual_usd": 0 if autorecarga else tope,
        "tope_bloquea_esenciales": (await obtener_configuracion("envios_tope_bloquea_esenciales", "false", negocio_id=negocio_id)).lower() == "true",
        "meta_fep_horas": _a_numero(await obtener_configuracion("meta_fep_horas", "72", negocio_id=negocio_id), 72),
        "cuota_gratis_servicio": int(_a_numero(await obtener_configuracion("meta_cuota_gratis_servicio", "1000", negocio_id=negocio_id), 1000) or 0),
        "zona_horaria": await obtener_configuracion("meta_zona_horaria_mes", "UTC", negocio_id=negocio_id),
        # Soles por dólar para mostrar equivalentes APROXIMADOS. 3.327 sale de las rate cards de Meta
        # para Perú (0.0998 PEN / 0.0300 USD); es referencial y editable, nunca se usa para cobrar.
        "tipo_cambio_pen_por_usd": _a_numero(await obtener_configuracion("meta_tipo_cambio_pen_por_usd", "3.327", negocio_id=negocio_id), 3.327),
        "tarifas_usd": tarifas,
    }


async def primer_momento_de_uso_registrado(negocio_id: str) -> datetime:
    """Cuándo el registro de estados de Meta empezó a medir en este negocio
    (UTC naive); ahora mismo si todavía no hay ninguno."""
    async with async_session() as session:
        primero = (await session.execute(
            select(func.min(UsoMensajeMeta.creado)).where(UsoMensajeMeta.negocio_id == negocio_id)
        )).scalar_one_or_none()
    return primero or datetime.utcnow()


async def estimar_uso_previo_servicio(
    negocio_id: str, desde: datetime, hasta: datetime, ventanas_fep_horas: tuple[int, ...] = (72, 168),
) -> dict:
    """Cuántos mensajes de servicio gratis (cuota de 1000) consumió el negocio
    entre `desde` y `hasta` (UTC naive), ANTES de que el registro de estados de
    Meta empezara a medir — insumo para `meta_uso_previo_servicio_<mes>:<numero>`.

    Parte de los mensajes realmente enviados por la API (Gabi y los asesores
    del panel; sin los de la app de WhatsApp Business ni los fallidos) y los
    clasifica como lo haría Meta:
    - `ventana_anuncio`: dentro del intervalo gratuito de un anuncio Click-to-
      WhatsApp. Se abre con la primera respuesta (dentro de las 24 h del
      mensaje que trajo el referral) y dura `D` horas. La duración se prueba
      con varios valores (72 h y 7 días) porque la documentación de Meta no
      es consistente entre páginas; el registro de estados dirá cuál es.
    - `servicio`: respuesta libre dentro de las 24 h del último mensaje del
      cliente → consume la cuota gratis.
    - `fuera_de_ventana_24h`: sin mensaje del cliente en las 24 h previas, solo
      puede haber sido plantilla → se cobra por su categoría, no es servicio.
    Es una cota: no distingue si el cliente hizo clic desde la app móvil
    (el único caso en que Meta abre el intervalo) ni si el mensaje llegó a ser
    entregado, así que 'ventana_anuncio' es el máximo posible y `servicio`
    el mínimo."""
    holgura = timedelta(days=max(ventanas_fep_horas) / 24 + 1)
    async with async_session() as session:
        mensajes = (await session.execute(
            select(Mensaje.telefono, Mensaje.role, Mensaje.timestamp, Mensaje.via_app, Mensaje.estado_envio)
            .where(Mensaje.negocio_id == negocio_id, Mensaje.timestamp >= desde - holgura, Mensaje.timestamp < hasta)
            .order_by(Mensaje.telefono, Mensaje.timestamp)
        )).all()
        anuncios = (await session.execute(
            select(AttributionEvent.lead_telefono, AttributionEvent.creado)
            .where(
                AttributionEvent.negocio_id == negocio_id,
                AttributionEvent.tipo_origen.in_(("meta_ads", "meta_ads_no_resuelto")),
                AttributionEvent.creado >= desde - holgura, AttributionEvent.creado < hasta,
            )
        )).all()

    clics: dict[str, list[datetime]] = {}
    for telefono, creado in anuncios:
        clics.setdefault(telefono, []).append(creado)
    por_telefono: dict[str, list[tuple]] = {}
    for fila in mensajes:
        por_telefono.setdefault(fila[0], []).append(fila[1:])

    dia = timedelta(hours=24)
    resultado = {h: {"ventana_anuncio": 0, "servicio": 0, "fuera_de_ventana_24h": 0} for h in ventanas_fep_horas}
    salientes = 0
    telefonos_con_anuncio: set[str] = set()
    for telefono, filas in por_telefono.items():
        salidas = [
            ts for role, ts, via_app, estado in filas
            if role in ("assistant", "asesor") and not via_app and estado != "fallido"
        ]
        # Aperturas: primera respuesta de la API dentro de las 24 h de cada referral.
        aperturas = []
        for clic in clics.get(telefono, []):
            apertura = next((ts for ts in salidas if clic <= ts <= clic + dia), None)
            if apertura is not None:
                aperturas.append(apertura)
        ultimo_cliente: datetime | None = None
        for role, ts, via_app, estado in filas:
            if role == "user":
                ultimo_cliente = ts
                continue
            if role not in ("assistant", "asesor") or via_app or estado == "fallido":
                continue
            if not desde <= ts < hasta:
                continue
            salientes += 1
            en_servicio = ultimo_cliente is not None and ts - ultimo_cliente <= dia
            for horas in ventanas_fep_horas:
                if any(a <= ts <= a + timedelta(hours=horas) for a in aperturas):
                    resultado[horas]["ventana_anuncio"] += 1
                    telefonos_con_anuncio.add(telefono)
                elif en_servicio:
                    resultado[horas]["servicio"] += 1
                else:
                    resultado[horas]["fuera_de_ventana_24h"] += 1

    consumos = [r["servicio"] for r in resultado.values()]
    return {
        "desde": desde.isoformat(), "hasta": hasta.isoformat(), "salientes_api": salientes,
        "conversaciones_con_anuncio": len(telefonos_con_anuncio),
        "por_duracion_ventana_horas": {str(h): r for h, r in resultado.items()},
        "consumo_cuota_estimado": {"minimo": min(consumos), "maximo": max(consumos)} if consumos else None,
    }


async def resumen_uso_mensual(negocio_id: str, mes: str | None = None) -> dict:
    """Uso del mes por número de WhatsApp del negocio, a partir de lo que Meta
    informó en cada mensaje ENTREGADO (`uso_mensajes_meta`):

    - `servicio_gratis_usados`: type=free_customer_service (consumen la cuota).
    - `servicio_cobrables`: type=regular y categoría service (ya pasó la cuota).
    - `ventana_anuncio_gratis`: type=free_entry_point (ventana gratuita de
      anuncios Click-to-WhatsApp; se cuenta aparte, no se supone que consuma
      la cuota — eso lo dice Meta mensaje a mensaje).
    - `otros_cobrables`: type=regular de otras categorías (utility,
      marketing, authentication...) por categoría.
    - `sin_clasificar`: entregados sin `pricing` (todavía no llegó o Meta no
      lo informó) — no se asigna a ningún grupo.

    La cuota (`meta_cuota_gratis_servicio`, 1000), la zona del mes
    (`meta_zona_horaria_mes`, UTC) y las tarifas (`meta_tarifa_usd_<categoria>`,
    sin valor por defecto) son configuración por negocio — nada de eso está
    fijo en el código. Sin tarifa configurada, `costo_estimado_usd` es None y
    se informa cuáles faltan. Las alertas (80/95/100 %) usan los gratis usados
    sobre la cuota; 100 % también si ya hay cobrables de servicio."""
    zona = await obtener_configuracion("meta_zona_horaria_mes", "UTC", negocio_id=negocio_id)
    cuota = int(_a_numero(await obtener_configuracion("meta_cuota_gratis_servicio", "1000", negocio_id=negocio_id), 1000) or 0)
    inicio, fin, mes_normalizado = _limites_de_mes_utc(mes, zona)

    momento = func.coalesce(UsoMensajeMeta.entregado_en, UsoMensajeMeta.leido_en)
    async with async_session() as session:
        filas = (await session.execute(
            select(
                UsoMensajeMeta.phone_number_id, UsoMensajeMeta.pricing_type, UsoMensajeMeta.pricing_categoria,
                func.count().label("n"),
            )
            .where(
                UsoMensajeMeta.negocio_id == negocio_id,
                UsoMensajeMeta.estado.in_(("delivered", "read")),
                momento >= inicio, momento < fin,
            )
            .group_by(UsoMensajeMeta.phone_number_id, UsoMensajeMeta.pricing_type, UsoMensajeMeta.pricing_categoria)
        )).all()

    previos = await _usos_previos_del_mes(negocio_id, mes_normalizado)

    def _nuevo_numero(phone_number_id: str) -> dict:
        return {
            "phone_number_id": phone_number_id, "entregados": 0, "servicio_gratis_usados": 0,
            "servicio_cobrables": 0, "ventana_anuncio_gratis": 0, "otros_cobrables": {}, "sin_clasificar": 0,
        }

    numeros: dict[str, dict] = {pid: _nuevo_numero(pid) for pid in previos}
    for phone_number_id, tipo, categoria, n in filas:
        d = numeros.setdefault(phone_number_id, _nuevo_numero(phone_number_id))
        d["entregados"] += n
        if tipo == "free_customer_service":
            d["servicio_gratis_usados"] += n
        elif tipo == "free_entry_point":
            d["ventana_anuncio_gratis"] += n
        elif tipo == "regular" and categoria == "service":
            d["servicio_cobrables"] += n
        elif tipo == "regular":
            clave = categoria or "sin_categoria"
            d["otros_cobrables"][clave] = d["otros_cobrables"].get(clave, 0) + n
        else:
            d["sin_clasificar"] += n

    categorias_usadas: set[str] = set()
    for d in numeros.values():
        if d["servicio_cobrables"]:
            categorias_usadas.add("service")
        categorias_usadas.update(d["otros_cobrables"])
    tarifas = {c: _a_numero(await obtener_configuracion(f"meta_tarifa_usd_{c}", "", negocio_id=negocio_id)) for c in categorias_usadas}
    faltantes = sorted(c for c, t in tarifas.items() if t is None)

    for d in numeros.values():
        # Lo enviado antes de que existiera el registro de estados (estimado a
        # mano, `meta_uso_previo_servicio_<mes>:<phone_number_id>`) consume la
        # misma cuota; se informa aparte para que no se confunda con lo medido.
        d["servicio_gratis_previos_estimados"] = previos.get(d["phone_number_id"], 0)
        usados = d["servicio_gratis_usados"] + d["servicio_gratis_previos_estimados"]
        d["servicio_gratis_total"] = usados
        d["gratis_restantes"] = max(0, cuota - usados)
        d["porcentaje_cuota"] = round(100 * usados / cuota, 1) if cuota else None
        alertas = [u for u in (80, 95, 100) if cuota and usados * 100 >= u * cuota]
        if d["servicio_cobrables"] and 100 not in alertas:
            alertas.append(100)
        d["alertas"] = alertas
        if faltantes:
            d["costo_estimado_usd"] = None
        else:
            costo = d["servicio_cobrables"] * (tarifas.get("service") or 0)
            costo += sum(n * (tarifas.get(c) or 0) for c, n in d["otros_cobrables"].items())
            d["costo_estimado_usd"] = round(costo, 4)

    # Tope mensual de gasto (capa de envíos, Fase B): sin tope configurado todo
    # esto queda en None. El gasto es el estimado con las tarifas configuradas;
    # con tarifas faltantes no se puede calcular y se informa como None.
    autorecarga = (await obtener_configuracion("envios_tope_modo", "tope", negocio_id=negocio_id)) == "autorecarga"
    tope = 0 if autorecarga else (_a_numero(await obtener_configuracion("envios_tope_mensual_usd", "", negocio_id=negocio_id), 0) or 0)
    gasto = None if faltantes else round(sum(d["costo_estimado_usd"] or 0 for d in numeros.values()), 4)
    porcentaje_tope = round(100 * gasto / tope, 1) if tope > 0 and gasto is not None else None
    alertas_tope = [u for u in (80, 100) if porcentaje_tope is not None and porcentaje_tope >= u]
    if tope == 0 and not autorecarga and gasto:
        alertas_tope = [80, 100]   # tope de USD 0 y ya hay gasto: está superado

    return {
        "mes": mes_normalizado, "zona_horaria": zona, "cuota_gratis_servicio": cuota,
        "tarifas_usd": {c: t for c, t in tarifas.items() if t is not None}, "tarifas_faltantes": faltantes,
        "numeros": sorted(numeros.values(), key=lambda d: d["phone_number_id"]),
        "autorecarga": autorecarga, "tope_mensual_usd": None if autorecarga else tope,
        "gasto_estimado_usd": gasto, "porcentaje_tope": porcentaje_tope, "alertas_tope": alertas_tope,
    }


async def resumen_envios_por_origen(negocio_id: str, mes: str | None = None) -> dict:
    """Cuánto envió cada origen en el mes y qué terminó cobrando Meta por ello.
    `enviados`/`bloqueados`/`fallidos` salen del registro de envíos; lo cobrado
    sale de cruzar el wamid con lo que Meta informó (uso_mensajes_meta): gratis
    por la cuota de servicio, gratis por ventana de anuncio, o cobrable (por
    categoría). `sin_estado` = enviados de los que Meta todavía no informó la
    entrega. El costo usa las tarifas configuradas (None si falta alguna)."""
    zona = await obtener_configuracion("meta_zona_horaria_mes", "UTC", negocio_id=negocio_id)
    inicio, fin, mes_normalizado = _limites_de_mes_utc(mes, zona)
    origenes: dict[str, dict] = {}

    def _origen(nombre: str) -> dict:
        return origenes.setdefault(nombre, {
            "origen": nombre, "enviados": 0, "fallidos": 0, "inciertos": 0, "bloqueados": 0, "motivos_bloqueo": {},
            "gratis_cuota": 0, "gratis_ventana_anuncio": 0, "cobrables": {}, "sin_estado": 0,
        })

    async with async_session() as session:
        conteos = (await session.execute(
            select(EnvioMeta.origen, EnvioMeta.decision, func.count())
            .where(EnvioMeta.negocio_id == negocio_id, EnvioMeta.creado >= inicio, EnvioMeta.creado < fin)
            .group_by(EnvioMeta.origen, EnvioMeta.decision)
        )).all()
        motivos = (await session.execute(
            select(EnvioMeta.origen, EnvioMeta.motivo, func.count())
            .where(EnvioMeta.negocio_id == negocio_id, EnvioMeta.decision == "bloqueado", EnvioMeta.creado >= inicio, EnvioMeta.creado < fin)
            .group_by(EnvioMeta.origen, EnvioMeta.motivo)
        )).all()
        asesores_conteos = (await session.execute(
            select(EnvioMeta.asesor_usuario, EnvioMeta.tipo, EnvioMeta.decision, func.count())
            .where(
                EnvioMeta.negocio_id == negocio_id, EnvioMeta.asesor_usuario.is_not(None),
                EnvioMeta.creado >= inicio, EnvioMeta.creado < fin,
            )
            .group_by(EnvioMeta.asesor_usuario, EnvioMeta.tipo, EnvioMeta.decision)
        )).all()
        cruzados = (await session.execute(
            select(EnvioMeta.origen, UsoMensajeMeta.pricing_type, UsoMensajeMeta.pricing_categoria, func.count())
            .join(UsoMensajeMeta, UsoMensajeMeta.wamid == EnvioMeta.wamid)
            .where(
                EnvioMeta.negocio_id == negocio_id, EnvioMeta.decision == "enviado",
                EnvioMeta.creado >= inicio, EnvioMeta.creado < fin, UsoMensajeMeta.estado.in_(("delivered", "read")),
            )
            .group_by(EnvioMeta.origen, UsoMensajeMeta.pricing_type, UsoMensajeMeta.pricing_categoria)
        )).all()

    for nombre, decision, n in conteos:
        d = _origen(nombre)
        if decision == "enviado":
            d["enviados"] += n
        elif decision == "fallido":
            d["fallidos"] += n
        elif decision == "incierto":
            d["inciertos"] += n   # el POST pudo llegar a Meta: no es ni enviado ni fallido (ver marcar_envio_incierto)
        elif decision == "bloqueado":
            d["bloqueados"] += n
    for nombre, motivo, n in motivos:
        _origen(nombre)["motivos_bloqueo"][motivo or "sin motivo"] = n
    # Por asesor (solo lo que mandó desde el panel; sin dinero): mensajes = texto, archivos =
    # imagen + documento + audio, bloqueados = lo que la política frenó. Los fallidos/inciertos
    # no cuentan como mensajes. Ordenado por mensajes de mayor a menor.
    por_asesor: dict[str, dict] = {}
    for asesor_u, tipo, decision, n in asesores_conteos:
        d = por_asesor.setdefault(asesor_u, {"asesor": asesor_u, "mensajes": 0, "archivos": 0, "bloqueados": 0})
        if decision == "bloqueado":
            d["bloqueados"] += n
        elif decision == "enviado":
            d["mensajes" if tipo == "texto" else "archivos"] += n
    medidos: dict[str, int] = {}
    for nombre, tipo, categoria, n in cruzados:
        d = _origen(nombre)
        medidos[nombre] = medidos.get(nombre, 0) + n
        if tipo == "free_customer_service":
            d["gratis_cuota"] += n
        elif tipo == "free_entry_point":
            d["gratis_ventana_anuncio"] += n
        elif tipo == "regular":
            clave = categoria or "sin_categoria"
            d["cobrables"][clave] = d["cobrables"].get(clave, 0) + n
    tarifas: dict[str, float | None] = {}
    for d in origenes.values():
        d["sin_estado"] = max(0, d["enviados"] - medidos.get(d["origen"], 0))
        costo: float | None = 0.0
        for categoria, n in d["cobrables"].items():
            if categoria not in tarifas:
                tarifas[categoria] = _a_numero(await obtener_configuracion(f"meta_tarifa_usd_{categoria}", "", negocio_id=negocio_id))
            costo = None if (costo is None or tarifas[categoria] is None) else costo + n * tarifas[categoria]
        d["costo_estimado_usd"] = None if costo is None else round(costo, 4)
    return {
        "mes": mes_normalizado, "zona_horaria": zona, "origenes": sorted(origenes.values(), key=lambda d: d["origen"]),
        "por_asesor": sorted(por_asesor.values(), key=lambda d: (-d["mensajes"], d["asesor"])),
    }


def _canal_a_dict(c: CanalWhatsApp) -> dict:
    """Retorna el canal con sus credenciales YA DESCIFRADAS — para uso interno
    (ProveedorMeta necesita el valor real para llamar a la API de Meta). El
    llamador (ej. la pantalla del panel) es responsable de no mostrar estos
    valores completos en la UI."""
    return {
        "id": c.id,
        "nombre": c.nombre,
        "phone_number_id": c.phone_number_id,
        "access_token": _descifrar(c.access_token_cifrado),
        "app_secret": _descifrar(c.app_secret_cifrado),
        "page_access_token": _descifrar(c.page_access_token_cifrado),
        "waba_id": c.waba_id,
        "token_renovado_en": c.token_renovado_en,
        "activo": c.activo,
        "modo": c.modo,
        "creado": c.creado,
        "actualizado": c.actualizado,
        # Gate 5.2 — necesario para que resolver_canal() pueda filtrar por
        # negocio (ver agent/providers/meta.py).
        "negocio_id": c.negocio_id,
        "unidad_id": c.unidad_id,
    }


async def crear_canal_whatsapp(
    nombre: str, phone_number_id: str, access_token: str = "",
    app_secret: str = "", page_access_token: str = "", modo: str = "produccion",
    waba_id: str = "", negocio_id: str | None = None, unidad_id: str | None = None,
) -> dict:
    """Agrega un número de WhatsApp nuevo administrable desde el panel.
    `negocio_id` es obligatorio (Gate 5.2, corrección H3) — quien llama debe
    resolverlo desde una fuente legítima (el Negocio del admin que crea el
    canal, o el único Negocio del sistema en el bootstrap desde .env). Nunca
    se asume un Negocio por defecto. `unidad_id` sigue opcional — las
    Unidades reales de Cálidda son dato pendiente (ver Arquitectura
    Contractual §6, excepción temporal de migración)."""
    if negocio_id is None:
        raise ValueError(
            f"crear_canal_whatsapp(): no se puede crear el canal '{nombre}' sin negocio_id "
            f"resuelto. No se asume ningún Negocio por defecto (Gate 5.2)."
        )
    async with async_session() as session:
        canal = CanalWhatsApp(
            nombre=nombre,
            phone_number_id=phone_number_id,
            access_token_cifrado=_cifrar(access_token),
            app_secret_cifrado=_cifrar(app_secret),
            page_access_token_cifrado=_cifrar(page_access_token),
            waba_id=waba_id or None,
            token_renovado_en=datetime.utcnow() if access_token else None,
            modo=modo if modo in ("produccion", "pruebas") else "produccion",
            negocio_id=negocio_id,
            unidad_id=unidad_id,
        )
        session.add(canal)
        await session.commit()
        await session.refresh(canal)
        return _canal_a_dict(canal)


async def listar_canales_whatsapp(negocio_id: str | None = None, solo_activos: bool = False) -> list[dict]:
    """Recupera los canales de WhatsApp configurados, con sus credenciales
    descifradas — usado tanto por ProveedorMeta (para enviar/verificar) como
    por la pantalla de administración del panel.

    `negocio_id` (Gate 5.4, T2) es OPCIONAL a propósito, a diferencia de las
    demás funciones de listado corregidas en este mismo Gate — es la única
    excepción documentada. `resolver_canal()` (agent/providers/meta.py) llama
    a esta función SIN negocio_id cuando todavía está tratando de averiguar a
    qué Negocio pertenece un mensaje entrante por su phone_number_id: es
    estructuralmente imposible pedirle de antemano el dato que está
    resolviendo (resolución de identidad del webhook). Cuando SÍ se pasa
    negocio_id (panel de administración, ver gestionar_canales_whatsapp en
    dashboard.py), se filtra con candado normal. Si se omite, la función
    devuelve canales de TODOS los Negocios — comportamiento intencional solo
    para ese único llamador legítimo, nunca para una pantalla del panel."""
    async with async_session() as session:
        query = select(CanalWhatsApp).order_by(CanalWhatsApp.creado.asc())
        if negocio_id is not None:
            query = query.where(CanalWhatsApp.negocio_id == negocio_id)
        if solo_activos:
            query = query.where(CanalWhatsApp.activo.is_(True))
        result = await session.execute(query)
        return [_canal_a_dict(c) for c in result.scalars().all()]


async def obtener_canal_whatsapp(canal_id: int) -> dict | None:
    """Gate 5.3 — corrección pequeña: existe para que las rutas admin de
    edición/toggle/modo puedan verificar `negocio_id` del recurso ANTES de
    mutar (hallazgo de la ronda de Diseño Técnico: la FK ya es correcta,
    faltaba el chequeo de ownership — hoy con un solo Negocio el gate de rol
    ya bastaba, deja de bastar en cuanto exista un segundo)."""
    async with async_session() as session:
        canal = await session.get(CanalWhatsApp, canal_id)
        return _canal_a_dict(canal) if canal else None


async def actualizar_canal_whatsapp(canal_id: int, **campos):
    """Actualiza los datos de un canal (nombre, tokens, activo/inactivo).
    Los campos de credenciales, si vienen presentes, se cifran antes de
    guardarse; si vienen vacíos/None no se tocan (para no borrar un token ya
    guardado solo porque el formulario de edición no lo volvió a mandar)."""
    async with async_session() as session:
        canal = await session.get(CanalWhatsApp, canal_id)
        if canal is None:
            return
        if "nombre" in campos and campos["nombre"]:
            canal.nombre = campos["nombre"]
        if "phone_number_id" in campos and campos["phone_number_id"]:
            canal.phone_number_id = campos["phone_number_id"]
        if campos.get("waba_id"):
            # Un canal creado a mano con "Nuevo canal" nace sin esto (ver
            # docstring de CanalWhatsApp) — se completa recién acá, cuando se
            # registra el número en Meta desde el panel (2026-09-16).
            canal.waba_id = campos["waba_id"]
        if campos.get("access_token"):
            canal.access_token_cifrado = _cifrar(campos["access_token"])
            # Solo se toca cuando de verdad llega un access_token nuevo — no
            # con cualquier edición (nombre, toggle activo/modo, etc.), para
            # que el contador de vencimiento refleje la última renovación
            # real, no la última vez que se tocó el registro.
            canal.token_renovado_en = datetime.utcnow()
        if campos.get("app_secret"):
            canal.app_secret_cifrado = _cifrar(campos["app_secret"])
        if campos.get("page_access_token"):
            canal.page_access_token_cifrado = _cifrar(campos["page_access_token"])
        if "activo" in campos:
            canal.activo = campos["activo"]
        if campos.get("modo") in ("produccion", "pruebas"):
            canal.modo = campos["modo"]
        canal.actualizado = datetime.utcnow()
        await session.commit()


async def sembrar_canales_desde_env(negocio_id: str | None):
    """Si la tabla de canales está vacía, la siembra a partir de las
    variables de entorno META_CANAL_N_* (o las sueltas META_ACCESS_TOKEN/
    META_PHONE_NUMBER_ID/META_APP_SECRET como canal único) — así una
    instalación que ya venía configurada por variable de entorno sigue
    funcionando igual tras este cambio, sin perder su configuración ni
    necesitar que alguien la vuelva a escribir a mano en el panel.

    Corrección arquitectónica post-auditoría: esta función YA NO busca a qué
    Negocio pertenecen los canales — ni por "el único que hay", ni por
    nombre/código fijo. `negocio_id` es SIEMPRE responsabilidad exclusiva de
    quien llama (ver `main.py`, que lo resuelve desde la variable de entorno
    `NEGOCIO_BOOTSTRAP_CODIGO` vía `obtener_negocio_por_codigo`) — que hoy
    exista un único Negocio operativo (Cálidda) es una condición actual del
    sistema, no una propiedad de esta función. Con `negocio_id=None` (el
    caller no pudo resolverlo) o un `negocio_id` que no corresponde a ningún
    Negocio real, falla cerrado: no siembra nada, nunca asume ni el primero
    ni el único."""
    # Idempotencia primero (igual orden que antes de esta corrección): si ya
    # hay canales, no se toca nada — ni siquiera vale la pena parsear el
    # entorno ni resolver negocio_id.
    existentes = await listar_canales_whatsapp()
    if existentes:
        return

    canales_env = []
    i = 1
    while True:
        phone_number_id = os.getenv(f"META_CANAL_{i}_PHONE_NUMBER_ID")
        if not phone_number_id:
            break
        canales_env.append({
            "nombre": os.getenv(f"META_CANAL_{i}_NOMBRE", f"Canal {i}"),
            "phone_number_id": phone_number_id,
            "access_token": os.getenv(f"META_CANAL_{i}_ACCESS_TOKEN", ""),
            "app_secret": os.getenv(f"META_CANAL_{i}_APP_SECRET", ""),
            "page_access_token": os.getenv(f"META_CANAL_{i}_PAGE_ACCESS_TOKEN", ""),
        })
        i += 1

    if not canales_env:
        phone_number_id = os.getenv("META_PHONE_NUMBER_ID")
        if phone_number_id:
            canales_env.append({
                "nombre": "Principal",
                "phone_number_id": phone_number_id,
                "access_token": os.getenv("META_ACCESS_TOKEN", ""),
                "app_secret": os.getenv("META_APP_SECRET", ""),
                "page_access_token": os.getenv("META_PAGE_ACCESS_TOKEN", ""),
            })

    if not canales_env:
        return

    if negocio_id is None or await obtener_negocio(negocio_id) is None:
        logger.error(
            "sembrar_canales_desde_env(): hay %d canal(es) para sembrar desde variables de "
            "entorno, pero negocio_id %s — no se siembra ninguno (fail-closed). Configura "
            "NEGOCIO_BOOTSTRAP_CODIGO con el código de un Negocio existente antes de arrancar.",
            len(canales_env),
            "no fue proporcionado" if negocio_id is None else f"'{negocio_id}' no corresponde a ningún Negocio existente",
        )
        return

    for datos in canales_env:
        await crear_canal_whatsapp(**datos, negocio_id=negocio_id)
    logger.info(f"Sembrados {len(canales_env)} canal(es) de WhatsApp desde variables de entorno, Negocio {negocio_id}")


async def inicializar_db():
    """Aplica las migraciones de Alembic hasta la última versión — Data
    Architecture Fase 1: create_all() deja de usarse como mecanismo de
    cambio de esquema en producción, ver agent/migraciones.py."""
    from agent.migraciones import aplicar_migraciones
    await aplicar_migraciones()


async def esperar_base_de_datos(intentos: int = 15, pausa_seg: float = 1.0) -> None:
    """Espera a que la base acepte conexiones antes de que un script de Cron
    haga su trabajo. Railway tarda un instante en levantar la red PRIVADA
    dentro de un contenedor nuevo, y un Cron que conecta en el mismo segundo
    en que arranca falla con "Connection refused" (2026-09-24: las dos tareas
    de las 11:01 y 11:04 fallaron así al pasar de la red pública a la
    privada). Reintenta y solo se rinde si tras `intentos` la base sigue sin
    contestar, con el último error a la vista."""
    ultimo_error: Exception | None = None
    for intento in range(1, intentos + 1):
        try:
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
            return
        except Exception as e:  # noqa: BLE001 — cualquier fallo de conexión cuenta como "aún no"
            ultimo_error = e
            if intento < intentos:
                await asyncio.sleep(pausa_seg)
    raise ultimo_error  # type: ignore[misc]


async def medir_latencia_db(muestras: int = 5) -> dict:
    """Mide cuánto tarda UN viaje de ida y vuelta a la base (SELECT 1, en una
    conexión ya abierta) — 2026-09-24: guardar un mensaje entrante pasó a
    tardar 1.3-2.5 s con ~15 consultas, o sea 100 ms por consulta, cuando un
    Postgres en la misma región debería dar 1-5 ms. Este número separa "la
    base está lejos/lenta" de "el código hace demasiado". Se registra al
    arrancar (ver main.py) y es el primer dato a mirar en los logs."""
    from sqlalchemy.pool import NullPool

    tiempos: list[float] = []
    async with engine.connect() as conn:
        await conn.execute(text("SELECT 1"))  # descarta el primero: puede incluir abrir la conexión
        for _ in range(muestras):
            inicio = time.perf_counter()
            await conn.execute(text("SELECT 1"))
            tiempos.append((time.perf_counter() - inicio) * 1000)

    # Costo de abrir una conexión NUEVA (TCP + TLS + autenticación), que es lo
    # que paga cada pedido cuando el pool no tiene una libre.
    sin_pool = create_async_engine(DATABASE_URL, poolclass=NullPool)
    try:
        inicio = time.perf_counter()
        async with sin_pool.connect() as conn:
            await conn.execute(text("SELECT 1"))
        conexion_nueva = (time.perf_counter() - inicio) * 1000
    finally:
        await sin_pool.dispose()
    resultado = {
        "min_ms": round(min(tiempos), 1), "prom_ms": round(sum(tiempos) / len(tiempos), 1),
        "max_ms": round(max(tiempos), 1), "conexion_nueva_ms": round(conexion_nueva, 1),
    }
    resultado["red"] = tipo_de_red_de_la_base(DATABASE_URL)
    resultado.update(await medir_latencia_escritura_db(muestras))
    return resultado


def tipo_de_red_de_la_base(url: str) -> str:
    """Dice SOLO si la app llega a la base por la red privada de Railway
    (`*.railway.internal`, rápida y sin costo de tráfico) o por otra ruta
    (el proxy público `*.proxy.rlwy.net` u otro host). Nunca devuelve el host,
    el usuario ni la contraseña: es lo único que se puede loguear sin filtrar
    credenciales. 2026-09-24: las métricas del Postgres mostraban tráfico en
    "red pública" con la app en la misma región."""
    from urllib.parse import urlparse

    if url.startswith("sqlite"):
        return "local"
    host = (urlparse(url).hostname or "").lower()
    if host.endswith(".railway.internal"):
        return "privada"
    if host.endswith(".rlwy.net") or host.endswith(".railway.app"):
        return "publica-proxy"
    return "otra"


async def medir_latencia_escritura_db(muestras: int = 5) -> dict:
    """Mide cuánto tarda un COMMIT que escribe en el registro de transacciones
    de Postgres (`txid_current()` asigna un id de transacción, así que el
    commit debe grabarse en disco sin tocar ninguna tabla). 2026-09-24: en
    producción los pasos del webhook que solo leen tardan 7-9 ms y los que
    escriben 500-3800 ms, mientras `SELECT 1` va a 2 ms — sospecha: el disco
    del Postgres. Este número lo confirma o lo descarta. Solo Postgres."""
    if engine.dialect.name != "postgresql":
        return {}
    tiempos: list[float] = []
    sin_fsync: list[float] = []
    lecturas: list[float] = []
    async with engine.connect() as conn:
        for _ in range(muestras):
            # Commit normal: espera a que el registro llegue a disco (fsync).
            inicio = time.perf_counter()
            await conn.execute(text("SELECT txid_current()"))
            await conn.commit()
            tiempos.append((time.perf_counter() - inicio) * 1000)
            # Mismo commit sin esperar el fsync: si este va rápido cuando el
            # normal tarda ~400 ms, el retraso es del disco.
            inicio = time.perf_counter()
            await conn.execute(text("SET LOCAL synchronous_commit = off"))
            await conn.execute(text("SELECT txid_current()"))
            await conn.commit()
            sin_fsync.append((time.perf_counter() - inicio) * 1000)
            # Lectura pura, para ver si la lentitud alcanza también a la red
            # y no solo al disco.
            inicio = time.perf_counter()
            await conn.execute(text("SELECT 1"))
            lecturas.append((time.perf_counter() - inicio) * 1000)
    return {
        "escritura_min_ms": round(min(tiempos), 1),
        "escritura_prom_ms": round(sum(tiempos) / len(tiempos), 1),
        "escritura_max_ms": round(max(tiempos), 1),
        "sin_fsync_max_ms": round(max(sin_fsync), 1),
        "lectura_max_ms": round(max(lecturas), 1),
    }


async def guardar_mensaje(
    telefono: str, role: str, content: str, negocio_id: str | None, archivo_id: int | None = None, via_app: bool = False,
    mensaje_id_meta: str | None = None, estado_envio: str | None = None,
    respondido_a_id: int | None = None,
) -> dict:
    """Guarda un mensaje en el historial de conversación. archivo_id solo se
    usa cuando el mensaje fue un archivo adjunto enviado por un asesor.
    via_app=True cuando llegó por el echo de coexistencia (asesor respondió
    desde la app de WhatsApp Business en el celular, no desde el panel).
    mensaje_id_meta/estado_envio: ver Mensaje. respondido_a_id: id interno
    (Mensaje.id) del mensaje que este mensaje citó al enviarse (Reply/Quote,
    ver responder_cliente) — None si no citó nada.

    `negocio_id` (Gate 5.5 — corrección de integridad de escritura, hallazgo
    del propio proceso de implementación de Realtime): antes se resolvía
    internamente desde `Lead.telefono` (Gate 5.2, corrección H1) — un bridge
    global, sin candado de Negocio, que en el escenario que motiva este Gate
    (mismo teléfono en dos Negocios) podía escribir el `Mensaje` con el
    `negocio_id`/`conversation_id` del Negocio que "ganó" la fila `Lead`, no
    necesariamente el del Canal por el que realmente llegó ESTE mensaje.
    Ahora es explícito en la firma y obligatorio en la práctica — los 12
    call sites reales (main.py, dashboard.py) YA tienen `negocio_id`
    disponible sin resolución adicional (el Canal ya identificado en el
    webhook, o `usuario["negocio_id"]` de la sesión del panel). Se acepta
    `None` en el tipo SOLO porque el webhook puede legítimamente no haber
    podido resolver el Canal todavía (mismo caso ya fail-closed que
    `actualizar_lead`/`obtener_lead` en ese mismo flujo) — en ese caso se
    falla cerrado con un error claro, nunca se infiere de `telefono`, nunca
    se cae a "el único Lead" ni a ningún otro default implícito.

    Retorna el mensaje ya guardado (con su `id` real) — antes no retornaba
    nada; hace falta para que quien envía un mensaje saliente pueda
    referenciarlo después (mostrarlo con opción de reintento si
    estado_envio=="fallido", o dejar que se lo cite desde otro mensaje)."""
    if negocio_id is None:
        raise ValueError(
            f"guardar_mensaje(): negocio_id no resuelto para telefono={telefono} — "
            f"no se puede escribir un Mensaje sin saber a qué Negocio pertenece. "
            f"No se asume ningún Negocio por defecto (Gate 5.5)."
        )
    async with async_session() as session:
        # Gate 5.5 — conversation_id resuelto vía la cadena Contact→
        # Conversation YA scoped por negocio_id (mismos helpers que usa
        # resolver_conversation_activa) — reemplaza al bridge global
        # `_obtener_conversation_activa_por_telefono` (que seguía resolviendo
        # desde `Lead.telefono`, sin candado). Get-only (no crea Contact/
        # Conversation acá) — si todavía no existen PARA ESTE Negocio, el
        # mensaje se guarda igual con conversation_id=None (columna nullable
        # durante EXPAND, ver Mensaje) y queda entre los "REQUIERE
        # RESOLUCIÓN" del backfill si nunca llega a crearse la Conversation.
        contact = await _obtener_contact(session, negocio_id, telefono)
        conversation = await _obtener_conversation_activa(session, contact.id) if contact else None
        ahora = datetime.utcnow()
        mensaje = Mensaje(
            telefono=telefono,
            negocio_id=negocio_id,
            conversation_id=conversation.id if conversation else None,
            role=role,
            content=content,
            timestamp=ahora,
            archivo_id=archivo_id,
            via_app=via_app,
            mensaje_id_meta=mensaje_id_meta,
            estado_envio=estado_envio,
            respondido_a_id=respondido_a_id,
        )
        session.add(mensaje)
        if conversation is not None:
            # 2026-09-17, hallazgo del usuario: en la Bandeja de Conversaciones
            # (orden = actualizado DESC, paginada) un chat con mensajes nuevos
            # no se reordenaba al tope — ni mostraba la bolita de pendientes —
            # hasta abrir esa conversación. `guardar_mensaje` nunca tocaba
            # `Conversation.actualizado` (solo lo hacen resolver_conversation_
            # activa al crear/cerrar, o acciones explícitas como asignar/
            # reactivar); un chat activo que solo recibe mensajes nuevos podía
            # quedar con un `actualizado` cada vez más viejo, cayendo fuera de
            # la página 1 en cuanto hubiera suficientes conversaciones más
            # "recientes" (de verdad) por delante — ahí la fila ni se reordena
            # ni el badge de pendientes es visible, porque la fila entera deja
            # de traerse. Cada mensaje (cliente, Gabi o asesor) ahora cuenta
            # como actividad real de la conversación.
            conversation.actualizado = ahora
            # 2026-10-03 — la Bandeja ordena y muestra ESTA hora, no
            # `actualizado` (que también se mueve al asignar, rotar, liberar
            # o cerrar por Cron). Solo un mensaje real la mueve.
            conversation.ultimo_mensaje_en = ahora
        # Punto 2 (2026-09-30) — un asesor respondiendo de verdad (desde el
        # panel, o el echo de coexistencia cuando responde directo desde la
        # app de WhatsApp Business) desarma el reloj de rotación por
        # inactividad para siempre en este ciclo — ver `Lead.derivado_en` y
        # `listar_leads_para_rotar_o_liberar`. Nunca se reactiva por un
        # cambio de resultado después: solo una respuesta real, o una
        # reasignación manual (`asignar_asesor_a_lead`, automatico=False),
        # apagan este reloj.
        if role == "asesor" or (role == "assistant" and via_app):
            lead = await session.get(Lead, telefono)
            if lead is not None and lead.derivado_en is not None:
                lead.derivado_en = None
        await session.commit()
        await session.refresh(mensaje)
        return {
            "id": mensaje.id, "telefono": mensaje.telefono, "role": mensaje.role,
            "content": mensaje.content, "archivo_id": mensaje.archivo_id, "via_app": mensaje.via_app,
            "mensaje_id_meta": mensaje.mensaje_id_meta, "estado_envio": mensaje.estado_envio,
            "respondido_a_id": mensaje.respondido_a_id, "conversation_id": mensaje.conversation_id,
            "timestamp": mensaje.timestamp,
        }


async def obtener_mensaje_por_id(mensaje_id: int) -> dict | None:
    """Un mensaje puntual por su id interno — usado para validar una cita
    (Reply/Quote, ver responder_cliente en dashboard.py): hay que confirmar
    que el mensaje pertenece a la misma conversación que se le está citando
    y que tiene mensaje_id_meta (el wamid real de Meta) antes de poder
    armar el `context` del envío saliente."""
    async with async_session() as session:
        mensaje = await session.get(Mensaje, mensaje_id)
        if mensaje is None:
            return None
        return {
            "id": mensaje.id, "telefono": mensaje.telefono, "role": mensaje.role,
            "content": mensaje.content, "mensaje_id_meta": mensaje.mensaje_id_meta,
            "estado_envio": mensaje.estado_envio, "timestamp": mensaje.timestamp,
        }


async def obtener_timestamp_ultimo_mensaje_usuario(telefono: str) -> datetime | None:
    """Instante del último mensaje con role=='user' (el cliente escribió) de
    este lead — para calcular si la ventana de atención de 24 horas de
    WhatsApp sigue abierta antes de intentar un envío saliente. Meta
    rechaza cualquier mensaje libre (no-plantilla) fuera de esa ventana; sin
    este chequeo, ese rechazo se veía como el mismo 502 genérico de
    cualquier otra falla de la API (token vencido, etc.).

    Gate 5.3 — corrección pequeña: `Mensaje.negocio_id` ya existe desde
    Gate 5.2 pero esta consulta no lo usaba (mismo hallazgo que
    `obtener_historial`/`limpiar_historial`). Se agrega como filtro
    adicional — defensa en profundidad, no cambia el resultado hoy (un
    teléfono sigue siendo único por Lead), pero cierra el mismo patrón de
    "columna presente, filtro ausente" ya corregido en el resto del Gate.

    2026-10-06 — REGLA ÚNICA sobre las reacciones ("Reaccionó con 👍"): NO cuentan
    como mensaje del cliente. Inicio ya las ignoraba, pero esta función las
    contaba, y no consta en la documentación de Meta que una reacción abra o
    renueve la ventana de servicio de 24 h. Lo prudente es no contarlas para
    PERMITIR texto libre: si en la práctica Meta sí la abriera, lo peor que pasa
    es que el panel ofrezca la plantilla de más; al revés, el asesor escribiría
    libre y Meta rechazaría el envío (error 131047)."""
    async with async_session() as session:
        lead = await session.get(Lead, telefono)
        if lead is None:
            return None
        query = (
            select(Mensaje.timestamp)
            .where(
                Mensaje.telefono == telefono, Mensaje.negocio_id == lead.negocio_id, Mensaje.role == "user",
                ~func.coalesce(Mensaje.content, "").startswith(_PREFIJO_REACCION),
            )
            .order_by(Mensaje.timestamp.desc())
            .limit(1)
        )
        result = await session.execute(query)
        return result.scalar_one_or_none()


# ── Estado de la ventana de WhatsApp de un cliente (2026-10-06, P3) ─────────────────────
# Responde, para un cliente, "¿puedo escribirle libre o solo con plantilla?" y "¿lo que
# le mande hoy sería gratis por ser de un anuncio?". Solo lectura, sin migración.
#
# Hechos de Meta (doc oficial leída el 2026-10-06):
#  - La ventana de servicio de 24 h se abre o renueva SOLO con un mensaje del CLIENTE. Con
#    ella cerrada solo se pueden mandar plantillas aprobadas, nunca texto libre.
#  - La ventana gratuita de 72 h de los anuncios Click-to-WhatsApp (Free Entry Point) es de
#    PRECIO, no de permiso: la abre NUESTRA respuesta dentro de las 24 h del mensaje del
#    anuncio y, dentro de ella, todos los mensajes (también las plantillas) salen gratis. El
#    texto libre sigue exigiendo las 24 h.
VENTANA_SERVICIO_HORAS = 24


async def obtener_estado_ventana(
    telefono: str, negocio_id: str | None = None, ahora: datetime | None = None, con_fep: bool = True,
) -> dict:
    """Estado de la ventana de WhatsApp de un cliente. `negocio_id` se resuelve desde el lead si
    no se pasa; un teléfono sin lead queda todo cerrado. Fechas en UTC naive (usar `iso_utc`).

    Devuelve: ventana_24h_abierta, vence_en (fin de las 24 h, o None), ultimo_mensaje_cliente_en,
    fep_abierta, fep_vence_en, fep_origen ("visto" | "por_abrir" | None), puede_texto_libre,
    puede_plantilla, negocio_id (el resuelto).

    `fep_abierta` = un envío AHORA caería en el intervalo gratuito de un anuncio. Dos señales (las
    mismas de `politica_envios._ventana_de_anuncio_abierta`, que decide el costo real): (1) Meta ya
    marcó como `free_entry_point` mensajes recientes a este cliente → la ventana va desde el primero
    de la racha hasta +`meta_fep_horas` (72 por defecto) y `fep_vence_en` es ese instante
    (`fep_origen="visto"`); (2) el cliente llegó por anuncio hace menos de 24 h y nadie le ha
    respondido → nuestra respuesta la abrirá (`fep_origen="por_abrir"`, sin `fep_vence_en`: aún no
    empezó a correr).

    Reacciones: no cuentan como mensaje del cliente (ver `obtener_timestamp_ultimo_mensaje_usuario`).
    `puede_plantilla` es siempre verdadero: Meta permite una plantilla aprobada en cualquier momento;
    si hay una configurada lo decide la capa del panel (`plantilla_disponible`).

    `con_fep=False` salta las consultas de anuncio (camino de envío, donde solo importa la ventana de
    24 h): `fep_abierta` queda en False, sin que signifique "no hay anuncio"."""
    ahora = ahora or datetime.utcnow()
    cerrado = {
        "ventana_24h_abierta": False, "vence_en": None, "ultimo_mensaje_cliente_en": None,
        "fep_abierta": False, "fep_vence_en": None, "fep_origen": None,
        "puede_texto_libre": False, "puede_plantilla": True, "negocio_id": negocio_id,
    }
    if negocio_id is None:
        async with async_session() as session:
            lead = await session.get(Lead, telefono)
        if lead is None:
            return cerrado
        negocio_id = lead.negocio_id
        cerrado["negocio_id"] = negocio_id
    horas_fep = (_a_numero(await obtener_configuracion("meta_fep_horas", "72", negocio_id=negocio_id), 72) or 72) if con_fep else 72

    async with async_session() as session:
        ultimo = (await session.execute(
            select(func.max(Mensaje.timestamp)).where(
                Mensaje.telefono == telefono, Mensaje.negocio_id == negocio_id, Mensaje.role == "user",
                ~func.coalesce(Mensaje.content, "").startswith(_PREFIJO_REACCION),
            )
        )).scalar_one_or_none()
        vence = ultimo + timedelta(hours=VENTANA_SERVICIO_HORAS) if ultimo else None
        abierta = bool(vence and vence > ahora)
        if not con_fep:
            return {
                "ventana_24h_abierta": abierta, "vence_en": vence if abierta else None, "ultimo_mensaje_cliente_en": ultimo,
                "fep_abierta": False, "fep_vence_en": None, "fep_origen": None,
                "puede_texto_libre": abierta, "puede_plantilla": True, "negocio_id": negocio_id,
            }

        # (1) Racha de mensajes que Meta marcó como Free Entry Point. Se agrupan en ventanas de
        # `horas_fep` desde el primer mensaje de cada una y se mira la última.
        instantes = [
            t for t in (await session.execute(
                select(func.coalesce(UsoMensajeMeta.entregado_en, UsoMensajeMeta.enviado_en))
                .where(
                    UsoMensajeMeta.negocio_id == negocio_id, UsoMensajeMeta.destinatario == telefono,
                    UsoMensajeMeta.pricing_type == "free_entry_point",
                    func.coalesce(UsoMensajeMeta.entregado_en, UsoMensajeMeta.enviado_en) >= ahora - timedelta(hours=2 * horas_fep),
                ).order_by(func.coalesce(UsoMensajeMeta.entregado_en, UsoMensajeMeta.enviado_en))
            )).scalars().all() if t is not None
        ]
        fep_vence, inicio = None, None
        for t in instantes:
            if inicio is None or t - inicio > timedelta(hours=horas_fep):
                inicio = t
        if inicio is not None:
            fep_vence = inicio + timedelta(hours=horas_fep)
        fep_abierta = bool(fep_vence and fep_vence > ahora)
        fep_origen = "visto" if fep_abierta else None
        if not fep_abierta:
            fep_vence = None
            # (2) Llegó por anuncio hace menos de 24 h y nadie le ha respondido todavía.
            clic = (await session.execute(
                select(func.max(AttributionEvent.creado)).where(
                    AttributionEvent.negocio_id == negocio_id, AttributionEvent.lead_telefono == telefono,
                    AttributionEvent.tipo_origen.in_(("meta_ads", "meta_ads_no_resuelto")),
                    AttributionEvent.creado >= ahora - timedelta(hours=VENTANA_SERVICIO_HORAS),
                )
            )).scalar_one_or_none()
            if clic is not None:
                respondido = (await session.execute(
                    select(Mensaje.id).where(
                        Mensaje.negocio_id == negocio_id, Mensaje.telefono == telefono, Mensaje.timestamp >= clic,
                        Mensaje.role.in_(("assistant", "asesor")), Mensaje.via_app.is_(False),
                    ).limit(1)
                )).scalar_one_or_none()
                if respondido is None:
                    fep_abierta, fep_origen = True, "por_abrir"

    return {
        "ventana_24h_abierta": abierta, "vence_en": vence if abierta else None, "ultimo_mensaje_cliente_en": ultimo,
        "fep_abierta": fep_abierta, "fep_vence_en": fep_vence, "fep_origen": fep_origen,
        "puede_texto_libre": abierta, "puede_plantilla": True, "negocio_id": negocio_id,
    }


async def obtener_historial(telefono: str, limite: int = 20) -> list[dict]:
    """
    Recupera los últimos N mensajes de una conversación.

    Args:
        telefono: Número de teléfono del cliente
        limite: Máximo de mensajes a recuperar (default: 20)

    Returns:
        Lista de diccionarios con role y content

    Gate 5.3 — corrección pequeña: agrega `Mensaje.negocio_id` como filtro
    (ya existe la columna desde Gate 5.2, esta consulta no la usaba —
    defensa en profundidad, no cambia el resultado hoy).
    """
    async with async_session() as session:
        lead = await session.get(Lead, telefono)
        query = (
            select(Mensaje)
            .where(Mensaje.telefono == telefono)
            .order_by(Mensaje.timestamp.desc())
            .limit(limite)
        )
        if lead is not None:
            query = query.where(Mensaje.negocio_id == lead.negocio_id)
        result = await session.execute(query)
        mensajes = result.scalars().all()

        # Invertir para orden cronológico (los más antiguos quedan primero)
        mensajes.reverse()

        # Segunda consulta liviana (no N+1) solo para saber si cada adjunto
        # es audio (se reproduce inline) o documento/imagen (se descarga) —
        # el chat en vivo lo necesita para pintar la burbuja correcta.
        archivo_ids = {m.archivo_id for m in mensajes if m.archivo_id}
        content_types: dict[int, str] = {}
        if archivo_ids:
            query_archivos = select(ArchivoAdjunto.id, ArchivoAdjunto.content_type).where(ArchivoAdjunto.id.in_(archivo_ids))
            result_archivos = await session.execute(query_archivos)
            content_types = dict(result_archivos.all())

        # Tercera consulta liviana (no N+1), misma idea que archivo_ids
        # arriba: trae de una sola vez el autor+contenido de cada mensaje
        # citado (Reply/Quote) que aparece en esta página — el mensaje
        # original puede estar fuera de la ventana `limite` (una cita a
        # algo dicho hace rato), así que no alcanza con buscarlo entre
        # `mensajes`. Si el citado ya no existe (borrado, caso raro) su id
        # simplemente no aparece acá y el campo `mensaje_citado` sale None
        # más abajo — no rompe nada.
        citado_ids = {m.respondido_a_id for m in mensajes if m.respondido_a_id}
        citados: dict[int, tuple[str, str]] = {}
        if citado_ids:
            query_citados = select(Mensaje.id, Mensaje.role, Mensaje.content).where(Mensaje.id.in_(citado_ids))
            result_citados = await session.execute(query_citados)
            citados = {fila.id: (fila.role, fila.content) for fila in result_citados}

        return [
            {
                # `id` interno — clave estable para que el frontend pueda
                # referenciar ESTE mensaje puntual (citarlo con Reply/Quote,
                # ver obtener_mensaje_por_id, o mostrar su opción de
                # reintento si estado_envio=="fallido"). No viajaba antes
                # porque nada lo necesitaba.
                "id": msg.id,
                "role": msg.role, "content": msg.content, "archivo_id": msg.archivo_id,
                "archivo_tipo": content_types.get(msg.archivo_id), "via_app": msg.via_app,
                # wamid de Meta (ver Mensaje.mensaje_id_meta) — nulo si el
                # mensaje es anterior a este campo o si un envío saliente
                # falló. El frontend lo necesita para poder citar ESTE
                # mensaje desde otro (Reply/Quote); si es nulo, la cita debe
                # deshabilitarse en la UI (el backend la rechaza igual si se
                # intenta, ver responder_cliente).
                "mensaje_id_meta": msg.mensaje_id_meta,
                # "fallido" si este envío saliente no se pudo confirmar con
                # Meta — el frontend lo usa para ofrecer reintentar. None en
                # cualquier otro caso (entrante, o saliente exitoso).
                "estado_envio": msg.estado_envio,
                # Instante real del mensaje, con sufijo `Z` (ver iso_utc): sin
                # él, `new Date()` en el navegador lo lee como hora local y en
                # Lima aparece ~5 h adelantado. El campo ya existía en la
                # tabla, simplemente no se exponía — quien consume esta lista
                # (chat del panel, /mensajes.json) no tenía forma de fechar un
                # mensaje.
                "timestamp": iso_utc(msg.timestamp),
                # Vista previa del mensaje que ESTE mensaje citó al enviarse
                # (Reply/Quote) — resuelto contra `citados` arriba. `None` si
                # este mensaje no citó nada, o si citó algo que ya no existe.
                # `BurbujaMensaje` (maiek-frontend) ya sabe pintar esta forma
                # exacta ({autor, extracto}); antes de este campo siempre
                # llegaba `undefined` y ningún mensaje mostraba la cita.
                "mensaje_citado": (
                    {"autor": citados[msg.respondido_a_id][0], "extracto": _extracto_cita(citados[msg.respondido_a_id][1])}
                    if msg.respondido_a_id and msg.respondido_a_id in citados
                    else None
                ),
            }
            for msg in mensajes
        ]


LARGO_EXTRACTO_CITA = 160


def _extracto_cita(content: str) -> str:
    """Recorta el contenido del mensaje citado antes de mandarlo al
    frontend — la burbuja solo necesita una vista previa corta (la UI ya la
    trunca visualmente a una línea), no el mensaje completo, que puede ser
    un párrafo largo."""
    content = content or ""
    if len(content) <= LARGO_EXTRACTO_CITA:
        return content
    return content[:LARGO_EXTRACTO_CITA].rstrip() + "…"


async def _construir_historial_mensajes(session, conversation_id: str, negocio_id: str, limite: int) -> list[dict]:
    """Cuerpo de `obtener_historial_de_conversation`, extraído para
    reusarse DENTRO de una sesión ya abierta (Gate 2026-09-23 —
    `listar_conversaciones_previas_con_historial` necesita construir el
    mismo dict para varias Conversation en una sola sesión, sin abrir N
    sesiones nuevas)."""
    query = (
        select(Mensaje)
        .where(Mensaje.conversation_id == conversation_id, Mensaje.negocio_id == negocio_id)
        .order_by(Mensaje.timestamp.desc())
        .limit(limite)
    )
    result = await session.execute(query)
    mensajes = result.scalars().all()
    mensajes.reverse()

    archivo_ids = {m.archivo_id for m in mensajes if m.archivo_id}
    content_types: dict[int, str] = {}
    if archivo_ids:
        query_archivos = select(ArchivoAdjunto.id, ArchivoAdjunto.content_type).where(ArchivoAdjunto.id.in_(archivo_ids))
        result_archivos = await session.execute(query_archivos)
        content_types = dict(result_archivos.all())

    citado_ids = {m.respondido_a_id for m in mensajes if m.respondido_a_id}
    citados: dict[int, tuple[str, str]] = {}
    if citado_ids:
        query_citados = select(Mensaje.id, Mensaje.role, Mensaje.content).where(Mensaje.id.in_(citado_ids))
        result_citados = await session.execute(query_citados)
        citados = {fila.id: (fila.role, fila.content) for fila in result_citados}

    return [
        {
            "id": msg.id,
            "role": msg.role, "content": msg.content, "archivo_id": msg.archivo_id,
            "archivo_tipo": content_types.get(msg.archivo_id), "via_app": msg.via_app,
            "mensaje_id_meta": msg.mensaje_id_meta,
            "estado_envio": msg.estado_envio,
            "timestamp": iso_utc(msg.timestamp),
            "mensaje_citado": (
                {"autor": citados[msg.respondido_a_id][0], "extracto": _extracto_cita(citados[msg.respondido_a_id][1])}
                if msg.respondido_a_id and msg.respondido_a_id in citados
                else None
            ),
        }
        for msg in mensajes
    ]


async def obtener_historial_de_conversation(conversation_id: str, negocio_id: str, limite: int = 20) -> list[dict]:
    """GATE 2.2 (Conversation ID Cutover) — equivalente de `obtener_historial`
    pero filtrado por `Mensaje.conversation_id` en vez de `Mensaje.telefono`.

    `obtener_historial(telefono)` NO se toca ni se llama desde acá — sigue
    existiendo tal cual para el panel legacy. El problema que resuelve esta
    función nueva: un mismo Contact puede tener varias Conversation
    SUCESIVAS (DR-4, Gate 5.3) que comparten el mismo `telefono` — filtrar
    por `telefono` mezcla el historial de una Conversation ya cerrada con el
    de la nueva. `Mensaje.conversation_id` ya se graba correctamente en cada
    mensaje desde Gate 5.5 (`guardar_mensaje`), así que alcanza con filtrar
    por la columna correcta — no hace falta backfill (Gate 2.1, validado
    contra producción: 103/103 mensajes con conversation_id, 0 NULL).

    `negocio_id` es obligatorio y viene YA resuelto por quien llama (la
    ruta HTTP, desde la sesión) — nunca se infiere de `Lead` ni de ningún
    otro bridge, a diferencia de `obtener_historial` (que todavía depende
    de `Lead.telefono` para resolverlo)."""
    async with async_session() as session:
        return await _construir_historial_mensajes(session, conversation_id, negocio_id, limite)


async def listar_conversaciones_previas_con_historial(
    conversation_id: str, negocio_id: str, limite_conversaciones: int = 3, limite_mensajes_cada_una: int = 50,
) -> list[dict]:
    """Gate 2026-09-23 (punto b del hallazgo DR-4) — Conversation(s) CERRADAS
    anteriores del mismo Contact que `conversation_id`, cada una con su
    propio historial, para que el panel de chat las muestre como contexto
    por ENCIMA de la conversación activa (bloques separados, con su propio
    divisor visual) — nunca fusionadas dentro del mismo array de mensajes.

    Deliberadamente NO toca nada del modelo de datos: `Opportunity`,
    atribución de campaña y la Bandeja de Conversaciones (`estado ==
    "activa"`) siguen exactamente igual que hoy (Gate 2.2/5.3) — esto es
    solo una vista de LECTURA adicional para que el asesor no pierda el
    hilo cuando el cliente vuelve tras un cierre definitivo (DR-4).

    Ordenadas de más antigua a más reciente (orden de lectura real).
    `limite_conversaciones` acota cuántas Conversation previas trae (las
    más recientes primero, se invierte después) — un Contact con muchos
    ciclos comerciales no debería inflar la respuesta indefinidamente.
    Una Conversation previa sin ningún mensaje real (no debería pasar, pero
    fail-safe) se omite en vez de mandar un bloque vacío."""
    async with async_session() as session:
        actual = await session.get(Conversation, conversation_id)
        if actual is None or actual.negocio_id != negocio_id:
            return []

        query = (
            select(Conversation)
            .where(
                Conversation.contact_id == actual.contact_id,
                Conversation.negocio_id == negocio_id,
                Conversation.id != conversation_id,
                Conversation.estado == "cerrada",
            )
            .order_by(Conversation.creado.desc())
            .limit(limite_conversaciones)
        )
        previas = (await session.execute(query)).scalars().all()
        previas = list(reversed(previas))

        resultado = []
        for conv in previas:
            mensajes = await _construir_historial_mensajes(session, conv.id, negocio_id, limite_mensajes_cada_una)
            if not mensajes:
                continue
            resultado.append({
                "conversation_id": conv.id,
                "cerrado_definitivamente_en": iso_utc(conv.cerrado_definitivamente_en),
                "actualizado": iso_utc(conv.actualizado),
                "mensajes": mensajes,
            })
        return resultado


async def obtener_ultimos_mensajes(telefonos: list[str], negocio_id: str) -> dict[str, dict]:
    """Último mensaje de cada teléfono (para la vista previa en la bandeja),
    en una sola consulta para toda la lista visible — no una por lead en un
    loop (mismo problema de N consultas que contar_leads_activos_por_asesor).

    Usa row_number() por teléfono en vez de traer todos los mensajes y
    quedarse con el primero en Python — un lead con una conversación larga
    (cientos de mensajes) habría traído toda esa historia solo para
    descartarla, lo cual es justo el mismo tipo de desperdicio que se
    intentaba evitar. row_number() funciona igual en SQLite y Postgres.

    `negocio_id` (Gate 5.4, T2): esta consulta nunca filtraba por negocio_id
    — un teléfono ajeno colado en `telefonos` (bug de otro lado) habría
    devuelto el último mensaje de un Negocio distinto. Mensaje.negocio_id ya
    es NOT NULL (Gate 5.2, H1), así que el filtro es directo en la fila,
    nunca por JOIN indirecto."""
    if not telefonos:
        return {}
    async with async_session() as session:
        fila = (
            func.row_number()
            .over(partition_by=Mensaje.telefono, order_by=Mensaje.timestamp.desc())
            .label("fila")
        )
        subconsulta = (
            select(Mensaje)
            .where(Mensaje.telefono.in_(telefonos), Mensaje.negocio_id == negocio_id)
            .add_columns(fila)
            .subquery()
        )
        ultimo_por_telefono = aliased(Mensaje, subconsulta)
        query = select(ultimo_por_telefono).where(subconsulta.c.fila == 1)
        result = await session.execute(query)
        return {
            msg.telefono: {"role": msg.role, "content": msg.content, "timestamp": msg.timestamp}
            for msg in result.scalars().all()
        }


def _lead_a_dict(lead: Lead) -> dict:
    return {
        "telefono": lead.telefono,
        "negocio_id": lead.negocio_id,
        "nombre": lead.nombre,
        "interes": lead.interes,
        "producto_tipo": lead.producto_tipo,
        "producto_marca": lead.producto_marca,
        "producto_modalidad": lead.producto_modalidad,
        "paso_flujo": lead.paso_flujo,
        "resultado": lead.resultado,
        "fecha_agendada": lead.fecha_agendada,
        "fecha_cierre": lead.fecha_cierre,
        "asesor_asignado": lead.asesor_asignado,
        "pausado_manual": lead.pausado_manual,
        "escalado_supervision_en": lead.escalado_supervision_en,
        "cerrado_definitivamente_en": lead.cerrado_definitivamente_en,
        "producto_vendido": lead.producto_vendido,
        "precio_venta": lead.precio_venta,
        "marca_venta": lead.marca_venta,
        "proveedor_venta": lead.proveedor_venta,
        "modalidad_pago": lead.modalidad_pago,
        "cuotas": lead.cuotas,
        "monto_financiado": lead.monto_financiado,
        "cuota_pactada": lead.cuota_pactada,
        "tea_pactada": lead.tea_pactada,
        "igv_pactado": lead.igv_pactado,
        "medio_pago": lead.medio_pago,
        "visto_asesor": lead.visto_asesor,
        "revision_prioritaria": lead.revision_prioritaria,
        "version": lead.version,
        "fallos_tecnicos": lead.fallos_tecnicos,
        "campana_origen": lead.campana_origen,
        "origen_contacto": lead.origen_contacto,
        "numero_whatsapp_id": lead.numero_whatsapp_id,
        "actualizado": lead.actualizado,
        "creado": lead.creado,
    }


async def obtener_lead(telefono: str, negocio_id: str | None = None) -> dict | None:
    """Recupera los datos estructurados conocidos de un cliente, si existen.

    Gate 5.4 (T1) — `negocio_id`, igual criterio que `actualizar_lead()`:
    explícito en la firma, NUNCA inferido. Si se pasa, es el candado de
    ownership — si el Lead existe pero pertenece a otro Negocio, retorna
    `None` (mismo comportamiento que "no existe": 404, no 403 — no
    confirma la existencia del recurso a quien no tiene acceso). Todo
    llamador con contexto de autorización (rutas HTTP, WebSocket del
    panel) DEBE pasarlo — es la corrección central del hallazgo T1
    (Arquitectura Integrada Gate 5.4): `Lead.telefono` es la PK, pero
    nunca fue el único candado.

    `negocio_id=None` (default) preserva el comportamiento anterior —
    reservado a los pocos llamadores internos del webhook (`agent/main.py`,
    `agent/campanas.py`) que están resolviendo el `negocio_id` de ESTE
    mismo teléfono a partir de un Canal ya identificado, no verificando el
    acceso de un tercero: no hay "otro usuario" que pueda explotar esa
    ausencia de candado, así que no es el mismo riesgo que en una ruta
    HTTP/WS con sesión. Nunca usar `negocio_id=None` desde un endpoint
    autenticado."""
    async with async_session() as session:
        lead = await session.get(Lead, telefono)
        if lead is None:
            return None
        if negocio_id is not None and lead.negocio_id != negocio_id:
            return None
        return _lead_a_dict(lead)


async def listar_leads(negocio_id: str, asesor_asignado: str | None = None) -> list[dict]:
    """Recupera los leads, del más recientemente actualizado al más antiguo.
    Si se pasa asesor_asignado, solo trae los leads asignados a ese asesor.

    `negocio_id` (Gate 5.4, T2 — mismo hallazgo que listar_leads_pipeline en
    Gate 5.3): esta consulta NUNCA filtraba por negocio_id. Ahora es
    obligatorio, resuelto server-side desde la sesión — nunca del cliente."""
    async with async_session() as session:
        query = select(Lead).where(Lead.negocio_id == negocio_id).order_by(Lead.actualizado.desc())
        if asesor_asignado:
            query = query.where(Lead.asesor_asignado == asesor_asignado)
        result = await session.execute(query)
        return [_lead_a_dict(lead) for lead in result.scalars().all()]


COLUMNAS_ORDEN_PIPELINE = {
    "nombre": Lead.nombre,
    "resultado": Lead.resultado,
    "asesor": Lead.asesor_asignado,
    "actualizado": Lead.actualizado,
    "creado": Lead.creado,
}


async def _conversation_ids_por_telefono(session, negocio_id: str, telefonos: list[str]) -> dict[str, str]:
    """Resuelve en bloque (no N+1) el `conversation_id` ACTIVO de cada
    teléfono, doblemente candado por `negocio_id` — GATE 3.1 (Inicio):
    extraída tal cual del bloque que ya usaba `listar_leads_pipeline` (Gate
    5.3 cutover real §8) para que Inicio use la MISMA lógica en vez de
    reimplementarla. Un teléfono sin Conversation todavía (no backfilleado
    / no pasó por el webhook) simplemente no aparece en el dict — quien
    llama decide el fallback (mismo criterio que `_dto_lead_pipeline`)."""
    if not telefonos:
        return {}
    filas = (await session.execute(
        select(Contact.telefono, Conversation.id)
        .join(Conversation, Conversation.contact_id == Contact.id)
        .where(
            Contact.negocio_id == negocio_id, Contact.telefono.in_(telefonos),
            Conversation.negocio_id == negocio_id, Conversation.estado == "activa",
        )
    )).all()
    return {telefono: conversation_id for telefono, conversation_id in filas}


async def resolver_conversation_ids_por_telefono(negocio_id: str, telefonos: list[str]) -> dict[str, str]:
    """Envoltorio público de `_conversation_ids_por_telefono` (arriba) — abre
    su propia sesión, para llamadores que no tienen una ya abierta (GATE 3.1:
    `agent/dashboard.py`, Inicio). `listar_leads_pipeline` sigue usando la
    versión privada directo, porque ya tiene la sesión abierta."""
    async with async_session() as session:
        return await _conversation_ids_por_telefono(session, negocio_id, telefonos)


async def listar_leads_pipeline(
    negocio_id: str,
    asesor_asignado: str | None = None,
    resultado: str | None = None,
    busqueda: str = "",
    interes: str | None = None,
    orden: str = "actualizado",
    direccion: str = "desc",
    pagina: int = 1,
    por_pagina: int = 20,
) -> tuple[list[dict], int]:
    """Consulta para CRM/Pipeline (MAIEK_AI_PRODUCT_PATTERNS.md, Cap. 6) — a
    diferencia de listar_leads (que siempre trae todo y deja orden/paginación
    al cliente), acá se resuelven en el servidor para que puedan persistirse
    como parámetros de la URL. Función independiente a propósito — duplica
    parte de listar_leads en vez de generalizarla, mismo criterio del Sprint 2
    de aceptar duplicación temporal antes que abstraer un Data Grid que
    todavía está evolucionando. Retorna (leads de la página, total sin paginar).

    `interes` es un filtro aparte de `busqueda`: `busqueda` es la búsqueda
    global (nombre OR teléfono OR interés) y `interes` acota SOLO por esa
    columna, para que la API JSON pueda combinar ambas cosas (buscar "Ana"
    dentro de los leads interesados en "cocina"). Es ILIKE por contiene y no
    igualdad porque `Lead.interes` es texto libre que escribe la IA, no una
    lista cerrada de valores como `resultado`.

    `negocio_id` (Gate 5.3 cutover real §18 — hallazgo de la auditoría
    adversarial): esta consulta NUNCA filtraba por negocio_id — un
    admin/supervisor con `alcance=todos` veía el Pipeline de TODOS los
    Negocios, no solo el propio (`_alcance_pipeline` solo acota por asesor,
    nunca por negocio_id). Ahora es un parámetro obligatorio, resuelto
    server-side por el router desde la sesión — nunca del cliente."""
    columna = COLUMNAS_ORDEN_PIPELINE.get(orden, Lead.actualizado)
    async with async_session() as session:
        query = select(Lead).where(Lead.negocio_id == negocio_id)
        if asesor_asignado:
            query = query.where(Lead.asesor_asignado == asesor_asignado)
        if resultado:
            query = query.where(Lead.resultado == resultado)
        if interes:
            query = query.where(Lead.interes.ilike(f"%{interes}%"))
        if busqueda:
            patron = f"%{busqueda}%"
            query = query.where(
                Lead.nombre.ilike(patron) | Lead.telefono.ilike(patron) | Lead.interes.ilike(patron)
            )

        total = (await session.execute(select(func.count()).select_from(query.subquery()))).scalar_one()

        orden_columna = columna.asc() if direccion == "asc" else columna.desc()
        query = query.order_by(orden_columna).offset((pagina - 1) * por_pagina).limit(por_pagina)
        result = await session.execute(query)
        leads = [_lead_a_dict(lead) for lead in result.scalars().all()]

        # Gate 5.3 cutover real §8 — Pipeline deja de exponer `telefono` como
        # `id`: se resuelve en bloque (no N+1) el conversation_id ACTIVO de
        # cada telefono, doblemente candado por negocio_id. Un lead sin
        # Conversation todavía (no backfilleado / no pasó por el webhook) no
        # se inventa ninguna — su fila sigue navegando por telefono como
        # fallback (ver _dto_lead_pipeline). Gate 3.1: extraído a
        # _conversation_ids_por_telefono() para que Inicio reuse la misma
        # lógica — este call site queda con el mismo resultado de siempre.
        telefonos = [l["telefono"] for l in leads]
        conversation_id_por_telefono = await _conversation_ids_por_telefono(session, negocio_id, telefonos)

        for l in leads:
            l["conversation_id"] = conversation_id_por_telefono.get(l["telefono"])
        return leads, total


# ── Casos ya gestionados (2026-10-06, paquete P1) ───────────────────────
#
# Inicio y la campana mostraban como pendientes casos que alguien ya resolvió
# (un lead cerrado definitivamente, un cliente al que un humano ya le contestó
# por el celular). REGLA ÚNICA: se decide por TIMESTAMP, nunca por un booleano
# suelto — "el cierre es igual o posterior al último mensaje real del cliente"
# saca el caso; si el cliente escribe DESPUÉS del cierre, vuelve a aparecer. Un
# mensaje real excluye las reacciones (`PREFIJO_REACCION`).

def _cierre_vigente(*cierres: datetime | None) -> datetime | None:
    """El cierre definitivo más reciente entre Lead y Conversation (los dos se
    escriben juntos, pero uno puede quedar sin espejo)."""
    validos = [c for c in cierres if c is not None]
    return max(validos) if validos else None


def cierre_cubre_mensaje(cierre: datetime | None, ultimo_cliente: datetime | None) -> bool:
    """True si el cierre definitivo es igual o posterior al último mensaje real
    del cliente (o el cliente nunca escribió): el caso ya está gestionado."""
    if cierre is None:
        return False
    return ultimo_cliente is None or cierre >= ultimo_cliente


def humano_atendio(ultimo_humano: datetime | None, ultimo_cliente: datetime | None) -> bool:
    """True si un humano (asesor, o la línea escrita desde el celular) escribió
    igual o después del último mensaje real del cliente."""
    if ultimo_humano is None:
        return False
    return ultimo_cliente is None or ultimo_humano >= ultimo_cliente


async def _estado_atencion_por_telefono(session, negocio_id: str, telefonos: list[str]) -> dict[str, dict]:
    """Por teléfono: `ultimo_cliente` (último mensaje real del cliente),
    `ultimo_humano` (último mensaje de un asesor, o de la línea escrito desde
    la app del celular: `role == "assistant"` con `via_app`; un envío fallido
    no cuenta como respuesta), `conversaciones` (cuántas tiene), `hay_activa` y
    `cierre_conversacion` (cierre definitivo de la Conversation activa). Tres
    consultas agrupadas para toda la lista, sin N+1."""
    if not telefonos:
        return {}
    no_reaccion = ~func.coalesce(Mensaje.content, "").startswith(PREFIJO_REACCION)
    base = (Mensaje.negocio_id == negocio_id, Mensaje.telefono.in_(telefonos), no_reaccion)
    clientes = {
        t: ts for t, ts in (await session.execute(
            select(Mensaje.telefono, func.max(Mensaje.timestamp)).where(*base, Mensaje.role == "user").group_by(Mensaje.telefono)
        )).all()
    }
    es_humano = sa_or(Mensaje.role == "asesor", sa_and(Mensaje.role == "assistant", Mensaje.via_app.is_(True)))
    humanos = {
        t: ts for t, ts in (await session.execute(
            select(Mensaje.telefono, func.max(Mensaje.timestamp))
            .where(*base, es_humano, func.coalesce(Mensaje.estado_envio, "") != "fallido")
            .group_by(Mensaje.telefono)
        )).all()
    }
    filas = (await session.execute(
        select(Contact.telefono, Conversation.estado, Conversation.cerrado_definitivamente_en)
        .join(Conversation, Conversation.contact_id == Contact.id)
        .where(
            Contact.negocio_id == negocio_id, Conversation.negocio_id == negocio_id, Contact.telefono.in_(telefonos),
        )
    )).all()
    estado = {
        t: {
            "ultimo_cliente": clientes.get(t), "ultimo_humano": humanos.get(t),
            "conversaciones": 0, "hay_activa": False, "cierre_conversacion": None,
        }
        for t in telefonos
    }
    for telefono, estado_conv, cierre in filas:
        e = estado[telefono]
        e["conversaciones"] += 1
        if estado_conv == "activa":
            e["hay_activa"] = True
            e["cierre_conversacion"] = cierre
    return estado


# ── Gestionado por resultado / venta / "ya lo atendí" (2026-10-07, R4) ───
#
# Un cliente cuyo último mensaje sigue sin respuesta deja de "esperar" también
# cuando una persona ya lo gestionó SIN escribirle por el chat: le puso un
# resultado (no_interesado, agendado, sin_respuesta…), registró la venta o
# marcó "Ya lo atendí" (llamada, atención fuera de WhatsApp). Misma regla que
# el cierre definitivo: por TIMESTAMP, nunca booleana — el evento cuenta si su
# `creado` es igual o posterior al último mensaje real del cliente; si el
# cliente escribe DESPUÉS, vuelve a esperar. Un resultado QUITADO
# (`payload.nuevo` vacío) no es una gestión.

EVENTO_ATENDIDO_MANUAL = "atendido_manual"
MOTIVO_ATENDIDO_MAXIMO = 200
TIPOS_EVENTO_GESTION = ("resultado_cambiado", "venta_registrada", EVENTO_ATENDIDO_MANUAL)


def evento_cuenta_como_gestion(tipo: str | None, payload) -> bool:
    """True si un evento de la conversación significa "una persona ya lo gestionó"."""
    if tipo == "resultado_cambiado":
        nuevo = payload.get("nuevo") if isinstance(payload, dict) else None
        return bool(str(nuevo).strip()) if nuevo is not None else False
    return tipo in ("venta_registrada", EVENTO_ATENDIDO_MANUAL)


async def _ultima_gestion_por_conversacion(
    session, negocio_id: str, conversation_ids: list[str], desde: datetime | None = None,
) -> dict[str, datetime]:
    """Por conversación: el `creado` del evento de gestión más reciente (ver arriba). `desde` acota la
    consulta (nada anterior a esa fecha puede cubrir un mensaje posterior). Una consulta agrupada."""
    if not conversation_ids:
        return {}
    query = select(EventoLead.conversation_id, EventoLead.tipo, EventoLead.payload, EventoLead.creado).where(
        EventoLead.negocio_id == negocio_id, EventoLead.conversation_id.in_(conversation_ids),
        EventoLead.tipo.in_(TIPOS_EVENTO_GESTION),
    )
    if desde is not None:
        query = query.where(EventoLead.creado >= desde)
    ultima: dict[str, datetime] = {}
    for cid, tipo, payload, creado in (await session.execute(query)).all():
        if creado is None or not evento_cuenta_como_gestion(tipo, payload):
            continue
        if cid not in ultima or creado > ultima[cid]:
            ultima[cid] = creado
    return ultima


async def _atendido_manual_por_telefono(session, negocio_id: str, telefonos: list[str]) -> dict[str, datetime]:
    """Por teléfono: el último "Ya lo atendí" de su Conversation activa. Una consulta agrupada."""
    if not telefonos:
        return {}
    filas = (await session.execute(
        select(Contact.telefono, func.max(EventoLead.creado))
        .join(Conversation, Conversation.contact_id == Contact.id)
        .join(EventoLead, EventoLead.conversation_id == Conversation.id)
        .where(
            Contact.negocio_id == negocio_id, Conversation.negocio_id == negocio_id,
            Conversation.estado == "activa", EventoLead.negocio_id == negocio_id,
            EventoLead.tipo == EVENTO_ATENDIDO_MANUAL, Contact.telefono.in_(telefonos),
        )
        .group_by(Contact.telefono)
    )).all()
    return {t: ts for t, ts in filas if ts is not None}


async def registrar_atendido_manual(conversation_id: str, negocio_id: str, autor: str, motivo: str = "") -> str:
    """"Ya lo atendí": deja el evento `atendido_manual` en la conversación (el caso sale de "esperando"
    hasta que el cliente vuelva a escribir). Idempotente: si ya hay uno igual o posterior al último
    mensaje real del cliente, no agrega otro. Devuelve "registrado", "ya_registrado", "motivo_largo" o
    "no_encontrada" (la conversación no existe o es de otro negocio)."""
    motivo = (motivo or "").strip()
    if len(motivo) > MOTIVO_ATENDIDO_MAXIMO:
        return "motivo_largo"
    async with async_session() as session:
        conversation = await session.get(Conversation, conversation_id)
        if conversation is None or conversation.negocio_id != negocio_id:
            return "no_encontrada"
        ultimo_cliente = (await session.execute(
            select(func.max(Mensaje.timestamp)).where(
                Mensaje.conversation_id == conversation_id, Mensaje.negocio_id == negocio_id, Mensaje.role == "user",
                ~func.coalesce(Mensaje.content, "").startswith(PREFIJO_REACCION),
            )
        )).scalar_one_or_none()
        previo = (await session.execute(
            select(func.max(EventoLead.creado)).where(
                EventoLead.conversation_id == conversation_id, EventoLead.negocio_id == negocio_id,
                EventoLead.tipo == EVENTO_ATENDIDO_MANUAL,
            )
        )).scalar_one_or_none()
        if previo is not None and (ultimo_cliente is None or previo >= ultimo_cliente):
            return "ya_registrado"
        opportunity = await _obtener_opportunity_vigente(session, conversation.id)
        session.add(EventoLead(
            conversation_id=conversation.id, negocio_id=conversation.negocio_id,
            opportunity_id=opportunity.id if opportunity else None,
            tipo=EVENTO_ATENDIDO_MANUAL, descripcion="Marcó el caso como atendido fuera del chat", autor=autor,
            payload={"motivo": motivo} if motivo else {},
        ))
        await session.commit()
    return "registrado"


async def listar_leads_agendados(negocio_id: str, asesor_asignado: str | None = None) -> list[dict]:
    """Leads con una cita agendada (resultado == 'agendado' y fecha_agendada
    definida), de la más próxima a la más lejana — para el aviso de "Próximas
    citas" dentro del panel. Si se pasa asesor_asignado, solo las de ese asesor.

    `negocio_id` (Gate 5.4, T2) obligatorio — mismo hallazgo que listar_leads."""
    async with async_session() as session:
        query = (
            select(Lead)
            .where(
                Lead.negocio_id == negocio_id,
                Lead.resultado == "agendado", Lead.fecha_agendada.is_not(None),
                # 2026-10-06: un lead cerrado definitivamente no tiene una cita viva
                # (resguardo para datos que quedaron a medias: cerrar exige un
                # resultado cerrado, y reactivar limpia este campo).
                Lead.cerrado_definitivamente_en.is_(None),
            )
            .order_by(Lead.fecha_agendada.asc())
        )
        if asesor_asignado:
            query = query.where(Lead.asesor_asignado == asesor_asignado)
        result = await session.execute(query)
        return [_lead_a_dict(lead) for lead in result.scalars().all()]


async def listar_leads_esperando_asesor(negocio_id: str, excluir_atendidos: bool = True) -> list[dict]:
    """Leads derivados a un asesor que se quedaron sin nadie disponible en su
    momento (asesor_asignado sigue vacío), del más antiguo al más reciente —
    para poder asignarlos apenas un asesor se ponga disponible, en vez de
    quedar huérfanos para siempre.

    El filtro de resultado se hace en Python (no en el WHERE de SQL) porque
    la mayoría de estos leads tiene resultado NULL (pendiente) — un
    `NOT IN` en SQL excluiría también esas filas por cómo SQL trata NULL en
    comparaciones, que no es lo que queremos.

    2026-10-06 — casos ya gestionados (ver el bloque de arriba): además del
    resultado cerrado, se descartan (por timestamp)
      · los cerrados definitivamente (Lead o Conversation activa) cuyo cierre
        es igual o posterior al último mensaje real del cliente;
      · los que ya no tienen una Conversation activa (todas cerradas);
      · con `excluir_atendidos` (por defecto), los que un humano ya contestó
        (último mensaje real de un asesor, o de la línea desde el celular) igual
        o después del último del cliente — `pausar_gabi_manual` deja el lead en
        `derivado_asesor` sin asesor A PROPÓSITO y esa atención no es un
        pendiente. Si el cliente escribe de nuevo, reaparece.
    `agendado` y `postventa` NO están en `RESULTADOS_CERRADOS` y se mantienen
    así: un lead agendado o en postventa sin asesor sigue necesitando dueño.

    `negocio_id` (Gate 5.4, T2) obligatorio — mismo hallazgo que listar_leads."""
    async with async_session() as session:
        query = (
            select(Lead)
            .where(
                Lead.negocio_id == negocio_id,
                Lead.paso_flujo == "derivado_asesor", Lead.asesor_asignado.is_(None),
            )
            .order_by(Lead.actualizado.asc())
        )
        result = await session.execute(query)
        candidatos = [l for l in result.scalars().all() if l.resultado not in RESULTADOS_CERRADOS]
        estado = await _estado_atencion_por_telefono(session, negocio_id, [l.telefono for l in candidatos])
        atendido_manual = (
            await _atendido_manual_por_telefono(session, negocio_id, [l.telefono for l in candidatos])
            if excluir_atendidos else {}
        )

    pendientes = []
    for lead in candidatos:
        e = estado[lead.telefono]
        cierre = _cierre_vigente(lead.cerrado_definitivamente_en, e["cierre_conversacion"])
        if cierre_cubre_mensaje(cierre, e["ultimo_cliente"]):
            continue
        if e["conversaciones"] and not e["hay_activa"]:
            continue
        if excluir_atendidos and humano_atendio(e["ultimo_humano"], e["ultimo_cliente"]):
            continue
        # R4 (2026-10-07): "Ya lo atendí" (llamada, atención fuera del chat) igual o posterior al último
        # mensaje del cliente. Solo este evento aplica acá: poner un resultado abierto (agendado, postventa)
        # NO le quita al lead su necesidad de dueño, y los cerrados ya se descartan arriba.
        if excluir_atendidos and humano_atendio(atendido_manual.get(lead.telefono), e["ultimo_cliente"]):
            continue
        pendientes.append(_lead_a_dict(lead))
    return pendientes


# ── Inicio verdadero (paquete B, 2026-10-05) ────────────────────────────
#
# "Clientes esperando": conversaciones activas cuyo ÚLTIMO mensaje real es del
# cliente y nadie respondió después, con una persona (asesor/supervisión) de
# por medio. Reemplaza el criterio anterior de Inicio (`pausado_manual`), que
# no decía si el cliente realmente estaba esperando ni cuánto le quedaba a la
# ventana de 24 h de Meta.

VENTANA_META_HORAS = 24

# Prefijo con el que meta.py guarda las reacciones (👍 sobre un mensaje): no
# son un mensaje real del cliente ni una respuesta — se ignoran al decidir.
PREFIJO_REACCION = "Reaccionó con"

_EMOJIS_CIERRE = "👍🙏👌🙌😊😉✅🤝👏"
_PALABRAS_NUCLEO_CIERRE = frozenset({
    "gracias", "ok", "okay", "okey", "listo", "lista", "vale", "perfecto", "perfecta", "dale",
    "entendido", "entendida", "genial", "excelente", "buenisimo", "emoji",
})
_PALABRAS_RELLENO_CIERRE = frozenset({
    "muchas", "muchisimas", "mil", "por", "todo", "la", "el", "su", "tu", "ayuda", "atencion",
    "informacion", "info", "ya", "bien", "bueno", "de", "nada", "quedo", "atento", "atenta",
    "saludos", "entonces", "te", "aviso", "avisare",
})


def es_probable_cierre(texto: str | None) -> bool:
    """True si el mensaje del cliente parece un cierre de cortesía (gracias,
    ok, listo, 👍...): muy corto (<= 30 caracteres), sin pregunta y formado
    solo por palabras de agradecimiento/cierre. SOLO etiqueta y baja la
    prioridad en Inicio — nunca oculta el caso ni cambia su estado."""
    t = (texto or "").strip()
    if not t or len(t) > 30 or "?" in t or "¿" in t:
        return False
    t = unicodedata.normalize("NFKD", t.lower())
    t = "".join(c for c in t if not unicodedata.combining(c))
    t = re.sub("[️\U0001F3FB-\U0001F3FF]", "", t)  # selector de variación y tonos de piel
    t = re.sub(f"[{_EMOJIS_CIERRE}]", " emoji ", t)
    t = re.sub(r"[^\w\s]|_", " ", t)
    palabras = t.split()
    if not palabras:
        return False
    permitidas = _PALABRAS_NUCLEO_CIERRE | _PALABRAS_RELLENO_CIERRE
    return all(p in permitidas for p in palabras) and any(p in _PALABRAS_NUCLEO_CIERRE for p in palabras)


# ── Cierre de cortesía tras un cierre definitivo (Q3, 2026-10-07) ────────
#
# Caso real (Mercy 51939567302): la supervisora cerró definitivamente un caso
# y 28 s después la cliente contestó "Oh ya ok" al último mensaje del asesor.
# DR-4 abrió un ciclo nuevo, borró el resultado, liberó la asignación y Gabi
# respondió largo. Un mensaje de pura cortesía NO debe reabrir un caso ya
# cerrado: se guarda en la conversación cerrada y nadie recibe aviso.
#
# `es_cierre_cortesia` es una función PURA y deliberadamente más estricta que
# `es_probable_cierre` (que solo etiqueta en Inicio y no se toca): lista
# cerrada de palabras, sin verbos, sin "sí/dale/claro/no/entonces/mañana". Todo
# lo dudoso cae en False = se reabre como siempre (falla hacia reabrir).

_EMOJIS_CORTESIA = "👍🙏👌🙌😊😉✅🤝👏❤"
_MARCA_EMOJI_CORTESIA = "xemojix"
_CORTESIA_GRATITUD = frozenset({"gracias"})
_CORTESIA_GRATITUD_MODIFICADORES = frozenset({"muchas", "mil", "infinitas"})
_CORTESIA_ACUSE = frozenset({
    "ok", "okay", "okey", "oki", "listo", "lista", "vale", "perfecto", "perfecta", "entendido", "entendida",
    "genial", "excelente", "ya", "oh", "ah", "aja", "pe",
})
_CORTESIA_RELLENO = frozenset({
    "por", "la", "el", "su", "tu", "info", "informacion", "ayuda", "atencion", "todo", "de", "nada", "igualmente",
    "saludos", "buen", "buena", "buenos", "buenas", "dia", "dias", "tarde", "tardes", "noche", "noches", "bien",
    "hasta", "luego", "quedo", "atento", "atenta",
})
_CORTESIA_PALABRAS_VALIDAS = (
    _CORTESIA_GRATITUD | _CORTESIA_GRATITUD_MODIFICADORES | _CORTESIA_ACUSE | _CORTESIA_RELLENO
    | {_MARCA_EMOJI_CORTESIA}
)
_LARGO_MAXIMO_CIERRE_CORTESIA = 40
# Máximo de mensajes de cierre que se absorben por cada cierre definitivo; el siguiente reabre.
TOPE_CIERRES_DE_CORTESIA = 5
_RE_URL_CORTESIA = re.compile(r"https?://|www\.|\.(com|pe|net|org|io|me)\b", re.IGNORECASE)


def _normalizar_cortesia(texto: str) -> str:
    """Minúsculas, sin tildes, emojis de cortesía como marca, sin signos y con
    las letras repetidas colapsadas ("graciass" -> "gracias", "okk" -> "ok")."""
    t = unicodedata.normalize("NFKD", texto.lower())
    t = "".join(c for c in t if not unicodedata.combining(c))
    t = re.sub("[️\U0001F3FB-\U0001F3FF]", "", t)  # selector de variación y tonos de piel
    t = re.sub(f"[{_EMOJIS_CORTESIA}]", f" {_MARCA_EMOJI_CORTESIA} ", t)
    t = re.sub(r"[^\w\s]|_", " ", t)
    return re.sub(r"([a-z])\1+", r"\1", t)


def nivel_cierre_cortesia(texto: str | None) -> str | None:
    """"A" (solo gratitud o emoji de cortesía: "gracias", "🙏"), "B" (con un
    acuse: "ok", "listo", "oh ya ok"…) o None si NO es un cierre de cortesía.
    Reglas (todas obligatorias): <= 40 caracteres, una sola línea, sin "?"/"¿",
    sin dígitos ni URL, todas las palabras en la lista cerrada y al menos una
    de gratitud ("gracias"), de acuse o un emoji de cortesía."""
    t = (texto or "").strip()
    if not t or len(t) > _LARGO_MAXIMO_CIERRE_CORTESIA:
        return None
    if "?" in t or "¿" in t or "\n" in t or "\r" in t or re.search(r"\d", t) or _RE_URL_CORTESIA.search(t):
        return None
    tokens = _normalizar_cortesia(t).split()
    if not tokens or any(p not in _CORTESIA_PALABRAS_VALIDAS for p in tokens):
        return None
    hay_acuse = any(p in _CORTESIA_ACUSE for p in tokens)
    hay_gratitud = any(p in _CORTESIA_GRATITUD for p in tokens)
    hay_emoji = _MARCA_EMOJI_CORTESIA in tokens
    if not (hay_acuse or hay_gratitud or hay_emoji):
        return None
    return "B" if hay_acuse else "A"


def es_cierre_cortesia(texto: str | None) -> bool:
    """True si el texto es un mensaje de cierre de cortesía (ver
    `nivel_cierre_cortesia`). NO decide si se absorbe: eso lo hace
    `evaluar_cierre_cortesia` mirando el contexto del caso cerrado."""
    return nivel_cierre_cortesia(texto) is not None


def es_mensaje_que_no_reabre(contenido: str | None) -> bool:
    """Reacción ("Reaccionó con 👍") o cierre de cortesía: lo único que, con el
    caso cerrado definitivamente, queda en la conversación cerrada sin
    reabrirla (no cuenta como "pendiente" en la Bandeja ni en Inicio)."""
    return (contenido or "").startswith(PREFIJO_REACCION) or es_cierre_cortesia(contenido)


def _norm_contexto(texto: str | None) -> str:
    t = unicodedata.normalize("NFKD", (texto or "").lower())
    return "".join(c for c in t if not unicodedata.combining(c))


_RE_COMPROMISO_SALIENTE = re.compile(
    r"\b\d{1,2}(:\d\d)?\s?(am|pm|a\.\s?m\.?|p\.\s?m\.?|h|hrs?)\b|\b\d{1,2}:\d\d\b|\ba las? \d"
    r"|\bmanana\b|\bhoy a las\b|\b(lunes|martes|miercoles|jueves|viernes|sabado|domingo)\b"
    r"|\besta (tarde|noche|manana)\b|\bmas tarde\b"
    r"|\b(envi\w*|pas[ae]\w*|confirm\w*|avis\w*|mand\w*|compart\w*|adjunt\w*|brind\w*|proporcion\w*"
    r"|necesit\w*|indic\w*|dime|dame|cuent\w*|llam\w*|dni|foto\w*|documento\w*|voucher|comprobante)\b"
)


def saliente_deja_algo_pendiente(texto: str | None) -> bool:
    """True si el último mensaje saliente cierra con una pregunta (C2: "?" o "¿"
    en sus últimos ~160 caracteres) o contiene un compromiso o una petición
    pendiente (C3: horario, "mañana", día de la semana, "envíame", "DNI",
    "foto"…). Con cualquiera de las dos un "ok" del cliente ya es una respuesta
    real y el caso se reabre. Tiende a decir True ante la duda."""
    cola = (texto or "")[-160:]
    if "?" in cola or "¿" in cola:
        return True
    return _RE_COMPROMISO_SALIENTE.search(_norm_contexto(texto)) is not None


# ── Lapso de gracia del cierre definitivo y agradecimiento automático (2026-10-07) ──
#
# Benchmarking (Gladly, Front/WhatsApp, WATI: 24 h; Zendesk, Help Scout): un cierre se puede
# deshacer sin papeleo mientras la conversación siga "caliente"; pasado ese lapso reabrir es una
# decisión de supervisión con motivo. `cierre_gracia_horas` (por negocio, default 24) manda en las
# tres piezas: cuándo se muestran el banner y el chip, quién puede reabrir y si hace falta motivo.

CIERRE_GRACIA_HORAS_POR_DEFECTO = 24
CLAVE_CIERRE_GRACIA_HORAS = "cierre_gracia_horas"
CLAVE_AGRADECIMIENTO_ACTIVO = "agradecimiento_cierre_activo"
CLAVE_AGRADECIMIENTO_TEXTO = "agradecimiento_cierre_texto"
AGRADECIMIENTO_CIERRE_TEXTO_POR_DEFECTO = "¡Gracias a ti! Si necesitas algo más, escríbenos cuando quieras. 😊"
EVENTO_AGRADECIMIENTO_CIERRE = "agradecimiento_cierre_enviado"
MOTIVO_REABRIR_MAXIMO = 300


def normalizar_cierre_gracia_horas(valor) -> float | int:
    """Horas del lapso de gracia. Valor ausente, inválido, no finito o <= 0 -> 24."""
    try:
        horas = float(str(valor).strip().replace(",", "."))
    except (TypeError, ValueError):
        return CIERRE_GRACIA_HORAS_POR_DEFECTO
    if horas != horas or horas in (float("inf"), float("-inf")) or horas <= 0:
        return CIERRE_GRACIA_HORAS_POR_DEFECTO
    return int(horas) if horas == int(horas) else horas


async def obtener_cierre_gracia_horas(negocio_id: str | None) -> float | int:
    """Lapso de gracia del negocio (clave `cierre_gracia_horas`, default 24 h). Nunca lanza."""
    try:
        valor = await obtener_configuracion(
            CLAVE_CIERRE_GRACIA_HORAS, str(CIERRE_GRACIA_HORAS_POR_DEFECTO), negocio_id=negocio_id,
        )
    except Exception:
        return CIERRE_GRACIA_HORAS_POR_DEFECTO
    return normalizar_cierre_gracia_horas(valor)


def cierre_en_lapso_de_gracia(cierre: datetime | None, ahora: datetime, horas: float | int) -> bool:
    """True si desde el cierre pasaron `horas` o menos (el borde exacto cuenta como dentro)."""
    return cierre is not None and (ahora - cierre) <= timedelta(hours=horas)


def contiene_gratitud(texto: str | None) -> bool:
    """True si el texto es un cierre de cortesía que incluye la palabra "gracias" (cualquier
    nivel: "gracias", "muchas gracias", "ok gracias"). Un "ok"/"listo" solo, un emoji solo o una
    reacción NO la contienen."""
    if not es_cierre_cortesia(texto):
        return False
    return "gracias" in _normalizar_cortesia((texto or "").strip()).split()


async def agradecimiento_cierre_activo(negocio_id: str | None) -> bool:
    """Interruptor `agradecimiento_cierre_activo` (default "1" = encendido; "0" lo apaga)."""
    try:
        valor = await obtener_configuracion(CLAVE_AGRADECIMIENTO_ACTIVO, "1", negocio_id=negocio_id)
    except Exception:
        return False
    return str(valor).strip().lower() not in ("0", "false", "no", "off", "apagado")


async def obtener_texto_agradecimiento_cierre(negocio_id: str | None) -> str:
    """Frase fija del agradecimiento (clave `agradecimiento_cierre_texto`); vacía -> la de siempre."""
    try:
        valor = await obtener_configuracion(CLAVE_AGRADECIMIENTO_TEXTO, "", negocio_id=negocio_id)
    except Exception:
        valor = ""
    return (valor or "").strip() or AGRADECIMIENTO_CIERRE_TEXTO_POR_DEFECTO


async def agradecimiento_cierre_ya_enviado(conversation_id: str, cierre_en: datetime) -> bool:
    """¿Ya se registró un agradecimiento automático DESPUÉS de este cierre? (una vez por cierre)."""
    async with async_session() as session:
        return (await session.execute(
            select(EventoLead.id).where(
                EventoLead.conversation_id == conversation_id, EventoLead.tipo == EVENTO_AGRADECIMIENTO_CIERRE,
                EventoLead.creado > cierre_en,
            ).limit(1)
        )).first() is not None


async def registrar_agradecimiento_cierre(
    conversation_id: str, negocio_id: str, cierre_en: datetime, texto: str, resultado: str, wamid: str | None = None,
) -> None:
    """Deja la marca de "ya se agradeció tras este cierre" con el texto enviado (el filtro de
    contexto lo usa para NO tratar ese mensaje como una respuesta humana) y cómo terminó el envío
    (`enviado` | `incierto` | `fallido` | `bloqueado`)."""
    async with async_session() as session:
        session.add(EventoLead(
            conversation_id=conversation_id, negocio_id=negocio_id, tipo=EVENTO_AGRADECIMIENTO_CIERRE,
            descripcion="Agradecimiento automático al cliente tras el cierre"[:300], autor=None,
            payload={"texto": texto, "cierre_en": cierre_en.isoformat(), "resultado": resultado, "wamid": wamid},
        ))
        await session.commit()


async def _textos_de_agradecimiento(session, conversation_id: str, cierre: datetime) -> set[str]:
    """Textos (normalizados) de los agradecimientos automáticos registrados tras el cierre."""
    eventos = (await session.execute(
        select(EventoLead.payload).where(
            EventoLead.conversation_id == conversation_id, EventoLead.tipo == EVENTO_AGRADECIMIENTO_CIERRE,
            EventoLead.creado > cierre,
        )
    )).scalars().all()
    return {
        _norm_contexto(p["texto"]).strip() for p in eventos if isinstance(p, dict) and isinstance(p.get("texto"), str)
    }


def _es_agradecimiento_automatico(mensaje: "Mensaje", textos: set[str]) -> bool:
    return bool(textos) and mensaje.role == "assistant" and _norm_contexto(mensaje.content).strip() in textos


def _es_saliente_valido(mensaje: "Mensaje") -> bool:
    return mensaje.role in ("assistant", "asesor") and (mensaje.estado_envio or "") != "fallido"


async def _resumen_tras_cierre(session, cierres: dict[str, datetime]) -> dict[str, dict]:
    """Por conversación con cierre definitivo: lo que el CLIENTE escribió DESPUÉS
    de ese cierre (los mensajes `user` posteriores). Una consulta en lote para
    toda la lista (sin N+1). Devuelve `{conversation_id: {"mensajes": n,
    "ultimo_en": datetime|None, "descontar_pendientes": k}}` donde
    `descontar_pendientes` son los que la Bandeja NO debe contar como
    pendientes (reacciones y cierres de cortesía posteriores al último
    mensaje que no es del cliente)."""
    if not cierres:
        return {}
    ids = list(cierres)
    ultimo_no_cliente = {
        cid: ts for cid, ts in (await session.execute(
            select(Mensaje.conversation_id, func.max(Mensaje.timestamp))
            .where(Mensaje.conversation_id.in_(ids), Mensaje.role != "user")
            .group_by(Mensaje.conversation_id)
        )).all()
    }
    resumen: dict[str, dict] = {}
    filas = (await session.execute(
        select(Mensaje.conversation_id, Mensaje.content, Mensaje.timestamp)
        .where(Mensaje.conversation_id.in_(ids), Mensaje.role == "user")
    )).all()
    for cid, contenido, ts in filas:
        if ts is None or ts <= cierres[cid]:
            continue
        r = resumen.setdefault(cid, {"mensajes": 0, "ultimo_en": None, "descontar_pendientes": 0})
        r["mensajes"] += 1
        if r["ultimo_en"] is None or ts > r["ultimo_en"]:
            r["ultimo_en"] = ts
        pendiente_desde = ultimo_no_cliente.get(cid)
        if es_mensaje_que_no_reabre(contenido) and (pendiente_desde is None or ts > pendiente_desde):
            r["descontar_pendientes"] += 1
    return resumen


async def evaluar_cierre_cortesia(
    telefono: str, negocio_id: str, texto: str | None, tipo: str = "texto", *,
    tiene_referral: bool = False, interactivo_id: str = "", contexto_id: str = "",
    ahora: datetime | None = None,
) -> dict | None:
    """SOLO LECTURA. ¿Este mensaje entrante debe quedarse en la conversación
    cerrada definitivamente, SIN abrir un ciclo nuevo (DR-4), sin despertar a
    Gabi y sin avisar a nadie? Devuelve el contexto (`conversation_id`,
    `cierre_en`, `nivel`, `numero_absorbido`, `ultimo_saliente_id`) o None =
    seguir por el camino de siempre. TODO fallo se resuelve hacia None.

    `tipo`: "texto" (mensaje del cliente: exige cierre de cortesía + C1-C4 +
    tope), "reaccion" o "echo" (el asesor escribió desde el celular): con el
    cierre vigente nunca abren ciclo, sin más filtros.

    Aplica con cierre definitivo vigente de CUALQUIER resultado (incluido
    vendido). El cierre se toma de la Conversation activa o del Lead, pero solo
    si es posterior a la creación de esa Conversation (uno viejo y sobrante de
    un ciclo anterior no cuenta).

    Filtro de contexto (tipo "texto") sobre el ÚLTIMO mensaje saliente
    (assistant o asesor, sin envío fallido) de la Conversation cerrada, o el
    mensaje que el cliente citó (`contexto_id`) si se puede resolver:
      C1 debe existir; C2 no termina en pregunta; C3 sin compromiso ni petición
      pendiente; C4 nadie (humano o Gabi) escribió DESPUÉS del cierre.
    Nivel A (solo gratitud/emoji) exige C1 y C4; Nivel B (con acuse: "ok",
    "listo"…) exige además C2 y C3. Tope: `TOPE_CIERRES_DE_CORTESIA` mensajes
    absorbidos por cierre dentro del lapso de gracia; el siguiente reabre.

    Lapso de gracia (2026-10-07, `cierre_gracia_horas`, default 24 h): el contexto trae
    `tardio` (True si pasaron más horas que el lapso desde el cierre: el mensaje se guarda
    como "mensaje suelto", sin banner, chip ni alerta; el tope no aplica porque nadie se
    entera), `gracia_horas` y `gratitud` (el texto contiene "gracias": dispara el
    agradecimiento automático). El agradecimiento automático (evento
    `agradecimiento_cierre_enviado`) NO cuenta como un saliente: ni en C4, ni como
    "último saliente" para C2/C3, ni como mensaje citado."""
    if tipo not in ("texto", "reaccion", "echo"):
        return None
    nivel = None
    if tipo == "texto":
        if tiene_referral or interactivo_id:
            return None
        nivel = nivel_cierre_cortesia(texto)
        if nivel is None:
            return None
    ahora = ahora or datetime.utcnow()
    gracia_horas = await obtener_cierre_gracia_horas(negocio_id)
    async with async_session() as session:
        contact = await _obtener_contact(session, negocio_id, telefono)
        if contact is None:
            return None
        conversation = await _obtener_conversation_activa(session, contact.id)
        if conversation is None or conversation.negocio_id != negocio_id:
            return None
        lead = await session.get(Lead, telefono)
        cierre_lead = lead.cerrado_definitivamente_en if lead is not None and lead.negocio_id in (None, negocio_id) else None
        cierre = _cierre_vigente(conversation.cerrado_definitivamente_en, cierre_lead)
        if cierre is None:
            return None
        if conversation.creado is not None and conversation.creado > cierre:
            return None  # cierre sobrante de un ciclo anterior: esta conversación es posterior

        salientes = (
            Mensaje.conversation_id == conversation.id, Mensaje.negocio_id == negocio_id,
            Mensaje.role.in_(("assistant", "asesor")), func.coalesce(Mensaje.estado_envio, "") != "fallido",
        )
        # El agradecimiento automático (frase fija, sin IA) no es una respuesta de nadie: se excluye
        # del "último saliente" y de C4 para que un "ok" posterior del cliente siga absorbiéndose.
        textos_agradecimiento = await _textos_de_agradecimiento(session, conversation.id, cierre)
        recientes = (await session.execute(
            select(Mensaje).where(*salientes).order_by(Mensaje.timestamp.desc(), Mensaje.id.desc()).limit(8)
        )).scalars().all()
        ultimo_saliente = next((m for m in recientes if not _es_agradecimiento_automatico(m, textos_agradecimiento)), None)

        tardio = not cierre_en_lapso_de_gracia(cierre, ahora, gracia_horas)
        if tipo != "texto":
            return {
                "conversation_id": conversation.id, "cierre_en": cierre, "nivel": None, "numero_absorbido": None,
                "ultimo_saliente_id": ultimo_saliente.id if ultimo_saliente else None,
                "tardio": tardio, "gracia_horas": gracia_horas, "gratitud": False,
            }

        # Tope: mensajes del cliente (no reacciones) ya absorbidos tras este cierre.
        previos = (await session.execute(
            select(func.count(Mensaje.id)).where(
                Mensaje.conversation_id == conversation.id, Mensaje.negocio_id == negocio_id,
                Mensaje.role == "user", Mensaje.timestamp > cierre,
                ~func.coalesce(Mensaje.content, "").startswith(PREFIJO_REACCION),
            )
        )).scalar_one()
        # El tope solo rige dentro del lapso de gracia: pasado el lapso el mensaje es "suelto"
        # y nadie se entera, así que no hay nada que acotar.
        if not tardio and previos >= TOPE_CIERRES_DE_CORTESIA:
            return None

        # C4: nadie (humano o Gabi) escribió después del cierre, salvo el agradecimiento automático.
        escritos_despues = (await session.execute(
            select(Mensaje).where(*salientes, Mensaje.timestamp > cierre).order_by(Mensaje.id).limit(50)
        )).scalars().all()
        if any(not _es_agradecimiento_automatico(m, textos_agradecimiento) for m in escritos_despues):
            return None

        # Contexto: el mensaje que el cliente citó, si se puede resolver; si no, el último saliente.
        contexto = ultimo_saliente
        if contexto_id:
            citado = (await session.execute(
                select(Mensaje).where(
                    Mensaje.conversation_id == conversation.id, Mensaje.negocio_id == negocio_id,
                    Mensaje.mensaje_id_meta == contexto_id,
                ).limit(1)
            )).scalar_one_or_none()
            if citado is not None:
                if not _es_saliente_valido(citado):
                    return None
                # Citar nuestro agradecimiento automático no cambia el contexto real del caso.
                if not _es_agradecimiento_automatico(citado, textos_agradecimiento):
                    contexto = citado
        if contexto is None:
            return None  # C1
        if nivel == "B" and saliente_deja_algo_pendiente(contexto.content):
            return None  # C2/C3
        return {
            "conversation_id": conversation.id, "cierre_en": cierre, "nivel": nivel,
            "numero_absorbido": previos + 1, "ultimo_saliente_id": contexto.id,
            "tardio": tardio, "gracia_horas": gracia_horas, "gratitud": contiene_gratitud(texto),
        }


async def _inicio_de_espera_por_conversacion(negocio_id: str, conversation_ids: list[str]) -> dict[str, datetime]:
    """Por conversación: el PRIMER mensaje real del cliente posterior al último mensaje saliente (de Gabi
    o de una persona; los envíos fallidos y las reacciones no cuentan). Es desde cuándo el cliente está
    sin respuesta (Atención atrasada, 2026-10-07). Una sola consulta agrupada. Se ancla al último saliente
    de CUALQUIER rol, no solo al humano: lo que Gabi conversó antes de derivar no es espera de una persona,
    y contarlo marcaría como "urgente" a un lead derivado hace minutos tras días de charla con Gabi."""
    if not conversation_ids:
        return {}
    no_reaccion = ~func.coalesce(Mensaje.content, "").startswith(PREFIJO_REACCION)
    ancla = (
        select(Mensaje.conversation_id.label("cid"), func.max(Mensaje.timestamp).label("ancla"))
        .where(
            Mensaje.negocio_id == negocio_id, Mensaje.conversation_id.in_(conversation_ids),
            Mensaje.role.in_(("assistant", "asesor")), func.coalesce(Mensaje.estado_envio, "") != "fallido", no_reaccion,
        )
        .group_by(Mensaje.conversation_id)
        .subquery()
    )
    async with async_session() as session:
        filas = (await session.execute(
            select(Mensaje.conversation_id, func.min(Mensaje.timestamp))
            .outerjoin(ancla, ancla.c.cid == Mensaje.conversation_id)
            .where(
                Mensaje.negocio_id == negocio_id, Mensaje.conversation_id.in_(conversation_ids),
                Mensaje.role == "user", no_reaccion,
                sa_or(ancla.c.ancla.is_(None), Mensaje.timestamp > ancla.c.ancla),
            )
            .group_by(Mensaje.conversation_id)
        )).all()
    return {cid: ts for cid, ts in filas if ts is not None}


async def listar_clientes_esperando(
    negocio_id: str, asesor: str | None = None, limite: int | None = None, ahora: datetime | None = None,
    con_desde: bool = True,
) -> list[dict]:
    """Clientes que esperan respuesta de una persona (Inicio verdadero).

    Criterio: Conversation `activa` del negocio cuyo ÚLTIMO mensaje real
    (ignorando reacciones) es del cliente (`role == "user"`), con un humano de
    por medio: lead con `asesor_asignado`, `pausado_manual` o
    `escalado_supervision_en`. NO incluye lo que Gabi atiende sola sin asesor
    (ella responde). Aplica a CUALQUIER resultado, incluido vendido y
    agendado — un cliente ya vendido que escribe de nuevo también espera.
    `asesor` acota a los leads de ese asesor (el asesor ve solo los suyos).

    2026-10-06 — NO esperan los cerrados definitivamente (`cerrado_definitivamente_en`
    del Lead o de la Conversation) cuyo cierre es igual o posterior al último
    mensaje real del cliente (p. ej. una venta cuyo último mensaje fue
    "gracias"). Se compara por timestamp: si el cliente escribe DESPUÉS del
    cierre, vuelve a esperar.

    2026-10-07 (R4) — tampoco esperan los que una persona ya GESTIONÓ sin escribir por el
    chat: un EventoLead de su conversación con `creado` igual o posterior al último mensaje real
    del cliente de tipo `resultado_cambiado` (con `payload.nuevo` no vacío; quitar el resultado
    no cuenta), `venta_registrada` o `atendido_manual` ("Ya lo atendí"). Misma regla por
    timestamp: si el cliente escribe DESPUÉS del evento, vuelve a esperar.

    Una sola consulta (ROW_NUMBER por conversación, sin N+1) más una agrupada para los eventos de
    gestión. Cada ítem:
    `conversation_id`, `telefono`, `nombre`, `asesor_asignado`, `resultado`,
    `ultimo_mensaje_cliente_en` (UTC naive), `escalado`, `probable_cierre`,
    `ventana_vence_en` (último mensaje + 24 h, UTC naive) y `ventana_abierta`.
    2026-10-07 (aditivo): `esperando_desde` = el PRIMER mensaje real del cliente que sigue sin
    respuesta saliente (de Gabi o de una persona) — ver `_inicio_de_espera_por_conversacion`.
    Con `con_desde=False` no se calcula y `esperando_desde` = `ultimo_mensaje_cliente_en`.

    Orden: primero ventana abierta (la que vence antes, primero); luego
    ventanas cerradas (la más reciente primero). Dentro de cada grupo los
    `probable_cierre` van al final. `probable_cierre` solo etiqueta: nunca
    oculta el ítem ni toca el estado del lead."""
    ahora = ahora or datetime.utcnow()
    async with async_session() as session:
        conversaciones_activas = select(Conversation.id).where(
            Conversation.negocio_id == negocio_id, Conversation.estado == "activa",
        )
        fila = (
            func.row_number()
            .over(partition_by=Mensaje.conversation_id, order_by=(Mensaje.timestamp.desc(), Mensaje.id.desc()))
            .label("fila")
        )
        ultimos = (
            select(
                Mensaje.conversation_id.label("conversation_id"), Mensaje.role.label("role"),
                Mensaje.content.label("content"), Mensaje.timestamp.label("ts"),
            )
            .where(
                Mensaje.negocio_id == negocio_id,
                Mensaje.conversation_id.in_(conversaciones_activas),
                ~func.coalesce(Mensaje.content, "").startswith(PREFIJO_REACCION),
            )
            .add_columns(fila)
            .subquery()
        )
        hay_humano = sa_or(
            sa_and(Lead.asesor_asignado.is_not(None), Lead.asesor_asignado != ""),
            Lead.pausado_manual.is_(True),
            Lead.escalado_supervision_en.is_not(None),
        )
        query = (
            select(
                Conversation.id, Contact.telefono, Contact.nombre, Lead.nombre, Lead.asesor_asignado,
                Lead.resultado, Lead.escalado_supervision_en, ultimos.c.content, ultimos.c.ts,
                Lead.cerrado_definitivamente_en, Conversation.cerrado_definitivamente_en,
            )
            .join(ultimos, sa_and(ultimos.c.conversation_id == Conversation.id, ultimos.c.fila == 1))
            .join(Contact, Contact.id == Conversation.contact_id)
            .join(Lead, sa_and(Lead.telefono == Contact.telefono, Lead.negocio_id == Conversation.negocio_id))
            .where(
                Conversation.negocio_id == negocio_id, Conversation.estado == "activa",
                ultimos.c.role == "user", hay_humano,
            )
        )
        if asesor:
            query = query.where(Lead.asesor_asignado == asesor)
        filas = (await session.execute(query)).all()

    items = []
    for (
        conv_id, telefono, nombre_contact, nombre_lead, asesor_asignado, resultado, escalado_en, contenido, ts,
        cierre_lead, cierre_conversacion,
    ) in filas:
        # Ya gestionado: el cierre definitivo es igual o posterior a lo último
        # que escribió el cliente. Si escribe DESPUÉS del cierre, sí espera.
        cierre_efectivo = _cierre_vigente(cierre_lead, cierre_conversacion)
        if cierre_cubre_mensaje(cierre_efectivo, ts):
            continue
        # Q3 (2026-10-07): el "ok"/"gracias" que llegó tras un cierre definitivo se
        # queda en la conversación cerrada y nadie lo espera. Se decide por el
        # texto (no por una marca) para que funcione también con datos viejos.
        if cierre_efectivo is not None and es_cierre_cortesia(contenido):
            continue
        vence = ts + timedelta(hours=VENTANA_META_HORAS)
        items.append({
            "conversation_id": conv_id, "telefono": telefono, "nombre": nombre_lead or nombre_contact,
            "asesor_asignado": asesor_asignado or None, "resultado": resultado,
            "ultimo_mensaje_cliente_en": ts, "escalado": escalado_en is not None,
            "probable_cierre": es_probable_cierre(contenido),
            "ventana_vence_en": vence, "ventana_abierta": vence > ahora,
        })
    if items:
        async with async_session() as session:
            gestion = await _ultima_gestion_por_conversacion(
                session, negocio_id, [it["conversation_id"] for it in items],
                desde=min(it["ultimo_mensaje_cliente_en"] for it in items),
            )
        items = [
            it for it in items
            if not (gestion.get(it["conversation_id"]) is not None
                    and gestion[it["conversation_id"]] >= it["ultimo_mensaje_cliente_en"])
        ]
    desde_por_conversacion = (
        await _inicio_de_espera_por_conversacion(negocio_id, [it["conversation_id"] for it in items])
        if con_desde and items else {}
    )
    for it in items:
        it["esperando_desde"] = desde_por_conversacion.get(it["conversation_id"]) or it["ultimo_mensaje_cliente_en"]

    def _clave(it: dict):
        ts = (it["ultimo_mensaje_cliente_en"] - datetime(1970, 1, 1)).total_seconds()
        # abiertas: la que vence antes (mensaje más viejo) primero; cerradas: la más reciente primero
        return (0 if it["ventana_abierta"] else 1, 1 if it["probable_cierre"] else 0, ts if it["ventana_abierta"] else -ts)

    items.sort(key=_clave)
    return items[:limite] if limite is not None else items


async def contar_casos_activos(negocio_id: str, asesor: str | None = None) -> int:
    """Conversaciones activas del negocio cuyo lead no tiene un resultado
    cerrado (`RESULTADOS_CERRADOS`) — el "caso activo" de Inicio. Con
    `asesor`, solo las de ese asesor. Un conteo SQL, sin traer filas."""
    async with async_session() as session:
        query = (
            select(func.count(Conversation.id))
            .join(Contact, Contact.id == Conversation.contact_id)
            .join(Lead, sa_and(Lead.telefono == Contact.telefono, Lead.negocio_id == Conversation.negocio_id))
            .where(
                Conversation.negocio_id == negocio_id, Conversation.estado == "activa",
                sa_or(Lead.resultado.is_(None), Lead.resultado.not_in(RESULTADOS_CERRADOS)),
            )
        )
        if asesor:
            query = query.where(Lead.asesor_asignado == asesor)
        return (await session.execute(query)).scalar_one()


def _exigir_lead_existente(lead: "Lead | None", telefono: str, funcion: str) -> "Lead":
    """Fail-closed (Gate 5.2, corrección H2): estas funciones (venta,
    asignación, pausa manual, fallo técnico, campaña de origen) actúan sobre
    un Lead que YA debería existir — nunca son el camino de creación
    legítimo (ese es `actualizar_lead`, con negocio_id resuelto desde el
    Canal). Antes de este Gate creaban silenciosamente un Lead vacío (sin
    negocio_id posible de resolver acá) si por algún motivo no existía; ahora
    fallan con un error claro en vez de eso — no inventan pertenencia a
    ningún Negocio."""
    if lead is None:
        raise ValueError(
            f"{funcion}(): no existe un Lead para telefono={telefono} — esta función no "
            f"crea Leads nuevos (requeriría negocio_id, que acá no tiene de dónde "
            f"resolverse de forma legítima). Si el Lead debería existir, verificar que "
            f"actualizar_lead() ya corrió para este teléfono."
        )
    return lead


def _requiere_negocio_id_para_lead_nuevo(negocio_id: str | None, telefono: str, funcion: str) -> None:
    """Fail-closed (Gate 5.2, corrección H2): un Lead NUEVO nunca se crea sin
    negocio_id resuelto — nunca se asume Cálidda ni ningún otro Negocio por
    defecto. La fuente legítima de `negocio_id` es el Canal por el que entró
    el mensaje (`CanalWhatsApp.negocio_id`, ya scoped por Negocio desde su
    propia creación) — no una constante global ni "el primer Negocio"."""
    if negocio_id is None:
        raise ValueError(
            f"No se puede crear un Lead nuevo (telefono={telefono}) sin negocio_id "
            f"resuelto — llamado desde {funcion}(). No se asume ningún Negocio por "
            f"defecto (Gate 5.2: nunca usar un Negocio como fallback silencioso)."
        )


async def actualizar_lead(
    telefono: str, campos_explicitos: tuple[str, ...] = (), negocio_id: str | None = None, **campos,
):
    """Actualiza (o crea) los datos estructurados del cliente. Por defecto solo
    sobreescribe los campos con un valor no vacío, para no perder datos ya
    conocidos — eso es lo correcto para las escrituras de Gabi, que manda lo que
    logró extraer de la conversación y nada más.

    `campos_explicitos` nombra los campos que vienen de una decisión HUMANA en
    el panel, donde "vacío" no significa "no sé", sino "bórralo" (Human Decision
    Gate: si una persona limpió el campo, el sistema no puede decidir por su
    cuenta conservar el valor viejo). Esos campos se escriben tal cual llegan,
    normalizando "" a NULL. Quien llama decide cuáles son: la misma función
    sirve para los dos casos sin que el llamador automático cambie.

    `negocio_id` (Gate 5.2) solo importa cuando el Lead todavía no existe —
    nunca sobreescribe el negocio_id de un Lead ya existente (el Negocio de
    un Lead se fija una sola vez, en su creación, igual criterio que
    `campana_origen`). Quien llama debe resolverlo desde una fuente legítima
    (el Canal de entrada); ver `_requiere_negocio_id_para_lead_nuevo`."""
    campos = _filtrar_campos(campos, campos_explicitos)
    if not campos:
        return
    async with async_session() as session:
        lead = await session.get(Lead, telefono)
        if lead is None:
            _requiere_negocio_id_para_lead_nuevo(negocio_id, telefono, "actualizar_lead")
            lead = Lead(telefono=telefono, negocio_id=negocio_id)
            session.add(lead)
        # Antes de pisar los valores: la transición se define contra el estado
        # ANTERIOR del lead. Vive acá (y no en el router) porque ésta es la
        # única función por la que pasan las dos vías que ponen "vendido".
        transicion_a_vendido = _es_transicion_a_vendido(lead, campos)
        for campo, valor in campos.items():
            setattr(lead, campo, valor)
        if transicion_a_vendido:
            _marcar_cierre_vendido(lead)
        # Punto 2 (2026-09-30) — mismo desarme que `intentar_cambiar_
        # resultado_opportunity`/`cerrar_opportunity_con_venta` (ver ahí el
        # porqué), para el camino fallback legacy: un Lead sin Contact/
        # Conversation/Opportunity todavía usa esta función como escritura
        # real de resultado. Solo cuenta como decisión humana cuando
        # "resultado" está en `campos_explicitos` (nunca en la escritura
        # automática de Gabi, que no lo incluye ahí).
        if "resultado" in campos and "resultado" in campos_explicitos:
            lead.derivado_en = None
        lead.actualizado = datetime.utcnow()

        # Gate 5.3 — mirror best-effort hacia Conversation/Opportunity, EN LA
        # MISMA transacción. Solo si ya existen (esta función no las crea —
        # la creación real ocurre en resolver_conversation_activa, llamada
        # desde el webhook con el Canal ya resuelto; acá no hay de dónde
        # sacar canal_id). Mientras no existan, Lead sigue siendo la única
        # fuente de verdad para este teléfono, sin bloquear nada.
        await _mirror_campos_lead_a_conversation_opportunity(session, lead, campos, transicion_a_vendido)

        await session.commit()


_CAMPOS_OPPORTUNITY = (
    "interes", "producto_tipo", "producto_marca", "producto_modalidad",
    "resultado", "fecha_agendada", "fecha_cierre", "modalidad_pago", "cuotas", "medio_pago",
    "monto_financiado", "cuota_pactada", "tea_pactada", "igv_pactado",
)
_CAMPOS_CONVERSATION = (
    "paso_flujo", "visto_asesor", "fallos_tecnicos", "pausado_manual",
    "revision_prioritaria", "origen_contacto",
)


async def _mirror_campos_lead_a_conversation_opportunity(session, lead: "Lead", campos: dict, transicion_a_vendido: bool):
    """Matriz de migración de Lead (Diseño Técnico Gate 5.3 §11) aplicada
    campo por campo, en vivo: cada escritura sobre Lead que toque un campo
    ya migrado a Conversation/Opportunity se refleja ahí también. Get-only
    (nunca crea Contact/Conversation/Opportunity acá)."""
    contact = await _obtener_contact(session, lead.negocio_id, lead.telefono)
    if contact is None:
        return
    # La Bandeja (lista, cabecera del chat y buscador) lee el nombre de
    # Contact.nombre; Gabi y el panel lo escriben en Lead.nombre.
    if "nombre" in campos:
        contact.nombre = campos["nombre"] or None
    conversation = await _obtener_conversation_activa(session, contact.id)
    if conversation is None:
        return
    campos_conversation = {k: v for k, v in campos.items() if k in _CAMPOS_CONVERSATION}
    if campos_conversation:
        for campo, valor in campos_conversation.items():
            setattr(conversation, campo, valor)
        conversation.actualizado = datetime.utcnow()

    opportunity = await _obtener_opportunity_vigente(session, conversation.id)
    if opportunity is None:
        return
    campos_opportunity = {k: v for k, v in campos.items() if k in _CAMPOS_OPPORTUNITY}
    if campos_opportunity:
        for campo, valor in campos_opportunity.items():
            setattr(opportunity, campo, valor)
        opportunity.actualizado = datetime.utcnow()
    if transicion_a_vendido:
        opportunity.fecha_cierre = lead.fecha_cierre
        conversation.pausado_manual = True


def _filtrar_campos(campos: dict, campos_explicitos: tuple[str, ...]) -> dict:
    """Regla de "vacío significa bórralo" de actualizar_lead, extraída para
    que guardar_venta —que escribe los mismos campos del lead pero dentro de
    su propia transacción— aplique exactamente el mismo criterio en vez de
    una copia que pueda desincronizarse."""
    return {
        k: (v if v not in ("",) else None) if k in campos_explicitos else v
        for k, v in campos.items()
        if v or k in campos_explicitos
    }


async def listar_lineas_venta(telefono: str, con_metadatos: bool = False) -> list[dict]:
    """Líneas de venta de un lead (un artefacto, varios, o un mix con
    servicio), en el orden en que se agregaron.

    Gate 5.3: interfaz pública sin cambios (telefono); internamente resuelve
    la Opportunity vigente vía Contact/Conversation y filtra por
    `opportunity_id` — nunca `telefono` contra `lineas_venta` (esa columna ya
    no existe, ver clase LineaVenta). Retorna `[]` si todavía no hay
    Conversation/Opportunity para este teléfono.

    `con_metadatos` agrega `id` y `creado` — los pide el DTO JSON del detalle
    de Lead, y NO viajan por defecto a propósito: el panel legacy serializa
    esta misma lista con json.dumps() para precargar el carrito del cierre de
    venta, y un datetime crudo ahí revienta la serialización."""
    async with async_session() as session:
        conversation = await _obtener_conversation_activa_por_telefono(session, telefono)
        if conversation is None:
            return []
        opportunity = await _obtener_opportunity_vigente(session, conversation.id)
        if opportunity is None:
            return []
        query = (
            select(LineaVenta)
            .where(LineaVenta.opportunity_id == opportunity.id, LineaVenta.negocio_id == opportunity.negocio_id)
            .order_by(LineaVenta.id.asc())
        )
        result = await session.execute(query)
        return [
            {
                "producto_id": l.producto_id,
                "producto": l.producto, "precio": l.precio, "marca": l.marca, "proveedor": l.proveedor,
                **({"id": l.id, "creado": l.creado} if con_metadatos else {}),
            }
            for l in result.scalars().all()
        ]


async def listar_lineas_venta_de_muchos(telefonos: list[str], negocio_id: str) -> dict[str, list[dict]]:
    """Igual que listar_lineas_venta pero para varios leads a la vez — para
    pintar la tabla de leads/exportar sin hacer un query por fila (N+1).

    Gate 5.3: resuelve primero (Contact, Conversation activa, Opportunity
    vigente) de cada teléfono en consultas agregadas (no N+1), luego trae
    las líneas de todas esas Opportunities de una sola vez, filtrando por
    `opportunity_id` — nunca `telefono` contra `lineas_venta`.

    Gate 5.6 — corrección: resolvía `Contact` por `telefono` SIN `negocio_id`
    — con el mismo teléfono existiendo como Contact en dos Negocios, podía
    adjuntar producto/marca/proveedor/precio de la venta de OTRO Negocio en
    la tabla de Métricas y sus exports (hallazgo de la investigación de Gate
    5.6). `negocio_id` ahora es obligatorio y candado doble: en la resolución
    de `Contact` y en el `WHERE` final de `LineaVenta` — mismo criterio ya
    documentado en el docstring de la clase `LineaVenta`."""
    if not telefonos:
        return {}
    async with async_session() as session:
        contacts = (await session.execute(
            select(Contact.id, Contact.telefono).where(
                Contact.telefono.in_(telefonos), Contact.negocio_id == negocio_id,
            )
        )).all()
        contact_id_por_telefono = {c.telefono: c.id for c in contacts}
        if not contact_id_por_telefono:
            return {}
        conversations = (await session.execute(
            select(Conversation.id, Conversation.contact_id)
            .where(Conversation.contact_id.in_(contact_id_por_telefono.values()), Conversation.estado == "activa")
        )).all()
        conversation_id_por_contact = {c.contact_id: c.id for c in conversations}
        if not conversation_id_por_contact:
            return {}
        opportunities = (await session.execute(
            select(Opportunity.id, Opportunity.conversation_id, Opportunity.creado)
            .where(Opportunity.conversation_id.in_(conversation_id_por_contact.values()))
            .order_by(Opportunity.creado.desc())
        )).all()
        # La primera (más reciente) por conversation_id es la vigente.
        opportunity_id_por_conversation: dict[str, str] = {}
        for o in opportunities:
            opportunity_id_por_conversation.setdefault(o.conversation_id, o.id)
        opportunity_id_por_telefono = {
            telefono: opportunity_id_por_conversation.get(conversation_id_por_contact.get(contact_id_por_telefono.get(telefono)))
            for telefono in telefonos
            if contact_id_por_telefono.get(telefono) and conversation_id_por_contact.get(contact_id_por_telefono[telefono])
        }
        ids_opportunity = [oid for oid in opportunity_id_por_telefono.values() if oid]
        if not ids_opportunity:
            return {}
        query = (
            select(LineaVenta)
            .where(LineaVenta.opportunity_id.in_(ids_opportunity), LineaVenta.negocio_id == negocio_id)
            .order_by(LineaVenta.id.asc())
        )
        result = await session.execute(query)
        lineas_por_opportunity: dict[str, list[dict]] = {}
        for l in result.scalars().all():
            lineas_por_opportunity.setdefault(l.opportunity_id, []).append(
                {"producto": l.producto, "precio": l.precio, "marca": l.marca, "proveedor": l.proveedor}
            )
        return {
            telefono: lineas_por_opportunity.get(oid, [])
            for telefono, oid in opportunity_id_por_telefono.items()
        }


async def ids_de_productos_existentes(ids: set[int], negocio_id: str) -> set[int]:
    """De los `id` de Producto que le pasan, cuáles existen realmente EN ESTE
    NEGOCIO. Se usa para validar el `producto_id` que manda el carrito del
    cierre de venta antes de persistirlo — un id real pero de otro Negocio
    debe rechazarse igual que un id inexistente (Gate 4.4).

    A propósito NO filtra por `activo`: un producto puede desactivarse del
    catálogo después de haberse vendido, y editar esa venta vieja no debería
    volverse imposible por eso. La pregunta acá es "¿este id es un producto
    real de este Negocio?", no "¿se puede vender hoy?"."""
    if not ids:
        return set()
    async with async_session() as session:
        result = await session.execute(
            select(Producto.id).where(Producto.id.in_(ids), Producto.negocio_id == negocio_id)
        )
        return {fila[0] for fila in result.all()}


async def guardar_venta(
    telefono: str,
    lineas: list[dict],
    campos: dict,
    campos_explicitos: tuple[str, ...] = (),
    revertir_resultado_al_vaciar: bool = False,
):
    """Escribe un cierre de venta COMPLETO en UNA sola transacción: reemplaza
    todas las líneas de venta del lead y actualiza los campos del lead (forma
    de pago, resultado, y los efectos de la transición a "vendido").

    Antes eran dos escrituras con dos commits (guardar_lineas_venta +
    actualizar_lead): si la segunda fallaba, el lead quedaba con las líneas
    nuevas y la forma de pago vieja, o vendido sin líneas. Acá o entra todo o
    no entra nada.

    El carrito siempre manda el estado completo (lo que quedó tras
    agregar/quitar productos), no un delta — por eso se borran todas las
    líneas y se reinsertan.

    `revertir_resultado_al_vaciar`: si el carrito queda vacío y el lead estaba
    en "vendido" TENIENDO líneas (es decir, estaba vendido por esta misma
    venta), se le quita el resultado en vez de dejarlo huérfano —vaciar el
    carrito borraba las líneas pero dejaba el lead "vendido" sin nada
    vendido—. Vuelve a None (sin resultado), no a un valor anterior: no hay
    ninguna fuente que sepa qué resultado tenía antes de venderse, y elegir
    uno sería inventarlo. Junto con el resultado se limpia `fecha_cierre`,
    que solo tiene sentido mientras el lead esté vendido. `pausado_manual` NO
    se toca al revertir: ese campo tiene otras fuentes (un asesor respondió
    desde la app de WhatsApp Business) y apagarlo acá podría hacer que Gabi
    pise a un humano que está atendiendo."""
    async with async_session() as session:
        lead = _exigir_lead_existente(await session.get(Lead, telefono), telefono, "guardar_venta")

        # Gate 5.3 — resuelto ACÁ (antes del chequeo de abajo), get-only, para
        # que el conteo de "¿había líneas?" pueda usar la clave fuerte
        # `opportunity_id` en vez de `telefono` — REGLA CRÍTICA de LineaVenta:
        # la columna `telefono` ya no existe en esta tabla (Gate 5.3), nunca
        # se vuelve a consultar por ella.
        contact = await obtener_o_crear_contact(session, lead.negocio_id, telefono)
        conversation = await _obtener_conversation_activa(session, contact.id)
        opportunity = await _obtener_opportunity_vigente(session, conversation.id) if conversation else None

        if not lineas and revertir_resultado_al_vaciar and lead.resultado == "vendido":
            habia_lineas = bool(opportunity) and await session.scalar(
                select(func.count()).select_from(LineaVenta).where(
                    LineaVenta.opportunity_id == opportunity.id, LineaVenta.negocio_id == opportunity.negocio_id,
                )
            )
            if habia_lineas:
                # Además del resultado: la forma de pago también queda
                # huérfana sin líneas ("contado / QR" de una venta que ya no
                # existe). Es la misma asimetría, así que se limpia junto —
                # `cuotas` ya viaja como campo explícito desde el servicio.
                campos = {
                    **campos,
                    "resultado": None, "fecha_cierre": None,
                    "modalidad_pago": None, "medio_pago": None,
                }
                campos_explicitos = tuple(campos_explicitos) + (
                    "resultado", "fecha_cierre", "modalidad_pago", "medio_pago",
                )

        campos = _filtrar_campos(campos, tuple(campos_explicitos))
        transicion_a_vendido = _es_transicion_a_vendido(lead, campos)
        for campo, valor in campos.items():
            setattr(lead, campo, valor)
        if transicion_a_vendido:
            _marcar_cierre_vendido(lead)
        lead.actualizado = datetime.utcnow()

        # Gate 5.3 — mirror hacia Contact/Conversation/Opportunity, EN LA
        # MISMA transacción que el escrito de Lead (cierra en el mismo commit
        # el defecto de "dos transacciones separadas" encontrado en el
        # bloque de Diseño Técnico: acá Lead + Opportunity + LineaVenta caen
        # en un solo commit). `opportunity_id` es la clave fuerte del
        # reemplazo de líneas — REGLA CRÍTICA: nunca `telefono` en solitario.
        # (`contact`/`conversation`/`opportunity` ya resueltos arriba.)
        if opportunity is not None:
            await session.execute(
                delete(LineaVenta).where(
                    LineaVenta.opportunity_id == opportunity.id,
                    LineaVenta.negocio_id == opportunity.negocio_id,
                )
            )
            for l in lineas:
                session.add(LineaVenta(
                    opportunity_id=opportunity.id, negocio_id=opportunity.negocio_id,
                    producto_id=l.get("producto_id"), producto=l["producto"],
                    precio=l.get("precio") or None, marca=l.get("marca") or None,
                    proveedor=l.get("proveedor") or None,
                ))
            for campo, valor in campos.items():
                if hasattr(Opportunity, campo):
                    setattr(opportunity, campo, valor)
            if transicion_a_vendido:
                opportunity.fecha_cierre = lead.fecha_cierre
                conversation.pausado_manual = True
            opportunity.version = Opportunity.version + 1
            conversation.version = Conversation.version + 1
        # Si todavía no hay Conversation/Opportunity para este teléfono (caso
        # de un Lead pre-existente cuyo backfill no corrió, o un entorno de
        # test que no pasó por el webhook), NO se inventa ninguna acá — el
        # mirror simplemente no aplica; Lead sigue siendo la fuente de verdad
        # hasta que exista. No bloquea el flujo legacy.

        await session.commit()


async def asignar_asesor_a_lead(telefono: str, asesor: str | None, automatico: bool = False):
    """Asigna (o reasigna) un lead a un asesor y lo marca como no visto por él.
    Función aparte de actualizar_lead porque ésta descarta valores 'falsy'
    (y visto_asesor=False necesita poder guardarse explícitamente).

    `asesor=None` DESASIGNA: el lead vuelve a quedar sin dueño. En ese caso
    visto_asesor vuelve a True —igual que en liberar_asignacion, la otra vía
    por la que un lead se queda sin asesor—: el indicador de "Nuevo" es para
    el asesor asignado, y sin asignado no tiene a quién avisarle. No se toca
    pausado_manual acá (sí lo hace liberar_asignacion): eso responde a que el
    caso anterior se cerró, no a que un supervisor quitó la asignación.

    `automatico=True` es la vía de Gabi (escalado por falla técnica, por baja
    confianza, o derivación a asesor; también el reparto de asignacion.py):
    además de asignar, avanza la versión del lead y deja un evento en el
    Timeline, porque hasta ahora una reasignación automática cambiaba el dueño
    del lead SIN dejar rastro y sin que un humano que tuviera el formulario
    abierto se enterara al guardar. La asignación se aplica igual, siempre —no
    puede fallar ni bloquearse por concurrencia (ver _avanzar_version)—; lo
    que cambia es que quien venga con la versión vieja ahora recibe un 409.

    Con `automatico=False` (default) el comportamiento es el de antes: la ruta
    del panel ya avanzó la versión con intentar_avanzar_version() y registra
    su propio evento con el autor humano — hacerlo también acá duplicaría el
    evento y saltearía la versión de dos en dos.

    Nota para `enrutar_posventa_si_corresponde` (Punto 3, 2026-09-28): esta
    función solo deja un evento en el Timeline cuando el asesor CAMBIA
    (`anterior != asesor`) — pero el ruteo a posventa suele apuntar al MISMO
    asesor que ya figuraba en el `Lead` (DR-4 abre una Conversation nueva
    SIN asesor, pero no toca `Lead.asesor_asignado`, que sigue mostrando al
    vendedor original hasta acá). Por eso ese llamador registra su propio
    evento aparte, en vez de depender de este (ver esa función).

    Punto 2 (2026-09-30) — acá también se arma/desarma `Lead.derivado_en`,
    el reloj de rotación por inactividad (ver `listar_leads_para_rotar_o_
    liberar`): `automatico=True` con un `asesor` real arma una ventana
    fresca de 30 min (Gabi deriva por primera vez, o
    `rotar_asignacion_por_inactividad` pasa al segundo asesor — en ambos
    casos hay una persona nueva que todavía no respondió, corresponde
    monitorear). `automatico=False` (una persona asignó/reasignó a mano
    desde el panel) SIEMPRE lo desarma — "ya el lead es de esa persona",
    una decisión humana no se segunda-adivina con un timeout automático.
    `asesor=None` (desasignación) también lo desarma — sin nadie asignado
    no hay a quién monitorear. `enrutar_posventa_si_corresponde` (Punto 3)
    es la única excepción real: llama a esta función con automatico=True
    pero para un `asesor` que YA era el mismo antes (nunca None), así que
    la arma igual — por eso esa función limpia `derivado_en` ella misma
    después, a propósito (un caso de posventa nunca debe rotar/liberarse
    por inactividad, es un flujo silencioso aparte)."""
    async with async_session() as session:
        # Gate 5.2 (H2): esta función nunca es el camino de creación de un
        # Lead — para cuando llega acá (asignación, automática o manual),
        # actualizar_lead() ya debió haber creado el Lead con su negocio_id
        # resuelto desde el Canal de entrada.
        lead = _exigir_lead_existente(await session.get(Lead, telefono), telefono, "asignar_asesor_a_lead")
        anterior = lead.asesor_asignado
        lead.asesor_asignado = asesor
        lead.visto_asesor = asesor is None
        lead.derivado_en = datetime.utcnow() if (automatico and asesor is not None) else None
        if automatico and asesor is not None:
            # 2026-10-07: una asignación automática NUEVA arranca el ciclo de espera de cero. Antes los
            # contadores quedaban como estuvieran: un lead liberado a mano tras una rotación conservaba
            # `veces_rotado_espera=1` (al reasignarlo iría directo a supervisión, sin segundo asesor) o
            # minutos viejos (rotaba antes de los 30 min). `rotar_asignacion_por_inactividad` fija
            # `veces_rotado_espera=1` DESPUÉS de llamar acá, así que la rotación no se afecta.
            lead.minutos_espera_asesor = 0
            lead.veces_rotado_espera = 0
        if asesor is not None:
            lead.escalado_supervision_en = None  # ya tiene dueño: sale de la cola de supervisión
        if automatico:
            _avanzar_version(lead, es_nuevo=False)
        lead.actualizado = datetime.utcnow()

        # Gate 5.3 — mirror best-effort (get-only) hacia Conversation.
        contact = await _obtener_contact(session, lead.negocio_id, telefono)
        if contact is not None:
            conversation = await _obtener_conversation_activa(session, contact.id)
            if conversation is not None:
                conversation.asesor_asignado_id = asesor
                conversation.visto_asesor = asesor is None
                conversation.version = Conversation.version + 1
                conversation.actualizado = datetime.utcnow()

        await session.commit()

    if automatico and anterior != asesor:
        # Fuera de la transacción de arriba a propósito: el Timeline es
        # append-only y su propio commit, igual que en las 3 escrituras
        # humanas del CRM (ver dashboard.py). `autor=None` = cambio
        # automático, tal como documenta EventoLead. Solo se anota si el
        # dueño realmente cambió: reasignar al mismo asesor no es un hecho.
        if asesor:
            tipo, descripcion = "asignado_automatico", f"Gabi asignó el lead automáticamente a {asesor}"
        else:
            tipo, descripcion = "desasignado_automatico", "Se quitó la asignación automáticamente"
        await registrar_evento_lead(
            telefono, tipo=tipo, descripcion=descripcion, autor=None,
            payload={"campo": "asesor_asignado", "anterior": anterior, "nuevo": asesor},
        )


async def marcar_lead_no_visto(telefono: str):
    """Reactiva el indicador de 'Nuevo' cuando un cliente ya asignado a un
    asesor vuelve a escribir (aunque ya se hubiera marcado como visto antes),
    para que el asesor no se pierda el mensaje de seguimiento."""
    async with async_session() as session:
        lead = await session.get(Lead, telefono)
        if lead is not None:
            lead.visto_asesor = False
            lead.actualizado = datetime.utcnow()
            await session.commit()


async def liberar_asignacion(telefono: str, autor: str | None = None, motivo: str = "caso_cerrado"):
    """Quita la asignación de un lead y limpia pausado_manual — Gabi retoma
    la atención. Dos llamadores, con la misma mecánica pero distinto origen:

    1. El webhook (main.py), cuando un caso YA CERRADO recibe un mensaje
       nuevo del cliente — llamada automática, sin `autor` (default None,
       motivo="caso_cerrado"): comportamiento IDÉNTICO al de antes de que
       este método aceptara estos parámetros.
    2. El endpoint manual "reactivar a Gabi" (dashboard.py), donde una
       persona del equipo decide devolverle el control a Gabi en un caso
       que sigue ABIERTO — pasa su propio nombre como `autor` y
       motivo="reactivado_manual", para que el Timeline describa la acción
       real en vez de la justificación automática ("el caso ya estaba
       cerrado"), que sería falsa en ese escenario.

    Es una escritura sin control de concurrencia optimista (a diferencia de
    las 3 escrituras humanas del CRM que sí usan intentar_avanzar_version):
    avanza la versión del lead incondicionalmente y deja un evento en el
    Timeline — cambiar el dueño de un lead sin dejar rastro es justo lo que
    hacía invisible este flujo. Se aplica siempre; nunca se bloquea por
    concurrencia (ver _avanzar_version)."""
    async with async_session() as session:
        lead = await session.get(Lead, telefono)
        if lead is None:
            return
        anterior = lead.asesor_asignado
        lead.asesor_asignado = None
        lead.pausado_manual = False
        lead.escalado_supervision_en = None  # devolverlo a Gabi lo saca de la cola de supervisión
        lead.cerrado_definitivamente_en = None
        lead.visto_asesor = True
        _avanzar_version(lead)
        lead.actualizado = datetime.utcnow()

        # Gate 5.3 — mirror best-effort (get-only) hacia Conversation. Si el
        # llamador es el webhook automático (main.py), `resolver_conversation_
        # activa` ya corrió ANTES y ya abrió la Conversation nueva si DR-4 lo
        # exigía — acá solo se refleja el estado limpio (no evalúa DR-4 de
        # nuevo, evita duplicar la lógica de apertura).
        contact = await _obtener_contact(session, lead.negocio_id, telefono)
        if contact is not None:
            conversation = await _obtener_conversation_activa(session, contact.id)
            if conversation is not None:
                conversation.asesor_asignado_id = None
                conversation.pausado_manual = False
                conversation.cerrado_definitivamente_en = None
                conversation.visto_asesor = True
                conversation.version = Conversation.version + 1
                conversation.actualizado = datetime.utcnow()

        await session.commit()

    descripcion = {
        "caso_cerrado": "El caso anterior ya estaba cerrado — se liberó la asignación y Gabi retomó la atención",
        "timeout_inactividad": "El asesor asignado no respondió a tiempo — se liberó la asignación automáticamente y Gabi retomó la atención",
        "cierre_definitivo": "El caso había quedado cerrado definitivamente — el cliente volvió a escribir, se liberó la asignación y Gabi retomó la atención",
    }.get(motivo, "Devolvió el control de la conversación a Gabi")
    await registrar_evento_lead(
        telefono, tipo="desasignado_automatico" if autor is None else "desasignado",
        descripcion=descripcion,
        autor=autor,
        payload={"campo": "asesor_asignado", "anterior": anterior, "nuevo": None, "motivo": motivo},
    )


# Punto 2 (2026-09-29) / calendario de negocio (2026-10-12): ya no hay una copia propia del cálculo de horario acá.
# `ejecutar_ciclo_de_espera` consulta `obtener_calendario_negocio` (horario semanal + feriados y días especiales,
# lógica pura en agent/calendario_negocio.py, que memory.py SÍ puede importar porque no depende de memory).

# Anti-avalancha (2026-10-12, apagado por defecto): con N > 0, el reloj de 30 min corre solo para los primeros N casos
# sin respuesta de cada asesor (por antigüedad de la derivación); los demás quedan «en fila» y no suman minutos.
CLAVE_ROTACION_RELOJ_MAX_CASOS = "rotacion_reloj_max_casos_por_asesor"


async def listar_leads_para_rotar_o_liberar(
    intervalo_minutos: int = 5, umbral_rotacion_minutos: int = 30,
) -> list[dict]:
    """Compatibilidad: devuelve solo los leads a ROTAR. Los que ya agotaron sus
    dos rotaciones se resuelven igual dentro (ver `ejecutar_ciclo_de_espera`,
    que además informa cuáles pasaron a la cola de supervisión)."""
    return (await ejecutar_ciclo_de_espera(intervalo_minutos, umbral_rotacion_minutos))["a_rotar"]


async def ejecutar_ciclo_de_espera(
    intervalo_minutos: int = 5, umbral_rotacion_minutos: int = 30,
) -> dict:
    """Una corrida del ciclo de espera del asesor. Devuelve
    `{"a_rotar": [...], "escalados": [telefonos]}`: los `a_rotar` los resuelve
    quien llama (elegir al segundo asesor vive en agent/asignacion.py) y los
    `escalados` ya pasaron a la cola de supervisión DENTRO de esta función.

    2026-10-04 — dos correcciones tras la primera corrida real del Cron de
    5 minutos (liberó un lead con resultado "Agendado", y el script decía
    "ningún lead cruzó el umbral" porque no contaba las liberaciones):
    - Solo entran leads SIN resultado. Si una persona ya le puso resultado
      (agendado, vendido, lo que sea), ya lo trabajó: nunca rota ni escala.
    - Los que agotan las dos rotaciones YA NO vuelven a Gabi: pasan a la cola
      de supervisión (ver `enviar_a_cola_de_supervision`).

    Punto 2 (2026-09-29, REDISEÑADO 2026-09-30 tras un incidente real en
    producción) — reemplaza a la antigua `liberar_asignaciones_inactivas`
    (24h de RELOJ, sin turno). Pedido explícito del usuario: "no veo viable
    que una persona permanezca sin contestar 24 horas después de que Gabi
    lo asignó".

    **El incidente que motivó el rediseño**: la primera versión de esta
    función detectaba "ciclo nuevo" comparando el timestamp del ÚLTIMO
    MENSAJE DEL CLIENTE — así que cuando un asesor reabría un resultado
    viejo (sin que el cliente hubiera escrito nada nuevo), el mensaje de
    hace DÍAS se trataba como si acabara de llegar, arrancando una cuenta
    regresiva de 30 min falsa. Peor: como el criterio de candidatura era
    puramente "resultado abierto + asesor asignado", una reasignación
    MANUAL (una persona resolviendo el caso a mano) no apagaba nada — el
    cron siguiente la deshacía igual. En un caso real (Pedro Padilla
    Medrano) esto rotó y liberó el mismo lead 5 veces en 3 horas, incluso
    deshaciendo una asignación manual 50 segundos después de hecha, y otra
    vez después de que el asesor ya lo había marcado "agendado".

    **El rediseño — basado en EVENTO, no en contenido**: ahora solo se
    considera un lead si `Lead.derivado_en` está seteado. Ese campo se
    arma (con la hora actual) EXCLUSIVAMENTE dentro de
    `asignar_asesor_a_lead` cuando la asignación es automática (Gabi deriva
    por primera vez, o `rotar_asignacion_por_inactividad` pasa al segundo
    asesor) — nunca por un cambio de resultado. Se desarma (vuelve a None)
    apenas el asesor responde de verdad (`guardar_mensaje` con role=
    "asesor", o el echo de coexistencia) o apenas una PERSONA reasigna a
    mano (`asignar_asesor_a_lead` con automatico=False — una decisión
    humana nunca se segunda-adivina). Mientras `derivado_en` sea None, este
    cron directamente no lo mira — un resultado que se reabre sobre un
    mensaje viejo, o un lead que un supervisor ya resolvió a mano, quedan
    afuera con certeza, no por casualidad de timing.

    Pensado para correr cada `intervalo_minutos` (Cron Schedule de Railway
    "*/5 * * * *"). Por cada lead con `derivado_en` armado:
    - Solo suma `intervalo_minutos` a `Lead.minutos_espera_asesor` si AHORA
      MISMO el negocio está dentro de su horario de atención (Horario
      Atencion) Y el asesor asignado está `disponible` — las horas fuera de
      turno no cuentan. Desde el calendario de negocio (2026-10-12) «dentro
      de su horario» también descarta feriados y días especiales cerrados
      (`agent/calendario_negocio.py`, leído fresco). Anti-avalancha opcional
      (`rotacion_reloj_max_casos_por_asesor`, 0 = apagado): con N > 0 solo
      corre el reloj de los N casos más antiguos de cada asesor.
    - Al llegar a `umbral_rotacion_minutos` (30 por defecto): si
      `veces_rotado_espera == 0`, el lead califica para ROTAR — se retorna
      en la lista (memory.py no elige al siguiente asesor, eso vive en
      agent/asignacion.py, que sí sabe de nivel/carga; ver
      `agent/asignacion.py::rotar_leads_inactivos`, el llamador real). Si
      `veces_rotado_espera >= 1` (el SEGUNDO asesor tampoco respondió en
      sus propios 30 min), se libera acá mismo (reusa `liberar_asignacion`,
      motivo="timeout_inactividad" de siempre).

    Retorna solo los que necesitan ROTAR: `[{"telefono", "negocio_id",
    "asesor_actual", "interes", "minutos_espera"}, ...]`.

    Defensa en profundidad (2026-09-30): además de `derivado_en`, la query
    excluye explícitamente `pausado_manual == True`. En teoría ya no hace
    falta — cada camino real de escritura de `resultado` (`intentar_cambiar_
    resultado_opportunity`, `cerrar_opportunity_con_venta`, `actualizar_lead`)
    desarma `derivado_en` en la misma transacción que marca `pausado_manual`
    — pero "Close-Won es indefinido" es una garantía demasiado sensible (ya
    hubo un incidente real) para depender de que nadie agregue un cuarto
    camino de escritura sin acordarse de este desarme. Un lead pausado a
    mano nunca debe rotar ni liberarse, así se haya colado por donde se
    haya colado."""
    ahora_utc = datetime.utcnow()
    a_liberar: list[str] = []
    a_rotar: list[dict] = []

    async with async_session() as session:
        query = select(Lead).where(
            Lead.derivado_en.is_not(None), Lead.asesor_asignado.is_not(None),
            Lead.pausado_manual.is_(False),
            sa_or(Lead.resultado.is_(None), Lead.resultado == ""),
        )
        candidatos = sorted(
            (await session.execute(query)).scalars().all(), key=lambda l: (l.derivado_en, l.telefono),
        )

        # Calendario de negocio (2026-10-12): horario semanal + feriados y días especiales, leído FRESCO (el Cron
        # no usa la caché de 60 s). Un día cerrado por calendario no suma minutos de turno a nadie.
        cache_calendarios: dict[str, cal_negocio.Calendario] = {}
        cache_tope_en_fila: dict[str, int] = {}
        posicion_en_fila: dict[tuple[str, str], int] = {}
        cache_disponibilidad: dict[tuple[str, str], bool] = {}

        for lead in candidatos:
            clave_asesor = (lead.negocio_id, lead.asesor_asignado)
            posicion = posicion_en_fila.get(clave_asesor, 0)     # 0 = el caso más antiguo de ese asesor
            posicion_en_fila[clave_asesor] = posicion + 1

            if lead.negocio_id not in cache_calendarios:
                cache_calendarios[lead.negocio_id] = await obtener_calendario_negocio(lead.negocio_id, fresco=True)
            if not cal_negocio.esta_abierto(ahora_utc, cache_calendarios[lead.negocio_id]):
                continue

            # Anti-avalancha (apagado por defecto = 0): solo los primeros N casos de cada asesor corren el reloj.
            if lead.negocio_id not in cache_tope_en_fila:
                try:
                    cache_tope_en_fila[lead.negocio_id] = max(0, int(
                        await obtener_configuracion(CLAVE_ROTACION_RELOJ_MAX_CASOS, "0", negocio_id=lead.negocio_id)
                    ))
                except (TypeError, ValueError):
                    cache_tope_en_fila[lead.negocio_id] = 0
            tope = cache_tope_en_fila[lead.negocio_id]
            if tope > 0 and posicion >= tope:
                continue    # «en fila»: el reloj de 30 min arranca cuando el asesor despeje casos más antiguos
            if clave_asesor not in cache_disponibilidad:
                usuario = await _obtener_usuario_orm(session, lead.negocio_id, lead.asesor_asignado)
                cache_disponibilidad[clave_asesor] = bool(usuario and usuario.disponible)
            if not cache_disponibilidad[clave_asesor]:
                continue

            lead.minutos_espera_asesor += intervalo_minutos
            if lead.minutos_espera_asesor < umbral_rotacion_minutos:
                continue

            if lead.veces_rotado_espera == 0:
                a_rotar.append({
                    "telefono": lead.telefono, "negocio_id": lead.negocio_id,
                    "asesor_actual": lead.asesor_asignado, "interes": lead.interes,
                    "minutos_espera": lead.minutos_espera_asesor,
                })
            else:
                a_liberar.append(lead.telefono)

        await session.commit()

    escalados: list[str] = []
    for telefono in a_liberar:
        if await enviar_a_cola_de_supervision(telefono, motivo="timeout_inactividad"):
            escalados.append(telefono)

    return {"a_rotar": a_rotar, "escalados": escalados}


async def enviar_a_cola_de_supervision(telefono: str, motivo: str = "timeout_inactividad") -> bool:
    """2026-10-04 — destino de un lead que NINGÚN asesor atendió (dos rotaciones
    sin respuesta, o no había otro asesor disponible). Antes se "liberaba":
    quedaba sin asesor y Gabi lo retomaba, aunque Gabi ya lo había derivado
    porque no podía seguir. Ahora se queda sin asesor, con Gabi PAUSADA
    (`pausado_manual`, mismo estado que usa `pausar_gabi_manual`), marcado
    `escalado_supervision_en`: aparece en la Zona de acción de Inicio del
    supervisor y NO se reasigna solo al primer asesor que se ponga disponible.

    Nunca actúa sobre un lead con resultado (False): ya lo trabajó una persona.
    Reinicia el reloj de espera. Devuelve True si lo escaló."""
    async with async_session() as session:
        lead = await session.get(Lead, telefono)
        if lead is None or (lead.resultado or "") != "":
            return False
        anterior = lead.asesor_asignado
        ahora = datetime.utcnow()
        lead.asesor_asignado = None
        lead.pausado_manual = True
        lead.escalado_supervision_en = ahora
        lead.derivado_en = None
        lead.minutos_espera_asesor = 0
        lead.veces_rotado_espera = 0
        lead.visto_asesor = True
        if not lead.paso_flujo:
            lead.paso_flujo = "derivado_asesor"
        _avanzar_version(lead)
        lead.actualizado = ahora

        contact = await _obtener_contact(session, lead.negocio_id, telefono)
        if contact is not None:
            conversation = await _obtener_conversation_activa(session, contact.id)
            if conversation is not None:
                conversation.asesor_asignado_id = None
                conversation.pausado_manual = True
                conversation.visto_asesor = True
                conversation.version = Conversation.version + 1
                conversation.actualizado = ahora
        await session.commit()

    await registrar_evento_lead(
        telefono, tipo="desasignado_automatico",
        descripcion=(
            "Ningún asesor respondió a tiempo — el caso pasó a la cola de supervisión. "
            "Gabi no lo retoma: lo debe tratar un supervisor."
        ),
        autor=None,
        payload={"campo": "asesor_asignado", "anterior": anterior, "nuevo": None, "motivo": motivo, "destino": "supervision"},
    )
    return True


async def rotar_asignacion_por_inactividad(telefono: str, asesor_anterior: str, asesor_nuevo: str, minutos_espera: int) -> None:
    """Punto 2 (2026-09-29) — aplica la rotación que decidió `listar_leads_
    para_rotar_o_liberar`: reasigna (reusa `asignar_asesor_a_lead`,
    automatico=True — mismo mirror a Conversation y el mismo evento
    "asignado_automatico" de cualquier reasignación automática) y además
    reinicia el contador (`minutos_espera_asesor=0`) y marca
    `veces_rotado_espera=1`, para que la PRÓXIMA corrida sepa que ya no
    queda otra rotación disponible — si este segundo asesor tampoco
    responde en 30 min, el siguiente paso es liberar, no rotar de nuevo.

    Deja su PROPIO evento en el Timeline además del genérico de
    `asignar_asesor_a_lead`: un supervisor necesita distinguir "Gabi lo
    derivó" de "nadie contestó en 30 minutos de turno y se rotó" — son
    señales de eficiencia distintas, y esta es la que alimenta el
    seguimiento de asesores."""
    await asignar_asesor_a_lead(telefono, asesor_nuevo, automatico=True)
    async with async_session() as session:
        lead = await session.get(Lead, telefono)
        if lead is not None:
            lead.minutos_espera_asesor = 0
            lead.veces_rotado_espera = 1
            await session.commit()
    await registrar_evento_lead(
        telefono, tipo="rotado_automatico_sin_respuesta",
        descripcion=f"{asesor_anterior} no respondió en {minutos_espera} min de turno — se rotó automáticamente a {asesor_nuevo}",
        autor=None,
        payload={"asesor_anterior": asesor_anterior, "asesor_nuevo": asesor_nuevo, "minutos_espera": minutos_espera},
    )


async def cerrar_lead_definitivamente(telefono: str, negocio_id: str, autor: str | None) -> bool:
    """Cierre EXPLÍCITO (Gate 2026-09-23) — dos orígenes, misma mecánica
    (mismo patrón dual que `liberar_asignacion`):
    1. Botón "Cerrar definitivamente" en la Ficha del Lead — `autor` es
       quien lo apretó.
    2. `cerrar_leads_definitivamente_inactivos` / `cerrar_ventas_sin_
       seguimiento` (los Cron de inactividad del cliente) — llamada
       automática, `autor=None`.

    No exige ningún umbral de silencio por sí sola (eso lo evalúa quien
    llama, versión 2 arriba) — un `autor=None` no es "sin validar", es
    "lo cerró el sistema, no una persona". Rechaza (retorna False, el
    router en dashboard.py lo traduce a 400) si el lead no existe, no es
    de este Negocio, o el `resultado` todavía no es uno cerrado.

    Punto 3 (2026-09-28) — "vendido" YA NO se rechaza acá. Antes sí
    (Close-Won es indefinido, mismo criterio que pausado_manual de una
    venta y "reactivar-gabi"), pero ese criterio hablaba de REACTIVAR A
    GABI, no de si el caso puede marcarse cerrado — y esta función nunca
    reactivó nada por sí sola (ver el párrafo de abajo). Lo que faltaba
    era la otra mitad: cuando el cliente de una venta ya cerrada vuelve a
    escribir, `agent/main.py` (`enrutar_posventa_si_corresponde`) rutea la
    Conversation nueva en silencio al MISMO asesor que hizo la venta —
    nunca a Gabi. El guardado real ("Gabi nunca vuelve a responderle a un
    vendido") sigue intacto y sin tocar en `reactivar_gabi()` y en
    `/conversation/{id}/liberar` (dashboard.py), que rechazan reactivar a
    Gabi para un vendido sin importar este cierre.

    Este cierre por sí solo NO reactiva nada ni notifica a nadie — solo
    deja la puerta abierta para que, cuando el cliente vuelva a escribir,
    `agent/main.py` reconozca `cerrado_definitivamente_en` y libere la
    asignación en ese momento (ver el bloque del webhook)."""
    async with async_session() as session:
        lead = await session.get(Lead, telefono)
        if lead is None or lead.negocio_id != negocio_id:
            return False
        if lead.resultado not in RESULTADOS_CERRADOS:
            return False
        ahora = datetime.utcnow()
        lead.cerrado_definitivamente_en = ahora
        lead.actualizado = ahora

        # Mirror get-only hacia Conversation (Gate 5.3, mismo patrón que
        # liberar_asignacion) — la Nueva Experiencia lee esto, no Lead.
        contact = await _obtener_contact(session, lead.negocio_id, telefono)
        if contact is not None:
            conversation = await _obtener_conversation_activa(session, contact.id)
            if conversation is not None:
                conversation.cerrado_definitivamente_en = ahora
                conversation.actualizado = ahora

        await session.commit()

    # Un vendido NUNCA vuelve a Gabi: si el cliente escribe de nuevo, el caso
    # pasa a postventa con el mismo asesor (`enrutar_posventa_si_corresponde`).
    # El texto anterior ("Gabi retomará la atención") era falso para ese caso.
    consecuencia = (
        "si el cliente vuelve a escribir, el caso pasará a postventa con el mismo asesor de la venta."
        if lead.resultado == "vendido" else
        "si el cliente vuelve a escribir, Gabi retomará la atención sin avisarle a quien lo tenía asignado."
    )
    descripcion = (
        f"Cerró el caso definitivamente — {consecuencia}"
        if autor is not None else
        f"Se cerró el caso automáticamente por inactividad del cliente sobre un resultado ya cerrado — {consecuencia}"
    )
    await registrar_evento_lead(
        telefono, tipo="cerrado_definitivamente" if autor is not None else "cerrado_definitivamente_automatico",
        descripcion=descripcion, autor=autor, payload={"resultado": lead.resultado},
    )
    return True


async def cerrar_lead_definitivamente_via_conversation(conversation_id: str, negocio_id: str, autor: str) -> str | None:
    """Punto de entrada para el endpoint `/conversation/{id}/cerrar-
    definitivamente` (mismo patrón que `liberar_asignacion_via_conversation`)
    — resuelve el teléfono get-only y reusa `cerrar_lead_definitivamente()`
    tal cual, sin duplicar sus validaciones.

    Retorna None si la Conversation no existe/no es de este Negocio, o si
    `cerrar_lead_definitivamente` rechazó el cierre (resultado todavía
    abierto) — el router ya resolvió existencia por separado
    con `resolver_conversation_operable` antes de llamar acá, así que un
    None de esta función siempre se traduce a 400, nunca a 404. Si puede
    cerrar, retorna el teléfono (para que el router arme el DTO de
    respuesta)."""
    async with async_session() as session:
        conversation = await session.get(Conversation, conversation_id)
        if conversation is None or conversation.negocio_id != negocio_id:
            return None
        contact = await session.get(Contact, conversation.contact_id)
        telefono = contact.telefono if contact else None
    if telefono is None:
        return None
    if not await cerrar_lead_definitivamente(telefono, negocio_id, autor):
        return None
    return telefono


_ETIQUETAS_CATEGORIA_TRIAJE = {"recibo": "recibo", "numero_cliente": "número de cliente", "pago_deuda": "pago o deuda"}
_DESCRIPCION_CIERRE_EMERGENCIA = "Triaje automático: emergencia de gas derivada a Emergencias de Cálidda — caso cerrado"

# Resultado con que el triaje tipifica y cierra (2026-10-11, configurable por negocio desde el panel «Derivación
# automática»). Default `consulta_atc` = comportamiento de siempre. Solo valen resultados que (a) cierran (están en
# RESULTADOS_CERRADOS: `cerrar_por_triaje` fija `cerrado_definitivamente_en`) y (b) NO son comerciales: un caso sin
# posibilidad de venta jamás debe quedar como vendido (ni agendado/postventa, que no cierran), ni como
# no_interesado/no_califica (pérdidas comerciales que ensuciarían la tasa de cierre) ni sin_respuesta (lo pone el barrido).
CLAVE_TRIAJE_RESULTADO = "triaje_atc_resultado"
RESULTADO_TRIAJE_POR_DEFECTO = "consulta_atc"
RESULTADOS_TRIAJE_NO_PERMITIDOS = ("vendido", "no_interesado", "no_califica", "sin_respuesta")
# El default va primero (así lo muestra el panel).
RESULTADOS_TRIAJE_PERMITIDOS = (RESULTADO_TRIAJE_POR_DEFECTO,) + tuple(
    r for r in RESULTADOS_CERRADOS if r not in RESULTADOS_TRIAJE_NO_PERMITIDOS and r != RESULTADO_TRIAJE_POR_DEFECTO
)


def resultado_triaje_valido(valor: str | None) -> bool:
    return (valor or "").strip() in RESULTADOS_TRIAJE_PERMITIDOS


def etiqueta_resultado(resultado: str | None) -> str:
    return _ETIQUETAS_RESULTADO_REAPERTURA.get(resultado or "", resultado or "")


async def obtener_resultado_triaje(negocio_id: str) -> str:
    """El resultado configurado para el cierre del triaje; ante cualquier valor inválido o un fallo de lectura,
    el de siempre (`consulta_atc`). Nunca lanza."""
    try:
        valor = (await obtener_configuracion(CLAVE_TRIAJE_RESULTADO, "", negocio_id=negocio_id) or "").strip()
    except Exception:
        return RESULTADO_TRIAJE_POR_DEFECTO
    return valor if resultado_triaje_valido(valor) else RESULTADO_TRIAJE_POR_DEFECTO


async def cerrar_por_triaje(
    telefono: str, negocio_id: str, categoria: str, ahora: datetime | None = None, resultado: str | None = None,
) -> dict | None:
    """Cierre del TRIAJE de temas no comerciales (2026-10-08, agent/triaje_atc.py), en UNA transacción:
    `Lead.resultado` y `Opportunity.resultado` = "consulta_atc", `cerrado_definitivamente_en` en el Lead y en
    la Conversation activa, y dos eventos del Timeline (`resultado_cambiado` con autor None y
    `triaje_atc_cerrado`). NO asigna asesor, NO notifica a nadie y NO toca `paso_flujo`.

    El llamador ya envió (y guardó como mensaje de Gabi) el texto que redirige al cliente a la línea ATC;
    ese mensaje queda ANTES del cierre en el tiempo, así que la condición C4 de
    `evaluar_cierre_cortesia` (nadie escribió después del cierre) deja absorber el "gracias"/"ok" posterior.

    Devuelve `{"conversation_id", "opportunity_id", "cierre_en"}`, o None SIN tocar nada si el caso ya no es
    cerrable (otro negocio, ya cerrado, un humano lo tomó o ya tiene resultado): una persona siempre gana.
    También vale para `categoria="emergencia_gas"` (2026-10-09): un lead con asesor o pausa NO se cierra (cerrar
    liberaría al asesor cuando el cliente vuelva a escribir) y uno vendido/agendado tampoco (ya tiene resultado).

    El resultado con que se tipifica sale de la configuración del negocio (`triaje_atc_resultado`, default
    `consulta_atc`; ver `obtener_resultado_triaje`) salvo que el llamador pase `resultado` (debe ser válido)."""
    ahora = ahora or datetime.utcnow()
    if resultado is None:
        resultado = await obtener_resultado_triaje(negocio_id)
    elif not resultado_triaje_valido(resultado):
        raise ValueError(f"cerrar_por_triaje: resultado no permitido para el triaje: {resultado!r}")
    async with async_session() as session:
        async with session.begin():
            contact = await _obtener_contact(session, negocio_id, telefono)
            conversation = await _obtener_conversation_activa(session, contact.id) if contact is not None else None
            lead = await session.get(Lead, telefono)
            if conversation is None or conversation.negocio_id != negocio_id:
                return None
            if lead is None or lead.negocio_id != negocio_id:
                return None
            if lead.cerrado_definitivamente_en is not None or conversation.cerrado_definitivamente_en is not None:
                return None
            if lead.asesor_asignado or lead.pausado_manual or conversation.asesor_asignado_id or conversation.pausado_manual:
                return None
            opportunity = await _obtener_opportunity_vigente(session, conversation.id)
            if opportunity is None or opportunity.resultado or lead.resultado:
                return None

            lead.resultado = resultado
            lead.cerrado_definitivamente_en = ahora
            lead.derivado_en = None
            _avanzar_version(lead)
            lead.actualizado = ahora
            opportunity.resultado = resultado
            opportunity.version = Opportunity.version + 1
            opportunity.actualizado = ahora
            conversation.cerrado_definitivamente_en = ahora
            conversation.version = Conversation.version + 1
            conversation.actualizado = ahora

            etiqueta = _ETIQUETAS_CATEGORIA_TRIAJE.get(categoria, categoria)
            session.add(EventoLead(
                conversation_id=conversation.id, negocio_id=conversation.negocio_id, opportunity_id=opportunity.id,
                tipo="resultado_cambiado", autor=None,
                descripcion=f"Cambió el resultado a «{etiqueta_resultado(resultado)}» (triaje automático)",
                payload={
                    "campo": "resultado", "anterior": None, "nuevo": resultado,
                    "origen": "triaje_atc", "categoria": categoria,
                },
                creado=ahora,
            ))
            session.add(EventoLead(
                conversation_id=conversation.id, negocio_id=conversation.negocio_id, opportunity_id=opportunity.id,
                tipo=EVENTO_TRIAJE_ATC_CERRADO, autor=None,
                descripcion=(
                    _DESCRIPCION_CIERRE_EMERGENCIA if categoria == "emergencia_gas"
                    else f"Triaje automático: consulta de {etiqueta} derivada a la línea de atención — caso cerrado"
                )[:300],
                payload={"categoria": categoria, "origen": "triaje_atc", "cierre_en": ahora.isoformat(), "resultado": resultado},
                creado=ahora,
            ))
            return {"conversation_id": conversation.id, "opportunity_id": opportunity.id, "cierre_en": ahora}


async def reabrir_caso_cerrado(
    conversation_id: str, negocio_id: str, autor: str, rol: str | None = None, motivo: str | None = None,
    ahora: datetime | None = None,
) -> str:
    """Deshace un cierre definitivo (botón "Reabrir caso", Q3 2026-10-07): el
    cierre pudo ser un error (caso real Mercy: se cerró como "no interesado"
    aunque la clienta sí quería). Limpia `cerrado_definitivamente_en` en el Lead
    y en la Conversation y deja el evento `cierre_deshecho` con el autor.
    CONSERVA el asesor, el resultado (editable después), los mensajes y deja a Gabi
    como esté: no reasigna, no libera y no responde nada.

    Lapso de gracia (2026-10-07, `cierre_gracia_horas`, default 24 h): DENTRO del lapso
    lo puede hacer quien puede cerrar (el permiso lo resuelve el router) y el `motivo` es
    opcional. PASADO el lapso solo un admin o supervisor (`rol`) y el `motivo` es
    obligatorio (texto no vacío, máx. `MOTIVO_REABRIR_MAXIMO`): queda en el payload del
    evento y en `RegistroAuditoria`.

    Retorna: "ok"; "no_encontrada" (no existe o es de otro Negocio);
    "sustituida" (el cliente ya reabrió el caso por su cuenta: hay una
    Conversation más nueva y esta quedó cerrada — no hay nada que deshacer);
    "no_cerrada" (el caso ya estaba abierto); "sin_permiso_fuera_de_lapso" (403);
    "motivo_requerido" y "motivo_largo" (400)."""
    motivo = (motivo or "").strip()
    if len(motivo) > MOTIVO_REABRIR_MAXIMO:
        return "motivo_largo"
    ahora = ahora or datetime.utcnow()
    gracia_horas = await obtener_cierre_gracia_horas(negocio_id)
    async with async_session() as session:
        conversation = await session.get(Conversation, conversation_id)
        if conversation is None or conversation.negocio_id != negocio_id:
            return "no_encontrada"
        if conversation.estado != "activa":
            return "sustituida"
        contact = await session.get(Contact, conversation.contact_id)
        lead = await session.get(Lead, contact.telefono) if contact is not None else None
        if lead is not None and lead.negocio_id not in (None, negocio_id):
            lead = None
        cierre = _cierre_vigente(
            conversation.cerrado_definitivamente_en, lead.cerrado_definitivamente_en if lead is not None else None,
        )
        if cierre is None:
            return "no_cerrada"

        fuera_de_lapso = not cierre_en_lapso_de_gracia(cierre, ahora, gracia_horas)
        if fuera_de_lapso:
            if rol not in ROLES_CON_VISION_TOTAL:
                return "sin_permiso_fuera_de_lapso"
            if not motivo:
                return "motivo_requerido"

        resumen = (await _resumen_tras_cierre(session, {conversation.id: cierre})).get(conversation.id)
        opportunity = await _obtener_opportunity_vigente(session, conversation.id)
        resultado = (lead.resultado if lead is not None else None) or (opportunity.resultado if opportunity else None)
        conversation.cerrado_definitivamente_en = None
        conversation.actualizado = ahora
        if lead is not None:
            lead.cerrado_definitivamente_en = None
            lead.actualizado = ahora
        descripcion = "Reabrió el caso — se deshizo el cierre definitivo; el asesor y el resultado se conservan"
        if fuera_de_lapso:
            descripcion = f"Reabrió el caso pasado el lapso de {gracia_horas} h tras el cierre — motivo: {motivo}"
        payload = {
            "cierre_en": cierre.isoformat(), "resultado": resultado,
            "asesor": conversation.asesor_asignado_id,
            "mensajes_tras_cierre": resumen["mensajes"] if resumen else 0,
            "fuera_de_lapso": fuera_de_lapso, "gracia_horas": gracia_horas, "motivo": motivo or None,
        }
        session.add(EventoLead(
            conversation_id=conversation.id, negocio_id=conversation.negocio_id,
            opportunity_id=opportunity.id if opportunity else None,
            tipo="cierre_deshecho", descripcion=descripcion[:300], autor=autor, payload=payload,
        ))
        if fuera_de_lapso:
            session.add(RegistroAuditoria(
                accion="caso_reabierto_fuera_de_lapso", actor=(autor or "")[:50] or None, negocio_id=conversation.negocio_id,
                entidad_tipo="conversation", entidad_id=conversation.id, payload=payload,
            ))
        await session.commit()
        return "ok"


async def cerrar_leads_definitivamente_inactivos(dias: int = 7) -> list[str]:
    """Cierra definitivamente (ver `Lead.cerrado_definitivamente_en`) todo
    lead con asesor asignado, `resultado` ya cerrado (nunca "vendido"), que
    el CLIENTE no respondió en los últimos `dias` días — mismo criterio de
    "silencio del cliente" que `listar_leads_inactividad_cliente`, pero
    acá el lead SÍ tiene asesor (esa función es exclusiva de leads que
    nunca tuvieron uno).

    Complementa, sin solaparse, a los otros 2 Cron Schedule de inactividad
    ya en producción:
    - `listar_leads_para_rotar_o_liberar` mide silencio del ASESOR sobre un
      resultado ABIERTO (Punto 2, 2026-09-29: reemplazó a la antigua
      `liberar_asignaciones_inactivas` de 24h de reloj).
    - `listar_leads_inactividad_cliente` mide silencio del CLIENTE sobre
      un lead que NUNCA tuvo asesor.
    - Esta mide silencio del CLIENTE sobre un resultado YA CERRADO con
      asesor asignado — el único de los 3 escenarios que faltaba.

    Solo MARCA el cierre (no libera la asignación ni notifica a nadie) —
    la liberación real pasa recién cuando el cliente vuelve a escribir
    (ver el bloque de `agent/main.py` que lee `cerrado_definitivamente_en`).
    Pensado para correr como un Cron Schedule de Railway (mismo patrón que
    los otros 3), una vez al día — el umbral son días, no horas, así que
    no necesita la frecuencia de los otros dos. Retorna la lista de
    teléfonos cerrados, para que el script que llama esto pueda loguearlo."""
    corte = datetime.utcnow() - timedelta(days=dias)
    async with async_session() as session:
        query = select(Lead).where(
            Lead.asesor_asignado.is_not(None),
            Lead.resultado.in_(RESULTADOS_CERRADOS),
            Lead.resultado != "vendido",
            Lead.cerrado_definitivamente_en.is_(None),
        )
        candidatos = (await session.execute(query)).scalars().all()

        elegibles: list[tuple[str, str]] = []
        for lead in candidatos:
            ultimo_cliente = await session.execute(
                select(Mensaje.timestamp)
                .where(Mensaje.telefono == lead.telefono, Mensaje.role == "user")
                .order_by(Mensaje.timestamp.desc())
                .limit(1)
            )
            fila = ultimo_cliente.first()
            # Sin ningún mensaje del cliente todavía (no debería pasar con
            # asesor ya asignado, pero fail-closed: nunca se cierra sin
            # evidencia real de silencio) — se salta.
            if fila is None or fila[0] >= corte:
                continue
            elegibles.append((lead.telefono, lead.negocio_id))

    # Fuera de la sesión de arriba: reusa cerrar_lead_definitivamente por
    # candidato (autor=None → cierre automático) en vez de duplicar el
    # mirror hacia Conversation y el registro de evento — mismo patrón que
    # listar_leads_para_rotar_o_liberar ya usa con liberar_asignacion.
    cerrados: list[str] = []
    for telefono, negocio_id in elegibles:
        if await cerrar_lead_definitivamente(telefono, negocio_id, autor=None):
            cerrados.append(telefono)

    return cerrados


async def cerrar_ventas_sin_seguimiento(dias: int = 5) -> list[str]:
    """Punto 3 (2026-09-28) — 4to escenario de inactividad, exclusivo de
    "vendido": cierra definitivamente toda venta con asesor asignado que el
    CLIENTE no respondió en los últimos `dias` días. Mismo mecanismo que
    `cerrar_leads_definitivamente_inactivos` (reusa `cerrar_lead_
    definitivamente`, ahora sin la exclusión de vendido — ver esa función),
    separado en su propia función y su propio Cron Schedule porque el
    umbral es distinto y deliberadamente MÁS CORTO que el de los otros 8
    resultados cerrados (7 días):

    - Este cierre es 100% silencioso e interno — nunca le escribe nada al
      cliente, y si vuelve a contactar en cualquier momento
      `agent/main.py` (`enrutar_posventa_si_corresponde`) reabre la
      atención sin pérdida, ruteándola de una al mismo asesor que hizo la
      venta. No hay downside de UX en cerrar antes.
    - Sí hay downside de negocio en NO cerrar antes: hasta este Gate,
      NINGÚN Cron cubría "vendido" — una venta con seguimiento pendiente
      (instalación, entrega) podía quedar sin que nadie se enterara si el
      cliente no volvía a escribir (ver el caso real investigado de
      Mariella Lachira, memoria de sesión 2026-09-28). Cerrar más rápido
      que el resto reduce esa ventana sin costo.
    - 5 días (vs. los 7 de `cerrar_leads_definitivamente_inactivos`) da
      margen de sobra para coordinación de entrega/instalación con
      terveros (el caso real de Mariella tardó 6 días en escribir de
      nuevo, y hubiera reabierto igual de bien un día después de cerrado)
      y deja las colas de los asesores más limpias — la investigación de
      mercado no arrojó un estándar único de "días de soporte post-venta
      antes de archivar el caso" para este rubro, así que el criterio acá
      es interno: no hay razón para esperar más que lo necesario cuando
      reabrir no cuesta nada.

    Pensado para correr como un Cron Schedule de Railway propio (mismo
    patrón que los otros 3), una vez al día. Retorna la lista de
    teléfonos cerrados."""
    corte = datetime.utcnow() - timedelta(days=dias)
    async with async_session() as session:
        query = select(Lead).where(
            Lead.asesor_asignado.is_not(None),
            Lead.resultado == "vendido",
            Lead.cerrado_definitivamente_en.is_(None),
        )
        candidatos = (await session.execute(query)).scalars().all()

        elegibles: list[tuple[str, str]] = []
        for lead in candidatos:
            ultimo_cliente = await session.execute(
                select(Mensaje.timestamp)
                .where(Mensaje.telefono == lead.telefono, Mensaje.role == "user")
                .order_by(Mensaje.timestamp.desc())
                .limit(1)
            )
            fila = ultimo_cliente.first()
            if fila is None or fila[0] >= corte:
                continue
            elegibles.append((lead.telefono, lead.negocio_id))

    cerrados: list[str] = []
    for telefono, negocio_id in elegibles:
        if await cerrar_lead_definitivamente(telefono, negocio_id, autor=None):
            cerrados.append(telefono)

    return cerrados


async def obtener_vendedor_venta_anterior(
    contact_id: str, negocio_id: str, conversation_actual_id: str,
) -> str | None:
    """Punto 3 (2026-09-28) — busca, entre las Conversation de este Contact
    DISTINTAS de la actual, la más reciente con asesor asignado cuya
    Opportunity vigente haya quedado "vendido", y devuelve ese asesor.
    None si no hay ninguna venta previa.

    Recorre las Conversation cerradas del Contact de la más reciente a la
    más vieja (nunca solo la última: una Conversation puede haberse
    cerrado por otro resultado sin venta) y usa `_obtener_opportunity_
    vigente` para cada una — el mismo criterio de "vigente" que usa el
    resto del código, en vez de asumir que cada Conversation tiene una
    sola Opportunity.

    `estado == "cerrada"` (y no solo excluir `conversation_actual_id`) es
    deliberado: el índice único parcial `ix_conversation_una_activa_por_
    contact` garantiza que un Contact nunca tiene más de una Conversation
    activa a la vez, así que cualquier "venta anterior" real solo puede
    estar entre las ya cerradas — filtrarlo así de explícito evita
    depender únicamente de que el llamador pase el id correcto a excluir."""
    async with async_session() as session:
        query = (
            select(Conversation)
            .where(
                Conversation.contact_id == contact_id,
                Conversation.negocio_id == negocio_id,
                Conversation.id != conversation_actual_id,
                Conversation.estado == "cerrada",
                Conversation.asesor_asignado_id.is_not(None),
            )
            .order_by(Conversation.creado.desc())
        )
        conversaciones = (await session.execute(query)).scalars().all()
        for conversation in conversaciones:
            opportunity = await _obtener_opportunity_vigente(session, conversation.id)
            if opportunity is not None and opportunity.resultado == "vendido":
                return conversation.asesor_asignado_id
        return None


async def enrutar_posventa_si_corresponde(
    telefono: str, contact_id: str, negocio_id: str, conversation_id: str,
) -> str | None:
    """Punto 3 (2026-09-28) — se llama desde `agent/main.py` justo después
    de `resolver_conversation_activa`, únicamente cuando la Conversation
    activa quedó sin asesor (recién abierta por DR-4, o nunca tuvo uno).
    Si este Contact tiene una venta anterior, rutea la Conversation nueva
    en silencio al mismo asesor que la cerró — resultado="postventa" — sin
    ninguna llamada a IA: es una búsqueda determinística, el mismo criterio
    que ya se le explicó al usuario para no reactivar a Gabi por una vía
    indirecta (Human Decision Gate, Close-Won es indefinido).

    También limpia `Lead.cerrado_definitivamente_en`: si no se limpiara,
    el chequeo de abajo en `agent/main.py` (`lead.get("cerrado_
    definitivamente_en") is not None`) leería el cierre de la venta VIEJA
    y llamaría a `liberar_asignacion` — deshaciendo esta misma asignación
    y devolviéndole el control a Gabi, justo lo que este diseño existe
    para evitar.

    Registra su PROPIO evento en el Timeline (en vez de dejárselo a
    `asignar_asesor_a_lead`): el asesor encontrado suele ser el MISMO que
    ya figuraba en `Lead.asesor_asignado` (DR-4 abre la Conversation nueva
    sin asesor, pero nunca tocó `Lead` hasta acá), así que el chequeo
    "¿cambió el dueño?" de esa función no dispara — y aun así ocurrió algo
    que el asesor necesita ver: una venta cerrada se reabrió porque el
    cliente volvió a escribir.

    Retorna el asesor asignado, o None si no había venta previa (no hace
    nada en ese caso — el flujo sigue exactamente igual que hoy).

    Punto 2 (2026-09-30): `asignar_asesor_a_lead(automatico=True)` arma
    `Lead.derivado_en` (el reloj de rotación por inactividad) para
    cualquier asignación automática — pero un caso de posventa NUNCA debe
    rotar ni liberarse solo por inactividad, es un flujo silencioso aparte
    (el asesor original puede tardar en responder sin que eso dispare nada
    automático). Se desarma acá mismo, explícito, después de asignar."""
    asesor = await obtener_vendedor_venta_anterior(contact_id, negocio_id, conversation_id)
    if asesor is None:
        return None
    await actualizar_lead(
        telefono, campos_explicitos=("resultado", "cerrado_definitivamente_en"),
        resultado="postventa", cerrado_definitivamente_en=None,
    )
    await asignar_asesor_a_lead(telefono, asesor, automatico=True)
    async with async_session() as session:
        lead = await session.get(Lead, telefono)
        if lead is not None:
            lead.derivado_en = None
            await session.commit()
    await registrar_evento_lead(
        telefono, tipo="asignado_automatico_postventa",
        descripcion=f"Cliente con una venta anterior — se reabrió la atención y se ruteó automáticamente a {asesor} (mismo asesor que la cerró)",
        autor=None, payload={"campo": "resultado", "anterior": "vendido", "nuevo": "postventa", "asesor": asesor},
    )
    return asesor


async def listar_leads_inactividad_cliente(
    horas_reenganche: float = 2.0, horas_cierre: float = 15.0,
) -> tuple[list[dict], list[dict]]:
    """Candidatos a reenganche/cierre por CLIENTE inactivo — Gabi sigue
    activa, sin asesor asignado ni pausada, esperando que el cliente
    responda (2026-09-17, pedido explícito del usuario, investigado el
    estándar real de seguimiento de leads por WhatsApp: horas, no minutos
    — un timeout tipo "chat en vivo" de 5-10 min cerraría leads que solo
    están ocupados, no perdidos).

    Distinto de `listar_leads_para_rotar_o_liberar` (asesor inactivo,
    siempre silencioso): acá SÍ hay un paso con mensaje — a `horas_reenganche` sin
    respuesta se manda UN mensaje de reenganche (el script que llama esto
    es quien lo envía y lo guarda, nunca esta función — memory.py no hace
    I/O externo); a `horas_cierre` sin respuesta (medidas desde el MISMO
    último mensaje del cliente, no desde el reenganche) se cierra en
    silencio con resultado="sin_respuesta", igual de silencioso que el
    caso del asesor — la puerta queda abierta: Gabi nunca se pausó para
    estos leads, así que si el cliente escribe en cualquier momento
    después (aunque sea días), Gabi le responde normal — ver el bloque en
    main.py que limpia "sin_respuesta" apenas eso pasa.

    Retorna (candidatos_reenganche, candidatos_cierre) — cada fila
    {telefono, negocio_id, numero_whatsapp_id}, lo mínimo que el script
    necesita para resolver el Canal y enviar/actualizar. Un lead nunca
    aparece en las dos listas a la vez (cierre tiene prioridad si por
    algún motivo ya cruzó ambos umbrales).

    Excepción (2026-10-06, falla transitoria de la IA): si lo único que el
    cliente recibió tras su último mensaje fue el texto de error técnico de
    Gabi, la fila lleva además `tras_falla_ia: True` y el script NO la
    reengancha ni la cierra: la deriva a una persona (ver el script)."""
    ahora = datetime.utcnow()
    corte_reenganche = ahora - timedelta(hours=horas_reenganche)
    corte_cierre = ahora - timedelta(hours=horas_cierre)

    candidatos_reenganche: list[dict] = []
    candidatos_cierre: list[dict] = []
    conocidos_error = textos_de_error_tecnico_conocidos()

    async with async_session() as session:
        query = select(Lead).where(
            Lead.asesor_asignado.is_(None),
            Lead.pausado_manual.is_(False),
            # 2026-10-07: un lead YA derivado a un asesor (con o sin asesor asignado todavía) o escalado a
            # supervisión espera a una persona, no al cliente: no se le manda "¡Hola de nuevo!" ni se cierra
            # como `sin_respuesta` (eso lo sacaba de la cola de pendientes antes de que alguien lo atendiera).
            sa_or(Lead.paso_flujo.is_(None), Lead.paso_flujo != "derivado_asesor"),
            Lead.escalado_supervision_en.is_(None),
            sa_or(Lead.resultado.is_(None), Lead.resultado.notin_(RESULTADOS_CERRADOS)),
        )
        candidatos = (await session.execute(query)).scalars().all()
        # "Para llamar" (2026-10-09): un lead con una tarea de llamada ABIERTA, visible y en juego (modo activo,
        # grupo `llamar`) NO se cierra como `sin_respuesta` a las 15 h: lo cierra la propia tarea al agotarse
        # (agent/llamadas.py). Las tareas de sombra y del grupo de control NUNCA frenan este cierre (el grupo de
        # control tiene que comportarse como siempre). Sin tareas, el conjunto es vacío y nada cambia.
        con_tarea_de_llamada_abierta: set[tuple[str, str]] = set()
        if candidatos:
            con_tarea_de_llamada_abierta = {
                (negocio, telefono) for negocio, telefono in (await session.execute(
                    select(TareaLlamada.negocio_id, TareaLlamada.telefono).where(
                        TareaLlamada.estado.in_(("programada", "pendiente")),
                        TareaLlamada.modo == "activo", TareaLlamada.grupo == "llamar",
                    )
                )).all()
            }

        for lead in candidatos:
            recientes = (await session.execute(
                select(Mensaje)
                .where(Mensaje.telefono == lead.telefono)
                .order_by(Mensaje.timestamp.desc(), Mensaje.id.desc())
                .limit(10)
            )).scalars().all()
            if not recientes or recientes[0].role != "assistant":
                # El último mensaje no es de Gabi (es del cliente, o no hay
                # ninguno) — no hay nada pendiente de nuestro lado, no aplica.
                continue

            ultimo_cliente = next((m for m in recientes if m.role == "user"), None)
            if ultimo_cliente is None:
                continue

            # ¿Ya se mandó el reenganche para ESTE silencio? Gabi solo
            # responde una vez por mensaje del cliente en el flujo normal —
            # si hay 2+ mensajes "assistant" seguidos DESPUÉS del último
            # mensaje del cliente, el segundo (o más) solo pudo haber sido
            # el reenganche automático (nunca una respuesta real, porque
            # esa siempre depende de un mensaje nuevo del cliente).
            asistentes_tras_cliente = sum(
                1 for m in recientes if m.timestamp > ultimo_cliente.timestamp and m.role == "assistant"
            )
            ya_reenganchado = asistentes_tras_cliente >= 2

            fila = {
                "telefono": lead.telefono, "negocio_id": lead.negocio_id,
                "numero_whatsapp_id": lead.numero_whatsapp_id,
            }

            # Falla transitoria de la IA (2026-10-06): lo ÚNICO que el cliente recibió después de su
            # último mensaje es el texto de error técnico (y, en casos viejos, el reenganche que lo
            # siguió) — Gabi nunca le respondió de verdad. Reenganchar con "¡Hola de nuevo!" o cerrarlo
            # como sin_respuesta sería enterrar un caso que falló por culpa nuestra: se marca con
            # `tras_falla_ia` para que el script lo DERIVE a una persona. Se lista (en la lista que le
            # toca por tiempo) aunque ya tuviera el reenganche.
            posteriores = recientes[:recientes.index(ultimo_cliente)]
            if (
                any(es_texto_de_error_tecnico(m.content, conocidos_error) for m in posteriores)
                and all(
                    es_texto_de_error_tecnico(m.content, conocidos_error) or es_texto_de_reenganche_automatico(m.content)
                    for m in posteriores
                )
            ):
                fila["tras_falla_ia"] = True
                if ultimo_cliente.timestamp < corte_cierre:
                    candidatos_cierre.append(fila)
                elif ultimo_cliente.timestamp < corte_reenganche:
                    candidatos_reenganche.append(fila)
                continue

            if ultimo_cliente.timestamp < corte_cierre:
                if (lead.negocio_id, lead.telefono) not in con_tarea_de_llamada_abierta:
                    candidatos_cierre.append(fila)
            elif not ya_reenganchado and ultimo_cliente.timestamp < corte_reenganche:
                candidatos_reenganche.append(fila)

    return candidatos_reenganche, candidatos_cierre


async def liberar_asignacion_via_conversation(conversation_id: str, negocio_id: str, autor: str, motivo: str = "reactivado_manual") -> str | None:
    """Punto de entrada para el endpoint nuevo `/conversation/{id}/liberar`
    (Gate 5.3 cutover real §1/§4/§8) — resuelve el teléfono get-only y
    reusa `liberar_asignacion()` tal cual (ya mirror-ea Conversation +
    Lead.version incondicional, sin duplicar esa lógica). No agrega chequeo
    de concurrencia nuevo: la propia función legacy nunca lo tuvo — esto
    conserva ese contrato real en vez de inventar uno más estricto.

    Retorna None si la Opportunity vigente de la Conversation ya está
    "vendido" (guardia de producto: un caso vendido nunca vuelve a Gabi por
    acá — verificado sobre Opportunity, la fuente de verdad, no sobre Lead)
    o si la Conversation no existe/no es de este Negocio. Si puede liberar,
    retorna el teléfono (para que el router registre el DTO de respuesta)."""
    async with async_session() as session:
        conversation = await session.get(Conversation, conversation_id)
        if conversation is None or conversation.negocio_id != negocio_id:
            return None
        opportunity = await _obtener_opportunity_vigente(session, conversation.id)
        if opportunity is not None and opportunity.resultado == "vendido":
            return None
        contact = await session.get(Contact, conversation.contact_id)
        telefono = contact.telefono if contact else None
    if telefono is None:
        return None
    await liberar_asignacion(telefono, autor=autor, motivo=motivo)
    return telefono


async def pausar_gabi_manual(telefono: str):
    """Pausa a Gabi para este lead porque un asesor le respondió directo
    desde la app de WhatsApp Business en el celular (coexistencia) — sin
    pasar por una asignación formal en el panel. No sabemos qué asesor fue
    (Meta no lo informa), así que no se llena asesor_asignado; en cambio se
    marca paso_flujo='derivado_asesor' (si no lo estaba ya) para que el caso
    aparezca en listar_leads_esperando_asesor() y un supervisor lo reclame y
    lo asigne a una persona real cuando pueda."""
    async with async_session() as session:
        lead = _exigir_lead_existente(await session.get(Lead, telefono), telefono, "pausar_gabi_manual")
        lead.pausado_manual = True
        if not lead.paso_flujo:
            lead.paso_flujo = "derivado_asesor"
        lead.actualizado = datetime.utcnow()
        await session.commit()


# Tipo del evento que deja agent/respaldo_sin_ia.py cuando Gabi no puede usar la IA y
# deriva el caso a una persona (Fase 1, modo sin IA) — 14 caracteres, cabe en
# eventos_lead.tipo (TIPO_EVENTO_LARGO_MAX).
TIPO_EVENTO_DERIVADO_SIN_IA = "derivado_sin_ia"


async def contar_derivados_sin_ia(desde: datetime, negocio_id: str | None = None) -> dict:
    """Cuántos casos derivó el modo sin IA desde `desde` (UTC naive): `total` y, de ellos,
    cuántos no encontraron ningún asesor y quedaron en la cola de supervisión (`en_cola`,
    por el `destino` del payload del evento — es lo que ocurrió al derivar). Con
    `negocio_id=None` cuenta todos los negocios (alerta al dueño de la plataforma)."""
    async with async_session() as session:
        query = select(EventoLead.payload).where(EventoLead.tipo == TIPO_EVENTO_DERIVADO_SIN_IA, EventoLead.creado >= desde)
        if negocio_id is not None:
            query = query.where(EventoLead.negocio_id == negocio_id)
        payloads = (await session.execute(query)).scalars().all()
    en_cola = sum(1 for p in payloads if isinstance(p, dict) and p.get("destino") == "supervision")
    return {"total": len(payloads), "en_cola": en_cola}


async def registrar_fallo_tecnico(telefono: str) -> int:
    """Suma 1 a los fallos técnicos consecutivos del lead y retorna el nuevo total."""
    async with async_session() as session:
        lead = _exigir_lead_existente(await session.get(Lead, telefono), telefono, "registrar_fallo_tecnico")
        lead.fallos_tecnicos = (lead.fallos_tecnicos or 0) + 1
        lead.actualizado = datetime.utcnow()
        await session.commit()
        return lead.fallos_tecnicos


async def resetear_fallos_tecnicos(telefono: str):
    """Reinicia el contador de fallos técnicos tras una respuesta exitosa de Gabi."""
    async with async_session() as session:
        lead = await session.get(Lead, telefono)
        if lead is not None and lead.fallos_tecnicos:
            lead.fallos_tecnicos = 0
            await session.commit()


async def marcar_lead_visto(telefono: str):
    """Marca un lead como visto por su asesor asignado (oculta el indicador de "Nuevo")."""
    async with async_session() as session:
        lead = await session.get(Lead, telefono)
        if lead is not None and not lead.visto_asesor:
            lead.visto_asesor = True
            await session.commit()


async def marcar_revision_prioritaria(telefono: str):
    """Marca un lead para revisión prioritaria por un asesor — la IA
    respondió con confianza "Requiere validación" (protocolo de
    confianza, AI Architecture Sec.6). No transfiere la conversación,
    solo llama la atención de un humano sobre ella."""
    async with async_session() as session:
        lead = await session.get(Lead, telefono)
        if lead is not None and not lead.revision_prioritaria:
            lead.revision_prioritaria = True
            lead.actualizado = datetime.utcnow()
            await session.commit()


async def limpiar_revision_prioritaria(telefono: str):
    """Limpia la marca de revisión prioritaria — se llama cuando alguien
    del equipo abre el detalle del lead, ya cumplió su propósito de
    llamar la atención."""
    async with async_session() as session:
        lead = await session.get(Lead, telefono)
        if lead is not None and lead.revision_prioritaria:
            lead.revision_prioritaria = False
            await session.commit()


async def contar_leads_activos(asesor: str) -> int:
    """Cuenta los leads asignados a un asesor que aún no llegaron a un resultado final.

    Ojo: un `resultado.notin_(...)` a nivel SQL excluiría también las filas
    con resultado NULL (el caso más común, antes de que el asesor marque
    algo) por cómo SQL trata NULL en comparaciones — por eso el filtro final
    se hace en Python, no en el WHERE."""
    async with async_session() as session:
        query = select(Lead.resultado).where(Lead.asesor_asignado == asesor)
        result = await session.execute(query)
        resultados = result.scalars().all()
        return sum(1 for r in resultados if r not in RESULTADOS_CERRADOS)


async def contar_conversations_activas_por_asesor(
    negocio_id: str, usernames: list[str], unidad_id: str | None = None,
) -> dict[str, int]:
    """Igual que contar_leads_activos, pero para todo el equipo en una sola
    consulta — el sidebar (rail EQUIPO) antes llamaba a contar_leads_activos
    una vez POR asesor en un loop, o sea un viaje de ida y vuelta a la base
    de datos por cada uno; con Postgres en producción (a diferencia de
    SQLite local, que es casi instantáneo) esa latencia por consulta se
    siente en cada carga completa de página. Acá se trae todo de una vez y
    se cuenta en Python.

    Gate 5.6 — reemplaza `contar_leads_activos_por_asesor()`: la versión
    anterior filtraba `Lead.asesor_asignado IN (usernames)` SIN `negocio_id`
    — con el mismo username de asesor existiendo en dos Negocios, la carga de
    trabajo de uno se sumaba a la del otro (hallazgo de la investigación de
    Gate 5.6). La asignación real vive en `Conversation.asesor_asignado_id`
    desde Gate 5.4/5.5 (`intentar_asignar_conversation`); "activo" sigue
    siendo el mismo criterio que antes — la Opportunity de esa Conversation
    todavía no llegó a un resultado cerrado (`RESULTADOS_CERRADOS`). Usa el
    índice ya existente `ix_conversation_negocio_asesor`, sin migración
    nueva. Asume, como el resto del modelo (Diseño Técnico Gate 5.3 §6), que
    cada Conversation tiene a lo sumo 1 Opportunity vigente — una Conversation
    sin ninguna Opportunity todavía simplemente no cuenta como carga activa."""
    if not usernames:
        return {}
    async with async_session() as session:
        query = (
            select(Conversation.asesor_asignado_id, Opportunity.resultado)
            .join(Opportunity, Opportunity.conversation_id == Conversation.id)
            .where(
                Conversation.negocio_id == negocio_id,
                Conversation.asesor_asignado_id.in_(usernames),
            )
        )
        if unidad_id is not None:
            query = query.where(Conversation.unidad_id == unidad_id)
        result = await session.execute(query)
        conteos = {u: 0 for u in usernames}
        for asesor, resultado in result.all():
            if resultado not in RESULTADOS_CERRADOS:
                conteos[asesor] += 1
        return conteos


async def _obtener_usuario_orm(session, negocio_id: str, username: str) -> "Usuario | None":
    """Lookup scoped — reemplaza `session.get(Usuario, username)` en toda
    escritura sobre una cuenta puntual (Gate 5.4, T3): `username` dejó de
    ser PK, la identidad real de una fila es `(negocio_id, username)`.
    Nunca usar fuera de un contexto donde `negocio_id` ya viene resuelto
    server-side (sesión del que llama) — ver `obtener_usuario()` para el
    único caso legítimo de búsqueda sin `negocio_id` (login)."""
    return (await session.execute(
        select(Usuario).where(Usuario.negocio_id == negocio_id, Usuario.username == username)
    )).scalar_one_or_none()


async def crear_usuario(
    username: str, password: str, nombre: str, rol: str, negocio_id: str, nivel: str | None = None,
):
    """Crea (o actualiza la contraseña de) una cuenta del panel interno.

    `negocio_id` (Gate 5.4, T3) es SIEMPRE obligatorio — antes solo se
    exigía al crear una cuenta nueva; ahora también es el candado de
    ownership para actualizar una existente (mismo `crear_usuario` se usa
    tanto para alta como para editar rol/nivel desde el panel). Antes de
    este Gate, dos Negocios con el mismo `username` colisionaban en la
    misma fila global — un admin de Negocio B dando de alta "admin" podía
    pisar password/rol de la cuenta "admin" de Negocio A sin darse cuenta.
    Ahora la búsqueda es por `(negocio_id, username)`: si no existe una
    fila para ESE Negocio, se crea una nueva — nunca se toca la de otro."""
    import bcrypt
    password_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
    async with async_session() as session:
        usuario = await _obtener_usuario_orm(session, negocio_id, username)
        if usuario is None:
            usuario = Usuario(username=username, negocio_id=negocio_id)
            session.add(usuario)
        usuario.password_hash = password_hash
        usuario.nombre = nombre
        usuario.rol = rol
        if nivel:
            usuario.nivel = nivel
        await session.commit()


async def contar_rotaciones_por_inactividad_por_asesor(negocio_id: str, dias: int = 30) -> dict[str, dict]:
    """Punto 2 (2026-09-29) — data cruda para el seguimiento del supervisor
    (pantalla Equipo): cuántas veces se le ROTÓ un lead a cada asesor por no
    responder en 30 min de turno, cuántas veces le LLEGÓ un lead rotado
    desde otro, y su promedio de minutos de turno sin responder antes de
    que lo rotaran. Ventana de `dias` (30 por defecto) — un contador desde
    el inicio de los tiempos no mide eficiencia RECIENTE, que es lo que le
    importa a un supervisor evaluando el desempeño de ahora, no el
    histórico completo.

    `payload` es JSON, sin índice — el filtro/agregado final se hace en
    Python (mismo criterio que `contar_leads_activos` con `resultado`).
    Solo cuenta usernames que aparecen en al menos un evento — un asesor
    sin ninguna rotación en la ventana simplemente no sale en el dict (el
    llamador decide el "—" para ese caso, igual que ya hace con `carga`)."""
    corte = datetime.utcnow() - timedelta(days=dias)
    async with async_session() as session:
        query = select(EventoLead.payload).where(
            EventoLead.negocio_id == negocio_id,
            EventoLead.tipo == "rotado_automatico_sin_respuesta",
            EventoLead.creado >= corte,
        )
        payloads = (await session.execute(query)).scalars().all()

    perdidos: dict[str, int] = {}
    recibidos: dict[str, int] = {}
    minutos_por_asesor: dict[str, list[int]] = {}
    for payload in payloads:
        if not payload:
            continue
        anterior = payload.get("asesor_anterior")
        nuevo = payload.get("asesor_nuevo")
        minutos = payload.get("minutos_espera")
        if anterior:
            perdidos[anterior] = perdidos.get(anterior, 0) + 1
            if isinstance(minutos, (int, float)):
                minutos_por_asesor.setdefault(anterior, []).append(minutos)
        if nuevo:
            recibidos[nuevo] = recibidos.get(nuevo, 0) + 1

    usernames = set(perdidos) | set(recibidos)
    return {
        u: {
            "veces_rotado_desde": perdidos.get(u, 0),
            "veces_rotado_hacia": recibidos.get(u, 0),
            "promedio_minutos_sin_responder": (
                round(sum(minutos_por_asesor[u]) / len(minutos_por_asesor[u]))
                if minutos_por_asesor.get(u) else None
            ),
        }
        for u in usernames
    }


async def cambiar_password(username: str, negocio_id: str, password_nueva: str):
    """Actualiza SOLO la contraseña de una cuenta, sin tocar nombre/rol/nivel
    — a diferencia de crear_usuario, que los sobreescribe. Dos llamadores:
    self-service (el propio usuario cambia su contraseña, `negocio_id` de su
    propia sesión) y reset por un admin/supervisor (Gate 5.4, T3: antes SIN
    ningún chequeo de ownership — un supervisor de Negocio B podía resetear
    la contraseña de un usuario de Negocio A si conocía/adivinaba el
    username. `negocio_id` ahora es el mismo candado que el resto del Gate:
    si el username no existe PARA ESE Negocio, no se toca nada."""
    import bcrypt
    password_hash = bcrypt.hashpw(password_nueva.encode(), bcrypt.gensalt()).decode()
    async with async_session() as session:
        usuario = await _obtener_usuario_orm(session, negocio_id, username)
        if usuario is None:
            return
        usuario.password_hash = password_hash
        await session.commit()


async def obtener_usuario(username: str, negocio_id: str | None = None) -> dict | None:
    """Recupera una cuenta del panel interno (incluye el hash, para verificar
    login).

    `negocio_id` (Gate 5.4, T3) — mismo criterio de opcionalidad que
    `obtener_lead()`: si se pasa, es el candado real de ownership. Si NO se
    pasa (login, y resumen de sesión — WebSocket del panel, que solo tiene
    el `username` guardado en la cookie), busca por `username` en TODOS los
    Negocios. Con `username` único por `(negocio_id, username)` en vez de
    global, eso puede dar más de un resultado el día que exista una
    colisión real entre Negocios (recién posible con un Tenant 002 real) —
    en ese caso, falla cerrado (retorna `None`) en vez de adivinar cuál de
    los dos: es una limitación conocida del login por username puro, no
    resuelta acá (necesitaría una UX de selección de Negocio en el login,
    Gate posterior) — preferible a autenticar contra la cuenta equivocada."""
    async with async_session() as session:
        if negocio_id is not None:
            usuario = await _obtener_usuario_orm(session, negocio_id, username)
        else:
            candidatos = (await session.execute(
                select(Usuario).where(Usuario.username == username, Usuario.eliminado_en.is_(None))
            )).scalars().all()
            if len(candidatos) != 1:
                return None
            usuario = candidatos[0]
        # Gate Equipo — una cuenta eliminada (soft delete) nunca resuelve acá,
        # tanto si vino del branch scoped (arriba, _obtener_usuario_orm no
        # filtra eliminado_en) como del branch de login.
        if usuario is None or usuario.eliminado_en is not None:
            return None
        return {
            "username": usuario.username,
            "password_hash": usuario.password_hash,
            "nombre": usuario.nombre,
            "rol": usuario.rol,
            "nivel": usuario.nivel,
            "disponible": usuario.disponible,
            "activo": usuario.activo,
            "negocio_id": usuario.negocio_id,
        }


async def listar_asesores(negocio_id: str) -> list[dict]:
    """Recupera las cuentas con rol 'asesor', para el selector de asignación.

    `negocio_id` (Gate 5.4, T2) obligatorio — esta consulta nunca filtraba
    por negocio_id, exponiendo asesores de cualquier Negocio al selector de
    asignación de otro.

    `eliminado_en.is_(None)` (2026-09-16, hallazgo del usuario: un asesor ya
    eliminado seguía saliendo en el selector de reasignación) — esta
    consulta nunca excluía las cuentas con soft delete (`eliminar_usuario`),
    a diferencia de `listar_equipo`/`obtener_usuario`/`autenticar`, que sí
    lo hacen.

    `activo.is_(True)` (2026-09-17, hallazgo del usuario: "gabi asigna a un
    asesor a pesar que este inactivo, solo debe asignar a los activos") —
    `toggle_usuario_activo` (Equipo) solo apaga `activo`, nunca toca
    `disponible`; una cuenta desactivada que quedó con `disponible=True` no
    puede volver a loguearse para corregirlo ella misma (`activo=False`
    bloquea el login), así que sin este filtro quedaba elegible para
    `elegir_asesor_automatico` (asignación de Gabi) y para el selector de
    reasignación manual PARA SIEMPRE. Distinto de `listar_equipo`, que sí
    debe seguir mostrando cuentas inactivas (para poder reactivarlas)."""
    async with async_session() as session:
        query = (
            select(Usuario)
            .where(
                Usuario.rol == "asesor", Usuario.negocio_id == negocio_id,
                Usuario.eliminado_en.is_(None), Usuario.activo.is_(True),
            )
            .order_by(Usuario.nombre)
        )
        result = await session.execute(query)
        return [
            {"username": u.username, "nombre": u.nombre, "nivel": u.nivel, "disponible": u.disponible}
            for u in result.scalars().all()
        ]


async def listar_equipo(negocio_id: str) -> list[dict]:
    """Recupera TODAS las cuentas del panel (admin+supervisor+asesor) de un
    Negocio, para la pantalla Equipo (MPA §3 — "dueño de usuarios, roles,
    disponibilidad y reglas de asignación").

    A diferencia de `listar_asesores()` (que sigue existiendo tal cual, sin
    tocar, para los selectores de asignación de leads — disponibilidad/nivel
    son conceptos que solo aplican a asesores), acá se listan los 3 roles.
    `nivel`/`disponible` viajan tal cual del modelo (`None`/`True` por
    default en admin/supervisor, que nunca los usa) — es la pantalla Equipo
    quien decide mostrar "—" para esas columnas quien no sea asesor, no esta
    función."""
    async with async_session() as session:
        query = (
            select(Usuario)
            .where(Usuario.negocio_id == negocio_id, Usuario.eliminado_en.is_(None))
            .order_by(Usuario.rol, Usuario.nombre)
        )
        result = await session.execute(query)
        return [
            {
                "username": u.username,
                "nombre": u.nombre,
                "rol": u.rol,
                "nivel": u.nivel if u.rol == "asesor" else None,
                "disponible": u.disponible if u.rol == "asesor" else None,
                "activo": u.activo,
            }
            for u in result.scalars().all()
        ]


async def actualizar_disponibilidad(username: str, negocio_id: str, disponible: bool):
    """El propio asesor togglea si está disponible para recibir leads nuevos
    — siempre self-service (su propio `negocio_id` de sesión), pero
    `session.get(Usuario, username)` dejó de servir (Gate 5.4, T3: `username`
    ya no es PK) — mismo lookup scoped que el resto de las funciones de
    identidad."""
    async with async_session() as session:
        usuario = await _obtener_usuario_orm(session, negocio_id, username)
        if usuario is not None:
            usuario.disponible = disponible
            await session.commit()


async def actualizar_nivel_asesor(username: str, negocio_id: str, nivel: str):
    """El supervisor/admin ajusta el nivel de experiencia de un asesor.

    `negocio_id` (Gate 5.4, T3) — antes SIN ningún chequeo de ownership,
    mismo hallazgo que `cambiar_password`: un supervisor de otro Negocio
    podía cambiar el nivel de un asesor ajeno si adivinaba el username."""
    async with async_session() as session:
        usuario = await _obtener_usuario_orm(session, negocio_id, username)
        if usuario is not None:
            usuario.nivel = nivel
            await session.commit()


async def toggle_usuario_activo(username: str, negocio_id: str) -> bool | None:
    """Prende/apaga una cuenta del panel (Equipo) — reversible, a diferencia
    de `eliminar_usuario` (soft delete, abajo). Una cuenta inactiva no puede
    iniciar sesión (ver `login_submit`, dashboard.py) pero conserva todo su
    historial/asignaciones tal cual, listo para reactivarla con el mismo
    botón. Sin restricción de rol a propósito (decisión del usuario, Gate
    Equipo 2026-09-14): solo `eliminar_usuario` protege al rol admin.

    Retorna el nuevo estado de `activo`, o `None` si la cuenta no existe (o
    ya fue eliminada) en este Negocio."""
    async with async_session() as session:
        usuario = await _obtener_usuario_orm(session, negocio_id, username)
        if usuario is None or usuario.eliminado_en is not None:
            return None
        usuario.activo = not usuario.activo
        await session.commit()
        return usuario.activo


async def eliminar_usuario(username: str, negocio_id: str, eliminado_por: str) -> str:
    """Soft delete de una cuenta del panel (Equipo) — mismo patrón que
    Contact/UnidadDeNegocio (`eliminado_en`/`eliminado_por`, nunca DELETE
    real): preserva referencias sueltas como Conversation.asesor_asignado_id
    (String suelto, sin FK — ver docstring de Usuario).

    Decisión del usuario (Gate Equipo, 2026-09-14): el rol admin nunca se
    puede eliminar — protege contra quedarse sin ninguna cuenta admin en el
    Negocio. Se aplica acá (capa de datos), no solo en la ruta, para que
    valga sin importar desde dónde se llame.

    Retorna "eliminado" | "no_encontrado" | "admin_protegido"."""
    async with async_session() as session:
        usuario = await _obtener_usuario_orm(session, negocio_id, username)
        if usuario is None or usuario.eliminado_en is not None:
            return "no_encontrado"
        if usuario.rol == "admin":
            return "admin_protegido"
        usuario.eliminado_en = datetime.utcnow()
        usuario.eliminado_por = eliminado_por
        await session.commit()
        return "eliminado"


async def asignar_campana_origen(telefono: str, nombre_campana: str):
    """Guarda la campaña de origen de un lead — solo si aún no tenía una
    asignada, para no perder la atribución original del primer contacto."""
    async with async_session() as session:
        lead = _exigir_lead_existente(await session.get(Lead, telefono), telefono, "asignar_campana_origen")
        if not lead.campana_origen:
            lead.campana_origen = nombre_campana
            lead.actualizado = datetime.utcnow()
        # La Analítica cuenta por Conversation.campana_origen_id, no por el
        # nombre en Lead: sin este reflejo toda campaña nueva sale en 0.
        contact = await _obtener_contact(session, lead.negocio_id, telefono)
        conversation = await _obtener_conversation_activa(session, contact.id) if contact else None
        if conversation is not None and conversation.campana_origen_id is None and lead.campana_origen:
            conversation.campana_origen_id = (await session.execute(
                select(Campana.id).where(Campana.negocio_id == lead.negocio_id, Campana.nombre == lead.campana_origen)
            )).scalars().first()
        await session.commit()


def _campana_a_dict(c: Campana) -> dict:
    return {
        "id": c.id,
        "nombre": c.nombre,
        "tipo_deteccion": c.tipo_deteccion,
        "patron": c.patron,
        "codigo_material": c.codigo_material,
        "producto_promocional": c.producto_promocional,
        "precio_promocional": c.precio_promocional,
        "texto_saludo": c.texto_saludo,
        "activa": c.activa,
        "creado": c.creado,
        "negocio_id": c.negocio_id,
        "unidad_id": c.unidad_id,
    }


async def crear_campana(
    nombre: str, tipo_deteccion: str, patron: str,
    codigo_material: str = "", producto_promocional: str = "", precio_promocional: str = "",
    texto_saludo: str = "", negocio_id: str | None = None, unidad_id: str | None = None,
) -> dict:
    """Crea una campaña nueva (ej. cuando cambia la promoción del mes).

    `negocio_id` es obligatorio (Gate 5.2, corrección H3) — quien llama debe
    resolverlo desde una fuente legítima (el Negocio del admin que crea la
    campaña). Nunca se asume un Negocio por defecto.

    Gate 5.2 — NOTA DE ALCANCE: la Arquitectura Contractual (§5) fija
    `unidad_id` como obligatoria para campañas nuevas, pero hoy no existe
    ninguna Unidad de Negocio real (dato pendiente, no se inventa — ver
    informe de cierre). Exigirlo acá bloquearía la creación de campañas en
    producción, violando "compatibilidad con producción > mínimo cambio".
    Por eso `unidad_id` sigue siendo opcional a nivel de función en este
    Gate; la validación NOT NULL se activa en el Gate donde existan
    Unidades reales para asignar (queda documentado como dependencia)."""
    if negocio_id is None:
        raise ValueError(
            f"crear_campana(): no se puede crear la campaña '{nombre}' sin negocio_id "
            f"resuelto. No se asume ningún Negocio por defecto (Gate 5.2)."
        )
    async with async_session() as session:
        campana = Campana(
            nombre=nombre,
            tipo_deteccion=tipo_deteccion,
            patron=patron,
            codigo_material=codigo_material or None,
            producto_promocional=producto_promocional or None,
            precio_promocional=precio_promocional or None,
            texto_saludo=texto_saludo or None,
            negocio_id=negocio_id,
            unidad_id=unidad_id,
        )
        session.add(campana)
        await session.commit()
        await session.refresh(campana)
        return _campana_a_dict(campana)


async def listar_campanas(negocio_id: str, solo_activas: bool = False) -> list[dict]:
    """Recupera las campañas configuradas, más recientes primero.

    `negocio_id` (Gate 5.4, T2) obligatorio — esta consulta nunca filtraba
    por negocio_id, exponiendo campañas (y su detección/promoción) de
    cualquier Negocio a otro."""
    async with async_session() as session:
        query = select(Campana).where(Campana.negocio_id == negocio_id).order_by(Campana.creado.desc())
        if solo_activas:
            query = query.where(Campana.activa.is_(True))
        result = await session.execute(query)
        return [_campana_a_dict(c) for c in result.scalars().all()]


async def obtener_campana(campana_id: int) -> dict | None:
    """Gate 5.3 — corrección pequeña: mismo motivo que obtener_canal_whatsapp
    — habilita el chequeo de ownership de negocio_id en editar/toggle/eliminar."""
    async with async_session() as session:
        campana = await session.get(Campana, campana_id)
        return _campana_a_dict(campana) if campana else None


async def obtener_campana_por_nombre(nombre: str, negocio_id: str) -> dict | None:
    """Recupera una campaña por su nombre exacto (ej. para saber qué promo
    ofrecer según la campana_origen guardada en el lead).

    `negocio_id` (Gate 5.4, hallazgo B del checkpoint anterior) obligatorio
    — sin candado, dos Negocios con una campaña del mismo `nombre` podían
    devolver la fila del Negocio equivocado (`Campana.nombre` nunca tuvo
    restricción UNIQUE). Ambos llamadores (`brain.py`, `campanas.py`) ya
    resuelven `negocio_id` desde un Canal/bootstrap conocido antes de
    llegar acá — nunca se adivina ni se cae a Cálidda por default.

    Sigue usando `.limit(1)` con `.first()` DENTRO de ese Negocio — no es
    una selección implícita entre Negocios, es la misma tolerancia previa
    a nombres duplicados dentro de uno solo (higiene de datos, no
    aislamiento)."""
    async with async_session() as session:
        query = (
            select(Campana)
            .where(Campana.nombre == nombre, Campana.negocio_id == negocio_id)
            .limit(1)
        )
        result = await session.execute(query)
        campana = result.scalars().first()
        return _campana_a_dict(campana) if campana else None


async def actualizar_campana(campana_id: int, **campos):
    """Actualiza los datos de una campaña (ej. la promo del mes) o su estado activa/inactiva."""
    async with async_session() as session:
        campana = await session.get(Campana, campana_id)
        if campana is None:
            return
        for campo, valor in campos.items():
            setattr(campana, campo, valor)
        await session.commit()


async def eliminar_campana(campana_id: int, negocio_id: str) -> bool:
    """Borra una campaña por completo — SOLO si nunca tuvo ninguna
    Conversation atribuida (así no se pierde historial de conversión real).
    Si ya tiene al menos una, no la borra y retorna False; el camino normal
    para una campaña con actividad es desactivarla (ver actualizar_campana
    activa=False), no borrarla.

    Gate 5.6 — corrección: contaba `Lead.campana_origen == campana.nombre`
    (match por nombre, global, sin `negocio_id`) — dos Negocios con una
    campaña homónima bloqueaban/permitían el borrado según la actividad del
    OTRO Negocio (hallazgo de la investigación de Gate 5.6). Ahora cuenta
    `Conversation.campana_origen_id` (FK real, ya resuelto por Negocio vía la
    propia Campana) y valida `negocio_id` explícitamente antes de tocar la
    fila — mismo criterio de defensa en profundidad de Gate 5.5, aunque el
    router ya valida ownership antes de llamar acá (`_verificar_ownership_
    campana`)."""
    async with async_session() as session:
        campana = await session.get(Campana, campana_id)
        if campana is None or campana.negocio_id != negocio_id:
            return False
        query_conteo = select(func.count()).select_from(Conversation).where(
            Conversation.campana_origen_id == campana_id
        )
        total_conversations = (await session.execute(query_conteo)).scalar_one()
        if total_conversations > 0:
            return False
        # Las reglas anuncio→campaña apuntan a la campaña (FK): se borran antes; esos anuncios
        # quedan "Sin campaña" hasta que se asignen de nuevo.
        await session.execute(delete(AnuncioCampana).where(AnuncioCampana.campana_id == campana_id))
        await session.delete(campana)
        await session.commit()
        return True


async def contar_opportunities_por_campana(
    negocio_id: str, unidad_id: str | None = None,
    desde: datetime | None = None, hasta: datetime | None = None,
    asesor: str | None = None, red: str | None = None,
) -> list[dict]:
    """Cuenta Conversation/Opportunity por campaña de origen, scoped por
    Negocio (y opcionalmente Unidad) — para medir conversión por campaña.

    `red` ("facebook" | "instagram" | "otra") acota TODOS los conteos a las
    conversaciones de esa red, deducida del enlace del anuncio (ver
    `_red_de_referral`); "otra" incluye SMS/wa.link y anuncios sin enlace
    reconocible. Cada fila trae además `redes`: cuántas de sus conversaciones
    son de cada red, con el mismo filtrado.

    `desde`/`hasta` (Gate Analítica P0) — opcionales, retrocompatibles con
    los 2 llamadores existentes que no los pasan (dashboard.py:6268 y los
    tests de Gate Campañas P0/5.6). Filtran por `Conversation.creado` — la
    misma columna que ya usaba esta función implícitamente como ventana
    "todo el histórico" cuando ambos vienen en `None`. Ya convertidos a UTC
    por quien llama (ver `rango_periodo_utc`); esta función nunca interpreta
    zona horaria.

    Gate 5.6 — reemplaza `contar_leads_por_campana()`: la versión anterior
    agrupaba por `Lead.campana_origen` (string legacy, first-touch inmutable)
    SIN `negocio_id` — con dos Negocios usando una campaña de nombre igual,
    los conteos de leads/ventas se mezclaban entre ambos (hallazgo confirmado
    de forma independiente por los 4 agentes de la investigación de Gate
    5.6). Esta versión cuenta sobre `Conversation.campana_origen_id` (FK real
    a Campana, poblada desde Gate 5.3) en vez de reconstruir el mismo tipo de
    bug sobre el modelo legacy.

    Dos consultas scoped (campañas del Negocio, luego conteos agregados por
    campana_origen_id) en vez de un JOIN directo Campana→Conversation→
    Opportunity: un LEFT JOIN de 3 tablas infla `total` si alguna vez una
    Conversation llega a tener más de una Opportunity (la cardinalidad hoy es
    0..1 por diseño, Diseño Técnico Gate 5.3 §6, pero esta forma es correcta
    sin depender de esa suposición). Sigue sin ser N+1: son 3 queries fijas,
    sin importar cuántas campañas o conversations existan.

    No filtra por `Conversation.estado` — cuenta TODA conversación histórica
    atribuida a la campaña, igual que el conteo legacy (que tampoco filtraba
    por estado del Lead). Filtrar solo "activas" sería una regresión
    silenciosa de comportamiento, no una corrección."""
    async with async_session() as session:
        query_campanas = select(Campana.id, Campana.nombre, Campana.activa).where(Campana.negocio_id == negocio_id)
        if unidad_id is not None:
            query_campanas = query_campanas.where(Campana.unidad_id == unidad_id)
        campanas = (await session.execute(query_campanas)).all()
        if not campanas:
            return []
        ids_campana = [c.id for c in campanas]

        query_total = (
            select(Conversation.campana_origen_id, func.count(Conversation.id))
            .where(Conversation.campana_origen_id.in_(ids_campana))
            .group_by(Conversation.campana_origen_id)
        )
        query_vendidos = (
            select(Conversation.campana_origen_id, func.count(func.distinct(Conversation.id)))
            .select_from(Conversation)
            .join(Opportunity, Opportunity.conversation_id == Conversation.id)
            .where(Conversation.campana_origen_id.in_(ids_campana), Opportunity.resultado == "vendido")
            .group_by(Conversation.campana_origen_id)
        )
        redes_de_conversation = await _red_por_conversation(session, negocio_id)
        filtros = []
        if desde is not None:
            filtros.append(Conversation.creado >= desde)
        if hasta is not None:
            filtros.append(Conversation.creado < hasta)
        if asesor is not None:
            # Responsable ACTUAL (Gate Analítica P0) — mismo criterio ya
            # cerrado en todo el módulo, sin reconstruir historial.
            filtros.append(Conversation.asesor_asignado_id == asesor)
        if red is not None:
            if red == "otra":
                filtros.append(Conversation.id.not_in([c for c, r in redes_de_conversation.items() if r != "otra"]))
            else:
                filtros.append(Conversation.id.in_([c for c, r in redes_de_conversation.items() if r == red]))
        if filtros:
            query_total = query_total.where(*filtros)
            query_vendidos = query_vendidos.where(*filtros)

        totales = dict((await session.execute(query_total)).all())
        vendidos = dict((await session.execute(query_vendidos)).all())

        redes_por_campana: dict[int, dict[str, int]] = {}
        query_conversaciones = select(Conversation.id, Conversation.campana_origen_id).where(
            Conversation.campana_origen_id.in_(ids_campana), *filtros,
        )
        for conversation_id, campana_id in (await session.execute(query_conversaciones)).all():
            redes = redes_por_campana.setdefault(campana_id, {"facebook": 0, "instagram": 0, "otra": 0})
            redes[redes_de_conversation.get(conversation_id, "otra")] += 1

        return [
            {
                # "id"/"activa" (Gate Analítica P0) — adición retrocompatible,
                # ningún llamador existente lee otra cosa que no sea
                # "campana"/"total"/"vendidos" (confirmado contra
                # test_gate_campanas_p0.py y test_gate56_atribucion_scoped.py).
                "id": c.id, "campana": c.nombre, "activa": c.activa,
                "total": totales.get(c.id, 0), "vendidos": vendidos.get(c.id, 0),
                "redes": redes_por_campana.get(c.id, {"facebook": 0, "instagram": 0, "otra": 0}),
            }
            for c in campanas
        ]


# ── Analítica P0 (Gate Analítica P0) ────────────────────────────────────
#
# Toda función de esta sección exige `negocio_id` como primer parámetro
# obligatorio, sin default (mismo criterio fail-closed que el resto del
# proyecto desde Gate 5.2). `desde`/`hasta`, cuando aplican, son `datetime`
# YA convertidos a UTC por quien llama — ver `rango_periodo_utc` — ninguna
# función de acá interpreta zona horaria por su cuenta.
#
# "Leads sin atención"/"Leads estancados" quedaron deliberadamente FUERA de
# esta sección (Gate Analítica P0, decisión Opción C): `Conversation.
# paso_flujo` existe en el esquema pero no lo escribe ni lo lee ningún
# código real (confirmado por grep en todo el repo) — sin esa señal no hay
# forma de distinguir "Gabi todavía atendiendo con normalidad" de "ya se
# derivó a un humano y nadie tomó todavía" usando el modelo moderno
# (Conversation/Opportunity). Aproximarlo con `asesor_asignado_id IS NULL`
# mezclaría ambos casos y mostraría una fuga que no es real; volver a
# `Lead.paso_flujo` (legacy) reabriría una fuente de datos ya descartada
# como canónica para esta capa. Documentado como deuda de producto, no
# resuelto acá.


def rango_periodo_utc(desde: str, hasta: str) -> tuple[datetime, datetime]:
    """Convierte un rango de fechas de calendario (`YYYY-MM-DD`,
    interpretadas en America/Lima, UTC-5 fijo — Perú no observa horario de
    verano) al rango UTC `[inicio, fin)` que filtra cualquier columna
    DateTime del proyecto (todas se guardan naive, ya en UTC — ver
    `iso_utc`). `hasta` es el ÚLTIMO día INCLUIDO, no el primero excluido:
    el límite superior devuelto es la medianoche del día siguiente en Lima,
    convertida a UTC, para que un dato de último minuto de ese día en Lima
    todavía entre en el rango."""
    inicio_lima = datetime.strptime(desde, "%Y-%m-%d")
    fin_lima = datetime.strptime(hasta, "%Y-%m-%d") + timedelta(days=1)
    offset = timedelta(hours=5)
    return inicio_lima + offset, fin_lima + offset


def _filtrar_opportunity_por_conversation(query, asesor: str | None, campana_id: int | None):
    """Aplica el filtro de asesor/campaña a una query de `Opportunity` que
    todavía no se unió con `Conversation` (Gate Analítica P0) — un solo JOIN
    cuando cualquiera de los dos viene informado, nunca dos JOIN separados
    contra la misma tabla. `Opportunity` no tiene su propio campo de asesor
    ni de campaña; ambos viven en `Conversation`."""
    if asesor is None and campana_id is None:
        return query
    query = query.join(Conversation, Conversation.id == Opportunity.conversation_id)
    if asesor is not None:
        query = query.where(Conversation.asesor_asignado_id == asesor)
    if campana_id is not None:
        query = query.where(Conversation.campana_origen_id == campana_id)
    return query


async def _contar_ventas_periodo(
    negocio_id: str, desde: datetime, hasta: datetime,
    unidad_id: str | None = None, asesor: str | None = None, campana_id: int | None = None,
) -> int:
    """Única fuente de 'ventas del período' — `contar_flujo_periodo` y
    `calcular_embudo_comercial` llaman EXACTAMENTE esta función (Gate
    Analítica P0): nunca deben mostrar números distintos para 'ventas' en
    la misma respuesta, y la única forma de garantizarlo es que sea
    literalmente el mismo cálculo, no dos fórmulas parecidas.

    `asesor` — responsable ACTUAL de la Conversation
    (`Conversation.asesor_asignado_id`), mismo criterio ya cerrado para el
    filtro de asesor en todo el módulo: nunca reconstruye quién tuvo el
    lead antes de una reasignación."""
    async with async_session() as session:
        query = (
            select(func.count(Opportunity.id))
            .select_from(Opportunity)
            .where(
                Opportunity.negocio_id == negocio_id,
                Opportunity.resultado == "vendido",
                Opportunity.fecha_cierre >= desde,
                Opportunity.fecha_cierre < hasta,
            )
        )
        if unidad_id is not None:
            query = query.where(Opportunity.unidad_id == unidad_id)
        query = _filtrar_opportunity_por_conversation(query, asesor, campana_id)
        return (await session.execute(query)).scalar_one()


# ── Métrica del embudo: ¿cuentan las consultas no comerciales? (2026-10-08, decisión del dueño) ──
#
# Cada `consulta_atc` es una Opportunity más: sin tocar nada, baja la tasa de cierre aunque nunca fue una
# oportunidad comercial. Es CONFIGURABLE por negocio (default apagado = comportamiento de siempre):
#   `metricas_excluir_consulta_atc`        "1"/"0" (default "0").
#   `metricas_excluir_consulta_atc_desde`  fecha de corte AAAA-MM-DD (Lima, opcional): solo se excluyen las
#                                          consultas de oportunidades creadas desde ese día; vacío = todo el
#                                          período consultado.
# Con la exclusión activa las consultas NO se ocultan: salen en `consultas_no_comerciales` (cantidad y
# porcentaje sobre los contactos del período) y la tasa bruta sigue disponible.

CLAVE_METRICAS_EXCLUIR_ATC = "metricas_excluir_consulta_atc"
CLAVE_METRICAS_EXCLUIR_ATC_DESDE = "metricas_excluir_consulta_atc_desde"
RESULTADO_CONSULTA_NO_COMERCIAL = "consulta_atc"


def normalizar_politica_metricas(excluir, desde) -> dict:
    """`{"excluir_consulta_atc": bool, "desde": datetime|None}` (UTC naive) a partir de los dos valores
    guardados. Cualquier valor inválido cae al comportamiento de siempre (no excluir / sin corte)."""
    activo = str(excluir if excluir is not None else "0").strip().lower() in ("1", "true", "si", "sí", "on", "activo", "yes")
    corte = None
    texto = str(desde or "").strip()
    if texto:
        try:
            if len(texto) <= 10:
                corte = rango_periodo_utc(texto, texto)[0]  # medianoche de Lima de ese día, en UTC
            else:
                corte = datetime.fromisoformat(texto).replace(tzinfo=None)
        except ValueError:
            corte = None
    return {"excluir_consulta_atc": activo, "desde": corte}


async def obtener_politica_metricas(negocio_id: str) -> dict:
    """Ver `normalizar_politica_metricas`. Nunca lanza: ante un fallo de lectura, no excluye."""
    try:
        excluir = await obtener_configuracion(CLAVE_METRICAS_EXCLUIR_ATC, "0", negocio_id=negocio_id)
        desde = await obtener_configuracion(CLAVE_METRICAS_EXCLUIR_ATC_DESDE, "", negocio_id=negocio_id)
    except Exception:
        return {"excluir_consulta_atc": False, "desde": None}
    return normalizar_politica_metricas(excluir, desde)


# Configuración de la métrica desde el panel (2026-10-09): lo que antes solo fijaba `scripts/configurar_triaje_atc.py`.
SIN_CAMBIO_METRICAS = object()   # "no tocar la fecha de corte" (distinto de None = "borrarla")


def validar_fecha_corte_metricas(valor) -> str:
    """'' si no hay corte; si no, la fecha AAAA-MM-DD (día de Lima) ya validada. Lanza ValueError con el motivo."""
    if valor is None:
        return ""
    if not isinstance(valor, str):
        raise ValueError("La fecha de corte debe ser un texto AAAA-MM-DD (o vacío).")
    texto = valor.strip()
    if not texto:
        return ""
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", texto):
        raise ValueError("La fecha de corte debe tener el formato AAAA-MM-DD (o ir vacía).")
    try:
        dia = datetime.strptime(texto, "%Y-%m-%d")
    except ValueError:
        raise ValueError("La fecha de corte no es un día válido del calendario.")
    if not 2020 <= dia.year <= 2100:
        raise ValueError("La fecha de corte debe estar entre los años 2020 y 2100.")
    return texto


async def obtener_configuracion_metricas(negocio_id: str) -> dict:
    """Lo guardado, listo para la pantalla: `{"excluir_consulta_atc": bool, "excluir_desde": "AAAA-MM-DD"|None}`.
    Un corte guardado que no sea una fecha válida se informa como ausente (así lo trata el cálculo)."""
    excluir = await obtener_configuracion(CLAVE_METRICAS_EXCLUIR_ATC, "0", negocio_id=negocio_id)
    desde = await obtener_configuracion(CLAVE_METRICAS_EXCLUIR_ATC_DESDE, "", negocio_id=negocio_id)
    try:
        corte = validar_fecha_corte_metricas(desde) or None
    except ValueError:
        corte = None
    return {"excluir_consulta_atc": normalizar_politica_metricas(excluir, None)["excluir_consulta_atc"], "excluir_desde": corte}


async def guardar_configuracion_metricas(
    negocio_id: str, excluir, desde=SIN_CAMBIO_METRICAS, autor: str | None = None,
) -> dict:
    """Valida y guarda la política de la métrica del embudo desde el panel (ver `normalizar_politica_metricas`).
    `excluir` debe ser un booleano; `desde`: AAAA-MM-DD, ''/None para borrar el corte, o `SIN_CAMBIO_METRICAS`
    para dejarlo como está. Los dos valores y la fila de auditoría (quién, cuándo, antes y después) van en UNA
    transacción. Lanza ValueError con el motivo si algo no es válido (no guarda nada). Devuelve
    `{"modificadas": [claves]}`."""
    if not isinstance(excluir, bool):
        raise ValueError("`excluir_consulta_atc` debe ser true o false.")
    cambios = {CLAVE_METRICAS_EXCLUIR_ATC: "1" if excluir else "0"}
    if desde is not SIN_CAMBIO_METRICAS:
        cambios[CLAVE_METRICAS_EXCLUIR_ATC_DESDE] = validar_fecha_corte_metricas(desde)
    por_defecto = {CLAVE_METRICAS_EXCLUIR_ATC: "0", CLAVE_METRICAS_EXCLUIR_ATC_DESDE: ""}

    async with async_session() as session:
        actuales = {
            c.clave: c for c in (await session.execute(
                select(Configuracion).where(Configuracion.negocio_id == negocio_id, Configuracion.clave.in_(list(cambios)))
            )).scalars().all()
        }
        registro: dict[str, dict] = {}
        for clave, valor in cambios.items():
            existente = actuales.get(clave)
            antes = existente.valor if existente else None
            if (antes if antes is not None else por_defecto[clave]) == valor:
                continue   # ya estaba así (o es el valor por defecto): ni se escribe ni se audita
            if existente is None:
                session.add(Configuracion(clave=clave, negocio_id=negocio_id, valor=valor))
            else:
                existente.valor = valor
            registro[clave] = {"antes": antes, "despues": valor}
        if registro:
            session.add(RegistroAuditoria(
                accion="metricas_configuracion", actor=autor, negocio_id=negocio_id, entidad_tipo="configuracion",
                payload={"cambios": registro, "riesgo_confirmado": False},
            ))
        await session.commit()
    return {"modificadas": sorted(registro)}


async def contar_consultas_atc_recientes(negocio_id: str, dias: int = 30) -> dict:
    """Contexto para la pantalla: cuántas oportunidades de los últimos `dias` días son consultas no comerciales
    (`consulta_atc`) sobre el total, SIN importar si la exclusión está activa. `{"dias", "consultas",
    "oportunidades", "porcentaje"}` (porcentaje None si no hubo oportunidades)."""
    hasta = datetime.utcnow() + timedelta(minutes=1)
    desde = hasta - timedelta(days=dias)
    async with async_session() as session:
        consultas = await _contar_consultas_no_comerciales(session, negocio_id, desde, hasta, None)
        total = (await session.execute(
            select(func.count(Opportunity.id)).where(
                Opportunity.negocio_id == negocio_id, Opportunity.creado >= desde, Opportunity.creado < hasta,
            )
        )).scalar_one()
    return {
        "dias": dias, "consultas": consultas, "oportunidades": total,
        "porcentaje": round(100 * consultas / total, 1) if total > 0 else None,
    }


async def _contar_consultas_no_comerciales(
    session, negocio_id: str, desde: datetime, hasta: datetime, corte: datetime | None,
    unidad_id: str | None = None, asesor: str | None = None, campana_id: int | None = None,
) -> int:
    """Oportunidades del período con resultado `consulta_atc` (mismos filtros que el resto del embudo). Con
    `corte`, solo las creadas desde esa fecha."""
    inicio = max(desde, corte) if corte is not None else desde
    if inicio >= hasta:
        return 0
    query = (
        select(func.count(Opportunity.id))
        .select_from(Opportunity)
        .where(
            Opportunity.negocio_id == negocio_id, Opportunity.resultado == RESULTADO_CONSULTA_NO_COMERCIAL,
            Opportunity.creado >= inicio, Opportunity.creado < hasta,
        )
    )
    query = _filtrar_opportunity_por_conversation(query, asesor, campana_id)
    if unidad_id is not None:
        query = query.where(Opportunity.unidad_id == unidad_id)
    return (await session.execute(query)).scalar_one()


def _bloque_consultas_no_comerciales(cantidad: int, brutas: int, corte: datetime | None) -> dict:
    return {
        "cantidad": cantidad,
        "porcentaje_de_contactos": round(100 * cantidad / brutas, 1) if brutas > 0 else None,
        "excluidas_desde": corte.isoformat() if corte is not None else None,
    }


async def contar_flujo_periodo(
    negocio_id: str, desde: datetime, hasta: datetime,
    unidad_id: str | None = None, asesor: str | None = None, campana_id: int | None = None,
) -> dict:
    """Volumen registrado por etapa durante el período — CONTEXTO, no
    funnel de conversión (Gate Analítica P0): Contact→Conversation y
    Conversation→Opportunity son transiciones estructurales del sistema
    (una Opportunity se crea siempre y únicamente junto con su Conversation,
    ver `resolver_conversation_activa`), no decisiones de gestión — por eso
    esta función nunca calcula un porcentaje entre etapas, solo el volumen
    de cada una.

    `asesor`/`campana_id` — un Contact no tiene responsable ni campaña
    propios (solo una Conversation los tiene), así que "leads" scoped a
    cualquiera de los dos se redefine como Contacts DISTINTOS detrás de las
    Conversation que califican en el período — misma relación
    `Conversation.contact_id` ya existente, no una nueva."""
    filtro_activo = asesor is not None or campana_id is not None
    async with async_session() as session:
        if filtro_activo:
            query_leads = select(func.count(func.distinct(Conversation.contact_id))).where(
                Conversation.negocio_id == negocio_id,
                Conversation.creado >= desde, Conversation.creado < hasta,
            )
            if asesor is not None:
                query_leads = query_leads.where(Conversation.asesor_asignado_id == asesor)
            if campana_id is not None:
                query_leads = query_leads.where(Conversation.campana_origen_id == campana_id)
        else:
            query_leads = select(func.count(Contact.id)).where(
                Contact.negocio_id == negocio_id, Contact.eliminado_en.is_(None),
                Contact.creado >= desde, Contact.creado < hasta,
            )
        query_conversaciones = select(func.count(Conversation.id)).where(
            Conversation.negocio_id == negocio_id,
            Conversation.creado >= desde, Conversation.creado < hasta,
        )
        if asesor is not None:
            query_conversaciones = query_conversaciones.where(Conversation.asesor_asignado_id == asesor)
        if campana_id is not None:
            query_conversaciones = query_conversaciones.where(Conversation.campana_origen_id == campana_id)

        query_oportunidades = (
            select(func.count(Opportunity.id))
            .select_from(Opportunity)
            .where(
                Opportunity.negocio_id == negocio_id,
                Opportunity.creado >= desde, Opportunity.creado < hasta,
            )
        )
        query_oportunidades = _filtrar_opportunity_por_conversation(query_oportunidades, asesor, campana_id)
        if unidad_id is not None:
            query_conversaciones = query_conversaciones.where(Conversation.unidad_id == unidad_id)
            query_oportunidades = query_oportunidades.where(Opportunity.unidad_id == unidad_id)
        leads = (await session.execute(query_leads)).scalar_one()
        conversaciones = (await session.execute(query_conversaciones)).scalar_one()
        oportunidades = (await session.execute(query_oportunidades)).scalar_one()
        politica = await obtener_politica_metricas(negocio_id)
        consultas = (
            await _contar_consultas_no_comerciales(
                session, negocio_id, desde, hasta, politica["desde"], unidad_id, asesor, campana_id,
            ) if politica["excluir_consulta_atc"] else 0
        )
    ventas = await _contar_ventas_periodo(negocio_id, desde, hasta, unidad_id, asesor, campana_id)
    flujo = {"leads": leads, "conversaciones": conversaciones, "oportunidades": oportunidades, "ventas": ventas}
    if politica["excluir_consulta_atc"]:
        # Aditivo: `oportunidades` pasa a ser la comercial (misma cifra que el embudo) y la bruta sigue visible.
        flujo.update({
            "oportunidades": oportunidades - consultas, "oportunidades_brutas": oportunidades,
            "consultas_no_comerciales": _bloque_consultas_no_comerciales(consultas, oportunidades, politica["desde"]),
        })
    return flujo


async def calcular_embudo_comercial(
    negocio_id: str, desde: datetime, hasta: datetime,
    unidad_id: str | None = None, asesor: str | None = None, campana_id: int | None = None,
) -> dict:
    """El único funnel de desempeño comercial de P0 (Gate Analítica P0):
    Oportunidad → Venta. `tasa_cierre` es `None` (no 0) cuando no hubo
    ninguna oportunidad en el período — dividir por cero no es "0% de
    cierre", es "no hay nada que medir todavía"."""
    async with async_session() as session:
        query = (
            select(func.count(Opportunity.id))
            .select_from(Opportunity)
            .where(
                Opportunity.negocio_id == negocio_id,
                Opportunity.creado >= desde, Opportunity.creado < hasta,
            )
        )
        query = _filtrar_opportunity_por_conversation(query, asesor, campana_id)
        if unidad_id is not None:
            query = query.where(Opportunity.unidad_id == unidad_id)
        oportunidades = (await session.execute(query)).scalar_one()
        politica = await obtener_politica_metricas(negocio_id)
        consultas = (
            await _contar_consultas_no_comerciales(
                session, negocio_id, desde, hasta, politica["desde"], unidad_id, asesor, campana_id,
            ) if politica["excluir_consulta_atc"] else 0
        )
    ventas = await _contar_ventas_periodo(negocio_id, desde, hasta, unidad_id, asesor, campana_id)
    if not politica["excluir_consulta_atc"]:
        tasa_cierre = (ventas / oportunidades) if oportunidades > 0 else None
        return {"oportunidades": oportunidades, "ventas": ventas, "tasa_cierre": tasa_cierre}
    # Exclusión activa (2026-10-08, configurable): el denominador es solo lo comercial. Contrato ADITIVO: las
    # claves de siempre se mantienen (ahora con la cifra comercial) y se suman la bruta y las consultas.
    comerciales = oportunidades - consultas
    return {
        "oportunidades": comerciales, "ventas": ventas,
        "tasa_cierre": (ventas / comerciales) if comerciales > 0 else None,
        "oportunidades_brutas": oportunidades,
        "tasa_cierre_bruta": (ventas / oportunidades) if oportunidades > 0 else None,
        "consultas_no_comerciales": _bloque_consultas_no_comerciales(consultas, oportunidades, politica["desde"]),
        "excluye_consulta_atc": True,
    }


async def contar_oportunidades_por_asesor(
    negocio_id: str, usernames: list[str], desde: datetime, hasta: datetime,
    unidad_id: str | None = None, campana_id: int | None = None,
) -> dict[str, dict]:
    """Oportunidades/ventas/tasa de cierre por RESPONSABLE ACTUAL (Gate
    Analítica P0) — `Conversation.asesor_asignado_id`, nunca reconstruye
    quién tuvo el lead antes de una reasignación (misma decisión ya cerrada
    para el filtro de asesor). Mismo patrón de JOIN y mismo criterio
    temporal (`Conversation.creado`) que `contar_opportunities_por_campana`,
    agrupado por asesor en vez de por campaña. `campana_id` combina ambos
    filtros (ej. "el equipo, pero solo para esta campaña")."""
    if not usernames:
        return {}
    async with async_session() as session:
        query = (
            select(Conversation.asesor_asignado_id, Opportunity.resultado)
            .join(Opportunity, Opportunity.conversation_id == Conversation.id)
            .where(
                Conversation.negocio_id == negocio_id,
                Conversation.asesor_asignado_id.in_(usernames),
                Conversation.creado >= desde, Conversation.creado < hasta,
            )
        )
        if unidad_id is not None:
            query = query.where(Conversation.unidad_id == unidad_id)
        if campana_id is not None:
            query = query.where(Conversation.campana_origen_id == campana_id)
        result = await session.execute(query)
        datos = {u: {"oportunidades": 0, "ventas": 0} for u in usernames}
        for asesor, resultado in result.all():
            datos[asesor]["oportunidades"] += 1
            if resultado == "vendido":
                datos[asesor]["ventas"] += 1
    for fila in datos.values():
        fila["tasa_cierre"] = (fila["ventas"] / fila["oportunidades"]) if fila["oportunidades"] > 0 else None
    return datos


async def distribucion_resultados_periodo(
    negocio_id: str, desde: datetime, hasta: datetime,
    unidad_id: str | None = None, asesor: str | None = None, campana_id: int | None = None,
) -> list[dict]:
    """Oportunidades del período agrupadas por resultado — sin inventar
    categorías nuevas, usa exactamente los valores ya escritos en
    `Opportunity.resultado`."""
    async with async_session() as session:
        query = (
            select(Opportunity.resultado, func.count(Opportunity.id))
            .select_from(Opportunity)
            .where(
                Opportunity.negocio_id == negocio_id,
                Opportunity.creado >= desde, Opportunity.creado < hasta,
            )
            .group_by(Opportunity.resultado)
        )
        query = _filtrar_opportunity_por_conversation(query, asesor, campana_id)
        if unidad_id is not None:
            query = query.where(Opportunity.unidad_id == unidad_id)
        result = await session.execute(query)
        return [{"resultado": r or "sin_resultado", "total": t} for r, t in result.all()]


async def resumen_ventas_periodo(
    negocio_id: str, desde: datetime, hasta: datetime,
    unidad_id: str | None = None, asesor: str | None = None, campana_id: int | None = None,
) -> dict:
    """Valor vendido del período, con el mismo fail-safe ya usado en
    `_resumen_venta` (dashboard.py): si AL MENOS una línea de una venta no
    es numérica, esa venta COMPLETA se excluye del total (nunca se suma solo
    la parte parcial, que parecería un número completo sin serlo) y se
    cuenta aparte en `ventas_excluidas`."""
    async with async_session() as session:
        query = (
            select(LineaVenta.opportunity_id, LineaVenta.precio)
            .select_from(LineaVenta)
            .join(Opportunity, Opportunity.id == LineaVenta.opportunity_id)
            .where(
                Opportunity.negocio_id == negocio_id, Opportunity.resultado == "vendido",
                Opportunity.fecha_cierre >= desde, Opportunity.fecha_cierre < hasta,
            )
        )
        query = _filtrar_opportunity_por_conversation(query, asesor, campana_id)
        if unidad_id is not None:
            query = query.where(Opportunity.unidad_id == unidad_id)
        filas = (await session.execute(query)).all()

    lineas_por_opportunity: dict[str, list[str | None]] = {}
    for opportunity_id, precio in filas:
        lineas_por_opportunity.setdefault(opportunity_id, []).append(precio)

    total = 0.0
    ventas_excluidas = 0
    for lineas in lineas_por_opportunity.values():
        subtotal = 0.0
        valido = True
        for precio in lineas:
            try:
                subtotal += float((precio or "0").replace(",", ""))
            except ValueError:
                valido = False
                break
        if valido:
            total += subtotal
        else:
            ventas_excluidas += 1
    return {"monto": f"{total:.2f}", "ventas_excluidas": ventas_excluidas}


async def productos_vendidos_periodo(
    negocio_id: str, desde: datetime, hasta: datetime,
    unidad_id: str | None = None, asesor: str | None = None, campana_id: int | None = None,
) -> list[dict]:
    """Unidades y valor por producto vendido en el período — `valor` es
    `None` (no un número parcial) para un producto puntual si alguna de sus
    líneas no es numérica; `unidades` no depende de eso, sigue siendo un
    conteo real. Ordenado por unidades descendente."""
    async with async_session() as session:
        query = (
            select(LineaVenta.producto, LineaVenta.precio)
            .select_from(LineaVenta)
            .join(Opportunity, Opportunity.id == LineaVenta.opportunity_id)
            .where(
                Opportunity.negocio_id == negocio_id, Opportunity.resultado == "vendido",
                Opportunity.fecha_cierre >= desde, Opportunity.fecha_cierre < hasta,
            )
        )
        query = _filtrar_opportunity_por_conversation(query, asesor, campana_id)
        if unidad_id is not None:
            query = query.where(Opportunity.unidad_id == unidad_id)
        filas = (await session.execute(query)).all()

    agregados: dict[str, dict] = {}
    for producto, precio in filas:
        entrada = agregados.setdefault(producto, {"unidades": 0, "valor": 0.0, "valor_confiable": True})
        entrada["unidades"] += 1
        try:
            entrada["valor"] += float((precio or "0").replace(",", ""))
        except ValueError:
            entrada["valor_confiable"] = False

    return [
        {
            "producto": nombre,
            "unidades": datos["unidades"],
            "valor": f"{datos['valor']:.2f}" if datos["valor_confiable"] else None,
        }
        for nombre, datos in sorted(agregados.items(), key=lambda kv: kv[1]["unidades"], reverse=True)
    ]


async def limpiar_historial(telefono: str):
    """Borra todo el historial de una conversación.

    Gate 5.3 — corrección: mismo patrón telefono-only que tenía
    `guardar_venta` antes de este Gate (DELETE filtrado SOLO por telefono,
    hallazgo del bloque de Decisiones Arquitectónicas Gate 5.3). Código sin
    call sites reales hoy (confirmado por grep en toda la auditoría), pero
    corregido igual — mina latente si se conecta a un endpoint real sin
    revisar antes. Se agrega `negocio_id` como candado adicional."""
    async with async_session() as session:
        lead = await session.get(Lead, telefono)
        query = select(Mensaje).where(Mensaje.telefono == telefono)
        if lead is not None:
            query = query.where(Mensaje.negocio_id == lead.negocio_id)
        result = await session.execute(query)
        mensajes = result.scalars().all()
        for msg in mensajes:
            session.delete(msg)
        await session.commit()


def _archivo_a_dict(a: ArchivoAdjunto) -> dict:
    return {
        "id": a.id, "nombre_original": a.nombre_original, "ruta_disco": a.ruta_disco,
        "content_type": a.content_type, "tamano_bytes": a.tamano_bytes,
        "reutilizable": a.reutilizable, "etiqueta": a.etiqueta,
        "subido_por": a.subido_por, "creado": a.creado, "negocio_id": a.negocio_id,
    }


async def crear_archivo_adjunto(
    nombre_original: str, ruta_disco: str, content_type: str, tamano_bytes: int,
    subido_por: str, reutilizable: bool = False, etiqueta: str | None = None,
    negocio_id: str | None = None,
) -> dict:
    """Registra un archivo ya guardado en disco (proforma puntual o catálogo
    reutilizable) — ver ARCHIVOS_DIR en dashboard.py para dónde vive el
    archivo. negocio_id es obligatorio para reutilizable=True (dueño tenant
    del catálogo, nunca compartido entre negocios); las proformas no lo
    necesitan y quedan en None — siguen aisladas de forma indirecta vía
    Mensaje.archivo_id → Mensaje.telefono → Lead.negocio_id."""
    if reutilizable and not negocio_id:
        raise ValueError("negocio_id es obligatorio para crear un archivo reutilizable")
    async with async_session() as session:
        archivo = ArchivoAdjunto(
            nombre_original=nombre_original, ruta_disco=ruta_disco, content_type=content_type,
            tamano_bytes=tamano_bytes, reutilizable=reutilizable, etiqueta=etiqueta, subido_por=subido_por,
            negocio_id=negocio_id,
        )
        session.add(archivo)
        await session.commit()
        await session.refresh(archivo)
        return _archivo_a_dict(archivo)


async def obtener_archivo_adjunto(archivo_id: int) -> dict | None:
    async with async_session() as session:
        archivo = await session.get(ArchivoAdjunto, archivo_id)
        return _archivo_a_dict(archivo) if archivo else None


async def listar_archivos_reutilizables(negocio_id: str) -> list[dict]:
    """Librería de catálogos ya subidos por ESTE negocio, listos para
    enviar en cualquier conversación sin volver a subirlos — más recientes
    primero. `negocio_id` es obligatorio: nunca devuelve catálogos de otro
    negocio (hallazgo de aislamiento cerrado en este Gate — antes esta
    consulta no tenía ningún predicado de tenant)."""
    async with async_session() as session:
        query = (
            select(ArchivoAdjunto)
            .where(
                ArchivoAdjunto.reutilizable.is_(True),
                ArchivoAdjunto.negocio_id == negocio_id,
            )
            .order_by(ArchivoAdjunto.creado.desc())
        )
        result = await session.execute(query)
        return [_archivo_a_dict(a) for a in result.scalars().all()]


async def eliminar_archivo_reutilizable(archivo_id: int, negocio_id: str) -> bool:
    """Quita un catálogo de la librería (no borra el archivo físico del disco,
    por si algún mensaje viejo todavía lo referencia — solo dejar de ofrecerlo
    para envíos nuevos). Exige negocio_id: nunca desactiva un catálogo de
    otro negocio, aunque el id exista y sea válido. Retorna False si el
    archivo no existe o pertenece a otro negocio — el caller (ruta) decide
    si eso es un 404 o un 403."""
    async with async_session() as session:
        archivo = await session.get(ArchivoAdjunto, archivo_id)
        if archivo is None or archivo.negocio_id != negocio_id:
            return False
        archivo.reutilizable = False
        await session.commit()
        return True


async def obtener_telefono_de_archivo(archivo_id: int) -> str | None:
    """A qué lead se le envió un archivo puntual (proforma) — para poder
    verificar que quien lo quiere descargar tiene acceso a ese lead. Un
    catálogo reutilizable puede estar ligado a varios leads, así que esto
    solo tiene sentido/se usa para archivos no reutilizables."""
    async with async_session() as session:
        query = select(Mensaje.telefono).where(Mensaje.archivo_id == archivo_id).limit(1)
        result = await session.execute(query)
        return result.scalar_one_or_none()


async def listar_archivos_no_reutilizables_antes_de(corte: datetime) -> list[dict]:
    """Proformas y notas de voz (`reutilizable=False`) subidas antes de
    `corte` — para el Cron de expiración de adjuntos (2026-09-16, pedido
    explícito del usuario tras el fix de tamaño de adjuntos: "esos catalogos
    pesados se queden en la memoria ocupando espacio o lo podemos expirar").
    Retención acordada: 90 días (más generosa que el límite propio de Meta
    de 30 días para media de WhatsApp Cloud API, y en línea con referencias
    de retención de CRMs para datos de alto volumen).

    Los catálogos reutilizables (`reutilizable=True`) NUNCA entran acá — se
    referencian desde muchos leads a la vez (reenviar el mismo catálogo no
    sube un archivo nuevo, ver `enviar_catalogo_chat` en dashboard.py), así
    que expirarlos rompería el historial de CUALQUIER lead al que se le
    haya mandado, no solo uno. Su borrado sigue siendo una acción manual
    explícita (`eliminar_archivo_reutilizable`), que además — a propósito —
    tampoco toca el disco, por la misma razón.

    Solo devuelve metadatos (para que el script que llama esto haga el
    `os.remove` real) — esta función nunca toca el disco, mismo criterio de
    capas que el resto de memory.py."""
    async with async_session() as session:
        query = select(ArchivoAdjunto).where(
            ArchivoAdjunto.reutilizable.is_(False),
            ArchivoAdjunto.creado < corte,
        )
        result = await session.execute(query)
        return [
            {"id": a.id, "ruta_disco": a.ruta_disco, "nombre_original": a.nombre_original, "creado": a.creado}
            for a in result.scalars().all()
        ]


# ── Catálogo de productos / lista de precios (Catálogo editable — sub-bloque a) ──
#
# CODIGO HANA no es único (filas "EN CREACIÓN" repetidas) — nunca usar como
# clave de búsqueda exacta con expectativa de una sola fila, ver Producto.

PLAZOS_CUOTAS_CATALOGO = ("3", "6", "9", "12", "18", "24", "36", "48", "60")

# Campos de negocio de un producto — los que definen QUÉ es el producto y a
# qué precio se vende. Excluye id/activo/creado/actualizado/version, que son
# metadatos del registro, no del producto. Se usan para: (a) el diff de la
# importación, (b) la comparación de igualdad exacta de las filas
# "EN CREACIÓN", (c) la auditoría campo por campo de una edición manual.
CAMPOS_NEGOCIO_PRODUCTO = (
    "canal", "proveedor", "marca", "tipo", "sub_tipo", "codigo_hana",
    "descripcion", "combo", "incluye_conexion", "comentarios", "fee_prv", "fee_clda", "precio",
)

# Campos que un admin puede editar desde el panel — los de negocio más las
# cuotas. `activo` NO está acá: se cambia por su propia ruta (toggle), para
# que activar/desactivar sea una decisión explícita y no un efecto colateral
# de guardar un formulario.
CAMPOS_EDITABLES_PRODUCTO = CAMPOS_NEGOCIO_PRODUCTO + ("cuotas",)

# Valores de `HistorialPrecioProducto.campo` que NO son un campo del producto
# sino un hecho sobre el registro. Se usan valores sentinel con guiones bajos
# para que nunca colisionen con un nombre de campo real. Verificado antes de
# escribir esta lógica: la tabla existente (campo/valor_anterior/valor_nuevo/
# autor/creado) alcanza para representar "creación" y "activo→inactivo" sin
# cambiar el esquema — una creación es (campo=__creado__, anterior=None,
# nuevo=descripción) y un cambio de estado es (campo=activo, anterior/nuevo
# en "true"/"false").
CAMPO_AUDITORIA_CREADO = "__creado__"
CAMPO_AUDITORIA_ACTIVO = "activo"

# Duplicado real confirmado entre proveedores distintos (revisado con Jesús
# el 10/07/2026, antes vivía como FILAS_DUPLICADAS_EXCLUIDAS en tools.py):
# mismo modelo LG WT16OBVTB 16KG, listado dos veces con precio distinto. La
# fila de GRUPO MERPES (S/2569, sin CODIGO HANA real todavía) se excluye a
# favor de la de PERU SMART SAC (S/1871, código 4501885).
FILAS_CATALOGO_EXCLUIDAS = {
    ("GRUPO MERPES PERU S.A.C.", "LAVADORA LG WT16OBVTB 16KG NEGRO"),
}


def _producto_a_dict(p: Producto) -> dict:
    """Reconstruye la fila con la MISMA forma que ya devolvía el CSV
    (mismas claves, incluidas las de cuotas como "12"/"24"/"36" a nivel
    top-level) — para que agent/tools.py no tenga que cambiar su lógica de
    negocio (scoring, formateo, familia de combos), solo la fuente de datos."""
    fila = {
        # Única clave que NO venía del CSV: el id real del registro. Se agrega
        # porque el cierre de venta necesita guardar QUÉ producto del catálogo
        # se vendió (LineaVenta.producto_id) y CODIGO HANA no sirve de clave
        # (no es único, ver Producto). Es aditiva: la lógica de negocio de
        # agent/tools.py lee las claves por nombre, no recorre el diccionario.
        "ID": p.id,
        "CANAL": p.canal or "",
        "PROVEEDOR": p.proveedor or "",
        "MARCA": p.marca or "",
        "TIPO": p.tipo or "",
        "SUB TIPO": p.sub_tipo or "",
        "CODIGO HANA": p.codigo_hana or "",
        "DESCRIPCIÓN": p.descripcion or "",
        "COMBO": p.combo or "",
        "INCLUYE CONEXIÓN": p.incluye_conexion or "",
        "COMENTARIOS": p.comentarios or "",
        "FEE PRV": p.fee_prv or "",
        "FEE CLDA": p.fee_clda or "",
        "PRECIO": p.precio or "",
    }
    fila.update(p.cuotas or {})
    return fila


async def listar_productos_activos(negocio_id: str) -> list[dict]:
    """Catálogo completo (solo filas activas) DE UN NEGOCIO para
    búsqueda/scoring en Python — ~360 filas es trivial de traer entero en
    cada consulta, igual que ya se hacía con el CSV cacheado en memoria de
    proceso (sin la desventaja de esa variable global: acá cada request ve
    el dato real).

    `negocio_id` (Gate 4.4) es obligatorio y se filtra en el WHERE, mismo
    criterio que `listar_leads` — ninguna llamada a esta función puede
    devolver productos de un Negocio distinto al pedido."""
    async with async_session() as session:
        query = (
            select(Producto)
            .where(Producto.negocio_id == negocio_id, Producto.activo.is_(True))
            .order_by(Producto.id.asc())
        )
        result = await session.execute(query)
        return [_producto_a_dict(p) for p in result.scalars().all()]


async def obtener_producto_por_codigo_hana(codigo: str, negocio_id: str) -> dict | None:
    """Primer producto activo DE ESTE NEGOCIO con este CODIGO HANA, ordenado
    por id (mismo criterio de "primera fila que matchea" que ya usaba el
    CSV — CODIGO HANA no es único, ver Producto). `negocio_id` obligatorio,
    filtrado en el WHERE (Gate 4.4)."""
    async with async_session() as session:
        query = (
            select(Producto)
            .where(Producto.codigo_hana == codigo, Producto.negocio_id == negocio_id, Producto.activo.is_(True))
            .order_by(Producto.id.asc())
            .limit(1)
        )
        result = await session.execute(query)
        p = result.scalar_one_or_none()
        return _producto_a_dict(p) if p else None


def _producto_a_dict_panel(p: Producto) -> dict:
    """Forma del producto para el PANEL / la API JSON — distinta a propósito de
    _producto_a_dict(), que reconstruye la fila con las claves del CSV
    ("CODIGO HANA", "DESCRIPCIÓN"...) para no tocar la lógica de negocio de
    agent/tools.py. Acá se exponen los nombres reales de los campos más los
    metadatos del registro (id, activo, version) que la UI administrativa sí
    necesita. Las fechas van en ISO porque el consumidor es JSON
    (JSONResponse no sabe serializar datetime), y con sufijo `Z` porque son
    instantes reales guardados en UTC — mismo criterio y misma función que ya
    usaban los DTO de Lead/Pipeline (ver iso_utc)."""
    return {
        "id": p.id,
        "canal": p.canal,
        "proveedor": p.proveedor,
        "marca": p.marca,
        "tipo": p.tipo,
        "sub_tipo": p.sub_tipo,
        "codigo_hana": p.codigo_hana,
        "descripcion": p.descripcion,
        "combo": p.combo,
        "incluye_conexion": p.incluye_conexion,
        "comentarios": p.comentarios,
        "fee_prv": p.fee_prv,
        "fee_clda": p.fee_clda,
        "precio": p.precio,
        "cuotas": p.cuotas or {},
        "activo": p.activo,
        "version": p.version,
        "creado": iso_utc(p.creado),
        "actualizado": iso_utc(p.actualizado),
    }


def _normalizar_texto_producto(valor) -> str | None:
    """Vacío y None son el mismo dato para un campo de catálogo — unificarlos
    evita auditar cambios falsos ("" -> None) en cada importación."""
    if valor is None:
        return None
    texto = str(valor).strip()
    return texto or None


def _valor_auditoria(valor) -> str | None:
    """Normaliza a texto el valor que va a la bitácora, SIN recortarlo: las
    columnas valor_anterior/valor_nuevo son Text desde la migración
    9b2c4d7e1a35, así que una descripción de 300 caracteres se guarda entera.
    Sigue existiendo como función (y no como str() suelto en cada punto de
    escritura) para que None no se convierta en la cadena "None" y para tener
    un solo lugar donde cambiar el formato del dato auditado."""
    if valor is None:
        return None
    return str(valor)


def _es_codigo_en_creacion(codigo: str | None) -> bool:
    """True si el CODIGO HANA es el placeholder de "producto todavía sin
    código asignado" en vez de un código real. Se acepta con y sin tilde
    porque el dato lo escribe una persona en un Excel."""
    if not codigo:
        return True
    return codigo.strip().upper().replace("Ó", "O").startswith("EN CREACION")


def _fila_csv_a_datos(fila: dict) -> dict:
    """Normaliza una fila cruda del CSV a los campos del modelo Producto."""
    return {
        "canal": _normalizar_texto_producto(fila.get("CANAL")),
        "proveedor": _normalizar_texto_producto(fila.get("PROVEEDOR")),
        "marca": _normalizar_texto_producto(fila.get("MARCA")),
        "tipo": _normalizar_texto_producto(fila.get("TIPO")),
        "sub_tipo": _normalizar_texto_producto(fila.get("SUB TIPO")),
        "codigo_hana": _normalizar_texto_producto(fila.get("CODIGO HANA")),
        "descripcion": _normalizar_texto_producto(fila.get("DESCRIPCIÓN")),
        "combo": _normalizar_texto_producto(fila.get("COMBO")),
        "incluye_conexion": _normalizar_texto_producto(fila.get("INCLUYE CONEXIÓN")),
        "comentarios": _normalizar_texto_producto(fila.get("COMENTARIOS")),
        "fee_prv": _normalizar_texto_producto(fila.get("FEE PRV")),
        "fee_clda": _normalizar_texto_producto(fila.get("FEE CLDA")),
        "precio": _normalizar_texto_producto(fila.get("PRECIO")),
        "cuotas": {
            plazo: fila[plazo].strip()
            for plazo in PLAZOS_CUOTAS_CATALOGO
            if (fila.get(plazo) or "").strip()
        },
    }


def _clave_igualdad_producto(datos: dict) -> tuple:
    """Huella de TODOS los campos de negocio (incluidas las cuotas) de un
    producto. Dos filas con la misma huella son literalmente indistinguibles
    en los datos: no hay ninguna forma de decidir cuál es cuál."""
    cuotas = datos.get("cuotas") or {}
    return (
        tuple(_normalizar_texto_producto(datos.get(campo)) for campo in CAMPOS_NEGOCIO_PRODUCTO),
        tuple((plazo, _normalizar_texto_producto(cuotas.get(plazo))) for plazo in PLAZOS_CUOTAS_CATALOGO),
    )


def _producto_a_datos(p: Producto) -> dict:
    """El producto de la BD con la misma forma que devuelve _fila_csv_a_datos,
    para poder compararlos campo por campo."""
    datos = {campo: getattr(p, campo) for campo in CAMPOS_NEGOCIO_PRODUCTO}
    datos["cuotas"] = p.cuotas or {}
    return datos


def _emparejar_por_igualdad_exacta(filas_bd: list, filas_csv: list) -> tuple[list, list, list]:
    """Empareja dos conjuntos de filas que NO tienen identificador confiable,
    usando la igualdad exacta de todos sus campos de negocio como única
    evidencia de que son "la misma fila".

    LIMITACIÓN CONOCIDA Y DELIBERADA (no es un bug): cuando varias filas son
    idénticas entre sí, la comparación es por CANTIDAD (multiset), no
    fila-por-fila — se empareja "3 filas idénticas de un lado con 3 del otro"
    sin decidir cuál instancia concreta corresponde a cuál, porque en los
    datos son intercambiables y esa decisión sería inventada. La consecuencia
    práctica: si una fila sin código cambia CUALQUIER campo (por ejemplo, le
    suben el precio), la vieja y la nueva ya no son iguales, así que esto NO
    lo registra como una modificación — lo registra como una baja + un alta.
    Es a propósito: preferimos un alta/baja honesta antes que una auditoría de
    "cambio de precio" atribuida a un producto que quizá no es ese (regla:
    nunca registrar una auditoría que no pueda atribuirse con certeza).

    Devuelve (emparejadas, solo_csv, solo_bd):
      - emparejadas: [(Producto, datos_csv)] con igualdad total de negocio
      - solo_csv:    [datos_csv] sin correspondencia -> se crean
      - solo_bd:     [Producto] sin correspondencia  -> se desactivan
    """
    # Entre filas INDISTINGUIBLES, cuál se empareja y cuál sobra es una
    # elección arbitraria en los datos — pero no en sus consecuencias: la que
    # sobra se DESACTIVA. Por eso se emparejan primero las activas y se deja
    # sobrar a las que ya estaban dadas de baja. Si en la BD hay 1 inactiva +
    # 2 activas idénticas y el CSV trae 2 filas, el catálogo debe quedar con 2
    # vigentes (lo que dice el CSV): emparejar la inactiva y dar de baja una
    # activa dejaría 1 sola vigente y escribiría una auditoría de baja que no
    # corresponde a ningún hecho nuevo de la fuente comercial. sorted() es
    # estable, así que dentro de cada grupo se conserva el orden original.
    pendientes: dict[tuple, list] = {}
    for p in sorted(filas_bd, key=lambda p: not p.activo):
        pendientes.setdefault(_clave_igualdad_producto(_producto_a_datos(p)), []).append(p)

    emparejadas: list = []
    solo_csv: list = []
    for datos in filas_csv:
        cola = pendientes.get(_clave_igualdad_producto(datos))
        if cola:
            emparejadas.append((cola.pop(0), datos))
        else:
            solo_csv.append(datos)

    solo_bd = [p for cola in pendientes.values() for p in cola]
    return emparejadas, solo_csv, solo_bd


def _diferencias_producto(p: Producto, datos: dict) -> list[tuple[str, str | None, str | None]]:
    """Campos que REALMENTE cambian entre el producto guardado y los datos
    nuevos. Devuelve [(campo, valor_anterior, valor_nuevo)] — las cuotas se
    reportan una por plazo ("cuota_12"), no como un JSON entero, para que la
    bitácora diga exactamente qué plazo se movió."""
    cambios: list[tuple[str, str | None, str | None]] = []
    for campo in CAMPOS_NEGOCIO_PRODUCTO:
        if campo not in datos:
            continue
        anterior = _normalizar_texto_producto(getattr(p, campo))
        nuevo = _normalizar_texto_producto(datos.get(campo))
        if anterior != nuevo:
            cambios.append((campo, anterior, nuevo))
    if "cuotas" in datos:
        cuotas_anteriores = p.cuotas or {}
        cuotas_nuevas = datos.get("cuotas") or {}
        for plazo in PLAZOS_CUOTAS_CATALOGO:
            anterior = _normalizar_texto_producto(cuotas_anteriores.get(plazo))
            nuevo = _normalizar_texto_producto(cuotas_nuevas.get(plazo))
            if anterior != nuevo:
                cambios.append((f"cuota_{plazo}", anterior, nuevo))
    return cambios


def _aplicar_datos_producto(p: Producto, datos: dict):
    """Escribe los campos de negocio (y cuotas) sobre el producto."""
    for campo in CAMPOS_NEGOCIO_PRODUCTO:
        if campo in datos:
            setattr(p, campo, _normalizar_texto_producto(datos.get(campo)))
    if "cuotas" in datos:
        p.cuotas = datos.get("cuotas") or {}


def _columnas_a_escribir(datos: dict) -> dict:
    """Los mismos campos que escribiría _aplicar_datos_producto(), pero como
    diccionario de columnas para un UPDATE de Core — solo las claves realmente
    presentes en `datos`, para que una edición parcial no borre lo que el
    formulario no envió."""
    valores = {
        campo: _normalizar_texto_producto(datos.get(campo))
        for campo in CAMPOS_NEGOCIO_PRODUCTO
        if campo in datos
    }
    if "cuotas" in datos:
        valores["cuotas"] = datos.get("cuotas") or {}
    return valores


def _auditar(session, producto_id: int, campo: str, anterior, nuevo, autor: str | None):
    """Agrega una fila de bitácora a la sesión EN CURSO (no hace commit) —
    a diferencia de registrar_cambio_precio_producto(), que abre su propia
    sesión. La importación necesita esta variante para que el catálogo y su
    auditoría se guarden en una sola transacción: si la importación falla a
    mitad de camino no queda una bitácora de cambios que nunca se aplicaron."""
    session.add(HistorialPrecioProducto(
        producto_id=producto_id, campo=campo,
        valor_anterior=_valor_auditoria(anterior), valor_nuevo=_valor_auditoria(nuevo),
        autor=autor,
    ))


def _activo_segun_csv(datos: dict) -> bool:
    """Un producto que viene en el CSV está vigente, salvo que esté en la
    lista de duplicados reales confirmados (FILAS_CATALOGO_EXCLUIDAS).

    Solo se usa al CREAR un producto nuevo. Sobre un producto que ya existe la
    importación no vuelve a decidir su `activo` (ver regla 4 de
    importar_catalogo_desde_csv): si un admin lo desactivó a mano, sigue
    desactivado por más que el CSV lo siga trayendo."""
    clave = (datos.get("proveedor") or "", datos.get("descripcion") or "")
    return clave not in FILAS_CATALOGO_EXCLUIDAS


async def importar_catalogo_desde_csv(ruta_csv: str, negocio_id: str, autor: str | None = None) -> dict:
    """Sincroniza el catálogo con un CSV del mismo formato de
    knowledge/lista_precios_canales_propios.csv, por DIFERENCIAS.

    Reemplaza a la estrategia anterior (borrar todo y reinsertar), que dejó de
    ser válida al existir edición manual desde el panel: un DELETE total
    destruye los ids de los productos y con eso la trazabilidad de
    HistorialPrecioProducto, que apunta a producto_id.

    Reglas de identidad, en orden:

    1. CODIGO HANA real -> es el identificador. Fila nueva se crea; fila
       existente que cambió se actualiza y se audita CAMPO POR CAMPO; fila
       idéntica no se toca ni se audita; fila que estaba en la BD y ya no
       viene en el CSV se DESACTIVA (nunca se borra físicamente).

    2. CODIGO HANA "EN CREACIÓN" -> ese texto es un placeholder, no una
       identidad, y tampoco se usa una clave compuesta como identidad
       oficial: se empareja solo por igualdad EXACTA de todos los campos de
       negocio, y lo que no empareja de forma inequívoca se resuelve como
       alta (fila nueva) + baja (fila vieja desactivada). Ver la limitación
       documentada en _emparejar_por_igualdad_exacta().

    3. Un CODIGO HANA real que aparezca REPETIDO (en la BD o en el CSV) cae
       también en el camino (2), porque deja de identificar una sola fila.
       Hoy no ocurre — los 342 códigos reales del CSV vigente son únicos —
       pero si ocurriera, es preferible degradar a alta/baja antes que
       atribuir un cambio de precio a la fila equivocada.

    4. `activo` NO se reconcilia contra el CSV en las filas que ya existen: un
       producto que ya estaba en la BD y sigue viniendo en el CSV conserva su
       `activo` tal cual, sin importar qué traiga el CSV. Activar o desactivar
       es una decisión humana explícita (el toggle del panel, auditado por su
       propia ruta) y una reimportación masiva no puede revertirla en silencio.
       La importación solo toca `activo` por dos caminos:
         - ALTA: un producto NUEVO nace con el `activo` que dicta el CSV
           (activo, salvo que esté en FILAS_CATALOGO_EXCLUIDAS);
         - BAJA: un producto existente que DESAPARECE por completo del CSV pasa
           a `activo=false` — dejó de existir en la fuente comercial, que es un
           hecho del catálogo y no una preferencia de un admin.
       Los demás campos (precio, cuotas, descripción, fees...) sí se
       sobrescriben desde el CSV, y la bitácora deja constancia de cada campo
       pisado.

    `version` avanza SOLO en las filas que esta importación cambió de verdad
    (ver Producto.version): así un formulario abierto sobre un producto que la
    importación acaba de pisar responde 409 en vez de sobrescribir el dato
    nuevo en silencio, y los formularios sobre productos intactos siguen
    siendo válidos.

    Devuelve {procesados, nuevos, modificados, sin_cambios, desactivados,
    en_creacion_ambiguas}, donde en_creacion_ambiguas cuenta las filas sin
    código (de ambos lados) que NO tuvieron correspondencia exacta y por eso
    se resolvieron por el camino conservador de alta/baja — es el número que
    una persona debería revisar a mano después de importar.

    `negocio_id` (Gate 4.4) es obligatorio: la sincronización por
    diferencias corre SOLO contra el catálogo de ESTE Negocio (no ve, no
    modifica ni desactiva productos de otro Negocio), y cada producto nuevo
    nace con este `negocio_id`.
    """
    with open(ruta_csv, "r", encoding="utf-8-sig") as f:
        filas_csv = [_fila_csv_a_datos(fila) for fila in csv.DictReader(f)]

    resumen = {
        "procesados": len(filas_csv), "nuevos": 0, "modificados": 0,
        "sin_cambios": 0, "desactivados": 0, "en_creacion_ambiguas": 0,
    }

    async with async_session() as session:
        result = await session.execute(select(Producto).where(Producto.negocio_id == negocio_id))
        productos_bd = list(result.scalars().all())

        # Partición por identidad: código real de un lado, placeholder del otro.
        por_codigo_bd: dict[str, list] = {}
        sin_codigo_bd: list = []
        for p in productos_bd:
            if _es_codigo_en_creacion(p.codigo_hana):
                sin_codigo_bd.append(p)
            else:
                por_codigo_bd.setdefault(p.codigo_hana.strip().upper(), []).append(p)

        por_codigo_csv: dict[str, list] = {}
        sin_codigo_csv: list = []
        for datos in filas_csv:
            if _es_codigo_en_creacion(datos.get("codigo_hana")):
                sin_codigo_csv.append(datos)
            else:
                por_codigo_csv.setdefault(datos["codigo_hana"].strip().upper(), []).append(datos)

        emparejadas: list = []   # [(Producto, datos_csv)] — identidad cierta
        a_crear: list = []       # [datos_csv]
        a_desactivar: list = []  # [Producto]

        # (1) y (3) — códigos HANA reales
        for codigo in set(por_codigo_bd) | set(por_codigo_csv):
            lista_bd = por_codigo_bd.get(codigo, [])
            lista_csv = por_codigo_csv.get(codigo, [])
            if len(lista_bd) <= 1 and len(lista_csv) <= 1:
                if lista_bd and lista_csv:
                    emparejadas.append((lista_bd[0], lista_csv[0]))
                elif lista_csv:
                    a_crear.extend(lista_csv)
                else:
                    a_desactivar.extend(lista_bd)
                continue
            # Código repetido: ya no identifica una sola fila (regla 3).
            logger.warning(
                "Importación de catálogo: CODIGO HANA %s aparece %d vez(ces) en la BD "
                "y %d en el CSV — se resuelve por igualdad exacta, no por código.",
                codigo, len(lista_bd), len(lista_csv),
            )
            pares, nuevas, viejas = _emparejar_por_igualdad_exacta(lista_bd, lista_csv)
            emparejadas.extend(pares)
            a_crear.extend(nuevas)
            a_desactivar.extend(viejas)

        # (2) — filas "EN CREACIÓN"
        pares, nuevas, viejas = _emparejar_por_igualdad_exacta(sin_codigo_bd, sin_codigo_csv)
        emparejadas.extend(pares)
        a_crear.extend(nuevas)
        a_desactivar.extend(viejas)
        # Solo cuentan las filas que ESTA importación deja sin resolver: las que
        # ya estaban dadas de baja en importaciones anteriores no se vuelven a
        # reportar, o el número crecería para siempre y dejaría de ser accionable.
        resumen["en_creacion_ambiguas"] = len(nuevas) + len([p for p in viejas if p.activo])

        for p, datos in emparejadas:
            # `activo` NO se toca acá a propósito (regla 4): el producto ya
            # existe y sigue en el CSV, así que su vigencia la decide la
            # persona que lo activó/desactivó desde el panel, no la
            # reimportación. Se auditan y aplican solo los cambios de datos.
            cambios = _diferencias_producto(p, datos)
            if not cambios:
                resumen["sin_cambios"] += 1
                continue
            _aplicar_datos_producto(p, datos)
            p.version += 1
            for campo, anterior, nuevo in cambios:
                _auditar(session, p.id, campo, anterior, nuevo, autor)
            resumen["modificados"] += 1

        for datos in a_crear:
            producto = Producto(
                negocio_id=negocio_id,
                **{campo: _normalizar_texto_producto(datos.get(campo)) for campo in CAMPOS_NEGOCIO_PRODUCTO},
                cuotas=datos.get("cuotas") or {},
                activo=_activo_segun_csv(datos),
            )
            session.add(producto)
            # flush para tener el id real: la auditoría nunca se escribe sin
            # poder atribuirse a un producto concreto.
            await session.flush()
            _auditar(session, producto.id, CAMPO_AUDITORIA_CREADO, None, producto.descripcion, autor)
            resumen["nuevos"] += 1

        for p in a_desactivar:
            if not p.activo:
                continue  # ya estaba dado de baja: no hay cambio que auditar
            p.activo = False
            p.version += 1
            _auditar(session, p.id, CAMPO_AUDITORIA_ACTIVO, "true", "false", autor)
            resumen["desactivados"] += 1

        await session.commit()

    return resumen


async def listar_productos(filtros: dict, pagina: int, por_pagina: int, negocio_id: str) -> tuple[list[dict], int]:
    """Página de productos DE UN NEGOCIO + total de coincidencias (para la
    paginación de la pantalla de catálogo). Filtros soportados: `q` (texto
    libre sobre marca y descripción), `canal`, `marca`, `tipo` (coincidencia
    exacta) y `activo` (bool; si no viene, devuelve activos e inactivos).

    `negocio_id` (Gate 4.4) es obligatorio y se filtra en el WHERE."""
    filtros = filtros or {}
    condiciones = [Producto.negocio_id == negocio_id]

    texto = (filtros.get("q") or "").strip()
    if texto:
        patron = f"%{texto}%"
        condiciones.append(Producto.marca.ilike(patron) | Producto.descripcion.ilike(patron))
    for campo in ("canal", "marca", "tipo"):
        valor = (filtros.get(campo) or "").strip()
        if valor:
            condiciones.append(getattr(Producto, campo) == valor)
    if filtros.get("activo") is not None:
        condiciones.append(Producto.activo.is_(bool(filtros["activo"])))

    pagina = max(1, int(pagina or 1))
    por_pagina = max(1, int(por_pagina or 20))

    async with async_session() as session:
        total = await session.scalar(select(func.count()).select_from(Producto).where(*condiciones))
        query = (
            select(Producto).where(*condiciones)
            .order_by(Producto.id.asc())
            .offset((pagina - 1) * por_pagina).limit(por_pagina)
        )
        result = await session.execute(query)
        return [_producto_a_dict_panel(p) for p in result.scalars().all()], int(total or 0)


async def obtener_producto(id: int, negocio_id: str) -> dict | None:
    """Candado de ownership por PK (Gate 4.4) — mismo criterio que
    `obtener_lead`: trae la fila por id y, si pertenece a otro Negocio,
    devuelve None (404, nunca 403 — no confirma la existencia del recurso a
    quien no tiene acceso)."""
    async with async_session() as session:
        p = await session.get(Producto, id)
        if p is None or p.negocio_id != negocio_id:
            return None
        return _producto_a_dict_panel(p)


async def crear_producto(datos: dict, autor: str, negocio_id: str) -> dict:
    """Alta manual desde el panel. Arranca en version=0 (igual que los leads)
    y deja constancia de la creación en la bitácora. `negocio_id` (Gate 4.4)
    obligatorio — el producto nace ligado al Negocio de quien lo crea."""
    async with async_session() as session:
        producto = Producto(
            negocio_id=negocio_id,
            **{campo: _normalizar_texto_producto(datos.get(campo)) for campo in CAMPOS_NEGOCIO_PRODUCTO},
            cuotas=datos.get("cuotas") or {},
            activo=bool(datos.get("activo", True)),
            version=0,
        )
        session.add(producto)
        await session.flush()
        _auditar(session, producto.id, CAMPO_AUDITORIA_CREADO, None, producto.descripcion, autor)
        await session.commit()
        return _producto_a_dict_panel(producto)


async def editar_producto(id: int, cambios: dict, version_esperada: int, autor: str, negocio_id: str) -> dict | None:
    """Edición manual con concurrencia optimista — MISMO criterio que
    intentar_avanzar_version() para leads: solo se aplica si el producto sigue
    en la versión que tenía cuando se abrió el formulario; si alguien más
    escribió antes, no se aplica NADA y se devuelve None para que quien llama
    muestre el conflicto (Human Decision Gate) en vez de sobrescribir en
    silencio. La diferencia con los leads es solo mecánica: acá el chequeo y
    la escritura viven en la misma sesión/transacción, porque hay campos que
    escribir en el mismo acto.

    `negocio_id` (Gate 4.4): candado de ownership, mismo criterio que
    obtener_producto — un producto de otro Negocio se trata igual que un
    producto inexistente (None), tanto en la lectura previa como en el
    WHERE del propio UPDATE (defensa en profundidad: aunque alguien
    llamara a esta función saltándose el chequeo de arriba, el UPDATE
    tampoco tocaría una fila de otro Negocio).

    Devuelve el producto actualizado, o None si la versión no coincide, si
    el producto no existe, o si pertenece a otro Negocio (quien llama
    distingue los casos consultando obtener_producto()).

    El chequeo de versión NO alcanza con comparar en Python y después
    escribir: entre esa comparación y el COMMIT hay una ventana en la que
    otra solicitud puede leer la misma versión, y las dos se dan por
    ganadoras (comprobado con dos ediciones simultáneas reales: ambas
    respondían 200 y el segundo commit pisaba al primero sin dejar 409 ni
    bitácora del conflicto — exactamente la sobrescritura silenciosa que este
    mecanismo existe para impedir). La condición de versión viaja por eso
    dentro del propio UPDATE (`WHERE id = ... AND version = ...`), que la base
    evalúa de forma atómica: si otra escritura ganó, el UPDATE afecta 0 filas
    y esto devuelve None igual que un conflicto normal.
    """
    async with async_session() as session:
        producto = await session.get(Producto, id)
        if producto is None or producto.negocio_id != negocio_id or producto.version != version_esperada:
            return None
        cambios_reales = _diferencias_producto(producto, cambios)
        if not cambios_reales:
            # Guardar sin cambiar nada no es un conflicto ni un error: no se
            # avanza la versión ni se ensucia la bitácora.
            return _producto_a_dict_panel(producto)
        valores = _columnas_a_escribir(cambios)

    # Sesión nueva para que el UPDATE sea la primera sentencia de su
    # transacción — así la condición de versión se evalúa contra el estado
    # comprometido en ese instante, no contra la lectura de arriba.
    async with async_session() as session:
        resultado = await session.execute(
            update(Producto)
            .where(Producto.id == id, Producto.negocio_id == negocio_id, Producto.version == version_esperada)
            .values(**valores, version=version_esperada + 1)
        )
        if resultado.rowcount == 0:
            await session.rollback()
            return None
        await session.commit()

    for campo, anterior, nuevo in cambios_reales:
        await registrar_cambio_precio_producto(id, campo, anterior, nuevo, autor)
    return await obtener_producto(id, negocio_id)


async def toggle_producto(id: int, version_esperada: int, autor: str, negocio_id: str) -> dict | None:
    """Activa/desactiva un producto — nunca se borra físicamente. Mismo manejo
    de concurrencia que editar_producto(), incluida la condición de versión
    dentro del UPDATE (dos toggles simultáneos con la misma versión daban 200
    los dos y dejaban una sola bitácora, ver editar_producto). `negocio_id`
    (Gate 4.4): mismo candado de ownership que editar_producto."""
    async with async_session() as session:
        producto = await session.get(Producto, id)
        if producto is None or producto.negocio_id != negocio_id or producto.version != version_esperada:
            return None
        anterior = producto.activo

    async with async_session() as session:
        resultado = await session.execute(
            update(Producto)
            .where(Producto.id == id, Producto.negocio_id == negocio_id, Producto.version == version_esperada)
            .values(activo=not anterior, version=version_esperada + 1)
        )
        if resultado.rowcount == 0:
            await session.rollback()
            return None
        await session.commit()

    await registrar_cambio_precio_producto(
        id, CAMPO_AUDITORIA_ACTIVO, str(anterior).lower(), str(not anterior).lower(), autor,
    )
    return await obtener_producto(id, negocio_id)


async def listar_historial_producto(producto_id: int) -> list[dict]:
    """Bitácora de un producto, del cambio más reciente al más antiguo — mismo
    criterio de orden que listar_eventos_lead()."""
    async with async_session() as session:
        query = (
            select(HistorialPrecioProducto)
            .where(HistorialPrecioProducto.producto_id == producto_id)
            .order_by(HistorialPrecioProducto.creado.desc(), HistorialPrecioProducto.id.desc())
        )
        result = await session.execute(query)
        return [
            {
                "id": h.id, "campo": h.campo,
                "valor_anterior": h.valor_anterior, "valor_nuevo": h.valor_nuevo,
                "autor": h.autor, "creado": iso_utc(h.creado),
            }
            for h in result.scalars().all()
        ]


async def registrar_cambio_precio_producto(producto_id: int, campo: str, valor_anterior: str | None, valor_nuevo: str | None, autor: str | None):
    """Auditoría append-only de un cambio de precio/campo de un producto. Abre
    su propia sesión (la variante interna que escribe dentro de una
    transacción en curso es _auditar())."""
    async with async_session() as session:
        session.add(HistorialPrecioProducto(
            producto_id=producto_id, campo=campo,
            valor_anterior=_valor_auditoria(valor_anterior), valor_nuevo=_valor_auditoria(valor_nuevo),
            autor=autor,
        ))
        await session.commit()
