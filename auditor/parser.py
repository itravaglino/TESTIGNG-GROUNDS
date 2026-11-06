"""Demand-forecast file loader.

Public API:
    load_bytes(filename, data) -> dict
    canonical_template_csv() -> str

Only pandas, numpy, and the standard library are imported. Excel .xlsx is read
through pandas (openpyxl). Legacy .xls (BIFF8 / OLE) is parsed directly so the
loader does not need xlrd or calamine.
"""

from __future__ import annotations

import csv
import io
import math
import re
import struct
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timedelta
from html.parser import HTMLParser
from typing import Any, Iterable, Literal, Sequence

import numpy as np
import pandas as pd

Frequency = Literal["D", "W", "M", "Q", "Y", "irregular"]
Layout = Literal["long", "wide"]

OUTPUT_COLUMNS: tuple[str, ...] = (
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

# Canonical field -> alias -> preference weight (higher wins among realized cols).
_PRODUCT_ID_STRONG: dict[str, int] = {
    "sku": 100,
    "codigo": 98,
    "producto_id": 97,
    "ean": 90,
    "material": 88,
    "cod": 86,
    "item": 84,
    "id": 80,
}
_PRODUCT_ID_CONDITIONAL: dict[str, int] = {
    "producto": 70,
    "product": 68,
}
_PRODUCT_NAME: dict[str, int] = {
    "product_name": 100,
    "descripcion": 96,
    "articulo": 90,
    "nombre": 88,
    "desc": 80,
}
_CATEGORY: dict[str, int] = {
    "categoria": 100,
    "category": 96,
    "familia": 90,
    "rubro": 88,
    "linea": 86,
    "grupo": 80,
}
_LOCATION: dict[str, int] = {
    "sucursal": 100,
    "location": 96,
    "tienda": 94,
    "deposito": 92,
    "almacen": 90,
    "canal": 88,
    "region": 86,
    "plaza": 84,
    "cd": 80,
}
_DATE: dict[str, int] = {
    "fecha": 100,
    "date": 96,
    "periodo": 94,
    "semana": 84,
    "mes": 82,
    "dia": 80,
}
_FORECAST: dict[str, int] = {
    "budget_fcst": 100,
    "pronostico": 98,
    "prediccion": 96,
    "prevision": 94,
    "forecast": 92,
    "yhat": 88,
    "fcst": 86,
    "pred": 80,
}
_ACTUAL_PREFERRED: dict[str, int] = {
    "actual": 100,
    "real": 96,
    "venta": 94,
    "ventas": 94,
    "demanda": 92,
    "demand": 90,
    "unidades": 78,
    "units": 76,
    "sell_out": 74,
    "sellout": 74,
    "y": 60,
}
_HISTORY: dict[str, int] = {
    "historico": 40,
    "historia": 38,
}
_MODEL: dict[str, int] = {
    "algoritmo": 100,
    "modelo": 96,
    "metodo": 90,
    "model": 88,
}
_HORIZON: dict[str, int] = {
    "horizonte": 100,
    "horizon": 96,
    "lead": 90,
    "h": 70,
}

_FIELD_ALIASES: dict[str, dict[str, int]] = {
    "product_id": _PRODUCT_ID_STRONG,
    "product_name": _PRODUCT_NAME,
    "category": _CATEGORY,
    "location": _LOCATION,
    "date": _DATE,
    "forecast": _FORECAST,
    "actual": {**_ACTUAL_PREFERRED, **_HISTORY},
    "model_name": _MODEL,
    "horizon": _HORIZON,
}

# Tie-break when two fields score a header equally: higher wins.
_FIELD_PRIORITY: dict[str, int] = {
    "product_id": 90,
    "date": 80,
    "forecast": 70,
    "actual": 68,
    "product_name": 60,
    "horizon": 50,
    "model_name": 40,
    "location": 30,
    "category": 20,
}

_FORECAST_NAMES = set(_FORECAST)
_ACTUAL_NAMES = set(_ACTUAL_PREFERRED) | set(_HISTORY)
_MEASURE_FORECAST = _FORECAST_NAMES | {"presupuesto", "ppto", "budget", "proyeccion"}
_MEASURE_ACTUAL = _ACTUAL_NAMES | {"realizado"}
_MEASURE_HEADERS = {
    "tipo",
    "medida",
    "metrica",
    "metric",
    "variable",
    "serie",
    "escenario",
    "valores",
    "valor",
    "tipo_dato",
    "clase",
}

_MONTHS: dict[str, int] = {
    "enero": 1,
    "ene": 1,
    "january": 1,
    "jan": 1,
    "febrero": 2,
    "feb": 2,
    "february": 2,
    "marzo": 3,
    "mar": 3,
    "march": 3,
    "abril": 4,
    "abr": 4,
    "april": 4,
    "apr": 4,
    "mayo": 5,
    "may": 5,
    "junio": 6,
    "jun": 6,
    "june": 6,
    "julio": 7,
    "jul": 7,
    "july": 7,
    "agosto": 8,
    "ago": 8,
    "august": 8,
    "aug": 8,
    "septiembre": 9,
    "setiembre": 9,
    "sept": 9,
    "sep": 9,
    "september": 9,
    "octubre": 10,
    "oct": 10,
    "october": 10,
    "noviembre": 11,
    "nov": 11,
    "november": 11,
    "diciembre": 12,
    "dic": 12,
    "december": 12,
    "dec": 12,
}
_MON_ALT = "|".join(sorted(_MONTHS, key=len, reverse=True))

_TIME_SUFFIX = re.compile(
    r"(?:[t ]\d{1,2}:\d{2}(?::\d{2})?(?:\.\d+)?)(?:\s*(?:z|[+-]\d{2}:?\d{2}))?$",
    re.IGNORECASE,
)
_RE_YMD = re.compile(r"^(\d{4})[\s\-/\._]+(\d{1,2})[\s\-/\._]+(\d{1,2})$")
_RE_DMY = re.compile(r"^(\d{1,2})[\s\-/\._]+(\d{1,2})[\s\-/\._]+(\d{2,4})$")
_RE_YM = re.compile(r"^(\d{4})[\s\-/\._]+(\d{1,2})$")
_RE_MY = re.compile(r"^(\d{1,2})[\s\-/\._]+(\d{4})$")
_RE_COMPACT8 = re.compile(r"^(\d{4})(\d{2})(\d{2})$")
_RE_COMPACT6 = re.compile(r"^(\d{4})(\d{2})$")
_RE_M = re.compile(r"^m[\s\-/\._]*(\d{4})[\s\-/\._]+(\d{1,2})$|^m(\d{4})(\d{2})$")
_RE_YW = re.compile(r"^(\d{4})[\s\-/\._]*w[\s\-/\._]*(\d{1,2})$")
_RE_WY = re.compile(r"^w[\s\-/\._]*(\d{1,2})[\s\-/\._]*(\d{4})$")
_RE_SEM_Y = re.compile(r"^sem(?:ana)?[\s\-/\._]+(\d{4})[\s\-/\._]+(\d{1,2})$")
_RE_SEM_W = re.compile(r"^sem(?:ana)?[\s\-/\._]+(\d{1,2})[\s\-/\._]+(\d{4})$")
_RE_Y_SEM = re.compile(r"^(\d{4})[\s\-/\._]+sem(?:ana)?[\s\-/\._]+(\d{1,2})$")
_RE_MES_Y = re.compile(r"^mes[\s\-/\._]+(\d{4})[\s\-/\._]+(\d{1,2})$")
_RE_MES_M = re.compile(r"^mes[\s\-/\._]+(\d{1,2})[\s\-/\._]+(\d{4})$")
_RE_YQ = re.compile(r"^(\d{4})[\s\-/\._]*[qt][\s\-/\._]*([1-4])$")
_RE_QY = re.compile(r"^[qt][\s\-/\._]*([1-4])[\s\-/\._]*(\d{4})$")
_RE_TRIM = re.compile(r"^(?:trimestre|trim)[\s\-/\._]*([1-4])[\s\-/\._]*(\d{4})$")
_RE_YTRIM = re.compile(r"^(\d{4})[\s\-/\._]*(?:trimestre|trim)[\s\-/\._]*([1-4])$")
_RE_MON_Y = re.compile(rf"^({_MON_ALT})[\s\-/\._]+(\d{{2}}|\d{{4}})$")
_RE_Y_MON = re.compile(rf"^(\d{{4}})[\s\-/\._]+({_MON_ALT})$")
_RE_D_DE_MON = re.compile(rf"^(\d{{1,2}})\s+de\s+({_MON_ALT})\s+de\s+(\d{{4}})$")
_RE_D_MON_Y = re.compile(
    rf"^(\d{{1,2}})[\s\-/\._]+({_MON_ALT})[\s\-/\._]+(\d{{2}}|\d{{4}})$"
)
_RE_MON_D_Y = re.compile(
    rf"^({_MON_ALT})[\s\-/\._]+(\d{{1,2}})[\s\-/\._,]+(\d{{2}}|\d{{4}})$"
)
_RE_BARE_YEAR = re.compile(r"^(?:19|20)\d{2}$")
_RE_FY = re.compile(r"^(?:fy|ano|year)[\s\-/\._]?((?:19|20)\d{2})$")

_MISSING_NUMBERS = {
    "",
    "-",
    "—",
    "–",
    "n/a",
    "na",
    "null",
    "none",
    "nan",
    "#n/a",
    "#n/d",
    "#na",
    "#valor!",
    "#value!",
    "nd",
    "n/d",
    "s/d",
    "s/i",
    ".",
    ",",
    "na.",
    "n.a.",
    "n.d.",
    "null.",
}

_VALUE_PREFIXES: list[tuple[str, str]] = sorted(
    [(name, "forecast") for name in _MEASURE_FORECAST]
    + [(name, "actual") for name in _MEASURE_ACTUAL],
    key=lambda item: len(item[0]),
    reverse=True,
)

_XLSX_EXT = {"xlsx", "xlsm", "xltx", "xltm"}
_ENDOFCHAIN = 0xFFFFFFFE
_FREESECT = 0xFFFFFFFF
_NOSTREAM = 0xFFFFFFFF


@dataclass
class PeriodCol:
    index: int
    header: str
    explicit_kind: str | None
    date: datetime
    resolved_kind: str


@dataclass
class MappedColumns:
    columns: dict[str, int]
    aliases: dict[str, str]
    headers: dict[str, str]
    extra_actual: list[tuple[int, str, str]]
    extra_forecast: list[tuple[int, str, str]]
    extra_date: list[tuple[int, str, str]]
    periods: list[PeriodCol]
    shared_name_and_id: bool
    id_from_name_only: bool


def canonical_template_csv() -> str:
    """Long-format Spanish CSV: two products, January–June 2024."""
    rows = [
        "codigo,descripcion,categoria,sucursal,fecha,pronostico,venta,modelo,horizonte",
        "SKU-100,Yerba mate 1kg,Bebidas,Buenos Aires,2024-01-01,100,98,promedio,1",
        "SKU-100,Yerba mate 1kg,Bebidas,Buenos Aires,2024-02-01,110,105,promedio,1",
        "SKU-100,Yerba mate 1kg,Bebidas,Buenos Aires,2024-03-01,120,119,promedio,1",
        "SKU-100,Yerba mate 1kg,Bebidas,Buenos Aires,2024-04-01,130,128,promedio,1",
        "SKU-100,Yerba mate 1kg,Bebidas,Buenos Aires,2024-05-01,140,141,promedio,1",
        "SKU-100,Yerba mate 1kg,Bebidas,Buenos Aires,2024-06-01,150,149,promedio,1",
        "SKU-200,Café molido 500g,Bebidas,Córdoba,2024-01-01,80,77,promedio,1",
        "SKU-200,Café molido 500g,Bebidas,Córdoba,2024-02-01,85,84,promedio,1",
        "SKU-200,Café molido 500g,Bebidas,Córdoba,2024-03-01,90,88,promedio,1",
        "SKU-200,Café molido 500g,Bebidas,Córdoba,2024-04-01,95,96,promedio,1",
        "SKU-200,Café molido 500g,Bebidas,Córdoba,2024-05-01,100,99,promedio,1",
        "SKU-200,Café molido 500g,Bebidas,Córdoba,2024-06-01,105,103,promedio,1",
    ]
    return "\n".join(rows) + "\n"


def load_bytes(filename: str, data: bytes) -> dict[str, Any]:
    """Load a forecast extract from raw file bytes.

    Returns a dict with ``frame``, ``frequency``, ``warnings``, ``column_map``,
    ``source_name`` and ``layout`` (``long`` or ``wide``).
    """
    source_name = "" if filename is None else str(filename)
    if isinstance(data, str):
        data = data.encode("utf-8")
    elif isinstance(data, (bytearray, memoryview)):
        data = bytes(data)
    elif not isinstance(data, bytes):
        raise ValueError("El contenido del archivo debe ser bytes.")
    if len(data) == 0:
        raise ValueError("El archivo está vacío.")

    grids, delimiter = _read_grids(source_name, data)
    if not grids or all(not rows for _, rows in grids):
        raise ValueError("El archivo está vacío.")

    warnings: list[str] = []
    chosen_name, chosen_rows, ignored = _select_grid(grids)
    if ignored:
        extra = ", ".join(f"'{name}'" for name in ignored)
        warnings.append(
            f"Se leyó la hoja '{chosen_name}' y se ignoraron otras hojas con datos: {extra}."
        )

    result = _grid_to_result(chosen_rows, delimiter, warnings)
    result["source_name"] = source_name
    result["warnings"] = _dedupe(warnings)
    return result


# ---------------------------------------------------------------------------
# Text helpers
# ---------------------------------------------------------------------------


def _dedupe(items: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for item in items:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out


def _strip_accents(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def _norm_header(text: str) -> str:
    cleaned = _strip_accents(str(text)).lower().strip()
    cleaned = cleaned.replace("\ufeff", "").replace("\u200b", "")
    cleaned = cleaned.replace("\n", " ").replace("\r", " ")
    cleaned = re.sub(r"[:*#]+$", "", cleaned.strip())
    cleaned = re.sub(r"[^a-z0-9]+", "_", cleaned)
    return cleaned.strip("_")


def _clean_cell(value: str) -> str:
    text = str(value).replace("\ufeff", "").replace("\u200b", "")
    text = text.replace("\xa0", " ").replace("\u2007", " ")
    return text.strip()


def _extension(filename: str) -> str:
    base = filename.replace("\\", "/").rstrip("/").split("/")[-1]
    if "." not in base:
        return ""
    return base.rsplit(".", 1)[-1].lower().strip()


def _alias_match(header_norm: str, alias: str) -> int:
    """Return a score for a bounded alias match, or 0."""
    if not header_norm or not alias:
        return 0
    if header_norm == alias:
        return 300 + len(alias)
    if f"_{alias}_" in f"_{header_norm}_":
        return 150 + len(alias)
    return 0


def _score_fields(header: str, *, allow_conditional_id: bool) -> dict[str, tuple[int, str | None]]:
    norm = _norm_header(header)
    scores: dict[str, tuple[int, str | None]] = {}
    for field, aliases in _FIELD_ALIASES.items():
        best = 0
        best_alias: str | None = None
        for alias, weight in aliases.items():
            matched = _alias_match(norm, alias)
            if matched <= 0:
                continue
            # Keep the weight as a tie-break inside the match class.
            score = matched + weight / 1000.0
            if score > best:
                best = score
                best_alias = alias
        scores[field] = (best, best_alias)
    if allow_conditional_id and norm:
        cond = 0.0
        cond_alias: str | None = None
        for alias, weight in _PRODUCT_ID_CONDITIONAL.items():
            matched = _alias_match(norm, alias)
            if matched <= 0:
                continue
            score = matched + weight / 1000.0
            if score > cond:
                cond = score
                cond_alias = alias
        current = scores["product_id"][0]
        if cond > current and cond_alias is not None:
            scores["product_id"] = (cond, cond_alias)
    return scores


def _header_points(cell: str) -> int:
    if not str(cell).strip():
        return 0
    _kind, parsed = _split_value_period(cell)
    if parsed is not None:
        return 2
    scores = _score_fields(cell, allow_conditional_id=True)
    if any(score > 0 for score, _alias in scores.values()):
        return 3
    return 0


def _is_value_type_label(cell: str) -> bool:
    norm = _norm_header(cell)
    if not norm:
        return False
    if norm in _MEASURE_FORECAST or norm in _MEASURE_ACTUAL:
        return True
    tokens = [tok for tok in norm.split("_") if tok and tok not in {"de", "del", "la", "el", "los", "las"}]
    if not tokens:
        return False
    known = _MEASURE_FORECAST | _MEASURE_ACTUAL
    if all(tok in known or tok in {"de", "unidades", "units"} for tok in tokens) and any(
        tok in known for tok in tokens
    ):
        return True
    return False


def _classify_measure(value: str) -> str | None:
    norm = _norm_header(value)
    if not norm:
        return None
    if norm in _MEASURE_FORECAST:
        return "forecast"
    if norm in _MEASURE_ACTUAL:
        return "actual"
    tokens = [tok for tok in norm.split("_") if tok]
    has_f = any(tok in _MEASURE_FORECAST for tok in tokens)
    has_a = any(tok in _MEASURE_ACTUAL for tok in tokens)
    if has_f and not has_a:
        return "forecast"
    if has_a and not has_f:
        return "actual"
    return None


# ---------------------------------------------------------------------------
# Dates
# ---------------------------------------------------------------------------


def _expand_year(year: int) -> int:
    if year >= 100:
        return year
    return 2000 + year if year < 70 else 1900 + year


def _valid_year(year: int) -> bool:
    return 1970 <= year <= 2100


def _valid_ymd(year: int, month: int, day: int) -> bool:
    if not _valid_year(year) or not 1 <= month <= 12 or not 1 <= day <= 31:
        return False
    try:
        datetime(year, month, day)
    except ValueError:
        return False
    return True


def _month_start(year: int, month: int) -> datetime | None:
    if not _valid_year(year) or not 1 <= month <= 12:
        return None
    return datetime(year, month, 1)


def _quarter_start(year: int, quarter: int) -> datetime | None:
    if quarter < 1 or quarter > 4:
        return None
    return _month_start(year, (quarter - 1) * 3 + 1)


def _week_start(year: int, week: int) -> datetime | None:
    if not _valid_year(year) or not 1 <= week <= 53:
        return None
    try:
        return datetime.fromisocalendar(year, week, 1)
    except ValueError:
        return None


def _preprocess_date_text(text: str) -> str:
    cleaned = _strip_accents(str(text)).strip().lower()
    cleaned = cleaned.replace("\u00a0", " ").replace("\u200b", "")
    cleaned = re.sub(r"\s+", " ", cleaned)
    cleaned = _TIME_SUFFIX.sub("", cleaned).strip()
    return cleaned


def _parse_period(text: str, *, allow_bare_year: bool = False) -> datetime | None:
    raw = _preprocess_date_text(text)
    if not raw:
        return None
    if not re.search(r"\d", raw) and not allow_bare_year:
        return None

    match = _RE_FY.match(raw)
    if match:
        year = int(match.group(1))
        if _valid_year(year):
            return datetime(year, 1, 1)

    match = _RE_YW.match(raw)
    if match:
        return _week_start(int(match.group(1)), int(match.group(2)))
    match = _RE_WY.match(raw)
    if match:
        return _week_start(int(match.group(2)), int(match.group(1)))
    match = _RE_SEM_Y.match(raw) or _RE_Y_SEM.match(raw)
    if match:
        return _week_start(int(match.group(1)), int(match.group(2)))
    match = _RE_SEM_W.match(raw)
    if match:
        return _week_start(int(match.group(2)), int(match.group(1)))

    match = _RE_YQ.match(raw) or _RE_YTRIM.match(raw)
    if match:
        return _quarter_start(int(match.group(1)), int(match.group(2)))
    match = _RE_QY.match(raw)
    if match:
        return _quarter_start(int(match.group(2)), int(match.group(1)))
    match = _RE_TRIM.match(raw)
    if match:
        return _quarter_start(int(match.group(2)), int(match.group(1)))

    match = _RE_M.match(raw)
    if match:
        year = int(match.group(1) or match.group(3))
        month = int(match.group(2) or match.group(4))
        return _month_start(year, month)

    match = _RE_D_DE_MON.match(raw)
    if match:
        year = _expand_year(int(match.group(3)))
        month = _MONTHS[match.group(2)]
        day = int(match.group(1))
        if _valid_ymd(year, month, day):
            return datetime(year, month, day)
        return None

    match = _RE_D_MON_Y.match(raw)
    if match:
        year = _expand_year(int(match.group(3)))
        month = _MONTHS[match.group(2)]
        day = int(match.group(1))
        if _valid_ymd(year, month, day):
            return datetime(year, month, day)
        return None

    match = _RE_MON_D_Y.match(raw)
    if match:
        year = _expand_year(int(match.group(3)))
        month = _MONTHS[match.group(1)]
        day = int(match.group(2))
        if _valid_ymd(year, month, day):
            return datetime(year, month, day)
        return None

    match = _RE_MON_Y.match(raw)
    if match:
        year = _expand_year(int(match.group(2)))
        return _month_start(year, _MONTHS[match.group(1)])
    match = _RE_Y_MON.match(raw)
    if match:
        return _month_start(int(match.group(1)), _MONTHS[match.group(2)])

    match = _RE_YMD.match(raw)
    if match:
        year, month, day = int(match.group(1)), int(match.group(2)), int(match.group(3))
        if _valid_ymd(year, month, day):
            return datetime(year, month, day)
        return None

    match = _RE_DMY.match(raw)
    if match:
        first, second, year = int(match.group(1)), int(match.group(2)), _expand_year(int(match.group(3)))
        if _valid_ymd(year, second, first):
            return datetime(year, second, first)
        if _valid_ymd(year, first, second):
            return datetime(year, first, second)
        return None

    match = _RE_COMPACT8.match(raw)
    if match:
        year, month, day = int(match.group(1)), int(match.group(2)), int(match.group(3))
        if _valid_ymd(year, month, day):
            return datetime(year, month, day)

    match = _RE_MES_Y.match(raw)
    if match:
        return _month_start(int(match.group(1)), int(match.group(2)))
    match = _RE_MES_M.match(raw)
    if match:
        return _month_start(int(match.group(2)), int(match.group(1)))

    match = _RE_YM.match(raw)
    if match:
        return _month_start(int(match.group(1)), int(match.group(2)))
    match = _RE_MY.match(raw)
    if match:
        return _month_start(int(match.group(2)), int(match.group(1)))

    match = _RE_COMPACT6.match(raw)
    if match:
        parsed = _month_start(int(match.group(1)), int(match.group(2)))
        if parsed is not None:
            return parsed

    if allow_bare_year and _RE_BARE_YEAR.match(raw):
        return datetime(int(raw), 1, 1)
    return None


def _excel_serial_to_datetime(serial: float, epoch_1904: bool = False) -> datetime | None:
    if not math.isfinite(serial):
        return None
    if epoch_1904:
        if serial < 0 or serial > 80000:
            return None
        base = datetime(1904, 1, 1)
        days = int(math.floor(serial))
        frac = serial - days
    else:
        if serial < 1 or serial > 80000:
            return None
        # Windows 1900 system, including the fictional 1900-02-29.
        base = datetime(1899, 12, 30)
        days = int(math.floor(serial))
        frac = serial - days
    try:
        stamp = base + timedelta(days=days)
    except OverflowError:
        return None
    if frac:
        seconds = int(round(frac * 86400))
        stamp += timedelta(seconds=seconds)
    return stamp.replace(hour=0, minute=0, second=0, microsecond=0)


def _parse_serial_text(text: str, epoch_1904: bool = False) -> datetime | None:
    token = text.strip().replace(",", ".")
    if not re.fullmatch(r"-?\d+(\.\d+)?", token):
        return None
    value = float(token)
    if epoch_1904:
        if not 0 <= value <= 80000:
            return None
    elif not 60 <= value <= 80000:
        return None
    # Reject values that are far more likely to be business numbers than dates
    # unless the column was already classified as a date. Callers gate this.
    return _excel_serial_to_datetime(value, epoch_1904=epoch_1904)


def _split_value_period(header: str) -> tuple[str | None, datetime | None]:
    original = _preprocess_date_text(header)
    if not original:
        return None, None
    spaced = re.sub(r"[_\s]+", " ", original).strip()
    for candidate in (original, spaced):
        parsed = _parse_period(candidate)
        if parsed is not None:
            return None, parsed
    variants = {original, spaced}
    for prefix, kind in _VALUE_PREFIXES:
        pref = prefix.replace("_", " ")
        for text in variants:
            if text == pref:
                continue
            if text.startswith(pref):
                rest = text[len(pref) :].lstrip(" _-:/").strip()
                parsed = _parse_period(rest) if rest else None
                if parsed is not None:
                    return kind, parsed
            if text.endswith(pref) and len(text) > len(pref) + 1:
                rest = text[: -len(pref)].rstrip(" _-:/").strip()
                # Avoid matching a prefix glued to the middle of a word.
                boundary = text[-(len(pref) + 1)]
                if boundary.isalnum():
                    continue
                parsed = _parse_period(rest) if rest else None
                if parsed is not None:
                    return kind, parsed
    return None, None


# ---------------------------------------------------------------------------
# Numbers
# ---------------------------------------------------------------------------


def _numeric_token(raw: str) -> str:
    text = str(raw).strip().lower()
    text = text.replace("\u00a0", "").replace(" ", "").replace("'", "").replace("’", "")
    text = text.replace("−", "-").replace("–", "-")
    text = re.sub(r"[€$£¥%]", "", text)
    if text.startswith("(") and text.endswith(")"):
        text = "-" + text[1:-1]
    if text.startswith("+"):
        text = text[1:]
    return text


def _detect_decimal_comma(samples: Iterable[str], delimiter: str | None) -> bool:
    euro = 0
    anglo = 0
    grouped_dots = 0
    for raw in samples:
        token = _numeric_token(raw)
        if not token or token in _MISSING_NUMBERS or not re.search(r"\d", token):
            continue
        signless = token[1:] if token.startswith("-") else token
        if re.fullmatch(r"\d{1,3}(\.\d{3})+,\d+", signless):
            euro += 2
        elif re.fullmatch(r"\d+,\d+", signless):
            frac = signless.split(",")[-1]
            if re.fullmatch(r"\d{1,3}(,\d{3})+", signless):
                anglo += 1
            elif len(frac) != 3:
                euro += 1
        elif re.fullmatch(r"\d{1,3}(,\d{3})+\.\d+", signless):
            anglo += 2
        elif re.fullmatch(r"\d+\.\d+", signless):
            anglo += 1
        elif re.fullmatch(r"\d{1,3}(,\d{3})+", signless):
            anglo += 1
        elif re.fullmatch(r"\d{1,3}(\.\d{3}){2,}", signless):
            euro += 1
            grouped_dots += 1
        elif re.fullmatch(r"\d{1,3}(\.\d{3})+", signless):
            grouped_dots += 1
    if euro > anglo:
        return True
    if anglo > euro:
        return False
    if delimiter == ";" and (euro > 0 or grouped_dots > 0):
        return True
    if grouped_dots > 0 and anglo == 0 and euro == 0 and delimiter == ";":
        return True
    return False


def _normalize_number(token: str, decimal_comma: bool) -> str:
    sign = ""
    if token.startswith("-"):
        sign = "-"
        token = token[1:]
    has_comma = "," in token
    has_dot = "." in token
    if decimal_comma:
        if has_comma and has_dot:
            token = token.replace(".", "").replace(",", ".")
        elif has_comma:
            token = token.replace(",", ".")
        elif re.fullmatch(r"\d{1,3}(\.\d{3})+", token):
            token = token.replace(".", "")
    else:
        if has_comma and has_dot:
            if token.rfind(",") < token.rfind("."):
                token = token.replace(",", "")
            else:
                token = token.replace(".", "").replace(",", ".")
        elif has_comma:
            if re.fullmatch(r"\d{1,3}(,\d{3})+", token):
                token = token.replace(",", "")
            else:
                token = token.replace(",", ".")
        elif re.fullmatch(r"\d{1,3}(\.\d{3}){2,}", token):
            token = token.replace(".", "")
    return sign + token


def _parse_number(raw: str, decimal_comma: bool) -> tuple[float, bool]:
    if raw is None:
        return (np.nan, False)
    original = str(raw).strip()
    if original == "":
        return (np.nan, False)
    collapsed = original.lower().replace(" ", "")
    if collapsed in _MISSING_NUMBERS:
        return (np.nan, False)
    token = _numeric_token(original)
    if token.lower() in _MISSING_NUMBERS or token == "":
        return (np.nan, False)
    normalized = _normalize_number(token, decimal_comma)
    try:
        value = float(normalized)
    except ValueError:
        return (np.nan, True)
    if not math.isfinite(value):
        return (np.nan, True)
    return (value, False)


# ---------------------------------------------------------------------------
# Header detection and column mapping
# ---------------------------------------------------------------------------


def _row_score(row: Sequence[str]) -> int:
    return sum(_header_points(cell) for cell in row)


def _pair_is_grouped_header(top: Sequence[str], bottom: Sequence[str]) -> bool:
    width = max(len(top), len(bottom))
    periods_bottom = 0
    periods_top = 0
    value_above = 0
    value_labels = 0
    last_value = False
    for index in range(width):
        top_cell = top[index] if index < len(top) else ""
        bot_cell = bottom[index] if index < len(bottom) else ""
        top_period = _split_value_period(top_cell)[1] is not None
        bot_period = _split_value_period(bot_cell)[1] is not None
        if top_period:
            periods_top += 1
        if bot_period:
            periods_bottom += 1
        if _is_value_type_label(top_cell):
            value_labels += 1
            last_value = True
        elif str(top_cell).strip() and not top_period:
            last_value = False
        if bot_period and (_is_value_type_label(top_cell) or (not str(top_cell).strip() and last_value)):
            value_above += 1
    if periods_bottom < 2 or periods_bottom <= periods_top:
        return False
    if value_above < 1 and value_labels < 2:
        return False
    return True


def _combine_group_headers(top: Sequence[str], bottom: Sequence[str]) -> list[str]:
    width = max(len(top), len(bottom))
    labels: list[str] = []
    last = ""
    for index in range(width):
        top_cell = top[index].strip() if index < len(top) else ""
        bot_cell = bottom[index].strip() if index < len(bottom) else ""
        if top_cell:
            if _is_value_type_label(top_cell):
                last = top_cell
            elif _split_value_period(top_cell)[1] is None:
                last = ""
            labels.append(top_cell)
        else:
            if last and _split_value_period(bot_cell)[1] is not None:
                labels.append(last)
            else:
                if not (last and _is_value_type_label(last)):
                    last = ""
                labels.append(last if last and _split_value_period(bot_cell)[1] is not None else "")
    headers: list[str] = []
    for index in range(width):
        top_cell = top[index].strip() if index < len(top) else ""
        bot_cell = bottom[index].strip() if index < len(bottom) else ""
        label = labels[index].strip()
        bot_period = _split_value_period(bot_cell)[1] is not None
        if bot_period:
            if label and _is_value_type_label(label):
                headers.append(f"{label} {bot_cell}".strip())
            else:
                headers.append(bot_cell)
            continue
        if top_cell and not _is_value_type_label(top_cell):
            headers.append(top_cell)
        elif bot_cell and _split_value_period(bot_cell)[1] is None:
            headers.append(bot_cell)
        else:
            headers.append(top_cell or bot_cell)
    return headers


def _detect_header(rows: Sequence[Sequence[str]]) -> tuple[list[str], int]:
    """Return (headers, index of the first data row)."""
    if not rows:
        return [], 0
    scan = min(len(rows), 40)
    best_score = -1
    best_headers = [str(cell) for cell in rows[0]]
    best_start = 1 if len(rows) > 1 else 1
    for index in range(scan):
        single = [str(cell) for cell in rows[index]]
        score = _row_score(single)
        if score > best_score:
            best_score = score
            best_headers = single
            best_start = index + 1
        if index + 1 < len(rows) and _pair_is_grouped_header(rows[index], rows[index + 1]):
            combined = _combine_group_headers(rows[index], rows[index + 1])
            pair_score = _row_score(combined) + 1
            if pair_score > best_score:
                best_score = pair_score
                best_headers = combined
                best_start = index + 2
    return best_headers, best_start


def _should_promote_years(headers: Sequence[str], period_indexes: set[int]) -> bool:
    """Bare years are period columns only when the sheet is not already long-format."""
    has_date = False
    has_value = False
    for index, header in enumerate(headers):
        if index in period_indexes or not str(header).strip():
            continue
        scores = _score_fields(str(header), allow_conditional_id=True)
        if scores["date"][0] > 0:
            has_date = True
        if scores["forecast"][0] > 0 or scores["actual"][0] > 0:
            has_value = True
    return not (has_date and has_value)


def _promote_year_columns(headers: Sequence[str]) -> list[tuple[int, datetime]]:
    found: list[tuple[int, datetime]] = []
    for index, header in enumerate(headers):
        text = _preprocess_date_text(header)
        if _RE_BARE_YEAR.match(text) or _RE_FY.match(text):
            parsed = _parse_period(text, allow_bare_year=True)
            if parsed is not None:
                found.append((index, parsed))
    if len(found) >= 2:
        return found
    return []


def _map_columns(headers: Sequence[str]) -> MappedColumns:
    periods: list[PeriodCol] = []
    period_indexes: set[int] = set()
    for index, header in enumerate(headers):
        if not str(header).strip():
            continue
        kind, parsed = _split_value_period(header)
        if parsed is not None:
            periods.append(
                PeriodCol(
                    index=index,
                    header=str(header).strip(),
                    explicit_kind=kind,
                    date=parsed,
                    resolved_kind=kind or "forecast",
                )
            )
            period_indexes.add(index)

    if len(periods) < 2 and _should_promote_years(headers, period_indexes):
        for index, parsed in _promote_year_columns(headers):
            if index in period_indexes:
                continue
            periods.append(
                PeriodCol(
                    index=index,
                    header=str(headers[index]).strip(),
                    explicit_kind=None,
                    date=parsed,
                    resolved_kind="forecast",
                )
            )
            period_indexes.add(index)
    periods.sort(key=lambda col: col.index)

    attribute_indexes = [index for index in range(len(headers)) if index not in period_indexes and str(headers[index]).strip()]
    preliminary = [
        _score_fields(str(headers[index]), allow_conditional_id=False) for index in attribute_indexes
    ]
    has_strong_id = any(score["product_id"][0] > 0 for score in preliminary)
    scored = [
        _score_fields(str(headers[index]), allow_conditional_id=not has_strong_id)
        for index in attribute_indexes
    ]
    if has_strong_id:
        for index, score in zip(attribute_indexes, scored):
            norm = _norm_header(str(headers[index]))
            conditional = [
                alias for alias in _PRODUCT_ID_CONDITIONAL if _alias_match(norm, alias) > 0
            ]
            strong_here = score["product_id"][0] > 0 and score["product_id"][1] not in _PRODUCT_ID_CONDITIONAL
            if conditional and not strong_here:
                score["product_id"] = (0, None)
                if score["product_name"][0] <= 0:
                    score["product_name"] = (160.0, conditional[0])

    ranked_columns: list[tuple[float, int, list[tuple[str, float, str]]]] = []
    for index, score in zip(attribute_indexes, scored):
        options: list[tuple[str, float, str]] = []
        for field, (field_score, alias) in score.items():
            if field_score > 0 and alias is not None:
                options.append((field, field_score, alias))
        options.sort(key=lambda item: (item[1], _FIELD_PRIORITY.get(item[0], 0)), reverse=True)
        top = options[0][1] if options else 0.0
        ranked_columns.append((top, index, options))
    ranked_columns.sort(key=lambda item: (item[0], item[1]), reverse=True)

    assigned: dict[str, int] = {}
    assigned_alias: dict[str, str] = {}
    used: set[int] = set()
    for _top, index, options in ranked_columns:
        for field, _score, alias in options:
            if field in assigned or index in used:
                continue
            assigned[field] = index
            assigned_alias[field] = alias
            used.add(index)
            break

    def _candidates(field: str) -> list[tuple[int, str, str, float]]:
        found: list[tuple[int, str, str, float]] = []
        for index, score in zip(attribute_indexes, scored):
            field_score, alias = score[field]
            if field_score <= 0 or alias is None:
                continue
            owner = next((name for name, col in assigned.items() if col == index), None)
            if owner is not None and owner != field:
                continue
            found.append((index, alias, str(headers[index]).strip(), field_score))
        return found

    extra_actual: list[tuple[int, str, str]] = []
    actual_options = _candidates("actual")
    if actual_options:
        def _actual_key(item: tuple[int, str, str, float]) -> tuple[int, float, int]:
            _index, alias, _header, field_score = item
            rank = _ACTUAL_PREFERRED.get(alias, _HISTORY.get(alias, 50))
            return (rank, field_score, _index)

        best = max(actual_options, key=_actual_key)
        assigned["actual"] = best[0]
        assigned_alias["actual"] = best[1]
        used.add(best[0])
        for item in actual_options:
            if item[0] != best[0]:
                extra_actual.append((item[0], item[1], item[2]))

    extra_forecast: list[tuple[int, str, str]] = []
    forecast_options = _candidates("forecast")
    if forecast_options:
        best_f = max(forecast_options, key=lambda item: (item[3], item[0]))
        assigned["forecast"] = best_f[0]
        assigned_alias["forecast"] = best_f[1]
        for item in forecast_options:
            if item[0] != best_f[0]:
                extra_forecast.append((item[0], item[1], item[2]))

    extra_date: list[tuple[int, str, str]] = []
    date_options = _candidates("date")
    if date_options:
        best_d = max(date_options, key=lambda item: (item[3], -item[0]))
        assigned["date"] = best_d[0]
        assigned_alias["date"] = best_d[1]
        for item in date_options:
            if item[0] != best_d[0]:
                extra_date.append((item[0], item[1], item[2]))

    shared = False
    id_from_name = False
    if "product_id" in assigned:
        alias = assigned_alias.get("product_id")
        if alias in _PRODUCT_ID_CONDITIONAL and "product_name" not in assigned:
            assigned["product_name"] = assigned["product_id"]
            assigned_alias["product_name"] = alias or "producto"
            shared = True
    elif "product_name" in assigned:
        assigned["product_id"] = assigned["product_name"]
        assigned_alias["product_id"] = assigned_alias.get("product_name", "nombre")
        shared = True
        id_from_name = True

    headers_out = {
        field: str(headers[index]).strip()
        for field, index in assigned.items()
    }
    _resolve_period_kinds(periods)
    return MappedColumns(
        columns=assigned,
        aliases=assigned_alias,
        headers=headers_out,
        extra_actual=extra_actual,
        extra_forecast=extra_forecast,
        extra_date=extra_date,
        periods=periods,
        shared_name_and_id=shared,
        id_from_name_only=id_from_name,
    )


def _resolve_period_kinds(periods: list[PeriodCol]) -> None:
    labeled_forecast = {col.date for col in periods if col.explicit_kind == "forecast"}
    labeled_actual = {col.date for col in periods if col.explicit_kind == "actual"}
    seen: set[datetime] = set()
    unlabeled = not labeled_forecast and not labeled_actual
    for col in periods:
        if col.explicit_kind is not None:
            col.resolved_kind = col.explicit_kind
        elif unlabeled:
            col.resolved_kind = "actual" if col.date in seen else "forecast"
        elif col.date in labeled_forecast and col.date not in labeled_actual:
            col.resolved_kind = "actual"
        elif col.date in labeled_actual and col.date not in labeled_forecast:
            col.resolved_kind = "forecast"
        else:
            col.resolved_kind = "forecast"
        seen.add(col.date)


# ---------------------------------------------------------------------------
# Reading bytes into grids
# ---------------------------------------------------------------------------


def _cell_to_str(value: Any) -> str:
    if value is None or value is pd.NA or value is pd.NaT:
        return ""
    if isinstance(value, (float, np.floating)):
        if not np.isfinite(value):
            return ""
        if float(value).is_integer() and abs(float(value)) < 1e15:
            return str(int(value))
        text = f"{float(value):.12f}".rstrip("0").rstrip(".")
        return text
    if isinstance(value, (int, np.integer)) and not isinstance(value, bool):
        return str(int(value))
    if isinstance(value, np.datetime64):
        if np.isnat(value):
            return ""
        value = pd.Timestamp(value)
    if isinstance(value, pd.Timestamp):
        if pd.isna(value):
            return ""
        value = value.to_pydatetime()
    if isinstance(value, datetime):
        if value.tzinfo is not None:
            value = value.replace(tzinfo=None)
        if value.hour == value.minute == value.second == value.microsecond == 0:
            return value.strftime("%Y-%m-%d")
        return value.strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(value, bytes):
        return _clean_cell(value.decode("utf-8", "replace"))
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    return _clean_cell(str(value))


def _drop_empty_rows(rows: list[list[str]]) -> list[list[str]]:
    return [row for row in rows if any(cell.strip() for cell in row)]


def _looks_html(data: bytes) -> bool:
    head = data[:800].lstrip().lower()
    return head.startswith(b"<") or b"<table" in head or b"<html" in head


def _decode_text(data: bytes) -> str:
    if data.startswith(b"\xff\xfe") or data.startswith(b"\xfe\xff"):
        text = data.decode("utf-16")
    elif data.startswith(b"\xef\xbb\xbf"):
        text = data.decode("utf-8-sig")
    else:
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            text = data.decode("cp1252", errors="replace")
    if text.startswith("\ufeff"):
        text = text.lstrip("\ufeff")
    return text.replace("\x00", "")


def _count_delim(line: str, delim: str) -> int:
    count = 0
    in_quotes = False
    index = 0
    while index < len(line):
        char = line[index]
        if char == '"':
            if in_quotes and index + 1 < len(line) and line[index + 1] == '"':
                index += 2
                continue
            in_quotes = not in_quotes
        elif char == delim and not in_quotes:
            count += 1
        index += 1
    return count


def _detect_delimiter(text: str, filename: str) -> str:
    ext = _extension(filename)
    lines = [line for line in text.splitlines() if line.strip()][:25]
    if not lines:
        return "\t" if ext == "tsv" else ","
    if ext == "tsv" and any("\t" in line for line in lines):
        return "\t"
    best = ","
    best_score = -1.0
    order = ["\t", ";", ",", "|"] if ext == "tsv" else [";", ",", "\t", "|"]
    for delim in order:
        counts = [_count_delim(line, delim) for line in lines]
        if not counts or max(counts) == 0:
            continue
        most = max(set(counts), key=counts.count)
        if most <= 0:
            continue
        consistency = counts.count(most) / len(counts)
        score = consistency * 100 + most
        if score > best_score:
            best_score = score
            best = delim
    try:
        sample = "\n".join(lines[:15])
        sniffed = csv.Sniffer().sniff(sample, delimiters=",;\t|")
        candidate = sniffed.delimiter
        if candidate in ",;\t|" and _count_delim(lines[0], candidate) > 0:
            # Trust the sniffer when it is consistent with the scored choice
            # or when scoring found nothing strong.
            if best_score < 0 or candidate == best:
                return candidate
    except csv.Error:
        pass
    return best


def _text_grid(data: bytes, filename: str) -> tuple[list[list[str]], str]:
    text = _decode_text(data)
    delimiter: str | None = None
    stripped = text.lstrip("\ufeff")
    lines = stripped.splitlines()
    if lines:
        first = lines[0].strip()
        if re.fullmatch(r"sep=([,;|\t]|\\t)", first, flags=re.IGNORECASE):
            token = first.split("=", 1)[1]
            delimiter = "\t" if token in {"\\t", "\t"} else token
            stripped = "\n".join(lines[1:])
    if delimiter is None:
        delimiter = _detect_delimiter(stripped, filename)
    rows: list[list[str]] = []
    reader = csv.reader(io.StringIO(stripped), delimiter=delimiter, quotechar='"')
    for raw_row in reader:
        cleaned = [_clean_cell(cell) for cell in raw_row]
        if any(cleaned):
            rows.append(cleaned)
    return rows, delimiter


class _HTMLTableParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tables: list[list[list[str]]] = []
        self._depth = 0
        self._rows: list[list[str]] = []
        self._row: list[str] = []
        self._cell: list[str] = []
        self._in_cell = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag == "table":
            self._depth += 1
            if self._depth == 1:
                self._rows = []
        elif tag == "tr" and self._depth:
            self._row = []
        elif tag in {"td", "th"} and self._depth:
            self._in_cell = True
            self._cell = []
        elif tag == "br" and self._in_cell:
            self._cell.append(" ")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in {"td", "th"} and self._in_cell:
            self._row.append(_clean_cell("".join(self._cell)))
            self._in_cell = False
        elif tag == "tr" and self._depth:
            if any(self._row):
                self._rows.append(self._row)
            self._row = []
        elif tag == "table" and self._depth:
            if self._depth == 1 and self._rows:
                self.tables.append(self._rows)
            self._depth -= 1

    def handle_data(self, data: str) -> None:
        if self._in_cell:
            self._cell.append(data)


def _html_grids(data: bytes) -> list[tuple[str, list[list[str]]]]:
    text = _decode_text(data)
    parser = _HTMLTableParser()
    parser.feed(text)
    return [(f"tabla_{index + 1}", rows) for index, rows in enumerate(parser.tables) if rows]


def _xlsx_grids(data: bytes) -> list[tuple[str, list[list[str]]]]:
    workbook = pd.ExcelFile(io.BytesIO(data), engine="openpyxl")
    grids: list[tuple[str, list[list[str]]]] = []
    for name in workbook.sheet_names:
        frame = workbook.parse(name, header=None, dtype=object)
        rows: list[list[str]] = []
        for record in frame.itertuples(index=False, name=None):
            row = [_cell_to_str(cell) for cell in record]
            if any(row):
                rows.append(row)
        grids.append((str(name), rows))
    return grids


def _read_grids(filename: str, data: bytes) -> tuple[list[tuple[str, list[list[str]]]], str | None]:
    ext = _extension(filename)
    magic_xlsx = data[:2] == b"PK"
    magic_xls = data[:8] == b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
    html = _looks_html(data)
    if html and not magic_xlsx and not magic_xls:
        grids = _html_grids(data)
        if grids:
            return grids, None
    if magic_xlsx or (ext in _XLSX_EXT and not html):
        try:
            return _xlsx_grids(data), None
        except ValueError:
            raise
        except Exception as exc:
            if magic_xlsx or ext in _XLSX_EXT:
                raise ValueError("No se pudo leer el archivo Excel.") from exc
    if magic_xls or (ext == "xls" and not html):
        try:
            return _xls_grids(data), None
        except ValueError:
            raise
        except Exception as exc:
            if magic_xls or ext == "xls":
                raise ValueError("No se pudo leer el archivo Excel.") from exc
    if html:
        grids = _html_grids(data)
        if grids:
            return grids, None
    rows, delimiter = _text_grid(data, filename)
    return [("datos", rows)], delimiter


def _select_grid(
    grids: Sequence[tuple[str, list[list[str]]]]
) -> tuple[str, list[list[str]], list[str]]:
    scored: list[tuple[int, int, str, list[list[str]]]] = []
    for name, rows in grids:
        if not rows:
            continue
        headers, start = _detect_header(rows)
        score = _row_score(headers)
        scored.append((score, len(rows) - start, name, rows))
    if not scored:
        raise ValueError("El archivo está vacío.")
    scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
    best = scored[0]
    ignored = [name for _score, _nrows, name, sheet_rows in scored[1:] if sheet_rows]
    return best[2], best[3], ignored


# ---------------------------------------------------------------------------
# Legacy XLS (OLE + BIFF8)
# ---------------------------------------------------------------------------

_BUILTIN_DATE_FORMATS = set(range(14, 23)) | set(range(27, 37)) | set(range(45, 48)) | set(range(50, 59))


def _format_is_date(fmt: str) -> bool:
    scrubbed = re.sub(r'"[^"]*"', "", fmt)
    scrubbed = re.sub(r"\[[^\]]*\]", "", scrubbed).lower()
    return bool(re.search(r"[ydhs]", scrubbed))


def _decode_rk(value: int) -> float:
    if value & 0x02:
        number = float(struct.unpack("<i", struct.pack("<I", value & 0xFFFFFFFC))[0] >> 2)
    else:
        number = struct.unpack("<d", struct.pack("<II", 0, value & 0xFFFFFFFC))[0]
    if value & 0x01:
        number /= 100.0
    return float(number)


class _OleFile:
    def __init__(self, data: bytes) -> None:
        if data[:8] != b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1":
            raise ValueError("No se pudo leer el archivo Excel.")
        self.data = data
        self.major = struct.unpack_from("<H", data, 0x1A)[0]
        sector_shift = struct.unpack_from("<H", data, 0x1E)[0]
        mini_shift = struct.unpack_from("<H", data, 0x20)[0]
        self.sector_size = 1 << sector_shift
        self.mini_size = 1 << mini_shift
        self.num_fat = struct.unpack_from("<I", data, 0x2C)[0]
        self.first_dir = struct.unpack_from("<I", data, 0x30)[0]
        self.mini_cutoff = struct.unpack_from("<I", data, 0x38)[0]
        self.first_mini_fat = struct.unpack_from("<I", data, 0x3C)[0]
        self.num_mini_fat = struct.unpack_from("<I", data, 0x40)[0]
        self.first_difat = struct.unpack_from("<I", data, 0x44)[0]
        self.num_difat = struct.unpack_from("<I", data, 0x48)[0]
        self.fat = self._read_fat()
        self._entries = self._read_dir()
        self._mini_stream = b""
        self._minifat: list[int] = []
        root = next((entry for entry in self._entries if entry["type"] == 5), None)
        if root is not None and self.num_mini_fat:
            self._mini_stream = self._read_chain(root["start"], root["size"], mini=False)
            self._minifat = self._read_minifat()

    def _sector_offset(self, sid: int) -> int:
        return (sid + 1) * self.sector_size

    def _read_sector(self, sid: int) -> bytes:
        offset = self._sector_offset(sid)
        return self.data[offset : offset + self.sector_size]

    def _read_fat(self) -> list[int]:
        difat: list[int] = []
        for index in range(109):
            value = struct.unpack_from("<I", self.data, 0x4C + 4 * index)[0]
            if value >= 0xFFFFFFF0:
                continue
            difat.append(value)
        next_sid = self.first_difat
        guard = 0
        while next_sid < 0xFFFFFFF0 and guard < 10000:
            guard += 1
            blob = self._read_sector(next_sid)
            entries = self.sector_size // 4
            for index in range(entries - 1):
                value = struct.unpack_from("<I", blob, index * 4)[0]
                if value < 0xFFFFFFF0:
                    difat.append(value)
            next_sid = struct.unpack_from("<I", blob, (entries - 1) * 4)[0]
        fat: list[int] = []
        for sid in difat[: self.num_fat or len(difat)]:
            blob = self._read_sector(sid)
            count = self.sector_size // 4
            fat.extend(struct.unpack_from("<" + "I" * count, blob))
        return fat

    def _next_sector(self, sid: int, table: Sequence[int]) -> int:
        if sid < 0 or sid >= len(table):
            return _ENDOFCHAIN
        return table[sid]

    def _read_chain(self, start: int, size: int, *, mini: bool) -> bytes:
        if start >= 0xFFFFFFF0 or size <= 0:
            return b""
        table = self._minifat if mini else self.fat
        chunk = self.mini_size if mini else self.sector_size
        out = bytearray()
        sid = start
        seen: set[int] = set()
        while sid < 0xFFFFFFF0 and len(out) < size + chunk:
            if sid in seen or sid < 0:
                break
            seen.add(sid)
            if mini:
                offset = sid * self.mini_size
                out += self._mini_stream[offset : offset + self.mini_size]
            else:
                out += self._read_sector(sid)
            sid = self._next_sector(sid, table)
            if len(seen) > 1_000_000:
                break
        return bytes(out[:size])

    def _read_minifat(self) -> list[int]:
        blob = self._read_chain_fat_sectors(self.first_mini_fat, self.num_mini_fat)
        count = len(blob) // 4
        if count == 0:
            return []
        return list(struct.unpack_from("<" + "I" * count, blob))

    def _read_chain_fat_sectors(self, start: int, count: int) -> bytes:
        out = bytearray()
        sid = start
        seen: set[int] = set()
        while sid < 0xFFFFFFF0 and len(seen) < max(count, 1) + 2:
            if sid in seen:
                break
            seen.add(sid)
            out += self._read_sector(sid)
            sid = self._next_sector(sid, self.fat)
            if count and len(seen) >= count:
                break
        return bytes(out)

    def _read_dir(self) -> list[dict[str, Any]]:
        blob = bytearray()
        sid = self.first_dir
        seen: set[int] = set()
        while sid < 0xFFFFFFF0 and sid not in seen and len(seen) < 100000:
            seen.add(sid)
            blob += self._read_sector(sid)
            sid = self._next_sector(sid, self.fat)
        entries: list[dict[str, Any]] = []
        for offset in range(0, len(blob), 128):
            entry = blob[offset : offset + 128]
            if len(entry) < 128:
                break
            name_len = struct.unpack_from("<H", entry, 64)[0]
            obj_type = entry[66]
            if obj_type == 0:
                continue
            raw = entry[: max(0, name_len - 2)]
            try:
                name = raw.decode("utf-16le", errors="ignore")
            except Exception:
                name = ""
            start = struct.unpack_from("<I", entry, 116)[0]
            size = struct.unpack_from("<Q", entry, 120)[0]
            if self.major < 4:
                size &= 0xFFFFFFFF
            entries.append({"name": name, "type": obj_type, "start": start, "size": size})
        return entries

    def stream(self, *names: str) -> bytes:
        wanted = {name.lower() for name in names}
        for entry in self._entries:
            if entry["name"].lower() not in wanted or entry["type"] != 2:
                continue
            mini = entry["size"] < self.mini_cutoff
            return self._read_chain(entry["start"], entry["size"], mini=mini)
        raise ValueError("No se pudo leer el archivo Excel.")


class _ChunkReader:
    """Read an SST that may be split across CONTINUE records."""

    def __init__(self, chunks: list[bytes], codepage: str) -> None:
        self.chunks = chunks or [b""]
        self.index = 0
        self.offset = 0
        self.codepage = codepage

    def remaining(self) -> int:
        # Do not cross into the next CONTINUE here. A split string stores a
        # fresh compression flag as the first byte of that record.
        if self.index >= len(self.chunks):
            return 0
        return len(self.chunks[self.index]) - self.offset

    def read(self, size: int) -> bytes:
        out = bytearray()
        while size:
            if self.remaining() == 0:
                self.index += 1
                self.offset = 0
                if self.index >= len(self.chunks):
                    raise ValueError("SST truncado")
            avail = self.remaining()
            take = min(size, avail)
            out += self.chunks[self.index][self.offset : self.offset + take]
            self.offset += take
            size -= take
        return bytes(out)

    def read_u8(self) -> int:
        return self.read(1)[0]

    def read_u16(self) -> int:
        return struct.unpack("<H", self.read(2))[0]

    def read_u32(self) -> int:
        return struct.unpack("<I", self.read(4))[0]

    def read_string(self, rich: bool = True) -> str:
        cch = self.read_u16()
        flags = self.read_u8()
        runs = 0
        ext = 0
        if rich and flags & 0x08:
            runs = self.read_u16()
        if rich and flags & 0x04:
            ext = self.read_u32()
        high = bool(flags & 0x01)
        parts: list[str] = []
        left = cch
        while left:
            if self.remaining() == 0:
                high = bool(self.read_u8() & 0x01)
                continue
            width = 2 if high else 1
            can = min(left, self.remaining() // width)
            if can == 0:
                high = bool(self.read_u8() & 0x01)
                continue
            blob = self.read(can * width)
            if high:
                parts.append(blob.decode("utf-16le", errors="replace"))
            else:
                parts.append(blob.decode(self.codepage, errors="replace"))
            left -= can
        if runs:
            self.read(4 * runs)
        if ext:
            self.read(ext)
        return "".join(parts)


def _parse_xl_unicode(payload: bytes, codepage: str, *, short: bool = False) -> str:
    if short:
        if len(payload) < 2:
            return ""
        cch = payload[0]
        flags = payload[1]
        data = payload[2:]
    else:
        if len(payload) < 3:
            return ""
        cch = struct.unpack_from("<H", payload, 0)[0]
        flags = payload[2]
        data = payload[3:]
    if flags & 0x01:
        raw = data[: cch * 2]
        return raw.decode("utf-16le", errors="replace")
    return data[:cch].decode(codepage, errors="replace")


def _xls_grids(data: bytes) -> list[tuple[str, list[list[str]]]]:
    ole = _OleFile(data)
    try:
        blob = ole.stream("Workbook", "Book")
    except ValueError:
        raise
    if not blob:
        raise ValueError("No se pudo leer el archivo Excel.")
    return _parse_biff8(blob)


def _parse_biff8(blob: bytes) -> list[tuple[str, list[list[str]]]]:
    records: list[tuple[int, bytes, list[bytes]]] = []
    pos = 0
    while pos + 4 <= len(blob):
        op, length = struct.unpack_from("<HH", blob, pos)
        pos += 4
        payload = blob[pos : pos + length]
        pos += length
        if op == 0 and length == 0:
            break
        if op == 0x003C and records:  # CONTINUE
            records[-1][2].append(payload)
        else:
            records.append((op, payload, []))

    codepage = "cp1252"
    sst: list[str] = []
    formats: dict[int, str] = {}
    xf_ifmt: list[int] = []
    sheet_names: list[str] = []
    epoch_1904 = False
    protected = False
    sheets: list[tuple[str, dict[tuple[int, int], str]]] = []
    current: dict[tuple[int, int], str] | None = None
    pending_string: tuple[int, int] | None = None
    sheet_ordinal = 0

    def is_date(xf_index: int) -> bool:
        if xf_index < 0 or xf_index >= len(xf_ifmt):
            return False
        ifmt = xf_ifmt[xf_index]
        if ifmt in formats:
            return _format_is_date(formats[ifmt])
        return ifmt in _BUILTIN_DATE_FORMATS

    def put_number(row: int, col: int, xf_index: int, value: float) -> None:
        if current is None:
            return
        if is_date(xf_index):
            stamp = _excel_serial_to_datetime(value, epoch_1904=epoch_1904)
            current[(row, col)] = stamp.strftime("%Y-%m-%d") if stamp else ""
            return
        if math.isfinite(value) and abs(value - round(value)) < 1e-9 and abs(value) < 1e15:
            current[(row, col)] = str(int(round(value)))
        elif math.isfinite(value):
            current[(row, col)] = f"{value:.12f}".rstrip("0").rstrip(".")
        else:
            current[(row, col)] = ""

    for op, payload, continues in records:
        if op == 0x002F:  # FILEPASS
            protected = True
            break
        if op == 0x0042 and len(payload) >= 2:  # CODEPAGE
            cp = struct.unpack_from("<H", payload, 0)[0]
            # 1200 marks uncompressed text as UTF-16. Compressed strings stay
            # single-byte Latin-1 (the low byte of that code point).
            codepage = {
                1200: "latin-1",
                1252: "cp1252",
                65001: "latin-1",
                28591: "latin-1",
                10000: "mac_roman",
            }.get(cp, "cp1252")
        elif op == 0x0022 and len(payload) >= 2:  # DATEMODE
            epoch_1904 = struct.unpack_from("<H", payload, 0)[0] == 1
        elif op == 0x041E:  # FORMAT
            if len(payload) >= 3:
                ifmt = struct.unpack_from("<H", payload, 0)[0]
                formats[ifmt] = _parse_xl_unicode(payload[2:], codepage)
        elif op == 0x00E0 and len(payload) >= 4:  # XF
            xf_ifmt.append(struct.unpack_from("<H", payload, 2)[0])
        elif op == 0x0085:  # BOUNDSHEET
            sheet_names.append(_parse_xl_unicode(payload[6:], codepage, short=True) or f"Hoja{len(sheet_names) + 1}")
        elif op == 0x00FC:  # SST
            try:
                reader = _ChunkReader([payload, *continues], codepage)
                _total = reader.read_u32()
                unique = reader.read_u32()
                sst = []
                for _ in range(unique):
                    sst.append(reader.read_string(rich=True))
            except Exception:
                sst = sst or []
        elif op == 0x0809:  # BOF
            dt = struct.unpack_from("<H", payload, 2)[0] if len(payload) >= 4 else 0
            pending_string = None
            if dt == 0x0010:
                name = sheet_names[sheet_ordinal] if sheet_ordinal < len(sheet_names) else f"Hoja{sheet_ordinal + 1}"
                sheet_ordinal += 1
                current = {}
                sheets.append((name, current))
            else:
                current = None
        elif op == 0x000A:  # EOF
            current = None
            pending_string = None
        elif current is None:
            continue
        elif op == 0x0203 and len(payload) >= 14:  # NUMBER
            row, col, xf = struct.unpack_from("<HHH", payload, 0)
            value = struct.unpack_from("<d", payload, 6)[0]
            put_number(row, col, xf, float(value))
        elif op == 0x00FD and len(payload) >= 10:  # LABELSST
            row, col, _xf, idx = struct.unpack_from("<HHHI", payload, 0)
            text = sst[idx] if 0 <= idx < len(sst) else ""
            current[(row, col)] = _clean_cell(text)
        elif op == 0x0204:  # LABEL
            row, col, _xf = struct.unpack_from("<HHH", payload, 0)
            current[(row, col)] = _clean_cell(_parse_xl_unicode(payload[6:], codepage))
        elif op == 0x027E and len(payload) >= 10:  # RK
            row, col, xf, rk = struct.unpack_from("<HHHI", payload, 0)
            put_number(row, col, xf, _decode_rk(rk))
        elif op == 0x00BD and len(payload) >= 6:  # MULRK
            row, first = struct.unpack_from("<HH", payload, 0)
            body = payload[4:-2]
            for offset in range(0, len(body) - 5, 6):
                xf, rk = struct.unpack_from("<HI", body, offset)
                put_number(row, first + offset // 6, xf, _decode_rk(rk))
        elif op == 0x0006 and len(payload) >= 14:  # FORMULA
            row, col, xf = struct.unpack_from("<HHH", payload, 0)
            cached = payload[6:14]
            if len(cached) >= 8 and cached[6] == 0xFF and cached[7] == 0xFF:
                kind = cached[0]
                if kind == 0:
                    pending_string = (row, col)
                elif kind == 1:
                    current[(row, col)] = "TRUE" if cached[2] else "FALSE"
                else:
                    current[(row, col)] = ""
            else:
                put_number(row, col, xf, float(struct.unpack("<d", cached)[0]))
        elif op == 0x0207 and pending_string is not None:  # STRING
            current[pending_string] = _clean_cell(_parse_xl_unicode(payload, codepage))
            pending_string = None
        elif op == 0x0205 and len(payload) >= 8:  # BOOLERR
            row, col, _xf, val, flag = struct.unpack_from("<HHHBB", payload, 0)
            if not flag:
                current[(row, col)] = "TRUE" if val else "FALSE"

    if protected and not sheets:
        raise ValueError("El archivo Excel está protegido y no se puede leer.")

    grids: list[tuple[str, list[list[str]]]] = []
    for name, cells in sheets:
        if not cells:
            grids.append((name, []))
            continue
        max_row = max(row for row, _col in cells)
        max_col = max(col for _row, col in cells)
        rows: list[list[str]] = []
        for row_index in range(max_row + 1):
            row = [cells.get((row_index, col_index), "") for col_index in range(max_col + 1)]
            if any(cell.strip() for cell in row):
                rows.append(row)
        grids.append((name, rows))
    if not grids:
        raise ValueError("No se pudo leer el archivo Excel.")
    return grids


# ---------------------------------------------------------------------------
# Grid -> canonical frame
# ---------------------------------------------------------------------------


def _empty_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "product_id": pd.Series(dtype="object"),
            "product_name": pd.Series(dtype="object"),
            "category": pd.Series(dtype="object"),
            "location": pd.Series(dtype="object"),
            "date": pd.Series(dtype="datetime64[ns]"),
            "forecast": pd.Series(dtype="float64"),
            "actual": pd.Series(dtype="float64"),
            "model_name": pd.Series(dtype="object"),
            "horizon": pd.Series(dtype="float64"),
        }
    )


def _cell(row: Sequence[str], index: int | None) -> str:
    if index is None or index < 0 or index >= len(row):
        return ""
    return row[index].strip()


def _is_nan(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, float) and math.isnan(value):
        return True
    return False


def _blank_record() -> dict[str, Any]:
    return {
        "product_id": "",
        "product_name": "",
        "category": "",
        "location": "",
        "date": None,
        "forecast": np.nan,
        "actual": np.nan,
        "model_name": "",
        "horizon": np.nan,
    }


def _record_has_content(record: dict[str, Any]) -> bool:
    if any(record[name] for name in ("product_id", "product_name", "category", "location", "model_name")):
        return True
    if record["date"] is not None:
        return True
    if not _is_nan(record["forecast"]) or not _is_nan(record["actual"]) or not _is_nan(record["horizon"]):
        return True
    return False


def _find_measure_column(
    headers: Sequence[str],
    rows: Sequence[Sequence[str]],
    data_start: int,
    mapped: MappedColumns,
) -> int | None:
    period_indexes = {col.index for col in mapped.periods}
    used = set(mapped.columns.values())
    best_index: int | None = None
    best_frac = 0.0
    for index, header in enumerate(headers):
        if index in period_indexes:
            continue
        values = []
        for row in rows[data_start:]:
            if index < len(row) and row[index].strip():
                values.append(row[index])
        if not values:
            continue
        hits = sum(1 for value in values if _classify_measure(value) is not None)
        frac = hits / len(values)
        header_norm = _norm_header(header)
        if header_norm in _MEASURE_HEADERS and frac >= 0.5 and hits >= 1:
            return index
        if index in used:
            continue
        if frac >= 0.6 and hits >= 1 and frac > best_frac:
            best_index = index
            best_frac = frac
    return best_index


def _column_mostly_serial(rows: Sequence[Sequence[str]], data_start: int, index: int) -> bool:
    numbers = 0
    nonempty = 0
    parsed = 0
    for row in rows[data_start:]:
        if index >= len(row):
            continue
        text = row[index].strip()
        if not text:
            continue
        nonempty += 1
        if _parse_period(text, allow_bare_year=True) is not None:
            parsed += 1
            continue
        token = text.replace(",", ".")
        if re.fullmatch(r"\d+(\.0+)?", token):
            value = float(token)
            if 60 <= value <= 80000:
                numbers += 1
    if nonempty == 0:
        return False
    return numbers >= 1 and numbers / nonempty >= 0.4 and parsed / nonempty < 0.5


def _parse_date_cell(text: str, *, serials: bool) -> datetime | None:
    parsed = _parse_period(text, allow_bare_year=True)
    if parsed is not None:
        return parsed
    if serials:
        return _parse_serial_text(text, epoch_1904=False)
    return None


def _base_attributes(
    row: Sequence[str],
    mapped: MappedColumns,
    decimal_comma: bool,
    bad_numbers: list[int],
) -> dict[str, Any]:
    record = _blank_record()
    for field in ("product_id", "product_name", "category", "location", "model_name"):
        record[field] = _cell(row, mapped.columns.get(field))
    if "horizon" in mapped.columns:
        value, invalid = _parse_number(_cell(row, mapped.columns["horizon"]), decimal_comma)
        record["horizon"] = value
        if invalid:
            bad_numbers[0] += 1
    return record


def _layout_of(mapped: MappedColumns) -> Layout:
    has_date = "date" in mapped.columns
    has_value = "forecast" in mapped.columns or "actual" in mapped.columns
    if len(mapped.periods) >= 2:
        return "wide"
    if len(mapped.periods) >= 1 and not (has_date and has_value):
        return "wide"
    return "long"


def _samples_for_decimals(
    rows: Sequence[Sequence[str]],
    data_start: int,
    mapped: MappedColumns,
    layout: Layout,
) -> list[str]:
    samples: list[str] = []
    indexes: list[int] = []
    if layout == "wide":
        indexes.extend(col.index for col in mapped.periods)
    else:
        for field in ("forecast", "actual"):
            if field in mapped.columns:
                indexes.append(mapped.columns[field])
    if "horizon" in mapped.columns:
        indexes.append(mapped.columns["horizon"])
    for row in rows[data_start:]:
        for index in indexes:
            if index < len(row) and row[index].strip():
                samples.append(row[index])
            if len(samples) >= 4000:
                return samples
    return samples


def _merge_records(records: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], int]:
    """Collapse rows that share product_id, location and date.

    A full long-format row replaces the previous one. Partial wide cells, which
    carry only one metric, fill the empty metric and count as duplicates only
    when both sides already have that metric.
    """
    order: list[tuple[str, str, datetime]] = []
    merged: dict[tuple[str, str, datetime], dict[str, Any]] = {}
    undated: list[dict[str, Any]] = []
    duplicates = 0
    for record in records:
        if not _record_has_content(record):
            continue
        when = record["date"]
        if when is None or (isinstance(when, float) and math.isnan(when)):
            undated.append(record)
            continue
        key = (record["product_id"], record["location"], when)
        if key not in merged:
            merged[key] = record
            order.append(key)
            continue
        previous = merged[key]
        both_full = not record.get("partial") and not previous.get("partial")
        if both_full:
            merged[key] = record
            duplicates += 1
            continue
        conflict = False
        for metric in ("forecast", "actual"):
            prev_set = not _is_nan(previous[metric])
            new_set = not _is_nan(record[metric])
            if prev_set and new_set:
                conflict = True
                previous[metric] = record[metric]
            elif new_set and not prev_set:
                previous[metric] = record[metric]
        for field in ("product_name", "category", "model_name", "product_id"):
            if record[field]:
                previous[field] = record[field]
        if record["location"]:
            previous["location"] = record["location"]
        if not _is_nan(record["horizon"]):
            previous["horizon"] = record["horizon"]
        if not record.get("partial"):
            previous["partial"] = False
        if conflict:
            duplicates += 1
    combined = [merged[key] for key in order]
    combined.extend(undated)
    return combined, duplicates


def _records_to_frame(records: list[dict[str, Any]]) -> pd.DataFrame:
    if not records:
        return _empty_frame()
    frame = pd.DataFrame(
        {
            "product_id": pd.Series([rec["product_id"] for rec in records], dtype="object"),
            "product_name": pd.Series([rec["product_name"] for rec in records], dtype="object"),
            "category": pd.Series([rec["category"] for rec in records], dtype="object"),
            "location": pd.Series([rec["location"] for rec in records], dtype="object"),
            "date": pd.to_datetime([rec["date"] for rec in records]),
            "forecast": pd.Series([rec["forecast"] for rec in records], dtype="float64"),
            "actual": pd.Series([rec["actual"] for rec in records], dtype="float64"),
            "model_name": pd.Series([rec["model_name"] for rec in records], dtype="object"),
            "horizon": pd.Series([rec["horizon"] for rec in records], dtype="float64"),
        }
    )
    for column in ("product_id", "product_name", "category", "location", "model_name"):
        frame[column] = frame[column].map(lambda value: "" if value is None else str(value).strip())
    frame["date"] = frame["date"].astype("datetime64[ns]")
    frame = frame.loc[:, list(OUTPUT_COLUMNS)]
    frame = frame.sort_values(
        by=["product_id", "location", "date"],
        kind="mergesort",
        na_position="last",
    ).reset_index(drop=True)
    return frame


def _bucket_frequency(median_days: float) -> Frequency:
    if 0.5 <= median_days < 1.5:
        return "D"
    if 6.5 <= median_days <= 7.5:
        return "W"
    if 27.5 <= median_days <= 31.5:
        return "M"
    if 88.5 <= median_days <= 92.5:
        return "Q"
    if 363.5 <= median_days <= 366.5:
        return "Y"
    return "irregular"


def _infer_frequency(frame: pd.DataFrame, warnings: list[str]) -> Frequency:
    if frame.empty or frame["date"].notna().sum() == 0:
        warnings.append(
            "La frecuencia es irregular: no hay suficientes fechas por producto para inferirla."
        )
        return "irregular"
    grouped: dict[tuple[str, str], list[pd.Timestamp]] = {}
    for product_id, location, stamp in zip(frame["product_id"], frame["location"], frame["date"]):
        if pd.isna(stamp):
            continue
        grouped.setdefault((str(product_id), str(location)), []).append(pd.Timestamp(stamp))
    buckets: list[Frequency] = []
    medians: list[float] = []
    for dates in grouped.values():
        unique = sorted(set(dates))
        if len(unique) < 2:
            continue
        diffs = [
            (unique[index] - unique[index - 1]).days
            for index in range(1, len(unique))
            if (unique[index] - unique[index - 1]).days > 0
        ]
        if not diffs:
            continue
        median = float(np.median(np.asarray(diffs, dtype=float)))
        medians.append(median)
        median_bucket = _bucket_frequency(median)
        diff_buckets = [_bucket_frequency(float(value)) for value in diffs]
        # A median can land in a bucket by chance when the gaps themselves disagree.
        if (
            median_bucket == "irregular"
            or diff_buckets.count(median_bucket) / len(diff_buckets) < 0.5
        ):
            buckets.append("irregular")
        else:
            buckets.append(median_bucket)
    if not buckets:
        warnings.append(
            "La frecuencia es irregular: no hay suficientes fechas por producto para inferirla."
        )
        return "irregular"
    unique_buckets = set(buckets)
    if len(unique_buckets) == 1 and "irregular" not in unique_buckets:
        return next(iter(unique_buckets))
    if unique_buckets == {"irregular"}:
        shown = ", ".join(f"{value:.0f}" for value in medians[:6])
        warnings.append(
            "La frecuencia es irregular: el espaciado mediano "
            f"({shown} días) no es D, W, M, Q ni Y."
        )
        return "irregular"
    labels = ", ".join(sorted(unique_buckets))
    warnings.append(
        "La frecuencia es irregular: el espaciado de fechas no es homogéneo "
        f"({labels})."
    )
    return "irregular"


def _repeated_header(row: Sequence[str], headers: Sequence[str]) -> bool:
    if not row or not headers:
        return False
    width = max(len(row), len(headers))
    matches = 0
    nonempty = 0
    for index in range(width):
        left = _norm_header(row[index]) if index < len(row) else ""
        right = _norm_header(headers[index]) if index < len(headers) else ""
        if not left and not right:
            continue
        nonempty += 1
        if left and left == right:
            matches += 1
    return nonempty > 0 and matches >= max(2, nonempty - 1)


def _grid_to_result(
    rows: list[list[str]],
    delimiter: str | None,
    warnings: list[str],
) -> dict[str, Any]:
    rows = _drop_empty_rows(rows)
    if not rows:
        raise ValueError("El archivo está vacío.")
    headers, data_start = _detect_header(rows)
    mapped = _map_columns(headers)
    if mapped.id_from_name_only:
        warnings.append(
            "No había una columna de identificador; se usó el nombre de producto como product_id."
        )
    if mapped.extra_actual:
        kept = mapped.headers.get("actual", mapped.aliases.get("actual", "actual"))
        ignored = ", ".join(f"'{name}'" for _idx, _alias, name in mapped.extra_actual)
        warnings.append(
            "Hay varias columnas de demanda realizada; "
            f"se usó '{kept}' y se ignoró {ignored}."
        )
    if mapped.extra_forecast:
        kept_f = mapped.headers.get("forecast", "pronostico")
        ignored_f = ", ".join(f"'{name}'" for _idx, _alias, name in mapped.extra_forecast)
        warnings.append(
            f"Hay varias columnas de pronóstico; se usó '{kept_f}' y se ignoró {ignored_f}."
        )

    has_product = "product_id" in mapped.columns
    has_values = bool(mapped.periods) or "forecast" in mapped.columns or "actual" in mapped.columns
    if not has_product and not has_values:
        raise ValueError(
            "No se reconocieron columnas de producto ni de valores (pronóstico o venta) en el archivo."
        )
    if not has_product:
        raise ValueError("No se reconoció una columna de producto en el archivo.")
    if not has_values:
        raise ValueError(
            "No se reconocieron columnas de valores (pronóstico, venta o periodos) en el archivo."
        )

    layout = _layout_of(mapped)
    if layout == "long" and "date" not in mapped.columns:
        warnings.append("No se reconoció una columna de fecha; las fechas quedaron vacías.")

    decimal_comma = _detect_decimal_comma(
        _samples_for_decimals(rows, data_start, mapped, layout),
        delimiter,
    )
    bad_numbers = [0]
    bad_dates = 0
    empty_dates = 0
    measure_index = None
    if layout == "wide":
        measure_index = _find_measure_column(headers, rows, data_start, mapped)

    serial_dates = False
    if layout == "long" and "date" in mapped.columns:
        serial_dates = _column_mostly_serial(rows, data_start, mapped.columns["date"])

    records: list[dict[str, Any]] = []
    used_forecast_header: str | None = None
    used_actual_header: str | None = None
    saw_forecast_metric = False
    saw_actual_metric = False

    for row in rows[data_start:]:
        if _repeated_header(row, headers):
            continue
        if layout == "wide":
            base = _base_attributes(row, mapped, decimal_comma, bad_numbers)
            measure_kind = _classify_measure(_cell(row, measure_index)) if measure_index is not None else None
            identifiers = any(
                base[name] for name in ("product_id", "product_name", "category", "location", "model_name")
            )
            period_payload: list[tuple[PeriodCol, str, float, bool]] = []
            any_payload = False
            for period in mapped.periods:
                raw = _cell(row, period.index)
                value, invalid = _parse_number(raw, decimal_comma)
                if raw.strip():
                    any_payload = True
                period_payload.append((period, raw, value, invalid))
            if not identifiers and not any_payload and _is_nan(base["horizon"]):
                continue
            for period, raw, value, invalid in period_payload:
                if invalid:
                    bad_numbers[0] += 1
                if period.explicit_kind is not None:
                    kind = period.explicit_kind
                elif measure_kind is not None:
                    kind = measure_kind
                else:
                    kind = period.resolved_kind
                record = dict(base)
                record["partial"] = True
                record["date"] = period.date
                if kind == "actual":
                    record["actual"] = value
                    saw_actual_metric = True
                    if used_actual_header is None:
                        used_actual_header = period.header
                else:
                    record["forecast"] = value
                    saw_forecast_metric = True
                    if used_forecast_header is None:
                        used_forecast_header = period.header
                records.append(record)
            continue

        record = _base_attributes(row, mapped, decimal_comma, bad_numbers)
        record["partial"] = False
        if "date" in mapped.columns:
            raw_date = _cell(row, mapped.columns["date"])
            if raw_date == "":
                empty_dates += 1
                record["date"] = None
            else:
                parsed = _parse_date_cell(raw_date, serials=serial_dates)
                if parsed is None:
                    bad_dates += 1
                    record["date"] = None
                else:
                    record["date"] = parsed
        if "forecast" in mapped.columns:
            value, invalid = _parse_number(_cell(row, mapped.columns["forecast"]), decimal_comma)
            record["forecast"] = value
            if invalid:
                bad_numbers[0] += 1
            saw_forecast_metric = True
        if "actual" in mapped.columns:
            value, invalid = _parse_number(_cell(row, mapped.columns["actual"]), decimal_comma)
            record["actual"] = value
            if invalid:
                bad_numbers[0] += 1
            saw_actual_metric = True
        if _record_has_content(record):
            records.append(record)

    if bad_numbers[0]:
        n = bad_numbers[0]
        warnings.append(
            f"Se convirtieron {n} valores numéricos no válidos a NaN."
            if n != 1
            else "Se convirtió 1 valor numérico no válido a NaN."
        )
    if bad_dates:
        warnings.append(
            f"Se dejaron vacías {bad_dates} fechas no reconocidas."
            if bad_dates != 1
            else "Se dejó vacía 1 fecha no reconocida."
        )
    if empty_dates:
        warnings.append(
            f"Hay {empty_dates} filas con fecha vacía."
            if empty_dates != 1
            else "Hay 1 fila con fecha vacía."
        )

    merged, duplicate_count = _merge_records(records)
    if duplicate_count:
        warnings.append(
            "Se descartó 1 fila duplicada de product_id+location+date; se conservó la última."
            if duplicate_count == 1
            else "Se descartaron "
            f"{duplicate_count} filas duplicadas de product_id+location+date; se conservó la última."
        )
    frame = _records_to_frame(merged)
    frequency = _infer_frequency(frame, warnings)

    column_map: dict[str, str] = {}
    for field in (
        "product_id",
        "product_name",
        "category",
        "location",
        "date",
        "model_name",
        "horizon",
    ):
        if field not in mapped.headers:
            continue
        if layout == "wide" and field == "date":
            continue
        column_map[field] = mapped.headers[field]
    if layout == "long":
        if "forecast" in mapped.headers:
            column_map["forecast"] = mapped.headers["forecast"]
        if "actual" in mapped.headers:
            column_map["actual"] = mapped.headers["actual"]
    else:
        if saw_forecast_metric and used_forecast_header:
            column_map["forecast"] = used_forecast_header
        if saw_actual_metric:
            if measure_index is not None and any(
                col.explicit_kind is None for col in mapped.periods
            ):
                column_map["actual"] = str(headers[measure_index]).strip()
                if saw_forecast_metric and "forecast" not in column_map and used_forecast_header:
                    column_map["forecast"] = used_forecast_header
            elif used_actual_header:
                column_map["actual"] = used_actual_header

    return {
        "frame": frame,
        "frequency": frequency,
        "warnings": warnings,
        "column_map": column_map,
        "source_name": "",
        "layout": layout,
    }
