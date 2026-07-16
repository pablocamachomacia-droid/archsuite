import os

from anthropic import Anthropic
from dotenv import load_dotenv
from fastapi import HTTPException

load_dotenv()

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
MODEL_NAME = "claude-sonnet-4-5"

client = Anthropic(api_key=ANTHROPIC_API_KEY) if ANTHROPIC_API_KEY else None

SEMAFOROS_VALIDOS = {"VERDE", "AMARILLO", "ROJO"}

SECCIONES_ESTANDAR = [
    ("01", "Identificación del solar y datos catastrales"),
    ("02", "Clasificación y calificación urbanística"),
    ("03", "Parámetros urbanísticos aplicables"),
    ("04", "Análisis de viabilidad"),
    ("05", "Tipo de licencia o título habilitante necesario"),
    ("06", "Documentación necesaria para el trámite"),
    ("07", "Plazos estimados de tramitación"),
    ("08", "Normativa de referencia"),
    ("09", "Alertas y restricciones"),
    ("10", "Recomendaciones del técnico IA"),
]

_SECCIONES_LISTADO = "\n".join(f"{cod} - {titulo}" for cod, titulo in SECCIONES_ESTANDAR)


SYSTEM_PROMPT = f"""Eres un arquitecto técnico y urbanista español, experto en tramitación de licencias urbanísticas \
y análisis de viabilidad de proyectos en cualquier municipio de España.

Debes analizar la viabilidad urbanística de un proyecto y generar un informe completo y estructurado según la \
legislación urbanística española (estatal y autonómica) y la normativa municipal habitual (PGOU, normas \
subsidiarias, ordenanzas).

PRINCIPIOS OBLIGATORIOS:

1. SÉ CONSERVADOR EN LA VIABILIDAD. Ante la duda, alerta de más, nunca de menos. Es preferible marcar AMARILLO \
o ROJO y recomendar consulta previa al ayuntamiento que dar una viabilidad optimista sin base sólida.

2. NO TIENES ACCESO AL PGOU CONCRETO DEL MUNICIPIO. Indícalo siempre de forma explícita y clara en el informe \
(especialmente en las secciones 02, 03 y 08). Da la respuesta más probable según la legislación autonómica \
aplicable a la provincia indicada y las prácticas urbanísticas habituales en España para el tipo de suelo y \
actuación descritos, dejando claro que son valores ORIENTATIVOS que deben verificarse con el ayuntamiento o \
consultando el planeamiento vigente antes de iniciar el trámite.

3. INCLUYE SIEMPRE normativa de referencia en la sección 08, aunque sea genérica: Ley del Suelo estatal (Real \
Decreto Legislativo 7/2015), la ley autonómica de urbanismo/ordenación del territorio que corresponda según la \
provincia indicada, el Código Técnico de la Edificación (CTE) y, si aplica, legislación de patrimonio histórico \
autonómica.

4. EL SEMÁFORO DE VIABILIDAD debe asignarse así:
   - VERDE: viable sin problemas aparentes, actuación habitual y sin restricciones detectadas.
   - AMARILLO: viable con condiciones, o existe incertidumbre relevante por falta de datos concretos del \
municipio, proximidad a protecciones, o parámetros ajustados.
   - ROJO: no viable con los datos aportados, o la actuación requiere obligatoriamente consulta previa/informe \
urbanístico municipal antes de poder afirmar nada (por ejemplo: zona protegida o casco histórico combinado con \
obra nueva o ampliación, elementos catalogados afectados, o indicios claros de incompatibilidad de uso).

Genera el informe con EXACTAMENTE estas 10 secciones, en este orden, usando estos códigos y títulos:

{_SECCIONES_LISTADO}

Para cada sección, el contenido debe devolverse en HTML semántico (sin <html>, <head> ni <body>), usando <p> \
para párrafos, <ul>/<li> para listas, y <table> con <thead>/<tbody> cuando proceda (especialmente en la sección \
03 para el cuadro de parámetros urbanísticos: edificabilidad, ocupación máxima, altura máxima, retranqueos, \
densidad). No incluyas <h2>/<h3> dentro del contenido (el título de la sección ya se muestra aparte).

Devuelve el informe EXCLUSIVAMENTE a través de la herramienta 'generar_informe_urbanistico', sin texto adicional \
fuera de la llamada a la herramienta."""


INFORME_TOOL = {
    "name": "generar_informe_urbanistico",
    "description": "Registra el informe de viabilidad urbanística completo con sus 10 secciones y el semáforo.",
    "input_schema": {
        "type": "object",
        "properties": {
            "semaforo": {
                "type": "string",
                "enum": ["VERDE", "AMARILLO", "ROJO"],
                "description": "Nivel de viabilidad urbanística global.",
            },
            "resumen_semaforo": {
                "type": "string",
                "description": "Frase breve (1-2 líneas) que justifica el semáforo asignado.",
            },
            "secciones": {
                "type": "array",
                "description": "Las 10 secciones del informe, en orden, con código de dos dígitos.",
                "items": {
                    "type": "object",
                    "properties": {
                        "codigo": {"type": "string", "description": "Código de dos dígitos, ej. '01'."},
                        "titulo": {"type": "string"},
                        "contenido_html": {"type": "string"},
                    },
                    "required": ["codigo", "titulo", "contenido_html"],
                },
            },
        },
        "required": ["semaforo", "resumen_semaforo", "secciones"],
    },
}


def construir_prompt_usuario(datos) -> str:
    return f"""Analiza la viabilidad urbanística del siguiente proyecto y genera el informe completo:

UBICACIÓN DEL SOLAR
- Dirección: {datos.direccion}
- Municipio: {datos.municipio}
- Provincia: {datos.provincia}

DATOS URBANÍSTICOS APORTADOS POR EL USUARIO
- Clasificación urbanística (según el usuario): {datos.clasificacion_urbanistica}
- Uso previsto: {datos.uso_previsto}
- Superficie del solar: {datos.superficie_solar} m²
- Edificabilidad prevista: {datos.edificabilidad} m² techo

DESCRIPCIÓN DEL PROYECTO
{datos.descripcion_proyecto}

Genera el informe de viabilidad urbanística completo con las 10 secciones y el semáforo usando la herramienta \
'generar_informe_urbanistico'."""


def generar_informe_ia(datos) -> dict:
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
            tools=[INFORME_TOOL],
            tool_choice={"type": "tool", "name": "generar_informe_urbanistico"},
            messages=[{"role": "user", "content": construir_prompt_usuario(datos)}],
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Error al generar el informe con Claude: {exc}")

    for block in response.content:
        if block.type == "tool_use" and block.name == "generar_informe_urbanistico":
            return block.input

    raise HTTPException(status_code=502, detail="Claude no devolvió un informe estructurado válido.")


def normalizar_informe(informe_raw: dict) -> dict:
    """Garantiza las 10 secciones en orden y un semáforo válido, incluso si la IA se desvía del esquema."""
    secciones_por_codigo = {}
    for sec in informe_raw.get("secciones", []):
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

    semaforo = str(informe_raw.get("semaforo", "")).upper()
    if semaforo not in SEMAFOROS_VALIDOS:
        semaforo = "AMARILLO"
        resumen_semaforo = "No se pudo determinar el semáforo de forma fiable; revisar el informe manualmente."
    else:
        resumen_semaforo = informe_raw.get("resumen_semaforo", "")

    return {
        "semaforo": semaforo,
        "resumen_semaforo": resumen_semaforo,
        "secciones": secciones,
    }
