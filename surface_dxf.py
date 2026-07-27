"""Extracción de espacios desde un archivo DXF.

Portado y ampliado de ../ArchSurface/core/dxf_parser.py. No usa IA: solo lee
geometría real del DXF con ezdxf y calcula áreas cerradas.

Detecta espacios de seis formas, por este orden:
1. Polilíneas cerradas directamente en el modelspace (LWPOLYLINE/POLYLINE),
   incluyendo las que no tienen el flag de cierre activado pero cuyo primer
   y último punto coinciden dentro de la tolerancia de cierre ("cierre
   automático").
2. Polilíneas cerradas dentro de bloques referenciados con INSERT, aplicando
   la transformación (posición, escala, rotación) del INSERT.
3. HATCH cuyo contorno exterior es una polilínea simple o un conjunto de
   aristas rectas, como alternativa cuando el espacio no está delimitado
   por una polilínea.
4. Entidades LINE sueltas que, encadenadas por capa, forman un contorno
   cerrado — habitual en DXFs antiguos o exportados desde Revit/ArchiCAD
   que no usan polilíneas para delimitar los espacios.
5. CIRCLE (área = pi × radio²), para patios circulares, torres, etc.
6. ELLIPSE completas (área = pi × semieje mayor × semieje menor); los arcos
   elípticos parciales se descartan.
"""

import glob
import math
import os
import shutil
import subprocess
import tempfile

import ezdxf
from ezdxf.entities import EdgePath, LineEdge, PolylinePath
from ezdxf.math import Vec2, area as polygon_area, is_point_in_polygon_2d
from ezdxf.path import make_path

CLOSED_POLYLINE_TYPES = ("LWPOLYLINE", "POLYLINE")
TEXT_TYPES = ("TEXT", "MTEXT")

# Distancia máxima (en unidades del dibujo) entre puntos al aproximar
# arcos/bulges como segmentos rectos para el cálculo de área.
FLATTEN_SAGITTA = 0.01

# Distancia (en unidades del dibujo) entre el primer y el último punto de una
# polilínea, por debajo de la cual se considera "geométricamente cerrada"
# aunque el flag de cierre del DXF no esté activado. Un mismo valor absoluto
# significa cosas muy distintas según la unidad del dibujo (0.01 es 1 cm en
# un plano en metros pero solo 0.01 mm en uno en milímetros), así que se
# ajusta según $INSUNITS en vez de usar una constante única — ver
# _resolve_close_tolerance().
CLOSE_TOLERANCE_BY_INSUNITS = {
    4: 10.0,  # milímetros -> 10 mm de tolerancia
    5: 1.0,   # centímetros -> 1 cm de tolerancia
    6: 0.01,  # metros -> 1 cm (0.01 m) de tolerancia
}
DEFAULT_CLOSE_TOLERANCE = 10.0  # unidades no declaradas o no contempladas: se asume mm

# Superficie mínima (en m², ya convertida) para que un HATCH se procese como
# espacio. Evita contar sombreados decorativos (texturas de materiales, etc.)
MIN_HATCH_AREA_M2 = 1.0

# Superficie mínima y máxima (en m², ya convertida) para que una polilínea
# cerrada (directa o dentro de un bloque) se procese como espacio. El mínimo
# descarta pilares, mobiliario y otros elementos pequeños; el máximo descarta
# el cajetín del plano u otros contornos gigantes que no son habitaciones.
MIN_POLYLINE_AREA_M2 = 0.5
MAX_POLYLINE_AREA_M2 = 10000

# Número de puntos con el que se aproximan CIRCLE/ELLIPSE a un polígono para
# el emparejamiento de etiquetas (_match_label / is_point_in_polygon_2d). No
# se usa para el área, que se calcula con la fórmula geométrica exacta.
CIRCLE_ELLIPSE_APPROX_POINTS = 32

# Tolerancia (en radianes) para considerar que un ELLIPSE es una elipse
# completa: start_param ~= 0 y end_param ~= 2*pi. Los arcos elípticos
# parciales (cualquier otro rango de parámetros) se descartan.
FULL_ELLIPSE_PARAM_TOLERANCE = 0.01

# Capas que nunca representan superficies habitables. Si el nombre de capa
# (en mayúsculas) contiene alguna de estas palabras, la polilínea se descarta
# aunque tenga un área válida.
IGNORED_LAYERS = {
    "MOBILIARIO", "MUEBLES", "FURNITURE", "COTAS", "DIMENSIONES",
    "TEXTO", "TEXT", "PILARES", "COLUMNAS", "EJES", "GRID",
    "ACOTACION", "ANNOTATIONS", "SIMBOLOS", "SYMBOLS",
}


