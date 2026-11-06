"""Tests del contrato: el sample real y CSVs rotos deben fallar rápido."""

from __future__ import annotations

import tempfile
import unittest
from datetime import date
from pathlib import Path

from planilla.parse import parse_csv, parse_number
from planilla.validate import validate_workbook

ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / "fixtures" / "samples" / "stratified.csv"
INVALID = ROOT / "fixtures" / "invalid"


class NumberParsing(unittest.TestCase):
    def test_comma_decimal(self) -> None:
        self.assertAlmostEqual(parse_number("9995,08") or 0, 9995.08)
        self.assertAlmostEqual(parse_number("0,46") or 0, 0.46)
        self.assertEqual(parse_number("-13"), -13.0)
        self.assertIsNone(parse_number(""))
        self.assertIsNone(parse_number(None))


class StratifiedSample(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.book = parse_csv(SAMPLE)

    def test_encoding_is_not_utf8_when_cp1252(self) -> None:
        self.assertIn(self.book.encoding, {"cp1252", "latin-1", "utf-8-sig"})

    def test_history_forecast_split(self) -> None:
        self.assertEqual(self.book.history_months[-1], date(2026, 10, 1))
        self.assertEqual(self.book.forecast_months[0], date(2026, 11, 1))
        self.assertEqual(len(self.book.forecast_months), 14)

    def test_golden_product_722344(self) -> None:
        row = self.book.by_id.get("722344")
        self.assertIsNotNone(row)
        assert row is not None
        self.assertEqual(row.sku, "WL7413")
        self.assertEqual(row.meta["Modelo"], "auto_SARIMA")
        self.assertEqual(row.meta["Tipo de demanda"], "Con tendencia")
        self.assertEqual(row.history[date(2026, 10, 1)], 6670.0)
        self.assertAlmostEqual(row.forecast[date(2026, 11, 1)] or 0, 8415.25)
        self.assertAlmostEqual(row.numbers["Promedio"] or 0, 9995.08)

    def test_model_typo_preserved(self) -> None:
        models = {p.meta["Modelo"] for p in self.book.products}
        self.assertIn("holtsWintersExponentialSmoothing", models)
        self.assertIn("prophet", models)

    def test_all_demand_types_present(self) -> None:
        demands = {p.meta["Tipo de demanda"] for p in self.book.products}
        self.assertEqual(
            demands,
            {"Erratica", "Intermitente", "Con tendencia", "Variable moderada"},
        )

    def test_validate_ok(self) -> None:
        result = validate_workbook(self.book)
        self.assertTrue(result.ok, result.errors)

    def test_pick_up_alias_is_not_parse_error(self) -> None:
        cats = {p.meta["Categoria"] for p in self.book.products}
        self.assertTrue("Pick up" in cats or "PICK UP" in cats)


class InvalidFiles(unittest.TestCase):
    def test_comma_delimiter_rejected(self) -> None:
        book = parse_csv(INVALID / "comma_delimiter.csv")
        result = validate_workbook(book)
        self.assertFalse(result.ok)

    def test_missing_meta_rejected(self) -> None:
        book = parse_csv(INVALID / "missing_modelo.csv")
        result = validate_workbook(book)
        self.assertFalse(result.ok)
        self.assertTrue(any("Modelo" in e for e in result.errors))

    def test_duplicate_product_id(self) -> None:
        book = parse_csv(INVALID / "duplicate_id.csv")
        result = validate_workbook(book)
        self.assertFalse(result.ok)
        self.assertTrue(any("duplicado" in e for e in result.errors))

    def test_unknown_model(self) -> None:
        book = parse_csv(INVALID / "unknown_model.csv")
        result = validate_workbook(book)
        self.assertFalse(result.ok)
        self.assertTrue(any("Modelo desconocido" in e for e in result.errors))


class RoundTripTiny(unittest.TestCase):
    def test_utf8_semicolon_still_parses(self) -> None:
        header = (
            "product_id;Familia;Region;Vendedor;Cliente;Categoria;Subcategoria;"
            "SKU;Descripcion;Tipo de demanda;Cluster;Error;ABC;Promedio;"
            "Desviacion Std;Coeficiente;YTD;QTD;MTD;FYTD;YTG;QTG;MTG;FYTG;"
            "Modelo;Precio Unitario;Costo Unitario;Reemplazado?;Reemplazado por;"
            "Descontinuado?;01/09/2026;01/10/2026;01/11/2026;01/12/2026"
        )
        line = (
            "1;;MTO;;WIX;PC;Oil Filter;X;desc;Erratica;Alto riesgo;10;C;1;1;1;"
            "0;0;0;0;0;0;0;0;prophet;0;0;No;N/A;No;1;2;3,5;4,1"
        )
        with tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False, encoding="utf-8") as fh:
            fh.write(header + "\n" + line + "\n")
            path = Path(fh.name)
        book = parse_csv(path)
        result = validate_workbook(book)
        self.assertTrue(result.ok, result.errors)
        self.assertEqual(book.products[0].forecast[date(2026, 11, 1)], 3.5)


if __name__ == "__main__":
    unittest.main()
