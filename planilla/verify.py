"""Verifica la planilla estándar y compara otra salida contra ella."""

from __future__ import annotations

import csv
import statistics
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from planilla.contract import (
    AS_OF,
    EXPECTED_FORECAST_MONTHS,
    EXPECTED_HISTORY_MONTHS,
    EXPECTED_ROWS,
    FORECAST_END,
    HISTORY_START,
    MODELOS,
)
from planilla.sheet import Sheet, load, parse_month, parse_number


@dataclass
class Finding:
    level: str
    code: str
    detail: str


@dataclass
class Report:
    findings: list[Finding] = field(default_factory=list)

    def add(self, level: str, code: str, detail: str) -> None:
        self.findings.append(Finding(level, code, detail))

    @property
    def errors(self) -> list[Finding]:
        return [item for item in self.findings if item.level == "error"]

    @property
    def ok(self) -> bool:
        return not self.errors

    def render(self) -> str:
        lines = [
            f"resultado: {'ok' if self.ok else 'falló'}",
            f"errores: {len(self.errors)}",
            f"avisos: {sum(item.level == 'aviso' for item in self.findings)}",
            "",
        ]
        for item in self.findings:
            lines.append(f"[{item.level}] {item.code}: {item.detail}")
        return "\n".join(lines)


def _month_index(months: tuple[date, ...], month: date) -> int:
    return months.index(month)


def _yoy(current: float, previous: float) -> float | None:
    if previous == 0:
        return None
    return (current - previous) / previous * 100


def _count_close(
    sheet: Sheet,
    reported_column: str,
    actual,
    tolerance: float,
) -> tuple[int, int]:
    hits = 0
    eligible = 0
    for row in sheet.rows:
        value = actual(row)
        if value is None:
            continue
        eligible += 1
        if abs(value - row.number(reported_column)) <= tolerance:
            hits += 1
    return hits, eligible


