"""Reglas de auditoría de un pronóstico de demanda.

Funciones puras: no imprimen, no escriben archivos y no modifican las
entradas. Si un dato no alcanza para medir la condición, la regla se omite.

``diagnose`` arma los hallazgos. ``verdict`` los resume en una decisión.

Esquema que leen las reglas
---------------------------
DataFrame (columnas canónicas, también se aceptan alias en español o de
prophet):

- ``date`` / ``fecha`` / ``ds``: período. Si no hay columna, se usa un
  índice de fechas.
- ``actual`` / ``demanda`` / ``y``: demanda real. NaN en el horizonte.
- ``forecast`` / ``pronostico`` / ``yhat``: pronóstico.

``metrics`` (primero) y ``profile`` (si no está en metrics), mismas unidades:

- ``wape``: fracción. 0,35 es 35 %. Puede pasar de 1.
- ``n``: períodos donde hay demanda y pronóstico (también ``n_overlap``).
- ``bias_pct``: puntos porcentuales. 20 es 20 %. Positivo = el pronóstico
  está por encima de la demanda: 100 * suma(pronóstico - demanda) / suma(demanda).
- ``fva_vs_naive``: fracción. Positivo = le gana al método ingenuo.
- ``flatness``: 0 a 1. 1 = pronóstico totalmente plano.
- ``tracking_signal``: suma del error / error absoluto medio.
- ``over_forecast_pct``, ``negative_forecast_pct``, ``zero_forecast_pct``,
  ``zero_actual_pct``: fracciones de 0 a 1.
- ``cv_forecast``: desvío / |promedio|.
- ``history_ratio``: promedio del pronóstico futuro / promedio de la historia.
- ``n_forecast``, ``n_future``, ``n_actual``, ``unique_forecast_values``.
- ``missing_date_gaps``: períodos que faltan entre la primera y la última fecha.
- ``mean_actual``.
- ``seasonality_strength``: 0 a 1. También se lee de ``profile``.
- ``demand_class``: ``smooth``, ``erratic``, ``intermittent`` o ``lumpy``.
  También se lee de ``profile``.

Si la clave no viene, se calcula desde el DataFrame cuando se puede.
"""

from __future__ import annotations

from typing import Any, Mapping, Optional, Sequence

import numpy as np
import pandas as pd

# Umbrales de las reglas. Las unidades están en el docstring del módulo.
NEG_MOSTLY = 0.5
HISTORY_HI = 10.0
HISTORY_LO = 0.1
MIN_HISTORY = 6
MIN_FUTURE = 3
Z_SPIKE = 3.5
MIN_Z_POINTS = 4
EXPLOSION_RATIO = 5.0
EXPLOSION_GROWTH = 3.0  # (último - anterior) / anterior; 3 = 300 %
MIN_EXPLOSION_N = 6
COLLAPSE_RATIO = 0.15
MIN_COLLAPSE_PRIOR = 3
WAPE_HIGH = 0.35
WAPE_CORRECT = 0.5
WAPE_DISCARD = 1.0
BIAS_PCT = 20.0
FVA_LOSE = -0.05
FVA_BEAT = 0.1
FLATNESS = 0.85
FLATNESS_SEASON = 0.7
FLATNESS_VERDICT = 0.9
SEASONALITY = 0.4
MIN_HORIZON = 6
ZERO_FORECAST_SMOOTH = 0.05
CV_SMOOTH = 0.15
OVER_FORECAST = 0.75
TRACKING = 4.0
ZERO_ACTUAL_HIGH = 0.50
MIN_ZERO_ACTUAL_N = 6
ZERO_EPS = 1e-8

_PENALTY = {"critical": 40, "error": 20, "warning": 8, "info": 2}
_SEVERITY_RANK = {"critical": 0, "error": 1, "warning": 2, "info": 3}

_DATE_ALIASES = (
    "date",
    "fecha",
    "ds",
    "period",
    "periodo",
    "timestamp",
    "time",
    "fecha_periodo",
    "period_start",
    "period_end",
)
_ACTUAL_ALIASES = (
    "actual",
    "actuals",
    "demanda",
    "demand",
    "y",
    "ventas",
    "sales",
    "history",
    "historico",
    "y_true",
    "demanda_real",
    "actual_value",
    "qty_actual",
    "real",
    "target",
    "unidades",
    "units",
    "quantity",
    "qty",
)
_FORECAST_ALIASES = (
    "forecast",
    "pronostico",
    "yhat",
    "prediccion",
    "prediction",
    "forecast_value",
    "y_pred",
    "forecast_qty",
    "pronostico_valor",
    "qty_forecast",
    "fcst",
    "pred",
)
_KIND_ALIASES = ("kind", "type", "tipo", "series", "variable", "role")
_VALUE_ALIASES = ("value", "valor", "cantidad", "qty", "quantity", "unidades")

_FREQ_TO_PERIOD = {
    "d": "D",
    "day": "D",
    "daily": "D",
    "diaria": "D",
    "diario": "D",
    "dia": "D",
    "w": "W",
    "week": "W",
    "weekly": "W",
    "semanal": "W",
    "semana": "W",
    "m": "M",
    "ms": "M",
    "me": "M",
    "month": "M",
    "monthly": "M",
    "mensual": "M",
    "mes": "M",
    "q": "Q",
    "qs": "Q",
    "qe": "Q",
    "quarter": "Q",
    "quarterly": "Q",
    "trimestral": "Q",
    "trimestre": "Q",
    "y": "Y",
    "ys": "Y",
    "ye": "Y",
    "a": "Y",
    "year": "Y",
    "yearly": "Y",
    "anual": "Y",
    "annual": "Y",
    "h": "h",
    "hourly": "h",
    "hora": "h",
    "b": "B",
    "business": "B",
    "habil": "B",
    "dias_habiles": "B",
}
_PERIOD_LABEL = {
    "D": "diaria",
    "W": "semanal",
    "M": "mensual",
    "Q": "trimestral",
    "Y": "anual",
    "h": "horaria",
    "B": "de días hábiles",
}
_CLASS_ES = {
    "smooth": "suave",
    "erratic": "errática",
    "intermittent": "intermitente",
    "lumpy": "lumpy (picos irregulares y muchos ceros)",
}
_NESTED_BUCKETS = (
    "demand",
    "forecast",
    "accuracy",
    "series",
    "summary",
    "stats",
    "quality",
    "history",
    "actual",
)


def diagnose(
    df: pd.DataFrame,
    frequency: str,
    profile: dict,
    metrics: dict,
) -> list[dict]:
    """Hallazgos ordenados por severidad: critical, error, warning, info."""
    ctx = _build_context(df, frequency, profile, metrics)
    findings = []
    for rule in _RULES:
        finding = rule(ctx)
        if finding is not None:
            findings.append(finding)
    findings.sort(key=lambda item: (_SEVERITY_RANK.get(item["severity"], 9), _RULE_INDEX[item["id"]]))
    return findings


