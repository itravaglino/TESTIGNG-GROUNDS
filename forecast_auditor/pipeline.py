"""Orquesta la auditoría producto por producto."""

from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd

from forecast_auditor.baselines import candidate_forecasts
from forecast_auditor.diagnostics import holdout_bounds, series_diagnostics
from forecast_auditor.metrics import annotate_metrics, metric_bundle
from forecast_auditor.recommend import recommend_models
from forecast_auditor.schema import normalize_frame

METODOLOGIA = (
    "Las métricas de validación usan el último 20% de la historia (mínimo 8 períodos), "
    "y ese tramo no entra en el cálculo del sesgo ni en la elección del método base. "
    "Los métodos base predicen cada período solo con la demanda anterior. "
    "La corrección de sesgo multiplica o desplaza el pronóstico original; no lo reemplaza por la demanda real. "
    "El nivel del tramo futuro, cuando está desconectado de las últimas semanas reales, se recalibra con demanda ya conocida."
)


def analyze_frame(frame: pd.DataFrame) -> dict[str, Any]:
    table, meta = normalize_frame(frame)
    products = [_analyze_group(product, model, group) for product, model, group in _groups(table)]
    products.sort(key=lambda item: ({"descartar": 0, "corregir": 1, "mantener": 2}[item["veredicto"]], item["puntaje"]))
    summary = _summary(products)
    return _json_safe({
        "metodologia": METODOLOGIA,
        "columnas": meta["columns"],
        "avisos": meta["warnings"],
        "filas": meta["rows"],
        "resumen": summary,
        "productos": products,
    })


def _groups(table: pd.DataFrame):
    models = table["model"].fillna("").astype(str).str.strip()
    table = table.copy()
    table["model"] = models
    if models.ne("").any():
        for (product, model), group in table.groupby(["product", "model"], sort=False):
            yield str(product), str(model), group
    else:
        for product, group in table.groupby("product", sort=False):
            yield str(product), "", group


