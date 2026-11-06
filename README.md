# TESTIGNG-GROUNDS

Campo de pruebas para el auditor de forecasts Mann/WIX.

La **planilla estándar** está en `fixtures/golden/`. El contrato, parser y validador están en `forecast_kit/` para que el resto de los agentes no reimplementen el CSV.

```bash
python3 -m unittest discover -s tests -v
python3 -m forecast_kit validate fixtures/golden/mini.csv
```

Ver `AGENTS.md` (cómo testear) y `docs/PLANILLA_ESTANDAR.md` (detalle del archivo).
