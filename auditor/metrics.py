"""Profile and accuracy metrics for one product's demand forecast.

Errors are forecast minus actual (positive means over-forecast).
``accuracy_metrics`` always includes ``error_sign`` =
``"forecast_minus_actual"``.

Scales
------
Shares in ``[0, 1]`` (not 0–100): ``zero_forecast_pct``,
``negative_forecast_pct``, ``missing_forecast_pct``, ``zero_actual_pct``,
``negative_actual_pct``, ``flatness``, ``over_forecast_pct``,
``under_forecast_pct``, ``hit_rate_10``, ``hit_rate_20``,
``seasonality_strength``.

Percentages (×100): ``bias_pct``, ``mpe``, ``mape``, ``mape_positive_only``,
``mdape``.

``smape`` is the mean of ``200 * |f-a| / (|f|+|a|)`` (about 0–200).
``wape`` is ``sum(|f-a|) / sum(|a|)`` with no extra ×100.
MAPE-family percentages use ``|a|`` in the denominator. MPE and ``bias_pct``
keep the signed actual (or sum of actuals) in the denominator.

Nulls and definitions are on ``series_profile`` and ``accuracy_metrics``.
Floats are rounded to 6 decimal places. Non-finite results are ``None``.
Counts are plain ``int``. No NaN or Inf is returned.
"""

from __future__ import annotations

import math
import re

import numpy as np
import pandas as pd

__all__ = ["series_profile", "accuracy_metrics"]

_SEASON_PERIOD = {"D": 7, "W": 52, "M": 12, "Q": 4}
_ADI_INTERMITTENT = 1.32
_CV2_ERRATIC = 0.49
_TREND_FLAT_FRACTION = 0.02
_HIT_EPS = 1e-9
_FLAT_ATOL = 1e-6
_FLAT_RTOL = 0.001  # 0.1% of local level

_PROFILE_INTS = {
    "n_forecast",
    "n_actual",
    "n_overlap",
    "missing_date_gaps",
    "unique_forecast_values",
}
_PROFILE_STRS = {"start", "end", "demand_class", "trend_direction"}

_FREQ_RE = re.compile(r"(\d+)?([A-Z][A-Z\-]*)")


def _num(value):
    """Float rounded to 6 decimals, or None if missing / non-finite."""
    if value is None or isinstance(value, (bool, np.bool_)):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    number = round(number, 6)
    if number == 0.0:
        return 0.0
    return number


def _finite_mask(values: np.ndarray) -> np.ndarray:
    return np.isfinite(values)


def _freq_kind(frequency) -> str:
    """Map a frequency label to D, W, M, Q, or I (irregular)."""
    if frequency is None:
        return "I"
    token = str(frequency).strip().upper().replace(" ", "")
    if token in {"", "IRREGULAR", "IRR", "NONE", "NA", "N/A", "NULL"}:
        return "I"
    match = _FREQ_RE.fullmatch(token)
    word = match.group(2) if match else token
    if word in {"D", "DAY", "DAYS", "DAILY"}:
        return "D"
    if word in {"W", "WEEK", "WEEKS", "WEEKLY"} or word.startswith("W-"):
        return "W"
    if word in {"M", "MS", "ME", "MONTH", "MONTHS", "MONTHLY", "MTH"}:
        return "M"
    if word in {"Q", "QS", "QE", "QUARTER", "QUARTERS", "QUARTERLY"} or word.startswith(
        ("Q-", "QS", "QE")
    ):
        return "Q"
    return "I"


def _prepare(df: pd.DataFrame) -> pd.DataFrame:
    dates = pd.to_datetime(df["date"], errors="coerce")
    if getattr(dates.dt, "tz", None) is not None:
        dates = dates.dt.tz_convert("UTC").dt.tz_localize(None)
    forecast = pd.to_numeric(df["forecast"], errors="coerce").to_numpy(
        dtype=np.float64, copy=True
    )
    actual = pd.to_numeric(df["actual"], errors="coerce").to_numpy(
        dtype=np.float64, copy=True
    )
    forecast[~np.isfinite(forecast)] = np.nan
    actual[~np.isfinite(actual)] = np.nan
    frame = pd.DataFrame(
        {
            "date": pd.to_datetime(np.asarray(dates.to_numpy())),
            "forecast": forecast,
            "actual": actual,
        }
    )
    frame = frame.dropna(subset=["date"])
    return frame.sort_values("date", kind="mergesort").reset_index(drop=True)


