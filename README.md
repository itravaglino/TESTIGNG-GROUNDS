# Planilla estándar de forecast

Contrato y verificador del escenario `forecast_mann_scenario_test4_unidades`.
Sirve para que un modelo lea el formato una vez y compruebe una salida en segundos, sin redescubrir columnas, fechas ni decimales.

La planilla de referencia está en `fixtures/forecast_mann_scenario_test4_unidades.csv`.

## Cómo correrlo

Desde la raíz del repo:

```bash
python3 -m planilla audit
python3 -m planilla validate salida.csv
python3 -m planilla compare salida.csv
python3 -m planilla largo -o pronostico_largo.csv
python3 -m unittest discover -s tests
```

`largo` escribe solo el horizonte noviembre 2026–diciembre 2027, una fila por producto y mes (`product_id;SKU;fecha;pronostico;modelo`). Sirve para las apps que no leen el formato ancho.

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

## Cruce con los otros modelos

Misma planilla (sha256 `460fc728da72…`, 2.354.913 bytes) en las ramas que la conservan byte a byte: `planilla-estandar-3b5a`, `planilla-estandar-727f`, `planilla-estandar-harness-8c84` y `forecast-kit-planilla-estandar-475c`. `planilla-estandar-modelos-4f4e` no versiona el CSV y publica el mismo hash en `contracts/profile.json`.

| Rama | Tests | Lectura de esta planilla |
| --- | --- | --- |
| `planilla-estandar-3b5a` | 10 ok | `check` ok, mismo archivo |
| `planilla-estandar-727f` | 7 ok | `verify` ok. Cierra MTD 1683/1698, FYTD 3278/3324, YTD 3321/3373, MTG 1926/1926 |
| `planilla-estandar-harness-8c84` | 9 ok | parser propio ok |
| `planilla-estandar-modelos-4f4e` | 13 ok | sample estratificada, sin el CSV completo |
| `planilla-estandar-verificacion-07e3` | 8 ok | reencode a UTF-8; los valores comparan igual |
| `planilla-estandar-verificacion-a1b0` | 16 ok | números iguales; reescribió 8 textos con tilde rota |
| `forecast-kit-planilla-estandar-475c` | 19 ok | `validate` ok |
| `forecast-qa-system-0430` | 13 ok | el ancho no entra (hay 30 columnas que no son fecha). `largo` sí: 61.628 filas, 0 avisos |
| `forecast-qa-system-5d48` | 13 ok | lee el ancho: 4.402 × 132 = 581.064 puntos, y también el `largo` |
| `forecast-qa-system-95dd` | 12 ok | no lee el ancho. `largo`: 61.628 filas aceptadas |
| `lupa-forecast-qa-e0e0` | 8 ok | no lee el ancho. `largo`: 4.402 productos × 14 meses, 0 filas descartadas |

`QTD`, `YTG`, `QTG` y `FYTG` no se reproducen con un año contra año simple. Quedan como campos del escenario.
