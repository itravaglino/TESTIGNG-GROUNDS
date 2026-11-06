import json
from pathlib import Path

import pytest

from forecast_qa.metrics import compute_metrics

GOLDEN = json.loads(
    (Path(__file__).resolve().parents[1] / "fixtures" / "golden" / "metrics.json").read_text()
)


def test_pinned_case_m02():
    case = GOLDEN["case_m02"]
    m = compute_metrics(case["actual"], case["forecast"])
    assert m.n == 4
    assert m.mae == pytest.approx(case["mae"])
    assert m.me == pytest.approx(case["me"])
    assert m.rmse == pytest.approx(case["rmse"])
    assert m.mape == pytest.approx(case["mape"])
    assert m.wape == pytest.approx(case["wape"])
    assert m.smape == pytest.approx(case["smape"])
    assert m.wape is not None and m.wape < 1  # ratio, not percent