def _ordinals(dates: pd.Series, kind: str) -> np.ndarray:
    """Period index from the first timestamp. Irregular data uses row order."""
    n = len(dates)
    if n == 0 or kind == "I":
        return np.arange(n, dtype=np.int64)
    origin = pd.Timestamp(dates.iloc[0]).normalize()
    if kind == "D":
        days = (dates.dt.normalize() - origin).dt.days.to_numpy()
        return np.asarray(days, dtype=np.int64)
    if kind == "W":
        days = (dates.dt.normalize() - origin).dt.days.to_numpy()
        return np.asarray(days, dtype=np.int64) // np.int64(7)
    if kind == "M":
        return (
            (dates.dt.year.to_numpy(dtype=np.int64) - np.int64(origin.year)) * np.int64(12)
            + (dates.dt.month.to_numpy(dtype=np.int64) - np.int64(origin.month))
        ).astype(np.int64, copy=False)
    if kind == "Q":
        return (
            (dates.dt.year.to_numpy(dtype=np.int64) - np.int64(origin.year)) * np.int64(4)
            + (dates.dt.quarter.to_numpy(dtype=np.int64) - np.int64(origin.quarter))
        ).astype(np.int64, copy=False)
    return np.arange(n, dtype=np.int64)


def _missing_gaps(ordinals: np.ndarray, kind: str) -> int:
    if kind == "I" or ordinals.size == 0:
        return 0
    uniq = np.unique(ordinals)
    span = int(uniq[-1] - uniq[0] + 1)
    return int(span - int(uniq.size))


def _period_map(ordinals: np.ndarray, values: np.ndarray) -> dict[int, float]:
    """Last finite value in each period."""
    found: dict[int, float] = {}
    for ordinal, value in zip(ordinals, values):
        number = float(value)
        if math.isfinite(number):
            found[int(ordinal)] = number
    return found


def _mean_std_cv(values: np.ndarray):
    """Sample mean, sample std (ddof=1), and std/mean.

    Mean is None when there are no values. Std and CV are None when fewer
    than 2 values. CV is also None when the mean is 0.
    """
    if values.size == 0:
        return None, None, None
    mean = float(np.mean(values))
    if not math.isfinite(mean):
        mean = None
    if values.size < 2 or mean is None:
        return mean, None, None
    std = float(np.std(values, ddof=1))
    if not math.isfinite(std):
        return mean, None, None
    if mean == 0.0:
        return mean, std, None
    return mean, std, std / mean


def _ols_slope(ordinals: np.ndarray, values: np.ndarray):
    """Simple OLS slope of ``values`` on period index. Needs >= 4 finite points."""
    mask = _finite_mask(values)
    if int(mask.sum()) < 4:
        return None, None
    x = ordinals[mask].astype(np.float64)
    y = values[mask].astype(np.float64)
    y_mean = float(np.mean(y))
    x_centered = x - float(np.mean(x))
    denom = float(np.dot(x_centered, x_centered))
    if denom == 0.0 or not math.isfinite(denom) or not math.isfinite(y_mean):
        return None, None
    slope = float(np.dot(x_centered, y - y_mean) / denom)
    if not math.isfinite(slope):
        return None, None
    return slope, y_mean


def _trend_direction(slope, level) -> str:
    slope_r = _num(slope)
    level_r = _num(level)
    if slope_r is None:
        return "unknown"
    level_abs = 0.0 if level_r is None else abs(level_r)
    if slope_r == 0.0 or abs(slope_r) < (_TREND_FLAT_FRACTION * level_abs):
        return "flat"
    if slope_r > 0.0:
        return "up"
    return "down"


def _adi(ordinals: np.ndarray, actual: np.ndarray):
    """Mean gap, in periods, between periods that contain a non-zero actual."""
    if not np.any(_finite_mask(actual)):
        return None
    demand_periods = set()
    for ordinal, value in zip(ordinals, actual):
        number = float(value)
        if math.isfinite(number) and number != 0.0:
            demand_periods.add(int(ordinal))
    if len(demand_periods) < 2:
        return None
    ordered = np.array(sorted(demand_periods), dtype=np.float64)
    return float(np.mean(np.diff(ordered)))


