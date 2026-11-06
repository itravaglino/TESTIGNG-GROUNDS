# Planilla estándar de forecast

Esta es la planilla que usan los modelos para probar un forecast de unidades sin volver a interpretar el archivo. El escenario es `test4` (Mann). La copia canónica está en `fixtures/Forecast_mann_scenario_test4_unidades.csv`.

## Qué es cada mes

La historia llega hasta **octubre 2026**. El pronóstico es **noviembre 2026 a diciembre 2027** (14 meses). Son 4402 productos y 132 meses, de enero 2017 a diciembre 2027.

El archivo original usa **cp1252**, separador **`;`**, decimales con **coma** y fin de línea CRLF. No lo conviertas a UTF-8 antes de leerlo: hay bytes que no son UTF-8.

## Cómo probar

Desde la raíz del repo, sin dependencias:

```bash
python3 -m planilla verify
python3 -m planilla show WL7413
python3 -m planilla compare ruta/a/otra_planilla.csv
python3 -m unittest discover -s tests -v
```

`verify` revisa la planilla estándar. Sale con código 1 si se rompe el contrato.

`compare` cruza otra salida por `product_id` (o por `SKU` si no hay id). Acepta `;` o `,`, decimales con coma o punto, y UTF-8 o cp1252. Mide el error absoluto medio del horizonte de pronóstico contra esta planilla.

`show` imprime la ficha de un SKU: últimos tres meses reales y los 14 de pronóstico.

## Campos que cierran con la historia

Con corte en octubre 2026, y dejando afuera los casos cuyo denominador es cero:

| Campo | Definición | Cierre |
| --- | --- | --- |
| MTD | octubre 2026 contra octubre 2025 | 1683/1698 dentro de 1 punto |
| FYTD | enero–octubre 2026 contra enero–octubre 2025 | 3278/3324 |
| YTD | 12 meses móviles a octubre 2026 contra los 12 anteriores | 3321/3373 |
| MTG | pronóstico de noviembre 2026 contra noviembre 2025 | 1926/1926 |
| Desviacion Std | desvío poblacional de noviembre 2025 a octubre 2026 | las 4402 filas |
| Promedio | media de esa misma ventana | 30 filas se alejan más de 1 unidad |
| Coeficiente | desvío / promedio, redondeado a 2 decimales | 2 filas no cierran |

Los porcentajes de la planilla están redondeados a entero. La tolerancia de 1 punto absorbe ese redondeo.

QTD, YTG, QTG y FYTG quedan como campos del escenario: no salen de un año contra año simple.

## Lo que la verificación deja como aviso

- `Familia` está vacía. Precio y costo están en cero. `Reemplazado?` es `No`, `Reemplazado por` es `N/A` y `Descontinuado?` es `No`.
- 834 filas tienen algún mes histórico negativo. El pronóstico no tiene negativos.
- 1562 filas repiten el mismo entero los 14 meses de pronóstico.
- `Categoria` mezcla `Pick up` y `PICK UP`. Hay 22 filas con `Region` `BLOQUEADO`.
- Ocho textos traen bytes cp1252 que no forman una palabra acentuada válida (`HidrA¡ulico`, `HabitA¡culo`, `elAƒA©ctrico`). Se conservan como vinieron.

`product_id` y `SKU` son únicos. Los modelos de la columna `Modelo` son `auto_SARIMA`, `holtsWintersExponentialSmoothing` y `prophet`.
