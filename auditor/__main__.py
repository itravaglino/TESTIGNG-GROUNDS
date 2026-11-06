"""Informe de consola: python -m auditor archivo.csv"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

from auditor.audit import auditar_texto, filas_dictamen, filas_forecast_corregido
from auditor.parse import ParseError


def _escribir(path: Path, filas: list[dict]) -> None:
    if not filas:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(filas[0].keys()), delimiter=";")
        writer.writeheader()
        writer.writerows(filas)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Audita un forecast producto por producto.")
    parser.add_argument("archivo", type=Path, help="CSV o TSV de forecast")
    parser.add_argument("--salida", type=Path, default=Path("salida_auditor"), help="Carpeta de los CSV")
    args = parser.parse_args(argv)
    try:
        resultado = auditar_texto(args.archivo.read_text(encoding="utf-8-sig"))
    except ParseError as exc:
        print(exc, file=sys.stderr)
        return 1
    port = resultado["portafolio"]
    print(f"Productos {port['productos']}  ·  mantener {port['mantener']}  ·  corregir {port['corregir']}  ·  descartar {port['descartar']}")
    if port.get("wape") is not None:
        print(f"WAPE global {port['wape']:.3f}  ·  sesgo {port['sesgo']:.3f}  ·  FVA vs naive {port['fva_vs_naive']}")
    for p in resultado["productos"]:
        wape = "—" if p["wape"] is None else f"{p['wape']:.3f}"
        print(f"{p['estado']:<10} {p['producto']:<16} WAPE {wape:<8} {p['modelo_recomendado']}")
    args.salida.mkdir(parents=True, exist_ok=True)
    _escribir(args.salida / "dictamen.csv", filas_dictamen(resultado))
    _escribir(args.salida / "forecast_corregido.csv", filas_forecast_corregido(resultado))
    print(f"CSV en {args.salida}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
