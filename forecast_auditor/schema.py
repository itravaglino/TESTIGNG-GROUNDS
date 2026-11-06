"""Lectura de CSV/XLSX y detección de columnas en español o inglés."""

from __future__ import annotations

import io
from typing import Any

import pandas as pd

MAX_BYTES = 8 * 1024 * 1024
MAX_ROWS = 200_000

COLUMN_ALIASES: dict[str, set[str]] = {
    "product": {
        "producto", "product", "sku", "item", "articulo", "artículo", "codigo",
        "código", "code", "product_id", "id_producto", "descripcion", "descripción",
        "material", "ean",
    },
    "date": {
        "fecha", "date", "periodo", "período", "period", "semana", "week", "mes",
        "month", "dia", "día", "day", "timestamp", "ds",
    },
    "forecast": {
        "forecast", "pronostico", "pronóstico", "prediccion", "predicción", "fcst",
        "yhat", "forecast_qty", "qty_forecast", "pronostico_qty", "forecast_unidades",
        "unidades_pronosticadas", "prediccion_demanda",
    },
    "actual": {
        "actual", "real", "venta", "ventas", "demanda", "demand", "y", "actual_qty",
        "qty", "unidades", "sell_out", "sellout", "consumo", "historico", "histórico",
    },
    "model": {
        "modelo", "model", "algoritmo", "algorithm", "metodo", "método", "origen",
    },
    "lower": {
        "lower", "limite_inf", "límite_inf", "limite_inferior", "límite_inferior",
        "q10", "p10", "forecast_lower", "lo", "minimo", "mínimo",
    },
    "upper": {
        "upper", "limite_sup", "límite_sup", "limite_superior", "límite_superior",
        "q90", "p90", "forecast_upper", "hi", "maximo", "máximo",
    },
}


class SchemaError(ValueError):
    pass


def _norm_col(name: object) -> str:
    text = str(name).strip().lower().replace("-", "_").replace(" ", "_")
    for ch in "áéíóúüñ":
        text = text.replace(ch, {"á": "a", "é": "e", "í": "i", "ó": "o", "ú": "u", "ü": "u", "ñ": "n"}[ch])
    return text


def _looks_like(column: str, kind: str) -> bool:
    return _norm_col(column) in COLUMN_ALIASES[kind]


def parse_numbers(series: pd.Series) -> pd.Series:
    if pd.api.types.is_numeric_dtype(series):
        return pd.to_numeric(series, errors="coerce")
    text = series.astype(str).str.strip()
    text = text.replace({"": pd.NA, "nan": pd.NA, "None": pd.NA, "none": pd.NA, "-": pd.NA})
    text = text.str.replace("\u00a0", "", regex=False).str.replace(" ", "", regex=False)
    return text.map(_parse_number)


def _parse_number(value):
    if value is pd.NA or value is None:
        return float("nan")
    text = str(value).strip()
    if text.lower() in {"", "nan", "none", "-"}:
        return float("nan")
    if "," in text and "." in text:
        if text.rfind(",") > text.rfind("."):
            text = text.replace(".", "").replace(",", ".")
        else:
            text = text.replace(",", "")
    elif "," in text:
        text = text.replace(",", ".")
    try:
        return float(text)
    except ValueError:
        return float("nan")


def read_table(filename: str, content: bytes) -> pd.DataFrame:
    if len(content) > MAX_BYTES:
        raise SchemaError(f"El archivo supera el límite de {MAX_BYTES // (1024 * 1024)} MB.")
    name = (filename or "").lower()
    if name.endswith(".xlsx"):
        frame = pd.read_excel(io.BytesIO(content), engine="openpyxl")
    elif name.endswith(".xls"):
        raise SchemaError("Guardá el Excel como .xlsx. El formato .xls viejo no se lee.")
    elif name.endswith(".csv") or name.endswith(".txt") or not name:
        text = _decode_text(content)
        frame = pd.read_csv(io.StringIO(text), sep=None, engine="python")
    else:
        raise SchemaError("Formato no reconocido. Usá CSV o XLSX.")
    if len(frame) > MAX_ROWS:
        raise SchemaError(f"El archivo tiene más de {MAX_ROWS:,} filas.".replace(",", "."))
    if frame.empty:
        raise SchemaError("El archivo no tiene filas.")
    return frame


