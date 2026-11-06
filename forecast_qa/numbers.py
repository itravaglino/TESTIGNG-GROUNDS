from __future__ import annotations

from datetime import date, datetime


def parse_es_number(raw: str | None) -> float | None:
    """Parse Mann/Excel Spanish numbers: 8415,25 → 8415.25; 100 → 100.0."""
    if raw is None:
        return None
    s = str(raw).strip().replace("\xa0", "").replace(" ", "")
    if s == "" or s.upper() in {"NA", "N/A", "NULL", "#N/A"}:
        return None
    if s.count(",") == 1 and s.count(".") == 0:
        s = s.replace(",", ".")
    elif "," in s and "." in s:
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    try:
        return float(s)
    except ValueError:
        return None


def parse_month_header(header: str) -> date:
    return datetime.strptime(header, "%d/%m/%Y").date()
