"""Assemble a demand-forecast audit report from profile, rules, correction, and model advice.

The sibling modules live next to this file. Their functions are called with the
parameters they declare (frame, frequency, profile, metrics, findings, verdict,
and the usual column aliases). This module does not recompute those results.
"""

from __future__ import annotations

import csv
import inspect
import io
import math
import statistics
import warnings
from collections import Counter
from datetime import date, datetime, timezone
from decimal import Decimal

import numpy as np
import pandas as pd

try:
    from .metrics import accuracy_metrics, series_profile
except ImportError:
    from metrics import accuracy_metrics, series_profile

try:
    from .rules import diagnose, verdict
except ImportError:
    from rules import diagnose, verdict

try:
    from .correct import correct_product, corrections_table
except ImportError:
    from correct import correct_product, corrections_table

try:
    from .models import recommend_models
except ImportError:
    from models import recommend_models


_COLUMNS = (
    "product_id",
    "product_name",
    "category",
    "location",
    "date",
    "forecast",
    "actual",
    "model_name",
    "horizon",
)

_PREVIEW_LIMIT = 30
_SUGGESTION_LIMIT = 6
_WORST_LIMIT = 5

_PARAM_ALIASES = {
    "dataframe": ("frame",),
    "product_frame": ("frame",),
    "subframe": ("frame",),
    "grouped": ("frame",),
    "history": ("frame",),
    "series": ("frame",),
    "granularity": ("frequency",),
    "freq_code": ("frequency",),
    "cadence": ("frequency",),
    "series_profile": ("profile",),
    "prof": ("profile",),
    "accuracy": ("metrics",),
    "accuracy_metrics": ("metrics",),
    "diagnosis": ("findings",),
    "diagnoses": ("findings",),
    "issues": ("findings",),
    "flags": ("findings",),
    "problems": ("findings",),
    "predicted": ("forecast",),
    "prediction": ("forecast",),
    "predictions": ("forecast",),
    "y_pred": ("forecast",),
    "yhat": ("forecast",),
    "preds": ("forecast",),
    "y_true": ("actual",),
    "real": ("actual",),
    "reals": ("actual",),
    "observations": ("actual",),
    "timestamp": ("dates",),
    "timestamps": ("dates",),
    "fecha": ("dates",),
    "fechas": ("dates",),
    "ts": ("dates",),
    "corrected_df": ("corrected_frame",),
    "corrected_data": ("corrected_frame",),
    "out_frame": ("corrected_frame",),
    "df_with_corrected": ("corrected_frame",),
    "df_corrected": ("corrected_frame",),
    "with_corrected": ("corrected_frame",),
    "result": ("correction",),
    "correction_result": ("correction",),
    "output": ("correction",),
    "original": ("original_frame",),
    "source_frame": ("original_frame",),
    "raw_frame": ("original_frame",),
    "sku": ("product_id",),
    "branch": ("location",),
    "store": ("location",),
    "sucursal": ("location",),
    "decision_str": ("decision_label",),
    "verdict_label": ("decision_label",),
}

_DECISION_EXACT = {
    "aprobar": "aprobar",
    "aprobado": "aprobar",
    "approve": "aprobar",
    "approved": "aprobar",
    "accept": "aprobar",
    "pass": "aprobar",
    "ok": "aprobar",
    "corregir": "corregir",
    "corregido": "corregir",
    "correct": "corregir",
    "adjust": "corregir",
    "revise": "corregir",
    "fix": "corregir",
    "descartar": "descartar",
    "descartado": "descartar",
    "discard": "descartar",
    "reject": "descartar",
    "rejected": "descartar",
    "drop": "descartar",
}

_CLASS_KEYS = (
    "demand_class",
    "clase_demanda",
    "sb_class",
    "classification",
    "demand_pattern",
    "pattern",
    "adi_cv_class",
    "class_name",
    "class",
)

_METRIC_KEYS = {
    "wape": ("wape", "WAPE"),
    "bias_pct": ("bias_pct", "bias", "pct_bias", "bias_percent"),
    "mase": ("mase", "MASE"),
    "fva_vs_naive": ("fva_vs_naive", "fva", "fva_naive", "forecast_value_added"),
}

_SCORE_KEYS = ("score", "puntaje", "quality_score", "quality", "grade", "nota")
_SUGGESTION_KEYS = (
    "suggestion",
    "sugerencia",
    "recommendation",
    "advice",
    "fix",
    "how_to",
)
_MODEL_NAME_KEYS = ("alias", "model", "modelo", "name", "model_name")
_SUGGESTION_LIST_KEYS = ("suggestions", "sugerencias", "actions", "acciones")
_MODEL_KEYS = ("model", "modelo", "name", "model_name", "family", "method")
_WHY_KEYS = (
    "why",
    "reason",
    "rationale",
    "summary",
    "detail",
    "because",
    "porque",
    "justification",
    "note",
    "line",
)
_CORRECTED_COLUMNS = (
    "forecast_corrected",
    "corrected_forecast",
    "forecast_corregido",
)
_NOTE_COLUMNS = ("correction_note", "note", "nota", "reason")
_CSV_SUMMARY_HEADER = [
    "producto",
    "sucursal",
    "decision",
    "puntaje",
    "clase_demanda",
    "wape",
    "bias_pct",
    "mase",
    "fva_vs_naive",
    "modelo_sugerido",
    "acciones",
]
_CSV_LONG_HEADER = [
    "product_id",
    "location",
    "date",
    "forecast",
    "forecast_corrected",
    "actual",
    "correction_note",
]

__all__ = ["analyze_frame", "report_to_csv_rows", "corrected_long_csv"]


