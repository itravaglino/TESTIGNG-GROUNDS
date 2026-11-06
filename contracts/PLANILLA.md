# Contrato de la planilla estándar de forecast

Este archivo es la fuente de verdad para parsers, métricas, reglas de calidad y tests.
Otros modelos deben leerlo **antes** de inventar columnas o formatos.

Vintage de referencia: `Forecast_mann_scenario_test4_unidades_in.csv`
(archivo subido `Forecast_mann_scenario_test4_unidades_in__b7f0.csv`).

## Formato de archivo

| Campo | Valor |
| --- | --- |
| Delimitador | `;` (nunca coma) |
| Decimal | `,` (ej. `9995,08`, `0,46`) |
| Miles | no se usan en este vintage |
| Encoding | `cp1252` / `latin-1` (no UTF-8; hay bytes `0xA1`) |
| Newline | CRLF |
| Fechas de columnas | `DD/MM/YYYY` con día siempre `01` (mes calendario) |
| Columnas totales | 162 = 30 metadatos + 132 meses |
| Filas de productos | 4402, `product_id` único |

No commitear el CSV completo (2.3 MB, datos comerciales). Usar
`fixtures/samples/stratified.csv` (20 filas reales, cubre todas las
combinaciones demanda×modelo, regiones, ABC, cluster, vendedor, alias
`PICK UP` y un valor de subcategoría con mojibake).

## Columnas de metadatos (orden fijo)

```
product_id, Familia, Region, Vendedor, Cliente, Categoria, Subcategoria,
SKU, Descripcion, Tipo de demanda, Cluster, Error, ABC, Promedio,
Desviacion Std, Coeficiente, YTD, QTD, MTD, FYTD, YTG, QTG, MTG, FYTG,
Modelo, Precio Unitario, Costo Unitario, Reemplazado?, Reemplazado por,
Descontinuado?
```

Después vienen 132 columnas mensuales: `01/01/2017` … `01/12/2027`.

## Corte historia / forecast (este vintage)

- Historia: `01/01/2017` … `01/10/2026` (118 meses, enteros o negativos)
- Forecast: `01/11/2026` … `01/12/2027` (14 meses, casi siempre con decimales)

Regla de detección si el vintage cambia: el forecast empieza en el primer
mes donde la mayoría de las filas tienen `,` decimal. No hardcodear el año
en el parser; el contrato del vintage vive en `contracts/profile.json`.

## Dominios observados (4402 filas)

**Tipo de demanda:** `Erratica` (3260), `Intermitente` (485), `Con tendencia` (439), `Variable moderada` (218)

**Cluster:** `Alto riesgo` (3261), `Bajo riesgo` (641), `Mediano riesgo` (500)

**ABC:** `C` (3870), `B` (344), `A` (188)

**Modelo (columna `Modelo`, nombre interno del motor):**

- `auto_SARIMA` (3240)
- `holtsWintersExponentialSmoothing` (669)  ← typo original, no “corregir”
- `prophet` (493)

**Region:** `MTO`, `MTS`, `VSF`, `REV`, `BLOQUEADO`

**Cliente:** `MANN-FILTER`, `WIX`

**Categoria:** `PC`, `OHI`, `CV`, `Pick up`, `IF`, `LCV`, y el alias `PICK UP` (1 fila)

**Reemplazado? / Descontinuado?:** siempre `No` en este vintage. `Reemplazado por` = `N/A`.
`Familia` vacío. `Vendedor` casi siempre vacío; a veces `"1"`.
`Precio Unitario` y `Costo Unitario` = `0`.

YTD/QTD/MTD/FYTD/YTG/QTG/MTG/FYTG son porcentajes con signo, no unidades.

`Error` es un número 0–100 con decimal coma (`31,32`). `Coeficiente` es CV (desv/promedio).

## Números

- Parser: reemplazar `,` por `.` y `float()`.
- Vacío → `null`.
- Negativos **permitidos** en historia (834 SKUs tienen al menos un mes negativo) y en YT*.
- No redondear el forecast al validar; comparar con tolerancia `1e-6` relativo o `0.01` absoluto.

## Qué no hacer

- No reinterpretar `;` como `,`.
- No asumir UTF-8 (rompe `Habitáculo` → `HabitA¡culo`).
- No “arreglar” `holtsWintersExponentialSmoothing`.
- No tratar `PICK UP` y `Pick up` como error de parseo; normalizar en una capa aparte.
- No exigir precio/costo > 0.
- No usar el CSV completo en CI; el sample alcanza para tests unitarios.

## Cómo verificar rápido

```bash
python3 -m planilla.cli validate fixtures/samples/stratified.csv
python3 -m unittest discover -s tests -v
```

Un parser propio pasa el contrato si:

1. Lee las 30 columnas meta + N columnas fecha.
2. `product_id` 722344 → SKU `WL7413`, modelo `auto_SARIMA`, historia oct-2026 = `6670`, forecast nov-2026 ≈ `8415,25`.
3. Rechaza CSV con delimitador coma o headers faltantes.
