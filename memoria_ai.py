"""Lógica de generación de memorias descriptivas para ArchMemoria.

Prompt portado tal cual de ../archmemoria/main.py. La única diferencia es el
modelo: el original usaba "claude-3-5-sonnet-20241022", que Anthropic retiró
el 28/10/2025 — se sustituye por "claude-sonnet-4-5" (el mismo modelo que ya
usan ArchLicencia y ArchPresupuesto en este portal).
"""

import os

from anthropic import Anthropic
from dotenv import load_dotenv
from fastapi import HTTPException

load_dotenv()

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
MODEL_NAME = "claude-sonnet-4-5"

client = Anthropic(api_key=ANTHROPIC_API_KEY) if ANTHROPIC_API_KEY else None


SYSTEM_PROMPT = """Eres un arquitecto técnico español experto en redacción de proyectos para visado colegial.
Redacta una memoria descriptiva completa, formal y técnica basada en los datos proporcionados.
El documento debe seguir el formato estándar de los Colegios de Arquitectos de España.
Usa terminología técnica correcta. Escribe en español formal.
Genera el documento completo con todos los apartados estándar:

1. Objeto del proyecto
2. Agentes de la edificación
3. Información urbanística
4. Descripción del proyecto
5. Cuadro de superficies
6. Descripción constructiva (materiales y sistemas)
7. Instalaciones
8. Cumplimiento del CTE (menciona los documentos básicos aplicables: DB-SE, DB-SI, DB-SUA, DB-HS, DB-HE, DB-HR)
9. Descripción de la obra a realizar

Devuelve el contenido EXCLUSIVAMENTE en HTML semántico (sin <html>, <head> ni <body>), usando:
- <h2> para cada uno de los 9 apartados numerados (ej: "1. Objeto del proyecto")
- <h3> para subapartados si son necesarios
- <p> para párrafos
- <ul>/<li> o <table> cuando proceda (por ejemplo, en el cuadro de superficies)
No incluyas comentarios, notas introductorias ni texto fuera del propio contenido de la memoria."""


def construir_prompt_usuario(datos) -> str:
    instalaciones_txt = ", ".join(datos.instalaciones) if datos.instalaciones else "No se especifican instalaciones"
    return f"""Datos del proyecto:

DATOS GENERALES
- Nombre del proyecto: {datos.nombre_proyecto}
- Tipo de obra: {datos.tipo_obra}
- Tipología: {datos.tipologia}
- Municipio: {datos.municipio}
- Provincia: {datos.provincia}
- Dirección: {datos.direccion}
- Referencia catastral: {datos.referencia_catastral or "No indicada"}

PROMOTOR Y TÉCNICO
- Promotor: {datos.nombre_promotor} (NIF: {datos.nif_promotor})
- Arquitecto: {datos.nombre_arquitecto} (Colegiado nº {datos.numero_colegiado})

SUPERFICIES
- Superficie de parcela: {datos.superficie_parcela} m²
- Superficie construida total: {datos.superficie_construida} m²
- Superficie útil total: {datos.superficie_util} m²
- Plantas sobre rasante: {datos.plantas_sobre_rasante}
- Plantas bajo rasante: {datos.plantas_bajo_rasante}

MATERIALES Y SISTEMAS CONSTRUCTIVOS
- Estructura: {datos.estructura}
- Cubierta: {datos.cubierta}
- Fachada: {datos.fachada}
- Carpintería exterior: {datos.carpinteria_exterior}
- Solados interiores: {datos.solados_interiores}

INSTALACIONES PREVISTAS
- {instalaciones_txt}

Redacta la memoria descriptiva completa siguiendo la estructura de 9 apartados indicada."""


def generar_memoria_ia(datos) -> str:
    if client is None:
        raise HTTPException(
            status_code=500,
            detail="No se ha configurado ANTHROPIC_API_KEY en el servidor.",
        )
    try:
        response = client.messages.create(
            model=MODEL_NAME,
            max_tokens=4096,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": construir_prompt_usuario(datos)}],
        )
        return response.content[0].text
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Error al generar la memoria con Claude: {exc}")
