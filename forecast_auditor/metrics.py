"""Métricas de precisión para pronósticos de demanda.

Las tasas (WMAPE, MAPE, hit rate, sesgo %) se devuelven como fracción: 0.2 = 20%.
El error se define como pronóstico − real. Un sesgo positivo es sobrepronóstico.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np

METRIC_META: list[dict[str, str]] = [
    {"id": "wmape", "nombre": "WMAPE", "formato": "pct", "grupo": "precisión",
     "ayuda": "Suma de errores absolutos dividida por la suma de la demanda real. Es la métrica principal porque respeta el volumen."},
    {"id": "mape", "nombre": "MAPE", "formato": "pct", "grupo": "precisión",
     "ayuda": "Error absoluto porcentual medio. Ignora los períodos con demanda real cero."},
    {"id": "smape", "nombre": "sMAPE", "formato": "pct", "grupo": "precisión",
     "ayuda": "Error porcentual simétrico. Menos explosivo que el MAPE cuando la demanda es chica."},
    {"id": "maape", "nombre": "MAAPE", "formato": "num", "grupo": "precisión",
     "ayuda": "Media del arco tangente del error porcentual. Acota el efecto de los ceros y de los picos."},
    {"id": "mae", "nombre": "MAE", "formato": "num", "grupo": "precisión",
     "ayuda": "Error absoluto medio, en las mismas unidades del producto."},
    {"id": "rmse", "nombre": "RMSE", "formato": "num", "grupo": "precisión",
     "ayuda": "Raíz del error cuadrático medio. Penaliza más los errores grandes."},
    {"id": "mse", "nombre": "MSE", "formato": "num", "grupo": "precisión",
     "ayuda": "Error cuadrático medio."},
    {"id": "medae", "nombre": "MedAE", "formato": "num", "grupo": "precisión",
     "ayuda": "Mediana del error absoluto. Resistente a un puñado de picos."},
    {"id": "rmsle", "nombre": "RMSLE", "formato": "num", "grupo": "precisión",
     "ayuda": "Error logarítmico. Útil cuando el producto se mueve en órdenes de magnitud distintos."},
    {"id": "mase", "nombre": "MASE", "formato": "num", "grupo": "contra base",
     "ayuda": "MAE dividido por el MAE del naive estacional (o del período anterior si no hay estacionalidad). Menor que 1 significa que el pronóstico le gana a esa base."},
    {"id": "rmsse", "nombre": "RMSSE", "formato": "num", "grupo": "contra base",
     "ayuda": "Versión del MASE con errores cuadráticos."},
    {"id": "fva_naive", "nombre": "FVA vs naive", "formato": "pct", "grupo": "contra base",
     "ayuda": "Valor agregado frente a repetir el período anterior. Positivo: el pronóstico aporta. Negativo: conviene el naive."},
    {"id": "fva_seasonal", "nombre": "FVA vs estacional", "formato": "pct", "grupo": "contra base",
     "ayuda": "Valor agregado frente a copiar la misma semana o el mismo mes del ciclo anterior."},
    {"id": "theil_u2", "nombre": "Theil U2", "formato": "num", "grupo": "contra base",
     "ayuda": "RMSE del pronóstico dividido por el RMSE del naive. Menor que 1 le gana al naive."},
    {"id": "bias", "nombre": "Sesgo (ME)", "formato": "num", "grupo": "sesgo",
     "ayuda": "Error medio. Positivo: se pronostica de más. Negativo: se pronostica de menos."},
    {"id": "bias_pct", "nombre": "Sesgo %", "formato": "pct", "grupo": "sesgo",
     "ayuda": "Sesgo dividido por la demanda media."},
    {"id": "mpe", "nombre": "MPE", "formato": "pct", "grupo": "sesgo",
     "ayuda": "Error porcentual medio, con signo. No entra en los períodos de demanda cero."},
    {"id": "tracking_signal", "nombre": "Tracking signal", "formato": "num", "grupo": "sesgo",
     "ayuda": "Error acumulado dividido por el MAD. Un valor que se va de ±4 indica que el sesgo se está acumulando."},
    {"id": "error_acumulado", "nombre": "Error acumulado", "formato": "num", "grupo": "sesgo",
     "ayuda": "Suma de pronóstico menos real. Es el faltante o el sobrante que el sesgo deja en el período."},
    {"id": "pct_sobre", "nombre": "% períodos sobre", "formato": "pct", "grupo": "sesgo",
     "ayuda": "Fracción de períodos en los que el pronóstico quedó por encima de la demanda."},
    {"id": "pct_bajo", "nombre": "% períodos bajo", "formato": "pct", "grupo": "sesgo",
     "ayuda": "Fracción de períodos en los que el pronóstico quedó por debajo de la demanda."},
    {"id": "hit_10", "nombre": "Acierto ±10%", "formato": "pct", "grupo": "acierto",
     "ayuda": "Períodos cuyo error absoluto no supera el 10% de la demanda real."},
    {"id": "hit_20", "nombre": "Acierto ±20%", "formato": "pct", "grupo": "acierto",
     "ayuda": "Períodos cuyo error absoluto no supera el 20% de la demanda real."},
    {"id": "hit_30", "nombre": "Acierto ±30%", "formato": "pct", "grupo": "acierto",
     "ayuda": "Períodos cuyo error absoluto no supera el 30% de la demanda real."},
    {"id": "error_abs_p50", "nombre": "Error abs. p50", "formato": "num", "grupo": "acierto",
     "ayuda": "Mediana del error absoluto."},
    {"id": "error_abs_p90", "nombre": "Error abs. p90", "formato": "num", "grupo": "acierto",
     "ayuda": "El error absoluto del peor 10% de los períodos empieza en este valor."},
    {"id": "correlacion", "nombre": "Correlación", "formato": "num", "grupo": "forma",
     "ayuda": "Correlación de Pearson entre pronóstico y demanda. Mide si la forma acompaña, más allá del nivel."},
    {"id": "r2", "nombre": "R²", "formato": "num", "grupo": "forma",
     "ayuda": "Proporción de la variación de la demanda que el pronóstico acompaña. Puede ser negativa si el pronóstico es peor que la media."},
    {"id": "cobertura_intervalo", "nombre": "Cobertura del intervalo", "formato": "pct", "grupo": "intervalo",
     "ayuda": "Fracción de reales que cayeron dentro del límite inferior y superior. Para una banda del 80% debería rondar ese valor."},
    {"id": "ancho_intervalo", "nombre": "Ancho del intervalo", "formato": "num", "grupo": "intervalo",
     "ayuda": "Ancho medio entre el límite superior y el inferior."},
    {"id": "winkler_80", "nombre": "Winkler (80%)", "formato": "num", "grupo": "intervalo",
     "ayuda": "Puntaje de Winkler asumiendo una banda nominal del 80%. Penaliza la banda ancha y, mucho más, dejar el real afuera."},
]


def _safe_div(num: float, den: float | None) -> float | None:
    if den is None or not np.isfinite(den) or abs(den) < 1e-12:
        return None
    if num is None or not np.isfinite(num):
        return None
    return float(num) / float(den)


def metric_bundle(
    forecast,
    actual,
    period: int,
    lower=None,
    upper=None,
) -> dict[str, Any]:
    f_all = np.asarray(forecast, dtype=float)
    a_all = np.asarray(actual, dtype=float)
    mask = np.isfinite(f_all) & np.isfinite(a_all)
    f = f_all[mask]
    a = a_all[mask]
    n = int(f.size)
    empty: dict[str, Any] = {"n": n}
    if n == 0:
        return empty

    err = f - a
    abs_err = np.abs(err)
    mae = float(np.mean(abs_err))
    mse = float(np.mean(err ** 2))
    rmse = float(math.sqrt(mse))
    medae = float(np.median(abs_err))
    bias = float(np.mean(err))
    sum_abs_a = float(np.sum(np.abs(a)))
    mean_a = float(np.mean(a))
    nonzero = np.abs(a) > 1e-8

    mape = float(np.mean(abs_err[nonzero] / np.abs(a[nonzero]))) if nonzero.any() else None
    smape_den = np.abs(a) + np.abs(f)
    smape_mask = smape_den > 1e-8
    smape = (
        float(np.mean(2.0 * abs_err[smape_mask] / smape_den[smape_mask]))
        if smape_mask.any()
        else None
    )
    maape = (
        float(np.mean(np.arctan(abs_err[nonzero] / np.abs(a[nonzero]))))
        if nonzero.any()
        else None
    )
    mpe = float(np.mean(err[nonzero] / a[nonzero])) if nonzero.any() else None

    seasonal_scale = bool(period and period >= 2 and n > period)
    m = int(period) if seasonal_scale else 1
    scale = float(np.mean(np.abs(a[m:] - a[:-m]))) if n > m else None
    scale_sq = float(np.mean((a[m:] - a[:-m]) ** 2)) if n > m else None
    mase = _safe_div(mae, scale)
    rmsse = _safe_div(rmse, math.sqrt(scale_sq)) if scale_sq is not None and scale_sq > 0 else None

    fva_naive = None
    theil_u2 = None
    if n > 1:
        naive_abs = np.abs(a[1:] - a[:-1])
        naive_mae = float(np.mean(naive_abs))
        model_mae_tail = float(np.mean(abs_err[1:]))
        fva_naive = None if naive_mae < 1e-12 else float((naive_mae - model_mae_tail) / naive_mae)
        naive_rmse = float(math.sqrt(np.mean((a[1:] - a[:-1]) ** 2)))
        model_rmse_tail = float(math.sqrt(np.mean((f[1:] - a[1:]) ** 2)))
        theil_u2 = _safe_div(model_rmse_tail, naive_rmse)

    fva_seasonal = None
    if m > 1 and n > m:
        seas_mae = float(np.mean(np.abs(a[m:] - a[:-m])))
        model_mae_tail = float(np.mean(abs_err[m:]))
        fva_seasonal = None if seas_mae < 1e-12 else float((seas_mae - model_mae_tail) / seas_mae)

    mad = float(np.mean(abs_err))
    tracking = None if mad < 1e-12 else float(np.sum(err) / mad)

    corr = None
    if n > 2 and float(np.std(a)) > 1e-12 and float(np.std(f)) > 1e-12:
        corr = float(np.corrcoef(a, f)[0, 1])
    ss_tot = float(np.sum((a - mean_a) ** 2))
    r2 = None if ss_tot < 1e-12 else float(1.0 - float(np.sum((a - f) ** 2)) / ss_tot)

    def hit(tol: float) -> float:
        return float(np.mean(abs_err <= (tol * np.maximum(np.abs(a), 1e-8))))

    rmsle = None
    if np.all(a >= -1e-8) and np.all(f >= -1e-8):
        rmsle = float(
            math.sqrt(
                np.mean(
                    (np.log1p(np.clip(f, 0, None)) - np.log1p(np.clip(a, 0, None))) ** 2
                )
            )
        )

    out: dict[str, Any] = {
        "n": n,
        "mae": mae,
        "mse": mse,
        "rmse": rmse,
        "medae": medae,
        "rmsle": rmsle,
        "mape": mape,
        "smape": smape,
        "wmape": _safe_div(float(np.sum(abs_err)), sum_abs_a),
        "maape": maape,
        "mase": mase,
        "mase_base": "estacional" if seasonal_scale else "periodo_anterior",
        "rmsse": rmsse,
        "bias": bias,
        "bias_pct": _safe_div(bias, abs(mean_a)),
        "mpe": mpe,
        "tracking_signal": tracking,
        "theil_u2": theil_u2,
        "fva_naive": fva_naive,
        "fva_seasonal": fva_seasonal,
        "correlacion": corr,
        "r2": r2,
        "hit_10": hit(0.10),
        "hit_20": hit(0.20),
        "hit_30": hit(0.30),
        "pct_sobre": float(np.mean(err > 1e-8)),
        "pct_bajo": float(np.mean(err < -1e-8)),
        "error_abs_p50": float(np.quantile(abs_err, 0.50)),
        "error_abs_p90": float(np.quantile(abs_err, 0.90)),
        "error_acumulado": float(np.sum(err)),
        "media_real": mean_a,
        "media_pronostico": float(np.mean(f)),
    }

    if lower is not None and upper is not None:
        lo = np.asarray(lower, dtype=float)
        up = np.asarray(upper, dtype=float)
        if lo.shape == f_all.shape and up.shape == f_all.shape:
            im = mask & np.isfinite(lo) & np.isfinite(up) & (up >= lo)
            if im.any():
                aa, l, u = a_all[im], lo[im], up[im]
                width = u - l
                alpha = 0.2
                wink = width.astype(float).copy()
                below = aa < l
                above = aa > u
                wink[below] = width[below] + (2.0 / alpha) * (l[below] - aa[below])
                wink[above] = width[above] + (2.0 / alpha) * (aa[above] - u[above])
                out["cobertura_intervalo"] = float(np.mean((aa >= l) & (aa <= u)))
                out["ancho_intervalo"] = float(np.mean(width))
                out["winkler_80"] = float(np.mean(wink))
                out["n_intervalo"] = int(im.sum())
    return out


def metric_status(metric_id: str, value: float | None, n: int = 0) -> str:
    if value is None or not np.isfinite(value):
        return "na"
    v = float(value)
    limits = {
        "wmape": (0.20, 0.40),
        "mape": (0.25, 0.50),
        "smape": (0.25, 0.50),
        "mase": (1.00, 1.25),
        "rmsse": (1.00, 1.25),
        "theil_u2": (1.00, 1.20),
        "maape": (0.25, 0.45),
    }
    if metric_id in limits:
        ok, warn = limits[metric_id]
        if v <= ok:
            return "ok"
        if v <= warn:
            return "warn"
        return "bad"
    if metric_id in {"bias_pct", "mpe"}:
        a = abs(v)
        if a <= 0.10:
            return "ok"
        if a <= 0.20:
            return "warn"
        return "bad"
    if metric_id == "tracking_signal":
        # En series largas un sesgo chico también empuja la señal; el umbral crece con la raíz del largo.
        band = 4.0 * max(1.0, math.sqrt(max(n, 1) / 12.0))
        a = abs(v)
        if a <= band:
            return "ok"
        if a <= band * 1.5:
            return "warn"
        return "bad"
    if metric_id in {"fva_naive", "fva_seasonal"}:
        if v >= 0:
            return "ok"
        if v >= -0.10:
            return "warn"
        return "bad"
    if metric_id == "correlacion":
        if v >= 0.60:
            return "ok"
        if v >= 0.30:
            return "warn"
        return "bad"
    if metric_id == "r2":
        if v >= 0.40:
            return "ok"
        if v >= 0.10:
            return "warn"
        return "bad"
    if metric_id in {"hit_10", "hit_20", "hit_30"}:
        target = {"hit_10": (0.55, 0.35), "hit_20": (0.70, 0.50), "hit_30": (0.80, 0.60)}[metric_id]
        if v >= target[0]:
            return "ok"
        if v >= target[1]:
            return "warn"
        return "bad"
    if metric_id == "cobertura_intervalo":
        if v >= 0.75:
            return "ok"
        if v >= 0.60:
            return "warn"
        return "bad"
    return "info"


def annotate_metrics(bundle: dict[str, Any]) -> list[dict[str, Any]]:
    n = int(bundle.get("n") or 0)
    rows = []
    for meta in METRIC_META:
        if meta["id"] not in bundle:
            continue
        value = bundle.get(meta["id"])
        rows.append({
            **meta,
            "valor": None if value is None or not np.isfinite(value) else float(value),
            "estado": metric_status(meta["id"], value if isinstance(value, (int, float)) else None, n),
        })
    return rows
