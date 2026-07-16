from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from auth import get_current_user
from database import get_db, get_user_projects
from models import User
from nav import ICONS, TOOLS, build_sidebar_items

router = APIRouter(tags=["dashboard"])
templates = Jinja2Templates(directory="templates")

TIPO_LABELS = {
    "licencia": "Licencia",
    "memoria": "Memoria",
    "presupuesto": "Presupuesto",
    "superficie": "Superficie",
    "pliego": "Pliego",
}


@router.get("/dashboard", response_class=HTMLResponse)
def dashboard(
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    proyectos = get_user_projects(db, user.id, limit=5)
    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "user": user,
            "tools": TOOLS,
            "sidebar_items": build_sidebar_items("Dashboard"),
            "icons": ICONS,
            "proyectos": proyectos,
            "tipo_labels": TIPO_LABELS,
        },
    )
