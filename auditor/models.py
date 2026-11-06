"""Baselines ajustables por producto. El horizonte se trunca a cero."""

from __future__ import annotations

import math

import numpy as np

from auditor.metrics import pearson


def _y(values) -> np.ndarray:
    y = np.asarray(list(values), dtype=float)
    return y[np.isfinite(y)]


def croston_nivel(values, alpha: float = 0.1) -> float:
    y = _y(values)
    pos = np.where(y > 0)[0]
    if len(pos) < 2:
        return math.nan
    z = float(y[pos[0]])
    p = float(pos[0] + 1)
    for i in range(1, len(pos)):
        z = z + alpha * (float(y[pos[i]]) - z)
        interval = float(pos[i] - pos[i - 1])
        p = p + alpha * (interval - p)
    if p <= 0:
        return math.nan
    return z / p


def croston_sba_nivel(values, alpha: float = 0.1) -> float:
    base = croston_nivel(values, alpha)
    if math.isnan(base):
        return base
    return base * (1 - alpha / 2)


def tsb_nivel(values, alpha: float = 0.1, beta: float = 0.1) -> float:
    y = _y(values)
    pos = np.where(y > 0)[0]
    if len(pos) == 0:
        return 0.0
    z = float(y[pos[0]])
    p = 1.0
    for t in range(int(pos[0]) + 1, len(y)):
        if y[t] > 0:
            z = z + alpha * (float(y[t]) - z)
            p = p + beta * (1 - p)
        else:
            p = p + beta * (0 - p)
    return max(0.0, p * z)


def _clip0(values: list[float]) -> list[float]:
    return [0.0 if v < 0 else v for v in values]


def futuro_constante(nivel: float, h: int) -> list[float]:
    if math.isnan(nivel):
        return []
    return _clip0([nivel] * h)


def naive_futuro(y, h: int) -> list[float]:
    serie = _y(y)
    if len(serie) == 0:
        return []
    return _clip0([float(serie[-1])] * h)


def media_futuro(y, h: int) -> list[float]:
    serie = _y(y)
    if len(serie) == 0:
        return []
    return _clip0([float(np.mean(serie))] * h)


def drift_futuro(y, h: int) -> list[float]:
    serie = _y(y)
    if len(serie) == 0:
        return []
    if len(serie) == 1:
        return _clip0([float(serie[-1])] * h)
    slope = (float(serie[-1]) - float(serie[0])) / (len(serie) - 1)
    return _clip0([float(serie[-1]) + (k + 1) * slope for k in range(h)])


