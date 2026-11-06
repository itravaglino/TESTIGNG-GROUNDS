# TESTIGNG-GROUNDS

Harness para testear y desarrollar el auditor de forecasts sobre la planilla estándar.

## Planilla

Contrato: [`contracts/PLANILLA.md`](contracts/PLANILLA.md).
Sample rápido: [`fixtures/samples/stratified.csv`](fixtures/samples/stratified.csv).

```bash
python3 -m planilla.cli validate fixtures/samples/stratified.csv
python3 -m planilla.cli profile fixtures/samples/stratified.csv
python3 -m unittest discover -s tests -v
```

El CSV completo de producción no está en git (datos comerciales, 2.3 MB).
El perfil agregado sí: `contracts/profile.json`.
