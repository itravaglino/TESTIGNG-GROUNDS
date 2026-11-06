"""Fast tests other agents can run without extra dependencies.

    python3 -m unittest discover -s tests -v
"""

from __future__ import annotations

import hashlib
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
import sys

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from forecast_kit.parse import parse_es_number, parse_forecast_csv
from forecast_kit.schema import (
    FORECAST_END,
    FORECAST_START,
    GOLDEN_FULL_RELPATH,
    GOLDEN_MINI_RELPATH,
    GOLDEN_SHA256,
    GOLDEN_STRATIFIED_RELPATH,
    HISTORY_END,
    HISTORY_START,
    KNOWN_MODELS,
    META_COLUMNS,
    N_COLUMNS,
    N_FORECAST_MONTHS,
    N_HISTORY_MONTHS,
    N_MONTHS,
)
from forecast_kit.validate import validate_path

GOLDEN_FULL = ROOT / GOLDEN_FULL_RELPATH
GOLDEN_MINI = ROOT / GOLDEN_MINI_RELPATH
GOLDEN_STRAT = ROOT / GOLDEN_STRATIFIED_RELPATH
NEGATIVE = ROOT / "fixtures" / "negative"


class NumberParsing(unittest.TestCase):
    def test_comma_decimal(self):
        self.assertAlmostEqual(parse_es_number("8415,25"), 8415.25)

    def test_dot_decimal(self):
        self.assertAlmostEqual(parse_es_number("1234.56"), 1234.56)

    def test_negative(self):
        self.assertEqual(parse_es_number("-2"), -2.0)

    def test_empty(self):
        self.assertIsNone(parse_es_number(""))
        self.assertIsNone(parse_es_number("  "))


class MiniGolden(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.book = validate_path(str(GOLDEN_MINI))

    def test_mini_exists_and_parses(self):
        self.assertTrue(GOLDEN_MINI.is_file())
        self.assertGreaterEqual(len(self.book.products), 8)
        self.assertEqual(len(self.book.errors), 0, [e.message for e in self.book.errors])

    def test_cutover(self):
        self.assertEqual(self.book.months[0], HISTORY_START)
        self.assertEqual(self.book.months[-1], FORECAST_END)
        hist = [m for m in self.book.months if m <= HISTORY_END]
        fcst = [m for m in self.book.months if m >= FORECAST_START]
        self.assertEqual(len(hist), N_HISTORY_MONTHS)
        self.assertEqual(len(fcst), N_FORECAST_MONTHS)
        self.assertEqual(fcst[0], date(2026, 11, 1))

    def test_models_present(self):
        models = {p.meta["Modelo"] for p in self.book.products}
        self.assertTrue(KNOWN_MODELS <= models)

    def test_history_and_forecast_split(self):
        product = self.book.products[0]
        self.assertEqual(len(product.history), N_HISTORY_MONTHS)
        self.assertEqual(len(product.forecast), N_FORECAST_MONTHS)
        self.assertTrue(all(m <= HISTORY_END for m in product.history))
        self.assertTrue(all(m >= FORECAST_START for m in product.forecast))


class StratifiedGolden(unittest.TestCase):
    def test_covers_regions_and_clients(self):
        book = validate_path(str(GOLDEN_STRAT))
        self.assertEqual(book.errors, [])
        regions = {p.meta["Region"] for p in book.products}
        clients = {p.meta["Cliente"] for p in book.products}
        self.assertIn("BLOQUEADO", regions)
        self.assertIn("MTO", regions)
        self.assertEqual({"MANN-FILTER", "WIX"}, clients)


class FullGolden(unittest.TestCase):
    def test_checksum_and_shape(self):
        data = GOLDEN_FULL.read_bytes()
        self.assertEqual(hashlib.sha256(data).hexdigest(), GOLDEN_SHA256)
        book = validate_path(str(GOLDEN_FULL))
        self.assertEqual(len(book.products), 4402)
        self.assertEqual(len(book.months), N_MONTHS)
        self.assertEqual(len(book.errors), 0, book.errors[:5])
        self.assertEqual(len(META_COLUMNS) + N_MONTHS, N_COLUMNS)


class NegativeFixtures(unittest.TestCase):
    def test_empty(self):
        book = validate_path(str(NEGATIVE / "empty.csv"))
        self.assertTrue(any(i.code == "empty_file" for i in book.errors))

    def test_header_only_is_ok_schema_but_zero_products(self):
        book = validate_path(str(NEGATIVE / "header_only.csv"))
        self.assertEqual(len(book.products), 0)
        self.assertEqual(book.errors, [])

    def test_duplicate_product_id(self):
        book = validate_path(str(NEGATIVE / "duplicate_product_id.csv"))
        self.assertTrue(any(i.code == "duplicate_product_id" for i in book.errors))

    def test_unknown_model(self):
        book = validate_path(str(NEGATIVE / "unknown_model.csv"))
        self.assertTrue(any(i.code == "unknown_model" for i in book.errors))

    def test_empty_sku(self):
        book = validate_path(str(NEGATIVE / "empty_sku.csv"))
        self.assertTrue(any(i.code == "required_empty" and i.column == "SKU" for i in book.errors))

    def test_iso_date_headers(self):
        book = validate_path(str(NEGATIVE / "iso_date_headers.csv"))
        self.assertTrue(any(i.code == "date_header" for i in book.errors))

    def test_truncated_row(self):
        book = validate_path(str(NEGATIVE / "truncated_row.csv"))
        self.assertTrue(any(i.code == "row_length" for i in book.errors))

    def test_comma_delimiter_breaks_column_count(self):
        book = validate_path(str(NEGATIVE / "comma_delimiter.csv"))
        self.assertTrue(any(i.code == "column_count" for i in book.errors))

    def test_dot_decimal_still_parses(self):
        book = parse_forecast_csv(NEGATIVE / "dot_decimal_forecast.csv")
        product = book.products[0]
        last = max(product.forecast)
        self.assertAlmostEqual(product.forecast[last], 1234.56)


if __name__ == "__main__":
    unittest.main()
