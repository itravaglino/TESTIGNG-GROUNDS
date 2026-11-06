"""Deterministic CSV fixtures for a demand-forecast auditor.

Bytes are UTF-8 with no BOM. Long files use the Spanish header
sku, descripcion, sucursal, fecha, pronostico, venta and ISO month
starts (YYYY-MM-DD). Generation uses only the standard library.
"""

from __future__ import annotations

import csv
import io
import math
from pathlib import Path

FIXTURE_NAMES = (
    "good_monthly",
    "bad_negative_flat",
    "explosive",
    "intermittent",
    "wide_spanish",
    "semicolon_decimal",
    "missing_and_dupes",
    "portfolio",
)

LONG_HEADER = ["sku", "descripcion", "sucursal", "fecha", "pronostico", "venta"]

WIDE_MONTHS = (
    "ene-2024",
    "feb-2024",
    "mar-2024",
    "abr-2024",
    "may-2024",
    "jun-2024",
)

# Population Syntetos-Boylan cutoffs used only to keep fixture classes stable.
_ADI_CUTOFF = 1.32
_CV2_CUTOFF = 0.49

_OUTPUT_DIR = Path("/tmp/collab/fixtures")


def build_fixtures() -> dict[str, bytes]:
    """Return named CSV payloads for the auditor cases."""
    fixtures = {
        "good_monthly": _good_monthly(),
        "bad_negative_flat": _bad_negative_flat(),
        "explosive": _explosive(),
        "intermittent": _intermittent(),
        "wide_spanish": _wide_spanish(),
        "semicolon_decimal": _semicolon_decimal(),
        "missing_and_dupes": _missing_and_dupes(),
        "portfolio": _portfolio(),
    }
    _validate(fixtures)
    return fixtures