def _cv2_nonzero(actual: np.ndarray):
    """Squared sample CV of non-zero actual observations. None if <2 or mean 0."""
    nonzero = actual[_finite_mask(actual) & (actual != 0.0)]
    if nonzero.size < 2:
        return None
    mean = float(np.mean(nonzero))
    if mean == 0.0 or not math.isfinite(mean):
        return None
    std = float(np.std(nonzero, ddof=1))
    if not math.isfinite(std):
        return None
    return (std / mean) ** 2


def _demand_class(n_actual: int, adi, cv2: float | None) -> str:
    if n_actual < 6 or adi is None or cv2 is None:
        return "unknown"
    intermittent = adi >= _ADI_INTERMITTENT
    erratic = cv2 >= _CV2_ERRATIC
    if intermittent and erratic:
        return "lumpy"
    if intermittent:
        return "intermittent"
    if erratic:
        return "erratic"
    return "smooth"


def _flatness(forecast: np.ndarray):
    """Share of successive finite forecast steps that are almost zero.

    A step is flat when ``|Δ| <= max(1e-6, 0.001 * max(|f_t|, |f_{t+1}|))``.
    None if fewer than 2 finite forecasts.
    """
    values = forecast[_finite_mask(forecast)]
    if values.size < 2:
        return None
    delta = np.diff(values)
    level = np.maximum(np.abs(values[:-1]), np.abs(values[1:]))
    tolerance = np.maximum(_FLAT_ATOL, _FLAT_RTOL * level)
    return float(np.mean(np.abs(delta) <= tolerance))


def _history_ratio(dates: pd.Series, forecast: np.ndarray, actual: np.ndarray):
    """mean(forecast on future-only rows) / mean(actual).

    Future-only rows have a forecast, no actual, and a calendar date strictly
    after the last actual. None if either mean is missing or the actual mean is 0.
    """
    actual_ok = _finite_mask(actual)
    if not np.any(actual_ok):
        return None
    normalized = dates.dt.normalize()
    last_actual = normalized[actual_ok].max()
    future = _finite_mask(forecast) & ~actual_ok & (normalized > last_actual).to_numpy()
    if not np.any(future):
        return None
    mean_forecast = float(np.mean(forecast[future]))
    mean_actual = float(np.mean(actual[actual_ok]))
    if (
        mean_actual == 0.0
        or not math.isfinite(mean_forecast)
        or not math.isfinite(mean_actual)
    ):
        return None
    return mean_forecast / mean_actual


def _last_finite(values: np.ndarray):
    indexes = np.flatnonzero(_finite_mask(values))
    if indexes.size == 0:
        return None
    return float(values[indexes[-1]])


def _iso_date(value) -> str | None:
    if value is None or pd.isna(value):
        return None
    return pd.Timestamp(value).date().isoformat()


def _seasonality_strength(ordinals: np.ndarray, values: np.ndarray, period: int, min_points: int):
    """Clipped R² of the seasonal-naive forecast on actuals.

    ``max(0, min(1, 1 - SSE / SST))`` where SSE is the sum of squared
    seasonal-naive errors ``(y_t - y_{t-m})`` and SST is the sum of squared
    deviations of those same ``y_t`` from their mean. Sample points are one
    value per period (last row in the period).

    None when there are fewer than ``min_points`` finite observations or fewer
    than 2 seasonal pairs. 0 when the paired tail has no variation.
    """
    if int(_finite_mask(values).sum()) < min_points:
        return None
    series = _period_map(ordinals, values)
    tail: list[float] = []
    sse = 0.0
    for ordinal in sorted(series):
        previous = series.get(ordinal - period)
        if previous is None:
            continue
        current = series[ordinal]
        error = current - previous
        tail.append(current)
        sse += error * error
    if len(tail) < 2:
        return None
    tail_arr = np.asarray(tail, dtype=np.float64)
    sst = float(np.sum((tail_arr - float(np.mean(tail_arr))) ** 2))
    if sst <= 0.0:
        return 0.0
    strength = 1.0 - sse / sst
    if not math.isfinite(strength):
        return None
    if strength < 0.0:
        return 0.0
    if strength > 1.0:
        return 1.0
    return strength


