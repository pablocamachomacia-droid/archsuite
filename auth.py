import os
from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple

from dotenv import load_dotenv
from fastapi import HTTPException, Request, status
from jose import jwt
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from models import User

load_dotenv()

SECRET_KEY = os.getenv("SECRET_KEY", "changeme")
ALGORITHM = os.getenv("ALGORITHM", "HS256")
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "60"))

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

COOKIE_NAME = "access_token"


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)


def authenticate_user(
    db: Session, email: str, password: str
) -> Tuple[Optional[User], Optional[str]]:
    user = db.query(User).filter(User.email == email).first()
    if not user or not verify_password(password, user.hashed_password):
        return None, "Email o contraseña incorrectos."
    if not user.activo:
        return None, "Tu cuenta está desactivada. Contacta con el administrador."
    return user, None


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (
        expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def get_current_user(request: Request) -> User:
    """El AuthMiddleware ya valida el JWT y adjunta el usuario a request.state.
    Esta dependencia solo lo expone a la ruta (con un fallback de seguridad)."""
    user = getattr(request.state, "user", None)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_303_SEE_OTHER,
            headers={"Location": "/login"},
        )
    return user


def get_optional_user(request: Request) -> Optional[User]:
    return getattr(request.state, "user", None)


def get_current_admin(request: Request) -> User:
    user = get_current_user(request)
    if user.rol.value != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Acceso restringido a administradores.",
        )
    return user
