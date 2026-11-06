"""Parse the standard forecast CSV into typed product rows."""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Iterable

from forecast_kit.schema import (
    DATE_HEADER_FORMAT,
    DELIMITER,
    ENCODINGS,
    HISTORY_END,
    META_COLUMNS,
    N_COLUMNS,
    N_META,
)

_DATE_HEADER_RE = re.compile(r"^\d{2}/\d{2}/\d{4}$")
_NUM_RE = re.compile(r"^-?\d+(?:[.,]\d+)?$")


def parse_es_number(raw: str) -> float | None:
    """Parse a Spanish/AR number: 8415,25 or 8415.25 or integer. Empty -> None."""
    text = (raw or "").strip()
    if text == "":
        return None
    if not _NUM_RE.match(text):
        # thousands separators are not used in this export; reject junk
        compact = text.replace(" ", "")
        if "," in compact and "." in compact:
            compact = compact.replace(".", "").replace(",", ".")
        else:
            compact = compact.replace(",", ".")
        try:
            return float(compact)
        except ValueError as exc:
            raise ValueError(f"not a number: {raw!r}") from exc
    return float(text.replace(",", "."))


def parse_date_header(raw: str) -> date:
    return datetime.strptime(raw, DATE_HEADER_FORMAT).date()


def is_date_header(raw: str) -> bool:
    return bool(_DATE_HEADER_RE.match(raw or ""))


def decode_bytes(data: bytes) -> tuple[str, str]:
    last_error: Exception | None = None
    for enc in ENCODINGS:
        try:
            return data.decode(enc), enc
        except UnicodeDecodeError as exc:
            last_error = exc
    assert last_error is not None
    raise last_error


@dataclass
class Issue:
    severity: str  # error | warning
    code: str
    message: str
    row: int | None = None  # 1-based data row, None = file/header
    product_id: str | None = None
    column: str | None = None


@dataclass
class ProductSeries:
    product_id: str
    sku: str
    meta: dict[str, str]
    history: dict[date, float]  # actuals, missing months omitted
    forecast: dict[date, float]
    source_row: int


@dataclass
class ForecastWorkbook:
    path: str
    encoding: str
    months: list[date]
    products: list[ProductSeries]
    issues: list[Issue] = field(default_factory=list)

    @property
    def errors(self) -> list[Issue]:
        return [i for i in self.issues if i.severity == "error"]

    @property
    def warnings(self) -> list[Issue]:
        return [i for i in self.issues if i.severity == "warning"]


def _read_table(path: Path) -> tuple[list[str], list[list[str]], str]:
    data = path.read_bytes()
    if not data.strip():
        return [], [], "empty"
    text, encoding = decode_bytes(data)
    reader = csv.reader(text.splitlines(), delimiter=DELIMITER)
    rows = [row for row in reader if any(cell.strip() for cell in row)]
    if not rows:
        return [], [], encoding
    return rows[0], rows[1:], encoding


def parse_forecast_csv(path: str | Path, *, collect_all: bool = True) -> ForecastWorkbook:
    """Parse a standard-planilla CSV.

    Does not raise on row-level problems; they are attached as issues.
    File-level problems (empty, unreadable) still produce a workbook with errors.
    """
    path = Path(path)
    issues: list[Issue] = []
    header, data_rows, encoding = _read_table(path)

    if encoding == "empty" or not header:
        issues.append(Issue("error", "empty_file", "CSV is empty"))
        return ForecastWorkbook(str(path), encoding, [], [], issues)

    if len(header) != N_COLUMNS:
        issues.append(
            Issue(
                "error",
                "column_count",
                f"expected {N_COLUMNS} columns, got {len(header)}",
            )
        )

    meta_ok = tuple(header[:N_META]) == META_COLUMNS
    if not meta_ok:
        issues.append(
            Issue(
                "error",
                "meta_headers",
                f"metadata headers do not match the standard planilla; got {header[:N_META]!r}",
            )
        )

    months: list[date] = []
    date_headers = header[N_META:]
    for col in date_headers:
        if not is_date_header(col):
            issues.append(
                Issue(
                    "error",
                    "date_header",
                    f"expected DD/MM/YYYY month header, got {col!r}",
                    column=col,
                )
            )
            continue
        months.append(parse_date_header(col))

    if months:
        for prev, cur in zip(months, months[1:]):
            gap = (cur.year - prev.year) * 12 + (cur.month - prev.month)
            if gap != 1 or cur.day != 1 or prev.day != 1:
                issues.append(
                    Issue(
                        "error",
                        "date_sequence",
                        f"months must be consecutive first-of-month; {prev.isoformat()} -> {cur.isoformat()}",
                    )
                )
                break

    products: list[ProductSeries] = []
    seen_ids: dict[str, int] = {}
    seen_skus: dict[str, int] = {}

    for offset, raw in enumerate(data_rows, start=1):
        if len(raw) != len(header):
            issues.append(
                Issue(
                    "error",
                    "row_length",
                    f"row has {len(raw)} cells, header has {len(header)}",
                    row=offset,
                    product_id=raw[0] if raw else None,
                )
            )
            if not collect_all:
                continue
        cells = raw + [""] * max(0, len(header) - len(raw))
        meta = {
            name: (cells[i].strip() if i < len(cells) else "")
            for i, name in enumerate(META_COLUMNS)
        }
        pid = meta.get("product_id", "")
        sku = meta.get("SKU", "")
        if pid in seen_ids:
            issues.append(
                Issue(
                    "error",
                    "duplicate_product_id",
                    f"product_id {pid} already seen on row {seen_ids[pid]}",
                    row=offset,
                    product_id=pid,
                )
            )
        else:
            seen_ids[pid] = offset
        if sku and sku in seen_skus:
            issues.append(
                Issue(
                    "warning",
                    "duplicate_sku",
                    f"SKU {sku} already seen on row {seen_skus[sku]}",
                    row=offset,
                    product_id=pid,
                    column="SKU",
                )
            )
        else:
            if sku:
                seen_skus[sku] = offset

        history: dict[date, float] = {}
        forecast: dict[date, float] = {}
        n_dates = min(len(months), max(0, len(cells) - N_META))
        for i in range(n_dates):
            month = months[i]
            cell = cells[N_META + i]
            try:
                value = parse_es_number(cell)
            except ValueError:
                issues.append(
                    Issue(
                        "error",
                        "bad_number",
                        f"invalid numeric {cell!r}",
                        row=offset,
                        product_id=pid,
                        column=month.strftime(DATE_HEADER_FORMAT),
                    )
                )
                continue
            if value is None:
                issues.append(
                    Issue(
                        "warning",
                        "empty_month",
                        "empty monthly cell (treated as missing)",
                        row=offset,
                        product_id=pid,
                        column=month.strftime(DATE_HEADER_FORMAT),
                    )
                )
                continue
            if month <= HISTORY_END:
                history[month] = value
            else:
                forecast[month] = value

        products.append(
            ProductSeries(
                product_id=pid,
                sku=sku,
                meta=meta,
                history=history,
                forecast=forecast,
                source_row=offset,
            )
        )

    return ForecastWorkbook(str(path), encoding, months, products, issues)


def iter_products(path: str | Path) -> Iterable[ProductSeries]:
    yield from parse_forecast_csv(path).products