def _analyze_group(product: str, model: str, group: pd.DataFrame) -> dict[str, Any]:
    group = group.sort_values("date").reset_index(drop=True)
    diag = series_diagnostics(group)
    forecast = group["forecast"].to_numpy(dtype=float)
    actual = group["actual"].to_numpy(dtype=float)
    lower = group["lower"].to_numpy(dtype=float)
    upper = group["upper"].to_numpy(dtype=float)
    dates = pd.to_datetime(group["date"])
    period = int(diag["frecuencia"]["periodo"])
    clase = diag["demanda"]["clase"]
    last = diag["ultimo_real_pos"]
    n_actual = int(diag["n_reales"])

    descriptive = metric_bundle(forecast, actual, period, lower, upper) if n_actual else {"n": 0}
    validation = False
    eval_idx = np.array([], dtype=int)
    train_idx = np.array([], dtype=int)
    if last is not None:
        start, _end = holdout_bounds(last + 1)
        history_finite = np.array(
            [i for i in range(last + 1) if np.isfinite(actual[i]) and np.isfinite(forecast[i])],
            dtype=int,
        )
        if start < last + 1:
            eval_idx = history_finite[history_finite >= start]
            train_idx = history_finite[history_finite < start]
            validation = bool(eval_idx.size >= 6 and train_idx.size >= 8)
            if validation and clase in {"intermitente", "irregular"}:
                volume_eval = float(np.sum(np.abs(actual[eval_idx])))
                volume_all = float(np.sum(np.abs(actual[history_finite])))
                if volume_all > 0 and volume_eval < 0.12 * volume_all:
                    validation = False
        if not validation:
            eval_idx = history_finite
            train_idx = history_finite

    before = _window_metrics(forecast, actual, eval_idx, period, lower, upper)
    candidates = _candidates(forecast, actual, train_idx, diag, last, period)
    best_name = "Pronóstico original"
    best_pred = forecast.copy()
    best_score = _score_pred(forecast, actual, eval_idx)
    for name, pred in candidates:
        score = _score_pred(pred, actual, eval_idx)
        if _better(score, best_score):
            best_name, best_pred, best_score = name, pred, score

    # Si el original está a menos de 2 puntos de WMAPE, se queda: no se cambia un archivo por ruido.
    original_score = _score_pred(forecast, actual, eval_idx)
    tolerance = 0.05 if original_score[0] is not None and original_score[0] <= 0.35 else 0.02
    if (
        best_name != "Pronóstico original"
        and original_score[0] is not None
        and best_score[0] is not None
        and original_score[0] - best_score[0] < tolerance
        and diag["pct_negativos_pronostico"] == 0
    ):
        best_name, best_pred, best_score = "Pronóstico original", forecast.copy(), original_score

    broken = (
        diag["pct_nulos_pronostico"] >= 0.50
        or diag["n_pronostico"] < 3
        or diag["pct_faltantes"] > 0.40
        or (n_actual == 0 and (diag["pct_negativos_pronostico"] > 0.20 or _absurd_forecast(diag)))
    )
    if broken:
        best_name, best_pred = "Pronóstico original", forecast.copy()
    elif n_actual == 0 and 0 < diag["pct_negativos_pronostico"] <= 0.20:
        clipped = forecast.copy()
        finite = np.isfinite(clipped)
        clipped[finite] = np.maximum(clipped[finite], 0)
        best_name, best_pred = "Original recortado a cero", clipped

    best_pred, future_fixed, future_ratio = _rescale_future(best_pred, actual, last)
    if future_fixed:
        best_name = f"{best_name} + nivel futuro recalibrado"

    after = _window_metrics(best_pred, actual, eval_idx, period, None, None)
    if diag["pct_nulos_pronostico"] >= 0.50 or diag["n_pronostico"] < 3:
        before = {"n": 0}
        after = {"n": 0}
        descriptive = {"n": 0}
    reasons, tips, verdict, origin = _verdict(
        diag, before, after, best_name, validation, n_actual, future_fixed, future_ratio
    )
    if verdict == "descartar":
        best_pred = forecast.copy()
        best_name = "Pronóstico original"
        future_fixed = False
    elif verdict == "mantener":
        best_pred = forecast.copy()
        best_name = "Pronóstico original"
        after = dict(before)
    models, model_note = recommend_models(diag, n_actual, model)
    if model_note:
        tips.insert(0, model_note)

    archivo_mean = descriptive.get("media_real") if n_actual else None
    if (
        validation
        and isinstance(archivo_mean, float)
        and isinstance(before.get("media_real"), float)
        and abs(archivo_mean) > 1e-8
        and before["media_real"] < 0.55 * abs(archivo_mean)
    ):
        tips.append(
            "El tramo de validación cae en un valle de la demanda. El WMAPE de ese tramo se ve peor que el del archivo completo; mirá los dos."
        )
    score = _quality_score(before, diag)
    score_after = _quality_score(after, diag) if n_actual else None
    corrected_frame, imputed = _export_frame(
        product, model, dates, forecast, actual, best_pred, lower, upper, verdict, best_name, diag
    )
    if imputed:
        tips.append(
            f"Faltaban {diag['fechas_faltantes']} fechas del calendario {diag['frecuencia']['etiqueta']}. "
            "En el archivo corregido esas fechas se completan con interpolación corta y quedan marcadas como imputadas."
        )

    title = product if not model else f"{product} · {model}"
    return {
        "id": title,
        "producto": product,
        "modelo_declarado": model or None,
        "veredicto": verdict,
        "origen": origin,
        "confianza": _confidence(n_actual, validation, diag),
        "puntaje": score,
        "puntaje_corregido": score_after,
        "metodo_correccion": (
            "Fechas faltantes imputadas"
            if imputed and best_name == "Pronóstico original" and not future_fixed
            else None if best_name == "Pronóstico original" and not future_fixed else best_name
        ),
        "motivos": reasons,
        "como_mejorar": tips,
        "validacion": validation,
        "antes": before,
        "despues": after,
        "metricas_historial": annotate_metrics(descriptive) if n_actual else [],
        "metricas_validacion": annotate_metrics(before) if n_actual else [],
        "metricas_validacion_corregido": annotate_metrics(after) if n_actual and best_name != "Pronóstico original" else [],
        "diagnostico": _public_diag(diag),
        "modelos": models,
        "nota_modelo_actual": model_note,
        "serie": _chart(dates, forecast, actual, best_pred),
        "exportacion": corrected_frame,
        "fechas_imputadas": imputed,
    }


