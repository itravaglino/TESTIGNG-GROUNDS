from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from forecast_qa.diagnose import audit_product
from forecast_qa.metrics import naive_seasonal_holdout
from forecast_qa.parse import MannFormatError, parse_mann_csv
from forecast_qa.split import split_workbook


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Valida y audita una planilla Mann de pronósticos."
    )
    parser.add_argument("csv_path", type=Path)
    parser.add_argument("--json", action="store_true", help="Salida JSON (una línea por SKU + resumen).")
    parser.add_argument("--limit", type=int, default=0, help="Auditar solo N SKUs (0 = todos).")
    args = parser.parse_args(argv)

    try:
        book = parse_mann_csv(args.csv_path)
    except MannFormatError as exc:
        print(f"ERROR DE FORMATO: {exc}", file=sys.stderr)
        return 2

    start, splits = split_workbook(book)
    if args.limit:
        splits = splits[: args.limit]

    audits = []
    counts = {"MANTENER": 0, "CORREGIR": 0, "REVISAR": 0, "DESCARTAR": 0}
    for split in splits:
        audit = audit_product(split)
        counts[audit.verdict] = counts.get(audit.verdict, 0) + 1
        holdout = naive_seasonal_holdout(split.history)
        audits.append(
            {
                "product_id": audit.product_id,
                "sku": audit.sku,
                "verdict": audit.verdict,
                "vendor_model": audit.vendor_model,
                "vendor_error": audit.vendor_error,
                "demand_type": audit.demand_type,
                "recommended_models": list(audit.recommended_models),
                "findings": [
                    {"code": f.code, "severity": f.severity, "message": f.message}
                    for f in audit.findings
                ],
                "naive_holdout_wape": holdout.wape,
                "history_points": len(split.history),
                "forecast_points": len(split.forecast),
            }
        )

    summary = {
        "path": str(args.csv_path),
        "encoding": book.encoding,
        "products": len(book.products),
        "months": len(book.months),
        "month_from": book.month_headers[0],
        "month_to": book.month_headers[-1],
        "forecast_start": start.isoformat(),
        "verdicts": counts,
        "warnings": book.warnings[:20],
    }
    if args.json:
        print(json.dumps({"summary": summary, "products": audits}, ensure_ascii=False, indent=2))
    else:
        print(
            f"{summary['products']} SKUs | {summary['months']} meses "
            f"({summary['month_from']} → {summary['month_to']}) | "
            f"forecast desde {book.month_headers[book.months.index(start)]} | "
            f"encoding={summary['encoding']}"
        )
        print("veredictos:", counts)
        for row in audits[:25]:
            codes = ",".join(f["code"] for f in row["findings"]) or "-"
            wape = row["naive_holdout_wape"]
            wape_s = f"{wape:.2%}" if isinstance(wape, float) else "n/a"
            print(
                f"  {row['verdict']:10} {row['product_id']} {row['sku'][:20]:20} "
                f"{(row['demand_type'] or ''):18} naiveWAPE={wape_s:>8} {codes}"
            )
        if len(audits) > 25:
            print(f"  … {len(audits) - 25} SKUs más (usar --json)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
