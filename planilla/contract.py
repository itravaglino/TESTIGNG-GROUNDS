"""Contrato de la planilla estándar de forecast (escenario test 4, unidades)."""

from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "fixtures" / "Forecast_mann_scenario_test4_unidades.csv"

ENCODING = "cp1252"
DELIMITER = ";"

# Último mes observado. Noviembre 2026 en adelante es pronóstico.
AS_OF = date(2026, 10, 1)
HISTORY_START = date(2017, 1, 1)
FORECAST_END = date(2027, 12, 1)

EXPECTED_ROWS = 4402
EXPECTED_HISTORY_MONTHS = 118
EXPECTED_FORECAST_MONTHS = 14

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

MODELOS = (
    "auto_SARIMA",
    "holtsWintersExponentialSmoothing",
    "prophet",
)