def verify(sheet: Sheet) -> Report:
    report = Report()
    history = sheet.history_months
    forecast = sheet.forecast_months
    months = sheet.months

    if len(sheet.rows) != EXPECTED_ROWS:
        report.add("error", "filas", f"{len(sheet.rows)} filas, se esperaban {EXPECTED_ROWS}")
    else:
        report.add("ok", "filas", f"{EXPECTED_ROWS} productos")

    if not history or history[0] != HISTORY_START or history[-1] != AS_OF:
        report.add(
            "error",
            "historia",
            f"historia {history[:1]} … {history[-1:]} no es {HISTORY_START} … {AS_OF}",
        )
    elif len(history) != EXPECTED_HISTORY_MONTHS:
        report.add("error", "historia", f"{len(history)} meses de historia")
    else:
        report.add(
            "ok",
            "historia",
            f"{HISTORY_START.isoformat()} a {AS_OF.isoformat()} ({len(history)} meses)",
        )

    if not forecast or forecast[0] != date(2026, 11, 1) or forecast[-1] != FORECAST_END:
        report.add("error", "pronostico", "el horizonte no es 2026-11 a 2027-12")
    elif len(forecast) != EXPECTED_FORECAST_MONTHS:
        report.add("error", "pronostico", f"{len(forecast)} meses de pronóstico")
    else:
        report.add(
            "ok",
            "pronostico",
            "2026-11 a 2027-12 (14 meses)",
        )

    broken_step = [
        (prev, nxt)
        for prev, nxt in zip(months, months[1:])
        if (nxt.year - prev.year) * 12 + (nxt.month - prev.month) != 1
    ]
    if broken_step:
        report.add("error", "calendario", f"cortes de mes: {broken_step[:3]}")
    else:
        report.add("ok", "calendario", "meses consecutivos sin huecos")

    ids = [row.product_id for row in sheet.rows]
    skus = [row.sku for row in sheet.rows]
    if len(set(ids)) != len(ids) or any(not item for item in ids):
        report.add("error", "product_id", "hay product_id vacíos o repetidos")
    else:
        report.add("ok", "product_id", "únicos")
    if len(set(skus)) != len(skus) or any(not item for item in skus):
        report.add("error", "sku", "hay SKU vacíos o repetidos")
    else:
        report.add("ok", "sku", "únicos")

    modelos = {row.meta["Modelo"] for row in sheet.rows}
    if not modelos <= set(MODELOS):
        report.add("error", "modelo", f"modelos fuera de contrato: {sorted(modelos - set(MODELOS))}")
    else:
        report.add("ok", "modelo", ", ".join(sorted(modelos)))

    n_history = len(history)
    i_oct_2026 = _month_index(months, date(2026, 10, 1))
    i_oct_2025 = _month_index(months, date(2025, 10, 1))
    i_nov_2026 = _month_index(months, date(2026, 11, 1))
    i_nov_2025 = _month_index(months, date(2025, 11, 1))
    jan_oct_2026 = [_month_index(months, date(2026, month, 1)) for month in range(1, 11)]
    jan_oct_2025 = [_month_index(months, date(2025, month, 1)) for month in range(1, 11)]
    trailing = [_month_index(months, date(2025, 11, 1)), _month_index(months, date(2025, 12, 1))]
    trailing += [_month_index(months, date(2026, month, 1)) for month in range(1, 11)]
    prior = [_month_index(months, date(2024, 11, 1)), _month_index(months, date(2024, 12, 1))]
    prior += [_month_index(months, date(2025, month, 1)) for month in range(1, 11)]

    def check_rate(code: str, column: str, actual, minimum_hits: int, eligible_expected: int) -> None:
        hits, eligible = _count_close(sheet, column, actual, tolerance=1.0)
        if hits < minimum_hits or eligible != eligible_expected:
            report.add(
                "error",
                code,
                f"{hits}/{eligible} dentro de 1 punto (umbral {minimum_hits}/{eligible_expected})",
            )
        else:
            report.add("ok", code, f"{hits}/{eligible} dentro de 1 punto")

    check_rate(
        "mtd",
        "MTD",
        lambda row: _yoy(row.series[i_oct_2026], row.series[i_oct_2025]),
        1683,
        1698,
    )
    check_rate(
        "fytd",
        "FYTD",
        lambda row: _yoy(
            sum(row.series[i] for i in jan_oct_2026),
            sum(row.series[i] for i in jan_oct_2025),
        ),
        3278,
        3324,
    )
    check_rate(
        "ytd",
        "YTD",
        lambda row: _yoy(
            sum(row.series[i] for i in trailing),
            sum(row.series[i] for i in prior),
        ),
        3321,
        3373,
    )
    check_rate(
        "mtg",
        "MTG",
        lambda row: _yoy(row.series[i_nov_2026], row.series[i_nov_2025]),
        1926,
        1926,
    )

    std_bad = 0
    promedio_lejos = 0
    coef_bad = 0
    for row in sheet.rows:
        window = [row.series[i] for i in trailing]
        mean = statistics.fmean(window)
        std = statistics.pstdev(window)
        if abs(std - row.number("Desviacion Std")) > 0.01:
            std_bad += 1
        if abs(mean - row.number("Promedio")) > 1:
            promedio_lejos += 1
        reported_mean = row.number("Promedio")
        expected_cv = 0.0 if reported_mean == 0 else round(std / reported_mean, 2)
        if abs(expected_cv - row.number("Coeficiente")) > 0.011:
            coef_bad += 1
    if std_bad:
        report.add("error", "desviacion", f"{std_bad} filas no son el desvío poblacional de los últimos 12 meses")
    else:
        report.add("ok", "desviacion", "desvío poblacional de nov-2025 a oct-2026")
    if promedio_lejos > 30:
        report.add("error", "promedio", f"{promedio_lejos} filas se alejan más de 1 de la media de 12 meses")
    else:
        report.add(
            "aviso",
            "promedio",
            f"{promedio_lejos} filas se alejan más de 1 de la media nov-2025 a oct-2026; el resto coincide",
        )
    if coef_bad > 2:
        report.add("error", "coeficiente", f"{coef_bad} filas no son desvío/promedio redondeado a 2 decimales")
    else:
        report.add(
            "aviso" if coef_bad else "ok",
            "coeficiente",
            f"{coef_bad} filas no cierran desvío/promedio a 2 decimales",
        )

    neg_hist = sum(
        1 for row in sheet.rows if any(value < 0 for value in row.history(n_history))
    )
    neg_fc = sum(
        1 for row in sheet.rows if any(value < 0 for value in row.forecast(n_history))
    )
    if neg_fc:
        report.add("error", "pronostico_negativo", f"{neg_fc} filas con pronóstico negativo")
    else:
        report.add("ok", "pronostico_negativo", "el horizonte no tiene negativos")
    report.add(
        "aviso",
        "historia_negativa",
        f"{neg_hist} filas tienen al menos un mes histórico negativo",
    )

    flat = 0
    for row in sheet.rows:
        horizon = row.forecast(n_history)
        if len(set(horizon)) == 1 and abs(horizon[0] - round(horizon[0])) < 1e-9:
            flat += 1
    report.add(
        "aviso",
        "pronostico_plano",
        f"{flat} filas repiten el mismo entero en los 14 meses de pronóstico",
    )

    if any(row.meta["Familia"] for row in sheet.rows):
        report.add("error", "familia", "Familia dejó de estar vacía")
    else:
        report.add("aviso", "familia", "Familia está vacía en todas las filas")
    if any(row.number("Precio Unitario") or row.number("Costo Unitario") for row in sheet.rows):
        report.add("error", "precio", "apareció un precio o costo distinto de cero")
    else:
        report.add("aviso", "precio", "Precio Unitario y Costo Unitario están en cero")

    non_ascii = [
        row.sku
        for row in sheet.rows
        if any(ord(char) > 127 for value in row.meta.values() for char in value)
    ]
    if non_ascii:
        report.add(
            "aviso",
            "encoding",
            f"{len(non_ascii)} filas traen caracteres fuera de ASCII (cp1252); ejemplos: {', '.join(non_ascii[:6])}",
        )

    categorias = sorted({row.meta["Categoria"] for row in sheet.rows})
    if "PICK UP" in categorias and "Pick up" in categorias:
        report.add(
            "aviso",
            "categoria",
            "Categoria mezcla 'Pick up' y 'PICK UP'",
        )
    bloqueado = sum(1 for row in sheet.rows if row.meta["Region"] == "BLOQUEADO")
    report.add("aviso", "region_bloqueado", f"{bloqueado} filas con Region BLOQUEADO")
    report.add(
        "aviso",
        "metricas_de_escenario",
        "QTD, YTG, QTG y FYTG no se reproducen con un año contra año simple; se tratan como campos del escenario",
    )
    return report


