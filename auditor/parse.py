"""Ingesta CSV/TSV de forecasts, en español o inglés."""

from __future__ import annotations

import csv
import io
import re
import unicodedata
from datetime import date, datetime, timedelta

class ParseError(ValueError):
    """El archivo no se puede auditar. El mensaje está en español."""


_ALIASES = {
    "product_id": {
        "product_id", "productid", "producto_id", "id_producto", "id_prod", "sku",
        "cod_sku", "codigo_sku", "codigo", "cod", "cod_prod", "cod_producto",
        "codigo_producto", "articulo", "art", "cod_art", "codigo_articulo",
        "material", "cod_material", "codigo_material", "item", "item_id", "upc",
        "ean", "referencia", "ref",
    },
    "product_name": {
        "product_name", "producto", "nombre", "nombre_producto", "descripcion",
        "desc", "desc_producto", "item_name", "sku_name",
    },
    "date": {
        "date", "fecha", "dia", "periodo", "period", "semana", "week", "mes",
        "month", "anio_mes", "ano_mes", "yyyymm", "ds", "timestamp",
    },
    "forecast": {
        "forecast", "fcst", "pronostico", "pron", "prevision", "prediccion",
        "pred", "yhat", "forecast_qty", "qty_fcst", "unidades_fcst",
        "demanda_pronosticada", "previsto",
    },
    "actual": {
        "actual", "real", "venta", "ventas", "venta_real", "ventas_reales",
        "demanda", "demand", "demanda_real", "unidades", "uds", "qty", "quantity",
        "actual_qty", "qty_real", "unidades_real", "sell_out", "sellout", "consumo",
        "y", "sales",
    },
    "model": {"model", "modelo", "algoritmo", "method", "metodo", "version_modelo", "model_name"},
    "lower": {"lower", "lower_bound", "limite_inferior", "intervalo_inferior", "p10", "q10", "fcst_min", "yhat_lower", "lo"},
    "upper": {"upper", "upper_bound", "limite_superior", "intervalo_superior", "p90", "q90", "fcst_max", "yhat_upper", "hi"},
    "category": {"category", "categoria", "familia", "subfamilia", "linea", "rubro", "segmento", "brand", "marca", "family"},
    "location": {
        "location", "ubicacion", "canal", "channel", "tienda", "store", "local",
        "pdv", "cliente", "cd", "cedis", "centro", "planta", "region", "zona", "warehouse",
    },
    "horizon": {"horizon", "horizonte", "h", "lead_time", "lag", "bucket"},
}

_NULL_TOKENS = {"", "na", "n/a", "null", "none", "-", "nan"}
_FCST_SUFFIX = ("_fcst", "_forecast", "_pronostico", "_pred", "_yhat")
_ACT_SUFFIX = ("_real", "_actual", "_venta", "_ventas", "_demanda")


def _strip_accents(text: str) -> str:
    norm = unicodedata.normalize("NFD", text)
    return "".join(ch for ch in norm if unicodedata.category(ch) != "Mn")


def normalizar_columna(name: str) -> str:
    text = _strip_accents(name.strip().lower())
    text = text.replace("%", " pct ")
    text = re.sub(r"[\s\-./]+", "_", text)
    text = re.sub(r"_+", "_", text).strip("_")
    return text


def _canon(name: str) -> str | None:
    key = normalizar_columna(name)
    for canon, aliases in _ALIASES.items():
        if key in aliases:
            return canon
    return None


