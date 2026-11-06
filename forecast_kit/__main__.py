"""CLI: python -m forecast_kit validate <csv>"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

from forecast_kit.validate import validate_path


def _cmd_validate(path: str, json_out: bool) -> int:
    book = validate_path(path)
    errors = book.errors
    warnings = book.warnings
    summary = {
        "path": book.path,
        "encoding": book.encoding,
        "products": len(book.products),
        "months": len(book.months),
        "errors": len(errors),
        "warnings": len(warnings),
        "error_codes": dict(Counter(i.code for i in errors)),
        "warning_codes": dict(Counter(i.code for i in warnings)),
        "models": dict(Counter(p.meta.get("Modelo", "") for p in book.products)),
        "ok": len(errors) == 0,
    }
    if json_out:
        payload = {
            **summary,
            "issues": [
                {
                    "severity": i.severity,
                    "code": i.code,
                    "message": i.message,
                    "row": i.row,
                    "product_id": i.product_id,
                    "column": i.column,
                }
                for i in book.issues
            ],
        }
        json.dump(payload, sys.stdout, ensure_ascii=False, indent=2)
        sys.stdout.write("\n")
    else:
        print(f"{path}  encoding={book.encoding}  products={len(book.products)}  months={len(book.months)}")
        print(f"errors={len(errors)}  warnings={len(warnings)}")
        if errors:
            print("error codes:", summary["error_codes"])
            for issue in errors[:20]:
                loc = f"row {issue.row}" if issue.row else "file"
                print(f"  ERROR [{issue.code}] {loc}: {issue.message}")
            if len(errors) > 20:
                print(f"  ... {len(errors) - 20} more")
        if warnings:
            print("warning codes:", summary["warning_codes"])
        print("OK" if not errors else "FAIL")
    return 0 if not errors else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="forecast_kit")
    sub = parser.add_subparsers(dest="cmd", required=True)
    v = sub.add_parser("validate", help="validate a standard planilla CSV")
    v.add_argument("csv")
    v.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    if args.cmd == "validate":
        if not Path(args.csv).is_file():
            print(f"not a file: {args.csv}", file=sys.stderr)
            return 2
        return _cmd_validate(args.csv, args.json)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
