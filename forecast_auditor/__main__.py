"""Auditoría por consola: python -m forecast_auditor archivo.csv -o informe.json"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from forecast_auditor.pipeline import analyze_frame
from forecast_auditor.sample_data import demo_frame
from forecast_auditor.schema import MAX_BYTES, read_table


def main() -> None:
    parser = argparse.ArgumentParser(description="Audita un forecast producto por producto.")
    parser.add_argument("archivo", nargs="?", help="CSV o XLSX. Si se omite, usa el ejemplo.")
    parser.add_argument("-o", "--output", help="Ruta del informe JSON.")
    parser.add_argument("--csv", help="Ruta del CSV con el pronóstico corregido y los descartes.")
    args = parser.parse_args()

    if args.archivo:
        path = Path(args.archivo)
        if path.stat().st_size > MAX_BYTES:
            raise SystemExit("El archivo supera el límite de 8 MB.")
        frame = read_table(args.archivo, path.read_bytes())
    else:
        frame = demo_frame()
    report = analyze_frame(frame)
    _print(report)
    if args.output:
        Path(args.output).write_text(json.dumps(_public(report), ensure_ascii=False, indent=2), encoding="utf-8")
    if args.csv:
        pd.DataFrame(_rows(report)).to_csv(args.csv, index=False)


def _print(report: dict) -> None:
    summary = report["resumen"]
    print(
        f"Productos {summary['productos']} · mantener {summary['mantener']} · "
        f"corregir {summary['corregir']} · descartar {summary['descartar']}"
    )
    for product in report["productos"]:
        wmape = product["antes"].get("wmape")
        wmape_txt = "s/d" if not isinstance(wmape, float) else f"{wmape * 100:.1f}%"
        print(f"  [{product['veredicto']}] {product['id']} · puntaje {product['puntaje']} · WMAPE {wmape_txt}")
        for reason in product["motivos"][:2]:
            print(f"     - {reason}")


def _public(report: dict) -> dict:
    cleaned = json.loads(json.dumps(report, default=str))
    for product in cleaned["productos"]:
        product.pop("exportacion", None)
        product.pop("serie", None)
    return cleaned


def _rows(report: dict) -> list[dict]:
    rows: list[dict] = []
    for product in report["productos"]:
        rows.extend(product["exportacion"])
    return rows


if __name__ == "__main__":
    main()
