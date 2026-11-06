"""CLI: python -m planilla audit|validate|compare"""

from __future__ import annotations

import argparse
import json
import sys

from planilla.checks import validate
from planilla.compare import compare_sheets
from planilla.sheet import fixture_path, load_fixture, load_sheet


def _print_report(report) -> None:
    state = "formato ok" if report.ok else "formato roto"
    print(f"{state} | {report.rows} filas | encoding {report.encoding}")
    print(f"archivo: {report.path}")
    for finding in report.errors:
        print(f"ERROR {finding.code} ({finding.count}) {finding.message}")
        for example in finding.examples:
            print(f"  - {example}")
    for finding in report.warnings:
        print(f"AVISO {finding.code} ({finding.count}) {finding.message}")
        for example in finding.examples:
            print(f"  - {example}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Verifica la planilla estándar de forecast en unidades."
    )
    sub = parser.add_subparsers(dest="command", required=True)

    audit = sub.add_parser("audit", help="Audita la planilla estándar incluida.")
    audit.add_argument("--json", action="store_true")

    validate_cmd = sub.add_parser("validate", help="Valida una planilla candidata.")
    validate_cmd.add_argument("path", nargs="?", help="CSV. Por defecto la planilla estándar.")
    validate_cmd.add_argument("--json", action="store_true")

    compare = sub.add_parser("compare", help="Compara una candidata contra la estándar.")
    compare.add_argument("path")
    compare.add_argument("--atol", type=float, default=0.01)
    compare.add_argument("--json", action="store_true")

    args = parser.parse_args(argv)

    if args.command == "audit":
        report = validate(load_fixture())
        if args.json:
            print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))
        else:
            _print_report(report)
        return 0 if report.ok else 1

    if args.command == "validate":
        path = args.path or fixture_path()
        report = validate(load_sheet(path))
        if args.json:
            print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))
        else:
            _print_report(report)
        return 0 if report.ok else 1

    candidate = load_sheet(args.path)
    golden = load_fixture()
    diff = compare_sheets(candidate, golden, atol=args.atol)
    if args.json:
        print(json.dumps(diff.to_dict(), ensure_ascii=False, indent=2))
    else:
        state = "igual a la estándar" if diff.identical else "difiere de la estándar"
        print(
            f"{state} | candidata {diff.candidate_rows} filas | estándar {diff.golden_rows}"
        )
        print(
            "faltan {m} | sobran {e} | meta {meta} | historia {h} | pronostico {f} | ilegibles {u}".format(
                m=len(diff.missing),
                e=len(diff.extra),
                meta=len(diff.meta_diffs),
                h=len(diff.history_diffs),
                f=len(diff.forecast_diffs),
                u=len(diff.unreadable),
            )
        )
        for bucket in (
            diff.missing,
            diff.extra,
            diff.meta_diffs,
            diff.history_diffs,
            diff.forecast_diffs,
            diff.unreadable,
        ):
            for example in bucket[:8]:
                print(f"  - {example}")
    return 0 if diff.identical else 1


if __name__ == "__main__":
    sys.exit(main())
