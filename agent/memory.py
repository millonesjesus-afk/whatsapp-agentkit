# agent/memory.py — Memoria de conversaciones con SQLite
# Generado por AgentKit

"""
Sistema de memoria del agente. Guarda el historial de conversaciones
por número de teléfono usando SQLite (local) o PostgreSQL (producción).
"""

import os
import csv
import logging
from datetime import datetime
from cryptography.fernet import Fernet
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, aliased
from sqlalchemy import String, Text, DateTime, select, Integer, Boolean, func, case, delete, update, JSON
from sqlalchemy.exc import IntegrityError
from dotenv import load_dotenv

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

engine = create_async_engine(DATABASE_URL, echo=False)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

# Resultados que cierran un lead (ya no se le hace seguimiento) — se usa acá
# (no solo en dashboard.py) porque main.py también necesita saber cuándo un
# lead está cerrado, para decidir si Gabi retoma la conversación cuando el
# cliente vuelve a escribir. Vive en memory.py, la capa que ambos importan,
# para no duplicar la lista ni arriesgar que se desincronicen.
RESULTADOS_CERRADOS = (
    "vendido", "no_interesado", "no_califica", "no_es_cliente_calidda", "otro", "consulta_atc",
    "servicio_postventa", "cartera_fnb",
)


class Base(DeclarativeBase):
    pass


class Mensaje(Base):
    """Modelo de mensaje en la base de datos."""
    __tablename__ = "mensajes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    telefono: Mapped[str] = mapped_column(String(50), index=True)
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


class ArchivoAdjunto(Base):
    """Archivo subido por un asesor para enviar por WhatsApp — proforma
    puntual (reutilizable=False, ligada a un solo envío) o catálogo de la
    librería reutilizable (reutilizable=True, se puede mandar en cualquier
    conversación sin volver a subirlo). El contenido vive en el volumen
    persistente de Railway (ver ARCHIVOS_DIR en dashboard.py) — acá solo se
    guardan los metadatos y la ruta en disco."""
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
    creado: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Lead(Base):
    """Datos estructurados del cliente (nombre, interés, paso del flujo),
    independientes del historial crudo de mensajes. Así, aunque el historial
    se trunque o se pierda contexto entre turnos, estos datos clave persisten."""
    __tablename__ = "leads"

    telefono: Mapped[str] = mapped_column(String(50), primary_key=True)
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


class EventoLead(Base):
    """Conversation Timeline (MAIEK_AI_PRODUCT_PATTERNS.md, Cap. 6) — eventos
    de NEGOCIO sobre un lead (resultado cambiado, asignado, venta registrada),
    distintos de los mensajes de chat crudos. Append-only: nunca se actualiza
    ni se borra una fila existente. `payload` guarda valores estructurados
    (campo/anterior/nuevo, líneas de venta, etc.) — no solo el texto de
    `descripcion` — para que el evento sea una fuente de datos reutilizable
    por auditoría, analítica y el Copiloto IA más adelante, no únicamente
    una lista para mostrar en pantalla. `autor` guarda el nombre de quien
    hizo el cambio TAL COMO ERA en ese momento (no una referencia viva a
    Usuario) — práctica estándar de bitácora: el registro histórico no debe
    cambiar si alguien edita su nombre después. None si el cambio fue
    automático (Gabi)."""
    __tablename__ = "eventos_lead"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    telefono: Mapped[str] = mapped_column(String(50), index=True)
    tipo: Mapped[str] = mapped_column(String(30))  # resultado_cambiado | asignado | venta_registrada
    descripcion: Mapped[str] = mapped_column(String(300))
    payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    autor: Mapped[str | None] = mapped_column(String(100), nullable=True)
    creado: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)


async def registrar_evento_lead(telefono: str, tipo: str, descripcion: str, autor: str | None, payload: dict | None = None):
    async with async_session() as session:
        session.add(EventoLead(telefono=telefono, tipo=tipo, descripcion=descripcion, autor=autor, payload=payload))
        await session.commit()


async def listar_eventos_lead(telefono: str, limite: int | None = None) -> list[dict]:
    """Del más reciente al más antiguo — para el Conversation Timeline y,
    tomando solo el primero, para el aviso de conflicto de edición (quién,
    cuándo, qué cambió)."""
    async with async_session() as session:
        query = select(EventoLead).where(EventoLead.telefono == telefono).order_by(EventoLead.creado.desc())
        if limite:
            query = query.limit(limite)
        result = await session.execute(query)
        return [
            {
                "tipo": e.tipo, "descripcion": e.descripcion, "payload": e.payload,
                "autor": e.autor, "creado": e.creado,
            }
            for e in result.scalars().all()
        ]


