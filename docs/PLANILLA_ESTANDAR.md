# Planilla estándar — forecast unidades

Fuente: `Forecast_mann_scenario_test4_unidades` (export de escenario test4).

Copia inmutable: `fixtures/golden/Forecast_mann_scenario_test4_unidades.csv`  
SHA-256 `460fc728da72c9773f6cb8751176cfa11a11b0404fa0e51f6952c7fb4f8bb9e0`

## Forma

- CSV `;`, 162 columnas, 4402 filas de producto + header.
- Encoding del archivo full: **cp1252/latin-1** (falla como UTF-8 por byte `0xA1`).
- `product_id` y `SKU` son únicos (1:1 en este extract).
- Meses: primero de mes, `DD/MM/YYYY`, de enero 2017 a diciembre 2027 sin huecos.

## Corte actual vs forecast (hoy: 6 nov 2026, America/Buenos_Aires)

En esta planilla el horizonte de forecast arranca en **noviembre 2026**:

- Actuals: `01/01/2017` … `01/10/2026` (118)
- Forecast: `01/11/2026` … `01/12/2027` (14)

Se detecta en el full file porque a partir de `01/11/2026` ~64% de las celdas usan coma decimal.

## Metadata observada

| Campo | Observado en el full file |
| --- | --- |
| Familia | siempre vacío |
| Region | MTO 2918, MTS 911, VSF 438, REV 113, BLOQUEADO 22 |
| Vendedor | vacío salvo 23 filas `1` |
| Cliente | MANN-FILTER 2312, WIX 2090 |
| Categoria | PC, OHI, CV, Pick up, IF, LCV, y 1× `PICK UP` |
| Tipo de demanda | Erratica 3260, Intermitente 485, Con tendencia 439, Variable moderada 218 |
| Cluster | Alto 3261, Bajo 641, Mediano 500 |
| ABC | C 3870, B 344, A 188 |
| Modelo | auto_SARIMA 3240, holtsWintersExponentialSmoothing 669, prophet 493 |
| Error | 0–100 |
| Precio/Costo | 0 |
| Reemplazado? / Descontinuado? | No / N/A / No |

YTD, QTD, MTD, FYTD, YTG, QTG, MTG, FYTG son porcentajes con signo (pueden ser miles). Tratarlos como métricas del export, no como unidades.

## Calidad de la serie

- Hay actuals **negativos** (devoluciones/ajustes), sobre todo 2017 y algunos meses 2024–2026. El parser no debe tirarlos.
- Muchos SKU arrancan con años en cero (lanzamientos tardíos / intermitentes).
- `Promedio` / `Desviacion Std` / `Coeficiente` vienen precalculados en el export (coma decimal).

## Fixtures derivadas

- `mini.csv`: 11 filas UTF-8, cubre los 3 modelos, BLOQUEADO, PICK UP, ceros largos, vendedor=1.
- `stratified.csv`: 27 filas, regiones y categorías.
- `fixtures/negative/`: casos que **tienen** que fallar validación (salvo `dot_decimal_forecast.csv` y `header_only.csv`).