def _candidates(forecast, actual, train_idx, diag, last, period) -> list[tuple[str, np.ndarray]]:
    found: list[tuple[str, np.ndarray]] = []
    finite = np.isfinite(forecast)
    if diag["pct_negativos_pronostico"] > 0 and diag["pct_negativos_real"] == 0:
        clipped = forecast.copy()
        clipped[finite] = np.maximum(forecast[finite], 0)
        found.append(("Original recortado a cero", clipped))

    if train_idx.size >= 8:
        train_a = actual[train_idx]
        train_f = forecast[train_idx]
        pair = np.isfinite(train_a) & np.isfinite(train_f)
        if int(pair.sum()) >= 8:
            corr = _corr(train_a[pair], train_f[pair])
            scale_like = corr is not None and (
                corr >= 0.30 or (diag["cv_pronostico"] is not None and abs(diag["cv_pronostico"]) < 0.2)
            )
            denom = float(np.sum(np.abs(train_f[pair])))
            if scale_like and denom > 1e-8:
                factor = float(np.sum(train_a[pair]) / np.sum(train_f[pair]))
                if 0.4 <= factor <= 2.5 and abs(factor - 1) >= 0.05:
                    scaled = forecast.copy()
                    scaled[finite] = forecast[finite] * factor
                    if diag["pct_negativos_real"] == 0:
                        scaled[finite] = np.maximum(scaled[finite], 0)
                    found.append((f"Original recalibrado ×{factor:.3f}", scaled))
            delta = float(np.mean(train_a[pair] - train_f[pair]))
            mean_a = float(np.mean(np.abs(train_a[pair])))
            if scale_like and mean_a > 1e-8 and abs(delta) >= 0.05 * mean_a:
                shifted = forecast.copy()
                shifted[finite] = forecast[finite] + delta
                if diag["pct_negativos_real"] == 0:
                    shifted[finite] = np.maximum(shifted[finite], 0)
                found.append((f"Original desplazado {delta:+.2f}", shifted))

        if diag["outliers_pronostico"] > 0 and np.isfinite(train_f).sum() >= 8:
            hi = float(np.nanquantile(train_f, 0.95))
            lo = float(np.nanquantile(train_f, 0.05))
            if diag["pct_negativos_real"] == 0:
                lo = max(0.0, lo)
            capped = forecast.copy()
            capped[finite] = np.clip(forecast[finite], lo, hi)
            found.append(("Original con picos recortados", capped))

    if last is not None and int(np.isfinite(actual[: last + 1]).sum()) >= 8:
        y = pd.Series(actual[: last + 1]).ffill().fillna(0.0).to_numpy(dtype=float)
        horizon = int(len(forecast) - (last + 1))
        intermittent = diag["demanda"]["clase"] in {"intermitente", "irregular"} or (
            diag["demanda"]["pct_ceros"] or 0
        ) >= 0.25
        for name, pred in candidate_forecasts(y, horizon, period, intermittent):
            found.append((f"Reemplazo: {name}", pred))
    return found


