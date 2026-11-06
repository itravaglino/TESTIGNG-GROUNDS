# TESTIGNG-GROUNDS

Planilla estándar de forecast en **unidades** y el validador para chequearla sin redescubrir el formato.

Archivo de referencia: `fixtures/Forecast_mann_scenario_test4_unidades.csv` (escenario test 4, Mann, 4.402 productos).

## Para otros modelos

No hay dependencias. Desde la raíz del repo:

```bash
python3 -m planilla spec
python3 -m planilla check fixtures/Forecast_mann_scenario_test4_unidades.csv
python3 -m planilla audit fixtures/Forecast_mann_scenario_test4_unidades.csv
python3 -m planilla diff mi_candidato.csv
python3 -m planilla example /tmp/plantilla.csv --rows 3
python3 -m unittest discover -s tests
```

`check` sale con código 0 solo si el archivo cumple el contrato. `diff` compara contra la planilla de referencia por `product_id`. `1,5` y `1,50` cuentan como el mismo número. `audit` no falla el proceso: describe los defectos que el export ya trae.

Desde Python:

```python
from planilla import read_sheet, validate, audit, diff_sheets

sheet = read_sheet("candidato.csv")
assert validate(sheet).ok
```

## Contrato

- Separador `;`. Encoding oficial **cp1252** (el archivo no es UTF-8). Fin de línea oficial CRLF. Un LF solo es un aviso, no un error. UTF-8 válido se acepta.
- 30 columnas de atributos, en este orden, y después un mes por columna desde `01/01/2017` hasta `01/12/2027` (132 meses, día 01).
- Último mes real: **octubre 2026**. Pronóstico: **noviembre 2026 a diciembre 2027** (14 meses).
- Reales: enteros, pueden ser negativos. Pronóstico: mayor o igual a 0, hasta 2 decimales.
- Decimal con coma y sin separador de miles: `8415,25`. No valen `8415.25` ni `8.415,25`.
- `product_id` de 6 dígitos, único. `SKU` único y no vacío.
- Enums cerrados (están en `python3 -m planilla spec`): tipo de demanda, cluster, ABC, modelo, cliente, región, categoría, reemplazado y descontinuado.

`Familia` puede ir vacía. En esta planilla va vacía en las 4.402 filas. Precio y costo van en 0: el archivo es de unidades.

## Qué se verificó en la planilla de referencia

El contrato cierra sin errores. El contenido tiene estos defectos, ya medidos por `audit`:

| Hallazgo | Cantidad |
| --- | ---: |
| Familia vacía | 4.402 filas |
| Precio y costo en 0 | 4.402 filas |
| Pronóstico entero en 0 (nov 2026–dic 2027) | 1.562 filas |
| Filas con algún mes real negativo | 834 filas, 1.036 celdas |
| Descripción vacía | 136 |
| Vendedor lleno con `1` | 23 |
| `Region=BLOQUEADO` | 22 |
| Texto con acentos rotos (`HabitA¡culo`, `elAƒA©ctrico`) | 8 filas |
| `Categoria=PICK UP` además de `Pick up` | 1 fila (`W 1323/1`) |
| Cluster atípico: intermitente + alto riesgo | 1 fila |
| SKU en notación científica de Excel | 1 (`8,00325E+11`) |

Esos números están fijados en `tests/test_planilla.py`. Si el export de referencia cambia, el test lo marca.
