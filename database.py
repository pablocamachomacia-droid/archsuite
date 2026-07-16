import os
from typing import Optional

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, declarative_base, sessionmaker

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./archportal.db")

engine = create_engine(
    DATABASE_URL, connect_args={"check_same_thread": False}
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# Los imports de `models` se hacen dentro de cada función (no a nivel de módulo)
# porque models.py importa `Base` desde este mismo archivo: un import circular
# a nivel de módulo rompería la carga de ambos ficheros.


def create_project(
    db: Session,
    user_id: int,
    nombre_proyecto: str,
    tipo,
    datos_entrada: Optional[dict] = None,
    estado=None,
):
    from models import EstadoProyecto, Project

    project = Project(
        user_id=user_id,
        nombre_proyecto=nombre_proyecto,
        tipo=tipo,
        datos_entrada=datos_entrada,
        estado=estado or EstadoProyecto.borrador,
    )
    db.add(project)
    db.commit()
    db.refresh(project)
    return project


def get_user_projects(db: Session, user_id: int, limit: Optional[int] = None):
    from models import Project

    query = (
        db.query(Project)
        .filter(Project.user_id == user_id)
        .order_by(Project.fecha_creacion.desc())
    )
    if limit is not None:
        query = query.limit(limit)
    return query.all()


def get_project_by_id(db: Session, project_id: int, user_id: Optional[int] = None):
    from models import Project

    query = db.query(Project).filter(Project.id == project_id)
    if user_id is not None:
        query = query.filter(Project.user_id == user_id)
    return query.first()


def count_users(db: Session) -> int:
    from models import User

    return db.query(User).count()


def count_projects_by_tipo(db: Session) -> dict:
    from sqlalchemy import func

    from models import Project

    rows = db.query(Project.tipo, func.count(Project.id)).group_by(Project.tipo).all()
    return {tipo.value: count for tipo, count in rows}


def count_projects_since(db: Session, since) -> int:
    from models import Project

    return db.query(Project).filter(Project.fecha_creacion >= since).count()


def get_all_users_with_counts(db: Session):
    """Todos los usuarios ordenados por fecha de registro (más reciente primero),
    con un atributo `project_count` calculado sin N+1 queries."""
    from sqlalchemy import func

    from models import Project, User

    counts = dict(
        db.query(Project.user_id, func.count(Project.id)).group_by(Project.user_id).all()
    )
    users = db.query(User).order_by(User.fecha_registro.desc()).all()
    for user in users:
        user.project_count = counts.get(user.id, 0)
    return users


def get_recent_projects(db: Session, limit: int = 20):
    from sqlalchemy.orm import joinedload

    from models import Project

    return (
        db.query(Project)
        .options(joinedload(Project.user))
        .order_by(Project.fecha_creacion.desc())
        .limit(limit)
        .all()
    )


def toggle_user_active(db: Session, user_id: int):
    from models import User

    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        return None
    user.activo = not user.activo
    db.commit()
    db.refresh(user)
    return user


def update_user_profile(
    db: Session,
    user_id: int,
    nombre: str,
    apellidos: str,
    empresa: Optional[str],
    telefono: Optional[str],
):
    """Recibe `user_id` (no el objeto `user`): el `user` de `get_current_user`
    proviene de la sesión de BD del middleware, ya cerrada, así que escribir sobre
    él directamente en otra sesión falla. Se vuelve a consultar en esta sesión,
    igual que `toggle_user_active`."""
    from models import User

    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        return None
    user.nombre = nombre
    user.apellidos = apellidos
    user.empresa = empresa
    user.telefono = telefono
    db.commit()
    db.refresh(user)
    return user


def set_user_password(db: Session, user_id: int, hashed_password: str):
    from models import User

    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        return None
    user.hashed_password = hashed_password
    db.commit()
    db.refresh(user)
    return user


def count_projects_by_tipo_for_user(db: Session, user_id: int) -> dict:
    from sqlalchemy import func

    from models import Project

    rows = (
        db.query(Project.tipo, func.count(Project.id))
        .filter(Project.user_id == user_id)
        .group_by(Project.tipo)
        .all()
    )
    return {tipo.value: count for tipo, count in rows}


def delete_project(db: Session, project_id: int, user_id: int) -> bool:
    from models import Project

    project = (
        db.query(Project)
        .filter(Project.id == project_id, Project.user_id == user_id)
        .first()
    )
    if project is None:
        return False
    db.delete(project)
    db.commit()
    return True
