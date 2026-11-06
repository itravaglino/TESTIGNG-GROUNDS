"""Error metrics. All percentage-like scores are RATIOS (0.11 = 11%).

error_t = forecast_t - actual_t
"""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class MetricSet:
    n: int
    mae: float | None
    me: float | None
    rmse: float | None
    mape: float | None
    smape: float | None
    wape: float | None
    bias_ratio: float | None


def _pairs(
    actual: list[float | None] | tuple[float | None, ...],
    forecast: list[float | None] | tuple[float | None, ...],
) -> list[tuple[float, float]]:
    if len(actual) != len(forecast):
        raise ValueError("actual y forecast deben tener la misma longitud")
    out: list[tuple[float, float]] = []
    for a, f in zip(actual, forecast, strict=True):
        if a is None or f is None:
            continue
        if math.isnan(a) or math.isnan(f):
            continue
        out.append((float(a), float(f)))
    return out


def compute_metrics(
    actual: list[float | None] | tuple[float | None, ...],
    forecast: list[float | None] | tuple[float | None, ...],
) -> MetricSet:
    pairs = _pairs(actual, forecast)
    n = len(pairs)
    if n == 0:
        return MetricSet(0, None, None, None, None, None, None, None)
    abs_err = [abs(f - a) for a, f in pairs]
    err = [f - a for a, f in pairs]
    mae = sum(abs_err) / n
    me = sum(err) / n
    rmse = math.sqrt(sum(e * e for e in err) / n)
    denom_abs_a = [abs(a) for a, _ in pairs if a != 0]
    mape = (
        sum(abs(f - a) / abs(a) for a, f in pairs if a != 0) / len(denom_abs_a)
        if denom_abs_a
        else None
    )
    smape_terms = []
    for a, f in pairs:
        den = abs(a) + abs(f)
        if den > 0:
            smape_terms.append(2.0 * abs(f - a) / den)
    smape = sum(smape_terms) / len(smape_terms) if smape_terms else None
    sum_abs_a = sum(abs(a) for a, _ in pairs)
    wape = sum(abs_err) / sum_abs_a if sum_abs_a else None
    sum_a = sum(a for a, _ in pairs)
    bias_ratio = sum(err) / sum_a if sum_a else None
    return MetricSet(n, mae, me, rmse, mape, smape, wape, bias_ratio)


def naive_seasonal_holdout(
    history: tuple[float | None, ...] | list[float | None],
    season: int = 12,
    holdout: int = 12,
) -> MetricSet:
    """Score a seasonal-naive baseline on the last `holdout` history months.

    Use this when the Mann file has no archived forecast for past months.
    """
    vals = list(history)
    if len(vals) < holdout + season:
        return MetricSet(0, None, None, None, None, None, None, None)
    actual = vals[-holdout:]
    forecast = vals[-holdout - season : -season]
    return compute_metrics(actual, forecast)
