from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from auth import get_current_admin
from database import (
    count_projects_by_tipo,
    count_projects_since,
    count_users,
    get_all_users_with_counts,
    get_db,
    get_recent_projects,
    toggle_user_active,
)
from models import User
from nav import ICONS, build_sidebar_items

router = APIRouter(tags=["admin"])
templates = Jinja2Templates(directory="templates")

TIPO_LABELS = {
    "licencia": "Licencia",
    "memoria": "Memoria",
    "presupuesto": "Presupuesto",
    "superficie": "Superficie",
    "pliego": "Pliego",
}


def _inicio_semana() -> datetime:
    hoy = datetime.now()
    return (hoy - timedelta(days=hoy.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)


def _inicio_mes() -> datetime:
    hoy = datetime.now()
    return hoy.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


@router.get("/admin", response_class=HTMLResponse)
def admin_panel(
    request: Request,
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    proyectos_por_tipo = count_projects_by_tipo(db)

    return templates.TemplateResponse(
        "admin.html",
        {
            "request": request,
            "user": admin,
            "icons": ICONS,
            "sidebar_items": build_sidebar_items("Admin"),
            "total_usuarios": count_users(db),
            "total_proyectos": sum(proyectos_por_tipo.values()),
            "proyectos_por_tipo": proyectos_por_tipo,
            "tipo_labels": TIPO_LABELS,
            "proyectos_semana": count_projects_since(db, _inicio_semana()),
            "proyectos_mes": count_projects_since(db, _inicio_mes()),
            "usuarios": get_all_users_with_counts(db),
            "proyectos_recientes": get_recent_projects(db, limit=20),
        },
    )


@router.post("/admin/usuarios/{user_id}/toggle")
def admin_toggle_usuario(
    user_id: int,
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    if user_id == admin.id:
        raise HTTPException(status_code=400, detail="No puedes desactivar tu propia cuenta.")

    updated = toggle_user_active(db, user_id)
    if updated is None:
        raise HTTPException(status_code=404, detail="Usuario no encontrado.")

    return RedirectResponse("/admin", status_code=303)