def analyze_frame(frame, frequency: str, source_name: str, warnings: list[str]) -> dict:
    """Audit every product-location series in ``frame``.

    ``frame`` has columns product_id, product_name, category, location, date,
    forecast, actual, model_name, horizon. Rows are grouped by product_id and
    location. The result is JSON-serializable: dates are ISO strings, and the
    payload has no NaN, numpy scalars, or dataframes.
    """
    source = "" if source_name is None else str(source_name)
    freq = "" if frequency is None else str(frequency)
    load_warnings = _as_warnings(warnings)
    original_rows = 0 if frame is None else int(len(frame))
    work = _prepare_frame(frame)
    products = []
    coverage = _actual_coverage(work)

    if original_rows == 0 or len(work) == 0:
        summary = {
            "products": 0,
            "rows": original_rows,
            "aprobar": 0,
            "corregir": 0,
            "descartar": 0,
            "avg_score": 0.0,
            "median_wape": None,
            "worst": [],
        }
        report = {
            "source_name": source,
            "frequency": freq,
            "load_warnings": load_warnings,
            "generated_at": _now_iso(),
            "summary": summary,
            "products": [],
            "portfolio_advice": _portfolio_advice(
                products=[],
                summary=summary,
                frequency=freq,
                source_name=source,
                warnings=load_warnings,
                with_actual=0,
                total_series=0,
            ),
        }
        return _jsonify(report)

    for product_id, location, group in _iter_groups(work):
        products.append(_product_report(group, freq, product_id, location))

    products.sort(key=_product_sort_key)
    scores = [score for score in (_score_of(p.get("verdict")) for p in products) if score is not None]
    wapes = [value for value in (_metric_value(p, "wape") for p in products) if value is not None]
    counts = Counter(_decision_of(p) for p in products)
    summary = {
        "products": len(products),
        "rows": original_rows,
        "aprobar": int(counts.get("aprobar", 0)),
        "corregir": int(counts.get("corregir", 0)),
        "descartar": int(counts.get("descartar", 0)),
        "avg_score": round(sum(scores) / len(scores), 6) if scores else 0.0,
        "median_wape": round(float(statistics.median(wapes)), 6) if wapes else None,
        "worst": [_worst_item(product) for product in products[:_WORST_LIMIT]],
    }
    report = {
        "source_name": source,
        "frequency": freq,
        "load_warnings": load_warnings,
        "generated_at": _now_iso(),
        "summary": summary,
        "products": products,
        "portfolio_advice": _portfolio_advice(
            products=products,
            summary=summary,
            frequency=freq,
            source_name=source,
            warnings=load_warnings,
            with_actual=coverage[0],
            total_series=coverage[1],
        ),
    }
    return _jsonify(report)


def report_to_csv_rows(report: dict) -> str:
    """One CSV row per product, Spanish headers, worst score first."""
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(_CSV_SUMMARY_HEADER)
    for product in report.get("products") or []:
        correction = product.get("correction") if isinstance(product.get("correction"), dict) else {}
        actions = correction.get("actions") if isinstance(correction, dict) else []
        if not isinstance(actions, list):
            actions = _as_str_list(actions)
        writer.writerow(
            [
                _csv_text(product.get("product_id")),
                _csv_text(product.get("location")),
                _decision_of(product),
                _format_number(_score_of(product.get("verdict"))),
                _demand_class(product.get("profile")),
                _format_number(_metric_value(product, "wape")),
                _format_number(_metric_value(product, "bias_pct")),
                _format_number(_metric_value(product, "mase")),
                _format_number(_metric_value(product, "fva_vs_naive")),
                _top_model_name(product.get("recommendations")),
                " | ".join(str(item) for item in actions if str(item).strip()),
            ]
        )
    return buffer.getvalue()


def corrected_long_csv(frame, frequency) -> str:
    """Re-run correction for each product-location and return a long CSV."""
    freq = "" if frequency is None else str(frequency)
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(_CSV_LONG_HEADER)
    work = _prepare_frame(frame)
    if len(work) == 0:
        return buffer.getvalue()
    for product_id, location, group in _iter_groups(work):
        corrected = _correct_group(group, freq, product_id, location)
        _write_long_rows(writer, product_id, location, group, corrected)
    return buffer.getvalue()


def _product_report(group: pd.DataFrame, frequency: str, product_id, location) -> dict:
    ctx = _base_context(group, frequency, product_id, location)
    profile = _call(series_profile, ctx)
    ctx["profile"] = profile
    metrics = _call(accuracy_metrics, ctx)
    ctx["metrics"] = metrics
    findings = _call(diagnose, ctx)
    ctx["findings"] = findings
    product_verdict = _call(verdict, ctx)
    ctx["verdict"] = product_verdict
    ctx["decision_label"] = _decision_from(product_verdict)
    raw_correction, corrected = _apply_correction(ctx, group)
    recommendations = _call(recommend_models, ctx)
    preview = _preview_rows(_call(corrections_table, _preview_context(ctx, group, corrected, raw_correction)))
    return {
        "product_id": _id_value(product_id),
        "product_name": _text_mode(group["product_name"]) if "product_name" in group.columns else "",
        "category": _text_mode(group["category"]) if "category" in group.columns else "",
        "location": _id_value(location),
        "model_name": _text_mode(group["model_name"]) if "model_name" in group.columns else "",
        "profile": _jsonify(profile),
        "metrics": _jsonify(metrics),
        "findings": _jsonify(findings),
        "verdict": _jsonify(product_verdict),
        "recommendations": _jsonify(recommendations),
        "correction": _correction_view(raw_correction, corrected),
        "corrections_preview": preview,
        "how_to_improve": _how_to_improve(findings, recommendations),
    }


