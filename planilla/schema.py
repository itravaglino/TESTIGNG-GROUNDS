"""Contrato de la planilla estándar de forecast en unidades.

Escenario de referencia: ``forecast_mann_scenario_test4_unidades``.
La historia cierra en octubre 2026 y el horizonte de pronóstico es
noviembre 2026 a diciembre 2027. Los decimales van con coma y las
columnas se separan con punto y coma.
"""

from __future__ import annotations

from datetime import date

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

NUMERIC_META: tuple[str, ...] = (
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

HISTORY_START = date(2017, 1, 1)
HISTORY_END = date(2026, 10, 1)
FORECAST_START = date(2026, 11, 1)
FORECAST_END = date(2027, 12, 1)

# Cortes que reproducen el ABC de este escenario en los 4402 SKU.
# Entre 106.42 y 106.67, y entre 457 y 466.08, el archivo no tiene casos.
ABC_A_MIN = 466.08
ABC_B_MIN = 106.67

REGIONES = frozenset({"MTO", "MTS", "VSF", "REV", "BLOQUEADO"})
CLIENTES = frozenset({"MANN-FILTER", "WIX"})
TIPOS_DEMANDA = frozenset(
    {"Erratica", "Intermitente", "Con tendencia", "Variable moderada"}
)
CLUSTERS = frozenset({"Alto riesgo", "Mediano riesgo", "Bajo riesgo"})
ABCS = frozenset({"A", "B", "C"})
MODELOS = frozenset(
    {"auto_SARIMA", "holtsWintersExponentialSmoothing", "prophet"}
)
SI_NO = frozenset({"No", "Si", "Sí"})

CATEGORIAS_CANONICAS = frozenset({"PC", "OHI", "CV", "Pick up", "IF", "LCV"})

TRAILING_MONTHS = 12
STDEV_TOLERANCE = 0.005
PROMEDIO_TOLERANCE = 0.05
COMPARE_ATOL = 0.01