def media_movil_futuro(y, h: int) -> list[float]:
    serie = _y(y)
    if len(serie) == 0:
        return []
    w = min(12, max(3, len(serie) // 3))
    w = min(w, len(serie))
    nivel = float(np.mean(serie[-w:]))
    return _clip0([nivel] * h)


def estacional_futuro(y, periodo: int, h: int) -> list[float]:
    serie = _y(y)
    if len(serie) == 0:
        return []
    if periodo < 2 or len(serie) < periodo:
        return naive_futuro(serie, h)
    base = serie[-periodo:]
    return _clip0([float(base[k % periodo]) for k in range(h)])


def _holt_path(y: np.ndarray, alpha: float, beta: float):
    level = float(y[0])
    trend = float(y[1] - y[0]) if len(y) > 1 else 0.0
    fitted = [level]
    for t in range(1, len(y)):
        prev_l, prev_b = level, trend
        fitted.append(prev_l + prev_b)
        level = alpha * float(y[t]) + (1 - alpha) * (prev_l + prev_b)
        trend = beta * (level - prev_l) + (1 - beta) * prev_b
    return fitted, level, trend


def holt_futuro(y, h: int) -> list[float]:
    serie = _y(y)
    if len(serie) < 3:
        return drift_futuro(serie, h)
    best = None
    best_sse = math.inf
    for alpha in (0.2, 0.4, 0.6, 0.8):
        for beta in (0.1, 0.2, 0.4):
            fitted, level, trend = _holt_path(serie, alpha, beta)
            sse = float(np.sum((serie[1:] - np.asarray(fitted[1:])) ** 2))
            if sse < best_sse:
                best_sse = sse
                best = (level, trend)
    level, trend = best
    return _clip0([level + (k + 1) * trend for k in range(h)])


def theta_futuro(y, h: int) -> list[float]:
    """Promedio de un suavizado simple y el drift, la forma clásica de Theta."""
    serie = _y(y)
    if len(serie) < 3:
        return media_futuro(serie, h)
    alpha = 0.3
    level = float(serie[0])
    for value in serie[1:]:
        level = alpha * float(value) + (1 - alpha) * level
    ses = [level] * h
    drift = drift_futuro(serie, h)
    return _clip0([(s + d) / 2 for s, d in zip(ses, drift)])


def holt_winters_futuro(y, periodo: int, h: int) -> list[float]:
    serie = _y(y)
    if periodo < 2 or len(serie) < 2 * periodo:
        return estacional_futuro(serie, max(periodo, 2), h)
    season = [float(v - np.mean(serie[:periodo])) for v in serie[:periodo]]
    level = float(np.mean(serie[:periodo]))
    trend = 0.0
    best = None
    best_sse = math.inf
    for alpha in (0.2, 0.4, 0.6):
        for beta in (0.1, 0.2):
            for gamma in (0.2, 0.4):
                lvl = level
                tr = trend
                seas = season[:]
                sse = 0.0
                last = (lvl, tr, seas[:])
                for t, value in enumerate(serie):
                    s_idx = t % periodo
                    pred = lvl + tr + seas[s_idx]
                    if t >= periodo:
                        sse += (float(value) - pred) ** 2
                    prev_l = lvl
                    lvl = alpha * (float(value) - seas[s_idx]) + (1 - alpha) * (lvl + tr)
                    tr = beta * (lvl - prev_l) + (1 - beta) * tr
                    seas[s_idx] = gamma * (float(value) - prev_l - tr) + (1 - gamma) * seas[s_idx]
                    last = (lvl, tr, seas[:])
                if sse < best_sse:
                    best_sse = sse
                    best = last
    lvl, tr, seas = best
    out = []
    for k in range(1, h + 1):
        out.append(lvl + k * tr + seas[(len(serie) + k - 1) % periodo])
    return _clip0(out)


def acf_lag(values, lag: int) -> float:
    y = _y(values)
    if lag < 1 or len(y) <= lag:
        return math.nan
    return pearson(y[:-lag], y[lag:])


def mejor_periodo(values) -> tuple[int | None, bool, float]:
    y = _y(values)
    n = len(y)
    if n < 6:
        return None, False, math.nan
    candidatos = set(range(2, min(12, n // 2) + 1))
    for extra in (4, 7, 12):
        if extra < n:
            candidatos.add(extra)
    mejor_lag = None
    mejor_acf = -math.inf
    for lag in sorted(candidatos):
        rho = acf_lag(y, lag)
        if math.isnan(rho):
            continue
        if rho > mejor_acf + 1e-9 or (abs(rho - mejor_acf) <= 0.05 and (mejor_lag is None or lag < mejor_lag)):
            # El periodo más corto gana un empate holgado.
            if rho > mejor_acf or mejor_lag is None or (rho >= mejor_acf - 0.05 and lag < mejor_lag and rho > 0.4):
                mejor_acf = rho
                mejor_lag = lag
    if mejor_lag is None or mejor_acf <= 0.4:
        return None, False, mejor_acf if mejor_lag else math.nan
    return mejor_lag, True, float(mejor_acf)


def pronosticar(modelo: str, values, horizonte: int, periodo: int | None) -> list[float]:
    nombre = modelo.lower()
    if "sba" in nombre:
        return futuro_constante(croston_sba_nivel(values), horizonte)
    if "tsb" in nombre:
        return futuro_constante(tsb_nivel(values), horizonte)
    if "croston" in nombre:
        return futuro_constante(croston_nivel(values), horizonte)
    if "holt-winters" in nombre or "holt winters" in nombre:
        return holt_winters_futuro(values, periodo or 0, horizonte)
    if "holt" in nombre:
        return holt_futuro(values, horizonte)
    if "theta" in nombre:
        return theta_futuro(values, horizonte)
    if "estacional" in nombre:
        return estacional_futuro(values, periodo or 0, horizonte)
    if "móvil" in nombre or "movil" in nombre:
        return media_movil_futuro(values, horizonte)
    if "drift" in nombre:
        return drift_futuro(values, horizonte)
    if "media histórica" in nombre or "media historica" in nombre:
        return media_futuro(values, horizonte)
    if "naive" in nombre or "naïve" in nombre:
        return naive_futuro(values, horizonte)
    return media_futuro(values, horizonte)


def baseline_en_muestra(modelo: str, values, periodo: int | None) -> list[float | None]:
    """Predicción a un paso, alineada a la historia. Los primeros puntos quedan vacíos."""
    y = _y(values)
    n = len(y)
    out: list[float | None] = [None] * n
    nombre = modelo.lower()
    for t in range(1, n):
        hist = y[:t]
        if "estacional" in nombre and periodo and t >= periodo:
            out[t] = float(y[t - periodo])
        elif "croston" in nombre or "sba" in nombre or "tsb" in nombre:
            nivel = pronosticar(modelo, hist, 1, periodo)
            out[t] = nivel[0] if nivel else None
        elif "media histórica" in nombre or "media historica" in nombre:
            out[t] = float(np.mean(hist))
        elif "móvil" in nombre or "movil" in nombre:
            out[t] = media_movil_futuro(hist, 1)[0]
        elif "drift" in nombre:
            out[t] = drift_futuro(hist, 1)[0]
        elif "holt" in nombre or "theta" in nombre:
            pred = pronosticar(modelo, hist, 1, periodo)
            out[t] = pred[0] if pred else None
        else:
            out[t] = float(y[t - 1])
    return out
