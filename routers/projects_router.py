import json

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from auth import get_current_user
from database import get_db, get_project_by_id, get_user_projects
from models import User
from nav import ICONS, build_sidebar_items
from surface_dxf import resumen_deteccion

router = APIRouter(tags=["proyectos"])
templates = Jinja2Templates(directory="templates")


@router.get("/proyectos")
def listar_proyectos(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    proyectos = get_user_projects(db, user.id)
    return [
        {
            "id": p.id,
            "nombre_proyecto": p.nombre_proyecto,
            "tipo": p.tipo.value,
            "fecha_creacion": p.fecha_creacion.isoformat(),
            "estado": p.estado.value,
            "datos_entrada": p.datos_entrada,
            "resultado": p.resultado,
            "archivo_generado": p.archivo_generado,
        }
        for p in proyectos
    ]


@router.get("/proyectos/{project_id}", response_class=HTMLResponse)
def ver_proyecto(
    project_id: int,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    project = get_project_by_id(db, project_id, user_id=user.id)
    if project is None:
        raise HTTPException(status_code=404, detail="Proyecto no encontrado.")

    context = {
        "request": request,
        "user": user,
        "icons": ICONS,
        "sidebar_items": build_sidebar_items("Mis Proyectos"),
        "project": project,
    }

    if project.tipo.value == "licencia" and project.resultado:
        context.update(
            {
                "datos": project.datos_entrada or {},
                "semaforo": project.resultado.get("semaforo", "AMARILLO"),
                "resumen_semaforo": project.resultado.get("resumen_semaforo", ""),
                "secciones": project.resultado.get("secciones", []),
            }
        )
        return templates.TemplateResponse("licencia_resultado.html", context)

    if project.tipo.value == "memoria" and project.resultado:
        context.update(
            {
                "datos": project.datos_entrada or {},
                "contenido_html": project.resultado.get("contenido_html", ""),
                "es_mock": bool(project.resultado.get("mock")),
            }
        )
        return templates.TemplateResponse("memoria_resultado.html", context)

    if project.tipo.value == "presupuesto" and project.resultado:
        datos_entrada = project.datos_entrada or {}
        capitulos = project.resultado.get("capitulos", [])
        totales = project.resultado.get("totales", {})
        context.update(
            {
                "datos": datos_entrada,
                "capitulos": capitulos,
                "totales": totales,
                "datos_json": json.dumps(
                    {"datos": datos_entrada, "capitulos": capitulos, "totales": totales},
                    ensure_ascii=False,
                ),
                "es_mock": bool(project.resultado.get("mock")),
            }
        )
        return templates.TemplateResponse("presupuesto_resultado.html", context)

    if project.tipo.value == "superficie" and project.resultado:
        datos_entrada = project.datos_entrada or {}
        spaces = project.resultado.get("spaces", [])
        context.update(
            {
                "filename": datos_entrada.get("filename", ""),
                "units": datos_entrada.get("units"),
                "project_info": datos_entrada.get("project_info", {}),
                "spaces": spaces,
                "totales": project.resultado.get("totales", {}),
                "project_id": project.id,
                "guardado": request.query_params.get("guardado") == "1",
                "deteccion": resumen_deteccion(spaces),
            }
        )
        return templates.TemplateResponse("surface_resultado.html", context)

    if project.tipo.value == "pliego" and project.resultado:
        context.update(
            {
                "datos": project.datos_entrada or {},
                "secciones": project.resultado.get("secciones", []),
                "project_id": project.id,
            }
        )
        return templates.TemplateResponse("pliego_resultado.html", context)

    return templates.TemplateResponse("proyecto_generico.html", context)