def expected_signals() -> dict:
    """Qualitative outcomes a test should assert. Not exact scores.

    ``findings_any`` values are case-insensitive substrings. A finding
    matches when any stem appears in the auditor text for that series.
    ``decision_in`` lists the Spanish decisions that are acceptable.
    """
    return {
        "good_monthly": {
            "format": "long",
            "delimiter": ",",
            "decimal": ".",
            "sku": "GOOD01",
            "n_data_rows": 24,
            "date_start": "2023-01-01",
            "date_end": "2024-12-01",
            "seasonal_period": 12,
            "level": 100,
            "amplitude": 30,
            "forecast_rule": "pronostico_t = venta_{t-12} if t >= 12 else 100",
            "decision_in": ["aprobar"],
            "wape_under": 0.35,
            "triggers": "Seasonal-naive backtest should aprobar with WAPE under 0.35.",
        },
        "bad_negative_flat": {
            "format": "long",
            "delimiter": ",",
            "decimal": ".",
            "sku": "BADFLAT",
            "n_data_rows": 12,
            "date_start": "2024-01-01",
            "date_end": "2024-12-01",
            "pronostico_constant": -5,
            "venta_min": 80,
            "venta_max": 140,
            "decision_in": ["corregir", "descartar"],
            "findings_any": ["negativ", "menor que cero", "below zero"],
            "triggers": "Constant negative forecast should corregir or descartar, with a negative-value finding.",
        },
        "explosive": {
            "format": "long",
            "delimiter": ",",
            "decimal": ".",
            "sku": "SPIKE",
            "n_data_rows": 10,
            "date_start": "2024-01-01",
            "date_end": "2024-10-01",
            "typical_pronostico": 50,
            "typical_venta_around": 50,
            "last_pronostico": 5000,
            "decision_in": ["corregir", "descartar"],
            "findings_any": ["outlier", "explosion", "explos", "atipic", "pico", "extrem"],
            "triggers": "Smooth demand near 50 with a final forecast of 5000 should raise outlier or explosion.",
        },
        "intermittent": {
            "format": "long",
            "delimiter": ",",
            "decimal": ".",
            "sku": "LUMPY",
            "n_data_rows": 24,
            "date_start": "2023-01-01",
            "date_end": "2024-12-01",
            "pronostico_constant": 10,
            "nonzero_venta": {"2023-04-01": 20, "2023-10-01": 40, "2024-04-01": 24, "2024-10-01": 36},
            "demand_class_in": ["intermittent", "lumpy"],
            "decision_in": ["corregir", "descartar"],
            "triggers": "Mostly-zero demand with a flat 10 forecast; class intermittent or lumpy.",
        },
        "wide_spanish": {
            "format": "wide",
            "delimiter": ";",
            "decimal": ",",
            "codigo": "WIDE01",
            "n_data_rows": 1,
            "n_dates": 6,
            "dates": [
                "2024-01-01",
                "2024-02-01",
                "2024-03-01",
                "2024-04-01",
                "2024-05-01",
                "2024-06-01",
            ],
            "month_columns": list(WIDE_MONTHS),
            "venta_columns": [f"venta_{name}" for name in WIDE_MONTHS],
            "decimal_comma_example": {"column": "mar-2024", "text": "120,5", "value": 120.5},
            "triggers": "Wide Spanish parse should yield 6 month-start dates, with 120,5 read as 120.5.",
        },
        "semicolon_decimal": {
            "format": "long",
            "delimiter": ";",
            "decimal": ",",
            "skus": ["DEC-A", "DEC-B"],
            "n_skus": 2,
            "n_months": 6,
            "n_data_rows": 12,
            "date_start": "2024-01-01",
            "date_end": "2024-06-01",
            "triggers": "Long file with semicolon separator and decimal commas; 2 products, 6 months.",
        },
        "missing_and_dupes": {
            "format": "long",
            "delimiter": ",",
            "decimal": ".",
            "sku": "MISS01",
            "frequency": "monthly",
            "span_start": "2024-01-01",
            "span_end": "2024-07-01",
            "missing_months": ["2024-03-01"],
            "duplicate_fecha": "2024-04-01",
            "conflicting_pronostico": [90.0, 140.0],
            "duplicate_venta_each": 110.0,
            "findings_any": ["faltante", "hueco", "missing", "gap", "duplic", "repetid"],
            "triggers": "Interior missing month 2024-03 plus two different forecasts on 2024-04-01.",
        },
        "portfolio": {
            "format": "long",
            "delimiter": ",",
            "decimal": ".",
            "n_skus": 8,
            "n_months_each": 18,
            "n_data_rows": 144,
            "date_start": "2023-01-01",
            "date_end": "2024-06-01",
            "summary_nontrivial": True,
            "aprobar_skus": ["P01-SEAS", "P02-STABLE"],
            "not_aprobar_skus": [
                "P03-NEG",
                "P04-SPIKE",
                "P05-INTER",
                "P06-LUMPY",
                "P07-BIAS",
                "P08-TREND",
            ],
            "series": {
                "P01-SEAS": {
                    "decision_in": ["aprobar"],
                    "wape_under": 0.35,
                    "behavior": "seasonal naive",
                },
                "P02-STABLE": {
                    "decision_in": ["aprobar"],
                    "wape_under": 0.35,
                    "behavior": "stable level",
                },
                "P03-NEG": {
                    "decision_in": ["corregir", "descartar"],
                    "findings_any": ["negativ", "menor que cero", "below zero"],
                    "behavior": "negative flat forecast",
                },
                "P04-SPIKE": {
                    "decision_in": ["corregir", "descartar"],
                    "findings_any": ["outlier", "explosion", "explos", "atipic", "pico", "extrem"],
                    "behavior": "terminal forecast explosion",
                },
                "P05-INTER": {
                    "demand_class_in": ["intermittent", "lumpy"],
                    "decision_in": ["corregir", "descartar"],
                    "behavior": "intermittent demand, flat forecast",
                },
                "P06-LUMPY": {
                    "demand_class_in": ["lumpy"],
                    "decision_in": ["corregir", "descartar"],
                    "behavior": "lumpy demand, flat forecast",
                },
                "P07-BIAS": {
                    "decision_in": ["corregir", "descartar"],
                    "wape_over": 0.5,
                    "findings_any": ["sesgo", "bias", "sobre"],
                    "behavior": "large positive bias",
                },
                "P08-TREND": {
                    "decision_in": ["corregir", "descartar"],
                    "wape_over": 0.5,
                    "findings_any": ["tendenc", "trend", "sesgo", "bias"],
                    "behavior": "flat forecast against a rising trend",
                },
            },
            "triggers": "Eight mixed series so aprobar, corregir or descartar, negative, explosion, and both sparse classes all show up.",
        },
    }


def _encode(rows: list[list[str]], delimiter: str = ",") -> bytes:
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer, delimiter=delimiter, lineterminator="\n")
    writer.writerows(rows)
    return buffer.getvalue().encode("utf-8")


def _dot(value: float, places: int = 2) -> str:
    return f"{value:.{places}f}"


def _comma(value: float, places: int = 2) -> str:
    return _dot(value, places).replace(".", ",")


