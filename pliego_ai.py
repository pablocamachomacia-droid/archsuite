import os

from anthropic import Anthropic
from dotenv import load_dotenv
from fastapi import HTTPException

load_dotenv()

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
MODEL_NAME = "claude-sonnet-4-5"

client = Anthropic(api_key=ANTHROPIC_API_KEY) if ANTHROPIC_API_KEY else None

SECCIONES_ESTANDAR = [
    ("01", "Disposiciones generales"),
    ("02", "Condiciones facultativas"),
    ("03", "Condiciones económicas"),
    ("04", "Condiciones técnicas generales"),
    ("05", "Condiciones técnicas particulares"),
    ("06", "Pliego de prescripciones técnicas particulares"),
]

_SECCIONES_LISTADO = "\n".join(f"{cod} - {titulo}" for cod, titulo in SECCIONES_ESTANDAR)


SYSTEM_PROMPT = f"""Eres un arquitecto técnico español, experto en la redacción de pliegos de condiciones \
técnicas y administrativas para proyectos de arquitectura y edificación en España.

Debes generar un pliego de condiciones completo, formal y técnicamente riguroso, basado en los datos del \
proyecto proporcionados, siguiendo la estructura y la terminología habituales en los estudios de arquitectura \
españoles y tomando como referencia la Ley 38/1999 de Ordenación de la Edificación (LOE), el Código Técnico de \
la Edificación (CTE, Real Decreto 314/2006) y el Pliego General de Condiciones Técnicas de la Dirección General \
de Arquitectura (PGCT) como base habitual de las condiciones técnicas generales.

PRINCIPIOS OBLIGATORIOS:

1. ADAPTA EL CONTENIDO al tipo de obra, sistemas constructivos y calidad de acabados indicados. No generes un \
pliego genérico: las condiciones técnicas particulares (sección 05) y el pliego de prescripciones técnicas \
particulares (sección 06) deben referirse explícitamente a los sistemas constructivos y la tipología descritos \
por el usuario.

2. SÉ TÉCNICAMENTE PRECISO pero indica siempre, cuando corresponda, que los datos concretos de la obra (precios \
unitarios, plazos, garantías) son ORIENTATIVOS y deben ajustarse en el proyecto de ejecución definitivo y en el \
contrato de obra correspondiente.

3. CADA SECCIÓN DEBE DESARROLLAR ESTOS CONTENIDOS MÍNIMOS:
   - Sección 01 (Disposiciones generales): objeto del pliego, documentos que componen el proyecto (memoria, \
planos, mediciones, presupuesto, estudio de seguridad y salud), y compatibilidad y relación entre dichos \
documentos en caso de contradicción.
   - Sección 02 (Condiciones facultativas): atribuciones y obligaciones de la dirección facultativa (dirección \
de obra y dirección de ejecución), y obligaciones y responsabilidades del contratista (medios, personal, \
subcontratación, libro de órdenes, seguros).
   - Sección 03 (Condiciones económicas): criterios de valoración de precios, mediciones y abonos, \
certificaciones de obra, revisión de precios, recepción y liquidación de la obra, y plazo de garantía.
   - Sección 04 (Condiciones técnicas generales): condiciones generales de materiales, ejecución de las \
unidades de obra, y control de calidad (ensayos, recepción de materiales, pruebas de servicio), con referencia \
al CTE y a la normativa UNE/EHE que resulte de aplicación general.
   - Sección 05 (Condiciones técnicas particulares): condiciones específicas según el tipo de obra indicado \
por el usuario (p.ej. requisitos particulares de vivienda unifamiliar, edificio plurifamiliar, nave industrial, \
equipamiento público, etc.).
   - Sección 06 (Pliego de prescripciones técnicas particulares): especificaciones concretas, unidad por \
unidad, de los sistemas constructivos indicados por el usuario (estructura, cubierta, fachada, instalaciones), \
incluyendo materiales, ejecución y control de cada uno.

Genera el pliego con EXACTAMENTE estas 6 secciones, en este orden, usando estos códigos y títulos:

{_SECCIONES_LISTADO}

Para cada sección, el contenido debe devolverse en HTML semántico (sin <html>, <head> ni <body>), usando <p> \
para párrafos, <ul>/<li> para listas, y <table> con <thead>/<tbody> cuando proceda. No incluyas <h2>/<h3> dentro \
del contenido (el título de la sección ya se muestra aparte).

Devuelve el pliego EXCLUSIVAMENTE a través de la herramienta 'generar_pliego', sin texto adicional fuera de la \
llamada a la herramienta."""


