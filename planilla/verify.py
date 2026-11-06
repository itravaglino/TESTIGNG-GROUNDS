from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .parse import ForecastSeries, ParseError, parse_planilla_path

GOLDEN_PATH = (
    Path(__file__).resolve().parent.parent
    / "fixtures"
    / "planilla-estandar"
    / "golden_stats.json"
)


@dataclass
class CheckResult:
    nombre: str
    ok: bool
    detalle: str


@dataclass
class VerifyReport:
    ok: bool
    archivo: str
    n_productos: int
    n_meses_historia: int
    n_meses_pronostico: int
    chequeos: list[CheckResult] = field(default_factory=list)
    errores: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "archivo": self.archivo,
            "n_productos": self.n_productos,
            "n_meses_historia": self.n_meses_historia,
            "n_meses_pronostico": self.n_meses_pronostico,
            "chequeos": [c.__dict__ for c in self.chequeos],
            "errores": self.errores,
        }


def _check(nombre: str, ok: bool, detalle: str) -> CheckResult:
    return CheckResult(nombre, ok, detalle)


def verify_planilla(
    series: list[ForecastSeries],
    *,
    source: str = "",
    golden: dict[str, Any] | None = None,
    exigir_golden: bool = False,
) -> VerifyReport:
    errores: list[str] = []
    chequeos: list[CheckResult] = []
    if not series:
        return VerifyReport(False, source, 0, 0, 0, [], ["sin series"])

    n_hist = len(series[0].historia)
    n_fcst = len(series[0].pronostico)
    chequeos.append(
        _check(
            "horizonte_uniforme",
            all(len(s.historia) == n_hist and len(s.pronostico) == n_fcst for s in series),
            f"historia={n_hist} pronostico={n_fcst}",
        )
    )
    chequeos.append(
        _check(
            "ids_unicos",
            len({s.product_id for s in series}) == len(series),
            f"{len(series)} productos",
        )
    )
    chequeos.append(
        _check(
            "sku_presente",
            all(s.sku for s in series),
            "todas las filas tienen SKU",
        )
    )
    chequeos.append(
        _check(
            "hay_historia_y_pronostico",
            n_hist >= 12 and n_fcst >= 1,
            f"historia={n_hist} pronostico={n_fcst}",
        )
    )
    hist_vals = [
        p.valor
        for s in series
        for p in s.historia
        if p.valor is not None
    ]
    fcst_decimal = sum(
        1
        for s in series
        for p in s.pronostico
        if p.crudo and "," in p.crudo
    )
    chequeos.append(
        _check(
            "historia_parseable",
            all(p.valor is not None or p.crudo.strip() == "" for s in series for p in s.historia),
            f"{len(hist_vals)} valores de historia",
        )
    )
    chequeos.append(
        _check(
            "pronostico_detectado",
            n_fcst > 0,
            f"{fcst_decimal} celdas de pronóstico con coma decimal",
        )
    )

    if golden is None and exigir_golden and GOLDEN_PATH.exists():
        golden = json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))
    if golden and exigir_golden:
        modelos = Counter(s.meta.get("Modelo", "") for s in series)
        chequeos.append(
            _check(
                "n_productos_golden",
                len(series) == golden["n_productos"],
                f"{len(series)} vs {golden['n_productos']}",
            )
        )
        chequeos.append(
            _check(
                "n_meses_golden",
                n_hist == golden["n_meses_historia"] and n_fcst == golden["n_meses_pronostico"],
                f"{n_hist}+{n_fcst} vs {golden['n_meses_historia']}+{golden['n_meses_pronostico']}",
            )
        )
        chequeos.append(
            _check(
                "modelos_golden",
                dict(modelos) == golden["modelos"],
                str(dict(modelos)),
            )
        )
        ctrl = golden["producto_control"]
        found = next((s for s in series if s.product_id == ctrl["product_id"]), None)
        if found is None:
            chequeos.append(_check("producto_control", False, "no está el product_id de control"))
        else:
            h0 = found.historia[0].crudo
            hlast = found.historia[-1].crudo
            f0 = found.pronostico[0].crudo
            ok_ctrl = (
                found.sku == ctrl["sku"]
                and h0 == ctrl["historia_2017_01"]
                and hlast == ctrl["historia_2026_10"]
                and f0 == ctrl["pronostico_2026_11"]
            )
            chequeos.append(
                _check(
                    "producto_control",
                    ok_ctrl,
                    f"sku={found.sku} hist0={h0} hist_last={hlast} fcst0={f0}",
                )
            )

    errores = [c.nombre + ": " + c.detalle for c in chequeos if not c.ok]
    return VerifyReport(
        ok=not errores,
        archivo=source,
        n_productos=len(series),
        n_meses_historia=n_hist,
        n_meses_pronostico=n_fcst,
        chequeos=chequeos,
        errores=errores,
    )


def verify_planilla_path(
    path: str | Path, *, exigir_golden: bool | None = None
) -> VerifyReport:
    path = Path(path)
    if exigir_golden is None:
        exigir_golden = path.name.startswith("Forecast_mann_scenario_test4")
    try:
        series = parse_planilla_path(path)
    except ParseError as exc:
        return VerifyReport(False, str(path), 0, 0, 0, [], [str(exc)])
    golden = None
    if exigir_golden and GOLDEN_PATH.exists():
        golden = json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))
    return verify_planilla(
        series, source=str(path), golden=golden, exigir_golden=exigir_golden
    )


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        description="Verifica que un CSV cumpla el contrato de la planilla estándar."
    )
    parser.add_argument("csv", nargs="?", help="Ruta al CSV a verificar")
    parser.add_argument(
        "--golden",
        action="store_true",
        help="Exigir conteos de la planilla completa (4402 SKUs, etc.)",
    )
    parser.add_argument("--json", action="store_true", help="Salida JSON")
    args = parser.parse_args(argv)
    default = (
        Path(__file__).resolve().parent.parent
        / "fixtures"
        / "planilla-estandar"
        / "Forecast_mann_scenario_test4_unidades.csv"
    )
    target = Path(args.csv) if args.csv else default
    report = verify_planilla_path(target, exigir_golden=args.golden or None)
    if args.json:
        print(json.dumps(report.as_dict(), ensure_ascii=False, indent=2))
    else:
        estado = "OK" if report.ok else "FAIL"
        print(f"[{estado}] {report.archivo}")
        print(
            f"productos={report.n_productos} historia={report.n_meses_historia} "
            f"pronostico={report.n_meses_pronostico}"
        )
        for c in report.chequeos:
            marca = "PASS" if c.ok else "FAIL"
            print(f"  {marca:4} {c.nombre}: {c.detalle}")
        for e in report.errores:
            print(f"  error: {e}")
    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