def _profile_seasonality(ordinals: np.ndarray, actual: np.ndarray, kind: str):
    # Monthly and weekly only. Daily, quarterly, and irregular stay None.
    if kind == "M":
        return _seasonality_strength(ordinals, actual, _SEASON_PERIOD["M"], 24)
    if kind == "W":
        return _seasonality_strength(ordinals, actual, _SEASON_PERIOD["W"], 104)
    return None


def _abs_naive_errors(series: dict[int, float], lag: int) -> np.ndarray:
    errors = []
    for ordinal, value in series.items():
        previous = series.get(ordinal - lag)
        if previous is None:
            continue
        errors.append(abs(value - previous))
    if not errors:
        return np.zeros(0, dtype=np.float64)
    return np.asarray(errors, dtype=np.float64)


def _naive_scale(series: dict[int, float], kind: str) -> np.ndarray:
    """In-sample naive absolute errors on actuals.

    Seasonal period is 7/52/12/4 for D/W/M/Q. Seasonal is used when at least
    one pair exists; otherwise lag-1. Irregular series always use lag-1.
    """
    period = _SEASON_PERIOD.get(kind)
    if period is not None:
        seasonal = _abs_naive_errors(series, period)
        if seasonal.size >= 1:
            return seasonal
    return _abs_naive_errors(series, 1)


def _paired_errors(ordinals, actual, forecast, lag: int):
    """Model (f-a) and naive (a - a_lag) on overlap rows whose lag actual exists."""
    series = _period_map(ordinals, actual)
    model = []
    naive = []
    for ordinal, actual_value, forecast_value in zip(ordinals, actual, forecast):
        actual_value = float(actual_value)
        forecast_value = float(forecast_value)
        if not (math.isfinite(actual_value) and math.isfinite(forecast_value)):
            continue
        previous = series.get(int(ordinal) - lag)
        if previous is None:
            continue
        model.append(forecast_value - actual_value)
        naive.append(actual_value - previous)
    return (
        np.asarray(model, dtype=np.float64),
        np.asarray(naive, dtype=np.float64),
    )


def _mae_rmse(abs_errors: np.ndarray):
    if abs_errors.size == 0:
        return None, None
    mae = float(np.mean(abs_errors))
    rmse = float(math.sqrt(float(np.mean(abs_errors ** 2))))
    if not math.isfinite(mae):
        mae = None
    if not math.isfinite(rmse):
        rmse = None
    return mae, rmse


def _ratio(numerator, denominator):
    if numerator is None or denominator is None or denominator == 0.0:
        return None
    value = numerator / denominator
    if not math.isfinite(value):
        return None
    return value