def _month_start(year: int, month: int, step: int = 0) -> str:
    index = (month - 1) + step
    year += index // 12
    month = index % 12 + 1
    return f"{year:04d}-{month:02d}-01"


def _months(year: int, month: int, count: int) -> list[str]:
    return [_month_start(year, month, step) for step in range(count)]


def _seasonal(index: int, level: float = 100.0, amplitude: float = 30.0, period: int = 12) -> float:
    raw = level + amplitude * math.sin(2.0 * math.pi * index / period)
    return round(raw, 2)


def _append_series(
    rows: list[list[str]],
    sku: str,
    descripcion: str,
    sucursal: str,
    dates: list[str],
    pronosticos: list[float],
    ventas: list[float],
    fmt=_dot,
) -> None:
    if not (len(dates) == len(pronosticos) == len(ventas)):
        raise RuntimeError(f"{sku} series lengths differ")
    for fecha, pronostico, venta in zip(dates, pronosticos, ventas):
        rows.append([sku, descripcion, sucursal, fecha, fmt(pronostico), fmt(venta)])


def _good_monthly() -> bytes:
    dates = _months(2023, 1, 24)
    ventas = [_seasonal(index) for index in range(24)]
    # Seasonal naive: last year when it exists, otherwise the level.
    pronosticos = [ventas[index - 12] if index >= 12 else 100.0 for index in range(24)]
    rows = [LONG_HEADER]
    _append_series(
        rows,
        "GOOD01",
        "Producto estacional",
        "CENTRO",
        dates,
        pronosticos,
        ventas,
    )
    return _encode(rows)


def _bad_negative_flat() -> bytes:
    dates = _months(2024, 1, 12)
    ventas = [_seasonal(index, level=110.0, amplitude=30.0) for index in range(12)]
    rows = [LONG_HEADER]
    _append_series(
        rows,
        "BADFLAT",
        "Pronóstico negativo plano",
        "SUR",
        dates,
        [-5.0] * 12,
        ventas,
    )
    return _encode(rows)


def _explosive() -> bytes:
    dates = _months(2024, 1, 10)
    ventas = [48.0, 51.0, 49.0, 53.0, 50.0, 47.0, 52.0, 50.0, 49.0, 51.0]
    pronosticos = [50.0] * 9 + [5000.0]
    rows = [LONG_HEADER]
    _append_series(
        rows,
        "SPIKE",
        "Pronóstico explosivo",
        "NORTE",
        dates,
        pronosticos,
        ventas,
    )
    return _encode(rows)


def _intermittent() -> bytes:
    dates = _months(2023, 1, 24)
    ventas = [0.0] * 24
    # Four hits inside 20-40. ADI is high and CV² stays low, so the
    # standard class is intermittent; a lumpy label is still acceptable.
    for index, value in ((3, 20.0), (9, 40.0), (15, 24.0), (21, 36.0)):
        ventas[index] = value
    rows = [LONG_HEADER]
    _append_series(
        rows,
        "LUMPY",
        "Demanda intermitente",
        "CENTRO",
        dates,
        [10.0] * 24,
        ventas,
    )
    return _encode(rows)


def _wide_spanish() -> bytes:
    venta_columns = [f"venta_{name}" for name in WIDE_MONTHS]
    header = ["codigo", "descripcion", *WIDE_MONTHS, *venta_columns]
    # One decimal comma (mar-2024). The other amounts are plain integers.
    forecasts = ["100", "110", "120,5", "130", "140", "150"]
    ventas = ["98", "109", "121", "127", "141", "148"]
    row = ["WIDE01", "Producto formato ancho", *forecasts, *ventas]
    return _encode([header, row], delimiter=";")


def _semicolon_decimal() -> bytes:
    dates = _months(2024, 1, 6)
    rows = [LONG_HEADER]
    _append_series(
        rows,
        "DEC-A",
        "Producto decimal A",
        "NORTE",
        dates,
        [10.40, 11.10, 12.20, 9.90, 13.30, 14.00],
        [10.50, 11.25, 12.00, 9.75, 13.50, 14.20],
        fmt=_comma,
    )
    _append_series(
        rows,
        "DEC-B",
        "Producto decimal B",
        "SUR",
        dates,
        [40.00, 42.40, 40.10, 41.20, 43.00, 44.50],
        [40.10, 42.60, 39.90, 41.00, 43.25, 44.80],
        fmt=_comma,
    )
    return _encode(rows, delimiter=";")