async def intentar_avanzar_version(telefono: str, version_esperada: int) -> bool:
    """Concurrencia optimista (MAIEK_AI_PRODUCT_PATTERNS.md, Cap. 6 —
    conflicto de edición): avanza la versión del lead en +1 SOLO si sigue en
    la versión esperada (la que tenía cuando el usuario abrió el formulario).
    True si se pudo (nadie más escribió antes) — en ese caso, quien llama
    debe aplicar su cambio a continuación. False si alguien más ya avanzó la
    versión — no se aplica nada, y quien llama debe mostrar el conflicto
    explícitamente en vez de sobrescribir en silencio (Human Decision Gate)."""
    async with async_session() as session:
        lead = await session.get(Lead, telefono)
        if lead is None or lead.version != version_esperada:
            return False
        lead.version += 1
        await session.commit()
        return True


class LineaVenta(Base):
    """Un producto o servicio dentro del cierre de venta de un lead — un
    cliente puede comprar un artefacto, varios, un servicio, o un mix de
    ambos, así que la venta de un lead es una LISTA de líneas en vez de un
    solo producto. La forma de pago (modalidad_pago/cuotas/medio_pago)
    sigue siendo una sola para toda la venta y vive en Lead, no acá."""
    __tablename__ = "lineas_venta"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    telefono: Mapped[str] = mapped_column(String(50), index=True)
    producto: Mapped[str] = mapped_column(String(300))
    precio: Mapped[str | None] = mapped_column(String(30), nullable=True)
    marca: Mapped[str | None] = mapped_column(String(100), nullable=True)
    proveedor: Mapped[str | None] = mapped_column(String(150), nullable=True)
    creado: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


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


class Usuario(Base):
    """Cuenta de acceso al panel interno (/dashboard). Roles: admin, supervisor, asesor."""
    __tablename__ = "usuarios"

    username: Mapped[str] = mapped_column(String(50), primary_key=True)
    password_hash: Mapped[str] = mapped_column(String(200))
    nombre: Mapped[str] = mapped_column(String(100))
    rol: Mapped[str] = mapped_column(String(20))  # admin | supervisor | asesor
    # Solo aplica a asesores: nivel de experiencia (para la asignación
    # automática) y si está disponible para recibir leads nuevos ahora mismo.
    nivel: Mapped[str | None] = mapped_column(String(20), nullable=True)  # junior | intermedio | senior
    disponible: Mapped[bool] = mapped_column(Boolean, default=True)