def verdict(findings: list[dict], metrics: dict, profile: dict) -> dict:
    """Decide descartar, corregir o aprobar, y asigna un puntaje de 0 a 100."""
    findings = [item for item in (findings or []) if isinstance(item, dict)]
    metrics = metrics or {}
    profile = profile or {}

    wape = _as_float(_lookup((metrics, profile), ("wape",)))
    n = _as_float(_lookup((metrics, profile), ("n", "n_overlap", "n_points", "n_paired", "n_eval")))
    flatness = _as_float(_lookup((metrics, profile), ("flatness", "forecast_flatness")))
    n_forecast = _as_float(_lookup((metrics, profile), ("n_forecast", "n_forecasts")))
    intermittent = _demand_is_intermittent(metrics, profile)
    n_forecast_metric = n_forecast

    critical = [item for item in findings if item.get("severity") == "critical"]
    errors = [item for item in findings if item.get("severity") == "error"]
    warnings = [item for item in findings if item.get("severity") == "warning"]
    infos = [item for item in findings if item.get("severity") == "info"]
    to_correct = [
        item
        for item in findings
        if item.get("severity") == "error" or item.get("action") == "correct"
    ]

    no_values = _forecast_has_no_values(findings, n_forecast_metric, metrics, profile)
    discard_reasons: list[str] = []
    if critical:
        discard_reasons.append("Hay hallazgos críticos: " + _join(_titles(critical)) + ".")
    if len(errors) >= 2:
        discard_reasons.append(
            f"Hay {_fmt_count(len(errors))} errores: " + _join(_titles(errors)) + "."
        )
    if wape is not None and wape > WAPE_DISCARD and n is not None and n >= MIN_HORIZON:
        discard_reasons.append(
            "El WAPE es "
            + _fmt_pct(wape)
            + f" en {_fmt_count(n)} períodos: el error supera a la demanda."
        )
    if no_values and not any(item.get("id") == "no_forecast_values" for item in critical):
        discard_reasons.append("El pronóstico no tiene valores numéricos utilizables.")

    if discard_reasons or no_values or critical or len(errors) >= 2 or (
        wape is not None and wape > WAPE_DISCARD and n is not None and n >= MIN_HORIZON
    ):
        if not discard_reasons:
            discard_reasons.append("El pronóstico no se puede usar tal como está.")
        return {
            "decision": "descartar",
            "score": _score(findings, wape),
            "reasons": discard_reasons,
        }

    correct_reasons: list[str] = []
    if errors or any(item.get("action") == "correct" for item in findings):
        names = _titles(to_correct) or _titles(errors)
        correct_reasons.append("Hay que corregir: " + _join(names) + ".")
    if wape is not None and wape > WAPE_CORRECT:
        correct_reasons.append(
            "El WAPE es " + _fmt_pct(wape) + ", por encima del 50%."
        )
    cv_actual = _as_float(_lookup((metrics, profile), ("cv_actual",)))
    demand_moves = cv_actual is None or cv_actual > 0.15
    already_accurate = wape is not None and wape <= 0.25
    if (
        flatness is not None
        and flatness > FLATNESS_VERDICT
        and n_forecast is not None
        and n_forecast >= MIN_HORIZON
        and intermittent is not True
        and demand_moves
        and not already_accurate
    ):
        correct_reasons.append(
            "El pronóstico está casi plano (planitud "
            + _fmt_num(flatness, 2)
            + ") en "
            + _fmt_count(n_forecast)
            + " períodos y la demanda no es intermitente."
        )
    if correct_reasons:
        return {
            "decision": "corregir",
            "score": _score(findings, wape),
            "reasons": correct_reasons,
        }

    approve_reasons: list[str] = []
    if warnings:
        approve_reasons.append(
            "Se puede aprobar, con "
            + _plural(len(warnings), "advertencia", "advertencias")
            + " para revisar: "
            + _join(_titles(warnings))
            + "."
        )
    else:
        approve_reasons.append("No hay hallazgos que impidan aprobar el pronóstico.")
    if infos and not warnings:
        approve_reasons.append("Notas: " + _join(_titles(infos)) + ".")
    return {
        "decision": "aprobar",
        "score": _score(findings, wape),
        "reasons": approve_reasons,
    }


def _score(findings: Sequence[Mapping[str, Any]], wape: Optional[float]) -> int:
    score = 100
    for finding in findings:
        score -= _PENALTY.get(str(finding.get("severity")), 0)
    if wape is not None and wape > 0:
        score -= min(30, int(wape * 40))
    if score < 0:
        return 0
    return int(score)


def _forecast_has_no_values(findings, n_forecast, metrics, profile) -> bool:
    if any(item.get("id") == "no_forecast_values" for item in findings):
        return True
    flag = _lookup((metrics, profile), ("has_usable_forecast", "forecast_has_values"))
    if flag is False or flag == 0:
        return True
    if n_forecast is not None and n_forecast <= 0:
        return True
    return False


def _demand_is_intermittent(metrics, profile) -> Optional[bool]:
    """True intermitente o lumpy, False si se sabe que no, None si no hay dato."""
    label = _lookup(
        (profile, metrics),
        ("demand_class", "demand_type", "series_class", "demand_pattern"),
    )
    if label is not None:
        kind = _normalize_class(label)
        if kind in ("intermittent", "lumpy"):
            return True
        if kind in ("smooth", "erratic"):
            return False
        folded = _fold(label)
        if "intermit" in folded or "lumpy" in folded or "abult" in folded:
            return True
        return False
    flag = _lookup((profile, metrics), ("intermittent", "is_intermittent"))
    if isinstance(flag, (bool, np.bool_)):
        return bool(flag)
    return None


# ---------------------------------------------------------------------------
# Hallazgos
# ---------------------------------------------------------------------------


def _rule_no_forecast_values(ctx: dict) -> Optional[dict]:
    n_forecast = ctx["n_forecast"]
    if n_forecast is None or n_forecast > 0:
        return None
    return _finding(
        "no_forecast_values",
        "critical",
        "No hay valores de pronóstico",
        "Todos los valores del pronóstico están vacíos o no son numéricos, así que no hay nada que evaluar.",
        "Cargar un número de pronóstico para cada período del horizonte.",
        "discard",
    )


def _rule_mostly_negative(ctx: dict) -> Optional[dict]:
    pct = ctx["negative_forecast_pct"]
    n_forecast = ctx["n_forecast"]
    if pct is None or n_forecast is None or n_forecast <= 0 or pct < NEG_MOSTLY:
        return None
    detail = (
        "El "
        + _fmt_pct(pct)
        + " del pronóstico es negativo ("
        + _fmt_count(ctx["n_negative"] if ctx["n_negative"] is not None else pct * n_forecast)
        + " de "
        + _fmt_count(n_forecast)
        + " valores)"
    )
    if ctx["forecast_min"] is not None:
        detail += ". El valor más bajo es " + _fmt_num(ctx["forecast_min"], 2)
    detail += "."
    return _finding(
        "mostly_negative",
        "critical",
        "La mayor parte del pronóstico es negativa",
        detail,
        "La demanda no puede ser negativa. Corregir el cálculo o llevar los negativos a cero antes de publicar.",
        "discard",
    )


def _rule_no_variation_and_no_history(ctx: dict) -> Optional[dict]:
    n_forecast = ctx["n_forecast"]
    n_actual = ctx["n_actual"]
    unique = ctx["unique_forecast_values"]
    if n_forecast is None or n_actual is None or unique is None:
        return None
    if n_forecast < MIN_HORIZON or unique != 1 or n_actual != 0:
        return None
    detail = (
        "Hay "
        + _fmt_count(n_forecast)
        + " períodos de pronóstico y todos valen lo mismo"
    )
    if ctx["flat_value"] is not None:
        detail += " (" + _fmt_num(ctx["flat_value"], 2) + ")"
    detail += ", pero no hay demanda histórica para contrastarlos."
    return _finding(
        "no_variation_and_no_history",
        "critical",
        "Pronóstico plano y sin historia",
        detail,
        "No publicar un valor único sin historia. Cargar la demanda real o rehacer el pronóstico con un método que use datos.",
        "discard",
    )


def _rule_absurd_level(ctx: dict) -> Optional[dict]:
    ratio = ctx["history_ratio"]
    n_actual = ctx["n_actual"]
    n_future = ctx["n_future"]
    if ratio is None or n_actual is None or n_future is None:
        return None
    if n_actual < MIN_HISTORY or n_future < MIN_FUTURE:
        return None
    if not (ratio >= HISTORY_HI or ratio <= HISTORY_LO):
        return None
    if ratio >= HISTORY_HI:
        comparison = (
            "el pronóstico futuro queda "
            + _fmt_num(ratio, 1)
            + " veces por encima de la demanda histórica"
        )
    elif ratio >= 0:
        comparison = (
            "el pronóstico futuro es apenas el "
            + _fmt_pct(ratio)
            + " de la demanda histórica"
        )
    else:
        comparison = (
            "el pronóstico futuro es negativo y equivale a "
            + _fmt_num(ratio, 1)
            + " veces la demanda histórica"
        )
    extra = []
    if ctx["mean_actual"] is not None:
        extra.append("demanda promedio " + _fmt_num(ctx["mean_actual"], 2))
    if ctx["mean_future"] is not None:
        extra.append("pronóstico futuro promedio " + _fmt_num(ctx["mean_future"], 2))
    detail = (
        "Con "
        + _fmt_count(n_actual)
        + " períodos reales y "
        + _fmt_count(n_future)
        + " períodos futuros, "
        + comparison
    )
    if extra:
        detail += " (" + "; ".join(extra) + ")"
    detail += "."
    return _finding(
        "absurd_level",
        "critical",
        "El nivel del pronóstico no cierra con la historia",
        detail,
        "Revisar unidades y escala (miles contra unidades, por ejemplo). Ajustar el nivel para que quede en el orden de la demanda histórica.",
        "discard",
    )