def _missing_and_dupes() -> bytes:
    # January through July 2024, March omitted, April repeated with two forecasts.
    rows = [LONG_HEADER]
    body = [
        ("2024-01-01", 100.0, 98.0),
        ("2024-02-01", 104.0, 101.0),
        ("2024-04-01", 90.0, 110.0),
        ("2024-04-01", 140.0, 110.0),
        ("2024-05-01", 108.0, 106.0),
        ("2024-06-01", 112.0, 109.0),
        ("2024-07-01", 116.0, 114.0),
    ]
    for fecha, pronostico, venta in body:
        rows.append(
            ["MISS01", "Hueco y duplicado", "CENTRO", fecha, _dot(pronostico), _dot(venta)]
        )
    return _encode(rows)


def _portfolio() -> bytes:
    dates = _months(2023, 1, 18)
    rows = [LONG_HEADER]

    seasonal_venta = [_seasonal(index) for index in range(18)]
    seasonal_pron = [seasonal_venta[index - 12] if index >= 12 else 100.0 for index in range(18)]
    _append_series(
        rows, "P01-SEAS", "Portfolio estacional", "CENTRO", dates, seasonal_pron, seasonal_venta
    )

    ripple = (0.0, 2.0, -1.0, 3.0, -2.0, 1.0, -3.0, 2.0, 0.0, 4.0, -2.0, 1.0, 3.0, -1.0, 2.0, -4.0, 1.0, 0.0)
    _append_series(
        rows,
        "P02-STABLE",
        "Portfolio estable",
        "NORTE",
        dates,
        [200.0] * 18,
        [200.0 + delta for delta in ripple],
    )

    negative_venta = [80.0 + (index % 7) * 10.0 for index in range(18)]
    _append_series(
        rows,
        "P03-NEG",
        "Pronóstico negativo plano",
        "SUR",
        dates,
        [-5.0] * 18,
        negative_venta,
    )

    spike_venta = [
        48.0, 51.0, 49.0, 53.0, 50.0, 47.0, 52.0, 50.0, 49.0,
        51.0, 48.0, 52.0, 50.0, 49.0, 53.0, 47.0, 51.0, 50.0,
    ]
    _append_series(
        rows,
        "P04-SPIKE",
        "Explosión en el cierre",
        "CENTRO",
        dates,
        [50.0] * 17 + [5000.0],
        spike_venta,
    )

    intermittent = [0.0] * 18
    for index, value in ((2, 22.0), (8, 35.0), (14, 28.0)):
        intermittent[index] = value
    _append_series(
        rows,
        "P05-INTER",
        "Demanda intermitente",
        "NORTE",
        dates,
        [10.0] * 18,
        intermittent,
    )

    lumpy = [0.0] * 18
    for index, value in ((1, 10.0), (6, 80.0), (12, 12.0), (16, 100.0)):
        lumpy[index] = value
    _append_series(
        rows,
        "P06-LUMPY",
        "Demanda irregular",
        "SUR",
        dates,
        [15.0] * 18,
        lumpy,
    )

    _append_series(
        rows,
        "P07-BIAS",
        "Sesgo alto",
        "ESTE",
        dates,
        [180.0] * 18,
        [100.0] * 18,
    )

    _append_series(
        rows,
        "P08-TREND",
        "Tendencia creciente",
        "OESTE",
        dates,
        [100.0] * 18,
        [100.0 + 15.0 * index for index in range(18)],
    )
    return _encode(rows)


def _parse(payload: bytes, delimiter: str = ",") -> list[list[str]]:
    text = payload.decode("utf-8")
    if text.startswith("\ufeff"):
        raise RuntimeError("fixture must be UTF-8 without a BOM")
    if "\r" in text:
        raise RuntimeError("fixture must use LF line endings")
    if not text.endswith("\n"):
        raise RuntimeError("fixture must end with a newline")
    return list(csv.reader(io.StringIO(text), delimiter=delimiter))


def _as_float(text: str) -> float:
    return float(text.replace(",", "."))


def _wape(actuals: list[float], forecasts: list[float]) -> float:
    scale = sum(abs(value) for value in actuals)
    if scale == 0:
        raise RuntimeError("WAPE scale is zero")
    error = sum(abs(actual - forecast) for actual, forecast in zip(actuals, forecasts))
    return error / scale