class Configuracion(Base):
    """Ajustes simples del panel (clave/valor) editables sin tocar código —
    hoy solo los umbrales de monto para la asignación automática por nivel,
    pero sirve para cualquier otro ajuste puntual que se agregue después."""
    __tablename__ = "configuracion"

    clave: Mapped[str] = mapped_column(String(50), primary_key=True)
    valor: Mapped[str] = mapped_column(String(200))


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
    todavía, así que ese campo no es único (confirmado en el CSV vigente)."""
    __tablename__ = "productos"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
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


async def obtener_configuracion(clave: str, valor_default: str) -> str:
    """Lee un valor de configuración, o el default si nunca se guardó."""
    async with async_session() as session:
        config = await session.get(Configuracion, clave)
        return config.valor if config else valor_default


async def guardar_configuracion(clave: str, valor: str):
    async with async_session() as session:
        config = await session.get(Configuracion, clave)
        if config is None:
            config = Configuracion(clave=clave)
            session.add(config)
        config.valor = valor
        await session.commit()


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
    }


async def crear_canal_whatsapp(
    nombre: str, phone_number_id: str, access_token: str = "",
    app_secret: str = "", page_access_token: str = "", modo: str = "produccion",
    waba_id: str = "",
) -> dict:
    """Agrega un número de WhatsApp nuevo administrable desde el panel."""
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
        )
        session.add(canal)
        await session.commit()
        await session.refresh(canal)
        return _canal_a_dict(canal)


async def listar_canales_whatsapp(solo_activos: bool = False) -> list[dict]:
    """Recupera los canales de WhatsApp configurados, con sus credenciales
    descifradas — usado tanto por ProveedorMeta (para enviar/verificar) como
    por la pantalla de administración del panel."""
    async with async_session() as session:
        query = select(CanalWhatsApp).order_by(CanalWhatsApp.creado.asc())
        if solo_activos:
            query = query.where(CanalWhatsApp.activo.is_(True))
        result = await session.execute(query)
        return [_canal_a_dict(c) for c in result.scalars().all()]


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


async def sembrar_canales_desde_env():
    """Si la tabla de canales está vacía, la siembra a partir de las
    variables de entorno META_CANAL_N_* (o las sueltas META_ACCESS_TOKEN/
    META_PHONE_NUMBER_ID/META_APP_SECRET como canal único) — así una
    instalación que ya venía configurada por variable de entorno sigue
    funcionando igual tras este cambio, sin perder su configuración ni
    necesitar que alguien la vuelva a escribir a mano en el panel."""
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

    for datos in canales_env:
        await crear_canal_whatsapp(**datos)
    if canales_env:
        logger.info(f"Sembrados {len(canales_env)} canal(es) de WhatsApp desde variables de entorno")


async def inicializar_db():
    """Aplica las migraciones de Alembic hasta la última versión — Data
    Architecture Fase 1: create_all() deja de usarse como mecanismo de
    cambio de esquema en producción, ver agent/migraciones.py."""
    from agent.migraciones import aplicar_migraciones
    await aplicar_migraciones()


async def guardar_mensaje(telefono: str, role: str, content: str, archivo_id: int | None = None, via_app: bool = False):
    """Guarda un mensaje en el historial de conversación. archivo_id solo se
    usa cuando el mensaje fue un archivo adjunto enviado por un asesor.
    via_app=True cuando llegó por el echo de coexistencia (asesor respondió
    desde la app de WhatsApp Business en el celular, no desde el panel)."""
    async with async_session() as session:
        mensaje = Mensaje(
            telefono=telefono,
            role=role,
            content=content,
            timestamp=datetime.utcnow(),
            archivo_id=archivo_id,
            via_app=via_app,
        )
        session.add(mensaje)
        await session.commit()


async def obtener_historial(telefono: str, limite: int = 20) -> list[dict]:
    """
    Recupera los últimos N mensajes de una conversación.

    Args:
        telefono: Número de teléfono del cliente
        limite: Máximo de mensajes a recuperar (default: 20)

    Returns:
        Lista de diccionarios con role y content
    """
    async with async_session() as session:
        query = (
            select(Mensaje)
            .where(Mensaje.telefono == telefono)
            .order_by(Mensaje.timestamp.desc())
            .limit(limite)
        )
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

        return [
            {
                "role": msg.role, "content": msg.content, "archivo_id": msg.archivo_id,
                "archivo_tipo": content_types.get(msg.archivo_id), "via_app": msg.via_app,
            }
            for msg in mensajes
        ]


async def obtener_ultimos_mensajes(telefonos: list[str]) -> dict[str, dict]:
    """Último mensaje de cada teléfono (para la vista previa en la bandeja),
    en una sola consulta para toda la lista visible — no una por lead en un
    loop (mismo problema de N consultas que contar_leads_activos_por_asesor).

    Usa row_number() por teléfono en vez de traer todos los mensajes y
    quedarse con el primero en Python — un lead con una conversación larga
    (cientos de mensajes) habría traído toda esa historia solo para
    descartarla, lo cual es justo el mismo tipo de desperdicio que se
    intentaba evitar. row_number() funciona igual en SQLite y Postgres."""
    if not telefonos:
        return {}
    async with async_session() as session:
        fila = (
            func.row_number()
            .over(partition_by=Mensaje.telefono, order_by=Mensaje.timestamp.desc())
            .label("fila")
        )
        subconsulta = (
            select(Mensaje).where(Mensaje.telefono.in_(telefonos)).add_columns(fila).subquery()
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
        "nombre": lead.nombre,
        "interes": lead.interes,
        "producto_tipo": lead.producto_tipo,
        "producto_marca": lead.producto_marca,
        "producto_modalidad": lead.producto_modalidad,
        "paso_flujo": lead.paso_flujo,
        "resultado": lead.resultado,
        "fecha_agendada": lead.fecha_agendada,
        "asesor_asignado": lead.asesor_asignado,
        "pausado_manual": lead.pausado_manual,
        "producto_vendido": lead.producto_vendido,
        "precio_venta": lead.precio_venta,
        "marca_venta": lead.marca_venta,
        "proveedor_venta": lead.proveedor_venta,
        "modalidad_pago": lead.modalidad_pago,
        "cuotas": lead.cuotas,
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


async def obtener_lead(telefono: str) -> dict | None:
    """Recupera los datos estructurados conocidos de un cliente, si existen."""
    async with async_session() as session:
        lead = await session.get(Lead, telefono)
        if lead is None:
            return None
        return _lead_a_dict(lead)


async def listar_leads(asesor_asignado: str | None = None) -> list[dict]:
    """Recupera los leads, del más recientemente actualizado al más antiguo.
    Si se pasa asesor_asignado, solo trae los leads asignados a ese asesor."""
    async with async_session() as session:
        query = select(Lead).order_by(Lead.actualizado.desc())
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


async def listar_leads_pipeline(
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
    lista cerrada de valores como `resultado`."""
    columna = COLUMNAS_ORDEN_PIPELINE.get(orden, Lead.actualizado)
    async with async_session() as session:
        query = select(Lead)
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
        return leads, total


