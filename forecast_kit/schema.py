"""Contract of the standard Mann/WIX forecast spreadsheet.

Other agents should import these constants instead of rediscovering
column names, encodings, and the actuals/forecast cut from the CSV.
"""

from __future__ import annotations

from datetime import date

DELIMITER = ";"
DATE_HEADER_FORMAT = "%d/%m/%Y"
# Source export is Windows/Latin-1 (byte 0xA1 in descriptions). Prefer this
# then UTF-8 so both the original file and converted fixtures parse.
ENCODINGS = ("utf-8-sig", "cp1252", "latin-1")

META_COLUMNS = (
    "product_id",
    "Familia",
    "Region",
    "Vendedor",
    "Cliente",
    "Categoria",
    "Subcategoria",
    "SKU",
    "Descripcion",
    "Tipo de demanda",
    "Cluster",
    "Error",
    "ABC",
    "Promedio",
    "Desviacion Std",
    "Coeficiente",
    "YTD",
    "QTD",
    "MTD",
    "FYTD",
    "YTG",
    "QTG",
    "MTG",
    "FYTG",
    "Modelo",
    "Precio Unitario",
    "Costo Unitario",
    "Reemplazado?",
    "Reemplazado por",
    "Descontinuado?",
)

N_META = len(META_COLUMNS)  # 30
N_MONTHS = 132
N_COLUMNS = N_META + N_MONTHS  # 162

HISTORY_START = date(2017, 1, 1)
HISTORY_END = date(2026, 10, 1)
FORECAST_START = date(2026, 11, 1)
FORECAST_END = date(2027, 12, 1)
N_HISTORY_MONTHS = 118  # Jan 2017 .. Oct 2026
N_FORECAST_MONTHS = 14  # Nov 2026 .. Dec 2027

REQUIRED_NONEMPTY = ("product_id", "SKU", "Region", "Cliente", "Categoria", "Modelo")

KNOWN_MODELS = frozenset(
    {
        "auto_SARIMA",
        "holtsWintersExponentialSmoothing",
        "prophet",
    }
)

KNOWN_DEMAND_TYPES = frozenset(
    {
        "Con tendencia",
        "Intermitente",
        "Erratica",
        "Variable moderada",
    }
)

KNOWN_CLUSTERS = frozenset(
    {
        "Bajo riesgo",
        "Mediano riesgo",
        "Alto riesgo",
    }
)

KNOWN_ABC = frozenset({"A", "B", "C"})

KNOWN_REGIONS = frozenset({"MTO", "MTS", "VSF", "REV", "BLOQUEADO"})

KNOWN_CLIENTS = frozenset({"MANN-FILTER", "WIX"})

# Observed in the standard file. Parsers must accept both Pick up spellings.
KNOWN_CATEGORIES = frozenset(
    {"PC", "OHI", "CV", "Pick up", "PICK UP", "IF", "LCV"}
)

YES_NO = frozenset({"Si", "Sí", "No", "SI", "NO"})

GOLDEN_FULL_RELPATH = "fixtures/golden/Forecast_mann_scenario_test4_unidades.csv"
GOLDEN_MINI_RELPATH = "fixtures/golden/mini.csv"
GOLDEN_STRATIFIED_RELPATH = "fixtures/golden/stratified.csv"
GOLDEN_SHA256 = "460fc728da72c9773f6cb8751176cfa11a11b0404fa0e51f6952c7fb4f8bb9e0"
GOLDEN_N_ROWS = 4402