def _better(score: tuple[float | None, float | None], best: tuple[float | None, float | None]) -> bool:
    wmape, mae = score
    best_wmape, best_mae = best
    if wmape is None:
        return False
    if best_wmape is None:
        return True
    if wmape < best_wmape - 1e-6:
        return True
    if abs(wmape - best_wmape) <= 1e-6 and mae is not None and (best_mae is None or mae < best_mae):
        return True
    return False


def _score_pred(pred: np.ndarray, actual: np.ndarray, idx: np.ndarray) -> tuple[float | None, float | None]:
    if idx.size == 0:
        return None, None
    a = actual[idx]
    p = pred[idx]
    mask = np.isfinite(a) & np.isfinite(p)
    if not mask.any():
        return None, None
    denom = float(np.sum(np.abs(a[mask])))
    abs_err = np.abs(p[mask] - a[mask])
    if denom < 1e-8:
        return None, float(np.mean(abs_err))
    return float(np.sum(abs_err) / denom), float(np.mean(abs_err))


def _window_metrics(pred, actual, idx, period, lower, upper) -> dict[str, Any]:
    if idx.size == 0:
        return {"n": 0}
    sl_lower = None if lower is None else np.asarray(lower)[idx]
    sl_upper = None if upper is None else np.asarray(upper)[idx]
    return metric_bundle(np.asarray(pred)[idx], np.asarray(actual)[idx], period, sl_lower, sl_upper)


def _rescale_future(pred: np.ndarray, actual: np.ndarray, last: int | None):
    if last is None or last + 1 >= len(pred):
        return pred, False, None
    future = pred[last + 1 :]
    finite = future[np.isfinite(future)]
    if finite.size < 4:
        return pred, False, None
    recent_idx = [i for i in range(last + 1) if np.isfinite(actual[i])][-8:]
    if len(recent_idx) < 4:
        return pred, False, None
    recent = float(np.mean(actual[recent_idx]))
    fut_mean = float(np.mean(finite))
    if recent <= 1e-6 or abs(fut_mean) <= 1e-8:
        return pred, False, None
    ratio = fut_mean / recent
    if 0.45 <= ratio <= 2.2:
        return pred, False, None
    out = pred.copy()
    out[last + 1 :] = future * (recent / fut_mean)
    return out, True, float(ratio)


