"""Contrato fijo de Forecast_mann_scenario_test4 (unidades)."""

from datetime import date

# Historia mensual cerrada y horizonte que ya viene pronosticado en la planilla.
HISTORIA_DESDE = date(2017, 1, 1)
HISTORIA_HASTA = date(2026, 10, 1)
PRONOSTICO_DESDE = date(2026, 11, 1)
PRONOSTICO_HASTA = date(2027, 12, 1)

N_FILAS = 4402
N_MESES = 132
N_MESES_HISTORIA = 118
N_MESES_PRONOSTICO = 14

COLUMNAS_META = (
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

MODELOS = frozenset(
    {"auto_SARIMA", "holtsWintersExponentialSmoothing", "prophet"}
)
TIPOS_DEMANDA = frozenset(
    {"Con tendencia", "Erratica", "Intermitente", "Variable moderada"}
)
CLUSTERS = frozenset({"Alto riesgo", "Bajo riesgo", "Mediano riesgo"})
ABC = frozenset({"A", "B", "C"})
REGIONES = frozenset({"MTO", "MTS", "VSF", "REV", "BLOQUEADO"})
CLIENTES = frozenset({"MANN-FILTER", "WIX"})
CATEGORIAS = frozenset({"PC", "OHI", "CV", "Pick up", "PICK UP", "IF", "LCV"})

# Desviacion Std de la planilla = desviación poblacional (N=12) de la
# historia de nov-2025 a oct-2026. Tolerancia por el redondeo a 2 decimales.
TOLERANCIA_STD = 0.02
# Un pronóstico candidato coincide con la planilla si cada mes difiere menos que esto.
TOLERANCIA_PRONOSTICO = 0.01

FIXTURE = "fixtures/planilla_estandar.csv"
MUESTRA = "fixtures/planilla_estandar_muestra.csv"
