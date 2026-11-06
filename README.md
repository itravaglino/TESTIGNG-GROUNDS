# Forecast QA

Auditor de pronósticos de demanda, producto por producto.

## Qué hace

1. Lee un CSV (coma, punto y coma o tab) con columnas en español o inglés.
2. Detecta problemas: negativos, huecos, picos, escala (cajas vs unidades), sesgo, estacionalidad ignorada, historia corta, ceros, intervalos invertidos.
3. Corrige lo reparable (clip, interpolación, winsor, sesgo, redondeo) y **descarta** lo inoperable.
4. Calcula métricas (WAPE, sMAPE, MAPE, MAE, RMSE, MASE, RMSSE, bias, tracking signal, Theil U, hit rate, ADI, CV², clase Syntetos-Boylan, …).
5. Recomienda modelos (SES, Holt-Winters, Croston/SBA/TSB, SARIMA, Prophet, LightGBM, análogos, …) con librerías e hiperparámetros de partida.

## Formato de entrada

Obligatorio:

| Rol | Nombres aceptados |
| --- | --- |
| producto | `sku`, `producto`, `product_id`, `codigo`, `item` |
| fecha | `fecha`, `date`, `semana`, `period`, `YYYY-MM-DD`, `DD/MM/YYYY`, `YYYY-Www` |
| pronóstico | `pronostico`, `forecast`, `yhat`, `fcst` |

Opcional: `nombre`, `ventas`/`actual`, `deposito`/`tienda`, `modelo`, `precio`, `lower`, `upper`.

Ejemplo:

```csv
sku,nombre,fecha,pronostico,ventas,deposito
SKU-LECHE-1L,Leche entera 1L,2025-01-06,220,215,CABA
```

## Uso

```bash
npm install
npm test
npm run dev
```

En la UI: cargar CSV o **Cargar ejemplo**, revisar la tabla, abrir un SKU, descargar `forecast_corregido.csv`, `forecast_descartes.csv` y `forecast_modelos.csv`.

Los datos no salen del navegador.