def series_profile(df: pd.DataFrame, frequency: str) -> dict:
    """Descriptive profile of one product history.

    ``df`` has columns ``date``, ``forecast``, and ``actual`` (float, possibly
    missing) and may be unsorted. Counts are rows after dropping unparseable
    dates. Non-finite forecast/actual values count as missing.

    Percent fields are shares in ``[0, 1]``. Zero and negative forecast shares
    use finite forecasts as the denominator; the missing-forecast share uses
    all dated rows. Zero and negative actual shares use finite actuals.

    ``std_*`` / ``cv_*`` / ``cv2_nonzero_actual`` use the sample standard
    deviation (ddof=1) and are None with fewer than 2 observations. CV is None
    when the mean is 0. ``cv2_nonzero_actual`` is ``(std/mean)^2`` of non-zero
    actuals, including negatives.

    ``intermittency_adi`` is the mean gap in periods between periods that have
    a non-zero actual. None when there are no actuals or fewer than two
    demand periods (a single demand has no gap).

    ``demand_class`` is Syntetos–Boylan on the rounded ADI and CV²:
    ADI >= 1.32 is intermittent, CV² >= 0.49 is erratic, both is lumpy,
    neither is smooth. ``unknown`` when there are fewer than 6 actuals or
    either input is None.

    ``trend_slope_per_period`` is an OLS slope per period on actuals when at
    least 6 actuals exist, otherwise on forecasts when at least 4 forecasts
    exist, otherwise None. Irregular series use row steps as periods; regular
    series use calendar periods, so gaps widen ``x``. ``trend_direction`` is
    ``up`` / ``down`` / ``flat`` / ``unknown``. Flat means
    ``|slope| < 0.02 * |mean|`` of the series used for the slope (or slope 0).

    ``seasonality_strength`` is computed on actuals only: monthly with at least
    24 actuals (period 12), or weekly with at least 104 (period 52); otherwise
    None. On the paired tail ``y_t`` (one value per period, last row wins):

        strength = clip(1 - sum((y_t - y_{t-m})^2) / sum((y_t - mean(y_t))^2), 0, 1)

    A pure repeating pattern scores 1. A pure trend scores 0. A flat tail
    scores 0. None if fewer than 2 seasonal pairs can be formed.

    ``missing_date_gaps`` counts calendar periods absent between the first and
    last dated row (0 when irregular, empty, or a single period).
    ``flatness`` is None with fewer than 2 forecasts. ``history_ratio`` is None
    without a future-only forecast, without actuals, or when the actual mean
    is 0. ``start`` / ``end`` are ISO dates or None.
    """
    frame = _prepare(df)
    kind = _freq_kind(frequency)
    forecast = frame["forecast"].to_numpy(dtype=np.float64)
    actual = frame["actual"].to_numpy(dtype=np.float64)
    ordinals = _ordinals(frame["date"], kind)

    finite_forecast = forecast[_finite_mask(forecast)]
    finite_actual = actual[_finite_mask(actual)]
    n_forecast = int(finite_forecast.size)
    n_actual = int(finite_actual.size)
    n_overlap = int(np.sum(_finite_mask(forecast) & _finite_mask(actual)))
    n_rows = int(len(frame))

    mean_f, std_f, cv_f = _mean_std_cv(finite_forecast)
    mean_a, _std_a, cv_a = _mean_std_cv(finite_actual)
    adi = _adi(ordinals, actual)
    cv2 = _cv2_nonzero(actual)
    adi_r = _num(adi)
    cv2_r = _num(cv2)

    if n_actual >= 6:
        slope, level = _ols_slope(ordinals, actual)
    elif n_forecast >= 4:
        slope, level = _ols_slope(ordinals, forecast)
    else:
        slope, level = None, None

    if n_rows == 0:
        start = None
        end = None
    else:
        start = _iso_date(frame["date"].iloc[0])
        end = _iso_date(frame["date"].iloc[-1])

    raw = {
        "n_forecast": n_forecast,
        "n_actual": n_actual,
        "n_overlap": n_overlap,
        "start": start,
        "end": end,
        "zero_forecast_pct": None if n_forecast == 0 else float(np.sum(finite_forecast == 0.0) / n_forecast),
        "negative_forecast_pct": None if n_forecast == 0 else float(np.sum(finite_forecast < 0.0) / n_forecast),
        "missing_forecast_pct": None if n_rows == 0 else float(np.sum(~_finite_mask(forecast)) / n_rows),
        "zero_actual_pct": None if n_actual == 0 else float(np.sum(finite_actual == 0.0) / n_actual),
        "negative_actual_pct": None if n_actual == 0 else float(np.sum(finite_actual < 0.0) / n_actual),
        "mean_forecast": mean_f,
        "std_forecast": std_f,
        "cv_forecast": cv_f,
        "mean_actual": mean_a,
        "cv_actual": cv_a,
        "intermittency_adi": adi_r,
        "cv2_nonzero_actual": cv2_r,
        "demand_class": _demand_class(n_actual, adi_r, cv2_r),
        "trend_slope_per_period": slope,
        "trend_direction": _trend_direction(slope, level),
        "seasonality_strength": _profile_seasonality(ordinals, actual, kind),
        "missing_date_gaps": _missing_gaps(ordinals, kind),
        "unique_forecast_values": int(np.unique(finite_forecast).size) if n_forecast else 0,
        "flatness": _flatness(forecast),
        "history_ratio": _history_ratio(frame["date"], forecast, actual),
        "last_actual": _last_finite(actual),
        "last_forecast": _last_finite(forecast),
    }
    cleaned = {}
    for key, value in raw.items():
        if key in _PROFILE_INTS:
            cleaned[key] = int(value)
        elif key in _PROFILE_STRS:
            cleaned[key] = None if value is None else str(value)
        else:
            cleaned[key] = _num(value)
    return cleaned