def _correct_group(group: pd.DataFrame, frequency: str, product_id, location) -> pd.DataFrame:
    ctx = _base_context(group, frequency, product_id, location)
    if _accepts_any(correct_product, {"profile", "metrics", "findings", "verdict", "decision_label"}):
        profile = _call(series_profile, ctx)
        ctx["profile"] = profile
        metrics = _call(accuracy_metrics, ctx)
        ctx["metrics"] = metrics
    if _accepts_any(correct_product, {"findings", "verdict", "decision_label"}):
        ctx["findings"] = _call(diagnose, ctx)
    if _accepts_any(correct_product, {"verdict", "decision_label"}):
        product_verdict = _call(verdict, ctx)
        ctx["verdict"] = product_verdict
        ctx["decision_label"] = _decision_from(product_verdict)
    _raw, corrected = _apply_correction(ctx, group)
    return corrected


def _apply_correction(ctx: dict, group: pd.DataFrame) -> tuple[object, pd.DataFrame]:
    raw = _call(correct_product, ctx)
    return raw, _extract_corrected_frame(raw, group)


def _preview_context(ctx: dict, group: pd.DataFrame, corrected: pd.DataFrame, raw) -> dict:
    preview_ctx = dict(ctx)
    preview_ctx["original_frame"] = group
    preview_ctx["corrected_frame"] = corrected
    preview_ctx["corrected"] = corrected
    preview_ctx["frame"] = corrected
    preview_ctx["df"] = corrected
    preview_ctx["data"] = corrected
    preview_ctx["group"] = corrected
    if isinstance(raw, dict):
        preview_ctx["correction"] = raw
    else:
        preview_ctx["correction"] = {"frame": corrected}
    preview_ctx["limit"] = _PREVIEW_LIMIT
    preview_ctx["max_rows"] = _PREVIEW_LIMIT
    return preview_ctx


def _base_context(group: pd.DataFrame, frequency: str, product_id, location) -> dict:
    forecast = _column_series(group, "forecast")
    actual = _column_series(group, "actual")
    dates = _column_series(group, "date")
    ctx = {
        "frame": group,
        "df": group,
        "data": group,
        "group": group,
        "history": group,
        "frequency": frequency,
        "freq": frequency,
        "forecast": forecast,
        "forecasts": forecast,
        "actual": actual,
        "actuals": actual,
        "y": actual,
        "demand": actual,
        "dates": dates,
        "date": dates,
        "ds": dates,
        "product_id": _id_value(product_id),
        "location": _id_value(location),
        "product_name": _text_mode(group["product_name"]) if "product_name" in group.columns else "",
        "category": _text_mode(group["category"]) if "category" in group.columns else "",
        "model_name": _text_mode(group["model_name"]) if "model_name" in group.columns else "",
    }
    horizon = _mode_generic(group["horizon"]) if "horizon" in group.columns else None
    if horizon is not None:
        ctx["horizon"] = horizon
    return ctx


def _call(fn, available: dict):
    try:
        signature = inspect.signature(fn)
    except (TypeError, ValueError):
        args = []
        if "frame" in available:
            args.append(available["frame"])
        if "frequency" in available:
            args.append(available["frequency"])
        return fn(*args)

    positional = []
    keywords = {}
    blocked = False
    for name, param in signature.parameters.items():
        if param.kind is inspect.Parameter.VAR_POSITIONAL:
            blocked = True
            continue
        if param.kind is inspect.Parameter.VAR_KEYWORD:
            continue
        found, value = _lookup(name, available)
        if param.kind is inspect.Parameter.KEYWORD_ONLY:
            if found:
                keywords[name] = value
            elif param.default is inspect.Parameter.empty:
                raise TypeError(f"{getattr(fn, '__name__', fn)}() missing required argument '{name}'")
            continue
        if found and not blocked:
            positional.append(value)
            continue
        if found and blocked:
            if param.kind is inspect.Parameter.POSITIONAL_ONLY:
                raise TypeError(f"{getattr(fn, '__name__', fn)}() cannot bind positional-only '{name}'")
            keywords[name] = value
            continue
        if param.default is inspect.Parameter.empty:
            raise TypeError(
                f"{getattr(fn, '__name__', fn)}() missing required argument '{name}'"
            )
        blocked = True
    return fn(*positional, **keywords)


def _lookup(name: str, available: dict) -> tuple[bool, object]:
    if name in available:
        return True, available[name]
    for alias in _PARAM_ALIASES.get(name, ()):
        if alias in available:
            return True, available[alias]
    return False, None


def _accepts_any(fn, logical_names: set[str]) -> bool:
    try:
        signature = inspect.signature(fn)
    except (TypeError, ValueError):
        return True
    for name, param in signature.parameters.items():
        if param.kind in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD):
            continue
        candidates = {name, *_PARAM_ALIASES.get(name, ())}
        if candidates & logical_names:
            return True
    return False


def _prepare_frame(frame) -> pd.DataFrame:
    if frame is None:
        work = pd.DataFrame(columns=list(_COLUMNS))
    elif isinstance(frame, pd.DataFrame):
        work = frame.copy()
    else:
        work = pd.DataFrame(frame)
    for column in _COLUMNS:
        if column not in work.columns:
            work[column] = pd.NA
    return work


def _iter_groups(frame: pd.DataFrame):
    if len(frame) == 0:
        return
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", category=FutureWarning)
        grouped = list(frame.groupby(["product_id", "location"], dropna=False, sort=False))
    for key, group in grouped:
        product_id, location = key
        yield product_id, location, _chrono(group)


def _chrono(group: pd.DataFrame) -> pd.DataFrame:
    group = group.copy()
    if "date" not in group.columns:
        return group.reset_index(drop=True)
    try:
        return group.sort_values("date", kind="mergesort", na_position="last").reset_index(drop=True)
    except TypeError:
        return group.reset_index(drop=True)


def _column_series(group: pd.DataFrame, name: str) -> pd.Series:
    if name in group.columns:
        return group[name]
    return pd.Series([pd.NA] * len(group), index=group.index, dtype="object")


