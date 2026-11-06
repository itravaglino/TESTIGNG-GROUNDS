"""Contrato de la planilla estándar de unidades (escenario test 4).

El archivo de referencia es
``fixtures/Forecast_mann_scenario_test4_unidades.csv``.
"""

from __future__ import annotations

from datetime import date

# Último mes con unidades reales. El primer mes de pronóstico es el siguiente.
AS_OF = date(2026, 10, 1)
SERIES_START = date(2017, 1, 1)
SERIES_END = date(2027, 12, 1)

ATTRIBUTE_COLUMNS: tuple[str, ...] = (
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

PERCENT_COLUMNS: tuple[str, ...] = (
    "YTD",
    "QTD",
    "MTD",
    "FYTD",
    "YTG",
    "QTG",
    "MTG",
    "FYTG",
)

NON_NEGATIVE_META: tuple[str, ...] = (
    "Error",
    "Promedio",
    "Desviacion Std",
    "Coeficiente",
    "Precio Unitario",
    "Costo Unitario",
)

DEMAND_TYPES: frozenset[str] = frozenset(
    {"Erratica", "Intermitente", "Con tendencia", "Variable moderada"}
)
CLUSTERS: frozenset[str] = frozenset(
    {"Alto riesgo", "Mediano riesgo", "Bajo riesgo"}
)
# Combinaciones observadas. Cualquier otra es válida en el contrato
# y queda marcada en la auditoría.
TYPICAL_CLUSTERS: dict[str, frozenset[str]] = {
    "Erratica": frozenset({"Alto riesgo"}),
    "Intermitente": frozenset({"Mediano riesgo", "Bajo riesgo"}),
    "Con tendencia": frozenset({"Mediano riesgo", "Bajo riesgo"}),
    "Variable moderada": frozenset({"Mediano riesgo", "Bajo riesgo"}),
}
ABC_CLASSES: frozenset[str] = frozenset({"A", "B", "C"})
MODELS: frozenset[str] = frozenset(
    {"auto_SARIMA", "holtsWintersExponentialSmoothing", "prophet"}
)
CLIENTS: frozenset[str] = frozenset({"MANN-FILTER", "WIX"})
REGIONS: frozenset[str] = frozenset({"MTO", "MTS", "VSF", "REV", "BLOQUEADO"})
CATEGORIES: frozenset[str] = frozenset(
    {"PC", "OHI", "CV", "Pick up", "PICK UP", "IF", "LCV"}
)
YES_NO: frozenset[str] = frozenset({"No", "Si", "Sí"})

DELIMITER = ";"
OFFICIAL_ENCODING = "cp1252"
OFFICIAL_NEWLINE = "\r\n"


def month_range(start: date, end: date) -> list[date]:
    months: list[date] = []
    year, month = start.year, start.month
    while (year, month) <= (end.year, end.month):
        months.append(date(year, month, 1))
        if month == 12:
            year += 1
            month = 1
        else:
            month += 1
    return months


def month_label(day: date) -> str:
    return day.strftime("%d/%m/%Y")


def _next_month(day: date) -> date:
    if day.month == 12:
        return date(day.year + 1, 1, 1)
    return date(day.year, day.month + 1, 1)


SERIES_MONTHS: tuple[date, ...] = tuple(month_range(SERIES_START, SERIES_END))
HISTORY_MONTHS: tuple[date, ...] = tuple(month_range(SERIES_START, AS_OF))
FORECAST_MONTHS: tuple[date, ...] = tuple(month_range(_next_month(AS_OF), SERIES_END))

EXPECTED_HEADER: tuple[str, ...] = ATTRIBUTE_COLUMNS + tuple(
    month_label(day) for day in SERIES_MONTHS
)

HISTORY_LABELS: frozenset[str] = frozenset(month_label(day) for day in HISTORY_MONTHS)
FORECAST_LABELS: frozenset[str] = frozenset(month_label(day) for day in FORECAST_MONTHS)
