"""Exporta una muestra larga de la planilla estándar para la revisión en el navegador."""

from __future__ import annotations

import csv
from pathlib import Path

from planilla.contract import MODELOS, ROOT
from planilla.sheet import Sheet, load

SAMPLE_PATH = ROOT / "public" / "samples" / "planilla_mann_muestra.csv"
TIPOS = ("Con tendencia", "Intermitente", "Erratica", "Variable moderada")


def _fmt(value: float) -> str:
    if abs(value - round(value)) < 1e-9:
        return str(int(round(value)))
    text = f"{value:.2f}".rstrip("0").rstrip(".")
    return text.replace(".", ",")


def choose_rows(sheet: Sheet, limit: int = 12):
    chosen = []
    seen: set[str] = set()

    def add(row) -> None:
        if row is None or row.sku in seen or len(chosen) >= limit:
            return
        seen.add(row.sku)
        chosen.append(row)

    def first(predicate):
        return next((row for row in sheet.rows if row.sku not in seen and predicate(row)), None)

    add(sheet.by_sku.get("WL7413"))
    for model in MODELOS:
        add(first(lambda row, model=model: row.meta["Modelo"] == model))
    for tipo in TIPOS:
        add(first(lambda row, tipo=tipo: row.meta["Tipo de demanda"] == tipo))
    for abc in ("A", "B", "C"):
        add(first(lambda row, abc=abc: row.meta["ABC"] == abc))

    n_history = len(sheet.history_months)
    add(first(lambda row: len(set(row.forecast(n_history))) == 1))
    add(first(lambda row: any(value < 0 for value in row.history(n_history))))
    return chosen


def write_sample(sheet: Sheet, path: Path, limit: int = 12) -> int:
    rows = choose_rows(sheet, limit)
    n_history = len(sheet.history_months)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, delimiter=";", lineterminator="\n", quoting=csv.QUOTE_MINIMAL)
        writer.writerow(["sku", "producto", "familia", "fecha", "modelo", "pronostico", "real"])
        count = 0
        for row in rows:
            description = row.meta["Descripcion"] or row.sku
            family = row.meta["Subcategoria"] or row.meta["Categoria"]
            model = row.meta["Modelo"]
            for month, value in zip(sheet.history_months, row.history(n_history)):
                writer.writerow([row.sku, description, family, month.strftime("%d/%m/%Y"), model, "", _fmt(value)])
                count += 1
            for month, value in zip(sheet.forecast_months, row.forecast(n_history)):
                writer.writerow([row.sku, description, family, month.strftime("%d/%m/%Y"), model, _fmt(value), ""])
                count += 1
    return count