class DXFParseError(Exception):
    pass


# Variable de entorno para apuntar a un ODAFileConverter.exe en una ruta no
# estándar (p.ej. en despliegues donde no se instala en Program Files).
ODA_CONVERTER_ENV_VAR = "ODA_FILE_CONVERTER_PATH"

# Rutas donde el instalador de ODA File Converter coloca el ejecutable. El
# nombre de la carpeta incluye la versión (p.ej. "ODAFileConverter 27.1"),
# de ahí el glob en vez de una ruta fija.
_ODA_CONVERTER_GLOBS = (
    r"C:\Program Files\ODA\ODAFileConverter*\ODAFileConverter.exe",
    r"C:\Program Files (x86)\ODA\ODAFileConverter*\ODAFileConverter.exe",
)

# Versión de AutoCAD del DXF de salida. ACAD2018 es el formato más moderno
# que ezdxf lee sin advertencias.
_ODA_OUTPUT_VERSION = "ACAD2018"
_ODA_CONVERSION_TIMEOUT_SECONDS = 120


def _find_oda_converter():
    """Localiza ODAFileConverter.exe, o None si no está instalado."""
    env_path = os.environ.get(ODA_CONVERTER_ENV_VAR)
    if env_path and os.path.isfile(env_path):
        return env_path

    for pattern in _ODA_CONVERTER_GLOBS:
        matches = glob.glob(pattern)
        if matches:
            return matches[0]

    return None


