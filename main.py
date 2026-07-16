from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from database import Base, engine
from middleware import AuthMiddleware
from routers import (
    admin_router,
    auth_router,
    dashboard_router,
    licencia_router,
    memoria_router,
    perfil_router,
    pliego_router,
    presupuesto_router,
    projects_router,
    public_router,
    surface_router,
)

Base.metadata.create_all(bind=engine)

app = FastAPI(title="ArchSuite - Portal de Arquitectos")

app.add_middleware(AuthMiddleware)

app.mount("/static", StaticFiles(directory="static"), name="static")

app.include_router(public_router.router)
app.include_router(auth_router.router)
app.include_router(dashboard_router.router)
app.include_router(projects_router.router)
app.include_router(licencia_router.router)
app.include_router(memoria_router.router)
app.include_router(presupuesto_router.router)
app.include_router(surface_router.router)
app.include_router(admin_router.router)
app.include_router(perfil_router.router)
app.include_router(pliego_router.router)
