"""Validador de la planilla estándar de forecast en unidades.

Otros modelos pueden correr, sin instalar nada::

    python3 -m planilla check fixtures/Forecast_mann_scenario_test4_unidades.csv
    python3 -m planilla audit fixtures/Forecast_mann_scenario_test4_unidades.csv
    python3 -m planilla diff candidato.csv
    python3 -m unittest discover -s tests
"""

from planilla.audit import audit
from planilla.diff import diff_sheets
from planilla.sheet import example_sheet, read_sheet, write_sheet
from planilla.validate import parse_number, validate

__all__ = [
    "audit",
    "diff_sheets",
    "example_sheet",
    "parse_number",
    "read_sheet",
    "validate",
    "write_sheet",
]
