"""Pruebas del auditor contra los fixtures acordados por las 8 instancias."""

from __future__ import annotations

import json
import unittest

from auditor.fixtures import build_fixtures, expected_signals
from auditor.parser import canonical_template_csv, load_bytes
from auditor.report import analyze_frame, corrected_long_csv, report_to_csv_rows
from auditor.server import _extract_upload, analyze_upload, correct_upload


def _audit(name: str, raw: bytes):
    loaded = load_bytes(f"{name}.csv", raw)
    report = analyze_frame(
        loaded["frame"],
        loaded["frequency"],
        name,
        list(loaded.get("warnings") or []),
    )
    return loaded, report


def _blob(finding_or_text) -> str:
    return json.dumps(finding_or_text, ensure_ascii=False).lower()


class AuditFixturesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixtures = build_fixtures()
        cls.signals = expected_signals()
        cls.results = {}
        for name, raw in cls.fixtures.items():
            cls.results[name] = _audit(name, raw)

    def test_template_parses(self):
        loaded = load_bytes("plantilla.csv", canonical_template_csv().encode("utf-8"))
        self.assertGreaterEqual(len(loaded["frame"]), 12)
        self.assertIn("product_id", loaded["frame"].columns)

    def test_good_monthly(self):
        loaded, report = self.results["good_monthly"]
        self.assertEqual(len(loaded["frame"]), 24)
        product = report["products"][0]
        self.assertEqual(product["verdict"]["decision"], "aprobar")
        wape = product["metrics"].get("wape")
        self.assertIsNotNone(wape)
        self.assertLess(wape, 0.35)
        self.assertTrue(product["recommendations"])
        self.assertTrue(product["how_to_improve"] or product["verdict"]["decision"] == "aprobar")

    def test_bad_negative_flat(self):
        _, report = self.results["bad_negative_flat"]
        product = report["products"][0]
        self.assertIn(product["verdict"]["decision"], {"corregir", "descartar"})
        blob = _blob(product["findings"])
        self.assertTrue(any(stem in blob for stem in ("negativ", "menor que cero", "below zero")))

    def test_explosive(self):
        _, report = self.results["explosive"]
        product = report["products"][0]
        self.assertIn(product["verdict"]["decision"], {"corregir", "descartar"})
        blob = _blob(product["findings"])
        self.assertTrue(
            any(stem in blob for stem in ("outlier", "explosion", "explos", "atipic", "pico", "extrem"))
        )

    def test_intermittent_class(self):
        _, report = self.results["intermittent"]
        product = report["products"][0]
        self.assertIn(product["profile"].get("demand_class"), {"intermittent", "lumpy"})
        self.assertGreaterEqual(len(product["recommendations"]), 3)
        names = " ".join(item.get("model", "") for item in product["recommendations"]).lower()
        self.assertTrue("croston" in names or "tsb" in names)

    def test_wide_spanish(self):
        loaded, report = self.results["wide_spanish"]
        frame = loaded["frame"]
        self.assertEqual(len(frame), 6)
        dates = sorted(frame["date"].dt.strftime("%Y-%m-%d"))
        self.assertEqual(dates, self.signals["wide_spanish"]["dates"])
        march = frame.loc[frame["date"].dt.strftime("%Y-%m-%d") == "2024-03-01", "forecast"].iloc[0]
        self.assertAlmostEqual(float(march), 120.5, places=4)
        self.assertEqual(report["summary"]["products"], 1)
        json.dumps(report, allow_nan=False)

    def test_semicolon_decimal(self):
        loaded, report = self.results["semicolon_decimal"]
        self.assertEqual(loaded["frame"]["product_id"].nunique(), 2)
        self.assertEqual(len(loaded["frame"]), 12)
        self.assertEqual(report["summary"]["products"], 2)

    def test_missing_and_dupes(self):
        loaded, report = self.results["missing_and_dupes"]
        dates = set(loaded["frame"]["date"].dt.strftime("%Y-%m-%d"))
        self.assertNotIn("2024-03-01", dates)
        self.assertEqual((loaded["frame"]["date"].dt.strftime("%Y-%m-%d") == "2024-04-01").sum(), 1)
        blob = _blob(report["products"][0]["findings"]) + " " + " ".join(loaded["warnings"]).lower()
        self.assertTrue(any(stem in blob for stem in ("faltante", "hueco", "missing", "gap", "duplic", "repetid")))

    def test_portfolio_mix(self):
        _, report = self.results["portfolio"]
        by_id = {item["product_id"]: item for item in report["products"]}
        self.assertEqual(set(by_id), {
            "P01-SEAS", "P02-STABLE", "P03-NEG", "P04-SPIKE",
            "P05-INTER", "P06-LUMPY", "P07-BIAS", "P08-TREND",
        })
        spec = self.signals["portfolio"]["series"]
        decisions = set()
        for sku, expect in spec.items():
            product = by_id[sku]
            decisions.add(product["verdict"]["decision"])
            self.assertIn(product["verdict"]["decision"], set(expect["decision_in"]), sku)
            if "wape_under" in expect:
                self.assertLess(product["metrics"]["wape"], expect["wape_under"], sku)
            if "wape_over" in expect and product["metrics"].get("wape") is not None:
                self.assertGreater(product["metrics"]["wape"], expect["wape_over"], sku)
            if "demand_class_in" in expect:
                self.assertIn(product["profile"]["demand_class"], set(expect["demand_class_in"]), sku)
            if "findings_any" in expect:
                blob = _blob(product["findings"])
                self.assertTrue(any(stem in blob for stem in expect["findings_any"]), sku)
        self.assertGreaterEqual(len(decisions), 2)
        self.assertGreater(report["summary"]["products"], 0)
        table = report_to_csv_rows(report)
        self.assertIn("producto", table.splitlines()[0].lower())

    def test_corrected_csv_and_json(self):
        raw = self.fixtures["explosive"]
        text = correct_upload("explosive.csv", raw)
        self.assertIn("forecast_corrected", text.splitlines()[0])
        self.assertIn("5000", text)
        report = analyze_upload("explosive.csv", raw)
        json.dumps(report, allow_nan=False)
        corrected = corrected_long_csv(
            load_bytes("explosive.csv", raw)["frame"], "M"
        )
        self.assertIn("SPIKE", corrected)

    def test_multipart_and_plain(self):
        raw = self.fixtures["good_monthly"]
        boundary = "----auditor"
        body = (
            f"--{boundary}\r\n"
            'Content-Disposition: form-data; name="file"; filename="good.csv"\r\n'
            "Content-Type: text/csv\r\n\r\n"
        ).encode() + raw + f"\r\n--{boundary}--\r\n".encode()
        name, data = _extract_upload(f"multipart/form-data; boundary={boundary}", body)
        self.assertEqual(name, "good.csv")
        self.assertEqual(data, raw)
        name, data = _extract_upload("text/plain; charset=utf-8", b"sku,fecha\n")
        self.assertTrue(data.startswith(b"sku"))


if __name__ == "__main__":
    unittest.main()