def parse_numero(raw) -> float | None:
    if raw is None:
        return None
    text = str(raw).strip()
    if text.lower() in _NULL_TOKENS:
        return None
    text = text.replace("\u00a0", "").replace(" ", "")
    for token in ("US$", "MXN", "$", "€"):
        text = text.replace(token, "")
    if text == "" or text.lower() in _NULL_TOKENS:
        return None
    negative = False
    if text.startswith("(") and text.endswith(")"):
        negative = True
        text = text[1:-1]
    if text.startswith("+"):
        text = text[1:]
    if text.startswith("-"):
        negative = not negative
        text = text[1:]
    if "," in text and "." in text:
        if text.rfind(",") > text.rfind("."):
            text = text.replace(".", "").replace(",", ".")
        else:
            text = text.replace(",", "")
    elif "," in text:
        if re.fullmatch(r"\d{1,3}(,\d{3})+", text):
            text = text.replace(",", "")
        else:
            text = text.replace(",", ".")
    elif text.count(".") > 1 or re.fullmatch(r"\d{1,3}(\.\d{3})+", text):
        text = text.replace(".", "")
    try:
        value = float(text)
    except ValueError as exc:
        raise ParseError(f"Número inválido: {raw}") from exc
    if value != value or value in (float("inf"), float("-inf")):
        raise ParseError(f"Número inválido: {raw}")
    return -value if negative else value


def parse_fecha(raw) -> date:
    text = str(raw).strip()
    if text.lower() in _NULL_TOKENS:
        raise ParseError("Fecha vacía.")
    for fmt, size in (
        ("%Y-%m-%d", None),
        ("%d/%m/%Y", None),
        ("%d-%m-%Y", None),
        ("%Y/%m/%d", None),
        ("%Y-%m", "month"),
        ("%Y/%m", "month"),
    ):
        try:
            parsed = datetime.strptime(text, fmt)
        except ValueError:
            continue
        if size == "month":
            return date(parsed.year, parsed.month, 1)
        return parsed.date()
    match = re.fullmatch(r"(\d{4})-?[Ww](\d{2})", text)
    if match:
        year, week = int(match.group(1)), int(match.group(2))
        if not 1 <= week <= 53:
            raise ParseError(f"Fecha inválida: {raw}")
        return date.fromisocalendar(year, week, 1)
    if re.fullmatch(r"\d{6}", text):
        year, month = int(text[:4]), int(text[4:])
        if 1 <= month <= 12:
            return date(year, month, 1)
    if re.fullmatch(r"\d{5}", text):
        serial = int(text)
        if 20000 <= serial <= 60000:
            return date(1899, 12, 30) + timedelta(days=serial)
    raise ParseError(f"Fecha inválida: {raw}")


def _sniff(text: str) -> str:
    sample = text[:8000]
    header = sample.splitlines()[0] if sample.splitlines() else ""
    if "\t" in header and header.count("\t") >= 1:
        return "\t"
    commas = header.count(",")
    semis = header.count(";")
    return ";" if semis > commas else ","


def _read_rows(text: str) -> tuple[list[str], list[list[str]], str]:
    if text.strip() == "":
        raise ParseError("El archivo está vacío: no hay datos para auditar.")
    delimiter = _sniff(text)
    reader = csv.reader(io.StringIO(text), delimiter=delimiter)
    rows = [row for row in reader if any(cell.strip() for cell in row)]
    if not rows:
        raise ParseError("El archivo está vacío: no hay datos para auditar.")
    header, data = rows[0], rows[1:]
    if not data:
        raise ParseError("El archivo solo tiene encabezado, sin datos para auditar.")
    return header, data, delimiter


def _fecha_de_encabezado(name: str) -> tuple[date, str] | None:
    base = name
    medida = "forecast"
    norm = normalizar_columna(name)
    for suffix in _FCST_SUFFIX:
        if norm.endswith(suffix):
            base = name[: -len(suffix)] if name.lower().endswith(suffix) else name
            # El sufijo se busca sobre el nombre normalizado; recortar por el original
            # es frágil si hay mayúsculas. Reconstruimos desde el normalizado.
            recorte = norm[: -len(suffix)].strip("_")
            base = recorte.replace("_", "-")
            medida = "forecast"
            break
    else:
        for suffix in _ACT_SUFFIX:
            if norm.endswith(suffix):
                recorte = norm[: -len(suffix)].strip("_")
                base = recorte.replace("_", "-")
                medida = "actual"
                break
        else:
            base = name.strip()
    try:
        return parse_fecha(base), medida
    except ParseError:
        return None


