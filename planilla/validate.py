"""Reglas de contrato. Una planilla válida puede seguir teniendo defectos de negocio:
esos los reporta ``planilla.audit``."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal

from planilla.schema import (
    ABC_CLASSES,
    ATTRIBUTE_COLUMNS,
    CATEGORIES,
    CLIENTS,
    CLUSTERS,
    DEMAND_TYPES,
    EXPECTED_HEADER,
    FORECAST_LABELS,
    HISTORY_LABELS,
    MODELS,
    NON_NEGATIVE_META,
    PERCENT_COLUMNS,
    REGIONS,
    YES_NO,
)
from planilla.sheet import Sheet

_NUMBER = re.compile(r"^-?(?:0|[1-9]\d*)(?:,\d{1,2})?$")
_FORECAST_NUMBER = re.compile(r"^(?:0|[1-9]\d*)(?:,\d{1,2})?$")
_HISTORY_NUMBER = re.compile(r"^-?(?:0|[1-9]\d*)$")
_PRODUCT_ID = re.compile(r"^\d{6}$")

_SAMPLES_PER_CODE = 8

_ENUMS: dict[str, frozenset[str]] = {
    "Region": REGIONS,
    "Cliente": CLIENTS,
    "Categoria": CATEGORIES,
    "Tipo de demanda": DEMAND_TYPES,
    "Cluster": CLUSTERS,
    "ABC": ABC_CLASSES,
    "Modelo": MODELS,
    "Reemplazado?": YES_NO,
    "Descontinuado?": YES_NO,
}


@dataclass(frozen=True)
class Issue:
    severity: str
    code: str
    message: str
    row: int | None = None
    column: str | None = None
    product_id: str | None = None


@dataclass
class Report:
    issues: list[Issue] = field(default_factory=list)
    counts: dict[str, int] = field(default_factory=dict)

    def add(self, issue: Issue) -> None:
        self.counts[issue.code] = self.counts.get(issue.code, 0) + 1
        shown = sum(1 for item in self.issues if item.code == issue.code)
        if shown < _SAMPLES_PER_CODE:
            self.issues.append(issue)

    @property
    def errors(self) -> list[Issue]:
        return [item for item in self.issues if item.severity == "error"]

    @property
    def warnings(self) -> list[Issue]:
        return [item for item in self.issues if item.severity == "warning"]

    @property
    def ok(self) -> bool:
        return not any(item.severity == "error" for item in self.issues) and not any(
            code for code, count in self.counts.items() if count and code in _ERROR_CODES
        )


# Se llena con los códigos emitidos como error. ``ok`` también mira la lista.
_ERROR_CODES: set[str] = set()


def _error(report: Report, code: str, message: str, **kwargs: object) -> None:
    _ERROR_CODES.add(code)
    report.add(Issue("error", code, message, **kwargs))  # type: ignore[arg-type]


def _warning(report: Report, code: str, message: str, **kwargs: object) -> None:
    report.add(Issue("warning", code, message, **kwargs))  # type: ignore[arg-type]


def parse_number(token: str) -> Decimal:
    """Acepta el formato de la planilla: ``-12`` o ``8415,25``. Sin separador de miles."""
    if not _NUMBER.fullmatch(token):
        raise ValueError(token)
    return Decimal(token.replace(",", "."))


def validate(sheet: Sheet) -> Report:
    report = Report()
    if sheet.newline == "\n":
        _warning(
            report,
            "LINE_ENDING",
            "El export oficial usa CRLF. Este archivo usa solo LF.",
        )
    if sheet.encoding != "cp1252":
        _warning(
            report,
            "ENCODING",
            f"El export oficial está en cp1252. Este archivo se leyó como {sheet.encoding}.",
        )
    if sheet.header != list(EXPECTED_HEADER):
        expected = list(EXPECTED_HEADER)
        missing = [name for name in expected if name not in sheet.header]
        extra = [name for name in sheet.header if name not in expected]
        order = sheet.header == expected
        detail = []
        if missing:
            detail.append("faltan " + ", ".join(missing[:6]) + ("…" if len(missing) > 6 else ""))
        if extra:
            detail.append("sobran " + ", ".join(extra[:6]) + ("…" if len(extra) > 6 else ""))
        if not missing and not extra and not order:
            detail.append("las columnas están en otro orden")
        _error(
            report,
            "HEADER",
            "El encabezado no coincide con la planilla estándar"
            + (": " + "; ".join(detail) if detail else "."),
        )
        return report

    if not sheet.rows:
        _error(report, "EMPTY", "La planilla no tiene filas de datos.")
        return report

    index = sheet.column_index()
    seen_ids: dict[str, int] = {}
    seen_skus: dict[str, int] = {}
    width = len(sheet.header)

    for offset, row in enumerate(sheet.rows):
        file_row = offset + 2
        product_id = row[index["product_id"]] if row else ""
        if len(row) != width:
            _error(
                report,
                "ROW_WIDTH",
                f"La fila tiene {len(row)} columnas; el encabezado tiene {width}.",
                row=file_row,
                product_id=product_id or None,
            )
            continue
        _check_identity(report, row, index, file_row, seen_ids, seen_skus)
        _check_enums(report, row, index, file_row)
        _check_numbers(report, row, index, file_row)

    return report


def _check_identity(
    report: Report,
    row: list[str],
    index: dict[str, int],
    file_row: int,
    seen_ids: dict[str, int],
    seen_skus: dict[str, int],
) -> None:
    product_id = row[index["product_id"]]
    sku = row[index["SKU"]]
    if not _PRODUCT_ID.fullmatch(product_id):
        _error(
            report,
            "PRODUCT_ID",
            f"product_id {product_id!r} tiene que ser 6 dígitos.",
            row=file_row,
            column="product_id",
            product_id=product_id or None,
        )
    elif product_id in seen_ids:
        _error(
            report,
            "DUPLICATE_PRODUCT_ID",
            f"product_id {product_id} repetido (primera vez en la fila {seen_ids[product_id]}).",
            row=file_row,
            column="product_id",
            product_id=product_id,
        )
    else:
        seen_ids[product_id] = file_row

    if sku == "":
        _error(
            report,
            "SKU",
            "SKU vacío.",
            row=file_row,
            column="SKU",
            product_id=product_id or None,
        )
    elif sku in seen_skus:
        _error(
            report,
            "DUPLICATE_SKU",
            f"SKU {sku!r} repetido (primera vez en la fila {seen_skus[sku]}).",
            row=file_row,
            column="SKU",
            product_id=product_id or None,
        )
    else:
        seen_skus[sku] = file_row

    for name in ("Subcategoria", "Reemplazado por"):
        if row[index[name]] == "":
            _error(
                report,
                "REQUIRED_TEXT",
                f"{name} está vacío.",
                row=file_row,
                column=name,
                product_id=product_id or None,
            )


def _check_enums(report: Report, row: list[str], index: dict[str, int], file_row: int) -> None:
    product_id = row[index["product_id"]]
    for name, allowed in _ENUMS.items():
        value = row[index[name]]
        if value not in allowed:
            _error(
                report,
                "ENUM",
                f"{name}={value!r} no está en el conjunto de la planilla estándar.",
                row=file_row,
                column=name,
                product_id=product_id or None,
            )


def _check_numbers(report: Report, row: list[str], index: dict[str, int], file_row: int) -> None:
    product_id = row[index["product_id"]]
    for name in ("Error", "Promedio", "Desviacion Std", "Coeficiente", *PERCENT_COLUMNS, "Precio Unitario", "Costo Unitario"):
        token = row[index[name]]
        if not _NUMBER.fullmatch(token):
            _error(
                report,
                "NUMBER_FORMAT",
                f"{name}={token!r} no es un número de la planilla (coma decimal, hasta 2 decimales, sin separador de miles).",
                row=file_row,
                column=name,
                product_id=product_id or None,
            )
            continue
        value = Decimal(token.replace(",", "."))
        if name in NON_NEGATIVE_META and value < 0:
            _error(
                report,
                "NEGATIVE_META",
                f"{name}={token} no puede ser negativo.",
                row=file_row,
                column=name,
                product_id=product_id or None,
            )
        if name == "Error" and value > 100:
            _error(
                report,
                "ERROR_RANGE",
                f"Error={token} está fuera de 0 a 100.",
                row=file_row,
                column="Error",
                product_id=product_id or None,
            )

    for label in EXPECTED_HEADER:
        if label in ATTRIBUTE_COLUMNS:
            continue
        token = row[index[label]]
        if label in HISTORY_LABELS:
            if not _HISTORY_NUMBER.fullmatch(token):
                _error(
                    report,
                    "HISTORY_FORMAT",
                    f"El real {label}={token!r} tiene que ser un entero (la coma decimal arranca en el pronóstico).",
                    row=file_row,
                    column=label,
                    product_id=product_id or None,
                )
        elif label in FORECAST_LABELS:
            if not _FORECAST_NUMBER.fullmatch(token):
                _error(
                    report,
                    "FORECAST_FORMAT",
                    f"El pronóstico {label}={token!r} tiene que ser >= 0, con coma decimal y hasta 2 decimales.",
                    row=file_row,
                    column=label,
                    product_id=product_id or None,
                )
