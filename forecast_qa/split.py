"""Split Mann wide months into history (actuals) vs forecast.

This export does NOT store a parallel actual/forecast pair per month.
History cells are realized demand (often integers). Forecast cells are
future points (often decimal commas). For the standard Nov-2026 file,
forecast starts at 01/11/2026 for most SKUs.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import date

from forecast_qa.parse import MannWorkbook, ProductSeries
from forecast_qa.schema import DEFAULT_FORECAST_START
from forecast_qa.numbers import parse_month_header


@dataclass(frozen=True)
class SplitSeries:
    product: ProductSeries
    forecast_start: date
    history_months: tuple[date, ...]
    history: tuple[float | None, ...]
    forecast_months: tuple[date, ...]
    forecast: tuple[float | None, ...]


def detect_file_forecast_start(book: MannWorkbook) -> date:
    """Majority of SKUs: first month whose raw cell contains a decimal comma."""
    votes: Counter[str] = Counter()
    for product in book.products:
        for header, raw in zip(book.month_headers, product.raw_values, strict=True):
            if raw and "," in raw:
                votes[header] += 1
                break
        else:
            votes[DEFAULT_FORECAST_START] += 1
    if not votes:
        return parse_month_header(DEFAULT_FORECAST_START)
    header, _ = votes.most_common(1)[0]
    return parse_month_header(header)


def split_product(product: ProductSeries, forecast_start: date) -> SplitSeries:
    hist_m, hist_v, fcst_m, fcst_v = [], [], [], []
    for month, value in zip(product.months, product.values, strict=True):
        if month < forecast_start:
            hist_m.append(month)
            hist_v.append(value)
        else:
            fcst_m.append(month)
            fcst_v.append(value)
    return SplitSeries(
        product=product,
        forecast_start=forecast_start,
        history_months=tuple(hist_m),
        history=tuple(hist_v),
        forecast_months=tuple(fcst_m),
        forecast=tuple(fcst_v),
    )


def split_workbook(book: MannWorkbook) -> tuple[date, list[SplitSeries]]:
    start = detect_file_forecast_start(book)
    return start, [split_product(p, start) for p in book.products]
