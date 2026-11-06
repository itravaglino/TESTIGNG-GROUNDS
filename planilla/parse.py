from __future__ import annotations

import csv
import io
import json
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Iterable, Sequence

SCHEMA_PATH = Path(__file__).with_name("schema.json")
META_COLUMNS: tuple[str, ...] = tuple(
    json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))["columnas_meta"]
)


class ParseError(ValueError):
    """Error de contrato de la planilla (mensaje en español)."""


@dataclass(frozen=True)
class MonthValue:
    fecha: date
    valor: float | None
    crudo: str
    es_pronostico: bool


@dataclass
class ForecastSeries:
    product_id: str
    sku: str
    meta: dict[str, str]
    historia: list[MonthValue]
    pronostico: list[MonthValue]

    def meses(self) -> list[MonthValue]:
        return [*self.historia, *self.pronostico]

    def a_filas_largas(self) -> list[dict[str, object]]:
        filas = []
        for punto in self.meses():
            filas.append(
                {
                    "product_id": self.product_id,
                    "sku": self.sku,
                    "fecha": punto.fecha.isoformat(),
                    "valor": punto.valor,
                    "es_pronostico": punto.es_pronostico,
                    "actual": None if punto.es_pronostico else punto.valor,
                    "forecast": punto.valor if punto.es_pronostico else None,
                    "modelo": self.meta.get("Modelo", ""),
                    "categoria": self.meta.get("Categoria", ""),
                    "region": self.meta.get("Region", ""),
                    "tipo_de_demanda": self.meta.get("Tipo de demanda", ""),
                    "cluster": self.meta.get("Cluster", ""),
                    "abc": self.meta.get("ABC", ""),
                }
            )
        return filas


def parse_number(texto: str | None) -> float | None:
    """Convierte un número de la planilla (coma decimal, sin miles)."""
    if texto is None:
        return None
    s = str(texto).strip().replace("\xa0", "").replace(" ", "")
    if s == "":
        return None
    s = s.replace(",", ".")
    try:
        return float(s)
    except ValueError as exc:
        raise ParseError(f"número inválido: {texto!r}") from exc


def _parse_month_header(header: str) -> date | None:
    header = header.strip()
    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y"):
        try:
            dt = datetime.strptime(header, fmt).date()
        except ValueError:
            continue
        if dt.day != 1:
            raise ParseError(
                f"la columna de mes {header!r} no es el día 1; grano esperado mensual"
            )
        return dt
    return None


def _detect_delimiter(sample: str) -> str:
    first = sample.splitlines()[0] if sample else ""
    counts = {d: first.count(d) for d in (";", ",", "\t")}
    best = max(counts, key=counts.get)
    if counts[best] == 0:
        raise ParseError("no se detectó delimitador ; , o tab en el encabezado")
    return best


def _decode(raw: bytes) -> str:
    for enc in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            text = raw.decode(enc)
        except UnicodeDecodeError:
            continue
        text = text.replace("A\u0083A\u00a9", "é").replace("A\u00a1", "á")
        text = text.replace("A\x83A\xa9", "é").replace("A\xa1", "á")
        return text
    raise ParseError("no se pudo decodificar el archivo (utf-8 / cp1252 / latin-1)")


def _month_columns(header: Sequence[str]) -> list[tuple[int, date]]:
    months: list[tuple[int, date]] = []
    for i, name in enumerate(header):
        parsed = _parse_month_header(name)
        if parsed is not None:
            months.append((i, parsed))
    if not months:
        raise ParseError("no hay columnas de mes (se esperan encabezados DD/MM/YYYY)")
    fechas = [d for _, d in months]
    if fechas != sorted(fechas):
        raise ParseError("las columnas de mes no están en orden cronológico")
    for prev, cur in zip(fechas, fechas[1:]):
        delta = (cur.year - prev.year) * 12 + (cur.month - prev.month)
        if delta != 1:
            raise ParseError(
                f"salto de meses entre {prev.isoformat()} y {cur.isoformat()}"
            )
    return months