def _rule_some_negative(ctx: dict) -> Optional[dict]:
    pct = ctx["negative_forecast_pct"]
    n_forecast = ctx["n_forecast"]
    if pct is None or n_forecast is None or n_forecast <= 0:
        return None
    if pct <= 0 or pct >= NEG_MOSTLY:
        return None
    n_negative = ctx["n_negative"]
    if n_negative is None:
        n_negative = pct * n_forecast
    detail = (
        "Hay "
        + _fmt_count(n_negative)
        + " valores negativos ("
        + _fmt_pct(pct)
        + " de "
        + _fmt_count(n_forecast)
        + ")"
    )
    if ctx["forecast_min"] is not None:
        detail += ". El más bajo es " + _fmt_num(ctx["forecast_min"], 2)
    detail += "."
    return _finding(
        "some_negative",
        "error",
        "Hay pronósticos negativos",
        detail,
        "Reemplazar los negativos por cero o corregir el modelo: la demanda no debería bajar de cero.",
        "correct",
    )


def _rule_duplicates_remain(ctx: dict) -> Optional[dict]:
    extra = ctx["duplicate_extra"]
    if extra is None or extra <= 0:
        return None
    n_dates = ctx["duplicate_dates"] or extra
    detail = (
        "Quedan "
        + _plural(extra, "fila repetida", "filas repetidas")
        + " en "
        + _plural(n_dates, "fecha", "fechas")
    )
    examples = ctx["duplicate_examples"]
    if examples:
        detail += " (por ejemplo " + ", ".join(examples) + ")"
    detail += ". Cada período debería aparecer una sola vez."
    return _finding(
        "duplicates_remain",
        "error",
        "Quedan fechas duplicadas",
        detail,
        "Unir las filas de la misma fecha y dejar una sola demanda y un solo pronóstico por período.",
        "correct",
    )


def _rule_gap(ctx: dict) -> Optional[dict]:
    gaps = ctx["missing_date_gaps"]
    if gaps is None or gaps <= 0:
        return None
    severity = "error" if gaps >= 2 else "warning"
    action = "correct" if severity == "error" else "review"
    freq = ctx["freq_label"]
    where = f" en la serie {freq}" if freq else " en la serie"
    detail = "Falta " if abs(gaps - 1) < 1e-9 else "Faltan "
    detail += _plural(gaps, "período", "períodos") + where
    if ctx["gap_expected"] is not None and ctx["gap_observed"] is not None:
        detail += (
            " (hay "
            + _fmt_count(ctx["gap_observed"])
            + " y el calendario pide "
            + _fmt_count(ctx["gap_expected"])
            + ")"
        )
    detail += "."
    suggestion = (
        "Completar los huecos. Si no hubo demanda, cargar cero: no omitir la fecha."
        if severity == "error"
        else "Completar el período que falta. Un solo hueco ya corre el calendario."
    )
    return _finding(
        "gap",
        severity,
        "Faltan períodos en la serie",
        detail,
        suggestion,
        action,
    )


def _rule_outlier_spikes(ctx: dict) -> Optional[dict]:
    spikes = ctx["spikes"]
    if not spikes:
        return None
    worst = max(spikes, key=lambda item: abs(item["z"]) if np.isfinite(item["z"]) else 1e308)
    z_text = "un z muy alto" if not np.isfinite(worst["z"]) else "z " + _fmt_num(worst["z"], 1)
    where = ""
    if worst.get("date"):
        where = " el " + worst["date"]
    detail = (
        "Hay "
        + _plural(len(spikes), "punto", "puntos")
        + " muy alejados del resto del pronóstico (z modificado mayor a 3,5: "
        + "qué tan lejos está el punto de la mediana, medida en desvíos absolutos). "
        + "El mayor es "
        + _fmt_num(worst["value"], 2)
        + where
        + " ("
        + z_text
        + ")."
    )
    return _finding(
        "outlier_spikes",
        "error",
        "Hay picos atípicos en el pronóstico",
        detail,
        "Revisar esos picos uno por uno: pueden ser un error de carga o un evento que conviene dejar fuera del pronóstico base.",
        "correct",
    )


def _rule_explosion(ctx: dict) -> Optional[dict]:
    info = ctx["explosion"]
    if not info:
        return None
    parts = []
    if info["ratio_hit"]:
        parts.append(
            "el último valor es "
            + _fmt_num(info["last"], 2)
            + " y la mediana de los "
            + _fmt_count(info["prior_n"])
            + " anteriores es "
            + _fmt_num(info["median"], 2)
            + " ("
            + _fmt_num(info["ratio"], 1)
            + " veces; el umbral es 5)"
        )
    if info["growth_hit"]:
        parts.append(
            "el último salto va de "
            + _fmt_num(info["prev"], 2)
            + " a "
            + _fmt_num(info["last"], 2)
            + ", un alza del "
            + _fmt_pct(info["growth"])
            + " (el umbral es 300%)"
        )
    detail = "Al final " + " y ".join(parts) + "."
    if info.get("date"):
        detail += " Fecha del último punto: " + info["date"] + "."
    return _finding(
        "explosion",
        "error",
        "El pronóstico se dispara al final",
        detail,
        "Revisar el último período. Si no hay un evento que lo justifique, bajar ese valor: un salto así suele ser un error.",
        "correct",
    )


def _rule_collapse(ctx: dict) -> Optional[dict]:
    info = ctx["collapse"]
    if not info:
        return None
    detail = (
        "El último pronóstico es "
        + _fmt_num(info["last"], 2)
        + ", el "
        + _fmt_pct(info["ratio"])
        + " de la mediana previa de pronósticos positivos ("
        + _fmt_num(info["median_forecast"], 2)
        + "). La última demanda real fue "
        + _fmt_num(info["last_actual"], 2)
        + " y no está igual de baja (mediana de la demanda positiva previa "
        + _fmt_num(info["median_actual"], 2)
        + ")."
    )
    if info.get("date"):
        detail += " Fecha del último pronóstico: " + info["date"] + "."
    return _finding(
        "collapse",
        "error",
        "El pronóstico se cae al final",
        detail,
        "Revisar el último período. La demanda reciente no acompaña semejante baja, así que conviene rehacer ese valor.",
        "correct",
    )


def _rule_all_zero_forecast(ctx: dict) -> Optional[dict]:
    if not ctx["all_zero_forecast"]:
        return None
    mean_actual = ctx["mean_actual"]
    n_forecast = ctx["n_forecast"]
    detail = "Todos los valores del pronóstico son 0"
    if n_forecast is not None:
        detail = "Los " + _fmt_count(n_forecast) + " valores del pronóstico son 0"
    detail += " y la demanda histórica promedio es " + _fmt_num(mean_actual, 2) + "."
    return _finding(
        "all_zero_forecast",
        "error",
        "El pronóstico está todo en cero",
        detail,
        "Rehacer el pronóstico. Un horizonte en cero no sirve si la historia muestra demanda.",
        "correct",
    )


def _rule_high_wape(ctx: dict) -> Optional[dict]:
    wape = ctx["wape"]
    if wape is None or wape <= WAPE_HIGH:
        return None
    detail = "El WAPE es " + _fmt_pct(wape)
    if ctx["n"] is not None:
        detail += " en " + _fmt_count(ctx["n"]) + " períodos"
    detail += (
        ". El WAPE es el error absoluto dividido por la demanda: "
        "por encima de 35% ya pesa en el plan."
    )
    return _finding(
        "high_wape",
        "warning",
        "El error del pronóstico es alto",
        detail,
        "Revisar el método o separar los períodos raros. Con este error conviene ajustar el número antes de usarlo en el plan.",
        "review",
    )


def _rule_strong_bias(ctx: dict) -> Optional[dict]:
    bias = ctx["bias_pct"]
    if bias is None or abs(bias) <= BIAS_PCT:
        return None
    side = "por encima" if bias > 0 else "por debajo"
    detail = (
        "El sesgo es "
        + _fmt_signed_pct(bias)
        + ". Está medido como pronóstico menos demanda, dividido por la demanda: "
        + "el pronóstico queda "
        + side
        + " de la demanda, y el umbral es 20%."
    )
    return _finding(
        "strong_bias",
        "warning",
        "El pronóstico está sesgado",
        detail,
        "Corregir el nivel para acercarlo a la demanda real: el error se inclina siempre para el mismo lado.",
        "review",
    )


