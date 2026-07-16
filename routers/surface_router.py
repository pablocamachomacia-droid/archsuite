import os
import re
import tempfile

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from auth import get_current_user
from database import create_project, get_db, get_project_by_id
from models import EstadoProyecto, TipoProyecto, User
from nav import ICONS, build_sidebar_items
from surface_dxf import DXFParseError, convert_dwg_to_dxf, parse_dxf, resumen_deteccion
from surface_reports import build_bc3, build_excel, build_pdf, calcular_totales

router = APIRouter(tags=["surface"])
templates = Jinja2Templates(directory="templates")

ALLOWED_EXTENSIONS = {".dxf", ".dwg"}
MAX_UPLOAD_SIZE_MB = 25


@router.get("/surface", response_class=HTMLResponse)
def surface_form(request: Request, user: User = Depends(get_current_user)):
    return templates.TemplateResponse(
        "surface.html",
        {
            "request": request,
            "user": user,
            "icons": ICONS,
            "sidebar_items": build_sidebar_items("Mediciones"),
            "error": None,
        },
    )


@router.post("/surface/analizar", response_class=HTMLResponse)
async def surface_analizar(
    request: Request,
    archivo: UploadFile = File(...),
    proyecto: str = Form(""),
    cliente: str = Form(""),
    ubicacion: str = Form(""),
    arquitecto: str = Form(""),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    filename = archivo.filename or ""
    extension = os.path.splitext(filename)[1].lower()

    ctx = {
        "request": request,
        "user": user,
        "icons": ICONS,
        "sidebar_items": build_sidebar_items("Mediciones"),
    }

    if extension not in ALLOWED_EXTENSIONS:
        ctx["error"] = "Formato no soportado. Sube un archivo .dxf o .dwg."
        return templates.TemplateResponse("surface.html", ctx, status_code=400)

    contenido = await archivo.read()
    if len(contenido) > MAX_UPLOAD_SIZE_MB * 1024 * 1024:
        ctx["error"] = f"El archivo supera el tamaño máximo permitido ({MAX_UPLOAD_SIZE_MB} MB)."
        return templates.TemplateResponse("surface.html", ctx, status_code=413)

    fd, temp_path = tempfile.mkstemp(suffix=extension)
    dxf_temp_path = None
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(contenido)
        ruta_dxf = temp_path
        if extension == ".dwg":
            dxf_temp_path = convert_dwg_to_dxf(temp_path)
            ruta_dxf = dxf_temp_path
        spaces, layers, units_info, deteccion = parse_dxf(ruta_dxf)
    except DXFParseError as exc:
        ctx["error"] = str(exc)
        return templates.TemplateResponse("surface.html", ctx, status_code=422)
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)
        if dxf_temp_path and os.path.exists(dxf_temp_path):
            os.remove(dxf_temp_path)

    project_info = {
        "proyecto": proyecto.strip(),
        "cliente": cliente.strip(),
        "ubicacion": ubicacion.strip(),
        "arquitecto": arquitecto.strip(),
    }
    project_info = {k: v for k, v in project_info.items() if v}

    totales = calcular_totales(spaces)

    project = create_project(
        db,
        user_id=user.id,
        nombre_proyecto=project_info.get("proyecto") or filename,
        tipo=TipoProyecto.superficie,
        datos_entrada={"filename": filename, "layers": layers, "units": units_info, "project_info": project_info},
        estado=EstadoProyecto.completado,
    )
    project.resultado = {"spaces": spaces, "totales": totales}
    db.commit()

    ctx.update({
        "filename": filename,
        "units": units_info,
        "project_info": project_info,
        "spaces": spaces,
        "totales": totales,
        "project_id": project.id,
        "guardado": False,
        "deteccion": deteccion,
    })
    return templates.TemplateResponse("surface_resultado.html", ctx)


