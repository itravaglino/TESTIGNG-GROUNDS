from __future__ import annotations

import csv
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from forecast_qa.numbers import parse_es_number, parse_month_header
from forecast_qa.schema import DATE_HEADER_RE, DELIMITER, META_COLUMNS, NUMERIC_META


class MannFormatError(ValueError):
    """The file is not the standard Mann wide export."""


@dataclass(frozen=True)
class ProductSeries:
    product_id: str
    sku: str
    meta: dict[str, str | float | None]
    months: tuple[date, ...]
    values: tuple[float | None, ...]
    raw_values: tuple[str, ...]

    def value_at(self, month: date) -> float | None:
        idx = self.months.index(month)
        return self.values[idx]


@dataclass
class MannWorkbook:
    encoding: str
    months: tuple[date, ...]
    month_headers: tuple[str, ...]
    products: list[ProductSeries] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _decode(data: bytes) -> tuple[str, str]:
    for enc in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            return data.decode(enc), enc
        except UnicodeDecodeError:
            continue
    return data.decode("latin-1"), "latin-1"


def _validate_header(fieldnames: list[str] | None) -> tuple[list[str], list[str]]:
    if not fieldnames:
        raise MannFormatError("CSV vacío o sin encabezado.")
    names = [h.strip() for h in fieldnames]
    if names[: len(META_COLUMNS)] != list(META_COLUMNS):
        raise MannFormatError(
            "El encabezado no es la planilla Mann. "
            f"Se esperaba comenzar con {list(META_COLUMNS[:8])}… "
            f"y se obtuvo {names[:8]}. "
            "No uses CSV largo (sku,fecha,pronostico)."
        )
    month_headers = names[len(META_COLUMNS) :]
    if len(month_headers) < 12:
        raise MannFormatError(
            f"Faltan columnas mensuales (hay {len(month_headers)}). "
            "La planilla estándar tiene meses 01/01/2017 … 01/12/2027."
        )
    bad = [h for h in month_headers if not DATE_HEADER_RE.match(h)]
    if bad:
        raise MannFormatError(
            f"Columnas de mes inválidas (formato 01/MM/YYYY): {bad[:5]}"
        )
    return names, month_headers


def parse_mann_csv(path: str | Path) -> MannWorkbook:
    data = Path(path).read_bytes()
    text, encoding = _decode(data)
    reader = csv.DictReader(text.splitlines(), delimiter=DELIMITER)
    _, month_headers = _validate_header(reader.fieldnames)
    months = tuple(parse_month_header(h) for h in month_headers)
    book = MannWorkbook(
        encoding=encoding,
        months=months,
        month_headers=tuple(month_headers),
    )
    for i, row in enumerate(reader, start=2):
        pid = (row.get("product_id") or "").strip()
        sku = (row.get("SKU") or "").strip()
        if not pid or not sku:
            book.warnings.append(f"Fila {i}: product_id o SKU vacío.")
            continue
        meta: dict[str, str | float | None] = {}
        for col in META_COLUMNS:
            raw = row.get(col, "")
            if col in NUMERIC_META:
                meta[col] = parse_es_number(raw)
            else:
                meta[col] = raw
        raw_values = tuple(row.get(h, "") for h in month_headers)
        values = tuple(parse_es_number(v) for v in raw_values)
        book.products.append(
            ProductSeries(
                product_id=pid,
                sku=sku,
                meta=meta,
                months=months,
                values=values,
                raw_values=raw_values,
            )
        )
    if not book.products:
        raise MannFormatError("No hay filas de producto.")
    return book