def _rule_loses_to_naive(ctx: dict) -> Optional[dict]:
    fva = ctx["fva_vs_naive"]
    if fva is None or fva >= FVA_LOSE:
        return None
    detail = (
        "El valor agregado contra el método ingenuo es "
        + _fmt_signed_pct(fva * 100.0)
        + ". El método ingenuo es repetir la demanda reciente: "
        "un valor menor a -5% quiere decir que eso hubiera errado menos."
    )
    return _finding(
        "loses_to_naive",
        "warning",
        "Rinde peor que repetir la historia",
        detail,
        "Si no le gana a repetir el último período, simplificar el método o revisar los parámetros antes de confiar en él.",
        "review",
    )


def _rule_flat_forecast(ctx: dict) -> Optional[dict]:
    flatness = ctx["flatness"]
    n_forecast = ctx["n_forecast"]
    if flatness is None or n_forecast is None:
        return None
    if flatness < FLATNESS or n_forecast < MIN_HORIZON:
        return None
    if ctx["intermittent"] is True:
        return None
    cv_actual = ctx.get("cv_actual")
    if cv_actual is not None and cv_actual <= 0.15:
        return None
    if ctx.get("wape") is not None and ctx["wape"] <= 0.20:
        return None
    clase = _class_phrase(ctx)
    detail = (
        "La planitud es "
        + _fmt_num(flatness, 2)
        + " en "
        + _fmt_count(n_forecast)
        + " períodos (1 = todos los valores iguales) y "
        + clase
        + "."
    )
    return _finding(
        "flat_forecast",
        "warning",
        "El pronóstico está casi plano",
        detail,
        "Usar un método que mueva el pronóstico con la demanda. Un valor casi constante no alcanza cuando la serie varía.",
        "review",
    )


def _rule_ignores_seasonality(ctx: dict) -> Optional[dict]:
    seasonal = ctx["seasonality_strength"]
    flatness = ctx["flatness"]
    if seasonal is None or flatness is None:
        return None
    if seasonal < SEASONALITY or flatness < FLATNESS_SEASON:
        return None
    detail = (
        "La estacionalidad de la demanda es "
        + _fmt_num(seasonal, 2)
        + " (0 = nada, 1 = muy marcada) y el pronóstico está plano (planitud "
        + _fmt_num(flatness, 2)
        + ")."
    )
    return _finding(
        "ignores_seasonality",
        "warning",
        "El pronóstico no sigue la estacionalidad",
        detail,
        "Incorporar el patrón de la misma época en años anteriores. Un pronóstico plano se pierde los picos de temporada.",
        "review",
    )


def _rule_too_short(ctx: dict) -> Optional[dict]:
    n_forecast = ctx["n_forecast"]
    if n_forecast is None or n_forecast <= 0 or n_forecast >= MIN_HORIZON:
        return None
    detail = (
        "Hay "
        + _plural(n_forecast, "período de pronóstico", "períodos de pronóstico")
        + ". Para leer estabilidad y temporada hacen falta al menos 6."
    )
    return _finding(
        "too_short",
        "warning",
        "El horizonte es demasiado corto",
        detail,
        "Extender el pronóstico a 6 períodos o más.",
        "review",
    )


def _rule_intermittent_smooth(ctx: dict) -> Optional[dict]:
    if ctx["intermittent"] is not True:
        return None
    zero_pct = ctx["zero_forecast_pct"]
    cv = ctx["cv_forecast"]
    if zero_pct is None or cv is None:
        return None
    if zero_pct >= ZERO_FORECAST_SMOOTH or cv >= CV_SMOOTH:
        return None
    detail = (
        "La demanda es "
        + _class_name(ctx)
        + ", pero el pronóstico casi no tiene ceros ("
        + _fmt_pct(zero_pct)
        + ") y se mueve poco (CV "
        + _fmt_num(cv, 2)
        + "; el CV es el desvío dividido por el promedio, y cerca de 0 es casi constante)."
    )
    return _finding(
        "intermittent_with_smooth_forecast",
        "warning",
        "Pronóstico suave para demanda intermitente",
        detail,
        "La demanda intermitente mezcla ceros y picos. Un promedio suave tapa ese patrón: dejar ceros en el horizonte o separar la chance de pedido del tamaño del pedido.",
        "review",
    )


def _rule_missing_actuals(ctx: dict) -> Optional[dict]:
    n_actual = ctx["n_actual"]
    if n_actual is None or n_actual != 0:
        return None
    return _finding(
        "missing_actuals",
        "warning",
        "No hay demanda histórica",
        "No hay valores reales cargados (0 períodos), así que no se puede medir si el pronóstico acierta.",
        "Cargar el histórico de demanda antes de aprobar el pronóstico.",
        "review",
    )


def _rule_high_zero_actuals(ctx: dict) -> Optional[dict]:
    pct = ctx["zero_actual_pct"]
    n_actual = ctx["n_actual"]
    if pct is None or n_actual is None:
        return None
    if n_actual < MIN_ZERO_ACTUAL_N or pct < ZERO_ACTUAL_HIGH:
        return None
    n_zero = ctx["n_zero_actual"]
    if n_zero is None:
        n_zero = pct * n_actual
    # Info solo cuando la intermitencia ya explica los ceros. Lumpy también
    # trae muchos ceros; una clase suave con esta proporción sí se revisa.
    info = ctx["demand_class"] == "intermittent" or (
        ctx["demand_class"] in (None, "lumpy") and ctx["intermittent"] is True
    )
    detail = (
        _fmt_count(n_zero)
        + " de "
        + _fmt_count(n_actual)
        + " períodos históricos están en cero ("
        + _fmt_pct(pct)
        + "). "
        + _class_phrase(ctx).capitalize()
        + "."
    )
    if info:
        return _finding(
            "high_zero_actuals",
            "info",
            "Hay muchos ceros en la demanda",
            detail,
            "En una demanda intermitente es habitual. Conviene medir el acierto con error absoluto y no tratar esos ceros como un error de carga.",
            "keep",
        )
    return _finding(
        "high_zero_actuals",
        "warning",
        "Hay muchos ceros en la demanda",
        detail,
        "Revisar si esos ceros son reales o períodos que faltó cargar. Si son reales, tratar la serie como intermitente.",
        "review",
    )


def _rule_overforecast_share(ctx: dict) -> Optional[dict]:
    pct = ctx["over_forecast_pct"]
    n = ctx["n"]
    if pct is None or n is None or n < MIN_HORIZON or pct < OVER_FORECAST:
        return None
    n_over = ctx["n_over"]
    if n_over is None:
        n_over = pct * n
    detail = (
        "En "
        + _fmt_count(n_over)
        + " de "
        + _fmt_count(n)
        + " períodos ("
        + _fmt_pct(pct)
        + ") el pronóstico quedó por encima de la demanda."
    )
    return _finding(
        "overforecast_share",
        "warning",
        "El pronóstico se pasa en la mayoría de los períodos",
        detail,
        "Bajar el nivel: está por encima de la demanda de forma reiterada, no en un período aislado.",
        "review",
    )


def _rule_tracking_signal(ctx: dict) -> Optional[dict]:
    signal = ctx["tracking_signal"]
    if signal is None or abs(signal) < TRACKING:
        return None
    detail = (
        "La señal de rastreo es "
        + _fmt_num(signal, 2)
        + ". Es la suma del error dividida por el error absoluto medio: "
        "desde 4, para arriba o para abajo, el sesgo ya no es ruido de un período."
    )
    return _finding(
        "tracking_signal_high",
        "warning",
        "El error se viene acumulando",
        detail,
        "Revisar los períodos recientes y corregir el nivel: el error se está juntando siempre del mismo lado.",
        "review",
    )


def _rule_beats_naive(ctx: dict) -> Optional[dict]:
    fva = ctx["fva_vs_naive"]
    if fva is None or fva <= FVA_BEAT:
        return None
    detail = (
        "El valor agregado contra el método ingenuo es "
        + _fmt_signed_pct(fva * 100.0)
        + ". El pronóstico erra menos que repetir la demanda reciente (el umbral para destacarlo es 10%)."
    )
    return _finding(
        "beats_naive",
        "info",
        "Le gana a repetir la historia",
        detail,
        "Se puede usar como base. Igual mirar el sesgo y el nivel antes de cerrar el plan.",
        "keep",
    )


