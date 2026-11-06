# Auditor de Forecasts

Revisa un pronóstico de demanda **producto por producto**: calcula el error, marca qué forecast mantener, cuál corregir y cuál descartar, y recomienda el modelo que corresponde a esa serie.

El archivo de ejemplo trae ocho productos semanales, de enero a abril de 2026, con un caso distinto cada uno: un forecast sano, sesgo, serie plana, negativos, demanda intermitente, copia del real, escala corrida y un pico imposible.

## Cómo usarlo

```bash
python3 -m pip install -r requirements.txt
python3 -m uvicorn auditor.server:app --host 127.0.0.1 --port 8765
```

Abrí `http://127.0.0.1:8765`, cargá el ejemplo o arrastrá un CSV. El separador puede ser coma, punto y coma o tab. Los encabezados pueden estar en español o en inglés (`SKU`, `Pronóstico`, `Venta Real`, `Fecha`, y también `producto`, `forecast`, `actual`).

Desde la consola:

```bash
python3 -m auditor fixtures/forecasts_largo.csv --salida salida_auditor
```

Eso escribe `dictamen.csv` y `forecast_corregido.csv`. En el corregido, un producto descartado queda con la celda vacía: no se inventa un número usable.

## Qué decide

| Dictamen | Cuándo |
|---|---|
| MANTENER | El error, el sesgo y la escala están en banda. |
| CORREGIR | Hay una corrección segura: negativos a cero, un pico imposible, sesgo de nivel, o una demanda intermitente pronosticada como serie suave (pasa al nivel de Croston). |
| DESCARTAR | El forecast copia la venta, está en otra escala (fuera de 0,2× a 5×), está plano contra una demanda que se mueve, o el error es alto y no hay un arreglo seguro. |

La métrica que manda es el **WAPE** (error absoluto sobre el volumen). El MAPE no decide cuando hay ceros. El sesgo positivo quiere decir que el forecast se pasa de la venta.

## Modelos

Por producto elige entre naive, naive estacional, media, media móvil, drift, Holt, Holt-Winters aditivo, Theta, Croston, Croston SBA y TSB. Esos sí se ajustan y se proyectan ocho periodos. SARIMA, Prophet y un modelo global (LightGBM, una red) se recomiendan cuando la historia lo justifica, y no se entrenan acá.

## Pruebas

```bash
python3 -m pytest
```

## Columnas que entiende

Obligatorias en formato largo: producto (o SKU) y fecha y pronóstico. La venta real es opcional: sin ella no hay error, solo una revisión de la forma del forecast. También acepta modelo, familia o categoría, canal o tienda, y límites inferior y superior. Si en vez de una columna fecha hay muchas columnas con fechas en el encabezado, el archivo ancho se convierte a largo.
