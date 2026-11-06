"""Métodos base, evaluados a un paso, sin librerías de modelos.

El pronóstico de cada período usa solo la demanda anterior. El tramo futuro
se proyecta desde el último real conocido.
"""

from __future__ import annotations

from typing import Callable

import numpy as np

PredictFn = Callable[[np.ndarray, int], np.ndarray]


def _clean(y: np.ndarray) -> np.ndarray:
    out = np.asarray(y, dtype=float).copy()
    # Los huecos internos no deberían llegar. Si llegan, se rellenan con el último valor.
    last = 0.0
    seen = False
    for i, value in enumerate(out):
        if np.isfinite(value):
            last = float(value)
            seen = True
        elif seen:
            out[i] = last
        else:
            out[i] = 0.0
    return out


def forecast_naive(y: np.ndarray, horizon: int) -> np.ndarray:
    hist = _clean(y)
    n = hist.size
    pred = np.zeros(n + horizon, dtype=float)
    pred[0] = hist[0]
    if n > 1:
        pred[1:n] = hist[:-1]
    last = hist[-1] if n else 0.0
    if horizon:
        pred[n:] = last
    return pred


def forecast_mean(y: np.ndarray, horizon: int) -> np.ndarray:
    hist = _clean(y)
    n = hist.size
    pred = np.zeros(n + horizon, dtype=float)
    running = 0.0
    for i in range(n):
        pred[i] = running / i if i else hist[0]
        running += hist[i]
    if horizon:
        pred[n:] = running / n if n else 0.0
    return pred


def forecast_seasonal_naive(y: np.ndarray, horizon: int, period: int) -> np.ndarray:
    hist = _clean(y)
    n = hist.size
    pred = np.zeros(n + horizon, dtype=float)
    for i in range(n + horizon):
        if i < period:
            pred[i] = hist[0] if n else 0.0
        elif i < n:
            pred[i] = hist[i - period]
        else:
            # Proyección: el valor del ciclo anterior, ya sea real o recién proyectado.
            source = hist[i - period] if i - period < n else pred[i - period]
            pred[i] = source
    return pred


def forecast_moving_average(y: np.ndarray, horizon: int, window: int) -> np.ndarray:
    hist = _clean(y)
    n = hist.size
    pred = np.zeros(n + horizon, dtype=float)
    for i in range(n):
        start = max(0, i - window)
        chunk = hist[start:i]
        pred[i] = float(np.mean(chunk)) if chunk.size else hist[0]
    level = hist[-window:] if n else np.array([0.0])
    for i in range(horizon):
        pred[n + i] = float(np.mean(level))
        level = np.roll(level, -1)
        level[-1] = pred[n + i]
    return pred


def _ses_path(hist: np.ndarray, alpha: float, horizon: int) -> np.ndarray:
    n = hist.size
    pred = np.zeros(n + horizon, dtype=float)
    level = float(hist[0])
    for i in range(n):
        pred[i] = level
        level = alpha * float(hist[i]) + (1 - alpha) * level
    for i in range(horizon):
        pred[n + i] = level
    return pred


def forecast_ses_grid(y: np.ndarray, horizon: int) -> tuple[np.ndarray, str]:
    hist = _clean(y)
    best = None
    best_name = "SES α=0.3"
    best_mae = math_inf()
    for alpha in (0.1, 0.2, 0.4, 0.6, 0.8):
        pred = _ses_path(hist, alpha, horizon)
        mae = _insample_mae(hist, pred[: hist.size])
        if mae < best_mae:
            best_mae = mae
            best = pred
            best_name = f"SES α={alpha:.1f}"
    return best if best is not None else _ses_path(hist, 0.3, horizon), best_name


def _holt_path(hist: np.ndarray, alpha: float, beta: float, phi: float, horizon: int) -> np.ndarray:
    n = hist.size
    pred = np.zeros(n + horizon, dtype=float)
    level = float(hist[0])
    trend = 0.0
    for i in range(n):
        pred[i] = level + phi * trend
        new_level = alpha * float(hist[i]) + (1 - alpha) * (level + phi * trend)
        trend = beta * (new_level - level) + (1 - beta) * phi * trend
        level = new_level
    for h in range(1, horizon + 1):
        step = phi * (1 - phi ** h) / (1 - phi) if abs(1 - phi) > 1e-8 else phi * h
        pred[n + h - 1] = level + step * trend
    return pred