def _rule_stable_smooth(ctx: dict) -> Optional[dict]:
    if ctx["demand_class"] != "smooth":
        return None
    wape = ctx["wape"]
    if wape is None or wape >= 0.2:
        return None
    detail = (
        "La demanda es suave y el WAPE es "
        + _fmt_pct(wape)
        + ", por debajo del 20%."
    )
    return _finding(
        "stable_smooth",
        "info",
        "Buen ajuste en una demanda suave",
        detail,
        "El ajuste alcanza para planificar esta serie. Conviene seguir el sesgo en los próximos cierres.",
        "keep",
    )


_RULES = (
    _rule_no_forecast_values,
    _rule_mostly_negative,
    _rule_no_variation_and_no_history,
    _rule_absurd_level,
    _rule_some_negative,
    _rule_duplicates_remain,
    _rule_gap,
    _rule_outlier_spikes,
    _rule_explosion,
    _rule_collapse,
    _rule_all_zero_forecast,
    _rule_high_wape,
    _rule_strong_bias,
    _rule_loses_to_naive,
    _rule_flat_forecast,
    _rule_ignores_seasonality,
    _rule_too_short,
    _rule_intermittent_smooth,
    _rule_missing_actuals,
    _rule_high_zero_actuals,
    _rule_overforecast_share,
    _rule_tracking_signal,
    _rule_beats_naive,
    _rule_stable_smooth,
)
_RULE_INDEX = {
    "no_forecast_values": 0,
    "mostly_negative": 1,
    "no_variation_and_no_history": 2,
    "absurd_level": 3,
    "some_negative": 4,
    "duplicates_remain": 5,
    "gap": 6,
    "outlier_spikes": 7,
    "explosion": 8,
    "collapse": 9,
    "all_zero_forecast": 10,
    "high_wape": 11,
    "strong_bias": 12,
    "loses_to_naive": 13,
    "flat_forecast": 14,
    "ignores_seasonality": 15,
    "too_short": 16,
    "intermittent_with_smooth_forecast": 17,
    "missing_actuals": 18,
    "high_zero_actuals": 19,
    "overforecast_share": 20,
    "tracking_signal_high": 21,
    "beats_naive": 22,
    "stable_smooth": 23,
}


def _finding(rule_id: str, severity: str, title: str, detail: str, suggestion: str, action: str) -> dict:
    return {
        "id": rule_id,
        "severity": severity,
        "title": title,
        "detail": detail,
        "suggestion": suggestion,
        "action": action,
    }


def _class_name(ctx: dict) -> str:
    kind = ctx.get("demand_class")
    if kind in _CLASS_ES:
        return _CLASS_ES[kind]
    raw = ctx.get("demand_class_raw")
    if raw:
        return str(raw)
    return "sin clasificar"


def _class_phrase(ctx: dict) -> str:
    if ctx.get("demand_class") is None and not ctx.get("demand_class_raw"):
        return "la clase de demanda no está informada"
    return "la demanda es " + _class_name(ctx)


# ---------------------------------------------------------------------------
# Contexto
# ---------------------------------------------------------------------------


