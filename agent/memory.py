# agent/memory.py — Memoria de conversaciones con SQLite
# Generado por AgentKit

"""
Sistema de memoria del agente. Guarda el historial de conversaciones
por número de teléfono usando SQLite (local) o PostgreSQL (producción).
"""

import os
from datetime import datetime
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy import String, Text, DateTime, select, Integer, Boolean, func, case
from dotenv import load_dotenv

load_dotenv()

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
    # Asesor al que el supervisor asignó este lead (username de Usuario)
    asesor_asignado: Mapped[str | None] = mapped_column(String(50), nullable=True)
    # Cierre de venta (si resultado == "vendido") — idealmente viene del
    # catálogo real (por código), pero se puede escribir a mano si el
    # producto no está cargado ahí todavía.
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
    actualizado: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
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


async def inicializar_db():
    """Crea las tablas si no existen."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def guardar_mensaje(telefono: str, role: str, content: str, archivo_id: int | None = None):
    """Guarda un mensaje en el historial de conversación. archivo_id solo se
    usa cuando el mensaje fue un archivo adjunto enviado por un asesor."""
    async with async_session() as session:
        mensaje = Mensaje(
            telefono=telefono,
            role=role,
            content=content,
            timestamp=datetime.utcnow(),
            archivo_id=archivo_id,
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

        return [
            {"role": msg.role, "content": msg.content, "archivo_id": msg.archivo_id}
            for msg in mensajes
        ]


async def obtener_ultimo_mensaje(telefono: str) -> dict | None:
    """Recupera el último mensaje de una conversación (para la vista previa en la bandeja)."""
    async with async_session() as session:
        query = (
            select(Mensaje)
            .where(Mensaje.telefono == telefono)
            .order_by(Mensaje.timestamp.desc())
            .limit(1)
        )
        result = await session.execute(query)
        msg = result.scalars().first()
        if msg is None:
            return None
        return {"role": msg.role, "content": msg.content, "timestamp": msg.timestamp}


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
        "producto_vendido": lead.producto_vendido,
        "precio_venta": lead.precio_venta,
        "marca_venta": lead.marca_venta,
        "proveedor_venta": lead.proveedor_venta,
        "modalidad_pago": lead.modalidad_pago,
        "cuotas": lead.cuotas,
        "medio_pago": lead.medio_pago,
        "visto_asesor": lead.visto_asesor,
        "fallos_tecnicos": lead.fallos_tecnicos,
        "campana_origen": lead.campana_origen,
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
    probablemente por una necesidad nueva. Gabi retoma la atención."""
    async with async_session() as session:
        lead = await session.get(Lead, telefono)
        if lead is not None:
            lead.asesor_asignado = None
            lead.visto_asesor = True
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
    ofrecer según la campana_origen guardada en el lead)."""
    async with async_session() as session:
        query = select(Campana).where(Campana.nombre == nombre)
        result = await session.execute(query)
        campana = result.scalar_one_or_none()
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