def _extract_corrected_frame(raw, original: pd.DataFrame) -> pd.DataFrame:
    if isinstance(raw, pd.DataFrame):
        return raw.reset_index(drop=True)
    if isinstance(raw, pd.Series):
        out = original.copy().reset_index(drop=True)
        values = raw.to_numpy() if len(raw) == len(out) else list(raw)
        out["forecast_corrected"] = values
        return out
    if isinstance(raw, dict):
        for key in ("frame", "df", "corrected_frame", "corrected_df", "data", "corrected"):
            value = raw.get(key)
            if isinstance(value, pd.DataFrame):
                return value.reset_index(drop=True)
        series_like = None
        for key in _CORRECTED_COLUMNS:
            if key in raw and not isinstance(raw[key], (str, dict)):
                series_like = raw[key]
                break
        if series_like is not None:
            out = original.copy().reset_index(drop=True)
            out["forecast_corrected"] = _as_sequence(series_like, len(out))
            for key in _NOTE_COLUMNS:
                if key in raw and not isinstance(raw[key], (str, dict)):
                    out["correction_note"] = _as_sequence(raw[key], len(out))
                    break
                if key in raw and isinstance(raw[key], str):
                    out["correction_note"] = raw[key]
                    break
            return out
    return original.copy().reset_index(drop=True)


def _as_sequence(value, length: int):
    if isinstance(value, pd.Series):
        return value.to_numpy() if len(value) == length else list(value)
    if isinstance(value, np.ndarray):
        return value
    return list(value)


def _correction_view(raw, corrected: pd.DataFrame) -> dict:
    actions: list[str] = []
    changed = None
    summary = ""
    if isinstance(raw, dict):
        actions = _as_str_list(_first_key(raw, ("actions", "acciones", "steps", "applied", "operations")))
        changed = _as_int(_first_key(raw, ("changed_points", "n_changed", "points_changed", "n_adjusted", "changed")))
        summary = _as_text(_first_key(raw, ("method_summary", "summary", "method", "description")))
    if changed is None:
        changed = _count_changes(corrected)
    return {
        "actions": actions,
        "changed_points": int(changed),
        "method_summary": summary,
    }


def _count_changes(frame: pd.DataFrame) -> int:
    corrected = _pick_column(frame, _CORRECTED_COLUMNS)
    if corrected is None or "forecast" not in frame.columns:
        return 0
    old = pd.to_numeric(frame["forecast"], errors="coerce")
    new = pd.to_numeric(corrected, errors="coerce")
    same = old.eq(new) | (old.isna() & new.isna())
    return int((~same).sum())


def _preview_rows(raw) -> list:
    if isinstance(raw, pd.DataFrame):
        data = _jsonify(raw)
    else:
        data = _jsonify(raw)
    if isinstance(data, dict):
        for key in ("rows", "preview", "table", "records", "data"):
            if isinstance(data.get(key), list):
                data = data[key]
                break
        else:
            return []
    if not isinstance(data, list):
        return []
    return data[:_PREVIEW_LIMIT]


def _write_long_rows(writer, product_id, location, original: pd.DataFrame, corrected: pd.DataFrame) -> None:
    corrected = corrected.reset_index(drop=True)
    original = original.reset_index(drop=True)
    dates = _aligned(corrected, original, "date")
    forecasts = _aligned(corrected, original, "forecast")
    actuals = _aligned(corrected, original, "actual")
    corrected_values = _pick_column(corrected, _CORRECTED_COLUMNS)
    notes = _pick_column(corrected, _NOTE_COLUMNS)
    has_corrected = corrected_values is not None
    for index in range(len(corrected)):
        forecast = forecasts.iloc[index] if index < len(forecasts) else pd.NA
        corrected_value = corrected_values.iloc[index] if has_corrected and index < len(corrected_values) else forecast
        note = notes.iloc[index] if notes is not None and index < len(notes) else ""
        writer.writerow(
            [
                _csv_text(_id_value(product_id)),
                _csv_text(_id_value(location)),
                _iso_text(dates.iloc[index] if index < len(dates) else pd.NA),
                _csv_value(forecast),
                _csv_value(corrected_value),
                _csv_value(actuals.iloc[index] if index < len(actuals) else pd.NA),
                "" if _scalar_na(note) else _csv_text(note),
            ]
        )


def _aligned(corrected: pd.DataFrame, original: pd.DataFrame, column: str) -> pd.Series:
    if column in corrected.columns:
        return corrected[column].reset_index(drop=True)
    if column in original.columns and len(original) == len(corrected):
        return original[column].reset_index(drop=True)
    return pd.Series([pd.NA] * len(corrected), dtype="object")


def _pick_column(frame: pd.DataFrame, names: tuple[str, ...]) -> pd.Series | None:
    for name in names:
        if name in frame.columns:
            return frame[name]
    return None


def _how_to_improve(findings, recommendations) -> list[str]:
    lines: list[str] = []
    seen: set[str] = set()
    for finding in _iter_findings(findings):
        for suggestion in _suggestions(finding):
            key = suggestion.casefold()
            if key in seen:
                continue
            seen.add(key)
            lines.append(suggestion)
            if len(lines) >= _SUGGESTION_LIMIT:
                break
        if len(lines) >= _SUGGESTION_LIMIT:
            break
    model_line = _top_model_line(recommendations)
    if model_line and model_line.casefold() not in seen:
        lines.append(model_line)
    return lines


def _iter_findings(findings):
    if findings is None:
        return
    if isinstance(findings, list):
        yield from findings
        return
    if isinstance(findings, tuple):
        yield from findings
        return
    if isinstance(findings, dict):
        if any(key in findings for key in ("suggestion", "sugerencia", "suggestions", "code", "id", "message", "severity")):
            yield findings
            return
        for value in findings.values():
            if isinstance(value, list):
                yield from value
            else:
                yield value
        return
    yield findings


