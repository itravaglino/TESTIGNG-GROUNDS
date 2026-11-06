import io

import numpy as np
import pandas as pd
from fastapi.testclient import TestClient

from app import app
from forecast_auditor.metrics import metric_bundle
from forecast_auditor.pipeline import analyze_frame
from forecast_auditor.sample_data import demo_frame
from forecast_auditor.schema import SchemaError, normalize_frame, read_table


def test_wmape_and_mase_are_ratios():
    actual = np.array([10.0, 12.0, 11.0, 13.0, 12.0])
    forecast = np.array([11.0, 11.0, 12.0, 12.0, 13.0])
    bundle = metric_bundle(forecast, actual, period=2)
    assert bundle["mae"] == 1
    assert abs(bundle["wmape"] - (5 / 58)) < 1e-9
    assert abs(bundle["mase"] - 1) < 1e-9
    flat = metric_bundle(np.array([10.0, 10.0, 10.0]), np.array([10.0, 10.0, 10.0]), period=2)
    assert flat["mase"] is None


def test_demo_verdicts_and_repairs():
    report = analyze_frame(demo_frame())
    verdicts = {item["producto"]: item["veredicto"] for item in report["productos"]}
    assert verdicts == {
        "Leche entera 1L": "mantener",
        "Yerba 1kg": "corregir",
        "Aceite girasol 900ml": "corregir",
        "Arroz 1kg": "corregir",
        "Pan lactal": "corregir",
        "Fideos 500g": "corregir",
        "Azúcar 1kg": "corregir",
        "Café molido 250g": "mantener",
        "Gaseosa 2.25L": "corregir",
        "Agua sin gas 2L": "mantener",
        "Sal fina 500g": "descartar",
        "Harina 000 1kg": "descartar",
        "Miel 500g": "descartar",
    }
    by_name = {item["producto"]: item for item in report["productos"]}
    assert by_name["Leche entera 1L"]["antes"]["wmape"] < 0.05
    assert by_name["Yerba 1kg"]["despues"]["wmape"] < by_name["Yerba 1kg"]["antes"]["wmape"]
    assert by_name["Aceite girasol 900ml"]["despues"]["wmape"] < 0.1
    assert by_name["Pan lactal"]["antes"]["wmape"] > 0.4
    assert by_name["Pan lactal"]["despues"]["wmape"] < 0.1
    assert "estacional" in by_name["Azúcar 1kg"]["metodo_correccion"]
    assert by_name["Fideos 500g"]["fechas_imputadas"] == 8
    future = [row for row in by_name["Gaseosa 2.25L"]["exportacion"] if row["estado_fecha"] == "futuro"]
    assert future
    assert all(row["pronostico_original"] == 4800 for row in future)
    assert all(500 < row["pronostico_corregido"] < 750 for row in future)
    assert by_name["Arroz 1kg"]["diagnostico"]["clase_codigo"] == "intermitente"
    assert by_name["Arroz 1kg"]["modelos"][0]["id"] == "tsb"
    assert any(metric["id"] == "cobertura_intervalo" for metric in by_name["Leche entera 1L"]["metricas_historial"])
    assert report["resumen"]["descartar"] == 3
    assert report["resumen"]["wmape_ponderado_despues"] < report["resumen"]["wmape_ponderado_antes"]


def test_spanish_decimal_comma_and_semicolon():
    raw = "producto;fecha;pronóstico;real\nYerba;05/01/2026;1.200,5;1.000,0\nYerba;12/01/2026;1.180,0;1.010,0\n"
    frame = read_table("demanda.csv", raw.encode("utf-8"))
    normal, meta = normalize_frame(frame)
    assert meta["columns"]["product"] == "producto"
    assert float(normal.iloc[0]["forecast"]) == 1200.5
    assert str(normal.iloc[0]["date"].date()) == "2026-01-05"


def test_frequency_and_calendar_do_not_invent_gaps():
    daily = pd.DataFrame({
        "producto": "Pan",
        "fecha": pd.date_range("2024-01-01", periods=40, freq="D"),
        "pronostico": 10,
        "real": 10,
    })
    monthly = pd.DataFrame({
        "producto": "Arroz",
        "fecha": pd.date_range("2023-01-01", periods=18, freq="MS"),
        "pronostico": 10,
        "real": np.linspace(8, 12, 18),
    })
    daily_report = analyze_frame(daily)["productos"][0]["diagnostico"]
    monthly_report = analyze_frame(monthly)["productos"][0]["diagnostico"]
    assert daily_report["frecuencia"] == "diaria"
    assert daily_report["pct_faltantes"] == 0
    assert monthly_report["frecuencia"] == "mensual"
    assert monthly_report["pct_faltantes"] == 0


def test_column_alias_does_not_steal_forecast():
    frame = pd.DataFrame({
        "producto": ["A", "A"],
        "fecha": ["2024-01-01", "2024-01-08"],
        "forecast_lower": [1, 1],
        "pronostico": [10, 12],
        "real": [9, 11],
    })
    normal, meta = normalize_frame(frame)
    assert meta["columns"]["forecast"] == "pronostico"
    assert list(normal["forecast"]) == [10, 12]


def test_negatives_without_actuals_are_clipped():
    frame = pd.DataFrame({
        "producto": ["Sal"] * 10,
        "fecha": pd.date_range("2024-01-01", periods=10, freq="W-MON"),
        "pronostico": [10, 10, 10, -4, 10, 10, 10, 10, 10, 10],
    })
    product = analyze_frame(frame)["productos"][0]
    assert product["veredicto"] == "corregir"
    assert product["metodo_correccion"] == "Original recortado a cero"
    assert min(row["pronostico_corregido"] for row in product["exportacion"]) == 0


def test_missing_columns():
    try:
        normalize_frame(pd.DataFrame({"foo": [1], "bar": [2]}))
    except SchemaError as exc:
        assert "producto" in str(exc)
    else:
        raise AssertionError("tenía que rechazar el archivo")


def test_api_example_and_upload():
    client = TestClient(app)
    health = client.get("/api/salud")
    assert health.status_code == 200
    sample = client.get("/api/ejemplo")
    assert sample.status_code == 200
    assert sample.json()["resumen"]["productos"] == 13
    page = client.get("/")
    assert page.status_code == 200
    assert "Kalibra" in page.text

    csv = demo_frame().to_csv(index=False).encode("utf-8")
    uploaded = client.post("/api/auditar", files={"archivo": ("forecast.csv", io.BytesIO(csv), "text/csv")})
    assert uploaded.status_code == 200
    assert uploaded.json()["archivo"] == "forecast.csv"

    rejected = client.post("/api/auditar", files={"archivo": ("malo.csv", io.BytesIO(b"a,b\n1,2\n"), "text/csv")})
    assert rejected.status_code == 400
