"""python -m planilla verify | compare RUTA | show SKU"""

import sys
from pathlib import Path

from planilla.export_sample import SAMPLE_PATH, write_sample
from planilla.sheet import load
from planilla.verify import compare, verify


def _fmt(value: float) -> str:
    if abs(value - round(value)) < 1e-9:
        return str(int(round(value)))
    return f"{value:.2f}"


def main(argv: list[str]) -> int:
    if not argv or argv[0] in {"-h", "--help", "help"}:
        print(
            "uso:\n"
            "  python3 -m planilla verify\n"
            "  python3 -m planilla compare RUTA.csv\n"
            "  python3 -m planilla show SKU\n"
            "  python3 -m planilla export-muestra"
        )
        return 0
    command, *rest = argv
    sheet = load()
    if command == "verify":
        report = verify(sheet)
        print(report.render())
        return 0 if report.ok else 1
    if command == "compare":
        if not rest:
            print("falta la ruta de la otra planilla", file=sys.stderr)
            return 2
        report = compare(sheet, Path(rest[0]))
        print(report.render())
        return 0 if report.ok else 1
    if command == "show":
        if not rest:
            print("falta el SKU", file=sys.stderr)
            return 2
        row = sheet.by_sku.get(rest[0])
        if row is None:
            print(f"SKU no está en la planilla estándar: {rest[0]}", file=sys.stderr)
            return 1
        history = sheet.history_months
        forecast = sheet.forecast_months
        print(f"product_id {row.product_id}")
        print(f"cliente {row.meta['Cliente']}  categoria {row.meta['Categoria']}")
        print(f"modelo {row.meta['Modelo']}  demanda {row.meta['Tipo de demanda']}")
        print(f"promedio {row.meta['Promedio']}  desvio {row.meta['Desviacion Std']}")
        print("historia (últimos 3 meses)")
        for month, value in list(zip(history, row.history(len(history))))[-3:]:
            print(f"  {month.isoformat()}  {_fmt(value)}")
        print("pronostico")
        for month, value in zip(forecast, row.forecast(len(history))):
            print(f"  {month.isoformat()}  {_fmt(value)}")
        return 0
    if command == "export-muestra":
        target = Path(rest[0]) if rest else SAMPLE_PATH
        written = write_sample(sheet, target)
        print(f"muestra escrita en {target} ({written} filas)")
        return 0
    print(f"comando desconocido: {command}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