def _build_context(df, frequency, profile, metrics) -> dict:
    profile = profile if isinstance(profile, Mapping) else {}
    metrics = metrics if isinstance(metrics, Mapping) else {}
    sources = (metrics, profile)
    profile_first = (profile, metrics)

    frame, actual_seen, forecast_seen = _canonicalize(df)
    period_freq = _period_freq(frequency if frequency is not None else _lookup(profile_first, ("frequency", "freq")))
    dates = frame["date"] if frame is not None else None
    actual = frame["actual"].to_numpy(dtype=float) if frame is not None else np.array([], dtype=float)
    forecast = frame["forecast"].to_numpy(dtype=float) if frame is not None else np.array([], dtype=float)

    finite_forecast = forecast[np.isfinite(forecast)] if forecast.size else np.array([], dtype=float)
    finite_actual = actual[np.isfinite(actual)] if actual.size else np.array([], dtype=float)
    paired = (
        np.isfinite(forecast) & np.isfinite(actual)
        if forecast.size and actual.size
        else np.array([], dtype=bool)
    )
    future = (
        np.isfinite(forecast) & ~np.isfinite(actual)
        if forecast.size and actual.size
        else np.array([], dtype=bool)
    )

    computed_n_forecast = int(finite_forecast.size) if forecast_seen else None
    computed_n_actual = int(finite_actual.size) if actual_seen else None
    computed_n_future = int(future.sum()) if forecast_seen and actual_seen else (
        int(finite_forecast.size) if forecast_seen and not actual_seen else None
    )
    computed_n_paired = int(paired.sum()) if forecast_seen and actual_seen else None

    def metric_count(names, computed):
        value = _as_float(_lookup(sources, names))
        if value is not None:
            return value
        return None if computed is None else float(computed)

    n_forecast = metric_count(("n_forecast", "n_forecasts"), computed_n_forecast)
    n_actual = metric_count(("n_actual", "n_actuals", "n_history"), computed_n_actual)
    n_future = metric_count(("n_future", "n_future_forecast", "future_periods"), computed_n_future)
    n_paired = metric_count(("n", "n_overlap", "n_points", "n_paired", "n_eval"), computed_n_paired)

    # Sin columna y sin métrica: no hay valores utilizables. Si hay métricas de
    # accuracy pero el frame no vino, el conteo queda desconocido (None).
    implied_accuracy = _lookup(sources, ("wape", "bias_pct", "fva_vs_naive", "mape")) is not None
    if n_forecast is None and not forecast_seen and not implied_accuracy:
        n_forecast = 0.0
    if n_actual is None and forecast_seen and not actual_seen and not implied_accuracy:
        n_actual = 0.0

    negative_mask_count = int(np.sum(finite_forecast < -ZERO_EPS)) if finite_forecast.size else 0
    negative_pct = _as_float(_lookup(sources, ("negative_forecast_pct",)))
    n_negative = _as_float(_lookup(sources, ("n_negative_forecast", "n_negative")))
    if negative_pct is None and computed_n_forecast:
        negative_pct = negative_mask_count / float(computed_n_forecast)
        if n_negative is None:
            n_negative = float(negative_mask_count)
    elif negative_pct is not None and n_negative is None and n_forecast:
        n_negative = negative_pct * n_forecast

    zero_forecast_pct = _as_float(_lookup(sources, ("zero_forecast_pct",)))
    if zero_forecast_pct is None and computed_n_forecast:
        zero_forecast_pct = float(np.mean(np.abs(finite_forecast) <= ZERO_EPS))

    zero_actual_pct = _as_float(_lookup(profile_first, ("zero_actual_pct", "zero_demand_pct")))
    n_zero_actual = None
    if finite_actual.size and actual_seen:
        n_zero_actual = float(np.sum(np.abs(finite_actual) <= ZERO_EPS))
        if zero_actual_pct is None and computed_n_actual:
            zero_actual_pct = n_zero_actual / computed_n_actual
    elif zero_actual_pct is not None and n_actual:
        n_zero_actual = zero_actual_pct * n_actual

    unique = _as_float(_lookup(sources, ("unique_forecast_values", "n_unique_forecast")))
    flat_value = None
    if finite_forecast.size:
        rounded = np.round(finite_forecast.astype(float), 8)
        uniq = np.unique(rounded)
        if unique is None:
            unique = float(uniq.size)
        if uniq.size == 1:
            flat_value = float(uniq[0])
    forecast_min = float(np.min(finite_forecast)) if finite_forecast.size else None

    flatness = _as_float(_lookup(sources, ("flatness", "forecast_flatness")))
    if flatness is None and finite_forecast.size:
        rounded = np.round(finite_forecast.astype(float), 6)
        _, counts = np.unique(rounded, return_counts=True)
        flatness = float(counts.max() / rounded.size)

    cv_forecast = _as_float(_lookup(sources, ("cv_forecast", "forecast_cv")))
    if cv_forecast is None and finite_forecast.size >= 2:
        mean_f = float(np.mean(finite_forecast))
        if abs(mean_f) > ZERO_EPS:
            cv_forecast = float(np.std(finite_forecast, ddof=0) / abs(mean_f))

    mean_actual = _as_float(_lookup(sources, ("mean_actual", "actual_mean")))
    if mean_actual is None and finite_actual.size:
        mean_actual = float(np.mean(finite_actual))
    mean_future = _as_float(_lookup(sources, ("mean_future", "future_mean", "mean_forecast_future")))
    future_values = forecast[future] if future.size else np.array([], dtype=float)
    if mean_future is None and future_values.size:
        mean_future = float(np.mean(future_values))

    history_ratio = _as_float(_lookup(sources, ("history_ratio", "forecast_to_history_ratio", "level_ratio")))
    if history_ratio is None and mean_actual is not None and mean_actual > 0 and mean_future is not None:
        history_ratio = mean_future / mean_actual

    wape = _as_float(_lookup(sources, ("wape",)))
    bias_pct = _as_float(_lookup(sources, ("bias_pct", "bias_percent")))
    if paired.size and int(paired.sum()) > 0:
        actual_p = actual[paired]
        forecast_p = forecast[paired]
        denom = float(np.sum(np.abs(actual_p)))
        signed_denom = float(np.sum(actual_p))
        if wape is None and denom > 0:
            wape = float(np.sum(np.abs(forecast_p - actual_p)) / denom)
        if bias_pct is None and signed_denom != 0:
            bias_pct = float(100.0 * np.sum(forecast_p - actual_p) / signed_denom)

    over_pct = _as_float(_lookup(sources, ("over_forecast_pct", "overforecast_pct")))
    n_over = _as_float(_lookup(sources, ("n_over_forecast",)))
    if over_pct is None and paired.size and int(paired.sum()) > 0:
        n_over = float(np.sum(forecast[paired] > actual[paired] + ZERO_EPS))
        over_pct = n_over / float(paired.sum())
    elif over_pct is not None and n_over is None and n_paired:
        n_over = over_pct * n_paired

    tracking = _as_float(_lookup(sources, ("tracking_signal",)))
    if tracking is None and paired.size and int(paired.sum()) >= 2:
        error = forecast[paired] - actual[paired]
        mae = float(np.mean(np.abs(error)))
        if mae > 0:
            tracking = float(np.sum(error) / mae)
        else:
            tracking = 0.0

    label = _lookup(profile_first, ("demand_class", "demand_type", "series_class", "demand_pattern"))
    demand_class = _normalize_class(label) if label is not None else None
    intermittent = _demand_is_intermittent(metrics, profile)

    gaps, gap_expected, gap_observed = _resolve_gaps(dates, period_freq, sources)
    duplicate_extra, duplicate_dates, duplicate_examples = _resolve_duplicates(dates, period_freq)

    ordered_forecast, ordered_dates, ordered_actual = _order_series(dates, forecast, actual)
    spikes = _spike_points(ordered_forecast, ordered_dates)
    explosion = _explosion_info(ordered_forecast, ordered_dates)
    collapse = _collapse_info(ordered_forecast, ordered_dates, ordered_actual)

    all_zero = False
    if mean_actual is not None and mean_actual > 0:
        if finite_forecast.size:
            all_zero = bool(np.all(np.abs(finite_forecast) <= ZERO_EPS))
        elif (
            zero_forecast_pct is not None
            and zero_forecast_pct >= 1.0
            and n_forecast is not None
            and n_forecast > 0
            and (negative_pct is None or negative_pct <= 0)
        ):
            all_zero = True

    return {
        "n_forecast": n_forecast,
        "n_actual": n_actual,
        "n_future": n_future,
        "n": n_paired,
        "negative_forecast_pct": negative_pct,
        "n_negative": n_negative,
        "forecast_min": forecast_min,
        "unique_forecast_values": unique,
        "flat_value": flat_value,
        "history_ratio": history_ratio,
        "mean_actual": mean_actual,
        "mean_future": mean_future,
        "missing_date_gaps": gaps,
        "gap_expected": gap_expected,
        "gap_observed": gap_observed,
        "duplicate_extra": duplicate_extra,
        "duplicate_dates": duplicate_dates,
        "duplicate_examples": duplicate_examples,
        "spikes": spikes,
        "explosion": explosion,
        "collapse": collapse,
        "all_zero_forecast": all_zero,
        "wape": wape,
        "bias_pct": bias_pct,
        "fva_vs_naive": _as_float(_lookup(sources, ("fva_vs_naive", "fva"))),
        "flatness": flatness,
        "seasonality_strength": _as_float(
            _lookup(profile_first, ("seasonality_strength", "seasonal_strength"))
        ),
        "zero_forecast_pct": zero_forecast_pct,
        "cv_forecast": cv_forecast,
        "cv_actual": _as_float(_lookup(profile_first, ("cv_actual", "actual_cv"))),
        "demand_class": demand_class,
        "demand_class_raw": None if label is None else str(label),
        "intermittent": intermittent,
        "over_forecast_pct": over_pct,
        "n_over": n_over,
        "tracking_signal": tracking,
        "zero_actual_pct": zero_actual_pct,
        "n_zero_actual": n_zero_actual,
        "freq_label": _PERIOD_LABEL.get(period_freq or "", ""),
    }


def _canonicalize(df):
    """Devuelve (frame con date/actual/forecast, actual_visto, forecast_visto)."""
    if df is None:
        return None, False, False
    if not isinstance(df, pd.DataFrame):
        try:
            df = pd.DataFrame(df)
        except (ValueError, TypeError):
            return None, False, False
    if df.columns.duplicated().any():
        df = df.loc[:, ~df.columns.duplicated()].copy()
    else:
        df = df.copy()

    renamed = {column: _fold(column) for column in df.columns}
    folded_to_original = {}
    for original, folded in renamed.items():
        folded_to_original.setdefault(folded, original)

    kind_col = _pick(folded_to_original, _KIND_ALIASES)
    value_col = _pick(folded_to_original, _VALUE_ALIASES)
    date_col = _pick(folded_to_original, _DATE_ALIASES)
    if kind_col is not None and value_col is not None and date_col is not None:
        df = _pivot_long(df, date_col, value_col, kind_col)
        renamed = {column: _fold(column) for column in df.columns}
        folded_to_original = {}
        for original, folded in renamed.items():
            folded_to_original.setdefault(folded, original)

    date_col = _pick(folded_to_original, _DATE_ALIASES)
    actual_col = _pick(folded_to_original, _ACTUAL_ALIASES)
    forecast_col = _pick(folded_to_original, _FORECAST_ALIASES)
    if forecast_col is not None and actual_col == forecast_col:
        actual_col = None

    if date_col is None and isinstance(df.index, pd.DatetimeIndex):
        df = df.reset_index()
        date_col = df.columns[0]
    elif date_col is None and isinstance(df.index, pd.PeriodIndex):
        df = df.copy()
        df["_date"] = df.index.to_timestamp()
        date_col = "_date"

    if date_col is None or actual_col is None or forecast_col is None:
        date_col, actual_col, forecast_col = _positional_fill(df, date_col, actual_col, forecast_col)

    actual_seen = actual_col is not None
    forecast_seen = forecast_col is not None
    n_rows = len(df)
    frame = pd.DataFrame(
        {
            "date": _as_dates(df[date_col]) if date_col is not None else pd.Series([pd.NaT] * n_rows),
            "actual": _as_numbers(df[actual_col]) if actual_col is not None else pd.Series(np.nan, index=df.index, dtype=float),
            "forecast": _as_numbers(df[forecast_col]) if forecast_col is not None else pd.Series(np.nan, index=df.index, dtype=float),
        }
    )
    if not actual_seen and not forecast_seen and n_rows == 0:
        return frame, False, False
    return frame, actual_seen, forecast_seen


def _pivot_long(df, date_col, value_col, kind_col) -> pd.DataFrame:
    work = df[[date_col, value_col, kind_col]].copy()
    kinds = work[kind_col].map(_fold)
    actual_tokens = set(_ACTUAL_ALIASES) | {"actual", "historia", "hist"}
    forecast_tokens = set(_FORECAST_ALIASES) | {"forecast", "futuro"}
    rows = []
    for date, group in work.groupby(date_col, dropna=False):
        actual = np.nan
        forecast = np.nan
        for kind, value in zip(kinds.loc[group.index], group[value_col]):
            number = _as_float(value)
            if number is None and value is not None:
                try:
                    number = float(pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0])
                except (TypeError, ValueError):
                    number = None
            if kind in forecast_tokens or "pronost" in str(kind) or "forecast" in str(kind):
                forecast = np.nan if number is None else number
            elif kind in actual_tokens or "demand" in str(kind) or "actual" in str(kind):
                actual = np.nan if number is None else number
        rows.append({"date": date, "actual": actual, "forecast": forecast})
    return pd.DataFrame(rows)


