"""Diff de una planilla candidata contra la estándar, por product_id."""

from __future__ import annotations

from dataclasses import dataclass, field

from planilla.schema import COMPARE_ATOL, META_COLUMNS
from planilla.sheet import FORECAST_COUNT, HISTORY_COUNT, Sheet, parse_number


@dataclass
class CompareReport:
    golden_rows: int
    candidate_rows: int
    missing: list[str] = field(default_factory=list)
    extra: list[str] = field(default_factory=list)
    meta_diffs: list[str] = field(default_factory=list)
    history_diffs: list[str] = field(default_factory=list)
    forecast_diffs: list[str] = field(default_factory=list)
    unreadable: list[str] = field(default_factory=list)

    @property
    def identical(self) -> bool:
        return not (
            self.missing
            or self.extra
            or self.meta_diffs
            or self.history_diffs
            or self.forecast_diffs
            or self.unreadable
        )

    def to_dict(self) -> dict:
        return {
            "golden_rows": self.golden_rows,
            "candidate_rows": self.candidate_rows,
            "identical": self.identical,
            "missing": len(self.missing),
            "extra": len(self.extra),
            "meta_diffs": len(self.meta_diffs),
            "history_diffs": len(self.history_diffs),
            "forecast_diffs": len(self.forecast_diffs),
            "unreadable": len(self.unreadable),
            "examples": {
                "missing": self.missing[:8],
                "extra": self.extra[:8],
                "meta": self.meta_diffs[:8],
                "history": self.history_diffs[:8],
                "forecast": self.forecast_diffs[:8],
                "unreadable": self.unreadable[:8],
            },
        }


def _index(row: tuple[str, ...], name: str) -> str:
    return row[META_COLUMNS.index(name)]


def compare_sheets(
    candidate: Sheet,
    golden: Sheet,
    atol: float = COMPARE_ATOL,
) -> CompareReport:
    report = CompareReport(golden_rows=len(golden.rows), candidate_rows=len(candidate.rows))
    golden_by_id = {_index(row, "product_id"): row for row in golden.rows}
    candidate_by_id = {_index(row, "product_id"): row for row in candidate.rows}
    report.missing = sorted(set(golden_by_id) - set(candidate_by_id))
    report.extra = sorted(set(candidate_by_id) - set(golden_by_id))

    meta_compare = [
        name
        for name in META_COLUMNS
        if name != "product_id"
    ]
    history_at = len(META_COLUMNS)
    forecast_at = history_at + HISTORY_COUNT

    for product_id in sorted(set(golden_by_id) & set(candidate_by_id)):
        left = golden_by_id[product_id]
        right = candidate_by_id[product_id]
        if len(left) != len(golden.header) or len(right) != len(candidate.header):
            report.unreadable.append(f"{product_id} ancho distinto")
            continue
        for name in meta_compare:
            position = META_COLUMNS.index(name)
            if left[position] != right[position]:
                report.meta_diffs.append(
                    f"{product_id} {name}: {left[position]!r} -> {right[position]!r}"
                )
                break
        history_broken = False
        for offset, (raw_left, raw_right) in enumerate(
            zip(left[history_at:forecast_at], right[history_at:forecast_at])
        ):
            if raw_left == raw_right:
                continue
            try:
                if abs(parse_number(raw_left) - parse_number(raw_right)) <= atol:
                    continue
            except ValueError:
                report.unreadable.append(f"{product_id} historia ilegible")
                history_broken = True
                break
            report.history_diffs.append(
                f"{product_id} mes {offset + 1}: {raw_left} -> {raw_right}"
            )
            break
        if history_broken:
            continue
        for offset, (raw_left, raw_right) in enumerate(
            zip(left[forecast_at : forecast_at + FORECAST_COUNT], right[forecast_at : forecast_at + FORECAST_COUNT])
        ):
            if raw_left == raw_right:
                continue
            try:
                if abs(parse_number(raw_left) - parse_number(raw_right)) <= atol:
                    continue
            except ValueError:
                report.unreadable.append(f"{product_id} pronostico ilegible")
                break
            report.forecast_diffs.append(
                f"{product_id} horizonte {offset + 1}: {raw_left} -> {raw_right}"
            )
            break
    return report
