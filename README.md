# Planilla estándar de forecast

Contrato y verificador del escenario `forecast_mann_scenario_test4_unidades`.
Sirve para que un modelo lea el formato una vez y compruebe una salida en segundos, sin redescubrir columnas, fechas ni decimales.

La planilla de referencia está en `fixtures/forecast_mann_scenario_test4_unidades.csv`.

## Cómo correrlo

Desde la raíz del repo:

```bash
python -m planilla audit
python -m planilla validate salida.csv
python -m planilla compare salida.csv
python -m unittest discover -s tests
```

`audit` y `validate` salen con código 0 cuando el formato cierra. `compare` sale con 0 solo si la candidata es la estándar (tolerancia 0,01 en cantidades). Agregá `--json` para leer el resultado desde otro script.

## Contrato

- Separador `;`. Decimales con coma. El archivo de referencia está en cp1252, no en UTF-8.
- 30 columnas de atributos y 132 meses, del `01/01/2017` al `01/12/2027`, siempre el día 1.
- Historia: enero 2017 a octubre 2026, unidades enteras (pueden ser negativas).
- Pronóstico: noviembre 2026 a diciembre 2027. No puede ser negativo.
- `product_id` y `SKU` únicos.
- `Desviacion Std` es el desvío poblacional (divisor n, no n−1) de los últimos 12 meses de historia, a 2 decimales.
- `Promedio` debería ser la media de esos mismos 12 meses. En la estándar, 668 SKU no cierran.
- ABC de este escenario: A si el promedio es ≥ 466,08, B si es ≥ 106,67, el resto C.

Catálogos: Region `MTO`, `MTS`, `VSF`, `REV`, `BLOQUEADO`. Cliente `MANN-FILTER` o `WIX`. Modelos `auto_SARIMA`, `holtsWintersExponentialSmoothing`, `prophet`.

## Auditoría de la estándar

El formato de las 4402 filas cierra. Estos son los problemas de datos, no de layout:

| Código | Filas | Qué pasa |
| --- | ---: | --- |
| `pronostico_cero` | 1562 | Los 14 meses de pronóstico están en cero. Son todos clase C y `auto_SARIMA` |
| `pronostico_cero_con_demanda` | 619 | De esos, la suma de los últimos 12 meses sigue siendo positiva |
| `promedio` | 668 | `Promedio` no es la media de esos 12 meses |
| `historia_negativa` | 834 | Algún mes de historia es negativo |
| `historia_cero` | 5 | Historia completa en cero |
| `texto` | 7 | Tildes rotas del export (`HidrA¡ulico`, `HabitA¡culo`) |
| `categoria` | 1 | `PICK UP` en vez de `Pick up` |
| `familia_vacia` | 4402 | `Familia` no viene cargada |

`Precio Unitario` y `Costo Unitario` están en 0. `Reemplazado?` y `Descontinuado?` están en `No`.