def _suggestions(finding) -> list[str]:
    if isinstance(finding, str):
        text = finding.strip()
        return [text] if text else []
    if not isinstance(finding, dict):
        return []
    found: list[str] = []
    for key in _SUGGESTION_KEYS:
        found.extend(_text_items(finding.get(key)))
    for key in _SUGGESTION_LIST_KEYS:
        found.extend(_text_items(finding.get(key)))
    return found


def _text_items(value) -> list[str]:
    if isinstance(value, str):
        text = value.strip()
        return [text] if text else []
    if isinstance(value, (list, tuple)):
        items = []
        for item in value:
            if isinstance(item, str) and item.strip():
                items.append(item.strip())
            elif isinstance(item, dict):
                text = _first_text(item, _SUGGESTION_KEYS + ("text", "description", "summary", "detail"))
                if text:
                    items.append(text)
        return items
    return []


def _iter_recs(recommendations):
    if recommendations is None:
        return []
    if isinstance(recommendations, str):
        return [recommendations]
    if isinstance(recommendations, (list, tuple)):
        return list(recommendations)
    if isinstance(recommendations, dict):
        if any(key in recommendations for key in _MODEL_KEYS):
            extras = []
            for key in ("alternatives", "others", "runners_up"):
                if isinstance(recommendations.get(key), list):
                    extras.extend(recommendations[key])
            return [recommendations, *extras]
        for key in ("recommendations", "models", "ranked", "items"):
            if isinstance(recommendations.get(key), list):
                return list(recommendations[key])
        rows = []
        for key, value in recommendations.items():
            if isinstance(value, dict):
                row = dict(value)
                row.setdefault("model", str(key))
                rows.append(row)
            elif isinstance(value, str):
                rows.append({"model": str(key), "why": value})
        return rows
    return []


def _top_model_name(recommendations) -> str:
    items = _iter_recs(recommendations)
    if not items:
        return ""
    top = items[0]
    if isinstance(top, str):
        return top.strip()
    if isinstance(top, dict):
        return _first_text(top, _MODEL_NAME_KEYS)
    if isinstance(top, (list, tuple)) and top:
        return str(top[0]).strip()
    return ""


def _top_model_line(recommendations) -> str:
    items = _iter_recs(recommendations)
    if not items:
        return ""
    top = items[0]
    if isinstance(top, str) and top.strip():
        return f"Modelo sugerido: {top.strip()}."
    name = ""
    why = ""
    if isinstance(top, dict):
        name = _first_text(top, _MODEL_NAME_KEYS)
        why = _first_text(top, _WHY_KEYS)
    elif isinstance(top, (list, tuple)) and top:
        name = str(top[0]).strip()
        if len(top) > 1 and top[1] is not None:
            why = str(top[1]).strip()
    if name and why:
        why = _model_reason(why)
        if why and why[-1] not in ".!?":
            why = f"{why}."
        if why:
            return f"Modelo sugerido: {name}. {why}"
    if name:
        return f"Modelo sugerido: {name}."
    return ""


def _model_reason(why: str) -> str:
    text = " ".join(why.split())
    if text.lower().startswith("cifras de esta serie:"):
        split_at = text.find(". ")
        if split_at != -1:
            text = text[split_at + 2 :].strip()
    if len(text) > 420:
        cut = text.rfind(". ", 80, 420)
        text = text[: cut + 1] if cut != -1 else text[:420].rstrip() + "..."
    return text


def _portfolio_advice(
    products: list[dict],
    summary: dict,
    frequency: str,
    source_name: str,
    warnings: list[str],
    with_actual: int,
    total_series: int,
) -> list[str]:
    if summary.get("products", 0) == 0:
        lines = _empty_advice(source_name, frequency, warnings)
        return _bound_advice(lines)

    lines = [
        _overview_sentence(
            summary,
            frequency,
            source_name,
            has_scores=any(_score_of(product.get("verdict")) is not None for product in products),
        ),
        _discard_sentence(products),
        _actuals_sentence(with_actual, total_series),
        _bias_sentence(products, file_lacks_actuals=(with_actual == 0)),
    ]
    if warnings:
        shown = "; ".join(warnings[:3])
        lines.append(f"La carga del archivo reportó advertencias: {shown}.")
    class_line = _class_sentence(products)
    if class_line:
        lines.append(class_line)
    model_line = _model_consensus(products)
    if model_line:
        lines.append(model_line)
    return _bound_advice(lines)


def _empty_advice(source_name: str, frequency: str, warnings: list[str]) -> list[str]:
    origin = f" '{source_name}'" if source_name else ""
    freq = _frequency_label(frequency)
    freq_bit = f" a frecuencia {freq}" if freq else ""
    lines = [
        (
            f"Advertencia: el archivo{origin} no contiene filas{freq_bit} "
            "y no hay series producto-sucursal para auditar."
        ),
        "El archivo carece de actuals y no hay bias_pct calculable, así que no se puede leer el signo del sesgo.",
        "No hay concentración de descartes: con cero series no hay nada que aprobar, corregir o descartar.",
    ]
    if warnings:
        lines.append("La carga del archivo reportó advertencias: " + "; ".join(warnings[:3]) + ".")
    return lines


