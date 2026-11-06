from pathlib import Path

from forecast_qa.diagnose import audit_product
from forecast_qa.parse import parse_mann_csv
from forecast_qa.split import split_workbook

MINI = Path(__file__).resolve().parents[1] / "fixtures" / "mann" / "mann_mini.csv"


def test_negative_history_is_flagged():
    book = parse_mann_csv(MINI)
    _, splits = split_workbook(book)
    by_id = {s.product.product_id: audit_product(s) for s in splits}
    neg = by_id["722346"]
    assert any(f.code == "DEMANDA_NEGATIVA" for f in neg.findings)
    assert neg.verdict in {"CORREGIR", "REVISAR", "DESCARTAR"}


def test_sparse_or_new_series_not_keep_blindly():
    book = parse_mann_csv(MINI)
    _, splits = split_workbook(book)
    sparse = next(s for s in splits if s.product.product_id == "722377")
    audit = audit_product(sparse)
    codes = {f.code for f in audit.findings}
    assert codes & {"HISTORICO_ESPARSO", "SERIE_NULA", "ERROR_VENDOR_100"}


def test_intermittent_gets_croston_family():
    book = parse_mann_csv(MINI)
    _, splits = split_workbook(book)
    inter = next(s for s in splits if s.product.product_id == "722345")
    audit = audit_product(inter)
    assert "croston" in audit.recommended_models


def test_all_verdicts_are_spanish():
    book = parse_mann_csv(MINI)
    _, splits = split_workbook(book)
    allowed = {"MANTENER", "CORREGIR", "REVISAR", "DESCARTAR"}
    for split in splits:
        assert audit_product(split).verdict in allowed