def _positional_fill(df, date_col, actual_col, forecast_col):
    used = {col for col in (date_col, actual_col, forecast_col) if col is not None}
    remaining = [col for col in df.columns if col not in used]
    if date_col is None:
        for col in remaining:
            if _looks_like_dates(df[col]):
                date_col = col
                remaining.remove(col)
                break
    numeric = [col for col in remaining if _looks_numeric(df[col])]
    if forecast_col is None and actual_col is None and len(numeric) >= 2:
        actual_col = numeric[0]
        forecast_col = numeric[1]
    elif forecast_col is None and actual_col is None and len(numeric) == 1:
        forecast_col = numeric[0]
    elif forecast_col is None and numeric:
        forecast_col = numeric[0]
    elif actual_col is None and numeric:
        actual_col = numeric[0]
    return date_col, actual_col, forecast_col


def _looks_like_dates(series: pd.Series) -> bool:
    if isinstance(series.dtype, (pd.DatetimeTZDtype, pd.PeriodDtype)) or pd.api.types.is_datetime64_any_dtype(series):
        return True
    sample = series.dropna().head(8)
    if sample.empty or pd.api.types.is_numeric_dtype(sample):
        return False
    parsed = pd.to_datetime(sample, errors="coerce")
    return int(parsed.notna().sum()) >= max(1, int(0.6 * len(sample)))


def _looks_numeric(series: pd.Series) -> bool:
    if pd.api.types.is_numeric_dtype(series):
        return True
    sample = series.dropna().head(8)
    if sample.empty:
        return False
    parsed = pd.to_numeric(sample, errors="coerce")
    return int(np.isfinite(parsed.to_numpy(dtype=float)).sum()) >= max(1, int(0.6 * len(sample)))


def _as_dates(series: pd.Series) -> pd.Series:
    if isinstance(series.dtype, pd.PeriodDtype):
        values = series.dt.to_timestamp()
    else:
        values = pd.to_datetime(series, errors="coerce")
    if getattr(values.dt, "tz", None) is not None:
        values = values.dt.tz_localize(None)
    return values


