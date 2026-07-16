from jose import JWTError, jwt
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import RedirectResponse

from auth import ALGORITHM, COOKIE_NAME, SECRET_KEY
from database import SessionLocal
from models import User

PUBLIC_PATHS = {"/", "/login", "/register", "/auth/login", "/auth/register", "/logout"}
PUBLIC_PREFIXES = ("/static",)


class AuthMiddleware(BaseHTTPMiddleware):
    """Protege todas las rutas salvo /, /login, /register y /static.

    Decodifica el JWT de la cookie en cada petición (incluidas las públicas,
    para que /login y /register puedan redirigir a un usuario ya autenticado)
    y adjunta el usuario a request.state.user.
    """

    async def dispatch(self, request: Request, call_next):
        request.state.user = None

        token = request.cookies.get(COOKIE_NAME)
        if token:
            try:
                payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
                email = payload.get("sub")
            except JWTError:
                email = None

            if email:
                db = SessionLocal()
                try:
                    user = db.query(User).filter(User.email == email).first()
                    if user and user.activo:
                        request.state.user = user
                finally:
                    db.close()

        path = request.url.path
        is_public = path in PUBLIC_PATHS or path.startswith(PUBLIC_PREFIXES)

        if not is_public and request.state.user is None:
            return RedirectResponse("/login", status_code=303)

        return await call_next(request)