async def listar_leads_agendados(asesor_asignado: str | None = None) -> list[dict]:
    """Leads con una cita agendada (resultado == 'agendado' y fecha_agendada
    definida), de la más próxima a la más lejana — para el aviso de "Próximas
    citas" dentro del panel. Si se pasa asesor_asignado, solo las de ese asesor."""
    async with async_session() as session:
        query = (
            select(Lead)
            .where(Lead.resultado == "agendado", Lead.fecha_agendada.is_not(None))
            .order_by(Lead.fecha_agendada.asc())
        )
        if asesor_asignado:
            query = query.where(Lead.asesor_asignado == asesor_asignado)
        result = await session.execute(query)
        return [_lead_a_dict(lead) for lead in result.scalars().all()]


async def listar_leads_esperando_asesor() -> list[dict]:
    """Leads derivados a un asesor que se quedaron sin nadie disponible en su
    momento (asesor_asignado sigue vacío), del más antiguo al más reciente —
    para poder asignarlos apenas un asesor se ponga disponible, en vez de
    quedar huérfanos para siempre.

    El filtro de resultado se hace en Python (no en el WHERE de SQL) porque
    la mayoría de estos leads tiene resultado NULL (pendiente) — un
    `NOT IN` en SQL excluiría también esas filas por cómo SQL trata NULL en
    comparaciones, que no es lo que queremos."""
    async with async_session() as session:
        query = (
            select(Lead)
            .where(Lead.paso_flujo == "derivado_asesor", Lead.asesor_asignado.is_(None))
            .order_by(Lead.actualizado.asc())
        )
        result = await session.execute(query)
        leads = result.scalars().all()
        return [_lead_a_dict(l) for l in leads if l.resultado not in RESULTADOS_CERRADOS]


async def actualizar_lead(telefono: str, campos_explicitos: tuple[str, ...] = (), **campos):
    """Actualiza (o crea) los datos estructurados del cliente. Por defecto solo
    sobreescribe los campos con un valor no vacío, para no perder datos ya
    conocidos — eso es lo correcto para las escrituras de Gabi, que manda lo que
    logró extraer de la conversación y nada más.

    `campos_explicitos` nombra los campos que vienen de una decisión HUMANA en
    el panel, donde "vacío" no significa "no sé", sino "bórralo" (Human Decision
    Gate: si una persona limpió el campo, el sistema no puede decidir por su
    cuenta conservar el valor viejo). Esos campos se escriben tal cual llegan,
    normalizando "" a NULL. Quien llama decide cuáles son: la misma función
    sirve para los dos casos sin que el llamador automático cambie."""
    campos = {
        k: (v if v not in ("",) else None) if k in campos_explicitos else v
        for k, v in campos.items()
        if v or k in campos_explicitos
    }
    if not campos:
        return
    async with async_session() as session:
        lead = await session.get(Lead, telefono)
        if lead is None:
            lead = Lead(telefono=telefono)
            session.add(lead)
        for campo, valor in campos.items():
            setattr(lead, campo, valor)
        lead.actualizado = datetime.utcnow()
        await session.commit()


async def listar_lineas_venta(telefono: str, con_metadatos: bool = False) -> list[dict]:
    """Líneas de venta de un lead (un artefacto, varios, o un mix con
    servicio), en el orden en que se agregaron.

    `con_metadatos` agrega `id` y `creado` — los pide el DTO JSON del detalle
    de Lead, y NO viajan por defecto a propósito: el panel legacy serializa
    esta misma lista con json.dumps() para precargar el carrito del cierre de
    venta, y un datetime crudo ahí revienta la serialización."""
    async with async_session() as session:
        query = select(LineaVenta).where(LineaVenta.telefono == telefono).order_by(LineaVenta.id.asc())
        result = await session.execute(query)
        return [
            {
                "producto": l.producto, "precio": l.precio, "marca": l.marca, "proveedor": l.proveedor,
                **({"id": l.id, "creado": l.creado} if con_metadatos else {}),
            }
            for l in result.scalars().all()
        ]


async def listar_lineas_venta_de_muchos(telefonos: list[str]) -> dict[str, list[dict]]:
    """Igual que listar_lineas_venta pero para varios leads a la vez en una
    sola consulta — para pintar la tabla de leads/exportar sin hacer un
    query por fila (N+1)."""
    if not telefonos:
        return {}
    async with async_session() as session:
        query = (
            select(LineaVenta)
            .where(LineaVenta.telefono.in_(telefonos))
            .order_by(LineaVenta.id.asc())
        )
        result = await session.execute(query)
        agrupado: dict[str, list[dict]] = {}
        for l in result.scalars().all():
            agrupado.setdefault(l.telefono, []).append(
                {"producto": l.producto, "precio": l.precio, "marca": l.marca, "proveedor": l.proveedor}
            )
        return agrupado


