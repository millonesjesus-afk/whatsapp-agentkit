# agent/memory.py — Memoria de conversaciones con SQLite
# Generado por AgentKit

"""
Sistema de memoria del agente. Guarda el historial de conversaciones
por número de teléfono usando SQLite (local) o PostgreSQL (producción).
"""

import os
import logging
from datetime import datetime
from cryptography.fernet import Fernet
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, aliased
from sqlalchemy import String, Text, DateTime, select, Integer, Boolean, func, case, delete, JSON
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
    todavía está evolucionando. Retorna (leads de la página, total sin paginar)."""
    columna = COLUMNAS_ORDEN_PIPELINE.get(orden, Lead.actualizado)
    async with async_session() as session:
        query = select(Lead)
        if asesor_asignado:
            query = query.where(Lead.asesor_asignado == asesor_asignado)
        if resultado:
            query = query.where(Lead.resultado == resultado)
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


async def actualizar_lead(telefono: str, **campos):
    """Actualiza (o crea) los datos estructurados del cliente. Solo sobreescribe
    los campos con un valor no vacío, para no perder datos ya conocidos."""
    campos = {k: v for k, v in campos.items() if v}
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


async def listar_lineas_venta(telefono: str) -> list[dict]:
    """Líneas de venta de un lead (un artefacto, varios, o un mix con
    servicio), en el orden en que se agregaron."""
    async with async_session() as session:
        query = select(LineaVenta).where(LineaVenta.telefono == telefono).order_by(LineaVenta.id.asc())
        result = await session.execute(query)
        return [
            {"producto": l.producto, "precio": l.precio, "marca": l.marca, "proveedor": l.proveedor}
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


async def asignar_asesor_a_lead(telefono: str, asesor: str):
    """Asigna (o reasigna) un lead a un asesor y lo marca como no visto por él.
    Función aparte de actualizar_lead porque ésta descarta valores 'falsy'
    (y visto_asesor=False necesita poder guardarse explícitamente)."""
    async with async_session() as session:
        lead = await session.get(Lead, telefono)
        if lead is None:
            lead = Lead(telefono=telefono)
            session.add(lead)
        lead.asesor_asignado = asesor
        lead.visto_asesor = False
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
