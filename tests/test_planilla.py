import tempfile
import unittest
from pathlib import Path

from planilla.checks import validate
from planilla.compare import compare_sheets
from planilla.sheet import EXPECTED_MONTHS, HISTORY_COUNT, fixture_path, load_fixture, load_sheet


class StandardSheetTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sheet = load_fixture()
        cls.report = validate(cls.sheet)

    def test_calendar_and_size(self):
        self.assertEqual(len(EXPECTED_MONTHS), 132)
        self.assertEqual(HISTORY_COUNT, 118)
        self.assertEqual(self.sheet.encoding, "cp1252")
        self.assertEqual(self.report.rows, 4402)
        self.assertTrue(self.report.ok)

    def test_known_quality_findings(self):
        counts = {item.code: item.count for item in self.report.warnings}
        self.assertEqual(counts["pronostico_cero"], 1562)
        self.assertEqual(counts["pronostico_cero_con_demanda"], 619)
        self.assertEqual(counts["promedio"], 668)
        self.assertEqual(counts["historia_negativa"], 834)
        self.assertEqual(counts["historia_cero"], 5)
        self.assertEqual(counts["categoria"], 1)
        self.assertEqual(counts["texto"], 7)
        self.assertEqual(counts["familia_vacia"], 4402)
        self.assertNotIn("abc_corte", counts)
        self.assertEqual(self.report.errors, [])

    def test_compare_fixture_to_itself(self):
        diff = compare_sheets(self.sheet, self.sheet)
        self.assertTrue(diff.identical)

    def test_compare_detects_a_forecast_edit(self):
        raw = fixture_path().read_bytes()
        text = raw.decode("cp1252")
        # Primer pronóstico del primer SKU: 8415,25 al cierre de la primera fila de datos.
        self.assertIn("8415,25", text)
        mutated = text.replace("8415,25", "8415,50", 1)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "mutada.csv"
            path.write_bytes(mutated.encode("cp1252"))
            diff = compare_sheets(load_sheet(path), self.sheet)
        self.assertFalse(diff.identical)
        self.assertEqual(len(diff.forecast_diffs), 1)
        self.assertTrue(diff.forecast_diffs[0].startswith("722344"))

    def test_rejects_a_decimal_in_history(self):
        header = ";".join(self.sheet.header)
        row = list(self.sheet.rows[0])
        row[len(self.sheet.header) - 14 - 1] = "10,5"
        body = ";".join(row)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "mala.csv"
            path.write_text(header + "\n" + body + "\n", encoding="utf-8")
            report = validate(load_sheet(path))
        codes = {item.code for item in report.errors}
        self.assertIn("historia_entera", codes)
        self.assertFalse(report.ok)


if __name__ == "__main__":
    unittest.main()