async def guardar_lineas_venta(telefono: str, lineas: list[dict]):
    """Reemplaza TODAS las líneas de venta de un lead por la lista dada —
    el carrito del formulario de Cierre de venta siempre manda el estado
    completo (lo que quedó tras agregar/quitar productos), no un delta."""
    async with async_session() as session:
        await session.execute(delete(LineaVenta).where(LineaVenta.telefono == telefono))
        for l in lineas:
            session.add(LineaVenta(
                telefono=telefono,
                producto=l["producto"],
                precio=l.get("precio") or None,
                marca=l.get("marca") or None,
                proveedor=l.get("proveedor") or None,
            ))
        await session.commit()


async def asignar_asesor_a_lead(telefono: str, asesor: str | None):
    """Asigna (o reasigna) un lead a un asesor y lo marca como no visto por él.
    Función aparte de actualizar_lead porque ésta descarta valores 'falsy'
    (y visto_asesor=False necesita poder guardarse explícitamente).

    `asesor=None` DESASIGNA: el lead vuelve a quedar sin dueño. En ese caso
    visto_asesor vuelve a True —igual que en liberar_asignacion, la otra vía
    por la que un lead se queda sin asesor—: el indicador de "Nuevo" es para
    el asesor asignado, y sin asignado no tiene a quién avisarle. No se toca
    pausado_manual acá (sí lo hace liberar_asignacion): eso responde a que el
    caso anterior se cerró, no a que un supervisor quitó la asignación."""
    async with async_session() as session:
        lead = await session.get(Lead, telefono)
        if lead is None:
            lead = Lead(telefono=telefono)
            session.add(lead)
        lead.asesor_asignado = asesor
        lead.visto_asesor = asesor is None
        lead.actualizado = datetime.utcnow()
        await session.commit()


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


async def liberar_asignacion(telefono: str):
    """Quita la asignación de un lead — se usa cuando el caso anterior ya
    quedó cerrado (vendido / no interesado) y el cliente vuelve a escribir,
    probablemente por una necesidad nueva. Gabi retoma la atención. También
    limpia pausado_manual, para que un caso viejo respondido desde la app no
    deje a Gabi pausada para siempre en un lead que ya se cerró."""
    async with async_session() as session:
        lead = await session.get(Lead, telefono)
        if lead is not None:
            lead.asesor_asignado = None
            lead.pausado_manual = False
            lead.visto_asesor = True
            lead.actualizado = datetime.utcnow()
            await session.commit()


async def pausar_gabi_manual(telefono: str):
    """Pausa a Gabi para este lead porque un asesor le respondió directo
    desde la app de WhatsApp Business en el celular (coexistencia) — sin
    pasar por una asignación formal en el panel. No sabemos qué asesor fue
    (Meta no lo informa), así que no se llena asesor_asignado; en cambio se
    marca paso_flujo='derivado_asesor' (si no lo estaba ya) para que el caso
    aparezca en listar_leads_esperando_asesor() y un supervisor lo reclame y
    lo asigne a una persona real cuando pueda."""
    async with async_session() as session:
        lead = await session.get(Lead, telefono)
        if lead is None:
            lead = Lead(telefono=telefono)
            session.add(lead)
        lead.pausado_manual = True
        if not lead.paso_flujo:
            lead.paso_flujo = "derivado_asesor"
        lead.actualizado = datetime.utcnow()
        await session.commit()


async def registrar_fallo_tecnico(telefono: str) -> int:
    """Suma 1 a los fallos técnicos consecutivos del lead y retorna el nuevo total."""
    async with async_session() as session:
        lead = await session.get(Lead, telefono)
        if lead is None:
            lead = Lead(telefono=telefono)
            session.add(lead)
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


async def contar_leads_activos_por_asesor(usernames: list[str]) -> dict[str, int]:
    """Igual que contar_leads_activos, pero para todo el equipo en una sola
    consulta — el sidebar (rail EQUIPO) antes llamaba a contar_leads_activos
    una vez POR asesor en un loop, o sea un viaje de ida y vuelta a la base
    de datos por cada uno; con Postgres en producción (a diferencia de
    SQLite local, que es casi instantáneo) esa latencia por consulta se
    siente en cada carga completa de página. Acá se trae todo de una vez y
    se cuenta en Python."""
    if not usernames:
        return {}
    async with async_session() as session:
        query = select(Lead.asesor_asignado, Lead.resultado).where(Lead.asesor_asignado.in_(usernames))
        result = await session.execute(query)
        conteos = {u: 0 for u in usernames}
        for asesor, resultado in result.all():
            if resultado not in RESULTADOS_CERRADOS:
                conteos[asesor] += 1
        return conteos


