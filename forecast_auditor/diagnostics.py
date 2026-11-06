"""Patrón de demanda, calendario y problemas de sanidad de la serie."""

from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd

# Umbrales de Syntetos y Boylan (2005) para clasificar demanda.
ADI_CUT = 1.32
CV2_CUT = 0.49


def infer_frequency(dates: pd.Series) -> dict[str, Any]:
    ordered = pd.to_datetime(pd.Series(dates).dropna()).sort_values()
    if len(ordered) < 3:
        return {"codigo": "W", "periodo": 52, "delta_dias": 7, "etiqueta": "semanal (supuesta)"}
    deltas = ordered.diff().dt.total_seconds().div(86400).dropna()
    deltas = deltas[deltas > 0]
    if deltas.empty:
        return {"codigo": "W", "periodo": 52, "delta_dias": 7, "etiqueta": "semanal (supuesta)"}
    # El percentil bajo evita que un calendario con huecos parezca una frecuencia más gruesa.
    values = deltas.to_numpy(dtype=float)
    week_k = np.round(values / 7.0)
    near_week = (week_k >= 1) & (np.abs(values - 7.0 * week_k) <= 1.0)
    exact_week = float(np.mean(np.abs(values - 7.0) <= 1.0))
    exact_biweek = float(np.mean(np.abs(values - 14.0) <= 1.5))
    if float(np.mean(near_week)) >= 0.8 and exact_week >= 0.2 and exact_week >= exact_biweek:
        return {"codigo": "W", "periodo": 52, "delta_dias": 7, "etiqueta": "semanal"}
    typical = float(np.percentile(values, 25))
    if typical <= 2:
        return {"codigo": "D", "periodo": 7, "delta_dias": 1, "etiqueta": "diaria"}
    if typical <= 10:
        return {"codigo": "W", "periodo": 52, "delta_dias": 7, "etiqueta": "semanal"}
    if typical <= 20:
        return {"codigo": "2W", "periodo": 26, "delta_dias": 14, "etiqueta": "quincenal"}
    if typical <= 45:
        return {"codigo": "M", "periodo": 12, "delta_dias": 30, "etiqueta": "mensual"}
    if typical <= 100:
        return {"codigo": "Q", "periodo": 4, "delta_dias": 91, "etiqueta": "trimestral"}
    return {"codigo": "Y", "periodo": 1, "delta_dias": 365, "etiqueta": "anual"}


def calendar_gaps(dates: pd.Series, freq: dict[str, Any]) -> tuple[pd.DatetimeIndex, float]:
    ordered = pd.to_datetime(pd.Series(dates).dropna()).dt.normalize().sort_values().unique()
    present = pd.DatetimeIndex(ordered)
    if len(present) < 2:
        return present, 0.0
    code = freq["codigo"]
    period_code = {"M": "M", "Q": "Q-DEC", "Y": "Y"}.get(code)
    if period_code:
        periods = present.to_period(period_code[0])
        full = pd.period_range(periods.min(), periods.max(), freq=period_code[0])
        missing_periods = full.difference(periods.unique())
        expected = int(len(full))
        rate = 0.0 if expected == 0 else len(missing_periods) / expected
        return pd.DatetimeIndex(missing_periods.to_timestamp()), float(rate)
    step = {"D": 1, "W": 7, "2W": 14}.get(code, int(freq["delta_dias"]))
    delta = pd.Timedelta(days=step)
    missing = []
    cursor = present.min()
    end = present.max()
    present_set = set(present)
    guard = 0
    while cursor <= end and guard < 20000:
        if cursor not in present_set:
            missing.append(cursor)
        cursor = cursor + delta
        guard += 1
    expected = len(present) + len(missing)
    rate = 0.0 if expected == 0 else len(missing) / expected
    return pd.DatetimeIndex(missing), float(rate)


def _seasonal_strength(values: np.ndarray, period: int) -> float:
    y = np.asarray(values, dtype=float)
    y = y[np.isfinite(y)]
    n = int(y.size)
    if period < 2 or n < period * 2:
        return 0.0, 0.0
    t = np.arange(n, dtype=float)
    slope, intercept = np.polyfit(t, y, 1)
    detrended = y - (slope * t + intercept)
    buckets = [detrended[t.astype(int) % period == s] for s in range(period)]
    seasonal = np.array([float(np.mean(b)) if len(b) else 0.0 for b in buckets])
    component = seasonal[t.astype(int) % period]
    resid = detrended - component
    var_resid = float(np.var(resid))
    var_both = float(np.var(component + resid))
    if var_both <= 1e-12:
        return 0.0, 0.0
    strength = float(max(0.0, min(1.0, 1.0 - var_resid / var_both)))
    amplitude = float(np.max(seasonal) - np.min(seasonal))
    return strength, amplitude