def _verdict(diag, before, after, method, validation, n_actual, future_fixed, future_ratio):
    reasons: list[str] = []
    tips: list[str] = []
    wmape = before.get("wmape")
    mase = before.get("mase")
    after_wmape = after.get("wmape")
    clase = diag["demanda"]["clase"]
    acceptable = _acceptable(clase, wmape, mase)
    acceptable_after = _acceptable(clase, after_wmape, after.get("mase"))
    poor = _poor(clase, wmape, mase)
    changed = method != "Pronóstico original"
    gain = None
    if wmape is not None and after_wmape is not None:
        gain = wmape - after_wmape

    if diag["pct_nulos_pronostico"] >= 0.50 or diag["n_pronostico"] < 3:
        reasons.append("La mayor parte del pronóstico está vacía o la serie no alcanza para leerla.")
        tips.append("Volvé a exportar el pronóstico completo, con una fila por producto y fecha, sin celdas vacías.")
        return reasons, tips, "descartar", "inutilizable"

    if diag["pct_faltantes"] > 0.40:
        reasons.append(
            f"Falta el {diag['pct_faltantes'] * 100:.0f}% del calendario {diag['frecuencia']['etiqueta']}. El hueco ya no se puede imputar con seriedad."
        )
        tips.append("Completá el calendario antes de auditar. Una semana faltante tiene que existir, aunque la demanda sea cero.")
        return reasons, tips, "descartar", "inutilizable"

    if n_actual == 0:
        absurd = _absurd_forecast(diag)
        if diag["pct_negativos_pronostico"] > 0.20 or absurd:
            reasons.append("Sin demanda real, y el pronóstico tiene negativos o picos que no se pueden justificar.")
            tips.append("Si es demanda, el pronóstico no debería ser negativo. Si es otro tipo de serie, separala de este auditor.")
            return reasons, tips, "descartar", "inutilizable"
        if diag["pct_negativos_pronostico"] > 0:
            reasons.append("Hay pronósticos negativos. Se recortan a cero porque la demanda real, cuando exista, no debería ser negativa.")
            tips.append("Revisá el modelo: un SES o un Holt sin restricción puede cruzar a negativo.")
            return reasons, tips, "corregir", "ajustar"
        if diag["pct_faltantes"] > 0.05:
            reasons.append("El calendario está incompleto. La forma del pronóstico no muestra otro problema, pero faltan fechas.")
            tips.append("Cerrá el calendario de la frecuencia detectada antes de publicar el número.")
            return reasons, tips, "corregir", "ajustar"
        reasons.append("No vino demanda real. El pronóstico es internamente coherente, pero la precisión no se puede medir.")
        tips.append("Sumá la columna de ventas o demanda real para obtener WMAPE, MASE, sesgo y una recomendación de modelo con evidencia.")
        return reasons, tips, "mantener", "usable"

    if diag["pct_faltantes"] > 0.05:
        reasons.append(
            f"Faltan {diag['fechas_faltantes']} fechas del calendario {diag['frecuencia']['etiqueta']}."
        )
    if diag["pct_negativos_pronostico"] > 0 and diag["pct_negativos_real"] == 0:
        reasons.append(
            f"El {diag['pct_negativos_pronostico'] * 100:.0f}% del pronóstico es negativo y la demanda real no lo es."
        )
    if diag["outliers_pronostico"] >= 3:
        reasons.append(f"Hay {diag['outliers_pronostico']} picos del pronóstico fuera de su propia variación.")
    if diag["pronostico_plano"] and diag["hay_estacionalidad"]:
        reasons.append("El pronóstico está casi plano y la demanda tiene estacionalidad.")
        tips.append("Un SES o una media no van a seguir la temporada. Hace falta Holt-Winters, un naive estacional o un modelo con calendario.")
    bias = before.get("bias_pct")
    if isinstance(bias, float) and abs(bias) >= 0.10:
        lado = "de más" if bias > 0 else "de menos"
        reasons.append(f"El sesgo es {abs(bias) * 100:.0f}% {lado} respecto de la demanda media.")
        tips.append(
            "Antes de cambiar de modelo, corregí el nivel. Un factor estimado en el tramo de entrenamiento suele alcanzar cuando la forma ya acompaña."
        )
    noisy = isinstance(wmape, float) and wmape > 0.12
    if n_actual >= 16 and isinstance(mase, float) and mase > 1.15 and noisy:
        base = "naive estacional" if before.get("mase_base") == "estacional" else "período anterior"
        reasons.append(f"El MASE es {mase:.2f}: el pronóstico no le gana al {base}.")
        tips.append("No publiques un modelo que pierde contra el naive. El naive tiene que ser un rival obligatorio en la validación.")
    fva = before.get("fva_naive")
    if n_actual >= 16 and isinstance(fva, float) and fva < -0.10 and noisy:
        tips.append(
            f"El valor agregado contra el naive es {fva * 100:.0f}%. Hoy, repetir el período anterior erra menos."
        )
    if clase in {"intermitente", "irregular"}:
        tips.append(
            f"La demanda es {diag['demanda']['etiqueta'].lower()} (ADI { _fmt(diag['demanda']['adi']) }, CV² { _fmt(diag['demanda']['cv2']) }). "
            "Un modelo continuo va a pronosticar todas las semanas, también las que deberían dar cero."
        )
    if diag["tendencia"]["hay_tendencia"] and clase == "suave" and not diag["hay_estacionalidad"]:
        tips.append("Hay tendencia. Si el modelo no la tiene, el sesgo va a crecer de un lado en las próximas semanas.")
    if not validation and n_actual >= 8:
        tips.append("La historia no alcanza para un tramo de validación separado. Las métricas describen todo el archivo y son optimistas.")
    if future_fixed and future_ratio is not None:
        reasons.append(
            f"El tramo futuro quedó en {future_ratio:.1f}× el nivel de las últimas semanas reales y se recalibró a ese nivel."
        )
        tips.append("Revisá si ese salto futuro es una promo o un error de horizonte. La recalibración conserva la forma y corrige el nivel.")

    hard_short = n_actual < 8
    if hard_short:
        reasons.append(f"Solo hay {n_actual} períodos con demanda real. No alcanza para descartar el producto por precisión.")
        tips.append("Juntá al menos 16 períodos antes de elegir un modelo. Mientras tanto, media móvil o naive.")
        if changed or future_fixed:
            return reasons, tips, "corregir", "ajustar"
        return reasons, tips, "mantener", "usable"

    if poor and not acceptable_after:
        reasons.append("Ni el pronóstico original ni un método base simple llegan a un error usable en el tramo de control.")
        tips.append("No uses este número para comprar o producir. Revisá si el histórico está mal cargado, si el producto cambió, o si la unidad de medida no coincide.")
        return reasons, tips, "descartar", "inutilizable"

    material = changed and gain is not None and gain >= 0.08
    structural = future_fixed or diag["pct_faltantes"] > 0.05 or (
        diag["pct_negativos_pronostico"] > 0 and diag["pct_negativos_real"] == 0
    )
    if (not acceptable) or material or structural:
        if changed and gain is not None and gain > 0:
            reasons.append(
                f"La propuesta baja el WMAPE de {wmape * 100:.1f}% a {after_wmape * 100:.1f}% en el tramo de control."
                if wmape is not None and after_wmape is not None
                else "Hay una corrección que mejora el tramo de control."
            )
        if isinstance(after_wmape, float) and after_wmape > 0.60:
            tips.append(
                "La corrección mejora el archivo, pero el error sigue alto para comprometer un pedido ajustado. "
                "Usala como tasa y no como cantidad cerrada de cada período."
            )
        if method.startswith("Reemplazo"):
            tips.append(
                f"Conviene reemplazar el archivo por «{method.removeprefix('Reemplazo: ')}», actualizado cada período. "
                "El gráfico corregido es una predicción a un paso: muestra lo que el método habría dicho, no la demanda real."
            )
        elif changed:
            tips.append(f"Aplicá «{method}» al próximo ciclo. El factor sale del entrenamiento, no del tramo que se usa para juzgar.")
        origin = "inutilizable" if poor else "ajustar"
        if not changed and not structural and acceptable:
            return reasons, tips, "mantener", "usable"
        return reasons, tips, "corregir", origin

    if not reasons:
        reasons.append("El error, el sesgo y la forma están dentro de una banda usable. No hace falta tocar el número.")
    tips.append("Mantené el modelo, pero seguí comparándolo contra el naive cada ciclo. Un buen pronóstico también se degrada.")
    return reasons, tips, "mantener", "usable"


