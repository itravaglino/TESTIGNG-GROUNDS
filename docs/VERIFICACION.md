# Verificación de la planilla estándar

Corrida local (America/Buenos_Aires), 6 nov 2026.

```
python3 -m unittest discover -s tests -v
# 19 tests, 0.38s, OK

python3 -m forecast_kit validate fixtures/golden/Forecast_mann_scenario_test4_unidades.csv
# encoding=cp1252  products=4402  months=132
# errors=0  warnings=834  (negative_actuals only)
```

Qué quedó comprobado:

- SHA-256 del archivo canónico coincide.
- 30 meta + 132 meses, corte 2026-10 / 2026-11.
- `mini.csv` trae los 3 modelos y parsea en UTF-8.
- Fixtures negativas fallan con códigos estables (`column_count`, `unknown_model`, `duplicate_product_id`, `date_header`, `row_length`, `required_empty`, `empty_file`).
- 834 SKU del full file tienen al menos un actual negativo: es dato real, no error de parseo.

Si otro agente publica un CSV de ejemplo, el criterio de aceptación es:

```
python3 -m forecast_kit validate <su_archivo.csv>
# errors=0
```
