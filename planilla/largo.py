"""Exporta el horizonte de pronóstico en formato largo.

Las apps que solo leen `producto, fecha, pronóstico` no reconocen los 30
atributos de la planilla ancha. Este export deja una fila por producto y mes,
de noviembre 2026 a diciembre 2027.
"""

from __future__ import annotations

import csv
from pathlib import Path

from planilla.schema import META_COLUMNS
from planilla.sheet import HISTORY_COUNT, Sheet, forecast_slice


LONG_HEADER = ("product_id", "SKU", "fecha", "pronostico", "modelo")


def write_long(sheet: Sheet, path: Path | str) -> int:
    destination = Path(path)
    id_at = META_COLUMNS.index("product_id")
    sku_at = META_COLUMNS.index("SKU")
    model_at = META_COLUMNS.index("Modelo")
    months = sheet.months()[HISTORY_COUNT:]
    written = 0
    with destination.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, delimiter=";", lineterminator="\n")
        writer.writerow(LONG_HEADER)
        for row in sheet.rows:
            for month, cell in zip(months, forecast_slice(row)):
                writer.writerow(
                    [
                        row[id_at],
                        row[sku_at],
                        month.strftime("%d/%m/%Y"),
                        cell.strip(),
                        row[model_at],
                    ]
                )
                written += 1
    return written
