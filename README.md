# ArchSuite

**Portal web con cinco herramientas de IA para el trabajo de estudio de un arquitecto.**

[![Python](https://img.shields.io/badge/Python-3.12%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![Claude API](https://img.shields.io/badge/Claude-Sonnet%204.5-D97757?logo=anthropic&logoColor=white)](https://www.anthropic.com/api)
[![Railway](https://img.shields.io/badge/deploy-Railway-0B0D0E?logo=railway&logoColor=white)](https://railway.app/)

Un arquitecto español dedica buena parte de su tiempo a documentos que se parecen mucho entre
proyectos: memorias descriptivas, análisis de viabilidad urbanística, pliegos, presupuestos por
capítulos, cuadros de superficies. ArchSuite reúne cinco herramientas que atacan cada uno de esos
documentos, sobre una misma base de usuarios y proyectos.

## Las cinco herramientas

| Herramienta | Qué hace | IA |
|---|---|---|
| **ArchLicencia** | Análisis de viabilidad urbanística sobre normativa municipal | Sí |
| **ArchMemoria** | Generador de memoria descriptiva de proyecto | Sí |
| **ArchPresupuesto** | Presupuesto por capítulos, exportable a Excel | Sí |
| **ArchPliego** | Pliego de condiciones, exportable a Word | Sí |
| **ArchSurface** | Medición de superficies desde un DXF de AutoCAD | No — geometría pura |

ArchSurface es la única sin IA y es deliberado: medir un plano es un problema geométrico con
respuesta correcta, y una alucinación en un cuadro de superficies es un error que acaba en el
visado. Lee las polilíneas cerradas del DXF con `ezdxf`, las clasifica por capa y emite el cuadro
en PDF, Excel y BC3.

## Arquitectura

```
main.py            arranque FastAPI, montaje de routers
routers/           12 routers: auth, dashboard, admin, perfil, projects,
                   licencia, memoria, pliego, presupuesto, surface, public
models.py          SQLAlchemy — User, Project + enums de rol/tipo/estado
auth.py            JWT (python-jose) + hashing bcrypt (passlib)
middleware.py      sesión y control de acceso
*_ai.py            un módulo por herramienta con IA; cliente Anthropic
surface_dxf.py     parseo geométrico del DXF
surface_reports.py salida PDF / Excel / BC3
templates/         20 plantillas Jinja2, herencia desde app_base.html
```

- **FastAPI + Jinja2** — server-side rendering, sin build de frontend.
- **SQLAlchemy + SQLite** — usuarios y proyectos.
- **JWT + bcrypt** — autenticación propia, con rol de administrador.
- **Claude Sonnet 4.5** — motor de los cuatro generadores documentales.
- **ezdxf / reportlab / openpyxl / python-docx** — lectura de planos y salida documental.

## Ejecutar en local

```bash
python -m venv venv
venv\Scripts\activate          # Linux/macOS: source venv/bin/activate
pip install -r requirements.txt

cp railway.env.example .env    # y rellena ANTHROPIC_API_KEY y SECRET_KEY
python -m uvicorn main:app --reload --port 8081
```

En http://127.0.0.1:8081. La base SQLite se crea sola al primer arranque.

## Variables de entorno

| Variable | Descripción |
|---|---|
| `ANTHROPIC_API_KEY` | API key de [console.anthropic.com](https://console.anthropic.com) |
| `SECRET_KEY` | Clave de firma de los JWT. Genera una con `python -c "import secrets;print(secrets.token_hex(32))"` |
| `ALGORITHM` | Algoritmo JWT (`HS256`) |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | Caducidad de sesión en minutos |
| `DATABASE_URL` | Cadena SQLAlchemy (por defecto SQLite local) |

## Despliegue

`Procfile` y `render.yaml` incluidos. En producción sobre **Railway**.

## Origen

Las herramientas nacieron como cuatro prototipos Flask independientes (`archlicencia`,
`archmemoria`, `archpresupuesto`, `archsurface`) y se refundieron aquí sobre FastAPI con
autenticación y persistencia comunes. `archsurface` se mantiene además como repositorio propio
porque su parseo de DXF tiene valor por separado.

## Licencia

MIT — ver [LICENSE](LICENSE).
