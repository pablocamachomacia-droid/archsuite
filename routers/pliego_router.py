from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, Response
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from sqlalchemy.orm import Session

from auth import get_current_user
from database import create_project, get_db, get_project_by_id
from models import EstadoProyecto, TipoProyecto, User
from nav import ICONS, build_sidebar_items
from pliego_ai import generar_pliego_ia, normalizar_pliego
from pliego_word import construir_word

router = APIRouter(tags=["pliego"])
templates = Jinja2Templates(directory="templates")


class PliegoPortalRequest(BaseModel):
    nombre_proyecto: str
    arquitecto: str
    tipo_obra: str
    municipio: str
    provincia: str
    presupuesto_pem: float
    descripcion_proyecto: str
    estructura: str
    cubierta: str
    fachada: str
    instalaciones: str
    calidad_acabados: str


@router.get("/pliego", response_class=HTMLResponse)
def pliego_form(request: Request, user: User = Depends(get_current_user)):
    return templates.TemplateResponse(
        "pliego.html",
        {
            "request": request,
            "user": user,
            "icons": ICONS,
            "sidebar_items": build_sidebar_items("Pliegos"),
        },
    )


@router.post("/pliego/generar", response_class=HTMLResponse)
def pliego_generar(
    request: Request,
    nombre_proyecto: str = Form(...),
    arquitecto: str = Form(...),
    tipo_obra: str = Form(...),
    municipio: str = Form(...),
    provincia: str = Form(...),
    presupuesto_pem: float = Form(...),
    descripcion_proyecto: str = Form(...),
    estructura: str = Form(...),
    cubierta: str = Form(...),
    fachada: str = Form(...),
    instalaciones: str = Form(...),
    calidad_acabados: str = Form(...),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    datos = PliegoPortalRequest(
        nombre_proyecto=nombre_proyecto,
        arquitecto=arquitecto,
        tipo_obra=tipo_obra,
        municipio=municipio,
        provincia=provincia,
        presupuesto_pem=presupuesto_pem,
        descripcion_proyecto=descripcion_proyecto,
        estructura=estructura,
        cubierta=cubierta,
        fachada=fachada,
        instalaciones=instalaciones,
        calidad_acabados=calidad_acabados,
    )

    pliego_raw = generar_pliego_ia(datos)
    pliego = normalizar_pliego(pliego_raw)

    project = create_project(
        db,
        user_id=user.id,
        nombre_proyecto=f"Pliego — {datos.nombre_proyecto}",
        tipo=TipoProyecto.pliego,
        datos_entrada=datos.model_dump(),
        estado=EstadoProyecto.completado,
    )
    project.resultado = {"secciones": pliego["secciones"]}
    db.commit()

    return templates.TemplateResponse(
        "pliego_resultado.html",
        {
            "request": request,
            "user": user,
            "icons": ICONS,
            "sidebar_items": build_sidebar_items("Pliegos"),
            "datos": datos,
            "secciones": pliego["secciones"],
            "project_id": project.id,
        },
    )


@router.post("/pliego/{project_id}/word")
def pliego_word(
    project_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    project = get_project_by_id(db, project_id, user_id=user.id)
    if project is None or project.tipo.value != "pliego" or not project.resultado:
        raise HTTPException(status_code=404, detail="Pliego no encontrado.")

    datos = project.datos_entrada or {}
    secciones = project.resultado.get("secciones", [])

    word_bytes = construir_word(datos, secciones)

    nombre_archivo = f"pliego_{(datos.get('nombre_proyecto') or 'pliego').strip().replace(' ', '_')}.docx"
    return Response(
        content=word_bytes,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f'attachment; filename="{nombre_archivo}"'},
    )
