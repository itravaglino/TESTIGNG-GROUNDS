"""Parser de la planilla estándar (`;`, decimal `,`, cp1252)."""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from . import schema

DATE_RE = re.compile(r"^(\d{2})/(\d{2})/(\d{4})$")
ENCODINGS = ("utf-8-sig", "cp1252", "latin-1")


def parse_number(raw: str | None) -> float | None:
    if raw is None:
        return None
    text = str(raw).strip()
    if text == "":
        return None
    text = text.replace(" ", "")
    if "," in text and "." in text:
        # 1.234,56 estilo ES; este vintage no lo usa, pero no rompe.
        text = text.replace(".", "").replace(",", ".")
    else:
        text = text.replace(",", ".")
    return float(text)


def parse_month_header(label: str) -> date | None:
    match = DATE_RE.match(label.strip())
    if not match:
        return None
    day, month, year = (int(p) for p in match.groups())
    return date(year, month, day)


def _decode(data: bytes) -> tuple[str, str]:
    last_error: Exception | None = None
    for enc in ENCODINGS:
        try:
            return data.decode(enc), enc
        except UnicodeDecodeError as exc:
            last_error = exc
            continue
    raise ValueError(f"no se pudo decodificar el CSV: {last_error}") from last_error


@dataclass
class ProductRow:
    product_id: str
    sku: str
    meta: dict[str, str]
    numbers: dict[str, float | None]
    history: dict[date, float | None]
    forecast: dict[date, float | None]

    def meta_get(self, key: str) -> str:
        return self.meta.get(key, "")


@dataclass
class ParsedWorkbook:
    encoding: str
    headers: list[str]
    month_headers: list[str]
    history_months: list[date]
    forecast_months: list[date]
    products: list[ProductRow]
    issues: list[str] = field(default_factory=list)

    @property
    def by_id(self) -> dict[str, ProductRow]:
        return {p.product_id: p for p in self.products}


def detect_forecast_start(month_headers: list[str], matrix: list[list[str]]) -> int:
    """Índice en month_headers donde empieza el forecast (mayoría con decimal)."""
    if not matrix:
        return len(month_headers)
    sample = matrix[: min(200, len(matrix))]
    for i, _header in enumerate(month_headers):
        decimalish = 0
        for row in sample:
            if i < len(row) and "," in row[i]:
                decimalish += 1
        if decimalish >= max(1, len(sample) // 2):
            return i
    return len(month_headers)


def parse_csv(path: str | Path, *, forecast_start: date | None = None) -> ParsedWorkbook:
    data = Path(path).read_bytes()
    text, encoding = _decode(data)
    reader = csv.reader(text.splitlines(), delimiter=schema.DELIMITER)
    rows = [r for r in reader if any(cell.strip() for cell in r)]
    if not rows:
        raise ValueError("CSV vacío")
    headers = rows[0]
    body = rows[1:]

    month_idx: list[int] = []
    month_headers: list[str] = []
    for i, h in enumerate(headers):
        if parse_month_header(h):
            month_idx.append(i)
            month_headers.append(h)

    month_matrix = [[r[i] if i < len(r) else "" for i in month_idx] for r in body]
    months = [parse_month_header(h) for h in month_headers]
    assert all(m is not None for m in months)
    months_d = [m for m in months if m is not None]

    if forecast_start is not None:
        split = next((i for i, m in enumerate(months_d) if m >= forecast_start), len(months_d))
    else:
        split = detect_forecast_start(month_headers, month_matrix)

    history_months = months_d[:split]
    forecast_months = months_d[split:]

    header_index = {name: i for i, name in enumerate(headers)}
    products: list[ProductRow] = []
    issues: list[str] = []

    for line_no, raw in enumerate(body, start=2):
        if len(raw) != len(headers):
            issues.append(f"L{line_no}: {len(raw)} columnas, se esperaban {len(headers)}")
        def cell(name: str) -> str:
            i = header_index.get(name)
            if i is None or i >= len(raw):
                return ""
            return raw[i].strip()

        pid = cell("product_id")
        numbers = {k: parse_number(cell(k)) for k in schema.NUMERIC_META}
        history: dict[date, float | None] = {}
        forecast: dict[date, float | None] = {}
        for i, month in enumerate(months_d):
            col = month_idx[i]
            value = parse_number(raw[col] if col < len(raw) else "")
            if i < split:
                history[month] = value
            else:
                forecast[month] = value
        meta = {name: cell(name) for name in schema.META_COLUMNS}
        products.append(
            ProductRow(
                product_id=pid,
                sku=cell("SKU"),
                meta=meta,
                numbers=numbers,
                history=history,
                forecast=forecast,
            )
        )

    return ParsedWorkbook(
        encoding=encoding,
        headers=headers,
        month_headers=month_headers,
        history_months=history_months,
        forecast_months=forecast_months,
        products=products,
        issues=issues,
    )

