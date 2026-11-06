"""Compara dos planillas alineando por product_id.

Una diferencia de formato (``1,5`` contra ``1,50``) no es una diferencia de valor.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from planilla.schema import EXPECTED_HEADER
from planilla.sheet import Sheet
from planilla.validate import parse_number

_SAMPLE_LIMIT = 12


@dataclass
class CellDiff:
    product_id: str
    column: str
    left: str
    right: str
    kind: str  # "valor" | "formato" | "fila"


@dataclass
class DiffReport:
    missing_right: list[str] = field(default_factory=list)
    missing_left: list[str] = field(default_factory=list)
    value_diffs: list[CellDiff] = field(default_factory=list)
    format_diffs: list[CellDiff] = field(default_factory=list)
    value_count: int = 0
    format_count: int = 0
    comparable_rows: int = 0

    @property
    def ok(self) -> bool:
        return self.value_count == 0 and not self.missing_right and not self.missing_left


def diff_sheets(left: Sheet, right: Sheet) -> DiffReport:
    """``left`` es el candidato y ``right`` la planilla de referencia."""
    report = DiffReport()
    if left.header != list(EXPECTED_HEADER) or right.header != list(EXPECTED_HEADER):
        report.value_diffs.append(
            CellDiff(
                product_id="",
                column="header",
                left="|".join(left.header[:4]),
                right="|".join(right.header[:4]),
                kind="valor",
            )
        )
        report.value_count += 1
        return report

    left_by_id = _index(left)
    right_by_id = _index(right)
    report.missing_right = sorted(set(left_by_id) - set(right_by_id))
    report.missing_left = sorted(set(right_by_id) - set(left_by_id))
    shared = sorted(set(left_by_id) & set(right_by_id))
    report.comparable_rows = len(shared)
    text = {
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
        "ABC",
        "Modelo",
        "Reemplazado?",
        "Reemplazado por",
        "Descontinuado?",
    }
    numeric = {name for name in EXPECTED_HEADER if name not in text}

    for product_id in shared:
        left_row = left_by_id[product_id]
        right_row = right_by_id[product_id]
        for position, name in enumerate(EXPECTED_HEADER):
            if name == "product_id":
                continue
            got = left_row[position]
            exp = right_row[position]
            if got == exp:
                continue
            kind = "valor"
            if name in numeric and _same_number(got, exp):
                kind = "formato"
            item = CellDiff(product_id, name, got, exp, kind)
            if kind == "formato":
                report.format_count += 1
                if len(report.format_diffs) < _SAMPLE_LIMIT:
                    report.format_diffs.append(item)
            else:
                report.value_count += 1
                if len(report.value_diffs) < _SAMPLE_LIMIT:
                    report.value_diffs.append(item)
    return report


def _index(sheet: Sheet) -> dict[str, list[str]]:
    found: dict[str, list[str]] = {}
    for row in sheet.rows:
        if len(row) != len(sheet.header):
            continue
        found[row[0]] = row
    return found


def _same_number(left: str, right: str) -> bool:
    try:
        return parse_number(left) == parse_number(right)
    except ValueError:
        return False
