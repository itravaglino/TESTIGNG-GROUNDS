# Contrato de la planilla estándar

Usá **esta** planilla. No inventes un CSV largo semanal (`sku,fecha,forecast,actual`).

El archivo real es **ancho**: una fila por SKU, 30 columnas de metadatos y **132 meses** en columnas `DD/MM/YYYY`.

## Cómo correr tests rápido

```bash
python3 -m unittest discover -s tests -q
python3 -m planilla fixtures/planilla-estandar/sample_diverso.csv
python3 -m planilla fixtures/planilla-estandar/Forecast_mann_scenario_test4_unidades.csv --golden
python3 -m planilla.export_long fixtures/planilla-estandar/sample_diverso.csv /tmp/sample_long.csv
```

- Tests de parser / melt / casos malos: `sample_diverso.csv` (18 SKUs, ~1s).
- Regresión contra conteos reales: la planilla completa (4402 SKUs) con `--golden`.

## Formato

| Campo | Valor |
| --- | --- |
| Delimitador | `;` |
| Decimal | `,` (sin miles) |
| Encoding | UTF-8 (el origen traía 9 bytes latin-1; el fixture ya está normalizado) |
| Grano | mensual, día 1 |
| Historia | `2017-01-01` … `2026-10-01` (118 meses, casi siempre enteros, puede haber negativos) |
| Pronóstico | `2026-11-01` … `2027-12-01` (14 meses, muchos con decimales) |
| Productos | 4402 `product_id` únicos = 4402 SKU únicos |

Corte historia/pronóstico: **primera columna mensual donde ≥50% de las celdas no vacías tienen coma decimal**. En esta planilla cae en noviembre 2026.

## Metadatos (orden fijo, primeras 30 columnas)

`product_id`, `Familia`, `Region`, `Vendedor`, `Cliente`, `Categoria`, `Subcategoria`, `SKU`, `Descripcion`, `Tipo de demanda`, `Cluster`, `Error`, `ABC`, `Promedio`, `Desviacion Std`, `Coeficiente`, `YTD`, `QTD`, `MTD`, `FYTD`, `YTG`, `QTG`, `MTG`, `FYTG`, `Modelo`, `Precio Unitario`, `Costo Unitario`, `Reemplazado?`, `Reemplazado por`, `Descontinuado?`

`Familia` viene vacía. `Reemplazado?` y `Descontinuado?` son `No` en toda la planilla actual.

## Catálogos observados

- **Modelo:** `auto_SARIMA` (3240), `holtsWintersExponentialSmoothing` (669), `prophet` (493)
- **Tipo de demanda:** `Erratica`, `Intermitente`, `Con tendencia`, `Variable moderada`
- **Cluster:** `Alto riesgo`, `Mediano riesgo`, `Bajo riesgo`
- **ABC:** A/B/C
- **Region:** `MTO`, `MTS`, `VSF`, `REV`, `BLOQUEADO`
- **Cliente:** `MANN-FILTER`, `WIX`

## Mapeo a modelo largo (para métricas)

`planilla.melt` emite:

`product_id, sku, fecha, valor, es_pronostico, actual, forecast, modelo, categoria, region, tipo_de_demanda, cluster, abc`

- Historia: `actual = valor`, `forecast = null`, `es_pronostico = false`
- Horizonte: `forecast = valor`, `actual = null`, `es_pronostico = true`

En esta planilla **no hay actual y forecast en el mismo mes**. Accuracy vs real hay que calcularla sobre historia (backtest) o esperar otra planilla con holdout.

## Producto de control (SKU WL7413 / 722344)

- Historia `2017-01` = `3`
- Historia `2026-10` = `6670`
- Pronóstico `2026-11` = `8415,25`
- Modelo `auto_SARIMA`, tipo `Con tendencia`

## Qué no asumir

- No es semanal ni ISO-8601 en el encabezado.
- No hay columnas `pronostico` / `ventas` / `actual`.
- `Promedio` ≈ últimos 12 meses de historia, pero **no** es un invariante (hay desvíos).
- No clamps de negativos en ingest: hay valores negativos reales en historia.

Contrato máquina: `planilla/schema.json`. Conteos golden: `fixtures/planilla-estandar/golden_stats.json`.
