"""Defectos de contenido de la planilla estándar.

No hacen fallar el contrato: el export real los trae. Quien regenere el archivo
tiene que verlos para no corregirlos en silencio ni copiarlos sin darse cuenta.
"""

from __future__ import annotations

import re

from planilla.schema import FORECAST_LABELS, HISTORY_MONTHS, TYPICAL_CLUSTERS, month_label
from planilla.sheet import Sheet
from planilla.validate import Issue, Report, parse_number

_MOJIBAKE = re.compile(r"A¡|Aƒ|Ã|Â")
_SCIENTIFIC_SKU = re.compile(r"^\d+,\d+E\+\d+$", re.IGNORECASE)
_ZERO_TOKENS = frozenset({"0", "0,0", "0,00"})
_HISTORY_ORDER = tuple(month_label(day) for day in HISTORY_MONTHS)

_TEXT_COLUMNS = (
    "Familia",
    "Region",
    "Vendedor",
    "Cliente",
    "Categoria",
    "Subcategoria",
    "SKU",
    "Descripcion",
    "Reemplazado por",
)


def audit(sheet: Sheet) -> Report:
    report = Report()
    index = {name: position for position, name in enumerate(sheet.header)}
    needed = set(_TEXT_COLUMNS) | {
        "product_id",
        "Tipo de demanda",
        "Cluster",
        "Precio Unitario",
        "Costo Unitario",
    }
    if not needed.issubset(index) or any(label not in index for label in FORECAST_LABELS):
        report.add(
            Issue(
                "warning",
                "AUDIT_SKIPPED",
                "No se auditó el contenido porque el encabezado no es el de la planilla estándar.",
            )
        )
        return report

    empty_familia = 0
    empty_description = 0
    zero_price = 0
    zero_forecast = 0
    negative_cells = 0

    for offset, row in enumerate(sheet.rows):
        if len(row) != len(sheet.header):
            continue
        file_row = offset + 2
        product_id = row[index["product_id"]]
        if row[index["Familia"]] == "":
            empty_familia += 1
        if row[index["Descripcion"]] == "":
            empty_description += 1
        if row[index["Vendedor"]] != "":
            _warn(
                report,
                "VENDEDOR_LLENO",
                f"Vendedor={row[index['Vendedor']]!r}. En el estándar casi todas las filas vienen vacías y las pocas llenas dicen '1'.",
                file_row,
                "Vendedor",
                product_id,
            )
        if row[index["Precio Unitario"]] == "0" and row[index["Costo Unitario"]] == "0":
            zero_price += 1
        if row[index["Region"]] == "BLOQUEADO":
            _warn(
                report,
                "REGION_BLOQUEADO",
                "Region=BLOQUEADO no es una región de venta; el producto está bloqueado.",
                file_row,
                "Region",
                product_id,
            )
        if row[index["Categoria"]] == "PICK UP":
            _warn(
                report,
                "CATEGORIA_PICK_UP",
                "Categoria='PICK UP' convive con 'Pick up'. Es la misma categoría con otra caja.",
                file_row,
                "Categoria",
                product_id,
            )
        demand = row[index["Tipo de demanda"]]
        cluster = row[index["Cluster"]]
        typical = TYPICAL_CLUSTERS.get(demand)
        if typical is not None and cluster not in typical:
            _warn(
                report,
                "CLUSTER_ATIPICO",
                f"Tipo de demanda {demand!r} con cluster {cluster!r} no es la combinación habitual.",
                file_row,
                "Cluster",
                product_id,
            )
        sku = row[index["SKU"]]
        if _SCIENTIFIC_SKU.fullmatch(sku):
            _warn(
                report,
                "SKU_CIENTIFICO",
                f"SKU {sku!r} tiene forma de notación científica de Excel, no de un código de filtro.",
                file_row,
                "SKU",
                product_id,
            )
        blob = " ".join(row[index[name]] for name in _TEXT_COLUMNS)
        if _MOJIBAKE.search(blob):
            _warn(
                report,
                "MOJIBAKE",
                "Hay texto con acentos rotos (A¡, Aƒ, Ã). Parte del texto ya llegó mal codificado.",
                file_row,
                "Descripcion",
                product_id,
            )
        negatives = [
            label
            for label in _HISTORY_ORDER
            if _is_negative(row[index[label]])
        ]
        if negatives:
            negative_cells += len(negatives)
            first = negatives[0]
            _warn(
                report,
                "REAL_NEGATIVO",
                f"{len(negatives)} meses reales negativos; el primero es {first}={row[index[first]]}.",
                file_row,
                first,
                product_id,
            )
        if all(row[index[label]] in _ZERO_TOKENS for label in FORECAST_LABELS):
            zero_forecast += 1

    total = len(sheet.rows)
    _note(
        report,
        "FAMILIA_VACIA",
        empty_familia,
        "Familia está vacía en todas las filas."
        if empty_familia == total
        else f"Familia vacía en {empty_familia} de {total} filas.",
    )
    _note(report, "DESCRIPCION_VACIA", empty_description, f"Descripcion vacía en {empty_description} filas.")
    _note(
        report,
        "PRECIO_Y_COSTO_CERO",
        zero_price if zero_price == total and total else 0,
        "Precio Unitario y Costo Unitario son 0 en todas las filas. Esta planilla es de unidades, no de dinero.",
    )
    if zero_price != total:
        report.counts["PRECIO_Y_COSTO_CERO"] = 0
    _note(
        report,
        "PRONOSTICO_CERO",
        zero_forecast,
        f"{zero_forecast} filas tienen pronóstico 0 de noviembre 2026 a diciembre 2027.",
    )
    report.counts["REAL_NEGATIVO_CELDAS"] = negative_cells
    return report


def _warn(
    report: Report,
    code: str,
    message: str,
    row: int,
    column: str,
    product_id: str,
) -> None:
    report.add(
        Issue(
            "warning",
            code,
            message,
            row=row,
            column=column,
            product_id=product_id or None,
        )
    )


def _note(report: Report, code: str, count: int, message: str) -> None:
    report.counts[code] = count
    if count:
        report.issues.append(Issue("warning", code, message))


def _is_negative(token: str) -> bool:
    try:
        return parse_number(token) < 0
    except ValueError:
        return False
