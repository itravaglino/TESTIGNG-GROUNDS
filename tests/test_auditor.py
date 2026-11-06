import math
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from auditor.audit import auditar_texto, filas_forecast_corregido
from auditor.metrics import calcular_metricas
from auditor.models import croston_nivel
from auditor.parse import ParseError, parse_texto
from auditor.server import app

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = (ROOT / "fixtures" / "forecasts_largo.csv").read_text(encoding="utf-8")
ESPERADO = {
    "SKU-OK": "MANTENER",
    "SKU-SESGO": "CORREGIR",
    "SKU-PLANO": "DESCARTAR",
    "SKU-NEG": "CORREGIR",
    "SKU-INTER": "CORREGIR",
    "SKU-LEAK": "DESCARTAR",
    "SKU-ESCALA": "DESCARTAR",
    "SKU-PICO": "CORREGIR",
}


def _r4(value):
    return round(value, 4)


def test_m02_metricas_vector():
    met = calcular_metricas([10, 20, 30, 40], [12, 18, 33, 36])
    assert _r4(met["mae"]) == 2.7500
    assert _r4(met["me"]) == -0.2500
    assert _r4(met["wape"]) == 0.1100
    assert _r4(met["smape"]) == 0.1219


def test_fixture_metricas_suave():
    met = calcular_metricas([10, 12, 14, 16], [11, 11, 15, 14])
    assert met["mae"] == pytest.approx(1.25)
    assert met["wape"] == pytest.approx(5 / 52)
    assert met["smape"] == pytest.approx(9.6123366888 / 100)


def test_croston_ejemplo():
    assert croston_nivel([0, 5, 0, 0, 10, 0]) == pytest.approx(5.5 / 2.1)


def test_p01_parser_punto_y_coma():
    texto = "Pronóstico;SKU;Fecha;Venta Real\n1,5;SKU-1;2024-01-01;10,25\n"
    parsed = parse_texto(texto)
    assert len(parsed["filas"]) == 1
    fila = parsed["filas"][0]
    assert fila["product_id"] == "SKU-1"
    assert fila["date"].isoformat() == "2024-01-01"
    assert fila["forecast"] == 1.5
    assert fila["actual"] == 10.25


def test_fixture_ocho_dictamenes():
    resultado = auditar_texto(FIXTURE)
    assert len(resultado["productos"]) == 8
    por_nombre = {p["producto"]: p for p in resultado["productos"]}
    assert set(por_nombre) == set(ESPERADO)
    for nombre, estado in ESPERADO.items():
        assert por_nombre[nombre]["estado"] == estado, nombre
    port = resultado["portafolio"]
    assert port["mantener"] + port["corregir"] + port["descartar"] == 8
    assert port["mantener"] == 1
    assert port["corregir"] == 4
    assert port["descartar"] == 3
    inter = por_nombre["SKU-INTER"]["modelo_recomendado"]
    assert "Croston" in inter or "TSB" in inter
    pico = next(p for p in por_nombre["SKU-PICO"]["serie"] if p["fecha"] == "2026-03-09")
    assert pico["forecast_corregido"] < 200
    assert pico["forecast_corregido"] > 0
    vecino = next(p for p in por_nombre["SKU-PICO"]["serie"] if p["fecha"] == "2026-03-02")
    assert vecino["forecast_corregido"] == vecino["forecast"]
    neg = [p["forecast_corregido"] for p in por_nombre["SKU-NEG"]["serie"]]
    assert all(v is not None and v >= 0 for v in neg)
    sesgo = por_nombre["SKU-SESGO"]
    assert sesgo["wape_corregido"] < sesgo["wape"]
    for punto in por_nombre["SKU-LEAK"]["serie"]:
        assert punto["forecast_corregido"] is None
    for punto in por_nombre["SKU-ESCALA"]["serie"]:
        assert punto["forecast_corregido"] is None


def test_n03_negativo_sano_se_corrige():
    lineas = ["producto,fecha,actual,forecast"]
    for i, (a, f) in enumerate(zip([40, 42, 41, 43, 40, 44, 42, 41], [41, 40, 42, 43, 39, 44, 41, -5])):
        lineas.append(f"SKU,{2026}-01-{i+1:02d},{a},{f}")
    resultado = auditar_texto("\n".join(lineas) + "\n")
    producto = resultado["productos"][0]
    assert producto["estado"] == "CORREGIR"
    assert all(p["forecast_corregido"] is not None and p["forecast_corregido"] >= 0 for p in producto["serie"])
    assert any(p["forecast"] == -5 and p["forecast_corregido"] == 0 for p in producto["serie"])


def test_l04_leakage_no_corrige():
    filas = ["producto,fecha,actual,forecast"]
    for i in range(1, 13):
        filas.append(f"SKU,2024-01-{i:02d},{i},{i}")
    resultado = auditar_texto("\n".join(filas) + "\n")
    producto = resultado["productos"][0]
    assert producto["estado"] == "DESCARTAR"
    assert all(p["forecast_corregido"] is None for p in producto["serie"])