def _cargar_proyecto_superficie(project_id: int, user: User, db: Session):
    project = get_project_by_id(db, project_id, user_id=user.id)
    if project is None or project.tipo.value != "superficie" or not project.resultado:
        raise HTTPException(status_code=404, detail="Proyecto no encontrado.")
    return project


@router.get("/surface/{project_id}/excel")
def surface_excel(
    project_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    project = _cargar_proyecto_superficie(project_id, user, db)
    datos = project.datos_entrada or {}
    spaces = project.resultado.get("spaces", [])

    excel_bytes = build_excel(spaces, datos.get("filename", "plano.dxf"), datos.get("project_info"))
    base = (datos.get("filename") or "plano").rsplit(".", 1)[0]
    return Response(
        content=excel_bytes,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="informe_superficies_{base}.xlsx"'},
    )


@router.get("/surface/{project_id}/pdf")
def surface_pdf(
    project_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    project = _cargar_proyecto_superficie(project_id, user, db)
    datos = project.datos_entrada or {}
    spaces = project.resultado.get("spaces", [])

    pdf_bytes = build_pdf(spaces, datos.get("filename", "plano.dxf"), datos.get("project_info"))
    base = (datos.get("filename") or "plano").rsplit(".", 1)[0]
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="informe_superficies_{base}.pdf"'},
    )


def _safe_filename_component(text):
    """Sanea un nombre de proyecto (texto libre del usuario) para usarlo en
    un nombre de archivo de descarga."""
    cleaned = re.sub(r'[\\/:*?"<>|\r\n]+', "_", (text or "plano").strip())
    return cleaned or "plano"


@router.get("/surface/{project_id}/bc3")
def surface_bc3(
    project_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    project = _cargar_proyecto_superficie(project_id, user, db)
    spaces = project.resultado.get("spaces", [])

    bc3_bytes = build_bc3(spaces, project.datos_entrada.get("project_info") if project.datos_entrada else None)
    base = _safe_filename_component(project.nombre_proyecto)
    return Response(
        content=bc3_bytes,
        media_type="text/plain",
        headers={"Content-Disposition": f'attachment; filename="{base}_mediciones.bc3"'},
    )


CLASIFICACIONES_VALIDAS = {"construida", "util"}


@router.post("/surface/{project_id}/reclasificar")
async def surface_reclasificar(
    project_id: int,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    project = _cargar_proyecto_superficie(project_id, user, db)
    form = await request.form()

    espacios = project.resultado.get("spaces", [])
    for espacio in espacios:
        espacio_id = espacio["id"]

        nuevo_nombre = form.get(f"nombre_{espacio_id}")
        if nuevo_nombre and nuevo_nombre.strip():
            espacio["name"] = nuevo_nombre.strip()

        nueva_clasificacion = form.get(f"clasificacion_{espacio_id}")
        espacio["classification"] = (
            nueva_clasificacion if nueva_clasificacion in CLASIFICACIONES_VALIDAS else None
        )

    totales = calcular_totales(espacios)
    project.resultado = {"spaces": espacios, "totales": totales}
    db.commit()

    return RedirectResponse(f"/proyectos/{project_id}?guardado=1", status_code=303)


@router.post("/surface/{project_id}/eliminar-espacio")
async def surface_eliminar_espacio(
    project_id: int,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    project = _cargar_proyecto_superficie(project_id, user, db)
    body = await request.json()
    espacio_id = body.get("espacio_id")
    if not espacio_id:
        raise HTTPException(status_code=400, detail="Falta espacio_id.")

    espacios = project.resultado.get("spaces", [])
    nuevos_espacios = [e for e in espacios if e["id"] != espacio_id]
    if len(nuevos_espacios) == len(espacios):
        raise HTTPException(status_code=404, detail="Espacio no encontrado.")

    totales = calcular_totales(nuevos_espacios)
    project.resultado = {"spaces": nuevos_espacios, "totales": totales}
    db.commit()

    return {"totales": totales}
