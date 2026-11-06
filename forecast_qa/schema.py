"""Canonical Mann / WIX wide forecast export.

Other models MUST ingest this layout. Do not invent weekly long-format CSVs.
"""

from __future__ import annotations

import re
from typing import Final

DELIMITER: Final = ";"
DECIMAL: Final = ","
DATE_HEADER_RE: Final = re.compile(r"^01/\d{2}/\d{4}$")
DATE_FORMAT: Final = "%d/%m/%Y"  # first day of month, e.g. 01/11/2026

META_COLUMNS: Final[tuple[str, ...]] = (
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

NUMERIC_META: Final[frozenset[str]] = frozenset(
    {
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
    }
)

YES_NO_META: Final[frozenset[str]] = frozenset({"Reemplazado?", "Descontinuado?"})

# Default origin for this standard file: first forecast month is Nov 2026.
DEFAULT_FORECAST_START = "01/11/2026"

VERDICTS: Final[tuple[str, ...]] = ("MANTENER", "CORREGIR", "REVISAR", "DESCARTAR")

# Metrics are stored as ratios in [0, inf), never already multiplied by 100.
METRIC_SCALE: Final = "ratio"