def test_s05_escala_10x():
    texto = "producto,fecha,actual,forecast\n" + "\n".join(
        f"SKU,2024-01-0{i},{a},{a * 10}" for i, a in enumerate([10, 20, 30, 40], start=1)
    )
    resultado = auditar_texto(texto + "\n")
    assert resultado["productos"][0]["estado"] == "DESCARTAR"


def test_b06_sesgo_30():
    texto = (
        "producto,fecha,actual,forecast\n"
        "SKU,2024-01-01,100,130\n"
        "SKU,2024-01-02,100,130\n"
        "SKU,2024-01-03,100,130\n"
        "SKU,2024-01-04,100,130\n"
        "SKU,2024-01-05,,130\n"
    )
    producto = auditar_texto(texto)["productos"][0]
    assert producto["estado"] == "CORREGIR"
    futuro = producto["serie"][-1]
    assert futuro["actual"] is None
    assert futuro["forecast_corregido"] == pytest.approx(100, abs=1e-6)
    assert futuro["forecast_corregido"] < 130
    assert producto["wape"] == pytest.approx(0.3, abs=1e-6)
    assert producto["wape_corregido"] == pytest.approx(0.0, abs=1e-6)
    assert producto["wape_corregido"] < producto["wape"]


def test_f07_plano_no_se_mantiene():
    texto = "producto,fecha,actual,forecast\nA,2024-01-01,10,30\nA,2024-01-02,50,30\nA,2024-01-03,5,30\nA,2024-01-04,80,30\n"
    assert auditar_texto(texto)["productos"][0]["estado"] != "MANTENER"


def test_i08_intermitente_recomienda_croston_o_tsb():
    actual = [0, 0, 0, 5, 0, 0, 0, 8, 0, 0, 0, 3]
    filas = ["producto,fecha,actual,forecast"]
    for i, a in enumerate(actual, start=1):
        filas.append(f"SKU,2024-01-{i:02d},{a},4")
    producto = auditar_texto("\n".join(filas) + "\n")["productos"][0]
    assert "Croston" in producto["modelo_recomendado"] or "TSB" in producto["modelo_recomendado"]


def test_e09_export_descartar_vacio():
    resultado = auditar_texto(FIXTURE)
    filas = filas_forecast_corregido(resultado)
    leak = [f for f in filas if f["producto"] == "SKU-LEAK"]
    assert leak
    assert all(f["forecast_corregido"] == "" for f in leak)
    assert all(f["forecast"] != "" for f in leak)
    sesgo = [f for f in filas if f["producto"] == "SKU-SESGO"]
    assert all(f["forecast_corregido"] != "" for f in sesgo)


def test_bordes_archivo():
    with pytest.raises(ParseError, match="vacío"):
        auditar_texto("   \n  ")
    with pytest.raises(ParseError, match="sin datos"):
        auditar_texto("Pronóstico;SKU;Fecha;Venta Real\n")
    una = auditar_texto("Pronóstico;SKU;Fecha;Venta Real\n1,5;SKU-1;2024-01-01;10,25\n")
    assert una["productos"][0]["serie"][0]["forecast"] == 1.5
    assert una["productos"][0]["estado"] == "MANTENER"
    with pytest.raises(ParseError, match="duplicad"):
        auditar_texto("SKU;Fecha;Pronóstico;Venta Real\nA;2024-01-01;1;10\nA;2024-01-01;2;11\n")
    with pytest.raises(ParseError, match="[Pp]ronóstico|forecast"):
        auditar_texto("SKU;Fecha;Venta Real\nA;2024-01-01;10\n")


def test_http_fixture_y_html():
    client = TestClient(app)
    pagina = client.get("/")
    assert pagina.status_code == 200
    assert "Auditor de Forecasts" in pagina.text
    respuesta = client.get("/api/ejemplo")
    assert respuesta.status_code == 200
    cuerpo = respuesta.json()
    assert len(cuerpo["productos"]) == 8
    port = cuerpo["portafolio"]
    assert port["mantener"] + port["corregir"] + port["descartar"] == 8
    subida = client.post("/api/auditar", files={"archivo": ("f.csv", FIXTURE, "text/csv")})
    assert subida.status_code == 200
    assert len(subida.json()["productos"]) == 8
    vacio = client.post("/api/auditar", files={"archivo": ("vacio.csv", b"", "text/csv")})
    assert vacio.status_code == 400
    assert "Traceback" not in vacio.text
    assert "vac" in vacio.json()["error"]
    duplicado = "SKU;Fecha;Pronóstico\nA;2024-01-01;1\nA;2024-01-01;2\n"
    malo = client.post("/api/auditar", files={"archivo": ("d.csv", duplicado, "text/csv")})
    assert malo.status_code == 400
    assert "duplicad" in malo.json()["error"]


def test_sin_nan_en_json():
    import json

    resultado = auditar_texto(FIXTURE)
    json.dumps(resultado)
    for producto in resultado["productos"]:
        for valor in producto["metricas"].values():
            assert not (isinstance(valor, float) and math.isnan(valor))
