from pathlib import Path

import pytest

from forecast_qa.parse import MannFormatError, parse_mann_csv
from forecast_qa.split import detect_file_forecast_start
from forecast_qa.numbers import parse_es_number

ROOT = Path(__file__).resolve().parents[1]
MINI = ROOT / "fixtures" / "mann" / "mann_mini.csv"
FULL = ROOT / "fixtures" / "mann" / "Forecast_mann_scenario_test4_unidades.csv"
LONG = ROOT / "tests" / "data" / "invented_long.csv"


def test_mini_shape_and_ids():
    book = parse_mann_csv(MINI)
    assert len(book.products) == 12
    assert len(book.months) == 132
    assert book.month_headers[0] == "01/01/2017"
    assert book.month_headers[-1] == "01/12/2027"
    ids = {p.product_id for p in book.products}
    assert "722344" in ids
    sku = next(p for p in book.products if p.product_id == "722344")
    assert sku.sku == "WL7413"
    assert sku.meta["Modelo"] == "auto_SARIMA"
    nov = parse_es_number("8415,25")
    assert nov == 8415.25
    from datetime import date

    assert sku.value_at(date(2026, 11, 1)) == 8415.25


def test_forecast_starts_nov_2026():
    book = parse_mann_csv(MINI)
    start = detect_file_forecast_start(book)
    assert start.isoformat() == "2026-11-01"


def test_rejects_invented_long_format():
    with pytest.raises(MannFormatError, match="planilla Mann"):
        parse_mann_csv(LONG)


def test_full_standard_file():
    book = parse_mann_csv(FULL)
    assert len(book.products) == 4402
    assert len(book.months) == 132
    models = {str(p.meta["Modelo"]) for p in book.products}
    assert "auto_SARIMA" in models
    assert "holtsWintersExponentialSmoothing" in models
    assert "prophet" in models
