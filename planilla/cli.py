"""CLI: python -m planilla.cli validate|profile PATH"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

from .parse import parse_csv
from .validate import validate_workbook


def cmd_validate(path: Path) -> int:
    book = parse_csv(path)
    result = validate_workbook(book)
    payload = {
        "ok": result.ok,
        "encoding": book.encoding,
        "n_products": len(book.products),
        "n_history": len(book.history_months),
        "n_forecast": len(book.forecast_months),
        "history_end": book.history_months[-1].isoformat() if book.history_months else None,
        "forecast_start": book.forecast_months[0].isoformat() if book.forecast_months else None,
        "errors": result.errors,
        "warnings": result.warnings[:40],
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if result.ok else 1


def cmd_profile(path: Path) -> int:
    book = parse_csv(path)
    dist: dict[str, dict[str, int]] = {}
    for key in ("Tipo de demanda", "Cluster", "ABC", "Modelo", "Region", "Cliente"):
        dist[key] = dict(Counter(p.meta.get(key, "") for p in book.products))
    payload = {
        "encoding": book.encoding,
        "n_products": len(book.products),
        "n_columns": len(book.headers),
        "history_start": book.history_months[0].isoformat() if book.history_months else None,
        "history_end": book.history_months[-1].isoformat() if book.history_months else None,
        "forecast_start": book.forecast_months[0].isoformat() if book.forecast_months else None,
        "forecast_end": book.forecast_months[-1].isoformat() if book.forecast_months else None,
        "distributions": dist,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="planilla")
    parser.add_argument("command", choices=("validate", "profile"))
    parser.add_argument("path", type=Path)
    args = parser.parse_args(argv)
    if args.command == "validate":
        return cmd_validate(args.path)
    return cmd_profile(args.path)


if __name__ == "__main__":
    sys.exit(main())