def normalize_frame(frame: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, Any]]:
    warnings: list[str] = []
    assigned: dict[str, str] = {}
    for kind in ("product", "date", "forecast", "actual", "model", "lower", "upper"):
        for column in frame.columns:
            if column in assigned.values():
                continue
            if _looks_like(str(column), kind):
                assigned[kind] = column
                break
    if "product" not in assigned or "date" not in assigned or "forecast" not in assigned:
        found = ", ".join(str(c) for c in frame.columns)
        raise SchemaError(
            "No encontré las columnas obligatorias: producto, fecha y pronóstico. "
            f"Columnas del archivo: {found}."
        )

    out = pd.DataFrame({
        "product": frame[assigned["product"]].astype(str).str.strip(),
        "date": parse_dates(frame[assigned["date"]]),
        "forecast": parse_numbers(frame[assigned["forecast"]]),
    })
    if "actual" in assigned:
        out["actual"] = parse_numbers(frame[assigned["actual"]])
    else:
        out["actual"] = np_nan()
        warnings.append("No hay columna de demanda real. Solo puedo auditar la sanidad del pronóstico, no su precisión.")
    if "model" in assigned:
        out["model"] = frame[assigned["model"]].astype(str).str.strip().replace({"nan": "", "None": ""})
    else:
        out["model"] = ""
    if "lower" in assigned:
        out["lower"] = parse_numbers(frame[assigned["lower"]])
    else:
        out["lower"] = np_nan()
    if "upper" in assigned:
        out["upper"] = parse_numbers(frame[assigned["upper"]])
    else:
        out["upper"] = np_nan()

    before = len(out)
    out = out[out["product"].ne("") & out["product"].ne("nan")]
    dropped_product = before - len(out)
    bad_dates = int(out["date"].isna().sum())
    out = out.dropna(subset=["date"])
    if dropped_product:
        warnings.append(f"Se ignoraron {dropped_product} filas sin producto.")
    if bad_dates:
        warnings.append(f"Se ignoraron {bad_dates} filas con fecha ilegible.")
    if out.empty:
        raise SchemaError("Después de leer fechas y productos no quedó ninguna fila útil.")

    out["date"] = out["date"].dt.tz_localize(None)
    out = out.sort_values(["product", "model", "date"])
    dup_mask = out.duplicated(["product", "model", "date"], keep=False)
    dup_count = int(dup_mask.sum())
    if dup_count:
        warnings.append(
            f"Había {dup_count} filas en claves producto-modelo-fecha repetidas. Me quedo con la última."
        )
        out = out.drop_duplicates(["product", "model", "date"], keep="last")
    out = out.reset_index(drop=True)
    meta = {
        "columns": {kind: assigned.get(kind) for kind in ("product", "date", "forecast", "actual", "model", "lower", "upper")},
        "warnings": warnings,
        "rows": int(len(out)),
        "duplicate_rows": dup_count,
    }
    return out, meta


def np_nan():
    return float("nan")


def _decode_text(content: bytes) -> str:
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        return content.decode("cp1252")
    if "\ufffd" in text:
        return content.decode("cp1252")
    return text


def parse_dates(series: pd.Series) -> pd.Series:
    if pd.api.types.is_datetime64_any_dtype(series):
        parsed = pd.to_datetime(series)
        try:
            if getattr(parsed.dt, "tz", None) is not None:
                return parsed.dt.tz_convert(None)
        except (AttributeError, TypeError):
            return pd.to_datetime(parsed, errors="coerce", utc=True).dt.tz_localize(None)
        return parsed
    numeric = pd.to_numeric(series, errors="coerce")
    if numeric.notna().mean() > 0.8:
        serial = numeric.where((numeric > 20000) & (numeric < 80000))
        return pd.to_datetime(serial, unit="D", origin="1899-12-30", errors="coerce")
    parsed = pd.to_datetime(series, errors="coerce", dayfirst=True, format="mixed")
    try:
        if getattr(parsed.dt, "tz", None) is not None:
            return parsed.dt.tz_convert(None)
    except (AttributeError, TypeError):
        return pd.to_datetime(parsed, errors="coerce", utc=True).dt.tz_localize(None)
    return parsed
