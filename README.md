# Revisión de pronósticos

Aplicación para **identificar, corregir y descartar** pronósticos de demanda malos, producto por producto. Calcula métricas de error y sesgo, recomienda modelos (SES, Holt, Holt-Winters, SBA/Croston/TSB, ingenuo estacional, análogos, etc.) y explica cómo mejorar cada serie.

## Cómo usarla

1. `npm install` y `npm run dev`
2. Cargue un CSV, péguelo, o pulse **Cargar portafolio de ejemplo**
3. Revise salud del portafolio, veredictos (mantener / revisar / descartar) y el detalle de cada SKU
4. Exporte `veredictos.csv` o JSON

## Formato de entrada

Se reconocen encabezados en español e inglés, separador `,` `;` o tab, decimales `1.234,56` o `1,234.56`, fechas `DD/MM/AAAA`, `AAAA-MM` o `AAAAMM`.

Columnas típicas:

- producto: `sku`, `codigo`, `producto`
- tiempo: `fecha`, `periodo`, o meses en columnas (formato ancho)
- medidas: `pronostico` / `forecast`, `real` / `actual` / `ventas`
- opcional: `modelo`, `lo`, `hi`, familia, canal

Plantillas en `public/samples/`.

## Qué hace el motor

- Calidad: negativos, duplicados, fugas (pronóstico = real), series cortas, outliers, intermitencia (ADI/CV²), tendencia, descontinuados
- Corrección: recorte a cero, deduplicado, winsorizado, relleno de huecos cortos (sin pisar el original)
- Métricas: MAE, RMSE, MAPE, sMAPE, WAPE, MASE, RMSSE, sesgo, tracking signal, Theil U2, R², correlación, fill rate, y más
- Modelos según clase Syntetos–Boylan y estacionalidad/tendencia
- Nota de salud 0–100 ponderada por volumen

## Pruebas

`npm test` — fixtures de oro (estacional, intermitente, negativos, fuga, tendencia, duplicados, locale europeo, ancho, SKU nuevo, outlier, dos modelos, descontinuado).