def _overview_sentence(summary: dict, frequency: str, source_name: str, has_scores: bool) -> str:
    n = int(summary["products"])
    rows = int(summary["rows"])
    freq = _frequency_label(frequency)
    freq_bit = f" a frecuencia {freq}" if freq else ""
    origin = f"En {source_name} hay" if source_name else "Hay"
    serie = "serie" if n == 1 else "series"
    fila = "fila" if rows == 1 else "filas"
    if has_scores:
        score_bit = f"Puntaje medio {_format_number(summary['avg_score'])}"
    else:
        score_bit = "Sin puntaje medio"
    median = summary.get("median_wape")
    wape_bit = f"WAPE mediano {_format_number(median)}" if median is not None else "sin WAPE mediano"
    return (
        f"{origin} {n} {serie} producto-sucursal y {rows} {fila}{freq_bit}. "
        f"Decisiones: {summary['aprobar']} para aprobar, {summary['corregir']} para corregir "
        f"y {summary['descartar']} para descartar. {score_bit}; {wape_bit}."
    )


def _discard_sentence(products: list[dict]) -> str:
    n = len(products)
    serie = "serie" if n == 1 else "series"
    discards = [product for product in products if _decision_of(product) == "descartar"]
    d = len(discards)
    if d == 0:
        if n == 1:
            return "No hay concentración de descartes: la serie no se descarta."
        return f"No hay concentración de descartes: ninguna de las {n} series se descarta."
    pct = int(round(100.0 * d / n))
    where = _discard_focus(discards, products)
    if d == 1:
        share = "de la serie" if n == 1 else f"de las {n} series"
        if where:
            return f"El único descarte ({pct}% {share}) se concentra en " + " y ".join(where) + "."
        loc = _label(discards[0].get("location")) or "sin sucursal"
        return f"El único descarte ({pct}% {share}) se concentra en la sucursal {loc}."
    head = f"Los descartes son {d} de {n} {serie} ({pct}%)"
    if where:
        return head + " y se concentran en " + " y ".join(where) + "."
    return head + " y no se concentran en una sola sucursal o categoría."


def _discard_focus(discards: list[dict], products: list[dict]) -> list[str]:
    """Places that hold most discards and a larger share than in the whole file."""
    n = len(products)
    d = len(discards)
    focus = []
    for field, kind in (("location", "la sucursal"), ("category", "la categoría")):
        labels = []
        for product in discards:
            label = _label(product.get(field))
            if field == "location" and not label:
                label = "sin sucursal"
            if label:
                labels.append(label)
        if not labels:
            continue
        label, count = Counter(labels).most_common(1)[0]
        if count * 2 <= d:
            continue
        portfolio = 0
        for product in products:
            other = _label(product.get(field))
            if field == "location" and not other:
                other = "sin sucursal"
            if other == label:
                portfolio += 1
        if n and portfolio / n >= count / d:
            continue
        focus.append(f"{kind} {label} ({count} de {d})")
    return focus


def _actuals_sentence(with_actual: int, total: int) -> str:
    if total == 0 or with_actual == 0:
        return (
            "El archivo carece de actuals: no hay venta real en la columna actual "
            "y la exactitud no es confiable."
        )
    if with_actual < total:
        missing = total - with_actual
        return (
            f"Faltan actuals en {missing} de {total} series; el resto sí trae venta real para medir el error."
        )
    return "El archivo sí trae actuals en todas las series, así que el error y el sesgo se pueden medir."


def _bias_sentence(products: list[dict], file_lacks_actuals: bool) -> str:
    if file_lacks_actuals:
        return (
            "No hay un signo de bias_pct que compartir: sin actuals el sesgo del pronóstico no es calculable."
        )
    signed = []
    for product in products:
        bias = _metric_value(product, "bias_pct")
        if bias is None or bias == 0:
            continue
        signed.append(bias)
    n = len(products)
    if not signed:
        return "Ninguna serie tiene bias_pct distinto de cero, así que no comparten un signo de sesgo."
    positive = sum(1 for bias in signed if bias > 0)
    negative = len(signed) - positive
    if positive > negative and positive > n / 2:
        return (
            f"La mayoría de las series ({positive} de {n}) comparte bias_pct positivo: "
            "el pronóstico queda por encima de la venta real."
        )
    if negative > positive and negative > n / 2:
        return (
            f"La mayoría de las series ({negative} de {n}) comparte bias_pct negativo: "
            "el pronóstico queda por debajo de la venta real."
        )
    return (
        f"El bias_pct no tiene un signo mayoritario ({positive} positivo y {negative} negativo entre {n} series)."
    )


def _class_sentence(products: list[dict]) -> str:
    labels = [label for label in (_demand_class(product.get("profile")) for product in products) if label]
    if not labels:
        return ""
    top, count = Counter(labels).most_common(1)[0]
    if count * 2 <= len(products):
        return ""
    serie = "serie" if count == 1 else "series"
    return f"La clase de demanda dominante es {top}: {count} {serie} de {len(products)}."


def _model_consensus(products: list[dict]) -> str:
    names = [name for name in (_top_model_name(product.get("recommendations")) for product in products) if name]
    if not names:
        return ""
    top, count = Counter(names).most_common(1)[0]
    if count < 2 and count * 2 <= len(products):
        return ""
    return f"El modelo más sugerido en el archivo es {top} ({count} de {len(products)} series)."


def _bound_advice(lines: list[str]) -> list[str]:
    cleaned = []
    seen = set()
    for line in lines:
        text = " ".join(str(line).split())
        if not text or text in seen:
            continue
        seen.add(text)
        cleaned.append(text)
    fillers = (
        "Revise el archivo completo antes de usar estos pronósticos en la operación.",
        "No hay evidencia adicional para una recomendación de portafolio más específica.",
    )
    for filler in fillers:
        if len(cleaned) >= 3:
            break
        cleaned.append(filler)
    return cleaned[:6]


