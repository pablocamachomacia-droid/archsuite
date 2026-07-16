import enum
from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
)
from sqlalchemy.orm import relationship

from database import Base


class RolUsuario(str, enum.Enum):
    admin = "admin"
    cliente = "cliente"


class TipoProyecto(str, enum.Enum):
    licencia = "licencia"
    memoria = "memoria"
    presupuesto = "presupuesto"
    superficie = "superficie"
    pliego = "pliego"


class EstadoProyecto(str, enum.Enum):
    borrador = "borrador"
    completado = "completado"


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String(255), unique=True, index=True, nullable=False)
    nombre = Column(String(100), nullable=False)
    apellidos = Column(String(150), nullable=False)
    empresa = Column(String(150), nullable=True)
    telefono = Column(String(30), nullable=True)
    hashed_password = Column(String(255), nullable=False)
    rol = Column(Enum(RolUsuario), default=RolUsuario.cliente, nullable=False)
    fecha_registro = Column(DateTime, default=datetime.utcnow, nullable=False)
    activo = Column(Boolean, default=True, nullable=False)

    projects = relationship("Project", back_populates="user")


class Project(Base):
    __tablename__ = "projects"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    nombre_proyecto = Column(String(200), nullable=False)
    tipo = Column(Enum(TipoProyecto), nullable=False)
    fecha_creacion = Column(DateTime, default=datetime.utcnow, nullable=False)
    estado = Column(Enum(EstadoProyecto), default=EstadoProyecto.borrador, nullable=False)
    datos_entrada = Column(JSON, nullable=True)
    resultado = Column(JSON, nullable=True)
    archivo_generado = Column(String(500), nullable=True)

    user = relationship("User", back_populates="projects")