PLIEGO_TOOL = {
    "name": "generar_pliego",
    "description": "Registra el pliego de condiciones técnicas y administrativas completo, con sus 6 secciones.",
    "input_schema": {
        "type": "object",
        "properties": {
            "secciones": {
                "type": "array",
                "description": "Las 6 secciones del pliego, en orden, con código de dos dígitos.",
                "items": {
                    "type": "object",
                    "properties": {
                        "codigo": {"type": "string", "description": "Código de dos dígitos, ej. '01'."},
                        "titulo": {"type": "string"},
                        "contenido_html": {"type": "string"},
                    },
                    "required": ["codigo", "titulo", "contenido_html"],
                },
            }
        },
        "required": ["secciones"],
    },
}


def construir_prompt_usuario(datos) -> str:
    return f"""Genera el pliego de condiciones técnicas y administrativas para el siguiente proyecto:

DATOS GENERALES
- Nombre del proyecto: {datos.nombre_proyecto}
- Arquitecto: {datos.arquitecto}
- Municipio: {datos.municipio}
- Provincia: {datos.provincia}
- Tipo de obra: {datos.tipo_obra}
- Presupuesto de ejecución material aproximado: {datos.presupuesto_pem} €
- Calidad de acabados: {datos.calidad_acabados}

DESCRIPCIÓN DEL PROYECTO
{datos.descripcion_proyecto}

SISTEMAS CONSTRUCTIVOS PRINCIPALES
- Estructura: {datos.estructura}
- Cubierta: {datos.cubierta}
- Fachada: {datos.fachada}
- Instalaciones: {datos.instalaciones}

Genera el pliego de condiciones completo con las 6 secciones usando la herramienta 'generar_pliego'."""


def generar_pliego_ia(datos) -> dict:
    if client is None:
        raise HTTPException(
            status_code=500,
            detail="No se ha configurado ANTHROPIC_API_KEY en el servidor.",
        )
    try:
        response = client.messages.create(
            model=MODEL_NAME,
            max_tokens=8192,
            system=SYSTEM_PROMPT,
            tools=[PLIEGO_TOOL],
            tool_choice={"type": "tool", "name": "generar_pliego"},
            messages=[{"role": "user", "content": construir_prompt_usuario(datos)}],
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Error al generar el pliego con Claude: {exc}")

    for block in response.content:
        if block.type == "tool_use" and block.name == "generar_pliego":
            return block.input

    raise HTTPException(status_code=502, detail="Claude no devolvió un pliego estructurado válido.")


def normalizar_pliego(pliego_raw: dict) -> dict:
    """Garantiza las 6 secciones en orden, incluso si la IA se desvía del esquema."""
    secciones_por_codigo = {}
    for sec in pliego_raw.get("secciones", []):
        codigo = sec.get("codigo", "")
        secciones_por_codigo[codigo] = {
            "codigo": codigo,
            "titulo": sec.get("titulo", ""),
            "contenido_html": sec.get("contenido_html", ""),
        }

    secciones = []
    for codigo, titulo_defecto in SECCIONES_ESTANDAR:
        if codigo in secciones_por_codigo:
            sec = secciones_por_codigo[codigo]
            secciones.append({
                "codigo": codigo,
                "titulo": sec["titulo"] or titulo_defecto,
                "contenido_html": sec["contenido_html"] or "<p>Sin contenido generado. Revisar manualmente.</p>",
            })
        else:
            secciones.append({
                "codigo": codigo,
                "titulo": titulo_defecto,
                "contenido_html": "<p><em>Esta sección no fue generada por la IA. Debe completarse manualmente.</em></p>",
            })

    return {"secciones": secciones}