def _actual_coverage(frame: pd.DataFrame) -> tuple[int, int]:
    if len(frame) == 0 or "actual" not in frame.columns:
        return 0, 0
    if "product_id" not in frame.columns or "location" not in frame.columns:
        numeric = pd.to_numeric(frame["actual"], errors="coerce")
        return (1 if bool(numeric.notna().any()) else 0), 1
    total = 0
    with_actual = 0
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", category=FutureWarning)
        grouped = frame.groupby(["product_id", "location"], dropna=False, sort=False)
        for _, group in grouped:
            total += 1
            numeric = pd.to_numeric(group["actual"], errors="coerce")
            if bool(numeric.notna().any()):
                with_actual += 1
    return with_actual, total


def _worst_item(product: dict) -> dict:
    score = _score_of(product.get("verdict"))
    return {
        "product_id": product.get("product_id"),
        "location": product.get("location"),
        "score": None if score is None else float(score),
        "decision": _decision_of(product),
    }


def _product_sort_key(product: dict):
    score = _score_of(product.get("verdict"))
    missing = score is None
    product_id = "" if product.get("product_id") is None else str(product.get("product_id"))
    location = "" if product.get("location") is None else str(product.get("location"))
    return (1 if missing else 0, 0.0 if missing else float(score), product_id, location)


def _decision_of(product: dict) -> str:
    if not isinstance(product, dict):
        return ""
    return _decision_from(product.get("verdict"))


def _decision_from(product_verdict) -> str:
    if isinstance(product_verdict, str):
        return _norm_decision(product_verdict)
    if isinstance(product_verdict, dict):
        for key in ("decision", "verdict", "status", "outcome", "label", "accion", "action"):
            value = product_verdict.get(key)
            if isinstance(value, str):
                return _norm_decision(value)
        raw = _dig(product_verdict, ("decision", "verdict", "status", "outcome", "label"))
        if isinstance(raw, str):
            return _norm_decision(raw)
    return ""


def _norm_decision(raw) -> str:
    if raw is None or _scalar_na(raw):
        return ""
    text = str(raw).strip().lower()
    if text in _DECISION_EXACT:
        return _DECISION_EXACT[text]
    if text.startswith("aprob") or text.startswith("approv"):
        return "aprobar"
    if text.startswith("correg") or text.startswith("correct"):
        return "corregir"
    if text.startswith("descart") or text.startswith("discard") or text.startswith("reject"):
        return "descartar"
    return text


def _score_of(product_verdict):
    if isinstance(product_verdict, dict):
        return _as_float(_dig(product_verdict, _SCORE_KEYS))
    if isinstance(product_verdict, str):
        return None
    return _as_float(product_verdict)


def _metric_value(product: dict, metric: str):
    metrics = product.get("metrics") if isinstance(product, dict) else None
    return _as_float(_dig(metrics, _METRIC_KEYS[metric]))


def _demand_class(profile) -> str:
    raw = _dig(profile, _CLASS_KEYS)
    if isinstance(raw, dict):
        raw = _first_text(raw, ("label", "name", "class", "demand_class", "code"))
    if raw is None or _scalar_na(raw):
        return ""
    return str(raw).strip()


def _dig(obj, keys):
    if not isinstance(obj, dict):
        return None
    for key in keys:
        if key in obj and not _scalar_na(obj[key]):
            return obj[key]
    for nest_name in ("summary", "stats", "values", "metrics", "profile", "classification", "sb"):
        inner = obj.get(nest_name)
        if isinstance(inner, dict):
            for key in keys:
                if key in inner and not _scalar_na(inner[key]):
                    return inner[key]
    return None


def _first_key(obj: dict, keys: tuple[str, ...]):
    for key in keys:
        if key in obj and obj[key] is not None and not _scalar_na(obj[key]):
            return obj[key]
    return None


def _first_text(obj: dict, keys: tuple[str, ...]) -> str:
    for key in keys:
        value = obj.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _as_str_list(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        text = value.strip()
        return [text] if text else []
    if isinstance(value, dict):
        items = []
        for key, item in value.items():
            text = _as_text(item)
            if text:
                items.append(f"{key}: {text}" if key else text)
        return items
    if isinstance(value, (list, tuple)):
        items = []
        for item in value:
            if isinstance(item, str) and item.strip():
                items.append(item.strip())
            elif isinstance(item, dict):
                text = _first_text(item, ("action", "description", "text", "summary", "detail", "method", "name"))
                if text:
                    items.append(text)
            elif item is not None and not _scalar_na(item):
                items.append(str(item))
        return items
    if isinstance(value, (pd.DataFrame, pd.Series)):
        return []
    return [str(value)]


def _as_text(value) -> str:
    if value is None or _scalar_na(value):
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (list, tuple)):
        parts = [_as_text(item) for item in value]
        return " ".join(part for part in parts if part)
    if isinstance(value, dict):
        return _first_text(value, ("text", "summary", "description", "method", "name"))
    if isinstance(value, (pd.DataFrame, pd.Series)):
        return ""
    return str(value).strip()


def _as_float(value):
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float, np.integer, np.floating, Decimal)):
        number = float(value)
    elif isinstance(value, str):
        text = value.strip().replace("%", "").replace(" ", "")
        if text.count(",") == 1 and "." not in text:
            text = text.replace(",", ".")
        else:
            text = text.replace(",", "")
        if not text:
            return None
        try:
            number = float(text)
        except ValueError:
            return None
    else:
        return None
    if not math.isfinite(number):
        return None
    return number


def _as_int(value):
    number = _as_float(value)
    if number is None:
        return None
    return int(round(number))


def _text_mode(series: pd.Series) -> str:
    counts: Counter[str] = Counter()
    for value in series.tolist():
        if _scalar_na(value):
            continue
        text = str(value).strip()
        if not text or text.lower() in {"nan", "none", "<na>", "nat"}:
            continue
        counts[text] += 1
    if not counts:
        return ""
    best = max(counts.values())
    for value in series.tolist():
        if _scalar_na(value):
            continue
        text = str(value).strip()
        if counts.get(text) == best:
            return text
    return ""


