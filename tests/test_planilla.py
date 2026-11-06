from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from planilla.parse import ParseError, melt, parse_number, parse_planilla, parse_planilla_path
from planilla.verify import verify_planilla, verify_planilla_path

FIXTURES = ROOT / "fixtures" / "planilla-estandar"
SAMPLE = FIXTURES / "sample_diverso.csv"
FULL = FIXTURES / "Forecast_mann_scenario_test4_unidades.csv"
GOLDEN = FIXTURES / "golden_stats.json"
BAD = FIXTURES / "malformados"


class ParseNumberTests(unittest.TestCase):
    def test_coma_decimal(self) -> None:
        self.assertEqual(parse_number("8415,25"), 8415.25)

    def test_entero(self) -> None:
        self.assertEqual(parse_number("6670"), 6670.0)

    def test_negativo(self) -> None:
        self.assertEqual(parse_number("-144"), -144.0)

    def test_vacio(self) -> None:
        self.assertIsNone(parse_number(""))
        self.assertIsNone(parse_number(None))

    def test_invalido(self) -> None:
        with self.assertRaises(ParseError):
            parse_number("n/a")


class SampleFixtureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.series = parse_planilla_path(SAMPLE)

    def test_tipos_y_modelos_cubiertos(self) -> None:
        tipos = {s.meta["Tipo de demanda"] for s in self.series}
        modelos = {s.meta["Modelo"] for s in self.series}
        self.assertEqual(
            tipos, {"Erratica", "Intermitente", "Con tendencia", "Variable moderada"}
        )
        self.assertEqual(
            modelos, {"auto_SARIMA", "holtsWintersExponentialSmoothing", "prophet"}
        )

    def test_region_bloqueado_en_sample(self) -> None:
        regiones = {s.meta["Region"] for s in self.series}
        self.assertIn("BLOQUEADO", regiones)

    def test_historia_y_pronostico(self) -> None:
        s = self.series[0]
        self.assertEqual(len(s.historia), 118)
        self.assertEqual(len(s.pronostico), 14)
        self.assertEqual(s.historia[0].fecha.isoformat(), "2017-01-01")
        self.assertEqual(s.historia[-1].fecha.isoformat(), "2026-10-01")
        self.assertEqual(s.pronostico[0].fecha.isoformat(), "2026-11-01")
        self.assertEqual(s.pronostico[-1].fecha.isoformat(), "2027-12-01")
        self.assertTrue(all(not p.es_pronostico for p in s.historia))
        self.assertTrue(all(p.es_pronostico for p in s.pronostico))

    def test_producto_control_si_esta(self) -> None:
        found = next((s for s in self.series if s.product_id == "722344"), None)
        self.assertIsNotNone(found)
        assert found is not None
        self.assertEqual(found.sku, "WL7413")
        self.assertEqual(found.historia[0].valor, 3.0)
        self.assertEqual(found.historia[-1].valor, 6670.0)
        self.assertEqual(found.pronostico[0].valor, 8415.25)

    def test_melt_largo(self) -> None:
        filas = melt(self.series)
        self.assertEqual(len(filas), len(self.series) * 132)
        first = filas[0]
        self.assertEqual(first["fecha"], "2017-01-01")
        self.assertFalse(first["es_pronostico"])
        self.assertEqual(first["actual"], first["valor"])
        last_hist = filas[117]
        self.assertEqual(last_hist["fecha"], "2026-10-01")
        first_fcst = filas[118]
        self.assertEqual(first_fcst["fecha"], "2026-11-01")
        self.assertTrue(first_fcst["es_pronostico"])
        self.assertEqual(first_fcst["forecast"], first_fcst["valor"])

    def test_verify_sample_sin_golden(self) -> None:
        report = verify_planilla(self.series, source=str(SAMPLE), exigir_golden=False)
        self.assertTrue(report.ok, report.errores)


class FullPlanillaTests(unittest.TestCase):
    def test_golden_conteos(self) -> None:
        report = verify_planilla_path(FULL, exigir_golden=True)
        self.assertTrue(report.ok, report.errores)
        golden = json.loads(GOLDEN.read_text(encoding="utf-8"))
        self.assertEqual(report.n_productos, golden["n_productos"])
        self.assertEqual(report.n_meses_historia, 118)
        self.assertEqual(report.n_meses_pronostico, 14)


class MalformedTests(unittest.TestCase):
    def test_vacio(self) -> None:
        with self.assertRaises(ParseError):
            parse_planilla("")

    def test_delimitador_coma(self) -> None:
        text = (BAD / "comma.csv").read_text(encoding="utf-8")
        with self.assertRaises(ParseError) as ctx:
            parse_planilla(text)
        self.assertIn("delimitador", str(ctx.exception))

    def test_sin_productos(self) -> None:
        text = (BAD / "solo_encabezado.csv").read_text(encoding="utf-8")
        with self.assertRaises(ParseError) as ctx:
            parse_planilla(text)
        self.assertIn("encabezado", str(ctx.exception))

    def test_faltan_columnas(self) -> None:
        text = (BAD / "sin_sku.csv").read_text(encoding="utf-8")
        with self.assertRaises(ParseError) as ctx:
            parse_planilla(text)
        self.assertIn("SKU", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
