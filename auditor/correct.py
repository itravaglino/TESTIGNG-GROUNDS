"""Reparación de pronósticos de demanda para un solo producto.

pandas / numpy / stdlib. Sin impresiones. Las series corregidas no contienen
NaN ni Inf, salvo el caso de descarte (forecast_corrected queda en NaN).
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd

__all__ = ["correct_product", "corrections_table"]

_DIFF_EPS = 1e-6
_ZERO_EPS = 1e-8
_INT_TOL = 1e-5
_MAD_EPS = 1e-12
_MOD_Z = 3.5
_MOD_Z_CONST = 0.6745
_ADI_THRESHOLD = 1.32
_HOLT_ALPHA = 0.4
_HOLT_BETA = 0.2
_MAX_GRID = 200_000

_SEASON = {"D": 7, "W": 52, "M": 12, "Q": 4, "Y": 1}


def correct_product(df: pd.DataFrame, frequency: str, findings: list[dict]) -> dict:
    """Corrige el pronóstico de un producto.

    ``df`` tiene columnas ``date``, ``forecast`` y ``actual``.
    Si algún hallazgo pide ``action == discard`` o ``severity == critical``,
    no se repara: ``forecast_corrected`` queda en NaN, ``changed_points`` es 0
    y ``actions`` explica el descarte.
    """
    findings = list(findings or [])
    frame = _prepare_frame(df)

    if _should_discard(findings):
        out = frame.sort_values("date", kind="mergesort").reset_index(drop=True)
        out["forecast_corrected"] = np.nan
        out["correction_note"] = "Descartado; no se repara el pronóstico"
        out["forecast_corrected"] = out["forecast_corrected"].astype(float)
        return {
            "frame": out,
            "actions": [
                "Serie descartada por un hallazgo con acción 'discard' o severidad crítica; no se repara el pronóstico."
            ],
            "changed_points": 0,
            "method_summary": "Serie descartada por hallazgo crítico o acción discard; no se repara el pronóstico.",
        }

    if frame.empty:
        out = frame.copy()
        out["forecast_corrected"] = pd.Series(dtype=float)
        out["correction_note"] = pd.Series(dtype=str)
        return {
            "frame": out,
            "actions": [],
            "changed_points": 0,
            "method_summary": "Sin datos de pronóstico para corregir.",
        }

    kind = _normalize_frequency(frequency, frame["date"])
    grid, kind = _build_grid(frame["date"], kind)
    aligned = _align_to_grid(frame, grid, kind)
    # Cap: no inventar más de 2 periodos más allá de la última fecha observada.
    aligned = _cap_horizon(aligned, kind, periods=2)

    n = len(aligned)
    raw = aligned["forecast"].to_numpy(dtype=float)
    actual = aligned["actual"].to_numpy(dtype=float)
    corrected = raw.copy()
    notes: list[list[str]] = [[] for _ in range(n)]
    observed = np.isfinite(raw)

    actions: list[str] = []
    steps: list[str] = []

    intermittent, adi, zero_ratio = _intermittency(actual)

    # 1. Negativos -> 0
    neg_mask = np.isfinite(corrected) & (corrected < -_ZERO_EPS)
    n_neg = int(neg_mask.sum())
    if n_neg:
        corrected[neg_mask] = 0.0
        for i in np.flatnonzero(neg_mask):
            notes[i].append("Negativo ajustado a 0")
        actions.append(
            "Se ajustó 1 pronóstico negativo a 0."
            if n_neg == 1
            else f"Se ajustaron {n_neg} pronósticos negativos a 0."
        )
        steps.append("negativos a 0")

    # 2. Huecos en la rejilla
    gap_counts = _fill_gaps(corrected, actual, notes, kind)
    n_gaps = sum(gap_counts.values())
    if n_gaps:
        parts = []
        if gap_counts["seasonal"]:
            parts.append(f"{gap_counts['seasonal']} con naive estacional")
        if gap_counts["interp"]:
            parts.append(f"{gap_counts['interp']} por interpolación lineal")
        if gap_counts["ffill"]:
            parts.append(f"{gap_counts['ffill']} con el último valor positivo")
        if gap_counts["zero"]:
            parts.append(f"{gap_counts['zero']} sin referencia (0)")
        verb = "Se rellenó" if n_gaps == 1 else "Se rellenaron"
        noun = "hueco" if n_gaps == 1 else "huecos"
        actions.append(
            f"{verb} {n_gaps} {noun} de la rejilla {_freq_label(kind)}: " + ", ".join(parts) + "."
        )
        steps.append("relleno de huecos")

    # La explosión de cola se decide antes de winsorizar: si el salto final
    # está respaldado por las ventas, ese punto no se recorta; si no, lo
    # sustituye el paso 4 (y no el límite de z modificado).
    tail = None if intermittent else _detect_tail_explosion(corrected, actual)
    skip_idx = {tail["index"]} if tail is not None else set()

    # 3. Atípicos (z modificado > 3.5), salvo intermitente
    if not intermittent:
        n_out = _winsorize_outliers(corrected, notes, skip_idx=skip_idx)
        if n_out:
            actions.append(
                "Se winsorizó 1 punto atípico (|z modificado| > 3.5) "
                "al límite mediana ± 3.5·MAD, con cota inferior 0."
                if n_out == 1
                else (
                    f"Se winsorizaron {n_out} puntos atípicos (|z modificado| > 3.5) "
                    "al límite mediana ± 3.5·MAD, con cota inferior 0."
                )
            )
            steps.append("winsorización")

    # 4. Explosión en la cola. En intermitente no se suavizan picos.
    if tail is not None and not tail["blocked"]:
        exploded = _apply_tail_explosion(corrected, notes, tail)
        if exploded is not None:
            old, new, k = exploded
            actions.append(
                f"Se corrigió la explosión del último periodo: {_fmt(old)} se reemplazó "
                f"por la mediana de los últimos {k} puntos ({_fmt(new)})."
            )
            steps.append("corrección de explosión final")

    # 5. Pronóstico todo ceros con ventas de media positiva
    zero_status = _replace_all_zero(corrected, actual, observed, notes, kind)
    if zero_status == "replaced":
        period = _SEASON[kind]
        actions.append(
            "Se reemplazó el pronóstico en ceros por un naive estacional de las ventas "
            f"(periodo {period}, con respaldo de rezago 1)."
        )
        steps.append("naive estacional por ceros")
    elif zero_status == "unrepairable":
        actions.append(
            "El pronóstico está en ceros y no hay ventas históricas; no se puede reparar."
        )
        steps.append("ceros irreparables")

    # 6. Pronóstico plano con ventas variables, no intermitente
    if not intermittent and zero_status != "replaced":
        n_holt = _replace_flat_with_holt(corrected, actual, observed, notes)
        if n_holt:
            actions.append(
                f"Se reemplazaron {n_holt} pronósticos futuros planos por suavizado "
                f"exponencial doble de Holt (alpha={_HOLT_ALPHA}, beta={_HOLT_BETA})."
            )
            steps.append("Holt")

    # 7. Historial entero -> pronóstico entero >= 0
    n_round = _round_if_integer_history(corrected, actual, notes)
    if n_round:
        actions.append(
            "Se redondeó 1 pronóstico al entero más cercano porque el historial de ventas es entero."
            if n_round == 1
            else (
                f"Se redondearon {n_round} pronósticos al entero más cercano "
                "porque el historial de ventas es entero."
            )
        )
        steps.append("redondeo a entero")

    _sanitize_finite(corrected, notes)

    note_str = ["; ".join(parts) if parts else "" for parts in notes]
    aligned = aligned.copy()
    aligned["forecast_corrected"] = corrected.astype(float)
    aligned["correction_note"] = note_str
    aligned = aligned.sort_values("date", kind="mergesort").reset_index(drop=True)

    changed = _count_changed(aligned["forecast"], aligned["forecast_corrected"])
    if steps:
        summary = "Correcciones: " + ", ".join(steps) + f". Puntos modificados: {changed}."
    else:
        summary = "Sin correcciones; el pronóstico se conserva."
    if intermittent:
        summary = (
            f"Demanda intermitente (ADI={adi:.2f}, proporción de ceros={zero_ratio:.2f}); "
            "no se suavizan picos. " + summary
        )

    return {
        "frame": aligned,
        "actions": actions,
        "changed_points": int(changed),
        "method_summary": summary,
    }


def corrections_table(df_with_corrected: pd.DataFrame) -> list[dict]:
    """Filas donde el pronóstico corregido difiere del original.

    Una fila entra si la diferencia absoluta supera 1e-6 o si uno de los dos
    lados es nulo. ``date`` va en ISO. Los valores no finitos se emiten como
    ``None`` para que el resultado sea serializable a JSON.
    """
    if "date" not in df_with_corrected.columns:
        raise KeyError("date")
    if "forecast" not in df_with_corrected.columns or "forecast_corrected" not in df_with_corrected.columns:
        raise KeyError("forecast/forecast_corrected")

    notes = df_with_corrected["correction_note"] if "correction_note" in df_with_corrected.columns else None
    rows: list[dict] = []
    for i, (date, forecast, corrected) in enumerate(
        zip(
            df_with_corrected["date"],
            df_with_corrected["forecast"],
            df_with_corrected["forecast_corrected"],
        )
    ):
        if not _values_differ(forecast, corrected):
            continue
        note = ""
        if notes is not None:
            raw_note = notes.iloc[i]
            if not _nullish(raw_note):
                note = str(raw_note)
        rows.append(
            {
                "date": _iso_date(date),
                "forecast": _json_number(forecast),
                "forecast_corrected": _json_number(corrected),
                "correction_note": note,
            }
        )
    return rows


# ---------------------------------------------------------------------------
# Descarte y preparación
# ---------------------------------------------------------------------------


def _should_discard(findings: list[Any]) -> bool:
    for finding in findings:
        if isinstance(finding, str):
            if finding.strip().lower() in {"discard", "critical"}:
                return True
            continue
        if not isinstance(finding, dict):
            continue
        action = finding.get("action", finding.get("decision", finding.get("recommendation", "")))
        severity = finding.get("severity", finding.get("level", ""))
        if isinstance(action, str) and action.strip().lower() == "discard":
            return True
        if isinstance(severity, str) and severity.strip().lower() == "critical":
            return True
    return False


def _prepare_frame(df: pd.DataFrame) -> pd.DataFrame:
    if df is None:
        raise ValueError("df is None")
    missing = [col for col in ("date", "forecast", "actual") if col not in df.columns]
    if missing:
        raise KeyError("Faltan columnas: " + ", ".join(missing))

    out = df.copy()
    # Si el llamador ya trae columnas de salida, se recalculan al final.
    for col in ("forecast_corrected", "correction_note"):
        if col in out.columns:
            out = out.drop(columns=[col])

    out["date"] = _parse_dates(out["date"])
    out["forecast"] = _to_float_series(out["forecast"])
    out["actual"] = _to_float_series(out["actual"])
    out = out.loc[out["date"].notna()].copy()
    return out


def _parse_dates(series: pd.Series) -> pd.Series:
    dates = pd.to_datetime(series, errors="coerce")
    if getattr(dates.dt, "tz", None) is not None:
        dates = dates.dt.tz_convert("UTC").dt.tz_localize(None)
    return dates


def _to_float_series(series: pd.Series) -> pd.Series:
    values = pd.to_numeric(series, errors="coerce").astype(float)
    values = values.mask(~np.isfinite(values), np.nan)
    return values


# ---------------------------------------------------------------------------
# Frecuencia y rejilla
# ---------------------------------------------------------------------------


def _normalize_frequency(frequency: str | None, dates: pd.Series) -> str:
    key = "" if frequency is None else str(frequency).strip().upper().replace(" ", "").replace("_", "-")
    aliases = {
        "D": "D",
        "DAY": "D",
        "DAILY": "D",
        "DIARIO": "D",
        "DIARIA": "D",
        "W": "W",
        "WEEK": "W",
        "WEEKLY": "W",
        "SEMANAL": "W",
        "M": "M",
        "MS": "M",
        "ME": "M",
        "MONTH": "M",
        "MONTHLY": "M",
        "MENSUAL": "M",
        "Q": "Q",
        "QS": "Q",
        "QE": "Q",
        "QUARTER": "Q",
        "QUARTERLY": "Q",
        "TRIMESTRAL": "Q",
        "Y": "Y",
        "A": "Y",
        "YS": "Y",
        "YE": "Y",
        "YEAR": "Y",
        "YEARLY": "Y",
        "ANNUAL": "Y",
        "ANUAL": "Y",
    }
    if key in aliases:
        return aliases[key]
    if key.startswith("W-"):
        return "W"
    if key.endswith("D") and key[:-1].isdigit():
        return "W" if int(key[:-1]) == 7 else "D"
    inferred = _infer_kind_from_dates(dates)
    return inferred or "D"


def _infer_kind_from_dates(dates: pd.Series) -> str | None:
    clean = pd.DatetimeIndex(dates.dropna()).sort_values().unique()
    if len(clean) < 2:
        return None
    deltas = np.diff(clean.values).astype("timedelta64[D]").astype(float)
    if deltas.size == 0:
        return None
    med = float(np.median(deltas))
    if med <= 2:
        return "D"
    if med <= 10:
        return "W"
    if med <= 45:
        return "M"
    if med <= 120:
        return "Q"
    if med <= 400:
        return "Y"
    return None


def _freq_label(kind: str) -> str:
    return {"D": "diaria", "W": "semanal", "M": "mensual", "Q": "trimestral", "Y": "anual"}.get(kind, kind)


def _build_grid(dates: pd.Series, kind: str) -> tuple[pd.DatetimeIndex, str]:
    stamped = pd.DatetimeIndex(pd.to_datetime(dates)).sort_values()
    if len(stamped) == 0:
        return pd.DatetimeIndex([]), kind
    start = stamped.min().normalize()
    end = stamped.max().normalize()

    if kind == "D":
        freq: Any = "D"
        anchor = "D"
    elif kind == "W":
        freq = "7D"
        anchor = "W"
        dow = int(pd.Series(stamped.dayofweek).mode().iloc[0])
        start = _snap_weekday(start, dow)
        end = _snap_weekday(end, dow)
        if end < start:
            end = start
    elif kind == "M":
        if _mostly_month_end(stamped):
            freq = "ME"
            anchor = "ME"
            start = _month_end(start)
            end = _month_end(end)
        else:
            freq = pd.DateOffset(months=1)
            anchor = "M"
    elif kind == "Q":
        if _mostly_quarter_end(stamped):
            freq = "QE"
            anchor = "QE"
            start = start + pd.offsets.QuarterEnd(0)
            end = end + pd.offsets.QuarterEnd(0)
        else:
            freq = pd.DateOffset(months=3)
            anchor = "Q"
    else:
        if _mostly_year_end(stamped):
            freq = "YE"
            anchor = "YE"
            start = start + pd.offsets.YearEnd(0)
            end = end + pd.offsets.YearEnd(0)
        else:
            freq = pd.DateOffset(years=1)
            anchor = "Y"

    if end < start:
        end = start
    try:
        grid = pd.date_range(start, end, freq=freq)
    except (ValueError, TypeError):
        grid = pd.DatetimeIndex([start])
    if len(grid) == 0:
        grid = pd.DatetimeIndex([start])
    if len(grid) > _MAX_GRID:
        # Rejilla desproporcionada: no inventar miles de periodos.
        grid = pd.DatetimeIndex(stamped.normalize().unique()).sort_values()
    kind_out = {"D": "D", "W": "W", "M": "M", "ME": "M", "Q": "Q", "QE": "Q", "Y": "Y", "YE": "Y"}.get(anchor, kind)
    return pd.DatetimeIndex(grid), kind_out


def _snap_weekday(ts: pd.Timestamp, dow: int) -> pd.Timestamp:
    ts = pd.Timestamp(ts).normalize()
    delta = int(ts.dayofweek) - int(dow)
    if delta > 3:
        delta -= 7
    elif delta < -3:
        delta += 7
    return ts - pd.Timedelta(days=int(delta))


def _month_end(ts: pd.Timestamp) -> pd.Timestamp:
    return pd.Timestamp(ts).normalize() + pd.offsets.MonthEnd(0)


def _mostly_month_end(dates: pd.DatetimeIndex) -> bool:
    flags = [(pd.Timestamp(d) + pd.offsets.MonthEnd(0)) == pd.Timestamp(d).normalize() for d in dates]
    return bool(flags) and (sum(flags) / len(flags) >= 0.6)


def _mostly_quarter_end(dates: pd.DatetimeIndex) -> bool:
    flags = [bool(pd.Timestamp(d).is_quarter_end) for d in dates]
    return bool(flags) and (sum(flags) / len(flags) >= 0.6)


def _mostly_year_end(dates: pd.DatetimeIndex) -> bool:
    flags = [pd.Timestamp(d).month == 12 and bool(pd.Timestamp(d).is_month_end) for d in dates]
    return bool(flags) and (sum(flags) / len(flags) >= 0.6)


def _shift(ts: pd.Timestamp, kind: str, steps: int, month_end: bool, quarter_end: bool, year_end: bool) -> pd.Timestamp:
    ts = pd.Timestamp(ts)
    if kind == "D":
        return ts + pd.Timedelta(days=steps)
    if kind == "W":
        return ts + pd.Timedelta(weeks=steps)
    if kind == "M":
        if month_end:
            return ts + pd.offsets.MonthEnd(steps)
        return ts + pd.DateOffset(months=steps)
    if kind == "Q":
        if quarter_end:
            return ts + pd.offsets.QuarterEnd(steps)
        return ts + pd.DateOffset(months=3 * steps)
    if year_end:
        return ts + pd.offsets.YearEnd(steps)
    return ts + pd.DateOffset(years=steps)


def _align_to_grid(frame: pd.DataFrame, grid: pd.DatetimeIndex, kind: str) -> pd.DataFrame:
    work = frame.copy()
    work["date"] = pd.to_datetime(work["date"])
    keys = [_bucket_date(pd.Timestamp(d), grid, kind) for d in work["date"]]
    work["_bucket"] = keys

    meta_cols = [c for c in work.columns if c not in {"date", "forecast", "actual", "_bucket"}]
    records = []
    for bucket, group in work.groupby("_bucket", sort=True):
        rec: dict[str, Any] = {"date": pd.Timestamp(bucket)}
        rec["forecast"] = _nanmean(group["forecast"].to_numpy(dtype=float))
        rec["actual"] = _nanmean(group["actual"].to_numpy(dtype=float))
        for col in meta_cols:
            non_null = group[col].dropna()
            rec[col] = non_null.iloc[-1] if len(non_null) else np.nan
        records.append(rec)

    if records:
        base = pd.DataFrame.from_records(records)
    else:
        base = pd.DataFrame(columns=["date", "forecast", "actual", *meta_cols])

    base["date"] = pd.to_datetime(base["date"])
    base = base.set_index("date").sort_index()
    full = base.reindex(pd.DatetimeIndex(grid))
    full.index.name = "date"
    full = full.reset_index()

    for col in meta_cols:
        if col not in full.columns:
            continue
        nunq = full[col].nunique(dropna=True)
        if nunq == 1:
            fill = full[col].dropna().iloc[0]
            full[col] = fill
    full["forecast"] = _to_float_series(full["forecast"])
    full["actual"] = _to_float_series(full["actual"])
    return full


def _bucket_date(ts: pd.Timestamp, grid: pd.DatetimeIndex, kind: str) -> pd.Timestamp:
    ts = pd.Timestamp(ts).normalize()
    if len(grid) == 0:
        return ts
    if kind == "D":
        return ts
    if kind == "W":
        # El ancla semanal ya está en la rejilla (paso de 7 días).
        start = pd.Timestamp(grid[0])
        delta_days = int((ts.normalize() - start.normalize()).days)
        step = int(round(delta_days / 7.0))
        candidate = start + pd.Timedelta(days=7 * step)
        return pd.Timestamp(min(grid, key=lambda g: abs(pd.Timestamp(g) - candidate)))
    if kind == "M":
        same = [pd.Timestamp(g) for g in grid if pd.Timestamp(g).year == ts.year and pd.Timestamp(g).month == ts.month]
        if same:
            return same[0]
    if kind == "Q":
        quarter = (ts.month - 1) // 3
        same = [
            pd.Timestamp(g)
            for g in grid
            if pd.Timestamp(g).year == ts.year and (pd.Timestamp(g).month - 1) // 3 == quarter
        ]
        if same:
            return same[0]
    if kind == "Y":
        same = [pd.Timestamp(g) for g in grid if pd.Timestamp(g).year == ts.year]
        if same:
            return same[0]
    # Reserva: punto de la rejilla más cercano, sin salirse del rango.
    return pd.Timestamp(min(grid, key=lambda g: abs(pd.Timestamp(g) - ts)))


def _cap_horizon(frame: pd.DataFrame, kind: str, periods: int) -> pd.DataFrame:
    if frame.empty:
        return frame
    dates = pd.to_datetime(frame["date"])
    # La última fecha observada es el extremo de la rejilla ya construida
    # (no se alarga el horizonte). El tope de 2 periodos solo descarta
    # cubos accidentales más allá de ese extremo.
    last_obs = pd.Timestamp(dates.max())
    month_end = bool(len(dates)) and _mostly_month_end(pd.DatetimeIndex(dates))
    quarter_end = bool(len(dates)) and _mostly_quarter_end(pd.DatetimeIndex(dates))
    year_end = bool(len(dates)) and _mostly_year_end(pd.DatetimeIndex(dates))
    limit = _shift(last_obs, kind, periods, month_end, quarter_end, year_end)
    # Se conservan las fechas ya presentes en la entrada (observadas como fila)
    # y cualquier hueco interno. No se dejan periodos nuevos posteriores al tope.
    keep = dates <= limit
    # El tope siempre cubre last_obs; si el ancla de fin de periodo desplaza
    # last_obs, no se elimina esa última observación.
    keep = keep | (dates <= last_obs)
    capped = frame.loc[keep].copy()
    return capped.reset_index(drop=True)


def _nanmean(values: np.ndarray) -> float:
    finite = np.asarray(values, dtype=float)
    finite = finite[np.isfinite(finite)]
    if finite.size == 0:
        return float("nan")
    return float(np.mean(finite))


# ---------------------------------------------------------------------------
# Correcciones
# ---------------------------------------------------------------------------


def _fill_gaps(
    corrected: np.ndarray,
    actual: np.ndarray,
    notes: list[list[str]],
    kind: str,
) -> dict[str, int]:
    counts = {"seasonal": 0, "interp": 0, "ffill": 0, "zero": 0}
    missing = ~np.isfinite(corrected)
    if not missing.any():
        return counts

    period = _SEASON[kind]
    use_seasonal = _spans_two_seasons(actual, period)
    if use_seasonal:
        seasonal_vals = _seasonal_naive_from_actuals(actual, period, fallback_lag1=False)
        for i in np.flatnonzero(missing):
            val = seasonal_vals[i]
            if val is None or not np.isfinite(val):
                continue
            corrected[i] = _nonneg(val)
            notes[i].append("Hueco rellenado con naive estacional")
            counts["seasonal"] += 1
            missing[i] = False

    if missing.any() and np.isfinite(corrected).sum() >= 2:
        filled = _linear_interpolate(corrected)
        for i in np.flatnonzero(missing):
            if np.isfinite(filled[i]):
                corrected[i] = _nonneg(filled[i])
                notes[i].append("Hueco rellenado por interpolación lineal")
                counts["interp"] += 1
                missing[i] = False

    if missing.any():
        anchor = _positive_anchor(actual, corrected)
        for i in np.flatnonzero(missing):
            if np.isfinite(anchor[i]):
                corrected[i] = _nonneg(anchor[i])
                notes[i].append("Hueco rellenado con el último valor positivo")
                counts["ffill"] += 1
                missing[i] = False

    for i in np.flatnonzero(missing):
        corrected[i] = 0.0
        notes[i].append("Hueco sin referencia; se usó 0")
        counts["zero"] += 1
    return counts


def _spans_two_seasons(actual: np.ndarray, period: int) -> bool:
    idx = np.flatnonzero(np.isfinite(actual))
    if idx.size == 0:
        return False
    coverage = int(idx[-1] - idx[0] + 1)
    need = max(2, 2 * max(period, 1))
    return coverage >= need


def _seasonal_naive_from_actuals(
    actual: np.ndarray,
    period: int,
    fallback_lag1: bool,
) -> list[float | None]:
    """Naive estacional sobre posiciones de la rejilla.

    Busca la venta en t-periodo, t-2·periodo, ... Si no existe y
    ``fallback_lag1`` es verdadero, usa la venta anterior (rezago 1).
    No encadena pronósticos inventados: la fuente son las ventas.
    """
    n = len(actual)
    out: list[float | None] = [None] * n
    for i in range(n):
        val = None
        if period >= 1:
            j = i - period
            while j >= 0:
                if np.isfinite(actual[j]):
                    val = float(actual[j])
                    break
                j -= period
        if val is None and fallback_lag1:
            j = i - 1
            while j >= 0:
                if np.isfinite(actual[j]):
                    val = float(actual[j])
                    break
                j -= 1
        out[i] = val
    return out


def _linear_interpolate(values: np.ndarray) -> np.ndarray:
    series = pd.Series(values, dtype=float)
    return series.interpolate(method="linear", limit_area="inside").to_numpy(dtype=float)


def _positive_anchor(actual: np.ndarray, forecast: np.ndarray) -> np.ndarray:
    """Último valor estrictamente positivo de venta o pronóstico, arrastrado."""
    out = np.full(len(actual), np.nan, dtype=float)
    last = np.nan
    for i in range(len(actual)):
        if np.isfinite(actual[i]) and actual[i] > _ZERO_EPS:
            last = float(actual[i])
        elif np.isfinite(forecast[i]) and forecast[i] > _ZERO_EPS:
            last = float(forecast[i])
        out[i] = last
    return out


def _intermittency(actual: np.ndarray) -> tuple[bool, float, float]:
    """ADI = n / n_positivos. Intermitente si ADI >= 1.32 y hay muchos ceros.

    Muchos ceros: al menos dos ceros y una proporción de ceros >= 0.20.
    Los huecos (NaN) no cuentan como ceros.
    """
    y = np.asarray(actual, dtype=float)
    y = y[np.isfinite(y)]
    if y.size < 3:
        return False, float("nan"), 0.0
    n_pos = int(np.sum(y > _ZERO_EPS))
    n_zero = int(np.sum(np.abs(y) <= _ZERO_EPS))
    if n_pos == 0:
        return False, float("inf"), 1.0
    adi = float(y.size / n_pos)
    zero_ratio = float(n_zero / y.size)
    many_zeros = n_zero >= 2 and zero_ratio >= 0.20
    return bool(adi >= _ADI_THRESHOLD and many_zeros), adi, zero_ratio


def _winsorize_outliers(
    corrected: np.ndarray,
    notes: list[list[str]],
    skip_idx: set[int] | None = None,
) -> int:
    idx = np.flatnonzero(np.isfinite(corrected))
    if idx.size < 3:
        return 0
    skip_idx = skip_idx or set()
    x = corrected[idx]
    med = float(np.median(x))
    mad = float(np.median(np.abs(x - med)))
    if mad <= _MAD_EPS:
        z = np.zeros(idx.size, dtype=float)
        deviate = np.abs(x - med) > 1e-8
        direction = np.sign(x - med)
        z[deviate] = np.inf * direction[deviate]
        upper = med
        lower = 0.0
    else:
        z = _MOD_Z_CONST * (x - med) / mad
        upper = med + _MOD_Z * mad
        lower = max(0.0, med - _MOD_Z * mad)
    upper = max(0.0, float(upper))
    changed = 0
    for k, i in enumerate(idx):
        zi = float(z[k])
        if zi > _MOD_Z:
            new = upper
        elif zi < -_MOD_Z:
            new = lower
        else:
            continue
        if int(i) in skip_idx:
            continue
        # No recortar una temporada: el punto tiene que estar solo, lejos de la mediana
        # y lejos de sus vecinos. Si no, el z infinito (MAD = 0) aplana la estacionalidad.
        if _neighbor_supports_level(x, k, med):
            continue
        if abs(float(x[k]) - med) < max(1.0, 0.5 * abs(med)):
            continue
        new = _nonneg(new)
        if abs(new - corrected[i]) <= _DIFF_EPS:
            continue
        corrected[i] = new
        notes[i].append("Atípico winsorizado")
        changed += 1
    return changed


def _neighbor_supports_level(values: np.ndarray, index: int, center: float) -> bool:
    dev = float(values[index] - center)
    if abs(dev) <= _ZERO_EPS:
        return True
    for neighbor in (index - 1, index + 1):
        if neighbor < 0 or neighbor >= values.size or not np.isfinite(values[neighbor]):
            continue
        other = float(values[neighbor] - center)
        if dev * other > 0.0 and abs(other) >= 0.4 * abs(dev):
            return True
    return False


def _detect_tail_explosion(corrected: np.ndarray, actual: np.ndarray) -> dict[str, Any] | None:
    """Último punto > 5× la mediana anterior. ``blocked`` si las ventas saltan igual."""
    finite_idx = np.flatnonzero(np.isfinite(corrected))
    if finite_idx.size < 2:
        return None
    last_i = int(finite_idx[-1])
    prev = corrected[finite_idx[:-1]]
    prev = prev[np.isfinite(prev)]
    if prev.size == 0:
        return None
    med_prev = float(np.median(prev))
    last = float(corrected[last_i])
    # 5× solo tiene sentido con una mediana estrictamente positiva.
    if not (med_prev > _ZERO_EPS and last > 5.0 * med_prev):
        return None
    k = min(6, int(finite_idx.size - 1))
    return {
        "index": last_i,
        "blocked": _actuals_show_jump(actual),
        "k": k,
        "old": last,
    }


def _apply_tail_explosion(
    corrected: np.ndarray,
    notes: list[list[str]],
    tail: dict[str, Any],
) -> tuple[float, float, int] | None:
    finite_idx = np.flatnonzero(np.isfinite(corrected))
    if finite_idx.size < 2:
        return None
    k = int(tail["k"])
    window = corrected[finite_idx[-(k + 1) : -1]]
    window = window[np.isfinite(window)]
    if window.size == 0:
        return None
    new = _nonneg(float(np.median(window)))
    last_i = int(tail["index"])
    old = float(corrected[last_i])
    if abs(new - old) <= _DIFF_EPS:
        return None
    corrected[last_i] = new
    notes[last_i].append("Explosión final reemplazada por la mediana reciente")
    return old, new, k


def _actuals_show_jump(actual: np.ndarray) -> bool:
    y = np.asarray(actual, dtype=float)
    y = y[np.isfinite(y)]
    if y.size < 2:
        return False
    last = float(y[-1])
    med = float(np.median(y[:-1]))
    return bool(last > 3.0 * med)


def _replace_all_zero(
    corrected: np.ndarray,
    actual: np.ndarray,
    observed: np.ndarray,
    notes: list[list[str]],
    kind: str,
) -> str:
    """Devuelve 'replaced', 'unrepairable' o 'no'."""
    if not observed.any():
        return "no"
    observed_vals = corrected[observed]
    if not np.all(np.isfinite(observed_vals) & (np.abs(observed_vals) <= _ZERO_EPS)):
        return "no"
    actual_finite = actual[np.isfinite(actual)]
    if actual_finite.size == 0:
        return "unrepairable"
    if float(np.mean(actual_finite)) <= 0.0:
        return "no"
    period = _SEASON[kind]
    projected = _seasonal_naive_from_actuals(actual, period, fallback_lag1=True)
    changed_any = False
    for i in range(len(corrected)):
        val = projected[i]
        if val is None or not np.isfinite(val):
            new = 0.0
        else:
            new = _nonneg(val)
        if abs(float(corrected[i]) - new) <= _DIFF_EPS and np.isfinite(corrected[i]):
            continue
        corrected[i] = new
        notes[i] = ["Pronóstico en ceros reemplazado por naive estacional"]
        changed_any = True
    return "replaced" if changed_any else "no"


def _replace_flat_with_holt(
    corrected: np.ndarray,
    actual: np.ndarray,
    observed: np.ndarray,
    notes: list[list[str]],
) -> int:
    if int(observed.sum()) < 6:
        return 0
    observed_vals = corrected[observed]
    if not np.all(np.isfinite(observed_vals)):
        return 0
    unique = np.unique(np.round(observed_vals.astype(float), 6))
    if unique.size != 1:
        return 0
    y = actual[np.isfinite(actual)]
    if y.size < 2 or not (_cv(y) > 0.15):
        return 0

    actual_idx = np.flatnonzero(np.isfinite(actual))
    last_actual_i = int(actual_idx[-1]) if actual_idx.size else -1
    if actual_idx.size == 0:
        future = np.ones(len(corrected), dtype=bool)
        origin = -1
    else:
        future = np.arange(len(corrected)) > last_actual_i
        origin = last_actual_i
    if not future.any():
        return 0

    if y.size >= 6:
        segment = _time_aligned_actuals(actual, int(actual_idx[0]), last_actual_i)
        fit = segment if segment.size >= 6 else y
    else:
        fit = _trailing_ma(y, 3)
    level, trend = _holt_level_trend(fit, _HOLT_ALPHA, _HOLT_BETA)

    changed = 0
    for i in np.flatnonzero(future):
        h = int(i - origin) if origin >= 0 else int(i + 1)
        if h < 1:
            continue
        yhat = level + h * trend
        yhat = _nonneg(yhat)
        if np.isfinite(corrected[i]) and abs(corrected[i] - yhat) <= _DIFF_EPS:
            continue
        corrected[i] = yhat
        notes[i] = ["Pronóstico plano reemplazado por Holt"]
        changed += 1
    return changed


def _time_aligned_actuals(actual: np.ndarray, first: int, last: int) -> np.ndarray:
    segment = actual[first : last + 1].astype(float).copy()
    if segment.size == 0:
        return segment
    if np.isfinite(segment).all():
        return segment
    filled = pd.Series(segment).interpolate(method="linear", limit_area="inside").to_numpy(dtype=float)
    # Bordes que la interpolación no cubre: se recortan si siguen vacíos.
    if not np.isfinite(filled).all():
        good = np.isfinite(filled)
        if good.any():
            filled = filled[good]
        else:
            return np.asarray([], dtype=float)
    return filled


def _trailing_ma(values: np.ndarray, window: int) -> np.ndarray:
    series = pd.Series(np.asarray(values, dtype=float))
    return series.rolling(window=window, min_periods=1).mean().to_numpy(dtype=float)


def _holt_level_trend(y: np.ndarray, alpha: float, beta: float) -> tuple[float, float]:
    """Holt lineal: nivel y tendencia al final de ``y``.

    l_t = alpha·y_t + (1-alpha)·(l_{t-1}+b_{t-1})
    b_t = beta·(l_t-l_{t-1}) + (1-beta)·b_{t-1}
    """
    series = np.asarray(y, dtype=float)
    series = series[np.isfinite(series)]
    if series.size == 0:
        return 0.0, 0.0
    level = float(series[0])
    trend = float(series[1] - series[0]) if series.size >= 2 else 0.0
    for t in range(1, series.size):
        prev_level = level
        level = alpha * float(series[t]) + (1.0 - alpha) * (prev_level + trend)
        trend = beta * (level - prev_level) + (1.0 - beta) * trend
        if not np.isfinite(level) or not np.isfinite(trend):
            return 0.0, 0.0
    return float(level), float(trend)


def _cv(values: np.ndarray) -> float:
    y = np.asarray(values, dtype=float)
    y = y[np.isfinite(y)]
    if y.size < 2:
        return 0.0
    mu = float(np.mean(y))
    sd = float(np.std(y, ddof=1))
    if abs(mu) <= _ZERO_EPS:
        return math.inf if sd > _ZERO_EPS else 0.0
    return sd / abs(mu)


def _round_if_integer_history(
    corrected: np.ndarray,
    actual: np.ndarray,
    notes: list[list[str]],
) -> int:
    y = actual[np.isfinite(actual)]
    if y.size == 0:
        return 0
    if not np.all(np.abs(y - np.round(y)) <= _INT_TOL):
        return 0
    changed = 0
    for i in range(len(corrected)):
        if not np.isfinite(corrected[i]):
            continue
        new = _nonneg(float(np.floor(corrected[i] + 0.5 + 1e-10)))
        if abs(new - float(corrected[i])) <= _DIFF_EPS:
            continue
        corrected[i] = new
        notes[i].append("Redondeado a entero")
        changed += 1
    return changed


def _sanitize_finite(corrected: np.ndarray, notes: list[list[str]]) -> None:
    for i in range(len(corrected)):
        val = float(corrected[i])
        if np.isfinite(val) and val > 0:
            corrected[i] = val
            continue
        corrected[i] = 0.0
        if np.isfinite(val) and abs(val) <= _DIFF_EPS:
            continue
        if not any("negativ" in part.lower() or "no finito" in part.lower() for part in notes[i]):
            notes[i].append("Valor no finito o negativo ajustado a 0")


# ---------------------------------------------------------------------------
# Comparación y formato
# ---------------------------------------------------------------------------


def _count_changed(forecast: pd.Series, corrected: pd.Series) -> int:
    total = 0
    for f_val, c_val in zip(forecast, corrected):
        if _values_differ(f_val, c_val):
            total += 1
    return total


def _values_differ(forecast: Any, corrected: Any) -> bool:
    f_null = _nullish(forecast)
    c_null = _nullish(corrected)
    if f_null and c_null:
        return False
    if f_null != c_null:
        return True
    return abs(float(forecast) - float(corrected)) > _DIFF_EPS


def _nullish(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, (str, bytes)):
        return False
    if isinstance(value, (bool, np.bool_)):
        return False
    try:
        if isinstance(value, (float, np.floating, int, np.integer)):
            return not np.isfinite(float(value)) if isinstance(value, (float, np.floating)) else False
        if pd.isna(value):
            return True
    except (TypeError, ValueError):
        return False
    return False


def _json_number(value: Any) -> float | None:
    if _nullish(value):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return number


def _iso_date(value: Any) -> str:
    ts = pd.Timestamp(value)
    if pd.isna(ts):
        return ""
    ts = ts.tz_convert("UTC").tz_localize(None) if ts.tzinfo is not None else ts
    if ts.normalize() == ts:
        return ts.strftime("%Y-%m-%d")
    return ts.isoformat()


def _fmt(value: float) -> str:
    if not np.isfinite(value):
        return "0"
    if abs(value - round(value)) < 1e-6:
        return str(int(round(value)))
    text = f"{value:.4f}".rstrip("0").rstrip(".")
    return text or "0"


def _nonneg(value: float) -> float:
    if value is None or not np.isfinite(value) or value <= 0:
        return 0.0
    return float(value)