def detect_forecast_start(rows: Sequence[Sequence[str]], month_cols: Sequence[tuple[int, date]]) -> date:
    """Primera columna mensual donde la mayoría de valores no vacíos usa coma decimal."""
    n = len(rows)
    if n == 0:
        raise ParseError("el archivo no tiene filas de producto")
    for idx, fecha in month_cols:
        nonempty = 0
        with_comma = 0
        for row in rows:
            if idx >= len(row):
                continue
            cell = row[idx].strip()
            if cell == "":
                continue
            nonempty += 1
            if "," in cell:
                with_comma += 1
        if nonempty == 0:
            continue
        if with_comma / nonempty >= 0.5:
            return fecha
    last = month_cols[-1][1]
    # fallback: últimos 14 meses si el archivo coincide con la planilla conocida
    if len(month_cols) >= 14:
        return month_cols[-14][1]
    raise ParseError(f"no se pudo detectar el inicio del pronóstico (último mes {last})")


def parse_planilla(texto: str, *, source: str = "<memoria>") -> list[ForecastSeries]:
    if not texto.strip():
        raise ParseError("archivo vacío")
    delimiter = _detect_delimiter(texto)
    if delimiter != ";":
        raise ParseError(
            f"delimitador {delimiter!r} no es el estándar ';'. Convertí la planilla o usá el fixture oficial."
        )
    reader = csv.reader(io.StringIO(texto), delimiter=";")
    try:
        header = next(reader)
    except StopIteration as exc:
        raise ParseError("archivo vacío") from exc
    header = [h.strip() for h in header]
    missing = [c for c in META_COLUMNS if c not in header]
    if missing:
        raise ParseError(f"faltan columnas meta: {', '.join(missing)}")
    meta_prefix = header[: len(META_COLUMNS)]
    if meta_prefix != list(META_COLUMNS):
        raise ParseError(
            "el orden de las primeras 30 columnas no coincide con la planilla estándar"
        )
    month_cols = _month_columns(header)
    rows = [row for row in reader if any(cell.strip() for cell in row)]
    if not rows:
        raise ParseError("solo hay encabezado; no hay productos")
    ragged = [i for i, row in enumerate(rows, start=2) if len(row) != len(header)]
    if ragged:
        raise ParseError(f"filas con cantidad de columnas distinta al encabezado: {ragged[:8]}")

    ids = [row[header.index("product_id")].strip() for row in rows]
    if any(not x for x in ids):
        raise ParseError("hay filas sin product_id")
    dup = [x for x, n in _counts(ids).items() if n > 1]
    if dup:
        raise ParseError(f"product_id duplicado: {dup[:8]}")
    skus = [row[header.index("SKU")].strip() for row in rows]
    if any(not x for x in skus):
        raise ParseError("hay filas sin SKU")

    start_fcst = detect_forecast_start(rows, month_cols)
    series: list[ForecastSeries] = []
    for row in rows:
        meta = {name: row[header.index(name)].strip() for name in META_COLUMNS}
        historia: list[MonthValue] = []
        pronostico: list[MonthValue] = []
        for idx, fecha in month_cols:
            crudo = row[idx] if idx < len(row) else ""
            punto = MonthValue(
                fecha=fecha,
                valor=parse_number(crudo),
                crudo=crudo,
                es_pronostico=fecha >= start_fcst,
            )
            (pronostico if punto.es_pronostico else historia).append(punto)
        series.append(
            ForecastSeries(
                product_id=meta["product_id"],
                sku=meta["SKU"],
                meta=meta,
                historia=historia,
                pronostico=pronostico,
            )
        )
    series[0].meta["_source"] = source
    series[0].meta["_forecast_start"] = start_fcst.isoformat()
    return series


def parse_planilla_path(path: str | Path) -> list[ForecastSeries]:
    path = Path(path)
    raw = path.read_bytes()
    return parse_planilla(_decode(raw), source=str(path))


def melt(series: Iterable[ForecastSeries]) -> list[dict[str, object]]:
    filas: list[dict[str, object]] = []
    for item in series:
        filas.extend(item.a_filas_largas())
    return filas


def _counts(values: Sequence[str]) -> dict[str, int]:
    out: dict[str, int] = {}
    for v in values:
        out[v] = out.get(v, 0) + 1
    return out
