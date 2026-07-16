from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from nav import ICONS, TOOLS

router = APIRouter(tags=["public"])
templates = Jinja2Templates(directory="templates")


@router.get("/", response_class=HTMLResponse)
def landing(request: Request):
    if request.state.user:
        return RedirectResponse("/dashboard")
    return templates.TemplateResponse(
        "landing.html",
        {"request": request, "tools": TOOLS, "icons": ICONS},
    )