async def crear_usuario(username: str, password: str, nombre: str, rol: str, nivel: str | None = None):
    """Crea (o actualiza la contraseña de) una cuenta del panel interno."""
    import bcrypt
    password_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
    async with async_session() as session:
        usuario = await session.get(Usuario, username)
        if usuario is None:
            usuario = Usuario(username=username)
            session.add(usuario)
        usuario.password_hash = password_hash
        usuario.nombre = nombre
        usuario.rol = rol
        if nivel:
            usuario.nivel = nivel
        await session.commit()


async def cambiar_password(username: str, password_nueva: str):
    """Actualiza SOLO la contraseña de una cuenta (self-service), sin tocar
    nombre/rol/nivel — a diferencia de crear_usuario, que los sobreescribe."""
    import bcrypt
    password_hash = bcrypt.hashpw(password_nueva.encode(), bcrypt.gensalt()).decode()
    async with async_session() as session:
        usuario = await session.get(Usuario, username)
        if usuario is None:
            return
        usuario.password_hash = password_hash
        await session.commit()


async def obtener_usuario(username: str) -> dict | None:
    """Recupera una cuenta del panel interno (incluye el hash, para verificar login)."""
    async with async_session() as session:
        usuario = await session.get(Usuario, username)
        if usuario is None:
            return None
        return {
            "username": usuario.username,
            "password_hash": usuario.password_hash,
            "nombre": usuario.nombre,
            "rol": usuario.rol,
            "nivel": usuario.nivel,
            "disponible": usuario.disponible,
        }


async def listar_asesores() -> list[dict]:
    """Recupera las cuentas con rol 'asesor', para el selector de asignación."""
    async with async_session() as session:
        query = select(Usuario).where(Usuario.rol == "asesor").order_by(Usuario.nombre)
        result = await session.execute(query)
        return [
            {"username": u.username, "nombre": u.nombre, "nivel": u.nivel, "disponible": u.disponible}
            for u in result.scalars().all()
        ]


async def actualizar_disponibilidad(username: str, disponible: bool):
    """El propio asesor togglea si está disponible para recibir leads nuevos."""
    async with async_session() as session:
        usuario = await session.get(Usuario, username)
        if usuario is not None:
            usuario.disponible = disponible
            await session.commit()


async def actualizar_nivel_asesor(username: str, nivel: str):
    """El supervisor/admin ajusta el nivel de experiencia de un asesor."""
    async with async_session() as session:
        usuario = await session.get(Usuario, username)
        if usuario is not None:
            usuario.nivel = nivel
            await session.commit()


async def asignar_campana_origen(telefono: str, nombre_campana: str):
    """Guarda la campaña de origen de un lead — solo si aún no tenía una
    asignada, para no perder la atribución original del primer contacto."""
    async with async_session() as session:
        lead = await session.get(Lead, telefono)
        if lead is None:
            lead = Lead(telefono=telefono)
            session.add(lead)
        if not lead.campana_origen:
            lead.campana_origen = nombre_campana
            lead.actualizado = datetime.utcnow()
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
    }


async def crear_campana(
    nombre: str, tipo_deteccion: str, patron: str,
    codigo_material: str = "", producto_promocional: str = "", precio_promocional: str = "",
    texto_saludo: str = "",
) -> dict:
    """Crea una campaña nueva (ej. cuando cambia la promoción del mes)."""
    async with async_session() as session:
        campana = Campana(
            nombre=nombre,
            tipo_deteccion=tipo_deteccion,
            patron=patron,
            codigo_material=codigo_material or None,
            producto_promocional=producto_promocional or None,
            precio_promocional=precio_promocional or None,
            texto_saludo=texto_saludo or None,
        )
        session.add(campana)
        await session.commit()
        await session.refresh(campana)
        return _campana_a_dict(campana)


async def listar_campanas(solo_activas: bool = False) -> list[dict]:
    """Recupera las campañas configuradas, más recientes primero."""
    async with async_session() as session:
        query = select(Campana).order_by(Campana.creado.desc())
        if solo_activas:
            query = query.where(Campana.activa.is_(True))
        result = await session.execute(query)
        return [_campana_a_dict(c) for c in result.scalars().all()]


async def obtener_campana_por_nombre(nombre: str) -> dict | None:
    """Recupera una campaña por su nombre exacto (ej. para saber qué promo
    ofrecer según la campana_origen guardada en el lead). Usa .first() con
    límite en vez de esperar una fila única: el nombre no tiene una
    restricción UNIQUE a nivel de base de datos, así que si llegara a haber
    más de una campaña con el mismo nombre, esto no debe tumbar el arranque
    del servidor — se toma la primera."""
    async with async_session() as session:
        query = select(Campana).where(Campana.nombre == nombre).limit(1)
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