def _as_numbers(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce").astype(float)


def _order_series(dates, forecast, actual):
    if dates is None or not forecast.size:
        empty_dates = np.array([], dtype=object)
        return forecast, empty_dates, actual
    nat = dates.isna().to_numpy()
    valid_idx = np.flatnonzero(~nat)
    nat_idx = np.flatnonzero(nat)
    if valid_idx.size:
        ordered_valid = valid_idx[np.argsort(dates.to_numpy()[valid_idx], kind="mergesort")]
        order = np.concatenate([ordered_valid, nat_idx])
    else:
        order = np.arange(forecast.size)
    return forecast[order], dates.to_numpy()[order], actual[order]


def _neighbor_supports(values: np.ndarray, index: int, center: float) -> bool:
    """Un pico de temporada se apoya en el mes de al lado. Un error de carga, no."""
    dev = float(values[index] - center)
    if abs(dev) <= ZERO_EPS:
        return True
    for neighbor in (index - 1, index + 1):
        if neighbor < 0 or neighbor >= values.size or not np.isfinite(values[neighbor]):
            continue
        other = float(values[neighbor] - center)
        if dev * other > 0.0 and abs(other) >= 0.4 * abs(dev):
            return True
    return False


def _spike_points(forecast: np.ndarray, dates: np.ndarray) -> list[dict]:
    mask = np.isfinite(forecast)
    values = forecast[mask]
    if values.size < MIN_Z_POINTS:
        return []
    zscores = _modified_z(values)
    if zscores is None:
        return []
    center = float(np.median(values))
    point_dates = dates[mask] if dates.size == forecast.size else np.array([None] * values.size)
    spikes = []
    for index, (value, score, date) in enumerate(zip(values, zscores, point_dates)):
        extreme = (np.isfinite(score) and abs(float(score)) > Z_SPIKE) or (
            not np.isfinite(score) and not np.isnan(score)
        )
        if not extreme:
            continue
        # Con MAD en cero, cualquier valor distinto de la mediana da z infinito.
        # Eso es una temporada o un cambio de nivel, no un pico, si el vecino lo acompaña.
        if _neighbor_supports(values, index, center):
            continue
        deviation = abs(float(value) - center)
        floor = max(1.0, 0.5 * abs(center))
        if deviation < floor:
            continue
        spikes.append(
            {
                "value": float(value),
                "z": float(score) if np.isfinite(score) else float("inf"),
                "date": None if _is_nat(date) else _fmt_date(date),
            }
        )
    return spikes


def _modified_z(values: np.ndarray) -> Optional[np.ndarray]:
    if values.size < MIN_Z_POINTS:
        return None
    center = float(np.median(values))
    deviation = np.abs(values - center)
    mad = float(np.median(deviation))
    if mad <= ZERO_EPS:
        scores = np.zeros(values.size, dtype=float)
        scores[deviation > ZERO_EPS] = np.inf
        return scores
    return 0.6745 * (values - center) / mad


def _in_time_mask(forecast: np.ndarray, dates: np.ndarray) -> np.ndarray:
    """Puntos con número. Si hay fechas, descarta las filas sin fecha para no tomarlas como el último período."""
    finite = np.isfinite(forecast) if forecast.size else np.array([], dtype=bool)
    if forecast.size and dates.size == forecast.size:
        dated = ~pd.isna(pd.Series(dates)).to_numpy()
        if np.any(dated & finite):
            return dated & finite
    return finite


def _explosion_info(forecast: np.ndarray, dates: np.ndarray) -> Optional[dict]:
    mask = _in_time_mask(forecast, dates)
    values = forecast[mask]
    if values.size < 2:
        return None
    point_dates = dates[mask] if dates.size == forecast.size else np.array([None] * values.size)
    last = float(values[-1])
    prev = float(values[-2])
    prior = values[:-1]
    median = float(np.median(prior))
    ratio_hit = False
    ratio = None
    if prior.size + 1 >= MIN_EXPLOSION_N and median > ZERO_EPS:
        ratio = last / median
        ratio_hit = ratio > EXPLOSION_RATIO
    growth = None
    growth_hit = False
    if prev > ZERO_EPS:
        growth = (last - prev) / prev
        growth_hit = growth > EXPLOSION_GROWTH
    if not ratio_hit and not growth_hit:
        return None
    date = point_dates[-1]
    return {
        "last": last,
        "prev": prev,
        "median": median,
        "prior_n": int(prior.size),
        "ratio": ratio,
        "ratio_hit": ratio_hit,
        "growth": growth,
        "growth_hit": growth_hit,
        "date": None if _is_nat(date) else _fmt_date(date),
    }


def _collapse_info(forecast, dates, actual) -> Optional[dict]:
    if not forecast.size:
        return None
    finite_idx = np.flatnonzero(_in_time_mask(forecast, dates))
    if finite_idx.size < MIN_COLLAPSE_PRIOR + 1:
        return None
    last_i = int(finite_idx[-1])
    prior = forecast[finite_idx[:-1]]
    prior_positive = prior[prior > ZERO_EPS]
    if prior_positive.size < MIN_COLLAPSE_PRIOR:
        return None
    median_forecast = float(np.median(prior_positive))
    if median_forecast <= ZERO_EPS:
        return None
    last = float(forecast[last_i])
    ratio = last / median_forecast
    if ratio >= COLLAPSE_RATIO:
        return None
    if actual.size != forecast.size:
        return None
    actual_idx = np.flatnonzero(np.isfinite(actual))
    if actual_idx.size < MIN_COLLAPSE_PRIOR + 1:
        return None
    last_actual_i = int(actual_idx[-1])
    prior_actual = actual[actual_idx[:-1]]
    prior_actual_positive = prior_actual[prior_actual > ZERO_EPS]
    if prior_actual_positive.size < MIN_COLLAPSE_PRIOR:
        return None
    median_actual = float(np.median(prior_actual_positive))
    last_actual = float(actual[last_actual_i])
    if median_actual <= ZERO_EPS:
        return None
    # "Igual de baja" = la demanda también cayó bajo el 15 % de su mediana.
    if last_actual < COLLAPSE_RATIO * median_actual:
        return None
    date = dates[last_i] if dates.size == forecast.size else None
    return {
        "last": last,
        "ratio": ratio,
        "median_forecast": median_forecast,
        "last_actual": last_actual,
        "median_actual": median_actual,
        "date": None if _is_nat(date) else _fmt_date(date),
    }


def _resolve_gaps(dates, period_freq, sources):
    metric = _as_float(_lookup(sources, ("missing_date_gaps", "n_missing_dates", "gap_count")))
    computed, expected, observed = _count_gaps(dates, period_freq)
    if metric is not None:
        return metric, expected, observed
    return computed, expected, observed


def _count_gaps(dates, period_freq):
    if dates is None or period_freq is None:
        return None, None, None
    clean = dates.dropna()
    if clean.size < 2:
        return None, None, None
    try:
        periods = clean.dt.to_period(period_freq)
        observed = periods.unique()
        full = pd.period_range(observed.min(), observed.max(), freq=observed.freq)
    except (ValueError, TypeError, AttributeError):
        return None, None, None
    expected = int(len(full))
    seen = int(len(observed))
    return float(max(0, expected - seen)), float(expected), float(seen)


def _resolve_duplicates(dates, period_freq):
    if dates is None:
        return None, None, []
    clean = dates.dropna()
    if clean.empty:
        return None, None, []
    try:
        if period_freq:
            keys = pd.Series(clean.dt.to_period(period_freq).astype(str).to_numpy(), index=clean.index)
        else:
            keys = pd.Series(clean.dt.strftime("%Y-%m-%d %H:%M:%S").to_numpy(), index=clean.index)
    except (ValueError, TypeError, AttributeError, OverflowError):
        keys = pd.Series(clean.astype(str).to_numpy(), index=clean.index)
    counts = keys.value_counts()
    duplicated = counts[counts > 1]
    if duplicated.empty:
        return 0, 0, []
    extra = int(duplicated.sum() - duplicated.size)
    examples = []
    seen = set()
    for date, key in zip(clean, keys):
        if key not in duplicated.index or key in seen:
            continue
        examples.append(_fmt_date(date))
        seen.add(key)
        if len(examples) == 3:
            break
    return extra, int(duplicated.size), examples


def _period_freq(frequency) -> Optional[str]:
    if frequency is None:
        return None
    raw = str(frequency).strip()
    if not raw or raw.lower() in {"none", "nan"}:
        return None
    mapped = _FREQ_TO_PERIOD.get(_fold(raw))
    if mapped:
        return mapped
    token = raw.upper()
    base = token.split("-")[0]
    base_map = {
        "D": "D",
        "W": "W",
        "M": "M",
        "MS": "M",
        "ME": "M",
        "Q": "Q",
        "QS": "Q",
        "QE": "Q",
        "Y": "Y",
        "YS": "Y",
        "YE": "Y",
        "A": "Y",
        "H": "h",
        "B": "B",
    }
    if base in base_map:
        try:
            pd.period_range("2020-01-01", periods=2, freq=token if base == "W" else base_map[base])
        except (ValueError, TypeError):
            return base_map[base]
        return base_map[base]
    return None


# ---------------------------------------------------------------------------
# Utilidades
# ---------------------------------------------------------------------------


def _lookup(sources: Sequence[Mapping], names: Sequence[str]):
    for source in sources:
        if not isinstance(source, Mapping):
            continue
        for name in names:
            if name in source and not _missing(source[name]):
                return source[name]
        for bucket in _NESTED_BUCKETS:
            nested = source.get(bucket) if hasattr(source, "get") else None
            if not isinstance(nested, Mapping):
                continue
            for name in names:
                if len(name) <= 2:
                    continue
                if name in nested and not _missing(nested[name]):
                    return nested[name]
    return None


def _missing(value) -> bool:
    if value is None:
        return True
    if isinstance(value, (bool, np.bool_)):
        return False
    if isinstance(value, (str, bytes)):
        return str(value).strip() == ""
    if isinstance(value, (int, np.integer)):
        return False
    if isinstance(value, (float, np.floating)):
        return not np.isfinite(float(value))
    try:
        na = pd.isna(value)
    except (TypeError, ValueError):
        return False
    if isinstance(na, (bool, np.bool_)):
        return bool(na)
    return False


def _as_float(value) -> Optional[float]:
    if _missing(value):
        return None
    if isinstance(value, (bool, np.bool_)):
        return float(value)
    if isinstance(value, str):
        text = value.strip().replace(" ", "")
        if "," in text and "." not in text:
            text = text.replace(",", ".")
        value = text
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not np.isfinite(number):
        return None
    return number


def _fold(value) -> str:
    text = str(value).strip().lower().replace(" ", "_").replace("-", "_")
    for source, target in (
        ("á", "a"),
        ("é", "e"),
        ("í", "i"),
        ("ó", "o"),
        ("ú", "u"),
        ("ü", "u"),
        ("ñ", "n"),
    ):
        text = text.replace(source, target)
    return text


def _pick(folded_to_original: dict, aliases: Sequence[str]) -> Optional[str]:
    for alias in aliases:
        if alias in folded_to_original:
            return folded_to_original[alias]
    return None


def _normalize_class(value) -> Optional[str]:
    if value is None or _missing(value):
        return None
    folded = _fold(value)
    aliases = {
        "smooth": "smooth",
        "suave": "smooth",
        "stable": "smooth",
        "erratic": "erratic",
        "erratica": "erratic",
        "erratico": "erratic",
        "intermittent": "intermittent",
        "intermitente": "intermittent",
        "lumpy": "lumpy",
        "abultada": "lumpy",
        "irregular": "lumpy",
    }
    if folded in aliases:
        return aliases[folded]
    if "intermit" in folded:
        return "intermittent"
    if "lumpy" in folded or "abult" in folded:
        return "lumpy"
    if "smooth" in folded or "suave" in folded:
        return "smooth"
    if "erratic" in folded or "erratic" in folded:
        return "erratic"
    return folded


def _fmt_num(value, digits: int = 1) -> str:
    number = float(value)
    if not np.isfinite(number):
        return "s/d"
    formatted = f"{number:,.{digits}f}"
    return formatted.replace(",", "⌀").replace(".", ",").replace("⌀", ".")


def _fmt_count(value) -> str:
    number = float(value)
    if abs(number - round(number)) < 1e-6:
        return _fmt_num(round(number), 0)
    return _fmt_num(number, 1)


def _fmt_pct(fraction, digits: int = 1) -> str:
    return _fmt_plain(float(fraction) * 100.0, digits) + "%"


def _fmt_signed_pct(percent_points, digits: int = 1) -> str:
    number = float(percent_points)
    text = _fmt_plain(abs(number), digits) + "%"
    if number > 0:
        return "+" + text
    if number < 0:
        return "-" + text
    return text


def _fmt_plain(value, digits: int) -> str:
    number = float(value)
    if not np.isfinite(number):
        return "s/d"
    return f"{abs(number):.{digits}f}".replace(".", ",")


def _fmt_date(value) -> str:
    try:
        stamp = pd.Timestamp(value)
    except (TypeError, ValueError):
        return str(value)
    if pd.isna(stamp):
        return "s/d"
    return stamp.strftime("%Y-%m-%d")


def _is_nat(value) -> bool:
    if value is None:
        return True
    try:
        return bool(pd.isna(value))
    except (TypeError, ValueError):
        return False


def _plural(n, one: str, many: str) -> str:
    count = int(round(float(n)))
    return _fmt_count(n) + " " + (one if count == 1 else many)


def _titles(findings: Sequence[Mapping]) -> list[str]:
    seen = []
    for finding in findings:
        title = str(finding.get("title") or finding.get("id") or "").strip()
        if title and title not in seen:
            seen.append(title)
    return seen


def _join(parts: Sequence[str]) -> str:
    items = [part for part in parts if part]
    if not items:
        return "hallazgos sin título"
    if len(items) == 1:
        return items[0]
    if len(items) == 2:
        return items[0] + " y " + items[1]
    return ", ".join(items[:-1]) + " y " + items[-1]