def _demand_class(actuals: list[float]) -> str:
    nonzero = [value for value in actuals if value != 0]
    if not nonzero:
        return "zero"
    adi = len(actuals) / len(nonzero)
    mean = sum(nonzero) / len(nonzero)
    variance = sum((value - mean) ** 2 for value in nonzero) / len(nonzero)
    cv2 = variance / (mean * mean) if mean else 0.0
    if adi >= _ADI_CUTOFF and cv2 >= _CV2_CUTOFF:
        return "lumpy"
    if adi >= _ADI_CUTOFF:
        return "intermittent"
    if cv2 >= _CV2_CUTOFF:
        return "erratic"
    return "smooth"


def _columns(table: list[list[str]]) -> dict[str, int]:
    header = table[0]
    return {name: index for index, name in enumerate(header)}


def _series_map(table: list[list[str]]) -> dict[str, list[tuple[str, float, float]]]:
    index = _columns(table)
    grouped: dict[str, list[tuple[str, float, float]]] = {}
    for row in table[1:]:
        sku = row[index["sku"]]
        grouped.setdefault(sku, []).append(
            (row[index["fecha"]], _as_float(row[index["pronostico"]]), _as_float(row[index["venta"]]))
        )
    return grouped


def _assert_month_span(dates: list[str], start: str, count: int) -> None:
    expected = _months(int(start[0:4]), int(start[5:7]), count)
    if dates != expected:
        raise RuntimeError(f"expected {expected[0]}..{expected[-1]}, got {dates[0]}..{dates[-1]}")


