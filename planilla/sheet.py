"""Carga de la planilla: cp1252, separador ';', decimales con coma."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from planilla.contract import (
    AS_OF,
    DELIMITER,
    ENCODING,
    FIXTURE,
    META_COLUMNS,
)


def parse_number(raw: str) -> float:
    text = raw.strip().replace(" ", "")
    if text == "":
        raise ValueError("vacío")
    if "," in text and "." in text:
        text = text.replace(".", "").replace(",", ".")
    elif "," in text:
        text = text.replace(",", ".")
    return float(text)


def parse_month(label: str) -> date:
    return datetime.strptime(label.strip(), "%d/%m/%Y").date()


@dataclass(frozen=True)
class Row:
    product_id: str
    sku: str
    meta: dict[str, str]
    series: tuple[float, ...]

    def number(self, column: str) -> float:
        return parse_number(self.meta[column])

    def history(self, n_history: int) -> tuple[float, ...]:
        return self.series[:n_history]

    def forecast(self, n_history: int) -> tuple[float, ...]:
        return self.series[n_history:]


@dataclass(frozen=True)
class Sheet:
    path: Path
    months: tuple[date, ...]
    rows: tuple[Row, ...]

    @property
    def history_months(self) -> tuple[date, ...]:
        return tuple(month for month in self.months if month <= AS_OF)

    @property
    def forecast_months(self) -> tuple[date, ...]:
        return tuple(month for month in self.months if month > AS_OF)

    @property
    def by_product_id(self) -> dict[str, Row]:
        return {row.product_id: row for row in self.rows}

    @property
    def by_sku(self) -> dict[str, Row]:
        return {row.sku: row for row in self.rows}


def load(path: Path | None = None) -> Sheet:
    source = Path(path) if path is not None else FIXTURE
    text = source.read_bytes().decode(ENCODING)
    reader = csv.reader(text.splitlines(), delimiter=DELIMITER)
    header = next(reader)
    if tuple(header[: len(META_COLUMNS)]) != META_COLUMNS:
        raise ValueError(
            "Las columnas descriptivas no coinciden con el contrato estándar"
        )
    months = tuple(parse_month(label) for label in header[len(META_COLUMNS) :])
    rows: list[Row] = []
    for cells in reader:
        if len(cells) != len(header):
            raise ValueError(
                f"Fila {cells[0] if cells else '?'} tiene {len(cells)} columnas, "
                f"se esperaban {len(header)}"
            )
        meta = dict(zip(META_COLUMNS, cells[: len(META_COLUMNS)]))
        series = tuple(parse_number(cell) for cell in cells[len(META_COLUMNS) :])
        rows.append(
            Row(
                product_id=meta["product_id"].strip(),
                sku=meta["SKU"].strip(),
                meta={key: value.strip() for key, value in meta.items()},
                series=series,
            )
        )
    return Sheet(path=source, months=months, rows=tuple(rows))
