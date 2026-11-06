# ForcastQA

Sistema para **identificar, corregir y descartar malos forecasts**, producto por producto, con métricas de error, perfil de demanda y recomendación de modelos.

## Cómo usarlo

```bash
npm install
npm test
npm run dev
```

Abra `http://127.0.0.1:5173`, pulse **Cargar muestra** o suba un CSV.

### Columnas

Obligatorias: `producto` (o `sku`), `fecha`, `forecast` (o `pronostico` / `prediccion` / `yhat`).

Opcionales: `nombre`, `real`, `modelo`, `ubicacion`, `canal`, `horizonte`, `lower`, `upper`.

Separador: coma, punto y coma o tab. Fechas ISO, `DD/MM/AAAA` o serial Excel. Decimales `1234.56` o `1.234,56`.

La muestra está en `public/sample-forecast.csv` (ocho productos con defectos plantados).

### Qué hace

1. Parsea el archivo y mapea alias en español e inglés.
2. Calcula MAE, RMSE, MAPE, sMAPE, WAPE, MdAPE, ME, MPE, sesgo de volumen, tracking signal, MASE, RMSSE, R², correlación, Theil U, hit rate, cobertura de intervalo, pinball 50, P90 del error.
3. Detecta negativos, duplicados, huecos, constante, ceros, picos, cambio de escala, sesgo, MAPE/WAPE altos, tendencia explosiva, intermitencia mal modelada, intervalos rotos.
4. Corrige (recorte a 0, winsor, interpolación de huecos, rescala de sesgo) o descarta (escala ×N, duplicados, no numérico, explosión, serie corta).
5. Clasifica la demanda (smooth / erratic / intermittent / lumpy) y ordena modelos: naive, SES, Holt, Holt-Winters, ETS, Croston, TSB, SBA, ARIMA, TBATS, Theta, Prophet, LightGBM, XGBoost, N-BEATS, NHITS, TFT, Chronos, TimesFM, MinT.

Baje `forecast-limpio.csv` y `forecast-descartado.csv` para operación.