def convert_dwg_to_dxf(dwg_path):
    """Convierte un DWG a DXF usando ODA File Converter (herramienta externa
    y gratuita, no incluida en ArchSuite).

    Devuelve la ruta a un .dxf temporal que el llamante es responsable de
    borrar. Lanza DXFParseError con un mensaje legible si el conversor no
    está instalado o si la conversión falla.
    """
    exe_path = _find_oda_converter()
    if exe_path is None:
        raise DXFParseError(
            "Para procesar archivos DWG instala ODA File Converter (gratuito) "
            "desde opendesign.com"
        )

    input_dir = tempfile.mkdtemp(prefix="archsurface_dwg_in_")
    output_dir = tempfile.mkdtemp(prefix="archsurface_dwg_out_")
    try:
        shutil.copyfile(dwg_path, os.path.join(input_dir, os.path.basename(dwg_path)))

        # Argumentos posicionales de ODAFileConverter en modo batch:
        # <carpeta_entrada> <carpeta_salida> <version_salida> <tipo_salida>
        # <recursivo:0/1> <auditar:0/1> [filtro_entrada]
        try:
            resultado = subprocess.run(
                [exe_path, input_dir, output_dir, _ODA_OUTPUT_VERSION, "DXF", "0", "1", "*.dwg"],
                capture_output=True,
                text=True,
                timeout=_ODA_CONVERSION_TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired as exc:
            raise DXFParseError(
                "ODA File Converter ha tardado demasiado en convertir el archivo "
                "y la operación se ha cancelado."
            ) from exc
        except OSError as exc:
            raise DXFParseError(f"No se pudo ejecutar ODA File Converter: {exc}") from exc

        if resultado.returncode != 0:
            detalle = resultado.stderr.strip() or resultado.stdout.strip()
            raise DXFParseError(
                "ODA File Converter no pudo convertir el archivo DWG"
                + (f": {detalle}" if detalle else ".")
            )

        dxf_generados = glob.glob(os.path.join(output_dir, "*.dxf"))
        if not dxf_generados:
            raise DXFParseError(
                "ODA File Converter no generó ningún DXF. El archivo DWG podría "
                "estar corrupto o en una versión no soportada."
            )

        fd, dxf_path = tempfile.mkstemp(suffix=".dxf")
        os.close(fd)
        shutil.move(dxf_generados[0], dxf_path)
        return dxf_path
    finally:
        shutil.rmtree(input_dir, ignore_errors=True)
        shutil.rmtree(output_dir, ignore_errors=True)


def _resolve_close_tolerance(insunits_code):
    """Tolerancia de cierre automático (en unidades de dibujo) según el
    código $INSUNITS del DXF. Ver CLOSE_TOLERANCE_BY_INSUNITS."""
    return CLOSE_TOLERANCE_BY_INSUNITS.get(insunits_code, DEFAULT_CLOSE_TOLERANCE)


def _is_closed(entity):
    dxftype = entity.dxftype()
    if dxftype == "LWPOLYLINE":
        return bool(entity.closed)
    if dxftype == "POLYLINE":
        if not entity.is_2d_polyline:
            return False
        return bool(entity.is_closed)
    return False


def _is_closed_by_geometry(points, close_tolerance):
    """True si el primer y el último punto de la polilínea coinciden dentro
    de close_tolerance (en unidades de dibujo) — habitual en planos
    exportados desde Revit/ArchiCAD o dibujados sin cerrar explícitamente la
    polilínea en AutoCAD."""
    if len(points) < 3:
        return False

    inicio, fin = points[0], points[-1]
    distancia = ((inicio.x - fin.x) ** 2 + (inicio.y - fin.y) ** 2) ** 0.5
    return distancia <= close_tolerance


def _evaluate_closure(entity, points, close_tolerance):
    """Determina si una entidad debe tratarse como un espacio cerrado.

    Devuelve (cerrada, auto_cerrada). `auto_cerrada` es True cuando el flag
    de cierre del DXF no estaba activado pero la polilínea está cerrada
    geométricamente (ver _is_closed_by_geometry)."""
    if _is_closed(entity):
        return True, False

    geometricamente_cerrada = _is_closed_by_geometry(points, close_tolerance)
    return geometricamente_cerrada, geometricamente_cerrada


def _entity_geometry(entity):
    """Puntos 2D aproximados y área absoluta de una polilínea."""
    path = make_path(entity)
    points = [Vec2(p.x, p.y) for p in path.flattening(FLATTEN_SAGITTA)]
    if len(points) < 3:
        return points, 0.0
    return points, float(abs(polygon_area(points)))


def _collect_text_labels(container):
    """Recoge los textos (TEXT/MTEXT) de un contenedor de entidades (el
    modelspace o la definición de un bloque) con su punto de inserción.

    Los arquitectos suelen rotular cada estancia con un texto dentro de su
    perímetro (p.ej. "DORMITORIO 1"). Estos textos se usan luego para dar
    a cada espacio un nombre real en vez de un identificador genérico.
    """
    labels = []
    for entity in container:
        dxftype = entity.dxftype()
        if dxftype == "TEXT":
            content = entity.dxf.text.strip()
            insert = entity.dxf.insert
        elif dxftype == "MTEXT":
            content = entity.plain_text().strip()
            insert = entity.dxf.insert
        else:
            continue
        if content:
            labels.append({"point": Vec2(insert.x, insert.y), "text": content, "used": False})
    return labels


def _match_label(polygon_points, labels):
    for label in labels:
        if label["used"]:
            continue
        if is_point_in_polygon_2d(label["point"], polygon_points) >= 0:
            label["used"] = True
            return label["text"]
    return None


def _polygon_centroid(points):
    """Centroide exacto de un polígono simple (fórmula del área con signo).
    Se usa como punto de muestra para _discard_container_candidates: para
    un polígono convexo o mínimamente cóncavo, este punto siempre cae
    dentro, a diferencia de la media simple de los vértices."""
    area2 = 0.0
    cx = 0.0
    cy = 0.0
    n = len(points)
    for i in range(n):
        x0, y0 = points[i].x, points[i].y
        x1, y1 = points[(i + 1) % n].x, points[(i + 1) % n].y
        cross = x0 * y1 - x1 * y0
        area2 += cross
        cx += (x0 + x1) * cross
        cy += (y0 + y1) * cross

    if area2 == 0:
        return Vec2(sum(p.x for p in points) / n, sum(p.y for p in points) / n)

    factor = 1.0 / (3.0 * area2)
    return Vec2(cx * factor, cy * factor)


def _discard_container_candidates(candidatos):
    """Descarta candidatos cuyo polígono englobe geométricamente a otro
    candidato más pequeño (su centroide cae dentro).

    Las habitaciones de una misma planta no se solapan entre sí: si un
    polígono SÍ contiene a otro, no es una habitación real sino un contorno
    envolvente — el cajetín del plano, el límite de parcela, el perímetro
    exterior del edificio... — dibujado como polilínea cerrada en la misma
    capa que las habitaciones (típico en capa "0" de AutoCAD). Sin este
    filtro, ese contorno puede colarse como espacio (si su área cae por
    debajo de MAX_POLYLINE_AREA_M2) y además "robar" la etiqueta de texto de
    una habitación real cercana cuyo rótulo esté fuera de su polilínea pero
    dentro del contorno envolvente.

    Devuelve (candidatos_filtrados, descartados)."""
    descartados = 0
    resultado = []
    for candidato in candidatos:
        centroides_menores = [
            _polygon_centroid(otro["points"])
            for otro in candidatos
            if otro is not candidato and otro["area_dibujo"] < candidato["area_dibujo"]
        ]
        es_envolvente = any(
            is_point_in_polygon_2d(centroide, candidato["points"]) >= 0
            for centroide in centroides_menores
        )
        if es_envolvente:
            descartados += 1
            continue
        resultado.append(candidato)
    return resultado, descartados


_LAYER_NAME_SUFFIXES = {
    "UTIL",
    "UTILES",
    "CONSTRUIDA",
    "CONSTRUIDO",
    "CONSTRUIDOS",
}


def _humanize_layer(layer_name):
    """Convierte un nombre de capa técnico en un nombre legible.

    P.ej. "DORMITORIO_1_UTIL" -> "Dormitorio 1". Quita sufijos técnicos
    habituales (_UTIL, _CONSTRUIDA...) usados para clasificar capas, ya
    que no aportan nada al nombre del espacio de cara al usuario.
    """
    cleaned = layer_name.replace("_", " ").replace("-", " ").strip()
    if not cleaned:
        return None
    words = cleaned.split()
    while len(words) > 1 and words[-1].upper() in _LAYER_NAME_SUFFIXES:
        words.pop()
    formatted = [w if w.isdigit() else w.capitalize() for w in words]
    return " ".join(formatted)


def _guess_classification(layer_name):
    """Sugerencia inicial de clasificación según el nombre de la capa."""
    name = layer_name.upper()
    if "UTIL" in name:
        return "util"
    if "CONSTRU" in name:
        return "construida"
    return None


def _layer_is_ignored(layer_name, ignored_layers=IGNORED_LAYERS):
    """True si el nombre de capa (en mayúsculas) contiene alguna palabra de
    ignored_layers — mobiliario, pilares, cotas, textos, etc. que no
    representan superficies habitables aunque estén dibujados como
    polilíneas cerradas."""
    name = layer_name.upper()
    return any(palabra in name for palabra in ignored_layers)


def _from_modelspace_polylines(msp, factor, close_tolerance):
    """Candidatos a espacio: polilíneas cerradas directamente en el modelspace.

    Devuelve (candidatos, descartadas_por_capa)."""
    candidatos = []
    descartadas_por_capa = 0
    for entity in msp:
        if entity.dxftype() not in CLOSED_POLYLINE_TYPES:
            continue

        layer = entity.dxf.layer
        if _layer_is_ignored(layer):
            descartadas_por_capa += 1
            continue

        points, area_dibujo = _entity_geometry(entity)
        cerrada, auto_cerrada = _evaluate_closure(entity, points, close_tolerance)
        if not cerrada or area_dibujo <= 0:
            continue

        area_m2 = area_dibujo * factor
        if area_m2 < MIN_POLYLINE_AREA_M2 or area_m2 > MAX_POLYLINE_AREA_M2:
            continue

        candidatos.append({
            "points": points,
            "area_dibujo": area_dibujo,
            "layer": layer,
            "handle": entity.dxf.handle,
            "auto_closed": auto_cerrada,
            "from_block": False,
            "block_name": None,
            "from_hatch": False,
            "from_lines": False,
            "from_circle": False,
            "from_ellipse": False,
            "radius_m": None,
            "nombre_forzado": None,
        })
    return candidatos, descartadas_por_capa


def _from_block_inserts(msp, doc, factor, close_tolerance):
    """Candidatos a espacio: polilíneas cerradas dentro de bloques
    referenciados con INSERT, con la transformación del INSERT (posición,
    escala, rotación) aplicada — así el área ya sale correcta aunque el
    bloque esté insertado con una escala distinta de 1.

    Devuelve (candidatos, descartadas_por_capa).
    """
    candidatos = []
    descartadas_por_capa = 0
    for entity in msp:
        if entity.dxftype() != "INSERT":
            continue

        block_name = entity.dxf.name
        try:
            block = doc.blocks[block_name]
        except KeyError:
            continue

        try:
            matrix = entity.matrix44()
        except Exception:
            continue

        # Los rótulos de texto del bloque se buscan en coordenadas LOCALES
        # del bloque (sin transformar), igual que las polilíneas locales:
        # así el emparejamiento no depende de la posición/escala del INSERT.
        block_labels = _collect_text_labels(block)

        for block_entity in block:
            if block_entity.dxftype() not in CLOSED_POLYLINE_TYPES:
                continue

            layer = block_entity.dxf.layer
            if _layer_is_ignored(layer):
                descartadas_por_capa += 1
                continue

            local_points, _ = _entity_geometry(block_entity)
            cerrada, auto_cerrada = _evaluate_closure(block_entity, local_points, close_tolerance)
            if not cerrada:
                continue

            nombre_local = _match_label(local_points, block_labels)

            world_points = [Vec2(p.x, p.y) for p in matrix.transform_vertices(local_points)]
            if len(world_points) < 3:
                continue
            area_dibujo = float(abs(polygon_area(world_points)))
            if area_dibujo <= 0:
                continue

            area_m2 = area_dibujo * factor
            if area_m2 < MIN_POLYLINE_AREA_M2 or area_m2 > MAX_POLYLINE_AREA_M2:
                continue

            candidatos.append({
                "points": world_points,
                "area_dibujo": area_dibujo,
                "layer": layer,
                "handle": block_entity.dxf.handle,
                "auto_closed": auto_cerrada,
                "from_block": True,
                "block_name": block_name,
                "from_hatch": False,
                "from_lines": False,
                "from_circle": False,
                "from_ellipse": False,
                "radius_m": None,
                "nombre_forzado": nombre_local,
            })
    return candidatos, descartadas_por_capa


def _hatch_boundary_points(hatch):
    """Puntos 2D del contorno exterior (paths[0]) de un HATCH, o None si el
    contorno no es una polilínea simple o un conjunto de aristas rectas
    (se ignoran arcos, elipses y splines en el contorno para mantener el
    cálculo de área simple y fiable)."""
    boundary_paths = hatch.paths
    if not boundary_paths or len(boundary_paths) == 0:
        return None

    boundary = boundary_paths[0]

    if isinstance(boundary, PolylinePath):
        return [Vec2(v[0], v[1]) for v in boundary.vertices]

    if isinstance(boundary, EdgePath):
        points = []
        for edge in boundary.edges:
            if not isinstance(edge, LineEdge):
                return None
            points.append(Vec2(edge.start[0], edge.start[1]))
        return points

    return None


def _from_hatches(msp, factor):
    """Candidatos a espacio a partir de entidades HATCH, como alternativa
    cuando el espacio está delimitado por un sombreado en vez de por una
    polilínea. Descarta HATCHs con área menor a MIN_HATCH_AREA_M2 (ya
    convertida a m²) para evitar sombreados decorativos."""
    candidatos = []
    for entity in msp:
        if entity.dxftype() != "HATCH":
            continue

        points = _hatch_boundary_points(entity)
        if points is None or len(points) < 3:
            continue

        area_dibujo = float(abs(polygon_area(points)))
        if area_dibujo <= 0:
            continue
        if area_dibujo * factor <= MIN_HATCH_AREA_M2:
            continue

        candidatos.append({
            "points": points,
            "area_dibujo": area_dibujo,
            "layer": entity.dxf.layer,
            "handle": entity.dxf.handle,
            "auto_closed": False,
            "from_block": False,
            "block_name": None,
            "from_hatch": True,
            "from_lines": False,
            "from_circle": False,
            "from_ellipse": False,
            "radius_m": None,
            "nombre_forzado": None,
        })
    return candidatos


def _line_distance(a, b):
    """Distancia euclídea 2D entre dos puntos."""
    return ((a.x - b.x) ** 2 + (a.y - b.y) ** 2) ** 0.5


def _chain_line_segments(segments, close_tolerance):
    """Encadena segmentos LINE (start, end, handle), en cualquier orden, en
    contornos cerrados mediante un algoritmo greedy:

    - Cada cadena arranca en un segmento sin usar.
    - En cada paso se busca, entre los segmentos restantes, uno cuyo start o
      end esté a menos de close_tolerance del último punto de la cadena
      (invirtiéndolo si hace falta para que encaje) y se añade.
    - Cuando ya no hay más segmentos conectables, la cadena se acepta como
      contorno cerrado solo si su último punto queda a menos de
      close_tolerance de su primer punto; si no, se descarta.

    Devuelve una lista de (points, handle) — el handle es el de la primera
    entidad LINE de cada cadena, como referencia representativa.
    """
    restantes = list(segments)
    contornos = []

    while restantes:
        start, end, handle = restantes.pop(0)
        cadena = [start, end]

        while True:
            ultimo = cadena[-1]
            match_idx, match_punto = None, None
            for i, (s, e, _h) in enumerate(restantes):
                if _line_distance(s, ultimo) <= close_tolerance:
                    match_idx, match_punto = i, e
                    break
                if _line_distance(e, ultimo) <= close_tolerance:
                    match_idx, match_punto = i, s
                    break
            if match_idx is None:
                break
            restantes.pop(match_idx)
            cadena.append(match_punto)

        if len(cadena) >= 3 and _line_distance(cadena[0], cadena[-1]) <= close_tolerance:
            contornos.append((cadena, handle))

    return contornos


def _from_line_segments(msp, labels, factor, close_tolerance, ignored_layers):
    """Candidatos a espacio a partir de entidades LINE sueltas que, al
    encadenarlas por capa, forman un contorno cerrado — habitual en DXFs
    antiguos o exportados desde Revit/ArchiCAD que no usan polilíneas.
    Un mismo grupo de capa puede producir varios contornos (varias
    habitaciones en la misma capa).

    Devuelve (candidatos, descartadas_por_capa)."""
    segmentos_por_capa = {}
    descartadas_por_capa = 0
    for entity in msp:
        if entity.dxftype() != "LINE":
            continue

        layer = entity.dxf.layer
        if _layer_is_ignored(layer, ignored_layers):
            descartadas_por_capa += 1
            continue

        start = Vec2(entity.dxf.start.x, entity.dxf.start.y)
        end = Vec2(entity.dxf.end.x, entity.dxf.end.y)
        segmentos_por_capa.setdefault(layer, []).append((start, end, entity.dxf.handle))

    candidatos = []
    for layer, segmentos in segmentos_por_capa.items():
        for points, handle in _chain_line_segments(segmentos, close_tolerance):
            area_dibujo = float(abs(polygon_area(points)))
            if area_dibujo <= 0:
                continue

            area_m2 = area_dibujo * factor
            if area_m2 < MIN_POLYLINE_AREA_M2 or area_m2 > MAX_POLYLINE_AREA_M2:
                continue

            nombre_forzado = _match_label(points, labels)

            candidatos.append({
                "points": points,
                "area_dibujo": area_dibujo,
                "layer": layer,
                "handle": handle,
                "auto_closed": False,
                "from_block": False,
                "block_name": None,
                "from_hatch": False,
                "from_lines": True,
                "from_circle": False,
                "from_ellipse": False,
                "radius_m": None,
                "nombre_forzado": nombre_forzado,
            })
    return candidatos, descartadas_por_capa


def _circle_polygon(center, radius, num_points=CIRCLE_ELLIPSE_APPROX_POINTS):
    """Aproxima un CIRCLE a un polígono de num_points puntos (para
    _match_label / is_point_in_polygon_2d — el área se calcula aparte con
    la fórmula exacta pi*r^2)."""
    return [
        Vec2(
            center.x + radius * math.cos(2 * math.pi * i / num_points),
            center.y + radius * math.sin(2 * math.pi * i / num_points),
        )
        for i in range(num_points)
    ]


def _ellipse_is_full(entity, tolerance=FULL_ELLIPSE_PARAM_TOLERANCE):
    """True si el ELLIPSE es una elipse completa (start_param ~= 0 y
    end_param ~= 2*pi) y no un arco elíptico parcial."""
    return (
        abs(entity.dxf.start_param) <= tolerance
        and abs(entity.dxf.end_param - 2 * math.pi) <= tolerance
    )


def _from_circles_and_ellipses(msp, labels, factor, ignored_layers):
    """Candidatos a espacio a partir de entidades CIRCLE y ELLIPSE (patios
    circulares, torres, salas de exposición...). Solo se procesan elipses
    completas; los arcos elípticos parciales se descartan.

    Devuelve (candidatos, descartadas_por_capa)."""
    candidatos = []
    descartadas_por_capa = 0

    for entity in msp:
        if entity.dxftype() != "CIRCLE":
            continue

        layer = entity.dxf.layer
        if _layer_is_ignored(layer, ignored_layers):
            descartadas_por_capa += 1
            continue

        radio = entity.dxf.radius
        area_dibujo = math.pi * radio ** 2
        area_m2 = area_dibujo * factor
        if area_m2 < MIN_POLYLINE_AREA_M2 or area_m2 > MAX_POLYLINE_AREA_M2:
            continue

        center = entity.dxf.center
        points = _circle_polygon(Vec2(center.x, center.y), radio)
        nombre_forzado = _match_label(points, labels)
        radio_m = radio * math.sqrt(factor)

        candidatos.append({
            "points": points,
            "area_dibujo": area_dibujo,
            "layer": layer,
            "handle": entity.dxf.handle,
            "auto_closed": False,
            "from_block": False,
            "block_name": None,
            "from_hatch": False,
            "from_lines": False,
            "from_circle": True,
            "from_ellipse": False,
            "radius_m": round(radio_m, 2),
            "nombre_forzado": nombre_forzado,
        })

    for entity in msp:
        if entity.dxftype() != "ELLIPSE":
            continue

        layer = entity.dxf.layer
        if _layer_is_ignored(layer, ignored_layers):
            descartadas_por_capa += 1
            continue

        if not _ellipse_is_full(entity):
            continue

        semieje_mayor = entity.dxf.major_axis.magnitude
        semieje_menor = entity.dxf.ratio * semieje_mayor
        area_dibujo = math.pi * semieje_mayor * semieje_menor
        area_m2 = area_dibujo * factor
        if area_m2 < MIN_POLYLINE_AREA_M2 or area_m2 > MAX_POLYLINE_AREA_M2:
            continue

        params = [2 * math.pi * i / CIRCLE_ELLIPSE_APPROX_POINTS for i in range(CIRCLE_ELLIPSE_APPROX_POINTS)]
        points = [Vec2(p.x, p.y) for p in entity.vertices(params)]
        nombre_forzado = _match_label(points, labels)

        candidatos.append({
            "points": points,
            "area_dibujo": area_dibujo,
            "layer": layer,
            "handle": entity.dxf.handle,
            "auto_closed": False,
            "from_block": False,
            "block_name": None,
            "from_hatch": False,
            "from_lines": False,
            "from_circle": False,
            "from_ellipse": True,
            "radius_m": None,
            "nombre_forzado": nombre_forzado,
        })

    return candidatos, descartadas_por_capa


def parse_dxf(file_path):
    """Lee un DXF y devuelve (espacios, capas, unidades, resumen_deteccion).

    espacios: lista de dicts {id, name, layer, area, classification,
        auto_closed, from_block, block_name, from_hatch, from_lines,
        from_circle, from_ellipse, radius_m} — el área ya viene convertida
        a m² según la unidad de dibujo declarada en el DXF. `radius_m` solo
        tiene valor (redondeado a 2 decimales) para espacios `from_circle`.
    capas: lista ordenada de nombres de capa presentes en los espacios.
    unidades: dict {label, insunits_code, factor_conversion, factor_label,
        asumido} con la información de conversión usada.
    resumen_deteccion: dict {directas, bloques, hatches, auto_cerradas,
        desde_lineas, desde_circulos, desde_elipses, descartadas_capa,
        descartadas_envolvente} con el recuento de espacios detectados por
        cada vía, de geometrías descartadas por estar en una capa de
        IGNORED_LAYERS y de candidatos descartados por ser un contorno
        envolvente de otro candidato más pequeño (ver
        _discard_container_candidates). `descartadas_capa` y
        `descartadas_envolvente` solo están disponibles al analizar el DXF
        original — no se recalculan al volver a ver un proyecto ya
        guardado, porque esa información no forma parte de los espacios
        persistidos.
    """
    try:
        doc = ezdxf.readfile(file_path)
    except IOError as exc:
        raise DXFParseError(f"No se pudo abrir el archivo: {exc}") from exc
    except ezdxf.DXFStructureError as exc:
        raise DXFParseError(
            "El archivo DXF está corrupto o tiene una estructura inválida."
        ) from exc

    msp = doc.modelspace()
    units_info = _resolve_units(doc)
    factor = units_info["factor_conversion"]
    close_tolerance = _resolve_close_tolerance(units_info["insunits_code"])
    labels = _collect_text_labels(msp)

    candidatos_directos, descartes_directos = _from_modelspace_polylines(msp, factor, close_tolerance)
    candidatos_bloques, descartes_bloques = _from_block_inserts(msp, doc, factor, close_tolerance)
    candidatos_lineas, descartes_lineas = _from_line_segments(msp, labels, factor, close_tolerance, IGNORED_LAYERS)
    candidatos_curvos, descartes_curvos = _from_circles_and_ellipses(msp, labels, factor, IGNORED_LAYERS)
    descartadas_capa = descartes_directos + descartes_bloques + descartes_lineas + descartes_curvos

    candidatos = []
    candidatos.extend(candidatos_directos)
    candidatos.extend(candidatos_bloques)
    candidatos.extend(_from_hatches(msp, factor))
    candidatos.extend(candidatos_lineas)
    candidatos.extend(candidatos_curvos)

    candidatos, descartadas_envolvente = _discard_container_candidates(candidatos)

    if not candidatos:
        raise DXFParseError(
            "No se encontraron espacios en el plano. Verifica que las superficies "
            "estén dibujadas como polilíneas cerradas (LWPOLYLINE/POLYLINE), "
            "bloques con polilíneas, sombreados (HATCH) de más de 1 m², líneas "
            "sueltas que formen un contorno cerrado, o CIRCLE/ELLIPSE."
        )

    spaces = []
    for counter, candidato in enumerate(candidatos, start=1):
        layer = candidato["layer"]
        name = (
            candidato["nombre_forzado"]
            or _match_label(candidato["points"], labels)
            or _humanize_layer(layer)
            or f"Espacio {counter}"
        )
        spaces.append({
            "id": f"ESP-{counter:03d}",
            "name": name,
            "handle": candidato["handle"],
            "layer": layer,
            "area": round(candidato["area_dibujo"] * factor, 2),
            "classification": _guess_classification(layer),
            "auto_closed": candidato["auto_closed"],
            "from_block": candidato["from_block"],
            "block_name": candidato["block_name"],
            "from_hatch": candidato["from_hatch"],
            "from_lines": candidato["from_lines"],
            "from_circle": candidato["from_circle"],
            "from_ellipse": candidato["from_ellipse"],
            "radius_m": candidato["radius_m"],
        })

    layers = sorted({s["layer"] for s in spaces})
    resumen = resumen_deteccion(spaces)
    resumen["descartadas_capa"] = descartadas_capa
    resumen["descartadas_envolvente"] = descartadas_envolvente
    return spaces, layers, units_info, resumen


def resumen_deteccion(spaces):
    """Recuento de espacios detectados por cada vía, para mostrarlo en la
    interfaz. Se deriva de los flags ya guardados en cada espacio, así que
    también puede recalcularse al volver a ver un proyecto guardado."""
    return {
        "directas": sum(
            1 for s in spaces
            if not s.get("from_block") and not s.get("from_hatch") and not s.get("from_lines")
            and not s.get("from_circle") and not s.get("from_ellipse")
        ),
        "bloques": sum(1 for s in spaces if s.get("from_block")),
        "hatches": sum(1 for s in spaces if s.get("from_hatch")),
        "auto_cerradas": sum(1 for s in spaces if s.get("auto_closed")),
        "desde_lineas": sum(1 for s in spaces if s.get("from_lines")),
        "desde_circulos": sum(1 for s in spaces if s.get("from_circle")),
        "desde_elipses": sum(1 for s in spaces if s.get("from_ellipse")),
    }


UNIT_LABELS = {
    0: "sin especificar",
    1: "pulgadas",
    2: "pies",
    4: "mm",
    5: "cm",
    6: "m",
    8: "km",
}

# Factor por el que se multiplica el área calculada en "unidades de dibujo al
# cuadrado" para obtener metros cuadrados reales, según el código $INSUNITS
# declarado en la cabecera del DXF.
AREA_CONVERSION_FACTORS = {
    1: 0.0254 ** 2,     # pulgadas
    2: 0.3048 ** 2,     # pies
    4: 1 / 1_000_000,   # milímetros
    5: 1 / 10_000,      # centímetros
    6: 1.0,             # metros (sin conversión)
    8: 1_000_000.0,     # kilómetros
}

FACTOR_DESCRIPTIONS = {
    1: "1 pulgada² = 0,00064516 m²",
    2: "1 pie² = 0,09290304 m²",
    4: "1 mm² = 0,000001 m²",
    5: "1 cm² = 0,0001 m²",
    6: "Sin conversión (ya en m²)",
    8: "1 km² = 1.000.000 m²",
}


def _resolve_units(doc):
    """Determina la unidad de dibujo declarada en el DXF ($INSUNITS) y el
    factor de conversión de área a m².

    Si el DXF no declara unidades ($INSUNITS = 0 — habitual en exportaciones
    poco cuidadas desde AutoCAD), se asume que el plano está en milímetros,
    la unidad más habitual en España, y se marca `asumido=True` para que la
    interfaz muestre un aviso al usuario.
    """
    try:
        code = doc.header.get("$INSUNITS", 0)
    except Exception:
        code = 0

    asumido = code == 0
    codigo_factor = 4 if asumido else code  # sin definir -> se asume mm
    factor = AREA_CONVERSION_FACTORS.get(codigo_factor, 1.0)

    return {
        "label": UNIT_LABELS.get(code, "sin especificar"),
        "insunits_code": code,
        "factor_conversion": factor,
        "factor_label": FACTOR_DESCRIPTIONS.get(codigo_factor, "Sin conversión (ya en m²)"),
        "asumido": asumido,
    }
