from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from auth import get_current_user, get_password_hash, verify_password
from database import (
    count_projects_by_tipo_for_user,
    delete_project,
    get_db,
    get_user_projects,
    set_user_password,
    update_user_profile,
)
from models import User
from nav import ICONS, build_sidebar_items

router = APIRouter(tags=["perfil"])
templates = Jinja2Templates(directory="templates")

TIPO_LABELS = {
    "licencia": "Licencia",
    "memoria": "Memoria",
    "presupuesto": "Presupuesto",
    "superficie": "Superficie",
    "pliego": "Pliego",
}


def _contexto_perfil(request: Request, user: User, db: Session, **extra):
    ctx = {
        "request": request,
        "user": user,
        "icons": ICONS,
        "sidebar_items": build_sidebar_items("Perfil"),
        "proyectos": get_user_projects(db, user.id),
        "resumen": count_projects_by_tipo_for_user(db, user.id),
        "tipo_labels": TIPO_LABELS,
    }
    ctx.update(extra)
    return ctx


@router.get("/perfil", response_class=HTMLResponse)
def perfil(
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return templates.TemplateResponse("perfil.html", _contexto_perfil(request, user, db))


@router.post("/perfil/actualizar", response_class=HTMLResponse)
def perfil_actualizar(
    request: Request,
    nombre: str = Form(...),
    apellidos: str = Form(...),
    empresa: str = Form(""),
    telefono: str = Form(""),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    update_user_profile(
        db,
        user.id,
        nombre=nombre,
        apellidos=apellidos,
        empresa=empresa.strip() or None,
        telefono=telefono.strip() or None,
    )
    return RedirectResponse("/perfil", status_code=303)


@router.post("/perfil/password", response_class=HTMLResponse)
def perfil_password(
    request: Request,
    password_actual: str = Form(...),
    password_nueva: str = Form(...),
    password_confirmar: str = Form(...),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not verify_password(password_actual, user.hashed_password):
        ctx = _contexto_perfil(request, user, db, error_password="La contraseña actual no es correcta.")
        return templates.TemplateResponse("perfil.html", ctx, status_code=400)

    if password_nueva != password_confirmar:
        ctx = _contexto_perfil(request, user, db, error_password="Las contraseñas nuevas no coinciden.")
        return templates.TemplateResponse("perfil.html", ctx, status_code=400)

    if len(password_nueva) < 8:
        ctx = _contexto_perfil(
            request, user, db, error_password="La nueva contraseña debe tener al menos 8 caracteres."
        )
        return templates.TemplateResponse("perfil.html", ctx, status_code=400)

    set_user_password(db, user.id, get_password_hash(password_nueva))

    ctx = _contexto_perfil(request, user, db, success_password="Contraseña actualizada correctamente.")
    return templates.TemplateResponse("perfil.html", ctx)


@router.post("/perfil/proyectos/{project_id}/eliminar")
def perfil_eliminar_proyecto(
    project_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    eliminado = delete_project(db, project_id, user_id=user.id)
    if not eliminado:
        raise HTTPException(status_code=404, detail="Proyecto no encontrado.")
    return RedirectResponse("/perfil", status_code=303)
