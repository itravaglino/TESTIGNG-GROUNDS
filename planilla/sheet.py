"""Lectura y escritura del CSV estándar (punto y coma, decimal con coma)."""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from pathlib import Path

from planilla.schema import (
    ATTRIBUTE_COLUMNS,
    EXPECTED_HEADER,
    FORECAST_LABELS,
    OFFICIAL_ENCODING,
    OFFICIAL_NEWLINE,
)

NUMBER_RE_SOURCE = r"-?(?:0|[1-9]\d*)(?:,\d{1,2})?"


@dataclass
class Sheet:
    """Planilla ya parseada. ``rows`` conserva el texto original de cada celda."""

    header: list[str]
    rows: list[list[str]]
    encoding: str
    newline: str
    path: str | None = None

    def column_index(self) -> dict[str, int]:
        return {name: index for index, name in enumerate(self.header)}

    def product_ids(self) -> list[str]:
        if "product_id" not in self.column_index():
            return []
        index = self.column_index()["product_id"]
        return [row[index] if index < len(row) else "" for row in self.rows]


def read_sheet(path: str | Path) -> Sheet:
    raw = Path(path).read_bytes()
    encoding = "utf-8"
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        encoding = OFFICIAL_ENCODING
        text = raw.decode(OFFICIAL_ENCODING)
    if b"\r\n" in raw:
        newline = "\r\n"
    elif b"\n" in raw:
        newline = "\n"
    else:
        newline = ""
    reader = csv.reader(io.StringIO(text, newline=""), delimiter=";")
    table = list(reader)
    if table and table[-1] == []:
        table.pop()
    if not table:
        return Sheet(header=[], rows=[], encoding=encoding, newline=newline, path=str(path))
    return Sheet(
        header=table[0],
        rows=table[1:],
        encoding=encoding,
        newline=newline,
        path=str(path),
    )


def write_sheet(path: str | Path, sheet: Sheet, encoding: str = OFFICIAL_ENCODING) -> None:
    """Escribe con el dialecto oficial: cp1252, CRLF, separador ``;``."""
    with Path(path).open("w", encoding=encoding, newline="") as handle:
        writer = csv.writer(
            handle,
            delimiter=";",
            lineterminator=OFFICIAL_NEWLINE,
            quoting=csv.QUOTE_MINIMAL,
        )
        writer.writerow(sheet.header)
        writer.writerows(sheet.rows)


def example_sheet(rows: int = 1) -> Sheet:
    """Planilla mínima que cumple el contrato. Sirve de plantilla para otros modelos."""
    if rows < 1:
        raise ValueError("rows debe ser >= 1")
    body: list[list[str]] = []
    for offset in range(rows):
        product_id = f"{722344 + offset:06d}"
        values = {
            "product_id": product_id,
            "Familia": "",
            "Region": "MTO",
            "Vendedor": "",
            "Cliente": "MANN-FILTER",
            "Categoria": "PC",
            "Subcategoria": "Oil Filter",
            "SKU": f"SKU-{product_id}",
            "Descripcion": "ejemplo",
            "Tipo de demanda": "Erratica",
            "Cluster": "Alto riesgo",
            "Error": "0",
            "ABC": "C",
            "Promedio": "0",
            "Desviacion Std": "0",
            "Coeficiente": "0",
            "YTD": "0",
            "QTD": "0",
            "MTD": "0",
            "FYTD": "0",
            "YTG": "0",
            "QTG": "0",
            "MTG": "0",
            "FYTG": "0",
            "Modelo": "auto_SARIMA",
            "Precio Unitario": "0",
            "Costo Unitario": "0",
            "Reemplazado?": "No",
            "Reemplazado por": "N/A",
            "Descontinuado?": "No",
        }
        record = [values[name] for name in ATTRIBUTE_COLUMNS]
        for label in EXPECTED_HEADER[len(ATTRIBUTE_COLUMNS) :]:
            record.append("1,50" if label in FORECAST_LABELS else "0")
        body.append(record)
    return Sheet(
        header=list(EXPECTED_HEADER),
        rows=body,
        encoding=OFFICIAL_ENCODING,
        newline=OFFICIAL_NEWLINE,
    )
