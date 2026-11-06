import tempfile
import unittest
from datetime import date
from pathlib import Path

from planilla.contract import FIXTURE
from planilla.sheet import load, parse_number
from planilla.verify import compare, verify


class ContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sheet = load(FIXTURE)

    def test_fixture_exists_and_keeps_source_encoding(self):
        raw = FIXTURE.read_bytes()
        self.assertGreater(len(raw), 1_000_000)
        self.assertIn("HidrA".encode("ascii") + bytes([0xA1]), raw)

    def test_verify_has_no_errors(self):
        report = verify(self.sheet)
        self.assertTrue(report.ok, report.render())

    def test_as_of_and_horizon(self):
        self.assertEqual(self.sheet.history_months[-1], date(2026, 10, 1))
        self.assertEqual(self.sheet.forecast_months[0], date(2026, 11, 1))
        self.assertEqual(len(self.sheet.forecast_months), 14)
        self.assertEqual(len(self.sheet.rows), 4402)

    def test_known_sku_mtd(self):
        row = self.sheet.by_sku["WL7413"]
        oct_2026 = row.series[self.sheet.months.index(date(2026, 10, 1))]
        oct_2025 = row.series[self.sheet.months.index(date(2025, 10, 1))]
        self.assertEqual(oct_2026, 6670)
        self.assertEqual(oct_2025, 5153)
        self.assertEqual(row.number("MTD"), 29)
        self.assertEqual(row.meta["Modelo"], "auto_SARIMA")

    def test_comma_decimals(self):
        self.assertEqual(parse_number("8415,25"), 8415.25)
        self.assertEqual(parse_number("-13"), -13.0)

    def test_compare_against_itself(self):
        report = compare(self.sheet, FIXTURE)
        self.assertTrue(report.ok, report.render())
        text = report.render()
        self.assertIn("filas idénticas 4402/4402", text)

    def test_compare_detects_a_changed_forecast(self):
        row = self.sheet.rows[0]
        header = [
            "product_id",
            "SKU",
            *[month.strftime("%d/%m/%Y") for month in self.sheet.forecast_months],
        ]
        values = [row.product_id, row.sku, *[str(value + 10) for value in row.forecast(118)]]
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "otro.csv"
            path.write_text(";".join(header) + "\n" + ";".join(values) + "\n", encoding="utf-8")
            report = compare(self.sheet, path)
        self.assertTrue(report.ok, report.render())
        self.assertIn("faltantes", report.render())
        self.assertNotIn("filas idénticas 1/1", report.render())


if __name__ == "__main__":
    unittest.main()