def _validate(fixtures: dict[str, bytes]) -> None:
    if tuple(fixtures) != FIXTURE_NAMES:
        raise RuntimeError("fixture names drifted")
    if tuple(expected_signals()) != FIXTURE_NAMES:
        raise RuntimeError("expected_signals names drifted")
    for name, payload in fixtures.items():
        if not isinstance(payload, bytes) or not payload:
            raise RuntimeError(f"{name} is empty")

    good = _parse(fixtures["good_monthly"])
    if good[0] != LONG_HEADER:
        raise RuntimeError("good_monthly header")
    good_rows = _series_map(good)["GOOD01"]
    if len(good_rows) != 24:
        raise RuntimeError("good_monthly row count")
    _assert_month_span([row[0] for row in good_rows], "2023-01-01", 24)
    good_pron = [row[1] for row in good_rows]
    good_venta = [row[2] for row in good_rows]
    for index, venta in enumerate(good_venta):
        if abs(venta - _seasonal(index)) > 1e-9:
            raise RuntimeError("good_monthly seasonality drifted")
        expected_pron = good_venta[index - 12] if index >= 12 else 100.0
        if abs(good_pron[index] - expected_pron) > 1e-9:
            raise RuntimeError("good_monthly seasonal naive drifted")
    if _wape(good_venta, good_pron) >= 0.35:
        raise RuntimeError("good_monthly WAPE is not under 0.35")

    bad = _series_map(_parse(fixtures["bad_negative_flat"]))["BADFLAT"]
    if len(bad) != 12 or any(row[1] != -5.0 for row in bad):
        raise RuntimeError("bad_negative_flat forecast")
    bad_venta = [row[2] for row in bad]
    if min(bad_venta) < 80 or max(bad_venta) > 140 or len(set(bad_venta)) < 2:
        raise RuntimeError("bad_negative_flat actuals")
    _assert_month_span([row[0] for row in bad], "2024-01-01", 12)

    spike = _series_map(_parse(fixtures["explosive"]))["SPIKE"]
    if len(spike) != 10 or spike[-1][1] != 5000.0 or any(row[1] != 50.0 for row in spike[:-1]):
        raise RuntimeError("explosive forecast")
    if any(not 45.0 <= row[2] <= 55.0 for row in spike):
        raise RuntimeError("explosive actuals")
    _assert_month_span([row[0] for row in spike], "2024-01-01", 10)

    lumpy = _series_map(_parse(fixtures["intermittent"]))["LUMPY"]
    if len(lumpy) != 24 or any(row[1] != 10.0 for row in lumpy):
        raise RuntimeError("intermittent forecast")
    nonzero = [row[2] for row in lumpy if row[2] != 0]
    if len(nonzero) != 4 or any(not 20.0 <= value <= 40.0 for value in nonzero):
        raise RuntimeError("intermittent actuals")
    if _demand_class([row[2] for row in lumpy]) not in {"intermittent", "lumpy"}:
        raise RuntimeError("intermittent class")
    _assert_month_span([row[0] for row in lumpy], "2023-01-01", 24)

    wide_text = fixtures["wide_spanish"].decode("utf-8")
    wide = _parse(fixtures["wide_spanish"], delimiter=";")
    if len(wide) != 2:
        raise RuntimeError("wide_spanish should be one data row")
    if wide[0] != ["codigo", "descripcion", *WIDE_MONTHS, *[f"venta_{name}" for name in WIDE_MONTHS]]:
        raise RuntimeError("wide_spanish header")
    if wide[1][wide[0].index("mar-2024")] != "120,5":
        raise RuntimeError("wide_spanish decimal comma")
    if wide_text.splitlines()[1].count(",") != 1:
        raise RuntimeError("wide_spanish should contain one decimal comma")

    decimal_rows = _parse(fixtures["semicolon_decimal"], delimiter=";")
    if decimal_rows[0] != LONG_HEADER:
        raise RuntimeError("semicolon_decimal header")
    decimal_series = _series_map(decimal_rows)
    if set(decimal_series) != {"DEC-A", "DEC-B"}:
        raise RuntimeError("semicolon_decimal skus")
    for sku, series in decimal_series.items():
        if len(series) != 6:
            raise RuntimeError(f"{sku} month count")
        _assert_month_span([row[0] for row in series], "2024-01-01", 6)
    for row in decimal_rows[1:]:
        for raw in (row[4], row[5]):
            if "," not in raw or "." in raw:
                raise RuntimeError("semicolon_decimal numeric format")

    missing = _parse(fixtures["missing_and_dupes"])
    if missing[0] != LONG_HEADER:
        raise RuntimeError("missing_and_dupes header")
    fechas = [row[3] for row in missing[1:]]
    if "2024-03-01" in fechas or fechas.count("2024-04-01") != 2:
        raise RuntimeError("missing_and_dupes calendar")
    april = [row for row in missing[1:] if row[3] == "2024-04-01"]
    april_pron = sorted(_as_float(row[4]) for row in april)
    if april_pron != [90.0, 140.0] or any(row[5] != "110.00" for row in april):
        raise RuntimeError("missing_and_dupes conflict")

    portfolio = _series_map(_parse(fixtures["portfolio"]))
    expected_skus = (
        "P01-SEAS",
        "P02-STABLE",
        "P03-NEG",
        "P04-SPIKE",
        "P05-INTER",
        "P06-LUMPY",
        "P07-BIAS",
        "P08-TREND",
    )
    if tuple(portfolio) != expected_skus:
        raise RuntimeError("portfolio skus")
    for sku, series in portfolio.items():
        if len(series) != 18:
            raise RuntimeError(f"{sku} length")
        _assert_month_span([row[0] for row in series], "2023-01-01", 18)
    seas_pron = [row[1] for row in portfolio["P01-SEAS"]]
    seas_venta = [row[2] for row in portfolio["P01-SEAS"]]
    stable_pron = [row[1] for row in portfolio["P02-STABLE"]]
    stable_venta = [row[2] for row in portfolio["P02-STABLE"]]
    if _wape(seas_venta, seas_pron) >= 0.35 or _wape(stable_venta, stable_pron) >= 0.35:
        raise RuntimeError("portfolio healthy WAPE")
    if any(row[1] != -5.0 for row in portfolio["P03-NEG"]):
        raise RuntimeError("portfolio negative")
    if portfolio["P04-SPIKE"][-1][1] != 5000.0:
        raise RuntimeError("portfolio explosion")
    if _demand_class([row[2] for row in portfolio["P05-INTER"]]) != "intermittent":
        raise RuntimeError("portfolio intermittent class")
    if _demand_class([row[2] for row in portfolio["P06-LUMPY"]]) != "lumpy":
        raise RuntimeError("portfolio lumpy class")
    bias_venta = [row[2] for row in portfolio["P07-BIAS"]]
    bias_pron = [row[1] for row in portfolio["P07-BIAS"]]
    trend_venta = [row[2] for row in portfolio["P08-TREND"]]
    trend_pron = [row[1] for row in portfolio["P08-TREND"]]
    if _wape(bias_venta, bias_pron) <= 0.5 or _wape(trend_venta, trend_pron) <= 0.5:
        raise RuntimeError("portfolio bad WAPE")
    if any(trend_venta[index] >= trend_venta[index + 1] for index in range(17)):
        raise RuntimeError("portfolio trend shape")


def main() -> None:
    _OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for name, payload in build_fixtures().items():
        (_OUTPUT_DIR / f"{name}.csv").write_bytes(payload)


if __name__ == "__main__":
    main()
