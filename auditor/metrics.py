"""Métricas de forecast. El sesgo positivo significa que el pronóstico se pasa."""

from __future__ import annotations

import math

import numpy as np


def _as_float(values) -> np.ndarray:
    return np.asarray(list(values), dtype=float)


def _safe_div(num, den):
    if den == 0:
        return 0.0 if num == 0 else math.nan
    return num / den


def pearson(a: np.ndarray, b: np.ndarray) -> float:
    if len(a) < 2 or len(b) < 2:
        return math.nan
    if np.std(a) == 0 or np.std(b) == 0:
        return math.nan
    return float(np.corrcoef(a, b)[0, 1])


def cv(values) -> float:
    x = _as_float(values)
    x = x[np.isfinite(x)]
    if len(x) < 2:
        return math.nan
    mean = float(np.mean(x))
    std = float(np.std(x, ddof=1))
    if abs(mean) < 1e-12:
        return 0.0 if std < 1e-12 else math.inf
    return std / mean


def adi_cv2(actual: np.ndarray) -> tuple[float, float, str]:
    y = actual[np.isfinite(actual)]
    if len(y) == 0:
        return math.nan, math.nan, "sin_datos"
    positivos = y[y > 0]
    if len(positivos) == 0:
        return math.nan, math.nan, "sin_demanda"
    adi = len(y) / len(positivos)
    if len(positivos) < 2:
        cv2 = math.nan
        clase = "intermitente" if adi >= 1.32 else "suave"
        return adi, cv2, clase
    cv2 = (float(np.std(positivos, ddof=1)) / float(np.mean(positivos))) ** 2
    if adi < 1.32 and cv2 < 0.49:
        clase = "suave"
    elif adi < 1.32:
        clase = "erratica"
    elif cv2 < 0.49:
        clase = "intermitente"
    else:
        clase = "lumpy"
    return float(adi), float(cv2), clase