def _mode_generic(series: pd.Series):
    values = []
    for value in series.tolist():
        if _scalar_na(value):
            continue
        if isinstance(value, str):
            value = value.strip()
            if not value or value.lower() == "nan":
                continue
        values.append(value)
    if not values:
        return None
    try:
        counts = Counter(values)
    except TypeError:
        return _jsonify(values[0])
    best = max(counts.values())
    for value in values:
        if counts[value] == best:
            number = _as_float(value)
            if number is not None and float(number).is_integer() and not isinstance(value, str):
                return int(number)
            return _jsonify(value)
    return None


def _label(value) -> str:
    if value is None or _scalar_na(value):
        return ""
    text = str(value).strip()
    if text.lower() in {"nan", "none", "<na>", "nat"}:
        return ""
    return text


def _as_warnings(warnings_value) -> list[str]:
    if warnings_value is None:
        return []
    if isinstance(warnings_value, str):
        return [warnings_value] if warnings_value else []
    return [str(item) for item in warnings_value]


def _id_value(value):
    cleaned = _jsonify(value)
    if isinstance(cleaned, float) and cleaned.is_integer():
        return int(cleaned)
    return cleaned


def _frequency_label(frequency: str) -> str:
    text = (frequency or "").strip()
    if not text:
        return ""
    key = text.lower().replace("-", "").replace("_", "").replace(" ", "")
    labels = {
        "d": "diaria",
        "day": "diaria",
        "daily": "diaria",
        "dia": "diaria",
        "diario": "diaria",
        "diaria": "diaria",
        "w": "semanal",
        "week": "semanal",
        "weekly": "semanal",
        "semana": "semanal",
        "semanal": "semanal",
        "m": "mensual",
        "month": "mensual",
        "monthly": "mensual",
        "mes": "mensual",
        "mensual": "mensual",
        "q": "trimestral",
        "quarter": "trimestral",
        "quarterly": "trimestral",
        "trimestral": "trimestral",
        "y": "anual",
        "a": "anual",
        "year": "anual",
        "yearly": "anual",
        "annual": "anual",
        "anual": "anual",
        "h": "horaria",
        "hour": "horaria",
        "hourly": "horaria",
        "horaria": "horaria",
    }
    return labels.get(key, text)


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _format_number(value) -> str:
    number = _as_float(value)
    if number is None:
        return ""
    text = f"{number:.6f}".rstrip("0").rstrip(".")
    if text in {"", "-0"}:
        return "0"
    return text


def _csv_text(value) -> str:
    if value is None or _scalar_na(value):
        return ""
    return str(value)


def _csv_value(value) -> str:
    if value is None or _scalar_na(value):
        return ""
    if isinstance(value, str):
        text = value.strip()
        number = _as_float(text)
        return _format_number(number) if number is not None else text
    number = _as_float(value)
    if number is not None:
        return _format_number(number)
    return _csv_text(value)


def _iso_text(value) -> str:
    iso = _iso_value(value)
    return "" if iso is None else iso


def _iso_value(value):
    if value is None or _scalar_na(value):
        return None
    if isinstance(value, str):
        text = value.strip()
        return text or None
    if isinstance(value, pd.Timestamp):
        if pd.isna(value):
            return None
        stamp = value
        if stamp.tzinfo is not None:
            stamp = stamp.tz_convert("UTC")
            return stamp.isoformat().replace("+00:00", "Z")
        if stamp.hour == 0 and stamp.minute == 0 and stamp.second == 0 and stamp.nanosecond == 0:
            return stamp.date().isoformat()
        return stamp.isoformat()
    if isinstance(value, datetime):
        if value.tzinfo is not None:
            return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
        if value.hour == 0 and value.minute == 0 and value.second == 0 and value.microsecond == 0:
            return value.date().isoformat()
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, np.datetime64):
        if np.isnat(value):
            return None
        return _iso_value(pd.Timestamp(value))
    try:
        stamp = pd.Timestamp(value)
    except (TypeError, ValueError):
        return str(value)
    if pd.isna(stamp):
        return None
    return _iso_value(stamp)


def _scalar_na(value) -> bool:
    if value is None:
        return True
    if isinstance(value, (str, bytes, bool, dict, list, tuple, set, frozenset)):
        return False
    if isinstance(value, (pd.DataFrame, pd.Series, np.ndarray)):
        return False
    try:
        missing = pd.isna(value)
    except (TypeError, ValueError):
        return False
    if isinstance(missing, (bool, np.bool_)):
        return bool(missing)
    return False


def _jsonify(value):
    if value is None:
        return None
    if isinstance(value, (bool, np.bool_)):
        return bool(value)
    if isinstance(value, str):
        return value
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    if _scalar_na(value):
        return None
    if isinstance(value, (int, np.integer)) and not isinstance(value, bool):
        return int(value)
    if isinstance(value, (float, np.floating, Decimal)):
        number = float(value)
        if not math.isfinite(number):
            return None
        return number
    iso_candidate = isinstance(value, (datetime, date, pd.Timestamp, np.datetime64))
    if iso_candidate:
        return _iso_value(value)
    if isinstance(value, np.ndarray):
        return _jsonify(value.tolist())
    if isinstance(value, pd.DataFrame):
        return [_jsonify(row) for row in value.to_dict(orient="records")]
    if isinstance(value, pd.Series):
        return [_jsonify(item) for item in value.tolist()]
    if isinstance(value, dict):
        return {str(key): _jsonify(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonify(item) for item in value]
    if isinstance(value, (set, frozenset)):
        return [_jsonify(item) for item in value]
    if hasattr(value, "item") and callable(value.item):
        try:
            return _jsonify(value.item())
        except Exception:
            return str(value)
    return str(value)