def _trend(values: np.ndarray) -> dict[str, float | bool]:
    y = np.asarray(values, dtype=float)
    y = y[np.isfinite(y)]
    n = int(y.size)
    if n < 6 or float(np.std(y)) < 1e-12:
        return {"pendiente_pct_periodo": 0.0, "correlacion": 0.0, "hay_tendencia": False}
    t = np.arange(n, dtype=float)
    slope, _intercept = np.polyfit(t, y, 1)
    mean = float(np.mean(y))
    pct = 0.0 if abs(mean) < 1e-8 else float(slope / abs(mean))
    corr = float(np.corrcoef(t, y)[0, 1])
    total = pct * n
    return {
        "pendiente_pct_periodo": pct,
        "correlacion": corr,
        "hay_tendencia": bool(abs(corr) >= 0.55 and abs(total) >= 0.15),
    }


def classify_demand(actual: np.ndarray) -> dict[str, Any]:
    y = np.asarray(actual, dtype=float)
    y = y[np.isfinite(y)]
    n = int(y.size)
    if n == 0:
        return {
            "adi": None,
            "cv2": None,
            "clase": "sin_historia",
            "etiqueta": "Sin demanda real",
            "pct_ceros": None,
        }
    nonzero = y[y > 1e-8]
    demand_periods = int(nonzero.size)
    adi = float(n / demand_periods) if demand_periods else None
    if demand_periods >= 2 and abs(float(np.mean(nonzero))) > 1e-8:
        cv2 = float((np.std(nonzero, ddof=1) / np.mean(nonzero)) ** 2)
    elif demand_periods == 1:
        cv2 = 0.0
    else:
        cv2 = None
    if adi is None:
        clase, etiqueta = "sin_demanda", "Sin demanda distinta de cero"
    elif adi < ADI_CUT and (cv2 is None or cv2 < CV2_CUT):
        clase, etiqueta = "suave", "Suave"
    elif adi < ADI_CUT:
        clase, etiqueta = "erratica", "Errática"
    elif cv2 is None or cv2 < CV2_CUT:
        clase, etiqueta = "intermitente", "Intermitente"
    else:
        clase, etiqueta = "irregular", "Irregular (lumpy)"
    return {
        "adi": adi,
        "cv2": cv2,
        "clase": clase,
        "etiqueta": etiqueta,
        "pct_ceros": float(np.mean(y <= 1e-8)),
    }