def forecast_holt_grid(y: np.ndarray, horizon: int) -> tuple[np.ndarray, str]:
    hist = _clean(y)
    best = None
    best_name = "Holt amortiguado"
    best_mae = math_inf()
    for alpha, beta, phi in (
        (0.3, 0.1, 0.90),
        (0.4, 0.2, 0.95),
        (0.5, 0.1, 0.80),
        (0.2, 0.05, 0.98),
    ):
        pred = _holt_path(hist, alpha, beta, phi, horizon)
        if not np.isfinite(pred).all():
            continue
        mae = _insample_mae(hist, pred[: hist.size])
        if mae < best_mae:
            best_mae = mae
            best = pred
            best_name = f"Holt amortiguado α={alpha:.1f} β={beta:.2f} φ={phi:.2f}"
    if best is None:
        best = forecast_naive(hist, horizon)
    return best, best_name


def _croston_path(hist: np.ndarray, alpha: float, horizon: int, sba: bool) -> np.ndarray:
    n = hist.size
    pred = np.zeros(n + horizon, dtype=float)
    q = None
    p = None
    since = 0.0
    for i in range(n):
        if q is None or p is None or p <= 1e-8:
            pred[i] = 0.0
        else:
            rate = q / p
            if sba:
                rate *= 1 - alpha / 2
            pred[i] = rate
        since += 1
        if hist[i] > 1e-8:
            if q is None:
                q = float(hist[i])
                p = since
            else:
                q = alpha * float(hist[i]) + (1 - alpha) * q
                p = alpha * since + (1 - alpha) * p
            since = 0.0
    if q is None or p is None or p <= 1e-8:
        rate = 0.0
    else:
        rate = q / p
        if sba:
            rate *= 1 - alpha / 2
    if horizon:
        pred[n:] = rate
    return pred


def _tsb_path(hist: np.ndarray, alpha: float, beta: float, horizon: int) -> np.ndarray:
    n = hist.size
    pred = np.zeros(n + horizon, dtype=float)
    z = 0.0
    demand_p = 0.0
    seen = False
    for i in range(n):
        pred[i] = demand_p * z
        if hist[i] > 1e-8:
            if not seen:
                z = float(hist[i])
                demand_p = beta
                seen = True
            else:
                z = alpha * float(hist[i]) + (1 - alpha) * z
                demand_p = beta * 1.0 + (1 - beta) * demand_p
        elif seen:
            demand_p = (1 - beta) * demand_p
    if horizon:
        pred[n:] = demand_p * z
    return pred


def math_inf() -> float:
    return float("inf")


def _insample_mae(hist: np.ndarray, pred: np.ndarray) -> float:
    # Se ignora el primer punto: casi todos los métodos lo copian y no informa.
    if hist.size < 4:
        err = np.abs(pred[: hist.size] - hist)
        return float(np.mean(err))
    err = np.abs(pred[2: hist.size] - hist[2:])
    if not np.isfinite(err).all():
        return math_inf()
    return float(np.mean(err))


def candidate_forecasts(y: np.ndarray, horizon: int, period: int, intermittent: bool) -> list[tuple[str, np.ndarray]]:
    hist = _clean(y)
    out: list[tuple[str, np.ndarray]] = []
    out.append(("Naive (período anterior)", forecast_naive(hist, horizon)))
    out.append(("Media histórica", forecast_mean(hist, horizon)))
    for window in (4, 8, 13):
        if hist.size > window:
            out.append((f"Media móvil {window}", forecast_moving_average(hist, horizon, window)))
    if period >= 2 and hist.size >= period * 2:
        out.append((f"Naive estacional (ciclo {period})", forecast_seasonal_naive(hist, horizon, period)))
    ses, ses_name = forecast_ses_grid(hist, horizon)
    out.append((ses_name, ses))
    if not intermittent and hist.size >= 10:
        holt, holt_name = forecast_holt_grid(hist, horizon)
        out.append((holt_name, holt))
    if intermittent or float(np.mean(hist <= 1e-8)) >= 0.25:
        for alpha in (0.1, 0.2, 0.4):
            out.append((f"Croston α={alpha:.1f}", _croston_path(hist, alpha, horizon, sba=False)))
            out.append((f"SBA α={alpha:.1f}", _croston_path(hist, alpha, horizon, sba=True)))
        for alpha, beta in ((0.1, 0.1), (0.2, 0.05), (0.3, 0.1)):
            out.append((f"TSB α={alpha:.1f} β={beta:.2f}", _tsb_path(hist, alpha, beta, horizon)))
    finite = []
    for name, pred in out:
        if pred.shape[0] == hist.size + horizon and np.isfinite(pred).all():
            finite.append((name, pred))
    return finite