def _fila_larga(header: list[str], values: list[str], line_no: int, avisos: list[str]) -> dict:
    mapped: dict[str, str] = {}
    for name, value in zip(header, values):
        canon = _canon(name)
        if canon is None:
            continue
        if canon in mapped:
            raise ParseError(f"La columna {canon} está duplicada en el encabezado.")
        mapped[canon] = value
    if "product_id" not in mapped and "product_name" not in mapped:
        raise ParseError("Falta la columna de producto (SKU, producto o artículo).")
    if "date" not in mapped:
        raise ParseError("Falta la columna de fecha.")
    if "forecast" not in mapped:
        raise ParseError("Falta la columna de pronóstico (Pronóstico o forecast).")
    try:
        fecha = parse_fecha(mapped["date"])
    except ParseError as exc:
        raise ParseError(f"Fila {line_no}: {exc}") from exc
    try:
        forecast = parse_numero(mapped["forecast"])
    except ParseError as exc:
        raise ParseError(f"Fila {line_no}: {exc}") from exc
    if forecast is None:
        raise ParseError(f"Fila {line_no}: el pronóstico está vacío.")
    actual = None
    if "actual" in mapped:
        actual = parse_numero(mapped["actual"])
    lower = parse_numero(mapped["lower"]) if "lower" in mapped else None
    upper = parse_numero(mapped["upper"]) if "upper" in mapped else None
    if lower is not None and upper is not None and lower > upper:
        avisos.append(f"Fila {line_no}: el límite inferior supera al superior. Se sigue con salvedad.")
    product_id = (mapped.get("product_id") or "").strip()
    product_name = (mapped.get("product_name") or "").strip()
    if not product_id and not product_name:
        raise ParseError(f"Fila {line_no}: el producto está vacío.")
    return {
        "product_id": product_id or product_name,
        "product_name": product_name or product_id,
        "date": fecha,
        "forecast": forecast,
        "actual": actual,
        "model": (mapped.get("model") or "").strip() or None,
        "lower": lower,
        "upper": upper,
        "category": (mapped.get("category") or "").strip() or None,
        "location": (mapped.get("location") or "").strip() or None,
        "horizon": (mapped.get("horizon") or "").strip() or None,
        "linea": line_no,
    }


def _derretir(header: list[str], data: list[list[str]], avisos: list[str]) -> list[dict]:
    id_idx = []
    date_cols = []
    for i, name in enumerate(header):
        parsed = _fecha_de_encabezado(name)
        if parsed and _canon(name) is None:
            date_cols.append((i, parsed[0], parsed[1], name))
        else:
            id_idx.append(i)
    if len({item[1] for item in date_cols}) < 4 and len(date_cols) < 4:
        raise ParseError("Falta la columna de fecha.")
    records = []
    bucket: dict[tuple, dict] = {}
    for r, row in enumerate(data, start=2):
        base = {
            "product_id": "",
            "product_name": "",
            "model": None,
            "category": None,
            "location": None,
            "horizon": None,
            "lower": None,
            "upper": None,
        }
        for i in id_idx:
            if i >= len(row):
                continue
            canon = _canon(header[i])
            if canon in {"product_id", "product_name", "model", "category", "location", "horizon"}:
                value = row[i].strip()
                if canon in {"model", "category", "location", "horizon"}:
                    base[canon] = value or None
                else:
                    base[canon] = value
        if not base["product_id"] and not base["product_name"]:
            raise ParseError("Falta la columna de producto (SKU, producto o artículo).")
        if not base["product_id"]:
            base["product_id"] = base["product_name"]
        if not base["product_name"]:
            base["product_name"] = base["product_id"]
        for i, fecha, medida, _name in date_cols:
            raw = row[i] if i < len(row) else ""
            number = parse_numero(raw)
            key = (base["product_id"], base["location"] or "", fecha.isoformat())
            slot = bucket.get(key)
            if slot is None:
                slot = {
                    **base,
                    "date": fecha,
                    "forecast": None,
                    "actual": None,
                    "linea": r,
                }
                bucket[key] = slot
            if number is None:
                continue
            slot[medida] = number
        # no-op to keep r used when a row has no numbers
        _ = r
    for slot in bucket.values():
        if slot["forecast"] is None and slot["actual"] is None:
            continue
        if slot["forecast"] is None:
            avisos.append(
                f"Fila {slot['linea']}: {slot['product_id']} en {slot['date'].isoformat()} no tiene pronóstico."
            )
            continue
        records.append(slot)
    if not records:
        raise ParseError("Falta la columna de pronóstico (Pronóstico o forecast).")
    return records


