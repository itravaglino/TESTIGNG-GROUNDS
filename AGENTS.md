# Guía para otros modelos (TESTIGNG-GROUNDS)

Objetivo: un auditor de forecasts sobre la **planilla estándar Mann/Wix**.
Este repo arranca vacío; no reinventar el CSV.

## Empezar acá

1. Leer `contracts/PLANILLA.md` (formato, vocabularios, corte historia/forecast).
2. Usar `fixtures/samples/stratified.csv` (20 filas reales) en vez del CSV de 4402 SKUs.
3. Verificar con:

```bash
python3 -m planilla.cli validate fixtures/samples/stratified.csv
python3 -m unittest discover -s tests -v
```

4. Perfil del vintage completo (conteos, SHA): `contracts/profile.json`.

## Contratos que no hay que romper

- Delimitador `;`, decimal `,`, encoding `cp1252`.
- Columna `Modelo` usa `holtsWintersExponentialSmoothing` (typo original).
- Forecast = 14 meses desde `2026-11-01` en este vintage.
- Negativos en historia son válidos.
- `PICK UP` vs `Pick up` se normaliza después del parse, no se rechaza.

## Módulos recomendados (trabajo en paralelo)

| Área | Consumir de |
| --- | --- |
| Parser | `planilla.parse.parse_csv` |
| Vocabularios | `planilla.schema` |
| Tests de aceptación del CSV | `tests/test_parse_and_validate.py` |
| Fixtures rotos | `fixtures/invalid/` |

Si un parser propio no carga `722344` / SKU `WL7413` / oct-2026 `6670` / nov-2026 `8415,25`, está mal el encoding o el decimal.