def _acceptable(clase: str, wmape, mase) -> bool:
    if wmape is None or not math.isfinite(float(wmape)):
        return False
    wmape = float(wmape)
    if clase in {"intermitente", "irregular"}:
        if isinstance(mase, float) and math.isfinite(mase) and mase <= 1.15:
            return True
        return wmape <= 0.70
    if isinstance(mase, float) and math.isfinite(mase) and mase <= 1.05 and wmape <= 0.50:
        return True
    return wmape <= 0.35


def _poor(clase: str, wmape, mase) -> bool:
    if wmape is None or not math.isfinite(float(wmape)):
        return True
    wmape = float(wmape)
    mase_poor = mase is None or not isinstance(mase, float) or not math.isfinite(mase) or mase >= 1.20
    if clase in {"intermitente", "irregular"}:
        return wmape >= 0.90 and (mase is None or not isinstance(mase, float) or mase >= 1.30)
    return wmape >= 0.55 and mase_poor


def _absurd_forecast(diag) -> bool:
    lo = diag["min_pronostico"]
    hi = diag["max_pronostico"]
    med = diag["media_pronostico"]
    if lo is None or hi is None or med is None:
        return True
    if abs(med) < 1e-8:
        return hi > 1
    return hi > max(50 * abs(med), abs(med) + 1) or (diag["outliers_pronostico"] >= 5 and hi > 20 * abs(med))