def _read_flexible(path: Path) -> tuple[list[str], list[list[str]]]:
    raw = path.read_bytes()
    text = None
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            text = raw.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    if text is None:
        text = raw.decode("latin-1")
    sample = text.splitlines()[0] if text else ""
    delimiter = ";" if sample.count(";") >= sample.count(",") else ","
    reader = csv.reader(text.splitlines(), delimiter=delimiter)
    header = next(reader)
    return header, list(reader)


def compare(sheet: Sheet, other: Path) -> Report:
    """Compara el horizonte de pronóstico de otra planilla contra la estándar."""
    report = Report()
    header, records = _read_flexible(other)
    index = {name.strip(): position for position, name in enumerate(header)}
    key_name = "product_id" if "product_id" in index else "SKU" if "SKU" in index else None
    if key_name is None:
        report.add("error", "clave", "la otra planilla no tiene product_id ni SKU")
        return report

    month_positions: dict[date, int] = {}
    for name, position in index.items():
        try:
            month_positions[parse_month(name)] = position
        except ValueError:
            continue
    missing_months = [month for month in sheet.forecast_months if month not in month_positions]
    if missing_months:
        report.add(
            "error",
            "horizonte",
            "faltan meses de pronóstico: "
            + ", ".join(month.strftime("%d/%m/%Y") for month in missing_months[:6]),
        )
        return report

    lookup = sheet.by_product_id if key_name == "product_id" else sheet.by_sku
    seen: set[str] = set()
    matched = 0
    exact = 0
    abs_error = 0.0
    cells = 0
    extra = 0
    parse_errors = 0
    for record in records:
        if len(record) < len(header):
            record = record + [""] * (len(header) - len(record))
        key = record[index[key_name]].strip()
        row = lookup.get(key)
        if row is None:
            extra += 1
            continue
        seen.add(key)
        matched += 1
        row_exact = True
        for offset, month in enumerate(sheet.forecast_months):
            raw = record[month_positions[month]].strip()
            try:
                value = parse_number(raw)
            except ValueError:
                parse_errors += 1
                row_exact = False
                continue
            expected = row.forecast(len(sheet.history_months))[offset]
            abs_error += abs(value - expected)
            cells += 1
            if abs(value - expected) > 1e-6:
                row_exact = False
        if row_exact:
            exact += 1

    missing = len(lookup) - len(seen)
    report.add("ok", "cruce", f"{matched} filas cruzadas por {key_name}")
    if missing:
        report.add("aviso", "faltantes", f"{missing} claves de la planilla estándar no están en la otra")
    if extra:
        report.add("aviso", "extra", f"{extra} claves de la otra planilla no están en la estándar")
    if parse_errors:
        report.add("error", "numeros", f"{parse_errors} celdas de pronóstico no se pudieron leer")
    if cells == 0:
        report.add("error", "cruce", "no hubo celdas de pronóstico para comparar")
    else:
        report.add(
            "ok",
            "error_absoluto",
            f"MAE {abs_error / cells:.4f} sobre {cells} celdas; filas idénticas {exact}/{matched}",
        )
    return report
