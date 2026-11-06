import csv
import subprocess
import sys
from datetime import date
from pathlib import Path

from planilla.contrato import (
    HISTORIA_HASTA,
    N_FILAS,
    N_MESES,
    PRONOSTICO_DESDE,
    PRONOSTICO_HASTA,
)
from planilla.parser import cargar, parse_numero
from planilla.verificar import comparar, meses_entre, verificar

RAIZ = Path(__file__).resolve().parents[1]
FIXTURE = RAIZ / "fixtures" / "planilla_estandar.csv"
MUESTRA = RAIZ / "fixtures" / "planilla_estandar_muestra.csv"


def test_contrato_de_la_planilla_completa():
    resultado = verificar(str(FIXTURE), completa=True)
    assert resultado.ok, resultado.texto()
    assert resultado.metricas["filas"] == N_FILAS
    assert resultado.metricas["meses"] == N_MESES


def test_muestra_cumple_el_mismo_esquema():
    resultado = verificar(str(MUESTRA), completa=False)
    assert resultado.ok, resultado.texto()
    planilla = cargar(MUESTRA)
    assert 8 <= len(planilla.filas) <= 40
    assert planilla.meses[0] == date(2017, 1, 1)
    assert planilla.meses[-1] == PRONOSTICO_HASTA
    assert len(meses_entre(PRONOSTICO_DESDE, PRONOSTICO_HASTA)) == 14
    assert planilla.meses[planilla.meses.index(HISTORIA_HASTA) + 1] == PRONOSTICO_DESDE


def test_muestra_coincide_con_el_estandar():
    resultado = comparar(str(FIXTURE), str(MUESTRA))
    assert resultado.ok, resultado.texto()
    assert resultado.metricas["puntos_distintos"] == 0
    assert resultado.metricas["wape"] == 0
    assert resultado.metricas["puntos"] == resultado.metricas["sku_comparados"] * 14


def test_un_pronostico_alterado_no_pasa():
    planilla = cargar(MUESTRA)
    fila = planilla.filas[0]
    destino = RAIZ / "fixtures" / "_tmp_alterado.csv"
    texto = MUESTRA.read_text(encoding="utf-8")
    lineas = texto.splitlines()
    encabezado = lineas[0].split(";")
    columna = encabezado.index("01/11/2026")
    celdas = lineas[1].split(";")
    assert celdas[encabezado.index("SKU")] == fila.sku
    celdas[columna] = "999999,99"
    lineas[1] = ";".join(celdas)
    destino.write_text("\n".join(lineas) + "\n", encoding="utf-8")
    try:
        resultado = comparar(str(FIXTURE), str(destino))
        assert not resultado.ok
        assert resultado.metricas["puntos_distintos"] >= 1
        assert any(fila.sku in error for error in resultado.errores)
    finally:
        destino.unlink(missing_ok=True)


def test_formato_largo_redondo(tmp_path: Path):
    salida = tmp_path / "largo.csv"
    subprocess.run(
        [
            sys.executable,
            str(RAIZ / "scripts" / "verificar_planilla.py"),
            "--largo",
            "--solo-pronostico",
            "-o",
            str(salida),
            str(MUESTRA),
        ],
        check=True,
        cwd=RAIZ,
    )
    resultado = comparar(str(FIXTURE), str(salida))
    assert resultado.ok, resultado.texto()
    assert resultado.metricas["wape"] == 0
    with salida.open(encoding="utf-8") as fh:
        filas = list(csv.DictReader(fh, delimiter=";"))
    assert filas
    assert set(filas[0]) >= {"SKU", "fecha", "unidades", "origen"}
    assert all(fila["origen"] == "pronostico" for fila in filas)
    assert all(fila["fecha"] >= "2026-11-01" for fila in filas)


def test_archivo_vacio(tmp_path: Path):
    vacio = tmp_path / "vacio.csv"
    vacio.write_text("", encoding="utf-8")
    resultado = verificar(str(vacio))
    assert not resultado.ok
    assert "vacío" in resultado.errores[0]


def test_numeros_con_coma_decimal():
    assert parse_numero("1.234,5") == 1234.5
    assert parse_numero("8415,25") == 8415.25
    assert parse_numero("-20") == -20
    assert parse_numero("") is None


def test_cli_de_la_muestra():
    corrida = subprocess.run(
        [sys.executable, str(RAIZ / "scripts" / "verificar_planilla.py"), str(MUESTRA)],
        check=False,
        cwd=RAIZ,
        capture_output=True,
        text=True,
    )
    assert corrida.returncode == 0, corrida.stdout + corrida.stderr
    assert corrida.stdout.startswith("OK")
