"""Lectura de la planilla estándar (punto y coma, decimales con coma)."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from planilla.schema import (
    FORECAST_END,
    FORECAST_START,
    HISTORY_END,
    HISTORY_START,
    META_COLUMNS,
)


FIXTURE_NAME = "forecast_mann_scenario_test4_unidades.csv"


def fixture_path() -> Path:
    return Path(__file__).resolve().parents[1] / "fixtures" / FIXTURE_NAME


def _month_range(start: date, end: date) -> list[date]:
    months: list[date] = []
    year, month = start.year, start.month
    while (year, month) <= (end.year, end.month):
        months.append(date(year, month, 1))
        month += 1
        if month == 13:
            month = 1
            year += 1
    return months


EXPECTED_MONTHS: tuple[date, ...] = tuple(_month_range(HISTORY_START, FORECAST_END))
HISTORY_COUNT = sum(1 for month in EXPECTED_MONTHS if month <= HISTORY_END)
FORECAST_COUNT = len(EXPECTED_MONTHS) - HISTORY_COUNT


def parse_number(cell: str) -> float:
    text = cell.strip()
    if text == "":
        raise ValueError("vacío")
    if "," in text:
        text = text.replace(".", "").replace(",", ".")
    return float(text)


def is_integer_token(cell: str) -> bool:
    text = cell.strip()
    if text in {"", "+", "-"}:
        return False
    if text[0] in "+-":
        text = text[1:]
    return text.isdigit()


def decode_bytes(raw: bytes) -> tuple[str, str]:
    if raw.startswith(b"\xef\xbb\xbf"):
        return raw.decode("utf-8-sig"), "utf-8-sig"
    try:
        return raw.decode("utf-8"), "utf-8"
    except UnicodeDecodeError:
        return raw.decode("cp1252"), "cp1252"


@dataclass(frozen=True)
class Sheet:
    path: Path
    encoding: str
    header: tuple[str, ...]
    rows: tuple[tuple[str, ...], ...]

    @property
    def meta(self) -> tuple[str, ...]:
        return self.header[: len(META_COLUMNS)]

    @property
    def month_labels(self) -> tuple[str, ...]:
        return self.header[len(META_COLUMNS) :]

    def column(self, name: str) -> int:
        return self.header.index(name)

    def months(self) -> tuple[date, ...]:
        parsed: list[date] = []
        for label in self.month_labels:
            parsed.append(datetime.strptime(label, "%d/%m/%Y").date())
        return tuple(parsed)


def load_sheet(path: Path | str) -> Sheet:
    file_path = Path(path)
    text, encoding = decode_bytes(file_path.read_bytes())
    # csv exige newlines conservados; splitlines() los descarta y rompe campos citados.
    reader = csv.reader(text.splitlines(), delimiter=";")
    try:
        header = tuple(next(reader))
    except StopIteration as exc:
        raise ValueError(f"{file_path} está vacío") from exc
    rows = tuple(tuple(row) for row in reader)
    return Sheet(path=file_path, encoding=encoding, header=header, rows=rows)


def load_fixture() -> Sheet:
    return load_sheet(fixture_path())


def history_slice(row: tuple[str, ...]) -> tuple[str, ...]:
    start = len(META_COLUMNS)
    return row[start : start + HISTORY_COUNT]


def forecast_slice(row: tuple[str, ...]) -> tuple[str, ...]:
    start = len(META_COLUMNS) + HISTORY_COUNT
    return row[start : start + FORECAST_COUNT]