def accuracy_metrics(df: pd.DataFrame, frequency: str) -> dict:
    """Accuracy on rows where forecast and actual are both finite.

    ``n`` is that overlap count (int). Every other numeric value is a float
    or None. ``error_sign`` is ``"forecast_minus_actual"``.

    Reported for ``n >= 1``: ``me``, ``mae``, ``mdae``, ``rmse`` (RMSE divides
    by ``n``, not ``n-1``), ``bias_pct``, ``mpe``, ``mape``,
    ``mape_positive_only``, ``mdape``, ``smape``, ``wape``, ``mase``, ``rmsse``,
    ``tracking_signal``, ``theil_u2``, ``fva_vs_naive``,
    ``fva_vs_seasonal_naive``, hit rates, ``cumulative_error``, and the
    over/under shares.

    ``mape`` is None if any overlap actual is exactly 0 (or ``n == 0``).
    ``mape_positive_only``, ``mdape``, and ``mpe`` skip actuals equal to 0
    and are None when none remain. ``smape`` skips pairs where both sides are
    0 and is None when none remain. ``wape`` is None when ``sum(|a|) == 0``.
    ``bias_pct`` is None when ``sum(a) == 0``.

    ``mase`` is overlap MAE / in-sample MAE of the seasonal naive on actuals
    (period 7/52/12/4). Lag-1 is used when no seasonal pair exists, including
    every irregular series. ``rmsse`` is the same with RMSE. Either is None
    when its naive scale is missing or 0. The naive scale collapses to one
    actual per period. The numerator uses every overlap row.

    ``theil_u2`` is RMSE(model) / RMSE(lag-1 naive) and ``fva_vs_naive`` is
    ``1 - MAE(model) / MAE(lag-1)``. Both use only overlap rows whose previous
    period has an actual (that actual may sit outside the overlap). None when
    there is no such row or the naive error is 0. ``fva_vs_seasonal_naive``
    is the same comparison against the seasonal naive and is None when that
    naive is not defined on the overlap (no seasonal period, or no pair).

    ``tracking_signal`` is ``sum(f-a) / mae`` and is None when ``mae == 0``.
    Hit rates use ``|f-a| / max(|a|, 1e-9)`` and are None only when ``n == 0``.
    ``correlation`` is Pearson and is None when ``n < 3`` or either side has
    zero variance. ``r2`` is ``1 - SS_res / SS_tot`` against the actual mean
    (forecasts are not re-fit) and is None when ``n < 3`` or the actual
    variance is 0. It can be negative.
    """
    frame = _prepare(df)
    kind = _freq_kind(frequency)
    forecast = frame["forecast"].to_numpy(dtype=np.float64)
    actual = frame["actual"].to_numpy(dtype=np.float64)
    ordinals = _ordinals(frame["date"], kind)
    overlap = _finite_mask(forecast) & _finite_mask(actual)
    n = int(overlap.sum())

    out = {
        "n": n,
        "error_sign": "forecast_minus_actual",
        "me": None,
        "mae": None,
        "mdae": None,
        "rmse": None,
        "bias_pct": None,
        "mpe": None,
        "mape": None,
        "mape_positive_only": None,
        "mdape": None,
        "smape": None,
        "wape": None,
        "mase": None,
        "rmsse": None,
        "tracking_signal": None,
        "theil_u2": None,
        "fva_vs_naive": None,
        "fva_vs_seasonal_naive": None,
        "hit_rate_10": None,
        "hit_rate_20": None,
        "correlation": None,
        "r2": None,
        "cumulative_error": None,
        "over_forecast_pct": None,
        "under_forecast_pct": None,
    }
    if n == 0:
        return out

    forecast_o = forecast[overlap]
    actual_o = actual[overlap]
    error = forecast_o - actual_o
    abs_error = np.abs(error)

    me = float(np.mean(error))
    mae = float(np.mean(abs_error))
    mdae = float(np.median(abs_error))
    rmse = float(math.sqrt(float(np.mean(error ** 2))))
    cumulative = float(np.sum(error))

    actual_sum = float(np.sum(actual_o))
    bias = None if actual_sum == 0.0 else float(100.0 * cumulative / actual_sum)

    nonzero = actual_o != 0.0
    if np.any(nonzero):
        signed_pct = (error[nonzero] / actual_o[nonzero]) * 100.0
        abs_pct = np.abs(signed_pct)
        mpe = float(np.mean(signed_pct))
        mape_positive = float(np.mean(abs_pct))
        mdape = float(np.median(abs_pct))
    else:
        mpe = None
        mape_positive = None
        mdape = None
    if np.any(actual_o == 0.0):
        mape = None
    else:
        mape = float(np.mean(np.abs(error) / np.abs(actual_o)) * 100.0)

    smape_denom = np.abs(forecast_o) + np.abs(actual_o)
    smape_ok = smape_denom > 0.0
    if np.any(smape_ok):
        smape = float(np.mean(200.0 * abs_error[smape_ok] / smape_denom[smape_ok]))
    else:
        smape = None

    abs_actual_sum = float(np.sum(np.abs(actual_o)))
    wape = None if abs_actual_sum == 0.0 else float(np.sum(abs_error) / abs_actual_sum)

    actual_series = _period_map(ordinals, actual)
    scale_errors = _naive_scale(actual_series, kind)
    scale_mae, scale_rmse = _mae_rmse(scale_errors)
    mase = _ratio(mae, scale_mae)
    rmsse = _ratio(rmse, scale_rmse)

    tracking = None if mae == 0.0 else float(cumulative / mae)

    lag_model, lag_naive = _paired_errors(ordinals, actual, forecast, 1)
    if lag_naive.size:
        naive_mae = float(np.mean(np.abs(lag_naive)))
        naive_rmse = float(math.sqrt(float(np.mean(lag_naive ** 2))))
        model_mae_lag = float(np.mean(np.abs(lag_model)))
        model_rmse_lag = float(math.sqrt(float(np.mean(lag_model ** 2))))
        theil = _ratio(model_rmse_lag, naive_rmse)
        fva_naive = None if naive_mae == 0.0 else 1.0 - (model_mae_lag / naive_mae)
    else:
        theil = None
        fva_naive = None

    period = _SEASON_PERIOD.get(kind)
    if period is None:
        fva_seasonal = None
    else:
        seas_model, seas_naive = _paired_errors(ordinals, actual, forecast, period)
        if seas_naive.size == 0:
            fva_seasonal = None
        else:
            seas_naive_mae = float(np.mean(np.abs(seas_naive)))
            seas_model_mae = float(np.mean(np.abs(seas_model)))
            if seas_naive_mae == 0.0:
                # Empate perfecto: el naive estacional ya no se puede mejorar.
                fva_seasonal = 0.0 if seas_model_mae == 0.0 else None
            else:
                fva_seasonal = 1.0 - (seas_model_mae / seas_naive_mae)

    hit_ratio = abs_error / np.maximum(np.abs(actual_o), _HIT_EPS)
    if n < 3:
        correlation = None
        r2 = None
    else:
        actual_centered = actual_o - float(np.mean(actual_o))
        forecast_centered = forecast_o - float(np.mean(forecast_o))
        ss_actual = float(np.dot(actual_centered, actual_centered))
        ss_forecast = float(np.dot(forecast_centered, forecast_centered))
        ss_res = float(np.dot(actual_o - forecast_o, actual_o - forecast_o))
        if ss_actual == 0.0:
            r2 = None
        else:
            r2 = 1.0 - ss_res / ss_actual
        if ss_actual == 0.0 or ss_forecast == 0.0:
            correlation = None
        else:
            correlation = float(
                np.dot(actual_centered, forecast_centered) / math.sqrt(ss_actual * ss_forecast)
            )
            if correlation > 1.0:
                correlation = 1.0
            elif correlation < -1.0:
                correlation = -1.0

    out.update(
        {
            "me": me,
            "mae": mae,
            "mdae": mdae,
            "rmse": rmse,
            "bias_pct": bias,
            "mpe": mpe,
            "mape": mape,
            "mape_positive_only": mape_positive,
            "mdape": mdape,
            "smape": smape,
            "wape": wape,
            "mase": mase,
            "rmsse": rmsse,
            "tracking_signal": tracking,
            "theil_u2": theil,
            "fva_vs_naive": fva_naive,
            "fva_vs_seasonal_naive": fva_seasonal,
            "hit_rate_10": float(np.mean(hit_ratio <= 0.10)),
            "hit_rate_20": float(np.mean(hit_ratio <= 0.20)),
            "correlation": correlation,
            "r2": r2,
            "cumulative_error": cumulative,
            "over_forecast_pct": float(np.mean(forecast_o > actual_o)),
            "under_forecast_pct": float(np.mean(forecast_o < actual_o)),
        }
    )
    for key, value in list(out.items()):
        if key in {"n", "error_sign"}:
            continue
        out[key] = _num(value)
    return out