def _quality_score(metrics: dict[str, Any], diag: dict[str, Any]) -> float:
    score = 100.0
    wmape = metrics.get("wmape")
    if isinstance(wmape, float) and math.isfinite(wmape):
        score -= min(55.0, wmape * 100.0)
    mase = metrics.get("mase")
    if isinstance(mase, float) and math.isfinite(mase) and mase > 1:
        score -= min(20.0, (mase - 1) * 20.0)
    elif metrics.get("n", 0) == 0:
        score -= 25.0
    score -= min(15.0, float(diag["pct_negativos_pronostico"]) * 50.0)
    score -= min(10.0, float(diag["pct_faltantes"]) * 40.0)
    score -= min(50.0, float(diag["pct_nulos_pronostico"]) * 60.0)
    score -= min(8.0, float(diag["outliers_pronostico"]))
    return round(max(0.0, min(100.0, score)), 1)


def _confidence(n_actual: int, validation: bool, diag: dict[str, Any]) -> float:
    if n_actual == 0:
        base = 0.28
    elif n_actual < 8:
        base = 0.35
    elif validation and n_actual >= 52:
        base = 0.82
    elif validation:
        base = 0.68
    else:
        base = 0.5
    if diag["pct_faltantes"] > 0.1:
        base -= 0.08
    return round(max(0.15, min(0.9, base)), 2)


def _export_frame(product, model, dates, forecast, actual, corrected, lower, upper, verdict, method, diag):
    delta = pd.Timedelta(days=int(diag["frecuencia"]["delta_dias"]))
    observed = pd.DataFrame({
        "fecha": pd.to_datetime(dates),
        "pronostico_original": forecast,
        "real": actual,
        "pronostico_corregido": corrected,
        "limite_inf": lower,
        "limite_sup": upper,
    })
    full_index = pd.date_range(observed["fecha"].min(), observed["fecha"].max(), freq=delta)
    observed = observed.drop_duplicates("fecha", keep="last").set_index("fecha").sort_index()
    present = observed.index
    expanded = observed.reindex(full_index)
    missing = ~expanded.index.isin(present)
    # La imputación solo cubre huecos cortos, y solo si el producto no se descarta.
    if verdict != "descartar":
        expanded["pronostico_corregido"] = expanded["pronostico_corregido"].interpolate(limit=2)
    still_missing = expanded["pronostico_corregido"].isna() & missing
    imputed_mask = missing & expanded["pronostico_corregido"].notna()
    known_actual = expanded["real"].dropna()
    last_actual = known_actual.index.max() if len(known_actual) else None
    rows = []
    for fecha, row in expanded.iterrows():
        if bool(still_missing.loc[fecha]):
            estado_fecha = "hueco_largo"
        elif bool(imputed_mask.loc[fecha]):
            estado_fecha = "imputada"
        elif last_actual is not None and pd.Timestamp(fecha) > last_actual:
            estado_fecha = "futuro"
        elif pd.isna(row["real"]):
            estado_fecha = "hueco"
        else:
            estado_fecha = "historia"
        rows.append({
            "producto": product,
            "modelo_declarado": model,
            "fecha": pd.Timestamp(fecha).date().isoformat(),
            "pronostico_original": _num(row["pronostico_original"]),
            "real": _num(row["real"]),
            "pronostico_corregido": _num(row["pronostico_corregido"]),
            "limite_inf": _num(row["limite_inf"]),
            "limite_sup": _num(row["limite_sup"]),
            "veredicto": verdict,
            "metodo": method,
            "estado_fecha": estado_fecha,
        })
    return rows, int(imputed_mask.sum())