def calcular_metricas(actual, forecast, lower=None, upper=None) -> dict:
    a = _as_float(actual)
    f = _as_float(forecast)
    n = min(len(a), len(f))
    a, f = a[:n], f[:n]
    mask = np.isfinite(a) & np.isfinite(f)
    a, f = a[mask], f[mask]
    n = len(a)
    out = {key: math.nan for key in (
        "n", "mae", "rmse", "mse", "medae", "me", "bias_ratio", "mpe", "mape",
        "smape", "wape", "mase", "mase_7", "mase_12", "rmsse", "mdape",
        "tracking_signal", "theil_u2", "pearson", "r2", "hit_10", "hit_20",
        "fva_naive", "fva_rel", "pbias", "mda", "adi", "cv2", "cv_forecast",
        "cv_actual", "cv_ratio", "mean_ratio", "media_actual", "media_forecast",
        "picp", "mpiw",
    )}
    out["n"] = n
    out["clase_sbc"] = "sin_datos"
    if n == 0:
        return out
    err = f - a  # positivo: el forecast se pasa
    abs_err = np.abs(a - f)
    out["mae"] = float(np.mean(abs_err))
    out["mse"] = float(np.mean(err ** 2))
    out["rmse"] = math.sqrt(out["mse"])
    out["medae"] = float(np.median(abs_err))
    out["me"] = float(np.mean(err))
    out["bias_ratio"] = _safe_div(out["me"], out["mae"])
    suma_abs_a = float(np.sum(np.abs(a)))
    out["wape"] = _safe_div(float(np.sum(abs_err)), suma_abs_a)
    suma_a = float(np.sum(a))
    out["pbias"] = _safe_div(float(np.sum(err)), suma_a) if suma_a != 0 else (0.0 if float(np.sum(err)) == 0 else math.nan)
    out["media_actual"] = float(np.mean(a))
    out["media_forecast"] = float(np.mean(f))
    out["mean_ratio"] = _safe_div(out["media_forecast"], out["media_actual"])

    denom = np.abs(a) + np.abs(f)
    terms = np.divide(2 * abs_err, denom, out=np.zeros(n), where=denom > 0)
    out["smape"] = float(np.mean(terms))

    nz = a != 0
    if np.any(nz):
        ape = np.abs(err[nz] / a[nz])
        out["mdape"] = float(np.median(ape))
        out["mape"] = float(np.mean(np.abs(err / a))) if np.all(nz) else math.nan
        signed = err[nz] / a[nz]
        out["mpe"] = float(np.mean(signed))
    out["hit_10"] = float(np.mean(np.where(a == 0, f == 0, abs_err <= 0.10 * np.abs(a))))
    out["hit_20"] = float(np.mean(np.where(a == 0, f == 0, abs_err <= 0.20 * np.abs(a))))

    if n >= 2:
        scale = float(np.mean(np.abs(np.diff(a))))
        out["mase"] = _safe_div(out["mae"], scale)
        naive_abs = np.abs(a[1:] - a[:-1])
        model_abs = abs_err[1:]
        out["fva_naive"] = float(np.mean(naive_abs) - np.mean(model_abs))
        out["fva_rel"] = _safe_div(out["fva_naive"], float(np.mean(naive_abs)))
        den_u = float(np.sum((a[1:] - a[:-1]) ** 2))
        num_u = float(np.sum(err[1:] ** 2))
        out["theil_u2"] = math.sqrt(_safe_div(num_u, den_u)) if den_u > 0 or num_u == 0 else math.nan
        if den_u == 0 and num_u == 0:
            out["theil_u2"] = 0.0
        sst = float(np.sum((a - np.mean(a)) ** 2))
        sse = float(np.sum((a - f) ** 2))
        out["r2"] = _safe_div(sst - sse, sst) if not (sst == 0 and sse > 0) else math.nan
        if sst == 0 and sse == 0:
            out["r2"] = 1.0
        out["pearson"] = pearson(a, f)
        jump = float(np.mean((a[1:] - a[:-1]) ** 2))
        out["rmsse"] = math.sqrt(_safe_div(out["mse"], jump)) if jump > 0 or out["mse"] == 0 else math.nan
        dirs_a = np.sign(a[1:] - a[:-1])
        dirs_f = np.sign(f[1:] - a[:-1])
        mov = dirs_a != 0
        out["mda"] = float(np.mean(dirs_a[mov] == dirs_f[mov])) if np.any(mov) else math.nan

    for period, key in ((7, "mase_7"), (12, "mase_12")):
        if n > period:
            scale_m = float(np.mean(np.abs(a[period:] - a[:-period])))
            out[key] = _safe_div(out["mae"], scale_m)

    alpha = 0.1
    mad = abs(err[0])
    cusum = err[0]
    for e in err[1:]:
        mad = alpha * abs(e) + (1 - alpha) * mad
        cusum = cusum + e
    out["tracking_signal"] = 0.0 if mad == 0 else float(cusum / mad)

    adi, cv2, clase = adi_cv2(a)
    out["adi"] = adi
    out["cv2"] = cv2
    out["clase_sbc"] = clase
    out["cv_actual"] = cv(a)
    out["cv_forecast"] = cv(f)
    if out["cv_actual"] == 0 and out["cv_forecast"] == 0:
        out["cv_ratio"] = 1.0
    else:
        out["cv_ratio"] = _safe_div(out["cv_forecast"], out["cv_actual"])

    if lower is not None and upper is not None:
        lo = _as_float(lower)[: len(mask) if False else n]
        # lower/upper llegan alineados al par filtrado solo si el caller ya filtró.
        lo = _as_float(lower)
        up = _as_float(upper)
        m = min(len(lo), len(up), len(a))
        if m:
            lo, up, aa = lo[:m], up[:m], a[:m]
            valid = np.isfinite(lo) & np.isfinite(up) & (up >= lo)
            if np.any(valid):
                out["picp"] = float(np.mean((aa[valid] >= lo[valid]) & (aa[valid] <= up[valid])))
                out["mpiw"] = float(np.mean(up[valid] - lo[valid]))
    return out


def calidad_forecast(forecast) -> dict:
    f = _as_float(forecast)
    f = f[np.isfinite(f)]
    n = len(f)
    info = {
        "n": n,
        "media": float(np.mean(f)) if n else math.nan,
        "min": float(np.min(f)) if n else math.nan,
        "max": float(np.max(f)) if n else math.nan,
        "pct_negativos": float(np.mean(f < 0)) if n else math.nan,
        "pct_ceros": float(np.mean(f == 0)) if n else math.nan,
        "cv": cv(f) if n else math.nan,
        "pegajosidad": math.nan,
    }
    if n >= 2:
        info["pegajosidad"] = float(np.mean(f[1:] == f[:-1]))
    return info


