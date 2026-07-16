from fastapi import APIRouter, Depends, Form, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from auth import (
    COOKIE_NAME,
    authenticate_user,
    create_access_token,
    get_optional_user,
    get_password_hash,
)
from database import get_db
from models import RolUsuario, User

router = APIRouter(tags=["auth"])
templates = Jinja2Templates(directory="templates")


@router.get("/login", response_class=HTMLResponse)
def login_form(request: Request, user=Depends(get_optional_user)):
    if user:
        return RedirectResponse("/dashboard", status_code=status.HTTP_303_SEE_OTHER)
    return templates.TemplateResponse(
        "login.html", {"request": request, "error": None}
    )


@router.post("/auth/login", response_class=HTMLResponse)
def login_submit(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
):
    user, error = authenticate_user(db, email, password)
    if error:
        return templates.TemplateResponse(
            "login.html",
            {"request": request, "error": error},
            status_code=status.HTTP_401_UNAUTHORIZED,
        )

    token = create_access_token({"sub": user.email})
    response = RedirectResponse("/dashboard", status_code=status.HTTP_303_SEE_OTHER)
    response.set_cookie(
        key=COOKIE_NAME,
        value=token,
        httponly=True,
        samesite="lax",
        max_age=60 * 60,
    )
    return response


@router.get("/register", response_class=HTMLResponse)
def register_form(request: Request, user=Depends(get_optional_user)):
    if user:
        return RedirectResponse("/dashboard", status_code=status.HTTP_303_SEE_OTHER)
    return templates.TemplateResponse(
        "register.html", {"request": request, "error": None}
    )


@router.post("/auth/register", response_class=HTMLResponse)
def register_submit(
    request: Request,
    nombre: str = Form(...),
    apellidos: str = Form(...),
    empresa: str = Form(""),
    email: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
):
    existing = db.query(User).filter(User.email == email).first()
    if existing:
        return templates.TemplateResponse(
            "register.html",
            {"request": request, "error": "Ya existe una cuenta con ese email."},
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    if len(password) < 8:
        return templates.TemplateResponse(
            "register.html",
            {
                "request": request,
                "error": "La contraseña debe tener al menos 8 caracteres.",
            },
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    user = User(
        nombre=nombre,
        apellidos=apellidos,
        empresa=empresa or None,
        email=email,
        hashed_password=get_password_hash(password),
        rol=RolUsuario.cliente,
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    token = create_access_token({"sub": user.email})
    response = RedirectResponse("/dashboard", status_code=status.HTTP_303_SEE_OTHER)
    response.set_cookie(
        key=COOKIE_NAME,
        value=token,
        httponly=True,
        samesite="lax",
        max_age=60 * 60,
    )
    return response


@router.get("/logout")
def logout():
    response = RedirectResponse("/login", status_code=status.HTTP_303_SEE_OTHER)
    response.delete_cookie(COOKIE_NAME)
    return response
