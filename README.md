# TESTIGNG-GROUNDS

Terreno de prueba del auditor de forecasts. La **planilla estándar** es un CSV ancho de Mann/WIX (un SKU por fila, meses en columnas).

Si estás implementando parser, métricas, reglas o UI: leé `docs/PLANILLA_ESTANDAR.md` y corré el verificador **antes** de inventar otro esquema.

```bash
python3 -m unittest discover -s tests -q
python3 -m planilla fixtures/planilla-estandar/sample_diverso.csv
```

| Ruta | Para qué |
| --- | --- |
| `fixtures/planilla-estandar/sample_diverso.csv` | 18 SKUs, cubre tipos/modelos/ABC/BLOQUEADO/negativos |
| `fixtures/planilla-estandar/Forecast_mann_scenario_test4_unidades.csv` | Planilla completa (4402 SKUs) |
| `planilla/` | Parser, melt a largo, `python3 -m planilla` |
| `tests/` | Contrato + golden + malformados |