def _colapsar_duplicados(records: list[dict]) -> list[dict]:
    grouped: dict[tuple, dict] = {}
    for rec in records:
        key = (rec["product_id"], rec["location"] or "", rec["date"].isoformat())
        prev = grouped.get(key)
        if prev is None:
            grouped[key] = rec
            continue
        same_fcst = abs(prev["forecast"] - rec["forecast"]) <= 1e-6 * max(abs(prev["forecast"]), abs(rec["forecast"]), 1)
        same_act = prev["actual"] == rec["actual"] or (
            prev["actual"] is not None
            and rec["actual"] is not None
            and abs(prev["actual"] - rec["actual"]) <= 1e-6 * max(abs(prev["actual"]), abs(rec["actual"]), 1)
        )
        if same_fcst and same_act:
            continue
        raise ParseError(
            "Hay fechas duplicadas para el mismo producto con valores distintos. No se promedian."
        )
    return list(grouped.values())


def parse_texto(text: str) -> dict:
    if text.startswith("\ufeff"):
        text = text[1:]
    header, data, delimiter = _read_rows(text)
    avisos: list[str] = []
    canons = [_canon(col) for col in header]
    tiene_fecha = "date" in canons
    tiene_forecast = "forecast" in canons
    if tiene_fecha and not tiene_forecast:
        raise ParseError("Falta la columna de pronóstico (Pronóstico o forecast).")
    if not tiene_fecha or not tiene_forecast:
        records = _derretir(header, data, avisos)
        layout = "ancho"
    else:
        if "product_id" not in canons and "product_name" not in canons:
            raise ParseError("Falta la columna de producto (SKU, producto o artículo).")
        if not tiene_forecast:
            raise ParseError("Falta la columna de pronóstico (Pronóstico o forecast).")
        records = [
            _fila_larga(header, row, i, avisos)
            for i, row in enumerate(data, start=2)
        ]
        layout = "largo"
    if "actual" not in canons and layout == "largo":
        avisos.append("No hay columna de venta real. Se audita el pronóstico sin medir el error contra la demanda.")
    records = _colapsar_duplicados(records)
    records.sort(key=lambda r: (r["product_id"], r["location"] or "", r["date"].isoformat()))
    columnas = {}
    for col in header:
        canon = _canon(col)
        if canon:
            columnas[col] = canon
    return {
        "filas": records,
        "avisos": avisos,
        "columnas": columnas,
        "layout": layout,
        "separador": delimiter,
        "tiene_actual": any(r["actual"] is not None for r in records),
        "tiene_intervalos": any(r["lower"] is not None and r["upper"] is not None for r in records),
    }


def parse_bytes(payload: bytes) -> dict:
    if not payload or not payload.strip():
        raise ParseError("El archivo está vacío: no hay datos para auditar.")
    for encoding in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            text = payload.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise ParseError("No se pudo leer el archivo como texto.")
    return parse_texto(text)
