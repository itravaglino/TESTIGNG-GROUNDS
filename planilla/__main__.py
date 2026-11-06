"""CLI: python -m planilla check|audit|diff|spec|example"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from planilla.audit import audit
from planilla.diff import diff_sheets
from planilla.schema import (
    ABC_CLASSES,
    AS_OF,
    CATEGORIES,
    CLIENTS,
    CLUSTERS,
    DEMAND_TYPES,
    EXPECTED_HEADER,
    FORECAST_MONTHS,
    HISTORY_MONTHS,
    MODELS,
    OFFICIAL_ENCODING,
    REGIONS,
    SERIES_END,
    SERIES_START,
    month_label,
)
from planilla.sheet import example_sheet, read_sheet, write_sheet
from planilla.validate import Report, validate

GOLDEN = Path(__file__).resolve().parents[1] / "fixtures" / "Forecast_mann_scenario_test4_unidades.csv"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m planilla")
    sub = parser.add_subparsers(dest="command", required=True)

    check = sub.add_parser("check", help="valida el contrato de una planilla")
    check.add_argument("path")

    audit_cmd = sub.add_parser("audit", help="lista defectos de contenido conocidos")
    audit_cmd.add_argument("path")

    diff = sub.add_parser("diff", help="compara un candidato contra la planilla estándar")
    diff.add_argument("path")
    diff.add_argument("--against", default=str(GOLDEN))

    sub.add_parser("spec", help="imprime el contrato")
    example = sub.add_parser("example", help="escribe una planilla mínima válida")
    example.add_argument("path")
    example.add_argument("--rows", type=int, default=1)

    args = parser.parse_args(argv)
    if args.command == "spec":
        _print_spec()
        return 0
    if args.command == "example":
        write_sheet(args.path, example_sheet(args.rows))
        print(f"escribí {args.rows} fila(s) en {args.path}")
        return 0
    if args.command == "check":
        return _check(args.path)
    if args.command == "audit":
        sheet = read_sheet(args.path)
        contract = validate(sheet)
        _print_report("contrato", contract)
        _print_report("auditoría", audit(sheet))
        return 0 if contract.ok else 1
    report = diff_sheets(read_sheet(args.path), read_sheet(args.against))
    return _print_diff(report, args.against)


def _check(path: str) -> int:
    sheet = read_sheet(path)
    report = validate(sheet)
    _print_report("contrato", report)
    if report.ok:
        print(f"OK {path}: {len(sheet.rows)} filas, {len(sheet.header)} columnas, encoding {sheet.encoding}.")
        return 0
    print(f"FALLÓ {path}.")
    return 1


def _print_report(title: str, report: Report) -> None:
    print(f"== {title} ==")
    if not report.counts:
        print("sin hallazgos")
        return
    for code, count in sorted(report.counts.items()):
        print(f"  {code}: {count}")
    for issue in report.issues:
        where = []
        if issue.row is not None:
            where.append(f"fila {issue.row}")
        if issue.product_id:
            where.append(f"id {issue.product_id}")
        if issue.column:
            where.append(issue.column)
        prefix = f" ({', '.join(where)})" if where else ""
        print(f"  - [{issue.severity}] {issue.code}{prefix}: {issue.message}")


def _print_diff(report, against: str) -> int:
    print(f"referencia: {against}")
    print(f"filas en común: {report.comparable_rows}")
    print(f"solo en el candidato: {len(report.missing_right)}")
    print(f"solo en la referencia: {len(report.missing_left)}")
    print(f"celdas con otro valor: {report.value_count}")
    print(f"celdas con el mismo número y otro formato: {report.format_count}")
    for product_id in report.missing_right[:8]:
        print(f"  - candidato de más: {product_id}")
    for product_id in report.missing_left[:8]:
        print(f"  - falta en el candidato: {product_id}")
    for item in report.value_diffs:
        print(f"  - valor id {item.product_id} {item.column}: {item.left!r} != {item.right!r}")
    for item in report.format_diffs:
        print(f"  - formato id {item.product_id} {item.column}: {item.left!r} vs {item.right!r}")
    if report.ok:
        print("OK sin diferencias de valor.")
        return 0
    print("FALLÓ la comparación.")
    return 1


def _print_spec() -> None:
    print("Planilla estándar de forecast, escenario de unidades.")
    print(f"Encoding oficial: {OFFICIAL_ENCODING}. Separador: punto y coma. Fin de línea: CRLF.")
    print(f"Serie: {month_label(SERIES_START)} a {month_label(SERIES_END)} ({len(EXPECTED_HEADER) - 30} meses).")
    print(f"Reales enteros hasta {month_label(AS_OF)} ({len(HISTORY_MONTHS)} meses). Pueden ser negativos.")
    print(f"Pronóstico desde {month_label(FORECAST_MONTHS[0])} ({len(FORECAST_MONTHS)} meses): >= 0, coma decimal, hasta 2 decimales.")
    print("Números: sin separador de miles, sin punto decimal. 8415,25 es válido. 8.415,25 y 8415.25 no.")
    print(f"Columnas fijas ({len(EXPECTED_HEADER)}):")
    print("  " + ";".join(EXPECTED_HEADER[:30]) + ";<meses>")
    print("Enums:")
    print("  Tipo de demanda: " + ", ".join(sorted(DEMAND_TYPES)))
    print("  Cluster: " + ", ".join(sorted(CLUSTERS)))
    print("  ABC: " + ", ".join(sorted(ABC_CLASSES)))
    print("  Modelo: " + ", ".join(sorted(MODELS)))
    print("  Cliente: " + ", ".join(sorted(CLIENTS)))
    print("  Region: " + ", ".join(sorted(REGIONS)))
    print("  Categoria: " + ", ".join(sorted(CATEGORIES)))
    print("product_id: 6 dígitos, único. SKU: texto único, no vacío.")
    print(f"Referencia: {GOLDEN}")


if __name__ == "__main__":
    sys.exit(main())
