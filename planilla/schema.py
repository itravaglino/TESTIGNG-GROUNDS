"""Columnas y vocabularios fijos de la planilla estándar."""

from __future__ import annotations

META_COLUMNS: tuple[str, ...] = (
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

NUMERIC_META = (
    "Error",
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
    "Precio Unitario",
    "Costo Unitario",
)

DEMAND_TYPES = frozenset(
    {"Erratica", "Intermitente", "Con tendencia", "Variable moderada"}
)
CLUSTERS = frozenset({"Alto riesgo", "Mediano riesgo", "Bajo riesgo"})
ABC_CLASSES = frozenset({"A", "B", "C"})
MODELS = frozenset(
    {"auto_SARIMA", "holtsWintersExponentialSmoothing", "prophet"}
)
REGIONS = frozenset({"MTO", "MTS", "VSF", "REV", "BLOQUEADO"})
YES_NO = frozenset({"Si", "Sí", "No", "SI", "NO", "Yes", "yes", "no"})

# Alias de categoría observados; no son error de parseo.
CATEGORIA_ALIASES = {"PICK UP": "Pick up"}

DELIMITER = ";"
DECIMAL = ","
DATE_FORMAT = "%d/%m/%Y"
