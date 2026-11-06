"""Exporta la planilla ancha a CSV largo para motores de métricas."""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

from .parse import melt, parse_planilla_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Convierte la planilla ancha estándar a formato largo."
    )
    parser.add_argument("csv_in")
    parser.add_argument("csv_out")
    args = parser.parse_args(argv)
    series = parse_planilla_path(args.csv_in)
    filas = melt(series)
    if not filas:
        raise SystemExit("sin filas")
    out = Path(args.csv_out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(filas[0].keys()), lineterminator="\n")
        writer.writeheader()
        writer.writerows(filas)
    print(f"ok {len(series)} productos -> {len(filas)} filas en {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
