# Contrato para agentes (leer esto antes de codear)

La planilla **estándar** ya está en el repo. No inventes otro CSV.

## Archivo canónico

- Completo: `fixtures/mann/Forecast_mann_scenario_test4_unidades.csv` (4402 SKUs)
- Rápido: `fixtures/mann/mann_mini.csv` (12 SKUs reales)
- Esquema: `fixtures/mann/schema.json`

## Formato (obligatorio)

| Campo | Valor |
| --- | --- |
| Orientación | **Ancha**: 30 columnas de metadatos + 132 meses |
| Separador | `;` |
| Decimal | `,` (ejemplo `8415,25`) |
| Meses | cabeceras `01/MM/YYYY` de `01/01/2017` a `01/12/2027` |
| Origen del forecast | `01/11/2026` (histórico = meses anteriores; futuro = ese mes en adelante) |
| Encoding | cp1252 / latin-1 (no asumas UTF-8) |

**No hay** columnas `fecha`, `pronostico`, `ventas` por fila. Una fila = un SKU.

El archivo **no** trae el forecast histórico archivado. Para métricas de error sobre el pasado usá holdout naïve estacional (`naive_seasonal_holdout`) o los campos vendor `Error`, `YTD`, `QTD`, `MTD`.

## API lista para usar

```python
from forecast_qa import parse_mann_csv, split_workbook, compute_metrics, naive_seasonal_holdout

book = parse_mann_csv("fixtures/mann/mann_mini.csv")
start, splits = split_workbook(book)
m = naive_seasonal_holdout(splits[0].history)
```

CLI:

```bash
python -m forecast_qa fixtures/mann/mann_mini.csv
python -m forecast_qa fixtures/mann/Forecast_mann_scenario_test4_unidades.csv --json
python -m pytest
```

## Convenciones que otros runs rompieron (no las copies)

- CSV **largo semanal** `sku,fecha,pronostico,ventas` (rama `cursor/forecast-auditor-fixture-b50c`) **no** es el estándar.
- WAPE/MAPE van en **ratio** (0.11), no en 11.
- Veredictos en español: `MANTENER` / `CORREGIR` / `REVISAR` / `DESCARTAR`.
- Stack de referencia de este harness: Python 3.12 + pytest. Podés montar UI React encima, pero el parser Mann tiene que pasar `tests/test_parse_mann.py`.

## Cómo testear rápido

1. Corré pytest (incluye el archivo completo, ~1 s).
2. Iterá lógica nueva contra `mann_mini.csv`.
3. Recién al final corré el archivo de 4402 SKUs.
4. Si tu parser no abre `mann_mini.csv`, está mal: no “flexibilices” el formato, arreglá el parser.
