from typing import List

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from sqlalchemy.orm import Session

from auth import get_current_user
from database import create_project, get_db
from memoria_ai import generar_memoria_ia
from models import EstadoProyecto, TipoProyecto, User
from nav import ICONS, build_sidebar_items

router = APIRouter(tags=["memoria"])
templates = Jinja2Templates(directory="templates")


class MemoriaPortalRequest(BaseModel):
    nombre_proyecto: str
    tipo_obra: str
    tipologia: str
    municipio: str
    provincia: str
    direccion: str
    referencia_catastral: str = ""

    nombre_promotor: str
    nif_promotor: str
    nombre_arquitecto: str
    numero_colegiado: str

    superficie_parcela: float
    superficie_construida: float
    superficie_util: float
    plantas_sobre_rasante: int
    plantas_bajo_rasante: int

    estructura: str
    cubierta: str
    fachada: str
    carpinteria_exterior: str
    solados_interiores: str

    instalaciones: List[str] = []


@router.get("/memoria", response_class=HTMLResponse)
def memoria_form(request: Request, user: User = Depends(get_current_user)):
    return templates.TemplateResponse(
        "memoria.html",
        {
            "request": request,
            "user": user,
            "icons": ICONS,
            "sidebar_items": build_sidebar_items("Memorias"),
        },
    )


@router.post("/memoria/generar", response_class=HTMLResponse)
def memoria_generar(
    request: Request,
    nombre_proyecto: str = Form(...),
    tipo_obra: str = Form(...),
    tipologia: str = Form(...),
    municipio: str = Form(...),
    provincia: str = Form(...),
    direccion: str = Form(...),
    referencia_catastral: str = Form(""),
    nombre_promotor: str = Form(...),
    nif_promotor: str = Form(...),
    nombre_arquitecto: str = Form(...),
    numero_colegiado: str = Form(...),
    superficie_parcela: float = Form(...),
    superficie_construida: float = Form(...),
    superficie_util: float = Form(...),
    plantas_sobre_rasante: int = Form(...),
    plantas_bajo_rasante: int = Form(...),
    estructura: str = Form(...),
    cubierta: str = Form(...),
    fachada: str = Form(...),
    carpinteria_exterior: str = Form(...),
    solados_interiores: str = Form(...),
    instalaciones: List[str] = Form([]),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    datos = MemoriaPortalRequest(
        nombre_proyecto=nombre_proyecto,
        tipo_obra=tipo_obra,
        tipologia=tipologia,
        municipio=municipio,
        provincia=provincia,
        direccion=direccion,
        referencia_catastral=referencia_catastral,
        nombre_promotor=nombre_promotor,
        nif_promotor=nif_promotor,
        nombre_arquitecto=nombre_arquitecto,
        numero_colegiado=numero_colegiado,
        superficie_parcela=superficie_parcela,
        superficie_construida=superficie_construida,
        superficie_util=superficie_util,
        plantas_sobre_rasante=plantas_sobre_rasante,
        plantas_bajo_rasante=plantas_bajo_rasante,
        estructura=estructura,
        cubierta=cubierta,
        fachada=fachada,
        carpinteria_exterior=carpinteria_exterior,
        solados_interiores=solados_interiores,
        instalaciones=instalaciones,
    )

    contenido_html = generar_memoria_ia(datos)

    project = create_project(
        db,
        user_id=user.id,
        nombre_proyecto=datos.nombre_proyecto,
        tipo=TipoProyecto.memoria,
        datos_entrada=datos.model_dump(),
        estado=EstadoProyecto.completado,
    )
    project.resultado = {"contenido_html": contenido_html}
    db.commit()

    return templates.TemplateResponse(
        "memoria_resultado.html",
        {
            "request": request,
            "user": user,
            "icons": ICONS,
            "sidebar_items": build_sidebar_items("Memorias"),
            "datos": datos,
            "contenido_html": contenido_html,
            "es_mock": False,
        },
    )