async def eliminar_campana(campana_id: int) -> bool:
    """Borra una campaña por completo — SOLO si nunca tuvo ningún lead
    atribuido (así no se pierde historial de conversión real). Si ya tiene
    al menos un lead, no la borra y retorna False; el camino normal para una
    campaña con leads es desactivarla (ver actualizar_campana activa=False),
    no borrarla."""
    async with async_session() as session:
        campana = await session.get(Campana, campana_id)
        if campana is None:
            return False
        query_conteo = select(func.count()).select_from(Lead).where(Lead.campana_origen == campana.nombre)
        total_leads = (await session.execute(query_conteo)).scalar_one()
        if total_leads > 0:
            return False
        await session.delete(campana)
        await session.commit()
        return True


async def contar_leads_por_campana() -> list[dict]:
    """Cuenta leads y ventas por campaña de origen — para medir conversión por campaña."""
    async with async_session() as session:
        query = select(
            Lead.campana_origen,
            func.count().label("total"),
            func.sum(case((Lead.resultado == "vendido", 1), else_=0)).label("vendidos"),
        ).where(Lead.campana_origen.is_not(None)).group_by(Lead.campana_origen)
        result = await session.execute(query)
        return [
            {"campana": fila.campana_origen, "total": fila.total, "vendidos": fila.vendidos or 0}
            for fila in result.all()
        ]


async def limpiar_historial(telefono: str):
    """Borra todo el historial de una conversación."""
    async with async_session() as session:
        query = select(Mensaje).where(Mensaje.telefono == telefono)
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
        "subido_por": a.subido_por, "creado": a.creado,
    }


async def crear_archivo_adjunto(
    nombre_original: str, ruta_disco: str, content_type: str, tamano_bytes: int,
    subido_por: str, reutilizable: bool = False, etiqueta: str | None = None,
) -> dict:
    """Registra un archivo ya guardado en disco (proforma puntual o catálogo
    reutilizable) — ver ARCHIVOS_DIR en dashboard.py para dónde vive el archivo."""
    async with async_session() as session:
        archivo = ArchivoAdjunto(
            nombre_original=nombre_original, ruta_disco=ruta_disco, content_type=content_type,
            tamano_bytes=tamano_bytes, reutilizable=reutilizable, etiqueta=etiqueta, subido_por=subido_por,
        )
        session.add(archivo)
        await session.commit()
        await session.refresh(archivo)
        return _archivo_a_dict(archivo)


async def obtener_archivo_adjunto(archivo_id: int) -> dict | None:
    async with async_session() as session:
        archivo = await session.get(ArchivoAdjunto, archivo_id)
        return _archivo_a_dict(archivo) if archivo else None


async def listar_archivos_reutilizables() -> list[dict]:
    """Librería de catálogos ya subidos, listos para enviar en cualquier
    conversación sin volver a subirlos — más recientes primero."""
    async with async_session() as session:
        query = (
            select(ArchivoAdjunto)
            .where(ArchivoAdjunto.reutilizable.is_(True))
            .order_by(ArchivoAdjunto.creado.desc())
        )
        result = await session.execute(query)
        return [_archivo_a_dict(a) for a in result.scalars().all()]


async def eliminar_archivo_reutilizable(archivo_id: int):
    """Quita un catálogo de la librería (no borra el archivo físico del disco,
    por si algún mensaje viejo todavía lo referencia — solo dejar de ofrecerlo
    para envíos nuevos)."""
    async with async_session() as session:
        archivo = await session.get(ArchivoAdjunto, archivo_id)
        if archivo is None:
            return
        archivo.reutilizable = False
        await session.commit()


async def obtener_telefono_de_archivo(archivo_id: int) -> str | None:
    """A qué lead se le envió un archivo puntual (proforma) — para poder
    verificar que quien lo quiere descargar tiene acceso a ese lead. Un
    catálogo reutilizable puede estar ligado a varios leads, así que esto
    solo tiene sentido/se usa para archivos no reutilizables."""
    async with async_session() as session:
        query = select(Mensaje.telefono).where(Mensaje.archivo_id == archivo_id).limit(1)
        result = await session.execute(query)
        return result.scalar_one_or_none()


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
    "descripcion", "combo", "comentarios", "fee_prv", "fee_clda", "precio",
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
        "CANAL": p.canal or "",
        "PROVEEDOR": p.proveedor or "",
        "MARCA": p.marca or "",
        "TIPO": p.tipo or "",
        "SUB TIPO": p.sub_tipo or "",
        "CODIGO HANA": p.codigo_hana or "",
        "DESCRIPCIÓN": p.descripcion or "",
        "COMBO": p.combo or "",
        "COMENTARIOS": p.comentarios or "",
        "FEE PRV": p.fee_prv or "",
        "FEE CLDA": p.fee_clda or "",
        "PRECIO": p.precio or "",
    }
    fila.update(p.cuotas or {})
    return fila


