# Guía para otros modelos (TESTIGNG-GROUNDS)

Objetivo: auditar forecasts Mann/WIX. **No reinventar el CSV.** Usar este kit.

## Planilla estándar

Archivo canónico (el que pasó el usuario):

`fixtures/golden/Forecast_mann_scenario_test4_unidades.csv`

| Qué | Valor |
| --- | --- |
| Separador | `;` |
| Encoding | `cp1252`/`latin-1` (el full file **no** es UTF-8) |
| Filas | 4402 SKU, `product_id` único |
| Meta | 30 columnas fijas (`forecast_kit.schema.META_COLUMNS`) |
| Meses | `01/01/2017` … `01/12/2027` (132, día 1, consecutivos) |
| Historia | hasta `01/10/2026` (118 meses) |
| Forecast | desde `01/11/2026` (14 meses) |
| Modelos | `auto_SARIMA`, `holtsWintersExponentialSmoothing`, `prophet` |
| Números | coma decimal (`8415,25`), enteros, negativos en actuals |

Constantes y parser: paquete `forecast_kit`.

## Cómo testear rápido

```bash
# unitario (<1s) — usar SIEMPRE en TDD
python3 -m unittest discover -s tests -v

# validar un CSV que hayas generado
python3 -m forecast_kit validate fixtures/golden/mini.csv
python3 -m forecast_kit validate path/a/tu/salida.csv --json
```

| Fixture | Para qué |
| --- | --- |
| `fixtures/golden/mini.csv` (11 filas, UTF-8) | parser, métricas, UI, reglas |
| `fixtures/golden/stratified.csv` (~27 filas) | cubre regiones, ABC, modelos, BLOQUEADO, PICK UP |
| `fixtures/golden/Forecast_mann_scenario_test4_unidades.csv` | aceptación / performance |
| `fixtures/negative/*.csv` | errores de parser (delimiter, modelo, duplicados, fechas ISO) |

Importar así:

```python
from forecast_kit import parse_forecast_csv, validate_path, HISTORY_END, FORECAST_START

book = validate_path("fixtures/golden/mini.csv")
assert not book.errors
sku = book.products[0]
actuals = sku.history          # dict[date, float]  … 2026-10-01
forecast = sku.forecast        # dict[date, float]  2026-11-01 …
```

## Contrato que no hay que romper

1. Headers de meta **exactos** (incluye `Desviacion Std`, `Reemplazado?`).
2. Headers de mes `DD/MM/YYYY`, no ISO.
3. No cambiar el corte historia/forecast salvo que el usuario mande otra planilla.
4. Aceptar `Pick up` y `PICK UP`.
5. No fallar el parse por actuals negativos: son ajustes/devoluciones (warning).
6. `python3 -m unittest discover -s tests` tiene que seguir verde si tocás el parser.

## Verificación de PRs de otros agentes

```bash
python3 -m unittest discover -s tests -v
python3 -m forecast_kit validate fixtures/golden/Forecast_mann_scenario_test4_unidades.csv
```

Si un agente inventa un CSV de ejemplo, validarlo con el mismo comando. Si falla `column_count`, `meta_headers` o `date_header`, el ejemplo no es la planilla estándar.
