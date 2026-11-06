# TESTIGNG-GROUNDS — auditor de pronósticos Mann

Planilla estándar (unidades, escenario test4) versionada en `fixtures/mann/`.

## Desarrollo rápido

```bash
python -m pytest
python -m forecast_qa fixtures/mann/mann_mini.csv
```

Leé `AGENTS.md` antes de cambiar el parser o inventar datos.

## Layout

- `forecast_qa/` — parser Mann, split histórico/forecast, métricas, diagnóstico mínimo, CLI
- `fixtures/mann/` — CSV real completo + mini de 12 SKUs
- `fixtures/golden/` — anclas numéricas de MAE/WAPE
- `tests/` — contrato: si esto se rompe, el resto de modelos está testeando el archivo equivocado