AYUDA = {
    "mae": "Error absoluto medio, en las mismas unidades de la demanda.",
    "rmse": "Raíz del error cuadrático. Un pico pesa más que en el MAE.",
    "mse": "Error cuadrático medio.",
    "medae": "Mediana del error absoluto. Ignora un pico suelto.",
    "me": "Sesgo medio. Positivo: el forecast se pasa. Negativo: se queda corto.",
    "bias_ratio": "Parte del error que no se cancela. Cerca de 1, todo el error es sesgo.",
    "mape": "Error porcentual medio. No se usa si la demanda tiene ceros.",
    "smape": "Error porcentual simétrico, de 0 a 2. Con ceros se infla: mirá el WAPE.",
    "wape": "Error absoluto pesado por el volumen. Más bajo, mejor.",
    "mase": "MAE contra repetir el último valor. Menor que 1 le gana al naive.",
    "mase_7": "MAE contra la demanda de hace 7 periodos.",
    "mase_12": "MAE contra la demanda de hace 12 periodos.",
    "rmsse": "RMSE contra los saltos de la demanda.",
    "pbias": "Sesgo sobre el volumen. Positivo: el forecast se pasa.",
    "fva_rel": "Positivo: el forecast le gana a repetir la demanda reciente.",
    "pearson": "Asociación lineal. No mira si el nivel está bien.",
    "r2": "Mejora contra pronosticar la media. Puede ser negativo.",
    "hit_20": "Fracción de periodos dentro de ±20%.",
    "hit_10": "Fracción de periodos dentro de ±10%.",
    "theil_u2": "Menor que 1 le gana al naive de no cambio.",
    "tracking_signal": "Deriva acumulada. Por encima de 4 el sesgo ya no es ruido.",
    "mda": "Aciertos de dirección: si la demanda sube o baja.",
    "adi": "Cada cuántos periodos hay una demanda distinta de cero.",
    "cv2": "Variabilidad de los tamaños cuando hay demanda.",
    "cv_ratio": "Si es mucho menor que 1, el forecast está planchado.",
    "mean_ratio": "Media del forecast sobre media de la venta. 1 es el nivel justo.",
    "picp": "Cobertura del intervalo: cuántos reales cayeron adentro.",
    "mpiw": "Ancho medio del intervalo, en unidades.",
    "mdape": "Mediana del error porcentual.",
    "mpe": "Sesgo porcentual medio. Un periodo chico lo domina.",
}

GRUPO = {
    "mae": "precision", "rmse": "precision", "mse": "precision", "medae": "precision",
    "mape": "precision", "smape": "precision", "wape": "precision", "mase": "precision",
    "mase_7": "precision", "mase_12": "precision", "rmsse": "precision", "theil_u2": "precision",
    "r2": "precision", "hit_10": "precision", "hit_20": "precision", "mda": "precision",
    "mdape": "precision",
    "me": "sesgo", "bias_ratio": "sesgo", "pbias": "sesgo", "mpe": "sesgo",
    "tracking_signal": "sesgo", "fva_rel": "sesgo",
    "mean_ratio": "escala", "cv_ratio": "escala", "pearson": "escala",
    "adi": "intermitencia", "cv2": "intermitencia",
    "picp": "intervalos", "mpiw": "intervalos",
}


def catalogo(metricas: dict) -> list[dict]:
    orden = [
        "wape", "mase", "mae", "rmse", "medae", "smape", "mape", "hit_20", "hit_10",
        "mase_7", "mase_12", "rmsse", "theil_u2", "r2", "mda", "mdape",
        "me", "pbias", "bias_ratio", "mpe", "tracking_signal", "fva_rel",
        "mean_ratio", "cv_ratio", "pearson",
        "adi", "cv2",
        "picp", "mpiw",
    ]
    filas = []
    for key in orden:
        if key not in metricas:
            continue
        filas.append({
            "id": key,
            "nombre": key.upper() if key in {"mae", "rmse", "mse", "wape", "mase", "mape", "smape"} else key,
            "valor": metricas[key],
            "ayuda": AYUDA.get(key, ""),
            "grupo": GRUPO.get(key, "precision"),
        })
    return filas