def series_diagnostics(frame: pd.DataFrame) -> dict[str, Any]:
    dates = pd.to_datetime(frame["date"])
    forecast = frame["forecast"].to_numpy(dtype=float)
    actual = frame["actual"].to_numpy(dtype=float)
    freq = infer_frequency(dates)
    missing, gap_rate = calendar_gaps(dates, freq)
    finite_f = forecast[np.isfinite(forecast)]
    finite_a = actual[np.isfinite(actual)]
    pct_null_f = float(np.mean(~np.isfinite(forecast))) if len(forecast) else 1.0
    pct_neg_f = float(np.mean(finite_f < -1e-8)) if finite_f.size else 0.0
    pct_neg_a = float(np.mean(finite_a < -1e-8)) if finite_a.size else 0.0
    pct_zero_f = float(np.mean(np.abs(finite_f) <= 1e-8)) if finite_f.size else 0.0

    demand = classify_demand(finite_a)
    if finite_a.size:
        seasonality, amplitude = _seasonal_strength(finite_a, int(freq["periodo"]))
    else:
        seasonality, amplitude = 0.0, 0.0
    trend = _trend(finite_a) if finite_a.size else _trend(np.array([]))
    level = abs(float(np.mean(finite_a))) if finite_a.size else 0.0
    sparse = (demand.get("pct_ceros") or 0) >= 0.35 or demand["clase"] in {"intermitente", "irregular", "sin_demanda"}
    cycles = finite_a.size / max(int(freq["periodo"]), 1)
    season_cut = 0.65 if cycles < 3 else 0.50
    seasonal_material = bool(
        seasonality >= season_cut and level > 1e-8 and amplitude >= 0.18 * level and not sparse
    )

    # Outliers del pronóstico respecto de su propia mediana absoluta.
    outlier_count = 0
    if finite_f.size >= 8:
        med = float(np.median(finite_f))
        mad = float(np.median(np.abs(finite_f - med)))
        if mad > 1e-8:
            z = 0.6745 * (finite_f - med) / mad
            outlier_count = int(np.sum(np.abs(z) > 3.5))
        else:
            # Pronóstico casi plano: un punto muy lejos de la mediana igual cuenta.
            outlier_count = int(np.sum(np.abs(finite_f - med) > max(abs(med) * 3, 1.0)))

    cv_f = None
    if finite_f.size >= 2 and abs(float(np.mean(finite_f))) > 1e-8:
        cv_f = float(np.std(finite_f, ddof=1) / np.mean(finite_f))
    cv_a = None
    if finite_a.size >= 2 and abs(float(np.mean(finite_a))) > 1e-8:
        cv_a = float(np.std(finite_a, ddof=1) / np.mean(finite_a))

    last_actual_idx = None
    good_actual = np.where(np.isfinite(actual))[0]
    if good_actual.size:
        last_actual_idx = int(good_actual.max())

    actual_moves = cv_a is not None and abs(cv_a) >= 0.12
    forecast_still = finite_f.size >= 8 and (cv_f is None or abs(cv_f) < 0.04)
    flat_forecast = bool(forecast_still and actual_moves)
    return {
        "frecuencia": freq,
        "fechas_faltantes": int(len(missing)),
        "pct_faltantes": float(gap_rate),
        "pct_nulos_pronostico": pct_null_f,
        "pct_negativos_pronostico": pct_neg_f,
        "pct_negativos_real": pct_neg_a,
        "pct_ceros_pronostico": pct_zero_f,
        "outliers_pronostico": outlier_count,
        "cv_pronostico": cv_f,
        "cv_real": cv_a,
        "estacionalidad": seasonality,
        "amplitud_estacional": amplitude,
        "hay_estacionalidad": seasonal_material,
        "tendencia": trend,
        "demanda": demand,
        "n_filas": int(len(frame)),
        "n_reales": int(finite_a.size),
        "n_pronostico": int(finite_f.size),
        "ultimo_real_pos": last_actual_idx,
        "n_futuro": int(0 if last_actual_idx is None else max(0, len(frame) - last_actual_idx - 1)),
        "inicio": dates.min().date().isoformat() if len(dates) else None,
        "fin": dates.max().date().isoformat() if len(dates) else None,
        "pronostico_plano": flat_forecast,
        "media_real": float(np.mean(finite_a)) if finite_a.size else None,
        "media_pronostico": float(np.mean(finite_f)) if finite_f.size else None,
        "min_pronostico": float(np.min(finite_f)) if finite_f.size else None,
        "max_pronostico": float(np.max(finite_f)) if finite_f.size else None,
    }


def holdout_bounds(n_history: int) -> tuple[int, int]:
    """Devuelve (inicio_validacion, fin_historia). Sin validación, ambos iguales a n_history."""
    if n_history < 16:
        return n_history, n_history
    size = max(8, int(round(n_history * 0.20)))
    size = min(size, n_history // 3)
    if size < 8:
        return n_history, n_history
    start = n_history - size
    return start, n_history


def modified_z_spike_mask(forecast: np.ndarray) -> np.ndarray:
    f = np.asarray(forecast, dtype=float)
    mask = np.zeros(f.shape, dtype=bool)
    finite = np.isfinite(f)
    if int(finite.sum()) < 8:
        return mask
    med = float(np.median(f[finite]))
    mad = float(np.median(np.abs(f[finite] - med)))
    scale = mad if mad > 1e-8 else max(abs(med) * 0.05, 1.0)
    z = 0.6745 * (f - med) / scale
    mask = finite & (np.abs(z) > 3.5) & (np.abs(f - med) > max(abs(med) * 0.5, 1.0))
    return mask


def round_or_none(value: float | None, digits: int = 4) -> float | None:
    if value is None or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        return None
    return round(float(value), digits)
