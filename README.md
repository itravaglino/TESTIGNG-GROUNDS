# Planilla estándar de verificación

Esta es la planilla que usan los modelos para testear pronósticos de unidades. El archivo de origen es el escenario `Forecast_mann_scenario_test4` (export ancho, separador `;`, coma decimal, Windows-1252). En el repo queda en UTF-8, sin cambiar ni un número.

## Qué cubre

| | |
|---|---|
| Filas | 4.402 productos, `product_id` y `SKU` únicos |
| Columnas fijas | 30 (identidad, ABC, cluster, modelo, variaciones) |
| Meses | 132, del `01/01/2017` al `01/12/2027`, sin huecos |
| Historia | `01/01/2017` a `01/10/2026` (puede traer negativos) |
| Pronóstico a contrastar | `01/11/2026` a `01/12/2027` (14 meses, ninguno negativo) |

`Desviacion Std` es la desviación poblacional (N = 12) de nov-2025 a oct-2026. `Modelo` es `auto_SARIMA`, `holtsWintersExponentialSmoothing` o `prophet`. En este extracto `Familia` viene vacía, precio y costo en 0, y nada está reemplazado ni descontinuado.

La muestra `fixtures/planilla_estandar_muestra.csv` trae las mismas columnas y unos pocos SKU (un caso de cada modelo, tipo de demanda, cluster, ABC, región y algún negativo). Sirve para pruebas rápidas. El contrato de verdad es el archivo completo.

## Verificar

```bash
python scripts/verificar_planilla.py fixtures/planilla_estandar.csv --larga
python scripts/verificar_planilla.py --contra fixtures/planilla_estandar.csv candidato.csv
python scripts/verificar_planilla.py --largo --solo-pronostico -o /tmp/pronostico.csv fixtures/planilla_estandar_muestra.csv
python -m pip install pytest && pytest
```

`candidato.csv` puede ser la misma planilla ancha o un CSV largo con `SKU` (o `product_id`), `fecha` y `pronostico`/`unidades`. El comparador cruza solo el horizonte nov-2026 a dic-2027 y reporta MAE, sesgo y WAPE. Sale con código 1 si algún punto se aleja más de 0,01 de la planilla.

Un candidato parcial (la muestra, un solo modelo) no falla por los SKU que no trae: el informe dice cuántos quedaron sin comparar. Sí falla si inventa un SKU o mueve un mes.
