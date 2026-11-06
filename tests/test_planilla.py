import tempfile
import unittest
from pathlib import Path

from planilla import audit, diff_sheets, example_sheet, read_sheet, validate, write_sheet
from planilla.schema import EXPECTED_HEADER, FORECAST_MONTHS, month_label

GOLDEN = Path(__file__).resolve().parents[1] / "fixtures" / "Forecast_mann_scenario_test4_unidades.csv"
FORECAST_COLUMN = month_label(FORECAST_MONTHS[0])
HISTORY_COLUMN = "01/01/2017"


class GoldenTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sheet = read_sheet(GOLDEN)

    def test_contract(self):
        report = validate(self.sheet)
        self.assertTrue(report.ok, [item.message for item in report.errors])
        self.assertEqual(report.counts, {})
        self.assertEqual(len(self.sheet.rows), 4402)
        self.assertEqual(self.sheet.header, list(EXPECTED_HEADER))
        self.assertEqual(self.sheet.encoding, "cp1252")
        self.assertEqual(self.sheet.newline, "\r\n")

    def test_audit_pins_known_defects(self):
        report = audit(self.sheet)
        self.assertEqual(report.counts["FAMILIA_VACIA"], 4402)
        self.assertEqual(report.counts["DESCRIPCION_VACIA"], 136)
        self.assertEqual(report.counts["PRECIO_Y_COSTO_CERO"], 4402)
        self.assertEqual(report.counts["PRONOSTICO_CERO"], 1562)
        self.assertEqual(report.counts["VENDEDOR_LLENO"], 23)
        self.assertEqual(report.counts["REGION_BLOQUEADO"], 22)
        self.assertEqual(report.counts["CATEGORIA_PICK_UP"], 1)
        self.assertEqual(report.counts["CLUSTER_ATIPICO"], 1)
        self.assertEqual(report.counts["SKU_CIENTIFICO"], 1)
        self.assertEqual(report.counts["MOJIBAKE"], 8)
        self.assertEqual(report.counts["REAL_NEGATIVO"], 834)
        self.assertEqual(report.counts["REAL_NEGATIVO_CELDAS"], 1036)

    def test_diff_against_itself(self):
        report = diff_sheets(self.sheet, self.sheet)
        self.assertTrue(report.ok)
        self.assertEqual(report.comparable_rows, 4402)
        self.assertEqual(report.format_count, 0)


class ContractTest(unittest.TestCase):
    def test_example_is_valid(self):
        report = validate(example_sheet(2))
        self.assertTrue(report.ok, [item.message for item in report.errors])

    def test_roundtrip_keeps_values(self):
        sheet = example_sheet(1)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "ejemplo.csv"
            write_sheet(path, sheet)
            loaded = read_sheet(path)
        self.assertTrue(validate(loaded).ok)
        self.assertEqual(loaded.rows, sheet.rows)
        self.assertEqual(loaded.newline, "\r\n")

    def test_rejects_comma_delimiter(self):
        sheet = example_sheet(1)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "mal.csv"
            path.write_bytes(",".join(sheet.header).encode("cp1252") + b"\r\n")
            loaded = read_sheet(path)
        self.assertFalse(validate(loaded).ok)
        self.assertIn("HEADER", validate(loaded).counts)

    def test_rejects_duplicate_forecast_sign_and_dot(self):
        sheet = example_sheet(1)
        index = sheet.column_index()
        sheet.rows[0][index[FORECAST_COLUMN]] = "-1,5"
        sheet.rows[0][index[HISTORY_COLUMN]] = "1,5"
        sheet.rows[0][index["Error"]] = "100.0"
        report = validate(sheet)
        self.assertGreaterEqual(report.counts["FORECAST_FORMAT"], 1)
        self.assertGreaterEqual(report.counts["HISTORY_FORMAT"], 1)
        self.assertGreaterEqual(report.counts["NUMBER_FORMAT"], 1)

    def test_rejects_duplicate_ids_and_bad_enum(self):
        sheet = example_sheet(2)
        sheet.rows[1][0] = sheet.rows[0][0]
        sheet.rows[1][sheet.column_index()["SKU"]] = sheet.rows[0][sheet.column_index()["SKU"]]
        sheet.rows[0][sheet.column_index()["Modelo"]] = "lstm"
        report = validate(sheet)
        self.assertEqual(report.counts["DUPLICATE_PRODUCT_ID"], 1)
        self.assertEqual(report.counts["DUPLICATE_SKU"], 1)
        self.assertEqual(report.counts["ENUM"], 1)

    def test_format_only_diff_does_not_fail(self):
        left = example_sheet(1)
        right = example_sheet(1)
        column = right.column_index()[FORECAST_COLUMN]
        left.rows[0][column] = "1,5"
        right.rows[0][column] = "1,50"
        report = diff_sheets(left, right)
        self.assertTrue(report.ok)
        self.assertEqual(report.format_count, 1)
        self.assertEqual(report.value_count, 0)

    def test_value_diff_fails(self):
        left = example_sheet(1)
        right = example_sheet(1)
        left.rows[0][right.column_index()["ABC"]] = "A"
        report = diff_sheets(left, right)
        self.assertFalse(report.ok)
        self.assertEqual(report.value_count, 1)


if __name__ == "__main__":
    unittest.main()