def _chart(dates, forecast, actual, corrected) -> list[dict[str, Any]]:
    n = len(dates)
    step = 1 if n <= 400 else math.ceil(n / 400)
    rows = []
    for i in range(0, n, step):
        rows.append({
            "fecha": pd.Timestamp(dates.iloc[i]).date().isoformat(),
            "pronostico": _num(forecast[i]),
            "real": _num(actual[i]),
            "corregido": _num(corrected[i]),
        })
    return rows


def _public_diag(diag: dict[str, Any]) -> dict[str, Any]:
    demand = diag["demanda"]
    trend = diag["tendencia"]
    return {
        "frecuencia": diag["frecuencia"]["etiqueta"],
        "periodo_estacional": diag["frecuencia"]["periodo"],
        "inicio": diag["inicio"],
        "fin": diag["fin"],
        "filas": diag["n_filas"],
        "reales": diag["n_reales"],
        "futuros": diag["n_futuro"],
        "fechas_faltantes": diag["fechas_faltantes"],
        "pct_faltantes": diag["pct_faltantes"],
        "pct_nulos_pronostico": diag["pct_nulos_pronostico"],
        "pct_negativos_pronostico": diag["pct_negativos_pronostico"],
        "pct_ceros_real": demand.get("pct_ceros"),
        "outliers": diag["outliers_pronostico"],
        "clase_demanda": demand["etiqueta"],
        "clase_codigo": demand["clase"],
        "adi": demand["adi"],
        "cv2": demand["cv2"],
        "estacionalidad": diag["estacionalidad"],
        "hay_estacionalidad": diag["hay_estacionalidad"],
        "hay_tendencia": trend["hay_tendencia"],
        "pendiente_pct_periodo": trend["pendiente_pct_periodo"],
        "cv_pronostico": diag["cv_pronostico"],
        "cv_real": diag["cv_real"],
        "pronostico_plano": diag["pronostico_plano"],
    }


def _summary(products: list[dict[str, Any]]) -> dict[str, Any]:
    counts = {"mantener": 0, "corregir": 0, "descartar": 0}
    weight_before = 0.0
    weight_after = 0.0
    volume = 0.0
    usable_volume = 0.0
    for product in products:
        counts[product["veredicto"]] += 1
        media = product["antes"].get("media_real")
        n = product["antes"].get("n") or 0
        if not isinstance(media, float) or n == 0:
            continue
        vol = abs(media) * n
        volume += vol
        if isinstance(product["antes"].get("wmape"), float):
            weight_before += product["antes"]["wmape"] * vol
        if product["veredicto"] != "descartar" and isinstance(product["despues"].get("wmape"), float):
            weight_after += product["despues"]["wmape"] * vol
            usable_volume += vol
    return {
        "productos": len(products),
        **counts,
        "wmape_ponderado_antes": None if volume <= 0 else weight_before / volume,
        "wmape_ponderado_despues": None if usable_volume <= 0 else weight_after / usable_volume,
        "puntaje_medio": None if not products else round(sum(p["puntaje"] for p in products) / len(products), 1),
    }


def _corr(a: np.ndarray, f: np.ndarray) -> float | None:
    if a.size < 3 or float(np.std(a)) < 1e-12 or float(np.std(f)) < 1e-12:
        if a.size >= 3 and float(np.std(f)) < 1e-12:
            return 0.0
        return None
    value = float(np.corrcoef(a, f)[0, 1])
    if not math.isfinite(value):
        return None
    return value


def _json_safe(value):
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, (np.floating, float)):
        number = float(value)
        return number if math.isfinite(number) else None
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.bool_,)):
        return bool(value)
    return value


def _num(value) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return round(number, 4)


def _fmt(value) -> str:
    if value is None or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        return "s/d"
    return f"{float(value):.2f}"
