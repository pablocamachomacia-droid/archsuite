from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from sqlalchemy.orm import Session

from auth import get_current_user
from database import create_project, get_db
from licencia_ai import generar_informe_ia, normalizar_informe
from models import EstadoProyecto, TipoProyecto, User
from nav import ICONS, build_sidebar_items

router = APIRouter(tags=["licencia"])
templates = Jinja2Templates(directory="templates")


class LicenciaPortalRequest(BaseModel):
    direccion: str
    municipio: str
    provincia: str
    clasificacion_urbanistica: str
    uso_previsto: str
    superficie_solar: float
    edificabilidad: float
    descripcion_proyecto: str


@router.get("/licencia", response_class=HTMLResponse)
def licencia_form(request: Request, user: User = Depends(get_current_user)):
    return templates.TemplateResponse(
        "licencia.html",
        {
            "request": request,
            "user": user,
            "icons": ICONS,
            "sidebar_items": build_sidebar_items("Licencias"),
        },
    )


@router.post("/licencia/analizar", response_class=HTMLResponse)
def licencia_analizar(
    request: Request,
    direccion: str = Form(...),
    municipio: str = Form(...),
    provincia: str = Form(...),
    clasificacion_urbanistica: str = Form(...),
    uso_previsto: str = Form(...),
    superficie_solar: float = Form(...),
    edificabilidad: float = Form(...),
    descripcion_proyecto: str = Form(...),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    datos = LicenciaPortalRequest(
        direccion=direccion,
        municipio=municipio,
        provincia=provincia,
        clasificacion_urbanistica=clasificacion_urbanistica,
        uso_previsto=uso_previsto,
        superficie_solar=superficie_solar,
        edificabilidad=edificabilidad,
        descripcion_proyecto=descripcion_proyecto,
    )

    informe_raw = generar_informe_ia(datos)
    informe = normalizar_informe(informe_raw)

    project = create_project(
        db,
        user_id=user.id,
        nombre_proyecto=f"Licencia — {direccion}, {municipio}",
        tipo=TipoProyecto.licencia,
        datos_entrada=datos.model_dump(),
        estado=EstadoProyecto.completado,
    )
    project.resultado = informe
    db.commit()

    return templates.TemplateResponse(
        "licencia_resultado.html",
        {
            "request": request,
            "user": user,
            "icons": ICONS,
            "sidebar_items": build_sidebar_items("Licencias"),
            "datos": datos,
            "semaforo": informe["semaforo"],
            "resumen_semaforo": informe["resumen_semaforo"],
            "secciones": informe["secciones"],
        },
    )
