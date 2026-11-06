#!/usr/bin/env python3
"""Verifica la planilla estándar o compara un pronóstico candidato.

Ejemplos:
  python scripts/verificar_planilla.py fixtures/planilla_estandar.csv
  python scripts/verificar_planilla.py --contra fixtures/planilla_estandar.csv candidato.csv
  python scripts/verificar_planilla.py --largo fixtures/planilla_estandar_muestra.csv -o /tmp/largo.csv
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from planilla.contrato import PRONOSTICO_DESDE, PRONOSTICO_HASTA
from planilla.parser import cargar
from planilla.verificar import comparar, meses_entre, verificar


def exportar_largo(origen: Path, destino: Path, solo_pronostico: bool) -> int:
    planilla = cargar(origen)
    meses = meses_entre(PRONOSTICO_DESDE, PRONOSTICO_HASTA) if solo_pronostico else planilla.meses
    destino.parent.mkdir(parents=True, exist_ok=True)
    with destino.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh, delimiter=";")
        writer.writerow(
            ["product_id", "SKU", "fecha", "unidades", "origen", "Modelo", "Tipo de demanda"]
        )
        n = 0
        for fila in planilla.filas:
            for mes in meses:
                if mes not in fila.serie:
                    continue
                origen_mes = "pronostico" if mes >= PRONOSTICO_DESDE else "historia"
                writer.writerow(
                    [
                        fila.product_id,
                        fila.sku,
                        mes.isoformat(),
                        f"{fila.serie[mes]:.4f}".rstrip("0").rstrip("."),
                        origen_mes,
                        fila.atributos.get("Modelo", ""),
                        fila.atributos.get("Tipo de demanda", ""),
                    ]
                )
                n += 1
    return n


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archivo", type=Path, help="Planilla a verificar, o la estándar si hay --contra")
    parser.add_argument("--contra", type=Path, help="Planilla estándar contra la que se compara archivo")
    parser.add_argument("--tolerancia", type=float, default=0.01)
    parser.add_argument("--json", action="store_true", dest="como_json")
    parser.add_argument("--larga", action="store_true", help="Exigir las 4402 filas")
    parser.add_argument("--largo", action="store_true", help="Exportar a formato largo y salir")
    parser.add_argument("-o", "--salida", type=Path)
    parser.add_argument(
        "--solo-pronostico",
        action="store_true",
        help="Al exportar, solo nov-2026 a dic-2027",
    )
    args = parser.parse_args(argv)

    if args.largo:
        if args.salida is None:
            parser.error("--largo requiere --salida")
        n = exportar_largo(args.archivo, args.salida, args.solo_pronostico)
        print(f"Exportadas {n} filas a {args.salida}")
        return 0

    if args.contra:
        resultado = comparar(str(args.contra), str(args.archivo), tolerancia=args.tolerancia)
    else:
        resultado = verificar(str(args.archivo), completa=True if args.larga else None)

    if args.como_json:
        print(
            json.dumps(
                {
                    "ok": resultado.ok,
                    "titulo": resultado.titulo,
                    "metricas": resultado.metricas,
                    "errores": resultado.errores,
                    "avisos": resultado.avisos,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        print(resultado.texto())
    return 0 if resultado.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