async def listar_productos_activos() -> list[dict]:
    """Catálogo completo (solo filas activas) para búsqueda/scoring en
    Python — ~360 filas es trivial de traer entero en cada consulta, igual
    que ya se hacía con el CSV cacheado en memoria de proceso (sin la
    desventaja de esa variable global: acá cada request ve el dato real)."""
    async with async_session() as session:
        query = select(Producto).where(Producto.activo.is_(True)).order_by(Producto.id.asc())
        result = await session.execute(query)
        return [_producto_a_dict(p) for p in result.scalars().all()]


async def obtener_producto_por_codigo_hana(codigo: str) -> dict | None:
    """Primer producto activo con este CODIGO HANA, ordenado por id (mismo
    criterio de "primera fila que matchea" que ya usaba el CSV — CODIGO
    HANA no es único, ver Producto)."""
    async with async_session() as session:
        query = (
            select(Producto)
            .where(Producto.codigo_hana == codigo, Producto.activo.is_(True))
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


async def importar_catalogo_desde_csv(ruta_csv: str, autor: str | None = None) -> dict:
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
    """
    with open(ruta_csv, "r", encoding="utf-8-sig") as f:
        filas_csv = [_fila_csv_a_datos(fila) for fila in csv.DictReader(f)]

    resumen = {
        "procesados": len(filas_csv), "nuevos": 0, "modificados": 0,
        "sin_cambios": 0, "desactivados": 0, "en_creacion_ambiguas": 0,
    }

    async with async_session() as session:
        result = await session.execute(select(Producto))
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


async def listar_productos(filtros: dict, pagina: int, por_pagina: int = 20) -> tuple[list[dict], int]:
    """Página de productos + total de coincidencias (para la paginación de la
    pantalla de catálogo). Filtros soportados: `q` (texto libre sobre marca y
    descripción), `canal`, `marca`, `tipo` (coincidencia exacta) y `activo`
    (bool; si no viene, devuelve activos e inactivos)."""
    filtros = filtros or {}
    condiciones = []

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


async def obtener_producto(id: int) -> dict | None:
    async with async_session() as session:
        p = await session.get(Producto, id)
        return _producto_a_dict_panel(p) if p else None


async def crear_producto(datos: dict, autor: str) -> dict:
    """Alta manual desde el panel. Arranca en version=0 (igual que los leads)
    y deja constancia de la creación en la bitácora."""
    async with async_session() as session:
        producto = Producto(
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


async def editar_producto(id: int, cambios: dict, version_esperada: int, autor: str) -> dict | None:
    """Edición manual con concurrencia optimista — MISMO criterio que
    intentar_avanzar_version() para leads: solo se aplica si el producto sigue
    en la versión que tenía cuando se abrió el formulario; si alguien más
    escribió antes, no se aplica NADA y se devuelve None para que quien llama
    muestre el conflicto (Human Decision Gate) en vez de sobrescribir en
    silencio. La diferencia con los leads es solo mecánica: acá el chequeo y
    la escritura viven en la misma sesión/transacción, porque hay campos que
    escribir en el mismo acto.

    Devuelve el producto actualizado, o None si la versión no coincide (o si
    el producto no existe — quien llama distingue los dos casos consultando
    obtener_producto()).

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
        if producto is None or producto.version != version_esperada:
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
            .where(Producto.id == id, Producto.version == version_esperada)
            .values(**valores, version=version_esperada + 1)
        )
        if resultado.rowcount == 0:
            await session.rollback()
            return None
        await session.commit()

    for campo, anterior, nuevo in cambios_reales:
        await registrar_cambio_precio_producto(id, campo, anterior, nuevo, autor)
    return await obtener_producto(id)


async def toggle_producto(id: int, version_esperada: int, autor: str) -> dict | None:
    """Activa/desactiva un producto — nunca se borra físicamente. Mismo manejo
    de concurrencia que editar_producto(), incluida la condición de versión
    dentro del UPDATE (dos toggles simultáneos con la misma versión daban 200
    los dos y dejaban una sola bitácora, ver editar_producto)."""
    async with async_session() as session:
        producto = await session.get(Producto, id)
        if producto is None or producto.version != version_esperada:
            return None
        anterior = producto.activo

    async with async_session() as session:
        resultado = await session.execute(
            update(Producto)
            .where(Producto.id == id, Producto.version == version_esperada)
            .values(activo=not anterior, version=version_esperada + 1)
        )
        if resultado.rowcount == 0:
            await session.rollback()
            return None
        await session.commit()

    await registrar_cambio_precio_producto(
        id, CAMPO_AUDITORIA_ACTIVO, str(anterior).lower(), str(not anterior).lower(), autor,
    )
    return await obtener_producto(id)


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
