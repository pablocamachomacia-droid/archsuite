import json
from datetime import date
from typing import Annotated, List, Optional

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, Response
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from sqlalchemy.orm import Session

from auth import get_current_user
from database import create_project, get_db
from models import EstadoProyecto, TipoProyecto, User
from nav import ICONS, build_sidebar_items
from presupuesto_ai import calcular_totales, construir_excel, generar_presupuesto_ia, normalizar_capitulos

router = APIRouter(tags=["presupuesto"])
templates = Jinja2Templates(directory="templates")


class PresupuestoPortalRequest(BaseModel):
    nombre_proyecto: str
    direccion: str
    promotor: str
    arquitecto: str
    fecha: str

    tipologia: str
    superficie_construida: float
    num_plantas: int
    calidad_acabados: str

    instalaciones: List[str] = []
    observaciones: Optional[str] = ""


@router.get("/presupuesto", response_class=HTMLResponse)
def presupuesto_form(request: Request, user: User = Depends(get_current_user)):
    return templates.TemplateResponse(
        "presupuesto.html",
        {
            "request": request,
            "user": user,
            "icons": ICONS,
            "sidebar_items": build_sidebar_items("Presupuestos"),
            "hoy": date.today().isoformat(),
        },
    )


@router.post("/presupuesto/generar", response_class=HTMLResponse)
def presupuesto_generar(
    request: Request,
    nombre_proyecto: str = Form(...),
    direccion: str = Form(...),
    promotor: str = Form(...),
    arquitecto: str = Form(...),
    fecha: str = Form(...),
    tipologia: str = Form(...),
    superficie_construida: float = Form(...),
    num_plantas: int = Form(...),
    calidad_acabados: str = Form(...),
    observaciones: str = Form(""),
    instalaciones: Annotated[List[str], Form()] = [],
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    datos = PresupuestoPortalRequest(
        nombre_proyecto=nombre_proyecto,
        direccion=direccion,
        promotor=promotor,
        arquitecto=arquitecto,
        fecha=fecha,
        tipologia=tipologia,
        superficie_construida=superficie_construida,
        num_plantas=num_plantas,
        calidad_acabados=calidad_acabados,
        instalaciones=instalaciones,
        observaciones=observaciones,
    )

    capitulos_raw = generar_presupuesto_ia(datos)
    capitulos = normalizar_capitulos(capitulos_raw)
    totales = calcular_totales(capitulos)

    project = create_project(
        db,
        user_id=user.id,
        nombre_proyecto=datos.nombre_proyecto,
        tipo=TipoProyecto.presupuesto,
        datos_entrada=datos.model_dump(),
        estado=EstadoProyecto.completado,
    )
    project.resultado = {"capitulos": capitulos, "totales": totales}
    db.commit()

    contexto_completo = {"datos": datos.model_dump(), "capitulos": capitulos, "totales": totales}

    return templates.TemplateResponse(
        "presupuesto_resultado.html",
        {
            "request": request,
            "user": user,
            "icons": ICONS,
            "sidebar_items": build_sidebar_items("Presupuestos"),
            "datos": datos,
            "capitulos": capitulos,
            "totales": totales,
            "datos_json": json.dumps(contexto_completo, ensure_ascii=False),
            "es_mock": False,
        },
    )


@router.post("/presupuesto/excel")
def presupuesto_excel(
    datos_json: str = Form(...),
    user: User = Depends(get_current_user),
):
    try:
        contexto = json.loads(datos_json)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Datos del presupuesto no válidos.")

    excel_bytes = construir_excel(contexto)

    nombre_archivo = f"presupuesto_{contexto['datos']['nombre_proyecto'].strip().replace(' ', '_')}.xlsx"
    return Response(
        content=excel_bytes,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{nombre_archivo}"'},
    )
